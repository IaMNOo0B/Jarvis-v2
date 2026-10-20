"""Tests for jarvis/patterns.py — confirmed-pattern memory.

Derivation mirrors skill_foundry's strict success semantics over
session-store-shaped event dicts (get_events() output). The lifecycle
proof that matters: suggest -> decline -> the pattern NEVER returns,
even with stronger later evidence and even across a fresh PatternStore
over the same data dir (restart durability). Confirm path is proven
against a real Memory (fact lands with provenance).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.memory import Memory
from jarvis.patterns import (
    MIN_PATTERN_COUNT,
    MIN_PATTERN_DAYS,
    PatternStore,
    pattern_key,
    propose_patterns,
)

_seq = [0]


def _event(type_, ts, payload=None, causal_parent=None, event_id=None):
    _seq[0] += 1
    return {"event_id": event_id or f"e{_seq[0]}", "session_id": "s1",
            "seq": _seq[0], "trace_id": "t", "ts": ts, "type": type_,
            "causal_parent": causal_parent, "actor": "brain",
            "trust": "user", "payload": payload or {}}


def success(tool, ts, verdict="allow", executed=None, ok=True):
    """A tool.call + linked tool.result pair, brain.py's shape."""
    payload = {"tool": tool, "args": {}, "gate_verdict": verdict}
    if executed is not None:
        payload["executed"] = executed
    call = _event("tool.call", ts, payload)
    res = _event("tool.result", ts, {"ok": ok, "output": "..."},
                 causal_parent=call["event_id"])
    return [call, res]


def habit(tool="web_search", hour=22, days=("2026-10-17", "2026-10-18",
                                           "2026-10-19"),
          per_day=(2, 1, 1)):
    """Successful calls of `tool` at `hour` (UTC), spread over days."""
    events = []
    for day, n in zip(days, per_day):
        for i in range(n):
            events += success(tool, f"{day}T{hour:02d}:{10 + i:02d}:00+00:00")
    return events


# ---------------------------------------------------------------- derivation

class TestPropose:
    def test_threshold_met_proposes(self):
        props = propose_patterns(habit())
        assert len(props) == 1
        p = props[0]
        assert p.tool == "web_search" and p.hour == 22
        assert p.count == 4 and p.days == 3
        assert p.key == "pattern:web_search@22"
        assert "web_search" in p.text

    def test_below_count_not_proposed(self):
        # 3 occurrences over 3 days: cross-day but too few.
        assert propose_patterns(habit(per_day=(1, 1, 1))) == []

    def test_below_days_not_proposed(self):
        # 6 occurrences but all inside 2 days: one busy stretch,
        # not a habit.
        events = habit(days=("2026-10-17", "2026-10-18"), per_day=(3, 3))
        assert propose_patterns(events) == []

    def test_hours_are_separate_buckets(self):
        events = habit(hour=9, per_day=(2, 1, 1)) + \
            habit(hour=22, per_day=(1, 1, 1))
        props = propose_patterns(events)
        assert [p.key for p in props] == ["pattern:web_search@09"]

    def test_failures_denials_proposals_never_count(self):
        events = []
        days = ("2026-10-17", "2026-10-18", "2026-10-19")
        for day in days:
            for _ in range(2):
                ts = f"{day}T22:15:00+00:00"
                events += success("web_search", ts, ok=False)       # failed
                events += success("web_search", ts, verdict="deny")  # denied
                events += success("web_search", ts, verdict="require_approval",
                                  executed=False)                    # proposal
                call = _event("tool.call", ts, {"tool": "web_search",
                                                "gate_verdict": "allow"})
                events.append(call)  # no result at all -> doesn't count
        assert propose_patterns(events) == []

    def test_call_ref_linking_counts(self):
        events = []
        for day in ("2026-10-17", "2026-10-18", "2026-10-19", "2026-10-19"):
            call = _event("tool.call", f"{day}T08:05:00+00:00",
                          {"tool": "clock_now", "gate_verdict": "allow"})
            res = _event("tool.result", f"{day}T08:05:01+00:00",
                         {"ok": True, "call_ref": call["event_id"]})
            events += [call, res]
        props = propose_patterns(events)
        assert [p.key for p in props] == ["pattern:clock_now@08"]
        assert props[0].count == 4 and props[0].days == 3

    def test_existing_excluded_in_all_forms(self):
        events = habit()
        key = pattern_key("web_search", 22)
        assert propose_patterns(events, existing=[key]) == []
        assert propose_patterns(events, existing=[{"key": key}]) == []
        first = propose_patterns(events)
        assert propose_patterns(events, existing=first) == []

    def test_deterministic_order_strongest_first(self):
        events = habit(tool="alpha", per_day=(3, 3, 3)) + \
            habit(tool="beta", per_day=(2, 1, 1))
        props = propose_patterns(events)
        assert [p.tool for p in props] == ["alpha", "beta"]

    def test_threshold_constants_are_the_documented_ones(self):
        assert MIN_PATTERN_COUNT == 4 and MIN_PATTERN_DAYS == 3

    def test_garbage_events_ignored(self):
        events = [{"type": "tool.call", "ts": "not-a-date",
                   "payload": {"tool": "x"}, "event_id": "e1"},
                  {"type": "user.message", "ts": "2026-10-19T22:00:00+00:00",
                   "payload": {}, "event_id": "e2"}]
        assert propose_patterns(events) == []


# ----------------------------------------------------------------- lifecycle

@pytest.fixture
def store(tmp_path):
    return PatternStore(tmp_path / "data")


class TestLifecycle:
    def test_suggest_persists_and_is_idempotent(self, store):
        fresh = store.suggest(habit())
        assert [p.key for p in fresh] == ["pattern:web_search@22"]
        assert [r["key"] for r in store.pending()] == [fresh[0].key]
        assert store.suggest(habit()) == []  # never minted twice

    def test_decline_is_forever_even_with_stronger_evidence(self, store):
        key = store.suggest(habit())[0].key
        out = store.decline(key)
        assert out["status"] == "declined" and out["suppressed"] is True
        assert store.pending() == []
        # Much stronger evidence later: still never returns.
        stronger = habit(per_day=(5, 5, 5, 5),
                         days=("2026-10-17", "2026-10-18",
                               "2026-10-19", "2026-10-20"))
        assert store.suggest(stronger) == []
        assert propose_patterns(stronger,
                                existing=store.suppressed_keys()) == []

    def test_decline_survives_restart(self, tmp_path):
        s1 = PatternStore(tmp_path / "data")
        key = s1.suggest(habit())[0].key
        s1.decline(key)
        s2 = PatternStore(tmp_path / "data")  # fresh instance, same dir
        assert s2.is_suppressed(key)
        assert s2.suggest(habit(per_day=(9, 9, 9))) == []

    def test_decline_mirrors_into_proactivity_suppression(self, store,
                                                            tmp_path):
        key = store.suggest(habit())[0].key
        out = store.decline(key)
        assert out["mirrored"] is True
        from jarvis.proactivity import SuppressionStore
        sup = SuppressionStore(str(tmp_path / "data"))
        assert sup.is_suppressed("patterns", {"shape": key})

    def test_confirm_writes_fact_with_provenance(self, tmp_path):
        memory = Memory(str(tmp_path / "memory.db"))
        store = PatternStore(tmp_path / "data", memory=memory)
        key = store.suggest(habit())[0].key
        out = store.confirm(key)
        assert out["status"] == "confirmed"
        assert out["fact"]["op"] == "ADD"
        fact = memory.get_fact(key)
        assert fact is not None
        assert fact["source"] == "patterns"
        assert fact["tier"] == "user"
        assert fact["value"] == store.get(key)["text"]
        assert 0.80 <= fact["confidence"] <= 0.95
        assert store.pending() == []

    def test_confirm_without_memory_is_status_only(self, store):
        key = store.suggest(habit())[0].key
        out = store.confirm(key)
        assert out["fact"] is None and out["status"] == "confirmed"

    def test_confirm_declined_raises(self, store):
        key = store.suggest(habit())[0].key
        store.decline(key)
        with pytest.raises(ValueError):
            store.confirm(key)

    def test_unknown_keys_fail_loud(self, store):
        with pytest.raises(KeyError):
            store.decline("pattern:nope@01")
        with pytest.raises(KeyError):
            store.confirm("pattern:nope@01")

    def test_confirmed_pattern_not_reproposed(self, store):
        key = store.suggest(habit())[0].key
        store.confirm(key)
        assert store.suggest(habit(per_day=(4, 4, 4))) == []
        assert store.get(key)["status"] == "confirmed"
