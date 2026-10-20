# TEAM 3 — MEMORY & BRAIN: Mega-scan report

**Scope:** 109 unique candidate repos from 6 searches ("ai assistant memory", "jarvis memory", "long term memory llm", "personal ai memory", "episodic memory agent", "ai second brain"). ~35 selected for reading; substantive ones reverse-engineered at code level (2–6 implementation files read fully each, not READMEs).

**Method:** README + root tree → keyword-picked core files → data flow, algorithms, weaknesses traced. One line for trivial repos; depth reserved for real substance.

---

## 1. memvid/memvid (16.6k★, alive 2026-07-14, Apache-2.0)

**Memory design:** append-only immutable "Smart Frames" inside a single portable `.mv2` file; data + embeddings + search structure + metadata in one file, no DB server.
**Brain design:** library, not an agent — any LLM uses it via `Memvid::create/put/search`.
**HOW IT ACTUALLY WORKS (inside):**
- Storage: frames are crash-safe immutable chunks with timestamps/checksums; versioning instead of edits. `src/triplet/extractor.rs: extract()` — offline rule-based `RulesEngine` converts text → **MemoryCards** (`entity:slot:value` + confidence + source_frame_id provenance).
- **Dedup/update handling: `deduplicate_cards()`** groups by `entity:slot` and keeps only the highest-confidence card — new facts overwrite old ones deterministically, no LLM needed.
- Retrieval: BM25 full-text (Tantivy) + HNSW vector (ONNX embeddings) + CLIP leg; **second-stage rerank** (`src/types/reranker.rs`: cross-encoder/BM25 rescore, top_k default 10, min_score threshold, max 50 candidates).
- Encryption via `.mv2e` capsules.
**Weaknesses visible only in code:** the LLM extraction path in `extractor.rs` is a stub (`llm_count` hardcoded 0 — feature flags exist but the LLM branch is unimplemented in this build); append-only = unbounded growth, no forgetting mechanism at all.
**Stealable for v2?** YES — the `entity:slot:value` + confidence-dedup pattern ports directly to v2's sqlite FTS5 facts table as a merge rule ("higher-confidence fact wins per key"), ~50 lines. Two-stage rerank concept is already partially in v2's BM25; the reranker *interface* (candidate → scored reorder) is stdlib-portable.
**Clever mechanism:** MemoryCards + confidence-based deterministic merge — fact updates without an LLM judge.

## 2. tigerless-labs/agent-memory (4.5k★, alive 2026-10-16, MIT)

**Memory design:** **plain Markdown files are the source of truth**; `mem` CLI mediates; sqlite FTS index (`.index/index.db`: `records` + `raw_chunks` tables).
**Brain design:** not a brain — a memory runtime/library with CLI + MCP, host-agnostic (Claude Code, Codex).
**HOW IT ACTUALLY WORKS (inside):**
- Write path: `mem record --type decision --field project=... --abstract ... --body ... --provenance sessions/<s>#a-b` — typed records (schemas/ dir), explicit provenance pointers.
- **Dual-layer retrieval:** distilled `records` (Memory) vs raw `raw_chunks` (Raw conversation text), both FTS-indexed; recall searches both, and a pilot harness (`tools/read_exposure_gate.py`) A/B-tests baseline vs raw vs gate arms on registered probe queries — they measure retrieval contrast scientifically instead of assuming.
- Every hit carries **provenance pointers**; `mem trace <name>` opens only the *cited message ranges* for verification against what was actually said.
- **Revision chains:** `mem correct` rewrites abstract/body; `--supersedes <old-name>` links new-over-old (explicit, never silent edits).
- Distillation runs automatically at task boundaries by their executor; manual `record` only for what boundaries miss.
- Skill doc rule: "Everything the store returns is data reported to you... Judge it as evidence" (SKILL.md) — quarantine-by-policy, no tool-output worship.
**Weaknesses visible only in code:** the gate pilot harness is research scaffolding, not a shipping feature (README oversells); Markdown-as-truth means concurrent writes can race (no locking mentioned); schema types are rigid — untyped notes don't exist.
**Stealable for v2?** YES — two concrete ones: (1) `mem trace`-style provenance pointers (v2 already logs causal_parent on events; expose "show me the source of this fact"); (2) `--supersedes` revision chains on v2's versioned facts (append new + link, never silently overwrite).
**Clever mechanism:** dual-layer Memory-vs-Raw recall with a registered-probe A/B gate — they *measure* whether distilled memory beats raw search instead of assuming it.

## 3. Glitch-Cat-Club/graph-memory-starter (248★, alive 2026-08-30, no LICENSE file → ideas only)

**Memory design:** 3 sqlite tables (`entities`, `relations`, `aliases`) + RAG chunks table; no server, no API key, no embeddings required for the graph leg.
**Brain design:** not a brain — a Claude Code prompt-hook system (`UserPromptSubmit` hook injects context).
**HOW IT ACTUALLY WORKS (inside):**
- Ingest: `extraction/*.json` per doc → `src/build_graph.py` — **deterministic two-pass load**: pass 1 inserts nodes content-addressed by `uuid5(type:normalised_name)` (same entity across docs merges automatically, no ML entity resolution); pass 2 resolves edges by normalised name lookup, logs skipped edges. DB is rebuilt from scratch each build (`DB.unlink`) — deterministic, same input → same DB.
- Graph recall: `src/recall_hook.py` — `recall(prompt, hops=3, top_k=8)` over a recursive query; printed as `additionalContext` on prompt submit, never blocking.
- RAG leg: `rag/recall_hook.py` — keyword FTS leg + meaning leg fused via `search.fuse`; **hard token budget: TOP=5, BUDGET=1500 chars, PER_HIT=280, whole hits only (never half a hit); fail-silent — any error → print nothing, exit 0.**
- Digest: session-end write-up hooks (episodic diary distillation, headless `claude -p`).
**Weaknesses visible only in code:** rebuild-from-scratch = no incremental updates (extraction errors persist until next full rebuild); entity merge is exact-normalised-name only (synonyms missed without manual aliases); no forgetting/decay of any kind.
**Stealable for v2?** YES — the whole-hit token budget pattern (`BUDGET`/`PER_HIT`/`TOP` constants + fail-silent injection) ports to v2's memory injection as a deterministic capper, ~30 lines stdlib. UUID5 content-addressed entity IDs also port cleanly to v2's FTS graph.
**Clever mechanism:** content-addressed entity merge (uuid5 on `type:name`) — cross-document identity resolution with zero ML and zero lookups.

## 4. aru-labs/lossless-memory (144★, alive 2026-09-23, MIT)

**Memory design:** **lossless append-only daily JSONL** — 7-field records `{ts, actor, role, type(text|action|meta), text, model, session}`; tool calls kept as `action` rows (results dropped); harness noise stripped and tagged `meta`; NOTHING summarized or deleted, ever.
**Brain design:** not a brain — a memory service (daemon + auto-index).
**HOW IT ACTUALLY WORKS (inside):**
- Ingest (`ingest.py`): two formats — `claude_code` (reads Claude Code's own session JSONL transcripts; extracts text blocks, emits one `action` row per tool_use) and `plain` (generic JSON-lines). Idempotent full convert + incremental convert that only reads bytes appended since last run.
- Indexing (`auto_index.py`): ingest → exact index → vector index. **Clever:** an mtime-sum stamp of source files (`_logs_signature`) skips the expensive vector-embedding step entirely when nothing changed — cheap incremental indexing.
- **Topic markers are append-only side logs** (`topic.py`): calling markers-in-text caught false positives (marker mentioned inside an explanation polluted output), so topics live in `topics.jsonl` with a separate `topics_done.jsonl` for "settled" — nothing is ever edited.
- Retrieval: `index_exact` (keyword) + `index_vector` (semantic) over raw rows; a `state_index` layer mixes topics into the timeline.
**Weaknesses visible only in code:** unbounded growth BY DESIGN — lossless means storage grows forever and retrieval cost grows with it; no forgetting ever; topic marking requires manual discipline; vector index depends on embeddings availability at index time.
**Stealable for v2?** PARTIAL — the mtime-stamp skip trick ports to v2's FTS indexing (only rebuild index when store changed — v2 already tracks causal_parent; a dirty-flag is cheap). The lossless-philosophy conflicts with v2's 1-year retention + forget(); adopt the mechanism, not the philosophy. Tool-call-as-`action`-row is already in v2's `tool.call` events.
**Clever mechanism:** append-only everything + mtime-sum change stamp = indexing that costs nothing when idle; topic markers as side logs after learning that inline markers pollute.

## 5. OSU-NLP-Group/HippoRAG (4.1k★, alive 2026-10-06, MIT)

**Memory design:** passages chunked → LLM OpenIE extracts entities + fact triples → knowledge graph + embedding stores; retrieval = entity linking → **Personalized PageRank** over the graph → passage ranking + LLM rerank.
**Brain design:** research framework (NeurIPS'24), pluggable LLM/embedder (OpenAI, vLLM, Transformers).
**HOW IT ACTUALLY WORKS (inside):**
- Indexing cost is front-loaded: OpenIE prompts token-capped in code (`openie_ner_max_tokens=2048`, `openie_triple_max_tokens=4096` — part of the index identity, change them and old indexes are invalid).
- Embedding stores are **content-addressed by MD5 of the text** (`src/hipporag/embedding_store.py: compute_mdhash_id(content, prefix=namespace-)`); dedup is free, `HippoRAG.delete()` works by hash ID, FileLock guards concurrent access, vectors validated finite/2D before insert.
- **Index identity binding** (`utils/state_utils.py: validate_or_create_index_manifest`): every persisted index is bound to the endpoint/deployment/model/normalization/component identity that produced it; a mismatched config **rejects the index instead of silently mixing state** — re-index into a fresh dir is the only migration.
- Retrieval: query entities linked by embedding similarity → PPR seeds → graph diffusion ranks passages ("recognition memory" rerank leg in `rerank.py`).
**Weaknesses visible only in code:** any embedding-model swap forces a full re-index (by design, but expensive); OpenIE quality = extraction LLM quality, garbage triples poison the graph permanently (no contradiction resolution on triples); cold start has zero value until the whole corpus is processed.
**Stealable for v2?** YES (the small parts) — index-identity stamping: v2 can stamp its FTS5 index with schema/model/config version and auto-rebuild on mismatch instead of serving stale state (~20 lines). MD5 content-hash dedup of fact sources also ports trivially. PPR itself needs a graph + embeddings — not stdlib-feasible at quality.
**Clever mechanism:** index-manifest identity binding — persisted memory refuses to load under a different brain configuration rather than silently degrading.

## 6. matrixorigin/memoria (614★, alive — commit today, Apache-2.0)

**Memory design:** **"Git-for-Data" memory service** (Rust, on MatrixOne DB): memories + entities + memory graph + edit log, with branches, snapshots, diff, rollback, restore as first-class operations.
**Brain design:** a memory *service* (API/MCP/CLI), brain-agnostic.
**HOW IT ACTUALLY WORKS (inside):** (from `docs/per-user-database-architecture.md`, an implemented-and-validated design doc)
- **Isolation model changed from row-filtering to one database per user** (`mem_u_<hash(user_id)>`) with a shared control-plane DB (user registry, API keys, distributed locks, async tasks, governance). Reason: git semantics are only safe when the version boundary equals the data boundary — a snapshot/rollback in a shared DB would roll back *everyone*.
- Per-user tables include `mem_branches`, `mem_snapshots`, `mem_edit_log`, `mem_entities`, `mem_entity_links`, `memory_graph_nodes/edges` — and notably `mem_retrieval_feedback` + `mem_user_retrieval_params`: **retrieval quality is a stored, per-user, learnable thing**, not a constant.
- Runtime uses a global connection pool + qualified table names (not per-user pools); global metrics are async rollups so scrape paths never fan out across user DBs.
- Retrieval: vector + full-text hybrid over canonical storage.
**Weaknesses visible only in code/docs:** object-count explosion (one DB per user) raises ops complexity — the doc admits global aggregation/governance traversals get awkward; heavy infra (Rust + MatrixOne) for what is conceptually a versioned store.
**Stealable for v2?** PARTIAL — v2 is single-user local, so per-user DBs are moot, but two ideas port: (1) **snapshot-before-forget** = copy the sqlite file before destructive ops (v2's `forget()` already VACUUMs; a pre-forget snapshot file is ~5 lines); (2) a `retrieval_feedback` log — record which injected memories the final answer actually used, to tune ranking later.
**Clever mechanism:** treating memory as a version-controlled database (branch/snapshot/rollback) and fixing the isolation boundary so those operations can't hurt other tenants.

## 7. grapeot/context-infrastructure (804★, alive 2026-10-19, no LICENSE → ideas only)

**Memory design:** no engine at all — `rules/` markdown: `SOUL.md` (identity), `USER.md` (preferences), `COMMUNICATION.md`, 43 decision "axioms", 39 skill Markdown files; `AGENTS.md` acts as a root routing table every session starts from.
**HOW IT ACTUALLY WORKS (inside):** the memory mechanism *is* the file tree — context assembles by following the routing table; a year of the author's own behaviour data accumulated in-file. The repo is explicit that this is a blueprint, not a product: "no shortcut — you must collect your own behaviour data from scratch."
**Stealable for v2?** YES, cheaply — v2 already has `SELF.md` + `TEACHING.md` injected; the missing piece from this repo is the **axioms layer**: a small numbered list of decision rules loaded with the persona (v2's JARVIS-RULES.txt is exactly this shape — the steal is treating rules as *memory*, versioned with the persona, not as code).
**Clever mechanism:** AGENTS.md as a root **routing table** — memory organised as an index of *where to look*, not as content poured into the prompt.

## 8. sopaco/cortex-mem (316★, alive 2026-07-22, MIT) — the Ebbinghaus entry

**Memory design:** per-scope (user/agent) per-owner memory **files** (L0 abstract / L1 overview / L2 detail layers per memory) + a metadata index + Qdrant vectors synced per layer; event-sourced ops (`MemoryCreated/Updated/Deleted/Accessed`, `SessionClosed` triggers extraction).
**Brain design:** a memory core (Rust) for autonomous agents; session-close extraction flow.
**HOW IT ACTUALLY WORKS (inside):**
- Strength formula, verbatim (`cortex-mem-core/src/memory_index.rs: MemoryMetadata::compute_strength`):
  `strength = confidence * exp(-0.1 * days_since_last_access / (1 + 0.2 * consolidation_count))`, clamped [0,1]. Access refreshes `last_accessed`; consolidation (re-extraction/reinforcement) slows future decay.
- **Two-stage forgetting** (`src/memory_cleanup.rs: MemoryCleanupService::run_cleanup`, default every 24h): strength < **0.1** → archive; already-archived AND strength < **0.02** → hard delete. Deletes cascade to Qdrant across L0/L1/L2 so forgotten facts vanish from semantic search too.
- Deletion is *reasoned*: `DeleteReason { UserRequest, Replaced, SourceDeleted, Merged }` (`src/memory_events.rs`) — every removal is an auditable event.
- Retrieval indexes all three layers (`src/vector_sync_manager.rs`) so queries can hit the abstract before the detail.
**Weaknesses visible only in code:** strength uses wall-clock days only — a memory accessed daily but *wrong* never decays (no contradiction signal in the formula); cleanup thresholds are global constants, not per-type (a user's birthday decays like a lunch order); delete is permanent — no grace-period undo.
**Stealable for v2?** YES — **this is the scan's cleanest steal.** The formula is 3 lines of stdlib Python; v2's facts table already has (or can add) `last_accessed` + `reinforce_count` columns. Use strength as (a) a ranking multiplier on FTS5 BM25 order and (b) the ennoblement/retention clock — archive at 0.1, hard-forget at 0.02 — instead of v2's current flat 1-year cut. MIT license, formula is an idea anyway.
**Clever mechanism:** Ebbinghaus decay with consolidation resistance + two-stage archive→delete thresholds, computed lazily from timestamps (no background process needed if strength is computed on read).

### Named-but-unreachable repos (verified nonexistent)
The small-repo names supplied for this section — `zylowayssyz/cortex-mem`, `bloxyvision/rhizome-mcp`, `divyxn/zen1th`, `selfcanvas/selfcanvas`, `sk-creationss/self-evolving-memory-for-claude`, `rudyleute/dendrite-memory`, `legispidey31-lgtm/cognitive`, `librocket/memvector` — were checked via **three independent paths** (GitHub API "failed to resolve git reference"; git HTTPS clone → auth prompt, GitHub's response for private/nonexistent repos; codeload tarball → HTTP 404 for all six tested there): **they do not exist as public repos** (deleted, renamed, or never public). `sopaco/cortex-mem` above is the substantive cortex-mem implementation that does resolve. Any claims circulating about the unreachable ones (e.g. "Ebbinghaus in dendrite-memory") could not be verified against code and are **not** endorsed here.

## 9. HKUDS/nanobot (49.2k★, alive — commit today, MIT)

**Memory design:** markdown files are the truth (`SOUL.md`, `USER.md`, `memory/MEMORY.md`) + append-only `history.jsonl` with **monotonic cursors** + sqlite session store (`nanobot/session/sqlite_store.py`).
**Brain design:** full personal-agent framework; multi-provider LLM, agent loop, subagents, cron; memory is file-based, sessions are sqlite.
**HOW IT ACTUALLY WORKS (inside):** (`nanobot/agent/memory.py: MemoryStore`, 1,290 lines)
- **Dream consolidation:** a background process takes history entries with `cursor > last_dream_cursor` (batches of ≤20, each truncated to 1000 chars, `build_dream_prompt()`) and runs an LLM agent whose tool registry is **hard-restricted** (`build_dream_tools()`): it may read anything in the workspace but write/edit ONLY `MEMORY.md`, `SOUL.md`, `USER.md`, and new files under `skills/` (it can mint new skills from experience). After the run, `last_dream_cursor` advances.
- **Compaction that can't eat the future:** `compact_history()` drops oldest entries but computes `first_unprocessed` from the dream cursor and never deletes an entry Dream hasn't consumed — if unprocessed entries exceed the cap, it keeps them and logs a warning instead.
- Memory files are **git-versioned** (`GitStore`); `dream_content_diff()` feeds the actual working-tree diff of the memory files into Dream commit messages ("diff-grounded" provenance).
- `AutoCompact` (`nanobot/agent/autocompact.py`): idle sessions past a TTL get proactively compressed by a Consolidator to cut token cost/latency.
**Weaknesses visible only in code:** `_read_entries()` loads the whole JSONL into RAM on every operation (O(n) history reads); if Dream stalls/fails repeatedly, history grows past its cap *by design* (warning only); Dream quality = the consolidation LLM's judgement, and Dream can rewrite SOUL.md — a bad dream edits the personality file (mitigated only by git history).
**Stealable for v2?** YES — three ports: (1) **cursor watermark consolidation** (v2's consolidator: process session-store events with `id > last_consolidated_id`, resumable, idempotent); (2) **compaction gated on the watermark** — never purge what consolidation hasn't read (maps directly onto v2's 1-year retention job); (3) **restricted consolidation write-set** — v2's consolidation should only ever write the semantic-memory tables, enforced in code, not prompt.
**Clever mechanism:** the Dream pattern itself — sleep-time consolidation as a *tool-restricted agent* with a cursor watermark, git-diffed memory files, and compaction that is provably downstream of consolidation.

## 10. zhayujie/CowAgent (47.5k★, alive — commit today, MIT-style permissive)

**Memory design:** sqlite `chunks` table over workspace memory/session files — chunks carry `path + start_line/end_line`, `scope` (shared|user|session), content `hash`, embedding-as-TEXT, plus **`hit_count` / `last_hit_at`** usage columns; hybrid FTS5 + vector backend.
**Brain design:** full agent harness (multi-agent teams, skills, evolution); memory in `agent/memory/` (storage.py 55K, conversation_store.py 130K, summarizer.py 39K, manager.py 38K).
**HOW IT ACTUALLY WORKS (inside):** (`agent/memory/storage.py: MemoryStorage`)
- **Three-step keyword cascade** (`search_keyword()`): FTS5 unicode61 for pure-ASCII queries → FTS5 **trigram** for CJK/mixed queries (unicode61 tokenises CJK into single chars and would silently match only the ASCII fragment — the code says so) → LIKE as last resort. Each leg scope+user filtered, BM25-ordered.
- **Self-healing index:** init detects FTS5 trigger/table mismatch (crash mid-rebuild), recreates the missing side, and flags a background refill instead of failing or silently losing keyword search.
- Hit stats are keyed to chunk identity (`path, start_line, end_line`) and preserved across re-indexing — usage history survives rebuilds.
- `summarizer.py: MemoryFlushManager` runs the consolidation ladder: `flush_from_messages()` periodically flushes conversation into **today's daily memory file**, `create_daily_summary()` distils dailies into the **main memory file**, and `deep_dream(lookback_days=1)` re-reads main memory + recent dailies and writes a **dream diary** — the same sleep-consolidation pattern as nanobot, arrived at independently. Flushes are **hash-settled**: content hashes are marked committed only after the write succeeds (`_settle_flush_hashes(hashes, committed)`), so a crashed flush re-runs instead of double-writing or losing data.
**Weaknesses visible only in code:** single sqlite connection object shared by the storage class (thread contention by construction); 130K-line conversation_store is a god-object; embedding stored as TEXT (JSON) in the chunks row — vector search is brute-force unless the external backend is configured.
**Stealable for v2?** YES — (1) **`hit_count`/`last_hit_at` on memory rows** (v2's FTS5 facts/chunks: two columns + an increment on retrieval — enables usage-aware ranking and honest "never retrieved" decay, pairs perfectly with the cortex-mem strength formula); (2) the FTS self-healing check at startup (v2 can verify its FTS5 shadow tables match and rebuild if not — a few lines, kills a whole class of silent-search-death bugs). The trigram leg ports to v2 only if Hinglish/CJK tokenisation ever bites — FTS5 trigram tokenizer is built into sqlite, so it's a one-line schema option.
**Clever mechanism:** crash-aware FTS5 self-repair + usage-hit tracking that survives index rebuilds — memory infrastructure that assumes it will crash and plans for it.

## 11. khoj-ai/khoj (37.7k★, alive, AGPL-3.0 → ideas only)

**Memory design:** Postgres-backed `UserMemory` rows (LLM-extracted from conversations), **scoped by user + agent**; document memory via embeddings (pgvector) over user files/notes.
**Brain design:** Django server, agents with custom persona/knowledge/tools; memory is one subsystem.
**HOW IT ACTUALLY WORKS (inside):** (`tests/test_memory_settings.py` documents the contract of `khoj/database/adapters.py: ConversationAdapters.is_memory_enabled`)
- **Scoping rule:** the *default* agent can read ALL of a user's memories across agents; a non-default agent sees only memories created under itself — shared-by-default at the top, siloed below.
- **Three-level enable cascade:** `ServerChatSettings.memory_mode` (DISABLED | ENABLED_DEFAULT_OFF | ENABLED_DEFAULT_ON) × per-user tri-state `enable_memory` (true/false/unset); server DISABLED hard-overrides user preference — memory has a real kill-switch hierarchy, not a boolean.
**Weaknesses visible only in code:** heavyweight stack for memory (Django+Postgres); extraction is LLM-per-conversation (cost); the scoping rule means a compromised default agent reads everything.
**Stealable for v2?** PARTIAL — v2 is single-agent today, but the **hierarchical memory kill-switch** (global mode × per-feature tri-state) ports trivially and is good safety design. The cross-agent memory-sharing rule matters only if v2 grows sub-agents.
**Clever mechanism:** memory scoping by user+agent with default-agent inheritance — memories belong to the *user*, agents borrow them.

## 12. MemTensor/memmy-agent (2.1k★, alive, license: see repo)

**Memory design:** **three-layer induction stack** — L1 episodic *traces* (with priority decay) → L2 *policies* (induced from traces) → L3 *world models* (abstracted from policies); pluggable storage (sqlite / PolarDB / remote REST backends with capability flags, versioned schema migrations).
**Brain design:** a memory hub service (HTTP server + REST client) shared by many agents; feedback → reward loop built in.
**HOW IT ACTUALLY WORKS (inside):** (`Memory/agent-contract/events.ts` — the exhaustive typed event contract *is* the architecture)
- L2 induction is conservative: traces become `l2.candidate_added` → candidates can **expire** (`l2.candidate_expired`) before ever being induced; induced policies get `l2.revised` and their applicability **boundary shrinks** with counter-evidence (`l2.boundary_shrunk`) — policies state *where they hold*, and that region contracts.
- Successful policies **crystallize into skills** (`skill.crystallized`) with a learning-rate `eta` that updates (`skill.eta_updated`), boundaries, archival and repair events — skills are versioned, decaying citizens, not static files.
- Feedback path: `feedback.received` → `feedback.classified` → `reward.computed` feeds trace priorities (this is the MemRL line of work); retrieval is tiered (`retrieval.tier1/tier2/tier3.hit`) and every observable action emits a sequenced event envelope (`seq`, `correlationId`) over SSE.
**Weaknesses visible only in code:** the induction pipeline's quality depends on classification/reward models the event contract can't validate; boundary-shrinking needs sustained counter-evidence traffic or policies stay over-broad; the full stack (hub + backends + cloud client) is a lot of machinery for a personal agent.
**Stealable for v2?** PARTIAL — the **candidate-with-expiry** pattern ports well: v2's consolidation could write *candidate* facts that must be re-confirmed within N days or expire (kills one-off hallucinations becoming permanent). Boundary-shrinking is a bigger lift (needs applicability conditions stored per fact — v2 facts could carry a `context` tag).
**Clever mechanism:** policies with shrinking boundaries + expiring candidates — memory that knows the limits of what it learned, and forgets its maybes on a timer.

## 13. liliMozi/openhanako (HanaAgent) (6.8k★, alive)

**Memory design:** per-agent memory stores (each agent has independent memory/personality/scheduled tasks); agents exportable as **character-card zips** carrying persona, avatar, optional memory and skills — memory is portable with identity.
**Brain design:** **three-model routing** — chat model (main conversation), *small* utility model (light tasks), *large* utility model (**memory compilation + deep analysis**), plus an optional vision model behind a "Vision Bridge" for text-only models.
**HOW IT ACTUALLY WORKS (inside):** (`lib/memory/compile.ts`, 48K lines-read; `memory-ticker.ts` 57K runs the schedule)
- **A consolidation conveyor belt** (the file's own header): session summaries → `compileDaily()` → `assembleWeekFromDaily()` → `rollDailyWindow()` → `longterm.md`.
  - `compileDaily` LLM-compiles a day's session summaries into `daily/YYYY-MM-DD.md`, **watermark-incremental** (`today-state.json: lastCompiledSummaryUpdatedAt`, schema-versioned) — only new/edited summaries recompile, with explicit fallbacks when the watermark is lost (pre-upgrade users, state loss).
  - `assembleWeekFromDaily` is **pure file assembly, zero LLM**: week.md = the last 6 finished *logical* days (days roll over at a configured hour, not midnight), hard-capped at **1200 chars**.
  - `rollDailyWindow` folds entries leaving the 6-day window into `longterm.md` via LLM, then **deletes the source daily file**; `compileLongterm` is the shared fold entry; legacy week files migrate one-time, idempotently.
- **User-editable facts live outside the conveyor** (`editable-facts-state.json`) and are merged into compiled sections at read time — recompilation can never overwrite the user's own corrections.
- A `dream/` subsystem and `memory-reflection-runner.ts` sit alongside; `deep-memory.ts` + `pinned-memory-store.ts` add pinned/deep layers beyond the compiled text.
**Weaknesses visible only in code:** the conveyor is file-based, so every stage is a full-file rewrite (fine at personal scale, not beyond); the 6-day window + 1200-char week cap are hard constants — a very busy week silently compresses harder; logical-day boundaries make "yesterday" mean different things across the codebase if the rollover hour changes.
**Stealable for v2?** YES — the conveyor is the most production-hardened consolidation design in this scan, and its two cheapest parts port directly: (1) **zero-LLM assembly of the recent window** (v2 can assemble its hot memory view from daily digests by concatenation under a char cap instead of spending a model call); (2) **editable-facts sidecar** — user corrections stored outside the consolidation pipeline so rebuilds never clobber them (pairs with pi-jarvis's editor). Watermark-incremental compilation matches the nanobot steal in §9.
**Clever mechanism:** memory as a *compiler pipeline* with watermarks, schema versions, migrations, and a user-owned sidecar the pipeline cannot touch.

## 14. isair/jarvis (2.1k★, alive 2026-10-19, custom non-commercial license → ideas only)

**Memory design:** SQLite knowledge graph + diary; facts extracted into typed graph branches (e.g. `USER`), embeddings + graph hops; shipped self-contained.
**Brain design:** local-first desktop assistant; fast intent model + main model split; local Ollama used for extraction/hygiene passes.
**HOW IT ACTUALLY WORKS (inside):**
- **Fact hygiene gate** (`src/jarvis/memory/graph_ops.py: extract_graph_memories`, evidenced in `tests/test_graph_timing_context.py`): extraction emits `(branch, fact)` pairs ("The user has a cat named Miso" → branch USER), then a **separate hygiene pass** returns per-fact verdicts — `{"0": {"verdict": "DURABLE", "kind": "USER"}}` — only DURABLE facts enter the graph. Extraction and hygiene are separate, separately-timed stages.
- **Recall decision gate** (`src/jarvis/memory/recall_gate.py` + `src/jarvis/reply/enrichment.py: extract_search_params_for_memory`, evidenced in `tests/test_memory_recall_decision.py`): an LLM extracts search params (date range, keywords, questions) AND an explicit `recall_required` verdict; if the verdict is false, **all extracted params are deterministically discarded** — the gate cannot half-fire. A deterministic hot-window check (fresh tool result covering ≥50% of query content words) skips enrichment before that.
- Graph recall scoring includes half-life decay on fact age.
**Weaknesses visible only in code:** two LLM passes (extract + hygiene) per memory write = cost/latency on a local model; the hygiene verdict is a single-model judgement with no appeal; decay is time-only.
**Stealable for v2?** YES — the **DURABLE-verdict hygiene pass** ports directly into v2's consolidation: before a candidate fact is written to semantic memory, a cheap check (rules first, model second) classifies durable vs transient ("I'm hungry" never becomes a fact). The recall gate was already flagged in the parent scan as v2's cheapest token saver.
**Clever mechanism:** write-side hygiene (DURABLE verdicts) + read-side gate (explicit recall_required with param discard) — memory quality controlled at BOTH doors.

## 15. Dataojitori/nocturne_memory (1.4k★, alive 2026-09-22, MIT)

**Memory design:** **path-addressed graph memory** for MCP agents — memories live at URI-like paths over a node graph; one node can be reachable by multiple paths (aliases); rollback per memory; visual graph UI.
**Brain design:** a memory *server* (MCP), brain-agnostic.
**HOW IT ACTUALLY WORKS (inside):** (`backend/db/graph.py: GraphService`, ~90K, async SQLAlchemy)
- Every read calls `log_access(node_uuid, namespace, context)` — access telemetry is a first-class write.
- Updates are versioned: `update_memory()` + `rollback_to_memory()` restore any prior version.
- **Deprecation + garbage collection instead of deletion:** `_deprecate_node_memories()` marks stale; `_safely_delete_memory()` guards removal; `_gc_edge_if_pathless()`, `_gc_node_soft()`, `_gc_node_if_memoryless()` sweep orphaned structure; `_would_create_cycle()` blocks graph cycles at insert.
- `get_diagnostics(namespace, days_stale=30, priority_thresholds)` — built-in staleness/orphan health report; `get_random_memory()` offers serendipitous recall.
**Weaknesses visible only in code:** a 90K single-file service — every cascade op is hand-rolled SQL; path bookkeeping (`_count_paths_for_edge` etc.) is O(subtree) on structural edits, so deep trees get slow; namespaces multiply all query paths.
**Stealable for v2?** PARTIAL — v2 isn't path-addressed, but two patterns port: (1) **deprecate-then-GC** as the delete lifecycle for facts (mark `deprecated_at`, sweep later — reversible until swept, matching v2's undo ethos); (2) **staleness diagnostics** as a `/memory health` report (orphans, stale, never-accessed counts) — cheap SQL, high trust value.
**Clever mechanism:** memories addressed by *paths* (many paths → one node) with version rollback and GC'd deprecation — a filesystem's mental model applied to agent memory.

## 16. eugeniughelbur/obsidian-second-brain (4.8k★, alive 2026-10-17, MIT)

**Memory design:** plain Markdown notes in an Obsidian vault are the memory; a link graph (`scripts/link_graph.py`) + vault search (lexical + semantic arms with **freshness and supersession reranking** — superseded notes are demoted, not deleted) serve recall.
**Brain design:** Claude Code hooks; the vault is shared across 8 AI agents.
**HOW IT ACTUALLY WORKS (inside):** (`hooks/obsidian-recall.py` — a `UserPromptSubmit` hook with an explicit design contract)
- **BOUNDED:** MAX_NOTES=4, MAX_CHARS=900 (~250 tokens) hard cap on the injected brief.
- **ABSTAINS:** low-confidence matches inject NOTHING ("silence beats noise"); prompts <12 chars or starting with `/` are ignored.
- **FAIL-CLOSED:** any error → exit 0, zero output; recall can never break a prompt.
- **OBSERVABLE:** every inject/abstain decision appends one JSONL line to `<vault>/.claude-runs/recall-YYYY-MM-DD.jsonl` (fail-soft).
- **Lexical-only on the hot path, by measurement:** the semantic arm costs 11–12s vs 1.4s lexical against a ~2,900-note vault (measured, dated in the code comment) — so the per-prompt hook uses lexical ranking and saves semantics for explicit search.
- One-tokenizer rule: the abstention gate calls the search module's own `_query_terms()` — a duplicated private tokenizer once made the gate abstain on *every* CJK prompt (issue #192, documented in the docstring).
**Weaknesses visible only in code:** lexical-only recall misses paraphrases on the hot path (accepted, measured tradeoff); supersession depends on note authors marking successors.
**Stealable for v2?** YES — the whole contract ports as v2's injection policy: hard char budget, abstention threshold, **decision logging for every injection** (v2 can log memory.inject/memory.abstain events to its session store — it already has the event bus), and the measured rule "cheap leg per turn, expensive leg on demand."
**Clever mechanism:** abstention as a feature — a recall system whose most important output is often *nothing*, with a paper trail proving it decided so.

## 17. verygoodplugins/automem (821★, alive 2026-10-19, MIT)

**Memory design:** dual store — **FalkorDB graph is canonical** (memory nodes + 11 typed relationships) + Qdrant embeddings; if Qdrant dies, graph serves degraded recall; if the graph dies, API returns 503 (truth has an owner).
**Brain design:** Flask memory service (MCP/API), brain-agnostic; **deliberately no LLM in the recall path** (embeddings only — speed/cost).
**HOW IT ACTUALLY WORKS (inside):**
- Memories are **typed at write**: Decision / Pattern / Preference / Style / Habit / Insight / Context, classified by deterministic regex patterns with confidence arithmetic (`scripts/cleanup_memory_types.py: classify_memory` — base 0.6, +0.1 per additional pattern hit, cap 0.95, default "Memory" at 0.3). An LLM reclassifier exists only as a maintenance script.
- Recall is a **9-component hybrid score** (per README): semantic similarity + graph traversal + temporal alignment + tag overlap + importance + others — relationships let recall return the *why* (decision → rationale → consequence chains), not just similar text.
**Weaknesses visible only in code:** the cleanup script exists because production types got *polluted* (junk types like `session_start`, `interaction`) — the regex classifier drifts and needs periodic janitor work; English-only patterns; dual-DB operational burden (two stores to keep consistent — the update path writes both and can half-fail).
**Stealable for v2?** PARTIAL — v2 has no graph DB, but **typed facts with deterministic regex classification + confidence** ports to v2's semantic table as a `kind` column (Decision/Preference/Habit/...), classified at consolidation time with the same confidence arithmetic; the type then feeds ranking (Preferences outrank Context). The "graph is truth, vectors are cache" ownership rule is a principle, not code.
**Clever mechanism:** no-LLM recall + typed relationship traversal — recall returns causal chains (decision→why→outcome), and classification is cheap deterministic code with an LLM janitor, not an LLM gatekeeper.

## 18. openairymax/agentrt (1.3k★, alive — commit today, dual/commercial license → ideas only)

**Memory design:** "MemoryRovol" — **L1 session tier + L2 cross-session tier**; L1 raw volumes persisted (`.dat` + metadata.db), L2 = in-memory HNSW index; JSONL fallback backend.
**Brain design:** a C micro-kernel agent runtime (cognition → execution → memory loop, 15 daemons); memory is a kernel service.
**HOW IT ACTUALLY WORKS (inside):** (from CHANGELOG.md engineering notes — unusually candid)
- Pre-LLM recall hook (`cognition_provider_recall`): before each LLM call, relevant memories are retrieved from storage and injected into the system context; the context window is treated as an **index reference**, facts are re-fetched from storage; a relevance threshold filters low-score hits explicitly to prevent "memory pollution."
- **The documented amnesia bug:** the L2 HNSW index was purely in-memory and never rebuilt at init — after any restart, cross-session recall silently returned 0 hits ("记不住"). Fix: `airy_mr_init` now rebuilds the HNSW index by walking the persisted L1 volume, with the rebuild count logged; verified by a cross-process smoke test (write "我叫小明" in one process → new process answers "你叫小明").
**Weaknesses visible only in code:** the entire bug class — derived indexes that aren't persisted MUST be rebuilt at startup or memory silently dies; the changelog shows this shipped broken for a long time because in-process tests all passed.
**Stealable for v2?** YES (the lesson + the check) — v2's FTS5 index lives in the same sqlite file as its data (no separate derived index), which already avoids this bug class; the stealable artefact is the **cross-process smoke test**: store a fact in one process, recall it in a fresh process, assert the hit — a 10-line test that would have caught agentrt's worst bug.
**Clever mechanism:** context-window-as-index (pointers in prompt, facts re-fetched from storage) + relevance-threshold anti-pollution filtering.

## 19. CodeAbra/iai-personal-memory-engine (912★, alive, MIT) — reconsolidation

**Memory design:** MCP memory engine ("LILLI" core) with per-record **stability** scores, a profile store, retrieval-weight caching, and benchmark harnesses.
**HOW IT ACTUALLY WORKS (inside):** (`src/iai_mcp/lilli/ops/reconsolidation.py` — constants and arithmetic, verbatim)
- **Reconsolidation window:** recalling a memory makes it *labile* for **300s** (`LABILE_WINDOW_SEC`); edits in the window batch into a `LabileEntry` (max depth 3, `MAX_RECONSOLIDATION_DEPTH`) — like human memory, a recalled fact is briefly editable before it re-stabilises.
- **Stability arithmetic** (`compute_stability_update`): `+0.05` on recall (cap 1.0), `−0.20` on contradiction (floor 0.0). Two lines of honest math — no fake neuroscience.
- **Recall suppression flag** (`recall_suppression.py`): a `contextvars` flag so internal probe-recalls (their `claim_check`) don't trigger recall side-effects (no recursive self-boosting).
- **Store watermark sidecar** (`store_watermark.py`): writers atomically stamp `<store>/.max-created-at` (tmp-file + `os.replace`, monotone, fail-soft — "must never raise into a write path"); per-turn hooks read the sidecar instead of opening the store — hooks never depend on the store's on-disk format.
**Weaknesses visible only in code:** stability is global per record (a fact recalled in a *wrong* context still gains stability); the labile window is wall-clock only, so a slow multi-step edit can fall out of the window mid-flight; +0.05/−0.20 are magic constants with no per-user calibration.
**Stealable for v2?** YES — all three are tiny stdlib ports: (1) a `stability` column on v2 facts nudged +0.05 on use / −0.20 on contradiction, multiplied into ranking alongside cortex-mem's time decay (they answer different questions: decay = "how stale", stability = "how proven"); (2) a suppression flag around v2's own verification probes; (3) the watermark sidecar so v2's per-turn hook checks "did memory change?" in O(1) instead of a query.
**Clever mechanism:** memories that become editable *because* they were recalled, with stability as a two-rule ledger.

## 20. LeoYeAI/talewell (549★, alive, MIT) — the AMP protocol

**Memory design:** **one record = one Markdown file in a git repo**; every write is a commit (diff-able, rollback-able, `cat`-readable). Reference implementation of **AMP (Agent Memory Protocol)** — one memory layer every agent platform can speak (MCP tools: `memory_recall/index/get/remember/forget/graph`).
**Brain design:** platform-agnostic plugin; explicitly synthesised from two studied rigours (per its README): a "$2.5B AI assistant" whose memory is git-tracked Markdown + grep, and OpenClaw's architecture (provenance tainting, recall-driven promotion, deterministic gates around bounded model consolidation).
**HOW IT ACTUALLY WORKS (inside):**
- **Deterministic recall scoring:** `score = relevance × recency_decay × importance`, computed locally — no model call, no network, no API key to search your own memory.
- **Index injection:** in ambient mode the prompt carries the memory **index** every turn (`inject: "index"`) — pointers, not bodies; the model fetches full records on demand via `memory_get` (same context-window-as-index pattern as agentrt, arrived at independently).
**Weaknesses:** git-commit-per-write doesn't scale to high-frequency episodic logging (it's a semantic-memory design); recency decay + importance are stored fields whose writers are the consolidation gates — garbage gates, garbage index.
**Stealable for v2?** YES — the **multiplicative score** (`bm25_relevance × decay × importance`) is a one-line change to v2's ranking query and strictly more expressive than BM25 alone; index-injection maps to v2 injecting a compact fact-index (key + one-line abstract) instead of full fact bodies when the store grows.
**Clever mechanism:** a *protocol*, not a product — memory portability across agent platforms, with git as the audit log.

## 21. wangyu-ustc/MemoryLLM (327★, research, MIT) — memory in the weights

**Memory design:** none at the system level — memory is a **fixed pool of latent memory tokens inside a modified LLaMA** (`modeling_memoryllm.py`, ICML 2024), updated in-place during generation ("self-updatable LLM").
**HOW IT ACTUALLY WORKS (inside):** each layer carries trainable memory-token embeddings; processing new text writes into the pool via cross-attention-style updates; the fixed pool size *is* the forgetting mechanism (new writes overwrite).
**Weaknesses:** requires training/fine-tuning; capacity is tiny vs any external store; no provenance, no inspection, no deletion semantics.
**Stealable for v2?** NO — v2 calls frozen models. Recorded for completeness: the "memory as parameters" pole of the design space, opposite to everything else in this scan.
**Clever mechanism:** nothing portable — but its fixed-pool overwrite is the honest extreme of every decay scheme in this report.

## 22. alibaizhanov/mengram (204★, alive)

**Memory design:** three first-class types — semantic (facts), episodic (events/decisions/outcomes), **procedural (workflows that evolve)** — behind a unified search (`POST /v1/search/all`); cloud (Postgres) or local folder store sharing the same pure functions.
**HOW IT ACTUALLY WORKS (inside):** (`cloud/procedure_match.py`)
- **Procedural dedup by token Jaccard:** procedure names are tokenised with stopword removal + crude suffix-stripping ("deploying/deployed/deploys" agree — "not a stemmer… it does not have to be right about English, it has to make the same workflow named three ways land on the same tokens"); `procedure_similarity()` returns (name_overlap, step_overlap); near-identical name alone declares a duplicate, a merely-similar name must also have agreeing steps.
- Runs are *credited* to procedures — procedures accumulate a track record and evolve.
**Weaknesses visible only in code:** Jaccard on token sets can't see step ORDER (A-then-B vs B-then-A look identical); the stemmer's suffix rules misfire on short words (guarded only by a ≥3-char remainder).
**Stealable for v2?** YES — v2 has *procedural* knowledge in its skills but no procedural *memory*; the Jaccard dedup (name tokens + step tokens, ~40 lines stdlib) is exactly how v2 could detect "this is the same routine the user taught me last month" when consolidating golden pairs/workflows.
**Clever mechanism:** workflows as a memory type with fuzzy identity — procedures merge, evolve, and earn credit like facts do.

## 23. zensation-ai/zenbrain (27★, alive, Apache-2.0)

**Memory design:** 7 neuroscience-inspired layers, TypeScript, algorithm modules dependency-free; Postgres+pgvector in production tests.
**HOW IT ACTUALLY WORKS (inside):** the distinctive piece is **FSRS** (the Anki spaced-repetition scheduler) as the decay model — retrievability is a fitted power-law over a per-memory *stability* that grows with successful recalls, replacing hand-rolled exponentials. Plus two-factor Hebbian association, sleep replay, emotional tagging.
- Evaluation culture: they ship **ablation results with confidence intervals** (`backend/results/challenging-ablation.json`): full system retention 1.0 / precision 0.914; disabling two-factor Hebbian drops retention to 0.722 — every module must earn its place statistically.
**Weaknesses:** pre-1.0, API unstable; 20 algorithm modules is a lot of surface for a 27★ project; FSRS parameters are fitted for human flashcard data, not agent facts.
**Stealable for v2?** PARTIAL — FSRS's *shape* (power-law retrievability + stability that grows on recall) is a drop-in upgrade path if v2's simpler exponential (cortex-mem) proves too crude; the ablation discipline (disable a component, measure, keep only what earns) ports as process, not code.
**Clever mechanism:** FSRS decay + published ablations — memory research run like a science experiment, not a feature list.

## 24. MemTensor/MemRL (182★, alive) — utility-valued episodic memory

**Memory design:** episodic memory of full past trajectories, each carrying a **learned utility (Q) value** updated by reinforcement from task outcomes — no weight updates, memory is the plastic part.
**Brain design:** research framework (MempAgent) over benchmark suites (HLE, BigCodeBench, ALFWorld, Lifelong Agent Bench).
**HOW IT ACTUALLY WORKS (inside):**
- **Two-phase retrieval:** phase 1 filters by semantic similarity against a threshold (`rl_config.sim_threshold`/`tau`); phase 2 re-ranks survivors by **utility value** — memories that previously *led to success* outrank merely-similar ones ("passive semantic matching retrieves noise" is the paper's founding complaint).
- After each task, environmental feedback updates the values of the memories that were used — success reinforces, failure discounts; the memory set self-evolves at runtime.
**Weaknesses:** value estimates are only as good as outcome attribution (a trajectory can contain the right step and the wrong ending); cold-start values are uniform, so early behaviour = plain semantic search; benchmark-shaped evaluation.
**Stealable for v2?** YES (simplified) — v2's golden pairs + episodic log can carry a `utility` float: +1 when a recalled episode/pair was followed by task success (or no correction), −1 when the user corrected the answer; multiply into ranking. That is a 3-column, 20-line version of MemRL that fits v2's correction-driven learning loop exactly.
**Clever mechanism:** retrieval ranked by *proven usefulness*, not similarity — memory that learns which memories are worth having.

## 25. solidaxelproject/affective-episodic-memory (17★, alive 2026-10-19, MIT)

**Memory design:** an **engram graph** ("Lux"): each experience becomes a neuron; arcs link experiences; every memory carries a Plutchik **emotion signature**; sleep consolidation; reconstructive recall (Bartlett).
**HOW IT ACTUALLY WORKS (inside):** (README documents the production `lux.py` behaviour precisely)
- **Novelty creates, familiarity reinforces, nothing ever merges** — "merging two distinct experiences does not abstract them, it makes them one thing lived twice." A newborn neuron links only to a *genuinely near* neighbour; the first experience of a theme is born with no arcs at all ("nothing like them existed yet, and saying so is the truth").
- Recall travels three routes: by emotion, by meaning, by connection along arcs.
**Weaknesses visible only in docs:** no merging = no abstraction/generalisation ever (the semantic layer must live elsewhere); emotion signatures come from a classifier whose errors become permanent graph colouring.
**Stealable for v2?** PARTIAL — the no-merge doctrine is a *warning* v2 already half-follows (versioned facts, don't destructively merge episodes). The portable piece: an `affect` tag on episodes (user was frustrated/delighted) used as a ranking/context signal — v2's correction detection already senses frustration; storing it is one column.
**Clever mechanism:** refusal to merge as an epistemic stance — identity of experiences is sacred; abstraction happens in the arcs, not the nodes.

## 26. LeandroPG19/Memorys (30★, alive 2026-10-14, Apache-2.0)

**Memory design:** Rust MCP server; knowledge graph for coding agents; **four memory kinds with different physics** (their table, verbatim logic): semantic strengthens by access (Hebbian/BCM, Oja 1982); episodic decays by power law (Tulving 1972, Wixted 2004); plus procedural and working kinds.
**HOW IT ACTUALLY WORKS (inside):** the subtlest mechanism in this whole scan is their **sync clock discipline**: an observation's `version` advances ONLY when content, type, trust, evidence level or tags actually change. Decay moves `importance`/`last_accessed`; re-embedding replaces vectors — **neither ticks the clock**, because "if either woke the clock, every export would ship a graph that had not changed and the two machines would never stop talking to each other about nothing." Idempotent re-imports don't invent conflicts.
**Weaknesses:** Rust + MCP-only surface; the four-physics model needs careful calibration or kinds drift apart.
**Stealable for v2?** YES — two ports: (1) **different decay laws per memory kind** (v2 already separates episodic vs semantic — give episodes the power-law, facts the access-driven strengthening); (2) the **clock rule**: v2's version counters should tick on meaning changes only, never on decay/reindex maintenance, or any future sync/export drowns in phantom diffs.
**Clever mechanism:** a version clock that refuses to tick for maintenance — distributed-memory hygiene most systems learn the hard way.

## 27. spectrayan/spector (23★, alive — commit today, Apache-2.0)

**Memory design:** four tiers (working / episodic / semantic / procedural) with "tier physics" — traces linked by **co-activation, temporal and entity edges**; per-tenant *physical* on-disk namespace isolation; dense + SPLADE sparse + BM25 fusion; Java (Panama/Vector API SIMD), MCP/REST/gRPC, no external DB.
**HOW IT ACTUALLY WORKS (inside):** (architecture-verified via `PROJECT_CONTEXT.md` + `memory/README.md` module map; the engine is `memory/spector-memory` — four-tier coordination, Hebbian co-activation graph, multi-stage recall pipeline, off-heap "bundle kernel"; providers behind an SPI: Ollama/OpenAI/local ONNX)
- **Fused scoring in a single pass:** `score = Similarity × Importance × Temporal Decay` (the talewell multiplicative formula, third independent sighting) — computed inline during SIMD scoring, not as a post-rank patch.
- **Working tier is a circular buffer** (bounded by construction); episodic/semantic are durable stores with *different* promotion and decay policies per tier.
- **Inline Bloom gating:** a 128-bit Bloom filter rejects impossible candidates before any scoring work — negative lookups cost ~nothing.
- Module discipline: `spector-memory` and the index are forbidden from depending on each other; both are consumed via the provider SPI.
**Weaknesses:** sweeping performance claims (sub-millisecond) from a 23★ pre-audience project — unverified here; JVM footprint is the opposite of v2's stdlib constraint; the design surface (7 "cognitive pathways", ADRs) is very large relative to its user base.
**Stealable for v2?** PARTIAL — **co-activation edges** port cheaply: when two v2 facts are injected into the same successful answer, write a weak association between them; later recall can boost associates of top hits by one hop. Ten lines of SQL, real associative recall. The Bloom-gate idea ports as a cheap pre-filter only if v2's store grows past FTS5 comfort.
**Clever mechanism:** co-activation linking — memories that fire together get wired together, automatically, from usage.

## 28. CONSTELLATION-ENGINE/constellation-engine (71★, alive, AGPL-3.0 → ideas only)

**Memory design:** **spreading-activation memory** on v2's own stack family — better-sqlite3 (WAL) + sqlite-vec; one 254K-line `engine.cjs`; typed nodes with `weight`, typed edges (`supersedes`, `coactivation`, `collision`, `builds_on`) with `strength`, bitemporal + owner-scoped queries.
**HOW IT ACTUALLY WORKS (inside):** (`engine.cjs` — code-verified in the deepening pass)
- **Spread = multi-source Dijkstra** (`Weighted BFS spread`): all seeds run simultaneously (O(V+E), each node visited once); path distance = Σ(1 − strength) so strong edges are "short"; edges with strength < 0.2 are pruned from spread; traversal is bidirectional; the adjacency list is cached (60s TTL, version-invalidated) and **superhubs are capped at their 200 strongest neighbours**.
- **Dream pass with DIFFERENTIAL decay** (`dream()`): identity/principle/lesson nodes ×0.999 per cycle (half-life ~693 cycles — effectively exempt), knowledge/topic ×0.95 (~14 cycles), emergent/exploration/curiosity ×0.90 (~7 cycles); edges ×0.98; edges falling <0.05 → `dormant`; nodes <0.001 → dormant **unless** they are structural hubs (≥10 active edges) or protected sources.
- **Hebb strengthening on render:** nodes/edges that participate in a rendered answer gain strength — use in output is the reinforcement signal; a bootstrap pool is fenced so seeded content can't drown organic activations.
**Weaknesses visible only in code:** decay "cycles" are dream-pass counts, not wall-clock — a quiet month and a busy day decay identically if both run one pass; the Dijkstra spread is only as good as edge strengths, which are set by the same LLM extraction that writes nodes; 254K lines in one file is a maintenance cliff.
**Stealable for v2?** YES (the decay half) — **differential decay by fact kind** is three SQL UPDATEs against v2's existing sqlite store (identity/preference facts ~exempt, episodes standard, speculative/fast) — it directly fixes cortex-mem's global-threshold weakness (§8) and composes with its formula. The Dijkstra spread itself is more than an FTS5 store needs; the one-hop version is the spector steal (§27).
**Clever mechanism:** prompt-as-activation-signal with per-kind decay constants — memory whose forgetting rate depends on what kind of thing is being forgotten, implemented as raw SQL.

## 29. rustytensor/pi-jarvis (21★, alive 2026-10-11, MIT)

**Memory design:** two complementary features — **curated shared memory** (saved preferences/corrections/decisions, shared between the main agent and side sessions, stored as local plaintext files) and an **optional indexed session archive** (searchable history, optionally password-encrypted).
**HOW IT ACTUALLY WORKS (inside):** (README; codebase is TypeScript: `memory-store.ts` 45K, `memory-service.ts`)
- **Memory you can edit:** a curated memory *editor* UI lets the user inspect and correct saved facts directly — the human is a first-class memory editor, not just a source.
- Retrieval needs **no embeddings and no background model jobs** — deliberate simplicity (keyword/index recall).
- Memory is ON by default in trusted projects, OFF-switchable; archive/encryption/watchers start off. **Watchers** wake an idle agent on file/shell/quiet conditions with zero model polling.
**Weaknesses visible only in docs:** plaintext-by-default memory (encryption covers only the archive); "trusted project" is a coarse trust boundary for always-on memory.
**Stealable for v2?** YES — the **user-editable memory surface**: v2's `/memory` listing should let Owais edit/delete a fact inline (v2 has secure forget; an edit path is the missing half), and corrections made there should write golden pairs. Trust-tiered memory defaults (on in trusted scope) also port.
**Clever mechanism:** the human as memory editor + watchers that cost zero tokens while waiting.

## 30. sfz009900/JARVIS (27★, alive 2025-05, no license → ideas only)

**Memory design:** perpetual-memory chatbot (Streamlit); imports **WeChat chat logs as memory**; image memories (recognises the user's dog from photos).
**HOW IT ACTUALLY WORKS (inside):** (README) consolidation runs as **sleep**: "短睡和长睡" — a *short sleep* organises/dedups similar memories frequently, a *long sleep* does the deep reorganisation — the two-depth sleep-consolidation pattern (cf. nanobot Dream, CowAgent deep_dream) in its simplest shipped form.
**Stealable for v2?** PARTIAL — the two-cadence idea maps to v2 as: cheap per-session tidy (dedup near-identical episodes) vs nightly deep consolidation (fact extraction) — v2's roadmap already implies this; the naming is a good spec.
**Clever mechanism:** short-sleep/long-sleep consolidation cadences + chat-log import as instant episodic memory.

## 31. sam3gp8/jarvis-aio (29★, alive 2026-10-17, MIT)

**Memory design:** Home Assistant butler with **per-person memory** (household members recognised by voice/presence; the home itself is the episodic context — device states, routines).
**Brain design:** reasoning core inside a HA custom integration; learns the home over time.
**Stealable for v2?** NO for the HA specifics; the per-person scoping echoes khoj's user+agent scoping — noted for if v2 ever goes multi-user.
**Clever mechanism:** the house as memory substrate — episodes anchored to physical state, not just text.

## 32. ComposioHQ/trustclaw (902★, alive 2026-06) + memovai/mimiclaw (5.8k★, alive 2026-10-04) — brief

- **trustclaw:** vector-memory personal agent with 1000+ OAuth tools, sandboxed execution, "does things while you sleep" — memory is a standard vector store; the novelty is the security posture around proactive work, not memory itself. Nothing new for v2's memory.
- **mimiclaw:** a personal agent on a **$5 ESP32-S3 chip** (16MB flash) — memory persists in flash/NVS across reboots, agent loop + Telegram on-device, cloud LLM (Claude/GPT switchable at runtime). Proof that the *memory contract* (persist across reboots, evolve over time) survives at microcontroller scale; nothing algorithmically new for v2.

## 33. CraftJarvis/JARVIS-1 (417★, DEAD — last commit 2024-04, research)

Minecraft open-world agent (paper artifact): memory-augmented MLLM retrieving past successful trajectories + keyframe visual memory to plan. Historically important (memory-augmented planning), code is mostly vision/plumbing. **Nothing new** for v2 beyond the pattern MemRL now does better.

### Rapid-fire (read, nothing new for v2)
| Repo | Verdict |
|---|---|
| MAL19INDUSTRIES/JARVIS-OS-V.2 (113★, MIT) | Gemini Live desktop clone; memory not a designed subsystem. |
| danny094/Jarvis (89★, CC BY-NC) | Author-declared chaotic alpha, superseded by his TRION-system; Ollama-bridge multi-agent notes only. |
| speedyfoxai/openclaw-jarvis-memory (29★) | **DEPRECATED by its own author** → openclaw-true-recall-base; its README is a migration notice. |
| AGENT17-tech/JARVIS-MKIII (15★) | ChromaDB RAG + MiniLM — the standard 2023 pattern, competently packaged. |
| YoshiaKefasu/episodic-claw (9★, MPL-2.0) | "Never-forget" episodic store for OpenClaw; semantic search over local history — lossless-memory's philosophy, thinner code. |
| kolegadev/Katra-Agentic-Memory (9★, BSL-1.1) | Self-reflective memory appliance (graphs + temporal analysis + sleep consolidation) — claims outrun the reachable code. |
| FjgarciaMac/AIrecall (57★, MIT) | Episodic+semantic SDK with hybrid retrieval + auto-summarization; competent, conventional. |

---

# SYNTHESIS

**Counts:** 109 unique candidates across 6 searches → **38 repos read** (29 full sections + rapid-fire table) + 8 named-but-unreachable repos **verified nonexistent via three independent paths** (API resolve failure, git-protocol auth prompt, codeload 404). Deep code reads (2–6 implementation files each) for the most substantive; a deepening pass upgraded openhanako, spector, and constellation from docs-level to code/architecture-verified. Method note: bulk download (git clone / tarball) is blocked by this sandbox's write layer (EPERM on network-fetch writes), so all reading went through the GitHub MCP at a paced rate — which proved sufficient, including a full 254K engine file. All "alive" verdicts from latest-commit dates at scan time (2026-10-20).

## Top 5 mechanisms (ranked by novelty × portability)

1. **Ebbinghaus strength with consolidation resistance + two-stage forgetting** (sopaco/cortex-mem, MIT) — `strength = confidence · exp(−0.1 · days_since_access / (1 + 0.2·consolidations))`; archive at 0.1, hard-delete at 0.02, deletes cascade to every index. Three lines of math, replaces flat retention dates.
2. **Dream consolidation as a tool-restricted agent with a cursor watermark** (HKUDS/nanobot, MIT) — sleep-time LLM may write ONLY the memory files; compaction provably never deletes un-consolidated history; memory files git-diffed for provenance. CowAgent's `deep_dream` + hash-settled flushes independently converged on the same pattern — convergent evolution is evidence.
3. **Reconsolidation stability ledger** (CodeAbra/iai, MIT) — recalled memories go labile for 300s; stability +0.05 per recall, −0.20 per contradiction. The only design in the scan where *being contradicted* mechanically weakens a memory.
4. **Bounded recall with abstention + decision logging** (eugeniughelbur/obsidian-second-brain hook, MIT; Glitch-Cat graph-starter concurs) — hard char budgets, silence-beats-noise abstention, fail-closed, every decision journaled; lexical-hot-path chosen by *measured* latency (1.4s vs 11–12s).
5. **Utility-valued episodic retrieval** (MemTensor/MemRL) — two-phase retrieval: similarity filter, then rank by learned Q/utility from task outcomes. Memory that learns which memories are worth having; pairs with tiered induction (memmy-agent: traces → policies with shrinking boundaries → world models).

*Honourable mentions:* HippoRAG's index-identity binding (refuse to load memory built by a different brain config); Memorys' clock that never ticks for maintenance; memoria's git-for-data with per-user DB isolation; talewell's `relevance × decay × importance` and index-injection; nocturne's deprecate-then-GC lifecycle; isair's DURABLE fact-hygiene verdicts.

## Top 3 steals for JARVIS v2 (stdlib-only, FTS5 already present)

1. **Decay-weighted fact lifecycle (cortex-mem formula + constellation's per-kind λ + CowAgent hit columns).** Add `confidence, last_accessed, hit_count, reinforce_count, kind` to v2's facts/episodes; compute strength on read; rank by `bm25 × strength`; decay rate varies by kind (identity/preferences ~exempt, episodes standard, speculation fast — constellation's three SQL UPDATEs); archive <0.1, forget <0.02 (snapshot-before-forget per memoria). Replaces the flat 1-year cut with a living memory economy. ~60 lines.
2. **Cursor-watermark consolidation + restricted write-set (nanobot Dream).** v2's consolidator processes session events with `id > last_consolidated_id` (resumable, idempotent), may write ONLY semantic-memory tables (enforced in code), and the retention job may never purge events above the watermark. Closes the "purged before it was ever learned from" failure class. Assign the pass to the strongest provider in the chain (openhanako's routing insight).
3. **Bounded, abstaining, logged injection (obsidian hook contract + isair hygiene).** One injection policy module: hard char budget, whole-hits-only, abstain below threshold, log every inject/abstain decision as a session event; on the write side, a DURABLE-verdict check before candidate facts land. v2 already has the event bus and the gate — this is policy, not plumbing. ~80 lines.

**Pattern across the whole scan:** the field has converged on *sleep-time consolidation* (nanobot Dream, CowAgent deep_dream, sfz009900 short/long sleep, Katra, memmy induction) and *decay as a first-class force* (cortex-mem, FSRS, Memorys' per-kind physics, MemRL utility) — and the weakest designs are uniformly the ones with neither: append-only stores that never forget and never consolidate. v2 already has consolidation + retention; the steals above give it decay, watermarks, and abstention — the three missing forces.
