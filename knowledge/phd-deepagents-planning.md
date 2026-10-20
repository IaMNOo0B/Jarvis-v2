# PhD: langchain-ai/deepagents — The Planning Primitive, Dissected

*LEARNING ONLY — no project files touched, no installs, no code executed. Date: 2026-10-19.*
*Task: PhD deep-dive on the #2 ranked planning repo for JARVIS.*

## Plain-words summary

deepagents is LangChain's "batteries-included agent harness" — 30,409 stars, MIT, the most field-tested agent framework in existence. Its planning system is a single tool, `write_todos`, that **does nothing**. It executes no code, changes no world state. It just writes a to-do list into the agent's context. And that no-op is the whole trick: forcing the model to articulate its plan *before* acting cures the three diseases of long-horizon agents — random task switching, forgotten steps, mid-task abandonment (collectively "context fade" / "task drift"). The mechanism is a 213-line behavioral description (the most detailed tool description in the system), a typed three-state item schema, a dedicated state channel, and a small set of structural guards. What JARVIS steals is the **format and the discipline** — never the trust model: deepagents' README says explicitly "trust the LLM... enforce boundaries at the tool/sandbox level, not by expecting the model to self-police." Our gate does the enforcing; their todo list does the planning. The two were made for each other.

**Outcome label (Domain XI):** the `write_todos` pattern = *known technique, experimentally supported* (30k stars of field evidence, Claude Code lineage). JARVIS's enforced-contract adaptation (hash + deviation-voids + tier re-lookup) = *new combination of known techniques*, unvalidated until built.

---

## 1. Identity and verification [VC]

| Fact | Value | Source |
|---|---|---|
| Repo | https://github.com/langchain-ai/deepagents | — |
| Stars | 30,409 | repo page, read live 2026-10-19 |
| License | **MIT — verified** | repo page, read live 2026-10-19 |
| Created | 2025-07-27 | repo page |
| Commits / releases | 4,269 / 318 | repo page |
| Stack | Python + TypeScript, LangGraph runtime | repo page |
| Lineage | "Inspired by Claude Code: an attempt to identify what makes it general-purpose, and push that further" | README, Acknowledgements |

The repo is real, active, and permissively licensed — ideas AND code are borrowable.

---

## 2. Mechanism — how the planning primitive actually works

### 2.1 TodoListMiddleware: the four things it does [VC]

`TodoListMiddleware` (now in `langchain.agents.middleware`, included by default in `create_deep_agent`) does exactly four things:

1. **Injects two tools:** `write_todos` (create/replace the list) and `read_todos` (read current state).
2. **Extends the state schema** with a dedicated `todos` state channel (LangGraph state channel — the list lives in agent state, not in message history).
3. **Injects system-prompt guidance** on when and how to plan (customizable via config).
4. **Enforces one structural guard:** `write_todos` may be called **at most once per model turn**, because the tool *replaces the entire list* — parallel calls would create ambiguity about precedence. This is deterministic code, not a suggestion. [HC — documented in the API reference]

### 2.2 The item schema — typed, minimal [VC]

```python
Todo = { "task": str, "status": Literal["pending", "in_progress", "completed"] }
```

Three fields in spirit (two in the type): a prose description and a three-state lifecycle. No IDs, no priorities, no dependencies, no owners in the schema — dependencies and tool-notes go in the prose. This minimalism is load-bearing: the schema is simple enough that every model (frontier to local) fills it correctly, and everything richer lives in the 213-line description where it can be *taught* rather than *typed*.

### 2.3 The 213-line tool description — behavioral rules, not adjectives [HC]

`WRITE_TODOS_TOOL_DESCRIPTION` is the most detailed tool description in the system (213 lines). Its sections:

| Section | Purpose |
|---|---|
| When to Use | 3+ steps, complex tasks, user explicitly requests planning |
| How to Use | mark `in_progress` *before* starting work, `completed` *after* |
| When NOT to Use | trivial single-step tasks, conversational turns — prevents over-planning |
| 4 Use Examples | full worked examples of proper usage |
| 7 Non-Use Examples | full worked examples of when NOT to use it |
| Task States | the three states and transition rules |
| Task Completion | mark complete only when fully accomplished |
| Task Breakdown | items must be specific and actionable |

The behavioral rules (the part that actually changes model behavior):

- **Mark the first task `in_progress` immediately** when creating the list — planning and starting are one motion, never "plan now, start later."
- **Always ≥1 task `in_progress`** unless all are complete — the list is never a passive document; something is always claimed to be underway. (This is our "no dead air" rule's ancestor.)
- **Mark complete immediately after finishing — no batching.** Completion is event-per-step, not a summary at the end. (This is our honest-completion-reporting rule's ancestor.)
- **Multiple `in_progress` allowed if parallel** — the only sanctioned parallelism signal.
- **Specific and actionable items** — "research X" is banned in spirit; "search for X's 2025 revenue in EDGAR" is the bar.
- **Terminal verification step** — the last item is always a review/verify step, not more work.
- **Update at meaningful milestones only** — not after every tool call. (Fights the #1 misuse: the model turning the list into a narrated log.)

This is the strongest field evidence for our own Study-56 finding (behavioral rules beat adjectives): the most successful planning primitive in production AI is not an architecture — it's 213 lines of *do this, don't do that*.

### 2.4 Middleware composition order — planning innermost, approvals outermost [HC]

When `create_deep_agent` builds the stack (from `graph.py`, documented via DeepWiki source analysis):

1. `TodoListMiddleware` — **innermost**, closest to the model
2. Memory, Skills, Filesystem, SubAgent, AsyncSubAgent middlewares
3. Summarization, PromptCaching, PatchToolCalls, ToolExclusion
4. `HumanInTheLoopMiddleware` — **outermost**, wrapping everything

The order is a thesis: planning is intimate with cognition (innermost context); approvals are a perimeter (outermost wrapper). Nothing about the plan can bypass the approval layer because the approval layer *contains* the planning layer. This is the same topology as our Gate-first-statement-of-dispatch — independent convergence, which raises confidence in both. [HC]

### 2.5 Subagent isolation [VC]

Every subagent receives its own `TodoListMiddleware` with an **isolated `todos` list**. Parent and child plans never share a channel — no pollution, no accidental completion-marking across agents. The orchestrator pattern from the deep-research quickstart makes the discipline explicit:

**Plan** (`write_todos`) → **Save** (persist the request) → **Research** (delegate to subagents — the orchestrator NEVER researches itself) → **Synthesize** → **Write** → **Verify**, with hard limits: max 3 concurrent subagents, max 3 delegation rounds, then stop.

### 2.6 Context engineering around the list [HC]

- **FilesystemMiddleware auto-offloads** any tool result exceeding 20K tokens to a file, returning a reference. The plan stays lean because the *evidence* lives on disk, not in context. (Our "brain receives pointers + snippets, never dumps" — same instinct.)
- **Todo content participates in Anthropic prompt caching** — the list is stable context, cheap to re-read.
- **Model-agnostic by construction:** any tool-calling LLM works — frontier APIs, open-weight hosted, or self-hosted via Ollama / vLLM / **llama.cpp**. The local-model path is a documented FAQ answer, not an afterthought. [VC — README FAQ]

---

## 3. Evidence — what 30k stars of field testing revealed

### 3.1 The no-op insight [VC on the claim's existence; HC on its importance]

The single most-quoted design fact about this system (flowtivity.ai, March 2026; llmwatch.com):

> "`write_todos` is essentially a no-op. It does not execute anything. It just writes a todo list into the agent context... it forces the agent to think about what it needs to do before doing it. **This is context engineering, not function engineering.**"

> "Sometimes the best tools are the ones that trick the model into better behavior."

The lesson for JARVIS: the highest-ROI planning component we can build is not a planner — it's a *format the model fills in*. Planning lives in context engineering, enforcement lives in code. The two layers must never be confused.

### 3.2 What it cures — task drift and context fade [HC]

Two independent sources name the disease and the cure:

- **Task drift** (deep-agents-from-scratch notebook): without structure, agents get distracted by tangential findings, forget intermediate subtasks, fail to complete all components, lose the original objective across turns. The todo list fixes all four by making the plan *external* to the reasoning stream.
- **Context fade** (learn-claude-code-rs): the plan exists only implicitly in context → three failure modes: random task switching, forgotten steps, mid-task abandonment. Externalizing the plan into a state channel (not message history) is the fix — the channel survives summarization and compaction that would dissolve an implicit plan.

Both map directly onto our session-store design: the plan as *events*, not as *messages*.

### 3.3 What practitioners report — the good [MC]

- A production user (ariso.ai) switched from the supervisor pattern after "weeks debugging coordination issues": the hierarchical planner with built-in todos produced "more coherent outputs with less boilerplate." The supervisor pattern's failures — shallow routing, context fragmentation, manual orchestration — are exactly what the todo discipline replaces.
- The deep-research quickstart's orchestrator discipline ("delegate, NEVER research itself") is widely copied: separation of planning from execution is the pattern practitioners converge on independently.

### 3.4 What practitioners report — the broken [MC]

- **Cost and complexity in production** (ariso.ai, pre-v1 era): "more expensive and complex than I expected." Planning turns cost a full model call; the middleware stack has real overhead. (Our router's FAST mode exists for exactly this reason — not everything deserves a planning turn.)
- **The v1 upgrade was painful** (breaking changes) — a young, fast-moving API. Pin versions; the 318 releases are velocity *and* churn.
- **Over-planning is the #1 misuse** — models creating todos for trivial tasks, micro-stepping, updating after every tool call. The 7 non-use examples exist because the failure was that common. A format without the *when-not-to* discipline is a tax, not a tool.

---

## 4. The transfer — field-by-field mapping to JARVIS's [C] contract

JARVIS's master-planner spec defines an 11-section plan; the **[C] subset** (objective, strategy, breakdown, dependencies, risks, validation) is the hashed contract. Here is the exact mapping from the todo format onto it:

| deepagents todo element | JARVIS [C] contract element | Notes |
|---|---|---|
| `task` (prose, specific + actionable) | P4 step: action + tool + **expected outcome as observable world-state** | We ADD the expected-outcome field — their prose carries it implicitly; we make it structural (deviation is defined as outcome ≠ expected) |
| `status: pending` | Step proposed, in the approved contract, not yet started | Session event: `plan.step_proposed` (implicit in approval) |
| `status: in_progress` | Step executing — the L2 runner's current step | Session event: `plan.step_started`. Their "always ≥1 in_progress" becomes our no-dead-air rule |
| `status: completed` | Step done AND its P9 checkpoint passed | Session event: `plan.step_completed`. Their "no batching" becomes our event-per-step honest-completion rule |
| Multiple `in_progress` (parallel) | P5 `PARALLEL-OK` marking | Their signal is ad-hoc; ours is declared in the contract's dependency section |
| "Note dependencies in prose" | P5 dependencies as a declared graph | We STRUCTURALIZE what they leave as prose — the L2 runner reads the graph, not the sentence |
| "Note which items need special tools/subagents" | P4's tool field + subagent delegation notes | Direct adoption |
| Terminal verification step | P9 validation checkpoints | Their convention becomes our enforced checkpoint: the plan is not complete until the verification step's assertions pass |
| 3+ steps → use; <3 → don't | Our router: ≥3 predicted tool calls → PLAN mode | Already convergent — no change needed |
| "Update at meaningful milestones" | Deviation-voids: the model may not silently adapt | We go further: unlisted steps VOID the contract (theirs allows ad-hoc additions) |
| Whole-list replacement | Contract re-issue: any plan change = new hash, new approval | Their mechanism (replace whole list) is the right one — partial edits create ambiguity. We add: re-issue requires re-approval |
| At-most-once-per-turn guard | L2 runner owns state transitions; the plan-write tool is proposal-only | Borrow the guard verbatim — it's deterministic and correct |

**The one-line transfer:** deepagents gives us the *shape of the contract* (bounded steps, concrete items, lifecycle states, terminal verification); JARVIS adds the *enforcement* (hash, deviation-voids, tier re-lookup, event log).

---

## 5. The gap — the enforcement layer their trust model forbids

Their README, verbatim: *"Deep Agents follows a 'trust the LLM' model. The agent can do anything its tools allow. Enforce boundaries at the tool/sandbox level, not by expecting the model to self-police."* [VC]

This is honest and correct *for a framework* — but it is the exact opposite of JARVIS's architecture, and the borrow must stop at the format. The enforcement layer JARVIS wraps around the borrowed shape:

1. **Contract hash at approval.** Their list is prose in state; ours is the [C] subset, hashed. The hash is what the L2 runner checks against — not the model's memory of the plan.
2. **Deviation-voids.** Before each step: does the step's actual action and expected outcome match the contract? Mismatch → VOID → stop → ask. Their middleware permits ad-hoc plan adaptation; ours treats unlisted steps as a contract violation.
3. **Tier re-lookup from the manifest, never the plan.** A step the plan calls tier-2 that the gate reads as tier-3 is re-tiered at execution. The plan's tier labels are advisory; the manifest is authority.
4. **Tier-3 steps are scheduled, never authorized.** Plan approval covers tiers 1–2 only; every tier-3 step still gates individually at execution time. (Their HITL middleware pauses per tool call — convergent on the *mechanism*, but ours binds the approval to the action hash with 10-minute expiry.)
5. **The plan-write tool is proposal-only.** In their system the model writes the list and then follows it. In ours, the model proposes the list; the L2 runner (deterministic code) owns all state transitions. The model can no more mark a step complete than it can approve its own tier-3 action.
6. **Stale-plan re-validation.** Their plans have no age. Ours: >30 minutes since approval → re-validate before executing (the β condition from multi-scale).

**What we never borrow:** the idea that the model's good intentions are a security boundary. The format is pedagogy; the enforcement is architecture. Confusing the two is how "trust the LLM" becomes "the LLM was tricked."

---

## 6. Limitations — honest [HC]

1. **No conditional branches.** The list is linear. "If the file exists, do A; else do B" has no representation — practitioners either write both branches as separate items (wasteful) or let the model improvise (unverifiable). Our P8 (edge cases + contingencies) covers the common branches; true branching stays a research item.
2. **No join semantics for parallel steps.** Multiple `in_progress` is allowed, but there is no "wait for all of these before that" — the model improvises the join. Our P5 declares the DAG; the L2 runner enforces the join.
3. **Completion is self-reported.** The model marks its own homework — the discriminator problem in miniature. Their mitigation is the terminal verification step (a convention). Ours is P9 deterministic checkpoints (a mechanism). Conventions rot; mechanisms hold.
4. **Over-planning is endemic.** 7 non-use examples exist because models chronically over-plan. The description fights it with rules, but the failure persists in the field. Our router's FAST default (voice → FAST always; <3 steps → FAST) is the structural answer: the *default* is no plan.
5. **The list can grow unbounded.** No compaction rule in the middleware — a 200-step plan is 200 items in state. Our session-store compaction (5,000-event trigger, summaries + archives) bounds it.
6. **No provenance on items.** Who added step 7, and why? The list doesn't say. Our session events (`plan.step_proposed` with causal_parent) answer it.
7. **Young, churning API.** 318 releases since July 2025 — pin versions, expect breakage. Borrow patterns, not dependencies.

---

## 7. The 5 most important patterns — implementable

**P1. The no-op planning tool.** Build the plan-writing tool as pure context engineering: it writes to state, executes nothing. Put the entire planning discipline in its description — 200+ lines of *when to / when not to / how*, with worked examples and non-examples. This is the highest-ROI planning component: a format, not a planner. *Implement from:* the section table in §2.3 — reproduce all eight sections, adapted to the [C] contract fields.

**P2. Whole-list replacement + at-most-once-per-turn.** The plan is always replaced whole, never patched; the write tool is structurally limited to one call per turn. This kills an entire class of ambiguity bugs (which edit won?) with ~5 lines of code. *Implement from:* §2.1(4) + §4 table row — verbatim.

**P3. Planning innermost, approvals outermost.** Order the pipeline so the planning layer sits closest to the model and the approval/gate layer wraps everything — nothing planned can execute without passing through the perimeter. *Implement from:* §2.4 — the middleware order is the architecture diagram.

**P4. Subagent plan isolation.** Every subagent gets its own plan channel; parent and child plans never share state. A subagent cannot mark parent steps complete, and parent replans never silently rewrite a child's list. *Implement from:* §2.5 — one channel per agent, enforced by the runner.

**P5. Terminal verification + observable outcomes.** Every plan ends with a verification step (not more work), and every step carries its expected outcome as an observable world-state ("the file exists at X with sections A–C"), never as effort ("work on the report"). Deviation is then *defined*: outcome ≠ expected. *Implement from:* §2.3 (terminal step rule) + §4 mapping row 1 — this is the field our contract adds to their format, and it's the one that makes deviation-voids computable.

---

## 8. Confidence, scope, and the honest bottom line

**[VC]:** repo identity, stars, MIT license (read live); the README's "trust the LLM" statement (verbatim); the middleware's four functions; the at-most-once-per-turn guard; subagent isolation; model-agnostic local support (Ollama/vLLM/llama.cpp); the no-op characterization (multiple independent practitioner sources).
**[HC]:** the 213-line description's section breakdown and behavioral rules (via DeepWiki source analysis — the file itself 404'd on the restructured path; sections cross-checked across two DeepWiki pages and the docs); the middleware composition order (via DeepWiki graph.py analysis); the field-failure reports (ariso.ai is pre-v1 era; flowtivity/llmwatch are practitioner press, not controlled studies).
**[MC]:** exact current line counts and defaults (the repo moves fast — 318 releases; verify at build time); the depth of the orchestrator pattern's field adoption.
**[UK]:** whether the 213-line description survives compression to smaller models (does a 4B model follow it as well as a frontier model? — directly relevant to our tier-0 planner question, unmeasured).

**What this PhD does NOT establish:** that the todo format is optimal (it's the most *field-tested*, not the most *tested* — no controlled comparison against alternatives was found); that 30k stars means 30k production users (stars are interest, not deployment); anything about the JS/TS implementation beyond the shared architecture.

**The honest bottom line:** deepagents proved that planning is a *format discipline* plus *structural guards*, and that the two must live in different layers. JARVIS's master-planner spec already had the right shape — this PhD supplies the field evidence that the shape works, the exact format to steal, the exact trust model to refuse, and five patterns precise enough to implement from. The todo list plans; the gate enforces; never the reverse.
