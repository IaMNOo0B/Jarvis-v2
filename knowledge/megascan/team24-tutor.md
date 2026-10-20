# MEGA-SCAN TEAM 24 — TUTOR & LEARNING AGENTS

**Mission:** How do AI tutors, spaced-repetition systems, Socratic agents, quiz assistants and language companions actually work — and what should JARVIS-as-teacher look like for an owner who is himself in learning phase?
**Method:** `git clone --depth 1` into `.work24/`, read locally. Discovery via GitHub search API (sparingly).
**Count: 39 repos cloned & read (16 at code depth, 23 triaged with verdicts); ~60 more surveyed in discovery lists.**
Honest gaps: `ankitects/anki` itself was NOT cloned (giant monorepo) — its scheduling role is evidenced through fsrs4anki + py-fsrs + obsidian-spaced-repetition. `Open-TutorAi/open-tutor-ai-CE` clone FAILED (empty dir) — excluded entirely, not counted. `free-spaced-repetition-scheduler` clones to docs only (it points at implementations). ChatTutor/freelingo read at README+structure depth.

---

## 0. The landscape in one view — a tutor is FOUR machines, not one

Every serious system in this scan decomposes into the same four layers, and most failed/thin repos implement only one:

| Layer | Job | Best-in-scan |
|---|---|---|
| **Scheduler** | When should this item come back? (memory math) | FSRS (py-fsrs / fsrs4anki) — nothing else is close |
| **Pedagogy engine** | How is one concept taught/tested in dialogue? | Engram's dialogue grammar (generation-first, 8 beats) |
| **Learner model** | What does the system believe the learner knows/feels/gets wrong? | Engram (per-node FSRS state + misconception log + calibration) · OpenTutor LOOM (mastery graph) · Bloom (annotation loop) |
| **Grader** | Who verifies learning actually happened? | Engram's **blind assessor** — the only honest design found |

The scan's central finding: **the field's winners separated teaching from grading.** A tutor that grades its own lesson inflates; every inflated grade then poisons the schedule. This is the same "separate generation from evaluation" law JARVIS v2 already follows for itself — it applies identically to teaching the owner.

---

## 1. FLAGSHIP — Engram (nagisanzenin/engram, 1,455★, MIT)

A learning system *for the human*, packaged as a plugin for coding agents (Claude Code, Codex, OpenCode, Hermes, OpenClaw…). The agent becomes tutor + examiner + scheduler. Stdlib-only Python engine (`scripts/engram.py`, ~12,900 lines), plain-JSON local state (`~/.claude/learning/`), zero network code. Commands: `/learn`, `/review`, `/coach`. **This is the closest existing thing to what "JARVIS teaches Owais" should be.**

### 1.1 Pedagogy: generation-first, always
- The tutor's core loop is a **dialogue grammar** (8 beats per concept node): gap → predict → struggle → resolve → self-explain → connect → verify → close. The learner must *produce* an answer before any explanation — "a tutor that makes you do the thinking."
- **Pretesting effect, operationalized:** new topics start with cold free-recall probes of the first 3 nodes *before teaching*; a miss is framed verbatim as *"a wrong guess before learning measurably improves what sticks next"* and becomes a scheduled destination, not a failure.
- **Pretest-the-frontier** for learners who "know the basics": probe mid-arc, walk `requires` ancestors deepest-first, credit only with receipts (≤6 probes/sitting cap so it never feels like an exam).
- Procedure nodes (skills, not facts) swap beats 2–4 for a **problem ladder**: worked example → completion → faded → cold solve, with the answer key *computed by execution, never inspection*.
- The session **never ends on a failed retrieval** — re-queue through other material and return until it lands ("retrieval to criterion").

### 1.2 The blind assessor (the single best mechanism in this entire scan)
`agents/engram-assessor.md` — a fresh-context grader that receives ONLY: node claims, rubrics, the probe, the learner's production, and their pre-feedback confidence. Never the lesson. Integrity rules, each one bought by a measured failure:
- **"Cap at X" is a ceiling, never a floor** — zero rubric criteria met = `lapsed`, always.
- **Meaning over wording** — paraphrase that preserves the mechanism scores; recitation that misses it doesn't.
- **Right answer + wrong method ≤ partial; right answer + zero criteria = lapsed.** ("The answer is not the knowledge.")
- **Procedure grading by execution** — run the learner's arithmetic/code (fed via stdin/file, never inlined into a shell command — command-injection discipline applied to learner text everywhere: productions reach the engine only via `--file`/stdin).
- **`error_class`: slip vs conceptual** — torn → conceptual, because "they only slipped" is the flattering direction and flattery corrupts the schedule.
- **`probe_gap`** — the assessor can indict the *curriculum*: rubric criteria a complete answer to the probe wouldn't necessarily contain are flagged, so bad questions can't cap honest learners.
- **Idempotent receipts** — every item carries a `sid` transaction id so a crash between grade and stash-clear can't double-apply a rating and skew the schedule.
- Grades map to FSRS ratings: recalled→good/easy, partial→hard, lapsed→again.
- `/coach` can **audit the grader itself**: 3 independent assessor spawns re-grade a sample; inflation is counted and published (their gold set: 0/258 graded up).

### 1.3 Learner model
- Per-node FSRS-4.5 state (stability/difficulty/reps/lapses) inside a **concept graph** with `requires` edges, built by a separate curriculum-architect agent from first principles against the learner's stated *goal* ("what do you want to be able to DO with this, and by when?").
- **Misconception log** — distinct wrong models stored in the learner's own framing; feedback references them ("that's the frequency fallacy in your misconception log").
- **Calibration as first-class data** — confidence is collected via picker *before* feedback, never estimated by the model (`null` stays null); `/coach` reports a Brier score in plain words ("when you say 80, you hit 62 — overconfident, mostly on derivable nodes").
- Session modes Sprint/Standard/Deep; an ADHD focus profile that changes dials (session length, feedback timing) — explicitly *not* dressed up as a "learning style."
- Due reviews surface as a quiet session-start nudge; reviews are pushed *before* new material ("spacing beats bingeing").

**Verdict for v2: STEAL THE ARCHITECTURE WHOLESALE (MIT).** Not the code (it's Claude-Code-plugin-shaped), but: concept graph + generation-first grammar + blind assessor + FSRS + calibration + misconception log is the complete blueprint for a JARVIS `teach` skill.

---

## 2. THE SCHEDULER — FSRS won; SM-2 is dead (open-spaced-repetition, MIT)

### 2.1 py-fsrs (513★, MIT) — the algorithm, readable in one file
FSRS-6: every card carries **Difficulty (1–10), Stability (days until recall probability drops to 90%), Retrievability** — the DSR triple. Power-law forgetting curve `R(t,S) = (1 + factor·t/S)^(-decay)`, decay ≈ 0.1542. 21 trainable weights with hard bounds (`fsrs/scheduler.py`):
- Initial stability from first rating: `S₀(G) = w[G-1]`.
- Recall stability update multiplies by `e^{w8} · (11−D) · S^{−w9} · (e^{(1−R)·w10} − 1)` × hard-penalty/easy-bonus — i.e., **the same review is worth more when done at low retrievability** (desirable difficulty is in the math, not the marketing).
- Difficulty mean-reverts toward D₀(Good) with linear damping.
- Interval = solve curve for desired retention (default 0.9), then **fuzzed** (longer intervals get ±5–15% jitter) so reviews don't clump.

### 2.2 The optimizer is the real moat (py-fsrs `optimizer.py`, fsrs4anki 4,109★)
- Weights are **fit per-learner from their own review logs**: replay history through the scheduler, predict retrievability at each review, minimize binary cross-entropy (Adam, torch) against actual recall outcomes.
- `compute_optimal_retention` **simulates** the learner's future workload across retention targets and picks the one minimizing total reviews — retention is a computed optimum, not a default.
- fsrs4anki ships this as an Anki add-on + the JS scheduler port Anki itself adopted (FSRS is built into Anki ≥23.10); `srs-benchmark` ranks FSRS above SM-2/Leitner/HLR across ~10k users' logs (~20–30% fewer reviews for the same retention — benchmark-repo claim [MC], direction consistent everywhere).
- Anki (32k★, not cloned) = the ecosystem gravity: decks, AnkiConnect API — see §5.

### 2.3 The long tail of schedulers — all simpler, all worse, some instructive
- **hashcards** (eudoxia0, 1,175★, Apache-2.0): plain-text decks (`Q:/A:`, `C: [cloze]`) + FSRS in Rust. *Proof the whole SRS core fits in a tiny local tool; plain-text cards = git-friendly, JARVIS-writable.*
- **obsidian-spaced-repetition** (2,591★, MIT): reviews flashcards *and whole notes* in-place; offers FSRS or SM-2 — the note-as-card idea matters for teaching from Owais's own notes/knowledge files.
- **learn-faster-kit** (390★, MIT): fixed ladder [1,3,7,14,30,60,90] days in a JSON file, driven by a `review_scheduler.py` whose **output JSON contains `llm_directive` fields** — scripts that instruct the LLM how to present results. Crude scheduling, excellent agent-ergonomics pattern.
- **memo** (1,870★, BSD-3): programming-oriented SRS (Flutter) — code-flavored cards; thin algorithm, good niche signal.
- **orbit** (Andy Matuschak, 1,834★, **all-rights-reserved — ideas only**): the "mnemonic medium" — spaced repetition embedded *inside* explanatory text (read a document, its embedded prompts resurface over time). Conceptually the future of teaching material; legally untouchable code.
- **ts-fsrs** (828★, MIT): same FSRS in TypeScript — confirms algorithm portability; v2 needs only the ~150-line pure-math core in Python stdlib.

**Verdict for v2: implement the FSRS core (MIT formulas) inside the teach skill; defaults until the owner has ~400 reviews, then fit weights from his logs. Never SM-2, never a fixed ladder.**

---

## 3. Bloom (Li-Evan/Bloom, 289★, MIT) — adaptation by annotation

Named for Bloom's 2-sigma finding (1-on-1 tutored students hit the top 2%). Flow: **syllabus → lesson → annotate → feedback → next lesson (regenerated) → … → evaluation → summary.** The learner highlights text and writes margin annotations + answers thought questions; "Done Reading" triggers generation of the *next* lesson conditioned on: prior lesson + annotations + feedback + a **mastery checklist** (items check off across the course).
- Learner model = *what the learner marked and said*, fed back into generation — no numeric mastery, no scheduling.
- Three input modes (topic / uploaded source / raw project files), depth dial (simple/standard/deep), next-topic recommendations from full learning history, FastAPI + React, also runs as a Claude Code skill.
**Verdict: steal the loop shape for open-ended topics** (lesson sized to one sitting, annotations = the learner telling JARVIS where it hurts, checklist as visible progress). Weakness to avoid: no verification — "read + annotated" is treated as learned. Pair it with Engram-style probing.

## 4. OpenTutor (zijinz456/OpenTutor, 147★, MIT) — the mastery-graph platform

"Block-based adaptive learning workspace that runs locally": upload anything → chapters/notes/quiz/knowledge-graph blocks. Learner model based on **LOOM** (arXiv 2511.21037): concepts extracted from material, prerequisite graph, per-concept `mastery_score` ∈ [0,1] with snapshots on every quiz event.
- The actual update rule (found in `apps/api/routers/progress_knowledge.py:375`) is disarmingly simple: `gain = 0.1 · (1 − mastery) · (fsrs_rating − 1)/3` on success (asymptotic approach to 1.0), `−0.1` on failure. Heuristic, not Bayesian Knowledge Tracing — honest and shippable.
- Tutor persona: adaptive depth + Socratic questioning + source citations; flashcards router reuses FSRS ratings.
**Verdict: steal the mastery-scalar + snapshot history for the HUD/progress view** — JARVIS can *show* Owais "Python decorators: 0.8" without pretending the number is science. Engram's per-node FSRS state remains the truer model underneath.

## 5. anki-mcp-server (ankimcp, 521★, MIT) — the bridge pattern

TypeScript MCP server over AnkiConnect: tools to create/search/update cards, decks, models, media, deck stats — plus **built-in prompts** (`anki_review` session runner, `twenty_rules` = Wozniak's 20 rules of formulating knowledge). Any MCP-capable agent can thus *run* a review session and *author* well-formed cards into the user's real Anki.
**Verdict for v2: pattern-steal, not dependency.** JARVIS's own skills system can expose the same surface (`card_create`, `review_due`, `review_grade`) against its internal FSRS store — or literally bridge to Anki later via the same tool shapes. The 20-rules prompt is the best card-authoring rubric found anywhere; adopt it as the teach skill's card-quality gate.

## 6. Language-learning companions

- **companion** (shakedzy, 195★, **CC BY-NC — ideas only, never code**): voice-first foreign-language tutor (Flask + Whisper + GPT + TTS). Structured per-message feedback (grammar correction separated from conversation flow), level setting at setup, persistent memory of learner errors printed/inspected as "memory updates." The UX lesson: *correction must not break conversational flow* — tutor replies in-language, corrections ride along as a side channel.
- **freelingo** (artcc, 192★, AGPL — ideas only): full self-hosted Duolingo-style platform, local or cloud LLM, SRS-driven lessons. Proof of demand; license blocks reuse.
- **open-course-cli** (scriptology, 17★, Apache-2.0): terminal language tutor (Rust) with the cleanest data model in the niche — per language-pair tables: `curriculum`, `progress`, `history`, `reviews`, `learning_items`. **Steal the schema shape** if JARVIS ever teaches Owais a language.
- **large-language-tutor** (vertesia, 26★, no license): multi-agent language tutor with structured I/O — "delegate deterministic work to code, judgment to the LLM," the same split v2 already uses.
- **Reality check for the Hinglish requirement:** NONE of the 40 repos teaches *in* Hinglish or handles code-mixed Hindi-English learner input. This is white space — JARVIS's teach skill speaking Hinglish (TEACHING.md Lesson 5) would be genuinely novel, and Team 17's Indic findings are the enabling layer.

## 7. Socratic agents — three ways to buy the behavior

1. **Prompt it** — Mr.-Ranedeer-AI-Tutor (JushBJJ, 29.5k★, no license): a single giant GPT prompt with a configuration wizard (depth, style, learning-preferences), prerequisite + main curriculum generation, lesson plans recalled across sessions. Proof that prompt-only tutoring has a hard ceiling: no state, no schedule, no verification — it *feels* like a tutor and retains nothing.
2. **Skill it** — Flagrare/llm-tutor (5★, MIT), sinhnt0220/learning-everything (6★, MIT, "teach the next real capability, verify with artifacts, not confidence"), Gadfly (Touchpoint-Labs, 48★, MIT — a Socratic *supervision* layer that interrogates coding agents, transferable pattern: the gadfly asks "what's your evidence?" before any claim is accepted). Prompt-pack tutors with rules (hint ladders: nudge → hint → worked step → answer) and explicit never-give-the-answer-first discipline.
3. **Train it** — GiovanniGatti/socratic-llm (36★, MIT): EULER project — **DPO fine-tuning** of Phi-3-mini (and a Qwen3-4B successor on HF) on MathDial + debugging dialogues so the model *prefers* Socratic moves over direct answers; GPT-4o-judged eval shows the preference sticks. For JARVIS this is a Phase-later option: a small local Socratic-tuned model as the dedicated tutor brain under the Ollama tier — flag, don't build now.

## 8. Quiz & exam machinery

- **quizicist** (cognitive-engineering-lab, 28★, no license — ideas): the only repo found that *measures* quiz generation — hand-scoring experiments comparing MCQ quality with/without source text, edit-mode JSON repair for malformed LLM output. Lesson: **generation is easy; distractor quality and format validity are the work.** Structured-output + validation loop before any quiz reaches the learner.
- **ExamPrepAgent** (cardea-mcp, 5★): MCP-served exam companion — random study questions, semantic+keyword answer search, guided conversation; Whisper/TTS for spoken drills. Pattern: exam bank as a *tool*, tutor as conversation.
- **exam-prep-agent** (Yajat-Sharma, 6★): the exam-strategy angle — topic ranking by predicted exam weight, study plans, revision roadmaps. Teaching-to-the-test as scheduling over topics (pairs naturally with FSRS over items).
- **AI-study-mission** (ShyamRV, 17★, MIT): 3-agent split (Tutor → Quiz Creator → Evaluator) over Agentverse — the multi-agent version of the teach/grade separation.
- **quiznote** (37★, MIT), **AITutorAgent** (Ebimsv, 15★, MIT, LangGraph + SQLite persistence + auto evaluation questions), **ai-tutor-app** (towardsai, 33★, Apache-2.0 — production-grade LangGraph RAG tutor with checkpointed history and graceful degradation), **edu-agent** (22★, MIT), **AI-Tutor "Nemo"** (Hawary00, 9★, Apache-2.0, age-adaptive), **SkillNet** (ANFAIA, 18★, Apache-2.0, docs→courses+grounded tutors), **CognitiveSB** (4★, no license — PDF/YT → Socratic tutor + flashcards + SRS + knowledge graph, the all-in-one shape at small scale), **cp-tutor-agent** (17★, no license — competitive-programming coaching team: analysis → Socratic guidance → code review → auto-judge, with a persistent user profile), **lumen** (ahmedEid1, 89★, GPL — ideas only: one-sentence goal → full course in ~50s, multi-agent with *auditable decisions* and public evals including weak scores — honesty pattern worth copying).
- **ChatTutor** (HugeCatLab, 1,314★, AGPL — ideas only): the whiteboard insight — a tutor with *tools* (math canvas, drawing) teaches STEM better than text-only chat. For v2 on PC: the HUD/whiteboard is a later wave, but note that "explain with a drawn diagram" is a capability class of its own.

---

## 9. CROSS-CUTTING FINDINGS (the PhD synthesis)

1. **FSRS is the settled science of scheduling.** DSR state + per-learner fitted weights + computed optimal retention. Everything else (SM-2, fixed ladders) survives only in thin tools. ~150 lines of pure math ports it to stdlib Python.
2. **Generation-first beats explanation-first everywhere it's tried.** Pretest → struggle → resolve outperforms read-then-quiz; passive annotation (Bloom) without probing is the known failure mode.
3. **Tutor ≠ grader is the integrity law.** Blind assessment, grade-the-grader audits, and `probe_gap` curriculum-indictment are one idea at three depths: *the system must be able to discover that it taught badly.*
4. **Confidence is data, collected before feedback, never fabricated.** Calibration (Brier) is the owner's mirror: an owner who learns to say "60%" and be right 60% of the time gets better at *everything*, not just the topic.
5. **Learner models form a spectrum**: per-item FSRS state (truest, narrowest) → per-concept mastery scalar (showable) → misconception log (most actionable) → free-text annotation history (richest, least computable). Engram is the only repo holding three of the four.
6. **Scripts should talk back to the LLM** (learn-faster-kit's `llm_directive` outputs) — deterministic state in code, presentation in the model. Identical to v2's existing doctrine; teaching confirms it independently.
7. **Learner text is untrusted input.** Engram's stdin/file-only rule for productions is prompt-injection + shell-injection defense applied to pedagogy — v2's DCL/gate thinking, already aligned.

## 10. WHAT JARVIS-AS-TEACHER SHOULD LOOK LIKE (v2 verdict)

TEACHING.md today teaches JARVIS *how to behave*. The missing twin is a **`teach` skill** that teaches *Owais*, assembled entirely from MIT/Apache parts above:

- **Topic intake (Engram):** goal-first ("what do you want to be able to DO?") → curriculum-architect pass builds a concept graph (`nodes` + `requires`) → stored in `memory.py` semantic store with provenance.
- **Session loop (Engram grammar):** due reviews first via the **reminders/proactivity path** (morning digest line: "3 concepts due — 4 minutes"), then generation-first teaching in Hinglish, confidence asked *before* feedback, productions logged verbatim to the session store.
- **Blind assessor (Engram):** a second brain call with NO conversation context — item + rubric + production only — returns grade → FSRS rating; weekly self-audit re-grades a sample 3× and reports inflation honestly.
- **Scheduler (py-fsrs formulas, MIT):** FSRS core in the skill (~150 lines stdlib), default weights until ~400 of the owner's reviews exist, then an optimizer pass fits his weights; retention target computed, not assumed.
- **Learner model (Engram + OpenTutor):** per-node FSRS state + misconception log (his framing, quoted back at him) + a mastery % per topic for the HUD — labeled as an estimate.
- **Cards (anki-mcp pattern + 20 rules):** `card_create/review_due/review_grade` tools in the skill's own store; Wozniak's 20 rules as the authoring gate; optional future Anki bridge reusing the same tool shapes.
- **Socratic dial (llm-tutor/Gadfly):** hint ladder for "help me" moments — JARVIS asks before it tells, exactly as deep as the owner's patience setting allows.

## TOP 5 REPOS
1. **nagisanzenin/engram** (1,455★, MIT) — the complete teaching machine: curriculum graph, generation-first grammar, blind assessor, FSRS, calibration, misconception log.
2. **open-spaced-repetition/py-fsrs + fsrs4anki** (513★/4,109★, MIT) — the scheduling science and its per-learner optimizer.
3. **Li-Evan/Bloom** (289★, MIT) — the annotation-driven adaptation loop for open-ended topics.
4. **zijinz456/OpenTutor** (147★, MIT) — local adaptive workspace; LOOM mastery graph in shippable heuristic form.
5. **ankimcp/anki-mcp-server** (521★, MIT) — the agent↔SRS bridge pattern + the 20-rules card-authoring prompt.

## TOP 3 STEALS FOR V2
1. **Engram's blind-assessor protocol** (MIT) — fresh-context grading with cap-is-ceiling, probe_gap, sid-idempotent receipts. Directly becomes the teach skill's verifier; mirrors v2's own verifier doctrine.
2. **The FSRS core + optimizer design** (py-fsrs, MIT) — DSR scheduling math in stdlib; fit-to-owner weights after ~400 reviews; computed optimal retention. Plugs into reminders + morning digest.
3. **Engram's generation-first dialogue grammar + confidence-before-feedback calibration** (MIT) — the actual teaching behavior, incl. pretest-the-frontier and never-end-on-a-failure; calibration data lands in `memory.py` next to everything else JARVIS knows about its owner.

*Licenses honored: MIT/Apache steals above are code-and-idea clean. CC BY-NC (companion), AGPL (ChatTutor, freelingo), GPL (lumen), all-rights-reserved (orbit) and no-license repos contributed ideas only — no code.*
