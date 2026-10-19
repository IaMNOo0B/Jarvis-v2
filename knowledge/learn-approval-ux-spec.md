# Approval-Gate UX & Autonomy Calibration — Design Specification

*PHASE INFINITY, Research Cycle 20. LEARNING ONLY — no project files, no installs, no code executed.*
*Date: 2026-10-19. Status: design complete, unvalidated on a real build or real user.*

---

## 0. The thesis (why this document exists)

The threat model (Cycle 10) concluded: **the remaining holes are all on the human side of the gate** — what Owais *sees* in the dialog, whether he *reads* it, what he *approves* under fatigue. The cheapest attack path is deceiving the user, not defeating the code.

The research is blunter than that. Three findings define the design space:

1. **Automation bias survives the gate.** LoopRails research on AI coding agents found plan-approval cut successful attacks from ~90% to 60–74% — but when a problem actually surfaced in front of a person, intervention success stayed at **9–26%**. The human approved it anyway, roughly three times out of four. The bottleneck is not noticing; it is *recognizing what you noticed as a problem*. The right question per action is not "is there a human in the loop?" but **"can this human catch this mistake in this window?"** If the answer is no, prevent the bad outcome rather than gate it behind a click. [dev.to, "Automation Bias: Why People Rubber-Stamp AI (and How to Fix It)"]
2. **Watch duty and verdict duty both fail.** Nielsen's UX roundup (Oct 2026): vigilance on mostly-empty event streams falls off within 30 minutes; each routine approval makes the next click more automatic, until the request that mattered gets rubber-stamped along with the rest. "Asking users to watch AI carefully is doomed to failure." [jakobnielsenphd.substack.com]
3. **Approval volume is the accelerant.** AWS's Well-Architected Agentic AI Lens: "routing every agent action through human review produces rubber-stamp approvals." The drift sequence is predictable: adoption → output volume → verification rigor falls → false confidence rises → review becomes performative → liability. At every point the audit log shows a human approval with a name and a timestamp. Complete. Oversight gone. [paice.work]

**Design consequence:** the gate's job is not to maximize human oversight — it is to **concentrate human attention where it can actually work**, and to architecturally prevent everything else. This spec does both.

**Cut sets this spec serves** (from learn-fault-trees.md, Cycle 4): B7 (UI spoofing), B10 (rubber-stamping), B11 (approval fatigue), plus threat-model attacks F1 (payload laundering, P0), F3 (manufactured fatigue). **Threat-model uncovered cells closed or concretely specified here:** F3, B10, B11 (behavioral) — each gets a spec clause below. F1 gets its mechanism. F2 (log-as-oracle) and F4 (nonce integrity) are code-layer and covered by rule, not UX — stated in §8.

---

## 1. The approval dialog

### 1.1 What it shows — the seven required fields

Every tier-3 approval dialog shows exactly these, in this order. No exceptions, no "compact mode" that drops fields (a real-world failure: dugganusa.com's team cut their consent dialog to counts-per-tier to fit on screen, and that let a rules-file change hide inside "Laws: 13" — the dialog now names every file again).

1. **The goal** — "I'm trying to [what you asked for]." One line, your words echoed back. *(Why: anchors the decision in YOUR intent, not the agent's framing — fights the LoopRails rationalization effect where users normalize the agent's framing.)* [LoopRails, dev.to]
2. **What's done so far** — "Done: [1], [2]." Where this action sits in the sequence. [learn-frontend §3: contextual handoff]
3. **The exact action in plain words** — "Delete these 3 files: `a.txt`, `b.txt`, `c.txt`" — never "execute filesystem mutation." Reading level ≤ lower-secondary. [learn-frontend §3, learn-accessibility §4]
4. **The blast radius** — what breaks if this is wrong. "These files cannot be recovered. 2 of them were modified in the last 7 days." The dialog computes blast radius from the action object (file age, size, backup status, external visibility), not from the brain's description. *(F1 clause: the renderer takes the action object, never the brain's text.)*
5. **The consequence line** — one sentence, worst case, plainly: "If this is a mistake, you will lose the contents of 3 files permanently."
6. **What happens if you say no** — "I'll keep the plan parked and you can review each file yourself." Reject must never equal broken functionality; the safe subset is always offered. [learn-frontend §3 rule 6]
7. **Origin proof** — a visual element that cannot be faked by web content (see §4). If it's not there, the dialog is not from JARVIS.

### 1.2 What it NEVER does

- **Never auto-expires.** No countdown, no "auto-approve in 10s." (WCAG 2.2.1 Timing Adjustable; learn-accessibility §1.) An auto-approving gate is a bypass with extra steps.
- **Never pre-checks Approve.** No default-on.
- **Never buries the dangerous part.** The dangerous parameter is first, bold, and complete. Counts-per-tier ("Files: 3") are banned as a summary format for tier-3 — the dialog names names.
- **Never takes tiers from the agent's text.** The dialog's own tier assignment is recomputed from the action surface definition in deterministic code. (This is the dugganusa.com lesson, generalized: their dialog took each file's tier from the proposal file *the agent writes* — a proposal could label a rules file as a skill and fold it into a count. The fix: tiers recomputed from the surface definition, files outside the surface refused. Same invariant here: the agent proposes the action; the *code* computes what kind of action it is.) [dugganusa.com; threat-model F1]
- **Never renders control characters from filenames.** Newlines, tabs, RTL-override characters in filenames/params are refused or collapsed before rendering. (Same source: a filename with a line break drew fake dialog lines.) Filenames that fail sanitization abort the dialog with "I can't display this safely — rejecting."
- **Never asks for passwords, keys, or secrets.** A legitimate dialog can never request a credential. Credentials go through the OS keyring UI, never a JARVIS dialog. (If a dialog asks for your password, it is definitionally spoofed — this is the user's one unbreakable rule to learn.) [§4]

### 1.3 The decision controls

Three buttons, **equal visual weight** (no big bright Allow + grey hidden Deny — dark patterns manufacture compliance and destroy trust [learn-frontend §3]):

- **Approve** — executes this action. Disabled until the payload has been *visible on screen* for a minimum dwell (see §3.3).
- **Edit** — opens the parameters for modification (change files, change target, change scope), then re-renders the dialog. Approval is per-action-object: editing creates a new action hash, which voids the old token (fault-tree B3 mitigation).
- **Reject** — cancels, offers the safe subset (§1.1 field 6).

Keyboard: Tab order Approve → Edit → Reject; Enter on focused button; Esc = Reject. Minimum 24×24 CSS px targets, 4.5:1 text contrast (WCAG 2.5.8, 1.4.3 — learn-accessibility §1). Announced on completion via `role="status"`, never per-token.

**Consequential-action evidence bar** [iprs.cloud]: for high-risk actions the reviewer sees the source records, proposed change, destination, affected party, and reason — the dialog's evidence, not just its claim. If the evidence can't be shown, the action is too broad to approve and gets narrowed or refused (LoopRails: "can this human catch this mistake in this window?").

---

## 2. Sliding-scale autonomy — the three tiers as UX

The 2026 Google-led 65-researcher finding: notice-and-choice "is unlikely to be effective for AI agents" — users can't foresee execution paths, consent covers inputs but not inferences, binary Allow/Deny can't carry conditions, and every-sub-task asking produces fatigue while asking less produces over-broad authority. The proposed replacement: **sliding scale** (low-stakes auto-proceed, financial explicit-confirm, third-party-risk blocked), per-request interfaces, learned policies, circuit breakers. [learn-frontend §3]

### 2.1 The tiers, as the user experiences them

| Tier | Definition | UX | Example |
|---|---|---|---|
| **T1 — Observe** | Reads only. No state change anywhere. | Happens silently. Lands in the activity feed (§5) as a grey line. No interruption. | Reading a file, searching the web, checking calendar |
| **T2 — Reversible** | Writes that can be undone within the undo window. | **Announce + act + 30s undo.** A calm line in chat: "Moved 4 files to archive. [Undo]". No modal. The undo token is real (snapshot before mutation), not decorative. | Organizing files, drafting a message, changing a setting |
| **T3 — Irreversible** | Cannot be undone, or high-impact (external, financial, destructive, security-relevant). | **Full dialog (§1).** Modal, trusted chrome, origin proof, dwell time. Nothing executes before approval. | Deleting files, sending messages, running code, installing anything, granting permissions |

**The tier is computed by code, from the action object, every time** — never inherited from the brain's label, never from the dialog's previous render (§1.2). Tier boundaries are the surface definition (the deterministic classifier), versioned and reviewable.

### 2.2 User-adjustable comfort — but only downward

Owais gets a settings surface: **"My autonomy level"**, per tier-pair:

- T2→T1 behavior: "Auto-approve reversible actions" (default ON) / "Ask me for reversible actions too" (more gates — his choice, with the fatigue warning shown: "More gates = each gate gets less attention. This is measured, not a guess.")
- T3 stays T3. **There is no setting that auto-approves irreversible actions.** Not a toggle, not a "power user mode," not a config flag. The tier-3 gate is load-bearing for the entire security model; making it optional would re-open cut set {B10} by policy. The spec is explicit about this because someone will ask.

**Ongoing revocation** [learn-frontend §3]: the settings surface shows every standing grant ("JARVIS may auto-approve: file organization, web searches, calendar reads") with one-tap revoke. Consent is a relationship, not a click.

### 2.3 Learned policies — with the receipts

"Policies learned from past decisions" (the 65-researcher proposal) is implemented as: after N consistent approvals of the *same action class with the same parameters pattern*, JARVIS may propose "You always approve X — want me to auto-approve it within these bounds?" The bounds are stated (which files, what size, what recipients). **The user says yes explicitly; the proposal is never auto-accepted.** And it only ever moves T3→T2-equivalent behavior (announce + undo), never T3→silent. The learned policy appears in the revocation surface (§2.2) like any other grant.

---

## 3. Fighting rubber-stamping — the anti-fatigue design

This is the section that closes threat-model cells **B10** (rubber-stamping) and **F3** (manufactured fatigue), and addresses B11 (approval fatigue). The research consensus: you cannot train the user to be vigilant. You can only design the system so vigilance is rarely needed and fatigue is structurally bounded.

### 3.1 Fewer gates, higher stakes (the volume rule)

**Approval volume is the accelerant** [AWS via paice.work]. The design rule: the number of tier-3 dialogs per day is a *budgeted resource*, not a free action.

- Target: **fewer than 5 tier-3 dialogs per day** in normal use [PROPOSED — needs measurement of Owais's actual threshold; learn-frontend §3 unknown #3].
- Mechanism: batching (one dialog for a coherent set of tier-3 actions in a plan — each individually listed, §6), learned policies (§2.3) absorbing the routine, and the T2 undo-buffer absorbing the reversible.
- **Anomaly flag:** any day exceeding 2× the user's 30-day median dialog count triggers a step-up: dialogs get the friction treatment (§3.3) and the activity feed shows "Unusual approval volume today — 14 dialogs vs your usual 4." Unusual-for-user actions (new recipient, large amount, first-time tool) are always flagged regardless of volume [learn-frontend §3; complyarmor].

### 3.2 Never the same "yes" (anti-muscle-memory)

**F3 clause (manufactured fatigue):** an attacker (or a misconfigured routine) that bursts low-stakes prompts to train auto-approve, then slips in a tier-3, is defeated by making the tier-3 gesture *structurally different* from the tier-2 gesture:

- T2 uses the inline Undo chip (one tap, no modal).
- T3 uses the modal dialog — and for actions above a severity line (deletion, external send, code execution, permission grants), the Approve button requires a **typed confirmation**: the user types the *action keyword* shown in the dialog ("type DELETE to confirm"). Typed confirmation is immune to click-muscle-memory; it forces the recognition step that LoopRails found missing (the bottleneck is recognizing what you noticed as a problem — typing the word makes the recognition unavoidable). [LoopRails, dev.to]
- The severity line is computed from blast radius (§1.1 field 4), not from tier alone. Routine tier-3 (approving a known-safe learned pattern) keeps the button; novel or high-blast-radius tier-3 gets typed confirmation.
- **Vary the dialog's friction with novelty, not randomly.** Same action approved 50 times → the dialog may compact (still shows payload, still requires the tap). Action never seen before → full friction. Random friction trains users to fight the UI; novelty-scaled friction trains attention to novelty.

### 3.3 Dwell and deliberation (no click-through)

- The Approve button is **disabled until the payload has been visible for a minimum dwell** — 3 seconds for standard tier-3, 5 for typed-confirmation tier [PROPOSED]. The countdown is honest ("reading time"), not a dark pattern: it exists because the measured failure is approval in under 1 second.
- The payload is visible *before* the buttons enable. A dialog that shows buttons first and payload on scroll is theater.
- Scroll-to-payload is not enough: for payloads longer than the dialog, the dangerous lines are *always* above the fold.

### 3.4 Fatigue detection → step-up friction

The system watches approval *behavior*, not just count:

- **Signals:** median time-to-approve trending down over a session; approve-without-scroll rate; approvals in bursts (<10s apart); time-of-day (late-night approvals get more friction — judgment degrades).
- **Response (the step-up ladder):** normal → +dwell time → typed confirmation on all tier-3 → "Take a breath" interstitial ("You've approved 8 actions in 3 minutes. Want to review them in the feed first?") → for extreme patterns, **refuse to present further tier-3 dialogs this session** and say so plainly. The gate degrades to *safer*, never to more permissive.
- This is the concrete mechanism for **F3**: manufactured burst prompts trip the burst detector (approvals <10s apart, or dialog presentation rate >N/min [threshold PROPOSED: 3/min]) before the slipped tier-3 arrives — the tier-3 then lands in stepped-up friction with a burst warning banner.

### 3.5 The weekly autonomy review

Every week, one calm card in chat:

> **Your week with JARVIS** — 212 actions. 204 silent (reads). 6 auto-approved with undo (all within your bounds). 2 needed your approval: *deleted 3 files Tuesday*, *sent the email Thursday*. Still comfortable with these standing grants? [Review] [Keep as-is]

- The review is the **revocation surface made routine** [learn-frontend §3]. It converts standing authority from "forgotten" to "re-affirmed."
- It also reports the fatigue metrics honestly: "Your median approval time dropped from 11s to 4s this month." No judgment, just the mirror.
- **B11 clause:** the review plus the volume budget (§3.1) plus learned policies (§2.3) is the fatigue strategy: fewer gates, each one more meaningful, standing authority periodically re-consented.

### 3.6 What we do NOT do (anti-patterns, researched)

- **No "Are you sure?" on top of "Are you sure?"** — stacked confirmations train dismissal, not care. One gate, done right, beats three gates done routinely.
- **No approval of plans-as-blank-checks** — see §6.
- **No gamification of approvals** — streaks, scores, or "careful reviewer" badges would optimize the metric, not the judgment.
- **No shaming** — "You approved without reading!" creates adversarial UX. The system adapts friction silently; the weekly review shows the mirror without lecture.

---

## 4. Anti-spoofing — trusted chrome and origin proof

**B7 clause.** Chromium's security guidance for browser UI: when introducing a new form of browser UI, ensure attacker content can't occlude it, partially or fully — "there are no longer any trustworthy pixels on the screen" if the attacker can cover the trust indicator. [chromium.googlesource.com]

### 4.1 Trusted chrome

- Tier-3 dialogs render in **Tauri's native window chrome / a dedicated always-on-top native dialog**, never inside the WebView2 content area. Web content (including anything the agent fetched) cannot draw over it, cannot read it, cannot clickjack it (Chromium clickjacking analysis: browser UI surfaces are clickjackable unless systematically protected — so the dialog is native, outside the content's reach). [learn-frontend §4; chromium docs]
- The dialog has a **persistent visual identity**: a fixed accent (the arc-reactor blue, exact hex), a fixed position (centered, not wherever the agent suggests), and the JARVIS wordmark rendered by the native layer. Users learn: *blue-centered-native = really JARVIS*. Anything else asking for approval-shaped clicks is fake.
- **The confirmation surface must be outside the content the agent or extension can edit.** [cyber-security-in-plain-english] The agent can request an approval; it can never render one, style one, reposition one, or dismiss one.

### 4.2 Origin proof

- Each dialog shows a **session-bound visual secret**: a short phrase + icon chosen at session start, shown in the native dialog chrome ("Today's phrase: *copper falcon* 🦅"). A spoofed dialog can't know it. (Lightweight, user-comprehensible — the heavy version is attestation; the phrase is the human-checkable layer.)
- The dialog states its provenance line: "Requested by JARVIS core · action #4821 · 14:32:07." Timestamps and sequence numbers make replay visible (B8: replayed approvals are rejected by single-use nonces regardless, but the user-visible sequence number lets a human notice "why is #4821 showing again?").

### 4.3 The credential rule (user-facing)

One rule, taught once in onboarding, repeated in the help surface: **"JARVIS will never ask for a password or key in a dialog. If a dialog asks, it's fake — close it and tell me."** Credentials only go through the OS keyring UI. This is the user's unbreakable heuristic — simple enough to survive fatigue. [§1.2]

---

## 5. The "what happened" feed

**No silent actions, ever.** Every action — T1, T2, T3, approved or auto — lands in a visible, persistent activity feed:

- **T1 (reads):** grey one-liners, collapsible. "Read `notes.md` · 14:31"
- **T2 (reversible):** the announce line with a live **Undo** chip for 30s, then a permanent "Undone"/"Kept" state. The undo is a real snapshot restore (R6 atomic writes), and the feed shows it worked: "Undone — 4 files restored."
- **T3 (approved):** the full payload summary with the approval record: who/when/how (button vs typed confirmation), the action hash, and a link to the event-log entry (R15 session store).
- **Denied/rejected:** shown too, with what JARVIS did instead (the safe subset). Rejections are first-class citizens — a feed that only shows approvals teaches the user approvals are the norm.

The feed is the **audit trail the user can actually read** — the AWS drift-sequence warning ("the log shows a human approval with a name and a timestamp. Complete. Oversight gone.") is answered by making the log *legible*: grouped by task, plain language, blast radius visible, undo where possible. An audit trail nobody reads is a write-only alibi.

**Circuit breaker visibility:** the STOP control (learn-frontend §1: the stop path must always be wired) is persistent in the feed header: "Stop all JARVIS activity." The 65-researcher proposal demands circuit breakers that *guarantee* STOP halts every spawned sub-agent — the feed's stop button is that guarantee's handle, and it reports what it stopped: "Stopped 3 running tasks."

---

## 6. Plan mode — the contract, not the blank check

For multi-step tasks, JARVIS states the plan first and the user says yes once. **The plan approval is a contract with itemized terms, not a blank check** [LoopRails: plan-approval cut attacks 90%→60–74% — it helps at the action level but the human still rubber-stamps 3/4 of problems; so plan mode narrows scope, it doesn't replace per-action gates]:

1. **The plan card** lists each step: action, target, tier. "1. Read `invoices/` (observe) 2. Draft summary (reversible) 3. **Send to accountant (irreversible — you'll approve this separately)**."
2. **Plan approval authorizes the T1/T2 steps only.** Every T3 step in the plan still gets its own §1 dialog at execution time, with the live payload. The plan card says this explicitly: "Steps marked irreversible will ask you individually when I get there."
3. **Deviation voids the contract.** If execution diverges from the approved plan (new tool, new target, new tier), the plan approval is void for the divergent step — it gates individually, and the feed notes "Step 4 differed from the plan — asked separately."
4. **The plan is interruptible.** The feed shows plan progress as a checklist; any step can be individually stopped or skipped. Stopping the plan stops all its pending steps (circuit breaker, §5).

---

## 7. Voice approvals

**The problem:** voice is the primary modality, but voice approvals carry extra risks — replay (recorded "yes"), spoofing (someone else says "yes"), mishearing ("yes" vs ambient), and the absence of a visible payload (the user can't *read* what they're approving).

### 7.1 The protocol

- **T3 over voice requires the "say it back" protocol:** JARVIS states the action and its blast radius aloud, then asks the user to repeat the *action keyword* back: "To delete the 3 files, say DELETE." A bare "yes" is **not** an approval over voice — it doesn't survive the recognition-bottleneck finding (LoopRails: the user must demonstrate recognition, not just vocalization).
- **The payload is always on screen too.** Voice approval is voice *plus* the visible dialog (§1), never voice alone. The screen shows the seven fields; the voice carries the summary. If there's no screen (phone call scenario), tier-3 voice approval is **refused** — "I need you to see this one. It's in your chat."
- **Speaker verification is a tripwire, not the wall.** If voice biometrics are available, a mismatch *escalates* (requires the typed confirmation on screen); a match does not *reduce* friction. (Borrowed-phone threat, C-X6/E1: the voice saying "yes" might not be Owais.)

### 7.2 When voice approval is refused (text required)

- Blast radius above the severity line (§3.2) with no screen available.
- Any approval requested within 60 seconds of a voice-channel anomaly (unrecognized speaker, background voices, low confidence transcription).
- Financial or credential-adjacent actions — always text, always the full dialog. No exceptions.
- The refusal is graceful and specific: "This one's too big for a voice yes — I've put the full details in your chat. Tap through when you've read it." (No dead ends; the action waits, it doesn't die. WCAG: no time pressure, §1.2.)

### 7.3 Voice-specific anti-fatigue

- Voice approvals count toward the daily dialog budget (§3.1) at 2× weight — voice decisions are faster and less deliberative, so they cost more budget.
- The weekly review (§3.5) breaks out voice approvals separately: "3 approvals were by voice. All had the screen dialog too." If any didn't, that's a bug report, not a statistic.

---

## 8. Traceability matrix — every clause to its source

| Spec clause | Source | Threat-model / cut-set cell |
|---|---|---|
| §1.1 seven fields, payload-not-summary | learn-frontend §3; Study 49 | F1 (visible payload defeats laundering) |
| §1.1 consequence line + "if you say no" | learn-frontend §3 rules 1, 6 | — (consent quality) |
| §1.2 never auto-expire | learn-accessibility §1 (WCAG 2.2.1) | — (anti-bypass-by-design) |
| §1.2 tiers recomputed from surface, not agent text | dugganusa.com (Loopjacking fix) | **F1 P0** — deterministic payload renderer |
| §1.2 control-character refusal | dugganusa.com | F1 (representation attacks) |
| §1.2 never asks for credentials | R9 (keyring-only) | — (spoof heuristic) |
| §1.3 equal-weight buttons, Edit voids token | learn-frontend §3; fault-tree B3 | B3 (TOCTOU), dark-pattern defense |
| §1.3 evidence bar for high-risk | iprs.cloud | LoopRails recognition bottleneck |
| §2 sliding-scale tiers | 65-researcher consent study via learn-frontend §3 | B11 (fewer gates = less fatigue) |
| §2.2 no auto-approve-irreversible setting | Fault-tree: B10 as policy | B10 (structural) |
| §2.2 revocation surface | learn-frontend §3 rule 7 | — (consent as relationship) |
| §2.3 learned policies, T3→T2 only, explicit opt-in | 65-researcher proposal | B11 |
| §3.1 volume budget <5/day, anomaly flag | AWS Well-Architected via paice.work | **B11**, **F3** (burst detection) |
| §3.2 typed confirmation for high blast radius | LoopRails (dev.to) — recognition bottleneck | **B10** |
| §3.2 T3 gesture ≠ T2 gesture | — (novel synthesis) | **F3** (muscle-memory immunity) |
| §3.3 dwell time, payload before buttons | Nielsen verdict-duty; LoopRails 9–26% | **B10** |
| §3.4 step-up ladder, burst detector | paice.work (approval volume accelerant); Nielsen | **F3**, **B11** |
| §3.5 weekly autonomy review | learn-frontend §3 (ongoing revocation) | **B11**, B10 (mirror) |
| §4.1 native trusted chrome, agent can't render/dismiss | Chromium browser-UI security docs; cyber-security-in-plain-english | **B7** (UI spoofing) |
| §4.2 session visual secret + sequence numbers | — (novel synthesis from B7/B8 mitigations) | B7, B8 |
| §4.3 credential rule | R9 | B7 (user-side detection) |
| §5 activity feed, undo, STOP guarantee | learn-frontend §1; 65-researcher circuit breakers; R6 | — (legible audit trail) |
| §6 plan as itemized contract, deviation voids | LoopRails plan-approval findings | B10 (plan ≠ blank check) |
| §7.1 say-it-back, bare "yes" rejected | LoopRails recognition bottleneck | B10 (voice) |
| §7.1 payload on screen, no screen → refuse | learn-accessibility §3 (no audio-only) | B7 (voice), A6 |
| §7.2 text-required conditions | — (novel synthesis) | B10/B11 (voice) |
| §7.3 voice approvals 2× budget weight | Nielsen (verdict duty degrades faster by voice) | B11 |

**Code-layer companions (not UX, stated for completeness):** F2 (log-as-oracle) → gate never consults the log as proof of approval (live single-use nonce only; threat-model §4). F4 (nonce integrity) → used-nonce set lives in the gate's process-private memory (threat-model §4). Both enforced in code review, not in pixels.

---

## 9. Open questions [UK] / proposed-not-measured [PROPOSED]

1. **The 5-dialogs/day budget** — [PROPOSED]. Owais's actual rubber-stamping threshold is unknown (learn-frontend §3 unknown #3). The budget must be calibrated against his first month of real usage: median time-to-approve, approve-without-scroll rate. Until then, 5 is a principled guess, labeled as such.
2. **Dwell times (3s / 5s)** — [PROPOSED]. Needs A/B against the fatigue metrics, not against "feels right."
3. **Burst thresholds (3 dialogs/min, <10s approvals)** — [PROPOSED]. The F3 detector's parameters need tuning against real burst data (including legitimate bursts, e.g., batch file operations).
4. **Typed-confirmation severity line** — [PROPOSED]. Where exactly blast radius crosses from button to typed confirmation needs the severity function defined (file count × recoverability × external visibility) and then validated.
5. **Session visual secret** — [MC]. Usability untested: does Owais actually check the phrase, or does it become wallpaper? The Nielsen verdict-duty finding suggests any static indicator decays. Mitigation: rotate the *position* of the origin-proof element occasionally, and measure.
6. **Tauri trusted-chrome reality** — [UK] (threat-model unknowns). Whether the native dialog actually defeats overlay attacks on Windows needs the frontend spike (learn-frontend §4 unknown).
7. **Voice "say it back" in Hinglish** — [UK]. The keyword protocol needs testing against code-switched speech and faster-whisper's transcription of short keywords. Falls back to screen-tap if transcription confidence is low.
8. **The LoopRails numbers' transfer** — [MC]. 9–26% intervention success was measured on coding-agent plan review, not on a personal assistant's tier-3 dialogs with visible payloads and typed confirmation. Our mitigations target exactly the recognition bottleneck they identified, but the transfer is unmeasured.

---

## 10. The one-paragraph version

Don't maximize human oversight — **concentrate it**. Three tiers: reads happen silently, reversible writes announce with 30s undo, irreversible actions get a full native dialog with the exact payload, the blast radius, and origin proof — never auto-expiring, never pre-approved, tiers recomputed from the action itself so the agent can't launder its own description through the dialog (that's the P0). Fight fatigue structurally, not morally: budget the dialogs (<5/day), make the tier-3 gesture physically different from routine taps (typed confirmation for the big ones), step up friction when behavior shows fatigue, and run a weekly review where standing grants get re-affirmed or revoked. Over voice, a bare "yes" is never approval — say the keyword back, see the dialog on screen, or it waits for text. And one rule Owais learns once: JARVIS never asks for a password in a dialog; if one does, it's fake.

---

## Confidence & unknowns (file-level)

- [VC] on the source findings quoted (LoopRails 90%→60–74%, 9–26%; Nielsen watch/verdict duty; AWS "approval volume is the accelerant"; WCAG 2.2.1; the dugganusa.com dialog failures — all read from live sources today).
- [HC] on the spec's structural claims (tier recomputation defeats F1; typed confirmation defeats muscle-memory; the step-up ladder addresses F3) — mechanism sound, untested on users.
- [MC] on all numeric thresholds (§9) — principled proposals, explicitly unmeasured.
- [UK] on Tauri trusted-chrome efficacy, Hinglish voice keywords, Owais's personal fatigue curve.

## References

- `~/workspace/jarvis-knowledge/learn-threat-model.md` — Cycle 10 (F1 P0, F3, uncovered cells, residual risks)
- `~/workspace/jarvis-knowledge/learn-fault-trees.md` — Cycle 4 (B7, B10, B11 cut sets)
- `~/workspace/jarvis-knowledge/learn-frontend.md` — §3 approval UX (65-researcher consent study, 7 design rules), §4 Tauri, §6 signing
- `~/workspace/jarvis-knowledge/learn-accessibility.md` — WCAG 2.2.1 no-timeout, 24px targets, no audio-only, plain language
- `~/workspace/jarvis-knowledge/DECISION-PLAYBOOK.md` — S1–S8
- https://dev.to/brennhill/automation-bias-why-people-rubber-stamp-ai-and-how-to-fix-it-2587 — LoopRails automation bias (90%→60–74%, 9–26% intervention)
- https://jakobnielsenphd.substack.com/p/ux-roundup-20261002 — Nielsen Oct 2026 roundup (watch duty / verdict duty)
- https://paice.work/blog/agentic-ai-approval-fatigue-rubber-stamp-governance — AWS Well-Architected Agentic AI Lens ("approval volume is the accelerant", drift sequence)
- https://medium.com/@omanyuk/too-many-ai-approval-requests-the-human-in-the-loop-bottleneck-699970ce8ca3 — "Habituation at the Gate" preprint (11,429 reviews)
- https://www.dugganusa.com/post/six-ai-agent-approval-gates-broke-in-public-this-quarter-we-turned-each-one-into-a-membrane-upgrade — real dialog failures (counts hide files, tiers from agent text, control chars)
- https://chromium.googlesource.com/chromium/src/+/161e6d2bd5e5ffa5955f85b20670b3f63058ceff/docs/security/security-considerations-for-browser-ui.md — trusted pixels, clickjacking of browser UI
- https://cyber-security-in-plain-english.com/post/developers/news/browser-extension-becomes-agent-command-channel/ — confirmation surface outside agent-editable content
- https://iprs.cloud/knowledge/how_should_businesses_control_ai_agent_permissions_without_slowing_down_teams_in_2026.php — consequential-action evidence bar
- https://www.complyarmor.com/blog-ai-agent-least-privilege.html — "verify approval gates actually gate"; least-privilege model

## Completion report (Rule 12)

- **Researched:** threat-model uncovered cells (F1/F3/B10/B11), frontend consent science, accessibility constraints, fault-tree cut sets — 4 local files read in full + 2 live web searches (12 sources scanned, 9 cited).
- **Validated:** LoopRails numbers, Nielsen findings, AWS guidance, WCAG criteria, and the dugganusa.com failure cases cross-checked across the cited pages; arXiv IDs not needed (no papers cited directly — the "Habituation at the Gate" preprint is cited via the Medium analysis, flagged as such).
- **Saved:** `~/workspace/jarvis-knowledge/learn-approval-ux-spec.md`.
- **Modified / tested / measured:** none (learning only, per task).
- **Incomplete:** none — all 7 spec sections written.
- **Blocked:** validation needs the Tauri build (trusted chrome), Owais's usage data (thresholds), and Hinglish voice testing (keywords) — recorded in §9, not assumed.
