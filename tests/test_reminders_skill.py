"""Tests for skills/reminders — the set/list/cancel/due pipeline."""

import importlib.util
import sys
import time
from pathlib import Path

import pytest

SKILL_PATH = Path(__file__).resolve().parent.parent / "skills" / "reminders" / "skill.py"
spec = importlib.util.spec_from_file_location("reminders_skill", SKILL_PATH)
rem = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rem)


class _Ctx:
    def __init__(self, jail):
        self.jail_dir = str(jail)


@pytest.fixture()
def ctx(tmp_path):
    return _Ctx(tmp_path)


class TestReminders:
    def test_set_and_list(self, ctx):
        out = rem.handle("reminder_set",
                         {"in_minutes": 30, "text": "Call mom"}, ctx)
        assert out["id"]
        listed = rem.handle("reminder_list", {}, ctx)
        assert len(listed["reminders"]) == 1
        assert listed["reminders"][0]["text"] == "Call mom"

    def test_due_empty_when_future(self, ctx):
        rem.handle("reminder_set", {"in_minutes": 60, "text": "Later"}, ctx)
        assert rem.handle("reminder_due", {}, ctx)["due"] == []

    def test_due_fires_when_past(self, ctx):
        out = rem.handle("reminder_set",
                         {"in_minutes": 1, "text": "Now"}, ctx)
        # Fast-forward: rewrite the stored due time into the past.
        items = rem._load(ctx)
        items[0]["due"] = time.time() - 5
        rem._save(ctx, items)
        due = rem.handle("reminder_due", {}, ctx)["due"]
        assert len(due) == 1
        assert due[0]["id"] == out["id"]

    def test_cancel(self, ctx):
        out = rem.handle("reminder_set",
                         {"in_minutes": 10, "text": "X"}, ctx)
        assert rem.handle("reminder_cancel", {"id": out["id"]}, ctx)["cancelled"] is True
        assert rem.handle("reminder_list", {}, ctx)["reminders"] == []
        assert rem.handle("reminder_cancel", {"id": out["id"]}, ctx)["cancelled"] is False

    def test_purge_due_rings_once(self, ctx):
        rem.handle("reminder_set", {"in_minutes": 1, "text": "Ring"}, ctx)
        items = rem._load(ctx)
        items[0]["due"] = time.time() - 1
        rem._save(ctx, items)
        assert len(rem.purge_due(ctx)) == 1
        assert rem.purge_due(ctx) == []

    def test_persistence_across_loads(self, ctx):
        rem.handle("reminder_set", {"in_minutes": 5, "text": "Persist"}, ctx)
        # Fresh module state would still read the same file.
        assert rem._load(ctx)[0]["text"] == "Persist"
