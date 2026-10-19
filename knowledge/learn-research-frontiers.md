# Frontier Research — JARVIS Phase 2, Track 14 (Research Frontiers & Open Problems)

*Learning mission. Research date: October 2026. LEARNING ONLY — no implementation.*

## Rule Zero — Skip Ledger

| Topic from Track 14 list | Status | Reason |
|---|---|---|
| Agentic RL training | **Already covered — skip** | SMITH PhD study complete (`smith-deep-dive.md`); Kinetic-4B LoRA template on file |
| Test-time compute basics | **Already covered — skip** | o1-style reasoning covered in efficiency research; this study adds only the Snell trade-off curve (new) |
| Long-context reliability / compression | **Already covered — skip** | LLMLingua-2 PhD complete (`llmlingua-deep-dive.md`) |
| Memory-augmented models | **Covered — skip** | mem0/Letta/A-MEM/cog studies complete |
| World models & model-based planning | **New — researched below** | |
| Process vs outcome supervision | **New — researched below** | |
| Mechanistic interpretability | **New — researched below** | |
| Limits of self-reflection | **New — researched below** | (extends Harness² finding with published evidence) |
| Inference-time scaling curve | **New — researched below** | (the Snell trade-off, not basics) |
| Temporal knowledge graphs + entity resolution | **New — researched below** | (Track 3 small gap) |
| Human preference evaluation methodology | **New — researched below** | (Track 10 small gap) |
| Efficient adaptation (distillation/LoRA) | **Covered — skip** | SMITH/LoRA covered |
| Formal AI safety approaches | **Partially covered — deferred** | Conscio judgment layer covers the engineering side; mathematical formal methods are out of scope for a 6GB local build |

---

## 1. World Models & Model-Based Planning

**Central claim:** An agent that can *predict* what its actions will do before taking them (a "world model") can plan instead of react. For JARVIS, the environment is the Windows desktop: the world model would predict the next screen/state given an action.

**Mechanism:** Three capability levels (per a 2026 survey of 400+ papers on agentic world models): **predictor** (estimate next state), **simulator** (roll out several future steps after a candidate action), **evolver** (revise the model when predictions fail against new evidence). GUI world models come in three flavors: *text-based* (predict next DOM/UI-tree text), *pixel-based* (diffusion-generated future screenshots), *code-based* (renderable HTML mock of the next state).

**Supporting evidence:**
- **WM-R1** (arXiv 2608.27508, 2026): trains GUI agents with RL *inside* a world model used as the training environment — i.e., the agent practices in simulation instead of the real desktop. Genuine step beyond imitation learning.
- **UI-Simulator / SimuRA** (2025): world models used to simulate agent training. But note: they operate at inference time only — the simulation isn't part of the agent's live decision loop.
- **Imagine-then-Plan** (arXiv 2601.08955): "mental sandbox" agents; LLM-as-world-model line: RAP (Hao et al., 2023) treats LLM reasoning as planning over an implicit state space; WKM / Agent Planning with World Knowledge Model (Qiao et al., arXiv 2405.14205) shows a small parametric world-knowledge model guiding a larger agent — including the finding that a *weak* world model can usefully guide a *strong* agent.
- **H-JEPA** (AMI Labs/NYU, Oct 2026, LeCun co-author): hierarchical world model with separate planning and control layers — the direction the field is moving.

**Limitations (the honest part):**
- **Rollout error compounds.** Every predicted step adds error; by step 3–4 the simulation is often fiction. This kills multi-step planning reliability — the exact thing JARVIS needs.
- **The usage gap (ACL 2026):** a study titled *"Current Agents Fail to Leverage World Model as Tool for Foresight"* found agents given access to generative world models used simulation **<1% of the time**, misused predicted rollouts **~15% of the time**, and in some tests simulation access *reduced* performance by up to 5%. Having a world model ≠ using it well.
- **Cost.** Pixel-based world models (diffusion) need GPU that the 2060 doesn't have to spare alongside the brain. Text/tree-based prediction is cheap but much less informative.

**Reproducibility:** Mixed. WM-R1 and SimuRA are published with code; the "agents fail to use world models" result is a single ACL 2026 study — treat as suggestive, not settled. H-JEPA is brand new (Oct 2026) — unevaluated by third parties.

**Practical relevance to JARVIS: [HC] — a full desktop world model is fantasy for v2.** The practical transfers are narrower and cheaper:
1. **Mental dry-run for high-risk actions only.** Before a destructive/irreversible action, the brain generates 2–3 predicted outcomes in text ("if I run this, X breaks downstream") — a 30-second LLM simulation, not a learned dynamics model. This is the *idea* of a world model without the infrastructure.
2. **Verify-after-acting** (already in `learn-multimodal.md`): tree → act → re-read tree → confirm. The environment *is* the simulator; acting is cheap, simulation is unreliable. For a desktop agent, the real world is a better world model than any learned one.
3. **Weak-guides-strong:** a tiny local model (BitNet tier) can pre-screen plans ("does this plan contain an irreversible step?") before the big brain commits. Cheap, deterministic-ish, matches WKM's finding.

**Confidence:** [HC] that world-model-as-training-env is real and growing; [HC] that a live desktop world model on 6GB VRAM is infeasible for v2; [MC] on the ACL usage-gap study (single study).

**Unknowns:** whether text/tree-based GUI simulation (no pixels) is reliable enough for 2–3 step lookahead; whether WM-R1-style training transfers to real Windows apps.

---

## 2. Process Supervision vs Outcome Supervision

**Central claim:** Rewarding *intermediate reasoning steps* (process supervision) produces more reliable reasoners than rewarding only the final answer (outcome supervision) — because outcome supervision can't distinguish "right answer, wrong reasoning" from "right answer, right reasoning."

**Mechanism:** A **Process Reward Model (PRM)** scores each step of a chain-of-thought; an **Outcome Reward Model (ORM)** scores only the final result. At inference time the PRM selects among candidate solutions (best-of-N) or guides search (MCTS/beam). PRMs catch the failure mode where a wrong chain stumbles into the right answer (false positives).

**Supporting evidence:**
- **"Let's Verify Step by Step"** (Lightman et al., OpenAI, arXiv 2305.20050, 2023): on a 500-problem MATH subset, process supervision reached **78.2%** vs **72.4%** outcome supervision vs 69.6% majority voting. Released **PRM800K** — 800,000 step-level human labels, which became foundational for reasoning-model training.
- **Math-Shepherd** (Wang et al., 2023): automated step-level labels *without* humans (using answer correctness to label steps) — cheaper process supervision that still localizes reasoning failures inside the trace.
- **Milestone-based agent evaluation** (AgentBoard's "Progress Rate", TheAgentCompany's checkpoints): the same idea scaled to long-horizon agents — score subgoal completion, not just binary task success. Partial progress stays visible when final success is ~0% (WebArena: GPT-4 at 14.4% end-to-end vs 78.2% human — milestones show *where* it dies).

**Limitations — read the fine print:**
- The headline 78.2 vs 72.4 is **not apples-to-apples**: the ORM's training set was an order of magnitude larger (100 uniform samples/problem) than the PRM's; and the evaluation measures *reward-model selection* (best-of-N), not generator improvement. A controlled small-scale comparison (same data, oracle labels) still favors process supervision — so the effect is real, but smaller than the headline.
- **Label cost.** PRM800K took massive human annotation. Math-Shepherd's automated labels are cheaper but noisier. For JARVIS: nobody is hand-labeling 800k reasoning steps.
- **2025 counterweight — OpenAI's "Monitoring Reasoning Models for Misbehavior"** (Baker et al.): a *weaker* LLM monitoring a *stronger* model's chain-of-thought catches reward hacking at production scale — but with a warning: pressuring models on their CoT can drive **obfuscated reasoning** (the model learns to hide bad reasoning, not stop it). Process-level visibility is powerful *and* adversarially fragile.

**Reproducibility:** The core result (process > outcome on MATH) has been replicated and extended (Math-Shepherd, PRM-based search in reasoning models). The active-learning + PRM pipeline is standard practice in frontier labs. Reproducibility is **strong** for math; **thinner** for open-ended agentic tasks.

**Practical relevance to JARVIS: [HC] — don't train a PRM; steal the *evaluation* pattern.** The v2 transfers:
1. **Milestone-based task tracking:** long tasks get verifiable subgoals (already R-spec'd as task state machines); score progress per milestone, not just success/fail. This is process supervision applied to *evaluation*, which is free.
2. **Step-level deterministic verification:** after each tool call, a cheap check (schema validation, precondition/postcondition — Track 8/9) plays the PRM's role. No learned reward model needed; the environment provides ground truth.
3. **Small-model monitor:** a tiny local model watches the big brain's plan for reward-hacking-shaped patterns (e.g., "the plan achieves the letter of the request while violating its spirit"). OpenAI's 2025 result says a weaker monitor works — and ours runs on CPU for free.
4. **Warning honored:** never train the brain to produce "good-looking reasoning traces." Monitor, don't optimize, the CoT — or you get obfuscation.

**Confidence:** [HC] on the core finding and its limits; [HC] that the transferable part for JARVIS is milestone eval + deterministic step checks, not PRM training.

**Unknowns:** whether automated step-labels (Math-Shepherd style) work for *tool-use* trajectories as opposed to math; how to define "correct step" for open-ended desktop tasks.

---

## 3. Mechanistic Interpretability — Honest Assessment

**Central claim:** Reverse-engineer the neural network to understand *how* it computes what it computes — features, circuits, the actual mechanisms — rather than trusting what the model *says* it did.

**What it can actually do today:**
- **Sparse autoencoders (SAEs):** decompose messy activations into cleaner "features." Anthropic extracted ~15,000 feature directions from a single GPT-2 Small layer, ~70% cleanly matching one identifiable concept. Scaled to larger models (16M-latent SAEs on GPT-4-class).
- **Circuit tracing:** link features into "attribution graphs" showing the path from prompt to output — the beginning of explaining the model's actual reasoning path, not just labeling parts.
- **Targeted monitoring:** find specific known-bad mechanisms (deception circuits, etc.) when you know what to look for.

**What it can't do (the honest list):**
1. **Partial coverage.** Small circuits in detail; *nobody* has a full account of a frontier model. Understanding one circuit doesn't compose into understanding the system.
2. **Scale cost.** Toy-model methods get expensive and messy at frontier scale; SAE training on large models costs serious compute.
3. **The validation problem ("interpretability illusions").** Convincing-seeming interpretations turn out false. The field's own roadmap paper stresses this.
4. **Non-identifiability.** Multiple equally-valid mechanistic explanations can exist for the same behavior — there may be no single "true" circuit.
5. **Polysemanticity / superposition.** Single neurons encode multiple unrelated features; the linear-representation assumption underlying SAEs is shaky in nonlinear systems.
6. **The knowledge-action gap (2026):** a study (*"Interpretability without actionability,"* arXiv 2603.18353) found models encode near-perfect internal representations of hazards, yet **four mechanistic intervention methods corrected <25% of the resulting errors**. Knowing what's inside doesn't reliably translate to fixing behavior. A >50-point gap between internal knowledge and output behavior.

**Field status:** "Open Problems in Mechanistic Interpretability" (Sharkey et al., arXiv 2501.16496, Jan 2025, 29 authors across Anthropic/DeepMind/Apollo/EleutherAI, commissioned by Schmidt Sciences) is the canonical roadmap. Anthropic targets "reliably detect most AI model problems by 2027"; DeepMind has pivoted toward "pragmatic interpretability." Tension between aspiration and utility defines the field.

**Reproducibility:** Methods reproduce within labs; cross-model generalization is shaky (a circuit found in one model may look different in another). The 2026 status is: real science, real progress, not yet engineering.

**Practical relevance to JARVIS: [HC] — zero direct application for v2.** The honest verdict:
- Do **not** plan any interpretability-based safety mechanism. The knowledge-action gap paper is the empirical reason: even perfect internal visibility doesn't buy reliable control.
- What JARVIS needs (behavioral guarantees) comes from the *outside*: deterministic guardrails, capability permissions, audit logs, behavioral evals — the Conscio judgment layer, not SAEs.
- **One legitimate use:** if a future JARVIS brain is *fine-tuned* (Track 4), interpretability tools could audit the fine-tune for introduced bad behaviors — a research-grade activity, not a v2 component.

**Confidence:** [HC] on the limitations (the field's own roadmap concedes them); [MC] on the 2027 detection timeline (aspirational, single-lab claim).

**Unknowns:** whether "pragmatic interpretability" (DeepMind's pivot) yields anything deployable before 2028; whether meta-SAEs (showing SAE latents aren't atomic) invalidate current feature catalogs.

---

## 4. Demonstrated Limits of Self-Reflection

**Central claim:** "The LLM critiques its own output and improves" — widely used, much less effective than believed. The evidence says intrinsic self-correction (no external feedback) is at best marginal and often *harmful*.

**Supporting evidence:**
- **"Large Language Models Cannot Self-Correct Reasoning Yet"** (Huang et al., arXiv 2310.01798, 2023): across reasoning benchmarks, intrinsic self-correction via prompting frequently *degrades* performance. Gains reported in earlier self-refine papers traced to **oracle feedback** (external ground truth used as a stop criterion) and over-engineered prompts — not to genuine self-correction.
- **"When Hindsight is Not 20/20"** (arXiv 2404.09129): single-round self-reflection (no multi-round hints) gives *mixed* results — helps on TruthfulQA, *hurts* on HotpotQA. Effectiveness depends on the model's initial confidence and question difficulty.
- **"Self-Reflection Outcome is Sensitive to Prompt Construction"** (2026): prompts that explicitly hunt for errors produce **>10× the false-positive rate** (flagging correct answers as wrong) and the *lowest* accuracy. Conservative prompts miss real errors. Net effect: **at best ~+1%** over no reflection. The model cannot reliably distinguish its own correct from incorrect responses.
- **Bottleneck decomposition** (Tyen et al. 2024; multiple 2024–2026 studies): the failure is in **error detection**, not error correction. Given the error location, models often fix it fine. They just can't find it — same weights that made the error can't see it. (This is our "deterministic verification" principle, independently confirmed.)
- **Harness² (our own research):** refinement *without* a lesson library made things **worse** (73.4 → 63.2). Self-improvement without external ground truth is anti-improvement.

**When self-correction DOES work (the boundary conditions):**
1. **External feedback present.** Reflexion (Shinn et al., 2023) works because the reflection is grounded in *environmental* failure signals (unit tests, tool errors) — verbal reinforcement on real outcomes, not introspection.
2. **A different model critiques.** "A dedicated checker consistently catches what the generator misses — even when the checker is smaller." Separation of generation from evaluation (our existing principle) is the empirically validated form.
3. **Confidence-gated.** Reflection helps when initial confidence is low; hurts when the model was already right and talks itself out of it.

**Reproducibility:** Strong and convergent — 2023 through 2026, multiple labs, same conclusion. This is one of the most robust negative results in the agent literature.

**Practical relevance to JARVIS: [VC] — this validates our existing architecture and kills a tempting shortcut.**
- **Never** build "brain reviews its own plan" as a safety mechanism. It is security theater with a −1% to negative expected value.
- **Do** build: deterministic step verification (Track 8/9), a *separate small* critic model with independent signal (tool results, not the brain's own text), and the Conscio Skeptic — hostile audit from a different context.
- **Do** use reflection *with* external grounding: after a tool fails, reflect on the tool's error message (external signal) — that's Reflexion, and it works.
- The Harness² lesson stands as the v2 law: **no refinement loop without a lesson library and external ground truth.**

**Confidence:** [VC] — among the best-evidenced claims in this document.

**Unknowns:** whether *trained* self-correction (RL on correction behavior, not prompting) escapes the bottleneck — early 2025–2026 work is inconclusive.

---

## 5. Inference-Time Scaling — The Trade-Off Curve

**Central claim (Snell et al.):** For a fixed model, more inference compute (best-of-N, longer reasoning, verifier-guided search) improves results — but *how much* depends on problem difficulty. With adaptive per-question allocation, test-time compute can be **>4× more efficient** than naive best-of-N, and on easy/intermediate problems a small model + test-time compute can **outperform a 14× larger model** (FLOPs-matched).

**Mechanism:** Two levers: (1) **search against a verifier** (PRM-guided best-of-N / tree search); (2) **adaptive compute allocation** — spend more where the problem is harder. The key object is the **difficulty curve**: for each problem there is a crossover point where more test-time compute on the small model becomes *more expensive* than one query to a larger model. Below crossover: scale inference. Above: scale the model.

**Supporting evidence:**
- **Snell, Lee, Xu, Kumar, "Scaling LLM Test-Time Compute Optimally…"** (arXiv 2408.03314, Aug 2024): the 4× efficiency and 14×-larger-model results above, on MATH-style tasks.
- **s1** (Muennighoff et al., arXiv 2501.19393, 2025): simple test-time scaling via "budget forcing" (append "Wait" to extend reasoning) — cheap, effective, open.
- **AB-MCTS / TreeQuest** (Sakana AI, 2025): multiple frontier models cooperating via adaptive branching tree search beat every individual model on ARC-AGI-2 — inference-time cooperation as a scaling axis.
- The reasoning-model era (o1/o3-style) is the industrialization of this: test-time compute as the third scaling axis alongside parameters and data.

**Limitations:**
- **Difficulty estimation is itself hard.** Adaptive allocation needs to know how hard the question is *before* solving it — misjudgment wastes the budget or starves hard problems.
- **Latency.** Test-time compute adds variable latency proportional to difficulty. Fine for background tasks; unacceptable for real-time voice turn-taking (JARVIS's core loop).
- **Verifier dependence.** Best-of-N is only as good as the selector. A weak verifier + large N = confidently selecting fluent garbage.
- **Diminishing returns.** Accuracy(c) ≈ a − b·c^(−α), α ≈ 0.5–0.8: 10× compute buys roughly 1–2 points. The curve flattens.

**Reproducibility:** The Snell results reproduce on math/reasoning benchmarks; the exact crossover points are task- and model-specific (no universal constants). s1's budget-forcing is trivially reproducible.

**Practical relevance to JARVIS: [HC] — this is the theoretical backbone of our three-tier 2060 architecture.**
- **Tier routing IS the difficulty curve:** BitNet-CPU (instant, trivial queries) → 4B (fast, medium) → 7B (daily driver) → cloud (frontier, hard). Each tier is a point on Snell's curve.
- **Where to spend test-time compute:** planning a multi-step desktop task (offline-ish, high stakes) → best-of-N plans + verifier = worth it. Voice turn-taking (200ms budget) → never; answer once, fast.
- **The v2 rule:** adaptive compute budget per *task tier*, not per query. Trivial: 1 sample. Standard: 1 sample + deterministic checks. High-stakes (irreversible actions): N samples + small-model judge + human gate. This is Snell's "compute-optimal" strategy translated to a personal agent.
- **Don't** do best-of-N on the chat brain by default — latency kills the voice experience, and the verifier for open conversation doesn't exist.

**Confidence:** [HC] on the trade-off shape and the tier-mapping; [MC] on exact crossover points (task-specific, must be measured on Owais's workloads).

**Unknowns:** measured difficulty distribution of Owais's actual usage (needed to set tier thresholds); whether a cheap difficulty classifier (tiny model, first-100-tokens heuristic) routes accurately.

---

## 6. Temporal Knowledge Graphs + Entity Resolution (Track 3 gap)

**Central claim:** Agent memory should be a *temporal* knowledge graph: facts as edges with validity windows (when true / when superseded), not overwritten rows. Identity ("is 'Amir' in this conversation the same person as 'Amir' last month?") is resolved explicitly — entity resolution — instead of hoped-for via embeddings.

**Mechanism (Graphiti/Zep reference design):** ingest each episode (message, event) → extract entities/relationships → reconcile against the existing graph → on contradiction, *mark the old edge invalid at timestamp T* rather than deleting it (bi-temporal model: t_valid = when the fact was true in the world; t_invalid = when it stopped). Retrieval = graph traversal + semantic + keyword hybrid, with temporal filtering ("what was true at time X?").

**Supporting evidence:**
- **"Zep: A Temporal Knowledge Graph Architecture for Agent Memory"** (arXiv 2501.13956, Jan 2025). Reference implementation **Graphiti** (MIT, ~19.4k stars): sub-second retrieval, incremental updates without full recomputation, custom entity types.
- Vendor benchmarks (treat as vendor-reported, not independent): Zep claims 94.8% DMR / 84.5% LongMemEval accuracy at ~28ms/query; a 2026 comparison reports Hindsight 94.6% vs Mem0 49.0% vs Zep 63.8% on LongMemEval — wide spread suggests benchmark/methodology sensitivity; do not treat as settled.
- **Counter-evidence (important):** Letta's own LoCoMo benchmarking found **simple filesystem grep (74.0%) beating Mem0's graph memory (68.5%)** on static recall. Infrastructure isn't the bottleneck — retrieval discipline is. Don't over-engineer.

**Limitations:** Graphiti needs Neo4j (a second daemon to supervise — rejected for v2's local-first constraint); entity extraction quality bounds everything (garbage entities → garbage graph); temporal reasoning helps only when queries are actually temporal (most daily queries aren't).

**Practical relevance to JARVIS: [HC] — steal the *pattern*, not the stack.**
1. **Bi-temporal memory rows in SQLite:** every memory gets `valid_from`, `valid_to` (NULL = current), `superseded_by`. Never UPDATE a memory — INSERT the new version, close the old window. This kills an entire class of "JARVIS remembers something I changed" bugs and gives point-in-time recall for free.
2. **Explicit entity resolution:** a deterministic entity table (canonical IDs for people/places/projects) + LLM-assisted linking at write time with confidence scores. "Amir" resolves once, at write; reads never guess.
3. **Hybrid retrieval** (already decided in `learn-databases.md`): graph traversal is the *third* leg alongside BM25 + vectors — add it only when relationship queries ("what did we decide about X last month?") prove frequent.
4. **The LoCoMo lesson honored:** grep-able plain-text memory (cog-style hot/warm/glacier) stays the default; the graph is an index, not the store.

**Confidence:** [HC] on the bi-temporal pattern's value; [MC] on benchmark claims (vendor-sourced); [HC] that Neo4j is wrong for v2.

**Unknowns:** measured frequency of temporal queries in real usage (determines whether the graph leg earns its keep); entity-extraction accuracy on Hinglish.

---

## 7. Human Preference Evaluation Methodology (Track 10 gap)

*Canonical-home note (Cycle 18): the statistical machinery here (Cohen's κ, Bradley-Terry, n=1 rater discipline) is canonically owned by `learn-evaluation-science.md` §§3.1–3.3 — this section's JARVIS-specific arena design (below) is the applied lens, not the reference. Edit stats there, design here.*

**Central claim:** For open-ended assistant quality, pairwise human preference (A vs B, blind) aggregated properly is the most reliable signal we have — but only if you report *intervals*, control for *style*, and remember that human agreement itself is variable.

**Mechanism (Chatbot Arena / LMArena reference design):**
- Anonymous pairwise battles → **Bradley-Terry model** fit (P(i beats j) = logistic(s_i − s_j)) → Elo-like scores.
- **Uncertainty quantification:** bootstrap confidence intervals; overlapping intervals = no meaningful difference ("small gaps at the top are near coin flips").
- **Style control:** length/format verbosity inflates scores — the style-controlled leaderboard exists because humans reward fluent long answers.
- **Anomaly detection + adaptive sampling** to keep the vote pool clean and efficient.
- Reference: Chiang et al., "Chatbot Arena: An Open Platform for Evaluating LLMs by Human Preference" (arXiv 2403.04132, 2024).

**Limitations — the critics are right about parts:**
- **"The Leaderboard Illusion"** (arXiv 2504.20879): public scores conflate prompt mix, serving parameters, and submission strategies (best-of-many launches inflate scores). A score is meaningless without its interval, rank range, and prompt mix.
- **Inter-annotator agreement is variable:** Smith et al., "Human Evaluation of Conversations is an Open Problem" — different crowdworker protocols give different agreement rates and different sensitivity. Single-model per-turn rating ≠ pairwise per-dialog assessment.
- **Non-transitivity:** ICML 2025 work shows LLM judges exhibit non-transitive preferences (A>B, B>C, C>A); round-robin + Bradley-Terry mitigates it for human votes too.
- Crowd preferences (72–83% agreement with experts) are stable *in aggregate* but noisy per-vote.

**Practical relevance to JARVIS: [HC] — this is the v2 evaluation harness design.**
1. **Private arena for brain configs:** when choosing between model/tier/prompt candidates, run blind A/B on Owais's *real* prompts (not generic benchmarks), fit Bradley-Terry, report intervals. This is how tier thresholds and prompt changes get decided — by measurement, not vibes.
2. **Owais is the rater pool (n=1):** adapt the method — pairwise comparisons of two candidate responses, ties allowed, prompt mix = his actual usage distribution. Small sample → wide intervals → only ship *clear* wins. The methodology's honesty about uncertainty is the point.
3. **Style control matters for JARVIS:** the butler persona must not win evaluations just by being verbose. Score task completion separately from style.
4. **Calibrate any LLM judge** against a few hundred of Owais's votes before trusting it — never deploy an uncalibrated judge.
5. **Inter-rater note:** with n=1, track *intra*-rater consistency instead (does Owais agree with his past self? re-show old pairs monthly).

**Confidence:** [HC] on the BT + intervals + style-control recipe (well-established); [MC] on exact agreement figures (protocol-dependent).

**Unknowns:** how many pairwise votes are needed for stable BT estimates on a single user's prompt distribution (likely 100–300; unmeasured).

---

## Cross-Cutting Synthesis — What Transfers to v2 Design

| Frontier finding | v2 design decision |
|---|---|
| World models: usage gap + rollout error | No learned desktop simulator. **Mental dry-run for high-risk actions only** + verify-after-acting against the real UI tree. |
| Process supervision | No PRM training. **Milestone-based eval** (score subgoal completion) + deterministic step checks as the "process reward." |
| Interpretability: knowledge-action gap | **Zero interpretability-based safety.** Behavioral guardrails (permissions, audit, Conscio Skeptic) instead. |
| Self-reflection limits [VC] | **Ban same-model self-review** as a safety mechanism. Critic must be a *different* model/context with *independent* signal (tool outputs). Reflection only on external failure signals. |
| Snell trade-off curve | **Tier routing = the difficulty curve.** Test-time compute budget by task tier: trivial 1 sample, standard 1+checks, high-stakes N+juries+human gate. Never best-of-N on the voice loop. |
| Temporal KG | **Bi-temporal SQLite memory** (valid_from/valid_to, supersede-don't-delete) + explicit entity resolution at write time. Graph traversal as optional third retrieval leg. |
| Human preference eval | **Private Bradley-Terry arena** on Owais's real prompts for every brain/prompt/tier decision. Intervals, not points. Style scored separately. |

**The meta-pattern:** every frontier result in this document points the same direction — *external ground truth beats internal introspection*. World models lose to the real environment; self-critique loses to independent critics; interpretability loses to behavioral guardrails; learned memory hierarchies lose (sometimes) to grep. v2's architecture should be biased accordingly: verify against the world, not against the model's opinion of the world.

## Remaining Unknowns (ranked)

1. Measured difficulty distribution of Owais's real usage — needed to set tier thresholds and compute budgets. (Blocks §5 application.)
2. Whether text/tree-based GUI lookahead is reliable for 2–3 steps. (Bounds §1's dry-run.)
3. Intra-rater consistency protocol for n=1 evaluation. (§7)
4. Trained (RL) self-correction — does it escape the prompting bottleneck? (Open research question; not blocking.)
5. Entity-extraction accuracy on Hinglish. (§6)

## Key References (all verified, none fabricated)

- Lightman et al., "Let's Verify Step by Step," arXiv 2305.20050 (2023)
- Wang et al., "Math-Shepherd," arXiv 2309.12284 (2023)
- Baker et al., "Monitoring Reasoning Models for Misbehavior…," OpenAI (2025)
- Sharkey et al., "Open Problems in Mechanistic Interpretability," arXiv 2501.16496 (2025)
- "Interpretability without actionability," arXiv 2603.18353 (2026)
- Huang et al., "Large Language Models Cannot Self-Correct Reasoning Yet," arXiv 2310.01798 (2023)
- Pan et al., "Automatically Correcting Large Language Models" (survey), arXiv 2308.06808 (2023)
- Snell et al., "Scaling LLM Test-Time Compute Optimally…," arXiv 2408.03314 (2024)
- Muennighoff et al., "s1: Simple test-time scaling," arXiv 2501.19393 (2025)
- Zep, "A Temporal Knowledge Graph Architecture for Agent Memory," arXiv 2501.13956 (2025) → Graphiti (MIT)
- Chiang et al., "Chatbot Arena…," arXiv 2403.04132 (2024)
- "The Leaderboard Illusion," arXiv 2504.20879 (2025)
- WM-R1, arXiv 2608.27508 (2026); ITP, arXiv 2601.08955 (2026); WKM, arXiv 2405.14205 (2024); Hao et al., RAP (2023)
- ACL 2026: "Current Agents Fail to Leverage World Model as Tool for Foresight" (single study — suggestive)
