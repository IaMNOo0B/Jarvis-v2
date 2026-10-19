# Voice Loop Specification — JARVIS v2

**PHASE INFINITY, Research Cycle 15.** Design-only. This is the document the voice plugin gets built from — when voice's turn comes (R1: voice is last, after the chatbot core).

**Status:** spec complete, unvalidated against real hardware. Every clause traces to a lesson. Open questions marked `[OQ]`.

**The governing rule** (AGENTS.md, "1st greeting" lesson): *Never fix a voice component in isolation. Always trace the FULL loop: mic → VAD → STT → brain → TTS → speakers → mic again. Before touching any voice code, ask: "what does the NEXT stage hear/see because of this change?"*

---

## 1. The loop as a stage graph

The architecture IS the graph. No stage talks to another except through declared edges. Each stage owns its state; the loop controller owns transitions.

```
 MIC ──► VAD ──► WAKE ──► COLLECT ──► STT ──► BRAIN ──► TTS ──► SPEAKERS
  ▲                                                              │
  │                    ECHO GUARD (watches TTS state)            │
  │                    BARGE-IN (watches mic DURING TTS)         │
  └────────────────────── acoustic path ────────────────────────┘
```

### 1.1 Stages: inputs, outputs, state, failure modes

| Stage | Input | Output | Owned state | Failure modes (→ §6 corpse refs) |
|---|---|---|---|---|
| **MIC** | OS audio device | raw PCM frames (16kHz mono) | device handle, stream state | stale device (H-V4), permission revoked (H-V5), exclusive-mode failure (H-V7), close→start RuntimeError (M-V18) |
| **VAD** | PCM frames | speech/no-speech + energy envelope | adaptive ambient floor, speaking-boost multiplier | onset clipping (H-V6), soft-voice floor (M-V8), noise freeze (M-V7), double-VAD double-trim (M-V11) |
| **WAKE** | VAD-gated frames | wake events + scores | model, threshold, cooldown, `last_score` surfaced | false accepts w/o backoff (M-V12), fixed uncalibrated threshold (M-V13), self-wake via TTS (H-V8, C-V3) |
| **COLLECT** | PCM frames | bounded utterance (≤30s, trimmed) | ring buffer, start/end markers | 40s static listening (M-V19), 1.2s trailing silence (M-V9), 30s hard cut mid-word (M-V9) |
| **STT** | utterance audio | text + confidence + word timestamps | model (loaded, never lazy-on-GUI-thread) | first-turn download freeze (M-V10), hallucination on noise (M-V7), download on GUI thread (M-V5) |
| **BRAIN** | text + session | Utterance Record (text sentences) | conversation history (truncated to *spoken* words) | confabulation of unspoken words (M-V16), unbounded history (H-B7), busy-turn swallow (M-V17) |
| **TTS** | sentences | word-level completion events | per-sentence status: queued→synthesizing→speaking→spoken/interrupted/skipped | barge-in permanent mute (C-V2), slow-synth uninterruptible (H-V3), lock head-of-line blocking (M-V6), all-backends-fail silent (H-V2) |
| **SPEAKERS** | PCM | acoustic output + playback position | device handle, current word index | per-sentence stream gaps (M-V3), device-busy silent skip (M-V3) |

### 1.2 The two cross-cutting watchers

These are not stages — they are *invariants enforced from outside*:

- **ECHO GUARD**: subscribes to TTS state. While `tts_state ∈ {speaking}`: VAD threshold ×2.5, wake sink **muted**, utterance collector **paused**. For 800ms after `tts_state → idle`: wake sink stays muted, VAD boost decays. *The guard exists before the speaker does* (§2).
- **BARGE-IN**: subscribes to mic partials DURING `tts_state == speaking`. Feeds STT partial hypotheses to the novel-word detector (§3). Never acts on energy alone.

### 1.3 The Utterance Record (Moshi pattern, zero-cost transfer)

One per assistant turn. The text spine of the speaking path. [moshi-deep-dive §4]

```
UTTERANCE RECORD
  trace:
    - llm_text_full            (complete LLM output)
    - sentences[]              (segmented for TTS)
      - text
      - status: queued | synthesizing | speaking | spoken | interrupted | skipped
      - spoken_words[]         (word + timestamp, WHAT ACTUALLY LEFT THE SPEAKERS)
  provenance: observed | derived | inferred   [REA lesson]
```

**The brain never "says" audio — it commits text sentences.** TTS consumes sentences and reports word-level completion back. "Record what was spoken, not what was generated" is a *field*, not a discipline. [moshi-deep-dive §4; AGENTS.md voice-loop rule]

---

## 2. Echo management by construction

**The v1 sin:** the guard was created *after* the speaker, wired by convention, and died silently. The fix is structural: **wiring that cannot be forgotten because the object cannot exist unwired.**

### 2.1 Construction order (the anti-C-V1 rule)

```
1. echo_guard = EchoGuard()            # FIRST
2. speaker = Speaker(on_state=echo_guard.tts_state)   # callback registered AT construction
3. mic_coordinator = MicCoordinator(echo_guard=echo_guard)  # guard injected, never fetched
4. assert speaker.state_callback is echo_guard.tts_state   # wiring test, runs at startup
```

- The `Speaker` constructor **requires** an `on_state` callback — there is no default, no `None`. A speaker without a guard does not compile/pass review. [C-V1]
- The mic coordinator receives the guard by injection. `getattr(self, "echo_guard", None)` patterns are banned by code review — the guard is a constructor dependency, not an optional attribute. [C-V1]
- **Startup wiring test:** asserts the callback chain `speaker.state → guard.tts_state → mic_coordinator.should_ignore` is live. If the test fails, the voice plugin refuses to load with a plain-language error — never silent. [R12]

### 2.2 The sequencing that makes self-trigger impossible

| TTS state | Mic behavior | Why |
|---|---|---|
| `speaking` | VAD threshold ×2.5; wake sink **hard-muted**; utterance collector **paused** | TTS output must not wake (C-V3, H-V8) or collect (C-V4). The guard gates the WAKE and BARGE sinks too — not just the utterance collector. [C-V3, C-V4] |
| `speaking → idle` transition | 800ms tail: wake sink stays muted; VAD boost decays linearly to 1.0 | Bluetooth/speaker tail bleeds past the stop event. [C-V1 tail mute] |
| `idle` (800ms elapsed) | Normal operation | — |

**M-V20 (fixed 800ms):** the tail duration is adaptive. Calibration procedure: at setup, play a test tone and measure the tail energy decay on the mic; set `ECHO_TAIL_MS = measured + 200ms margin`. Re-measure on audio-device change. The constant is a *default*, not a law.

**M-V1 (settings rebuild drops wiring):** `_apply_settings` never rebuilds the speaker without re-attaching `on_state` — because the speaker *cannot be constructed* without it (§2.1). The old worker thread is joined before the new one starts (no leak). The wiring test re-runs after every rebuild.

### 2.3 Anti-self-wake by signal path, not hope

Two independent mechanisms, either sufficient:

1. **Wake sink muted during TTS** (§2.2) — the wake model never sees TTS audio. [C-V3, H-V8]
2. **Content guard:** if a wake event fires within 2s of TTS completion, the loop controller checks whether the wake-score audio window overlaps the TTS tail; if yes, discard the event. Belt and suspenders — the mute is primary, the content check catches the race.

---

## 3. Barge-in done right

**The v1 sin:** barge-in permanently muted all future speech (C-V2) because `stop()` set a flag that nothing ever cleared.

### 3.1 Novel-word detection (never energy alone)

While `tts_state == speaking`, mic partials flow to a lightweight STT pass:

```
spoken_so_far = utterance_record.spoken_words[] → text
partial = stt_partial(mic_frames)
match_ratio = word_overlap(partial, spoken_so_far) / len(partial.words)

if match_ratio ≥ 0.70:  → ECHO (our own voice coming back). Keep ignoring.
else if novel_words accumulate ≥ 3:  → USER INTERRUPTING. Yield. [AGENTS.md barge-in rule]
```

- Energy alone never triggers. [AGENTS.md]
- "Stop!" / "shut up" / "never mind" are in a **hard interrupt phrase list** — they bypass the word-count accumulator and yield immediately. [M-V14]
- The 70% threshold and the 3-word accumulator are calibrated on the Hinglish golden set (code-switch boundaries are where naive matchers fail). [learn-hinglish-golden]

### 3.2 The TTS stop protocol (the anti-C-V2 rule)

```
def stop(self):
    self._stop_requested.set()          # signal, not a latch
    self._worker.join(timeout=2.0)      # wait for the worker to park
    self._audio_device.abort()          # kill the stream NOW
    self._queue.clear()                 # drop unsaid sentences → mark `skipped`
    self._stop_requested.clear()        # ← THE LINE V1 WAS MISSING
    self._state = IDLE
    self.on_state(IDLE)                 # guard hears it → tail mute starts
```

- The stop flag is **cleared by `stop()` itself**, not by some unreachable future code path. [C-V2]
- `say()` asserts `not self._stop_requested.is_set()` at entry — defense in depth.
- **Slow cloud synthesis (H-V3):** synthesis runs on a worker thread; `stop()` sets the flag the synthesizer checks between chunks. A 30s network synth is interruptible at chunk boundaries (≤2s granularity). The blocking `synthesize()` call is banned from the audio thread.
- **Lock discipline (M-V6):** the fallback lock is held per-sentence, never across network synthesis. Slow backends don't head-of-line-block the stop signal.

### 3.3 Trace surgery on interrupt (Moshi's Utterance Record)

On yield:

```
1. current_sentence.status = INTERRUPTED
2. spoken = tts.spoken_words[]          # what ACTUALLY left the speakers
3. record.spoken_words = spoken
4. conversation_history.truncate_to(spoken_text)   # brain forgets unspoken words
5. remaining_sentences.status = SKIPPED
6. process the user's interruption as the new turn
```

The brain never "remembers" saying words the user never heard. [M-V16; moshi-deep-dive §4; AGENTS.md "record what was spoken"]

---

## 4. Turn-taking

### 4.1 Endpointing (when is the user done?)

Three signals, OR-ed:

1. **Silence:** 700ms trailing silence after speech (adaptive: 500ms in quiet rooms, 900ms in noisy — tied to the VAD ambient floor). [M-V9: trailing silence is *measured*, not a fixed 1.2s include]
2. **Semantic completion:** STT partial ends on a complete clause AND silence ≥400ms → endpoint early. (Saves the dead 300ms.)
3. **Hard cap:** 30s — but the cap **fades out, doesn't cut**: at 28s the HUD shows "wrapping up…", at 30s the utterance closes at the last word boundary. [M-V9: no mid-word cuts]

### 4.2 The no-dead-air rule

Every loop state has an audible or visible signal. No state is silent *and* invisible. [H-B6, M-V19]

| State | Signal |
|---|---|
| Listening | pulsing ring + soft tick |
| Transcribing | "got it, thinking…" (if >1s) |
| Brain working | typing indicator (never >3s without a status word) |
| Warming up (cold model) | "warming up, one moment" [M-V19] |
| Speaking | speaking pill with voice profile name [voicebox-deep-dive §1: bidirectional pill] |
| Degraded (any fallback) | one calm notice: what happened, what to do [R12] |

### 4.3 Interruption of slow paths

- Cloud TTS synthesis >2s: chunk-interruptible (§3.2). The user never waits out a 30s synth. [H-V3]
- STT model not loaded: the *first* turn never blocks the GUI thread — model loads on a worker, HUD shows progress. [M-V5, M-V10]
- Brain hung: per-turn tool budget + circuit breaker aborts; the loop announces and offers text mode. [H-B8, M-S28]

### 4.4 Fallback to text (R1 — voice is a plugin)

If the voice plugin fails to load, fails its wiring test, loses the mic, or the user mutes: **the chatbot continues in text with zero degradation of capability.** Voice adds modality; it never gates function. [R1; H-V7: engine.start() failure must not kill PTT/text]

---

## 5. Wake-word

### 5.1 The two-word scheme (locked in, Phase 4)

- **"hey jarvis"** → wakes the LOCAL brain. Always-on, on-device model (openWakeWord, ships pre-trained).
- **"hello jarvis"** → wakes the CLOUD brain for exactly one turn. Custom-trained model (user's voice samples) before arming. [roadmap Phase 2: livekit-wakeword path supersedes the Colab notebook]
- **Stale-word hygiene (M-V21):** the wake word is cleared by the *same* function that consumes it. No `_wake_word` without `_wake_evt`; no consumer without a clearer. One struct, one lifecycle.

### 5.2 Threshold calibration procedure

1. At setup: play 20 known-negative clips (TV dialogue, music, silence) + 10 user-spoken wake phrases.
2. Set threshold at the point maximizing (true accepts − 3 × false accepts). False accepts cost 3× because each one is a 10s dead turn. [M-V12]
3. `last_score` is **always surfaced** in the voice debug panel — "hey jarvis ×5 → nothing" must show *why* (scores 0.3, 0.4, 0.35… → threshold too high, recalibrate). [M-V13]
4. Re-calibrate on: audio device change, major ambient change (user-triggered), or >5 false accepts/day (auto-suggest).

### 5.3 False-accept / false-reject measurement

- **False accepts:** counted per day, shown in the voice panel. >5/day → suggest recalibration. Anti-double-fire cooldown (1.5s) + exponential backoff on repeated accepts (2nd within 60s → 5s cooldown, 3rd → 15s). [M-V12]
- **False rejects:** measured during calibration; in production, 3 consecutive sub-threshold near-misses (score within 0.1 of threshold) → HUD hint "didn't catch that — tap to talk or recalibrate". [M-V13]
- Both are SLO inputs (S3: ≤3 false wakes/day). [learn-reliability-spec]

### 5.4 Anti-self-wake (by signal path)

Covered in §2.3. Restated as a test: **the voice test suite includes "TTS says the wake word" as a regression case.** Play "my wake word is hey jarvis" through TTS; assert zero wake events. [H-V8] This test would have caught the original self-talk loop.

---

## 6. The failure table — every v1 corpse, mapped to its clause

| Corpse | Clause that prevents it |
|---|---|
| **C-V1** echo guard dead code | §2.1: guard-first construction, mandatory `on_state`, startup wiring test |
| **C-V2** barge-in permanent mute | §3.2: stop flag cleared by `stop()` itself; `say()` entry assert |
| **C-V3** wake sink unfiltered post-TTS | §2.2: wake sink hard-muted during TTS + 800ms tail |
| **C-V4** VAD multiplier feeds wrong sink | §2.2: guard gates WAKE and BARGE sinks, not just the utterance collector |
| **H-V1** backend missing, silent | §4.2 no-dead-air + R12 preflight: backend presence checked at plugin load, plain-language error |
| **H-V2** all backends fail, silent | §4.2: degraded-mode announcement, always |
| **H-V3** slow synth uninterruptible | §3.2: chunk-interruptible synthesis, ≤2s granularity |
| **H-V4** stale mic device | §1.1 MIC: device re-enumeration on change events + mic selector in settings |
| **H-V5** mic permission revoked | §1.1 MIC: zero-frame detection → immediate toast, no 40s hang |
| **H-V6** onset clipping 250–300ms | §1.1 VAD: 500ms pre-roll ring buffer retained; utterance starts *before* the trigger |
| **H-V7** engine.start failure kills voice | §4.4: voice failure → text continues; PTT/text never gated on the audio engine |
| **H-V8** self-wake via reply content | §2.3 + §5.4: wake muted during TTS; regression test "TTS says the wake word" |
| **M-V1** settings rebuild drops wiring | §2.1: speaker unconstructible without `on_state`; wiring test re-runs post-rebuild |
| **M-V2** scheduler/watcher bypass mic coordination | All speech paths (scheduler, watcher, telegram) go through the loop controller's `speak()` — no direct speaker access. Single choke point. |
| **M-V3** per-sentence stream gaps/skips | One persistent output stream per session; device-busy → queued retry with notice, never silent skip |
| **M-V4** unbounded monologue | Reply-length cap (configurable, default ~90s of speech); cap hit → "there's more — want me to continue?" |
| **M-V5** first-run download on GUI thread | All downloads on workers with progress UI; R12 preflight |
| **M-V6** fallback lock head-of-line | §3.2: lock per-sentence, never across network synth |
| **M-V7** noise freeze → 30s garbage | VAD ambient floor has a sanity ceiling; sustained max-energy → "it's loud in here" notice + shorter windows |
| **M-V8** soft voice under floor | §5.2-style calibration: floor set from the user's own voice at setup; "didn't catch that" always names the suspected cause |
| **M-V9** trailing silence / mid-word cut | §4.1: measured silence, fade-out at cap, word-boundary close |
| **M-V10** STT download blocks controller | §4.3: worker-thread loads, HUD progress |
| **M-V11** double VAD double-trim | ONE VAD stage. The whisper `vad_filter` is OFF when the energy VAD is ON — chosen at config, never both. |
| **M-V12** false accepts, no backoff | §5.3: cooldown + exponential backoff + daily counter |
| **M-V13** false rejects, no feedback | §5.2: `last_score` surfaced; near-miss hints |
| **M-V14** "stop!" does nothing | §3.1: hard interrupt phrase list |
| **M-V15** wake disabled → zero interruption | Barge-in is independent of the wake word: mic partials during TTS always feed the novel-word detector. PTT never queues behind a reply — it interrupts. |
| **M-V16** confabulation of unspoken words | §3.3: history truncated to `spoken_words[]` |
| **M-V17** telegram mid-turn swallow | Cross-surface turns queue: a Telegram message during a voice turn gets a voice acknowledgment ("noted — I'll handle it after this") or joins the text queue visibly. Never silent. |
| **M-V18** close→start RuntimeError | Stream lifecycle owned by one object with create→start→stop→destroy; no restart of a dead thread — always a fresh stream |
| **M-V19** cold-start silence | §4.2: "warming up" state with sound |
| **M-V20** fixed 800ms tail | §2.2: adaptive tail from measured decay + margin |
| **M-V21** stale wake word → wrong brain | §5.1: word and event share one lifecycle; consumer clears both |
| **M-V22** `_cleanup` AttributeError | All service handles initialized in `__init__` (to `None`); cleanup guards on `None`. Constructor-complete invariant. |

**Completeness check:** all 4 critical + 8 high + 22 medium voice corpses map to at least one clause. No orphan corpses. [spec completeness: 34/34]

---

## 7. Engine integration (Voicebox as appliance)

v2 does NOT build TTS/STT engines. The voice plugin's engine layer is a thin client over Voicebox's MCP server (`127.0.0.1:17493/mcp`); the in-process ladder (Piper → Kokoro-82M) is the failsafe when Voicebox is absent. [voicebox-deep-dive §5]

**The boundary is explicit:** Voicebox owns *engines* (synthesis, transcription, cloning, playback). v2's voice plugin owns the *loop* (this spec: wake, barge-in, echo guard, turn-taking, Utterance Record). Voicebox has no wake word, no streaming TTS, no barge-in — those are loop concerns and stay here. [voicebox-deep-dive §5–6]

**Latency gate** [voicebox-deep-dive calibration, 70%]: sentence-level `voicebox_speak` round-trips must measure ≤800ms on the target PC before the MCP boundary is accepted. Above that → engine-level streaming (Chatterbox-Turbo direct) instead. **This is a benchmarking-weekend measurement** (Track B). [learn-benchmark-spec]

**The pill** [voicebox-deep-dive §1]: every agent-initiated speech surfaces the speaking pill with the voice profile name for the full duration. No silent background TTS — the user always sees what's coming out of the machine. (R14 honest UX.)

---

## 8. Open questions

- **[OQ1]** The 70% word-match / 3-novel-word barge-in thresholds: proposals from AGENTS.md doctrine, uncalibrated. Calibrate on the Hinglish golden set + real usage. [MC]
- **[OQ2]** Adaptive tail measurement (M-V20 fix): the test-tone procedure needs validation on Bluetooth vs wired vs laptop speakers — tail profiles differ wildly. [SP]
- **[OQ3]** Semantic endpointing (§4.1.2): needs the STT partial stream to be reliable mid-utterance; faster-whisper partial quality on Hinglish code-switches is unmeasured. [MC]
- **[OQ4]** The joint turn-taking policy (Moshi §3 lesson): this spec implements it as explicit rules. Whether a small learned controller beats the rules is a later experiment, not a v1 decision. [SP]
- **[OQ5]** Voicebox sentence-level latency on the 2060: unmeasured, gates the MCP boundary. [UK — benchmarking weekend]

---

## 9. Confidence & traceability

- **[VC]** The stage-graph architecture and the guard-first construction rule — forced by the v1 corpses, which are measured facts.
- **[VC]** The Utterance Record pattern — Moshi's 3× benchmark delta is the strongest empirical result in the studied literature.
- **[HC]** Novel-word barge-in design — doctrine + Moshi's joint-channel lesson; thresholds uncalibrated.
- **[HC]** The 34/34 corpse coverage — verified by the table above; coverage is structural, not tested.
- **[MC]** Adaptive tail, semantic endpointing, Voicebox latency — proposals awaiting the benchmarking weekend.

**Every clause traces to:** `moshi-deep-dive.md` (§2 Inner Monologue, §3 full-duplex), `voicebox-deep-dive.md` (§1 pill, §5 integration shape, §6 limits), `FAILURE-ANALYSIS.md` (C-V1–C-V4, H-V1–V8, M-V1–V22), `AGENTS.md` (voice-loop thinking, barge-in rule, record-what-was-spoken), `learn-hinglish-golden.md` (calibration data), `learn-benchmark-spec.md` (Track B latency gate), `learn-reliability-spec.md` (S2/S3 SLOs).

**Honest completion (Rule 12):** Researched: 4 source files read in full. Validated: corpse IDs cross-checked against FAILURE-ANALYSIS.md. Saved: 1 file. Tested/Measured: nothing (design only). Incomplete: none — spec answers its brief. Blocked: OQ2/OQ3/OQ5 need the 2060.
