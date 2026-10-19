# Deterministic Plan Validation (STRIPS-lite) — Phase ∞, Cycle 8

*Research cycle 8, written 2026-10-19. LEARNING ONLY — no code, no installs, no model calls. Contains design pseudocode as specification; nothing here was executed.*
*Confidence tags: [VC] >95% · [HC] 80–95% · [MC] 60–80% · [SP] 40–60% · [UK] unknown. **DESIGN** = derived from research, unmeasured.*

**Research question:** Can deterministic plan validation replace LLM judgment of plan quality?

**Answer in one paragraph:** Yes — for the *formal* half of plan quality. A STRIPS-lite contract validator decides plan **validity** (preconditions satisfied, permissions respected, irreversible steps approved, goal achieved) in time linear in plan length, where planning itself is PSPACE-complete. This covers exactly the fault classes the cycle-7 study hypothesizes an LLM plan-judge fails to discriminate (precondition violations, wrong order, policy violations: rung 4, ~55–65% hypothesized). It does **not** replace *semantic* judgment — whether the plan is the right plan for the user's intent — which stays in the escalate/human column. The architecture inverts the SELF-[IN]CORRECT finding: the LLM does what it can do (generate candidates), the machine does what it does at ~100% (discriminate validity). This cycle is the "disposes" half of the neuro-symbolic loop from learn-frontier-reasoning.md: LLM proposes → validator disposes → machine-generated counterexample feeds back → replan.

**§19 protocol followed:** audit (§1) → question (§2) → research (§3) → compare (§4) → derive (§5: the design) → validate (§6: falsifiers) → integrate (§7: ADR) → record (§8) → reassess (§9).

---

## 1. Audit — what prior cycles established (referenced, not re-researched)

| Prior file | Contribution to this cycle | Status |
|---|---|---|
| `learn-self-verification-calibration.md` (cycle 7) | The squeeze argument: no rung deploys an LLM self-judge; rung 4 (plan-quality judgment) hypothesized at 55–65%, far below the 90% discriminator threshold. Null architecture §7 names a "STRIPS-lite action model" validator but does not design it. Rung-4 golden items (E4.1–E4.4) already use declared preconditions/effects as ground truth. | Accepted as the **problem statement**; this cycle supplies the missing design. |
| `learn-formal-methods.md` | Design by Contract (deal/beartype) on 5–10 critical functions; Hypothesis stateful testing; "Z3 proves the design, Hypothesis tests the code, runtime guards enforce." | Accepted; contracts here are the **plan-level** analogue of deal's function-level contracts. |
| `learn-frontier-reasoning.md` | Neuro-symbolic loop: LLM proposes → symbolic verifier disposes → counterexample feeds back. "The verifier is the strategy." ≥90% discriminator required for tree search. | Accepted as the **loop architecture**; this cycle designs the verifier. |
| `learn-advanced-cs.md` | Durable queue, idempotency keys, event sourcing lite. | Accepted; the validator's dispatch-time re-check and compensation fields plug into this. |
| `learn-underspecification.md` | Missing preconditions as a detection signal (missing arguments). | Accepted; precondition checking is the mechanization of that signal. |

**Genuinely new in this cycle:** the STRIPS-vs-validation complexity separation; the LLM-Modulo empirical precedent; the tool-contract schema (beyond JSON Schema); the validator algorithm with complexity bound; the worked example; the contract-completeness / TOCTOU / frame-problem breakage analysis with mitigations; the Saga-pattern justification for the approval-event check.

---

## 2. The question, sharpened

Cycle 7's null architecture says rung 4 is replaced by "a symbolic plan validator [that] runs the chain before execution." Three sub-questions decide whether that sentence is load-bearing or hand-waving:

1. **Is plan validation actually cheaper than planning?** (If not, we've smuggled the hard problem back in.)
2. **What must each tool declare for validation to be possible?** (The contract schema — and why JSON Schema / MCP `inputSchema` is insufficient.)
3. **Where does the deterministic guarantee break, and what catches the breakage?** (Contract-completeness, TOCTOU, frame problem.)

---

## 3. Research — the genuinely new evidence

### 3.1 STRIPS/PDDL in one page — and the validation/planning split

**STRIPS** (Fikes & Nilsson 1971): a state is a set of true propositions (closed-world assumption — anything not listed is false). An **action** is a triple:

- **preconditions** `pre(a)`: propositions that must be true for the action to apply.
- **add effects** `add(a)`: propositions made true.
- **delete effects** `del(a)`: propositions made false.

Applying action `a` in state `s` (when `pre(a) ⊆ s`): `s' = (s \ del(a)) ∪ add(a)`.

A **planner** must *find* a sequence from initial state to a goal — PlanSAT is **PSPACE-complete** (Bylander 1994); even bounded-length PlanSAT is NP-complete [VC — standard results, e.g. Nebel & Mattmüller lecture slides, https://ai.dmi.unibas.ch/_files/teaching/hs25/po/slides/po-b07.pdf].

A **validator** is given the sequence and only *simulates* it: walk the plan, check each action's preconditions against the running state, apply effects, and at the end check the goal is a subset of the final state. This is **polynomial — linear in plan length** for propositional STRIPS [HC]. The canonical implementation is **VAL** (Howey, Long & Fox 2004; http://strathprints.strath.ac.uk/2719/1/strathprints002719.pdf): "validation of the plan can proceed by simulation of its execution, as is the case for PDDL plans" — tractable for domains without continuous effects (Fox & Long, JAIR 2003; https://www.cs.cmu.edu/afs/cs/project/jair/pub/volume20/fox03a-html/node16.html).

**The split that matters for JARVIS:** we never ask the machine to *plan* (PSPACE). The LLM proposes a plan (its generative strength); the machine *validates* the proposal (its discriminative strength). This is the one place in the whole self-verification literature where the DG-DIFF asymmetry works *for* us: SELF-[IN]CORRECT (cycle 7 §3.1) showed LLM discrimination ≈ LLM generation, so asking the LLM to judge is pointless — but asking a *machine* to judge a *formal* property is exactly where machines beat LLMs 100%-to-60%.

### 3.2 LLM-Modulo — the empirical precedent for propose→dispose→replan

Kambhampati et al., "LLMs Can't Plan, But Can Help Planning in LLM-Modulo Frameworks" (arXiv:2402.01817, ICML 2024 spotlight): LLMs generate plan candidates; **external verifiers** (not the LLM) check them; failures are backprompted to the LLM as critiques; loop until valid. Result: **12% of GPT-4 plans executable without verification → 82% with the LLM-Modulo feedback loop** [HC — peer-reviewed; figures via https://theagenttimes.com/articles/landmark-icml-paper-shows-llms-fail-at-planning-alone-but-th-62033522].

Two design details transfer directly:
1. **The verifier must be external to the generator.** LLM-Modulo's gains come from critics the LLM cannot argue with — the same independence-of-signal argument as cycle 7's H-INDEP.
2. **The feedback is a machine-generated counterexample, not a vibe.** Recent tooling makes this concrete: the 2025 **Planning Copilot** exposes VAL as an MCP tool — on validation failure the LLM receives *the reason for failure and a possible fix suggestion*, and a separate simulate-trace tool records the intermediate state after each action (https://arxiv.org/html/2509.12987v1) [HC]. That is precisely our §5.2's `first_fault` + `unmet` output format, already field-tested as an MCP pattern.

### 3.3 The contract-completeness literature — models are always incomplete

The objection "but the contracts will be incomplete" is forty years old and has a literature:
- **Model-lite planning** (Kambhampati 2007): complete models can't be guaranteed; systems must work with reasonable-but-incomplete models and still produce high-success-chance plans.
- **Robust plans under incomplete domain models** (Nguyen, Kambhampati & Do, 2011): annotate *known incompleteness* explicitly and compile to conformant probabilistic planning — i.e., **mark what you don't know** rather than pretending the model is complete (https://liner.com/review/synthesizing-robust-plans-under-incomplete-domain-models) [HC].
- **Action-model learning** (ARMS, Yang et al. 2007; RIM; FAMA): learn/refine STRIPS preconditions and effects from execution traces via constraint solving — contracts need not be purely hand-authored; they can be **refined offline from observed traces** [HC].

Transfer: every contract field gets a **completeness annotation** (`known_complete` / `known_incomplete`), incomplete contracts lower the ledger's confidence and trigger verify-after-acting more aggressively, and contract refinement happens **offline from traces** — never by the live LLM editing its own contracts (that would be the judge judging the judge).

### 3.4 The Saga pattern — why irreversible actions need approval *before*, not compensation *after*

Garcia-Molina & Salem (1987): a saga is a sequence of sub-transactions each with a **compensating transaction** that semantically undoes it; on failure, run compensations in reverse. The pattern assumes every step *has* a compensation. The JARVIS-relevant critique (dev.to, Oct 2026 — https://dev.to/robat_das_3c6e956212f6408/ai-agent-rollback-why-the-saga-pattern-fails-for-tool-calls-3j6a): **"a saga can only undo what it has a rule for. The destructive call is the one nobody wrote a rule for"** — and therefore *"the irreversible class should be blocked by scope or approval before the call runs, not compensated"* [MC — practitioner analysis, but the logic is airtight and matches the 1987 paper's own definition: compensation "does not necessarily restore the earlier state"].

Transfer: this is the principled justification for validator check (c) in §5.2. Compensation is the mechanism for *reversible* steps; **approval events are the mechanism for irreversible steps** (compensation: none). The validator enforces the split at plan time, before anything executes.

### 3.5 The frame problem, in miniature

STRIPS bakes in a solution to the frame problem: the **STRIPS assumption** — everything not mentioned in `del(a)` persists. For tool contracts this becomes: *the validator is sound with respect to the model, not the world.* A tool that mutates unmodeled shared state (rate-limit counters, caches, "last opened" timestamps) violates the assumption silently. Mitigations in §5.4: typed effect categories (tracked predicates vs. open world), verify-after-acting diffs, and Hypothesis conformance tests that compare declared vs. observed effects.

---

## 4. Compare — relation to prior cycles

- **Cycle 7** posed the rung-4 replacement as one table row ("STRIPS-lite action model … named but not designed"). This cycle is that design, and it closes the loop on the squeeze argument: the deterministic competitor for rung 4 now has a spec, an algorithm, and a complexity bound instead of a name.
- **learn-formal-methods.md** put contracts on *functions* (deal on 5–10 critical functions). This cycle puts contracts on *tool actions* — same DbC idea, lifted one level to plan composition. The deal-contracted permission gate and the STRIPS validator compose: the gate decides *whether an action may run at all*; the validator decides *whether this sequence is coherent*.
- **learn-frontier-reasoning.md**'s neuro-symbolic loop gets its "disposes" half specified here; the LLM-Modulo numbers (12%→82%) are the first empirical anchor for that loop's effectiveness claim.
- **learn-advanced-cs.md**'s durable queue + idempotency is where the validator's `compensation` and `idempotent` fields get consumed at runtime (dispatch-time re-check, reverse-order compensation on mid-plan failure).

---

## 5. DERIVE — the STRIPS-lite plan validator [DESIGN]

### 5.1 The tool-contract schema — beyond JSON Schema

MCP tools and JSON Schema describe **syntax**: argument names, types, required fields (cycle 7's rungs 1–2 — already deterministic). Plan validation needs **semantics**: what must be true before, what becomes true after, what is destroyed, and how to undo it. The schema below extends the existing TOOL_DEFINITIONS contract; every field is machine-checkable.

```yaml
tool: email_send                       # name — must exist in the tool registry (catches hallucinated tools, cycle-7 E4.4-class)
tier: dangerous                        # read | write | dangerous — maps to the permission manifest
description: "Send an email via the connected mailbox."

preconditions:                         # propositions that must hold in the simulated state
  - network_available
  - valid_address(to)                  # parameterized predicates; args bound at validation time
  - file_exists(attachment)            # conditional: only when `attachment` arg is present

add_effects:                           # propositions made true
  - email_sent(to, subject)

delete_effects:                        # propositions made false (STRIPS del)
  - draft_exists(draft_id)             # conditional: only when sending from a draft

idempotent: false                      # re-execution with same args: same end state? (feeds the queue's retry policy)
compensation: none                     # none | <tool-call template> — the Saga-pattern undo. `none` ⟹ irreversible.
requires_approval: true                # false | true — irreversible or policy-flagged actions need an approval event
completeness: known_incomplete         # known_complete | known_incomplete — model-lite annotation (§3.3)
budget_cost: { tokens: 0, seconds: 5 } # expected cost; feeds the metalevel ≤5% budget law
```

**Field rationale (why each exists):**
- `preconditions` / `add_effects` / `delete_effects` — the STRIPS triple; the minimum for simulation.
- `tier` — checked against the **permission manifest** (monotonicity: a plan may never use a tier above what the session manifest grants; revocation mid-session invalidates already-validated plans — re-validate on manifest change).
- `idempotent` — decides the queue's retry policy (learn-advanced-cs.md): idempotent steps retry freely; non-idempotent steps need idempotency keys.
- `compensation` — the Saga undo, run in reverse order on mid-plan failure. `none` marks the irreversible class.
- `requires_approval` — the Saga-critique transfer (§3.4): irreversible steps are gated *before* execution by an approval event in the ledger, never "compensated" after.
- `completeness` — the model-lite transfer (§3.3): honesty about what the contract doesn't know; drives verify-after-acting aggressiveness.
- `budget_cost` — validation itself must obey the metalevel budget (cycle 7: ≤5% overhead).

**Authoring cost control:** contracts are hand-written once per tool (~40 tools), each reviewed like a deal contract on a critical function. Refinement is offline via trace analysis (ARMS-style), never live self-edit.

### 5.2 The validator algorithm

**Inputs:**
- `plan`: ordered list of grounded tool calls `[(tool, args), ...]` proposed by the LLM.
- `contracts`: registry mapping tool name → contract (§5.1).
- `S0`: initial state — set of ground propositions from the belief ledger + fresh environment reads (filesystem, network, permission manifest snapshot).
- `goal`: set of goal propositions (extracted from the task statement by the planner prompt; itself validated for sanity — every goal predicate must be producible by some tool's add_effects, else the goal is unachievable *by construction* and the plan is rejected before simulation).
- `manifest`: permission manifest (tool → max allowed tier).
- `approvals`: set of approval events in the ledger.

**Algorithm** (simulate, checking four properties):

```
S ← S0
for i, (tool, args) in enumerate(plan):
    if tool ∉ contracts:                       # hallucinated tool
        return REJECT(i, "unknown_tool", tool)
    c ← contracts[tool]

    # (b) permission monotonicity
    if tier_rank(c.tier) > tier_rank(manifest[tool]):
        return REJECT(i, "permission", f"{tool} tier {c.tier} exceeds manifest grant")

    # (c) irreversible actions need approval events
    if c.requires_approval and approval_id(tool, args, i) ∉ approvals:
        return REJECT(i, "approval", f"{tool} is irreversible/policy-gated; no approval event")

    # (a) precondition check against simulated state
    for p in ground(c.preconditions, args):
        if p ∉ S:
            return REJECT(i, "precondition", f"unmet: {p} — no prior step establishes it")

    # apply effects
    S ← (S − ground(c.delete_effects, args)) ∪ ground(c.add_effects, args)

    # verify-after-acting hook (post-dispatch, not shown here): after real execution,
    # re-read environment, diff observed vs declared effects, write to ledger
    # (cycle-7 null architecture: "the environment is the verifier")

# (d) goal check — not full search, just subset
if not goal ⊆ S:
    return REJECT(len(plan), "goal", f"unachieved: {goal − S}")
return ACCEPT(trace=S)
```

**Rejection output is a machine counterexample**, not prose: `(step_index, fault_class, unmet_proposition)`. The replan prompt receives exactly this triple plus the failed plan — the LLM-Modulo/Planning-Copilot backprompt pattern (§3.2), and it respects cycle 7's least-privilege rule: no validator internals, no narration, no trace laundering.

**Complexity** [DESIGN, straightforward analysis]:
- Let `n` = plan length, `p` = max preconditions per action, `e` = max effects per action, `g` = |goal|. States as hash sets → precondition check O(p), effect application O(e), manifest/approval lookups O(1).
- **Validation: O(n·(p + e) + g)** — linear in plan length. For JARVIS plans (n ≤ ~10, p,e ≤ ~6): microseconds.
- Compare: PlanSAT (plan *existence*) is **PSPACE-complete**; bounded PlanSAT is **NP-complete** [VC, §3.1]. Validation is not a watered-down planner — it is a *different, exponentially cheaper problem*, because the LLM supplies the candidate sequence. The hardness lives in search; we never search.

### 5.3 Worked example — hand-run, with a caught violation

**Task:** "Download the Q3 report, extract the revenue table, and email it to Priya."

**Contracts** (abbreviated to the fields that matter):

| tool | tier | preconditions | add_effects | idempotent | compensation | requires_approval |
|---|---|---|---|---|---|---|
| `http_fetch(url, to)` | read | `network_available`, `url_wellformed(url)` | `file_exists(to)` | false | `delete_file(to)` | false |
| `pdf_extract_table(path, page, table, to)` | read | `file_exists(path)` | `file_exists(to)`, `table_extracted(path,to)` | true | `delete_file(to)` | false |
| `email_send(to, subject, attachment?)` | dangerous | `network_available`, `valid_address(to)`, `file_exists(attachment)` if given | `email_sent(to,subject)` | false | **none** | **true** |

**Initial state S0** (ledger + environment reads): `{ network_available, valid_address(priya@example.com), url_wellformed(https://reports.example.com/q3.pdf) }`. Approval ledger: empty.

**LLM-proposed plan P (faulty order — the cycle-7 E4.3 class):**
1. `pdf_extract_table(path=/tmp/q3.pdf, page=3, table=1, to=/home/owais/Documents/reports/revenue-q3.csv)`
2. `http_fetch(url=https://reports.example.com/q3.pdf, to=/tmp/q3.pdf)`
3. `email_send(to=priya@example.com, subject="Q3 revenue table", attachment=/home/owais/Documents/reports/revenue-q3.csv)`

**Validation run 1:**
- Step 1 `pdf_extract_table`: known tool ✓; tier read ≤ manifest ✓; no approval needed ✓; precondition `file_exists(/tmp/q3.pdf)` — **∉ S0, and no prior step** → **REJECT(1, "precondition", unmet: file_exists(/tmp/q3.pdf))**.
- Counterexample to the LLM: `(step=1, fault=precondition, unmet=file_exists(/tmp/q3.pdf))` + hint "no prior step establishes it — fetch the report first." An LLM plan-judge at 55–65% might wave this through ("the steps are all sensible"); the validator cannot.

**Replanned P′ (correct order):**
1. `http_fetch(...)` → preconditions ✓ → S1 = S0 ∪ {`file_exists(/tmp/q3.pdf)`}
2. `pdf_extract_table(...)` → `file_exists(/tmp/q3.pdf)` ✓ → S2 = S1 ∪ {`file_exists(…/revenue-q3.csv)`, `table_extracted(…)`}

**Validation run 2:**
- Step 3 `email_send`: known ✓; tier dangerous ≤ manifest (mailbox connected) ✓; preconditions `network_available` ✓, `valid_address` ✓, `file_exists(attachment)` ✓ — all satisfied; **but** `requires_approval: true`, `compensation: none`, and no approval event in the ledger → **REJECT(3, "approval", "email_send is irreversible (no compensation); no approval event")**.
- This is the Saga-critique check (§3.4): a sent email cannot be unsent, so the gate fires *before* execution. The plan is formally flawless and still refused — correctly.

**Approval granted** (Owais taps the approval card) → approval event recorded in the ledger → **validation run 3:** step 3 passes → S3 = S2 ∪ {`email_sent(priya@example.com, "Q3 revenue table")`}.
- **Goal check:** G = {`email_sent(priya@example.com,"Q3 revenue table")`, `file_exists(…/revenue-q3.csv)`} ⊆ S3 → **ACCEPT**. Dispatch.

Two faults caught, two different check classes (a: precondition, c: approval), one clean accept. The validator also demonstrates what it does *not* do: it cannot tell whether Priya is the *right* recipient (semantic fault — needs valid_address only, not correct_address) — admitted residual, §5.4.

### 5.4 Where it breaks — and the mitigations

| Breakage | Mechanism | Mitigation | Status |
|---|---|---|---|
| **Contract incompleteness** (the big one): a tool does something its contract doesn't declare — e.g. `http_fetch` follows a redirect to another domain; `pdf_extract_table` writes a cache file. The validator is sound w.r.t. the *model*, blind outside it. | Unmodeled effect violates the STRIPS assumption silently. | Three layers: (1) **verify-after-acting** (adopted, cycle 7): after each consequential step, re-read the environment and diff observed vs declared effects — the environment is the verifier; (2) **contract conformance tests**: Hypothesis generates random action sequences × random environments, executes against sandboxed mocks, asserts declared add/del effects match the observed state diff — the formal-methods cycle's Hypothesis recommendation applied to contracts; (3) **completeness annotations** (§3.3): `known_incomplete` contracts trigger aggressive verify-after-acting and lower ledger confidence. | DESIGN — needs the conformance harness. |
| **TOCTOU**: state changes between validation and execution — the file validated at plan time is deleted before dispatch. | Validation is a snapshot; the world moves. | **Dispatch-time re-check**: the queue dispatcher re-evaluates *preconditions only* against fresh environment reads immediately before each tool call (cheap: O(p), no full re-validation). Plus durable queue + idempotency keys (learn-advanced-cs.md) so a mid-plan crash replays safely. The deep validation runs once per plan; the cheap re-check runs per dispatch. | DESIGN — standard practice. |
| **Frame problem in miniature**: shared unmodeled state — rate-limit counters, "recently used" lists, caches. The STRIPS assumption ("what isn't deleted persists") is false for these. | Validator's state diverges from reality over long plans. | **Typed effect categories**: contracts distinguish *tracked* predicates (in the state set) from the open world; validator soundness is explicitly scoped to tracked predicates. Verify-after-acting diffs catch drift; systematic drift on one tool → contract amendment (offline, ARMS-style). Long plans (>~10 steps) get a mid-plan re-validation checkpoint. | DESIGN. |
| **Semantic faults pass**: valid-but-wrong plans — right file, wrong recipient (address valid, person wrong); plan achieves the stated goal but not the intent; goal itself mis-extracted. | The validator checks *validity*, never *intent*. | Admitted residual (cycle 7 §7: "accepted residual risk"). Handling: high-stakes plans → different-model critic or human gate per the §6 POMDP math; goal-extraction sanity check (every goal predicate producible by some add_effect). **This is the boundary of the deterministic core — stated, not hidden.** | Accepted limitation. |
| **Permission manifest drift**: grant revoked after validation, before dispatch. | Stale manifest snapshot. | Manifest version counter; any change invalidates in-flight validated plans → re-validate (cheap: microseconds). | DESIGN — trivial. |
| **Contract authoring burden**: ~40 tools × contract fields; authors get preconditions wrong. | Human error in the model. | Contracts reviewed like deal contracts on critical functions; the conformance-test harness (§3.3, ARMS-style offline refinement) catches authoring errors empirically; start with the dangerous tier (highest ROI), then write tier. | Open measurement: time-per-contract; kill threshold in §6. |

**What the validator deliberately excludes** (STRIPS-*lite*): conditional effects, numeric fluents, durative/temporal actions, parallel steps. If a tool needs conditional effects, that is a **design smell** — split the tool into two tools with unconditional contracts. JARVIS dispatches sequentially through the durable queue, so the sequential-plan assumption holds by construction.

---

## 6. Validate — falsifiers [DESIGN]

What would kill or bound this design (measured when built):

1. **Contract-authoring cost**: if hand-authoring a correct contract takes >30 min/tool on average across the dangerous+write tiers, the registry won't be maintained and will rot. Mitigation path: ARMS-style offline learning from traces.
2. **False-reject rate**: run the cycle-7 rung-4 golden set (50 plans) through the validator; if validator precision < 95% against the STRIPS-simulator ground truth — i.e., it rejects valid plans because contracts are wrong — the contracts are the problem, not the algorithm (the algorithm is provably sound w.r.t. the model).
3. **Replan convergence**: LLM-Modulo reports 12%→82% on PDDL tasks; our domain (tool APIs, messier predicates) may differ. Measure: % of rejected plans reaching ACCEPT within 2 replan rounds. If <70%, the counterexample format needs work (richer hints), not the validator.
4. **The honest-scope test**: construct 10 valid-but-wrong plans (right file/wrong person class). The validator must accept all 10 — if it rejects any, it's smuggling in semantic judgment it can't do reliably, and the boundary statement is false. **The validator passing this test by accepting is the correct outcome.**

## 7. Integrate — ADR

**Decision:** ADOPT the STRIPS-lite plan validator as the rung-4 replacement in the null-hypothesis architecture (cycle 7 §7), with the tool-contract schema (§5.1) extending TOOL_DEFINITIONS.

**Consequences:**
- Every tool in the dangerous tier gets a full contract first (approval + compensation fields are load-bearing there), then write tier, then read tier.
- The plan boundary (LLM output → queue dispatch) gains a validation gate: REJECT → machine counterexample → replan (max 2 rounds) → escalate per POMDP math.
- The dispatcher gains the cheap precondition re-check (TOCTOU) and reverse-order compensation runner (Saga).
- Contracts are versioned data, refined offline from traces; the live LLM never edits contracts.
- Open-problem #3 (from learn-open-problems.md, via cycle 7): the discriminator precondition for tree search now has a *deterministic* candidate for the plan-validity sub-problem — tree search over tool plans can use the validator as its discriminator for formal faults, with semantic faults still gated by the 90% rule.

## 8. Record — evidence table

| # | Claim | Evidence | Confidence |
|---|---|---|---|
| 1 | Plan validation (given sequence) is polynomial; planning is PSPACE-complete | Bylander 1994 (PlanSAT PSPACE-complete); VAL/Howey-Long-Fox 2004 (validation by simulation); Nebel & Mattmüller slides | [VC] on the complexity split |
| 2 | LLM proposes + external verifier disposes + backprompt converges (12%→82%) | Kambhampati et al., LLM-Modulo, arXiv:2402.01817, ICML 2024 | [HC] (peer-reviewed; domain is PDDL tasks, not tool APIs) |
| 3 | Validation-as-a-tool with machine failure reasons is a field-tested MCP pattern | Planning Copilot 2025 (VAL as MCP tool; failure reason + fix suggestion fed back) | [HC] |
| 4 | Incomplete models should be explicitly annotated, not pretended complete | Model-lite planning (Kambhampati 2007); Nguyen et al. 2011 (robust plans under incomplete models) | [HC] |
| 5 | Irreversible actions must be approval-gated before execution, not compensated after | Garcia-Molina & Salem 1987 (compensation ≠ restoration) + the 2026 agent-rollback critique | [MC] (practitioner analysis; logic verified against the 1987 definition) |
| 6 | Contracts can be refined offline from execution traces | ARMS (Yang et al. 2007), RIM, FAMA — action-model acquisition literature | [HC] on existence; [MC] on effort for our domain |
| 7 | Validation is O(n·(p+e)+g) — microseconds for JARVIS-scale plans | Direct analysis of §5.2 (§6: falsifiable via benchmark) | [DESIGN] — analysis, unmeasured |
| 8 | The validator catches precondition/order/approval faults; cannot catch intent faults | Worked example §5.3 (hand-run); honest-scope test spec §6.4 | [DESIGN] for the mechanism; the boundary is definitional |

## 9. Reassess — what changes, what's still unknown

**What changes:** rung 4 of the null architecture is no longer a named hope — it has a schema, an algorithm, a complexity bound, and a hand-run example. The squeeze argument (cycle 7) now rests on a *constructed* deterministic competitor rather than an asserted one. The neuro-symbolic loop has both halves specified: propose (LLM) and dispose (validator + counterexample).

**Unknowns [UK]:**
- The false-reject rate from imperfect contracts in practice (needs the conformance harness + golden set — §6.2).
- Replan convergence rate on tool-API domains vs PDDL domains (LLM-Modulo's 82% may not transfer — §6.3).
- Whether predicate grounding (`valid_address`, `file_exists`) stays cheap enough at dispatch scale for the TOCTOU re-check.
- The right mid-plan re-validation checkpoint for long plans (proposed: >~10 steps; unmeasured).
- Interaction with concurrent plan execution — currently out of scope by the sequential-dispatch design; if JARVIS ever dispatches parallel tool calls, the validator needs a partial-order extension (PDDL2.1-style mutex checking per VAL — known tractable, but unbuilt).

**Next cycle suggestion:** the contract-conformance test harness design (Hypothesis × sandboxed tool mocks × declared-vs-observed effect diffing) — it is the load-bearing mitigation for breakage #1, and it is currently the least-designed piece.
