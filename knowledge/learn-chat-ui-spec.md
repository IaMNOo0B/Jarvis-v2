# v2 Chat UI — Design Specification

*PHASE INFINITY, Research Cycle 25. LEARNING ONLY — no project files, no installs, no code executed.*
*Date: 2026-10-19. Status: design complete, unvalidated on a real build or real user.*

---

## 0. The thesis — what this window is

The chat window is the **primary surface** of JARVIS v2 (chatbot-first, R1). It is the one thing Owais will look at every day. It must:

1. **Never leave him guessing.** Every brain state has a visible signal. No dead air, ever. (The trust repair for v1's long silent stretches.)
2. **Never lie.** Streaming shows what's actually there; states show what's actually happening; errors say what actually broke.
3. **Never trap him.** Every action is visible, undoable where possible, stoppable always.
4. **Degrade to text, never to nothing.** Voice, approval dialogs, notifications — every modality bottoms out at readable text. (learn-accessibility §3; R1)

The window is built in **Tauri 2.x** (learn-frontend §4 verdict: 30–70MB idle vs Electron's 150–400MB — headroom for the actual brain on a 16GB machine; deny-by-default capabilities). The Python brain runs as a **sidecar** exposing HTTP on a localhost port; the frontend talks to it over SSE/WS. Safety decisions, API keys, budgets live in the Python backend — the frontend trusts nothing until a type guard passes. [HC]

---

## 1. The chat window

### 1.1 Message list and streaming

- **Transport:** Server-Sent Events for token streaming (WebSocket later for pushed events: wake-word heard, timer fired, approval requested). Whether to use the Vercel AI SDK's streaming parser or hand-roll a ~100-line SSE client is an open spike (learn-frontend §1 unknown #1) — the SDK's value is the streaming parser + abort plumbing; the contract is the same either way: the frontend receives *processed output*, API keys never leave the backend. [HC]
- **Batch tokens before painting.** Fast streams emit many tiny chunks; batch via `requestAnimationFrame` so React reconciles ~60×/sec, not per-token. Reveal characters at a steady pace that speeds up when the buffer grows — never fall far behind, never stutter. [learn-frontend §1]
- **Hold back incomplete syntax.** `**bold` without the closer stays hidden until it closes or the stream ends — never show half-formed markup. Code fences: keep the incomplete fence readable as plain text mid-stream; render the full highlighted block (with copy button) only when the closing fence arrives. [learn-frontend §1]
- **Never re-render history.** Memoize each message row (`React.memo`); completed messages are static and never re-render when a new token arrives. Virtualize long histories (`react-virtuoso`) — 500 message DOM nodes kill scroll. [learn-frontend §1]
- **Markdown:** `react-markdown` + `remark-gfm`; **sanitize all LLM-fed HTML** (DOMPurify-style) before rendering — the renderer never trusts model output markup. Code highlighting via `rehype-highlight`, deferred per the fence rule above. [learn-frontend §1]
- **STOP is always wired.** Every generation has an abort path (AbortController); the stop control is visible during streaming. A generation with no abort path is a runaway-cost source. (Same instinct as the circuit breaker — the user can always grab control back.) [learn-frontend §1, §3]
- **Scroll discipline:** auto-scroll follows the stream *until the user scrolls up*, then yields instantly and shows a "jump to latest" pill. Never yank the user back down. [learn-frontend §1]
- **Queue messages typed mid-reply.** Text typed while JARVIS is answering is queued, not dropped; drafts persist per-chat (debounced `localStorage`). [learn-frontend §1]

### 1.2 The composer

- Enter sends, Shift+Enter newline; IME-aware (don't send on Enter during CJK composition). [learn-frontend §1]
- Grows with content (1 → ~8 rows), measured via `scrollHeight` in a layout effect — never `setState` per keystroke. [learn-frontend §1]
- Voice input **transcribes into the field for review before sending** — never direct-submit. Precision matters more than speed. [learn-frontend §2]
- The text composer is **always visible, never hidden behind voice-first branding** — it is the fallback for speech impairments, noisy rooms, and privacy. (learn-accessibility §3)

### 1.3 Brain states — always legible

The window shows one unambiguous state at all times (Supervision UX: state must always be legible):

| State | What Owais sees | What it means |
|---|---|---|
| **Idle** | Composer active, subtle reactor glow | Ready. Nothing running. |
| **Listening** | Listening ring + live waveform + "Listening…" + elapsed | Mic open, VAD active. |
| **Transcribing** | Spinner + "Heard you — writing it down…" | STT running on the captured audio. |
| **Thinking** | Calm pulse + "Thinking…" (no fake progress %) | Brain generating. Never show a fake percentage. |
| **Calling tools** | "Checking your calendar…" — the *actual tool*, named in plain words | Tool in flight. The activity feed (§2) shows each call. |
| **Waiting for approval** | "Needs your OK — see dialog" + inline plan context | A tier-3 dialog is open (native, §3). The chat waits; no timeout. |
| **Speaking** | "Speaking…" + the words appear as text simultaneously | TTS playing. Text mirror always present. |
| **Working (background)** | Feed badge count + calm status line | A long task runs; results land in the feed. |
| **Degraded** | "Running on local brain only — cloud is down. [What this means]" | Honest degraded state (R12). Never green-when-broken. |
| **Stopped** | "Stopped. Nothing is running." | Circuit breaker engaged; reports what it stopped. |

**No dead air, ever.** Every state has a visual signal *and* a text label. If a state lasts longer than ~5 seconds, the status line updates with what's actually happening ("Still thinking — this one's taking a while"). [AGENTS.md: narrate work live]

---

## 2. The activity feed

**No silent actions, ever.** Every action JARVIS takes — reads, writes, approvals, denials, background work — lands in a visible, persistent feed inside the chat window. (learn-approval-ux-spec §5)

- **Reads (T1):** grey one-liners, collapsible by task. "Read `notes.md` · 14:31"
- **Reversible writes (T2):** the announce line with a live **Undo** chip for 30 seconds: "Moved 4 files to archive. [Undo]". The undo is a real snapshot restore (R6), and the feed confirms it worked: "Undone — 4 files restored." After the window, a permanent "Kept" state.
- **Irreversible (T3):** the full payload summary with the approval record — who, when, how (tap vs typed confirmation), the action hash, link to the event-log entry (R15 session store).
- **Denied/rejected:** shown too, with what JARVIS did instead (the safe subset). A feed that only shows approvals teaches the user approvals are the norm. Rejections are first-class citizens.
- **STOP control** in the feed header: "Stop all JARVIS activity." The 65-researcher circuit-breaker requirement — STOP *guarantees* every spawned sub-task halts, and reports what it stopped: "Stopped 3 running tasks." [learn-frontend §3; learn-approval-ux-spec §5]
- **Plan progress** renders as a checklist in the feed; any step can be individually stopped or skipped. [learn-approval-ux-spec §6]
- The feed is grouped by task, in plain language, with blast radius visible — **the audit trail Owais can actually read**. (The AWS drift-sequence warning — "the log shows a human approval with a name and a timestamp. Complete. Oversight gone." — is answered by making the log legible.) [learn-approval-ux-spec §5]

---

## 3. Approval dialogs in the chat UI

The full dialog design is specified in `learn-approval-ux-spec.md` (Cycles 20). This section states how it *renders* in the chat window.

### 3.1 What renders where

- **T2 (reversible):** inline **Undo chip** in the chat + feed. No modal. One tap. [learn-approval-ux-spec §2.1]
- **Plan cards:** inline in the chat — itemized steps with tiers, "Steps marked irreversible will ask you individually when I get there." Plan approval authorizes T1/T2 steps only; deviation voids the contract for the divergent step. [learn-approval-ux-spec §6]
- **T3 (irreversible):** the full dialog renders in **Tauri's native window chrome — a dedicated always-on-top native dialog, never inside the WebView2 content area.** Web content (including anything the agent fetched) cannot draw over it, read it, or clickjack it. The chat window shows a calm placeholder: "Needs your OK — approval dialog is open." The feed records the outcome. [learn-approval-ux-spec §4.1]

### 3.2 What a spoofed dialog can't fake

The native dialog has a **persistent visual identity** users learn once:

- Fixed accent (the arc-reactor blue, exact hex), fixed centered position, JARVIS wordmark rendered by the native layer — *blue-centered-native = really JARVIS*. Anything else asking for approval-shaped clicks is fake.
- **Session visual secret:** a short phrase + icon chosen at session start, shown in the native dialog chrome ("Today's phrase: *copper falcon* 🦅"). A spoofed dialog can't know it.
- Provenance line: "Requested by JARVIS core · action #4821 · 14:32:07." Timestamps and sequence numbers make replay visible.
- **The credential rule** (taught once in onboarding): "JARVIS will never ask for a password or key in a dialog. If a dialog asks, it's fake — close it and tell me." [learn-approval-ux-spec §1.2, §4]

### 3.3 The dialog's own rules (carried from Cycle 20)

Seven required fields (goal, what's done, exact action in plain words, blast radius, consequence line, what happens if you say no, origin proof). Never auto-expires. Never pre-checks Approve. Tiers recomputed from the action object in deterministic code — never from the brain's text. Approve/Edit/Reject with **equal visual weight**. For high blast radius: typed confirmation ("type DELETE"). Approve disabled until the payload has been visibly on screen for the dwell time. [learn-approval-ux-spec §1–§3]

---

## 4. Voice mode UI

### 4.1 The mic button — five honest states

Idle → requesting-permission → listening → processing → error. Each state has a distinct visual **and a text label** (accessibility, not decoration). [learn-frontend §2; learn-accessibility §1]

- **Permission denied** gets a settings-redirect hint ("Microphone is blocked — enable it in Windows Settings, or just type instead"), never a dead button. [learn-frontend §2]
- The button shows **what the system hears** — a live transcript preview — not just a level meter. (v1's echo autopsy: the UI must mirror pipeline discipline.) [learn-frontend §2]

### 4.2 The listening ring

- The arc-reactor ring pulses while listening — the brand made functional.
- **`prefers-reduced-motion` is respected:** users who set reduced motion get a **static state indicator** instead of the pulse. A pulsing ring can trigger vestibular issues; the brand never outranks the body. (learn-accessibility §1)
- Nothing flashes more than 3×/second, ever (seizure safety, WCAG 2.3.1). [learn-accessibility §1]

### 4.3 Waveform

- Live waveform via Web Audio `AnalyserNode` → `<canvas>` in a `requestAnimationFrame` loop. Zero dependencies, browser-native. `fftSize` 2048 default. [learn-frontend §2]
- The waveform is the "is it hearing me?" trust cue — if it moves, the mic is live; if it's flat, something's wrong and the UI says so.
- A failed waveform feeder degrades to the static state indicator and logs once — it never freezes the UI forever. (M-U8 clause)

### 4.4 States that can't be confused

Listening / thinking / speaking look and read differently — distinct color, distinct label, distinct motion. Shared state between voice and GUI: while voice gives auditory feedback, the GUI supplements with visual cues. The approval dialog is the canonical case: spoken request + on-screen Approve/Reject with visible payload. [learn-accessibility §3; learn-frontend §2]

### 4.5 Text fallback — one tap, always

- The text composer is **always one tap away** in voice mode. Voice fails in cafés, in meetings, with a sore throat — the GUI is a full peer, not a companion. [learn-accessibility §3]
- **No audio-only signals, ever.** Wake confirmation, approval requests, errors, "done" — all have visual + text equivalents. A TTS-only "done" is a barrier for 460M+ people with disabling hearing loss. [learn-accessibility §3]
- Over voice, a bare "yes" is **never** a tier-3 approval — the "say the keyword back" protocol, with the payload on screen. No screen → the action waits for text. [learn-approval-ux-spec §7]

---

## 5. Accessibility — the testable checklist

Web accessibility **is** desktop accessibility here: semantic HTML + ARIA in the Tauri frontend flows through WebView2 → UIA → NVDA with no extra native code. And symmetrically — the UIA tree JARVIS *reads* to control the PC is the same tree screen readers read, so JARVIS must expose a clean one. [learn-accessibility §2]

### 5.1 Non-negotiables

- **Screen readers:** announce on **message completion** via `role="status"` / `aria-live` — never per-token (chaos). Approval dialogs announced with their full payload. [learn-accessibility §1]
- **Keyboard:** everything operable — composer, mic button, approval dialogs, settings, feed. Tab order Approve → Edit → Reject; Enter activates; Esc = Reject/close. No keyboard traps. Focus visible and never hidden behind overlays. [learn-accessibility §1]
- **Text scaling:** usable at **200% zoom** with no clipping or overlap — no fixed-height containers in the chat UI. [learn-accessibility §1]
- **Contrast:** 4.5:1 normal text, 3:1 large text and UI components. The arc-reactor blue-on-dark aesthetic gets checked with a contrast tool, not eyeballed — this is exactly where dark themes fail. [learn-accessibility §1]
- **Targets:** 24×24 CSS px minimum for every interactive target — Approve/Reject thumb-tappable. [learn-accessibility §1]
- **No time pressure:** approval dialogs never auto-expire. No countdowns. (learn-accessibility §1)
- **Reduced motion:** honored everywhere (ring, waveform, transitions). [learn-accessibility §1]
- **Plain language:** reading level ≤ lower-secondary; errors say what happened **and what to do**. "Microphone unavailable" → "Plug in a mic or click to type instead." Never an error code. [learn-accessibility §1, §4]
- **Native elements first:** real `<button>`, `<input>`, landmarks; ARIA only where native falls short. Every interactive element gets a name, a role, and a state (`aria-pressed` on mic toggle, `disabled` on Approve during execution). [learn-accessibility §1–§2]

### 5.2 Testing (three layers)

1. **CI:** axe-core on every PR (missing labels, contrast, target size, invalid ARIA); Lighthouse a11y as smoke signal; scripted Tab-order walk. Automation catches ~57% of issues by volume — necessary, not sufficient. [learn-accessibility §5]
2. **Manual before release:** NVDA pass of the two core flows (ask by voice, ask by text, approve a consequential action); keyboard-only pass (unplug the mouse); 200% zoom pass; Microsoft Accessibility Insights. [learn-accessibility §5]
3. **Scheduled re-scans** between releases. [learn-accessibility §5]

---

## 6. The HUD lessons — what carries forward, what's left behind

### Carries forward

- **The arc-reactor aesthetic** — dark theme, reactor-blue accent, calm glow. It's the brand; the chat window keeps it (contrast-checked per §5.1).
- **State legibility** — v1's reactor states (listening/thinking/speaking) were the right instinct; §1.3 makes them unambiguous with text labels.
- **Tray presence** — tray icon + context menu (Show chat / Voice mode / Settings / Check updates / Quit). Win11 hides tray icons in overflow by default — **onboarding must say to drag it out**, or users think the app died. [learn-frontend §5]
- **Summon hotkey** (e.g. Ctrl+Alt+J) that shows the chat from anywhere; Ctrl+Alt+S for settings (v1's binding, kept). Hotkeys user-remappable. Registration failure is non-fatal and reported, never silent. [learn-frontend §5]
- **Native toasts, gated** — notifications are interruptions; the Four Checks gate them, otherwise they batch into the chat. A JARVIS that toasts constantly gets muted. [learn-frontend §5]

### Left behind

- **The invisible click-through overlay** (H-U4, M-U13) — the click-eating hole is gone. The chat window is a normal window with correct hit-testing from the first frame. No `WS_EX_TRANSPARENT` tricks.
- **Focus stealing** (M-U2) — the window never steals focus uninvited. Summon uses show-without-activating; type-ahead works without yanking focus.
- **Geometry guessing** (M-U5, M-U6) — window position is remembered, validated against the live monitor set on every launch and on display-change events; off-screen → moved to primary. "Reset window position" lives in the tray menu.
- **Translucency assumptions** (M-U3) — if compositing is unavailable, the UI falls back to a solid background. Never an opaque black rectangle.
- **Z-order fights with fullscreen apps** (M-U4) — fullscreen detected → yield, notify via toast instead of fighting.
- **Native-event-filter hacks** (H-U1) — no `nativeEventFilter` tuple games; hotkeys go through the Tauri global-shortcut plugin, frontend keys are standard web handlers.

---

## 7. Error UX — "what happened + what to do"

Every failure the UI surfaces uses the same format: **what happened** (plain words) **+ what to do** (the fix path). Never a stack trace or error code to a non-technical user. Never a bare "couldn't start." [learn-accessibility §4; R12]

- **Crash dialog (mid-session vs startup):** H-U3's fix — the dialog knows which one it is. Startup failure: "JARVIS couldn't start because [reason]. [Try again] [Reset settings] — details saved to [true path]." Mid-session: "Something broke while you were working. Your chat is safe. [Restart JARVIS] [Report]." The log path named is verified to exist before it's named (M-U9 clause). [R14]
- **Startup preflight:** before the main window — VC++ redist, Python version/bitness, disk space, mic/camera availability, model files with checksums. Each check that fails gets a plain-language fix. [R12]
- **Startup watchdog:** progress milestones with budgets; a hung stage offers "Wait / Restart / Report" — never a silent hang forever. (M-U15 clause) [R14]
- **Runtime watchdog:** a real heartbeat replaces the startup-only faulthandler dump. Brain heartbeat missed → "JARVIS stopped responding. [Restart] [Report]". Deadlock at minute 30 gets a trace and a recovery offer, not a frozen window. (H-U5 clause) [R14]
- **Optional hardware honest states:** camera/mic/wake-word each have an explicit unavailable state with the reason — "Camera unavailable: couldn't load the camera library." Never a stuck "◌ searching…" spinner. (M-U10/M-U11/M-U12 clauses)
- **Hotkeys dead?** The chat still launches; the feed notes "Hotkeys unavailable ([reason]). The window still works — remap in Settings." (M-U16 clause)
- **Degraded, never silently:** cloud down → "Running on local brain only — cloud is down. [What this means]". The UI is never green-when-broken. [R12; §1.3]

---

## 8. Failure table — every v1 UI corpse and the clause that kills it

| Corpse | Spec clause |
|---|---|
| H-U1 `nativeEventFilter` tuple TypeError | §6 left-behind: no native event filtering; hotkeys via Tauri global-shortcut plugin, frontend keys are standard web handlers |
| H-U2 hotkey leak on partial registration | §6: single owner for registration; `unregisterAll` on quit; stale registrations detected at startup and reported |
| H-U3 excepthook logs-and-limps, wrong MessageBox | §7: crash dialog distinguishes startup vs mid-session; correct message; restart/recovery offered; true log path |
| H-U4 fake click-through, click-eating hole | §6 left-behind: normal window, correct hit-testing from first frame; no overlay transparency tricks |
| H-U5 zero runtime hang detection | §7: runtime heartbeat watchdog; hang → trace + "Restart / Report" |
| M-U1 `screen` None → startup crash | §6: geometry code treats missing screen as normal; fallback to primary; never crashes on geometry |
| M-U2 `show()`/`raise_()` steals focus | §6 left-behind: show-without-activating on summon; focus moves only on explicit user action |
| M-U3 translucency without DWM → black rectangle | §6 left-behind: solid-background fallback when compositing unavailable |
| M-U4 z-order fight in fullscreen games | §6 left-behind: fullscreen detected → yield + toast instead of fighting |
| M-U5 HUD on wrong monitor first launch | §6: position remembered, validated against live monitors on launch |
| M-U6 off-screen after monitor disconnect | §6: rect validated on launch + display-change events; "Reset window position" in tray menu |
| M-U7 arbitrary size → negative gauge math | §7/R14: all geometry/settings clamped at load AND apply; window enforces min/max |
| M-U8 feeder thread dies → frozen waveform | §4.3: feeder failures degrade to static indicator, log once; heartbeat on UI update paths |
| M-U9 crash log path lies in dialog | §7: single log location in data dir; path verified to exist before being named |
| M-U10 cv2 import kills thread, stuck "searching…" | §7: every optional-hardware feature has an explicit unavailable state with the reason |
| M-U11 no cascade check → silent thread death | §7: assets validated in startup preflight; broken asset → honest message, feature disabled |
| M-U12 camera held while delivering no frames | §7: hardware health check — no frames in N seconds → release camera + say so |
| M-U13 120ms click-eating window on show | §6 left-behind: no click-through timing hacks; hit-testing correct from first frame |
| M-U14 invalid `corner` silently falls back | §7/R14: config values validated with clamps at load; invalid → default + one-time feed notice |
| M-U15 startup hang, no retry/kill/notify | §7: startup watchdog with milestones; "Wait / Restart / Report" on hung stage |
| M-U16 `register_hotkeys()` no try/except → startup dies | §6: hotkey registration non-fatal; failure → chat launches, feed notes it, remap offered |

**Orphan check:** 21 corpses, 21 clauses. No orphans. [VC on the mapping — each corpse is quoted from the autopsy above]

---

## 9. Traceability — every section to its source

| Spec section | Sources |
|---|---|
| §1.1 streaming engineering | learn-frontend §1 (Vercel AI SDK pattern, batching, memoization, virtualization, stop path, scroll discipline, code fences) |
| §1.2 composer | learn-frontend §1 (Enter/IME/grow/drafts/queue); learn-accessibility §3 (transcribe-for-review, composer always visible) |
| §1.3 brain states | AGENTS.md Supervision UX + "narrate work live"; learn-frontend §2 (states mirror pipeline); R12 (honest degraded) |
| §2 activity feed | learn-approval-ux-spec §5 (feed, undo, STOP guarantee); learn-frontend §3 (circuit breakers) |
| §3 approval rendering | learn-approval-ux-spec §§1–4, 6–7 (dialog fields, trusted chrome, origin proof, plan mode, voice approvals) |
| §4.1–4.3 mic button, ring, waveform | learn-frontend §2 (states, permission, AnalyserNode); learn-accessibility §1 (reduced motion, no >3Hz flash) |
| §4.4–4.5 states, text fallback | learn-accessibility §3 (no audio-only, GUI as peer); learn-approval-ux-spec §7 (voice approvals) |
| §5 accessibility checklist | learn-accessibility §§1–5 (WCAG 2.2, WebView2/UIA, testing layers) |
| §6 HUD carry/leave | FAILURE-ANALYSIS H-U1–H-U5, M-U1–M-U16; learn-frontend §5 (tray, hotkeys, toasts) |
| §7 error UX | learn-accessibility §4 (what happened + what to do); R12; R14 (crash reporting, watchdogs) |
| §8 failure table | FAILURE-ANALYSIS.md UI findings, quoted verbatim above |

---

## 10. Open questions [UK] / proposed-not-measured [PROPOSED]

1. **Vercel AI SDK vs hand-rolled SSE client** — [UK] (learn-frontend §1). Spike both against the local Python brain; measure, don't theorize.
2. **WebView2 a11y fidelity on the pinned runtime** — [UK] (learn-accessibility §6). NVDA pass needed before any conformance claim; Evergreen updates can shift behavior.
3. **`prefers-reduced-motion` inside WebView2** — [UK]. Verify the media query propagates from OS settings.
4. **200% text scaling on the chat layout** — [UK]. Verify no clipping/overlap at 200%+ before release.
5. **Tauri trusted-chrome reality** — [UK] (learn-approval-ux-spec §9). Whether the native dialog actually defeats overlay attacks on Windows needs the frontend spike.
6. **Owais's approval-fatigue curve** — [UK]. The 5-dialogs/day budget and dwell times are principled proposals; calibrate against his first month of real usage.
7. **Hotkey collisions on his machine** — [UK]. The exact set needs testing on the real Windows install.
8. **VAD tuning for Hinglish** — [UK] (learn-frontend §1). Thresholds need real-usage tuning, not docs.
9. **SmartScreen reputation timeline** — [UK] (learn-frontend §6). "Weeks and hundreds of installs" is the documented shape, not measured for JARVIS.

---

## 11. The one-paragraph version (plain English)

The chat window is JARVIS's face. It always shows what JARVIS is doing — listening, thinking, working, waiting for your OK — so there's never a confusing silence. Everything JARVIS does appears in a feed you can read, undo where possible, and stop with one button that really stops everything. When JARVIS needs permission for something irreversible, the request opens in a special window that web pages can't fake, showing exactly what will happen in plain words — and you can always say no. If you use voice, there's a clear ring and waveform so you know it's hearing you, but typing is always one tap away and nothing important is ever voice-only. If something breaks, it tells you what broke and what to do about it, in plain English — never a bare "couldn't start." And every way the old HUD broke (click-eating invisible windows, stealing your focus, freezing silently) is mapped to the rule that prevents it.

---

## Confidence & unknowns (file-level)

- [VC] on the v1 corpse mappings (§8 — quoted verbatim from the autopsy).
- [HC] on the streaming engineering (§1.1 — converges across production write-ups in learn-frontend §1), the accessibility checklist (§5 — WCAG 2.2 criteria verified against multiple sources), and the approval rendering (§3 — carried from the Cycle-20 spec).
- [MC] on the Tauri recommendation's fit to this team (learn-frontend §4: right on paper, Rust capacity unproven) and on the brain-state table's completeness (states may need revision against the real pipeline).
- [UK] on the nine items in §10.

## Completion report (Rule 12)

- **Researched:** 4 source files read in full (FAILURE-ANALYSIS UI sections + R14, learn-frontend, learn-accessibility, learn-approval-ux-spec). No new web searches — skip-if-learned applied; all mechanics were already in the knowledge base.
- **Validated:** corpse IDs and quotes cross-checked against FAILURE-ANALYSIS.md via grep; R14 text quoted verbatim; section-to-source traceability table built.
- **Saved:** `~/workspace/jarvis-knowledge/learn-chat-ui-spec.md`.
- **Modified / tested / measured:** none (learning only, per task).
- **Incomplete:** none — all 8 spec sections + traceability + open questions written.
- **Blocked:** validation needs the Tauri build (streaming, trusted chrome, a11y passes) and Owais's usage data (fatigue thresholds) — recorded in §10, not assumed.
