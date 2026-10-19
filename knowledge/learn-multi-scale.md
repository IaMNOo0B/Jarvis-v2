# Multi-Scale Intelligence — Coordinating Five Clocks Without the Slow Ones Hijacking the Fast Ones

*PHASE OMEGA ∞+1, Domain X. Design document, not code. LEARNING ONLY — no project files touched, no installs, no code executed.*
*Date: 2026-10-19.*

**Sources:** `learn-session-store.md` (supervisor as separate fate domain, `wake(sessionId)`, event log), `learn-proactivity-spec.md` (routines as contracts, interruption budget, DND), `learn-control-theory.md` (cascade control, rate separation, "what stops this oscillating?"), DECISION-PLAYBOOK.md (S1–S8, A1–A9, R2/R3), `learn-fault-trees.md` (B1–B11), web: options framework (Sutton/Precup/Singh 1999), subsumption architecture (Brooks 1986).

---

## Plain-words summary

JARVIS thinks on **five clocks at once**: reflexes (milliseconds), single tasks (seconds), multi-step plans (minutes), long-term objectives (days), and a supervisor watching all of them. The danger: the slow clocks quietly taking over — a week-old objective overriding what you just said, a stuck plan burning through your afternoon.

The fix has one sentence: **authority flows upward to the fast, actions flow downward from the slow.** Your new instruction (fast) always beats an old plan (slow). And slow layers can never *act* — they can only *suggest*, and every suggestion is re-checked against your latest words at the moment it would act. A long-term goal overriding you isn't just discouraged; the code has no path for it to happen.

---

## 1. The five layers — precisely

| Layer | Name | Timescale | What it does | What it emits | Brain? |
|---|---|---|---|---|---|
| **L0** | Reflexes | ms–seconds | Echo guard, barge-in, circuit breakers, watchdog, DND checks | Control signals (stop, gate, skip) | **No** — deterministic code only |
| **L1** | Tasks | seconds–minutes | One user request = one ReAct task: propose → gate → act → verify | `tool.call` events (the ONLY layer that can) | Yes |
| **L2** | Workflows | minutes–hours | Multi-step plans under a plan contract (proactivity §4 routines live here) | Task *requests* (never actions) | Yes (plans), code (contract checks) |
| **L3** | Objectives | days–weeks | User-approved objectives: goals, standing routines, foresight candidates | *Proposals* (never actions, never task requests) | Yes (proposes), code (contract hash) |
| **L4** | Supervisor | continuous | Preemption broadcast, budget enforcement, termination verdicts, `wake()` | Preemption signals, budget grants | **No** — deterministic code only |

**Two load-bearing facts about this table:**

1. **Only L1 emits actions.** L2 emits task *requests* (which L1 may propose to the Gate). L3 emits *proposals* (which L2 may turn into plans, which become task requests). There is no code path from L2/L3 to the actuator. This is the structural core of the non-override guarantee (§2). [VC — derived from R2/R3, skill-spec dispatch]
2. **L0 and L4 are brain-free.** The layers that can *stop* things (L0) and *judge* things (L4) never consult the model. A stop signal that requires the brain's cooperation is not a stop signal — it's a suggestion the brain can ignore. (Source: fault-trees B5 — "brain evasion defeats the gate"; the fix is the same shape.) [VC]

### The diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ L4 SUPERVISOR — event-driven, deterministic, separate fate      │
│  owns: preemption broadcast · budgets · termination verdicts    │
│  never: emits actions · calls the brain · holds turn state     │
└────────────────────────┬────────────────────────────────────────┘
                         │ preemption signals (control plane —
                         │ bypasses judgment entirely)
                         │ budget grants · termination verdicts
┌────────────────────────▼────────────────────────────────────────┐
│ L3 OBJECTIVES (days–weeks) — user-approved CONTRACTS            │
│  emits: PROPOSALS only                                          │
│  every proposal re-hashed against the approved contract text    │
└────────────────────────┬────────────────────────────────────────┘
                         │ proposal → L2 decomposes into a plan
┌────────────────────────▼────────────────────────────────────────┐
│ L2 WORKFLOWS (minutes–hours) — plan CONTRACTS                   │
│  emits: TASK REQUESTS only (each re-validated at L1)            │
│  deviation from plan → contract VOID → stop, ask                 │
└────────────────────────┬────────────────────────────────────────┘
                         │ task request → L1 → THE GATE → action?
┌────────────────────────▼────────────────────────────────────────┐
│ L1 TASKS (seconds–minutes) — the ONLY action emitter            │
│  every tool.call re-checked vs LATEST user.message + DND + gate │
└────────────────────────┬────────────────────────────────────────┘
                         │ tool results flow back up as evidence
┌────────────────────────▼────────────────────────────────────────┐
│ L0 REFLEXES (milliseconds) — deterministic, brain-free          │
│  echo guard · barge-in · circuit breakers · watchdog · DND      │
└─────────────────────────────────────────────────────────────────┘

        AUTHORITY FLOWS UP (fast preempts slow)
        ACTIONS FLOW DOWN (slow proposes, fast disposes)
```

**Rate separation** (control-theory study, [HC]): adjacent layers are separated by ~10× in characteristic time (ms → s → min → hr/day). This is the cascade-control rule (3–5× minimum): without separation, layers interfere and oscillate. The task's own question — "what stops this oscillating?" — is answered by the separation plus explicit termination (§3).

---

## 2. The non-override guarantee — a mechanism, not a wish

**Theorem (structural):** No L3 objective and no L2 workflow can cause an action that contradicts the user's latest instruction, a safety boundary, or a permission constraint — not because the model is told not to, but because the code paths don't exist.

**Three preemption rules (all enforced in deterministic code):**

### Rule 1 — Slow layers cannot emit actions (capability removal)

The action-dispatch function (`dispatch(tool, args)` in the skill spec's pipeline) is reachable **only** from the L1 task-executor code path. L2's plan runner and L3's objective loop hold no reference to it; they hold references to *proposal queues*.

- L3 wanting something done → writes a proposal to L2's inbox. That's all it *can* do.
- L2 wanting a step done → writes a task request to L1's inbox.
- L1 → proposes to the Gate → Gate approves → dispatch.

If a compromised or drifted L3 "decides" to delete a file, the decision is a JSON blob in an inbox. There is no function it can call to make it happen. **This is S5 (filesystem jail) applied to the architecture itself: the jail isn't around the filesystem, it's around the actuator.** [VC]

### Rule 2 — The Gate re-validates at execution time (freshness)

Every `tool.call` is checked at L1 dispatch against **current** state, not plan-time state:

1. The latest `user.message` event (session store) — a plan approved 10 minutes ago that conflicts with what the user just said is refused. The Gate reads the log, not the plan's memory of the log.
2. Safety boundaries (S1–S8): instruction hierarchy, capability grants, tier lookup — recomputed, not cached.
3. DND + degradation state (proactivity §2, reliability ladder): a workflow step that was fine yesterday but the user is now in a meeting / the system is degraded gets held.

**Consequence:** a stale long-term instruction is structurally incapable of overriding a fresh immediate one, because the fresh one is always an input to the decision and the stale one never is — except as a *proposal* the Gate may reject. [VC — derived from R3 "gate is the first statement of dispatch" + session-store causal spine]

### Rule 3 — Preemption is a signal, not a request (control plane)

User interrupt (new message, STOP button, wake-word during TTS, Ctrl+C equivalent) is delivered as a **preemption signal** that the supervisor broadcasts on the control plane. It does not go through the brain:

- **L0** (ms): barge-in halts TTS; watchdog trips. No judgment involved.
- **L1** (bounded, ≤2s): the in-flight tool call gets an abort window — finish the current *atomic* step (atomic writes: it lands or it doesn't, never half), then stop. Partial results checkpoint to the session store.
- **L2** (seconds): workflow suspends; plan state checkpointed; status → `SUSPENDED`. Does NOT auto-resume.
- **L3** (seconds): objective marked `INTERRUPTED — awaiting user`. Does NOT auto-resume. Ever.

**The brain is informed of preemption, never asked.** "The brain doesn't get to decide whether to honor STOP" — this is the fault-tree B5 fix generalized: any safety mechanism that routes through the component it's meant to constrain is decoration. [VC]

### What "silently" means, and why it's impossible here

"Silently override" requires three things: (a) a path to act, (b) stale authority beating fresh instruction, (c) no record. The design removes all three: (a) Rule 1 removes the path; (b) Rule 2 makes fresh instruction always win; (c) every proposal, task request, gate decision, and preemption is a session-store event (the audit trail from §6 of the session spec answers "did my old objective cause that?"). [HC]

---

## 3. Termination conditions — the β for every layer

Borrowed from the options framework (Sutton, Precup & Singh 1999: an option is `(I_ω, π_ω, β_ω)` — initiation set, policy, **termination condition**; verified via search results above): every temporally-extended behavior carries an explicit, checkable β. JARVIS's layers are options; here are their β functions. **Borrow the termination discipline, not the RL machinery** — the hierarchy is designed, not learned (full HRL/option-critic is overkill for a single-user desktop agent; §6).

| Layer | Terminates when (β) | Who checks | On termination |
|---|---|---|---|
| **L0** | Guard condition clears OR reflex completes (echo guard: TTS stopped; circuit breaker: probe succeeds) | The reflex itself (deterministic) | Silent return; event logged |
| **L1** | Task complete · task failed (2-attempt rule → escalate, per Debugging Decay) · user interrupt · turn budget exhausted (3 rounds/12 calls, skill spec) · supervisor preemption | L1 executor + supervisor | Result or escalation to user; partial state checkpointed |
| **L2** | Plan complete · **plan deviation** (any step's outcome ≠ contract → contract VOID, stop, ask — proactivity §4) · step budget exhausted · 3 consecutive step failures → auto-pause (proactivity §4) · user interrupt · supervisor preemption | L2 runner (code) + supervisor | `SUSPENDED` checkpoint; resume requires explicit user confirmation |
| **L3** | Objective achieved · `until:` expiry (cog temporal markers) · user revokes · supervisor judges infeasible (with evidence, announced) · 30-day dormancy with no progress → archived | Supervisor (code) + user | Archived with receipt; re-arming is a new approval, never automatic |
| **L4** | **Never**, except process shutdown | OS watchdog | Fail-closed: on supervisor restart, ALL L1–L3 work suspends pending re-authorization (session-store §8). The supervisor's job is small enough to be auditable — if it can't be, it's too big. |

**Design notes:**
- **β is checked by code, not by the model.** A termination condition the brain evaluates is a suggestion. Every β above is a predicate over the session store (event counts, timestamps, hashes) — deterministic, testable, auditable. [HC]
- **L2's deviation rule is the sharpest β:** the plan contract is hashed at approval; any step whose outcome doesn't match the contract voids it. This is the proactivity spec's "routines never gain new powers" generalized to all medium-horizon work. [HC]
- **L3's dormancy rule** comes from the foresight velocity taxonomy (Dormant: 30+ days → one gentle nudge, then never again). Objectives don't get to linger as background hauntings. [MC — threshold proposed]

---

## 4. Interruptibility — what each layer keeps, and what resume costs

| Layer | State kept (in session store) | On interrupt | Resume rule |
|---|---|---|---|
| **L0** | None (stateless by design) | Stop. Nothing to unwind. | N/A — reflexes re-arm automatically |
| **L1** | Current `tool.call` event_id (idempotency key), partial results, turn event tail | Abort in-flight call within bounded window; checkpoint partials; mark task `INTERRUPTED` | Automatic within the same turn only (re-issue with same idempotency key). Across turns: user confirms. |
| **L2** | Plan contract + hash, completed/pending steps, per-step results | `SUSPENDED` checkpoint; in-flight L1 task aborted per L1 rule | **Explicit user confirmation required.** "Want me to continue X?" — never silent auto-resume. (Kills the "helpful ghost" failure: JARVIS continuing work the user thought was cancelled.) |
| **L3** | Objective definition + contract hash, progress log, next scheduled action | `INTERRUPTED — awaiting user`; scheduled triggers disabled until re-armed | **Explicit re-arm by the user.** An interrupted objective never wakes itself up. |
| **L4** | Budget ledgers, preemption log | N/A (doesn't hold task state) | On restart: fail-closed suspend-all (session-store §8) |

**The resume asymmetry is deliberate:** downward (toward fast) resume is cheap and automatic; upward (toward slow) resume is expensive and explicit. This is the structural form of "long-term never silently overrides" — a slow layer can't even *continue*, let alone override, without the user saying so. [HC — derived from Rule 3 + proactivity wake policy]

**Restart/mid-flight changes:** if the user changes requirements mid-workflow ("actually, do Y instead of X"), that's not an interrupt — it's a *new* L1 task that preempts. The L2 plan's deviation β fires (outcome ≠ contract), the plan voids, and the supervisor asks whether to draft a new plan for Y or just do Y as a one-off. The old plan's completed steps are kept as evidence, not as momentum. [MC]

---

## 5. Resource allocation — what starves, what preempts

The supervisor allocates attention/compute across timescales. Principles:

1. **L0 is reserved, never starved.** Reflexes are deterministic code — microseconds. Their budget is a rounding error, and starving L0 means the system can't stop itself. Reserved unconditionally. [VC]
2. **L1 gets the bulk.** One active task per session; bounded parallelism (global 8, skill spec). A new user message preempts the current L1 task (checkpoint + yield).
3. **L2 gets what L1 doesn't need.** Workflows run as *sequences* of L1 tasks; between tasks the workflow yields. L2 never holds the brain while idle — it sleeps on its next trigger.
4. **L3 is background-only.** Objectives are checked on schedule (scheduler ticks), never polled continuously. Idle cost ≈ zero. A proposal costs one L2-plan drafting at most.
5. **Preemption order: L0 > L1 > L2 > L3.** When L1 starts, L2's current step checkpoints and yields. When the user speaks, everything yields.

**Budgets (all [PROPOSED], tuned from measurement):**

| Layer | Budget | Exhaustion → |
|---|---|---|
| L1 | 3 rounds / 12 tool calls per turn; 120s wall-clock | Escalate to user ("this is taking a while — continue?") |
| L2 | 20 steps per plan; 3 consecutive failures → auto-pause | Void contract → ask |
| L3 | 1 proposal per objective per day; foresight shares the 2/day nudge budget | Queue for tomorrow |
| Supervisor | N/A — its work is O(events), not O(model calls) | If the supervisor is slow, the watchdog fires (that's its β) |

**Starvation policy:** L3 proposals starve first (they're the least urgent by construction — if it mattered now, it'd be an L1 task). L2 yields to L1. Nothing starves L0. The supervisor logs budget exhaustion as events — "workflow X paused: step budget" is interrogable, never silent. [HC]

---

## 6. Prior art — borrowable vs overkill

| Approach | What it is | Borrow? | Verdict |
|---|---|---|---|
| **Options framework** (Sutton, Precup & Singh 1999) | Temporally-extended actions as `(initiation set, policy, termination condition)`; call-and-return execution | **β termination conditions** — explicit, checkable, per-layer (§3) | **Borrow the discipline, not the RL.** We don't learn options; we design layers. The paper's contribution here is the *shape* of the answer (every extended behavior names its end), verified via the search above. [HC] |
| **Subsumption** (Brooks 1986) | Layered reactive behaviors; higher layers suppress/inhibit lower via defined interfaces; no central planner | **The mechanism, inverted.** Brooks: slow/abstract subsumes fast/reactive. JARVIS: fast/immediate preempts slow/abstract. Same wiring (layers + suppression signals), opposite authority direction. | **Borrow the wiring, invert the arrow.** The preemption signal (§2 Rule 3) *is* a suppression wire — it just points up, not down. [HC] |
| **Cascade control** (control-theory study) | Outer loop sets the inner loop's *setpoint*; inner loop has hard limits the outer cannot exceed; 3–5× rate separation | **The setpoint analogy + rate separation.** L3 sets L2's *objectives* (setpoints), never its actions; L1's Gate is the inner loop's hard limit. | **Already adopted** (learn-control-theory.md); §1's 10× separation applies it. [HC] |
| **Event-triggered control** | Act on events, not clock ticks | **Supervisor is event-driven**: user message, tool result, timer fire, interrupt, budget exhaustion — never a poll loop. | **Borrow.** A polling supervisor is a battery/CPU tax and a latency tax; events are free in the session store. [HC] |
| **HTN planning** | Hierarchical task networks: tasks decompose via methods | The *decomposition* idea (proposal → plan → tasks) | **Overkill as formalism.** The plan contract + skill system covers it; full HTN (method preconditions, task networks) buys nothing at v2's scale. [MC] |
| **Full HRL** (option-critic, etc.) | Learning the hierarchy/options themselves via gradient methods | Nothing — the hierarchy is a design decision, not a learned artifact | **Overkill.** Training hierarchy-discovery needs 24GB+ GPUs and solves a problem we don't have. (Cf. SMITH study: training method beats params — but only where training is the bottleneck. Here, design is.) [HC] |
| **Three-layer robot architectures** (reactive/executive/deliberative) | The classic hybrid split | Confirms the shape: our L0≈reactive, L1–L2≈executive, L3≈deliberative, L4≈the arbiter they usually leave implicit | **Confirming, not new.** Our contribution is making the arbiter (L4) explicit and brain-free. [MC] |

**The novel claim** (labeled per Domain XI: *new combination of known techniques*, [MC]): nobody in the surveyed prior art combines **inverted subsumption** (fast preempts slow) with **action-origination restriction** (only the fastest deliberative layer can act) and **execution-time re-validation** (fresh instruction always beats stale plan). Each piece is known; the composition is the guarantee. It is falsifiable: exhibit a code path by which an L3 proposal causes a `tool.call` without passing the L1 Gate against the latest `user.message`, and the theorem falls.

---

## 7. Failure modes — the classics, each with its killer

### F1. Long-term goal drift
*The mechanism:* L3's objective is reinterpreted over weeks — via memory evolution (A-MEM), proposal paraphrase, or scope creep ("organize my files" → "reorganize my entire drive").
*The killer:* **objectives are contracts, hashed.** The approved text is hashed at approval time (session-store event). Every proposal derived from the objective carries the hash; the supervisor re-hashes before accepting. Paraphrase ≠ same hash → proposal rejected, user asked to re-approve the new wording. Drift is *representable* (the user can see the old vs new text) but never *silent*. [HC]

### F2. Medium-term loop burning the fast layer's budget
*The mechanism:* L2 workflow stuck — each step "almost works," retries, each retry spawns L1 tasks, each L1 task burns model calls and the user's afternoon.
*The killer:* **three nested circuit breakers** — L1's 2-attempt rule (Debugging Decay), L2's 3-consecutive-failures auto-pause (proactivity §4), and the supervisor's budget-burn-rate watch (if L2's spend/10min exceeds 3× its historical median, preempt and ask). The loop cannot survive all three; each breaker's trip is a session event. [HC]

### F3. Supervisor as single point of failure
*The mechanism:* L4 hangs (deadlock, infinite loop in budget accounting) → nothing terminates, nothing preempts.
*The killer:* **the supervisor is the simplest component on purpose.** No brain calls, no network, no unbounded loops — it processes a bounded event queue with bounded handlers. An OS-level watchdog (separate, dumber) restarts it if its heartbeat lapses; on restart, fail-closed: suspend-all pending re-authorization (session-store §8). A supervisor too complex to audit is a design bug, not a scaling challenge. [HC]

### F4. Preemption storms (interrupt thrash)
*The mechanism:* user rapidly interrupts/corrects → L1 aborts, L2 suspends, user re-asks, L2 re-suspends — thrash, no progress, checkpoint churn.
*The killer:* **debounce + explicit re-arm.** Interrupts within 2s collapse into one (extend, don't restart). L2/L3 require explicit re-arm after interrupt (§4), so they can't thrash — they wait. The session log shows the storm as evidence if the UX needs tuning. [MC — timings proposed]

### F5. Stale preemption (interrupt lands mid-tool-call)
*The mechanism:* user says "stop" while L1 is mid-write. Does the write land?
*The killer:* **bounded abort window + atomic writes.** The in-flight call finishes its current *atomic* step (a write either lands whole or not at all — A4), then stops. The Gate then re-validates: the next step is checked against the interrupt. Nothing half-done, nothing continued past the stop. The partial result is checkpointed so resume (on user confirmation) doesn't redo work. [HC — derived from A4 + Rule 3]

### F6. Objective starvation by chatty user
*The mechanism:* user is active all day → L1 always busy → L3 proposals never get L2 time → standing objectives silently die.
*The killer:* **they don't die; they queue visibly.** Starved proposals sit in L2's inbox, listed in the activity feed ("3 background proposals waiting"). The interruption budget (proactivity §5) governs when they surface — and the user can always pull them. Starvation is *visible*, which is the difference between "paused" and "dead." [MC]

### F7. The supervisor's blind spot: cross-layer causality
*The mechanism:* L3 proposal → L2 plan → L1 task → tool call → bad outcome. Which layer is at fault?
*The killer:* **the causal spine.** Every event carries `causal_parent` (session-store §2.2): the tool call points to the L1 task, which points to the L2 plan step, which points to the L3 proposal, which points to the approved contract. Fault attribution is a log walk, not a debate. (This is the causal-discovery study's "temporal order is free" applied to the layer stack.) [HC]

---

## 8. What this changes in the other specs

| Spec | Change |
|---|---|
| Session store (R15) | Supervisor's remit extends: preemption broadcast + budget ledgers + β checks, all as events. No schema change — new event types (`preemption.signal`, `budget.exhausted`, `objective.suspended`) fit the existing envelope. |
| Skill system | Dispatch function gains the Rule-1 restriction: callable only from the L1 code path (assert at the top of dispatch; test it). |
| Brain spec | The Gate's input list gains "latest `user.message`" as a mandatory re-validation input (Rule 2). |
| Proactivity | Routines are L2 contracts; foresight candidates are L3 proposals. The interruption budget (§5) is enforced by L4. No text changes needed — this spec *is* the enforcement layer the proactivity spec assumed. |
| Reliability | New SLO candidate: **preemption latency** — user interrupt → L0 stop ≤100ms [PROPOSED]; → L1 abort ≤2s [PROPOSED]; → L2/L3 suspend ≤5s [PROPOSED]. Measurable on the 2060 box. |

---

## Confidence & unknowns

| Claim | Confidence |
|---|---|
| Five-layer decomposition with the stated timescales | [HC] — derived from session-store supervisor + proactivity contracts + control-theory rate separation |
| Only-L1-emits-actions (Rule 1) | [VC] — structural; matches the skill-spec dispatch design |
| Execution-time re-validation (Rule 2) | [VC] — extends R3 "gate is the first statement"; the freshness argument is airtight |
| Preemption-as-signal bypassing judgment (Rule 3) | [VC] — same shape as the fault-tree B5 fix |
| β per layer, checked by code | [HC] — options-framework discipline applied; specific predicates designed, untested |
| Inverted subsumption as the composition | [HC] — mechanism described precisely; falsifiability stated |
| Budget numbers, debounce timings, preemption-latency SLOs | [MC]/[PROPOSED] — principled, unmeasured |
| Supervisor process-vs-thread topology | [UK] — inherited from session-store OQ1 |
| Whether 10× rate separation is sufficient (vs 3–5×) | [MC] — control theory says 3–5× minimum; 10× is margin, unvalidated |

### Open questions [UK]

1. **Measured preemption latencies** on the 2060 box — the proposed SLOs need the benchmarking weekend.
2. **The L2→L1 inbox protocol** — proposal queue depth, backpressure, priority between user tasks and workflow steps. Designed here as "L1 first," details at build.
3. **Contract-hash UX** — when a proposal's hash mismatches (F1), how is "your objective drifted, re-approve?" presented without annoying Owais? The approval-UX spec's dwell-time + plain-words rules apply; the exact copy is build-time.
4. **Multi-session layers** — this spec assumes one active session. Phone + desktop concurrently (phone-remote spec) means L4 arbitrates *across* sessions. Deferred to the phone-remote build.

---

## Traceability

| Choice | Source |
|---|---|
| Five layers, timescales, rate separation | learn-control-theory.md (cascade, 3–5×) + session-store (supervisor) + proactivity (routines) |
| Only L1 emits actions | DECISION-PLAYBOOK S5/R2; learn-skill-system-spec §dispatch |
| Re-validation at execution | DECISION-PLAYBOOK R3; learn-fault-trees B3 (TOCTOU) |
| Preemption bypasses judgment | learn-fault-trees B5; learn-threat-model (AND-gates) |
| β per layer | Options framework, Sutton/Precup/Singh 1999 (verified via search) |
| Inverted subsumption | Brooks 1986 (verified via search); authority direction inverted by design |
| Event-driven supervisor | learn-session-store §3 (supervisor owns transitions); event-triggered control |
| Contract hashing (F1) | learn-proactivity-spec §4 (routines as contracts); DECISION-PLAYBOOK A4 |
| Triple circuit breakers (F2) | learn-ai-for-se (Debugging Decay); proactivity §4; learn-skill-system-spec |
| Fail-closed supervisor restart (F3) | learn-session-store §8; learn-reliability-spec degradation ladder |
| Causal spine attribution (F7) | learn-session-store §2.2 (`causal_parent`); learn-causal-discovery (temporal order is free) |

*End of Domain X study. Status: design complete as a learning document; unimplemented by intent. The falsifiable core: exhibit an L3→tool.call path that bypasses the L1 Gate's fresh-instruction check, and the non-override theorem falls.*
