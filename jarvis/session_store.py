"""JARVIS v2 — Durable Session Store (R15).

The ONLY stateful component. Brain and hands are stateless and disposable.
Append-only event log in SQLite WAL mode + a dumb per-day JSONL spillover.
Crash recovery via wake(sessionId): checkpoint -> replay -> reconcile.

Design spec: ~/workspace/jarvis-knowledge/learn-session-store.md
Stdlib only: sqlite3, hashlib, json, uuid, os, time, threading, datetime.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone

SCHEMA_VERSION = 1

# Crockford base32 for ULIDs (no I, L, O, U).
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_ulid_lock = threading.Lock()
_ulid_last_ts = 0
_ulid_last_rand = 0

_VALID_ACTORS = {"user", "brain", "tool", "system", "supervisor"}
_VALID_TRUST = {"user", "system", "tool_untrusted", "tool_verified"}

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
  session_id   TEXT PRIMARY KEY,
  profile_id   TEXT NOT NULL DEFAULT 'owais',
  surface      TEXT NOT NULL,
  state        TEXT NOT NULL,
  created_ts   TEXT NOT NULL,
  updated_ts   TEXT NOT NULL,
  last_seq     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
  event_id      TEXT PRIMARY KEY,
  session_id    TEXT NOT NULL REFERENCES sessions(session_id),
  seq           INTEGER NOT NULL,
  trace_id      TEXT NOT NULL,
  ts            TEXT NOT NULL,
  type          TEXT NOT NULL,
  causal_parent TEXT,
  actor         TEXT NOT NULL,
  trust         TEXT NOT NULL,
  payload       TEXT NOT NULL,
  UNIQUE(session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_events_session_seq ON events(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_trace ON events(trace_id);
CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events(type, ts);
CREATE INDEX IF NOT EXISTS idx_events_causal ON events(causal_parent);

CREATE TABLE IF NOT EXISTS checkpoints (
  session_id   TEXT NOT NULL REFERENCES sessions(session_id),
  covers_seq   INTEGER NOT NULL,
  ref          TEXT NOT NULL,
  sha256       TEXT NOT NULL,
  created_ts   TEXT NOT NULL,
  PRIMARY KEY (session_id, covers_seq)
);

CREATE TABLE IF NOT EXISTS tombstones (
  event_id    TEXT PRIMARY KEY,
  session_id  TEXT NOT NULL,
  reason      TEXT NOT NULL,
  created_ts  TEXT NOT NULL
);
"""


def _ulid() -> str:
    """128-bit ULID: 48-bit ms timestamp + 80-bit randomness, Crockford base32.

    Monotonic within the same millisecond (random part increments), so
    ULIDs are strictly sortable by creation time.
    """
    global _ulid_last_ts, _ulid_last_rand
    with _ulid_lock:
        ts = int(time.time() * 1000) & 0xFFFFFFFFFFFF
        if ts > _ulid_last_ts:
            _ulid_last_ts = ts
            _ulid_last_rand = int.from_bytes(os.urandom(10), "big")
        else:
            # same (or clock-skewed) millisecond: increment to stay monotonic
            _ulid_last_ts = _ulid_last_ts
            _ulid_last_rand = (_ulid_last_rand + 1) & 0xFFFFFFFFFFFFFFFFFFFF
            ts = _ulid_last_ts
        value = (ts << 80) | _ulid_last_rand
    return "".join(_CROCKFORD[(value >> (5 * (25 - i))) & 31] for i in range(26))


def _now_ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class SessionStore:
    """Single-writer, append-only session store."""

    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        self.dir = os.path.dirname(self.db_path)
        os.makedirs(self.dir, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "PRAGMA user_version=%d" % SCHEMA_VERSION
        )
        self._conn.commit()
        os.makedirs(os.path.join(self.dir, "checkpoints"), exist_ok=True)
        self._closed = False

    # -- lifecycle ----------------------------------------------------

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.commit()
            self._conn.close()
            self._closed = True

    def __enter__(self) -> "SessionStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- sessions ------------------------------------------------------

    def create_session(self, profile_id: str, surface: str) -> str:
        """Create a session; returns session_id. Starts in CREATED state."""
        session_id = _ulid()
        ts = _now_ts()
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (session_id, profile_id, surface, state,"
                " created_ts, updated_ts, last_seq) VALUES (?, ?, ?, 'CREATED', ?, ?, 0)",
                (session_id, profile_id, surface, ts, ts),
            )
            self._conn.commit()
        return session_id

    def get_session(self, session_id: str) -> dict | None:
        cur = self._conn.execute(
            "SELECT session_id, profile_id, surface, state, created_ts,"
            " updated_ts, last_seq FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        keys = ("session_id", "profile_id", "surface", "state",
                "created_ts", "updated_ts", "last_seq")
        return dict(zip(keys, row))

    def _set_state(self, session_id: str, state: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET state = ?, updated_ts = ? WHERE session_id = ?",
            (state, _now_ts(), session_id),
        )

    # -- events --------------------------------------------------------

    def emit(
        self,
        session_id: str,
        type: str,  # noqa: A002 - spec-mandated field name
        payload: dict,
        actor: str,
        trust: str = "user",
        causal_parent: str | None = None,
        trace_id: str | None = None,
    ) -> str:
        """Append one event. Returns event_id. Also writes the JSONL spillover."""
        if actor not in _VALID_ACTORS:
            raise ValueError("invalid actor: %r" % actor)
        if trust not in _VALID_TRUST:
            raise ValueError("invalid trust tier: %r" % trust)
        event_id = _ulid()
        ts = _now_ts()
        trace = trace_id or uuid.uuid4().hex
        payload_json = json.dumps(payload, separators=(",", ":"),
                                  ensure_ascii=False)

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "UPDATE sessions SET last_seq = last_seq + 1,"
                " updated_ts = ?,"
                " state = CASE WHEN state = 'CREATED' THEN 'ACTIVE' ELSE state END"
                " WHERE session_id = ?",
                (ts, session_id),
            )
            if cur.rowcount == 0:
                raise KeyError("unknown session: %s" % session_id)
            cur.execute(
                "SELECT last_seq FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            seq = cur.fetchone()[0]
            envelope = {
                "event_id": event_id,
                "session_id": session_id,
                "seq": seq,
                "trace_id": trace,
                "ts": ts,
                "type": type,
                "causal_parent": causal_parent,
                "actor": actor,
                "trust": trust,
                "payload": payload,
            }
            # JSONL spillover FIRST (spec: the dumb durable copy), then commit.
            self._append_jsonl(envelope)
            cur.execute(
                "INSERT INTO events (event_id, session_id, seq, trace_id, ts,"
                " type, causal_parent, actor, trust, payload)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, session_id, seq, trace, ts, type,
                 causal_parent, actor, trust, payload_json),
            )
            self._conn.commit()
        return event_id

    def _append_jsonl(self, envelope: dict) -> None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = os.path.join(self.dir, "sessions-%s.jsonl" % day)
        line = json.dumps(envelope, separators=(",", ":"),
                           ensure_ascii=False) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def get_events(
        self, session_id: str, after_seq: int = 0, limit: int = 1000
    ) -> list[dict]:
        """Events ordered by seq, strictly after after_seq. Read-only."""
        cur = self._conn.execute(
            "SELECT event_id, session_id, seq, trace_id, ts, type,"
            " causal_parent, actor, trust, payload FROM events"
            " WHERE session_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (session_id, after_seq, limit),
        )
        out = []
        for row in cur.fetchall():
            out.append({
                "event_id": row[0], "session_id": row[1], "seq": row[2],
                "trace_id": row[3], "ts": row[4], "type": row[5],
                "causal_parent": row[6], "actor": row[7], "trust": row[8],
                "payload": json.loads(row[9]),
            })
        return out

    def causal_chain(self, event_id: str) -> list[dict]:
        """Walk causal_parent links upward: [event, parent, grandparent, ...]."""
        chain = []
        seen = set()
        current = event_id
        while current and current not in seen:
            seen.add(current)
            cur = self._conn.execute(
                "SELECT event_id, session_id, seq, trace_id, ts, type,"
                " causal_parent, actor, trust, payload FROM events"
                " WHERE event_id = ?",
                (current,),
            )
            row = cur.fetchone()
            if row is None:
                break
            chain.append({
                "event_id": row[0], "session_id": row[1], "seq": row[2],
                "trace_id": row[3], "ts": row[4], "type": row[5],
                "causal_parent": row[6], "actor": row[7], "trust": row[8],
                "payload": json.loads(row[9]),
            })
            current = row[6]
        return chain

    # -- checkpoints ---------------------------------------------------

    def checkpoint(self, session_id: str) -> dict:
        """Write snapshot (tmp+rename), record sha256. Returns ref info."""
        session = self.get_session(session_id)
        if session is None:
            raise KeyError("unknown session: %s" % session_id)
        covers_seq = session["last_seq"]
        events = self.get_events(session_id, after_seq=0, limit=10**9)
        snapshot = {
            "session_id": session_id,
            "covers_seq": covers_seq,
            "created_ts": _now_ts(),
            "session": session,
            "events": events,
        }
        data = json.dumps(snapshot, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        cdir = os.path.join(self.dir, "checkpoints")
        final = os.path.join(cdir, "%s-%d.json" % (session_id, covers_seq))
        tmp = final + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, final)  # atomic
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO checkpoints"
                " (session_id, covers_seq, ref, sha256, created_ts)"
                " VALUES (?, ?, ?, ?, ?)",
                (session_id, covers_seq, final, digest, _now_ts()),
            )
            self._conn.commit()
        return {"ref": final, "sha256": digest, "covers_seq": covers_seq}

    def _latest_checkpoint(self, session_id: str) -> dict | None:
        cur = self._conn.execute(
            "SELECT covers_seq, ref, sha256, created_ts FROM checkpoints"
            " WHERE session_id = ? ORDER BY covers_seq DESC LIMIT 1",
            (session_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {"covers_seq": row[0], "ref": row[1], "sha256": row[2],
                "created_ts": row[3]}

    # -- crash recovery --------------------------------------------------

    def wake(self, session_id: str) -> dict:
        """Recover a session after crash/restart.

        1. Load latest checkpoint; sha256-verify (mismatch -> quarantine,
           replay-only from seq 0).
        2. Replay tail (reduce into derived state; never re-emit).
        3. Reconcile in-flight tool.call events with no tool.result ->
           returned as `pending` (NOT re-executed here).
        4. Write crash.marker, set state RESUMED, return the report.
        """
        session = self.get_session(session_id)
        if session is None:
            raise KeyError("unknown session: %s" % session_id)
        notes: list[str] = []
        cp = self._latest_checkpoint(session_id)
        checkpoint_seq = 0
        checkpoint_ok = False

        if cp is None:
            notes.append("no checkpoint found; replaying full log from seq 0")
        else:
            try:
                with open(cp["ref"], "rb") as f:
                    raw = f.read()
                digest = hashlib.sha256(raw).hexdigest()
                if digest != cp["sha256"]:
                    raise ValueError("sha256 mismatch")
                checkpoint_seq = cp["covers_seq"]
                checkpoint_ok = True
            except (OSError, ValueError) as exc:
                bad = "%s.corrupt-%d" % (cp["ref"], int(time.time()))
                try:
                    os.replace(cp["ref"], bad)
                    notes.append(
                        "checkpoint sha256 mismatch (%s); quarantined to %s;"
                        " replay-only from seq 0" % (exc, bad)
                    )
                except OSError:
                    notes.append(
                        "checkpoint unreadable (%s); replay-only from seq 0" % exc
                    )

        # Replay the tail: reduce, never re-emit.
        tail = self.get_events(session_id, after_seq=checkpoint_seq,
                               limit=10**9)
        by_type: dict[str, int] = {}
        tool_calls: dict[str, dict] = {}
        resolved_calls: set[str] = set()
        for ev in tail:
            by_type[ev["type"]] = by_type.get(ev["type"], 0) + 1
            if ev["type"] == "tool.call":
                tool_calls[ev["event_id"]] = ev
            elif ev["type"] == "tool.result":
                if ev["causal_parent"]:
                    resolved_calls.add(ev["causal_parent"])
                ref = ev["payload"].get("call_ref") \
                    if isinstance(ev["payload"], dict) else None
                if ref:
                    resolved_calls.add(ref)

        pending = [
            {"event_id": eid, "seq": ev["seq"],
             "tool": ev["payload"].get("tool") if isinstance(ev["payload"], dict) else None,
             "payload": ev["payload"]}
            for eid, ev in tool_calls.items() if eid not in resolved_calls
        ]

        last_seq = tail[-1]["seq"] if tail else checkpoint_seq

        # crash.marker: the honest record of the gap.
        marker_id = self.emit(
            session_id,
            "crash.marker",
            {"last_seq_before_marker": last_seq,
             "checkpoint_seq": checkpoint_seq,
             "checkpoint_ok": checkpoint_ok,
             "replayed": len(tail),
             "pending_tool_calls": len(pending)},
            actor="supervisor",
            trust="system",
        )
        with self._lock:
            self._set_state(session_id, "RESUMED")
            self._conn.commit()

        return {
            "session_id": session_id,
            "checkpoint_found": cp is not None,
            "checkpoint_ok": checkpoint_ok,
            "checkpoint_seq": checkpoint_seq,
            "replayed": len(tail),
            "events_by_type": by_type,
            "last_seq": last_seq + 1,  # includes the crash.marker just written
            "pending": pending,
            "crash_marker": marker_id,
            "notes": notes,
        }

    # -- deletion (tombstone + purge; never DELETE rows) -------------------

    def tombstone(self, event_ids: list[str], reason: str) -> int:
        """Purge payloads; keep rows (seq/order/auditability intact)."""
        ts = _now_ts()
        count = 0
        with self._lock:
            for eid in event_ids:
                cur = self._conn.execute(
                    "SELECT session_id FROM events WHERE event_id = ?", (eid,))
                row = cur.fetchone()
                if row is None:
                    continue
                self._conn.execute(
                    "INSERT OR IGNORE INTO tombstones"
                    " (event_id, session_id, reason, created_ts)"
                    " VALUES (?, ?, ?, ?)",
                    (eid, row[0], reason, ts),
                )
                # The ONE sanctioned mutation: payload -> {} (content gone,
                # ordering and auditability preserved).
                self._conn.execute(
                    "UPDATE events SET payload = '{}' WHERE event_id = ?",
                    (eid,),
                )
                count += 1
            self._conn.commit()
        return count
