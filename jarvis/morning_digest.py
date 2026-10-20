"""JARVIS v2 — the morning digest: a deterministic briefing, no LLM.

Pattern (ideas only) from OpenJarvis: a digest is a *preset over generic
machinery* — collectors read existing stores, a composer assembles short
speakable lines. v2's composer needs no model at all: every section here
is arithmetic over stores JARVIS already owns.

Sections (each independent; a missing/broken store skips ONLY its section):
  - reminders due today      <- reminders.json (skills/reminders format:
                                a list of {id, due(epoch), text}; the
                                proactivity ReminderStore dict format
                                {"reminders": {id: {when_ts, text}}} is
                                also understood)
  - yesterday's session stats <- sessions.db (session_store SQLite, read-only)
  - pending approvals count  <- injected count, or pending_approvals.json
  - disk free                <- shutil.disk_usage

Hard guarantees:
  - NO LLM call, NO network call. Pure stdlib reads.
  - build_digest NEVER raises. The morning must not crash because one
    store is corrupt; the corrupt section is silently skipped.
  - Deterministic: same stores + same `now` -> identical output.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from datetime import datetime, timezone

#: Event types that count as conversation in yesterday's stats.
_USER_EVENT = "user.message"
_REPLY_EVENT = "brain.reply"


# --------------------------------------------------------------------------- #
# Section collectors — each returns None (or []) when its store is absent.
# --------------------------------------------------------------------------- #

def _local_day_bounds(now: float) -> tuple[float, float]:
    """[start, end) epoch bounds of the local calendar day containing now."""
    lt = time.localtime(now)
    start = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                         0, 0, 0, 0, 0, -1))
    return start, start + 86400.0


def _reminders_today(data_dir: str, now: float) -> list[dict]:
    """Reminders whose due time falls on today's local date.

    Silent [] on any problem: file missing, unparseable, wrong shape.
    """
    path = os.path.join(data_dir, "reminders.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    start, end = _local_day_bounds(now)
    out: list[dict] = []
    items: list[dict] = []
    if isinstance(data, list):
        items = [i for i in data if isinstance(i, dict)]
        for i in items:
            due = i.get("due")
            if isinstance(due, (int, float)) and start <= due < end:
                out.append({"text": str(i.get("text", "")).strip(),
                            "due": float(due)})
    elif isinstance(data, dict):
        # proactivity.ReminderStore shape: {"reminders": {id: {...}}}
        inner = data.get("reminders")
        if isinstance(inner, dict):
            for i in inner.values():
                if not isinstance(i, dict) or i.get("fired"):
                    continue
                due = i.get("when_ts")
                if isinstance(due, (int, float)) and start <= due < end:
                    out.append({"text": str(i.get("text", "")).strip(),
                                "due": float(due)})
    out = [r for r in out if r["text"]]
    out.sort(key=lambda r: r["due"])
    return out


def _yesterday_stats(data_dir: str, now: float) -> dict | None:
    """Diary-worthy counts for yesterday (local date) from sessions.db.

    Read-only SQLite connection: the digest never writes to, or locks
    for writing, the live session store. None when the DB is absent or
    has no activity yesterday.
    """
    path = os.path.join(data_dir, "sessions.db")
    if not os.path.exists(path):
        return None
    start, end = _local_day_bounds(now - 86400.0)
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        rows = conn.execute(
            "SELECT ts, session_id, type FROM events").fetchall()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    sessions: set[str] = set()
    events = user_messages = replies = 0
    for ts_raw, session_id, type_ in rows:
        try:
            ts = datetime.fromisoformat(str(ts_raw))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            epoch = ts.timestamp()
        except (ValueError, OverflowError, OSError):
            continue
        if not (start <= epoch < end):
            continue
        events += 1
        sessions.add(str(session_id))
        if type_ == _USER_EVENT:
            user_messages += 1
        elif type_ == _REPLY_EVENT:
            replies += 1
    if events == 0:
        return None
    return {"sessions": len(sessions), "events": events,
            "user_messages": user_messages, "replies": replies}


def _pending_approvals(data_dir: str,
                       injected: int | list | None) -> int | None:
    """Pending approvals count, or None when unknown (section skipped).

    Priority: an explicitly injected count/list (the caller knows its
    live queue), then a persisted pending_approvals.json (a list, or a
    dict with a 'pending'/'requests' list). Never guessed.
    """
    if isinstance(injected, int):
        return max(0, injected)
    if isinstance(injected, (list, tuple)):
        return len(injected)
    path = os.path.join(data_dir, "pending_approvals.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("pending", "requests"):
            if isinstance(data.get(key), list):
                return len(data[key])
    return None


def _disk(data_dir: str) -> dict | None:
    try:
        usage = shutil.disk_usage(data_dir if os.path.isdir(data_dir)
                                  else os.path.expanduser("~"))
    except OSError:
        return None
    if usage.total <= 0:
        return None
    return {"total_gb": round(usage.total / 1e9, 1),
            "free_gb": round(usage.free / 1e9, 1),
            "free_pct": round(100.0 * usage.free / usage.total)}


# --------------------------------------------------------------------------- #
# Composer
# --------------------------------------------------------------------------- #

def build_digest(data_dir: str, *, now: float | None = None,
                 pending_approvals: int | list | None = None) -> dict:
    """Compose the morning briefing dict. NEVER raises.

    Returns {"date", "lines", "reminders_today", "yesterday",
    "pending_approvals", "disk"}. Skipped sections are None (or []
    for reminders) and contribute no line.
    """
    now = time.time() if now is None else float(now)
    lt = time.localtime(now)
    date_str = time.strftime("%Y-%m-%d", lt)
    lines: list[str] = [
        "Good morning, sir. "
        + time.strftime("%A, %d %B", lt).lstrip("0").replace(" 0", " ") + "."
    ]

    reminders: list[dict] = []
    try:
        reminders = _reminders_today(data_dir, now)
    except Exception:
        reminders = []
    if reminders:
        shown = reminders[:5]
        parts = [f"{time.strftime('%H:%M', time.localtime(r['due']))} "
                 f"{r['text']}" for r in shown]
        line = (f"{len(reminders)} reminder"
                f"{'s' if len(reminders) != 1 else ''} today: "
                + "; ".join(parts))
        if len(reminders) > len(shown):
            line += f"; and {len(reminders) - len(shown)} more"
        lines.append(line + ".")

    yesterday: dict | None = None
    try:
        yesterday = _yesterday_stats(data_dir, now)
    except Exception:
        yesterday = None
    if yesterday:
        lines.append(
            f"Yesterday: {yesterday['sessions']} session"
            f"{'s' if yesterday['sessions'] != 1 else ''}, "
            f"{yesterday['user_messages']} messages from you, "
            f"{yesterday['replies']} replies from me.")

    pending: int | None = None
    try:
        pending = _pending_approvals(data_dir, pending_approvals)
    except Exception:
        pending = None
    if pending:
        lines.append(f"{pending} approval"
                     f"{'s are' if pending != 1 else ' is'} "
                     f"waiting for you.")

    disk: dict | None = None
    try:
        disk = _disk(data_dir)
    except Exception:
        disk = None
    if disk is not None:
        if disk["free_pct"] < 10:
            lines.append(f"Warning, sir: disk is almost full — "
                         f"only {disk['free_pct']} percent free.")
        else:
            lines.append(f"Disk is {disk['free_pct']} percent free.")

    return {"date": date_str, "lines": lines,
            "reminders_today": reminders, "yesterday": yesterday,
            "pending_approvals": pending, "disk": disk}


def digest_lines(data_dir: str, *, now: float | None = None,
                 pending_approvals: int | list | None = None) -> list[str]:
    """Just the speakable lines of build_digest()."""
    return build_digest(data_dir, now=now,
                        pending_approvals=pending_approvals)["lines"]
