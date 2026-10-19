"""Tests for jarvis.memory — Wave 1. Every test asserts behavior, not mocks."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.memory import Memory


@pytest.fixture
def mem(tmp_path):
    m = Memory(tmp_path / "mem.db", profile_id="test")
    yield m
    m.close()


# ------------------------------------------------------------ quarantine gate

def test_web_tier_fact_is_quarantined_and_marked(mem):
    r = mem.write_fact("web_tip", "some web claim", source="example.com",
                       tier="web", confidence=0.5)
    assert r["op"] == "ADD"
    assert r["quarantined"] is True
    # excluded from default recall ...
    assert mem.recall("web_tip") == []
    # ... but retrievable WITH the quarantine flag when asked
    hits = mem.recall("web_tip", include_quarantined=True)
    assert len(hits) == 1
    assert hits[0]["quarantined"] is True
    assert hits[0]["key"] == "web_tip"


def test_tool_tier_fact_is_quarantined(mem):
    r = mem.write_fact("tool_out", "tool said so", source="file_reader",
                       tier="tool", confidence=0.7)
    assert r["quarantined"] is True
    assert mem.recall("tool_out") == []


def test_user_tier_fact_not_quarantined(mem):
    r = mem.write_fact("name", "Owais", source="user", tier="user", confidence=1.0)
    assert r["quarantined"] is False
    hits = mem.recall("name")
    assert len(hits) == 1
    assert hits[0]["quarantined"] is False
    got = mem.get_fact("name")
    assert got["value"] == "Owais"
    assert got["quarantined"] is False


def test_inferred_tier_not_quarantined(mem):
    r = mem.write_fact("pref", "plain english", source="brain",
                       tier="inferred", confidence=0.8)
    assert r["quarantined"] is False


# ------------------------------------------------------- resolve: ADD/UPDATE

def test_update_chains_superseded_by(mem):
    r1 = mem.write_fact("phone", "111", source="user", tier="user", confidence=1.0)
    assert r1["op"] == "ADD"
    r2 = mem.write_fact("phone", "222", source="user", tier="user", confidence=1.0)
    assert r2["op"] == "UPDATE"
    assert r2["id"] != r1["id"]
    # old row carries the superseded_by pointer, never deleted
    with mem._lock:
        old = mem._conn.execute("SELECT superseded_by FROM facts WHERE id = ?",
                                (r1["id"],)).fetchone()
    assert old["superseded_by"] == r2["id"]
    # current value wins
    assert mem.get_fact("phone")["value"] == "222"
    # stale value not retrievable
    assert all(h["snippet"].find("111") == -1 or "222" in h["snippet"]
               for h in mem.recall("phone"))


def test_noop_on_identical_value(mem):
    r1 = mem.write_fact("city", "Mumbai", source="user", tier="user", confidence=1.0)
    r2 = mem.write_fact("city", "Mumbai", source="user", tier="user", confidence=1.0)
    assert r2["op"] == "NOOP"
    assert r2["id"] == r1["id"]
    with mem._lock:
        n = mem._conn.execute(
            "SELECT COUNT(*) AS n FROM facts WHERE key = 'city'").fetchone()["n"]
    assert n == 1


# ------------------------------------------------------------------- forget

def test_forget_verified_empty_via_recall(mem):
    mem.write_fact("secret_x", "hunter2", source="user", tier="user", confidence=1.0)
    assert mem.get_fact("secret_x") is not None
    receipt = mem.forget("secret_x")
    assert receipt["verified"] is True
    assert receipt["tombstoned"] is True
    # verified empty across every read path
    assert mem.get_fact("secret_x") is None
    assert mem.recall("secret_x") == []
    assert mem.recall("secret_x", include_quarantined=True) == []
    assert mem.recall("hunter2") == []
    assert mem.tombstone_count("secret_x") >= 1


def test_forget_removes_fts_copies(mem):
    mem.write_fact("gossip", "zebras paint stripes", source="user",
                   tier="user", confidence=0.9)
    assert mem.recall("zebras") != []
    mem.forget("gossip")
    assert mem.recall("zebras") == []  # FTS token copies gone too


def test_forget_unknown_key_is_safe(mem):
    receipt = mem.forget("never_existed")
    assert receipt["deleted_rows"] == 0
    assert receipt["verified"] is True


# ------------------------------------------------------------------- expiry

def test_expired_fact_returns_none_and_tombstones(mem):
    mem.write_fact("trip", "Goa this week", source="user", tier="user",
                   confidence=1.0, expires_at="2000-01-01T00:00:00+00:00")
    assert mem.get_fact("trip") is None  # auto-expired on read
    assert mem.tombstone_count("trip") >= 1
    assert mem.recall("Goa") == []


def test_unexpired_fact_survives(mem):
    mem.write_fact("trip2", "Goa next week", source="user", tier="user",
                   confidence=1.0, expires_at="2999-01-01T00:00:00+00:00")
    assert mem.get_fact("trip2")["value"] == "Goa next week"


# ----------------------------------------------------------------- episodes

def test_episode_write_and_recall(mem):
    eid = mem.write_episode("Deleted 3 old installers after confirmation",
                            session_id="s1")
    assert isinstance(eid, int)
    hits = mem.recall("installers")
    assert len(hits) == 1
    assert hits[0]["kind"] == "episode"
    assert hits[0]["session_id"] == "s1"
    assert "installers" in hits[0]["snippet"]


def test_episodes_are_append_only(mem):
    e1 = mem.write_episode("first", session_id="s1")
    e2 = mem.write_episode("second", session_id="s1")
    assert e2 > e1
    with mem._lock:
        n = mem._conn.execute("SELECT COUNT(*) AS n FROM episodes").fetchone()["n"]
    assert n == 2  # nothing overwritten


# ------------------------------------------------------------- recall shape

def test_recall_top5_and_snippet_length(mem):
    for i in range(10):
        mem.write_fact(f"fact{i}", f"commonword value number {i}", source="user",
                       tier="user", confidence=0.9)
    hits = mem.recall("commonword")
    assert len(hits) == 5
    assert all(len(h["snippet"]) <= 200 for h in hits)
    assert all(h["id"] is not None for h in hits)  # memory_id for citations
    assert all("quarantined" in h and "confidence" in h for h in hits)


def test_recall_never_dumps_full_long_values(mem):
    long_val = "x" * 500
    mem.write_fact("longk", long_val, source="user", tier="user", confidence=1.0)
    hits = mem.recall("longk")
    assert len(hits[0]["snippet"]) <= 200 < len(long_val)


def test_recall_empty_query(mem):
    assert mem.recall("") == []
    assert mem.recall("   ") == []


# --------------------------------------------------------------- validation

def test_value_over_500_chars_rejected(mem):
    with pytest.raises(ValueError):
        mem.write_fact("k", "x" * 501, source="user", tier="user", confidence=1.0)


def test_invalid_tier_rejected(mem):
    with pytest.raises(ValueError):
        mem.write_fact("k", "v", source="user", tier="admin", confidence=1.0)


def test_invalid_confidence_rejected(mem):
    with pytest.raises(ValueError):
        mem.write_fact("k", "v", source="user", tier="user", confidence=1.5)
    with pytest.raises(ValueError):
        mem.write_fact("k", "v", source="user", tier="user", confidence=-0.1)


def test_empty_key_rejected(mem):
    with pytest.raises(ValueError):
        mem.write_fact("", "v", source="user", tier="user", confidence=1.0)
