# PhD: pydantic-ai's Planning Capability — the plan as a shared typed store

*LEARNING ONLY — no project files touched, no installs, no code executed. Date: 2026-10-19.*
*Subject: `pydantic/pydantic-ai` (MIT verified, 20,726 stars, 4,320 commits, 343 releases) — the `Planning` capability in `pydantic-ai-harness`.*
*Primary sources: the official Planning docs (pydantic.dev/docs/ai/harness/planning, read in full), the repo's own README and file tree (read), community coverage (duklee.net, PyPI). NOT read: the raw `planning/*.py` source files (fetch 404'd on the monorepo path) — mechanism below is from the official docs, which are unusually detailed and internally consistent. Flagged where it matters.*

## Plain-words summary

Pydantic's Planning capability solves one problem: long agent runs drift, and the usual fix (pasting the plan into the system prompt every turn) destroys the prompt cache — every plan edit changes the cached prefix, so the whole conversation gets re-processed at full token price.

Their answer: the model owns the plan through six small tools (`write_plan`, `read_plan`, `add_task`, `update_task_status`, `remove_task`...). The current plan is whispered back to the model as a short reminder at the *end* of each request — never written into the permanent history, never touching the cached system prompt. The plan can live in memory or in SQLite/Postgres/Redis.

The killer pattern: **two different agents can share one plan through the store alone.** A big model investigates and writes the plan; a small cheap model executes it, starting with zero history — it never pays for the big model's thinking. The plan is the *only* state that crosses between them.

What JARVIS steals: the plan-as-shared-store, whole-plan replacement (no fragile numbered steps), typed plan events with before/after states, and the fail-loud store. What JARVIS must add: the part they don't have — **the plan as an enforced contract** (hash it at approval; any mismatch voids it and stops work). Their trust model is "the model will follow the plan"; ours must be "the code checks the plan."

**Outcome label (Domain XI):** our adaptation = *new combination of known techniques*. The capability itself = *experimentally supported* in production use, but with no controlled benchmark of the planning mechanism itself that I could find.

---

## 1. The mechanism, in depth

### 1.1 The problem it solves (and why the naive fix is expensive)

Long agentic runs drift: the model forgets what it set out to do. The naive fix is keeping a running plan and re-injecting it into the system prompt each turn. The docs explain exactly why this is expensive [VC — from the official docs]: the system prompt sits at the *front* of the request, so every plan edit changes the cached prefix, and the entire conversation is re-processed at full token price. The cost isn't the plan's tokens — it's the *invalidation* of everything cached after it.

### 1.2 The solution: model-owned plan + ephemeral tail reminder

- The model owns the plan through the `planning` toolset. Static usage guidance goes in the system prompt (cache-stable, written once).
- The *current plan* is surfaced back as an **ephemeral reminder appended to the tail of each request**, led by the capability's single cache breakpoint (`CachePoint`).
- The reminder is added **after** the durable history is persisted: it reaches the model but is **never written to `message_history`**. No reminders accumulate across turns. [VC]
- The `CachePoint` attaches to the content right before the reminder (last user prompt, or latest tool result in a tool loop). On Anthropic/Bedrock/OpenAI, each request reads the previous request's prefix back from cache — tool results included — and only the reminder travels uncached. Provider mapping applies (OpenRouter attaches to the previous user message; Google's models ignore explicit breakpoints). [HC — docs are precise here; the provider-specific behavior is stated as mapping rules, not benchmarks]

This is the deep insight: **separate the cache-stable (guidance) from the mutable (plan) at the protocol level**, not by convention. The architecture makes the cheap thing (static guidance) cached and the changing thing (plan) cheap-to-resend, instead of asking the model to be careful.

### 1.3 The toolset

| Tool | Purpose |
|---|---|
| `write_plan(items)` | Create or **replace the full plan** (whole-list replacement) |
| `read_plan()` | Read current plan with step ids + progress summary |
| `add_task(content, active_form)` | Append a single `pending` step |
| `update_task_status(task_id, status)` | Move one step between statuses by id |
| `update_task_statuses(updates)` | Batch status changes, validated all-or-nothing |
| `remove_task(task_id)` | Delete a step by id |

Each step: a `content` string, an optional present-continuous `active_form` label ("Refactoring the auth module"), and a `status` (`pending`, `in_progress`, `completed`, `cancelled`). Convention: exactly one step `in_progress` at a time.

**Whole-plan replacement is the load-bearing design choice** [HC]: addressing steps by mutable integer index (insert/remove/reorder) is error-prone for *both* the code and the model. `write_plan` restates the whole plan each call — no indices to track. Granular edits reference the **stable `id`** from `read_plan`. This kills an entire class of "step 3 of what?" bugs. JARVIS's contract sections should work the same way: restate, don't patch.

With `enable_subtasks=True`: three more tools (`add_subtask`, `set_dependency`, `get_available_tasks`), the `blocked` status, and a hierarchical view. Dependencies are real: the dependent step auto-`blocked` until its prerequisite resolves; self-dependencies, cycles, and duplicates are **rejected by the store** (validation in the storage layer, not the model — note this, it's the one place they put enforcement in code). [VC]

### 1.4 The stores

`InMemoryPlanStore` (default, fresh isolated plan per run), `SqlitePlanStore` (file-backed; `SqlitePlanStore('plan.db', session='issue-403')`), `PostgresPlanStore` (over a caller-owned asyncpg pool), `RedisPlanStore` (caller-owned redis client). `PlanStore` is a **protocol** — any implementation works, `store_resolver` picks per run, and you can wrap one (the docs show a `BestEffort` wrapper sketch).

Two details that matter for JARVIS:
1. **`SqlitePlanStore` keeps its DB on the machine running the agent, not in the workspace.** The plan store is infrastructure state, not work product — exactly our session-store placement rule (`%APPDATA%`, never the repo). [VC]
2. **Fail-loud, not fail-soft:** the tail reminder reads the store on *every* model request, so a store that raises **fails the run rather than degrading**. The docs state this is deliberate: *"a plan the model can no longer see is not a state to continue running in silently."* Retry/fallback policy belongs to the store, not to `Planning`. This is the honest-design pattern our reliability spec demands — adopt it verbatim. [VC]

### 1.5 The planner/executor split — the headline pattern

```python
store = SqlitePlanStore('plan.db', session='issue-403')
planner  = Agent('anthropic:claude-opus-5-5',  capabilities=[Planning(store=store)])
executor = Agent('anthropic:claude-sonnet-5-5', capabilities=[Planning(store=store)])
await planner.run('Investigate the issue and write a plan. Do not implement anything.')
await executor.run('Implement the plan.')
```

- The **shared store is the whole handoff mechanism**. One agent writes the plan, a second executes it; the plan is the *only* state that crosses between them. [VC]
- The executor starts with **no `message_history`** — it never pays for the planner's investigation. Its first request carries only the new prompt plus the plan reminder, rebuilt from the store.
- That's why the two agents can run on **different models**: a large-context model does the reading and reasoning; a smaller one executes against the checklist. For JARVIS: the cloud/tier-2 brain can plan, the local 7B executes — the cost math of our three-tier architecture applied to planning. [HC — the mechanism is verified; the JARVIS cost application is our derivation]
- **The planner's read-only discipline is configuration, not enforcement:** "a property of how you configure that agent (which toolsets it gets, and what its instructions say), **not something the capability enforces**." The docs say this plainly. It is the honest statement of the trust-model gap (§4). [VC]

### 1.6 The typed events

Subscribe via `@agent.on_event(PlanCompletedEvent)`. The family: `PlanCreatedEvent`, `PlanUpdatedEvent`, `PlanStatusChangedEvent`, `PlanCompletedEvent`, `PlanDeletedEvent`. Each carries the affected **`item`** and, for updates, **`previous_state`** — before/after on every mutation. [VC]

Two subtleties:
- Run events come from **planning tool paths** (including `write_plan`). **Direct application mutations on a `PlanStore` have no run context and do not produce run events.** Translation: if you bypass the tools and write to the store directly, the audit trail goes blind. For JARVIS: the supervisor/gate must be the *only* writer besides the tool path, or events lie by omission. [HC]
- `PlanEvent` carries **no `timestamp`** — a consumer that orders or logs by time supplies its own clock. (Noted for our event envelope: we already have `seq` as the ordering authority — strictly better.) [VC]

### 1.7 Durable execution integration

With a durable-execution capability attached, every plan store call is a **journaled** operation: the plan read used to build the reminder, each read/write the tools make. **Replay reuses the recorded result instead of calling the store again** — recovering a run doesn't append a step to a persistent store a second time. `Planning` carries the stable default `id='planning'` so durable recovery works without configuration. [HC — from the docs; matches our session-store replay rule "reduce, never re-emit"]

### 1.8 Configuration surface

`Planning(guidance, cache_ttl='5m', store, enable_subtasks, inject=True, tools, descriptions)` — plus `tools=` allowlist narrowing (e.g., `Planning(tools=['write_plan'])` for whole-plan-replacement-only, no step ids to track) and YAML/JSON agent specs. The allowlist-narrowing is the same move as our skill manifest: declare the surface, shrink it per use. [VC]

---

## 2. Evidence: what's proven vs claimed

**Verified facts** [VC — repo metadata read directly]:
- 20,726 stars, 4,320 commits, 343 releases, created 2024-06-21, MIT license, by the Pydantic/Logfire team (David Hewitt et al.) — the most credible maintainer group in the Python AI ecosystem.
- The Planning capability **supersedes the standalone `pydantic-ai-todo` library** (tools renamed: `write_todos`→`write_plan` etc.) — the pattern survived contact with real users and got promoted into the official harness.
- It ships inside the `Coder` and `Researcher` combined harnesses — i.e., it is the planning layer of their own coding agent, dogfooded.
- 50+ capabilities in the harness; Planning is one of the core orchestration primitives alongside Subagents and Dynamic Workflow.
- Community alternatives orbit it (vstorm-co's subagents/pydantic-deep, DougTrajano's skills) — ecosystem validation of the *problem space*, not of this capability specifically.

**Honest gaps** [UK — searched, not found]:
- I found **no published controlled benchmark of the Planning capability itself** — no "plan-first vs ReAct on task suite X, measured by the pydantic team." The practitioner figures sometimes quoted (85% vs 92%) come from outside sources, not from pydantic.
- Adoption *of the planner/executor split specifically* (two models, shared store) is documented as a pattern in the docs, but I found no public case study with measured cost/quality numbers. The cost claim ("executor never pays for the planner's investigation") is **structurally true** (zero history = zero tokens — arithmetic, not a study) but the *quality* claim (small model executes as well from a checklist) is asserted, not measured. [HC on the structure point; UK on the quality point]
- The harness is on **0.x releases** — the docs warn the API may change between minors (with deprecation warnings + migration guidance). For JARVIS: borrow the *patterns*, don't pin the *dependency* — especially since v2's plan model needs the enforcement layer anyway.

---

## 3. The transfer: event-by-event mapping onto JARVIS's session store

Our plan events (from learn-master-planner.md / session-store): `plan.proposed`, `plan.approved`, `plan.step_completed`, `plan.step_failed`, `plan.voided`, `plan.completed`, `plan.died`.

| pydantic-ai event | JARVIS event | Mapping notes |
|---|---|---|
| `PlanCreatedEvent` | `plan.proposed` | A plan now exists. In JARVIS it enters **awaiting-approval**, not active — the approval gate is the step pydantic-ai doesn't have. The event carries the full plan content (their `item`); we hash the [C] sections at this point and store the hash alongside. |
| `PlanUpdatedEvent` (content change, pre-approval) | *(no event — working paper)* | Edits before approval are drafting. In JARVIS these mutate the draft without emitting session events (or emit to a draft-scoped log only). **Critical:** an update *after* approval is not an update — see next row. |
| `PlanUpdatedEvent` (content change, post-approval) | `plan.voided` | **This is the core divergence.** Pydantic-ai treats post-hoc plan edits as normal. JARVIS treats any content change to the approved [C] sections as **contract void** → stop → ask the user. The `previous_state` they carry becomes our forensic evidence: *what* changed, shown to the user in the void notice. |
| `PlanStatusChangedEvent` (pending→in_progress) | *(implicit in step lifecycle)* | Their status transitions are bookkeeping. Ours: a step starting is not session-worthy; only outcomes are. We keep their `item`+`previous_state` shape for the transitions we do record. |
| `PlanStatusChangedEvent` (→completed) | `plan.step_completed` | Direct map. Ours additionally records the **verification evidence** (the world-state assertion that proved it — "verify outcomes, not motion"), which theirs doesn't require. |
| `PlanStatusChangedEvent` (→cancelled/failed) | `plan.step_failed` | Their model is binary-ish (cancelled); ours distinguishes failed (attempted, didn't work — feeds the retry/escalation logic) from cancelled (deliberately dropped). |
| `PlanCompletedEvent` | `plan.completed` | Direct map. Ours requires the P1 success criteria check (the falsification of "done") before emitting. |
| `PlanDeletedEvent` | `plan.died` | Their deletion = plan removed. Ours: `died` = removed without completing (user-deleted, superseded, or run abandoned). `voided` is separate: killed *by the enforcement layer* for deviation. The distinction matters for the failure DB: voids are security-relevant, deaths usually aren't. |

**What ours has that theirs lacks** (the enforcement delta):
- `plan.approved` — the approval gate. Their capability has no approval concept (their Approval workflows are a separate in-progress PR). Every JARVIS plan transitions proposed→approved via the tier-3 dialog; the approved hash is the contract.
- `plan.voided` — structural deviation-void. Their events are **observational** (they tell you what happened); ours are **normative** (they define what may happen next). This is the entire gap, and it's architectural, not incremental.

---

## 4. The gap: designing what JARVIS adds (contract hash + void-on-mismatch)

### 4.1 Why their trust model is insufficient for us

The docs are admirably honest: *"The planner's read-only discipline is a property of how you configure that agent (which toolsets it gets, and what its instructions say), not something the capability enforces."*

That sentence is the whole gap. Their model: **the model will follow the plan** (a property of instructions). Our requirement (threat model, R2/R3, fault-tree B5): **the code checks the plan** (a property of the system). An instruction-following plan is a *convention the model can ignore* — under prompt injection, under confusion, under a drifted long run. For a personal assistant with full PC control, "the model usually follows the plan" is not a security boundary. [HC]

### 4.2 The contract-hash design

At `plan.approved`:
1. Serialize the [C] sections (objective+success criteria, strategy, breakdown with per-step expected outcomes, dependencies, risks+mitigations, validation checkpoints) in canonical form (sorted keys, fixed encoding).
2. `contract_hash = sha256(canonical)` — stored in the session store alongside the `plan.approved` event, plus the approver identity (user) and timestamp.
3. The *live* plan in the working store may still be edited by the model (drafting, re-planning) — but the **L2 runner never reads the live plan for authorization**. It reads the hashed contract.

Before each step executes, the L2 runner checks (deterministic code, not the model):
- Does this step's *action* match the contract's expected action for this step id? (tool name + argument schema shape — not exact args, which may legitimately vary, but the *kind* of action)
- Does the previous step's *outcome* match the contract's expected outcome? (world-state assertion, not "I clicked")
- Is the tier of this step ≤ the tier the contract declared? (tier escalation = void, always)

Any mismatch → emit `plan.voided` (with the expected-vs-actual diff, using their `previous_state` pattern as the evidence format) → halt at the next atomic boundary → ask the user. Not "adapt silently." Stop. [DESIGN — proposed, unbuilt]

### 4.3 Why hashing, not just comparing to the live plan

Because the model *owns* the live plan in pydantic-ai's design — it can `write_plan` a new version at any time. If the runner compared against the live plan, a confused or injected model could rewrite the plan to authorize whatever it's about to do — the plan becomes a rubber stamp. The hash freezes the *approved* version outside the model's reach. The model may propose a new plan (→ `plan.proposed`, → re-approval); it may never silently amend the contract. This is the structural version of their "whole-plan replacement": replacement is fine, but only through the approval gate. [HC]

### 4.4 What we deliberately do NOT copy

- **Their cache-breakpoint machinery as-is.** The `CachePoint` dance is provider-specific (Anthropic/Bedrock/OpenAI explicit breakpoints; Google ignores them). Our local tier runs on llama-server, where the KV-cache economics differ: there's no cross-request provider cache to protect in the same way. The *pattern* (static guidance cached, mutable plan resent cheaply) transfers; the *mechanism* needs a local-tier variant — and on the 2060 the win is architectural cleanliness more than token savings. Don't cargo-cult the CachePoint. [HC]
- **Their 0.x API surface.** Pin patterns, not the package. The capability is young and the API moves between minors.

---

## 5. Limitations: what doesn't transfer / breaks at our scale

1. **Scale mismatch (in our favor, mostly).** Their stores target multi-agent SaaS (Postgres/Redis, caller-owned pools). Ours is single-user, single-machine: SQLite WAL is the whole story. Simpler — but we must not import their distributed-systems complexity. Take `SqlitePlanStore`'s *shape* (file-backed, session-scoped, protocol-based), leave the pool machinery. [HC]
2. **No approval workflow.** Their approval story is a separate in-progress PR (#173). Our tier-3 dialog is load-bearing and must be built, not borrowed. [VC — from the PyPI roadmap table]
3. **Direct store mutations are event-blind.** Their docs warn: mutations bypassing the tool path produce no run events. In JARVIS the supervisor writes checkpoints and the gate writes approvals — *every* writer must go through the event-emitting path, or the audit trail lies by omission. This is a hard implementation rule, not a suggestion. [HC]
4. **The executor-trusts-checklist quality claim is unmeasured.** "A smaller model executes as well from a checklist" is structurally plausible and economically attractive (our tier-2-plans/tier-1-executes split), but I found no measurement. Our discriminator protocol (Cycle 7) should cover executor fidelity before we rely on it for tier-3-adjacent work. [UK → flagged as a measurement task]
5. **Python-sidecar fit is good** (it *is* Python — unlike eino's Go), but the capability assumes the Pydantic AI agent loop. Our v2 brain is a custom loop (Tauri + Python sidecar); we take the store/event/checkpoint patterns, not the `Agent(capabilities=[...])` scaffolding. Transplant the organs, not the body. [HC]
6. **Their fail-loud store assumes an operator.** "Fails the run rather than degrading" is correct — but in JARVIS the "operator" is Owais, who needs the plain-words version ("I lost sight of the plan, so I stopped") not a traceback. The UX wrapper is ours to build. [HC]

---

## 6. The 5 most important code-level patterns (implementable)

**P1. Plan-as-shared-store (the handoff).** Planner and executor share *nothing* except the store. The executor starts with empty history; its context is assembled from the store alone. Implement: a session-scoped plan table (`plan.db` per session, on the machine not the workspace); a `build_executor_context(store, session)` function that returns prompt + plan reminder and *nothing else*. The cost win is arithmetic: zero history = zero tokens. Different models may plan vs execute — for us, cloud plans / local executes.

**P2. Whole-plan replacement over indexed mutation.** `write_plan(items)` restates the entire plan; granular edits (`add_task`, `update_task_status`) reference stable string ids from `read_plan`, never integer positions. No "step 3" — only `task_id`s. This kills index-drift bugs for the model and the code alike. Our contract sections follow the same rule: restate, don't patch; amend only via re-approval.

**P3. Ephemeral tail reminder (cache-safe surfacing).** The plan is re-attached per request *after* durable history is sealed — it reaches the model but is never persisted into history. Static guidance lives in the system prompt (written once, cache-stable); the mutable plan rides the cheap tail. Implement as: `seal_history()` → `attach_plan_reminder(request, store.read())`. Even without provider prompt-caching, this keeps history clean and the plan always current.

**P4. Typed events with (item, previous_state).** Every plan mutation emits a typed event carrying the affected item *and* its previous state. This is the audit spine: `PlanCreated/Updated/StatusChanged/Completed/Deleted` → our `plan.proposed/approved/step_completed/step_failed/voided/completed/died` (§3 table). Before/after on every mutation is what makes "what changed?" answerable — and it's the evidence format for `plan.voided` notices.

**P5. Store-as-protocol + fail-loud.** `PlanStore` is a Protocol (wrappable, swappable: memory → SQLite → Postgres without touching the capability). And: a store that can't serve the plan **fails the run loudly** — never silently continues plan-blind. Implement the wrapper seam from day one; implement the fail-loud as a startup/runtime assertion with the plain-words user message, not an exception dump.

---

## 7. Confidence & honest scope

- **[VC]:** repo metadata (MIT, 20,726★, 4,320 commits); the cache-invalidation problem statement; the toolset and its semantics; whole-plan-replacement rationale; the store family and protocol design; the planner/executor split mechanics (zero-history executor, shared-store-only handoff); the typed event family with (item, previous_state); the fail-loud store rule; "read-only discipline is configuration, not enforcement" (their words).
- **[HC]:** the CachePoint provider-mapping details (precise in docs, provider behavior may drift); the durable-execution journaling interaction; the transfer mapping (§3 — our event model is designed, theirs is documented, the join is my synthesis); the contract-hash design (§4 — proposed, unbuilt); the local-tier cache-economics caveat.
- **[MC]:** that the executor-quality claim holds for our model pairs (unmeasured); exact 2060 cost deltas of the split.
- **[UK]:** any controlled benchmark of the Planning capability itself; adoption numbers for the planner/executor split specifically; the raw `planning/*.py` source (fetch failed — mechanism rests on the official docs).
- **Outcome label (Domain XI):** the capability = *experimentally supported* (production dogfooding, ecosystem adoption) without a controlled benchmark I could find; our adaptation (contract hash + void-on-mismatch + approval gate) = *new combination of known techniques*, unvalidated until built.

*End of PhD. Status: research complete as a document; unimplemented by intent (learning phase). The next step is Owais's go-ahead — and when the build comes, §6 is the implementation order.*
