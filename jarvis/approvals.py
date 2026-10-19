"""JARVIS v2 — Approval UX (Wave 2).

Implements learn-approval-ux-spec.md as code:
  - 7-field approval dialogs (goal, progress, action, blast radius,
    consequence, if-no, origin) — NEVER auto-expiring, never pre-checked.
  - Blast radius computed from the ACTION OBJECT in code, never from the
    brain's text (threat-model F1, P0).
  - Tiers recomputed from the surface definition, never inherited from the
    agent's label.
  - Trusted chrome: native OS MessageBox on Windows (outside any webview);
    terminal fallback elsewhere. Session visual secret in every dialog
    (anti-spoofing, B7).
  - Anti-fatigue: 5-dialog daily budget (HOLD after), burst detection
    (3 dialogs <60s -> typed confirmation), step-up ladder.
  - Tier-2: announce + real 30s undo (UndoRegistry with inverse actions).
  - Voice rule: bare "yes" is never approval — callers must use the
    say-it-back keyword path (require_typed=True); no screen -> refuse.

Python 3.11+, stdlib only. No model calls, no randomness in decisions.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# --------------------------------------------------------------------------- #
# Constants (all [PROPOSED] per spec §9 — principled, unmeasured)
# --------------------------------------------------------------------------- #

DAILY_DIALOG_BUDGET = 5          # §3.1: max tier-3 dialogs per day, then HOLD
BURST_COUNT = 3                  # §3.4: N dialogs ...
BURST_WINDOW_S = 60              # ... inside this window = burst
DWELL_STANDARD_S = 3             # §3.3: payload visible before buttons enable
DWELL_TYPED_S = 5                # §3.3: longer for typed-confirmation tier
UNDO_WINDOW_S = 30               # §2.1: tier-2 undo window
TYPED_KEYWORDS = {               # §3.2: action keyword per severity class
    "delete": "DELETE",
    "send": "SEND",
    "exec": "EXECUTE",
    "install": "INSTALL",
    "permission": "GRANT",
}

# Small built-in wordlist for the session visual secret (no external files).
_VISUAL_WORDS = (
    "copper falcon river stone ember wolf lantern tide grove spark "
    "birch comet moss quartz heron flint willow onyx lark cedar"
).split()

_CREDENTIAL_RULE = (
    "JARVIS will NEVER ask for a password or key in a dialog. "
    "If a dialog asks, it is fake — close it and report it."
)


# --------------------------------------------------------------------------- #
# Rendering safety (dugganusa.com lessons: control chars, bidi overrides)
# --------------------------------------------------------------------------- #

_BIDI = set("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u200e\u200f")


class UnsafeRender(ValueError):
    """A value cannot be rendered safely — the dialog must refuse, not guess."""


def safe_render(value: Any, max_len: int = 500) -> str:
    """Render a value for the dialog. Control characters and bidi overrides
    are refused (not silently stripped): a filename that changes meaning when
    cleaned aborts the dialog. Returns the safe string or raises UnsafeRender.
    """
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    for ch in text:
        if ch in _BIDI:
            raise UnsafeRender(f"bidi override character in {text[:40]!r}")
        if unicodedata.category(ch) == "Cc" and ch not in ("\t",):
            raise UnsafeRender(f"control character U+{ord(ch):04X} in {text[:40]!r}")
    text = text.replace("\t", " ")
    if len(text) > max_len:
        text = text[:max_len] + "…"
    return text


# --------------------------------------------------------------------------- #
# Blast radius — computed from the ACTION OBJECT, never agent text (F1 P0)
# --------------------------------------------------------------------------- #

def _cap(fs_caps: list[str], *names: str) -> bool:
    return any(c in fs_caps for c in names)


def blast_radius(args: dict, tool_info: dict) -> str:
    """Compute what breaks if this action is wrong — from the action object.
    tool_info: {name, tier, schema, capabilities, description} (from registry).
    """
    caps = list(tool_info.get("capabilities", []))
    name = str(tool_info.get("name", "unknown"))
    schema_props = (tool_info.get("schema") or {}).get("properties", {})

    # Filesystem writes: path + size + overwrite risk.
    if _cap(caps, "fs.write"):
        path = args.get("path", args.get("file", args.get("target", "?")))
        try:
            p = safe_render(path, 200)
        except UnsafeRender:
            return "UNSAFE: the target path cannot be displayed safely — refusing to estimate."
        content = args.get("content", args.get("text", args.get("data", "")))
        size = len(str(content)) if content else 0
        exists = os.path.exists(str(path)) if isinstance(path, str) and path != "?" else False
        parts = [f"Writes to `{p}`"]
        if size:
            parts.append(f"~{size} characters of new content")
        parts.append("an EXISTING file will be OVERWRITTEN" if exists
                     else "creates a new file" if path != "?" else "target unclear")
        parts.append("Recoverable via the 30s undo window (tier-2)." if tool_info.get("tier") == 2
                     else "NOT recoverable after the undo window.")
        return ". ".join(parts) + "."

    # Deletion-likes: name every target (counts-per-tier is banned).
    if _cap(caps, "fs.delete") or any(k in name.lower() for k in ("delete", "remove", "rm", "purge")):
        targets = args.get("paths", args.get("files", args.get("path", args.get("target"))))
        if isinstance(targets, str):
            targets = [targets]
        if isinstance(targets, list) and targets:
            try:
                named = [safe_render(t, 120) for t in targets[:5]]
            except UnsafeRender:
                return "UNSAFE: a target cannot be displayed safely — refusing to estimate."
            extra = f" and {len(targets) - 5} more" if len(targets) > 5 else ""
            return (f"Permanently deletes {len(targets)} item(s): "
                    + ", ".join(f"`{n}`" for n in named) + extra
                    + ". These CANNOT be recovered — no undo, no trash.")
        return "Permanently deletes the target. This CANNOT be recovered."

    # Network egress: destination + volume.
    if _cap(caps, "net.outbound"):
        dest = args.get("url", args.get("to", args.get("destination", "?")))
        try:
            d = safe_render(dest, 200)
        except UnsafeRender:
            return "UNSAFE: the destination cannot be displayed safely — refusing to estimate."
        return (f"Sends data to `{d}`. Once sent, it leaves this machine "
                f"and cannot be recalled.")

    # Code execution: the command itself.
    if _cap(caps, "exec"):
        cmd = args.get("command", args.get("cmd", args.get("code", "?")))
        try:
            c = safe_render(cmd, 300)
        except UnsafeRender:
            return "UNSAFE: the command cannot be displayed safely — refusing to estimate."
        return (f"Runs this command: `{c}`. Code can do anything the user "
                f"account can do — treat as the highest blast radius.")

    # Conservative fallback: describe from the schema, never invent.
    if schema_props:
        keys = ", ".join(f"`{k}`" for k in list(schema_props)[:6])
        return (f"Invokes `{name}` with parameters: {keys}. "
                f"No specific blast-radius model exists for this tool — "
                f"treating it as potentially state-changing.")
    return (f"Invokes `{name}`. No blast-radius model exists for this tool — "
            f"treating it as potentially state-changing.")


def needs_typed(tool_info: dict, radius: str) -> bool:
    """Severity line (§3.2): does this action require TYPED confirmation?
    Computed from the action surface, not from the brain's description."""
    name = str(tool_info.get("name", "")).lower()
    desc = str(tool_info.get("description", "")).lower()
    caps = set(tool_info.get("capabilities", []))
    if caps & {"net.outbound", "exec"}:
        return True
    for key in ("delete", "remove", "purge", "send", "install", "grant", "permission"):
        if key in name or key in desc:
            return True
    if "CANNOT be recovered" in radius or "cannot be recalled" in radius:
        return True
    return False


def typed_keyword(tool_info: dict) -> str:
    """The keyword the user must type for this severity class."""
    name = str(tool_info.get("name", "")).lower()
    desc = str(tool_info.get("description", "")).lower()
    caps = set(tool_info.get("capabilities", []))
    text = name + " " + desc
    if "exec" in caps or "exec" in text:
        return TYPED_KEYWORDS["exec"]
    for key, word in TYPED_KEYWORDS.items():
        if key in text:
            return word
    if "net.outbound" in caps:
        return TYPED_KEYWORDS["send"]
    return "CONFIRM"


# --------------------------------------------------------------------------- #
# ApprovalRequest — the 7 required fields + gate bindings
# --------------------------------------------------------------------------- #

@dataclass
class ApprovalRequest:
    # Gate bindings (from GateDecision.approval_request)
    tool: str
    args: dict
    tier: int
    action_hash: str
    token: str
    # The 7 required dialog fields (§1.1)
    goal: str = ""            # 1. "I'm trying to [your words]"
    progress: str = ""        # 2. "Done: [1], [2]"
    action_text: str = ""     # 3. exact action in plain words (computed)
    blast_radius: str = ""    # 4. computed from the action object
    consequence: str = ""     # 5. worst case, one sentence
    if_no: str = ""           # 6. safe subset offered on reject
    # Origin proof (§4.2)
    seq_no: int = 0           # 7a. user-visible sequence number
    visual_secret: str = ""   # 7b. session-bound phrase
    timestamp: str = ""       # 7c. ISO time of request
    # Derived
    require_typed: bool = False
    keyword: str = ""

    @classmethod
    def from_gate(cls, gate_request: dict, *, tool_info: dict,
                  goal: str = "", progress: str = "", if_no: str = "",
                  seq_no: int = 0, visual_secret: str = "") -> "ApprovalRequest":
        """Build from a gate's approval_request dict + caller context.
        The tier is recomputed from tool_info, never trusted from the dict."""
        tier = int(tool_info.get("tier", 3))
        radius = blast_radius(dict(gate_request.get("args", {})), tool_info)
        typed = needs_typed(tool_info, radius)
        action_text = _plain_action(str(gate_request.get("tool", "?")),
                                    dict(gate_request.get("args", {})), tool_info)
        consequence = _consequence(radius, typed)
        return cls(
            tool=str(gate_request.get("tool", "?")),
            args=dict(gate_request.get("args", {})),
            tier=tier,
            action_hash=str(gate_request.get("action_hash", "")),
            token=str(gate_request.get("token", "")),
            goal=goal, progress=progress,
            action_text=action_text, blast_radius=radius,
            consequence=consequence,
            if_no=if_no or "I'll keep the plan parked — nothing runs, nothing breaks.",
            seq_no=seq_no, visual_secret=visual_secret,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            require_typed=typed,
            keyword=typed_keyword(tool_info) if typed else "",
        )


def _plain_action(tool: str, args: dict, tool_info: dict) -> str:
    """Field 3: the exact action in plain words — from the action object."""
    try:
        name = safe_render(tool, 80)
    except UnsafeRender:
        return "UNSAFE: the tool name cannot be displayed — rejecting."
    bits = []
    for k, v in list(args.items())[:6]:
        try:
            bits.append(f"{k}={safe_render(v, 120)}")
        except UnsafeRender:
            return "UNSAFE: a parameter cannot be displayed safely — rejecting."
    params = ", ".join(bits) if bits else "no parameters"
    return f"{name}({params})"


def _consequence(radius: str, typed: bool) -> str:
    """Field 5: one sentence, worst case, plainly."""
    if "CANNOT be recovered" in radius:
        return "If this is a mistake, the data is gone permanently."
    if "cannot be recalled" in radius:
        return "If this is a mistake, the data has already left this machine."
    if "Anything the user account can do" in radius or "highest blast radius" in radius:
        return "If this is a mistake, arbitrary code just ran as you."
    if typed:
        return "If this is a mistake, the change may be hard or impossible to undo."
    return "If this is a mistake, you can undo it within 30 seconds."


# --------------------------------------------------------------------------- #
# Session visual secret + sequence numbers (origin proof, §4.2)
# --------------------------------------------------------------------------- #

class OriginProof:
    """Per-process: monotonically increasing sequence numbers + one
    session-bound 3-word visual secret. A spoofed dialog cannot know it."""

    def __init__(self, secret: Optional[str] = None) -> None:
        import random
        rng = random.SystemRandom()
        self.visual_secret = secret or " ".join(rng.choice(_VISUAL_WORDS) for _ in range(3))
        self._seq = 0

    def next(self) -> tuple[int, str]:
        self._seq += 1
        return self._seq, self.visual_secret


# --------------------------------------------------------------------------- #
# Anti-fatigue: the dialog budget (§3.1, §3.4)
# --------------------------------------------------------------------------- #

class BudgetExhausted(Exception):
    """Raised when the daily dialog budget is spent — HOLD, never auto-approve."""


class ApprovalBudget:
    """Max 5 tier-3 dialogs/day (§3.1); burst detection 3 dialogs/<60s (§3.4).
    State persists in a JSON file so the budget survives restarts."""

    def __init__(self, data_dir: str | Path,
                 now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._file = Path(data_dir) / "approval_budget.json"
        self._state = self._load()

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _load(self) -> dict:
        try:
            state = json.loads(self._file.read_text())
            if state.get("day") != self._today():
                return {"day": self._today(), "count": 0,
                        "dialog_ts": [], "approve_latencies": []}
            return state
        except (OSError, json.JSONDecodeError, ValueError):
            return {"day": self._today(), "count": 0,
                    "dialog_ts": [], "approve_latencies": []}

    def _save(self) -> None:
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state))
        os.replace(tmp, self._file)

    def check(self) -> tuple[bool, str]:
        """Pre-dialog gate. Returns (ok, reason). HOLD when exhausted."""
        if self._state["count"] >= DAILY_DIALOG_BUDGET:
            return (False,
                    f"Daily approval budget spent ({DAILY_DIALOG_BUDGET} dialogs). "
                    f"HOLDING — no more tier-3 dialogs today. The actions wait; "
                    f"nothing auto-approves.")
        return (True, "")

    def record_dialog(self) -> dict:
        """Call when a dialog is PRESENTED. Returns fatigue signals."""
        now = self._now()
        self._state["count"] += 1
        ts = self._state.setdefault("dialog_ts", [])
        ts.append(now)
        # Keep only the recent window for burst detection.
        self._state["dialog_ts"] = [t for t in ts if now - t < BURST_WINDOW_S]
        self._save()
        burst = len(self._state["dialog_ts"]) >= BURST_COUNT
        return {"burst": burst,
                "dialogs_today": self._state["count"],
                "burst_warning": (
                    "Unusual burst — 3 approval dialogs in under 60 seconds. "
                    "A skill may be misbehaving. Typed confirmation required."
                ) if burst else ""}

    def record_decision(self, latency_s: float) -> None:
        """Call after each decision — feeds the weekly fatigue mirror (§3.5)."""
        lat = self._state.setdefault("approve_latencies", [])
        lat.append(latency_s)
        self._state["approve_latencies"] = lat[-100:]
        self._save()

    def median_latency(self) -> Optional[float]:
        lat = sorted(self._state.get("approve_latencies", []))
        if not lat:
            return None
        mid = len(lat) // 2
        return lat[mid] if len(lat) % 2 else (lat[mid - 1] + lat[mid]) / 2


# --------------------------------------------------------------------------- #
# The dialog — native trusted chrome on Windows, terminal fallback
# --------------------------------------------------------------------------- #

def _render_text(req: ApprovalRequest, burst_warning: str = "") -> str:
    """The full 7-field payload as plain text. Same content on every chrome."""
    lines = [
        "JARVIS needs your approval",
        f"Action #{req.seq_no} · {req.timestamp} · phrase: {req.visual_secret}",
        "",
        f"1. GOAL: {req.goal or '(not stated)'}",
        f"2. DONE SO FAR: {req.progress or '(first step)'}",
        f"3. ACTION: {req.action_text}",
        f"4. BLAST RADIUS: {req.blast_radius}",
        f"5. IF THIS IS A MISTAKE: {req.consequence}",
        f"6. IF YOU SAY NO: {req.if_no}",
        f"7. ORIGIN: requested by JARVIS core · action #{req.seq_no} · {req.timestamp}",
    ]
    if burst_warning:
        lines.insert(2, f"!! {burst_warning}")
    if req.require_typed:
        lines.append(f"")
        lines.append(f"TYPE '{req.keyword}' TO APPROVE — a bare yes is not enough.")
    lines.append("")
    lines.append(_CREDENTIAL_RULE)
    return "\n".join(lines)


def _windows_dialog(text: str, title: str = "JARVIS needs approval") -> Optional[bool]:
    """Native MessageBox — trusted OS chrome, outside any webview (§4.1).
    Returns True (Yes) / False (No) / None (unavailable/failed).
    Limitation (documented): a raw MessageBox cannot disable its buttons, so
    the dwell rule (§3.3) is enforced in the terminal path only; the Windows
    path compensates with typed confirmation for high-severity actions."""
    if sys.platform != "win32":
        return None
    try:
        MB_YESNO = 0x04
        MB_ICONWARNING = 0x30
        MB_SYSTEMMODAL = 0x1000
        MB_TOPMOST = 0x40000
        res = ctypes.windll.user32.MessageBoxW(
            None, text, title,
            MB_YESNO | MB_ICONWARNING | MB_SYSTEMMODAL | MB_TOPMOST)
        IDYES = 6
        return res == IDYES
    except Exception:
        return None


def request_approval(req: ApprovalRequest,
                     budget: Optional[ApprovalBudget] = None,
                     input_fn: Callable[[str], str] = input,
                     sleep_fn: Callable[[float], None] = time.sleep,
                     force_terminal: bool = False) -> bool:
    """Present the approval dialog. Returns True ONLY on explicit approval.

    Anti-patterns structurally absent (there is no code path for them):
      - no timeout/auto-approve: no timer anywhere in this function
      - no pre-checked approve: the default answer is always "no"
      - no "approve all": no such option exists in any branch
    """
    # Budget first: exhausted -> HOLD, the dialog is never even built (§3.1).
    burst_warning = ""
    if budget is not None:
        ok, reason = budget.check()
        if not ok:
            print(f"[approval HOLD] {reason}")
            return False
        signals = budget.record_dialog()
        burst_warning = signals["burst_warning"]
        # Burst steps up friction: typed confirmation even for standard tier-3.
        typed = req.require_typed or signals["burst"]

    typed = req.require_typed or bool(burst_warning)
    keyword = req.keyword or "CONFIRM"
    text = _render_text(req, burst_warning)
    dwell = DWELL_TYPED_S if typed else DWELL_STANDARD_S
    t0 = time.time()

    # Windows native chrome (payload display). The typed path still decides
    # in the terminal so the gesture differs from a click (F3 clause).
    if not force_terminal and not typed:
        native = _windows_dialog(text)
        if native is not None:
            if budget is not None:
                budget.record_decision(time.time() - t0)
            return native

    # Terminal path (fallback everywhere; always for typed confirmation).
    print("=" * 64)
    print(text)
    print("=" * 64)
    # Dwell: the payload is visible BEFORE the prompt accepts input (§3.3).
    print(f"[reading time — deciding in {dwell}s…]")
    sleep_fn(dwell)
    try:
        if typed:
            answer = input_fn(f"Type {keyword} to approve (anything else rejects): ").strip()
            approved = answer == keyword  # exact match; bare "yes" never counts
        else:
            answer = input_fn("Approve? [y/N]: ").strip().lower()
            approved = answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        approved = False  # closed/aborted stdin is a rejection, never approval
    if budget is not None:
        budget.record_decision(time.time() - t0)
    return approved


# --------------------------------------------------------------------------- #
# Tier-2: announce + REAL 30s undo (§2.1)
# --------------------------------------------------------------------------- #

class UndoRegistry:
    """Holds inverse actions for tier-2 executions. Undo is a real snapshot
    restore, not decorative: register() takes the inverse callable."""

    def __init__(self, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._pend: dict[str, dict] = {}

    def register(self, undo_token: str, description: str,
                 inverse: Callable[[], Any]) -> None:
        self._pend[undo_token] = {
            "description": description,
            "inverse": inverse,
            "expires": self._now() + UNDO_WINDOW_S,
        }

    def undo(self, undo_token: str) -> tuple[bool, str]:
        rec = self._pend.get(undo_token)
        if rec is None:
            return (False, "unknown undo token")
        if self._now() > rec["expires"]:
            del self._pend[undo_token]
            return (False, "undo window expired (30s) — the change stands")
        try:
            rec["inverse"]()
        except Exception as exc:
            return (False, f"undo failed: {exc}")
        del self._pend[undo_token]
        return (True, f"undone: {rec['description']}")

    def pending(self) -> list[dict]:
        """Live undo offers (for the /undo surface and the feed)."""
        now = self._now()
        live = []
        for token, rec in list(self._pend.items()):
            if now > rec["expires"]:
                del self._pend[token]
                continue
            live.append({"token": token,
                         "description": rec["description"],
                         "seconds_left": int(rec["expires"] - now)})
        return live


def confirm_tier2(undo_token: str, description: str,
                  registry: UndoRegistry,
                  inverse: Callable[[], Any],
                  print_fn: Callable[[str], None] = print) -> None:
    """The tier-2 UX: announce + act (already done by caller) + 30s undo.
    Call AFTER the mutation with a real inverse."""
    registry.register(undo_token, description, inverse)
    print_fn(f"[done] {description}")
    print_fn(f"[undo] within 30s type: /undo {undo_token[:8]}")
