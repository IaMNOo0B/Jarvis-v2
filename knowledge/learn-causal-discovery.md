# Causal Discovery for Failure Diagnosis — JARVIS Phase Infinity, Research Cycle 6

*Researched October 2026. Research question: Can causal discovery make JARVIS's failure diagnosis rigorous instead of folk wisdom?*

*Skip-if-learned check (applied): Cycle 5 already covered PC/FCI/Granger/PCMCI verdicts, the four feasibility killers (small N, hidden confounders, non-stationarity, equivalence-class blindness), the post-mortem template, fault trees, and the counterfactual-replay protocol. Those are referenced, not re-taught. This cycle's genuine gaps: **GES and LiNGAM verdicts** (never assessed), the **formal intervention literature** (Eberhardt's N−1 bound — Cycle 5 argued "interventions beat discovery" informally; the theorem was never cited), **PN/PS bounds and identification conditions** (Cycle 5 used PN/PS as a scoring habit; the Tian–Pearl machinery, exogeneity/monotonicity requirements, and what the log must capture to compute them were never specified), and the **causal-graph → belief-ledger wiring** (asserted, never designed).*

---

## 1. The two algorithms Cycle 5 skipped: GES and LiNGAM

### GES — Greedy Equivalence Search (score-based) [VC]

Chickering, D.M. (2002). "Optimal structure identification with greedy search." *JMLR* 3:507–554. (Verified via citation lists in the causal-discovery literature; the reference appears in standard bibliographies, e.g. the *Introduction to Causal Inference* reference set.)

Instead of running conditional-independence tests (PC's approach), GES searches the space of Markov equivalence classes, greedily adding then removing edges to maximize a score — typically BIC (Bayesian Information Criterion). It is *consistent*: given faithfulness and enough data, it converges to the true equivalence class. FGES (Ramsey et al. 2017) scales it to very high dimensions (demonstrated on ~1M variables in fMRI data — verified via the Springer causal-discovery chapter reference list).

- **Assumes:** causal sufficiency (same as PC — no hidden confounders), acyclicity, faithfulness. Same identifiability ceiling as PC: it returns an equivalence class, not a DAG.
- **Where it breaks for JARVIS:** (a) hidden confounders are the norm in the failure setting (provider-side changes, network state, OS state) — GES, like PC, has no honest representation for them and will assert edges that are actually confounded; (b) score functions (BIC/BDeu) assume the right parametric family — tool-call outcomes are binary/categorical with threshold effects, not the Gaussian-linear world BIC likes; (c) sample hunger per failure type is the same killer Cycle 5 identified for PC. GES is faster than PC on dense graphs but solves none of the four killers. Verdict: **same SKIP as PC, for the same reasons** [HC].

### LiNGAM — Linear Non-Gaussian Acyclic Model [VC]

Shimizu, S., Hoyer, P.O., Hyvärinen, A., Kerminen, A. (2006). "A linear non-Gaussian acyclic model for causal discovery." *JMLR* 7:2003–2030. (Verified: abstract and assumption statements read directly from the JMLR paper.) Python implementation at `github.com/cdt15/lingam`; DirectLiNGAM (Shimizu et al. 2011) improves finite-sample behavior.

The clever trick: in linear-Gaussian models, direction is unidentifiable (X→Y and Y→X fit the covariance matrix equally well). But if the noise terms are *non-Gaussian* and independent, ICA (independent component analysis) can recover the full causal order — direction becomes identifiable from observational data alone. No faithfulness assumption needed (an explicit advantage over PC).

- **Assumes:** (1) relationships are *linear*, (2) *no unobserved confounders* (the paper states this explicitly: independent disturbances ⟹ causally sufficient case), (3) disturbances are *non-Gaussian* with non-zero variance, (4) acyclicity, (5) "a large number of data vectors" observed.
- **Where it breaks for JARVIS — on every axis:** (1) tool failures are threshold/binary phenomena (timeout → fail is a step function; arg-valid → success is a logic gate, not a linear coefficient); (2) hidden confounders are the defining feature of the setting, and LiNGAM's own paper says the method *assumes them away*; (3) the "large number of data vectors" requirement collides with the N=1 novel-failure problem. Non-Gaussianity buys direction *within* linear continuous models — JARVIS's failures aren't in that world. Verdict: **hardest SKIP of all five algorithms** [HC].

**The complete algorithm scorecard** (Cycle 5's three + this cycle's two):

| Algorithm | Output | Key assumption that kills it for JARVIS | Verdict |
|---|---|---|---|
| PC | CPDAG (equivalence class) | Causal sufficiency — no hidden confounders | SKIP (Cycle 5) |
| FCI | PAG (admits latent confounding) | Sample hunger + super-exponential CI testing | SKIP (Cycle 5) |
| GES | Equivalence class (score-based) | Causal sufficiency, again | SKIP (this cycle) |
| LiNGAM | Full DAG (ICA trick) | Linearity + no confounders + continuous data | SKIP (this cycle) |
| Granger | "Causality" (prediction) | Predictability ≠ mechanism | SKIP (Cycle 5) |

The pattern is the finding: **every observational discovery algorithm either assumes away the setting's hardest feature (hidden confounders) or answers a question JARVIS doesn't need answered (the full graph).** [HC]

---

## 2. The intervention advantage — the formal version

Cycle 5 argued informally that JARVIS's sandbox makes it an experimentalist, not an observer. The literature says exactly how much that buys:

**Eberhardt, Glymour & Scheines (2005).** "On the number of experiments sufficient and in the worst case necessary to identify all causal relations among N variables." *UAI 2005*, pp. 178–184. (Verified: abstract and theorem statement read from the authors' draft at `its.caltech.edu/~fehardt/papers/EGS_draft2006.pdf` and the UAI 2005 reference entry.)

> Under familiar assumptions (no latent variables, perfect data), **N−1 experiments that randomize at most one variable are always sufficient — and in the worst case necessary — to identify the full causal graph among N > 2 variables.**

Why this matters for JARVIS:

1. **Equivalence-class blindness dissolves.** The single biggest objection to observational discovery (Cycle 5's killer #4) is that many DAGs fit the same CI pattern. A single-variable intervention orients every edge incident to the intervened variable. N−1 such interventions orient *everything*. JARVIS's failure-relevant variable set per incident is small (5–10 candidate causes); N−1 sandbox replays is trivially affordable. [VC for the theorem; HC for the cost claim]
2. **Interventions are robust to the hidden-confounder problem that kills PC/GES.** Randomizing X breaks all incoming arrows to X — including unmeasured ones. An intervention on X identifies the X→Y effect *even when latent confounders exist* (this is why randomized trials work in medicine). So interventions don't just add information; they specifically neutralize the assumption PC and GES die on. [HC]
3. **Active learning chooses which intervention.** Murphy (2001) and Tong & Koller (2001) frame experiment selection as expected information gain — pick the intervention that most reduces graph uncertainty. For JARVIS: when a post-mortem has two tied candidate causes, the replay protocol should intervene on the variable with higher expected information gain (practically: the one whose PN/PS bounds are widest). [MC — the Bayesian active-learning computation is intractable in general (Steyvers et al. note this); the heuristic version — "replay the cause with the widest bounds" — is the engineering translation]

**The formal warrant for Cycle 5's replay protocol:** the sandbox isn't a nice-to-have — it's the difference between the hard problem (observational discovery: equivalence classes, sufficiency assumptions, NP-hard search) and the easy problem (interventional identification: N−1 experiments, robust to latents). JARVIS lives in the easy problem's world. The four feasibility killers were stated for *observational* discovery; **interventions kill killer #4 (equivalence blindness) outright and blunt killer #2 (hidden confounders)**. Killers #1 (small N per failure type) and #3 (non-stationarity) remain — which is why the graph stays small, curated, and per-incident rather than global and auto-learned. [HC]

---

## 3. PN/PS — the rigorous form of "was X the cause of failure Y?"

### Definitions (Pearl 2009, ch. 9; Tian & Pearl 2000) [VC]

For binary cause X and binary outcome Y (x/x', y/y' are true/false):

- **PN** (probability of necessity) ≜ P(y'_{x'} | x, y) — given that X happened and Y happened, the probability Y would *not* have happened without X. The "but-for" cause. This is what a post-mortem means by "X caused the failure."
- **PS** (probability of sufficiency) ≜ P(y_x | x', y') — given neither happened, the probability Y *would* happen if X were introduced. The "would it fail again?" question.
- **PNS** (necessity and sufficiency) ≜ P(y_x, y'_{x'}) — the joint counterfactual.

These are *counterfactual* quantities (rung 3 of Pearl's ladder) — they cannot be read off any single dataset in general. That's the whole point: folk-wisdom diagnosis asserts PN=1 implicitly ("the timeout caused it"); PN/PS forces the number into the open.

### Bounds — what the data actually pins down (Tian & Pearl 2000) [VC]

Verified against two independent secondary sources (arXiv 2210.08453; FSU technical report r26.pdf). With experimental data P(y_x), P(y_{x'}) **and** observational data P(x,y):

```
max{0, P(y_x) − P(y_{x'}), P(y) − P(y_{x'}), P(y_x) − P(y)} ≤ PNS
PNS ≤ min{P(y_x), P(y'_{x'}), P(x,y) + P(x',y'), P(y_x) − P(y_{x'}) + P(x,y') + P(x',y)}
```

PN and PS have analogous bounds (e.g. PN ≥ max{0, [P(y) − P(y_{x'})]/P(x,y)}).

**The critical engineering reading of these bounds:** they need BOTH experimental and observational terms. With observational data only (the event log alone), the bounds collapse toward vacuous — PNS ∈ [0, 1] in the worst case. **The replay isn't optional garnish on the post-mortem; it's what makes PN/PS non-vacuous.** One interventional datapoint per candidate cause is the minimum price of a rigorous causal claim. [HC — this is the single most actionable sentence in this file]

### Point identification — when bounds collapse to numbers (Tian & Pearl 2000) [VC]

Under two conditions — **exogeneity** (no confounding between X and Y, so P(y_x) = P(y|x)) and **monotonicity** (Y never goes *down* when X goes up: no unit has y'_x ∧ y_{x'}, i.e. X never *prevents* Y):

```
PNS = P(y_x) − P(y_{x'})
PN  = [P(y) − P(y_{x'})] / P(x, y)
PS  = [P(y_x) − P(y)] / P(x', y')
```

JARVIS translation, per candidate-cause class [MC — needs per-class validation, but the structure is favorable]:

- **Exogeneity:** the sandbox replay *randomizes* the intervention (we choose to set timeout/no-timeout). Randomization breaks confounding by construction. The replay log approximately satisfies exogeneity — the cleanest assumption in the whole design, bought by the sandbox rather than asserted.
- **Monotonicity:** "fixing the hypothesized cause never turns a success into a failure." For X = *network_timeout_present* → Y = *tool_call_failed*: monotonicity says no call succeeds *with* a timeout but fails *without* one — near-tautologically true for timeouts, auth failures, malformed args. It is *checkable per failure class*: scan the log for counterexamples (x,y') ∧ (x',y) pairs. Where monotonicity fails (e.g. retry storms where retrying *causes* the failure — a genuine non-monotonic case), fall back to bounds.

**So the middle-ground identification recipe is:** observational joint from the event log + one sandbox replay per candidate cause + a per-class monotonicity check = **point-identified PN/PS**. No do-calculus engine, no full SCM, no discovery algorithm. Just the definitions, one experiment, and one checkable assumption. [HC for the math; MC for how often monotonicity holds — the checker must actually run]

### Counterfactual logging requirements (what the event log must capture)

To compute PN/PS for candidate cause X of failure Y, the post-mortem record needs:

| Requirement | Source | Why |
|---|---|---|
| Observational joint P(x, y): X and Y co-observed across runs | Event log (existing) | The P(x,y), P(y) terms in every formula |
| Experimental P(y_x): outcome under forced X | Sandbox replay log (new) | The P(y_x) term; without it bounds are vacuous |
| Experimental P(y_{x'}): outcome under forced ¬X | Sandbox replay log (new) | The P(y_{x'}) term; the "control arm" |
| Monotonicity audit: scan for (x,y')∧(x',y) counterexamples | Log query (new, cheap) | Decides bounds vs point identification |
| Intervention provenance: replay_id, exact do() setting, sandbox fidelity notes | Replay metadata (new) | Exogeneity claim rests on this; fidelity bounds transfer |
| Candidate-cause discretization: each X must be binary/categorical | Post-mortem schema (new) | PN/PS are defined for binary X,Y; continuous causes (latency) must be thresholded ("latency > 5s") |

Note the discretization requirement is a real design constraint: PN/PS in the Tian–Pearl form are binary. Continuous causes get bucketed at decision-relevant thresholds — which is fine, because the *response* is binary anyway (retry vs fix vs failover). [HC]

---

## 4. The middle-ground design — concrete proposal

### What the failure post-mortem pipeline records (schema)

Extends Cycle 5's template with the causal fields:

```
incident:
  symptom, t0, timeline, trace_ids          # Cycle 5 (unchanged)
  action:        {tool, args_hash, attempt}   # the failed call
  context_vars:  {var: value}                 # candidate causes, DISCRETIZED to binary/categorical
                     # e.g. network_timeout_present: bool, args_wellformed: bool,
                     #      provider_degraded: bool, auth_valid: bool, cache_fresh: bool
  outcome:       {success: bool, error_class, latency_bucket}
  candidates:
    - var: network_timeout_present
      pn: [lo, hi] | point                  # from log + replay
      ps: [lo, hi] | point
      monotonicity: holds | violated | unchecked
      replays: [replay_id...]               # the experimental datapoints
  verdict:       {root_cause | unresolved}
  composed_rule: WHEN [signature] THEN [fix] # Harness² compose step
  mast_cluster:  spec | coordination | verification
```

### The causal graph over tool failures (small, curated, intervention-fed)

- **Scope:** one DAG over ~10–20 failure-relevant variables (the context_vars vocabulary above), NOT over the whole system. Bounded by design.
- **Seeding:** edges proposed by experts/fault trees (Cycle 5's five critical paths), not by PC. The graph starts as prior knowledge, not discovered knowledge.
- **Updating:** each post-mortem's (x, y, do) triples update the PN/PS on the relevant edge. Edge annotated with `(pn, ps, n_obs, n_exp, monotonicity_status)`. Edges whose PN and PS stay low across incidents get pruned; edges confirmed by replay get a `measured` badge (vs `hypothesized`).
- **What it is NOT:** it is never re-learned wholesale by a discovery algorithm (non-stationarity + small N forbid it — Cycle 5's killers #1 and #3). It is a *ledger of causal claims with evidence attached*, curated by the post-mortem pipeline. Think "causal claims database," not "learned Bayesian network."

### How the graph feeds the belief ledger (the rigor payoff)

Current ledger (from learn-math-for-jarvis.md): Beta(α,β) per tool = raw success rate. The upgrade: **per (tool, cause-class) attribution** — P(fail | tool, cause), where cause comes from the causal graph's PN/PS:

- Cause = *network_timeout* (context, PN high): response = retry with backoff / switch provider. Do NOT penalize the tool's own reliability score — the tool didn't fail, its environment did.
- Cause = *bad_args* (agent-side, PN high): response = fix the call. Penalize the *caller policy* (the thing generating args), not the tool.
- Cause = *provider_degraded* (external, PN high): response = circuit-break the provider, fail over.
- Cause = *unknown* (no candidate with high PN): response = the 8-step ask/act/escalate rule fires at its diagnostic branch; the incident is flagged "unresolved" honestly rather than attributed to the nearest correlate.

**Why this beats the raw ledger:** raw failure rates conflate "tool is unreliable" with "tool is called badly" with "network is flaky" — three different failures with three different fixes, one number. Causal attribution separates them, and the response branches on the cause. This is also the compounding-reliability play (0.95²⁰ ≈ 0.36): fixing the right link shortens the *effective* chain at the right place; misattribution "fixes" a healthy link and leaves the broken one. [HC]

### The decision rule (engineering form)

```
on tool failure:
  1. log (action, context_vars, outcome)            # observational datapoint
  2. look up causal graph: candidates sorted by PN  # prior from history
  3. if top candidate PN ≥ threshold AND monotonicity holds for class:
       replay in sandbox with candidate toggled    # the intervention
       recompute PN/PS with new (do) datapoint
  4. branch on attributed cause:
       context-cause → retry/backoff/failover (don't touch tool's ledger score)
       agent-cause   → fix args, penalize caller policy
       external-cause → circuit-break provider
       unresolved    → escalate per 8-step rule, mark honestly
  5. compose WHEN/THEN rule; update graph edge evidence
```

Cost is bounded: one replay per incident (not N−1 — we only need the top candidate's control arm, because temporal order + fault-tree priors already constrain the graph; the N−1 bound is the worst case for *de novo* discovery, not for confirming a ranked hypothesis). [MC — the "one replay suffices" claim assumes the candidate ranking is good; when the top two candidates tie, replay both]

---

## 5. What to deliberately NOT build (the complexity cliff)

| Don't build | Why we stop before it |
|---|---|
| Full causal Bayesian network over the whole system | NP-hard structure learning; requires causal sufficiency, which fails by default; decisions are per-incident anyway — a global graph is machinery without a customer |
| do-calculus / ID-algorithm engine | Do-calculus answers "can I identify this effect *without* experimenting?" JARVIS can just experiment. The engine is a substitute for a lab; JARVIS owns the lab. Building it anyway is paying for a map when you can walk the terrain |
| Nightly PC/FCI re-runs over the event log | Cycle 5's four killers stand: small N per failure type, hidden confounders, non-stationarity, equivalence blindness. Chasing noise with extra compute |
| Neural causal discovery (NOTEARS et al.) | Continuous-optimization DAG learning (Zheng et al. 2018) needs large continuous datasets with soft acyclicity constraints; JARVIS's outcomes are discrete and its N is small. Wrong tool, wrong data |
| Continuous (non-binary) PN/PS machinery | The Tian–Pearl binary form covers the decision (retry/fix/failover are binary responses). Continuous extensions (Li & Pearl's general bounds) add complexity with no new decision |
| Counterfactuals for non-replayable actions | External side-effecting actions can't be re-run; mark the boundary (Cycle 5's unknown #3) and use bounds-only reasoning there — don't build a simulator to fake the experiment |

**The middle ground, stated once:** use Pearl's *counterfactual definitions* (PN/PS) as the scoring discipline and *intervention data* as the evidence source — **without** Pearl's identification machinery (do-calculus) or Spirtes's discovery machinery (PC/FCI/GES). Definitions without the heavy algorithms. That is the rigorous middle ground between "no causal machinery" (learn-math-for-jarvis.md's original scope-out) and "full Pearl." [HC — this is the cycle's thesis]

---

## 6. Verdict

**Can causal discovery make JARVIS's failure diagnosis rigorous instead of folk wisdom?** Half-yes, and the half matters:

- **Observational causal discovery (PC/FCI/GES/LiNGAM/Granger): no.** Five algorithms assessed across two cycles; every one fails on the setting's actual features. The literature is unanimous about what these methods need (causal sufficiency, large N, stationarity, parametric faith) and the event log provides none of it. [HC]
- **Interventional causal identification (replay + PN/PS): yes.** Eberhardt's N−1 bound gives the formal warrant; Tian–Pearl gives the scoring math; the sandbox gives exogeneity; per-class monotonicity checks give point identification. The event log alone can't do it (bounds vacuous without experimental terms) — **the replay is load-bearing, not optional**. [HC]
- **Net new machinery vs Cycle 5:** the discretized context_vars schema, the PN/PS bound/identification formulas with their logging requirements, the small curated causal-claims graph, and the cause-attributed belief ledger. No discovery library. No do-calculus. [HC]

Folk wisdom says "the timeout caused it." The middle ground says "PN(timeout→fail) = 0.91, point-identified, monotonicity holds for this class, evidence: 14 observational + 3 interventional datapoints" — and then retries instead of blaming the tool. That is what rigor buys: the right fix, at the right link, with the receipt attached.

---

## 7. Unknowns (ranked, Cycle 6 additions)

1. **Monotonicity hit rate** — for what fraction of real failure classes does the per-class monotonicity check pass? If it's <50%, we live in bounds-world and the point-identification recipe is a special case, not the default. Needs measurement on the first 50 post-mortems. [UK]
2. **Sandbox fidelity for the exogeneity claim** — replay randomization gives exogeneity *within* the sandbox; transfer to production is the fidelity question Cycle 5 already flagged (unknown #1). Unchanged. [UK]
3. **Discretization threshold choice** — where to bucket continuous causes (latency, queue depth)? Thresholds chosen at decision boundaries are principled; but a bad threshold can hide a real cause. Sensitivity analysis needed. [UK]
4. **Candidate-ranking quality** — the "one replay per incident" cost bound assumes the PN-ranked top candidate is usually right. Needs the n=1/n=2 eval protocol from evaluation-science. [UK]
5. **The non-replayable boundary** — unchanged from Cycle 5 (unknown #3). Bounds-only reasoning is the fallback; the exact fallback per action class still needs design-time enumeration. [UK]

---

## 8. References

- Pearl, J. (2009). *Causality: Models, Reasoning, and Inference*, 2nd ed. Cambridge University Press. — PN/PS definitions, ch. 9; the ladder. (Verified via Cambridge/Stanford catalog records.)
- Tian, J. & Pearl, J. (2000). "Probabilities of causation: Bounds and identification." *UAI 2000*. — PNS/PN/PS bounds and the exogeneity+monotonicity identification formulas. (Verified via two independent secondary sources: arXiv:2210.08453 and FSU tech report r26.pdf.)
- Spirtes, P., Glymour, C. & Scheines, R. (2000/2001). *Causation, Prediction, and Search*, 2nd ed. MIT Press. (1st ed. 1993, Springer-Verlag.) — PC/FCI foundations. (Verified via Springer chapter reference list and PMC review bibliographies.)
- Chickering, D.M. (2002). "Optimal structure identification with greedy search." *JMLR* 3:507–554. — GES. (Verified via standard causal-inference bibliographies.)
- Shimizu, S., Hoyer, P.O., Hyvärinen, A. & Kerminen, A. (2006). "A linear non-Gaussian acyclic model for causal discovery." *JMLR* 7:2003–2030. — LiNGAM; assumptions (linearity, no unobserved confounders, non-Gaussian noise) read directly from the paper. Implementation: `github.com/cdt15/lingam`.
- Eberhardt, F., Glymour, C. & Scheines, R. (2005). "On the number of experiments sufficient and in the worst case necessary to identify all causal relations among N variables." *UAI 2005*, pp. 178–184. — N−1 single-variable experiments suffice (worst-case necessary) for N>2. (Verified: theorem statement read from authors' draft.)
- Murphy, K.P. (2001). "Active learning of causal Bayes net structure." UC Berkeley tech report. / Tong, S. & Koller, D. (2001). "Active learning for structure in Bayesian networks." *IJCAI*. — experiment selection as expected information gain.
- Ramsey, J., Glymour, M., Sanchez-Romero, R. & Glymour, C. (2017). "A million variables and more: the fast greedy equivalence search algorithm…" *Int. J. Data Sci. Anal.* 3(2):121–129. — FGES scaling result.
- Prior cycles in this knowledge base: `learn-frontier-reasoning.md` (causal post-mortem discipline, PN/PS as habit, sandbox-as-lab), `learn-math-for-jarvis.md` (Pearl scope-out, Beta-Bernoulli ledger, 0.95²⁰ compounding), `learn-continual-learning.md` (MAST taxonomy 42/37/21, failure clustering), `learn-evaluation-science.md` (n=1/n=2 eval protocol).

*Honest completion (Rule 12): Researched: GES and LiNGAM verdicts (2 web searches + paper-abstract verification), Eberhardt N−1 intervention bound (theorem statement verified from authors' draft), Tian–Pearl PN/PS bounds and identification formulas (verified against 2 independent secondary sources), counterfactual logging requirements (derived from the formulas). Validated: all citations checked against real sources — no fabricated references. Saved: this file (supersedes the Cycle 5 version; Cycle 5's PC/FCI/Granger verdicts and replay protocol preserved by reference, not re-researched). Tested/Measured: nothing (learning only). Incomplete: monotonicity hit rate, discretization thresholds, candidate-ranking quality (marked UK). Blocked: none.*
