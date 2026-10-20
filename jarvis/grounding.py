"""JARVIS v2 — vision grounding cascade (Team 18 steal #1).

The zoom cascade around an INJECTED grounder, from the Team 18 mega-scan
(~/workspace/jarvis-knowledge/megascan/team18-vision.md): on ScreenSpot-Pro,
GUI-AIMA-3B's two-step zoom (53.8 -> 61.5) beats a 72B single-pass grounder
(34.5). Procedure > parameters. And the report's single most important
number: the field's best first-look grounding is still wrong ~40% of the
time — so NO vision point is clickable until a verifier has looked at the
refined crop and said yes. That law is enforced here, in code:

  ground() runs: full-view ground -> crop (default 3.5x) around the point
  -> re-ground inside the crop -> project back to full-image pixels ->
  verifier gate. GroundResult.clickable is True ONLY when a point was
  found, refined, AND verified. No verifier configured == unverified ==
  not clickable (fail-closed). UIA targets never pass through here — they
  carry their own identity and are exempt by design (see pc_control).

The grounder/verifier are callables, not models: this module is pure
stdlib orchestration and knows nothing about VLMs, screenshots, or disks.

  grounder(crop_box | None, query) -> (x, y, confidence) | None
      Coordinates are NORMALIZED (0..1) within the given view: the full
      image when crop_box is None, the crop when a box is passed.
      A production grounder closes over the RAM-only screenshot (and, for
      the crop call, the cropped region) plus its model client.
  verifier(crop_box, query) -> bool
      "Is the thing in this crop actually <query>?" — a second, closer
      look (GUI-Actor's verifier pattern). Any exception = not verified.

Every step's numbers land on GroundResult.steps (the audit trail), so a
proposed point can always be traced: coarse -> crop -> refined -> final.

Capture discipline (Team 8 steal #2, trycua/cua's one-use capture_id):
every result carries a `capture_id` minted at observation time, bound to
the image size it was minted for. A click must present the capture_id of
the observation that produced its point — a point derived from a stale
or foreign observation must never authorize an action. `assert_fresh()`
below is the mechanical check. WIRING NOTE for the pc round (deliberately
NOT done here): PCController.click_grounded should call
`grounding.assert_fresh(result, image_size=<live frame size>)` BEFORE
backend.click_at, and burn each capture_id after one click (one-use).

DVOC refinement (Team 8 steal #1, Pomilon DVOC, PAPER.md): `refine()`
wraps the cascade in a closed kinematic loop — instead of asking the
model "where is the target?" again (absolute re-prediction: 17% in their
ablation), an injected offsetter is shown the current estimate and asks
"how far off is the marker?" via relative offsets (83%). Corrections are
applied under DVOC's exponential damping; the loop converges, oscillates,
or gives up — and only a converged loop moves the point. A non-converged
refine keeps the cascade point, honestly flagged in `dvoc_outcome`.
"""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Callable, Optional, Sequence

# (crop_box | None, query) -> (nx, ny, confidence) normalized in the view.
Grounder = Callable[[Optional[tuple], str], Optional[Sequence[float]]]
# (crop_box, query) -> "yes, that crop is the target".
Verifier = Callable[[tuple, str], bool]

DEFAULT_ZOOM = 3.5

REASON_VERIFIED = "verified"
REASON_UNVERIFIED = "unverified"
REASON_NOT_FOUND = "not_found"
REASON_REFINEMENT_FAILED = "refinement_failed"
REASON_GROUNDER_ERROR = "grounder_error"


class StaleCaptureError(ValueError):
    """A click was proposed from an observation that is stale (minted
    for a different image size) or foreign (its capture_id was not
    minted by this process's ground()/refine()). Fail-closed: acting on
    an old screen is how agents click the wrong window."""


# Every capture_id minted in this process. One short string per ground()
# call — negligible memory for a desktop session, and it makes "foreign"
# a mechanical fact instead of a format guess: an id from another
# process, another run, or a hand-written dict is simply not in the set.
_MINTED_CAPTURES: set[str] = set()
_CAPTURE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _mint_capture_id() -> str:
    """Mint + register a one-observation capture_id (uuid4 hex)."""
    cid = uuid.uuid4().hex
    _MINTED_CAPTURES.add(cid)
    return cid


@dataclass(frozen=True)
class GroundResult:
    """One cascade run, fully audited. `clickable` is the ONLY field a
    click path may trust; everything else is evidence."""
    query: str
    image_size: tuple[int, int]
    found: bool
    coarse: Optional[tuple[float, float]] = None        # normalized, full view
    coarse_pixel: Optional[tuple[float, float]] = None  # pixels, full image
    crop_box: Optional[tuple[int, int, int, int]] = None  # x, y, w, h pixels
    refined: Optional[tuple[float, float]] = None       # normalized, in crop
    point: Optional[tuple[int, int]] = None             # final pixels
    point_exact: Optional[tuple[float, float]] = None   # pre-rounding floats
    confidence: Optional[float] = None                  # refined confidence
    verified: bool = False
    clickable: bool = False
    reason: str = REASON_NOT_FOUND
    steps: tuple = field(default_factory=tuple)         # audit trail (dicts)
    # Observation binding (cua capture_id): minted by construction, so
    # EVERY result carries the id of the observation that produced it.
    capture_id: str = field(default_factory=_mint_capture_id)
    refined_dvoc: bool = False          # True only if refine() converged
    dvoc_outcome: str = ""              # "" = refine() never ran

    def to_dict(self) -> dict:
        """Plain-dict form for tool results / session logs (JSON-safe)."""
        return {
            "query": self.query,
            "image_size": list(self.image_size),
            "found": self.found,
            "coarse": list(self.coarse) if self.coarse else None,
            "coarse_pixel": (list(self.coarse_pixel)
                             if self.coarse_pixel else None),
            "crop_box": list(self.crop_box) if self.crop_box else None,
            "refined": list(self.refined) if self.refined else None,
            "point": list(self.point) if self.point else None,
            "confidence": self.confidence,
            "verified": self.verified,
            "clickable": self.clickable,
            "reason": self.reason,
            "capture_id": self.capture_id,
            "refined_dvoc": self.refined_dvoc,
            "dvoc_outcome": self.dvoc_outcome,
            "steps": [dict(s) for s in self.steps],
        }


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def _coerce(raw) -> tuple[float, float, float, bool]:
    """Validate a grounder return: (nx, ny, confidence), clamped to 0..1.

    Returns (nx, ny, confidence, was_clamped). Malformed output raises
    ValueError — the caller records it and fails closed; a grounder that
    emits garbage must never become a click.
    """
    if raw is None:
        raise ValueError("grounder returned None")
    try:
        nx, ny, conf = float(raw[0]), float(raw[1]), float(raw[2])
    except (TypeError, ValueError, IndexError, KeyError) as exc:
        raise ValueError(f"malformed grounder output: {raw!r}") from exc
    cx, cy, cc = _clamp01(nx), _clamp01(ny), _clamp01(conf)
    return cx, cy, cc, (cx, cy, cc) != (nx, ny, conf)


def crop_box_for(image_size: tuple[int, int],
                 center_pixel: tuple[float, float],
                 zoom: float = DEFAULT_ZOOM) -> tuple[int, int, int, int]:
    """The step-2 crop: a (W/zoom x H/zoom) box centered on the point,
    clamped inside the image. Returns (x, y, w, h) in pixels."""
    width, height = image_size
    if zoom <= 0:
        raise ValueError("zoom must be positive")
    cw = min(width, max(1, int(round(width / zoom))))
    ch = min(height, max(1, int(round(height / zoom))))
    cx, cy = center_pixel
    x0 = int(round(cx - cw / 2))
    y0 = int(round(cy - ch / 2))
    x0 = max(0, min(x0, width - cw))
    y0 = max(0, min(y0, height - ch))
    return (x0, y0, cw, ch)


def project(crop_box: tuple[int, int, int, int],
            normalized: tuple[float, float]) -> tuple[float, float]:
    """Step 4: crop-normalized coords -> exact full-image pixel floats."""
    x0, y0, cw, ch = crop_box
    return (x0 + normalized[0] * cw, y0 + normalized[1] * ch)


def ground(image_size: tuple[int, int], query: str, grounder: Grounder,
           verifier: Optional[Verifier] = None, *,
           zoom: float = DEFAULT_ZOOM) -> GroundResult:
    """Run the zoom cascade. Never raises for grounder/verifier failures —
    they are recorded in the audit trail and the result fails closed."""
    width, height = int(image_size[0]), int(image_size[1])
    if width <= 0 or height <= 0:
        raise ValueError(f"image_size must be positive, got {image_size!r}")
    if grounder is None:
        raise ValueError("ground() requires a grounder callable")
    size = (width, height)
    steps: list[dict] = []

    # -- step 1: full-view ground ------------------------------------------ #
    try:
        raw = grounder(None, query)
    except Exception as exc:
        steps.append({"step": 1, "action": "ground_full", "view": None,
                      "error": f"{type(exc).__name__}: {exc}"})
        return GroundResult(query=query, image_size=size, found=False,
                            reason=REASON_GROUNDER_ERROR,
                            steps=tuple(steps))
    if raw is None:
        steps.append({"step": 1, "action": "ground_full", "view": None,
                      "result": None})
        return GroundResult(query=query, image_size=size, found=False,
                            reason=REASON_NOT_FOUND, steps=tuple(steps))
    try:
        nx, ny, conf1, clamped1 = _coerce(raw)
    except ValueError as exc:
        steps.append({"step": 1, "action": "ground_full", "view": None,
                      "error": str(exc)})
        return GroundResult(query=query, image_size=size, found=False,
                            reason=REASON_GROUNDER_ERROR,
                            steps=tuple(steps))
    coarse = (nx, ny)
    coarse_pixel = (nx * width, ny * height)
    rec1: dict = {"step": 1, "action": "ground_full", "view": None,
                  "normalized": [nx, ny], "confidence": conf1,
                  "pixel": [coarse_pixel[0], coarse_pixel[1]]}
    if clamped1:
        rec1["clamped"] = True
    steps.append(rec1)

    # -- step 2: crop around the coarse point ------------------------------- #
    box = crop_box_for(size, coarse_pixel, zoom)
    steps.append({"step": 2, "action": "crop",
                  "crop_box": list(box), "zoom": zoom})

    # -- step 3: re-ground inside the crop ---------------------------------- #
    try:
        raw2 = grounder(box, query)
    except Exception as exc:
        steps.append({"step": 3, "action": "ground_crop",
                      "view": list(box),
                      "error": f"{type(exc).__name__}: {exc}"})
        return GroundResult(
            query=query, image_size=size, found=True, coarse=coarse,
            coarse_pixel=coarse_pixel, crop_box=box,
            point=(int(round(coarse_pixel[0])), int(round(coarse_pixel[1]))),
            point_exact=coarse_pixel, confidence=conf1,
            reason=REASON_REFINEMENT_FAILED, steps=tuple(steps))
    if raw2 is None:
        steps.append({"step": 3, "action": "ground_crop",
                      "view": list(box), "result": None})
        return GroundResult(
            query=query, image_size=size, found=True, coarse=coarse,
            coarse_pixel=coarse_pixel, crop_box=box,
            point=(int(round(coarse_pixel[0])), int(round(coarse_pixel[1]))),
            point_exact=coarse_pixel, confidence=conf1,
            reason=REASON_REFINEMENT_FAILED, steps=tuple(steps))
    try:
        rx, ry, conf2, clamped2 = _coerce(raw2)
    except ValueError as exc:
        steps.append({"step": 3, "action": "ground_crop",
                      "view": list(box), "error": str(exc)})
        return GroundResult(
            query=query, image_size=size, found=True, coarse=coarse,
            coarse_pixel=coarse_pixel, crop_box=box,
            point=(int(round(coarse_pixel[0])), int(round(coarse_pixel[1]))),
            point_exact=coarse_pixel, confidence=conf1,
            reason=REASON_REFINEMENT_FAILED, steps=tuple(steps))
    refined = (rx, ry)
    rec3: dict = {"step": 3, "action": "ground_crop", "view": list(box),
                  "normalized": [rx, ry], "confidence": conf2}
    if clamped2:
        rec3["clamped"] = True
    steps.append(rec3)

    # -- step 4: project back to full-image pixels --------------------------- #
    exact = project(box, refined)
    point = (int(round(exact[0])), int(round(exact[1])))
    steps.append({"step": 4, "action": "project",
                  "point_exact": [exact[0], exact[1]], "point": list(point)})

    # -- verifier gate: no verified crop, no click --------------------------- #
    if verifier is None:
        steps.append({"step": 5, "action": "verify", "verifier": "absent",
                      "verified": False})
        return GroundResult(
            query=query, image_size=size, found=True, coarse=coarse,
            coarse_pixel=coarse_pixel, crop_box=box, refined=refined,
            point=point, point_exact=exact, confidence=conf2,
            verified=False, clickable=False, reason=REASON_UNVERIFIED,
            steps=tuple(steps))
    try:
        ok = bool(verifier(box, query))
    except Exception as exc:
        steps.append({"step": 5, "action": "verify", "verifier": "provided",
                      "verified": False,
                      "error": f"{type(exc).__name__}: {exc}"})
        return GroundResult(
            query=query, image_size=size, found=True, coarse=coarse,
            coarse_pixel=coarse_pixel, crop_box=box, refined=refined,
            point=point, point_exact=exact, confidence=conf2,
            verified=False, clickable=False, reason=REASON_UNVERIFIED,
            steps=tuple(steps))
    steps.append({"step": 5, "action": "verify", "verifier": "provided",
                  "verified": ok})
    return GroundResult(
        query=query, image_size=size, found=True, coarse=coarse,
        coarse_pixel=coarse_pixel, crop_box=box, refined=refined,
        point=point, point_exact=exact, confidence=conf2,
        verified=ok, clickable=ok,
        reason=REASON_VERIFIED if ok else REASON_UNVERIFIED,
        steps=tuple(steps))


# --------------------------------------------------------------------------- #
# Capture freshness — the mechanical stale/foreign check (cua discipline)
# --------------------------------------------------------------------------- #

def assert_fresh(result, *, image_size: tuple[int, int]) -> str:
    """Verify a result still belongs to the CURRENT observation frame.

    Accepts a GroundResult or its dict form (to_dict()). Returns the
    result's capture_id when the observation is fresh. Raises
    StaleCaptureError when:
      * there is no capture_id (not an observation product at all),
      * the capture_id is malformed or was NOT minted by this process
        (foreign — another run, another process, a hand-written dict),
      * the image size it was minted for differs from `image_size`
        (stale — the screen changed shape since the observation).
    A click path calls this with the live frame's size before acting;
    one-use burning of the id after a click is the pc round's wiring.
    """
    if isinstance(result, GroundResult):
        cid, size = result.capture_id, result.image_size
    elif isinstance(result, Mapping):
        cid, size = result.get("capture_id"), result.get("image_size")
    else:
        raise StaleCaptureError(
            f"assert_fresh needs a GroundResult or its dict form, got "
            f"{type(result).__name__}")
    if not cid:
        raise StaleCaptureError(
            "no capture_id: this result was not minted by ground() — "
            "an unobserved point may not authorize a click")
    if not _CAPTURE_ID_RE.match(str(cid)) or cid not in _MINTED_CAPTURES:
        raise StaleCaptureError(
            f"foreign capture_id {cid!r}: not minted by this process's "
            f"ground()/refine() — re-observe before acting")
    want = (int(image_size[0]), int(image_size[1]))
    if size is None or tuple(int(v) for v in size) != want:
        raise StaleCaptureError(
            f"stale capture {cid}: minted for image size {size!r}, "
            f"current frame is {want!r} — re-observe before acting")
    return str(cid)


# --------------------------------------------------------------------------- #
# DVOC — iterative relative-offset refinement (Team 8, Pomilon DVOC)
# --------------------------------------------------------------------------- #

# (current_point_px, crop_box) -> (dx_px, dy_px, confidence) | None.
# The production offsetter renders a crosshair at the current point on
# the crop and asks the VLM "how far off is the marker?" (DVOC's
# report_offset); here it is an injected callable so the loop stays pure
# orchestration. Offsets are FULL-IMAGE PIXELS relative to the point:
# positive dx = the target sits right of the marker.
Offsetter = Callable[[tuple, tuple], Optional[Sequence[float]]]

#: DVOC damping schedule (PAPER.md): alpha(0)=1.0, alpha(1)=0.5,
#: alpha(>=2)=0.25 — early corrections are trusted, later ones are
#: increasingly gentle so the loop settles instead of orbiting.
_DVOC_ALPHAS = (1.0, 0.5, 0.25)

DVOC_CONVERGED = "converged"
DVOC_NOT_CONVERGED = "not_converged"
DVOC_OSCILLATING = "oscillating"
DVOC_OFFSETTER_ERROR = "offsetter_error"
DVOC_NO_POINT = "no_point"

DEFAULT_EPSILON_PX = 30.0   # DVOC's epsilon (their ACT_SAFE threshold)
DEFAULT_MAX_ROUNDS = 4


def _coerce_offset(raw) -> tuple[float, float, float, bool]:
    """Validate an offsetter return: (dx_px, dy_px, confidence).

    Offsets are pixels — NOT clamped to 0..1 (they may be negative or
    large); they must be finite. Confidence is clamped to 0..1.
    Malformed output raises ValueError: a grounder that emits garbage
    must never move a click point.
    """
    if raw is None:
        raise ValueError("offsetter returned None")
    try:
        dx, dy, conf = float(raw[0]), float(raw[1]), float(raw[2])
    except (TypeError, ValueError, IndexError, KeyError) as exc:
        raise ValueError(f"malformed offsetter output: {raw!r}") from exc
    if not (math.isfinite(dx) and math.isfinite(dy)
            and math.isfinite(conf)):
        raise ValueError(f"non-finite offsetter output: {raw!r}")
    cc = _clamp01(conf)
    return dx, dy, cc, cc != conf


def refine(image_size: tuple[int, int], query: str, grounder: Grounder,
           offsetter: Offsetter, verifier: Optional[Verifier] = None, *,
           zoom: float = DEFAULT_ZOOM, max_rounds: int = DEFAULT_MAX_ROUNDS,
           epsilon_px: float = DEFAULT_EPSILON_PX) -> GroundResult:
    """Run the cascade, then refine its point with the DVOC loop.

    Each round the offsetter sees the CURRENT point (full-image pixel
    floats) and the cascade's crop box, and reports a relative offset.
    The correction is applied under DVOC damping. Stop rules:

      * CONVERGED — two consecutive reported offsets with magnitude
        below `epsilon_px`. Only then does the point move:
        `refined_dvoc=True`, `dvoc_outcome="converged"`.
      * OSCILLATING — an offset flips sign on an axis while its
        magnitude GROWS vs the previous round: the marker is orbiting
        the target; abort immediately.
      * NOT CONVERGED / OFFSETTER ERROR — rounds exhausted, or the
        offsetter raised / returned None / emitted garbage.

    Every non-converged outcome KEEPS THE CASCADE POINT — a failed
    refinement never silently substitutes its own guess. The verifier
    gate is untouched: refinement moves the point within the verified
    crop's neighbourhood, it cannot mint clickability (an unverified
    cascade result stays unclickable no matter how well DVOC settles).
    The capture_id carries over: the refined point derives from the
    same observation, so the same capture authorizes it.
    """
    width, height = int(image_size[0]), int(image_size[1])
    if width <= 0 or height <= 0:
        raise ValueError(f"image_size must be positive, got {image_size!r}")
    if offsetter is None:
        raise ValueError("refine() requires an offsetter callable")
    if max_rounds < 1:
        raise ValueError(f"max_rounds must be >= 1, got {max_rounds!r}")
    if epsilon_px <= 0:
        raise ValueError(f"epsilon_px must be positive, got {epsilon_px!r}")

    base = ground(image_size, query, grounder, verifier, zoom=zoom)
    rounds: list[dict] = []
    if base.point_exact is None or base.crop_box is None:
        rounds.append({"action": "dvoc", "outcome": DVOC_NO_POINT,
                       "detail": "cascade produced no point to refine"})
        return replace(base, dvoc_outcome=DVOC_NO_POINT,
                       steps=base.steps + tuple(rounds))

    current = (float(base.point_exact[0]), float(base.point_exact[1]))
    prev: Optional[tuple[float, float]] = None
    prev_mag = 0.0
    small_streak = 0
    for i in range(max_rounds):
        alpha = _DVOC_ALPHAS[min(i, len(_DVOC_ALPHAS) - 1)]
        rec: dict = {"action": "dvoc_round", "round": i + 1,
                     "alpha": alpha,
                     "point_before": [current[0], current[1]]}
        try:
            raw = offsetter(current, base.crop_box)
            dx, dy, conf, conf_clamped = _coerce_offset(raw)
        except Exception as exc:
            rec["error"] = f"{type(exc).__name__}: {exc}"
            rec["outcome"] = DVOC_OFFSETTER_ERROR
            rounds.append(rec)
            return replace(base, dvoc_outcome=DVOC_OFFSETTER_ERROR,
                           steps=base.steps + tuple(rounds))
        mag = math.hypot(dx, dy)
        rec.update({"offset": [dx, dy], "confidence": conf,
                    "magnitude_px": mag})
        if conf_clamped:
            rec["confidence_clamped"] = True

        # Oscillation: sign flip on an axis AND growing magnitude — the
        # marker is orbiting the target, not settling on it. Abort
        # BEFORE this offset is applied.
        if prev is not None:
            flip = ((prev[0] != 0.0 and dx * prev[0] < 0.0)
                    or (prev[1] != 0.0 and dy * prev[1] < 0.0))
            if flip and mag > prev_mag:
                rec["outcome"] = DVOC_OSCILLATING
                rounds.append(rec)
                return replace(base, dvoc_outcome=DVOC_OSCILLATING,
                               steps=base.steps + tuple(rounds))

        applied = (alpha * dx, alpha * dy)
        nx = min(max(current[0] + applied[0], 0.0), float(width))
        ny = min(max(current[1] + applied[1], 0.0), float(height))
        if (nx, ny) != (current[0] + applied[0], current[1] + applied[1]):
            rec["clamped"] = True
        current = (nx, ny)
        rec["applied"] = [applied[0], applied[1]]
        rec["point_after"] = [nx, ny]
        small_streak = small_streak + 1 if mag < epsilon_px else 0
        rec["small_streak"] = small_streak
        rounds.append(rec)
        prev, prev_mag = (dx, dy), mag
        if small_streak >= 2:
            rec["outcome"] = DVOC_CONVERGED
            point = (int(round(current[0])), int(round(current[1])))
            return replace(base, point=point, point_exact=current,
                           refined_dvoc=True, dvoc_outcome=DVOC_CONVERGED,
                           steps=base.steps + tuple(rounds))
    return replace(base, dvoc_outcome=DVOC_NOT_CONVERGED,
                   steps=base.steps + tuple(rounds))
