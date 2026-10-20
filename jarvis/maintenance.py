"""JARVIS v2 maintenance — keeping the soil healthy so the seed can grow.

Source: the "Jarvis Soil" growth studies (~/workspace/jarvis-soil/):
  - hardware-requirements.md §5  — 24/7 survival: weekly reboot, disk/RAM
    headroom, temperature/disk watchdogs.
  - software-api-data.md         — log rotation under the data dir, model /
    provider health probes, ASCII-path hygiene, 1-year retention posture.
  - testing-deployment-maintenance.md §2/§3 — degrade-don't-die, crash
    recovery, updater rollback ("two consecutive startup crashes -> revert"),
    pin-and-verify maintenance rhythm.
  - seed-viability.md §4 (PRR)   — reliability: single-instance lock,
    watchdog, crash capture, auto-recovery.

What lives here (all stdlib, all file-level — this module never reaches
into brain/memory/session internals):

  * run_health_checks()  — disk, RAM, Python window, DB integrity
    (PRAGMA integrity_check), backup freshness, log pressure, crash
    state, heartbeat/watchdog, uptime, GPU + Ollama probes.
  * create_backup() / list_backups() / restore_backup() — consistent
    snapshots of the whole data dir (SQLite backup API for live DBs),
    rotation, and restore that always takes a pre-restore safety
    snapshot first.
  * cleanup_data_dir()   — log + archive pruning honoring the owner's
    1-year session-archive retention rule; never touches DBs, config,
    secrets, or backups.
  * Crash tracking       — note_startup()/note_clean_shutdown() count
    consecutive unclean starts; auto_recover() restores the newest
    backup when a crash loop is suspected (the soil's rollback rule).
  * InstanceLock         — one live JARVIS per data dir, stale-aware.
  * write_heartbeat() / watchdog_status() — the watchdog's other half.
  * run_maintenance()    — the nightly rhythm in one call: health ->
    backup (when due) -> cleanup -> optional memory consolidation
    (dependency-injected; this module does not import jarvis.memory).

Design rules:
  * Nothing here raises at the caller for an *environment* problem —
    problems are reported as data (HealthItem / report dicts).
  * Nothing here prints, prompts, or touches the network except the
    loopback Ollama probe (1s timeout, warn-only semantics).
  * Time is injectable (`now=`) everywhere so tests are deterministic.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

# --------------------------------------------------------------------------- #
# Soil constants
# --------------------------------------------------------------------------- #

#: Owner's retention rule: session archives live for one year.
RETENTION_DAYS = 365

#: Backups kept by rotation (soil: "keep the old as fallback — disk is
#: cheap; a broken Tuesday is expensive").
DEFAULT_KEEP_BACKUPS = 7

#: A backup counts as "due" if the newest one is older than this.
BACKUP_DUE_AFTER = timedelta(hours=24)

#: Two consecutive unclean starts = crash loop (testing/maintenance §3.5:
#: "if the new version crashes on startup twice, revert automatically").
CRASH_LOOP_THRESHOLD = 2

#: Disk pressure thresholds for the health report.
DISK_FAIL_FREE_BYTES = 2 * 1024**3
DISK_WARN_FREE_BYTES = 10 * 1024**3

#: RAM guidance from the hardware soil tiers (16 GB recommended).
RAM_WARN_BYTES = 8 * 1024**3

#: Log pressure: total log bytes above this and cleanup is advised.
LOG_WARN_BYTES = 200 * 1024**2

#: Watchdog: heartbeat older than this means "probably dead".
HEARTBEAT_STALE_SECONDS = 300.0

#: 24/7 soil checklist item 5: a weekly reboot keeps software fresh.
UPTIME_REBOOT_ADVICE = timedelta(days=7)

BACKUP_DIRNAME = "backups"
BACKUP_PREFIX = "jarvis-backup-"
_STATE_FILE = "startup-state.json"
_HEARTBEAT_FILE = "heartbeat.json"
_LOCK_FILE = "instance.lock"

#: Runtime-state files that must never ride along in a backup — restoring
#: yesterday's heartbeat/lock/crash-counter would lie about today.
_RUNTIME_FILES = {_STATE_FILE, _HEARTBEAT_FILE, _LOCK_FILE}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(now: datetime) -> str:
    return now.strftime("%Y%m%d-%H%M%S")


# --------------------------------------------------------------------------- #
# Health checks
# --------------------------------------------------------------------------- #

@dataclass
class HealthItem:
    """One health result. status: "ok" | "warn" | "fail"."""

    name: str
    status: str
    detail: str

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status,
                "detail": self.detail}


@dataclass
class HealthReport:
    data_dir: str
    generated_at: str
    items: list[HealthItem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(i.status != "fail" for i in self.items)

    def status_of(self, name: str) -> Optional[str]:
        for i in self.items:
            if i.name == name:
                return i.status
        return None

    def to_dict(self) -> dict:
        return {"data_dir": self.data_dir,
                "generated_at": self.generated_at,
                "ok": self.ok,
                "items": [i.to_dict() for i in self.items]}


def _total_ram_bytes() -> Optional[int]:
    """Total physical RAM, stdlib only. None when unknowable."""
    try:
        if os.name == "nt":
            class _MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = _MemStatus()
            status.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
            return None
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            for line in meminfo.read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
        if hasattr(os, "sysconf"):
            return int(os.sysconf("SC_PHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
    except Exception:  # noqa: BLE001 — a probe must never crash the suite
        return None
    return None


def _uptime_seconds() -> Optional[float]:
    try:
        if os.name == "nt":
            return ctypes.windll.kernel32.GetTickCount64() / 1000.0
        up = Path("/proc/uptime")
        if up.exists():
            return float(up.read_text(encoding="utf-8").split()[0])
    except Exception:  # noqa: BLE001
        return None
    return None


def _gpu_probe() -> Optional[str]:
    try:
        exe = shutil.which("nvidia-smi")
        if not exe:
            return None
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=3)
        line = (out.stdout or "").strip().splitlines()
        return line[0].strip() if line else None
    except Exception:  # noqa: BLE001
        return None


def _ollama_reachable() -> bool:
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001 — unreachable is a normal state
        return False


def check_db_integrity(db_path: Path) -> HealthItem:
    """PRAGMA integrity_check on one database, opened read-only."""
    name = f"db_integrity:{db_path.name}"
    if not db_path.exists():
        return HealthItem(name, "ok", f"{db_path.name} not created yet.")
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True,
                               timeout=5.0)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
        verdict = (row[0] if row else "").strip().lower()
        if verdict == "ok":
            return HealthItem(name, "ok", f"{db_path.name} passed its "
                                          "integrity check.")
        return HealthItem(name, "fail", f"{db_path.name} failed its "
                                        f"integrity check: {verdict}")
    except sqlite3.Error as exc:
        return HealthItem(name, "fail", f"{db_path.name} could not be "
                                        f"checked ({exc}).")


def _check_disk(data_dir: Path) -> HealthItem:
    try:
        usage = shutil.disk_usage(data_dir)
        gb = usage.free / 1024**3
        if usage.free < DISK_FAIL_FREE_BYTES:
            return HealthItem("disk_space", "fail",
                              f"Only {gb:.1f} GB free — JARVIS is about "
                              "to run out of room.")
        if usage.free < DISK_WARN_FREE_BYTES:
            return HealthItem("disk_space", "warn",
                              f"{gb:.1f} GB free — below the 10 GB "
                              "comfort floor from the soil study.")
        return HealthItem("disk_space", "ok", f"{gb:.1f} GB free.")
    except OSError as exc:
        return HealthItem("disk_space", "warn",
                          f"Could not measure free space ({exc}).")


def _check_ram() -> HealthItem:
    total = _total_ram_bytes()
    if total is None:
        return HealthItem("memory_size", "ok",
                          "Could not measure memory size; skipping.")
    gb = total / 1024**3
    if total < RAM_WARN_BYTES:
        return HealthItem("memory_size", "warn",
                          f"{gb:.0f} GB of memory — the soil tiers call "
                          "this cloud-brain territory; the local brain "
                          "will be cramped.")
    return HealthItem("memory_size", "ok", f"{gb:.0f} GB of memory.")


def _check_python() -> HealthItem:
    vi = sys.version_info
    label = f"Python {vi.major}.{vi.minor}.{vi.micro}"
    if (vi.major, vi.minor) < (3, 11):
        return HealthItem("python_version", "fail",
                          f"{label} — JARVIS needs 3.11 or newer.")
    if (vi.major, vi.minor) > (3, 12):
        return HealthItem("python_version", "warn",
                          f"{label} — the soil study froze the runtime "
                          "at 3.11/3.12; newer versions are unproven "
                          "ground for the voice libraries.")
    return HealthItem("python_version", "ok", f"{label}.")


def _check_backup_freshness(data_dir: Path, now: datetime) -> HealthItem:
    backups = list_backups(data_dir)
    if not backups:
        return HealthItem("backup_freshness", "warn",
                          "No backup exists yet — the first safety "
                          "snapshot has not been taken.")
    newest = backups[0]
    age = now - newest.created_at
    if age > timedelta(days=7):
        return HealthItem("backup_freshness", "warn",
                          f"Newest backup is {age.days} days old.")
    return HealthItem("backup_freshness", "ok",
                      f"Newest backup is from "
                      f"{newest.created_at:%Y-%m-%d %H:%M} UTC.")


def _log_bytes(data_dir: Path) -> int:
    total = 0
    logs_dir = data_dir / "logs"
    if logs_dir.is_dir():
        for p in logs_dir.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    for p in data_dir.glob("*.log"):
        if p.is_file():
            total += p.stat().st_size
    return total


def _check_log_pressure(data_dir: Path) -> HealthItem:
    total = _log_bytes(data_dir)
    mb = total / 1024**2
    if total > LOG_WARN_BYTES:
        return HealthItem("log_pressure", "warn",
                          f"Logs occupy {mb:.0f} MB — a cleanup pass "
                          "is due (drainage keeps the soil healthy).")
    return HealthItem("log_pressure", "ok", f"Logs occupy {mb:.1f} MB.")


def _check_crash_state(data_dir: Path) -> HealthItem:
    count = consecutive_unclean_starts(data_dir)
    if count >= CRASH_LOOP_THRESHOLD:
        return HealthItem("crash_state", "warn",
                          f"{count} starts in a row ended without a "
                          "clean shutdown — a crash loop is suspected "
                          "and auto-recovery can restore the last "
                          "backup.")
    if count == 1:
        return HealthItem("crash_state", "warn",
                          "The previous run did not shut down cleanly.")
    return HealthItem("crash_state", "ok",
                      "Previous run shut down cleanly.")


def _check_uptime() -> HealthItem:
    secs = _uptime_seconds()
    if secs is None:
        return HealthItem("uptime", "ok", "Uptime unknown; skipping.")
    up = timedelta(seconds=secs)
    if up > UPTIME_REBOOT_ADVICE:
        return HealthItem("uptime", "warn",
                          f"This computer has been up {up.days} days — "
                          "the soil checklist suggests a weekly restart "
                          "to keep things fresh.")
    return HealthItem("uptime", "ok", f"Uptime {up.days} day(s).")


def _check_path_encoding(data_dir: Path) -> HealthItem:
    try:
        str(data_dir).encode("ascii")
        return HealthItem("path_encoding", "ok",
                          "Data path uses plain letters only.")
    except UnicodeEncodeError:
        return HealthItem("path_encoding", "warn",
                          "The data path contains special letters, "
                          "which can confuse some model libraries.")


def _check_gpu() -> HealthItem:
    gpu = _gpu_probe()
    if gpu:
        return HealthItem("gpu", "ok", f"Graphics card found: {gpu}.")
    return HealthItem("gpu", "ok",
                      "No NVIDIA graphics card detected — the local "
                      "brain runs on the processor, or the cloud brain "
                      "is used. Both are supported soil.")


def _check_ollama() -> HealthItem:
    if _ollama_reachable():
        return HealthItem("ollama", "ok", "Local brain (Ollama) is "
                                          "running.")
    return HealthItem("ollama", "warn",
                      "Local brain (Ollama) is not running — JARVIS "
                      "will use the cloud brain until it is opened.")


def run_health_checks(data_dir: Path | str, *,
                      now: Optional[datetime] = None,
                      probe_ollama: bool = True) -> HealthReport:
    """Run the whole health suite. Never raises for env problems."""
    data_dir = Path(data_dir)
    now = now or _utcnow()
    report = HealthReport(data_dir=str(data_dir),
                          generated_at=now.isoformat())
    checks: list[Callable[[], HealthItem]] = [
        lambda: _check_disk(data_dir),
        _check_ram,
        _check_python,
        lambda: _check_backup_freshness(data_dir, now),
        lambda: _check_log_pressure(data_dir),
        lambda: _check_crash_state(data_dir),
        lambda: watchdog_status(data_dir, now=now),
        _check_uptime,
        lambda: _check_path_encoding(data_dir),
        _check_gpu,
    ]
    if probe_ollama:
        checks.append(_check_ollama)
    if data_dir.is_dir():
        for db in sorted(data_dir.glob("*.db")):
            checks.append(lambda db=db: check_db_integrity(db))
    else:
        checks.append(lambda: HealthItem(
            "data_dir", "fail",
            "The data folder does not exist yet."))
    for fn in checks:
        try:
            report.items.append(fn())
        except Exception as exc:  # noqa: BLE001 — report, never crash
            report.items.append(HealthItem(
                "health_probe", "warn",
                f"A health probe hit an unexpected error "
                f"({type(exc).__name__})."))
    return report


# --------------------------------------------------------------------------- #
# Backups — snapshot, rotate, restore
# --------------------------------------------------------------------------- #

@dataclass
class BackupInfo:
    path: Path
    created_at: datetime
    size_bytes: int

    def to_dict(self) -> dict:
        return {"path": str(self.path),
                "created_at": self.created_at.isoformat(),
                "size_bytes": self.size_bytes}


def _backup_dir(data_dir: Path) -> Path:
    return data_dir / BACKUP_DIRNAME


_STAMP_RE = None  # compiled lazily below (keeps imports tidy)


def _parse_backup_stamp(path: Path) -> Optional[datetime]:
    """jarvis-backup-[label-]YYYYMMDD-HHMMSS[-N].zip -> datetime (UTC)."""
    global _STAMP_RE
    if _STAMP_RE is None:
        import re
        _STAMP_RE = re.compile(r"(\d{8})-(\d{6})")
    match = _STAMP_RE.search(path.stem)
    if not path.stem.startswith(BACKUP_PREFIX) or match is None:
        return None
    try:
        parsed = datetime.strptime(f"{match.group(1)}-{match.group(2)}",
                                   "%Y%m%d-%H%M%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def list_backups(data_dir: Path | str) -> list[BackupInfo]:
    """All backups, newest first."""
    bdir = _backup_dir(Path(data_dir))
    infos: list[BackupInfo] = []
    if bdir.is_dir():
        for p in bdir.glob(f"{BACKUP_PREFIX}*.zip"):
            stamp = _parse_backup_stamp(p)
            if stamp is None:
                continue
            infos.append(BackupInfo(path=p, created_at=stamp,
                                    size_bytes=p.stat().st_size))
    infos.sort(key=lambda b: b.created_at, reverse=True)
    return infos


def _snapshot_db(src: Path, staging: Path) -> None:
    """Consistent copy of a (possibly live, WAL-mode) SQLite database
    via the sqlite3 backup API — never a raw file copy of a hot DB."""
    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=10.0)
    try:
        dest = sqlite3.connect(str(staging))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()


def _iter_backup_files(data_dir: Path) -> Iterable[Path]:
    for p in sorted(data_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(data_dir)
        if rel.parts and rel.parts[0] == BACKUP_DIRNAME:
            continue  # never back up the backups
        if p.name in _RUNTIME_FILES or p.suffix == ".lock":
            continue  # runtime state lies about the past if restored
        if p.suffix in (".part", ".tmp"):
            continue  # half-finished downloads/temp — not soil, litter
        yield p


def create_backup(data_dir: Path | str, *,
                  keep: int = DEFAULT_KEEP_BACKUPS,
                  label: str = "",
                  now: Optional[datetime] = None) -> Path:
    """Snapshot the whole data dir into backups/ as one zip, then rotate.

    SQLite databases are copied through the backup API so a snapshot is
    consistent even while JARVIS is running. Returns the zip path.
    """
    data_dir = Path(data_dir)
    now = now or _utcnow()
    bdir = _backup_dir(data_dir)
    bdir.mkdir(parents=True, exist_ok=True)
    label_part = f"{label}-" if label else ""
    target = bdir / f"{BACKUP_PREFIX}{label_part}{_stamp(now)}.zip"
    counter = 1
    while target.exists():  # same-second collision: suffix, never clobber
        target = bdir / (f"{BACKUP_PREFIX}{label_part}{_stamp(now)}"
                         f"-{counter}.zip")
        counter += 1

    with tempfile.TemporaryDirectory() as tmp:
        staging_root = Path(tmp) / "snapshot"
        staging_root.mkdir()
        for src in _iter_backup_files(data_dir):
            rel = src.relative_to(data_dir)
            staged = staging_root / rel
            staged.parent.mkdir(parents=True, exist_ok=True)
            if src.suffix == ".db":
                try:
                    _snapshot_db(src, staged)
                    continue
                except sqlite3.Error:
                    pass  # fall back to a plain copy below
            shutil.copy2(src, staged)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            for staged in sorted(staging_root.rglob("*")):
                if staged.is_file():
                    zf.write(staged, staged.relative_to(staging_root))
    _rotate_backups(data_dir, keep)
    return target


def _rotate_backups(data_dir: Path, keep: int) -> list[Path]:
    """Delete all but the newest `keep` backups. Returns deleted paths."""
    deleted: list[Path] = []
    for info in list_backups(data_dir)[keep:]:
        try:
            info.path.unlink()
            deleted.append(info.path)
        except OSError:
            pass
    return deleted


def restore_backup(data_dir: Path | str,
                   backup: Optional[Path | str] = None, *,
                   now: Optional[datetime] = None) -> Path:
    """Restore a backup into the data dir.

    Always takes a pre-restore safety snapshot of the current state
    first (the soil rollback rule: an undo for the undo). Returns the
    safety snapshot's path. Raises FileNotFoundError if there is no
    backup to restore — that is a caller bug, not an env problem.
    """
    data_dir = Path(data_dir)
    now = now or _utcnow()
    if backup is None:
        infos = list_backups(data_dir)
        if not infos:
            raise FileNotFoundError("no backups exist to restore")
        backup_path = infos[0].path
    else:
        backup_path = Path(backup)
        if not backup_path.exists():
            raise FileNotFoundError(f"backup not found: {backup_path}")

    # keep high enough that rotation cannot delete the very backup we
    # are about to restore (it may sit beyond the normal keep window).
    keep_all = len(list_backups(data_dir)) + 1
    safety = create_backup(data_dir, label="pre-restore", now=now,
                           keep=max(DEFAULT_KEEP_BACKUPS, keep_all))
    data_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(backup_path) as zf:
        for member in zf.infolist():
            dest = (data_dir / member.filename).resolve()
            if dest != data_dir.resolve() and \
                    data_dir.resolve() not in dest.parents:
                raise ValueError(f"backup entry escapes the data dir: "
                                 f"{member.filename}")
            zf.extract(member, data_dir)
    return safety


# --------------------------------------------------------------------------- #
# Cleanup — drainage: logs + archives under the 1-year retention rule
# --------------------------------------------------------------------------- #

@dataclass
class CleanupReport:
    files_removed: int = 0
    bytes_freed: int = 0
    removed: list[str] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> dict:
        return {"files_removed": self.files_removed,
                "bytes_freed": self.bytes_freed,
                "removed": list(self.removed),
                "dry_run": self.dry_run}


def _older_than(path: Path, cutoff: datetime) -> bool:
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime,
                                       tz=timezone.utc)
    except OSError:
        return False
    return mtime < cutoff


def cleanup_data_dir(data_dir: Path | str, *,
                     retention_days: int = RETENTION_DAYS,
                     now: Optional[datetime] = None,
                     dry_run: bool = False) -> CleanupReport:
    """Prune what the retention rule says may go:

    * log files (logs/** and *.log) older than `retention_days`
    * session archives (archive/**) older than `retention_days`
      — the owner's 1-year rule
    * stale download parts (*.part under models/) older than 7 days
    * leftover write-probe files, any age

    Databases, config, secrets and backups are NEVER touched here.
    """
    data_dir = Path(data_dir)
    now = now or _utcnow()
    cutoff = now - timedelta(days=retention_days)
    part_cutoff = now - timedelta(days=7)
    report = CleanupReport(dry_run=dry_run)

    def consider(path: Path, limit: datetime) -> None:
        if not path.is_file() or not _older_than(path, limit):
            return
        try:
            size = path.stat().st_size
        except OSError:
            return
        if not dry_run:
            try:
                path.unlink()
            except OSError:
                return
        report.files_removed += 1
        report.bytes_freed += size
        report.removed.append(str(path.relative_to(data_dir)))

    logs_dir = data_dir / "logs"
    if logs_dir.is_dir():
        for p in logs_dir.rglob("*"):
            consider(p, cutoff)
    for p in data_dir.glob("*.log"):
        consider(p, cutoff)

    archive_dir = data_dir / "archive"
    if archive_dir.is_dir():
        for p in archive_dir.rglob("*"):
            consider(p, cutoff)

    models_dir = data_dir / "models"
    if models_dir.is_dir():
        for p in models_dir.rglob("*.part"):
            consider(p, part_cutoff)

    probe = data_dir / ".jarvis_write_probe"
    if probe.exists():
        if not dry_run:
            try:
                probe.unlink()
            except OSError:
                pass
        report.files_removed += 1
        report.removed.append(probe.name)
    return report


# --------------------------------------------------------------------------- #
# Crash tracking + auto-recovery (the updater-rollback rule, data-side)
# --------------------------------------------------------------------------- #

def _state_path(data_dir: Path) -> Path:
    return Path(data_dir) / _STATE_FILE


def _read_state(data_dir: Path) -> dict:
    try:
        return json.loads(_state_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(data_dir: Path, state: dict) -> None:
    path = _state_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def note_startup(data_dir: Path | str, *,
                 now: Optional[datetime] = None) -> int:
    """Record a start. Returns the consecutive-unclean-start count:
    a start that follows a run which never marked a clean shutdown
    raises the count; a counted crash loop is >= CRASH_LOOP_THRESHOLD.
    """
    data_dir = Path(data_dir)
    now = now or _utcnow()
    state = _read_state(data_dir)
    count = int(state.get("consecutive_unclean", 0))
    if state.get("started_once") and not state.get("clean_shutdown", True):
        count += 1
    state.update({
        "started_once": True,
        "clean_shutdown": False,
        "consecutive_unclean": count,
        "last_start": now.isoformat(),
    })
    _write_state(data_dir, state)
    return count


def note_clean_shutdown(data_dir: Path | str, *,
                        now: Optional[datetime] = None) -> None:
    data_dir = Path(data_dir)
    now = now or _utcnow()
    state = _read_state(data_dir)
    state.update({"clean_shutdown": True, "consecutive_unclean": 0,
                  "last_clean_shutdown": now.isoformat()})
    _write_state(data_dir, state)


def consecutive_unclean_starts(data_dir: Path | str) -> int:
    state = _read_state(Path(data_dir))
    return int(state.get("consecutive_unclean", 0))


def crash_loop_suspected(data_dir: Path | str,
                         threshold: int = CRASH_LOOP_THRESHOLD) -> bool:
    return consecutive_unclean_starts(data_dir) >= threshold


def auto_recover(data_dir: Path | str, *,
                 threshold: int = CRASH_LOOP_THRESHOLD,
                 now: Optional[datetime] = None) -> dict:
    """If a crash loop is suspected, restore the newest backup and
    reset the counter. Never raises — recovery that crashes helps no
    one. Returns a plain report dict."""
    data_dir = Path(data_dir)
    now = now or _utcnow()
    count = consecutive_unclean_starts(data_dir)
    if count < threshold:
        return {"recovered": False, "reason": "no crash loop suspected",
                "consecutive_unclean": count}
    infos = list_backups(data_dir)
    if not infos:
        return {"recovered": False,
                "reason": "crash loop suspected but no backup exists",
                "consecutive_unclean": count}
    try:
        safety = restore_backup(data_dir, infos[0].path, now=now)
    except Exception as exc:  # noqa: BLE001 — report, never crash
        return {"recovered": False,
                "reason": f"restore failed ({type(exc).__name__})",
                "consecutive_unclean": count}
    note_clean_shutdown(data_dir, now=now)
    return {"recovered": True,
            "restored_from": str(infos[0].path),
            "safety_snapshot": str(safety),
            "consecutive_unclean": count}


# --------------------------------------------------------------------------- #
# Single-instance lock (PRR reliability) — stale-aware, file-based
# --------------------------------------------------------------------------- #

class AlreadyRunningError(RuntimeError):
    """Another live JARVIS already owns this data dir."""


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    except OSError:
        return False
    return True


class InstanceLock:
    """Context manager: one live JARVIS per data dir.

    The lock file carries {pid, ts}. A lock is stale when its pid is
    dead OR its heartbeat is older than `stale_after_s` — a crashed
    JARVIS can never lock the owner out of his own assistant.
    """

    def __init__(self, data_dir: Path | str, *,
                 stale_after_s: float = 30.0):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / _LOCK_FILE
        self.stale_after_s = stale_after_s
        self._owned = False

    def _existing(self) -> Optional[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def is_stale(self, *, now: Optional[datetime] = None) -> bool:
        info = self._existing()
        if info is None:
            # No file, or an unreadable one: no live owner can be
            # proven, so the lock must not block a fresh start.
            return True
        now = now or _utcnow()
        pid = int(info.get("pid", 0))
        try:
            ts = datetime.fromisoformat(info.get("ts", ""))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            fresh = (now - ts).total_seconds() <= self.stale_after_s
        except ValueError:
            fresh = False
        return not (_pid_alive(pid) and fresh)

    def acquire(self, *, now: Optional[datetime] = None) -> "InstanceLock":
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and not self.is_stale(now=now):
            info = self._existing() or {}
            raise AlreadyRunningError(
                f"another JARVIS (pid {info.get('pid')}) already owns "
                f"{self.data_dir}")
        self._write(now=now)
        self._owned = True
        return self

    def _write(self, *, now: Optional[datetime] = None) -> None:
        now = now or _utcnow()
        payload = {"pid": os.getpid(), "ts": now.isoformat()}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self.path)

    def refresh(self, *, now: Optional[datetime] = None) -> None:
        if self._owned:
            self._write(now=now)

    def release(self) -> None:
        if self._owned:
            try:
                self.path.unlink()
            except OSError:
                pass
            self._owned = False

    def __enter__(self) -> "InstanceLock":
        return self.acquire()

    def __exit__(self, *exc) -> bool:
        self.release()
        return False


def is_instance_running(data_dir: Path | str, *,
                        stale_after_s: float = 30.0,
                        now: Optional[datetime] = None) -> bool:
    lock = InstanceLock(data_dir, stale_after_s=stale_after_s)
    if not lock.path.exists():
        return False
    return not lock.is_stale(now=now)


# --------------------------------------------------------------------------- #
# Heartbeat / watchdog
# --------------------------------------------------------------------------- #

def write_heartbeat(data_dir: Path | str, *,
                    now: Optional[datetime] = None,
                    status: str = "alive") -> None:
    data_dir = Path(data_dir)
    now = now or _utcnow()
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = {"ts": now.isoformat(), "pid": os.getpid(),
               "status": status}
    path = data_dir / _HEARTBEAT_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)


def watchdog_status(data_dir: Path | str, *,
                    max_age_s: float = HEARTBEAT_STALE_SECONDS,
                    now: Optional[datetime] = None) -> HealthItem:
    data_dir = Path(data_dir)
    now = now or _utcnow()
    path = data_dir / _HEARTBEAT_FILE
    if not path.exists():
        return HealthItem("watchdog", "ok",
                          "No heartbeat recorded — JARVIS is not "
                          "running right now.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(payload["ts"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except (OSError, ValueError, KeyError):
        return HealthItem("watchdog", "warn",
                          "The heartbeat file is unreadable.")
    age = (now - ts).total_seconds()
    if age <= max_age_s:
        return HealthItem("watchdog", "ok",
                          f"Heartbeat {age:.0f}s old — JARVIS is alive.")
    return HealthItem("watchdog", "warn",
                      f"Last heartbeat was {age / 60:.0f} minutes ago — "
                      "the process may have died without a clean "
                      "shutdown.")


# --------------------------------------------------------------------------- #
# The nightly rhythm — one call that does the soil-keeping
# --------------------------------------------------------------------------- #

@dataclass
class MaintenanceReport:
    data_dir: str
    generated_at: str
    health: dict
    backup: Optional[str] = None
    backup_skipped_reason: str = ""
    cleanup: dict = field(default_factory=dict)
    recovery: dict = field(default_factory=dict)
    consolidate: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"data_dir": self.data_dir,
                "generated_at": self.generated_at,
                "health": self.health,
                "backup": self.backup,
                "backup_skipped_reason": self.backup_skipped_reason,
                "cleanup": self.cleanup,
                "recovery": self.recovery,
                "consolidate": self.consolidate}


def _backup_due(data_dir: Path, now: datetime) -> bool:
    infos = list_backups(data_dir)
    if not infos:
        return True
    return (now - infos[0].created_at) > BACKUP_DUE_AFTER


def run_maintenance(data_dir: Path | str, *,
                    memory_store: Any = None,
                    now: Optional[datetime] = None,
                    force_backup: bool = False) -> MaintenanceReport:
    """The maintenance rhythm (soil §3.4 cadence, automated nightly):

    1. crash-loop check -> auto-recover if suspected
    2. health suite
    3. backup when due (or forced)
    4. retention cleanup
    5. memory consolidation, IF a store with consolidate() is injected
       (dependency injection keeps this module out of memory.py's
       territory — growth-learning's nightly purge rides along here)

    Every step is isolated: one failing step is reported, never fatal.
    """
    data_dir = Path(data_dir)
    now = now or _utcnow()
    report = MaintenanceReport(data_dir=str(data_dir),
                               generated_at=now.isoformat(),
                               health={})

    try:
        report.recovery = auto_recover(data_dir, now=now)
    except Exception as exc:  # noqa: BLE001
        report.recovery = {"recovered": False,
                           "reason": f"recovery probe failed "
                                     f"({type(exc).__name__})"}

    try:
        report.health = run_health_checks(data_dir, now=now).to_dict()
    except Exception as exc:  # noqa: BLE001
        report.health = {"ok": False,
                         "error": f"health suite failed "
                                  f"({type(exc).__name__})"}

    try:
        if force_backup or _backup_due(data_dir, now):
            report.backup = str(create_backup(data_dir, now=now))
        else:
            report.backup_skipped_reason = "newest backup is fresh"
    except Exception as exc:  # noqa: BLE001
        report.backup_skipped_reason = f"backup failed " \
                                       f"({type(exc).__name__})"

    try:
        report.cleanup = cleanup_data_dir(data_dir, now=now).to_dict()
    except Exception as exc:  # noqa: BLE001
        report.cleanup = {"error": f"cleanup failed "
                                   f"({type(exc).__name__})"}

    consolidate = getattr(memory_store, "consolidate", None)
    if callable(consolidate):
        try:
            result = consolidate()
            report.consolidate = {"ran": True, "result": result}
        except Exception as exc:  # noqa: BLE001
            report.consolidate = {"ran": True,
                                  "error": type(exc).__name__}
    else:
        report.consolidate = {"ran": False,
                              "reason": "no memory store injected"}
    return report
