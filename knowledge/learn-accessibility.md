# Accessibility — Scoped Study for the JARVIS Tauri UI (LIFETIME DIRECTIVE gap research)

*Learning only. Written 2026-10-19. Genuine gap: the lifetime ledger records "accessibility missing" under Human factors. Approval-UX and zero-terminal requirements were referenced, not re-taught.*

## 0. Purpose — why this matters for JARVIS specifically

Owais's own requirements are already accessibility requirements wearing different clothes:
- **Zero terminal, GUI-first** → operability for non-technical users (WCAG Operable)
- **Plain simple English, no hardcore jargon** → cognitive accessibility (WCAG Understandable, 3.1)
- **One-tap decisions, 30s undo buffer** → error prevention for cognitive disabilities (WCAG 3.3.4 / 3.3.6)
- **Voice-first** → already the most accessible input modality for visual/motor impairments

The gap: nobody has translated these instincts into a **checklist the UI build can be tested against**. That's this file. [HC]

## 1. WCAG 2.2 essentials — distilled for a Tauri desktop app

WCAG 2.2 is the current W3C Recommendation (published Oct 2023; backward compatible — 2.2 AA implies 2.1/2.0 AA) [VC]. Its 4 principles (POUR) map to concrete Tauri/WebView2 obligations:

### Perceivable
- **Contrast: 4.5:1 for normal text, 3:1 for large text** (1.4.3). UI components and focus indicators need 3:1 against adjacent colors (1.4.11) [VC]. JARVIS's dark HUD theme must be checked with a contrast tool, not eyeballed — the arc-reactor blue-on-dark aesthetic is exactly where contrast fails.
- **Text scaling:** content must remain usable at 200% zoom without clipping or overlap (1.4.4, 1.4.10, 1.4.12) [VC]. No fixed-height containers in the chat UI that clip reflowed text.
- **Reduced motion:** the listening waveform/pulse animation must respect `prefers-reduced-motion` — a static state indicator for users who set it (2.3.3, WCAG 2.2 AA) [HC]. This is a real JARVIS risk: a pulsing "listening" ring is the brand, and it can trigger vestibular issues.
- **Audio-only output is not enough:** every TTS response needs a visible text equivalent in the chat log (1.2.x applied by analogy) [HC]. The streaming chat UI already satisfies this if TTS always mirrors to text.

### Operable
- **Everything keyboard-operable** (2.1.1) [VC]: mic button, approval dialogs, settings, composer. No keyboard traps (2.1.2).
- **Visible focus** (2.4.7, plus 2.2's 2.4.11 Focus Appearance and 2.4.13 Focus Not Obscured): focus must be visible AND not hidden behind sticky headers/overlays [HC]. The HUD overlay must never cover the focused element.
- **No time pressure:** approval dialogs must not auto-expire on a countdown (2.2.1 Timing Adjustable) [VC]. The existing design (no expiry, calm status) already complies — do not add "auto-approve in 10s" later.
- **Target size:** 24×24 CSS px minimum for interactive targets (2.5.8, new in 2.2) [VC]. Approval Approve/Reject buttons must be thumb-tappable.
- **No seizure-risk flashing:** nothing flashing >3×/second (2.3.1) [VC].

### Understandable
- **Plain language** (3.1.5, AAA but the spirit): reading level ≤ lower-secondary where possible. Owais's requirement already exceeds this [HC].
- **Error guidance:** errors say what went wrong AND how to fix it, in plain language (3.3.1, 3.3.3) [VC]. "Microphone unavailable" → "Plug in a mic or click to type instead" — not an error code.
- **Consistent navigation and help** (3.2.3, 3.2.6): settings always in the same place; help reachable the same way everywhere [HC].

### Robust
- **Semantic HTML + ARIA:** use native `<button>`, `<input>`, landmarks first; ARIA only where native falls short (4.1.2 Name, Role, Value) [VC].
- **Status messages announced:** toasts/notifications use `role="status"` or `aria-live` so screen readers announce them (4.1.3) [HC]. The streaming chat's token stream should NOT be live-announced per token (chaos) — announce on message completion.

**Key meta-fact:** WCAG 2.2 added 9 success criteria and removed 4.1.1 Parsing. Of the new criteria, axe-core automates only 2.5.8 Target Size (Minimum) — automation alone cannot reach conformance [HC, per Deque/testmuai reporting].

## 2. Windows accessibility APIs — the symmetric insight

**The big one for JARVIS:** the UI Automation (UIA) tree that JARVIS *reads* to control the computer is the **same tree screen readers read** to narrate the computer [VC]. This is symmetric:

1. **JARVIS reads UIA** (computer use) — already the north star (tree-first, pixels as fallback).
2. **JARVIS must EXPOSE a clean UIA tree** (its own UI) — every button needs an accessible name, every control a correct role/state.

How it works in Tauri: on Windows, Tauri renders in **WebView2**, and Microsoft's docs state: *"By default, WebView2 will show up in the accessibility tree as a child of the parent HWND"* [VC, learn.microsoft.com WebView2 API overview]. Inside that node, Chromium exposes the full web accessibility tree (HTML semantics → UIA providers), which NVDA and other screen readers consume. So the practical rule is:

- **Web accessibility IS desktop accessibility here.** Semantic HTML + ARIA in the Tauri frontend flows through WebView2 → UIA → NVDA with no extra native code [HC].
- **What must be explicit:** every interactive element gets a name (visible label or `aria-label`), a role (prefer native elements), and a state (`aria-pressed` on the mic toggle, `aria-expanded` on menus, `disabled` on Approve during execution) [HC].
- **The native shell (tray icon, window chrome) is outside WebView2** — tray tooltip text and notification content are the accessible surface there; Win11 hides tray icons in overflow, which is itself an operability gap to document in onboarding (already noted in learn-frontend.md) [HC].
- **Verify at build time:** WebView2 version variance affects a11y fidelity; pin and test the runtime version (Evergreen updates can shift behavior) [MC].

## 3. Voice-first accessibility — the double edge

### Where voice is the accessibility feature
- **Visual impairments:** voice input/output replaces the screen entirely. Screen-reader market penetration is ~10%, but only ~39% of smart-home devices are compatible with such tech (reported figures [MC]) — JARVIS's chat log gives screen readers a text surface voice alone can't.
- **Motor impairments:** hands-free operation removes keyboard/mouse dependence (WCAG 2.5 Input Modalities explicitly includes voice control) [HC].

### Where voice creates NEW barriers (the design must cover these)
- **Speech impairments:** ~5% of the global population has a speech disorder (reported [MC]). Faster-whisper must not be the only input path — **the text composer is the fallback, always visible, never hidden behind voice-first branding** [HC].
- **Deaf / hard of hearing:** 460M+ people have disabling hearing loss (reported [MC]). **No audio-only signals, ever:** wake confirmation, approval requests, and error states all need visual (and where relevant, text) equivalents. A TTS-only "done" is a barrier [HC].
- **Noisy environments (situational disability):** the same logic — voice fails in a café; the GUI must be a full peer, not a companion [HC].
- **Research direction:** an arXiv study on DHH access to intelligent assistants found LLM-powered *touch* interfaces a promising complement to voice, with the key takeaway that input options must be flexible and multimodal (arxiv.org/html/2601.15209v2) [HC]. JARVIS's text-first core (R1) is already this architecture: **voice is a plugin over a text brain, so every modality degrades to text, never to nothing**.

**Design rule:** shared state between voice and GUI (one UI control's state depends on the other's) — while VUI gives auditory feedback, the GUI supplements with visual cues [HC, accessibility.com]. The approval dialog is the canonical case: spoken request + on-screen Approve/Reject with visible payload.

## 4. Cognitive accessibility — what we already do, what to add

**Already serving it (from existing decisions):**
- Plain simple English (Owais's standing requirement) → WCAG 3.1 readable [HC]
- One-tap Approve/Reject with visible payload → reduces decision load [HC]
- 30-second undo buffer → error recovery without panic (WCAG 3.3.4/3.3.6 spirit) [HC]
- No time-pressure dialogs → 2.2.1 Timing Adjustable [HC]
- Consistent layout, predictable behavior → 3.2 predictable [HC]

**To add:**
- **Error messages in plain language with a fix path** (3.3.1/3.3.3): every failure state the HUD shows gets the "what happened + what to do" format. Never a stack trace or error code to a non-technical user [HC].
- **Redundant entry (3.3.7, WCAG 2.2):** don't make the user re-enter information they already gave in the same session (e.g., re-typing a path after a failed action) [MC].
- **No memory/auth puzzles (3.3.8/3.3.9 Accessible Authentication):** if JARVIS ever gates on authentication, don't require solving puzzles or recalling secrets unaided — use the OS keyring + biometrics path [HC].
- **Chunked instructions:** multi-step plans shown as a short numbered list with progress, not a paragraph (cognitive load) [HC].
- **Consistent help (3.2.6):** the "how do I…" entry point in the same place on every screen [MC].

Cognitive accessibility is one of the highest-leverage investments — plain language helps non-native speakers, stressed readers, and everyone scanning quickly [HC, exceedability.com].

## 5. Testing accessibility — what CI can and can't do

**The honest split (Deque 2021, 2,000+ audits):** automated testing catches ~57% of issues **by volume**; by success-criterion coverage it's much lower because common issues inflate the figure [HC, testmuai.medium.com]. Automation alone will not reach WCAG 2.2 AA.

**Layer 1 — CI (automated, every PR):**
- **axe-core** (the engine behind most tools; very few false positives) via Playwright against the Tauri frontend in a test harness, or `vitest-axe`/`jest-axe` at component level [HC]. Catches: missing labels, contrast failures, target size (2.5.8), invalid ARIA.
- **Lighthouse** accessibility score as a smoke signal, not a verdict [MC].
- **Keyboard trap scan:** scripted Tab-order walk asserting focus never leaves the document unexpectedly [MC].

**Layer 2 — manual (before release):**
- **NVDA (free, Windows)** — complete the two core flows (ask a question by voice AND by text; approve a consequential action) with the screen reader on. If you get lost, users get lost [HC].
- **Keyboard-only pass:** unplug the mouse. Reach everything, see focus, operate dialogs, escape them [HC].
- **Microsoft Accessibility Insights** (free, MSFT): guided assessments including Tab-stop visualization — purpose-built for Windows apps [HC].
- **200% zoom + text-spacing overrides:** layout must survive (1.4.4, 1.4.12) [HC].

**Layer 3 — scheduled:** re-scans between releases catch regressions from content/third-party updates [MC].

**Notable 2026 development:** Vercel's agent-browser ships an embedded axe-core audit command, and BlindPilot v0.43.3 is a screen-reader-first desktop front end for coding agents (NVDA/JAWS/VoiceOver) — evidence that agent UIs are starting to treat the accessibility tree as first-class [MC, aiagentstore.ai].

## 6. Unknowns / needs measurement or prototyping

1. **[UK]** WebView2/Evergreen version variance in UIA fidelity — needs a test pass on the pinned runtime with NVDA before any conformance claim.
2. **[UK]** `prefers-reduced-motion` behavior inside WebView2 on Windows — verify the media query propagates from OS settings.
3. **[UK]** OS text-scaling (Settings → Accessibility → Text size) effect on WebView2 rendering — verify chat layout survives 200%+.
4. **[MC]** faster-whisper accuracy on atypical speech — the text-fallback design assumes the fallback is sufficient; untested with real speech-impaired users.
5. **[MC]** Exact axe-core rule coverage for the Tauri test harness (Playwright-in-WebView2 vs real window) — prototype needed.

## 7. Connections to existing knowledge

- **learn-frontend.md:** approval UX (one-tap, visible payload, undo buffer), mic button states (visual + text label), Tauri vs Electron verdict, tray-in-overflow onboarding note. This file extends those into a testable standard.
- **learn-multimodal.md:** UIA tree as perception backbone (pywinauto/uiautomation, Inspect.exe, Accessibility Insights) — the same tree is JARVIS's *output* accessibility surface (Section 2).
- **R1 (text-first core):** the architectural reason voice degrades gracefully — every modality bottoms out at text.
- **R3 (confirmation gates):** approval dialogs are the highest-stakes accessibility surface (cognitive + motor + visual) — they get the strictest checklist: keyboard-reachable, screen-reader-announced, no timeout, 24px+ targets, plain-language payload.
- **Zero-terminal requirement:** already an operability win; extend to "zero *precise-pointer* requirement" (all actions keyboard- and target-size-safe).

## References (verbatim, from live search — no fabricated citations)

- https://accesstive.com/blog/wcag-2-2-checklist/
- https://www.xsibility.com/compliance/wcag-2-2.html
- https://accesstive.com/blog/wcag-level-aa-guidelines/
- https://www.forgesdlc.com/disciplines-product-ux-design-accessibility-wcag-guide.html
- https://www.kozite.com/wcag-guide.html
- https://learn.microsoft.com/uk-ua/microsoft-edge/webview2/concepts/overview-features-apis (WebView2 in accessibility tree as child of parent HWND)
- https://www.accessibility.com/blog/some-considerations-for-accessible-voice-user-interfaces
- https://beaccessible.com/post/website-accessibility-for-speech-disabilities/
- https://arxiv.org/html/2601.15209v2/ (DHH access to intelligent personal assistants)
- https://testmuai.medium.com/wcag-2-2-testing-checklist-for-2026-what-automated-a11y-scanners-catch-what-they-miss-and-how-to-43e19e780ffa
- https://www.xsibility.com/guides/free-accessibility-testing-tools.html
- https://practices.mightyacorn.com/practices/engineering/accessibility-testing
- https://aiagentstore.ai/ai-agent-news/topic/accessibility-inclusion (BlindPilot, Vercel agent-browser axe-core)
- https://exceedability.com/cognitive-disabilities.html (cognitive criteria mapping)
- https://www.interaction-design.org/literature/topics/web-content-accessibility-guidelines

## Completion report (Rule 12)

- **Researched:** WCAG 2.2 essentials, WebView2/UIA accessibility, voice-first accessibility barriers, cognitive accessibility, automated + manual testing — all via live web search.
- **Validated:** WCAG 2.2 status/contrast/keyboard criteria against multiple sources; WebView2 UIA behavior against Microsoft docs; the 57% automation figure attributed to its source.
- **Saved:** this file, `~/workspace/jarvis-knowledge/learn-accessibility.md`.
- **Modified / tested / measured:** none (learning only, per task).
- **Incomplete:** the five unknowns in Section 6 need prototyping on the real Tauri build — flagged, not claimed.
- **Blocked:** nothing — all sources publicly accessible.
