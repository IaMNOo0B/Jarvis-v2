"""JARVIS v2 — the snapshot-diff layer for briefings: diff before you speak.

Pattern (Team 14 mega-scan, code-evidenced in two independent systems:
coleam00/second-brain-starter's heartbeat `diff_snapshot` and Anthropic's
daily-brief run protocol): a periodic briefing that re-reports the same
items every cycle becomes noise and dies. Only DELTAS may be reported.

Protocol per run (mirrors the Anthropic run book):
  gather -> diff against the ledger -> verify each new item is still
  live -> compose under a line cap -> deliver -> ONLY THEN commit:
  delivered items are marked reported and cursors advance.

Failure honesty is structural:
  - A source that fails (returns None, or its gather callable raises) is
    reported as UNREADABLE — never as "nothing new". Blanks are never
    filled in.
  - Items are marked reported only on commit, and commit happens only
    after the caller confirms delivery. A failed delivery re-diffs the
    same items next run instead of losing them.
  - An item that fails the live check is skipped for this run and NOT
    marked reported — it was never delivered, so it must not retire.

State is one small file, briefing_state.json:
  {"sources": {name: {"cursor": str | None}},
   "reported": [item keys, oldest first, capped],
   "updated_ts": float}

Relationship to morning_digest.py: that module composes today's fixed
sections and stays exactly as it is. This module is the delta layer a
caller wraps AROUND any item-producing sources (reminders, watcher
completions, store snapshots) so JARVIS never says the same thing twice.

Python 3.11+, stdlib only. Deterministic; no LLM, no network.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field

from .proactivity import _atomic_write_json, _read_json

#: Cap on the reported-items ledger; oldest keys retire first. The cap
#: keeps the state file small forever; an item older than the cap may
#: be reported once more — an accepted, documented trade-off.
MAX_REPORTED = 1000

#: Default speakable-line cap for one composed briefing.
DEFAULT_LINE_CAP = 8


# --------------------------------------------------------------------------- #
# Item identity — EXACT identity (this item, not this shape of item).
# (Shape-based identity — "anything like this" — is the suppression
# store's job, in proactivity.py. The two are deliberately different.)
# --------------------------------------------------------------------------- #

def item_key(source: str, item: dict) -> str:
    """Stable exact key for one item from one source."""
    if isinstance(item, dict):
        for field_name in ("id", "key", "uid"):
            value = item.get(field_name)
            if value is not None and str(value) != "":
                return f"{source}:{value}"
        canonical = json.dumps(item, sort_keys=True, ensure_ascii=False,
                               default=str)
    else:
        canonical = str(item)
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{source}:{digest}"


def _item_title(item: dict) -> str:
    if isinstance(item, dict):
        for field_name in ("title", "text", "summary", "name"):
            value = item.get(field_name)
            if value:
                return str(value).strip()
    return str(item).strip()


# --------------------------------------------------------------------------- #
# Ledger state
# --------------------------------------------------------------------------- #

class BriefingState:
    """The persisted bookmarks + reported-items ledger."""

    def __init__(self, data_dir: str, time_fn=None) -> None:
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._path = os.path.join(data_dir, "briefing_state.json")
        self._time = time_fn or time.time

    # -- persistence ---------------------------------------------------- #
    def _load(self) -> dict:
        state = _read_json(self._path, {"sources": {}, "reported": []})
        if not isinstance(state.get("sources"), dict):
            state["sources"] = {}
        if not isinstance(state.get("reported"), list):
            state["reported"] = []
        return state

    def _save(self, state: dict) -> None:
        state["updated_ts"] = self._time()
        _atomic_write_json(self._path, state)

    # -- reads ------------------------------------------------------------ #
    def cursor(self, source: str) -> str | None:
        entry = self._load().get("sources", {}).get(source, {})
        return entry.get("cursor") if isinstance(entry, dict) else None

    def reported_keys(self) -> set[str]:
        return set(self._load().get("reported", []))

    def is_reported(self, source: str, item: dict) -> bool:
        return item_key(source, item) in self.reported_keys()

    # -- the commit (call ONLY after delivery is confirmed) -------------- #
    def commit(self, source: str, items: list[dict],
               cursor: str | None = None) -> None:
        """Mark `items` reported and advance the source's cursor.

        Advancing cursors before delivery is how briefings lose news:
        this is a separate call precisely so the caller cannot do it
        by accident mid-compose.
        """
        state = self._load()
        reported = state.setdefault("reported", [])
        known = set(reported)
        for item in items:
            key = item_key(source, item)
            if key not in known:
                reported.append(key)
                known.add(key)
        if len(reported) > MAX_REPORTED:
            del reported[: len(reported) - MAX_REPORTED]
        sources = state.setdefault("sources", {})
        entry = sources.get(source)
        if not isinstance(entry, dict):
            entry = {}
            sources[source] = entry
        entry["cursor"] = cursor
        entry["last_commit_ts"] = self._time()
        self._save(state)


# --------------------------------------------------------------------------- #
# Diffing
# --------------------------------------------------------------------------- #

@dataclass
class SourceDiff:
    """One source's delta for one run."""
    source: str
    new_items: list[dict] = field(default_factory=list)
    unreadable: bool = False
    cursor: str | None = None   # cursor offered by the gather, if any


def diff_source(state: BriefingState, source: str,
                gathered, verify=None) -> SourceDiff:
    """Diff one source's gathered items against the ledger.

    gathered: a list of item dicts, OR a {"items": [...], "cursor": str}
    dict, OR None when the source failed. Raises are the caller's to
    convert to None (run_digest does).

    verify: optional callable(item) -> bool, the live check. A falsy
    result (or an exception) means the item is stale — it is excluded
    from the delta and NOT marked reported.
    """
    if gathered is None:
        return SourceDiff(source=source, unreadable=True)
    cursor = None
    items = gathered
    if isinstance(gathered, dict):
        cursor = gathered.get("cursor")
        items = gathered.get("items")
        if items is None:
            return SourceDiff(source=source, unreadable=True)
    if not isinstance(items, list):
        return SourceDiff(source=source, unreadable=True)

    already = state.reported_keys()
    new_items: list[dict] = []
    seen_this_run: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            item = {"text": str(item)}
        key = item_key(source, item)
        if key in already or key in seen_this_run:
            continue
        seen_this_run.add(key)
        if verify is not None:
            try:
                live = bool(verify(item))
            except Exception:
                live = False  # can't confirm it lives -> don't speak it
            if not live:
                continue
        new_items.append(item)
    return SourceDiff(source=source, new_items=new_items, cursor=cursor)


# --------------------------------------------------------------------------- #
# One whole briefing run
# --------------------------------------------------------------------------- #

@dataclass
class DigestRun:
    """The composed delta briefing. Nothing is committed yet."""
    diffs: list[SourceDiff]
    lines: list[str]
    state: BriefingState

    @property
    def unreadable(self) -> list[str]:
        return [d.source for d in self.diffs if d.unreadable]

    @property
    def has_news(self) -> bool:
        return any(d.new_items for d in self.diffs)

    def commit_delivery(self) -> None:
        """Mark exactly the delivered new items reported + advance cursors.

        Call ONLY after the lines were actually delivered (rung/spoken/
        posted). Unreadable sources commit nothing and keep their old
        cursor, so their items diff again next run.
        """
        for diff in self.diffs:
            if diff.unreadable:
                continue
            self.state.commit(diff.source, diff.new_items,
                              cursor=diff.cursor)


def run_digest(data_dir: str, sources: dict, *,
               verify: dict | None = None,
               line_cap: int = DEFAULT_LINE_CAP,
               now: float | None = None,
               state: BriefingState | None = None) -> DigestRun:
    """Gather -> diff -> compose. Does NOT commit (see DigestRun).

    sources: {name: callable(cursor) -> gathered}. Each callable gets
    the source's stored cursor and may return a list, a {"items",
    "cursor"} dict, or None. Any exception = that source is unreadable
    this run; the run itself never raises because a source did.

    verify: optional {source: callable(item) -> bool} live checks.

    Lines: one per source with news ('name: 2 new — title; title'),
    one per unreadable source ('name: unreadable right now'), composed
    under `line_cap` lines total.
    """
    state = state or BriefingState(
        data_dir, time_fn=(lambda: now) if now is not None else None)
    verify = verify or {}
    diffs: list[SourceDiff] = []
    for name, gather in sources.items():
        try:
            gathered = gather(state.cursor(name))
        except Exception:
            gathered = None  # a failed source is unreadable, not empty
        diffs.append(diff_source(state, name, gathered,
                                 verify=verify.get(name)))

    lines: list[str] = []
    for diff in diffs:
        if diff.unreadable:
            lines.append(f"{diff.source}: unreadable right now.")
        elif diff.new_items:
            titles = [_item_title(i) for i in diff.new_items[:3]]
            titles = [t for t in titles if t]
            line = (f"{diff.source}: {len(diff.new_items)} new"
                    + (f" — {'; '.join(titles)}" if titles else ""))
            lines.append(line + ".")
    if len(lines) > line_cap:
        extra = len(lines) - line_cap
        lines = lines[:line_cap] + [f"And {extra} more update"
                                    f"{'s' if extra != 1 else ''}."]
    return DigestRun(diffs=diffs, lines=lines, state=state)
