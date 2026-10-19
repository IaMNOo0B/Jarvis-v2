# Control Theory for AI Agents (Scoped)

*LIFETIME DIRECTIVE gap research, 2026-10-19. LEARNING ONLY — no project files touched, no installs, no code executed.*
*Skip-if-learned applied: hysteresis (learn-observability.md:307), Beta-Bernoulli ledger (learn-math-for-jarvis.md:33-43), brain/hands/session decoupling (Anthropic managed-agents PhD) — referenced, not re-taught.*
*Scope rule: no Laplace transforms, no proofs. Only what changes a JARVIS design decision.*

---

## 1. Feedback Loops: Open-Loop vs Closed-Loop

**Mechanism.** An *open-loop* controller acts blindly: it issues commands with no measurement of the result (a washing machine timer). A *closed-loop* controller measures the outcome, compares it to the target, and corrects (a thermostat). The loop is: **sense → compare → act → repeat**.

**JARVIS application — the agent loop IS a feedback controller [VC].** Every ReAct turn is sense (tool result / UI observation) → compare (does this match the goal?) → act (next tool call). Recognizing this reframes agent design questions as control questions:

- **Open-loop agent behavior = a bug class.** Anywhere JARVIS acts without verifying the outcome — fire-and-forget tool calls, "email sent" assumed from a 200 OK, a file written but never re-read — is open-loop control. The v1 autopsy class "assumed actions succeeded" is exactly this. The fix is closing the loop: verify-after-acting (already adopted via the UIA-tree-first field order: tree → OCR → screenshot → verify-after-acting).
- **The loop needs a sensor model.** A thermostat trusts its thermometer; an agent must decide what counts as evidence of success. This is where the REA evidence model (observed/derived/inferred) and the belief ledger slot in: they are the agent's *sensor* for its own control loop.
- **Loop rate matters.** Voice barge-in needs sub-second loop closure; a nightly backup job doesn't. Design rule: match the loop rate to the process dynamics — fast loops for fast processes, slow loops for slow ones. Running a slow process on a fast loop wastes compute; running a fast process on a slow loop loses control (the voice echo bug was partly a loop-rate problem: the mic heard TTS before the echo guard could close the loop).

---

## 2. PID Control: P, I, D Thinking for Adaptive Behavior

**Mechanism.** A PID controller computes its action from three terms on the error e(t) = target − measured:

- **P (proportional):** react in proportion to *current* error. Big error → big correction.
- **I (integral):** react to *accumulated past* error. Eliminates persistent small offsets that P alone never fixes (steady-state error).
- **D (derivative):** react to the *rate of change* of error. Damps overshoot — brakes before crossing the target.

The classic tuning procedure (Ziegler–Nichols: raise P until sustained oscillation, record ultimate gain Ku and period Pu, then set Kp=0.6Ku, Ti=Pu/2, Td=Pu/8) is a heuristic for finding the stability boundary by experiment rather than math. [VC — verified via Wikipedia and multiple tuning references.]

**JARVIS applications.** Nobody is wiring a literal PID into the brain. The value is PID *thinking* — three distinct timescales of correction — applied to adaptive subsystems:

1. **Adaptive retry backoff (worked example).** A provider starts 429ing.
   - **P-term:** current failure rate → immediate backoff proportional to it (1 failure: wait 2s; 5 failures: wait 30s). This is what exponential backoff approximates.
   - **I-term:** accumulated failures over the last hour → escalate: if the provider has failed 20 times today, stop hammering and fail over to the next provider in the chain (this is the B1 fallback recipe, now with a name for its memory).
   - **D-term:** *rate of change* of failures → if failures are accelerating (1 → 2 → 8 in a minute), back off harder and sooner than the current count alone suggests; if failures are *decelerating* (provider recovering), ease back in faster instead of waiting out a fixed cooldown. The D-term is what's missing from naive fixed backoff — it reads the trend, not just the level.
   - **Anti-windup (the gotcha):** in real PID, the integral term keeps accumulating while the actuator is saturated, causing violent overshoot on recovery. Agent analog: a failure counter that keeps growing during a long outage, then triggers an absurdly long cooldown after the provider recovers. Fix: cap the integral (decay old failures, e.g., sliding window), exactly as control engineers clamp the integrator.
2. **Rate limiting / token bucket governors:** the token bucket is a P-controller on request rate; adding an integral term (track sustained over-limit) gives graduated penalties instead of binary allow/deny.
3. **VRAM budget governor:** P = current VRAM pressure → shed load now (drop KV cache, compress context); I = sustained pressure over minutes → escalate (unload the ambitious model tier, fall back to the smaller one); D = pressure rising fast → pre-emptive shed *before* OOM. An OOM mid-conversation is a v1-class failure; a three-timescale governor is the control-theoretic shape of the fix.
4. **Watchdog sensitivity:** P = missed heartbeat now; I = pattern of flakiness over days (this box always stutters at 3pm — don't page); D = sudden change in heartbeat interval (something just died).

**Design decision changed:** adaptive subsystems get three timescales (now / accumulated / trend), with the integral always windowed and capped. [HC]

---

## 3. Stability: Why Feedback Loops Oscillate or Diverge

**Mechanism.** A feedback loop goes unstable when correction *overshoots* and the correction-of-the-correction overshoots back — oscillation — or when each cycle amplifies the last — divergence. Two classic causes:

- **Gain too high:** reacting too strongly to each error (the Ziegler–Nichols Ku is literally the gain where this starts).
- **Delay in the loop:** acting on stale measurements. A thermostat with a 10-minute sensor delay will heat past the target, then cool past it, forever. Delay + high gain is the standard recipe for oscillation.

**JARVIS applications — three instability patterns, each with a control-theoretic fix:**

1. **Retry storms.** Provider fails → every queued task retries immediately → load spikes → more failures → more retries. This is *positive feedback*: the correction amplifies the disturbance. Fixes from control theory: **gain reduction** (exponential backoff with jitter — jitter breaks the synchronization that makes storms coherent), and **one retry budget across layers** (already adopted in learn-backend.md O6 — the HTTP client and brain router must not multiply retries, i.e., don't stack two controllers on the same loop).
2. **Approval-prompt flapping.** Degraded-mode toggling: cloud 429s → "degraded" → one success → "OK" → 429 again → "degraded"… The UI flickers and the user stops trusting the status. Fix already adopted (learn-observability.md:307): **hysteresis** — require 3 consecutive failures to enter degraded mode and 3 consecutive successes to leave. Hysteresis is a deadband: the on-threshold differs from the off-threshold, so noise near the boundary can't flip the state. This is the standard control fix for relay chatter, and it generalizes: any binary agent state driven by a noisy signal (user idle/active, network up/down, "stuck" detection) gets asymmetric thresholds.
3. **Screen-watcher oscillation.** The watcher decides "user looks stuck" → interrupts → user annoyed → dismisses → watcher re-triggers on the same screen state. Fix: the interruption itself must feed back into the controller as a *setpoint change* (raise the bar for re-interrupting on the same context), plus a cooldown — a rate limiter on the control action. In control terms: limit the actuator, not just the sensor.

**Meta-rule:** whenever an agent subsystem both *measures* and *acts on* the same signal, ask "what stops this from oscillating?" If the answer is nothing, add one of: reduced gain, hysteresis/deadband, actuator rate limiting, or delay compensation. [HC]

---

## 4. State Estimation (Lite): The Kalman Idea in One Paragraph

**Mechanism.** The Kalman filter (Kálmán, 1960) answers: "the world has a true state I can't see directly; I have a noisy model of how it evolves (prediction) and noisy measurements (update) — what's my best estimate?" Each cycle: predict the next state from the model, then correct the prediction with the measurement, weighting the two by their relative uncertainties via the **Kalman gain** — trust the measurement more when the sensor is good, trust the prediction more when the sensor is bad (GPS in a tunnel). It needs only the previous estimate, so it's O(1) memory. The math assumes linear dynamics and Gaussian noise; the *idea* — predict-then-correct, weighted by uncertainty — is the portable part. [VC — verified against multiple references.]

**JARVIS verdict: the Beta-Bernoulli ledger already covers the need — do NOT build a Kalman filter [HC].** Reasons:

- JARVIS's estimation problems are **binary and event-driven** (did the tool succeed? is the provider up? was that a real wake word?), not continuous tracking problems. The Beta(α,β) per-tool ledger from learn-math-for-jarvis.md is the correct conjugate model for Bernoulli observations, is auditable (14 successes, 3 failures — visible), and needs three integers per tool.
- A Kalman filter would add matrix machinery to estimate quantities JARVIS never needs as continuous states. The *one* portable insight worth stealing: **the Kalman gain as a principle** — when fusing two uncertain sources, weight by inverse uncertainty. The belief ledger already does this implicitly (more observations → tighter posterior → more trust in the estimate vs any single new measurement).
- **The one place to revisit:** if JARVIS ever tracks a genuinely continuous hidden state from noisy sensors — e.g., estimating user *engagement/availability* from mic activity + app focus + time patterns for proactive interruption decisions — a 1-D Kalman (or even exponential moving average, its degenerate cousin) beats threshold rules. Mark as tripwire, not todo.

---

## 5. Supervisory Control: The Hierarchy of Controllers

**Mechanism.** Cascade/supervisory control nests loops: a **fast inner loop** controls a quickly-responding variable, and a **slow outer loop** sets the inner loop's *setpoint* rather than touching the actuator directly. The inner loop rejects local disturbances before they reach the outer loop; the outer loop handles strategy. Rule of thumb from process control: the inner loop must run 3–5× faster than the outer. The outer controller never sees the actuator's mess — it commands "hold 95°C" and the inner loop fights the sticky valve. [VC — verified via apmonitor.com cascade control reference and multiple control sources.]

**JARVIS application — this is the formal name for the architecture already chosen [HC]:**

| Control layer | JARVIS layer | Loop rate | Job |
|---|---|---|---|
| Inner loop (fast) | **Hands** (tools, skills, UI driver) | ms–s | Execute precisely, reject local disturbances (retry a flaky click, re-read after write) |
| Outer loop (slow) | **Brain** (planner, LLM) | s–min | Set the goal: "book the flight" — never micromanage the clicks |
| Supervisory | **Session** (event log, memory, policy) | min–h | Set the *policy*: which tools are allowed, what the budget is, what "done" means |

Three consequences that sharpen the existing design:

1. **Disturbance rejection belongs in the inner loop.** A flaky tool should retry *inside* the tool wrapper (fast, cheap, invisible) rather than bubbling every transient failure up to the brain for replanning (slow, expensive, token-burning). The brain should only see disturbances the inner loop *couldn't* reject. This is the control-theoretic justification for bounded auto-retry at the tool layer + escalation on exhaustion.
2. **The outer loop commands setpoints, not actuations.** The brain emits *goals with acceptance criteria* ("file saved and verified"), not click coordinates. This is already the OpenGCUA lesson ("only act on what you have been shown") restated: the interface between loops is declarative.
3. **Supervisory override is the safety architecture.** The session/policy layer can change the inner loops' setpoints — revoke a tool's permission mid-task, tighten the budget, halt everything. In control terms this is the emergency stop that every cascade system needs: the outer loop must always be able to *clamp* the inner loop's authority. This maps directly onto R2 (instruction hierarchy) and the Conscio circuit breaker: policy enforcement lives above the model, not inside it.

**Design decision changed:** explicit "3–5× rate separation" guidance — tool-layer retries resolve in milliseconds-to-seconds without brain involvement; brain replans on seconds-to-minutes; session policy changes on minutes-to-hours. If a disturbance is being handled at the wrong layer (brain micromanaging retries, or the tool layer making policy decisions), that's a layering bug. [HC]

---

## Cross-Cutting Summary

| Concept | Verdict for JARVIS |
|---|---|
| Closed-loop discipline | **ADOPT** — every consequential action gets verify-after-acting; open-loop = bug class |
| PID three-timescale thinking | **ADOPT** — now / accumulated / trend on retry, VRAM, watchdog governors; integral always windowed |
| Stability analysis | **ADOPT** — "what stops this oscillating?" asked of every sense-and-act loop; hysteresis, gain reduction, rate limiting |
| Kalman filter | **SKIP** — Beta-Bernoulli ledger covers it; Kalman gain *principle* (weight by inverse uncertainty) noted |
| Supervisory/cascade control | **ADOPT (formalizes existing)** — inner loop rejects disturbances, outer loop sets setpoints, supervisory layer clamps authority; 3–5× rate separation |

## Unknowns

1. The actual oscillation risks in the full v2 loop topology can't be analyzed until the loops exist — stability review belongs in the design review checklist, not in more reading. [UK]
2. Retry-governor constants (windows, caps, hysteresis counts) are tuning parameters — Ziegler–Nichols-style empirical tuning on the real system, not derivable from theory. [UK]
3. Whether the 1-D continuous state estimation tripwire (user availability for proactive interruption) ever fires — needs the proactivity feature to exist first. [UK]

## References (all verified live, none fabricated)

- Ziegler–Nichols tuning method — https://en.wikipedia.org/wiki/Ziegler%E2%80%93Nichols_method
- Cascade control (primary/secondary loop hierarchy) — https://apmonitor.com/pdc/index.php/Main/CascadeControl
- Kalman filter intuition (predict/update, Kalman gain) — https://jonathan-hui.medium.com/self-driving-object-tracking-intuition-and-the-math-behind-kalman-filter-657d11dd0a90
- Related prior knowledge: `learn-observability.md` (hysteresis §), `learn-math-for-jarvis.md` (Beta-Bernoulli §), `learn-backend.md` O6 (single retry budget), `learn-frontier-reasoning.md` §2 (belief ledger), Anthropic managed-agents PhD (brain/hands/session decoupling)
