# Phone Remote (Telegram) — Design Specification

*PHASE INFINITY, Research Cycle 24. The phone is a window into JARVIS, not a second root account.*
*Date: 2026-10-19. Status: design spec, unbuilt. LEARNING ONLY — no project files touched, no installs, no code executed.*

---

## 0. The doctrine

v1 treated the Telegram channel as a second mouth for the same brain: the allowlisted sender got `brain.respond` with the **entire toolset** (C-X6). A borrowed phone or hijacked Telegram session was full remote PC control. The design principle for v2:

**The phone surface is a separate trust domain from the desktop surface.** It gets its own capability set, its own confirmation rules, its own rate limits, and its own session read scope. Nothing on the phone path assumes the desktop path's privileges. Every clause below answers a v1 corpse or an uncovered threat-model cell. Where this spec proposes a number, it is [PROPOSED] until measured.

---

## 1. The remote capability model

Three tiers. Enforced in deterministic code on the PC side (the phone sends *requests*; the PC decides what they *mean*). The R2 rule applies: prompts and chat text never grant capability — the tier is structural, checked before the brain is consulted.

### Tier R0 — read-only (default, no confirmation)

The phone may, without any confirmation:

- Ask questions answered from the brain's knowledge and memory ("what did I ask you to remind me about tomorrow?")
- Check PC status (is JARVIS running, what rung of the degradation ladder is it on, last-seen time)
- Read the activity feed (recent events from the session store — subject to §5 read-scope rules)
- Query interrogation results ("what did you do at 3pm?")
- Receive proactive notifications the desktop chose to send (scheduler briefings, error alerts the user opted into)

Tier R0 is **read and talk**. It cannot change state on the PC. [DERIVED — E1's "read-only default," made enforceable]

### Tier R1 — writes with per-command confirmation

Anything that changes state on the PC requires **out-of-band confirmation** delivered and answered on the phone surface:

- File writes/edits (inside the workspace jail only — R4 holds remotely too)
- Sending messages on the user's behalf (email, social)
- Starting/stopping skills, changing settings, scheduling reminders
- Any `system_control` action (app launch/close, volume, media)

The confirmation is a Telegram inline button or explicit typed "yes" bound to the **action hash** (the fault-tree B3/B8 fix: the approval token embeds the action hash, so a swapped action invalidates the token). The approval is a session-store `approval.granted` event whose `causal_parent` is the exact `tool.call` event_id — replay never re-arms (session-store §4, step 4). [DERIVED — R3 applied to the remote surface + fault-tree B8]

**Confirmation UX rules:**

- The approval message shows the payload in plain language (action + target + blast radius), never a bare "allow?" (fault-tree B7: a spoofed or meaningless dialog has nothing to convince with — the same logic applies to our own dialog being *meaningful*).
- Confirmations expire: 10 minutes, unanswered → denied, logged. [PROPOSED]
- One confirmation = one action. No "approve all," no standing approvals, no session-wide elevation. The phone never gets a mode where confirmations are off.
- Confirmation requests are rate-limited separately from chat (see §3): manufactured approval fatigue (threat-model F3, UNCOVERED cell) is a denial-of-safety attack. More than 5 confirmation requests in 10 minutes → pause and tell the user "I'm holding further requests — reply RESUME when ready." [PROPOSED]

### Tier R2 — never available remotely

The following are refused at the phone surface *before the brain sees the request*, with a plain-language explanation and the desktop alternative:

- `execute_code` and any arbitrary command execution
- Destructive system actions (shutdown, restart, logoff, process kill, file delete outside trash)
- Secret/key management (viewing keys, adding keys, exporting secrets)
- Skill installation or enabling new skills (new code paths — R11)
- Updater actions (`git pull`, `pip install`, applying updates — R10)
- Memory deletion or bulk memory export (privacy: deletion needs the desktop, where the user can see what they're deleting)
- Changing the remote capability model itself (no privilege escalation from the phone, ever)

**Why the hard list instead of "confirm everything":** confirmations work for actions the user can *evaluate* in a chat bubble. `execute_code` output can't be meaningfully evaluated on a phone screen, and a destructive action confirmed by accident on a borrowed phone is irreversible. The threat model's residual-risk finding — "the remaining holes are all on the human side of the gate" — is sharpest on a small screen; the answer is fewer, not more, confirmable actions. [DERIVED — E1 scoping + threat-model residual risks]

### Enforcement architecture

The phone channel does not call `brain.respond` directly. It calls a **remote dispatcher** that:

1. Classifies the request into R0/R1/R2 by matching against the remote command allowlist (explicit list, not pattern-guessing — R11's manifest discipline applied to the surface).
2. R2 → refuse with explanation. R1 → emit `approval.requested`, wait for the bound confirmation, then dispatch. R0 → dispatch to a brain turn whose toolset is the **remote-scoped toolset** (a strict subset: no `execute_code`, no system control beyond R1-confirmed actions, read tools only).
3. The remote-scoped toolset is constructed at startup from the skill manifest, filtered by the remote allowlist. A skill not on the allowlist is invisible to phone turns — the brain can't even name it. [DERIVED — E1 PARTIAL resolved: "scoping designed, not enforced" → enforced here]

---

## 2. Identity and session binding

### 2.1 Pairing (not a static ID)

v1 used a static `allowed_user_ids` list typed into settings — which the settings panel could silently corrupt from `[]` to `""` (C-B4), killing the phone link with no error. v2 replaces the static list with a **pairing flow**:

1. On the desktop: Settings → Phone → "Pair new device" generates a one-time 6-digit code, valid 5 minutes, shown once. [PROPOSED]
2. On the phone: send the code to the bot in a DM. The PC binds the Telegram `chat_id` + `user_id` pair to the profile, emits a session-store `session.created` (surface=phone) event, and sends a confirmation the user sees on *both* surfaces.
3. The pairing code is single-use; generating a new one invalidates the old.

**Why this beats the static ID:** the static ID is a bearer token that never expires and can't be rotated without hand-editing YAML. Pairing gives you issuance, expiry, per-device identity, and revocation — the consent lifecycle (privacy study: GRANT → ACTIVE → REVOKED → PURGED) applied to the phone. [DERIVED — privacy consent lifecycle + C-B4]

### 2.2 The P4 adversary: borrowed phone / hijacked session

The threat model names it explicitly: physical access to an unlocked phone, or a hijacked Telegram session, inherits the paired identity. Defenses in depth:

- **Session expiry:** phone sessions expire after 24 hours of inactivity; re-pairing requires the desktop code again. A stolen phone goes stale by itself. [PROPOSED]
- **Destructive-adjacent R1 actions need a second factor on the phone:** the confirmation for R1 writes includes a 4-digit PIN set at pairing time (not the pairing code — a separate, persistent PIN the user memorizes). An attacker holding the unlocked phone still can't confirm writes without the PIN. [PROPOSED]
- **Theft response:** from the desktop, one click: "Revoke phone access." This kills the pairing, expires the session, and the bot stops responding to that chat_id immediately. Also available: replying REVOKE from any *other* paired surface. [DERIVED — consent lifecycle REVOKED]
- **Anomaly tripwire:** a new device fingerprint (Telegram reports the client) on an existing pairing → the PC demands re-pairing rather than trusting it. [PROPOSED]

### 2.3 Group chats

v1 replied in group chats, leaking answers to all members (H-X10). v2: **the bot ignores group chats entirely** — DMs only, from the paired chat_id only. A message from any other chat_id gets no response and is logged as a contact attempt (visible on desktop: "someone messaged your JARVIS bot"). [DERIVED — H-X10]

---

## 3. Rate limiting and abuse resistance

E2 is an UNCOVERED threat-model cell: "thresholds unspecified." This section specifies them. All [PROPOSED] until the reliability soak measures real costs.

### 3.1 Per-sender limits

| Bucket | Limit | Window | On exceed |
|---|---|---|---|
| Text messages | 20 | 1 minute | Soft: reply "slow down, I'm catching up" once per 5 min; hard-drop beyond 40/min |
| Voice notes | 5 | 5 minutes | Drop with explanation |
| Brain turns (full LLM) | 10 | 5 minutes | Queue, don't drop: tell the user their position; queue depth cap 5, then refuse politely |
| R1 confirmation requests | 5 | 10 minutes | Hold further requests (the F3 fatigue defense, §1) |
| Pairing attempts | 3 | 15 minutes | Lock pairing for 1 hour, alert desktop |

Counters are per paired chat_id, in-memory with the session store as backup (survive restart — the limits must not reset on crash, or a crash becomes a limit reset). [PROPOSED]

### 3.2 Circuit breaker on error loops

v1's poll loop retried every 5 seconds forever on auth failure, spamming errors into the HUD (C-I4, M-I24's cousin). v2:

- **Auth failure (401):** 3 attempts with exponential backoff (5s, 20s, 60s), then the channel **disables itself** and raises a desktop alert: "Telegram disconnected — check the bot token." It never retries again until the user re-enables it. A 401 means the credential is wrong; retrying is not a strategy. [DERIVED — C-I4]
- **Transport errors (5xx, timeouts):** bounded retries (5) with jittered backoff, then degrade: the channel reports "phone link degraded" on desktop and keeps a slow heartbeat (1 poll / 5 min) so it recovers without spam. (Reliability spec: degradation announced, never silent; hysteresis on recovery.)
- **Brain-turn errors:** 3 consecutive turn failures → the phone surface announces "I'm having trouble thinking right now — the desktop still works" and stops accepting new turns until one succeeds. The error loop cannot burn compute forever. [DERIVED — H-X10's cost-DoS]

### 3.3 The poll loop, fixed (M-I22)

v1 ran the brain inline on the poll thread: a 30s+ turn stalled polling; a hung brain hung the channel. v2:

- The poll loop does exactly one thing: fetch updates, validate, enqueue. It never blocks on the brain.
- A **bounded work queue** (depth 10, [PROPOSED]) feeds a single worker thread. Queue full → the update is acknowledged-but-deferred with a "I'll get to this" reply, not silently dropped, not unboundedly queued.
- Poll interval adapts: 1s when a conversation is active, 10s idle, 5-min heartbeat when degraded. Long polling with a 30s timeout (not tight-loop `getUpdates`). [DERIVED — M-I22]
- Every poll-loop exception is caught, counted, and circuit-broken per §3.2 — never a tight fail-loop (M-I24's lesson, applied to the channel).

---

## 4. Voice notes

### 4.1 The path

1. Telegram voice message arrives (`.oga`/Opus). The channel downloads it to a temp file — **size cap 10 MB** (roughly 10 minutes of Opus; [PROPOSED]).
2. Over the cap → refused before download completes, with "voice note too long — keep it under ~10 minutes." The download streams with a byte counter; the cap is enforced *during* transfer, not after. (M-X10's 20MB RAM spike: v1 had no cap at all; the fix is a streaming cap, not a post-hoc check.) [DERIVED — M-X10]
3. Transcription runs through the **local STT** (faster-whisper/whisper.cpp) — the voice note never goes to a cloud STT. This is both a privacy rule and a cost rule.
4. The transcript enters the pipeline as a `user.message` event with `audio_ref` pointing at the temp file; the audio bytes are **deleted after transcription** (session-store §2.3 exclusion list: audio bytes never in the log; privacy study: voice audio RAM-only, never disk — the temp file is the one sanctioned exception, deleted immediately). [DERIVED — session-store §2.3, privacy study]
5. On transcription failure: tell the user plainly ("I couldn't make out that voice note — could you type it?"), log the failure class (not the audio), never retry in a loop.

### 4.2 What voice notes can't do

A voice note is a Tier R0/R1 input, same as text. It cannot carry R2 actions, and a voice note *confirming* an R1 action is not accepted — confirmations require the inline button or typed "yes" (voice-confirmed approvals are spoofable by anyone who can play audio at the phone; the session-store event model records `method: button/typed`, and voice is not on the list). [DERIVED — R3 + fault-tree B7]

---

## 5. Continuity — phone ↔ PC handoff

### 5.1 The mechanism

Both surfaces share the session store (session-store §1, purpose 4: "the brain is cattle; the session is the thread of continuity"). A turn started on the desktop continues on Telegram because the session — not the process — holds the state. Concretely:

- The phone surface reads and writes the **same session** when the user says "continue" (or by default, the most recent active session — [PROPOSED], needs the UX decision).
- The Utterance Record rule crosses surfaces: if the desktop was mid-TTS-reply when the user switches to phone, the resumed brain's history is truncated to `tts.completed` — it never "remembers" saying words the user didn't hear on the speakers just because the phone is now the surface. [DERIVED — session-store §4, Moshi rule]
- Pending R1 confirmations are surface-bound: a confirmation requested on desktop cannot be granted from the phone and vice versa. The approval dialog lives where the action was requested. (Otherwise a phone attacker could approve a desktop-initiated destructive action — the P4 adversary again.) [DERIVED]

### 5.2 Read scope — refining session-store §6.3

The session store proposed default-deny: the phone reads only sessions tagged with its surface or explicitly shared. This spec refines it:

- **Phone-created sessions:** full read access. Obviously.
- **Desktop sessions:** the phone sees *metadata only* by default (session exists, last activity time, turn count) — not the content. Content requires explicit per-session sharing from the desktop ("share this session with my phone"), which emits a session-store event and expires with the phone session (24h inactivity, §2.2). [PROPOSED — resolves session-store open question #2 with a concrete default]
- **Why default-deny:** the phone is the most losable surface. A desktop session may contain screen-watcher observations, file contents, clipboard-adjacent material — exactly the things that shouldn't survive a phone theft. The metadata-only default gives continuity ("continue where I left off" works — the phone can *see* the session and ask to share it) without the exfiltration surface.
- **Scheduler sessions:** readable — they're the user's own briefings and reminders, designed to be consumed remotely. [PROPOSED]

---

## 6. The secrets rules

1. **Token acquisition:** the user creates the bot via @BotFather (their 30-second job — the standing rule: signups are theirs). The token is pasted into Settings → Phone, which writes it to the **OS keyring** (Windows Credential Manager), never to any file. [DERIVED — R9, M-X3]
2. **The loader ignores secret-looking keys in `config.yaml`.** If `telegram_bot_token` appears in `config.yaml` (git-tracked), the loader refuses it with a warning pointing at Settings → Phone. v1's natural token placement leaked to GitHub on the next push (M-X3); the loader makes that placement inert. [DERIVED — M-X3, threat-model E3 "covered by rule"]
3. **No token-bearing URLs in logs.** The Telegram API puts the token in the URL path (`/bot<token>/...`). The channel constructs requests through a wrapper that **redacts the token before any logging, exception formatting, or HUD display**. v1's `HTTPError` embedded the full URL and it landed in `jarvis.log`, the console, and the HUD every 5 seconds (C-I4). The wrapper is covered by a test that feeds a 401 and asserts the token string appears nowhere in the captured log. [DERIVED — C-I4, R9 redaction filter]
4. **No raw exceptions to chat.** v1's `_safe_handle` returned raw brain exceptions to the chat — paths, key fragments (M-X1). v2 maps exceptions to a fixed set of user-facing messages ("something went wrong on my end — the desktop has the details"); the full redacted trace goes to the session store's `error` event and the desktop log only. [DERIVED — M-X1, R12 honest UX]
5. **Token validation at startup (M-I23).** The channel calls `getMe` on startup. Empty/missing token → channel stays disabled with a desktop notice ("phone not configured"), not a 404-spam loop. Invalid token → the C-I4 backoff path, then disable + alert. The channel never runs in a state where it doesn't know its credential is good. [DERIVED — M-I23]
6. **No token in backups or crash reports.** The crash reporter and the settings-export path scrub the keyring handle list; a backup contains "telegram: configured" — never the token. (Privacy study: secrets never sync; the phone pairing is per-device anyway.) [DERIVED — R9]

---

## 7. Reliability

Covered mostly in §3 (the poll loop, backoff, circuit breakers). Three remaining items:

### 7.1 Message dedup — resolving session-store open question #5

The session store left this open: Telegram's `sendMessage` has no client dedup ID, so a crash between send and log-mark can double-send. Decision: **send-then-verify**.

- The outbox entry is written *before* the send (`tool.call` IS the intent — session-store §4.2).
- After sending, the channel immediately calls `getUpdates`/reads the sent message's `message_id` from the response and marks the outbox entry `confirmed` with that ID in the same transaction.
- On recovery, any outbox entry `sent` but not `confirmed` is checked: query the chat's recent messages for a matching `reply_to` / text hash within the window. If found → mark confirmed, no resend. If not found → resend once with a "resending — I restarted" prefix so a duplicate is recognizable, not confusing.
- The residual risk (send succeeded, process died before the response was read, message not yet visible on query) is documented and accepted: the failure mode is a *duplicate message*, never a duplicate mutating action — because mutating actions are never triggered by the send path. Duplicated text is embarrassing; duplicated side effects are dangerous; the design ensures only the former is possible. [DERIVED — session-store §4.2/§9, R6 atomicity]

### 7.2 Update offset discipline

The poll loop persists `update_id` offset in the session store (not in memory — M-I22's stall and any crash would reprocess or skip updates). On startup, resume from the stored offset. Updates older than 24h are skipped with a log line (a week-old "do X" resurfacing after a long outage is worse than useless). [DERIVED — M-I22, session-store durability]

### 7.3 Health signal

The phone channel emits a heartbeat event to the session store every 5 minutes (`phone.heartbeat`: queue depth, last poll latency, consecutive errors). The desktop's reliability dashboard (reliability spec §4) reads it; the user can ask "is my phone link healthy?" from either surface and get a real answer, not a guess. [DERIVED — reliability spec observability]

---

## 8. The failure table — every corpse mapped

| Corpse | Spec clause |
|---|---|
| C-X6: allowlisted sender gets full brain + all tools | §1 — three-tier capability model; remote-scoped toolset; R2 never-available list; remote dispatcher, not direct `brain.respond` |
| C-I4: token leaked into logs/HUD on 401, retried every 5s forever | §3.2 — 3-attempt backoff then self-disable + desktop alert; §6.3 — token-redacting request wrapper + test |
| H-X10: no rate limiting; group-chat reply leaks | §3.1 — per-sender rate limits with named thresholds; §2.3 — group chats ignored entirely |
| M-X1: raw brain exceptions returned to chat | §6.4 — fixed user-facing message set; redacted traces to store + desktop only |
| M-X2: `resolve_token` accepts any token with len > 16 | §6.5 — `getMe` validation at startup; invalid → backoff → disable, never a spam loop |
| M-X3: token falls back to git-tracked `config.yaml` | §6.1–6.2 — keyring only; loader ignores secret-looking keys in `config.yaml` with warning |
| M-X7 (Telegram half): token in URL path | §6.3 — redacting wrapper; token never in a loggable string |
| M-I22: brain inline on poll thread; hung brain hangs channel | §3.3 — poll loop only enqueues; bounded work queue; single worker thread; adaptive intervals |
| M-I23: no token validation; `""` → 404-spam loop | §6.5 — startup `getMe`; empty token → disabled with notice, never a loop |
| C-B4 (Telegram half): settings save rewrites `allowed_user_ids` `[]`→`""`, killing the phone link silently | §2.1 — pairing flow replaces the static ID list; no hand-edited allowlist to corrupt |
| E1 (threat model): remote scoping PARTIAL — "designed, not enforced" | §1 enforcement architecture — dispatcher + allowlist-filtered toolset constructed at startup |
| E2 (threat model): rate limits UNCOVERED — "thresholds unspecified" | §3.1 — specified (all [PROPOSED]) |
| E3 (threat model): token in git config | §6.1–6.2 — keyring only + loader refusal |
| F3 (threat model): manufactured approval fatigue, UNCOVERED | §1 — 5 confirmations / 10 min then hold + RESUME; §3.1 — confirmations rate-limited separately |
| Session-store §9 Q2: phone read scope of desktop sessions | §5.2 — metadata-only default; explicit per-session share, expiring with phone session |
| Session-store §9 Q5: Telegram outbox dedup | §7.1 — send-then-verify; duplicate text possible, duplicate side effects impossible by construction |

No orphans. Every named corpse and every remote-cluster finding has a clause.

---

## 9. Open questions (ranked by decision urgency)

1. **The R1 confirmation set boundary** (§1): exactly which actions land in R1 vs R2 needs the concrete tool inventory at build time. The principle is fixed (evaluable-in-a-chat-bubble); the list is not. Needs Owais's review — it's his risk tolerance being encoded.
2. **The PIN** (§2.2): memorized 4-digit PIN vs. phone biometrics (Telegram doesn't expose biometric gating to bots — so it's PIN or nothing). Needs Owais: is a PIN acceptable UX, or does it kill the convenience the phone is for?
3. **Rate-limit numbers** (§3.1): all [PROPOSED]. The reliability soak (benchmark spec Track E) should measure real turn costs and set these from data, not guesses.
4. **Default session for "continue"** (§5.1): most-recent-active vs. ask-every-time. Needs the multi-surface UX decision (session-store §9 Q2's sibling).
5. **Voice-note cap** (§4.1): 10 MB / ~10 min is [PROPOSED]. Whisper-small local transcription time for 10 min of audio on the Ryzen 3600 is unmeasured — the benchmarking weekend should time it.
6. **Session-share expiry** (§5.2): tied to phone-session expiry (24h inactivity) — but should a share survive re-pairing? Default no (re-share explicitly); needs Owais's call.

---

## 10. Traceability matrix

| Design choice | Source | Confidence |
|---|---|---|
| Three-tier capability model; R2 never-available list | E1 (threat model); C-X6 | [HC] |
| Remote dispatcher + allowlist-filtered toolset at startup | E1 "designed, not enforced" → enforced; R11 manifest discipline | [HC] |
| Approval bound to action hash; one confirmation = one action; 10-min expiry | R3; fault-tree B3/B8; session-store §4 | [HC] |
| Confirmation fatigue hold (5/10min + RESUME) | F3 uncovered cell; fault-tree B11 | [PROPOSED] (numbers), [DERIVED] (mechanism) |
| Pairing flow replacing static ID list | C-B4; privacy consent lifecycle | [HC] |
| 24h phone-session expiry; per-device revocation | P4 adversary (threat model); consent REVOKED | [PROPOSED] |
| R1 write confirmations need memorized PIN | P4 borrowed-phone case | [PROPOSED] |
| Group chats ignored; DMs from paired chat_id only | H-X10 | [HC] |
| Per-sender rate limits (named thresholds) | E2 uncovered → specified; H-X10 cost-DoS | [PROPOSED] |
| Auth-failure: 3-attempt backoff then self-disable + alert | C-I4 | [HC] |
| Poll loop enqueues only; bounded queue; adaptive intervals | M-I22; M-I24 (no tight fail-loops) | [HC] |
| Voice-note 10MB streaming cap; local STT; audio deleted post-transcription | M-X10; session-store §2.3; privacy study | [PROPOSED] (cap), [DERIVED] (path) |
| Voice cannot confirm R1 actions | R3; fault-tree B7 | [HC] |
| Phone ↔ PC handoff via session store; surface-bound approvals | Session-store §1 purpose 4; P4 | [HC] |
| Utterance Record across surfaces | Session-store §4 Moshi rule | [HC] |
| Desktop sessions: metadata-only default; explicit expiring share | Session-store §9 Q2 → resolved | [PROPOSED] |
| Token in OS keyring; loader refuses config.yaml secrets | M-X3; R9; E3 | [HC] |
| Token-redacting request wrapper + 401 test | C-I4; R9 redaction | [HC] |
| Fixed user-facing error messages; no raw exceptions to chat | M-X1; R12 | [HC] |
| Startup `getMe` validation; empty token → disabled, never a loop | M-I23; M-X2 | [HC] |
| Send-then-verify outbox; duplicate text possible, duplicate side effects impossible | Session-store §4.2/§9 Q5 → resolved | [HC] |
| Update offset in session store; >24h updates skipped | M-I22; session-store durability | [HC] |
| Phone heartbeat every 5 min to session store | Reliability spec §4 observability | [PROPOSED] |

---

## 11. The one-line version

The phone gets eyes and a voice, never hands: it can see what JARVIS is doing and ask it things, it can request changes that JARVIS confirms back in plain language, and the things that could hurt — code execution, destruction, secrets, updates — simply do not exist on the remote surface. A stolen phone yields a read-only window that goes stale in a day, not a root shell.
