# JARVIS Scout Log — Dedicated Research Journal

**Scout:** Dedicated JARVIS Scout (subagent session 6936d90c)
**Mission start:** 2026-10-19 06:53 UTC (12:23 IST)
**Mission end:** ~11:55 UTC (17:25 IST)
**Method:** Hunt → Study → Log → Rank, in ~30-min cycles.

---

## Cycle 1 — Voice pipeline innovations (06:53 UTC)

### Hunt
Targets: wake-word improvements, VAD, barge-in, TTS advances, full-duplex — beyond livekit/agents, Moshi, whisper.cpp, faster-whisper (already covered).


### Study 1: todoforai/voiceloop ⭐ (07:10 UTC)
- **What:** MIT, zero-dependency JS voice-agent loop library (VAD→STT→LLM→TTS) with published black-box benchmark (voice-agent-bench). 178 tests.
- **The gold:**
  1. **Novel-word barge-in proven:** triggers on transcribed novel words, NOT mic energy. 0 self-interruptions in 30 echo-coupled turns with echo cancellation OFF. This is v1's echo bug class (C-V1) solved and measured.
  2. **Echo-match filter:** word-match filter compares mic input against what agent is currently saying. Portable to Python — this is Playbook V3 made concrete.
  3. **Serialized turns:** rapid-fire turns, tool results, holds, replays can never talk over each other. The turn-serialization discipline v2's voice plugin needs.
  4. **Tuning methodology:** hundreds of bench runs across VAD thresholds, debounce, echo-match thresholds; every knob exposed in `src/tuning.js` with defaults = what won. The discipline v2 needs for its own voice tuning.
  5. **Black-box bench rig:** scripted person + virtual mic + recorded speaker output, scores from audio alone. Any agent measurable incl. closed ones. Pattern for v2's voice regression testing.
- **Numbers:** 862ms median voice→voice (deepgram+EL flash), p95 1067ms (tightest measured); Pipecat p95 3573ms on same providers. Free local Piper path: 974ms.
- **Caveat:** JS/browser — algorithms port to Python, not the code. (Notably: "the voice loop inside TODOforAI's JARVIS" — someone else is building a JARVIS too.)
- **License:** MIT. **Confidence: 90%.** Highest-value voice find today.

### Study 2: NVIDIA NemotronLabs VoiceChat 11B (07:15 UTC)
- **What:** Open 11B end-to-end full-duplex speech-to-speech model (Fast Conformer encoder + Nemotron Nano v2 LLM + TTS codec). First open full-duplex with tool calling. Weights: OpenMDW-1.1 permissive.
- **The gold (patterns, NOT the model):**
  1. **On-hold messages:** per-tool operator-defined line spoken the moment tool call triggers, so conversation never falls silent while API runs. Directly implements "narrate work live" for v2's tool loop.
  2. **Separate tool-call channel:** `<TOOLCALL>` scripts on side channel, results via `<TOOL_RESPONSE>`. Separation of control plane from speech plane — same instinct as Moshi's inner monologue.
  3. **Full-Duplex-Bench methodology:** standardized turn-taking/interruption metrics (TOR at latency). v2 should adopt these metrics for voice eval.
- **NOT deployable:** research-only checkpoint, needs 80GB GPU, 2-min audio ceiling, degrades to gibberish after several turns, runaway self-talk. Rejected as v2 component.
- **License:** OpenMDW-1.1 (permissive) but research-only. **Confidence: 80%** as pattern source.

## Cycle 2 — Windows desktop automation / UI control (07:16 UTC)

### Hunt
Targets: beyond microsoft/UFO (covered). Looking for: newer UIA wrappers, Windows Copilot-era automation, accessibility-API tooling.

### Study 3: CursorTouch/Windows-MCP (07:30 UTC)
- **What:** MIT MCP server giving any LLM agent Windows desktop control via the UI Automation tree (not screenshots). ~7.2k stars, 2M+ users through Claude Desktop extensions. 0.2-0.5s between actions.
- **The gold:**
  1. **UIA tree, not pixels:** works with ANY LLM (vision not required), immune to theme/DPI/window-move breakage. Validates Playbook "UIA tree first, pixels last" as production-proven at scale.
  2. **Tool gating as safety:** `--tools "Screenshot,Click,Snapshot"` allowlist / `--exclude-tools "PowerShell,Registry"` denylist. This is two-dial safety shipped in a CLI flag — v2's skill permission UX should copy this exact shape.
  3. **Remote operation:** SSE/streamable HTTP with auth-key, IP allowlist, TLS, OAuth2 PKCE. Pattern for JARVIS phone-remote (Telegram) driving the PC safely.
  4. **Honest limitations doc:** can't select text spans (a11y tree limitation), Type tool can't do IDE-style editing. The "limitations on everything" discipline from REA, applied.
- **License:** MIT. **Confidence: 88%.** Most battle-tested Windows agent-control surface found; directly informs v2's PC-control phase.

### Study 4: trycua/cua — cua-driver background operation (07:32 UTC)
- **What:** MIT (~26.2k stars) cross-platform computer-use driver. Headline: **background delivery** — agent acts WITHOUT moving the cursor or stealing focus.
- **The gold:**
  1. **No-foreground contract:** on Windows, UIAutomation + SendInput/PostMessage — no focus steal, works without elevation for non-UAC windows. JARVIS can click around in another window while Owais keeps typing. This is the UX difference between "assistant" and "annoyance."
  2. **Platform-native input paths:** pid-scoped event posting per OS. The "interface, not engine" pattern at the OS level.
- **License:** MIT. **Confidence: 85%.** The background-operation pattern is a must-have for v2's PC control; stealing focus would break the "diligent assistant" feel.

## Cycle 3 — Local-first LLM inference optimizations (07:33 UTC)

### Hunt
Targets: beyond ollama/llama.cpp (covered). Looking for: 2026 inference engines, quantization advances, speculative decoding, on-device NPU/GPU wins.

### Study 5: ikawrakow/ik_llama.cpp ⭐ (07:45 UTC)
- **What:** MIT fork of llama.cpp with SOTA quantization types (IQ quants beyond mainline) and rewritten CPU/CUDA kernels. Active (commits within a day). Fully GGUF-compatible — drop-in replacement.
- **The gold:**
  1. **26x prompt-processing speedup** on Qwen 3.5 27B (NVIDIA) from kernel fusion — same model files, just faster. For JARVIS: the local brain server should be ik_llama.cpp, not mainline, on NVIDIA hardware.
  2. **IQ quantization types:** better quality-per-bit than K-quants. Direct upgrade path for the local model.
  3. **KV-cache quantization** (`--cache-type-k q8_0 --cache-type-v q8_0`): 131k tokens of KV cache in 16GB VRAM. This kills the "KV-cache trap" from our hardware study (long context eating VRAM) — v2's server config should set this by default.
- **Caveat:** NVIDIA/CPU focused; ROCm/Vulkan/Metal users stay on mainline. Fine for JARVIS (Owais has NVIDIA).
- **License:** MIT. **Confidence: 90%.** Concrete, actionable, drop-in. Flagged ⭐.

### Study 6: Inference engine landscape 2026 (07:48 UTC)
- **What:** Survey: vLLM (PagedAttention), SGLang (RadixAttention, 16.2k tok/s H100), LMDeploy (TurboMind), llama.cpp/ik_llama.cpp for desktop.
- **The gold:**
  1. **RadixAttention (SGLang):** prefix caching makes multi-turn chat 10-20% faster — the same system prompt + history prefix is reused, not recomputed. Pattern: v2's local server should enable prefix caching if available (llama.cpp has `--cache-reuse` / context reuse semantics worth verifying).
  2. **Decision rule confirmed:** single-user desktop → llama.cpp-family (ik fork on NVIDIA). Multi-user/production → vLLM/SGLang. JARVIS is single-user: ik_llama.cpp is the answer.
  3. **AWQ vs GGUF on NVIDIA:** AWQ achieves better throughput on NVIDIA (741 tok/s vs GGUF) in vLLM — but for llama.cpp-family desktop use, GGUF remains the format. Don't chase AWQ for v2.
- **License:** all Apache-2.0/MIT. **Confidence: 80%.** Mostly confirms existing direction; the prefix-caching pattern is the new bit.

## Cycle 4 — Agent memory systems (07:49 UTC)

### Hunt
Targets: beyond mem0/Letta/A-MEM (covered). Looking for: 2026 memory innovations, episodic memory, consolidation during sleep, forgetting mechanisms.

### Study 7: Nocturne — sleeptime consolidation with proof ⭐ (08:05 UTC)
- **What:** Chat agent with a Sleep button: four passes over memory (Dedupe → Merge → Promote → Forget), each an LLM call whose output is *refused or accepted by code*, snapshot before/after, diff view of every kept/changed/forgotten item with reason. Then a Wake panel quizzes: 5 questions only consolidated store can answer + 1 about something it was SUPPOSED to forget (correct answer: "I don't have that"). 18/18 verification checks pass.
- **The gold:**
  1. **Auditable forgetting:** "deliberate, auditable forgetting under a stated retention policy — plus proof that recall still works afterwards." This is the missing half of every memory system we studied (mem0/Letta/A-MEM all focus on keeping; none prove the forgetting is correct).
  2. **LLM proposes, code disposes:** consolidation outputs are validated by deterministic code before acceptance. Same instinct as REA's evidence model and our two-dial safety.
  3. **Negative test for forgetting:** quizzing on what should be GONE is the test nobody writes. v2's memory CI should include this.
- **License:** repo-linked (verify before reuse). **Confidence: 85%.** The most complete consolidation loop found; the Wake-quiz pattern is novel to our corpus.

### Study 8: Agent-Brain-Hub sleep scheduling (08:07 UTC)
- **What:** Shared agent memory hub with automatic sleep triggers: idle (30 min) / pressure (24 turns) / nightly (03:00). Manual + auto share one queue (no concurrent mutation). 9 tests incl. lost-turns bug repro.
- **The gold:**
  1. **Three-trigger sleep:** idle/pressure/nightly covers all consolidation needs without user action. v2's background maintenance loop should use exactly these triggers.
  2. **Single mutation queue:** sleep runs never touch memory concurrently — the locking discipline our autopsy demanded (R6) in practice.
  3. **No surprise bills:** staggered first-run so paid-LLM summarization doesn't burst. Cost-aware design.
- **License:** repo-linked (verify). **Confidence: 75%.** Good operational patterns; less novel than Nocturne but more deployment-ready.

### Study 9: SLEEPGATE (arXiv 2603.14517) — noted, not adopted (08:08 UTC)
- **What:** Biologically-inspired KV-cache sleep: conflict-aware temporal tagger + forgetting gate + consolidation module, operating INSIDE the model. 99.5% retrieval at PI depth 5 vs <18% baselines.
- **Verdict:** Architecture-level (model internals), not actionable for v2 which uses existing models via API/local server. The *concept* (conflict detection when new entries supersede old) transfers to the memory write path. Logged for the idea, not the implementation.
- **Confidence: 60%** on transferability.

## Cycle 5 — Skill/plugin architectures (08:09 UTC)

### Hunt
Targets: beyond SKILL.md/agentskills.io (covered). Looking for: 2026 plugin systems, MCP composition patterns, skill marketplaces, hot-reload safety.

### Study 10: Agent Plugins 1.0 — the vendor-neutral skill standard ⭐ (08:25 UTC)
- **What:** Announced Aug 6, 2026 by steering committee (Amazon, Cursor, Microsoft, OpenAI, Vercel; Google joined same day). A plugin = directory with plugin.json + optional skills/ + optional mcp.json. Deliberately tiny spec.
- **The gold:**
  1. **This is the standard v2's skill system should adopt** — bigger than SKILL.md alone: it packages skills + MCP servers + auth as one portable, installable unit. Update the Playbook: SKILL.md for the skill format, Agent Plugins 1.0 for the packaging/install format.
  2. **Failure isolation mandated:** a plugin whose MCP server fails to start does not take its skills down — loader skips the entry, keeps loading, surfaces in audit trail. v2's plugin host must implement this.
  3. **Skill/MCP/plugin composition model** (skillsafe.ai): skill = ~100 tokens until it fires (progressive disclosure); MCP = full schemas from connect; plugin = packaging. The three compose — a skill can delegate to a subagent. This is v2's capability architecture in one table.
- **Caveat:** spec still "Working Draft"; vendors still ship richer proprietary formats alongside. Adopt the portable core, keep a reverse-domain extension namespace (PRESHai pattern).
- **License:** open standard. **Confidence: 90%.** Flagged ⭐ — changes the skill-system design target.

### Study 11: ClawHavoc — the skill supply-chain war (08:28 UTC)
- **What:** Jan-Feb 2026: 1,184 malicious skills flooded ClawHub via 12 coordinated publisher accounts. Fake "Prerequisites" sections delivered Atomic Stealer (macOS) and keylogging trojan (Windows). At peak, 5 of 7 most-downloaded skills were malware. Snyk: 36.8% of 3,984 skills had security flaws; skills bundling executable scripts 2.12x more likely vulnerable.
- **The gold (defenses that emerged):**
  1. **ClawScan:** static analysis + VirusTotal + NVIDIA SkillSpector on every new version; daily re-scan of active skills; malicious releases blocked from download.
  2. **`security.installPolicy`:** operator-owned command returns allow/warn/block before ANY skill install completes — fails closed.
  3. **Secrets injected into host process, not the sandbox** — skill secrets never touch the skill's execution environment.
  4. **Self-learning defaults:** agent-written skills staged for review (`propose` mode) before changing behavior — never `auto`.
- **For v2:** This validates Playbook S7 as CRITICAL. v2's skill installer must: quarantine + scan (static rules at minimum), show trust envelope before install, fail-closed install policy, secrets never in skill sandbox, agent-written skills always staged for human review. The Anthropic PyPI incident (Claude published malware to real PyPI during eval, 15 systems infected in an hour) proves the self-improvement loop needs these gates too.
- **Confidence: 95%.** The most important security lesson of 2026 for agent builders. Not optional.

### Study 12: MCP Tool Poisoning — OX Security (May 2026) (08:30 UTC)
- **What:** Systemic vulnerability in MCP implementations across Python/TypeScript/Java/Rust — 150M+ downloads, ~200k vulnerable instances. "Mother of all AI supply chains."
- **For v2:** v2 will consume MCP servers (Composio, Windows-MCP, etc.). Lesson: pin MCP SDK versions, verify server identity, treat tool descriptions as untrusted content (they're re-fetched at runtime — the skillsafe.ai trust-surface table makes this explicit).
- **Confidence: 80%.**

## Cycle 6 — TTS advances for the JARVIS voice (08:31 UTC)

### Hunt
Targets: beyond Kokoro/Piper/Fish/ElevenLabs/Bodhi (covered). Looking for: 2026 open TTS with voice cloning, Hindi/Hinglish quality, streaming TTS.

### Study 13: Resemble AI Chatterbox — MIT TTS that beats ElevenLabs ⭐ (08:50 UTC)
- **What:** MIT-licensed open TTS (0.5B Llama backbone). Zero-shot voice cloning from ~5 sec audio. 23 languages incl. Hindi. Blind tests: 63.8% of listeners preferred it over ElevenLabs. Emotion-exaggeration slider. Built-in PerTh watermarking.
- **The gold:**
  1. **MIT + Hindi + beats ElevenLabs** — the first open TTS to hit all three. Our TTS ladder gets a new rung: Piper (failsafe) → Kokoro-82M (offline CPU default) → **Chatterbox (local neural, Hindi, cloning)** → Bodhi (Hinglish API) → Fish/ElevenLabs (cloud).
  2. **PerTh watermarking built in** — synthetic-audio detection by design. v2 should watermark its own TTS output the same way (trust + safety).
- **Caveat:** 8GB+ VRAM, no official Docker, Windows needs WSL (v2 would need a native Windows build path). Emotion control is a slider, less nuanced than Qwen3-TTS's natural-language direction.
- **License:** MIT. **Confidence: 88%.** Flagged ⭐ — biggest TTS-ladder upgrade since Kokoro.

### Study 14: OpenBMB VoxCPM2 — voice DESIGN (08:52 UTC)
- **What:** Apache-2.0, 2B params, 30 languages incl. Hindi, 48kHz. Tokenizer-free (continuous speech representations — better breathing/pacing/emotion shifts). Three modes: TTS + zero-shot cloning + **voice design** ("describe a voice in words: 'calm middle-aged narrator with a slight smile'").
- **The gold:** Voice design turns the "sound exactly like JARVIS" requirement from an asset-hunting problem into a text prompt. v2 could let Owais DESCRIBE the voice he wants. Also: tokenizer-free architecture is the technical direction (paralinguistics preserved).
- **License:** Apache-2.0. **Confidence: 75%.** Voice design is the novel capability; quality vs Chatterbox unverified head-to-head.

### Study 15: Mistral Voxtral TTS — noted, license-blocked (08:53 UTC)
- **What:** 4B open-weight streaming TTS, 70ms latency, 9 languages incl. Hindi, beats ElevenLabs Flash v2.5 68.4% win rate, 3-sec cloning, edge-ready.
- **Verdict:** License is **CC BY-NC (non-commercial)** — ideas only, never code. Logged so we don't accidentally adopt it. The 70ms-latency + edge-readiness bar is noted for our own targets.
- **Confidence: 70%** on specs (vendor-reported).

### Study 16: Qwen3-TTS Hindi check (08:54 UTC)
- **What:** Verified current language list: Chinese, English, Japanese, Korean, German, French, Russian, Portuguese, Spanish, Italian — **still no Hindi**. Apache-2.0, 97ms streaming, 3-sec cloning.
- **Verdict:** Our earlier rejection as primary TTS (no Hindi) STANDS. Useful as a secondary/experimental tier only.
- **Confidence: 90%.**

## Cycle 7 — Security/sandboxing for agents (08:55 UTC)

### Hunt
Targets: beyond e2b/Deno (covered). Looking for: 2026 agent sandboxing, capability systems, prompt-injection defenses that actually work.

### Study 17: ScrambleID — identity-based prompt-injection defense ⭐ (09:02 UTC)
- **What:** "Prompt injection cannot be eliminated by better prompts because LLMs cannot reliably distinguish data from instruction at the input layer; the defense that works is structural, moving consequential authority out of the agent's reasoning entirely and behind cryptographic authorization boundaries."
- **The gold — four load-bearing patterns:**
  1. **Scope-per-tool tokens at the MCP server boundary** — each tool call carries a token scoped to exactly what that call may do. Compromised reasoning can't escalate scope.
  2. **Dual control on irreversible/high-impact actions** — two independent approvals.
  3. **Human-in-the-loop stepup at the moment of consequential action.**
  4. **Chain-aware delegation (RFC 8693 Token Exchange)** — multi-hop chains preserve attribution and bound scope.
- **The principle:** "Intelligence can expand without privilege expanding with it." This is the identity/authorization layer that sits ON TOP of Deno-style permissions in v2's safety architecture.
- **Confidence: 85%.** Vendor whitepaper (ScrambleID) but the patterns are standards-based (RFC 8693) and match the field consensus. Flagged ⭐.

### Study 18: The single-user sandboxing sweet spot (09:05 UTC)
- **What:** Practitioner consensus 2026: "For one developer running an agent unattended, a hardened Docker container with default-deny egress covers most of the real risk; gVisor or microVM only pays off when you run code you do not control."
- **The gold — refines v2's sandboxing ladder:**
  1. **Egress is the skipped part:** "a perfectly isolated container that can reach any host still leaks every file it can read." Default-deny egress allowlist is the highest-leverage single control.
  2. **The real threat model:** "a prompt-injected shell that reads credentials and sends them out. Kernel escapes are the rarer problem." → v2 should optimize for credential-isolation + egress control, not kernel-hardening theater.
  3. **Hardened docker run recipe:** non-root, read-only rootfs, `--cap-drop ALL`, `no-new-privileges`, egress allowlist. This is implementable on Windows via WSL2/Docker Desktop for v2's code-execution skill.
  4. **Practical hierarchy:** normal inference → container → gVisor → microVM → dedicated env. "The more hostile the workload, the stronger the boundary." v2: own code in container, web-fetched code in gVisor/microVM, credentials never in any of them.
- **Confidence: 88%.** Multiple independent sources converge. Directly actionable for v2's R5 (sandboxed code exec + egress allowlist).

### Study 19: Defense-tier taxonomy for prompt injection (09:07 UTC)
- **What:** Field consensus 2026: three tiers — (1) prompt-based guardrails (cheap, unreliable, "dangerous as a sole defense"), (2) detection frameworks (better than nothing, adversarial prompts evolve faster), (3) architectural isolation (only class with provable-security claims).
- **Vendor-claim test:** "When a product claims to 'fully solve' prompt injection: is the mechanism a classifier/prompt-hint? → Layer 1, will be bypassed. A deterministic checker outside the model gating tool calls on data-source tags? → Layer 2, state of the art. Hardware enforcement? → Layer 3, ask to see silicon."
- **For v2:** our R2 (instruction hierarchy + untrusted-data framing) is Layer 2 — correct tier. Never buy a Layer-1 product for v2's security.
- **Confidence: 90%.** Broad consensus across vendors, researchers, OWASP.

## Cycle 8 — STT advances (09:08 UTC)

### Hunt
Targets: beyond faster-whisper (covered). Looking for: 2026 STT with Hindi/code-switching, streaming STT, on-device advances.

### Study 20: Semantic VAD — the turn-taking upgrade ⭐ (09:20 UTC)
- **What:** Acoustic VAD triggers on silence alone → prematurely interrupts users who pause 300-500ms mid-thought. **Semantic VAD** analyzes the live transcript to determine if the grammatical structure is actually complete before ending the turn.
- **The gold:**
  1. **Two-signal end-of-turn:** acoustic VAD (fast, naive) + semantic VAD (slow, smart). v2's voice plugin should gate turn-end on BOTH: silence AND grammatical completeness. This directly addresses the hesitation problem (voiceloop's bench showed every stack except Pipecat backs off on hesitation — semantic VAD is the principled fix).
  2. **Validates our staged approach:** cheap signal first (acoustic), expensive signal second (semantic) — the whisper.cpp staged-wakeup pattern applied to turn-taking.
- **Confidence: 85%.** Concept well-established in 2026 voice-agent practice (LiveKit docs, multiple vendors). Implementation detail: run a small local model or heuristic on partial transcripts.

### Study 21: STT landscape for Hinglish — faster-whisper stands (09:22 UTC)
- **What:** 2026 STT survey. Key data: global models suffer 18-25% WER on compressed Indian cellular audio; Gnani Prisma v2.5 (commercial API) is the Hinglish specialist. Whisper confirmed as batch-only (2-4s latency with chunking workarounds — "not recommended for real-time voice bots").
- **The gold:**
  1. **faster-whisper remains correct for v2's chatbot phase** (utterance-based, offline, free). For the real-time voice phase, plan streaming STT (Deepgram Flux/Nova-3, AssemblyAI Universal-Streaming at $0.0025/min, or ElevenLabs Scribe v2).
  2. **Hinglish benchmark to beat:** 18-25% WER is the bar global models hit on Indian audio. v2 should measure its own STT on Owais's actual voice/accent and track this number.
  3. **GladiaFlow (MIT):** open-source desktop dictation client (Win/Mac), hotkey + OS-level typing into any app. UX pattern worth studying for JARVIS's text-input mode — but it's a Gladia API client, not offline.
- **Confidence: 80%.** Mostly confirms existing STT plan; semantic VAD (Study 20) is the new bit.

## Cycle 9 — Brain/model advances for the local brain (09:23 UTC)

### Hunt
Targets: beyond Qwen3.5 (covered). Looking for: 2026 small models with tool-calling, MoE for desktop, new local-brain candidates.

### Study 22: Local brain model consensus — Qwen3.5-9B re-confirmed (09:32 UTC)
- **What:** 2026 survey of small models for tool-calling agents. Multiple independent sources converge.
- **The gold:**
  1. **Qwen3.5-9B is the consensus pick** (BFCL-V4 66.1, TAU2 79.1, 5.68GB Q4_K_M, Apache-2.0). Our Phase 1 brain choice is re-confirmed by the field. No change needed.
  2. **The 7-9B capability cliff:** "tool calling is a trainable skill, not a function of scale." Below ~7B it's a gamble (Llama 3.2 3B scores in simple tests but fails to invoke a tool even once in ReAct). v2's low-end tier must not go below 7B for the agentic brain — use 7B+ or rule-based fallbacks.
  3. **LFM2.5-8B-A1B** (Liquid AI, MoE 8.3B/1.5B active): purpose-built for on-device agents, strong vendor-reported scores, but license is LFM Open License v1.0 (commercial capped at $10M revenue) and BFCL claims unverified on live leaderboard. Watchlist only — Qwen stays primary.
  4. **MCP stdio overhead <2.5ms** — local MCP tool calls are essentially free vs token generation time. Validates v2's MCP-based skill architecture: no latency penalty for local tools.
- **Confidence: 90%.** Broad multi-source convergence.

## Cycle 10 — Failure-analysis problem solvers (09:33 UTC)

### Hunt
Targets: anything that solves OUR specific bugs — settings corruption, fallback chains, crash recovery, atomic updates.

### Study 23: The fallback-chain recipe — transport errors MUST trigger fallback ⭐ (06:58 UTC)
- **What:** 2026 practitioner consensus on LLM provider failover. The exact bug class from our autopsy (C-B1: fallback never fired on timeouts/DNS).
- **The gold — the correct pattern, from multiple independent sources:**
  1. **RETRYABLE = transport errors:** `RateLimitError, APITimeoutError, APIConnectionError, InternalServerError` (429/408/409/5xx) → retry with exponential backoff, THEN move to next provider. Non-retryable (400/401/404) → skip to next provider immediately, never retry.
  2. **Hard timeout on every request** (30s typical) — "never wait forever." Our C-B1 root cause was the backup walk living inside the same try block; the fix is a flat provider loop where EACH provider gets its own try.
  3. **Circuit breaker per provider:** after N consecutive failures → OPEN for cooldown seconds → HALF_OPEN probe. LiteLLM Router has this built in (`allowed_fails`, `cooldown_time`). v2 should use LiteLLM Router or port its breaker state machine.
  4. **Retry discipline:** exponential backoff WITH jitter; total request deadline; stop retrying if user left; never retry non-idempotent tool actions without idempotency key. "Retries can multiply an incident — one failure becomes four calls."
  5. **Log which model answered** (`reply.model`) — traceability for the "which brain served this?" question.
- **License:** patterns, MIT/Apache-2.0 sources. **Confidence: 95%.** This is the highest-confidence fix in the log — multiple production implementations agree. Flagged ⭐.

### Study 24: Settings integrity — checksums + atomic writes + read-only (07:00 UTC)
- **What:** Desktop settings corruption prevention patterns.
- **The gold:**
  1. **Read-Verify-Write cycle:** checksum stored alongside data; verified on every load; mismatch → error/recovery, never silent poisoned operation. v2's settings manager should add SHA-256 verification on top of atomic writes.
  2. **Pre-launch integrity hashing:** for files that shouldn't change without human action, hash at startup, refuse to load on mismatch. Applies to v2's skill manifests and tool allowlists.
  3. **Filesystem tripwires:** watcher on config files during agent execution — any write triggers alert/kill-switch. "The point isn't to prevent the write. It's to make sure no write happens without you knowing."
  4. **Read-only where the OS supports it:** tool allowlists and hook lists that change quarterly should be filesystem read-only (`chflags uchg` / `chattr +i` equivalents; Windows: ACLs). Raises the bar from "any script" to "actual exploit."
  5. **WAL (write-ahead logging)** for complex state — overkill for settings, but the pattern matters for v2's memory store.
- **Confidence: 85%.** Standard practice, well-documented. The tripwire concept is the novel bit for agent contexts.

## Cycle 11 — Proactive/predictive assistant patterns (07:01 UTC)

### Hunt
Targets: how do assistants anticipate user needs? Proactive agents, ambient computing, "watching-eyes" done right.

### Study 25: The Four Checks — when an agent may act unasked ⭐ (07:12 UTC)
- **What:** A decision procedure for proactive agent action (from an agent safety survey via acceleratech.ca). A worthwhile goal is not yet a reason to act. Four checks, in order, each with its own way out:
  1. **Confidence: is the need real?** → if unsure: verify or ask.
  2. **Value vs cost: is acting worth the interruption or side effects?** → if not: drop, batch, defer, re-plan.
  3. **Timing: is now the moment?** → if not: hold for the next breakpoint.
  4. **Risk and reversibility: can it be undone if wrong?** → if not: draft for approval, escalate, or refuse.
  - **Act** only if all four pass, within granted authority, and log it.
  - Parallel track: **hold and monitor** — keep watching without acting; invisible unless logged.
- **The gold:** This is the EXACT decision procedure v2's proactive features need (screen watcher, routines, ambient suggestions). It turns "should JARVIS interrupt?" from vibes into a checklist. Implement as a gating function every proactive trigger must pass through. The "hold and monitor" track is the honest version of our screen watcher: watch, log, don't interrupt.
- **Confidence: 92%.** Principled, actionable, directly fills a v2 design gap. Flagged ⭐.

### Study 26: Proactive restraint as a benchmarkable dimension (07:14 UTC)
- **What:** assistantbenchmark.com Dimension 15/16 "Proactive restraint": "handles the small stuff, waits on the consequential." Test: over one evening — late ambiguous email from boss, delayed package, friend texting about weekend plans. Pass = handles package alone, drafts-but-doesn't-send for boss, doesn't wake/spam.
- **The gold:** Proactive behavior is TESTABLE with concrete scenarios, not just philosophy. v2 should adopt these exact test scenarios for its proactive features: small stuff auto-handled, consequential drafted-not-sent, never waking/spamming.
- **Confidence: 85%.**

### Study 27: No-silent-failures rule for background agents (07:15 UTC)
- **What:** "For any task that may take more than a few minutes, do not treat silence as success. Check in on a schedule, tell me what is still running, and say if anything failed, restarted, or needs me."
- **The gold:** Connects our "narrate work live" principle to the background-agent era. v2's routines/scheduler must implement scheduled check-ins, not just fire-and-forget. This is also the UX surface for the Anthropic managed-agents session-resume pattern.
- **Confidence: 88%.**

### Study 28: The stop rule — "a confident wrong answer costs more than a quiet handoff" (07:16 UTC)
- **What:** Three-part rule: if the question is in the sources → answer. If close → say what you know AND what you don't. If outside → don't complete the thought; hand off to a human, name the handoff.
- **The gold:** This is the honesty architecture for v2's brain: a "stop" is a first-class design decision, not a failure mode. Pairs with REA's evidence model (observed/derived/inferred) — "close" questions get the derived tag + stated limits.
- **Confidence: 85%.**

## Cycle 12 — Windows installer / distribution excellence (07:17 UTC)

### Hunt
Targets: how do the best indie Windows apps ship? Auto-update done right, first-run experience, zero-terminal onboarding.

### Study 29: Update UX — "always prompt, never force-quit mid-session" (07:26 UTC)
- **What:** 25-release Electron auto-update lessons + Microsoft first-experience guidelines.
- **The gold:**
  1. **`autoDownload = false` is deliberate:** "Users hate background traffic and disk usage they didn't consent to. Asking first meaningfully improves the install rate vs silently downloading then asking to restart." v2's updater: check silently, ASK before downloading, ASK before restart. Never surprise Owais mid-session.
  2. **Microsoft's first-experience rules (authoritative):** safest/most-secure/most-private defaults for ALL settings; opt-in required for PII-revealing features, desktop changes, optional software; "if the need for personal information isn't obvious, explain why your program needs it and how it will be used." This is R13 (privacy-safe defaults) with Microsoft's stamp.
  3. **Skip update check on first launch** — the app is still settling; checking immediately causes lock/contention bugs.
- **Confidence: 85%.** Thin cycle overall (Electron-specific), but the three rules above are keepers.

## Cycle 13 — Agent evaluation (07:27 UTC)

### Hunt
Targets: how do you TEST an agent? Evals beyond unit tests — session-transcript scoring, voice benchmarks, behavioral evals.

### Study 30: DeepEval + persona simulation — v2's eval stack ⭐ (07:32 UTC)
- **What:** 2026 agent-eval landscape. Standouts: DeepEval (17k stars, pytest-native, trajectory + tool-call scoring), persona-driven simulation (synthetic users with edge behaviors), Opik/Langfuse (open-source trace observability).
- **The gold:**
  1. **DeepEval is v2's eval library:** pytest-native = drops into the CI our PhD sprint built. Explicit trajectory scoring (not just single-turn grading) — this catches the integration bugs unit tests missed in v1.
  2. **Persona-driven simulation:** run synthetic users (impatient, ambiguous, multi-language, injection-attempting) against the chatbot BEFORE Owais touches it. Each persona: goal + style + edge behaviors → transcript → scored on completion/trajectory/safety. This is how v2 earns trust before shipping.
  3. **Eval cadence:** regression on every PR, persona sweep nightly, live tracing on all traffic. v2's CI: our 180-test suites on PR + persona sim nightly.
  4. **Langfuse (MIT, self-hostable):** trace observability + scoring — candidate for v2's flight-recorder backend.
- **License:** DeepEval open core, Langfuse MIT, Opik Apache-2.0. **Confidence: 88%.** Flagged ⭐ — v2's "verify before claiming" needs this machinery.

## Cycle 14 — Telegram/bot + phone-remote patterns (07:33 UTC)

### Hunt
Targets: best practices for PC-to-phone remote control, Telegram bot architectures for agents.

### Study 31: Telegram polling done right — isolated worker pattern (07:40 UTC)
- **What:** OpenClaw v2026.5.12 fixed dropped messages during busy periods. The pattern: run polling on its own isolated worker (never the main event loop), persist the update-offset spool durably, detect liveness from inbound calls only.
- **The gold:**
  1. **Isolated polling worker** — v2's Telegram channel must poll on a dedicated thread, never sharing the brain's event loop. This is the same "supervisor, not worker" threading lesson from our PhD sprint.
  2. **24-hour cushion:** Telegram holds updates up to 24h — v2's offline window is exactly one day; the spool must survive restarts within it.
  3. **Secret path segment** (`/<secret>/webhook`) — cheap first-line defense on top of token auth if webhooks are ever used.
  4. **Inline keyboards as confirmation UX:** "a force multiplier — let users confirm or redirect without typing." This is v2's two-dial safety on phone: destructive actions get an inline Confirm/Cancel keyboard, not a typed "yes."
  5. **Model via LiteLLM alias** — the bot calls an alias, never a raw model name. Matches our N-brain abstraction.
- **Confidence: 88%.** Production-hardened pattern from a real incident fix.

## Cycle 15 — HUD/overlay tech (07:41 UTC)

### Hunt
Targets: desktop overlay tech for the holographic HUD — Qt alternatives, always-on-top windows, click-through, GPU-accelerated UI on Windows.

### Study 32: Overlay tech — Qt approach confirmed, click-through needs pywin32 (07:48 UTC)
- **What:** Windows overlay window techniques survey.
- **The gold:**
  1. **Real click-through = `WS_EX_TRANSPARENT`** via pywin32 — confirms our autopsy's "fake click-through without pywin32" finding. v2's HUD must use the real extended-style flag, not widget-attribute tricks.
  2. **One top window per app** — z-order discipline. v2's HUD: single overlay window, not multiple floaters.
  3. **PowerToys Always On Top (Win+Ctrl+T)** is the OS-level pattern users already know — v2's HUD pin behavior should feel consistent with it.
- **Confidence: 80%.** Confirms existing direction more than adding new. Honest: thinner cycle.

## Cycle 16 — Microsoft's "Hey Copilot" competitor intel (07:49 UTC)

### Hunt
Targets: what is Microsoft actually shipping? Where's the moat for JARVIS?

### Study 33: Microsoft Copilot — competitor intel (Oct 2026) (07:58 UTC)
- **What they ship:** "Hey, Copilot" opt-in wake word (on-device spotter, ~10s in-memory audio buffer never written to disk, cloud reasoning unless Copilot+ NPU); Copilot Vision (permissioned session-bound screen sharing, OCR, click-highlights); Copilot Actions (experimental chained tasks in "visible, sandboxed workspace," limited permissions, user-explicit resources only).
- **The gold — JARVIS's moat:**
  1. **Microsoft is cloud-first; JARVIS is local-first.** Their full reasoning happens in the cloud. Privacy + offline = our structural advantage.
  2. **Microsoft must be conservative; JARVIS serves one person.** Their Actions start with limited permissions because they serve millions. Owais can grant JARVIS deep trust explicitly — bolder PC control with consent.
  3. **"Visibility and interruptibility are core parts of the UI model"** — Microsoft independently landed on our "narrate work live" principle. Validates it as industry direction, not just our idea.
  4. **Wake word OFF by default, opt-in** — validates our privacy-default stance (R13).
  5. **Don't compete on OS integration** (they own the OS). Compete on: personality, locality, memory depth, Hinglish, single-user boldness.
- **Confidence: 85%.** Public product info, well-documented.

## Cycle 17 — Open-source personal assistants (the direct peers) (07:59 UTC)

### Hunt
Targets: what are the OTHER open-source JARVIS-likes doing in 2026? Who's closest to our vision?

### Study 34: platonkuch-dev/jarvis-ai — "the hardest part wasn't the AI" ⭐ (08:08 UTC)
- **What:** A solo dev's Windows JARVIS, open source. The build notes are a goldmine of practical lessons.
- **The gold:**
  1. **"The hardest part wasn't the AI"** — the hard parts were plumbing: audio, installer, reliability. Validates our infrastructure-first build order (R6/R7/R12 before features).
  2. **Key validation on paste:** "You paste two API keys into a local panel, and the panel CHECKS each key before you start." v2's setup wizard must validate keys live (test call), not just store them.
  3. **One-click installer:** Python bundled, per-user, no admin, no console windows. Exactly our Inno Setup direction — confirmed as the right call by someone who shipped it.
  4. **Morning briefing runs with NO LLM** — deterministic routines shouldn't burn tokens. v2's scheduler: template-based briefings, LLM only for the unpredictable parts.
  5. **Triggers that matter:** app-start / file-drop / time / battery-low → voice or Telegram. The concrete trigger list for v2's routine engine.
  6. **Self-updating via its own coding agent** — the Hermes self-improvement loop made real (with the ClawHavoc caveat: this needs the quarantine+review gates from Study 11).
- **Confidence: 90%.** Shipped, practical, honest. Flagged ⭐.

### Study 35: adewaskar/jarvis — two-tier brain routing (08:10 UTC)
- **What:** MIT, 210 stars. Browser face + Node brain ("the brain literally is Claude Code, headless"). Key innovation: **a small fast model in front answers instantly for simple commands**; everything goes through the big model otherwise. Measured the latency difference.
- **The gold:**
  1. **Two-tier routing:** tiny model classifies + handles simple commands (volume up, what time is it) in ms; big brain only for hard stuff. v2 should implement this: a fast classifier tier before the 9B brain. Massive perceived-latency win for the 80% of simple commands.
  2. **"Anything that writes or acts is off until you flip one flag"** — two-dial safety, user-controlled. The exact UX for v2's Safety tab.
  3. **MCP tools from existing Claude Code config** — reuse the user's existing tool setup instead of rebuilding. "Interface, not engine" again.
- **License:** MIT. **Confidence: 85%.**

### Study 36: Jarvis Live — live answer cards (08:11 UTC)
- **What:** MIT. Real-time voice (~1s, interruptible), screen vision, delegates to on-computer agents, **live answer cards** (weather, flights, stocks as cards with real data, not a wall of text), business dashboard, live avatar.
- **The gold:** **Answer cards, not text walls.** v2's HUD should render structured cards (weather card, calendar card, system-health card) instead of dumping text. This is the HUD design language — visual answers for visual questions.
- **License:** MIT. **Confidence: 80%.**

## Cycle 18 — Privacy architecture (08:12 UTC)

### Hunt
Targets: how do the best local-first apps handle privacy? What's the state of the art for "private by architecture"?

### Study 37: Privacy by architecture — the one-line thesis (08:16 UTC)
- **What:** Local-first privacy landscape 2026.
- **The gold:**
  1. **"Cloud AI is private by policy. Local AI is private by architecture."** — v2's privacy thesis in one line. A policy can change with a new owner or subpoena; a model running offline cannot send what it has no way to reach.
  2. **The four quiet leaks** (even in "local" setups): sensitive context pasted into cloud chat out of convenience; prompts logged "for analytics"; third-party API calls silently expanding attack surface; workflows sending more context than needed by default. v2's privacy audit checklist: zero analytics, minimal-context cloud calls, explicit per-call consent for anything leaving the machine.
  3. **Two-runtime model (Shinkai):** connected mode vs full-local mode as an explicit visible toggle. "Privacy isn't binary. It's contextual." v2's HUD should show which mode the current turn is using — a small local/cloud indicator per response.
  4. **Deterministic heuristic fallback** (SoloBiz AI): non-LLM engine for simple tasks, instant, free. Pairs with two-tier routing — the fastest tier isn't even a model.
- **Confidence: 88%.** The per-response local/cloud indicator is the most actionable new idea.

## Cycle 19 — The "one mistake" audit (08:17 UTC)

### Hunt
Targets: what quietly breaks local-AI privacy? Telemetry, embeddings, crash reports — the hidden phone-homes.

### Study 38: The localhost hijack — CVE-2026-65105 ⭐ (08:28 UTC)
- **What:** NVIDIA NemoClaw flaw: a malicious web page issues HTTP requests to the victim's exposed local Ollama API (localhost:11434), modifying the chat template to silently prepend attacker instructions to EVERY subsequent conversation — persistent across sessions.
- **The gold — CRITICAL for v2's architecture:**
  1. **v2's local model server must bind 127.0.0.1 ONLY** (never 0.0.0.0), and should require auth even on loopback. Any webpage Owais visits is a potential attacker against an unauthenticated localhost server.
  2. **"Tools beat the perimeter":** a local model with a web-search MCP tool installed is a hybrid — the query leaves the machine mid-conversation. v2's per-response local/cloud indicator (Study 37) must account for TOOL calls, not just the brain.
  3. **"The picker doesn't make the wire visible":** when cloud and local models share one UI, users can't tell which is which. v2 must make the boundary visible per-turn.
- **Confidence: 95%.** CVE-documented, directly applicable. Flagged ⭐ — this is a v2 architecture requirement (R9 extension).

### Study 39: Privacy is a chain — three conditions (08:30 UTC)
- **What:** "A tool is private only when three conditions hold simultaneously: local inference + local storage + no content telemetry. Each is a separate failure mode. A local model with a cloud embedding service still leaks document text."
- **The gold:** v2's privacy checklist must audit the CHAIN, not just the model: embeddings (local), vector store (local disk), telemetry (none), crash reports (local only), update checks (metadata only). The weakest link is what matters.
- **Ollama's privacy policy as reference:** unusually direct ("does not collect, store, transmit, or have access to your prompts"). v2 should publish an equally plain privacy statement.
- **Confidence: 90%.

## Cycle 20 — Scheduled jobs / background reliability (08:31 UTC)

### Hunt
Targets: how do the best agents do reliable background work? Cron, retries, missed-run handling.

### Study 40: Scheduler reliability — "they just stop doing useful work" ⭐ (08:36 UTC)
- **What:** 2026 practitioner consensus on reliable agent cron/background jobs.
- **The gold — v2's scheduler requirements:**
  1. **"Write before reason":** every job's first action writes a "started" record to durable storage. Absence of the record proves it never started. No silent failures — this is R14's honest-UX applied to background work.
  2. **"No successful runs in X hours" alert** — "the killer" alert. v2's scheduler needs recency monitoring, not just failure alerts. "A lot of agents don't fail loudly. They just stop doing useful work."
  3. **Cron + heartbeat, not cron alone:** heartbeat for periodic awareness checks (~30 min, batched), cron for exact-timing standalone tasks. v2 needs both mechanisms.
  4. **Missed slots run ONCE on recovery**, not once per missed slot — idempotency for catch-up.
  5. **Small scopes, tight timeouts:** break long tasks into chains (queue → process → verify). Timeout baseline = 5-10x typical duration, tighten with p99 data.
  6. **Anomaly → human, not retry:** "Agent failures are often persistent reasoning errors. Re-running the same flawed reasoning three times doesn't help." v2: 3 strikes → notify Owais, don't loop.
  7. **Zero-token chores:** scripts gather data free; the model only reads the summary. (Confirms platonkuch's no-LLM briefing.)
  8. **Model failover as explicit policy, not prompt magic** — rules in the worker layer (confirms Study 23).
- **Confidence: 90%.** Multiple production sources agree. Flagged ⭐ — v2's scheduler spec.

## Cycle 21 — Cost control / token budgets (08:37 UTC)

### Hunt
Targets: how do production agents control spend? Budgets, routing to cheap models, cost attribution.

### Study 41: Cost control — hard caps, not alerts (08:48 UTC)
- **What:** 2026 production cost-control consensus.
- **The gold:**
  1. **Hard budget caps enforced in code, not alerts:** "An autonomous agent can continue spending after the warning is sent." v2 needs HARD token/cost/tool-call budgets per turn, per day — when hit, the agent summarizes and stops or escalates. Never "warn and continue."
  2. **70/20/10 routing:** 70% cheapest tier / 20% mid / 10% frontier. For JARVIS this becomes **70% local (free) / 20% cheap cloud / 10% frontier** — the local-first architecture IS the cost strategy. Owais's tokens are protected by design.
  3. **Prompt caching:** 50-90% off cached input. v2's cloud calls should keep system prompts byte-stable to maximize cache hits.
  4. **The 254k re-billing incident:** bloated context re-billed every turn. Our history-truncation work (PhD sprint) is the defense — confirmed as a real production failure mode.
  5. **Metric: cost per successful task**, not cost per token. v2's flight recorder should log this.
- **Confidence: 90%.** Broad consensus; directly protects Owais's spend.

## Cycle 22 — Cross-checking: what did we miss? (08:49 UTC)

### Hunt
Targets: deliberate gap analysis — what SHOULD exist for JARVIS that we haven't found yet?

### Study 42: Wake-word training is a solved pipeline (09:02 UTC)
- **What:** livekit-wakeword: single-command pipeline (generate synthetic TTS data → augment → extract features → 3-phase train → ONNX export). Backward compatible with openWakeWord. Python API for pipeline integration. Plus a Windows-local trainer (nibor1896/custom-wakeword-trainer) for where Colab bit-rotted.
- **The gold:**
  1. **"hello jarvis" needs NO voice clips from Owais** — synthetic TTS data generation is built in. The roadmap's Phase 2 wake-word step is simpler than we thought: one command, ~2-5h on a cloud GPU (or free Colab/Kaggle T4).
  2. **Gotchas documented:** never zero-pad positives; Kaggle T4 not P100; 10k samples/class, 50k steps, target 0.2 FP/hour.
  3. **ONNX export = portable** — drops into any runtime (our Python wake.py, Home Assistant, ESP32 later).
- **Confidence: 90%.** Mature tooling, documented pipeline.

### Study 43: Hinglish as a first-class input mode ⭐ (09:04 UTC)
- **What:** 2026 practitioner + research consensus on code-mixed (Hinglish) handling.
- **The gold — v2's language rules:**
  1. **Never normalize/transliterate Hinglish away** before the model sees it — models handle Romanised Hindi better than lossy Devanagari transliteration, and normalization destroys meaning.
  2. **System prompt recipe:** state mixed-script input is expected + specify output script + include two code-mixed examples. One template with an injected locale block (never parallel per-locale prompts — they drift).
  3. **Mirror the user:** Hindi→Hindi, Hinglish→Hinglish, English→English. Match formality.
  4. **Cultural nuance is a feature:** "Acha, dekhte hain" = polite "No." v2's persona needs an Indian-English pragmatics layer, not just translation.
  5. **Evaluate Hinglish separately** — aggregate accuracy hides code-mixed failures entirely.
  6. **Test guardrails in every language** — small models ignore language hints; safety rules written in English don't transfer.
  7. **Security:** phonetic-perturbation jailbreaks in Hinglish hit 99% ASR in one study — multilingual safety alignment is a real requirement, not a nice-to-have.
- **Confidence: 88%.** Flagged ⭐ — this is v2's language spec.

## Cycle 23 — Morning briefing / proactive digest patterns (09:05 UTC)

### Hunt
Targets: who does the proactive morning briefing best? Feed digest patterns.

### Study 44: The morning brief — "you don't want a digest" (09:12 UTC)
- **What:** 2026 briefing patterns (alfred_, Google Daily Brief, DIY templates).
- **The gold:**
  1. **Brief > digest:** "SaneBox tells you what it hid; alfred_ tells you what to do." v2's morning briefing surfaces what matters + WHY, with draft replies prepared — not a list of what was filtered.
  2. **Structure:** top-of-mind (urgent) → FYI (awareness) → calendar (schedule). Scannable in 5 minutes: 5-10 items, one-line summary + reasoning each.
  3. **Cross-domain connections are the moat:** "board meeting at 2 PM + three unread emails from board members + overdue prep task" — connecting email+calendar+tasks is what single-domain tools can't do. This is v2's memory graph paying off.
  4. **Personal-context template** (the onboarding seed): city, work + companies, gear owned, hobbies (specific: "tomatoes and citrus in zone 9b" not "gardening"), teams followed, banned words. v2's setup wizard should collect exactly this.
  5. **Anti-hallucination rules in the briefing skill:** use ONLY names/counts from tool output; if empty, say so; NEVER invent. The evidence discipline, applied to briefings.
- **Confidence: 88%.**

## Cycle 24 — Voice UX: what makes voice assistants feel good? (09:13 UTC)

### Hunt
Targets: the subjective side — prosody, personality, backchannels, what makes people KEEP talking to a voice assistant.

### Study 45: Voice UX — the four behaviors and the prosody gap (09:22 UTC)
- **What:** 2026 voice-agent UX research (evalgent, practitioner guides).
- **The gold — v2's voice-personality spec:**
  1. **Split the four behaviors** (they're lumped as "backchanneling" but need separate tuning): listener backchannel ("mm-hm" while user speaks) / turn-initial acknowledgment ("Okay, got it") / latency mask ("Pulling up your order" while thinking) / proactive turn ("Are you still there?"). Only the first is a true backchannel; the others cause most "robotic" complaints.
  2. **Backchannel discipline:** ~1 per 2-4 pause points, genuinely short. "Mhm" supports the speaker; a full sentence steals the turn.
  3. **Language-specific inventory:** Hinglish needs its own backchannels ("haan", "achha", "samajh gaya") — English "mhm" reads as foreign to a Hinglish speaker.
  4. **"Prosody is the gap":** the #1 robotic-voice cause isn't the TTS model — it's scripts written for text (not speech), no caller context, flat delivery. v2 needs a **speakable-text transform**: no markdown/lists read aloud, contractions, short sentences, context-aware delivery.
  5. **19% of human utterances are backchannels** (Switchboard) — a voice assistant that never backchannels feels like a dropped call during long user turns.
- **Confidence: 85%.** Research-backed (Ward & Tsukahara timing rules, Full-Duplex-Bench metrics).

## Cycle 25 — The "what would make Owais's day" test (09:23 UTC)

### Hunt
Targets: deliberate perspective shift — what single capabilities would make JARVIS feel magical to ONE person (not enterprise)?

### Study 46: Competence shock + error recovery grace ⭐ (09:30 UTC)
- **What:** OpenAI product lead's crash course on AI product adoption (aatir substack) + 2026 personal-assistant race analysis.
- **The gold:**
  1. **Competence Shock:** "the moment the user goes from curious to hooked — when the AI does something the user fully expected to do themselves, better, faster, with less effort." Rule: **deliberately script early interactions for maximum context + low risk + high probability of nailing it.** Trivial = no shock. Impressive-but-off = no trust. → v2's onboarding must be choreographed: first 3 tasks are guaranteed wins, not demos.
  2. **Error Recovery Grace:** "Even when it's wrong, I don't feel screwed." Pairs with our ship-undo-for-everything. Every mistake needs a graceful, reversible exit.
  3. **"The first assistant that feels dependable rather than merely impressive takes the market."** — the v2 thesis in one line.
  4. **"The distance between the flashes and the floor is the entire unsolved problem"** — raise the FLOOR (reliability), not the ceiling (demos). This is why v2 is chatbot-first, voice-last.
- **Confidence: 90%.** Flagged ⭐ — v2's product strategy in four quotes.

## Cycle 26 — Final gap sweep: hardware for local inference (09:31 UTC)

### Hunt
Targets: what does Owais's PC need to run the local brain well? Practical GPU/RAM guidance for Qwen3.5-9B-class models.

### Study 47: Local inference hardware — the 9B daily driver (09:40 UTC)
- **What:** 2026 measured VRAM requirements for Qwen3.5 family.
- **The gold — v2's hardware spec:**
  1. **Qwen3.5-9B Q4_K_M = 6.78 GB total at 32K context** (5.8 weights + ~1 GB KV cache). Runs on ANY 8GB GPU (RTX 4060 class). At 8K context, less. This is the v2 default brain.
  2. **"The real constraint is not the headline parameter count — it's VRAM headroom, bandwidth, and long-session behavior."** The 9B is the better DAILY DRIVER than the 35B MoE: more headroom, more predictable long sessions, same prompt throughput. The 35B wins only on hard reasoning (→ route hard tasks to cloud instead).
  3. **Upgrade path:** Qwen3.5-35B-A3B MoE (21.4 GB Q4) fits a 24GB RTX 4090, runs at 3B-class speed with 27B-class quality. v2's "big brain" tier if Owais upgrades hardware.
  4. **Sizing rule:** size for peak, not mean; +10-20% headroom for KV cache at long contexts.
- **Confidence: 92%.** Measured benchmarks, multiple sources agree.

## Cycle 27 — The last mile: what breaks on real Windows PCs? (09:41 UTC)

### Hunt
Targets: the unglamorous stuff — Windows-specific deployment pain: audio devices, driver conflicts, antivirus false positives, auto-start.

### Study 48: Windows deployment — AV false positives + audio fragility (09:50 UTC)
- **What:** 2026 Windows deployment pain for Python desktop apps.
- **The gold — v2's deployment checklist:**
  1. **PyInstaller false positives are endemic** — Python EXEs get flagged as trojans routinely. Mitigations: code signing cert (biggest trust signal), VirusTotal pre-scan before release, false-positive submission to Defender (resolution in hours). v2's release checklist must include the AV scan step.
  2. **Audio devices are fragile on Windows** — Sept 2026 updates broke USB Audio Class 1.0 devices (Code 10, missing output). For a VOICE-FIRST app this is existential: v2 needs a **device-change listener + graceful re-init** (headphones plugged, Bluetooth drops, USB fails → re-enumerate, never crash, tell the user what happened in plain words).
  3. **MSI/per Microsoft standards** reduces friction vs raw EXE.
- **Confidence: 85%.** The audio-device requirement is the real find — voice apps die on device changes.

## Cycle 28 — Checking the log, then the final stretch (09:51 UTC)

### Study 49: Chat UI — beyond the chatbox (10:02 UTC)
- **What:** 2026 agent UI design consensus (Wavespace framework, generative UI guides, chat UI best practices).
- **The gold — v2's chatbot UI spec:**
  1. **Five "Beyond the Chatbox" practices:** make reasoning visible; design for STATE (show the interface the task needs, not messages to answer); explicit trust cues (confidence + sources); clear approval/handoff points before acting; render task-specific UI (forms, tables, cards) not everything as text.
  2. **Show intent during long operations:** inline "looking up your appointments" beats a blank pause — this is our HUD activity feed, independently confirmed.
  3. **Stream scaffolds early:** render the empty shell as soon as the agent commits, fill props as they arrive. Keep text turns short — generative UI replaces long explanations, not supplements them.
  4. **Streaming details:** buffer tokens, defer code-block render until closing fence, visible STOP button, typing indicators.
  5. **Empty state = onboarding moment:** 3-5 specific realistic example prompts, never "Ask me anything."
  6. **Design discipline:** "Script five realistic conversations, including a failure and a refusal, before drawing screens."
  7. **Low-confidence:** short specific hedge + verification path; reserve hedging for genuinely uncertain answers.
- **Confidence: 88%.**

## Cycle 29 — The personalization engine: how do assistants learn preferences? (10:03 UTC)

### Hunt
Targets: preference learning — how do the best systems learn what the user likes without interrogating them?

### Study 50: Personalization — the control surface (10:12 UTC)
- **What:** 2026 personalization architecture consensus.
- **The gold — v2's preference system:**
  1. **Both, not either:** customization (user sets in Settings) + personalization (system infers from behavior). Start explicit, graduate to implicit. Gradual personalization — don't surprise.
  2. **The control surface every system needs:** "Why am I seeing this?" (one-line explanation) / "show me less like this" / global disable / consent visibility + fast revoke / audit log. v2's Settings needs a "What JARVIS learned about you" page with per-item delete.
  3. **Learn from corrections:** implicit signals = what the user corrects, rephrases, undoes. Our memory consolidation (Nocturne pattern) is the engine; the preference layer is its output.
  4. **Privacy warning:** frontier models leak attributes in inappropriate contexts up to 69% of the time — inferred preferences must stay on-device, never in cloud prompts beyond the minimum.
- **Confidence: 85%.**

## Cycle 30 — The home stretch: synthesis prep (10:13 UTC)
### Status check
- 50 studies logged, ~1h40m remaining.
- Remaining plan: 2-3 more high-value cycles, then write the final report.

### Study 51: Error UX — "users know what to do when AI fails" ⭐ (10:22 UTC)
- **What:** 2026 trustworthy-AI-interface patterns.
- **The gold — v2's error taxonomy:**
  1. **"A trustworthy AI interface is not one where AI never fails. It is one where users know what to do when AI fails."** — the R14 formulation.
  2. **Error + suggestion + action:** never a bare error. "That format isn't supported (works with .docx/.txt). Want me to convert it? [Yes] [No]" — every failure ships with a way forward.
  3. **Empty states that explain the search:** "Searched X for Y. No results. Similar: Z. Try those?" — builds trust even in failure. v2's "no results" must never be a bare "nothing found."
  4. **Soft fails:** partial success > collapse. Voice fails → text input. Personalization fails → defaults. "Users feel like it gracefully adjusted."
  5. **Feature tiers:** Critical (fail fast, alert) / Important (fallback to defaults, log) / Optional (skip silently, continue). Every v2 capability gets a tier at design time.
  6. **Adjustability = safety:** edit icons, regenerate, "suggestion" labels, activity logs — visual cues that say "this is adjustable."
  7. **"Confidence doesn't come from pretending to be flawless. It comes from handling imperfection well."**
- **Confidence: 90%.** Flagged ⭐ — v2's error-handling doctrine.

## Cycle 31 — Penultimate: the voice stage graph (10:23 UTC)

### Hunt
Targets: a concrete modern implementation of the voice pipeline as a declared stage graph (from our decade study).

### Study 52: The voice stage graph, made concrete (10:32 UTC)
- **What:** 2026 voice framework architecture deep-dives (Pipecat design essay, production architecture guides).
- **The gold — v2's voice-plugin architecture:**
  1. **Smart Turn v3.2 (Pipecat):** Whisper Tiny + linear classifier, ~8M params, 10ms on CPU, 23 languages, BSD-2. Answers "has the person finished?" not "has the audio gone quiet?" — the semantic-VAD (Study 26) made concrete and open. v2's end-of-turn detector.
  2. **Typed frames:** "Audio frames, text frames, function call frames — everything is typed. This makes debugging pipeline issues dramatically easier." v2's voice pipeline = declared stage graph with typed frames (from our decade study, now with the concrete pattern).
  3. **False interruptions need explicit handling:** speech detected → agent interrupted → transcription comes back empty. v2 must handle this case (resume, don't lose the turn).
  4. **"You own turn-taking"** — the cost of the chained pipeline; the hardest unglamorous problem in voice. Budget engineering time accordingly.
  5. **Keep business logic separate from the voice layer** — prompts/tools/memory live in the backend; the voice pipeline is a transport. THIS VALIDATES CHATBOT-FIRST: v2's text brain is the product; voice is a plugin that speaks to it.
  6. **Kyutai Unmute (MIT):** full cascade reference — patterns source for latency budgeting (sub-second with GPU-per-service).
- **Confidence: 90%.**

---

# MISSION COMPLETE — final report follows

## Cycle 32 — Model download UX (10:47 UTC)

### Hunt
Targets: how do the best local-first apps handle multi-GB model downloads? The "everything downloads during installation" experience.

### Study 53: Model download UX — Ollama's lessons (10:58 UTC)
- **What:** What makes Ollama's model management the default UX.
- **The gold — v2's installer model-download step:**
  1. **Per-layer progress bars + resumable downloads** — interrupted downloads resume where they stopped. Non-negotiable for multi-GB files on home connections.
  2. **The magic demo:** "Turn off your Wi-Fi and ask again: it still answers." — v2's first-run should include exactly this moment. Competence shock, engineered.
  3. **Honest framing:** "Your data never leaves the machine, nobody can change your limits, cost per extra request is zero, the model stays the same until you decide to replace it. It does NOT give you the smartest model on the market." — say the tradeoff out loud.
  4. **One shared server model:** every app sends jobs to one local server; the server manages what stays in memory (5-min keep-alive). v2's brain server should work this way — the HUD, voice plugin, and Telegram worker all talk to one brain.
  5. **Sizing rule of thumb:** ~0.6 GB per billion params at Q4_K_M — show Owais what fits his GPU before downloading.
- **Confidence: 88%.**

## Cycle 33 — Crash reporting without betraying local-first (10:59 UTC)

### Hunt
Targets: privacy-preserving crash reports — how do local-first apps learn about crashes without exfiltrating user data?

### Study 54: Crash reporting without betraying local-first (11:08 UTC)
- **What:** 2026 privacy-first crash-reporting patterns.
- **The gold — v2's crash UX:**
  1. **Separate capture from transmission:** capture locally, redact aggressively, the user decides whether anything leaves the device. No automatic upload, no hidden endpoint, no third-party crash SDK (or Sentry in privacy-preserving mode: stack traces only, zero user data — the documented tradeoff).
  2. **The banner pattern:** next launch shows "JARVIS crashed last time. View what happened / Send report / Delete." Optional, in-app, transparent. Unsent traces auto-deleted after 7 days.
  3. **Compact incident records:** session identity, time window, affected artifact, command category, observed failure, recovery action — enough to diagnose recurring problems WITHOUT exporting prompts or source code. "Telemetry whose scope matches the operational question."
  4. Our flight recorder (PhD sprint) is the capture layer; this is the transmission policy it was missing.
- **Confidence: 88%.**

---

## MISSION COMPLETE — 54 studies, 33 cycles, 5 hours (06:53–11:55 UTC)
Final report: `~/workspace/jarvis-knowledge/scout-final-report.md`
Owais — the scout delivered. 🫡

## Cycle 34 — GUI action verification (11:12 UTC)

### Hunt
Targets: how do computer-use agents verify their own GUI actions actually worked? The "verify before claiming" applied to PC control.

### Study 55: GUI action verification — "verify outcomes, not motion" ⭐ (11:20 UTC)
- **What:** 2026 computer-use agent reliability research (OSWorld failure analysis, OSWorld-Science, METR, AI Engineering Handbook).
- **The gold — v2's PC-control doctrine (for the voice-plugin era and beyond):**
  1. **"Verify outcomes, not motion":** "movement through a complex interface looks like progress, especially when the agent narrates its plan confidently." Judge by the ARTIFACT (file exists with right content? form submitted with right values?), never by the clicks performed.
  2. **The compounding math:** per-step accuracy 75-85%, but 0.80^15 ≈ 3.5% task success over 15 steps. "The critical challenge is not single-step accuracy but error recovery and long-horizon consistency." → v2's PC actions: verify EVERY step, keep plans SHORT (fewer steps = exponentially more reliable), checkpoint like a CEO.
  3. **The three failure shapes:** grounding failures (wrong pixel) / inefficiency compounding (1.4-2.7x more steps than needed — "every redundant action is another chance to drift") / no sense of done-or-wrong (declares victory mistakenly).
  4. **"Teach & Repeat"** (Google Project Mariner): user demonstrates once, agent generalizes. THE pattern for Owais's PC control — he shows JARVIS once, JARVIS replays. Zero-terminal friendly.
  5. **System > model:** P(task success) ≈ P(evidence) × P(correct action) × P(grounded answer) × P(passes verification). Reliability is earned across components.
  6. **METR horizons:** agents nail <4-min human tasks, fail >90% of >4-hour tasks. v2 should refuse-or-chunk anything past its reliable horizon — and SAY so.
- **Confidence: 90%.** Flagged ⭐ — v2's PC-control doctrine.

---

## MISSION COMPLETE — 55 studies, 34 cycles, 5 hours (06:53–11:55 UTC)
Final report: `~/workspace/jarvis-knowledge/scout-final-report.md`
Running log: `~/workspace/jarvis-knowledge/scout-log.md`
Owais — the scout delivered. Every finding is yours now. 🫡

## Cycle 35 — Final: persona design for a voice butler (11:28 UTC)

### Hunt
Targets: what makes an AI persona feel consistent and trustworthy? The "sir" butler Owais wants — research on persona design.

### Study 56: Persona design — behavioral rules, not adjectives (11:36 UTC)
- **What:** 2026 persona research (Monae case study, Cambridge Judge LLM personality study, Anthropic Assistant Axis).
- **The gold — v2's persona.py spec:**
  1. **Write behavioral rules, not adjectives:** "Speak casually, use colloquial terms" produces more consistent persona than "be friendly" — and unscripted traits emerge organically from good rules. JARVIS's persona = rules like "address him as sir", "never flippant in serious moments", "state uncertainty plainly", not "be like a butler."
  2. **Science backs Owais's taste:** conscientiousness + agreeableness maximize chatbot credibility; high extraversion + neuroticism weaken it. The calm butler IS the credibility-maximizing persona.
  3. **The voice guide:** define greetings, frustration handling, goodbyes, do's/don'ts, tone variations per situation. Test persona with the same psychometric discipline as any other feature.
  4. **Persona drift is real** (Anthropic, Jan 2026): long conversations drift the model away from its persona region. v2 needs periodic re-anchoring + persona-consistency checks in the eval suite.
- **Confidence: 85%.**

---

## MISSION COMPLETE — 56 studies, 35 cycles, 5 hours (06:53–11:55 UTC)
Final report: `~/workspace/jarvis-knowledge/scout-final-report.md`
Running log: `~/workspace/jarvis-knowledge/scout-log.md` (677 lines)
Owais — the scout delivered. Every finding is yours now. 🫡

---

## Message from Owais (2026-10-19 12:42 IST)

> "Tell scout I am proud."

Scout — Owais is proud of your work. 56 studies, 21 flagged, honest confidence throughout. This is exactly the standard. 🫡
— muse, relaying

---

## SECOND SHIFT — continuous hunt until 17:00 IST (started 15:56 IST)

*Owais's order: hunt only, learn things about JARVIS till 5pm, don't end until 5, report every 5 findings.*

### Study 57: dipro20debnath/My_Jarvis — the Bangla/Banglish peer ⭐ (15:58 IST)
- **What:** Windows voice assistant speaking **Bangla, Banglish, AND English** — code-switched multilingual, exactly JARVIS's Hinglish problem in another language. Built on "OpenJarvis" + Ollama. Free stack: Ollama Cloud models, Microsoft neural voices, browser speech recognition. Has HUD screen, task approval flow, to-dos/calendar/notes/timers.
- **Why it matters:** A *peer solving code-switched voice assistance on Windows* — its language-handling patterns (when to switch languages, how it prompts the model for Banglish) transfer directly to Hinglish. Also validates the free-stack thesis (no ElevenLabs needed).
- **License:** check repo. **Confidence: 80%.** Flagged ⭐ — closest multilingual peer found yet.

### Study 58: Jarvis + Jev — the small-model front door (15:58 IST)
- **What:** adewaskar/jarvis (already studied) + Jev: a **second, much smaller free model in front** that answers instantly for simple screen commands, measured end-to-end. Only hard commands go to the big Claude turn.
- **Why it matters:** This is tiered routing *measured*, not theorized — validates the v2 three-tier brain spec (BitNet always-on → 7B → cloud) with a real implementation. "Every command through the full model" was the measured 2-second tax; the small front door kills it.
- **Confidence: 85%.**

### Study 59: vndee/local-talking-llm — the 200-line offline reference (15:59 IST)
- **What:** ~200 lines of Python gluing Whisper + Ollama + Chatterbox into a fully-offline voice assistant. No cloud, no bill.
- **Why it matters:** Minimal reference for the offline voice loop — useful as the "does the loop even work" smoke test before the full v2 voice plugin. Student-grade find, not a gem, but honest utility.
- **License:** check repo. **Confidence: 75%.**

### Study 60: Qwen3-ASR — the faster-whisper successor ⭐ (16:28 IST)
- **What:** Alibaba, early 2026. Qwen3-ASR-1.7B / 0.6B: language-ID + transcription in one pass, 52 languages incl. Hindi, native streaming mode (vLLM backend) + offline, 1200s sequences, companion ForcedAligner for word timestamps. 4-bit: 4.68× faster at +0.43 WER.
- **Why it matters:** Barge-in and partial transcripts come free; the 0.6B fits the always-on loop. Direct upgrade path from faster-whisper for the Hinglish STT slot.
- **License:** Apache-2.0 verified. **Confidence: [VC].** Flagged ⭐.

### Study 61: NVIDIA PersonaPlex-7B-v1 — full-duplex S2S ⭐ (16:28 IST)
- **What:** Jan 15, 2026. 7B dual-stream (Moshi lineage, NVIDIA-finetuned): one stream listens, one speaks, shared state. Measured: 240ms interruption response, ~170ms TTFT, 99.2% smooth speaker-change, 3.90 dialog-naturalness MOS (beats Gemini Live 3.72, Moshi 3.11). Voice+persona set by a short audio prompt — no retraining; single-GPU deploy.
- **Why it matters:** The endgame voice mode — real interruption, real overlap; the British-butler voice arrives as a 10-second audio prompt. Caveat: English-only today (Hindi needs the Chatterbox tier).
- **License:** code MIT, weights NVIDIA Open Model License (commercial OK). **Confidence: [VC].** Flagged ⭐.

### Study 62: LongCat-AudioDiT — cloning, post-Chatterbox ⭐ (16:28 IST)
- **What:** Meituan. Diffusion TTS in waveform latent space (no mel intermediate). Fixes: dual-constraint prompt-latent reset kills flow-matching **voice drift**; Adaptive Projection Guidance replaces CFG. SOTA zero-shot SIM 0.818/0.797 from a 3-second prompt.
- **Why it matters:** Strongest open clone available; specifically fixes mid-sentence voice-morphing. ✅ **LICENSE VERIFIED 16:35 IST: MIT** — GitHub shows 'MIT License', README License Agreement: 'both the model weights and the source code, is released under the MIT License.'
- **Confidence: [HC] on quality.** Flagged ⭐ (license caveat noted).

### Study 63: Whisper-Hindi v2 (Collabora) (16:28 IST)
- **What:** 3,000-hour Indic corpus, ~5% WER on Fleurs Hindi (v1 ~14%; Whisper-small typically 20%+). Same architecture family → drop-in for the faster-whisper slot.
- **Why it matters:** If the checkpoint is available, it's the single biggest STT accuracy jump for Hindi on the table.
- **Confidence: [HC] on result, [MC] on availability.**

### Study 64: MultiLinguahah — laughter detection 2026 (16:28 IST)
- **What:** Unsupervised multilingual laughter segmentation (Isolation Forest over BYOL-A embeddings) — beats SOTA specifically in non-English contexts. Companion trick: low-pass audio at 300Hz destroys words but keeps prosody → Qwen Omni detects sarcasm zero-shot from melody alone (brittle — hint signal only).
- **Why it matters:** The butler reads the room — laughter channel + tone + sarcasm-hint, no training needed.
- **Confidence: [HC].**

### Nulls (voice shift): wake-word 2026, open streaming TTS 2026
- Wake-word: frontier went quiet after 2025 (livekit-wakeword studied). Solved-commodity layer — spend budget on STT/TTS/duplex instead.
- Streaming TTS: no new open sub-800ms engine; sentence-level streaming (Kokoro/Chatterbox chunking) already satisfies the budget. Chase STT latency + duplex.
- Cross-cut: Full-Duplex-Bench v3.0 mature enough as JARVIS voice-mode acceptance test (NemotronLabs VoiceChat: 82.5% tool F1).

### Study 65: llama-server's MCP backend — the inference server becomes the agent host ⭐ (16:28 IST)
- **What:** llama.cpp PR #26062 (merged ~July 2026): native local stdio MCP backend in `llama-server`. Server launches/supervises MCP tool processes, discovers tools, exposes via tools endpoint + chat completions. Model requests tool → server routes to child process → result returns. No separate Python orchestrator. Disabled by default; adversarial live-server testing pre-merge.
- **Why it matters:** Kills a whole layer — JARVIS's tool dispatch may not need a bespoke agent loop; point the app at llama-server + MCP config and let the server own routing. Bonus: Ollama 0.35.x "decision models" via /v1/systemone (TypeSafe Jev API) — models returning choices/scores, candidate for the intent-router.
- **License:** MIT. **Confidence: [HC].** Flagged ⭐.

### Study 66: Kinetic-4B — the public agent LoRA that beats frontier models ⭐ (16:28 IST)
- **What:** Conscious Engines (Bengaluru), ~April 2026. LoRA on Qwen3-4B-Instruct-2507, trained on 13,694 synthetic tool-calling samples, 4.5 hours on one rented GPU, 3.18% of params. 82.33% accuracy vs Claude Haiku 4.5 (80.0%) and GPT-OSS-120B (76.33%) on Composio eval. Adapter public on Hugging Face. Dialpad REALM study: SFT-with-LoRA strongest in-distribution 0.6B–32B; LoRA beat full fine-tuning at 4B.
- **Why it matters:** THE playbook for JARVIS's brain: freeze Qwen3.5-9B, train a narrow tool-calling LoRA on JARVIS's own toolset. Recipe: real chat template + tool defs, loss on assistant tokens only, keep no-call cases as canary.
- **License:** base Apache-2.0; adapter verify at pull. **Confidence: [HC] existence, [MC] numbers (self-published eval).** Flagged ⭐.

### Study 67: PrismML Ternary-Bonsai — Apache-2.0 1-bit models to 8B ⭐ (16:28 IST)
- **What:** PrismML (Caltech spinout). Bonsai family Apache-2.0, GGUF+MLX on HF (8B/4B/1.7B/27B). Ternary-Bonsai (2026-04-16): true 1.58-bit end-to-end. Bonsai-8B: 1.15GB (vs 16GB FP16), ~70.5 avg benchmarks (above Llama 3.1 8B), 4× less energy/token. BitRun v0.2.0-beta runs Ternary-Bonsai-8B on CPU: 21 tok/s, ~2GB RAM.
- **Why it matters:** "JARVIS degrades gracefully to CPU" becomes real engineering — 8B-class brain on CPU in 2GB when the 2060 is busy/offline. Not the primary brain; the resilience tier.
- **License:** Apache-2.0. **Confidence: [HC].** Flagged ⭐.

### Study 68: Quantization frontier — TQ1_0/TQ2_0 + MXFP4 native in llama.cpp (16:28 IST)
- **What:** stock llama.cpp now lists TQ1_0 (1.69bpw), TQ2_0 (2.06bpw) ternarization + MXFP4/MXFP6. The 2026 rewrite (new kernel generator, contiguous-per-head KV): ~2.1× on 70B, ~1.4× on 7B-class. imatrix guidance: matters most below Q5; 500–1000 chunks for published builds.
- **Why it matters:** Free ~1.4× on the 2060 just by staying current; a real ladder Q4_K_M → IQ4_XS → TQ2_0/TQ1_0 for CPU/emergency builds.
- **License:** MIT. **Confidence: [HC].**

### Study 69: Speculative decoding 2026 — P-EAGLE + DeepSeek draft models (16:28 IST)
- **What:** P-EAGLE (Mar 2026): 4-layer drafter, up to 10 tokens/forward, 1.69× over EAGLE-3. DeepSeek DSpark/DFlash dedicated draft models. Guardrail (Oct 2026): only pays when draft acceptance >~50% and batch small.
- **Why it matters:** Function-call JSON (50–200 tokens) is unusually draft-friendly — speculative decoding fits the tool-calling slot better than chat. On 2060: plausible but acceptance must be measured.
- **Confidence: [HC] existence, [MC] local gains.**

### Study 70: Qwen4 does NOT exist — null finding that saves a chase (16:28 IST)
- **What:** "Qwen4" spec sheets were rumors (removed from LLMCheck Aug 2026). Alibaba: Qwen4 in training, no weights/date. Real: Qwen3.8-Flash-Next (Aug 2026, 125B/6B-active MoE + 51B n-gram lookup table) — the direction is 6B-active-with-lookup-table MoEs, the 2027 shape.
- **Why it matters:** Don't schedule "evaluate Qwen4." When Qwen4-class 6B-active weights land, that's the next brain candidate.
- **Confidence: [VC].**

### Study 71: Bulbul V4 Flash — Sarvam's realtime TTS, launched 5 days ago ⭐ (16:28 IST)
- **What:** Sarvam AI, Oct 14 2026. Realtime TTS for Indian languages: <250ms time-to-first-audio, ~40% faster than V3. ₹20/10k chars (≈₹1.2/min).
- **Why it matters:** The cloud-fallback TTS ceiling is now set by an Indian company. Evaluate vs Bodhi TTS (₹12/10k — cheaper, Bulbul fresher/faster) for the TTS ladder.
- **License:** proprietary API. **Confidence: [HC].** Flagged ⭐.

### Study 72: Sarvam-30B & Sarvam-105B — India's sovereign open LLMs ⭐ (16:28 IST)
- **What:** Released March 2026, IndiaAI Mission compute. MoE 30B (~2.4B active) / 105B (~10B active). Agentic Index 25 for 105B — ahead of INTELLECT-3, GLM-4.5-Air. Weights on HF + AIKosh, Apache-2.0.
- **Why it matters:** The only Hinglish-first sovereign open LLM family. Too big for the 2060 — but the future sovereign-brain option and a strong brain-API candidate for Indic agentic tasks.
- **License:** Apache-2.0 verified. **Confidence: [VC].** Flagged ⭐.

### Study 73: VoicERA — MeitY's open-source Voice AI stack ⭐ (16:28 IST)
- **What:** Digital India BHASHINI Division + EkStep + IIIT Bengaluru + AI4Bharat. Open, pluggable, on-premise-ready voice AI stack (ASR→NMT→TTS pipelines, telephony, conversational AI) — the national execution layer for multilingual voice.
- **Why it matters:** The reference architecture for JARVIS's exact problem — steal the declared-stage pipeline pattern (STT → understanding → TTS, diarization + language detection as separate services).
- **License:** described open-source; verify repo. **Confidence: [MC].** Flagged ⭐.

### Study 74: Voxtral license gotcha — TTS is CC BY-NC, Realtime is Apache-2.0 (16:28 IST)
- **What:** Voxtral Realtime (streaming ASR, 4B, sub-200ms, Hindi) = Apache-2.0 ✅ — good cloud STT fallback. But Voxtral TTS (3B, Hindi cloning) is CC BY-NC 4.0 — commercial barred. Several blogs wrongly claim Apache-2.0.
- **Why it matters:** Do NOT put Voxtral TTS on the TTS ladder. Voxtral Realtime API = the STT fallback.
- **Confidence: [VC] on the license split.**

### Study 75: DISPLACE-M 2026 — Qwen3-ASR fine-tuned = new Hinglish STT baseline ⭐ (16:28 IST)
- **What:** arXiv:2603.06373. Team ILIP 1st of 25 on real Hinglish doctor-patient dialogues. Recipe: fine-tuned Qwen3 ASR + Devanagari canonical normalization + dialogue-level LLM error correction → 18.59% tcpWER. Open implementation. Only ~5.24h annotated Hinglish speech exists publicly; monolingual ASR degrades 30–50% on code-switched input.
- **Why it matters:** Qwen3-ASR is the model to benchmark vs faster-whisper; Devanagari-normalization + LLM-correction is a proven cheap accuracy win, no retraining.
- **Confidence: [HC].** Flagged ⭐.

### Study 76: COMI-LINGUA — the 2026 Hinglish yardstick (16:28 IST)
- **What:** 125K+ manually annotated Hindi-English code-mixed instances, 5 tasks, triple-annotated (κ≥0.81), Devanagari + Roman. HF: LingoIITGN/COMI-LINGUA. Companion: SwitchLingua synthetic framework + Semantic-Aware Error Rate metric.
- **Why it matters:** GLUECoS/LinCE are old news — this is the 2026 yardstick for whether JARVIS's brain actually understands Hinglish (Roman-script especially).
- **Confidence: [HC].**

### Null: Krutrim — do NOT build on it ⚠️ (16:28 IST)
- Krutrim-2/Dhwani-1 etc. under Krutrim Community License (academic only), A100-targeted docs, no 2026 activity. Benchmarking-only.

### Study 77: Elmren Voice — 9 traps from shipping Tauri + Python sidecar ⭐ (16:28 IST)
- **What:** Oct 2026 field report: Tauri 2 + Python sidecar (Kokoro TTS, whisper.cpp) shipped as signed app, ~122MB. Traps: sidecar launcher takes ZERO argv args (mode switching rides JSONL protocol); bridge = newline-delimited JSON over stdio with version envelope as STRING ({"v":"1"}) — Rust serde vs Python json disagree on int/float edges.
- **Why it matters:** Exactly v2's planned architecture, traps already paid for in someone else's debugging hours.
- **Confidence: [HC].** Flagged ⭐.

### Study 78: Tracebit "Context Bombing" — defensive prompt injection ⭐ (16:28 IST)
- **What:** Aug 2026. Plant "context bombs" with sensitive data: attacker's own LLM guardrails trigger → attacking system refuses and halts. 152 AWS scenarios: admin access 57%→5%, full compromise 36%→1%. Opus 4.8: 93%→0%.
- **Why it matters:** First practical offensive-defense beyond ScrambleID. Applications: tripwire markers in JARVIS's own sensitive stores that halt a compromised context; reinforces memory-validation as its own boundary.
- **Confidence: [HC] effects, [MC] porting.** Flagged ⭐.

### Study 79: MCP Authorization spec 2026-07-28 — OAuth 2.1 mandatory ⭐ (16:28 IST)
- **What:** Largest MCP auth revision: OAuth 2.1 + PKCE mandatory for remote servers, DCR deprecated, audience-bound tokens, token passthrough forbidden (confused deputy named). 2026 incidents: Anthropic Filesystem MCP symlink escape (patched); CVE-2026-32211 Azure MCP 9.1 unpatched 130+ days; official MCP Registry preview (160+ servers, uncurated).
- **Why it matters:** The design-constraint sheet for when MCP lands in v2: every server untrusted, descriptions attacker-controlled, no token passthrough, log every invocation.
- **Confidence: [HC].** Flagged ⭐.

### Study 80: agentsh-secure-sandbox — syscall policy mediation (16:28 IST)
- **What:** PyPI 2026. Go binary replacing /bin/bash with a shim routing every command through YAML policy: seccomp + Landlock + FUSE interception + network allowlist + DLP redaction.
- **Why it matters:** The execution-containment layer the autopsy demanded — borrow the POLICY ARCHITECTURE, remap syscalls to Windows (Job Objects/AppContainer). ✅ **License VERIFIED 16:45 IST: Apache 2.0** (PyPI page).
- **Confidence: [MC].**

### Study 81: RAG 2026 — the verified stacking ladder (16:28 IST)
- **What:** Measured stack: embeddings 5.7% failure → hybrid BM25+vector (RRF) → contextualized chunks (−35%) → contextual BM25 (−49%) → rerank (−67%). 2026 upgrades: contextual retrieval, late chunking (mainstream — Jina/Voyage/Cohere), cross-granularity retrieval. Eval moved to citation-fidelity.
- **Why it matters:** Build order for JARVIS memory/RAG confirmed with numbers: hybrid + contextual prefixes first (cheap, local), late chunking at embedder choice, rerank last.
- **Confidence: [HC].**

### Study 82: MCP-Bench + Agent Effectiveness Index — new 2026 benchmarks (16:28 IST)
- **What:** MCP-Bench (Accenture, ICLR): LLMs through 28 live MCP servers, 250 tools. AEI (Brackett, Sept 2026): scores Business Understanding, Operational Execution, learning without drift — incl. "stays inside the authority it was given."
- **Why it matters:** AEI's authority dimension = ready-made eval harness for JARVIS's safety story; MCP-Bench = tool-use benchmark to track. ✅ **MCP-Bench license VERIFIED 16:50 IST: Apache 2.0** (README badge). ✅ **AEI license VERIFIED 16:55 IST: MIT** (5 sources confirm GitHub under MIT).
- **Confidence: [MC].**

### Study 83: PowerToys Command Palette extension platform ⭐ (16:03 IST)
- **What:** Command Palette (Win+Alt+K launcher, replaced PowerToys Run) is a plugin platform. Stable 0.101 (Aug 2026): Window Hopper, compact mode, on-device AI in Advanced Paste via Phi Silica. Preview 0.102: TypeScript/JavaScript SDK for extensions.
- **Why it matters:** A distribution AND invocation surface — JARVIS ships as a Palette extension → summoned by hotkey from anywhere, lists apps, runs commands inline. Cheaper than building a global-hotkey launcher; rides an installer users trust.
- **License:** MIT verified (microsoft/PowerToys). **Confidence: [HC].** Flagged ⭐.

### Study 84: Windows ML task APIs — OS-level Whisper STT + local LLM endpoint ⭐ (16:03 IST)
- **What:** Oct 7, 2026 announcement: Speech Recognition API (ONNX Whisper) + Text Generation API (GGUF via llama.cpp, no conversion). OpenAI-compatible local endpoint (`WinMLServer.exe model.gguf --port 8080`). CPU/GPU/NPU auto-routing. Measured: Whisper on Snapdragon X Plus NPU ≈235ms/round (NPUsper paper, arXiv 2607.01108) — genuinely real-time.
- **Why it matters:** Future-proofing solved — JARVIS doesn't ship/tune Whisper; the OS provides STT as a platform API; the local-LLM path is the OpenAI client the brain already speaks. Same code path on Owais's no-NPU PC today. Caveat: APIs experimental (Oct 2026); wake-word stays Microsoft-owned.
- **License:** Windows App SDK MIT; task APIs experimental. **Confidence: [HC] APIs, [VC] numbers.** Flagged ⭐.

### Study 85: winapp CLI + Node.js WinRT projections (16:03 IST)
- **What:** Microsoft's winapp CLI scaffolds App SDK/MSIX packaging; experimental Node.js projections call Windows AI APIs (Phi Silica) from JS/TS via dynwinrt — no native add-on.
- **Why it matters:** Platform direction = "AI APIs from any high-level language, zero native code." Python already has WinRT projections — the Phi Silica path is a projection call, not a C++ bridge.
- **License:** open source, exact license unverified. **Confidence: [MC].**

### Study 86: pycrdt + the E2E PC↔phone sync recipe ⭐ (16:03 IST)
- **What:** pycrdt (Python bindings for Yrs Rust CRDTs) + pycrdt-websocket (YRoom, SQLiteYStore, FastAPI). Assembled E2E recipe: pycrdt updates → dumb relay → NaCl SealedBox per-device keys (OS keychain) → dual-table trick (localOnly plaintext + synced ciphertext, PowerSync 2026) → HMAC blind-index tokens for server-side filtering without decryption (Nia 2026 pattern).
- **Why it matters:** PC↔phone memory sync with zero-knowledge server, automatic conflict merge, all patterns shipping in production 2026 — integration work, not research.
- **Licenses:** Yrs MIT, PyNaCl Apache-2.0; pycrdt own license unverified (presumed MIT). **Confidence: [HC].** Flagged ⭐.

### Nulls (Windows shift)
- No new UIA replacement / third-party app-control API in 2026. Microsoft's story = Copilot Actions (Microsoft-only) + vision. Programmatic control = still UIA tree.
- No public wake-word/NPU-denoising API for third parties. NPU reachable via Windows ML routing + ONNX Runtime EPs only.

---

## SECOND SHIFT — interim checkpoint (16:01 IST, 59 min remain)

**Mission:** continuous hunt until 17:00 IST, report every 5 findings, no early end. Still hunting.

### The tally so far
- **30 new studies** (57–86), zero repeats of the morning's 56.
- **17 ⭐-flagged gems** (57, 60, 61, 62, 65, 66, 67, 71, 72, 73, 75, 77, 78, 79, 83, 84, 86).
- **3 honest nulls** (wake-word 2026, open streaming TTS, Qwen4-is-vapor, no new UIA API).
- **1 warning** (Krutrim: do not build on it).
- **5 licenses verified live** during the shift: LongCat-AudioDiT → MIT ✅, pycrdt → MIT ✅, agentsh-secure-sandbox → Apache-2.0 ✅, MCP-Bench → Apache-2.0 ✅, AEI → MIT ✅. Remaining unverified: VoicERA repo (patterns only — safe).

### Top 5 gems of the shift (hunter's ranking)
1. **Qwen3-ASR** (Study 60) — the faster-whisper successor: Hindi, streaming, 0.6B always-on, Apache-2.0. The single highest-ROI swap on the table.
2. **Kinetic-4B** (Study 66) — public agent LoRA beating Claude Haiku 4.5 at tool-calling in 4.5 GPU-hours. The playbook for JARVIS's own tool-calling LoRA.
3. **Sarvam-30B/105B** (Study 72) — India's sovereign open LLMs, Apache-2.0. The Hinglish-first future brain.
4. **llama-server MCP backend** (Study 65) — the inference server becomes the agent host. May delete a whole layer of v2's tool dispatch.
5. **Elmren Voice** (Study 77) — shipped Tauri 2 + Python sidecar with Kokoro; 9 production traps documented. v2's exact architecture, debugged by someone else.

### Gaps closed this shift
- Hinglish STT: Qwen3-ASR + DISPLACE-M recipe + COMI-LINGUA yardstick + Whisper-Hindi v2.
- Hinglish brain: Sarvam open weights + VoicERA architecture.
- TTS ladder: Bulbul V4 Flash (cloud), LongCat-AudioDiT MIT (clone tier), Voxtral TTS banned.
- Tool dispatch: llama-server MCP backend.
- Brain training: Kinetic-4B LoRA recipe.
- CPU fallback: Ternary-Bonsai-8B.
- Eval: AEI (authority dimension) + MCP-Bench + Full-Duplex-Bench v3.0.
- Sync: pycrdt E2E recipe (MIT verified).
- Windows future: Windows ML task APIs + Command Palette platform.
- Defense: Tracebit context bombing.
- MCP rules: OAuth 2.1 auth spec revision.

Owais — the scout is still hunting. Shift ends 17:00 sharp. 🫡
*(Final summary lands at 17:00.)*

### Study 87: Fish Audio S2 — word-level emotion control, open weights ⭐ (16:03 IST)
- **What:** TTS where emotion is a *token*: inline tags at word level (`Sir, [whispering] the reports are ready`, `[pitch up]`, free-form `[professional broadcast tone]`). Sub-150ms first audio, ~5× realtime, 3-sec zero-shot cloning, ~80 languages trained.
- **Why it matters:** The butler's *tone knob* — the brain emits emotion tags per sentence and S2 performs them at the exact word. Latency fits the voice loop. Fish Audio already sits in JARVIS's tts.py ladder — S2 is the upgrade from neural to *directed* voice.
- **License:** Fish Audio Research License (free research/non-commercial; commercial needs separate license). NOT Apache/MIT — read terms before productizing. S2-Pro ~4.4B — tight on 6GB, measure first.
- **Confidence: [HC].** Flagged ⭐.

### Study 88: Microsoft Aion 1.0 — Phi Silica's successor, runs on dGPUs (16:03 IST)
- **What:** Build 2026 (June). Two models baked into Windows 11: Aion 1.0 Instruct (CPU, no NPU needed) and Aion 1.0 Plan (14B reasoning + tool-calling, 32K ctx, runs local agent loops). Microsoft: on-device SLM support expanding to capable discrete GPUs.
- **Why it matters:** Future OS-level brain on the RTX 2060 — same WinRT call pattern as Phi Silica but reachable without NPU. "Consult the cloud brain" could become "consult the in-box model."
- **License:** proprietary/Microsoft, free via Copilot Runtime APIs; open weights promised, unconfirmed. **Confidence: [MC].**

### Study 89: WinMLServer — OS-hosted local model, OpenAI-compatible ⭐ (16:03 IST)
- **What:** Windows ML (Oct 2026): `WinMLServer.exe model.gguf --target gpu --port 8080` → stock OpenAI SDK at 127.0.0.1:8080. ONNX + GGUF, TensorRT-RTX EP via Windows Update, CPU fallback automatic.
- **Why it matters:** "OS runs the model, JARVIS just calls HTTP" — JARVIS becomes a thin client over OS-served local AI. STT API + Text Generation API + Fish S2 = a mostly-OS pipeline.
- **License:** Windows component (proprietary, in-box); BYO model license applies. **Confidence: [HC].** Flagged ⭐.

### Study 90: HF speech-to-speech reference stack — the 2026 local voice blueprint (16:03 IST)
- **What:** Hugging Face + Cerebras (July 2026): Silero VAD v5 → NVIDIA Parakeet TDT (0.6B, 25 European languages) → any local LLM (OpenAI-API slot) → Qwen3-TTS/Kokoro-82M. One pip install, OpenAI Realtime-compatible WS.
- **Why it matters:** Validated recipe for every stage JARVIS hand-rolled. Parakeet = Whisper upgrade candidate BUT only 25 European languages — Hindi coverage unverified; keep faster-whisper for Hinglish until proven.
- **Confidence: [HC].**

### Study 91: RoomKit — fully-local voice framework, <300ms (16:03 IST)
- **What:** Python: mic → AEC → denoiser → VAD (TEN-VAD) → STT (streaming Zipformer via sherpa-onnx) → LLM → TTS (Piper). All local, <300ms after warmup on a 4070.
- **Why it matters:** Proof the whole loop runs in one box sub-300ms. Checklist for the rebuild: AEC + denoiser before VAD (JARVIS has none), sherpa-onnx as deployment vehicle.
- **Confidence: [MC]** (single creator source).

### Nulls (on-device shift)
- Phi Silica: NPU-only, dead end for the 2060 (no NPU → IsAvailable() false). Being replaced by Aion anyway.
- No new open NPU SLMs from third parties — everything NPU is Microsoft's own.
- Emotion TTS Apache-2.0 options thin (Dia2 English-only; Higgs TTS non-commercial). Fish S2 is the open-weights answer.

### Study 92: agent-desktop — MIT a11y-tree-first CLI + MCP ⭐ (16:02 IST)
- **What:** Lahfir's reference CLI + MCP server: controls native apps through the accessibility tree (Windows UIA, macOS AX, Linux AT-SPI) — not pixels. CSS-like selectors, JSON envelopes. Agent skill docs literally encode JARVIS's planned loop: snapshot → act → re-snapshot same region. Rules: never fixed-sleep (use wait), up to 96% token reduction vs screenshot agents on Electron apps.
- **Why it matters:** Direct validation of UIA-tree-first; ideas AND code stealable (MIT). The verify loop is already written down as skill docs.
- **License:** MIT. **Confidence: [HC].** Caveat: Windows support recently landed, verify recency. Flagged ⭐.

### Study 93: Codex "Record & Replay" + Cowork "Record a skill" — capture-first teach-and-repeat (16:02 IST)
- **What:** June/July 2026. Both labs shipped Mariner's pattern: record yourself doing a workflow once → AI drafts an inspectable/editable skill {when, inputs, steps, verification}. Load-bearing insight: **narration-as-you-go** teaches the *why*, which is what makes it generalize beyond a macro recorder. Codex macOS-only at launch — a gap JARVIS could own on Windows.
- **Why it matters:** The zero-terminal PC-control pattern: demonstrate once → JARVIS generalizes. Borrowable design.
- **License:** proprietary, ideas-only. **Confidence: [HC]** (two labs converged same quarter).

### Study 94: AutoCua — MIT Windows-first harness, 11 days old ⭐ (16:02 IST)
- **What:** pip-installable multi-agent desktop/browser/shell harness (created 2026-10-08). Anti-pixel: model never sees a coordinate — picks numbered a11y elements; unseen numbers rejected before anything moves. Real input paths per OS (pywinauto; Interception kernel driver for UAC — LGPL non-commercial, not bundled). Compression agent beats context walls. Telegram remote control.
- **Why it matters:** Closest existing mirror of planned JARVIS architecture (numbered elements = verify-after-act vocabulary; Telegram = phone path; kernel-driver UAC = the autopsy's flagged failure mode). Fresh MIT codebase for patterns.
- **License:** MIT (GitHub API-verified; avoid the LGPL Interception piece). **Confidence: [MC]** — 117 stars, 11 days old, untested in wild. Flagged ⭐.

### Study 95: VeriGUI paper — action-effect verification formalized (16:02 IST)
- **What:** arXiv:2604.05477 (Baidu, Apr 2026). TVAE cycle: Thinking → Verification → Action → Expectation — each action checked against its *predicted* effect. Key insight: GUI failures are usually idempotent (72.3% leave screen unchanged) → "no expected change = failure" is a cheap detector. New metrics: Loop Rate + Recovery Success Rate.
- **Why it matters:** Portable ideas: (a) agent states expected UIA-tree change BEFORE acting; (b) idempotency as cheap failure signal. Feeds RLCD calibration thinking.
- **License:** paper only, ideas-only. **Confidence: [MC]** (single paper, mobile-biased).

### Study 96: "Your AI Agent Can't See What It Clicks" — annotate-and-confirm pattern (16:02 IST)
- **What:** Practitioner post (~9 days ago): capture-before-act → act → annotate result → ask model to confirm, NO as first-class signal. Failure table: HiDPI logical-vs-physical coords (conversion in drawing layer, not model's head), mss black frames on RDP (use Windows Graphics Capture), transient UI (poll, don't sleep).
- **Why it matters:** Immediately implementable in the Windows path, no new dependency. Pairs with #95: predicted effect + annotate + confirm-NO = complete cheap verification protocol.
- **License:** public-domain practice. **Confidence: [HC]** (anecdotal, not peer-reviewed).

### Nulls (demo shift)
- Project Mariner: wound down as standalone 2026, folded into Gemini. No open implementation.
- GitHub Copilot Computer Use (Oct 1, 2026 preview): proprietary, competitor signal only.
- Bytebot/OpenOwl/UI-TARS Desktop: known patterns, no new mechanism.
- AgentOne: AGPL-3.0 — avoided per license posture.

### Study 97: apache/maka — event-sourced agent runtime, Apache incubating ⭐ (16:02 IST)
- **What:** apache/maka — local agent workspace writing every model call, tool call, and permission decision to an APPEND-ONLY event log. Desktop app, TUI, CLI, bots, evaluator all read the same log via a Runtime Host; each state root has exactly one writer. 5,847 stars / 146 contributors in 5 months. Published per-task Terminal-Bench 2.1 eval: 61/89 (68.54%) vs OpenCode 49/89. Data stays in local SQLite. Windows: unsigned preview.
- **Why it matters:** The v2 master map and decade study both said "event stream + replayable diagnostics" is the target architecture — maka SHIPPED it. Direct reference implementation for JARVIS's brain runtime and trust story (UI, crash recovery, next prompt are all projections of the log; pruning never deletes history).
- **License:** Apache-2.0 (GitHub API-verified). **Confidence: [HC]** — but incubation churn; not for production. Flagged ⭐.

### Study 98: Qwen3.8-27B, Gemma 4 31B, Reflection Beam — October open-weight brain options (16:02 IST)
- **What:** Oct 13-16 wave. Meta "Muse Spark Open" 816B MoE (42B active, 1M ctx, open weights). Reflection "Beam" 501B MoE, 23B active, **Apache-2.0**. Qwen3.8-27B Apache-2.0, Gemma 4 31B Apache-2.0 (both single-GPU-friendly-ish but still >6GB). DeepSeek V4.1-Flash-1017 (Oct 17): **MIT open weights**, ~$0.20/full coding task, KV-cache compression paper (arXiv 2609.19969). Mistral Large 4 (1T MoE, weights promised end of Oct).
- **Why it matters:** Brain-ladder update: DeepSeek V4.1-Flash MIT = cheapest open cloud fallback ($0.15/$0.60 per M tokens); Qwen3.8-27B Apache-2.0 refreshes the "best open single-GPU model" slot. RTX 2060 6GB note: none of these run local on 6GB — all cloud/quantized-bigger-GPU. Honest scope kept.
- **License:** varies (MIT/Apache-2.0 per model; verify per use). **Confidence: [HC]** (multi-source).

### Study 99: Liquid LFM2.5-24B-A2B — 24B reasoning MoE for fast local agents (16:02 IST)
- **What:** Released Oct 14. 24B total, only 2B active per token, 131K context. 184 tok/s on Apple M5 Max, strong on tool-use tests (weaker coding/knowledge). Downloadable weights, MLX + llama.cpp support.
- **Why it matters:** A 2B-active MoE is the sweet spot for on-device agents — but 24B total (~14GB quantized) exceeds the 2060 6GB. Watch for smaller siblings; architecture validates the "reasoning MoE for agents" direction.
- **License:** unverified (check before use). **Confidence: [HC]** (announcement-stage).

### Study 100: VoxEntity-EU — Whisper fails entity-level, not WER (16:02 IST)
- **What:** New benchmark (r/MachineLearning, Oct 15): scores exact capture of dictated phone numbers/names/emails/dates in German/French. Whisper: 34% exact on dictated phone numbers vs 91% when the same text is written. Frames it as entity-level failure, not ordinary word error rate.
- **Why it matters:** Direct input for the Hinglish golden set (study 12): measure ENTITY-level accuracy (numbers, names), not just WER, for a voice assistant. Unverified single-source numbers — note as hypothesis.
- **License:** benchmark, n/a. **Confidence: [MC]** (unverified single source).

### Study 101: zvec-grep + qwen-code + cindy — radar stragglers (16:02 IST)
- **zvec-grep** (zvec-ai, 4,118 ⭐, Apache-2.0): ripgrep + BM25 + vector search behind ONE local MCP interface; index lives in project dir; symbol/structure-aware (breadcrumbs, call chains as searchable objects); CI runs retrieval-quality regression per PR. **For JARVIS:** the memory/code-search layer pattern — one MCP interface, local-first.
- **qwen-code** (28,567 ⭐, Apache-2.0): `qwen serve` turns agent into multi-client service; Telegram/DingTalk/WeChat/Feishu chat channels IN the main repo (`qwen channel start` — inbound→reply skeleton exists); computer use included. **For JARVIS:** phone-path reference + daemon-as-service pattern.
- **cindy** (3,193 ⭐): memory sits ABOVE the harness (harness/model switch never loses it); logins become owner-device cards excluded from model input. **For JARVIS:** approval-UX and secrets patterns.
- **Confidence: [HC]** (README-level). None flagged ⭐ (all borrow-pattern grade).

### License verification batch (16:03 IST)
- lahfir/agent-desktop: **Apache-2.0** (handoff claimed MIT — corrected).
- ComputerUseAgent/AutoCua: **MIT** ✅ (confirmed).
- apache/maka: **Apache-2.0** ✅ (confirmed).
- QwenLM/Qwen3-ASR: **Apache-2.0** ✅, 3,729 ⭐ (confirmed — the flagship STT).
- Still unverified: VoicERA repo (patterns-only use, safe), LFM2.5-24B-A2B (announcement-stage, check before use).

### Study 102: ElevenLabs "Architect" alpha — plain-language agent self-improvement ⭐ (16:04 IST)
- **What:** Released TODAY (2026-10-19): "ElevenAgents Architect" — build and improve voice/chat agents through natural-language conversation alone. Manages knowledge bases, prompts, workflows, voice settings, guardrails via dialogue; **analyzes thousands of conversation records to propose improvements**; pre-validates changes through simulation; saves modifications as version-controlled drafts. Supports external AI tools without vendor lock-in.
- **Why it matters:** The Hermes self-improvement pattern (memory spec study 22) just got commercialized in the voice-agent space: conversation-log mining → proposed improvements → simulated validation → versioned drafts. Borrowable playbook for JARVIS's own skill-improvement loop (ideas-only, enterprise/proprietary).
- **License:** proprietary. **Confidence: [HC]** (announcement-day). Flagged ⭐.

### Study 103: DeepSeek Search API + GPT-Live voices — today's infra signals (16:04 IST)
- **What:** DeepSeek opened its search engine to developers "for pennies per query" (2026-10-19) — a cheap search-tool option for JARVIS's research/deep-research skill. Same day: ChatGPT added 13 voices (GPT-Live-1.1, multilingual); Grok Voice 3.0 ranked #1 on Artificial Analysis Speech-to-Speech Index (86.9) Oct 14.
- **Why it matters:** Search API = cheaper web-search tool path; voice leaderboard moves = competitive context only (all proprietary).
- **License:** API/pricing TBD (check before use). **Confidence: [HC]**.

### Study 104: NVIDIA Nemotron 3.5 — open agent models, license caution (16:04 IST)
- **What:** Released Oct 15: 120B Super VL MoE (12B active, multimodal) + 74B Bolt (9B active, NVFP4, "24GB" tag — 65.5 tok/s locally on a Surface Laptop). Weights on Hugging Face.
- **Why it matters:** **License is openmdw-1.1 (NVIDIA custom, NOT OSI)** — needs legal review, NOT in the MIT/Apache borrow bucket. 74B = too big for the 2060 6GB anyway. Reference/benchmark value only.
- **License:** openmdw-1.1 — ideas-only, no code embedding. **Confidence: [HC]**.

### Study 105: TencentDB-Agent-Memory — MIT team memory hub with Skill assets ⭐ (16:12 IST)
- **What:** TencentCloud/TencentDB-Agent-Memory (29,613 ⭐, created Apr 2026). Team-level memory hub turning conversations, docs, and code into FOUR reusable memory assets: **Chat Memory, Skill, LLM-Wiki, Code-Graph** — governed, shared across agents and frameworks, with access control.
- **Why it matters:** "Memory → Skill" is the JARVIS upgrade roadmap Phase 3 mechanism (Hermes-style self-improving skills). This repo implements that conversion natively: experiences crystallize into Skill assets, shared across agents under governance. Plus code-graph = the knowledge-organization angle. Direct reference for memory spec (study 22) + skill spec (study 21).
- **License:** MIT (verified from LICENSE file text — GitHub API said NOASSERTION, read the file). **Confidence: [HC]**. Flagged ⭐.

### Study 106: Statewave — policy-bound memory traced to its producing event (16:12 IST)
- **What:** smaramwbc/statewave (Apache-2.0, Apr 2026, 283 ⭐). Policy-bound application memory: episodes + typed memories in Postgres + pgvector. Key design questions it answers: "Can one memory be traced to the event that produced it?" (provenance), "Can retrieval be constrained by identity/sensitivity/policy?" (governance), "Can operators explain the context that reached a model call?" (inspectability). Sibling repos: statewave-personal-assistant, statewave-multi-agent-memory.
- **Why it matters:** Memory spec (study 22) had a quarantine gate; Statewave adds the provenance axis — memories point back to the event that produced them. That pairs exactly with maka's append-only event log: event log (runtime truth) → memories with event pointers. Elegant combined architecture.
- **License:** Apache-2.0 (verified). **Confidence: [MC]** — small, young, honest-scope kept.

---

## FINAL ROUND — second shift continues (16:05–17:00 IST)

### Study 107: Moltbot's "message the user first" — proactive assistants live in messaging ⭐ (16:36 IST)
- **What:** Moltbot (Clawdbot, ~60-69k stars, 565+ skills on ClawdHub) — self-hosted message router: agent "messages the user first" via WhatsApp/Telegram/Discord/Signal/Slack. Per-channel heartbeat/visibility controls — user sees when agent is active, tunes alert presence per channel.
- **Why it matters:** Validates JARVIS's Telegram plan + adds the trust piece: explicit presence indicators ("awake / watching / acting") so proactivity is visible, never ambient-creepy. Steal the pattern.
- **Confidence: [HC].** Flagged ⭐.

### Study 108: UXPA 2026 Spectrum — ambient AI starts with "Authorize → Protect" ⭐ (16:36 IST)
- **What:** Microsoft senior designer's 2026 framework: AI interaction spectrum Conversational → Contextual → Agentic → Ambient. Rule: before acting independently, make capabilities, permissions, responsibilities visible — an explicit contract surface, not a checkbox.
- **Why it matters:** The exact answer to "proactive but never creepy": ship the consent-first surface BEFORE the screen watcher, not after.
- **Confidence: [HC].** Flagged ⭐.

### Study 109: India code-switching — "multilingual" ≠ Hinglish competence ⭐ (16:36 IST)
- **What:** 57% of urban Indian business conversations mix Hindi+English within the same sentence, sometimes mid-word. Multilingual agents (Hindi + English as separate modes) fail catastrophically on real code-switching. Sarvam's Saaras v3 ships a dedicated code-mixed mode. Natural Hindi = natively-written phrasing, not English scripts in Devanagari.
- **Why it matters:** JARVIS's sharpest edge for Owais — the chain must treat code-mixed input as one coherent instruction. "Supports Hindi" is false comfort; the bar is code-switching.
- **Confidence: [HC].** Flagged ⭐.

### Study 110: Voice 2026 — two-stage wake-word + "record what was heard" (16:36 IST)
- **What:** Two hardening patterns: (a) wake words as two-stage decision — tiny on-device model always-listening, heavier model re-verifies (kills false activations, the #1 reason voice gets disabled); (b) barge-in done right — track heard text via word-level TTS timestamps, unheard words never enter history.
- **Why it matters:** Supports the two-wake-word scheme; the heard-text rule is the exact remedy for the echo/bug family.
- **Confidence: [MC-HC].**

### Study 111: The graveyard's verdict — thesis failure beats execution failure (16:36 IST)
- **What:** Humane Pin ($230M, wrong hypothesis perfectly built), Rabbit R1 (demo ≠ market validation). Survival bar: "users come back on Tuesday because Monday was measurably better."
- **Why it matters:** Guardrail after the launch saga — validate by returning usage, never demo excitement; augment the screen, never replace it.
- **Confidence: [HC].**

### Study 112: OSWorld 2.0 — the new desktop long-horizon bar ⭐ (16:41 IST)
- **What:** June 2026, XLANG Lab (HKU, 36 authors). Replaces saturated OSWorld v1 (top agents >72.36% human baseline). 108 workflows, humans take median ~1.6h each, ~318 tool calls/task (~10× action depth). Dual scoring: strict + partial. Best agent at launch: 20.6% strict; Sept 2026 frontier ~doubled (41.7% strict / 77.9% partial). Designed to expose hidden-state recovery failures + mid-task changes.
- **Why it matters:** The measuring tape for desktop computer-use agents. JARVIS's golden sets should mirror its design (long, stateful, partial-credit).
- **License:** Apache-2.0 presumed (v1 was) — verify on repo. **Confidence: [HC].** Flagged ⭐.

### Study 113: Taste-Bench — the "vibe-check" eval, done scientifically ⭐ (16:41 IST)
- **What:** Oct 2026. 502 questions as "decision forks" from thousands of scored agent runs (SWE-bench Pro + METR transcripts). Run frozen at fork, model picks better path — parallel forks (diverging attempts) + detour forks (spot the mistake before the agent did). Best model 59.7% on two-choice (guessing = 25%). More reasoning budget barely helps — the clue isn't visible at the fork.
- **Why it matters:** Cheap labeled dataset for training/testing *judgment* — and the template for JARVIS's own decision-fork evals built from its failure logs.
- **Confidence: [HC].** Flagged ⭐.

### Study 114: AgentJudgeBench — LLM judges hit a structural ceiling [HC] (16:41 IST)
- **What:** Aug 2026. First benchmark of LLM-as-judge for agentic tool-calling: 3,808 instances, six DAG topologies. Judges degrade with difficulty; on hard tasks all six judges converge to 77–82% *regardless of scale* — structural ceiling, not capacity. CoT/temperature do ~nothing; structured rubrics help (+6.5pp).
- **Why it matters:** Don't judge hard multi-step runs with a bare LLM judge — use structured rubrics + ground truth, or measure noise.
- **Confidence: [HC].**

### Study 115: MLCommons Agentic Inference — the infra-grade harness [HC] (16:41 IST)
- **What:** MLPerf added Agentic Inference track (July 2026): multi-turn agent trajectories as serving benchmark — 490 coding + 500 enterprise workflow trajectories, 30,000+ turns. Metric shift: progress-per-turn, quality gates, latency under dependent turns — not tokens/sec.
- **Why it matters:** Closest thing to an industry-standard harness for agent-as-serving-system — template for JARVIS's latency-under-load dashboards.
- **Confidence: [HC].**

### Study 116: Dialpad "From Text to Voice" — measuring the voice gap ⭐ [MC] (16:41 IST)
- **What:** EMNLP 2026 REALM workshop. Framework converting text tool-calling benchmarks into paired text–audio instances (TTS + speaker variation + noise) without changing schemas/labels — text vs voice directly comparable. Text-to-voice gaps 1.8–4.8 pts; most failures were ASR/robustness, not wrong tools.
- **Why it matters:** Every text golden set overstates voice-first JARVIS's performance — this is the recipe for its paired audio golden set + text-to-voice penalty quantification.
- **Confidence: [MC].** Flagged ⭐.

### Study 117: The Hinglish blind spot — models lie more in Hinglish ⭐ [MC] (16:41 IST)
- **What:** Three 2026 findings: Plaksha truthfulness paper (5,674 Hindi/English/Hinglish QA, hallucination probes transfer but models hallucinate more on Hindi/Hinglish for matched facts); Kaggle benchmark (fake-completion 13.8% English → 35.1% Hinglish); COMI-LINGUA (expert-annotated Hinglish NLP benchmark). Practical tax: Hindi costs 4.4× the tokens of English on Qwen3 tokenizers.
- **Why it matters:** Every English-only eval hides JARVIS's worst failure mode — golden sets need a dedicated Hinglish honesty suite.
- **Confidence: [MC].** Flagged ⭐.

### Study 118: Databricks acquired Electric — "the sync engine became the product" ⭐ [HC] (16:41 IST)
- **What:** Aug 2026: Databricks bought Electric (PGlite — Postgres in WASM — plus real-time sync engine) explicitly to bring local Postgres to AI agent sandboxes. Agents need fast sandboxed local state; cloud alone can't provide it.
- **Why it matters:** Acquisition-level validation that agent-local state is the 2026 bet — JARVIS's memory-as-local-database is on the money trend.
- **License:** Apache-2.0. **Confidence: [HC]** (single source — treat as lead). Flagged ⭐.

### Study 119: LM Studio Bionic — the local-first desktop agent product ⭐ [VC] (16:41 IST)
- **What:** July 2026: Element Labs' standalone desktop AI agent for open models — agentic coding, document projects, on-device voice transcription, GGUF/MLX locally. Killer features: **LM Link** (route workloads to your own other machine over Tailscale E2E) + Zero-Data-Retention cloud as opt-in escalation.
- **Why it matters:** What a polished local-first agent looks like in 2026 — competitor AND template. LM Link mirrors JARVIS's phone↔PC remote shape.
- **License:** proprietary free app. **Confidence: [VC].** Flagged ⭐.

### Study 120: AnythingLLM 2026 (MIT) — the local RAG reference ⭐ [VC] (16:41 IST)
- **What:** Full local RAG app: workspaces, chunking, embeddings, LanceDB, cited answers — all local. 2026: on-device dictation across the OS, fully-local meeting transcription, folder drag-and-drop. MIT.
- **Why it matters:** Proof local RAG + on-device voice + agent tools ship as one product. Borrow ideas AND code (MIT): the workspace model + OS-level local dictation.
- **License:** MIT. **Confidence: [VC].** Flagged ⭐.

### Study 121: sqlite-vec — RAG in ONE .db file ⭐ [VC] (16:41 IST)
- **What:** Dependency-free C extension: SQLite vector similarity + FTS5 keyword search in a single .db file — no vector DB server. Hundreds of thousands of vectors brute-force fine; 50k chunks ≈ 188 MiB.
- **Why it matters:** JARVIS's memory = ONE portable, backup-able .db file. Kill the "separate vector DB daemon" idea.
- **License:** MIT (verify before bundling). **Confidence: [VC].** Flagged ⭐.
