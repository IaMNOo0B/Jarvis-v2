# Frontier Reasoning for JARVIS — Phase 2, Track 1 Gaps

*Learning mission, 2026-10-19. LEARNING ONLY — no project files touched.*
*Coverage check first (Rule Zero): hierarchical planning, Soar impasse→chunk, calibration/RLCD, Conscio judgment layer — all SKIP (already covered). This file researches ONLY the four genuine gaps: search-based reasoning, belief-state/Bayesian tracking, causal reasoning, neuro-symbolic architectures.*

---

## 1. Search-Based Reasoning for Agents

### Mechanism

Instead of one greedy ReAct trajectory (act → observe → act…), generate **multiple candidate trajectories** and search among them:

- **Tree-of-Thoughts (ToT, Yao et al. 2023):** BFS/DFS over "thoughts"; LLM self-evaluates which branches are promising.
- **RAP — Reasoning via Planning (Hao et al., EMNLP 2023):** repurposes the LLM as its own *world model* (predicts next state) and runs MCTS over reasoning steps with UCB exploration. Key move: the reward comes from anticipated future states, not just immediate plausibility.
- **LATS — Language Agent Tree Search (Zhou et al. 2023):** MCTS + LLM value function + self-reflection on failure, adapted to acting (not just reasoning). Adds external environment feedback into the search.

### When it helps (measured)

| Benchmark | ReAct | LATS | Gain |
|---|---|---|---|
| HotPotQA (EM) | 67.0 | **81.1** | +21% |
| HumanEval (pass@1, GPT-3.5) | 56.9 | **83.8** | +47% |
| WebShop (score) | 53.8 | **75.9** | +41% |
| VisualWebArena (GPT-4o, tree search) | 18.9% | 26.4% | +39.7% relative |

RAP on LLaMA-33B beat CoT on GPT-4 by **33% relative** in plan generation — a smaller model with search beat a bigger model without it. That is the single most important number in this section.

### Cost

- Roughly **10× token budget** (one call → dozens; 8 branches × 4 levels × evaluators ≈ 32k tokens vs 3k baseline).
- LATS at k=50 trajectories: ~173k tokens on HotPotQA vs RAP's ~176–500k (LATS expands fewer nodes per success — more *principled* search = cheaper per win).
- Tree search is **10–20× slower** wall-clock than greedy decoding (liner.com review of "When is Tree Search Useful for LLM Planning").
- Parallelism helps: sibling nodes can be evaluated concurrently, so latency ≠ proportional to compute on parallel hardware.

### The critical caveat — the discriminator is everything

The paper "When is Tree Search Useful for LLM Planning? It Depends on the Discriminator" found:

- Tree search needs **≥90% discriminator accuracy** to beat simple re-ranking. Below that threshold it performs comparably or *worse*.
- Current LLM-based self-discriminators generally **do not meet 90%** even with environmental observations → marginal gains in practice.
- **The evaluator does not have to be another LLM. It can be the environment.** This is the decisive design insight: ToT-with-LLM-judge is weak; ToT-with-unit-tests (code), ToT-with-SQL-execution (queries), ToT-with-compiler (math proofs) is strong. Search is only as good as its verifier, and deterministic verifiers are free and perfect.

### Failure modes

1. **Weak discriminator → inverse scaling:** search over-exploits spurious signals; more search = worse answers (Chen et al. 2024; Gao et al. 2023).
2. **Overthinking:** on easy/short-horizon instances, large search budgets give nothing (Chen et al. 2025).
3. **Verification-dominated budget:** if evaluation is expensive, exploration depth collapses → bad accuracy–latency trade.
4. **Open-ended tasks:** without verifiable correctness, gains over strong decoding baselines are marginal.

### How to evaluate whether it improves results

- **Standardized Compute-Reporting Protocol (SCRP):** report B = (C_policy, C_eval, C_verify, T_wall) — policy compute, evaluation compute, verification overhead, wall time. Never compare methods without matched compute budgets.
- **Difficulty-stratified eval:** Snell et al. (2024) showed the answer depends on difficulty — easy: single pass wins; medium: best-of-N with small model matches big model; extreme: nothing compensates for capability gaps. Evaluate per-difficulty-tier, not in aggregate.
- **Ablate the discriminator:** run the same search with oracle vs LLM vs environment evaluator; the gap tells you whether search or verification is the bottleneck.

### Confidence: [HC] on benchmarks and cost model; [MC] on the 90%-discriminator threshold (one paper, needs replication)

### References

- Yao et al., "Tree of Thoughts: Deliberate Problem Solving with Large Language Models" (2023) — ToT
- Hao et al., "Reasoning with Language Model is Planning with World Model" (EMNLP 2023) — RAP. Code: github.com/Ber666/llm-reasoners
- Zhou et al., "Language Agent Tree Search Unifies Reasoning, Acting, and Planning" (2023) — LATS. arXiv:2310.04406
- Snell et al. (2024) — compute-optimal test-time scaling, difficulty routing (3–10× cost reduction via routing)
- "When is Tree Search Useful for LLM Planning? It Depends on the Discriminator" — discriminator-accuracy requirement
- Tree Search for Language Model Agents (VisualWebArena/WebArena results) — alphaxiv 2407.01476
- "When LLM Meets Tree Search: A Systematic View" (2025) — survey; backup strategy (max for binary verifiers, average for high-variance), 20–30% of compute to evaluation

### Unknowns

- Discriminator quality on *JARVIS's actual tool set* (file ops, Windows UI) — unmeasured until built.
- Whether a small local value model (distilled) can substitute for LLM-as-judge cheaply.
- Interaction with voice latency budgets (search is inherently non-streaming).

---

## 2. Belief-State Tracking & Bayesian Reasoning

### Mechanism

A POMDP models the world as hidden state *s*, with observations *o* and a **belief** *b(s)* = probability distribution over states, updated by Bayesian filtering after each action+observation. The policy maps *beliefs* (not states) to actions. The practical core:

- **Belief entropy as a trigger:** when uncertainty about a relevant state variable exceeds a threshold, insert an *information-gathering action* (verify, re-read, ask) instead of proceeding. The Spot-robot example: belief entropy > ~0.6 bits over the next cell → "peek" rotation instead of forward step.
- **Beliefs don't monotonically collapse:** stochastic transitions re-inject uncertainty every step. A system that assumes "more observations = certainty" stops verifying too early and acts on stale confidence.
- **Pinductor (Max Planck / Oxford, 2025):** an LLM *proposes candidate POMDP models* from a few observation-action trajectories and refines them against a belief-based likelihood score — matches methods that had privileged access to hidden state. LLMs as priors make POMDP learning sample-efficient.

### When it helps

- Tasks where **verification is cheap but errors are expensive**: "did the file save actually work?", "is the payment submitted or just queued?", "did the user mean delete or archive?"
- Long tool chains where early-state errors compound silently.
- Anywhere JARVIS currently *assumes* an action succeeded because no error was raised (a known v1 failure class).

### Cost

- Full POMDP planning (belief-tree search, e.g., Tru-POMDP replanning at 1Hz) is **overkill** for a personal agent: the state spaces are small but the modeling burden (transition/observation models per tool) is enormous.
- **POMDP-lite is nearly free:** maintain a small explicit "uncertainty ledger" — per-claim confidence + source + staleness — and gate consequential actions on it. This is a data structure, not a solver.

### Failure modes

1. **Model misspecification:** a wrong transition/observation model produces confidently wrong beliefs — worse than no model.
2. **Threshold tuning:** too-sensitive entropy triggers → verification spam, user annoyance; too-lax → the failures it was built to prevent.
3. **Overhead without payoff:** tracking beliefs over variables that never affect decisions is pure cost.

### How to evaluate

- **Calibration of the uncertainty ledger:** when JARVIS marks a claim "uncertain," is it actually wrong more often? (Brier score on flagged claims.)
- **Intervention rate vs error rate:** does adding verify-on-uncertainty reduce silent failures without doubling turn count?
- **Ablation:** same tasks with/without the ledger; measure undetected-error rate, not just success rate.

### Confidence: [HC] on the POMDP-lite verdict (practical, grounded in the failure analysis); [MC] on Pinductor's transferability (robotics/game domains, not desktop agents yet)

### References

- Kaelbling et al. (1998) — information-gathering actions in POMDPs (the "peek" pattern)
- "Learning POMDP World Models from Observations with Language-Model Priors" (2025) — Pinductor. Code: github.com/atomresearch/pinductor
- "Tru-POMDP: Task Planning Under Uncertainty via Tree of Hypotheses and Open-Ended POMDPs" (2025) — online belief-tree search, arXiv:2506.02860

### Unknowns

- Optimal entropy/uncertainty thresholds for JARVIS's tool set — must be tuned empirically.
- Whether the uncertainty ledger should feed the Conscio judgment layer's risk gate (integration design, not yet done).

---

## 3. Causal Reasoning

### Mechanism

Pearl's ladder of causation — three rungs, each needing information the rung below cannot supply:

1. **Association (seeing):** P(Y|X) — correlation, pattern recognition, next-token prediction. *All* unaided LLM reasoning lives here.
2. **Intervention (doing):** P(Y|do(X)) — "what happens if I *do* X?" Acting ≠ observing. Needs a causal model (DAG) or actual experiments.
3. **Counterfactual (imagining):** "Would this specific user have churned if they had *not* hit the broken page — given they did, and did churn?" Reasoning about alternatives to events that already happened. This is the language of explanation, blame, and debugging.

The three-step counterfactual procedure: **abduction** (infer the background conditions from what happened) → **action** (hypothetically intervene) → **prediction** (simulate forward).

### The key empirical finding

Microsoft's **RE-IMAGINE** framework (ICLR 2025 workshop) applies counterfactual mutations to reasoning benchmarks: **every evaluated model, including GPT-4-class systems, dropped ~20% accuracy** on counterfactual variants. Rung 3 is a genuine wall, not a slight incline. It also introduced measurable metrics: **Probability of Necessity (PN)** — was the cause necessary for the effect? — and **Probability of Sufficiency (PS)** — was it sufficient? These let you distinguish models that correlate surface features from ones that capture causal structure.

### When it helps for JARVIS

- **Debugging and diagnosis:** "would the bug still occur if I changed X?" — the failure-analysis loop. Causal framing turns "the setting broke it" (correlation) into "the setting broke it *because* the write path assumes X, which fails when Y" (mechanism).
- **Post-mortems:** PN/PS discipline for the autopsy habit — was the echo-guard bug *necessary* for the self-triggering? (Yes.) Was it *sufficient*? (Yes — dead code alone caused it.) High PN + high PS = true root cause.
- **Intervention planning:** before a multi-step action, ask the Rung-2 question explicitly: "if I *do* this sequence, what breaks?" rather than pattern-matching past successes.

### Cost

- Full do-calculus is heavyweight; **the lite version is a reasoning discipline, not a solver**: for each diagnosis, state the assumed causal graph in words, then run abduction→action→prediction explicitly.
- Where the environment permits *actual* intervention (sandboxes, dry-runs, test suites), Rung 2 is free — just do the experiment. JARVIS's sandbox is a causal laboratory.

### Failure modes

1. **Confounding:** attributing an effect to X when Z causes both (the classic trap; LLMs are especially prone because training data is pure Rung 1).
2. **Counterfactual hallucination:** inventing plausible-but-false alternate histories — needs grounding in the actual event log.
3. **Overkill:** not every "why is this slow?" needs a DAG; reserve for recurring or high-stakes failures.

### How to evaluate

- **RE-IMAGINE-style mutation testing:** take JARVIS's diagnostic outputs, apply counterfactual mutations, measure accuracy drop. Smaller drop = more genuinely causal reasoning.
- **PN/PS scoring on post-mortems:** for each claimed root cause, score necessity and sufficiency against the evidence. Track the fraction of "root causes" that survive both.
- **Intervention success rate:** of the fixes proposed from causal analysis, what fraction actually resolve the issue on first try?

### Confidence: [HC] on the ladder framing and the RE-IMAGINE 20% finding; [MC] on PN/PS as operational metrics (new, limited validation)

### References

- Pearl & Mackenzie, *The Book of Why* (2018) — the ladder, do-operator, do-calculus
- Bareinboim et al. — Causal Hierarchy Theorem (lower-rung data cannot answer higher-rung questions)
- RE-IMAGINE framework (ICLR 2025 workshop) — counterfactual benchmark mutation, PN/PS metrics
- "A Critical Review of Causal Reasoning Benchmarks for LLMs" (arXiv:2407.08029) — most benchmarks only test Rung 1
- Forney, Pearl & Bareinboim (2017) — counterfactual data fusion in bandits (observational + experimental + counterfactual beats Thompson sampling)

### Unknowns

- Whether explicit causal-graph elicitation from the LLM (ask it to draw the DAG) improves diagnosis vs implicit reasoning — untested.
- Integration with the memory system: storing *causal* links between events, not just temporal ones.

---

## 4. Neuro-Symbolic Architectures

### Mechanism

The canonical pattern, validated at the highest levels of competition mathematics:

- **LLM proposes → symbolic system verifies → counterexample feeds back → repeat.**
- *AlphaProof* (DeepMind, 2024): LLM proposes proof steps, **Lean theorem prover** verifies → IMO silver medal.
- *AlphaGeometry*: same pattern on geometry → IMO gold.
- **CEGIS loop (LLM + Z3):** LLM as learner proposes candidate solutions; Z3 SMT solver formally checks them; counterexamples go back into the prompt. The LLM even translates natural-language action descriptions ("pick up", "stack") into formal Z3 constraints.
- **SPCA framework (2026):** sense → LLM-to-PDDL symbolic description → heuristic planner generates valid plan → LLM converts to code → compile + simulate to validate → local repair on failure. ~71–75% task completion on robot tasks.
- **Propose–verify–repair** with a **guaranteed-safe symbolic fallback**: if the neural proposer produces nothing verifiable, fall back to a slow-but-correct classical plan. The fallback is not optional.

### When it helps

- Anywhere correctness is **checkable but not generatable** by the LLM: code (tests/type-checkers), plans (PDDL validators), configs (schema validators), math (provers), permissions (policy checkers).
- This is *already* JARVIS's "verify before claiming" doctrine — neuro-symbolic gives it a formal name and a literature.
- Highest ROI where the verifier is **deterministic and cheap**: Pydantic schemas (already planned as the R2 enforcement point), test suites, Z3 for constraint problems, PDDL for multi-step plans with ordering constraints.

### Cost

- The verifier must be *built* (schemas, test suites, PDDL domain definitions) — upfront modeling cost per domain.
- Repair loops add latency (propose → fail → repair → re-verify), but each iteration is cheap when the verifier is fast.
- Translation risk: the LLM must faithfully encode the problem into the formal system; a mistranslated spec verifies the wrong thing perfectly.

### Failure modes

1. **Spec mistranslation:** formally verified against the wrong specification — the most dangerous failure because it *looks* rigorous.
2. **Verifier gaps:** the symbolic checker doesn't cover the actual failure mode (tests pass, bug ships).
3. **No fallback:** neural proposer fails on hard cases and there is no safe default → crash or, worse, unverified output presented as verified.

### How to evaluate

- **Verification coverage:** fraction of high-stakes tool actions that pass through a deterministic checker. Target: 100% of irreversible actions.
- **Repair-loop statistics:** how often does the first proposal fail verification? (Measures proposer quality.) How often does repair succeed within N rounds? (Measures loop viability.)
- **False-verification rate:** deliberately inject spec mistranslations; does the pipeline catch them or rubber-stamp?

### Confidence: [HC] on the propose→verify→repair pattern (multiple independent validations incl. IMO medals); [MC] on PDDL-for-desktop-agents (robotics-validated, desktop unproven)

### References

- DeepMind AlphaProof / AlphaGeometry (2024) — LLM + Lean prover, IMO silver/gold
- "Neuro Symbolic Reasoning for Planning: CEGIS using LLMs and Satisfiability Solving" — alphaxiv 2309.16436 (LLM + Z3 loop)
- "Robot Planning via LLM Proposals and Symbolic Verification" (2026) — SPCA framework, doi:10.3390/make8010022
- The AI Compendium: Neurosymbolic AI survey (theorem proving, code verification, AI scientist systems)

### Unknowns

- PDDL domain definitions for JARVIS's actual tool set — modeling work not yet done.
- Whether Z3-scale verification is ever needed for a personal agent, or schemas+tests suffice (hypothesis: the latter).

---

## 5. Comparative Decision Table — Which Reasoning Strategy, When

| # | Strategy | Mechanism (one line) | Use when… | Skip when… | Relative cost | Key failure mode | How to know it's working |
|---|---|---|---|---|---|---|---|
| 1 | **Single-pass ReAct** | Greedy act→observe loop | Easy/medium tasks; latency matters (voice) | High-stakes or verifiable-hard tasks | 1× (baseline) | Silent compounding errors | Task success rate; undetected-error rate |
| 2 | **Best-of-N / self-consistency** | N independent samples, vote/rerank | Medium difficulty; no verifier available | Easy tasks (overthinking); hard tasks (capability gap) | N× (N=16–64 sweet spot) | Reward hacking on weak ranker | Per-difficulty-tier gains (Snell) |
| 3 | **Tree search (ToT/BFS)** | Branch + LLM-judge prune | Combinatorial reasoning, no environment | Discriminator <90%; open-ended tasks | ~10× tokens | Inverse scaling on weak judge | SCRP reporting; ablate judge quality |
| 4 | **MCTS + environment verifier (LATS/RAP)** | Search guided by real feedback | Hard + **verifiable** tasks (code, plans, web) | No cheap verifier exists | ~10× tokens, 10–20× slower | Verification-dominated budget | Benchmarks: +21–47% (LATS numbers) |
| 5 | **Belief ledger (POMDP-lite)** | Track uncertainty; verify when high | Cheap verification, expensive errors | Uncertainty never affects decisions | ~1× (data structure) | Threshold mis-tuning → spam or misses | Calibration: flagged claims actually wrong more often |
| 6 | **Causal post-mortem** | Abduction→intervention→prediction; PN/PS | Recurring failures; debugging; diagnosis | One-off trivial bugs | ~1× (discipline) | Confounding; hallucinated counterfactuals | PN/PS survival rate; first-try fix rate |
| 7 | **Neuro-symbolic verify** | LLM proposes; deterministic checker disposes | Irreversible/high-stakes actions; checkable domains | Checker doesn't exist; spec untranslatable | 1–3× (verifier cheap) | Spec mistranslation (verified wrong thing) | 100% of irreversible actions checked; repair-loop stats |
| 8 | **Escalate (model/tool/human)** | Route up on uncertainty | All strategies exhausted or risk too high | — (this is the backstop) | Variable | Escalation fatigue | Escalation precision: was it truly needed? |

### The routing rule (for JARVIS's brain)

```
1. Classify: difficulty (easy/med/hard) × verifiability (yes/no) × reversibility (yes/no) × latency budget (voice/interactive/batch)
2. Easy OR voice-latency-critical → Strategy 1 (single-pass ReAct)
3. Medium, no verifier → Strategy 2 (best-of-N, small N)
4. Hard + verifiable + batch budget → Strategy 4 (LATS-style MCTS, environment as judge)
5. Hard + verifiable + interactive budget → Strategy 3 with tight node cap, or Strategy 2
6. Hard, no verifier → Strategy 2 + Strategy 8 (escalate: stronger model or human)
7. ALWAYS, in parallel: Strategy 5 (belief ledger) + Strategy 7 (neuro-symbolic verify on irreversible actions) + Strategy 6 (causal post-mortem on failure)
8. NEVER: Strategy 3/4 with an LLM-only judge below 90% discrimination — worse than useless
```

### Cross-cutting insights

1. **The verifier is the strategy.** Search without a good discriminator is expensive noise; search with an environment verifier is the biggest measured gain in the literature (+21–47%). Build verifiers before building search.
2. **Strategies 5, 6, 7 are disciplines, not compute** — they cost ~1× and compose with everything. They should be default-on; 1–4 are the compute dial.
3. **Difficulty routing beats uniform brilliance** (Snell et al.): adaptive allocation cuts inference cost 3–10× vs sending everything to the max pipeline.
4. **Belief tracking and causal reasoning are the same instinct**: know what you don't know (belief), and know *why* things happened (cause). Together they turn the failure-analysis habit from a document into a runtime system.
5. **Neuro-symbolic is the formalization of "verify before claiming"** — JARVIS's existing doctrine, now with IMO-medal evidence behind it.

---

## 6. Remaining unknowns (ranked)

1. Discriminator accuracy on JARVIS's real tool set — unmeasured; gates all of Strategy 3/4.
2. Uncertainty thresholds for the belief ledger — must be tuned on real usage.
3. Whether PDDL/Z3-scale verification is ever needed vs schemas+tests (bet: schemas+tests suffice).
4. Explicit causal-graph elicitation vs implicit reasoning — untested.
5. Small distilled value model as cheap judge — unexplored.
6. Search under voice latency budgets — inherently non-streaming; needs architecture work.
7. Causal links in the memory system (not just temporal) — design work pending.
