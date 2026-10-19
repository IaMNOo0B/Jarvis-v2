# The JARVIS Master Planner — Plan Mode as a Designed System

*LEARNING ONLY — no project files touched, no installs, no code executed. Date: 2026-10-19.*

**Research question:** What is the complete, executable specification for JARVIS's planning system — adapted from the MASTER PLANNER prompt, with our own organs grafted in?

## Plain-words summary

JARVIS plans in three modes, chosen by a router: **FAST** (no plan, act now), **PLAN** (write the 11-section contract, get it approved, then execute), **DEEP** (plan + independent verification before execution). The plan is a *contract*, not a suggestion — any step whose outcome doesn't match the contract voids it, and work stops. Plans are never audited by their own author. Every plan states what would prove it wrong and when it gives up. This file is the full spec: the template, the behavioral rules, the mandatory inputs, the router, the stopping rule, the audit protocol, and the termination conditions.

**Phase 1 (own sources, read first):** `learn-frontier-reasoning.md` (8 strategies, the routing rule), `learn-multi-scale.md` (L2 workflows as contracts, β termination, the non-override guarantee), `learn-adaptive-computation-math.md` (EU(c)=VoI−Cost, the stopping rule, Layer 0/1/2), `learn-dynamic-modules.md` (fixed vs templates vs dynamic; the §5 two-pipeline router), `learn-asking-economics.md` (ask iff gain > cost; narration as cheap ask), `learn-v2-master-map.md` (plan mode in approval UX, the 12-box map), `learn-proactivity-spec.md` (routines as user-authored contracts, deviation voids).

**Phase 2 (outside sources, searched):** ReAct vs Plan-and-Execute evidence (arXiv 2509.08646 — P-t-E as prompt-injection defense; practitioner 85% vs 92% accuracy figures; LangChain plan-and-execute cost/speed claims); planner-centric frameworks (Qwen3-8B RL + DAG planner: 59.8% vs GPT-4 ReAct 48.2% on StableToolBench, 2.29 avg steps); plan verification literature (arXiv 2509.02761 — critic-refine convergence 96.5% by iteration 3; arXiv 2609.31937 — verification as architectural layer, ReAct myopic-trap rates >50%, post-error recovery ~5%); classical planning verdict (PlanBench: GPT-4 CoT <12% vs LLM+P >95%; LLM-as-modeler beats LLM-as-planner — Zuo et al. 2024; Kambhampati/Valmeekam; SayCan grounding pattern; 2025 practitioner stack: reasoning model + search + verifiers + classical planners for formal sub-problems).

---

## 1. The plan router — when to plan at all

Not every task deserves a plan. The router runs at turn start, on already-computed signals (tier, modality, turn type, belief variance) — never a model call. Three outputs:

| Mode | When | What happens | Cost |
|---|---|---|---|
| **FAST** | Tier-1, single action, reversible, voice-latency-critical | No plan. Single-pass ReAct (strategy 1), act, narrate the uncertain part | 1× |
| **PLAN** | Multi-step (≥3 tool calls), tier-2, chat path, novel-but-structured task | The 11-section contract (§2) is written, approved once, then executed step-by-step with deviation checks | ~1.2× (one planning turn + execution) |
| **DEEP** | Tier-3 present in the plan, irreversible steps, high stakes, or user explicitly asked for a plan | PLAN + an independent verifier reviews the plan before execution (the Plan-Validate-Execute loop) | ~1.5–2× |

**Routing rules (deterministic, in order):**
1. Voice path → FAST always (the latency veto — planning is disqualified on the 2s budget). [VC — from dynamic-modules §4.5]
2. Tier-3 in the task → PLAN minimum, DEEP recommended. A tier-3 action is never executed inside a FAST turn. [VC — from R3, threat model]
3. ≥3 predicted tool calls OR novel task shape → PLAN. The "novel task shape" signal: no matching routine/skill-template in the library. [HC]
4. User said "plan first" / "show me the plan" → PLAN (explicit override). [VC]
5. Everything else → FAST.

**Safe default:** uncertain → PLAN (err upward — the same fail-safe direction as every safety term). A wrongly-planned simple task costs one extra turn; a wrongly-unplanned complex task costs a compounding-error chain. [HC — from adaptive-computation §3.2]

**What the router is NOT:** it does not choose *which* plan (that's the planner's job), and it does not design structures (full-dynamic composition stays research-only per dynamic-modules). It answers one binary-ish question: *is this worth a contract?*

---

## 2. The 11-section plan template (adopted, JARVIS-ified)

Every PLAN/DEEP turn produces a plan with these sections. The brain fills them; the contract (the hashed, approved part) is a subset — marked [C] below.

**P1. Objective and success criteria [C].** One sentence: what "done" looks like, stated as an observable world-state ("the report is saved at X with sections A–C"), never as effort ("I'll work on the report"). Plus the falsification of success: what evidence would show it *isn't* done.

**P2. Initial assessment and missing information.** What JARVIS knows, what it doesn't, and which unknowns block which steps. Each unknown tagged: [user-has-it → ask] / [tools-have-it → look up] / [nobody-has-it → proceed-with-assumption, flagged]. (From the underspecification taxonomy.)

**P3. Recommended strategy and alternatives [C].** The chosen approach + exactly two alternatives considered, each with one-line reason for rejection. (Two, not ten — the metareasoning bound: alternatives beyond the second rarely change the decision, and the planning turn has its own EU budget.)

**P4. Hierarchical task breakdown [C].** Steps, each with: the action, the tool, the expected outcome (observable), the tier, and the step's own termination condition. Max depth 2 (steps, sub-steps) — deeper hierarchies are a smell; split the plan.

**P5. Dependencies and execution sequence [C].** Which steps need which prior steps' outputs. Steps with no dependencies are marked PARALLEL-OK (the graph-agent lesson: parallelism is the main measured win of plan-first over ReAct).

**P6. Time, budget, resources, technical requirements.** Predicted tool calls (≤12 per the skill-spec turn budget), predicted model tier, wall-clock estimate, which 2060 resources (GPU resident? which models co-resident?). Checked against the multi-scale L2 budget: 20 steps/plan max.

**P7. Risk analysis and mitigation [C].** Per-step: what could go wrong, the mitigation, and the *pre-registered* response (retry-with-X / skip-if-non-critical / abort-and-escalate). Irreversible steps are listed explicitly with their tier-3 gates — the plan does not authorize them; it *schedules* their approval requests.

**P8. Edge cases and contingency plans.** The 2–3 most likely deviations and what happens in each. (Bounded: the plan is not a proof against all futures; the deviation rule in §3 handles the unlisted ones.)

**P9. Validation, testing, quality checkpoints [C].** After which steps does a deterministic check run (schema, assertion, test)? Which steps need the independent verifier (DEEP mode)? The "verify outcomes, not motion" rule: each checkpoint asserts a world-state, never "I clicked the button."

**P10. Progress tracking.** How the user watches: which events land in the session store per step, what the activity feed shows, the STOP behavior (halts at the next atomic boundary, checkpoints partials — from multi-scale §4).

**P11. Immediate next actions and the completion checklist.** The first step to execute on approval, and the final checklist re-stating P1's success criteria as checkable boxes.

**Contract = the [C] sections, hashed at approval.** The rest is working paper. (From approval-UX plan mode + multi-scale contract hashing.)

---

## 3. The plan contract — deviation voids, always

**The rule (structural, from proactivity §4 and multi-scale L2):** the approved [C] sections are hashed. Before each step executes, the L2 runner checks: does this step's *actual* action and its *actual* outcome match the contract? Any mismatch → **contract VOID → stop → ask the user**. Not "adapt silently." Stop.

**What counts as deviation:**
- A step's outcome ≠ its P4 expected outcome (file not where expected, tool returned an error class not in P7).
- A step the plan didn't list (the brain "improvising" step 6 of a 5-step plan).
- A tier escalation: a step the plan marked tier-2 turning out tier-3 (re-classified by the gate at execution — the gate's tier lookup is from the manifest, never the plan).
- New information that invalidates a P2 assumption the plan depended on.

**What does NOT count as deviation (and must not void):**
- A step succeeding via a slightly different tool-internal path with the same observable outcome.
- Latency/cost overruns within the P6 budget (those escalate via the budget rule, not the deviation rule).
- The user interrupting (that's preemption, multi-scale Rule 3 — a different mechanism).

**On void:** the workflow suspends, partial state checkpoints to the session store, and the user gets: what was done, what deviated, and two options — approve a revised plan, or abandon. The old plan's completed steps are evidence, not momentum. Re-arming is explicit, never automatic. [VC — from multi-scale §4]

**Plan approval authorizes the plan, not the tier-3 steps inside it.** Each tier-3 step still gates individually at execution time, with its own dialog, its own signed token, its own 10-minute expiry. The plan approval covers tier-1/2 only. (From approval-UX spec — the single most misunderstood point of plan mode; restated here because getting it wrong voids the safety case.) [VC]

---

## 4. Behavioral rules, not adjectives

The MASTER PLANNER prompt says "act as an elite master planner." Per our own persona research (Study 56: behavioral rules beat adjectives), that sentence is replaced by:

**DO:**
- Write every plan so a stranger could execute it without asking you a question. If a step needs your memory to understand, rewrite the step.
- State the observable outcome of every step before the step runs. "Click submit" is not an outcome; "the form shows 'saved'" is.
- List exactly two rejected alternatives with one-line reasons. (Forces the comparison without unbounded search.)
- Mark every assumption with who can resolve it (user / tools / nobody) and what happens if it's wrong.
- End every plan with its own kill criteria (§6) and its give-up conditions (§8).

**DON'T:**
- Don't plan what you can look up. If the information exists in a tool, the plan says "look up X," not "assume X, verify later."
- Don't write steps that are really wishes ("the API should return…"). Steps are actions with tools, not hopes with verbs.
- Don't bury tier-3 steps inside tier-2 language. If it can break something, it says tier-3 in P4 and P7.
- Don't produce a plan longer than the task warrants: ≤5 steps for PLAN, ≤10 for DEEP. Longer plans are two plans.
- Don't audit your own plan (§7). Ever.

**The planning turn has its own EU budget** (from adaptive-computation §1.4): planning stops when EU(next-planning-refinement) < 0. Concretely: one drafting pass + one self-consistency check of the *structure* (not the content — content is the auditor's job). A third planning pass needs a named reason ("P7 has no mitigation for step 4's failure mode").

---

## 5. Mandatory inputs — a plan that ignores these is rejected structurally

Before the planner runs, the harness assembles the plan context. Missing any item → the plan is not written; the turn degrades to FAST-with-narration and the missing input is logged:

1. **The 14 architecture requirements (R1–R14)** — as constraints, not suggestions. The plan's P7 must show no R-violation; the auditor's checklist (§7) re-checks.
2. **The threat model boundaries** — which of the 7 trust boundaries the plan crosses, and which box enforces each crossing.
3. **JARVIS-RULES.txt** — the current rules, loaded fresh. P3's strategy and P7's risk analysis must not contradict any P0/P1 rule. (Note: the planner *reads* the file; it cannot *edit* it — R-2 of the rules file.)
4. **Current resource state** — the 2060 budget: which models are resident, VRAM headroom, the L2 step budget remaining, the interruption budget remaining. A plan that needs 8GB VRAM when 5.2GB is resident is not a plan; it's fiction.
5. **The latest user.message** — from the session store, not from the turn's working memory. (Multi-scale Rule 2: fresh instruction beats the plan's memory of the instruction.)
6. **Belief-ledger variance on the task's key claims** — what the planner is uncertain about, so P2's unknowns are honest rather than decorative.

**Structural rejection:** the L2 runner (code, not the brain) checks inputs 1–4 before accepting a plan for execution. A plan with no resource check, or one that contradicts a P0 rule, is refused at the gate — the planner is informed, not obeyed. [DESIGN — extends the gate's remit from tool calls to plans]

---

## 6. Falsification per plan — what would prove it wrong

Every plan's P1 and P3 carry falsification criteria. Two levels:

**Plan-level (in P1):** "This plan is wrong if [observable]." Examples: "wrong if the API returns paginated results (the plan assumes single-page)"; "wrong if step 2 takes >60s (the plan assumes the cache is warm)."

**Strategy-level (in P3):** for each rejected alternative: "Alternative B would have been right if [observable]" — so that when the world surprises the plan, the *next* plan starts from the recorded alternative instead of from scratch. (This is the belief-ledger discipline applied to planning: rejected hypotheses are stored, not discarded.)

**Kill criteria (in P11):** the plan dies (not voids — *dies*, no re-plan offered automatically) when: the objective is shown impossible (P2's U5/U6c), the budget is exhausted with <50% of steps complete, or the user says stop. Death is logged with the reason; the corpse feeds the failure DB. [DESIGN]

---

## 7. Fresh-eyes audit — the planner never audits its own plan

**The rule:** the system that writes the plan never judges the plan. Two audit paths, chosen by mode:

**PLAN mode — deterministic checklist (code, ~0 cost):** the L2 runner verifies structurally before execution:
- [ ] All [C] sections present and non-empty.
- [ ] Every step has an observable outcome, a tier, and a termination condition.
- [ ] Every tier-3 step has a P7 mitigation and is NOT pre-authorized by the plan approval.
- [ ] P6's predicted tool calls ≤ 12, steps ≤ 20 (multi-scale L2 budget).
- [ ] No step's action contradicts JARVIS-RULES.txt P0/P1 (keyword + schema check, not semantic).
- [ ] Dependencies form a DAG (no cycles without an exit predicate).
- [ ] P9 has a checkpoint after every irreversible step.
Checklist failure → plan returned to planner with the failed items (one repair round, then escalate to user if still failing).

**DEEP mode — independent verifier (separate context):** a second pass receives ONLY (task + plan + rubric), never the planning transcript. It judges: logical coherence, missing dependencies, tier misclassification, P7 coverage of the obvious failures. Outside evidence: critic-refine loops converge 96.5% by iteration 3 (arXiv 2509.02761) — so cap at 2 critique rounds, then ship or escalate. The verifier's verdict is advisory to the *user*, not to the planner: on DEEP, the user sees the plan AND the verifier's notes before approving. [HC — the convergence numbers are measured; the "user sees both" is design]

**Why not the planner self-reviewing:** the discriminator problem (frontier-reasoning §1) — LLM self-judges don't reach the 90% needed for the judgment to help, and the verification-as-layer paper (arXiv 2609.31937) shows ReAct-style self-contained loops have myopic-trap rates above 50%. The audit must come from outside the generative loop — deterministic checklist or a context-separated verifier. [HC]

---

## 8. Termination — every plan's β

From multi-scale §3 (the options-framework β, checked by code): the plan carries explicit give-up conditions, and they are predicates over the session store, not judgments by the brain:

| β condition | Predicate | On fire |
|---|---|---|
| Plan complete | All P11 checklist boxes checkable-true | Close plan, log receipt |
| Step budget exhausted | steps_executed ≥ 20 | Void → ask (not auto-extend) |
| Consecutive failures | 3 failed steps in a row | Auto-pause → ask (proactivity §4) |
| Deviation | Any §3 deviation predicate true | Void → ask |
| User interrupt | Preemption signal | Suspend per multi-scale Rule 3 |
| Objective impossible | A P2 unknown resolves to U5/U6c | Plan dies → honest report |
| Stale plan | >30 min since approval with no step executed | Re-validate P2/P5 before resuming (world may have changed) |

**The stale-plan β is the one most planners forget** [HC — design claim]: a plan approved at 2pm and executed at 4pm is a different plan. The L2 runner re-checks P2's unknowns and P5's dependencies against current state before the first step; mismatch → re-plan the affected steps, don't execute blindly. (This is the dev.to PlanValidator pattern — "validate plan assumptions against current reality before execution" — adopted as a β condition rather than a separate component.)

---

## 9. Plan mode integration — where plans live

- **Plans are session-store events.** `plan.proposed` (the full 11 sections), `plan.approved` (the [C] hash + approver), `plan.step_completed` / `plan.step_failed` (each with the outcome vs expected), `plan.voided` (with the deviation), `plan.completed` / `plan.died`. The causal spine (`causal_parent`) links every tool call to its plan step to the plan approval to the user message. "Why did you do that?" is a log walk. [DESIGN — extends the session-store event taxonomy]
- **The activity feed shows the plan** as a collapsible checklist: completed steps checked, current step highlighted, voided plans marked (not hidden — the failure is visible). STOP is always visible during execution.
- **Routines are standing plans** (proactivity §4): a routine IS a plan contract with a schedule. Same deviation rule, same void behavior, same re-arm discipline. The planner and the routine author are the same system; the contract format is shared.
- **Narration during execution:** the uncertain part of each step is narrated as it runs (asking-economics §5), not the confident part. "Trying the cached credentials first — will fall back to login if they fail" beats "Executing step 3."

---

## 10. What the outside literature changed in this spec

| Finding | Source | What it changed |
|---|---|---|
| P-t-E is a prompt-injection defense (control flow locked before execution) | arXiv 2509.08646 | Strengthened §3's deviation rule: the security value of plan-first is architectural, not just organizational. The plan approval + deviation-void is now explicitly a security boundary, not a UX convenience. |
| Automatic Planning + User-Involved Execution for critical systems | arXiv 2509.08646 (He et al. 2025) | Confirmed the plan-approves-tiers-1/2 / each-tier-3-gates-individually split in §3. |
| Plan-Validate-Execute evolution | arXiv 2509.08646 §7.3.1 | The DEEP mode's independent verifier (§7) — named as the P-V-E loop. |
| Planner-centric beats ReAct: 59.8% vs 48.2%, 2.29 steps | Beyond-ReAct paper (themoonlight review) | Evidence for the router's PLAN bias on multi-step tasks (§1, rule 3): planning isn't just tidier, it's measured-better on structured work. |
| Critic-refine converges 96.5% by iteration 3 | arXiv 2509.02761 | The 2-round cap on the DEEP verifier (§7). More rounds are theater. |
| ReAct myopic traps >50%, post-error recovery ~5% | arXiv 2609.31937 | The structural case for §7's outside-the-loop audit: self-contained planning loops don't just underperform, they trap. |
| LLM+P >95% vs LLM-direct <12% (PlanBench) | Liu et al. 2023; compendium | The surviving classical-planning pattern for JARVIS: LLM-as-modeler (writes the P4/P5 structure), deterministic machinery as validator (§7 checklist) — never LLM-as-solver for constraint problems. Kept narrow: schemas + checklists, not full PDDL (HTN-overkill verdict stands). |
| SayCan: score = P_LLM × P_affordance | Ahn et al. 2022 | P4 step feasibility: each step's "expected outcome" must pass an affordance check (can this tool, in this state, plausibly produce this outcome?) at plan time — a cheap static version of SayCan's grounding, run by the checklist. |
| PlanValidator: validate against live state before execution | dev.to (tamizuddin) | The stale-plan β in §8 — adopted as a termination condition, not a new component. |

**What did NOT survive from the outside literature:**
- Full PDDL/HTN planning for the agent loop — overkill stands (dynamic-modules §6, frontier-reasoning unknowns). Classical machinery appears only as the §7 checklist and schema validation.
- Unbounded replanning loops — capped by the β table and the 2-round verifier limit. "Replan until it works" is how you burn the afternoon (multi-scale F2).
- The planner auditing itself — killed by the discriminator evidence, twice over.

---

## 11. Confidence tags

- **[VC]:** the router's safe-default-upward; tier-3 never inside FAST; plan approval ≠ tier-3 authorization (each gates individually); deviation-voids-contract; the planner-never-audits rule; the structural rejection of R-violating plans; only-L1-emits-actions (inherited).
- **[HC]:** the 11-section template as specified (adopted structure, JARVIS-ified content); the [C]-subset contract design; the deterministic checklist catching structural defects; the 2-round verifier cap; the stale-plan β; SayCan-lite affordance checks at plan time; the planning-turn EU budget.
- **[MC]:** the router's exact thresholds (≥3 tool calls → PLAN; ≤5/≤10 step caps); the "two alternatives" bound; the 30-minute staleness threshold; that the checklist catches the defects that actually matter (unmeasured until the first 100 plans).
- **[SP]:** whether DEEP's verifier notes actually improve user approval quality (vs just slowing it); whether the falsification sections get used or rot.
- **[UK]:** real-world deviation rates (how often plans void — the number that tunes everything); planner calibration on P6 estimates; whether users read P3's rejected alternatives.

## 12. Unknowns (ranked)

1. **Deviation rate in production** — the single number that determines whether plan mode is a scalpel or a straitjacket. If >30% of plans void, the planner is miscalibrated, not the world.
2. **The checklist's catch rate** — what fraction of bad plans does the deterministic checklist stop? Needs the first 100 plans logged with outcomes.
3. **P6 estimation accuracy** — are the predicted tool calls/times within 2× of reality? Uncalibrated estimates make the budget β fire spuriously.
4. **User behavior on void** — do users re-approve revised plans, or does a voided plan usually mean abandonment? Determines whether void→ask is the right response or whether it should void→propose-revision-first.
5. **Interaction with the asking controller** — the plan's P2 unknowns and the asking-economics pricing overlap. Currently: P2 *declares* unknowns, the asking controller *prices* the questions about them. The handoff protocol between the two is designed, not yet specified in detail.

## Honest scope

- **Researched:** 7 own-source files re-read (relevant sections); 3 web searches (ReAct-vs-P&E evidence, plan verification literature, classical-planning verdict); the MASTER PLANNER prompt itself, analyzed.
- **Validated:** the 11-section structure is adopted from the prompt (not invented); every grafted organ traces to a file in §traceability; outside numbers are cited with sources and treated as single-source where they are.
- **Saved:** this file.
- **Tested/Measured:** nothing — design document.
- **Incomplete:** the asking-controller handoff (§12.5); the exact checklist implementation; DEEP verifier rubric text.
- **Blocked:** production data for deviation rates, checklist catch rates, P6 calibration (all need the build + real usage).

**Outcome label (Domain XI):** *new combination of known techniques* — the 11-section template is adopted, the contract/void/audit/β machinery is assembled from our own specs, the outside evidence is used for calibration not invention. Nothing here claims to be a novel planning algorithm.

---

## Traceability

| Choice | Source |
|---|---|
| 11-section template | MASTER PLANNER prompt (adopted); content JARVIS-ified |
| Behavioral rules over adjectives | Study 56 (persona research): rules > adjectives |
| Router: FAST/PLAN/DEEP | learn-dynamic-modules.md §5 (two-pipeline router, generalized); learn-adaptive-computation-math.md Layer 0 |
| Safe default upward | learn-adaptive-computation-math.md §3.2 (fail-safe direction) |
| Contract = hashed [C] subset; deviation voids | learn-proactivity-spec.md §4 (routines as contracts); learn-multi-scale.md §3 (β), §2 (Rule 1) |
| Plan approval ≠ tier-3 authorization | learn-approval-ux-spec.md (plan mode); learn-threat-model.md (AND-gates) |
| Planning-turn EU budget | learn-adaptive-computation-math.md §1.4 (metalevel overhead discipline) |
| Mandatory inputs incl. JARVIS-RULES.txt | learn-v2-master-map.md §1 (owns/never-touches); JARVIS-RULES.txt R-1/R-2 |
| Falsification per plan | OMEGA ∞+1 Domain XI (novelty verification); learn-adaptive-computation-math.md §5 F7 (pre-registration) |
| Fresh-eyes audit; planner never self-audits | learn-frontier-reasoning.md §1 (discriminator problem); arXiv 2609.31937 (myopic traps) |
| 2-round verifier cap | arXiv 2509.02761 (96.5% convergence by iteration 3) |
| Stale-plan β; validate-before-execute | dev.to PlanValidator pattern; learn-multi-scale.md §3 |
| SayCan-lite affordance check | Ahn et al. 2022 (SayCan) |
| P-t-E as injection defense | arXiv 2509.08646 |
| LLM-as-modeler, not solver | Zuo et al. 2024; Kambhampati/Valmeekam; PlanBench gap |
| Termination β table | learn-multi-scale.md §3 (options-framework β) |

*End of Master Planner spec. Status: design complete as a learning document; unimplemented by intent. The next step is not more planning theory — it's the first 100 measured plans.*
