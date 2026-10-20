"""Tests for Extension Team 7 — evolution_runner (CowAgent idle review).

Uses a real SessionStore + real Memory. Covers: the full happy-path
cycle (foundry drafts, diary roll-up, consolidation, anticipation
snapshot, persisted report), per-step failure isolation, the
anti-poisoning guard on the diary lesson (rejected text is removed from
memory again), the deterministic should_run gate (once-a-day + idle,
injected clocks), and the read_last_run / last_user_turn_at helpers.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.evolution_runner import (
    DEFAULT_IDLE_SECONDS,
    ReviewReport,
    _lesson_is_safe,
    last_user_turn_at,
    read_last_run,
    run_review,
    should_run,
)
from jarvis.memory import Memory
from jarvis.session_store import SessionStore

NOW = datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)
DIARY_DAY = "2026-10-19"  # NOW - 1 day


@pytest.fixture
def store(tmp_path):
    s = SessionStore(str(tmp_path / "sessions.db"))
    yield s
    s.close()


@pytest.fixture
def mem(tmp_path):
    m = Memory(tmp_path / "mem.db", profile_id="test")
    yield m
    m.close()


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


def call(store, sid, tool, verdict="allow"):
    return store.emit(sid, "tool.call",
                      {"tool": tool, "args": {}, "gate_verdict": verdict},
                      actor="brain", trust="user")


def success_seq(store, sid, tools):
    for t in tools:
        cid = call(store, sid, t)
        store.emit(sid, "tool.result", {"ok": True, "output": "..."},
                   actor="tool", trust="tool_untrusted",
                   causal_parent=cid)


def plant_episode(mem, day, summary, session_id="sess-1", hms="08:00:00"):
    with mem._lock:
        mem._conn.execute(
            "INSERT INTO episodes (profile_id, ts, summary, session_id)"
            " VALUES (?, ?, ?, ?)",
            (mem.profile_id, f"{day}T{hms}.000+00:00", summary, session_id),
        )
        mem._conn.commit()


def shift_events_to_day(store, day):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with store._lock:
        store._conn.execute(
            "UPDATE events SET ts = REPLACE(ts, ?, ?)", (today, day))
        store._conn.commit()


# ------------------------------------------------------------- happy path

def test_run_review_full_cycle(store, mem, data_dir):
    sid = store.create_session("test", "test")
    for _ in range(3):
        success_seq(store, sid, ["web_search", "note_save"])
    store.emit(sid, "user.message", {"text": "thanks jarvis"},
               actor="user", trust="user")
    shift_events_to_day(store, DIARY_DAY)
    plant_episode(mem, DIARY_DAY, "opened chrome and checked mail")
    plant_episode(mem, DIARY_DAY, "set a reminder for tea", hms="09:00:00")

    report = run_review(data_dir, store, mem, NOW)

    assert report.ok, report.steps
    assert report.silent is True
    assert report.day == "2026-10-20" and report.diary_day == DIARY_DAY
    # foundry drafted exactly one quarantined skill
    assert len(report.new_skills) == 1
    assert report.new_skills[0]["sequence"] == ["web_search", "note_save"]
    assert (data_dir / "foundry").is_dir()
    # diary rolled up yesterday, fed the day's session events
    assert report.diary is not None
    assert report.diary["episodes"] == 2
    assert report.steps["diary"]["detail"]["events_used"] == 13
    assert report.steps["diary"]["detail"]["lesson_check"] == "passed"
    assert mem.get_fact(f"diary:{DIARY_DAY}") is not None
    # consolidation ran and returned the four pass counters
    assert report.consolidation is not None
    assert set(report.consolidation) == {
        "expired", "deduped", "promoted", "decayed"}
    # anticipation snapshot: in the report AND appended on disk
    assert isinstance(report.anticipations, list)
    snap = data_dir / "evolution" / "anticipations.jsonl"
    lines = snap.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["ts"] == NOW.isoformat()
    # report persisted for the morning digest
    on_disk = json.loads(
        (data_dir / "evolution" / "last_review.json").read_text(
            encoding="utf-8"))
    assert on_disk["kind"] == "evolution_review"
    assert on_disk["silent"] is True and on_disk["ok"] is True
    assert "Night review:" in report.summary_line()
    # helper round-trip: the persisted run is the gate's last_run
    assert read_last_run(data_dir) == NOW


def test_run_review_second_run_drafts_nothing_new(store, mem, data_dir):
    sid = store.create_session("test", "test")
    for _ in range(3):
        success_seq(store, sid, ["web_search", "note_save"])
    first = run_review(data_dir, store, mem, NOW)
    second = run_review(data_dir, store, mem,
                        NOW + timedelta(days=1))
    assert len(first.new_skills) == 1
    assert second.new_skills == []  # foundry drafting is idempotent
    snap = data_dir / "evolution" / "anticipations.jsonl"
    assert len(snap.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_run_review_accepts_str_data_dir(store, mem, tmp_path):
    report = run_review(str(tmp_path / "data"), store, mem, NOW)
    assert report.ok, report.steps
    assert (tmp_path / "data" / "evolution" / "last_review.json").exists()


# --------------------------------------------------------- step isolation

def test_failing_step_does_not_stop_others(store, mem, data_dir):
    def boom(now_iso=None):
        raise RuntimeError("consolidate exploded")
    mem.consolidate = boom  # instance shadow: only this step is broken

    report = run_review(data_dir, store, mem, NOW)

    assert report.steps["consolidate"]["ok"] is False
    assert "consolidate exploded" in report.steps["consolidate"]["error"]
    assert report.failed_steps == ["consolidate"]
    assert report.ok is False
    for name in ("foundry", "diary", "anticipation", "persist"):
        assert report.steps[name]["ok"] is True, name


def test_corrupt_store_fails_only_store_backed_steps(mem, data_dir,
                                                     tmp_path):
    bad = tmp_path / "corrupt.db"
    bad.write_bytes(b"this is not a sqlite database at all" * 4)

    report = run_review(data_dir, str(bad), mem, NOW)

    assert report.steps["foundry"]["ok"] is False
    assert report.steps["anticipation"]["ok"] is False
    # diary degrades to episodes-only instead of dying with the store
    assert report.steps["diary"]["ok"] is True
    assert report.steps["diary"]["detail"]["events_used"] == 0
    assert report.steps["consolidate"]["ok"] is True
    assert report.steps["persist"]["ok"] is True
    assert report.ok is False


# --------------------------------------------------------- anti-poisoning

def test_lesson_filter_delegates_to_brain():
    assert _lesson_is_safe("Owner prefers tea in the morning") is True
    assert _lesson_is_safe("I can't do that") is False
    assert _lesson_is_safe("the web_search tool doesn't work") is False
    assert _lesson_is_safe("ye main nahi kar sakta") is False
    # a quoted counter-example is discussion, not a claim
    assert _lesson_is_safe("never say 'I can't do that'") is True
    assert _lesson_is_safe("") is False
    assert _lesson_is_safe("   ") is False


def test_poisoned_diary_is_rejected_and_removed(store, mem, data_dir):
    # an episode summary carrying a negative capability claim flows
    # into the composed diary value ("first: ...") — the guard must
    # catch it and the stored fact must not survive.
    plant_episode(mem, DIARY_DAY,
                  "jarvis answered I can't do that, it is beyond him")

    report = run_review(data_dir, store, mem, NOW)

    step = report.steps["diary"]
    assert step["ok"] is False
    assert "anti-poisoning" in step["error"]
    assert report.diary is None
    assert mem.get_fact(f"diary:{DIARY_DAY}") is None
    assert mem.tombstone_count(f"diary:{DIARY_DAY}") >= 1
    # the rejection does not take the rest of the cycle down with it
    assert report.steps["foundry"]["ok"] is True
    assert report.steps["consolidate"]["ok"] is True


# -------------------------------------------------------------- should_run

def test_should_run_first_ever_and_idle():
    assert should_run(None, NOW) is True
    assert should_run(None, NOW, last_user_turn=None) is True


def test_should_run_once_per_day():
    assert should_run(NOW - timedelta(hours=2), NOW) is False
    assert should_run(NOW - timedelta(days=1), NOW) is True
    # clock skew: a "last run" in the future blocks, never double-runs
    assert should_run(NOW + timedelta(hours=1), NOW) is False


def test_should_run_idle_gate():
    recent = NOW - timedelta(minutes=10)
    old = NOW - timedelta(minutes=31)
    assert should_run(None, NOW, last_user_turn=recent) is False
    assert should_run(None, NOW, last_user_turn=old) is True
    # exactly at the threshold counts as idle
    edge = NOW - timedelta(seconds=DEFAULT_IDLE_SECONDS)
    assert should_run(None, NOW, last_user_turn=edge) is True
    # custom threshold
    assert should_run(None, NOW, idle_seconds=60,
                      last_user_turn=NOW - timedelta(seconds=120)) is True
    assert should_run(None, NOW, idle_seconds=3600,
                      last_user_turn=old) is False


def test_should_run_accepts_iso_strings_and_naive():
    assert should_run("2026-10-19T03:00:00+00:00", NOW) is True
    assert should_run("2026-10-20T01:00:00+00:00", NOW) is False
    naive_now = datetime(2026, 10, 20, 3, 0)
    assert should_run(None, naive_now) is True
    assert should_run(None, "not a timestamp") is False


# ----------------------------------------------------------------- helpers

def test_read_last_run_missing(tmp_path):
    assert read_last_run(tmp_path / "nope") is None


def test_last_user_turn_at(store):
    assert last_user_turn_at(store) is None
    sid = store.create_session("test", "test")
    call(store, sid, "web_search")
    assert last_user_turn_at(store) is None  # tool calls are not turns
    eid = store.emit(sid, "user.message", {"text": "hello"},
                     actor="user", trust="user")
    expected = store.get_events(sid)[-1]["ts"]
    assert store.get_events(sid)[-1]["event_id"] == eid
    got = last_user_turn_at(store)
    assert got is not None
    assert got == datetime.fromisoformat(expected)
    assert last_user_turn_at(str(store.db_path)) == got  # path works too


def test_quiet_report_summary_line():
    r = ReviewReport(day="2026-10-20", diary_day="2026-10-19",
                     ran_at=NOW.isoformat())
    assert r.summary_line() == "Night review: nothing new."
    assert r.ok is True and r.failed_steps == []
    assert r.to_dict()["silent"] is True
