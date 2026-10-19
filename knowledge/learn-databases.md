# Databases & Knowledge Retrieval — Learning Notes (JARVIS Master Curriculum, Domain K)

*Research date: 2026-10-19. Learning ONLY — no code written, no packages installed.*
*Skipped as already covered: RAG fundamentals (TF-IDF, chunk→embed→retrieve, cosine similarity), basic chunking + overlap, Chroma-as-upgrade-path, nomic-embed-text via Ollama — all in `~/workspace/learning/rag/`. Everything below is new.*

---

## T1. PostgreSQL vs SQLite for a Personal Agent

### Purpose
Decide which relational store underpins JARVIS v2's durable state (sessions, memory, skills registry, schedules). Wrong choice = either operational overhead (PG) or a concurrency/corruption wall (SQLite).

### How it works internally (the real difference)
- **SQLite** is an in-process library: your app *is* the database. One file, zero-config, no server. WAL mode (write-ahead logging): writes append to a `-wal` file, checkpoint copies them into the DB; readers never block the writer and vice versa. Still **one writer at a time** — concurrent writes serialize via `busy_timeout`.
- **PostgreSQL** is a client-server DBMS: MVCC (multi-version concurrency control) gives every transaction a snapshot; writers never block readers and row-level locks let many writers proceed. Extensions (pgvector, pg_trgm, PostGIS), roles/RBAC, streaming + logical replication, WAL archiving → point-in-time recovery (PITR).

### The verdict for JARVIS (single-user, on-device, Windows)
**Start with SQLite (WAL mode).** JARVIS is a personal agent: one user, one process tree, writes dominated by background jobs (memory writes, scheduler ticks). SQLite with WAL + `busy_timeout=5000` + single-writer discipline handles 5k–10k req/s — orders of magnitude above what a personal assistant generates. Zero installer burden (critical for the "normal exe installer" requirement), database = one file in `%APPDATA%\JARVIS`, backup = file copy.

**PostgreSQL wins only if:** (a) multiple processes write heavily and concurrently (e.g., PC agent + phone bot + cloud relay all writing at once with conflicts — still likely fine on SQLite/WAL at personal scale), (b) you need pgvector's mature HNSW + hybrid search in one engine, (c) row-level security for multi-user, (d) replication/PITR. None of these are day-1 JARVIS requirements. The v2 thesis is "dependable beats impressive" — PG is a server Owais must install, monitor, and back up; SQLite is invisible.

Decision rule (sourced): single user / embedded / zero-ops → SQLite. Multi-user, concurrent writers, advanced features → PostgreSQL. Revisit at >1M memory chunks or genuine multi-device write contention.

### Schemas for agent state (SQLite, starting design)
```sql
-- Schema versioning: PRAGMA user_version = N; migrations run at startup in order.
CREATE TABLE sessions (          -- append-only event log (R15 candidate)
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL, ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  role TEXT NOT NULL,            -- user|assistant|tool|system
  content TEXT NOT NULL,
  metadata TEXT                  -- JSON: tool calls, citations, model, tokens
);
CREATE INDEX idx_sessions_session_ts ON sessions(session_id, ts);

CREATE TABLE memories (          -- semantic store (mem0 two-phase gate writes here)
  id INTEGER PRIMARY KEY,
  key TEXT UNIQUE,                -- stable identifier
  fact TEXT NOT NULL,             -- the memory text
  embedding BLOB,                 -- serialized vector (if SQLite-side ANN) or NULL (if external store)
  source TEXT NOT NULL,           -- user|inferred|tool|web  (provenance → poisoning quarantine)
  confidence REAL, importance REAL,
  created_at TEXT, updated_at TEXT, expires_at TEXT,  -- cog-style temporal markers
  superseded_by INTEGER REFERENCES memories(id)
);
CREATE TABLE chunks (             -- RAG corpus
  id INTEGER PRIMARY KEY,
  doc_id TEXT NOT NULL, chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  metadata TEXT,                  -- JSON: source, tenant, language, chunker, model_version
  embedding_id TEXT               -- FK into vector store (keeps ANN out of SQLite if desired)
);
-- Full-text sidecar for hybrid search:
CREATE VIRTUAL TABLE chunks_fts USING fts5(content, content='chunks', content_rowid='id');
```
Notes: keep vectors in a dedicated store (Chroma/Qdrant file) or pgvector later; SQLite FTS5 (`bm25()` rank function) covers the sparse/BM25 leg of hybrid search today. `PRAGMA foreign_keys=ON` on every connection. One write connection behind a lock; reads can share connections.

### Migrations (lightweight, no Alembic needed)
- Track schema version in `PRAGMA user_version` (integer in the DB header).
- At startup: read version, run numbered `migrations/NNNN_description.sql` in order inside a single transaction, bump `user_version`. Migrations are forward-only, idempotent-guarded (`IF NOT EXISTS`), and tested on a copy first.
- Failure mode it prevents: v1-style silent corruption where a settings rewrite changed types. Migration scripts must be reviewed like code (they run with full DB privileges).

### Backups
- **Live backup:** never `shutil.copy` a hot WAL-mode DB — use SQLite's online backup API (`VACUUM INTO 'backup.db'` or `sqlite3.Connection.backup()`) which copies a consistent snapshot while the app runs.
- **Rotation:** keep N timestamped backups (e.g., 7 daily + 4 weekly) in `%APPDATA%\JARVIS\backups\`; verify with `PRAGMA integrity_check` on restore — "a backup never restored is a hope."
- JARVIS-specific: memories + sessions are the irreplaceable data; the vector index can be rebuilt from `chunks` (re-embed), so backup priority is SQLite > vector files.
- Optional later: Litestream-style continuous WAL replication is overkill for a single-user desktop app; skip.

### Libraries
- `sqlite3` (stdlib) — fine; consider `apsw` for full API control (backup API, virtual tables).
- Migrations: hand-rolled `user_version` runner (~60 lines) or `yoyo-migrations` / `alembic` (heavy; avoid for v1).
- Official docs: sqlite.org — [WAL mode](https://www.sqlite.org/wal.html), [backup API](https://www.sqlite.org/backup.html), [FTS5](https://www.sqlite.org/fts5.html), [PRAGMA user_version](https://www.sqlite.org/pragma.html#pragma_user_version).

### Limitations / trade-offs
- One writer at a time (serialize writes or hit `SQLITE_BUSY`); no network access (good for privacy, bad for multi-device without sync layer); no stored procedures; FTS5 is BM25-capable but not a full search engine (no distributed anything — fine at this scale).
- Corruption risk is real but overstated: WAL + `synchronous=NORMAL` is crash-safe; corruption historically comes from network filesystems (never put the DB on a network drive) and copying hot files (use the backup API).

### Security implications
- File-level security only: the DB file inherits NTFS ACLs — store under the user's profile, never in a shared/temp dir. Secrets (API keys) do **not** belong in the DB — OS keyring per AGENTS.md. `PRAGMA key` (SQLCipher) is an option for at-rest encryption of memories; weigh against complexity.
- Injection: parameterize everything; the agent must never concatenate tool output into SQL.

### Common failure modes
1. Copying a hot DB file → corrupt backup. Fix: backup API / `VACUUM INTO`.
2. Forgetting WAL on one connection → readers block writers. Fix: set PRAGMAs on every connect (they're per-connection, except journal_mode which persists).
3. Schema drift across app versions → fix with `user_version` migrations.
4. Write contention from multiple threads → single-writer lock.

### Confidence: [HC] 80–95%, measured from official SQLite docs + multiple 2025–2026 production guides.
### Unknown: exact write throughput on Owais's disk (measure, don't assume); whether future multi-device sync needs CRDTs vs last-write-wins.

---

## T2. Vector DBs: pgvector vs Qdrant vs Chroma (on-device trade-offs)

### Purpose
Pick the ANN (approximate nearest neighbor) store for JARVIS's semantic memory + document retrieval. This is the "meaning search" layer.

### How it works internally (all three)
All use **HNSW** (Hierarchical Navigable Small World) graphs: multi-layer graphs where each vector links to its nearest neighbors; search descends layers for ~log(n) approximate nearest-neighbor lookup. The databases differ in everything *around* the index: storage engine, filtering, ops model.

| | **pgvector** | **Qdrant** | **Chroma** |
|---|---|---|---|
| What it is | PostgreSQL extension (`vector` type) | Standalone Rust server | Python library (embedded or server) |
| License | PostgreSQL license (open) | Apache-2.0 | Apache-2.0 |
| p50/p99 @ 1M×1536d (Q1 2026 bench) | 18ms / 90ms | 4ms / 25ms | 12ms / 70ms |
| Filtered search | Post-filter via SQL WHERE (correct but slower) | **Pre-filter** inside HNSW traversal (fastest filtered) | Python-side (slowest) |
| Hybrid search | Manual: tsvector + vector, merge in app | Native sparse+dense + DBSF fusion | Keyword search is Cloud-only; local = manual |
| Multi-tenancy | Schemas/tables/RLS | Collections + `is_tenant` payload index | Collections only |
| Max reliable scale | ~10–50M vectors | Billions (distributed) | ~500k–1M (single node) |
| Concurrency | PG MVCC (excellent) | Good | Single-process (poor) |
| Durability | WAL + PITR | Snapshots | SQLite+WAL (local) |
| Auth | PG roles + RLS | JWT/API key (default instance is OPEN) | None in 1.x local |

*(Benchmark figures are community-reported approximations, Q1 2026; treat as order-of-magnitude, not gospel. The consistent finding across sources: Qdrant fastest filtered queries, pgvector best when PG already exists, Chroma fastest to prototype but not production-grade.)*

### The verdict for JARVIS (single-user, RTX 2060, Windows, zero-ops)
**Chroma (embedded) for v1, with the storage interface abstracted so Qdrant can replace it.** Reasons:
- Zero infrastructure: `pip install chromadb`, persistent local dir — matches the zero-terminal installer story. A Qdrant server is a second daemon to supervise (violates "dependable beats impressive" for a personal app); pgvector requires PostgreSQL (rejected in T1).
- Scale reality: JARVIS's corpus is 10k–500k chunks (memories, docs, chat history). Chroma is reliable in this band; its failure modes (poor concurrency, no auth) don't bite a single-user local app.
- The interface boundary matters more than the choice: hide the store behind a `VectorStore` protocol (upsert/search/delete/filter). Migration later = re-embed + backfill, no brain surgery.
- **Revisit trigger:** corpus >1M chunks, need for pre-filtered multi-tenant search, or Qdrant's quantization (INT8: ~4× RAM reduction — 160MB vs 600MB per 100k×1536d) becomes necessary. On a 16GB machine this is not day-1.

### Embeddings (the other half of the decision)
- Local default: `nomic-embed-text` via Ollama/llama-server (already in the plan; ~137M params, runs on CPU/GPU, 8192 ctx).
- **Re-embed when you change models** — vectors from different models are not comparable. Version the index (`embedding_model` in metadata); migration = re-embed corpus.

### Official docs
- pgvector: https://github.com/pgvector/pgvector · Qdrant: https://qdrant.tech/documentation/ · Chroma: https://docs.trychroma.com/

### Limitations / trade-offs
- Chroma: no auth (fine locally, never expose to network), single-process writes, keyword search only in Cloud tier (do BM25 via SQLite FTS5 — see T3), longest index build times in benchmarks.
- Qdrant: operational weight (Docker/service), default-open instance (must set API key), payload JWT claims for tenant scoping deprecated in v1.16+ — tenant filter is the app's job.
- pgvector: needs PostgreSQL; filtered queries are post-filter (recall suffers when the filter is selective — must over-fetch).

### Security implications
- **Never bind any vector DB to a network interface** on the user's PC (localhost hijack CVE-2026-65105 pattern: unauthenticated local APIs are an attack surface). Embedded Chroma = no port at all — a security feature, not just convenience.
- Embeddings are reversible-ish: they leak semantic content. Treat the vector store with the same sensitivity as the source text (file ACLs, no cloud sync without encryption).

### Common failure modes
1. Changing embedding models without re-indexing → silently degraded retrieval (vectors incomparable across models).
2. HNSW `ef`/`M` left at defaults for filtered workloads → recall collapse; tune per workload.
3. Post-filter with selective filters → returns fewer than k results; fix with pre-filtering (Qdrant) or over-fetch ×5 then filter.
4. Quantization without measuring recall loss → INT8/binary is great for RAM but verify recall@k on your eval set.

### Confidence: [HC] on architecture/license facts; [MC] on benchmark numbers (community sources, methodology varies).
### Unknown: Chroma 1.x long-term maintenance trajectory; exact HNSW recall on Hinglish-mixed corpora (measure with T4 eval).

---

## T3. Hybrid Search (dense + BM25) and Reranking

### Purpose
Pure vector search misses exact identifiers (error codes, names, SKUs, function names); pure BM25 misses paraphrase ("money back" → "refund"). Production RAG uses both. Measured: dense-only 78% recall@10, BM25-only 65%, **hybrid 91%** (+6ms p50 latency). ~72% of production RAG systems use hybrid.

### How it works internally
1. **Two retrievers, one corpus:** dense (HNSW over embeddings) + sparse (BM25 over an inverted index — SQLite FTS5 or pg tsvector or Tantivy).
2. **Fusion:** **Reciprocal Rank Fusion (RRF)** merges ranked lists using ranks only (scores aren't comparable across systems): `score(d) = Σ 1/(k + rank_i)`, k=60 (original paper default). Robust, hard to misconfigure. Qdrant also offers DBSF (Distribution-Based Score Fusion — normalizes by score distribution; better when one retriever's scores have much higher variance).
3. **Rerank:** retrieve 50–150 candidates cheaply (recall stage), then a **cross-encoder** reads query+candidate *jointly* (bi-encoders process them separately) and scores relevance. Keep top 5–10 (precision stage). Anthropic's study: reranking cut failures 2.9% → 1.9% — the largest cheap gain in the pipeline.

**The canonical pipeline:**
```
query → [optional rewrite] → BM25 top-50 + vector top-50 (same metadata filters on both)
      → RRF fuse → ~50–100 candidates → cross-encoder rerank → top 5–10
      → LLM answers with citations
```

### JARVIS application
- **BM25 leg:** SQLite FTS5 table over `chunks` (`bm25()` rank function) — zero new infrastructure. pgvector path would use `tsvector`/`ts_rank_cd` instead.
- **Dense leg:** Chroma (T2).
- **Reranker (local, CPU):** `BAAI/bge-reranker-v2-m3` (~568M params, multilingual — matters for Hinglish) via `sentence_transformers.CrossEncoder`, or **FlashRank** (quantized cross-encoders, sub-100ms on CPU) for tighter budgets. ~80ms per 50 candidates on CPU when batched (batch 32, load model once per process — reloading costs 3–8s).
- **Guardrails:** filter (tenant/permissions/date) BEFORE fusion — "a prompt saying 'don't mention confidential docs' is not access control." Never multiply reranker scores by hand-tuned heuristics (recency × term-match etc.) — it silently inverts relevance; use tie-breaks only.
- **Query rewriting** (fixes vocabulary mismatch before search): (a) conversational rewrite — resolve "what about the second one?" via LLM; (b) **HyDE** — generate a hypothetical answer, embed *that* instead of the question (helps when the answer's vocabulary differs from the question's); (c) multi-query fan-out (costs ~400ms+ per extra query — off by default, enable for hard queries). All three need eval (T4) to prove they help *your* corpus.

### Libraries
- `rank-bm25` or SQLite FTS5 (prefer FTS5 — no dependency, SQL-native).
- `sentence-transformers` CrossEncoder, `flashrank` (pip), `BAAI/bge-reranker-v2-m3`.
- RRF: ~8 lines of Python (see sources); no library needed.
- References: Anthropic contextual retrieval study (contextualize-each-chunk: +49% failure reduction in their tests — prepend chunk with 1–2 sentences of document context before embedding; costs LLM calls at ingest); SMARTCHUNK (ICLR 2026) benchmark comparisons.

### Limitations / trade-offs
- Reranking adds 50–200ms latency; skip for batch/high-throughput paths.
- Cross-encoder max_length=512: chunks longer than 512 tokens get silently truncated — re-chunk for reranking or use long-context rerankers (Jina ColBERT-v2).
- Reranker scores are NOT calibrated probabilities — never show "82% relevant" to the user.
- HyDE can hallucinate the hypothetical answer into a wrong neighborhood — eval-gated.

### Security implications
- Query rewriting uses an LLM on user input — the rewrite prompt must treat input as data (R2 instruction hierarchy).
- Reranker runs locally: no data exfiltration; hosted rerank APIs (Cohere/Voyage) send chunk text off-device — default to local for a privacy-first product.

### Common failure modes
1. Starving the reranker: fetching top-10 then reranking → the right doc was at rank 40. Fetch 100–150, rerank to 10.
2. Feeding it junk: one-message chunks ("yes let's do that") have no rerankable signal — prepend conversation title + neighbor context.
3. Tuning alpha globally instead of per query category (exact-match vs semantic vs mixed).
4. Forgetting the same metadata filters on both retrievers → cross-tenant leakage in the fused list.

### Confidence: [HC] on pipeline shape and RRF; [MC] on the exact recall numbers (single benchmark source, corpus-dependent — must re-measure).
### Unknown: optimal alpha per query category for JARVIS's corpus (measure); whether contextual retrieval's ingest cost pays off at personal scale (likely yes for docs, no for chat logs).

---

## T4. Chunking Strategies Compared (what works for code + docs)

### Purpose
Chunking is the #1 determinant of RAG quality (worse chunking → diluted embeddings → wrong retrieval). Choose per content type, not globally.

### The strategies
| Strategy | How | Best for | Cost |
|---|---|---|---|
| **Fixed-size** | Cut every N chars/tokens, optional overlap | Prototyping only | ~0 |
| **Recursive** (LangChain `RecursiveCharacterTextSplitter`) | Try separators in order: `\n\n` → `\n` → `. ` → ` ` → `""`; merge small pieces | General docs, articles, **code**, API refs | ~0 |
| **Semantic** (`SemanticChunker`) | Embed sentences, split where neighbor similarity drops | Dense technical/legal text with abrupt topic shifts | Embedding pass per sentence + threshold tuning |
| **Token-based** | Exact token counts via tokenizer | Tight context/cost budgets | Tokenizer dependency |
| **Parent-child** (`ParentDocumentRetriever`) | Retrieve small child (200 tok), return large parent (2000 tok) to LLM | Precision retrieval + rich context | 2× storage |
| **Proposition-level** | One atomic fact per chunk | Factoid QA, eval sets | LLM call per chunk |
| **Late chunking** | Embed whole doc with long-context model, slice embeddings after | Long docs where context spans chunks | Long-ctx embedder |
| **Contextual retrieval** (Anthropic) | Prepend 1–2 sentences of doc context to each chunk before embedding | Any corpus with ambiguous chunks | LLM calls at ingest |

Benchmark signal: semantic chunking up to ~70% lift over naive baselines on technical docs (vendor benchmark — treat as optimistic); recursive is the robust default ("best balance"); fixed-size is never the production answer.

### What actually works for code + docs (JARVIS's corpus)
- **Docs/prose:** recursive, **256–512 tokens, 10–20% overlap** (512/50–100). The v1 RAG used ~120 words/20 overlap — reasonable; bump to 256–512 tokens for richer context per the 2026 consensus.
- **Code:** recursive with **code-aware separators** (`\nclass `, `\ndef `, `\n\n`, `\n`, ` `) — never split mid-function. Better: AST-aware chunking (tree-sitter per language; one chunk per function/class + docstring). For JARVIS's own codebase search, function-level chunks + file-path metadata beat blind token windows.
- **Chat history/memory:** message-pair or turn-based chunks (user+assistant turn = 1 chunk) with conversation title prepended — sentence-window chunking destroys dialogue structure.
- **Rule of thumb from the field:** start recursive; switch to semantic only if recall metrics (T5) show clear deficiencies; add parent-child when answers need surrounding context.

### JARVIS application
- Store `chunker` + `chunker_version` + `embedding_model` in chunk metadata (T1 schema) so the corpus can be re-chunked without mystery.
- Re-chunking is cheap (CPU); re-embedding is the expensive part — version them independently.

### Libraries
- `langchain_text_splitters` (RecursiveCharacterTextSplitter, SemanticChunker), `chonkie` (modern chunking library), `tree-sitter` (code AST), `unstructured`/`LlamaParse` (PDF/complex docs).

### Limitations / trade-offs
- Overlap reduces boundary loss but inflates storage and duplicate retrieval — 10–20% is the sweet spot, not more.
- Semantic chunking needs a tuned breakpoint threshold per corpus; mis-tuned = worse than recursive.
- No chunking fixes a bad embedding model or missing metadata.

### Common failure modes
1. One global chunk size for mixed corpora (code + prose + tables).
2. Splitting tables mid-row (keep tables whole or use table-aware chunkers).
3. Chunks without provenance metadata (can't cite, can't filter, can't expire).
4. Evaluating chunking by "looks good" instead of retrieval metrics (T5).

### Confidence: [HC] on recursive-as-default and code-aware separators; [MC] on the 70% semantic-chunking figure (single vendor benchmark).
### Unknown: best chunker for Hinglish code-switched text (likely recursive is fine; semantic chunkers are English-tuned — verify).

---

## T5. RAG Evaluation: Retrieval Precision, Citation Grounding, Query Rewriting

### Purpose
Without eval, every RAG change is a guess. The v1 autopsy proved this: bugs lived for months because nothing measured them. Eval is the layer that would have caught C-B1, C-V1, C-B4.

### How it works internally — the three-layer cake
Each layer answers a different diagnostic question and points to a different repair:

**Layer 1 — Retrieval** (did the right chunks come back?)
- `hit_rate@k`, `recall@k`, `precision@k`, **MRR** (1/rank of first relevant), **nDCG@k** (rank-aware, graded relevance).
- **Context precision** (RAGAS): of retrieved chunks, how many were relevant (target ≥0.75).
- **Context recall** (RAGAS): of the info needed, how much was retrieved — needs a reference answer (target ≥0.80).

**Layer 2 — Generation** (did the model use the context faithfully?)
- **Faithfulness/groundedness**: decompose answer into atomic claims; % entailed by retrieved context (target ≥0.85) — the hallucination detector.
- **Answer relevancy**: reverse-generate questions from the answer, compare to the original (target ≥0.80) — catches "correct but off-topic."
- **Citation precision/recall**: are citations attached, and do they support the claims? (critical for JARVIS's "show receipts" doctrine).

**Layer 3 — End-to-end** (was the final answer good?)
- Answer correctness vs gold answer, **refusal calibration** (does it say "I don't know" when the corpus lacks the answer? — split golden set into answerable/unanswerable), task success, latency/token cost.

### The golden dataset (how you actually do it)
1. Collect 50–100 real questions from usage (or write them per capability).
2. For each: the question, the known-good answer, the chunk IDs that support it, and an answerable/unanswerable label.
3. Score every pipeline change against it. Promote user-flagged failures into the set (regression suite).
4. Frameworks: **RAGAS** (open-source, LLM-as-judge baseline), **DeepEval** (already in MASTER-INDEX I2 — "evals before users"), **TruLens**, Phoenix/Arize. RAGAS + SME review is the standard starting stack.

### Citation grounding (JARVIS-specific requirement)
- The generator must return `(claim → chunk_id)` mappings, not just text. Enforce in the prompt *and* verify post-hoc: every factual claim in the answer must have ≥1 supporting chunk, else flag.
- Failure mode it catches: the "Section 4.2" hallucination — a correct-looking answer with invented citations that string-match evals score as "correct."
- Store citations in the session log (T1 `sessions.metadata`) — the external session store (R15) makes post-hoc audit possible.

### Query rewriting eval
- A/B the pipeline with rewriting on/off on the golden set; rewriting must *prove* +recall before shipping (it's +400ms and another LLM call).
- Measure per query category (T3): rewriting helps conversational follow-ups most, exact-identifier queries least (rewriting can mangle SKUs/codes — add a "don't rewrite identifiers" rule).

### Libraries / references
- `ragas`, `deepeval`, `trulens-eval`; BEIR (retrieval benchmark suite); RAGAS docs: https://docs.ragas.io/
- The LLM-as-judge pattern has known bias (prefers its own outputs) — calibrate with human spot-checks on a sample.

### Limitations / trade-offs
- Eval needs the golden set — building it is real work (~1 day for 100 Q&A). No golden set = no eval = flying blind.
- LLM-as-judge costs tokens and has bias; deterministic metrics (hit_rate, MRR) are cheaper and should gate first.
- Metrics drift as the corpus grows — eval is continuous, not a launch gate.

### Security implications
- The golden set may contain sensitive user data — store it with the same protections as the DB (T1).
- Adversarial eval (prompt-injection queries in the golden set) doubles as a security regression suite (ties to SEC4/SEC7 in MASTER-INDEX).

### Common failure modes
1. End-to-end "looks good in the demo" without layer-wise scores → can't localize failures.
2. Optimizing the metric instead of the user (Goodhart) — keep human spot-checks.
3. No unanswerable questions in the set → refusal calibration never tested → confident hallucinations.

### Confidence: [HC] on the three-layer structure and RAGAS metrics; [MC] on target thresholds (community practice, corpus-dependent).
### Unknown: the actual golden-set questions for JARVIS (must be built from real usage); whether LLM-as-judge works reliably on Hinglish answers (spot-check).

---

## T6. Metadata Filtering & Per-User Isolation in One Local DB

### Purpose
Two jobs: (a) **retrieval-time filtering** — scope search by source, date, language, tenant before ranking; (b) **isolation** — guarantee one user's data never leaks into another's context. For JARVIS v2 (single user today, possibly family/multi-profile later), build the mechanism now, enforce it always.

### How it works internally
- **Filter-before-rank** (not post-filter): the metadata predicate (`tenant_id = X AND source = 'memory'`) constrains the candidate set *before* ANN traversal. Qdrant does this natively (payload indexes extend the HNSW graph — one traversal). pgvector: SQL `WHERE` then vector search (post-filter — over-fetch ×k to compensate). Chroma: `where={...}` metadata filter (Python-side, fine at local scale).
- **Qdrant's `is_tenant: true` payload index**: marks the tenant field so Qdrant co-locates one tenant's points — the documented best practice for multi-tenant single-collection design.
- **SQLite/pgvector equivalent**: `WHERE tenant_id = ?` on the chunks table; with pgvector + RLS (row-level security), the database *itself* enforces `current_setting('app.tenant')` — the filter can't be forgotten by application code.
- **Chroma**: collections per tenant (`client.get_or_create_collection(f"mem_{user_id}")`) — simple, hard isolation boundary; or `where={"tenant_id": ...}` within one collection.

### The isolation ladder (strongest → weakest)
1. **Separate databases/files per user** — strongest; trivial with SQLite (one file per profile). Slight ops cost, zero leak surface.
2. **RLS in PostgreSQL** — the DB enforces the tenant predicate even if the app forgets it. (Only available if PG is chosen — it isn't, T1.)
3. **Collection-per-tenant** (Chroma/Qdrant) — the collection name is the boundary; a bug can still pick the wrong collection, so wrap access in a tenant-scoped client.
4. **Payload/metadata filter per query** — weakest: one forgotten `where` clause leaks everything. Mandatory code review + a wrapper function that *requires* the tenant argument (no default) + eval probes that attempt cross-tenant retrieval.

### JARVIS application (single-user now, design for later)
- **Today:** one SQLite file + one Chroma collection. Still pass an explicit `tenant_id='owais'` (or `profile_id`) through every retrieval call — the habit is the protection. The wrapper: `retrieve(query, profile_id, filters)` with `profile_id` required positional.
- **Schema:** `tenant_id TEXT NOT NULL DEFAULT 'default'` on `chunks` and `memories` (T1) + index. FTS5 queries always include the tenant predicate.
- **If multi-profile later:** separate SQLite files per profile (ladder #1) — cheapest strong isolation on a single-user OS; no PG needed.
- **Eval:** add cross-tenant probe queries to the golden set (T5): "retrieve X's data as Y" must return empty. This is the test that catches the forgotten-filter bug class.
- **Memory poisoning tie-in:** `source` metadata (T1 schema) + quarantine — untrusted-source memories are filtered out of (or down-weighted in) retrieval for sensitive actions.

### Security implications
- "A prompt that says 'don't mention confidential documents' is not access control." Filters are authorization; prompts are suggestions.
- Qdrant's default instance is **open** (no auth) — if ever run as a service, set API key + bind 127.0.0.1 (localhost-hijack lesson, SEC2).
- JWT payload-scoped tenant claims in Qdrant were deprecated (v1.16+) — don't build on them; application-enforced filters + collection scoping instead.

### Common failure modes
1. Forgotten filter on one code path (the #1 real-world leak) → wrapper requires tenant, eval probes.
2. `OR` where `AND` was needed in filter composition → searches whole collection.
3. FTS5 and vector stores disagreeing on tenant scoping → apply the same filter object to both legs (T3).
4. Backup/restore mixing tenant files → per-profile backup dirs.

### Confidence: [HC] on the ladder and Qdrant/Chroma mechanisms (official docs); [MC] on RLS specifics (not directly applicable to the SQLite choice — documented for completeness).
### Unknown: whether JARVIS ever needs true multi-user (family profiles?) — if yes, re-evaluate PG + RLS vs per-profile SQLite files.

---

## Cross-topic connections (the connected understanding)

- **T1↔T2:** SQLite + Chroma-embedded = zero daemons; PG + pgvector = one daemon doing both jobs. The choice is coupled — don't pick PG "just for pgvector" unless T1's triggers fire.
- **T2↔T3:** The vector DB choice determines hybrid-search ergonomics (Qdrant native, pgvector manual, Chroma+FTS5 split). Reranking is DB-agnostic — it sits above all of them.
- **T3↔T4:** Chunking and retrieval are one system: parent-child chunking exists *because* retrieval wants small units and generation wants large context. Evaluate them together (T5).
- **T4↔T5:** You cannot choose a chunking strategy without retrieval metrics — "looks good" is not a method.
- **T3↔T6:** The same metadata filter must apply to BM25 and dense legs, or the fused list leaks across tenants.
- **T1↔T5:** The append-only session log (T1 schema) is what makes post-hoc eval and citation audit possible — eval needs the trace.
- **All → v2 thesis:** "Declaration beats orchestration" — declare the retrieval pipeline (retrievers, fusion, reranker, filters) as config; "dependable beats impressive" — SQLite+Chroma+FTS5+local reranker is boring, local, and auditable.

## Remaining knowledge gaps (for future missions)
1. Measured numbers on Owais's hardware: HNSW recall/latency for Chroma at 100k–500k chunks, bge-reranker-v2-m3 CPU latency on Ryzen 5 3600.
2. Hinglish corpus behavior: embedding quality (nomic-embed-text on code-switched text), semantic chunker thresholds, LLM-judge reliability.
3. The golden dataset itself (built from real usage, not researchable in advance).
4. LanceDB as a Chroma alternative (embedded, lower memory overhead — flagged in sources, not deeply evaluated).
5. Whether `sqlite-vec` / `sqlite-vss` (vector search *inside* SQLite) matures enough to collapse T1+T2 into one file — worth a revisit in 6–12 months.

## Sources consulted
- Official docs: sqlite.org (WAL, backup API, FTS5, pragmas), qdrant.tech/documentation, docs.trychroma.com, pgvector GitHub, docs.ragas.io
- Benchmarks: salttechno.ai Vector DB Benchmark 2026 (CC BY 4.0), aifoss.dev pgvector-vs-Chroma-vs-Qdrant local RAG 2026, jahanzaib.ai vector DB comparison 2026, arXiv 2608.12812 (empirical ANN evaluation)
- Practice guides: Anthropic contextual retrieval findings (via secondary sources), RRF original paper (k=60), aiworkflowlab.dev hybrid+RRF guide, futureagi.com RAG eval 2026, llmbook.icsgen-ai.org §43.1
- All benchmark figures treated as approximate/community-reported; no fabricated numbers.
