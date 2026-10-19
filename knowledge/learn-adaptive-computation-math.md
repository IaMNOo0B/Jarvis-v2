# The Math of Deciding What to Do Next — Adaptive Computation for JARVIS

**PHASE OMEGA ∞+1 — Domain III.** Written 2026-10-19. LEARNING ONLY — no project code touched, no experiments run, no claims fabricated.

**Research question:** What is the exact math for JARVIS deciding what kind of computation to do next?

**Answer in one paragraph:** At every step, JARVIS faces ten possible computations (more inference, retrieval, symbolic check, code execution, simulation, formal verification, specialist model, more observation, ask the user, or STOP). The optimal choice is the one maximizing **EU(c) = VoI(c) − Cost(c)** — the expected value of the information the computation produces, minus its cost in latency, tokens, money, energy, and risk. This is Russell & Wefald's metareasoning equation (1989/1991), specialized to JARVIS's action set and cost structure. Everything in this file is that equation, unpacked: what each term means concretely, when "stop" wins, when adaptive routing beats fixed pipelines, what must be measured before the math can run, and where the math lies to you. The honest verdict: implement the *static approximation* first (the 3-tier router + 2-attempt rule we already specified), measure on the 2060 and in production, then fit the equation to the measurements — never the reverse.

**Coverage check (Rule Zero):** the 8-strategy table (learn-frontier-reasoning.md §5), the unified ask rule (learn-asking-economics.md §3), VoI (learn-math-for-jarvis.md §3), the 2-attempt debugging rule (learn-ai-for-se.md), satisficing (learn-bounded-rationality.md), difficulty routing (Snell et al. 2024) — all SKIP as known. This file contributes ONLY the formal equation, the stopping rule, the fixed-vs-adaptive analysis, the measurement table, and the failure modes.

---

## 1. The decision problem, formulated

### 1.1 The setting

At any point in a turn, JARVIS holds:
- **b** — a belief state: what it thinks is true, with uncertainty (the belief ledger, learn-frontier-reasoning.md §2).
- **A** — the set of candidate task-level actions (call tool X, answer directly, escalate…).
- **C** — the set of candidate *computations*, the metalevel actions. Exactly ten, per the directive:

| # | Computation c | What it buys |
|---|---|---|
| 1 | More inference (same model) | Better plan/answer from more tokens (strategies 1–4 of the 8-table: ReAct, best-of-N, tree search, MCTS) |
| 2 | Retrieval | External evidence (memory, vector DB, web) |
| 3 | Symbolic check | Deterministic verification (schema, regex, policy) |
| 4 | Code execution | Ground truth from running something (sandbox dry-run) |
| 5 | Simulation | Predicted effects without touching the world |
| 6 | Formal verification | Proof-level certainty (Z3 on the one adopted check) |
| 7 | Specialist model | A different brain for this subtask (tier escalation, LoRA adapter) |
| 8 | More observation | Re-read the screen, re-run the tool, gather state |
| 9 | Ask the user | Human-supplied information (the asking-economics special case) |
| 10 | **STOP** | Act on the current best action with no further computation |

The metalevel decision: choose c ∈ C (including STOP) to maximize expected utility.

### 1.2 The equation

The canonical form is Russell & Wefald's **value of computation** (Russell & Wefald, *Do the Right Thing*, MIT Press, 1991 — the foundational text of metareasoning; the asking-economics file already cites it for the greedy-failure argument):

```
EU(c | b)  =  E_o[ max_a EU(a | b, c, o) ]  −  max_a EU(a | b)  −  Cost(c)
             ─────────────────────────────    ─────────────────
                    value of the information      what you'd do
                    the computation might         without it
                    produce (VoI)
```

In words: *a computation is worth doing iff the improvement it might produce in your eventual decision outweighs what the computation costs.* The first two terms together are exactly **VoI(c)** — Howard (1966), already in learn-math-for-jarvis.md §3: information has no value unless it can change the decision. The equation adds the missing half: *and the change has to be worth the price.*

### 1.3 Each term, concretely, for JARVIS

**VoI(c) — the gain side.** Decompose as probability × magnitude:

```
VoI(c) = P(c changes the decision | b) × E[ |U(new best) − U(current best)| | change ]
```

- **P(change):** the discriminator's job. For c=4 (code execution) on "did the file save?", P(change) is high when the tool's Beta-ledger reliability is middling — the observation is genuinely informative. For c=1 (more inference) on a tier-1 chit-chat turn, P(change) ≈ 0 — a better-phrased greeting doesn't change any action. This is where the equation bites hardest: *most candidate computations on most turns have VoI ≈ 0*, because the decision is already determined. [HC on the structure; the P(change) numbers are [UK] until measured — this is the same discriminator-accuracy problem as learn-frontier-reasoning.md §1, now generalized to all ten computations.]
- **Magnitude:** bounded by the stakes. On tier-1 (reversible, trivial), even a decision-flip is worth little. On tier-3 (irreversible), a flip can be worth enormously. This is why the equation *automatically* spends more on high-stakes turns — no separate "be careful" rule needed; the stakes live inside the utility function. The risk tiers (learn-math-for-jarvis.md §3) are the discretized version of this. [HC]

**Cost(c) — the price side.** Five currencies, one equation:

```
Cost(c) = λ_L·L(c) + λ_T·T(c) + λ_M·M(c) + λ_E·E(c) + λ_R·R(c)
```

| Currency | What it is | JARVIS concrete value | When it dominates |
|---|---|---|---|
| **L — latency** | Wall-clock seconds the user waits | Voice path: p50 ≤ 2s budget (reliability spec S2). A 10× tree search (10–20× slower) is *unaffordable* on voice regardless of VoI | Voice turns; interactive chat |
| **T — tokens** | Inference compute on the 2060 | ~35–45 tok/s on Qwen2.5-7B Q4. 1,000 extra tokens ≈ 25s. The budget is *time*, not just money | Local tier; long contexts |
| **M — money** | Cloud API spend | Tier-2 cloud calls; ~$0.20/task figures for flash models (scout, Oct 2026) | Cloud tier; high-volume background work |
| **E — energy** | Watts × time on the user's machine | 2060 ≈ 160W under load; the efficiency trio (BitNet/LLMLingua-2) exists to cut this | Always-on tier; laptop-on-battery (future) |
| **R — risk** | What goes wrong *because* you computed | c=4 (code exec) can have side effects; c=9 (ask) spends trust (C_t); c=5 (simulation) can be mistaken for reality | Irreversible-adjacent computations; the trust account |

- **The λs are exchange rates**, not constants. λ_L is huge on the voice path (every 100ms matters) and ~0 for background batch work. λ_M is ~0 for the local tier and dominant for cloud. The routing rule "voice → tier 0, chat → tier 1" (brain spec) is the λ-configuration made static. [HC on the structure; every λ is [UK] until measured — §4.]
- **Risk deserves emphasis** [HC]: most metareasoning treatments price computation in time/tokens only. For JARVIS, R is load-bearing: asking the user too often destroys the trust account (asking-economics §6), executing code to "check" something can itself break things, and simulation results can be confused with observations (learn-research-frontiers.md: "never confuse a simulated result with an observation"). A computation with negative expected risk-adjusted value must lose *even if* its VoI is positive.

### 1.4 The myopic approximation — and its known failure

Computing the full EU(c) requires predicting, for each computation, the distribution over *observations it might produce* and the *decisions those would imply* — a tree one level deeper than the task itself. Russell & Wefald's practical answer: **myopic metareasoning** — evaluate each computation as if it were the *last* one before acting (one-step lookahead), pick the max, repeat.

```
loop:
    c* = argmax_c EU_myopic(c | b)     # one-step lookahead only
    if c* == STOP or EU(c*) < 0: break
    execute c*, update b with observation
act on argmax_a EU(a | b)
```

- **Why myopic is the right default** [HC]: the full sequential metareasoning problem is intractable (it recurses — deciding how to decide how to decide). One-step lookahead with re-planning after each observation captures most of the value, because each real observation collapses the uncertainty the deeper lookahead was hedging about. This is the same reason the asking-economics file prices questions one at a time.
- **The known failure — greedy myopia** [HC, already flagged in asking-economics §6 and bounded-rationality]: a computation with negative myopic value can be the *gateway* to a positive-value sequence (e.g., retrieval looks worthless until you retrieve the schema that makes the symbolic check possible). The mitigation is not deeper lookahead — it's **macro-actions**: bundle known-useful sequences ("retrieve schema → run symbolic check") as a single c in the action set, priced as a unit. The bundle's VoI is computed on the *final* observation, so the gateway problem disappears by construction. Design rule: the computation set C should contain bundles for every known-useful pipeline, not just atomic computations. [DESIGN]
- **Metalevel overhead discipline** [VC, inherited]: evaluating EU(c) for ten computations must cost ≪ the cheapest computation. The equation is evaluated as **arithmetic on ledger values** (Beta parameters, tier constants, token counts) — never a model call. If pricing the computation costs more than the computation, the controller is the tax. Target: ≤1% of turn compute.

### 1.5 The asking rule as a special case

Set c = 9 (ask the user). Then VoI(c) = G_u + G_a + G_c and Cost(c) = C_i + C_t + C_l — exactly the asking-economics pricing (learn-asking-economics.md §3.1), with C_t (trust erosion) living inside the R currency and G_c (corrigibility) inside the magnitude term via stakes. The unified ask rule *is* the adaptive-computation equation with one computation plugged in. This is a consistency check on both files: the general equation reproduces the special case without modification. [VC on the structural claim.]

---

## 2. The stopping rule — when "good enough" is optimal

### 2.1 The formal stop condition

From the loop in §1.4, stopping is optimal exactly when:

```
STOP  iff  max_c EU(c | b) < 0   AND   aspiration satisfied
```

Two conditions, not one. The first says no computation pays for itself. The second — the aspiration level — is satisficing (Simon, 1955; already in bounded-rationality): even if some computation has positive EU, stop if the current best action already meets the aspiration threshold for this task's stakes.

- **Why both** [HC]: EU < 0 alone can stop too early on high-stakes tasks (a €-scale decision deserves the extra check even when the equation is uncertain about its own VoI estimate — the equation's *inputs* are uncertain, and uncertainty about VoI should bias toward more care on tier-3, not less). The aspiration level is the fail-safe: tier-3 tasks have aspiration = "verified by an independent channel," which no amount of EU<0 can waive. This mirrors the asking-economics standing rule: *absence of measurement never relaxes a safety term.*
- **Aspiration by tier** [DESIGN, proposed]: tier-1: "an answer exists" (any coherent response). Tier-2: "the action is the best of the considered options" (no obvious better alternative). Tier-3: "an independent channel confirms" (deterministic check, second observation, or user confirmation — never the same computation that produced the plan).

### 2.2 The 2-attempt debugging rule, derived

The Debugging Decay Index (learn-ai-for-se.md): the 1st fix attempt helps, the 2nd is marginal, the 3rd+ *degrades* (up to 80% drop by round 5). In the equation's terms:

- Attempt 1: VoI high (the obvious bug is often the real bug), Cost = 1 round. EU > 0. Go.
- Attempt 2: VoI lower (the easy hypotheses are exhausted; P(change) drops), Cost same. EU ≈ 0. Marginal.
- Attempt 3+: VoI *negative* — not just small, but negative, because repeated failed attempts corrupt the context (the model starts "fixing" things that weren't broken — the measured degradation). **Cost now includes R: the risk of breaking working code.** EU < 0. Stop.

The 2-attempt rule is the equation's output for the specific computation c = "try another fix" under the measured VoI-decay curve. It's not a separate heuristic — it's what the math says when you plug in the measured numbers. [HC on the derivation; the decay curve itself is literature-measured, cited in learn-ai-for-se.md.]

**Generalization** [DESIGN]: every *repeated* computation type gets its own decay curve, measured, not assumed. "Re-read the file" probably decays slower than "try another fix" (observations don't corrupt context the way failed edits do). "Ask the user again" decays fastest (the H-answer-quality decay, asking-economics §7.5). The stopping rule is per-computation-type: stop type c when its *marginal* EU goes negative, even while other types still price positive.

### 2.3 Satisficing vs optimizing — when each wins

- **Optimize** (keep computing while EU > 0) when: stakes are high (tier-3), the decision is hard to reverse, and computation is cheap relative to the mistake. The equation handles this automatically — high magnitude keeps EU positive longer.
- **Satisfice** (stop at aspiration) when: the remaining uncertainty is *irreducible* (no computation in C can resolve it — e.g., the user's unstated preference), or the decision is cheap to reverse (tier-1: just act and let the user correct you — the correction *is* the computation, purchased at ~zero cost).
- **The deep point** [HC]: the optimal policy is almost never "always optimize" or "always satisfice" — it's *the equation itself*, which optimizes the metalevel decision and thereby produces satisficing behavior at the task level exactly when satisficing is optimal. Satisficing isn't a rival to the math; it's what the math outputs under low stakes and irreducible uncertainty.

---

## 3. Fixed vs adaptive — when routing beats pipelines

### 3.1 What the literature says (updated with 2026 work)

| Finding | Source | Number |
|---|---|---|
| Difficulty routing cuts inference cost | Snell et al. 2024 (already indexed) | 3–10× vs uniform max-pipeline |
| Three-path adaptive routing (τ₁=0.3, τ₂=0.7; budgets c=1/2/6) | ODAR, arXiv:2602.23681 (Feb 2026) | +20.2% on IMO 2025, +12% on HLE vs frontier baselines, at lower cost |
| Lagrangian-relaxation budget allocation, matched budget | cited in kriraai.com survey (2026) | +12.8% accuracy vs uniform allocation |
| Calibrated difficulty prediction, negligible overhead | Sonata framework (2026) | <0.1% overhead for the difficulty estimator |
| Overthinking: extra compute *hurts* on easy tasks | Wei et al. 2025; Yang et al. 2025 (via ODAR) | Easy inputs degrade under excessive deliberation |
| Thinking ceiling: test-time compute can't fix missing knowledge | CS8803-LLM 2026 (R-ratio analysis) | ~0 gain on hardest tier regardless of budget |

**The picture** [HC]: adaptive routing is no longer a hypothesis — it's the deployed consensus by 2026 (all major API providers expose thinking budgets as product tiers). The open question for JARVIS is not *whether* but *how cheap the router can be* on a 6GB card.

### 3.2 When adaptive wins — the three preconditions

Adaptive routing beats a fixed pipeline iff all three hold:

1. **Difficulty variance is high.** If every turn is equally hard, routing saves nothing — the router's classifications are noise and the overhead is pure cost. JARVIS's workload *is* high-variance (chit-chat vs multi-step PC control vs tier-3 confirmations), so this holds. [HC]
2. **The difficulty signal is cheap and better than chance.** Sonata's <0.1% overhead is the existence proof for LLM inference; JARVIS's router can be cheaper still — it doesn't need a learned difficulty estimator on day one. Tier (from the skill manifest) + turn type (voice/chat/background) + belief-ledger variance are *already-computed* signals. The router is arithmetic on values the system already holds — cost ≈ 0. [HC on the design claim; the "better than chance" part needs the measurement in §4.]
3. **The cost of being wrong about difficulty is asymmetric in the safe direction.** Over-estimating difficulty wastes compute (recoverable); under-estimating it on tier-3 skips verification (unrecoverable). So the router errs upward: *when uncertain, route to the more expensive path.* This is the same fail-safe direction as every other safety term in the knowledge base. [VC on the principle.]

### 3.3 When adaptive does NOT win — the honest boundaries

1. **Uniform workloads.** A JARVIS deployment that only ever does one thing (e.g., voice Q&A) should use the fixed optimal pipeline for that thing. Routing is overhead with no variance to exploit. [HC]
2. **The knowledge barrier.** The R-ratio finding: on the hardest tier, more thinking gives ~0 gain — the model lacks the knowledge, not the compute. Adaptive routing must include the **escalate-or-abstain** path (strategies 7/8 of the 8-table), not just "spend more." A router that only chooses *how much* to think, and never *whether thinking can help*, will burn budget on the unthinkable. [HC — this is the most under-appreciated boundary in the routing literature, which focuses on easy-vs-hard and under-discusses impossible.]
3. **Estimator cost exceeds savings.** If the difficulty signal required a separate model call, the router would need to save more than one call's worth of compute on average. JARVIS's already-computed signals dodge this, but any *future* learned estimator must clear this bar explicitly. [DESIGN constraint]
4. **Latency-dominated paths.** On the voice path (p50 ≤ 2s), there is no time to route *and then* think — the routing decision must be made from pre-turn signals (tier, history, modality), not from a "think a little, then decide whether to think more" probe. Two-phase routing (cheap probe → route) is a chat-path luxury. [HC]

### 3.4 The JARVIS routing architecture (proposed)

Three layers, cheapest first — the equation's static approximation:

```
Layer 0 — pre-turn static route (cost ≈ 0, always on):
    inputs: risk tier (manifest), modality (voice/chat/background), turn type
    voice      → single-pass ReAct, tier-0/1 model, no search, EVER
    chat t1/t2 → single-pass ReAct, tier-1 model
    chat t3    → single-pass + mandatory independent verification
    background → whatever the budget allows (this is where search lives)

Layer 1 — mid-turn metalevel check (arithmetic on ledger, ≤1% overhead):
    after each tool observation, evaluate EU(c) for c in {re-observe, verify, escalate, stop}
    using Beta-ledger reliability, tier stakes, and the decay curves (§2.2)
    → this is the equation running, but only over the 4 cheapest computations

Layer 2 — full adaptive (later, measured):
    the complete 10-computation equation, enabled per-turn-type after §4's
    measurement program yields the λs and the P(change) curves
```

Layer 0 is the brain spec's router, unchanged. Layer 1 is the new contribution of this file: *the equation running in miniature on every turn.* Layer 2 is the aspiration, gated on measurement. [DESIGN — proposed, unbuilt.]

---

## 4. What must be measured — every parameter, marked

The equation is a shape until these have numbers. Ranked by load-bearing importance:

| # | Parameter | What it is | Measurable on the 2060? | How |
|---|---|---|---|---|
| 1 | **P(change) per computation type** | How often does each of the 10 computations actually change the decision? | Partially — needs the agent loop running, which needs the 2060 | Instrument: log (computation, belief-before, decision-before, decision-after) for 500+ turns; P(change) = flips/total. The single most load-bearing number in the file. |
| 2 | **λ_L per modality** | The latency exchange rate: how much is 1s of user waiting worth? | Voice: partially (budget exists: p50 ≤2s) | Voice: barge-in/abandonment timing vs latency (revealed preference). Chat: reply-latency tolerance A/B. Background: ~0 by definition. |
| 3 | **Decay curves per repeated computation** | VoI of the n-th "try again" / "re-read" / "re-ask" | Yes — the harness can run this | Golden-set ablation: success rate vs attempt number, per computation type. The debugging-decay curve is the template. |
| 4 | **T(c), tokens per computation** | Deterministic-ish; measure don't assume | Yes — trivially, on the 2060 | Log token counts per computation type; the 2060's tok/s converts to latency directly. |
| 5 | **E(c), energy per computation** | Watts × seconds | Yes — nvidia-smi logging during the benchmark weekend | Part of the benchmark spec's instrumentation (learn-benchmark-spec.md). |
| 6 | **Difficulty-signal quality** | Are tier+modality+variance better than chance at predicting P(change)? | Yes — once P(change) is measured (#1) | Correlation of the cheap signals with measured flips. If ~0, the router is decoration — kill it (FAILED-first discipline). |
| 7 | **M(c), money per cloud computation** | Priced by the provider | N/A (not 2060) — from price sheets | Provider pricing × measured tokens. Updates quarterly. |
| 8 | **R(c), risk per computation** | The hardest currency: what breaks *because* you checked | No — needs production incident data | Near-miss logging + the trust-erosion measurement (asking-economics §7.2). Until measured: R assumed ≥0, and large for ask-on-tier-3-skipping. |
| 9 | **Aspiration thresholds per tier** | What counts as "good enough" | No — needs Owais as rater | Stated preference + revealed preference (does he correct tier-1 answers? how often?). |
| 10 | **The λ cross-rates** | λ_L vs λ_T vs λ_M: the actual exchange (is 1s of voice latency worth 500 tokens?) | Partially | Derived from the modality budgets + #2. These are *policy* as much as measurement — Owais sets the voice latency budget, the math converts. |

**Standing rule** [DESIGN, inherited from asking-economics §7]: until a parameter is measured, its prior errs fail-safe — P(change) assumed *low* for expensive computations (don't spend on unproven gains), λ_L assumed *high* on voice (never trade latency for quality there without Owais's explicit call), R assumed *non-negative* (checking is never assumed free).

---

## 5. Failure modes — when the math lies

### F1. Miscalibrated P(change) — the discriminator problem, generalized
The equation is only as good as its P(change) estimates, and those estimates come from the same machinery whose accuracy is the open question (learn-frontier-reasoning.md: tree search needs ≥90% discrimination). If P(change) is systematically overestimated, the controller *overspends* — the "thoughtful" agent that burns 10× compute for 0 gain. **Defense:** the standing rule (§4) — assume low P(change) for expensive computations until measured; the Layer-1 miniature (§3.4) only prices the 4 cheapest computations, bounding the damage of miscalibration. [HC]

### F2. Goodhart on V — optimizing the proxy for decision quality
VoI is computed against *estimated* utility, and the estimate can be gamed — by the model (reward hacking the verifier, learn-frontier-reasoning.md §1) or by the metric (a "decision changed" that changed only cosmetically). **Defense:** VoI's magnitude term must be grounded in *downstream* outcomes (task success, user correction rate), never in intermediate scores (plan "quality" ratings, self-reported confidence). The belief ledger's Brier-score discipline (learn-math-for-jarvis.md §6) applies to P(change) estimates too: bin the predictions, check the calibration. [HC]

### F3. Overthinking — computation with negative true VoI
Wei et al. 2025 / Yang et al. 2025 (via ODAR, 2026): on easy tasks, *more* deliberation degrades performance — the model talks itself out of the right answer. The equation predicts this correctly *if* P(change) accounts for it (P(harmful change) > 0), but a naive "more compute = weakly better" prior gets the sign wrong. **Defense:** the decay curves (§2.2) must be allowed to go *negative*, and the Layer-0 static route must *forbid* search on the voice path regardless of what the equation says — a structural backstop above the math. [HC]

### F4. The estimator eats the savings
A learned difficulty estimator that costs one model call must save more than one call on average. The subtler version: *attention* spent on metareasoning is attention not spent on the task (context window is finite). **Defense:** the ≤1%-overhead discipline (§1.4) and the already-computed-signals design (§3.2). If a proposed router can't prove its overhead budget on paper, it doesn't ship. [VC on the principle.]

### F5. Myopic lock-in — the gateway problem (§1.4)
Covered in §1.4: mitigated by macro-action bundles, not deeper lookahead. Listed here for completeness — it's the failure mode most likely to be *rediscovered* during implementation, because every greedy controller eventually meets a gateway. [HC]

### F6. λ drift — exchange rates that silently change
λ_M changes when providers reprice. λ_L changes when Owais's patience changes (or the modality mix shifts). A tuned controller rots as its λs drift. **Defense:** the λs live in *config*, not code — versioned, reviewable, with a quarterly re-measurement trigger. The config-tuning discipline (learn-math-for-jarvis.md §5: random search over ranges, never hand-tuned constants worshipped as truth). [DESIGN]

### F7. The equation as theater — math that justifies what was already decided
The most human failure mode: the team (or the agent) wants the expensive pipeline, so P(change) gets estimated generously until the equation blesses it. **Defense:** pre-registration (learn-bayesian-design.md's registry rules — no, the Cycle-3 appendix: *no experiment without a pre-registered criterion*), and the FAILED-first discipline: the equation's predictions are *logged* (predicted VoI vs realized outcome — the prediction-log infrastructure, crew Cycle 18), and systematic overprediction is a bug report against the controller, not a tuning opportunity. [HC — this is a process defense, and process defenses only work if followed.]

---

## 6. What we'd implement first — the cheapest version that still helps

Not the equation. The equation is the *destination*; the implementation path is three steps, each shippable alone:

**Step 1 — Layer 0 static router (already specified, ~0 new work).**
The brain spec's tier × modality router IS the equation's static approximation with the λs hardcoded by judgment. Ship it as-is. It captures ~80% of the routing value (Snell's 3–10× comes mostly from not sending easy queries to the max pipeline — a static rule does that).

**Step 2 — The stopping rule as code (~1 day).**
Implement §2 as deterministic logic, not as the full equation:
- Per-computation-type attempt caps from the decay intuition: fix=2, re-read=3, re-ask=2 (all tunable, all logged).
- The aspiration check per tier (§2.1) as a gate before any Layer-1 computation.
- Log every stop decision with its reason (cap hit / aspiration met / EU-negative-estimate).
This is the 2-attempt rule generalized — the single highest-ROI piece of this file, because it *prevents* waste rather than optimizing spend.

**Step 3 — Layer-1 miniature (after Step 2's logs exist).**
Once the stop-decision logs give us empirical P(change) for the 4 cheapest computations, fit the one-step equation to *those four only*. If the fitted controller beats the static caps on the golden set (pre-registered: ≥5pp task-success or ≥20% compute saved, Wilson CIs), promote it. If not, keep the caps — the FAILED-first discipline means a null result here is a *finding*, published in the log, not a failure.

**Explicitly NOT first:** the full 10-computation equation, any learned difficulty estimator, λ tuning beyond the hardcoded modality budgets. Those are Layer 2 — gated on §4's measurement program, which needs the 2060 benchmark weekend and production data. [DESIGN — proposed build order.]

---

## 7. Confidence tags

- **[VC]:** the equation's structure (Russell & Wefald metareasoning — textbook); VoI ≤ decision-change value (Howard); the asking rule as special case (structural identity with learn-asking-economics.md); the ≤1%-overhead discipline; myopic-with-replanning as the tractable default; the λ-drift and theater failure modes as process risks.
- **[HC]:** the five-currency cost model (structure right; the R currency's load-bearing role is the file's main claim); the 2-attempt rule derived from decay curves; the three preconditions for adaptive-winning; the knowledge-barrier boundary; macro-bundles as the myopia fix; the Layer 0/1/2 build order; the 2026 literature numbers (ODAR, Sonata, Lagrangian — single-source each, recent).
- **[MC]:** the exact attempt caps in Step 2 (intuition + one measured curve, generalized); the "80% of routing value is static" estimate (plausible from Snell, unproven for agents); that Layer-1's 4-computation miniature is the right scope (judgment call).
- **[SP]:** whether the fitted Layer-1 controller will beat static caps (genuinely unknown — that's why it's a gated experiment, not a plan).
- **[UK]:** every parameter in §4's table; whether P(change) is estimable well enough for the equation to beat heuristics at all (the load-bearing unknown of the entire file).

## 8. Unknowns (ranked)

1. **P(change) measurability** — if the flip-rate of computations is too noisy to estimate from 500 turns, the equation never gets off the ground and the static caps are the permanent answer. (§4.1)
2. **Whether Layer 1 beats Layer 0** — the gated experiment in Step 3. A null result is informative, not a failure.
3. **The R currency's true shape** — risk-of-computation is the least theorized term; the literature prices time and tokens, not trust. (§4.8)
4. **Cross-computation interactions** — the equation prices computations independently (myopic); bundles handle known pipelines, but unknown interactions (does verification change the value of a later retrieval?) are unmodeled. Second-order; revisit after Layer 1 works.
5. **Multi-turn horizons** — the equation is per-turn; the *session*-level compute budget (don't burn the month's cloud budget on Monday) is a separate controller above this one. Named, not designed.

## Integration notes

- **Consumes:** learn-frontier-reasoning.md (8 strategies → the "more inference" computation family; the discriminator problem → F1); learn-asking-economics.md (the ask rule → §1.5 special case; the Lagrange/budget machinery → §3.2.3); learn-math-for-jarvis.md §3 (VoI, asymmetric loss → the gain side and the tier discretization); learn-ai-for-se.md (Debugging Decay → §2.2); learn-bounded-rationality.md (satisficing, myopia, ≤5% metalevel).
- **Produces:** the metalevel controller spec — equation, stopping rule, Layer 0/1/2 architecture, measurement table, build order — ready to wire into the brain's turn loop after the 2060 benchmark weekend.
- **Feeds:** DECISION-PLAYBOOK.md — ADR candidate: *"JARVIS v2 shall implement metalevel compute control as Layer-0 static routing (tier × modality) plus a deterministic stopping rule (per-type attempt caps, tier aspiration gates), with the full EU(c) = VoI(c) − Cost(c) equation gated on measured P(change) curves and λ calibrations. Status: PROPOSED — Layer 0/Step 2 buildable now; Layer 1/2 await measurement."*
- **Resolves:** the open question from the directive's Domain III — "formulate the decision problem mathematically" — done in §1. The "compare against fixed strategies under the same budget" is specified as the Step-3 gated experiment, not claimed in advance.

---

## References

- Russell, S. & Wefald, E. *Do the Right Thing: Studies in Limited Rationality.* MIT Press, 1991. (Metareasoning; value of computation; myopic approximation. The foundation of §1.)
- Howard, R.A. (1966), "Information Value Theory," *IEEE Trans. Systems Science and Cybernetics*, 2(1). (VoI — the gain side.)
- Simon, H.A. (1955), "A Behavioral Model of Rational Choice," *QJE*. (Satisficing — the aspiration level.)
- Snell, C. et al. (2024), "Scaling LLM Test-Time Compute Optimally can be More Effective than Scaling Model Parameters." (Difficulty routing; 3–10×; the easy/medium/extreme trichotomy.)
- ODAR: "Principled Adaptive Routing for LLM Reasoning via Active Inference," arXiv:2602.23681 (Feb 2026). (Three-path routing τ₁=0.3/τ₂=0.7, c=1/2/6; overthinking finding via Wei et al. 2025, Yang et al. 2025; +20.2% IMO 2025.)
- Sonata framework (2026, via kriraai.com survey): calibrated difficulty prediction at <0.1% overhead.
- Lagrangian-relaxation adaptive compute allocation (2026, via kriraai.com survey): +12.8% accuracy under matched budget vs uniform.
- R-ratio / thinking-ceiling analysis (CS8803-LLM, Georgia Tech, Spring 2026): test-time compute ~0 gain on the hardest tier (knowledge barrier).
- Bergstra & Bengio (2012) — random > grid (for the λ-tuning discipline, §5 F6).
- Brier (1950) — the calibration discipline for P(change) estimates (F2 defense).
- All knowledge-base-internal citations (learn-*.md) as listed in Integration notes.

*Honest scope:* the equation is derived, not validated. The 2026 literature numbers are single-source and recent. Every parameter the equation needs is unmeasured — §4 is the measurement program, and §6 gates every implementation step on its results. This file is a specification awaiting data, labeled as such throughout.
