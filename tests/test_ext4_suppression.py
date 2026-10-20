"""Extension Team 4 — durable suppression (proactivity.SuppressionStore).

Team 14 steal #3 (hawky + langchain-101): dismissal is forever —
a durable per-shape key, checked BEFORE a candidate is minted,
surviving restarts; feedback is targeted (one key at a time, never a
whole-profile rewrite). Urgent kinds are exempt by design: a safety
alert cannot be silenced forever by one cut.
"""

import pytest

from jarvis.proactivity import (
    RingManager,
    SuppressionStore,
    Watcher,
    item_shape,
    suppression_key,
)

DISK_91 = {"title": "Disk space", "detail": "Disk is 91% full"}
DISK_93 = {"title": "disk space", "detail": "Disk is 93% full"}


# --------------------------------------------------------------------------- #
# shape identity
# --------------------------------------------------------------------------- #

class TestShape:
    def test_digits_and_case_collapse(self):
        # 91% vs 93% is the SAME shape of nudge.
        assert item_shape(DISK_91) == item_shape(DISK_93)

    def test_explicit_shape_wins(self):
        assert item_shape({"shape": "disk-low", "title": "zzz"}) == "disk-low"

    def test_string_items(self):
        assert item_shape("Build 12 finished") == item_shape("build 99 finished")

    def test_key_includes_source(self):
        assert suppression_key("watcher", DISK_91) != suppression_key(
            "reminder", DISK_91)
        assert suppression_key("watcher", DISK_91).startswith("watcher|")


# --------------------------------------------------------------------------- #
# the store itself
# --------------------------------------------------------------------------- #

class TestStore:
    def test_dismissal_round_trip(self, tmp_path):
        store = SuppressionStore(str(tmp_path))
        assert not store.is_suppressed("watcher", DISK_91)
        store.record("watcher", DISK_91, "dismissed")
        assert store.is_suppressed("watcher", DISK_93)  # same shape
        assert store.outcome_of("watcher", DISK_91) == "dismissed"

    def test_pickup_and_edit_do_not_suppress(self, tmp_path):
        store = SuppressionStore(str(tmp_path))
        store.record("watcher", DISK_91, "picked_up")
        store.record("reminder", {"title": "x"}, "edited")
        assert not store.is_suppressed("watcher", DISK_91)
        assert not store.is_suppressed("reminder", {"title": "x"})

    def test_survives_restart(self, tmp_path):
        SuppressionStore(str(tmp_path)).record("watcher", DISK_91,
                                                "dismissed")
        fresh = SuppressionStore(str(tmp_path))
        assert fresh.is_suppressed("watcher", DISK_91)

    def test_targeted_recording_never_clobbers_neighbours(self, tmp_path):
        store = SuppressionStore(str(tmp_path))
        store.record("watcher", {"title": "alpha"}, "dismissed")
        store.record("watcher", {"title": "beta"}, "picked_up")
        store.record("watcher", {"title": "beta"}, "dismissed")
        # Recording beta (twice) left alpha's entry exactly as it was.
        assert store.outcome_of("watcher", {"title": "alpha"}) == "dismissed"
        entry = store.all()[suppression_key("watcher", {"title": "beta"})]
        assert entry["outcome"] == "dismissed" and entry["count"] == 2
        assert store.all()[suppression_key(
            "watcher", {"title": "alpha"})]["count"] == 1

    def test_invalid_outcome_rejected(self, tmp_path):
        store = SuppressionStore(str(tmp_path))
        with pytest.raises(ValueError):
            store.record("watcher", DISK_91, "ignored-ish")

    def test_forget_and_clear(self, tmp_path):
        store = SuppressionStore(str(tmp_path))
        store.record("watcher", DISK_91, "dismissed")
        store.record("reminder", DISK_91, "dismissed")
        assert store.forget("watcher", DISK_91)
        assert not store.is_suppressed("watcher", DISK_91)
        assert store.is_suppressed("reminder", DISK_91)  # other source kept
        assert not store.forget("watcher", DISK_91)  # already gone
        store.record("watcher", DISK_91, "dismissed")
        assert store.clear("watcher") == 1
        assert store.clear() == 1  # the reminder key
        assert store.all() == {}


# --------------------------------------------------------------------------- #
# RingManager integration — cut writes the key; the key blocks pre-mint
# --------------------------------------------------------------------------- #

def manager(tmp_path):
    return RingManager(str(tmp_path), time_fn=lambda: 1_700_000_000.0)


class TestRingManagerIntegration:
    def test_cut_then_same_shape_is_refused(self, tmp_path):
        rm = manager(tmp_path)
        ring = rm.ring("normal", "watcher", "Disk space",
                       "Disk is 91% full", item=DISK_91)
        assert ring is not None
        assert rm.cut(ring.id)
        # The dismissal was written durably at cut time.
        assert rm.suppressions.is_suppressed("watcher", DISK_91)
        again = rm.ring("normal", "watcher", "disk space",
                        "Disk is 93% full", item=DISK_93)
        assert again is None
        assert "durable suppression" in (rm.last_suppression or "")

    def test_dismissal_survives_manager_restart(self, tmp_path):
        rm = manager(tmp_path)
        ring = rm.ring("normal", "watcher", "Disk space",
                       "Disk is 91% full", item=DISK_91)
        rm.cut(ring.id)
        rm2 = manager(tmp_path)  # fresh process, same data dir
        assert rm2.ring("normal", "watcher", "Disk space",
                        "Disk is 95% full", item=DISK_91) is None

    def test_different_item_still_rings(self, tmp_path):
        rm = manager(tmp_path)
        ring = rm.ring("normal", "watcher", "Disk space",
                       "Disk is 91% full", item=DISK_91)
        rm.cut(ring.id)
        other = rm.ring("normal", "watcher", "Build done",
                        "Build 12 finished",
                        item={"title": "Build done"})
        assert other is not None

    def test_urgent_is_never_item_suppressed(self, tmp_path):
        rm = manager(tmp_path)
        rm.suppressions.record("watcher", DISK_91, "dismissed")
        urgent = rm.ring("disk_failing", "watcher", "Disk space",
                         "Disk is 91% full", item=DISK_91)
        assert urgent is not None and urgent.kind == "urgent"

    def test_pickup_records_preference_without_suppressing(self, tmp_path):
        rm = manager(tmp_path)
        ring = rm.ring("normal", "watcher", "Disk space",
                       "Disk is 91% full", item=DISK_91)
        assert rm.pick_up(ring.id) is not None
        assert rm.suppressions.outcome_of("watcher", DISK_91) == "picked_up"
        assert not rm.suppressions.is_suppressed("watcher", DISK_91)

    def test_legacy_rings_without_item_are_untouched(self, tmp_path):
        # No item identity -> no durable key -> old behaviour exactly:
        # a cut ring of the same title may ring again (budget permitting).
        rm = manager(tmp_path)
        ring = rm.ring("normal", "watcher", "Disk space",
                       "Disk is 91% full")
        assert ring is not None and ring.item_key is None
        rm.cut(ring.id)
        assert rm.suppressions.all() == {}
        assert rm.ring("normal", "watcher", "Disk space",
                       "Disk is 91% full") is not None


class TestWatcherIntegration:
    def test_dismissed_candidate_never_rings_again(self, tmp_path):
        rm = manager(tmp_path)
        candidate = {"title": "Disk space", "detail": "Disk is 91% full",
                     "type": "watcher"}
        watcher = Watcher(rm, observer=lambda: candidate)
        watcher._cycle()
        assert watcher.rang == 1
        ring = next(iter(rm._rings.values()))
        rm.cut(ring.id)
        watcher._cycle()  # same candidate, next tick
        assert watcher.rang == 1  # refused before minting
        assert "durable suppression" in (rm.last_suppression or "")
