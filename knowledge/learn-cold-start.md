# Cold Start — How JARVIS Behaves Safely When the Ledger Is Empty

**PHASE INFINITY — Research Cycle 17.** Written 2026-10-19. LEARNING ONLY — no project code touched, no installs, no experiments run, no claims fabricated.

**Research question:** How does JARVIS behave safely on day one, when the belief ledger is empty?

**Answer in one paragraph:** By treating "no evidence" as a first-class belief state, not a missing feature. Every ledger entry is born from a four-source elicitation protocol (conservative class default as the floor, hierarchical shrinkage from the parent, transfer-discounted benchmark pseudo-evidence routed to the *caller* not the tool, and discounted developer attestation labeled as attested-not-measured) — with all elicited strength capped so that ~20 real observations dominate any prior. Safety-relevant subjects get *pessimistic location* priors (mean shifted down, strength kept small), which the VoI gate and Gate C automatically translate into more verification and more asking; the measured cost is ~20–25% more observations to reach decision-convergence. Burn-in is per-subject, measured in *evidence mass* not calendar days, with instant demotion on failure and slow promotion through two graduation gates (consecutive-success counts, then the lower-bound crossing). Prior-data conflict is an investigation trigger, not an arithmetic event: attribute first (U1), run the prior-predictive check (Evans & Moshonov), shed the suspect pseudo-evidence, and rebuild from real data. And day one is a designed UX — "JARVIS is learning your setup" — with visible per-capability calibration progress and explicit training-wheels-off moments, because over-asking on day one would burn the trust account that real confirmations draw on.

**Confidence tags:** [VC] >95% · [HC] 80–95% · [MC] 60–80% · [SP] 40–60% · [UK] unknown. **DESIGN** = derived proposal, unmeasured.

---

## 1. The cold-start problem, stated precisely

Cycle 16 built the ledger; Cycle 16 unknown #7 flagged the bootstrap as open. The problem:

1. **Every entry starts at its prior** (lazy creation, learn-belief-ledger §2.3). On day one, *all* decisions — Gate C, the VoI gate, ask/act/escalate, Thompson routing — run on priors.
2. **Priors are the only thing the system "knows,"** and they are the weakest form of knowledge: elicited, transferred, or guessed. If they are wrong in *location*, early decisions are wrong in the dangerous direction (over-trust). If they are wrong in *strength*, early decisions are either frozen (too strong — evidence can't move them) or jittery (too weak — one failure panics the system).
3. **The asymmetry:** a wrong-optimistic prior causes unsafe actions; a wrong-pessimistic prior causes only wasted verification. The cold-start design exploits this asymmetry deliberately.

**The core design thesis:** *day-one priors should be weak in strength, honest in uncertainty, and pessimistic in location exactly where mistakes are expensive.* Everything below is the machinery for that sentence.

**Terminology note:** "cold start" is borrowed from recommender systems (Schein et al. 2002 — the classic cold-start recommendations work [HC]): the new-user/new-item problem, where the system must act before it has interaction history. JARVIS's version is a cold start on *every subject simultaneously* — the ledger equivalent of a brand-new user meeting a brand-new catalog.

---

## 2. Prior elicitation — the four-source protocol

Where day-one priors come from, in precedence order. Each source has a defined strength cap, because the central failure mode of elicitation is a confident prior that real evidence cannot overturn.

### 2.1 Source (a): conservative class defaults — the floor

Every subject type has a class prior from the learn-belief-ledger §2.2 table. These are the *floor*: no entry may be seeded weaker-in-location than its class default without an explicit reason, and no entry may be seeded stronger than the elicitation cap (§2.5).

**The neutral-vs-weak question the task poses** — α=2,β=2 vs α=1,β=1 for tools — analyzed behaviorally:

| Prior | Mean | Strength | 95% interval (normal approx) | Confidence 1−(hi−lo) |
|---|---|---|---|---|
| Beta(1,1) | 0.50 | 2 | [0.03, 0.97] | 0.05 |
| Beta(2,2) | 0.50 | 4 | [0.06, 0.94] | 0.12 |

Behavioral consequence [DESIGN, HC on the arithmetic]: after one failure, (1,1)→(1,2) mean **0.333**; (2,2)→(2,3) mean **0.400**. After ten straight successes, (1,1)→(11,1) mean 0.917, lo ≈ 0.767; (2,2)→(12,2) mean 0.857, lo ≈ 0.680. The (1,1) prior is *more* movable — it converges to trusting decisions faster, but it also panics faster on early failures (one failure drops the mean to 0.33, which under a pessimistic reading could demote a capability on noise).

**Decision:** the class default is **Beta(2,2), strength 4** [DESIGN]. Rationale: (1,1) is honest ignorance, but its jitter under the first few observations interacts badly with the burn-in demotion rule (§4) — a single flaky failure on day one would demote a healthy tool. Strength 4 absorbs one unlucky observation without whiplash, while still being overwhelmed by ~10 real observations (prior weight 4 vs data weight 10 → data dominates 71% of the posterior mass). This is the "stability without stubbornness" point.

### 2.2 Source (d): hierarchical priors — shrinkage, the default inheritance

The ledger already specifies the mechanism (learn-belief-ledger §7); this cycle fixes the protocol [DESIGN]:

- **New TOOL** ← its **class prior** (the §2.2 table: code-exec 0.80@10, web-read 0.80@10, messaging 0.90@10, system-control 0.75@10, media 0.85@10). With the pessimism shift of §3 applied for safety-relevant classes.
- **New TOOL×ARGCLASS** ← the parent TOOL's posterior via shrinkage:
  `(α,β)_child = (prior_α,prior_β) + s·(excess_α,excess_β)`, `s ∈ [0,1]`.
  Default `s = 0.3` for novel patterns, `s = 0.7` for seen-similar patterns [SP — Cycle 16's placeholder, retained pending the similarity-metric study].
- **The class prior itself is empirical-Bayes-updated:** once ≥10 sibling tools in a class have strength ≥20 each, the class prior's location is re-estimated as the precision-weighted mean of the siblings (partial pooling — the standard compromise between complete pooling and no pooling; cf. the hierarchical-modeling literature [HC]). Until then, the hand-set class prior stands. This makes the hierarchy *self-correcting*: early tools inherit guesses; later tools inherit the fleet's measured reality.

Why hierarchy matters for cold start: it is the only source that gives a *new* subject a non-vacuous prior without any observations of that subject. A new tool in a well-measured class starts near the class's earned reliability, not at ignorance.

### 2.3 Source (b): offline benchmarks as pseudo-evidence — with the routing correction

Benchmark scores (e.g., BFCL-style function-calling evaluations — Yan et al. 2024 [HC]) can seed priors, but **only with two corrections** that the naive "score → prior" mapping gets wrong:

**Correction 1 — the transfer discount.** Benchmark ≠ production. The protocol: a benchmark run of `n` items with `k` successes contributes pseudo-counts `(k·d, (n−k)·d)` with transfer discount `d ∈ (0,1]`, default **d = 0.3** [SP], *and* the total pseudo-evidence from benchmarks is capped at strength 10 (the elicitation cap, §2.5). The discount is the quantitative form of "synthetic ≠ production" (learn-belief-ledger unknown #7). It should be re-estimated once production data exists: `d̂ = observed_field_rate / benchmark_rate`, shrunk toward 0.3.

**Correction 2 — route to the caller, not the tool.** This is the sharp point. A function-calling benchmark measures *the model's ability to call functions correctly* — that is evidence about the **caller policy / strategy**, not about the tool. Under rule U1's cause-routing, benchmark pseudo-evidence updates the STRATEGY/caller-policy entry, **never** the TOOL entry. The TOOL entry measures "when invoked correctly, does the tool do its job" — a benchmark of the agent cannot observe that separately from the agent's own competence. The one exception: **deterministic code tools** (the filesystem jail's canonicalize, pure parsers) where the tool's behavior is independent of the caller — there, and only there, benchmark/unit-test pseudo-evidence may seed the TOOL entry.

*No specific benchmark scores are asserted here* — using a published score requires verifying the exact model/tool/benchmark version match, and unverified numbers in a prior are precisely the "confident wrong prior" failure. The protocol is score-agnostic by design.

### 2.4 Source (c): developer attestation — elicitation, not evidence

"The filesystem jail's canonicalize function is ~100% — but who attests that, and is attestation evidence?"

**Attestation is expert elicitation, not evidence.** The protocol [DESIGN]:

1. **The attestor is named and versioned.** The prior records `(attestor_id, artifact_version, attested_at)`. An unattributed "we're sure" is not a prior source — it's a rumor with a Beta distribution.
2. **Elicit quantiles, fit the Beta, discount.** Following the SHELF elicitation framework (O'Hagan et al. — the Sheffield Elicitation Framework for structured expert judgment [HC]): ask the attestor for three quartiles ("give me the 25th/50th/75th percentile of this tool's success rate"), fit the Beta by least squares, then **halve the fitted strength** — experts are systematically overconfident (the elicitation literature's most replicated finding; Garthwaite & O'Hagan 2000 [HC]), and the halving is the crude-but-honest correction.
3. **Strength cap 4, and the label sticks.** Attested priors carry `evidence_kind = attested_not_measured`, capped at strength 4 — the same mass as the neutral default. Rationale: attestation should be able to *locate* a prior ("this is near 1.0, not near 0.5") but never to *certify* it. Certification comes only from observations.
4. **Attestation is falsifiable.** If the tool fails twice in its first 20 uses, the attestation is *invalidated* (not merely updated): the entry reverts to the class default and the attestation is archived with reason `attestation_falsified`. This is the prior-data conflict procedure (§6) applied to the attestor.

The canonicalize example worked: developer attests quartiles (0.99, 0.999, 0.9999) → fitted ≈ Beta(40, 0.4)? — no. Halved strength, capped at 4: seeded ≈ (3.96, 0.04), mean 0.99, labeled attested. The first real failure moves it to (3.96, 1.04), mean 0.79 — the attestation evaporates on contact with one contrary fact, exactly as designed. **Data trumps elicitation, by construction.**

### 2.5 The elicitation strength cap — the load-bearing rule

**No elicited prior may exceed strength 10; attested priors may not exceed strength 4.** (Morita, Thall & Müller 2008 [HC] formalize this as the prior's *effective sample size* — the number of real observations the prior is "worth." The cap says: no opinion, however expert, is worth more than ten observations, and no attestation more than four.)

Consequence: after ~20 real observations, even the strongest elicited prior contributes ≤33% of the posterior mass. The ledger *cannot* stay wrong about a well-observed subject because someone was confident on day one. This is what makes the whole protocol safe to operate: **elicitation buys a starting location, never a permanent veto.**

---

## 3. The pessimism principle — formalized per class

**Principle:** for safety-relevant subjects, the prior's *location* is shifted pessimistic (assume less reliable than hoped) while its *strength* stays small. Pessimism is a location choice, not a knowledge claim — and the ledger's own machinery (Gate C's lower bound, the VoI gate's p_wrong) converts it into behavior automatically: more verification, more asking, no code changes.

### 3.1 Which classes get pessimism, and how much [DESIGN]

| Subject class | Prior | Location shift δ | Rationale |
|---|---|---|---|
| Reversible reads, well-tested utilities (tier 0–1) | Beta(2,2) neutral | 0 | Mistakes are cheap and undoable; exploration should be cheap too |
| Strategies (the 8) | Beta(2,2) neutral | 0 | Thompson sampling *needs* neutral priors to explore; pessimism here would freeze exploration |
| Claim types, source tiers | Beta(2,2) neutral | 0 | These aggregate fast; pessimism would just add noise |
| **New/never-seen tools** | **Beta(2,4), mean 0.33** | −0.17 vs neutral | Unknown unknowns dominate; verify-first until the tool earns its rate |
| **Irreversible actions (tier 2–3): system-control, messaging-send, deletion** | **Beta(2,4), mean 0.33** | −0.17 | False-allow cost is high (learn-math-for-jarvis §3: asymmetric loss); the prior should price that in |
| **Security-gate judges** (intrusion/phishing/tool-output-screening judges) | TPR prior Beta(2,4) — assume the judge *misses* most attacks until measured | −0.17 on TPR | A security gate that hasn't proven its true-positive rate is assumed blind; cf. pessimism in offline RL (Jin et al. 2021 [HC]): act on the lower bound when data is thin |
| **Quality judges** (entailment/factuality critics) | FPR prior Beta(4,2) — assume the judge *cries wolf* until measured | +0.17 on FPR | A loud unmeasured judge would otherwise veto good claims; pessimism here means *distrusting its alarms*, which keeps it inert per U3's least-privilege theorem |

Note the asymmetry in the last two rows: pessimism is always *in the direction that fails safe*. For a security gate, failing safe means assuming attacks get through (verify more). For a quality critic, failing safe means assuming its challenges are noise (don't block good work on an unmeasured alarm). **Pessimism is not "low numbers everywhere" — it is "the prior location that makes the default action the safe action."**

### 3.2 How pessimism becomes behavior — no new machinery

With a (2,4) prior (mean 0.333, 95% interval ≈ [0, 0.68]):

- **Gate C** reads the *lower bound* lo ≈ 0. No aspiration threshold τ is ever ≤ 0 → Gate C cannot fire on a fresh pessimistic entry. The system *cannot* act-on-confidence until real evidence arrives. This is the stopping rule enforcing humility with zero extra code.
- **The VoI gate** reads p_wrong = 1 − 0.333 = 0.667. `verify ⟺ 0.667 × cost_wrong > cost_verify` — with p_wrong this high, verification fires for almost any non-trivial cost_wrong. The task's observation is exactly right: **the VoI gate naturally does this when P(wrong) is high.** Pessimism is a way of *telling the VoI gate the truth about day-one ignorance*.
- **Ask/act/escalate** reads P(wrong interpretation) from the discriminator's JUDGE entry; a pessimistic (high-FPR) prior on a fresh discriminator pushes VoI(ask) up → more asking on day one, tapering as the discriminator is measured.

### 3.3 The pessimism tax — quantified (worked)

Pessimism is not free: a low prior location delays the moment the posterior's lower bound crosses the aspiration threshold. Worked below in §5; the headline result: **for a tool with true 95% reliability and a τ = 0.90 decision threshold, the pessimistic (2,4) prior needs ~165 expected observations to reach decision-convergence vs ~135 for the neutral (2,2) — a ~22% tax.** The tax is modest because the binding constraint near convergence is interval *width* (∝ 1/√n), not prior location. You pay ~a fifth more observations; you buy strictly safer behavior on every one of the early ones. For irreversible actions, that trade is always worth it [DESIGN judgment, HC on the arithmetic].

**Boundary condition:** pessimism must never be so strong that the system refuses to ever try (the exploration death-spiral). Strength stays ≤ 6 for pessimistic priors — ten clean observations move (2,4) to (12,4), mean 0.75, and the system is already learning. Pessimism delays trust; it never denies the *opportunity* to earn it.

---

## 4. The burn-in period — per-subject, in evidence mass, not days

### 4.1 The design correction: burn-in is not a calendar

"First N days" is the wrong unit. A tool used 50×/day and a tool used 1×/month do not burn in on the same clock. **The burn-in clock is the entry's strength field** — effective evidence mass. A capability graduates when its *evidence* justifies it, which for a daily-used tool is days and for a monthly-used tool is months. The UX (§7) must be honest about this: "I rarely use this, so I'll keep double-checking it for a while" is a *feature* of the design, not a bug.

### 4.2 The three stages [DESIGN]

Every TOOL and TOOL×ARGCLASS subject lives in one stage. (Strategies are exempt — Thompson sampling is already the exploration policy. Judges graduate by calibration-set size, §4.4.)

| Stage | Name | Behavior | Exit condition (all must hold) |
|---|---|---|---|
| **0** | UNTRUSTED | Irreversible: always verify or ask (per ask/act/escalate). Reversible: act with narrated assumption. Gate C disabled (cannot fire — lo is below every τ by construction at these priors). | Graduation counter ≥ g₁ consecutive successes **and** no open conflict flag |
| **1** | PROBATION | Full VoI-gated operation: verify iff `voi_gate` fires; Gate C live. Ask/act/escalate unchanged. | Posterior lower bound lo ≥ τ_class **and** strength ≥ n₂(class) |
| **2** | TRUSTED | Normal operation. Verification only where VoI says so; confirmations only where ask/act/escalate says so. | — (terminal unless demoted) |

**The asymmetry — the load-bearing rule:** *promotion is slow, demotion is instant.* Any failure attributed to the tool (U1 cause-routing: tool-caused, not context, not caller) demotes the subject to Stage 0 immediately and resets the graduation counter. Any prior-data conflict flag (§6) demotes to Stage 0. Promotion requires sustained clean evidence; demotion requires one bad fact. This is the sequential-testing intuition (Wald 1947, Sequential Analysis [VC]): the test for "reliable" needs many consistent observations, but a single decisive contrary observation can reject.

### 4.3 Graduation thresholds per class [DESIGN — all SP, data overwrites]

| Class | g₁ (consecutive successes → Stage 1) | Stage 2: τ_class (lo threshold) | n₂ (min strength) | Notes |
|---|---|---|---|---|
| Reversible reads/utilities | 10 | 0.90 | 30 | Cheap mistakes; graduate fast. From (2,2): 10 straight successes → (12,2), mean 0.857 — VoI-gated, not yet trusted |
| Irreversible / tier 2–3 (delete, send, system-control) | 30 | 0.95 | 200 | From pessimistic (2,4): 30 straight successes → (32,4), mean 0.889, lo ≈ **0.788** (§5) — still Stage 1. Stage 2 needs real mass |
| New/never-seen tools | 30 (as irreversible until attributed data exists) | 0.95 | 200 | Inherit the strict class until the tool earns its own entry |
| Deterministic code tools (attested) | 10 | 0.95 | 50 | Attestation buys a head start on *location*, not on *graduation* — the counter still runs |

Why consecutive successes rather than raw strength for g₁: a streak is a *sequential* test — it asks "has this worked every time lately?", which is the right question for regime freshness, whereas raw strength can be dominated by ancient history. (The decay in learn-belief-ledger §4 already discounts ancient history; the streak counter is the belt-and-suspenders version for the burn-in window specifically.)

Why the counter resets on any tool-attributed failure rather than tolerating a rate: during burn-in there is no measured rate yet — tolerating "some" failures requires a rate estimate you don't have. After Stage 2, the ledger's own posterior (not the counter) governs, and occasional failures are absorbed arithmetically. **The counter is scaffolding; the posterior is the building.** Scaffolding comes down.

### 4.4 Judges graduate differently — by calibration, not by use

A judge's influence comes from measured (TPR, FPR) on gold-labeled data (U3's least-privilege theorem). Burn-in for a JUDGE entry: it remains **inert** (prior (1,1), likelihood ratio ≈ 1) until it has **≥ 50 gold-labeled calibration verdicts** [SP], at which point its measured rates go live with a strength cap of 20 until 200 labels. Using a judge "in production" without calibration labels does not graduate it — only *labeled* outcomes count, because only they measure discrimination. This is stricter than the tool burn-in on purpose: an unmeasured judge is either inert or dangerous, nothing in between.

### 4.5 What "graduation" does and doesn't mean

Graduation changes *behavioral permissions* (fewer verifications, fewer confirmations), never *epistemic claims*. A Stage-2 entry is not "certain" — its interval is simply narrow enough that the decision rules stop firing their caution branches. The ledger still reports the interval; the audit still watches the Brier score. **Burn-in ends the training wheels, not the measurement.**

---

## 5. Convergence analysis — the math, worked

Setup: true reliability p* (unknown to the system, known to this analysis). Prior (α₀,β₀). After n observations with k successes: posterior (α₀+k, β₀+n−k). All intervals by the normal approximation on the Beta (flagged; exact quantiles would tighten these slightly — [MC] on exactness, [HC] on shape and ordering).

### 5.1 The task's example: true 95%, prior (2,2), n = 20

Expected k = 19 → posterior **(21, 3)**. Mean = 21/24 = **0.875**. Variance = 21·3/(24²·25) = 63/14400 = 0.004375; sd = 0.0661; 95% interval = 0.875 ± 1.96·0.0661 = **[0.745, 1.000]**. Confidence = 1 − 0.255 = **0.745**.

Read behaviorally: after 20 observations at 95% true reliability, the ledger says 0.875 [0.745, 1.000]. Gate C with τ = 0.90: lo = 0.745 < 0.90 → **does not fire** — the system keeps verifying. The prior's pull (0.875 vs the empirical 0.95) is still visible. Twenty observations feel like a lot; the ledger correctly judges they are not enough to *stop checking* at τ = 0.90. This is the ledger being more patient than a human would be, in the safe direction.

### 5.2 Decision-convergence: when does the ledger's policy match the asymptotic policy?

Define **decision-convergence** as the n at which the posterior lower bound lo(n) crosses the aspiration threshold τ — the moment Gate C *would* start firing and stay firing (on the expected-data path). This is the number the burn-in schedule must respect: graduating a capability before its decisions have converged is graduating on hope.

Case A — neutral prior (2,2), p* = 0.95, τ = 0.90:
lo(n) ≈ (2+0.95n)/(4+n) − 0.427/√(5+n) ≥ 0.90 → n ≈ **135** observations. (At n=135: mean = 0.937, lo ≈ 0.901.)

Case B — pessimistic prior (2,4), p* = 0.95, τ = 0.90:
lo(n) ≈ (2+0.95n)/(6+n) − 0.427/√(7+n) ≥ 0.90 → n ≈ **165** observations. (At n=165: mean = 0.935, lo ≈ 0.901.)

**The pessimism tax: 165/135 ≈ 1.22×.** Pessimism costs ~22% more observations to reach the same decision — the price of safer early behavior, and a modest one, because near convergence the binding constraint is interval width (∝ 1/√n), which barely depends on the prior.

Case C — the certification number (for §4.3's n₂): from (2,2), how many *consecutive* successes to be 95% sure that θ ≥ 0.95? For Beta(α,2), P(θ ≥ x) = 1 − x^α(1 + α(1−x)/… ) — in closed form: P(θ≥0.95) = 1 − (0.95)^α(1+0.05α). Setting ≥ 0.95 with α = 2+k gives **k = 91 consecutive successes**. Ninety-one clean runs to *certify* 95% reliability at 95% confidence, vs ~135 mixed observations to *operate* at τ = 0.90. The gap between "operate" and "certify" is why Gate C uses lo ≥ τ (operational) rather than P(θ ≥ τ) ≥ 0.95 (certification): the ledger is allowed to act before it could publish.

### 5.3 What this implies for burn-in length

| Class | Decision threshold τ | Prior | Decision-convergence (expected obs) | g₁/n₂ from §4.3 | Verdict |
|---|---|---|---|---|---|
| Reversible reads | 0.90 | (2,2) | ~135 | n₂ = 30 | n₂ is *faster* than convergence — deliberate: reversible mistakes are cheap, so Stage 2 arrives before full convergence; VoI still gates the expensive verifications |
| Irreversible | 0.95 | (2,4) | ~800 (at p* = 0.97; note: if p* = τ exactly, lo never crosses — the threshold must sit below the true rate, which is why τ = 0.95 demands genuinely ≥96%+ tools) | n₂ = 200 | n₂ = 200 is *slower* than needed for lo ≥ 0.90 but the τ = 0.95 bar dominates; the 200 floor keeps thin-but-lucky streaks from certifying |

The general lesson: **burn-in length in observations is set by (τ, prior, p*) via the lo-crossing, not by fiat.** The §4.3 table is the practical discretization; the §5.2 computation is the instrument for tuning it once field p* values are measured. And in calendar time: a tool used 5×/day reaches 135 observations in ~27 days; at 50×/day, in ~3 days. The per-subject evidence clock (§4.1) falls out of the math — it was never a choice.

### 5.4 The weak-prior convergence theorem (informal)

As n → ∞, the posterior mean → p* and the interval width → 0 at rate 1/√n *regardless of the prior* (Bernstein–von Mises intuition; for Beta-Bernoulli it is exact algebra: prior contributes fixed (α₀,β₀) against n growing observations [VC on the mechanics]). Two consequences for cold start:

1. **Prior location washes out; prior strength sets the washout rate.** This is the formal justification for the elicitation cap (§2.5): a capped prior is *guaranteed* to wash out, so no elicitation mistake is permanent.
2. **The only permanent damage a prior can do is through the decisions taken while it dominates.** Hence pessimism: while the prior dominates (small n), let it dominate *in the safe direction*. The asymptotic math doesn't care about the prior; the first 20 decisions do.

---

## 6. Prior-data conflict — investigation, not arithmetic

The scenario: a tool seeded "reliable" — say (9,1), mean 0.90, strength 10, from benchmark pseudo-evidence — then fails 3 of its first 5 real uses (k=2, n=5). Naive Bayes would plod to (11,4), mean 0.733, and carry on. **That is the wrong response.** Three early failures against a confident prior is not "mild negative evidence" — it is a signal that *the prior's source is broken* (transfer failure, false attestation, or a regime the benchmark never saw). The procedure:

### 6.1 Detect — the prior-predictive check

For Beta-Binomial conjugacy the check is closed-form (no simulation needed). Under prior (α,β), the prior-predictive distribution of K successes in n trials is Beta-Binomial: P(K=k) = C(n,k)·B(k+α, n−k+β)/B(α,β). The conflict p-value: P(K ≤ k_obs) under the prior predictive (Evans & Moshonov 2006 [HC] — "is the observed sufficient statistic surprising under the prior predictive M_T?"; the Box 1980 [VC] prior-predictive check is the ancestor).

Worked: prior (9,1), n=5, k_obs=2. B(9,1) = 1/9.
- P(K=0) = B(9,6)/B(9,1) = (8!5!/14!)·9 ≈ 0.0005
- P(K=1) = 5·B(10,5)·9 ≈ 0.0045
- P(K=2) = 10·B(11,4)·9 ≈ 0.0225
- **p = P(K ≤ 2) ≈ 0.0275 < 0.05 → conflict declared.**

(For non-conjugate or large-n cases, the ledger's standing CUSUM-lite from learn-belief-ledger §4.3 is the detector: last-20 empirical rate outside the decayed entry's 99% interval → `suspect_regime`. Page 1954 [VC]. The two detectors agree in spirit: *is the recent data surprising under what we believed?*)

**Design rule:** the prior-predictive check runs automatically for any entry whose prior strength is ≥50% elicited (benchmark/attested) during its first 30 observations. After that, CUSUM-lite takes over. Elicited priors get extra scrutiny exactly when they are most influential — which is also when they are most dangerous.

### 6.2 Attribute — U1 before anything else

Before touching the prior: **cause-route the failures** (learn-belief-ledger U1). Three failures might be one network outage (context — don't touch the tool entry), one bad-arg call (caller — penalize the strategy), and one genuine tool bug. The conflict procedure operates on *attributed* outcomes. If attribution is unavailable, the outcomes are flagged `unattributed` and the conflict threshold tightens (p < 0.01) — don't burn a prior on unexamined evidence.

### 6.3 Diagnose — which source lied?

| Finding | Diagnosis | Response |
|---|---|---|
| Failures are context/caller-caused | Prior is fine; the *data* was misrouted | No prior change; fix routing; the conflict flag clears |
| Tool-caused, prior was benchmark-seeded | **Transfer failure** — the benchmark doesn't predict this deployment | Shed the benchmark pseudo-counts: entry reverts to the class default (or pessimistic default for its class); the benchmark evidence is archived with reason `transfer_failed`. The class default is honest; the benchmark was a guess about *this* deployment and the guess lost |
| Tool-caused, prior was attested | **Attestation falsified** | Attestation invalidated per §2.4 step 4; entry reverts to class default; attestor notified (the developer's mental model of their own code was wrong — that is itself valuable feedback) |
| Tool-caused, prior was the class default | **Genuine surprise** — the class prior mislocates this tool | Keep the default (it's the hierarchy's best guess), but halve the entry's half-life (accelerated decay per learn-belief-ledger §4.3) and lower the verification bar: the entry is now `suspect_regime` until fresh evidence re-converges it |

### 6.4 Respond and rebuild

1. Mark `status = suspect_regime`; queries return the **conservative bound** (lo for success probabilities) as the headline estimate.
2. Shed the suspect pseudo-evidence (§6.3) — never "average it in." A broken source's pseudo-counts are not weak evidence; they are *wrong* evidence, and wrong evidence doesn't get a vote.
3. **Rebuild from real data only.** The entry re-converges under the standard update rules. Because the elicitation cap (§2.5) kept the prior weak, this typically takes tens of observations, not hundreds.
4. Log everything: the conflict p-value, the attribution, the diagnosis, the shed counts. The audit (Cycle 15's arm) reviews conflict diagnoses quarterly — a pattern of transfer failures in one benchmark poisons that benchmark's discount d for *all* tools.

**The slogan:** *arithmetic updates beliefs; conflict investigates sources.* A ledger that only ever adds pseudo-counts will eventually believe a confident lie. The conflict procedure is the immune system.

---

## 7. The empty-ledger UX — day one as a designed experience

On day one the ledger is all priors: wide intervals, pessimistic locations, Stage 0 everywhere. The user-visible consequences: more confirmations, more narrated assumptions, more verification latency, less autonomy. **This must read as "JARVIS is learning your setup," not as "JARVIS is broken or timid."** The design:

### 7.1 The onboarding narrative

First session, once, briefly (not a tutorial — a single honest framing):

> "I'm new here, so I'll double-check the important stuff for the first while — and I'll tell you what I'm assuming when I act. Every clean run teaches me; you'll see me ask less as I learn your setup. If I'm ever too cautious, say so."

Three properties: it **names the mechanism** (double-checking), **promises the trajectory** (ask less over time), and **gives the user a control** ("say so"). No fake precision ("calibration at 37%"), no jargon ("my Beta priors are diffuse").

### 7.2 Visible calibration progress — per capability, in plain language

A lightweight, glanceable surface (HUD-adjacent, not a dashboard — Owais's zero-terminal, buttons-only rule applies): per capability, a plain-language trust state. Not numbers — *stages with evidence*:

- "Web search — still learning · 12 clean runs" (Stage 0)
- "File reading — mostly trusted · I'll only double-check the odd one" (Stage 1)
- "Sending messages — still cautious · I verify every send for now" (Stage 0, pessimistic class)

When a capability graduates, **the training-wheels-off moment is explicit and celebrated briefly**:

> "I've fetched pages 30 times without a failure — I'll stop pre-checking them now. Say the word if I get cocky."

Why explicit: silent graduation looks like the system "changed its mind" about safety; narrated graduation shows the *evidence* earned it. And "say the word if I get cocky" hands the user the demotion lever — which is honest, because one failure *will* demote it (§4.2).

### 7.3 Day-one questioning discipline — protect the trust account

The underspecification cycle's rubber-stamping warning applies with full force on day one: **every unnecessary question trains the user to approve blindly, destroying the safety value of real confirmations.** So:

- Day-one questions must be **VoI-positive and batched** (ask/act/escalate §3.1 steps 6–8): one turn, highest-VoI questions together, max 2–3 per task.
- Everything else uses **act-with-narrated-assumption**: "Playing your liked songs — say the word to change it." The narration is the cheap substitute for the question; the user's correction (or silence) is *itself* evidence that feeds the discriminator's burn-in.
- **Never re-ask.** The redundancy cost is real; a repeated question on day two tells the user the first answer went nowhere, which is worse than not having asked.
- Confirmations on day one show the **payload and blast radius** (learn-frontend: visible payload or it's theater) — "Delete these 14 files in Downloads?" with the list, not "Are you sure?"

### 7.4 What the user never sees

The (α,β) values. The discount factors. The CUSUM statistics. The conflict p-values. These are the engine room; the UX shows *behavioral* states (learning / cautious / trusted) and *evidence* counts ("12 clean runs"), never the machinery. The one exception: on explicit request ("why are you still double-checking this?"), the honest answer is available — "it's failed twice in the last ten tries, so I'm being careful" — because the ledger's numbers are auditable by design (learn-belief-ledger §2.3 invariant 3), and auditability that can't be surfaced on demand isn't auditability.

---

## 8. Honest scope — what cold-start design does NOT solve

1. **It doesn't manufacture knowledge.** A well-designed cold start is still ignorance — organized, humble, pessimistic-where-it-matters ignorance. The first weeks of production are the actual experiment; this file designs the *conditions* for that experiment, not its results.
2. **Rarely-used tools may never graduate.** A tool used 1×/month needs years to reach n₂. That is correct behavior (the ledger should stay cautious about things it rarely sees), but the UX must not promise graduation it can't deliver — §7.2's "still cautious" state is a *steady* state for rare tools, not a failure.
3. **The pessimism tax is real.** ~22% more observations per safety-relevant subject (§5.2). For a fleet of tools each used a handful of times daily, the aggregate extra verification is measurable latency and measurable user patience. The §4.3 thresholds are the dial; production data turns it.
4. **Attestation gaming.** A developer who learns that attestation buys a favorable prior location can over-attest. The strength-4 cap and falsification rule (§2.4) bound the damage, but attestor calibration (are *this developer's* attestations usually right?) is unbuilt — a natural LEDGER_SELF-style meta-entry for a later cycle.
5. **Correlated cold starts.** A new deployment (new machine, new user) cold-starts *all* subjects at once — the maximum-caution configuration. If everything is Stage 0 simultaneously, the UX burden (§7.3) is at its heaviest exactly when first impressions form. Mitigation: class priors and hierarchy (§2.1–2.2) mean entries start at *sensible* locations even with zero local evidence; only the *strength* is thin. The system is cautious, not clueless.

---

## 9. Integration map

```
day-one boot
  │
  ├─ elicitation protocol (§2) ──▶ every entry seeded:
  │      class default (floor) + hierarchical shrinkage
  │      + benchmark pseudo-evidence (d=0.3, cap 10, routed to CALLER)
  │      + attestation (halved, cap 4, labeled attested_not_measured)
  │      + pessimism shift for safety classes (§3)
  │
  ├─ burn-in stages (§4) ──▶ Stage 0: verify/ask/narrate
  │      ──g₁ consecutive successes──▶ Stage 1: VoI-gated
  │      ──lo ≥ τ_class, strength ≥ n₂──▶ Stage 2: trusted
  │      failure/conflict ──▶ instant demotion to Stage 0
  │
  ├─ decisions read priors through the standard API:
  │      Gate C (learn-bounded-rationality) — lo bound, can't fire at pessimistic priors
  │      voi_gate (learn-math-for-jarvis) — p_wrong high → verifies
  │      ask/act/escalate (learn-underspecification) — VoI(ask) up → asks more
  │      Thompson routing — neutral strategy priors keep exploring
  │
  ├─ prior-data conflict (§6) ──▶ investigate, attribute (U1),
  │      shed suspect pseudo-evidence, rebuild from real data
  │
  └─ day-one UX (§7) ──▶ "learning your setup" narrative,
         per-capability trust states, training-wheels-off moments,
         VoI-positive batched questions only
```

**Fills learn-belief-ledger unknown #7** (cold-start bootstrap): the ledger no longer starts from "literature guesses" alone — it starts from the four-source protocol with capped elicitation strength, pessimistic safety locations, per-subject evidence-mass burn-in, and a conflict immune system. The remaining unknowns move to §10.

**ADR candidate (for DECISION-PLAYBOOK.md):** *"JARVIS v2 shall cold-start the belief ledger per learn-cold-start.md: every entry seeded by the four-source elicitation protocol (class-default floor, hierarchical shrinkage, transfer-discounted benchmark pseudo-evidence capped at strength 10 and routed to caller-policy entries, developer attestation halved/capped at strength 4 and labeled attested-not-measured); safety-relevant subjects get pessimistic location priors (Beta(2,4)-class) with strength ≤ 6; burn-in is per-subject in evidence mass with instant demotion and two graduation gates (g₁ consecutive successes, then lo ≥ τ_class with strength ≥ n₂); prior-data conflict triggers the investigate-attribute-shed-rebuild procedure, never silent arithmetic. Rationale: on day one all decisions run on priors; priors must therefore be weak enough to wash out (~20 observations dominate any elicited prior), pessimistic exactly where mistakes are expensive, and falsifiable. Status: PROPOSED — protocol and thresholds are design; d, g₁, n₂, and τ_class await production data."*

---

## 10. Evidence table

| Claim | Source | Confidence |
|---|---|---|
| Beta-Bernoulli conjugate updating; pseudo-counts as prior observations; mean α/(α+β) | Murphy, *PML: An Introduction* (2022); Gelman et al., *BDA* 3rd ed. | [VC] |
| Prior predictive checks for model/prior criticism | Box, G.E.P. (1980), "Sampling and Bayes' inference in scientific modelling and robustness," JRSS A 143:383–430 | [VC] |
| Prior-data conflict: compare the minimal sufficient statistic against its prior predictive M_T | Evans, M. & Moshonov, H. (2006), "Checking for prior-data conflict," *Bayesian Analysis* 1(4):893–914 | [HC] |
| CUSUM sequential change detection; recursive W_n = max(0, W_{n−1} + log LR) | Page, E.S. (1954), "Continuous inspection schemes," *Biometrika* 41(1/2):100–115 | [VC] |
| Prior effective sample size (ESS): the number of observations a prior is "worth" | Morita, S., Thall, P.F. & Müller, P. (2008), "Determining the effective sample size of a parametric prior," *Biometrics* 64:595–602 | [HC] |
| Power priors: historical-data discount a₀ ∈ [0,1]; the transfer-discount precedent | Ibrahim, J.G. & Chen, M.-H. (2000), *Statistical Science* 15:46–60 (via learn-belief-ledger) | [VC] on the paper; [SP] on d = 0.3 |
| Sequential testing: few observations can reject, many are needed to accept | Wald, A. (1947), *Sequential Analysis* | [VC] |
| Structured expert elicitation; experts are systematically overconfident; quartile fitting | SHELF framework (O'Hagan et al.); Garthwaite & O'Hagan (2000) on overconfidence reduction | [HC] |
| Hierarchical partial pooling: compromise between complete pooling and no pooling; shrinkage | Standard hierarchical-modeling literature (Gelman et al., *BDA*) | [HC] |
| Pessimism under uncertainty: act on lower bounds when data is thin (offline RL) | Jin, Y. et al. (2021), "Is pessimism provably efficient for offline RL?", ICML | [HC] |
| Cold-start problem lineage (new users/items with no history) | Schein, A. et al. (2002), cold-start recommendations | [HC] |
| Function-calling benchmarks as (transfer-uncertain) capability evidence | BFCL, Yan et al. (2024), Berkeley Function-Calling Leaderboard | [HC] — protocol only; no scores asserted |
| Bernstein–von Mises / washout: fixed prior contributes negligibly as n → ∞ | Standard asymptotic theory; exact algebra for Beta-Bernoulli | [VC] on mechanics |
| Worked arithmetic: (21,3) → 0.875 [0.745, 1.000]; lo-crossing n≈135 (neutral) / n≈165 (pessimistic) at τ=0.90; 91 consecutive successes to certify θ≥0.95 at 95%; prior-predictive p≈0.0275 for the conflict example | Hand-computed this cycle; Beta intervals by normal approximation | [HC] on arithmetic; [MC] on exact quantiles |
| Four-source protocol, pessimism table, burn-in stages and thresholds, conflict procedure, day-one UX | This cycle's design | DESIGN/[SP] — unmeasured, data overwrites |

**Real references (no fabricated citations):** Box (1980) JRSS-A; Evans & Moshonov (2006) Bayesian Analysis 1(4); Page (1954) Biometrika 41; Morita, Thall & Müller (2008) Biometrics 64; Wald (1947) Sequential Analysis; Ibrahim & Chen (2000) Statist. Sci. 15; Jin et al. (2021) ICML; Yan et al. (2024) BFCL; Schein et al. (2002); O'Hagan et al. SHELF; Garthwaite & O'Hagan (2000). Prior cycles: learn-belief-ledger.md, learn-math-for-jarvis.md, learn-bounded-rationality.md, learn-underspecification.md, learn-frontend.md.

---

## 11. Unknowns (ranked)

1. **Transfer discount d.** Default 0.3 is a placeholder [SP]. The honest estimate needs paired benchmark+field measurements per tool — the first production quarter's most valuable statistic. Until then, the cap (strength ≤ 10) matters more than the discount.
2. **Graduation thresholds (g₁, n₂, τ_class).** All [SP]. The annoyance-vs-safety trade-off they encode can only be tuned against real user patience data — and the rubber-stamping dynamics (learn-underspecification) mean the cost of over-verification is non-linear.
3. **Streak-counter fragility.** One flaky, unattributed failure demotes a healthy tool to Stage 0. The CUSUM-lite + attribution pipeline is supposed to distinguish noise from regime change, but that discrimination is itself unmeasured (learn-belief-ledger unknown #4).
4. **Attestor calibration.** Developers overstate; the halving rule is crude. Whether attestation sources need their own reliability entries (a meta-ledger over attestors) is open — flagged as a later-cycle design.
5. **Rare-tool steady state.** Tools used 1×/month may sit in Stage 0/1 indefinitely. The design says that's correct; the UX (§7.2) must frame "still cautious" as a steady state, and whether users accept that framing is untested.
6. **Correlated cold start at new deployments.** All subjects at Stage 0 simultaneously on a fresh install — the heaviest UX burden lands on first impressions. The mitigation (sensible class-prior locations via hierarchy) is designed but the first-session experience is unvalidated.
7. **The pessimism tax at fleet scale.** ~22% extra observations per safety-relevant subject is fine per subject; across dozens of tools with low daily usage, the aggregate verification load and its latency/patience cost need measurement.

---

*Honest completion (Rule 12): Researched: four-source elicitation protocol (new; SHELF, Morita ESS, power-prior discount, and the benchmark→caller routing correction are new), pessimism principle formalized per class with the security/quality judge asymmetry (new; Jin et al. 2021 pessimism grounding verified via search), per-subject evidence-mass burn-in with instant-demotion/slow-promotion and graduation thresholds (new; Wald 1947 sequential-testing grounding), convergence math fully worked by hand — (21,3) posterior, lo-crossing at n≈135 neutral / n≈165 pessimistic, 91-success certification number, pessimism tax ≈1.22× (new), prior-data conflict procedure with closed-form Beta-Binomial prior-predictive check worked (p≈0.0275; Box 1980 / Evans & Moshonov 2006 verified via search; Page 1954 CUSUM verified via search), day-one UX narrative with questioning discipline (new). Validated: all external citations checked against real sources — no fabricated references; worked-example arithmetic rechecked (normal-approximation intervals flagged). Saved: this file. Tested/Measured: nothing (learning only). Incomplete: the seven unknowns above, all marked. Blocked: none.*
