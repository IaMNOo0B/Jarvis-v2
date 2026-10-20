"""JARVIS v2 — the routine guard: deterministic fire discipline.

Pattern (MIT, markfulton/ai-employees + herdr-automations, both read at
code level in the Team 14 mega-scan): the fire time is only a HINT. Every
scheduled fire — reminder, morning digest, watcher tick — passes through
this guard first, and the guard alone decides whether it may run.

The ai-employees rule: all clock times live in ONE schedule table (the
specs dict handed to RoutineGuard). Routine code never carries its own
fire time, window, or budget.

For each fire the guard enforces, in order:
  1. Fail-closed lookup — an unknown routine name, or a spec that fails
     validation, is a recorded "failed", never a guessed window.
  2. Not-due check — before the period's due instant, no fire.
  3. Bounded catch-up — a missed occurrence may fire late ONLY inside
     the routine's catch_up_minutes window (default 120). Past it, the
     occurrence is recorded "missed" and NEVER silently replayed.
  4. Window check — outside [window_start, window_end) local time, the
     fire is "skipped-out-of-window" (scheduler drift, sleep and DST
     are absorbed here, not by the routine).
  5. Period-key once-guard — a routine fires at most once per period.
     The key is YYYY-MM-DD (day), YYYY-Www ISO (week) or YYYY-MM
     (month), always computed from LOCAL time, so double fires from a
     drifting scheduler are harmless.
  6. Hard wall-clock budget — a run that overruns its budget records
     "partial" (it wrote what it had), never a clean "fired".

Outcomes use a closed vocabulary: ok / failed / missed /
skipped-not-due / skipped-out-of-window / skipped-already-fired /
skipped-disabled. Runs record: fired / partial / failed.

State is one small JSON file (routine_state.json), written atomically
on every transition, so a crash mid-run leaves a truthful record and
the once-guard survives restarts.

Python 3.11+, stdlib only. No LLM anywhere near this file.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .proactivity import _atomic_write_json, _read_json

#: Default bounded catch-up window, minutes (herdr-automations).
DEFAULT_CATCH_UP_MINUTES = 120

#: Period kinds the guard understands.
PERIODS = ("day", "week", "month")

#: Closed outcome vocabulary for run.finish().
RUN_OUTCOMES = ("fired", "partial", "failed")


def _parse_hhmm(value: str) -> int:
    """'HH:MM' -> minutes since local midnight. ValueError if malformed."""
    parts = str(value).strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"expected HH:MM, got {value!r}")
    hh, mm = int(parts[0]), int(parts[1])
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"time out of range: {value!r}")
    return hh * 60 + mm


def period_key(period: str, ts: float) -> str:
    """The once-guard key for the period containing `ts` (LOCAL time).

    day -> 'YYYY-MM-DD', week -> 'YYYY-Www' (ISO), month -> 'YYYY-MM'.
    """
    dt = datetime.fromtimestamp(ts)
    if period == "day":
        return dt.strftime("%Y-%m-%d")
    if period == "month":
        return dt.strftime("%Y-%m")
    if period == "week":
        iso = dt.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    raise ValueError(f"unknown period {period!r} (expected one of {PERIODS})")


def _period_start(period: str, ts: float) -> float:
    """Epoch of local midnight at the start of the period containing ts."""
    lt = time.localtime(ts)
    if period == "day":
        y, m, d = lt.tm_year, lt.tm_mon, lt.tm_mday
    elif period == "month":
        y, m, d = lt.tm_year, lt.tm_mon, 1
    elif period == "week":
        day = datetime.fromtimestamp(ts).date()
        monday = day - timedelta(days=day.weekday())
        y, m, d = monday.year, monday.month, monday.day
    else:
        raise ValueError(f"unknown period {period!r}")
    return time.mktime((y, m, d, 0, 0, 0, 0, 0, -1))


@dataclass
class RoutineSpec:
    """One row of the schedule table.

    due:      'HH:MM' local time of day the routine falls due within
              its period (default: the period start itself).
    window:   (start, end) 'HH:MM' pair; the fire must land inside
              [start, end) local time. May wrap midnight ('22:00',
              '02:00'). None = no window restriction.
    budget_s: hard wall-clock budget for one run; overrunning turns a
              'fired' outcome into 'partial'. None = no budget.
    catch_up_minutes: how late a missed occurrence may still fire.
    """
    name: str
    period: str = "day"
    due: str | None = None
    window: tuple[str, str] | None = None
    budget_s: float | None = None
    catch_up_minutes: float = DEFAULT_CATCH_UP_MINUTES
    enabled: bool = True

    def validate(self) -> None:
        """Raise ValueError (plain words) on any malformed field."""
        if not self.name or not str(self.name).strip():
            raise ValueError("a routine needs a name")
        if self.period not in PERIODS:
            raise ValueError(
                f"routine {self.name!r}: period must be one of {PERIODS}")
        if self.due is not None:
            _parse_hhmm(self.due)
        if self.window is not None:
            if len(self.window) != 2:
                raise ValueError(
                    f"routine {self.name!r}: window needs (start, end)")
            _parse_hhmm(self.window[0])
            _parse_hhmm(self.window[1])
        if self.budget_s is not None and float(self.budget_s) <= 0:
            raise ValueError(
                f"routine {self.name!r}: budget must be positive")
        if float(self.catch_up_minutes) < 0:
            raise ValueError(
                f"routine {self.name!r}: catch_up_minutes can't be negative")

    def due_ts(self, ts: float) -> float:
        """Epoch this routine falls due in the period containing ts."""
        start = _period_start(self.period, ts)
        if self.due is None:
            return start
        return start + _parse_hhmm(self.due) * 60

    def in_window(self, ts: float) -> bool:
        """True when local time-of-day at ts is inside the window."""
        if self.window is None:
            return True
        lt = time.localtime(ts)
        now_min = lt.tm_hour * 60 + lt.tm_min
        start = _parse_hhmm(self.window[0])
        end = _parse_hhmm(self.window[1])
        if start <= end:
            return start <= now_min < end
        return now_min >= start or now_min < end  # wraps midnight


@dataclass
class GuardDecision:
    """The guard's verdict on one proposed fire."""
    allowed: bool
    status: str            # closed vocabulary, see module docstring
    reason: str
    name: str
    period_key: str = ""
    caught_up: bool = False   # allowed, but late (inside catch-up window)
    late_by_s: float = 0.0


class RoutineRun:
    """Handle for one claimed run. finish() writes the truthful record."""

    def __init__(self, guard: "RoutineGuard", spec: RoutineSpec,
                 key: str, started_ts: float) -> None:
        self._guard = guard
        self.spec = spec
        self.period_key = key
        self.started_ts = started_ts
        self.finished = False

    def elapsed(self) -> float:
        return self._guard._now() - self.started_ts

    def over_budget(self) -> bool:
        """Cooperative budget check for long runs to poll."""
        return (self.spec.budget_s is not None
                and self.elapsed() > float(self.spec.budget_s))

    def finish(self, outcome: str = "fired") -> str:
        """Record the run's outcome; returns the FINAL recorded status.

        A 'fired' that overran the hard budget is recorded 'partial' —
        the run wrote what it had; claiming a clean fire would be a lie.
        Explicit 'partial'/'failed' outcomes are recorded as given.
        """
        if outcome not in RUN_OUTCOMES:
            raise ValueError(
                f"outcome must be one of {RUN_OUTCOMES}, got {outcome!r}")
        final = outcome
        elapsed = self.elapsed()
        if (outcome == "fired" and self.spec.budget_s is not None
                and elapsed > float(self.spec.budget_s)):
            final = "partial"
        now = self._guard._now()
        self._guard._record(self.spec.name, {
            "period": self.period_key, "status": final,
            "started_ts": self.started_ts, "finished_ts": now,
            "elapsed_s": elapsed,
        })
        self.finished = True
        return final


class RoutineGuard:
    """Owns every scheduled fire decision. One instance per data dir.

    specs: the single schedule table, {name: RoutineSpec}. Looking up a
    name that isn't in the table fails CLOSED — the guard never invents
    a schedule.
    """

    def __init__(self, data_dir: str,
                 specs: dict[str, RoutineSpec] | None = None,
                 time_fn=None) -> None:
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._path = os.path.join(data_dir, "routine_state.json")
        self._specs: dict[str, RoutineSpec] = dict(specs or {})
        self._time = time_fn or time.time
        self.last_decision: GuardDecision | None = None

    # -- the schedule table --------------------------------------------- #
    def register(self, spec: RoutineSpec) -> None:
        self._specs[spec.name] = spec

    def spec(self, name: str) -> RoutineSpec | None:
        return self._specs.get(name)

    # -- state ------------------------------------------------------------ #
    def _now(self) -> float:
        return float(self._time())

    def _load(self) -> dict:
        return _read_json(self._path, {"routines": {}})

    def _record(self, name: str, entry: dict) -> None:
        state = self._load()
        routines = state.setdefault("routines", {})
        prev = routines.get(name, {})
        entry = {**prev, **entry}
        missed = list(prev.get("missed_periods", []))
        if entry.get("status") == "missed" and entry.get("period"):
            if entry["period"] not in missed:
                missed.append(entry["period"])
        entry["missed_periods"] = missed[-50:]  # bounded history
        routines[name] = entry
        _atomic_write_json(self._path, state)

    def state(self, name: str) -> dict:
        """Last recorded state for a routine ({} if never fired)."""
        return dict(self._load().get("routines", {}).get(name, {}))

    # -- the decision ----------------------------------------------------- #
    def check(self, name: str, now: float | None = None) -> GuardDecision:
        """May routine `name` fire at `now`? Pure verdict + missed record.

        Order matters (see module docstring): fail-closed -> disabled
        -> already-handled -> not-due -> missed -> window -> ok.
        A 'missed' verdict is RECORDED the first time it is reached, so
        the occurrence is surfaced exactly once and never replayed.
        """
        now = self._now() if now is None else float(now)
        spec = self._specs.get(name)
        if spec is None:
            dec = GuardDecision(
                False, "failed",
                f"no schedule row for {name!r} — failing closed, "
                "never guessing a window", name)
            self.last_decision = dec
            return dec
        try:
            spec.validate()
        except ValueError as exc:
            dec = GuardDecision(False, "failed",
                                f"bad schedule row: {exc}", name)
            self.last_decision = dec
            return dec

        key = period_key(spec.period, now)
        if not spec.enabled:
            dec = GuardDecision(False, "skipped-disabled",
                                f"{name} is switched off", name, key)
            self.last_decision = dec
            return dec

        prev = self.state(name)
        if prev.get("period") == key and prev.get("status") in (
                "running", "fired", "partial", "failed"):
            dec = GuardDecision(
                False, "skipped-already-fired",
                f"already handled this period ({prev['status']})",
                name, key)
            self.last_decision = dec
            return dec
        if prev.get("period") == key and prev.get("status") == "missed":
            dec = GuardDecision(
                False, "missed",
                "this period's run was missed and the catch-up window "
                "has closed — recorded, not replayed", name, key)
            self.last_decision = dec
            return dec

        due = spec.due_ts(now)
        if now < due:
            dec = GuardDecision(False, "skipped-not-due",
                                f"not due until {spec.due or 'period start'}",
                                name, key)
            self.last_decision = dec
            return dec

        late_by = now - due
        if late_by > float(spec.catch_up_minutes) * 60.0:
            self._record(name, {"period": key, "status": "missed",
                                "due_ts": due, "finished_ts": now})
            dec = GuardDecision(
                False, "missed",
                f"due {late_by / 60.0:.0f} min ago, beyond the "
                f"{spec.catch_up_minutes:.0f} min catch-up window — "
                "recorded as missed, not replayed", name, key,
                late_by_s=late_by)
            self.last_decision = dec
            return dec

        if not spec.in_window(now):
            dec = GuardDecision(
                False, "skipped-out-of-window",
                f"outside its window {spec.window[0]}–{spec.window[1]}",
                name, key, late_by_s=late_by)
            self.last_decision = dec
            return dec

        dec = GuardDecision(True, "ok", "clear to fire", name, key,
                            caught_up=late_by > 0, late_by_s=late_by)
        self.last_decision = dec
        return dec

    def begin(self, name: str, now: float | None = None) -> RoutineRun | None:
        """Check + atomically claim this period. None when not allowed.

        The claim (status 'running' with the period key) is persisted
        BEFORE the run starts: a crash mid-run leaves the period claimed,
        so a restarted scheduler cannot double-fire it.
        """
        now = self._now() if now is None else float(now)
        dec = self.check(name, now)
        if not dec.allowed:
            return None
        spec = self._specs[name]
        self._record(name, {"period": dec.period_key, "status": "running",
                            "started_ts": now, "due_ts": spec.due_ts(now)})
        return RoutineRun(self, spec, dec.period_key, now)
