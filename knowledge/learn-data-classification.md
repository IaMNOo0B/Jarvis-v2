# App→Cloud Data Classification — Closing the C6/C7 Gap

*PHASE INFINITY, Research Cycle 27. Learning-only design document — no code, no installs, no code execution.*
*Date: 2026-10-19. Status: design complete, NOT validated on hardware, real usage, or adversarial testing.*

**What this is:** the missing layer the threat model names but never designs. Two uncovered cells — **C6** (clipboard → cloud, no mitigation in any source) and **C7** (full history → cloud, "named as concern, no enforcement designed") — plus residual risk #6 ("classification-before-send is a defined build task"). This document is that build task, specified.

**What this is NOT:** a DLP product, a promise of perfect detection, or a recall mechanism for data already sent. Provider-side retention (threat-model residual risk #3) is unchanged by this layer: classification governs what *leaves*, not what providers *keep*.

---

## 0. The Problem Restated

### The two cells [VC — learn-threat-model.md §4]

| ID | Attack | Vector | Why it was uncovered |
|---|---|---|---|
| **C6** | Clipboard into cloud context | `clipboard_get` pulls passwords/2FA/API keys into LLM context → transmittable to cloud brains, speakable | No source named any mitigation. The clipboard is the highest-density secret surface on a PC (passwords are *copied*, not typed). |
| **C7** | Full history → cloud every turn | Clipboard, file contents, diagnostics leave the machine unclassified on every cloud-brain call | Named as concern (v1 M-X5, M-X6). The brain-spec's tier routing reduces *how often* data goes to cloud; nothing governs *what* goes when it does. |

### The v1 corpses this answers [VC — FAILURE-ANALYSIS.md]

- **M-X5:** full conversation history → cloud every turn, no data classification or redaction.
- **M-X6:** `clipboard_get` pulls clipboard (often passwords/2FA) into LLM context → transmittable to cloud, speakable. No secret detection.
- **M-X4:** nothing stops `save_learned_knowledge("my wifi password")` — spoken secrets persist to plaintext, re-inject into prompts, transmittable to cloud brains. (Adjacent: classification tags travel into memory — §8.)

### The design thesis [HC — new design, traced below]

**Classification is a deterministic pipeline stage between the gate and the network — not a model judgment, not a prompt.** It runs on every cloud-bound payload, tags content by class, and enforces a per-class policy in code. Detection uses fast deterministic methods first (patterns, registries); a small local model may assist, but the *enforcement* (block/confirm/send) never depends on a model's opinion. This follows the brain-spec's core principle: the brain does judgment, code does enforcement.

The layer has a name for the architecture: the **Data Classification Layer (DCL)**.

---

## 1. The Classification Taxonomy

Four classes. Every piece of content crossing the App→Cloud boundary gets exactly one. Definitions are operational (a classifier can implement them), not legalistic.

### The four classes

| Class | Definition | JARVIS examples | Policy |
|---|---|---|---|
| **PUBLIC** | Content with no privacy impact if disclosed | User's spoken command ("what's the weather"), public web page text, tool schemas, system prompt | Send freely. No note. |
| **PERSONAL** | About the user but not exploitable: preferences, project names, non-sensitive file contents, conversation substance | "Remind me about the dentist", notes.md contents, calendar event titles, code the user wrote | Send. Logged in the "what left the machine" feed as a class label (never content). |
| **SENSITIVE** | Exploitable with effort or embarrassing: personal identifiers, financial amounts, health mentions, location history, private communications, full file contents of unknown provenance | Email bodies, bank balances, home address, medical notes, someone else's messages on screen | **Confirm-first** on first occurrence per session (or per data item — §5); send only after explicit user confirmation; always feed-logged. |
| **SECRET** | Directly credential-equivalent: authenticates, decrypts, or authorizes | API keys, passwords, 2FA codes, OAuth tokens, Telegram bot token, SSH private keys, session cookies, credit card numbers, crypto seed phrases | **Never sent to cloud.** Local tiers only. Withheld with a placeholder (see §3). |

### Boundary rules [HC — new design]

1. **When in doubt, escalate the class.** A classifier unsure between PERSONAL and SENSITIVE tags SENSITIVE. Unsure between SENSITIVE and SECRET tags SECRET. False positives cost annoyance (recoverable — §5); false negatives cost leaks (irrecoverable — provider retention).
2. **The class of a composite is the max of its parts.** A prompt containing one SECRET segment is SECRET-classified as a whole for policy purposes — then redacted down (see §3), not blocked wholesale.
3. **User-stated constraints are never downgraded.** "Never send my location to the cloud" pins location data at SECRET regardless of what the classifier thinks. Pins live in the verbatim constraint slot (brain-spec §5) and the DCL reads them before every classification.
4. **Classification is per-content, not per-turn.** The same turn can carry PUBLIC tool schemas, PERSONAL user text, and a SECRET clipboard segment. Policy applies per segment.

### What the taxonomy does NOT try to do [MC — honest scope]

- It does not classify *intent* (is this request malicious?) — that's the gate's job (R3).
- It does not judge *accuracy* — that's the verifier's job.
- It does not handle *inferred* sensitivity well (ten PERSONAL facts that together identify someone). Marked as a known limitation — §6.

---

## 2. Detection Mechanisms

Three detection tiers, run in order, cheapest first. The design principle: **deterministic methods carry the security weight; model-based methods are assist-only.**

### Tier A — The known-secrets registry [VC — extends C2's `register_secret()`]

The strongest mechanism, and it's structural, not heuristic.

At startup, every secret loaded into the OS keyring (R9) is **registered** with the DCL: not the value (never stored twice), but a salted hash plus a length + format fingerprint. Any content matching a registered fingerprint is SECRET **by construction** — no pattern-matching uncertainty, no false positives possible on the system's own secrets.

- Covers: API keys, Telegram token, OAuth refresh tokens — everything in the keyring.
- Cost: one hash lookup per content segment. Negligible.
- Limitation: only covers secrets the system *knows*. User-pasted passwords, 2FA codes from SMS, secrets in files — those need Tier B. [VC]

This is the same registry C2's `RedactingFilter` uses for log redaction — one registry, two enforcement points (logs + cloud-bound payloads). [HC — learn-threat-model.md §4 C2]

### Tier B — Secret-pattern detection [HC — deterministic, well-understood]

Regex + entropy + format checks for credential-shaped content the registry doesn't know:

| Pattern family | Examples | Reliability |
|---|---|---|
| Labeled secrets | `password\s*[:=]\s*\S+`, `api[_-]?key\s*[:=]`, `secret\s*[:=]` | High precision; misses unlabeled |
| Token formats | `ghp_`, `sk-`, `xoxb-`, `AKIA`, `-----BEGIN .*PRIVATE KEY-----`, `bot\d+:[\w-]+` (Telegram) | High precision, provider-specific; needs a maintained list |
| High-entropy strings | 20+ char alphanumeric with Shannon entropy > 4.5 bits/char, in a context suggesting credentials | Medium precision — **the false-positive source** (hashes, UUIDs, base64 blobs) |
| 2FA / OTP codes | 6-digit codes adjacent to "code", "OTP", "verify", "2FA" | Medium precision; time-boxed (codes expire — see §3) |
| Card numbers | Luhn-valid 13–19 digit sequences | High precision |
| Seed phrases | 12/24 words from the BIP-39 wordlist | High precision, low frequency |

**Rules:**
- Matches are SECRET-classified. No "maybe" — Tier B is the recall arm; precision losses are handled by the UX (§5), not by softening detection.
- **Decode-then-scan:** base64/hex/URL-encoded content is decoded before scanning (the A1 lesson: base64 bypasses detectors — verified: base64 → zero hits on the injection detector). Up to 2 decode layers; deeper nesting is itself suspicious → SENSITIVE minimum. [HC — learn-threat-model.md §4 A1]
- Context windows: a high-entropy string *inside a code file the user asked to debug* is less suspicious than one in clipboard. Context adjusts the *class* (SECRET stays SECRET — a key is a key) but adjusts the *UX* (auto-withhold vs confirm — §5). The class never downgrades; the friction can. [MC — new design]

### Tier C — Semantic PII detection (assist-only) [MC — optional, unmeasured]

For SENSITIVE-class content that has no credential shape: names + addresses together, financial amounts in statements, health mentions, private communications.

Two options, honestly compared:

| Option | How | Cost on the 2060 | Accuracy | Verdict |
|---|---|---|---|---|
| Regex + keyword lists | Patterns for emails, phones, addresses, IBANs, diagnosis keywords | ~0 (CPU, µs) | Decent recall on structured PII; poor on prose ("my cardiologist said…") | **Adopt as baseline** |
| Small local classifier | 100M-class model (e.g., a PII-NER model) on CPU per cloud-bound payload | ~50–200ms on Ryzen 3600 [EST — unmeasured] | Better on prose; still misses inference-based sensitivity | **Watch** — adopt only if Tier B + regexes prove insufficient in practice |

**The honest position:** Tier C is where diminishing returns live. Tiers A+B catch the catastrophic cases (credentials). Tier C catches the embarrassing ones. The layer ships with A+B+regexes; the NER model is a measured decision later. **Detection is a tripwire, not the wall** — the wall is the policy (SECRET never leaves) plus local-first routing (most turns never reach cloud at all). [HC — threat-model LEARNINGS §2/§4]

### What detection does NOT cover (stated gaps) [MC]

- **Secrets split across messages** ("my password is" … "hunter2" three turns later). Partial mitigation: a per-session candidate buffer holds high-entropy unlabeled strings for N turns; a later label ("that's my password") retro-tags the buffer. Imperfect — marked as residual.
- **Steganographic / novel exfiltration by a compromised brain.** If the brain itself is adversarial (P-model beyond the threat model), no output filter suffices — it can encode secrets in prose. Out of scope by design; the mitigation is tier routing (sensitive turns stay local) + the gate, not the DCL.
- **Inference-assembled sensitivity** (ten PERSONAL facts → one identity). No per-segment classifier catches this. Partial mitigation: the SENSITIVE-confirm gate fires on *accumulation* (see §3).

---

## 3. Enforcement Points and the DCL Pipeline

### Where the DCL sits [HC — new design]

```
user request → [BRAIN: propose] → [GATE: permission/tier/schema] → [TOOLS: execute]
                                                                      ↓
                                                              [DCL: classify]
                                                                      ↓
                                              ┌─────────────┬──────────┴──────────┬──────────────┐
                                              ↓             ↓                     ↓              ↓
                                        cloud-brain    phone upstream      logging        local-only
                                        call           (Telegram out)      (already        (no DCL
                                        (classify →     (classify →          covered         friction)
                                        redact/confirm) redact)             by C2)
```

**Four enforcement points:**

1. **E1 — Cloud-brain prompt assembly (PRIMARY).** Before any Tier-2 call, the assembled prompt (system + history + tool results + memory context) is classified per segment. This is the C7 fix.
2. **E2 — Clipboard ingestion.** `clipboard_get` classifies at READ time, before content enters the LLM context. The class tag travels with the content (taint). This is the C6 fix — the earliest possible intervention.
3. **E3 — Phone-remote upstream.** Answers and notifications the PC sends via Telegram are cloud-bound (Telegram's servers). Classified before send. (Phone-remote spec §6 secrets rules + this layer.)
4. **E4 — Memory write path (tagging only, never blocking).** Content written to memory carries its class tag (extends the M4 provenance tags). The tag gates *future* cloud sends: a SECRET-tagged memory is never included in cloud-bound context. This closes the M-X4 adjacency (spoken password → memory → cloud).

### The per-segment policy [HC — new design]

Classification produces segments: `(text, class, source)`. Policy per class:

| Class | Cloud-brain call | Phone upstream | What the user sees |
|---|---|---|---|
| PUBLIC | Send | Send | Nothing (no note) |
| PERSONAL | Send | Send | Feed entry: class label only ("sent: personal data") — never content |
| SENSITIVE | **Hold for confirmation** (first occurrence per session per data item; "always allow this kind" available — §5) | Hold for confirmation | Dialog: what class, from where, to whom — never the content itself in the dialog |
| SECRET | **Withhold.** Replaced in the cloud-bound payload with a placeholder: `[withheld: <class> from <source> — <n> chars]` | Withhold, same placeholder | Feed entry: "withheld 1 secret (clipboard, 32 chars) from cloud call — tap to review" |

**The placeholder rule:** the brain is told *that* something was withheld and *what kind* — never the value. This preserves the brain's ability to reason ("the user pasted a key; I can't see it, but I can help them use it locally") without exposing the secret. [MC — new design; the brain must be prompted to handle placeholders gracefully]

**Taint propagation:** the class tag follows content through the pipeline — clipboard → tool result → brain context → memory. Tags are (class, source, timestamp). A tag never *downgrades* in transit (SECRET stays SECRET through summarization — summaries of secrets are SECRET). Tags *can* upgrade on accumulation: 3+ SENSITIVE segments about the same entity in one session → the bundle is treated as SENSITIVE-minimum for the confirm gate. [MC — new design]

**2FA special case:** OTP codes are SECRET-class but time-boxed (30–60s validity). Withholding is almost always correct — by the time a cloud round-trip completes, the code is dead anyway. The UX says so plainly: "withheld an expiring code — use it locally." [HC — new design]

### The confirm gate for SENSITIVE [HC — new design]

Not the R3 approval gate (that's for *actions*). This is a *data* gate, lighter by design:

- **First occurrence** of a SENSITIVE item per session → inline confirm card in chat: "This would send <class description> from <source> to <provider>. [Send once] [Always allow this kind] [Never send]."
- **"Always allow this kind"** creates a user pin (like the location pin in §1) — recorded, visible in Settings → Privacy, revocable.
- **"Never send"** creates a SECRET-equivalent pin for that data kind.
- The dialog shows class + source + destination. **Never the content itself** — showing the content in a confirm dialog is itself an exposure surface (shoulder surfing, screenshots). [HC]
- Voice channel: SENSITIVE confirms are text-only, never voice ("I've put a data-permission request in your chat"). Bare "yes" is never confirmation — the approval-UX spec's rule applies. [HC — learn-approval-ux-spec.md]

### Defense in depth with C2 [VC]

C2's `RedactingFilter` (fail-closed, on every logger) remains the backstop: if the DCL misses something, the log filter catches registered secrets. Two different layers, two different failure modes — the DCL is *content-aware* (classes, placeholders, confirms), the log filter is *pattern-blind* (redact on match). Neither depends on the other.

---

## 4. Failure Modes and the FP/FN Tradeoff

### The fundamental asymmetry [VC]

- **False negative (miss a secret → leak):** irrecoverable. Provider retention means the data is gone the moment it sends. Cost: catastrophic-to-severe.
- **False positive (flag benign content → withhold/confirm):** recoverable. The user taps "send anyway" or "always allow." Cost: annoyance, measured in seconds.

**Therefore: the layer is tuned for recall, and the UX is designed to make precision failures cheap.** This is the same fail-closed philosophy as the log filter (C2) and the gate (R3). [HC]

### FP cost control (making precision failures cheap) [HC — new design]

1. **One-tap release:** a withheld segment shows in the feed with [Send anyway] [Always allow this kind]. Two taps max to override.
2. **Smart defaults per source:** a high-entropy string in a *code file the user asked to debug* gets "confirm" UX rather than silent withhold; the same string in *clipboard* gets silent withhold + feed note. The class is identical (SECRET); the friction differs by source risk. (The clipboard is where passwords live; code files are where hashes live.)
3. **Learning pins:** "always allow this kind" / "never send" pins accumulate into a personal policy. The FP rate should *decay* with usage. Pins are visible, editable, revocable in Settings → Privacy.
4. **No confirm fatigue:** SENSITIVE confirms are per-item-per-session, not per-turn. The same email body discussed across 10 turns confirms once.

### FN residual (what still leaks, honestly) [MC]

1. **Split secrets** (§2): partial mitigation via the session candidate buffer.
2. **Novel credential formats** not in the Tier-B list: the list needs maintenance (quarterly review, or community-contributed patterns — never auto-updated from the network without signature verification, per R10).
3. **Paraphrased secrets** ("my password is the name of my dog plus 123"): no pattern catches this. The registry (Tier A) catches it *if* it's a system secret; otherwise it relies on the user not pasting it into a cloud turn — which is why local-first routing is the primary defense and the DCL is the secondary one.
4. **A compromised brain exfiltrating deliberately**: out of scope (see §2).

### The tuning dashboard [MC — new design]

Settings → Privacy → Data Classification shows:
- Withhold/confirm counts per class per week (is the layer firing sanely?)
- The pin list (user's allow/deny rules)
- A "test" box: paste text, see its classification — **the transparency instrument**. Users who can see the classifier's judgment can correct it; a black-box classifier breeds either blind trust or blanket disabling.

---

## 5. UX: What the User Sees and Controls

### Per-tier defaults [HC — new design]

| Setting | Default | Rationale |
|---|---|---|
| Cloud-brain data policy | Classify + enforce (this layer) | The safe default; local-only mode is stricter |
| SENSITIVE confirm | Ask per item per session | Balances safety and fatigue |
| SECRET handling | Always withhold | No safe default exists for sending credentials to a third party |
| "What left the machine" feed | On | Transparency is the trust mechanism |
| Pins | User-managed | The personal policy belongs to the user |

### The "what left the machine" feed [HC — new design]

Every cloud-bound send creates a feed entry (in the chat UI's activity feed — approval-UX spec §5):

```
→ Sent to Gemini 2:34 PM
  • your question (public)
  • 2 tool results (personal)
  • 1 memory snippet (personal)
  ⊘ withheld: 1 secret — clipboard, 32 chars (tap to review)
```

**Never the content** — class labels, sources, counts, timestamps, destinations. The feed is the audit trail for residual risk #3 (provider retention): the user can see *exactly* what each provider received, which is the precondition for informed consent. [HC]

### Overrides [HC]

- Per-send: [Send anyway] on any withheld/held item (logged as a user override — the audit trail records that *the user* chose to send it).
- Per-kind: pins ("always allow calendar titles", "never send anything from my password manager").
- Global: "local-only mode" — no cloud calls at all, the DCL becomes tag-only (still feeds the audit trail). This is the maximum-privacy posture, one toggle.

### The plain-language promise [MC — proposed copy]

Settings → Privacy shows, in Owais-readable words:

> "When JARVIS needs its cloud brain, it checks everything it's about to send first. Passwords and keys never leave your PC — ever. Personal stuff gets noted in your activity feed. Sensitive stuff asks you first. You can see everything that ever left, and take back any permission."

---

## 6. Interaction with Existing Specs

### With the gate (R2/R3) [HC]

Sequential, not overlapping:
1. **Gate first:** is this *action* allowed? (permissions, tiers, schema, approval for tier-3.)
2. **DCL second:** is this *data* allowed to leave? (classification, redaction, confirmation.)

The gate governs *doing*; the DCL governs *telling*. A tier-1 read action (allowed silently by the gate) can still trigger a SENSITIVE confirm from the DCL if the read content is cloud-bound. Neither layer can waive the other. [HC — new design]

### With the session store (stored vs sent) [HC — learn-session-store.md]

The critical distinction this layer introduces:

| | Session store (local) | Cloud-bound payload (derived) |
|---|---|---|
| Fidelity | Full — including SECRET content (it's the user's own machine, ACL-protected) | Redacted — placeholders for SECRET, confirmed SENSITIVE |
| Purpose | Crash recovery, audit, interrogation | Thinking (the cloud brain's working set) |
| Deletion | The 13-item checklist (privacy-engineering §2) | Unrecallable — provider retention (residual risk #3) |

**Replay uses the local log, not the cloud payload.** On `wake(sessionId)`, the brain replays from full-fidelity local events. The cloud never had the secrets, so a resumed cloud turn re-derives the redacted payload — deterministic, no secret needed. [MC — new design]

**The Utterance Record interaction:** TTS speaks locally — the DCL does not gate speech (that's the voice-loop spec's domain). But SECRET-class content is never *spoken aloud* either — a spoken password is overheard-password. The DCL tag is checked by the TTS path: SECRET → the speaker says "[withheld]" or the relevant non-secret paraphrase. This is new design, marked [MC] — the exact UX needs the voice-loop treatment.

### With the reliability spec's local-first rule [HC — learn-reliability-spec.md]

Local-first routing is the *primary* defense (data that never leaves can't leak); the DCL is the *secondary* defense (data that must leave is screened). They compose:

- **Local turn:** DCL tags content (for memory tags + feed), enforces nothing (nothing leaves).
- **Cloud turn:** DCL enforces fully.
- **Degraded (local-only) mode:** DCL enforces nothing — nothing *can* leave. The feed notes "local-only — nothing sent."

The degradation ladder's hard rule ("degradation changes capability, never permissions" — Cycle 12) extends: **degradation never weakens classification either.** A system under load doesn't start sending secrets to "save time." [HC — new design]

### With memory (M4 provenance) [HC — learn-memory-spec.md]

DCL class tags extend the M4 provenance tags: every memory carries `(source, trust, class)`. The quarantine gate (untrusted content never auto-acted-on) and the class gate (SECRET never cloud-sent) are orthogonal axes of the same tag. A memory can be `trust=tool, class=secret` (e.g., a password read from a password-manager export) — quarantined from action AND withheld from cloud. [HC — new design]

### With the phone-remote spec [HC — learn-phone-remote-spec.md]

Phone upstream (PC → Telegram) is cloud-bound → E3 classifies it. The R0/R1/R2 capability tiers and the DCL classes are orthogonal: a *capability-allowed* R0 answer containing *SECRET-class* content is still withheld. Capability says what the phone may *do*; classification says what may *leave*. [HC — new design]

---

## 7. The Coverage-Matrix Update — Which Cells Move

### C6: clipboard → cloud — ○ → ● [HC — this design]

| Layer | Mechanism |
|---|---|
| **New: DCL E2** | Classify at `clipboard_get` read time; tag travels with content (taint) |
| **New: DCL E1** | Strip SECRET-class segments from cloud-bound prompts; placeholder substitution |
| **Existing: Tier A registry** | System secrets (API keys, tokens) matched by fingerprint — zero-FP path |
| **Existing: Tier B patterns** | Passwords, 2FA codes, card numbers, seed phrases, labeled secrets |
| **New: UX** | "Withheld 1 secret from clipboard" feed entry + one-tap review |

**Residual:** split secrets across turns (partial: session candidate buffer), novel formats (list maintenance), paraphrased secrets (out of scope — see §2). Downgrade from UNCOVERED to **covered-with-stated-residuals**.

### C7: full history → cloud — ○ → ● [HC — this design]

| Layer | Mechanism |
|---|---|
| **New: DCL E1** | Per-segment classification of the assembled cloud prompt; SECRET redacted, SENSITIVE confirmed, PERSONAL feed-logged |
| **New: DCL E4** | Memory class tags gate future cloud context assembly |
| **Existing: local-first routing** | Brain-spec tier routing — most turns never reach cloud (primary defense; DCL is secondary) |
| **New: feed** | "What left the machine" audit trail per cloud call |

**Residual:** provider-side retention (accepted risk #3 — unchanged, now *informed* by the feed); deliberately-exfiltrating brain (out of scope). Downgrade from UNCOVERED to **covered-with-stated-residuals**.

### Threat-model §6 residual risk #6 — updated

| Before | After |
|---|---|
| "Accepted *temporarily*: classification-before-send is a defined build task. Interim: local-first default keeps most traffic on-device; user is told what the cloud tier implies." | "Accepted *as designed*: the DCL is specified (Cycle 27). Interim until implementation: local-first default + the explicit user notice. The acceptance moves from 'we'll design it later' to 'designed, awaiting build' — implementation is a build task under the v2 go-ahead." |

### Proposed test additions (hardened_runner style) [MC — new design]

The 13-attack suite gains a data-exfiltration family:
- `test_attack_secret_in_cloud_prompt_redacted` — SECRET segment in history → placeholder in cloud payload, value absent.
- `test_attack_clipboard_secret_withheld` — password in clipboard → withheld from cloud call, feed entry created.
- `test_attack_encoded_secret_decoded_and_caught` — base64'd key → decoded, matched, withheld.
- `test_attack_sensitive_history_triggers_confirm` — bank balance in history → confirm gate fires, no silent send.
- `test_attack_registered_secret_fingerprint_match` — keyring secret in tool output → SECRET by registry, zero false-positive path exercised.
- `test_attack_taint_survives_summarization` — SECRET survives a summarize step without downgrade.

---

## 8. Open Questions (Ranked)

1. **Tier C (NER model) adoption** [UK] — is regex + patterns enough in practice? Resolution: ship A+B+regexes, measure the SENSITIVE-miss rate on real usage (via the feed + user corrections), adopt the NER model only if misses are material.
2. **The 2FA UX** [MC] — withholding expiring codes is usually correct, but is there a case where the user *wants* the cloud brain to see the code? (Answer: almost never — the code is dead by round-trip. Keep the withhold, note it.)
3. **SECRET-via-voice** [UK] — the TTS check (§6) needs the voice-loop treatment: exact phrasing, the "[withheld]" UX, interaction with the Utterance Record.
4. **Accumulation sensitivity** [MC] — the 3+-SENSITIVE-segments escalation rule needs tuning on real data; the threshold is a guess.
5. **Pattern-list maintenance** [MC] — who updates the Tier-B provider list, how often, and via what signed channel (R10 applies — never auto-update from the network unsigned).
6. **The candidate buffer's privacy** [MC] — the per-session high-entropy buffer is itself a secret store; it must be memory-only, never persisted, cleared on session end. (Otherwise the mitigation *becomes* the vulnerability.)
7. **Multi-profile** [UK] — per-profile DCL pins and registries (isolation rule from privacy-engineering §1). Deferred until profiles exist.

---

## 9. Confidence Summary

- **[VC]** The C6/C7 gap statements (read from threat model); the v1 corpses (read from autopsy); the registry mechanism (extends C2's proven `register_secret()`); the FP/FN asymmetry; provider retention as irrecoverable.
- **[HC]** The 4-class taxonomy; the DCL pipeline position (gate → DCL → network); per-segment policy; taint propagation rules; the feed design; composition with gate/session-store/reliability/memory/phone specs; the ○→● verdicts with stated residuals.
- **[MC]** Tier B precision in practice; decode-then-scan depth; the accumulation rule; placeholder-brain interaction; test list completeness; pattern-list maintenance cadence.
- **[SP]** Tier C cost/accuracy figures (unmeasured on the 2060); FP decay rate from pins.
- **[UK]** The 7 open questions above.

---

## 10. Honest Completion (Rule 12)

- **Researched:** learn-threat-model.md (C6/C7, residual #6, coverage matrix — read in full), learn-privacy-engineering.md (lifecycle, deletion, consent — read in full), learn-brain-spec.md (three-tier routing, gate boundary — read in full). Cross-referenced: learn-memory-spec.md (M4 tags), learn-session-store.md (stored-vs-sent), learn-reliability-spec.md (local-first, degradation rule), learn-phone-remote-spec.md (E3 upstream), learn-approval-ux-spec.md (confirm UX, feed).
- **Validated:** finding IDs (C6, C7, M-X4/5/6, residual #6) cross-checked against the threat model and autopsy; no ID corrections needed.
- **Saved:** 1 file (`learn-data-classification.md`).
- **Modified:** none (MASTER-INDEX update is a separate step — see report).
- **Tested / Measured:** nothing — design document, unimplemented by intent.
- **Incomplete:** none — the design question is answered.
- **Blocked:** implementation awaits Owais's v2 go-ahead; Tier C figures await the 2060.

*Traceability: every mechanism is tagged [VC]/[HC]/[MC]/[SP]/[UK] and traced to its source study or marked "new design." The two uncovered cells move to covered-with-stated-residuals; the residuals are named, not hidden.*
