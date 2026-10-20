"""Builder Team E — watcher state ladder + completion batching.

Covers jarvis/proactivity.py additions: derive_state precedence,
should_ring policy, CompletionBatcher, and Watcher._cycle integration.
The pre-existing structural guarantees (closed urgent enum, 5/day
backstop) are asserted untouched, not re-tested in full.
"""

import pytest

from jarvis.proactivity import (
    MAX_RINGS_PER_DAY,
    STATE_BUSY,
    STATE_DEAD,
    STATE_DONE,
    STATE_FRESH,
    STATE_IDLE,
    STATE_IDLE_ASKED,
    STATE_WAITING,
    URGENT_KINDS,
    CompletionBatcher,
    RingManager,
    Watcher,
    derive_state,
    looks_like_question,
    should_ring,
    urgency_of,
)


# --------------------------------------------------------------------------- #
# derive_state — precedence is the whole point
# --------------------------------------------------------------------------- #

class TestDeriveState:
    def test_dead_beats_everything(self):
        signals = {"alive": False, "waiting_for": "approval",
                   "status": "waiting", "busy": True}
        assert derive_state(signals) == STATE_DEAD

    def test_fresh_beats_waiting(self):
        # Never started, yet somehow flagged waiting: fresh wins.
        signals = {"started": False, "waiting_for": "input"}
        assert derive_state(signals) == STATE_FRESH

    def test_fresh_statuses(self):
        for status in ("fresh", "new", "never_started", "QUEUED"):
            assert derive_state({"status": status}) == STATE_FRESH
        assert derive_state({"never_started": True}) == STATE_FRESH

    def test_waiting_explicit(self):
        assert derive_state({"waiting_for": "a decision"}
                            ) == STATE_WAITING
        assert derive_state({"blocked_reason": "needs PIN"}) == STATE_WAITING
        assert derive_state({"status": "Waiting"}) == STATE_WAITING
        assert derive_state({"status": "needs_you"}) == STATE_WAITING

    def test_waiting_beats_busy(self):
        # Explicit blocked beats inferred busy.
        assert derive_state({"waiting_for": "x", "busy": True}
                            ) == STATE_WAITING

    def test_done(self):
        assert derive_state({"completed": True}) == STATE_DONE
        assert derive_state({"status": "finished"}) == STATE_DONE

    def test_busy(self):
        assert derive_state({"busy": True}) == STATE_BUSY
        assert derive_state({"status": "running"}) == STATE_BUSY

    def test_busy_beats_idle_asked(self):
        # Inference (question tail) never outranks a hard busy signal.
        signals = {"busy": True, "tail_text": "Shall I continue?"}
        assert derive_state(signals) == STATE_BUSY

    def test_idle_asked_by_flag_and_by_tail(self):
        assert derive_state({"tail_is_question": True}) == STATE_IDLE_ASKED
        assert derive_state({"tail_text": "Done.\nWhich file next?"}
                            ) == STATE_IDLE_ASKED
        assert derive_state({"last_text": "Ready when you are?"}
                            ) == STATE_IDLE_ASKED

    def test_idle_fallback(self):
        assert derive_state({}) == STATE_IDLE
        assert derive_state({"status": "idle"}) == STATE_IDLE
        assert derive_state({"tail_text": "All quiet here."}) == STATE_IDLE


class TestLooksLikeQuestion:
    def test_obvious(self):
        assert looks_like_question("Proceed?") is True
        assert looks_like_question("Line one.\nLine two?") is True
        assert looks_like_question("Proceed.") is False
        assert looks_like_question("") is False
        assert looks_like_question(None) is False
        assert looks_like_question("   \n  \n") is False


# --------------------------------------------------------------------------- #
# should_ring — the policy asymmetry
# --------------------------------------------------------------------------- #

class TestShouldRing:
    def test_waiting_rings_immediately_with_reason(self):
        ring, why = should_ring(STATE_WAITING, "needs your PIN")
        assert ring is True
        assert "needs your PIN" in why

    def test_waiting_rings_without_reason_too(self):
        ring, why = should_ring(STATE_WAITING)
        assert ring is True and why

    def test_idle_asked_rings(self):
        ring, _ = should_ring(STATE_IDLE_ASKED)
        assert ring is True

    def test_done_never_rings_solo(self):
        ring, why = should_ring(STATE_DONE)
        assert ring is False
        assert "batch" in why

    def test_fresh_and_dead_never_announced(self):
        assert should_ring(STATE_FRESH)[0] is False
        assert should_ring(STATE_DEAD)[0] is False

    def test_busy_and_idle_silent(self):
        assert should_ring(STATE_BUSY)[0] is False
        assert should_ring(STATE_IDLE)[0] is False
        assert should_ring("nonsense-state")[0] is False


# --------------------------------------------------------------------------- #
# CompletionBatcher
# --------------------------------------------------------------------------- #

class TestCompletionBatcher:
    def test_add_pending_drain(self):
        b = CompletionBatcher()
        b.add("Build A", "ok", ts=1.0)
        b.add("Build B", ts=2.0)
        assert len(b) == 2
        pending = b.pending()
        assert [i["title"] for i in pending] == ["Build A", "Build B"]
        drained = b.drain()
        assert len(drained) == 2
        assert len(b) == 0
        assert b.drain() == []  # drains exactly once

    def test_flush_line(self):
        b = CompletionBatcher()
        assert b.flush_line() is None
        b.add("Tests")
        assert b.flush_line() == "1 thing finished: Tests"
        assert b.flush_line() is None  # already drained
        for t in ("a", "b", "c"):
            b.add(t)
        assert b.flush_line() == "3 things finished: a; b; c"

    def test_flush_line_caps_long_batches(self):
        b = CompletionBatcher()
        for i in range(7):
            b.add(f"t{i}")
        line = b.flush_line()
        assert line.startswith("7 things finished:")
        assert "and 2 more" in line


# --------------------------------------------------------------------------- #
# Watcher integration — ladder states drive ring/batch decisions
# --------------------------------------------------------------------------- #

def _watcher(tmp_path, candidate):
    rm = RingManager(str(tmp_path))
    return Watcher(rm, observer=lambda: candidate, interval_s=60)


class TestWatcherLadderIntegration:
    def test_completion_is_batched_not_rung(self, tmp_path):
        w = _watcher(tmp_path, {"title": "Build done", "detail": "green",
                                "signals": {"completed": True}})
        w._cycle()
        assert w.rang == 0
        assert len(w.completions) == 1
        assert w.completions.pending()[0]["title"] == "Build done"

    def test_waiting_rings(self, tmp_path):
        w = _watcher(tmp_path, {"title": "Blocked", "detail": "needs PIN",
                                "signals": {"waiting_for": "PIN"}})
        w._cycle()
        assert w.rang == 1
        assert len(w.completions) == 0

    def test_fresh_is_silent(self, tmp_path):
        w = _watcher(tmp_path, {"title": "Queued job", "detail": "",
                                "signals": {"started": False}})
        w._cycle()
        assert w.rang == 0 and len(w.completions) == 0

    def test_candidate_without_signals_unchanged(self, tmp_path):
        # Legacy observer contract: no "signals" key -> normal ring path.
        w = _watcher(tmp_path, {"title": "Hi", "detail": "there"})
        w._cycle()
        assert w.rang == 1


# --------------------------------------------------------------------------- #
# Untouched guarantees — the ladder must not weaken them
# --------------------------------------------------------------------------- #

class TestGuaranteesUntouched:
    def test_urgent_enum_still_closed(self):
        assert URGENT_KINDS == ("disk_failing", "security_event",
                                "user_critical")
        assert urgency_of("disk_failing") == "urgent"
        assert urgency_of("totally_made_up") == "normal"
        assert urgency_of("") == "normal"

    def test_backstop_constant(self):
        assert MAX_RINGS_PER_DAY == 5

    def test_waiting_rings_still_hit_backstop(self, tmp_path):
        # Ladder says "deserves a ring"; RingManager's cap still rules.
        rm = RingManager(str(tmp_path))
        w = Watcher(rm, observer=lambda: {
            "title": "Blocked", "detail": "x",
            "signals": {"waiting_for": "you"}}, interval_s=60)
        for _ in range(MAX_RINGS_PER_DAY + 3):
            w._cycle()
        assert w.rang == MAX_RINGS_PER_DAY
