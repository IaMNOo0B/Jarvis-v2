# MEGA-SCAN TEAM 23 — Accessibility Assistants

Reverse-engineering how assistive technology achieves **hands-free computer control, deep
voice-control grammar science, and graceful failure** — for JARVIS v2's
`voice_loop.py`, `stt.py`, `intent_router.py`, `tts.py`, and `pc_control.py` (UIA-first).
Accessibility tech has the deepest production voice-control science in existence: it is
used daily by people who literally cannot use a keyboard, so every false-trigger guard,
grammar design, and recovery path is battle-tested where it matters most.

**Method note:** `git clone --depth 1` + local code reads (slice C read via blobless
clones + `git show` per file after full clones exceeded sandbox bandwidth; all facts still
[CODE]-tagged from real source). Evidence tags: **[CODE]** (read in cloned source),
**[README]** (project's own claim), **[SEARCH]** (search metadata), **[INFERENCE]**.

**Coverage: ~38 targets touched, 33 repos deep-read at code level** (target 40; every
miss is documented below — nothing invented to close the gap):
- [A. Voice-control grammars & dictation](team23-part-a-voice.md) — 11 deep-read (Cursorless, talonhub/community, dragonfly, Caster, Vocola2, nerd-dictation, vosk-api, Handy, voice2json, a discovered motor-impairment desktop assistant, Serenade via proxy repo)
- [B. Screen readers & a11y automation](team23-part-b-readers.md) — 13/13 resolved (NVDA, Orca, axe-core, Accessibility Insights for Windows, speech-dispatcher, eSpeak NG, RHVoice, Guidepup, pa11y, Android Accessibility Test Framework, WCAG taxonomy + 2 discovery passes)
- [C. Gaze / switch / AAC & alternative input](team23-part-c-gaze.md) — 9 deep-read (OptiKey, Intel ACAT, Dasher, AsTeRICS, FLipMouse, Cboard, GazePlay, Opentrack, Eviacam) + 3 discovery finds

---

## The convergent architecture (what 17+ years of assistive systems agree on)

Read independently, the three slices land on the same four-layer design [INFERENCE from CODE in all three part-files]:

1. **A deterministic grammar tier in front of the model** — compositional grammars compiled from declarative specs, merged into one validated registry, with matching that degrades in tiers (exact → fuzzy → LLM) and an explicit no-match event at every tier.
2. **Recognition constrained to what the system can actually do** — command-mode STT restricted to the live grammar's phrases (Vosk FST), so the recogniser cannot "hear" a command that doesn't exist.
3. **Speech output as a prioritized, indexed, truncatable stream** — per-priority queues, cancel-vs-postpone-vs-latest-wins semantics, fragment indexes that make barge-in a data operation instead of a prayer.
4. **Anti-false-trigger discipline at every input surface** — dwell gates that consume their lock on firing, measured-noise thresholds instead of fixed constants, cancel-before-irreversible contracts, and failure that degrades down a ladder (UIA → keyboard → grid) instead of dying.

JARVIS v2 already has pieces of layers 1–2 (intent_router grammar tier, Builder F) and the *shape* of layer 3 (interruption watermark, Builder B) — this scan supplies the production-proven semantics and constants for all four.

---

## Top 5 mechanisms

1. **The SSIP×NVDA speech core.** [B, CODE] Speech Dispatcher defines 5 priority categories (important / message / text / notification / progress) with different self-interruption rules — text and notification are latest-wins, progress collapses bursts; NVDA implements per-priority queues with **preempt-and-resume** (an interrupted queue keeps its remaining sequences *and* synth-parameter state), plus **index callbacks marking exactly what finished speaking**. Together: a complete policy table + queue design for TTS interruption that two mature projects already proved in daily use by blind users.
2. **Compositional grammar → AST, with grammar-constrained decoding and tiered match.** [A, CODE] Cursorless parses action×modifier×target into a serialised AST dict validated per-slot; dragonfly compiles spec-strings; Caster merges rules into one registry with load-time validation; Vosk constrains the recogniser itself to the live grammar (FST `SetGrammar`); voice2json adds a fuzzy template tier (±1 word, typed slots). Explicit failure at each tier — never silence, never a silent LLM guess for safety commands.
3. **Phrase-history correction algebra.** [A, CODE] talonhub/community keeps every inserted phrase *and its exact character length*; `scratch that` / `select that` / `cap that` / `spell that` + a homophone picker operate deterministically on that memory. Correction by voice becomes cheaper than the error — the mechanism that makes dictation viable when there is no keyboard fallback. (nerd-dictation's stable-delta partial typing is the streaming half of the same idea.)
4. **The DwellGate family: two-phase dwell + consume-the-lock + measured-noise gates.** [C, CODE] OptiKey: lock-on (all gaze samples inside radius for the full window) → progress dwell → fire → **forced re-lock** (firing consumes the lock; repeats impossible by construction). Eviacam: 1000 ms dwell, 3 px tolerance, consecutive clicks disallowed by default — the input must *leave the zone* before anything fires again. Opentrack: smoothing threshold derived from a **60 s rolling noise estimate (0–3σ crossover)** instead of any fixed constant. GazePlay adds a 1000 ms pre-selection grace; Cboard a 300–1000 ms dwell ladder.
5. **Graceful-failure contracts: fallback descriptors + cancel-generation + three-valued checks.** [A+B, CODE] Cursorless: every action returns success, a fallback descriptor executable by cruder means, or a routed failure; a spoken STOP bumps a generation counter checked immediately before the irreversible step (Handy has the same cancel-generation pattern). axe-core/Android ATF: checks return pass / fail / **incomplete** — machines never guess; the undecidable goes to a human or model *with evidence attached*.

Runners-up (implement soon after): Orca's **event obsolescence** (a newer UI event deletes stale queued events — proactive narration that forgets doesn't babble) [B]; Dasher's **uniform floor** (PPM order 5, α=49, β=77, 5 % uniform — predicted options get less friction, nothing plausible ever reaches zero) [C]; ACAT's **scan sweep** (1000 ms step, +250 ms first-option hesitation, max 4 iterations then silent timeout — production numbers for Owais's call-ringing budget) [C].

---

## Top 3 steals for JARVIS v2

1. **`jarvis/tts.py` + `jarvis/voice_loop.py` — implement the SSIP×NVDA speech core** *(sources GPL/LGPL = ideas only, original code)*. `speak(seq, priority)`: important → NOW queue (cancels synth, never interrupted), message → normal queue with preempt-and-resume, text/notification/progress → latest-wins slots with progress throttling. Every utterance carries fragment indexes; on barge-in, truncate the spoken-phrase log to the last completed index (Guidepup's debounced spoken-phrase capture shows the observable shape) and offer resume for preempted normal speech. **Why first:** it is the direct, proven cure for v2's worst documented bug class — echo-era muting, lost interruptions, and history remembering words the user never heard (Builder B's watermark already gives the chunk-id substrate; this adds the missing priority/resume semantics).
2. **`jarvis/intent_router.py` + `jarvis/stt.py` — spec-string grammar compiler, merged registry, constrained command mode** *(dragonfly/Caster are LGPL = ideas; voice2json + Cursorless + talonhub/community are MIT = liftable with attribution)*. Commands become declarative data (spec-strings like Vocola/dragonfly lines, incl. a user-editable command file); skills register rules into one load-time-validated registry instead of hard-coding matches; "what can I say?" generates its own help. In command mode the STT phrase list is generated *from the live grammar* with dual endpointer profiles and n-best + word confidences surfaced; matching degrades exact → fuzzy (typed slots) → LLM with an explicit no-match event. Add community's **phrase-history + correction vocabulary** (`scratch/select/cap/spell that`, homophone picker, length-exact) and Handy's hangover-VAD + Soundex/Levenshtein vocabulary snap — this is the steal that converts recognition failure from a dead end into a one-word repair. **Why second:** every other voice improvement plugs into the router; flat matching is the root constraint on v2's voice reliability, and the Hinglish phrase files plug straight into this registry.
3. **`jarvis/pc_control.py` — DwellGate + UIA discipline + fallback ladder** *(OptiKey/Eviacam GPL = ideas only, re-implement; ACAT Apache-2.0 = liftable with attribution)*. (a) A `DwellGate` state machine — `IDLE → LOCKING (signal stable inside window) → DWELLING (progress 0→1, exit resets) → FIRED (locked until input exits tolerance)` — applied to gaze/head pointer *and* to voice confirmations ("yes" counts only after grace + dwell), seeded with production constants (grace 1000 ms, dwell ladder 300/500/700/1000 ms). (b) NVDA/Accessibility-Insights UIA discipline: dedicated MTA thread, RawView/ControlView walkers, snapshot-then-act on elements identified by ControlType+Name+Rect+Patterns, pattern-first invocation, post-action tree re-read to verify. (c) Cursorless-style fallback descriptors per action (UIA → keyboard → mouse grid, the talon grid as guaranteed-reachable last resort), cancel-generation checked before every irreversible actuation. Plus the axe/ATF-shaped UIA rule pack (rules-as-data, all/any/none, pass/fail/incomplete) so JARVIS can *prove* an app is drivable before it starts clicking. **Why third:** it turns pc_control from coordinate hope into verifiable, self-reporting, always-stoppable action — the safety property the whole accessibility field rests on.

---

## License map (verified from LICENSE files / repo docs — see part files per repo)

| Posture | Repos |
|---|---|
| **MIT / Apache-2.0 / ISC — code liftable with attribution** | Cursorless (MIT), talonhub/community (MIT), Vocola2 (MIT), Handy (MIT), voice2json (MIT), Accessibility Insights for Windows (MIT), Guidepup (MIT), Android ATF (Apache-2.0), vosk-api (Apache-2.0), **Intel ACAT (Apache-2.0 — verified from LICENSE by slice C)**, Opentrack core (ISC), AsTeRICS (dual MIT-or-GPL — take the MIT path) |
| **LGPL — ideas only for v2's clean-room posture** | dragonfly (LGPL-3.0), Caster (LGPL-3.0), Orca (LGPL-2.1), pa11y (LGPL-3.0), speech-dispatcher (GPL/LGPL mix) |
| **GPL / MPL / CC — IDEAS ONLY, never code** | **NVDA (GPL-2.0)**, eSpeak NG (GPL-3.0), RHVoice (GPL-2.0), nerd-dictation (GPL-3.0), OptiKey (GPL), Dasher (GPL), Eviacam (GPL), GazePlay, Cboard (GPL/CC-BY-SA family), axe-core (MPL-2.0 — file-level copyleft; treat as ideas for v2) |

---

## Honest gaps

- **Serenade** (`serenade-ai/serenade`) is closed/private (404 on clone) — read via the community proxy repo `awulkan/serenade-commands` and marked as proxy evidence in part A. **VoiceAttack** is closed-source; no open repo exists — reported as absent, not invented.
- NVDA, eSpeak NG, and the WCAG repo were recovered via **sparse/blobless checkout** after full clones timed out/disconnected (slice B); FLipMouse's repo holds hardware/settings only — **no firmware exists to read** (slice C); `enable-viacam/eviacam` 404s — the real repo is `cmauri/eviacam`.
- Slice C's reads are file-level (`git show` on blobless clones) rather than working-tree clones — same source bytes, noted for method honesty.
- Total **33 deep-read vs the 40 target**: the shortfall is entirely accounted for by the closed/absent repos above plus discovery-only entries (FlaUI, pywinauto, dogtail noted as [SEARCH] in part B). No padding was added.

*Part files: [A — voice grammars](team23-part-a-voice.md) · [B — screen readers](team23-part-b-readers.md) · [C — gaze/switch/AAC](team23-part-c-gaze.md). Clones under `~/workspace/jarvis-knowledge/megascan/.work23/` as of 2026-10-20.*
