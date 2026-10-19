# The Belief Ledger — JARVIS's Calibrated Confidence Substrate

**PHASE INFINITY — Research Cycle 16.** Written 2026-10-19. LEARNING ONLY — no project code touched, no installs, no experiments run, no claims fabricated.

**Research question:** How does JARVIS maintain calibrated confidence over everything it believes and does?

**Answer in one paragraph:** As a single SQLite table of Beta(α,β) entries — one per tool, strategy, claim-type, source-tier, and judge — where every entry is a conjugate Bayesian posterior over a repeatable binary event, updated by six precise evidence-type rules, decayed lazily toward its class prior via a power-prior discount (half-life per subject type), invalidated (never silently rotted) on regime change, queried through a sub-millisecond arithmetic-only API that serves the stopping rule, the VoI gate, ask/act/escalate, and strategy routing, and calibrated against reality by a quarterly Brier/reliability-diagram loop with per-bin bias correction. The ledger is the one place in the architecture where "how sure are we?" has an auditable answer: every probability resolves to visible pseudo-counts with evidence IDs attached.

**Confidence tags:** [VC] >95% · [HC] 80–95% · [MC] 60–80% · [SP] 40–60% · [UK] unknown. **DESIGN** = derived proposal, unmeasured.

---

## 1. Audit — what prior cycles assumed about the ledger (referenced, not re-researched)

Every prior cycle fed or read a ledger that was never designed whole. The requirements, collected:

| Cycle | What it needs from the ledger | Status in this file |
|---|---|---|
| Math (Beta-Bernoulli) | "Three integers per tool": Beta(α,β) per tool; auditable counts behind every reliability number | §2, §3 U1 |
| Math (Brier + reliability diagrams) | Brier score on confidence statements; quarterly reliability diagrams; FRIDAY per-bin bias correction | §6 |
| Math (VoI) | P(wrong) from measurement, never vibes; "information has no value unless it can change a decision" | §5 (voi_gate) |
| Bounded rationality (3-gate stopping) | Gate C: P(action correct) vs aspiration τ; τ adapts from logged (τ_used, outcome); metalevel ≤5% overhead | §5 decision 1 |
| Bounded rationality (8-strategy table) | Per-strategy success estimates for tier routing; Thompson-sampling-compatible | §5 decision 4 |
| Self-verification (judge TPR/FPR) | Per-judge (TPR, FPR) from calibration sets; belief update b₁ = FPR·b₀/(FPR·b₀+TPR·(1−b₀)); unmeasured judges must be inert | §2, §3 U3 |
| Self-verification (least-privilege) | Checkers write to the ledger, never into prompts; confidence from measurement, not introspection | §3 (all rules) |
| Causal discovery (replay) | Counterfactual replay as the measurement arm; replay fidelity weights simulated evidence | §3 U2 |
| Causal discovery (attribution) | Raw failure rates conflate tool/environment/caller faults — updates must be cause-routed | §3 U1 preamble |
| Memory write gate | (strength, confidence) pairs; ECAN decay with half-lives | §2 derived fields; §4 |
| Underspecification (ask/act/escalate) | P(wrong interpretation) from *measured* discriminator accuracy; cost-asymmetric VoI | §5 decision 3 |
| Evaluation science | Wilson CIs on every reported rate; Brier/ECE metrics; `point (CI, n)` reporting | §2, §6 |
| Conformance (Cycle 9) / Audit (Cycle 15) | Batch verdict ingestion; miscalibration flags flow to the audit | §3 U4; §6 ladder |
| Resolution (Cycle 14) | Winning strategy gains on observed outcome, not on selection | §3 U5 |

**Genuinely new in this cycle:** the entry schema, the six update rules stated precisely, the lazy power-prior decay, principled invalidation, the query API with its four served decisions, the ledger's self-calibration loop, and the worked example. Nothing here re-derives a prior cycle's result.

---

## 2. Ledger schema — what a ledger entry is

### 2.1 The entry

```sql
ledger_entry(
  subject_id      TEXT PRIMARY KEY,   -- e.g. "tool:web_fetch", "strategy:react",
                                     -- "claimtype:price_quote", "sourcetier:T2",
                                     -- "judge:entailment_v3:tpr", "tool:web_fetch|argclass:novel_domain"
  subject_type    TEXT,               -- TOOL | TOOL_ARGCLASS | STRATEGY | CLAIMTYPE | SOURCETIER | JUDGE | LEDGER_SELF
  label           TEXT,               -- human-readable
  alpha           REAL,               -- Beta posterior parameter (fractional allowed)
  beta            REAL,               -- Beta posterior parameter
  prior_alpha     REAL,               -- class prior: the fixed point of decay
  prior_beta      REAL,
  half_life_days  REAL,               -- decay rate for this subject type
  evidence_ids    TEXT,               -- JSON array: last 64 event IDs (ring buffer);
                                     -- full observation history lives in the event store
  updated_at      REAL,               -- unix time of last touch (update or decay)
  version_key     TEXT,               -- invalidated when this changes (model id, tool version, prompt hash)
  status          TEXT,               -- active | invalidated | suspect_regime
  queries_30d     INTEGER             -- for eviction ranking
)
```

**Derived at query time** (after lazy decay, §4) — the (strength, confidence) pair the memory-write-gate study specified, now with exact definitions [DESIGN]:

- `mean = α/(α+β)` — the point estimate.
- `strength = α+β` — effective evidence weight; how hard the estimate is to move.
- 95% interval `(lo, hi)` — normal approximation on the Beta, clipped to [0,1]: `mean ± 1.96·√(αβ/((α+β)²(α+β+1)))`. (Wilson interval used in the worked example where counts are integral; both are [HC]-adequate here.)
- `confidence = 1 − (hi − lo)` — a 0–1 summary: 0.19 for a uniform prior (honest ignorance), →1 as evidence accumulates.

The query returns an `Estimate = (mean, lo, hi, strength, confidence, as_of)`.

### 2.2 Subject taxonomy — the bounded set

The ledger stays small by rule: **entries exist only for repeatable event classes the brain actually queries.** Individual claims, individual tool calls, and raw observations are *events*, not entries — they live in the event log and are *consumed* by entries.

| subject_type | Subjects | Seeded prior | Half-life | Evictable? |
|---|---|---|---|---|
| TOOL | one per tool (~40) | class prior of its tool class | 90 d | **never** (core set) |
| TOOL×ARGCLASS | ≤8 per tool; *coarse* arg features only (never raw args — cardinality + privacy) | parent tool's posterior (hierarchical, §7) | 30 d | yes — lowest `strength·ln(1+queries_30d)` first |
| STRATEGY | the 8 reasoning strategies | Beta(2,2) each (neutral; Thompson sampling explores) | 180 d | never |
| CLAIMTYPE | ~12 claim types (price_quote, date, code_correctness, …) | Beta(2,2) | 90 d | never |
| SOURCETIER | T0–T4 (5) | Beta(2,2) | 180 d | never |
| JUDGE | per judge × {tpr, fpr} (two Beta entries each) | **Beta(1,1) — an unmeasured judge is mathematically inert** (its likelihood ratio ≈ 1; §3 U3) | 180 d | never |
| LEDGER_SELF | `ledger:self:brier_30d` — the ledger's own rolling Brier | n/a | n/a | never |

Initial tool-class priors [SP — starting values, data overwrites them]: code-exec 0.80@10 → (8,2); web-read 0.80@10 → (8,2); messaging 0.90@10 → (9,1); system-control 0.75@10 → (7.5,2.5); media 0.85@10 → (8.5,1.5).

**Size bound:** core set ≈ 70 entries (never evicted) + ≤8 argclass entries per tool, hard cap **512 entries**. At cap, the lowest-scoring evictable entry is archived (not deleted — the audit trail survives). The brain queries ≤4 subjects per decision; all are indexed lookups.

### 2.3 Design invariants

1. **Lazy creation:** an entry is created on first query/update, seeded from its class prior. Nothing is pre-registered.
2. **Decay is not evidence:** touching an entry for decay updates `updated_at` but appends no evidence ID.
3. **Every probability has a receipt:** `(α,β)` must reconcile with replaying the entry's evidence IDs against the event store. The quarterly audit checks this (§6).
4. **No model calls on the write path or the query path.** Updates are arithmetic; queries are arithmetic. (The squeeze: an LLM never judges the ledger, and the ledger never asks an LLM how sure it is.)

---

## 3. Update rules per evidence type

**Rule U0 — lazy decay first (applies before every rule below).** On read or update at time `t` (last touch `t₀`): apply the §4 decay, *then* apply the update. Ordering matters: fresh evidence must not be decayed in the same instant it arrives. [DESIGN]

**Rule U1 — tool success/failure (the simple case), with causal routing.** On an observed tool outcome:
1. **Attribute first** (learn-causal-discovery §4): consult the causal-claims graph for the failure's PN-ranked cause. If the attributed cause is *context* (network_timeout, provider_degraded — PN high, monotonicity holds): do **not** touch the tool's entry — the tool didn't fail, its environment did. Route the failure to the *provider/context* entry instead. If the cause is *agent-side* (bad args): penalize the *caller policy* entry (the strategy that generated the args), not the tool. Only unattributed-or-tool-caused failures do `β += 1`; successes do `α += 1`.
2. Append the event ID to `evidence_ids`.

This is the cycle's central correction to the naive Beta-per-tool ledger: raw failure rates conflate "tool is unreliable" with "tool is called badly" with "network is flaky" — three failures, three fixes, one number. Cause-routed updates keep each number meaning one thing. [DESIGN, derived from learn-causal-discovery — HC on the principle, MC on how often attribution is available at update time; when attribution is unavailable, the update goes to the tool entry and the event is flagged `unattributed`]

**Rule U2 — counterfactual replay outcome (updates the strategy, never the tool).** A sandbox replay asks "would strategy S′ have succeeded on this trace where S failed?" This is *simulated* evidence about decision strategies:
- Winner strategy: `α += w_replay`; loser strategy: `β += w_replay`, where `w_replay ∈ (0,1]` is the replay fidelity score (sandbox fidelity assessment from the causal cycles; default **0.5** [SP]).
- **Never `w_replay = 1`:** simulated evidence must not outweigh real evidence. A replay is a lab result, not a field result.
- **Replay never updates TOOL entries** — the tool didn't run; there is no observation of the tool. (Category error the naive design makes; stated explicitly so it isn't.)
- Append the replay ID as evidence.

**Rule U3 — judge verdicts (weighted by the judge's own measured TPR/FPR).** A judge `J` with measured rates `TPR_J = P(challenge | claim false)`, `FPR_J = P(challenge | claim true)` (two JUDGE-type Beta entries, updated only from gold-labeled calibration data) issues a verdict on a claim. The claim's posterior is computed **transiently** (claims are not ledger subjects — §2.2) by exact odds-form Bayes [DESIGN, HC on the math]:

1. Prior: combine the claim-type and source-tier entries as independent evidence streams — `(α,β) = (1,1) + (excess_ct) + (excess_st)` where excess is pseudo-counts above the (1,1) base. [MC — the streams aren't fully independent; mild over-sharpening is possible. The calibration loop's reliability term (§6) detects it and the FRIDAY correction compensates. Stated, not hidden.]
2. Fold each verdict via its likelihood ratio. For verdict `challenge`: `LR = TPR_J / FPR_J`; for `uphold`: `LR = (1−TPR_J)/(1−FPR_J)` — applied to the odds of the verdict's *favored* hypothesis. Multiple verdicts multiply (conditional independence given truth assumed [MC]; least-privilege evidence and different-model critics are the mitigation).
3. Report the posterior mean `m` exactly; report the interval from a **moment-matched Beta with the prior's strength** — `(m·S, (1−m)·S)` where `S` is the combined prior strength. Rationale: verdicts *reweight* belief about this claim; they don't add independent evidence mass. Ten correlated judges piling on cannot manufacture certainty. [DESIGN]
4. **The least-privilege theorem of this rule:** an unmeasured judge has prior Beta(1,1) on both rates → expected LR ≈ 1 → its verdicts move nothing. *A judge earns influence by being measured, not by being loud.* This is Cycle 7's least-privilege judging made quantitative.

*Mini-example (hand-computed):* claim-type `price_quote` entry (18,2), source-tier T2 entry (36,4) → combined (53,5), prior mean 0.914. Judge with TPR=0.8, FPR=0.1 challenges: posterior `P(true) = 0.1·0.914/(0.1·0.914 + 0.8·0.086) = 0.0914/0.1602 = 0.57`, interval ≈ [0.44, 0.70]. One challenge from a decent judge moves 0.91 → 0.57. The same challenge from a weak judge (TPR=0.55, FPR=0.45): posterior = 0.897 — barely moves the needle, exactly as designed.

**Rule U4 — conformance/audit batch updates (large, but capped).** An audit examines `n` items of a class, finds `k` failures (gold labels — the highest-quality evidence the system gets):
- `α += (n−k)·w_audit`, `β += k·w_audit`, with `w_audit = 1.0` for random samples, `< 1` for targeted/adversarial samples (which oversample failures by design).
- **Anti-hijack cap:** no single batch may contribute more than **50% of the entry's post-update strength**. One bad audit — mislabeled, mis-sampled, or malicious — cannot capture the ledger. [DESIGN]
- Append the audit batch ID as one evidence pointer (not n IDs — the ring buffer is for pointers, the audit report holds the item list).

**Rule U5 — resolution outcomes (the winner gains on outcome, not on selection).** When the brain runs candidate resolutions/strategies and selects one:
- Update the winner's STRATEGY entry **only on the observed downstream outcome** (did the winner actually succeed?): success → `α += 1`, failure → `β += 1`.
- The selection event itself is evidence about the *selector*, not the strategy — it updates nothing.
- Losers get **nothing** unless the resolution was a true A/B with an observed loser outcome. Absence of evidence is not evidence of absence. [DESIGN]

**Rule U6 — claim verification outcomes (ground truth).** A claim verified true/false against ground truth (not a judge — a judge is U3):
- Update the CLAIMTYPE entry (`α` or `β` += 1) **and** the SOURCETIER entry (`α` or `β` += 1). Both move: the claim-type base rate and the tier's reliability. This is how source tiers earn and lose trust over time.
- Append the verification event ID to both entries.

---

## 4. Decay and non-stationarity — old evidence counts less, honestly

### 4.1 The decay rule (lazy, toward the class prior)

On every read/update, before anything else:

```
λ = 2^(−Δt / half_life_days)          # Δt in days since updated_at
α ← prior_α + (α − prior_α)·λ
β ← prior_β + (β − prior_β)·λ
```

Properties [HC on the math, DESIGN on the choice]:
- The **class prior is the fixed point**: an entry with no evidence sits exactly at its prior; ancient evidence regresses the entry *toward the prior*, never toward 0.5 or toward zero. Forgetting means "return to what things of this class are usually like," not "return to ignorance."
- **Evidence mass determines memory**: a (48,3) entry barely moves in a month; a (9,2) entry nearly dissolves (§7 works this out). This falls out of the math, not from a special case.
- **This is exactly a power prior** (Ibrahim & Chen 2000 [VC — verified this cycle]): the historical pseudo-counts are raised to `a₀ = 2^(−Δt/h)` while the initial prior stays fixed. The ledger's decay is not an ad-hoc hack; it is the standard Bayesian treatment of historical data under heterogeneity, with a time-varying discount. The half-life table (§2.2) is the `a₀` schedule.

**Why time-based, not count-based:** evidence arrives irregularly. A count window lets one bad afternoon (50 tool calls during an outage) erase a year of history; time-based decay treats "no news" as mild evidence of stability. **Guardrail:** effective-strength cap `N_max` per subject type (tools 500, strategies 200, others 100): excess pseudo-counts above the cap are scaled down proportionally. No entry becomes immovable. [DESIGN]

**Convergence note:** this decay is the continuous-time cousin of the Beta reputation system's forgetting factor (Jøsang & Ismail 2002 [VC — verified this cycle]) and the half-life-weighted evidence pattern now standard in agent-reputation scoring. Independent convergence on the same shape is weak evidence it's the right shape [HC].

### 4.2 Half-life schedule (initial values [SP] — data overwrites)

TOOL 90d · TOOL×ARGCLASS 30d · STRATEGY 180d · CLAIMTYPE 90d · SOURCETIER 180d · JUDGE 180d. Rationale: tools drift with provider behavior (quarterly); thin argclass entries regress fast (they're the most overfit-prone); strategies and judges move only when the brain or the judge changes — which triggers §4.3 anyway.

### 4.3 Regime-change invalidation — principled, never silent rot

Every entry carries a `version_key`: for TOOLs, the tool version + arg-schema hash; for STRATEGYs and JUDGEs, the model id + prompt hash. When the key changes:

1. **Full invalidation** (model swap, tool rewrite, judge re-prompt): the entry's `status → invalidated`, `(α,β)` reset to the class prior, and the old entry **archived** with `(invalidated_at, reason, final_α, final_β)`. The brain sees a thin entry — wide intervals, conservative decisions — instead of stale confidence wearing a fresh face. The archive keeps the audit trail: "we used to believe X with this much evidence, then the world changed."
2. **Partial change** (tool args extended, logic unchanged): no reset — instead the entry's half-life is **halved** (accelerated decay). Old evidence still counts, but fades faster under the new regime. [DESIGN]
3. **Suspected regime change** (no version bump, but the world moved): CUSUM-lite — if the last 20 outcomes' empirical rate falls outside the decayed entry's 99% interval, set `status = suspect_regime`: queries return the **conservative bound** (`lo` for success probabilities), and the entry is prioritized for fresh evidence (verification bar lowered per §5). Either the world confirms the new rate (entry re-converges) or it was noise (entry relaxes back). [DESIGN, MC]

What invalidation is *not*: silent. There is no path by which an entry's numbers quietly stop meaning what they meant. Every invalidation is an event with a reason, visible to the audit.

---

## 5. Query interface — what the brain asks, and the four decisions it serves

### 5.1 The API (pure functions; no model calls, ever)

```python
Estimate = (mean, lo, hi, strength, confidence, as_of)   # §2.1

ledger.p_success(subject, arg_pattern=None) -> Estimate
    # P(this plan step / strategy succeeds). Applies U0 decay, then the
    # novelty backoff (§7) when arg_pattern has no direct evidence.

ledger.p_true(claim_type, source_tier, judge_verdicts=[]) -> Estimate
    # P(this claim is true). Prior from claim-type × source-tier (U3 rule);
    # judge verdicts folded by exact odds-form Bayes.

ledger.voi_gate(p_wrong, cost_wrong, cost_verify) -> (verify: bool, margin: float)
    # verify ⟺ p_wrong × cost_wrong > cost_verify. The VoI one-liner as a function.

ledger.route(strategies, context) -> [(strategy, sampled_theta)]
    # Thompson sampling: draw θ_s ~ Beta(α_s, β_s) per eligible strategy,
    # rank by draw. Probability matching — explores in proportion to uncertainty.
```

**Latency budget:** SQLite (WAL mode, indexed `subject_id`) + in-process LRU cache (hot entries, 60s TTL) + arithmetic. Target **p99 < 1ms per query**, ≤4 queries per decision → <4ms per decision, inside the ≤5% metalevel envelope (learn-bounded-rationality). The query path never touches a model, a network, or the event store — only the decayed `(α,β)` row. [DESIGN]

### 5.2 The four served decisions

**Decision 1 — the stopping rule's confidence gate (Gate C).** Gate C fires when the *lower bound* `lo` of `p_success(chosen action)` ≥ `τ(tier, stakes)` — the lower bound, not the mean, because the gate must be robust to thin evidence. The aspiration threshold `τ` adapts per learn-bounded-rationality §3.3, and the ledger is what makes the adaptation *measurable*: it logs `(τ_used, gates_fired, outcome)` per decision, so the dynamics ("budget gates fire constantly + outcomes succeed → lower τ") run on data, not vibes.

**Decision 2 — the VoI computation's P(wrong).** `p_wrong = 1 − p_true(...)` for claims, `1 − p_success(...)` for actions. The ledger is the **only sanctioned source** of `p_wrong` — never the brain's verbalized confidence (Cycle 7's ban: raw stated confidence is systematically overconfident, CLAIM-CAL ECE ≈ 0.21). `voi_gate` then decides: verify ⟺ `p_wrong × cost_wrong > cost_verify`. "Information has no value unless it can change a decision" is now a function call.

**Decision 3 — the ask/act/escalate rule's consequence weighting.** Learn-underspecification §3.1 step 6: `C_wrong = P(wrong interpretation) × cost(action)`; ask ⟺ `VoI(ask) > C_ask`. `P(wrong interpretation)` is read from the ledger — the intent discriminator is a JUDGE-type entry with measured (TPR, FPR), exactly the "P(wrong) needed from *measured* discriminator accuracy" requirement. Costs come from the risk tiers. The hard gates (divergent × irreversible → ask, always) remain as overrides above the arithmetic.

**Decision 4 — tier-routing in the 8-strategy table.** The router calls `p_success` per eligible strategy (eligibility pre-filtered by the modality matrix — never S3/S4 without a measured ≥90% discriminator, never best-of-N on voice), then `route()` Thompson-samples: each strategy's Beta is sampled, strategies ranked by draw. Probability matching means the router **explores strategies in proportion to how plausible it is that they're best** — no epsilon-greedy constant to tune, no UCB bonus to calibrate, and the exploration automatically shrinks as evidence accumulates. On the voice path the sampling policy is computed offline per the modality rules (Cycle 7: the POMDP runs offline to set policies, not online per turn). [DESIGN]

---

## 6. Calibration of the ledger itself — who watches the watchers

A ledger can be precisely wrong: perfectly self-consistent pseudo-counts that don't predict reality. The calibration loop closes that gap.

### 6.1 The prediction log

Every query that feeds a decision logs `(prediction_id, subject_id, p_stated, correction_version, timestamp, context_hash)`. Outcomes join later via event IDs (tool-call events, verification events, audit gold labels). This is the dataset everything below runs on. [DESIGN]

### 6.2 Scores — Brier with the Murphy decomposition

Per subject type, rolling 30-day and quarterly: **Brier score** `BS = (1/N)Σ(pᵢ − oᵢ)²`, decomposed per Murphy (1973) [VC — verified this cycle]:

```
BS = RELIABILITY  −  RESOLUTION  +  UNCERTAINTY
```

- **Reliability** (calibration proper): do events happen at the stated rate? The term the loop minimizes.
- **Resolution** (sharpness): does the ledger *discriminate* — issue different probabilities for different situations? A ledger that always predicts the base rate is perfectly calibrated and perfectly useless; the resolution term catches that. Response to low resolution: *finer subjects* (split the entry), not more of the same evidence.
- **Uncertainty**: the base-rate noise term — irreducible, reported for context, never "optimized."

Brier is **strictly proper** (DeGroot & Fienberg 1983 [VC — verified this cycle]): the ledger cannot improve its score by stating probabilities it doesn't believe. The scoring rule is incentive-compatible with honesty — a property worth naming because most of the system's other feedback loops are not.

### 6.3 Reliability diagrams + ECE, quarterly

Ten equal-width bins over `p_stated`; plot bin mean confidence (x) vs empirical outcome rate (y); perfect calibration is the 45° diagonal. **ECE = Σ(|Bₖ|/N)·|acc(Bₖ) − conf(Bₖ)|** (Naeini et al. 2015; Guo et al. 2017 [VC — verified this cycle]). Expect the classic shape: overconfidence in the mid-high bins (points below the diagonal) — the same direction as LLM verbalized confidence, though the ledger's numbers come from counts, not introspection.

### 6.4 Recalibration — FRIDAY's per-bin correction as a versioned layer

When a bin shows systematic bias `bₖ = observedₖ − statedₖ`, apply the empirical correction at query time:

```
p_calibrated = clip(p_stated + b_bin(p), 0, 1)
```

This is the FRIDAY 3-line RLCD from learn-math-for-jarvis §6 ("if the reliability diagram shows systematic overconfidence in the 60–80% bins, subtract the measured bias"). Two architectural points [DESIGN]:
- The correction is a **query-time layer with a version number**, not a rewrite of history. Raw `(α,β)` entries stay auditable; `correction_version` is logged with every prediction (§6.1), so any past decision can be replayed with or without the correction.
- Isotonic regression on the quarterly batch is the heavy alternative; the per-bin additive correction is the online patch. Both are honest about the same fact: *the ledger's raw counts were systematically off here, and now we say so.*

### 6.5 The miscalibration response ladder

| Trigger | Response |
|---|---|
| ECE > 0.10 or any bin \|bias\| > 0.15 | (1) Apply per-bin correction automatically. |
| Correction persists 2 quarters running | (2) **Widen**: queries return the conservative bound as the headline; lower the verification bar for that subject type (gather more evidence where the ledger is weakest). |
| Reliability term worsening 3 quarters running | (3) **Flag to the audit** (Cycle 15 arm) + mark entries `suspect_regime` (§4.3): the miscalibration may be the world changing, not the ledger erring. |

### 6.6 The meta-entry — the ledger watches itself

`ledger:self:brier_30d` tracks the ledger's own rolling Brier score across all subject types. If the meta-Brier degrades while per-type scores look fine, the substrate itself is suspect (e.g., the outcome labels are corrupt — garbage labels make a calibrated ledger that predicts garbage). The audit's first question on a meta-Brier regression is always: **are the labels still trustworthy?** [DESIGN]

---

## 7. Worked example — the full lifecycle of one belief

Tool `web_fetch`, entry `(α=47, β=3)` — 94% observed over 50 effective trials. Class prior for web-read tools: `(8,2)` (0.80 @ strength 10). A call arrives with a **novel argument pattern** (URL from a never-seen domain class). All numbers hand-computed; Wilson intervals exact, Beta intervals by normal approximation (flagged where used).

**Step 1 — base rate lookup.** `p_success("tool:web_fetch")` → mean `47/50 = 0.94`. Wilson 95% CI (n=50, p̂=0.94): center `(0.94 + 1.9208/50… )` — computed: `[0.838, 0.979]` → reported **0.94, 95% CI [0.84, 0.98]**, strength 50, confidence `1 − 0.141 = 0.86`. The ledger is quite sure about the tool *in general*.

**Step 2 — novelty discount (no direct evidence → back off toward the class prior).** No `tool:web_fetch|argclass:novel_domain` entry exists. The backoff rule [DESIGN]: treat the parent's history as transferable evidence with similarity weight `s`, without double-counting the prior —

```
excess_parent = (α_parent − α_prior, β_parent − β_prior) = (47−8, 3−2) = (39, 1)
(α, β)_pattern = (α_prior, β_prior) + s · excess_parent
```

With `s = 0.3` (novel pattern, low similarity): `(8 + 11.7, 2 + 0.3) = (19.7, 2.3)` → **mean 0.895 ≈ 0.90**, strength 22, 95% CI (normal approx) `[0.77, 1.00]`, confidence 0.77. The estimate moved from 0.94 toward the class prior 0.80 *and* got wider — both the location and the uncertainty respond to novelty. Endpoints sanity-check: `s=1` recovers the full parent posterior; `s=0` recovers the bare class prior.

**Step 3 — the VoI decision (verify: a cheap test exists).** `p_wrong = 1 − 0.90 = 0.10`. Cost of being wrong: a failed fetch wastes ~2 min of agent time plus a retry ≈ **150 s** equivalent. Cost of verification: a cheap HEAD pre-check ≈ **5 s**. `voi_gate`: `0.10 × 150 = 15 > 5` → **VERIFY**, margin 10 s of expected value. (On a high-stakes variant the gate would use the conservative bound `1 − 0.77 = 0.23` instead of the mean — the Estimate carries both, the stakes pick which.)

**Step 4 — post-execution update.** Pre-check passes, full fetch succeeds. Rule U1 on the pattern entry (now created, seeded from the backoff estimate): `(19.7, 2.3) + success → (20.7, 2.3)` → mean `20.7/23 = 0.90`, strength 23. One success on a novel pattern *barely moved the needle* (0.895 → 0.900) — correct: a single observation shouldn't outweigh the transferred prior. The tool entry also updates: `(48, 3)` → mean `48/51 = 0.941`, strength 51.

**Step 5 — 30 days later (decay does its job).** No further observations on this pattern. Lazy decay (U0) with half-life 30d → `λ = 0.5`, toward class prior (8,2):
- Pattern entry: `α = 8 + 12.7·0.5 = 14.35`, `β = 2 + 0.3·0.5 = 2.15` → **mean 0.87**, strength 16.5, CI [0.71, 1.00], confidence 0.71.
- Tool entry (half-life 90d → `λ = 2^(−1/3) ≈ 0.794`): `α = 8 + 40·0.794 = 39.75`, `β = 2 + 0.794 = 2.79` → **mean 0.934**, strength 42.5.

The contrast is the design working as intended: the well-evidenced tool entry barely budged (0.941 → 0.934) while the thin pattern entry regressed toward the class prior and widened (0.90 [0.77, 1.00] → 0.87 [0.71, 1.00]). **Evidence mass determines memory.** A month of silence on a one-observation belief correctly restores near-prior humility; a month of silence on a fifty-observation belief correctly changes almost nothing.

---

## 8. Honest scope — what the ledger does NOT do

1. **No one-off judgments.** Bayes needs a likelihood — P(evidence|hypothesis) — and novel situations don't have one (learn-math-for-jarvis §2). The ledger tracks *repeatable* event classes. For the unrepeatable, the Conscio evidence-tagged confidence (measured / derived / asserted / none) stays the right tool. Forcing one-off judgments into Beta entries would be precision theater.
2. **No causal attribution by itself.** The ledger records outcomes; the causal-claims graph attributes them (learn-causal-discovery §4). Rule U1's routing preamble is the seam between them — and when attribution is unavailable, the ledger says `unattributed` rather than guessing.
3. **Not a fact store.** Memories carry (strength, confidence); the ledger carries *rates*. "The backup completed at 02:14" is a memory. "web_fetch succeeds 94% of the time" is a ledger entry. Conflating them reintroduces the category errors the write gate was built to prevent.
4. **Garbage labels in, calibrated garbage out.** The ledger is only as honest as its outcome labels. The meta-entry (§6.6) and the audit are the backstops — the ledger cannot detect its own label corruption, only its statistical symptoms.
5. **Cold start is honest ignorance, not failure.** Until entries have data, decisions run on priors with wide intervals and conservative bounds. The ledger's first virtue is saying "I don't know" with a number attached.

---

## 9. Integration map — who reads and writes the ledger

```
counterfactual replay ──U2──▶ STRATEGY entries ──▶ router (Thompson sampling)
tool executions ──U1 (cause-routed)──▶ TOOL / provider / caller-policy entries ──▶ Gate C, p_wrong
judge verdicts ──U3 (TPR/FPR-weighted)──▶ transient claim posteriors ──▶ verification gate
audits (conformity Cycle 9, audit Cycle 15) ──U4 (capped batches)──▶ class entries ──▶ miscalibration flags
resolutions (Cycle 14) ──U5 (outcome, not selection)──▶ STRATEGY entries
ground-truth verifications ──U6──▶ CLAIMTYPE + SOURCETIER entries ──▶ p_true priors
                                                         │
calibration loop ◀── prediction log + outcome joins ─────┘
   ├── quarterly: Brier (+REL/−RES/+UNC), reliability diagrams, ECE
   ├── FRIDAY per-bin correction (versioned query-time layer)
   └── miscalibration ladder → widen → gather → audit-flag → suspect_regime
```

**ADR candidate (for DECISION-PLAYBOOK.md):** *"JARVIS v2 shall implement the belief ledger as specified in learn-belief-ledger.md: a SQLite table of Beta(α,β) entries over the bounded subject taxonomy (§2.2), updated by rules U0–U6 (§3), decayed lazily toward class priors via the power-prior discount (§4), invalidated on version-key change (§4.3), queried through the arithmetic-only API (§5.1) serving Gate C, VoI's P(wrong), ask/act/escalate weighting, and Thompson-sampled strategy routing, and self-calibrated by the quarterly Brier/reliability loop with FRIDAY per-bin correction (§6). Rationale: six prior cycles assumed this substrate; unifying it makes every 'how sure are we?' answer auditable to visible pseudo-counts with evidence IDs. Status: PROPOSED — schema and rules are design; all rates, half-lives, and priors are initial values awaiting production data."*

---

## 10. Evidence table

| Claim | Source | Confidence |
|---|---|---|
| Beta(α,β) conjugate updating: success → α+1, failure → β+1; mean α/(α+β) | Murphy, *PML: An Introduction* (2022); Gelman et al., *BDA* 3rd ed. | [VC] |
| Brier score BS=(1/N)Σ(p−o)²; strictly proper (forecaster can't gain by lying) | Brier (1950); DeGroot & Fienberg (1983) | [VC] |
| Brier decomposition BS = REL − RES + UNC (reliability/resolution/uncertainty) | Murphy (1973) — verified this cycle via search | [VC] |
| Reliability diagrams (10 bins, 45° diagonal); ECE = Σ(Nₘ/n)\|Acc−Conf\| | DeGroot & Fienberg (1983); Naeini et al. (2015); Guo et al. (2017, ICML) — verified this cycle | [VC] |
| Temperature scaling / per-bin bias correction as recalibration | Guo et al. (2017); FRIDAY per-bin curves (in-repo prior cycle) | [HC] |
| Beta reputation system: opinions ↔ Beta PDFs; discounting + consensus operators; forgetting factor | Jøsang & Ismail (2002), Bled — verified this cycle | [VC] |
| Power prior π(θ\|D₀,a₀) ∝ L(θ\|D₀)^a₀π₀(θ), a₀∈[0,1]; ledger decay is the power prior with a₀=2^(−Δt/h) | Ibrahim & Chen (2000), Statist. Sci. 15:46–60 — verified this cycle | [HC] (equivalence is exact algebra; the time-varying-a₀ use is our design) |
| Thompson sampling (probability matching) for routing under uncertainty | Thompson (1933) — standard | [VC] |
| Wilson score intervals for reported rates | Wilson (1927); Agresti & Coull (1998) — via learn-evaluation-science | [VC] |
| Judge belief update b₁ = FPR·b₀/(FPR·b₀+TPR·(1−b₀)); judge quality = (TPR,FPR) from holdout | learn-self-verification-calibration §6 (AutoMix adaptation; "Noisy but Valid") | [HC] |
| Cause-routed updates (don't penalize the tool for context causes) | learn-causal-discovery §4 | [HC] on principle; [MC] on attribution availability |
| VoI: verify ⟺ p_wrong × cost_wrong > cost_verify; "no value unless it can change a decision" | Howard (1966); learn-math-for-jarvis §3 | [VC] on principle; [MC] on cost numbers |
| Half-life schedule, class priors, s=0.3 novelty default, 50% anti-hijack cap, 512-entry cap | This cycle's design choices | [SP]/DESIGN — initial values, data overwrites |
| Worked-example arithmetic (Wilson [0.84,0.98]; backoff (19.7,2.3); decayed (14.35,2.15)→0.87) | Hand-computed this cycle | [HC] (arithmetic checked; Beta CIs by normal approximation) |

**Real references (no fabricated citations):** Brier, G.W. (1950), *Monthly Weather Review* 78(1). Murphy, A.H. (1973) — Brier decomposition. DeGroot, M.H. & Fienberg, S.E. (1983) — proper scoring rules; reliability diagrams. Naeini, M.P. et al. (2015) — ECE. Guo, C. et al. (2017), "On Calibration of Modern Neural Networks," ICML 2017 — temperature scaling, ECE, reliability diagrams. Jøsang, A. & Ismail, R. (2002), "The Beta Reputation System," Bled eConference — Beta reputation, discounting, forgetting. Ibrahim, J.G. & Chen, M.-H. (2000), "Power Prior Distributions for Regression Models," *Statistical Science* 15:46–60 — power priors. Thompson, W.R. (1933) — Thompson sampling. Wilson, E.B. (1927); Agresti, A. & Coull, B.A. (1998) — Wilson intervals. Howard, R.A. (1966) — information value theory. Tian, J. & Pearl, J. (2000) — PN/PS (via learn-causal-discovery). Prior cycles (this knowledge base): learn-math-for-jarvis.md, learn-bounded-rationality.md, learn-self-verification-calibration.md, learn-causal-discovery.md, learn-memory-write-gate.md, learn-underspecification.md, learn-evaluation-science.md.

---

## 11. Unknowns (ranked)

1. **All rates are unmeasured.** Every (α,β) in production starts at a prior. The ledger is a designed empty vessel until the event log fills it — the first month of production is the actual experiment. [UK]
2. **Half-life schedule.** 90d/30d/180d are reasoned starting values [SP]. Too slow → stale confidence after provider changes; too fast → the ledger never accumulates enough mass to be useful. The calibration loop's reliability term is the instrument that tunes them — but the tuning procedure itself is unvalidated.
3. **The p_true combination approximation** (§3 U3 step 1): claim-type and source-tier streams aren't fully independent; the pseudo-count sum mildly over-sharpens. Bounded by the FRIDAY correction, but the bound's adequacy is unmeasured. [MC]
4. **Attribution availability at update time** (U1 preamble): how often the causal graph actually has a PN-ranked cause ready when a tool fails. If rarely, most updates stay unattributed and the cause-routing is mostly aspirational. Needs the first 50 post-mortems (learn-causal-discovery unknown #1). [UK]
5. **Judge correlation** (U3 step 2): verdicts from judges reading the same evidence violate conditional independence; the moment-matched interval (which refuses to shrink) is the mitigation, but its conservatism cost — how much real signal it discards — is unmeasured. [MC]
6. **The novelty similarity `s`.** Default 0.3 is a placeholder [SP]. What *computes* s from arg features (embedding distance? schema overlap?) is unspecified — it needs its own small study, or the backoff degrades to a magic constant.
7. **Cold-start bootstrap.** Seeding priors from literature/tool-class guesses is honest but weak. Whether to bootstrap from the 2060 shootout's golden-set runs (measured tool rates on synthetic tasks) before production is an open decision with real trade-offs (synthetic ≠ production). [UK]

---

*Honest completion (Rule 12): Researched: ledger schema design (new), six update rules U0–U6 (new, from prior-cycle requirements), lazy power-prior decay + half-life schedule + regime-change invalidation (new; power-prior equivalence verified against Ibrahim & Chen 2000, forgetting-factor precedent verified against Jøsang & Ismail 2002), query API + four served decisions (new), self-calibration loop with Brier/Murphy/ECE/FRIDAY (new; Murphy 1973 and Guo et al. 2017 verified via search), worked example (all numbers hand-computed this cycle). Validated: all four external citations checked against real sources — no fabricated references; worked-example arithmetic rechecked. Saved: this file. Tested/Measured: nothing (learning only). Incomplete: the seven unknowns above, all marked. Blocked: none.*
