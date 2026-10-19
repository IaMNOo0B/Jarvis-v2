# Frontend & Desktop Applications — Learning Notes (Domain P)

*Learning mission 2026-10-19. Scope discipline: the interaction spec for the chat UI (streaming honesty, approval cards, error UX) is already covered in `scout-phd-chat-ui.md` (Study 49, 88%) and the frontend/backend contract in `~/workspace/learning/typescript-hud/LEARNINGS.md`. This file covers ONLY the gaps: the React engineering of streaming, web voice controls, one-tap approval UX research, Electron vs Tauri decision, Windows tray/hotkey/notification integration, and auto-updates + code signing.*

---

## 1. React Streaming Chat UI — the engineering

**Purpose:** Turn a token stream into a readable, controllable interface without jank. (The *behavior* spec — 5 response states, STOP button, scroll discipline, deferred code fences — is Study 49 §2.4. This section is the *implementation*.)

**How it works (the stack):**
- **Transport:** Server-Sent Events (SSE) or the AI SDK's UI-message stream. The 2026 default for React is the **Vercel AI SDK** (`ai` + `@ai-sdk/react`): server does `streamText(...)` → `result.toUIMessageStreamResponse()`; client `useChat()` consumes parts (`m.parts.map(p => p.type === "text" ? p.text : …)`). API keys stay server-side; the frontend only receives processed output. In AI SDK v7+, `convertToModelMessages` is async (a real gotcha). Note: the SDK is React-opinionated; Vue/Svelte need custom adapters.
- **Markdown:** `react-markdown` + `remark-gfm` (tables, task lists) + Tailwind `typography` plugin. **Sanitize LLM-fed HTML** before rendering (DOMPurify-style) — the renderer never trusts model output markup (Study 49).
- **Code blocks:** syntax highlighting via `rehype-highlight` (or `react-syntax-highlighter`). Key rule: **never re-highlight the whole block on every token** — highlight incrementally, and defer the full code-block render (with copy button) until the closing fence arrives; keep the incomplete fence readable as plain text mid-stream. Tell the model to format in markdown in the system prompt — CSS alone won't add bullets if the model emits plain line breaks.

**Efficient re-renders (the performance layer):**
- **Batch tokens before committing to UI** — fast streams emit many tiny chunks; batch via `requestAnimationFrame` so React reconciles ~60×/sec instead of per-token. Rendering exactly what arrives makes text stutter (nothing, then twelve words, then nothing).
- **Smooth the reveal:** reveal characters at a steady pace that speeds up when the buffer grows — never fall far behind, never stutter. Hold back incomplete inline syntax (`**bold` without the closer) until it closes or the stream ends.
- **Memoize message components** (`React.memo` on the message row) so a streaming message doesn't re-render the entire history on every token. Completed messages are static — they should never re-render.
- **Virtualize long histories** (`react-virtuoso` / `react-window`) when conversations grow long; rendering 500 message DOM nodes kills scroll performance.
- **The `stop` path:** `useChat` exposes `stop()` (AbortController). Always wire it — long generations with no abort path are a runaway-cost source.

**Composer details that matter (from production experience):**
- Enter sends / Shift+Enter newline; check `event.nativeEvent.isComposing` for IME (CJK) users or Enter confirms the candidate, not the message.
- Grow the textarea with content (1 → ~8 rows), measuring `scrollHeight` in a layout effect — never `setState` on every keystroke in a native input listener.
- Save drafts to `localStorage` keyed by chat id (debounced); queue messages typed during a reply rather than dropping them.

**JARVIS application:** v2's chat is the primary surface (chatbot-first). The React frontend talks to the local Python brain over HTTP now, WebSocket later for token streaming and pushed events (wake-word heard, timer fired) — same contract discipline as the typescript-hud learnings: frontend trusts nothing until a type guard passes; API keys, budgets, safety decisions live in the Python backend.

**Best libraries:** `ai` + `@ai-sdk/react` (transport), `react-markdown` + `remark-gfm` + `rehype-highlight` (rendering), `react-virtuoso` (virtualization), DOMPurify (sanitization).

**Official docs:** Vercel AI SDK docs (ai-sdk.dev), react-markdown README, MDN Web API (SSE/EventSource).

**Limitations/trade-offs:** Vercel AI SDK is React-centric and opinionated; abstraction leaks mean you still need to know the underlying provider SDKs when debugging. SSE is one-directional (fine for chat; WebSocket needed for bidirectional push). Markdown renderers must be configured, not assumed — raw model output is not reliably GFM.

**Security implications:** Never initialize an LLM client in the browser (keys extractable from devtools). Sanitize all model HTML. Budgets/rate-limits enforced server-side where the client can't bypass them.

**Common failure modes:** Re-render storm on every token (flicker + dropped frames); half-rendered code fences (fixed by the two-state `content`/`final` contract); scroll-yank (auto-scroll must yield the moment the user scrolls up); dropped messages typed mid-stream; IME Enter conflicts.

**Confidence: 85% [HC]** — the libraries and patterns are well-evidenced across production write-ups; JARVIS-specific composition (local Python brain + React via WS) unvalidated.

**Unknown:** Whether JARVIS even needs the Vercel AI SDK (it's cloud-provider-shaped) vs. a thin custom SSE/WS client to the local brain — the SDK's value is mostly the streaming parser + abort plumbing, which is ~100 lines to hand-roll.

---

## 2. Voice Controls in a Web UI

**Purpose:** Mic button, live feedback, and input-mode selection for the chat composer — the web surface of the voice pipeline (pipeline itself is the V-studies).

**How it works:**
- **Capture:** `navigator.mediaDevices.getUserMedia({ audio: true })` → `MediaStream`. Permission states: `granted` / `prompt` / `denied` — handle all three in the UI (denied needs a settings redirect hint, not a dead button). AudioContext must be created/resumed inside a user gesture.
- **Waveform visualization:** `AudioContext.createAnalyser()` → `createMediaStreamSource(stream).connect(analyser)` → per-frame `getByteTimeDomainData()` (waveform) or `getByteFrequencyData()` (bars) drawn on `<canvas>` in a `requestAnimationFrame` loop. `fftSize` 2048 is the common default (power of 2, 32–32768); smaller = faster updates, lower resolution. Zero dependencies — browser-native.
- **Mic button states (minimum):** idle → requesting-permission → listening (animated waveform/pulse) → processing (transcribing spinner) → error. Each state needs distinct visual + a text label for accessibility.
- **Push-to-talk vs VAD (the input-mode decision):**
  - **Push-to-talk:** hold (or toggle) to record; explicit start/stop; `MediaRecorder` captures to a blob sent for transcription. Predictable, zero false triggers, works everywhere. Cost: one hand busy; feels mechanical.
  - **VAD (voice activity detection):** mic open, speech start/stop detected automatically. In-browser options: energy-threshold on the AnalyserNode (cheap, false-triggers on noise — never use raw energy alone for *actions*), or a real model — `@ricky0123/vad-web` (Silero VAD compiled to ONNX/WASM, runs fully client-side) is the standard choice. Semantic end-of-turn (Smart Turn v3.2, V3 study) is the high end.
  - **JARVIS rule (from v1's echo autopsy):** the web UI must mirror the pipeline discipline — barge-in on *novel transcribed words*, never on raw audio energy; the mic button shows *what the system hears* (transcript preview), not just a level meter.

**JARVIS application:** The composer gets voice input that **transcribes into the field for review before sending** (Study 49: never direct-submit — precision matters). Waveform = the "is it hearing me?" trust cue. The HUD's voice states (listening/thinking/speaking) get a web mirror.

**Best libraries:** Native Web Audio API + Canvas (visualization); `MediaRecorder` (capture); `@ricky0123/vad-web` (client-side VAD); Wavesurfer.js if full waveform editing is ever needed.

**Official docs:** MDN — `MediaDevices.getUserMedia`, `AnalyserNode`, `MediaRecorder`, Permissions API.

**Limitations/trade-offs:** Browser mic requires a user gesture and (in production) a secure context; permission denial is common and must be designed for. Energy VAD false-triggers on noise/keyboard. Client-side VAD models add WASM payload (~MBs). Echo: if TTS plays through speakers while the mic is open, the loop hears itself — the web UI inherits v1's echo lesson.

**Security implications:** Mic access is a sensitive permission — request it in context (when the user taps the mic), never at page load. Show a persistent "mic live" indicator; never capture silently. Audio stays local for VAD; only send to STT what the user approved.

**Common failure modes:** AudioContext suspended (created outside a gesture — call `resume()`); permission-denied dead button; feedback loop (mic + speakers); VAD cutting off quiet speakers; stream tracks never stopped (mic light stays on — always `track.stop()` on unmount).

**Confidence: 90% [HC]** — Web Audio APIs are stable, long-documented standards.

**Unknown:** Which VAD threshold/model feels right for Hinglish conversational speech on Owais's hardware — needs tuning against real usage, not docs.

---

## 3. Approval Dialogs / One-Tap Permission UX

**Purpose:** The core JARVIS UX problem — "JARVIS wants to do X" presented so a non-technical user decides correctly in one tap. (Study 49 §2.3 gives the ApprovalCard anatomy; the Four Checks (Study 25) are the gating procedure. This section adds the *consent science*.)

**How it works — what the research says:**
- **Permission dialogs rarely create real consent; they create ritualized acceptance.** Users treat prompts as speed bumps to click past. After dozens of consequence-free "Allow" clicks, users learn Allow is low-cost and click first, think later. A button's presence does not create agency.
- **The Google-led 65-researcher finding (2026)** — Google Research, *"Open and Emergent Problems in Agentic Privacy and Security: A Contextual Angle"* (65 authors, 36 Google-affiliated; from the CAPS Workshop, NYC Nov 2025; research blog post Oct 5, 2026, Bagdasarian & Gruteser): notice-and-choice "is unlikely to be effective for AI agents" — four breakdowns: (1) users can't foresee execution paths ("manage my schedule" = signing a blank check); (2) consent covers raw inputs but not *inferences* (grocery switch → medical diagnosis); (3) binary Allow/Deny can't carry conditions ("only if the price is reasonable"); (4) asking about every sub-task → fatigue, asking less → overly broad authority. Proposed: a **sliding scale** (low-stakes auto-proceed, financial transfers explicit-confirm, third-party-risk actions blocked), per-request generated interfaces, policies learned from past decisions, and **circuit breakers** that guarantee STOP halts every spawned sub-agent (current "stop" messages offer no such guarantee).
- **Design rules that survive the research:**
  1. **Plain language a 12-year-old understands** — no jargon, ever ("delete these 3 files" not "execute filesystem mutation").
  2. **Show the payload, not a summary** — recipient, diff, amount, the exact tool. A card that hides the payload is theater (Study 49).
  3. **Equal visual weight for Approve and Reject** — dark patterns (big bright Allow, grey hidden Deny) manufacture compliance and destroy trust.
  4. **Contextual handoff:** "I'm trying to [goal]. Done [1], [2]. Stuck at [problem]. Options:" — not a bare "What should I do?"
  5. **Fewer, higher-stakes gates + undo buffer** — reserve checkpoints for irreversible/high-stakes actions; use Gmail-style 30-second Undo for the middle ground. Too many gates → rubber-stamping (consent fatigue) → the gates stop working.
  6. **Always-offer alternatives on deny** — "No" must not equal broken functionality; offer the safe subset.
  7. **Ongoing revocation** — a settings surface where past grants are visible and revocable; consent is a relationship, not a click.

**JARVIS application:** The two-dial safety model (auto-allow reads, confirm writes, sandbox code) gets its screen here. ApprovalCard props: goal, what's-done, exact payload, Approve / Edit / Reject with equal weight, calm-butler copy, zero terminal. The Four Checks decide *whether* the card appears; this section decides *what it looks like*.

**Best references:** Study 49 §2.3 (anatomy), Study 25 (Four Checks gating), Google Research "Open and Emergent Problems in Agentic Privacy and Security" (Oct 2026, 65 authors, CAPS Workshop), UXMag consent-fatigue analysis.

**Limitations/trade-offs:** No dialog design fixes the fundamental agent-consent problem (unforeseeable execution paths) — the mitigation is architectural (sliding-scale autonomy, scoped tool tokens à la ScrambleID/SEC3, circuit breakers), not cosmetic. Fewer prompts = better decisions per prompt, but broader standing authority per grant.

**Security implications:** Rubber-stamping is a security vulnerability — an attacker who can trigger many low-stakes prompts trains the user to approve the one high-stakes prompt. Rate-limit and aggregate approval requests; anomaly-flag unusual ones (new recipient, large amount, first-time tool).

**Common failure modes:** Consent fatigue → blind approval; payload hidden behind "details" link; Deny styled as secondary; approval requested at the moment of maximum friction (mid-task) instead of at a natural decision point; no undo; no revocation surface.

**Confidence: 88% [HC]** — converges across UX research, the agent-consent report, and our own studies.

**Unknown:** The exact calibration for Owais — how many gates before *he* starts rubber-stamping. Needs observation, not theory.

---

## 4. Electron vs Tauri for a Python AI Assistant — the decision

**Purpose:** Choose the desktop shell for JARVIS v2's HUD/chat. (v1 used PyQt6; the question is what the chatbot-first rebuild uses.)

**How they differ:**

| | Electron | Tauri 2.x |
|---|---|---|
| UI runtime | Bundles Chromium (~80–200MB installer) | System WebView (WebView2 Win / WKWebView mac / WebKitGTK Linux) → 2–10MB |
| Idle memory | ~150–400MB | ~30–70MB |
| Cold start | ~1–2s | ~0.2–0.9s |
| Backend language | Node.js | Rust |
| Security model | Permissive — you harden it (context isolation, preload, CSP) | Deny-by-default capabilities — everything disabled until explicitly allowed |
| Python integration | Spawn via `child_process` / `utilityProcess`; manual lifecycle | **Sidecar pattern** (`externalBin` + `Command::new_sidecar`), permission-gated via `shell:allow-execute` |
| Auto-update | electron-updater (mature) | Built-in updater plugin (minisign-signed, younger) |
| Mobile | No | iOS/Android from same codebase (v2) |
| Ecosystem | Huge (VS Code, Slack, Discord, 1Password…) | Growing fast; 2026 momentum ~55% YoY star growth |
| Dev learning curve | JS everywhere | Rust required for backend work |

**Python integration — the decisive detail for JARVIS:**
- **Tauri sidecar (the documented pattern):** pack the Python brain with PyInstaller → declare `externalBin: ["binaries/jarvis-brain"]` in `tauri.conf.json` → binary must carry the target-triple suffix (`jarvis-brain-x86_64-pc-windows-msvc`) → spawn from Rust with `Command::new_sidecar("binaries/jarvis-brain")`, stream stdout events, and **you own killing the child on app close** (orphan processes are the classic bug). Shell execution is permission-gated in the capabilities file (`shell:allow-execute` scoped to the named sidecar). Communication: sidecar exposes HTTP on a localhost port (Rust picks a free port, passes it as an arg) — the exact architecture the typescript-hud learnings already sketch (`fetch` → `127.0.0.1:port`, WebSocket later).
- **Electron:** `child_process.spawn` / `utilityProcess` for the Python exe; you manage lifecycle, port discovery, and crash restarts yourself. More examples in the wild, less structure.

**Trade-offs for JARVIS specifically:**
- JARVIS is **always-on background software** on a 6GB-VRAM / 16GB-RAM machine — Tauri's 30–70MB idle vs Electron's 150–400MB is not cosmetic, it's headroom for the actual brain.
- Tauri's deny-by-default capabilities map 1:1 onto v2's security requirements (R2 instruction hierarchy, R11 skill permissions, the Deno lesson/SEC5).
- Electron wins on: ecosystem examples, build speed (faster incremental builds), rendering consistency (bundled Chromium vs WebView2 version variance), and updater maturity.
- Tauri costs: Rust learning curve (2–3 months to productivity per practitioner reports); younger plugin ecosystem; WebView2 must exist on the user's Windows (it's preinstalled on Win10 1803+ / Win11 — fine for Owais, but a setup-check item for distribution).

**Recommendation: Tauri 2.x.** The Python-sidecar pattern is first-class (not a hack), the resource profile fits an always-on assistant on modest hardware, and the capability model is the security architecture v2 already requires. Electron is the fallback if the team hits Rust-shaped walls.

**Official docs:** Tauri v2 docs (v2.tauri.app) — sidecar guide, updater plugin, Windows code-signing guide; Electron docs (electronjs.org) — `autoUpdater`, `Tray`, `globalShortcut`, `Notification`; electron-builder auto-update guide.

**Limitations:** Tauri needs Rust competence on the team; sidecar binaries bloat the installer by the Python runtime size (~15–30MB PyInstaller — still far under Electron's Chromium); WebView2 version drift across user machines.

**Security implications:** Tauri's capability ACLs are the enforcement point for R2/R11 — frontend gets exactly the commands it needs, nothing else. Electron requires manual hardening (contextIsolation, sandbox, preload-only bridge) — misconfiguration is the common CVE source. Either way the Python brain must bind 127.0.0.1 and authenticate loopback callers (SEC2 localhost-hijack lesson).

**Common failure modes:** Orphaned Python sidecar after app close; port collision on localhost; WebView2 missing/outdated on user machines; capability file too permissive (defeats the model) or too strict (mysterious failures); unsigned updates rejected.

**Confidence: 90% [HC]** on the comparison facts; 80% [MC] on the recommendation — it's the right call on paper, unproven against this team's Rust capacity.

**Unknown:** Real-world Tauri + PyInstaller-sidecar + auto-update behavior across Windows updates — needs a spike build, not more reading.

---

## 5. System Tray, Global Hotkeys, Notifications on Windows

**Purpose:** JARVIS lives in the background — tray icon = presence, hotkey = summon, notification = the tap on the shoulder. All three are OS-integration, not web UI.

**How it works:**

**System tray:**
- **Tauri:** `tray-icon` (built on the `tray-icon` Rust crate) — icon + context menu, configured in `tauri.conf.json` (`id`, `iconPath` .ico, `iconAsTemplate`), accessed via `app.tray_by_id("tray")`. Windows backend = `Shell_NotifyIcon` Win32 API. v1 already proved the pattern with PyQt6's `QSystemTrayIcon` — the concept transfers, the API changes.
- **Electron:** `new Tray(nativeImage)` + `tray.setContextMenu(Menu.buildFromTemplate([...]))`; click/double-click handlers show/hide the window.

**Global hotkeys:**
- **Tauri:** `@tauri-apps/plugin-global-shortcut` (Rust 1.90+ for current versions) — register in Rust or from the frontend via the JS guest bindings; shortcut strings normalized (`Control+Shift+J` style). Note: some key combos are reserved by Windows; registration can fail silently if another app holds the combo — always handle the failure and offer remapping.
- **Electron:** `globalShortcut.register('CommandOrControl+Shift+J', handler)`; must `unregisterAll()` on quit.
- **JARVIS mapping:** Ctrl+Alt+S (settings — already v1's binding), plus a summon hotkey (e.g., Ctrl+Alt+J) that shows the chat window from anywhere. Hotkeys user-remappable in Settings (v1's settings philosophy: Owais delegates the defaults).

**Notifications:**
- **Tauri:** `@tauri-apps/plugin-notification` → native Windows toast notifications.
- **Electron:** `new Notification({ title, body }).show()` → same native toasts.
- **Design rule (Four Checks):** notifications are interruptions — gate them. ACT only when the Four Checks pass; otherwise batch into the chat. A JARVIS that toasts constantly is a JARVIS that gets muted.

**JARVIS application:** Tray menu = Show chat / Voice mode / Settings / Check updates / Quit. Single-instance lock (v1's QLockFile lesson) + tray "already running" nudge. Hotkey summons the window; the window is the chat (chatbot-first).

**Official docs:** Tauri v2 plugin docs (tray-icon, global-shortcut, notification on docs.rs / v2.tauri.app); Electron docs — `Tray`, `globalShortcut`, `Notification`; Microsoft docs on toast notifications.

**Limitations/trade-offs:** Global hotkeys contend with other apps (no central registry on Windows — first-come wins, failures silent). Tray icons on Win11 hide in the overflow by default (user must drag it out — onboarding must say so). Toast notification permissions can be disabled system-wide.

**Security implications:** Global hotkeys are a keystroke-interception-adjacent surface — register the minimum set; never log keystrokes. Tray context menus must not expose privileged actions without the same approval gates as chat.

**Common failure modes:** Hotkey registration silently failing (combo taken); tray icon invisible in Win11 overflow (user thinks the app died — this is a support-ticket generator); notifications muted at OS level so "JARVIS never tells me anything"; toast click not focusing the window.

**Confidence: 88% [HC]** — stable, long-lived APIs on both frameworks.

**Unknown:** The exact hotkey set that feels native without colliding — needs testing on Owais's machine.

---

## 6. Auto-Updates + Code Signing on Windows

**Purpose:** Ship fixes without Owais touching anything (zero-terminal doctrine extends to updates). Two layers: (a) the update *mechanism*, (b) the *trust* that makes Windows run it.

### 6a. The mechanisms

**Tauri updater:**
- Plugin `@tauri-apps/plugin-updater`; update server serves a `latest.json` manifest (platform URLs + signatures, template vars `{{current_version}}`/`{{target}}`/`{{arch}}`).
- **Every update artifact is signed with minisign (Ed25519)** — private key in CI secrets (`TAURI_SIGNING_PRIVATE_KEY`), public key embedded in `tauri.conf.json` (`plugins.updater.pubkey`). Signature verification happens client-side before install; **failure aborts the install**. Key rotation invalidates old releases — plan rotation deliberately.
- Windows targets: **NSIS or MSI** installers; NSIS updates run with `/UPDATE` flags, MSI via `msiexec` with install modes (Quiet/Passive/BasicUi). The `tauri-action` GitHub Action generates signatures + `latest.json` automatically when the signing env vars are present.

**Electron (electron-updater):**
- Mature; reads `latest.yml` metadata; supports **delta updates** (Squirrel.Windows downloads only the binary diff N→N+1). electron-builder's NSIS target is the recommended path (Squirrel.Windows maker path is legacy — electron-builder docs note simplified auto-update works with default NSIS).
- Built-in `autoUpdater` auto-selects the mechanism by package format (Squirrel.Windows vs MSIX). Squirrel apps must handle `--squirrel-install/--squirrel-updated/--squirrel-uninstall/--squirrel-firstrun` argv events or shortcuts/registry break.
- Update server can be GitHub Releases, S3, or any static host (even `update.electronjs.org` for public repos via the `update-electron-app` one-liner).

**JARVIS rule:** updates download in the background, prompt once via the chat/tray ("Update ready — restart to apply? [Restart now] [Tonight]"), never force-restart mid-conversation. Signed updates only (R10) + rollback to the previous version on failed start (R10's rollback requirement — keep N-1 installer cached).

### 6b. Code signing on Windows — the 2026 reality

- **The old world is gone:** EV certificates no longer grant instant SmartScreen reputation (Microsoft removed EV OID special-casing; all code-signing certs treated equally). Paying EV prices solely to dodge SmartScreen is not justified.
- **The current path: Azure Artifact Signing** (renamed from Trusted Signing), ~$9.99/month: Microsoft-managed short-lived certs (rotated daily — you never possess them), no hardware token, CI-native (GitHub Actions). Identity validation required (individual: government ID, 1–3 days; organization: business docs, 3–5 days). **Public Trust** profile type is what affects SmartScreen; Private Trust is internal-only.
- **Reputation still accumulates:** even signed binaries show "Windows protected your PC / unrecognized app" until download volume + clean installs build reputation (weeks, hundreds of installs). Reputation binds to the **publisher identity** — same identity across versions inherits trust faster. The only zero-warning path is the **Microsoft Store** (Microsoft re-signs).
- **Tauri wiring:** `bundle.windows.signCommand` (e.g., via `relic` against Azure Key Vault, or Artifact Signing) — runs at `tauri build` time. This is **separate** from the minisign updater signing: minisign = "this update came from us" (app-level), Authenticode/Artifact Signing = "Windows trusts this publisher" (OS-level). You need both.
- **Unsigned (today's v1 reality):** SmartScreen "Unknown publisher" → user must click "Run anyway". This is the warning Owais's users will hit on the first installer — the chat/onboarding must say it plainly before they do.

**Official docs:** Tauri v2 "Windows Code Signing" guide (v2.tauri.app/distribute/sign/windows); Microsoft Learn "SmartScreen reputation for Windows app developers"; electron-builder auto-update docs; Electron `autoUpdater` API docs.

**Limitations/trade-offs:** Artifact Signing = new Azure dependency + identity validation hoop + monthly cost; reputation lag is unavoidable for a new publisher (no instant-whitelist form exists); MSIX/Store distribution kills warnings but adds Store policy constraints.

**Security implications:** Unsigned auto-update = RCE-by-design (this is R10's "unsigned LLM-triggerable git pull" class). Minisign verification + HTTPS-only endpoints + pinned public key are all mandatory, not optional. CI secrets holding the signing key need the same protection as any production credential.

**Common failure modes:** "Signature verification failed" (pubkey/privkey mismatch after rotation); update applied but app won't start (no rollback → bricked install — hence R10); SmartScreen blocking the updater's downloaded installer; NSIS/MSIC install-mode flags wrong (update installs interactively at 3am); GitHub Releases rate-limiting the update check.

**Confidence: 90% [HC]** on mechanisms (official docs + practitioner write-ups converge); 85% on the signing/reputation details (Microsoft's docs are explicit; the "EV no longer bypasses" change is documented).

**Unknown:** Actual reputation-build timeline for a brand-new publisher identity — "weeks and hundreds of installs" is the documented shape, not a measured number for JARVIS.

---

## Cross-topic connections (the file's own §3)

- **Streaming ↔ approval UX:** the STOP button (streaming) and the circuit breaker (consent research) are the same instinct — the user can always grab control back. Both must be *guaranteed*, not decorative.
- **Tauri capabilities ↔ approval UX ↔ SEC5:** the permission model is one system with three faces — the ACL declares it, the approval card explains it, Deno's deny-by-default justifies it.
- **Sidecar ↔ SEC2:** the Python brain on localhost inherits the localhost-hijack requirements (bind 127.0.0.1, authenticate loopback, template integrity) regardless of shell framework.
- **Auto-update ↔ R10:** signed updates + rollback is an architecture requirement, not a nice-to-have — the updater is a remote-code-execution channel by definition.
- **Voice UI ↔ V1/V8:** the web mic button is the visible tip of the voice stage graph; its states must mirror pipeline states (listening → transcribing → speaking), never invent their own.

## What remains unknown (consolidated)

1. Vercel AI SDK vs hand-rolled SSE/WS client for the local brain — spike both, measure.
2. VAD tuning for Hinglish conversational speech on real hardware.
3. Owais's personal rubber-stamping threshold — observed, not theorized.
4. Tauri + PyInstaller sidecar + auto-update end-to-end on Windows — needs a spike build.
5. SmartScreen reputation timeline for a new publisher identity.
6. Hotkey set that avoids collisions on a real Windows machine.

*Notes written 2026-10-19. Confidence tags: [VC] >95% · [HC] 80–95% · [MC] 60–80%. Per-file: §1 85% · §2 90% · §3 88% · §4 90%/80% · §5 88% · §6 90%/85%.*
