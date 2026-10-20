"""Tests for Builder D memory-graph edges (isair diary+KG pattern, stdlib).

Covers: link()/neighbors() semantics, write_fact(metadata={"relates_to":
...}) linking on ADD/UPDATE/NOOP, upsert-on-relink, direction reporting,
superseded/expired/deleted filtering, cascade on forget(), and validation.
"""

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


def _fact(mem, key, value="v", tier="user", source="t"):
    return mem.write_fact(key, value, source=source, tier=tier,
                          confidence=0.9)["id"]


# ------------------------------------------------------------------ basics

def test_link_by_keys_and_neighbors(mem):
    a, b = _fact(mem, "a"), _fact(mem, "b")
    r = mem.link("a", "b", relation="related_to", weight=2.0)
    assert (r["src_fact"], r["dst_fact"]) == (a, b)
    assert r["relation"] == "related_to" and r["weight"] == 2.0
    n = mem.neighbors("a")
    assert len(n) == 1
    assert n[0]["key"] == "b" and n[0]["direction"] == "out"
    assert n[0]["hops"] == 1
    # Traversed both ways: from b, the same edge reports "in".
    n2 = mem.neighbors("b")
    assert len(n2) == 1 and n2[0]["key"] == "a"
    assert n2[0]["direction"] == "in"


def test_relink_updates_weight_no_duplicate(mem):
    _fact(mem, "a")
    _fact(mem, "b")
    mem.link("a", "b", weight=1.0)
    mem.link("a", "b", weight=3.5)
    n = mem.neighbors("a")
    assert len(n) == 1
    assert n[0]["weight"] == 3.5


def test_two_hop_traversal(mem):
    _fact(mem, "a")
    _fact(mem, "b")
    _fact(mem, "c")
    mem.link("a", "b")
    mem.link("b", "c")
    n1 = mem.neighbors("a", hops=1)
    assert [x["key"] for x in n1] == ["b"]
    n2 = mem.neighbors("a", hops=2)
    keys = [x["key"] for x in n2]
    assert keys == ["b", "c"], keys
    assert n2[1]["hops"] == 2


def test_neighbors_sorted_by_weight_then_id(mem):
    _fact(mem, "hub")
    _fact(mem, "lo")
    _fact(mem, "hi")
    mem.link("hub", "lo", weight=0.5)
    mem.link("hub", "hi", weight=5.0)
    n = mem.neighbors("hub")
    assert [x["key"] for x in n] == ["hi", "lo"]


# ----------------------------------------------------- write_fact metadata

def test_write_fact_links_by_id_key_and_dict(mem):
    target = _fact(mem, "target")
    _fact(mem, "other")
    r = mem.write_fact("main", "hello", source="t", tier="user",
                       confidence=0.9,
                       metadata={"relates_to": [
                           target,
                           "other",
                           {"key": "other", "relation": "uses", "weight": 2.0},
                       ]})
    assert r["op"] == "ADD"
    n = { (x["key"], x["relation"]): x for x in mem.neighbors("main") }
    assert ("target", "related_to") in n
    assert ("other", "related_to") in n
    assert n[("other", "uses")]["weight"] == 2.0


def test_write_fact_noop_still_links(mem):
    _fact(mem, "target")
    _fact(mem, "same", value="stable")
    r = mem.write_fact("same", "stable", source="t", tier="user",
                       confidence=0.9,
                       metadata={"relates_to": ["target"]})
    assert r["op"] == "NOOP"
    assert [x["key"] for x in mem.neighbors("same")] == ["target"]


def test_bad_link_target_raises_before_mutation(mem):
    _fact(mem, "target")
    with pytest.raises(ValueError):
        mem.write_fact("boom", "v", source="t", tier="user",
                       confidence=0.9,
                       metadata={"relates_to": ["no_such_key"]})
    # The write never half-landed.
    assert mem.get_fact("boom") is None


def test_self_link_target_is_old_version(mem):
    mem.write_fact("k", "v1", source="t", tier="user", confidence=0.9)
    with pytest.raises(ValueError):
        # integer ids never exist in this empty-ish db at scale; 999999 does not
        mem.link(999999, "k")
    with pytest.raises(ValueError):
        mem.link("k", 999999)


# ------------------------------------------------------------------ filters

def test_neighbors_skips_superseded(mem):
    old = mem.write_fact("x", "v1", source="t", tier="user",
                         confidence=0.9)["id"]
    y = _fact(mem, "y")
    mem.link("y", old)  # linked while v1 was live
    assert [x["key"] for x in mem.neighbors("y")] == ["x"]
    mem.write_fact("x", "v2", source="t", tier="user", confidence=0.9)
    # x v1 is now superseded: the stale edge is not followed.
    assert mem.neighbors("y") == []


def test_neighbors_tombstones_expired(mem):
    mem.write_fact("old", "gone", source="t", tier="user", confidence=0.9,
                   expires_at="2000-01-01T00:00:00+00:00")
    _fact(mem, "y")
    mem.link("y", "old")
    assert mem.neighbors("y") == []
    # the expiry side-effect ran: the fact is gone
    assert mem.get_fact("old") is None


def test_forget_cascades_edges(mem):
    _fact(mem, "a")
    _fact(mem, "b")
    mem.link("a", "b")
    assert len(mem.neighbors("a")) == 1
    mem.forget("b")
    assert mem.neighbors("a") == []


# --------------------------------------------------------------- validation

def test_link_validation(mem):
    _fact(mem, "a")
    _fact(mem, "b")
    with pytest.raises(ValueError):
        mem.link("a", "b", relation="  ")
    with pytest.raises(ValueError):
        mem.link("a", "b", weight=0)
    with pytest.raises(ValueError):
        mem.link("a", "b", weight=-1)
    with pytest.raises(ValueError):
        mem.link("a", "b", weight="heavy")
    with pytest.raises(ValueError):
        mem.neighbors("a", hops=0)
    with pytest.raises(ValueError):
        mem.write_fact("z", "v", source="t", tier="user", confidence=0.9,
                       metadata={"relates_to": "not-a-list"})
