"""Tests for jarvis.maintenance — the soil-keeping layer.

Covers the Jarvis Soil studies' code-implementable demands:
health suite (disk/RAM/Python/DB integrity via PRAGMA), data-dir
backup with rotation + restore, log/archive cleanup under the owner's
1-year retention rule, crash tracking + auto-recovery (the soil's
two-crash rollback rule), the stale-aware instance lock, and the
heartbeat watchdog.

Conventions: stdlib + pytest only; all time is injected (`now=`);
real SQLite databases in tmp dirs; no mocks of the units under test.
"""

from __future__ import annotations

import json
import os
import sqlite3
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jarvis import maintenance as m

BASE = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)


def _make_db(path: Path, rows: int = 1) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    for i in range(rows):
        conn.execute("INSERT INTO t (v) VALUES (?)", (f"row-{i}",))
    conn.commit()
    conn.close()


def _aged(path: Path, days: float) -> None:
    ts = (BASE - timedelta(days=days)).timestamp()
    os.utime(path, (ts, ts))


def _populated_data_dir(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    (data / "config.yaml").write_text("profile: owais\n", encoding="utf-8")
    _make_db(data / "sessions.db", rows=2)
    _make_db(data / "memory.db")
    sub = data / "notes"
    sub.mkdir()
    (sub / "note.txt").write_text("remember this", encoding="utf-8")
    (data / "heartbeat.json").write_text("{}", encoding="utf-8")
    (data / "instance.lock").write_text("{}", encoding="utf-8")
    (data / "models").mkdir()
    (data / "models" / "half.bin.part").write_bytes(b"partial")
    return data


# --------------------------------------------------------------------------- #
# Health suite
# --------------------------------------------------------------------------- #

def test_db_integrity_good_db(tmp_path):
    db = tmp_path / "sessions.db"
    _make_db(db)
    item = m.check_db_integrity(db)
    assert item.status == "ok"


def test_db_integrity_corrupt_db_fails(tmp_path):
    db = tmp_path / "memory.db"
    db.write_bytes(b"this is not a sqlite database at all" * 10)
    item = m.check_db_integrity(db)
    assert item.status == "fail"


def test_db_integrity_missing_db_is_ok(tmp_path):
    item = m.check_db_integrity(tmp_path / "not-yet.db")
    assert item.status == "ok"
    assert "not created yet" in item.detail


def test_health_report_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "DISK_FAIL_FREE_BYTES", 0)
    monkeypatch.setattr(m, "DISK_WARN_FREE_BYTES", 0)
    data = _populated_data_dir(tmp_path)
    report = m.run_health_checks(data, now=BASE, probe_ollama=False)
    names = [i.name for i in report.items]
    for expected in ("disk_space", "memory_size", "python_version",
                     "backup_freshness", "log_pressure", "crash_state",
                     "watchdog", "uptime", "path_encoding", "gpu"):
        assert expected in names
    assert "db_integrity:sessions.db" in names
    assert "db_integrity:memory.db" in names
    assert report.ok is True  # populated dir is healthy (warns allowed)
    d = report.to_dict()
    assert d["ok"] is True and d["data_dir"] == str(data)


def test_health_report_flags_corrupt_db(tmp_path):
    (tmp_path / "bad.db").write_bytes(b"garbage" * 50)
    report = m.run_health_checks(tmp_path, now=BASE, probe_ollama=False)
    assert report.ok is False
    assert report.status_of("db_integrity:bad.db") == "fail"


def test_health_missing_data_dir_is_fail_not_crash(tmp_path):
    report = m.run_health_checks(tmp_path / "ghost", now=BASE,
                                 probe_ollama=False)
    assert report.status_of("data_dir") == "fail"


def test_health_ollama_probe_warns_when_down(monkeypatch):
    monkeypatch.setattr(m, "_ollama_reachable", lambda: False)
    item = m._check_ollama()
    assert item.status == "warn"
    monkeypatch.setattr(m, "_ollama_reachable", lambda: True)
    assert m._check_ollama().status == "ok"


def test_ram_and_uptime_probes_never_crash():
    ram = m._total_ram_bytes()
    assert ram is None or ram > 0
    up = m._uptime_seconds()
    assert up is None or up >= 0


# --------------------------------------------------------------------------- #
# Backup / rotation / restore
# --------------------------------------------------------------------------- #

def test_backup_contains_data_but_not_runtime_litter(tmp_path):
    data = _populated_data_dir(tmp_path)
    out = m.create_backup(data, now=BASE)
    assert out.exists() and out.parent == data / "backups"
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert "config.yaml" in names
    assert "sessions.db" in names and "memory.db" in names
    assert "notes/note.txt" in names
    # Runtime state must not ride along (it would lie if restored).
    assert "heartbeat.json" not in names
    assert "instance.lock" not in names
    assert not any(n.endswith(".part") for n in names)
    assert not any(n.startswith("backups/") for n in names)


def test_backup_db_snapshot_is_a_valid_database(tmp_path):
    data = _populated_data_dir(tmp_path)
    out = m.create_backup(data, now=BASE)
    extract = tmp_path / "extract"
    with zipfile.ZipFile(out) as zf:
        zf.extract("sessions.db", extract)
    conn = sqlite3.connect(str(extract / "sessions.db"))
    rows = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    conn.close()
    assert rows == 2


def test_backup_rotation_keeps_newest(tmp_path):
    data = _populated_data_dir(tmp_path)
    for i in range(4):
        m.create_backup(data, keep=2, now=BASE + timedelta(hours=i))
    backups = m.list_backups(data)
    assert len(backups) == 2
    newest = backups[0]
    assert newest.created_at == BASE + timedelta(hours=3)


def test_list_backups_newest_first(tmp_path):
    data = _populated_data_dir(tmp_path)
    m.create_backup(data, now=BASE)
    m.create_backup(data, now=BASE + timedelta(hours=5))
    stamps = [b.created_at for b in m.list_backups(data)]
    assert stamps == sorted(stamps, reverse=True)


def test_restore_roundtrip_and_safety_snapshot(tmp_path):
    data = _populated_data_dir(tmp_path)
    original_config = (data / "config.yaml").read_text(encoding="utf-8")
    m.create_backup(data, now=BASE)
    (data / "config.yaml").write_text("profile: corrupted\n",
                                       encoding="utf-8")
    (data / "notes" / "note.txt").unlink()
    safety = m.restore_backup(data, now=BASE + timedelta(hours=1))
    assert safety.exists()  # an undo for the undo
    assert (data / "config.yaml").read_text(encoding="utf-8") == original_config
    assert (data / "notes" / "note.txt").exists()


def test_restore_without_backups_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        m.restore_backup(tmp_path)


def test_restore_never_deletes_the_backup_being_restored(tmp_path):
    data = _populated_data_dir(tmp_path)
    target = m.create_backup(data, now=BASE)
    # Surround the target with many newer backups (kept via a wide
    # window), then restore the old one explicitly — rotation during
    # the restore's own safety snapshot must not eat it.
    for i in range(1, 10):
        m.create_backup(data, keep=100, now=BASE + timedelta(hours=i))
    (data / "config.yaml").write_text("changed\n", encoding="utf-8")
    m.restore_backup(data, target, now=BASE + timedelta(hours=10))
    assert target.exists()
    assert "owais" in (data / "config.yaml").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Cleanup — the 1-year retention rule (drainage)
# --------------------------------------------------------------------------- #

def _cleanup_fixture(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    (data / "logs").mkdir(parents=True)
    (data / "archive").mkdir()
    (data / "models").mkdir()
    old_log = data / "logs" / "old.log"
    old_log.write_text("old", encoding="utf-8")
    _aged(old_log, 400)
    new_log = data / "logs" / "new.log"
    new_log.write_text("new", encoding="utf-8")
    _aged(new_log, 10)
    old_arc = data / "archive" / "session-2025.txt"
    old_arc.write_text("ancient session", encoding="utf-8")
    _aged(old_arc, 400)
    new_arc = data / "archive" / "session-2026.txt"
    new_arc.write_text("recent session", encoding="utf-8")
    _aged(new_arc, 10)
    db = data / "sessions.db"
    _make_db(db)
    _aged(db, 400)  # ancient but a database — never pruned by cleanup
    stale_part = data / "models" / "gone.bin.part"
    stale_part.write_bytes(b"x")
    _aged(stale_part, 10)
    (data / "config.yaml").write_text("profile: owais\n", encoding="utf-8")
    return data


def test_cleanup_honors_retention_rule(tmp_path):
    data = _cleanup_fixture(tmp_path)
    report = m.cleanup_data_dir(data, now=BASE)
    assert not (data / "logs" / "old.log").exists()
    assert (data / "logs" / "new.log").exists()
    assert not (data / "archive" / "session-2025.txt").exists()
    assert (data / "archive" / "session-2026.txt").exists()
    assert (data / "sessions.db").exists()       # DBs are never touched
    assert (data / "config.yaml").exists()
    assert not (data / "models" / "gone.bin.part").exists()
    assert report.files_removed == 3
    assert report.bytes_freed > 0


def test_cleanup_dry_run_reports_but_deletes_nothing(tmp_path):
    data = _cleanup_fixture(tmp_path)
    report = m.cleanup_data_dir(data, now=BASE, dry_run=True)
    assert report.dry_run is True
    assert report.files_removed == 3
    assert (data / "logs" / "old.log").exists()
    assert (data / "archive" / "session-2025.txt").exists()


def test_cleanup_custom_retention(tmp_path):
    data = _cleanup_fixture(tmp_path)
    m.cleanup_data_dir(data, now=BASE, retention_days=5)
    assert not (data / "logs" / "new.log").exists()  # 10 days > 5


# --------------------------------------------------------------------------- #
# Crash tracking + auto-recovery
# --------------------------------------------------------------------------- #

def test_crash_counter_lifecycle(tmp_path):
    assert m.consecutive_unclean_starts(tmp_path) == 0
    assert m.note_startup(tmp_path, now=BASE) == 0          # first start
    assert m.note_startup(tmp_path, now=BASE) == 1          # crashed once
    assert m.note_startup(tmp_path, now=BASE) == 2          # crashed twice
    assert m.crash_loop_suspected(tmp_path) is True
    m.note_clean_shutdown(tmp_path, now=BASE)
    assert m.consecutive_unclean_starts(tmp_path) == 0
    assert m.crash_loop_suspected(tmp_path) is False
    assert m.note_startup(tmp_path, now=BASE) == 0          # clean restart


def test_auto_recover_below_threshold_is_noop(tmp_path):
    m.note_startup(tmp_path, now=BASE)
    out = m.auto_recover(tmp_path, now=BASE)
    assert out["recovered"] is False
    assert "no crash loop" in out["reason"]


def test_auto_recover_restores_backup_and_resets(tmp_path):
    data = _populated_data_dir(tmp_path)
    m.create_backup(data, now=BASE)
    (data / "config.yaml").write_text("wrecked\n", encoding="utf-8")
    for _ in range(3):
        m.note_startup(data, now=BASE)
    assert m.crash_loop_suspected(data) is True
    out = m.auto_recover(data, now=BASE + timedelta(hours=1))
    assert out["recovered"] is True
    assert "owais" in (data / "config.yaml").read_text(encoding="utf-8")
    assert m.consecutive_unclean_starts(data) == 0


def test_auto_recover_without_backup_reports_honestly(tmp_path):
    for _ in range(3):
        m.note_startup(tmp_path, now=BASE)
    out = m.auto_recover(tmp_path, now=BASE)
    assert out["recovered"] is False
    assert "no backup" in out["reason"]


# --------------------------------------------------------------------------- #
# Instance lock + heartbeat watchdog
# --------------------------------------------------------------------------- #

def test_instance_lock_blocks_second_owner(tmp_path):
    with m.InstanceLock(tmp_path):
        assert m.is_instance_running(tmp_path) is True
        with pytest.raises(m.AlreadyRunningError):
            m.InstanceLock(tmp_path).acquire()
    assert not (tmp_path / "instance.lock").exists()
    assert m.is_instance_running(tmp_path) is False


def test_instance_lock_stale_dead_pid_takeover(tmp_path):
    stale = {"pid": 999999,
             "ts": (BASE - timedelta(hours=2)).isoformat()}
    (tmp_path / "instance.lock").write_text(json.dumps(stale),
                                            encoding="utf-8")
    with m.InstanceLock(tmp_path) as lock:
        assert lock.path.exists()


def test_instance_lock_stale_by_age_takeover(tmp_path):
    real_now = datetime.now(timezone.utc)
    old = {"pid": os.getpid(),
           "ts": (real_now - timedelta(hours=2)).isoformat()}
    (tmp_path / "instance.lock").write_text(json.dumps(old),
                                            encoding="utf-8")
    lock = m.InstanceLock(tmp_path, stale_after_s=30.0)
    assert lock.is_stale(now=real_now) is True
    with lock:
        pass


def test_watchdog_states(tmp_path):
    item = m.watchdog_status(tmp_path, now=BASE)
    assert item.status == "ok" and "not running" in item.detail
    m.write_heartbeat(tmp_path, now=BASE)
    item = m.watchdog_status(tmp_path, now=BASE + timedelta(seconds=30))
    assert item.status == "ok"
    item = m.watchdog_status(tmp_path, now=BASE + timedelta(hours=2))
    assert item.status == "warn"


# --------------------------------------------------------------------------- #
# The nightly rhythm — run_maintenance
# --------------------------------------------------------------------------- #

class _FakeStore:
    def __init__(self, result=None, boom=False):
        self._result = result if result is not None else {"expired": 3}
        self._boom = boom
        self.calls = 0

    def consolidate(self):
        self.calls += 1
        if self._boom:
            raise RuntimeError("consolidation exploded")
        return self._result


def test_run_maintenance_full_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "DISK_FAIL_FREE_BYTES", 0)
    monkeypatch.setattr(m, "DISK_WARN_FREE_BYTES", 0)
    data = _populated_data_dir(tmp_path)
    store = _FakeStore()
    report = m.run_maintenance(data, memory_store=store, now=BASE,
                               force_backup=True)
    assert report.health["ok"] is True
    assert report.backup is not None and Path(report.backup).exists()
    assert isinstance(report.cleanup, dict)
    assert report.consolidate["ran"] is True
    assert report.consolidate["result"] == {"expired": 3}
    assert store.calls == 1
    d = report.to_dict()
    assert d["data_dir"] == str(data)


def test_run_maintenance_survives_failing_consolidate(tmp_path):
    data = _populated_data_dir(tmp_path)
    report = m.run_maintenance(data, memory_store=_FakeStore(boom=True),
                               now=BASE, force_backup=True)
    assert report.consolidate["ran"] is True
    assert "error" in report.consolidate
    assert report.backup is not None  # other steps still ran


def test_run_maintenance_without_store_skips_consolidate(tmp_path):
    data = _populated_data_dir(tmp_path)
    report = m.run_maintenance(data, now=BASE, force_backup=True)
    assert report.consolidate["ran"] is False


def test_run_maintenance_backup_only_when_due(tmp_path):
    data = _populated_data_dir(tmp_path)
    m.create_backup(data, now=BASE)
    report = m.run_maintenance(data, now=BASE + timedelta(hours=2))
    assert report.backup is None
    assert "fresh" in report.backup_skipped_reason
    report = m.run_maintenance(data, now=BASE + timedelta(days=2))
    assert report.backup is not None  # 24h due-window passed
