# TEAM 10 — INTERNET APPS & WEB-BASED AI ASSISTANTS: PhD Reverse-Engineering Report

**Mission:** Reverse-engineer JARVIS-like assistants that live on the internet and the web — not just desktop GitHub repos. Four surfaces: (A) web-based voice assistants & AI companions, (B) Chrome-extension assistants + WhatsApp/Telegram/Discord bots, (C) smart-home voice stacks + closed flagship teardowns.

**Total targets: 49** (goal was 40) — 35 open codebases read at code level, 14 closed products analysed from public evidence only.
- Slice A (web voice & companions): 18 targets — 10 open repos/SDKs code-read, 8 closed products
- Slice B (extensions & messaging bots): 15 targets — 7 extensions, 7 bots, 1 bonus
- Slice C (smart home + flagship teardowns): 16 targets — 10 open stacks, 6 closed products

Full per-target PhD sections are appended after this synthesis (Parts A, B, C, verbatim from the slice reports).

## Honesty ledger (FAILED-first)
- GitHub's MCP API hit **HTTP 429** during slices B and C. Per hard-stop policy the researchers stopped and did **not** retry via alternate routes; gaps were filled from DeepWiki code indexes (which cite `file:line`), official docs, store listings and framework literature. A few star counts and licences in Parts B/C are marked [MC]/[UK] and **must be re-verified before reusing code** (patterns are safe to copy; code is not, until licence is confirmed).
- Closed products are labelled **[PUBLIC EVIDENCE]** vs **[INFERENCE]** throughout. No internals were invented.
- One non-finding worth recording: `HumeAI/voice-starter` does **not exist** (404). Deepgram's js-sdk licence was verified MIT.
- Both big negative case studies (Rabbit R1, Humane Ai Pin) are documented as failures — see "The company dies tomorrow" test below.

---

## TOP 5 MECHANISMS (across all 49 targets)

### 1. The Interruption Watermark — ElevenLabs JS SDK (Slice A)
TTS audio chunks carry a **monotonic `event_id`**. When the user barges in, the client sets `lastInterruptId = current event_id` and silently **drops every in-flight or queued chunk with id ≤ watermark**. No timers, no state machine races — post-interruption "ghost audio" is mathematically impossible. This is the exact bug class that crippled JARVIS v1 (echo-guard dead code, permanent mute after barge-in, per the v1 failure autopsy).

### 2. Grammar-Compiled Deterministic Intent — Rhasspy → Hassil (Slice C)
One human-written sentence-grammar file compiles to **both** a constrained STT language model **and** a finite-state intent transducer. The speech decoder physically cannot output words the assistant cannot act on; matching returns confidence 1.0 or no-match — **zero hallucination by construction**. OVOS pairs this with a confidence-tiered pipeline (`stop_high → converse → padatious_high → adapt_high → persona-LLM → fallback_low`): deterministic matchers first, the expensive LLM only on a miss, and the last-used skill gets first refusal on follow-ups.

### 3. Wyoming Protocol Stage Events — Home Assistant / Rhasspy (Slice C)
The whole voice pipeline speaks ~20 JSON-header + binary-payload events over TCP (`audio-chunk`, `transcribe`, `detection`, `run-pipeline` with explicit start/end **stage**). Every stage (wake, STT, intent, TTS) is an independently runnable, swappable process; satellites are found via Zeroconf on convention ports (Piper 10200, Whisper 10300, openWakeWord 10400). HA's **Pipeline Debugger** records every run (audio → transcript → decision) as a replayable trace — and ESPHome's event vocabulary (`WAKE_WORD_END, STT_END, INTENT_PROGRESS, TTS_STREAM_START…`) enables *streaming TTS while the agent is still thinking*.

### 4. Full-Duplex Background Delegation — OpenAI GPT-Live / Gemini Live pattern (Slice A)
No turn boundary at all: the voice model continuously decides speak/listen/tool, and **hard questions are delegated to a heavyweight model in the background** while the conversation continues. Tools are declared `blocking` vs `background` (Gemini Live's `behavior` flag); background work plays a holding line and injects its result when ready. The voice path can never freeze waiting for a tool or the cloud brain. LiveKit Agents adds the complementary front-end: an audio model judges the first few hundred ms of an overlap in ≤30 ms and **rejects ~51% of VAD barge-ins as backchannels** ("mm-hmm" is not an interruption), with speculative LLM/TTS generation rolled back if the user resumes. Deepgram Flux completes the picture: one fused model emits *turn-complete* transcripts from semantic completeness, not silence (vendor-claimed median end-of-turn detection <300 ms).

### 5. Real-Browser Inheritance — mcp-chrome + Nanobrowser (Slice B)
Instead of a fresh automation profile (no logins, bot-detected), an MV3 extension + Native-Messaging bridge exposes the owner's **actual authenticated Chrome** (cookies, sessions, tabs) to the agent as MCP tools — with on-device embeddings (`@xenova/transformers` + hnswlib-wasm). Control discipline comes from Nanobrowser: a **Planner/Navigator/Validator** split with per-role models (planner replans every 3 steps on a smart model, navigator clicks cheap over an **indexed DOM tree**, not pixels), `maxSteps`/`maxFailures` circuit breakers, and a URL firewall. This is v2's UIA-first/vision-last doctrine applied to the web — and it beats screenshot-watching (A-Eye's cost/privacy trap).

**Runner-ups:** Hume EVI's prosody-as-metadata loop (~48-dim perceived-expression scores on every message, honestly labelled as interpretation-likelihood, `chat_group_id` session resume); Vapi's assistant-as-a-JSON-object (personalisation = a config diff); openWakeWord's frozen shared embedding + ~1MB per-phrase ONNX classifiers trained on synthetic Piper voices; Stanford Almond/Genie's inspectable typed ThingTalk programs as the action layer; LangBot's capabilities≠permissions intersected at bind time (AGPL — ideas only); wassenger's ack-first webhook + cheapest-first eligibility gauntlet + two-phase quota.

---

## TOP 3 STEALS FOR JARVIS v2 (ranked by value × ease)

### Steal 1 — Interruption watermark in the TTS playback queue (ElevenLabs)
~15 lines of stdlib Python: tag every utterance chunk with a monotonic id, keep a `last_interrupt_id`, drop anything ≤ watermark at dequeue time. Directly deletes the v1 autopsy bug class (ghost audio, barge-in permanent mute) by construction rather than by guard code. **Do this first.**

### Steal 2 — Deterministic grammar tier under the LLM (Rhasspy/Hassil + OVOS tier order)
Each v2 skill ships a `phrases.txt` (including Hinglish variants — "band kar", "chrome khol" — with Genie-style template generation for test coverage). Routing order per utterance: exact intent → fuzzy intent → LLM → clarifying fallback. Result: hallucination-proof PC commands at <50 ms, LLM budget reserved for the long tail. Pair with the learned end-of-turn policy (Steal 3's front half) for the biggest perceived-intelligence jump on the RTX 2060.

### Steal 3 — Blocking/background tool declarations + Wyoming-style run traces
Every skill manifest gains a `blocking|background` field (Gemini Live pattern): background tools speak a backchannel line and deliver results asynchronously — the voice loop never stalls on web fetches, code runs or the cloud brain. Simultaneously, adopt the Wyoming/ESPHome event names inside v2's existing voice loop and log every run as a replayable trace (audio meta → transcript → router decision → tool call → TTS text); ship HA's dry-run sentence parser as a debug tool. This makes every future voice bug debuggable from evidence instead of vibes.

**Next tier (documented in the parts, build when scheduled):**
- **Browser sense via MV3 extension + Python Native-Messaging host** (mcp-chrome pattern, Nanobrowser controls) — authenticated Chrome as tools.
- **Telegram module hardening** (Slice B): wassenger's ack-first + eligibility gauntlet + durable per-chat quota + ~20-message context cap; AstrBot's `platform:type:chat_id` addressing, **venue-scoped memory** (group content never recalls into the owner's session) and a self-hearing guard.
- **Gladys Plus E2EE relay blueprint** for phone remote if Telegram's trust model is ever outgrown (per-message AES-GCM-256 wrapped in RSA-OAEP-2048, ECDSA-signed, expiry anti-replay) — plus Apple's per-turn **"privacy receipt"**: a log line showing exactly what left the machine.
- **"The company dies tomorrow" test** (from Rabbit R1 + Humane post-mortems): with zero cloud keys and the internet unplugged, local Ollama + deterministic intents + Piper must still run JARVIS's core. Rabbit's "LAM" was cloud scripting over stored user sessions with hardcoded keys disclosed and 95% abandonment; Humane's cloud-dependent pin was bricked on 28 Feb 2025 after HP's $116M asset buy. v2's local-first design already passes this test on paper — keep it that way.

---

---

# PART A — WEB VOICE ASSISTANTS & AI COMPANIONS (Slice A, full)

# MEGA-SCAN WAVE 2 — TEAM 10 SLICE A
## Web-Based Voice Assistants & AI Companion Web Apps — PhD-Level Reverse Engineering

**Scope:** Browser voice assistants + AI companion web apps. ~17 targets: 9 open repos/SDKs (code or README/SDK surface read) + 8 closed products/platforms (PUBLIC EVIDENCE ONLY).
**Evidence labelling:** `[PUBLIC EVIDENCE]` = docs / API reference / changelog / published teardown or benchmark in sources retrieved this pass. `[INFERENCE]` = my reasoned extrapolation — never presented as a fact about internals. `[CODE READ]` = implementation file / README / SDK source actually retrieved this pass.
**Method note / failure first:** GitHub MCP search worked for discovery, then `get_file_contents` began timing out and finally returned **HTTP 429 (rate limit)** — per hard-stop policy, GitHub was not retried after that. Licences for several repos therefore could **not** be re-verified from their LICENSE files in this pass; those are marked `[UNVERIFIED — check LICENSE before copying any code]`. Nothing below claims a licence that was not seen.
**Date:** 2026-10-20. Hardware lens for stealability: JARVIS v2 = Python, stdlib-first, Windows, RTX 2060 6GB, local-first, cloud brain optional.

---

## 0. THE ONE-PARAGRAPH SYNTHESIS

The whole field has converged on three architectures, in historical order:
1. **Cascaded pipeline** — mic → STT → LLM (text) → TTS → speaker. Every handoff loses prosody and adds latency (ChatGPT Gen-1: ~1,700 ms dead air `[PUBLIC EVIDENCE]`, search result citing VentureBeat Oct-2024 analysis). Still the only fully *controllable / observable / local* design — this is JARVIS's design, and Pipecat + LiveKit are its industrial forms.
2. **Native speech-to-speech (S2S)** — one model ingests raw audio and emits raw audio (GPT-4o AVM / GPT-Live, Gemini Live Native Audio, Hume EVI, xAI Grok Voice). Prosody, laughter, hesitation survive; turn-taking moves *inside* the model; you lose transcript-perfect observability and any local run.
3. **Orchestrated pipeline-as-a-service** — Vapi / Deepgram Voice Agent / ElevenLabs Conversational AI / Cartesia Line: someone else runs the cascade on WebRTC/WebSocket edge infra, you supply prompt + tools + provider keys. Latency is bought with geography (edge inference) and streaming-at-every-stage, not with a better brain.

The cleverness worth stealing is almost never the model. It is: **(a) turn-detection as a learned model, not a silence timer; (b) interruption with stale-audio invalidation; (c) speculative / preemptive generation; (d) ephemeral-token browser security; (e) separating the audio path from slow tool logic so a tool call can never stall speech.**

---

# PART A — OPEN REPOS / SDKs (code read)

## A1. pipecat-ai/pipecat-examples + Pipecat framework (Daily Co)

- **Discovery:** GitHub search `pipecat examples` → `pipecat-ai/pipecat-examples ★398` "Pipecat example applications"; framework package `pipecat-ai` on PyPI `[CODE READ — PyPI project page + DeepWiki pipeline analysis]`.
- **Architecture as evidenced:** Server-side Python bot process; browser/phone client joins a **Daily (WebRTC)** room (also `FastAPI WebSocket`, `SmallWebRTCTransport`, local transport). The bot is a **linear pipeline of FrameProcessors**:
  `transport.input() → RTVIProcessor → context_aggregator.user() → LLM service → transport.output() → context_aggregator.assistant()` `[CODE READ — DeepWiki citing server/bot.py:96-105]`.
- **HOW IT ACTUALLY WORKS (inside):**
  - Everything is a **Frame**: `AudioRawFrame`, `VideoFrame`, `TranscriptionFrame`, `TextFrame`, `LLMRunFrame`, plus control frames (`EndFrame`, start/stop speaking frames `frames.py:536-633`). Frames flow downstream; system/interruption frames also flow upstream — that bidirectionality is how a downstream VAD event can cancel upstream TTS.
  - **RTVI (Real-Time Voice/Video Interaction)** is a protocol layer between client and bot: the client doesn't just send audio, it sends/receives synchronised UI events (bot is speaking, transcript delta, config) so the web UI stays in lockstep with audio state.
  - **Smart Turn**: pluggable analysers — `LocalSmartTurnAnalyzer` (on-device, Torch), `LocalCoreMLSmartTurnAnalyzer`, `HttpSmartTurnAnalyzer` / `FalSmartTurnAnalyzer` (remote). Turn-end is a *classifier over the audio segment*, not `silence > X ms` `[CODE READ — DeepWiki Advanced Features citing base_input.py:230-321, base_output.py:310-324]`.
  - **Context aggregators** are separate user/assistant processors: user aggregator assembles transcripts+frames into LLM context; assistant aggregator captures what was *actually spoken* into history — the pattern that prevents "the bot remembers saying words it never finished saying."
  - Services are mix-and-match extras (`pip install pipecat-ai[deepgram|cartesia|openai|...]`): STT incl. Whisper/Deepgram, TTS incl. Cartesia/ElevenLabs/Piper/XTTS, S2S incl. OpenAI Realtime + Gemini Live, memory via mem0, VAD Silero/Krisp.
  - Canonical minimal bot (PyPI example `[CODE READ]`): `DailyTransport(room_url, token="", bot_name, DailyParams(audio_out_enabled=True))` + `CartesiaTTSService` → `Pipeline([tts, transport.output()])`, greet on `on_first_participant_joined` by `task.queue_frame(TextFrame(...))`, `EndFrame` on participant-left.
- **Clever mechanism:** Frame-typed pipeline + interruption-as-a-frame. Because cancellation is a first-class frame type, *any* processor can originate or obey it; no processor owns a special "stop" API.
- **Privacy/safety:** Self-hostable; audio goes to whichever STT/TTS providers *you* plug in — data-leaves-device is a deployment choice, not a framework property `[INFERENCE from the pluggable-service design]`.
- **Licence:** `[UNVERIFIED in this pass — 429]` (do not copy code until LICENSE checked; prior team notes in this workspace record Pipecat patterns as idea-stealable).
- **Stealability for JARVIS v2: ★★★★★ (patterns), ★★ (as a dependency).** JARVIS is stdlib-first/local — importing Pipecat + Daily contradicts local-first. Steal: (1) frame/event taxonomy, (2) user/assistant aggregator split, (3) Smart-Turn classifier interface with local/remote implementations behind one protocol.

## A2. livekit/agents (+ livekit-examples voice frontend pattern)

- **Discovery:** GitHub search → `livekit/agents ★14,853` "A framework for building realtime voice AI agents", Python, created 2023-10-19 `[CODE READ — search result metadata]`. Deep detail from LiveKit's own docs (docs.livekit.io, retrieved this pass).
- **Architecture as evidenced:** **Worker / Entrypoint / Session** triad `[PUBLIC EVIDENCE — LiveKit+Gemini slide deck + docs]`: a long-running **Worker** process registers with LiveKit (SFU media server, WebRTC rooms) and waits for jobs; per call, an **Entrypoint** runs once (connect to room, load context); an **AgentSession** wires STT/LLM/TTS-or-RealtimeModel + tools + turn detection into one conversation loop.
- **HOW IT ACTUALLY WORKS (inside):**
  - `AgentSession(turn_handling={"endpointing": {"min_delay": 0.3}, "interruption": {...}, "preemptive_generation": {"preemptive_tts": True}})` `[CODE READ — docs.livekit.io API reference]`. Endpointing defaults `min_delay 0.5 / max_delay 3.0 s`; dynamic endpointing (Python) adapts delay from the session's own pause statistics.
  - **Two-signal turn-taking** `[PUBLIC EVIDENCE — LiveKit docs + 2026 engineering analyses]`: (1) Silero VAD (acoustic, sub-ms/chunk) + (2) a **model-based audio turn detector** (v1 on LiveKit Inference, v1-mini local on CPU, 14 languages) that predicts end-of-turn from audio, not just transcript. Its predecessor, text-based `MultilingualModel` (a Qwen2.5-0.5B distillation), "cut false interruptions by 39%" and is now deprecated in favour of the audio model.
  - **Adaptive interruption handling** (default since Python Agents 1.5.0, Mar 2026 per analysis): when VAD fires over the agent's speech, a small audio model judges the first few hundred ms in ≤30 ms and **rejects ~51% of VAD-triggered barge-ins as backchannels** ("uh-huh") instead of killing the agent's turn. True barge-in: TTS cancelled, **the interrupted LLM turn is rolled back**, new input processed.
  - **Preemptive generation:** LLM (and optionally TTS) starts generating *before* end-of-turn is confirmed; if the user resumes speaking, the speculative work is discarded — trading compute for perceived latency.
  - **False-interruption recovery:** if the agent stopped for what turns out to be a non-interruption, it can resume its interrupted utterance rather than losing it.
  - Latency budget published in engineering guides: target time-to-first-audio <800 ms cascading = VAD ~50 ms + STT ~150 ms (streaming partials) + LLM TTFT ~400 ms + TTS first chunk ~150 ms + network ~50 ms (+100–300 ms SIP on phone).
  - STT can own turn detection: `turn_detection="stt"` delegates end-of-turn to models like AssemblyAI Universal / Deepgram Flux that emit their own EOT signal (`endpointing min_delay=0` then, to avoid stacking delays).
- **Clever mechanism:** Interruption is a *classification problem with a recovery path*, not a binary VAD trip — plus speculative generation hidden behind turn confirmation.
- **Privacy/safety:** Self-hostable SFU + agents; LiveKit Cloud optional. Krisp noise/background-voice cancellation is a metered cloud add-on (from May 2026, ~$0.002–0.004/min per analyses) — background-voice cancellation lifts STT accuracy a claimed 10–20% on noisy channels.
- **Licence:** `[UNVERIFIED in this pass — 429]`.
- **Stealability: ★★★★★ patterns / ★★ dependency.** Steal the triad of *endpointing-delay-as-statistics*, *adaptive (backchannel-aware) interruption*, and *preemptive generation with rollback*. A 0.5B-class turn classifier is exactly RTX-2060-sized; Silero VAD already in JARVIS's known stack.

## A3. HumeAI — @humeai/voice-react SDK + EVI web starter pattern

- **Discovery:** GitHub search for Hume returned empty via API (rate-limit era), but the SDK README was retrieved `[CODE READ]`: package `@humeai/voice-react`, `VoiceProvider` + `useVoice()` hook.
- **Architecture as evidenced:** Browser React client ↔ Hume cloud over **one WebSocket**. Client captures mic (Web Audio), streams audio up; server (EVI speech-language model) streams back `assistant_message` + `audio_output` (base64 audio) messages. Auth is by **short-lived access token** minted server-side from the API key — the key never ships to the browser (same ephemeral-credential pattern as OpenAI, §A5).
- **HOW IT ACTUALLY WORKS (inside):**
  - Message taxonomy `[CODE READ — Hume dev docs]`: inbound `chat_metadata {chat_id, chat_group_id}`, `user_message` (carrying `models.prosody.scores`), `assistant_message` (also carrying prosody scores), `audio_output {data: base64}`, `tool_call`. Outbound: `audio_input {data}`, `session_settings`, `user_input`, `assistant_input` (TTS-only mode), `tool_response` / `tool_error`.
  - **Every message carries expression-measurement scores** — e.g. `prosody.scores {Admiration: 0.031, Adoration: 0.0018, …}` (~48-dimension expression space, Cowen & Keltner-derived categories) measured **at sentence level** because word-level prosody is unstable `[PUBLIC EVIDENCE — EVI FAQ]`. The scores are *likelihood that a human observer would interpret the expression that way*, explicitly **not** a claim the speaker feels it — an unusually honest epistemic label worth copying.
  - **Session resumption:** store `chat_group_id` from `chat_metadata`; reconnect with `resumed_chat_group_id` query param / `resumedChatGroupId` prop → full prior context restored after a network drop or days later. Config may change on resume (with a warning that prompt/LLM changes may behave unexpectedly).
  - **Pause/resume assistant:** `pauseAssistant` stops EVI responding while chat history keeps accumulating; on resume the queued history is sent — i.e. "keep listening, don't answer yet" is a protocol state, not a mute hack.
  - Client surface (`useVoice`): `connect/disconnect, mute/unmute, muteAudio, setVolume (clamped 0–1), sendSessionSettings, sendUserInput, sendAssistantInput, sendToolMessage, clearMessages`, plus FFT / mic-level analysers for UI visualisations.
- **Clever mechanism:** Prosody-as-metadata on *every* turn in both directions — the LLM's TTS prosody is *guided by* the measured expression of the user, and the response's own expression is reported back, closing an affect loop inside one model ("speech-language model generates the language response and guides TTS prosody" — EVI FAQ).
- **Privacy/safety:** All audio leaves the device to Hume cloud `[PUBLIC EVIDENCE — it's a hosted WebSocket API]`; expression labels carry the not-a-diagnosis disclaimer above.
- **Licence:** SDK `[UNVERIFIED in this pass — 429]`.
- **Stealability: ★★★★.** Steal: (1) `chat_group_id` resumable-session design for JARVIS's session store; (2) pause-assistant protocol state; (3) a *cheap local prosody-features vector* (pitch/energy/rate — computable with stdlib DSP, no model) attached to each transcript in memory, so the persona can react to *how* Owais said it, and so records are labelled "perceived expression," never "felt emotion."

## A4. elevenlabs/elevenlabs-js — Conversational AI client SDK

- **Discovery:** `elevenlabs/elevenlabs-swift-sdk ★118`, web JS SDK README + source analysis retrieved `[CODE READ — SDK README + DeepWiki analysis of src/.../Conversation.ts]`.
- **Architecture as evidenced:** Browser/Node client ↔ ElevenLabs cloud over **WebSocket** (WebRTC also supported for agents). Server owns STT + turn-taking + LLM (or bring-your-own LLM endpoint) + Flash TTS; client owns mic capture, playback, and executing client-side tools.
- **HOW IT ACTUALLY WORKS (inside) — the single best interruption implementation in this slice:**
  ```ts
  // Conversation._handleMessage() (paraphrased from retrieved analysis)
  case "audio":
    if (parseInt(audioEvent.event_id) <= this.lastInterruptId) return; // stale — drop
    this.audioInterface.output(Buffer.from(audioEvent.audio_base_64, "base64"));
  case "interruption":
    this.lastInterruptId = parseInt(interruptionEvent.event_id);
    this.audioInterface.interrupt(); // halt playback, clear queued buffers, reset to idle — capture keeps running
  ```
  - **Monotonic `event_id` + `lastInterruptId` watermark** solves the race every naive implementation hits: audio chunks already in flight when the interruption is detected arrive *after* it and would play as "ghost audio." Anything `≤ watermark` is discarded on arrival. No timers, no guessing.
  - Interruption contract for the audio layer: immediate stop (ms), buffer clear, state→idle, **mic capture never interrupted**.
  - SDK also handles sequential ordering of audio events and base64 decode; history management is a first-class API.
- **Clever mechanism:** Watermark invalidation (above). Also (product side, §B4) the turn-taking model feeding this event.
- **Privacy/safety:** Cloud; agent config can enable/disable transcript/audio retention in the vendor dashboard `[INFERENCE — dashboard feature, not verified this pass; treat as unknown]`.
- **Licence:** `[UNVERIFIED in this pass — 429]`.
- **Stealability: ★★★★★ — copy the watermark verbatim as a pattern.** JARVIS v2's known worst bug class is exactly this (echo/barge-in ghosts, "permanent mute after interruption" from the failure autopsy in memory). A monotonic utterance-id + drop-stale-chunks rule is ~15 lines of stdlib Python in the TTS playback queue.

## A5. openai/openai-realtime-console (+ Cloudflare Workers relay pattern)

- **Discovery:** `openai/openai-realtime-console` README retrieved `[CODE READ]`; relay pattern corroborated by DeepWiki analyses of the console and of `cloudflare/openai-workers-relay` `[CODE READ]`.
- **Architecture as evidenced:** React browser app ↔ OpenAI Realtime API directly over **WebRTC** (audio tracks + an `oai-events` data channel for JSON events). Optional **relay server** (Node WebSocket proxy / Cloudflare Worker) for the WebSocket transport.
- **HOW IT ACTUALLY WORKS (inside):**
  - WebRTC path `[CODE READ — OpenAI docs example retrieved]`: browser `fetch("/token")` → server mints an **ephemeral key** (`POST /v1/realtime/sessions` with the real key; token valid ~60 s to *initiate*, session lives up to ~30 min) → browser `RTCPeerConnection`, `getUserMedia` mic track added, remote track → autoplay `<audio>`, data channel `oai-events` created → SDP offer POSTed to `/v1/realtime/calls` with `Authorization: Bearer <EPHEMERAL_KEY>` → answer applied. After setup, **media flows browser↔OpenAI with no app server in the path** — the server only mints tokens.
  - Relay path: `RealtimeRelay` class (`relay-server/lib/relay.js`) holds the real key in server `.env`, accepts keyless browser WebSocket connections, opens an authenticated upstream WebSocket, and forwards messages both ways. README is explicit the relay "is only a simple message relay" but is the interception point for custom instructions, event filtering, auth, rate-limiting, logging.
  - The console itself is a *debugging instrument*: a live event log panel showing every client/server event — the reference UX for "show me what the voice session is actually doing."
  - Function calling runs *in the client*: the model emits a function-call event over the data channel, the browser app executes it (e.g. map/weather widgets in the console) and returns the result into the same session.
- **Clever mechanism:** Ephemeral-token security boundary + media/logic split: WebRTC carries audio (UDP, loss-tolerant, ~100 ms class per Microsoft's Realtime docs) while the data channel carries events/tools — a slow tool can never block audio because it isn't *on* the audio path.
- **Privacy/safety:** Direct-WebRTC means raw audio leaves the device straight to OpenAI; with a relay, everything additionally transits your server (observability vs. exposure trade-off, stated in the relay docs).
- **Licence:** `[UNVERIFIED in this pass — 429]`.
- **Stealability: ★★★★.** For any future JARVIS web/phone remote: mint short-lived session tokens from the PC (which holds the real keys in the OS keyring), never ship keys to the phone/browser client. Also steal the event-log panel as a diagnostics surface.

## A6. AlexandreSajus/JARVIS — the canonical "JARVIS web" clone

- **Discovery:** GitHub search `web voice assistant` → `AlexandreSajus/JARVIS ★528` "Your own personal voice assistant: Voice to Text to LLM to Speech, displayed in a web interface", Python, topics: deepgram/elevenlabs/taipy `[CODE READ — search metadata + README retrieval]`.
- **Architecture as evidenced:** Python backend (Taipy web UI) running the classic cascade locally-as-a-server: browser mic → Deepgram STT → OpenAI LLM → ElevenLabs TTS → browser playback. The brain and all provider keys live in the Python process; the browser is a thin mic/speaker/UI.
- **HOW IT ACTUALLY WORKS (inside):** Turn-based (not full-duplex), exactly as its README enumerates `[CODE READ — README retrieved in the late-arriving GitHub batch]`: 1) user speaks into mic → 2) **Deepgram** voice-to-text → 3) text to **OpenAI GPT-3 API** → 4) response to **ElevenLabs** speech → 5) speech played via **Pygame** (i.e. playback is server/desktop-side, not Web Audio) → 6) conversation displayed in a webpage via **Taipy**. Conversation state is the message list held in the Python process.
- **Clever mechanism:** Honestly, its *simplicity*: it is the minimal proof that the cascade + a web UI is a weekend build — and therefore the baseline every fancier system in this file is measured against. Its limits (no barge-in, no streaming partials, latency = sum of three cloud round-trips) are the cascade's limits.
- **Privacy/safety:** Audio + text leave to three separate US cloud providers per turn; keys in local env.
- **Licence:** `[UNVERIFIED in this pass — 429]`.
- **Stealability: ★★★ (as a reference skeleton) / ★ (novelty).** Useful negative/positive control for JARVIS v2: Owais's build already exceeds it (local brain, wake word, PC control). Do not regress to turn-based cloud-only.

## A7. deepgram/deepgram-js-sdk — Voice Agent client

- **Discovery:** SDK README retrieved `[CODE READ]`; Voice Agent API design detailed in §B7.
- **Architecture as evidenced:** One WebSocket from client (browser via JS SDK, or server) to Deepgram, which internally orchestrates **Listen (Flux STT) → Think (LLM, yours or hosted) → Speak (Aura/Flux TTS)**. Function calls are emitted *to your client* as `FunctionCallRequest`; you execute and return `FunctionCallResponse`; a `client_side` flag decides who executes each function `[PUBLIC EVIDENCE — Deepgram function-calling docs analysis]`.
- **HOW IT ACTUALLY WORKS (inside):** The agent session is configured declaratively (listen/think/speak providers + prompt + functions) in a `Settings` message on the socket; thereafter the socket carries binary audio up, and JSON events + binary audio down, including barge-in signalling: on detected user speech the server tells the client to **flush its outbound audio buffer** (Twilio integration sends a `clear` event) `[PUBLIC EVIDENCE — Twilio×Deepgram integration write-up]`.
- **Clever mechanism:** The `client_side` split for tools — read-only hosted functions execute server-side (zero round-trip), side-effecting functions execute on *your* infra where your auth/data live. Directly applicable to JARVIS's phone-remote trust tiers.
- **Licence:** **MIT** `[CODE READ — README badge "license-MIT" linking ./LICENSE in deepgram-js-sdk, retrieved in late GitHub batch]`.
- **Stealability: ★★★★ (the tool-split + flush-on-barge-in protocol).**

## A8. cartesia-ai/cartesia-js — Sonic (TTS) + Ink (STT) client

- **Discovery:** SDK README retrieved `[CODE READ]`; model architecture in §B8.
- **Architecture as evidenced:** WebSocket streaming client: send text incrementally (even mid-sentence, as LLM tokens arrive), receive audio chunks with **word-level timestamps**; supports context objects that keep one continuous synthesis stream across many text sends so prosody doesn't restart per sentence.
- **HOW IT ACTUALLY WORKS (inside):** The client keeps a persistent WebSocket + a `context_id`; each `send(text)` appends to that context; the server (State-Space-Model Sonic, §B8) emits audio at ~40 ms time-to-first-audio class latency; timestamps let the client highlight words karaoke-style and, more importantly, know *exactly which words were already spoken* when an interruption lands.
- **Clever mechanism:** Continuous-context streaming + timestamped output = interruption can truncate history at the *word actually reached*, not the sentence sent. (Same "record what was spoken" doctrine JARVIS v2 already adopted for its voice loop — Cartesia is the commercial proof it matters.)
- **Licence:** `[UNVERIFIED in this pass — 429]`.
- **Stealability: ★★★★.** Pattern: TTS interface must return a spoken-progress cursor (words/chars actually played). If JARVIS's local Piper/Kokoro path lacks it, add a playback-position estimator (chars × per-voice rate) as the fallback cursor.

## A9. jedarden/duck-e — WebRTC rubber-duck with server-side tools (search-level)

- **Discovery:** GitHub search → `jedarden/duck-e ★54` "Voice rubber-duck debugging assistant: a FastAPI backend bridges the browser (WebRTC) to the OpenAI Realtime API, with server-side tools for web search, URL fetch, weather, and per-user memory" `[CODE READ — search metadata only; file read blocked by 429]`.
- **Architecture as evidenced:** The *inverse* of A5: instead of browser↔OpenAI direct, a FastAPI bridge terminates WebRTC server-side so **tools and per-user memory live on the server**, executed mid-conversation, while the Realtime model supplies voice. `[INFERENCE — bridge implies server can interpose tool results into the session]`.
- **Why it matters:** It is the small-scale template for JARVIS's Telegram/phone remote: PC-side bridge = tools + memory + keys stay home; the remote client is disposable.
- **Licence:** `[UNVERIFIED]`. **Stealability: ★★★★ (topology, not code).**

*(Also found, not deep-dived — discovery evidence only: `livekit-examples/voice-assistant-frontend` pattern (Next.js + LiveKit room UI), `leonvanzyl/elevenlabs-nextjs-conversational-ai ★41`, `donvito/nextjs-elevenlabs-agent ★45`, `kaymen99/AI-Voice-assistant ★82` (Deepgram+Groq+LiteLLM cascade with Gmail/Calendar tools), `ahmad2b/langgraph-voice-call-agent-web ★17` (LangGraph brain behind LiveKit transport — proof the brain and the voice loop can be fully decoupled), `NVIDIA/voice-agent-examples ★66` (Pipecat orchestrator).)*

---

# PART B — CLOSED PRODUCTS / PLATFORMS (PUBLIC EVIDENCE ONLY)

## B1. ChatGPT Voice — Advanced Voice Mode → GPT-Live (OpenAI)

- **Three generations** `[PUBLIC EVIDENCE — OpenAI launch material as summarised in retrieved analyses]`:
  - Gen 1 (2023) cascaded Whisper → GPT-4 → TTS: strict turns, ~1,700 ms latency, prosody lost at each handoff.
  - Gen 2 AVM (Jul–Sep 2024): single native-audio model (GPT-4o), interruptible, senses humour/sarcasm — but still turn-based, end-of-turn by silence → "even a brief pause or background noise could be mistaken for the end of turn" (OpenAI's own stated failure mode).
  - Gen 3 **GPT-Live** (announced Jul 8, 2026 per retrieved coverage): **full-duplex — no turn boundary at all.** The model continuously processes incoming audio while generating output and decides many times per second whether to speak, keep listening, pause, interrupt, or invoke a tool.
- **HOW IT ACTUALLY WORKS (inside, public claims only):**
  - **Background delegation:** GPT-Live hands harder questions to a frontier text model (GPT-5.5 in coverage) *in the background and keeps the conversation going* — the voice model is a real-time "front of house," the reasoning model is the kitchen. `[PUBLIC EVIDENCE]`
  - **Audio path separated from application logic**, so a slow tool/backend cannot stall speech; **media system rewritten in Go** (from Python) for smoother audio-frame delivery `[PUBLIC EVIDENCE — launch coverage]`.
  - Transport: **WebRTC** for ChatGPT clients (loss/change tolerant); Realtime API offers WebRTC (~100 ms class) / WebSocket (~200 ms) / SIP `[PUBLIC EVIDENCE — Microsoft Foundry Realtime docs table]`.
  - Realtime API mechanics: server VAD default, **semantic VAD** option (model judges completeness), function calling mid-conversation (adds ~400–800 ms felt latency when the tool itself is <200 ms, per production guide), prompt-cache discount ~80× on cached audio input is "the single biggest cost lever" `[PUBLIC EVIDENCE — 2026 production guide]`.
  - Safety posture (AVM launch): fixed preset voices, output filtering to block imitation of other voices and violent/copyrighted content `[PUBLIC EVIDENCE]`.
- **Clever mechanism:** Full-duplex decision loop + async frontier delegation. **Stealability: ★★★★★ as a *pattern* for JARVIS:** the local fast brain holds the conversation (acknowledge, clarify, small talk) while the cloud brain answers in the background — JARVIS's existing `consult_online_brain` mid-turn handoff is already a primitive version; make it *non-blocking*: speak a holding line, inject the deep answer when it lands, never freeze the audio path for a tool.

## B2. Gemini Live (Google)

- **Architecture** `[PUBLIC EVIDENCE — Google Cloud blog/docs]`: Single **native-audio model** (Gemini 2.5 Flash Native Audio, GA on Vertex AI; later 3.x Live line in docs) over **one bidirectional WebSocket**: raw **16-bit PCM 16 kHz in, 24 kHz audio out**, plus text, plus **video frames at ~1 FPS (JPEG)** for screen/camera context. Affective dialogue and proactive audio are config flags (default-on in the 3.8 Live docs table retrieved).
- **HOW IT ACTUALLY WORKS (inside, public claims only):** No STT→LLM→TTS hops: acoustic cues (pitch, pace, hesitation, laughter) are inputs to the same model that reasons; barge-in halts the output buffer mid-sentence; **function calling can be asynchronous non-blocking or `behavior="BLOCKING"` auto-cancelling** (3.8 docs) — i.e. the API itself exposes the "should this tool block speech?" decision. 3.8 adds "polite interruption downgrade" (waits when the user speaks, vs. 2.5's immediate overlap) and dynamic mid-stream language switching.
- **Latency:** Third-party testing blogs cite 250–450 ms responses `[PUBLIC EVIDENCE — secondary source, treat as indicative, not Google-published]`.
- **Privacy/safety:** Cloud-only; session context is in-session — "everything beyond it is your job (memory)" per LiveKit's Gemini guide `[PUBLIC EVIDENCE]`.
- **Clever mechanism:** Async-vs-blocking as a *declared property of each tool*. **Stealability: ★★★★★** — tag every JARVIS skill `blocking | background`: background skills get a holding response + late injection (see B1); blocking skills are the minority (stop, cancel).

## B3. Hume EVI 2 / EVI 3 (Hume AI) — the empathic companion engine

- **Architecture** `[PUBLIC EVIDENCE — Hume FAQ/docs, §A3 for protocol]`: Speech-to-speech **speech-language model** (not contingent on an external LLM for the first response — "therefore able to generate an initial response much faster"; frontier LLMs can be integrated for longer responses). WebSocket, ~500–800 ms average response (EVI 2, 40% faster than EVI 1); one enterprise case study reports 140 ms–1.3 s range under load and a reliable **end-of-speech signal** that lets integrators release inference resources instantly `[PUBLIC EVIDENCE — Hume/Journee case study]`.
- **Clever mechanism:** Emotion is a *measured signal with error bars*, in both directions (§A3), plus **in-conversation style prompting** ("speak faster / more excited" mid-session via session settings) and voice creation by *modulating parameters* (pitch/gender) rather than cloning a real person — a deliberate safety choice `[PUBLIC EVIDENCE]`.
- **Privacy/safety posture:** Hosted; expression measures explicitly framed as perceived-expression likelihoods, not diagnoses `[PUBLIC EVIDENCE — FAQ]`.
- **Stealability: ★★★★** — see A3 steals. The companion lesson: Pi-style warmth is not a prompt, it's a *feedback loop* (measure → adapt prosody → measure again).

## B4. ElevenLabs Conversational AI 2.0 / ElevenAgents

- **Architecture** `[PUBLIC EVIDENCE]`: Hosted agent platform; WebSocket (or WebRTC/SIP via Twilio/Vonage trunks); Flash v2.5 TTS (~75 ms model inference; 150–300 ms time-to-first-audio end-to-end per integration guides); regional inference (US/EU-Netherlands/APAC-Singapore) — a Tokyo client saves ~100 ms RTT via Singapore `[PUBLIC EVIDENCE — secondary guide]`.
- **Clever mechanism — the turn-taking model:** Hybrid: VAD + a learned model over **filler words, prosody, speech rhythm, micro-pauses** to separate a *thinking pause* from *end of sentence*; exposed to developers as **turn eagerness (Eager/Normal/Patient) + turn timeout 1–30 s**. Deepgram's competing teardown notes ElevenLabs publishes **no false-interruption precision/recall** — a calibration gap worth noting `[PUBLIC EVIDENCE — Deepgram analysis]`. Client-side, the `interruption` event + event-id watermark (§A4) does the rest. **Audio tags** (`[laughs] [whispers] [hesitates] [sighs]`) in generated text steer non-verbal vocalisation in v3-class models.
- **Stealability: ★★★★** — "turn eagerness" as a *user-facing JARVIS setting* (Patient for Owais thinking aloud, Eager for quick commands) is a one-enum feature with outsized feel. Audio tags are a free persona upgrade for any TTS that supports them, and a no-op text convention for ones that don't.

## A10. VapiAI/web — @vapi-ai/web SDK (code read, late batch)

- **HOW IT ACTUALLY WORKS (inside)** `[CODE READ — README retrieved]`: `npm install @vapi-ai/web`; `const vapi = new Vapi('your-public-key')` — note a **public key** (publishable, scoped) in the browser, distinct from server keys; `vapi.start(assistantId)` for a pre-configured assistant, or `vapi.start({model:{provider:"openai", model:"gpt-3.5-turbo", messages:[{role:"system",...}]}, voice:{provider:"11labs", voiceId:"burt"}, ...})` to define the whole assistant **inline in client code**. The browser SDK is a thin call-control layer (Daily/WebRTC underneath per Vapi's platform design, §B5); all STT/LLM/TTS runs server-side at Vapi.
- **Clever mechanism:** Assistant-as-a-JSON-object — the entire agent (model + messages + voice) is one declarative config passed at call start, so A/B tests and per-user personalisation are just config diffs.
- **Licence:** `[UNVERIFIED]`. **Stealability: ★★★ (config pattern).**

## B5. Vapi (hosted voice-agent orchestration)

- **Architecture** `[PUBLIC EVIDENCE]`: API-native orchestration over WebRTC/telephony: you configure **transcriber + model + voice** (200+ provider integrations, BYOK or self-hosted models), Vapi runs media, endpointing, interruption, tool-webhooks. Assistants are stateless; scale bottleneck is *your* webhook server (~500 concurrent lightweight calls per Node instance in one field guide).
- **Numbers, honestly split:** Vendor claim **sub-500 ms**; independent field guides measure **550–800 ms typical, 1,200–1,800 ms** for a naive GPT-4 + Turbo-TTS cascade (STT 300–500 + LLM 400–800 + TTS 500–700), and note default **endpointing = 500 ms of the budget is just waiting-for-silence**; streaming partial transcripts + early function calls save 200–400 ms of *perceived* latency. Webhooks time out at 5 s → async-ack pattern required for slow tools `[PUBLIC EVIDENCE — field guides]`.
- **Clever mechanisms:** **Backchanneling** as a config ("mm-hmm" while listening), ~4,200 configuration points including pronunciation, noise suppression, max duration; **simulated-agent test suites + hallucination testing + A/B of prompt/voice/flow** before production.
- **Privacy/safety:** SOC 2 / HIPAA options; **Zero Data Retention is a paid add-on** (cited $1,000/mo) — i.e. retention is the default business model, privacy is the upsell `[PUBLIC EVIDENCE — review aggregating pricing]`.
- **Stealability: ★★★** — steal backchanneling (a local "mm-hmm / got it" clip played while the cloud brain thinks costs nothing and masks latency) and *simulated-user testing* for JARVIS skills.

## B6. Pi (Inflection AI) — the companion web app

- **What it is** `[PUBLIC EVIDENCE — Inflection launch post + 2026 coverage]`: "Personal Intelligence": a kind/supportive companion optimised for **EQ over IQ** — coach/confidante/sounding-board; web + mobile + messaging surfaces; no account needed to start; account = persistent memory across sessions (help-centre: login saves history past 60 days).
- **HOW IT ACTUALLY WORKS (inside, public claims only):** Proprietary in-house models; the *product* mechanism is memory + persona, not voice tech: short, warm, curious turns; it asks follow-ups instead of dumping answers. **Pi Journeys** (2026 Labs relaunch) makes the memory *structured*: onboarding asks your life stage, then builds a **structured memory around the people in that context** — a "memory prosthetic" that resurfaces what you last discussed with a person and nudges you to call them; users can delete/manage recorded people `[PUBLIC EVIDENCE — VentureBeat]`.
- **Privacy posture** `[PUBLIC EVIDENCE — Pi privacy policy as summarised Aug 2026]`: inputs **are used to train models unless you opt out** in settings; `!delete` in chat deletes the account; inputs generally retained ≤15 days after deletion with exceptions; single messages deletable immediately from history.
- **Clever mechanism:** Structured *relationship* memory (people × life-stage × last-discussed) + pro-social nudges — memory organised around the user's relationships, not around chat logs.
- **Stealability: ★★★★★ for JARVIS's memory redesign** — Owais's memory system already has people pages; add per-person `last_discussed / open_thread` fields and a proactivity rule "resurface an open thread when that person comes up / after N days." Pure data-model change, zero new infra.

## B7. Deepgram Voice Agent API + Flux

- **Architecture** `[PUBLIC EVIDENCE]`: One WebSocket, three declared stages (Listen/Think/Speak, §A7), $4.50/hr flat agent pricing cited. **Flux** is the interesting part: a **conversational speech-recognition model that fuses transcription + turn detection in one model** — no separate VAD/endpointing stage.
- **HOW IT ACTUALLY WORKS (inside, public claims only):** Flux emits **turn-complete transcripts** (no partial-reconstruction), decides end-of-turn from acoustic + semantic + conversational context; `eot_threshold` configures the latency/accuracy trade-off, including **eager EOT for speculative response generation**; median EOT detection **<300 ms (p95 1.5 s)** per model card; claimed −200–600 ms agent latency and ~30% fewer false interruptions vs. VAD pipelines `[PUBLIC EVIDENCE — Deepgram/Together model material; vendor claims, no independent replication in this pass]`. **Flux TTS** (GA, `/v2/speak`) is *turn-based*: you stream LLM tokens in, `send_flush()` ends the turn, audio returns while you're still sending, and the model **retains conversational state between turns** so delivery stays consistent without SSML restyling.
- **Clever mechanism:** Fusing EOT into the STT model itself — semantic completeness ("the sentence is grammatically/thoughtfully finished") as an endpoint signal.
- **Stealability: ★★★★ (concept) / ★ (the model — cloud, English-first benchmarks; Hindi/Hinglish unverified).** Local approximation for JARVIS: faster-whisper partials + a tiny completeness check (last-token punctuation/logprob + a 0.5B text classifier, LiveKit-style) before declaring end-of-turn. Even a heuristic version beats a fixed 800 ms silence timer.

## B8. Cartesia — Sonic (TTS) / Ink (STT) / Line (agent platform)

- **Architecture** `[PUBLIC EVIDENCE]`: Sonic is built on **State Space Models (SSMs), not transformers** — O(N) sequential processing vs. O(N²) attention — yielding **~40 ms time-to-first-audio** (Sonic-3/Turbo class; 40–90 ms across sources, all vendor/benchmark-derived) over streaming WebSocket; voice cloning from ~10 s; 40+ languages with accent localisation; pronunciation dictionaries; speed/emotion controls. Line is their agent platform on top; Ink is the matching streaming STT ("fastest time-to-first-transcript" claim).
- **Clever mechanism:** Architecture choice as latency strategy: for *streaming generation of a 1-D signal*, an SSM's constant-size state beats attention — the same reason JARVIS should prefer streaming-native local models (Piper/Kokoro class) over chunked transformer TTS for the first word, reserving quality models for long-form.
- **Stealability: ★★★ (principle: optimise TTFA, not total synthesis time; measure JARVIS's TTS in TTFA).** Cloud-only, so no direct local use without API key.

## B9. Microsoft Copilot Voice

- **Architecture** `[PUBLIC EVIDENCE — Microsoft blog via coverage; Windows-forum technical summary is secondary/INFERENCE-grade and flagged as such]`: Copilot Voice (web + Windows + mobile) is cloud speech-to-speech backed by OpenAI models (Voice/Think Deeper made free+unlimited Feb 2025; Think Deeper = o1-class reasoning). Four preset voices; voice is a *mode* of the general Copilot chat, sharing its memory/connectors. The often-repeated "on-device NPU wake-word spotter + hybrid local/cloud" description comes from Copilot+ PC coverage `[INFERENCE-grade secondary source — not confirmed from a Microsoft primary doc in this pass]`.
- **Clever mechanism (product-level):** Voice as a *mode toggle on a general assistant with existing memory and app integrations*, not a separate voice product — plus a "dreamy water" listening visualisation as the entire voice UI. Minimalism as the interface.
- **Stealability: ★★★** — confirms JARVIS's one-assistant-many-surfaces direction (HUD + Telegram + chat window sharing one brain/memory).

---

# PART C — CROSS-CUTTING TABLES

## C1. Latency anatomy (all vendor/secondary claims, labelled)

| System | Claim | Source quality |
|---|---|---|
| ChatGPT Gen-1 cascade | ~1,700 ms to first word | Secondary (VentureBeat analysis via summary) |
| OpenAI Realtime WebRTC | ~100 ms transport class; <500 ms design target | Microsoft docs table / production guide |
| GPT-Live | Full-duplex, no turn gap (no single number published in sources) | Launch coverage |
| Gemini Live | 250–450 ms response | Third-party testing blog — indicative only |
| Hume EVI 2 | 500–800 ms avg; 140 ms–1.3 s in enterprise case study | Vendor + Hume case study |
| ElevenLabs Flash v2.5 | ~75 ms inference; 150–300 ms TTFA end-to-end | Integration guides (secondary) |
| Vapi | <500 ms vendor; 550–800 ms typical; 1,200–1,800 ms naive cascade | Vendor vs field guides |
| Deepgram Flux EOT | <300 ms median detection, p95 1.5 s | Model card (vendor) |
| Cartesia Sonic | ~40 ms TTFA | Vendor benchmark via comparisons |
| LiveKit cascade budget | <800 ms TTFA total (50/150/400/150/50 stage split) | Engineering guides |

**Lesson:** in a cascade, LLM time-to-first-token (~400 ms) and the endpointing wait (~300–500 ms) dominate. TTS model choice is third. Optimise in that order.

## C2. What leaves the device

| Target | Audio leaves device? | To whom | Retention posture (public) |
|---|---|---|---|
| Pipecat / LiveKit (self-hosted) | Only to providers you plug in | Your choice | Yours |
| AlexandreSajus/JARVIS | Yes, every turn | Deepgram + OpenAI + ElevenLabs | Provider defaults |
| Hume EVI / ElevenLabs / Vapi / Deepgram / Cartesia | Yes | That vendor (+ your chosen LLM) | Vapi: ZDR is paid add-on; others: not verified this pass |
| ChatGPT Voice / Gemini Live / Copilot Voice | Yes | OpenAI / Google / Microsoft | Consumer-product policies (not deep-read this pass) |
| Pi | Yes (text+voice) | Inflection | Trains on inputs unless opt-out; ≤15 days post-deletion (policy summary) |
| OpenAI Realtime direct WebRTC | Yes, browser→OpenAI, no app server | OpenAI | Ephemeral-token session model |

## C3. Licence / stealability summary

All repo licences in this slice are `[UNVERIFIED in this pass]` due to the GitHub 429 hard-stop — **one exception verified from its README badge in the late-arriving batch: deepgram-js-sdk = MIT** — **check each other LICENSE file before copying code; patterns/ideas in this file are documented from public behaviour and are safe to reimplement.** Also verified negatively: `HumeAI/voice-starter` returns 404 (no such repo); the Hume web pattern lives in the `@humeai/voice-react` SDK (§A3), not a starter repo. Known from workspace prior knowledge (not re-verified): Pipecat/LiveKit are permissively licensed ecosystems — treat as *likely* stealable code, pending the check.

---

# PART D — TOP STEALS FOR JARVIS v2 (ranked by value ÷ effort)

1. **Interruption watermark (ElevenLabs JS SDK, §A4).** Monotonic audio `event_id`; on barge-in set `last_interrupt_id`; the playback queue drops any chunk `≤ watermark`. Directly kills JARVIS's ghost-audio / permanent-mute bug class. ~15 lines, stdlib only.
2. **Non-blocking tool declaration + background brain delegation (Gemini Live `behavior` flag + GPT-Live delegation, §B1/B2).** Tag each skill `blocking|background`; background work speaks a holding/backchannel line and injects results when ready; the audio path never waits on a tool. JARVIS already has the seed (`consult_online_brain`) — this makes it architectural.
3. **Learned/heuristic end-of-turn + turn-eagerness setting (LiveKit / Deepgram Flux / ElevenLabs, §A2/B4/B7).** Replace fixed silence timeout with: Silero VAD + semantic-completeness check on partial transcript + per-user pause statistics (dynamic endpointing), exposed as Eager/Normal/Patient. Biggest single *feel* upgrade available locally on a 2060.
4. **Resumable sessions by group-id (Hume, §A3)** — store `chat_group_id`, resume with full context after crash/network drop. JARVIS's session store + Telegram remote both want this.
5. **Structured relationship memory (Pi Journeys, §B6)** — people-pages gain `last_discussed/open_thread`; proactivity resurfaces open threads. Zero infra.
6. **Ephemeral tokens for any web/phone client (OpenAI console, §A5)** — PC mints 60-second tokens; real keys never leave the keyring/PC.
7. **Backchannel clips + TTFA metric (Vapi/Cartesia, §B5/B8)** — measure and optimise time-to-first-audio; mask unavoidable waits with a spoken "mm-hmm."

## Honest gaps
- GitHub 429 cut off file-level reads for pipecat-examples, livekit/agents, Vapi/Cartesia example repos and all LICENSE files — those sections rest on READMEs, official docs, PyPI pages and DeepWiki code analyses retrieved this pass, and are labelled accordingly.
- No independent (non-vendor) latency replication was found for Flux, Sonic, or EVI figures; all are reported as claims.
- Siri-on-web: skipped per instructions (no public web product evidence).
- Grok Voice (xAI) surfaced only as a LiveKit Inference listing + docs.x.ai speech-to-speech page (server-VAD, session resumption, idle-timeout proactive re-engagement — a nice steal: `idle_timeout_ms` re-engages the user after silence, re-arming after every response); not counted as a full target.

---

# PART B — CHROME EXTENSIONS & MESSAGING BOTS (Slice B, full)

# MEGA-SCAN Wave 2 — Team 10 Slice B: Chrome-Extension AI Assistants + WhatsApp/Telegram/Discord AI Bots

**Date:** 2026-10-20 · **Targets covered:** 14 (+1 bonus) · **Method:** GitHub MCP search (3 queries completed, then HTTP 429 hard-stop on the GitHub provider — no further GitHub API calls made in this slice) + DeepWiki code-level indexes + Chrome Web Store listings + framework comparison literature. Where a fact rests on DeepWiki/README rather than a direct file read by this agent, it is tagged. Licences not directly verified via the API are tagged [MC]/[UK] and must be re-checked before any code reuse.

**Confidence key:** [VC] >95% · [HC] 80–95% · [MC] 60–80% · [SP] 40–60% · [UK] unknown.

---

## TL;DR — The two architectures that matter

1. **Extensions split into two species.** (a) *Side-panel companions* (Syncia, hasan-py, A-Eye): content script harvests selection/page text → background service worker calls an LLM with the user's own key → answer renders in a side panel or floating menu. No server. (b) *Agent bridges* (mcp-chrome, Nanobrowser): the extension is not the brain at all — it is a **tool surface** (DOM, tabs, screenshots, your logged-in session) exposed over a local protocol (MCP / CDP-via-`chrome.debugger`) to a brain that lives elsewhere. Species (b) is the strategically important one for JARVIS.
2. **Bots split by transport legality.** Official-API bots (Meta Cloud API / Wassenger, Telegram Bot API, Discord gateway) verify signatures, ack webhooks instantly and process in the background, and keep per-chat state in a small TTL store. Unofficial bots (askrella via `whatsapp-web.js` + Puppeteer) get full consumer-WhatsApp access at the price of QR-login fragility and an explicit ban risk. Every production-grade bot independently converged on the same pipeline: **eligibility filter → quota check → transcribe → build bounded context → LLM (+tools) → deliver → persist flag/metadata**.

---

# PART A — CHROME-EXTENSION AI ASSISTANTS (7)

## A1. hangwin/mcp-chrome — ★12,498 [VC, GitHub search 2026-10-20]

*TypeScript · The most-starred target in this slice.*

### HOW IT ACTUALLY WORKS (inside)
Three execution tiers (DeepWiki, citing `README.md:17-31`, `app/native-server/package.json`, `app/chrome-extension/package.json`):

- **Chrome extension (`chrome-mcp-server`, WXT + Vue 3)** runs in **five isolated JS contexts**: background service worker (`background/index.ts` — central message router + tool execution), popup, side panel, builder page, per-tab content scripts (`*.content.ts`), and an **offscreen document** for heavy compute (on-device ML inference, GIF encoding) that a service worker cannot host.
- **Native bridge (`mcp-chrome-bridge`, Node.js)** is a Chrome **Native Messaging host**: Fastify HTTP server on **port 12306** speaking MCP over HTTP+SSE, plus a STDIO MCP transport (`mcp-chrome-stdio`) for clients without HTTP. Entry: `app/native-server/src/cli.ts`. It translates MCP JSON-RPC ⇄ Native Messaging frames to the extension.
- **Inter-context routing is namespaced and typed**: `app/chrome-extension/common/message-types.ts:1-396` defines `BACKGROUND_MESSAGE_TYPES` (16-91), `OFFSCREEN_MESSAGE_TYPES` (94-103), `CONTENT_MESSAGE_TYPES` (106-118), `TOOL_MESSAGE_TYPES` (121-179); the background worker is a command-pattern dispatcher mapping type → handler.
- **On-device semantics inside the extension**: `@xenova/transformers` (ONNX/WASM) + `hnswlib-wasm-static` give local embeddings + vector search over tab content — "semantic search across your open tabs" without any page text leaving the machine.
- **Record & Replay**: `ContentRecorder` (injected script capturing click/type/navigate with debouncing) → `SessionManager` (background, batches steps) → `FlowStore` (IndexedDB, with migrations) → `FlowRunner` (executes flows as a **DAG with topological sort**); triggers = URL patterns, context menus, commands, DOM events.
- Agent chat lives in the side panel (`entrypoints/sidepanel/components/AgentChat.vue`, state via `useAgentThreads.ts` composables) and talks HTTP/SSE to the bridge, which fronts external engines (Claude Code, Codex).

### Clever mechanism
**Inherit the user's real browser.** Because tools execute inside the user's daily Chrome, the agent gets their cookies, logins, bookmarks and history, and is indistinguishable from the user to bot detection — no fresh Playwright profile, no re-login. The extension is a *capability server*, the brain is interchangeable.

### Privacy / safety
Page content flows to whichever MCP client/LLM the user connects — the extension itself is local, but connecting a cloud brain exfiltrates page text by design. Blast radius is large (20+ tools incl. network capture via WebRequest/debugger APIs); there is no per-tool approval layer documented — trust is placed entirely in the connected client.

### Licence / stealability
Licence: not returned by search; DeepWiki/chatforest list it as "—" **[UK — verify before reuse]**. **Verdict: STEAL THE PATTERN, not necessarily code.** JARVIS v2 equivalent in Python: a tiny MV3 extension + Native Messaging host in Python (stdlib `struct`-framed JSON on stdin/stdout) exposing `get_page_text / get_selection / list_tabs / screenshot` as MCP-style tools to the local brain. This is the cheapest way to give JARVIS eyes on the *authenticated* web.

---

## A2. nanobrowser/nanobrowser — open-source AI web agent extension [HC]

### HOW IT ACTUALLY WORKS (inside)
Hierarchical multi-agent system, all inside the extension background (`chrome-extension/src/background/index.ts:1-362`):

- **Three agents, three models allowed**: `NavigatorAgent` (every step; output schema `{current_state, action[]}`), `PlannerAgent` (strategic replanning, default every 3 steps — `planningInterval`), `ValidatorAgent` (at conclusion; checks result against user intent). All extend `BaseAgent` (`chrome-extension/src/background/agent/agents/base.ts:1-228`): LLM call → structured output → **manual JSON-extraction fallback for models without structured-output support** → Zod schema validation. Navigator implementation: `agents/navigator.ts:1-679`.
- **Browser layer is Puppeteer-over-`chrome.debugger`**: `browser/transport.ts` implements a custom `ExtensionTransport` so Puppeteer Core speaks CDP through the extension debugger API; `browser/page.ts:buildDomTree()` builds an indexed DOM tree (interactive elements numbered) + screenshot; `browser/context.ts` manages tab attach/switch/cleanup.
- **Self-correction loop**: failed action → Navigator retries differently; failed strategy → Planner replans; hard stop via `maxSteps` / `maxFailures` in `generalSettingsStore`.
- **Typed storage layer**: separate stores — `llmProviderStore` (11+ providers, keys in Chrome local storage), `agentModelStore` (role→provider+model+params, **including an STT role**), `chatHistoryStore`, `firewallStore` (URL allow/deny lists gating navigation).
- Voice input exists as a first-class service: `chrome-extension/src/background/agent/services/speechToText.ts`.

### Clever mechanism
**Planner/Navigator temperature split + per-role model assignment**: planner runs hot (creative decomposition) on a smart expensive model, navigator runs cold (precise clicking) on a cheap fast model, validator judges at the end. Cost and reliability both come from *not* using one model for everything. The DOM-tree-with-indices (not screenshots) is the default observation — pixels only when `useVision` is on.

### Privacy / safety
Best-in-slice posture: no vendor server at all, keys in local storage, no telemetry, Ollama supported for zero-egress runs; firewall allow/deny lists bound where the agent may navigate. Residual risk is inherent: page content is sent to the chosen LLM provider.

### Licence / stealability
Apache-2.0 [MC — widely listed as Apache-2.0; re-verify]. **Verdict: HIGH steal value for concepts.** For JARVIS v2: copy (1) planner-every-N-steps cadence, (2) indexed-DOM observation before vision, (3) per-role model routing, (4) `maxSteps/maxFailures` circuit breakers, (5) URL firewall. The TypeScript itself doesn't port to a Python-stdlib core, but every mechanism does.

---

## A3. Royal-lobster/Syncia — ★98 [VC] · sidebar ChatGPT on any site

### Architecture as evidenced
MV3 extension (TypeScript/React). Two surfaces: (1) **side-panel chat** opened with `Ctrl+Shift+X` on any website; (2) **floating quick menu injected under any text selection** (summarise, simplify, translate, grammar, custom length). User supplies their **own OpenAI API key**; custom prompts are stored and reusable from the quick menu; a full settings page. Chrome Web Store disclosure: developer states it **will not collect or use your data** [HC].

### Clever mechanism
The selection menu is the product: zero-friction, the AI action appears *at the selection coordinates* before the user has decided to "open the AI". No page-context chat by default — the user's selection *is* the context window, which is both a privacy and a token-cost win.

### Privacy / safety
BYO-key, no backend, no collection claim. Page text only leaves when the user selects/invokes.

### Licence / stealability
MIT [MC]. **Verdict: steal the UX pattern** — for JARVIS's future browser surface: selection-anchored action menu > sidebar-first design. Trivially small codebase; read it as the reference MV3 skeleton.

---

## A4. hasan-py/Ai-Assistant-Chrome-Extension — ★61 [VC]

### Architecture as evidenced
Vanilla-JS MV3 three-part structure, documented by the author (dev.to walkthrough): **popup** (provider/action picker), **background script** (API dispatch), **content script** (captures `window.getSelection()` on any page). One selection can be routed to **GPT, Gemini, Grok, or a local Ollama** model for summarise / code-review / generate actions "with just a few clicks".

### Clever mechanism
**Provider as a per-action choice at the selection point**, including localhost Ollama — the same gesture can be free/private (local) or smart/cloud, decided per use. This is the multi-provider key-rotation idea JARVIS already implements in its brain, surfaced in one click.

### Privacy / safety
Selection-only exfiltration; Ollama path is fully local. Keys in extension storage (plaintext local storage is the norm in this class — a weakness JARVIS's OS-keyring approach already beats).

### Licence / stealability
Licence [UK]. **Verdict: pattern-only steal** (selection→provider router). Codebase is tutorial-grade; do not copy code.

---

## A5. vincentwun/A-Eye-Web-Chat-Assistant — ★15 [VC] · accessibility + voice

### Architecture as evidenced
Chrome extension (v2.0.20, 9.33 MiB, Web Store) for accessible browsing: **screenshot/screen analysis + full voice control of the page**. Brain is user-selectable across a local/cloud ladder: **Gemini Nano (on-device, via Chrome built-in AI) / Ollama / LM Studio / vLLM** locally, **Gemini 2.5 / Mistral** in cloud. Developer declares no data collection/sale [HC, store listing].

### Clever mechanism
**Screenshot-as-accessibility-tree substitute**: where Syncia/Nanobrowser read DOM/selection, A-Eye captures the *rendered screen* and asks a vision model what is there, then drives the page by voice — the only design in this slice that works on canvas-heavy, screen-reader-hostile pages. The local-first ladder (Nano → Ollama → cloud) is a graceful degradation chain: privacy and capability traded explicitly per user setting.

### Privacy / safety
Local backends keep screenshots on-device; cloud backends send screenshots — the most sensitive payload class in this whole slice (full screen, incl. other content) — so backend choice *is* the privacy policy.

### Licence / stealability
Licence [UK]. **Verdict: steal the ladder + the lesson.** JARVIS's screen-watcher already follows "UIA tree first, vision only when needed"; A-Eye validates the inverse fallback — when the tree is empty, screenshot+vision+voice is a complete interaction loop, not a dead end.

---

## A6. firebotQL/CompAInion — ★6 [VC] · text-selection injection

Small TypeScript extension (Next.js/Vercel AI SDK, shadcn sidebar) integrating ChatGPT with a **"unique text-selection injection feature"**: selected page text is injected into the sidebar conversation as context (per repo description). Architecturally Syncia-class (BYO model, sidebar), distinguished only by making selection-injection automatic into an ongoing conversation rather than one-shot actions. **Licence [UK]. Verdict: no separate steal** — confirms selection-injection is the convergent primitive of this whole category.

## A7. pixelpump/Ai-Interview-Assistant-Chrome-Extension — ★48 [VC] · tab-audio STT

### Architecture as evidenced
Extension listens to **current-tab audio** (`chrome.tabCapture`), transcribes speech in near-real time, **detects questions** in the transcript, and generates concise answers with GPT, displayed as an overlay. Brain runs cloud-side (OpenAI); the extension's job is capture + question segmentation.

### Clever mechanism
**Tab audio as an input channel**: no microphone permission drama, no meeting-bot joining the call — the browser tab itself is the microphone. Question-detection gating means the LLM is only invoked on interrogative utterances, not the whole transcript.

### Privacy / safety
Weakest posture in Part A by design: continuous tab audio → cloud transcription. Included because the *mechanism* matters: JARVIS's voice loop could treat "what the PC is playing / what a call participant asked" as a caption stream (ASR = captions, never commands — matching v2's existing safety invariant).

### Licence / stealability
Licence [UK]. **Verdict: steal tab/system-audio capture + question-gating; reject the always-streaming privacy posture.**

**Bonus (not counted): steipete/summarize** — CLI + Chrome extension summarising pages/YouTube/podcasts/files; evidence that the winning extension feature is often just *one* extraction (page→clean text) done extremely well.

---

# PART B — WHATSAPP / TELEGRAM / DISCORD AI BOTS (7)

## B1. askrella/whatsapp-chatgpt — ★3,794 [VC] · the unofficial-WhatsApp archetype

*TypeScript · ChatGPT + DALL-E + WhatsApp.*

### HOW IT ACTUALLY WORKS (inside)
- Transport is **`whatsapp-web.js`**: a real WhatsApp Web instance driven by Puppeteer, authenticated by QR code (`src/index.ts:23-35` client init). This inherits the *user's own number and chats* — no Business API, no Meta app review.
- Single entry `handleIncomingMessage` (`src/index.ts:84-107`): (1) validations — group-message filtering, **whitelist check**; (2) if voice message → download + transcribe; (3) route by **command prefix**; (4) reply.
- Prefix router: `!gpt` text, `!dalle` image, `!sd` Stable Diffusion (HF), `!config` **runtime reconfiguration of the AI**, `!reset` conversation context reset, `!lang` LangChain (web-browsing) mode.
- Voice loop is symmetric: voice-in → Whisper transcription; voice-out (when `TTS_ENABLED`) in `src/handlers/gpt.ts`: GPT text → TTS provider (`speech-api` self-hostable, or AWS Polly) → buffer saved to a **temp file with random UUID** → wrapped as `MessageMedia` with MIME **`audio/ogg; codecs=opus`** (the only format WhatsApp renders as a voice note) → sent → **temp file deleted** (`gpt.ts:95-149`).

### Clever mechanism
Prefix-as-capability-router + `!reset`/`!config` as in-chat admin surface: no dashboard needed because the chat *is* the control plane. The opus-temp-file dance is the canonical voice-note recipe every WhatsApp bot since has copied.

### Privacy / safety
Whitelist is the only access control; group support is opt-in. Authors are explicit: unofficial client, **WhatsApp may ban the number** — the honesty is part of the design doc.

### Licence / stealability
MIT [MC]. **Verdict: steal `!reset`/`!config` in-chat admin + the opus voice-note recipe + whitelist-first gating.** Do NOT steal the transport for JARVIS (ban risk on the owner's number; v2 correctly uses Telegram's official Bot API).

---

## B2. daveebbelaar/python-whatsapp-bot — ★1,540 [VC] · the official-API Python archetype

*Python/Flask · Meta Cloud API.*

### HOW IT ACTUALLY WORKS (inside)
- Flask **factory pattern**: `run.py` → `app/__init__.py:create_app()`; webhook is a blueprint in `app/views.py` with `GET /webhook` (Meta verification handshake) and `POST /webhook` (events).
- **Signature verification as a decorator**: `app/decorators/security.py` validates the `X-Hub-Signature-256` HMAC against `APP_SECRET` before any payload is trusted — security is a wrapper, not inline code, so no route can forget it.
- `app/utils/whatsapp_utils.py`: `get_text_message_input()` (:16-25) builds the Graph API payload; `send_message()` (:33-57) POSTs with timeout/error handling; `process_whatsapp_message()` (:78-94) is the central coordinator (extract → generate → reply); `is_valid_whatsapp_message()` (:96-107) shape-validates the payload before processing.
- **Session = OpenAI Assistants thread per WhatsApp ID**: a "Threads Database" maps `wa_id → thread_id`, so conversation memory is delegated to OpenAI's thread store rather than a local history table.

### Clever mechanism
Two: (1) decorator-enforced HMAC — the secure path is the only path; (2) thread-per-phone-number identity: the phone number *is* the user ID, session lookup is one dict/DB hit, and memory survives restarts without the bot storing transcripts itself.

### Privacy / safety
Official API only (no ban risk), signature-verified ingress. Cost of the design: all conversation content lives at OpenAI (thread store) and Meta — nothing is local.

### Licence / stealability
MIT [MC]. **Verdict: DIRECTLY stealable into JARVIS v2's Telegram module's design language** — replace HMAC decorator with Telegram's `secret_token` header check + owner-ID gate (v2 has the PIN; this adds the transport-auth layer), and copy the `is_valid_*` shape-gate before any handler runs. Python + Flask structure maps 1:1 onto a stdlib `http.server` equivalent if Flask is to be avoided.

---

## B3. wassengerhq/whatsapp-chatgpt-bot-python (+ JS sibling) — the production-quota archetype

*Python/FastAPI · Wassenger (WhatsApp API reseller) · the most complete anti-abuse implementation in this slice.*

### HOW IT ACTUALLY WORKS (inside)
- **Ack-first webhook**: `src/http/router.py` validates `event == "message:in:new"`, returns **200 OK immediately**, and processes via FastAPI `BackgroundTasks` — the provider never times out and never retries-duplicates while the LLM is thinking. Dev mode auto-creates an ngrok tunnel and registers the webhook (`src/main.py:84-112`); prod uses `WEBHOOK_URL`.
- **Eligibility gauntlet, cheapest-first**: `ChatBot.can_reply` (`src/bot/chatbot.py:23-57`) — skip if chat assigned to a human agent → skip own number → individual chats only → label blacklist → number whitelist/blacklist → banned/blocked → archived. Each check is O(1) and ordered so LLM cost is spent only on messages that survive all of them.
- **Two-phase quota** (`chatbot.py:59-80`): fast in-memory counter in `MemoryStore` (`src/storage/memory_store.py`, thread-safe, TTL-cached) — default **500 msgs / 24 h / chat** — plus a **persistent metadata flag** on the chat (`bot:chatgpt:status = too_many_messages`) that survives restarts; on quota breach the chat is **auto-assigned to a human agent** instead of just going silent.
- **Bounded memory**: per-chat history capped (default **20 messages**) in `MemoryStore`; `extract_message_body()` (`chatbot.py:152-166`) normalises modalities — audio → Whisper transcript; image/video/document/location → a literal placeholder string ("User sent an image") so non-text events still enter context coherently. `process_message` pipeline (:127-149): eligibility → quota → typing indicator → transcribe → build context → OpenAI (with function calling) → send text *or* TTS audio → update metadata/labels.

### Clever mechanism
Quota-exceeded → **human handoff as a state transition**, not an error message; and the persistent-flag + in-memory-counter pairing (fast path for speed, durable path for correctness across restarts).

### Privacy / safety
Best-in-slice: whitelist/blacklist/labels, per-chat quotas, history caps, human takeover. In-memory state is the weakness — restart loses counters (hence the persistent flag pattern).

### Licence / stealability
Licence [UK]. **Verdict: the single best steal source for JARVIS v2's Telegram module hardening** (see Top Steals): ack-first + background processing, cheapest-first eligibility, two-phase quota with durable flag.

---

## B4. RockChinQ/LangBot (langbot-app/LangBot) — production multi-platform bot platform [HC]

*Python · Discord / Telegram / Slack / LINE / QQ / WeChat / WeCom / Lark / DingTalk / KOOK from one codebase; runners = local agent, Dify, n8n, Langflow, Coze.*

### HOW IT ACTUALLY WORKS (inside)
- **Pipeline architecture**: platform adapter normalises any IM event → a *pipeline* (triggers, safety controls, AI logic, output formatting) → a *runner* (the brain backend). Different bots bind different pipelines/backends.
- **Event bindings replace bot→one-pipeline (v4.11)**: bindings stored as JSON on the `bots` table (`src/langbot/pkg/entity/persistence/bot.py:55-56`); each binding = `event_pattern` (exact / `namespace.*` / `*`, matched in `src/langbot/pkg/platform/botmgr.py:152-159`) + `filters` (`chat_type`, `chat_id`, `message_text`, element types; ops `eq/neq/contains/regex`, all must hold) + target (`pipeline` | `agent` | **`discard`**) + priority. Non-message events (member joins, friend requests) become routable for the first time.
- **Runners became plugins (v4.11)**: runtime discovers plugin runners via `LIST_RUNNERS`, cached in `RunnerRegistry` (`src/langbot/pkg/agent/runner/registry.py:20,24,152`); runner IDs are namespaced `plugin:author/plugin/runner` (`runner/id.py:24-27`) and rejected without the prefix. A runner manifest declares `capabilities` (typed booleans, for UI) **separately from `permissions` (the access ceiling)** — and the effective permission is the *intersection* of manifest ceiling and binding policy.
- **Plugin process isolation**: three process layers (main → Plugin Runtime → per-plugin subprocesses) over JSON-RPC-style stdio; in Docker the Runtime is a separate container over WebSocket — and **on Windows, where asyncio stdio subprocess support is incomplete, it auto-falls-back to WebSocket**. A crashing plugin cannot crash the bot.
- Production controls named in the platform: access control, **rate limiting, sensitive-word filtering**, monitoring, WebUI management, SQLite→PostgreSQL, vector DB options (Chroma/Qdrant/Milvus/pgvector).

### Clever mechanism
Capabilities ≠ permissions, intersected at bind time; and event-pattern routing with a first-class `discard` target — silence is a routing decision, not a missing feature. The Windows WebSocket fallback is a hard-won platform lesson JARVIS (Windows-first) should note verbatim.

### Privacy / safety
Strongest governance model in the slice (access control + rate limits + content filtering + permission ceilings per runner).

### Licence / stealability
AGPL-3.0 [MC — **ideas only, never code**, per standing licence posture]. **Verdict: steal the architecture on paper**: adapter/pipeline/runner separation, event bindings, capability∩permission intersection. Zero code reuse.

---

## B5. Soulter/AstrBot — ★~18-41k (sources conflict) · community multi-platform framework

*Python · QQ / Telegram / Discord / Lark / WeChat + 20+ platforms via adapters; `uv tool install astrbot`, WebUI, plugin marketplace.*

### Architecture as evidenced
Adapter-per-platform feeding a unified event model; plugins declare handlers with decorators — e.g. `@filter.platform_adapter_type(PlatformAdapterType.AIOCQHTTP)` scopes a plugin to one platform's events so a plugin **cannot accidentally process its own cross-platform output** (loop prevention by type system). Chats are addressed by a **`unified_msg_origin`** string (`platform:type:chat_id`, e.g. `telegram:group_message:<id>`) — one identity scheme across all platforms. Documented plugin patterns include: transient `LocalCache` queues with waiting-time/cooldown enforcement in front of async processors (debounce/batching of bursty group messages before acting), and memory plugins providing **venue-scoped isolation** — `global` scope = one shared bot identity; `venue` scope = a separate memory-user per group/DM — with auto-capture of conversations, semantic recall injected before each LLM call, and auto-commit of memory on message-count / token-threshold / idle-timeout triggers.

### Clever mechanism
**Venue isolation as the group-chat answer**: the bot doesn't have one memory that groups pollute; each group/DM is its own memory principal, while `global` remains available for the owner. Plus platform-type filtering as an infinite-loop guard (a bot that forwards/reacts across platforms must never hear itself).

### Privacy / safety
Per-venue isolation is itself a privacy control (one group's content never recalls into another). Plugin ecosystem is community-grade — review before install.

### Licence / stealability
MIT per framework comparison [MC; another listing conflicts — re-verify]. **Verdict: steal `unified_msg_origin` addressing + venue-scoped memory + platform-type self-hearing guard** — all three map directly onto JARVIS v2 (desktop session vs Telegram session vs future WhatsApp = venues; JARVIS must never treat its own Telegram output as a new command).

---

## B6. ebibibi/claude-code-discord-bridge (CCDB) — Discord-specific agent bridge [HC]

*Discord threads ⇄ coding-agent sessions (Claude Code / Codex).*

### Architecture as evidenced (author's production log)
- **Thread = session**: a Discord thread maps 1:1 to a persistent agent session; `/effort` switches reasoning strength per backend; model follows the CLI's own default instead of a hardcoded pin (anti-staleness).
- **Mention-only arbitration with a real security bug found & fixed**: channels configured "respond only when @mentioned" had a hole — a *human-created thread* inside such a channel could spawn a session uninvited. Fixed by treating thread-creation origin as part of the trigger check.
- **Multi-agent "break room"**: multiple agent sessions share a coordination channel where they **notice each other and yield** ("I'm working on that, hold on") to avoid colliding edits — group-chat arbitration between bots, not just humans.
- **Context economics**: long sessions continue via **diff + server-side memory** instead of resending full history each turn.

### Clever mechanism
Yield-to-each-other protocol + diff-based continuation. And the lesson that **the trigger surface is larger than messages**: threads, joins and reactions are all session-spawning events and each needs the mention/permission gate (exactly LangBot's event-binding insight, learned the hard way).

### Licence / stealability
Licence [UK]. **Verdict: steal the arbitration rules for any future JARVIS group presence**: respond only when addressed, thread-scoped sessions, explicit yield when another agent/human is already handling, never spawn work from ambient group events.

---

## B7. NousResearch/hermes-agent (Hermes Agent) — notable product/framework [HC]

*MIT [HC, multiple listings] · Self-improving agent reachable from Telegram, Discord, Slack, WhatsApp, Signal + terminal.*

### Architecture as evidenced
Always-on server process (VPS or serverless backends — Modal/Daytona); messaging platforms are *front doors* to one long-lived agent with persistent memory and a cron scheduler; web dashboard shows every session/model/skill/MCP server. Defining mechanism: **post-task skill crystallisation** — when a task completes, the agent saves the successful procedure as a reusable skill and refines it on later runs, so competence compounds per-user. Any model provider incl. self-hosted OpenAI-compatible endpoints; optional vendor portal bundles models/search under one key.

### Clever mechanism
Skill crystallisation + one agent, many chat front-doors, with the *server* (not the chat app) as the session's home — the chat is replaceable, the agent's memory/skills are not.

### Privacy / safety
Self-hostable and provider-agnostic; reviewers' consistent warning (and the steal-guard): self-written skills need human review and scoped credentials, because an agent that edits its own procedures is harder to predict.

### Licence / stealability
MIT [HC]. **Verdict: steal skill-crystallisation as a *reviewed* pipeline for JARVIS** (propose skill → owner approves → store), and the front-door/server split — v2's Telegram module is already the front door; Hermes is the proof the pattern scales to five platforms without five bots. (OpenClaw, the category's star leader — "your own AI assistant that runs on your machine and answers you in WhatsApp, Slack or Telegram" [HC] — validates the same local-machine + chat-front-door shape JARVIS v2 already chose.)

---

# CROSS-CUTTING FINDINGS

## Voice notes — the universal pipeline (all bot targets agree)
1. Download media → **Whisper-class STT** (cloud Whisper in askrella/wassenger; local options in extensions) → transcript enters the *same* text pipeline (no separate voice brain).
2. Voice-out is opt-in and format-locked: TTS → **OGG/Opus** temp file (UUID name) → send as voice note → delete temp file (askrella `gpt.ts:95-149`).
3. Modality normalisation: non-voice media becomes a placeholder sentence in context rather than being dropped (wassenger `extract_message_body`).
4. Extensions mirror this: Nanobrowser has an STT *agent role* with its own model assignment (`speechToText.ts`); A-Eye treats voice as a full control channel, not just dictation.

## Session / identity — four models observed
| Model | Used by | Key property |
|---|---|---|
| Thread-per-phone-number (delegated store) | daveebbelaar | Number = user; memory outsourced to provider |
| In-memory per-chat dict + TTL + caps | wassenger | Fast, bounded (20 msgs), lost on restart → durable flag compensates |
| Unified origin string (`platform:type:chat_id`) | AstrBot | One addressing scheme for every platform + venue |
| Thread-per-Discord-thread + server memory | CCDB, Hermes | Chat object = session; server owns the durable state |

## Anti-abuse — the convergent stack
Whitelist-first (askrella, wassenger) → cheapest-first eligibility gauntlet (wassenger) → per-chat quota with human handoff (wassenger) → rate limiting + sensitive-word filter (LangBot) → capability∩permission intersection for tools (LangBot) → mention-gating + trigger-surface audit (CCDB). **No target in this slice gives a chat bot un gated tool execution** — every production system gates identity before intelligence.

## Extension context extraction — ranked by fidelity/cost
Selection (Syncia/hasan-py/CompAInion — cheapest, user-curated) → indexed DOM tree (Nanobrowser — structured, cheap, default) → full page text → screenshot+vision (A-Eye — most general, most expensive, most privacy-sensitive) → live session/tool surface (mcp-chrome — the page is not context, it's an *actuator*).

---

# TOP STEALS FOR JARVIS v2 (concrete)

See report-back summary; in full in §"Top 3 steals" of the parent report. In-file shortlist:
1. **Wassenger pipeline for the Telegram module** (ack-first, eligibility gauntlet, two-phase quota + durable flag, 20-msg bounded context, modality placeholders).
2. **LangBot/AstrBot identity & permission algebra** (unified origin addressing, venue-scoped memory, capabilities∩permissions, self-hearing guard) — ideas only from LangBot (AGPL).
3. **mcp-chrome pattern as JARVIS's browser sense**: minimal MV3 extension + Python Native-Messaging host exposing the authenticated browser as tools; Nanobrowser's planner/navigator/validator + indexed-DOM + URL firewall as the control logic on top.

*Evidence note: GitHub MCP returned HTTP 429 after 3 searches; per policy this slice made no further GitHub API calls. Star counts for A1–A5, B1–B2 are from the live searches [VC]; all other figures are [HC]/[MC] from the cited secondary sources and should be re-verified in a later pass, as should every licence marked [MC]/[UK], before any code (vs pattern) reuse.*

---

# PART C — SMART HOME STACKS & FLAGSHIP TEARDOWNS (Slice C, full)

# MEGA-SCAN WAVE 2 — TEAM 10 SLICE C
## Smart-Home Assistant Integrations + Closed-Product Teardowns
### PhD-Level Reverse Engineering — 16 Targets

> Method: Open targets — GitHub search via official MCP (`search_repositories`) + official docs / DeepWiki code-derived docs / project whitepapers. GitHub API rate-limited (HTTP 429) mid-scan after verified hits for rhasspy/rhasspy (2,750★, archived), rhasspy3, dscripka/openWakeWord (2,857★), rhasspy/wyoming-openwakeword, HeyWillow/willow (3,127★, C/ESP-IDF). Closed targets — PUBLIC EVIDENCE ONLY, every claim labelled `[PUBLIC EVIDENCE]` or `[INFERENCE]`. Nothing about closed internals is invented.
> Context for verdicts: JARVIS v2 = stdlib-first Python, Windows desktop, local Ollama + cloud keys, voice loop with known echo/barge-in history, Telegram phone satellite, UIA-first PC control.

---

# PART A — OPEN SMART-HOME VOICE STACKS

## A1. Home Assistant "Assist" Pipeline + Wyoming Protocol — `home-assistant/core`, `rhasspy/wyoming*` family

**Architecture as evidenced**
Pipeline is a *configurable stage graph*, not a monolith. Documented flow (HA Contributor Docs, Assist Pipelines):
```
Device streams audio+metadata → [Wake Word] → [STT] → [Conversation Agent / Intent] → [TTS] → device fetches response-audio URL → plays it
```
Each stage is its own integration/entity type: `assist_pipeline` (runner), `wake_word` entity, `stt` entity, `conversation` entity, `tts` entity. User assembles pipelines in Settings → Voice Assistants, picking language + one provider per stage — e.g. wake=openWakeWord *or* on-device, STT=faster-whisper *or* Speech-to-Phrase *or* cloud, Agent=built-in intent *or* Ollama/OpenAI LLM, TTS=Piper. Multiple named pipelines can coexist (per-language, per-device). A satellite device is an `assist_satellite` entity that *runs a pipeline for you*.

**Wyoming protocol (the clever mechanism #1)**
- Rhasspy author's post-HA protocol replacing MQTT/Hermes: **simple event protocol over TCP: one JSON header line per event, followed by optional binary payload** (audio chunks). Events are typed strings: `describe/info`, `audio-start / audio-chunk / audio-stop`, `detect / detection`, `voice-started / voice-stopped` (VAD), `transcribe / transcript`, `recognize / intent / not-recognized`, `synthesize / synthesized`, `run-pipeline` (with `start_stage`/`end_stage` so a satellite can start at STT and end at TTS), `run-satellite`, `streaming-start/stop`, `timer-*`, `error`.
- Convention ports: Piper TTS `10200`, faster-whisper STT `10300`, openWakeWord `10400`. Discovery via Zeroconf `_wyoming._tcp.local.`
- Because every stage speaks the same 20-odd events, *any* stage can be swapped, run on another machine, or written in a weekend. The wyoming-satellite program has three modes: (1) **stream-everything** (server does wake), (2) **wake-streaming** (local wake service gates streaming), (3) **VAD-gated** (local Silero VAD gates streaming, server does wake). Optional WebRTC noise-suppression / AGC preprocessing services sit in front of the mic as separate Wyoming services.
- **Assist Pipeline Debugger:** every pipeline run is recorded as a trace — stage-by-stage: raw audio metadata, STT transcript, intent/agent input+output, TTS text — replayable in UI, plus a *text-only* "Run text pipeline" / sentence-parser tool that dry-runs a sentence showing intent triggered, entities targeted, which matched/missed, *without executing*. Errors are typed: `no_intent_match`, `no_valid_targets`, `failed_to_handle`.
- **Built-in agent is deterministic:** sentences come from `home-assistant/intents` YAML per language, parsed by **Hassil** (grammar matcher) into intent+slots; entities must be *explicitly exposed* to Assist; satellite's **area** resolves ambiguity ("turn on the lights" = lights in satellite's room). LLM agents are just another `conversation` entity — deterministic agent stays the fast path, LLM is opt-in per pipeline. Newer local STT **Speech-to-Phrase** exploits this: vocabulary constrained to exposed entity names + sentence grammar → tiny, fast, near-perfect for commands.

**Privacy/safety:** fully local pipeline possible (Whisper+Piper+built-in agent, zero cloud); exposure is opt-in per entity (an unexposed device *cannot* be voice-controlled — least-privilege by construction); conversation_id carries multi-turn context explicitly.

**License:** HA Core Apache-2.0; Wyoming Python libs MIT (rhasspy). **Stealability: ★★★★★ — copy the protocol shape and the debugger, not the code volume.** See Steals §1.

---

## A2. Rhasspy (2.5) + Rhasspy 3 — `rhasspy/rhasspy` (2,750★, archived), `rhasspy/rhasspy3` (382★, archived)

**Architecture:** Predecessor architecture that HA/Wyoming grew out of. Profile-driven monolith-or-satellites over **Hermes MQTT topics** (`hermes/hotword/<site>/detected`, `hermes/asr/…`, `hermes/intent/…`, `hermes/tts/…`) + HTTP/WebSocket API (`/api/text-to-intent`, `/api/events/intent|wake|text`). Every home node has a `siteId`; satellites forward mic audio to a base; base runs STT/intent/TTS. Pluggable per stage: wake (Porcupine/Pocketsphinx/Snowboy/Raven), STT (Pocketsphinx/Kaldi/DeepSpeech), intent (fsticuffs/Fuzzywuzzy/Rasa/Adapt/remote), TTS (many).

**The clever mechanism — deterministic intent as compiled FST:**
User writes sentences in a compact grammar (ini + JSGF-like syntax):
```
[LightState]
states = (on|off)
turn (<states>){state} [the] light
```
supports `(a|b)` alternatives, `[optional]`, `<rule>` references, `(value){slot}` tagging, `$slot-lists`, `1..100` number ranges, `TEXT!float` converters, `in:out` substitutions. **Training compiles the same grammar twice:** (1) expanded sentences → ARPA language model (opengrm) constraining the STT decoder to *only sentences the assistant can act on*, (2) tagged sentences → OpenFST transducer (**fsticuffs**) mapping text → `{intent, slots}` JSON deterministically, confidence 1.0 or no-match. STT errors collapse because the decoder literally cannot output out-of-grammar words.

**Privacy/safety:** the offline poster-child — 16+ languages, no cloud path exists by default. Cost: retrain on every sentence change; grammar ceiling = no open conversation.

**License:** MIT. **Stealability: ★★★★★ for the idea** (grammar-constrained STT + compiled intent), ★★ for code (archived, superseded by Hassil/Wyoming — copy Hassil's model, cite Rhasspy as origin). JARVIS lesson: a Hinglish grammar file (`turn on/off`, `bhai light band kar`-style variants) compiled to an intent table gives instant, hallucination-proof PC commands *underneath* the LLM.

---

## A3. openWakeWord — `dscripka/openWakeWord` (2,857★)

**Architecture:** Not a full assistant — one stage, done rigorously. Three ONNX models in series, first two **shared and frozen** for every wake phrase:
```
16kHz audio → melspectrogram.onnx (32 mel bands, 25ms win/10ms hop) → embedding_model.onnx
  (Google speech-embedding CNN ~330k params, 76-frame windows, stride 8 → 16×96 embeddings)
  → <phrase>.onnx (tiny per-phrase classifier, ~800KB-1MB) → probability → threshold + refractory/cooldown
```
Pre-trained phrases ship ready (incl. "hey jarvis"). Runs via ONNX Runtime / TFLite; Wyoming server wrapper exists (`rhasspy/wyoming-openwakeword`).

**The clever mechanism — synthetic training:** a new phrase needs no field recordings: generate thousands of positives with TTS (Piper voices), augment (noise, reverb, pitch/speed), mine *confusion-word negatives*, train only the tiny classifier head on the frozen embedding. Also ships **verifier models** (second-stage per-user models trained on a few real samples of *your* voice saying the phrase) to slash false-accepts, and per-model recommended thresholds + false-accept-per-hour benchmarking methodology.

**Privacy/safety:** audio never leaves the always-on stage; only post-detection audio is ever streamed. Failure mode is measurable (FA/hour vs recall curve) — rare honesty in wake-word land.

**License:** Code Apache-2.0; note some pre-trained model weights carry their own terms — check per-model before redistributing. **Stealability: ★★★★★ — JARVIS v2 already targets this; copy the *evaluation harness* (FA/hr on TV-noise corpus) and verifier idea for the custom bare-"Jarvis" model, not just the model.**

---

## A4. Willow — `HeyWillow/willow` (3,127★, C / ESP-IDF + ESP-ADF)

**Architecture:** The cleanest open Echo-clone split:
```
ESP32-S3-BOX (~$50, ~100mW)                Self-hosted server
WakeNet on-device ("Hi ESP"/"Alexa")  →    WAS (Willow Application Server: routing/HA API)
+ ESP-SR: AEC, noise suppression,      →    WIS (Willow Inference Server: Whisper STT)
  AGC, blind source separation             → HA / openHAB / generic REST POST endpoint
+ VAD endpointing, LCD/touch               ← TTS streamed back
```
**The clever mechanism — dual-mode recognition:** (a) **fully on-device command recognition for up to ~400 commands** (Espressif MultiNet speech-command model — no network at all for "turn off the kitchen light"), (b) open-ended speech → WIS Whisper transcription → arbitrary endpoint. Same utterance path, two engines chosen by confidence/mode. Plus engineering pragmatism: optional audio compression for congested 2.4GHz Wi-Fi, far-field tested ~25ft, OTA updates, "any endpoint that can take an HTTP POST" as the integration contract.

**Privacy/safety:** self-hosted WIS means transcription never leaves LAN; on-device mode means *audio* never leaves the room for common commands. No account, no telemetry business model.

**License:** Apache-2.0 (firmware); ESP-SR/WakeNet components under Espressif's own terms. **Stealability: ★★★★ — pattern, not code (C/ESP32 ≠ Windows).** For JARVIS: a ₹/ $50 satellite in another room beats shouting at the PC — Willow proves the satellite can be *dumb + one smart trick* (wake + AEC) and still feel premium. Copy the **400-command on-device fast lane** concept for PC hotkeys later.

---

## A5. OVOS / OpenVoiceOS + mycroft-core (legacy) — `OpenVoiceOS/ovos-core`, `MycroftAI/mycroft-core` (defunct company, 2023)

**Architecture:** Mycroft's surviving fork. Micro-services around a **WebSocket messagebus** (`mycroft.*` messages): `ovos-listener` (wake+STT), `ovos-skills`, `ovos-audio`, `ovos-gui`, **PHAL** (Platform Hardware Abstraction Layer — LEDs, buttons, enclosure as plugins, admin PHAL for privileged), skills as *separate pip-installable packages/processes* communicating only via bus.

**The clever mechanism — confidence-tiered intent pipeline:** `ovos-core` config is an ordered pipeline list, executed in tiers:
```
stop_high → converse → ocp_high (media) → padatious_high → adapt_high → persona_high (LLM)
→ ocp_medium → fallback_high → stop_medium → adapt_medium → padatious_medium → adapt_low
→ common_qa → fallback_medium → persona_low → fallback_low
```
- **Adapt** = deterministic keyword/entity matcher (embedded-grade). **Padatious** = per-intent tiny neural net trained on example sentences, entities extracted — each intent trains *independently* (add a skill without retraining the world; note current OVOS docs themselves warn Padatious memorizes rather than generalizes and steer new work to classifier/fuzzy engines — an honest deprecation worth copying as documentation culture).
- **Persona pipeline** = LLM solver plugins slotted *into* the tier order, high persona only after strong deterministic matchers fail, low persona as near-last resort before fallback. **Converse** lets the last-active skill get first refusal on follow-ups ("and turn it up?").
- Lesson from Mycroft-the-company's death: the *bus + skill isolation* survived the company because skills were packages, not plugins into a monolith.

**Privacy/safety:** local by default, Selene cloud backend optional and removable — Mycroft's original sin was defaulting account pairing to their cloud; OVOS removed the requirement.

**License:** OVOS Apache-2.0; original mycroft-core Apache-2.0. **Stealability: ★★★★ — steal the tier list verbatim as JARVIS's router spec** (exact tool match → fuzzy intent → LLM persona → clarifying fallback), and converse-first-refusal for follow-ups. Bus itself: overkill for single-process v2; an in-process ordered matcher list gets 90%.

---

## A6. ESPHome Voice Assistant + microWakeWord — `esphome/esphome`, `esphome/home-assistant-voice-pe`

**Architecture:** YAML → **C++ code generation** for ESP32. The `voice_assistant` component is an explicit **phase state machine** driven by HA Assist events:
`idle(1) → waiting_for_command(2) → listening(3) → thinking(4) → replying(5)`, plus `not_ready(10)`, `error(11)` — each phase id drives LEDs/sounds/UI in YAML. Full event surface mirrored on device: `RUN_START, WAKE_WORD_END, STT_VAD_START/END, STT_START/END, INTENT_START/PROGRESS/END, TTS_START/END, TTS_STREAM_START/END, ERROR` — note **INTENT_PROGRESS carries streaming TTS sentences while the agent is still thinking** (perceived-latency trick). Audio transport: native ESPHome API or raw UDP. Wake options: **microWakeWord** on-device (TFLite-Micro streaming models, multiple simultaneous wake words + per-model probability cutoff) or streaming to HA. Voice PE hardware adds an **XMOS audio processor**: hardware AEC/NS/IC before the ESP32 ever sees audio — the honest admission that *echo is a hardware/DSP problem first*.

**The clever mechanism:** wake-word *streaming* inference — microWakeWord consumes audio in small chunks continuously with a sliding feature window (no 2-second buffer-then-classify), so detection latency ≈ phrase end + ~100ms, RAM stays tiny. Plus `use_wake_word`, continuous-conversation flag, and announce pre-emption as first-class config.

**Privacy/safety:** same HA posture; hardware mute switch on Voice PE cuts mic power (physical, LED-visible).

**License:** ESPHome MIT (Python/codegen) with GPL-licensed components noted per-component. **Stealability: ★★★★ — steal the phase enum + event names for JARVIS's HUD states** (v2 HUD should render exactly these phases; INTENT_PROGRESS streaming is the fix for "JARVIS feels slow") and the mute-is-hardware principle for the mic indicator: UI must show mic state from the capture layer, not from intent.

---

## A7. Gladys Assistant — `GladysAssistant/Gladys` (Node.js)

**Architecture:** Not voice-first — a privacy-first *home platform* (Node.js + SQLite, Docker, ~200-400MB RAM) with voice/chat as one input. Model deliberately simpler than HA: **Device → Feature** (a light has features, not HA's thing/channel/item or entity/registry stack). **Scenes = visual trigger → condition → action chains**, no code. Integrations curated (~30: Zigbee2MQTT, Matter, MQTT, Sonos, RTSP cameras…).

**The clever mechanism — Gladys Plus E2EE relay (steal-worthy crypto spec, publicly documented):** optional remote access *without opening ports and without trusting the relay*: per-message **AES-GCM 256** key, wrapped with instance's **RSA-OAEP 2048** public key, signed **ECDSA P-256**, message expiry anti-replay, and **manual public-key validation on the local instance** to block MITM key substitution. Relay compromise yields ciphertext + metadata only. Also: instance-down detection (relay notices disconnect > user-set 10min-24h → emails admin, and again on recovery).

**Privacy/safety:** local core fully functional free forever; business model = relay subscription, explicitly "no investors, no ads, no data resale."

**License:** Apache-2.0. **Stealability: ★★★ for platform, ★★★★★ for the relay pattern** — this is the documented blueprint for JARVIS's Telegram/phone remote path evolution: E2EE command channel + dead-man's-switch notification, if/when Telegram's trust model is outgrown. Also steal Device→Feature simplicity for v2's PC-device model (don't build HA's registry).

---

## A8. Kalliope — `kalliope-project/kalliope` (Python, largely dormant)

**Architecture:** Pre-LLM modular assistant, brain as one YAML file:
```yaml
- name: "say-hello-synapse"
  signals: [{order: "say hello"}]
  neurons: [{say: {message: "Hello sir"}}]
```
**Synapse = signals → neurons.** Signals: `order` (spoken/text pattern with `{{variable}}` extraction), `event` (cron-like schedule), GPIO, MQTT. Neurons: pluggable Python modules (say, shell, HA/REST calls, music…) chained in order, output of one feeds the next. STT/TTS/wake (Snowboy) all pluggable providers. REST API mirrors the same synapses.

**The clever mechanism:** *the whole assistant is one declarative, diff-able file* — backup, version-control, and share an entire personality in `brain.yml`. Event signals make proactivity a config line, not a subsystem.

**Why it matters / failure lesson:** YAML sprawl + string-matching orders hit a ceiling fast; no learning, no LLM path, project stalled. It is the fossil record proving deterministic-only assistants die at the long tail of phrasing.

**License:** MIT. **Stealability: ★★★ — steal synapse shape for JARVIS Routines** (trigger → ordered actions in one YAML the user can read), nothing else.

---

## A9. Leon — `leon-ai/leon` (Node.js + Python, MIT)

**Architecture:** Self-hosted personal assistant, server-centric: **Node.js core** (HTTP/WebSocket web app, skill runner) + **Python bridge over a dedicated TCP server** for NLP nodes (spaCy-era NLU) and Python skills + separate **hotword node** process (Snowboy) so the always-listening loop can't block the brain. Skills = packages with a corpus (example utterances) + actions; NLU classifies `domain → action`, extracts entities; ASR/TTS provider-pluggable with **offline options** (e.g. local STT/TTS) vs cloud (Google/AWS/Watson). Text chat works with zero third parties.

**The clever mechanism:** *skill corpus as training data* — a skill ships its own utterances, Leon trains/updates its classifier from all installed skill corpora at startup ("train" step), so installing a skill *is* teaching the assistant its phrases; uninstalling cleanly removes them. Same insight as Padatious/Rhasspy, packaged for a general (non-home) assistant.

**Weakness (documented by its own longevity):** two runtimes + TCP bridge = latency, deployment friction, and a stalled 1.0; NLU classifier saturates like Kalliope's.

**License:** MIT. **Stealability: ★★★ — steal "skill ships its phrases; router retrains from phrase files"** (JARVIS v2 skills should each own a `phrases.txt` feeding the deterministic tier), reject the dual-runtime bridge (v2 is one Python process — correct call).

---

## A10. Stanford Almond / Genie / ThingTalk — `stanford-oval/*` (research, now GenieGPT lineage)

**Architecture:** Assistant as **semantic parser → typed program → local executor**:
```
NL utterance → neural semantic parser → ThingTalk program → Almond runtime executes against Thingpedia APIs
"Get a cat picture and post it on Facebook with caption X"
  => now => @com.thecatapi.get() => @com.facebook.post_picture(picture_url=…, caption="…")
```
**Thingpedia** = crowd-sourced catalog of device/service APIs, each function typed + annotated with example utterances. Execution can be fully local (parser on your server); credentials and data stay with the user — Almond's founding privacy claim vs Alexa Skills (where your utterance *and* data go to the skill vendor's cloud).

**The clever mechanism — Genie synthetic data engine:** hand-annotating compound commands doesn't scale, so developers write **primitive + construct templates**; Genie composes them into an *exponential* synthetic corpus of (utterance, ThingTalk) pairs, augments with crowdsourced paraphrases, and trains the parser — first parser to handle **compound commands with unquoted free-form parameters** (62% accuracy on realistic inputs, PLDI'19 — modest number, honestly reported). ThingTalk was *redesigned for parseability*: the language bends to the parser, not vice-versa.

**Privacy/safety:** access control is *in the language* — a program can only call Thingpedia functions with declared permissions; parser output is inspectable code before execution (show-the-program = auditability).

**License:** Almond/Genie code Apache-2.0 / BSD-family per repo (verify per-repo before copying code; ideas unencumbered). **Stealability: ★★★★ — steal two ideas:** (1) **LLM output should be a typed, inspectable program** (v2 already trends this way with tool calls — render the pending tool-call as readable ThingTalk-like text in approval dialogs: `now => open_app("chrome") => type_text(…)`); (2) **synthetic phrase generation for training/testing the deterministic tier** — generate Hinglish command variants from templates to *test* the router, Genie-style.

---

# PART B — CLOSED FLAGSHIPS (PUBLIC EVIDENCE ONLY)

## B1. Amazon Alexa+ (2025)

- `[PUBLIC EVIDENCE]` Announced 26 Feb 2025 as a "complete re-architecture": built on **Amazon Bedrock**, **model-agnostic routing** across Amazon **Nova** models and Anthropic **Claude**, choosing per-task. $19.99/mo, free for Prime; Echo Show 8/10/15/21 first, plus new app + Alexa.com web surface with cross-device context.
- `[PUBLIC EVIDENCE]` Capability layer = **"experts"**: grouped systems of APIs/capabilities/instructions per domain (smart home incl. Ring/Hue/Roborock, OpenTable, Uber, Ticketmaster, Grubhub, Thumbtack, music/video services) — i.e. curated tool-groups behind the LLM, not one giant prompt.
- `[PUBLIC EVIDENCE]` **Agentic** claims: can navigate websites and complete multi-step tasks autonomously; proactive suggestions (e.g. leave early for traffic); ingests user-uploaded documents/emails/photos into a personal knowledge store it can recall/act on; remembers preferences, purchases, media history.
- `[PUBLIC EVIDENCE]` Independent hands-on (The Verge, via secondary reporting) found Alexa+ (and Gemini for Home) **noticeably slower than the deterministic assistants they replaced — responses often >10s**.
- `[INFERENCE]` Architecture is cloud-total: Echo is wake+audio endpoint, everything else (LLM routing, experts, memory) is Bedrock-side — consistent with all public material; no on-device LLM has ever been claimed by Amazon.
- **Privacy posture `[PUBLIC EVIDENCE]`:** data-hungry by design (personalization *from* Amazon's commerce/media graph), mitigations are settings-level (voice deletion, profiles) rather than architectural.
- **Steal verdict:** steal **"experts" = named tool-groups the router selects as a unit** and the **model-agnostic router** (v2 already does provider chain — name the groups). Do NOT steal cloud-total memory: v2's edge is local memory the user can read/delete.

## B2. Google — Gemini for Home (2025, replacing Google Assistant)

- `[PUBLIC EVIDENCE]` Announced Oct 2025; early access from 28 Oct 2025 (US), replacing Assistant on *every speaker/display/camera/doorbell shipped since 2016* — **one-way migration, no rollback** per Google. Continued Conversation (no repeated wake word), multi-intent in one breath, 10 new voices, **Ask Home** = natural-language command center over devices/automations/camera history in the Home app; natural-language camera search + AI event descriptions ("person detected" → contextual description).
- `[PUBLIC EVIDENCE]` Tiering: core assistant free; **Google Home Premium ($10-20/mo, replaces Nest Aware)** gates Gemini Live, voice-built automations, AI descriptions.
- `[PUBLIC EVIDENCE]` Hands-on/reported failures: Vergecast testing (Aug 2026, secondary) ~50% success on basic TV/media commands, room/device misidentification, legacy Assistant voice occasionally surfacing (hybrid migration seams), >10s latency, and an Aug 2026 server outage rendering devices globally unresponsive — cloud-dependence made visible.
- `[PUBLIC EVIDENCE]` Privacy change: interactions move to **Gemini Apps Activity**, may be **human-reviewed and used to train models** — a materially broader data footprint than legacy Assistant, per Google's own activity disclosures as reported.
- `[INFERENCE]` Gemini is a wrapper/routing layer over the legacy deterministic home graph (device/room model) — the reported "old voice popping back" and room confusion are consistent with an LLM front-end translating to the old execution layer rather than a ground-up replacement.
- **Steal verdict:** steal **Ask Home** (NL query over *your own* device/state history: "was the front door opened while I was out?" → answer from local event log) and natural-language **automation creation** ("make a routine for…"). Reject one-way migration: v2 must keep the deterministic path *permanently*, not as a legacy to be retired — Google's reliability regression is the cautionary tale.

## B3. Apple Siri — Apple Intelligence Era

- `[PUBLIC EVIDENCE]` Two-tier architecture, WWDC24 onward: **~3B-param on-device foundation model** (Neural Engine) for most tasks; heavier requests → **Private Cloud Compute (PCC)**: Apple-silicon servers, request processed, **data never stored, never accessible to Apple**, with the privacy promise made *verifiable* — PCC software images are published for independent security-researcher inspection (cryptographic transparency). Third tier: **ChatGPT hand-off only with explicit per-request permission**.
- `[PUBLIC EVIDENCE]` Personal context is indexed **on-device** (semantic index over messages/mail/photos/calendar); Siri's rebuild (culminating in "Siri AI", announced 2026) adds a **system orchestrator** tapping the on-device **Spotlight index + App Toolbox / App Intents**, screen awareness, and cross-app actions — execution capability grows via *developer-declared App Intents*, not screen scraping.
- `[PUBLIC EVIDENCE]` The LLM-Siri was publicly delayed (previewed Jun 2024; Mar 2025 reporting: pushed to 2026 cycle, leadership change) — even Apple could not ship conversational Siri on schedule; Bloomberg reported evaluation of Anthropic/OpenAI models for PCC, and later Apple/Google collaboration on foundation models `[PUBLIC EVIDENCE as reported by Bloomberg/MacRumors/BusinessWire summaries]`.
- `[INFERENCE]` The delay's root cause is architectural, not model quality: bolting an LLM onto a decade of deterministic Siri intents + privacy constraints (no stored data to learn from) is strictly harder than a greenfield assistant.
- **Privacy posture:** strongest in class *by architecture* (on-device index, PCC non-retention, random identifiers, no ad profile) — and Apple pays for it in slower feature velocity.
- **Steal verdict:** steal **PCC's verifiability pattern at v2 scale**: JARVIS should be able to *show* what leaves the machine per request (a "privacy receipt" log: this turn → provider X, payload = transcript only) — trust through inspectability, Apple's real innovation. Also steal **App Intents > scraping** where possible: prefer an app's API/CLI over UIA when both exist (v2's UIA-first rule gains an exception clause).

## B4. Samsung Bixby (+ Viv lineage, Galaxy AI overlay)

- `[PUBLIC EVIDENCE]` Bixby's differentiator since 2018 (Viv Labs founders, Siri's creators): **Capsules** — third-party domains built in Bixby Developer Studio from **concepts (typed objects) + actions**, with training examples; the platform does **dynamic program generation**: "developers describe the *what*, the AI generates the *how*" — a compositional planner assembles multi-step programs (nested/conditional: "when it rains at my sister's house, turn off the sprinklers") instead of one intent → one action. Capsule execution renders both dialog + GUI views; debugging shows the generated program/trace.
- `[PUBLIC EVIDENCE]` **Bixby Home Platform** layer sits between Bixby Voice (NLU/command) and **SmartThings** (device graph) so one command fans out across devices. On-device wake ("Hi Bixby"); Bixby Vision mixes on-device + cloud recognition.
- `[PUBLIC EVIDENCE]` Market reality: Bixby never escaped Samsung-hardware gravity; Marketplace stayed thin vs Alexa Skills — a platform with a superior planner lost to a platform with superior distribution. 2024-25 Samsung layers Galaxy AI / LLM features (incl. Gemini partnerships on Galaxy devices) over Bixby rather than replacing its device-control core `[PUBLIC EVIDENCE]`.
- `[INFERENCE]` Samsung's quiet endgame — Bixby as deterministic device-control substrate, partner LLM as conversational skin — is the same hybrid Google/Amazon are converging on, arrived at from the opposite direction.
- **Steal verdict:** steal **capsule = typed concepts + actions + examples as one publishable unit** (v2 skill format should declare its *types*, enabling composition: output of skill A feeds skill B without glue code) and dynamic-program *display* (show the composed plan before multi-step execution — pairs with Almond's inspectable program).

## B5. Rabbit R1 — Post-Mortem (the "LAM" that wasn't)

- `[PUBLIC EVIDENCE]` Launched Apr 2024, $199, Teenage Engineering hardware, ~100k units sold on pre-orders; **~5,000 daily active users five months later (~95% abandonment)** per Rabbit's own reported figures in press coverage. Founder admitted it shipped too early.
- `[PUBLIC EVIDENCE]` The headline **"Large Action Model (LAM)"** claim — a model that learns any app's UI — shipped as a **handful of services** (Spotify, Uber, DoorDash, Midjourney…) executed via **cloud-hosted automated sessions**: users logged into services through Rabbit's web portal ("Rabbithole"), and actions ran in Rabbit's cloud browsers/VMs against those stored sessions. Investigative teardowns (Verge, Android Authority, jailbreak community) showed the device itself runs an **Android (AOSP-derived) system where the Rabbit experience is effectively an app**, with **no on-device LAM**; responses routed to cloud LLM APIs (Perplexity for Q&A).
- `[PUBLIC EVIDENCE]` Security post-mortems: researchers disclosed (Jun 2024, "Rabbitude" disclosure) **hardcoded API keys in the codebase** enabling access to third-party service keys and user-response data; Rabbit rotated keys and disputed scope. Separately, the session-credential model meant a Rabbit-cloud compromise = users' Uber/Spotify sessions.
- `[PUBLIC EVIDENCE]` UX failures catalogued across reviews: minutes-long task completion vs seconds on a phone, no calls/texts at launch, tiny scroll-wheel + small screen unfit for reviewing agent actions, always-cloud latency, unsustainable economics (cloud LLM costs, no subscription).
- **Root causes (synthesis):** (1) **Demo-driven development** — CES demos showed capabilities that didn't exist in the shipped build; (2) **renaming scripting "a model"** — brittleness of per-service automation was hidden until users hit the long tail; (3) **credential custody inversion** — holding users' live sessions for other services is maximum liability for minimum gain vs OAuth/on-device tokens; (4) **new form factor + new interaction + new ecosystem simultaneously** — three inventions, none finished.
- **Steal verdict (negative knowledge — the most valuable kind):** v2 rules confirmed — never market a capability before it passes the test suite; call automation *automation* (UIA scripts named honestly); credentials in OS keyring on the user's machine, never in our cloud; JARVIS lives on hardware the user already owns (phone-as-satellite), inventing zero form factors.

## B6. Humane Ai Pin — Post-Mortem (bricked by design)

- `[PUBLIC EVIDENCE]` Launched Apr 2024 at **$699 + $24/mo mandatory subscription**, screenless laser-projection palm UI, own phone number (not the user's), cloud-only intelligence (GPT-4-class models via Humane's CosmOS), Snapdragon wearable running always-hot.
- `[PUBLIC EVIDENCE]` Documented failures: **>10s response latency**, laser unreadable in daylight, **overheating** (device + charging case; Humane told users to stop using the case over fire risk; a battery-related recall followed), ~10,000 units shipped vs 100,000 projected, returns reportedly exceeding sales at points in 2024.
- `[PUBLIC EVIDENCE]` End: **HP acquired Humane's assets/team for $116M (Feb 2025) — less than its ~$230M raised — and Ai Pins were remotely bricked on 28 Feb 2025**: servers off = device dead, including its local functions, with owners offered limited refunds. The Pin is now the canonical case study in **cloud-brick risk**.
- **Root causes (synthesis):** (1) **subtracting the screen subtracted the fastest I/O channel humans have** — voice+gesture for *everything* (reviewing, correcting, scanning) is a category error, the mirror of JARVIS's HUD-first design being right; (2) **physics ignored** — projector + cellular + LLM-round-trips in a pin-sized thermal envelope; (3) **phone-replacement ambition with phone-companion capability**; (4) **no local fallback whatsoever** — when the company died, the product died the same day.
- **Steal verdict (negative):** v2 must pass the **"company dies tomorrow" test**: if every cloud key vanished, local Ollama + deterministic intents + Piper still give Owais a working assistant. And: **never remove a working channel (screen/HUD) to force a novel one (voice)** — add voice *to* the HUD, never instead of it.

---

# SYNTHESIS — CROSS-CUTTING FINDINGS

**1. Everyone converges on the same hybrid.** Deterministic grammar/intents for device control (fast, reliable, auditable) + LLM for conversation/long-tail (slow, creative, fallible). HA keeps Hassil under LLM agents; OVOS tiers persona *below* Adapt; Google/Amazon bolted LLMs *on top of* deterministic cores and shipped latency/reliability regressions; Bixby kept its planner and rented an LLM skin. **The LLM-first, intent-never design has zero surviving exemplars.**

**2. The protocol is the product.** Wyoming's ~20 events outlived Rhasspy's monolith and now connect dozens of independent implementations. Assist's stage-entity model means HA didn't have to build a good TTS — Piper did. JARVIS v2's internal stage events (wake/stt/agent/tts as named, loggable events) matter more than any single model choice.

**3. Echo is solved at the DSP, not the LLM.** Willow (ESP-SR AEC), Voice PE (XMOS), Alexa/Google (proprietary arrays) all cancel echo *before* transcription. Software-only echo guards (v2's known greeting-echo history) are the fallback, never the plan: reference-signal AEC (feed TTS output as cancellation reference) is the minimum viable version on Windows.

**4. Debuggability is a feature users feel.** HA's pipeline trace, Bixby's generated-program view, Almond's inspectable ThingTalk — every serious system can answer "what did you hear / decide / do?" JARVIS needs the same one-click answer.

**5. Failure taxonomy from the dead:** demo-driven shipping (Rabbit), channel subtraction (Humane), cloud-brick (Humane), credential custody (Rabbit), one-way migration (Google), YAML/grammar ceiling (Kalliope/Rhasspy — mitigated by LLM fallback), company-death (Mycroft — mitigated by package-isolated skills).

**Coverage:** 16 targets — A1 HA Assist+Wyoming, A2 Rhasspy, A3 openWakeWord, A4 Willow, A5 OVOS/Mycroft, A6 ESPHome+microWakeWord, A7 Gladys, A8 Kalliope, A9 Leon, A10 Almond/Genie — B1 Alexa+, B2 Gemini for Home, B3 Siri/Apple Intelligence, B4 Bixby, B5 Rabbit R1, B6 Humane Ai Pin.
**Licenses summary:** MIT — Wyoming libs, Rhasspy, Kalliope, Leon, ESPHome(py); Apache-2.0 — HA Core, openWakeWord code, Willow, OVOS, Gladys; Almond/Genie mixed Apache/BSD per-repo. All Part-A *ideas* stealable; code-copy per license above.
