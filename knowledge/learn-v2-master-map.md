# JARVIS v2 — Master Map

*PHASE INFINITY, Research Cycle 26 (capstone synthesis). LEARNING ONLY — no code, no installs, no project files touched.*
*Date: 2026-10-19. Status: synthesis of 13 subsystem specs + 3 cross-cutting specs.*

**What this is:** the document that turns 26 research cycles into one navigable whole. Every subsystem as a box, every data flow, every trust boundary, the build order, and an honest account of what's missing. Every claim traces to a spec file.

**What this is not:** a build plan. No implementation is authorized. Implementation awaits Owais's go-ahead (see §7).

---

## 1. The Component Map

Twelve boxes. Each owns something; each is forbidden something. The owns/never-touches discipline is the architecture — it is what makes v2 different from v1, where everything touched everything.

### 1.1 Session Store — the foundation (`learn-session-store.md`, Cycle 14)

- **Owns:** the append-only event log (every event, envelope: event_id, session_id, trace_id, timestamp, causal parent); the session lifecycle (create → active → suspended → resumed → compacted → archived); crash recovery via `wake(sessionId)`; compaction policy; the interrogation interface ("show me every tier-3 action this week and their approvals"); SQLite WAL storage mapping; the JSONL spillover when the DB itself fails.
- **Never touches:** semantic facts — those belong to Memory. The session store records *what happened*; Memory decides *what is true*.
- **Key interfaces:** everything logs to it (skill pipeline E-8, brain turns, TTS completion records, approval events); phone remote reads/writes the same session for continuity; memory's nightly consolidation pass reads the session log (memory-spec §2.1 M3).

### 1.2 The Gate — the enforcement layer (defined across `learn-brain-spec.md` §0, `learn-skill-system-spec.md` §4, `learn-threat-model.md` §2)

- **Owns:** schema validation of every tool call; capability checks against the skill manifest (deny-by-default); risk-tier lookup from the tool definition (never from the brain's claim); routing tier-3 actions to out-of-band approval; tagging every tool result as `<tool_output trust="untrusted">` before it re-enters the brain. ~200 lines of plain deterministic code.
- **Never touches:** judgment. It never decides which tool to call, never interprets results, never reviews plans. The brain does judgment; code does enforcement; never the reverse (brain-spec §0 — the single most important sentence in the v2 design).
- **Key interfaces:** sits between brain and skills: `brain propose → gate check → tools execute → brain interpret`. The brain has no code path to side effects except through the gate — this is the AND-gate from the fault-tree study (Cycle 4).

### 1.3 The Brain — the judgment layer (`learn-brain-spec.md`, Cycle 19)

- **Owns:** which tool to call and with what arguments; what to ask the user; interpreting ambiguous requests; generating and repairing candidate plans; drafting what to say; three-tier model routing (1-bit CPU always-on → 7-9B GPU daily driver → cloud frontier); the fallback chain; the 8-strategy reasoning selector; the belief ledger; the ask-vs-act gate (8-step rule); context management (4k-physical + compression stack).
- **Never touches:** permissions (the gate decides allowed); tier assignment (the manifest decides); its own verification (always a separate system); recording what was spoken (the TTS completion signal writes the Utterance Record, never the brain's memory).
- **Key interfaces:** receives tagged tool results from the gate; writes proposed actions to the gate; reads memory retrieval results; logs turns to the session store.

### 1.4 The Skill System — the hands (`learn-skill-system-spec.md`, Cycle 16)

- **Owns:** manifest-based discovery (`skill.json`, never executing untrusted top-level code without approval); the tool execution pipeline (parse → schema-validate → capability-check → risk-gate → dispatch → bound → output-validate → evidence-wrap → event-log); circuit breakers (N consecutive failures → auto-disable with user notice); bounded parallelism (global concurrency budget); the SKILL.md progressive-disclosure standard.
- **Never touches:** permissions beyond its manifest grants; approval decisions (the gate routes, the user decides); other skills' state (dispatch isolation — a throwing tool cannot take down the turn).
- **Key interfaces:** tools execute only through the gate; results are evidence-wrapped before returning; the event log goes to the session store.

### 1.5 Memory — what is true (`learn-memory-spec.md`, Cycle 17)

- **Owns:** the two stores (episodic: what happened; semantic: what is true); the capture → extract → resolve (ADD/UPDATE/DELETE/NOOP) → quarantine gate → store pipeline; the hot/warm/archival tier system with ECAN-lite promotion/demotion; forgetting (temporal expiry, deletion across stores); the GUI viewer ("What JARVIS remembers"); atomic writes + backups + locking (R6).
- **Never touches:** the session event log (session store's job); untrusted content promotion — anything from tool/web sources enters quarantine, retrievable for factual questions, never auto-acted on, never promoted to behavioral facts (the C-S6 fix).
- **Key interfaces:** the brain receives retrieval results (provenance-tagged); the Hermes review loop proposes captures after each turn; the nightly consolidation pass reads the session store.

### 1.6 Approval UX — the human in the loop (`learn-approval-ux-spec.md`, Cycle 20)

- **Owns:** the approval dialog (seven required fields: action, target, blast radius, tier, origin, reversibility, what-happens-if-yes); sliding-scale autonomy (three tiers as UX, adjustable only downward); anti-fatigue design (fewer gates, never the same "yes", dwell time, fatigue detection → step-up friction, weekly autonomy review); anti-spoofing (trusted chrome, origin proof); voice approvals ("say it back" protocol, payload always on screen too); plan mode (contract, not blank check).
- **Never touches:** the enforcement decision — the dialog *renders* the request and *collects* the decision; the code gate *enforces* it. The dialog never approves by itself; a bare voice "yes" is never an approval.
- **Key interfaces:** receives tier-3 requests from the gate; returns signed approval tokens (bound to action hash, single-use, 10-min expiry) to the gate; renders in the chat UI / trusted chrome.

### 1.7 Chat UI — the primary surface (NO SPEC — see §6)

- **Would own:** message display, text input, approval dialog rendering surface, status indicators (degradation rung, never green when degraded), the "what happened" feed.
- **Status:** unspecified. Study material exists (scout-phd-chat-ui, referenced by the setup spec). This is the largest missing piece.

### 1.8 Setup & Updates — the front door (`learn-setup-spec.md`, Cycle 21)

- **Owns:** the single entry point; startup preflight (8 checks, cheap → expensive: VC++ redist → Python version/bitness → Store stub → disk space → model assets → dependency importability → mic/camera → data-dir write test); model acquisition (temp file + atomic rename + SHA-256, resume support); no-keys onboarding; signed updates (minisign) with rollback; uninstall; the zero-terminal promise.
- **Never touches:** brain/skill/memory internals (setup *delivers* them, doesn't define them); the chat UI; voice specifics (only guarantees assets + preflight).
- **Key interfaces:** preflight gates startup; the updater never applies mid-session (download in background, apply on restart); `pip install` is never LLM-triggerable.

### 1.9 PC Control — the desktop hands (`learn-pc-control-spec.md`, Cycle 22)

- **Owns:** the observation stack (UIA tree first — free and exact → OCR for text gaps → local screenshot + local VLM → gated cloud vision); one unified Python program per step (OpenGCUA pattern); grounding via ShowUI-2B on the 2060 (pixels only when the tree is insufficient); assert-after-act verification; undo for GUI actions.
- **Never touches:** the browser as its own domain (ghost browser exists separately); mobile control; remote-desktop control of other machines; elevated/UAC windows (honest boundary — announced, not attempted silently).
- **Key interfaces:** exposed to the brain as skills (tier-2 minimum for GUI actions); every action flows through the gate; screenshots are untrusted content (injection applies to pixels).

### 1.10 Proactivity — helpful without being creepy (`learn-proactivity-spec.md`, Cycle 23)

- **Owns:** the proactivity contract (per-capability opt-in, stated data flow, revocation with teeth); the screen watcher done right (opt-in with egress disclosure, RAM-only captures, probabilistic gating + cooldowns, do-not-disturb awareness); the foresight engine (one nudge, velocity taxonomy, dismissal learning, three-gate promotion); reminders and routines (durable scheduler, wake policy); the interruption budget.
- **Never touches:** financial/destructive/irreversible actions from observations (may mention once; the action is always the user's); other people's screens; passwords; speaking raw model output about the screen aloud (H-X2: attacker pixels → spoken text was a voice-phishing vector — model text about the screen is displayed, never spoken, until seen).
- **Key interfaces:** the watcher uses a brain for judgment; nudges render in the chat UI; the scheduler persists to the durable queue (survives restarts — the H-I10 fix).

### 1.11 Phone Remote — the window, not a second root (`learn-phone-remote-spec.md`, Cycle 24)

- **Owns:** the Telegram surface; the three-tier remote capability model (R0 read-only default → R1 writes with per-command confirmation + PIN → R2 never available remotely); pairing (not a static ID list — the C-B4 fix); per-sender rate limits; the poll loop (fixed: work queue, no inline brain); voice notes (transcribed locally, capped); phone ↔ PC continuity via the shared session store.
- **Never touches:** desktop session *content* by default (metadata only; content requires explicit per-session sharing from the desktop — the phone is the most losable surface); R2 actions ever; desktop-initiated confirmations (surface-bound: a confirmation requested on desktop cannot be granted from the phone).
- **Key interfaces:** reads/writes the session store (same session = continuity); dispatches through the gate with an allowlist-filtered toolset; the Utterance Record rule crosses surfaces (resumed brain history truncated to `tts.completed`).

### 1.12 Voice Loop — the plugin, built last (`learn-voice-loop-spec.md`, Cycle 15)

- **Owns:** the stage graph (mic → VAD → wake → STT → brain → TTS → speakers → mic, declared edges only); echo management by construction (guard created before speaker, state callback in the same function — the anti-C-V1 rule); barge-in on novel words (never energy alone; ≥70% word-match = echo); the TTS stop protocol that doesn't permanently mute (anti-C-V2); trace surgery on interrupt (Utterance Record); turn-taking (endpointing, no-dead-air); the two-wake-word scheme (hey jarvis = local, hello jarvis = cloud one turn); Voicebox as the TTS appliance via MCP.
- **Never touches:** brain judgment; the chatbot core (R1: the brain, skills, memory, and UI work fully with zero audio code loaded — voice is a plugin behind an interface, never imported at startup).
- **Key interfaces:** STT text feeds the brain like typed text; TTS completion signals write the Utterance Record to the session store; the fallback is always text (R1 text-only rung).

### Cross-cutting (not boxes — they constrain all boxes)

- **Threat Model** (`learn-threat-model.md`, Cycle 10): 7 trust boundaries, 6 adversary profiles, 36 deduplicated attacks, 36×12 coverage matrix with 7 uncovered cells listed honestly, 8 accepted residual risks. The rule: never by prompt alone.
- **Reliability Spec** (`learn-reliability-spec.md`, Cycle 12): 7 SLOs (S6 approval-gate integrity and S7 secret containment have zero error budget), per-subsystem RTO/RPO, the degradation ladder (R0 full → R1 text-only → R2 local-only → R3 read-only → R4 honest "I can't"), 15-row dependency map, the 15-gate ship checklist.
- **Benchmark Spec** (`learn-benchmark-spec.md`, Cycle 9): 6 measurement tracks (A model shootout, B latency, C grounding, D VRAM, E reliability, F discriminator), the executable runbook for the 2060 weekend. Spec complete, unexecuted — running it is blocked on PC access.

---

## 2. The Data Flows

### 2.1 The chat path (the primary path — R1)

```
User types in Chat UI
  → Brain: interpret request, propose action (judgment)
  → Gate: schema-validate → capability-check → tier lookup
      → tier 1/2: proceed
      → tier 3: Approval UX dialog → user decides → signed token → Gate
  → Skill pipeline: dispatch (bounded, circuit-broken) → execute → output-validate
  → Gate: evidence-wrap <tool_output trust="untrusted">
  → Brain: interpret result, draft reply
  → Session Store: append turn events (request, action, gate decision, result, reply)
  → Chat UI: render reply
  → Memory: Hermes review loop asks "anything worth remembering?" → pipeline → quarantine gate → store
```

Every arrow is a declared interface. The brain never touches tools directly; the gate never judges; the UI never executes.

### 2.2 The voice path (the plugin path)

```
Mic → VAD → Wake ("hey jarvis" ≥ threshold) → STT → [joins the chat path at "Brain"]
  → Brain → Gate → Skills → Brain drafts reply
  → TTS (sentence streaming, Voicebox appliance)
  → TTS completion signal → Utterance Record → Session Store
  → Speakers → (echo guard active: 800ms tail mute, VAD raise)
```

**Barge-in:** novel transcribed words accumulate → not echo (≥70% word-match against spoken reply) → TTS stop protocol (clears cleanly, no permanent mute) → trace surgery: brain history truncated to what actually left the speakers → user speaks.

**Wake-word routing:** "hey jarvis" → local tier; "hello jarvis" → cloud tier for exactly one turn (locked in, Phase 4).

**Failure:** any voice stage fails → R1 text-only rung, announced once: "Sir, voice is unavailable — I'm listening in text until it's restored." Voice never takes down the chatbot.

### 2.3 The proactive path

```
Screen Watcher (opt-in, RAM-only) → periodic capture
  → Judgment loop (cheap model): "does he look stuck?" → probabilistic gating + cooldowns
  → If yes: ONE nudge → Chat UI (displayed, never spoken raw — H-X2)
  → User acts or dismisses → dismissal learning tunes future nudges
Scheduler (durable queue) → reminder fires → announcement (calm voice rule, interruption budget)
Foresight Engine → velocity taxonomy (Accelerating/Cruising/Stalling/Dormant) → at most one nudge per cycle
```

Hard lines: never acts on financial/destructive observations; never creates reminders from observed context (only from stated commitments); revocation stops observation immediately.

### 2.4 The phone path

```
Telegram message → pairing check (paired chat_id, session not expired)
  → Remote dispatcher: R0 (read) / R1 (write + per-command confirmation + PIN) / R2 (refused, always)
  → Gate (allowlist-filtered toolset) → Skills → evidence-wrap
  → Session Store (same session = continuity; phone sees desktop metadata only by default)
  → Telegram reply
```

Surface-bound confirmations: a desktop-initiated tier-3 cannot be approved from the phone. The Utterance Record crosses surfaces: a resumed brain never "remembers" saying words the user didn't hear.

---

## 3. The Trust Architecture

The threat model's 7 boundaries overlaid on the component map — which box enforces what:

| Boundary | Enforced by | Where on the map |
|---|---|---|
| External content → Model | The Gate (nonce-framed `<tool_output trust="untrusted">` + instruction hierarchy) | Between Skill System and Brain, §2.1 |
| Model → Tools | The Gate (schema check, capability check, R3 routing) | Between Brain and Skill System, §2.1 |
| Tools → OS | Skill System (R4 filesystem jail, R5 sandbox, egress allowlist) | Inside the Skill System box |
| User → Gate | Approval UX + code gate (out-of-band UI confirmation, single-use nonces bound to action hash, synchronous check-and-dispatch) | Between Gate and Approval UX, §2.1 tier-3 branch |
| Memory → Model | Memory (provenance tags, quarantine gate, low-trust never auto-acted on) | Between Memory and Brain |
| App → Cloud providers | Brain routing + Proactivity (R13 opt-in, local-first default; data classification — noted GAP) | Brain tier selection; watcher egress |
| Secrets → Anywhere | OS keyring + fail-closed redaction on every log/display path | Cross-cutting; Setup never writes secrets to git-tracked config |

**Where the human sits:** at the approval gate, out-of-band, with a visible payload (seven fields) in trusted chrome. The human is not a sensor to be optimized — the anti-fatigue design (§1.6) exists because the threat model found the cheapest attack path is deceiving the user, not defeating the code (threat-model §6).

**The structural guarantee:** safety layers are AND-gates, not rungs. The degradation ladder (R0–R4) changes *capability*, never *permissions* — the gate, the jail, and redaction hold at every rung (reliability-spec §4, rule 4; fault-tree G2).

---

## 4. The Dependency Order

Which spec must be built before which. The DAG, with reasons:

```
                        ┌─────────────┐
                        │ SESSION     │  foundation: everything logs here;
                        │ STORE (14)  │  crash recovery; phone + memory depend on it
                        └──────┬──────┘
                               │
                        ┌──────▼──────┐
                        │ GATE (R2)   │  enforcement before anything acts;
                        │ (10/16/19)  │  ~200 lines, no dependencies but the manifest schema
                        └──────┬──────┘
               ┌───────────────┼───────────────┐
               │               │               │
        ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
        │ BRAIN (19)  │ │ SKILLS (16) │ │ MEMORY (17) │  brain needs gate+store;
        │             │ │             │ │             │  skills need gate;
        └──────┬──────┘ └──────┬──────┘ │  memory needs store (session-distilled capture)
               │               │        └──────┬──────┘
               │               │               │
               │        ┌──────▼───────────────▼──────┐
               │        │ CHAT UI (—)  ★ MISSING SPEC │  the surface; approval dialogs render here
               │        └──────┬──────────────────────┘
               │               │
               │        ┌──────▼──────┐
               │        │ APPROVAL    │  needs gate (enforcement) + UI (surface)
               │        │ UX (20)     │
               │        └─────────────┘
        ┌──────▼──────────────────────────────────────────────┐
        │ SETUP (21) — parallel track; needed for install,     │
        │ preflight gates startup of everything                │
        └─────────────────────────────────────────────────────┘
        ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐
        │ PC CONTROL  │  │ PROACTIVITY │  │ PHONE (24)  │  │ VOICE (15)  │
        │ (22)        │  │ (23)        │  │             │  │ ★ LAST      │
        └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘
         skill via gate   needs brain     needs store     plugin; R1:
         + UIA driver     + store         + gate + brain  chatbot core first
```

**Build waves (spec order, not a build authorization):**

1. **Wave 1 — the spine:** session store → gate → brain core → skill system → memory. The chatbot that can think, act safely, remember, and survive crashes. No UI surface yet beyond a minimal console for testing.
2. **Wave 2 — the human:** chat UI → approval UX → setup/preflight. Now it's a product Owais can install and talk to.
3. **Wave 3 — the reach:** PC control → proactivity → phone remote. The hands, the eyes, the pocket window.
4. **Wave 4 — the voice:** voice loop, last, as a plugin (R1).

**Cross-cutting through all waves:** threat model (boundaries enforced from wave 1 — never bolted on), reliability spec (SLOs measured from wave 2), benchmark spec (the 2060 weekend feeds decisions in waves 1–3).

---

## 5. The Spec Index

| # | Spec file | Cycle | One-line purpose | Status | Open questions |
|---|---|---|---|---|---|
| 1 | `learn-brain-spec.md` | 19 | Judgment layer: routing, fallback, reasoning strategies, ask-vs-act | Complete | 8 (all need 2060 or real usage) |
| 2 | `learn-skill-system-spec.md` | 16 | Manifest discovery, capability permissions, tool execution pipeline | Complete | 6 (constants PROPOSED; MCP deferred) |
| 3 | `learn-memory-spec.md` | 17 | Two stores, capture→quarantine→store pipeline, tiers, forgetting | Complete | 5 (extractor choice, Hinglish embeddings) |
| 4 | `learn-session-store.md` | 14 | Append-only event log, `wake(sessionId)` crash recovery, interrogation | Complete | 6 (process topology = build-time; compaction # needs measurement) |
| 5 | `learn-voice-loop-spec.md` | 15 | Stage graph, echo-by-construction, novel-word barge-in, wake words | Complete | 5 (thresholds uncalibrated; 3 need 2060) |
| 6 | `learn-approval-ux-spec.md` | 20 | Dialog fields, anti-fatigue, trusted chrome, voice approvals, plan mode | Complete | 8 (several need Owais's decisions) |
| 7 | `learn-setup-spec.md` | 21 | Preflight, model acquisition, onboarding, signed updates, zero-terminal | Complete | 5 |
| 8 | `learn-pc-control-spec.md` | 22 | UIA-first observation, code-per-step actions, ShowUI-2B grounding | Complete | 6 (all latency/accuracy need 2060) |
| 9 | `learn-proactivity-spec.md` | 23 | Proactivity contract, screen watcher, foresight, scheduler, interruption budget | Complete | 4 |
| 10 | `learn-phone-remote-spec.md` | 24 | Telegram R0/R1/R2 tiers, pairing, rate limits, phone↔PC continuity | Complete | 6 (PIN, session defaults need Owais) |
| 11 | `learn-threat-model.md` | 10 | 7 boundaries, 36 attacks, 36×12 coverage matrix, residual risks | Complete | 7 uncovered cells + 8 residual risks (honest gaps, not open Qs) |
| 12 | `learn-reliability-spec.md` | 12 | 7 SLOs, error budgets, RTO/RPO, degradation ladder, ship checklist | Complete | Numeric targets all PROPOSED until measured |
| 13 | `learn-benchmark-spec.md` | 9 | 6 measurement tracks + executable runbook for the 2060 weekend | Complete as spec; **unexecuted** (blocked on PC access) | — |

**Total: 13 specs, 13 complete as design documents. 0 tested. 0 measured.** (Rule 12: researched / saved — yes; validated / tested / measured — no. Design is not proof.)

---

## 6. What's NOT Yet Specified

Honest list — subsystems with no spec:

1. **Chat UI (the chatbot window)** — the largest gap. No `learn-chat-ui-spec.md` exists. Study material exists (`scout-phd-chat-ui`, referenced by the setup spec §10 as the owner of "frontend §1"), but no design document. The approval UX spec describes *what the dialog contains*; nothing specifies the window it renders in, the message list, the input, the status indicators, or the transcript behavior. This blocks Wave 2.
2. **HUD (the holographic overlay)** — no v2 spec. v1's `overlay.py` is the reference implementation, but the chatbot-first design hasn't specified whether/how the arc-reactor HUD returns. Not needed for Wave 1–2; needed before any "JARVIS feel" work.
3. **MCP servers inside plugins** — explicitly deferred by the skill spec (OQ4): "ship skills first, MCP second. Needs a dedicated study before v2 ships plugin MCP support."
4. **Skill version migration** — unspecified (skill-spec OQ6): v1→v2 of a skill with stored data has no migration story.
5. **App → Cloud data classification** — noted as a GAP in the threat model (§2, §6): prompts/screenshots/audio leave the machine with no classification layer before send. Local-first routing is the mitigation; the classifier is unbuilt.
6. **Chat UI-adjacent decisions** that are really Owais's: the R1 confirmation-set boundary (phone-spec OQ1), the PIN question (OQ2), session-share defaults (OQ4/OQ6, session-store OQ2), the ask budget (brain-spec OQ8), archive retention (session-store OQ4). These aren't missing specs — they're decisions only he can make.

---

## 7. The Build-Readiness Verdict

Per subsystem — three verdicts: **spec-complete** (design done, buildable), **needs-measurement** (design done, numbers await the 2060 weekend), **needs-decision** (design done, a human choice blocks finalization).

| Subsystem | Verdict | The specific blocker |
|---|---|---|
| Session store | spec-complete; needs-decision | Process topology (3 processes vs isolated thread) — build-time call |
| Gate | spec-complete | — (defined across three specs; ~200 lines) |
| Brain | spec-complete; needs-measurement | 8 open Qs: tier thresholds, discriminator accuracy, model shootout, Hinglish boundary |
| Skill system | spec-complete; needs-measurement | Numeric constants (breaker N, timeouts, budgets) — sane defaults proposed |
| Memory | spec-complete; needs-measurement | Extractor model choice; Hinglish embedding quality |
| Chat UI | **needs-spec** | No design document exists — the critical path item |
| Approval UX | spec-complete; needs-decision | R1 boundary, PIN, session-share defaults — Owais's calls |
| Setup/updates | spec-complete | — |
| PC control | spec-complete; needs-measurement | All latency/accuracy numbers need the 2060 |
| Proactivity | spec-complete; needs-decision | Consent defaults are Owais's |
| Phone remote | spec-complete; needs-decision | 6 open Qs, several need Owais |
| Voice loop | spec-complete; needs-measurement; **build-last** | Thresholds uncalibrated; R1: plugin after chatbot core |

**The explicit statement:** 13 of 14 subsystem areas are spec-complete as learning documents. None are validated, tested, or measured — design is not proof, and this document does not claim otherwise. The chat UI has no spec. Several decisions need Owais. **No implementation is authorized. The build begins when Owais says go.**

---

## Traceability

Every section above traces to:
- The 13 spec files in `~/workspace/jarvis-knowledge/` (§5 index)
- `~/workspace/jarvis-build/FAILURE-ANALYSIS.md` (the v1 corpses each spec was written to prevent; R1–R14 + proposed R15)
- `~/workspace/jarvis-knowledge/DECISION-PLAYBOOK.md` (S1–S8, V1–V8, A1–A8, M1–M4, P1–P5)
- `~/workspace/jarvis-knowledge/MASTER-INDEX.md` (the knowledge map this document caps)

**Honest completion (Rule 12):** Researched: 13 spec files read (headers + interface sections + open questions). Validated: cross-references checked (e.g., phone-spec §5.2 resolves session-store OQ2; skill E-8 logs to session store; approval tokens bound to action hash per fault-tree B3/B8). Saved: 1 file. Tested/Measured: nothing — synthesis only, as tasked. Incomplete: chat UI + HUD have no specs (§6). Blocked: implementation awaits Owais's go-ahead (§7).
