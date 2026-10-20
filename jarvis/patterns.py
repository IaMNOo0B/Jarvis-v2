"""Patterns — confirmed-pattern memory (Analytics Team).

The piece the whole quantified-self field is missing (Team 30 scan):
nobody closes the loop derive -> propose pattern -> owner confirms ->
remember forever. Dawarich does it for places only; v2's own
skill_foundry.anticipations() emits raw frequencies with no
confirm/decline memory, so the same guesses would surface forever.
This module is the general fix.

DERIVATION (deterministic counting, mirroring skill_foundry): a tool
call counts only when it actually executed (gate verdict allow /
allow_with_undo, not a proposal, not a denial) AND a causally linked
tool.result reports ok=True. Counts are bucketed by (tool, UTC hour)
with the set of distinct UTC days tracked alongside.

THRESHOLDS — a pattern claim is a HABIT claim, and habits need
cross-day evidence:
  MIN_PATTERN_COUNT = 4 occurrences inside one (tool, hour) bucket
  MIN_PATTERN_DAYS  = 3 distinct days contributing to that bucket
One busy afternoon can never mint a pattern (3 days), and one polite
visit per day is not enough either (3 days x 1 = 3 < 4 — the fourth
occurrence forces a repeat). Thresholds err high on purpose: every
suggestion costs the owner exactly one decision, once, forever —
a declined pattern is NEVER suggested again — so suggestions must be
worth that decision.

LIFECYCLE (Dawarich): suggested -> confirmed / declined.
  confirm -> status "confirmed"; if a Memory is attached, the pattern
             is written as a semantic fact (source "patterns",
             tier "user" — the owner stated it) via memory.write_fact.
  decline -> status "declined" AND a durable suppression key. The key
             lives in patterns.json (restart-proof by construction)
             and is mirrored into proactivity's SuppressionStore when
             importable (Team 14's dismissal-is-forever shape), so the
             ring gate sees it too.

API only: nothing here rings, speaks, or renders UI.

Persistence: <data_dir>/patterns.json, atomic writes (tmp + replace),
one record per pattern key "pattern:<tool>@<HH>".

Stdlib only: json, re, sqlite-free, collections, datetime, pathlib.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "MIN_PATTERN_COUNT",
    "MIN_PATTERN_DAYS",
    "Proposal",
    "PatternStore",
    "propose_patterns",
    "pattern_key",
]

#: Occurrences inside one (tool, hour) bucket before it can be proposed.
MIN_PATTERN_COUNT = 4
#: Distinct days that must contribute to the bucket. A habit claim
#: needs cross-day evidence; a single busy day never qualifies.
MIN_PATTERN_DAYS = 3

_EXECUTED_VERDICTS = ("allow", "allow_with_undo")
_SOURCE = "patterns"


def pattern_key(tool: str, hour: int) -> str:
    """The stable identity of one pattern: 'pattern:<tool>@<HH>'."""
    return f"pattern:{tool}@{hour:02d}"


@dataclass(frozen=True)
class Proposal:
    """One candidate pattern, derived deterministically from events."""
    key: str        # pattern:<tool>@<HH>
    tool: str
    hour: int       # UTC hour-of-day bucket, 0..23
    count: int      # successful occurrences inside the bucket
    days: int       # distinct UTC days contributing
    text: str       # speakable one-liner; also the memory fact value

    def to_dict(self) -> dict:
        return {"key": self.key, "tool": self.tool, "hour": self.hour,
                "count": self.count, "days": self.days, "text": self.text}


def _proposal_text(tool: str, hour: int, count: int, days: int) -> str:
    return (f"You often use {tool} around {hour:02d}:00 "
            f"({count} times over {days} days).")


def _confidence(count: int, days: int) -> float:
    """Deterministic fact confidence for a confirmed pattern: 0.80 at
    threshold, +0.02 per extra occurrence, +0.03 per extra day,
    capped at 0.95."""
    conf = (0.80
            + 0.02 * max(0, count - MIN_PATTERN_COUNT)
            + 0.03 * max(0, days - MIN_PATTERN_DAYS))
    return round(min(0.95, conf), 2)


# --------------------------------------------------------------------------- #
# Derivation — pure: events in, proposals out
# --------------------------------------------------------------------------- #

def _ts_parts(ts) -> tuple[int, str] | None:
    """ISO timestamp -> (UTC hour, 'YYYY-MM-DD') or None if unparseable."""
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.hour, dt.date().isoformat()


def _successful_tool_events(store_events) -> list[tuple[str, int, str]]:
    """(tool, hour, day) per successful tool call, skill_foundry rules:
    executed + gate-allowed + a linked tool.result with ok=True."""
    ok_calls: set[str] = set()
    for ev in store_events:
        if ev.get("type") != "tool.result":
            continue
        payload = ev.get("payload") or {}
        if payload.get("ok") is True:
            if ev.get("causal_parent"):
                ok_calls.add(ev["causal_parent"])
            ref = payload.get("call_ref")
            if ref:
                ok_calls.add(ref)
    out: list[tuple[str, int, str]] = []
    for ev in store_events:
        if ev.get("type") != "tool.call":
            continue
        payload = ev.get("payload") or {}
        if payload.get("executed", True) is False:
            continue  # a proposal that never ran
        if payload.get("gate_verdict", "allow") not in _EXECUTED_VERDICTS:
            continue  # denied or approval-pending
        if ev.get("event_id") not in ok_calls:
            continue  # no successful result linked
        tool = payload.get("tool")
        if not isinstance(tool, str) or not tool:
            continue
        parts = _ts_parts(ev.get("ts"))
        if parts is None:
            continue
        out.append((tool, parts[0], parts[1]))
    return out


def _existing_keys(existing) -> set[str]:
    """Normalise `existing` (Proposals, dicts, or bare keys) to keys."""
    keys: set[str] = set()
    for item in existing or ():
        if isinstance(item, str):
            keys.add(item)
        elif isinstance(item, Proposal):
            keys.add(item.key)
        elif isinstance(item, dict) and item.get("key"):
            keys.add(str(item["key"]))
    return keys


def propose_patterns(store_events, existing=(), *,
                     min_count: int = MIN_PATTERN_COUNT,
                     min_days: int = MIN_PATTERN_DAYS) -> list[Proposal]:
    """Candidate patterns in `store_events` not already in `existing`.

    A (tool, hour) bucket is proposed iff it holds >= min_count
    successful calls spread over >= min_days distinct days. `existing`
    is anything the system already knows — suggested, confirmed, or
    declined proposals, in Proposal/dict/key form — and is excluded:
    a pattern is proposed at most once in its life.

    Sorted by (-count, -days, tool, hour): strongest evidence first,
    fully deterministic.
    """
    known = _existing_keys(existing)
    counts: Counter = Counter()
    days_of: dict[tuple, set] = {}
    for tool, hour, day in _successful_tool_events(store_events):
        bucket = (tool, hour)
        counts[bucket] += 1
        days_of.setdefault(bucket, set()).add(day)
    out: list[Proposal] = []
    for (tool, hour), n in counts.items():
        days = len(days_of[(tool, hour)])
        if n < min_count or days < min_days:
            continue
        key = pattern_key(tool, hour)
        if key in known:
            continue
        out.append(Proposal(key=key, tool=tool, hour=hour, count=n,
                            days=days,
                            text=_proposal_text(tool, hour, n, days)))
    out.sort(key=lambda p: (-p.count, -p.days, p.tool, p.hour))
    return out


# --------------------------------------------------------------------------- #
# Persistence + lifecycle
# --------------------------------------------------------------------------- #

def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class PatternStore:
    """Pattern proposals + their lifecycle, persisted in patterns.json.

    State file: {"proposals": {key: record}, "suppressed": [key]}.
    A record is the Proposal fields plus "status"
    (suggested/confirmed/declined) and "updated_ts". The suppressed
    list is the durable never-again set: keys enter it on decline and
    are consulted before any proposal is minted — a declined pattern
    cannot return even if later evidence is stronger, and even across
    restarts (a fresh PatternStore over the same data dir sees it).
    """

    def __init__(self, data_dir, memory=None) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._path = self.data_dir / "patterns.json"
        self._memory = memory

    # -- persistence ----------------------------------------------------- #
    def _load(self) -> dict:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"proposals": {}, "suppressed": []}
        if not isinstance(data, dict):
            return {"proposals": {}, "suppressed": []}
        if not isinstance(data.get("proposals"), dict):
            data["proposals"] = {}
        if not isinstance(data.get("suppressed"), list):
            data["suppressed"] = []
        return data

    def _save(self, state: dict) -> None:
        _atomic_write(self._path,
                      json.dumps(state, indent=2, ensure_ascii=False))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # -- reads ----------------------------------------------------------- #
    def all(self) -> list[dict]:
        """Every stored proposal record, sorted by key."""
        state = self._load()
        return [state["proposals"][k] for k in sorted(state["proposals"])]

    def pending(self) -> list[dict]:
        """Records still awaiting the owner's decision."""
        return [r for r in self.all() if r.get("status") == "suggested"]

    def get(self, key: str) -> dict | None:
        return self._load()["proposals"].get(key)

    def suppressed_keys(self) -> set[str]:
        return set(self._load().get("suppressed", []))

    def is_suppressed(self, key: str) -> bool:
        if key in self.suppressed_keys():
            return True
        rec = self.get(key)
        return bool(rec and rec.get("status") == "declined")

    # -- suggestion ------------------------------------------------------ #
    def suggest(self, store_events, *,
                min_count: int = MIN_PATTERN_COUNT,
                min_days: int = MIN_PATTERN_DAYS) -> list[Proposal]:
        """Derive + persist new proposals as "suggested". Idempotent:
        anything already known — suggested, confirmed, declined, or
        suppression-listed — is never minted (again)."""
        state = self._load()
        known = set(state["proposals"]) | set(state["suppressed"])
        fresh = propose_patterns(store_events, existing=known,
                                 min_count=min_count, min_days=min_days)
        fresh = [p for p in fresh
                 if not self._mirror_suppressed(p.tool, p.hour)]
        if fresh:
            now = self._now()
            for p in fresh:
                rec = p.to_dict()
                rec.update({"status": "suggested", "updated_ts": now})
                state["proposals"][p.key] = rec
            self._save(state)
        return fresh

    # -- lifecycle ------------------------------------------------------- #
    def confirm(self, key: str, memory=None) -> dict:
        """suggested -> confirmed, and into semantic memory.

        With a Memory attached (constructor or this call), the pattern
        becomes a fact via write_fact — key = the pattern key, value =
        the pattern text, source "patterns", tier "user" (the owner
        stated it), confidence derived from the evidence. Returns
        {"key", "status", "fact"} where fact is write_fact's result
        (None when no Memory is attached). Raises KeyError for an
        unknown key, ValueError for a declined one (clear the
        suppression first — declining is forever until the owner
        deliberately un-declines).
        """
        state = self._load()
        rec = state["proposals"].get(key)
        if rec is None:
            raise KeyError(f"unknown pattern: {key!r}")
        if rec.get("status") == "declined":
            raise ValueError(
                f"pattern {key!r} was declined; it cannot be confirmed")
        rec["status"] = "confirmed"
        rec["updated_ts"] = self._now()
        self._save(state)
        fact = None
        mem = memory if memory is not None else self._memory
        if mem is not None:
            fact = mem.write_fact(
                key=key, value=rec["text"], source=_SOURCE, tier="user",
                confidence=_confidence(rec["count"], rec["days"]))
        return {"key": key, "status": "confirmed", "fact": fact}

    def decline(self, key: str) -> dict:
        """suggested/confirmed -> declined, forever.

        Writes the durable suppression key (patterns.json suppressed
        list) and mirrors it into proactivity's SuppressionStore when
        importable, in Team 14's shape: source "patterns", item shape
        the pattern key. Raises KeyError for an unknown key.
        """
        state = self._load()
        rec = state["proposals"].get(key)
        if rec is None:
            raise KeyError(f"unknown pattern: {key!r}")
        rec["status"] = "declined"
        rec["updated_ts"] = self._now()
        suppressed = state.setdefault("suppressed", [])
        if key not in suppressed:
            suppressed.append(key)
        self._save(state)
        mirrored = self._mirror_record(rec)
        return {"key": key, "status": "declined", "suppressed": True,
                "mirrored": mirrored}

    # -- proactivity suppression mirror (best-effort, no hard dep) ------ #
    @staticmethod
    def _mirror_item(rec: dict) -> dict:
        # item_shape() uses a dict's explicit "shape": the pattern key
        # itself, so "anything like this pattern" is what gets silenced.
        return {"shape": rec["key"]}

    def _mirror_record(self, rec: dict) -> bool:
        try:
            from jarvis.proactivity import SuppressionStore
        except ImportError:
            return False
        try:
            SuppressionStore(str(self.data_dir)).record(
                _SOURCE, self._mirror_item(rec), "dismissed")
            return True
        except Exception:
            return False  # the local suppressed list already guarantees it

    def _mirror_suppressed(self, tool: str, hour: int) -> bool:
        try:
            from jarvis.proactivity import SuppressionStore
        except ImportError:
            return False
        try:
            item = {"shape": pattern_key(tool, hour)}
            return SuppressionStore(str(self.data_dir)).is_suppressed(
                _SOURCE, item)
        except Exception:
            return False
