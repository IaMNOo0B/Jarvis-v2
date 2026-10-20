"""Tests for Builder D skill_foundry (Nolan solidification + anticipation).

Uses a real SessionStore: tool.call/tool.result pairs are emitted exactly
the way brain.py emits them (gate_verdict on the call, ok flag on the
causally-linked result). Covers: strict success semantics (deny, proposal,
failure, missing result never count), sequence thresholds and the
subsumption filter, quarantined draft drafting (manifest parses via the
real registry validator, sidecar + note, idempotency, nothing is ever
approved), and hourly anticipation with crafted timestamps.
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.session_store import SessionStore
from jarvis.skill_foundry import SkillFoundry
from jarvis.skills.registry import SkillManifest


@pytest.fixture
def store(tmp_path):
    s = SessionStore(str(tmp_path / "sessions.db"))
    yield s
    s.close()


def call(store, sid, tool, verdict="allow", executed=None):
    payload = {"tool": tool, "args": {}, "gate_verdict": verdict}
    if executed is not None:
        payload["executed"] = executed
    return store.emit(sid, "tool.call", payload, actor="brain", trust="user")


def result(store, sid, call_id, ok=True):
    return store.emit(sid, "tool.result", {"ok": ok, "output": "..."},
                      actor="tool", trust="tool_untrusted",
                      causal_parent=call_id)


def success_seq(store, sid, tools):
    for t in tools:
        result(store, sid, call(store, sid, t), ok=True)


def foundry(store, tmp_path):
    return SkillFoundry(store, tmp_path / "data")


# ----------------------------------------------------------- solidification

def test_repeated_successful_sequence_found(store, tmp_path):
    s1 = store.create_session("test", "test")
    s2 = store.create_session("test", "test")
    success_seq(store, s1, ["web_search", "note_save"])
    success_seq(store, s2, ["web_search", "note_save"])
    success_seq(store, s2, ["web_search", "note_save"])
    found = foundry(store, tmp_path).find_sequences()
    seqs = {tuple(d["sequence"]): d for d in found}
    assert seqs[("web_search", "note_save")]["count"] == 3
    assert seqs[("web_search", "note_save")]["sessions"] == 2


def test_below_threshold_not_found(store, tmp_path):
    s1 = store.create_session("test", "test")
    success_seq(store, s1, ["web_search", "note_save"])
    success_seq(store, s1, ["web_search", "note_save"])
    assert foundry(store, tmp_path).find_sequences() == []


def test_failures_denials_proposals_not_counted(store, tmp_path):
    s1 = store.create_session("test", "test")
    for _ in range(4):
        # failed run
        result(store, s1, call(store, s1, "web_fetch"), ok=False)
        # denied call (no result at all)
        call(store, s1, "pc.shell", verdict="deny")
        # proposal never executed
        cid = call(store, s1, "pc.click", verdict="require_approval",
                   executed=False)
        result(store, s1, cid, ok=True)
        # call with no result event
        call(store, s1, "ghost_tool")
    assert foundry(store, tmp_path).find_sequences() == []
    assert foundry(store, tmp_path)._successful_streams().get(s1) is None


def test_longer_pattern_subsumes_shorter(store, tmp_path):
    s1 = store.create_session("test", "test")
    for _ in range(3):
        success_seq(store, s1, ["a_tool", "b_tool", "c_tool"])
    found = foundry(store, tmp_path).find_sequences()
    seqs = [tuple(d["sequence"]) for d in found]
    # (a,b,c) x3 wins; (a,b) and (b,c) have the same count and are subsumed
    assert ("a_tool", "b_tool", "c_tool") in seqs
    assert ("a_tool", "b_tool") not in seqs
    assert ("b_tool", "c_tool") not in seqs


def test_max_window_is_four(store, tmp_path):
    s1 = store.create_session("test", "test")
    for _ in range(3):
        success_seq(store, s1, ["t1", "t2", "t3", "t4", "t5"])
    found = foundry(store, tmp_path).find_sequences()
    assert all(len(d["sequence"]) <= 4 for d in found)
    assert any(len(d["sequence"]) == 4 for d in found)


# ----------------------------------------------------------------- drafting

def test_draft_writes_quarantined_package(store, tmp_path):
    s1 = store.create_session("test", "test")
    for _ in range(3):
        success_seq(store, s1, ["web_search", "note_save"])
    f = foundry(store, tmp_path)
    created = f.draft_skills()
    assert len(created) == 1
    pkg = Path(created[0]["path"])
    assert pkg.parent.name == "foundry"
    # manifest is valid under the REAL registry validator, name == folder
    raw = json.loads((pkg / "skill.json").read_text(encoding="utf-8"))
    manifest = SkillManifest.from_dict(raw, source=str(pkg / "skill.json"))
    assert manifest.name == pkg.name == created[0]["name"]
    assert manifest.tools[0].tier == 2
    # sidecar carries provenance; SKILL.md explains the quarantine
    sidecar = json.loads((pkg / "foundry.json").read_text(encoding="utf-8"))
    assert sidecar["sequence"] == ["web_search", "note_save"]
    assert sidecar["occurrences"] == 3
    assert sidecar["status"] == "quarantined-draft"
    note = (pkg / "SKILL.md").read_text(encoding="utf-8")
    assert "QUARANTINED" in note
    # drafting again is a no-op (idempotent)
    assert f.draft_skills() == []


def test_draft_sanitizes_dotted_tool_names(store, tmp_path):
    s1 = store.create_session("test", "test")
    for _ in range(3):
        success_seq(store, s1, ["pc.click", "web_search"])
    f = foundry(store, tmp_path)
    created = f.draft_skills()
    assert len(created) == 1
    raw = json.loads((Path(created[0]["path"]) / "skill.json")
                     .read_text(encoding="utf-8"))
    SkillManifest.from_dict(raw, source="test")  # must not raise


def test_no_candidates_no_drafts(store, tmp_path):
    foundry(store, tmp_path).draft_skills()
    assert not (tmp_path / "data" / "foundry").exists() or \
        list((tmp_path / "data" / "foundry").iterdir()) == []


# -------------------------------------------------------------- anticipation

def _insert_event(store, sid, seq, ts, typ, payload, causal=None,
                  actor="brain"):
    conn = sqlite3.connect(store.db_path)
    conn.execute(
        "INSERT INTO events (event_id, session_id, seq, trace_id, ts, type,"
        " causal_parent, actor, trust, payload)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (f"EV{seq:05d}", sid, seq, "trace", ts, typ, causal, actor, "user",
         json.dumps(payload)),
    )
    conn.commit()
    conn.close()


def test_anticipations_by_hour(store, tmp_path):
    sid = store.create_session("test", "test")
    seq = 100

    def ok_tool(hour, tool):
        nonlocal seq
        seq += 1
        cid = f"EV{seq:05d}"
        _insert_event(store, sid, seq, f"2026-10-19T{hour:02d}:00:00.000+00:00",
                      "tool.call", {"tool": tool, "gate_verdict": "allow"})
        seq += 1
        _insert_event(store, sid, seq, f"2026-10-19T{hour:02d}:00:30.000+00:00",
                      "tool.result", {"ok": True}, causal=cid, actor="tool")

    ok_tool(14, "web_search")
    ok_tool(14, "web_search")
    ok_tool(14, "note_save")
    ok_tool(9, "web_search")
    _insert_event(store, sid, 999, "2026-10-19T14:15:00.000+00:00",
                  "user.message", {"text": "hi"})
    f = foundry(store, tmp_path)
    got = f.anticipations(datetime(2026, 10, 20, 14, 45,
                                     tzinfo=timezone.utc))
    by_action = {d["action"]: d for d in got}
    assert by_action["tool:web_search"]["count"] == 2
    assert by_action["tool:note_save"]["count"] == 1
    assert by_action["user.message"]["count"] == 1
    assert all(d["hour"] == 14 for d in got)
    # sorted by count desc
    assert got[0]["action"] == "tool:web_search"
    # hour 9 has only the one search
    morning = f.anticipations(datetime(2026, 10, 20, 9, 5,
                                       tzinfo=timezone.utc))
    assert [(d["action"], d["count"]) for d in morning] == \
        [("tool:web_search", 1)]
    # an hour with nothing -> empty, silence is the correct answer
    assert f.anticipations(datetime(2026, 10, 20, 3, 0,
                                    tzinfo=timezone.utc)) == []


def test_anticipations_naive_now_is_utc(store, tmp_path):
    f = foundry(store, tmp_path)
    assert f.anticipations(datetime(2026, 10, 20, 14, 0)) == []
