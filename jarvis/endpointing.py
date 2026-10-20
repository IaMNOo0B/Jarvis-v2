"""jarvis.endpointing — LEARNED end-of-turn silence policy (Voice Pack).

Team 7's top steal (megascan/team7-voice2.md): LiveKit's
``DynamicEndpointing`` — the silence that ends an utterance should not be
a universal constant copied from someone else's room. It is an
exponential moving average (alpha 0.9) over the OWNER's own observed
pauses:

  - Between-utterance pauses teach the average owner's rhythm.
  - A proven FALSE end-of-turn (we cut in, the owner immediately
    resumed — they were mid-thought, not finished) teaches the FLOOR
    upward: the owner provably needed at least that much silence, so
    the threshold may never sink below it again.
  - The maximum is a CLAMP, never learned ("there is no natural lower
    max to observe" — LiveKit): threshold_s lives in [0.3, 3.0] always.

This module is the policy only: pure arithmetic + atomic JSON
persistence in the data dir. The voice loop consults ``threshold_s``
where it used to read a fixed constant, and feeds observations back.
Corrupt or missing state -> seed defaults, never a crash: endpointing
must not be able to take the voice loop down with it.

Stdlib only. Python 3.11+.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

__all__ = [
    "EndpointPolicy",
    "ALPHA",
    "SEED_S",
    "MIN_THRESHOLD_S",
    "MAX_THRESHOLD_S",
    "STATE_FILENAME",
]

ALPHA = 0.9               # EMA weight on the newest observation (LiveKit)
SEED_S = 0.5              # threshold before anything is learned (LiveKit min)
MIN_THRESHOLD_S = 0.3     # hard floor: never snappier than this
MAX_THRESHOLD_S = 3.0     # hard clamp: never learned, never exceeded
STATE_FILENAME = "endpointing.json"
_STATE_VERSION = 1


def _clamp_threshold(value: float) -> float:
    return min(MAX_THRESHOLD_S, max(MIN_THRESHOLD_S, value))


class EndpointPolicy:
    """The owner's learned end-of-turn silence threshold.

    ``threshold_s`` = clamp(max(ema, floor)) — the EMA tracks the
    owner's average pause; the floor is the ratchet a proven false
    end-of-turn leaves behind. Observations are clamped into the
    threshold's own range before entering the EMA: a 30 s absence is
    not a "pause habit" and carries no extra information for a
    threshold that can never exceed 3.0 s anyway.
    """

    def __init__(self, data_dir: Optional[Path] = None,
                 seed_s: float = SEED_S) -> None:
        self._seed_s = _clamp_threshold(float(seed_s))
        self._ema_s = self._seed_s
        self._floor_s = MIN_THRESHOLD_S
        self._observations = 0
        self._data_dir = Path(data_dir) if data_dir is not None else None
        if self._data_dir is not None:
            self.load()

    # -- the number the loop ends utterances on ---------------------------- #
    @property
    def threshold_s(self) -> float:
        return _clamp_threshold(max(self._ema_s, self._floor_s))

    # -- introspection (tests, diagnostics, the owner's "why") ------------- #
    @property
    def learned_s(self) -> float:
        """The raw EMA over observed pauses (before floor/clamp)."""
        return self._ema_s

    @property
    def floor_s(self) -> float:
        """The false-EOT ratchet: threshold never sinks below this."""
        return self._floor_s

    @property
    def observations(self) -> int:
        return self._observations

    # -- learning ------------------------------------------------------------ #
    def observe_pause(self, pause_s: float) -> None:
        """A genuine pause the owner took (e.g. between utterances)."""
        p = self._sanitize(pause_s)
        if p is None:
            return
        self._ema_s = ALPHA * p + (1.0 - ALPHA) * self._ema_s
        self._observations += 1
        self.save()

    def observe_false_eot(self, needed_pause_s: float) -> None:
        """A proven false end-of-turn: we ended the utterance after
        ``threshold`` silence and the owner immediately continued —
        their real pause was ``needed_pause_s``. The EMA learns it AND
        the floor ratchets up to it: never cut this owner that early
        again."""
        p = self._sanitize(needed_pause_s)
        if p is None:
            return
        self._ema_s = ALPHA * p + (1.0 - ALPHA) * self._ema_s
        self._floor_s = max(self._floor_s, p)
        self._observations += 1
        self.save()

    @staticmethod
    def _sanitize(pause_s: float) -> Optional[float]:
        try:
            p = float(pause_s)
        except (TypeError, ValueError):
            return None
        if p <= 0:
            return None
        return min(p, MAX_THRESHOLD_S)

    # -- persistence: atomic JSON, corruption -> defaults, never raises ----- #
    def load(self) -> None:
        if self._data_dir is None:
            return
        try:
            raw = json.loads((self._data_dir / STATE_FILENAME).read_text())
            ema = float(raw["ema_s"])
            floor = float(raw["floor_s"])
            obs = int(raw["observations"])
            if not (0 < ema <= MAX_THRESHOLD_S):
                raise ValueError("ema out of range")
            if not (MIN_THRESHOLD_S <= floor <= MAX_THRESHOLD_S):
                raise ValueError("floor out of range")
            if obs < 0:
                raise ValueError("observations out of range")
        except Exception:
            return  # defaults stand; a corrupt file is not an outage
        self._ema_s, self._floor_s, self._observations = ema, floor, obs

    def save(self) -> None:
        if self._data_dir is None:
            return
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            p = self._data_dir / STATE_FILENAME
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "version": _STATE_VERSION,
                "ema_s": self._ema_s,
                "floor_s": self._floor_s,
                "observations": self._observations,
            }))
            tmp.replace(p)  # atomic: a crash mid-save keeps the old state
        except Exception:
            pass  # persistence is a courtesy, never a failure mode
