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
  - Dismissal is durable (Team 14 steal, hawky pattern): cutting a ring
    that carries an item identity writes a suppression key to
    suppressions.json BEFORE the candidate can ever be minted again, and
    it survives restarts. One exception, by design: URGENT kinds are
    never item-suppressed — a safety alert cannot be silenced forever
    by a single cut.
  - Proactivity is governed by NUMBERS, not vibes (Team 22 numeric
    pack — dota-ai-coach + vrchat-assistant, both read at code level):
    a post-interaction silence window (60s), a consecutive-failure
    threshold per source (3 strikes -> the source goes quiet until it
    next succeeds), and a per-source minimum interval between minted
    rings (300s). All three sit BESIDE the 5/day backstop; none of
    them replaces it, and URGENT kinds bypass all three, as always.

Python 3.11+, stdlib only (threading, time, json, os, re, uuid).
"""

from __future__ import annotations

import json
import os
import re
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

#: Post-interaction silence window (seconds): after the user interacts,
#: non-urgent rings are held for this long. The user speaking resets the
#: proactive clock (dota-ai-coach silence_duration_seconds, Team 22 §1.3).
DEFAULT_SILENCE_AFTER_USER_S = 60.0

#: Consecutive failed/empty checks after which a source goes quiet until
#: its next success (vrchat-assistant consecutive_fail_threshold,
#: Team 22 §1.16).
DEFAULT_FAIL_THRESHOLD = 3

#: Minimum seconds between rings minted by the same source, independent
#: of the daily backstop (vrchat-assistant min_interval_sec, Team 22
#: §1.16). Both limits apply; whichever is stricter wins.
DEFAULT_MIN_INTERVAL_S = 300.0

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
# Durable suppression store — dismissal is forever (hawky pattern)
# --------------------------------------------------------------------------- #
#
# Identity here is SHAPE-based: "anything like this", not "this exact
# item" (exact identity is the briefing ledger's job, digest_diff.py).
# The shape collapses digits and case, so "Disk 91% full" and
# "Disk 93% full" are the same shape of nudge. A dismissal recorded
# against that shape suppresses every future candidate of that shape
# from that source, across restarts, until the owner clears it.
#
# Feedback is TARGETED (langchain ambient-agent pattern): recording an
# outcome touches exactly one key. There is no whole-profile rewrite —
# one preference can never clobber another.

#: Outcomes the store records. Only "dismissed" suppresses.
SUPPRESSION_OUTCOMES = ("dismissed", "picked_up", "edited")


def item_shape(item) -> str:
    """Canonical shape signature of a candidate item.

    From a dict: its explicit "shape" if given, else title/text/detail
    joined. From anything else: its string form. Normalised: lowercased,
    digit runs collapsed to '#', whitespace collapsed, capped at 120
    chars so keys stay readable in the store file.
    """
    if isinstance(item, dict):
        if item.get("shape"):
            raw = str(item["shape"])
        else:
            raw = " ".join(str(item.get(k, "") or "")
                           for k in ("title", "text", "detail"))
    else:
        raw = str(item)
    norm = re.sub(r"\d+", "#", raw.lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm[:120]


def suppression_key(source: str, item) -> str:
    """The durable store key for one candidate: 'source|shape'."""
    return f"{source}|{item_shape(item)}"


class SuppressionStore:
    """Persisted per-item-shape feedback: suppressions + preferences.

    File: suppressions.json in the data dir, one entry per key:
    {outcome, source, title, count, first_ts, last_ts}. Written
    atomically on every record; a fresh instance over the same data
    dir sees everything (dismissal survives restarts BY CONSTRUCTION).
    """

    def __init__(self, data_dir: str, time_fn=None) -> None:
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._path = os.path.join(data_dir, "suppressions.json")
        self._time = time_fn or time.time
        self._lock = threading.Lock()

    # -- persistence ---------------------------------------------------- #
    def _load(self) -> dict:
        state = _read_json(self._path, {"keys": {}})
        if not isinstance(state.get("keys"), dict):
            state["keys"] = {}
        return state

    def _save(self, state: dict) -> None:
        _atomic_write_json(self._path, state)

    # -- recording (targeted: exactly one key is ever touched) ----------- #
    def record(self, source: str, item, outcome: str) -> str:
        """Record one outcome for one item shape. Returns the key."""
        return self.record_key(suppression_key(source, item), outcome,
                               source=source,
                               title=item_shape(item))

    def record_key(self, key: str, outcome: str, source: str = "",
                   title: str = "") -> str:
        if outcome not in SUPPRESSION_OUTCOMES:
            raise ValueError(
                f"outcome must be one of {SUPPRESSION_OUTCOMES}, "
                f"got {outcome!r}")
        now = self._time()
        with self._lock:
            state = self._load()
            keys = state.setdefault("keys", {})
            entry = keys.get(key)
            if not isinstance(entry, dict):
                entry = {"first_ts": now, "count": 0}
                keys[key] = entry
            entry.update({"outcome": outcome, "source": source,
                          "title": title, "last_ts": now})
            entry["count"] = int(entry.get("count", 0)) + 1
            self._save(state)
        return key

    # -- reads ------------------------------------------------------------ #
    def is_suppressed(self, source: str, item) -> bool:
        return self.is_suppressed_key(suppression_key(source, item))

    def is_suppressed_key(self, key: str) -> bool:
        """True iff this exact key's latest outcome is a dismissal."""
        entry = self._load().get("keys", {}).get(key)
        return isinstance(entry, dict) and entry.get("outcome") == "dismissed"

    def outcome_of(self, source: str, item) -> str | None:
        entry = self._load().get("keys", {}).get(
            suppression_key(source, item))
        return entry.get("outcome") if isinstance(entry, dict) else None

    def all(self) -> dict:
        """A copy of every recorded key -> entry (Settings UI)."""
        return dict(self._load().get("keys", {}))

    # -- owner control ------------------------------------------------------ #
    def forget(self, source: str, item) -> bool:
        """Remove one key (the owner's 'actually, do tell me again')."""
        key = suppression_key(source, item)
        with self._lock:
            state = self._load()
            keys = state.setdefault("keys", {})
            if key not in keys:
                return False
            del keys[key]
            self._save(state)
            return True

    def clear(self, source: str | None = None) -> int:
        """Remove all keys, or only one source's. Returns how many."""
        with self._lock:
            state = self._load()
            keys = state.setdefault("keys", {})
            if source is None:
                removed = len(keys)
                keys.clear()
            else:
                doomed = [k for k in keys if k.startswith(f"{source}|")]
                removed = len(doomed)
                for k in doomed:
                    del keys[k]
            self._save(state)
            return removed


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
    item_key: str | None = None  # durable-suppression identity, if any


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
                 time_fn=None,
                 suppression_store: "SuppressionStore | None" = None,
                 silence_after_user_s: float = DEFAULT_SILENCE_AFTER_USER_S,
                 source_fail_threshold: int = DEFAULT_FAIL_THRESHOLD,
                 min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
                 min_interval_by_source: dict | None = None) -> None:
        if float(silence_after_user_s) < 0:
            raise ValueError("silence_after_user_s can't be negative")
        if int(source_fail_threshold) < 1:
            raise ValueError("source_fail_threshold must be at least 1")
        if float(min_interval_s) < 0:
            raise ValueError("min_interval_s can't be negative")
        overrides = dict(min_interval_by_source or {})
        for src, val in overrides.items():
            if float(val) < 0:
                raise ValueError(
                    f"min interval for source {src!r} can't be negative")
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._store = session_store
        self._session_id = session_id
        self._time = time_fn or time.time
        self._rings: dict[str, Ring] = {}
        self._lock = threading.Lock()
        # --- Team 22 numeric pack (see module constants) ---------------- #
        # Post-interaction silence window. In-memory on purpose: the
        # window is 60s of UX state, not learned state — a restart is a
        # natural end to it. 0 disables the window.
        self.silence_after_user_s = float(silence_after_user_s)
        self._last_user_activity: float | None = None
        # Per-source consecutive-failure accounting. In-memory: streaks
        # describe the source's health RIGHT NOW, not its history.
        self.source_fail_threshold = int(source_fail_threshold)
        self._source_streaks: dict[str, int] = {}
        # Per-source minimum interval between MINTED rings. Only rings
        # minted with an explicit source= are tracked (direct/legacy
        # rings carry no source identity; the 5/day backstop governs
        # them). In-memory: a short-horizon anti-spam gate, not a
        # learned preference. 0 disables.
        self.min_interval_s = float(min_interval_s)
        self._min_interval_by_source = {str(k): float(v)
                                        for k, v in overrides.items()}
        self._last_mint_by_source: dict[str, float] = {}
        self._rings_path = os.path.join(data_dir, "rings.json")
        self._learning_path = os.path.join(data_dir, "learning.json")
        # Durable per-item suppression (dismissal is forever). Defaults
        # to a store over the same data dir; injectable for tests/UI.
        self.suppressions = (suppression_store
                             if suppression_store is not None
                             else SuppressionStore(data_dir,
                                                   time_fn=self._time))

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

    # -- numeric pack: silence window, source health, source interval ---- #
    def note_user_activity(self, now: float | None = None) -> None:
        """The app reports: the user just interacted (a turn happened).

        Starts (or refreshes) the post-interaction silence window:
        non-urgent rings are held until silence_after_user_s has
        elapsed since the MOST RECENT activity. Urgent kinds are
        never held — see ring().
        """
        self._last_user_activity = self._time() if now is None else float(now)

    @property
    def last_user_activity(self) -> float | None:
        """When the user last interacted (None = never recorded)."""
        return self._last_user_activity

    def in_silence_window(self, now: float | None = None) -> bool:
        """True while a non-urgent ring would be held for silence."""
        if self.silence_after_user_s <= 0 or self._last_user_activity is None:
            return False
        now = self._time() if now is None else float(now)
        return (now - self._last_user_activity) < self.silence_after_user_s

    def note_source_check(self, source: str, ok: bool) -> int:
        """Report one check outcome for a source. Returns the streak.

        ok=True (the check returned something real): the streak resets
        to 0 — success revives a muted source. ok=False (the check
        failed or came back empty): the streak grows by one; at
        source_fail_threshold the source is muted (see source_muted).
        Checks are counted per source; one source's failures never
        touch another's streak.
        """
        source = str(source)
        with self._lock:
            if ok:
                self._source_streaks[source] = 0
            else:
                self._source_streaks[source] = (
                    int(self._source_streaks.get(source, 0)) + 1)
            return self._source_streaks[source]

    def source_fail_streak(self, source: str) -> int:
        """Current consecutive-failure streak for a source (0 if none)."""
        return int(self._source_streaks.get(str(source), 0))

    def source_muted(self, source: str) -> bool:
        """True once a source's failed/empty checks hit the threshold
        in a row. It stays muted until its next successful check."""
        return (self.source_fail_streak(source)
                >= self.source_fail_threshold)

    def _min_interval_for(self, source: str) -> float:
        return self._min_interval_by_source.get(str(source),
                                                self.min_interval_s)

    # -- decisions ------------------------------------------------------- #
    def is_suppressed(self, type_: str) -> bool:
        return bool(self._type_stats(self._learning(), type_).get("suppressed"))

    def ring(self, urgency: str, type_: str, title: str, detail: str,
             signals: dict | None = None,
             item=None,
             source: str | None = None) -> Ring | None:
        """Attempt one ring. Returns the Ring, or None when suppressed.

        Suppression reasons are recorded in the returned-None contract via
        `last_suppression` (not exceptions: suppression is routine).

        `item` (optional dict/str) gives the candidate a durable
        identity: if this item SHAPE was dismissed before, the candidate
        is refused BEFORE it is minted (checked first — most specific
        suppression wins). URGENT kinds skip the item check entirely:
        dismissal is forever for nudges, never for safety alerts.

        `source` (optional) names the proactive source minting this
        ring (a watcher feed, the digest, ...). It defaults to the
        ring type for the mute gate; when given explicitly it ALSO
        opts the ring into per-source minimum-interval tracking.
        The numeric gates (muted source, silence window, minimum
        interval) apply to NORMAL rings only — urgent bypasses them
        all, exactly like the backstop and the busy gate.
        """
        self.last_suppression: str | None = None
        kind = urgency_of(urgency)
        key = suppression_key(type_, item) if item is not None else None
        src = str(source) if source is not None else type_

        with self._lock:
            if (key is not None and kind == "normal"
                    and self.suppressions.is_suppressed_key(key)):
                self.last_suppression = (
                    "dismissed before — durable suppression (dismissal "
                    "is forever; clear it in Settings to hear it again)")
                self._log("proactivity.suppressed",
                          {"type": type_, "item_key": key,
                           "reason": self.last_suppression})
                return None

            if self.is_suppressed(type_):
                self.last_suppression = f"type {type_!r} auto-suppressed"
                self._log("proactivity.suppressed",
                          {"type": type_, "reason": self.last_suppression})
                return None

            if kind == "normal":
                if self.source_muted(src):
                    self.last_suppression = (
                        f"source muted: {src!r} quiet after "
                        f"{self.source_fail_streak(src)} consecutive "
                        f"failed/empty checks — it speaks again after "
                        f"its next success")
                    self._log("proactivity.suppressed",
                              {"type": type_, "source": src,
                               "reason": self.last_suppression})
                    return None
                if self.in_silence_window():
                    ago = self._time() - float(self._last_user_activity)
                    self.last_suppression = (
                        f"silence: user was active {ago:.0f}s ago — "
                        f"holding non-urgent rings for "
                        f"{self.silence_after_user_s - ago:.0f}s more")
                    self._log("proactivity.suppressed",
                              {"type": type_, "source": src,
                               "reason": self.last_suppression})
                    return None
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
                if source is not None:
                    interval = self._min_interval_for(src)
                    last_mint = self._last_mint_by_source.get(src)
                    if (interval > 0 and last_mint is not None
                            and self._time() - last_mint < interval):
                        ago = self._time() - last_mint
                        self.last_suppression = (
                            f"min interval: source {src!r} minted a "
                            f"ring {ago:.0f}s ago (minimum "
                            f"{interval:.0f}s between rings)")
                        self._log("proactivity.suppressed",
                                  {"type": type_, "source": src,
                                   "reason": self.last_suppression})
                        return None
                self._bump_ring_count()

            ring = Ring(id=uuid.uuid4().hex, kind=kind, type=type_,
                        title=title, detail=detail, ts=self._time(),
                        item_key=key)
            self._rings[ring.id] = ring
            if source is not None:
                # A mint is a mint, urgent included: the source's
                # interval clock starts from EVERY ring it mints,
                # though urgent rings themselves are never gated.
                self._last_mint_by_source[src] = ring.ts
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
            if ring.item_key is not None:
                # Targeted preference: this shape was welcome. Recorded,
                # never suppressing — and it touches only this one key.
                self.suppressions.record_key(
                    ring.item_key, "picked_up", source=ring.type,
                    title=item_shape(ring.title))
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
            if ring.item_key is not None:
                # Dismissal is FOREVER for this item shape: the durable
                # key is written now, before any future candidate of
                # this shape can be minted — and it survives restarts.
                self.suppressions.record_key(
                    ring.item_key, "dismissed", source=ring.type,
                    title=item_shape(ring.title))
                self._log("proactivity.item_dismissed",
                          {"ring_id": ring.id, "type": ring.type,
                           "item_key": ring.item_key})
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
                 time_fn=None,
                 source: str | None = None) -> None:
        if interval_s < MIN_INTERVAL_S:
            raise ValueError(
                f"watcher interval {interval_s}s refused: "
                f"floor is {MIN_INTERVAL_S}s")
        self.rings = ring_manager
        self.observer = observer
        self.interval_s = interval_s
        self.signals_fn = signals_fn or (lambda: {})
        self._time = time_fn or time.time
        # This watcher's source identity for the numeric pack. A
        # candidate may override it per cycle ("source" key wins, then
        # its "type"). Naming the watcher (or its candidates) is what
        # opts its rings into per-source minimum-interval tracking;
        # check outcomes are always reported (default identity
        # "watcher") so the failure threshold can mute the feed.
        self.source = source
        self.enabled = False  # OFF by default. Not "off but nagging". Off.
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.cycles = 0
        self.rang = 0
        # Completions never ring one-by-one; they collect here for a
        # single batched recap (the state-ladder policy, below).
        self.completions = CompletionBatcher()

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

    # -- numeric pack: app-facing hooks ---------------------------------- #
    def note_user_activity(self, now: float | None = None) -> None:
        """The app reports a user turn: start the silence window."""
        self.rings.note_user_activity(now)

    def note_check_result(self, source: str, ok: bool) -> int:
        """Report a check outcome for a source (see RingManager)."""
        return self.rings.note_source_check(source, ok)

    def source_muted(self, source: str) -> bool:
        return self.rings.source_muted(source)

    def _cycle(self) -> None:
        """One observe -> decide -> maybe-ring pass. Also directly testable."""
        self.cycles += 1
        if self.observer is None:
            return
        try:
            candidate = self.observer()  # RAM-only inside the observer
        except Exception:
            # A failed check counts against this watcher's source,
            # then propagates exactly as before (the loop swallows it).
            self.rings.note_source_check(self.source or "watcher", False)
            raise
        if not candidate:
            # An empty check counts too: fail OR empty, N in a row,
            # and the source goes quiet until it next succeeds.
            self.rings.note_source_check(self.source or "watcher", False)
            return
        # A real candidate IS a successful check: it resets the
        # source's failure streak (reviving it if muted) BEFORE any
        # ring attempt, so a revived source's candidate may ring.
        check_source = (candidate.get("source") or candidate.get("type")
                        or self.source or "watcher")
        self.rings.note_source_check(check_source, True)
        title = str(candidate.get("title", ""))[:200]
        detail = str(candidate.get("detail", ""))[:2000]
        # State ladder (only when the observer supplies task signals):
        # completions are batched, never rung; silent states return
        # without ringing; waiting/idle-asked fall through to ring(),
        # where the 5/day backstop still applies untouched.
        signals = candidate.get("signals")
        if isinstance(signals, dict):
            state = derive_state(signals)
            if state == STATE_DONE:
                self.completions.add(title, detail, ts=self._time())
                return
            ring_it, _why = should_ring(state)
            if not ring_it:
                return
        ring = self.rings.ring(
            urgency=candidate.get("urgency", "normal"),
            type_=candidate.get("type", "watcher"),
            title=title,
            detail=detail,
            signals=self.signals_fn(),
            # Durable identity: an explicit candidate "item" wins;
            # otherwise the title+detail ARE the item. A shape the
            # owner already dismissed is refused before it can ring.
            item=candidate.get("item") or {"title": title,
                                           "detail": detail},
            # Declared source identity (candidate "source" key, else
            # this watcher's): opts the ring into per-source minimum
            # -interval tracking. Undeclared -> None -> untracked.
            source=candidate.get("source") or self.source,
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


# --------------------------------------------------------------------------- #
# Watcher state ladder — certainty-ordered task states (ethanplusai pattern)
# --------------------------------------------------------------------------- #
#
# When the watcher supervises long tasks (builds, downloads, JARVIS's own
# background work), each task gets ONE state from deterministic signals.
# The ladder is ordered by CERTAINTY: hard signals (process liveness,
# explicit waiting flags) outrank inferred ones (question-shaped tails).
#
# Policy asymmetry (the product insight): blocked-on-a-human is urgent
# and singular — it rings immediately, WITH the reason. Finished is
# informational and batchable — completions collect in a CompletionBatcher
# for one recap, never a ring each. Fresh/never-started tasks are never
# announced: nobody started them.

STATE_DEAD = "dead"                # process/task gone
STATE_FRESH = "fresh"              # exists but never started
STATE_WAITING = "waiting"          # explicitly blocked on a human
STATE_DONE = "done"                # completed (batchable, never rung solo)
STATE_BUSY = "busy"                # actively working
STATE_IDLE_ASKED = "idle_asked"    # idle, but its tail asked a question
STATE_IDLE = "idle"                # alive, started, nothing needed

_WAITING_STATUSES = frozenset(
    {"waiting", "blocked", "needs_you", "needs-you", "awaiting_input"})
_BUSY_STATUSES = frozenset(
    {"busy", "working", "running", "in_progress", "active"})
_DONE_STATUSES = frozenset(
    {"done", "completed", "complete", "finished", "success", "succeeded"})
_FRESH_STATUSES = frozenset({"fresh", "new", "never_started", "queued"})


def looks_like_question(text: str | None) -> bool:
    """Lowest rung of the ladder: does the tail read like a question?

    Deliberately dumb and deterministic: the last non-empty line ends
    with '?'. Inference this weak is only ever consulted after every
    hard signal has had its say.
    """
    if not text:
        return False
    lines = [ln.strip() for ln in str(text).splitlines() if ln.strip()]
    return bool(lines) and lines[-1].endswith("?")


def derive_state(signals: dict) -> str:
    """Classify one watched task from its signals. Pure function.

    Recognised signals (all optional):
      alive: bool            — False means the process/task is gone
      started: bool          — False means it never ran
      never_started: bool    — explicit alias for started=False
      status: str            — upstream status string (any case)
      waiting_for / blocked_reason: str — explicit wait, with reason
      completed: bool        — finished successfully
      busy: bool             — actively working right now
      tail_is_question: bool — precomputed question-tail flag
      tail_text / last_text: str — tail to run the question check on

    Precedence (highest certainty first):
      dead -> fresh -> waiting -> done -> busy -> idle_asked -> idle
    """
    signals = signals or {}
    if signals.get("alive") is False:
        return STATE_DEAD
    status = str(signals.get("status") or "").strip().lower()
    if (signals.get("started") is False
            or signals.get("never_started")
            or status in _FRESH_STATUSES):
        return STATE_FRESH
    if (signals.get("waiting_for") or signals.get("blocked_reason")
            or status in _WAITING_STATUSES):
        return STATE_WAITING
    if signals.get("completed") or status in _DONE_STATUSES:
        return STATE_DONE
    if signals.get("busy") or status in _BUSY_STATUSES:
        return STATE_BUSY
    if signals.get("tail_is_question") or looks_like_question(
            signals.get("tail_text") or signals.get("last_text")):
        return STATE_IDLE_ASKED
    return STATE_IDLE


def should_ring(state: str, reason: str | None = None) -> tuple[bool, str]:
    """Ring policy for a ladder state. Returns (ring?, why).

    This decides whether a state DESERVES a ring attempt; RingManager
    still enforces the busy gate and the 5/day backstop on top.
    `reason` (the blocked-on reason) is attached to waiting rings so
    the human hears WHY, not just THAT.
    """
    if state == STATE_WAITING:
        if reason:
            return True, f"blocked on you: {reason}"
        return True, "waiting for you"
    if state == STATE_IDLE_ASKED:
        return True, "idle, but it asked a question"
    if state == STATE_DONE:
        return False, "completion — batched into the digest, not rung"
    if state == STATE_FRESH:
        return False, "never started — never announced"
    if state == STATE_DEAD:
        return False, "gone — never announced"
    if state == STATE_BUSY:
        return False, "still working"
    return False, "nothing needs you"


class CompletionBatcher:
    """Collects finished-task notices for ONE batched recap.

    Completions are informational: announcing each one as it lands is
    how assistants become noise. They accumulate here (thread-safe)
    until flush_line() drains them into a single speakable line.
    """

    def __init__(self) -> None:
        self._items: list[dict] = []
        self._lock = threading.Lock()

    def add(self, title: str, detail: str = "",
            ts: float | None = None) -> None:
        with self._lock:
            self._items.append({"title": str(title), "detail": str(detail),
                                "ts": time.time() if ts is None else ts})

    def pending(self) -> list[dict]:
        """Current batch, oldest first. Does not drain."""
        with self._lock:
            return list(self._items)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def drain(self) -> list[dict]:
        """Return the batch and clear it (announce exactly once)."""
        with self._lock:
            items, self._items = self._items, []
            return items

    def flush_line(self) -> str | None:
        """Drain into one line: '3 things finished: a; b; c'. None if empty."""
        items = self.drain()
        if not items:
            return None
        titles = [i["title"] for i in items if i["title"]]
        if not titles:
            return None
        noun = "thing" if len(titles) == 1 else "things"
        return f"{len(titles)} {noun} finished: " + "; ".join(titles[:5]) + (
            f"; and {len(titles) - 5} more" if len(titles) > 5 else "")
