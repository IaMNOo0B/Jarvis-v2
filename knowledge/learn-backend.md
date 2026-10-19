# Backend & APIs — Learning Notes (Domain O)

*JARVIS master curriculum, domain O. Learning only — no implementation.*
*Researched 2026-10-19. Official docs preferred; nothing fabricated. Confidence tags: [VC] >95%, [HC] 80–95%, [MC] 60–80%, [SP] 40–60%, [UK] unknown.*

---

## O1. FastAPI production patterns for a LOCAL personal-agent server

### Purpose
FastAPI is the Python framework for building the HTTP control plane of JARVIS v2: a localhost API server that the chat UI, HUD, skills, and tools talk to. It's built on Starlette (ASGI) + Pydantic v2 — async by default, with automatic request validation and OpenAPI docs.

### How it works internally
- **ASGI, not WSGI**: one event loop handles many concurrent I/O-bound requests via `async/await`. A single Uvicorn worker is fine for a single-user local server; CPU-bound work (inference, audio) must never run on the event loop — use `asyncio.to_thread` or a process pool. [VC]
- **Request pipeline**: route → dependencies (`Depends`) → Pydantic validation of path/query/body → endpoint → Pydantic serialization of response model → JSON. Validation failures return 422 automatically, before your code runs. [VC]
- **Dependency injection**: `Depends()` provides request-scoped resources (DB sessions, auth checks, settings). Generator dependencies (`yield`) give setup/teardown semantics — the code after `yield` runs like a `finally` block. This is where auth gating and resource cleanup live. [VC]
- **Lifespan management**: `@asynccontextmanager def lifespan(app)` passed as `FastAPI(lifespan=lifespan)`. Everything before `yield` = startup (validate config, open DB pools, start scheduler); everything after = shutdown (close pools, cancel background loops, flush buffers). Replaces the deprecated `@app.on_event("startup"/"shutdown")` — the context manager guarantees cleanup runs even if startup fails partway. [VC — https://fastapi.tiangolo.com/advanced/events/]
- **Pydantic v2**: Rust-based `pydantic-core` engine (5–50× faster than v1). API changes from v1: `.dict()` → `model_dump()`, `.parse_obj()` → `model_validate()`, `class Config` → `model_config = ConfigDict(...)`, `@validator` → `@field_validator`. Strict mode (`StrictStr`, etc.) rejects coercions — use it for tool arguments where "123" must not silently become `123`. [VC — https://pydantic.dev/docs/validation/2.7/get-started/migration/]
- **BackgroundTasks**: `background_tasks.add_task(fn, ...)` runs after the response is sent. It is **fire-and-forget in-process** — NOT a queue. Under load, background tasks compete with request handling on the same loop. [HC]

### JARVIS application
- v2's control plane: bind **127.0.0.1 only** (never 0.0.0.0 — see SEC2 localhost-hijack study). Endpoints for chat, tool execution, memory, settings, scheduler.
- Pydantic models are the **R2 enforcement point**: every tool call's arguments are validated by a strict schema *before* the LLM's judgment is trusted. "Verify before claiming, operationalized" (AGENTS.md).
- Lifespan: startup validates config (fail fast on malformed settings — R7), opens SQLite, starts APScheduler; shutdown cancels loops, closes pools, flushes the event log (R15 candidate).
- BackgroundTasks: fine for "send a desktop notification after responding." Anything durable (reminders, digests, retries) goes to the persistent queue (O4), never BackgroundTasks.

### Best libraries
| Need | Pick | Why |
|---|---|---|
| Server | `uvicorn[standard]` | Reference ASGI server; `--loop uvloop` on Linux (Windows: default asyncio) |
| Validation | `pydantic>=2` | Core of FastAPI; strict mode for tool args |
| Settings | `pydantic-settings` | Env/dotenv → typed config, fail-fast validation |
| HTTP client (outbound) | `httpx` | Async, per-stage timeouts (connect/read/write/pool) |

### Official docs
- Lifespan: https://fastapi.tiangolo.com/advanced/events/
- Dependencies: https://fastapi.tiangolo.com/tutorial/dependencies/
- Background tasks: https://fastapi.tiangolo.com/tutorial/background-tasks/
- Pydantic v2 migration: https://pydantic.dev/docs/validation/2.7/get-started/migration/
- Pydantic settings: https://docs.pydantic.dev/latest/concepts/pydantic_settings/

### Limitations / trade-offs
- Single-process async: one blocking call (e.g., `time.sleep`, sync subprocess) stalls ALL requests. Discipline required everywhere. [VC]
- BackgroundTasks die with the process — a crash mid-task loses the work silently. [VC]
- OpenAPI/Swagger at `/docs` is a local-info-leak surface; gate or disable it on any non-dev build. [HC]
- FastAPI version churn is real (~0.11x→0.14x in the 0.x line); pin in `uv.lock`/requirements at build time. [MC on exact current version]

### Security implications (matters most)
- **Bind 127.0.0.1, add auth on loopback anyway** (SEC2: DNS rebinding can make a browser talk to your "localhost" server). [VC]
- Never trust `X-Forwarded-For`/`Host` headers on a local server — validate the Host header against an allowlist. [HC]
- Input validation is a security boundary: Pydantic strict schemas on every tool-call endpoint are the R2 instruction-hierarchy enforcement. [VC]
- Error responses must not leak internals: custom exception handlers that return calm messages (U2 error-UX doctrine), log the full trace server-side only. [HC]

### Common failure modes
1. Request-scoped DB session reused inside a BackgroundTask → "session is closed" errors. Fix: background tasks create their own session. [VC]
2. BackgroundTasks used as a durable queue → work lost on crash/restart; request starvation under load. [VC]
3. CPU-bound work on the event loop → whole server freezes during inference/audio encode. [VC]
4. Lifespan cleanup skipped → leaked DB connections, port stays bound on restart ("address already in use"). [HC]
5. Missing timeouts on outbound httpx calls → one hung provider hangs the request forever. [VC]

### Confidence: [VC] on core patterns (official docs verified); [HC] on production failure modes (multiple production guides agree)
### Unknown
- Exact FastAPI/Starlette versions at v2 build time — pin then, don't bake into design now.
- Whether to run 1 vs 2 Uvicorn workers (single-user → 1 is fine; revisit if HUD + API + voice contend).

---

## O2. OAuth 2.0: authorization code + PKCE + refresh tokens

### Purpose
How JARVIS connects to Gmail, Google Calendar, etc. **on Owais's behalf** — without ever seeing his password, with scoped, revocable, refreshable access.

### How it works internally
**Authorization code flow (RFC 6749 §4.1)** — the only flow that matters; implicit flow and password flow are deprecated (OAuth 2.1 draft). [VC]
1. JARVIS opens the **system browser** (never an embedded WebView — RFC 8252) to the provider's `/authorize` with `response_type=code`, `client_id`, `redirect_uri`, `scope`, `state` (CSRF token), and PKCE `code_challenge`.
2. Owais signs in **on Google's own pages** and approves scopes. JARVIS never sees the password.
3. Provider redirects to the `redirect_uri` with a one-time `code` (+ echoed `state`, which JARVIS verifies).
4. JARVIS exchanges the code at the back-channel `/token` endpoint → receives `access_token` (~1 hour), `refresh_token` (long-lived), `expires_in`.

**PKCE (RFC 7636, "pixie")** — the public-client armor: JARVIS generates `code_verifier` (43–128 random chars), sends `code_challenge = BASE64URL(SHA256(verifier))` with the authorize request, then proves possession by sending the raw `code_verifier` at token exchange. An attacker who intercepts the code can't exchange it without the verifier. **Mandatory for desktop/mobile apps** — they can't keep a client secret. [VC]

**Native-app redirect (RFC 8252)**: desktop apps use a **loopback redirect** — JARVIS starts a temporary HTTP listener on `http://127.0.0.1:<random_port>/callback` and passes it as `redirect_uri`. Only a process on the same machine can receive the code. [VC]

**Refresh tokens**: when the access token expires, JARVIS POSTs `grant_type=refresh_token` + `refresh_token` to get a new access token — no user interaction. Google's rules (verified): request `access_type=offline` at authorize time or you get **no** refresh token; refresh tokens are rate-limited (don't refresh per-call — cache and refresh on 401/expiry); Google revokes after ~6 months of disuse or on password change → app must gracefully re-prompt. [HC]

**Device flow** (alternative): for input-constrained devices — user visits a URL and types a code. Not needed for JARVIS (it has a browser), but good to know it exists. [HC]

### JARVIS application
- Gmail/Calendar/Drive integration: JARVIS registers as a **Desktop app** OAuth client (Google Cloud Console → "Desktop app" type), runs PKCE + loopback redirect, stores the refresh token in the **OS keyring** (R9 — never env files, never chat).
- Minimal scopes only: `gmail.readonly` before `gmail.send`, etc. — least privilege, expandable later with re-consent.
- Token manager: in-memory cache of access token; refresh lazily on 401 or near-expiry; on `invalid_grant`, surface a calm "reconnect Google" button (U2 error UX), never a traceback.
- This is the sanctioned path for "connect Gmail/Calendar" — no screen-scraping passwords, no pasted tokens (the chat-token incidents must never repeat).

### Best libraries
| Need | Pick | Why |
|---|---|---|
| OAuth client | `httpx-oauth` or `authlib` | authlib is the most complete OAuth/OIDC implementation; httpx-oauth is lighter |
| Google APIs | `google-api-python-client` + `google-auth` | Official; handles the installed-app flow |
| Secret storage | `keyring` | OS keyring abstraction (Windows Credential Manager / macOS Keychain / Secret Service) |

### Official docs
- Google installed apps: https://developers.google.com/identity/protocols/oauth2/native-app
- RFC 6749 (OAuth 2.0): https://www.rfc-editor.org/rfc/rfc6749
- RFC 7636 (PKCE): https://www.rfc-editor.org/rfc/rfc7636
- RFC 8252 (OAuth for native apps): https://www.rfc-editor.org/rfc/rfc8252
- Authlib docs: https://docs.authlib.org/

### Limitations / trade-offs
- Google's verification: sensitive scopes (Gmail send) may require app verification for distribution; for personal use it's fine. [HC]
- Client secret embedded in a desktop app is **not a secret** — Google explicitly documents this for installed apps. The security rests on PKCE + loopback, not the secret. [VC — Google docs]
- Refresh tokens can be revoked server-side at any time → JARVIS must always handle re-auth as a normal path, not an exception. [VC]
- One OAuth client per provider per app: if JARVIS is open-sourced, Owais should create his own client ID (30-second job, fits his "my finger on the button" rule for credentials). [HC]

### Security implications (matters most)
- **Tokens in OS keyring, never plaintext, never env files, never logs** (R9). `keyring` on Windows → Credential Manager, owner-only ACL. [VC]
- Always verify `state` on the callback — CSRF otherwise. [VC]
- Loopback listener: bind 127.0.0.1, random free port, shut it down immediately after capturing the code; validate the full callback URL. [HC]
- Minimal scopes; treat every granted scope as an attack surface the agent can be tricked into using (ties to ScrambleID scope-per-tool, SEC3). [HC]
- Never log tokens, never include them in crash reports or diagnostics bundles (log redaction, R9). [VC]
- Refresh-token theft = full account access until revoked → keyring + prompt before any *sending* action (two-dial safety: reads auto, writes confirm). [VC]

### Common failure modes
1. Forgot `access_type=offline` → no refresh token → user must re-login every hour. [VC]
2. Refreshing on every API call → Google rate-limits → cascading failures. Cache the access token. [HC]
3. `redirect_uri_mismatch` → port changed between authorize and callback; use the any-port loopback pattern where the provider supports it, or hold the port for the flow's duration. [HC]
4. `invalid_grant` on refresh (revoked/expired) → must surface re-auth UI, not crash. [VC]
5. Storing tokens in `settings.local.yaml`/logs → credential leak into backups, GitHub Desktop commits, diagnostics. [VC]

### Confidence: [VC] on flow mechanics (RFCs + Google docs); [HC] on Google-specific behaviors (docs + community experience)
### Unknown
- Google's future policy on unverified desktop-app clients and sensitive-scope verification for personal-use apps — re-check at build time.
- Whether to ship a shared JARVIS OAuth client ID vs. per-user client creation (UX vs. security trade-off — decision for design phase).

---

## O3. Streaming to a UI: WebSockets vs Server-Sent Events

### Purpose
Getting live updates to the chat UI: LLM token streaming, tool-call progress, notifications, scheduler events.

### How they work internally
**Server-Sent Events (SSE)**: a long-lived HTTP response with `Content-Type: text/event-stream`. Unidirectional (server → client), UTF-8 text events with optional `event:` names and `id:`s. The browser's `EventSource` API **auto-reconnects** on drop and sends `Last-Event-ID` so the server can replay missed events. Plain HTTP → passes through proxies/firewalls, works over HTTP/2 multiplexing. [VC]

**WebSockets**: an HTTP Upgrade handshake switches to a full-duplex framed protocol (`ws://`). Both sides send anytime; supports binary. **No** built-in reconnect, heartbeat, or resume — the app implements ping/pong, exponential-backoff reconnect, and resubscription itself. [VC]

**Backpressure** — the sharp edge both share: the browser WebSocket API has no receive-side backpressure (`bufferedAmount` only tells you you're drowning); `EventSource` has no pull API either. If the server floods faster than the network drains, the browser drops the connection. Server-side you must bound queue depth and shed load early (drop/coalesce/429) rather than buffering unboundedly. [HC]

### Trade-off matrix
| | SSE | WebSockets |
|---|---|---|
| Direction | Server → client only | Full duplex |
| Reconnect | Built-in (`EventSource`) | Hand-rolled |
| Resume | `Last-Event-ID` replay | Hand-rolled |
| Payload | Text only | Text + binary |
| Proxies/firewalls | Just HTTP | Needs WS-aware proxying, sticky sessions |
| HTTP/1.1 limits | 6 connections/domain (use HTTP/2) | Per-browser socket limits |
| Complexity | Low | High (heartbeat, auth refresh, routing, shutdown) |
| LLM token streaming | ✅ ideal | Overkill |

**Decision rule**: if the client mostly *receives* and sends commands via normal HTTP, SSE wins on operational simplicity. WebSockets earn their complexity only for continuous two-way traffic (multiplayer, collaborative editing, full-duplex voice). For JARVIS v2 chatbot-first: **SSE for token/progress streaming + REST for commands**. [VC — broad consensus across sources]

### JARVIS application
- Chat UI token streaming: `GET /api/chat/stream` → SSE events (`token`, `tool_call`, `tool_result`, `done`), each with incrementing `id:` for resume.
- Scheduler/proactive pings: SSE channel for "JARVIS noticed X" notifications to the HUD.
- Voice plugin later: full-duplex audio may eventually want WebSockets — but per "voice last" (R1), don't build it now. Design the event *schema* once so the transport can change.
- Note: JARVIS's HUD is PyQt6 (native, not browser) — the streaming client there is `httpx` reading the SSE stream, not `EventSource`. Same protocol, different client.

### Best libraries
| Need | Pick | Why |
|---|---|---|
| SSE server (FastAPI) | `sse-starlette` | `EventSourceResponse` — production-ready, W3C-compliant, disconnect detection, graceful shutdown (PyPI-verified) |
| WS server (if ever) | Starlette `WebSocket` | Built into the stack; add `websockets` only if needed |

### Official docs / refs
- SSE spec (W3C/HTML): https://html.spec.whatwg.org/multipage/server-sent-events.html
- sse-starlette: https://pypi.org/project/sse-starlette/
- WebSocket RFC 6455: https://www.rfc-editor.org/rfc/rfc6455
- MDN EventSource: https://developer.mozilla.org/en-US/docs/Web/API/EventSource

### Limitations / trade-offs
- SSE is text-only; binary (audio frames) needs base64 or a separate channel. [VC]
- `EventSource` can't set custom headers → auth via cookie or short-lived signed URL, not `Authorization` header. (For the PyQt client using httpx, headers are fine.) [VC]
- `sse-starlette` + `GZipMiddleware` = broken streams (documented caveat); reverse-proxy buffering (nginx `proxy_buffering off`, `X-Accel-Buffering: no`) must be set. [HC]
- Reconnect storms after server restart: clients should reconnect with jitter, server should bound per-client replay buffers. [HC]

### Security implications
- Authenticate the stream endpoint like any API — an open SSE endpoint leaks conversation tokens in real time. [VC]
- Signed, short-lived stream URLs or session cookies; never long-lived tokens in query params (they land in logs). [HC]
- `Last-Event-ID` replay buffers are a memory DoS surface — cap buffer size and age. [HC]
- CORS: lock `Access-Control-Allow-Origin` to the exact UI origin; never `*` with credentials. [VC]

### Common failure modes
1. Proxy buffers the stream → UI gets everything at the end, not live. Fix headers/config. [VC]
2. GZipMiddleware enabled → SSE silently breaks. [VC — documented]
3. Generator never cancelled on disconnect → leaked tasks pile up; always handle `CancelledError`/disconnect. [HC]
4. Unbounded replay buffer → memory growth on flaky networks. [HC]
5. Using WebSockets "because real-time" for a one-way feed → months of reconnect/heartbeat bugs for zero benefit. [VC]

### Confidence: [VC] on protocol trade-offs; [HC] on sse-starlette specifics (PyPI-verified)
### Unknown
- Exact auth pattern for JARVIS's streams (session cookie vs. signed URL) — design-phase decision.
- Whether the future voice plugin needs WS or can ride chunked HTTP — revisit at voice phase.

---

## O4. Persistent job queues without Docker

### Purpose
Scheduled and proactive work that **survives restarts**: reminders, morning briefings, periodic memory consolidation, retryable background tasks. v1's `scheduler.py` was in-process and fragile (one malformed time string = app won't start, C-infra). v2 needs durability without infrastructure.

### How it works internally
Two distinct needs, two tools:
1. **Scheduled jobs (cron-like)**: run X at time T, on a schedule. → **APScheduler** with `SQLAlchemyJobStore(url='sqlite:///jobs.sqlite')`. Job definitions persist in SQLite; on startup the scheduler reloads them. Missed-fire handling (`misfire_grace_time`, `coalesce`) decides what happens when the PC was asleep. [VC — https://apscheduler.readthedocs.io/en/3.x/userguide.html]
2. **Ad-hoc durable tasks**: "do this once, retry if it fails." → **Huey** with `SqliteHuey` (also `FileHuey`, `PostgresHuey`, `RedisHuey`). Zero-dependency, decorator API (`@huey.task(retries=2, retry_delay=60)`), periodic tasks via `crontab()`, result storage, task locking/rate-limits/timeouts. [HC — https://pypi.org/project/huey/]
3. **The SQLite queue pattern** (if hand-rolling): `jobs` table + atomic claim via `UPDATE ... WHERE id = (SELECT ... FOR UPDATE SKIP LOCKED)` or `RETURNING` with `isolation_level="IMMEDIATE"`. Single-writer semantics of SQLite are fine at JARVIS scale (single user, tens of jobs). [HC]

### JARVIS application
- APScheduler (persistent): Owais's routines — "brief me at 8am," weekly digest, Nocturne-style idle consolidation passes, memory promotion sweeps. Malformed schedule entries must be quarantined, never crash startup (R7 — the direct lesson from v1).
- Huey SqliteHuey (durable tasks): "retry that failed upload," "process this file when idle," webhook follow-ups.
- Both live in the FastAPI lifespan: scheduler starts after config validation, shuts down gracefully (drain or requeue in-flight jobs).
- Zero new infrastructure: no Redis, no RabbitMQ, no Docker — matches the zero-terminal, single-PC doctrine. Celery/RQ/Dramatiq are explicitly rejected for v2 (right tools, wrong deployment).

### Best libraries
| Need | Pick | Why |
|---|---|---|
| Persistent scheduling | `APScheduler` 3.x | `SQLAlchemyJobStore` + SQLite; cron/interval/date triggers; officially documented |
| Durable ad-hoc tasks | `huey` (`SqliteHuey`) | Zero-dep, retries, crontab, result store, locks — all on SQLite |
| (Rejected) | Celery / RQ / Dramatiq | Need Redis/RabbitMQ — infra JARVIS won't run |

### Official docs
- APScheduler user guide: https://apscheduler.readthedocs.io/en/3.x/userguide.html
- Huey guide: https://huey.readthedocs.io/ (PyPI: https://pypi.org/project/huey/)

### Limitations / trade-offs
- APScheduler 3.x serializes jobs with **pickle** into the jobstore — job functions must be importable by reference; code refactors can orphan stored jobs (version your job IDs, or clear-and-reseed on upgrade). [HC]
- SQLite single-writer: fine for one user; parallel workers contend. Keep one consumer process. [VC]
- At-least-once delivery: a crash mid-job can double-execute → **jobs must be idempotent** (see O6). [VC]
- PC sleep: missed jobs need an explicit policy (run-late vs. skip vs. coalesce) — `misfire_grace_time` + `coalesce=True` for digests, `coalesce=False` for reminders. [HC]
- APScheduler 4.x exists in development; 3.x is the stable documented line — pin 3.x until 4.x stabilizes. [MC]

### Security implications
- Job payloads live in a SQLite file — may contain secrets/arguments. File must be owner-only permissions; consider encrypting sensitive args or storing references, not values. [HC]
- Deserialization: APScheduler's pickle jobstore is a **remote-code-execution vector if the DB file is writable by an attacker** — the jobs DB must never be world-writable, and job definitions should be allowlisted on load (R11 manifest discipline applies to scheduled jobs too). [HC]
- A scheduled job is an unattended agent action → every job runs through the Four Checks gate (`may_act_unasked()`), and destructive jobs require prior user consent. [VC — design rule]

### Common failure modes
1. Malformed cron/time string crashes the scheduler at startup (v1's actual bug) → validate-then-quarantine, R7. [VC]
2. Non-idempotent job runs twice after crash → duplicate notifications/charges. [VC]
3. Timezone bugs: schedule in the user's tz, store in UTC; DST transitions skip or double-fire jobs. [HC]
4. Pickled jobs orphaned after refactor → scheduler loads stale references and errors. [HC]
5. Long-running job blocks the scheduler thread → use executors (ThreadPoolExecutor/ProcessPoolExecutor), not the default. [VC — APScheduler docs]

### Confidence: [VC] on APScheduler persistence (official docs); [HC] on Huey SQLite suitability (PyPI-verified, less production lore than Celery)
### Unknown
- APScheduler 4.x timeline/stability — re-evaluate at build time.
- Huey `SqliteHuey` behavior under concurrent multi-process access — likely fine single-consumer; unverified under contention.

---

## O5. Webhooks: receiving securely + local tunneling

### Purpose
Letting external services **push** events to JARVIS (a calendar update, a payment notification) instead of polling.

### How it works internally
**Receiving securely** — the non-negotiable checklist (Standard Webhooks spec + Svix/GitHub/Stripe practice): [VC]
1. **HMAC-SHA256 signature verification**: sender signs the **raw request bytes** (before JSON parsing — re-serializing changes whitespace/key order and breaks the HMAC) with a per-endpoint shared secret; receiver recomputes and compares with **constant-time** comparison (`hmac.compare_digest`, never `==`). Wrong/missing signature → 401/403 immediately, before touching the payload.
2. **Timestamp tolerance**: if the scheme signs a timestamp, reject anything older than ~5 minutes → kills replay attacks.
3. **HTTPS only**; secret in keyring/env, rotated on exposure; never logged.
4. **Ack fast, process async**: return 2xx immediately, enqueue the work (O4) — slow handlers cause provider retries → duplicate deliveries.
5. **Deduplicate by event/delivery ID**: providers retry (Stripe: up to 3 days exponential; Shopify: 8×/4h; GitHub: manual) → at-least-once delivery is the contract; idempotency (O6) makes it safe.
6. **SSRF defense on registration**: validate endpoint URLs, refuse private/link-local ranges.

**Local tunneling for dev**: providers can't reach `localhost`, so during development you expose it: `cloudflared tunnel`, `ngrok`, provider CLIs (`stripe listen --forward-to localhost:4242/webhook`), `webhook.site` (inspect raw payloads without code), `smee.io`. [VC]

### JARVIS application
- **Prefer polling where the provider supports it**: Telegram bots offer `getUpdates` long-polling — JARVIS's `telegram_channel.py` already polls, which means **no inbound port, no tunnel, no webhook attack surface at all**. Keep it. [VC — design decision]
- Webhooks only if a provider *requires* push (rare for personal use). If ever needed: FastAPI endpoint → verify HMAC → enqueue to Huey → 200 immediately.
- Tunneling is a **dev-only** tool for testing handlers, never a production architecture for a personal PC (tunnel URLs change, tunnels die, and they punch outbound holes).

### Best libraries
| Need | Pick | Why |
|---|---|---|
| Signature verify | stdlib `hmac` + `hashlib` | `hmac.compare_digest` — no dependency needed |
| Tunneling (dev) | `cloudflared` | Free, no account for quick tunnels; `ngrok` as alternative |
| Inspection (dev) | `webhook.site` | See exactly what a provider sends before writing code |

### Official docs / refs
- Standard Webhooks spec: https://www.standardwebhooks.com/
- Svix security practices: https://www.svix.com/resources/webhook-best-practices/security/
- GitHub webhook signatures: https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
- Stripe webhooks: https://docs.stripe.com/webhooks

### Limitations / trade-offs
- Webhooks invert the security posture: you're now running a public-facing listener. For a personal assistant, every webhook is attack surface that polling avoids. [VC]
- Signature schemes differ per provider (hex vs base64, different signed content) — one verifier per provider, tested with fixtures including wrong-signature and duplicate-delivery cases. [VC]
- Tunnel URLs are ephemeral → webhook registrations break; production webhooks need a stable public URL JARVIS doesn't have. Another reason to poll. [VC]

### Security implications (matters most)
- **Unverified webhook = unauthenticated RCE-adjacent input**: a forged "calendar event" carrying prompt-injection text would flow straight into the brain (C-S1 class). Signature verification is the R2 boundary for inbound pushes. [VC]
- Inbound payloads are **untrusted content** — REA markers apply (SEC4): mark, don't concatenate raw into LLM context. [VC]
- Keep webhook secrets per-endpoint, in the keyring, rotated; alert on invalid-signature spikes (probing). [HC]
- If a tunnel is ever used, it's outbound-initiated and temporary; never leave `cloudflared` running unattended with a fixed URL. [HC]

### Common failure modes
1. Verifying the **re-serialized** JSON instead of raw bytes → every genuine delivery fails signature check. The #1 webhook bug. [VC]
2. Wrong secret (test vs live) or wrong encoding (hex vs base64). [VC]
3. Slow handler → provider timeout → retry storm → duplicate side effects without dedup. [VC]
4. Clock skew → timestamp rejections on valid deliveries. [HC]
5. Tunnel dies overnight → silently stops receiving; no alerting because "it worked yesterday." [HC]

### Confidence: [VC] on the verification checklist (spec + 4+ sources agree); [VC] on prefer-polling for JARVIS (architectural judgment)
### Unknown
- Which (if any) future JARVIS integrations will *require* push webhooks — none identified for v2 scope.

---

## O6. Reliability patterns: rate limiting, retries, timeouts, idempotency

### Purpose
The network is unreliable and providers are flaky. These four patterns turn "it failed" into "it worked, eventually, exactly once."

### How each works internally

**1. Retries with exponential backoff + jitter**
- Retry **only transient, idempotent failures**: HTTP 408/429/5xx, timeouts, connection resets. Never retry 400 (fix the request) or 401/403 (fix the credentials). [VC]
- Backoff: wait 2^attempt seconds (capped), plus **jitter** (random spread) so N clients don't retry in lockstep and DDoS the recovering provider (thundering herd). [VC]
- Stop conditions are mandatory: `stop_after_attempt` AND/OR `stop_after_delay` — unbounded retry is a slow-motion outage. [VC]
- **Library: `tenacity`** — the de-facto Python retry library (fork of `retrying`): `@retry(stop=stop_after_attempt(5), wait=wait_exponential_jitter(initial=1, max=60), retry=retry_if_exception_type(...), reraise=True)`. Works sync and async identically. Honor the provider's `Retry-After` header when present (429). [VC]
- urllib3's `Retry` also grew `backoff_jitter` in 2.0 for the requests-level path. [HC]

**2. Timeouts (always, everywhere)**
- Every outbound call gets explicit timeouts: httpx supports `(connect, read, write, pool)` separately. LLM calls need generous *read* timeouts (slow first token) but tight *connect* timeouts. No timeout = one hung provider can wedge a worker/thread forever. [VC]
- Interaction with retries: the per-try timeout bounds each attempt; the backoff clock starts when the failure is known. [HC]

**3. Rate limiting (protecting yourself and others)**
- Algorithms: **token bucket** (capacity + refill rate; allows bursts — the general default), sliding-window counter (smooth "N per minute"), fixed window (boundary spikes), leaky bucket (fixed-rate downstream protection). If unsure: token bucket. [HC]
- Always return `X-RateLimit-Limit/Remaining/Reset` + `Retry-After` on 429 — clients that can see the wall slow down before hitting it. [VC]
- Key by API key / user, not bare IP (NAT punishes innocents); exempt `/health`; decide **fail-open vs fail-closed** when the limiter store is down — deliberately, in advance. [HC]
- **Library: `slowapi`** for FastAPI (decorator-based limits). For a single-user local server, a tiny in-memory token bucket is sufficient — no Redis. [MC]

**4. Idempotency keys (exactly-once effect)**
- The Stripe pattern: client generates a UUIDv4 `Idempotency-Key` per *logical operation* (not per attempt); server stores key→response for 24h+; a retry with the same key returns the stored response instead of re-executing. Same key + *different* payload → 409 (client bug, surface it). [VC — https://docs.stripe.com/api/idempotent_requests]
- DB-level: unique constraint on the key + `INSERT ... ON CONFLICT DO NOTHING` makes claim-and-record atomic — no race between two workers. [VC]
- Design rule: GET/PUT/DELETE are idempotent by convention; **every POST that has side effects gets an idempotency key**, and every background job asks "what if this runs twice?" [VC]
- Reality check: true exactly-once doesn't exist over networks; the pattern is **at-least-once delivery + idempotent processing = once in effect**. [VC]

### JARVIS application
- **All provider calls** (Gemini/Groq/OpenRouter/local llama-server) go through tenacity with the retryable-status taxonomy — this is the transport layer under the B1 fallback-chain recipe (retry transient → then fail over to next provider; never retry 400s). [VC]
- **Timeouts on everything**: brain calls, tool subprocesses (already in hardened_runner), webhook handlers, SSE generators. [VC]
- **Idempotency on mutating tools**: "send email," "create calendar event," "pay" (never auto — but the pattern still applies) — generate the key at *intent* time, so a crash-and-retry can't double-send. This is also how the scheduler's at-least-once jobs become safe. [VC]
- **Rate-limit the localhost API** even though it's loopback: defense in depth (a compromised renderer/HUD shouldn't be able to hammer the brain endpoint), plus it protects the *outbound* side — JARVIS must rate-limit itself against provider quotas (per-provider token buckets in the brain router). [HC]

### Best libraries
| Need | Pick | Why |
|---|---|---|
| Retries | `tenacity` | De-facto standard; sync+async; composable wait/stop/retry predicates |
| HTTP (with timeouts) | `httpx` | Per-stage timeouts; async-native |
| Rate limiting (FastAPI) | `slowapi` | Standard FastAPI limiter; or hand-rolled token bucket for local-only |
| Idempotency store | SQLite table | `idempotency_key TEXT PRIMARY KEY, response JSON, expires_at` — no new infra |

### Official docs / refs
- Tenacity: https://tenacity.readthedocs.io/
- Stripe idempotent requests: https://docs.stripe.com/api/idempotent_requests
- httpx timeouts: https://www.httpx.org/advanced/timeouts/
- IETF draft on idempotency keys: https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/

### Limitations / trade-offs
- Retries **amplify** load on a struggling provider — jitter + `Retry-After` + circuit breaker (I4 has a proven one) are the counterweight. Retry budget: N attempts total, not N per layer (retries at HTTP layer × retries at brain layer = multiplicative storm). [VC]
- Idempotency storage is a small DB that needs TTL eviction; keys must never contain PII (they get logged). [HC]
- Timeouts that are too tight cause false failures (slow LLM first token); too loose cause cascading slowness. Per-endpoint tuning, measured not guessed. [HC]

### Security implications
- Retry logic must never retry with **escalated** credentials or across providers in a way that leaks the request to a less-trusted provider (fallback chain must respect data-classification per provider). [HC]
- Idempotency-key store replays *responses* — ensure stored responses don't contain secrets that outlive their context; TTL aggressively. [HC]
- Rate limiting is a DoS control: without it, one runaway agent loop (retrying a failing tool) can exhaust provider quota or disk (log spam). [VC]
- `Retry-After` from an untrusted server is advisory only — cap it; a malicious value of 10^9 shouldn't park your worker. [MC]

### Common failure modes
1. Retrying 400/401s → burns quota, fixes nothing, masks the real bug. Classify before retrying. [VC]
2. No jitter → synchronized retry storm after a provider blip. [VC]
3. Retrying non-idempotent POSTs → duplicate charges/emails/messages. The idempotency key must exist *before* the first attempt. [VC]
4. Missing timeouts → thread-pool exhaustion → whole server wedges. [VC]
5. Two layers retrying independently (HTTP client × brain router) → 5×5=25 attempts against a down provider. One retry budget, enforced at one layer. [HC]

### Confidence: [VC] on retry taxonomy, tenacity, idempotency pattern (official docs + broad consensus); [HC] on rate-limit algorithm guidance; [MC] on slowapi (single source + training knowledge)
### Unknown
- Optimal timeout values for each provider — must be measured against real latency distributions at build time.
- Whether outbound rate limiting belongs in the brain router, a middleware, or both — design-phase call.

---

## Knowledge connections (the curriculum's §3, applied)

- **O1 → R2**: Pydantic strict schemas are where the instruction hierarchy becomes code — tool inputs validated before LLM judgment is trusted.
- **O1 → SEC2**: localhost FastAPI server inherits every localhost-hijack requirement (bind 127.0.0.1, auth on loopback, Host validation).
- **O2 → R9**: OAuth refresh tokens are the highest-value secrets JARVIS holds → OS keyring, log redaction, minimal scopes.
- **O2 → SEC3**: OAuth scopes are coarse; ScrambleID-style per-tool tokens are the finer-grained complement for agent tool use.
- **O3 → U1**: SSE is the transport for the chat UI's token streaming; event schema designed once, transport swappable.
- **O4 → I1/I3**: APScheduler is the durable substrate for the scheduler spec; every job passes the Four Checks gate.
- **O4 → O6**: at-least-once jobs + idempotent handlers = exactly-once effect (the reliability composition).
- **O5 → SEC4**: inbound webhooks are untrusted content — HMAC verification then REA markers before anything reaches the brain.
- **O6 → B1**: tenacity's retryable taxonomy (408/429/5xx only) is the transport layer the fallback-chain recipe sits on; retries-then-failover, never retries-instead-of-failover.
- **O6 → R11**: idempotency keys on skill/tool mutations make retries safe — reliability and the skill system meet here.

---

## Open questions for the design phase (not learning gaps — decisions)

1. Ship a shared JARVIS OAuth client ID vs. per-user client creation (UX vs. credential-hygiene trade-off).
2. SSE stream auth pattern (session cookie vs. short-lived signed URL).
3. Single Uvicorn worker vs. two (measure under HUD + API + voice load).
4. Outbound rate-limit placement: brain router, middleware, or both.
5. APScheduler 3.x vs 4.x at build time; exact version pins for the whole stack.

*End of Domain O notes.*
