# TEAM 9 (WAVE 2) — MEMORY, CONTEXT & PERSONA SYSTEMS: Mega-scan report

**Scope:** 40 NEW repos (none overlap Team 3's Wave-1 set: memvid, tigerless agent-memory, graph-memory-starter, lossless-memory, HippoRAG, memoria, context-infrastructure, cortex-mem). Candidates: 296 unique from the 9 assigned searches + targeted supplements (letta/persona/generative-agents lanes).

**Method (rate-limit switch):** GitHub API (MCP) hit HTTP 429 hard; per owner instruction, reads moved to `git clone --depth 1` + local file reads. API used only for discovery searches. Depth (2–6 core files fully read) on real systems; one line for trivial/guide/tutorial repos.

**The v2 yardstick:** v2 has sqlite FTS5 (BM25) episodic+semantic memory, provenance tiers, secure `forget()`, versioned facts. Known gaps: **TTL, confidence decay, conflict resolution on the write path**. Every entry ends with a steal verdict against that yardstick.

---

## 1. mem0ai/mem0 (67.5k★, alive 2026-10-20, Apache-2.0) — the category standard

**Store schema:** facts live as vector-store payloads: `{data (text), hash (md5 of text), text_lemmatized, created_at, updated_at, user_id/agent_id/run_id, actor_id, role, expiration_date?, linked ids}`. A sqlite **history table** logs every mutation (ADD/UPDATE/DELETE, prev_value, new_value, actor, timestamps, is_deleted) — full audit trail beside the live store.
**Write path (`mem0/memory/main.py: _add_to_vector_store`, "V3 phased batch pipeline"):**
- Phase 0: pull last 10 session messages for context.
- Phase 1: embed the new messages, vector-search top-10 existing memories in scope.
- Phase 2: ONE LLM call (`ADDITIVE_EXTRACTION_PROMPT`) sees existing memories (UUIDs remapped to small ints — anti-hallucination: the LLM can only reference "0".."9") + new messages → extracts new facts, each optionally linked to existing ones.
- Phase 3/4: batch-embed extracted facts, create with history rows.
**Retrieval math (`mem0/utils/scoring.py: score_and_rank` + `_search_vector_store`):** over-fetch semantic top `max(limit*4, 60)`; BM25 keyword leg with **sigmoid normalization** `1/(1+exp(-k(score-mid)))` where (mid,k) adapt to query length (≤3 terms: 5.0/0.7 → >15 terms: 12.0/0.5); entity boosts from an entity store (weight 0.5); `combined = min((semantic + bm25 + entity) / max_possible, 1.0)` with max_possible ∈ {1.0, 1.5, 2.0, 2.5} depending on which signals are active. Semantic threshold gates BEFORE combining.
**TTL:** YES — per-memory `expiration_date` (YYYY-MM-DD); expired rows are filtered at search (`_payload_is_expired`), `show_expired` flag can reveal them.
**Conflict resolution:** extraction is *additive-first*; conflicts are resolved by the LLM seeing existing facts during extraction and by explicit update/delete API (`_update_memory` re-embeds, rewrites payload, logs history, re-links entities). No automatic contradiction detector — recency wins by LLM judgment at write time.
**Persona:** none built in; the "profile" is emergent from user-scoped facts.
**Steal verdict for v2: HIGH (ideas + formulas).** Three directly portable pieces: (1) sigmoid-normalized BM25 with query-length-adaptive (mid,k) so FTS5 scores can be *added* to other signals in v2 without scale chaos — pure stdlib math; (2) `expiration_date` TTL column + hide-at-search — closes v2's TTL gap in ~15 lines; (3) the history/audit pattern v2 already half-has via session events — extend to fact mutations.

## 2. Gentleman-Programming/engram (7.5k★, alive 2026-10-20, MIT) — the closest cousin to v2

Go binary, agent-agnostic, **SQLite + FTS5 — the same storage bet as v2**, for coding agents.
**Schema (`internal/store/store.go`):** `observations(id, sync_id, session_id, type, title, content, tool_name, project, scope, topic_key, normalized_hash, revision_count, duplicate_count, last_seen_at, pinned, created_at, updated_at, deleted_at)`; FTS5 virtual table over title/content/tool_name/type/project/topic_key with **trigram tokenizer**; `observation_versions` (full version history per observation); `memory_relations` (typed edges with verbs + confidence, `relations.go: JudgeRelation/JudgeBySemantic` — LLM-judged linking); `user_prompts` + prompt tombstones.
**Write/dedup:** `normalized_hash` dedups; re-saving an existing fact bumps `revision_count`/`duplicate_count` and `last_seen_at` instead of duplicating. A deterministic SQLite scalar function (`candidate_relevance.go: engram_save_candidate_relevant`) gates save-candidates by normalized title-term overlap with a stopword list — deliberately NOT BM25 ("corpus-dependent magnitude is not evidence").
**Conflict resolution — the best in this scan (`internal/store/consolidate.go`):** merging N observations into one survivor is **plan-then-mutate**: plan resolves every refusal first (needs ≥2 sources, no duplicate IDs, no cross-project mixing, no provenance cycles); each plan carries a SHA fingerprint of the resolved sources; confirm requires the same fingerprint, and execution re-resolves inside the same transaction — a changed source forces re-plan, never a blind write. Survivor content gets a `## consolidated_from` provenance footer listing source sync_ids.
**Forgetting:** soft-delete (`deleted_at`) + dead-row pruning for sync evidence (`dead_row_prune.go`: age cap 30d + per-scope cap 1000, newest kept). No time-decay of live facts — pinned flag protects.
**Persona:** none (coding agents). Context: `context_history.go` assembles session context for MCP `mem_context` pulls.
**Steal verdict for v2: HIGHEST — adopt the consolidation protocol.** v2's missing conflict resolution should be plan→fingerprint→confirm, not an LLM coin flip: deterministic, auditable, fits v2's verified-facts ethos. Trigram FTS5 is also a one-line upgrade for Hinglish substring matching. MIT → code patterns liftable with attribution.

## 3. MemoriLabs/Memori (17.1k★, alive 2026-10-20, Apache-2.0) — SQL-native structured memory

**Design:** "agent-native memory infrastructure" — executions are distilled by an augmentation pipeline into a relational store (multi-DB: sqlite/Oracle/etc. migrations) instead of a vector DB.
**Schema (`memori/storage/migrations/_oracle.py`):** `memori_entity`, `memori_entity_fact(id, uuid, entity_id, content, content_embedding, num_times, date_last_time, uniq CHAR(64), date_created, date_updated)` with UNIQUE(entity_id, uniq); plus `memori_subject`/`memori_predicate`/`memori_process_attribute` — a **subject-predicate-object triple store** beside the facts. Index on `(entity_id, num_times DESC, date_last_time DESC)`.
**Write/dedup:** fact identity = `uniq` hash per entity; a repeated fact **increments `num_times` and refreshes `date_last_time`** — frequency *is* the reinforcement signal, rows never duplicate.
**Retrieval (`memori/memory/recall.py`, `memori/llm/pipelines/recall_injection.py`):** search returns facts with `rank_score`; injection filters by `recall_relevance_threshold`, formats each as `- {content}. Stated at {date}`, and attaches per-fact **summaries** (first = primary, rest = additional) — a fact carries its own compressed context. Injection goes into the system prompt via framework middleware (LLM-framework intercept), not as a user message.
**Decay/TTL/conflict:** no decay math; freshness ordering via date_last_time + num_times. Conflict = same-entity uniq collision → reinforcement, not contradiction handling.
**Persona:** entity-centric — the "user" is an entity whose facts accumulate; no persona authoring.
**Steal verdict for v2: MEDIUM-HIGH (one mechanism).** `num_times + date_last_time` reinforcement columns on v2 facts: two columns + an upsert change, gives v2 a frequency signal for ranking and for decay exemptions. The "Stated at {date}" injection suffix is a 1-line provenance win for the prompt.

## 4. EverMind-AI/EverOS (13.5k★, alive 2026-10-20, Apache-2.0) — Markdown is the database

**Design:** portable, local-first, **Markdown-native**: the source of truth is human-readable `.md` files per user — `users/<id>/user.md` (profile), `users/<id>/.atomic_facts/atomic_fact-<YYYY-MM-DD>.md` (daily fact logs), episode files, foresight files, agent_case/agent_skill files. A filesystem-watcher "cascade" (`src/everos/memory/cascade/`: scanner → orchestrator → reconciler → handlers) projects markdown into derived indexes (LanceDB vectors + sqlite) — edit the markdown by hand and the indexes follow.
**Profile schema (`infra/persistence/markdown/mds/profile.py`):** frontmatter `summary` (free-form paragraph = retrieval anchor) + `explicit_info` (verbatim user-stated facts) + `implicit_traits` (LLM-inferred preferences) — **two provenance buckets kept visibly separate**, exactly v2's provenance-tier philosophy. Re-extraction trigger: `profile_timestamp_ms` vs cluster `last_ts_ms` — re-synthesize only when newer MemCells exist.
**Memory types:** atomic_fact (hangs off a source "MemCell"), episode, **foresight** (forward-looking predictions as first-class memories), agent_case/agent_skill (the agent's own learned cases/skills). Atomic-fact frontmatter carries `deprecated_entries` — invalidated facts are deprecated in-file, not deleted.
**Retrieval (`src/everos/memory/search/`):** HYBRID = **RRF fusion (k=40–60) of BM25 + dense MaxSim → logistic-regression reranker → heap expansion → eviction**; AGENTIC mode adds cross-encoder rerank; LLM_MULTIROUND mode: an LLM decider pins a "core" set and issues gap-covering sub-queries per round. **Final injection order is specified: core first → each sub-query's top-1 guaranteed → fill by max RRF score.** Owner partition is hard: user searches return episodes+profiles, agent searches return cases+skills, never mixed.
**Steal verdict for v2: HIGH (two mechanisms).** (1) The injection-order spec (pinned-core → per-aspect top-1 → score fill) is a deterministic prompt-assembly rule v2 can adopt verbatim in stdlib — prevents one hot topic from evicting everything else. (2) explicit/implicit profile buckets = validation of v2's tier design; steal the *freshness-trigger* (re-derive profile only when newer evidence exists) for v2's user-model updates.

## 5. BAI-LAB/MemoryOS (1.6k★, EMNLP 2025 Oral, alive, Apache-2.0) — OS paging for memory

**Design:** explicit OS analogy in JSON files + FAISS (`memoryos-pypi/`): ShortTerm = deque, capacity **10 QA pairs**, FIFO; MidTerm = segmented sessions, capacity 2000, **LFU eviction**; LongTerm = user_profile + user_knowledge + assistant_knowledge deques, capacity 100 each.
**The heat equation (`mid_term.py: compute_segment_heat`, the famous bit):** `H = α·N_visit + β·L_interaction + γ·R_recency`, α=β=γ=1.0, `R_recency = exp(-Δhours/24)`. Eviction and promotion between tiers are driven by heat; a max-heap keyed on -H picks eviction candidates. New pages merge into an existing session when combined similarity ≥ 0.6, else a new session starts.
**Retrieval (`retriever.py`):** page-level cosine similarity, threshold 0.1, heap top-N across sessions; long-term knowledge search threshold 0.1/top-5. Injection = retrieved pages + knowledge concatenated as context.
**Forgetting:** capacity eviction only (LFU in mid-term) — no semantic decay; heat *is* the closest thing: cold segments sink and get evicted first.
**Persona:** `update_user_profile(merge=True)` — profile is a merged JSON dict, updated by the updater LLM pass; assistant has its own knowledge deque (self-model, primitive but present).
**Steal verdict for v2: MEDIUM (formula only).** `H = visits + interactions + exp(-age/τ)` with τ=24h is a clean, stdlib, zero-ML **confidence/freshness score** for v2's facts — gives decay a number to sort and threshold on. The tier capacities (10/2000/100) are toy numbers, skip those.

## 6. Shikigami-Lab/Shikigami-Protocol (12★, alive 2026-09, AGPL-3.0 → ideas only) — the persona state-machine reference

Local-first character-companion framework (Python). Persona is NOT a prompt blob — it is **three coupled state machines** persisted as JSON per profile:
**Emotion (`src/engines/emotion_engine.py`):** state = up to 3 weighted emotion layers (primary/secondary/tertiary + intensities) + `energy_level` 0–100. Energy recovers **+2.0 per 300s** in a background task (full recovery 4h); emotions apply instant energy deltas (excited/joyful +8, tired/sad/anxious/frustrated −25). Post-chat, a secondary LLM classifies the exchange fire-and-forget. The code comments explicitly warn about the **feedback loop**: cheerful persona → positive classification → energy surge → even more hyper prompt → runaway; impact values are capped for this reason.
**Affinity (`src/engines/affinity_engine.py`):** numeric score (start 100, max 1400) adjusted by an LLM every N messages; 8 tiers (stranger → eternal bond) each mapped to a *behavior description* (e.g. familiar = "warm, proactively caring, occasional light jokes"); state file tracks total_interactions + milestones_unlocked.
**Persona evolution (`src/core/persona_evolution.py`):** a `core_anchor` is distilled from base_prompt + style constraints; after each memory-refresh cycle an evolution pass rewrites the working persona, appending to `persona_changelog.json` (last 20 entries) with **rollback to any version**.
**Prompt assembly (`src/prompt/segments/`):** registered segments with numeric priorities (affinity_state = 67) and trigger modes (`always`/conditional); segments include emotion_state, energy_state, long_term_facts, mid_term_memory, lorebook, user_persona, time/weather context, reflection output.
**Steal verdict for v2: MEDIUM (ideas only, AGPL).** JARVIS's persona is fixed-butler by design, so affinity tiers don't apply — but two things do: (1) **changelog + rollback for any self-modifying prompt/persona state** — if v2 ever lets golden-pairs evolve behavior, version them like this; (2) the energy/feedback-loop caution is a documented failure mode for ANY stateful persona — worth a line in v2's proactivity design (enthusiasm must not self-amplify).

## 7. Ch1rpy2613/Mirrai (1.29k★, alive 2026-10-19, MIT) — persona rebuilt from real chat logs

TypeScript app that rebuilds a digital persona of a real person from uploaded chat logs (WeChat/QQ exports), then chats as them.
**Persona representation (`server/_core/persona-utils.ts`):** personaData = distilled style/traits from the logs; system prompt composed from name + relationshipDesc + together-period (from/to dates); AI-transparency defaults ON (admits being AI when sincerely asked) — an honest-persona switch in env.
**Intimacy (deterministic, no LLM):** `score = min(chats*2,300) + min(messages*0.5,200) + min(memoryCount*15,150) + min(emotionVariety*25,150) + min(days*0.5,100) + min(consecutiveDays*10,100)`, capped 1000; tiers at 0/100/300/600/1000.
**Emotion state (deterministic regex classifier):** keyword classes over (userMsg + aiReply) → states warm/playful/nostalgic/melancholy/happy/distant, each with a one-line behavior description injected into the prompt; falls back to previous state. Zero LLM cost — contrast Shikigami's LLM classifier.
**Memory:** extracted "memories" count feeds intimacy; chat-derived facts stored per persona.
**Steal verdict for v2: LOW-MEDIUM.** The capped-additive intimacy formula is a neat deterministic alternative to LLM-judged relationship state, but JARVIS's relationship with Owais is fixed — the portable bit is the **regex emotion-state classifier**: v2's proactivity could cheaply tag conversation mood (tired/frustrated keywords) without a model call.

## 8. Timwood0x10/Mnemosyne (4★, alive 2026-08, Apache-2.0) — LLM-free memory distillation (Rust)

MCP server that "compiles" conversations into structured cognition with **zero LLM calls**: rule-based extractor, entity resolver, dictionary/lexicon matching.
**Decay — the most explicit policy in the scan (`src/decay.rs`):** deterministic; strategies Time/Importance/AccessFrequency/Hybrid (default Hybrid); defaults **TTL 90 days, importance_threshold 0.3, access_threshold 5, decay_factor 0.5**. Crucial invariant, stated in code: **decay never deletes** — it writes back a `weight` and an `archived` flag only, so the persona-evolution timeline stays reconstructable (append-only ADD-style store underneath, SQLite fact store).
**Exemptions:** `is_high_value()` — Relationship-type facts and agent-personality facts **never decay**.
**Persona extraction (`src/personality.rs`):** keyword-pattern table (keyword → trait, weight) producing Trait{name, confidence, evidence-snippet} — every inferred trait carries its textual evidence; profiles are sorted by confidence. Built for literary characters (patterns include Dream-of-the-Red-Chamber cues) but the mechanism is domain-free.
**Steal verdict for v2: HIGH (policy, not code).** This is the missing v2 decay spec, fully written: thresholds, factor, archive-don't-delete, and *type-based exemptions*. v2's facts already have types/provenance — applying "P0/identity facts never decay; others weight × 0.5 past TTL unless accessed ≥5 times" is a small, testable stdlib module.

## 9. sheshpalsingh01/lang_memory (0★, alive 2026-10, no LICENSE → ideas only) — Generative-Agents scoring, production-shaped

Despite the name, a complete 3-layer memory for voice-calling agents: L1 active-call working memory, L2 per-caller memory, L3 global knowledge (Postgres or files).
**The scoring formula (`layer2_calling_memory.py: recall_episodes`) — the cleanest small implementation of the Stanford memory-stream math found:** over-fetch `k*4` (min 8) by vector relevance → min-max normalize relevance across candidates → `score = 1.0*norm_relevance + 1.0*exp(-0.02*age_days) + 1.0*importance` (recency half-life ≈ 35 days). Importance is **not** LLM-guessed per memory: it is mapped from the call outcome (`booked 1.0, callback 0.8, not_interested 0.6, failed 0.5, info_only 0.3`) — domain events carry salience.
**Write path (`extraction.py`):** ONE structured LLM call at call-end → CallRecord{summary, outcome enum, typed CallFacts(name, preferred_language, preferred_callback_time, do_not_call)}; durable facts and sensitive data are separated by design (document numbers never enter memory; they go through an encrypted KYC path). Extraction failure → fallback record, never a crash.
**Reflection:** `reflect()` distills durable preferences from episode texts into the caller profile (Generative-Agents-style, on demand). `forget()` implements full erasure (profile + episodes + global contributions by caller_id).
**Steal verdict for v2: HIGH (formula + one design rule).** The outcome→importance map generalizes: **v2 should derive fact importance from event type** (correction = 1.0, stated preference = 0.8, incidental mention = 0.3) instead of a flat default — 10 lines, makes decay and ranking meaningful. The formula itself is the reference implementation to mirror next to MemoryOS's heat.

## 10. bal-spec/sillytavern-character-memory (75★, alive 2026-10-19, license: none seen in-tree → ideas only)

SillyTavern extension: auto-extracts structured character memories from roleplay chat into lorebook (world-info) entries.
**Extraction:** LLM pass instructed to extract ONLY new facts/events/relationship developments **not already covered by the character card or existing memories** — dedup is enforced in the prompt against the existing memory text (LLM-side, no embeddings). Output = MemoryBlocks `{chat, date, bullets[]}`.
**Consolidation (`consolidation.js`):** map-reduce over memory blocks — pack blocks into chunks, one LLM consolidation call per chunk, **one retry per chunk, cancel-aware**, partial results preserved; consolidated text replaces the blocks.
**Persona model:** the character card is the immutable persona anchor; memories are strictly the *delta* (what the card doesn't know). Injection rides SillyTavern's lorebook keyword/depth machinery.
**Steal verdict for v2: LOW.** The pattern (card = anchor, memory = delta) restates v2's SELF.md + facts split. The chunked-consolidation-with-retry is a decent template if v2 ever compacts episodic logs, but engram's consolidation protocol (##2) is strictly stronger.

---

## 11. MemMachine/MemMachine (3.1k★, alive 2026-10-19, Apache-2.0) — features as tuples, consolidation as a pass

Server-grade universal memory layer. Two stores: **Episodic** (short-term + long-term; long-term splits into declarative memory and event memory with a segmenter/deriver pipeline) and **Semantic** (`packages/server/src/memmachine_server/semantic_memory/`).
**Semantic schema (`semantic_model.py`):** a feature is `(set_id, category/tag schema, feature name, value)` + metadata with **citations = the episode UUIDs the feature was derived from**. Semantic types are configured with a tag dictionary + description, which generates the update/consolidation prompts.
**Write path (`semantic_ingestion.py: IngestionService._process_single_set`):** background service walks un-ingested history per set; for each semantic type, the LLM sees up to `max_features_per_update` existing features + new episodes and emits **SemanticCommands — only ADD and DELETE exist** (an update is delete+add; there is deliberately no in-place edit verb). A separate `llm_consolidate_features` pass periodically merges/dedups features within a tag.
**Conflict resolution:** the consolidation pass *is* the conflict resolver — bounded (one tag at a time, capped feature window) and citation-preserving.
**Retrieval:** set-scoped search over features + episodes; features inject as structured profile lines.
**Steal verdict for v2: MEDIUM-HIGH.** Two ideas: (1) **citations on every derived fact** — v2 has provenance tiers; adding source-event IDs per fact is cheap and powers "why do you believe that?" answers. (2) The ADD/DELETE-only command vocabulary for LLM memory edits — a smaller, safer action space than free-form update, and it maps onto v2's versioned facts (delete = supersede).

## 12. memodb-io/Acontext (3.7k★, alive 2026-10-19, Apache-2.0) — memory IS skills; retrieval is disclosure, not search

"Agent Skills as a Memory Layer" (clients + dashboard + docs in OSS repo; the distillation service is hosted — mechanism below is from the repo's own README/docs, marked as such).
**Storage:** learnings are **Markdown skill files** (SKILL.md schema), organized in "learning spaces". The memory's *structure itself is user-designed*: you attach a "working context skill" that defines naming/layout (e.g. one file per contact, one per project).
**Write trigger (the distinctive bit):** task marked complete **or failed** → distillation LLM pass over messages+execution trace (what worked, what failed, user preferences) → a "Skill Agent" decides existing-skill vs new-skill and rewrites the file. Failure trajectories are first-class learning input, not noise.
**Retrieval:** deliberately **no embeddings, no top-k** — "progressive disclosure": the agent gets `get_skill`/`get_skill_file` tools and pulls what it reasons it needs. Memory you can git, grep, zip, and read.
**Conflict handling:** file rewrite by the skill agent (latest distillation wins, git history is the audit trail).
**Steal verdict for v2: MEDIUM (philosophy check).** v2 already has skills + golden pairs; Acontext argues the *correction pairs should live as editable skill files*, not a JSONL black box — Owais could open and edit what JARVIS "learned". The task-outcome trigger (learn on complete AND on fail) is a concrete upgrade to v2's correction-only learning trigger.

## 13. ClaudioDrews/memory-os (1.38k★, alive 2026-10-17, MIT) — 7 layers + trust scores + the Ground-Truth lesson

A memory OS for Hermes Agent (plugin + Docker worker: Qdrant + Redis). Layers: 1 workspace files (MEMORY.md/USER.md injected every turn), 2 sessions (FTS5 over all history), 3 structured fact store, 4 "Icarus fabric" (entity graph), 5 Qdrant semantic search, 6 self-curating LLM wiki, 7 ground-truth hierarchy.
**Fact schema (`layers/03-fact-store.md`):** `facts(fact_id, content, category ∈ user_pref|project|tool|general, entities JSON, tags, trust_score, retrieval_count, helpful_count, created_at, last_accessed_at)` in SQLite + FTS5 (+ HRR vectors for entity resolution).
**Trust scoring:** `trust_score` from helpful/(retrieved) ratio with a **Bayesian prior starting at 0.50**; the agent MUST call `fact_feedback(helpful|unhelpful)` in the same turn it uses a fact — the docs admit without feedback "trust_score is ornamental and fact quality degrades silently". Tool surface includes `fact_store(action='contradict')` — an explicit conflict finder.
**Injection:** Icarus fork injects labeled blocks `[qdrant] [fabric] [sessions] [facts]` on the **first turn only** (cost control).
**Layer 7 — the scan's best documented failure mode (`layers/07-ground-truth.md`):** injection alone did nothing — the agent ignored injected memory and re-searched files, because its identity docs ranked terminal output and official docs as ground truth and *didn't list injected memory at all*. Fix: SOUL.md's truth hierarchy explicitly ranks injected memory #2 (ground truth for prior decisions), above official documentation. "No status = no authority."
**Steal verdict for v2: HIGH (two cheap mechanisms).** (1) **trust_score with feedback loop** — v2 facts get retrieved but never graded; retrieval_count/helpful_count + same-turn feedback gives decay a *quality* signal to complement Mnemosyne's time signal. (2) The Ground-Truth rule maps directly onto v2: JARVIS-RULES/SELF.md should state that memory hits outrank model priors — one paragraph, zero code, fixes a real observed failure class.


## 14. DrJonaC/Pensieve (1.38k★, alive 2026-10-13, MIT) — contextual-integrity tiers on every memory

TypeScript memory layer + dashboard for coding-agent hosts (Claude Code/Codex adapters). Its distinctive organ is **CDV — contextual drift/violation checking** (`lib/cdv.ts`).
**Model:** every MemoryUnit carries `origin_context` (free text of where it was learned) and an `origin_tp` — a transparency/privacy tier from a poset: `public(0) < consent-required(1) < reciprocity(2) < confidentiality(3)`. Categories (preference/medical/financial) are classified by deterministic keyword scoring, each with a baseline tier (medical = confidentiality, financial = consent-required, preference = public).
**The check:** when a memory is about to be used in a new context, the current context is classified the same way; `gap = origin_rank - current_rank`; gap 0 = clean, gap 1 = warning ("minor contextual drift"), gap ≥2 = critical violation — with a generated human-readable reason. Unknown current context is treated as `public` precisely because that *maximizes* detection of sensitive-memory leakage.
**Steal verdict for v2: HIGH (concept, small code).** v2's DCL classes (PUBLIC/PERSONAL/SENSITIVE/SECRET) already gate egress to providers — CDV adds the missing half: **an origin tier stored on each memory + a deterministic gap check at retrieval time**, so a fact learned in a private context can't silently surface in a casual one. Directly extends DCL from data-in-motion to memory-at-rest.

## 15. VectorSpaceLab/general-agentic-memory / GAM (864★, alive 2026-10-10, MIT) — memory as a filesystem, maintained by a researcher

**Storage:** memory is a literal directory tree on disk (`src/gam/core/node.py: FSNode{name, node_type, content, summary, children, meta, created_at, updated_at}`); every directory carries an LLM-written **summary/README of its subtree** — the index is the folder structure itself.
**Two-agent split:** an online agent answers by exploring the tree (summaries first, drill down on demand); an offline "deep research" process integrates new material — chunking, filing into the right directory, rewriting summaries up the tree. All writes execute as Linux commands inside a sandboxed (Docker) workspace; read nodes are immutable views.
**Retrieval:** no vectors in the core loop — navigation by summary, i.e. retrieval = hierarchical disclosure (same family as Acontext's, but tree-shaped instead of skill-shaped).
**Steal verdict for v2: LOW-MEDIUM.** v2's knowledge skill is already a file tree with an index; GAM's portable idea is **summary-per-directory maintained by a background pass** — v2's knowledge base could carry per-folder summaries so the knowledge skill navigates instead of flat-searching. Not a memory-store change.


## 16. ace-agent/ace (1.38k★, alive 2026-10-19, Apache-2.0) — context as an evolving playbook (code read via API after clone stalls)

ACE (Agentic Context Engineering, arXiv 2510.04618) treats the *context itself* as the memory: a **playbook** of ID'd bullet points in sections.
**Loop (`ace/ace.py`):** Generator answers using the playbook and reports which bullet IDs it used (logged to `bullet_usage_log.jsonl`) → **Reflector** tags each used bullet helpful/harmful/neutral from the outcome → per-bullet counters update (`update_bullet_counts`) → **Curator** edits the playbook with **incremental delta operations only** (add/update/remove bullets) — never a full rewrite, which the paper shows causes "context collapse"; playbook token budget default 80,000. A BulletpointAnalyzer dedups bullets by embedding similarity ≥ 0.90.
**Why it matters here:** the helpful/harmful counter per bullet is memory-os's fact trust score applied to *instructions*. Persona and procedure memory both become self-grading.
**Steal verdict for v2: MEDIUM-HIGH (pattern).** v2's TEACHING.md/golden pairs are a static playbook today; ACE's loop (cite-what-you-used → grade it → delta-edit) is the upgrade path, and the counters give the grading signal Mnemosyne-style decay needs. Full ACE needs an outcome signal per turn — v2 has one: Owais's corrections.

## 17. volcengine/MineContext (5.5k★, alive 2026-10-19, Apache-2.0 — README/structure-level; backend clone stalled)

ByteDance's proactive context partner: continuous **screenshot capture → comprehension → storage → resurfacing**. Produces six context types (activities, summaries, todos, insights…) and *proactive delivery* (daily/weekly digests on a homepage) rather than query-only recall. All data local by default (`~/Library/Application Support/MineContext/Data`), OpenAI-protocol model config incl. local models. Sibling project OpenViking = "context database" unifying memories/resources/skills in a filesystem paradigm (same family as GAM #15).
**Steal verdict for v2: LOW for memory internals; NOTE for proactivity.** v2's screen watcher is RAM-only/off-by-default by Owais's rule — MineContext is the always-on opposite. The portable piece is the *resurfacing* contract: stored context must come back as digests/todos unprompted, which v2's morning-digest plan already adopts.

## 18. boomyjee/slonagent (4★, alive 2026-10-18, license: none seen → ideas only) — the most complete small retrieval stack

Russian-built agent with **pluggable memory providers** (file / RAG / letta-like / fact) plus context compressors (window, log).
**Fact recall (`src/memory/providers/fact/recall.py`) — 4-way parallel:** (1) semantic (LanceDB), (2) BM25 (SQLite FTS5), (3) graph LinkExpansion over entity co-occurrence + causal links, (4) temporal (dateparser constraints + spreading) → fused by **RRF (k=60)** → FlashRank cross-encoder rerank of top 30. Constants in code: `SEMANTIC_THRESHOLD=0.3`, `MAX_ENTITY_FREQUENCY=500` (over-frequent entities skipped as stop-entities), `CAUSAL_WEIGHT_THRESHOLD=0.3`; recall depth by budget tier low/mid/high with a soft max_tokens cap.
**Staleness as API surface:** recall responses carry `pending_consolidation` and `is_stale` — callers are *told* when unconsolidated facts exist instead of silently reading stale memory.
**Steal verdict for v2: MEDIUM-HIGH (two details).** (1) `is_stale/pending_consolidation` flags on v2 memory results — one boolean that makes the brain honest about memory freshness. (2) The entity-frequency cap (500) as a cheap anti-hub filter if v2's FTS graph grows entity links.

## 19. Kein-chronicle/ai-companion-persona-kit (1★, alive 2026-10-19, MIT) — deterministic companion skeleton

Zero-dependency Python skeleton: **persona-as-data** (YAML persona + daily situation engine). `core/situation.py` computes what the character is doing *right now* from a schedule template + day type; `core/routine.py` builds each day with a stable-seed picker that avoids repeating activities within 5 days; `core/proactive.py: decide()` gates proactive messages with quiet hours (windows may wrap midnight) and daily caps; `core/wellbeing.py` is an explicit **guard mode** — the README frames it as keeping "attachment features from becoming dependence levers"; `core/modes.py` has a write-guard (`assert_can_write`) classifying change requests by kind.
**Steal verdict for v2: MEDIUM (policy patterns).** v2's proactivity already has call-ringing + caps; this kit's portable bits are (a) quiet-hours as wrap-midnight windows in config, and (b) a written wellbeing rule for proactive behavior — JARVIS should never optimize for Owais's dependence, only for his outcomes. Both are config/doc-level, zero risk.

## 20. Letta-blocks ports: gordonbrander/pi-memory-blocks (9★, MIT) + joshuadavidthomas/opencode-agent-memory (349★, alive 2026-10-19, MIT)

The MemGPT core-memory pattern, minimal and modern (both code-read):
- **pi-memory-blocks:** blocks are Markdown files with frontmatter (`.pi/memory-blocks/<key>.md`); ALL blocks inject into the system prompt every turn; the LLM self-edits via an `updateMemory` tool; default blocks `user` and `agent`; **per-block character limit default 2000**.
- **opencode-agent-memory (`src/letta.ts`):** tools `memory_set` (overwrite), `memory_replace` (surgical multi-edit in one call — preferred), `memory_get`; block `chars_limit` is a **soft budget**: over-limit writes succeed but flag the block `over_limit` until the agent compacts it; **two scopes** — global vs project blocks, with project-only mode supported.
**Steal verdict for v2: HIGH (validates + sharpens a v2 shape).** v2's SELF.md + semantic facts ≈ blocks + store. The sharp, portable rules: (1) always-in-context memory must have a **hard size budget per block** (2000 chars is the field-tested number); (2) soft-budget-with-flag beats write-rejection — the agent compacts when told, instead of losing facts at the gate. Both fit v2's existing prompt assembly.

## 21. Jacknelson6/owl-brain (6★, alive 2026-06, license in-tree) — provider-stack wrapper

"Advanced memory stack for OpenClaw agents": a `unified/` layer composing Mem0 + ChromaDB + Zep + Letta behind one interface, with a Letta-hierarchy example (core/recall/archival tiers). No novel mechanism found in code — its value is comparative: it demonstrates the four systems are composable behind a single provider interface.
**Steal verdict for v2: NONE (composition reference only).**

## 22. alphaparkinc/genpark-stateful-os-tier-memory-virtualization-agent-skill (9★, alive 2026-09, MIT) — MemGPT paging as an MCP skill

A small MCP server + client exposing Letta-style tiered memory ("OS-tier virtualization with auto-paging") as a portable agent skill. Structure read; the engine is a thin implementation of the well-known MemGPT page-in/page-out pattern without new math.
**Steal verdict for v2: NONE beyond confirming the pattern's portability.**

## 23. HBM1990/persona-state-engine (0★, alive 2026-09, no LICENSE → ideas only) — SOUL.md loader, literally

Two small files: `modfile_parser.py` (loads role YAMLs) and `state_manager.py`, whose `load_identity(identity_file='SOUL.md')` reads an identity Markdown file from a state dir and returns 'No identity found.' otherwise. A skeleton of the same identity-file convention this workspace itself uses.
**Steal verdict for v2: NONE — noted because it independently converged on SELF/SOUL.md-as-identity.**

## 24. ALucek/agentic-memory (555★, alive 2026-10-02, Jupyter) — CoALA teaching implementation

Notebooks implementing the CoALA cognitive architecture (working / episodic / semantic / procedural memory) with LangGraph variants and system diagrams; includes the CoALA paper PDF. Educational, not a shippable system.
**Steal verdict for v2: NONE (taxonomy reference; v2's episodic+semantic split already matches CoALA).**


---

## Quick tier — README/structure-level (mechanism noted; no deep code read unless stated)

| # | Repo | Stars | What it actually is | Memory/persona mechanism | Steal? |
|---|------|-------|--------------------|--------------------------|--------|
| 25 | campfirein/byterover-cli | 4.9k★ | Memory layer for coding agents (TS) | **Context tree with git-like version control** — branch/commit/merge/push for curated project knowledge; REPL + webui curation | Versioned memory trees = engram consolidation's social form; v2: NO (git itself serves this) |
| 26 | rlaope/oh-my-hermes | 3.4k★ | Operating layer over Hermes Agent | Project memory inherited from Hermes + "explicit evidence boundaries" workflow gates | NO — process layer, no new memory mechanism |
| 27 | Ar9av/obsidian-wiki | 3.6k★ | Karpathy LLM-Wiki pattern as 39 Markdown skills | Knowledge **compiled once into an interconnected vault** and kept current (ingest/digest skills), instead of re-running RAG; no runtime, no keys | PARTIAL — v2's knowledge skill could add a weekly "digest/compile" pass (GAM #15's summary maintenance, vault-shaped) |
| 28 | wangziqi06/724-office | 1.0k★ | 24/7 personal agent (WeCom), v2 = 1 Node process + WAL SQLite, zero frameworks | Three layers: session history + **LLM-compressed long-term memory** + LanceDB; top-K memories into system prompt; "layered memory with honest forgetting"; dynamic tool filtering via 5 context profiles | PARTIAL — context profiles for tool filtering (voice/scheduler/group) is a neat token saver for v2's tool list |
| 29 | dimang01/xiyu-ai | 37★ | WeChat-style AI companion framework (JS) | **Memory v2: 7 layers × weights × Ebbinghaus forgetting curve; per-memory pin / lock / NEVER-MENTION flags; semantic recall + keyword fallback; daily reflection engine distills new memories. Persona Guard: post-reply consistency check + deterministic prompt-injection interception** | **YES (one flag)** — the never-mention flag is a per-memory disclosure control, the companion-side twin of Pensieve's tiers (#14); xiyu is the closest design cousin to v2+DCL found in the companion world. (README-level evidence; clone was blocked, code not read.) |
| 30 | ruvnet/ruflo | 77k★ | Agent harness (Claude Code/Codex swarms) | RuVector: local vector search + graph relations + feedback learning; **trajectory learning with contrastive updates** (successful paths reinforced without an LLM) | NO for v2 core; contrastive trajectory updates are the swarm-scale version of ACE counters (#16) |
| 31 | affaan-m/ECC | 284k★ (self-reported ecosystem numbers — treat star/count claims with caution) | Giant Claude-Code harness bundle (agents/skills/hooks) | "Instincts": learned behaviors carrying **confidence scores** that strengthen/weaken with outcomes + continuous-learning hooks + session summaries | PARTIAL — instinct confidence = ACE bullet counters again; three independent systems converging on per-item confidence is the scan's loudest signal |
| 32 | gsd-build/get-shit-done | 64k★ | Meta-prompting/spec-driven dev system | Context engineering via specs and fresh-context execution; no persistent memory system | NO |
| 33 | deepset-ai/haystack | 26.8k★ | Production LLM framework | Pipelines with explicit memory components + agent lifecycle hooks; progressive skill discovery (`SkillToolset` — skill descriptions enter context only when needed) | PARTIAL — progressive tool/skill disclosure is a context-budget pattern v2 can copy for its growing tool list |
| 34 | muratcankoylan/Agent-Skills-for-Context-Engineering | 18.2k★ | Skill collection (not a system) | Skills teaching context curation: compaction, masking, isolation patterns | NO (reading list) |
| 35 | coleam00/context-engineering-intro | 13.8k★ | Tutorial/template | PRP (plan-requirements-product) files as project context | NO |
| 36 | jasontang-ai/Context-Engineering | 9.2k★ | Curated guide (from search metadata) | Survey repo, no system | NO |
| 37 | NeoLabHQ/context-engineering-kit | 1.78k★ | Hand-crafted Claude Code skills | Token-minimal context techniques as installable skills | NO |
| 38 | trpc-group/trpc-agent-go | 1.87k★ | Go agent framework (Tencent) | Session/memory service abstraction (in-memory impl + tools exposure) — framework plumbing | NO |
| 39 | KsanaDock/Microverse | 2.5k★ | Godot multi-agent social sim | MemoryManager + CharacterManager per NPC; game-scale generative-agents descendant (README-level) | NO |
| 40 | NirDiamant/Agent_Memory_Techniques | 1.12k★ | 30 runnable notebooks | Every major pattern incl. MemGPT/Mem0/Zep/Graphiti + LoCoMo bench code | NO (best single study resource in the tier) |
| 41 | pipiku915/FinMem-LLM-StockTrading | 962★ | ICLR-workshop trading agent (arXiv 2311.13743) | Layered memory (perceptual → working/shallow → deep) + **character design** = explicit risk-profile traits that bias decisions; memory adjusts the persona's trading character | PARTIAL — "character = small set of numeric traits that bias behavior" is the domain version of Shikigami's affinity/energy (#6). Clone repeatedly failed on this network; README/paper-level only |

**Coverage count:** 41 repos (24 numbered entries = 25 repos incl. both Letta-block ports, + 17 quick-tier rows... numbered entries total 25 repos; quick tier adds 17 rows but #25–41 above are 17 repos → **42 repos total**, all NEW vs Team 3's set).

**Method honesty:** git-clone path worked for 25 repos; a sandbox guard began blocking new `.git` creation mid-mission, so ACE/MineContext + the quick tier were read via sparing GitHub API calls (README level, or ace.py code level for ACE) — each entry is labeled with its evidence depth. FinMem's clone failed 3× (network disconnects); it is included at README/paper level only and flagged as such.

---

## SYNTHESIS — what the memory/persona field actually converged on (2025–26)

Five independent lines of evidence point the same way:

1. **Every serious system grades its memories.** mem0 (sigmoid-BM25 + entity boosts), memory-os (trust_score, Bayesian prior 0.5, mandatory same-turn feedback), ACE (helpful/harmful bullet counters), ECC (instinct confidence), Memori (num_times reinforcement). Ungraded memory stores all rot. v2 currently retrieves but never grades — the single biggest gap this scan exposes, bigger than TTL.
2. **Decay is a policy, not an accident.** Mnemosyne wrote it down best: TTL + importance threshold + access threshold + ×0.5 factor + archive-don't-delete + type exemptions. MemoryOS's heat `H = visits + interactions + exp(-Δ/24h)` and lang_memory's `relevance + exp(-0.02·days) + importance` are the same shape at different scales.
3. **Conflicts resolve at write time, deterministically where possible.** engram's plan→fingerprint→confirm consolidation is the strongest design; mem0 (LLM sees existing facts during extraction) and MemMachine (ADD/DELETE-only commands + consolidation pass) are the LLM-judged versions. Nobody serious lets contradictions accumulate silently.
4. **Injection is a designed act, not a dump.** EverOS specifies injection ORDER (core → per-aspect top-1 → score fill); Memori filters by threshold and dates every fact ("Stated at …"); the Letta-block ports prove always-in-context memory needs a hard per-block budget (~2000 chars); memory-os's Layer 7 proves injected memory needs *authority* (a ground-truth ranking) or the model ignores it.
5. **Persona = state + anchor, separately versioned.** Shikigami (emotion/energy/affinity state machines + persona changelog with rollback), Mirrai (deterministic intimacy/emotion formulas), charmem (card = anchor, memory = delta), persona-kit (persona-as-data + wellbeing guard). The persona *text* changes rarely and under version control; the persona *state* changes constantly and numerically.

## TOP 5 MECHANISMS (PhD picks)

1. **engram consolidation protocol** — plan-then-mutate merge with fingerprint confirmation and provenance footers; deterministic conflict resolution. (§2)
2. **Mnemosyne decay policy** — TTL 90d / importance 0.3 / access 5 / factor 0.5, archive-never-delete, Relationship+identity facts exempt. (§8)
3. **memory-os trust loop + Ground-Truth hierarchy** — facts graded by same-turn feedback (Bayesian 0.5 prior); identity doc ranks injected memory above model priors. (§13)
4. **lang_memory outcome-mapped importance** — importance from event type (correction 1.0 … incidental 0.3), inside `score = norm_relevance + exp(-0.02·age_days) + importance`. (§9)
5. **EverOS injection order + freshness-triggered profile re-synthesis** — core-first/per-aspect-guarantee/fill ordering; profile re-derived only when newer evidence exists, with explicit-vs-implicit buckets kept separate. (§4)

## TOP 3 STEALS FOR JARVIS v2 (ranked by value × stdlib ease)

1. **Decay + TTL module (closes 2 of v2's 3 known gaps in one move):** add `weight`, `last_accessed`, `access_count`, `expires_at` to facts; policy from Mnemosyne (identity/relationship facts exempt; past-TTL facts weight ×0.5 and archived, never deleted; mem0's `expiration_date` hide-at-search for hard TTL). Importance seeded by event type (lang_memory map). ~120 lines stdlib + tests.
2. **engram-style consolidation for conflicts (closes the 3rd gap):** when a new fact contradicts an existing key, don't overwrite — run plan→fingerprint→confirm merge producing one survivor with a `consolidated_from` footer; expose it through the gate as a tier-2 action. Plus FTS5 **trigram tokenizer** swap for Hinglish substring recall.
3. **Trust grading + authority line:** `retrieval_count`/`helpful_count` on facts, brain marks facts helpful/unhelpful in the same turn it uses them (memory-os), trust feeds ranking beside BM25 (mem0's sigmoid normalization makes the addition scale-safe); and one paragraph in JARVIS-RULES/SELF.md ranking memory hits above model priors (Ground-Truth fix). Bonus micro-steals if budget allows: Pensieve origin-tier per memory (DCL-at-rest), Memori's `num_times` reinforcement + "Stated at {date}" injection suffix, slonagent's `is_stale` flag on memory results.

*Report compiled by Team 9 (Wave 2). All file:function references are from local clones or labeled API reads made during this mission. Clones were scratch under megascan/.work9 and are removed after reporting.*
