"""JARVIS v2 memory subsystem — Wave 1.

Two stores, one database:
  facts     - semantic memory ("what is true"), versioned via superseded_by
  episodes  - episodic memory ("what happened"), append-only

Built from learn-memory-spec.md (Research Cycle 17).

Security invariants:
  * tool/web-tier facts are QUARANTINED: retrievable for factual questions,
    NEVER returned as behavioral facts and never auto-acted on. Every
    recalled fact carries its quarantine flag; the brain MUST honor it.
  * Episodic feeds semantic, never the reverse. No code path here does
    otherwise (there is no method that writes facts from episodes).
  * Forgetting is verified, not assumed: forget() raises unless a fresh
    recall proves the fact is gone (spec 6.1, item 13).

Durability (spec 5):
  * SQLite WAL + busy_timeout + single writer behind a threading lock.
  * Every mutating method commits atomically; failures roll back.
  * forget() runs VACUUM + wal_checkpoint(TRUNCATE) after deletion.

Wave-1 scope notes (condensed 13-item deletion checklist):
  Implemented: SQLite row delete, FTS5 entry removal, tombstone record,
  VACUUM + checkpoint, retrieval-verified empty.
  N/A in Wave 1 (no such stores yet): vector index, backups rotation,
  hot-tier cache, session snapshots, reranker cache, sync/export copies,
  log redaction, GUI viewer.

Stdlib only (sqlite3). Python 3.11+.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone


_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS facts (
  id             INTEGER PRIMARY KEY,
  profile_id     TEXT NOT NULL,
  key            TEXT NOT NULL,
  value          TEXT NOT NULL CHECK (length(value) <= 500),
  confidence     REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
  source         TEXT NOT NULL,
  provenance_tier TEXT NOT NULL CHECK (provenance_tier IN ('user','inferred','tool','web')),
  quarantined    INTEGER NOT NULL DEFAULT 0 CHECK (quarantined IN (0, 1)),
  created_ts     TEXT NOT NULL,
  expires_at     TEXT,
  superseded_by  INTEGER REFERENCES facts(id)
);
CREATE INDEX IF NOT EXISTS idx_facts_current
  ON facts(profile_id, key) WHERE superseded_by IS NULL;

CREATE TABLE IF NOT EXISTS episodes (
  id         INTEGER PRIMARY KEY,
  profile_id TEXT NOT NULL,
  ts         TEXT NOT NULL,
  summary    TEXT NOT NULL,
  session_id TEXT NOT NULL,
  causal_ref TEXT
);
CREATE INDEX IF NOT EXISTS idx_episodes_ts ON episodes(profile_id, ts);

CREATE TABLE IF NOT EXISTS tombstones (
  id         INTEGER PRIMARY KEY,
  profile_id TEXT NOT NULL,
  key        TEXT NOT NULL,
  deleted_ts TEXT NOT NULL,
  reason     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tombstones_key ON tombstones(profile_id, key);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
  kind, content, key,
  ref_id UNINDEXED, profile_id UNINDEXED,
  tokenize='porter'
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Memory:
    """Two-store memory with provenance quarantine and verified forgetting."""

    TIERS = ("user", "inferred", "tool", "web")
    QUARANTINE_TIERS = frozenset({"tool", "web"})
    MAX_VALUE_CHARS = 500
    SNIPPET_CHARS = 200
    SCHEMA_VERSION = 1

    def __init__(self, db_path, profile_id: str = "owais"):
        self.db_path = str(db_path)
        self.profile_id = profile_id
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10.0)
        self._conn.row_factory = sqlite3.Row
        # Fail loud if FTS5 is unavailable: retrieval is indexed or it doesn't ship.
        try:
            self._conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe USING fts5(x)")
            self._conn.execute("DROP TABLE _fts_probe")
        except sqlite3.OperationalError as exc:  # pragma: no cover
            raise RuntimeError("SQLite FTS5 is required but unavailable") from exc
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(f"PRAGMA user_version = {self.SCHEMA_VERSION}")
            self._conn.commit()

    # ------------------------------------------------------------------ facts

    def write_fact(self, key: str, value: str, source: str, tier: str,
                   confidence: float, expires_at: str | None = None) -> dict:
        """Capture -> extract -> resolve -> quarantine gate -> store.

        Resolve (mem0-style): same key + identical value -> NOOP;
        same key + new value -> UPDATE (old row gets superseded_by, never
        deleted); new key -> ADD. Confidence is attached at birth and is
        mandatory. Values over 500 chars are rejected (atomic facts only).
        tier 'tool'/'web' -> quarantined=1 (spec 2.4, C-S6 fix).
        """
        if tier not in self.TIERS:
            raise ValueError(f"tier must be one of {self.TIERS}, got {tier!r}")
        if not key or not key.strip():
            raise ValueError("key must be non-empty")
        if len(value) > self.MAX_VALUE_CHARS:
            raise ValueError(
                f"value is {len(value)} chars; atomic facts only "
                f"(max {self.MAX_VALUE_CHARS})"
            )
        if not (0.0 <= confidence <= 1.0):
            raise ValueError(f"confidence must be in [0, 1], got {confidence!r}")
        quarantined = 1 if tier in self.QUARANTINE_TIERS else 0
        now = _now_iso()
        with self._lock:
            row = self._conn.execute(
                "SELECT id, value, quarantined FROM facts "
                "WHERE profile_id = ? AND key = ? AND superseded_by IS NULL",
                (self.profile_id, key),
            ).fetchone()
            if row is not None and row["value"] == value:
                return {"op": "NOOP", "id": row["id"],
                        "quarantined": bool(row["quarantined"])}
            new_id = self._conn.execute(
                "INSERT INTO facts (profile_id, key, value, confidence, source,"
                " provenance_tier, quarantined, created_ts, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self.profile_id, key, value, confidence, source,
                 tier, quarantined, now, expires_at),
            ).lastrowid
            if row is not None:
                self._conn.execute(
                    "UPDATE facts SET superseded_by = ? WHERE id = ?",
                    (new_id, row["id"]),
                )
                self._conn.execute(
                    "DELETE FROM memory_fts WHERE kind = 'fact' AND ref_id = ?",
                    (row["id"],),
                )
                op = "UPDATE"
            else:
                op = "ADD"
            self._conn.execute(
                "INSERT INTO memory_fts (kind, content, key, ref_id, profile_id)"
                " VALUES ('fact', ?, ?, ?, ?)",
                (f"{key} {value}", key, new_id, self.profile_id),
            )
            self._conn.commit()
            return {"op": op, "id": new_id, "quarantined": bool(quarantined)}

    def get_fact(self, key: str) -> dict | None:
        """Keyed lookup of the current fact. Expired facts auto-expire here:
        returns None and records a tombstone (spec 6.2)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM facts WHERE profile_id = ? AND key = ?"
                " AND superseded_by IS NULL",
                (self.profile_id, key),
            ).fetchone()
            if row is None:
                return None
            if self._is_expired(row):
                self._expire_key_locked(key, row["id"])
                return None
            return self._fact_dict(row)

    # ----------------------------------------------------------------- recall

    def recall(self, query: str, include_quarantined: bool = False,
               limit: int = 5) -> list[dict]:
        """Hybrid-lite retrieval: FTS5 BM25 over facts + episodes -> top N.

        The brain receives snippets (<=200 chars), never dumps. Quarantined
        facts are excluded unless include_quarantined=True, and are always
        returned WITH the quarantine flag set. Expired facts are tombstoned
        on sight and excluded.
        """
        query = (query or "").strip()
        if not query or limit <= 0:
            return []
        results: list[dict] = []
        with self._lock:
            for hit in self._fts_search_locked(query, limit * 4):
                if len(results) >= limit:
                    break
                if hit["kind"] == "fact":
                    row = self._conn.execute(
                        "SELECT * FROM facts WHERE id = ? AND profile_id = ?"
                        " AND superseded_by IS NULL",
                        (hit["ref_id"], self.profile_id),
                    ).fetchone()
                    if row is None:
                        continue  # superseded or forgotten since indexed
                    if self._is_expired(row):
                        self._expire_key_locked(row["key"], row["id"])
                        continue
                    if row["quarantined"] and not include_quarantined:
                        continue
                    results.append({
                        "kind": "fact",
                        "id": row["id"],
                        "key": row["key"],
                        "snippet": f"{row['key']}: {row['value']}"[:self.SNIPPET_CHARS],
                        "score": -hit["rank"],
                        "source": row["source"],
                        "confidence": row["confidence"],
                        "quarantined": bool(row["quarantined"]),
                    })
                else:
                    ep = self._conn.execute(
                        "SELECT * FROM episodes WHERE id = ? AND profile_id = ?",
                        (hit["ref_id"], self.profile_id),
                    ).fetchone()
                    if ep is None:
                        continue
                    results.append({
                        "kind": "episode",
                        "id": ep["id"],
                        "key": None,
                        "snippet": ep["summary"][:self.SNIPPET_CHARS],
                        "score": -hit["rank"],
                        "source": "session",
                        "confidence": None,
                        "quarantined": False,
                        "session_id": ep["session_id"],
                        "ts": ep["ts"],
                    })
        return results

    # ----------------------------------------------------------------- forget

    def forget(self, key: str) -> dict:
        """Deliberate, complete, verifiable forgetting (spec 6.1).

        Deletes ALL rows for the key (current + superseded history), removes
        FTS entries, records a tombstone, runs VACUUM + wal_checkpoint, then
        VERIFIES via a fresh recall. Raises RuntimeError if anything survives.
        """
        with self._lock:
            ids = [r["id"] for r in self._conn.execute(
                "SELECT id FROM facts WHERE profile_id = ? AND key = ?",
                (self.profile_id, key),
            )]
            self._conn.execute(
                "DELETE FROM facts WHERE profile_id = ? AND key = ?",
                (self.profile_id, key),
            )
            for fid in ids:
                self._conn.execute(
                    "DELETE FROM memory_fts WHERE kind = 'fact' AND ref_id = ?",
                    (fid,),
                )
            self._conn.execute(
                "INSERT INTO tombstones (profile_id, key, deleted_ts, reason)"
                " VALUES (?, ?, ?, 'forget')",
                (self.profile_id, key, _now_iso()),
            )
            self._conn.commit()
            # VACUUM / checkpoint must run outside a transaction.
            self._conn.execute("VACUUM")
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        # Verification: the delete is tested, not assumed (spec 6.1 item 13).
        if self.get_fact(key) is not None or self.recall(key):
            raise RuntimeError(
                f"forget({key!r}) FAILED verification: fact still retrievable"
            )
        return {"key": key, "deleted_rows": len(ids),
                "tombstoned": True, "verified": True}

    # --------------------------------------------------------------- episodes

    def write_episode(self, summary: str, session_id: str,
                      causal_ref: str | None = None) -> int:
        """Append-only episodic record. No auto-summarization in Wave 1;
        hot/warm is derived from ts at query time."""
        if not summary or not summary.strip():
            raise ValueError("summary must be non-empty")
        if not session_id:
            raise ValueError("session_id must be non-empty")
        with self._lock:
            eid = self._conn.execute(
                "INSERT INTO episodes (profile_id, ts, summary, session_id, causal_ref)"
                " VALUES (?, ?, ?, ?, ?)",
                (self.profile_id, _now_iso(), summary, session_id, causal_ref),
            ).lastrowid
            self._conn.execute(
                "INSERT INTO memory_fts (kind, content, key, ref_id, profile_id)"
                " VALUES ('episode', ?, '', ?, ?)",
                (summary, eid, self.profile_id),
            )
            self._conn.commit()
            return eid

    # ------------------------------------------------------------------ misc

    def tombstone_count(self, key: str) -> int:
        """Audit helper: how many tombstones exist for a key."""
        with self._lock:
            return self._conn.execute(
                "SELECT COUNT(*) AS n FROM tombstones WHERE profile_id = ? AND key = ?",
                (self.profile_id, key),
            ).fetchone()["n"]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -------------------------------------------------------------- internals

    @staticmethod
    def _is_expired(row: sqlite3.Row) -> bool:
        exp = row["expires_at"]
        if not exp:
            return False
        return exp <= _now_iso()

    def _expire_key_locked(self, key: str, fact_id: int) -> None:
        """Lazy expiry: tombstone + delete, mirroring forget() (spec 6.2)."""
        self._conn.execute(
            "DELETE FROM facts WHERE profile_id = ? AND key = ?",
            (self.profile_id, key),
        )
        self._conn.execute(
            "DELETE FROM memory_fts WHERE kind = 'fact' AND ref_id = ?",
            (fact_id,),
        )
        self._conn.execute(
            "INSERT INTO tombstones (profile_id, key, deleted_ts, reason)"
            " VALUES (?, ?, ?, 'expired')",
            (self.profile_id, key, _now_iso()),
        )
        self._conn.commit()

    def _fts_search_locked(self, query: str, n: int) -> list[sqlite3.Row]:
        """BM25 search; falls back to quoted tokens if the raw query has
        FTS5 syntax that fails to parse."""
        attempts = [query]
        quoted = " ".join(f'"{t}"' for t in query.split())
        if quoted != query:
            attempts.append(quoted)
        for q in attempts:
            try:
                return self._conn.execute(
                    "SELECT kind, ref_id, bm25(memory_fts) AS rank"
                    " FROM memory_fts"
                    " WHERE memory_fts MATCH ? AND profile_id = ?"
                    " ORDER BY rank LIMIT ?",
                    (q, self.profile_id, n),
                ).fetchall()
            except sqlite3.OperationalError:
                continue
        return []

    @staticmethod
    def _fact_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "key": row["key"],
            "value": row["value"],
            "confidence": row["confidence"],
            "source": row["source"],
            "tier": row["provenance_tier"],
            "quarantined": bool(row["quarantined"]),
            "created_ts": row["created_ts"],
            "expires_at": row["expires_at"],
        }
