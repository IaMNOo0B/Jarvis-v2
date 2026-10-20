# Mega-Scan Team 23, Slice B — Screen Readers & Accessibility Automation

Scope: 13 target repos. Outcome: **11 cloned and deep-read in source, 1 cloned via sparse/blobless checkout after full-clone failures (NVDA, espeak-ng, WCAG = 3 sparse), 1 renamed upstream and cloned under its successor name (Android ATF).** Clone failures are stated per-repo, never papered over. Tag key: [CODE] read in cloned source · [README] project's own claim · [SEARCH] search metadata · [INFERENCE] my synthesis.

> **License warning up front:** NVDA is **GPL-2.0** — for JARVIS v2 it is **IDEAS ONLY, no code may be lifted**. Same ideas-only posture for Orca (LGPL-2.1), speech-dispatcher server (GPL), eSpeak NG (GPL-3.0), RHVoice (GPL-2.0), pa11y (LGPL-3.0). Code-liftable (with attribution/conditions): guidepup (MIT), Android ATF (Apache-2.0), Accessibility Insights for Windows (MIT), axe-core (MPL-2.0, file-level copyleft — reuse isolated files only with MPL obligations).

---

## deep-read repos

### 1. nvaccess/nvda — NVDA (TOP priority) ✅ sparse blobless clone of `source/` after full clone timed out at 120 s

**What it is:** The free Windows screen reader. Python core over COM accessibility backends (UIA, IAccessible/IA2, Java Access Bridge) with per-app modules, a virtual "browse mode" buffer for documents, pluggable synth/braille drivers, and an add-on system. [CODE]

**Speech/UI mechanism from code:**
- **Speech is a typed sequence, not a string.** `source/speech/types.py`: `SpeechSequence = list[str | SpeechCommand]` — commands (LangChange, Index, rate/pitch `SynthParamCommand`, EndUtterance, profile triggers) travel inline with text. [CODE]
- **Three priorities, per-priority queues, preempt-and-resume.** `source/speech/priorities.py`: `SpeechPriority.NORMAL=0, NEXT=1, NOW=2` (mirrored in the NVDAController RPC IDL). [CODE] `source/speech/manager.py` `SpeechManager`: one `_ManagerPriorityQueue` per priority, each storing `pendingSequences` **plus the state needed to resume after preemption** (`enteredProfileTriggers`, a `ParamChangeTracker` of non-default synth params). Flow (class docstring, steps 1–15): sequences are normalized/split at IndexCommands and EndUtteranceCommands → queued per priority → `_pushNextSpeech` always serves the highest non-empty queue → a **first** sequence at `NOW` calls `getSynth().cancel()` and interrupts; interrupted lower-priority speech later **resumes with its changed parameters re-applied**. Index callbacks (cycling 1…9999, deliberately not reused quickly to avoid cancel races) tell the manager exactly which fragment finished. [CODE]
- **Expired-speech cancellation:** config feature flag `cancelExpiredFocusSpeech` — stale focus announcements can be dropped instead of spoken late. [CODE]
- **UI tree → speech:** events (`executeEvent`) → `NVDAObject` per backend; `UIAHandler/__init__.py` runs UIA on a dedicated **MTA COM thread**, creates `RawViewWalker` + condition-based `createTreeWalker` walkers, and caches elements; document content is flattened by `virtualBuffers/` + `browseMode.py` tree interceptors into a linear `TextInfo` stream that `speech.speakTextInfo` / `sayAll.py` (cursor-walking `_Reader.walk()` over objects) renders sequentially — i.e. the tree becomes a *navigable text buffer first, speech second*. [CODE]
- **Automation hooks:** the controller-client RPC interface (priority enum's counterpart in `nvdaController.idl` — external apps can make NVDA speak/braille and test whether it is running); add-ons/appModules in Python; a remote client (`source/_remoteClient/`) — the channel Guidepup plugs into. [CODE]

**Graceful failure from code:** a `silence` synth driver (`synthDrivers/silence.py`, `check()` always true) is the guaranteed-available fallback output; drivers self-report availability via `check()`; `executeEvent` wraps handling in try/except and drops events for objects below the lock screen; bad speech-sequence types are type-checked and logged (optionally raised in debug) instead of crashing the synth (`types.logBadSequenceTypes`). [CODE]

**License:** GPL-2.0-or-later with two stated exceptions (`copying.txt`). [CODE] **IDEAS ONLY for v2.**

**Steal verdict:** Implement NVDA's exact speech semantics in **`jarvis/tts.py` + `jarvis/voice_loop.py`**: (1) 3-level priority (NORMAL/NEXT/NOW) with **per-priority queues**; (2) NOW preempts via synth cancel, and the preempted utterance **resumes** (store its remaining text + voice params — the ParamChangeTracker idea); (3) index/fragment callbacks so "what was actually spoken" is known when barge-in truncates history; (4) drop-expired: focus/status utterances queued >N ms are discarded, not spoken late. This is the direct cure for v2's known echo/barge-in failure family. For **`jarvis/pc_control.py`**: copy the UIA discipline — dedicated MTA thread, RawView vs ControlView walkers chosen per query, element caching, and "act only on elements from the last tree snapshot."

### 2. GNOME/orca — Orca ✅ full clone (GitHub mirror of GNOME's Linux reader)

**What it is:** GNOME's screen reader (Python, AT-SPI2). Recently refactored into *presenters* (speech, braille, chat, document, flat-review…), a `speech_generator`, a `speech_manager`, and pluggable speech servers — Speech Dispatcher is the default backend. [CODE]

**Speech/UI mechanism from code:**
- **Event PriorityQueue with obsolescence.** `src/orca/event_manager.py`: AT-SPI events enter a `queue.PriorityQueue[tuple[EventPriority, int, Atspi.Event]]`. `_get_priority` maps event types to levels — window activation / active dialog = HIGHEST, focused-state = HIGH, children-changed = LOW; live-region text inserts inherit the region's politeness (`container-live=assertive` → HIGHEST, `polite` → HIGH). `_is_obsoleted_by` **deletes queued events that a newer event for the same source renders worthless** — the queue actively forgets stale work. [CODE]
- **Presentation is generated, then dispatched:** `speech_generator.py` builds utterance strings (role/name/state/position templates) per object+script; per-app/per-toolkit scripts under `src/orca/scripts/` (apps, toolkits, web, terminal, `default.py`) override what an event should say/do; `speechdispatcherfactory.SpeechServer.speak()` handles chars vs strings specially (single char → `client.char`, capitalization icon handling) and `say_all` is deferred via `GLib.idle_add` with a progress callback. [CODE]
- **Server abstraction:** `speechserver.SpeechServer` factory (`get_speech_server`, `shutdown_active_servers`, VoiceFamily/ACSS voice descriptions) — Orca treats the TTS backend as replaceable middleware. [CODE]

**Graceful failure from code:** voice-family enumeration wraps the dispatcher call in try/except and logs a warning token stream, returning what it has (`list_synthesis_voices failed` path); every subsystem logs via tokenized debug instead of raising into the event loop; `event_manager.deactivate()` swaps in a fresh empty queue rather than draining a poisoned one. [CODE]

**License:** LGPL-2.1 (`COPYING`). [CODE] **IDEAS ONLY for v2.**

**Steal verdict:** Steal the **event-priority + obsolescence model** for `jarvis/pc_control.py`'s UIA event watcher and for `jarvis/voice_loop.py`'s announcement path: when JARVIS watches the screen, a newer focus/window event must *delete* the queued narration of the older one (this is the proactive-watcher's anti-babble mechanism). Also steal presenter separation: one module decides *what to say* about a UI element (generator), another *how/when to say it* (queue) — v2 currently risks tangling both in the voice loop.

### 3. dequelabs/axe-core ✅ full clone (first attempt timed out; retry succeeded)

**What it is:** The web accessibility testing engine (JS) that powers axe DevTools and pa11y's default runner. [README]/[CODE]

**Speech/UI mechanism (rule-engine mechanism) from code:**
- **Rules are data, checks are functions.** `lib/rules/button-name.json`: `{id, impact:"critical", selector:"button", matches:"no-explicit-name-required-matches", tags:["wcag2a","wcag412","section508","EN-301-549","ACT",…], actIds:[…], all:[], any:["button-has-visible-text","aria-label","aria-labelledby","non-empty-title",…], none:[]}` — a rule = a CSS selector + an optional `matches` filter + three check lists with boolean algebra: **all must pass, any must pass (≥1), none may pass**. [CODE]
- **Checks are `*-evaluate.js` functions** (e.g. `lib/checks/navigation/heading-order-evaluate.js`) run against a virtual-DOM snapshot (`axe._tree`), using shared `commons/` (dom/aria/text) helpers and a per-run `cache`; a check returns true/false/**undefined**, and undefined propagates as **"incomplete — needs manual review"** rather than pass/fail. `this.data({...})` attaches structured evidence to the result. [CODE]
- Rule metadata carries impact (minor→critical) and standards tags, so the same run can be filtered by WCAG level, EN 301 549, Section 508 or ACT rule id. [CODE]

**Graceful failure from code:** the three-valued result (pass / violation / **incomplete**) is the graceful failure: when axe cannot decide programmatically (e.g. color contrast over an image), it refuses to guess and files the node under incomplete with the data it did gather. [CODE]/[INFERENCE]

**License:** MPL-2.0 (`package.json` `"license": "MPL-2.0"`). [CODE] Isolated files may be reused under MPL-2.0 obligations; the *pattern* is free.

**Steal verdict:** Build v2's **`pc_control.py` UI-sanity checker** (and any future HUD a11y self-test) as axe-shaped data: a JSON rule = `{uia_selector (ControlType/Name pattern), all/any/none: [check-ids], impact, wcag_tag}` + tiny Python check functions returning `True/False/None`, where `None` = "ask the vision model / tell the user it needs eyes." Never let a checker guess: three-valued results keep JARVIS honest about what the UIA tree did not prove.

### 4. microsoft/accessibility-insights-windows ✅ full clone

**What it is:** Microsoft's Windows a11y inspection/testing tool (C#/.NET): live UIA-tree Inspect (hover-highlight, properties, patterns), FastPass (automated checks + Tab-stop visualization), and guided Assessments. [README]

**Speech/UI mechanism from code:** this repo is the **UX shell** — `src/` is organized as `AccessibilityInsights` (main app), `SharedUx`, `Win32`, `Extensions.*` (GitHub/Azure DevOps issue-filing, telemetry, auto-update) with the actual scan engine consumed as an external component (the Axe.Windows engine lives outside this repo; no rule engine source is in this tree). [CODE] The transferable design visible in code: extensions are first-class (issue-filing/telemetry are separate assemblies behind interfaces), and the tree view is property/pattern-centric — every element is shown as (ControlType, Name, BoundingRectangle, supported **UIA Patterns**). [CODE]/[INFERENCE]

**Graceful failure from code:** not deep-read for the engine (absent by design, see above); the app isolates failures per-extension so a broken telemetry/issue extension cannot take down inspection. [INFERENCE from assembly layout]

**License:** MIT (`license.txt`, © Microsoft). [CODE] Code liftable with attribution (but it's C# — patterns, not files, are what v2 takes).

**Steal verdict:** For `jarvis/pc_control.py`: adopt its Inspect mental model as JARVIS's own debug/verify view — when an action fails, report the target as **(ControlType, Name, Rect, Patterns)** and re-snapshot, not "click didn't work." Pattern-first acting (Invoke/Value/ExpandCollapse…) over coordinates is exactly AI-Windows' inspect assumption and NVDA's practice.

### 5. brailcom/speechd — Speech Dispatcher ✅ full clone (first attempt timed out; retry succeeded)

**What it is:** The Unix TTS middleware daemon: one server multiplexing many clients (Orca etc.) onto many synth modules over the SSIP text protocol. [CODE]

**Speech/UI mechanism from code:**
- **SSIP protocol** (`doc/ssip.texi`, `src/server/parse.c`): line commands `SPEAK` (block input until `.`), `SET … PRIORITY`, `STOP`, `CANCEL`, `PAUSE/RESUME`, `SOUND_ICON`, history commands; the server parses with per-command block-allowed flags and drives output modules via `src/server/output.c`'s output queue events (`SPEAK_QUEUE_QET_BEGIN`…). [CODE]
- **The 5-priority model — the most complete written semantics in this slice** (`ssip.texi`, Priority Categories): `important` (speaks now, cancels whatever is playing, never interrupted itself, FIFO among peers; lower `message`/`text` are *postponed*, `notification`/`progress` are *canceled*), `message` (waits for important/message; cancels notification/progress/text), `text` (**interrupts itself — only the latest text message survives**), `notification` (canceled by almost anything; only latest survives), `progress` (like notification but rate-shaped so "Completed 45 %" bursts collapse instead of spamming). [CODE]

**Graceful failure from code:** priorities *are* the failure policy for overload — speech faster than synthesis is resolved by cancel/postpone rules per category instead of an ever-growing queue; clients are isolated so one client's STOP/CANCEL targets only its own messages. [CODE]

**License:** mixed — `COPYING.GPL-2`, `COPYING.GPL-3`, `COPYING.LGPL` (server GPL, client libs LGPL). [CODE] **IDEAS ONLY for v2** (protocol semantics are the steal, not code).

**Steal verdict:** This is the **priority taxonomy for `jarvis/tts.py`**. NVDA gives the queue mechanics; speech-dispatcher gives the *vocabulary* v2 should expose to the brain: `important` (urgent alerts — speak now, never queued behind chatter), `message` (normal answers), `text` (live narration/screen-watching — **self-interrupting, latest-wins**), `notification` (status ticks — cancelable by anything), `progress` (download/build % — throttled collapse). JARVIS's call-ringing interruption budget maps 1:1: ring = notification, picked-up briefing = message, urgent = important.

### 6. espeak-ng/espeak-ng ✅ sparse clone of `src/` + COPYING (two full-clone attempts died with `fetch-pack: unexpected disconnect`)

**What it is:** The compact formant TTS engine NVDA bundles by default; C library with a command FIFO and both synchronous and asynchronous audio-output modes. [CODE]

**Speech/UI mechanism from code:** `src/libespeak-ng/espeak_api.c`: `espeak_Initialize(output_type, buf_length, …)` selects `AUDIO_OUTPUT_PLAYBACK / RETRIEVAL / SYNCHRONOUS`; `speech.c` runs a **FIFO command queue** (`fifo_add_command(s)`, `fifo_is_command_enabled()`) feeding `synthesize.c`, and emits **events** (word/ sentence boundaries, end-of-utterance) back to the host — which is precisely how NVDA's `_espeak` driver gets index callbacks for its speech manager. [CODE] Synthesis itself is rule/dictionary-driven per language (`dictionary.c`, `compiledata.c`) — tiny footprint, no model files, deterministic latency. [CODE]

**Graceful failure from code:** retrieval/synchronous modes let a host that loses audio fall back to generating WAV without a device; the FIFO accepts cancel/flush as commands in-band rather than killing the synth thread. [CODE]/[INFERENCE]

**License:** GPL-3.0 (`COPYING`). [CODE] **IDEAS ONLY** (v2 already treats eSpeak-class engines as external binaries via Piper-style adapters — keep it that way).

**Steal verdict:** One mechanism for `jarvis/tts.py`: **boundary events are non-negotiable** — whichever engine v2 drives (Piper/Kokoro/cloud), wrap it so it emits word/end indexes like eSpeak's event stream; without indexes there is no correct barge-in truncation and no "record what was actually spoken." Also: keep a zero-dependency fallback voice (Piper/eSpeak-class) so speech never hard-depends on the network.

### 7. RHVoice/RHVoice ✅ full clone

**What it is:** Free multilingual TTS (HTS-based voices, many languages incl. Slavic/Georgian/Esperanto) shipping as a library, a Speech Dispatcher module, a SAPI voice, and an NVDA add-on from **one core**. [CODE]

**Speech/UI mechanism from code:** `src/core/` separates *language processing* (per-language `.cpp`: english, georgian, brazilian_portuguese…, plus `emoji.cpp`, FST/dtree components) from the *engine* (`engine.cpp`, HTS label/vocoder wrappers) and from *documents*: `document.cpp` parses input (incl. SSML — `RHVoice_message_ssml` in `include/RHVoice.h`) into an internal document before synthesis. Delivery adapters are thin: `src/lib/lib.cpp` (C API), `src/sd_module/`, `src/sapi/`, `src/nvda-addon/synthDriver/`. [CODE]

**Graceful failure from code:** not singled out in the core; the resilience story is architectural — if one front-end (SAPI/NVDA/SD) dies, the engine and the other front-ends are unaffected, and language data is data-only (`data_only_language.cpp`) so a missing voice degrades to another language pack rather than a crash. [CODE]/[INFERENCE]

**License:** GPL-2.0 (`LICENSE.md`) for the project overall, with some components under other free licenses in `licenses/`. [CODE] **IDEAS ONLY.**

**Steal verdict:** Mirror the **one-engine/many-thin-adapters** split in `jarvis/tts.py`: a single `speak(sequence, priority)` core, with adapters (local Piper, cloud, Telegram voice-note file) as replaceable shells — never let a provider's API shape leak into the voice loop. The document-first step (parse SSML-ish markup → internal doc → synth) is also how v2 should handle Hinglish code-switch text: normalize once, centrally.

### 8. guidepup/guidepup ✅ full clone

**What it is:** MIT TypeScript library for **screen-reader-driven test automation**: one `IScreenReader` interface implemented over NVDA (Windows), VoiceOver (macOS), so tests can drive a real reader and assert on what it *said*. [CODE]

**Speech/UI mechanism from code:**
- `src/IScreenReader.ts`: the contract — `detect()/default()/start()/stop()`, cursor movement (`next/previous`, heading/link/form variants), `act()`, and crucially **`lastSpokenPhrase()` / `spokenPhraseLog()`** as first-class outputs. [CODE]
- Windows NVDA driver (`src/windows/NVDA/NVDAClient.ts`): connects over a **TLS socket** to an NVDA add-on channel, joins as `connection_type:"master"`, negotiates `protocol_version:2`, and receives `{type:"speak", sequence:string[], priority:number}` and `{type:"cancel"}` messages — with production-hardened timing: `POLL_INTERVAL=500`, `MAX_CONSECUTIVE_CONNECTION_FAILURES=20`, `CANCEL_DEBOUNCE_TIMEOUT=250`, `SPEAK_DEBOUNCE_TIMEOUT=1000`. Capture defaults to `"initial"` so a test doesn't drown in the reader's startup chatter. [CODE]
- macOS side drives VoiceOver via AppleScript with `retryIfAppleEventTimeout` wrappers. [CODE]

**Graceful failure from code:** named errors (`ERR_NVDA_CANNOT_CONNECT / NOT_INSTALLED / NOT_RUNNING`), bounded retries (20 consecutive failures then give up), and debounce windows that treat a cancel followed instantly by speech as one event — failure is *classified*, not retried forever. [CODE]

**License:** MIT. [CODE] **Code may be lifted with attribution** (TS — port the constants/semantics to Python).

**Steal verdict:** Two steals for v2: (1) **A spoken-phrase log as a testable artifact** — `jarvis/voice_loop.py` should keep `spoken_phrase_log()` exactly like Guidepup's, so v2's own UI actions can be verified by "what JARVIS announced" in tests, and truncation-on-interrupt has a ground truth. (2) The **debounce constants pattern** for `jarvis/tts.py` interruption: a cancel that is followed by new speech within ~250 ms is a *replacement*, not a stop — this kills the flicker where barge-in permanently mutes output.

### 9. google/android-accessibility-test-framework ✅ cloned under successor name (original `google/android-accessibility-test-framework` returns 404/auth prompt — repo renamed to `google/Accessibility-Test-Framework-for-Android`)

**What it is:** Google's Android a11y checker library (Java, Apache-2.0) — the engine behind Accessibility Scanner / Espresso a11y checks. [CODE]

**Speech/UI mechanism from code:** Same rule/check DNA as axe-core, one level more formal: `AccessibilityHierarchyCheck` (abstract) operates over a view-hierarchy snapshot; concrete checks in `checks/` — `SpeakableTextPresentCheck`, `DuplicateSpeakableTextCheck`, `TouchTargetSizeCheck`, `TextContrastCheck`, `ImageContrastCheck`, `TraversalOrderCheck`, `EditableContentDescCheck`, `RedundantDescriptionCheck`, `UnexposedTextCheck`… Results are `AccessibilityHierarchyCheckResult` with `AccessibilityCheckResultType` (ERROR / WARNING / INFO / **RESOLVED** / SUPPRESSED…) and rich metadata (`HashMapResultMetadata`, Question/Answer "ask the user" types for cases a machine cannot settle). Presets (`AccessibilityCheckPreset`) bundle check sets by API level. [CODE]

**Graceful failure from code:** results can be *suppressed* with reason, *resolved*, or escalated to a human Question — the framework models "the app is broken in a way we can't auto-judge" as data, not as a crash or a silent pass. [CODE]

**License:** Apache-2.0. [CODE] Code/patterns liftable with attribution.

**Steal verdict:** For `jarvis/pc_control.py`: name v2's UIA checks after this taxonomy — **speakable-text-present** (element has a Name), **duplicate-speakable-text** (two identical buttons = ambiguous target, ask/disambiguate), **traversal-order** (Tab order sanity before keyboard-driving an app), **touch-target-size → click-target-size** (tiny rect = risky click, prefer Invoke pattern). And copy the result-type enum incl. SUPPRESSED-with-reason for the gate's audit log.

### 10. pa11y/pa11y ✅ full clone

**What it is:** Web a11y testing in CI: drives headless Chrome (Puppeteer), injects a runner (axe-core by default, HTML_CodeSniffer optional), reports issues with exit codes. [CODE]

**Speech/UI mechanism from code:** `lib/pa11y.js` orchestrates state-ful runs with actions (`lib/action.js`: click, wait-for-text, set field, navigate…) executed *before* the audit; `lib/runners/axe.js` resolves the installed `axe-core` package, maps pa11y options → axe `RunOptions` (`runOnly` tags from the chosen standard WCAG2A/AA/AAA, rules allow-list, ignore list), converts axe's selector arrays back to strings, and normalizes results into pa11y's issue shape (code, context, selector, type). Errors are captured into `pa11yError` and returned alongside (possibly partial) results rather than thrown away. [CODE]

**Graceful failure from code:** the run wrapper distinguishes *test ran with issues* from *test could not run*, supports `ignore` lists per rule, and thresholds (`threshold: max errors tolerated`) so CI degrades to a warning budget instead of a binary cliff. [CODE]

**License:** LGPL-3.0-only (`package.json`). [CODE] **IDEAS ONLY.**

**Steal verdict:** For v2's future web/HUD checks (and its self-test skill): the **actions-then-audit** shape — JARVIS should be able to script "open dialog → run UIA checks → report" as one verifiable routine — and the **threshold budget** idea for proactive warnings: don't nag per-issue, report when a budget is crossed (fits the call-ringing interruption model).

### 11. w3c/wcag ✅ sparse clone of `guidelines/` (two full attempts died mid-fetch; spec repo is enormous)

**What it is:** The WCAG specification source — skimmed for **rule taxonomy only**, per brief. [CODE]

**Taxonomy from code:** success criteria live as one HTML file per criterion under `guidelines/sc/{20,21,22}/` (WCAG 2.0/2.1/2.2 layers — e.g. 2.2 adds `focus-not-obscured-minimum`, `target-size-minimum`, `redundant-entry`, `accessible-authentication-minimum`), with `guidelines/act-mapping.json` mapping criteria to ACT rules — the same ACT ids axe-core rules cite. [CODE] Criteria are organized under the four principles (Perceivable, Operable, Understandable, Robust) at conformance levels A/AA/AAA. [README]

**License:** W3C Document License (spec text — taxonomy/terminology use only). 

**Steal verdict:** Use WCAG ids as the **stable vocabulary** for v2's UI-check findings (axe tags already carry them): a `pc_control` finding tagged `wcag412` (Name, Role, Value) means the same thing in JARVIS's log, a test, and a web audit. No code, just names.

### Discovery (GitHub/web search, 2 queries — [SEARCH])

- **FlaUI** (.NET UIA library) and **pywinauto** (Python, Win32+UIA backends) are the standard open-source UIA-automation pair; pywinauto is the obvious Python-side reference for v2's UIA work (BSD). [SEARCH]
- **dogtail** (Linux, AT-SPI) is Orca's ecosystem counterpart for scripted GUI testing. [SEARCH]
- **Community-Access/accessibility-agents** publishes structured desktop-a11y test-coach material (NVDA + Accessibility Insights + pywinauto workflows, rule ids `TST-A11Y-001…010`) — evidence the "checks-as-numbered-rules" pattern is now standard practice. [SEARCH]
- Practitioner consensus from the same results: **tree first, OCR/text next, screenshot last; verify by re-reading the tree after acting.** [SEARCH] — independently confirms v2's UIA-first north star.

---

# Top 5 mechanisms

1. **Per-priority speech queues with preempt-and-resume (NVDA).** Separate queue per priority; first NOW utterance cancels the synth; the interrupted queue keeps its remaining sequences *and* its synth-parameter state so it resumes mid-thought. Index callbacks (non-reused, cycling) mark exactly what finished. [CODE]
2. **Five-category priority semantics with self-interruption rules (Speech Dispatcher/SSIP).** important/message/text/notification/progress differ in *cancel vs postpone vs latest-wins* behavior — text and notification are latest-wins by design, progress collapses bursts. The spec text is a ready-made policy table. [CODE]
3. **Event obsolescence (Orca).** A priority queue of UI events where a newer event for the same source *deletes* stale queued events, and live-region politeness (assertive/polite) sets priority. Proactive narration that forgets is narration that doesn't babble. [CODE]
4. **Rules-as-data + checks-as-functions + three-valued results (axe-core & Android ATF).** Rule JSON (selector, all/any/none, impact, WCAG/ACT tags) × evaluate functions returning pass/fail/**undefined→incomplete** (ATF adds WARNING/SUPPRESSED/RESOLVED and human Questions). Machines never guess; undecidable goes to a human/model with evidence attached. [CODE]
5. **Spoken-output as a capturable, debounced stream (Guidepup + eSpeak events).** The reader's speech is an event stream (`speak{sequence,priority}`, `cancel`) with debounce windows and a persistent phrase log; synths emit boundary indexes. Speech becomes observable, testable, and truncatable — the precondition for correct barge-in. [CODE]

# Top 3 steals (for JARVIS v2)

1. **`jarvis/tts.py` — adopt the SSIP×NVDA speech core (ideas-only sources, original implementation).** Expose `speak(seq, priority)` with the 5 SSIP categories mapped onto 3 NVDA-style queues: important→NOW (cancel + never interrupted), message→NORMAL queue, text/notification/progress→latest-wins slots with progress throttling. Every utterance carries fragment indexes; on interrupt, truncate the *spoken-phrase log* to the last completed index and offer resume for preempted NORMAL speech. **Why:** this single mechanism addresses v2's documented worst bugs — echo-era muting, lost interruptions, stale announcements — with semantics two mature projects already proved.
2. **`jarvis/pc_control.py` — UIA discipline from NVDA + Accessibility Insights.** Dedicated MTA thread for UIA, RawView/ControlView walkers per query type, snapshot-then-act (act only on elements from the latest snapshot, identified by ControlType+Name+Rect+Patterns), pattern-first invocation, and post-action tree re-read to verify. Plus Orca-style event obsolescence for the screen-watcher so proactive speech never narrates a dead focus state. **Why:** it converts pc_control from coordinate hope into verifiable, self-reporting actions.
3. **`jarvis/` (new `a11y_checks` in pc_control or a self-test skill) — axe/ATF-shaped UIA rule pack.** JSON rules over the UIA tree (`speakable-text-present`, `duplicate-speakable-text`, `click-target-size`, `traversal-order`, `name-role-value`/`wcag412`) with all/any/none check lists and True/False/None results; None routes to the vision model or the user with the element's (ControlType, Name, Rect, Patterns) attached. **Why:** JARVIS gains a deterministic way to say "this app is/isn't drivable, and here's the proof" *before* it starts clicking — graceful failure by construction, in WCAG vocabulary its logs and tests can share.
