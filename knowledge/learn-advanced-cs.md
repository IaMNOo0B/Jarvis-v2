# Advanced Computer Science — Scoped Learning for JARVIS (Domain X)

*Mission: learn each pattern AND give an honest verdict. JARVIS is a single-user local desktop app, not a distributed SaaS. Ruthless scope.*
*Already covered (skipped, not re-learned): in-process event bus + JSONL replay (`~/workspace/learning/architecture/eventbus.py`, `eventlog.py`); circuit breakers, safety state machine, backpressure stage graph (MASTER-INDEX I4); external session store R15 candidate (diamond-1). This file covers only what those don't.*
*Date: 2026-10-19. Sources are primary where possible; claims I couldn't verify are marked.*

**Verdict table (the whole page in one glance)**

| # | Pattern | Verdict for JARVIS |
|---|---|---|
| 1 | Event sourcing (production-grade) | **NEED it — lite** (event store + replay + snapshots, no EventStoreDB server) |
| 2 | CQRS (separate read/write models) | **SKIP it** (overkill; R15 session store covers the real need) |
| 3 | Durable local queue | **NEED it — lite** (SQLite WAL job queue, not Kafka/RabbitMQ) |
| 4 | Caching | **NEED it — selective** (embeddings + deterministic tool results; NO semantic LLM cache) |
| 5 | Fault domains / isolation | **NEED it** (voice/brain/UI/tool processes must fail independently; v1 crashed on all of these) |
| 6 | Multi-tenancy / horizontal scaling / distributed transactions | **Explicitly NOT build** (documented refusal) |

---

## 1. Event sourcing — what production-grade adds over our eventlog.py

### Purpose
Persistence strategy: instead of storing current state and overwriting it, store the *sequence of everything that happened*. Current state = fold(replay(events)). Fowler's litmus test: "at any time we can blow away the application state and confidently rebuild it from the log." (git is the canonical laptop example: `git log` is an event store, `git checkout` is replay, the working tree is a projection — no broker needed.)

### How it works (the production pieces beyond JSONL append)
1. **Event store**: append-only, immutable, per-aggregate event streams with sequence numbers and optimistic concurrency (write fails if stream version moved — replaces locking).
2. **Snapshots**: periodic saved state at sequence N; rehydration = load snapshot + replay only events after N. Without this, startup time grows linearly with history — the #1 practical cost of naive event sourcing.
3. **Projections / materialized views**: read-optimized views derived from the event stream (e.g. "conversation list", "memory index"). Rebuildable from scratch; throwaway.
4. **Event versioning / upcasting**: old events must stay readable as code evolves — upcasters translate v1→v2 events during replay. (The trickiest part in production; snapshots cap the pain since events older than a snapshot rarely need replaying.)
5. **Command → event separation**: commands are validated against current state, then *facts that happened* are appended. Replay applies events, never re-runs commands (our eventlog.py already does this correctly with the `replaying` flag).

### Honest verdict for JARVIS: NEED IT — LITE (no event-store server)
The value for JARVIS is exactly three things, none of which need a broker:
- **Crash recovery + time-travel debugging** (R15 territory): the session log outlives the process. On crash, `wake(sessionId)` rebuilds brain state, pending tool calls, and conversation. This is what the Anthropic diamond study validated at 95%.
- **Audit trail**: every mutating tool call recorded as a fact → the "undo everything" promise needs this to reconstruct prior state.
- **Projections for memory**: mem0/A-MEM style indexes are just projections of the event log; they can be rebuilt when corrupted (note: v1's non-atomic memory writes wiped memories — event-sourced memory would have survived).

Skip the enterprise machinery: **no EventStoreDB/Kurrent server, no Kafka, no saga orchestration**. A SQLite WAL-backed event table (seq, stream_id, type, payload, ts) + snapshots + projections-in-SQLite is the entire production stack at this scale. Greg Young (who coined CQRS/event sourcing) and the Azure architecture docs both treat the RDBMS-backed event store as the normal case; dedicated servers are for scale we don't have.

**Libraries (only if needed):** none required — stdlib `sqlite3` + a 200-line module. If we want a library, `EventStoreDB` Python client exists but requires the server (rejected).

**Official references:** martinfowler.com/eaaDev/EventSourcing.html; Microsoft Learn "Event Sourcing pattern" (Azure Architecture Center); Greg Young's original writings (CQRS.nu).

**Trade-offs:** replay correctness demands deterministic handlers (no wall-clock reads, no randomness without seeded values inside the reduce); event schema evolution is real work; a log that never compacts grows unboundedly → retention policy needed (e.g. snapshot per session, compact events older than N days into snapshots).

**Security implications:** the event log is a full-fidelity record of everything JARVIS did — tool args, web content, user messages. It must be: (a) encrypted at rest or at least ACL'd to the user account; (b) excluded from skill-upload/debug bundles; (c) covered by the same memory-deletion promise (user's "forget" must purge log entries too). An attacker who reads the log learns everything the user asked.

**Confidence:** [HC] on the mechanics (well-documented pattern, hands-on proven in track 2); [MC] on SQLite-vs-server sizing (fine for one user, unproven past ~10M events — but JARVIS won't reach that).

**Unknowns:** whether projections should live in the same SQLite file as the event store (simpler, lock contention on write-heavy phases) or a separate file (Rails' Solid Queue practice: separate DB for the queue). Decide at build time with a benchmark, not theory.

---

## 2. CQRS — separating reads from writes

### Purpose
Split the system into a **command side** (validate + mutate, returns only success/ID) and a **query side** (read-optimized, denormalized views, never mutates). Each side evolves, scales, and is optimized independently. Usually paired with event sourcing (events feed the read models) but doesn't require it.

### How it works
Commands → write model (normalized, rule-enforcing) → events → projectors → read models (denormalized per-UI-view, e.g. one table per screen). Reads never touch the domain model; queries can be raw `SELECT * FROM chat_view WHERE id=?`.

### Honest verdict for JARVIS: SKIP IT
Why it exists: (a) read/write workloads that scale *independently* (thousands of browsers, few purchasers), (b) teams large enough to own each side, (c) query shapes that don't match the domain model. JARVIS has exactly one reader, one writer, and the same process. The independent-scaling argument is void; the "different query shapes" argument is handled by 2–3 SQL views, not an architecture pattern. Fowler himself advises against it when CRUD suffices; one veteran's summary: "one app in 25 years required it; hundreds implemented it."

The real need people confuse with CQRS is **eventual consistency between brain state and derived indexes** (e.g. memory projection lagging the log). Handle that with explicit projection-refresh semantics, not with a command/query split.

**Partial credit to keep:** the one durable idea — commands return *outcomes not data*, and read paths never mutate. Enforce as a code convention (`queries.py` vs `commands.py`), not as infrastructure.

**Confidence:** [VC] — the rejection case is the well-documented consensus; keeping it would be CV-driven engineering, the exact thing Owais hates.

**Unknowns:** none material.

---

## 3. Message queues — when a local queue beats in-process pub/sub

### Purpose
Decouple "work requested" from "work executed" with **durability across crashes**: if the process dies between enqueue and completion, the work survives and resumes. In-process pub/sub (our EventBus) loses everything on crash — it is a *routing* mechanism, not a *durability* mechanism.

### How it works (the local version)
The **transactional outbox / queue-table pattern**: a SQLite table `jobs(id, queue, payload, status, attempts, run_at, created_at)`. Enqueue and mark-complete happen inside the same SQLite transaction as the state change → crash-safe by construction. A dispatcher polls (or is notified) and executes. Failed jobs retry with backoff; poison jobs get quarantined after N attempts (same discipline as our circuit-breaker work).

SQLite WAL mode matters here: WAL gives concurrent readers + one writer, atomic commits, and crash recovery without a journal-replay dance. Rails 8's Solid Queue runs production background jobs on SQLite with this exact pattern (separate queue DB file from primary DB to avoid write contention).

### Honest verdict for JARVIS: NEED IT — LITE (SQLite queue table, not a broker)
JARVIS's durable-work needs are real and small:
- **Scheduled/proactive tasks** (reminders, routines, "check this every hour"): the scheduler spec I1's "write-before-reason" is a queue by another name. A cron tick that crashes mid-task must resume, not vanish.
- **Long-running tool work** (multi-step research, downloads): enqueue → survive restart → resume.
- **The outbox for side effects**: Telegram replies, notifications — send-attempt recorded before sending, so a crash doesn't double-send or silently drop.

What we do NOT need: Kafka/RabbitMQ/Pulsar (no network, no consumers across machines, no backpressure at scale — our backpressure stage graph already handles in-process flow control).

**Libraries:** none — a ~150-line `queue.py` on `sqlite3` with WAL. (If we ever want a library: `arq`/`dramatiq` are overkill here; `huey` with SQLite is the lightest real option, still unnecessary.)

**Official references:** SQLite docs on WAL mode (sqlite.org/wal.html); Solid Queue design (Rails guides, background jobs); Martin Kleppmann's *Designing Data-Intensive Applications* ch. 11 (stream processing / outbox) for the theory.

**Trade-offs:** polling adds latency (mitigate: 100ms–1s poll + `threading.Event` wake on enqueue); SQLite is single-writer — keep transactions short; poison-job quarantine needs a dead-letter convention or jobs silently clog the queue.

**Security implications:** the queue holds *pending actions*, including mutating tool calls. Queue DB must have the same protections as the event log (see §1). Also: on restart, re-executed jobs must be **idempotent** (or keyed by idempotency key) or a crash-restart double-fires actions. This is the concrete form of the autopsy's "restart" failure class.

**Confidence:** [HC] — pattern is standard, Rails 8 runs it in production, SQLite WAL semantics are documented and stable.

**Unknowns:** exact poll interval vs battery impact on a laptop (measure; wake-on-enqueue mitigates).

---

## 4. Caching and invalidation

### Purpose
Don't recompute what's already known. For an LLM agent the expensive resources are: cloud API tokens (money + latency), embedding compute, and repeated tool I/O.

### What JARVIS should cache (verdict per item)

| Cache | Verdict | Invalidation rule |
|---|---|---|
| **Static prompt prefixes** (system prompt, persona, skill definitions) | **YES — prompt caching first.** Provider-level (Anthropic 5–60min TTL, OpenAI automatic) cuts 50–90% of repeated-prefix cost. Zero code: tag the stable prefix. | TTL by provider; bump cache-version key on persona/skill updates. |
| **Embeddings** (document chunks, memory vectors) | **YES.** Embed once, store beside the content. Standard practice; content-addressed (hash of chunk) so invalidation is automatic on change. | Content hash as key — changed content = new hash, no stale reads possible. |
| **Deterministic tool results** (file hashes, `git status`, weather with TTL, package versions) | **YES, narrow.** TTL-keyed or event-invalidated (file-watcher → drop file caches). | TTL for external data (weather: 15min); event-driven for local files (write event → invalidate). |
| **Semantic LLM response cache** (serve past answers to similar questions) | **NO for the chat brain.** Reasons: (1) multi-turn conversation changes meaning of every follow-up — the failure mode is serving a confident wrong answer; (2) personalization (memory-grounded answers) makes "similar question" ≠ "same answer"; (3) one user ≠ the repetitive-query workloads where 30–50% hit rates pay off. The 0.95-threshold discipline that makes it safe in support bots doesn't transfer to a personal agent whose answers depend on evolving memory. | N/A — don't build. |
| **Model/KV artifacts** (compiled wake-word models, tokenizer caches) | **YES, trivially.** Disk cache of built artifacts; rebuild only when source changes (mtime/hash check). | Hash-keyed. |
| **Web search results** | **MAYBE — short TTL (minutes) within a single task.** A research task hitting the same query twice shouldn't pay twice. Never across sessions (staleness + the "current facts" problem). | Task-scoped, dropped at task end. |

### The invalidation doctrine (applies to every YES above)
1. **Content-addressed keys** where possible (hash of input) — invalidation becomes a non-problem.
2. **TTL** for external/time-varying data, with the TTL stated next to the cache, not buried.
3. **Event-driven invalidation** for local state: the event bus already emits the write events; subscribe a cache-invalidator to them. This is the concrete payoff of §1+§3 combined.
4. **Versioned cache namespaces** (`cache_v3:` prefix): on model/persona/schema upgrades, bump the version and let the old namespace expire — no flush logic needed.

### Official references
Redis "Prompt caching vs semantic caching" (redis.io/blog); GPTCache / LangChain caching docs for the mechanics; Phil Karlton's "two hard things" (naming things, cache invalidation, off-by-one errors) as the cultural anchor.

### Trade-offs
Cache hit = latency win; cache miss on a semantic cache *costs more* than no cache (embedding call + miss). Stale cache is a correctness bug that looks like a feature working. Every cache needs a hit-rate metric or it's unmaintainable — log hits/misses per cache from day one.

### Security implications
Caches are a **cross-context leakage surface**: a cached answer generated with one user's memory visible must never serve in a context where it isn't. For single-user JARVIS this is low-risk today, but the rule stands: cache keys include the identity/permission context, not just the query. Also expire sensitive content quickly (best-practice from the literature). Tool-result caches must respect the fs-jail: a cached read from `/allowed/` must not be served after the jail config changes.

### Confidence
[HC] on prompt caching + embedding caching (provider-documented, standard); [HC] on rejecting the semantic chat cache for a personal agent (the multi-turn/personalization argument is structural, not a tuning detail); [MC] on web-result task-scoped caching (useful but unproven in our stack).

### Unknowns
Anthropic/OpenAI prompt-cache TTL and pricing behavior at build time (re-verify — these change); whether local-model inference even benefits (it doesn't pay per token, so prompt caching is moot for ik_llama.cpp — KV-cache reuse across turns is the local equivalent, handled by the server).

---

## 5. Fault domains — what can fail independently in JARVIS, and how to isolate

*Unification note (Cycle 18): fault domains, the degradation ladder, and SLOs are canonically specified in `learn-reliability-spec.md` (Cycle 12, §18 #10) — this section is the analysis; that file is the spec. Edit analysis here, targets there.*

### Purpose
A fault domain is a unit that can fail without taking the rest down. Design rule: enumerate them, then make each one's failure *contained, detectable, and degradable*.

### JARVIS's fault domains (and v1's evidence for each)
| Domain | What fails | v1 evidence | Isolation design |
|---|---|---|---|
| **UI/HUD (Qt)** | Qt event-loop crash, GPU driver issue | v1's `_report_crash` missed Qt-loop crashes — whole app died silently | UI is a *client* of the core, not the core. Core runs headless (`--no-hud`); UI reconnects. Watchdog restarts UI only. |
| **Voice pipeline** (wake, VAD, STT, TTS) | mic driver, model load OOM, TTS backend down | echo-guard dead code; barge-in muted all future speech | Voice as plugin process (R1): core works fully in text mode; voice crash → text fallback with a calm message, never a dead app. |
| **Brain** (local LLM server) | OOM, model load fail, llama-server crash | fallback chain never triggered on transport errors (C-B1) | Brain behind the OpenAI-compatible interface (B5): server crash → circuit breaker → cloud provider → honest "brain unavailable" state. Health-check endpoint, restart policy. |
| **Tools/skills** | skill crash, infinite loop, malicious skill | unsandboxed `execute_code` = RCE | Per-skill: timeout + subprocess/memory sandbox + circuit breaker (I4, SEC8). One skill's failure is a failed tool call, not an app crash. |
| **Network/providers** | DNS, 429s, key revocation | no retry/rotation discipline (C-B1) | Provider abstraction + per-provider circuit breaker + key rotation; offline-first: local brain keeps answering. |
| **Storage** (SQLite, event log, memory) | disk full, corrupt file, locked DB | non-atomic writes wiped memories/settings (C-B4) | Atomic writes + backups (R6); storage failure → read-only degraded mode with honest banner, never silent data loss. |
| **Scheduler/proactive** | malformed time string killed the whole app | v1: one bad string = no startup | Scheduler runs in its own domain; its crash is logged + surfaced, never fatal to chat. |

### The patterns (borrowed, not invented)
- **Bulkhead** (from shipbuilding via Hystrix): partition resources so one domain can't starve others — e.g. voice gets its own thread pool/GPU budget; a runaway STT can't block the chat loop. *This* is the pattern behind "minimal GPU/CPU energy" thinking: budgets per domain.
- **Circuit breaker**: already hands-on proven (I4) — use per provider, per skill, per TTS backend.
- **Graceful degradation ladder**: full → text-only → read-only → honest "I can't" — each rung is a designed state, not an accident. The Error UX doctrine (U2) gives the user-facing copy.
- **Watchdog + single-instance lock**: already in v1's launch hardening — keep, extend to per-domain heartbeats.

### What NOT to do
Don't isolate by *process-per-everything* on day one — IPC complexity is its own fault domain. Start with: core process + voice plugin process + brain server process (the three with different crash/OOM profiles), threads + bulkheads inside the core. Promote a domain to its own process only after it crashes the core once (evidence-driven, not speculative).

### Confidence
[HC] on the domain list (each grounded in a v1 autopsy finding); [MC] on the 3-process topology (right instinct, unproven in our stack — validate with fault-injection tests like track 3's).

### Unknowns
Exact GPU-budget partitioning on the 6GB card when voice + brain coexist (measure at voice-plugin build time); whether Qt can truly run as a detachable client without major overlay.py surgery (spike needed).

---

## 6. What to explicitly NOT build (and why)

| Pattern | Why it's wrong for JARVIS |
|---|---|
| **Multi-tenancy** | One user, one machine, one trust boundary. Tenant isolation (row-level security, per-tenant quotas, noisy-neighbor protection) solves a SaaS problem. Cost if built: every query gains a tenant filter, every cache key a tenant prefix, security review doubles — for zero users gained. |
| **Horizontal scaling** (more machines for more load) | Load = one human typing. Vertical headroom (a bigger GPU) is the only scaling axis, and even that is bounded by the 6GB card. Sharding, consensus, and leader election are pure cost. |
| **Distributed transactions / sagas / 2PC** | Transactions here are single-SQLite-file ACID. A "saga" for "send Telegram message + write memory" is handled by the local outbox (§3) — no coordinator, no compensating transactions across services. |
| **Service mesh / API gateway** | No services to mesh. The OpenAI-compatible brain interface (B5) is the entire "gateway." |
| **Full CQRS with separate read/write stores** | §2 verdict stands — views in SQLite are the read model. |
| **Kubernetes / container orchestration** | One Windows process tree. The installer + process supervisor (already in v1: single-instance lock, watchdog) is the deployment story. |
| **Event streaming platform (Kafka/Pulsar)** | §3: a SQLite queue table is the whole streaming platform at this scale. |

**The meta-rule (for the playbook):** every distributed-systems pattern must pass the test — *"which failure that JARVIS will actually experience does this prevent?"* If the answer is "a failure mode of a 10,000-user SaaS," it doesn't get built. The autopsy's 210 findings are all single-process failures; the architecture should answer those, not hypothetical scale.

**Confidence:** [VC] — this is the highest-confidence section; building any of these would be the textbook "smart-work" violation (solving someone else's problem).

---

## Cross-links to existing knowledge
- Event store design → extends `eventlog.py`; durability → R6 (atomic writes); crash recovery → R15 (Anthropic `wake(sessionId)`).
- Queue → scheduler spec I1 (write-before-reason); idempotency → autopsy restart-failure class.
- Cache invalidation via events → the event bus (S4) earning its keep.
- Fault domains → R1 (text core, voice plugin), R11 (skill circuit breakers), U2 (error UX copy for each degraded rung).
- The NOT-build list → v2 thesis #3 ("dependable beats impressive") and Owais's "no ruckus" rule.

## Remaining unknowns (honest scope)
1. SQLite event-store sizing past ~10M events — irrelevant until it isn't; add a counter + warning at 1M.
2. Three-process topology validation — fault-injection spike at build time.
3. GPU budget partitioning on 6GB with voice+brain — measure, don't model.
4. Provider prompt-cache TTL/pricing at build time — re-verify (changes often).
5. Poll interval vs laptop battery for the queue dispatcher — measure with wake-on-enqueue.
