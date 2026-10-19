# The Durable Session Store — Design Specification (proposed R15)

*PHASE INFINITY, Research Cycle 14. Design document, not code.*
*Date: 2026-10-19. LEARNING ONLY — no project files touched, no installs, no code executed.*

**Sources:** `diamond-1-managed-agents.md` (Anthropic: session/harness/sandbox decoupling, `wake(sessionId)`, append-only session log), `learn-reliability-spec.md` (SLOs S5/S6, RTO/RPO, checkpoint cadence, degradation ladder), `learn-databases.md` (SQLite WAL, schema versioning, backup API, single-writer discipline), `learn-observability.md` (§1 trace_id via contextvars, §2 structured logging + redaction, §6 crash detection layers + resume semantics).

**Thesis (diamond-1, 95% [VC]):** the session store is the only stateful component. Brain and hands are stateless and disposable. Everything else in this spec falls out of that topology.

---

## 1. Purpose — what the session store is FOR

Four jobs, in priority order:

1. **Crash recovery.** `wake(sessionId)` resumes mid-turn after any crash, restart, or deploy. Target: RTO ≤60s to responsive chat, RPO ≤5 min / ≤50 events (reliability spec S5, [PROPOSED]). The store is what makes "restart-required failure classes designed out" (diamond-1) a real claim instead of a slogan.
2. **Interrogability.** The store answers questions about what happened: "what did you do at 3pm Tuesday?", "show me every tier-3 action this week and their approvals", "why did you fail that turn?" Anthropic's distinction (diamond-1 §2): the session log is a *context object that lives outside the context window* — durable recoverable storage, not context-engineering policy. The harness interrogates it via positional slices and rewinds; the store itself stays opinionated about the log format and unopinionated about what the brain does with it.
3. **Audit.** Every mutating action is traceable to the event that authorized it: tool call → approval event → user. This is the evidentiary backbone of S6 (approval-gate integrity, 0 violations ever) and S7 (secret containment). The fault tree's B9 (event log tampered) is addressed in §8.
4. **Multi-surface continuity.** PC → phone → PC handoff. A turn started on the desktop continues on Telegram because the session — not the process — holds the state. The brain is cattle; the session is the thread of continuity.

**What the store is NOT:** it is not the context window (the harness assembles that from slices), not semantic memory (mem0-style facts live elsewhere), not the vector store (that's retrieval, not record). Confusing these is the coupled-design mistake in miniature.

---

## 2. The event model — append-only log schema

### 2.1 The invariant (diamond-1, [VC])

The primary record is an **append-only log**. Events are never mutated, never deleted in place (deletion is a tombstone event, §7). Resume re-enters at the *event* level, not the *turn* level: `emitEvent` per event is the unit of durability. Anything the harness does that changes state without emitting an event is unrecoverable *by design* — this is a hard rule on harness implementers, not a suggestion.

### 2.2 Event envelope (every event, no exceptions)

| Field | Type | Purpose | Source |
|---|---|---|---|
| `event_id` | TEXT (ULID, sortable + unique) | Total ordering; idempotency key for mutating tools (§4) | databases T1 sessions sketch; observability §1 |
| `session_id` | TEXT (ULID) | Which session this belongs to | diamond-1 `getSession(id)` |
| `trace_id` | TEXT (W3C 128-bit, `contextvars`-propagated) | Joins events across logs, spans, metrics for one turn | observability §1 |
| `seq` | INTEGER (monotonic per session) | Ordering within session; checkpoint cursor (§4) | diamond-1 positional slices |
| `ts` | TEXT (ISO-8601 UTC, ms) | Wall-clock time for interrogation | — |
| `type` | TEXT (from the taxonomy below) | What happened | diamond-1 event taxonomy |
| `causal_parent` | TEXT (event_id, nullable) | The event this one is *in response to* — the causal spine | causal-discovery cycle 5: precedence is free, use it |
| `actor` | TEXT (`user` \| `brain` \| `tool` \| `system` \| `supervisor`) | Who/what produced it (provenance for R2 instruction hierarchy) | R2 |
| `payload` | JSON | Type-specific content | — |
| `trust` | TEXT (`user` \| `system` \| `tool_untrusted` \| `tool_verified`) | Trust tier of any embedded content — R2's instruction hierarchy made structural | R2 |

**Design decisions and their traces:**
- **ULID for `event_id`** (not UUIDv4): lexicographically sortable by time, so "replay tail after seq N" is an index range scan, no timestamp comparison. [HC — standard practice]
- **`seq` per session, not global:** checkpoints store `(session_id, seq)`; replay starts "strictly after seq" (observability §6's torn-checkpoint rule). Global sequence numbers couple sessions that have nothing to do with each other.
- **`causal_parent`:** the fault-tree B3 (TOCTOU) mitigation — the approval token embeds the action hash — is expressed as an event link: `approval_granted` → `causal_parent: <the exact tool_call event_id it authorizes>`. A swapped action has a different event_id; the gate check compares them. This turns the approval gate into a property of the log, auditable forever.
- **`trust` on every event:** tool results enter as `tool_untrusted` by default; the brain may promote to `tool_verified` only via a verification step (contract check, schema validation). Memory writes from `tool_untrusted` content carry provenance and are never auto-acted on (R2). [DERIVED from R2 + C-S6 memory poisoning]

### 2.3 Event taxonomy

| Type | Emitted by | Payload | Notes |
|---|---|---|---|
| `session.created` | supervisor | `surface` (desktop/phone), `profile_id`, initial config hash | Session birth; nothing exists before this |
| `session.checkpoint` | supervisor | `covers_seq`, `checkpoint_ref`, `sha256` | Cursor + pointer to derived snapshot (§5) |
| `session.compacted` | supervisor | `covers_seq`, `summary_ref`, `archived_to` | Compaction marker (§5) |
| `session.status` | supervisor | `from`, `to` (active/suspended/resumed/archived) | Lifecycle transitions (§3) |
| `user.message` | UI/phone | `text` or `audio_ref`, `surface`, `language` | The turn's root event; everything hangs off it |
| `brain.decision` | harness | `decision` (act/ask/refuse/escalate), `reasoning_ref`, `confidence`, model + tokens | The underspecification Cycle-1 decision rule's output, recorded |
| `tool.call` | harness | `tool`, `args` (schema-validated), `idempotency_key` (= event_id), `tier` | Gate-checked BEFORE emission for tier-3 (R3: gate is the first statement) |
| `tool.result` | sandbox/hands | `output` (bounded), `ok`, `ms`, `trust` | Untrusted content marker (R2); output bounded to prevent log bombs |
| `approval.requested` | harness | `action_ref` (tool.call event_id), `action_hash`, `blast_radius` | Out-of-band gate (R3) |
| `approval.granted` / `approval.denied` | UI | `request_ref`, `user_id`, `method` (button/voice-confirmed) | `granted.causal_parent` = the exact tool.call it authorizes |
| `tts.started` / `tts.word` / `tts.completed` / `tts.interrupted` | voice plugin | `sentence_ref`, `word_index` (for word-level), `interrupted_at_word` | **The Utterance Record** (Moshi diamond): `tts.completed` is the proof of what left the speakers |
| `wake.detected` | voice plugin | `score`, `model` | Observability §3's false-wake counter reads these |
| `degradation.entered` / `degradation.recovered` | supervisor | `rung` (R1–R4), `trigger`, `announcement` | The ladder as events, not vibes (reliability §4) |
| `brain.fallback` | supervisor | `from`, `to`, `reason` (transport-only per B1 recipe) | Closes the C-B1 loop with evidence |
| `memory.write` | harness | `key`, `fact`, `source`, `trust`, `confidence` | Provenance mandatory; `tool_untrusted` sources quarantined |
| `error` | any | `component`, `class`, `trace_id`, redacted message | Redacted per observability §2 — never raw |
| `crash.marker` | supervisor (on boot) | `last_seq`, `checkpoint_seq`, `gap` | Written at recovery start: the honest record of what was lost |
| `tombstone` | supervisor | `target_event_ids`, `reason` (user deletion) | Deletion without rewriting history (§7) |

**What is NEVER stored in the log** (reliability S7, privacy study):
- Audio bytes or bystander transcripts (store `audio_ref` → RAM-only, or nothing).
- Screenshot bytes (store `capture_ref` → RAM-only; the screen-watcher study: captures stay in RAM, never disk).
- Raw secrets/API keys (store `credential_handle`, never bytes — diamond-1 Pattern 2: the harness never sees credentials).
- Full file contents read by tools (store `file_ref` + hash + excerpt bounds).
- LLM full prompts in DEBUG (INFO-level events only in the session log; verbose traces go to the separate structured log with rotation).

**Why the exclusion list is load-bearing:** the session store is the *most durable* component — it outlives crashes, survives in backups, and is interrogated by the brain. Anything in it is effectively permanent and recallable. S7's "0 findings" target is only achievable if secrets never enter the log in the first place; redaction is the second line, not the first. [DERIVED]

---

## 3. The session lifecycle — state machine

```
                    ┌──────────────────────────────────────────────────┐
                    │                                                  ▼
  (boot) ──► CREATED ──► ACTIVE ◄──► SUSPENDED ──► RESUMED ──► ACTIVE
                    │         │          │              │
                    │         │          │              ▼
                    │         │          │         COMPACTED ──► ARCHIVED
                    │         │          ▼
                    │         │     (crash detected
                    │         │      at boot: latest
                    │         │      checkpoint + replay)
                    ▼         ▼
              (tombstoned/deleted per §7)
```

| State | Meaning | Entry trigger | Exit trigger |
|---|---|---|---|
| `CREATED` | Session record exists; no user turn yet | `session.created` emitted | First `user.message` → ACTIVE |
| `ACTIVE` | Live turn loop; harness attached | user message, resume complete | Idle timeout (configurable, default 30 min) → SUSPENDED; crash → (implicit) |
| `SUSPENDED` | Checkpoint written; harness detached; no process holds it | Idle timeout, user switches surface, clean shutdown | `wake(sessionId)` → RESUMED |
| `RESUMED` | Boot-time recovery path: checkpoint loaded, tail replayed, `crash.marker` written | `wake(sessionId)` after crash or suspend | Replay verified → ACTIVE |
| `COMPACTED` | Raw events archived; session continues from summary (§5) | Compaction policy fires (§5) | New user message → ACTIVE (on the compacted base) |
| `ARCHIVED` | Read-only; retained per policy; queryable | Age threshold or explicit user action | Deletion request → tombstoned (§7) |

**Design decisions:**
- **SUSPEND is explicit, crash is implicit.** A crash is detected only at next boot (the supervisor compares "was ACTIVE at last write, no clean SUSPEND" — this is observability §6's recovery-on-boot). The state machine never has a "crashed" state; crash is the *absence* of an expected transition. This avoids the classic bug of writing crash state with a dying process.
- **RESUMED is a distinct state, not a flag.** The recovery path (checkpoint + replay + `crash.marker` + honesty announcement) is different code from normal resume-from-suspend. Merging them is how "resume silently drops the tail" bugs happen. [HC — derived from observability §6's "recovery code is itself fault-handled"]
- **The supervisor owns transitions, never the brain.** The harness (brain loop) emits domain events; the supervisor process (or supervisor thread with its own exception domain — diamond-1's "supervisor lives outside the thing that fails") owns `session.status` transitions, checkpoints, and `wake()`. This is the C-B1 lesson applied to recovery: the thing that recovers must not share fate with the thing that failed. [DERIVED, diamond-1 §4 + R8 mapping]

---

## 4. Crash recovery protocol — `wake(sessionId)`, step by step

### 4.1 Preconditions

- The session store process/storage is itself healthy (its own failure modes are §8).
- `session_id` exists; latest `session.checkpoint` (if any) is readable and its sha256 verifies.

### 4.2 The protocol

1. **Lock.** Acquire the session lock (single-writer discipline, databases T1). If another harness holds it, `wake` fails closed with "session already active" — never two writers. [DERIVED from T1's one-writer rule]
2. **Load checkpoint.** Read `checkpoint_ref` → derived state (conversation summary, pending task graph, scheduler queue, belief-ledger state). Verify sha256. On mismatch → quarantine (`checkpoint.json.corrupt-<ts>`), proceed with **event-log replay alone** (observability §6), tell the user. Never boot-loop.
3. **Replay tail.** Read all events with `seq > checkpoint.covers_seq`, in order. Handlers **reduce, never re-emit** (observability §6's `bus.replaying` discipline): replaying must not append duplicate events to the log.
4. **Reconcile in-flight work.** For every `tool.call` with no matching `tool.result`:
   - **Idempotent tools** (reads, pure queries): re-execute or mark complete — safe either way. The idempotency key IS the `tool.call` event_id; the tool checks "did this event_id already execute?" before acting (observability §6).
   - **Mutating tools:** check the outbox pattern (observability §6): intent was written before execution (`tool.call` IS the intent). Query reality: did the effect land? If yes → emit `tool.result` with `recovered: true` (reduction, not a new call — do NOT re-execute blindly). If no → re-execute once with the same idempotency key. If unknown → **ask the user**, never guess. The classic at-least-once problem; diamond-1 is honest that it doesn't solve the semantic half — this protocol contains it. [DERIVED, diamond-1 §4 honest limits]
   - **Tier-3 approvals:** an `approval.requested` with no `approval.granted`/`denied` is **expired, not pending**. The user never approved; the action never runs. Re-present the request if the task still matters. This is the fault-tree B8 (replay) mitigation as protocol: a recorded approval is bound to its `action_ref` and its session generation; replay never re-arms it. [DERIVED from fault-trees B8 + Cycle-1 ESCALATE class]
5. **Utterance reconciliation (the Moshi rule).** Truncate the brain's claimed conversation history to what `tts.completed` / `tts.interrupted` events prove was actually spoken. If the crash happened mid-sentence, the resumed brain's history ends at the last completed word — never at the generated sentence. The brain must never "remember" saying words the user never heard (AGENTS.md voice-loop doctrine). On resume, if the interrupted content mattered, the brain re-says it fresh — a new `tts.started` event, a new claim. [DERIVED, diamond-2/Moshi]
6. **Write `crash.marker`.** `last_seq` (last event before the gap), `checkpoint_seq`, `gap` (events lost, if any — with checkpoint+RPO discipline this should be ≤50 events / 5 min). This is the honest record; the reliability spec's S5 measurement reads it.
7. **Announce.** Butler voice, once, plain language: "Sir, I had to restart — I've picked up where we left off. I may have lost the last [N] seconds." (reliability §4 announcement discipline). If nothing was lost: "Sir, I restarted cleanly — nothing was lost." Silence is a lie; confabulation ("as I was saying…") about unspoken words is worse. [DERIVED]
8. **Resume the loop.** Reconstruct context from checkpoint + replayed tail (the harness's job — diamond-1's "session vs. context window" separation), re-enter at the next step after the last reconciled event.

### 4.3 What the protocol does NOT promise

- **In-flight TTS audio and half-heard utterances are unrecoverable** (reliability RTO table: voice RPO = "in-flight utterance only"). The protocol is honest about this instead of papering over it.
- **Semantic idempotency for external actions** (sent a Telegram message, crashed before logging): the outbox pattern bounds it, but a message sent twice is possible if the send succeeded and the mark didn't land. Mitigation: outbox entries include a client-generated deduplication ID where the downstream API supports it (Telegram doesn't — document as residual risk). [OPEN — §8]
- **Cross-session causality:** if crash A in session 1 caused the user to act in session 2, no protocol recovers the *meaning*. The log records the facts; interpretation is the brain's job on resume.

---

## 5. Compaction policy

**The problem** (diamond-1 §2): long-horizon sessions exceed the context window. Compaction (summarization) makes irreversible decisions about what to keep. The session store solves it by keeping the *raw log* while the *harness* works from compacted views — but the raw log can't grow forever on a laptop SSD.

### 5.1 When compaction fires

- **Event-count trigger:** `seq` exceeds 5,000 events since last compaction. [PROPOSED — needs measurement of replay time vs. count]
- **Age trigger:** session idle >7 days moves toward ARCHIVED rather than COMPACTED (different policy — see below).
- **Manual trigger:** user says "summarize and start fresh" → explicit `session.compacted` with user-initiated flag.

### 5.2 What the summary preserves (and what it must not)

**Preserves** (lossless for the purposes below):
- **Decisions** (`brain.decision` events): the decision, the options considered, the confidence. The *reasoning* may compress; the *verdict* may not.
- **Commitments and open loops:** promises made ("I'll remind you at 5"), tasks in flight, approvals granted with their `action_ref`s, scheduled items. These are the things the user will hold JARVIS to.
- **Facts learned about the user** that graduated to memory (pointers to `memory.write` event_ids, not copies).
- **The causal spine:** which tool calls served which user requests (`causal_parent` chains survive as the skeleton).

**Must NOT contain:**
- Vibes, personality notes, or editorializing ("the user seemed frustrated" — if frustration matters, the *events* show it; the summary doesn't interpret).
- Full tool outputs (pointers to archived raw log).
- Anything the raw log doesn't also contain (the summary is derived, never primary).

### 5.3 The losslessness argument (why this is safe)

Compaction is lossless **for recovery purposes** because of the two-tier design:

1. The compacted summary + all events after `covers_seq` are sufficient to **resume the session** (the recovery protocol only needs the tail + derived state).
2. The raw events before `covers_seq` are **archived, not deleted** (`session.compacted.archived_to` → compressed JSONL in the archive dir, content-hashed). Interrogation of old history reads the archive.
3. Therefore "lossy" applies only to *what the harness keeps in its working view* — the durable record is intact. This is exactly diamond-1's separation: durable storage (session) vs. arbitrary context management (harness). [DERIVED]

**The honest caveat:** archive retrieval is slower (decompress + scan). Queries spanning the compaction boundary pay that cost. The interrogation interface (§6) hides it, but the latency is real — document it, don't pretend archives are free. [HC]

### 5.4 Archive retention

- Archives live in `%APPDATA%\JARVIS\sessions\archive\` (data dir, never repo — databases T1).
- Default retention: 1 year, then eligible for user-confirmed purge (privacy study: retention needs the user's call; 1 year is [PROPOSED], not decided).
- Deletion follows the §7 checklist: archive files are in the "event log" row (tombstone + purge, including rotations).

---

## 6. Interrogation interface

The store exposes a read API. The harness uses it for context assembly; the UI uses it for the "what did you do" views; the audit path uses it for S6/S7 evidence. **Reads never mutate** (no read-path side effects — the log is append-only; even "mark as read" is a separate derived store, not a log mutation).

### 6.1 Query surface

| Query | Parameters | Answers |
|---|---|---|
| `get_session(id)` | session_id | Metadata + lifecycle state + latest checkpoint ref |
| `get_events(id, after_seq, before_seq, limit)` | session_id, seq range | Positional slices (diamond-1); rewind/re-read for recovery lead-up |
| `events_by_type(id, types, since)` | session_id, type list, time bound | "all tool.calls in the last hour" |
| `events_by_tool(id, tool, since)` | session_id, tool name | Per-tool history (feeds the Beta-Bernoulli belief ledger — Cycle-1/Q1) |
| `trace(turn_id)` | trace_id | Everything about one turn across components (observability §1's join key) |
| `causal_chain(event_id)` | event_id | Follow `causal_parent` links up: what authorized this action |
| `tier3_actions(since, profile)` | time bound | Every tier-3 `tool.call` + its `approval.granted` — the S6 audit query |
| `approvals_without_action` / `actions_without_approval` | time bound | The two anomaly queries; either non-empty is an S6 incident |
| `open_loops(session_id)` | session_id | Commitments/tasks not yet closed (from checkpoint + tail) |
| `search(id, text, since)` | session_id, FTS query | Full-text over payloads (SQLite FTS5 sidecar — databases T3) |

### 6.2 Questions it must answer (acceptance criteria)

1. "What did you do at 3pm Tuesday?" → `get_events` by time range, rendered as a timeline.
2. "Show me every tier-3 action this week and their approvals." → `tier3_actions`; each row links `tool.call` → `approval.granted` → `user.message` via `causal_parent`.
3. "Why did you fail that turn?" → `trace(turn_id)`: the full event spine including `brain.fallback`, `error`, `degradation.entered`.
4. "Did I approve that?" → `causal_chain(tool_call_event_id)`: walks up to the `approval.granted` or terminates at "no approval found" — which is itself the answer.
5. "What did you tell me yesterday?" → utterance reconciliation applies: only `tts.completed` content, never generated-but-unspoken text.

### 6.3 Access control on reads

- The brain reads its own sessions freely; **cross-profile reads are denied** (databases T6: single-user today, `profile_id` required on every call as habit).
- The phone surface reads only sessions tagged with its `surface` or explicitly shared — a Telegram query can't dump the desktop's full history by default. [PROPOSED — needs the multi-surface UX decision]
- Interrogation results shown to the user pass through the same redaction as logs (observability §2): the store never returns raw secrets because it never stored them (§2.3).

---

## 7. Storage mapping — SQLite WAL schema

**Choice: SQLite in WAL mode** (databases T1, [HC]): single-user, zero-ops, crash-safe by construction (uncommitted WAL frames are ignored on recovery — the database itself implements half the crash protocol). One writer behind a lock; `busy_timeout=5000`; `PRAGMA foreign_keys=ON`, `synchronous=NORMAL`, `journal_mode=WAL` on every connection. Schema versioned via `PRAGMA user_version` with forward-only migrations (databases T1).

```sql
-- sessions.db in %APPDATA%\JARVIS\ (data dir, never the repo)
PRAGMA journal_mode=WAL;

CREATE TABLE sessions (
  session_id   TEXT PRIMARY KEY,
  profile_id   TEXT NOT NULL DEFAULT 'owais',
  surface      TEXT NOT NULL,              -- desktop | phone | scheduler
  state        TEXT NOT NULL,              -- CREATED|ACTIVE|SUSPENDED|RESUMED|COMPACTED|ARCHIVED
  created_ts   TEXT NOT NULL,
  updated_ts   TEXT NOT NULL,
  last_seq     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE events (                       -- the append-only log
  event_id      TEXT PRIMARY KEY,            -- ULID
  session_id    TEXT NOT NULL REFERENCES sessions(session_id),
  seq           INTEGER NOT NULL,            -- monotonic per session
  trace_id      TEXT NOT NULL,
  ts            TEXT NOT NULL,
  type          TEXT NOT NULL,
  causal_parent TEXT,                        -- event_id or NULL
  actor         TEXT NOT NULL,
  trust         TEXT NOT NULL,
  payload       TEXT NOT NULL,               -- JSON
  UNIQUE(session_id, seq)                    -- the replay cursor is (session_id, seq)
);
CREATE INDEX idx_events_session_seq ON events(session_id, seq);
CREATE INDEX idx_events_trace ON events(trace_id);
CREATE INDEX idx_events_type_ts ON events(type, ts);
CREATE INDEX idx_events_causal ON events(causal_parent);

CREATE TABLE checkpoints (
  session_id   TEXT NOT NULL REFERENCES sessions(session_id),
  covers_seq   INTEGER NOT NULL,            -- replay starts strictly after this
  ref          TEXT NOT NULL,              -- path to checkpoint file (same dir, tmp+rename)
  sha256       TEXT NOT NULL,
  created_ts   TEXT NOT NULL,
  PRIMARY KEY (session_id, covers_seq)
);

CREATE VIRTUAL TABLE events_fts USING fts5(payload, content='events', content_rowid='rowid');
-- NOTE: FTS sidecar must carry the same session predicate on every query (databases T6).

CREATE TABLE tombstones (                   -- deletion without rewriting history
  event_id    TEXT PRIMARY KEY,             -- tombstoned event
  session_id  TEXT NOT NULL,
  reason      TEXT NOT NULL,
  created_ts  TEXT NOT NULL
);
```

**Design notes:**
- **Events are never UPDATEd or DELETEd by the application.** The only writer operations are INSERT (events, checkpoints, tombstones) and session-state transitions. Enforcement: application-level (code review + a `no_update_events` test), since SQLite can't revoke per-table UPDATE from its own process. The *discipline* is the mechanism; the schema makes violations obvious. [HC]
- **Deletion = tombstone + purge** (privacy study's 13-item checklist, mapped):
  1. `tombstones` row per event (+ reason).
  2. Purge payloads: `UPDATE events SET payload='{}' WHERE event_id IN (...)` — the *one* sanctioned mutation, recorded in the audit trail; seq/event_id/timestamps survive (ordering and auditability preserved, content gone).
  3. FTS sidecar: delete rows, then rebuild (`INSERT INTO events_fts(events_fts) VALUES('rebuild')`).
  4. `PRAGMA secure_delete=ON` + `VACUUM` (rewrite pages), `wal_checkpoint(TRUNCATE)`.
  5. Backups: mark beyond-use; physical purge on rotation expiry (never restore deleted data).
  6. Crash reports, structured logs, metrics snapshots: grep rotations for the tombstoned content's unique strings; purge or let retention expire (documented bound).
  7. Verification pass: query + grep, confirm FTS returns nothing. Receipt recorded: what, from which stores, when, what remains (backup expiry date).
- **Backups:** `VACUUM INTO` / backup API while live (never file-copy a hot WAL DB — databases T1); 7 daily + 4 weekly in `%APPDATA%\JARVIS\backups\`; `PRAGMA integrity_check` on restore. The session DB is priority #1 (irreplaceable); the vector index rebuilds from chunks.
- **File location:** `%APPDATA%\JARVIS\sessions\sessions.db` (+ `-wal`, `-shm`). Never the repo (v1's M-S13: frozen install under Program Files is read-only). [DERIVED from v1 autopsy]
- **Size budget:** at ~1KB/event average and 200 events/day, a year is ~70MB — trivial. The 5,000-event compaction trigger (§5) keeps the hot table small; archives compress ~10:1. [MC — event size unmeasured]

---

## 8. Failure modes — the recovery ladder for the recovery system

The session store is the last line of defense; its own failures need a ladder, not a shrug.

| Failure | Detection | Response | Residual |
|---|---|---|---|
| **Corrupt checkpoint** | sha256 mismatch on load | Quarantine (`*.corrupt-<ts>`); boot from event-log replay alone; tell the user (observability §6) | Slower boot; full history still intact |
| **Corrupt event DB** | `PRAGMA integrity_check` fails on open | Restore latest verified backup; replay any newer JSONL spillover (§8.1); tell the user what was lost | Loss bounded by backup age; the JSONL spillover narrows it |
| **Disk full** | Preflight + runtime free-space gauge (<1GB) | Degradation ladder R3 (read-only): stop appending, announce, refuse new sessions; never crash mid-append | Session frozen, not lost |
| **WAL growth unbounded** | Checkpoint the WAL on every clean checkpoint (`wal_checkpoint(PASSIVE)`); alert if `-wal` >100MB | Force checkpoint; if writers stall, single-writer lock means one slow writer, not corruption | [PROPOSED threshold] |
| **Slow queries** (archive scans) | Query-time logging; p95 on `get_events` | Archive pruning policy; FTS index on hot table; interrogation of archives is async with progress | Old-history queries are slow, not wrong |
| **Log tampering (fault-tree B9)** | Append-only discipline + per-checkpoint hash chain: each `session.checkpoint` includes `prev_hash` (hash of log up to `covers_seq`) | Tamper detected at next checkpoint verification; alert as S6-class incident; restore from backup | A sophisticated attacker with disk access can rewrite the chain — this detects *accidental* and *unsophisticated* tampering, not a root-level adversary. Honest bound. [HC] |
| **Session lock contention** | Lock wait >5s | Fail closed: second `wake` refused; the holder is the live session | No split-brain; the cost is a refused wake, diagnosable |
| **Clock skew** (event ordering) | `seq` is the ordering authority, not `ts` | `ts` is display-only; causal order comes from `seq` + `causal_parent` | NTP skew can't corrupt ordering. [DERIVED from reliability dependency map] |

### 8.1 The JSONL spillover (belt and suspenders)

Every `emitEvent` ALSO appends to a per-day JSONL file (`sessions-2026-10-19.jsonl`, rotated) before the SQLite insert commits. The JSONL is the **dumb, nearly-uncorruptible** copy: sequential appends, no indexes, human-readable, greppable. If SQLite is ever unrecoverable AND backups are stale, the JSONL rebuilds the log (replay the files in order; ULIDs + seq re-derive). Cost: ~2× write I/O on the event path — negligible at 200 events/day. This is the flight-recorder philosophy: the recorder must be simpler than the system it records. [HC — derived from observability §2's "three layers, each catching what the layer above missed"]

### 8.2 What we explicitly do NOT build

- **Multi-writer / distributed consensus.** Single user, single machine, single writer. Raft is not a personal-assistant component. If multi-device sync ever arrives, tombstones + CRDTs (privacy study §5) — not now. [DERIVED from databases T1]
- **Encryption at rest in v1.** File ACLs (user profile) + OS disk encryption (BitLocker) as the last line (privacy study honest bounds). SQLCipher is a documented later option, weighed against complexity. The threat model (Cycle 10) owns this decision; the store just keeps secrets out of the log either way.
- **A query language.** The §6 API is fixed methods, not SQL-over-the-wire. The brain never concatenates anything into SQL (databases T1 security).

---

## 9. Open questions (ranked by decision urgency)

1. **Three processes vs. three trust domains in fewer processes** (diamond-1 calibration: 70%). The supervisor/harness separation is non-negotiable as *fate domains*; whether the supervisor is a separate Windows process (IPC cost, startup complexity) or an isolated thread with its own exception domain is a build-time decision. The spec works either way — the interface is `wake(sessionId)`, not the process topology.
2. **Phone-surface read scope** (§6.3): can Telegram interrogate desktop sessions? Default-deny is [PROPOSED]; the UX decision (explicit share per session vs. blanket) needs Owais.
3. **Compaction triggers** (§5.1): 5,000 events is [PROPOSED]; the real number comes from measuring replay time on the Ryzen 5 3600 (benchmark spec Track E covers checkpoint/replay timing).
4. **Archive retention** (§5.4): 1 year is [PROPOSED]; retention is the user's call (privacy study).
5. **Telegram outbox deduplication** (§4.2): Telegram's API has no client dedup ID for sends — double-send on crash remains a documented residual risk. Mitigation options (send-then-verify vs. verify-then-send) need a decision.
6. **The 43%-faithful problem** (Cycle 11): if formal verification of the gate ever arrives, the *statement* of what's proven must be audited — a proven-vacuous property is worse than an unproven real one. The session store records which properties were proven and their statements, so the audit is possible.

---

## 10. Traceability matrix — every major choice to its source

| Design choice | Source | Confidence |
|---|---|---|
| Session/harness/sandbox as separate fate domains | diamond-1 §2, §4 | [VC] |
| Append-only event log as primary record | diamond-1 §2; R6 | [VC] |
| `wake(sessionId)` recovery semantics | diamond-1 §2; observability §6 | [VC] |
| Events as unit of durability (not turns) | diamond-1 §2 | [VC] |
| Credential handles, never bytes, in the log | diamond-1 §3 (structural separation) | [VC] |
| Session is not the context window | diamond-1 §2 | [VC] |
| SQLite WAL, single writer, user_version migrations | databases T1 | [HC] |
| Checkpoint = snapshot + covers_seq; tmp+rename; quarantine on corruption | observability §6; reliability §3 | [HC] |
| Idempotency keys (= event_id) on mutating tools; outbox pattern | observability §6 | [HC] |
| trace_id via contextvars as the join key | observability §1 | [HC] |
| RTO ≤60s / RPO ≤5min/50 events; checkpoint cadence derived | reliability §3, §5 | [PROPOSED] (numbers), [DERIVED] (structure) |
| Utterance Record: truncate history to tts.completed | diamond-2 (Moshi); AGENTS.md voice doctrine | [HC] |
| Approval as causal_parent link; replay never re-arms | fault-trees B8; Cycle-1 ESCALATE | [HC] |
| Deletion = tombstone + purge + verify + receipt | privacy study 13-item checklist | [HC] |
| Degradation events in the log; safety never degrades | reliability §4 ladder rule 4 | [DERIVED] |
| JSONL spillover as the dumb durable copy | observability §2 (three layers) | [HC] |
| Hash-chained checkpoints for tamper evidence | fault-trees B9 | [HC] (mechanism), honest bound stated |
| No multi-writer, no query language, no at-rest encryption v1 | databases T1; privacy bounds | [DERIVED] decisions, marked as such |

---

## Confidence & unknowns

**[VC]:** the decoupled topology, append-only log, wake() semantics, credential exclusion, event-level durability — all directly from the Anthropic diamond's reported production experience.
**[HC]:** the SQLite mapping, checkpoint mechanics, idempotency protocol, tombstone deletion, JSONL spillover — standard distributed-systems practice applied to the diamond's topology, cross-checked against three prior studies.
**[MC]:** size budgets, compaction triggers, WAL thresholds — derived estimates awaiting the benchmarking weekend.
**[PROPOSED]:** every numeric target (RTO/RPO, 5,000 events, 1-year retention, phone read scope) — hypotheses, not promises.
**[UK]:** process-vs-thread topology for the supervisor; Telegram dedup; Owais's retention preference; measured replay/checkpoint costs on the 2060 box.

*End of R15 design spec. Status: complete as a design document; unimplemented by intent (learning phase). The next step is not more design — it's Owais's go-ahead on the v2 architecture, of which this is one component.*
