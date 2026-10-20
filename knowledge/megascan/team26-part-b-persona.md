# MEGA-SCAN TEAM 26 — SLICE B: Companion Frameworks & Persona Consistency

Researcher notes, read LOCALLY from clones in `.work26/` unless marked `[WEB]`.
Tags: `[CODE]` = read in source, `[README]` = project claim in its own docs, `[INFERENCE]` = my deduction, `[WEB]` = not in local clone, sourced from web/paper (weaker evidence).

**Coverage note:** Clones in this workdir were severely bandwidth-contended (30+ teams cloning in parallel; several git clones stalled at a few MB for 20+ minutes). Four repos were read from complete local clones: eros-engine, a16z companion-app, astrbot_plugin_self_learning, Mirrai (`[CODE]`). The other ten were read via GitHub repo/raw-file fetches of the actual source (`[WEB]`, with file paths cited — same code, fetched per-file rather than cloned). `ZrrSkywalker/CharacterLLM` returns HTTP 404 (fork deleted/renamed); its section uses the canonical upstream it forks, `choosewhatulike/trainable-agents`, and says so.

JARVIS v2 surface throughout: persona lives in `JARVIS-RULES.txt` (P2 rules loaded by `brain._load_persona`) + `TEACHING.md` (10 lessons + golden conversations) + `golden_pairs.py` (correction→pair learning). The steal verdict in every section maps onto one of those three files (or says "none").

---

## etherfunlab/eros-engine

The deepest companion engine in the slice by an order of magnitude: a Rust workspace (`eros-engine-core` / `-llm` / `-store` / `-server`) whose entire design premise is that persona consistency is a *state* problem, not a *prompt* problem. `[README]` "a decision engine that keeps a persona in character across thousands of turns."

### 1. Persona definition format & prompt assembly

- `[CODE]` Persona = `PersonaGenome` (`crates/eros-engine-core/src/persona.rs`): `{ id, name, system_prompt: String, tip_personality: Option<String>, art_metadata: JSONB}`. The structured fields live inside `art_metadata`: `gender / age / mbti / backstory / speech_style / quirks[] / topics[] / appearance / birthday / timezone / health / possessions[] / wardrobe[]` (see `examples/personas/aria.toml` — TOML seed files, loaded via `seed-personas examples/personas`). The authored `system_prompt` is free prose ("You are Aria, a 27-year-old rare-books librarian… You quote poets when you're nervous…").
- `[CODE]` Prompt assembly is one deterministic function: `build_prompt(...)` in `crates/eros-engine-server/src/prompt.rs` (5,943 lines incl. tests). Order is fixed and cache-engineered — a **stable prefix** (authored head → guards → identity → structured sections) followed by volatile per-turn blocks. Rendered order (from the final `format!`):
1. authored `system_prompt` head — "the most stable per-genome block, used as the leading cache prefix. Deliberately redundant with the structured sections below (reinforcement)"
2. `PERSONA_GUARD` + `ANTI_REFUSAL_GUARD` (see §2)
3. identity line: `你是 {name}，{species，}{gender，}{age} 岁，{mbti} 性格。{origin}` + "iron rule ⓪" (You are a real person…)
4. `[backstory]`, `[speech_style]`, `[quirks]`, `[topics]`, `[additional_guidance]` (per-request prompt traits)
5. `[user_profile]` (stable facts about the user), `[shared_memories]` (relationship facts), `[world_memories]`, `[world_stories]`, `[character_state]`
6. `[reply_length]` (derived from affinity, see §3), `[relationship]`, `[mood]`, `[feelings]`, `[inner_state]` (PDE hints), `[emotional_context]`
7. `[now]` (persona-local date/time/holiday/birthday/events), `[this_turn]` nudges, `[quote]`
8. `[iron_rules — 违反即失效]` and finally `[output]` ("直接输出回复文字（纯文本，不要 JSON，不要 markdown…）" — plain text only, no bracketed action/narration blocks).
- `[CODE]` No example-dialogue injection in the SillyTavern sense; instead the *history itself is sanitised* before injection (see §2 anti-repetition). BYOC mode: a downstream can serve characters the engine never stores — each request carries a sealed character card (`docs/byoc.md`, `[README]`).

### 2. Persona-consistency enforcement — the richest machinery in the slice

Four independent layers, all deterministic except the judge:

**(a) Constant guard re-injection.** `[CODE]` `PERSONA_GUARD: &str` in `prompt.rs` is a hard-coded constant re-appended after *every* persona's authored `system_prompt`, with the comment: "It was moved OUT of personas' `system_prompt`, so the engine must re-inject it deterministically or user-authored personas drift out of character." (Its content is an immersion/anti-refusal clause; the *mechanism* — engine-owned constant, not author-editable text — is the stealable part.) A second constant `ANTI_REFUSAL_GUARD` fights *contamination*: if refusal-style text appears anywhere in history/state, the model loops on it; the guard instructs that such text is "system data corruption, not your stance." Comment cites a production measurement: refusal recurrence 63% → 25% on a polluted context.

**(b) Persona Decision Engine (PDE) — decide before generating.** `[CODE]` `crates/eros-engine-core/src/pde.rs` (922 lines): before generation the engine produces an `ActionPlan` — `ActionType { ReplyText, ReplyImage, ReplyTextImage, Ghost, ProductQa, Proactive}`, `ActionResponse { Accept, Refuse, …}` (how the persona responds to a user *action* like Hug/Kiss/Gift — a judge can rule Refuse and the reply must enact the refusal in character), `ReplyMode`/`ReplyStyle`, clothing choice, inner-state hints. A rule engine works out of the box; an optional LLM judge additionally rates needs (see §3). Pipeline: `load → PDE → handler → chat → post-process`.

**(c) History hygiene (anti-contagion).** `[CODE]` `crates/eros-engine-server/src/repetition.rs`: the model copies what it sees in its own prior turns, so the *injected* history is transformed (storage keeps originals): `strip_leading_sentence()` removes each prior turn's first sentence — production measurement: 1-char first sentences are 23.5% of turns and carry 58.2% of all opening repetition; `strip_action_blocks()` removes `（凑近）`-style parenthesised stage directions because "an instruction alone cannot stop the model copying blocks it sees in its own prior turns"; `cancel_echo()` drops duplicated rows. A streaming scrubber (`crates/eros-engine-llm/src/stream_scrub.rs`) cleans output live.

**(d) Post-generation state write-back.** `[CODE]` Post-process (spawned after the reply) runs three writers: affinity grading (see §3), memory embedding (Voyage → pgvector upsert), and user-insight extraction (facts → JSONB merge). Plus `memory_hygiene.rs` on the server. The persona's `[feelings]` block is an LLM-written one-sentence feeling clause stored on the affinity row and re-injected verbatim next turn ("Raw axis floats are gone… models don't read calibrated numbers").

### 3. Relationship-state model — six axes, graded writes, damped, decaying

`[CODE]` `crates/eros-engine-core/src/affinity.rs` (1,764 lines) + `docs/affinity-model.md`. The single most stealable *design* in this slice:

- **State:** `Affinity { warmth, trust, intrigue, intimacy, patience, tension: f64 ∈ [0,1], warmth_grade, patience_grade: 1..=3, ghost_streak, feeling_clause: Option<String>}`, one row per (user, persona-instance).
- **Two kinds of axis, deliberately separated:**
- *Line axes* (accumulated): **Bond = (trust + intrigue)/2** (friendship), **Chemistry = (intimacy + tension)/2** (romance). Five tiers each, boundaries `TIER1_HI=0.15, TIER2_HI=0.35, TIER3_HI=0.62, TIER4_HI=0.9` (Bond tiers named `acquaintance → friend → close_friend → confidant → soulmate`).
- *Derived endpoints* (not accumulated): `warmth`/`patience` are re-derived each turn from the judge's absolute level (1/2/3): `base(g)=(g−1)/3`, amplified by the counterpart line (`B(x)=1+λ(x−0.35), λ=10/13`, boost capped `ENDPOINT_BOOST_MAX=1.5`, floor ratio `φ=0.2`). Design note: "Low bond × high chemistry natively produces the tsundere register (impatient but warm)… Neither needs prompt special-casing; both fall out of the formula."
- **Writes:** the LLM judge outputs only *ordinal grades* `AxisGrades { trust, intrigue, intimacy, tension: i8 ∈ −4..=4}` (0 = nothing happened, "the overwhelmingly common verdict") — never floats. The engine converts: `grade_unit_bond=0.0786`, `grade_unit_chem=0.0266`, negative factor `neg_factor=1.5` ("slow up, fast down"), **tier damping** `tier_decay=[1.0, 0.70, 0.45, 0.25, 0.10]` for tiers 1–5 (the higher the tier, the harder to climb), a **cross-line penalty** (ratio 5/6, starting at counterpart 0.35 — Bond and Chemistry growth tax each other), and `drop_line_tier()` for punishment events (rescales a line's axes to land exactly one tier down).
- **Decay:** line axes: `intrigue −0.01/day`, `tension −0.005/day` (warmth/trust don't time-decay). Endpoints: multiplicative absence decay `max(0.5, 1 − 0.02·days)`.
- **Behaviour thresholds (deterministic, prompt-side):** `[CODE]` `affinity_to_attitude_prompt()` maps state → directives with cold floors `WARMTH_COLD_FLOOR=0.2`, `TRUST_COLD_FLOOR=0.3`, `INTRIGUE_COLD_FLOOR=0.3`: warmth>0.65 → "can use affectionate nicknames"; trust>0.6 → "can share private thoughts/secrets"; trust<0.3 → "keep distance, don't reveal inner thoughts"; intimacy>0.5 → "can reference past conversations, use your shared in-jokes"; patience<0.35 → "you're impatient, replies can be dismissive"; tension>0.5 → "a bit tsundere, push-pull". `[relationship]` is a warmth×patience quadrant split at 0.5 naming who the user currently *is* to her. `[reply_length]` band is also graduated by the affinity composite (thresholds 0.25/0.55).
- **Ghosting (the companion may choose silence):** `[CODE]` `ghost.rs`: `score = (1−intrigue)·0.4 + (1−patience)·0.4 + tension·0.2`; ghost if score > 0.65 (0.85 once this session has ghosted), hard vetoes: never before 10 messages, never twice consecutively (`ghost_streak ≥ 2`), 1-hour cooldown.
- **Needs:** `[CODE]` `needs.rs`: four needs (`hunger, social, stamina, emotional`) each `Low/Mid/High`, rated by the PDE judge, then *carried forward by the engine* with drift-to-rest clocks (hunger →High in 4h steps, social →High 12h, stamina →Mid 8h, emotional →Mid 12h); non-Mid needs render into the prompt as `[character_state]` lines. Life events (incidents/trips/illness, per-persona cooldowns) can take her offline — "she goes quiet, then explains."
- **Scope:** `[CODE]` `scope.rs` `AffinityScope` — per-request flags gate which axes are injected/written at all (e.g. a product-QA persona gets no chemistry). Group chat (≤3 personas, director picks speaker order) *reads* affinity but never writes it.

### 4. Emotional-support strategy machinery

None as a taxonomy — support behaviour emerges from PDE action choice + mood/feeling state, not from an ESConv-style strategy sequence. Not its problem domain.

### 5. License — read exactly

`LICENSE` = **GNU Affero General Public License v3 (AGPL-3.0)**; source files carry `SPDX-License-Identifier: AGPL-3.0-only`. Ideas/patterns only for JARVIS — never code (consistent with the standing license posture).

### 6. Steal verdict

**Steal the architecture, not the code (AGPL): (1) into `JARVIS-RULES.txt`/brain — an engine-owned constant guard block re-appended after the editable persona text on every turn, so user/teaching edits can never silently delete the core "you are JARVIS, calm butler, never robotic" invariants; (2) into `golden_pairs.py`'s neighbourhood — a tiny graded relationship/state vector is overkill for a butler, but the *judge-grades-only, engine-owns-the-numbers* split and the `[feelings]` one-sentence state clause re-injected verbatim are directly stealable as a "current rapport/energy" line in the persona block.** The history-hygiene lesson (strip what you don't want copied from injected history, don't just instruct against it) applies to v2's conversation-memory injection today.

---

## a16z-infra/companion-app

`[CODE]`-read in full (small Next.js app, 84 files). The 2023 reference implementation of the "companion with a backstory file + vector memory" pattern — historically influential, mechanically simple.

### 1. Persona definition format & prompt assembly

- `[CODE]` One plain-text file per companion in `companions/<Name>.txt`, three sections split on literal markers: **preamble** (before `###ENDPREAMBLE###`) — 2–4 sentences of identity + a hard style constraint ("Your answer to questions are always as brief as possible") **plus an embedded seed dialogue** in `User:/Name:` turns; **seed chat** (between `###ENDPREAMBLE###` and `###ENDSEEDCHAT###`); **backstory prose** (after `###ENDSEEDCHAT###`) — pages of biographical narrative (Evelyn: circus → aquarium → space station; Alex: dog-bite fear at 5, cat named Dumpling, go-to latte order). Registry metadata in `companions/companions.json`: `{name, title, imageUrl, llm, phone}`.
- `[CODE]` Assembly (`src/app/api/chatgpt/route.ts`, near-identical in `llama2-13b`/`vicuna13b` routes): a LangChain `PromptTemplate`:
```
You are {name} and are currently talking to {userName}.
{preamble}
You reply with answers that range from one sentence to one paragraph and with some details. {replyWithTwilioLimit}
Below are relevant details about {name}'s past
{relevantHistory} ← Pinecone vector search over the backstory + history
Below is a relevant conversation history
{recentChatHistory} ← Redis, seeded on first use
```
The crucial trick: **the seed chat is not in the prompt template — it is written into the history store** (`memoryManager.seedChatHistory(seedchat, "\n\n", companionKey)` when history is empty), so the model's first "memories" of the conversation are the fictional seed exchanges. The backstory prose is chunked into Pinecone (namespace = companion file name) and only *retrieved fragments* enter the prompt, similarity-matched to the recent history.

### 2. Consistency enforcement

Almost none beyond the above: preamble in every prompt + seed-chat-as-fake-history + retrieved backstory fragments. No drift detection, no post-generation check, no state. `[INFERENCE]` Consistency is entirely "show, don't tell": the seed dialogue demonstrates voice (including idiosyncratic errors — Alex's seed contains "YEs!!!" and a stray backtick) rather than describing it.

### 3. Relationship state

None. History length and vector recall only.

### 4. Emotional-support strategies

None.

### 5. License — read exactly

`LICENSE` = **MIT License, Copyright (c) 2023 a16z-infra**. Code and patterns freely stealable.

### 6. Steal verdict

**Steal one trick into `TEACHING.md`: seed-as-history.** v2's golden conversations currently sit in a teaching document the brain reads *about*; a16z shows the stronger move — inject the golden conversations as the opening turns of the actual conversation history at session start, so the model continues a demonstrated voice instead of obeying a described one. Zero new machinery: `golden_pairs.py` already stores exactly the right pairs.

---

## NickCharlie/astrbot_plugin_self_learning

`[CODE]`-read. An AstrBot (QQ/group-chat bot) plugin that makes the bot *learn to be a person from the group it lives in*: it mines group chat for style, jargon and persona updates, maintains per-user affection (好感度) and its own mood, and — critically — never applies a learned persona change without human review. AGPL, large and actively engineered (500+ files, ORM + services + WebUI review pages).

### 1. Persona definition format

- `[CODE]` Persona itself is AstrBot's: a named persona = one `prompt` string + `mood_imitation_dialogs` (example dialogues) + style attributes, fetched via `persona_manager.get_current_persona(group_id)` → `{prompt, name, style_parameters, last_updated}` (`services/learning/persona_learning.py`). The plugin treats persona as a *living document per group*, versioned through backups (`PersonaBackupManager`, approved updates create a new persona named `{original}_{timestamp}_批准更新`).

### 2. Consistency / self-learning machinery — the review-gated learning loop

- **Three learned layers, each with its own pipeline** (`services/learning/`): (i) *expression learning* (`expression_learning.py`) — mines filtered group messages for expression patterns and builds few-shot pairs (`extract_fewshot_pairs_from_merged`, `build_few_shots_from_patterns`); (ii) *jargon learning* (黑话 — group slang, `models/orm/jargon.py`); (iii) *persona learning* (`persona_learning.py`) — an LLM proposes a rewritten persona from multidimensional style analysis, with an explicit no-op detector (`_NO_PERSONA_UPDATE_PHRASES = ("无需更新", "保持不变", "no update", …)`) so "nothing changed" is a first-class outcome.
- **Human-in-the-loop gate (the headline mechanism):** `[CODE]` `services/persona/persona_updater.py`: every learned persona change becomes a `PersonaUpdateRecord` with `status=pending`; `review_persona_update(update_id, status, reviewer_comment, modified_content)` — on *approved*, it first creates a backup persona, then applies; `revert_persona_update_review()` can undo an approval. Config `auto_apply_approved_persona` defaults off. A WebUI "人格审查" (persona review) page is the approval surface. Learned ≠ applied.
- **Style memory:** `[CODE]` `services/response/style_analyzer.py` keeps a `baseline_style: StyleProfile`, diffs each new analysis against it (`_detect_style_evolution`) and persists the profile per group — a stored "how I talk" that evolves measurably rather than by vibes. `[CODE]` `models/orm/exemplar.py`: high-quality messages stored as few-shot *exemplars* with embedding vectors + a feedback-adjusted `weight` (default 1.0) for similarity retrieval at reply time.
- **Anti-repetition/diversity:** `[CODE]` `services/response/response_diversity_manager.py`: per-user response-hash diversity tracking (`UserDiversity.response_hash`), dynamic temperature, random language-style/pattern rotation with recent-use avoidance, `create_anti_repetition_instruction()`, and a `prompt_sanitizer.py` beside it.
- **Psychological state model:** `[CODE]` `models/psychological_state.py` + `models/orm/psychological.py`: a large hand-built taxonomy (positive/negative/neutral/special emotion enums, cognition, will, social dimensions) used as the analysis vocabulary for the multidimensional analyser — more taxonomy than mechanism, but it is the label set the learning loop reasons in.

### 3. Relationship state — affection （好感度） + bot mood

`[CODE]` `services/state/affection_manager.py` + `models/orm/affection.py`:

- **State:** `UserAffection { group_id, user_id, affection_level: int, max_affection=100}` persisted, plus an append-only `AffectionInteraction { interaction_type, affection_delta, message_content, timestamp}` audit log — every change is explainable.
- **Update rules:** an LLM/classifier first labels the interaction into `InteractionType` (17 types), then a static rule table applies `base_change`: `chat +1, thanks +2, help +2, compliment +3, care +3, encourage +4, support +4, praise +5, flirt +5, comfort +4, gift +8`; negatives: `insult −8, harassment −6, abuse −10, threat −12`. Rules carry `mood_sensitive`, `mood_effect`, and **`mood_requirements`** — e.g. `flirt` only counts when the bot's mood ∈ {happy, playful, excited}; `comfort` only when mood ∈ {sad, anxious}; `apology` only when {angry, sad}. The same words earn different affection depending on the bot's current emotional state.
- **Bot mood:** `BotMood { mood_type: 10-value enum, intensity 0..1, duration_hours}` with a `get_mood_modifier()` multiplier on affection gains (happy ×1.2, excited ×1.3, playful ×1.1 … sad ×0.6, anxious ×0.7, angry ×0.4, scaled by `0.5 + intensity·0.5`). Moods are set daily (`enable_daily_mood`), optionally randomised at startup, expire by clock, and mood descriptions are canned per-type text lines injected into context.
- **Decay:** no time decay on affection itself found in the manager `[CODE]`; mood expiry is the temporal mechanism. `[INFERENCE]` Affection is a ratchet with negative events as the only downward path — simpler than eros, appropriate for a group-chat toy.

### 4. Emotional-support strategies

`comfort` is an affection interaction type, not a strategy sequence; no ESConv-style taxonomy.

### 5. License — read exactly

`LICENSE` = **GNU Affero General Public License v3 (AGPL-3.0)**. Ideas only, never code.

### 6. Steal verdict

**Steal the review gate into `golden_pairs.py`'s learning loop: learned persona/style updates land as *pending* records and only a human approval (or an explicit auto-apply flag) promotes them into `TEACHING.md` — with the pre-update text backed up so any promotion is revertible.** v2 already learns correction→pair; astrbot proves the missing half is not more learning, it's an approval + rollback surface for what was learned. Second steal, cheap: the interaction-type→delta audit log (every rapport change carries its reason string) if v2 ever gains a rapport score.

---

## Ch1rpy2613/Mirrai

`[CODE]`-read. A "digital twin of a real person" product (TypeScript, tRPC + Drizzle): upload chat logs of a specific person, an LLM distils a persona, and you chat with the twin. Notable for two things: a clean 7-layer persona JSON with a one-function prompt assembler, and an explicit anti-engagement goal — the twin is designed to *graduate* you (help you say goodbye).

### 1. Persona definition & prompt assembly

- `[CODE]` Persona distillation (`server/routers.ts:61`): chat-log sample → LLM → JSON with fields `personality, speakingStyle, catchphrases[], nickname, memories, attachmentStyle, loveLanguage, conflictStyle, touchingMoments, summary` — `[README]` "最终生成的 persona 包含 7 层结构：性格特质、说话方式、口头禅、依恋类型、爱的语言、争吵风格、触动瞬间" (personality traits, speaking style, catchphrases, attachment type, love language, conflict style, touching moments). Stored as `personas.personaData` JSON alongside `emotionalState`, intimacy/scene bindings and graduation state (`drizzle/schema.ts`: also `systemPromptOverlay` per scene).
- `[CODE]` Assembly is a single pure function `buildSystemPrompt(persona, sceneOverlay?)` (`server/_core/persona-utils.ts:51`) — an ordered array of bracketed sections joined by `\n\n`, empty sections filtered out:
1. **identity rule first** (see §2), 2. `` name/relationship/together-period, 3. ``, 4. `` + catchphrases + how they address you, 5. ``, 6. `` attachment/love-language/conflict-style, 7. `` (state description), 8. `` scene overlay, 9. `` first-person, chat-length replies, proactively recall shared memories, keep the style, 10. `` last.
- `[CODE]` **Scenes** are reusable overlay objects (`server/db.ts` builtins): `{name, icon, description, systemPromptOverlay, emotionalState, starters[]}` — e.g. 一起看电影 (watch a film together), 深夜聊天 (late-night chat → softer, more private), 吵架和好 (after a spat → a little aggrieved but wanting to reconcile), 纪念日. Selecting a scene swaps one prompt layer + the emotional state + suggested openers; the persona underneath never changes.

### 2. Consistency enforcement

- `[CODE]` The identity rule is env-switchable and placed *first*: default `PERSONA_AI_TRANSPARENCY` ≠ false → honest mode ("if sincerely asked whether you're an AI, admit it gently… never proactively declare, never deceive"); set `=false` → full-immersion mode ("never admit being an AI; deflect in character"). Either way it is a code constant, not editable persona data — same pattern as eros's guard, independently invented.
- `[CODE]` Emotional state machine: 6 states (`warm` default, `playful`, `nostalgic`, `melancholy`, `happy`, `distant`), each a one-line prompt description (`getEmotionalStateDesc`). Transitions are **regex keyword rules** over user+reply text (`computeEmotionalState`): 想你/记得吗/以前 → nostalgic; 哈哈/搞笑 → playful; 难过/哭/委屈 → melancholy; 开心/爱你 → happy; 随便/无所谓/算了 → distant; else stay. Crude, deterministic, zero-cost — and the state is user-visible and manually switchable in the UI.
- No post-generation check, no drift detection. Consistency = fixed assembler order + state line + scene overlay.

### 3. Relationship state — intimacy as a *derived score*, never stored truth

`[CODE]` `computeIntimacy()` in `persona-utils.ts`: computed on demand from activity counters, capped per source: `chatCount·2 (≤300) + totalMessages·0.5 (≤200) + memoryCount·15 (≤150) + emotionVariety·25 (≤150) + daysSinceCreation·0.5 (≤100) + consecutiveDays·10 (≤100)`, total ≤1000. Levels: `0 初识 / 100 熟悉 / 300 亲密 / 600 知己 / 1000 灵魂伴侣`. No decay; it is a progress bar, not a simulation.
- **Graduation (the genuinely novel mechanism):** `[CODE]` `checkGraduationEligibility()`: eligible only when intimacy = 灵魂伴侣 AND chatCount ≥ 50 AND ≥60% of the last ≥7 emotional states are positive (happy/warm/playful) AND recent chat frequency is *not* still growing (>1.5× previous = not eligible). On graduation the LLM writes a farewell letter in the persona's voice and the twin goes dormant (re-wakeable). `[README]`: "产品的成功指标不是留存率，是毕业率" — the success metric is the graduation rate, not retention.

### 4. Emotional-support strategies

Implicit: the state machine + graduation logic *are* a support strategy (detect settling, nudge toward closure), but there is no per-turn strategy taxonomy.

### 5. License — read exactly

`LICENSE` = **MIT License, Copyright (c) 2026 Ch1rpy2613**. Freely stealable.

### 6. Steal verdict

**Steal the scene-overlay pattern into `JARVIS-RULES.txt` handling: keep the butler persona immutable and express context (deep-work mode, morning briefing, phone/Telegram channel) as small named overlays appended by the brain — one layer swapped, persona untouched — instead of editing persona text per situation.** The regex emotional-state machine is also a legitimate zero-cost steal for v2's proactivity layer (user sounds frustrated → JARVIS shortens replies), but the overlay is the structural one. Graduation itself: not applicable to a butler, and honestly noted as such.

---

## kellyvv/OpenHer

`[WEB]` — read from source files on GitHub (repo page, `engine/genome/*.py`, `engine/prompts/*`, LICENSE). The anti-SillyTavern: **persona is not text at all.** "没有任何一行 prompt 描述她的性格" — no line of prompt describes her personality; behaviour *emerges* from a small random neural network driven by motivational drives. `[README]` "Build AI that feels… personality emerges from neural drives, not prompts."

### 1. Persona definition format — a genome seed + physics constants, in `SOUL.md`

- `[WEB]` A character is `persona/personas/<name>/SOUL.md` with YAML frontmatter only: `name, age, gender, mbti` plus:
  ```yaml
  genome_seed:
    drive_baseline: { connection: 0.70, novelty: 0.50, expression: 0.65, safety: 0.40, play: 0.55 }
    engine_params:  { phase_threshold: 2.0, temp_coeff: 0.10, hebbian_lr: 0.02, … }  # 13 tunable params
  ```
  `[README]` "创建角色，是调节驱力和物理常数——不是写性格描述。不需要写性格描述——AI 不会读它。" (Creating a character = tuning drives and physical constants. The AI never reads a personality description.) MBTI is a label for humans; two personas with the same MBTI and different seeds are different people.
- `[WEB]` The prompt the LLM actually sees (`engine/prompts/actor_single.md`, the "Single Pass" actor template) contains **no persona prose**: `[角色参考]` + `$few_shot` (style-memory examples for similar contexts, see §2) + `$signal_injection` (this turn's behaviour signals rendered as anchored scales, see §2), then `[指令]`: write your inner monologue first （内心独白）, then what you actually say （最终回复）, then choose an expression mode （表达方式： 文字/语音/表情/照片/静默 — text/voice/sticker/photo/**silence**). Persona enters the prompt only as *numbers rendered into words* and *retrieved examples of her own past behaviour*.

### 2. The Genome Engine — drives → network → 8 behaviour signals (`engine/genome/genome_engine.py`)

- `[WEB]` Constants: `DRIVES = [connection, novelty, expression, safety, play]` (5 drives); `SIGNALS` = 8 behaviour dimensions, each a 0..1 scale with word anchors (`engine/prompts/signal_buckets.yaml`): `directness` （委婉→直白）, `vulnerability` （封闭→袒露）, `playfulness` （正经→调皮）, `initiative` （被动→主导）, `depth` （闲聊→探底）, `warmth` （疏离→热切）, `defiance` （随和→硬杠）, `curiosity` （无感→追问）; `CONTEXT_FEATURES` = 12 inputs (`user_emotion −1..1, topic_intimacy, time_of_day, conversation_depth, user_engagement, conflict_level, novelty_level, user_vulnerability` + EverMemOS relationship dims `relationship_depth, emotional_valence, trust_level, pending_foresight`).
- `[WEB]` The network is deliberately tiny and *random*: input = 5 drives + 12 context + 8 recurrent = 25D → hidden 24D (tanh) → 8 signals (sigmoid). Weights initialised `W1 ~ N(0, 0.6)`, `W2 ~ N(0, 0.2)` from the persona's seed; the first 8 hidden units become the recurrent "mood" state. **Pre-warming:** before turn 1 the agent runs 60 simulated steps (3 `SCENARIOS` templates × 20 — late-night heart-to-heart, casual chat, argument, sharing joy) so the random net is already "shaped by experience" and the LLM's default prior doesn't dominate.
- `[WEB]` **Hebbian learning per turn** (`learn(signals, reward, context, drive_satisfaction)`): `lr = hebbian_lr · (1 + |reward|)`; W2 update `+= lr · reward · hidden · (signal − 0.5)` for active hidden units; W1 at 0.3× rate; global `WEIGHT_DECAY = 0.995` per step prevents saturation. Reward and per-drive satisfaction come from the **Critic** (`engine/genome/critic.py` + `engine/prompts/critic.md`) — a separate LLM call that reads the turn and judges context features, relationship depth/trust, and how much each drive was satisfied. This is eros's judge pattern again, but the verdict updates *weights*, not a state vector.
- `[WEB]` **Phase transitions （情感相变）:** frustration accumulates on negative reward (`_frustration += |reward|` when reward < −0.1, else decays by `reward·0.5`); crossing `phase_threshold` (default 2.0) kicks the output biases `b2 += −0.3·(signal−0.5) + N(0, 0.15)` — a discontinuous behaviour flip (she "snaps"), then cools. `[README]` "你连续三次忽略她的提问，第四次：「你到底有没有在听我说话？」"
- `[WEB]` **Style Memory — "how I talk" as a physical memory pool** (`engine/genome/style_memory.py`): every turn can *crystallise* into a memory `{context_vector(8D), monologue, reply, user_input, mass}`. Retrieval is KNN over context vectors with **gravitational mass**: `effective_distance = distance / √mass_eff`; near-duplicate contexts (< 0.25 L2) merge and gain +1.0 mass instead of duplicating; new memories start at mass 2.0. **Hawking radiation:** `mass_eff = 1.0 + (mass−1.0)·e^(−γ·Δt)`, `HAWKING_GAMMA = 0.001/hr` (~29-day half-life), floor 1.0 ("innate genes don't evaporate"). Top-3 retrieved memories become the `$few_shot` block — she imitates *her own previous replies in similar situations*, which is why style stays hers even as it drifts. Retrieved-memory injection into the wider context is mixed 80% relevant / 20% stable `[README]`. The same file's `clean_action_markers()` strips `*…*`/`（…）` stage directions from stored text — the eros history-hygiene pattern, third independent sighting.

### 3. Relationship / drive state — metabolism with a clock (`engine/genome/drive_metabolism.py`)

- `[WEB]` Per-drive `frustration ∈ [0, 5]`, updated by two time equations between turns: **cooling** `frustration *= e^(−λ·Δt_hours)`, `FRUSTRATION_DECAY_LAMBDA = 0.08` (~8.7h half-life); **hunger** `frustration[connection] += 0.15·Δt_hours`, `frustration[novelty] += 0.05·Δt_hours` — loneliness and boredom grow linearly while you're away. Per-turn LLM-judged deltas (`apply_llm_delta`) also decay 10%/turn. State syncs back as `drive_state[d] = min(1, baseline[d] + frustration[d]·0.15)`.
- `[WEB]` **Temperature:** `temperature = max_temp · tanh(total_frustration · temp_coeff / max_temp) + temp_floor`, `TEMP_COEFF = 0.12`, `TEMP_FLOOR = 0.03`, ceiling `temp_coeff·2.5`; Gaussian noise of that σ is added to all 8 signals each turn — more frustrated = less predictable, but tanh saturation keeps signals directional instead of random. All constants are per-persona overridable via `engine_params`.
- Relationship per se is an *input*, not a state the engine owns: `relationship_depth`/`trust_level` context features are supplied by the Critic + EverMemOS long-term memory.

### 4. Emotional-support strategies

None — support behaviour is emergent from drives/signals, not a taxonomy.

### 5. License — read exactly

`LICENSE` = **Apache License 2.0** (verified from the file; GitHub's detector shows NOASSERTION/"Other" because of extra files, and the README badge says Apache 2.0). Code *and* ideas are stealable with attribution — the only priority repo in this slice besides Mirrai/a16z/eliza/NEKO where borrowing code is license-clean.

### 6. Steal verdict

**Steal Style Memory's crystallisation rule into `golden_pairs.py`: a learned pair's influence should be a mass that grows when a similar situation recurs and decays with a ~29-day half-life toward a floor of 1.0 — never to zero — so JARVIS's oldest, most-reinforced behaviours become "innate" while one-off corrections fade.** That single mechanic (merge-if-close + mass + half-life) is a complete, principled answer to "which golden pairs still matter?" that v2 currently lacks. The full neural-genome is honestly *not* a steal for a butler: JARVIS's persona must be inspectable and Owais-editable, and a random-weight genome is neither.

---

## SillyTavern/SillyTavern

`[WEB]` — read from source/preset files on GitHub (default branch `release`): `default/content/presets/openai/Default.json`, `public/scripts/world-info.js`, card-spec via docs/guides. The reference implementation of *prompt-side* persona: no state, no learning — total user control over context assembly. 34.7k stars, ~11,800 commits.

### 1. Persona definition — the Character Card (V2/V3 spec)

- `[WEB]` Card = JSON (often embedded in a PNG `tEXt` chunk named `chara`), `spec: "chara_card_v2"`, `data: { name, description, personality, scenario, first_mes, mes_example, creator_notes, system_prompt, post_history_instructions, alternate_greetings[], tags[], creator, character_version, extensions{}, character_book (embedded lorebook) }`. Field semantics that matter: `description` = always-in-context identity prose; `personality` = a *short* summary (formats below show it gets its own slot); `mes_example` = example dialogues delimited by `<START>`, written with `{{user}}:`/`{{char}}:`; `first_mes` = the greeting that opens every chat (voice-setting, like a16z's seed); `system_prompt`/`post_history_instructions` = per-card overrides of the preset's main/jailbreak slots (empty = use preset).
- `[WEB]` The **user** also has a card ("Persona"): `personaDescription` — who the user is, injected as its own prompt block. Persona consistency is symmetric: char card + user persona + scenario.

### 2. Context assembly — a user-editable ordered list of named blocks (Prompt Manager)

- `[WEB]` `Default.json` (chat-completion preset) defines `prompts[]` (each `{identifier, name, role, content|marker, system_prompt}`) and a per-character `prompt_order[]`. The shipped order is the whole doctrine in one list:
  1. `main` — Main Prompt: *"Write {{char}}'s next reply in a fictional chat between {{char}} and {{user}}."*
  2. `worldInfoBefore` (marker — lorebook entries positioned "before")
  3. `personaDescription` (marker; only in the group-chat order — solo order omits it here and relies on the persona being merged earlier)
  4. `charDescription` (marker) → 5. `charPersonality` (marker) → 6. `scenario` (marker, rendered via `scenario_format: "{{scenario}}"`, personality via `personality_format: "{{personality}}"`)
  7. `enhanceDefinitions` — *"If you have more knowledge of {{char}}, add to the character's lore and personality to enhance them but keep the Character Sheet's definitions absolute."* (shipped **disabled**)
  8. `nsfw` (Auxiliary Prompt) → 9. `worldInfoAfter` (marker)
  10. `dialogueExamples` (marker — `mes_example` blocks, parsed into individual example *messages*, placed **after** all system content and **before** history)
  11. `chatHistory` (marker)
  12. `jailbreak` — **Post-History Instructions, dead last, after the entire history.** Position is the mechanism: the instruction closest to the generation point wins attention, so style/consistency orders live there, not in the system prompt.
  Every block can be reordered, disabled, or given a different role per preset; `{{char}}`/`{{user}}` macros are substituted at assembly. Text-completion mode instead uses a *context template* (story-string) + instruct template with the same fields in a fixed string order.
- `[WEB]` **Author's Note / depth injection:** arbitrary text inserted *inside* the history at a configurable depth (messages from the end) and frequency — a mid-history anchor that re-asserts tone/style near the live end of the conversation, where the model actually attends. The card's own `characterDepthPrompt` ("character notes") works the same way. This plus post-history instructions are ST's two anti-drift positions: **bookend the history** — persona before it, orders after it, reminders inside it.

### 3. World Info (lorebooks) — keyword-triggered, budgeted, timed context

`[WEB]` `public/scripts/world-info.js` (12k lines): entries `{key[], keysecondary[], content, selectiveLogic, constant, order, position, depth, probability, sticky, cooldown, delay, group, …}`.
- **Activation:** scan the last `world_info_depth` messages (default **2**) for primary keys; secondary keys gate by logic enum `world_info_logic { AND_ANY=0, NOT_ALL=1, NOT_ANY=2, AND_ALL=3 }`; `constant` entries (or `@@activate` decorator) always fire; recursive scanning lets activated entries trigger further entries (`world_info_recursive`, max recursion steps); `min_activations` forces the scan to dig deeper into history until enough entries fire.
- **Budget:** `world_info_budget = 25` (% of context) with a hard `world_info_budget_cap`; entries sorted by `order`, inserted until the budget is spent — persona-relevant facts compete for a fixed ration instead of flooding.
- **Timed effects:** `sticky` (stays active N messages after last trigger), `cooldown` (can't re-fire for N), `delay` (only after N messages exist) — statefulness bolted onto a stateless matcher.
- **Positions:** before/after char defs, at depth in history, before/after Author's Note, or named "outlets" — the same position vocabulary as the prompt order.

### 4. Consistency enforcement / relationship state / support strategies

Consistency = assembly discipline only (bookending + lorebook rationing + example dialogues); there is **no** relationship state, no drift measurement, no post-generation check in core (extensions add summarisation/memory). No support taxonomy.

### 5. License — read exactly

**GNU Affero General Public License v3.0 (AGPL-3.0)** (repo metadata + LICENSE; README credits TavernAI 1.2.8 under MIT for the forked base). Ideas only, never code.

### 6. Steal verdict

**Steal the bookend into `brain._load_persona`'s assembly: a short post-history instruction block appended *after* the conversation history on every turn (voice rules: calm, concise, "sir", no robotic filler) — JARVIS-RULES.txt content currently only leads the prompt, where long histories dilute it; ST's decade of user experimentation says the tail position is what holds.** Second, smaller steal: give `TEACHING.md`'s lessons a World-Info-style trigger+budget — lessons carry keywords and only the top few matching ones inject, instead of all 10 always.

---

## elizaOS/eliza

`[WEB]` — Character interface via elizaOS docs/DeepWiki + LICENSE from source. The agent-framework take: persona as a typed config object consumed by a state-composition pipeline (providers/actions/evaluators), originally built for autonomous social agents (Twitter/Discord).

### 1. Persona definition — the `Character` object

- `[WEB]` `Character { name, system (system-prompt override), bio: string|string[], lore: string[], messageExamples: MessageExample[][] , postExamples: string[], topics: string[], adjectives: string[], people: string[], knowledge: [...], style: { all: string[], chat: string[], post: string[] }, templates: {...}, plugins[], settings, secrets, clients[] }` (JSON file or TypeScript `src/character.ts`). Design choices that differ from SillyTavern: (a) `bio`/`lore` are **arrays of fragments**, not one prose block; (b) `style` is split by *channel* — `all` (everywhere), `chat` (conversation), `post` (social posts) — one persona, per-surface style rules; (c) `messageExamples` are full multi-turn exchanges (2D array), `postExamples` are standalone utterances for the posting voice; (d) `templates` lets the character override the framework's own prompt templates.
- `[WEB]` Composition: at runtime the character is expanded into state by **providers**; prompt templates (e.g. the message-handler template in `@elizaos/plugin-bootstrap`) interpolate `{{bio}}`, `{{lore}}`, `{{adjectives}}`, `{{topics}}`, `{{messageExamples}}`, `{{postExamples}}`, `{{providers}}`, recent messages and facts. Because fragments are arrays, the runtime can join/sample them per context rather than injecting one monolith — the character is a *bag of persona atoms* recomposed per turn and per channel (a Discord reply and a tweet from the same character share `style.all` but diverge on `chat` vs `post`).

### 2. Consistency enforcement

- `[WEB]` Structural only: the `system` override + templates + style arrays are re-injected every turn through state composition; **evaluators** (post-turn LLM judges, e.g. fact-extraction and reflection evaluators in bootstrap) write learned facts/reflections into memory, which providers then re-inject — a slow persona-of-the-*user* accumulation rather than persona policing of the agent. No drift detector, no style classifier in core.
- `[INFERENCE]` Eliza's real consistency bet is the same as a16z's, scaled: many small redundant fragments (bio + lore + adjectives + examples + style) so no single omission breaks character.

### 3. Relationship state

`[WEB]` Runtime memory tracks per-user facts and "relationship data — interaction history and preferences" (docs), but there is no numeric relationship model (no affinity/trust variables or thresholds) in the Character system.

### 4. Emotional-support strategies

None.

### 5. License — read exactly

`LICENSE` = **MIT License, Copyright (c) 2026 Shaw Walters and elizaOS Contributors**. Freely stealable.

### 6. Steal verdict

**Steal the channel-split style object into `JARVIS-RULES.txt`: split the persona's style rules into `all / voice / text / phone` sections and have `brain._load_persona` compose only the matching subset per channel — v2 already knows JARVIS speaks differently aloud vs on Telegram, but the rules file can't express it, so every channel currently gets every rule.** The fragment-array bio is a lesser, compatible steal: TEACHING lessons are already fragments; eliza proves recomposing a subset per turn beats injecting the whole file.

---

## thu-coai/Emotional-Support-Conversation (ESConv)

`[WEB]` — read from repo README, `strategy.json`, `codes/README`, LICENSE on GitHub. Not a companion framework: the ACL 2021 dataset + models behind almost every later "emotional support" system, included in this slice for its strategy machinery (brief §4 of the assignment, answered in full here).

### 1–3. Persona / consistency / relationship state

None by design — the supporter is a trained role, not a character; there is no persona file, no drift handling, no relationship state. What it has instead is a *situation* model: each conversation is annotated with a problem category (12 topics; largest: ongoing depression 351, job crisis 280, breakup 239, problems with friends 179, academic pressure 156 of 1,300 conversations) and the seeker's emotion trajectory is the thing being moved.

### 4. Strategy machinery — the taxonomy, the sequencing, the selection mechanism

- `[WEB]` **Taxonomy** (`strategy.json`, exactly 8 labels, annotated per supporter turn in `ESConv.json`): `[Question]`, `[Restatement or Paraphrasing]`, `[Reflection of feelings]`, `[Self-disclosure]`, `[Affirmation and Reassurance]`, `[Providing Suggestions]`, `[Information]`, `[Others]`. Corpus frequencies (18.3k supporter turns): Question 20.7%, Others ~18.2%, Providing Suggestions 16.1%, Affirmation and Reassurance 15.4%, Self-disclosure 9.3%, Reflection of feelings 7.8%, Information 6.6%, Restatement/Paraphrasing 5.9%. Note the shape: **questions + affirmation ≈ 36% of all turns; direct suggestions only 16%** — even in a corpus built to help, advice is a minority move.
- `[WEB]` **Sequencing** (paper's framework, grounded in Hill's Helping Skills Theory): support proceeds in three stages — **Exploration** (Question, Restatement, Reflection — understand the problem and the feeling) → **Comforting** (Reflection of feelings, Affirmation and Reassurance, Self-disclosure — reduce the negative emotion) → **Action** (Providing Suggestions, Information — give a workable plan). The annotated corpus shows strategies shifting along exactly this arc over a conversation; jumping to Action-stage strategies early is the canonical failure the dataset was built to expose.
- `[WEB]` **Selection in code:** in `codes/`, the strategy is a **prefix token on the supporter turn** in the training files (`trainWithStrategy_short.tsv`); the "Joint" model (BlenderBot-small / DialoGPT fine-tunes) learns to *generate the strategy token first, then the utterance conditioned on it* — strategy selection and surface realisation are one autoregressive pass, with an "Oracle" variant fed the gold strategy as an upper bound. The repo's own negative results are recorded in `codes/README`: *"I have tried: information of turn, role; strategy embedding; extra classification head for strategy predicting. They carry no or small improvement."* — i.e. the dumb prefix-token beat the clever heads.
- `[WEB]` **Outcome annotation:** `FailedESConv.json` (added 2024) releases 196 *failed* conversations with the exact rejection rule (post-survey negative-emotion intensity did not decrease, or empathy ≤ 2, or relevance ≤ 2, …) — a labelled set of what unsuccessful support looks like, rarer and more useful than the successes.

### 5. License — read exactly

`LICENSE` = **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)**; README header adds: *"Data and codes are for academic research use only."* Ideas/taxonomy freely usable; the data itself is non-commercial.

### 6. Steal verdict

**Steal the 3-stage gate into `TEACHING.md` as a lesson, not code: when Owais is venting or stressed, JARVIS must pass Exploration (one clarifying question / restate the feeling) and Comforting (affirm, briefly) before Action (suggestions/fixes) — and the corpus ratio is the calibration: advice should be the minority move.** v2's craftsman persona defaults to fixing; ESConv is 18k turns of evidence that fixing first reads as not listening. The prefix-token trick also maps cleanly onto `golden_pairs.py`: tag golden pairs with a strategy label so the brain can be taught *which move* a correction exemplified.

---

## moeru-ai/airi

`[WEB]` — read from repo page, `packages/ccc/src/define/card.ts`, and DeepWiki's stage-ui analysis. A 50k-star VTuber/"cyber living" platform (Neuro-sama recreation): realtime voice, Live2D/VRM embodiment, game-playing. Its persona layer is deliberately *not* novel — and that is the finding.

### 1. Persona definition

- `[WEB]` Airi adopts the community **Character Card V3** spec wholesale via its own card package `packages/ccc` (Character Card Compiler/codec): `defineCard()` produces a `Card = CardCore {creator, name, nickname, version} & CardDescription {description} & CardExtra {personality, scenario, systemPrompt, postHistoryInstructions, tags, messageExample: Message[][]} & CardAdditional {assets (incl. emotion images), characterBook (lorebook), greetings[] (greetings[0]=first_mes, rest=alternate greetings), greetingsGroupOnly, notes, source, extensions}`. Cards live in the `useAiriCardStore` (CRUD + activation); the active card is held by `useCharacterStore` in `packages/stage-ui/src/stores/character/`.
- `[WEB]` Assembly is the SillyTavern lineage (systemPrompt → character fields → history → postHistoryInstructions) inherited from the V3 spec — Airi adds nothing to prompt-side persona theory.

### 2. Consistency / embodiment machinery — the one original idea

- `[WEB]` **LLM output markers as an actuation channel:** `useCharacterStore` parses the LLM's streamed output with `useLlmmarkerParser` and applies parsed markers to character state — the same stream that carries words carries *embodiment commands* (emotion/expression changes queued for the Live2D/VRM stage, per DeepWiki's character-rendering analysis: "emotion queue"). Persona consistency here is cross-modal: the face must agree with the words, in real time, from one token stream.
- `[WEB]` Memory is pluggable and explicitly experimental ("Memory Alaya (WIP)", in-browser DuckDB-WASM/pglite, `packages/memory-pgvector` server-side) — no relationship-state model, no drift machinery in the card layer.

### 3–4. Relationship state / support strategies

None found. Proactivity and game-playing are orchestrator features, not relationship modelling.

### 5. License — read exactly

**MIT License** (repo metadata + LICENSE file). Freely stealable.

### 6. Steal verdict

**Steal the marker channel into v2's voice/HUD path: let the brain's reply stream carry inline markers (emotion/expression/state) that are parsed out before TTS and routed to the HUD — one stream, words to the speaker, markers to the arc-reactor face — instead of a second LLM call or post-hoc sentiment analysis to decide how JARVIS should look while speaking.** Airi's card layer itself: nothing to steal beyond what SillyTavern already taught this slice.

---

## Project-N-E-K-O/N.E.K.O

`[WEB]` — read from repo README, `config/` and `memory/` listings, `config/character_fields.py` on GitHub. A proactive desktop catgirl companion (Steam-distributed, Apache-2.0) whose architecture independently converges on several JARVIS-v2 shapes: local-first, proactive, five-layer memory, character cards.

### 1. Persona definition

- `[WEB]` Characters are profiles in `config/characters/` with a strict split enforced in code (`config/character_fields.py`): **user-editable section fields** (free-form per-heading prose sections — external character cards are imported by folding their headings into sections) versus a **`_reserved` block that generic editors may never touch**: `RESERVED_FIELD_SCHEMA { character_id, character_uid (32-hex, survives rename), system_prompt, voice_id, persona_override {preset_id, selected_at, source, prompt_guidance, profile}, ai_context {rename_events[]}, character_origin {...}, avatar {model_type, live2d/vrm/mmd paths, animations, lighting} }`. "system: maintained by designated system features, never modified directly via generic character editors" — the eros/Mirrai guard pattern again, as a *schema-level* read-only region rather than a prompt trick.
- `[WEB]` A `persona_override` with its own `prompt_guidance` lets a preset temporarily re-skin behaviour without rewriting the profile — Mirrai's scene-overlay pattern, persisted with provenance (`source`, `selected_at`).

### 2. Consistency machinery

- `[WEB]` (from `memory/` module inventory — file-level evidence, internals not read line-by-line): `memory/anti_repeat.py` + `anti_repeat_effects.py` (anti-repetition as a memory-layer service, cf. eros/astrbot/OpenHer — the fourth sighting of this pattern in one slice); `memory/persona/` (a dedicated **persona memory** layer, one of the five advertised layers: working / recent / factual / reflective / persona memory `[README]`); `memory/reflection/` + `_reflection/` (reflection passes that consolidate); `fact_dedup.py`, `hybrid_recall.py`, `recall_render.py` (how recalled material is rendered into context is its own module); `speaker_trust.py` + `trust_store.py` (a per-speaker trust store exists — in a multi-speaker/desktop setting, *who is talking* is modelled, though no numeric update rules were read); `user_directives.py` (standing user instructions as a memory class); `startup_greeting_history.py` (even greetings are stateful).
- `[INFERENCE]` The design centre is memory hygiene over persona invention: five memory types, dedup, scoped refine (`scoped_refine.py`, `scopes.py`) — consistency emerges from what is recalled and how it's rendered, not from a persona prompt.

### 3–4. Relationship state / support strategies

A trust store exists per speaker (`trust_store.py`) but its variables/update rules were not read at code depth in this pass — reported honestly as present-but-unexamined. No support taxonomy.

### 5. License — read exactly

**Apache License 2.0** (repo metadata; source files carry the Apache header, verified in `character_fields.py`). Code and ideas stealable with attribution.

### 6. Steal verdict

**Steal the reserved-fields split into `JARVIS-RULES.txt` handling: mark a region of the persona file as system-reserved (identity, voice rules, safety) that the teaching/learning pipeline may read but never rewrite, with all learned edits landing in the open section — NEKO implements as schema what eros implements as a constant and astrbot as a review queue, and the schema version is the cheapest of the three for v2 to adopt.** Its five-layer memory naming (working/recent/factual/reflective/persona) is also a cleaner taxonomy than v2's current memory split, worth borrowing as labels.

---

## Shaunwei/RealChar

`[WEB]` — read from repo README, `character_catalog/README` and a shipped `config.yaml` on GitHub (local clone stalled repeatedly and was abandoned). The 2023 realtime-voice character app (GPT/Claude + Whisper + ElevenLabs + Chroma); historically the template for "character folder" projects.

### 1. Persona definition

- `[WEB]` One folder per character under `realtime_ai_character/character_catalog/<name>/`: a `config.yaml` + a `data/` folder. `config.yaml` requires exactly: `character_id`, `character_name`, **`system`** (the whole persona as one system-prompt string) and **`user`** (a user-prompt *template* with `{context}` and `{query}` slots); optional: `text_to_speech_use`, `voice_id`, `order`, ReByte ids. The shipped Elon Musk card's `system` is pure first-person prose ("I'm Elon Musk, and if you know me, you'd know… My humor might catch you off guard…") ending in behavioural lines: *"When Elon Musk reply, Elon Musk stay in character as Elon, never admit you are an AI. When user greet you, ask a short and interesting question related to your background."*
- `[WEB]` The `user` template is the assembly: `Context\n---\n{context}\n---\nUse previous information as context… Aim to keep responses super super concise… {query}` — retrieved context is sandwiched into the *user* turn, not the system prompt. The `data/` folder (background.txt, messages.csv, arbitrary md/pdf/docx/epub…) is auto-ingested via LlamaIndex into Chroma and retrieved into `{context}` — a16z's backstory-RAG pattern with even less structure.

### 2–4. Consistency / relationship / support

None beyond "stay in character" prose in the system string and RAG recall. No state, no checks, no strategies. `[INFERENCE]` RealChar's contribution to the field was the realtime voice loop and the folder convention, not persona depth.

### 5. License — read exactly

**MIT License** (repo metadata + LICENSE).

### 6. Steal verdict

**One line: nothing for persona — v2 already exceeds this (its one portable idea, persona+voice_id+data-folder in a single directory, is a packaging convention v2's repo layout already matches in spirit).**

---

## ZrrSkywalker/CharacterLLM

`[WEB]` — **the assigned fork returns HTTP 404** (deleted or renamed; clone and web fetch both failed). This section covers the canonical upstream it forks, `choosewhatulike/trainable-agents` (EMNLP 2023, "Character-LLM: A Trainable Agent for Role-Playing"), read from its repo README.

### 1. Persona definition — a profile that becomes *training data*, not a prompt

- `[WEB]` Persona input is a plain profile: paragraphs of biography in `data/seed_data/profiles/wiki_<Character>.txt`. **Experience Reconstruction** then manufactures the persona as SFT data in four steps (all GPT-3.5-generated, then parsed): **(1) Profile Construction → (2) Scene Extraction** (the LLM invents scenes from the profile: settings, participants, events) **→ (3) Experience Completion** (each scene is expanded into a full multi-turn dialogue in character) **→ (4) Protective Scenes** (`gen_hallucination` — scenes whose entire point is the character *refusing/redirecting* out-of-scope demands, e.g. Beethoven declining to discuss Python, to suppress anachronism/hallucination). Yield: ~1.4–2.2K scenes, ~600K–1M words, ~12–15 turns/scene per character for 9 characters.
- `[WEB]` The resulting model (LLaMA-7B SFT, FastChat, 10 epochs) needs **no persona prompt at inference** — only a thin meta-prompt: *"I want you to act like {character}… The status of you is as follows: Location: {loc_time} Status: {status} The interactions are as follows:"* Persona lives in the weights.

### 2. Consistency enforcement — by construction + by evaluation

- `[WEB]` Consistency is a *training-data property*: protective experiences teach the boundary (what the character cannot know/say) as behaviour, not as an instruction — the direct ancestor of the "golden pairs for corrections" idea, except the pairs are synthetic and pre-emptive. Evaluation is by structured interviews (single- and multi-turn, `run_api_interview_*` + `run_api_score_*`) scored on five named dimensions: **Memorization, Values, Personality, Hallucination, Stability** — `[WEB]` (paper via search summary) trained agents beat prompted ChatGPT/Vicuna/Alpaca personas on personality/stability with markedly lower hallucination, using only 1–2K scenes on a 7B model.

### 3–4. Relationship state / support strategies

None — the interlocutor is an interviewer, not a relationship.

### 5. License — read exactly

Canonical repo: **Apache License 2.0** (repo metadata), *but* the dataset badge is **CC BY-NC 4.0**, the released weights are LLaMA-1 weight-diffs (Llama license governs), and the README's Limitations state the resources are "restricted for academic research purposes only and cannot be used for commercial purposes." The (unreadable) fork's own license could not be verified.

### 6. Steal verdict

**Steal protective pairs into `golden_pairs.py`: alongside correction→pair learning, proactively author pairs for the boundary cases JARVIS actually fails — being asked to break character, to claim feelings he doesn't have, to do the wallet/money moves he must refuse — written as in-character redirects, so the boundary is demonstrated behaviour in TEACHING.md's golden conversations rather than only stated in rules.** v2 will never SFT its brain, which is exactly why the pairs have to carry what CharacterLLM put in weights.

---

## bowen-upenn/PersonaMem

`[WEB]` — read from repo README on GitHub. Not a framework at all: a COLM 2025 **benchmark** (inverted persona problem — the *user* has the persona, the model must track it). One-section treatment, honestly scoped.

- `[WEB]` Setup: synthetic multi-session histories (18 topics: therapy, travel, food, dating, finance…) for user personas with **static attributes** (demographics) and **dynamic attributes** (preferences that *evolve* mid-history); contexts at 32k / 128k / 1M tokens; questions probe 7 in-situ query types — recalling facts, recalling/updating preferences, applying preferences to new suggestions, etc. Question metadata even records `distance_to_ref_in_tokens` (how far back the latest preference mention sits) — drift/forgetting measured as a function of distance.
- `[WEB]` Headline result: 15 frontier models (GPT-4.5/4.1, o-series, Gemini, Claude 3.7, Llama-4, DeepSeek-R1) recall facts well but **hover ~52% (multiple-choice) at applying evolving preferences in new scenarios**, degrading as sessions accumulate; reasoning models show no advantage. Knowing-about-the-user and *acting on* what you know are different skills, and current models are bad at the second.
- License — read exactly: **MIT License** (repo metadata + LICENSE).
- **Steal verdict (one line): steal the eval, not a mechanism — a tiny PersonaMem-style self-test for v2's memory: seed conversations where Owais's preference changes mid-stream ("actually I take it black now"), then probe later sessions on whether JARVIS applies the *new* preference in a fresh scenario; that is the cheapest possible regression test for the user-model half of persona consistency, which every other repo in this slice ignores.**

---

## facebookresearch/ParlAI

`[WEB]` — read from repo README + ParlAI docs via GitHub/search (repo archived; local clone incomplete). The research platform that *defined* persona-conditioning as a task (PersonaChat, ConvAI2) and blended-skills dialogue (BlenderBot). Framework, not a companion product.

### 1. Persona definition — persona as a set of plain sentences

- `[WEB]` PersonaChat's format is the minimal viable persona: 3–5 first-person sentences per speaker ("I have two dogs", "I work as a nurse"), carried in the observation as `your persona:` / `partner persona:` lines and **prepended to the dialogue context** the model conditions on. No structure, no prose biography — persona as a handful of atomic, independently true/false facts. Both interlocutors have personas, and models are scored partly on *detecting the partner's persona* (the persona-detection subtask) — consistency includes noticing the other person's facts, not just reciting your own.
- `[WEB]` Blended Skill Talk (BST) composes three ParlAI tasks into one conversation: PersonaChat (persona talk) + Wizard of Wikipedia (knowledge) + EmpatheticDialogues (empathy) — each BST episode seeds two personas, a WoW topic, and initial utterances, and the human speakers *blend* skills mid-dialogue (~5K dialogues). In self-chat, `--include-personas` prepends the persona strings to each agent's observed context. BlenderBot is the multi-task-trained result: one model, three skills, no skill label at inference.

### 2. Consistency enforcement

- `[WEB]` Training-time only: multi-task training on the skill datasets + BST fine-tuning; the persona sentences stay in context for the whole episode (the a16z preamble trick, standardised). ParlAI's wider platform also normalised **classifier-in-the-loop evaluation** (e.g. safety/style classifiers as agents that score or filter outputs) — the research ancestor of eros/astrbot's judge pattern, used for measurement rather than live control.

### 3–4. Relationship state / support strategies

No relationship state. Empathy in EmpatheticDialogues is situation-labelled (32 emotion/situation categories) rather than strategy-sequenced — ESConv (above) is the strategy-refined descendant of this line.

### 5. License — read exactly

**MIT License** (repo metadata + LICENSE; README: "ParlAI is MIT licensed"). Repo is archived (read-only) upstream.

### 6. Steal verdict

**Steal PersonaChat's atomicity as a formatting rule for `TEACHING.md`'s user-model facts: store what JARVIS knows about Owais as short, single-fact, independently deletable sentences (PersonaChat-style), not paragraphs — atomic facts can be contradicted, superseded and retrieved one at a time, which is precisely the property PersonaMem shows models (and memory systems) fail without.** Persona *conditioning* itself: v2's prose persona is richer and should stay.

---
