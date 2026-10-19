# JARVIS System Reliability Specification

*PHASE INFINITY, Research Cycle 12. §18 artifact #10 — unified from previously scattered material.*
*Date: 2026-10-19. LEARNING ONLY — no code, no installs.*

**Sources unified:** `learn-advanced-cs.md` (fault domains, degradation ladder, durable queue, 3-process topology), `learn-observability.md` (health checks, watchdogs, metrics, checkpoints, crash detection), `learn-fault-trees.md` (approval-gate cut sets, secrets/updater/poisoning trees), `learn-evaluation-science.md` (M1–M18 scorecard, 7 release gates).

**Target labels:** [DERIVED] = follows from measured evidence or hard hardware facts. [PROPOSED] = reasoned starting point, unmeasured — a hypothesis, not a promise. No theater: if it's a guess, it says so.

---

## 1. SLOs — Service-Level Objectives (user-facing)

SLOs are promises to Owais, stated in his experience, not in system internals.

### S1. Turn success rate
- **Definition:** % of user turns that complete correctly end-to-end (task done, answer correct, no crash, no silent wrong action). A turn "fails" if the user rephrases/repeats within 30s (implicit signal) or the task's own verification fails (explicit).
- **Measurement:** instrumented counters `turns_total` / `turns_failed_total` (§3 observability); golden-set eval gives the calibrated number (M1).
- **Target:** ≥95% weekly on real usage [PROPOSED]; ≥75% on golden set (M1 gate) [PROPOSED as gate, DERIVED as framework].
- **Why:** below ~95%, the assistant feels unreliable and the user stops delegating — the product dies by a thousand small failures, not one big one. The golden-set bar is lower because golden tasks are adversarially chosen; real usage is easier on average. [PROPOSED reasoning]

### S2. Voice-loop latency
- **Definition:** time from end-of-utterance to start-of-response (first audible word).
- **Measurement:** `turn_latency_seconds` histogram + `stage_latency_seconds{stage}` (§3); buckets tuned to voice: `[0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10]`.
- **Target:** p50 ≤ 2.0s, p95 ≤ 4.0s [PROPOSED — the "feels instant" boundary for Owais is unmeasured; 2s is the telephony industry's conversational comfort line, applied by analogy].
- **Why:** latency is the voice UX. Past ~4s p95, users repeat themselves — which the system reads as a new turn, compounding the failure (S1 drops too).

### S3. False-wake rate
- **Definition:** wake-word triggers with no user intent, per day.
- **Measurement:** `wake_false_positive_total` counter (§3); user dismissals ("not for you") as ground truth.
- **Target:** ≤3 per day [PROPOSED]; aspirational ≤1/day.
- **Why:** every false wake is an interruption + a privacy event (mic opens, audio processed). More than a handful per day and the user mutes the mic — killing the product's core modality. Also: false wakes burn the error budget of trust faster than any other failure.

### S4. Crash-free operation
- **Definition:** mean time between crashes (any process) and, separately, % of 24h periods with zero crashes.
- **Measurement:** crash log + supervisor restart records (§6 observability: excepthook → faulthandler → atexit → external supervisor).
- **Target:** ≥99% of days crash-free; MTBC (mean time between crashes) ≥ 7 days [PROPOSED].
- **Why:** a crash costs the conversation (S5 covers how much). v1's history (hours of failed launches) makes this the trust SLO — Owais's confidence lives or dies here.

### S5. Data-loss-on-crash (durability SLO)
- **Definition:** maximum conversation/memory/task state lost when a crash occurs.
- **Measurement:** on recovery, compare last checkpointed `event_id` vs last event before crash.
- **Target:** RPO ≤ 5 minutes of activity or ≤ 50 events, whichever is smaller [PROPOSED — checkpoint cadence from observability §6, unmeasured on target hardware]. Zero loss of *committed* user data (memories, settings) — atomic writes make this [DERIVED from R6 design, not yet measured].
- **Why:** losing the last 30 seconds is an apology; losing an hour's work or a saved memory is a betrayal. Durability is where "dependable beats impressive" is proven.

### S6. Approval-gate integrity
- **Definition:** zero tier-3 actions executing without genuine user approval (the fault-tree top event).
- **Measurement:** approval-gate fault tree cut sets (§fault-trees): 8 size-1 single points of failure, each with a mitigation; attack suite M9 covers adversarial branches.
- **Target:** 0 violations, ever. This SLO has no error budget (see §2) [DERIVED from the tree: a single violation is a safety failure, not a quality dip].
- **Why:** one unauthorized irreversible action destroys more trust than a hundred failed turns. This is the SLO that justifies the entire R2/R3 apparatus.

### S7. Secret/PII containment
- **Definition:** zero secrets or non-consented PII in logs, cloud-bound payloads, crash dumps, or backups.
- **Measurement:** automated scan per release (M10) + fail-closed redaction processors.
- **Target:** 0 findings [DERIVED from M10 gate design].
- **Why:** a leaked API key is a compromised account; the user cannot undo it. Matches the secrets fault tree finding: every cut set is size 1, so the response is elimination, not layering.

---

## 2. Error budgets

**The rule:** every SLO except S6/S7 gets a monthly error budget. S6 (approval integrity) and S7 (secret containment) have **zero budget** — any violation is a stop-ship incident, not budget burn.

| SLO | Monthly budget | Burn policy |
|---|---|---|
| S1 turn success | 5% of turns may fail (i.e., 95% floor) | Budget >50% burned by mid-month → freeze new features, reliability sprint. Budget exhausted → no release until S1 recovers for 2 consecutive weeks. [PROPOSED] |
| S2 voice latency | 5% of turns may exceed p95 4s | Same as S1 — latency and success share the "feels broken" budget. Track stage_latency to find which stage burns it. [PROPOSED] |
| S3 false wakes | 90 false wakes/month (~3/day) | Sustained >5/day for a week → wake-word threshold retune (V4) becomes P0; consider disabling always-listen until fixed. [PROPOSED] |
| S4 crash-free days | 1 crash-day per month tolerable | 2nd crash in a month → the crash's fault domain gets a hardening sprint before any feature work. 3rd → release freeze. [PROPOSED] |
| S5 data loss | 0 committed-data losses; ≤5min activity loss per crash | Any committed-data loss = S6-class incident (stop-ship). Activity-loss overruns → checkpoint cadence tightened. [PROPOSED] |

**Budget-burn alerts (how we know):** the in-process metrics registry (§3) computes budget consumption; the HUD diagnostics tab shows it ("Reliability: 96% success this month, budget 62% remaining"). No silent burn — the user sees the same numbers we do (R12 honest UX).

**Anti-gaming rule** (from evaluation-science §4.4): if a metric improves while Owais reports worse quality, the metric is wrong, not the user. Fix the metric, don't celebrate.

---

## 3. Recovery objectives (RTO/RPO per subsystem)

| Subsystem | RTO (max time to restore service) | RPO (max acceptable loss) | Mechanism |
|---|---|---|---|
| **Core process** (brain, tools, memory) | ≤60s to responsive chat [PROPOSED] | ≤5 min activity / ≤50 events [PROPOSED] | Recovery-on-boot: latest checkpoint + replay tail of event log; `wake(sessionId)` semantics. Checkpoint: tmp+`os.replace()` in same dir, or SQLite WAL. |
| **Brain server** (llama-server) | ≤120s (model reload on 2060) [PROPOSED — reload time unmeasured] | 0 — no state lives in the server; all state is in the core's event log [DERIVED from architecture] | Circuit breaker → cloud fallback during reload → local when ready. Health-check canary prompt gates "ready." |
| **Voice plugin** | ≤30s to text-fallback announcement [PROPOSED] | In-flight utterance only — honest "could you repeat that?" [DERIVED from observability §6: unrecoverable by design] | Voice crash → core announces text mode; voice restarts independently (separate process). |
| **UI/HUD** | ≤15s to tray icon; full HUD on next launch [PROPOSED] | 0 — UI holds no state; core is headless-capable (`--no-hud`) [DERIVED from fault-domain design] | Watchdog restarts UI only; core never dies with the UI. |
| **Scheduler** | Next tick resumes missed tasks [DERIVED from durable queue] | 0 — scheduled tasks are events in the log; crash mid-task resumes the task [DERIVED from write-before-reason] | SQLite WAL job table; poison-job quarantine after N attempts. |
| **Memory store** | N/A (no separate process) | **0 committed memories** — atomic writes + backups (R6) [DERIVED from design] | Corrupt checkpoint → quarantine (`checkpoint.json.corrupt-<ts>`), boot from event-log replay alone, tell the user. Never boot-loop. |

**Checkpoint cadence derived from RPO:** RPO ≤5 min / ≤50 events → checkpoint every 5 minutes or 50 events, whichever first; always checkpoint before a destructive action (ship-undo). [PROPOSED — needs the replay-time measurement: time a full day's replay on the Ryzen 5 3600; if replay >30s, tighten cadence.]

**Recovery code is itself fault-handled:** corrupt checkpoint → quarantine, don't crash; recovery wrapped so a recovery failure degrades to "report loss honestly" rather than looping. [DERIVED from observability §6]

---

## 4. The degradation ladder — as specification

Each rung is a **declared, tested mode**, not an accident. Transitions are measured, announced, and hysteretic.

| Rung | State | Trigger (measured, not vibes) | Announcement (butler voice, once) | Hysteresis |
|---|---|---|---|---|
| **R0 Full** | All systems nominal | Default | — | — |
| **R1 Text-only** | Voice plugin down or degraded; brain + tools + UI healthy | Voice heartbeat silent >30s (§4 watchdog) OR 3 consecutive STT/TTS failures | "Sir, voice is unavailable — I'm listening in text until it's restored." | Voice healthy for 5 consecutive checks before re-enabling |
| **R2 Local-only** | Cloud providers unreachable/failing; local brain healthy | 3 consecutive cloud failures (429/5xx/timeout) OR cloud health-check fail; local brain canary passes | "Sir, I've lost the cloud connection; running fully local until it returns." | 5 consecutive cloud successes before re-enabling cloud tier |
| **R3 Read-only** | Storage degraded (disk full, DB locked, write failures) | Write failure on event log or memory DB; disk <1GB free | "Sir, I can look things up but can't save anything right now — your data is safe, nothing is being written." | Writes succeed for 5 consecutive attempts before leaving R3 |
| **R4 Honest "I can't"** | Brain unavailable (local OOM + cloud down) | Local brain health-check fail AND cloud tier in R2-degraded | "Sir, I can't think right now — both my local and cloud brains are down. Your data is intact; I'll keep trying to reconnect." | Full preflight passes before leaving R4 |

**Ladder rules:**
1. **Skips allowed downward, never upward.** R0 can drop straight to R4 (brain OOM + cloud down simultaneously); recovery climbs one rung at a time with hysteresis at each step. [PROPOSED]
2. **Announcement is mandatory and once.** Silent degradation destroys trust (R12). Repeated announcements destroy patience — announce on entry, show persistent status (HUD dot / tray), announce on recovery. [DERIVED from observability §4 + U2]
3. **Never show green when degraded.** The HUD status reflects the current rung, always. [DERIVED from R12]
4. **Degradation never loosens safety.** R1–R4 change *capability*, never *permissions*: the approval gate, fs-jail, and redaction apply at every rung. A degraded JARVIS is a less capable JARVIS, not a less safe one. [DERIVED from fault-tree G2: safety layers are AND-gates, not rungs]
5. **Flap guard:** 3 consecutive failures to degrade, 5 consecutive successes to recover — per observability §4. Counters reset on rung change. [PROPOSED values, DERIVED principle]

---

## 5. Dependency map — everything that can fail

*If it can fail, it's in the table. Detection method and fallback for each.*

| Dependency | Failure modes | Blast radius | Fallback | Detection |
|---|---|---|---|---|
| **llama-server (local brain)** | OOM, crash, model load fail, slow (>30s canary) | R4 if cloud also down; else R2-local unaffected... actually brain-down = R4 unless cloud covers | Cloud provider via circuit breaker (B1 recipe: transport errors only) | Health-check canary prompt; VRAM gauge <500MB headroom warning |
| **Cloud providers (Gemini/Groq/OpenRouter)** | 429 rate limit, DNS, key revoked, 5xx, timeout | None if local healthy (R2 rung) | Local brain; per-provider circuit breaker + key rotation | `brain_fallback_total{from,to,reason}` counter; consecutive-failure count |
| **Microphone / audio input** | Device unplugged, driver wedged, permission revoked | Voice input dead → R1 | Text input (always available) | VAD frame watchdog: device callbacks silent >10s |
| **Speakers / TTS backend** | Backend crash, voice model missing | Voice output dead → R1 (text responses) | Text display; TTS backend fallback chain (Piper→Kokoro→Chatterbox→cloud) | Canary synthesis or last-success timestamp staleness |
| **Wake-word engine** | Model missing, false-negative storm | Always-listen dead; push-to-talk still works | Push-to-talk / hotkey fallback | `wake_false_positive_total` + user reports of missed wakes |
| **SQLite (event log, memory, queue)** | Disk full, file lock, corruption, WAL growth | R3 read-only; crash if unhandled | Atomic writes + backups (R6); quarantine corrupt files, replay from log | Write-failure catch; disk-space check in preflight (<1GB = R3); integrity check on open |
| **Chroma (vector store)** | Corrupt index, OOM on large query | Retrieval degraded (keyword FTS5 still works) | FTS5-only retrieval; rebuild index from event log (projections are disposable) | Query error rate; index integrity on open |
| **Telegram (phone remote)** | Network down, token revoked, API change | Phone remote dead; desktop unaffected | None (desktop is primary); queue outbound messages in outbox for retry | API error codes; consecutive-failure counter |
| **Tavily / web search APIs** | 429, key revoked, timeout | Deep-research skill degraded | Cached results (task-scoped); honest "can't reach the web right now" | Same as cloud providers |
| **Windows OS services** | UIA tree walk hangs, screenshot API fails, notification service down | PC-control degraded; screen-watch off | UIA→OCR→screenshot fallback chain (multimodal study); timeouts on every OS call | Per-call timeouts; watchdog on automation threads |
| **GPU driver / CUDA** | Driver crash, TDR (timeout detection) | Brain server dead → cloud fallback | Cloud brain (R2); CPU inference as last resort (BitNet tier) | pynvml errors; llama-server health check |
| **Disk** | Full, failing (SMART), permission loss | R3 → R4 cascade | Preflight disk check; log rotation bounds growth; honest announcement | Preflight + runtime free-space gauge |
| **Network (general)** | Offline, captive portal, DNS poisoned | Cloud + web + Telegram down; local-first keeps working | Full local operation (the local-first design *is* the fallback) | Soft health check; never blocks startup |
| **Python runtime / deps** | Corrupt venv, DLL hell (MSVC), AV quarantine | Won't start | Installer repair; VC++ redist check in preflight (v1's #1 fresh-machine killer) | Preflight dependency checks; crash log on import failure |
| **NTP / system clock** | Clock skew | Token expiry misjudged, log timestamps wrong, approval token expiry wrong | Monotonic clocks for intervals (`time.monotonic()`); wall clock only for display | Skew detection vs boot time; never trust wall clock for security decisions |

**Dependency principles:**
- **Local-first is the fallback for everything networked.** The network going down degrades, never kills. [DERIVED from architecture]
- **Timeouts on every external call.** No unbounded waits — a hung dependency is indistinguishable from a dead one without a timeout. [DERIVED from backend study O6]
- **One retry budget across layers.** The HTTP client and the brain router share one budget; retries must not multiply. [DERIVED from learn-backend.md]

---

## 6. "Reliable enough to ship" — the release-gate checklist

*The single page. All gates must pass; any gate failure blocks release. Combines the evaluation-science gates (M1–M18) with the reliability gates from this spec.*

### Quality gates (from M1–M18) 🔒
- [ ] **M1** Task success ≥75% on golden set v{pinned}, reported as `82% (95% CI: 73–89%, n=100)` — no bare proportions
- [ ] **M2** Factual accuracy ≥95% (n≥200 claims, independent checker)
- [ ] **M5** Memory correction ≥95% — a correction ignored is a trust violation
- [ ] **M9** Attack suite 100% on known attacks (≥50 cases), ≥95% on extended/novel
- [ ] **M10** Privacy findings = **0** (automated scan + manual memory-write review)
- [ ] **M15** VRAM ≤5.5GB / RAM ≤8GB sustained during golden run (the 2060/16GB box)
- [ ] **M18** Regressions = **0** — or explicitly waived by Owais with recorded reason, expiring after one release

### Reliability gates (from this spec)
- [ ] **S1–S5** measured on a soak run (≥7 days real or simulated usage): turn success, p95 latency, false wakes, crash-free days, recovery loss — all within SLO or within error budget with a burn-down plan
- [ ] **S6** Approval-gate fault tree reviewed against the *actual* gate code: all 8 size-1 cut sets have mitigations implemented; G2's AND gate (code enforcement post-brain) verified present — a refactor moving the gate into a prompt is a release-blocking regression
- [ ] **S7** Secret-containment scan clean: no secrets in logs, dumps, backups, or cloud-bound payloads in the soak run
- [ ] **Degradation ladder tested:** each rung (R1–R4) triggered by fault injection, announcement verified, hysteresis verified (no flapping), recovery climbs correctly
- [ ] **Recovery tested:** kill -9 mid-task on 20 long tasks → ≥80% correct resume, **100% no-duplicate-mutating-action** (M17's second half is a gate)
- [ ] **Dependency table walked:** every row's fallback exercised at least once by fault injection (provider 429s, disk-full simulation, mic unplug, model OOM)
- [ ] **Checkpoint/replay timed:** full-day replay <60s on the Ryzen 5 3600, or cadence tightened until it is [PROPOSED threshold]
- [ ] **No fake numbers:** every metric reported with CI and n; every target labeled [DERIVED] or [PROPOSED]; untested = marked UNTESTED, not omitted

### The ship decision
Ship requires: all 7 quality gates ✅ + all 8 reliability gates ✅ + Owais's explicit go. A regression in any gate blocks release regardless of improvements elsewhere (non-collapse rule). Trade-offs are presented as trade-offs — "latency −300ms, accuracy −2pp: reject (accuracy is a gate)."

---

## Confidence, unknowns, and what's PROPOSED vs DERIVED

**[DERIVED] (evidence-backed):** fault-domain list (each grounded in a v1 autopsy finding); the 3-layer verification rule (Z3-proves/Hypothesis-tests/runtime-enforces); approval-gate AND-gate structure (R2); local-first as universal network fallback; atomic-write durability; idempotency requirement for resume; the non-collapse scorecard rule; M9's 13/13 v1 baseline; VRAM/RAM budgets from hardware facts.

**[PROPOSED] (reasoned, unmeasured):** every numeric SLO target (95% success, 2s/4s latency, 3 false wakes/day, 7-day MTBC); error-budget sizes and burn policies; RTO numbers (60s/120s/30s/15s); checkpoint cadence (5min/50 events); hysteresis counts (3-down/5-up); the 200MB/day leak threshold; replay-time threshold (60s).

**Unknowns (ranked):**
1. All baselines UNTESTED — the first measurement task is measuring the current build (M1, M9, M15 first).
2. Real per-turn overhead, replay time, checkpoint cost on the Ryzen 5 3600 / RTX 2060 — the benchmarking weekend resolves most PROPOSED numbers.
3. Owais's actual rubber-stamping rate and "feels instant" latency boundary — production-measured only.
4. Whether the 3-process topology survives fault injection without IPC becoming its own fault domain.
5. NTP/clock-skew handling on Windows for approval-token expiry — edge case, unexamined.

*End of reliability spec. Status: unified and internally consistent; numeric targets await the benchmarking weekend. Per the precision protocol: everything marked [PROPOSED] is a hypothesis, not a promise.*
