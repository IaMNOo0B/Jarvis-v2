"""Extension Team 4 — the routine guard (jarvis/routine_guard.py).

Fire discipline from Team 14's top steals (ai-employees + herdr):
window check, period-key once-guard (local time), hard wall-clock
budget recording 'partial', fail-closed on missing config, bounded
catch-up — missed work recorded, never silently replayed.

All timestamps are built from LOCAL date/time components, so the
suite is timezone-independent.
"""

import time

import pytest

from jarvis.routine_guard import (
    GuardDecision,
    RoutineGuard,
    RoutineSpec,
    period_key,
)


def local_ts(y, mo, d, hh=0, mm=0):
    return time.mktime((y, mo, d, hh, mm, 0, 0, 0, -1))


# Tue 2026-10-20, a fixed "today" for most tests.
TUE_0800 = local_ts(2026, 10, 20, 8, 0)


def daily_spec(**kw):
    base = {"name": "morning-digest", "period": "day", "due": "08:00"}
    base.update(kw)
    return RoutineSpec(**base)


def guard(tmp_path, *specs, time_fn=None):
    return RoutineGuard(str(tmp_path),
                        specs={s.name: s for s in specs},
                        time_fn=time_fn)


# --------------------------------------------------------------------------- #
# period keys — local time, three formats
# --------------------------------------------------------------------------- #

class TestPeriodKey:
    def test_day(self):
        assert period_key("day", TUE_0800) == "2026-10-20"

    def test_month(self):
        assert period_key("month", TUE_0800) == "2026-10"

    def test_week_iso(self):
        # Mon 2026-10-19 and Tue 2026-10-20 share ISO week 43.
        assert period_key("week", local_ts(2026, 10, 19, 9)) == "2026-W43"
        assert period_key("week", TUE_0800) == "2026-W43"
        assert period_key("week", local_ts(2026, 10, 26, 9)) == "2026-W44"

    def test_bad_period(self):
        with pytest.raises(ValueError):
            period_key("hourly", TUE_0800)


# --------------------------------------------------------------------------- #
# spec mechanics — due instant + window
# --------------------------------------------------------------------------- #

class TestSpecMechanics:
    def test_due_ts(self):
        spec = daily_spec()
        assert spec.due_ts(local_ts(2026, 10, 20, 3, 30)) == TUE_0800

    def test_due_defaults_to_period_start(self):
        spec = RoutineSpec(name="x", period="day")
        assert spec.due_ts(TUE_0800) == local_ts(2026, 10, 20, 0, 0)

    def test_in_window(self):
        spec = daily_spec(window=("08:00", "10:00"))
        assert spec.in_window(local_ts(2026, 10, 20, 8, 0))
        assert spec.in_window(local_ts(2026, 10, 20, 9, 59))
        assert not spec.in_window(local_ts(2026, 10, 20, 10, 0))
        assert not spec.in_window(local_ts(2026, 10, 20, 7, 59))

    def test_window_wraps_midnight(self):
        spec = daily_spec(window=("22:00", "02:00"))
        assert spec.in_window(local_ts(2026, 10, 20, 23, 30))
        assert spec.in_window(local_ts(2026, 10, 20, 1, 30))
        assert not spec.in_window(local_ts(2026, 10, 20, 12, 0))

    def test_no_window_always_in(self):
        assert daily_spec().in_window(local_ts(2026, 10, 20, 3, 0))

    def test_validate_rejects_bad_rows(self):
        with pytest.raises(ValueError):
            daily_spec(period="hourly").validate()
        with pytest.raises(ValueError):
            daily_spec(due="25:00").validate()
        with pytest.raises(ValueError):
            daily_spec(budget_s=0).validate()
        with pytest.raises(ValueError):
            daily_spec(catch_up_minutes=-1).validate()


# --------------------------------------------------------------------------- #
# check() — the verdict ladder
# --------------------------------------------------------------------------- #

class TestCheck:
    def test_unknown_name_fails_closed(self, tmp_path):
        g = guard(tmp_path, daily_spec())
        dec = g.check("no-such-routine", TUE_0800)
        assert isinstance(dec, GuardDecision)
        assert not dec.allowed
        assert dec.status == "failed"
        assert "failing closed" in dec.reason

    def test_invalid_spec_fails_closed(self, tmp_path):
        g = guard(tmp_path, RoutineSpec(name="bad", period="hourly"))
        dec = g.check("bad", TUE_0800)
        assert not dec.allowed and dec.status == "failed"

    def test_disabled(self, tmp_path):
        g = guard(tmp_path, daily_spec(enabled=False))
        dec = g.check("morning-digest", TUE_0800)
        assert not dec.allowed and dec.status == "skipped-disabled"

    def test_not_due_yet(self, tmp_path):
        g = guard(tmp_path, daily_spec())
        dec = g.check("morning-digest", local_ts(2026, 10, 20, 7, 0))
        assert not dec.allowed and dec.status == "skipped-not-due"

    def test_on_time_ok(self, tmp_path):
        g = guard(tmp_path, daily_spec())
        dec = g.check("morning-digest", TUE_0800)
        assert dec.allowed and dec.status == "ok"
        assert not dec.caught_up and dec.late_by_s == 0
        assert dec.period_key == "2026-10-20"

    def test_late_within_catch_up_ok(self, tmp_path):
        g = guard(tmp_path, daily_spec(catch_up_minutes=120))
        dec = g.check("morning-digest", local_ts(2026, 10, 20, 9, 30))
        assert dec.allowed and dec.status == "ok"
        assert dec.caught_up and dec.late_by_s == 90 * 60

    def test_beyond_catch_up_is_missed_and_recorded(self, tmp_path):
        g = guard(tmp_path, daily_spec(catch_up_minutes=30))
        late = local_ts(2026, 10, 20, 12, 0)
        dec = g.check("morning-digest", late)
        assert not dec.allowed and dec.status == "missed"
        # Recorded in state...
        st = g.state("morning-digest")
        assert st["status"] == "missed"
        assert st["missed_periods"] == ["2026-10-20"]
        # ...and stable: a later check reports the same missed run,
        # it does not silently become fireable.
        dec2 = g.check("morning-digest", local_ts(2026, 10, 20, 13, 0))
        assert not dec2.allowed and dec2.status == "missed"
        assert g.begin("morning-digest", local_ts(2026, 10, 20, 13, 0)) is None

    def test_out_of_window(self, tmp_path):
        # Due 08:00, window ends 09:00, catch-up 120 min: at 09:30 the
        # run is inside catch-up but outside the window -> window wins.
        g = guard(tmp_path, daily_spec(window=("08:00", "09:00"),
                                       catch_up_minutes=120))
        dec = g.check("morning-digest", local_ts(2026, 10, 20, 9, 30))
        assert not dec.allowed and dec.status == "skipped-out-of-window"

    def test_missed_history_survives_into_next_period(self, tmp_path):
        g = guard(tmp_path, daily_spec(catch_up_minutes=30))
        g.check("morning-digest", local_ts(2026, 10, 20, 12, 0))  # missed
        dec = g.check("morning-digest", local_ts(2026, 10, 21, 8, 5))
        assert dec.allowed  # Wednesday is a fresh period
        assert g.state("morning-digest")["missed_periods"] == ["2026-10-20"]


# --------------------------------------------------------------------------- #
# begin() / RoutineRun — claim, once-guard, budget
# --------------------------------------------------------------------------- #

class TestBeginAndRun:
    def test_begin_claims_period_and_blocks_refire(self, tmp_path):
        clock = [TUE_0800]
        g = guard(tmp_path, daily_spec(), time_fn=lambda: clock[0])
        run = g.begin("morning-digest")
        assert run is not None and run.period_key == "2026-10-20"
        assert g.state("morning-digest")["status"] == "running"
        # Same period: the once-guard refuses a second claim even
        # before the first run finishes (crash-safe double-fire proof).
        assert g.begin("morning-digest") is None
        dec = g.check("morning-digest")
        assert dec.status == "skipped-already-fired"

    def test_finish_fired(self, tmp_path):
        clock = [TUE_0800]
        g = guard(tmp_path, daily_spec(), time_fn=lambda: clock[0])
        run = g.begin("morning-digest")
        clock[0] += 300
        assert run.finish("fired") == "fired"
        st = g.state("morning-digest")
        assert st["status"] == "fired" and st["elapsed_s"] == 300
        # Next day: fresh period, fires again.
        clock[0] = local_ts(2026, 10, 21, 8, 0)
        assert g.begin("morning-digest") is not None

    def test_over_budget_fired_becomes_partial(self, tmp_path):
        clock = [TUE_0800]
        g = guard(tmp_path, daily_spec(budget_s=60),
                  time_fn=lambda: clock[0])
        run = g.begin("morning-digest")
        clock[0] += 30
        assert not run.over_budget()
        clock[0] += 120  # 150s elapsed, budget 60s
        assert run.over_budget()
        assert run.finish("fired") == "partial"
        assert g.state("morning-digest")["status"] == "partial"

    def test_failed_stays_failed_even_over_budget(self, tmp_path):
        clock = [TUE_0800]
        g = guard(tmp_path, daily_spec(budget_s=60),
                  time_fn=lambda: clock[0])
        run = g.begin("morning-digest")
        clock[0] += 600
        assert run.finish("failed") == "failed"

    def test_finish_validates_outcome(self, tmp_path):
        g = guard(tmp_path, daily_spec(), time_fn=lambda: TUE_0800)
        run = g.begin("morning-digest")
        with pytest.raises(ValueError):
            run.finish("exploded")

    def test_begin_refused_when_check_fails(self, tmp_path):
        g = guard(tmp_path, daily_spec(catch_up_minutes=30))
        assert g.begin("morning-digest",
                       local_ts(2026, 10, 20, 12, 0)) is None
        assert g.last_decision.status == "missed"

    def test_weekly_once_guard(self, tmp_path):
        spec = RoutineSpec(name="weekly-review", period="week",
                           due="09:00")
        g = guard(tmp_path, spec)
        mon = local_ts(2026, 10, 19, 9, 0)
        run = g.begin("weekly-review", mon)
        assert run is not None and run.period_key == "2026-W43"
        run.finish("fired")
        # Wednesday of the same ISO week: already handled.
        dec = g.check("weekly-review", local_ts(2026, 10, 21, 9, 0))
        assert dec.status == "skipped-already-fired"
        # Next Monday: new week, clear.
        dec = g.check("weekly-review", local_ts(2026, 10, 26, 9, 0))
        assert dec.allowed and dec.period_key == "2026-W44"

    def test_state_survives_restart(self, tmp_path):
        g = guard(tmp_path, daily_spec(), time_fn=lambda: TUE_0800)
        g.begin("morning-digest").finish("fired")
        g2 = guard(tmp_path, daily_spec())
        dec = g2.check("morning-digest", local_ts(2026, 10, 20, 8, 30))
        assert dec.status == "skipped-already-fired"
