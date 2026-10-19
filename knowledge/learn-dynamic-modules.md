# Dynamic Cognitive Modules for JARVIS — Domain I, OMEGA ∞+1

*PHASE OMEGA ∞+1, Domain I. LEARNING ONLY — no code, no installs, no project files touched.*
*Date: 2026-10-19. Status: research document. This is the most speculative cycle in the program — speculation is marked [SPEC] explicitly.*

**Research question:** Is one fixed pipeline (brain → gate → skills) unnecessarily restrictive? What would dynamically composed cognition look like for JARVIS?

**First read (done):** `learn-v2-master-map.md` (the 12-box map this proposes going beyond), `learn-frontier-reasoning.md` (the 8-strategy selector — strategy-level adaptivity already exists; this cycle asks about *structural* adaptivity, one level up).

---

## 0. The proposal, concretely

**The idea:** instead of every turn flowing through the same fixed stages (brain → gate → skills → brain), JARVIS assembles a *temporary computational structure* per task, then dissolves it. Persistent state lives in the session store; the reasoning structure is transient.

**The composable modules (7 — kept small deliberately):**

| # | Module | Does | Stateless? |
|---|---|---|---|
| M1 | **Perceive** | gather: retrieve memory, read UIA tree, fetch web | yes — results go to session store |
| M2 | **Plan** | decompose task into steps with explicit termination | yes — the plan is logged, then it's data |
| M3 | **Act** | execute tools through the gate (the ONLY module with side effects) | yes — actions are events |
| M4 | **Verify** | deterministic checkers on results (schemas, tests, assertions) | yes |
| M5 | **Judge** | LLM deliberation on ambiguity, interpretation, drafting | yes |
| M6 | **Ask** | user elicitation under the asking-economics rule | yes — answers are events |
| M7 | **Critic** | adversarial review of a plan or output (separate context) | yes |

**Two candidate compositions:**

- *Research task:* Perceive → Plan → Act(retrieve) → Verify(source-trust) → Judge(synthesize) → Critic → (Ask if gaps)
- *Coding task:* Plan → Act(write) → Verify(tests) → Critic(review) → Act(fix) → Verify(tests) — loop with explicit termination (max 2 repair rounds, the Debugging Decay rule)

**What triggers composition vs the default pipeline:** a routing decision at turn start — task-type classification (see §5 for the minimal version).

**What dissolves a structure:** turn end, or explicit termination (max rounds, success predicate met, user interrupt). Dissolution is total: no module retains state. The *only* persistent artifact is the event log in the session store — including a `structure.selected` event recording *which* structure was used and *why* (interrogability: "why did you use the research structure?" must be answerable).

**The critical invariant [HC]:** M3 (Act) is the only module with side effects, and it always routes through the gate. No composition, however dynamic, can give any module a path to tools that bypasses capability checks, tier lookup, and approval routing. Dynamic composition changes *cognition*; it never changes *enforcement*. The gate is not a module — it is the substrate.

---

## 1. Design (a): Fixed pipeline — the null hypothesis

**1. Intended capability.** Every turn flows through the same declared path: brain (judge + propose) → gate (validate) → skills (act) → brain (interpret). Adaptivity lives *inside* the brain via the 8-strategy reasoning selector (Cycle: frontier-reasoning §5) — the pipeline is fixed, the strategy varies.

**2. Theoretical motivation.** Anthropic's "Building Effective Agents" (Dec 2024) — the most field-validated guidance in the industry: the most successful implementations use simple, composable patterns; add multi-step agentic behavior only when simpler solutions fall short. For well-understood task classes, a fixed workflow with clear responsibilities beats dynamic orchestration. Determinism is a feature: fixed trace shapes make testing, debugging, and safety certification tractable.

**3. Assumptions.** (i) JARVIS's task distribution is dominated by a few task shapes (chat, lookup, simple action, multi-step task). (ii) Strategy-level adaptivity (the 8 strategies) captures most of the achievable variance. (iii) Composition overhead (latency, failure modes, debug cost) exceeds composition benefit for the common case.

**4. Computational cost.** 1× baseline. No composition decision, no router, no validator. The 8-strategy selector adds strategy cost only (best-of-N, tree search) — never structural cost.

**5. Failure modes.** (i) Underfits genuinely novel task shapes — the "one loop for everything" strain on tasks that need a fundamentally different shape (e.g., long-horizon research with parallel branches). (ii) The strategy selector becomes the new bottleneck — note it is *already* a meta-decision; this design doesn't eliminate meta-decisions, it just keeps them small. (iii) Strategy bloat: as more strategies are added, the brain's selection prompt grows and its own selection accuracy degrades.

**6. Closest existing alternative.** The v2 master map itself (Cycle 26) — this is the status quo. Externally: Anthropic's recommended workflow-first pattern; the "single agent" column of the single-vs-manager-vs-handoff comparison (dev.to, 2026): "one owner keeps the full context… usually lower cost and latency… simplest trace."

**7. Measurable prediction [SPEC].** On a task battery spanning 6 task types (chat, lookup, file ops, research, code, GUI), the fixed pipeline matches the template library (design b) within ±5pp task success at ≤0.5× the per-turn cost.

**8. Falsification criteria.** If any task class shows ≥15pp success gain from a structural change at ≤2× cost on a pre-registered battery, the fixed pipeline is falsified *as sufficient* — it remains the default, but the winning task class earns its own structure.

---

## 2. Design (b): Template library — pre-designed structures per task type

**1. Intended capability.** A library of ~6–10 declared structures (fast-QA, lookup, research, code, plan-and-execute, deep-verify, GUI-task…), each a DAG of M1–M7 modules with explicit termination conditions. A router selects the template at turn start; the template executes; the structure dissolves.

**2. Theoretical motivation.** Snell et al. (2024): difficulty routing cuts inference cost 3–10× vs sending everything to the max pipeline — applied here to *structure*, not just model size. The 2025 field consensus (from current literature): "workflows for orchestration + skills for specialization" — hybrids beat both monoliths and agent swarms. Templates are workflows; the brain remains the universal agent inside them.

**3. Assumptions.** (i) Task types are enumerable and stable — the library covers the distribution's head. (ii) Misrouting cost < structural gain on matched tasks. (iii) Templates can be authored once, versioned, and reused (they are code, not prompts — reviewable, testable).

**4. Computational cost.** One routing decision (a small classifier or heuristic — *not* a full LLM turn; see §5) + template execution. ~1.0–1.5× the fixed pipeline on matched tasks; cheaper than fixed on tasks where the fixed pipeline over-acts (e.g., fast-QA skipping the full loop).

**5. Failure modes.** (i) **Template misselection** — the wrong structure for the task; a *new* failure class the fixed pipeline doesn't have. (ii) Template sprawl: N templates × maintenance, versioning, interaction testing. (iii) Edge tasks fitting no template fall back to the fixed pipeline — which means the fixed pipeline must still exist and be maintained; the library is additive complexity, never a replacement. (iv) Templates ossify: the world changes, the library lags, and nobody notices because routing still "works."

**6. Closest existing alternative.** LangGraph supervisor pattern (supervisor node + conditional edges to specialists); AutoGen team composition; the "manager with specialists" column (dev.to 2026): "manager selects specialist input… typical risk: bad delegation or conflicting outputs."

**7. Measurable prediction [SPEC].** ≥10pp success gain on matched task classes (research, code) vs the fixed pipeline at ≤1.5× cost; misroute rate <10% on a labeled task-type set; template-sprawl held at ≤10 templates after 6 months of real usage.

**8. Falsification criteria.** If misroute rate exceeds 20% after tuning, or matched-task gains are <5pp, or the library exceeds 15 templates within 6 months (sprawl), the template library is falsified as worth its maintenance — collapse back to (a).

---

## 3. Design (c): Full dynamic composition — the brain designs the structure per task

**1. Intended capability.** At turn start, a composer (LLM) designs the module DAG for *this specific task* — including structures no template anticipates. Modules are typed (preconditions/postconditions); a deterministic validator checks the composed structure before execution (all side effects through M3→gate; termination conditions present; no cycles without exit predicates).

**2. Theoretical motivation.** The MoA lineage at task level: orchestrator decomposes, specialists execute, structures assemble dynamically (Broadhead 2025, "Society of Mind through MoA"). Automated agent generation literature — EvoAgent (2406.14228), MAS-Zero, SkillOrchestra (2602.19672), SwarmAgentic (2506.15672) — shows systems can design their own topologies. RouteMoA (2601.18130) shows dynamic routing without pre-inference overhead is achievable. The motivation is the long tail: tasks no template anticipated.

**3. Assumptions.** (i) The composer can be constrained enough to be safe — typed modules + validator. (ii) Composition benefit on novel tasks exceeds composition cost (latency + the validator's own complexity). (iii) Composed structures are auditable post-hoc via the session store's `structure.selected` events.

**4. Computational cost.** One composition turn (full LLM call) + validation + execution: ~2–4× per-turn cost vs fixed. The *debugging* cost is the real tax, not the tokens: every turn has a different architecture, so regression testing must test (task × structure) pairs, not tasks.

**5. Failure modes.** (i) **Composer failure** — invalid or incoherent structure; needs the validator, which is itself a new critical component (and a new thing to get wrong). (ii) **Composition as attack surface** — prompt injection could influence *structure design*, not just tool choice; a structure that routes around verification is a tier-3-equivalent event. Any single demonstrated instance = stop-ship. (iii) **Non-reproducibility** — same task, different structure, different outcome; the evaluation nightmare (was the failure the structure or the execution?). (iv) **The validator regress** — the validator's rules *are* a fixed architecture. Full-dynamic doesn't remove the fixed part; it moves it one level up and calls it something else.

**6. Closest existing alternative.** EvoAgent/MAS-Zero (automated agent generation); MoA proper (2406.04692, layered LLM stacks); the "agent-level learning" direction (train a routing policy on task outcomes — noted in the literature as the deeper research direction beyond agent-level routing).

**7. Measurable prediction [SPEC].** On novel/out-of-distribution task classes (no matching template), ≥15pp success over the template library; on in-distribution tasks, no gain (and the composer should *converge* to template-equivalent structures — a checkable prediction in itself).

**8. Falsification criteria.** If OOD gains are <10pp, OR >5% of composed structures fail validation, OR any prompt-injection instance alters structure (stop-ship, immediate), OR the composer does not converge to template-equivalent structures on in-distribution tasks (it should — if it invents novelty where none is needed, it's noise, not intelligence), then full dynamic composition is falsified for production. It remains a research instrument.

---

## 4. The skeptic's case — against dynamic composition

**4.1 The meta-decision problem.** Choosing the structure is itself a decision that can fail — and its failures are *worse* than the failures it replaces. One wrong tool call is recoverable; one wrong structure poisons every step downstream. Dynamic composition doesn't eliminate the meta-decision; it *escalates* it. (Note the fixed pipeline already has a meta-decision — the 8-strategy selector. The honest question is marginal: does structural adaptivity buy enough over strategic adaptivity to justify its larger failure blast radius? [SPEC] The prior says probably not for the common case.)

**4.2 The validator regress.** Design (c) needs a structure validator. The validator's rules — which module sequences are legal, which terminations are required — constitute a fixed architecture. You have not removed the fixed part; you have moved it up one level and given it a new name. Any safety argument for (c) bottoms out in the validator, which must be as carefully designed as the fixed pipeline it replaced.

**4.3 Debugging a shapeshifter.** A system whose architecture changes per task defeats the standard debugging loop. "It worked yesterday" is meaningless if yesterday's structure differs from today's. Regression suites must pin (task, structure) pairs — which is just the template library with extra steps. The session store's `structure.selected` events make this *auditable*, not *debuggable*.

**4.4 The empirical prior [HC].** Anthropic's field evidence: simple composable patterns beat complex frameworks in production. The 2025 industry consensus: workflows for orchestration, skills for specialization — *not* agent proliferation, and *not* runtime-designed topologies. Nobody in the surveyed literature runs full-dynamic composition in a production personal agent. That is evidence, not proof — but the burden of proof is on the novelty.

**4.5 The latency veto.** JARVIS is a voice-first assistant with ~2s turn budgets on the common path. A composition turn (full LLM call) before execution is disqualifying for the common path — dynamic composition can only ever be a *deep-path* option, never the default. This alone caps its value: it must earn its place on hard tasks only.

**4.6 When the complexity IS worth it — three gates, all must pass.** (i) The task distribution has a fat novel tail — measured, not asserted. (ii) The fixed pipeline demonstrably fails on that tail (falsification criterion from §1.8 met). (iii) Templates cannot cover it (falsification criterion from §2.8 met — misroutes stay high after tuning). Until all three are measured true, dynamic composition is research, not architecture.

---

## 5. The minimal version — two pipelines and a learned router

**The smallest step from fixed toward dynamic.** Not a module system. Not a library. Two pipelines:

- **FAST:** Recall → Judge → respond. Single brain turn; read-only tools at most; no gate round-trip beyond capability check; no critic, no verify loop. For "what's the capital…", "remind me…", simple lookups.
- **DEEP:** the full fixed pipeline (brain → gate → skills → brain) with verify + critic default-on. For everything else.

**The router:** a small classifier — not a full LLM turn. Options in cost order: (i) heuristics (question-word + verb analysis + length); (ii) a tiny distilled classifier trained on turn outcomes; (iii) the tier-0 BitNet model as a 1-token classifier. The router's job is *only* FAST-vs-DEEP, a binary decision with a safe default (uncertain → DEEP).

**Why this is the right minimal step [HC]:** it is Snell-style difficulty routing applied to structure; it is falsifiable in a weekend (A/B on 100 labeled tasks: FAST-vs-DEEP routing vs always-DEEP); its failure mode is bounded (a misrouted FAST turn just gets re-run DEEP — the cost of a mistake is one extra turn, not a poisoned structure); and it directly attacks the most expensive inefficiency of the fixed pipeline (over-acting on simple tasks) without adding any new architectural moving part.

**Pre-registered experiment:** 100 tasks (50 simple / 50 complex, labeled). Metric 1: success rate FAST-routed vs always-DEEP (non-inferiority margin 3pp on simple tasks). Metric 2: mean per-turn cost (target: ≥30% reduction on simple tasks). Metric 3: misroute rate (FAST chosen for a task needing DEEP — target <10%, each instance reviewed). Falsified if simple-task success drops >3pp or savings <15%.

---

## 6. Recommendation

**Stay fixed (design a) as the default. Test the template library (design b) on exactly two task classes. Keep full dynamic (design c) as a research instrument, not a production architecture. Build the minimal version (§5) first — this weekend-scale.**

The honest accounting:

| Design | Verdict | Reason |
|---|---|---|
| (a) Fixed pipeline | **SHIP** | The empirical prior, the latency budget, and the existing 8-strategy adaptivity all favor it. The null hypothesis stands until falsified. |
| (b) Template library | **TEST** | Worth an experiment on research + code tasks, where the fixed pipeline is weakest. Pre-registered falsification criteria in §2.8. |
| (c) Full dynamic | **RESEARCH ONLY** | The validator regress (§4.2) and the attack-surface expansion (§3.5.ii) are disqualifying for production until resolved. Build the validator + sandbox experiments; do not ship the composer. |
| §5 two-pipeline router | **BUILD FIRST** | Cheapest falsifiable step; bounded failure mode; directly attacks over-acting. |

**What would change this recommendation [SPEC]:** measured evidence that the task distribution's novel tail is fat AND the fixed pipeline fails there AND templates can't cover it (the three gates of §4.6). Until then, structural dynamism is a solution in search of a measured problem.

**Interaction with existing systems:** the 8-strategy selector (frontier-reasoning §5) already provides *strategic* adaptivity; the belief ledger (POMDP-lite) already provides *uncertainty-driven* adaptivity; the degradation ladder already provides *capability* adaptivity. Dynamic modules would add a fourth adaptivity axis. Four adaptive axes is a lot of moving parts for a system whose first virtue must be predictability. The burden is on each new axis to prove it earns its complexity — none gets in on elegance.

---

## Traceability

- Master map: `learn-v2-master-map.md` (the 12-box fixed architecture this cycle interrogates)
- Strategy adaptivity: `learn-frontier-reasoning.md` §5 (the 8-strategy table; strategies 5–7 default-on disciplines)
- Cost routing: Snell et al. 2024 (3–10× via difficulty routing); RouteMoA arXiv:2601.18130
- Fixed-workflow prior: Anthropic "Building Effective Agents" (Dec 2024) [HC — field-validated guidance]
- MoA lineage: arXiv:2406.04692; Rethinking MoA 2502.00674; automated generation: EvoAgent 2406.14228, MAS-Zero, SkillOrchestra 2602.19672
- Architecture comparison: single vs manager-vs-handoff (dev.to, 2026); "workflows + skills" 2025 consensus
- Enforcement invariant: threat model (the gate is substrate, never a module); brain-spec §0 (judgment vs enforcement)

**Honest completion (Rule 12):** Researched: master map + frontier-reasoning re-read in full; two web searches (dynamic composition literature, MoA/routing papers). Validated: arXiv IDs 2406.04692, 2502.00674, 2601.18130, 2406.14228, 2602.19672 cross-checked against search results (format-plausible, registry-unverified — flagged per Cycle 29 protocol). Saved: 1 file. Tested/Measured: nothing — design comparison only. Incomplete: the §5 experiment is designed, not run (needs the task battery — build work). Blocked: production data for the three gates (§4.6). Speculation: every forward prediction marked [SPEC]; the recommendation is argued, not proven.
