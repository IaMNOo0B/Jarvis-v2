# MEGA-SCAN Team 23 — Slice C: Gaze Tracking, Switch Access, AAC & Alternative Input

Method honesty: full clones/tarballs of these repos exceeded the sandbox bandwidth (tarballs truncated ~8.5 MB, git checkouts timed out). All repos were instead cloned **blobless** (`git clone --depth 1 --filter=blob:none --no-checkout`, succeeds in seconds) and every code fact below was read from actual source files fetched individually via `git show HEAD:<path>` from those clones in `~/workspace/jarvis-knowledge/megascan/.work23/c/`. Tags: [CODE] read in source · [README] project's own claim · [SEARCH] GitHub search/API metadata · [INFERENCE] my reasoning.

Repos deep-read: **9** (OptiKey, ACAT, Dasher, AsTeRICS, FLipMouse, Cboard, GazePlay, Opentrack, Eviacam) + 3 discovery finds noted at the end. Clone failures: none of the 9 targets failed via the blobless route; `enable-viacam/eviacam` returns 404/empty — the live repo is **`cmauri/eviacam`** [CODE, cloned]. Dasher's canonical repo `dasher-project/dasher` exists and was read [CODE]; `dasher-project/dasher-web` (55★) also exists [SEARCH].

---

## Deep-read repos

### 1. OptiKey — JuliusSweetland/OptiKey (TOP priority)

**What it is:** Full on-screen keyboard for gaze/mouse/switch/key users: pluggable point sources (Tobii, IrisBond Hiru/Duo, TheEyeTribe, mouse, touch), pluggable trigger sources (fixation dwell, eye gestures, switch, click), dictionary autocomplete, multi-key (swipe-style) selection, scratchpad, TTS output, and a plugin engine that loads eye-tracker/speech plugins from GitHub repos at runtime (`Services/PluginEngine/GithubPluginsSearch.cs`, `OptikeyPluginEngine.cs`) [CODE].

**Input pipeline from code:**
- **Two-phase fixation trigger** — `Observables/TriggerSources/PointFixationSource.cs` [CODE]: Phase 1 *lock-on*: a rolling buffer keeps only points within the last `lockOnTime`; lock-on completes only when the buffer is full **and every buffered point lies within `lockOnRadius` of the buffer's centre point** (squared-distance test). Phase 2 *fixation*: progress = `fixationSpan / timeToCompleteTrigger`; any point outside `fixationRadius` of the fixation centre **resets progress to 0 and publishes a reset signal**. On progress ≥ 1 it fires, then **clears the buffer and the fixation centre** — the user must re-lock-on, so a held gaze cannot machine-gun repeat selections. Stale points (`tp.Value == null`) are filtered out *without* resetting fixation progress — a dropped tracker frame doesn't punish the user.
- **Gaze smoothing** — `GazeFilter.cs` [CODE]: exponential approach `result = last + multiplier·(point − last)` with a *gravity-well* multiplier: inside `LockRadius` multiplier = **0 (dead zone, point frozen)**; inside `FixationRadius` multiplier scales as `DampingLevel·(|Δ|/FixationRadius)^(1+DampingLevel)` (heavy smoothing near target); far away multiplier = `0.2·(1+4·DampingLevel)` (fast catch-up); over a key, speed is prioritised: `0.5·(1+DampingLevel)`. Damping presets from `TobiiEyeXProcessingLevel`: High=**0.1**, Medium=**0.4**, Low=**0.7**, Off=**1.0**.
- **Prediction** — three interchangeable engines behind `ISuggestions` [CODE]: (a) `BasicAutoComplete` — prefix match on a normalised dictionary, ranked `UsageCount` desc, then length asc; phrases are dual-indexed by full text **and by first-letter-of-each-word hash** (type "wru" → "where are you"). (b) `NGramAutoComplete` — trigram index (`gramCount=3, leadingSpaces=2, trailingSpaces=1`; leading padding weights word-start matches higher). (c) `PresageSuggestions` — wraps the Presage C++ LM via past/future-stream callbacks for true next-word prediction. Dictionary entries carry a persistent `UsageCount` that increments on use — the dictionary learns the user [CODE: `Models/DictionaryEntry.cs`, `DictionaryService.cs`].
- **Calibration:** per-vendor `ICalibrationService` implementations (Tobii, IrisBond, EyeTribe) behind one interface; calibration result is surfaced as a notification (`NotificationWithCalibrationResult`) rather than silently applied [CODE].

**Error recovery from code:** fixation exit = instant progress reset (no partial credit carried) [CODE]; post-trigger buffer clear = mandatory re-lock (cooldown by construction) [CODE]; per-key `TimeSpanOverrides` let dangerous keys demand longer dwell than letters [CODE: `OverrideTimesByKey`].

**License:** GPL-3.0 (`LICENSE.txt`) [CODE] — **IDEAS ONLY, no code lift.**

**Steal verdict:** Steal the *two-phase lock-on → dwell → forced re-lock* state machine and the *gravity-well gaze/pointer filter* as pure algorithms (re-implement, don't copy) into **`jarvis/pc_control.py`** — this is exactly the anti-false-trigger pattern JARVIS needs before any gaze/head pointer or even before "look at it and say yes" confirmation: a command target must be *stably* attended (all samples inside radius for the whole lock window) before its confirmation timer even starts, and firing consumes the lock. Steal the *phrase dual-indexing* (full text + initials hash, ranked by usage count) into **`jarvis/intent_router.py`** for command shortcuts ("oys" → "open youtube subscriptions"-style personal macros that learn from use).

### 2. Intel ACAT — intel/acat (TOP priority, Stephen Hawking's system)

**What it is:** Assistive Context-Aware Toolkit: a scanning UI (highlight sweeps rows/groups/widgets, one switch selects) driven by *actuators* (keyboard keys, USB HID switches, BCI/EEG headsets, winsock) with pluggable agents per application, word prediction, abbreviations, and TTS talk window [CODE: `src/Libraries/ACATCore/{ActuatorManagement,AnimationManagement,PanelManagement}`].

**Input pipeline from code:**
- **Scan engine** — `AnimationManagement/Animation.cs` + `AnimationPlayer.cs` [CODE]: each panel animation has `SteppingTime` (default `ScanTime`) and `HesitateTime` (default `FirstPauseTime`) — the first item is held longer so the user can orient. Defaults from `Config/Schemas/AppPreferences.schema.json` [CODE]: **`scanTime = 1000 ms`, `firstPauseTime = 250 ms`, `firstRepeatTime = 1000 ms`, `gridScanIterations = 4`, `rowScanIterations = 1`, `columnScanIterations = 1`** — after 4 full grid sweeps with no selection the scan times out/stops instead of looping forever. `hideOnIdleTimeout = 5000 ms` hides the scanner when idle.
- **Switch debounce = minimum hold** — `ActuatorSwitchBase.cs` [CODE]: `RegisterSwitchDown()` starts an accept Stopwatch; a press shorter than `MinActuationHoldTime` (preference `minActuationHoldTime`, default 0, per-switch overridable via `ResolveVariableInt(switchSetting.MinHoldTime, …)`) is rejected as accidental. Actuator abstraction: `IActuator`/`IActuatorSwitch` with keyboard-hook, USB-HID, winsock and BCI implementations behind one manager — any binary event source is a "switch" [CODE].
- **Manual scan mode:** pre-actuate and actuate pauses of **2000 ms** (`manualScanPreActuatePauseTime`, `manualScanActuatePauseTime`) bracket a deliberate selection [CODE schema].
- **Word prediction as an out-of-process service** — `Extensions/Default/WordPredictors/ConvAssist/` [CODE]: the predictor runs as a separate process talking **named pipes** (`NamedPipeServerConvAssist`, request handlers for word, character *and sentence* prediction). ACAT core never blocks on the LM. Plus `AbbreviationsManager` — user-defined abbreviation → expansion (typed or spoken) [CODE].

**Error recovery from code:** scan iterations cap → timeout state (`PlayerState.Timeout`) instead of infinite sweep [CODE]; min-hold rejection of bounce/accidental presses [CODE]; per-app *agents* mean a crashed/misbehaving panel is a replaceable module, and predictors failing degrade to no-prediction because they're out-of-process [INFERENCE from the pipe architecture].

**License:** **Apache-2.0** — verified from `LICENSE` ("Licensed under the Apache License, Version 2.0", © Intel) [CODE]. **Code may be lifted with attribution** — the only repo in this slice where that's true besides AsTeRICS-MIT-path and Opentrack-ISC.

**Steal verdict:** Steal (a) the **scan-with-iteration-cap + first-item hesitate** pattern for JARVIS's confirmation UX in **`jarvis/voice_loop.py`**: when JARVIS offers spoken/onscreen choices, present them in a timed sweep, hold the first option +250 ms longer, and *give up after N sweeps* instead of nagging forever — this is the call-ringing/interruption-budget idea with production numbers attached. (b) The **min-hold debounce** for its push-to-talk / wake handling: any activation shorter than a floor is discarded as noise. (c) The **predictor-behind-a-pipe** architecture for **`jarvis/intent_router.py`**: keep the LLM/intent model out of the real-time loop; the loop only ever consumes its latest cached output.

### 3. Dasher — dasher-project/dasher (TOP priority)

**What it is:** Continuous-gesture text entry: letters live in boxes sized by a language model's probability; you steer toward the letter you want and it zooms in — writing is one continuous pointing gesture, no clicks, no dwell. Steering back out to the left *deletes* — undo is the same gesture reversed [CODE: `Src/DasherCore/DasherModel.cpp` — `oldroots` stack, zooming back restores the previous root and its text].

**Input pipeline / language model from code:**
- **PPM language model** — `LanguageModelling/PPMLanguageModel.cpp` [CODE]: Prediction by Partial Matching with *exclusion*; per-symbol probability `p = slice·(100·count − beta) / (100·total + alpha)` blended down the context vine. Defaults from `Parameters.cpp` [CODE]: **`LP_LM_ALPHA = 49`, `LP_LM_BETA = 77`, `LP_LM_MAX_ORDER = 5`** (5-char context), **`LP_UNIFORM = 50` → a 5 % uniform floor** (`UniformTimes1000 = 50`) so no letter ever gets zero area — the model can be wrong without making a letter unreachable. A separate word-level model runs in parallel (`LP_LM_WORD_ALPHA = 50`, `WordLanguageModel`, `MixtureLanguageModel` mixes char + word models).
- **Input filtering / speed governance** — `DasherModel::ScheduleOneStep` [CODE]: zoom speed is fraction-governed per frame with an explicit "too fast" brake (computes bits-entered-per-step and clamps), `LP_SLOW_START_TIME = 1000 ms` ramps speed at start, `BP_AUTO_SPEEDCONTROL` adapts rate to how centred the user's steering is. Button-mode timings [CODE]: `LP_HOLD_TIME = 1000 ms` (long-press), `LP_TAP_TIME = 200 ms` (tap vs hold boundary).
- **Learning:** the PPM counts update as you write (with `LP_LM_UPDATE_EXCLUSION` controlling whether unseen-context updates are excluded) and training files can be imported — the model is personal and on-device [CODE].

**Error recovery from code:** there is no "wrong selection" to recover from — an error is corrected by *reversing the same continuous gesture*, cost proportional to how far you overshot; the uniform floor guarantees the intended letter is always still reachable [CODE + INFERENCE].

**License:** GPL-2.0 (`COPYING`) [CODE] — **IDEAS ONLY.**

**Steal verdict:** Steal the **probability-proportional target sizing + uniform floor** for **`jarvis/intent_router.py`**: when JARVIS ranks candidate intents/actions, size the "hit area" (how easy each is to confirm, how much evidence it needs) by predicted probability, but *never* let any plausible intent drop to zero — a 5 % floor keeps the unexpected command reachable. And steal **continuous-reversible correction** as a design rule for `jarvis/voice_loop.py`: undo should cost the same gesture as do (say the wake word + "undo" / steer back), never a menu dive. PPM itself (order-5, α=49/β=77) is a ~150-line stdlib-feasible fallback next-word predictor for offline text fields — worth implementing in `intent_router.py` for when the LLM is down [INFERENCE].

### 4. GazePlay — gazeplay/gazeplay

**What it is:** Suite of gaze-controlled games for children, with a device-manager abstraction over Tobii/EyeTribe/etc., fixation-based selection with visible progress feedback, and per-user configuration [CODE].

**Input pipeline from code:** `Configuration.java` defaults [CODE]: **`DEFAULT_VALUE_FIXATION_LENGTH = 2000 ms`** dwell to select, **`DEFAULT_VALUE_DELAY_BEFORE_SELECTION_TIME = 1000 ms`** grace delay before the dwell clock starts, `DEFAULT_VALUE_QUESTION_LENGTH = 5000 ms`, transition time 2000 ms. Selection widgets (`ProgressButton`, `ProgressPane`, `IGazeProgressIndicator` in gazeplay-games-commons) render dwell progress *on the target itself* — the child sees the button fill [CODE]. `FixationSequence`/`FixationPoint` record and visualise scanpaths for post-hoc analysis of where attention actually went [CODE].

**Error recovery from code:** **`DEFAULT_VALUE_QUESTION_REASKED_ON_FAIL = true`** — a wrong gaze answer re-asks the question rather than advancing/punishing; failure is a loop, not a dead end [CODE].

**License:** GPL-3.0 (`LICENSE`) [CODE] — **IDEAS ONLY.**

**Steal verdict:** Steal the **two numbers + re-ask rule** into **`jarvis/voice_loop.py`**: a 1000 ms *grace delay* before any confirmation dwell starts counting (the "hesitate" that stops drive-by triggers), progress rendered/spoken *on the target being confirmed*, and on a failed/ambiguous confirmation **re-ask once with the same wording** instead of escalating or guessing.

### 5. Opentrack — opentrack/opentrack

**What it is:** Head-tracking → pointer/game input: tracker (webcam face, IR points, IMU…) → filter → protocol output, with per-axis mapping splines [CODE: `logic/pipeline.cpp`, module dirs].

**Input pipeline from code:**
- **EWMA2 filter** — `filter-ewma2/ftnoir_filter_ewma2.cpp` [CODE]: dynamic smoothing — the delta is smoothed over ~16 ms (1/60 s) and compared against the noise variance estimated over ~60 s; as delta grows from 0 to **3σ of measured noise**, smoothing scales from maxSmooth down to minSmooth along a pow curve. Still = rock steady, moving = low lag, and the crossover is *measured from the user's own noise*, not a magic constant.
- **Accela filter** — `filter-accela/ftnoir_filter_accela.cpp` + `accela-settings.hpp` [CODE]: per-axis **deadzone** subtracted with sign (`if |d| > dz: d −= copysign(dz, d)`), delta normalised by a smoothing threshold (rotation sensitivity default slider **1.5**, range 0.05–2.5), then passed through user-drawn gain splines (separate rotation/translation curves).

**Error recovery:** filters are stateless-per-frame with first-run state seeding; a lost tracker simply stops the pipeline — no integrator windup because smoothing is output-referenced (`last_output`), not input-accumulating [CODE].

**License:** core ISC-style permissive ("Permission to use, copy, modify… with or without fee", © Stanislaw Halik) per `OPENTRACK-LICENSING.txt` [CODE] — **code may be lifted with attribution** (per-module; check 3rdparty notices).

**Steal verdict:** Steal **noise-adaptive EWMA** (σ-measured crossover, 16 ms delta window / 60 s noise window) into **`jarvis/pc_control.py`** for any future webcam head-pointer, and — more immediately — the same math into **`jarvis/voice_loop.py`**'s VAD/energy gating: measure the room's noise floor over a long window and set the speech threshold at a multiple of *measured* σ instead of a fixed dB constant. Also steal the **signed deadzone** one-liner for stick/pointer drift.

### 6. Eviacam — cmauri/eviacam (repo is `cmauri`, not `enable-viacam` — that org 404s)

**What it is:** Webcam face-tracking head mouse for Windows/Linux: face motion → pointer, with dwell clicking and a click toolbar [CODE: `src/viacamcontroller.cpp`, `src/dwellclick.cpp`].

**Input pipeline from code:** `CDwellClick::InitDefaults()` [CODE]: dwell tolerance area = **3 px**, dwell time default = **10 × 100 ms = 1000 ms** (`SetDwellTime(ds)` stores `ds·100` ms — decisecond configuration). `ProcessMotion()`: if displacement exceeds the tolerance area, the countdown **resets and the progress alert ends**; while inside, a visual progress alert updates with `PercentagePassed()`. On expiry, `OneShootAction()` fires the click selected in the click window (left/middle/right/drag…). **`m_consecutiveClicksAllowed` defaults to false** — after a dwell click you must leave and re-dwell; holding still cannot double-click. A motion-calibration mode (`CMotionCalibration::ComputeMotionRange`) measures the user's actual head range and maps it to screen range [CODE].

**License:** GPL-3.0 (`COPYING`) [CODE] — **IDEAS ONLY.**

**Steal verdict:** Steal **consecutive-trigger disallowance + tolerance-area reset** into **`jarvis/pc_control.py`** and the wake/confirmation path in `voice_loop.py`: after *any* fired action, require the input to exit the tolerance zone and re-enter before the same action can fire again. This is the cheapest possible cure for JARVIS's known repeat/echo failure class — one boolean and a radius.

### 7. Cboard — cboard-org/cboard

**What it is:** Web AAC app: symbol boards (OBF format) → a sentence strip the user builds tile-by-tile → spoken via TTS, built for switch scanning and eye control as first-class inputs [CODE: `src/components/Board`, `src/providers/{SpeechProvider,ScannerProvider}`].

**Input pipeline from code:** `Scanning.constants.js` [CODE]: scanning methods automatic/manual; **eye-control dwell options = [300, 400, 500, 700, 1000] ms** (a deliberately short, discrete ladder, not a free slider); blink/eye-close sensitivity via face blendshape thresholds **0.35 (high) / 0.5 (medium) / 0.65 (low)** — "higher threshold = eyes must close more fully = lower sensitivity". Speech provider is engine-pluggable (Web Speech ↔ ElevenLabs) with per-engine voice/pitch/rate state and voice caching [CODE]. `ImprovePhraseOutput` takes the telegraphic tile sentence ("me want water") and offers an improved full phrase before speaking — grammar repair as an explicit, user-visible step [CODE: component name + board flow].

**Error recovery:** the sentence strip *is* the undo model — tiles are removed one tap at a time before anything is spoken; nothing is committed until the user hits speak [INFERENCE from board/output-bar architecture, CODE for the components].

**License:** GPL-3.0 (`LICENSE.txt`) [CODE] — **IDEAS ONLY.**

**Steal verdict:** Steal (a) the **discrete dwell ladder [300…1000 ms]** as JARVIS's confirmation-timing presets in `pc_control.py` (offer Fast/Default/Careful, not a raw ms box); (b) the **blendshape-threshold sensitivity naming** (0.35/0.5/0.65) if webcam blink ever becomes a JARVIS confirm channel; (c) **"improve phrase" as an explicit step** for `intent_router.py`: when a Hinglish/telegraphic command is parsed, show/echo the expanded interpretation *before* executing irreversible actions — the expansion is the confirmation.

### 8. AsTeRICS — AsTeRICS/AsTeRICS (+ FLipMouse below)

**What it is:** A component framework (ARE runtime, OSGi-style bundles) for wiring assistive pipelines: sensors (camera, BCI, switches) → processors → actuators, composed in a graphical model or via REST API [CODE: `ARE/components/*` — 100+ single-purpose components].

**Input pipeline from code:** the processor catalogue *is* the pipeline vocabulary [CODE]: `processor.averager`, `processor.deadzone`, `processor.differentiate`, `processor.comparator`, `processor.delay`, `processor.eventblock`, `processor.eventdelay`, `processor.eventcounter`, `processor.blinkdetector` + `processor.blinkdetectortrainer` (a *trainable* blink detector — calibration as a component), `processor.acousticscanning`. Every stage is a separate bundle with declared in/out event+data ports, so a pipeline is inspectable and hot-swappable.

**License:** **dual MIT *or* GPL-3.0-with-exception** (`ARE-LICENSE_MITOrGPLv3WithException.txt`) [CODE] — choosing the MIT path makes **code liftable with attribution**.

**Steal verdict:** Steal the **named-stage pipeline vocabulary** into **`jarvis/pc_control.py`/`voice_loop.py`** design: implement input conditioning as composable stdlib stages — `averager → deadzone → comparator → eventblock(cooldown) → eventdelay` — each unit-testable in isolation, instead of one monolithic handler. Specifically `eventblock` (swallow repeats for T after an event) is ACAT's min-hold + Eviacam's no-consecutive-click generalised, and it should be a first-class stage in JARVIS's trigger path.

### 9. FLipMouse — asterics/FLipMouse

**What it is:** Open-hardware lip/finger mouse: a mouthpiece joystick (pressure sensor MPXV7007 + stick) + sip/puff + buttons, appearing as USB/BLE mouse+keyboard, configured by *slots* [CODE/README]. Honest scope note: **this repo now contains hardware (KiCad), construction kit and settings profiles — the firmware does not live here** (sibling project FABI, `asterics/FABI`, 21★, is the button-interface firmware family [SEARCH]); I did not deep-read firmware that isn't in the repo.

**From the repo:** `Settings/default.md` [CODE]: default slot — stick = mouse movement, Button 1 = load next slot, Buttons 2/3 unassigned; alternative profiles (`Settings/minecraft_with_2buttons.md`, `mouse_usb+keys_usb+mouse_bt.md`) show the whole device personality is a swappable profile, switchable by one button press at runtime.

**License:** dual **CC BY-SA 4.0 *or* GPL-3.0** (`LICENSE`) [CODE] — **IDEAS ONLY** for JARVIS purposes.

**Steal verdict:** Steal **runtime-swappable input profiles ("slots")** into **`jarvis/pc_control.py`**: one button/voice command cycles JARVIS's input personality (Mouse / Keyboard / Media / Presentation), each slot a declarative mapping table — the user changes what their one reliable switch *means* without opening settings.

### Discovery finds (not deep-read)
- `tensorsense/LaserGaze` — 44★, **MIT** [SEARCH]: real-time gaze estimation using temporal data — the only permissively-licensed gaze estimator found; candidate if JARVIS ever does webcam gaze.
- `dasher-project/dasher-web` — 55★ [SEARCH]: Dasher's LM/zoom model in the browser — fastest way to *feel* PPM sizing before implementing.
- `igoor-noprofit/igoor` — AGPL-3.0 eye-tracking-controllable conversational app [SEARCH] — ideas only, watch-list.

---

# Top 5 mechanisms

1. **Two-phase dwell: lock-on (all samples inside radius for the full window) → progress dwell → fire → forced re-lock.** [OptiKey, CODE] The single best anti-false-trigger pattern in the slice; firing *consumes* the lock, so repeats are impossible by construction.
2. **Probability-proportional targets with a uniform floor.** [Dasher PPM, CODE: order 5, α=49, β=77, 5 % uniform] Predicted options get more room/less friction; nothing plausible ever reaches zero — the model can be wrong safely.
3. **Scan sweep with hesitate + iteration cap.** [ACAT, CODE: 1000 ms step, +250 ms first pause, 4 grid iterations then timeout] Timed presentation of options that *gives up gracefully* instead of looping forever.
4. **Noise-adaptive smoothing (measured σ crossover).** [Opentrack EWMA2, CODE: 16 ms delta window vs 60 s noise window, smoothing fades over 0–3σ] Thresholds derived from the user's own measured noise beat every fixed constant in this report.
5. **No-consecutive-trigger + tolerance reset.** [Eviacam, CODE: dwell 1000 ms, tolerance 3 px, consecutive clicks disallowed by default] After firing, the input must leave the zone before anything can fire again — one boolean that kills double-fires and echo loops.

# Top 3 steals (for JARVIS v2, stdlib-only Python)

1. **`pc_control.py` — DwellGate state machine** (from OptiKey + Eviacam, re-implemented; both GPL so *no code copied*): `IDLE → LOCKING (all points/commands stable inside window) → DWELLING (progress 0→1, exit resets) → FIRED (locked until input exits tolerance)`. Apply it to gaze/head pointer *and* to voice confirmations ("yes" only counts after the grace + dwell). Constants seeded from production: grace 1000 ms [GazePlay], dwell ladder 300/500/700/1000 ms [Cboard], lock radius from OptiKey's squared-distance test.
2. **`intent_router.py` — usage-ranked dual-index shortcuts + uniform-floor intent ranking** (from OptiKey's BasicAutoComplete + Dasher, re-implemented): personal commands indexed by full phrase *and* initials, ranked by a persisted usage count; candidate intents get confirmation friction ∝ predicted probability with a hard 5 % floor so the rare command is never unreachable. Bonus: abbreviations table (ACAT-style) as user-defined expansions — ACAT is Apache-2.0, so its *design* (and code, with attribution) is fair game.
3. **`voice_loop.py` — measured-noise gating + scan-style choice presentation** (from Opentrack EWMA2, ISC — liftable with attribution; and ACAT, Apache-2.0): VAD threshold = k·σ of a 60 s rolling noise estimate instead of a fixed level; when JARVIS must offer choices, sweep them ACAT-style — first option +250 ms hesitate, 1000 ms per step, max 4 sweeps, then time out silently and log for later (which is precisely Owais's call-ringing interruption budget, with production numbers).
