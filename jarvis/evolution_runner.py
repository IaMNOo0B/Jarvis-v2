"""Evolution Runner — the idle self-review cycle (Extension Team 7).

CowAgent pattern (MIT — pattern only, this is our code): a background
review pass that runs while the owner is away, is "[SILENT]" by default,
and turns the day's raw activity into durable improvements. CowAgent's
anti-poisoning doctrine applies throughout: a lesson JARVIS teaches
itself must never be a negative capability claim ("I can't…", "tool X
doesn't work") — such text hardens into self-refusal. Every lesson text
this runner stores passes jarvis.brain.filter_lesson first.

Four steps, each fully isolated — a failing step is recorded in the
report and the others still run:

1. foundry      — SkillFoundry.draft_skills(): repeated successful tool
                  sequences become QUARANTINED draft skills (never
                  auto-approved; the owner reviews them).
2. diary        — Memory.write_diary_entry() for yesterday (UTC), fed
                  yesterday's session events. The composed diary value
                  is lesson-checked with filter_lesson; a rejected value
                  is removed again via Memory.forget() and the step is
                  reported failed — poison never stays in memory.
3. consolidate  — Memory.consolidate(): expire / dedupe / promote /
                  decay.
4. anticipation — SkillFoundry.anticipations(now) snapshot, appended to
                  <data_dir>/evolution/anticipations.jsonl and carried
                  in the report. Data only; nothing acts on it here.

[SILENT] semantics: run_review returns a ReviewReport — DATA for the
morning digest. It never prints, never rings, never interrupts. The
report itself is persisted to <data_dir>/evolution/last_review.json.

Scheduling is the caller's job; should_run() is the deterministic gate:
idle-triggered (no user turn for `idle_seconds`, default 30 minutes)
and at most once per UTC day. Intended call site (chat/proactivity
loop, owned by another worker):

    from jarvis.evolution_runner import (
        last_user_turn_at, read_last_run, run_review, should_run)
    if should_run(read_last_run(data_dir), now,
                  last_user_turn=last_user_turn_at(session_store)):
        run_review(data_dir, session_store, memory, now)

Stdlib only: sqlite3, json, dataclasses, datetime, pathlib.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from jarvis.observability import rotate_numbered
except Exception:  # observability unavailable -> snapshots don't rotate
    rotate_numbered = None  # type: ignore[assignment]

DEFAULT_IDLE_SECONDS = 30 * 60  # 30 minutes without a user turn
EVOLUTION_DIRNAME = "evolution"
_REPORT_NAME = "last_review.json"
_SNAPSHOTS_NAME = "anticipations.jsonl"
_DIARY_EVENT_TYPES = ("tool.call", "tool.result", "user.message")


# --------------------------------------------------------------------- util

def _as_utc(value) -> datetime | None:
    """datetime | ISO str | None -> aware UTC datetime (or None)."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _lesson_is_safe(text: str) -> bool:
    """Anti-poisoning gate: True iff `text` may be stored as a lesson.

    Delegates to jarvis.brain.filter_lesson (lazy import — brain is a
    heavy module and this keeps any import cycle impossible). Fail
    CLOSED: if the filter cannot be consulted, the text is rejected.
    """
    if not text or not text.strip():
        return False
    try:
        from jarvis.brain import filter_lesson
    except Exception:
        return False
    try:
        return bool(filter_lesson(text))
    except Exception:
        return False


def _events_for_day(db_path: str, day: str) -> list[dict]:
    """Session-store envelopes for one UTC day, diary-shaped.

    Read-only, mirroring skill_foundry's access pattern. Any read
    problem degrades to [] — the diary then rolls up episodes only,
    rather than the whole step failing on an auxiliary input.
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT event_id, session_id, seq, ts, type,"
                " causal_parent, actor, trust, payload FROM events"
                " WHERE ts LIKE ? AND type IN (?, ?, ?)"
                " ORDER BY session_id, seq",
                (f"{day}%",) + _DIARY_EVENT_TYPES,
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    out = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (ValueError, TypeError):
            payload = {}
        out.append({
            "event_id": row["event_id"], "session_id": row["session_id"],
            "seq": row["seq"], "ts": row["ts"], "type": row["type"],
            "causal_parent": row["causal_parent"], "actor": row["actor"],
            "trust": row["trust"],
            "payload": payload if isinstance(payload, dict) else {},
        })
    return out


# ------------------------------------------------------------------- report

@dataclass
class ReviewReport:
    """Outcome of one review cycle. DATA for the morning digest.

    `silent` is always True: a review never interrupts the owner. It is
    surfaced (if at all) as lines inside the morning digest.
    """

    day: str                                   # run date (UTC)
    diary_day: str                             # the day rolled up (UTC)
    ran_at: str                                # ISO timestamp of the run
    steps: dict = field(default_factory=dict)  # name -> step record
    new_skills: list = field(default_factory=list)
    diary: dict | None = None
    consolidation: dict | None = None
    anticipations: list = field(default_factory=list)
    silent: bool = True

    @property
    def ok(self) -> bool:
        return all(step.get("ok") for step in self.steps.values())

    @property
    def failed_steps(self) -> list[str]:
        return [name for name, step in self.steps.items()
                if not step.get("ok")]

    def to_dict(self) -> dict:
        return {
            "kind": "evolution_review",
            "silent": self.silent,
            "day": self.day,
            "diary_day": self.diary_day,
            "ran_at": self.ran_at,
            "ok": self.ok,
            "steps": self.steps,
            "new_skills": self.new_skills,
            "diary": self.diary,
            "consolidation": self.consolidation,
            "anticipations": self.anticipations,
        }

    def summary_line(self) -> str:
        """One deterministic, speakable line for the morning digest."""
        parts = []
        if self.new_skills:
            names = ", ".join(s["name"] for s in self.new_skills[:3])
            extra = len(self.new_skills) - 3
            parts.append(f"{len(self.new_skills)} new draft skill(s) "
                         f"awaiting review: {names}"
                         + (f" and {extra} more" if extra > 0 else ""))
        if self.diary is not None:
            parts.append(f"diary for {self.diary_day} written "
                         f"({self.diary.get('episodes', 0)} episodes)")
        if self.consolidation is not None:
            c = self.consolidation
            moved = sum(c.get(k, 0) for k in
                        ("expired", "deduped", "promoted", "decayed"))
            if moved:
                parts.append(f"memory consolidated ({moved} facts "
                             f"touched)")
        if self.failed_steps:
            parts.append("failed step(s): " + ", ".join(self.failed_steps))
        if not parts:
            return "Night review: nothing new."
        return "Night review: " + "; ".join(parts) + "."


def _step(fn) -> dict:
    """Run one review step, isolating its failure into the step record."""
    try:
        return {"ok": True, "detail": fn(), "error": None}
    except Exception as exc:  # isolation is the contract — never raise
        return {"ok": False, "detail": None,
                "error": f"{type(exc).__name__}: {exc}"}


# -------------------------------------------------------------------- steps

def _step_foundry(foundry, report: ReviewReport) -> dict:
    created = foundry.draft_skills()
    report.new_skills = created
    return {"drafted": len(created),
            "names": [d["name"] for d in created]}


def _step_diary(session_store, memory, diary_day: str,
                report: ReviewReport) -> dict:
    db_path = str(getattr(session_store, "db_path", session_store))
    events = _events_for_day(db_path, diary_day)
    result = memory.write_diary_entry(diary_day, events)
    value = result.get("value", "")
    if not _lesson_is_safe(value):
        # Anti-poisoning enforcement: write_diary_entry fuses compose +
        # store, so a rejected lesson is removed again immediately and
        # the step reports the rejection — poison never stays stored.
        removed = False
        try:
            memory.forget(f"diary:{diary_day}")
            removed = True
        except Exception:
            removed = False
        raise ValueError(
            "diary lesson rejected by anti-poisoning filter "
            f"(stored fact removed: {removed})")
    report.diary = result
    return {"day": diary_day, "episodes": result.get("episodes", 0),
            "events_used": len(events), "lesson_check": "passed"}


def _step_consolidate(memory, now: datetime,
                      report: ReviewReport) -> dict:
    counts = memory.consolidate(now_iso=now.isoformat())
    report.consolidation = counts
    return counts


def _step_anticipation(foundry, now: datetime, evo_dir: Path,
                       report: ReviewReport) -> dict:
    snapshot = foundry.anticipations(now)
    report.anticipations = snapshot
    line = json.dumps({"ts": now.isoformat(), "anticipations": snapshot},
                      ensure_ascii=False)
    if rotate_numbered is not None:
        # Team 19 E2: the snapshots log rotates on the shared budget
        # (10 MB x 5) instead of growing forever.
        rotate_numbered(evo_dir / _SNAPSHOTS_NAME)
    with open(evo_dir / _SNAPSHOTS_NAME, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    return {"count": len(snapshot)}


# -------------------------------------------------------------------- entry

def run_review(data_dir, session_store, memory,
               now: datetime | None = None) -> ReviewReport:
    """Run one full idle review cycle. Never raises; never interrupts.

    data_dir: the JARVIS data dir (foundry drafts + evolution state
    live under it). session_store: a SessionStore (or its db path).
    memory: a Memory instance. now: injected clock (tests); defaults
    to the real UTC clock. Returns the ReviewReport; the same data is
    persisted to <data_dir>/evolution/last_review.json.
    """
    now = _as_utc(now) or datetime.now(timezone.utc)
    data_path = Path(data_dir)
    evo_dir = data_path / EVOLUTION_DIRNAME
    report = ReviewReport(
        day=now.strftime("%Y-%m-%d"),
        diary_day=(now - timedelta(days=1)).strftime("%Y-%m-%d"),
        ran_at=now.isoformat(),
    )

    def _foundry():
        from jarvis.skill_foundry import SkillFoundry
        return SkillFoundry(session_store, data_path)

    report.steps["foundry"] = _step(
        lambda: _step_foundry(_foundry(), report))
    report.steps["diary"] = _step(
        lambda: _step_diary(session_store, memory, report.diary_day,
                            report))
    report.steps["consolidate"] = _step(
        lambda: _step_consolidate(memory, now, report))
    report.steps["anticipation"] = _step(
        lambda: _step_anticipation(_foundry(), now, _ensure_dir(evo_dir),
                                   report))

    # Persist the report itself (digest reads it from disk). Marked ok
    # optimistically in the serialized copy — if the write raises, the
    # returned report corrects the record (the disk copy then simply
    # stays stale/absent, which read_last_run tolerates).
    report.steps["persist"] = {"ok": True, "detail": None, "error": None}
    try:
        _ensure_dir(evo_dir)
        _atomic_write(evo_dir / _REPORT_NAME,
                      json.dumps(report.to_dict(), indent=2,
                                 ensure_ascii=False))
        report.steps["persist"]["detail"] = {
            "path": str(evo_dir / _REPORT_NAME)}
    except Exception as exc:  # persistence must never break the cycle
        report.steps["persist"] = {
            "ok": False, "detail": None,
            "error": f"{type(exc).__name__}: {exc}"}
    return report


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------- scheduling

def should_run(last_run, now, idle_seconds: int = DEFAULT_IDLE_SECONDS,
               last_user_turn=None) -> bool:
    """Deterministic gate for the idle review cycle.

    True iff BOTH:
    - once-per-day: `last_run` is None or on an earlier UTC day than
      `now` (a future last_run — clock skew — also blocks), and
    - idle: `last_user_turn` is None (no user turn ever recorded —
      nothing to interrupt) or at least `idle_seconds` before `now`.

    Accepts datetimes or ISO strings; naive values are read as UTC.
    """
    now = _as_utc(now)
    if now is None:
        return False
    last = _as_utc(last_run)
    if last is not None and last.date() >= now.date():
        return False
    turn = _as_utc(last_user_turn)
    if turn is not None and (now - turn).total_seconds() < idle_seconds:
        return False
    return True


def read_last_run(data_dir) -> datetime | None:
    """When the last review ran, from the persisted report (or None)."""
    path = Path(data_dir) / EVOLUTION_DIRNAME / _REPORT_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return _as_utc(data.get("ran_at"))


def last_user_turn_at(session_store) -> datetime | None:
    """Timestamp of the most recent user.message in the session store.

    Read-only; None when there is no user turn or the store cannot be
    read (a missing history means nothing to interrupt, so the idle
    gate treats it as idle rather than blocking the review forever).
    """
    db_path = str(getattr(session_store, "db_path", session_store))
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT MAX(ts) FROM events WHERE type = 'user.message'"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return _as_utc(row[0]) if row else None
