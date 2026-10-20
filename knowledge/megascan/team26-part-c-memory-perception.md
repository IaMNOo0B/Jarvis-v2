# MEGA-SCAN TEAM 26 — SLICE C: Relationship Memory & Emotion Perception

Deep-read notes. Tags: [CODE] = read in source, [README] = docs claim, [INFERENCE] = my synthesis.
Clones read from `~/workspace/jarvis-knowledge/megascan/.work26/` (MemoryOS/mem0 first read from the identical
upstream clones in `.work9/`, then confirmed present in `.work26/`). JARVIS v2 baseline for verdicts:
`memory.py` = SQLite episodic + semantic facts, provenance tiers, FTS5, `consolidate()`/`decay()`;
`recall_gate.py` = per-turn recall gate.

---

## MemTensor/MemoryOS

**License: Apache-2.0** [CODE — LICENSE file is the full Apache License 2.0 text; README badge "License: Apache 2.0"].

### 1. Memory architecture in code
Four modules — Storage / Updating / Retrieval / Generation [README] — implemented as three tiers in
`memoryos-pypi/` (duplicated verbatim in `memoryos-mcp/`, `memoryos-chromadb/`, `memoryos-playground/`):

- **Short-term** (`short_term.py`, 66 LOC): `deque(maxlen=10)` of raw QA pairs
  `{user_input, agent_response, timestamp}`, JSON file per user. FIFO eviction only. [CODE]
- **Mid-term** (`mid_term.py`, 393 LOC): *sessions* (topic segments) of *pages* (QA pairs). A session =
  `{id, summary, summary_keywords, summary_embedding, details[pages], L_interaction, R_recency, N_visit,
  H_segment, last_visit_time}`; a page adds `page_embedding, page_keywords, pre_page/next_page` (a linked
  list across pages), `analyzed, preloaded`. Embeddings default `all-MiniLM-L6-v2`, FAISS `IndexFlatIP`
  rebuilt per search. Capacity 2000 sessions, **LFU eviction**. New pages merge into the best session when
  `cosine(summary) + 1.0 * Jaccard(keywords) >= 0.6`, else a new session is created (`insert_pages_into_session`). [CODE]
- **Long-term** (`long_term.py`, 172 LOC), *split per user and per assistant*: (a) one free-text
  `user_profiles[user_id] = {data: str, last_updated}` — a single prose blob, replaced wholesale on update;
  (b) two `deque(maxlen=100)` knowledge bases (user-private knowledge, assistant knowledge), entries =
  `{knowledge: str, timestamp, knowledge_embedding}`. No graph; vectors are stored inline in JSON and
  searched by brute-force FAISS per query. [CODE]

**Promotion math — the stealable core** (`mid_term.py: compute_segment_heat`, `memoryos.py: H_PROFILE_UPDATE_THRESHOLD = 5.0`):
`H_segment = α·N_visit + β·L_interaction + γ·R_recency`, α=β=γ=1, where
`R_recency = exp(-Δt_hours / τ)`, τ=24h (`utils.py: compute_time_decay`). After every `add_memory()`,
`_trigger_profile_and_knowledge_update_if_needed()` peeks the max-heap: if the hottest session's heat ≥ 5.0,
its *unanalyzed* pages are sent (in parallel) to two LLM jobs, pages are marked `analyzed`, and
`N_visit`/`L_interaction` are reset so heat must re-earn the threshold. [CODE]

**Extraction is 100% LLM-prompt, zero rules** (`prompts.py`, `utils.py`):
- `gpt_user_profile_analysis` — PERSONALITY_ANALYSIS prompt scores the user on **90 named dimensions**
  (Big Five + Maslow needs + "AI alignment" expectations: Helpfulness/Honesty/Complexity/Conciseness… +
  ~30 interest tags: Tech Interest, Family Concern, Religious Interest, Emotional Expression, Sense of Humor,
  Language Style…), each as `Dimension (High/Medium/Low)` + brief reasoning, merged into the existing profile
  text in the same call. Dimensions with no evidence are omitted. [CODE]
- `gpt_knowledge_extraction` — KNOWLEDGE_EXTRACTION prompt splits output into *user private data*
  (shortest-possible phrases) vs *assistant knowledge*. [CODE]
- Updater (`updater.py`) also runs LLM multi-topic summarisation (≤2 subtopics) + an LLM continuity check
  (`CONTINUITY_CHECK`: "true/false — is this page a continuation?") to maintain `pre_page/next_page` links
  and a running `meta_info` chain summary. [CODE]
- **Forget rules:** short-term FIFO; mid-term LFU at capacity; long-term knowledge FIFO at 100 entries.
  There is **no semantic decay/forgetting of facts** — heat only gates *promotion*, never deletion. [CODE]

**Retrieval** (`retriever.py`): three parallel searches (mid-term pages, user knowledge, assistant
knowledge; thresholds ~0.1, top-k 5 sessions / 20 knowledge) + the *entire* user profile blob + short-term
history are all stuffed into the generation prompt every turn. No per-turn relevance gate on the profile. [CODE]

**Claims:** LoCoMo +49.11% F1 / +46.18% BLEU-1 over baselines [README]; EMNLP 2025 main [README].

### 2. Relationship-specific?
Weakly, and only as a *prompt parameter*: `get_response(query, relationship_with_user="friend", style_hint="")`
interpolates `{relationship}` into the system/user prompts ("You are talking to your {relationship}…").
There is **no relationship state, no bond variable, no shared-event model** — the "relationship" is a static
string the caller supplies. The genuinely relationship-adjacent asset is the 90-dimension profile: several
dimensions (Need for Belonging, Emotional Expression, Language Style, Conciseness/Complexity expectations of
the AI) describe *how the user wants to be treated by this agent*, not just who the user is. [CODE]

### 5. Steal verdict for JARVIS v2
**Steal the heat-gated promotion trigger, not the storage.** v2's `consolidate()` is time/idle-driven;
MemoryOS shows a better trigger: accumulate a cheap scalar per topic cluster
(`visits + interactions + exp-recency`, all computable in SQLite with no LLM) and only spend an LLM
consolidation/profile pass when a cluster crosses a threshold (their 5.0), then reset its counters.
Also steal the 90-dimension profile *checklist* as the schema for v2's semantic-fact extraction prompt —
it is a ready-made, evidence-gated ("omit if not inferred") taxonomy for "how Owais wants to be spoken to".
Do **not** steal: JSON-file stores, per-user/per-assistant file split, whole-profile-blob replacement
(v2's provenance-tiered facts are strictly better), or unconditional profile injection every turn
(v2's `recall_gate.py` already beats it).

---

## agiresearch/A-mem

**License: MIT** [CODE — LICENSE: "MIT License, Copyright (c) 2025 AGI Research"].

### 1. Memory architecture in code
Zettelkasten in code (`agentic_memory/memory_system.py`, 727 LOC; `retrievers.py` ChromaDB). One type only —
the atomic note [CODE]:

```python
class MemoryNote:  # m_i = {content, timestamp, keywords, tags, context, links, evolution_history,
                   #        category, retrieval_count, last_accessed, id}
```

- **Note construction** (`analyze_content`, LLM prompt, strict JSON schema): for raw content the LLM emits
  ≥3 `keywords` (nouns/verbs/concepts, explicitly *not* speaker names or times), one prose `context`
  ("what this memory means / its broader domain"), ≥3 `tags` (domain/format/type). Content itself is
  **never rewritten by any later process**. Embeddings: `all-MiniLM-L6-v2` into Chroma. [CODE]
- **Link generation** (`process_memory` → `find_related_memories(k=5)`): cosine top-5 neighbours are shown
  to the LLM, which judges links on causal/conceptual grounds embeddings miss. [CODE]
- **Memory evolution** (the paper's contribution, verified in code): one LLM call returns
  `{should_evolve, connections_to_add, tags_to_update, new_context_neighborhood[], new_tags_neighborhood[]}` —
  i.e. it may **rewrite the `context` and `tags` of the existing neighbours** in light of the new note,
  append to the new note's `links`, and log to each note's `evolution_history`. Fail-safe: any exception →
  original note returned unchanged. Every 100 evolutions (`evo_threshold=100`) `consolidate_memories()`
  rebuilds the whole Chroma collection from the in-memory dict. [CODE]
- **Retrieval:** embed query → Chroma top-k, then `find_related_memories_raw` *also inlines every linked
  neighbour's* content/context/keywords/tags — 1-hop graph expansion for free at read time. [CODE]
- **Update/forget:** explicit `update()`/`delete()` APIs only. **No decay, no forgetting, no dedup gate** —
  every `add_note()` is stored; quality control is entirely downstream of evolution. [CODE]
- **Claims:** LoCoMo multi-hop F1 24.55 (no link/evolution) → 31.24 (links only) → **45.85 (full)**,
  GPT-4o-mini [prior PhD study of the same repo/paper, `~/workspace/github-archaeology/phd-studies/diamond-3-a-mem.md`];
  NeurIPS 2025, arXiv 2502.12110 [README/study].

### 2. Relationship-specific?
No user/relationship model at all — notes are speaker-agnostic conversation content; the prompt even forbids
speaker names in keywords. What it models is **memory↔memory relationships** (typed-by-prose links +
backward-propagating reinterpretation), which is the missing half of most user-fact stores. [CODE]

### 5. Steal verdict for JARVIS v2
**Steal evolution as an async post-write pass inside v2's existing `consolidate()`:** after a fact is
stored, take its FTS5/vector top-5 neighbours, ask the (local) LLM one gated question — *should_evolve?* —
and if yes, only rewrite neighbours' *interpretive* fields (a `context`/`tags` column v2 should add) and
append an `evolution_history` row; raw fact text and provenance stay immutable, and untrusted-provenance
facts are excluded from being evolution *sources* (A-MEM amplifies poisoning: one bad note rewrites 5 good
ones — the study's warning, [INFERENCE] load-bearing for v2's tier design). Cost is bounded (k=5, gate
declines most writes, runs in consolidation, never in the chat path).

---

## verygoodplugins/automem (AutoMem)

**License: MIT** [CODE — LICENSE: "MIT License, Copyright (c) 2025 Jack Arturo"].

### 1. Memory architecture in code
A *service*, not a library: Flask REST + MCP server (`app.py`, `automem/`), graph is canonical, vectors are an index.

- **Stores:** FalkorDB graph = source of truth (503 if down); Qdrant = 1024-d embedding per memory
  (recall degrades to graph-only if Qdrant is down). Embeddings pluggable: Voyage / OpenAI / Ollama /
  fastembed / placeholder (`automem/embedding/`). [CODE][README]
- **Per-memory record:** `{id, content, timestamp, updated_at, importance 0–1, confidence 0–1, type,
  tags, last_accessed, metadata}`. Writes are *client-authored* — the calling assistant decides what is
  worth storing and supplies content/importance via `POST /memory`; the server classifies, embeds, links
  and enriches, it does not extract from raw conversation. Edges are first-class objects too:
  associations carry `{strength 0–1, updated_at}` properties. [CODE] **Type is assigned without a mandatory LLM call**: `MemoryClassifier`
  (`automem/classification/memory_classifier.py`) first runs regex pattern banks for 7 types —
  Decision / Pattern / Preference / Style / Habit / Insight / Context (e.g. Preference ← `prefer`,
  `favorite`, `rather than`) — confidence 0.6 + 0.1 per extra matching pattern (cap 0.95); only on no-match
  does it fall back to an LLM JSON classification; final fallback `"Memory", 0.3`. [CODE]
- **Graph structure — 11 authorable typed edges** [README][CODE]: `RELATES_TO, LEADS_TO, OCCURRED_BEFORE,
  PREFERS_OVER, EXEMPLIFIES, CONTRADICTS, REINFORCES, INVALIDATED_BY, EVOLVED_INTO, DERIVED_FROM, PART_OF`,
  plus 3 machine-added: `SIMILAR_TO, PRECEDED_BY, DISCOVERED`. Background *enrichment*
  (`automem/enrichment/`) adds temporal edges, semantic-neighbour edges, and **Pattern nodes**: when ≥N
  memories of a type accumulate, it mints a `pattern-<type>-<hash>` node they `EXEMPLIFIES` — a reified
  generalisation other memories can attach to. [CODE]
- **Recall — 9-component weighted score, no LLM in the read path** (`automem/api/recall.py`,
  `docs/COMPARISON.md`): vector 0.35 + keyword(TF-IDF) 0.35 + relation 0.25 + tag 0.20 + exact-phrase 0.20 +
  importance 0.10 + recency 0.10 (linear, 180 d) + confidence 0.05 + relevance 0.00 (off by default).
  Graph expansion (`expand_relations`) does multi-hop *bridge discovery*: two seed memories sharing an
  `EXEMPLIFIES` edge to a pattern get ranked *below* the bridge — recall returns the "why", not the words. [CODE][README]
- **Consolidation — "dream cycles"** (`consolidation.py`, `MemoryConsolidator`): Decay (daily), Creative
  (weekly, REM-like random-pair association discovery), Cluster (monthly, mint meta-patterns), Forget
  (off by default). The decay formula is explicit and worth quoting [CODE]:

  ```
  relevance = exp(-0.01 · age_days) · (0.3 + 0.3 · access_factor) · (1 + 0.3 · ln(1 + rel_count))
              · (0.5 + importance) · (0.7 + 0.3 · confidence)
  access_factor = 1 if accessed <1d ago else exp(-0.05 · days_since_access)
  floor: relevance ≥ importance · 0.3
  ```
  Archive below 0.2, delete below 0.05 — **but** `_should_protect_memory` vetoes both for: explicit
  `protected` flag, importance ≥ 0.7, age < 90-day grace period, or type ∈ {Decision, Insight}. [CODE]
- **Claims:** LoCoMo (Agent Memory Benchmark) 85.1%, LongMemEval full 87.0% (97.0% recall@5), BEAM 10M
  57.4% while returning only ~2.6–4.8k tokens [README][CODE — docs/COMPARISON.md].

### 2. Relationship-specific?
Its "relationships" are memory↔memory edges, not user↔agent. Two edges are user-model-shaped though:
`PREFERS_OVER` (a first-class preference *ordering*, not a fact string) and identity synthesis
(`automem/consolidation/identity_synthesis.py` — periodically LLM-synthesises an identity/profile document
from the graph). No bond, affect, or shared-history model. [CODE]

### 5. Steal verdict for JARVIS v2
**Steal the protection-veto + the relevance formula's shape for v2's `decay()`:** v2 should never decay
(i) high-importance facts, (ii) anything younger than a grace period, (iii) Decision/Insight-type facts —
and its decay score should multiply in a *connection-count* term (`1 + 0.3·ln(1+links)`) so well-connected
facts (which in v2 = facts FTS5 co-retrieves often) resist forgetting, with an importance floor so decay
is bounded, not terminal. Secondary steal: the regex-first/LLM-fallback classifier — v2 can type its
semantic facts (Preference/Decision/Habit…) for ~free before spending any LLM call. Do **not** steal the
FalkorDB+Qdrant service stack; SQLite already holds v2's scale.

---

## senjinthedragon/Smart-Memory

**License: AGPL-3.0** [CODE — LICENSE is the GNU Affero GPL v3 text; README badge AGPL-3.0].
**Ideas only — never copy code into JARVIS.**

### 1. Memory architecture in code
SillyTavern extension, ~20.4k LOC vanilla JS, per-character stores in extension settings. The most
*tier-complete* design in this slice [CODE — `longterm.js`, `session.js`, `memory-utils.js`, `prompts.js`, `arcs.js`, `canon.js`, `epistemic.js`, `state-ledger.js`, `graph.js`]:

| Tier | Scope | Content |
|---|---|---|
| Short-term | chat | rolling LLM summary, incrementally folded (never rewritten from scratch) |
| Session | chat | granular scene details; extraction is *told what LTM already holds* to avoid duplication |
| Long-term | character, cross-chat | typed facts (below) |
| Scenes | chat | auto-detected scene breaks (time skip / location change / `---`) → per-scene summary |
| Story arcs | chat (pinnable → character) | open narrative threads; resolved arcs get a closing summary |
| Canon | character | prose "story bible" synthesised from resolved arcs + high-importance LTM facts |
| Profiles | character | regenerated snapshots: character state / world state / relationship matrix |
| State Ledger | chat | per-entity *current* physical state cards (location, outfit, injuries, carried items; object/place/faction variants) |
| Entity Registry + graph | character | entities typed character/place/object/faction/concept, memory counts, last-seen index, timelines, force-directed graph with **directed supersession arrows** |

- **Extraction format is a 1-line DSL the LLM must emit** (`buildLongtermExtractionPrompt`):
  `[type:importance:expiration(:entity=Name/type,…)] text` where type ∈ {fact, relationship, preference,
  event}, importance ∈ 1–3, expiration ∈ {scene, session, permanent}. Prompt prioritisation rule #1:
  *"durable memories about the ACTIVE CHARACTER and their bond with the user."* [CODE]
- **Supersession (their word for fact-update):** cheap checks first (embedding similarity + state-change
  patterns like "no longer", "moved to"); only inconclusive pairs above threshold get a narrow binary LLM
  prompt — UPDATE or INDEPENDENT? Retired memories are **kept in storage, excluded from injection**,
  and drawn as arrows in the graph. [CODE]
- **Confidence decay — importance deliberately does NOT decay** (`longterm.js`): re-extracted ("confirmed")
  memories get `confidence = min(1, c+0.05)`, `last_confirmed_ts = now`, counter reset; unconfirmed ones
  increment `unconfirmed_since`, and at ≥10 passes lose 0.02 confidence (floor 0.3). [CODE]
- **Retention utility score** (`memory-utils.js: memoryUtilityScore`) [CODE]:
  `importance·100 + expiration·35 + confidence·25 + persona_relevance·25 + intimacy_relevance·20
   + min(20, retrieval_count·2) + keyword_recurrence·2 + last_confirmed/1e13`; superseded ⇒ 0.001.
  Note the two *relationship-native* terms: `persona_relevance` and `intimacy_relevance` (0–3).
- **Activation triggers:** each memory gets LLM-suggested trigger keywords (synonyms/cues *not in the text*),
  filtered out if they appear in >35% of memories; a trigger hit in the current turn adds +80 to the
  retrieval score (vs +40 for content-word overlap) **and** re-injects the memory in a second slot closer
  to the prompt. [CODE]
- **Consolidation** is per-type with count thresholds (defaults: relationship 3, preference 3, fact 4,
  event 4 accumulated same-subject entries before an LLM merge pass fires), a 5-signal hybrid retrieval
  score (utility + entity-overlap with the current turn + open-arc similarity + temporal proximity +
  last-turn cosine − contradiction penalty), and protected-type floors guarantee at least one
  relationship + one fact memory survives budget trimming. [CODE]
- Default total injection budget 3,750 tokens across tiers, with per-tier auto-tune (observed demand +15%,
  budgets only grow). [README][CODE]

### 2. Relationship-specific? — YES, the best in this slice
A dedicated **Relationship History** store, separate from memories [CODE — `longterm.js: load/save/injectRelationshipHistory`, `prompts.js: buildRelationshipDeltaPrompt`]:
- State = map of **directed** pairs `"A->B"` → ≤6 descriptors, each `{word, magnitude ∈ low|medium|high}`,
  rendered `trusting(high), cautious(medium)`. Direction matters: A→B and B→A are separate lines
  ("feelings are not always mutual").
- After each extraction pass, an LLM *delta* prompt receives the scene + the full current state and must
  **carry all descriptors forward unless the scene explicitly resolves them** (`!descriptor` = resolved/
  removed); new descriptors merge, magnitudes update, cap 6 (lowest magnitude dropped). Descriptor
  validity is prompt-policed: must describe how subject *feels toward* target — "would this word still
  apply if the target left the room? If yes, it is not a relationship descriptor."
- Magnitudes are semantically anchored: low = kind gesture/small disagreement, medium = confession/
  betrayal/reconciliation, high = life-changing/traumatic/years of bonding.
- Injection is presence-gated (only pairs whose names appear in the recent message window) under a
  ~250-token budget — dormant relationships cost nothing.
- Plus: relationship *matrix* in profiles (one directional line per entity + confidence), `[secondhand]`
  tagging of memories the responding character didn't witness, and a 5-tag epistemic store per character
  (Knows / Suspects / Believes-false / Unaware / Hiding-from-whom). [CODE]

### 5. Steal verdict for JARVIS v2
**Steal the Relationship History data model wholesale (idea only — AGPL):** a tiny SQLite table
`relationship_state(pair, descriptor, magnitude, updated_at)` for the single pair that matters —
Owais↔JARVIS — updated by the same gated LLM delta prompt pattern (carry-forward by default, explicit
resolution to remove, cap ~6, magnitude anchored to event classes), and injected only when the turn is
relational. It is the cheapest possible representation of "bond" that still accumulates, and v2 has
nothing like it today: v2 remembers *facts about Owais*, not *the state of the relationship itself*.
Secondary steals: confidence-only decay (importance never decays) and trigger-keywords as an FTS5
synonym column boosting `recall_gate.py`.

---

## KsanaDock/Microverse

**License: MIT** [CODE — LICENSE: "MIT License, Copyright (c) 2025 KsanaDock"].

### 1. Memory architecture in code
Godot 4 / GDScript god-sim: 8 LLM-driven office characters, JSON local saves. Memory is one flat list per
character (`script/ai/memory/MemoryManager.gd`, 175 LOC) [CODE]:

```gdscript
memory_obj = {content: String, timestamp: "YYYY-MM-DD HH:MM", type: MemoryType,
              importance: int, created_at: unix_time}
MemoryType      = {PERSONAL, INTERACTION, TASK, EMOTION, EVENT}
MemoryImportance = {LOW=1, NORMAL=3, HIGH=5, CRITICAL=10}
```

- **What gets stored:** almost entirely *hard-coded template strings from the simulation loop*, not LLM
  extraction — e.g. `AIAgent.gd` writes "You moved to {room} to complete task '{task}'", "You successfully
  completed task: {task}. Felt a great sense of accomplishment!"; `DialogManager.gd` writes mirrored pairs
  ("You started a conversation with X" / "X started a conversation with you"). No summarisation, no
  embeddings — retrieval is (a) sort by (importance desc, timestamp desc) and dump into the prompt, or
  (b) `search_memories`: case-insensitive substring keyword match. [CODE]
- **Forget rule:** `_cleanup_old_memories(max=50)` — hard cap 50/character, keep top-50 by
  (importance, recency). No decay curve, no consolidation. [CODE]
- Personality is a static hand-written dict per character (`CharacterPersonality.gd`: position,
  personality prose, speaking style, duties, habits) — never learned or updated. [CODE]

### 2. Relationship-specific? — the requested "relationship math", honestly: there is almost none
Relationships live **outside** MemoryManager, as Godot node metadata [CODE]:

```gdscript
character.get_meta("relations")  # { target_name: {"type": <emotion:String>, "strength": <int>} }
character.get_meta("mood")       # single String, default "普通" (normal)
```

- **Taxonomy** (`script/ui/GodUI.gd`): type ∈ {喜欢 like, 尊敬 respect, 嫉妒 jealousy, 愤怒 anger,
  信任 trust, 怀疑 suspicion, 崇拜 admiration}; strength is an int slider **−10…+10**
  (labelled: <−5 strong dislike, <0 mild dislike, 0 neutral, ≤5 mild like, >5 strong like). [CODE]
- **Update math: none.** A repo-wide search shows `relations` is *written in exactly one place* —
  `GodUI._on_emotion_confirm()`, i.e. **the human player (as god) sets A→B's emotion by hand in a popup**;
  the same action also appends an EMOTION-type memory ("A developed a strongly positive {type} feeling
  toward B"). No dialogue outcome, LLM judgment, interaction count, or time ever modifies a relation or
  mood automatically — agents never grow closer or apart on their own. [CODE]
- **Use:** relations + mood + health + money are formatted verbatim into every status prompt
  (`AIAgent.get_character_status_info`, duplicated in `ConversationManager.gd` and `DialogManager.gd`):
  "- Toward {name}: {strong|mild|neutral} {type} (strength: {n})" — so the LLM *performs* the relationship
  without the system *tracking* its evolution. [CODE]

### 5. Steal verdict for JARVIS v2
Steal only the *shape*, and as a cautionary tale: a directed `{type, strength −10…+10}` pair is a fine
minimal UI for bond state, but Microverse proves a relationship variable that nothing updates is
theatre — if v2 adopts a bond scalar it must be written by an event-driven rule/LLM delta (Smart-Memory's
model), never left as a static field. The mirrored-pair interaction memory ("you did X with Y" written
to *both* parties) is a genuinely cute trick for a future multi-agent v2, worth one line in the backlog.

---

## mem0ai/mem0

**License: Apache-2.0** [CODE — LICENSE is the full Apache License 2.0 text]. Version in clone: 2.2.1 (`pyproject.toml`). [CODE]

### 1. Memory architecture in code
Single flat memory collection per scope, in a pluggable vector store (Qdrant/Chroma/pgvector/… ~20
backends) + SQLite history DB. Scope is by filter triple `{user_id, agent_id, run_id}` — every memory is a
vector + payload `{data: text, hash: md5(text), created_at, updated_at, user_id/agent_id/run_id,
actor_id, role, linked_memory_ids, expiration_date?}`. There are no tiers and no graph in the OSS core
(entity linking below is the closest). [CODE — `mem0/memory/main.py`, 3,912 LOC]

**Write path v3 — "phased batch pipeline"** (`_add_to_vector_store`) [CODE]:
0. Gather session scope + last 10 messages from the history DB.
1. Embed the new messages, vector-search top-10 existing memories; remap their UUIDs to small ints
   ("0","1",…) before showing the LLM — an anti-hallucination guard so the model can't invent IDs.
2. **One** LLM call with `ADDITIVE_EXTRACTION_PROMPT`: extract *contextually rich, self-contained*
   memories (15–80 words, pronouns resolved, relative dates converted to absolute against the
   *observation date*, exact quantities/proper nouns preserved, transitions captured as
   "switched from X to Y because Z"), from **both** user and assistant messages, each with
   `linked_memory_ids` pointing at related existing memories. The older two-phase path
   (`FACT_RETRIEVAL_PROMPT` → `DEFAULT_UPDATE_MEMORY_PROMPT` deciding ADD/UPDATE/DELETE/NONE per fact)
   still exists in `mem0/configs/prompts.py` and in the async/legacy code paths. [CODE]
3. Batch-embed all extracted texts. 4. CPU pass: lemmatise for BM25. 5. **MD5-hash dedup** against
   existing + in-batch hashes — exact-duplicate facts are dropped without any LLM cost.
- **Entity linking:** extracted entities get their own vector-store collection; a memory mentioning an
  entity appends its ID to that entity's `linked_memory_ids` (and unlinking on delete is handled) —
  a poor-man's graph: entity → memory IDs, no typed edges. [CODE]
- **Update/forget:** UPDATE keeps the ID, bumps `updated_at`, stores `old_memory` in the history DB
  (full audit trail in SQLite `history` table: event, old/new, timestamps, actor, role). DELETE is
  LLM-decided on contradiction in the legacy path; in the additive path, contradiction handling is
  mostly *link, don't delete*. Optional per-memory `expiration_date` is honoured at read
  (`_payload_is_expired`). No decay scoring. [CODE]
- **Procedural memory:** with `agent_id` + `memory_type=procedural`, assistant trajectories are
  summarised into agent know-how — the one place mem0 stores *agent-side* memory. [CODE]
- **Claims:** LoCoMo **92.5**, LongMemEval **94.4** (98.2 on assistant-memory recall), ~7K tokens/query,
  0.88–1.09s latency — for the *current* (v3/platform) algorithm [README].

### 2. Relationship-specific?
No. Facts *about* relationships are a first-class extraction category ("Maintain Important Personal
Details: names, relationships, important dates" — `FACT_RETRIEVAL_PROMPT`), and the additive prompt
insists emotional states/motivations survive extraction ("scared but reassured", "liberated and
empowered" are kept, not stripped) — but the user↔agent relationship itself is never modelled; there is
no bond, no shared-event ledger, no agent-side persona memory except procedural know-how. [CODE]

### 5. Steal verdict for JARVIS v2
**Steal two cheap mechanics, skip the architecture:** (1) **MD5-hash dedup before any LLM/semantic
dedup** in v2's write path — exact repeats (the common case for a daily assistant) should cost zero
tokens; (2) the additive prompt's *quality rules* for v2's fact extractor — self-contained facts,
absolute dates grounded to the observation date, transitions stored as "from X to Y because Z", and
emotional texture preserved rather than flattened. v2's provenance tiers + FTS5 + SQLite history already
cover mem0's audit trail; adopting mem0 itself would *lose* provenance and add a vector-DB dependency.

---

## cjhutto/vaderSentiment (VADER) — the zero-cost text-sentiment option

**License: MIT** [CODE — LICENSE.txt: "The MIT License (MIT), Copyright (c) 2016 C.J. Hutto"].

### 3. Emotion perception in code
Not emotion classification — **valence only**. One file, `vaderSentiment/vaderSentiment.py` (695 LOC),
pure Python stdlib, plus `vader_lexicon.txt` (7,520 tokens, each with a human-validated mean valence
−4…+4 from 10 raters, SD < 2.5) [CODE][README].

- `SentimentIntensityAnalyzer.polarity_scores(text) -> {neg, neu, pos, compound}`; compound =
  `normalize(Σ valence) = s / sqrt(s² + α)`, α=15 → [−1, +1]; thresholds: ≥0.05 positive, ≤−0.05 negative. [CODE]
- **Five rule families adjust raw lexicon valence** [CODE]: (1) punctuation — each `!` adds emphasis
  (capped), `?` weaker; (2) ALL-CAPS differential ±`C_INCR=0.733`; (3) degree modifiers —
  boosters/dampeners ±`B_INCR=0.293` ("very", "uber", "kinda", "marginally"…); (4) negation —
  valence × `N_SCALAR=−0.74` if a negator (incl. `n't` contractions) appears in the preceding window;
  (5) contrastive "but" — sentiment before "but" is halved, after it ×1.5. Plus special-case idioms
  ("the shit" +3, "yeah right" −2) and emoticon/emoji/slang lexicon entries (lol, sux, :D, 💘). [CODE]
- **Accuracy claims:** paper (Hutto & Gilbert, ICWSM 2014) — VADER outperformed 11 baselines incl.
  human raters on tweet sentiment (F1 0.96 for 3-class tweet classification is the commonly reported
  headline) and generalised across movie reviews / NYT editorials / Amazon reviews corpora shipped in
  the repo as ground-truth sets (4,200 tweets, 5,190 NYT snippets, 10,605 movie snippets, Amazon
  snippets, each with ≥20-rater means) [README]. These are *sentiment* numbers, not emotion numbers.
- **Cost: essentially zero.** No model, no embeddings, no network; O(N) after George Berry's refactor;
  ~ms per utterance on any CPU; ~1 MB lexicon. Verified live in this read [CODE — executed]:
  `"I hate this, it is broken again" → compound −0.778`; `"great work, love it!!!" → +0.880`;
  `"I am so frustrated today" → −0.656`.
- **Honest limits for JARVIS:** (a) English lexicon only — romanised Hinglish scores as neutral
  (verified: `"theek hai, chal raha hai" → compound 0.0, neu 1.0`); Devanagari likewise absent.
  (b) Valence ≠ mood: it cannot distinguish angry vs sad vs anxious — all are just "negative".
  (c) Tuned for social-media text; terse spoken commands ("delete it", "not that one") can false-fire
  on negators. [CODE][INFERENCE]

### 5. Steal verdict for JARVIS v2
**Steal it outright (MIT, vendored single file + lexicon) as `mood_gate` v0:** run VADER on every user
turn's transcript (µs, offline, RTX/CPU irrelevant), keep a rolling EMA of compound, and feed only
*deviations* (e.g. sustained compound < −0.4, or a sharp drop vs the user's baseline) into
`recall_gate.py`/response-style selection — frustration detection for "back off, be brief, don't ask
questions" mode. It is the only emotion signal in this slice that is free, deterministic, unit-testable,
and shippable today; treat it as a *frustration thermostat*, not an emotion recogniser, and budget a
small Hinglish booster-word extension to the lexicon later.

---

## Renovamen/Speech-Emotion-Recognition

**License: MIT** [README via web — GitHub repo metadata: "License: MIT License (MIT)"; a `LICENSE` file
exists in the root listing. *Method note: the local clone of this repo stalled repeatedly (git transport
hang, shared with several teams' clones); this section is read from the repo's GitHub page/README via
web fetch, tagged accordingly, not from local disk.*]

### 3. Emotion perception
A 2019-era teaching-grade SER repo (1,314★): Keras/TensorFlow 2 + sklearn, Python 3.8 [README via web].

- **Features — two interchangeable extractors** (`extract_feats/`): (a) librosa features saved as
  pickles; (b) **openSMILE standard sets** — IS09_emotion (384 feats), IS10_paraling (1,582),
  IS11_speaker_state (4,368), IS12_speaker_trait (6,125), IS13_ComParE / ComParE_2016 (6,373) —
  i.e. large prosodic/spectral statistical functionals, the pre-deep-learning state of the art. [README via web]
- **Models** (`models/`): CNN and LSTM (Keras DNNs over feature sequences), SVM and MLP (sklearn,
  joblib-persisted) over the flat feature sets. Checkpoints for pretrained models ship in `checkpoints/`. [README via web]
- **Taxonomy = union of its 4 datasets:** RAVDESS 8 {neutral, calm, happy, sad, angry, fearful, disgust,
  surprised}; SAVEE 7 (no calm); EMO-DB 7 {neutral, angry, fear, happy, sad, disgust, **boredom**};
  CASIA (Mandarin) 6. Folder-per-emotion data layout; label is encoded in dataset-specific filename
  positions. [README via web]
- **Accuracy claim:** README (Chinese) states the improved feature extraction raised recognition accuracy
  "to around 80%" — no per-dataset table, split protocol, or UA/WA breakdown in the README; treat as an
  unverified headline on acted corpora. [README via web]
- **Output:** `predict.py` → per-class probability array for one wav (visualised as a radar chart). [README via web]
- **Cost:** SVM/MLP on openSMILE features is CPU-feasible but requires the openSMILE binary + TF2-era
  dependency archaeology; the CNN/LSTM path wants TF2. Either way it is a train-it-yourself kit, not a
  drop-in mood sensor. [INFERENCE]

### 5. Steal verdict for JARVIS v2
Trivial for v2 — one line: a competent museum of pre-SSL SER (openSMILE functionals + SVM gets you
~80%-claimed on acted speech), superseded by frozen-SSL heads (EmoBox) and by the transcript channel
(Demfier's fusion lesson); steal nothing, cite it as the baseline any future v2 SER must beat.

---

## emo-box/EmoBox

**License: no LICENSE file exists in the clone** [CODE — repo root has none]; README carries a badge
claiming "License-MIT" [README]. Treat as *unverified MIT* — do not vendor code until upstream adds the file.

### 3. Emotion perception
EmoBox is **not a model — it is a benchmark + data toolkit** (arXiv 2406.07162): standardised
preprocessing/partitions for **32 SER corpora, 14 languages, 262,020 utterances, 294.4 h**, a
`torch` dataset class (`EmoBox/EmoDataset.py`) and an eval class (`EmoBox/EmoEval.py` →
`{wa (accuracy), ua (balanced accuracy), micro/macro F1, confusion}`), plus a SpeechBrain recipe
(`examples/sb/`) for fine-tuning frozen foundation models. [CODE][README]

- **Benchmarked front-ends (10 pretrained speech models):** wav2vec2-base/large, HuBERT-base/large,
  data2vec-base/large, wav2vec2.0, Whisper-family and emotion2vec-style models in the paper's tables —
  pattern in the shipped recipe: frozen SSL encoder → pooled features → small classifier head,
  16 kHz mono input. [CODE — `examples/sb/hparams/*_freeze.yaml`][README]
- **Taxonomy is per-dataset, not unified.** Canonical label maps shipped in `data/<corpus>/label_map.json`:
  IEMOCAP → {Neutral, Happy (exc merged in), Angry, Sad}; RAVDESS → {Neutral, Calm, Happy, Sad, Angry,
  Fear, Disgust, Surprise}; MELD → 7 (Ekman + neutral); MSP-Podcast → 8. Ekman-6 + neutral/surprise is
  the centre of gravity. [CODE]
- **Accuracy reality check (the paper's point):** intra-corpus UA/WA looks respectable for fine-tuned
  SSL models on acted corpora, but **cross-corpus performance collapses** (their Track-2 balanced test
  sets exist precisely to expose this) — a model trained on acted IEMOCAP does not transfer to a new
  speaker/room/language at anywhere near its headline number. Exact tables live on the project site,
  not in the repo. [README]
- **Cost:** EmoBox itself ships no deployable weights; any model it benchmarks is a 95M–300M+ param
  SSL encoder — CPU inference per utterance is feasible (seconds) but it is a *training/eval* purchase,
  not a runtime one. [INFERENCE]

### 5. Steal verdict for JARVIS v2
Steal the *evaluation discipline*, not code: if v2 ever adds voice SER, adopt EmoBox's protocol —
report UA + WA, test cross-corpus (train IEMOCAP → test RAVDESS/MELD), and distrust any single-corpus
headline. For now it is a map of why SER is a Phase-3 problem: acted-data accuracy does not survive
contact with one real owner's voice in one real room.

---

## kristofferv98/SemanthaVoiceAssistant

**License: MIT** [CODE — LICENSE is the standard MIT text, "Copyright (c) [2024] [Kristoffer Vatnehol]"].

### 3. Emotion "perception" — it isn't; it's sentiment *routing*
There is no SER, no VADER, no classifier. `Router_logic/Sentiment_router.py` uses
**semantic-router** (aurelio-labs) with an OpenAI `text-embedding-3-large` encoder (3072-d,
`score_threshold=0.51`): the user utterance is embedded and matched against hand-written example
utterances for 5 routes; the winning route injects a fixed system-note into the LLM prompt [CODE]:

| Route | Trigger examples (paraphrased from code) | Injected behaviour |
|---|---|---|
| `positive_affection_route` | "You always know how to make me smile", "Talking to you feels like coming home" | persona note: curious, warm, Ava-like yearning tone |
| `angry_response_route` | "You freaking idiot", "You're useless", "I'm fed up with this crap" (26 examples) | `CORECTIVE_PROMPT` [sic]: be light-hearted/playful, "a little offended", witty, don't belittle, *figure out why they are frustrated* |
| `problem_solving` | "I'm having trouble with {problem} in {topic}" | empathy + step-by-step actionable advice |
| `contacts`, `semantic_project_route` | contact lookups / "explain the Semantha program" | canned info / README dump |

- **Taxonomy:** effectively 2 emotion classes (affection-positive, angry) + intent routes. No scores,
  no probabilities surfaced, no persistence — the detected "sentiment" lives for exactly one turn and
  changes only the *tone instructions*, never memory or state. [CODE]
- **Cost/accuracy:** one OpenAI embedding API call per turn (network + paid, no local option wired);
  no evaluation, no accuracy claims anywhere in the repo. Quality = quality of ~45 hand-written example
  utterances; two routes contain a Python bug — adjacent string literals concatenate
  (`"I quite like you. great advise" "You always know…"` becomes one utterance), silently halving the
  example set. [CODE]
- Everything else is plumbing: AutoGen web-surfer + Perplexity research router, VoiceProcessingToolkit
  (Picovoice wake word, ElevenLabs TTS), profile switching via routes. No memory system beyond
  conversation context. [README][CODE]

### 5. Steal verdict for JARVIS v2
Steal the *pattern*, one level down in cost: **route-on-affect → tone-policy injection** is exactly
right for a companion (angry user ⇒ different JARVIS: shorter, playful-deflecting, zero clarifying
questions; affectionate user ⇒ warmer register) — but implement the detector with VADER (free, local,
deterministic) instead of a paid embedding call, and make the route *sticky for the session* rather
than per-turn. Semantha itself: trivial beyond that pattern. One line.

---

## Demfier/multimodal-speech-emotion-recognition

**License: MIT** [CODE — LICENSE: "MIT License, Copyright (c) 2020 Gaurav"].

### 3. Emotion perception in code
Course-project research code (Waterloo CS 698; arXiv 1904.06022), IEMOCAP only, Jupyter-notebook
pipeline (`src/`, `lstm_classifier/{s2e,t2e,combined}`). The interesting part is how *small* the audio
model is [CODE]:

- **Audio features — 8 hand-crafted scalars per utterance** (`src/extract_audio_features.py`):
  `sig_mean, sig_std, rmse_mean, rmse_std, silence_ratio` (fraction of frames with RMSE ≤ 0.4·mean),
  `harmonic_mean` (HPSS harmonic component), `auto_corr_max, auto_corr_std` (autocorrelation of a
  centre-clipped signal — a pitch proxy). Extracted with librosa from raw waveforms. [CODE]
- **Labels:** IEMOCAP categorical `emotion_dict = {ang 0, hap 1, exc 2, sad 3, fru 4, fea 5, sur 6,
  neu 7, xxx/oth 8}` + dimensional valence/activation/dominance annotations carried through the CSV. [CODE]
- **Models:** sklearn Logistic Regression / SVM / Random Forest / XGBoost / Multinomial NB, plus MLP
  and an LSTM over feature sequences; ensembles E1 = RF+XGB+MLP, E2 = +MNB+LR. Text side uses the
  transcript; combined concatenates both. [CODE][README]
- **Accuracy (IEMOCAP, [README] tables):** audio-only best **56.6% acc / 55.7 F1** (E1 ensemble;
  RF alone 56.0); text-only **64.9 / 66.0** (E2); **audio+text 70.1 / 71.8** (E2), 4-class combined
  ensemble 70.3 vs the paper's cited MDRE baseline 75.3. Headline lesson: *transcript text beat raw
  audio by ~8 points, and fusion beat either alone by ~5.* [README]
- **Cost:** the audio pipeline is CPU-trivial (8 statistics + a random forest) — but the pinned stack
  is archaeological (`torch==1.0.1, scikit-learn==0.20.3, librosa==0.7.0, xgboost==0.82`, Python-2-era
  pandas idioms like `df.append`), no trained weights are shipped in a loadable modern format, and
  56% 9-way accuracy on acted dyadic speech is a coin-flip-plus for real mood sensing. [CODE]

### 5. Steal verdict for JARVIS v2
Steal the *fusion lesson* and the *feature list*, not the code: if v2 adds prosody sensing, 3 of these
8 features (silence ratio, RMSE mean/std = speaking energy, signal std) are computable from the VAD
stream JARVIS already runs, for free, and combined with transcript+VADER they will beat any audio-only
toy model. As a standalone SER: trivial/outdated — do not adopt.

---

## elevenyellow/handcrafted-persona-engine *(optional repo — short section)*

**License: could not verify exactly** [README via web — root listing fetched from GitHub shows **no
LICENSE file**; a license badge exists in the README but its text was not readable in the fetched page.
Treat as unlicensed for code reuse until checked. *Method note: local clone stalled; read via web.*]

Live2D **avatar embodiment engine** (.NET, Windows x64, NVIDIA CUDA *required* — ASR/TTS/RVC via ONNX
Runtime; CPU explicitly unsupported): Silero VAD → dual Whisper (fast model for barge-in, large for final
transcript) → LLM (any OpenAI-compatible endpoint) driven by a hand-written `personality.txt` → Kokoro
or Qwen3 TTS → optional RVC voice clone → VBridger/Audio2Face lip-sync + Live2D overlay/OBS Spout. [README via web]
**Emotion here is expression, not perception:** the LLM may tag its own streamed reply with inline
markers like `[EMOTION:😊]`, which trigger the avatar's Live2D expressions/motions — the agent *declares*
its emotion in-band; nothing senses the user's emotion, and there is no memory or relationship system
beyond conversation history + the static personality file. [README via web]

**Steal verdict:** one mechanism only — the in-band `[EMOTION:…]` tag protocol is a clean, zero-cost way
for v2's brain to drive HUD expression/TTS prosody from the same token stream it already generates
(strip tags before TTS, map to HUD state); everything else is VTuber plumbing JARVIS doesn't need.

---

## rlin27/MOSAIC *(optional repo — short section)*

**License: MIT** [README via web — license badge in README header reads "License-MIT". *Method note:
local clone stalled; read via web.*]

Privacy-first **local journaling companion** (17★, personal project): Telegram bot + web UI capture
fragmented daily text inputs → SQLite store + ChromaDB RAG (`core/database.py`, `core/rag.py`) → Ollama
local LLM (default Qwen2.5:7B + `shaw/dmeta-embedding-zh`; "tested on a mid-range CPU laptop") generates
diary entries, idea/TODO lists, and **mood insights**; a background `core/processor.py` analyses pending
entries, and specialised agents (Main/Diary/Ideas/Mood/Chat in `core/agents/`, prompts in
`prompts/analyze_prompt.py`) are routed by a two-stage skill system (`skills/*/SKILL.md` description →
intent route → Python script executes with SKILL.md as the LLM prompt — a reliability pattern for 7B
models). [README via web]
**Emotion model:** no classifier and no per-turn sensing — "mood" is an *LLM-written periodic reflection*
over the user's own self-reported fragments, stored as markdown, browsable as a calendar + day-level
mood detail + trend-over-window view. No relationship/bond model (single-user diary). [README via web]

**Steal verdict:** steal the *aggregation cadence*, not the app: a periodic (nightly/weekly) LLM "mood &
themes" reflection distilled from v2's episodic log and stored back as a semantic fact is the natural
complement to VADER's per-turn signal — VADER says *this turn feels frustrated*, a MOSAIC-style
reflection says *this month has been trending frustrated since the PC crashes* — and v2's existing
`consolidate()` is exactly where that reflection job belongs.
