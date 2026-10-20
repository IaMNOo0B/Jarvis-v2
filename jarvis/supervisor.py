"""JARVIS v2 — the supervisor: JARVIS's self-healing engine.

Patterns (Team 19 mega-scan, code-read; licenses noted in the scan):
  * Supervisor/supervisord (BSD-family) — the explicit state machine
    STOPPED/STARTING/RUNNING/BACKOFF/FATAL and the rule that the retry
    counter resets only after demonstrated uptime.
  * pm2 (AGPL — ideas only) — exponential backoff reset by uptime, and
    the scar-tissue rule: a dying process must never overwrite a good
    checkpoint with an empty one.
  * OTP restart intensity + Circus flapping + systemd StartLimitBurst —
    too many restarts inside a window is a different disease than one
    crash: escalate to a layer with more context (ultimately the
    owner), never loop faster.
  * cdog (MIT) — the verified-restart ritual: snapshot BEFORE action,
    restart, post-test with a real probe, automatic rollback on
    failure, a daily rollback budget, then escalate and STOP.
  * gosuv / ochinchina fast-death heuristics — a run that dies almost
    immediately is misconfigured, not unlucky, so it counts double.

This module is the ENGINE only. Every collaborator is injected —
spawn / probe / snapshot / restore / escalate / clock — so the state
machine is fully testable with fakes and never spawns a real process
by itself. The Windows-service outer layer (WinSW/SCM pattern) and
the launcher integration are later rounds; production snapshot /
restore wiring to jarvis.maintenance lives in the adapters at the
bottom of this file (reuse, never duplicate).

State persists to ``<data_dir>/supervisor_state.json`` (atomic
tmp + os.replace, same discipline as maintenance). A corrupt state
file loads as safe defaults and NEVER locks the owner out: FATAL
blocks automatic restarts only — a manual ``start()`` always works.

Python 3.11+, stdlib only. No LLM anywhere near this file.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

STATE_FILENAME = "supervisor_state.json"
_STATE_VERSION = 1

# --- policy constants (Team 19 numbers; every one constructor-tunable) --- #
BACKOFF_BASE_S = 1.0          # first retry waits base * 2**0
BACKOFF_CAP_S = 60.0          # delays never exceed this
BACKOFF_FACTOR = 2.0
UPTIME_RESET_S = 60.0         # demonstrated uptime that refills the budget
FAST_DEATH_S = 5.0            # a run shorter than this counts double
FLAP_MAX_RESTARTS = 5         # restarts inside the window -> FATAL
FLAP_WINDOW_S = 600.0         # 10 minutes
MAX_ROLLBACKS_PER_DAY = 50    # cdog's guard, same number


class SupState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    BACKOFF = "backoff"
    FATAL = "fatal"


class ScarTissueRefusal(RuntimeError):
    """A new snapshot was empty while a good one already exists.

    pm2's scar tissue: the snapshot writer refuses, loudly, rather
    than letting a sick moment erase the last known-good state.
    """


@dataclass
class RestartResult:
    """Outcome of one verified_restart() ritual."""
    ok: bool                    # the (possibly restored) run passed its probe
    verified: bool              # the NEW run itself passed (no rollback needed)
    rolled_back: bool
    snapshot_id: Optional[str]
    state: SupState
    reason: str
    rollbacks_today: int

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "verified": self.verified,
            "rolled_back": self.rolled_back,
            "snapshot_id": self.snapshot_id,
            "state": self.state.value,
            "reason": self.reason,
            "rollbacks_today": self.rollbacks_today,
        }


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class Supervisor:
    """A tiny deterministic supervisor for ONE child (the JARVIS app).

    Collaborators (all injected):
      spawn() -> handle            start the child; handle is opaque,
                                   except an optional callable
                                   ``handle.stop()`` used on replace.
      probe(handle) -> bool        proof-of-work health check. In
                                   production: one real brain turn +
                                   one tool call (cdog's post-test).
      snapshot() -> snapshot_id    take a data-dir snapshot.
      restore(snapshot_id)         restore a snapshot.
      escalate(reason: str)        tell the owner, in plain words.
      clock() -> float             seconds (monotonic in production).
    Optional:
      snapshot_probe(id) -> int    a size for a snapshot (entry count,
                                   bytes...); powers the scar-tissue
                                   guard. Without it the guard is off.
      today() -> "YYYY-MM-DD"      day key for the rollback budget.
    """

    def __init__(self,
                 spawn: Callable[[], object],
                 probe: Callable[[object], bool],
                 snapshot: Callable[[], str],
                 restore: Callable[[str], None],
                 escalate: Callable[[str], None],
                 clock: Callable[[], float] = time.monotonic,
                 *,
                 data_dir: Path | str | None = None,
                 snapshot_probe: Optional[Callable[[str], int]] = None,
                 today: Callable[[], str] = _utc_today,
                 backoff_base_s: float = BACKOFF_BASE_S,
                 backoff_cap_s: float = BACKOFF_CAP_S,
                 backoff_factor: float = BACKOFF_FACTOR,
                 uptime_reset_s: float = UPTIME_RESET_S,
                 fast_death_s: float = FAST_DEATH_S,
                 flap_max_restarts: int = FLAP_MAX_RESTARTS,
                 flap_window_s: float = FLAP_WINDOW_S,
                 max_rollbacks_per_day: int = MAX_ROLLBACKS_PER_DAY) -> None:
        self._spawn = spawn
        self._probe = probe
        self._snapshot = snapshot
        self._restore = restore
        self._escalate = escalate
        self._clock = clock
        self._snapshot_probe = snapshot_probe
        self._today = today
        self._data_dir = Path(data_dir) if data_dir is not None else None

        self.backoff_base_s = float(backoff_base_s)
        self.backoff_cap_s = float(backoff_cap_s)
        self.backoff_factor = float(backoff_factor)
        self.uptime_reset_s = float(uptime_reset_s)
        self.fast_death_s = float(fast_death_s)
        self.flap_max_restarts = int(flap_max_restarts)
        self.flap_window_s = float(flap_window_s)
        self.max_rollbacks_per_day = int(max_rollbacks_per_day)

        # live (never persisted) runtime fields
        self._handle: object = None
        self._started_at: Optional[float] = None
        self._healthy_since: Optional[float] = None
        self._next_restart_at: Optional[float] = None

        # persisted fields
        self.state: SupState = SupState.STOPPED
        self.backoff_level: int = 0
        self._restart_times: list[float] = []
        self._rollback_day: str = self._today()
        self._rollback_count: int = 0
        self.last_snapshot_id: Optional[str] = None
        self.last_snapshot_size: Optional[int] = None
        self.last_escalation: Optional[str] = None
        self._load()

    # ------------------------------------------------------------------ #
    # persistence
    # ------------------------------------------------------------------ #

    def _state_path(self) -> Optional[Path]:
        if self._data_dir is None:
            return None
        return self._data_dir / STATE_FILENAME

    def _load(self) -> None:
        path = self._state_path()
        if path is None:
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("supervisor state is not an object")
            self.state = SupState(raw.get("state", SupState.STOPPED.value))
            self.backoff_level = max(0, int(raw.get("backoff_level", 0)))
            now = self._clock()
            times = raw.get("restart_times", [])
            if isinstance(times, list):
                # Monotonic stamps from a previous process are only
                # meaningful inside the window and never from the
                # future; anything else is dropped, not trusted.
                self._restart_times = [
                    float(t) for t in times
                    if isinstance(t, (int, float))
                    and now - self.flap_window_s <= float(t) <= now
                ]
            rb = raw.get("rollbacks", {})
            if isinstance(rb, dict):
                self._rollback_day = str(rb.get("day", self._today()))
                self._rollback_count = max(0, int(rb.get("count", 0)))
            snap = raw.get("last_snapshot_id")
            self.last_snapshot_id = str(snap) if snap else None
            size = raw.get("last_snapshot_size")
            self.last_snapshot_size = (
                int(size) if isinstance(size, (int, float)) else None)
            esc = raw.get("last_escalation")
            self.last_escalation = str(esc) if esc else None
        except (OSError, ValueError, TypeError) as exc:
            # Safe defaults: STOPPED, zeroed counters, and — the point
            # of the rule — a manual start() remains fully available.
            logger.warning("supervisor state unreadable (%s); "
                           "starting from safe defaults", exc)
            self.state = SupState.STOPPED
            self.backoff_level = 0
            self._restart_times = []
            self._rollback_count = 0
            self.last_snapshot_id = None
            self.last_snapshot_size = None

    def _save(self) -> None:
        path = self._state_path()
        if path is None:
            return
        state = {
            "version": _STATE_VERSION,
            "state": self.state.value,
            "backoff_level": self.backoff_level,
            "restart_times": list(self._restart_times),
            "rollbacks": {"day": self._rollback_day,
                          "count": self._rollback_count},
            "last_snapshot_id": self.last_snapshot_id,
            "last_snapshot_size": self.last_snapshot_size,
            "last_escalation": self.last_escalation,
        }
        # Scar tissue, checkpoint form: never let a state write erase
        # the last known-good snapshot pointer.
        if state["last_snapshot_id"] is None:
            try:
                disk = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(disk, dict) and disk.get("last_snapshot_id"):
                    state["last_snapshot_id"] = disk["last_snapshot_id"]
                    state["last_snapshot_size"] = disk.get(
                        "last_snapshot_size")
                    logger.warning(
                        "supervisor state write tried to drop the "
                        "snapshot pointer; kept %s",
                        state["last_snapshot_id"])
            except (OSError, ValueError):
                pass
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            logger.warning("could not persist supervisor state: %s", exc)

    # ------------------------------------------------------------------ #
    # small helpers
    # ------------------------------------------------------------------ #

    def _now(self) -> float:
        return float(self._clock())

    def _stop_child(self) -> None:
        handle, self._handle = self._handle, None
        stop = getattr(handle, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:  # a dying child may refuse; we move on
                logger.exception("child stop() raised; continuing")

    def _do_escalate(self, reason: str) -> None:
        self.last_escalation = reason
        try:
            self._escalate(reason)
        except Exception:
            logger.exception("escalate callback raised")

    @property
    def rollbacks_today(self) -> int:
        if self._rollback_day != self._today():
            return 0
        return self._rollback_count

    def status(self) -> dict:
        return {
            "state": self.state.value,
            "backoff_level": self.backoff_level,
            "restarts_in_window": len(self._restart_times),
            "rollbacks_today": self.rollbacks_today,
            "last_snapshot_id": self.last_snapshot_id,
            "last_escalation": self.last_escalation,
            "next_restart_at": self._next_restart_at,
        }

    # ------------------------------------------------------------------ #
    # lifecycle: manual start / stop
    # ------------------------------------------------------------------ #

    def start(self) -> bool:
        """Manual start. Returns True if a spawn happened.

        Always available — from STOPPED, from BACKOFF (start now
        instead of waiting), and from FATAL (the owner's override:
        escalation stops AUTOMATIC restarts, never the human). A
        manual start from FATAL earns a fresh backoff/flap budget;
        the rollback budget is separate and is NOT refilled here.
        """
        if self.state in (SupState.STARTING, SupState.RUNNING):
            return False
        if self.state is SupState.FATAL:
            self.backoff_level = 0
            self._restart_times = []
        self._next_restart_at = None
        return self._launch()

    def stop(self) -> None:
        """Owner stop: halt the child and stay down."""
        self._stop_child()
        self.state = SupState.STOPPED
        self._next_restart_at = None
        self._healthy_since = None
        self._save()

    def _launch(self) -> bool:
        """Spawn once -> STARTING. A spawn that raises is a death at
        duration zero and goes through the normal death accounting."""
        self.state = SupState.STARTING
        self._started_at = self._now()
        self._healthy_since = None
        try:
            self._handle = self._spawn()
        except Exception:
            logger.exception("spawn() raised; treating as a fast death")
            self._handle = None
            self._register_death()
            return False
        self._save()
        return True

    # ------------------------------------------------------------------ #
    # the tick: time- and probe-driven transitions
    # ------------------------------------------------------------------ #

    def tick(self) -> SupState:
        now = self._now()
        if self.state is SupState.BACKOFF:
            if self._next_restart_at is not None \
                    and now >= self._next_restart_at:
                self._next_restart_at = None
                self._launch()
        elif self.state is SupState.STARTING:
            if self._probe_ok():
                self.state = SupState.RUNNING
                self._healthy_since = now
                self._save()
        elif self.state is SupState.RUNNING:
            if self._probe_ok():
                if self._healthy_since is None:
                    self._healthy_since = now
                elif self.backoff_level > 0 and \
                        now - self._healthy_since >= self.uptime_reset_s:
                    # Demonstrated uptime refills the retry budget.
                    self.backoff_level = 0
                    logger.info("uptime proven; backoff budget refilled")
                    self._save()
            else:
                # Alive but not proving work: the uptime streak is
                # broken. (Killing a wedged child is the watchdog
                # round; this engine only refuses to call it healthy.)
                self._healthy_since = None
        return self.state

    def _probe_ok(self) -> bool:
        if self._handle is None:
            return False
        try:
            return bool(self._probe(self._handle))
        except Exception:
            logger.exception("probe() raised; treating as unhealthy")
            return False

    # ------------------------------------------------------------------ #
    # death accounting: backoff, fast-death, flapping breaker
    # ------------------------------------------------------------------ #

    def notify_exited(self, exit_code: Optional[int] = None) -> SupState:
        """The outer runner reports the child died. (exit_code is
        recorded for the caller's logs; policy is duration-based.)"""
        if self.state not in (SupState.STARTING, SupState.RUNNING):
            return self.state  # late/duplicate notice: already counted
        self._handle = None
        self._register_death()
        return self.state

    def _register_death(self) -> None:
        now = self._now()
        started = self._started_at if self._started_at is not None else now
        duration = max(0.0, now - started)
        # Fast death counts double: it is misconfigured, not unlucky.
        weight = 2 if duration < self.fast_death_s else 1
        self._healthy_since = None

        # Flapping breaker (OTP intensity / StartLimitBurst): count
        # restarts in the sliding window, weighted like the backoff.
        self._restart_times = [
            t for t in self._restart_times if now - t < self.flap_window_s]
        self._restart_times.extend([now] * weight)
        if len(self._restart_times) >= self.flap_max_restarts:
            self.state = SupState.FATAL
            self._next_restart_at = None
            self._save()
            self._do_escalate(
                f"JARVIS restarted {len(self._restart_times)} times in "
                "under 10 minutes and kept failing, so I have stopped "
                "restarting it — a loop would not fix this. It needs "
                "your attention, sir.")
            self._save()
            return

        delay = min(self.backoff_cap_s,
                    self.backoff_base_s
                    * (self.backoff_factor ** self.backoff_level))
        self.backoff_level += weight
        self.state = SupState.BACKOFF
        self._next_restart_at = now + delay
        self._save()

    # ------------------------------------------------------------------ #
    # cdog's verified-restart ritual
    # ------------------------------------------------------------------ #

    def _guarded_snapshot(self) -> str:
        """Snapshot with pm2's scar-tissue guard: a new EMPTY snapshot
        never replaces a known non-empty one. Refusal raises."""
        snap_id = str(self._snapshot())
        if self._snapshot_probe is not None:
            try:
                size: Optional[int] = int(self._snapshot_probe(snap_id))
            except Exception:
                logger.exception("snapshot_probe raised; size unknown")
                size = None
            if size is not None:
                if size == 0 and (self.last_snapshot_size or 0) > 0:
                    logger.error(
                        "refusing empty snapshot %s over good snapshot "
                        "%s (size %s)", snap_id, self.last_snapshot_id,
                        self.last_snapshot_size)
                    raise ScarTissueRefusal(
                        f"new snapshot {snap_id!r} is empty; keeping "
                        f"known-good {self.last_snapshot_id!r}")
                self.last_snapshot_size = size
        self.last_snapshot_id = snap_id
        return snap_id

    def _spawn_and_probe(self) -> bool:
        """Spawn, then the post-test probe. True = verified healthy."""
        self.state = SupState.STARTING
        self._started_at = self._now()
        self._healthy_since = None
        try:
            self._handle = self._spawn()
        except Exception:
            logger.exception("spawn() raised during verified restart")
            self._handle = None
            return False
        if self._probe_ok():
            self.state = SupState.RUNNING
            self._healthy_since = self._now()
            return True
        return False

    def verified_restart(self) -> RestartResult:
        """snapshot -> restart -> post-test -> rollback on failure.

        Never restarts without a snapshot first. A failed post-test
        restores the snapshot and counts against the daily rollback
        budget; an exhausted budget — or a rollback that also fails
        its probe — escalates to the owner and stops (FATAL).
        """
        if self.state is SupState.FATAL:
            return RestartResult(
                ok=False, verified=False, rolled_back=False,
                snapshot_id=self.last_snapshot_id, state=self.state,
                reason="supervisor is FATAL; a manual start is "
                       "required before any restart ritual",
                rollbacks_today=self.rollbacks_today)
        try:
            snap_id = self._guarded_snapshot()
        except ScarTissueRefusal as exc:
            return RestartResult(
                ok=False, verified=False, rolled_back=False,
                snapshot_id=self.last_snapshot_id, state=self.state,
                reason=f"restart aborted: {exc}",
                rollbacks_today=self.rollbacks_today)
        self._save()

        self._stop_child()
        if self._spawn_and_probe():
            self._save()
            return RestartResult(
                ok=True, verified=True, rolled_back=False,
                snapshot_id=snap_id, state=self.state,
                reason="post-restart health probe passed",
                rollbacks_today=self.rollbacks_today)

        # Post-test failed. Budget check BEFORE another rollback.
        if self.rollbacks_today >= self.max_rollbacks_per_day:
            self._stop_child()
            self.state = SupState.FATAL
            self._save()
            self._do_escalate(
                f"JARVIS failed its health check after a restart, and "
                f"it has already rolled back {self.rollbacks_today} "
                "times today, so I have stopped the automatic "
                "recovery — this needs your eyes first, sir.")
            self._save()
            return RestartResult(
                ok=False, verified=False, rolled_back=False,
                snapshot_id=snap_id, state=self.state,
                reason="rollback budget for today is exhausted; "
                       "escalated and stopped",
                rollbacks_today=self.rollbacks_today)

        # Roll back: restore the snapshot, count it, run the old state.
        self._stop_child()
        self._restore(snap_id)
        today = self._today()
        if self._rollback_day != today:
            self._rollback_day, self._rollback_count = today, 0
        self._rollback_count += 1
        self._save()
        if self._spawn_and_probe():
            self._save()
            return RestartResult(
                ok=True, verified=False, rolled_back=True,
                snapshot_id=snap_id, state=self.state,
                reason="new run failed its health probe; rolled back "
                       "to the pre-restart snapshot and the restored "
                       "run is healthy",
                rollbacks_today=self.rollbacks_today)

        self._stop_child()
        self.state = SupState.FATAL
        self._save()
        self._do_escalate(
            "JARVIS failed its health check after a restart, and the "
            "restored backup failed the same check, so I have stopped "
            "it rather than guess further, sir.")
        self._save()
        return RestartResult(
            ok=False, verified=False, rolled_back=True,
            snapshot_id=snap_id, state=self.state,
            reason="rolled back, but the restored run also failed "
                   "its health probe; escalated and stopped",
            rollbacks_today=self.rollbacks_today)


# ---------------------------------------------------------------------- #
# production adapters — reuse jarvis.maintenance, never duplicate it
# ---------------------------------------------------------------------- #

def maintenance_snapshot(data_dir: Path | str) -> Callable[[], str]:
    """snapshot() backed by maintenance.create_backup (zip snapshot
    via the sqlite backup API, rotated). Returns the zip path."""
    def _snap() -> str:
        from jarvis import maintenance
        return str(maintenance.create_backup(data_dir,
                                             label="supervisor"))
    return _snap


def maintenance_restore(data_dir: Path | str) -> Callable[[str], None]:
    """restore(id) backed by maintenance.restore_backup (which takes
    its own pre-restore safety snapshot first)."""
    def _restore(snap_id: str) -> None:
        from jarvis import maintenance
        maintenance.restore_backup(data_dir, snap_id)
    return _restore


def maintenance_snapshot_probe(snap_id: str) -> int:
    """Size of a maintenance snapshot = number of files in the zip
    (0 for a missing/corrupt snapshot — exactly what the scar-tissue
    guard must catch)."""
    import zipfile
    try:
        with zipfile.ZipFile(snap_id) as zf:
            return len(zf.namelist())
    except (OSError, zipfile.BadZipFile):
        return 0


def supervisor_for_data_dir(
        data_dir: Path | str, *,
        spawn: Callable[[], object],
        probe: Callable[[object], bool],
        escalate: Callable[[str], None],
        clock: Callable[[], float] = time.monotonic,
        **policy: object) -> Supervisor:
    """A Supervisor wired to maintenance snapshots for a real data
    dir. spawn/probe/escalate stay injected — they belong to the
    launcher round, not to this engine."""
    return Supervisor(
        spawn, probe,
        maintenance_snapshot(data_dir),
        maintenance_restore(data_dir),
        escalate, clock,
        data_dir=data_dir,
        snapshot_probe=maintenance_snapshot_probe,
        **policy)  # type: ignore[arg-type]
