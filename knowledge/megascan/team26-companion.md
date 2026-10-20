# MEGA-SCAN TEAM 26 — Emotional Intelligence & Companion Depth

Reverse-engineering how other systems build a companion that *feels* real — emotional
TTS/prosody, persona consistency, relationship state, emotion perception, and the memory
of a bond — for JARVIS v2 (persona in `JARVIS-RULES.txt` + `TEACHING.md`, learning in
`golden_pairs.py`, voice in `jarvis/tts.py` + `jarvis/speech_policy.py`, memory in
`jarvis/memory.py` + `consolidate()`/`recall_gate.py`). Owner hardware yardstick:
**RTX 2060 6GB, Ryzen 5 3600, 16GB RAM.**

**Method note (honesty):** 40 repos targeted; **40 received write-ups** — 23 read from
full local clones at code level, 17 read via per-file GitHub fetch of the same source
after the shared clone proxy stalled under 30+-team load (those sections are tagged
`[WEB]` and cite file paths; they are shallower and say so). Facts are tagged `[CODE]`
(read in source), `[README]` (project's own claim), `[WEB]`, `[INFERENCE]`. Two
integrity notes: the assigned `ZrrSkywalker/CharacterLLM` fork returns HTTP 404
(deleted/renamed) — its section covers the canonical upstream
`choosewhatulike/trainable-agents` and says so; N.E.K.O's trust-store internals are
reported as present-but-unexamined. Full per-repo notes:
[Part A — Emotional TTS & prosody](team26-part-a-tts.md) ·
[Part B — Companion frameworks & persona consistency](team26-part-b-persona.md) ·
[Part C — Relationship memory & emotion perception](team26-part-c-memory-perception.md).

**The headline finding:** nobody in this scan makes a companion feel real with better
persona *prose*. The systems that work treat feeling as **state + position + delivery**,
not description: (1) persona orders placed *after* the history, where attention actually
lives; (2) a numeric relationship state the *engine* owns, updated by an LLM judge that
may only emit grades, never numbers; (3) voice delivery as a contract — direction ×
intensity + a closed set of event tags — translated per TTS backend. JARVIS v2 today has
excellent persona prose (TEACHING.md) and zero of the three mechanisms. All three are
cheap. That is the whole report in one paragraph; the evidence follows.

---

## 1. Prosody & emotional voice (Part A, 13 repos)

All 13 repos reduce to **five mechanism families**:

| # | Family | Repos | Intensity control |
|---|--------|-------|-------------------|
| 1 | Free-form NL tags/instructions in text | Fish, CosyVoice-instruct, IndexTTS2 (soft instruct), Orpheus, Bark, Dia | Lexical only ("a bit…", "very…") |
| 2 | Closed in-text event tags | CosyVoice fine-grained, Chatterbox Turbo, Orpheus, Dia | None — binary events |
| 3 | Continuous scalar dial | Chatterbox `exaggeration`, EmoSphere radius | **Native, bounded 0–1** |
| 4 | Factorised discrete attributes | Spark-TTS, EmoSphere VAD angles | Discrete levels / continuous VAD |
| 5 | Reference/style cloning (bundled mood) | F5, Dia, OpenVoice, Fish, CosyVoice zero-shot | Whatever the clip contains |

Code-level facts that matter:

- **Fish Speech** `[CODE]`: emotion tags are *not tokens and not parsed anywhere* —
  `ServeTTSRequest` is raw text + references; the only structured token in the inference
  path is `<|speaker:0..15|>` (`generate.py:40`). Intensity is purely lexical. S2-Pro is
  4B, Drama 3 is 35B-A3B → **cloud-only for the 2060** — which matches how v2 already
  uses Fish. Drama 3's genuinely new idea is *director revision* ("say that again,
  gentler") as a conversation-layer retry.
- **CosyVoice** `[CODE]`: the most complete control surface — three stacked channels:
  an utterance-level NL `instruct` channel (`frontend.py:200` — the instruction
  *replaces* prompt text and the speaker embedding is deliberately removed to prevent
  leakage), a closed tokenizer-registered tag set (`[breath] [laughter] <strong>…`),
  and zero-shot reference cloning. Bi-streaming (text-in + audio-out, ~150 ms claimed),
  0.5B → **fits the 2060**; but Chinese-first, **no Hindi**.
- **Chatterbox** `[CODE]`: the cleanest knob in the scan — `exaggeration: float`
  becomes a conditioning tensor via a dedicated `nn.Linear(1, n_channels)`
  (`cond_enc.py:55`); default 0.5, ~0.7+ dramatic. Turbo *deletes* the knob
  (`hp.emotion_adv = False`) and uses `[chuckle]`-type tags instead. MIT; Multilingual
  variant **supports Hindi** — the only local candidate that does.
- **Spark-TTS** `[CODE]`: richest algebra — a 25-label pragmatic emotion taxonomy
  (`EMO_MAP`, mixing emotions with speech acts: APOLOGETIC, ENCOURAGING, NO-AGREEMENT)
  plus pitch/pitch-variance/loudness/speed as value *and* level tokens — but the
  shipped CLI exposes only gender/pitch/speed; **emotion has no public inference entry
  point**. Paper surface ≠ shipped surface.
- **EmoSphere-TTS** `[CODE]`: the only *principled* intensity model — spherical VAD:
  radius from the neutral centroid = intensity, clamped [0,1] (`EmoSphere.py:71-73`);
  azimuth/elevation buckets = direction. Research-grade voice, priceless algebra.
- **F5-TTS** `[CODE]`: the control case — **zero emotion control**; emotion is whatever
  the reference clip is doing, inseparably. Its Gradio convention (named speech-types =
  one reference clip per mood) is a workflow worth copying, not a mechanism.
- **EmergentTTS-Eval** `[WEB]`: no synthesis at all — a 1,645-case benchmark in six
  categories (Emotions / Paralinguistics / Foreign Words / Syntactic Complexity /
  Pronunciation / Questions) with an audio-LLM judge. It is how "more expressive"
  becomes falsifiable instead of a vibe.

**Hardware verdict:** CosyVoice 2/3 (0.5B), Chatterbox (110–500M), Spark-TTS (0.5B),
F5 (~0.3B) and OpenVoice fit 6GB comfortably; Dia (4.4GB bf16) and IndexTTS2 (~1.5B)
are borderline; Orpheus-3B, Fish and Bark do not fit locally.

## 2. Persona consistency (Part B, 14 repos)

Four independent enforcement layers were found across the slice — and the strongest
systems stack them:

**(a) Position — the bookend (SillyTavern, AGPL, ideas only).** `[WEB]` A decade of
power-user experimentation converged on assembly order as the mechanism: character
definitions *before* history, **Post-History Instructions dead last, after the entire
history**, Author's-Note anchors injected *inside* history at configurable depth, and
lorebook entries rationed by a **25% context budget** with sticky/cooldown timing.
Recency position, not system-prompt prose, is what holds a persona in long sessions.
This matters because of the measurement in §2e below.

**(b) Engine-owned guards (eros-engine, N.E.K.O, Mirrai — three independent
inventions).** `[CODE]` eros re-appends a constant `PERSONA_GUARD` after *every*
persona's authored system prompt, with the comment that it was moved out of persona
text "or user-authored personas drift out of character"; its `ANTI_REFUSAL_GUARD`
treats refusal text in history as contamination (production measurement: refusal
recurrence 63% → 25% on polluted context). N.E.K.O implements the same idea as a
schema-level `_reserved` block generic editors may never touch; Mirrai places an
env-switchable identity rule *first* in its assembler. **Convergence: persona
invariants must live where editors and learners cannot rewrite them.**

**(c) Decide before generating (eros PDE; OpenHer genome).** `[CODE]` eros's Persona
Decision Engine produces an `ActionPlan` (reply/refuse/ghost, style, inner-state hints)
*before* the chat model runs. `[WEB]` OpenHer goes furthest: **no line of prompt
describes her personality at all** — a character is a `SOUL.md` of drive baselines
(connection 0.70, novelty 0.50, expression 0.65, safety 0.40, play 0.55) + physics
constants; a tiny seeded random network (25D → 24D → 8 behaviour signals with word
anchors) is pre-warmed on 60 simulated steps, learns per turn by Hebbian updates from a
Critic LLM's reward, and *snaps* discontinuously when frustration crosses
`phase_threshold = 2.0`. Behaviour emerges; it is never described. (Verdict for v2:
fascinating, wrong fit — JARVIS's persona must stay inspectable and owner-editable.)

**(d) History hygiene — the pattern nobody expects (eros, OpenHer, N.E.K.O, astrbot —
four sightings).** Models copy what they see in their own prior turns, so the
*injected* history is transformed while storage keeps originals: eros strips each
prior turn's first sentence (23.5% of turns carry 58.2% of opening repetition) and
strips stage-direction blocks ("an instruction alone cannot stop the model copying
blocks it sees"); OpenHer's `clean_action_markers()` does the same for stored style
memories. **You cannot instruct your way out of a copying problem; you must edit what
the model is shown.**

**(e) The measurement that justifies all of it (PersonaMem, MIT).** `[WEB]` 15
frontier models recall user facts well but hover at **~52% (multiple-choice) at
applying a user's *evolving* preferences in new scenarios**, degrading as sessions
accumulate; reasoning models show no advantage. Knowing-about-the-user and acting on
it are different skills. v2's per-turn recall (recall_gate.py) answers the first;
nothing in v2 yet tests the second.

Also in Part B: **a16z companion-app** (MIT) — the seed-chat trick: example dialogues
are written into the *history store*, so the model's first "memories" are the fictional
seed exchanges (show, don't tell). **eliza** (MIT) — persona as an array of fragments
with style split by channel (`all / chat / post`), recomposed per turn. **Mirrai**
(MIT) — scene overlays that swap one prompt layer (late-night chat, after-a-spat)
without touching the persona, a regex emotional-state machine at zero cost, and a
"graduation" mechanic (the twin succeeds by helping you let go — not applicable to a
butler, honestly noted). **CharacterLLM** (upstream Apache-2.0) — *protective scenes*:
training scenes whose whole point is the character refusing out-of-scope demands, so
boundaries are demonstrated behaviour, not stated rules. **ParlAI** (MIT, archived) —
PersonaChat's atomic persona sentences: independently true/false facts, the ancestor
of every user-model format since.

## 3. Relationship state — the bond as data (Parts B + C)

Two full implementations and two simple ones were found; **12 of the 13 memory repos in
Part C have no relationship model at all** — they store facts *about* the user, never
the state of the relationship itself. That gap is the single biggest finding of this
team.

- **eros-engine affinity** `[CODE]` (`affinity.rs`, 1,764 lines; AGPL — ideas only):
  six axes ∈ [0,1] — warmth, trust, intrigue, intimacy, patience, tension — split into
  *line axes* that accumulate (**Bond = (trust+intrigue)/2**, **Chemistry =
  (intimacy+tension)/2**, five tiers at 0.15/0.35/0.62/0.9) and *derived endpoints*
  (warmth/patience re-derived each turn from the judge's grade, amplified by the
  counterpart line). The discipline is the steal: **the LLM judge outputs only ordinal
  grades −4..+4, never floats**; the engine converts (grade units 0.0786 bond /
  0.0266 chem, negatives ×1.5 — "slow up, fast down", tier damping
  [1.0, 0.70, 0.45, 0.25, 0.10], cross-line tax 5/6), decays intrigue −0.01/day and
  tension −0.005/day, and maps state to behaviour deterministically (warmth>0.65 →
  affectionate nicknames allowed; trust<0.3 → keep distance; patience<0.35 → replies
  may be dismissive). The persona's `[feelings]` is a one-sentence LLM-written clause
  stored on the row and re-injected verbatim — "models don't read calibrated numbers."
  A ghosting scorer can even choose silence (hard vetoes: never before 10 messages,
  never twice in a row).
- **Smart-Memory Relationship History** `[CODE]` (AGPL — ideas only): the cheapest
  sufficient model. State = directed pairs `A->B` → ≤6 descriptors `{word, magnitude
  ∈ low|medium|high}`, updated by an LLM *delta* prompt that must **carry every
  descriptor forward unless the scene explicitly resolves it** (`!descriptor` =
  removed). Magnitudes are anchored to event classes (low = kind gesture, medium =
  confession/betrayal, high = life-changing). Injection is presence-gated (~250
  tokens) — dormant relationships cost nothing. Its retention score also contains the
  scan's only relationship-native terms (`persona_relevance`, `intimacy_relevance`).
- **astrbot affection** `[CODE]` (AGPL — ideas only): the toy version, still
  instructive — an integer 0–100 per user, an **append-only audit log** of every delta
  with its reason, and a static rule table over 17 classified interaction types
  (thanks +2, praise +5, gift +8, insult −8, threat −12) gated by the bot's own mood
  (flirt only counts when mood ∈ {happy, playful, excited}; mood multiplies gains
  ×0.4–×1.3). Every rapport change is explainable.
- **Mirrai intimacy** `[CODE]` (MIT): the anti-pattern to avoid — intimacy is a
  *derived* progress-bar score from capped activity counters (≤1000, levels up to
  灵魂伴侣 "soulmate"). It measures engagement, not a relationship.
- **Microverse** `[CODE]` (MIT): the negative finding — its "relationship math" does
  not exist; relations are `{type ∈ 7 labels, strength −10…+10}` written **only by the
  human god-UI**, never auto-updated. A label is not a model.

## 4. Emotion perception — hearing the owner's mood (Part C)

- **VADER** `[CODE]` (MIT): 695 LOC, a 7,520-token lexicon + 5 rule families (boosters
  ±0.293, caps ±0.733, negation ×−0.74, "but"-clause reweighting), `{neg/neu/pos,
  compound}` in ~milliseconds, zero dependencies. **Verified live by execution during
  this scan:** "I am so frustrated today" → compound −0.656. Honest limit, also
  verified: romanised Hinglish scores neutral 0.0 — the lexicon is English-only, so a
  v2 mood gate needs a small Hinglish supplement or an LLM fallback for Hindi turns.
- **Speech emotion recognition is the weak sense.** Demfier's own tables `[CODE]`:
  transcript text 64.9% vs audio-only 56.6% on IEMOCAP; EmoBox `[CODE/README]`
  demonstrates cross-corpus SER collapse (and ships no LICENSE file — its MIT badge is
  unverified). **Verdict: sense mood from words first (VADER + transcript), treat
  voice-prosody SER as experimental.** SemanthaVoiceAssistant `[CODE]` shows the
  consumption pattern — route-on-affect → tone-policy injection — implemented there as
  a paid embedding call where VADER does it free.
- The handcrafted-persona-engine `[README via web]` contributes one zero-cost
  protocol: in-band `[EMOTION:…]` tags emitted by the LLM and consumed by the avatar
  layer — the same marker channel airi uses for embodiment (§2, Part B).

## 5. Emotional support — how to respond, in what order (Part B)

**ESConv** `[WEB]` (thu-coai; data CC BY-NC 4.0, taxonomy free to use): 8 labelled
strategies over 18.3k supporter turns — Question 20.7%, Providing Suggestions 16.1%,
Affirmation and Reassurance 15.4%, Self-disclosure 9.3%, Reflection of feelings 7.8%,
Information 6.6%, Restatement 5.9%. Sequencing follows Hill's stages — **Exploration →
Comforting → Action** — and the corpus's canonical failure is jumping to Action early:
even in a corpus built to help, **advice is the minority move (~16%); questions +
affirmation are ~36%**. In code, the winning selection mechanism was embarrassingly
simple: a strategy *prefix token* generated before the utterance beat strategy
embeddings and classifier heads ("they carry no or small improvement" — the repo's own
negative results). `FailedESConv.json` (196 failed conversations with an explicit
rejection rule) is the rarest artefact in the scan: labelled unsuccessful support.

## 6. Memory that serves the bond (Part C, 13 repos)

- **MemoryOS heat-gated promotion** `[CODE]` (Apache-2.0): consolidation fires when a
  session's heat `H = N_visit + L_interaction + exp(−Δt/24h)` crosses **5.0**, then the
  LLM profile/knowledge pass runs and the counters reset — *attention*, not the clock,
  decides when memory work happens. Its 90-dimension user-profile taxonomy (including
  how the user wants the AI to behave) is evidence-gated.
- **A-MEM memory evolution** `[CODE]` (MIT): a new note triggers one gated LLM call
  that may rewrite *neighbours' context/tags only* — raw content is immutable, every
  change lands in an `evolution_history` log, failure is a safe no-op. LoCoMo multi-hop
  F1 24.55 → 45.85.
- **AutoMem** `[CODE]` (MIT): an explicit relevance formula (age × access ×
  `1+0.3·ln(1+links)` × importance × confidence) with a **protection veto** — importance
  ≥ 0.7, < 90 days old, or Decision/Insight type can never decay — plus regex-first /
  LLM-fallback fact typing and a 9-component no-LLM recall scorer.
- **mem0** `[CODE]`: steal two cheap mechanics, skip the architecture — MD5-hash dedup
  *before* any LLM/semantic work, and its extraction prompt's negative discipline.
- **MOSAIC** `[README via web]`: steal the cadence, not the app — a periodic
  (nightly/weekly) LLM "mood & themes" digest over the day's entries is the natural
  input format for a relationship digest.

---

## Top 5 mechanisms (all slices, ranked)

1. **The bookend** (SillyTavern) — persona orders *after* the history + anchors inside
   it. Zero state, zero cost, attacks the empirically measured failure (PersonaMem's
   ~52%) that long sessions dilute persona. The single highest value-per-line change
   available to v2.
2. **Judge-grades-only relationship state** (eros affinity × Smart-Memory Relationship
   History) — two independent implementations converging on the same design: an LLM
   proposes *grades/descriptors*, deterministic engine code owns the numbers, updates
   are damped, asymmetric (slow up, fast down) and auditable. This is the difference
   between "remembers facts about Owais" and "has a relationship with Owais."
3. **The two-part delivery contract** (Fish × CosyVoice × Chatterbox × EmoSphere) —
   utterance-level direction (emotion-direction × intensity 0–1) plus a closed
   whitelist of in-text event tags, owned by `speech_policy.py` and translated or
   stripped per backend. Ships with zero new models; works with v2's Fish cloud backend
   today and with CosyVoice3/Chatterbox on the 2060 tomorrow.
4. **Review-gated self-modification with mass-weighted pairs** (astrbot × OpenHer) —
   learned persona changes land as *pending* records with backup-before-apply and
   one-click revert; a golden pair's influence is a mass that grows on recurrence and
   decays with a ~29-day half-life toward a floor of 1.0, never zero. Together they
   make v2's existing correction→pair learning both safe and self-pruning.
5. **Heat-gated, veto-protected memory maintenance** (MemoryOS × A-MEM × AutoMem) —
   consolidation triggered by attention heat (threshold 5.0) instead of idle time;
   neighbour evolution that can touch context/tags but never raw content; decay with a
   protection veto for important/recent/decision facts. A direct upgrade path for v2's
   `consolidate()`/`decay()`.

## Top 3 steals for JARVIS v2

1. **Bookend + reserved persona region** → `brain._load_persona` + `JARVIS-RULES.txt`.
   Append a short post-history persona tail (a distilled dozen lines: calm, concise,
   "sir", no robotic filler) *after* the conversation history on every turn, in
   addition to the current head load; and mark a system-reserved region of the rules
   file (identity, voice rules, safety) that the teaching/learning pipeline may read
   but never rewrite — eros's guard constant, N.E.K.O's reserved schema and astrbot's
   review queue are three implementations of this one idea; v2 can take the cheapest
   (a file region + a tail block). *License posture: all three sources are AGPL or
   pattern-level — implement as our own code, which the design makes trivial.*
2. **A relationship_state for the one pair that matters** → `jarvis/memory.py`,
   updated inside `consolidate()`. A tiny table
   `relationship_state(pair, descriptor, magnitude, updated_at)` for Owais↔JARVIS,
   maintained by Smart-Memory's carry-forward delta pattern (descriptors persist
   unless explicitly resolved; magnitudes anchored to event classes; cap ~6;
   presence-gated injection ~250 tokens, relational turns only). Start descriptor-
   based (auditable, no fake precision); eros's graded axes are the documented
   upgrade path if descriptors prove too coarse. Pair it with the VADER mood gate
   (MIT, vendored, verified live in this scan) so JARVIS can *hear* a bad day —
   with a Hinglish supplement, since VADER alone scores romanised Hindi as neutral.
3. **The delivery contract + one ESConv lesson** → `jarvis/speech_policy.py`,
   `jarvis/tts.py`, `TEACHING.md`. speech_policy owns: (i) an utterance direction =
   persona instruction + emotion-direction × intensity 0–1 (EmoSphere's algebra,
   Chatterbox's single-dial ergonomics — expose it as one `expressiveness` value in
   the persona config, default 0.5); (ii) a closed tag whitelist
   (`[pause] [breath] [laugh] [chuckle] (sighs) <strong>`) passed through to
   tag-capable backends (Fish today) and stripped for tag-blind ones (Piper);
   (iii) Orpheus's restraint as policy — tags are seasoning, default is no tag. In
   TEACHING.md, add the ESConv lesson as Lesson 11: *when Owais is venting or
   stressed, pass Exploration (one question / restate the feeling) and Comforting
   (brief affirmation) before Action (fixes) — advice is the minority move* — and
   apply a16z's seed-as-history trick: inject TEACHING.md's golden conversations as
   the opening turns of session history, not only as a document the brain reads
   about. Close the loop with EmergentTTS-Eval's six categories as a fixed
   `tests/voice/` regression set (including Hinglish cases) so every warmth change is
   measurable.

## License ledger (verified from LICENSE files / repo metadata)

- **Ideas only, never code (AGPL-3.0):** eros-engine, astrbot_plugin_self_learning,
  SillyTavern, Smart-Memory. (All four headline mechanisms above are designs, and each
  steal is specified at pattern level for exactly this reason.)
- **Non-commercial taint:** ESConv data (CC BY-NC 4.0 — taxonomy/ideas fine, data not
  for product use), CharacterLLM dataset (CC BY-NC 4.0 + LLaMA weight terms),
  OpenVoice V2 weights and F5-TTS weights (Emilia, CC-BY-NC — both repos' *code* is
  MIT; do not ship the weights on the strength of the code license).
- **Custom/restrictive:** Fish Audio Community License (commercial only below
  USD 500k revenue, hosted-TTS needs separate licence, no training other models; S2
  weights under Fish Audio Research License) — fine for JARVIS's own replies via the
  cloud API, not a shippable local dependency. IndexTTS weights (bilibili Model Use
  License — commercial use needs prior written authorisation; code is Apache-2.0).
- **Clean MIT / Apache-2.0 (code stealable with attribution):** CosyVoice, Spark-TTS,
  Dia, Orpheus-TTS, Chatterbox, EmoSphere-TTS, OpenVoice (code), a16z companion-app,
  Mirrai, eliza, airi, RealChar, ParlAI, PersonaMem, OpenHer (Apache-2.0), N.E.K.O
  (Apache-2.0), MemoryOS (Apache-2.0), A-MEM, AutoMem, mem0, VADER, Microverse.
- **Unverified:** EmoBox (no LICENSE file in repo; README badge claims MIT),
  Expressive-FastSpeech2 (clone empty; license not read). Neither is cited as
  license-clean anywhere in this report.

## Full coverage table (40)

| Repo | Slice | Depth | One-line verdict |
|------|-------|-------|------------------|
| fishaudio/fish-speech | A | CODE | Steal the inline-tag interface; model is cloud-only, license is custom |
| FunAudioLLM/CosyVoice | A | CODE | Two-level control split + bi-streaming; best local instruct model, no Hindi |
| index-tts/index-tts (IndexTTS2) | A | WEB | Steal the voice/emotion disentanglement requirement; weights need bilibili authorisation |
| resemble-ai/chatterbox | A | CODE | Steal the `exaggeration` dial; MIT, Hindi-capable multilingual variant |
| SparkAudio/Spark-TTS | A | CODE | Steal the factorised attribute schema + 25-label taxonomy; emotion not wired in shipped CLI |
| canopyai/Orpheus-TTS | A | CODE | Steal the 8-tag restraint; 3B doesn't fit the 2060 in this implementation |
| nari-labs/dia | A | CODE | Steal parenthetical stage-directions as the human-readable tag spelling; don't ship the model |
| SWivid/F5-TTS | A | CODE | Negative control: cloning bundles mood; steal only the per-mood reference library workflow |
| myshell-ai/OpenVoice | A | CODE | Steal the named style-slot asset pattern (6–9 categorical moods) |
| Choddeok/EmoSphere-TTS | A | CODE | Steal the (direction × radius) emotion algebra; research-grade voice |
| keonlee9420/Expressive-FastSpeech2 | A | WEB | Nothing repo-specific verifiable (clone empty) |
| suno-ai/bark | A | WEB | Historical proof for tags + typography-as-prosody; too big/unruly to ship |
| boson-ai/EmergentTTS-Eval | A | WEB | Steal the 6-category taxonomy as v2's voice regression set |
| etherfunlab/eros-engine | B | CODE | The relationship-physics reference design; AGPL — ideas only |
| a16z-infra/companion-app | B | CODE | Steal seed-as-history for golden conversations; MIT |
| NickCharlie/astrbot_plugin_self_learning | B | CODE | Steal the review gate + delta audit log for learned persona changes; AGPL |
| Ch1rpy2613/Mirrai | B | CODE | Steal scene overlays; derived intimacy score is an anti-pattern; MIT |
| kellyvv/OpenHer | B | WEB | Steal Style Memory's mass/half-life pair weighting; genome itself wrong fit for a butler; Apache-2.0 |
| SillyTavern/SillyTavern | B | WEB | Steal the bookend + lorebook budget/trigger discipline; AGPL |
| elizaOS/eliza | B | WEB | Steal channel-split style (`all/voice/text/phone`) for JARVIS-RULES; MIT |
| thu-coai/Emotional-Support-Conversation | B | WEB | Steal the 3-stage gate + strategy labels for golden pairs; data CC BY-NC |
| moeru-ai/airi | B | WEB | Steal the inline marker channel (words→TTS, markers→HUD); card layer adds nothing over ST; MIT |
| Project-N-E-K-O/N.E.K.O | B | WEB | Steal the reserved-fields schema split; trust store present but unexamined; Apache-2.0 |
| Shaunwei/RealChar | B | WEB | Nothing for persona — v2 already exceeds it; MIT |
| choosewhatulike/trainable-agents (CharacterLLM) | B | WEB | Steal protective pairs for boundary behaviour; assigned fork 404s |
| bowen-upenn/PersonaMem | B | WEB | Steal the eval: preference-change self-test for v2 memory; MIT |
| facebookresearch/ParlAI | B | WEB | Steal atomic single-fact formatting for user-model facts; MIT, archived |
| BAI-LAB/MemoryOS | C | CODE | Steal heat-gated promotion (H ≥ 5.0) for consolidate(); Apache-2.0 |
| agiresearch/A-mem | C | CODE | Steal context-only neighbour evolution with an audit log; MIT |
| verygoodplugins/automem | C | CODE | Steal the decay protection veto + relevance formula shape; MIT |
| senjinthedragon/Smart-Memory | C | CODE | Steal the Relationship History data model; AGPL — ideas only |
| KsanaDock/Microverse | C | CODE | Cautionary: human-written relation labels are not a relationship model; MIT |
| mem0ai/mem0 | C | CODE | Steal hash-dedup-before-LLM + extraction negative discipline only |
| cjhutto/vaderSentiment | C | CODE | Steal outright as the mood gate (verified live); needs a Hinglish supplement; MIT |
| Renovamen/Speech-Emotion-Recognition | C | README-web | Tutorial-grade SER; nothing to steal |
| emo-box/EmoBox | C | CODE | Steal the cross-corpus evaluation discipline, not code; license unverified |
| kristofferv98/SemanthaVoiceAssistant | C | CODE | Steal the route-on-affect → tone-policy pattern, at VADER's cost not OpenAI's |
| Demfier/multimodal-speech-emotion-recognition | C | CODE | Steal the fusion lesson: transcript text beats audio-only SER |
| elevenyellow/handcrafted-persona-engine | C | README-web | Steal the in-band `[EMOTION:…]` tag protocol idea |
| rlin27/MOSAIC | C | README-web | Steal the nightly mood-digest cadence for relationship summaries |
