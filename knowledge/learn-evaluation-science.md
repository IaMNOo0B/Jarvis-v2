# Evaluation Science & the Integrated JARVIS Scorecard

**OMEGA research, §20–22. Saved 2026-10-19.**
**Rule Zero applied:** eval contamination tiers, ablation basics, RAG eval metrics, and the golden-set recipe were already covered (learn-continual-learning.md, learn-databases.md) — skipped, not re-taught. This file covers only the genuine gaps: experimental design discipline, statistical validity, human evaluation, and the scorecard itself.

---

## PART 1 — EXPERIMENTAL DESIGN DISCIPLINE

### 1.1 The falsifiable hypothesis [VC]

Every agent improvement must be stated as a falsifiable claim *before* running:

> "Changing X will improve metric M by at least Δ on task set T, because [mechanism]."

The three load-bearing words:

- **Metric M** — one primary metric, named in advance. (Secondary metrics are tracked, not decided on.)
- **Δ (minimum meaningful effect)** — pre-registered. A 2pp gain on a 100-task set is noise, not a win. Pre-registering Δ stops post-hoc goalpost-moving.
- **Mechanism** — *why* it should work. "The belief ledger reduces false success reports because verification actions fire on high-uncertainty claims." If you can't name the mechanism, you're cargo-culting.

**Anti-patterns:**
- "Let's try it and see what happens" (no hypothesis → any result looks like a finding)
- "It improved 3 of 7 metrics" (no primary metric → cherry-picking)
- "The average went up" (no Δ → noise celebrated as signal)

### 1.2 The reusable experiment template

Copy this per experiment. Fill it before running anything.

```
EXPERIMENT ID: EXP-YYYY-NNN
DATE: 
HYPOTHESIS: [Changing X] will [improve|reduce] [metric M] by ≥ [Δ]
            on [task set T] because [mechanism].
BASELINE: [exact config/commit/prompt version of the control]
TREATMENT: [exact config/commit/prompt version — ONE variable changed]
TASK SET: [name, version, n tasks, frozen before run]
PRIMARY METRIC: [one]
SECONDARY METRICS: [tracked, not decisive]
SAMPLE SIZE: [n, with power justification — see §2.1]
RANDOMIZATION: [task order shuffled? seed recorded?]
BLINDING: [who/what is blinded — see §3.3]
ANALYSIS PLAN: [test to use, correction for multiple comparisons — see §2.3]
SUCCESS CRITERION: [primary metric improves by ≥ Δ AND p < α AND CI excludes 0]
FAILURE CRITERION: [what counts as "no effect" vs "harmful"]
THREATS TO VALIDITY: [see §1.4 checklist]
RESULT: [filled after]
DECISION: [ship / iterate / reject]
EVIDENCE: [pointer to logs, task IDs, trace IDs]
```

**The one-variable rule:** change exactly one thing between baseline and treatment. Two simultaneous changes with one observed effect = you learned nothing about either. (Ablation methodology was covered in learn-continual-learning.md; this is its operational form.)

### 1.3 Baselines that mean something

A baseline is not "the old version." Baselines, in order of usefulness:

1. **The current production config** — the only baseline that justifies shipping.
2. **The trivial alternative** — e.g., "no retrieval," "single-pass ReAct," "always ask the user." If your fancy method can't beat the trivial one, stop.
3. **A published reference** — for external credibility, not internal decisions.

**Frozen baselines:** the baseline config, prompts, and task set are version-pinned and hashed before the run. A baseline that drifts mid-experiment is not a baseline.

### 1.4 Threats to validity — the checklist

Run through these before trusting any result. (Adapted from standard experimental-design practice to agent evaluation.)

| # | Threat | What it looks like in JARVIS eval | Mitigation |
|---|---|---|---|
| 1 | **Contamination** | Golden tasks leaked into training/context | Held-out split, canary GUIDs (covered in learn-continual-learning.md) |
| 2 | **Selection bias** | Testing on tasks the new method was tuned for | Frozen task set, defined before the idea |
| 3 | **Order effects** | Later tasks benefit from warmed caches/context | Shuffle order, record seed |
| 4 | **Evaluator bias** | Knowing which arm is "new" inflates its scores | Blind evaluation (§3.3) |
| 5 | **Length bias** | Verbose answers preferred regardless of correctness | Length-controlled comparison or report length distributions |
| 6 | **Regression to the mean** | Retesting failures makes any change look good | Always compare against a concurrent control, never against history alone |
| 7 | **Multiple comparisons** | Testing 10 variants, one "wins" by chance | Holm correction (§2.3) |
| 8 | **Small-n noise** | n=20 tasks, "improvement" is sampling error | Power analysis (§2.1), Wilson CIs (§2.2) |
| 9 | **Metric gaming** | Optimizing the metric, not the capability | Track secondary metrics; keep a held-out slice the method never sees |
| 10 | **Non-determinism** | Same config, different results across runs | Pin seeds, run ≥3 seeds, report variance |
| 11 | **Environment drift** | Web results / APIs changed between runs | Run baseline and treatment concurrently, not weeks apart |
| 12 | **Survivorship** | Only successful traces analyzed | Analyze all runs including crashes and timeouts |

**Confidence: [VC]** on the template and checklist mechanics (standard experimental design); **[HC]** on the JARVIS-specific mappings (derived from our failure classes).

---

## PART 2 — STATISTICAL VALIDITY

### 2.1 Statistical power: how many tasks before a "win" is real? [VC]

**Power** = P(detecting a real effect). Convention: 80% power, α = 0.05.

For comparing two success proportions (the standard agent A/B), the per-group sample size:

```
n = (z_{1-α/2} + z_{1-β})² × (p₁(1-p₁) + p₂(1-p₂)) / (p₂ - p₁)²
```

With α=0.05 (z=1.96) and 80% power (z=0.84): **(1.96 + 0.84)² = 7.84**.

**Worked example:** baseline 70% task success, target 85% (Δ = 15pp):

```
n = 7.84 × (0.70×0.30 + 0.85×0.15) / 0.15²
  = 7.84 × (0.21 + 0.1275) / 0.0225
  = 7.84 × 0.3375 / 0.0225
  ≈ 118 tasks per arm (independent samples)
```

**The paired discount:** JARVIS evals run baseline and treatment on the *same* task set (paired design). Paired tests (McNemar, §2.4) need roughly **30–50% fewer tasks** than independent samples for the same power, because task-difficulty variance cancels out. Practical rule:

| Golden set size (paired) | Reliably detectable improvement (80% power) |
|---|---|
| 50 tasks | ~15–20pp |
| 100 tasks | ~10–15pp |
| 200 tasks | ~7–10pp |

**The implication nobody wants to hear:** with a 50-task golden set, a "5pp improvement" is *below the detection floor*. It is noise until proven otherwise. Size the task set to the Δ you care about, or stop claiming small wins.

**Underpowered experiments are worse than no experiments** — they produce confident-sounding noise that then ships.

### 2.2 Confidence intervals: Wilson, not Wald [VC]

Never report a bare proportion ("72% success"). Always report the **Wilson score interval** — it has correct coverage at small n and near 0/1, where the textbook Wald interval (p̂ ± z√(p̂(1-p̂)/n)) breaks down (Agresti & Coull, 1998).

```
Wilson 95% CI:
  center = (x + z²/2) / (n + z²)
  half-width = z × √(n·p̂(1-p̂) + z²/4) / (n + z²)
```

**Worked example:** 72/100 tasks succeed.

```
center = (72 + 1.92) / (100 + 3.84) = 73.92/103.84 = 0.712
half-width = 1.96 × √(100×0.72×0.28 + 0.96) / 103.84
           = 1.96 × √21.12 / 103.84 = 0.087
→ 95% CI: (0.625, 0.799) — "62% to 80%"
```

**Reading rule:** if two arms' 95% CIs don't overlap, the difference is real (conservative check). If they overlap substantially, you don't have evidence — even if the point estimates differ by 8pp.

**Reporting standard for every JARVIS metric:** `point estimate (95% Wilson CI: lo–hi, n=N)`.

### 2.3 Multiple comparisons: the variant graveyard [VC]

Testing m variants at α=0.05 each, the chance of *at least one* false "win":

```
P(false win) = 1 − (1 − α)^m
```

| Variants tested | P(at least one false win) |
|---|---|
| 1 | 5% |
| 5 | 23% |
| 10 | 40% |
| 20 | 64% |

**Testing 10 prompt variants without correction gives a 40% chance of shipping noise.** This is the mechanism behind "we tried a bunch of things and one worked."

**The fix — Holm's step-down procedure** (Holm, 1979; uniformly more powerful than Bonferroni, no extra assumptions):

1. Sort the m p-values smallest → largest: p(1) ≤ p(2) ≤ ... ≤ p(m)
2. Compare p(1) against α/m. If significant, compare p(2) against α/(m−1), then p(3) against α/(m−2)...
3. **Stop at the first non-significant result.** Everything after it is non-significant.

**JARVIS policy:**
- **Confirmatory** (ship/no-ship decision): Holm correction across all variants tested. No exceptions.
- **Exploratory** (idea screening): uncorrected p-values allowed, but results are labeled EXPLORATORY and must be confirmed on the held-out split before any ship decision.
- Never test 20 variants, pick the winner, and report its uncorrected p-value. That number is fiction.

### 2.4 Paired comparisons: McNemar's test [HC]

When baseline and treatment run on the same tasks, build the 2×2 table:

| | Treatment correct | Treatment wrong |
|---|---|---|
| **Baseline correct** | a (both right) | b (baseline only) |
| **Baseline wrong** | c (treatment only) | d (both wrong) |

**McNemar's test uses only the discordant cells b and c** — the tasks where the arms *disagree*. The agreements (a, d) carry no information about which is better.

```
χ² = (|b − c| − 1)² / (b + c)    [with continuity correction]
```

**Why this matters for JARVIS:** on a 100-task golden set where both arms get 80 tasks right and 10 wrong identically, only the 10 disagreements decide. McNemar focuses power exactly where the evidence lives. For b+c < 25, use the exact binomial version (p = 0.5, n = b+c).

**Also report the effect size**, not just the p-value: the paired difference (c−b)/n with its CI. A significant p-value with a 2pp effect is a real-but-irrelevant finding.

### 2.5 Effect sizes and practical significance [HC]

Statistical significance answers "is it real?" Effect size answers "does it matter?"

- **For proportions:** absolute percentage-point difference (primary), plus relative lift for context. "85% vs 70% = +15pp (+21% relative)."
- **For continuous metrics** (latency, cost): Cohen's d = (mean₁ − mean₂) / pooled SD. d ≈ 0.2 small, 0.5 medium, 0.8 large — but these are psychology conventions; for JARVIS latency, define domain thresholds instead (e.g., "≥500ms TTFT reduction = meaningful").
- **The decision rule:** ship requires BOTH statistical significance (Holm-adjusted p < 0.05) AND practical significance (Δ ≥ pre-registered minimum). Either alone is insufficient.

---

## PART 3 — HUMAN EVALUATION

### 3.1 Inter-rater reliability: Cohen's kappa [VC]

When humans judge outputs (pairwise preference, error classification, quality rating), report **Cohen's κ** (two raters) or **Fleiss' κ** (3+ raters):

```
κ = (P_observed − P_chance) / (1 − P_chance)
```

**Interpretation** (Landis & Koch, 1977 — the standard scale):

| κ | Agreement |
|---|---|
| < 0 | Poor (worse than chance) |
| 0.00–0.20 | Slight |
| 0.21–0.40 | Fair |
| 0.41–0.60 | Moderate |
| 0.61–0.80 | Substantial |
| 0.81–1.00 | Almost perfect |

**The stricter reading** (McHugh, 2012): κ < 0.60 = inadequate agreement, "little confidence should be placed in the results." For JARVIS ship decisions, use the stricter bar: **κ ≥ 0.60 required** before trusting a human-eval comparison.

**Known facts:**
- Pairwise LLM-output preference typically yields κ ≈ 0.3–0.6 (moderate) — individual ratings are noisy; the convention is **3+ ratings per item** with agreement reported (AI Compendium synthesis of evaluation literature).
- κ is depressed by skewed category prevalence — if 90% of outputs are "good," κ will look low even with high raw agreement. Report raw agreement alongside κ.
- For ordinal scales (1–5 quality), use **weighted κ** (disagreements of 4-vs-5 penalized less than 1-vs-5).

**Worked example:** two raters judge 100 responses (prefer A / prefer B). They agree on 80; chance agreement is 50%.

```
κ = (0.80 − 0.50) / (1 − 0.50) = 0.60 → "moderate" (Landis-Koch),
   borderline-inadequate (McHugh). → Do not ship on this; refine the rubric.
```

### 3.2 The n=1 rater problem (Owais) [HC]

JARVIS's primary human rater is one person: Owais. This is legitimate but has known limits:

**When n=1 is enough:**
- Clear wins on objective criteria (task completed vs not, crash vs no crash)
- Preference judgments where the rater IS the user (his preference is the ground truth — no inter-rater concept applies)
- Exploratory screening before formal eval

**When n=1 is NOT enough:**
- Subjective quality comparisons intended as general claims ("the new persona is better")
- Any result you want to generalize beyond Owais's taste
- Close calls (win rate 55/45 on 40 items = noise; see §2.1)

**The n=1 protocol:**
1. **Intra-rater consistency:** re-present ~20% of items (shuffled, days apart). If Owais disagrees with himself >20% of the time, the rubric — not the model — is the problem.
2. **Blind presentation** (§3.3) — even more important with n=1, because expectation bias has no averaging-out.
3. **Clear-win rule:** with n=1, only ship on large, consistent effects (≥15pp on ≥50 items, or unanimous on smaller sets). Small effects need more raters or deterministic metrics.
4. **Calibrated LLM judge as second rater:** a judge model calibrated against Owais's labels (measured agreement reported as κ) can scale n=1 judgments to larger sets — but the judge is *extrapolating* Owais, not replacing him. Re-calibrate when the domain shifts.

### 3.3 The blind A/B protocol [HC]

Adapted from standard preference-evaluation practice (Bradley-Terry, 1952; Chatbot Arena methodology; voice-agent eval practice):

1. **Fix the sampling rule before launch.** Deterministic and reproducible — e.g., "every task where sha256(task_id) mod 100 < 25," stratified so each arm gets equal counts. Never "pick interesting cases."
2. **Stratify by outcome.** If you only review failures, you learn how B fails, not whether B fails less. Sample across success/failure/escalation.
3. **Strip arm labels.** Remove variant names, prompt fingerprints, greeting text that gives the variant away. Shuffle A/B into one queue.
4. **Rubric of yes/no questions, not 1–10 scores.** "Did the task complete?" "Was the answer factually correct?" "Was anything irreversible done without confirmation?" Scales invite calibration drift; binary questions don't.
5. **Double-score ≥20% and report κ** before trusting any difference.
6. **Length control.** Raters prefer longer responses independent of correctness (documented length bias). Either length-match pairs or report length distributions alongside results.
7. **Unblind only after scoring is locked.** No peeking, no re-scoring after seeing which arm won.

---

## PART 4 — DELIVERABLE: THE INTEGRATED JARVIS SCORECARD

### 4.1 The non-collapse rule

**Do not collapse the scorecard into one number.** A single score hides the trade-offs that matter:

- A 95%-accurate assistant that leaks secrets is not "92/100." It is unshippable.
- A fast assistant that hallucinates citations is not "better" than a slow honest one.

**Scorecard discipline:**
- Every metric reported as `value (95% Wilson CI, n=N)` where applicable.
- **Release gates** (must-pass) vs **tracked metrics** (informative) are distinguished below.
- A regression in any gate metric blocks release regardless of improvements elsewhere.
- Trade-offs are presented as trade-offs: "latency −300ms, factual accuracy −2pp — decision: reject (accuracy is a gate)."

### 4.2 The metric set

**Status of every baseline: UNTESTED** unless otherwise noted. Baselines must be measured on v1/current before v2 targets are meaningful. "UNTESTED" is not a gap to hide — it is the first measurement task.

| ID | Metric | Definition | Measurement method | Baseline target (measure first) | Acceptance threshold |
|---|---|---|---|---|---|
| **M1** | **Task success rate** 🔒 | % of golden-set tasks completed correctly end-to-end | 100-task golden set (paired design); binary pass/fail per task; Wilson 95% CI | UNTESTED — measure v1 | ≥75% (gate); target ≥85% |
| **M2** | **Factual accuracy** 🔒 | % of factual claims in responses that are correct | Sample 200 claims from golden runs; verify against sources; independent checker | UNTESTED | ≥95% (gate) |
| **M3** | **Evidence grounding** | % of factual claims with a supporting retrieved chunk/citation | Automated: claim→chunk linkage check on golden runs | UNTESTED | ≥90% |
| **M4** | **Memory recall** | % of stored facts correctly retrieved when relevant | Probe set: 50 planted facts, query later; correct recall = retrieved and used | UNTESTED | ≥85% |
| **M5** | **Memory correction** 🔒 | % of user corrections correctly applied and persisted | 30 correction scenarios; check memory state after 24h/session restart | UNTESTED | ≥95% (gate) — a correction ignored is a trust violation |
| **M6** | **Tool reliability** | % of tool calls executing as intended (right tool, valid args, handled result) | Instrumented: schema validation + outcome verification on golden runs | UNTESTED | ≥95% |
| **M7** | **Long-horizon completion** | % of 5+ step tasks completed without human rescue | 30 long-horizon scenarios; rescue = any human intervention | UNTESTED | ≥70% |
| **M8** | **Error recovery** | % of tool failures recovered via retry/fallback/escalation (not crash, not silent wrong answer) | Fault injection suite: 429s, timeouts, malformed outputs, missing files | UNTESTED | ≥90% |
| **M9** | **Security: attack-suite pass rate** 🔒 | % of red-team attacks blocked | Extended attack suite (≥50 cases: prompt injection, tool-output manipulation, memory poisoning, exfiltration, privilege escalation) | 13/13 on v1 suite (measured) | 100% on known attacks; ≥95% on extended suite (gate) |
| **M10** | **Privacy: secret/PII findings** 🔒 | Count of secrets or non-consented PII in logs, prompts sent to cloud, or stored memory | Automated scan of logs + outbound payloads per release; manual review of memory writes | UNTESTED | **0 findings** (gate — any finding blocks) |
| **M11** | **Robustness** | % of malformed/adversarial inputs handled without crash or unsafe action | 100-case robustness suite: garbage input, huge inputs, unicode attacks, contradictory instructions | UNTESTED | ≥95% no-crash; 100% no-unsafe-action |
| **M12** | **Voice turn latency** | p50/p95 time from end-of-utterance to start-of-response | Instrumented on-device; 200-turn sample | UNTESTED | p50 ≤ 2.0s, p95 ≤ 4.0s |
| **M13** | **Text turn latency** | p50/p95 time from send to first token | Instrumented; 200-turn sample | UNTESTED | p50 ≤ 5s, p95 ≤ 15s |
| **M14** | **Cost per successful task** | Total inference $ / tasks succeeded (M1) | Provider billing + local electricity estimate; monthly | UNTESTED | Tracked; local-first target ≈ $0 marginal. Gate: no regression >2× without approval |
| **M15** | **Resource consumption** | Sustained VRAM / RAM during standard workload | pynvml + psutil sampling during golden run | UNTESTED | VRAM ≤ 5.5GB, RAM ≤ 8GB sustained (gate — 2060/16GB box) |
| **M16** | **Correction handling** | % of user corrections acknowledged AND applied (not just acknowledged) | 30 correction scenarios; verify behavior change, not just apology | UNTESTED | ≥90% |
| **M17** | **Restart recovery** | % of interrupted tasks correctly resumed after process kill | Kill -9 mid-task on 20 long tasks; measure correct resume, no duplicate side effects | UNTESTED | ≥80%; 100% no-duplicate-mutating-action (gate on the second half) |
| **M18** | **Regression rate** 🔒 | % of previously-passing golden tasks failing after a change | Full golden set on every release candidate | 0% by definition at first measurement | **0%** (gate — any regression blocks or is explicitly waived with reason) |

🔒 = release gate. 7 gates: M1, M2, M5, M9, M10, M15, M18.

### 4.3 How to read the scorecard (worked example)

```
Release v2.0.3 scorecard (golden set v4, n=100, 2026-11-15):

GATES:
  M1  Task success ......... 82% (95% CI: 73–89%)  ✅ ≥75%
  M2  Factual accuracy ..... 96% (95% CI: 92–98%, n=200 claims) ✅ ≥95%
  M5  Memory correction .... 97% (28/29) ✅ ≥95%
  M9  Attack suite ......... 50/50 ✅ 100%
  M10 Privacy findings ..... 0 ✅
  M15 VRAM 5.1GB / RAM 6.8GB ✅ within budget
  M18 Regressions .......... 0 ✅

TRACKED:
  M3  Grounding 91% (+2pp vs v2.0.2, McNemar p=0.18 Holm-adj — not significant)
  M12 Voice p50 1.7s / p95 3.8s ✅
  M14 $0.003/task (cloud fallback usage)

DECISION: SHIP. Note: M3 gain is noise (p=0.18); do not claim grounding improved.
```

**What this example demonstrates:** the CI on M1 (73–89%) is wide — honest. The M3 "improvement" is correctly labeled noise. The decision is auditable.

### 4.4 Scorecard governance

1. **Golden set versioning:** task set, prompts, model IDs, and seeds are pinned per scorecard. A score without a version is not comparable to anything.
2. **Cadence:** full scorecard on every release candidate; M1/M9/M18 on every commit to main (fast subset).
3. **Regression policy:** any M18 > 0% blocks release until fixed or explicitly waived by Owais with a recorded reason. Waivers expire after one release.
4. **Threshold review:** thresholds are revisited quarterly against real usage — a threshold nobody can hit is a wish, not a gate.
5. **No metric gaming:** if a metric improves while user-reported quality doesn't, the metric is wrong, not the user. Fix the metric.

---

## PART 5 — CONFIDENCE, REFERENCES, UNKNOWNS

### Confidence levels
- **Experimental design template & threats checklist:** [VC] — standard practice, adapted.
- **Power formulas, Wilson CI, Holm procedure, McNemar:** [VC] — textbook statistics, formulas verified against multiple sources.
- **Detectable-effect table (§2.1):** [HC] — independent-sample formula is exact; the 30–50% paired discount is a standard rule of thumb, task-dependent.
- **Kappa interpretation & n=1 protocol:** [HC] — scales are standard; the n=1 rules are derived judgment, not published protocol.
- **Scorecard thresholds:** [MC] — reasoned targets for a personal assistant, not empirically derived. Every baseline is UNTESTED and must be measured before the thresholds bite.
- **Blind A/B protocol:** [HC] — standard practice synthesized from multiple sources.

### References (all real, none fabricated)
- Agresti, A. & Coull, B.A. (1998). "Approximate is Better than 'Exact' for Interval Estimation of Binomial Proportions." *The American Statistician*, 52(2), 119–126. — Wilson interval superiority.
- Cohen, J. (1960). "A coefficient of agreement for nominal scales." *Educational and Psychological Measurement*, 20(1), 37–46. — kappa.
- Landis, J.R. & Koch, G.G. (1977). "The measurement of observer agreement for categorical data." *Biometrics*, 33(1), 159–174. — kappa interpretation scale.
- McHugh, M.L. (2012). "Interrater reliability: the kappa statistic." *Biochemia Medica*, 22(3), 276–282. — stricter kappa adequacy bar (0.60).
- Holm, S. (1979). "A simple sequentially rejective multiple test procedure." *Scandinavian Journal of Statistics*, 6, 65–70. — Holm step-down.
- Benjamini, Y. & Hochberg, Y. (1995). "Controlling the false discovery rate." *JRSS-B*, 57(1), 289–300. — FDR control.
- Bradley, R.A. & Terry, M.E. (1952). "Rank analysis of incomplete block designs." *Biometrika*, 39, 324–345. — paired comparison foundations.
- Snell, C. et al. (2024). "Scaling LLM Test-Time Compute Optimally can be More Effective than Scaling Model Parameters." arXiv:2408.03314. — inference-time scaling (from learn-research-frontiers.md).
- Sample-size methods for two proportions: G*Power methodology; see also PMC5738522 (NIH) for worked clinical examples of the same formulas.
- Spotify Confidence blog (2026): "Are Optimal Multiple Testing Corrections Optimal for You?" — empirical comparison of Bonferroni/Holm/BH ship rates.
- Evalgent (2026): "A/B Test Voice Agent Prompts: Offline and Live Guide" — blind vs deterministic sampling protocol for agent eval.
- The AI Compendium: "LLM Evaluation" — annotator agreement norms (κ 0.3–0.6 typical for pairwise preference), length bias.

### Unknowns (ranked)
1. **All baselines are UNTESTED.** The scorecard is a framework awaiting its first measurement. Priority: M1, M9, M15 on the current build.
2. **Detectable-effect sizes for McNemar on JARVIS's actual task distribution** — the §2.1 table is approximate; real discordant-pair rates will refine it.
3. **Intra-rater consistency protocol for n=1** — the 20% re-presentation rule is a starting point, unvalidated.
4. **Cost-per-task accounting for local inference** — electricity + hardware amortization model unbuilt.
5. **Whether κ ≥ 0.60 is achievable on JARVIS's subjective judgments** — if raters can't agree, the rubric needs work before the model does.
6. **Latency thresholds vs user perception** — p50 ≤ 2s is a reasoned target; the actual "feels instant" boundary for Owais is unmeasured.

---

*End of learn-evaluation-science.md — OMEGA §20–22 complete.*
