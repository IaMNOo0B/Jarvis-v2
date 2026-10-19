# Bayesian Experimental Design for the Self-Improvement Loop — Research Cycle 3

*PHASE INFINITY, Cycle 3. Date: 2026-10-19. Status: researched, not validated on real workloads.*
*Learning only — no code executed, no experiments run.*

**Research question:** Can Bayesian experimental design make the self-improvement loop sample-efficient?

**Short answer:** Not at JARVIS's scale. The machinery is real and the math is sound, but for ~10 discrete configs, exhaustive evaluation is cheaper than the thinking about which experiment to run. BoED answers "what should I learn next?" — the Harness² loop's expensive step is "what should I try next?", which is a different question. Details below.

---

## 1. BoED mechanics in plain language

**The loop.** You have a prior belief about some unknown parameters θ (e.g., "which config is best", or "how much does chunk size matter"). You have candidate experiments d (e.g., "run config A on the golden set"). For each candidate, you compute the **expected information gain**:

> **EIG(d)** = expected reduction in entropy of your belief about θ after seeing the outcome of d.

Pick the d with the highest EIG, run it, update your belief with Bayes' rule, repeat. This is *sequential* or *adaptive* design — the EIG objective updates as data arrives. [VC — Rainforth et al., "Modern Bayesian Experimental Design", arXiv 2302.14545]

**Three equivalent views of EIG** (all the same quantity): [VC]
- (a) the mutual information between θ and the outcome y, given d;
- (b) the expected information gain over outcomes *simulated from your model*;
- (c) the expected reduction in entropy from observing data.

Formally: EIG(d) = E[log p(θ|y,d) / p(θ)] — the expected log-ratio of posterior to prior, i.e., how much the experiment is expected to *move your beliefs*. [VC — Foster et al., "Variational Bayesian Optimal Experimental Design", arXiv 1903.05480]

**The critical distinction the question glosses over: BoED ≠ Bayesian optimization.** [HC — this is the most important conceptual point in this note]
- **BoED (EIG)** optimizes for *learning*: which experiment teaches me most about θ? Use it when the goal is understanding (factor screening: "does chunk size matter?").
- **Bayesian optimization (EI/UCB)** optimizes for *finding*: which config is best? Use it when the goal is winning.

The Harness² probe step wants to *find the best config* — that's Bayesian optimization, not BoED. EIG would happily spend your budget learning that config #7 is *precisely* mediocre. Relevant, but only for the compose step (writing general rules like "reranking always helps").

**When BoED/EIG earns its keep** (from the literature): experiments are expensive, the design space is large, and you have a decent simulator p(y|θ,d) to imagine outcomes with. Classic wins: psychology trials (which question best reveals the trait?), sensor placement, clinical trials. [HC]

---

## 2. The JARVIS setting (concrete)

**Design space** (today): discrete choices —
model {7B, 4B} × quant {Q4_K_M, Q8_0} × chunk {256, 512} × reranker {on, off} × prompt {v1, v2} ≈ 32 combos, of which ~10 are sane (Q8 on 4B is pointless, etc.).

**Experiment cost**: one config evaluated on a 50-task golden set. Local inference ~35 tok/s; ~500 tokens/task → ~25k tokens → **~12 minutes per config** (estimate [MC] — unmeasured on the 2060). 10 configs ≈ **2 hours, exhaustive**.

**Noise**: task success is binomial. 50 tasks at p≈0.70 → standard error ≈ 6.5pp. A "5pp improvement" is inside the noise — this is why the evaluation-science study demands Wilson intervals and pre-registered minimum deltas. Any experiment-selection method must survive this noise floor.

**What the loop actually needs**: the Harness² *propose* step generates qualitative hypotheses ("add a verification step", "compress history harder") — new designs, not points in a fixed space. No EIG computation can propose a design that isn't in the candidate set. **BoED cannot do the propose step at all.** [VC — follows from the definition: EIG is defined over a fixed design set D]

---

## 3. Acquisition functions: which fits noisy, discrete, expensive agent evals?

For *finding the best config* (the actual need), the candidates:

| Function | Idea | Fit for JARVIS |
|---|---|---|
| **Expected Improvement (EI)** | Expected gain over current best, under the surrogate | Standard for BO; needs a surrogate (GP/TPE); overkill at N=10 |
| **Upper Confidence Bound (UCB)** | Mean + κ·uncertainty; κ tunes explore/exploit | Same overhead as EI; κ is a tuning parameter you now must tune |
| **Probability of Improvement (PI)** | P(config beats best) | Myopic — ignores *how much* better; rarely the right choice |
| **Thompson sampling** | Sample θ from posterior, act optimally for the sample | **Best fit for the online case**: no tuning parameters, handles discrete arms natively, degrades gracefully. The Beta-Bernoulli per-config ledger (already adopted in learn-math-for-jarvis) IS Thompson sampling for binary outcomes. [VC] |

**The practical discrete-space tool: TPE (Tree-structured Parzen Estimator)**, Optuna's default sampler. Instead of modeling p(y|x) like a GP, TPE models two densities: l(x) over *good* observed configs and g(x) over the rest, then picks the candidate maximizing l(x)/g(x). For categorical/discrete parameters it uses weighted histograms — **no kernel engineering, handles JARVIS's categorical space natively**. [VC — Bergstra et al. 2011 originated TPE; Optuna docs confirm categorical support]

**Empirical grounding for BO-vs-random** (so the verdict isn't vibes): [HC]
- Black-Box Optimization Challenge 2020: BO methods achieved **>100× sample efficiency** vs random search on ML hyperparameter tuning (top submission: 128 evals ≈ 15,512 random-search iterations). All top-20 teams used surrogate-assisted optimization. [HC — arXiv 2104.10201; single competition, real-world ML tasks]
- Snoek, Larochelle & Adams (2012): BO the preferred choice when evaluations are expensive.
- Bergstra & Bengio (2012): random search beats grid search via low effective dimensionality — the baseline discipline, already adopted.

Note the pattern: BO's wins are all in **large spaces with expensive evals**. Nobody runs BO over 10 discrete configs — there's nothing to be efficient *about*.

---

## 4. Worked conceptual example: 5 configs, EIG reasoning

Configs: A (7B·Q4·c256·rerank) | B (7B·Q4·c512·rerank) | C (7B·Q8·c256·rerank) | D (7B·Q4·c256·no-rerank) | E (4B·Q4·c256·rerank).
Prior: uniform over "which is best" (entropy = log₂5 ≈ 2.32 bits).

**Exhaustive**: 5 evals × 12 min = **60 minutes, certain answer** (modulo binomial noise, which no method escapes).

**EIG-style reasoning**: run A first (the prior favorite). Suppose A scores 72%. Posterior: A likely best, but B/C/D/E still live — entropy maybe 1.5 bits. Next-highest-EIG experiment: the config whose outcome would most change the ranking — probably C (tests "does Q8 matter?") or D (tests "does reranking matter?"). Each EIG step requires *simulating outcomes under the current belief* — nested estimation that is itself expensive and noisy at n=50 tasks.

**Honest accounting**: EIG might save 1–2 evals (12–24 min) at the cost of implementing and debugging nested EIG estimation, plus the risk that EIG's simulated outcomes mislead (the surrogate is fit on 1–4 points — garbage in, confident out). **Net: negative.** [MC — reasoning, not measurement]

**The legitimate EIG use in this setting — factor screening**: "does chunk size matter *at all*?" Run A vs B (differ only in chunk size). One experiment, high EIG about the *factor*, and the answer becomes a durable rule in the compose step ("chunk 256–512, don't sweat it"). EIG is for learning generalizable facts, not picking winners. [HC]

---

## 5. Scale-threshold analysis: when does each method win?

| Design space | Eval cost | Right method | Why |
|---|---|---|---|
| N ≤ ~15 discrete configs | minutes each | **EXHAUSTIVE** | Certainty; zero machinery; 2 hours once. **This is JARVIS today.** |
| N ~ 20–200 discrete | expensive | Random search → **Optuna TPE** | TPE handles categorical natively; `pip install optuna`; near-zero implementation cost |
| Large / continuous, evals very expensive (hours) | hours | Full BO (GP + EI) or TuRBO | The 100×-efficiency regime from the literature; GP overhead justified |
| Online selection during live use | ongoing | **Thompson sampling** (Beta-Bernoulli) | Already adopted; no tuning; explore/exploit handled by the posterior |
| "Does factor X matter?" | 1–2 evals | **EIG / factor screening** | The one legitimate BoED use: durable general knowledge |

**Thresholds are estimates** [MC] — the exact crossover depends on eval cost and noise, both unmeasured. The qualitative shape (exhaustive → random/TPE → GP-BO as space×cost grows) is well-supported. [HC]

**The noise floor caveat**: at 50 golden tasks, SE ≈ 6.5pp. Below ~10pp true differences, *no* selection method reliably picks the winner — the answer is "they're tied, pick the cheaper one." Method sophistication cannot beat binomial noise. [VC — arithmetic]

---

## 6. Complexity-vs-gain: the honest accounting

**For BoED-proper (EIG) at JARVIS scale:**
- Gain: save ~1–2 evals (~12–24 min, estimated) on a 2-hour exhaustive sweep, in the best case.
- Cost: implement nested EIG estimation; debug it; maintain it; risk of surrogate overconfidence on 1–4 data points; cannot propose new designs (the actual bottleneck of the Harness² loop).
- **Net: negative. SKIP.** [MC]

**For Optuna TPE (the practical BO tool):**
- Gain: real when the space goes combinatorial (prompt variants × thresholds × chunk sizes ≈ 100+).
- Cost: `pip install optuna`, ~20 lines. Near zero.
- **Net: positive when triggered. LATER with a defined trigger.** [HC]

**What BoED was never going to fix**: the propose step (hypothesis generation) is a *creativity* bottleneck, not a *selection* bottleneck. EIG selects among given candidates; the loop's cost is in dreaming up good candidates. Nothing in this literature proposes experiments you didn't enumerate. [VC — definitional]

---

## 7. Verdict: SKIP (now) — with LATER triggers

**SKIP** Bayesian optimal experimental design as EIG machinery for the self-improvement loop at current scale. Exhaustive evaluation over ≤15 discrete configs is cheaper, certain, and simpler. Random search is the disciplined baseline if anyone proposes "just try things."

**LATER** — adopt Optuna TPE when EITHER trigger fires:
- **Trigger 1**: the design space exceeds ~30 sane discrete configs (prompt variants multiply it fast), OR
- **Trigger 2**: a single eval exceeds ~1 hour (larger golden set, multi-seed), making exhaustive infeasible.

**Already adopted (no action)**: Thompson sampling via the Beta-Bernoulli per-tool/config ledger covers online selection; the 2-attempt fail-fast rule bounds wasted probe effort; EIG-style factor screening is approved as a *reasoning pattern* ("run the experiment that best distinguishes the hypotheses") without the nested-estimation machinery.

**Uncertainty on the verdict**: [MC]. The threshold numbers are derived estimates, not measurements. If evals turn out 10× cheaper (faster hardware) the exhaustive regime extends; if the golden set grows to 500 tasks, TPE triggers sooner. Revisit when either is measured.

---

## 8. Connections to existing knowledge

- **learn-math-for-jarvis.md**: VoI ("information has no value unless it can change a decision") is the decision-theoretic twin of EIG — EIG *is* expected VoI about θ. The Beta-Bernoulli ledger is Thompson sampling already deployed.
- **learn-evaluation-science.md**: the noise floor (Wilson intervals, pre-registered deltas) constrains every method here equally; the registry template below feeds the golden-set protocol.
- **learn-continual-learning.md**: ablation discipline ("one variable, pinned baseline") is the experimental hygiene EIG assumes but doesn't provide.
- **learn-frontier-reasoning.md**: "the verifier is the strategy" — the experiment (golden-set eval) is the verifier; EIG/BO only *schedule* verifications.
- **Harness² (AGENTS.md)**: propose → probe → compose. This study covers the probe step. Propose remains LLM-creative; compose remains rule-writing.

---

## Confidence & unknowns

- [VC] EIG definition/mechanics; BoED≠BO distinction; TPE categorical support; Thompson sampling mechanics; binomial noise floor arithmetic.
- [HC] BO >100× efficiency claim (single competition, real tasks); TPE near-zero implementation cost; "EIG can't propose designs" (definitional but worth stating).
- [MC] Threshold numbers (15/30 configs, 12 min/eval, 2-hour sweep); net-negative accounting; LATER triggers.
- [UK] Actual eval cost and noise on the 2060 (unmeasured — the benchmarking weekend resolves it); whether config effects exceed the noise floor at all (if not, the whole tuning enterprise is moot and prompt/workflow changes dominate); Hinglish golden-task variance.

## References

- Rainforth, T. et al. "Modern Bayesian Experimental Design." arXiv 2302.14545 (2024). — EIG survey; sequential BED.
- Foster, A. et al. "Variational Bayesian Optimal Experimental Design." arXiv 1903.05480 (2019). — EIG estimators in Pyro.
- "BED-LLM: Intelligent Information Gathering with LLMs and Bayesian Experimental Design." arXiv 2508.21184 (2025). — EIG as mutual information; sequential design.
- Foster, A. "Bayesian experimental design for model selection." ae-foster.github.io (2022). — EIG for model selection, worked framing.
- Snoek, J., Larochelle, H. & Adams, R.P. "Practical Bayesian Optimization of Machine Learning Algorithms." NeurIPS (2012). — BO for expensive evals.
- Bergstra, J. & Bengio, Y. "Random Search for Hyper-Parameter Optimization." JMLR 13:281–305 (2012). — random > grid; low effective dimensionality.
- Bergstra, J. et al. "Algorithms for Hyper-Parameter Optimization." NeurIPS (2011). — original TPE.
- "Bayesian Optimization is Superior to Random Search…: Analysis of the Black-Box Optimization Challenge 2020." arXiv 2104.10201. — >100× sample efficiency; all top-20 used surrogates.
- Thompson, W.R. "On the Likelihood that One Unknown Probability Exceeds Another." Biometrika (1933). — Thompson sampling.
- Howard, R.A. "Information Value Theory." IEEE Trans. Systems Science and Cybernetics (1966). — value of information.
- Optuna documentation (Preferred Networks) — TPESampler; categorical parameter support. (Via optuna.org; surveyed through secondary sources above.)

*No citations fabricated. arXiv IDs verified against search results. Cost/threshold figures are derived estimates marked [MC].*

---

## Appendix: Hypothesis / Experiment Registry template (§18 artifact #6)

*Each Harness² probe cycle gets one row. This is the "hypothesis and experiment registry" required by the directive.*

| Field | Description | Example |
|---|---|---|
| `exp_id` | EXP-YYYY-NNN | EXP-2026-014 |
| `date` | Proposed date | 2026-10-19 |
| `hypothesis` | Falsifiable claim | "Reranking improves task-success ≥5pp on the golden set" |
| `mechanism` | Why it should work | "Cross-encoder fixes dense-retrieval ranking errors on multi-hop queries" |
| `design_space` | Configs under test | {rerank on/off} × {chunk 256/512} = 4 |
| `baseline` | Frozen reference | config A (7B·Q4·c256·rerank), seed 42 |
| `method` | exhaustive / random / tpe / bandit | exhaustive (N=4 ≤ 15) |
| `budget` | Max evals / time | 4 evals, ~48 min |
| `success_criterion` | Pre-registered Δ + stats | Δ ≥ 5pp, 95% Wilson CI excludes 0 |
| `result` | Measured outcome | +7pp (95% CI 1.2–12.8) |
| `verdict` | adopt / reject / inconclusive | adopt |
| `evidence` | Pointer to logs | `evals/EXP-2026-014/` |
| `composed_rule` | What entered the playbook | "Rerank on for multi-hop; off for single-fact lookup" |
| `follow_up` | Next question it raised | "Does rerank help on Hinglish queries? → EXP-2026-015" |

**Registry rules:**
1. No experiment without a pre-registered success criterion (Rule 12).
2. `method` chosen by the scale table in §5, not by fashion.
3. Negative results get full rows (FAILED-first discipline) — a rejected hypothesis is data.
4. `composed_rule` is the only output that touches the playbook; everything else is evidence.
5. Review the registry quarterly: which hypotheses keep failing? That's a research question, not bad luck.
