# Assistance Games & CIRL — The Game-Theoretic Keystone of "Helpfulness"

**Research question:** What do assistance games and cooperative inverse reinforcement learning imply for JARVIS's help-under-uncertainty architecture?
**Status:** Research complete (Cycle 8, PHASE INFINITY). Theory distillation + design translation. Nothing validated on real usage; all candidate additions are proposals with verdicts.
**Date:** 2026-10-19

---

## 0. Why this cycle exists

Cycle 1 built an 8-step ask/act/escalate rule from the underspecification taxonomy. Cycle 7 grounded it in bounded rationality. But both rest on an *assumed* answer to a deeper question: **when should an assistant act on uncertain beliefs about what the user wants, when should it ask, and when should it obey a literal instruction versus inferring the intent behind it?** Hadfield-Menell et al.'s assistance games (originally "cooperative inverse reinforcement learning," CIRL, 2016) are the formalization of exactly this question. This file distills it and maps it onto the existing architecture. Nothing prior is re-taught; everything here points at decisions the existing files already made and shows which of them were theoretically load-bearing all along.

---

## 1. The formalism, in plain language

An **assistance game** (CIRL game) is a two-player game of partial information with two agents — human H and robot R — and **one shared reward function**, which only H knows [VC, from the paper's Definition 1].

The tuple: `M = ⟨S, {A_H, A_R}, T, {Θ, R(·;θ)}, P₀, γ⟩`.

- **S**: world states. **A_H, A_R**: each player's actions. **T**: transitions.
- **θ ∈ Θ**: the reward parameters — the true objective. Only H observes θ.
- **R(s, a_H, a_R; θ)**: the reward both players get, determined by H's true objective.
- R starts with a **prior** over Θ and must learn θ *while acting*, from H's behavior.

Three structural facts do all the work:

**F1 — The posterior is a sufficient statistic.** Computing optimal play reduces to solving a single-agent POMDP, exponentially easier than the general Dec-POMDP (NEXP-complete) case — and there exist optimal policies where R's behavior depends *only on the current state and its belief over θ* (Theorem 1, Corollary 1) [VC]. In engineering terms: **the belief about the user's objective is the whole decision state.** A preference estimate without its uncertainty is an incomplete input to any action rule.

**F2 — Optimal play produces teaching and asking, not just acting.** In contrast to classical IRL — where the human is assumed to act optimally *in isolation* (the "demonstration-by-expert" assumption) — optimal assistance-game play has H *teach* and R *interleave learning with acting*, managing the explore–exploit tradeoff (Abstract; Russell's 2019 summary of the three principles) [VC]. The behaviors the pipeline already wants — narrating assumptions, spending an ask budget — are not UX polish; they are what optimal play *looks like*.

**F3 — The standard model is the wrong model.** Standard RL assumes a fixed, known reward function. Supervised learning assumes the human's demonstrations are the thing to imitate. Both are wrong for personal assistance: the human's true objective is **unknown to the agent, misspecifiable, and only partially revealed by any single instruction or demonstration** (Introduction: the vacuum-robot and King Midas examples) [VC]. The assistance game is the first formalism that treats "the user knows what they want and I don't" as the *central* structure rather than as noise.

Russell's three principles from *Human Compatible* (2019) are the slogan form of the same game, and the virtues they imply map directly onto design vocabulary this pipeline already uses [HC — well-attested summary, see nunosempere forum summary of the book]:

1. The machine's objective is to maximize the realization of **human preferences** (not its own).
2. The machine is **initially uncertain** about what those preferences are.
3. The machine must **learn** them from human behavior — while behaving in ways that make that learning possible.

The corresponding agent virtues: **humility** (don't take high-stakes actions when uncertain — risk tiers), **communicativeness** (take actions that reveal information, including revealing your own uncertainty — narrated assumptions, ask budget), **diligence** (act autonomously and ambitiously when the uncertainty is resolved — satisficing execution) [HC — the triad is Russell's standard framing across book and talks; the JARVIS mappings are mine].

---

## 2. Key results and their JARVIS translations

| # | Result (source) | What it says | JARVIS translation | Status |
|---|---|---|---|---|
| 1 | Posterior sufficiency (CIRL 2016, Cor. 1) | R's optimal policy needs only (state, belief over θ) | The Beta-Bernoulli belief ledger (learn-math-for-jarvis.md) **is** the decision state. Point estimates of preferences without their variance are an incomplete input — see Candidate A. | Gap → A |
| 2 | Uncertainty makes cooperation optimal (Off-Switch Game, Hadfield-Menell et al., IJCAI 2017) | A rational H is sufficient to incentivize R to permit shutdown **only under uncertainty about the objective**; "uncertainty about the objective is crucial to incentivizing cooperative behaviors" | The ask/act/escalate rule is not a cost center — it is the mechanism of alignment. The ask budget is what keeps the game cooperative. Never optimize it away for "efficiency." | Reframe of existing |
| 3 | DBE suboptimality (CIRL 2016, Thm. 3; Remark 3) | Expert demonstrations are *not* H's best response; experienced users produce **instructive** demonstrations optimized for teaching, sacrificing immediate reward to improve R's estimate | Owais's corrections, rephrasings, and "no, like this" moments are information-dense *teaching* moves, not noise. Weight corrections above passive acceptance in the ledger; offer a "show me" channel — see Candidate C. | Gap → C |
| 4 | Obedience/autonomy tradeoff (Milli et al., "Should Robots Be Obedient?", IJCAI 2017) | When H is not perfectly rational, an IRL robot that infers preferences **always beats** a blindly obedient one — but there is a real tradeoff, and the practical recommendation is a middle ground that **errs on the side of obedience** | The 8-step rule's tier structure *is* this middle ground operationalized. Literal obedience is the default on high stakes / low model-confidence; intent-inference earns its autonomy by demonstrated accuracy. The U3/U4 handling (ambiguous scope, contradictions) is where the tradeoff lives. | Reframe of existing |
| 5 | MLE-R robustness (Milli et al. 2017, findings 3–5) | An MLE-based IRL robot is **more obedient** than the theoretically optimal one, and this is a *feature*: it is robust to wrong estimates of human rationality (β) and to wrong feature sets; "err on the side of extra features" beats fewer | Two concrete rules: (a) when expanding capability (new provider, new skill), keep the preference hypothesis set **wide** — premature collapse to a few features is the dangerous direction; (b) detect model misspecification by watching the first-order obedience rate — if JARVIS keeps needing to be corrected on first attempts, the feature set is wrong. | Partially new |
| 6 | Underestimate human rationality (Milli et al. 2017; Hadfield-Menell, FLI interview) | There is a sweet spot in assumed human rationality: assuming *too much* rationality extracts more information per observation but fails catastrophically when wrong; the safe side is to **underestimate** | Treat Owais's instructions as noisier than they look. A crisp instruction is still one noisy sample of θ, not θ itself — see Candidate B. Contradictory instructions across sessions (U4) should trigger clarification, not aggressive belief overwrite. | Gap → B |
| 7 | IRD: reward functions are observations (Hadfield-Menell et al., NeurIPS 2017) | A designed/proxy reward is **evidence about** the true objective, interpreted in the context where it was produced; combined with risk-averse planning this mitigates reward hacking and negative side effects | This is the formal reason behind R2 ("instructions as data, not commands"). Extends to JARVIS's own telemetry: thumbs-up, acceptance, dwell — all proxy rewards, all observations, none of them the objective. On new territory (new skills/providers), plan risk-aversely: narrate, confirm, then optimize. | Formal backing for R2 |
| 8 | Communicative actions (CIRL 2016, §3.4; Fisac et al. 2017 pragmatic-pedagogic alignment) | R should compute actions informative of the *correct* θ; H likewise acts to reduce R's entropy | Narrated assumptions (existing) get a sharper spec: **narrate the uncertain part, not the confident part.** Exposing R's belief is what lets H correct it cheaply. A narration that only states what JARVIS is confident about is communicatively dead. | Refinement |
| 9 | Corrigibility decay (Hadfield-Menell, FLI interview) | As R's confidence in θ grows over time, the math predicts its incentive to accept oversight **decays** — "you can predict that it should lose that incentive over time" | Structural countermeasure required, not willpower: an **uncertainty floor** (belief never fully sharpens) plus a **re-grounding mandate** (high-stakes actions always confirm, regardless of confidence). Confidence must never buy exemption from oversight. | New policy |
| 10 | Conservative agency (Turner, Hadfield-Menell & Tadepalli, AIES 2020) | Penalize actions by their side effects on the ability to optimize *unknown* future objectives (attainable utility preservation) | Humility's mechanism: prefer reversible actions. The risk tiers should weight **irreversibility** alongside stakes — a low-stakes irreversible action (deleting, sending) outranks a high-stakes reversible one (drafting, previewing). | Refinement |
| 11 | Assistance games scale to real users (AssistanceZero, 2025) | Assistance-game-trained assistants reduced users' required actions vs SFT baselines; users rated them more helpful; advantages came from **predicting goals, responding to corrections, adapting assistance level** | Validates the whole direction: the three behaviors in the finding are exactly humility (adapt level), communicativeness (respond to corrections), diligence (predict goals). Human assistants still won — the ceiling is "good human assistant," which is a useful product target to name. | Validation [MC — via secondary summary] |

---

## 3. Inverse reward design — why R2 is formally necessary

Cycle files assert R2: *instructions are data, not commands.* IRD supplies the proof sketch for why anything else fails [HC]:

1. Any instruction Owais gives was produced **in a context** — his current task, his patience level, what he assumes JARVIS knows. The instruction is an observation `O ~ P(O | θ, context)`, generated by a process that optimized for *communicating under constraints*, not for *stating θ exactly*.
2. Optimizing the literal instruction is reward hacking's domestic cousin: "book something nice" optimized literally produces *a* booking, not the one he'd endorse on reflection. The IRD paper's lava-gridworld is the same shape as "delete the old files" — the proxy succeeds in the training context (his past tolerance) and fails in the new one (this folder matters).
3. The fix has two halves, and the pipeline already has both words but only one mechanism: (a) **infer** the true objective from the instruction + context (belief update — have), (b) **plan risk-aversely** in proportion to remaining uncertainty about the objective (uncertainty-gated autonomy — gap, Candidate A).

Practical consequence: every prompt/instruction handler should be built as an *observation model with a noise term*, never as a command parser. The noise term is not a fudge factor — it is the quantity that the obedience/autonomy tradeoff (Result 4) and the rationality-sweet-spot (Result 6) are both about.

---

## 4. What breaks in practice — CIRL vs Owais

The formalism's assumptions fail in specific, predictable ways. Each failure is a design constraint [MC overall — these are my extrapolations from the papers' stated limitations plus the pipeline's user model]:

**B1. θ is not static — preference drift.** CIRL assumes a fixed θ that H knows. Owais's θ drifts: tastes change, projects end, yesterday's "always do X" becomes today's annoyance. A belief that only sharpens will become confidently wrong. *Constraint:* the belief ledger needs **forgetting/decay** (this connects to the temporal markers in learn-bounded-rationality.md and preference provenance in learn-privacy-engineering.md — inferred preferences must carry `until:` dates; confirmed ones decay slower but still decay).

**B2. H is not Boltzmann-rational — he satisfices and contradicts himself.** The papers model human suboptimality as noise around the optimum (β parameter). Real Owais: U4 contradictions across sessions ("make it fast" Monday, "make it perfect" Friday), satisficing under his own time bounds (Cycle 7), strategic testing of the agent. *Constraint:* Result 6's advice (underestimate rationality) is the floor, not the ceiling — contradictory instructions must be treated as **evidence of a changed or context-dependent θ**, never silently averaged into the old one.

**B3. H teaches adversarially-by-accident.** Theorem 3 says experienced users deviate from demonstration-by-expert *to teach*. But Owais will also deviate because he's in a hurry, because he's testing JARVIS, because he misspoke. R cannot distinguish "instructive demonstration" from "sloppy instruction" from a single sample. *Constraint:* this is exactly what Candidate B's noise model is for — down-weight single surprising observations, up-weight repeated ones.

**B4. Partial observability breaks the clean results.** Russell notes (FAR.AI talk) that the original formulation assumes full observability and that partial observability introduces failure modes the theorems don't cover — agents that hide messes rather than cleaning them. *Constraint:* JARVIS acts through tools with hidden side effects (files changed, messages sent). The humility tier must cover **observability of consequences**, not just stakes: if JARVIS can't see what an action did, it must act as if stakes are one tier higher.

**B5. The corrigibility-decay prediction is the dangerous one.** A JARVIS that learns well *should*, by the off-switch math, become progressively less receptive to correction. This is not a bug to patch later — it is the **predicted equilibrium** of the learning dynamics. *Constraint:* the uncertainty floor + re-grounding mandate (Result 9) must be architectural, not a policy suggestion. Concretely: no preference ever reaches zero variance; no high-stakes action skips confirmation no matter how long the track record.

**B6. Single principal is a simplification that mostly holds.** Multi-principal assistance games (Fickinger et al., NeurIPS CoopAI Workshop 2020) handle competing humans. JARVIS has one principal (Owais), which dodges the social-choice machinery — but household/shared-device use would reintroduce it. *Constraint:* note it, don't build it; keep the belief ledger single-principal-shaped so the extension is possible.

---

## 5. Candidate additions — with honest verdicts

### Candidate A — Uncertainty as a first-class gate on autonomy [ADOPT]

**What:** The ask/act/escalate tiers currently gate on *stakes*. CIRL's Corollary 1 says the decision state is (state, belief-over-θ) — so tiers must gate on **stakes × uncertainty**. Concretely: the Beta-Bernoulli ledger already maintains a posterior per preference; expose its variance. Rule sketch: act autonomously only when `stakes < f(uncertainty)`; as uncertainty → 0 the allowed stakes rise, but Result 9's floor means uncertainty never actually reaches 0, so the top tier always confirms.

**Why it's cheap:** the math (Beta variance) already exists in learn-math-for-jarvis.md; this is a wiring change, not a research project.

**Honest verdict:** Adopt. It is the single most load-bearing import in this file — it turns the belief ledger from a logging convenience into the decision state the theory says it must be. [HC that the theory supports it; MC on the exact gating function — that needs tuning against real usage.]

### Candidate B — Instructions as noisy observations with an explicit, conservative noise model [ADOPT-LITE]

**What:** Every instruction updates the belief as `P(θ | instruction) ∝ P(instruction | θ, β) · P(θ)`, where β (human reliability in this context) is estimated **conservatively** — biased toward "noisier than it looks" per Result 6. Operationally, not as a Boltzmann fit (unidentifiable on sparse data) but as a coarse per-instruction confidence: crisp, repeated, low-frustration instructions get high weight; first-time, frustrated, or contradicted instructions get low weight and trigger clarification rather than belief overwrite.

**Why lite:** full β-fitting is a research project with poor identifiability on a single user's sparse data; the *lesson* (underestimate rationality, weight by context) ports cleanly without the machinery.

**Honest verdict:** Adopt the concept and the conservative default; do not build the Boltzmann machinery. The failure mode it prevents — one frustrated "just do it however" permanently corrupting a preference — is real and cheap to prevent. [HC on the lesson; MC on any specific weighting scheme.]

### Candidate C — "Show me" as a first-class information channel + correction overweighting [ADOPT]

**What:** Theorem 3 predicts Owais will try to *teach*, not demonstrate optimally. Two changes: (1) when U3/U4 ambiguity recurs on the same task type, offer demonstration explicitly ("show me once and I'll learn the pattern") — demonstration is a higher-bandwidth channel than language for θ; (2) in the ledger, **corrections outweigh passive acceptances** — a correction is an instructive demonstration (costly to H, therefore informative); an accept is weak evidence (cheap, possibly inattentive).

**Honest verdict:** Adopt. Theorem-backed, UI-cheap, and it converts the most frustrating interaction pattern (repeated corrections) into the fastest learning signal. [HC]

### (Not a candidate — a policy) Corrigibility floor [ADOPT AS ARCHITECTURE]

Folded out of Result 9 because it is not optional: minimum posterior variance > 0 for all preferences; high-stakes actions always confirm regardless of track record; interrupt/override always works and is itself logged as a (noisy) observation, never as a system insult. This is the structural answer to the predicted decay of oversight incentives. Not glamorous, not negotiable.

---

## 6. Deliberately NOT importing

| # | Tempting import | Why not |
|---|---|---|
| 1 | Full MaxEnt / Bayesian IRL (Ziebart et al. 2008; Ramachandran & Amir 2007) | Needs dense trajectory demonstrations; assumes demonstration-by-expert, which Theorem 3 shows experienced users *violate on purpose*; θ here is open-ended natural-language preference, not an enumerable feature vector; compute is intractable at real state spaces. The pipeline's Beta-Bernoulli ledger is the right *shape* (belief over θ updated from observations) without the machinery. |
| 2 | Exact CIRL POMDP solving (incl. Malik et al.'s efficient Bellman update, ICML 2018) | Toy-scale by design (|S|·|Θ| still explodes for a real assistant's state space). Import the *structural lesson* (belief is sufficient statistic) as Candidate A, not the solver. |
| 3 | Static-θ assumption | Directly contradicted by preference drift (B1). The belief must be time-varying with decay; a CIRL-pure implementation would become confidently wrong. |
| 4 | Optimal joint policy pairs (perfect H–R coordination) | Real coordination fails constantly — that is what the ask budget is for. Keep explicit clarification as the coordination mechanism; do not assume H plays the equilibrium teaching strategy. |
| 5 | The off-switch game as a literal mechanism | Conversational agents have no off-switches; the game is about corrigibility under capability growth. Import the principle (deference to human control, Result 9's floor), not the game. |
| 6 | Boltzmann-rationality as the fitted human model | Identifiability is hopeless on sparse single-user data, and real suboptimality is systematic (biases, satisficing, strategy), not entropic noise. Keep Result 6's *lesson* (underestimate rationality) via Candidate B's coarse weighting, not the likelihood function. |
| 7 | RLHF-style "reward model then optimize" as the alignment core | AssistanceZero (2025) positions assistance games as an *alternative* to RLHF post-training, with better uncertainty-management incentives. For JARVIS's architecture, the implication is: keep learning θ online from interaction (the ledger), don't freeze a reward model and optimize it — frozen models are exactly what IRD warns against. [MC — one 2025 result, via secondary summary] |

---

## 7. Open questions this cycle leaves

1. **Calibrating the uncertainty floor:** Result 9 demands a floor but the theory doesn't give its height. Too high = learned helplessness (asks forever); too low = the decay prediction bites. This needs empirical tuning, not more theory. [UK]
2. **β per context:** is "frustrated Owais" vs "deliberate Owais" detectable well enough to drive Candidate B's weighting? Prosody/timing features exist in the voice pipeline; text-only sessions are thinner. [SP]
3. **Multi-principal later:** single-principal holds for now (B6), but the ledger schema should not make multi-principal extension impossible.
4. **Relation to the 8-step rule's ask budget:** the rule treats asking as a cost to budget; CIRL treats asking as *the thing being optimized*. Reconciling these framings (budget as Lagrange multiplier on the information-acquisition term) is a clean piece of future work — the VoI machinery in learn-math-for-jarvis.md is the bridge. [MC]

---

## 8. References

All citations verified via web search during this cycle; nothing fabricated. Secondary summaries are tagged where the primary wasn't directly read.

- Hadfield-Menell, D., Dragan, A., Abbeel, P., & Russell, S. **Cooperative Inverse Reinforcement Learning.** *NeurIPS 2016.* (Definition 1, Theorems 1–3, Corollaries; DBE suboptimality.) Primary read. https://proceedings.neurips.cc/paper_files/paper/2016/file/c3395dd46c34fa7fd8d729d8cf88b7a8-Paper.pdf
- Hadfield-Menell, D., Dragan, A., Abbeel, P., & Russell, S. **The Off-Switch Game.** *IJCAI 2017.* (Uncertainty about the objective as the incentive for cooperative/deferential behavior.)
- Milli, S., Hadfield-Menell, D., Dragan, A., & Russell, S. **Should Robots Be Obedient?** *IJCAI 2017.* arXiv:1705.09990. (Supervision POMDP; obedience/autonomy tradeoff; MLE-R robustness to wrong β and wrong Θ; err toward obedience and toward extra features.)
- Hadfield-Menell, D., Milli, S., Abbeel, P., Russell, S., & Dragan, A. **Inverse Reward Design.** *NeurIPS 2017.* arXiv:1711.02827. (Proxy rewards as observations of true intent; risk-averse planning under reward uncertainty.)
- Malik, D., Palaniappan, M., Fisac, J., Hadfield-Menell, D., Russell, S., & Dragan, A. **An Efficient, Generalized Bellman Update for Cooperative Inverse Reinforcement Learning.** *ICML 2018.* (Cited for the tractability line; solver itself not imported — see §6.2.)
- Fisac, J. F., Gates, M. A., Hamrick, J. B., Liu, C., Hadfield-Menell, D., Palaniappan, M., Malik, D., Sastry, S. S., Griffiths, T. L., & Dragan, A. **Pragmatic-Pedagogic Value Alignment.** *ISRR 2017.* (Communicative/pedagogic actions.)
- Russell, S. **Human Compatible: Artificial Intelligence and the Problem of Control.** Viking, 2019. (Three principles; humility/communicativeness/diligence virtues; assistance games as the technical core.)
- Zhuang, S., & Hadfield-Menell, D. **Consequences of Misaligned AI.** *NeurIPS 2020.* (Downstream of the assistance-games program; listed for the research lineage.)
- Turner, A. M., Hadfield-Menell, D., & Tadepalli, P. **Conservative Agency via Attainable Utility Preservation.** *AAAI/ACM AIES 2020.* (Reversibility as humility's mechanism.)
- Fickinger, A., Zhuang, S., Critch, A., Hadfield-Menell, D., & Russell, S. **Multi-Principal Assistance Games.** *NeurIPS Cooperative AI Workshop 2020.* (Why single-principal is a simplification — §4.B6.)
- **AssistanceZero: Scalably Solving Assistance Games.** 2025. (Human-study validation: goal prediction, correction response, adaptive assistance level; positioned as RLHF alternative.) Via secondary summary — treat findings as [MC].
- Russell, S. **Provably Beneficial AI.** *Daedalus*, Spring 2022. (Assistance games as the precise form of "machines uncertain about human objectives"; partial-observability failure modes.)
- Hadfield-Menell, D. Interview, **Future of Life Institute AI Alignment podcast** (on IRL and inferring human preferences). (Corrigibility decay over time; underestimate-rationality sweet spot.) https://futureoflife.org/podcast/podcast-ai-systems-learning-human-preferences/

---

## 9. Honest scope

What this cycle establishes: the game-theoretic reason the pipeline's existing instincts (ask budget, risk tiers, narrated assumptions, instructions-as-data) are correct, four concrete adoptions (A, B-lite, C, corrigibility floor), and a fenced not-import list. What it does **not** establish: any threshold, gating function, or weighting scheme — those need real interaction data. The theory tells JARVIS *what shape* the solution is; only usage tells it the parameters.
