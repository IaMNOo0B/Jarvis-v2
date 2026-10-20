"""Tests for skills/calendar — local calendar, RRULE-lite, ICS, brief."""

import importlib.util
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent / "skills" / "calendar"
SKILL_PATH = SKILL_DIR / "skill.py"
spec = importlib.util.spec_from_file_location("calendar_skill", SKILL_PATH)
cal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cal)

from jarvis.skills.registry import (  # noqa: E402
    SkillContext, SkillManifest, SkillRegistry, scan_skill)

ALLOW_ALL = lambda tool, tier, args, ctx: True  # noqa: E731
IST = timezone(timedelta(hours=5, minutes=30))


class _Ctx:
    def __init__(self, jail):
        self.jail_dir = str(jail)


@pytest.fixture()
def ctx(tmp_path):
    return _Ctx(tmp_path)


def iso(y, mo, d, h=0, mi=0, tz=IST):
    return datetime(y, mo, d, h, mi, tzinfo=tz).isoformat()


def add(ctx, title, start, end, **kw):
    return cal.handle("cal_add",
                      {"title": title, "start": start, "end": end, **kw}, ctx)


def listed(ctx, rs, re_):
    return cal.handle("cal_list",
                      {"range_start": rs, "range_end": re_}, ctx)["events"]


# --------------------------------------------------------------------------- #
# Manifest, scan
# --------------------------------------------------------------------------- #

class TestManifest:
    def test_manifest_validates_all_tier1(self):
        raw = json.loads((SKILL_DIR / "skill.json").read_text("utf-8"))
        manifest = SkillManifest.from_dict(raw, source="calendar")
        assert manifest.name == "calendar"
        assert {t.name for t in manifest.tools} == {
            "cal_add", "cal_list", "cal_next", "cal_cancel",
            "cal_import_ics", "cal_export_ics", "cal_brief"}
        assert all(t.tier == 1 for t in manifest.tools)

    def test_static_scan_is_clean(self):
        assert scan_skill(SKILL_DIR) == []


# --------------------------------------------------------------------------- #
# Add / list / validation
# --------------------------------------------------------------------------- #

class TestAddList:
    def test_add_and_list_sorted(self, ctx):
        add(ctx, "Bravo", iso(2026, 10, 20, 14), iso(2026, 10, 20, 15))
        add(ctx, "Alpha", iso(2026, 10, 20, 9), iso(2026, 10, 20, 10))
        events = listed(ctx, iso(2026, 10, 20), iso(2026, 10, 21))
        assert [e["title"] for e in events] == ["Alpha", "Bravo"]
        assert events[0]["recurring"] is False

    def test_persistence_and_schema_version(self, ctx, tmp_path):
        add(ctx, "Persisted", iso(2026, 10, 20, 9), iso(2026, 10, 20, 10))
        raw = json.loads((tmp_path / "calendar.json").read_text("utf-8"))
        assert raw["schema_version"] == 1
        assert raw["events"][0]["title"] == "Persisted"
        events = listed(ctx, iso(2026, 10, 20), iso(2026, 10, 21))
        assert len(events) == 1  # a fresh read of the same jail sees it

    def test_naive_time_refused_in_plain_words(self, ctx):
        with pytest.raises(ValueError, match="timezone"):
            add(ctx, "Floating", "2026-10-20T09:00:00", "2026-10-20T10:00:00")

    def test_end_must_follow_start(self, ctx):
        with pytest.raises(ValueError, match="after start"):
            add(ctx, "Backwards", iso(2026, 10, 20, 10), iso(2026, 10, 20, 9))

    def test_zulu_accepted(self, ctx):
        out = add(ctx, "UTC", "2026-10-20T03:30:00Z", "2026-10-20T04:30:00Z")
        assert out["start"].startswith("2026-10-20T03:30:00")

    def test_bad_recurrence_refused(self, ctx):
        with pytest.raises(ValueError, match="freq"):
            add(ctx, "X", iso(2026, 10, 20, 9), iso(2026, 10, 20, 10),
                recurrence={"freq": "yearly"})
        with pytest.raises(ValueError, match="either until or count"):
            add(ctx, "X", iso(2026, 10, 20, 9), iso(2026, 10, 20, 10),
                recurrence={"freq": "daily", "count": 3,
                            "until": iso(2027, 1, 1)})


# --------------------------------------------------------------------------- #
# Recurrence expansion
# --------------------------------------------------------------------------- #

class TestRecurrence:
    def test_daily_count(self, ctx):
        add(ctx, "Standup", iso(2026, 10, 20, 7), iso(2026, 10, 20, 7, 30),
            recurrence={"freq": "daily", "count": 4})
        events = listed(ctx, iso(2026, 10, 1), iso(2026, 12, 1))
        assert [e["start"][8:10] for e in events] == ["20", "21", "22", "23"]
        assert all(e["recurring"] for e in events)

    def test_weekly_until_inclusive(self, ctx):
        add(ctx, "Gym", iso(2026, 10, 5, 18), iso(2026, 10, 5, 19),
            recurrence={"freq": "weekly",
                        "until": iso(2026, 10, 19, 18)})
        events = listed(ctx, iso(2026, 10, 1), iso(2026, 12, 1))
        assert [e["start"][8:10] for e in events] == ["05", "12", "19"]

    def test_every_two_weeks(self, ctx):
        add(ctx, "Review", iso(2026, 10, 5, 10), iso(2026, 10, 5, 11),
            recurrence={"freq": "weekly", "interval": 2, "count": 3})
        events = listed(ctx, iso(2026, 10, 1), iso(2026, 12, 31))
        assert [e["start"][5:10] for e in events] == ["10-05", "10-19", "11-02"]

    def test_monthly_month_end_anchor(self, ctx):
        """Jan 31 monthly: Feb clamps to 28, March returns to 31."""
        add(ctx, "Rent", iso(2026, 1, 31, 9), iso(2026, 1, 31, 10),
            recurrence={"freq": "monthly", "count": 3})
        events = listed(ctx, iso(2026, 1, 1), iso(2026, 5, 1))
        assert [e["start"][:10] for e in events] == [
            "2026-01-31", "2026-02-28", "2026-03-31"]

    def test_open_ended_series_bounded_by_range(self, ctx):
        add(ctx, "Daily forever", iso(2026, 10, 20, 6), iso(2026, 10, 20, 7),
            recurrence={"freq": "daily"})
        events = listed(ctx, iso(2026, 10, 20), iso(2026, 10, 23))
        assert len(events) == 3  # the range bounds it, no runaway


# --------------------------------------------------------------------------- #
# Cancel: series vs single occurrence
# --------------------------------------------------------------------------- #

class TestCancel:
    def test_cancel_series(self, ctx):
        out = add(ctx, "Yoga", iso(2026, 10, 20, 7), iso(2026, 10, 20, 8),
                  recurrence={"freq": "daily", "count": 5})
        res = cal.handle("cal_cancel", {"id": out["id"]}, ctx)
        assert res == {"cancelled": True, "scope": "series"}
        assert listed(ctx, iso(2026, 10, 1), iso(2026, 12, 1)) == []

    def test_cancel_one_occurrence(self, ctx):
        out = add(ctx, "Yoga", iso(2026, 10, 20, 7), iso(2026, 10, 20, 8),
                  recurrence={"freq": "daily", "count": 4})
        res = cal.handle(
            "cal_cancel",
            {"id": out["id"], "occurrence_start": iso(2026, 10, 21, 7)}, ctx)
        assert res == {"cancelled": True, "scope": "occurrence"}
        events = listed(ctx, iso(2026, 10, 1), iso(2026, 12, 1))
        assert [e["start"][8:10] for e in events] == ["20", "22", "23"]

    def test_cancel_occurrence_of_single_event(self, ctx):
        out = add(ctx, "Once", iso(2026, 10, 20, 7), iso(2026, 10, 20, 8))
        res = cal.handle(
            "cal_cancel",
            {"id": out["id"], "occurrence_start": iso(2026, 10, 20, 7)}, ctx)
        assert res == {"cancelled": True, "scope": "occurrence"}
        assert listed(ctx, iso(2026, 10, 1), iso(2026, 12, 1)) == []

    def test_cancel_unknown_and_wrong_occurrence(self, ctx):
        assert cal.handle("cal_cancel", {"id": "nope"}, ctx)[
            "cancelled"] is False
        out = add(ctx, "Yoga", iso(2026, 10, 20, 7), iso(2026, 10, 20, 8),
                  recurrence={"freq": "daily", "count": 2})
        res = cal.handle(
            "cal_cancel",
            {"id": out["id"], "occurrence_start": iso(2026, 11, 5, 7)}, ctx)
        assert res["cancelled"] is False


# --------------------------------------------------------------------------- #
# cal_next
# --------------------------------------------------------------------------- #

class TestNext:
    def test_next_orders_and_limits(self, ctx):
        add(ctx, "Past", iso(2026, 10, 19, 9), iso(2026, 10, 19, 10))
        add(ctx, "Later", iso(2026, 10, 22, 9), iso(2026, 10, 22, 10))
        add(ctx, "Soon", iso(2026, 10, 20, 12), iso(2026, 10, 20, 13))
        add(ctx, "Daily", iso(2026, 10, 18, 8), iso(2026, 10, 18, 9),
            recurrence={"freq": "daily", "count": 10})
        out = cal.handle("cal_next",
                         {"count": 3, "now": iso(2026, 10, 20, 7)}, ctx)
        assert [e["title"] for e in out["events"]] == [
            "Daily", "Soon", "Daily"]  # Oct 20 daily, Soon, Oct 21 daily
        assert out["count"] == 3


# --------------------------------------------------------------------------- #
# ICS export / import round-trip
# --------------------------------------------------------------------------- #

def _views(ctx, rs=None, re_=None):
    """Occurrence views compared as instants (export normalizes to UTC)."""
    rs = rs or iso(2026, 1, 1)
    re_ = re_ or iso(2027, 6, 1)
    out = []
    for e in listed(ctx, rs, re_):
        out.append({
            "id": e["id"], "title": e["title"],
            "start": datetime.fromisoformat(e["start"]),
            "end": datetime.fromisoformat(e["end"]),
            "location": e["location"], "notes": e["notes"],
            "recurring": e["recurring"]})
    return sorted(out, key=lambda v: (v["start"], v["title"]))


class TestIcsRoundTrip:
    def test_round_trip_equal_on_supported_subset(self, ctx, tmp_path):
        add(ctx, "Plan, review; Q3", iso(2026, 10, 20, 9),
            iso(2026, 10, 20, 10, 30), location="Room 4, HQ",
            notes="Line one\nLine two; bring files")
        add(ctx, "A very long weekly planning meeting title that must "
                 "survive RFC line folding intact",
            iso(2026, 10, 5, 18), iso(2026, 10, 5, 19),
            recurrence={"freq": "weekly", "count": 6})
        rent = add(ctx, "Rent", iso(2026, 1, 31, 9), iso(2026, 1, 31, 10),
                   recurrence={"freq": "monthly", "count": 4})
        cal.handle("cal_cancel",
                   {"id": rent["id"],
                    "occurrence_start": iso(2026, 2, 28, 9)}, ctx)
        before = _views(ctx)

        exported = cal.handle("cal_export_ics", {}, ctx)
        assert exported["events"] == 3
        assert "BEGIN:VCALENDAR" in exported["ics"]

        other = tmp_path / "other"
        other.mkdir()
        ctx2 = _Ctx(other)
        report = cal.handle("cal_import_ics",
                            {"ics_text": exported["ics"]}, ctx2)
        assert report["imported"] == 3
        assert report["skipped"] == []
        assert report["unsupported"] == []
        assert _views(ctx2) == before  # import(export(x)) == x

    def test_duplicate_import_skipped_and_reported(self, ctx):
        add(ctx, "Once", iso(2026, 10, 20, 9), iso(2026, 10, 20, 10))
        ics = cal.handle("cal_export_ics", {}, ctx)["ics"]
        report = cal.handle("cal_import_ics", {"ics_text": ics}, ctx)
        assert report["imported"] == 0
        assert report["skipped"] and "already exists" in \
            report["skipped"][0]["reason"]


class TestIcsUnsupportedHonesty:
    def test_yearly_rrule_imports_as_single_and_reports(self, ctx):
        ics = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            "UID:yearly-1\r\nDTSTART:20261020T090000Z\r\n"
            "DTEND:20261020T100000Z\r\nSUMMARY:Birthday\r\n"
            "RRULE:FREQ=YEARLY\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
        report = cal.handle("cal_import_ics", {"ics_text": ics}, ctx)
        assert report["imported"] == 1
        assert any(u["construct"] == "RRULE" for u in report["unsupported"])
        events = listed(ctx, iso(2026, 10, 1), iso(2027, 12, 1))
        assert len(events) == 1  # single event, no phantom yearly series

    def test_valarm_and_unknown_property_reported(self, ctx):
        ics = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            "UID:alarm-1\r\nDTSTART:20261020T090000Z\r\n"
            "DTEND:20261020T100000Z\r\nSUMMARY:Wake\r\n"
            "X-CUSTOM-THING:abc\r\n"
            "BEGIN:VALARM\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n")
        report = cal.handle("cal_import_ics", {"ics_text": ics}, ctx)
        assert report["imported"] == 1
        constructs = {u["construct"] for u in report["unsupported"]}
        assert "VALARM" in constructs
        assert "X-CUSTOM-THING" in constructs

    def test_floating_and_date_starts_skipped(self, ctx):
        ics = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:f1\r\nDTSTART:20261020T090000\r\n"
            "DTEND:20261020T100000\r\nSUMMARY:Floating\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:d1\r\nDTSTART;VALUE=DATE:20261020\r\n"
            "SUMMARY:All day\r\nEND:VEVENT\r\n"
            "END:VCALENDAR\r\n")
        report = cal.handle("cal_import_ics", {"ics_text": ics}, ctx)
        assert report["imported"] == 0
        reasons = " ".join(s["reason"] for s in report["skipped"])
        assert "floating" in reasons
        assert "all-day" in reasons

    def test_missing_dtend_assumed_and_reported(self, ctx):
        ics = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            "UID:open-1\r\nDTSTART:20261020T090000Z\r\n"
            "SUMMARY:Open ended\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
        report = cal.handle("cal_import_ics", {"ics_text": ics}, ctx)
        assert report["imported"] == 1
        assert any(u["construct"] == "DTEND" for u in report["unsupported"])
        events = listed(ctx, iso(2026, 10, 20), iso(2026, 10, 21))
        assert events[0]["end"].startswith("2026-10-20T10:00")


# --------------------------------------------------------------------------- #
# Brief
# --------------------------------------------------------------------------- #

class TestBrief:
    def _seed(self, ctx):
        add(ctx, "Dentist", iso(2026, 10, 20, 9), iso(2026, 10, 20, 10, 30),
            location="City Clinic")
        add(ctx, "Team call", iso(2026, 10, 20, 10), iso(2026, 10, 20, 11),
            location="Home")
        add(ctx, "Site visit", iso(2026, 10, 20, 11, 10),
            iso(2026, 10, 20, 12), location="Office")
        add(ctx, "Flight to Delhi", iso(2026, 10, 21, 7, 30),
            iso(2026, 10, 21, 9))

    def test_brief_full(self, ctx):
        self._seed(ctx)
        out = cal.handle("cal_brief",
                         {"now": iso(2026, 10, 20, 8)}, ctx)
        brief = out["brief"]
        assert out["events_today"] == 3
        assert out["conflicts"] == 1
        assert brief.startswith(
            "Calendar brief for Tuesday, 20 October 2026.")
        assert "9:00–10:30 AM — Dentist at City Clinic" in brief
        assert "Conflict: Dentist overlaps Team call (10:00–10:30 AM)" \
            in brief
        assert "only 10 minutes between Team call (Home) and " \
               "Site visit (Office)" in brief
        assert "Tomorrow starts with Flight to Delhi at 7:30 AM." in brief

    def test_brief_empty_day(self, ctx):
        out = cal.handle("cal_brief", {"now": iso(2026, 11, 2, 8)}, ctx)
        assert "Nothing scheduled today." in out["brief"]
        assert "Nothing on the calendar tomorrow." in out["brief"]
        assert out["events_today"] == 0


# --------------------------------------------------------------------------- #
# End-to-end through the real registry pipeline
# --------------------------------------------------------------------------- #

class TestRegistryDispatch:
    @pytest.fixture()
    def reg(self, tmp_path):
        skills = tmp_path / "skills"
        skills.mkdir()
        shutil.copytree(SKILL_DIR, skills / "calendar")
        data = tmp_path / "data"
        data.mkdir()
        registry = SkillRegistry(skills, data)
        registry.discover()
        return registry

    def _skill_ctx(self, tmp_path):
        jail = tmp_path / "jail"
        jail.mkdir(exist_ok=True)
        return SkillContext(
            skill_name="calendar",
            capabilities=["fs.read", "fs.write", "time.read"],
            jail_dir=str(jail))

    def test_discovery_clean_and_quarantined_until_approved(self, reg):
        rec = reg._records["calendar"]
        assert rec.load_error is None
        assert reg.quarantine() == ["calendar"]

    def test_dispatch_add_list_brief(self, reg, tmp_path):
        ctx = self._skill_ctx(tmp_path)
        out = reg.dispatch(
            "cal_add",
            {"title": "Dentist", "start": iso(2026, 10, 20, 9),
             "end": iso(2026, 10, 20, 10)}, ctx, ALLOW_ALL)
        assert out["ok"] is False
        assert out["error"]["code"] == "skill_quarantined"

        reg.approve("calendar")
        out = reg.dispatch(
            "cal_add",
            {"title": "Dentist", "start": iso(2026, 10, 20, 9),
             "end": iso(2026, 10, 20, 10)}, ctx, ALLOW_ALL)
        assert out["ok"] is True
        assert out["result"]["id"]

        out = reg.dispatch("cal_next",
                           {"now": iso(2026, 10, 20, 8)}, ctx, ALLOW_ALL)
        assert out["ok"] is True
        assert out["result"]["events"][0]["title"] == "Dentist"
