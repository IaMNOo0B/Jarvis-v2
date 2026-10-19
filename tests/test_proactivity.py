"""Tests for jarvis/proactivity.py — the call-ringing interruption model.

Every structural guarantee gets a test: closed urgent enum, deterministic
busy gate, backstop cap, cut-streak suppression, RAM-only captures,
reminder durability invariants.
"""

import json
import os

import pytest

from jarvis.proactivity import (
    CUT_STREAK_SUPPRESS,
    MAX_RINGS_PER_DAY,
    MIN_INTERVAL_S,
    URGENT_KINDS,
    ReminderError,
    ReminderStore,
    RingManager,
    Watcher,
    should_interrupt,
    urgency_of,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

class FakeClock:
    def __init__(self, t=1_700_000_000.0):
        self.t = t
    def __call__(self):
        return self.t
    def advance(self, s):
        self.t += s


class FakeSessionStore:
    """Captures emit() calls. Raises nothing."""
    def __init__(self):
        self.events = []
    def emit(self, session_id, type, payload, actor, trust="user",
             causal_parent=None, trace_id=None):
        self.events.append({"session_id": session_id, "type": type,
                            "payload": payload, "actor": actor})
        return "evt-test"


@pytest.fixture()
def clock():
    return FakeClock()


@pytest.fixture()
def mgr(tmp_path, clock):
    return RingManager(str(tmp_path / "data"), time_fn=clock)


FREE_SIGNALS = {"idle_seconds": 600, "fullscreen": False, "hour": 14,
                "dismissal_streak": 0}


# --------------------------------------------------------------------------- #
# Urgency: closed enum
# --------------------------------------------------------------------------- #

def test_urgent_enum_has_exactly_three_kinds():
    assert tuple(URGENT_KINDS) == ("disk_failing", "security_event",
                                  "user_critical")


def test_only_named_kinds_are_urgent():
    for kind in URGENT_KINDS:
        assert urgency_of(kind) == "urgent"


def test_novel_kind_cannot_be_urgent():
    # Structural: no caller can mint urgency. Typos, attacks, novel
    # strings all collapse to normal.
    for novel in ("hacker_urgent", "URGENT", "disk_FAILING", "", "critical",
                  "disk_failing "):
        assert urgency_of(novel) == "normal", novel


def test_ring_with_novel_urgency_is_normal(mgr):
    ring = mgr.ring(urgency="definitely_urgent_trust_me", type_="watcher",
                    title="t", detail="d", signals=FREE_SIGNALS)
    assert ring is not None
    assert ring.kind == "normal"


# --------------------------------------------------------------------------- #
# Busy gate: deterministic, model gets no vote
# --------------------------------------------------------------------------- #

def test_should_interrupt_free():
    assert should_interrupt(FREE_SIGNALS) == (True, "ok")


def test_should_interrupt_fullscreen():
    ok, reason = should_interrupt({**FREE_SIGNALS, "fullscreen": True})
    assert ok is False and reason == "fullscreen"


def test_should_interrupt_quiet_hours():
    for hour in (0, 3, 6):
        ok, reason = should_interrupt({**FREE_SIGNALS, "hour": hour})
        assert ok is False and reason == "quiet_hours", hour
    ok, _ = should_interrupt({**FREE_SIGNALS, "hour": 7})
    assert ok is True


def test_should_interrupt_dismissal_streak():
    ok, reason = should_interrupt({**FREE_SIGNALS, "dismissal_streak": 3})
    assert ok is False and reason == "dismissal_streak"
    ok, _ = should_interrupt({**FREE_SIGNALS, "dismissal_streak": 2})
    assert ok is True


def test_should_interrupt_is_deterministic():
    # Same signals, same answer, every time. No model, no randomness.
    s = {"fullscreen": False, "hour": 22, "dismissal_streak": 1}
    assert should_interrupt(s) == should_interrupt(s) == (True, "ok")


def test_busy_suppresses_normal_ring(mgr):
    ring = mgr.ring(urgency="normal", type_="watcher", title="t", detail="d",
                    signals={**FREE_SIGNALS, "fullscreen": True})
    assert ring is None
    assert mgr.last_suppression == "busy: fullscreen"


def test_busy_suppression_logged_quietly(tmp_path, clock):
    store = FakeSessionStore()
    m = RingManager(str(tmp_path / "d"), session_store=store,
                    session_id="s1", time_fn=clock)
    m.ring(urgency="normal", type_="watcher", title="t", detail="d",
           signals={**FREE_SIGNALS, "hour": 2})
    assert any(e["type"] == "proactivity.suppressed" for e in store.events)


# --------------------------------------------------------------------------- #
# Backstop: 5 non-urgent rings/day
# --------------------------------------------------------------------------- #

def test_backstop_five_then_block(mgr):
    for _ in range(MAX_RINGS_PER_DAY):
        r = mgr.ring(urgency="normal", type_="watcher", title="t", detail="d",
                     signals=FREE_SIGNALS)
        assert r is not None
    sixth = mgr.ring(urgency="normal", type_="watcher", title="t", detail="d",
                     signals=FREE_SIGNALS)
    assert sixth is None
    assert "backstop" in mgr.last_suppression


def test_urgent_breaks_through_backstop(mgr):
    for _ in range(MAX_RINGS_PER_DAY):
        mgr.ring(urgency="normal", type_="watcher", title="t", detail="d",
                 signals=FREE_SIGNALS)
    for kind in URGENT_KINDS:
        r = mgr.ring(urgency=kind, type_="safety", title="t", detail="d",
                     signals=FREE_SIGNALS)
        assert r is not None and r.kind == "urgent"


def test_urgent_breaks_through_busy(mgr):
    r = mgr.ring(urgency="disk_failing", type_="safety", title="disk",
                 detail="SSD failing", signals={**FREE_SIGNALS,
                                                 "fullscreen": True})
    assert r is not None and r.kind == "urgent"


def test_backstop_resets_next_day(tmp_path, clock):
    m = RingManager(str(tmp_path / "d"), time_fn=clock)
    for _ in range(MAX_RINGS_PER_DAY):
        m.ring(urgency="normal", type_="w", title="t", detail="d",
               signals=FREE_SIGNALS)
    assert m.ring(urgency="normal", type_="w", title="t", detail="d",
                  signals=FREE_SIGNALS) is None
    clock.advance(86400)  # next day
    assert m.ring(urgency="normal", type_="w", title="t", detail="d",
                  signals=FREE_SIGNALS) is not None


# --------------------------------------------------------------------------- #
# Ring lifecycle: pick up / cut
# --------------------------------------------------------------------------- #

def test_pick_up_returns_detail(mgr):
    r = mgr.ring(urgency="normal", type_="watcher", title="t",
                 detail="speak this", signals=FREE_SIGNALS)
    assert mgr.pick_up(r.id) == "speak this"
    assert r.state == "picked_up"
    assert mgr.pick_up(r.id) is None  # already handled


def test_cut_is_silent_and_logged(tmp_path, clock):
    store = FakeSessionStore()
    m = RingManager(str(tmp_path / "d"), session_store=store,
                    session_id="s1", time_fn=clock)
    r = m.ring(urgency="normal", type_="watcher", title="t", detail="d",
               signals=FREE_SIGNALS)
    assert m.cut(r.id) is True
    assert r.state == "cut"
    assert m.cut(r.id) is False  # already handled
    dismissed = [e for e in store.events
                 if e["type"] == "proactivity.dismissed"]
    assert len(dismissed) == 1
    assert dismissed[0]["payload"]["ring_id"] == r.id


def test_cut_streak_suppresses_type(mgr, clock):
    for _ in range(CUT_STREAK_SUPPRESS):
        r = mgr.ring(urgency="normal", type_="naggy", title="t", detail="d",
                     signals=FREE_SIGNALS)
        assert r is not None
        mgr.cut(r.id)
    assert mgr.is_suppressed("naggy") is True
    assert mgr.ring(urgency="normal", type_="naggy", title="t", detail="d",
                    signals=FREE_SIGNALS) is None
    # Other types unaffected (next day, so the backstop doesn't interfere).
    clock.advance(86400)
    assert mgr.ring(urgency="normal", type_="watcher", title="t", detail="d",
                    signals=FREE_SIGNALS) is not None


def test_pick_up_resets_cut_streak(mgr, clock):
    for _ in range(CUT_STREAK_SUPPRESS - 1):
        r = mgr.ring(urgency="normal", type_="naggy", title="t", detail="d",
                     signals=FREE_SIGNALS)
        mgr.cut(r.id)
    r = mgr.ring(urgency="normal", type_="naggy", title="t", detail="d",
                 signals=FREE_SIGNALS)
    mgr.pick_up(r.id)  # streak resets
    clock.advance(86400)  # fresh budget for the second phase
    for _ in range(CUT_STREAK_SUPPRESS - 1):
        r = mgr.ring(urgency="normal", type_="naggy", title="t", detail="d",
                     signals=FREE_SIGNALS)
        assert r is not None
        mgr.cut(r.id)
    assert mgr.is_suppressed("naggy") is False


def test_unsuppress_reenables(tmp_path, clock):
    m = RingManager(str(tmp_path / "d"), time_fn=clock)
    for _ in range(CUT_STREAK_SUPPRESS):
        r = m.ring(urgency="normal", type_="naggy", title="t", detail="d",
                   signals=FREE_SIGNALS)
        m.cut(r.id)
    m.unsuppress("naggy")
    clock.advance(86400)  # fresh budget; suppression was the only blocker
    assert m.ring(urgency="normal", type_="naggy", title="t", detail="d",
                  signals=FREE_SIGNALS) is not None


# --------------------------------------------------------------------------- #
# Watcher: off by default, floor enforced, RAM-only by structure
# --------------------------------------------------------------------------- #

def test_watcher_off_by_default(tmp_path, clock):
    m = RingManager(str(tmp_path / "d"), time_fn=clock)
    w = Watcher(m, observer=lambda: None, interval_s=3600)
    assert w.enabled is False
    assert w._thread is None


def test_watcher_refuses_sub_60s_interval(tmp_path, clock):
    m = RingManager(str(tmp_path / "d"), time_fn=clock)
    with pytest.raises(ValueError):
        Watcher(m, interval_s=59)
    with pytest.raises(ValueError):
        Watcher(m, interval_s=0)
    Watcher(m, interval_s=60)  # floor itself is fine


def test_watcher_enable_disable_immediate(tmp_path, clock):
    m = RingManager(str(tmp_path / "d"), time_fn=clock)
    w = Watcher(m, observer=lambda: None, interval_s=3600)
    w.enable()
    assert w.enabled is True and w._thread is not None
    w.disable()
    assert w.enabled is False
    assert w._thread is None or not w._thread.is_alive()


def test_watcher_cycle_rings_on_candidate(tmp_path, clock):
    m = RingManager(str(tmp_path / "d"), time_fn=clock)
    w = Watcher(m,
                observer=lambda: {"title": "stuck?",
                                  "detail": "20 min on this error",
                                  "type": "watcher", "urgency": "normal"},
                interval_s=3600,
                signals_fn=lambda: FREE_SIGNALS)
    w._cycle()
    assert w.rang == 1
    assert w.cycles == 1


def test_watcher_cycle_quiet_on_none(tmp_path, clock):
    m = RingManager(str(tmp_path / "d"), time_fn=clock)
    w = Watcher(m, observer=lambda: None, interval_s=3600,
                signals_fn=lambda: FREE_SIGNALS)
    w._cycle()
    assert w.rang == 0


def test_watcher_captures_never_touch_disk(tmp_path, clock):
    """The observer owns capture->triage->discard in RAM. The watcher only
    ever sees a candidate dict. Assert no capture bytes land on disk."""
    data = tmp_path / "data"
    m = RingManager(str(data), time_fn=clock)

    def observer():
        fake_pixels = b"\x89PNG" + os.urandom(4096)  # never leaves RAM
        assert len(fake_pixels) > 0
        return {"title": "t", "detail": "d", "type": "watcher",
                "urgency": "normal"}

    w = Watcher(m, observer=observer, interval_s=3600,
                signals_fn=lambda: FREE_SIGNALS)
    w._cycle()
    allowed = {"rings.json", "learning.json"}
    on_disk = {p.name for p in data.iterdir() if p.is_file()}
    assert on_disk <= allowed, on_disk


# --------------------------------------------------------------------------- #
# Reminders: durability invariants
# --------------------------------------------------------------------------- #

def test_schedule_persists_before_ack(tmp_path, clock):
    s = ReminderStore(str(tmp_path / "d"), time_fn=clock)
    rid = s.schedule(clock() + 3600, "call mom")
    # The file must exist the moment schedule() returns — the ack is only
    # valid because the bytes are already on disk.
    raw = json.loads((tmp_path / "d" / "reminders.json").read_text())
    assert rid in raw["reminders"]


def test_reminder_survives_restart(tmp_path, clock):
    d = str(tmp_path / "d")
    s1 = ReminderStore(d, time_fn=clock)
    rid = s1.schedule(clock() + 3600, "call mom")
    del s1  # simulated restart
    s2 = ReminderStore(d, time_fn=clock)
    assert any(r["id"] == rid for r in s2.list())


def test_due_and_fire(tmp_path, clock):
    s = ReminderStore(str(tmp_path / "d"), time_fn=clock)
    rid = s.schedule(clock() + 10, "stand up")
    assert s.due() == []
    clock.advance(11)
    due = s.due()
    assert [r["id"] for r in due] == [rid]
    fired = s.fire(rid)
    assert fired["text"] == "stand up"
    assert s.due() == []  # one-shot: gone after firing


def test_rearm_before_announce(tmp_path, clock):
    """INVARIANT: the next occurrence is on disk BEFORE the current one is
    marked fired. A crash after fire() returns loses nothing."""
    d = str(tmp_path / "d")
    s = ReminderStore(d, time_fn=clock)
    rid = s.schedule(clock() + 10, "hourly check", repeat_s=3600)
    clock.advance(11)
    s.fire(rid)
    # Fresh store (simulated restart right after fire): the NEXT occurrence
    # must already exist, and the old one must be marked fired.
    s2 = ReminderStore(d, time_fn=clock)
    live = [r for r in s2.list() if not r["fired"]]
    assert len(live) == 1
    assert live[0]["text"] == "hourly check"
    assert live[0]["id"] != rid


def test_schedule_validates_plain_words(tmp_path, clock):
    s = ReminderStore(str(tmp_path / "d"), time_fn=clock)
    with pytest.raises(ReminderError, match="already passed"):
        s.schedule(clock() - 10, "too late")
    with pytest.raises(ReminderError, match="what to remind"):
        s.schedule(clock() + 10, "   ")
    with pytest.raises(ReminderError, match="didn't catch the time"):
        s.schedule("banana", "nope")
    with pytest.raises(ReminderError, match="too long"):
        s.schedule(clock() + 10, "x" * 501)


def test_cancel(tmp_path, clock):
    s = ReminderStore(str(tmp_path / "d"), time_fn=clock)
    rid = s.schedule(clock() + 60, "x")
    assert s.cancel(rid) is True
    assert s.cancel(rid) is False
    assert s.list() == []


def test_fire_idempotent(tmp_path, clock):
    s = ReminderStore(str(tmp_path / "d"), time_fn=clock)
    rid = s.schedule(clock() + 10, "x")
    clock.advance(11)
    assert s.fire(rid) is not None
    assert s.fire(rid) is None
    assert s.fire("nope") is None
