# MEGASCAN WAVE 2 — Team 7: VOICE, DEEPER (reverse-engineered at code level)

**Coverage:** 36 NEW repos read (none repeated from Wave 1's 43). 8 deep full-pipeline
traces, 14 medium code-level reads, 12 quick reads, 2 structure-only (clone transport
failed repeatedly — flagged honestly per repo). Target was 40; the last 4 (ssftalk,
Voca, pocket-tts-streaming, wbb921) plus duplexjev/VAP pack transfers died on this
network egress after multiple retries — not padded, not invented.

**Method:** GitHub API for discovery only (hit 429), then `git clone --depth 1`
(+ sparse/blob-filtered clones for pipecat, livekit/agents, TEN, moonshine) and local
code reading. All file:function refs below are from the clones.

**Wave-2 headline:** Wave 1's field was wake-word hobbyists. Wave 2's field is the
*turn-taking science* layer: learned end-of-turn models (Smart Turn v3, Easy Turn,
SoulX-Duplug, TEN's LLM judge, LiveKit's streaming EOU + backchannel head), production
endpointing that *learns the user's pause habits* (LiveKit dynamic endpointing), and
barge-in treated as a classification problem, not a volume problem (streamcore's
transcript predicates, Bolna's word-count gate, protoVoice's 350 ms grace gate).
The cascaded pipeline still wins on deployed systems; end-to-end omni models
(SpeechGPT-2.0, VoiceAgent-600ms omni path) now measure 200–250 ms first-audio but
remain Chinese-first and GPU-hungry.

---

## CONSTANTS CONVERGENCE (Wave 2, from code)

| Constant | Values found | Where |
|---|---|---|
| Frame/chunk size | 512 spl/32 ms (RMS VAD) · 1024 spl/64 ms (browser tick) · 2560 spl/160 ms (semantic VAD) · 20 ms (telephony AudioSocket) | pguso · dsh-voice · Duplug · tvbench |
| Energy VAD threshold | RMS 0.02 (speech gate) · RMS 0.015 (silence/level gate) | pguso, Duplug far-field · kiwi-voice, dsh-voice |
| Neural VAD threshold | Silero 0.5 act / act−0.15 deact (LiveKit) · 0.7 conf + vol 0.6 (Pipecat) · FireRedVAD 0.5 | livekit plugin · pipecat · VoiceAgent-600ms |
| VAD confirm times | start 0.2 s / stop 0.2 s | pipecat `vad_analyzer.py` |
| Endpoint delay (fixed) | min 0.5 s / max 3.0 s (non-streaming) · min 0.3 s / max 2.5 s (streaming) | livekit `turn.py` defaults |
| Endpoint delay (learned) | EMA alpha 0.9 over user pause durations; max is a clamp, never learned | livekit `DynamicEndpointing` |
| Learned EOT decision | p > 0.5 on last ≤8 s of audio (Smart Turn v3) · 4-state head/160 ms chunk (Duplug) · 4-state acoustic+linguistic (Easy Turn: 96.3/97.7/91/98 % acc) | pipecat · Duplug · Easy-Turn |
| Eager/speculative EOT | Deepgram Flux eager 0.5 vs commit 0.7, force at 500 ms silence · speculation timeout 5.0 s · preemptive gen ≤10 s speech, ≤3 retries/turn | bolna constants · pipecat · livekit |
| Barge-in gate | 350 ms grace + transcript confirm (protoVoice) · >3 words or phrase list (Bolna) · RMS 0.055 × 4 sustained 32 ms blocks after 1.0 s lead-in (pguso) · ≥2 tokens + ≥1 content word, backchannels excluded (streamcore) | — |
| False-interruption handling | 2.0 s silence → classify false, resume TTS (LiveKit) · backchannel boundary (1.0 s, 1.0 s) around agent turns | livekit `turn.py` |
| Sentence cut for TTS | first sentence at ≥10 chars + terminal punct (spark) · clause delimiters incl. `;:—` (Wave-1 alts, reconfirmed pattern) | spark-voice-pipeline |
| Latency budgets (measured/claimed) | cascade 458 ms · omni 250 ms · barge-in cut 160 ms · SpeechGPT-2.0 <200 ms · "800 ms = machine-perception threshold" | VoiceAgent-600ms · SpeechGPT |

---

## DEEP READS (full pipeline trace)

### 1. pipecat-ai/pipecat — 16,634★, ALIVE, BSD-2-Clause ★ deepest framework read
Flow: mic → `VADProcessor.process_frame` (forwards frame *first*, VAD after — audio
never waits for detection) → `VADController` over `VADAnalyzer` → turn strategies →
STT → aggregators → LLM → sentence aggregation → TTS → transport.
- `audio/vad/vad_analyzer.py:25-28` — VAD_CONFIDENCE=0.7, VAD_START_SECS=0.2,
  VAD_STOP_SECS=0.2, VAD_MIN_VOLUME=0.6; volume is EMA-smoothed (factor 0.2) so a
  single loud frame can't fake speech.
- `audio/vad/silero.py:33-38` — **model-state reset trick**: Silero's recurrent state
  gets poisoned by music/long noise (worse at 8 kHz); pipecat force-resets the model
  every 2.0 s, but only once 5 consecutive windows (~160 ms) score < 0.1 confidence —
  a reset mid-word would cost more than it saves. Nobody else in either wave does this.
- Smart Turn v3 (`local_smart_turn_v3.py:_predict_endpoint`): truncate/pad the
  utterance tail to exactly 8 s, Whisper-feature front-end, endpoint iff p > 0.5.
  Params (`base_smart_turn.py:27-29`): stop_secs=3, pre_speech_ms=500, max 8 s.
- Turn strategies (`turns/user_turn_strategies.py`): default start =
  VAD + Transcription; default stop = Smart Turn v3. `FilterIncompleteUserTurnStrategies`:
  the LLM must open every reply with ●/◐/○ (complete / incomplete-short 5.0 s /
  incomplete-long 10.0 s); only ● finalizes the turn — the LLM grades its *own*
  completeness as a gating token.
- **Speculation, productized** (`turns/speculation_gate.py` + `eager_end_of_turn_mixin.py`):
  an STT service may *predict* EOT; the LLM answers immediately but the
  `SpeculationGate` (OPEN/HOLDING/DROPPING) holds every response frame until
  `UserStoppedSpeakingFrame` confirms; `EagerEndOfTurnCancelFrame` discards it.
  Match policy defaults to NormalizedMatch (committed transcripts get re-cased/
  re-punctuated); speculation_timeout=5.0 s so a dead predictor can't mute the bot.
- Weakness (code-visible): holding is *unbounded* in the gate — the bound lives in
  the strategy, a split-brain invariant a host can violate. VAD stop_secs 0.2 s is
  aggressive; it works only because Smart Turn sits behind it.
- **Steal verdict: YES** — Silero reset discipline + speculation-gate semantics +
  ●/◐/○ self-grading token are all portable to v2's stdlib loop. BSD-2: code liftable.

### 2. livekit/agents — 14,853★, ALIVE, Apache-2.0
Flow: WebRTC room → Silero VAD plugin → STT → `AgentActivity` → turn handling
(`voice/turn.py` option resolution) → LLM (optional preemptive) → TTS → room_io.
- **Silero plugin** (`livekit-plugins-silero/.../vad.py:67,110`): activation_threshold
  0.5 default; deactivation = max(activation − 0.15, 0.01) — a hysteresis band so
  borderline frames don't flap speech on/off.
- **Endpointing defaults** (`voice/turn.py`): fixed mode min_delay 0.5 s / max_delay
  3.0 s; streaming sessions min 0.3 s / max 2.5 s; dynamic mode alpha 0.9.
- **`DynamicEndpointing`** (`voice/endpointing.py:49-135`): min_delay is *learned* —
  an ExpFilter (α=0.9) over (a) between-utterance pauses and (b) the pause before an
  immediate interruption (a proven false-EOT teaches the floor upward). Overlap with
  agent speech is explicitly excluded from the statistics. max_delay is never
  learned — "there is no natural lower max to observe."
- **Interruption options**: min_duration 0.5 s, resume_false_interruption=True with
  false_interruption_timeout 2.0 s (interrupt → silence 2 s → it was false → agent
  *resumes its sentence*), backchannel_boundary (1.0 s, 1.0 s) around turn edges.
- **Preemptive generation**: on by default; LLM only (preemptive_tts=False), skipped
  when user speech > 10.0 s, max 3 attempts/turn. Turn detector events also carry a
  `backchannel_probability` — the agent can decide to say "mm-hm" *instead of* taking
  the turn (local mini EOU model returns None for it; server model fills it).
- EOU plugin (`turn_detector/english.py`): per-language `unlikely_threshold`; text is
  normalized before inference. Weakness: the good EOU models are server-side; the
  local mini model drops the backchannel signal entirely.
- **Steal verdict: YES** — dynamic endpointing (learned floor, α=0.9) and the
  false-interruption resume are the two most production-proven ideas in either wave.
  Apache-2.0: liftable with attribution.

### 3. Soul-AILab/SoulX-Duplug — 324★, ALIVE, Apache-2.0
A *semantic VAD microservice*: plug into any cascade; it replaces silence timers.
- Model: Qwen3-0.6B with expanded vocab, LoRA r=32/α=64, GLM-4-Voice tokenizer
  (`config/config.yaml`). Per 160 ms chunk (chunk_size=2560 @16 kHz; back-context
  15,360 spl ≈ 0.96 s; lookahead 640 spl = 40 ms) it emits one state token:
  `<|user_idle|>`, `<|user_nonidle|>`, `<|user_backchannel|>`, (+complete/incomplete
  family). Turn decision = state machine over tokens, not probabilities.
- `service/model.py:state_predict` — **far-field guard**: RMS < 0.02 AND no speech
  yet AND model says nonidle → treat as distant TV/another room: reset, stay idle.
- `service/model.py` wait logic: after user pauses, count idle chunks;
  wait_idle_cnt ≥ max_wait_num=8 (≈1.28 s) → commit ASR over the accumulated buffer
  and return state "speak". History capped at 5 chunks; >200 chunks of silence with
  no speech → session reset (memory hygiene).
- **Word-boundary repair**: when speech resumes after idle/backchannel, it walks
  history backwards (≤5 chunks) and re-concatenates the clipped chunk audio into
  buffer_for_asr — the first syllable swallowed by the previous chunk boundary is
  recovered instead of transcribed as garbage.
- Weakness: CUDA/bf16 assumed; the 0.6B judge costs a full LLM forward per 160 ms
  chunk — fine on a server GPU, heavy for a 6 GB card already running ASR+LLM+TTS.
- **Steal verdict: DESIGN YES, MODEL NO** — steal the state-token vocabulary and the
  back-fill repair; run the *policy* in v2 with Smart-Turn-class small models.

### 4. ASLP-lab/Easy-Turn — 149★, ALIVE, Apache-2.0 (paper: arXiv 2509.23938)
- Architecture (from `Easy_Turn/.../conf/train.yaml` + `wenet/LLM/`): Whisper
  transformer encoder (16 heads) → link module → **Qwen2.5-0.5B-Instruct** (LoRA)
  generates the turn label. Two modalities — acoustic (prosody) + linguistic (ASR
  tokens) — most open models use only one.
- Four states: complete / incomplete / backchannel / wait. Trained on a released
  1,145 h corpus (580 complete / 532 incomplete / 10 backchannel / 23 wait).
- Measured (RTX 4090, their table): 850 MB params, 263 ms latency, 2,559 MB GPU;
  accuracy 96.33 % complete, 97.67 % incomplete, 91 % backchannel, 98 % wait —
  vs Smart Turn v2 (95 MB, 27 ms, 78.67/62 %) and TEN Turn Detection (text-only,
  needs Paraformer in front, 204 ms, 7.2 GB footprint).
- Weakness: 263 ms/decision is the *whole* endpointing budget of a tight cascade;
  the backchannel class has only 10 h of training data (class imbalance shows: it's
  their worst score). Chinese-first data (WeNetSpeech).
- **Steal verdict: BENCHMARK YES** — the 4-state taxonomy + open testset is the
  yardstick to score v2's endpointing against; the model itself is too heavy/slow
  for the 2060 next to everything else.

### 5. streamcoreai/streamcore-server — 235★, ALIVE, Apache-2.0 (Go, WebRTC/WHIP)
- `internal/pipeline/bargein.go` — **barge-in as transcript classification**, the
  anti-VAD position: `isMeaningfulBargeInTranscript` requires (≥2 tokens AND ≥1
  content word of len ≥3) OR a command token; pure backchannel tokens
  (`backchannelWordTokens`) never interrupt, checked *after* commands so "okay stop"
  interrupts but "okay yeah" doesn't. `isStrongBargeInCommand` = {stop, cancel,
  hang up} punches through even the readback guard.
- Turn merging (`bargein.go:endsTerminal/endsIncomplete/endsDictation`): trailing
  terminal punctuation shrinks the merge window; trailing conjunction/article/filler
  extends it; spelled dictation ("…n z y", digit runs) gets a far longer window
  (callers pause ~600 ms between spelled segments).
- `internal/pipeline/partial.go` — **reflexes**: partial transcripts are matched
  against a snapshotted tool registry; safe tools fire *on the partial* (dedup TTL
  10 s) so lookups start before the turn ends. `duck.go` ducks agent audio under
  user speech instead of hard-cutting.
- Weakness: the token lists are English telephony-shaped; Hinglish backchannels
  ("haan", "accha", "theek hai") would need a local list — but the structure
  (two-tier predicates, ack-vs-answer bars at different strictness) transfers.
- **Steal verdict: YES, TOP-3** — this predicate stack is ~150 lines of stdlib Go→
  Python translation and fixes v2's known false-barge-in class without any model.

### 6. bolna-ai/bolna — 798★, ALIVE, Apache-2.0 (telephony, India)
- `bolna/constants.py` (597 lines of scar tissue) — the most honest constants file
  in either wave. Deepgram Flux: EOT_THRESHOLD=0.7, **EAGER_EOT_THRESHOLD=0.5**
  (speculative LLM starts at 0.5 confidence), EOT_TIMEOUT_MS=500 (hard force),
  TURN_STALL_FLOOR_S=3.0, STALL_HANGUP_HARD_CAP_S=60.0, DEFAULT_MAX_SILENCE_REPEATS=2,
  LLM_GENERATION_TIMEOUT_S=60.0, DUPLICATE_RESPONSE_SIMILARITY=0.9 (near-dup agent
  replies are suppressed), STUCK_AUDIO_GATE_RELEASE_S=2.0.
- `agent_manager/interruption_manager.py:13` — interruption needs
  `number_of_words_for_interruption=3` words (strictly greater) **or** an exact
  accidental-interruption phrase; the mirror predicate `is_false_interruption`
  reclassifies late. Per-call interruption counters + per-turn latency annotation
  (was_interrupted) make tuning data-driven.
- `input_handlers/default.py` — **played-audio truth**: telephony "mark" events ACK
  each agent audio chunk; Bolna tracks `last_final_chunk_played_ts` and answers
  `get_response_heard_by_user()` — history stores what the caller *actually heard*,
  the exact v2 utterance-record rule, implemented for phones. Plivo latency is a
  rolling mean of the last 10 mark samples (seeded 0.25 s).
- Weakness: constants are per-provider whack-a-mole (11 ASR/TTS vendors, each with
  keyterm/prompt caps) — the file *is* the vendor-quirk database.
- **Steal verdict: YES** — eager-EOT 0.5/0.7 two-threshold pattern + the mark-ACK
  heard-truth ledger for v2's phone channel.

### 7. pguso/voice-agents-from-scratch — 49★, ALIVE, MIT
A runnable book (chapters 00–07); ch. 06 is the cleanest minimal duplex reference.
- VAD chapter: SR=16,000, BLOCK=512 samples (32 ms), RMS threshold 0.02.
- `turn_taking.py:72-74,145-165` — **energy barge-in done carefully**: LEAD_IN_S=1.0
  (gate arms 1 s after playback starts, swallowing the speaker's own startle/echo),
  RMS_THRESH_BARGE=0.055, SUSTAIN_BLOCKS=4 (4×32 ms ≈ 128 ms of *sustained* loud
  audio before cancel fires). Llama.cpp LLM (temp 0.7, 256 max tokens), Whisper STT,
  Kokoro TTS, all local — proof the whole loop fits consumer hardware.
- Weakness (theirs, named): RMS barge-in can't tell user speech from TV/echo —
  exactly the failure class v2's novel-word rule exists to kill; energy-only is a
  teaching step, not a product answer.
- **Steal verdict: YES for constants** — lead-in + sustain-count is a 10-line guard
  that belongs in front of *any* energy fallback path. MIT: liftable.

### 8. protoLabsAI/protoVoice — 8★, ALIVE, NO LICENSE FILE (ideas only)
Pipecat-based, but its `agent/` layer is original and unusually well-argued.
- `agent/bargein.py` — **BargeInGate**: cites LiveKit production data (2025) that
  ~51 % of VAD barge-ins are false (coughs, TV, "mm-hm", pets). On UserStartedSpeaking
  during bot speech it *holds* the frame for grace_ms=350: UserStopped inside the
  window → suppress; a Transcription/Interim frame inside the window → real words,
  flush immediately; timeout → flush as a normal interrupt. Worst case cost = 350 ms,
  paid only when the bot is speaking.
- `agent/backchannel.py:62` — COMMIT_GRACE_MS=180: agent backchannels are committed
  only after a 180 ms re-check ("below perceptual threshold").
- `agent/delivery.py:92,221` — outbound delivery policies (NEXT_SILENCE, WHEN_ASKED)
  with a 0.6 s silence-settle so proactive messages land in pauses, not over speech.
- **Steal verdict: DESIGN YES (no license → re-implement)** — the 350 ms hold-and-
  classify gate composes with v2's novel-word rule: hold first, classify by content,
  cut only on evidence.

---

## MEDIUM READS

### 9. xcc-zach/xtalk — 248★, ALIVE, Apache-2.0
Full-duplex cascade as a *module registry + event bus* (`src/xtalk/serving/event_bus.py`:
typed events, subscribe/unsubscribe, 1,000-event history). Models are swappable
containers: ASR, TTS, VAD, diarization, forced aligner, punctuation restorer,
*speech speed controller*, captioner. Turn detection has **four interchangeable
backends** (`models/turn_detector/`): TurnSense (remote model, periodic inference
with pause/interrupt result paths), XTurnix (streaming snapshots + longest-common-
prefix transcript tracking), an LLM detector, and a SoulX-Duplug adapter whose
comments document the commit rule — a candidate "speak" is only committed after
enough following idle chunks confirm it. VAD: Silero wrapper, threshold 0.5, strict
512-sample frames, per-session state isolation. **Steal:** the detector-backend
interface itself — v2 should treat endpointing as a pluggable strategy with a
shared contract, exactly like its provider chain treats LLMs.

### 10. TEN-framework/ten-framework — 11,181★, ALIVE, Apache-2.0
Graph-runtime (C core, extensions as nodes). `extension/ten_turn_detection/`:
turn-keeping is an **LLM judge** — config.py: temperature 0.1, top_p 0.1,
force_threshold_ms=5000 (a 5 s watchdog force-finishes if the judge stalls),
keepalive 600 s; the judge emits finished/unfinished special tokens over the
streaming transcript. `ten_vad_python` is the lightweight sibling. Ecosystem note:
Easy-Turn's table shows TEN's text-only judging needs an ASR in front and lands
86.67/89.3/91 % — respectable, and zero extra audio models. **Steal:** the 5 s
force-finish watchdog pattern for any judge-based endpointing v2 adopts.

### 11. HenryZ838978/VoiceAgent-600ms — 4★, ALIVE, Apache-2.0
A latency-budgeted build with the discipline v2 should copy: 600 ms *perceived*
budget (their doctrine: >800 ms reads as "talking to a machine"). Two routes on one
base — cascade (measured 458 ms first response) and end-to-end omni (250 ms first
frame, 10.5 GB VRAM — *does not fit* a 6 GB 2060), barge-in cut 160 ms both routes.
`engine/` includes FireRedVAD wrapper (threshold 0.5), a dedicated `turn_detector.py`,
`speaker_vad.py`, and `filler.py` — generated filler utterances mask LLM think-time.
Chat-state SFT for ~$20 makes the cascade sound native. **Steal:** the explicit
budget table + filler masking; reject the omni route on VRAM math alone.

### 12. dograh-hq/dograh — 5,907★, ALIVE, BSD-2-Clause
Self-hosted Vapi/Retell alternative; the pipeline is Pipecat under a product shell
(FastAPI `api/`, campaigns, MCP tools, RNNoise in `api/native/`). An alembic
migration literally named `retire_provisional_vad_turn_start` is the tell: they
shipped VAD-provisional turn starts, measured them in production calls, and retired
them — the same lesson as protoVoice's 51 % statistic, learned the expensive way.
**Steal:** treat that migration as evidence — v2's roadmap should skip provisional-
VAD turn starts entirely and start from transcript/model-confirmed starts.

### 13. Omni-Interaction-Gander/Omni-Interaction-Agent — 569★, ALIVE, Apache-2.0
MiniCPM-o-class omni runtime (`gander_runtime/`). Its gem is bookkeeping:
`media_timeline.py` — every browser PCM frame carries an `AudioFrameHeader`
(start_sample, sample_count, sequence, captured_at_ms) and an `AudioCaptureTimeline`
maps frames onto the model's fixed-duration units *sample-exactly*, so gaps/dups are
detectable instead of silently shifting the stream. Plus `duplex_bridge.py`,
`lean_realtime.py`, a codex_coordinator + worker-tool router (the agent talks while
background workers act). **Steal:** sample-indexed audio bookkeeping if v2 ever
streams mic audio across a process boundary (phone/web clients).

### 14. Logos-Flux/spark-voice-pipeline — 19★, ALIVE, LICENSE present
Single-file Starlette WebSocket server (VibeVoice TTS). `voice_chat_streaming.py`:
SAMPLE_RATE_IN=16000, OUT=24000; `SentenceBuffer.min_chars=10` — accumulate LLM
tokens, cut at the first sentence end once ≥10 chars exist, stream PCM16 per
sentence; a `/voice-simple` full-response endpoint is kept as the measurable
baseline ("slightly higher latency"). Claims 766 ms to first audio (DGX Spark
hardware — not transferable to a 2060, and they say so via hardware framing).
**Steal:** nothing new beyond reconfirming clause-cutting — but its honesty pattern
(ship the slow path as the built-in A/B baseline) is worth copying in v2's tests.

### 15. acatovic/ova — 174★, ALIVE, MIT
"Fully local ASR + LLM + TTS" — but `ova/mlx_pipeline.py` gives it away: it's
Apple-Silicon MLX-first. `pipeline.py:OVAPipeline` still has two portable details:
ASR CUDA-graphs are *disabled on purpose* (`_disable_asr_cuda_graphs`, graph capture
breaks on variable-length audio) and decoding config is centralized per profile.
**Steal verdict: NO for v2's Windows/2060 target** — recorded as a negative result:
"fully local" claims need a platform check before they mean anything to us.

### 16. FireRedTeam/FireRedChat — 593★, ALIVE, Apache-2.0
Self-hosted full-duplex stack = two model servers + agent glue: `fireredasr-server`
(streaming ASR HTTP service, `server/src/main.py` + routes) and `fireredtts-server`,
with an `agents-playground` for the dialogue layer. FireRedASR/TTS are the same
models VoiceAgent-600ms builds on (its `firered_vad.py` threshold 0.5 belongs to
this family). Architecture lesson: ASR and TTS as independent HTTP services with
health endpoints — the cascade survives one model server dying. **Steal:** service
split for v2's Wave-4 voice if local models move off-process; the models themselves
are Mandarin-strong, English-usable.

### 17. moonshine-ai/moonshine — 11,259★, ALIVE, custom source-available LICENSE
C++ streaming STT core (ONNX) built for *live* transcription: the Python examples
(`examples/python/mic_transcription.py`, `agent_flow.py`) show the intended shape —
continuous mic stream, per-line finalized callbacks, plus `ollama-voice/` (Moonshine
STT → Ollama → TTS) which is the closest published cousin of v2's local path.
Moonshine's design center is latency-to-first-token on weak CPUs (Pi-class), with
intent/command recognition in the same engine. **Steal:** candidate STT for v2's
wake-followup transcription on CPU fallback; license is custom — read before any
redistribution.

### 18. fluxions-ai/vui — 774★, ALIVE, LICENSE present (Vui)
Vui Nano: a 219M-param *conversational* TTS — trained on real dialogue so fillers
and prosody are in-domain. `src/vui/` is a real engine: `streaming.py`,
`inference.py`, Qwen-based codec (`qwen_codec.py`), forced alignment (`align.py`,
trellis/backtrack word timings), speaker encoder. The alignment module matters
beyond TTS: word-level timings of *your own output* are what make echo-timeline
mapping (Wave-1's top mechanism) precise. **Steal:** evaluate as the Piper upgrade
path for English; Hinglish quality unproven — benchmark before adopting.

### 19. neosun100/personaplex — 10★, ALIVE, MIT (wrapper) + Moshi code (own licenses)
Docker/REST/MCP packaging of NVIDIA PersonaPlex (Moshi-lineage full-duplex model):
18 voices, persona via text prompt, single-container GPU service. The wrapper is
thin; the substance is upstream Moshi (frame-synchronous speech-text interleaving —
the model *is* the pipeline). **Steal verdict: NO for v2 now** — PersonaPlex-class
models don't fit 6 GB alongside everything else and offer no tool-use surface;
revisit if a ≤3B duplex model with function calling appears.

### 20. OpenMOSS/SpeechGPT-2.0-preview — 374★, ALIVE, Apache-2.0
End-to-end spoken LM: ultra-low-bitrate streaming codec jointly modeling semantics
+ acoustics, speech-text mixed architecture + multi-stage training so text skills
(tool calls, search) survive voice training. Claimed **<200 ms** practical latency
with natural interruption. Hard limits, stated by the authors: trained only on
Chinese speech; **English voice unsupported**; release is a demo (`demo_gradio.py`),
not a serving stack. **Steal verdict: NO (watch-list)** — proof of where the
ceiling is, not a component.

### 21. rogerchappel/bargekit — 5★, ALIVE, MIT
Browser-side VAD/barge-in primitives (JS). `src/contracts.js:63-102` — DEFAULT_CONFIG:
speechThreshold 0.58, minSpeechMs 120, silenceMs 450, debounceMs 80; named presets
shift all four coherently (quiet-room: 0.64/140/520/90; noisy: 0.44/110/380/60) and
`tuning.js` *auto-calibrates*: threshold = clamp(noiseCeiling + 0.04, 0.04, 0.5)
from measured room noise. **Steal:** preset bundles + noise-floor auto-calibration
for v2's setup wizard — thresholds should be measured in the user's room, not shipped
as universal constants. MIT: liftable.

### 22. haoku123/dsh-voice — 4★, ALIVE, LICENSE present (TS, DeepSeek Harness plugin)
Browser mic → host. `src/asr.ts`: SenseVoice (sherpa-onnx) is *non-streaming*, so
"live" captions = re-decode the growing buffer, gated by PARTIAL_MIN_S=0.5 and a
min-hold segment of 0.25 s (below that SenseVoice "mostly returns noise");
ENERGY_THRESHOLD RMS=0.015 on 1024-sample/64 ms ticks; NLMS AEC runs browser-side
(`src/aec.ts`). A `SentenceSegmenter` + `tts-queue.ts` handle the speak side.
**Steal:** the re-decode-preview pattern is the honest way to fake streaming with a
batch ASR — v2's faster-whisper path can use the same gating constants.

---

## QUICK READS

23. **Ikaros-521/RealtimeSTT_LLM_TTS** (435★, MIT) — web-served RealtimeSTT fork +
    streaming LLM + GPT-SoVITS/Edge-TTS; `normal_interval 0.5` s interim cadence.
    Tutorial-grade glue; nothing to steal beyond the cadence default.
24. **bloodraven66/Low_latency_Spoken_Dialogue_System_RAG** (2★, no license) —
    `endpoint_anticipation/` is the idea: predict the endpoint *before* it happens
    and pre-warm RAG retrieval. Small code, right instinct; superseded by
    pipecat/livekit speculation machinery.
25. **ekleziast/kiwi-voice** (13★, LICENSE present) — Home Assistant voice with
    speaker recognition + voice-gated security; `kiwi/api/audio_bridge.py:51`
    _SILENCE_THRESHOLD=0.015 RMS energy gate feeding VAD. The speaker-gating
    (only the owner's voice may issue commands) is a genuinely v2-shaped idea for
    the phone channel.
26. **FahadiF/Edge-Voice-Assistant** (8★, Apache-2.0) — clean modular local stack
    (`eva/asr/fasterwhisper.py`, `eva/audio/chunker.py`, registry pattern for ASR).
    Competent, conventional; the registry-per-stage layout mirrors v2's own.
27. **ictinnovations/telephony-voice-agent-benchmark (tvbench)** (3★, LICENSE
    present) — measures what callers *hear*: AudioSocket 20 ms frame pacing,
    worst-burst-frames, continuity gaps. **Steal the metric mindset:** v2's voice
    tests should assert frame pacing, not just total latency.
28. **coval-ai/benchmarks** (103★, Apache-2.0) — reproducible TTS/STT/S2S latency+
    accuracy harness. Use its methodology to score v2's providers instead of vibes.
29. **disler/personal-ai-starter-pack** (201★, NO LICENSE) — fixed-duration record →
    transcribe → LLM → speak loop (`main.py:record_audio(duration=...)`). The
    anti-pattern baseline: no VAD, no streaming, no interruption. One line.
30. **mallahyari/RealtimeSTT-TTS** (50★, NO LICENSE) — backend/frontend wrapper over
    the RealtimeSTT library; library-grade, no original pipeline logic found.
31. **ahmad2b/langgraph-voice-call-agent** (49★, LICENSE present) — LiveKit +
    LangGraph call agent; the graph is the brain, voice is LiveKit's defaults.
    Confirms the framework-defaults path is viable but unoriginal.
32. **avera-labs/ConversationalVoice** (70★, LICENSE present) — a *dataset* repo
    (full-duplex speech data + scoring scripts), not a system. Useful only as
    training/eval material for a future v2 turn model.
33. **pegainfer-project/pega-omni** (47★, Apache-2.0 via Cargo.toml) — Rust
    OpenAI-compatible speech serving: streaming TTS + GPT-Live full-duplex sessions.
    Structure-read only; Rust serving is off-path for v2's Python core.
34. **xkx-hub/SID-bench** (23★, NO LICENSE) — Qwen team's interruption benchmark
    from *real* human dialogue (3,700 clips EN/ZH + 500 noise/silence traps):
    genuine interruption vs backchannel is the scored distinction. **Steal as an
    eval:** run v2's barge-in classifier against its protocol before trusting it.

## STRUCTURE-ONLY (clone transport failed repeatedly — not code-verified)

35. **inokoj/VAP-Realtime** (114★, LICENSE present) — real-time Voice Activity
    Projection: a CPC/transformer model predicts both speakers' voice activity
    ~2 s into the future (p_now/p_future distributions), letting a system pre-plan
    turn shifts instead of reacting. ONNX/TFLite/TFJS exports exist (`tools/`).
    Concept is the far end of the speculation spectrum; unverified at code level
    here (3 clone attempts died mid-pack).
36. **adventists-ai/duplexjev** (29★, LICENSE present) — DuplexJev-4B/32B "speech
    decision models": a dedicated model whose only job is the duplex decision
    (speak/listen/wait), with benchmarks + integrations dirs. Same caveat: structure
    from repo listing, code unread (2 clone attempts died mid-pack).

---

## FIELD-LEVEL WEAKNESSES (visible only in code, across Wave 2)

1. **Learned endpointing is paywalled or heavy**: the accurate judges are either
   server-side (LiveKit EOU, Deepgram Flux), 0.5B+ local models (Duplug, Easy-Turn),
   or an LLM call per pause (TEN). A 6 GB local stack must *combine* cheap signals
   (VAD + transcript completeness) — nobody ships that hybrid well yet. Open lane.
2. **Constants are copied, not measured**: 0.5 Silero thresholds and 0.5–0.8 s
   endpoint delays recur verbatim across dozens of repos (bargekit's auto-calibration
   and LiveKit's dynamic floor are the exceptions). Most "tuned" systems are tuned
   to their author's room and microphone.
3. **Backchannel handling is the new frontier and mostly absent**: only Easy-Turn,
   Duplug, LiveKit's server model and streamcore's token lists treat "mm-hm" as a
   first-class signal; everyone else either interrupts on it or ignores real speech
   mixed with it.
4. **Heard-truth bookkeeping is rare**: Bolna's mark-ACK ledger and Wave-1's
   utterance record are the same insight; most frameworks still log what they
   *generated*, corrupting history after every interruption.
5. **End-to-end omni models demo well and deploy narrow**: Chinese-first training,
   10.5 GB+ VRAM, no tool surface. The cascade's boring modularity is why every
   *product* in this wave is still a cascade.

---

## TOP 5 MECHANISMS (Wave 2, ranked by value to v2)

1. **Learned/dynamic endpointing floor** (livekit `DynamicEndpointing`): endpoint
   delay as an EMA (α=0.9) over the *user's own* pauses, with false-EOT events
   teaching the floor up and max_delay as a pure clamp. ~60 lines of stdlib,
   benefits every single turn, zero model cost.
2. **Speculation with a hold-gate** (pipecat `SpeculationGate` + eager EOT;
   Deepgram Flux 0.5-eager/0.7-commit in bolna): start the LLM on a *predicted*
   endpoint, hold all output frames, release on confirmation, drop on cancel,
   5 s watchdog. Converts endpointing latency from serial to overlapped.
3. **Barge-in as transcript classification** (streamcore predicates + bolna's
   >3-words gate + protoVoice's 350 ms hold): three independent layers — content
   test, command whitelist, backchannel exclusion — none of them volume-based.
4. **Semantic-VAD state tokens + chunk back-fill** (SoulX-Duplug): a 4-state
   turn vocabulary (idle/nonidle/backchannel/…) decided per 160 ms chunk, with
   backward history re-concatenation repairing chunk-boundary word cuts, and an
   RMS far-field veto (0.02) for TV-in-another-room false wakes.
5. **Silero state-reset discipline** (pipecat `silero.py`): recurrent VAD state
   poisoned by music/noise is reset every 2.0 s, gated on 5 consecutive windows
   below 0.1 confidence. Invisible failure mode, 15-line fix, nobody else does it.

## TOP 3 STEALS FOR JARVIS v2

1. **Endpointing pack**: LiveKit dynamic floor (α=0.9 EMA, learned min / fixed
   3.0 s max, streaming variant 0.3/2.5 s) + pipecat's ●/◐/○ LLM self-grade as the
   completeness signal + TEN's 5 s force-finish watchdog. All stdlib; directly
   replaces fixed silence timers in `voice_loop.py`.
2. **Barge-in pack**: protoVoice's 350 ms hold-gate (frame-level, composes with
   v2's novel-word rule) + streamcore's predicate stack ported to Python with a
   Hinglish backchannel/command list ("haan/accha/theek" ≠ interrupt; "ruko/stop/
   bas" = strong interrupt) + pguso's lead-in/sustain guard on the energy path.
   SID-bench's protocol as the acceptance test.
3. **Speculative-turn pack**: eager-EOT two-threshold pattern (start LLM at
   0.5-confidence/transcript-complete, commit at 0.7/confirmed-stop), output held
   behind a speculation gate with normalized-transcript matching and a 5 s
   withdrawal timeout, preemptive work capped (≤10 s utterances, ≤3 tries/turn).
   Expected effect: perceived latency drops by roughly the endpoint delay
   (~300–500 ms) on most turns — the single biggest responsiveness win available
   without new models, and it fits the 2060 because the speculation is the *same*
   LLM call, just started earlier.

**Constants to adopt as v2 defaults (Wave-2 converged):** 16 kHz mono · 32 ms
frames for energy paths · Silero act 0.5 / deact act−0.15 · endpoint min learned
(EMA α=0.9, seed 0.5 s) / max 3.0 s (2.5 s streaming) · barge-in hold 350 ms ·
false-interruption resume after 2.0 s silence · first TTS sentence cut at ≥10
chars + terminal punctuation · speculation watchdog 5.0 s · VAD state reset 2.0 s
gated at conf < 0.1 × 5 windows.
