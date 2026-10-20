"""Tests for Builder D diary roll-up (Deus auto-compress pattern, stdlib).

The roll-up is deterministic: counts + top tools + corrections count over
one UTC day of episodes (+ optional session-store envelopes). No LLM.
Covers: day validation/filtering, strict tool-success semantics (denied,
proposed, and failed calls excluded), corrections via golden_pairs,
idempotency through write_fact, provenance (source='diary'), 500-char cap.
"""

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.memory import Memory

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


@pytest.fixture
def mem(tmp_path):
    m = Memory(tmp_path / "mem.db", profile_id="test")
    yield m
    m.close()


def _day(s: str) -> str:
    return s.strftime("%Y-%m-%d")


@pytest.fixture
def mem_with_eps(mem):
    mem.write_episode("opened chrome and checked mail", "sess-1")
    mem.write_episode("set a reminder for tea", "sess-1")
    mem.write_episode("daily standup notes written", "sess-2")
    # one episode planted on another day (raw insert: write_episode is now-only)
    with mem._lock:
        mem._conn.execute(
            "INSERT INTO episodes (profile_id, ts, summary, session_id)"
            " VALUES (?, ?, ?, ?)",
            ("test", "2020-01-01T08:00:00.000+00:00", "ancient episode", "sess-0"),
        )
        mem._conn.commit()
    return mem


def _events(day):
    """Session-store shaped envelopes for a day."""
    def ev(eid, typ, ts_hms, payload, causal=None):
        return {"event_id": eid, "session_id": "sess-1", "seq": 0,
                "ts": f"{day}T{ts_hms}+00:00", "type": typ,
                "causal_parent": causal, "actor": "brain",
                "trust": "user", "payload": payload}

    return [
        # two successful web_search
        ev("c1", "tool.call", "09:00:00", {"tool": "web_search",
                                           "gate_verdict": "allow"}),
        ev("r1", "tool.result", "09:00:05", {"ok": True}, causal="c1"),
        ev("c2", "tool.call", "09:05:00", {"tool": "web_search",
                                           "gate_verdict": "allow_with_undo"}),
        ev("r2", "tool.result", "09:05:05", {"ok": True}, causal="c2"),
        # one successful note_save
        ev("c3", "tool.call", "09:10:00", {"tool": "note_save",
                                           "gate_verdict": "allow"}),
        ev("r3", "tool.result", "09:10:05", {"ok": True}, causal="c3"),
        # denied -> not counted
        ev("c4", "tool.call", "09:15:00", {"tool": "pc.shell",
                                           "gate_verdict": "deny"}),
        # proposed but never executed -> not counted
        ev("c5", "tool.call", "09:20:00",
           {"tool": "pc.click", "gate_verdict": "require_approval",
            "executed": False}),
        # executed but failed -> not counted
        ev("c6", "tool.call", "09:25:00", {"tool": "web_fetch",
                                           "gate_verdict": "allow"}),
        ev("r6", "tool.result", "09:25:05", {"ok": False}, causal="c6"),
        # one correction + one plain message
        ev("m1", "user.message", "09:30:00",
           {"text": "no, make it shorter instead"}),
        ev("m2", "user.message", "09:35:00", {"text": "thanks jarvis"}),
        # an event from a different day -> excluded by ts filter
        ev("c9", "tool.call", "09:00:00",
           {"tool": "web_search", "gate_verdict": "allow"}),
        ev("r9", "tool.result", "09:00:05", {"ok": True}, causal="c9"),
    ]


def test_diary_counts_and_template(mem_with_eps):
    events = _events(TODAY)
    # cheat the different-day event into yesterday's timestamps
    events[-2]["ts"] = events[-2]["ts"].replace(TODAY, "2020-01-01")
    events[-1]["ts"] = events[-1]["ts"].replace(TODAY, "2020-01-01")
    out = mem_with_eps.write_diary_entry(TODAY, events)
    assert out["op"] == "ADD"
    assert out["episodes"] == 3          # today's three, not the ancient one
    assert out["sessions"] == 2
    assert out["top_tools"] == {"web_search": 2, "note_save": 1}
    assert out["corrections"] == 1
    assert len(out["value"]) <= Memory.MAX_VALUE_CHARS
    assert "diary" in out["value"] and "top tools" in out["value"]


def test_diary_provenance(mem_with_eps):
    out = mem_with_eps.write_diary_entry(TODAY)
    fact = mem_with_eps.get_fact(f"diary:{TODAY}")
    assert fact is not None
    assert fact["id"] == out["id"]
    assert fact["source"] == "diary"
    assert fact["tier"] == "inferred"
    assert fact["quarantined"] is False


def test_diary_without_events(mem_with_eps):
    out = mem_with_eps.write_diary_entry(TODAY)
    assert out["top_tools"] == {}
    assert out["corrections"] == 0
    assert out["episodes"] == 3
    assert "first:" in out["value"] and "last:" in out["value"]


def test_diary_idempotent_and_updates(mem_with_eps):
    first = mem_with_eps.write_diary_entry(TODAY, _events(TODAY))
    again = mem_with_eps.write_diary_entry(TODAY, _events(TODAY))
    assert first["op"] == "ADD"
    assert again["op"] == "NOOP"
    assert again["id"] == first["id"]
    # changed input -> UPDATE supersedes with a fresh diary fact
    mem_with_eps.write_episode("one more thing happened", "sess-2")
    updated = mem_with_eps.write_diary_entry(TODAY, _events(TODAY))
    assert updated["op"] == "UPDATE"
    assert updated["id"] != first["id"]
    assert updated["episodes"] == 4


def test_diary_empty_day(mem):
    out = mem.write_diary_entry("2026-02-03")
    assert out["episodes"] == 0
    assert out["sessions"] == 0
    assert "0 episodes, 0 sessions" in out["value"]
    assert mem.get_fact("diary:2026-02-03") is not None


def test_diary_day_validation(mem):
    for bad in ("", "20-1-1", "2026/01/01", "yesterday", "2026-13-40",
                "2026-02-30"):
        with pytest.raises(ValueError):
            mem.write_diary_entry(bad)


def test_diary_value_never_exceeds_cap(mem):
    # many long episode summaries + many tools can't push past 500 chars
    for i in range(8):
        mem.write_episode(f"episode {i} " + "x" * 300, f"s{i}")
    events = _events(TODAY)
    out = mem.write_diary_entry(TODAY, events)
    assert len(out["value"]) <= Memory.MAX_VALUE_CHARS
    assert mem.get_fact(f"diary:{TODAY}")["value"] == out["value"]
