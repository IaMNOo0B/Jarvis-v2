"""Skill Foundry — self-learning from JARVIS's own session logs (Builder D).

Nolan pattern ("skill solidification" + "statistical anticipation"), our
code, deterministic throughout — NO LLM is consulted anywhere in this file.
Counting is the whole trick, and counting never hallucinates.

Two jobs:

1. Solidification. Scan the session-store event log for tool-call sequences
   (length 2-4) that SUCCEEDED at least MIN_REPEATS times and freeze each
   one into a draft skill package under <data_dir>/foundry/<name>/:
   skill.json (a manifest in jarvis.skills.registry format), foundry.json
   (provenance sidecar), SKILL.md (owner review note). Drafts are
   QUARANTINED BY LOCATION: the foundry dir is not a registry discovery
   path, nothing here can execute, and a draft becomes real only when the
   owner reviews it and moves it into skills/ for the normal registry
   quarantine + approve() flow. NEVER auto-approved — there is no code
   path in this module that approves anything.

2. Anticipation. Per-hour frequencies of successful tool calls (and user
   messages) from the same log. anticipations(now) returns the likely
   actions for now's hour-of-day with counts — DATA ONLY. Nothing acts on
   it here; a consumer (proactivity) may read it later.

"Successful" is strict: a tool.call event counts only when it actually
executed (gate verdict allow/allow_with_undo, not a require_approval
proposal, not a denial) AND a tool.result linked to it (causal_parent or
payload.call_ref) reports ok=True. Tombstoned payloads ('{}') never count.

Stdlib only: sqlite3, json, collections, datetime, pathlib, re.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

MIN_REPEATS = 3
MIN_SEQ_LEN = 2
MAX_SEQ_LEN = 4
_NAME_MAX = 64
_EXECUTED_VERDICTS = ("allow", "allow_with_undo")


def _slug(tool_name: str) -> str:
    """Tool name -> manifest-safe fragment (^[a-z0-9_]+$)."""
    return re.sub(r"[^a-z0-9]+", "_", tool_name.lower()).strip("_") or "tool"


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class SkillFoundry:
    """Reads a SessionStore database (read-only) + a data dir for drafts."""

    def __init__(self, store, data_dir) -> None:
        # `store` is a SessionStore (uses its .db_path) or a path to one.
        self.db_path = str(getattr(store, "db_path", store))
        self.data_dir = Path(data_dir)
        self.foundry_dir = self.data_dir / "foundry"

    # ------------------------------------------------------------- log reads

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _payload(row) -> dict:
        try:
            data = json.loads(row["payload"])
        except (ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _successful_streams(self) -> dict[str, list[str]]:
        """session_id -> ordered tool names of successful calls only."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT event_id, session_id, seq, type, causal_parent,"
                " payload FROM events"
                " WHERE type IN ('tool.call', 'tool.result')"
                " ORDER BY session_id, seq"
            ).fetchall()
        finally:
            conn.close()
        ok_calls: set[str] = set()
        for row in rows:
            if row["type"] != "tool.result":
                continue
            payload = self._payload(row)
            if payload.get("ok") is True:
                if row["causal_parent"]:
                    ok_calls.add(row["causal_parent"])
                ref = payload.get("call_ref")
                if ref:
                    ok_calls.add(ref)
        streams: dict[str, list[str]] = {}
        for row in rows:
            if row["type"] != "tool.call":
                continue
            payload = self._payload(row)
            if payload.get("executed", True) is False:
                continue  # a proposal that never ran
            if payload.get("gate_verdict", "allow") not in _EXECUTED_VERDICTS:
                continue  # denied or approval-pending
            if row["event_id"] not in ok_calls:
                continue  # no successful result linked
            name = payload.get("tool")
            if isinstance(name, str) and name:
                streams.setdefault(row["session_id"], []).append(name)
        return streams

    # ------------------------------------------------------- solidification

    def find_sequences(self, min_repeats: int = MIN_REPEATS,
                       min_len: int = MIN_SEQ_LEN,
                       max_len: int = MAX_SEQ_LEN) -> list[dict]:
        """Tool sequences of length min_len..max_len seen >= min_repeats.

        Every occurrence is a contiguous window inside ONE session's
        successful-call stream. A sequence is dropped when a longer
        qualifying sequence contains it contiguously with the SAME count
        (it adds no information beyond the longer pattern). Order:
        (-count, -length, sequence) — deterministic.
        """
        streams = self._successful_streams()
        counts: Counter = Counter()
        sessions_of: dict[tuple, set] = {}
        for session_id, tools in streams.items():
            for length in range(min_len, max_len + 1):
                for i in range(len(tools) - length + 1):
                    seq = tuple(tools[i:i + length])
                    counts[seq] += 1
                    sessions_of.setdefault(seq, set()).add(session_id)
        candidates = {seq: n for seq, n in counts.items() if n >= min_repeats}

        def _contained(short: tuple, long: tuple) -> bool:
            return any(long[i:i + len(short)] == short
                       for i in range(len(long) - len(short) + 1))

        result = []
        for seq, n in candidates.items():
            subsumed = any(
                len(other) > len(seq) and counts[other] == n
                and _contained(seq, other)
                for other in candidates
            )
            if subsumed:
                continue
            result.append({"sequence": list(seq), "count": n,
                           "sessions": len(sessions_of[seq])})
        result.sort(key=lambda d: (-d["count"], -len(d["sequence"]),
                                   d["sequence"]))
        return result

    def _drafted_sequences(self) -> set[tuple]:
        """Sequences already drafted (from sidecars) — drafting is idempotent."""
        done: set[tuple] = set()
        if self.foundry_dir.is_dir():
            for sidecar in self.foundry_dir.glob("*/foundry.json"):
                try:
                    data = json.loads(sidecar.read_text(encoding="utf-8"))
                    done.add(tuple(data["sequence"]))
                except (ValueError, KeyError, OSError):
                    continue
        return done

    @staticmethod
    def _manifest(name: str, sequence: list[str], count: int) -> dict:
        routine = " -> ".join(sequence)
        tool_name = ("replay_" + "_".join(_slug(t) for t in sequence))
        tool_name = tool_name[:_NAME_MAX].rstrip("_")
        return {
            "name": name,
            "version": "0.1.0",
            "description": (
                f"Foundry draft (QUARANTINED - not approved): replays the "
                f"routine {routine}. Seen {count} times in the session "
                f"log, every run succeeded. Solidified by skill_foundry; "
                f"review before approving."
            ),
            "capabilities": [],
            "tools": [{
                "name": tool_name,
                "description": (
                    f"Replay the solidified routine: {routine}. One shared "
                    f"args object is passed to each step."
                ),
                "tier": 2,
                "capabilities": [],
                "timeout_s": 30,
                "output_cap_chars": 10240,
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "args": {
                            "type": "object",
                            "description": "Arguments object passed to "
                                           "each step of the routine.",
                        },
                    },
                },
                "returns": {
                    "type": "object",
                    "properties": {
                        "steps": {"type": "array",
                                  "items": {"type": "object"}},
                    },
                    "required": [],
                },
            }],
        }

    def draft_skills(self, min_repeats: int = MIN_REPEATS) -> list[dict]:
        """Write a quarantined draft package per new solidified sequence.

        Layout per draft: foundry/<name>/skill.json (registry manifest),
        foundry/<name>/foundry.json (provenance sidecar),
        foundry/<name>/SKILL.md (owner review note). Returns one dict per
        NEW draft: {"name", "path", "sequence", "count"}. Sequences already
        drafted are skipped, so re-running is a no-op.
        """
        already = self._drafted_sequences()
        created: list[dict] = []
        used_names = {p.name for p in self.foundry_dir.iterdir()} \
            if self.foundry_dir.is_dir() else set()
        for cand in self.find_sequences(min_repeats=min_repeats):
            seq = tuple(cand["sequence"])
            if seq in already:
                continue
            base = ("foundry_" + "_".join(_slug(t) for t in seq))
            base = base[:_NAME_MAX].rstrip("_")
            name, n = base, 2
            while name in used_names:
                name = f"{base[:_NAME_MAX - 3]}_{n}"
                n += 1
            used_names.add(name)
            pkg = self.foundry_dir / name
            pkg.mkdir(parents=True, exist_ok=True)
            routine = " -> ".join(seq)
            manifest = self._manifest(name, list(seq), cand["count"])
            _atomic_write(pkg / "skill.json",
                          json.dumps(manifest, indent=2, ensure_ascii=False))
            sidecar = {
                "source": "skill_foundry",
                "status": "quarantined-draft",
                "sequence": list(seq),
                "occurrences": cand["count"],
                "sessions": cand["sessions"],
                "created_ts": datetime.now(timezone.utc).isoformat(),
                "note": "Draft only. Nothing executes from the foundry "
                        "dir; the owner must review, write/approve a "
                        "replay implementation, and move this package "
                        "into skills/ for registry quarantine + approval.",
            }
            _atomic_write(pkg / "foundry.json",
                          json.dumps(sidecar, indent=2, ensure_ascii=False))
            _atomic_write(pkg / "SKILL.md",
                          f"# Foundry draft: {name}\n\n"
                          f"Solidified routine: **{routine}**\n\n"
                          f"- Seen {cand['count']} times across "
                          f"{cand['sessions']} session(s), every run "
                          f"succeeded.\n"
                          f"- Status: QUARANTINED DRAFT — never "
                          f"auto-approved.\n"
                          f"- To adopt: review the sequence, then move "
                          f"this folder into `skills/` and approve via "
                          f"the registry flow.\n")
            created.append({"name": name, "path": str(pkg),
                            "sequence": list(seq), "count": cand["count"]})
        return created

    # -------------------------------------------------------- anticipation

    def hourly_frequencies(self) -> dict[int, Counter]:
        """hour-of-day (UTC) -> Counter of actions, from the full log.

        Actions: "tool:<name>" for each successful tool call (same strict
        success rules as solidification) and "user.message" per user turn.
        """
        by_hour: dict[int, Counter] = {}
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT event_id, session_id, seq, ts, type, causal_parent,"
                " payload FROM events"
                " WHERE type IN ('tool.call', 'tool.result')"
                " ORDER BY session_id, seq"
            ).fetchall()
        finally:
            conn.close()
        ok_calls: set[str] = set()
        for row in rows:
            if row["type"] == "tool.result":
                payload = self._payload(row)
                if payload.get("ok") is True:
                    if row["causal_parent"]:
                        ok_calls.add(row["causal_parent"])
                    ref = payload.get("call_ref")
                    if ref:
                        ok_calls.add(ref)
        for row in rows:
            if row["type"] != "tool.call":
                continue
            payload = self._payload(row)
            if payload.get("executed", True) is False:
                continue
            if payload.get("gate_verdict", "allow") not in _EXECUTED_VERDICTS:
                continue
            if row["event_id"] not in ok_calls:
                continue
            name = payload.get("tool")
            if not isinstance(name, str) or not name:
                continue
            hour = _hour_of(row["ts"])
            if hour is not None:
                by_hour.setdefault(hour, Counter())[f"tool:{name}"] += 1
        conn = self._connect()
        try:
            msg_rows = conn.execute(
                "SELECT ts FROM events WHERE type = 'user.message'"
            ).fetchall()
        finally:
            conn.close()
        for row in msg_rows:
            hour = _hour_of(row["ts"])
            if hour is not None:
                by_hour.setdefault(hour, Counter())["user.message"] += 1
        return by_hour

    def anticipations(self, now: datetime | None = None) -> list[dict]:
        """Likely actions for now's hour-of-day, with counts. DATA ONLY —
        nothing in this module acts on the result.

        Each entry: {"action": "tool:<name>" | "user.message",
        "hour": int, "count": int}. Sorted by (-count, action).
        """
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        hour = now.hour
        counter = self.hourly_frequencies().get(hour, Counter())
        out = [{"action": action, "hour": hour, "count": n}
               for action, n in counter.items()]
        out.sort(key=lambda d: (-d["count"], d["action"]))
        return out


def _hour_of(ts: str) -> int | None:
    """UTC ISO timestamp -> hour-of-day, or None if unparseable."""
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).hour
    except ValueError:
        return None
