# Observability & Reliability for JARVIS — Learning Notes

*Domain S of the JARVIS master curriculum. LEARNING ONLY — no code written against the project.*
*Date: 2026-10-19. Skip-if-learned applied: event sourcing + JSONL replay (S4/I4), circuit breakers (I4),
Anthropic `wake(sessionId)` crash recovery (SEC1), fallback-chain recipe (B1), DeepEval evals (I2) already
exist in the knowledge base — this file covers only the gaps, and references them instead of re-learning.*

---

## 1. OpenTelemetry for a Personal Agent: What's Useful vs Overkill

### Purpose
Distributed tracing answers "which request caused this, and where did the time go?" For JARVIS: one spoken
request fans out across wake-word → VAD → STT → brain (local/cloud) → tools → TTS → speakers. A single
`trace_id` tying those stages together turns "it's slow sometimes" into "STT took 1.8s on that turn."

### How it works internally
- **Trace** = one end-to-end request. **Span** = one timed unit of work inside it (e.g. `stt.transcribe`).
  Spans nest: `turn` → `brain.respond` → `tool.exec("read_file")`.
- Context propagation: the current trace/span travels via `contextvars` (async-safe). Each span carries
  `trace_id` (128-bit), `span_id` (64-bit), and attributes (key-value pairs, e.g. `model.name="qwen3.5:9b"`).
- **Exporters** decide where spans go. `ConsoleSpanExporter` prints JSON to stdout; OTLP exporters ship to a
  collector/backend (Jaeger, Tempo). **Sampling** (`TraceIdRatioBased`) drops most traces in high-volume
  systems; irrelevant at JARVIS's volume (tens of turns/day).

### The honest verdict for one user [HC]
Full OTel (collector + backend + dashboards) is **overkill** for a single-user desktop app — it's built for
fleets of microservices. What's actually useful:
1. **The data model, not the infrastructure.** W3C-format `trace_id`/`span_id` propagated through
   brain→tools→voice via `contextvars`, attached to every log line. That's 90% of the value at ~1% of the cost.
2. **A JSONL span exporter.** `opentelemetry-sdk` with a file exporter (or 20 lines of custom code writing
   spans to the existing JSONL event log) gives replayable per-turn timelines with zero servers.
3. **Selective manual instrumentation only:** wrap ~6 boundaries — `turn`, `wake`, `stt.transcribe`,
   `brain.respond`, `tool.exec`, `tts.speak`. Auto-instrumentation packages (`opentelemetry-instrument`) are
   for web frameworks; skip them.

### JARVIS application
- The existing event bus (`eventbus.py`) already gives every event an `event_id`. The gap: events from one
  turn aren't linked. Fix = a `trace_id` set at wake/turn-start, propagated to every event and tool call.
- Voice-stage latency attribution: which stage blew the 2s "feels instant" budget? (V8 stage graph already
  declares the stages; traces measure them.)
- Cost accounting: Anthropic's pattern puts cumulative token counts on `span.model_request_end` events so
  cost tracking survives crashes (diamond-1, §2).

### Libraries
- `opentelemetry-api` + `opentelemetry-sdk` (Apache-2.0, PyPI). Use the API for instrumentation, SDK only
  for the file/console exporter. Skip `opentelemetry-instrumentation-*` auto-packages.
- Lighter alternative: hand-rolled `contextvars`-based trace context (~50 lines) writing to the existing
  JSONL log. Zero dependencies, no SDK weight. [MC — worth prototyping before committing to the SDK.]

### Official references
- https://opentelemetry.io/docs/languages/python/instrumentation/ (manual instrumentation)
- https://opentelemetry.io/docs/languages/python/getting-started/ (tracer setup, exporters)
- W3C Trace Context: traceparent format (`00-<trace-id>-<span-id>-<flags>`)

### Limitations / trade-offs
- SDK adds import weight and a background `BatchSpanProcessor` thread — fine on desktop, but it's a thread
  that can deadlock on interpreter shutdown if not closed; always call `tracer_provider.shutdown()`.
- Spans without a viewer are write-only: if nobody reads the JSONL, it's pure overhead. Pair with a tiny
  local viewer (the HUD diagnostics tab) or don't bother.
- Attribute cardinality: don't put user utterances or tool outputs in span attributes unfiltered — that's
  the log-privacy problem in another costume (see §2).

### Security / privacy
- Traces contain the same sensitive data as logs (utterances, file paths, tool args). Local-only storage,
  same rotation/deletion policy as logs. Never export to a cloud backend without explicit opt-in.

### Common failure modes
- Forgetting `shutdown()` → lost spans on exit and shutdown hangs.
- Trace context leaking across turns (contextvars not reset) → two conversations merged into one trace.
- Over-instrumentation: a span per loop iteration = 10k spans/turn = unusable noise.

### Confidence / unknowns
- [HC] on the data model and the "model not infrastructure" verdict. [MC] on whether the OTel SDK or
  hand-rolled contextvars wins — needs a prototype. Unknown: exact per-turn overhead of the SDK's batch
  processor on a 6-core Ryzen (likely <1ms/turn, unmeasured).

---

## 2. Structured Logging Done Right

### Purpose
Logs are the only witness when the user reports "it did something weird yesterday." Structured (JSON) logs
are machine-grepable: `{"event":"tool.exec","tool":"read_file","ms":42,"trace_id":"…"}` beats regexing
prose. For a personal agent the log is also the audit trail (what did it touch on my PC?) and the raw
material for crash forensics.

### How it works internally
- **structlog** (the reference implementation): a pipeline of *processors*. Each log call passes a dict
  through `add_log_level → TimeStamper → [your processors] → renderer`. Dev renderer = colored console;
  prod renderer = `JSONRenderer` → one JSON object per line (JSONL).
- stdlib `logging` alternative: `python-json-logger` formatter on a normal `Handler`. Less ergonomic
  (no bound context), zero new concepts.
- **Bound loggers:** `log.bind(trace_id=…, turn=3)` returns a logger that attaches those fields to every
  subsequent call — this is how correlation IDs ride along for free.
- **Rotation:** `logging.handlers.RotatingFileHandler` (size-based, e.g. 1MB × 3 backups) or
  `TimedRotatingFileHandler` (daily). v1's `logger.py` already does rotating `jarvis.log` — keep the pattern.
- **Secrets redaction:** a structlog processor that scans values against a denylist of key names
  (`*key*`, `*token*`, `*secret*`, `*password*`) and replaces matches with `"[REDACTED]"`. The hardened
  tool runner (SEC8, 13/13 attack tests) already redacts; the logging layer needs the same processor so a
  `log.info("brain config", config=cfg)` can never leak a key.

### What to log vs never log
| Log (INFO) | Log (DEBUG, dev only) | NEVER log |
|---|---|---|
| Lifecycle: startup stages, shutdown, config validation results | Full LLM prompts/responses | API keys, tokens, secrets (any form) |
| Turn boundaries: wake, turn start/end, latency totals | Per-token streaming chunks | Full file contents read by tools |
| Tool calls: name, args schema-validated, ms, ok/fail | Raw tool stdout | Audio bytes / transcripts of bystanders |
| Fallback triggers: which provider, why (B1) | KV-cache stats | Passwords typed anywhere |
| Health transitions: OK→DEGRADED→OK | Event-bus replay details | Anything from `secrets.local.yaml` |

### JARVIS application
- One JSONL log file, rotation 1MB × 5, plus a human-readable console renderer in dev.
- Every line carries `ts`, `level`, `event`, `trace_id`, `component`. That's the whole schema — resist
  adding fields per call site.
- Crash forensics chain: `faulthandler` dump (see §6) → last 200 log lines → JSONL event log replay (S4).
  Three layers, each catching what the layer above missed.

### Libraries
- `structlog` (MIT, PyPI) — the pick. `python-json-logger` if stdlib-only is required.
- stdlib: `logging.handlers.RotatingFileHandler`, `logging.handlers.QueueHandler` + `QueueListener`
  (decouples logging I/O from the voice hot path — see failure modes).

### Official references
- https://www.structlog.org/en/stable/getting-started.html
- https://docs.python.org/3/library/logging.handlers.html (RotatingFileHandler, QueueHandler)
- structlog processor docs: `structlog.processors.JSONRenderer`, `TimeStamper`

### Limitations / trade-offs
- JSON logging costs ~µs per call — negligible, *except* in the audio callback hot path (48kHz). Never log
  inside the mic/speaker callback; aggregate and log per second.
- Disk: 1MB × 5 is ~2 weeks at JARVIS volume. DEBUG in production would 100× that — keep DEBUG behind a
  flag that needs a restart (prevents accidental disk fill).
- Structured logs are only as good as the `event` vocabulary. Free-text messages (`log.info("hmm, weird")`)
  defeat the purpose — enforce a fixed event-name list in code review.

### Security / privacy (the big one)
- **Logs contain user data by design** (utterances, commands, file paths touched). Threat model: someone
  with the laptop reads `jarvis.log`. Mitigations: logs live in `%APPDATA%/JARVIS` (user profile, not
  shared), rotation bounds the history window, a Settings toggle "detailed logging" + "delete logs" button
  (R13 privacy-safe defaults), and redaction processors as above.
- Never ship logs anywhere (no telemetry upload) without explicit opt-in. This is a product promise, not
  just engineering.

### Common failure modes
- Logging inside a lock / inside the audio thread → deadlock or dropouts. Fix: `QueueHandler`.
- An exception *inside* a redaction processor → logging itself crashes the turn. Processors must be
  total functions (try/except → pass through unredacted is *wrong*; fail-closed = drop the field).
- Log file locked by a crashed previous instance → new instance can't open it. Fix: open with
  `delay=True`, or per-boot log filenames (`jarvis-2026-10-19.log`).

### Confidence / unknowns
- [HC] on structlog + JSONL + rotation + redaction as the design. [MC] on `QueueHandler` necessity —
  depends on measured logging volume in the audio path (unmeasured). Unknown: best retention window the
  user will accept (ask: 7 days? 30 days?).

---

## 3. Metrics That Matter for JARVIS

### Purpose
Evals (I2/DeepEval) answer "is the brain good?" **Metrics answer "is the system healthy right now?"**
A personal agent needs a handful of runtime numbers, not a Grafana farm: did tasks succeed, how slow did
it feel, which fallbacks fired.

### The metric set (small on purpose)
| Metric | Type | Why |
|---|---|---|
| `turns_total` / `turns_failed_total` | Counter | Task success rate = 1 − failed/total. The single top-line health number. |
| `tool_calls_total{tool, ok}` | Counter | Tool-call accuracy per tool; catches a degrading skill. |
| `turn_latency_seconds` | Histogram | p50/p95 time from wake to first audible word. The "feels instant" number. |
| `stage_latency_seconds{stage}` | Histogram | Per-stage (wake, stt, brain, tool, tts) — finds *which* stage blew the budget. |
| `brain_fallback_total{from,to,reason}` | Counter | Fallback triggers (B1) — silent fallback storms are invisible without this. |
| `wake_false_positive_total` | Counter | Wake-word quality over time (V4 threshold tuning needs this). |
| `tts_interrupted_total` | Counter | Barge-in rate — distinguishes engaged users from a broken echo guard. |
| `memory_rss_bytes`, `gpu_vram_bytes` | Gauge | 16GB RAM / 6GB VRAM constraints — alert before OOM, not after. |

### How it works internally
- **Prometheus data model:** Counter (only up), Gauge (up/down), Histogram (bucketed observations →
  server-side `histogram_quantile()`), Summary (client-side quantiles, *not* aggregatable).
- **Critical Python-client fact** (verified in docs): the Python `prometheus_client` **does not compute
  quantiles locally** — a `Summary` exposes only `_count`/`_sum`. If you want p95, use a **Histogram**
  (with buckets tuned to voice latencies: `[0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10]`) — or skip Prometheus
  types and compute percentiles in-process.
- **For one desktop app, Prometheus itself is overkill** (no scraper, no server). The pragmatic shape:
  an in-process registry (dict of counters/gauges + small histograms) flushed to the JSONL log or a
  `metrics.json` snapshot every 60s. p50/p95 computed from a bounded reservoir (e.g. last 1,000
  observations) — no `t-digest` dependency needed at this volume.
- Golden Signals (Google SRE) map cleanly: latency (histograms), traffic (turns counter), errors
  (failed counter), saturation (RSS/VRAM gauges).

### JARVIS application
- Success-rate definition needs care: a turn "succeeds" if the user didn't rephrase/repeat within 30s
  (implicit) or the task's own verification passed (explicit). Log both; report explicit.
- Fallback metric closes the B1 loop: the recipe says retryable=transport-errors-only — the counter
  proves it's behaving that way in the wild.
- HUD diagnostics tab reads `metrics.json` — "last 24h: 97% success, p95 1.8s" is the dependability story.

### Libraries
- `prometheus_client` (Apache-2.0) if Prometheus-compatible exposition is ever wanted; otherwise
  hand-rolled (~80 lines) is lighter and honest about the single-process reality.
- `psutil` (BSD) for RSS/CPU; `pynvml` (NVIDIA) for VRAM — both needed for the saturation gauges.

### Official references
- https://pypi.org/project/prometheus-client/ (metric types; "Python client doesn't store quantile info")
- Google SRE Book, "Monitoring Distributed Systems" (the four Golden Signals)
- https://prometheus.io/docs/practices/histograms/ (bucket design; cumulative counting)

### Limitations / trade-offs
- Cardinality: labels like `{tool="read_file"}` are fine (~40 tools); labels with user data
  (`{utterance="…"}`) are a memory leak — never.
- In-process percentiles from a reservoir are approximate; fine for a HUD, not for an SLA.
- Metrics without alerts are decoration — but a desktop app has no alerting pipeline; the "alert" is the
  HUD status dot + log line. Design for that.

### Security / privacy
- Metric *labels* must never contain PII. `stage="stt"` good; `transcript="…"` catastrophic.

### Common failure modes
- Counter reset on restart misread as "traffic dropped to zero" — document that counters reset per boot.
- Histogram buckets copied from a web-service example (`[0.005, …, 10]`) — voice latencies live in
  0.1–5s; mistuned buckets make p95 unreadable.
- Measuring everything → measuring nothing. The 8-metric table above is the cap; new metrics need a
  written reason.

### Confidence / unknowns
- [HC] on the metric set and the Histogram-over-Summary rule. [MC] on hand-rolled vs `prometheus_client`
  — lean hand-rolled for v2 (single process, no scraper). Unknown: the exact "turn succeeded" heuristic
  thresholds (needs real usage data).

---

## 4. Health Checks and Graceful Degradation

### Purpose
"Healthy" for a voice assistant isn't "process is alive" — a wedged audio thread is alive and useless.
Health checks answer *can it do its job right now*, and graceful degradation decides *what it stops doing
first* when the answer is "partially."

### What "healthy" means for JARVIS (checklist)
1. **Brain:** model loaded, VRAM headroom > 500MB, inference round-trip < 30s on a canary prompt.
2. **Audio in:** mic device present, VAD producing frames (silence ≠ dead — check device callbacks fire).
3. **Audio out:** TTS engine responds to a canary synthesis (or last-success timestamp fresh).
4. **Config:** `config.yaml` + `settings.local.yaml` parse; required keys present (R7 validation doubles as
   a health check).
5. **Disk:** log dir writable, > 1GB free (models/logs shouldn't OOM the disk).
6. **Network (soft):** cloud providers reachable — failure here degrades, never kills (local-first).

Checks 1–5 are **liveness-critical** (fail = restart-worthy); 6 is **readiness-soft** (fail = degraded mode).

### How it works internally
- **Startup preflight** (R12): run the checklist *before* showing the HUD. Fail fast with error+suggestion+action
  (U2) — e.g. "No microphone found → [Open sound settings]". v1's stage markers in `jarvis_app.py` are the
  skeleton; preflight makes each stage a *gating* check.
- **Runtime watchdog (internal):** a heartbeat thread. Each subsystem (audio, brain, scheduler) updates
  `last_ok[component] = now` on its hot path. Watchdog wakes every 5s; any component silent > 30s →
  `faulthandler.dump_traceback_later`-style diagnostic dump (see §6) + attempt soft restart of that
  component, else escalate to full restart. This is the poor-man's supervisor *inside* the process.
- **Runtime watchdog (external):** Windows has no systemd. Options: **NSSM** (nssm.cc, auto-restart on
  crash, I/O redirection — but note: upstream inactive since ~2018; community forks active), **WinSW**
  (XML-configured service wrapper), or **Task Scheduler** ("on event: application error" trigger → relaunch).
  For a GUI desktop app the honest default is simpler: single-instance `QLockFile` (v1 has it) + Task
  Scheduler "at logon" entry + a "restart on crash" relaunch shim that re-execs `JARVIS.exe` if the exit
  code was abnormal. Services can't easily show a GUI/HUD — don't service-ify the HUD process.
- **Graceful degradation ladder** (design the failure paths *ahead of time*):
  `cloud brain → local brain → cached/templated replies` · `voice I/O → text chat` · `full HUD → tray icon` ·
  `proactive screen-watch → off`. Each rung is a declared, tested mode — not an accident.
- **Circuit breakers** (already proven, I4) are the per-dependency mechanism; the ladder is the
  product-level policy that reads breaker states.

### JARVIS application
- Preflight checklist on every boot; results on the HUD diagnostics tab ("Mic ✓ · Brain ✓ (qwen3.5:9b, 4.2GB
  VRAM) · Cloud: degraded (Groq 429)").
- Degradation must be *announced* in butler voice, once: "Sir, I've lost the cloud connection; running
  fully local until it returns." Silent degradation destroys trust.
- The "honest UX" requirement (R12): never show a green dot when degraded.

### Libraries / tools
- NSSM (https://nssm.cc/) — service wrapper, auto-restart. WinSW as alternative.
- stdlib: `threading` heartbeat, `faulthandler.dump_traceback_later()`, `atexit`.
- `psutil` for the resource half of health checks.

### Official references
- https://nssm.cc/scenarios, https://nssm.cc/description (restart-on-crash semantics)
- https://docs.python.org/3/library/faulthandler.html (`dump_traceback_later` as deadlock detector)
- Martin Fowler, "CircuitBreaker" (pattern); Google SRE workbook (health-check design)

### Limitations / trade-offs
- Watchdogs can only detect what they check. A brain that returns fluent garbage passes every liveness
  check — that's an *eval* problem (I2), not a health problem. Don't conflate them.
- External restart loses in-memory state → needs crash recovery (§6) to be worth anything. Restart
  without resume is just a fancier crash.
- NSSM/WinSW run as services (no interactive desktop in modern Windows) — wrong tool for the HUD
  process; right tool for a headless helper if v2 ever splits one out.

### Security / privacy
- Health endpoints must be local-only. A `GET /healthz` on 0.0.0.0 is a fingerprinting/info-leak surface
  (and echoes CVE-2026-65105 localhost-hijack thinking, SEC2). Bind 127.0.0.1 or skip HTTP entirely —
  the HUD reads health from shared memory/files.
- Canary prompts must be fixed strings, never user data.

### Common failure modes
- Watchdog restarting a component that's *slow*, not dead (model loading takes 40s on first boot) →
  restart loops. Fix: separate "starting" grace period from "running" checks.
- Health check that *itself* crashes (e.g. pynvml import fails on non-NVIDIA) → the checker must be the
  most defensive code in the system.
- Flapping: cloud 429s toggling degraded/OK every minute → hysteresis (require 3 consecutive failures to
  degrade, 5 consecutive successes to recover).

### Confidence / unknowns
- [HC] on the checklist, the ladder, and announce-degradation. [MC] on NSSM vs Task-Scheduler-vs-shim —
  needs a decision with Owais (zero-terminal constraint favors the installer setting it up silently).
  Unknown: canary-prompt latency budget on the 2060 (measure at build time).

---

## 5. Profiling Python: Finding CPU/GPU Bottlenecks (16GB Constraint)

### Purpose
Guessing at bottlenecks is how you "optimize" the wrong function for a week. Profiling answers *where the
time/RAM actually goes* — on Owais's exact box (Ryzen 5 3600, 16GB RAM, RTX 2060 6GB), where every GB is
budgeted.

### The toolkit (each does one job)
| Tool | Type | Overhead | Best for |
|---|---|---|---|
| `cProfile` (+ `pstats`/`snakeviz`) | Deterministic (every call) | High (2–5× slowdown) | Dev-time: exact call counts, who-called-whom |
| `py-spy` | Sampling (external process) | ~1% | **Prod-safe:** attach to the running JARVIS, flame graphs, `--native` for C extensions |
| `tracemalloc` (stdlib) | Allocation tracing | Low–moderate | Memory *leaks*: snapshot diffs show which line grew |
| `psutil` | OS counters | ~0 | Live RSS/CPU gauges (the §3 saturation metrics) |
| `pynvml` / `nvidia-smi` | GPU counters | ~0 | VRAM headroom — the 6GB budget enforcer |
| `memory_profiler` | Line-by-line RSS | High | Dev-time: which line allocates |

### How they work internally
- **cProfile:** hooks every call/return via `sys.setprofile`. Exact, but the hook cost distorts
  short-function timings and it can't see threads well. Rule: use for *structure* (call graph), not for
  *absolute* timings of tiny functions.
- **py-spy:** doesn't touch the target at all. It reads the process's memory from outside
  (`ReadProcessMemory` on Windows, `process_vm_readv` on Linux), finds the `PyInterpreterState`, walks
  each thread's `PyFrameObject` chain, and samples the stacks ~100×/s. Because the ABI changes per Python
  version, it ships bindgen-generated layouts per interpreter. Commands: `record` (flame graph SVG),
  `top` (live view), `dump` (all stacks *right now* — the "it's hung, what is it doing?" button).
  Needs permission to read process memory (same-user is usually fine on Windows; may need admin for
  service contexts).
- **tracemalloc:** tracks *Python* allocations with tracebacks. `take_snapshot()` → do work →
  `take_snapshot()` → `compare_to()` shows per-line growth. Start early (`PYTHONTRACEMALLOC=1` or
  `tracemalloc.start(25)` for 25-frame depth). Blind spot: C-extension allocations (numpy, torch, whisper)
  — it sees the Python wrapper, not the underlying buffer. For those, watch RSS via psutil.
- **GPU:** VRAM doesn't show in any Python profiler. `pynvml.nvmlDeviceGetMemoryInfo()` is the truth.
  Budget math for the 2060: model weights + KV cache + ~500MB headroom, else CUDA OOM mid-sentence.

### JARVIS application (the 16GB/6GB budget)
- Dev loop: `py-spy record -o profile.svg --pid <jarvis>` during a voice turn → flame graph shows
  whether the p95 blowup is STT, tokenization, or a chatty tool loop.
- Leak watch: `tracemalloc` snapshot every hour in a background thread; alert if Python-side growth >
  200MB/day with no new conversations (event log growing unbounded is the usual suspect — bound it, R6).
- VRAM guard: sample `pynvml` every 30s into the `gpu_vram_bytes` gauge (§3); if headroom < 300MB, refuse
  to load a second model / trigger the degradation ladder *before* CUDA OOMs.
- Known suspects from the failure analysis: unbounded `memory_bank/knowledge.json` growth (R6), the
  screen-watcher's RAM captures (Phase 6), per-turn context accumulation without compaction.

### Libraries
- `py-spy` (MIT, PyPI — prebuilt wheels; Rust binary, no compiler needed)
- stdlib: `cProfile`, `pstats`, `tracemalloc`
- `psutil` (BSD), `pynvml` (ships with NVIDIA driver bindings)

### Official references
- https://docs.python.org/3/library/profile.html (cProfile/pstats)
- https://docs.python.org/3/library/tracemalloc.html
- https://pypi.org/project/py-spy/ (how-it-works: external memory reading per OS)
- https://docs.nvidia.com/deploy/nvml-api/ (NVML)

### Limitations / trade-offs
- Sampling profilers lie about *rare* events (a 5ms spike sampled at 100Hz is usually missed) — they're
  for hotspots, not tail-latency forensics. Traces (§1) cover the tails.
- `py-spy --native` on Windows needs symbols for good C-stack resolution; Python-stack-only mode still
  answers "which Python function is hot."
- tracemalloc's per-allocation traceback storage *is itself* memory — don't run depth-25 in production;
  depth-1 or periodic snapshots only.

### Security / privacy
- `py-spy dump --locals` prints local variables — including anything in scope (utterances, file contents).
  Treat profiler output like logs: local-only, redacted before sharing.
- Memory-reading profilers are dual-use (same technique as game cheats/malware); on a hardened box they
  may trip AV. Document it in the installer notes.

### Common failure modes
- Profiling the wrong build (debug vs frozen PyInstaller exe — paths differ, flame graphs confuse).
- "Optimizing" GIL-bound threading: py-spy `top --gil` exists because threads *look* busy while
  serialized. For JARVIS: audio I/O threads are fine; the brain is one hot thread — don't thread the
  unthreadable, pipeline the stages instead (V8).
- Chasing RSS while the leak is in VRAM (or vice versa). Check both, every time.

### Confidence / unknowns
- [HC] on the toolkit and the VRAM/RSS split. [MC] on py-spy-on-Windows permission behavior for a
  PyInstaller-frozen app (needs a real test on Owais's PC). Unknown: actual per-turn allocation profile
  (measure at build time; the 200MB/day leak threshold is a starting guess, not a law).

---

## 6. Crash Recovery: Checkpointing, Resume, and `wake(sessionId)`

### Purpose
A crash must cost seconds, not the conversation. Recovery = **reconstruct enough state to continue the
user's task as if the crash didn't happen** — or, failing that, to explain exactly what was lost.

### What's already learned (skip-if-learned — referenced, not repeated)
- **Anthropic's `wake(sessionId)`** (diamond-1, SEC1, 95%/90%): session log lives *outside* harness and
  sandbox; new harness boots → `getSession(id)` → resumes from the last *event* (not the last turn —
  `emitEvent` per event). The session is the only stateful component; everything else is disposable.
- **JSONL event log + deterministic replay** (S4, `eventlog.py`): replay rebuilds state; handlers must
  reduce, never re-emit, during replay (`bus.replaying` flag).
- These two together *are* v2's R15 (external, interrogable session store). This section adds only the
  missing mechanics: checkpoints, crash *detection*, and the unhandled-crash layer.

### The missing mechanics
**Checkpoints (snapshots + offsets).** Replaying a 10,000-event day to recover is slow. A checkpoint =
serialized derived state (conversation summaries, task graph, scheduler queue) + the `event_id`/offset it
covers. Resume = load latest checkpoint → replay only events after it. Checkpoint cadence: every N events
(e.g. 50) or M minutes (e.g. 5), whichever first; always checkpoint *before* a destructive action (the
"ship undo" principle — snapshot first).
- **Atomicity:** write checkpoint to `checkpoint.json.tmp` → `os.replace()` (atomic on Windows/NTFS) →
  fsync the directory. A torn checkpoint is worse than none; the tmp+rename pattern (R6, proven in
  settings work, U7) applies.
- **SQLite alternative:** for structured state (tasks, scheduler), SQLite with `PRAGMA journal_mode=WAL`
  gives atomic commits for free: changes append to the `-wal` file with a commit marker; a crash
  mid-transaction leaves unmarked frames that recovery ignores; the next opener auto-recovers. WAL also
  lets the HUD read state while the brain writes. (Never delete the `-wal` file; back up with the
  backup API or `VACUUM INTO`.)

**Crash detection layers (inside → out):**
1. `sys.excepthook` — catches *uncaught Python exceptions* (v1 added this, `d2e7e06`). Write the traceback
   + last trace_id to the crash log, attempt checkpoint, then exit nonzero.
2. `faulthandler.enable(file=crash_log)` — catches *segfaults/aborts/deadlocks* that excepthook never
   sees (C extensions: whisper, TTS, Qt). Implemented in C, uses signal-safe functions only; also
   `dump_traceback_later(90, exit=True)` as the deadlock tripwire feeding the §4 watchdog.
3. `atexit` — best-effort graceful checkpoint on *clean* shutdown. Never rely on it for crashes (it
   doesn't run on SIGKILL/_exit).
4. External supervisor (§4) — notices the nonzero exit / silence and relaunches; the relaunched process
   runs **recovery-on-boot**: find latest checkpoint → replay tail of event log → announce "Sir, I had to
   restart — picking up where we left off."

**Resume semantics (the subtle part):**
- Resume at the *event* level: re-deliver unacknowledged events (tool calls whose results never landed).
- **Idempotency is mandatory:** a tool call replayed after a crash must not double-execute (no double
  file writes, no double messages). Every mutating tool needs an idempotency key (the event_id) and a
  "did this already happen?" check. This is the #1 thing crash recovery demands of the *rest* of the
  system.
- Non-idempotent external actions (sent a Telegram message, then crashed before logging it) need an
  outbox pattern: write intent → execute → mark sent. On resume, intents without "sent" are reconciled
  (check the outbox against reality), never blindly retried.
- What *can't* be recovered: in-flight TTS audio, a half-heard utterance. Honest UX: "I lost the last
  few seconds — could you repeat that?" beats confabulation.

### JARVIS application
- Recovery-on-boot is a v2 boot stage (after preflight, before HUD): `latest_checkpoint + replay_tail →
  resume or report loss`. Tie to the Moshi Utterance Record (V5): truncate claimed speech to what the
  TTS completion events prove was spoken — the brain must never "remember" saying words lost to a crash.
- Scheduler (I1/S-0) already wants write-before-reason; crash recovery makes it real: scheduled tasks
  are events in the log, so a crash mid-task resumes the task, not just the process.

### Libraries
- stdlib only: `faulthandler`, `atexit`, `sqlite3` (WAL via PRAGMA), `os.replace`.
- No new dependencies needed — this is the cheapest section to implement.

### Official references
- https://docs.python.org/3/library/faulthandler.html
- https://docs.python.org/3/library/sys.html (`sys.excepthook`)
- https://www.sqlite.org/wal.html (write-ahead logging, crash recovery semantics)
- diamond-1-managed-agents.md (wake/resume mechanics — the architecture this plugs into)

### Limitations / trade-offs
- Checkpointing costs write I/O per checkpoint; too frequent = disk churn on a laptop SSD, too rare =
  long replay. The 50-events/5-minutes starting point needs tuning against real log sizes.
- `faulthandler` output is minimal (ASCII, no source lines, 100-frame cap) — it's a coroner's report,
  not a debugger. Pair with the structured log tail.
- Resume can *never* be fully transparent for side-effecting tools; the outbox pattern adds latency to
  every mutating call. Accept it — correctness over speed for writes.

### Security / privacy
- Crash dumps may contain anything in memory (utterances, secrets). `faulthandler` file lives next to
  logs with the same protections; the "send crash report" dialog (if ever built) must show the user the
  *exact* contents before any upload — default local-only.
- Checkpoint files contain conversation state → same ACL/rotation policy as the event log.

### Common failure modes
- Checkpoint written *after* the event log advanced past it → replay double-applies. Fix: checkpoint
  stores the exact `event_id`; replay starts strictly after it.
- `os.replace` across filesystems (temp dir ≠ data dir) silently becomes non-atomic copy. Fix: tmp file
  in the *same directory*.
- Recovery code that itself crashes (corrupt checkpoint) → boot loop. Fix: recovery is wrapped; on
  failure, quarantine the checkpoint (`checkpoint.json.corrupt-<ts>`) and boot from event-log replay
  alone, telling the user.

### Confidence / unknowns
- [HC] on the four detection layers, tmp+rename atomicity, WAL crash semantics, and idempotency as the
  core requirement. [HC] on wake(sessionId) from the prior PhD (not re-derived here).
- [MC] on checkpoint cadence (needs measurement). Unknown: worst-case replay time for a full day's event
  log on the Ryzen 5 3600 (prototype and time it); whether NTFS `os.replace` + fsync gives the durability
  assumed (standard practice, untested here).

---

## Cross-topic connections (the connected understanding)

- **Traces (§1) → logs (§2):** `trace_id` is the join key. One ID answers "show me everything about the
  turn where it went wrong" across logs, spans, and metrics.
- **Metrics (§3) → health (§4):** gauges feed the watchdog; counters feed the degradation ladder
  (3 consecutive fallback failures → degrade cloud tier).
- **Profiling (§5) → metrics (§3):** the saturation gauges (RSS/VRAM) are profiling made continuous.
- **Logging (§2) → crash recovery (§6):** the log tail + faulthandler dump is the coroner's report;
  the event log is the resurrection.
- **Everything → R12/R6:** preflight validates what health checks monitor; atomic writes protect what
  checkpoints persist. Observability is how R1–R14 *prove* they're holding.

## Remaining gaps (for future missions)
1. Measure real per-turn overhead of the OTel SDK batch processor on the target box.
2. Prototype hand-rolled `contextvars` tracing vs OTel SDK — pick one with numbers.
3. Time full-day event-log replay; set checkpoint cadence from data, not guesses.
4. Decide the external supervisor (Task Scheduler vs shim) with Owais's zero-terminal constraint.
5. Define "turn succeeded" thresholds from real usage; set the leak-watch growth threshold from real data.
6. Retention policy for logs/traces/checkpoints — needs the user's call (7/30/90 days?).

*End of Domain S notes. Confidence overall: [HC] on designs and doctrine, [MC] on tuning constants —
every number with "starting point" next to it is a hypothesis awaiting measurement, per the
precision protocol.*
