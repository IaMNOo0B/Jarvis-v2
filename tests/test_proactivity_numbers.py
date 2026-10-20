"""Tests for the Team 22 numeric pack in jarvis/proactivity.py.

Proactivity governed by numbers, not vibes (dota-ai-coach §1.3 +
vrchat-assistant §1.16, via team22-gaming.md):

  1. Post-interaction silence window (60s): the user just interacted,
     so non-urgent rings hold. Urgent kinds bypass.
  2. Consecutive-failure threshold (3): a source whose checks fail or
     come back empty 3x in a row goes quiet until its next success.
  3. Per-source minimum interval (300s): a declared source cannot mint
     rings more often than that, independent of the 5/day backstop.

All three sit beside the existing backstop/busy/suppression gates and
never weaken them; every clock here is injected.
"""

import pytest

from jarvis.proactivity import (
    DEFAULT_FAIL_THRESHOLD,
    DEFAULT_MIN_INTERVAL_S,
    DEFAULT_SILENCE_AFTER_USER_S,
    RingManager,
    Watcher,
)


# --------------------------------------------------------------------------- #
# Helpers (same patterns as test_proactivity.py)
# --------------------------------------------------------------------------- #

class FakeClock:
    def __init__(self, t=1_700_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture()
def clock():
    return FakeClock()


@pytest.fixture()
def mgr(tmp_path, clock):
    return RingManager(str(tmp_path / "data"), time_fn=clock)


FREE_SIGNALS = {"idle_seconds": 600, "fullscreen": False, "hour": 14,
                "dismissal_streak": 0}

CANDIDATE = {"title": "Update", "detail": "something happened",
             "type": "watcher", "urgency": "normal"}


class ScriptedObserver:
    """Returns queued results in order; exceptions are raised."""

    def __init__(self, results):
        self.results = list(results)

    def __call__(self):
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


# --------------------------------------------------------------------------- #
# The numbers themselves + constructor validation
# --------------------------------------------------------------------------- #

def test_report_defaults_are_the_constants():
    # dota-ai-coach silence_duration_seconds / vrchat-assistant
    # consecutive_fail_threshold + min_interval_sec (team22 §1.3/§1.16).
    assert DEFAULT_SILENCE_AFTER_USER_S == 60
    assert DEFAULT_FAIL_THRESHOLD == 3
    assert DEFAULT_MIN_INTERVAL_S == 300


def test_invalid_numbers_refused(tmp_path):
    with pytest.raises(ValueError):
        RingManager(str(tmp_path / "a"), silence_after_user_s=-1)
    with pytest.raises(ValueError):
        RingManager(str(tmp_path / "b"), source_fail_threshold=0)
    with pytest.raises(ValueError):
        RingManager(str(tmp_path / "c"), min_interval_s=-5)
    with pytest.raises(ValueError):
        RingManager(str(tmp_path / "d"),
                    min_interval_by_source={"x": -1})


# --------------------------------------------------------------------------- #
# 1. Post-interaction silence window
# --------------------------------------------------------------------------- #

class TestSilenceWindow:
    def test_no_activity_no_window(self, mgr):
        assert mgr.last_user_activity is None
        assert mgr.in_silence_window() is False
        ring = mgr.ring("normal", "watcher", "t", "d", signals=FREE_SIGNALS)
        assert ring is not None

    def test_ring_held_inside_window(self, mgr, clock):
        mgr.note_user_activity()
        clock.advance(30)
        assert mgr.in_silence_window() is True
        ring = mgr.ring("normal", "watcher", "t", "d", signals=FREE_SIGNALS)
        assert ring is None
        assert "silence" in mgr.last_suppression

    def test_window_boundary(self, mgr, clock):
        mgr.note_user_activity()
        clock.advance(59)
        assert mgr.ring("normal", "watcher", "t", "d",
                        signals=FREE_SIGNALS) is None
        clock.advance(1)  # exactly 60s after the interaction
        assert mgr.in_silence_window() is False
        assert mgr.ring("normal", "watcher", "t", "d",
                        signals=FREE_SIGNALS) is not None

    def test_urgent_bypasses_window(self, mgr, clock):
        mgr.note_user_activity()
        clock.advance(5)
        ring = mgr.ring("disk_failing", "safety", "disk", "SSD failing",
                        signals=FREE_SIGNALS)
        assert ring is not None and ring.kind == "urgent"

    def test_new_activity_refreshes_window(self, mgr, clock):
        mgr.note_user_activity()
        clock.advance(50)
        mgr.note_user_activity()  # user spoke again at +50
        clock.advance(50)         # +100 from the first, +50 from the last
        assert mgr.ring("normal", "watcher", "t", "d",
                        signals=FREE_SIGNALS) is None
        clock.advance(11)         # +61 from the last interaction
        assert mgr.ring("normal", "watcher", "t", "d",
                        signals=FREE_SIGNALS) is not None

    def test_explicit_timestamp_accepted(self, mgr, clock):
        mgr.note_user_activity(clock() - 120)  # two minutes ago
        assert mgr.in_silence_window() is False
        assert mgr.ring("normal", "watcher", "t", "d",
                        signals=FREE_SIGNALS) is not None

    def test_window_disabled_with_zero(self, tmp_path, clock):
        m = RingManager(str(tmp_path / "d"), time_fn=clock,
                        silence_after_user_s=0)
        m.note_user_activity()
        assert m.in_silence_window() is False
        assert m.ring("normal", "watcher", "t", "d",
                      signals=FREE_SIGNALS) is not None

    def test_held_ring_does_not_burn_daily_budget(self, mgr, clock):
        mgr.note_user_activity()
        assert mgr.ring("normal", "watcher", "t", "d",
                        signals=FREE_SIGNALS) is None
        clock.advance(61)
        # The held attempt never reached the backstop counter: the
        # full day's budget of 5 is still available afterwards.
        for _ in range(5):
            assert mgr.ring("normal", "watcher", "t", "d",
                            signals=FREE_SIGNALS) is not None
        assert mgr.ring("normal", "watcher", "t", "d",
                        signals=FREE_SIGNALS) is None
        assert "backstop" in mgr.last_suppression

    def test_watcher_delegate_starts_window(self, tmp_path, clock):
        rm = RingManager(str(tmp_path / "d"), time_fn=clock)
        w = Watcher(rm, observer=lambda: CANDIDATE, interval_s=3600,
                    signals_fn=lambda: FREE_SIGNALS)
        w.note_user_activity()
        w._cycle()
        assert w.rang == 0  # held: the user JUST interacted
        clock.advance(61)
        w._cycle()
        assert w.rang == 1


# --------------------------------------------------------------------------- #
# 2. Consecutive-failure threshold per source
# --------------------------------------------------------------------------- #

class TestSourceFailureThreshold:
    def test_two_failures_do_not_mute(self, mgr):
        assert mgr.note_source_check("feed", False) == 1
        assert mgr.note_source_check("feed", False) == 2
        assert mgr.source_fail_streak("feed") == 2
        assert mgr.source_muted("feed") is False
        assert mgr.ring("normal", "feed", "t", "d",
                        signals=FREE_SIGNALS) is not None

    def test_third_failure_mutes(self, mgr):
        for _ in range(DEFAULT_FAIL_THRESHOLD):
            mgr.note_source_check("feed", False)
        assert mgr.source_muted("feed") is True
        assert mgr.ring("normal", "feed", "t", "d",
                        signals=FREE_SIGNALS) is None
        assert "muted" in mgr.last_suppression

    def test_success_resets_streak(self, mgr):
        mgr.note_source_check("feed", False)
        mgr.note_source_check("feed", False)
        assert mgr.note_source_check("feed", True) == 0
        mgr.note_source_check("feed", False)
        mgr.note_source_check("feed", False)
        assert mgr.source_muted("feed") is False  # only 2 in a row
        assert mgr.ring("normal", "feed", "t", "d",
                        signals=FREE_SIGNALS) is not None

    def test_success_revives_muted_source(self, mgr):
        for _ in range(3):
            mgr.note_source_check("feed", False)
        assert mgr.source_muted("feed") is True
        mgr.note_source_check("feed", True)
        assert mgr.source_muted("feed") is False
        assert mgr.ring("normal", "feed", "t", "d",
                        signals=FREE_SIGNALS) is not None

    def test_failures_are_per_source(self, mgr):
        for _ in range(3):
            mgr.note_source_check("noisy", False)
        assert mgr.source_muted("noisy") is True
        assert mgr.source_fail_streak("quiet") == 0
        assert mgr.source_muted("quiet") is False
        assert mgr.ring("normal", "quiet", "t", "d",
                        signals=FREE_SIGNALS) is not None

    def test_urgent_bypasses_mute(self, mgr):
        for _ in range(3):
            mgr.note_source_check("safety", False)
        assert mgr.source_muted("safety") is True
        ring = mgr.ring("security_event", "safety", "t", "d",
                        signals=FREE_SIGNALS)
        assert ring is not None and ring.kind == "urgent"


class TestWatcherFailureAccounting:
    def test_empty_checks_mute_then_candidate_revives(self, tmp_path, clock):
        rm = RingManager(str(tmp_path / "d"), time_fn=clock)
        obs = ScriptedObserver([None, None, None, CANDIDATE])
        w = Watcher(rm, observer=obs, interval_s=3600,
                    signals_fn=lambda: FREE_SIGNALS)
        for _ in range(3):
            w._cycle()
        assert rm.source_muted("watcher") is True
        assert w.rang == 0
        w._cycle()  # a real candidate = the next success
        assert rm.source_muted("watcher") is False
        assert rm.source_fail_streak("watcher") == 0
        assert w.rang == 1

    def test_raising_observer_counts_failures(self, tmp_path, clock):
        rm = RingManager(str(tmp_path / "d"), time_fn=clock)
        obs = ScriptedObserver([RuntimeError("boom")] * 3 + [CANDIDATE])
        w = Watcher(rm, observer=obs, interval_s=3600,
                    signals_fn=lambda: FREE_SIGNALS)
        for _ in range(3):
            with pytest.raises(RuntimeError):
                w._cycle()  # propagates exactly as before the pack
        assert rm.source_muted("watcher") is True
        w._cycle()
        assert w.rang == 1
        assert rm.source_muted("watcher") is False

    def test_candidate_type_is_its_own_source(self, tmp_path, clock):
        rm = RingManager(str(tmp_path / "d"), time_fn=clock)
        feed = {"title": "f", "detail": "d", "type": "feed"}
        obs = ScriptedObserver([None, None, None, feed])
        w = Watcher(rm, observer=obs, interval_s=3600,
                    signals_fn=lambda: FREE_SIGNALS)
        for _ in range(3):
            w._cycle()
        assert rm.source_muted("watcher") is True
        w._cycle()  # 'feed' succeeds on its own streak, unaffected
        assert w.rang == 1
        assert rm.source_fail_streak("feed") == 0
        assert rm.source_muted("watcher") is True  # still muted

    def test_watcher_delegates(self, tmp_path, clock):
        rm = RingManager(str(tmp_path / "d"), time_fn=clock)
        w = Watcher(rm, observer=lambda: None, interval_s=3600)
        for _ in range(3):
            w.note_check_result("ext", False)
        assert w.source_muted("ext") is True
        w.note_check_result("ext", True)
        assert w.source_muted("ext") is False


# --------------------------------------------------------------------------- #
# 3. Per-source minimum interval
# --------------------------------------------------------------------------- #

class TestMinInterval:
    def test_second_ring_inside_interval_held(self, mgr, clock):
        assert mgr.ring("normal", "watcher", "t", "d",
                        signals=FREE_SIGNALS, source="disk") is not None
        assert mgr.ring("normal", "watcher", "t", "d",
                        signals=FREE_SIGNALS, source="disk") is None
        assert "min interval" in mgr.last_suppression
        clock.advance(299)
        assert mgr.ring("normal", "watcher", "t", "d",
                        signals=FREE_SIGNALS, source="disk") is None
        clock.advance(2)  # 301s since the mint
        assert mgr.ring("normal", "watcher", "t", "d",
                        signals=FREE_SIGNALS, source="disk") is not None

    def test_interval_is_per_source(self, mgr):
        assert mgr.ring("normal", "watcher", "t", "d",
                        signals=FREE_SIGNALS, source="a") is not None
        assert mgr.ring("normal", "watcher", "t", "d",
                        signals=FREE_SIGNALS, source="b") is not None

    def test_unsourced_rings_are_not_interval_tracked(self, mgr):
        # Legacy/direct rings carry no source identity; the 5/day
        # backstop alone governs them (existing behaviour, unchanged).
        for _ in range(3):
            assert mgr.ring("normal", "watcher", "t", "d",
                            signals=FREE_SIGNALS) is not None

    def test_per_source_override(self, tmp_path, clock):
        m = RingManager(str(tmp_path / "d"), time_fn=clock,
                        min_interval_by_source={"fast": 10})
        assert m.ring("normal", "watcher", "t", "d",
                      signals=FREE_SIGNALS, source="fast") is not None
        assert m.ring("normal", "watcher", "t", "d",
                      signals=FREE_SIGNALS, source="slow") is not None
        clock.advance(11)
        assert m.ring("normal", "watcher", "t", "d",
                      signals=FREE_SIGNALS, source="fast") is not None
        # 'slow' still answers to the 300s default.
        assert m.ring("normal", "watcher", "t", "d",
                      signals=FREE_SIGNALS, source="slow") is None

    def test_zero_interval_disables(self, tmp_path, clock):
        m = RingManager(str(tmp_path / "d"), time_fn=clock,
                        min_interval_s=0)
        assert m.ring("normal", "watcher", "t", "d",
                      signals=FREE_SIGNALS, source="disk") is not None
        assert m.ring("normal", "watcher", "t", "d",
                      signals=FREE_SIGNALS, source="disk") is not None

    def test_both_limits_apply_backstop_still_caps(self, tmp_path, clock):
        # Interval off: sourced rings still hit the 5/day backstop.
        m = RingManager(str(tmp_path / "d"), time_fn=clock,
                        min_interval_s=0)
        for _ in range(5):
            assert m.ring("normal", "watcher", "t", "d",
                          signals=FREE_SIGNALS, source="disk") is not None
        assert m.ring("normal", "watcher", "t", "d",
                      signals=FREE_SIGNALS, source="disk") is None
        assert "backstop" in m.last_suppression

    def test_urgent_mint_starts_the_sources_clock(self, mgr, clock):
        assert mgr.ring("normal", "watcher", "t", "d",
                        signals=FREE_SIGNALS, source="s") is not None
        clock.advance(10)
        # Urgent is never gated, even inside the interval...
        ring = mgr.ring("disk_failing", "safety", "t", "d",
                        signals=FREE_SIGNALS, source="s")
        assert ring is not None and ring.kind == "urgent"
        # ...but its mint counts: the source minted 10s ago, so a
        # normal ring 200s later is still inside 300s of that mint.
        clock.advance(200)
        assert mgr.ring("normal", "watcher", "t", "d",
                        signals=FREE_SIGNALS, source="s") is None
        clock.advance(101)  # 301s since the urgent mint
        assert mgr.ring("normal", "watcher", "t", "d",
                        signals=FREE_SIGNALS, source="s") is not None

    def test_named_watcher_is_interval_governed(self, tmp_path, clock):
        rm = RingManager(str(tmp_path / "d"), time_fn=clock)
        w = Watcher(rm, observer=lambda: CANDIDATE, interval_s=3600,
                    signals_fn=lambda: FREE_SIGNALS, source="screen")
        w._cycle()
        assert w.rang == 1
        w._cycle()  # same source, same instant: held by the interval
        assert w.rang == 1
        assert "min interval" in (rm.last_suppression or "")
        clock.advance(301)
        w._cycle()
        assert w.rang == 2

    def test_unnamed_watcher_keeps_legacy_cadence(self, tmp_path, clock):
        rm = RingManager(str(tmp_path / "d"), time_fn=clock)
        w = Watcher(rm, observer=lambda: CANDIDATE, interval_s=3600,
                    signals_fn=lambda: FREE_SIGNALS)
        w._cycle()
        w._cycle()  # no declared source: no interval tracking
        assert w.rang == 2
