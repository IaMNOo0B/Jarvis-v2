"""Builder Team E — jarvis/morning_digest.py.

Deterministic briefing composition: sections come from real stores,
missing/corrupt stores skip silently, and the digest NEVER raises.
"""

import json
import sqlite3
import time
from datetime import datetime, timezone

from jarvis.morning_digest import build_digest, digest_lines
from jarvis.session_store import SessionStore

# Fixed "now": Tuesday 2026-10-20, 08:00 local.
NOW = time.mktime((2026, 10, 20, 8, 0, 0, 0, 0, -1))


def _epoch(y, m, d, hh=9, mm=0):
    return time.mktime((y, m, d, hh, mm, 0, 0, 0, -1))


def _iso_utc(epoch):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(
        timespec="milliseconds")


def _write_reminders(data_dir, items):
    (data_dir / "reminders.json").write_text(
        json.dumps(items), encoding="utf-8")


def _seed_sessions_db(data_dir, rows):
    """Create a real sessions.db, then insert events with crafted ts.

    rows: list of (session_id, ts_iso, type)
    """
    store = SessionStore(str(data_dir / "sessions.db"))  # builds schema
    sids = {r[0] for r in rows}
    store.close()
    conn = sqlite3.connect(str(data_dir / "sessions.db"))
    for sid in sids:
        conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, profile_id,"
            " surface, state, created_ts, updated_ts, last_seq)"
            " VALUES (?, 'owais', 'test', 'active', ?, ?, 0)",
            (sid, _iso_utc(NOW - 86400), _iso_utc(NOW - 86400)))
    for n, (sid, ts, typ) in enumerate(rows):
        conn.execute(
            "INSERT INTO events (event_id, session_id, seq, trace_id,"
            " ts, type, causal_parent, actor, trust, payload)"
            " VALUES (?, ?, ?, 'trace', ?, ?, NULL, 'owais', 'user', '{}')",
            (f"evt-{n}", sid, n + 1, ts, typ))
    conn.commit()
    conn.close()


class TestGreetingAndEmptyStores:
    def test_empty_data_dir_never_crashes(self, tmp_path):
        d = build_digest(str(tmp_path), now=NOW)
        assert d["date"] == "2026-10-20"
        assert d["lines"][0].startswith("Good morning, sir.")
        assert "Tuesday" in d["lines"][0]
        assert d["reminders_today"] == []
        assert d["yesterday"] is None
        assert d["pending_approvals"] is None
        # Disk section survives even when nothing else exists.
        assert d["disk"] is not None

    def test_digest_is_deterministic(self, tmp_path):
        _write_reminders(tmp_path, [
            {"id": "a", "due": _epoch(2026, 10, 20, 9, 30), "text": "Call"}])
        assert build_digest(str(tmp_path), now=NOW) == \
            build_digest(str(tmp_path), now=NOW)


class TestRemindersSection:
    def test_todays_reminders_listed_with_times(self, tmp_path):
        _write_reminders(tmp_path, [
            {"id": "a", "due": _epoch(2026, 10, 20, 9, 30),
             "text": "Call mom"},
            {"id": "b", "due": _epoch(2026, 10, 20, 17, 0),
             "text": "Gym"},
            {"id": "c", "due": _epoch(2026, 10, 21, 9, 0),
             "text": "Tomorrow thing"},
            {"id": "d", "due": _epoch(2026, 10, 19, 9, 0),
             "text": "Yesterday thing"},
        ])
        d = build_digest(str(tmp_path), now=NOW)
        assert [r["text"] for r in d["reminders_today"]] == ["Call mom", "Gym"]
        line = [ln for ln in d["lines"] if "reminder" in ln][0]
        assert "2 reminders today" in line
        assert "09:30 Call mom" in line and "17:00 Gym" in line
        assert "Tomorrow thing" not in line

    def test_proactivity_dict_format_also_read(self, tmp_path):
        # ReminderStore shape: {"reminders": {id: {when_ts, text, fired}}}
        _write_reminders(tmp_path, {"reminders": {
            "r1": {"id": "r1", "text": "Stand up",
                   "when_ts": _epoch(2026, 10, 20, 12, 0), "fired": False},
            "r2": {"id": "r2", "text": "Already fired",
                   "when_ts": _epoch(2026, 10, 20, 7, 0), "fired": True},
        }})
        d = build_digest(str(tmp_path), now=NOW)
        assert [r["text"] for r in d["reminders_today"]] == ["Stand up"]

    def test_corrupt_reminders_file_skips_section(self, tmp_path):
        (tmp_path / "reminders.json").write_text("{not json!!",
                                                 encoding="utf-8")
        d = build_digest(str(tmp_path), now=NOW)
        assert d["reminders_today"] == []
        assert not any("reminder" in ln for ln in d["lines"])


class TestYesterdaySection:
    def test_counts_yesterday_only(self, tmp_path):
        y = _epoch(2026, 10, 19, 15, 0)
        _seed_sessions_db(tmp_path, [
            ("s1", _iso_utc(y), "user.message"),
            ("s1", _iso_utc(y + 60), "brain.reply"),
            ("s1", _iso_utc(y + 120), "user.message"),
            ("s2", _iso_utc(y + 180), "session.started"),
            ("s1", _iso_utc(_epoch(2026, 10, 18, 15, 0)), "user.message"),
            ("s1", _iso_utc(NOW), "user.message"),  # today — excluded
        ])
        d = build_digest(str(tmp_path), now=NOW)
        ys = d["yesterday"]
        assert ys is not None
        assert ys["sessions"] == 2
        assert ys["events"] == 4
        assert ys["user_messages"] == 2
        assert ys["replies"] == 1
        assert any(ln.startswith("Yesterday:") for ln in d["lines"])

    def test_no_activity_yesterday_skips(self, tmp_path):
        _seed_sessions_db(tmp_path, [
            ("s1", _iso_utc(NOW), "user.message")])
        d = build_digest(str(tmp_path), now=NOW)
        assert d["yesterday"] is None
        assert not any(ln.startswith("Yesterday:") for ln in d["lines"])

    def test_missing_db_skips(self, tmp_path):
        d = build_digest(str(tmp_path), now=NOW)
        assert d["yesterday"] is None


class TestApprovalsSection:
    def test_injected_count(self, tmp_path):
        d = build_digest(str(tmp_path), now=NOW, pending_approvals=2)
        assert d["pending_approvals"] == 2
        assert any("2 approvals are waiting" in ln for ln in d["lines"])

    def test_injected_list_and_zero(self, tmp_path):
        d = build_digest(str(tmp_path), now=NOW,
                         pending_approvals=[{"a": 1}, {"b": 2}, {"c": 3}])
        assert d["pending_approvals"] == 3
        d0 = build_digest(str(tmp_path), now=NOW, pending_approvals=0)
        assert d0["pending_approvals"] == 0
        assert not any("approval" in ln for ln in d0["lines"])

    def test_pending_file(self, tmp_path):
        (tmp_path / "pending_approvals.json").write_text(
            json.dumps([{"id": "1"}, {"id": "2"}]), encoding="utf-8")
        d = build_digest(str(tmp_path), now=NOW)
        assert d["pending_approvals"] == 2


class TestDiskSection:
    def test_disk_present_and_sane(self, tmp_path):
        d = build_digest(str(tmp_path), now=NOW)
        disk = d["disk"]
        assert disk is not None
        assert 0 <= disk["free_pct"] <= 100
        assert disk["total_gb"] > 0


class TestLinesHelper:
    def test_digest_lines_matches_build(self, tmp_path):
        lines = digest_lines(str(tmp_path), now=NOW, pending_approvals=1)
        assert lines == build_digest(
            str(tmp_path), now=NOW, pending_approvals=1)["lines"]
