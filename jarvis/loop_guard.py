"""JARVIS v2 — LoopGuard: loop / stagnation / cycle detection (Team 8).

Windows-Use's LoopGuard (mega-scan team8-desktop2.md, mechanism 5),
reduced to its deterministic core. An agent loop can fail while every
individual action "succeeds": it repeats the same call forever, ping-
pongs between two states, or acts and acts while the world never
changes. v2's brain stops after 2 consecutive FAILURES — it is blind to
all three of those. This guard sees them.

The caller builds a canonical action signature (tool name + args JSON,
normalized by the caller — the same contract as Windows-Use's
SHA-256(tool + normalized params)) and a state fingerprint (whatever
identifies "the world right now" for that surface — Windows-Use uses
HWND + a hash of the interactive-elements string). Both are hashed
with SHA-256 here; comparisons run over the hashes inside a sliding
window of the last `window` observations.

Verdicts (observe() returns exactly one string):
  OK        — nothing pathological.
  STAGNANT  — the last 3 state fingerprints are identical, with an
              action taken between each: the world is not moving.
  CYCLE     — the last 3 action signatures form A -> B -> A (A != B):
              the agent is ping-ponging.
  REPEAT    — the current action signature now appears >= 4 times in
              the window (not necessarily consecutively).
Precedence when several fire: STAGNANT > CYCLE > REPEAT — a frozen
world is the strongest stuck signal, then a visible ping-pong, then
mere repetition (a repeated action in a CHANGING world can be honest
work, e.g. scrolling; a repeated action in a frozen world is already
caught as STAGNANT).

Pure stdlib, no I/O, fully deterministic: same observation sequence,
same verdicts, every process, every time.

WIRING NOTE: brain wiring is a later round. The intended call site is
the brain's Act loop — observe(signature, state_fingerprint) before/
after each tool dispatch, escalate on non-OK verdicts (nudge, then the
existing honest stop). Nothing imports this module yet, by design.
"""

from __future__ import annotations

import hashlib
from collections import deque

OK = "OK"
STAGNANT = "STAGNANT"
CYCLE = "CYCLE"
REPEAT = "REPEAT"

DEFAULT_WINDOW = 15        # Windows-Use's 15-step window
STAGNANT_AFTER = 3         # consecutive identical state fingerprints
REPEAT_AFTER = 4           # same action signature within the window


def _hash(value) -> str:
    """Canonical hash of a signature/fingerprint (any str-able value)."""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


class LoopGuard:
    """Sliding-window loop detector. One guard per agent loop."""

    def __init__(self, window: int = DEFAULT_WINDOW) -> None:
        if int(window) < 1:
            raise ValueError(f"window must be >= 1, got {window!r}")
        self.window = int(window)
        self._actions: deque = deque(maxlen=self.window)
        self._states: deque = deque(maxlen=self.window)

    def observe(self, action_signature, state_fingerprint) -> str:
        """Record one action + the state it left behind; return a verdict.

        `action_signature`: canonical string the CALLER builds
        (tool + args JSON). `state_fingerprint`: caller's hash of the
        current world state. The CURRENT observation counts toward
        every check — the verdict describes the loop as of right now.
        """
        action = _hash(action_signature)
        state = _hash(state_fingerprint)
        self._actions.append(action)
        self._states.append(state)

        # STAGNANT: the world has not moved across the last 3
        # observations, though an action was taken between each pair.
        if len(self._states) >= STAGNANT_AFTER:
            tail = list(self._states)[-STAGNANT_AFTER:]
            if tail.count(tail[0]) == STAGNANT_AFTER:
                return STAGNANT

        # CYCLE: the last 3 actions go A -> B -> A — a ping-pong the
        # consecutive-checks cannot see.
        if len(self._actions) >= 3:
            first, _mid, last = list(self._actions)[-3:]
            if first == last and first != _mid:
                return CYCLE

        # REPEAT: this action has now run REPEAT_AFTER times inside
        # the window, consecutive or not.
        if self._actions.count(action) >= REPEAT_AFTER:
            return REPEAT

        return OK

    def reset(self) -> None:
        """Forget all observations (e.g. a new task begins)."""
        self._actions.clear()
        self._states.clear()

    def __len__(self) -> int:
        return len(self._actions)
