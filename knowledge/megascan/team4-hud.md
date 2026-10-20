# MEGA-SCAN TEAM 4 — HUD/UI & Full-Product JARVIS Repos

**Date:** 2026-10-20 · **Method:** code-level reverse engineering — README + 2–4 core implementation files read per repo (GitHub API first, then `git clone --depth 1` after the API hit HTTP 429). Stars/activity from GitHub search metadata at scan time. License judged from the actual LICENSE file (size/type), not badges.
**Coverage:** 37 repos targeted; **33 read at code level**, 4 at tree/README level only (network failures on clone — marked ⚠ in their entries).

---

## CROSS-CUTTING FINDINGS (the patterns that repeat)

1. **The transport war is settled: WebSocket for voice, SSE for text, polling only as fallback.**
   Voice products (eadmin2, mp-web3, PanPenek, EliseyRotar) all use one full-duplex WebSocket carrying JSON control frames + **binary PCM audio**. Text/agent dashboards (jincocodev, jontsai, MultiX0, Itsme23476) use **Server-Sent Events** — simpler, auto-reconnect, enough for one-way agent→UI streams. Polling survives only in (a) file-based designs (AlexandreSajus: 0.5 s file poll; Prompt-Surfer: version-counter poll) and (b) fallbacks (jontsai: SSE → polling fallback; kian-irani dashboard: 5 s/8 s polls).

2. **"Claude Code is the brain" is now a genre.** Four repos don't implement an agent at all — they wrap Claude Code and build the HUD around it: Itsme23476 (drives the `claude` CLI), ehteshambuildagents (Claude Agent SDK `query()`, auth = your `~/.claude.json`, no API key), artbyjazi (sidecar + CDP browser control), oujnit (doesn't even drive it — just *watches* Claude Code/Codex session logs and visualizes them). The HUD is the product; the brain is rented.

3. **Hermes Agent's Sessions API is the other rented brain** — three independent repos (eadmin2/jarvis_ai, EliseyRotar/jarvis-ai, MultiX0/jarvis) all speak to `POST /api/sessions/{id}/chat/stream` (SSE) for persistent memory + run IDs + approval events. Nobody re-implements session memory when Hermes gives it away.

4. **The orb is audio-reactive or it's fake.** Every HUD that "feels alive" drives its centerpiece from a Web Audio `AnalyserNode` fed by the *actual* TTS/mic stream (jincocodev, eadmin2, ehtesham, Itsme23476). Pure-CSS pulsing orbs (most single-file HTML repos) are decoration — they animate identically whether the agent is working or dead.

5. **State vocabularies converged:** `idle / listening / thinking / acting(tool_use) / speaking` (+ `final/aborted` for runs). jincocodev, artbyjazi, eadmin2 and Itsme23476 all use near-identical state sets, and all map state → animation speed/color/glow. This is the de-facto JARVIS UI state machine.

6. **Fake-vs-real verdict for the slice:** the top-starred "iron man jarvis" repos are mostly *decoration* (PNG rings, CSS glows, hardcoded weather). The real engineering sits in the mid-star wired products: eadmin2 (full voice pipeline), Dix01 (Electron+Python product), LeoSasion (Windows shell replacement), sam3gp8 (Home Assistant integration), jontsai (ops console). Star count anti-correlates with HUD honesty.

7. **Security is bimodal.** Most repos: zero auth, `ws://` on LAN, keys in plaintext config. Two stand out doing it properly: Itsme23476 (per-boot token + Host/Origin checks + size caps + path-traversal guard, all stdlib) and jincocodev's gateway (device keypair, 0600 token store, nonce handshake). sam3gp8 inherits HA's auth. Everyone else is wide open.

---

## TOP MECHANISMS (ranked by steal-value for JARVIS v2)

1. **Speech/render split (artbyjazi)** — the agent's answer is `{speech, render}`: TTS speaks only the clean spoken text; URLs/IDs/code/tables go into a structured `RenderPayload` drawn on screen. Kills the "JARVIS reads a URL aloud" problem by construction.
2. **Typed event stream for a run (Itsme23476)** — one POST returns a stream of typed events `note | delta | focus | graph | complete | error`: narration, reply tokens, and UI side-effects on a single channel. The GUI renders *work in progress*, not just final answers.
3. **File/session-log watching as a data source (oujnit + AlexandreSajus)** — oujnit tails `~/.claude` / `~/.codex` / `~/.zcode` JSONL session files (mtime = agent is working) to build a live "what are my agents doing" console with zero integration into the agents themselves. AlexandreSajus does the same trick at toy scale (`conv.txt`/`status.txt` polled at 2 Hz).
4. **PCM-over-WebSocket voice protocol with approvals (eadmin2)** — documented frame protocol: `start{sample_rate,format}` → binary PCM → `stop`; mid-turn `start` = barge-in; `stop_run` halts the agent; `approval_decision{run_id, approval_id, allow|deny}` lets the *voice client* answer the agent's permission prompts. Server events include `partial_transcript` and `agent_status{thinking|tool_use|speaking}`.
5. **LocalStorage + CustomEvent state bus with versioned, validated payloads (LeoSasion)** — shell modules communicate via versioned JSON envelopes in localStorage + `storage`/CustomEvents, every payload passed through a strict `normalize*()` validator (enums, length caps, control-char stripping). Desktop-OS-grade discipline inside a webview.
6. **Graph-version counter polling (Prompt-Surfer)** — server bumps an integer on every rebuild; clients poll one cheap endpoint and refetch the big payload only when the integer moves. The simplest correct cache-invalidation in the slice.
7. **Browser-feed vision (kshicdi/whisperflow)** — Chrome CDP screenshots at 2 fps streamed over WS into the HUD, so the assistant "sees" your browser tab without any extension.
8. **Audio cross-correlation echo check (mp-web3 reference impl)** — an AudioWorklet `correlatorNode` compares mic input against what's being played to detect the assistant hearing itself. (v2 solves echo differently — novel-word barge-in — but the correlation trick is the other real answer.)

---

## REPO ENTRIES

### 1. AlexandreSajus/JARVIS — 528★ · alive (pushed 2026-10) · GPL-3.0 (LICENSE 35 KB)
- **UI stack:** Taipy (Python→web) chat page + CSS bubbles. Not a HUD — a chat table with a sidebar status line.
- **What the UI does beyond looks:** shows the live conversation + agent status (Idle/working) — real data, but the *entire* data path is two text files.
- **HOW IT ACTUALLY WORKS (inside):** `display.py:client_handler()` runs a thread that sleeps 0.5 s then calls Taipy's `invoke_callback(gui, state_id, update_conv)`. `display.py:update_conv()` re-reads `status.txt` and `conv.txt` from disk, splits conv.txt on newlines into a table, auto-selects the last row. `main.py` (async loop: Deepgram STT → OpenAI → ElevenLabs TTS via pygame) *writes* those files as it works. Bubble styling alternates by row parity (`idx % 2 == 0` = "user") — author detection is literally odd/even lines. `record.py` = PyAudio capture for Deepgram.
- **ONE clever mechanism:** the file-as-message-bus. Brain and UI are fully decoupled processes that never import each other; two append-only text files are the whole IPC. Crude, crash-proof, zero dependencies.
- **Fake vs real:** real (conversation is genuine), just primitive.
- **Stealable for v2?** Partially — v2's GUI already does the cleaner version (thread-safe queue + `after()` drain). The stealable kernel: a tiny on-disk *status file* the brain writes (state, current tool, last error) so any external watcher (phone, second window) can render JARVIS's state without an API.

### 2. jincocodev/openclaw-jarvis-ui — 38★ · alive · license file present (741 B, custom/short)
- **UI stack:** vanilla JS + Three.js-style WebGL orb, Vite build, draggable panels; Node server.
- **What the UI does:** audio-reactive orb + spectrum/waveform visualizers, chat, system monitor, tasks/skills/memory/schedule panels, thought-stream panel, power-save mode, notifications.
- **HOW IT ACTUALLY WORKS (inside):** Three processes: browser ⇄ Node server ⇄ OpenClaw gateway. `server/gateway.js` is a WS *client* to the gateway (`ws://…:8001`) speaking JSON-RPC-ish frames — `{type:'req', id, method:'connect', params}` with a persisted device identity (keypair PEM + token store written `0600`), nonce challenge on connect, `{type:'res', ok, payload.type:'hello-ok'}`, then `{type:'event', event:'chat', payload:{runId, state, message{role, content[], model, provider, usage}}}`. `server/sse.js:broadcastChat()` flattens that into SSE (`data: {runId, state, text, role, done, model, usage}`) for browsers; the same events fan out to voice handlers (TTS speaks the chat stream). Client `src/main.js`: a global `agent-state` CustomEvent (`idle|thinking|responding`) drives orb status text + scanner-line speed (4 s idle / 1.5 s thinking / 2.5 s responding); the orb itself is driven by `core/audio.js` AnalyserNode (`getByteFrequencyData/TimeDomainData`) — camera zoom is bound to audio level (`zoomCameraForAudio`). `/api/status` REST for channel + message counts; system stats polled.
- **ONE clever mechanism:** state → *ambient animation tempo*. The scanline literally speeds up when the agent thinks; you can read agent state from across the room without reading text.
- **Fake vs real:** real wiring throughout (usage tokens and model names come from the gateway stream). The demo music tracks in `index.html` are a side toy.
- **Stealable for v2?** Yes — the *principle*: bind GUI animation tempo/glow to brain state (idle/thinking/tool/speaking). In tkinter terms: one `state → (color, pulse interval)` map applied to the status pill. Cheap, huge perceived-life payoff.

### 3. eadmin2/jarvis_ai — 194★ · alive (pushed on scan day) · MIT
- **UI stack:** one-file HTML HUD (`server/hud/index.html`, 885 lines: canvas arc-reactor + panels) served by a FastAPI server; separate thin Python WS client for the mic/speaker machine; separate STT worker process.
- **What the UI does:** reactor canvas animated from the *real* TTS audio stream, live transcript + partials, agent status, machine stats panel, usage/cost stats, approvals.
- **HOW IT ACTUALLY WORKS (inside):** `server/server.py` (1,241 lines) documents its own protocol in the module docstring. Client→server WS: `{type:"start", sample_rate:16000, format:"pcm_s16le", conversation?}` → raw binary int16 PCM frames → `{type:"stop"}`. A second `start` mid-turn **is** the barge-in. `{type:"stop_run"}` kills the agent run; `{type:"approval_decision", run_id, approval_id, decision}` answers agent permission prompts from the voice client. Server→client: `status, transcript, partial_transcript, agent_status{thinking|tool_use|speaking}, run_started{run_id}, approval_request, error, done{timing}` + binary PCM TTS audio. Brain = **Hermes Agent Sessions API** (`/api/sessions/{id}/chat/stream`, SSE) with persistent memory + stoppable runs; falls back to direct Anthropic ("basic mode") — `server.py:_send_tts_sentence()` streams TTS sentence-by-sentence so speech starts before the reply finishes. STT runs in a separate worker (RealtimeSTT) that the server *polls* for health (`poll_worker()`, offloaded to threads so a dead worker can't hang a request). HUD JS opens `wss://host/ws` with `binaryType="arraybuffer"` and feeds an AudioContext@16 kHz; the reactor's `requestAnimationFrame` loop reads that stream. Server also persists per-day token/char usage stats to JSON.
- **ONE clever mechanism:** approvals over the voice channel — the agent's permission prompt becomes a WS event the *client* can answer, so a voice-only user can approve/deny tool use without touching a screen.
- **Fake vs real:** fully real; latency timings are even logged (`logs/latency.jsonl`).
- **Stealable for v2?** Yes, two things: (1) sentence-streamed TTS (speak sentence 1 while sentence 2 renders) — v2 voice roadmap item; (2) the `done{timing}` event — every turn reports its own latency breakdown, free diagnostics for the GUI's activity feed.

### 4. sam3gp8/jarvis-aio — 29★ · alive, heavily maintained (743 KB changelog) · MIT
- **UI stack:** Home Assistant custom integration; the HUD is a **native HA sidebar panel** — one 640 KB web-component file (`frontend/jarvis-panel.js`) with dashboard + cameras + 3D residence view + settings + logs.
- **What the UI does:** live house state, camera feeds, per-room occupancy glow on a 3D house model, butler suggestions ("suggest, don't act" — autonomy widens only as the user allows).
- **HOW IT ACTUALLY WORKS (inside):** `panel_register.py:async_register_panel()` registers the panel via HA's `panel_custom.async_register_panel` (webcomponent `jarvis-panel`, `/jarvis` path, `embed_iframe=False`), serves the static dir, and **cache-busts with a SHA-1 content hash** of the JS file (`?v=<hash>`) so panel updates actually reach browsers. Live data flows over HA's WebSocket API — the integration's own `websocket.py` is 170 KB of WS command handlers; the brain is split into `cognitive_core.py` (232 KB), `agent.py` (196 KB), `pattern_analyzer.py` (128 KB), `camera.py` (82 KB), `conversation.py` (62 KB). State = HA's entity/event bus; the panel subscribes like any HA frontend.
- **ONE clever mechanism:** don't build a platform — *move into one*. By living inside Home Assistant it inherits auth, device integrations, the entity state machine, mobile apps and the WS transport; all its own code goes into cognition + one panel file.
- **Fake vs real:** real (HA state is ground truth). The 3D residence is a visualization of real occupancy/entity data.
- **Stealable for v2?** Conceptually: the content-hash cache-bust is moot in tkinter, but "suggest, don't act" as an autonomy dial mirrors v2's gate tiers. No code steal (HA-specific, though MIT if ever needed).

### 5. Itsme23476/jarvis-claude-code — 15★ · alive · license not verified from file
- **UI stack:** vanilla JS web HUD (`ui/app.js` 22 KB, `ui/graph.js` 18 KB) served by a **pure-stdlib Python** server (`http.server.ThreadingHTTPServer`) — zero dependencies.
- **What the UI does:** streaming chat with the agent's live narration, an interactive **memory graph** (nodes = your Markdown notes, edges = wiki-links), voice visualizer, status bar (model, permission mode, workdir, note/link counts).
- **HOW IT ACTUALLY WORKS (inside):** brain = the user's own `claude` CLI via `runtime.py` (inherits subscription, tools, MCP servers, CLAUDE.md). `server.py:Handler` routes: `GET /api/status`, `GET /api/graph` (built by `memory.py:build_graph()` from an Obsidian-style vault folder), `POST /api/run` → long-lived chunked response emitting typed JSON events via `emit()`: `{t:"note"}` (agent narration), `{t:"delta"}` (reply tokens), `{t:"focus", id}` (highlight the memory node being used), `{t:"graph"}` (vault changed — refetch), `{t:"complete", ms}`, `{t:"error"}`. Client cancels with an `AbortController`. Voice: `POST /api/speak`, server-side STT (Whisper/Fish); the HUD's voice ring is an AnalyserNode on the mic stream (`ui/app.js` Live object, fftSize 1024). **Security done right:** random per-boot `API_TOKEN` injected into index.html by placeholder replacement (`__JARVIS_TOKEN__`), `Host` + `Origin` allowlist checks, 1 MB JSON / 12 MB audio caps, path-traversal guard on static files, localhost bind only.
- **ONE clever mechanism:** `{t:"focus"}` — when the agent uses a memory note, the graph *lights up that node live*. Provenance you can watch.
- **Fake vs real:** completely real; the graph is your actual notes vault.
- **Stealable for v2?** YES — the strongest stdlib pattern in the slice. (1) The typed event stream maps 1:1 onto v2's brain callbacks (note→activity feed, delta→streaming bubble, complete{ms}→turn timing). (2) Token+Origin+Host checks are the exact recipe if v2 ever serves its GUI over HTTP. (3) Focus-highlight = show *which knowledge note* an answer used — v2's knowledge skill could do this in the sources line.

### 6. artbyjazi/jarvis — 13★ · alive · monorepo (Next.js + Node sidecar + shared types)
- **UI stack:** Next.js HUD (`apps/web`: `components/Orb.tsx`, `lib/hud.tsx`, `lib/voice.tsx`, `components/DebugPanel.tsx`, `components/AnswerSurface.tsx`) + Node **sidecar** process (`apps/sidecar`) that runs the agent loop and drives a real browser via CDP.
- **What the UI does:** five-state orb, live task-step strip (each step: running/done/failed), answer cards, approval prompts, browser-connection status — over a real logged Claude session.
- **HOW IT ACTUALLY WORKS (inside):** the contract lives in `packages/shared/src/index.ts` — a **types-only** file both processes import "so their message shapes can never silently drift apart". Sidecar→UI `ServerEvent` union: `agent.state{state: idle|thinking|acting}`, `task.step{id,label,status}`, `task.aborted{reason}`, `answer{speech, render?}`, `approval.request{id,description}`, `browser.state{connected,url,title}`, `error`, and `hello{browserConnected}` sent on connect so a fresh UI renders current state immediately. UI→sidecar `ClientCommand`: `ask{query}`, `approval.respond{id,approved}`, `abort`. `apps/sidecar/src/ws.ts:attachWebSocket()` mounts a typed WS hub on `/ws`; `agent/loop.ts` runs the agent; `browser/cdp.ts`+`actions.ts` drive Chrome. **The `answer` event is the gem:** `speech` (what TTS says — never contains URLs/IDs, "those are read aloud badly") is split from `render: RenderPayload{title?, markdown?, code?, table?, links?, imageUrl?}` (what the screen shows).
- **ONE clever mechanism:** the speech/render split (above). Voice and screen get different, purpose-shaped content from one agent turn.
- **Fake vs real:** real — it drives an actual browser and a real agent session; the HUD is a thin typed client.
- **Stealable for v2?** YES — top steal of the scan. v2's brain reply should become `{speech, display}` at the source: persona/rules instruct the model to keep spoken text clean and put links/IDs/paths in the display payload; the tkinter GUI renders display, TTS speaks speech. Also stealable: `hello` state-snapshot on connect (v2 GUI already re-derives state; an explicit snapshot event is cleaner).

### 7. LeoSasion/Jarvis3D — 15★ · alive (15★ but very actively engineered) · GPL-family (LICENSE 32 KB)
- **UI stack:** React+Vite frontend hosted in **WebView2 inside a .NET 8 WPF shell** — it is a *Windows shell replacement*: custom taskbar, window switcher, desktop surface.
- **What the UI does:** replaces the Windows taskbar/desktop: real window management (its taskbar buttons drive actual WPF surfaces), Alt+Tab replacement switcher, start menu, quick search, knowledge-graph window, agent panel, system feed.
- **HOW IT ACTUALLY WORKS (inside):** `host/README.md`: the WPF host (`host/Jarvis.Host/MainWindow.xaml.cs` 63 KB, `TaskbarWindow.xaml.cs`, `WindowSwitcherWindow.xaml.cs`) embeds `frontend/dist` in WebView2 and exposes a "small authenticated-by-origin JSON bridge" to Windows services. Default mode is *hybrid* (Explorer keeps the tray; JARVIS overlays the rest of the taskbar); full replacement is opt-in and guarded by an **out-of-process recovery watchdog** — the custom surface reveals only after the watchdog signals ready and confirms `Shell_TrayWnd` hidden; a low-level keyboard-hook thread reroutes physical Alt+Tab. Inside the frontend, modules never call each other directly: `frontend/src/workspace-runtime-channel.js` and `shell-feedback-channel.js` implement a **localStorage + CustomEvent + `storage`-event bus** with versioned envelopes (`jarvis.workspace.runtime.v1`), strict `normalize*()` validators (window-ID allowlists, action enums `toggle|close|minimize|restore`, severity/source enums for feedback, control-char stripping, length caps, nonces). Agent-side models (`agent-session-model.js`, `agent-context-model.js`, `knowledge-graph-model.js`) are local JS; the "agent" is the least-real part (provider model file exists; answers are model-front-end logic).
- **ONE clever mechanism:** the watchdog-gated shell swap — never hide the user's real taskbar until an external process confirms it can bring it back. Failure-mode thinking v2's own autopsy would approve of.
- **Fake vs real:** window management = real (drives your actual desktop); agent intelligence = mostly simulated front-end models. Split verdict.
- **Stealable for v2?** The bus discipline, yes: versioned, validated state envelopes between GUI and brain (v2: a `state.json` schema with a version field + validator) instead of ad-hoc attribute poking. The shell replacement itself: no (out of scope, GPL anyway — ideas only).

### 8. Dix01/JARVIS — 19★ · alive · MIT
- **UI stack:** **Electron** shell (`electron/main.cjs` 16 KB) + React web app (`web/src/App.tsx`) + Python backend package (`jarvis/`).
- **What the UI does:** full local-first assistant console: chat, voice (browser mic), vision (webcam/screen), media generation panel, memory, system tools — a real product surface, not a demo skin.
- **HOW IT ACTUALLY WORKS (inside):** Python core: `jarvis/core/orchestrator.py` (43 KB) routes through `intent_router.py` (24 KB) into `brain.py` and plugins (media_generation 56 KB, web_tools, vision_tools, browser_tools, memory_tools, file/code tools); `jarvis/core/vram_manager.py` juggles local-model VRAM on consumer GPUs. Transport: `jarvis/server/routes.py` (53 KB REST) + `jarvis/server/ws.py` (17 KB WebSocket event channel). Voice enters through the **browser**: `plugins/voice_tools_optional.py` states it outright — "JARVIS uses the BROWSER mic via MediaRecorder + /api/stt" — so STT is a REST upload from the web UI, not a native audio stack. Config is one big `config.yaml` (13 KB).
- **ONE clever mechanism:** the VRAM manager as a first-class core module — local models (Whisper/vision/FLUX/LLM) are loaded/evicted against a VRAM budget instead of each plugin grabbing GPU memory until OOM. (Directly relevant to a 6 GB RTX 2060.)
- **Fake vs real:** real product; optional plugins degrade with honest "not installed" messages.
- **Stealable for v2?** Conceptually: a VRAM/RAM budget object consulted before any local model loads. v2 is cloud-first today, but the moment local Whisper/Ollama run together this becomes the difference between working and crashing. MIT — code borrowable too.

### 9. oujnit/jarvis-sentinel — 1★ · alive · MIT
- **UI stack:** single-file HTML console (`jarvis.html`, 1,261 lines: orbiting-sphere canvas, sparklines, waveform canvas) + stdlib Python server (`sentinel.py`, 585 lines).
- **What the UI does:** a mission-control for *your coding agents* — which of Codex / Claude Code / ZCode are active right now, session activity, token/quota resets, plus host stats (battery, memory, disk, weather).
- **HOW IT ACTUALLY WORKS (inside):** `sentinel.py` defines per-agent watch specs: process-name regexes (e.g. `codex-code-mode-host`, `@anthropic-ai/claude-code`) + session-log globs — `~/.codex/sessions/**/*.jsonl`, `~/.claude/projects/*/*.jsonl`, `~/.claude/history.jsonl`, `~/.zcode/cli/rollout/*.jsonl` — with the telling comment "one JSONL per session; a write means it's working". Fresh mtime on a session file = that agent is alive and mid-turn. It also polls public quota APIs (codex-resets.com), DeepSeek/GLM balance endpoints, and system probes, then pushes everything to the page over **SSE** (`Content-Type: text/event-stream`). No agent cooperation, no APIs, no plugins — pure side-channel observation.
- **ONE clever mechanism:** mtime-as-heartbeat. File writes are the universal agent activity signal; you can monitor *any* CLI agent without its permission or an SDK.
- **Fake vs real:** 100% real data; the holographic sphere is decoration layered on top of real numbers.
- **Stealable for v2?** YES — a "watch my other agents" panel is cheap in v2: glob the same session dirs, mtime-poll in the clock skill's tick, render in the activity feed. Also the general trick — *watch the artifacts a tool leaves behind* — applies to downloads folders, build outputs, etc.

### 10. EliseyRotar/jarvis-ai — 10★ · alive · license not verified from file
- **UI stack:** two UIs in one repo — a vanilla static HUD (`jarvis/static/jarvis.js` + CSS) and a React app (`jarvis/web`: `OrbConsole.tsx` 30 KB, `lib/orbScene.ts` Three.js orb 31 KB, `components/MemoryPanel.tsx`).
- **What the UI does:** orb console with live hardware panel, weather, project context, memory panel, model switcher.
- **HOW IT ACTUALLY WORKS (inside):** brain client is `jarvis/hermes_client.py` (736 lines) — another **Hermes Sessions API** consumer; `jarvis/stream_parser.py` parses the SSE stream; `jarvis/memory_store.py` is the local memory layer. The React console polls REST: `/api/hardware`, `/api/mode`, `/api/project/context?cwd=…` and even external APIs directly from the browser (ipapi.co geolocation → open-meteo weather). The older static UI uses a WebSocket (`static/jarvis.js` §"WebSocket") + `/api/models` REST. The repo also bundles a WhatsApp MCP bridge (Go + Python `whatsapp-mcp-server`) — phone channel via MCP.
- **ONE clever mechanism:** project-context awareness — the HUD asks the server "what project is this cwd?" and re-skins its context panel per project.
- **Fake vs real:** real; weather/hardware are genuine live feeds.
- **Stealable for v2?** Minor: per-working-directory context in the chat header (v2 knows its workspace; surfacing "current project + its notes count" is a small GUI win). Architecture lesson only otherwise.

### 11. ehteshambuildagents/jarvis — 23★ · alive · license not verified from file
- **UI stack:** Vite + React + TS HUD (`src/ui/Hud.tsx`, `Blades.tsx`, `scene/Core.tsx` reactor) + Node **bridge** server (`bridge/server.mjs` 66 KB, `chrome.mjs`, `net.mjs`, `panels.mjs`, `ui.mjs`).
- **What the UI does:** holographic HUD with hand-gesture tracking (`src/lib/hands.ts` 35 KB, camera), voice (`voice.ts`, `tts.ts`), reactor that pulses with your voice, panels fed by the bridge.
- **HOW IT ACTUALLY WORKS (inside):** the bridge authenticates "exactly the way `claude` does" — it reads `~/.claude.json` and calls the **Claude Agent SDK** (`import { query } from '@anthropic-ai/claude-agent-sdk'`, model from `JARVIS_MODEL`, default an Opus-class model) — no API key anywhere. HUD ⇄ bridge over WebSocket (`src/lib/bridge.ts` opens `new WebSocket(BRIDGE_WS_URL)`; state in zustand `src/store.ts`). Voice analysis is deliberately split: the comment in `App.tsx` explains the analyser needs a `getUserMedia` stream while speech recognition "does not, and gets its own" — two mic pipelines, one for looks (analyser → reactor pulse) and one for ears (SR). Boot/ambient/work music tracks ship in `public/audio/`.
- **ONE clever mechanism:** subscription-as-auth — the product has *no key management at all*; if you can run Claude Code, you can run this. (Same trick as #5, via the SDK instead of the CLI.)
- **Fake vs real:** real session, real agent; the sci-fi audio dressing is garnish.
- **Stealable for v2?** The two-pipeline mic split is a real implementation lesson for any future tkinter waveform: the visualizer tap and the STT tap are separate streams with separate failure modes — don't couple them.

### 12. MultiX0/jarvis — 23★ · alive · Dart/Flutter
- **UI stack:** Flutter desktop HUD for Windows (panels: weather/files/tasks/schedule; reactor with distinct visual states) talking to a Hermes backend.
- **What the UI does:** panel-grid HUD with reactor states (idle/working/complete/no-link), typed commands, voice.
- **HOW IT ACTUALLY WORKS (inside):** `lib/data/hermes_client.dart` — third sighting of the **Hermes Sessions API** pattern (requests carry `Accept: text/event-stream`). `lib/main.dart` hosts a telemetry poller + an SSH session to the backend host; comments reveal production scars ("tearing down the websocket and the core's hold on it while a run may be in progress", status-poll caps) — this is a *used* system, not a demo. `lib/core/panel_host.dart` hosts the panel system.
- **ONE clever mechanism:** nothing architecturally new — its value is proof that the Hermes-SSE contract is stable enough for a *third-party client in another language*.
- **Fake vs real:** real.
- **Stealable for v2?** No (Flutter/Hermes-specific). Confirms the pattern though: one SSE contract, many thin clients — v2's brain events could serve GUI + Telegram from one stream definition.

### 13. jontsai/openclaw-command-center — 247★ · alive · JS (Express)
- **UI stack:** server-rendered + vanilla JS ops console (`public/index.html` 207 KB, `lib/server.js` 221 KB monolith server). Panels: dashboard, cron, sessions, memory ("cerebro"), operators, cost, privacy.
- **What the UI does:** this is not a toy HUD — it's the **admin console for an OpenClaw deployment**: live sessions, scheduled jobs, token cost tracking, memory inspection, operator management.
- **HOW IT ACTUALLY WORKS (inside):** server pushes over **SSE** (`GET api/events`, event types `connected|update|heartbeat`); `public/js/app.js` falls back to polling if `EventSource` is missing. The transport gem is `public/js/state-stream.js`: a **SharedWorker** holds the single SSE connection and fans events out to every tab via `MessagePort.postMessage` — five open tabs = one server connection, and the stream survives individual tab closes (`pagehide` → `port.postMessage({type:"close"})`). Server side caches sessions with a TTL refreshed by `setInterval` (`src/index.js`).
- **ONE clever mechanism:** SharedWorker SSE fan-out. Any multi-window JARVIS UI eventually hits "each window opens its own stream"; this is the clean fix.
- **Fake vs real:** entirely real ops data.
- **Stealable for v2?** Not in tkinter (single window), but the pattern matters if v2's GUI ever becomes web-based or multi-surface (GUI + phone web view): one event connection, many renderers.

### 14. Prompt-Surfer/obsidian-jarvis-ui — 65★ · alive · GPL-3.0 (LICENSE 34.5 KB)
- **UI stack:** React + Three.js 3D graph universe for an Obsidian vault (`src/components/Graph3D.tsx` 90 KB) + Node server (`server/index.ts`) + **WASM force simulation** (Rust, `wasm/force-sim/`, run inside a Web Worker `src/workers/force3d.worker.ts`).
- **What the UI does:** renders your notes vault as a navigable 3D galaxy (shapes: milky-way, sun, saturn, black-hole…); search, sidebar, settings.
- **HOW IT ACTUALLY WORKS (inside):** the server builds the graph from the vault; physics (force-directed layout) runs off-main-thread in the worker/WASM so the UI never janks. Sync is the honest hack documented in `server/index.ts:153` — `let graphVersion = 0 // bumped on every completed build — clients poll this to detect vault changes`; clients poll `/api/graph/status` and refetch the full graph only when the version moves. There's even a `STUTTER_INVESTIGATION_COMPLETE.md` — they profiled their own frame drops.
- **ONE clever mechanism:** version-counter invalidation (above) — cheaper than ETags/WS for "big payload, rare changes".
- **Fake vs real:** real vault data; the galaxy shapes are layout presets, not data.
- **Stealable for v2?** The pattern, yes: v2's knowledge index rebuilds could bump a version counter the GUI polls instead of re-querying FTS on every frame. GPL — pattern only, no code.

### 15. kian-irani/Jarvis-android — alive · Kotlin/FastAPI "Agent OS"
- **UI stack:** Android app + a web `dashboard.html` + FastAPI **brain** (`brain/main.py`) that coordinates a mesh of devices ("nodes").
- **What the UI does:** dashboard shows node health and lets you chat / dispatch commands to any connected device.
- **HOW IT ACTUALLY WORKS (inside):** devices connect *up* to the brain via WebSocket (`brain/main.py: @app.websocket("/node/connect")`, sockets kept in `node_sockets: dict[str, WebSocket]`); the dashboard polls `GET /health` (5 s) and `GET /nodes` (8 s), posts chat to `/chat`, and remote-execs via `POST /nodes/{node_id}/exec` which the brain forwards down the node's socket. Topology analysis tooling (`analysis/extract_topology.py`) even maps the mesh.
- **ONE clever mechanism:** reverse-connection node mesh — phones/PCs behind NAT all dial out to one brain, which routes work to whichever node is online. (Exactly why v2's Telegram channel works without port forwarding — same shape, different transport.)
- **Fake vs real:** real routing; the "cognitive framework" PRD docs are aspirational.
- **Stealable for v2?** Architecture validation only — v2 already chose the polling-outward pattern for the phone.

### 16. mp-web3/jarvis-v3 — 35★ · alive · Python (FastAPI)
- **UI stack:** web voice client (`web/index.html`) + FastAPI WS server (`jarvis/web/server.py`); fully local voice (Parakeet STT + Kokoro TTS) fronting **Claude Code**.
- **What the UI does:** push-to-talk-free full-duplex voice in the browser; the browser is the audio device.
- **HOW IT ACTUALLY WORKS (inside):** `jarvis/web/server.py` docstring lays out the loop: browser captures mic with `getUserMedia({echoCancellation:true})` — **hardware/browser AEC is the echo solution** — audio streams up the WebSocket; server runs VAD (`jarvis/vad.py`) → STT (`listener.py`) → `pipeline.py` → Claude Code; replies return via a "voice-output-hook → .tts-queue → TTS → WebSocket → browser" chain, WAV bytes down the same socket. The bundled `reference/offline-voice-ai/` implementation goes further: an AudioWorklet **`correlatorNode`** cross-correlates mic input against playback to detect self-hearing in software.
- **ONE clever mechanism:** delegate echo cancellation to the browser's WebRTC AEC instead of building it — free, battle-tested, and the reason the browser is the mic client at all.
- **Fake vs real:** real voice loop.
- **Stealable for v2?** The lesson, not the code: v2's echo-proofing is construction-based (TTS text never treated as commands + novel-word barge-in); if v2 ever adds a web/phone voice surface, browser AEC is the correct first move.

### 17. PanPenek/JarvisAi — 17★ · alive · Python
- **UI stack:** single-page web UI (`jarvis/static/index.html` 52 KB) + FastAPI-ish Python backend (`jarvis/main.py`, `web.py`).
- **What the UI does:** chat + live provider/model switcher + mute control + voice, over 31 tools (wake word, screen vision, app control).
- **HOW IT ACTUALLY WORKS (inside):** the page opens `new WebSocket('ws://host/ws')` for the conversation stream and uses REST for control plane: `GET/POST /api/mute`, `GET /api/providers`, `POST /api/providers/{name}` (hot-swap the LLM provider from the UI). Backend: `tools/router.py` dispatches to tool modules (desktop, system, app_control, web_search, code_exec, subagent); wake.py/stt.py/tts.py form the voice chain.
- **ONE clever mechanism:** provider hot-swap as a first-class UI control — the model dropdown is wired straight to the live router, no restart. (v2's fallback chain is automatic; an explicit override pin is the stealable bit.)
- **Fake vs real:** real.
- **Stealable for v2?** Small: a provider *pin* in the GUI (auto-chain by default, pin to override) — v2 has the chain; the UI affordance is what's missing.

### 18. thevickypedia/Jarvis — 270★ · alive (pushed day before scan) · MIT
- **UI stack:** essentially **no HUD** — voice-first Python product with a small REST API (`jarvis/api/server.py`, 59 lines), Telegram bot (`jarvis/modules/telegram/bot.py` 26 KB), and Sphinx docs. Included because it's the most-starred *complete product* in the slice.
- **What it does:** mature multi-year assistant: executors, API *triggers* (e.g. `jarvis/api/triggers/stock_monitor.py` — event sources that wake the assistant), offline/online modes, extensive config.
- **HOW IT ACTUALLY WORKS (inside):** `jarvis/main.py` boots an executor architecture; the API server exposes the assistant to external triggers; modules (telegram, email templates, indicators with sound files `indicators/*.mp3`) are peripherals around a voice core.
- **ONE clever mechanism:** triggers as a plugin class — external events (stock moves, schedules) enter through the same door as voice commands.
- **Fake vs real:** real, production-used.
- **Stealable for v2?** The trigger-door idea maps to v2's proactivity engine; v2's design is already ahead (call-ringing budget). No UI steal — there is no UI.

### 19. MAL19INDUSTRIES/JARVIS-OS-V.2 — 113★ · Python
- **UI stack:** **PyQt6** — `ui.py` is a single 370 KB file; `main.py` another 100 KB; actions/ library (browser, email, instagram, files, presentations…) + a real test suite incl. `tests/test_ui_regressions.py` (57 KB).
- **What the UI does:** full desktop control-center window for the assistant: chat, status, action panels.
- **HOW IT ACTUALLY WORKS (inside):** classic Qt signal flow — the monolith UI talks to `agent/executor.py` which runs action modules; nothing streams: request/response calls with the UI updating on completion (Qt timers for clocks/status). The engineering tell is the tests: UI *regression* tests are almost unheard of in this repo class.
- **ONE clever mechanism:** nothing architecturally new — the notable thing is discipline (tests around a hobbyist-scale PyQt monolith).
- **Fake vs real:** real actions (the action modules are tens of KB each of working automation).
- **Stealable for v2?** No. (And a warning in reverse: a 370 KB single-file UI is where v2 must never end up.)

### 20. sebastianrenker/rencora-public — 1★ · Python (codebase sibling of #19)
- **UI stack:** PyQt-style desktop `ui.py` (139 KB) + `main.py` (94 KB) **plus a web dashboard** (`dashboard/server.py` 76 KB) serving `static/rencora3d.html` (Three.js), `globe.html`, `app.html`, `desk.html`.
- **What the UI does:** desktop assistant + a browser "info wall": 3D globe, hand-tracking input, desk panels.
- **HOW IT ACTUALLY WORKS (inside):** same `actions/*` lineage as MAL19 (browser_control, game_updater, file_processor at near-identical sizes — a fork family). The dashboard server serves static pages; the 3D globe is fed by the assistant's data endpoints; hand tracking runs client-side (MediaPipe-style) per the repo description.
- **ONE clever mechanism:** two-surface strategy — native window for control, browser wall for ambience/display. The display surface is deliberately dumb (static files + polling) so it can run on any screen in the house.
- **Fake vs real:** actions real; globe is a visualization skin.
- **Stealable for v2?** The dumb-second-screen idea: a read-only status page (state, last actions, reminders) served on localhost for a phone browser costs ~50 lines once the state file from entry #1 exists.

### 21. Concept-Bytes/JarvisV3 — 45★ · Python (Streamlit)
- **UI stack:** **Streamlit** app (`app.py`) with Chat / Realtime Audio / Settings tabs; PNG ring artwork.
- **What the UI does:** chat + a live speech-to-speech mode.
- **HOW IT ACTUALLY WORKS (inside):** `s2s.py` opens a raw WebSocket to **OpenAI's Realtime API** (`wss://api.openai.com/v1/realtime?model=…`) via `websocket.WebSocketApp`; `app.py:54` starts it from Streamlit session state (`st.session_state.text_client.start_realtime()`). STT, brain and TTS are *all* inside that one realtime session — there is no local pipeline to speak of; `functions.py` holds the tool definitions the realtime model can call.
- **ONE clever mechanism:** none of its own — it demonstrates the "rent the whole voice loop" endpoint: one WS replaces STT+LLM+TTS.
- **Fake vs real:** real, but thin — a wrapper around a hosted realtime model.
- **Stealable for v2?** No (v2's chain is provider-plural by design; a single-vendor realtime socket contradicts it).

### 22. Temavrix/JARVIS — 78★ · Python · GPL-3.0
- **UI stack:** none — console/voice. Single `Jarvis.py` (309 lines) + trained intent model (`datasets/jardata.pth`, `datasets/jarintents.json` 34 KB).
- **What it does:** the classic tutorial architecture preserved in amber: a small neural intent classifier (PyTorch) maps utterances to intent tags → canned skill functions; pyttsx3-style speech out.
- **HOW IT ACTUALLY WORKS (inside):** no LLM at all — bag-of-words → NN → intent → handler. Everything the assistant "knows" is enumerable in jarintents.json.
- **ONE clever mechanism:** nothing new (2020-era pattern).
- **Fake vs real:** real but bounded — it can only ever do its trained intents.
- **Stealable for v2?** No. Historical baseline: this is what JARVIS repos looked like before LLMs; half the "iron man jarvis" search results are still this.

### 23. dmrr35/Open.Jarvis — 30★ · alive · Python
- **UI stack:** **customtkinter** — `open_jarvis/ui/arayuz.py` (22 KB, Turkish for "interface") + `ui_dialogs.py` (21 KB), `ui_rendering.py`, `ui_hud_effects.py`, `ui_pages.py`.
- **What the UI does:** Windows-first local assistant window with pages, dialogs and HUD effects; local/offline routing (Windows-first, privacy posture).
- **HOW IT ACTUALLY WORKS (inside):** `audio/voice_controller.py` + `audio/voice_state.py` — an explicit **voice state machine** module separate from the controller; `memory/memory_store.py`; commands are domain-dispatched (`commands/domains/runtime_actions.py`); root is littered with ~166-byte stub scripts (packaging shims). Unusually test-heavy for its size (action dispatcher, provider system, release eval tests).
- **ONE clever mechanism:** voice *state* as its own module (`voice_state.py`) — state transitions are data, testable without audio hardware. v2's voice loop does the same separation for the same reason.
- **Fake vs real:** real.
- **Stealable for v2?** No new steal; independent confirmation of v2's own choices (explicit voice state, domain command routing).

### 24. ayu-yishu13/Advanced-Jarvis- — 12★ · HTML/Python (Eel)
- **UI stack:** **Eel** (Python ⇄ Chrome app window): `www/index.html` (30 KB, canvas animation + Bootstrap chat offcanvas), `www/main.js`, backend `engine/` + `jarvis.db` (SQLite).
- **What the UI does:** animated face/orb canvas, chat drawer, and a **face-auth gate**: `engine/auth/` ships a Haar cascade + LBPH trainer (`trainer.yml`, face sample photos) — the assistant unlocks only for the owner's face.
- **HOW IT ACTUALLY WORKS (inside):** Eel exposes Python functions to JS; the www layer is decoration (canvas particle face) plus the chat drawer; commands run in the Python engine; auth is classical OpenCV face recognition, not a neural embedder.
- **ONE clever mechanism:** face-unlock as the *only* auth — charming and genuinely how a movie JARVIS behaves; security-wise it's a screen door (Haar+LBPH is spoofable with a photo), but as a *wake gate* it's a legit UX idea.
- **Fake vs real:** the assistant plumbing is real (SQLite memory, command engine); the "AI face" is canvas decoration.
- **Stealable for v2?** No (v2 has a PIN/keyring model; face-gate adds a webcam dependency for negative security).

### 25. kshicdi/whisperflow — 35★ · alive · Python (macOS)
- **UI stack:** giant single-file web HUD (`whisperflow/static/jarvis.html` 175 KB) + Python WS server on `ws://localhost:8767`; state PNGs for the avatar (idle/thinking/speaking/recording).
- **What the UI does:** local voice assistant with a visual feed system: it **watches your browser** and shows what it sees; hand-gesture input (MediaPipe `hand_landmarker.task` ships in-repo); a full *sound design* pack (dozens of UI .wavs: acks, interrupts, camera fail, system online…).
- **HOW IT ACTUALLY WORKS (inside):** `browser_feed.py:BrowserFeed(cdp_port=9222, ws_url="ws://localhost:8767", fps=2)` — connects to Chrome's DevTools Protocol endpoint, takes screenshots at 2 fps and streams them over the same WS the HUD uses ("Chrome CDP screenshot capture and JARVIS WebSocket streaming"). `assistant_session.py` (451 lines) owns the session; `app_launcher.py` launches targets. The avatar is state-image swaps, not animation — the *feed* is the living part.
- **ONE clever mechanism:** the CDP browser feed (above) — screen-awareness of the browser with zero extension installs, at a frame rate chosen for LLM-vision token sanity.
- **Fake vs real:** real; the mockup PNG in-repo shows intended design, but the feed code is functional.
- **Stealable for v2?** The 2 fps CDP trick is a cheaper cousin of v2's screen-vision roadmap item — for browser content specifically it beats full-screen captures (less private surface, less noise). Worth a line in the vision design doc.

### 26. novik133/jarvis — 23★ · C++ · GPL-3.0
- **UI stack:** **KDE Plasma 6 plasmoid** — QML UI (`package/contents/ui/main.qml` 54 KB) + C++ plugin backend; lives *in the Linux desktop shell itself*.
- **What the UI does:** always-present desktop widget assistant: offline voice commands, reminders, connection health.
- **HOW IT ACTUALLY WORKS (inside):** Qt throughout — `src/plugin/jarvisbackend.cpp` runs `QTimer`s for health checks (`checkConnection`) and reminders (`checkReminders`); `audio/jarvisaudio.cpp` processes the wake-word buffer on a timer set to `wakeBufferSeconds` and caps voice commands at `voiceCmdMaxSeconds`. Fully offline pipeline (local STT), settings in C++ (`jarvissettings.cpp` 53 KB).
- **ONE clever mechanism:** nothing new mechanically — but it's the only repo in the slice that is *part of the OS shell* rather than an app on top of it (Plasma plasmoid = the Linux twin of LeoSasion's Windows gambit, at 1% of the complexity).
- **Fake vs real:** real.
- **Stealable for v2?** No (Linux/KDE). GPL ideas-only anyway.

### 27. cesarandreslopez/sidekick-agent-hub — 87★ · TypeScript monorepo
- **UI stack:** three surfaces over shared code — Ink (React-for-terminal) CLI (`sidekick-cli`), a **VS Code webview dashboard** (`sidekick-vscode/src/webview/dashboard/`, incl. a 138 KB `legacy.ts`), and `sidekick-shared` stores.
- **What the UI does:** an agent *hub*: multiple coding-agent accounts/sessions, credential store (`codexCredentialStore.ts`), historical session store (`historicalStore.ts`), dashboards and HTML session reports.
- **HOW IT ACTUALLY WORKS (inside):** shared TS package owns state (browser/session/credential/history stores); CLI and VS Code webview are renderers over it. Not a voice HUD at all — it's fleet management for AI coding agents, the business end of the same trend as oujnit (#9).
- **ONE clever mechanism:** one shared store package, three front-ends (terminal, editor, reports) — no duplicated state logic. 
- **Fake vs real:** real, heavily tested (test files throughout the CLI).
- **Stealable for v2?** No direct steal; corroborates the "agents need ops tooling" direction.

### 28. codeking-ai/cligate — 133★ · JS
- **UI stack:** web admin console (vanilla JS SPA, `public/js/app.js`, `chat-page.js` module) for an **LLM API gateway**.
- **What the UI does:** not a JARVIS assistant — a management dashboard for API accounts/keys, usage & cost charts, request logs, channel health, built-in chat page. Included in the scan because it surfaced under "ai assistant dashboard" and is the slice's most complete *gateway* console.
- **HOW IT ACTUALLY WORKS (inside):** aggressive **polling architecture**: `app.js` runs `setInterval` timers — clock 1 s, health 30 s, several data refreshers; cross-frame comms via `window.postMessage`; a manual/docs sub-app syncs via `storage` events. No websockets anywhere — proof a busy ops dashboard can live on disciplined polling when data changes slowly.
- **ONE clever mechanism:** nothing novel; its discipline (staggered intervals per data volatility) is the takeaway.
- **Fake vs real:** real gateway data.
- **Stealable for v2?** No.

### 29. JashanMaan28/Zorin — 41★ · Python (Eel-style)
- **UI stack:** HTML/CSS/JS frontend (`frontend/index.html`, `main.js` 33 KB, particle.js decor) + Python backend modules.
- **What the UI does:** voice + text chat with feature panels; start-sound, particle background.
- **HOW IT ACTUALLY WORKS (inside):** backend is a clean module-per-capability layout (`backend/ChatBot.py`, `RealtimeSearchEngine.py`, `features.py` 32 KB, `ImageGeneration.py`, `chatlog_manager.py` persisting chat logs, `speechToText.py`/`textToSpeech.py`); `frontend/controller.js` bridges UI events to Python (Eel pattern).
- **ONE clever mechanism:** nothing new — a well-organized instance of the standard tutorial architecture.
- **Fake vs real:** real features; the particles are wallpaper.
- **Stealable for v2?** No.

### 30. satiricalguru/Jarvis — 7★ · Python + React
- **UI stack:** FastAPI backend (`backend/app/main.py`, `brain.py`, `tools.py` 30 KB, `voice_engine.py`) + Vite/React frontend (`frontend/src/App.tsx`) with a Three.js holographic skin; settings modal; terminal panel.
- **What the UI does:** chat + voice with **hold-to-talk (push-to-talk) spacebar** as the default interaction, TTS rate/enable controls, hotkey rebinding — the settings state lives in React `useState`s in App.tsx.
- **HOW IT ACTUALLY WORKS (inside):** browser speech via a `useSpeechToText.ts` hook (Web Speech API) for input; backend `voice_engine.py` for output; REST between frontend and brain; the hologram is presentational.
- **ONE clever mechanism:** push-to-talk as a *configurable hold key* with all voice prefs in one settings surface — mundane but exactly the UX v2's dictation item needs.
- **Fake vs real:** real plumbing, decorative hologram.
- **Stealable for v2?** Only the reminder that PTT hold-key beats wake-word for dictation contexts. v2 already plans PTT.

### 31. Gmasterzhangxinyang/jarvis-amber-protocol-hud — 64★ · HTML (browser-only)
- **UI stack:** single-file HTML HUD (Three.js via CDN, hand-tracking canvas) + a **Dify** workflow export (`jarvis agent/Jarvis.yml` 12 KB DSL).
- **What the UI does:** amber holographic interface: voice in (Web Speech API `SpeechRecognition`), gesture canvas, panels — and it actually *answers*, via Dify.
- **HOW IT ACTUALLY WORKS (inside):** `jarvis-agent.html: fetch(DIFY_CONFIG.endpoint, …)` posts the query to a Dify agent app (the brain is the imported `Jarvis.yml` workflow — prompts/tools live in Dify, not in the repo); responses render into the HUD; `setInterval` loops drive clocks/status decoration. The "starter" variant is the same page minus the wiring.
- **ONE clever mechanism:** the whole brain is a portable Dify DSL file — export/import the assistant like a theme.
- **Fake vs real:** split — visuals largely decorative, but the Q&A path is genuinely wired to a live agent backend.
- **Stealable for v2?** No (Dify is a different universe), but it's the cleanest proof in the slice that a static HTML file + one fetch endpoint can be a "product".

---

## ⚠ PARTIAL COVERAGE (tree/README level only — clone transfers failed repeatedly on a degraded network; NOT counted as code-read)

### 32. AyanBhardwaj1/mossJARVIS — 11★ · TS (Next.js + Tauri)
Root tree (from API): Next.js `app/`+`lib/`, `desktop-shell/`, `src-tauri/` — a text-first, frameless always-on-top assistant that runs in-browser or as a Tauri desktop app (38 KB README). Architecture claim (frameless overlay + web core) is plausible and matches the tree; internals unverified.

### 33. ishaan1013/jarvis — 56★ · TS — ⚠ CODE SAYS: VAPORWARE
Tarball of the default branch contains **seven files**: `backend/app.py` (816 B, a 34-line stub), two camera-calibration result PNGs, `.DS_Store`s and a 1.4 KB README. The "gesture-controlled 3D hologram" exists as screenshots/calibration artifacts, not as shippable code in the repo. Counted as read — the finding *is* that there's nothing inside. Fake vs real: the demo may exist on the author's machine; the repo does not contain it.

### 34. xxjun9527/jarvis-holographic — 44★ · TS
AR/3D holographic interface (per description). Clone hollow; no code read. Not counted.

### 35. titechprabhasolutions/Brahma-AI---Lite — 71★ · Python
"Lite" assistant build; clone hollow; no code read. Not counted.

### 36. atulyaai/Atulya-Tantra — 1★ · Python — much bigger than its star count
- **UI stack:** web app served by a monolith **FastAPI server** (`atulya/server.py` — 121 KB, 2,315 lines) with a particle-hologram WebUI, PWA push, and Hindi/English voice.
- **HOW IT ACTUALLY WORKS (inside):** real product plumbing — `auth.py` (39 KB) + `google_auth.py` (login flow with a *polling* login-request endpoint, `/api/agents/poll`), `secrets_store.py` (dedicated secret storage module), `profiles.py`, `tasks.py`, `history.py`, `mcp_connections.py`, `push.py` with Web Push subscriptions (`POST /api/push/subscribe`), and **SSE streaming** for chat/events (`StreamingResponse(..., media_type="text/event-stream")` at server.py:2067 and :2204). Voice detail worth noting: a spoken-number homophone map (`server.py:331` — "to"→2, "for"→4, "oh"→0) normalizing STT output before parsing.
- **ONE clever mechanism:** nothing architecturally novel; the homophone-normalization table is the kind of unglamorous Hinglish/STT scar tissue that only appears in systems people actually talk to.
- **Fake vs real:** real.
- **Stealable for v2?** The homophone map idea — a tiny STT post-correction table for numbers/commands — is directly applicable to v2's dictation path.

### 37. harkishen/Jarvis-personal-assistant — Go
Linux personal assistant written in Go (rare stack in this space); clone failed; no code read. Not counted.

*Also scanned-and-rejected as off-theme during discovery: phord/Jarvis (standing-desk hardware), vkaracic/Jarvis (NN training UI, dead), wdgdc/Jarvis (WordPress plugin), generic BI dashboards (chartbrew etc.), Termux theme repos.*

---

## VERDICT FOR JARVIS v2

**What the whole slice proves:** nobody in the open-source JARVIS world has v2's safety stack (gate/DCL/verifier) — the best repos here have *either* a great HUD *or* a working brain *or* product discipline, never all three, and approvals-over-voice (eadmin2) is the only real permission UX anyone else built. v2's gap is purely presentational: its GUI doesn't yet *show* the work the way #5/#6 do.

**Top 3 steals (implementable in v2's tkinter/stdlib world):**
1. **Speech/render split** (artbyjazi #6): brain returns `{speech, display}`; GUI shows display, TTS speaks speech. Kills read-aloud URLs/IDs forever.
2. **Typed run-event stream in the GUI** (Itsme23476 #5): `note/delta/focus/complete{ms}/error` events driving the activity feed + streaming bubble + "which note did I use" highlight — v2's brain already produces these signals internally; they just need a rendering contract.
3. **State-tempo status pill** (jincocodev #2): map brain state → pill color + pulse speed (idle slow, thinking fast, tool-use distinct), so JARVIS's state is legible from across the room.

**Runner-up steals:** on-disk status file for external watchers (#1/#9), version-counter cache checks for the knowledge panel (#14), provider pin in the GUI (#17), CDP 2 fps browser feed as a cheap vision source (#25).
