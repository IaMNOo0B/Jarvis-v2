"""Tests for the Persona Round (Team 26 steals):

1. Golden-pair mass & decay (jarvis/golden_pairs.py) — influence is a
   weight: recurrence grows it (+0.5, cap 5.0), disuse fades it toward
   the 1.0 floor with a ~29-day half-life, decay never deletes.
2. Relationship state (jarvis/memory.py) — engine-owned axes
   {trust, familiarity, warmth}, clamped nudges, journaled moves, and
   deterministic consolidate() rules.
3. TEACHING.md Lesson 11 (ESConv: Exploration -> Comforting -> Action).
"""

import json
import sqlite3
import time
from pathlib import Path

import pytest

from jarvis.golden_pairs import (
    MASS_CAP,
    MASS_FLOOR,
    GoldenPair,
    PairStore,
)
from jarvis.memory import Memory

DAY = 86400.0


# ------------------------------------------------------------ golden pairs

def _pair(context="weather in Mumbai", bad="formal English",
          good="casual Hinglish"):
    return GoldenPair(context=context, bad_response=bad, good_response=good)


def _set_fields(path: Path, **fields) -> None:
    """Rewrite the single stored JSONL line with overridden fields."""
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    d = json.loads(lines[0])
    d.update(fields)
    path.write_text(json.dumps(d, ensure_ascii=False) + "\n",
                    encoding="utf-8")


class TestPairMass:
    def test_new_pair_born_at_floor(self, tmp_path):
        store = PairStore(tmp_path / "pairs.jsonl")
        store.save(_pair())
        (p,) = store.all()
        assert p.mass == MASS_FLOOR == 1.0
        assert p.last_used > 0

    def test_recurrence_grows_mass(self, tmp_path):
        store = PairStore(tmp_path / "pairs.jsonl")
        store.save(_pair())
        store.save(_pair(bad="stiff reply"))   # same signature, new bad
        (p,) = store.all()                     # still ONE pair
        assert p.mass == pytest.approx(1.5)
        store.save(_pair(bad="another failure"))
        (p,) = store.all()
        assert p.mass == pytest.approx(2.0)

    def test_recurrence_capped(self, tmp_path):
        store = PairStore(tmp_path / "pairs.jsonl")
        for _ in range(12):
            store.save(_pair())
        (p,) = store.all()
        assert p.mass == MASS_CAP == 5.0

    def test_signature_is_normalized(self, tmp_path):
        store = PairStore(tmp_path / "pairs.jsonl")
        store.save(_pair(context="Weather in Mumbai"))
        store.save(_pair(context="weather   in  mumbai"))
        (p,) = store.all()
        assert p.mass == pytest.approx(1.5)

    def test_changed_correction_is_a_new_pair(self, tmp_path):
        store = PairStore(tmp_path / "pairs.jsonl")
        store.save(_pair(good="casual Hinglish"))
        store.save(_pair(good="short answers only"))
        pairs = store.all()
        assert len(pairs) == 2
        assert all(p.mass == 1.0 for p in pairs)

    def test_mass_persists_across_instances(self, tmp_path):
        path = tmp_path / "pairs.jsonl"
        PairStore(path).save(_pair())
        PairStore(path).save(_pair())
        (p,) = PairStore(path).all()
        assert p.mass == pytest.approx(1.5)


class TestPairDecay:
    def test_one_half_life(self, tmp_path):
        path = tmp_path / "pairs.jsonl"
        store = PairStore(path)
        store.save(_pair())
        t0 = 1_700_000_000.0
        _set_fields(path, mass=5.0, last_used=t0)
        out = PairStore(path).decay_pairs(now=t0 + 29 * DAY)
        assert out == {"pairs": 1, "decayed": 1}
        (p,) = PairStore(path).all()
        # 1.0 + (5.0 - 1.0) * 0.5 ** (29/29) = 3.0
        assert p.mass == pytest.approx(3.0)

    def test_two_half_lives(self, tmp_path):
        path = tmp_path / "pairs.jsonl"
        PairStore(path).save(_pair())
        t0 = 1_700_000_000.0
        _set_fields(path, mass=5.0, last_used=t0)
        PairStore(path).decay_pairs(now=t0 + 58 * DAY)
        (p,) = PairStore(path).all()
        # 1.0 + 4.0 * 0.25 = 2.0
        assert p.mass == pytest.approx(2.0)

    def test_floor_holds_and_nothing_is_deleted(self, tmp_path):
        path = tmp_path / "pairs.jsonl"
        PairStore(path).save(_pair())
        t0 = 1_700_000_000.0
        _set_fields(path, mass=1.3, last_used=t0)
        out = PairStore(path).decay_pairs(now=t0 + 3650 * DAY)
        pairs = PairStore(path).all()
        assert out["pairs"] == 1 and len(pairs) == 1   # never deleted
        assert pairs[0].mass >= MASS_FLOOR
        assert pairs[0].mass == pytest.approx(MASS_FLOOR, abs=1e-6)

    def test_decay_is_incremental_not_recharged(self, tmp_path):
        path = tmp_path / "pairs.jsonl"
        PairStore(path).save(_pair())
        t0 = 1_700_000_000.0
        _set_fields(path, mass=5.0, last_used=t0)
        store = PairStore(path)
        store.decay_pairs(now=t0 + 29 * DAY)
        out = store.decay_pairs(now=t0 + 29 * DAY)   # same instant again
        assert out["decayed"] == 0
        (p,) = PairStore(path).all()
        assert p.mass == pytest.approx(3.0)

    def test_used_pair_does_not_decay(self, tmp_path):
        path = tmp_path / "pairs.jsonl"
        store = PairStore(path)
        store.save(_pair())
        ancient = time.time() - 40 * DAY
        _set_fields(path, mass=3.0, last_used=ancient)
        rel = PairStore(path).relevant("Mumbai weather")
        assert len(rel) == 1 and rel[0].used_count >= 1
        PairStore(path).decay_pairs()   # now: last_used was just refreshed
        (p,) = PairStore(path).all()
        assert p.mass == pytest.approx(3.0)


class TestPairSelection:
    def test_mass_breaks_relevance_ties(self, tmp_path):
        store = PairStore(tmp_path / "pairs.jsonl")
        store.save(_pair(context="weather in Mumbai", good="casual style"))
        store.save(_pair(context="weather in Delhi", good="formal style"))
        # Recur the Delhi correction until it outweighs the Mumbai one.
        for _ in range(3):
            store.save(_pair(context="weather in Delhi",
                             good="formal style"))
        rel = store.relevant("weather today")
        assert len(rel) == 2
        assert "formal" in rel[0].good_response   # heavier pair first
        assert rel[0].mass > rel[1].mass

    def test_irrelevant_massive_pair_stays_out(self, tmp_path):
        store = PairStore(tmp_path / "pairs.jsonl")
        for _ in range(9):
            store.save(_pair(context="quantum physics lectures",
                             good="simple words"))
        assert store.relevant("weather today") == []


# -------------------------------------------------------- relationship state

@pytest.fixture()
def mem(tmp_path):
    m = Memory(tmp_path / "mem.db")
    yield m
    m.close()


def _episodes(db_path, session=None):
    conn = sqlite3.connect(db_path)
    try:
        if session is None:
            return conn.execute(
                "SELECT summary, session_id FROM episodes").fetchall()
        return conn.execute(
            "SELECT summary, session_id FROM episodes"
            " WHERE session_id = ?", (session,)).fetchall()
    finally:
        conn.close()


class TestRelationshipBasics:
    def test_snapshot_defaults(self, mem):
        snap = mem.relationship_snapshot()
        assert snap["trust"] == 0.5
        assert snap["familiarity"] == 0.5
        assert snap["warmth"] == 0.5
        assert snap["descriptor"] == (
            "steady trust, steady familiarity, steady warmth")

    def test_nudge_clamps_delta(self, mem):
        out = mem.nudge_relationship("trust", 0.5, "owner shared a key "
                                                 "decision unprompted")
        assert out["applied_delta"] == pytest.approx(0.05)
        assert out["value"] == pytest.approx(0.55)
        out = mem.nudge_relationship("trust", -0.9, "a promise was broken")
        assert out["applied_delta"] == pytest.approx(-0.05)
        assert out["value"] == pytest.approx(0.50)

    def test_nudge_axis_bounds(self, mem):
        for _ in range(20):
            mem.nudge_relationship("warmth", 0.05, "good moment")
        assert mem.relationship_snapshot()["warmth"] == 1.0
        out = mem.nudge_relationship("warmth", 0.05, "at the ceiling")
        assert out["applied_delta"] == 0.0     # cannot move, honest zero
        assert out["value"] == 1.0
        for _ in range(30):
            mem.nudge_relationship("warmth", -0.05, "cold spell")
        assert mem.relationship_snapshot()["warmth"] == 0.0

    def test_nudge_validation(self, mem):
        with pytest.raises(ValueError):
            mem.nudge_relationship("loyalty", 0.05, "not an axis")
        with pytest.raises(ValueError):
            mem.nudge_relationship("trust", 0.05, "   ")   # reason required
        with pytest.raises(ValueError):
            mem.nudge_relationship("trust", "a lot", "not a number")

    def test_nudge_is_journaled_with_reason(self, mem, tmp_path):
        mem.nudge_relationship("familiarity", 0.05,
                               "long late-night debugging session together")
        rows = _episodes(tmp_path / "mem.db", session="relationship")
        assert len(rows) == 1
        summary = rows[0][0]
        assert "familiarity" in summary
        assert "late-night debugging" in summary   # the reason rides along

    def test_noop_nudge_journals_nothing(self, mem, tmp_path):
        for _ in range(10):
            mem.nudge_relationship("trust", 0.05, "climbing")
        before = len(_episodes(tmp_path / "mem.db", session="relationship"))
        mem.nudge_relationship("trust", 0.05, "already at the top")
        after = len(_episodes(tmp_path / "mem.db", session="relationship"))
        assert before == after

    def test_descriptor_bands(self, mem):
        for _ in range(5):
            mem.nudge_relationship("trust", 0.05, "kept every promise")
        mem.nudge_relationship("familiarity", 0.05, "daily chats")
        mem.nudge_relationship("familiarity", 0.05, "daily chats")
        snap = mem.relationship_snapshot()
        assert snap["trust"] == pytest.approx(0.75)
        assert snap["descriptor"].startswith("high trust")
        assert "growing familiarity" in snap["descriptor"]

    def test_snapshot_persists_across_instances(self, tmp_path):
        path = tmp_path / "mem.db"
        m1 = Memory(path)
        m1.nudge_relationship("trust", 0.05, "first save")
        m1.close()
        m2 = Memory(path)
        try:
            assert m2.relationship_snapshot()["trust"] == pytest.approx(0.55)
        finally:
            m2.close()


class TestConsolidateRelationshipRules:
    def test_counts_shape_unchanged_when_nothing_fires(self, mem):
        counts = mem.consolidate()
        assert counts == {"expired": 0, "deduped": 0,
                          "promoted": 0, "decayed": 0}

    def test_trust_rises_on_helpful_feedback(self, mem, tmp_path):
        mem.write_fact("pref:tea", "adrak chai", source="user",
                       tier="user", confidence=0.9)
        for _ in range(5):
            mem.record_feedback("pref:tea", helpful=True)
        counts = mem.consolidate()
        # The counts contract stays exactly the four pass counters —
        # the relationship move is proven by state + journal instead.
        assert set(counts) == {"expired", "deduped", "promoted", "decayed"}
        snap = mem.relationship_snapshot()
        assert snap["trust"] == pytest.approx(0.52)   # +0.02, slow up
        rows = _episodes(tmp_path / "mem.db", session="relationship")
        assert len(rows) == 1 and "helpful-feedback ratio" in rows[0][0]

    def test_trust_falls_faster_on_unhelpful_feedback(self, mem):
        mem.write_fact("fact:weather-source", "site-x", source="web",
                       tier="web", confidence=0.4)
        for _ in range(5):
            mem.record_feedback("fact:weather-source", helpful=False)
        mem.consolidate()
        snap = mem.relationship_snapshot()
        assert snap["trust"] == pytest.approx(0.47)   # -0.03, fast down

    def test_thin_feedback_is_not_judged(self, mem):
        mem.write_fact("pref:tea", "adrak chai", source="user",
                       tier="user", confidence=0.9)
        mem.record_feedback("pref:tea", helpful=True)
        mem.record_feedback("pref:tea", helpful=True)
        mem.consolidate()
        assert mem.relationship_snapshot()["trust"] == 0.5

    def test_mixed_feedback_leaves_trust_alone(self, mem):
        mem.write_fact("pref:tea", "adrak chai", source="user",
                       tier="user", confidence=0.9)
        for helpful in (True, True, True, False, False):   # ratio 0.6
            mem.record_feedback("pref:tea", helpful=helpful)
        mem.consolidate()
        assert mem.relationship_snapshot()["trust"] == 0.5

    def test_familiarity_grows_with_new_episodes_once(self, mem):
        mem.write_episode("debugged the PC fan curve together", "s1")
        mem.consolidate()
        assert mem.relationship_snapshot()["familiarity"] == \
            pytest.approx(0.51)
        # No new episodes since -> no second helping, and the journal
        # episodes consolidate writes do not count as shared history.
        mem.consolidate()
        assert mem.relationship_snapshot()["familiarity"] == \
            pytest.approx(0.51)

    def test_warmth_has_no_automatic_rule(self, mem):
        mem.write_fact("pref:tea", "adrak chai", source="user",
                       tier="user", confidence=0.9)
        for _ in range(6):
            mem.record_feedback("pref:tea", helpful=True)
        mem.write_episode("a long session", "s1")
        mem.consolidate()
        assert mem.relationship_snapshot()["warmth"] == 0.5


# ---------------------------------------------------------------- TEACHING

class TestLesson11:
    def test_lesson_11_present_with_esconv_order(self):
        text = (Path(__file__).resolve().parent.parent
                / "TEACHING.md").read_text(encoding="utf-8")
        assert "## Lesson 11" in text
        section = text.split("## Lesson 11", 1)[1].split("---", 1)[0]
        assert "Exploration" in section
        assert "Comforting" in section
        assert "Action" in section
        # The golden micro-example: a frustrated Hinglish owner.
        assert "dimag kharab" in section
        assert "WRONG" in section and "RIGHT" in section
