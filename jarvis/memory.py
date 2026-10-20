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

Grading (Team 9 steals — Mnemosyne decay policy, memory-os trust loop,
engram consolidation protocol; see fact_grades / fact_merges below):
  * Every fact carries a grade: weight, trust_score, access/retrieval/
    helpful counters, last_accessed, an archived flag and a soft
    (search-only) expires_at. Grades live in a side table keyed by fact
    id — the facts table itself is never altered (migration-safe).
  * Decay NEVER deletes: past-TTL, low-importance, rarely-accessed facts
    lose weight per consolidation pass at a PER-KIND rate and are
    eventually flagged archived (hidden from search, kept in storage).
    forget() remains the only deletion path.
  * fact-table expires_at keeps its Wave-1 hard semantics (tombstone on
    sight, spec 6.2); the grade-level expires_at is a soft TTL that only
    hides the fact from recall.

Relationship state (Team 26 — Smart-Memory x eros discipline):
  * The Owais<->JARVIS bond is three numeric axes (trust, familiarity,
    warmth) stored as namespaced facts ("relationship:<axis>") and owned
    by deterministic code. Callers may only nudge via
    nudge_relationship() — deltas clamped to +/-0.05, axes to [0, 1],
    every applied nudge journaled as an episode with its reason.
  * consolidate() maintains the axes by fixed rules (helpful-feedback
    ratio -> trust; new shared episodes -> familiarity); no LLM ever
    proposes or writes these numbers.

Wave-1 scope notes (condensed 13-item deletion checklist):
  Implemented: SQLite row delete, FTS5 entry removal, tombstone record,
  VACUUM + checkpoint, retrieval-verified empty.
  N/A in Wave 1 (no such stores yet): vector index, backups rotation,
  hot-tier cache, session snapshots, reranker cache, sync/export copies,
  log redaction, GUI viewer.

Stdlib only (sqlite3). Python 3.11+.
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
import threading
from dataclasses import dataclass
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

-- Knowledge-graph edges between facts (Builder D: isair diary+KG pattern,
-- minimal stdlib version). Additive + IF NOT EXISTS = migration-safe on
-- existing DBs. ON DELETE CASCADE keeps forget()/expiry cleanup automatic:
-- deleting a fact deletes its edges, no orphans.
CREATE TABLE IF NOT EXISTS fact_edges (
  id         INTEGER PRIMARY KEY,
  profile_id TEXT NOT NULL,
  src_fact   INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
  relation   TEXT NOT NULL,
  dst_fact   INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
  weight     REAL NOT NULL DEFAULT 1.0,
  created_ts TEXT NOT NULL,
  UNIQUE(profile_id, src_fact, relation, dst_fact)
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON fact_edges(profile_id, src_fact);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON fact_edges(profile_id, dst_fact);

-- Memory grading (Team 9). Additive side table, following the memory_meta
-- precedent: the facts table is never ALTERed, so existing DBs open
-- unchanged. One row per fact, created lazily on first graded touch;
-- absent row = the documented defaults (weight 1.0, trust 0.5, counts 0).
-- ON DELETE CASCADE: forget()/expiry remove grades with their fact.
CREATE TABLE IF NOT EXISTS fact_grades (
  fact_id         INTEGER PRIMARY KEY REFERENCES facts(id) ON DELETE CASCADE,
  weight          REAL NOT NULL DEFAULT 1.0,
  trust_score     REAL NOT NULL DEFAULT 0.5,
  helpful_count   INTEGER NOT NULL DEFAULT 0,
  retrieval_count INTEGER NOT NULL DEFAULT 0,
  access_count    INTEGER NOT NULL DEFAULT 0,
  last_accessed   TEXT,
  expires_at      TEXT,
  archived        INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
  consolidated_from TEXT,
  updated_ts      TEXT NOT NULL
);

-- Audit trail for applied consolidation plans (engram pattern): the
-- survivor's provenance note also lands on its fact_grades row.
CREATE TABLE IF NOT EXISTS fact_merges (
  id          INTEGER PRIMARY KEY,
  profile_id  TEXT NOT NULL,
  survivor_id INTEGER NOT NULL,
  source_ids  TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  note        TEXT NOT NULL,
  applied_ts  TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
  kind, content, key,
  ref_id UNINDEXED, profile_id UNINDEXED,
  tokenize='porter'
);
"""


@dataclass(frozen=True)
class ConsolidationPlan:
    """An un-applied merge of two facts (engram plan-then-mutate).

    Built by Memory.plan_consolidation(); carries a sha256 fingerprint
    over both sources and the survivor text. apply_consolidation()
    re-derives the fingerprint from the live rows inside one transaction
    and refuses loudly if anything changed since the plan was made.
    """

    key: str                 # survivor key (fact_a's key)
    survivor_text: str       # survivor value (default: the newer value)
    sources: tuple           # two dicts: id/key/value/tier/source/created_ts
    fingerprint: str         # sha256 over sources + survivor key/text


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
                   confidence: float, expires_at: str | None = None,
                   metadata: dict | None = None) -> dict:
        """Capture -> extract -> resolve -> quarantine gate -> store.

        Resolve (mem0-style): same key + identical value -> NOOP;
        same key + new value -> UPDATE (old row gets superseded_by, never
        deleted); new key -> ADD. Confidence is attached at birth and is
        mandatory. Values over 500 chars are rejected (atomic facts only).
        tier 'tool'/'web' -> quarantined=1 (spec 2.4, C-S6 fix).

        metadata (optional): {"relates_to": [...], ...} links this fact to
        others in the knowledge graph. Each relates_to item is a fact id
        (int), a fact key (str), or a dict {"fact_id"|"key": ...,
        "relation": str, "weight": float}. A bad target raises BEFORE any
        mutation, so a write never half-lands.
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
            # Resolve graph-link targets first: a bad relates_to raises here,
            # before a single row has been touched.
            pending_links = self._resolve_links_locked(metadata)
            row = self._conn.execute(
                "SELECT id, value, quarantined FROM facts "
                "WHERE profile_id = ? AND key = ? AND superseded_by IS NULL",
                (self.profile_id, key),
            ).fetchone()
            if row is not None and row["value"] == value:
                for dst_id, relation, weight in pending_links:
                    self._link_locked(row["id"], dst_id, relation, weight)
                self._conn.commit()
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
            for dst_id, relation, weight in pending_links:
                self._link_locked(new_id, dst_id, relation, weight)
            self._conn.commit()
            return {"op": op, "id": new_id, "quarantined": bool(quarantined)}

    def get_fact(self, key: str) -> dict | None:
        """Keyed lookup of the current fact. Expired facts auto-expire here:
        returns None and records a tombstone (spec 6.2). A successful read
        bumps the fact's grade (access_count + last_accessed)."""
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
            self._record_access_locked(row["id"])
            self._conn.commit()
            grade = self._grade_row_locked(row["id"])
            return self._fact_dict(row, grade)

    # ----------------------------------------------------------------- recall

    def recall(self, query: str, include_quarantined: bool = False,
               limit: int = 5) -> list[dict]:
        """Hybrid-lite retrieval: FTS5 BM25 over facts + episodes -> top N.

        The brain receives snippets (<=200 chars), never dumps. Quarantined
        facts are excluded unless include_quarantined=True, and are always
        returned WITH the quarantine flag set. Expired facts are tombstoned
        on sight and excluded. Archived facts and facts past their
        grade-level (soft) expires_at are hidden from search — the rows
        stay in storage; only forget() deletes.

        Ranking (Team 9 blend, deterministic): each candidate's BM25 score
        is sigmoid-normalized (mem0's query-length-adaptive mid/k, so the
        scale is stable) and multiplied by a grade factor —
        facts: 0.5 + 0.5 * weight * trust_score; episodes: the neutral
        factor (an ungraded fresh fact). "score" stays the raw BM25 value;
        "grade_score" is the blended value the ordering used. Facts that
        are actually returned get an access bump (access_count,
        last_accessed).
        """
        query = (query or "").strip()
        if not query or limit <= 0:
            return []
        n_terms = len(query.split())
        now = _now_iso()
        scored: list[tuple[float, int, dict]] = []
        with self._lock:
            for seq, hit in enumerate(self._fts_search_locked(query, limit * 4)):
                raw = -hit["rank"]
                base = self._sigmoid_bm25(raw, n_terms)
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
                    grade = self._grade_row_locked(row["id"])
                    if grade is not None:
                        if grade["archived"]:
                            continue  # faded by decay: hidden, not deleted
                        if grade["expires_at"] and grade["expires_at"] <= now:
                            continue  # soft TTL passed: hidden, not deleted
                        weight, trust = grade["weight"], grade["trust_score"]
                    else:
                        weight, trust = 1.0, self.GRADE_TRUST_PRIOR
                    factor = 0.5 + 0.5 * weight * trust
                    scored.append((base * factor, seq, {
                        "kind": "fact",
                        "id": row["id"],
                        "key": row["key"],
                        "snippet": f"{row['key']}: {row['value']}"[:self.SNIPPET_CHARS],
                        "score": raw,
                        "grade_score": base * factor,
                        "weight": weight,
                        "trust_score": trust,
                        "source": row["source"],
                        "confidence": row["confidence"],
                        "quarantined": bool(row["quarantined"]),
                    }))
                else:
                    ep = self._conn.execute(
                        "SELECT * FROM episodes WHERE id = ? AND profile_id = ?",
                        (hit["ref_id"], self.profile_id),
                    ).fetchone()
                    if ep is None:
                        continue
                    scored.append((base * self.RECALL_NEUTRAL_FACTOR, seq, {
                        "kind": "episode",
                        "id": ep["id"],
                        "key": None,
                        "snippet": ep["summary"][:self.SNIPPET_CHARS],
                        "score": raw,
                        "grade_score": base * self.RECALL_NEUTRAL_FACTOR,
                        "source": "session",
                        "confidence": None,
                        "quarantined": False,
                        "session_id": ep["session_id"],
                        "ts": ep["ts"],
                    }))
            scored.sort(key=lambda t: (-t[0], t[1]))
            results = [r for _, _, r in scored[:limit]]
            for r in results:
                if r["kind"] == "fact":
                    self._record_access_locked(r["id"])
            if any(r["kind"] == "fact" for r in results):
                self._conn.commit()
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

    # ---------------------------------------------------------- consolidation

    DECAY_MIN_AGE_DAYS = 30      # facts younger than this never decay
    DECAY_DAILY_FACTOR = 0.98    # confidence *= factor ** days since last run
    DECAY_FLOOR = 0.1

    # ------------------------------------------------------- grading policy
    # Mnemosyne decay policy (Team 9 report, section 8): TTL 90 days,
    # importance threshold 0.3, access threshold 5, archive-don't-delete.
    # v2 has no separate importance column: importance := the fact's
    # stored confidence (its birth salience), read after the confidence
    # decay pass has run.
    GRADE_TTL_DAYS = 90
    GRADE_IMPORTANCE_MAX = 0.3   # gate: confidence must be BELOW this
    GRADE_ACCESS_MAX = 5         # gate: access_count must be BELOW this
    GRADE_ARCHIVE_WEIGHT = 0.5   # weight below this -> archived flag set
    GRADE_TRUST_PRIOR = 0.5      # Bayesian prior (Beta(1,1) posterior mean)
    GRADE_TRUST_FLOOR = 0.5      # identity facts never sink below the prior
    # Per-kind weight multipliers per consolidation pass (constellation-
    # engine rates via Team 3, mapped onto v2's provenance tiers):
    #   provenance-marked identity (key namespace 'identity:' /
    #   'relationship:' or source 'identity') -> EXEMPT (no decay at all)
    #   tier 'user'     (owner-stated; identity/principle class) -> x0.999
    #   tier 'tool'/'web' (semantic, learned from the world)     -> x0.95
    #   tier 'inferred' (emergent / inferred)                    -> x0.90
    GRADE_DECAY_FACTORS = {"user": 0.999, "tool": 0.95, "web": 0.95,
                           "inferred": 0.90}
    IDENTITY_KEY_NAMESPACES = frozenset({"identity", "relationship"})
    # Recall blend: final = sigmoid_bm25 * (0.5 + 0.5 * weight * trust).
    # With untouched grades (weight 1.0, trust = prior 0.5) every item —
    # facts and episodes alike — gets the same 0.75 factor, so default
    # ordering is exactly the old BM25 ordering (sigmoid is monotonic).
    RECALL_NEUTRAL_FACTOR = 0.75

    def consolidate(self, now_iso: str | None = None) -> dict:
        """Sleep-consolidation pass (Nocturne pattern: code applies the
        passes; no LLM proposes anything here).

        expire  — rows past expires_at are tombstoned via the normal path.
        dedupe  — duplicate live (key, value) rows merge into the earliest.
        promote — a quarantined fact corroborated by >=2 distinct sources
                  leaves quarantine with a small confidence bump.
        decay   — confidence of facts older than DECAY_MIN_AGE_DAYS decays
                  with elapsed wall-clock time since the previous run
                  (tracked in memory_meta), floored at DECAY_FLOOR.
        grading — Mnemosyne weight decay (see GRADE_* constants): facts
                  past the TTL with low importance and few accesses lose
                  weight at their per-kind rate; weight below the archive
                  threshold sets the archived flag. NEVER deletes.
        relationship — deterministic bond maintenance (see REL_*
                  constants): the all-time helpful-feedback ratio over
                  graded retrievals nudges trust (up slowly at >= 0.7,
                  down faster at <= 0.3, only on >= 5 judged retrievals),
                  and any new shared episodes since the previous run
                  nudge familiarity. Warmth has NO automatic rule —
                  explicit nudges only. Every move is journaled.
        Returns per-pass counts — safe to run nightly/idle, idempotent.
        The grading counts ride along under "weight_decayed"/"archived"
        keys, present only when nonzero, so the base counts shape is
        unchanged for existing callers.
        """
        from datetime import datetime, timezone

        def _parse(ts: str | None):
            if not ts:
                return None
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                return None
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

        now = _parse(now_iso) or datetime.now(timezone.utc)
        counts = {"expired": 0, "deduped": 0, "promoted": 0, "decayed": 0}
        with self._lock:
            # 1) expire
            rows = self._conn.execute(
                "SELECT * FROM facts WHERE profile_id = ?"
                " AND superseded_by IS NULL",
                (self.profile_id,),
            ).fetchall()
            for row in rows:
                if self._is_expired(row):
                    self._expire_key_locked(row["key"], row["id"])
                    counts["expired"] += 1

            # 2) dedupe identical live (key, value) pairs
            dupes = self._conn.execute(
                "SELECT key, value, MIN(id) AS keep_id, COUNT(*) AS n"
                " FROM facts WHERE profile_id = ? AND superseded_by IS NULL"
                " GROUP BY key, value HAVING n > 1",
                (self.profile_id,),
            ).fetchall()
            for d in dupes:
                extra = self._conn.execute(
                    "SELECT id FROM facts WHERE profile_id = ? AND key = ?"
                    " AND value = ? AND superseded_by IS NULL AND id != ?",
                    (self.profile_id, d["key"], d["value"], d["keep_id"]),
                ).fetchall()
                for e in extra:
                    self._conn.execute(
                        "UPDATE facts SET superseded_by = ? WHERE id = ?",
                        (d["keep_id"], e["id"]))
                    self._conn.execute(
                        "DELETE FROM memory_fts WHERE kind = 'fact'"
                        " AND ref_id = ?", (e["id"],))
                    counts["deduped"] += 1

            # 3) promote corroborated quarantined facts
            qrows = self._conn.execute(
                "SELECT * FROM facts WHERE profile_id = ?"
                " AND superseded_by IS NULL AND quarantined = 1",
                (self.profile_id,),
            ).fetchall()
            for row in qrows:
                n_sources = self._conn.execute(
                    "SELECT COUNT(DISTINCT source) AS n FROM facts"
                    " WHERE profile_id = ? AND key = ? AND value = ?",
                    (self.profile_id, row["key"], row["value"]),
                ).fetchone()["n"]
                if n_sources >= 2:
                    self._conn.execute(
                        "UPDATE facts SET quarantined = 0,"
                        " confidence = MIN(1.0, confidence + 0.1)"
                        " WHERE id = ?", (row["id"],))
                    counts["promoted"] += 1

            # 4) decay with elapsed time since the last run
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS memory_meta"
                " (key TEXT PRIMARY KEY, value TEXT)")
            prev = self._conn.execute(
                "SELECT value FROM memory_meta"
                " WHERE key = 'last_consolidation_ts'").fetchone()
            prev_dt = _parse(prev["value"]) if prev else None
            days = max(0.0, (now - prev_dt).total_seconds() / 86400.0) \
                if prev_dt else 0.0
            if days > 0:
                factor = self.DECAY_DAILY_FACTOR ** days
                live = self._conn.execute(
                    "SELECT id, confidence, created_ts FROM facts"
                    " WHERE profile_id = ? AND superseded_by IS NULL",
                    (self.profile_id,),
                ).fetchall()
                for row in live:
                    created = _parse(row["created_ts"])
                    if created is None:
                        continue
                    age_days = (now - created).total_seconds() / 86400.0
                    if age_days < self.DECAY_MIN_AGE_DAYS:
                        continue
                    new_conf = max(self.DECAY_FLOOR,
                                   row["confidence"] * factor)
                    if abs(new_conf - row["confidence"]) > 0.001:
                        self._conn.execute(
                            "UPDATE facts SET confidence = ? WHERE id = ?",
                            (new_conf, row["id"]))
                        counts["decayed"] += 1
            # 5) grading decay (Mnemosyne): weight only, never deletion.
            grows = self._conn.execute(
                "SELECT f.id, f.confidence, f.provenance_tier, f.source,"
                " f.key, f.created_ts, g.weight, g.access_count, g.archived"
                " FROM facts f LEFT JOIN fact_grades g ON g.fact_id = f.id"
                " WHERE f.profile_id = ? AND f.superseded_by IS NULL",
                (self.profile_id,),
            ).fetchall()
            n_decayed = n_archived = 0
            for row in grows:
                if row["archived"]:
                    continue  # already faded out; the flag is sticky
                if self._is_identity_fact(row):
                    continue  # provenance-marked identity never decays
                created = _parse(row["created_ts"])
                if created is None:
                    continue
                age_days = (now - created).total_seconds() / 86400.0
                if age_days <= self.GRADE_TTL_DAYS:
                    continue
                if row["confidence"] >= self.GRADE_IMPORTANCE_MAX:
                    continue
                if (row["access_count"] or 0) >= self.GRADE_ACCESS_MAX:
                    continue
                factor = self.GRADE_DECAY_FACTORS[row["provenance_tier"]]
                weight = (row["weight"] if row["weight"] is not None
                          else 1.0) * factor
                self._ensure_grade_locked(row["id"])
                if weight < self.GRADE_ARCHIVE_WEIGHT:
                    self._conn.execute(
                        "UPDATE fact_grades SET weight = ?, archived = 1,"
                        " updated_ts = ? WHERE fact_id = ?",
                        (weight, _now_iso(), row["id"]))
                    n_archived += 1
                else:
                    self._conn.execute(
                        "UPDATE fact_grades SET weight = ?, updated_ts = ?"
                        " WHERE fact_id = ?",
                        (weight, _now_iso(), row["id"]))
                n_decayed += 1
            if n_decayed:
                counts["weight_decayed"] = n_decayed
            if n_archived:
                counts["archived"] = n_archived

            # 6) relationship state (Team 26): deterministic rules only.
            # Deliberately NOT reported in the counts dict — its shape
            # is a pinned contract (four pass counters, plus grading
            # keys when they fire). The moves are observable via
            # relationship_snapshot() and the journal episodes.
            agg = self._conn.execute(
                "SELECT COALESCE(SUM(g.helpful_count), 0) AS h,"
                " COALESCE(SUM(g.retrieval_count), 0) AS r"
                " FROM fact_grades g JOIN facts f ON f.id = g.fact_id"
                " WHERE f.profile_id = ? AND f.superseded_by IS NULL",
                (self.profile_id,),
            ).fetchone()
            if agg["r"] >= self.REL_FEEDBACK_MIN_RETRIEVALS:
                ratio = agg["h"] / agg["r"]
                if ratio >= self.REL_TRUST_UP_RATIO:
                    self._apply_relationship_nudge_locked(
                        "trust", self.REL_TRUST_UP_STEP,
                        f"consolidation: helpful-feedback ratio "
                        f"{ratio:.2f} >= {self.REL_TRUST_UP_RATIO} over "
                        f"{agg['r']} judged retrievals",
                        _now_iso())
                elif ratio <= self.REL_TRUST_DOWN_RATIO:
                    self._apply_relationship_nudge_locked(
                        "trust", -self.REL_TRUST_DOWN_STEP,
                        f"consolidation: helpful-feedback ratio "
                        f"{ratio:.2f} <= {self.REL_TRUST_DOWN_RATIO} over "
                        f"{agg['r']} judged retrievals",
                        _now_iso())
            # Familiarity = accumulated shared history: episodes
            # (other than the relationship journal itself) recorded
            # since the previous consolidation count as time together.
            # A monotone watermark in memory_meta (not a timestamp
            # compare) decides what is "new" — episodes are append-only,
            # so the count can only grow.
            total_eps = self._conn.execute(
                "SELECT COUNT(*) AS n FROM episodes"
                " WHERE profile_id = ? AND session_id != ?",
                (self.profile_id, self.RELATIONSHIP_JOURNAL_SESSION),
            ).fetchone()["n"]
            seen_row = self._conn.execute(
                "SELECT value FROM memory_meta"
                " WHERE key = 'relationship_episodes_seen'").fetchone()
            seen_eps = int(seen_row["value"]) if seen_row else 0
            n_new_eps = max(0, total_eps - seen_eps)
            self._conn.execute(
                "INSERT INTO memory_meta (key, value) VALUES"
                " ('relationship_episodes_seen', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(total_eps),))
            if n_new_eps > 0:
                self._apply_relationship_nudge_locked(
                    "familiarity", self.REL_FAMILIARITY_STEP,
                    f"consolidation: {n_new_eps} new shared episode(s) "
                    f"since the previous consolidation",
                    _now_iso())

            stamp = now.strftime("%Y-%m-%dT%H:%M:%S+00:00")
            self._conn.execute(
                "INSERT INTO memory_meta (key, value) VALUES"
                " ('last_consolidation_ts', ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (stamp,))
            self._conn.commit()
        return counts

    # -------------------------------------------------------------- grading

    def grade(self, fact) -> dict:
        """The grade of a live fact (id or key): weight, trust_score,
        helpful/retrieval/access counts, last_accessed, soft expires_at,
        archived, consolidated_from. Facts never graded report the
        documented defaults."""
        with self._lock:
            fid = self._resolve_fact_locked(fact)
            self._ensure_grade_locked(fid)
            self._conn.commit()
            return self._grade_dict(self._grade_row_locked(fid))

    def record_feedback(self, fact, helpful: bool) -> dict:
        """Same-turn feedback on a fact the brain used (memory-os trust
        loop). Each call is one judged retrieval: retrieval_count += 1,
        helpful_count += 1 when helpful, and trust_score becomes the
        Bayesian posterior mean with a Beta(1,1) prior:

            trust = (helpful_count + 1) / (retrieval_count + 2)

        Prior mean 0.5; no feedback yet -> exactly 0.5. Identity facts
        (identity-marked or tier 'user') floor at the prior — sparse bad
        luck can never sink the owner's own statements below neutral.
        Returns the updated grade dict.
        """
        with self._lock:
            fid = self._resolve_fact_locked(fact)
            row = self._conn.execute(
                "SELECT provenance_tier, source, key FROM facts WHERE id = ?",
                (fid,),
            ).fetchone()
            self._ensure_grade_locked(fid)
            self._conn.execute(
                "UPDATE fact_grades SET retrieval_count = retrieval_count + 1,"
                " helpful_count = helpful_count + ?, updated_ts = ?"
                " WHERE fact_id = ?",
                (1 if helpful else 0, _now_iso(), fid),
            )
            g = self._grade_row_locked(fid)
            trust = (g["helpful_count"] + 1) / (g["retrieval_count"] + 2)
            if self._is_identity_fact(row) or row["provenance_tier"] == "user":
                trust = max(trust, self.GRADE_TRUST_FLOOR)
            self._conn.execute(
                "UPDATE fact_grades SET trust_score = ? WHERE fact_id = ?",
                (trust, fid),
            )
            self._conn.commit()
            return self._grade_dict(self._grade_row_locked(fid))

    def set_fact_expiry(self, fact, expires_at: str | None) -> dict:
        """Set/clear a fact's SOFT expiry (grade-level): once passed, the
        fact is hidden from recall but kept in storage (unlike the
        fact-table expires_at, which tombstones). Returns the grade."""
        with self._lock:
            fid = self._resolve_fact_locked(fact)
            self._ensure_grade_locked(fid)
            self._conn.execute(
                "UPDATE fact_grades SET expires_at = ?, updated_ts = ?"
                " WHERE fact_id = ?",
                (expires_at, _now_iso(), fid),
            )
            self._conn.commit()
            return self._grade_dict(self._grade_row_locked(fid))

    # ---------------------------------------------- relationship state
    # Team 26 steal (Smart-Memory Relationship History x eros-engine
    # discipline): the bond Owais<->JARVIS as data — a tiny namespaced
    # fact set (keys "relationship:<axis>") holding numeric axes the
    # ENGINE owns. An LLM/caller may only hand in a graded nudge via
    # nudge_relationship(); deterministic code clamps it, applies it,
    # and journals it with its reason. The numbers are never written
    # directly by anything but this section.
    RELATIONSHIP_AXES = ("trust", "familiarity", "warmth")
    RELATIONSHIP_KEY_PREFIX = "relationship:"
    RELATIONSHIP_DEFAULT = 0.5      # neutral midpoint for an unborn axis
    RELATIONSHIP_NUDGE_MAX = 0.05   # one nudge moves an axis at most this
    RELATIONSHIP_JOURNAL_SESSION = "relationship"
    # consolidate() rules (deterministic, no LLM — see pass 6):
    REL_FEEDBACK_MIN_RETRIEVALS = 5   # thinner than this, don't judge
    REL_TRUST_UP_RATIO = 0.7          # helpful ratio >= this -> trust up
    REL_TRUST_DOWN_RATIO = 0.3        # helpful ratio <= this -> trust down
    REL_TRUST_UP_STEP = 0.02          # slow up...
    REL_TRUST_DOWN_STEP = 0.03        # ...fast down (eros asymmetry)
    REL_FAMILIARITY_STEP = 0.01       # per consolidation with new episodes

    def nudge_relationship(self, axis: str, delta: float,
                           reason: str) -> dict:
        """Move one relationship axis by a graded, clamped step.

        delta is clamped to +/-RELATIONSHIP_NUDGE_MAX per call and the
        axis to [0, 1] — no single event, however dramatic, swings the
        bond. Every nudge that actually moves an axis is journaled as
        an episode (session "relationship") carrying its reason: the
        audit trail astrbot keeps for every rapport change. A nudge
        that cannot move the axis (already at the bound) changes and
        journals nothing, and reports applied_delta 0.0.

        Returns the axis outcome plus a fresh relationship_snapshot().
        """
        if axis not in self.RELATIONSHIP_AXES:
            raise ValueError(
                f"axis must be one of {self.RELATIONSHIP_AXES}, got {axis!r}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("a nudge needs a reason — the journal is "
                             "the audit trail, an unexplained move is "
                             "not allowed")
        if isinstance(delta, bool) or not isinstance(delta, (int, float)):
            raise ValueError(f"delta must be a number, got {delta!r}")
        with self._lock:
            change = self._apply_relationship_nudge_locked(
                axis, float(delta), reason.strip(), _now_iso())
            self._conn.commit()
        snap = self.relationship_snapshot()
        applied = change["delta"] if change else 0.0
        value = change["new"] if change else snap[axis]
        return {"axis": axis, "value": value, "applied_delta": applied,
                "descriptor": snap["descriptor"], "snapshot": snap}

    def relationship_snapshot(self) -> dict:
        """The bond as the prompt layer needs it: the three axes plus a
        one-line deterministic descriptor ("high trust, growing
        familiarity, steady warmth") — models don't read calibrated
        numbers, so the state is also rendered as words. Axes never
        written yet report the neutral default."""
        axes: dict[str, float] = {}
        for axis in self.RELATIONSHIP_AXES:
            fact = self.get_fact(self.RELATIONSHIP_KEY_PREFIX + axis)
            value = self.RELATIONSHIP_DEFAULT
            if fact is not None:
                try:
                    value = float(fact["value"])
                except (TypeError, ValueError):
                    value = self.RELATIONSHIP_DEFAULT
            axes[axis] = max(0.0, min(1.0, value))
        return {**axes,
                "descriptor": self._relationship_descriptor(axes)}

    @staticmethod
    def _relationship_word(value: float) -> str:
        if value >= 0.75:
            return "high"
        if value >= 0.55:
            return "growing"
        if value >= 0.35:
            return "steady"
        return "low"

    @classmethod
    def _relationship_descriptor(cls, axes: dict) -> str:
        w = cls._relationship_word
        return (f"{w(axes['trust'])} trust, "
                f"{w(axes['familiarity'])} familiarity, "
                f"{w(axes['warmth'])} warmth")

    def _relationship_value_locked(self, axis: str) -> float:
        """Current axis value (caller holds the lock). Unwritten or
        unparseable axes read as the neutral default."""
        row = self._conn.execute(
            "SELECT value FROM facts WHERE profile_id = ? AND key = ?"
            " AND superseded_by IS NULL",
            (self.profile_id, self.RELATIONSHIP_KEY_PREFIX + axis),
        ).fetchone()
        if row is None:
            return self.RELATIONSHIP_DEFAULT
        try:
            return max(0.0, min(1.0, float(row["value"])))
        except (TypeError, ValueError):
            return self.RELATIONSHIP_DEFAULT

    def _apply_relationship_nudge_locked(self, axis: str, delta: float,
                                         reason: str, now: str
                                         ) -> dict | None:
        """Clamp + apply + journal one nudge. Caller holds self._lock;
        no commit. Returns the change dict, or None when the clamped
        step cannot move the axis (nothing applied, nothing journaled).

        The axis value is stored as a versioned fact (source
        "relationship", tier "user") written with write_fact's own
        supersede discipline, mirrored here because the caller already
        holds the lock; the journal entry is an episode, mirroring
        write_episode for the same reason.
        """
        key = self.RELATIONSHIP_KEY_PREFIX + axis
        old = self._relationship_value_locked(axis)
        step = max(-self.RELATIONSHIP_NUDGE_MAX,
                   min(self.RELATIONSHIP_NUDGE_MAX, delta))
        new = max(0.0, min(1.0, old + step))
        if abs(new - old) < 1e-12:
            return None
        value = f"{new:.4f}"
        row = self._conn.execute(
            "SELECT id FROM facts WHERE profile_id = ? AND key = ?"
            " AND superseded_by IS NULL",
            (self.profile_id, key),
        ).fetchone()
        new_id = self._conn.execute(
            "INSERT INTO facts (profile_id, key, value, confidence, source,"
            " provenance_tier, quarantined, created_ts, expires_at)"
            " VALUES (?, ?, ?, 1.0, 'relationship', 'user', 0, ?, NULL)",
            (self.profile_id, key, value, now),
        ).lastrowid
        if row is not None:
            self._conn.execute(
                "UPDATE facts SET superseded_by = ? WHERE id = ?",
                (new_id, row["id"]))
            self._conn.execute(
                "DELETE FROM memory_fts WHERE kind = 'fact' AND ref_id = ?",
                (row["id"],))
        self._conn.execute(
            "INSERT INTO memory_fts (kind, content, key, ref_id, profile_id)"
            " VALUES ('fact', ?, ?, ?, ?)",
            (f"{key} {value}", key, new_id, self.profile_id))
        summary = (f"relationship {axis}: {old:.2f} -> {new:.2f} "
                   f"({new - old:+.2f}) — {reason}")
        eid = self._conn.execute(
            "INSERT INTO episodes (profile_id, ts, summary, session_id,"
            " causal_ref) VALUES (?, ?, ?, ?, NULL)",
            (self.profile_id, now, summary,
             self.RELATIONSHIP_JOURNAL_SESSION),
        ).lastrowid
        self._conn.execute(
            "INSERT INTO memory_fts (kind, content, key, ref_id, profile_id)"
            " VALUES ('episode', ?, '', ?, ?)",
            (summary, eid, self.profile_id))
        return {"axis": axis, "old": old, "new": new, "delta": new - old,
                "reason": reason}

    # --------------------------------------------- consolidation plan (API)

    def plan_consolidation(self, fact_a, fact_b,
                           survivor_text: str | None = None
                           ) -> ConsolidationPlan:
        """Plan a merge of two live facts WITHOUT applying it (engram).

        The survivor keeps fact_a's key; its text defaults to the NEWER
        fact's value (corrections supersede). The plan fingerprints both
        sources (id, key, value, created_ts) plus the survivor key/text
        with sha256. Raises ValueError on anything unplannable: same
        fact twice, dead facts, an over-long survivor text, or a third
        live fact already holding the survivor key.
        """
        with self._lock:
            ida = self._resolve_fact_locked(fact_a)
            idb = self._resolve_fact_locked(fact_b)
            if ida == idb:
                raise ValueError("consolidation needs two distinct facts")
            rows = {}
            for fid in (ida, idb):
                rows[fid] = self._conn.execute(
                    "SELECT * FROM facts WHERE id = ?", (fid,)).fetchone()
            clash = self._conn.execute(
                "SELECT id FROM facts WHERE profile_id = ? AND key = ?"
                " AND superseded_by IS NULL AND id NOT IN (?, ?)",
                (self.profile_id, rows[ida]["key"], ida, idb),
            ).fetchone()
            if clash is not None:
                raise ValueError(
                    f"survivor key {rows[ida]['key']!r} is also held by live"
                    f" fact {clash['id']}; refusing to plan an ambiguous merge")
            if survivor_text is None:
                newer = rows[ida] if (rows[ida]["created_ts"], ida) \
                    >= (rows[idb]["created_ts"], idb) else rows[idb]
                survivor_text = newer["value"]
            if len(survivor_text) > self.MAX_VALUE_CHARS:
                raise ValueError(
                    f"survivor text is {len(survivor_text)} chars; atomic"
                    f" facts only (max {self.MAX_VALUE_CHARS})")
            sources = tuple(
                {"id": r["id"], "key": r["key"], "value": r["value"],
                 "confidence": r["confidence"], "tier": r["provenance_tier"],
                 "source": r["source"], "created_ts": r["created_ts"],
                 "quarantined": bool(r["quarantined"])}
                for r in (rows[ida], rows[idb]))
            fp = self._plan_fingerprint(rows[ida]["key"], survivor_text,
                                        sources)
            return ConsolidationPlan(key=rows[ida]["key"],
                                     survivor_text=survivor_text,
                                     sources=sources, fingerprint=fp)

    def apply_consolidation(self, plan: ConsolidationPlan) -> dict:
        """Apply a plan from plan_consolidation(), atomically.

        Inside one transaction the sources are re-read and the plan's
        fingerprint re-derived: any change since planning (either source
        superseded, edited or forgotten) refuses loudly with RuntimeError
        and NOTHING is written. On success both sources are superseded by
        one survivor (confidence = max of the sources; tier/quarantine
        inherited from the text donor), the survivor's grade carries a
        consolidated_from provenance note, and fact_merges audits the
        merge. (Approval gating is the caller's tier-2 concern.)
        """
        if not isinstance(plan, ConsolidationPlan):
            raise TypeError(f"expected ConsolidationPlan, got {type(plan)!r}")
        with self._lock:
            try:
                rows = []
                for src in plan.sources:
                    row = self._conn.execute(
                        "SELECT * FROM facts WHERE id = ? AND profile_id = ?"
                        " AND superseded_by IS NULL",
                        (src["id"], self.profile_id),
                    ).fetchone()
                    if row is None:
                        raise RuntimeError(
                            f"consolidation refused: source fact"
                            f" {src['id']} is no longer live; re-plan")
                    rows.append(row)
                current = tuple(
                    {"id": r["id"], "key": r["key"], "value": r["value"],
                     "confidence": r["confidence"],
                     "tier": r["provenance_tier"], "source": r["source"],
                     "created_ts": r["created_ts"],
                     "quarantined": bool(r["quarantined"])}
                    for r in rows)
                if self._plan_fingerprint(plan.key, plan.survivor_text,
                                          current) != plan.fingerprint:
                    raise RuntimeError(
                        "consolidation refused: sources changed since the"
                        " plan was made (fingerprint mismatch); re-plan")
                donor = next((r for r in rows
                              if r["value"] == plan.survivor_text), rows[0])
                now = _now_iso()
                new_id = self._conn.execute(
                    "INSERT INTO facts (profile_id, key, value, confidence,"
                    " source, provenance_tier, quarantined, created_ts,"
                    " expires_at) VALUES (?, ?, ?, ?, 'consolidation', ?, ?,"
                    " ?, NULL)",
                    (self.profile_id, plan.key, plan.survivor_text,
                     max(r["confidence"] for r in rows),
                     donor["provenance_tier"], donor["quarantined"], now),
                ).lastrowid
                for r in rows:
                    self._conn.execute(
                        "UPDATE facts SET superseded_by = ? WHERE id = ?",
                        (new_id, r["id"]))
                    self._conn.execute(
                        "DELETE FROM memory_fts WHERE kind = 'fact'"
                        " AND ref_id = ?", (r["id"],))
                self._conn.execute(
                    "INSERT INTO memory_fts (kind, content, key, ref_id,"
                    " profile_id) VALUES ('fact', ?, ?, ?, ?)",
                    (f"{plan.key} {plan.survivor_text}", plan.key, new_id,
                     self.profile_id))
                # Survivor grade: best weight/trust of the sources, summed
                # usage, and the provenance note (also audited below).
                grades = [self._grade_row_locked(r["id"]) for r in rows]
                weights = [g["weight"] if g else 1.0 for g in grades]
                trusts = [g["trust_score"] if g else self.GRADE_TRUST_PRIOR
                          for g in grades]
                src_ids = ",".join(str(i) for i in
                                   sorted(r["id"] for r in rows))
                note = f"consolidated_from facts {src_ids}"
                self._conn.execute(
                    "INSERT INTO fact_grades (fact_id, weight, trust_score,"
                    " helpful_count, retrieval_count, access_count,"
                    " last_accessed, expires_at, archived, consolidated_from,"
                    " updated_ts) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?)",
                    (new_id, max(weights), max(trusts),
                     sum(g["helpful_count"] if g else 0 for g in grades),
                     sum(g["retrieval_count"] if g else 0 for g in grades),
                     sum(g["access_count"] if g else 0 for g in grades),
                     max((g["last_accessed"] for g in grades
                          if g and g["last_accessed"]), default=None),
                     src_ids, now))
                self._conn.execute(
                    "INSERT INTO fact_merges (profile_id, survivor_id,"
                    " source_ids, fingerprint, note, applied_ts)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (self.profile_id, new_id, src_ids, plan.fingerprint,
                     note, now))
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return {"op": "CONSOLIDATE", "id": new_id, "key": plan.key,
                "sources": sorted(r["id"] for r in rows),
                "fingerprint": plan.fingerprint}

    # ------------------------------------------------------- knowledge graph

    def link(self, src, dst, relation: str = "related_to",
             weight: float = 1.0) -> dict:
        """Add (or re-weight) a directed edge between two facts.

        src/dst accept a fact id (int) or a fact key (str, resolved to the
        current live fact). Extraction stays manual/API-driven — no NLP:
        callers link explicitly, or via write_fact(metadata={"relates_to":
        [...]}). Re-linking the same (src, relation, dst) updates the
        weight instead of duplicating the edge.
        """
        if not isinstance(relation, str) or not relation.strip():
            raise ValueError("relation must be a non-empty string")
        try:
            weight = float(weight)
        except (TypeError, ValueError):
            raise ValueError(f"weight must be a number, got {weight!r}") from None
        if not weight > 0:
            raise ValueError(f"weight must be > 0, got {weight!r}")
        with self._lock:
            src_id = self._resolve_fact_locked(src)
            dst_id = self._resolve_fact_locked(dst)
            self._link_locked(src_id, dst_id, relation.strip(), weight)
            self._conn.commit()
        return {"src_fact": src_id, "dst_fact": dst_id,
                "relation": relation.strip(), "weight": weight}

    def neighbors(self, fact, hops: int = 1) -> list[dict]:
        """Breadth-first neighborhood of a fact over fact_edges.

        Edges are traversed in both directions (direction is reported per
        result: "out" = fact -> neighbor, "in" = neighbor -> fact). Only
        LIVE facts are returned: superseded rows are skipped and expired
        rows are tombstoned on sight, mirroring recall(). One row per
        (neighbor, relation, direction) at its shallowest depth — a fact
        linked by two different relations appears twice; BFS still expands
        each fact once. Ordered by (hops, -weight, id): deterministic.
        """
        if not isinstance(hops, int) or hops < 1:
            raise ValueError(f"hops must be a positive int, got {hops!r}")
        with self._lock:
            start = self._resolve_fact_locked(fact)
            discovered = {start: 0}
            emitted: set[tuple] = set()
            frontier = {start}
            found: list[dict] = []
            for depth in range(1, hops + 1):
                next_frontier: set[int] = set()
                for node in sorted(frontier):
                    edges = self._conn.execute(
                        "SELECT src_fact, dst_fact, relation, weight"
                        " FROM fact_edges WHERE profile_id = ?"
                        " AND (src_fact = ? OR dst_fact = ?)"
                        " ORDER BY id",
                        (self.profile_id, node, node),
                    ).fetchall()
                    for e in edges:
                        if e["src_fact"] == node:
                            other, direction = e["dst_fact"], "out"
                        else:
                            other, direction = e["src_fact"], "in"
                        if discovered.get(other, depth) < depth:
                            continue  # already found at a shallower depth
                        row = self._conn.execute(
                            "SELECT * FROM facts WHERE id = ?"
                            " AND profile_id = ? AND superseded_by IS NULL",
                            (other, self.profile_id),
                        ).fetchone()
                        if row is None:
                            continue  # superseded/deleted since linking
                        if self._is_expired(row):
                            self._expire_key_locked(row["key"], row["id"])
                            continue
                        if other not in discovered:
                            discovered[other] = depth
                            next_frontier.add(other)
                        sig = (other, e["relation"], direction)
                        if sig in emitted:
                            continue
                        emitted.add(sig)
                        found.append({
                            "id": row["id"],
                            "key": row["key"],
                            "value": row["value"],
                            "relation": e["relation"],
                            "weight": e["weight"],
                            "direction": direction,
                            "hops": depth,
                        })
                frontier = next_frontier
                if not frontier:
                    break
        found.sort(key=lambda d: (d["hops"], -d["weight"], d["id"]))
        return found

    # ----------------------------------------------------------------- diary

    def write_diary_entry(self, day: str, events: list[dict] | None = None) -> dict:
        """Diary roll-up: compress one day's episodes into ONE semantic fact.

        Deus auto-compress pattern: the raw record stays append-only in
        episodes; the diary is a deterministic template over it — counts,
        top tools, corrections count. NO LLM summarization (a learned
        summarizer is future work; counts never hallucinate).

        day: "YYYY-MM-DD" (UTC — episode/event timestamps are UTC).
        events: optional session-store envelopes for the day, used for the
        tool and correction counts (episodes alone don't carry them). A
        tool counts only if it actually executed (gate allowed, not a
        proposal) AND its tool.result says ok. A correction counts when a
        user.message matches golden_pairs.detect_correction.

        Provenance note: the fact is stored tier='inferred', source='diary',
        key='diary:<day>'. The facts table fixes the tier vocabulary by
        CHECK constraint (user/inferred/tool/web), so the diary provenance
        rides on source + key namespace instead of a new tier value.
        Re-running for the same day is idempotent via write_fact semantics
        (same value -> NOOP, changed counts -> UPDATE supersedes).
        """
        import re
        from datetime import datetime

        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day or ""):
            raise ValueError(f"day must be 'YYYY-MM-DD', got {day!r}")
        datetime.strptime(day, "%Y-%m-%d")  # raises on impossible dates
        with self._lock:
            eps = self._conn.execute(
                "SELECT id, summary, session_id, ts FROM episodes"
                " WHERE profile_id = ? AND ts LIKE ? ORDER BY ts, id",
                (self.profile_id, f"{day}%"),
            ).fetchall()
        n_episodes = len(eps)
        n_sessions = len({e["session_id"] for e in eps})

        tool_counts: dict[str, int] = {}
        corrections = 0
        if events:
            ok_calls: set[str] = set()
            for ev in events:
                if ev.get("type") != "tool.result":
                    continue
                payload = ev.get("payload") or {}
                if payload.get("ok") is True:
                    if ev.get("causal_parent"):
                        ok_calls.add(ev["causal_parent"])
                    ref = payload.get("call_ref")
                    if ref:
                        ok_calls.add(ref)
            try:
                from jarvis.golden_pairs import detect_correction
            except Exception:  # pragma: no cover - golden_pairs is in-repo
                detect_correction = None
            for ev in events:
                ts = ev.get("ts") or ""
                if ts and not ts.startswith(day):
                    continue
                payload = ev.get("payload") or {}
                if ev.get("type") == "tool.call":
                    executed = payload.get("executed", True) is not False
                    verdict = payload.get("gate_verdict", "allow")
                    if (executed and verdict in ("allow", "allow_with_undo")
                            and ev.get("event_id") in ok_calls):
                        name = payload.get("tool")
                        if name:
                            tool_counts[name] = tool_counts.get(name, 0) + 1
                elif ev.get("type") == "user.message":
                    text = payload.get("text") or ""
                    if detect_correction is not None and text \
                            and detect_correction(text):
                        corrections += 1
        top_tools = sorted(tool_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        tools_str = ", ".join(f"{name} x{n}" for name, n in top_tools)

        def _short(text: str, cap: int) -> str:
            text = " ".join(str(text).split())
            return text if len(text) <= cap else text[:cap - 3].rstrip() + "..."

        parts = [f"diary {day}: {n_episodes} episodes, {n_sessions} sessions."]
        if tools_str:
            parts.append(f"top tools: {tools_str}.")
        parts.append(f"corrections: {corrections}.")
        if eps:
            parts.append(f"first: {_short(eps[0]['summary'], 110)}")
            if len(eps) > 1:
                parts.append(f"last: {_short(eps[-1]['summary'], 110)}")
        value = " ".join(parts)
        if len(value) > self.MAX_VALUE_CHARS:  # hard cap: facts are <= 500
            value = value[: self.MAX_VALUE_CHARS - 3].rstrip() + "..."
        result = self.write_fact(f"diary:{day}", value, source="diary",
                                 tier="inferred", confidence=1.0)
        return {"day": day, "episodes": n_episodes, "sessions": n_sessions,
                "top_tools": dict(top_tools), "corrections": corrections,
                "value": value, **result}

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

    def _ensure_grade_locked(self, fact_id: int) -> None:
        """Create the fact's grade row with documented defaults if absent.
        Caller holds self._lock; no commit."""
        self._conn.execute(
            "INSERT OR IGNORE INTO fact_grades (fact_id, updated_ts)"
            " VALUES (?, ?)",
            (fact_id, _now_iso()),
        )

    def _grade_row_locked(self, fact_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM fact_grades WHERE fact_id = ?", (fact_id,),
        ).fetchone()

    def _record_access_locked(self, fact_id: int) -> None:
        """One read of a fact: access_count += 1, last_accessed = now.
        Caller holds self._lock; no commit."""
        self._ensure_grade_locked(fact_id)
        self._conn.execute(
            "UPDATE fact_grades SET access_count = access_count + 1,"
            " last_accessed = ?, updated_ts = ? WHERE fact_id = ?",
            (_now_iso(), _now_iso(), fact_id),
        )

    @staticmethod
    def _grade_dict(row: sqlite3.Row) -> dict:
        return {
            "fact_id": row["fact_id"],
            "weight": row["weight"],
            "trust_score": row["trust_score"],
            "helpful_count": row["helpful_count"],
            "retrieval_count": row["retrieval_count"],
            "access_count": row["access_count"],
            "last_accessed": row["last_accessed"],
            "expires_at": row["expires_at"],
            "archived": bool(row["archived"]),
            "consolidated_from": row["consolidated_from"],
        }

    @classmethod
    def _is_identity_fact(cls, row) -> bool:
        """Provenance-marked identity: key lives in the identity: /
        relationship: namespace, or the fact's source is 'identity'.
        Such facts are permanently exempt from grading decay and floor
        at the trust prior."""
        key = row["key"] or ""
        namespace = key.split(":", 1)[0] if ":" in key else ""
        return namespace in cls.IDENTITY_KEY_NAMESPACES \
            or row["source"] == "identity"

    @staticmethod
    def _sigmoid_bm25(score: float, n_terms: int) -> float:
        """mem0's sigmoid BM25 normalization with query-length-adaptive
        (mid, k): <=3 terms -> (5.0, 0.7), >=15 terms -> (12.0, 0.5),
        linear interpolation between. Maps BM25 magnitudes onto (0, 1)
        so they can be blended with grade signals without scale chaos."""
        if n_terms <= 3:
            mid, k = 5.0, 0.7
        elif n_terms >= 15:
            mid, k = 12.0, 0.5
        else:
            t = (n_terms - 3) / 12.0
            mid, k = 5.0 + 7.0 * t, 0.7 - 0.2 * t
        x = -k * (score - mid)
        if x > 500:
            return 0.0
        if x < -500:
            return 1.0
        return 1.0 / (1.0 + math.exp(x))

    @staticmethod
    def _plan_fingerprint(key: str, survivor_text: str, sources) -> str:
        """sha256 over the survivor key/text + both sources' identity
        fields (id, key, value, created_ts), order-independent."""
        h = hashlib.sha256()
        h.update(f"v1\x1f{key}\x1f{survivor_text}".encode("utf-8"))
        for s in sorted(sources, key=lambda d: d["id"]):
            h.update(
                f"\x1e{s['id']}\x1f{s['key']}\x1f{s['value']}"
                f"\x1f{s['created_ts']}".encode("utf-8"))
        return h.hexdigest()

    def _resolve_fact_locked(self, fact: int | str) -> int:
        """A fact id (int) or key (str) -> the current live fact id."""
        if isinstance(fact, bool):
            raise ValueError(f"not a fact id or key: {fact!r}")
        if isinstance(fact, int):
            row = self._conn.execute(
                "SELECT id FROM facts WHERE id = ? AND profile_id = ?"
                " AND superseded_by IS NULL",
                (fact, self.profile_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"no live fact with id {fact!r}")
            return row["id"]
        if isinstance(fact, str) and fact.strip():
            row = self._conn.execute(
                "SELECT id FROM facts WHERE profile_id = ? AND key = ?"
                " AND superseded_by IS NULL",
                (self.profile_id, fact.strip()),
            ).fetchone()
            if row is None:
                raise ValueError(f"no live fact with key {fact!r}")
            return row["id"]
        raise ValueError(f"not a fact id or key: {fact!r}")

    def _link_locked(self, src_id: int, dst_id: int, relation: str,
                     weight: float) -> None:
        """Insert-or-reweight one edge. Caller holds self._lock; no commit."""
        self._conn.execute(
            "INSERT INTO fact_edges (profile_id, src_fact, relation, dst_fact,"
            " weight, created_ts) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(profile_id, src_fact, relation, dst_fact)"
            " DO UPDATE SET weight = excluded.weight",
            (self.profile_id, src_id, relation, dst_id, weight, _now_iso()),
        )

    def _resolve_links_locked(self, metadata: dict | None) -> list[tuple]:
        """Validate + resolve metadata['relates_to'] -> [(dst_id, relation,
        weight)]. Runs BEFORE any fact mutation; raises ValueError on any
        bad target so a write never half-lands."""
        if not metadata:
            return []
        targets = metadata.get("relates_to")
        if not targets:
            return []
        if not isinstance(targets, (list, tuple)):
            raise ValueError("'relates_to' must be a list")
        resolved: list[tuple] = []
        for item in targets:
            relation, weight = "related_to", 1.0
            if isinstance(item, dict):
                target = item.get("fact_id", item.get("id", item.get("key")))
                relation = item.get("relation", relation)
                weight = item.get("weight", weight)
            else:
                target = item
            if not isinstance(relation, str) or not relation.strip():
                raise ValueError(f"bad link relation {relation!r}")
            try:
                weight = float(weight)
            except (TypeError, ValueError):
                raise ValueError(f"bad link weight {weight!r}") from None
            if not weight > 0:
                raise ValueError(f"link weight must be > 0, got {weight!r}")
            dst_id = self._resolve_fact_locked(target)
            resolved.append((dst_id, relation.strip(), weight))
        return resolved

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
    def _fact_dict(row: sqlite3.Row, grade: sqlite3.Row | None = None) -> dict:
        d = {
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
        if grade is not None:
            d["weight"] = grade["weight"]
            d["trust_score"] = grade["trust_score"]
            d["access_count"] = grade["access_count"]
            d["archived"] = bool(grade["archived"])
            if grade["consolidated_from"]:
                d["consolidated_from"] = grade["consolidated_from"]
        return d
