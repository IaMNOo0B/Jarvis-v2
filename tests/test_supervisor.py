"""Tests for jarvis.supervisor — the self-healing engine.

Patterns under test (Team 19 mega-scan): the Supervisor/OTP state
machine (STOPPED/STARTING/RUNNING/BACKOFF/FATAL), counted exponential
backoff refilled ONLY by demonstrated uptime, fast-death double
weight, the flapping breaker (5 restarts / 10 min -> FATAL +
escalate once, never loop), cdog's verified-restart ritual
(snapshot -> restart -> post-test -> rollback), the 50/day rollback
budget, and pm2's scar-tissue guard (an empty snapshot never
replaces a good one).

Conventions: stdlib + pytest only; every collaborator is a fake —
no real process is ever spawned; all time is injected.
"""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path

import pytest

from jarvis import supervisor as sup_mod
from jarvis.supervisor import Supervisor, SupState

TODAY = "2026-10-20"


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = float(t)

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


class FakeHandle:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class SpawnFake:
    """Returns FakeHandles; can be told to raise instead."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0
        self.handles: list[FakeHandle] = []

    def __call__(self) -> FakeHandle:
        self.calls += 1
        if self.fail:
            raise RuntimeError("spawn blew up")
        h = FakeHandle()
        self.handles.append(h)
        return h


class ProbeFake:
    """Scripted probe: pops queued results, then falls to default."""

    def __init__(self, default: bool = True) -> None:
        self.default = default
        self.results: list[bool] = []
        self.calls = 0

    def __call__(self, handle: object) -> bool:
        self.calls += 1
        if self.results:
            return self.results.pop(0)
        return self.default


class SnapshotFake:
    def __init__(self, sizes: dict[str, int] | None = None) -> None:
        self.sizes = sizes or {}
        self.taken: list[str] = []
        self.restored: list[str] = []
        self._n = 0

    def snapshot(self) -> str:
        self._n += 1
        snap_id = f"snap-{self._n}"
        self.taken.append(snap_id)
        return snap_id

    def restore(self, snap_id: str) -> None:
        self.restored.append(snap_id)

    def probe(self, snap_id: str) -> int:
        return self.sizes.get(snap_id, 1)


class Rig:
    """A Supervisor + all its fakes, wired together."""

    def __init__(self, tmp_path: Path | None = None, **policy) -> None:
        self.clock = FakeClock()
        self.spawn = SpawnFake()
        self.probe = ProbeFake()
        self.snaps = SnapshotFake(policy.pop("sizes", None))
        self.escalations: list[str] = []
        self.data_dir = (tmp_path / "data") if tmp_path else None
        self.sup = Supervisor(
            self.spawn, self.probe, self.snaps.snapshot,
            self.snaps.restore, self.escalations.append, self.clock,
            data_dir=self.data_dir,
            snapshot_probe=self.snaps.probe,
            today=lambda: TODAY,
            **policy)

    # -- driving helpers ------------------------------------------------ #
    def to_running(self) -> None:
        assert self.sup.start() is True
        assert self.sup.tick() is SupState.RUNNING

    def kill(self, run_s: float) -> None:
        """Run the child for run_s seconds, then report its death."""
        self.clock.advance(run_s)
        self.sup.notify_exited(1)


# --------------------------------------------------------------------- #
# the state machine: transition table as tested
# --------------------------------------------------------------------- #

def test_transition_table_full_walk(tmp_path):
    r = Rig(tmp_path)
    s = r.sup
    assert s.state is SupState.STOPPED
    assert s.tick() is SupState.STOPPED          # tick is a no-op down here
    assert s.start() is True
    assert s.state is SupState.STARTING
    assert s.start() is False                    # already starting: no-op
    assert s.tick() is SupState.RUNNING          # probe passed
    r.kill(30.0)                                 # healthy-length run, dies
    assert s.state is SupState.BACKOFF
    assert s.tick() is SupState.BACKOFF          # delay (1s) not yet over
    r.clock.advance(1.0)
    assert s.tick() is SupState.STARTING         # backoff expired: respawn
    assert s.tick() is SupState.RUNNING
    s.stop()
    assert s.state is SupState.STOPPED
    assert r.spawn.handles[-1].stopped is True
    assert s.tick() is SupState.STOPPED


def test_manual_start_from_backoff_skips_the_wait(tmp_path):
    r = Rig(tmp_path)
    r.to_running()
    r.kill(30.0)
    assert r.sup.state is SupState.BACKOFF
    assert r.sup.start() is True                 # owner impatience wins
    assert r.sup.state is SupState.STARTING


# --------------------------------------------------------------------- #
# backoff: doubling, cap, and the uptime-only reset
# --------------------------------------------------------------------- #

def test_backoff_delays_double_and_cap(tmp_path):
    r = Rig(tmp_path, backoff_cap_s=8.0, flap_max_restarts=99)
    delays = []
    for _ in range(5):
        assert r.sup.start() is True
        r.sup.tick()                             # -> RUNNING
        died_at = r.clock.t + 10.0
        r.kill(10.0)
        delays.append(r.sup._next_restart_at - died_at)
    assert delays == [1.0, 2.0, 4.0, 8.0, 8.0]   # cap holds at 8
    assert r.sup.backoff_level == 5


def test_backoff_reset_only_after_60s_proven_uptime(tmp_path):
    r = Rig(tmp_path, flap_max_restarts=99)
    r.to_running()
    r.kill(10.0)
    assert r.sup.backoff_level == 1
    assert r.sup.start() is True
    assert r.sup.tick() is SupState.RUNNING      # healthy streak starts
    r.clock.advance(59.0)
    r.sup.tick()
    assert r.sup.backoff_level == 1              # 59s proves nothing
    r.clock.advance(1.0)
    r.sup.tick()
    assert r.sup.backoff_level == 0              # 60s demonstrated: refill


def test_probe_failure_breaks_the_uptime_streak(tmp_path):
    r = Rig(tmp_path, flap_max_restarts=99)
    r.to_running()
    r.kill(10.0)
    assert r.sup.backoff_level == 1
    r.sup.start()
    r.sup.tick()                                 # RUNNING, streak starts
    r.clock.advance(30.0)
    r.sup.tick()
    r.probe.results = [False]
    r.sup.tick()                                 # unhealthy: streak broken
    r.sup.tick()                                 # healthy again: streak restarts
    r.clock.advance(59.0)
    r.sup.tick()                                 # new streak only 59s old
    assert r.sup.backoff_level == 1
    r.clock.advance(1.0)
    r.sup.tick()
    assert r.sup.backoff_level == 0


def test_fast_death_counts_double(tmp_path):
    r = Rig(tmp_path, flap_max_restarts=99)
    r.sup.start()
    died_at = r.clock.t + 3.0
    r.kill(3.0)                                  # < 5s: misconfigured
    assert r.sup.backoff_level == 2              # double weight
    assert r.sup._next_restart_at - died_at == 1.0   # delay from level 0
    r.sup.start()
    died_at = r.clock.t + 10.0
    r.kill(10.0)                                 # a normal death now
    assert r.sup.backoff_level == 3
    assert r.sup._next_restart_at - died_at == 4.0   # 2**2: skipped a step


def test_spawn_failure_is_a_fast_death(tmp_path):
    r = Rig(tmp_path)
    r.spawn.fail = True
    assert r.sup.start() is False
    assert r.sup.state is SupState.BACKOFF
    assert r.sup.backoff_level == 2              # duration 0 -> double


# --------------------------------------------------------------------- #
# the flapping breaker: escalation over looping
# --------------------------------------------------------------------- #

def test_flapping_breaker_trips_and_escalates_once(tmp_path):
    r = Rig(tmp_path)
    r.sup.start()
    r.kill(3.0)                                  # window count 2
    assert r.sup.state is SupState.BACKOFF
    r.sup.start()
    r.kill(3.0)                                  # window count 4
    assert r.sup.state is SupState.BACKOFF
    r.sup.start()
    r.kill(10.0)                                 # window count 5 -> FATAL
    assert r.sup.state is SupState.FATAL
    assert len(r.escalations) == 1
    assert "stopped restarting" in r.escalations[0]
    # and it STAYS stopped: no respawn, no re-escalation, ever
    calls = r.spawn.calls
    r.clock.advance(3600.0)
    assert r.sup.tick() is SupState.FATAL
    r.sup.notify_exited(1)
    assert r.spawn.calls == calls
    assert len(r.escalations) == 1


def test_flap_window_prunes_old_restarts(tmp_path):
    r = Rig(tmp_path)
    for _ in range(4):
        r.sup.start()
        r.kill(10.0)                             # one restart per death
        assert r.sup.state is SupState.BACKOFF   # never FATAL: too slow
        r.clock.advance(700.0)                   # window (600s) slides past
    assert r.escalations == []


def test_manual_start_from_fatal_is_the_owner_override(tmp_path):
    r = Rig(tmp_path)
    r.sup.start(); r.kill(3.0)
    r.sup.start(); r.kill(3.0)
    r.sup.start(); r.kill(10.0)
    assert r.sup.state is SupState.FATAL
    assert r.sup.start() is True                 # the human can always act
    assert r.sup.state is SupState.STARTING
    assert r.sup.backoff_level == 0              # fresh budget
    assert r.sup.tick() is SupState.RUNNING
    assert len(r.escalations) == 1


# --------------------------------------------------------------------- #
# cdog's verified-restart ritual
# --------------------------------------------------------------------- #

def test_verified_restart_happy_path(tmp_path):
    r = Rig(tmp_path, sizes={"snap-1": 4})
    r.to_running()
    old = r.spawn.handles[-1]
    res = r.sup.verified_restart()
    assert res.ok is True and res.verified is True
    assert res.rolled_back is False
    assert res.snapshot_id == "snap-1"
    assert old.stopped is True                  # old child replaced
    assert r.snaps.restored == []                # no rollback needed
    assert r.sup.state is SupState.RUNNING
    assert r.sup.last_snapshot_id == "snap-1"


def test_verified_restart_rolls_back_on_probe_failure(tmp_path):
    r = Rig(tmp_path, sizes={"snap-1": 4})
    r.to_running()
    r.probe.results = [False, True]              # new run sick, old healthy
    res = r.sup.verified_restart()
    assert res.verified is False
    assert res.rolled_back is True
    assert res.ok is True                        # restored run is healthy
    assert r.snaps.restored == ["snap-1"]
    assert r.sup.state is SupState.RUNNING
    assert res.rollbacks_today == 1
    # the count is persisted, not just in memory
    on_disk = json.loads(
        (r.data_dir / "supervisor_state.json").read_text("utf-8"))
    assert on_disk["rollbacks"] == {"day": TODAY, "count": 1}


def test_verified_restart_rollback_also_fails_escalates(tmp_path):
    r = Rig(tmp_path, sizes={"snap-1": 4})
    r.to_running()
    r.probe.results = [False, False]             # even the backup is sick
    res = r.sup.verified_restart()
    assert res.ok is False and res.rolled_back is True
    assert r.sup.state is SupState.FATAL
    assert len(r.escalations) == 1
    assert "restored backup failed" in r.escalations[0]


def _seed_state(r: Rig, **overrides) -> None:
    r.data_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "version": 1, "state": "stopped", "backoff_level": 0,
        "restart_times": [],
        "rollbacks": {"day": TODAY, "count": 0},
        "last_snapshot_id": None, "last_snapshot_size": None,
        "last_escalation": None,
    }
    state.update(overrides)
    (r.data_dir / "supervisor_state.json").write_text(
        json.dumps(state), encoding="utf-8")


def test_rollback_daily_cap_escalates_without_restoring(tmp_path):
    r = Rig(tmp_path, sizes={"snap-1": 4})
    _seed_state(r, rollbacks={"day": TODAY, "count": 50})
    sup = Supervisor(r.spawn, r.probe, r.snaps.snapshot, r.snaps.restore,
                     r.escalations.append, r.clock, data_dir=r.data_dir,
                     snapshot_probe=r.snaps.probe, today=lambda: TODAY)
    assert sup.rollbacks_today == 50
    r.probe.results = [False]
    res = sup.verified_restart()
    assert res.ok is False and res.rolled_back is False
    assert r.snaps.restored == []                # budget spent: no rollback
    assert sup.state is SupState.FATAL
    assert len(r.escalations) == 1
    assert "rolled back 50 times" in r.escalations[0]


def test_rollback_counter_resets_on_a_new_day(tmp_path):
    r = Rig(tmp_path, sizes={"snap-1": 4})
    _seed_state(r, rollbacks={"day": "2026-10-19", "count": 50})
    sup = Supervisor(r.spawn, r.probe, r.snaps.snapshot, r.snaps.restore,
                     r.escalations.append, r.clock, data_dir=r.data_dir,
                     snapshot_probe=r.snaps.probe, today=lambda: TODAY)
    assert sup.rollbacks_today == 0             # yesterday doesn't count
    r.probe.results = [False, True]
    res = sup.verified_restart()
    assert res.rolled_back is True
    assert res.rollbacks_today == 1


def test_verified_restart_refused_in_fatal(tmp_path):
    r = Rig(tmp_path)
    _seed_state(r, state="fatal")
    sup = Supervisor(r.spawn, r.probe, r.snaps.snapshot, r.snaps.restore,
                     r.escalations.append, r.clock, data_dir=r.data_dir,
                     snapshot_probe=r.snaps.probe, today=lambda: TODAY)
    assert sup.state is SupState.FATAL
    res = sup.verified_restart()
    assert res.ok is False
    assert "manual start" in res.reason
    assert r.snaps.taken == []                   # ritual never began


# --------------------------------------------------------------------- #
# pm2's scar-tissue guard
# --------------------------------------------------------------------- #

def test_scar_tissue_guard_refuses_empty_over_good(tmp_path, caplog):
    r = Rig(tmp_path, sizes={"snap-1": 5, "snap-2": 0})
    r.to_running()
    res1 = r.sup.verified_restart()             # records the good snapshot
    assert res1.ok is True
    assert r.sup.last_snapshot_id == "snap-1"
    spawns_before = r.spawn.calls
    handle_before = r.spawn.handles[-1]
    with caplog.at_level(logging.ERROR, logger="jarvis.supervisor"):
        res2 = r.sup.verified_restart()         # new snapshot is EMPTY
    assert res2.ok is False
    assert "empty" in res2.reason
    assert "refusing empty snapshot" in caplog.text
    assert r.sup.last_snapshot_id == "snap-1"    # good pointer survives
    assert r.spawn.calls == spawns_before       # child never touched
    assert handle_before.stopped is False
    assert r.sup.state is SupState.RUNNING


def test_first_snapshot_may_be_empty_without_a_good_one(tmp_path):
    r = Rig(tmp_path, sizes={"snap-1": 0})
    res = r.sup.verified_restart()              # nothing good to protect
    assert res.ok is True
    assert r.sup.last_snapshot_id == "snap-1"


# --------------------------------------------------------------------- #
# persistence: roundtrip, corruption, FATAL on disk
# --------------------------------------------------------------------- #

def _fresh_sup(r: Rig) -> Supervisor:
    return Supervisor(r.spawn, r.probe, r.snaps.snapshot, r.snaps.restore,
                      r.escalations.append, r.clock, data_dir=r.data_dir,
                      snapshot_probe=r.snaps.probe, today=lambda: TODAY)


def test_state_persistence_roundtrip(tmp_path):
    r = Rig(tmp_path, sizes={"snap-1": 4}, flap_max_restarts=99)
    r.to_running()
    r.sup.verified_restart()
    r.kill(10.0)                                 # -> BACKOFF, level 1
    sup2 = _fresh_sup(r)
    assert sup2.state is SupState.BACKOFF
    assert sup2.backoff_level == 1
    assert sup2.last_snapshot_id == "snap-1"
    assert sup2.rollbacks_today == 0


def test_corrupt_state_loads_defaults_and_manual_start_works(tmp_path):
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "supervisor_state.json").write_text("not json {{{",
                                                encoding="utf-8")
    r = Rig(tmp_path)
    assert r.sup.state is SupState.STOPPED       # safe defaults
    assert r.sup.backoff_level == 0
    assert r.sup.start() is True                 # never locked out
    assert r.sup.state is SupState.STARTING


def test_fatal_state_on_disk_blocks_auto_but_not_manual(tmp_path):
    r = Rig(tmp_path)
    _seed_state(r, state="fatal")
    sup = _fresh_sup(r)
    assert sup.state is SupState.FATAL
    assert sup.tick() is SupState.FATAL
    assert r.spawn.calls == 0
    assert sup.start() is True                   # owner override
    assert sup.state is SupState.STARTING


# --------------------------------------------------------------------- #
# production adapters: real maintenance backups (reuse, not copies)
# --------------------------------------------------------------------- #

def test_maintenance_adapters_take_a_real_snapshot(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "config.yaml").write_text("profile: owais\n", encoding="utf-8")
    escalations: list[str] = []
    spawn, probe = SpawnFake(), ProbeFake()
    sup = sup_mod.supervisor_for_data_dir(
        data, spawn=spawn, probe=probe,
        escalate=escalations.append, clock=FakeClock())
    res = sup.verified_restart()
    assert res.ok is True
    snap_path = Path(res.snapshot_id)
    assert snap_path.exists()                    # a real zip on disk
    assert sup.last_snapshot_size is not None
    assert sup.last_snapshot_size >= 1           # it holds the config
    with zipfile.ZipFile(snap_path) as zf:
        assert "config.yaml" in zf.namelist()


def test_maintenance_snapshot_probe_counts_entries(tmp_path):
    empty_zip = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty_zip, "w"):
        pass
    assert sup_mod.maintenance_snapshot_probe(str(empty_zip)) == 0
    assert sup_mod.maintenance_snapshot_probe(str(tmp_path / "gone.zip")) == 0
