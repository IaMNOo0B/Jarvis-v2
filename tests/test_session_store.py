"""Tests for jarvis/session_store.py. All must pass. No mocks of the store itself."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.session_store import SessionStore  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    s = SessionStore(str(tmp_path / "sessions.db"))
    yield s
    s.close()


def test_append_replay_order(store):
    sid = store.create_session("owais", "desktop")
    ids = [store.emit(sid, "user.message", {"text": "msg %d" % i}, actor="user")
           for i in range(5)]
    events = store.get_events(sid)
    assert [e["seq"] for e in events] == [1, 2, 3, 4, 5]
    assert [e["event_id"] for e in events] == ids
    assert len(set(ids)) == 5  # ULIDs unique
    # ULIDs sort roughly by time (monotonic non-decreasing here)
    assert ids == sorted(ids)
    # payloads round-trip
    assert events[2]["payload"] == {"text": "msg 2"}
    assert events[0]["trust"] == "user"


def test_causal_chain(store):
    sid = store.create_session("owais", "desktop")
    root = store.emit(sid, "user.message", {"text": "hi"}, actor="user")
    call = store.emit(sid, "tool.call", {"tool": "notes.write"},
                      actor="brain", trust="system", causal_parent=root)
    grant = store.emit(sid, "approval.granted", {"ok": True},
                       actor="user", causal_parent=call)
    chain = store.causal_chain(grant)
    assert [e["event_id"] for e in chain] == [grant, call, root]
    assert chain[0]["type"] == "approval.granted"
    # unknown event -> empty chain, no crash
    assert store.causal_chain("0" * 26) == []


def test_jsonl_spillover(store, tmp_path):
    sid = store.create_session("owais", "desktop")
    eid = store.emit(sid, "user.message", {"text": "spill"}, actor="user")
    day_files = [f for f in os.listdir(str(tmp_path))
                 if f.startswith("sessions-") and f.endswith(".jsonl")]
    assert len(day_files) == 1
    lines = open(os.path.join(str(tmp_path), day_files[0]),
                 encoding="utf-8").read().strip().split("\n")
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["event_id"] == eid and rec["seq"] == 1


def test_wake_after_crash_recovers(store, tmp_path):
    db = str(tmp_path / "sessions.db")
    sid = store.create_session("owais", "desktop")
    store.emit(sid, "user.message", {"text": "do things"}, actor="user")
    call1 = store.emit(sid, "tool.call", {"tool": "notes.write"},
                      actor="brain", trust="system")
    store.emit(sid, "tool.result", {"ok": True}, actor="tool",
               trust="tool_untrusted", causal_parent=call1)
    store.checkpoint(sid)  # covers seq 1..3
    call2 = store.emit(sid, "tool.call", {"tool": "web.search"},
                      actor="brain", trust="system")
    # --- simulated crash: brand-new store object on the same DB ---
    store.close()
    store2 = SessionStore(db)
    try:
        report = store2.wake(sid)
        assert report["checkpoint_found"] is True
        assert report["checkpoint_ok"] is True
        assert report["checkpoint_seq"] == 3
        assert report["replayed"] == 1  # only the post-checkpoint tool.call
        assert len(report["pending"]) == 1
        assert report["pending"][0]["event_id"] == call2
        assert report["pending"][0]["tool"] == "web.search"
        # crash.marker was written and session is RESUMED
        assert store2.get_session(sid)["state"] == "RESUMED"
        markers = [e for e in store2.get_events(sid)
                   if e["type"] == "crash.marker"]
        assert len(markers) == 1
        assert markers[0]["event_id"] == report["crash_marker"]
        # full history intact and ordered
        assert [e["seq"] for e in store2.get_events(sid)] == [1, 2, 3, 4, 5]
    finally:
        store2.close()


def test_corrupt_checkpoint_quarantine(store, tmp_path):
    sid = store.create_session("owais", "desktop")
    store.emit(sid, "user.message", {"text": "a"}, actor="user")
    store.emit(sid, "user.message", {"text": "b"}, actor="user")
    info = store.checkpoint(sid)
    # corrupt the snapshot on disk
    with open(info["ref"], "ab") as f:
        f.write(b"GARBAGE")
    report = store.wake(sid)
    assert report["checkpoint_found"] is True
    assert report["checkpoint_ok"] is False
    assert report["checkpoint_seq"] == 0  # replay-only from seq 0
    assert report["replayed"] == 2  # both events replayed, nothing lost
    assert any("quarantine" in n for n in report["notes"])
    # quarantine file exists
    cdir = os.path.join(str(tmp_path), "checkpoints")
    assert any(".corrupt-" in f for f in os.listdir(cdir))
    # original events untouched
    assert [e["seq"] for e in store.get_events(sid)] == [1, 2, 3]


def test_tombstone_purges_payload_keeps_order(store):
    sid = store.create_session("owais", "desktop")
    e1 = store.emit(sid, "user.message", {"text": "keep me"}, actor="user")
    e2 = store.emit(sid, "user.message", {"text": "forget me"}, actor="user")
    e3 = store.emit(sid, "user.message", {"text": "keep me too"}, actor="user")
    n = store.tombstone([e2], reason="user deletion request")
    assert n == 1
    events = store.get_events(sid)
    assert [e["event_id"] for e in events] == [e1, e2, e3]
    assert [e["seq"] for e in events] == [1, 2, 3]  # ordering intact
    assert events[1]["payload"] == {}  # content gone
    assert events[0]["payload"] == {"text": "keep me"}
    # tombstone record exists
    cur = store._conn.execute(
        "SELECT reason FROM tombstones WHERE event_id = ?", (e2,))
    assert cur.fetchone()[0] == "user deletion request"
    # causal chain still walks through the tombstoned event
    e4 = store.emit(sid, "tool.call", {"tool": "x"}, actor="brain",
                   trust="system", causal_parent=e2)
    assert [e["event_id"] for e in store.causal_chain(e4)] == [e4, e2]


def test_emit_validates_actor_and_session(store):
    sid = store.create_session("owais", "desktop")
    with pytest.raises(ValueError):
        store.emit(sid, "user.message", {}, actor="hacker")
    with pytest.raises(KeyError):
        store.emit("0" * 26, "user.message", {}, actor="user")
