"""Tests for jarvis/analytics.py — the canonical event-transform layer.

Pure functions over canned event streams: flood (gap-fill / midpoint
split / later-wins overlap), merge_adjacent, classify (owner rules),
period_summary (per-category day totals with midnight clipping), and
intersect. Every test also pins the layer's hard guarantees where
relevant: inputs are never mutated and outputs are deterministic.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.analytics import (
    Event,
    classify,
    flood,
    intersect,
    merge_adjacent,
    period_summary,
)


def ev(ts, dur=0.0, **data):
    return Event(float(ts), float(dur), data)


# --------------------------------------------------------------------- Event

class TestEvent:
    def test_end_and_defaults(self):
        e = Event(100, 30)
        assert e.end == 130
        assert e.data == {}
        assert Event(5).duration_s == 0.0  # point sample

    def test_negative_duration_rejected(self):
        with pytest.raises(ValueError):
            Event(0, -1)

    def test_int_inputs_coerced_to_float(self):
        e = Event(10, 5)
        assert isinstance(e.ts, float) and isinstance(e.duration_s, float)


# --------------------------------------------------------------------- flood

class TestFlood:
    def test_small_gap_equal_data_merges(self):
        out = flood([ev(0, 10, app="code"), ev(13, 10, app="code")],
                    pulsetime=5)
        assert len(out) == 1
        assert out[0].ts == 0 and out[0].end == 23

    def test_small_gap_different_data_splits_at_midpoint(self):
        # gap is [10, 14); midpoint 12: prev extends to 12, next starts 12.
        out = flood([ev(0, 10, app="code"), ev(14, 10, app="web")],
                    pulsetime=5)
        assert [(e.ts, e.end, e.data["app"]) for e in out] == [
            (0, 12, "code"), (12, 24, "web")]

    def test_large_gap_untouched(self):
        out = flood([ev(0, 10, app="code"), ev(100, 10, app="code")],
                    pulsetime=5)
        assert [(e.ts, e.end) for e in out] == [(0, 10), (100, 110)]

    def test_gap_exactly_pulsetime_merges(self):
        out = flood([ev(0, 10, app="a"), ev(15, 10, app="a")], pulsetime=5)
        assert len(out) == 1 and out[0].end == 25

    def test_overlap_later_event_wins(self):
        out = flood([ev(0, 30, app="code"), ev(10, 10, app="web")])
        assert [(e.ts, e.end, e.data["app"]) for e in out] == [
            (0, 10, "code"), (10, 20, "web")]

    def test_later_event_truncates_earlier_span(self):
        # b spans 0-30; a (10-15) starts inside b. The later event
        # wins its span: b is truncated to end where a begins.
        out = flood([ev(10, 5, app="a"), ev(0, 30, app="b")])
        assert [(e.ts, e.end, e.data["app"]) for e in out] == [
            (0, 10, "b"), (10, 15, "a")]
        # No second of time is ever double-counted.
        assert sum(e.duration_s for e in out) == 15

    def test_fully_covered_event_dropped(self):
        # Same start, later event longer: the earlier event is
        # entirely inside the later one's span and disappears.
        out = flood([ev(10, 5, app="a"), ev(10, 30, app="b")])
        assert [(e.ts, e.end, e.data["app"]) for e in out] == [
            (10, 40, "b")]

    def test_point_pulses_merge_across_small_gaps(self):
        # heartbeat-style points 3s apart, same data -> one span.
        out = flood([ev(0, 0, app="code"), ev(3, 0, app="code"),
                     ev(6, 0, app="code")], pulsetime=5)
        assert len(out) == 1 and out[0].ts == 0 and out[0].end == 6

    def test_unsorted_input_sorted_output(self):
        out = flood([ev(100, 10, app="b"), ev(0, 10, app="a")])
        assert [e.ts for e in out] == [0, 100]

    def test_chain_of_merges(self):
        out = flood([ev(0, 10, app="a"), ev(12, 10, app="a"),
                     ev(24, 10, app="a")], pulsetime=5)
        assert len(out) == 1 and out[0].end == 34

    def test_empty_and_single(self):
        assert flood([]) == []
        one = [ev(5, 5, app="a")]
        assert flood(one) == one

    def test_input_not_mutated(self):
        src = [ev(0, 10, app="a"), ev(12, 10, app="b")]
        snapshot = [(e.ts, e.duration_s, dict(e.data)) for e in src]
        flood(src)
        assert [(e.ts, e.duration_s, e.data) for e in src] == snapshot

    def test_negative_pulsetime_rejected(self):
        with pytest.raises(ValueError):
            flood([ev(0, 1)], pulsetime=-1)


# ------------------------------------------------------------- merge_adjacent

class TestMergeAdjacent:
    def test_touching_equal_data_merges(self):
        out = merge_adjacent([ev(0, 10, app="a"), ev(10, 10, app="a")])
        assert len(out) == 1 and out[0].end == 20

    def test_gap_does_not_merge(self):
        out = merge_adjacent([ev(0, 10, app="a"), ev(11, 10, app="a")])
        assert len(out) == 2

    def test_different_data_does_not_merge(self):
        out = merge_adjacent([ev(0, 10, app="a"), ev(10, 10, app="b")])
        assert len(out) == 2

    def test_overlap_unions_span(self):
        out = merge_adjacent([ev(0, 30, app="a"), ev(10, 10, app="a")])
        assert len(out) == 1 and out[0].end == 30

    def test_key_function_merges_on_subset_keeps_first_data(self):
        out = merge_adjacent(
            [ev(0, 10, app="code", title="x.py"),
             ev(10, 10, app="code", title="y.py")],
            key=lambda d: d.get("app"))
        assert len(out) == 1
        assert out[0].data["title"] == "x.py"  # first event's data kept
        assert out[0].end == 20

    def test_key_function_distinguishes(self):
        out = merge_adjacent(
            [ev(0, 10, app="code"), ev(10, 10, app="web")],
            key=lambda d: d.get("app"))
        assert len(out) == 2

    def test_input_not_mutated(self):
        src = [ev(0, 10, app="a"), ev(10, 10, app="a")]
        merge_adjacent(src)
        assert src[0].duration_s == 10


# ------------------------------------------------------------------ classify

RULES = [("github", "work"), (r"youtube\.com", "distraction", "regex"),
         ("code", "work")]


class TestClassify:
    def test_substring_rule_case_insensitive(self):
        out = classify([ev(0, 5, title="GitHub - PR review")], RULES)
        assert out[0].data["category"] == "work"

    def test_regex_rule(self):
        out = classify([ev(0, 5, url="https://youtube.com/watch?v=1")],
                       RULES)
        assert out[0].data["category"] == "distraction"

    def test_first_match_wins(self):
        # both "github" (work) and "code" (work) could hit; specific
        # ordering decides when categories differ:
        rules = [("github", "work"), ("git", "distraction")]
        out = classify([ev(0, 5, title="github")], rules)
        assert out[0].data["category"] == "work"

    def test_no_match_passes_through_without_category(self):
        out = classify([ev(0, 5, title="a walk outside")], RULES)
        assert "category" not in out[0].data

    def test_dict_rule_form(self):
        rules = [{"match": "standup", "category": "meetings"},
                 {"pattern": r"\.py$", "category": "coding", "regex": True}]
        assert classify([ev(0, 5, title="daily standup")],
                        rules)[0].data["category"] == "meetings"
        assert classify([ev(0, 5, title="main.py")],
                        rules)[0].data["category"] == "coding"

    def test_malformed_rules_fail_loud(self):
        with pytest.raises(ValueError):
            classify([ev(0, 1)], [("only-one-element",)])
        with pytest.raises(ValueError):
            classify([ev(0, 1)], [("x", "cat", "not-a-mode")])
        with pytest.raises(ValueError):
            classify([ev(0, 1)], [{"category": "cat"}])  # no pattern

    def test_input_event_data_not_mutated(self):
        src = ev(0, 5, title="github")
        classify([src], RULES)
        assert "category" not in src.data


# ------------------------------------------------------------- period_summary

DAY = "2026-10-20"
DAY_START = 1792454400.0  # 2026-10-20T00:00:00Z


class TestPeriodSummary:
    def test_totals_per_category(self):
        events = [
            ev(DAY_START + 3600, 1800, category="work"),
            ev(DAY_START + 7200, 900, category="work"),
            ev(DAY_START + 8000, 600, category="rest"),
        ]
        s = period_summary(events, DAY)
        assert s["day"] == DAY
        assert s["by_category"] == {"work": 2700.0, "rest": 600.0}
        assert s["total_s"] == 3300.0

    def test_uncategorized_bucket(self):
        s = period_summary([ev(DAY_START + 10, 60, app="x")], DAY)
        assert s["by_category"] == {"uncategorized": 60.0}

    def test_midnight_spanning_event_clipped(self):
        # 23:00 -> 01:00 next day: only 3600s belong to DAY.
        events = [ev(DAY_START + 82800, 7200, category="work")]
        s = period_summary(events, DAY)
        assert s["by_category"]["work"] == 3600.0
        s2 = period_summary(events, "2026-10-21")
        assert s2["by_category"]["work"] == 3600.0

    def test_events_outside_day_excluded(self):
        events = [ev(DAY_START - 7200, 3600, category="work"),
                  ev(DAY_START + 90000, 3600, category="work")]
        s = period_summary(events, DAY)
        assert s["total_s"] == 0.0 and s["by_category"] == {}

    def test_point_events_contribute_nothing(self):
        s = period_summary([ev(DAY_START + 5, 0, category="work")], DAY)
        assert s["total_s"] == 0.0

    def test_date_object_accepted(self):
        s = period_summary([ev(DAY_START + 5, 10, category="a")],
                           date(2026, 10, 20))
        assert s["day"] == "2026-10-20" and s["total_s"] == 10.0

    def test_garbage_day_fails_loud(self):
        with pytest.raises(ValueError):
            period_summary([], "not-a-day")

    def test_by_category_ordering_deterministic(self):
        events = [ev(DAY_START + 1, 100, category="b"),
                  ev(DAY_START + 200, 300, category="a"),
                  ev(DAY_START + 600, 300, category="c")]
        s = period_summary(events, DAY)
        assert list(s["by_category"]) == ["a", "c", "b"]  # (-s, name)


# ----------------------------------------------------------------- intersect

class TestIntersect:
    def test_basic_clipping(self):
        a = [ev(0, 100, app="code")]
        b = [ev(30, 40)]  # covers 30..70
        out = intersect(a, b)
        assert [(e.ts, e.end, e.data["app"]) for e in out] == [
            (30, 70, "code")]

    def test_multiple_pieces_from_one_event(self):
        a = [ev(0, 100, app="code")]
        b = [ev(10, 10), ev(50, 10)]
        out = intersect(a, b)
        assert [(e.ts, e.end) for e in out] == [(10, 20), (50, 60)]

    def test_no_overlap_empty(self):
        assert intersect([ev(0, 10)], [ev(50, 10)]) == []

    def test_point_event_inside_span_kept(self):
        out = intersect([ev(50, 0, app="ping")], [ev(0, 100)])
        assert len(out) == 1 and out[0].duration_s == 0

    def test_point_event_outside_span_dropped(self):
        assert intersect([ev(150, 0)], [ev(0, 100)]) == []

    def test_empty_inputs(self):
        assert intersect([], [ev(0, 1)]) == []
        assert intersect([ev(0, 1)], []) == []

    def test_inputs_not_mutated(self):
        a = [ev(0, 100, app="x")]
        intersect(a, [ev(10, 10)])
        assert a[0].duration_s == 100


# ------------------------------------------------------------- end-to-end-ish

def test_pipeline_flood_classify_summarize():
    """The canonical flow: raw noisy points -> flood -> classify ->
    daily totals, exactly as a digest consumer would run it."""
    raw = [
        ev(DAY_START + 3600, 0, app="Code", title="main.py - VS Code"),
        ev(DAY_START + 3603, 0, app="Code", title="main.py - VS Code"),
        ev(DAY_START + 3606, 1200, app="Code", title="main.py - VS Code"),
        ev(DAY_START + 7200, 600, app="Chrome", title="YouTube"),
    ]
    flooded = flood(raw, pulsetime=5)
    tagged = classify(flooded, [("youtube", "distraction"),
                                 ("code", "work")])
    s = period_summary(tagged, DAY)
    assert s["by_category"]["distraction"] == 600.0
    # code span: points merge/flood to 3600..4806, minus nothing else
    assert s["by_category"]["work"] == 1206.0
    assert s["total_s"] == 1806.0
