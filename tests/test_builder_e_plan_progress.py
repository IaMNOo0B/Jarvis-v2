"""Builder Team E — jarvis/plan_progress.py.

Measured progress from plan checkboxes. The sacred rule under test:
a plan with zero steps is NEVER complete.
"""

import pytest

from jarvis.plan_progress import (
    PlanProgress,
    parse_plan,
    parse_plan_file,
    progress_line,
    progress_of,
)

PLAN = """# Build plan

Intro prose — not a step.

## Task 1: Setup
- [x] Clone repo
- [x] Install deps

## Task 2: Core
- [x] Write parser
- [ ] Write tests
- [ ] Wire into watcher

## Task 3: Ship
- [ ] Tag release
- [ ] Announce

Not a checkbox: [ ] this is mid-line prose
"""


class TestParsePlan:
    def test_counts(self):
        p = parse_plan(PLAN)
        assert p.total == 7
        assert p.done == 3

    def test_next_open_is_first_unticked(self):
        assert parse_plan(PLAN).next_open == "Write tests"

    def test_mid_line_brackets_ignored(self):
        p = parse_plan("Some [ ] prose\n- [x] real step\n")
        assert (p.done, p.total) == (1, 1)

    def test_uppercase_x_counts_done(self):
        p = parse_plan("- [X] Shouted done\n- [ ] open\n")
        assert p.done == 1 and p.next_open == "open"

    def test_star_and_plus_bullets(self):
        p = parse_plan("* [ ] star\n+ [x] plus\n")
        assert (p.done, p.total) == (1, 2)

    def test_indented_checkboxes(self):
        p = parse_plan("  - [ ] nested step\n    - [x] deep done\n")
        assert (p.done, p.total) == (1, 2)

    def test_empty_text(self):
        p = parse_plan("")
        assert (p.done, p.total, p.next_open) == (0, 0, None)

    def test_dict_shape(self):
        d = progress_of(PLAN)
        assert d == {"done": 3, "total": 7, "next_open": "Write tests",
                     "complete": False}


class TestZeroStepsNeverDone:
    def test_no_checkboxes_is_not_complete(self):
        p = parse_plan("# Plan\n\nJust headings and hope.\n")
        assert p.total == 0
        assert p.complete is False

    def test_empty_plan_is_not_complete(self):
        assert PlanProgress(done=0, total=0).complete is False
        assert parse_plan("").complete is False


class TestComplete:
    def test_all_ticked(self):
        p = parse_plan("- [x] a\n- [x] b\n")
        assert p.complete is True
        assert p.next_open is None

    def test_almost_is_not_complete(self):
        assert parse_plan("- [x] a\n- [ ] b\n").complete is False


class TestProgressLine:
    def test_partial_line_format(self, tmp_path):
        f = tmp_path / "plan.md"
        f.write_text(PLAN, encoding="utf-8")
        assert progress_line(str(f)) == "3 of 7 done — next: Write tests"

    def test_complete_line(self, tmp_path):
        f = tmp_path / "plan.md"
        f.write_text("- [x] a\n- [x] b\n", encoding="utf-8")
        assert progress_line(str(f)) == "2 of 2 done — plan complete"

    def test_zero_steps_line(self, tmp_path):
        f = tmp_path / "plan.md"
        f.write_text("# Nothing here yet\n", encoding="utf-8")
        assert progress_line(str(f)) == (
            "0 of 0 done — the plan has no steps yet")

    def test_parse_plan_file(self, tmp_path):
        f = tmp_path / "plan.md"
        f.write_text(PLAN, encoding="utf-8")
        p = parse_plan_file(str(f))
        assert (p.done, p.total) == (3, 7)

    def test_missing_file_raises_honestly(self, tmp_path):
        with pytest.raises(OSError):
            progress_line(str(tmp_path / "nope.md"))
