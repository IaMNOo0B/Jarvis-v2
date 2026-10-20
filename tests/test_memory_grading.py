"""Tests for memory grading (Team 9 steals): fact_grades side table,
Mnemosyne decay policy with per-kind rates, memory-os trust loop,
engram plan->fingerprint->apply consolidation, migration safety.

Decay math is exercised through consolidate(now_iso=...) with backdated
created_ts rows, the same technique as test_phd_implementations.py.
"""

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.memory import ConsolidationPlan, Memory


@pytest.fixture
def mem(tmp_path):
    m = Memory(tmp_path / "mem.db", profile_id="test")
    yield m
    m.close()


def _backdate(mem, key, days):
    ts = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%S+00:00")
    with mem._lock:
        mem._conn.execute(
            "UPDATE facts SET created_ts = ? WHERE profile_id = ? AND key = ?",
            (ts, mem.profile_id, key))
        mem._conn.commit()


def _now_plus(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


# ------------------------------------------------------------ migration

_OLD_SCHEMA = """
CREATE TABLE facts (
  id INTEGER PRIMARY KEY, profile_id TEXT NOT NULL, key TEXT NOT NULL,
  value TEXT NOT NULL, confidence REAL NOT NULL, source TEXT NOT NULL,
  provenance_tier TEXT NOT NULL, quarantined INTEGER NOT NULL DEFAULT 0,
  created_ts TEXT NOT NULL, expires_at TEXT,
  superseded_by INTEGER REFERENCES facts(id)
);
CREATE TABLE episodes (
  id INTEGER PRIMARY KEY, profile_id TEXT NOT NULL, ts TEXT NOT NULL,
  summary TEXT NOT NULL, session_id TEXT NOT NULL, causal_ref TEXT
);
CREATE TABLE tombstones (
  id INTEGER PRIMARY KEY, profile_id TEXT NOT NULL, key TEXT NOT NULL,
  deleted_ts TEXT NOT NULL, reason TEXT NOT NULL
);
CREATE VIRTUAL TABLE memory_fts USING fts5(
  kind, content, key, ref_id UNINDEXED, profile_id UNINDEXED,
  tokenize='porter'
);
"""


def test_old_schema_db_opens_and_grades(tmp_path):
    """A pre-grading DB (no fact_grades/fact_merges) opens unchanged and
    every grading feature works on its existing facts."""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_SCHEMA)
    conn.execute(
        "INSERT INTO facts (profile_id, key, value, confidence, source,"
        " provenance_tier, quarantined, created_ts) VALUES ('test',"
        " 'legacy', 'old value', 0.8, 'user', 'user', 0,"
        " '2026-01-01T00:00:00+00:00')")
    fid = conn.execute("SELECT id FROM facts").fetchone()[0]
    conn.execute(
        "INSERT INTO memory_fts (kind, content, key, ref_id, profile_id)"
        " VALUES ('fact', 'legacy old value', 'legacy', ?, 'test')", (fid,))
    conn.commit()
    conn.close()

    m = Memory(path, profile_id="test")
    try:
        assert m.get_fact("legacy")["value"] == "old value"
        g = m.grade("legacy")  # lazily created with documented defaults
        assert g["weight"] == 1.0 and g["trust_score"] == 0.5
        assert m.recall("legacy")[0]["key"] == "legacy"
        counts = m.consolidate()
        assert counts["expired"] == 0  # nothing broke on the legacy row
        tables = {r[0] for r in m._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"fact_grades", "fact_merges"} <= tables
    finally:
        m.close()


# ------------------------------------------------------- defaults/access

def test_grade_defaults(mem):
    mem.write_fact("city", "Pune", source="user", tier="user", confidence=0.9)
    g = mem.grade("city")
    assert g["weight"] == 1.0
    assert g["trust_score"] == 0.5  # Bayesian prior, no feedback yet
    assert g["helpful_count"] == 0 and g["retrieval_count"] == 0
    assert g["access_count"] == 0 and g["last_accessed"] is None
    assert g["archived"] is False and g["consolidated_from"] is None


def test_grade_unknown_fact_raises(mem):
    with pytest.raises(ValueError):
        mem.grade("never_existed")


def test_get_fact_bumps_access(mem):
    mem.write_fact("city", "Pune", source="user", tier="user", confidence=0.9)
    mem.get_fact("city")
    mem.get_fact("city")
    g = mem.grade("city")
    assert g["access_count"] == 2
    assert g["last_accessed"] is not None


def test_recall_bumps_access_only_for_returned_facts(mem):
    mem.write_fact("note_a", "zebra shared token", source="brain",
                   tier="inferred", confidence=0.8)
    mem.write_fact("note_b", "zebra shared token", source="brain",
                   tier="inferred", confidence=0.8)
    hits = mem.recall("zebra", limit=1)
    assert len(hits) == 1
    counts = sorted(mem.grade(k)["access_count"]
                    for k in ("note_a", "note_b"))
    assert counts == [0, 1]  # exactly the returned fact was bumped


# ------------------------------------------------------------------ trust

def test_trust_posterior_math(mem):
    mem.write_fact("tip", "use the side door", source="brain",
                   tier="inferred", confidence=0.8)
    g = mem.record_feedback("tip", True)
    assert g["trust_score"] == pytest.approx(2 / 3)  # (1+1)/(1+2)
    assert g["retrieval_count"] == 1 and g["helpful_count"] == 1
    g = mem.record_feedback("tip", False)
    assert g["trust_score"] == pytest.approx(0.5)    # (1+1)/(2+2)
    assert g["retrieval_count"] == 2 and g["helpful_count"] == 1


def test_trust_sinks_for_unhelpful_learned_fact(mem):
    mem.write_fact("tip", "dubious claim", source="site", tier="web",
                   confidence=0.4)
    for _ in range(10):
        g = mem.record_feedback("tip", False)
    assert g["trust_score"] == pytest.approx(1 / 12)
    assert g["trust_score"] < 0.5  # no floor for non-identity facts


def test_identity_facts_floor_at_prior(mem):
    mem.write_fact("name", "Owais", source="user", tier="user",
                   confidence=1.0)
    for _ in range(10):
        g = mem.record_feedback("name", False)
    assert g["trust_score"] == 0.5  # floored, never below the prior
    # Provenance-marked identity floors too, whatever the tier.
    mem.write_fact("identity:city", "Pune", source="brain", tier="inferred",
                   confidence=0.9)
    for _ in range(10):
        g = mem.record_feedback("identity:city", False)
    assert g["trust_score"] == 0.5


# ------------------------------------------------------------ recall blend

def test_recall_default_order_is_bm25_order(mem):
    mem.write_fact("zebra_key", "zebra zebra zebra", source="user",
                   tier="user", confidence=0.9)
    mem.write_fact("other_key", "a zebra appeared once", source="user",
                   tier="user", confidence=0.9)
    hits = mem.recall("zebra")
    assert hits[0]["key"] == "zebra_key"  # strongest BM25 first, as before
    assert hits[0]["score"] >= hits[1]["score"]  # raw BM25 preserved
    assert "grade_score" in hits[0] and "weight" in hits[0]


def test_recall_blend_demotes_distrusted_fact(mem):
    mem.write_fact("note_a", "zebra facts here", source="brain",
                   tier="inferred", confidence=0.8)
    mem.write_fact("note_b", "zebra facts here", source="brain",
                   tier="inferred", confidence=0.8)
    for _ in range(20):
        mem.record_feedback("note_a", False)  # trust -> 1/22, factor ~0.52
    hits = mem.recall("zebra")
    assert [h["key"] for h in hits[:2]] == ["note_b", "note_a"]
    assert hits[0]["grade_score"] > hits[1]["grade_score"]


def test_soft_expiry_hides_from_search_but_keeps_storage(mem):
    mem.write_fact("promo", "zebra discount code", source="site",
                   tier="web", confidence=0.5)
    assert mem.recall("zebra", include_quarantined=True) != []
    mem.set_fact_expiry("promo", "2000-01-01T00:00:00+00:00")
    assert mem.recall("zebra", include_quarantined=True) == []  # hidden
    kept = mem.get_fact("promo")  # ... but storage keeps it
    assert kept is not None and kept["value"] == "zebra discount code"
    assert mem.tombstone_count("promo") == 0  # soft expiry never tombstones
    mem.set_fact_expiry("promo", None)
    assert mem.recall("zebra", include_quarantined=True) != []


# ------------------------------------------------------------------ decay

def test_decay_gates_block_young_important_and_accessed(mem):
    mem.write_fact("young", "v", source="brain", tier="inferred",
                   confidence=0.2)
    _backdate(mem, "young", 30)  # < TTL 90
    mem.write_fact("important", "v", source="brain", tier="inferred",
                   confidence=0.9)  # >= importance threshold 0.3
    _backdate(mem, "important", 200)
    mem.write_fact("popular", "v", source="brain", tier="inferred",
                   confidence=0.2)
    _backdate(mem, "popular", 200)
    for _ in range(6):
        mem.get_fact("popular")  # access_count 6 >= gate 5
    counts = mem.consolidate(now_iso=_now_plus(0))
    assert "weight_decayed" not in counts
    for key in ("young", "important", "popular"):
        assert mem.grade(key)["weight"] == 1.0


def test_decay_applies_per_kind_rates(mem):
    cases = [("k_inferred", "inferred", 0.90), ("k_web", "web", 0.95),
             ("k_tool", "tool", 0.95), ("k_user", "user", 0.999)]
    for key, tier, _ in cases:
        mem.write_fact(key, "v", source="s", tier=tier, confidence=0.2)
        _backdate(mem, key, 200)
    counts = mem.consolidate(now_iso=_now_plus(0))
    assert counts["weight_decayed"] == 4
    for key, _, factor in cases:
        assert mem.grade(key)["weight"] == pytest.approx(factor)


def test_identity_facts_never_decay(mem):
    mem.write_fact("identity:spouse", "v", source="brain", tier="inferred",
                   confidence=0.1)
    mem.write_fact("relationship:mother", "v", source="user",
                   tier="inferred", confidence=0.1)
    mem.write_fact("plain_key", "v", source="identity", tier="inferred",
                   confidence=0.1)
    for key in ("identity:spouse", "relationship:mother", "plain_key"):
        _backdate(mem, key, 400)
    for i in range(3):
        counts = mem.consolidate(now_iso=_now_plus(i))
        assert "weight_decayed" not in counts
    for key in ("identity:spouse", "relationship:mother", "plain_key"):
        g = mem.grade(key)
        assert g["weight"] == 1.0 and g["archived"] is False


def test_decay_archives_at_low_weight_and_never_deletes(mem):
    mem.write_fact("stale", "zebra old claim", source="brain",
                   tier="inferred", confidence=0.2)
    _backdate(mem, "stale", 200)
    archived_on = None
    for i in range(1, 12):  # 0.9^n < 0.5 first at n = 7
        counts = mem.consolidate(now_iso=_now_plus(i))
        if counts.get("archived"):
            archived_on = i
            break
    assert archived_on == 7
    g = mem.grade("stale")
    assert g["archived"] is True and g["weight"] < 0.5
    # Archived = hidden from search, still stored, never tombstoned.
    assert mem.recall("zebra") == []
    assert mem.get_fact("stale")["value"] == "zebra old claim"
    assert mem.tombstone_count("stale") == 0
    # More passes change nothing; forget() remains the only way out.
    mem.consolidate(now_iso=_now_plus(30))
    assert mem.get_fact("stale") is not None
    receipt = mem.forget("stale")
    assert receipt["verified"] is True
    assert mem.get_fact("stale") is None


# ---------------------------------------------------- consolidation plans

def test_plan_is_pure_and_defaults_to_newer_text(mem):
    a = mem.write_fact("city", "Pune", source="user", tier="user",
                       confidence=0.9)
    b = mem.write_fact("city_long", "Pune, Maharashtra", source="web",
                       tier="web", confidence=0.5)
    _backdate(mem, "city", 10)  # fact_b is the newer one
    plan = mem.plan_consolidation("city", "city_long")
    assert isinstance(plan, ConsolidationPlan)
    assert plan.key == "city"                      # fact_a's key survives
    assert plan.survivor_text == "Pune, Maharashtra"  # newer value wins
    assert len(plan.fingerprint) == 64
    # Nothing was applied: both facts live, no merge audited.
    assert mem.get_fact("city")["id"] == a["id"]
    assert mem.get_fact("city_long")["id"] == b["id"]
    n = mem._conn.execute("SELECT COUNT(*) AS n FROM fact_merges").fetchone()
    assert n["n"] == 0


def test_plan_refuses_same_fact_and_bad_text(mem):
    mem.write_fact("k", "v", source="user", tier="user", confidence=0.9)
    with pytest.raises(ValueError):
        mem.plan_consolidation("k", "k")
    mem.write_fact("k2", "v2", source="user", tier="user", confidence=0.9)
    with pytest.raises(ValueError):
        mem.plan_consolidation("k", "k2", survivor_text="x" * 501)


def test_apply_consolidation_merges_with_provenance(mem):
    a = mem.write_fact("city", "Pune", source="user", tier="user",
                       confidence=0.9)
    b = mem.write_fact("city_long", "Pune, Maharashtra", source="web",
                       tier="web", confidence=0.5)
    plan = mem.plan_consolidation(a["id"], b["id"],
                                  survivor_text="Pune, Maharashtra")
    out = mem.apply_consolidation(plan)
    assert out["op"] == "CONSOLIDATE" and out["fingerprint"] == plan.fingerprint
    survivor = mem.get_fact("city")
    assert survivor["id"] == out["id"]
    assert survivor["value"] == "Pune, Maharashtra"
    assert survivor["source"] == "consolidation"
    assert survivor["confidence"] == 0.9  # max of the sources
    assert survivor["consolidated_from"] == f"{a['id']},{b['id']}"
    assert mem.get_fact("city_long") is None  # superseded, not deleted
    hits = mem.recall("Pune", include_quarantined=True)
    assert [h["id"] for h in hits] == [out["id"]]  # only the survivor found
    audit = mem._conn.execute(
        "SELECT * FROM fact_merges WHERE survivor_id = ?",
        (out["id"],)).fetchone()
    assert audit["fingerprint"] == plan.fingerprint
    assert audit["source_ids"] == f"{a['id']},{b['id']}"


def test_apply_refuses_when_source_changed(mem):
    mem.write_fact("city", "Pune", source="user", tier="user", confidence=0.9)
    mem.write_fact("city_long", "Pune, Maharashtra", source="web",
                   tier="web", confidence=0.5)
    plan = mem.plan_consolidation("city", "city_long")
    with mem._lock:  # source edited in place: still live, fingerprint stale
        mem._conn.execute(
            "UPDATE facts SET value = 'Pune (edited)' WHERE key = 'city_long'")
        mem._conn.commit()
    with pytest.raises(RuntimeError, match="fingerprint mismatch"):
        mem.apply_consolidation(plan)
    # Refusal wrote nothing: both sources intact, no survivor.
    assert mem.get_fact("city")["value"] == "Pune"
    assert mem.get_fact("city_long")["value"] == "Pune (edited)"
    n = mem._conn.execute("SELECT COUNT(*) AS n FROM fact_merges").fetchone()
    assert n["n"] == 0


def test_apply_refuses_when_source_superseded(mem):
    mem.write_fact("city", "Pune", source="user", tier="user", confidence=0.9)
    mem.write_fact("city_long", "Pune, Maharashtra", source="web",
                   tier="web", confidence=0.5)
    plan = mem.plan_consolidation("city", "city_long")
    mem.write_fact("city", "Pune!", source="user", tier="user",
                   confidence=0.9)  # supersedes source A
    with pytest.raises(RuntimeError, match="no longer live"):
        mem.apply_consolidation(plan)


def test_apply_rejects_non_plan(mem):
    with pytest.raises(TypeError):
        mem.apply_consolidation({"key": "x"})


def test_survivor_inherits_usage_and_trust(mem):
    a = mem.write_fact("a_key", "alpha", source="user", tier="user",
                       confidence=0.9)
    mem.write_fact("b_key", "beta", source="brain", tier="inferred",
                   confidence=0.5)
    for _ in range(3):
        mem.get_fact("a_key")            # access_count 3 on A
    mem.record_feedback("a_key", True)   # A trust -> 2/3
    plan = mem.plan_consolidation("a_key", "b_key", survivor_text="alpha beta")
    out = mem.apply_consolidation(plan)
    g = mem.grade(out["id"])
    assert g["access_count"] == 3
    assert g["trust_score"] == pytest.approx(2 / 3)  # max of the sources
    assert g["consolidated_from"] == f"{a['id']},{out['sources'][1]}"
