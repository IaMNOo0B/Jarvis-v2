# v2 Memory System — Design Specification

*PHASE INFINITY, Research Cycle 17. LEARNING ONLY — no code, no installs. This is the document the memory system gets built from.*

*Date: 2026-10-19. Status: design spec, unvalidated against a real build.*

---

## 0. Purpose

Memory is the subsystem that turns JARVIS from a chatbot that forgets you every restart into an assistant that knows you. It stores what happened (episodic) and what is true (semantic), retrieves both on demand, forgets on command, and never lets an attacker plant a permanent instruction in your assistant's head.

**What this spec covers:** the two stores, the write pipeline, the tier system, retrieval, durability, forgetting, and the failure table mapping every v1 memory corpse to the clause that prevents it.

**What this spec does NOT cover:** the session store internals (see `learn-session-store.md` — the session store feeds episodic memory but is a separate component); the consolidation review loop (M2, Hermes pattern — referenced, not re-designed here).

---

## 1. The two stores

[HC] — the two-store split is the converged industry pattern (letta, mem0, Mem0+memOS); the split exists for one reason: **facts and events have different lifecycles and different query shapes.**

### 1.1 Episodic memory — "what happened"

- **Content:** timestamped records of interactions, decisions, actions, outcomes. "On Oct 14, Owais asked me to clean his downloads folder; I deleted 3 files after confirmation; he said the old installers were fine to remove."
- **Fed by:** the session store (R15). Sessions are the raw append-only log; episodic memory is the *distilled* version — what survived the consolidation pass.
- **Query shape:** time-ordered, "when did we last…", "what did I decide about…". Retrieval is temporal + semantic.
- **Lifecycle:** hot for ~30 days, warm for ~1 year, then summarized into semantic or archived. Individual events are never edited — append-only with superseding records (letta pattern). [HC]

### 1.2 Semantic memory — "what is true"

- **Content:** stable facts, preferences, learned skills-behaviors. "Owais prefers plain English over jargon." "His GitHub username is IaMNOo0B." "The RTX 2060 has 6GB VRAM."
- **Fed by:** the extraction pipeline (§2), the Hermes review loop (M2), and direct user statements ("remember that I…").
- **Query shape:** keyed lookup + semantic search. "What do I know about X?"
- **Lifecycle:** versioned with `superseded_by` pointers (learn-databases.md T1 schema). Facts are updated, not appended — one current value per key, with history behind it. [HC]

### 1.3 Why the split exists

One store for both fails in two ways, both observed in v1:
1. **Event replay as truth:** if "what happened" and "what is true" share a table, a one-off event ("Owais said 'delete it' once, angrily") gets treated as a standing preference. The split forces a promotion decision.
2. **Query mismatch:** temporal queries over a fact table scan everything; fact queries over an event table return anecdotes. Different indexes, different shapes.

The rule: **episodic feeds semantic, never the reverse.** A fact enters semantic memory only through the pipeline's extraction and gate (§2). [HC]

---

## 2. The memory pipeline

Every candidate memory passes five stages. [HC on the pipeline shape; the mem0 two-phase gate is the proven mechanism]

```
capture → extract → resolve (ADD/UPDATE/DELETE/NOOP) → quarantine gate → store
```

### 2.1 Capture

- **Auto-capture hooks** (M1: 12 hooks): after each turn, the Hermes review loop (M2) asks the cheap local model one question: *"anything worth remembering or skill-ifying?"* Capture candidates are (fact, source, confidence, context) tuples — never raw text dumps.
- **Direct capture:** "remember that…" / "forget that…" — highest-confidence source (`source='user'`, explicit intent). Takes effect immediately, still passes the resolve gate for dedup.
- **Session-distilled capture:** the nightly consolidation pass (M3: "timeline-first, organize later") reads the session log and proposes episodic entries. Timeline first — organize later — because organizing at write time is where v1's bugs lived. [HC]

### 2.2 Extract

The extraction step converts conversation into candidate facts. Rules:
- **Atomic facts only:** one claim per memory. "Owais's GitHub username is IaMNOo0B" — not a paragraph.
- **Hard char caps** (M1): no memory longer than 500 chars at capture. Longer content gets summarized or stays in the session log.
- **Confidence attached at birth:** every candidate carries `confidence` (0–1, from the extractor) and `source`. No memory exists without both — this is the field that makes quarantine and decay possible. [HC]

### 2.3 Resolve — the mem0 two-phase gate

Against existing memories, each candidate is classified (mem0's ADD/UPDATE/DELETE/NOOP, the converged pattern):

| Operation | Meaning | Example |
|---|---|---|
| **ADD** | genuinely new fact | "Owais got a new phone number" |
| **UPDATE** | replaces an existing fact | new phone number replaces old |
| **DELETE** | invalidates an existing fact | "Owais no longer uses Telegram" |
| **NOOP** | duplicate or already-known | drop it, don't store twice |

The gate runs against the semantic store with hybrid retrieval (§4) to find candidates for UPDATE/DELETE matching. **Dedup is a retrieval problem, not a string problem** — "his GPU" and "the RTX 2060" must resolve to the same fact. [HC — mem0 mechanism verified in prior studies]

### 2.4 The quarantine gate (C-S6 fix) [CRITICAL]

This is the stage v1 lacked entirely. **Untrusted content never auto-promotes.**

- **Provenance tiers:** `user` (highest — direct statements) > `inferred` (brain-extracted from conversation) > `tool` (from tool outputs) > `web` (from web content, lowest).
- **The rule:** anything with `source IN ('tool', 'web')` enters quarantine — retrievable for factual questions, **never auto-acted on, never promoted to behavioral facts**. A web page cannot teach JARVIS a new preference. A tool result cannot become a standing instruction.
- **Promotion requires:** either explicit user confirmation ("yes, remember that") or a second independent source corroborating the fact. Quarantined facts carry a visible marker in the GUI viewer (M1).
- **Memory poisoning kill chain:** C-S6's attack was injected content → `save_learned_knowledge` → trusted context → permanent backdoor. The pipeline breaks it at two points: provenance tagging at capture (§2.1) and the quarantine gate here. Both must hold — defense in depth, not a single check. [VC — this is the direct fix for a v1 critical]

### 2.5 Store

Writes go to the semantic table (SQLite, WAL) per the durability spec (§5). Vectors go to the vector store behind the `VectorStore` protocol (learn-databases.md T2: Chroma embedded, swappable for Qdrant). **Text is the source of truth; vectors are an index.** If the vector store is lost, it rebuilds from SQLite. [HC]

---

## 3. The tier system

Three tiers, borrowed from letta (core/recall/archival) and cog (hot/warm/glacier). The purpose is one number: **what's in the prompt right now.** [HC on the tier pattern; specific sizes are PROPOSED]

### 3.1 Hot — always in context

- **Budget:** <50 lines, always loaded (cog's rule). This is the brain's working memory of *you*.
- **Contents:** identity facts (name, language preference, key constraints), current open loops (unfinished tasks, pending confirmations), today's context.
- **Rule:** hot memory is loaded at session start, not retrieved per turn. If it doesn't fit in 50 lines, it doesn't belong in hot — demote it.

### 3.2 Warm — retrieved on demand

- **Contents:** the bulk of semantic memory. Retrieved via hybrid search (§4) when relevant to the current turn.
- **Rule:** the brain receives **pointers + snippets, not dumps.** Retrieval returns (memory_id, snippet, relevance_score); the brain requests full text only for the top hits it actually uses. This is progressive disclosure applied to memory (SKILL.md pattern, A6).

### 3.3 Archival — summarized, searchable

- **Contents:** old episodic records (>1 year), superseded facts, consolidated summaries.
- **Rule:** archival memories are retrievable but never auto-loaded. Summaries are generated at compaction, not at query time.

### 3.4 Promotion / demotion — ECAN-lite attention economics

Borrowed from the AtomSpace study (attention economics, ideas-only license — mechanism, not code):

- **Every memory has attention rent:** each retrieval boosts its importance; each month without retrieval decays it.
- **Promotion:** warm → hot when retrieved in ≥3 sessions within 30 days (three-gate promotion pattern from cog). Demotion: hot → warm when unused for 60 days.
- **The 4-tier decay lifecycle** (M1): active → fading → dormant → archived. Transitions are logged, visible in the GUI viewer, and reversible — decay is forgetting-with-a-paper-trail, not silent loss.
- **Frozen per-session snapshots** (M1): what was in hot at session start is recorded. If a memory is later found wrong, the snapshot shows when it entered — the audit trail for memory debugging. [HC on the mechanism; the exact thresholds are PROPOSED]

### 3.5 Evolution with quarantine (A-MEM pattern, guarded)

A-MEM's insight: memories should *evolve* — new observations refine old facts. The danger (flagged in the A-MEM study): **evolution amplifies poisoning** — an injected "fact" gets refined into a stronger injected fact.

- **The guard:** evolution passes (merging related memories, updating confidences) run **only on non-quarantined memories.** Quarantined facts are excluded from the evolution pass entirely.
- **Confidence compounding:** when two independent sources agree, confidence rises; when a fact is contradicted, it drops and the contradiction is flagged for user review — never silently resolved. [HC]

---

## 4. Retrieval

### 4.1 The pipeline [HC — from learn-databases.md T3]

```
query → BM25 top-50 (SQLite FTS5) + vector top-50 (Chroma)
      → RRF fuse (k=60) → ~50–100 candidates
      → cross-encoder rerank (bge-reranker-v2-m3, local CPU) → top 5–10
      → brain receives pointers + snippets
```

- **Recall target: 91%** (hybrid measured: dense-only 78%, BM25-only 65%, hybrid 91%). This is a measured-from-literature target to be re-verified on JARVIS's corpus (learn-databases.md T3, [MC] on the exact number).
- **The same metadata filters on both legs** (learn-databases.md T6): `profile_id` is a required argument on every retrieval call. A forgotten filter is a leak — the wrapper enforces it, not the caller's memory.
- **Provenance-aware ranking:** quarantined facts are down-weighted in retrieval for action-driving queries, full-weight for factual questions. The brain sees the quarantine marker on every returned memory. [HC]

### 4.2 Chunking for memory content

- **Semantic facts:** one fact = one record. No chunking needed — atomicity is enforced at capture (§2.2).
- **Episodic summaries and documents:** recursive chunking, 256–512 tokens, 10–20% overlap, never split mid-function for code (learn-databases.md T4). Chunker name + version in metadata for re-chunking.
- **Chat turns:** turn-based chunks (user+assistant = 1 chunk) with conversation title prepended — sentence-window chunking destroys dialogue structure. [HC]

### 4.3 What the brain receives

Never a dump. The retrieval response is:

```
(memory_id, snippet ≤200 chars, relevance, source, confidence, quarantine_flag)
```

The brain cites `memory_id` when it uses a memory — and the session log records which memories influenced which turn. This is the "show receipts" doctrine applied to memory, and it makes the wake-quiz possible (scout-final-report: verify what was retained vs forgotten). [HC]

---

## 5. Durability — the R6 fixes

This section exists because v1's memory died in six different ways. Every clause below maps to a corpse in §8. [VC — R6 is the established requirement]

### 5.1 Atomic writes (kills C-I2, H-S11)

- **Every write:** temp file → fsync → atomic rename. No exceptions. `open(path, "w")` on a live database file is forbidden by code review rule.
- **SQLite specifically:** WAL mode + `synchronous=NORMAL` (crash-safe) or `FULL` (paranoid). `PRAGMA journal_mode=WAL` set on every connection. Writes go through one writer behind a lock.
- **Corrupt load → restore backup + warn, never silent empty.** v1's `except: return []` is the canonical example of a "helpful" fallback that destroys data. The load path: try primary → on corruption, restore last-good backup → warn the user visibly → log the incident. Returning empty is not an option. [VC]

### 5.2 Backups (kills H-S11)

- **Live backup via the SQLite backup API** (`VACUUM INTO` or `Connection.backup()`) — never `shutil.copy` a hot WAL-mode DB.
- **Rotation:** 7 daily + 4 weekly in `%APPDATA%\JARVIS\backups\`. Verified with `PRAGMA integrity_check` on restore — "a backup never restored is a hope" (learn-databases.md T1).
- **Priority order:** SQLite (memories + sessions, irreplaceable) > vector files (rebuildable from SQLite by re-embedding). [HC]

### 5.3 Locking (kills C-I3, H-S12)

- **Single-writer discipline:** one write connection behind a threading lock. `busy_timeout=5000` on all connections.
- **Single-instance enforcement that actually enforces:** v1's `QLockFile.tryLock(100)` warned and continued — the spec requires it to **exit** on lock failure. Two instances writing the same DB is not a degraded mode, it's a refusal-to-start.
- **Cross-process:** if the phone channel (Telegram) ever writes directly, it goes through the same single-writer queue — no second writer, ever. [VC]

### 5.4 Data-dir paths (kills H-S13)

- **All memory paths via `paths.user_file()`** (data dir: `%APPDATA%\JARVIS`). Repo-relative `memory_bank/` is forbidden — the frozen install under Program Files is read-only and the app must start there.
- **Schema versioning:** `PRAGMA user_version`, forward-only migrations at startup, tested on a copy first (learn-databases.md T1). [HC]

### 5.5 Write-failure isolation (kills M-I20)

- **A failed memory write never aborts a turn.** The write path catches IOError (disk-full, permissions), logs it, warns the user once, and continues. v1's `_save` with no try/except turned a full disk into a dead assistant — the spec inverts the priority: the conversation is the product, the memory write is best-effort with a retry queue.
- **Failed writes go to a retry queue** (durable, in the DB itself), not to `/dev/null`. [VC]

### 5.6 Bounded growth (kills M-I21)

- **Hard caps** (M1): semantic store ≤10,000 facts (PROPOSED — revisit trigger at 5,000), episodic ≤100,000 events before forced compaction (PROPOSED).
- **Compaction is not deletion:** compacted content becomes archival summaries (§3.3). The cap triggers the nightly consolidation pass (M3), not data loss.
- **No O(n) full-file re-parse:** SQLite indexes replace v1's JSON-file scan. Search is indexed or it doesn't ship. [VC]

---

## 6. Forgetting

Forgetting is a feature, not a failure mode — but it must be deliberate, complete, and verifiable. [HC on the checklist approach; the privacy-engineering study is the source]

### 6.1 The right to be forgotten

"Forget that" is a direct command with immediate effect on the semantic store. The 13-item deletion checklist (from `learn-privacy-engineering.md`):

1. SQLite `memories` row deleted (not flagged — deleted)
2. FTS5 index entry removed (FTS5 keeps token copies; `DELETE FROM chunks_fts` must run)
3. Vector store entry deleted (Chroma delete by ID)
4. Episodic records referencing the fact flagged superseded (events aren't rewritten, but the fact link is severed)
5. Hot-tier cache invalidated (in-memory copy dropped)
6. Session snapshots referencing it annotated (snapshots are audit trails — annotated, not edited)
7. Backups: tombstone recorded (backups are point-in-time; the tombstone ensures restores don't resurrect it)
8. Reranker/index caches cleared
9. Export/sync copies: deletion propagates on next sync (tombstones propagate — privacy-engineering §sync)
10. Logs: memory content redacted from logs (log redaction, R9)
11. The `until:` expiry index entry removed
12. GUI viewer reflects the deletion immediately
13. **Verification:** a retrieval query for the forgotten fact returns empty across all three tiers — the delete is tested, not assumed. [VC — "DELETE FROM isn't enough" is the established finding]

### 6.2 Temporal expiry — `until:` dates (cog pattern)

- Every memory may carry `expires_at`. On expiry, the memory demotes to archival (facts) or is summarized (episodic) — expiry is not silent deletion, it's a transition with a log entry.
- **Examples:** "Owais is traveling this week" (`until:` +7 days). "The meeting is at 3pm" (`until:` the meeting time).
- The nightly consolidation pass processes expiries. [HC]

### 6.3 What "delete" means across stores

| Store | Delete means |
|---|---|
| SQLite (source of truth) | Row deleted + `VACUUM` periodically to reclaim freelist pages + `wal_checkpoint(TRUNCATE)` |
| FTS5 | Delete from the FTS table (token copies gone) |
| Vector store | Delete by ID; index rebuilt if the store doesn't support true deletion |
| Backups | Tombstone; restore replays the tombstone |
| Session log | Annotated, never rewritten (audit integrity) |

SSD wear-leveling means physical erasure isn't guaranteed — BitLocker is the last line (privacy-engineering honest bounds). [HC]

---

## 7. The failure table — every v1 memory corpse → the clause that prevents it

| Corpse | v1 failure | Spec clause |
|---|---|---|
| **C-S6** (CRITICAL) | Injected content saved as trusted memory, no provenance, no quarantine → permanent backdoor | §2.4 quarantine gate: provenance tiers, tool/web sources quarantined, promotion requires corroboration or user confirmation |
| **C-I2** (CRITICAL) | Non-atomic write; crash mid-save wipes all memories | §5.1: temp → fsync → atomic rename; WAL mode; corrupt load restores backup + warns, never returns empty |
| **C-I3** (CRITICAL) | Two instances, interleaved writes → total memory loss | §5.3: single-writer lock; lock-file failure EXITS, never warns-and-continues |
| **H-S11** (HIGH) | Corrupt JSON → `except: return []` → silent total irreversible loss, no backup | §5.1 + §5.2: backup rotation with integrity checks; corrupt load → restore + warn |
| **H-S12** (HIGH) | No file locking; parallel saves → last-wins, entries lost | §5.3: single-writer discipline, `busy_timeout`, one write connection |
| **H-S13** (HIGH) | Hardcoded repo-relative `memory_bank/` → frozen install can't start | §5.4: all paths via `paths.user_file()`; repo-relative paths forbidden |
| **M-I20** (MEDIUM) | `_save` no try/except; disk-full aborts the entire turn | §5.5: write failures isolated, logged, retried from a durable queue; turn continues |
| **M-I21** (MEDIUM) | Unbounded growth; O(n) re-parse; fills small drives | §5.6: hard caps trigger consolidation; SQLite indexes replace file scans |

*Note: the task brief listed "M-S13" as a memory corpse; the autopsy shows M-S13 is `clipboard_set` (not memory-related). The repo-relative-path corpse is H-S13, covered above. No orphans — every memory-path corpse in the autopsy maps to a clause.* [VC — verified against FAILURE-ANALYSIS.md]

---

## 8. Storage schema sketch

From learn-databases.md T1, extended with the pipeline's fields:

```sql
CREATE TABLE memories (
  id INTEGER PRIMARY KEY,
  key TEXT UNIQUE,                 -- stable identifier for UPDATE matching
  fact TEXT NOT NULL CHECK(length(fact) <= 500),  -- hard cap at the DB level (M1)
  embedding_id TEXT,               -- FK into vector store (vectors are an index, not the truth)
  source TEXT NOT NULL CHECK(source IN ('user','inferred','tool','web')),
  provenance TEXT NOT NULL,        -- free-text: which turn/tool/page produced this
  confidence REAL NOT NULL, importance REAL NOT NULL DEFAULT 0.5,
  tier TEXT NOT NULL DEFAULT 'warm' CHECK(tier IN ('hot','warm','archival')),
  quarantined INTEGER NOT NULL DEFAULT 0,  -- §2.4 gate
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  expires_at TEXT,                 -- cog until: (§6.2)
  superseded_by INTEGER REFERENCES memories(id),
  tenant_id TEXT NOT NULL DEFAULT 'owais'  -- §4.1: required filter
);
CREATE TABLE episodic (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL, ts TEXT NOT NULL,
  summary TEXT NOT NULL,           -- distilled, not the raw log
  event_ids TEXT NOT NULL,         -- JSON: session-store event IDs this summarizes
  importance REAL NOT NULL DEFAULT 0.5,
  created_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE memories_fts USING fts5(fact, content='memories', content_rowid='id');
```

Migrations via `PRAGMA user_version`, forward-only, tested on a copy (learn-databases.md T1). [HC]

---

## 9. The GUI viewer (M1: "What JARVIS remembers")

The memory system is user-visible, not a black box:

- **"What JARVIS remembers" Settings tab:** browse hot/warm/archival, see provenance + confidence + quarantine markers on every fact.
- **User actions:** edit (creates an UPDATE via the pipeline), delete (runs the 13-item checklist, §6.1), quarantine/unquarantine (with confirmation).
- **The wake-quiz** (scout-final-report §71): periodic verification of what was retained vs forgotten — "verify before claiming" applied to memory itself. [HC — M1 decision]

---

## 10. Open questions

1. **The 10,000-fact cap** — PROPOSED. The real number depends on retrieval quality at scale; the revisit trigger (5,000 facts) forces a measurement before the cap binds. [UK]
2. **Extractor model choice** — the Hermes review loop needs a cheap local model. BitNet 1-bit on CPU is the candidate (efficiency-gems study); unvalidated for extraction quality. [UK]
3. **Hinglish in embeddings** — nomic-embed-text quality on code-switched memory text is unmeasured (learn-databases.md gap #2). The Hinglish golden set (Cycle 8) is the measurement vehicle. [UK]
4. **Multi-profile** — the `tenant_id` mechanism is built; whether family profiles ever need it is unknown. Per-profile SQLite files are the escalation path (learn-databases.md T6). [UK]
5. **Quarantine UX** — how quarantined facts appear to Owais without training him to ignore the markers (the rubber-stamping problem from the threat model). Needs real usage to tune. [UK]

---

## 11. Confidence summary

- **[VC]:** the C-S6 quarantine fix, R6 durability clauses, the corpse→clause mapping (verified against the autopsy), the 13-item deletion checklist mechanics.
- **[HC]:** two-store split, mem0 ADD/UPDATE/DELETE/NOOP, tier system, hybrid retrieval pipeline, schema shape, ECAN-lite decay, A-MEM evolution-with-quarantine.
- **[MC]:** the 91% recall target (single benchmark source), exact tier thresholds (50 lines, 30-day/60-day), the 10,000-fact cap.
- **[SP]:** none — no speculative claims in this spec.
- **[UK]:** the five open questions above.

---

## Sources

- `~/workspace/jarvis-knowledge/learn-databases.md` (T1–T6: SQLite WAL, Chroma, hybrid search, chunking, eval, isolation)
- `~/workspace/jarvis-build/FAILURE-ANALYSIS.md` (C-S6, C-I2, C-I3, H-S11, H-S12, H-S13, M-I20, M-I21; R6)
- `~/workspace/jarvis-knowledge/DECISION-PLAYBOOK.md` (M1–M4 memory decisions)
- `~/workspace/jarvis-knowledge/learn-privacy-engineering.md` (13-item deletion checklist, tombstones, secure deletion)
- `~/workspace/jarvis-knowledge/learn-session-store.md` (R15 — feeds episodic; read alongside)
- Prior studies (general knowledge): mem0 (two-phase ADD/UPDATE/DELETE/NOOP), letta (core/recall/archival, superseding), A-MEM (evolution + poisoning amplification warning), cog (hot/warm/glacier, `until:` expiry, three-gate promotion) — patterns only, per license posture (cog MIT = borrowable; mem0/letta Apache-2.0 = borrowable; A-MEM MIT paper = ideas).

*Honest completion (Rule 12): Researched: 4 source files read in full + prior indexed studies referenced. Validated: corpse IDs cross-checked against FAILURE-ANALYSIS.md (including the M-S13→H-S13 correction). Saved: 1 file. Tested/Measured: nothing — design spec, unbuilt. Blocked: none.*
