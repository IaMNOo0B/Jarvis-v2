# Bounded Rationality for JARVIS — Satisficing Under Strict Bounds

**PHASE INFINITY — Research Cycle 6.** Written 2026-10-19. LEARNING ONLY — no project code touched, no experiments run, no claims fabricated.

**Research question:** How should JARVIS make good-enough decisions under strict resource bounds?

**Answer in one paragraph:** JARVIS should not maximize answer quality — it should satisfice against explicit aspiration levels per task tier, treating every unit of reasoning as a purchase: continue only while myopic value-of-information stays positive, stop on confidence or hard budget, and prefer interruptible (anytime) components that return a valid best-so-far answer when the budget gate fires. The controller that runs this is a tiny metalevel (router + monitor) whose own cost must stay ≪ the object-level budget. Everything else in this file is the machinery for that sentence.

**§19 protocol followed:** audit (§1) → question (§2) → research (§3) → compare (§4) → derive (§5) → validate (§6) → integrate (§7) → record (§8) → reassess (§9).

**Confidence tags (state-of-knowledge, not the question):** [VC] >95% · [HC] 80–95% · [MC] 60–80% · [SP] 40–60% · [UK] unknown. Design proposals are marked **DESIGN** — they are derivations from the research, not measured facts.

---

## 1. Audit — what prior cycles already established (referenced, not re-researched)

| Prior file | What it contributes to this cycle | Status |
|---|---|---|
| `learn-frontier-reasoning.md` | The 8-strategy decision table (ReAct → best-of-N → tree search → MCTS+verifier → belief ledger → post-mortem → neuro-symbolic → escalate) + routing rule: voice-latency-critical → Strategy 1; never Strategies 3/4 with an LLM-only judge below 90% discrimination. "The verifier is the strategy." | Accepted as the **menu**. This cycle builds the **controller** that drives it. |
| `learn-math-for-jarvis.md` | Value of information ("information has no value unless it can change a decision"), asymmetric loss for the approval gate, the Beta-Bernoulli belief ledger. | Accepted as the **stopping machinery's math**. |
| `learn-inference-frontiers.md` | Prefill vs decode asymmetry, the 4k-physical strategy, "measure-don't-assume." Budgets on the 2060 are physical, not decorative. | Accepted as the **hardware grounding** for budget numbers. |
| `learn-underspecification.md` | The 8-step ask/act/escalate rule with cost-asymmetric VoI and hard gates. | Handles *missing-information* decisions. This cycle handles *reasoning-effort* decisions — sibling controllers, shared VoI math. |
| `learn-research-frontiers.md` | Inference-time scaling: small model + test-time compute beats 14× larger model on easy problems; budget compute by task tier; never best-of-N on the voice loop. | Accepted as the **scaling evidence**. |
| `learn-open-problems.md` | Problem #7 (this cycle's target): allocating reasoning effort under a strict latency budget — `FIELD`, score 60, [HC]. Notes difficulty estimation as the hard sub-problem. | Target problem. §9 updates its status. |

**Genuinely new in this cycle:** the Simonian frame, the contract/interruptible distinction and subsystem map, the three-gate stopping rule, the metacognition/difficulty-estimation literature (routing papers), and the tier × modality budget matrix. None of these existed in prior files.

---

## 2. Question

Open-problem #7: *Given a hard latency budget (voice <300ms, interactive <3s, batch unbounded), how should the agent allocate reasoning compute — and when does more thinking merely add latency, cost, and unsupported conclusions?*

Decomposed into the five investigations below.

---

## 3. Research

### 3.1 The conceptual frame — Simon's bounded rationality and satisficing

Herbert Simon's bounded rationality (Simon 1955, 1956; *Models of Man*, 1957) starts from the observation that optimal decisions are **uncomputable under bounds**: limited information, limited processing capacity, limited time [HC — encyclopedia.com; scales.arabpsychology.com]. The behavioral consequence is **satisficing** (satisfy + suffice): set an **aspiration level** — a threshold of acceptability — and search sequentially until the *first* alternative meets it, then stop. "The players, instead of seeking for a 'best' move, need only to look for a 'good' move" (Simon 1955, p. 108) [HC].

Three properties matter operationally for JARVIS [HC]:

1. **Deliberation costs are part of rationality, not outside it.** Simon's frame includes search cost in the rationality calculation: if the effort to find a marginally better option exceeds the expected benefit of the improvement, stopping is the rational act — not a failure mode [HC — db.arabpsychology.com]. This is the philosophical parent of the VoI stopping rule in §3.3.
2. **Aspiration levels are adaptive, not fixed.** If the environment is rich in options, the level rises; if sparse, it falls. Preferences are endogenous to experience [HC — encyclopedia.com]. Operationally: JARVIS's acceptance thresholds must adapt from observed outcomes (the belief ledger records them), not be frozen constants.
3. **Procedural rationality over substantive rationality.** What matters is whether the *procedure* is efficient given the feedback, not whether the outcome was globally optimal [HC]. This is exactly the posture for the controller: we cannot verify JARVIS found the best plan; we can verify its procedure was bound-respecting and satisficing.

**Operational meaning of "good enough with guarantees about the bound" [DESIGN]:** For each task tier, define an aspiration level as a *testable acceptance criterion* (e.g., "tool call returned schema-valid output and the belief ledger holds the key claim at ≥0.8"). The controller's guarantee is never "this was optimal" — it is: **"this met the tier's acceptance criterion within the tier's budget, using a procedure that stops when the marginal value of more thinking goes negative."** That is the only guarantee a bounded agent can honestly give, and it is the right one.

### 3.2 Anytime algorithms — contract vs interruptible, and the v2 subsystem map

**Definitions** [HC — Russell & Zilberstein 1996, via ar5iv 1810.11291 and Bernstein–Perkins–Zilberstein–Finkelstein, AAAI 2002; origins Horvitz 1987/1989, Dean & Boddy 1988]:

- **Contract algorithm:** takes its time allocation as an *input parameter*. If interrupted before the allocation completes, the output may be meaningless. Easier to design and maintain.
- **Interruptible algorithm:** can be queried at *any* moment and must always report its current (not necessarily optimal) solution; quality improves with time. The canonical example: branch-and-bound search keeping the running best-so-far.
- Any contract algorithm can be converted to an interruptible one by repeatedly running it with a **geometric (doubling) schedule** of increasing time allocations; the worst-case overhead over the contract version is a small constant (the optimal single-processor "acceleration ratio"; commonly cited as ~4×) [HC on the construction; MC on the ~4 constant].

**Performance profiles** — each anytime algorithm has a profile describing output quality as a function of time [HC — AIMA metareasoning paper, aima.eecs.berkeley.edu]. The metalevel's job (which algorithm to run, when to stop) becomes "fairly trivial" *given* the profile [HC]. The hard part is obtaining the profiles — they must be measured (open-problem #7's resolution experiment is exactly a profile-measurement experiment).

**The v2 subsystem map — anytime or not [DESIGN, derived from the definitions]:**

| v2 subsystem | Anytime? | What "best-so-far" means on interruption |
|---|---|---|
| Dense/sparse retrieval | **Yes (interruptible)** | Return top-k retrieved so far; quality improves as more of the index is scanned |
| Re-ranking of candidates | **Yes** | Return current ranked list; each additional scoring pass refines order |
| ReAct tool loop | **Interruptible at step boundaries** | Return the last *completed* step's state + partial trajectory; never mid-tool-call |
| Best-of-N sampling | **Contract** | Needs all N samples before voting; make interruptible by switching to *sequential* sampling with running majority vote (a contract→interruptible conversion, cf. the doubling-schedule idea) |
| Tree search / MCTS | **Yes** | Return best leaf/node value found so far (branch-and-bound pattern) |
| Plan synthesis (full) | **Mostly no** | A half-plan is not executable. Exception: hierarchical plans — a *committed prefix* of subgoals is a valid partial answer |
| Memory recall (vector) | **Yes** | Nearest-neighbors-so-far; more probe time → better recall |
| Context compression / summarization | **Yes** | Quality improves with passes; first pass is already a valid summary |
| Symbolic/neuro-symbolic verification | **No (mostly)** | Boolean or per-invariant verdicts are all-or-nothing; *but* decomposable into per-invariant checks → quasi-anytime if invariants are ordered by importance |
| Few-shot self-verification (AutoMix-style) | **Contract** | Needs the full draft answer before judging it |
| Belief-ledger update | **Yes (trivially)** | It's a data structure; always in a valid state |
| The router itself | **No — and must not be** | The metalevel decision must be a cheap contract computation (see §3.4: tens of ms) |

**Design rule from the map:** put interruptible components on the paths where the budget gate is most likely to fire (voice, interactive). Contract components are allowed only where the budget is generous (background) or where their quantum is tiny relative to the budget.

### 3.3 Stopping criteria — the three-gate rule

The literature gives three stopping mechanisms; JARVIS needs all three, in series.

**Gate A — VoI-based (marginal value of computation ≤ 0).** Rational metareasoning (Russell & Wefald 1989, 1991; Horvitz 1987/1989; rooted in Howard 1966 information-value theory and Good 1971 "Type II rationality") treats a computation as an action whose benefit is the expected improvement in the external decision and whose cost is the delay [HC — AIMA metareasoning paper]. The stopping criterion: **stop when no further computation has positive expected net value** — Russell & Wefald's DTA* stops search when no node expansion has non-negative expected utility, and expands the "hardest" node first [HC — Russell & Wefald ch. 4–5 summaries]. In practice the field uses **myopic (greedy, depth-one) metareasoning**: estimate only the value of the *next* computation step [HC — AIMA paper: "almost all systems to date have adopted a myopic strategy"]. Myopic VoI is cheap enough to compute online with little overhead; exact VoI is as intractable as the object-level problem [HC — cs.berkeley.edu/ijcai95 paper].

For JARVIS, the myopic VoI estimate has a concrete, cheap form [DESIGN]: **if the current top-two candidate actions cannot be reordered by any plausible single unit of further computation, the marginal VoI is ~0 — stop.** This is the "information has no value unless it can change a decision" principle from `learn-math-for-jarvis.md`, applied to the reasoning loop itself. Concretely: the controller tracks the belief gap between the leading plan/tool-call and its best challenger (beliefs from the Beta-Bernoulli ledger); when the gap exceeds what one more search/sample step could plausibly close, Gate A fires.

**Gate B — budget-based (hard caps).** Token cap and wall-clock cap per (tier × modality). This is the contract-algorithm discipline: every reasoning strategy runs under an explicit allocation. When the cap fires, interruptible components return best-so-far (§3.2); contract components must have quanta small enough that overshoot is bounded. **Budget caps are the backstop that makes the other two gates safe to be approximate** [DESIGN].

**Gate C — confidence-based (aspiration reached).** The belief ledger's posterior on the chosen action crosses the tier's aspiration threshold → stop and act. This is Simon's satisficing made computational: the aspiration level *is* Gate C's threshold [DESIGN].

**The combined stopping rule [DESIGN — the core deliverable of this cycle]:**

```
At each reasoning step t, with current best answer a_t:
  STOP and return/commit a_t if ANY fires:
    (C) CONFIDENCE:  P(a_t is correct) ≥ τ(tier, stakes)        # aspiration reached
    (A) VOI:         E[Δquality | one more unit of compute] ≤ cost(unit)  # myopic; nothing left to gain
    (B) BUDGET:      tokens_used ≥ T_max  OR  wall_clock ≥ L_max          # contract honored
  Otherwise continue under the router's selected strategy.
```

**Aspiration dynamics [DESIGN, from Simon's adaptivity]:** τ is not constant. The belief ledger logs (τ_used, outcome) per tier; periodically, τ adapts: if budget gates fire constantly *and* outcomes succeed, τ was too demanding → lower it; if confidence-gated actions succeed far above the required rate, τ was too lax → raise it. "Aspiration levels are endogenous to experience" — the controller learns its own standards. **Until the ledger has data, τ starts conservative (high) on irreversible actions and moderate elsewhere** (fail-safe direction: over-verifying wastes compute; under-verifying causes the failures the autopsy catalogued).

**Why three gates and not one:** VoI alone needs performance profiles we don't have yet (unmeasured — §9); confidence alone drifts without grounding; budgets alone waste compute on easy wins and starve hard ones. The three gates cover each other's failure modes. **And critically: the gates must be cheap.** The AAAI-2008 workshop note warns explicitly: metalevel monitoring must be sensitive to its own cost; the myopic rule "stops the computation when the marginal value of computation becomes negative — can be computed online with little overhead" [HC — cdn.aaai.org WS-08-07]. If the controller ever costs more than a few percent of the reasoning budget, it has become the problem it was built to solve.

### 3.4 Metacognition — the difficulty-estimation problem (and its honest limits)

Routing to a reasoning strategy requires estimating difficulty **before** solving — the recursion at the heart of this cycle.

**What the literature actually does [HC]:**

- **Snell et al. (2024), arXiv:2408.03314** — the canonical result: difficulty estimated via pass@1 over (expensive) 2048 samples; per-difficulty-bin, the best test-time strategy is chosen on a validation set (easy → iterative refinement of one solution; hard → beam search with PRMs); the compute-optimal adaptive strategy is up to **4× more efficient than best-of-N**, and on easy/intermediate problems a small model with test-time compute **beats a 14× larger model** [HC — multiple corroborating sources]. Two honest caveats from the same literature: the difficulty-estimation cost is real, but **can be amortized by reusing the same samples for search** [HC]; and **beam search overfits the PRM on easy problems** — the strategy must match the difficulty, not just the budget [HC].
- **Predictive routing (RouteLLM, Ong et al.)** — a ~110M-parameter BERT-class classifier predicts which tier wins for a prompt in **10–30ms**, trained on ~65K Chatbot Arena battles plus ~$700 of GPT-4-judge-augmented labels; reported ~85% cost reduction on MT-Bench at ~95% of GPT-4 quality [MC — secondary sources (seangeng, letsdatascience); benchmark-specific]. NVIDIA ships an off-the-shelf prompt-task-and-complexity classifier (DeBERTa-v3-base) claimed at 94–99% depending on dimension [SP — single blog source, unverified].
- **Cascade routing (FrugalGPT, Chen et al.)** — tries cheap models first, escalates on a scoring function; up to **98% cost reduction** matching the best model [HC — widely corroborated]. But structurally: **cascade doesn't predict, it tries and retries — which doubles latency and breaks streaming. Great for batch, bad for chat** [HC — structural, from seangeng].
- **Post-generation routing (AutoMix, Aggarwal et al., arXiv:2310.12963, NeurIPS 2023)** — small model generates, then a **few-shot self-verification step (framed as entailment)** estimates reliability; because self-verification is noisy, a **POMDP-based router** decides escalation rather than a hard threshold; >50% cost reduction at comparable performance across five models and five datasets [HC — from the paper's abstract].

**What this means for JARVIS's metalevel [DESIGN]:**

1. **The live path uses predictive routing, never cascades, never LLM-judge routers.** The numbers force it: a BERT-class router decides in ~10–30ms; an LLM-as-judge router adds ~1–5s [SP on exact ms, HC on the order-of-magnitude gap]; a cascade doubles latency and breaks streaming. On the voice path (<300ms barge-in), only the classifier fits. **NEVER run an LLM-judge router on the live path** [VC — follows from the latency arithmetic].
2. **Don't hard-threshold a noisy signal — that's AutoMix's lesson.** Self-verification/confidence estimates are noisy; the escalation decision should be POMDP-flavored: escalate on (low confidence × high stakes), not on a single threshold [DESIGN, grounded in AutoMix HC].
3. **The honest limits [UK/MC]:**
   - Snell et al. explicitly note **crossover points are task-specific and must be measured** — JARVIS's difficulty distribution for Owais's real usage is unmeasured (open-problem #2). The controller ships with literature-shaped priors and a measurement plan, not with tuned thresholds.
   - RouteLLM-style classifiers are trained on **chat preference data**; transfer to **agentic tool-calling difficulty** is unvalidated [SP]. A classifier trained on the golden set (open-problem #4) is the fix; until then, task-type heuristics (tool count needed, reversibility, stakes) are the pragmatic prior.
   - Difficulty estimation is itself a bounded-rationality problem: the estimator's budget must be ≪ the decision's budget, or metacognition becomes the tax it was meant to avoid.

### 3.5 Latency budgets per modality — the tier × modality matrix

**Modality latency targets** (design targets from the v2 architecture context; treat as requirements, not measurements):

| Modality | Response target | What it implies |
|---|---|---|
| **Voice loop** | <300ms barge-in response; <1s turn start | No multi-step reasoning on the live turn. Single-pass ReAct (Strategy 1) only; decode must stream; the router itself must be ≤ ~30ms |
| **Chat / interactive** | Seconds acceptable | Strategy 1 default; Strategy 2 (best-of-N, small N) and capped Strategy 3 allowed; one verification pass affordable |
| **Background** | Minutes acceptable | Full table including Strategy 4 (MCTS+verifier) and cascades; difficulty estimation can afford sampling |

**The tier × modality budget matrix [DESIGN — budgets as formulas, not invented constants]:**

| | **Voice** (<300ms / <1s) | **Chat** (seconds) | **Background** (minutes) |
|---|---|---|---|
| **Easy** | S1. Aspirations low; Gate C fires on first valid draft. Router: classifier only. | S1. Gate C primary. | S1 or cheap cascade. |
| **Medium** | S1 only. Extra compute forbidden by budget — the bound *is* the strategy choice. Gate B dominates. | S2 (small N) or S1+verify. Gates A+C. | S2 / S3 with node cap. Gates A+C, generous B. |
| **Hard** | S1 + **deferral**: voice gives an immediate acknowledgment and the task continues in background (modality handoff — the voice budget cannot contain hard reasoning, so the architecture must route around it, not through it). | S3 with tight node cap, or S2; S8 if no verifier. Gates A+B+C. | S4 (MCTS + environment verifier) if verifier exists; else S3. Full gate set; B generous. |
| **High-stakes / irreversible** | S1 to *refuse-or-defer* safely; S7 (neuro-symbolic verify) on the proposed action before any execution. Never execute blind on voice. | S1 + S7 mandatory on irreversible actions; S8 (human) when uncertainty high. Asymmetric loss applies. | S7 + S8. Budgets generous; correctness dominates latency. |

**Always-on, all modalities, ~1× cost:** Strategy 5 (belief ledger) + Strategy 6 (causal post-mortem on failure) [from the prior routing rule — unchanged].

**NEVER rules (carried forward, now with the controller's justification):**
- Never Strategies 3/4 with an LLM-only judge below 90% discrimination — below that, search is expensive noise (prior rule; the controller enforces it by checking the discriminator's measured accuracy before selecting S3/S4 — a *precondition* on the strategy, not a runtime decision).
- Never best-of-N on the voice loop (prior rule; §3.4 shows the router-classifier is the only live-path mechanism that fits).
- Never let the metalevel (router + gates) exceed ~5% of the modality's time budget. On voice that's ~15ms for the stop-check per step — the gates must be arithmetic on ledger values, not model calls.

**On token budgets:** this cycle does not invent token constants. The controller takes `T_max(tier, modality)` as a **measured parameter**: `T_max = (L_max − fixed_overhead) / ms_per_token`, where `ms_per_token` comes from the 2060 shootout (open-problem #1) and `fixed_overhead` from the voice-pipeline measurements (open-problem #6). Until measured, the controller runs on wall-clock budgets only, with conservative token guards. **Inventing the numbers here would be exactly the "measure-don't-assume" violation `learn-inference-frontiers.md` forbids.**

---

## 4. Compare — how this cycle relates to the prior studies

| Prior study | Relationship to this cycle |
|---|---|
| `learn-frontier-reasoning.md` | **Menu vs controller.** That file lists the 8 strategies and a routing rule. This file designs the *runtime controller* that executes the routing rule under bounds: the router (which strategy), the monitor (the three gates), and the modality matrix (what's legal where). If frontier-reasoning is the strategy table, this cycle is the waiter, the kitchen timer, and the house rule that you don't order the tasting menu when the train leaves in ten minutes. |
| `learn-math-for-jarvis.md` | **Supplies the math.** VoI ("no value unless it can change a decision") becomes Gate A; the Beta-Bernoulli belief ledger becomes the substrate for Gate C and the aspiration-dynamics loop; asymmetric loss shapes τ on irreversible actions. This cycle adds nothing to the math — it *spends* it. |
| `learn-underspecification.md` | **Sibling controller.** The 8-step ask/act/escalate rule governs decisions under *missing information*; this cycle's controller governs decisions under *limited reasoning effort*. They share the VoI formalism and the escalation backstop (Strategy 8), and both must run within the same modality budgets. A future integration pass should merge their gate logic into one metalevel. |
| `learn-inference-frontiers.md` | **Grounds the budgets.** Prefill/decode asymmetry and the 4k-physical strategy determine what `T_max` can physically be on the 2060. This cycle deliberately refuses to invent token constants — the budgets are parameters filled by that file's measurement program. |
| `learn-research-frontiers.md` | **Supplies the scaling evidence.** Snell et al.'s compute-optimal allocation is the empirical backbone of "budget compute by task tier"; this cycle adds the *pre-decision* difficulty-estimation machinery and the stopping rules that make the allocation executable at runtime. |

**What this cycle does NOT redo:** the strategy table, the VoI formalism, the belief ledger, the hardware numbers, the test-time scaling results. All referenced, none re-derived.

## 5. Derive — the controller design (the deliverable)

**The controller's job, stated once:** *maximize expected decision utility under the bound* — not answer quality, not token efficiency, not elegance. Every design choice below serves that objective.

### 5.1 Architecture: router + monitor, both cheap

- **Router (predictive, pre-generation):** a tiny classifier (BERT-class, tens of ms) maps (task features, tier, modality) → strategy from the 8-strategy table, subject to the modality matrix's legality constraints (§3.5) and strategy preconditions (S3/S4 require a measured ≥90% discriminator; S4 requires an environment verifier). Task-type heuristics (tool count, reversibility, stakes) are the prior until a golden-set-trained classifier exists.
- **Monitor (the three gates, §3.3):** evaluated per reasoning step; all three gates are arithmetic on ledger values — no model calls. Budget for the monitor: ≤5% of the modality's time budget.
- **Escalation (Strategy 8):** the backstop. Triggered POMDP-style (AutoMix lesson): on (low confidence × high stakes), or when all strategies are exhausted, or when the budget gate fires on a high-stakes task without the aspiration being met. Escalation targets: stronger model → human, in that order.
- **Aspiration ledger:** logs (tier, τ_used, gates fired, outcome) per decision; τ adapts per §3.3. This is the controller's learning loop — procedural rationality improving the procedure.

### 5.2 The decision flow (one turn)

```
1. Classify: difficulty (heuristic/classifier) × verifiability × reversibility × modality
2. Router selects strategy S from the table, filtered by the modality matrix;
   S3/S4 only if discriminator ≥90% measured, S4 only if environment verifier exists
3. Set budget: L_max (wall-clock, from matrix), T_max (tokens, when measured)
   Set aspiration τ(tier, stakes)
4. Run S as contract (budget) / interruptible (best-so-far) per the anytime map
5. After each step, evaluate gates C → A → B (any fires → stop, return best-so-far)
6. On stop: commit answer, or escalate (S8) if stakes high and aspiration unmet
7. Log (tier, τ, gates, outcome) to the aspiration ledger; adapt τ periodically
```

### 5.3 What "good enough with guarantees about the bound" compiles to

For each tier, the v2 build must ship a **satisficing contract**: (acceptance criterion, budget, gate configuration). The controller's runtime guarantee is then checkable in logs: *every committed decision either met its acceptance criterion within budget, or escalated.* That is auditable, testable, and honest — it never claims optimality. The golden set (open-problem #4) is what validates the contracts: success-vs-latency curves per strategy per tier *are* the measured performance profiles (§3.2) that the metalevel needs.

## 6. Validate — falsification criteria and pre-registered experiments

**No experiments were run this cycle.** The following would validate or kill the design; all are unrun unless noted.

| # | Claim / design element | Falsifier | Status |
|---|---|---|---|
| V1 | Myopic VoI gate (A) stops reasoning without hurting tier success rates | On the golden set, ABLATE the gate: success rate drops >noise or latency doesn't improve → gate is miscalibrated or useless | Unrun — needs golden set (#4) |
| V2 | The three gates in series beat any single gate on success-per-ms | Measure success-vs-latency curves per strategy per tier with each gate ablated | Unrun — this is open-problem #7's resolution experiment |
| V3 | A tiny classifier routes agentic tasks better than task-type heuristics | Train on golden-set labels; compare routing precision vs heuristic baseline | Unrun — needs golden set + labels (#4, #2) |
| V4 | Aspiration dynamics (τ adaptation) converge rather than oscillate | Simulate on logged decisions; check τ stability over time | Unrun — needs the aspiration ledger to exist |
| V5 | Interruptible best-so-far answers are actually valid on interruption | Fault-inject: interrupt ReAct mid-trajectory, retrieval mid-scan; check returned state is usable | Unrun — engineering test for v2 build |
| V6 | The metalevel stays ≤5% of the modality budget | Profile router + gate evaluation on the 2060/Ryzen 5 3600 | Unrun — needs hardware access |

**Pre-registration note:** V2 is the experiment open-problem #7 prescribes ("measure success-vs-latency curves per strategy per difficulty tier; find the crossover points empirically"). This cycle's contribution is making that experiment *well-posed*: the curves to measure are performance profiles; the tiers are the matrix rows; the ablation targets are the three gates.

## 7. Integrate — links, ADR candidate, open-problem update

**Links into the knowledge base:**
- Extends the routing rule in `learn-frontier-reasoning.md` §5 with the runtime controller (router + three gates + modality matrix). The table there is unchanged; the *execution* of it is now specified.
- Consumes: belief ledger + VoI + asymmetric loss (`learn-math-for-jarvis.md`); hardware budgets (`learn-inference-frontiers.md`); scaling evidence (`learn-research-frontiers.md`); ask/act/escalate as sibling (`learn-underspecification.md`).
- Feeds: `DECISION-PLAYBOOK.md` — ADR candidate below.

**ADR candidate (for the playbook):** *"JARVIS v2 shall implement a bounded-rationality controller: a predictive router (tiny classifier, ≤30ms) selecting among the 8 reasoning strategies subject to a tier × modality legality matrix, plus a three-gate monitor (confidence / myopic-VoI / hard-budget) evaluated per reasoning step with ≤5% metalevel overhead, with aspiration thresholds adapted from the belief ledger. Token budgets are measured parameters from the 2060 shootout, not constants. Rationale: optimal reasoning is uncomputable under the voice/interactive bounds; satisficing with explicit, auditable contracts is the only honest guarantee. Status: PROPOSED — awaits golden-set validation (V1–V6)."*

**Open-problem #7 status update:** was "design missing, experiment prescribed." Now: **controller design proposed (this file); experiment still unrun** (V2). Difficulty estimation remains the hard sub-problem — its honest limits are in §3.4, and its measurement is open-problem #2. Score unchanged (60); state-of-knowledge tag stays [HC] — the *design* is now grounded, but nothing is *measured* yet.

## 8. Record — evidence table

| Claim | Source | Confidence |
|---|---|---|
| Satisficing: aspiration level set, search stops at first alternative meeting it; "a 'good' move" suffices | Simon 1955, p. 108 (via encyclopedia.com) | [HC] |
| Aspiration levels adapt to experience (rise when rich, fall when sparse); deliberation costs belong inside rationality | encyclopedia.com; scales/db.arabpsychology.com | [HC] |
| Contract vs interruptible anytime algorithms; branch-and-bound as interruptible exemplar | Russell & Zilberstein 1996 (via ar5iv 1810.11291; AAAI-2002 Bernstein et al.); Waterloo AI seminar | [HC] |
| Contract→interruptible conversion via geometric schedule; small constant overhead | AAAI-2002 abstract (construction [HC]); ~4× constant [MC] | [HC]/[MC] |
| Performance profiles (quality vs time) make metalevel decisions tractable; profiles must be measured | AIMA metareasoning paper (aima.eecs.berkeley.edu) | [HC] |
| Value of computation = expected decision improvement − delay cost; myopic (depth-one) metareasoning is the practical standard | Russell & Wefald 1989/1991; Horvitz 1987/1989; Howard 1966; Good 1971 (via AIMA paper, cs.berkeley.edu) | [HC] |
| DTA*: stop when no expansion has non-negative expected utility; expand hardest node first | Russell & Wefald ch. 4–5 (via jimdavies.org summaries) | [MC] |
| Myopic stop rule computable online with little overhead; metalevel cost must be monitored | AAAI-2008 workshop paper (cdn.aaai.org WS-08-07); Hansen & Zilberstein 1996 (monitoring as Markov process) | [HC] |
| Snell et al.: difficulty-adaptive test-time compute up to 4× more efficient than best-of-N; small model beats 14× larger on easy/intermediate; difficulty via pass@1 (2048 samples, cost amortizable); easy→refine, hard→search; beam search overfits PRM on easy | arXiv:2408.03314 (via alphaxiv, machinelearningatscale, llmbook, insidellms, medium — 5 corroborating sources) | [HC] |
| RouteLLM: ~110M BERT router, 10–30ms, ~65K arena battles + ~$700 judge labels; ~85% MT-Bench cost cut at ~95% GPT-4 quality | seangeng.com; letsdatascience.com (secondary) | [MC] |
| FrugalGPT cascade: up to 98% cost reduction; but cascade doubles latency and breaks streaming — bad for chat | Chen et al. 2023 (via codingscape, medium, letsdatascience); structural point via seangeng | [HC] |
| AutoMix: few-shot self-verification as entailment + POMDP router for noisy verification; >50% cost reduction, comparable performance | Aggarwal et al., arXiv:2310.12963 (abstract, primary) | [HC] |
| Router decision latencies: ~10–30ms classifier vs ~1–5s LLM-judge; NVIDIA complexity classifier 94–99% | seangeng.com (single blog source) | [SP] |
| Ramp production router: ~30% own-cost reduction | codingscape.com | [MC] |
| Modality latency targets (<300ms barge-in, <1s turn start, seconds for chat, minutes for background) | v2 architecture context (task brief) — design requirements, not measurements | [MC] as targets |

**Real references (no fabricated citations):** Simon 1955 "A Behavioral Model of Rational Choice"; Simon 1956; Simon 1957 *Models of Man*; Horvitz 1987/1989; Dean & Boddy 1988; Russell & Wefald 1989, 1991 *Do the Right Thing* (MIT Press); Zilberstein 1993 (PhD, conditional performance profiles); Russell & Zilberstein 1996; Hansen & Zilberstein 1996; Bernstein, Perkins, Zilberstein & Finkelstein, AAAI 2002; Howard 1966; Good 1971; Snell, Lee, Xu & Kumar 2024 (arXiv:2408.03314); Chen et al. 2023 (FrugalGPT); Ong et al. (RouteLLM, LMSYS); Aggarwal et al. 2023 (AutoMix, arXiv:2310.12963). URLs: https://www.encyclopedia.com/social-sciences/applied-and-social-sciences-magazines/satisficing-behavior · https://ar5iv.labs.arxiv.org/html/1810.11291 · https://aaai.org/papers/00702-AAAI02-105-scheduling-contract-algorithms-on-multiple-processors/ · http://aima.eecs.berkeley.edu/%7Erussell/papers/mitecs-metareasoning.pdf · https://cdn.aaai.org/Workshops/2008/WS-08-07/WS08-07-010.pdf · https://www.alphaxiv.org/overview/2408.03314v1 · https://arxiv.org/pdf/2310.12963 · https://seangeng.com/writing/the-honest-guide-to-llm-routing

## 9. Reassess — unknowns marked, what's next

**Explicit unknowns [UK]:**
1. JARVIS's real difficulty distribution for Owais's usage (open-problem #2) — the crossover points Snell et al. say must be measured. The controller's priors are literature-shaped until this is measured.
2. Whether a chat-preference-trained difficulty classifier transfers to agentic tool-calling routing [SP at best].
3. The actual performance profiles (quality-vs-time curves) of each strategy on the 2060 — the metalevel's core input, entirely unmeasured.
4. Aspiration-dynamics stability: τ adaptation is designed but its convergence is unproven (V4).
5. Discriminator accuracy on JARVIS's real tool set (open-problem #3) — gates S3/S4 selection.

**What this cycle resolved:** open-problem #7 now has a concrete controller design (router + three-gate monitor + modality matrix + anytime map + satisficing contracts) instead of a bare question. The design is falsifiable (V1–V6) and its parameters are explicitly marked as measured-inputs, not inventions.

**Recommended next cycles:** (a) the golden-set build (open-problem #4) — unblocks V1/V2/V3 and the performance profiles; (b) the 2060 model shootout (open-problem #1) — fills `T_max`; (c) a focused study on self-verification calibration for agentic tool calls (the AutoMix entailment trick applied to tool trajectories — is the verifier's confidence signal any good on JARVIS's tools? feeds open-problem #3).

**One-line verdict for the ledger:** Bounded rationality isn't a compromise JARVIS accepts reluctantly — it's the design principle. The controller doesn't apologize for stopping early; stopping early *correctly* is the skill. Simon gave the frame, Russell and Wefald gave the stopping math, Snell gave the scaling evidence, AutoMix gave the noisy-signal handling. What's left is measurement.


---

# PART II — Cycle 7: Does the Theory Sharpen the Machinery or Merely Redescribe It?

**PHASE INFINITY — Research Cycle 7.** Written 2026-10-19. LEARNING ONLY — no project code touched, no experiments run, no claims fabricated.

**Research question:** What does bounded rationality imply for JARVIS's decision architecture — beyond what Cycle 6 already built?

**Note on this file:** Part I (above) is the Cycle 6 research — the Simonian frame, anytime algorithms, the three-gate controller (confidence / myopic-VoI / hard-budget), metacognition and routing literature, the tier × modality budget matrix, satisficing contracts. It is preserved unchanged. Part II is a *separate investigation with a different question*, not a rewrite. Cycle 6 asked "how should the agent allocate reasoning effort under a strict latency budget?" and answered with a controller design. Cycle 7 asks: now that the machinery exists (the 8-step ask/act/escalate rule, VoI, the Beta-Bernoulli ledger, tier budgets, 2-attempt fail-fast), what does the theory *add*? The honest verdict is reported either way — sharpen or redescription.

**Answer in one paragraph:** The theory mostly *re-describes and justifies* the existing machinery — which is still valuable, because it shows the rules are principled rather than arbitrary, and it names the exact failure mode each rule guards against. Simon's scissors explain *why* tier routing and the voice-loop rules have their shape (the environment blade: <300ms, user present, errors cheap to correct); satisficing formalizes what "good enough" means (first alternative meeting a testable aspiration level — and aspiration levels must be adaptive, which Part I's τ-dynamics already proposes); procedural rationality licenses auditing JARVIS on its *procedures* rather than on unknowable outcome-optimality. The genuine additions are four: (1) recognition-primed decision making as the design for the routine-task fast path (Klein) — the one truly new decision path; (2) ecologically-designed fast-and-frugal rules for the voice loop (Gigerenzer) — designed from environment structure, not just latency panic; (3) a per-turn deliberation budget in wall-clock ms, not tokens; (4) automation bias and algorithm aversion as the two biases worth importing — both verified in the literature, both about the human's trust calibration toward JARVIS, both with concrete design handles. The behavioral-economics zoo beyond those two is deliberately rejected, with reasons.

**Confidence tags (state-of-knowledge, not the question):** [VC] >95% · [HC] 80–95% · [MC] 60–80% · [SP] 40–60% · [UK] unknown. **DESIGN** = derived proposals, unmeasured.

---

## II.1. Simon's core ideas in plain language (verified against sources, not re-derived from Part I)

### II.1.1 Satisficing vs optimizing

Simon (1955), "A Behavioral Model of Rational Choice," *Quarterly Journal of Economics* 69(1):99–118 [VC on existence and content — corroborated by encyclopedia.com, the scielo.br summary, and flyriver]. The setup: the decision maker's information-processing capacity cannot examine all alternatives and their consequences. The mechanism:

1. Set an **aspiration level** — a threshold of acceptability.
2. Search alternatives **sequentially**.
3. Stop at the **first** alternative that meets the level. "The players, instead of seeking for a 'best' move, need only to look for a 'good' move" (Simon 1955, p. 108) [HC — encyclopedia.com].

Formal meaning of "good enough": preferences are partially ordered into exactly two classes — acceptable / not acceptable. No utility maximization; a binary acceptance test. "The higher the aspiration level is, the harder a decision will be. And the opposite is also the case: the lower the aspiration level is, the easier a decision will be. Any option that is above the aspiration level is a good enough option" (scielo.br summary of Simon 1955) [HC].

Two properties Part I underplayed and this cycle restores:

- **Aspiration levels are adaptive and endogenous** — "conceived of as being learned in a series of choices. If the aspiration level is set too low, too many alternatives qualify… If set too high, no alternatives may qualify, and the level is lowered. This makes preferences endogenous to ongoing experience and feedback rather than fixed" (encyclopedia.com) [HC]. A frozen threshold is not Simonian; the threshold must move with experience. (Part I's τ-dynamics implements this; §II.3.1 extends it.)
- **Simon did not frame heuristics as inferior.** Gigerenzer's chapter notes Simon treated satisficing heuristics as "our only viable option in a fundamentally uncertain world" (Gigerenzer 2015, "Heuristics: Tools for an Uncertain World") [HC]. The posture for JARVIS: satisficing is not the consolation prize for failing to optimize — under uncertainty, optimization is not on the menu at all.

Why a satisficing assistant beats an optimizing one — on latency, cost, *and* robustness [DESIGN, derived]:

- **Latency:** optimizing requires enumerating and comparing; satisficing stops at first-acceptable. Expected search length is strictly shorter whenever acceptable options are dense in the search order — and JARVIS controls the search order (best-guess first), so it can *make* them dense.
- **Cost:** every comparison is compute; the marginal value of the comparison that finds the *best* rather than merely *acceptable* is usually tiny (diminishing returns), while its cost is fixed. This is VoI applied to the search itself.
- **Robustness:** optimizers are brittle to model error — the "best" option under a wrong model is confidently wrong. A satisficer with a good acceptance test fails *safe*: it rejects everything rather than picking a bogus optimum. This is the less-is-more mechanism (§II.3.3) in another guise: fewer moving parts, fewer ways to overfit noise.

### II.1.2 The scissors metaphor

Simon (1990, p. 7): "Human rational behavior … is shaped by a scissors whose two blades are the structure of task-environments and the computational capabilities of the actor" [HC — quoted identically in the emerald FFH chapter and in Petracca (2024), Elgar Companion to Herbert Simon, ch. 7; the qeios synthesis cites the same metaphor].

Plain language: you cannot understand — or design — rational behavior by looking at the mind alone. One blade is the agent's compute (the model, the budget, the latency allowance); the other blade is the environment's structure (where information lives, what feedback exists, what errors cost, who is present to correct). Rationality is the *fit* between the blades. Design rule for JARVIS: **every decision rule should be justifiable from both blades** — "we do X because the model affords it AND because the environment makes X sufficient." Rules justified from only one blade are suspect. Example: a clever routing scheme that ignores that voice errors are instantly correctable by the user standing in the room is admiring one blade.

The companion line from *The Sciences of the Artificial* (1969, p. 53): "Human beings, viewed as behaving systems, are quite simple. The apparent complexity of our behavior over time is largely a reflection of the complexity of the environment in which we find ourselves" [HC — en.wikiquote]. For JARVIS: apparent intelligence can come from a *simple controller nested in a rich environment* (tools, feedback, user corrections, the belief ledger) rather than from a brilliant brain. This is an argument for investing in the environment blade (tool quality, feedback loops, ledger) over the compute blade — directly supporting the v2 "interface, not engine" posture.

### II.1.3 Procedural vs substantive rationality

Simon (1976), "From Substantive to Procedural Rationality," in Spiro Latsis (ed.), *Method and Appraisal in Economics*, Cambridge UP, pp. 130–131 [HC — corroborated by four independent citations]. **Substantive rationality** = rationality of the *result* (were the goals achieved? was utility maximized?). **Procedural rationality** = rationality of the *process that generated the decision* — "depends only on the thought process that generated it" and "makes no claim that the actor correctly anticipates the consequences of his decision."

Why this matters for JARVIS [DESIGN]: we can *never* verify substantive rationality of a single decision — we cannot know whether the plan was optimal. We *can* verify procedural rationality: did the controller respect the budget, apply the three gates, check strategy preconditions, log the decision with its evidence? This is the philosophical license for Part I's satisficing contracts ("every committed decision either met its acceptance criterion within budget, or escalated") and for the DECISION-PLAYBOOK posture generally: **audit JARVIS on its procedures, not on outcome optimality.** It dissolves a false debate: "but was that the *best* answer?" is the wrong question under bounds; "was that an *acceptable* answer produced by a sound, bound-respecting procedure?" is the right one.

Related and worth naming: Good's **Type II rationality** (1952, 1971) — rationality that *includes the cost of deliberation* in the optimization, vs Type I which ignores it [HC — via MITECS/Doyle]. The ask budget and fail-fast rules are Type-II-rational; any analysis of them that ignores deliberation cost is Type-I and therefore wrong by construction. When someone proposes "just think harder," the Type-II reply is: thinking harder is itself an action with a cost — show me the VoI.

---

## II.2. Where JARVIS already satisfices — the audit

For each existing rule: its bounded-rationality justification, what the *unbounded* version would do, and why the unbounded version is worse. (Sources: the knowledge files named; all [VC] in-repo.)

| # | Existing rule | Bounded-rationality justification | The unbounded version | Why unbounded is worse |
|---|---|---|---|---|
| 1 | **Tier routing** — BitNet-CPU → 4B → 7B → cloud; compute budget per task tier; never best-of-N on voice (`learn-research-frontiers.md`) | **Scissors:** the *environment* blade (voice: <300ms, user present, errors cheap) selects the strategy, not the model's capability. **Attention-allocation:** scarce compute goes where marginal utility is highest (hard tasks), not spread evenly. | Every turn gets the frontier model with full deliberation (MCTS + verifier), regardless of difficulty. | Latency blowup on trivial turns; cost explosion; and per Snell et al., *worse* results on easy problems (small model + right compute beats a 14× larger model). Optimizing the easy turn spends the budget the hard turn needed — **allocation myopia**. |
| 2 | **2-attempt fail-fast** — 2 failed attempts = change approach (AGENTS.md; `learn-ai-for-se.md` calls 2 "approximately the measured optimum") | **Myopic VoI:** after two failures the Beta posterior on "this approach works" has collapsed; the expected value of a third attempt ≈ 0 — it cannot change the decision (switch approaches / escalate). **Type-II:** the attempt itself costs latency the user feels. | Keep retrying / exhaustively enumerate alternative approaches until one succeeds. | Burns the user's time on a posterior that's already decided. The unbounded retrier is the gambler's fallacy with someone else's clock. |
| 3 | **Exhaustive-over-BoED at small scale** — for ~10 discrete configs, just run them all; EIG machinery costs more than the experiments (`learn-bayesian-design.md`) | **Meta-deliberation must be cheaper than the object decision** (Part I's ≤5% rule). The recursion guard: thinking about what to think about must itself satisfice. | Always run the optimal sequential experimental design (full BoED/EIG) regardless of design-space size. | The EIG computation (nested estimation) exceeds the cost of just running all 10 configs. Optimizing the *learning* loses to satisficing it — a clean, measured instance of Type II rationality. |
| 4 | **4k-physical context strategy** — 14× fewer attention FLOPs; prefill is quadratic in context (`learn-inference-frontiers.md`) | **Scissors' compute blade:** the 2060's physical bounds are hard. **Satisficing on context:** keep the high-MI tokens (MI between kept context and answer — `learn-math-for-jarvis.md`), drop the rest. First-*acceptable* context, not maximal context. | Stuff everything into the largest available window "just in case." | Quadratic prefill → TTFT blowup; plus the less-is-more mechanism (§II.3.3): extra low-MI context is noise the model can overfit to (distraction), so the unbounded version is slower *and* often worse. |
| 5 | **Ask budget 2–3** — max ~2–3 questions per task; batch independent questions; never re-ask (`learn-underspecification.md` §3.1 step 8) | **C_ask grows with repetition** (redundancy cost); marginal VoI of the 4th question ≈ 0 vs acting best-effort or escalating. Aspiration applied to *elicitation*: stop at "good enough to act," not "fully specified." | Keep asking until the task is fully specified — the 20-questions agent. | User abandonment; and the rubber-stamping finding (`learn-underspecification.md` §3.2): over-asking trains blind approval, destroying the safety value of the questions actually needed. The unbounded asker is *less safe*, not more. |
| 6 | **The 8-step ask/act/escalate rule itself** (`learn-underspecification.md` §3.1) | **Procedural rationality in pure form:** a cheap sequential procedure with hard gates, instead of solving the full Bayesian decision problem per turn (enumerate all interpretations × exact posteriors × exact VoI of every possible question). Exact VoI is intractable (Part I §3.3); the rule is the tractable procedure. | Full decision-theoretic optimization per turn: exact posterior over interpretations, exact EVPI question selection, argmax over all (act, ask, escalate) triples. | The controller becomes the tax it was built to avoid (metalevel ≫ object-level). And it would be *fragile*: exact VoI needs exact probabilities we don't have — optimizing on invented numbers is worse than satisficing on measured ones. |
| 7 | **Beta-Bernoulli belief ledger** — two counters per tool, not a full model (`learn-math-for-jarvis.md` §2) | **Satisficing on belief precision:** track the cheapest representation that still gates decisions (α, β → mean + width). The update is three lines, always valid, auditable. | Full hierarchical Bayesian model of each tool's behavior conditional on task type, time of day, input features. | Overfits small observation counts; unmaintainable; the extra precision doesn't change any gate decision (VoI of the fancier model ≈ 0 for the decisions it feeds). |
| 8 | **Never S3/S4 with discriminator <90%** (`learn-frontier-reasoning.md`; DISC-100 protocol) | **Ecological rationality:** a strategy's rationality is relative to its environment — tree search's environment *includes* the discriminator. With a bad judge, search is expensive noise (measured: performs comparably or worse). Fit, not power, decides. | Always use the most powerful strategy (MCTS everywhere) because it's "the best algorithm." | 10–20× slower for equal-or-worse results. The classic scissors violation: admiring one blade (compute) while ignoring the other (the judge the search depends on). |

**Audit verdict [HC]:** all eight rules are defensible instances of bounded rationality, and in each case the theory names the *exact* failure mode the unbounded version falls into — allocation myopia, the metalevel tax, optimizing on invented numbers, scissors violation. The theory overturns zero rules. What it changes is the *justification quality*: "we do this because it measured well / felt right" becomes "we do this because the alternative is provably the wrong *kind* of rationality under these bounds." That conversion is what lets future designers distinguish load-bearing principles from tunable constants — which is a genuine, if unglamorous, contribution.

---

## II.3. What the theory adds — genuine gaps only

Three candidates from the investigation; each assessed honestly against what Part I already built.

### II.3.1 Aspiration-level adaptation → mostly already covered; one genuine extension

Simon's adaptivity ("levels rise/fall with experience") is already Part I §3.3's τ-dynamics: log (τ_used, outcome) per tier; lower τ when budget gates fire constantly with successful outcomes; raise it when confidence-gated actions succeed far above the required rate. The open question: should the bar also adapt to *task stakes and user patience*?

- **Stakes:** already in the design — τ(tier, stakes), asymmetric loss on irreversible actions. Nothing new. [VC]
- **User patience:** genuinely unmeasurable without instrumentation we'd rather not build. Proxies exist (explicit "quickly", barge-in frequency, time-of-day, session length) but each is confounded — a fast typist isn't an impatient user. **Verdict: SKIP the patience sensor** until there's honest instrumentation; marked [UK].
- **The genuine extension — the familiarity dividend:** for task classes with long success histories, τ can be *lower*, because the Beta posterior is tight. Aspiration should adapt not just to past success *rates* but to posterior *width*: τ_adapted = τ_base(tier, stakes) − k·(1 − posterior_width), floored at a safety minimum for irreversible actions. This connects aspiration adaptation to the belief ledger quantitatively — uncertainty width, not vibes, sets the bar. [DESIGN, MC]

### II.3.2 The attention-allocation problem → sharpens the frame; adds one session-level gap

"Bounded rationality *as* rational allocation of scarce computation" is the frame Part I's controller implements per-turn (router + budgets + gates). The theory sharpens it by naming the missing scope: **allocation myopia across turns**. The router optimizes each turn independently, but the compute budget is shared across a session — an agent that spends lavishly on turn 1 starves turn 5. Russell & Wefald's metareasoning is single-episode; the *session* is the actual episode.

The Snell et al. crossover connection: the inference-time scaling finding *is* an attention-allocation result — difficulty-contingent allocation beats uniform allocation by up to 4×. The theory adds the normative wrapper: Snell measured *that* it works; bounded rationality says *why* it's the rational thing (Type-II: the allocation maximizing expected utility net of deliberation cost). Sharpening, not new machinery. [HC]

**Candidate addition (§II.4.4): a session-level compute budget**, with per-turn allocations shrinking as remaining budget shrinks and explicit borrowing for high-stakes turns. Priority: low until usage data exists — the session difficulty distribution is open-problem #2, and any allocation function fit now would be invented. [DESIGN]

### II.3.3 Ecological rationality → the most genuinely new lens

Gigerenzer's program (ABC Group, Max Planck Institute for Human Development; *Simple Heuristics That Make Us Smart*, Gigerenzer & Todd, 1999; *Heuristics: The Foundations of Adaptive Behavior*, 2016) [VC on existence]: rationality = **fit between heuristic structure and environment structure**. Fast-and-frugal heuristics (FFH) — search rules + stopping rules + decision rules using little information. Canonical examples: **take-the-best** (try cues in validity order, stop at the first discriminating cue), the **recognition heuristic** (if you recognize one object and not the other, infer the recognized one scores higher), the **hiatus heuristic** ("classify customer as active iff last purchase < 9 months" — used by real airline/apparel managers, beating fancier models) [HC — OUP descriptions, frontiersin.org 2018].

The **less-is-more effect**: fewer parameters → less overfitting → better generalization. "Simple heuristics often need access to less information (i.e. they are frugal) and can thus make a decision faster… because they have few parameters they avoid overfitting data in a learning sample and, consequently, generalize better… The extra parameters of more complex models often fit the noise rather than the signal" (blog.jcx.au, summarizing the program) [HC]. Gigerenzer & Goldstein (1996) showed a fast-and-frugal satisficing algorithm beating standard linear models on inference accuracy [HC — via the MPRA paper]. Simon (1999) himself applauded the program as "a revolution in cognitive science, striking a great blow for sanity in the approach to human rationality" [HC — OUP book description].

What this adds beyond Part I [HC]: Part I's voice-loop rules ("S1 only", "never best-of-N on voice") are justified by *latency arithmetic* — they're constraints, not designs. Ecological rationality supplies a **design method** for the voice loop: enumerate the environment's stable structure, then pick heuristics that exploit it:

- Environment structure of the voice loop: extreme time pressure; the user is present and listening; errors are immediately correctable at near-zero cost; most turns are low-stakes; feedback is instant.
- Heuristic this structure affords: **act on the first parseable intent; spend zero compute on disambiguation the user can supply in one word.** This is the voice equivalent of the gaze heuristic (which exploits optical structure to intercept a ball without computing trajectories): *don't compute what the environment gives you for free.*
- The less-is-more caution: don't run the full NLU/discrimination pipeline on voice — extra cues invite overfitting to noise under time pressure. One or two high-validity cues (wake-word confidence + verb-slot parse), then act.

The non-negotiable discipline, in Gigerenzer's own words: "we are not saying that all simple heuristics are good; only some simple heuristics will perform well in any given environment" [HC — blog.jcx.au]. **A heuristic without its ecological justification is just a hack.** The playbook rule: every fast-and-frugal rule ships with the environment structure it exploits documented alongside it, or it doesn't ship. **Candidate addition (§II.4.3).** Verdict: PROPOSE.

---

## II.4. Decision rules the theory suggests that we DON'T have yet

Four candidates, each with an honest verdict (adopt / propose / skip).

### II.4.1 Per-turn deliberation budget in wall-clock ms — PROPOSE

Part I's Gate B uses token caps + wall-clock caps per (tier × modality), with token budgets as *measured* parameters and a deliberate refusal to invent constants. The gap: **tokens are the wrong primary unit.** Prefill/decode asymmetry (`learn-inference-frontiers.md`) means tokens don't map linearly to user-felt latency; wall-clock is the actual scarce resource (the user's waiting time), and ms budgets are directly enforceable by the monitor — a timer, not a token counter.

The addition: make wall-clock ms the *primary* per-turn contract. Sketch: the monitor enforces "this turn gets L_max ms; at ~80% of budget the router may only select interruptible continuations; at 100% return best-so-far" — with tokens kept as a secondary guardrail against pathological per-token costs. This is the contract-algorithm discipline stated in the unit the bound is actually expressed in. No invented constants: the L_max values remain measured parameters from the modality matrix; the 80% preemption threshold is a design constant to be tuned on the golden set. [DESIGN — HC on the reasoning, MC on the 80% figure]

### II.4.2 Recognition-primed decision making for familiar tasks — PROPOSE, with activation gate

Klein (1998), *Sources of Power: How People Make Decisions* (MIT Press) [VC on existence]: experts under time pressure don't compare options. The **recognition-primed decision (RPD) model**: recognize the situation as typical → retrieve the typical action → **mentally simulate it once** → if the simulation reveals problems, modify or try the next-typical action. "The decision makers looked at several options yet never compared any two of them… evaluating each option on its own merits… *Satisficing*: selecting the first option that works. Satisficing is more efficient" than optimizing (direct book text, via fluidself.org) [HC — corroborated by researchgate, mindtools, bagrounds, slideshare summaries].

The JARVIS translation — the **routine-task fast path** [DESIGN]:

1. **Situation recognition:** match the current task against a library of prototypes (task-type + slots + context signature). Match = "I've seen this shape before."
2. **Typical action retrieval:** the prototype carries its last-successful trajectory (the skill/plan that worked).
3. **Mental simulation (cheap):** check preconditions and expected effects against current state — *not* a full re-plan. This is the RPD "will it work?" step, implemented as invariant checks (cf. `learn-formal-methods.md`: preconditions/postconditions), not LLM deliberation.
4. **Act or fall back:** simulation passes → execute the typical action, skipping the reasoning loop entirely. Simulation flags an anomaly → fall back to normal deliberation. (Klein's experts do exactly this: anomalies trigger diagnosis, not blind execution.)

Why this is genuinely new: nothing in the current machinery skips deliberation on *recognition* — the router always reasons about which strategy to use. RPD inverts the default: for familiar tasks the decision is *retrieval + one cheap check*, and deliberation is the fallback.

The honest gate: RPD needs experience, and JARVIS's prototype library starts empty. **Activation condition:** a prototype becomes eligible only when its Beta posterior (successes/total for that prototype) is tight and high — the belief ledger is the experience counter. Until then, the fast path is designed but dormant. Failure mode to log: mis-recognition (wrong prototype fires) — the cheap simulation is the guard, and every fast-path execution logs (prototype, checks, outcome) so bad prototypes lose eligibility. [DESIGN — MC on the mechanism, HC on the Klein model it translates]

### II.4.3 Fast-and-frugal voice-loop rules, ecologically justified — PROPOSE

From §II.3.3: restate the voice path as designed heuristics, each paired with the environment structure it exploits (the second blade of the scissors):

- **H1 — First-parseable-intent:** act on the first interpretation that fills the verb's required slots; never run multi-hypothesis disambiguation on voice. *Exploits:* user present, correction cost ≈ one word, time pressure extreme.
- **H2 — No second opinions:** one model call per voice turn (no verifier, no best-of-N). *Exploits:* the less-is-more effect under time pressure — a second judgment can't be computed carefully in the remaining ms anyway, so it's noise, not signal.
- **H3 — Defer, don't deliberate:** if no parseable intent within the parse budget → immediate acknowledgment + background continuation (the existing modality-handoff rule, restated as a heuristic). *Exploits:* the environment has a background channel — use the environment's structure instead of the brain's effort.

Each rule ships with its ecological justification or doesn't ship (§II.3.3's discipline). These are cheap to implement — mostly *removals* of computation — and testable: A/B the voice loop with and without H1/H2 on task success + user correction rate. [DESIGN, MC]

### II.4.4 Session-level compute budget — PROPOSE as design, parked behind measurement

From §II.3.2: the router's per-turn optimality ignores the session. Design sketch: a session budget B (wall-clock); per-turn allocation b_t = f(remaining budget, estimated remaining turns, current stakes); high-stakes turns may explicitly borrow against future turns (logged). This is the attention-allocation problem stated at the right scope. **Parked:** the session difficulty distribution is open-problem #2 and unmeasured, so any allocation function now would be invented. The honest move is to log per-turn compute starting now so the function can be fit later. Verdict: PROPOSE the logging + the sketch; do not implement allocation until the data exists. [DESIGN — HC on the problem statement, UK on the allocation function]

**Considered and rejected:** a separate mid-turn "deliberation scheduler" that re-plans the turn's compute beyond the three gates — rejected as duplication; the gates already *are* the scheduler. Also rejected for now: aspiration adaptation to user patience (§II.3.1) — unmeasurable without instrumentation.

---

## II.5. What to deliberately NOT import — the behavioral-economics zoo

The brief: dozens of biases exist; which 2–3 actually matter for an AI assistant's design, and which are irrelevant. Both candidate biases verified in the literature first.

### II.5.1 IMPORT: automation bias [verified — HC]

- **Exists.** Term introduced by Mosier et al. studying pilots in simulated flight; systematized by Parasuraman & Riley (1997), "Humans and Automation: Use, Misuse, Disuse, Abuse," *Human Factors* 39(2):230–253 [VC — APA record, https://doi.org/10.1518/001872097778543886]. Two error types (Skitka and colleagues): **commission** — following wrong automated advice despite contradictory evidence; **omission** — failing to act because the automation didn't prompt, despite environmental cues [HC — review chapter via academia.edu]. Robust across aviation, medicine, process control, and military command-and-control; occurs in experts as well as novices; **cannot be prevented by training or explicit instructions to verify** (Parasuraman & Manzey review) [HC — via researchgate].
- **Why it matters for JARVIS:** JARVIS is the automation; Owais is the operator. As JARVIS gets more capable, Owais's monitoring *will* degrade — he will approve wrong tool calls (commission) and miss things JARVIS didn't flag (omission). This is the primary human-factors risk of a personal agent, and it gets *worse* as the agent gets better, because reliability breeds complacency.
- **Design handles (concrete):** (a) confirmations that require reading — the visible-payload rule (`learn-frontend.md`) is an automation-bias countermeasure; keep it; (b) make the belief ledger's reliability estimates *visible* so trust tracks evidence, not vibes; (c) never let approvals become one-tap muscle memory — the 8-step rule's "typed, not one-tap" for catastrophic stakes is exactly this; (d) the rubber-stamping warning (`learn-underspecification.md` §3.2) is the same phenomenon from the asking side. [DESIGN — HC on the mapping]

### II.5.2 IMPORT: algorithm aversion [verified — VC]

- **Exists.** Dietvorst, Simmons & Massey (2015), "Algorithm Aversion: People Erroneously Avoid Algorithms After Seeing Them Err," *Journal of Experimental Psychology: General* 144(1):114–126 [VC — PubMed PMID 25401381; APA record]. Finding: people lose confidence in an algorithm faster than in a human after *identical* errors — even when they watched the algorithm outperform the human. Costly and robust [HC].
- **Why it matters:** the mirror image of automation bias. After JARVIS makes a visible error, Owais may under-use it precisely where it's strongest — *disuse*, in Parasuraman & Riley's taxonomy. The agent designer's problem is therefore not "more trust" or "less trust" but **calibrated trust** (Lee & See 2004) [HC — via PMC review].
- **Design handles:** (a) own mistakes fast and plainly — the "diligent like you / own mistakes out loud" doctrine *is* an algorithm-aversion countermeasure; (b) Dietvorst, Simmons & Massey (2018): giving users a small ability to *adjust* the algorithm's output restores trust — editable drafts beat take-it-or-leave-it answers [HC — via IJRAR review]; (c) show the track record (the ledger) so one error doesn't rewrite the whole history; (d) boundary conditions matter — Castelo, Bos & Lehmann (2019): people accept algorithms for objective/quantifiable tasks but resist for subjective ones — frame JARVIS's role accordingly and don't push algorithmic answers where Owais wants judgment [MC — via IJNTI review].
- **The tension to hold:** automation bias says he will over-trust; algorithm aversion says he will under-trust after errors. Both are miscalibration in opposite directions. The design goal is a trust interface that moves with evidence — which is what the visible belief ledger is for.

### II.5.3 IMPORT (honorable mention): the less-is-more / overfitting mechanism

Not a "bias" but the mechanism behind several: extra information and parameters fit noise, degrading generalization (Gigerenzer & Goldstein 1996; §II.3.3). Already operationalized in the 4k-physical strategy and H2. Keep as a standing veto: any proposal to "add more context / more checks / more candidates" must answer the less-is-more objection. [HC]

### II.5.4 DELIBERATELY NOT IMPORTED

| Bias / effect | Why it's out |
|---|---|
| Prospect theory, loss aversion, probability weighting (Kahneman & Tversky 1979) | Describes *human* choice under risk. JARVIS's decisions already use asymmetric loss (`learn-math-for-jarvis.md`) — the full descriptive apparatus adds nothing to the agent's machinery. (May matter for *how options are framed to Owais* — a UX question, not a decision-architecture question. Parked.) |
| Anchoring, framing effects, endowment effect | Human judgment quirks with no handle on the agent's side. The agent doesn't "anchor" — it computes. |
| Sunk-cost fallacy | The agent-side version ("don't keep a failing trajectory because of invested compute") is already the 2-attempt fail-fast rule + Gate B. The bias label adds no new rule. |
| Base-rate neglect, representativeness, availability | The Beta-Bernoulli ledger tracks base rates explicitly — and better than vibes. Importing the bias framing would be redescribing the ledger. |
| Confirmation bias (in the agent) | The discriminator-accuracy requirement (≥90% for search) and external verifiers are the structural answer. "Try not to confirm yourself" is not an implementable rule. |
| The heuristics-and-biases program as a whole | Note the rivalry: Kahneman/Tversky treat deviations from logic as *errors*; Gigerenzer treats them as *(mis)matches to environment structure*. For an agent *designer*, the ecological framing is the actionable one — it says fix the fit, not de-bias the mind. We import Gigerenzer's program (§II.3.3), not the biases catalog. |

**The meta-rule [DESIGN]:** import a bias only if it (a) is verified in the literature, (b) describes the *human's* interaction with JARVIS — not the agent's internals, whose failure modes are already covered by the autopsy + gates — and (c) yields a concrete design handle. Automation bias and algorithm aversion pass all three. Everything else fails (b) or (c).

---

## II.6. The honest verdict: sharpen or redescribe?

| Investigation | Verdict |
|---|---|
| §II.1 Simon's core ideas | **Redescribes** — but the redescription is load-bearing: scissors / procedural-rationality / Type-II give the playbook principled names for why each rule exists, which is what lets future designers distinguish principles from constants. |
| §II.2 Audit of existing rules | **Sharpens.** Each rule now carries its unbounded counterpart and the exact failure mode it guards against (allocation myopia, the metalevel tax, optimizing on invented numbers, scissors violation). Zero rules changed; every rule's *justification* got stronger. |
| §II.3.1 Aspiration adaptation | **Mostly covered** by Part I; one genuine extension (familiarity dividend via posterior width). Patience-adaptation honestly parked as unmeasurable. |
| §II.3.2 Attention allocation | **Sharpens** the frame; adds one genuine gap (session-level budget, parked behind measurement). |
| §II.3.3 Ecological rationality | **Genuinely new lens.** The voice-loop rules graduate from latency-imposed prohibitions to designed heuristics with ecological justifications — and the discipline (no heuristic ships without its environment structure) is new to the playbook. |
| §II.4.1 ms deliberation budget | **Sharpens** Gate B (right unit for the bound). |
| §II.4.2 Recognition-primed fast path | **Genuinely new machinery** — the only candidate that adds a decision path that doesn't exist: skip deliberation on recognition, deliberate only on anomaly. Gated on measured prototype reliability. |
| §II.4.3 Fast-and-frugal voice rules | **New formulation** of existing constraints; the design method (not just the rules) is the contribution. |
| §II.4.4 Session budget | **New problem statement**, honestly parked. |
| §II.5 Bias zoo | **Two imports** (automation bias, algorithm aversion — both verified, both about the human's trust calibration, both with design handles); the rest deliberately rejected with reasons. |

**One-line verdict for the ledger:** Bounded rationality mostly *justifies* the existing machinery rather than replacing it — eight rules audited, zero overturned — but it is not mere redescription: it adds the RPD fast path (the one genuinely new decision path), the ecological design discipline for heuristics, the ms-first budget, and two verified human-factors imports with concrete handles. The theory's sharpest contribution is negative: it tells us what NOT to build (unbounded optimizers, the biases catalog, patience sensors without instrumentation) — and why.

---

## II.7. Evidence table

| Claim | Source | Confidence |
|---|---|---|
| Scissors quote (Simon 1990, p. 7) | Emerald FFH chapter; Petracca (2024), Elgar Companion to Herbert Simon, ch. 7; qeios synthesis | [HC] |
| "Good move" (Simon 1955, p. 108); set level → first-acceptable → stop; levels adapt with experience | encyclopedia.com, "Satisficing Behavior" | [HC] |
| Simon 1955, QJE 69(1):99–118; higher level = harder decision; binary acceptable/not-acceptable | scielo.br (Brazilian J. of Political Economy 42(2), 2022); flyriver | [HC] |
| Heuristics as "our only viable option in a fundamentally uncertain world" (Simon's attitude) | Gigerenzer (2015), "Heuristics: Tools for an Uncertain World" | [HC] |
| Procedural vs substantive rationality (Simon 1976, Latsis ed., Cambridge UP, pp. 130–131) | 4+ independent citations (academia.edu ×2, d-nb.info, thefreelibrary) | [HC] |
| Good's Type II rationality (deliberation cost inside rationality) | MITECS/Doyle (ai.ato.ms) | [HC] |
| *Sciences of the Artificial*, p. 53 (behavioral simplicity / environmental complexity) | en.wikiquote, "Herbert A. Simon" | [HC] |
| FFH: take-the-best, recognition heuristic, hiatus heuristic; less-is-more (fewer params → less overfitting → better generalization); ecological rationality = heuristic–environment fit; Simon (1999) "revolution in cognitive science, striking a great blow for sanity in the approach to human rationality" | OUP, *Heuristics* (2016); blog.jcx.au; MPRA paper (Gigerenzer & Goldstein 1996 result); frontiersin.org (2018) | [HC] |
| "Not all simple heuristics are good" — a heuristic needs its environment | blog.jcx.au (quoting the program) | [HC] |
| RPD: experts don't compare options; singular evaluation; mental simulation; satisficing basis; anomaly → diagnose | Klein (1998) via researchgate, mindtools, bagrounds, fluidself (direct book text), slideshare | [HC] |
| Automation bias: Mosier et al. coined the term; commission vs omission (Skitka et al.); Parasuraman & Riley (1997), *Human Factors* 39(2):230–253; robust incl. experts; not fixable by training or instruction (Parasuraman & Manzey) | APA record; doi.org; academia.edu review chapter; researchgate (attentional integration); PMC review | [HC] |
| Algorithm aversion: Dietvorst, Simmons & Massey (2015), JEP:General 144(1):114–126; faster confidence loss vs humans after identical errors | PubMed PMID 25401381; APA record | [VC] on existence; [HC] on details |
| User adjustment restores trust (Dietvorst et al. 2018); five drivers of aversion (Burton, Stein & Jensen 2020); algorithm appreciation (Logg, Minson & Moore 2019); task-dependence (Castelo, Bos & Lehmann 2019) | IJRAR review; IJNTI review (rjpn.org) | [MC] (secondary sources) |
| Calibrated trust (Lee & See 2004); transparency of rationale improves automation-use accuracy | PMC review article | [HC] |
| 2-attempt fail-fast as measured optimum; tier routing as difficulty curve; 4k-physical = 14× fewer attention FLOPs; ask budget 2–3; 8-step rule; Beta-Bernoulli ledger; discriminator ≥90% | `learn-ai-for-se.md`; `learn-research-frontiers.md`; `learn-inference-frontiers.md`; `learn-underspecification.md`; `learn-math-for-jarvis.md`; `AGENTS.md` | [VC] (in-repo) |

**Real references (no fabricated citations):** Simon, H. A. (1955). "A Behavioral Model of Rational Choice." *Quarterly Journal of Economics* 69(1):99–118. · Simon, H. A. (1969). *The Sciences of the Artificial.* MIT Press. · Simon, H. A. (1976). "From Substantive to Procedural Rationality." In S. Latsis (ed.), *Method and Appraisal in Economics.* Cambridge UP, pp. 130–131. · Simon, H. A. (1990). "Invariants of Human Behavior." *Annual Review of Psychology* 41:1–19. [scissors-quote venue per the emerald chapter — MC] · Gigerenzer, G. & Todd, P. M. (1999). *Simple Heuristics That Make Us Smart.* Oxford UP. · Gigerenzer, G., Hertwig, R. & Pachur, T. (2016). *Heuristics: The Foundations of Adaptive Behavior.* Oxford UP. · Gigerenzer, G. & Goldstein, D. G. (1996). "Reasoning the Fast and Frugal Way." *Psychological Review* 103:650–669. [MC — via MPRA paper] · Goldstein, D. G. & Gigerenzer, G. (2002). "Models of Ecological Rationality: The Recognition Heuristic." *Psychological Review* 109:75–90. [MC — via qeios] · Klein, G. (1998). *Sources of Power: How People Make Decisions.* MIT Press. · Parasuraman, R. & Riley, V. (1997). "Humans and Automation: Use, Misuse, Disuse, Abuse." *Human Factors* 39(2):230–253. https://doi.org/10.1518/001872097778543886 · Dietvorst, B. J., Simmons, J. P. & Massey, C. (2015). "Algorithm Aversion: People Erroneously Avoid Algorithms After Seeing Them Err." *Journal of Experimental Psychology: General* 144(1):114–126. PMID 25401381. · Logg, J. M., Minson, J. A. & Moore, D. A. (2019). "Algorithm Appreciation." *JEP:General.* [MC — via IJNTI review] · Lee, J. D. & See, K. A. (2004). "Trust in Automation." *Human Factors* 46(1). [HC — via PMC review]

**URLs consulted (verbatim from search results):** https://www.emerald.com/md/article/62/13/283/1219796/Simon-s-scissors-meta-heuristics-for-decision · https://ideas.repec.org/h/elg/eechap/19952_7.html · https://www.encyclopedia.com/social-sciences/applied-and-social-sciences-magazines/satisficing-behavior · https://en.wikiquote.org/wiki/?title=Herbert_A._Simon&oldid=3757905 · http://ai.ato.ms/MITECS/Articles/doyle.html · https://www.oup.com.au/books/higher-education/psychology/9780190494629 · https://blog.jcx.au/posts/the-power-of-heuristics · https://mpra.ub.uni-muenchen.de/78162/3/MPRA_paper_78162.pdf;h=repec:pra:mprapa:78162 · https://www.frontiersin.org/articles/10.3389/fpsyg.2018.00227/full · https://fluidself.org/books/psychology/sources-of-power · https://www.mindtools.com/a5wclfo/the-recognition-primed-decision-rpd-process/ · https://awspntest.apa.org/record/1997-05566-005 · https://doi.org/10.1518%2F001872097778543886 · https://pubmed.ncbi.nlm.nih.gov/25401381 · https://awspntest.apa.org/record/2014-48748-001 · https://pmc.ncbi.nlm.nih.gov/articles/PMC11461414/ · https://pmc.ncbi.nlm.nih.gov/articles/PMC9942970/

---

## II.8. Open questions [UK]

1. How to measure user patience/inattention cost without creepy instrumentation — the honest blocker for stakes-and-patience-adaptive aspiration.
2. The session-level allocation function (§II.4.4) — needs the session difficulty distribution (open-problem #2) before any function is fit.
3. Whether the RPD prototype library converges or accumulates junk — needs the fast path to exist first (prototype eligibility dynamics unstudied).
4. Whether ecologically-justified voice heuristics (H1–H3) actually reduce user correction rate vs the current prohibition-style rules — A/B once the voice loop exists.

**Ledger note:** the Infinity ledger flags §16 bounded rationality as "shallow." That flag predates both the Cycle 6 file (Part I: controller design, anytime map, three gates, routing literature) and this Cycle 7 audit. Recommend updating §16: theory audited against machinery, 8 rules justified with unbounded counterparts, RPD fast path + ecological heuristics + ms-first budget proposed, automation bias + algorithm aversion imported with design handles, session budget + patience sensing honestly parked.
