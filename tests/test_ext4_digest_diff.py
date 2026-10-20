"""Extension Team 4 — the snapshot-diff ledger (jarvis/digest_diff.py).

Team 14's unanimous anti-fatigue law: diff before you speak, only
deltas may be reported, cursors advance only after confirmed delivery,
and a failed source is 'unreadable' — never a filled-in blank.
"""

import pytest

from jarvis.digest_diff import (
    MAX_REPORTED,
    BriefingState,
    diff_source,
    item_key,
    run_digest,
)


def items(*titles):
    return [{"title": t} for t in titles]


# --------------------------------------------------------------------------- #
# item identity — exact, stable
# --------------------------------------------------------------------------- #

class TestItemKey:
    def test_id_based(self):
        assert item_key("mail", {"id": "42", "title": "x"}) == "mail:42"

    def test_content_hash_stable_across_key_order(self):
        a = item_key("mail", {"title": "Hi", "n": 1})
        b = item_key("mail", {"n": 1, "title": "Hi"})
        assert a == b

    def test_different_items_differ(self):
        assert item_key("mail", {"title": "a"}) != item_key("mail",
                                                            {"title": "b"})
        assert item_key("mail", {"id": "1"}) != item_key("news", {"id": "1"})


# --------------------------------------------------------------------------- #
# BriefingState — ledger + cursors, commit discipline
# --------------------------------------------------------------------------- #

class TestBriefingState:
    def test_commit_marks_reported_and_advances_cursor(self, tmp_path):
        st = BriefingState(str(tmp_path))
        assert st.cursor("mail") is None
        st.commit("mail", items("a", "b"), cursor="c1")
        assert st.cursor("mail") == "c1"
        assert st.is_reported("mail", {"title": "a"})
        assert not st.is_reported("mail", {"title": "z"})

    def test_persists_across_instances(self, tmp_path):
        BriefingState(str(tmp_path)).commit("mail", items("a"),
                                             cursor="c9")
        st2 = BriefingState(str(tmp_path))
        assert st2.cursor("mail") == "c9"
        assert st2.is_reported("mail", {"title": "a"})

    def test_reported_ledger_is_capped(self, tmp_path):
        st = BriefingState(str(tmp_path))
        big = [{"id": str(i)} for i in range(MAX_REPORTED + 25)]
        st.commit("bulk", big)
        assert len(st.reported_keys()) == MAX_REPORTED
        # Oldest retired first; the newest survive.
        assert st.is_reported("bulk", {"id": str(MAX_REPORTED + 24)})
        assert not st.is_reported("bulk", {"id": "0"})


# --------------------------------------------------------------------------- #
# diff_source — deltas only, unreadable honesty, verify-live
# --------------------------------------------------------------------------- #

class TestDiffSource:
    def test_first_run_everything_is_new(self, tmp_path):
        st = BriefingState(str(tmp_path))
        diff = diff_source(st, "mail", items("a", "b"))
        assert not diff.unreadable
        assert [i["title"] for i in diff.new_items] == ["a", "b"]

    def test_after_commit_nothing_is_new(self, tmp_path):
        st = BriefingState(str(tmp_path))
        gathered = items("a", "b")
        diff_source(st, "mail", gathered)
        st.commit("mail", gathered)
        diff2 = diff_source(st, "mail", items("a", "b", "c"))
        assert [i["title"] for i in diff2.new_items] == ["c"]

    def test_none_means_unreadable_not_empty(self, tmp_path):
        st = BriefingState(str(tmp_path))
        diff = diff_source(st, "mail", None)
        assert diff.unreadable and diff.new_items == []

    def test_malformed_gather_is_unreadable(self, tmp_path):
        st = BriefingState(str(tmp_path))
        assert diff_source(st, "mail", {"cursor": "c"}).unreadable
        assert diff_source(st, "mail", "a string").unreadable

    def test_cursor_offered_by_gather(self, tmp_path):
        st = BriefingState(str(tmp_path))
        diff = diff_source(st, "mail",
                           {"items": items("a"), "cursor": "c7"})
        assert diff.cursor == "c7" and len(diff.new_items) == 1

    def test_duplicates_within_one_gather_count_once(self, tmp_path):
        st = BriefingState(str(tmp_path))
        diff = diff_source(st, "mail", items("a", "a", "b"))
        assert [i["title"] for i in diff.new_items] == ["a", "b"]

    def test_verify_filters_stale_and_does_not_retire_them(self, tmp_path):
        st = BriefingState(str(tmp_path))
        gathered = items("live", "stale")
        live = {"live"}
        diff = diff_source(st, "mail", gathered,
                           verify=lambda i: i["title"] in live)
        assert [i["title"] for i in diff.new_items] == ["live"]
        st.commit("mail", diff.new_items)
        # The stale item was never delivered, so it must NOT be
        # reported: once it verifies live, it surfaces.
        live.add("stale")
        diff2 = diff_source(st, "mail", gathered,
                            verify=lambda i: i["title"] in live)
        assert [i["title"] for i in diff2.new_items] == ["stale"]

    def test_verify_exception_means_not_live(self, tmp_path):
        st = BriefingState(str(tmp_path))

        def boom(_item):
            raise RuntimeError("checker died")

        diff = diff_source(st, "mail", items("a"), verify=boom)
        assert diff.new_items == [] and not diff.unreadable


# --------------------------------------------------------------------------- #
# run_digest — gather -> diff -> compose -> (caller) commit
# --------------------------------------------------------------------------- #

class TestRunDigest:
    def test_composes_delta_lines(self, tmp_path):
        run = run_digest(str(tmp_path), {
            "mail": lambda cur: items("Invoice", "Lunch?"),
            "news": lambda cur: [],
        })
        assert run.has_news
        assert any("mail: 2 new" in ln and "Invoice" in ln
                   for ln in run.lines)
        assert not any("news" in ln for ln in run.lines)  # no news, no line

    def test_failed_source_is_unreadable_never_empty(self, tmp_path):
        def boom(_cur):
            raise ConnectionError("store down")

        run = run_digest(str(tmp_path), {
            "mail": boom,
            "gone": lambda cur: None,
        })
        assert set(run.unreadable) == {"mail", "gone"}
        assert any("unreadable right now" in ln for ln in run.lines)
        assert not any("0 new" in ln for ln in run.lines)

    def test_no_commit_no_amnesia(self, tmp_path):
        # Delivery failed -> caller never commits -> the same items
        # diff again next run instead of being lost.
        sources = {"mail": lambda cur: items("a")}
        run_digest(str(tmp_path), sources)
        run2 = run_digest(str(tmp_path), sources)
        assert [i["title"] for i in run2.diffs[0].new_items] == ["a"]

    def test_commit_delivery_ends_the_story(self, tmp_path):
        sources = {"mail": lambda cur: {"items": items("a"),
                                         "cursor": "c2"}}
        run = run_digest(str(tmp_path), sources)
        run.commit_delivery()
        run2 = run_digest(str(tmp_path), sources)
        assert run2.diffs[0].new_items == []
        assert run2.lines == []

    def test_cursor_flows_to_the_next_gather(self, tmp_path):
        seen = []

        def gather(cur):
            seen.append(cur)
            return {"items": items("a"), "cursor": "next"}

        run = run_digest(str(tmp_path), {"mail": gather})
        run.commit_delivery()
        run_digest(str(tmp_path), {"mail": gather})
        assert seen == [None, "next"]

    def test_unreadable_source_keeps_its_cursor(self, tmp_path):
        st = BriefingState(str(tmp_path))
        st.commit("mail", [], cursor="keepme")
        run = run_digest(str(tmp_path), {"mail": lambda cur: None},
                         state=st)
        run.commit_delivery()
        assert st.cursor("mail") == "keepme"

    def test_line_cap(self, tmp_path):
        sources = {f"s{i}": (lambda cur, i=i: items(f"t{i}"))
                   for i in range(12)}
        run = run_digest(str(tmp_path), sources, line_cap=8)
        assert len(run.lines) == 9  # 8 capped + the 'more' line
        assert "more update" in run.lines[-1]
