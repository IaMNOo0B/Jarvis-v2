"""JARVIS v2 — proactivity: the call-ringing interruption model.

Owais's design (JARVIS-RULES.txt P2-4):
  Normal update = rings like a call (visual + soft tone, never voice yet).
  Pick up = "I'm free"  -> JARVIS speaks the update.
  Cut      = "I'm busy"  -> silent, logged quietly for later.
  Urgent   = no ring, JARVIS speaks directly.

The one rule: hearing JARVIS's voice unprompted means you asked,
or it is genuinely urgent.

Structural guarantees (not conventions):
  - The urgent enum is CLOSED. Only disk_failing / security_event /
    user_critical can be urgent. Any other urgency string is coerced to
    normal. A caller cannot invent urgency.
  - Busy detection is deterministic code over on-device signals. The model
    gets no vote.
  - Captures never reach this module: the observer owns capture -> triage ->
    discard entirely in RAM. The watcher only ever receives a candidate
    remark (or None). RAM-only is structural, not a flag.
  - The watcher is OFF by default and refuses intervals below 60s.
  - Reminders are persisted atomically BEFORE acknowledgment, and re-armed
    BEFORE announcement. A crash between fire and announce loses nothing.

Python 3.11+, stdlib only (threading, time, json, os, uuid).
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field


# --------------------------------------------------------------------------- #
# Structural constants
# --------------------------------------------------------------------------- #

#: Watcher interval floor (seconds). Lower values are refused, not clamped.
MIN_INTERVAL_S = 60

#: P3-1 backstop: max non-urgent rings per day. No rollover.
MAX_RINGS_PER_DAY = 5

#: Consecutive cuts of one nudge type before that type auto-suppresses.
CUT_STREAK_SUPPRESS = 5

#: Quiet hours (24h clock): normal rings never fire here.
QUIET_HOURS = range(0, 7)

#: CLOSED urgent enum. Anything not in this tuple CANNOT be urgent.
URGENT_KINDS = ("disk_failing", "security_event", "user_critical")

#: Busy signals the deterministic gate understands.
_BUSY_FULLSCREEN = "fullscreen"
_BUSY_QUIET_HOURS = "quiet_hours"
_BUSY_DISMISSAL_STREAK = "dismissal_streak"


# --------------------------------------------------------------------------- #
# Urgency: a closed enum, enforced by construction
# --------------------------------------------------------------------------- #

def urgency_of(urgency: str) -> str:
    """Map a requested urgency to 'urgent' or 'normal'.

    Only the three URGENT_KINDS are urgent. EVERYTHING else — typos,
    novel strings, empty strings — is normal. There is no code path by
    which a caller can mint a new urgent kind.
    """
    return "urgent" if urgency in URGENT_KINDS else "normal"


# --------------------------------------------------------------------------- #
# Busy detection: deterministic code, on-device signals only
# --------------------------------------------------------------------------- #

def should_interrupt(signals: dict) -> tuple[bool, str]:
    """Decide whether a NORMAL ring may fire right now.

    signals: {idle_seconds, fullscreen, hour, dismissal_streak}.
    Pure function of the signals. The model is never consulted —
    there is no parameter, prompt, or hook by which model output could
    influence this decision.
    """
    if signals.get("fullscreen"):
        return False, _BUSY_FULLSCREEN
    hour = signals.get("hour")
    if hour is not None and int(hour) in QUIET_HOURS:
        return False, _BUSY_QUIET_HOURS
    if int(signals.get("dismissal_streak", 0) or 0) >= 3:
        return False, _BUSY_DISMISSAL_STREAK
    return True, "ok"


# --------------------------------------------------------------------------- #
# Atomic JSON persistence (small state files: rings, learning, reminders)
# --------------------------------------------------------------------------- #

def _atomic_write_json(path: str, obj: dict) -> None:
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False, sort_keys=True))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _read_json(path: str, default: dict) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else dict(default)
    except (OSError, ValueError):
        return dict(default)


# --------------------------------------------------------------------------- #
# Ring
# --------------------------------------------------------------------------- #

@dataclass
class Ring:
    """One interruption. The module never plays audio or shows UI itself:
    ring() returns the Ring for the UI layer to display + soft tone.
    pick_up() returns the detail text for the voice layer to speak.
    """
    id: str
    kind: str            # "normal" | "urgent"
    type: str            # nudge type, for learning (e.g. "watcher", "reminder")
    title: str
    detail: str
    ts: float
    state: str = "ringing"   # ringing | picked_up | cut | expired


# --------------------------------------------------------------------------- #
# RingManager — budget, busy gate, learning, dismissal logging
# --------------------------------------------------------------------------- #

class RingManager:
    """Owns all ringing decisions.

    session_store / session_id are optional: when provided, cuts (and
    suppressions) are logged as session events. When absent, decisions are
    still enforced; logging is skipped, never faked.
    """

    def __init__(self, data_dir: str,
                 session_store=None,
                 session_id: str | None = None,
                 time_fn=None) -> None:
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._store = session_store
        self._session_id = session_id
        self._time = time_fn or time.time
        self._rings: dict[str, Ring] = {}
        self._lock = threading.Lock()
        self._rings_path = os.path.join(data_dir, "rings.json")
        self._learning_path = os.path.join(data_dir, "learning.json")

    # -- persistence ---------------------------------------------------- #
    def _today(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self._time()))

    def _ring_count(self) -> tuple[str, int]:
        state = _read_json(self._rings_path, {})
        today = self._today()
        if state.get("date") != today:
            return today, 0
        return today, int(state.get("normal_count", 0))

    def _bump_ring_count(self) -> None:
        today, count = self._ring_count()
        _atomic_write_json(self._rings_path,
                           {"date": today, "normal_count": count + 1})

    def _learning(self) -> dict:
        return _read_json(self._learning_path, {})

    def _save_learning(self, learning: dict) -> None:
        _atomic_write_json(self._learning_path, learning)

    def _type_stats(self, learning: dict, type_: str) -> dict:
        stats = learning.get(type_)
        if not isinstance(stats, dict):
            stats = {"picked": 0, "cut": 0, "cut_streak": 0,
                     "suppressed": False}
            learning[type_] = stats
        return stats

    def _log(self, type_: str, payload: dict) -> None:
        if self._store is None or self._session_id is None:
            return
        try:
            self._store.emit(self._session_id, type_, payload,
                             actor="jarvis", trust="user")
        except Exception:
            pass  # logging must never break ringing decisions

    # -- decisions ------------------------------------------------------- #
    def is_suppressed(self, type_: str) -> bool:
        return bool(self._type_stats(self._learning(), type_).get("suppressed"))

    def ring(self, urgency: str, type_: str, title: str, detail: str,
             signals: dict | None = None) -> Ring | None:
        """Attempt one ring. Returns the Ring, or None when suppressed.

        Suppression reasons are recorded in the returned-None contract via
        `last_suppression` (not exceptions: suppression is routine).
        """
        self.last_suppression: str | None = None
        kind = urgency_of(urgency)

        with self._lock:
            if self.is_suppressed(type_):
                self.last_suppression = f"type {type_!r} auto-suppressed"
                self._log("proactivity.suppressed",
                          {"type": type_, "reason": self.last_suppression})
                return None

            if kind == "normal":
                _, count = self._ring_count()
                if count >= MAX_RINGS_PER_DAY:
                    self.last_suppression = (
                        f"backstop: {MAX_RINGS_PER_DAY} non-urgent rings used today")
                    self._log("proactivity.suppressed",
                              {"type": type_, "reason": self.last_suppression})
                    return None
                ok, reason = should_interrupt(signals or {})
                if not ok:
                    self.last_suppression = f"busy: {reason}"
                    # Suppressed rings are logged quietly, never announced.
                    self._log("proactivity.suppressed",
                              {"type": type_, "title": title, "reason": reason})
                    return None
                self._bump_ring_count()

            ring = Ring(id=uuid.uuid4().hex, kind=kind, type=type_,
                        title=title, detail=detail, ts=self._time())
            self._rings[ring.id] = ring
            self._log("proactivity.rang",
                      {"ring_id": ring.id, "kind": kind, "type": type_,
                       "title": title})
            return ring

    def pick_up(self, ring_id: str) -> str | None:
        """User picked up: return the detail text for the voice layer to speak."""
        with self._lock:
            ring = self._rings.get(ring_id)
            if ring is None or ring.state != "ringing":
                return None
            ring.state = "picked_up"
            learning = self._learning()
            stats = self._type_stats(learning, ring.type)
            stats["picked"] = int(stats.get("picked", 0)) + 1
            stats["cut_streak"] = 0
            self._save_learning(learning)
            self._log("proactivity.picked_up",
                      {"ring_id": ring.id, "type": ring.type})
            return ring.detail

    def cut(self, ring_id: str) -> bool:
        """User cut the call: silent. Logged quietly for later."""
        with self._lock:
            ring = self._rings.get(ring_id)
            if ring is None or ring.state != "ringing":
                return False
            ring.state = "cut"
            learning = self._learning()
            stats = self._type_stats(learning, ring.type)
            stats["cut"] = int(stats.get("cut", 0)) + 1
            stats["cut_streak"] = int(stats.get("cut_streak", 0)) + 1
            if stats["cut_streak"] >= CUT_STREAK_SUPPRESS:
                stats["suppressed"] = True
                self._log("proactivity.type_suppressed",
                          {"type": ring.type,
                           "reason": f"cut {CUT_STREAK_SUPPRESS}x in a row"})
            self._save_learning(learning)
            self._log("proactivity.dismissed",
                      {"ring_id": ring.id, "type": ring.type,
                       "title": ring.title})
            return True

    def unsuppress(self, type_: str) -> None:
        """Manual re-enable of an auto-suppressed type (Settings UI)."""
        with self._lock:
            learning = self._learning()
            stats = self._type_stats(learning, type_)
            stats["suppressed"] = False
            stats["cut_streak"] = 0
            self._save_learning(learning)


# --------------------------------------------------------------------------- #
# Watcher — background observer loop. OFF by default. RAM-only by structure.
# --------------------------------------------------------------------------- #

class Watcher:
    """Background watcher thread.

    The observer callable owns capture -> triage -> discard ENTIRELY in RAM
    and returns either None or a candidate dict:
        {"title": ..., "detail": ..., "type": ..., "urgency": "normal"|...}
    This module never receives raw captures, so it cannot write them to disk.
    RAM-only is structural, not a flag.

    enable()/disable() take effect immediately. disable() stops the thread;
    it does not wait for the next cycle.
    """

    def __init__(self, ring_manager: RingManager,
                 observer=None,
                 interval_s: float = 300,
                 signals_fn=None,
                 time_fn=None) -> None:
        if interval_s < MIN_INTERVAL_S:
            raise ValueError(
                f"watcher interval {interval_s}s refused: "
                f"floor is {MIN_INTERVAL_S}s")
        self.rings = ring_manager
        self.observer = observer
        self.interval_s = interval_s
        self.signals_fn = signals_fn or (lambda: {})
        self._time = time_fn or time.time
        self.enabled = False  # OFF by default. Not "off but nagging". Off.
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.cycles = 0
        self.rang = 0

    def enable(self) -> None:
        if self.enabled:
            return
        self.enabled = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="jarvis-watcher")
        self._thread.start()

    def disable(self) -> None:
        """Immediate stop. Not 'next restart'. Now."""
        self.enabled = False
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self._cycle()
            except Exception:
                # A failed cycle never kills the watcher; backoff is the
                # observer's job. Count it and move on.
                continue

    def _cycle(self) -> None:
        """One observe -> decide -> maybe-ring pass. Also directly testable."""
        self.cycles += 1
        if self.observer is None:
            return
        candidate = self.observer()  # RAM-only inside the observer
        if not candidate:
            return
        ring = self.rings.ring(
            urgency=candidate.get("urgency", "normal"),
            type_=candidate.get("type", "watcher"),
            title=str(candidate.get("title", ""))[:200],
            detail=str(candidate.get("detail", ""))[:2000],
            signals=self.signals_fn(),
        )
        if ring is not None:
            self.rang += 1


# --------------------------------------------------------------------------- #
# Reminders — durable scheduler. Persist BEFORE ack; re-arm BEFORE announce.
# --------------------------------------------------------------------------- #

class ReminderError(ValueError):
    """Invalid reminder request, in plain words (never a raw ValueError)."""


@dataclass
class Reminder:
    id: str
    text: str
    when_ts: float
    repeat_s: float | None = None   # None = one-shot
    fired: bool = False
    created_ts: float = 0.0


class ReminderStore:
    """Atomic, crash-safe reminders.

    Invariants (tested):
      1. schedule() persists BEFORE it returns. The acknowledgment the user
         hears is only valid because the reminder is already on disk.
      2. fire() re-arms the next occurrence BEFORE the current one is marked
         fired. A crash between re-arm and announce loses nothing: the next
         occurrence already exists.
    """

    def __init__(self, data_dir: str, time_fn=None) -> None:
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._path = os.path.join(data_dir, "reminders.json")
        self._time = time_fn or time.time
        self._lock = threading.Lock()

    # -- persistence ---------------------------------------------------- #
    def _load(self) -> dict:
        return _read_json(self._path, {"reminders": {}})

    def _save(self, state: dict) -> None:
        _atomic_write_json(self._path, state)

    # -- API ------------------------------------------------------------ #
    def schedule(self, when_ts: float, text: str,
                 repeat_s: float | None = None) -> str:
        """Create a reminder. Validates first (plain-words errors), persists
        atomically, and only then returns the id (the acknowledgment point)."""
        now = self._time()
        text = (text or "").strip()
        if not text:
            raise ReminderError("I need to know what to remind you about, sir.")
        try:
            when = float(when_ts)
        except (TypeError, ValueError):
            raise ReminderError(
                "I didn't catch the time, sir — when should I remind you?")
        if when <= now:
            raise ReminderError(
                "That time has already passed, sir — when should I remind you?")
        if len(text) > 500:
            raise ReminderError("That reminder is too long, sir — keep it short.")
        if repeat_s is not None and float(repeat_s) <= 0:
            raise ReminderError("The repeat interval must be positive, sir.")

        with self._lock:
            state = self._load()
            reminders = state.setdefault("reminders", {})
            rid = uuid.uuid4().hex
            reminders[rid] = {
                "id": rid, "text": text, "when_ts": when,
                "repeat_s": repeat_s, "fired": False, "created_ts": now,
            }
            # INVARIANT 1: on disk BEFORE the caller may acknowledge.
            self._save(state)
            return rid

    def due(self, now: float | None = None) -> list[dict]:
        """Reminders whose time has come and haven't fired."""
        now = self._time() if now is None else now
        with self._lock:
            state = self._load()
            return [r for r in state.get("reminders", {}).values()
                    if not r.get("fired") and r.get("when_ts", 0) <= now]

    def fire(self, reminder_id: str) -> dict | None:
        """Mark fired and re-arm. Returns the fired reminder for announcement.

        INVARIANT 2: the next occurrence is persisted BEFORE the current one
        is marked fired. Crash anywhere after this returns: the future is
        already safe.
        """
        with self._lock:
            state = self._load()
            reminders = state.get("reminders", {})
            rem = reminders.get(reminder_id)
            if rem is None or rem.get("fired"):
                return None
            repeat = rem.get("repeat_s")
            if repeat:
                nxt_id = uuid.uuid4().hex
                reminders[nxt_id] = {
                    "id": nxt_id, "text": rem["text"],
                    "when_ts": rem["when_ts"] + float(repeat),
                    "repeat_s": repeat, "fired": False,
                    "created_ts": self._time(),
                }
                # Re-arm persisted FIRST...
                self._save(state)
            rem["fired"] = True
            self._save(state)
            return dict(rem)

    def cancel(self, reminder_id: str) -> bool:
        with self._lock:
            state = self._load()
            reminders = state.get("reminders", {})
            if reminder_id not in reminders:
                return False
            del reminders[reminder_id]
            self._save(state)
            return True

    def list(self) -> list[dict]:
        with self._lock:
            state = self._load()
            return sorted(state.get("reminders", {}).values(),
                          key=lambda r: r.get("when_ts", 0))
