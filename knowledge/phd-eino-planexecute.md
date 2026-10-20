# PhD: eino's planexecute — Replanning as a First-Class Role

*LEARNING ONLY — no code written, no installs, no execution. Date: 2026-10-19.*
*Subject: `github.com/cloudwego/eino/adk/prebuilt/planexecute` (Apache-2.0 ✅ verified on repo page; 13,345★; 470 commits; ByteDance official via cloudwego org; created 2024-12-04).*
*Method: full source read of `plan_execute.go` (1,621 lines, main branch @ 0a5ca53), pkg.go.dev API docs, official cloudwego.io docs (EN+ZH), official examples (Excel agent; `6_plan-execute-replan` travel booking with human-in-the-loop).*

## Plain-words summary

eino's planexecute splits an agent into three roles that take turns: a **Planner** writes a step list once, an **Executor** does the first step, and a **Replanner** looks at what happened and makes a forced either/or choice — write a new plan, or declare the job done. They talk to each other through a shared notepad (session keys), not by passing chat history. The single most stealable idea: **the thing that asks "the plan met reality — now what?" is its own component**, with its own prompt and its own budget — not a mode of the thing doing the work. The honest gaps: their replanner judges by vibe (no structural check that the plan actually held), their "plan" is prose strings (so deviation can't be detected mechanically), and three model calls per step is too expensive for anything latency-sensitive. JARVIS steals the role separation and the forced binary choice, but keeps the void-decision in deterministic code.

**Outcome label (Domain XI):** the eino module itself = *experimentally supported* (shipping production framework, official examples, 13k stars) but *unbenchmarked as a module* (no published numbers on planexecute specifically). Our adaptation below = *new combination of known techniques*.

---

## 1. The mechanism — from the source

### 1.1 The composition (plan_execute.go L1584–1619)

The entire module is one expression:

```go
New() = SequentialAgent[ Planner, LoopAgent[ Executor, Replanner ] ]
```

- `Planner` runs **exactly once**, at the start. Planning is not re-entrant by default.
- Then a loop alternates `Executor → Replanner → Executor → Replanner…`, bounded by `MaxIterations` (default **10**).
- The loop breaks when the Replanner calls the `respond` tool, which emits `adk.NewBreakLoopAction` — the break is an *event*, not a return value. [VC — read in source, L1369–1379]

### 1.2 The shared blackboard (L450–471)

The three roles never pass messages to each other. They read/write four named session keys:

| Key | Written by | Read by | Content |
|---|---|---|---|
| `UserInput` | Planner (L607) | Executor, Replanner | the original user messages |
| `Plan` | Planner (L744), Replanner (L1400) | Executor, Replanner | the current `Plan` object |
| `ExecutedStep` | Executor (via `OutputKey`, L1026) | Replanner | the latest step's result (string) |
| `ExecutedSteps` | Replanner (L1223–1231) | Executor, Replanner | the appended history of {step, result} |

The `ExecutionContext` struct (L877–885) is rebuilt from these keys at the start of every Executor and Replanner turn — **each role gets a fresh, minimal context; nobody pays for anyone else's history.** [VC]

### 1.3 The Plan as a JSON interface (L82–151)

```go
type Plan interface {
    FirstStep() string        // the only behavioral method
    json.Marshaler             // serialize for prompts
    json.Unmarshaler           // parse model output
}
```

The default implementation is `defaultPlan{ Steps []string }` — an ordered list of **prose strings**. This is the module's deepest design decision and its biggest weakness: a step is text, not a typed action with an expected world-state. There is no field for "what should be true after this step," no tier, no contract hash. [VC — the weakness is structural, visible in the type definition itself]

### 1.4 The Planner (L558–872)

Two construction modes, both producing a structured `Plan`:
1. **Structured-output model** (`ChatModelWithFormattedOutput`) — the model emits the Plan JSON directly.
2. **Tool-calling model + forced choice** — the model is configured with the `plan` tool (`PlanToolInfo`: one required param, `steps: string[]`) and `ToolChoiceForced` (L758). **The model cannot answer in prose; it must emit a plan.** [VC]

The planner prompt demands steps that are specific, self-contained, independently executable, and logically sequenced — and its final step must "produce a complete answer or deliverable." The plan is written to the session once; the planner never runs again.

### 1.5 The Executor (L940–1075)

A standard `ChatModelAgent` with the user's tools, `MaxIterations` 20 (its own internal ReAct loop per step), and one job: **execute the first step of the current plan**. Its prompt receives `{input, plan, executed_steps, step}` — the objective, the full plan, what's done, and the single step to do now. Its final output is stored as the `ExecutedStep` string. Note the asymmetry: the executor sees the *whole plan* but is told to do *only the first step* — the discipline against "helpfully" running ahead lives in the prompt, not in code. [HC]

### 1.6 The Replanner (L1078–1535) — the heart of the module

This is the piece that matters. The replanner:

1. **Reads** the latest `ExecutedStep`, **appends** it to `ExecutedSteps` (L1223–1231).
2. **Builds** its input: objective + original plan + all executed steps & results.
3. **Is forced into a binary choice** via `ToolChoiceForced` (L1302) between exactly two tools:
   - `respond` → emits `NewBreakLoopAction` → **the loop breaks, the task is done** (L1371–1379).
   - `plan` → the returned JSON is unmarshalled into a new `Plan`, which **replaces** `PlanSessionKey` (L1400) → loop continues with the revised plan.
   - Anything else → hard error: `"unexpected tool call"` (L1386). There is no third option, no prose escape hatch.

**The transferable trick, stated precisely:** the replanner's judgment is reduced to the *smallest possible decision surface* — one forced binary tool call. All the "should I continue?" reasoning happens in the model's head, but the *output* is mechanically constrained to two verbs. This is how you get LLM judgment without LLM sprawl. [VC — this is the #1 steal]

### 1.7 Human-in-the-loop

The official `6_plan-execute-replan` example (travel booking) shows the framework's interrupt support firing at **tool-call level inside the executor**: before `book_flight` executes, the run pauses, shows tool + arguments, and the user types `ok`, `n`, or edited JSON. The replanner then continues from the human-modified result. Interrupts are a framework capability (ADK), not planexecute-specific — but planexecute's step granularity makes them natural: **every tool call inside every step is an interruptible boundary.** [HC — from the official example transcript]

---

## 2. Evidence — what's proven vs claimed

| Claim | Status |
|---|---|
| Apache-2.0 license | ✅ VERIFIED — GitHub repo page, "Apache License 2.0" |
| 13,345 stars, 470 commits, ByteDance official (cloudwego org) | ✅ VERIFIED — repo page, 2026-10-19 |
| Module exists in `adk/prebuilt/planexecute`, documented | ✅ VERIFIED — source read + pkg.go.dev + cloudwego.io docs (EN+ZH) |
| Official examples work (Excel agent, travel HITL) | ✅ VERIFIED — example transcripts published |
| ByteDance uses planexecute internally in production | ⚠️ [UK] — plausible (Doubao/Feishu agent programs exist; eino is ByteDance's official framework) but **no public statement ties planexecute to a production deployment** |
| Benchmarks of planexecute vs ReAct / vs alternatives | ❌ NONE FOUND — no published numbers on the module itself |
| The 3-role split improves outcomes | [MC] — supported by framework adoption + examples, not by controlled comparison |

Honest bottom line: this is a *production framework's* planning module with real users and official examples — that clears "experimentally supported." It is not a *measured* planning result — nothing here is a benchmark claim. [VC on the distinction]

---

## 3. The transfer — exactly what JARVIS steals

### 3.1 The core steal: replanning as a first-class role

JARVIS's deviation-voids rule needs a component whose entire job is: **"the plan met reality — now what?"** eino proves this should be a *separate component* with its own prompt, its own inputs, and its own budget — not a branch inside the executor, not a re-invocation of the planner. The separation is what makes the behavior legible, testable, and budgetable.

### 3.2 The critical divergence: who decides the plan is void

| | eino | JARVIS (our adaptation) |
|---|---|---|
| Void detection | LLM judgment ("do the results suggest strategy adjustment?") | **Deterministic code**: contract-hash comparison of step outcome vs expected outcome |
| Replan trigger | model calls `plan` tool | code declares VOID → stop → the *proposal* of a revised plan goes to the user (tier ≥2) or auto-continues (tier-1, within budget) |
| Complete detection | model calls `respond` tool | code checks success criteria (P1 observable world-state); model *proposes* completion, code *verifies* it |

**The rule: the void decision is structural; the revised plan is advisory.** eino's forced-binary-choice trick is kept — JARVIS's replan component also gets exactly two verbs (`continue` / `complete`) — but the *void* verdict comes from comparing the `ExecutedStep`'s recorded outcome against the contract's expected outcome, in code, before the model is consulted. The model never gets to decide "the plan held" when the hash says it didn't. [DESIGN — this is the adaptation, marked as such]

### 3.3 Python interface sketch (patterns only — no eino code)

```python
@dataclass(frozen=True)
class PlanStep:
    action: str            # what to do
    tool: str              # which tool
    expected: str          # observable world-state after (the void-check target)
    tier: int              # 1/2/3 — from the skill manifest, never the plan
    terminal: bool = False # must be the last step; produces the deliverable

@dataclass(frozen=True)
class PlanContract:
    objective: str
    success: str           # observable "done", plus what would prove not-done
    steps: tuple[PlanStep, ...]
    contract_hash: str     # sha256 of the canonical serialization, taken at approval

@dataclass(frozen=True)
class ExecutedStep:
    step_index: int
    step: PlanStep
    result: str
    outcome: str           # observed world-state (the void-check source)

class PlanStore:           # the session blackboard
    def get_plan(self, session_id) -> PlanContract: ...
    def append_step(self, session_id, s: ExecutedStep) -> None: ...
    def void_plan(self, session_id, reason: str) -> None: ...  # tombstone, never mutate

def check_deviation(contract: PlanContract, s: ExecutedStep) -> str | None:
    """Deterministic. Returns None if the step matches, else the void reason."""
    # outcome vs step.expected; unlisted step; tier escalation via manifest lookup

def replan_controller(session_id) -> Literal["continue", "complete", "void"]:
    """Deterministic pre-pass. The LLM replan-proposer only runs on 'continue'."""

def propose_revised_plan(objective, old_contract, executed: list[ExecutedStep]) -> PlanContract:
    """LLM, forced binary output (continue-with-this-plan / complete-with-this-answer).
    Its output is a PROPOSAL; the contract is only replaced after the approval path."""
```

The loop, mirroring eino's `SequentialAgent[Planner, LoopAgent[Executor, Replanner]]`:

```python
def run_plan_turn(session_id, user_input, budget):
    contract = planner_agent.propose(user_input)   # once; approved → hashed → stored
    while budget.steps_remaining and not contract.complete:
        step = contract.next_step()
        gate.check(step)                            # tier gate BEFORE execution — eino lacks this
        executed = executor_agent.run(step)         # one step only
        store.append_step(session_id, executed)
        verdict = replan_controller(session_id)     # deterministic void/continue/complete
        if verdict == "void":
            return ask_user(void_reason)            # deviation voids, always
        if verdict == "complete" and gate.verify_success(contract, executed):
            break
        # 'continue': the LLM replan-proposer may suggest a revised contract,
        # which re-enters the approval path; it never silently replaces the old one
```

### 3.4 What maps where (traceability)

| eino | JARVIS |
|---|---|
| `Plan` interface + `FirstStep()` | `PlanContract` + `next_step()` |
| Session keys (UserInput/Plan/ExecutedSteps) | Session-store events (`plan.proposed/approved/step_completed/voided`) |
| Forced `plan`/`respond` binary | Forced `continue`/`complete` proposal verbs |
| `MaxIterations` 10 | Turn budget (12 tool calls) + β termination per multi-scale |
| `NewBreakLoopAction` on respond | `plan.completed` event; loop exits |
| Executor's whole-plan visibility | Executor sees current step + contract summary only (least privilege) |
| HITL at tool-call level | Tier-3 approval gates (already specced) |

---

## 4. The gap — Go to Python, patterns only

Nothing is copied: the language differs, and — more importantly — the *trust model* differs. eino's roles trust the model; JARVIS's roles trust the code and use the model for proposals. What transfers is pure structure: (a) three roles, (b) the blackboard, (c) run-planner-once-then-loop, (d) the forced binary verdict, (e) executed-step as the unit of progress. All five are language-independent. [VC]

---

## 5. Limitations — honest

1. **Cost: ≥3 model calls per step** (executor + replanner every iteration, planner once). On JARVIS's voice path this is disqualified outright (the latency veto); replanning belongs on PLAN/DEEP turns only. eino pays this on every turn with no fast path. [VC]
2. **Thrashing:** nothing stops the replanner rewriting the plan every step — the only guard is the crude `MaxIterations=10`. A replanner that "adapts" forever never converges. JARVIS needs the β discipline (replan budget, deviation budget, 3-failure auto-pause) that eino lacks. [HC]
3. **Vibe-judged completion:** "is the objective satisfied?" is answered by the model's feeling. Their travel example needs a human at every booking *because the framework cannot verify outcomes itself*. JARVIS's P1 observable success criteria + deterministic verification exist precisely to fill this hole. [VC]
4. **Prose plans can't void structurally:** steps are strings, so "deviation" is undefinable in code. This is the single biggest thing JARVIS adds: typed steps with expected world-states. [VC]
5. **Fail-loud session reads:** `panic("impossible: plan not found")` — the "impossible" states are reachable on interrupt/resume paths. Fail-loud beats fail-silent, but a production system needs the recovery path, not the panic. [HC]
6. **No security model:** the executor's tools run with ambient authority; eino's own README says enforce at the tool/sandbox level. JARVIS's gate + jail + tiers are the missing layer. [VC — stated in their docs]

---

## 6. The 5 patterns — precise enough to implement from

1. **Forced binary verdict.** The replan component's output is mechanically constrained to two verbs (`continue` / `complete`) via forced tool choice (or structured output with a 2-variant schema). The model's reasoning can sprawl; its *verdict* cannot. *Implement:* the replan LLM call uses `tool_choice="required"` with exactly two tools; any other output is a retryable error, not a judgment.
2. **Blackboard, not history.** Roles share state through named, typed session keys — never by forwarding conversation transcripts. Each role invocation rebuilds a minimal context from the blackboard. *Implement:* `plan.proposed/approved/step_completed/voided` events in the session store; each role reads events, not messages.
3. **Plan once, loop the rest.** The planner is outside the loop and runs exactly once per turn. Replanning revises; it never re-derives from scratch (that would discard the executed evidence). *Implement:* `SequentialAgent[Planner, LoopAgent[Executor, ReplanController]]` — the composition is the architecture.
4. **ExecutedStep as the unit of progress.** Every loop iteration appends `{step, result, observed_outcome}`. Progress tracking, audit, deviation detection, and the replanner's input are all the same object. *Implement:* one append-only per-step record; the activity feed, the void-check, and the replan prompt all read it.
5. **Replan is a role with a budget.** The "plan met reality — now what?" function has its own prompt, its own inputs (objective + contract + executed steps), and its own termination (max replans, deviation budget). It is not a mode of the executor and not a second planner. *Implement:* separate component, separate β conditions, and — the JARVIS addition — its verdict is *advisory*; the void/complete decision is deterministic code that runs first.

---

## Confidence & unknowns

- **[VC]:** the mechanism (full source read), the license, the forced-binary trick, the blackboard pattern, the cost-per-step arithmetic, the prose-plan weakness, the missing security model.
- **[HC]:** the thrashing risk, the panic-on-missing-key reachability, the HITL mapping, the Python sketch's fidelity to the pattern.
- **[MC]:** that the 5 patterns transfer cleanly to the tiered/contract architecture (the adaptation is designed, not tested).
- **[UK]:** ByteDance internal production use of planexecute specifically; any benchmark of the 3-role split vs alternatives; optimal replan budget numbers (awaiting build + measurement).

*End of PhD. Status: complete as a study; unimplemented by intent (learning phase). The 5 patterns are specified for the plan-mode build, gated on Owais's go-ahead.*
