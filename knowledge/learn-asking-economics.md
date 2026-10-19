# The Economics of Asking — Reconciling the Cost Framing and the CIRL Framing

**PHASE INFINITY — Research Cycle 9.** Written 2026-10-19. LEARNING ONLY — no project code touched, no experiments run, no claims fabricated.

**Research question:** How should JARVIS price the act of asking? Reconciling Cycle 1's cost framing ("asking is overhead to be minimized") with Cycle 8's CIRL framing ("communicativeness is part of optimal play").

**Answer in one paragraph:** There is no conflict to resolve, only a generalization to make. The Cycle 1 rule — ask iff VoI(ask) > C_ask — is the *single-agent, single-gain-term* special case of a joint-utility pricing rule. CIRL's objective is the shared reward; the cost of asking is paid in that same currency (the human's time and attention are part of the joint game, not an externality). The unified rule is: **ask iff expected joint-utility gain > total ask cost**, where the gain has three terms (uncertainty reduction, alignment of the human's model, corrigibility value) and the cost has three terms (interruption, trust-erosion, latency). Cycle 1's hard gates — "divergent × irreversible → always ask," "tier-3 never acts on assumption" — are not exceptions to this pricing; they are what the pricing *outputs* once the corrigibility term is correctly valued. The ~2–3 ask budget is the static approximation of the rule's dynamic pricing: the Lagrange multiplier on the human's attention constraint. Nothing here is validated on real usage; all parameters are proposals with measurement targets in §7.

---

## 1. Why the two framings look like they conflict

| | Cycle 1 (cost framing) | Cycle 8 (CIRL framing) |
|---|---|---|
| **Objective** | Minimize expected task cost | Maximize shared reward R(s, a_H, a_R; θ) |
| **Asking is** | A cost C_ask, pure overhead | A first-class action; communicativeness is optimal play |
| **Ask when** | VoI(ask) > C_ask — the answer must change a decision | When it improves joint performance — even to shape the human's model |
| **Failure mode it fears** | Over-asking (rubber-stamping, abandonment) | Under-communicating (uncoordinated, uncorrectable behavior) |

The apparent conflict: the cost framing's gain term counts *only* the agent's uncertainty reduction, so any question that doesn't change the agent's next action prices at ~0 gain — including "trust-but-verify" confirmations on tier-3 actions, which Cycle 1 rescued via hard gates bolted on *outside* the pricing. The CIRL framing's gain term counts joint performance, so communicative acts have positive value — but taken naively, "communicativeness is good" could justify endless questions.

**The reconciliation [HC]:** in an assistance game, the human's attention is not free — H's actions (answering, correcting, waiting) have costs inside the shared reward, because H is a player with finite patience, not a query oracle. CIRL's optimal policy already trades off asking against those costs; it was never "ask endlessly." Cycle 1's rule is the *same tradeoff* with a narrowed gain term (only G_uncertainty) and a narrowed cost term (only interruption + latency). The unified rule widens both terms and recovers both behaviors: Cycle 1's parsimony *and* CIRL's communicativeness, each priced in one currency.

**The budget-as-Lagrange-multiplier identity [MC — standard optimization, applied here as the reconciliation mechanism]:** maximize joint utility U_joint subject to total human attention spent ≤ B. The Lagrangian is L = U_joint − λ·(attention spent). The per-decision pricing rule with the correctly set shadow price λ *is* the budget: ask while marginal gain > λ. The ~2–3 heuristic is the static guess at where marginal gain crosses λ for typical tasks. So the budget is not a rival to pricing — it is the **dual variable** of the same objective under an attention constraint. Cycle 8 §7.4 already named this ("budget as Lagrange multiplier on the information-acquisition term"); this file makes it the load-bearing identity.

---

## 2. Taxonomy of why to ask — five purposes, which framing covers each

| # | Purpose | Definition | Covered by | Missed by the other framing |
|---|---|---|---|---|
| (a) | **Reduce own uncertainty** | Classic VoI: the answer changes which action JARVIS takes | **Cost framing** — this is VoI(ask) > C_ask, the rule's core case (Cycle 1 step 6) | CIRL adds a refinement: the uncertainty that matters is over **θ (reward parameters)**, not just slot values. Asking "cuisine?" reduces slot uncertainty; asking "what does 'nice' mean to you for dinner?" reduces θ-uncertainty, which compounds across future tasks. [HC] |
| (b) | **Verify a high-stakes assumption** | "Trust but verify": JARVIS is confident, but the action is irreversible | **CIRL framing** — via corrigibility value (see §3). Pure cost framing prices this at ~0 gain (confident ⇒ VoI ≈ 0 ⇒ don't ask) and would get it wrong; Cycle 1 rescued it only with a hard gate outside the pricing | Cost framing misses it *inside* the pricing. This is the single most important case the CIRL framing contributes: the off-switch-game logic says uncertainty about the objective is what keeps the game cooperative — and when confidence is high, the *predicted* incentive to accept oversight decays (Cycle 8, Result 9). The verify-ask is the structural countermeasure. [HC] |
| (c) | **Calibrate the user's mental model** | Shape H's model of the situation / of JARVIS's beliefs, so future corrections are cheap and expectations are right | **CIRL framing** — communicativeness: R should take actions informative of its beliefs (Fisac et al. 2017 pragmatic-pedagogic alignment; Cycle 8, Result 8: "narrate the uncertain part, not the confident part") | Cost framing treats this as a zero-VoI ask and skips it. Misses the compounding return: a user with an accurate model of JARVIS corrects *faster and earlier*, which is future VoI purchased now. [HC] |
| (d) | **Obtain information only the user has** | U6a: the fact exists nowhere except in the user's head | **Both** — this is the canonical high-VoI ask in the cost framing, and in CIRL it is the standard information-gathering action | Neither misses it, but the framings disagree on *how*: cost framing asks once, minimally; CIRL notes H is also a teacher (Theorem 3, DBE suboptimality — Cycle 8, Result 3) and that corrections are instructive demonstrations, so the *way* the question is framed can invite teaching, not just a slot-fill. [MC] |
| (e) | **Maintain common ground / signal corrigibility** | Keep the oversight channel warm; demonstrate deference; preserve H's ability to intervene | **CIRL framing** — the ask is a move in the repeated game: it signals "I remain checkable," which is what keeps the equilibrium cooperative as R's capability/confidence grows | Cost framing cannot price this at all — it looks like pure cost. Yet Cycle 1's rubber-stamping warning (§3.2) is the *negative* of this purpose: every unnecessary question spends the same trust account that purpose-(e) asks deposit into. The two purposes share one ledger. [HC] |

**Reconciliation reading of the table [HC]:** purposes (a) and (d) are the cost framing's home turf; (b), (c), (e) are the CIRL framing's. A pricing rule that only counts (a)+(d) systematically under-asks on high-stakes actions and under-communicates on coordination — exactly the two gaps the hard gates in Cycle 1 were papering over. The unified rule prices all five in one currency (§3).

---

## 3. The unified pricing model — the decision rule

### 3.1 The rule, written out

```
ASK-VALUE(q, context):   # q = a candidate question (or confirmation, or narration)
  GAIN:
    G_u(q)  = expected reduction in cost of wrong action from the answer
              # classic VoI: P(wrong) × C_wrong avoided; purposes (a), (d)
              # = 0 if the answer cannot change the decision (learn-math-for-jarvis §3)
    G_a(q)  = expected improvement in H's model of R / the situation
              # better-calibrated expectations → cheaper future corrections;
              # pedagogic value: teaches H what information R needs; purposes (c), (d-lite)
    G_c(q)  = corrigibility / oversight value
              # re-grounding: preserves H's ability to intervene;
              # counter to predicted corrigibility decay (Cycle 8, Result 9);
              # purposes (b), (e)
              # LARGE by construction on tier-3 / irreversible actions
  COST:
    C_i(n)  = interruption cost: base annoyance × growth with n = questions already
              asked this task × user-state modifier (frustrated >> deliberate)
              # redundancy cost: C_i grows with n_a(t) (arXiv 2511.08798)
    C_t(m)  = trust-erosion cost: expected loss of FUTURE confirmation value
              # rubber-stamping: over-asking trains blind approval, destroying the
              # safety value of the questions actually needed (Cycle 1 §3.2)
              # super-linear in m = unnecessary questions asked recently
    C_l     = latency cost of the ask round-trip (modality-dependent:
              voice >> chat >> background)

  PRICING:
    ASK  iff  G_u + G_a + G_c  >  C_i + C_t + C_l
           AND n_asked < 3        (soft budget = sequence guard; §5)

  HARD GATES (override — equivalently, G_c set ≫ C on these):
    - tier-3 / irreversible action → ASK (confirmation with visible payload),
      regardless of confidence. [re-grounding mandate, Cycle 8 Result 9]
    - divergent interpretations × irreversible action → ASK, always. [Cycle 1, VC]
    - tier-3 confirmation is NEVER replaced by narration. (Narration ≠ consent.)

  CHEAP ASK (narration):
    NARRATE the uncertain part iff G_a(narration) > C_narration (≈ 0)
      # i.e., narrate whenever there is material uncertainty worth exposing
      # narration is a communicative act with ~zero interruption cost (§4)

  FALLBACK: steps 1–3 of Cycle 1 unchanged (impossible → escalate; U6b → self-serve;
    U6c → honest abstention). The pricing rule governs the ask/act choice only
    after those filters.
```

**Key claim [HC]:** the hard gates are not exceptions to the pricing — they are the pricing with G_c correctly valued. "Divergent × irreversible → always ask" is what `G_c(confirm) ≫ C` looks like when irreversibility makes the oversight value dominate. The reconciliation is complete when the gates *fall out of* the rule rather than being bolted onto it.

### 3.2 What changed vs Cycle 1's rule

1. **Gain term widened:** VoI(ask) → G_u + G_a + G_c. Purpose-(b) asks (confident-but-irreversible) now price *inside* the rule instead of via an external gate.
2. **Cost term widened:** C_ask → C_i + C_t + C_l. The rubber-stamping warning becomes a priced term (C_t), not a paragraph of caution — this is what stops degenerate over-asking under the CIRL framing (§5).
3. **Budget demoted from rule to guard:** ~2–3 is no longer a heuristic cap on top of the pricing; it is the sequence-level backstop the pricing alone cannot provide (each individual ask can be marginally positive while the interrogation as a whole is degenerate — see §5).
4. **Narration promoted:** from a UX nicety ("act with narrated assumption") to a priced communicative action with ~zero cost and positive G_a (§4).

### 3.3 Design notes for implementation as the brain's asking controller

- **Controller inputs per turn:** (i) interpretation set with consequence classes (Cycle 1 step 4); (ii) risk tier of the candidate action; (iii) belief-ledger variance on the relevant preference/interpretation (Cycle 8 Candidate A — stakes × uncertainty gating); (iv) n_asked this task; (v) a rolling count of recent unnecessary questions (for C_t); (vi) modality (voice/chat/background).
- **Controller outputs:** ASK (with the highest-priced question, batched) / ACT / ACT+NARRATE / ESCALATE. Same action set as Cycle 1; richer pricing behind it.
- **Metalevel cost constraint:** the pricing evaluation must be arithmetic on ledger values, not a model call — same ≤5% metalevel-overhead discipline as learn-bounded-rationality.md Part I §3.3. If pricing the ask costs more than the ask, the controller has become the tax.
- **G_a and G_c are the least measurable terms** (see §7) — ship with conservative priors: G_a small-positive for narrations, G_c large on tier-3 and ~0 elsewhere, and let the measurement program (§7) move them.

---

## 4. Worked scenarios

### Scenario 1 — Vague tier-2 request: "Book something nice for dinner"

- **Underspecification:** U2 (cuisine, budget, area, time, party size all missing); interpretations diverge widely in outcome.
- **Pricing:** G_u is large — P(wrong interpretation) is high (near-uniform over cuisines/areas) and C_wrong is real (a bad booking wastes an evening and money; hard to undo a reservation gracefully). G_a is moderately positive: the question also teaches Owais what information JARVIS needs for bookings, reducing future asks (pedagogic value). G_c ≈ 0 (tier-2, reversible-ish; no oversight value beyond the information). C_i is moderate — one batched turn; C_t ≈ 0 (first question, clearly necessary); C_l small (chat modality).
- **Decision: ASK.** One batched question: "What cuisine, budget, and area — and for when?" Highest-VoI slots first; never re-ask an aspect already asked.
- **Framing verdict:** both framings agree here; the CIRL addition (G_a's pedagogic value) is a bonus, not the decider. [HC]

### Scenario 2 — Confident-but-irreversible tier-3: "Delete this file" (referent resolved from context, high confidence)

- **Underspecification:** U1, apparently resolved — JARVIS is ~95% sure which file "this" is.
- **Pure cost framing would say:** VoI(ask) ≈ 0 (confident ⇒ the answer won't change the action) < C_ask ⇒ ACT. This is the dangerous failure the CIRL framing exists to prevent.
- **Unified pricing:** G_u ≈ 0 (genuinely — confidence is high). But G_c is LARGE by construction on tier-3: (i) re-grounding mandate — confidence must never buy exemption from oversight (Cycle 8, Result 9: the predicted equilibrium of learning is decaying corrigibility); (ii) conservative agency — irreversibility weights alongside stakes (Turner, Hadfield-Menell & Tadepalli, AIES 2020); (iii) the instruction is a noisy observation (IRD; Candidate B) — "this" resolved from context is exactly the kind of crisp-looking signal that should be treated as noisier than it looks. G_u + G_a + G_c ≫ C_i + C_t + C_l.
- **Decision: ASK — as confirmation, not clarification.** Show the exact file (visible payload — learn-frontend doctrine), require explicit confirmation. This is purpose (b): trust-but-verify.
- **Framing verdict:** the cost framing alone gets this wrong; the hard gate in Cycle 1 got it right for the wrong reason (outside the pricing). The unified rule gets it right *inside* the pricing, via G_c. This scenario is the proof that the reconciliation matters. [HC]

### Scenario 3 — Routine task where narration suffices: "Play some music"

- **Underspecification:** U2 but convergent — interpretations (which music?) diverge in content but all are low-stakes and instantly reversible.
- **Pricing:** G_u ≈ 0 (the answer can't change much — any music satisfies the convergent set). A full question would price C_i > G — don't ask. But narration: G_a(narration) is small-positive (exposes the assumption "your liked playlist," making correction one word instead of a new request) and C_narration ≈ 0 (ambient, non-blocking).
- **Decision: ACT + NARRATE the uncertain part.** "Playing your liked songs — say the word to change it." Per Cycle 8, Result 8: narrate the *uncertain* part (the choice of playlist), not the confident part ("I am now playing audio").
- **Framing verdict:** the cost framing says ACT (correct); the CIRL framing adds the narration as a priced communicative act (also correct, and strictly better). Narration substitutes for the question here because correction is cheap and instant. [HC]

---

## 5. Narration as cheap asking

**Thesis [HC]:** narration is a communicative act with C_interrupt ≈ 0 that purchases G_a (alignment of the human's model). It is not a degraded question — it is a *different-priced* ask: near-zero cost, no blocking, correction invited but not demanded.

**When narration substitutes for a question:**

1. Stakes ≤ tier 2 (reversible or trivially correctable — the 30-second undo buffer widens this region).
2. The uncertainty is about something the user can correct *after* seeing the action cheaply ("wrong playlist" → one-word correction), not something that must be supplied *before* acting (U6a — "who should I email?" cannot be narrated; there is nothing to act on).
3. The correction channel is actually open in this modality (voice: the user is present and can interrupt; chat: the message is visible).

**When narration fails:**

1. **The user doesn't read notifications.** Narration-as-ask assumes a read-rate > 0. If narration goes to a channel Owais demonstrably ignores, G_a(narration) → 0 and the "cheap ask" purchased nothing — it becomes theater. This is why read-rate is a measurement target (§7.3), and why the rule must treat *unread* narration as *no* narration.
2. **Irreversible actions (tier-3).** Narrating "deleting your file now" is not consent; a correction that arrives after deletion is worthless. The re-grounding mandate forbids substituting narration for tier-3 confirmation — always. [VC]
3. **Narration of the confident part.** A narration that only states what JARVIS is sure about ("I have completed your request") is communicatively dead (Cycle 8, Result 8). It spends ~zero cost but also buys ~zero G_a. The discipline: narrate the *uncertain* part, the assumption the user would most want to correct.
4. **Narration as a stream.** Continuous narration of every micro-step reintroduces interruption cost through the back door (notification fatigue → read-rate collapse → failure mode 1). Narration budget: narrate decisions, not steps.

**Implementation rule [DESIGN]:** `NARRATE iff (tier ≤ 2) AND (reversible OR read-rate high) AND (there exists material uncertainty worth exposing)`. Tier-3: never narration-instead-of-confirmation. Unread channel: treat as no narration.

---

## 6. Ask-budget revisited — dissolved, then restored as a guard

**Cycle 1's ~2–3 budget was heuristic [HC]. What the unified model says:**

1. **The budget dissolves into per-decision pricing for the typical case.** With C_i growing in n (redundancy cost) and marginal G_u declining (the highest-VoI question is asked first; the 4th question's VoI is the residual), the pricing rule *already* implies a stopping point — usually around 1–3 asks for normal tasks. The budget is the shadow price λ made visible, not a separate mechanism (§1).

2. **But per-decision pricing alone is insufficient — the sequence can be degenerate.** Each individual question can pass `G > C` while the interrogation as a whole fails: multi-turn underspecification drift (the user answers ambiguously; each follow-up looks locally justified), and the "20-questions agent" that is locally rational at every step and globally intolerable. This is the classic failure of greedy myopic rules — noted in learn-bounded-rationality.md Part I §3.3 for computation, and it applies identically to elicitation.

3. **So the budget returns as a sequence-level guard, not a pricing term:** `n_asked < 3` per task, after which the controller switches from ASK to ESCALATE-with-blocker ("here's what's missing, here's the closest I can do without it"). The budget is the recursion guard for drift, the backstop for misestimated per-question VoI, and the embodiment of the Lagrange multiplier when the controller's G/C estimates are uncalibrated (which, pre-measurement, they are).

**What stops degenerate over-asking under the CIRL framing — four mechanisms, all inside the model [HC]:**

1. **C_t, the trust-erosion term.** Over-asking trains blind approval (rubber-stamping), which destroys the safety value of the confirmations that actually matter. The C_t term makes the 5th unnecessary question *expensive* — it spends the trust account that tier-3 confirmations draw on. Communicativeness is only optimal while communication remains *attended to*.
2. **H's bounded rationality (Cycle 8, Result 6).** Assume the human is noisier than they look: beyond a few questions, answer quality collapses ("whatever, just do it") — G_u and G_a saturate and then reverse, because inattentive answers are *mis*information. The game-theoretic optimum never asks past the point where H stops answering carefully.
3. **Redundancy cost.** Cost(q,t) grows with n_a(t) (arXiv 2511.08798): each additional question on the same task is priced higher than the last, independent of content.
4. **The escalation switch at n=3.** When the budget guard fires, the controller stops pricing questions and states the blocker — the "20 questions" equilibrium is unreachable by construction.

**Verdict [HC]:** the budget is neither kept as a heuristic nor discarded — it is *re-derived* as the sequence-level Lagrange guard on top of per-decision pricing. The controller prices each ask dynamically; the budget catches the cases where the pricing is wrong.

---

## 7. What remains unmeasurable — measurement targets for the instrumentation phase

These parameters cannot be set by theory; they need production data. Ranked by load-bearing importance:

| # | Parameter | What it is | Why theory can't set it | How to measure it |
|---|---|---|---|---|
| 1 | **C_i base + growth curve** | Interruption cost of one question; how it scales with n_asked, user state (frustrated vs deliberate), and modality | Annoyance is a property of Owais, not of decision theory | Log n_asked per task vs task-completion/abandonment; correlate with observable frustration signals (rephrasing, "just do it", session abandonment). Needs the interaction log to exist first. |
| 2 | **Trust-erosion rate (C_t)** | The rubber-stamping function: blind-approval rate as a function of unnecessary-question frequency | The safety-account balance is behavioral and user-specific | A/B the question rate on low-stakes tasks; measure approval latency and reversal rate on subsequent tier-3 confirmations. (Already open-problem #10 in learn-open-problems.md.) |
| 3 | **Narration read-rate** | P(Owais actually registers a narrated assumption), per modality and channel | Determines whether narration-as-ask is real or theater (§5) | Instrument: narrate a material assumption, then measure correction rate vs a control where the assumption is unstated. If corrections don't rise, read-rate ≈ 0 on that channel. |
| 4 | **P(wrong interpretation) distribution** | The discriminator's real accuracy per task type — the G_u term's core input | No substitute for measured performance on JARVIS's real tools | Golden-set eval (learn-underspecification.md §5, 30 tasks) + inter-rater check with Owais as rater. (Already open-problem #3.) |
| 5 | **H's answer-quality decay curve** | How answer informativeness degrades with question count ("whatever, just do it" point) — bounds G_u/G_a for late questions | Depends on Owais's patience profile | Log question index vs answer specificity (slot-fill rate, correction rate on the resulting action). |
| 6 | **G_c magnitude (corrigibility value)** | The value of a confirmation that changes nothing but keeps oversight warm | Counterfactual by nature — the value is in the disasters that *don't* happen | Proxy: incident/counterfactual review; stated-preference ("would you want me to confirm even when sure?"); near-miss logging. Hardest to measure honestly — treat the tier-3 mandate as architectural (non-negotiable) rather than waiting for this number. |
| 7 | **Corrigibility-floor height** | Minimum posterior variance — how much uncertainty to preserve (Cycle 8, open question 1) | Theory demands a floor but gives no height | Empirical tuning: too high → learned helplessness (ask-forever); too low → the decay prediction bites. Tune against correction-rate and autonomy-success metrics. |
| 8 | **G_a magnitude (alignment value)** | Future correction-cost saved by one unit of present communication | Compounding, long-horizon, confounded | Long-horizon proxy: does narration density correlate with fewer corrections per task over weeks? Needs the longitudinal ledger. |
| 9 | **C_l per modality** | Latency cost of an ask round-trip (voice vs chat vs background) | Depends on Owais's felt time-cost per context | Voice: barge-in/abandonment timing; chat: reply latency tolerance; background: essentially free. |
| 10 | **Hinglish ambiguity density** | Whether code-switched requests carry ambiguity signals absent in English (Cycle 1 unknown #3) | Linguistic, user-specific | Log deixis density ("ye"/"woh") vs clarification rate in Hinglish vs English turns. |

**Standing rule [DESIGN]:** until a parameter is measured, its prior errs in the fail-safe direction — G_c large on tier-3 (never relax the mandate for lack of data), C_t assumed super-linear (don't over-ask to "gather data" on the trust account), narration assumed unread on unproven channels. Absence of measurement is never evidence for relaxing a safety term.

---

## 8. Confidence tags

- **[VC]** The Lagrange-multiplier identity (budget as dual of the attention-constrained objective); narration must never substitute for tier-3 confirmation; the five-purpose taxonomy's coverage claims for (a)/(d); U6b/U6c filters precede pricing.
- **[HC]** The unified pricing rule as stated (structure right, terms right, magnitudes unmeasured); G_c rescuing purpose-(b) inside the pricing; the four anti-degenerate mechanisms; the budget-as-sequence-guard verdict; narration's substitution conditions.
- **[MC]** Exact functional forms (linear vs super-linear C_t; the n=3 guard value — inherited heuristic, not derived); G_a's pedagogic component size; the claim that per-decision pricing typically implies ~1–3 asks (depends on unmeasured C_i curve).
- **[SP]** Whether the brain can evaluate the pricing in ≤5% metalevel overhead on the voice path (arithmetic on ledger values — plausible, unbuilt).
- **[UK]** All ten measurement targets in §7; whether Owais's C_i curve matches the assumed shape; the corrigibility-floor height.

## 9. Unknowns (ranked)

1. Every parameter in §7 — the rule is a *shape*, not a tuned controller, until production data fills it.
2. Whether G_a (alignment value) is large enough to ever flip a decision on its own, or whether it only ever breaks ties — determines if communicativeness is a first-class driver or a tiebreaker.
3. Interaction with the approval UX: when does a purpose-(a) clarifying question *become* a purpose-(b) confirmation? The ASK/CONFIRM boundary needs design (Cycle 1 unknown #4, still open).
4. Multi-principal future: the pricing assumes one principal's attention budget; shared-device use reintroduces competing budgets (Cycle 8, B6).
5. Whether the escalation-with-blocker at n=3 is experienced as helpful or as giving up — needs Owais as rater.

## Integration notes

- **Consumes:** `learn-underspecification.md` §3 (8-step rule, VoI, ask budget, hard gates, rubber-stamping, golden set); `learn-assistance-games.md` (communicativeness, humility, θ-uncertainty, noisy instructions, corrigibility decay, Candidates A/B/C); `learn-math-for-jarvis.md` §3 (VoI one-liner, asymmetric loss); `learn-bounded-rationality.md` (myopic/greedy failure modes, metalevel ≤5%, rubber-stamping as automation-bias-adjacent trust dynamics).
- **Produces:** the asking controller spec — inputs, pricing rule, hard gates, narration rule, budget guard — ready to be wired into the brain's turn loop once §7's measurement program yields numbers.
- **Feeds:** DECISION-PLAYBOOK.md — ADR candidate: *"JARVIS v2 shall implement asking as joint-utility pricing (G_u + G_a + G_c > C_i + C_t + C_l) with a sequence-level budget guard at n=3 and an architectural tier-3 confirmation mandate; narration is a priced communicative act, never a tier-3 substitute. Status: PROPOSED — parameters unmeasured, see §7."*
- **Resolves** the open question left in `learn-assistance-games.md` §7.4 (reconciling the ask-budget framing with the CIRL framing): the budget is the Lagrange multiplier on the attention constraint; the hard gates are the pricing rule with G_c correctly valued.

---

## References

Real citations only; all previously verified in Cycles 1/6/8. Nothing fabricated.

- Hadfield-Menell, D., Dragan, A., Abbeel, P., & Russell, S. **Cooperative Inverse Reinforcement Learning.** *NeurIPS 2016.* (Assistance games; posterior sufficiency; teaching/asking as optimal play; DBE suboptimality.)
- Hadfield-Menell, D., Dragan, A., Abbeel, P., & Russell, S. **The Off-Switch Game.** *IJCAI 2017.* (Uncertainty about the objective as the incentive for cooperative/deferential behavior.)
- Milli, S., Hadfield-Menell, D., Dragan, A., & Russell, S. **Should Robots Be Obedient?** *IJCAI 2017.* arXiv:1705.09990. (Obedience/autonomy tradeoff; underestimate human rationality; MLE-R robustness.)
- Hadfield-Menell, D., Milli, S., Abbeel, P., Russell, S., & Dragan, A. **Inverse Reward Design.** *NeurIPS 2017.* arXiv:1711.02827. (Instructions as noisy observations; risk-averse planning under reward uncertainty.)
- Fisac, J. F., et al. **Pragmatic-Pedagogic Value Alignment.** *ISRR 2017.* (Communicative/pedagogic actions — the formal backing for purpose (c).)
- Turner, A. M., Hadfield-Menell, D., & Tadepalli, P. **Conservative Agency via Attainable Utility Preservation.** *AAAI/ACM AIES 2020.* (Reversibility/irreversibility weighting — purpose (b)'s mechanism.)
- Russell, S. **Human Compatible.** Viking, 2019. (Three principles; humility/communicativeness/diligence.)
- Howard, R.A. (1966), "Information Value Theory," *IEEE Trans. Systems Science and Cybernetics*, 2(1). (VoI — G_u's foundation.)
- "Value of Information: A Framework for Human–Agent Communication," arXiv 2601.06407. (NetVoI(q) = VoI(q) − c.)
- "Structured Uncertainty guided Clarification," arXiv 2511.08798. (EVPI question selection; redundancy cost — C_i's growth term.)
- Simon, H.A. (1955), "A Behavioral Model of Rational Choice." (Satisficing; aspiration levels — the budget guard's philosophical parent: stop eliciting at "good enough to act.")
- Russell, S. & Wefald, E. (1989/1991), *Do the Right Thing*. (Myopic metareasoning — why greedy per-question pricing needs the sequence guard.)
