# JARVIS Scout — Final Report
**Mission:** 5 hours of continuous research for JARVIS v2 (2026-10-19, ~06:53–11:55 UTC)
**Output:** 56 deep studies logged in `scout-log.md`, 21 of them ⭐-flagged (goldmine/diamond tier)
**Method:** hunt → study → log → rank, in 35 cycles. Quality over quantity; confidence stated honestly throughout.

---

## How to read this report

Studies are ranked by **impact on JARVIS v2 specifically** — not general interestingness. Tier 0 items change the architecture; Tier 1–2 change major subsystems; Tier 3–4 sharpen behavior and product. Every item links to its study number in `scout-log.md`.

---

## TIER 0 — Architecture-changing (do these or v2 is wrong)

### 1. Competence shock + error recovery grace (Study 46) ⭐ — v2's product strategy
Four quotes that are the whole v2 thesis:
- **"The first assistant that feels dependable rather than merely impressive takes the market."**
- **"The distance between the flashes and the floor is the entire unsolved problem"** — raise the FLOOR (reliability), not the ceiling (demos). This is why v2 is chatbot-first, voice-last.
- **Competence Shock:** deliberately script early interactions for maximum context + low risk + near-certain success. Trivial = no shock; impressive-but-off = no trust. v2's onboarding must be choreographed: the first 3 tasks are guaranteed wins.
- **Error Recovery Grace:** "Even when it's wrong, I don't feel screwed." Every mistake needs a graceful, reversible exit (pairs with ship-undo-for-everything).
- *Confidence: 90%.*

### 2. The fallback-chain recipe (Study 23) ⭐ — the C-B1 fix, highest-confidence finding in the log
Multiple production implementations agree: **retryable = transport errors only** (timeouts, DNS, 5xx, connection resets); hard per-attempt timeouts; per-provider circuit breakers; model failover as explicit policy rules in the worker layer, never "prompt magic." This is the direct fix for the autopsy's critical finding that v2's fallback chain never fires on timeouts/DNS failures.
- *Confidence: 95%. License: patterns from MIT/Apache-2.0 sources.*

### 3. The localhost hijack — CVE-2026-65105 (Study 38) ⭐ — v2 security requirement
A malicious web page issued HTTP requests to a victim's exposed local Ollama API (localhost:11434), modifying the chat template to silently prepend attacker instructions to EVERY subsequent conversation — persistent across sessions. Consequences for v2:
- The local model server **must bind 127.0.0.1 only** (never 0.0.0.0) and require auth even on loopback. Any webpage Owais visits is a potential attacker.
- **"Tools beat the perimeter":** a local model with a web-search MCP tool is a hybrid — the query leaves the machine mid-conversation. The per-response local/cloud indicator must account for TOOL calls, not just the brain.
- *Confidence: 95%. Extends architecture requirement R9.*

### 4. ClawHavoc — the skill supply-chain war (Study 11) ⭐ — the most important security lesson of 2026
Jan–Feb 2026: 1,184 malicious skills flooded ClawHub via 12 coordinated publisher accounts; at peak, 5 of 7 most-downloaded skills were malware. Defenses that emerged and v2 must adopt: quarantine + scan (static analysis minimum, VirusTotal-class at best) on every skill version; **fail-closed `installPolicy`** (operator-owned allow/warn/block before any install completes); secrets injected into the host process, never the skill sandbox; agent-written skills staged for human review, never auto-applied. Validates Playbook S7 as CRITICAL.
- *Confidence: 95%.*

---

## TIER 1 — The voice plugin (v2's voice layer, built last but designed now)

### 5. voiceloop (Study 1) ⭐ — barge-in done right, with proof
MIT. **Novel-word barge-in**: interrupt on genuinely new transcribed words (≥70% word-match against the spoken reply = echo, keep ignoring; new words accumulate = user interrupting, stop TTS) — never on raw audio energy. Reports **0 self-interruptions** in echo-coupled tests, 178 tests, public benchmark. This is the direct fix for the autopsy's barge-in findings (C-V1 dead echo guard, C-V2 permanent mute).
- *Confidence: 92%.*

### 6. Resemble AI Chatterbox (Study 13) ⭐ — biggest TTS-ladder upgrade since Kokoro
MIT. Beats ElevenLabs in blind preference **63.8%**, native Hindi/Hinglish, voice cloning from short samples. New TTS tier for v2: Piper (offline default) → Chatterbox (local neural, Hindi-capable) → Fish/ElevenLabs (cloud). Replaces the "Bodhi TTS needs a signup" step — Chatterbox runs locally with no account.
- *Confidence: 88%.*

### 7. Semantic VAD + Pipecat Smart Turn v3.2 (Studies 20, 52) ⭐ — end-of-turn detection
Two-signal end-of-turn: acoustic (has audio gone quiet?) + semantic (has the person FINISHED?). Smart Turn v3.2: Whisper Tiny + linear classifier, ~8M params, **10ms on CPU**, 23 languages, BSD-2. Plus: **false interruptions need explicit handling** (speech detected → agent interrupted → transcription comes back empty → resume, don't lose the turn).
- *Confidence: 88–90%.*

### 8. livekit-wakeword (Study 42) — "hello jarvis" needs NO voice clips from Owais
Single-command pipeline (synthetic TTS data generation → augment → train → ONNX export), backward compatible with openWakeWord. The roadmap's Phase 2 wake-word step is simpler than assumed: one command, a few hours on a free Colab/Kaggle T4. Documented gotchas: never zero-pad positives, target 0.2 false positives/hour.
- *Confidence: 90%.*

### 9. Voice UX: the four behaviors + the prosody gap (Study 45)
Split "backchanneling" into four separately-tuned behaviors: listener backchannel ("mm-hm") / turn-initial acknowledgment ("Okay, got it") / latency mask ("Pulling up your order") / proactive turn ("Are you still there?"). **"Prosody is the gap"** — the #1 robotic-voice cause isn't the TTS model, it's scripts written for text instead of speech. v2 needs a speakable-text transform (no markdown read aloud, contractions, short sentences) and a Hinglish backchannel inventory ("haan", "achha", "samajh gaya" — English "mhm" reads as foreign).
- *Confidence: 85%.*

---

## TIER 2 — Brain, memory, and the local machine

### 10. ik_llama.cpp (Study 5) ⭐ — 26× prompt speedup, v2's local server pick
MIT. IQ quantizations + KV-cache quantization deliver **26× faster prompt processing** on consumer hardware. This is what makes a 9B local brain feel instant. v2's local inference server choice.
- *Confidence: 90%.*

### 11. Nocturne (Study 7) ⭐ — sleep consolidation with PROOF it worked
Auditable memory consolidation: the agent consolidates during idle, then a **wake-quiz** verifies what was actually retained vs. forgotten. This turns "memory" from a black box into a testable subsystem — the "verify before claiming" principle applied to memory itself. v2's memory rework target (Phase 3).
- *Confidence: 88%.*

### 12. The 9B daily driver (Study 47) — v2's hardware spec, measured
Qwen3.5-9B Q4_K_M = **6.78 GB total VRAM at 32K context** — runs on any 8GB GPU. **"The real constraint is not the headline parameter count — it's VRAM headroom, bandwidth, and long-session behavior."** The 9B is the better daily driver than the 35B MoE (more headroom, more predictable, same prompt throughput); route hard reasoning to cloud instead. Upgrade path: 35B-A3B MoE on a 24GB GPU.
- *Confidence: 92%.*

### 13. DeepEval + persona simulation (Study 30) ⭐ — v2's eval stack
"Verify before claiming" needs machinery: DeepEval (open core) for regression evals of brain/tool behavior, persona simulation for testing the assistant against simulated Owais-like users (including Hinglish, including adversarial). Every v2 subsystem gets evals before it gets users.
- *Confidence: 88%.*

---

## TIER 3 — Agent behavior, safety, and honesty

### 14. ScrambleID (Study 17) ⭐ — identity-based prompt-injection defense
Scope-per-tool tokens (RFC 8693 token exchange): every tool call carries a token scoped to exactly what that call may do. The autopsy found **zero prompt-injection defense** (tool/web output pasted raw into LLM context = RCE risk); identity-based scoping is the structural fix, complementing the Anthropic "structural injection" pattern from the diamond mines.
- *Confidence: 85%.*

### 15. The Four Checks (Study 25) ⭐ — when an agent may act unasked
A proactive action must pass four gates: **confidence → value → timing → reversibility**. Fills the v2 design gap for proactive behavior (morning brief, screen watcher, reminders): high-confidence + high-value + right-time + reversible = act; anything else = suggest or stay silent. Directly prevents the "clippy problem."
- *Confidence: 92%.*

### 16. Scheduler reliability (Study 40) ⭐ — "they just stop doing useful work"
- **"Write before reason":** every job's first action writes a "started" record to durable storage. Absence of the record proves it never started. No silent failures.
- **"No successful runs in X hours" alert** — the killer alert. Agents don't fail loudly; they stop doing useful work.
- **Anomaly → human, not retry:** "Re-running the same flawed reasoning three times doesn't help." 3 strikes → notify Owais.
- **Zero-token chores:** scripts gather data free; the model only reads the summary (confirms the no-LLM briefing pattern).
- *Confidence: 90%.*

### 17. Error UX doctrine (Study 51) ⭐ — "users know what to do when AI fails"
- **Error + suggestion + action**, never a bare error: "That format isn't supported (works with .docx/.txt). Want me to convert it? [Yes] [No]"
- **Empty states that explain the search:** "Searched X for Y. No results. Similar: Z. Try those?" — builds trust even in failure.
- **Soft fails:** voice fails → text input; personalization fails → defaults. "Users feel like it gracefully adjusted."
- **Feature tiers at design time:** Critical (fail fast, alert) / Important (fallback to defaults, log) / Optional (skip silently, continue).
- *Confidence: 90%.*

### 18. Hinglish as a first-class input mode (Study 43) ⭐ — v2's language spec
- **Never normalize/transliterate Hinglish away** — models handle Romanised Hindi better than lossy Devanagari transliteration; normalization destroys meaning.
- System prompt recipe: state mixed-script input is expected + specify output script + two code-mixed examples. One template with an injected locale block (never parallel per-locale prompts).
- **Mirror the user:** Hindi→Hindi, Hinglish→Hinglish, English→English. Indian-English pragmatics ("Acha, dekhte hain" = polite "No").
- Evaluate Hinglish separately; test guardrails in every language. Security note: phonetic-perturbation jailbreaks in Hinglish hit 99% attack success in one study — multilingual safety alignment is a requirement.
- *Confidence: 88%.*

---

## TIER 4 — Product, platform, and craft

### 19. Agent Plugins 1.0 (Study 10) ⭐ — the vendor-neutral skill standard
Aug 2026 standard for packaging skills + MCP servers as installable, versioned, signed units. v2's skill format target — build to the standard, not a bespoke format, so the ecosystem (and future tooling) interoperates.
- *Confidence: 90%.*

### 20. platonkuch-dev/jarvis-ai (Study 34) ⭐ — "the hardest part wasn't the AI"
A shipped open-source JARVIS peer. Lessons: key-validation-on-paste (validate API keys the moment they're entered, not at first use); **no-LLM briefings** (template + data, zero tokens); self-updating via its own coding agent — with the ClawHavoc caveat that self-modification needs quarantine+review gates.
- *Confidence: 90%.*

### 21. Privacy by architecture (Study 37) + the local/wire audit (Study 39)
One-line thesis: **privacy is a chain — local inference + local storage + no content telemetry must ALL hold** ("a local model with a cloud embedding service still leaks document text"). v2 needs a per-response local/cloud indicator (accounting for tool calls, not just the brain) and a plain-language privacy statement in the Ollama style. Plus the LM Studio lesson: vendor proxies (e.g., HuggingFace model lookups) can quietly route through third parties — audit every network call the app makes.
- *Confidence: 90%.*

### 22. Beyond the chatbox (Study 49) — v2's chatbot UI spec
Make reasoning visible; design for STATE (render the interface the task needs — forms, tables, cards — not everything as text); explicit trust cues (confidence + sources); clear approval/handoff points before acting. Streaming details: buffer tokens, defer code-block render until the closing fence, visible STOP button. Empty state = onboarding moment (3-5 specific example prompts, never "Ask me anything"). "Script five realistic conversations, including a failure and a refusal, before drawing screens."
- *Confidence: 88%.*

---

## Strong supporting finds (not ⭐, but load-bearing)

- **Cost control (Study 41):** hard budget caps enforced in code, not alerts ("an agent can continue spending after the warning is sent"); 70/20/10 routing becomes **70% local (free) / 20% cheap cloud / 10% frontier** — the local-first architecture IS the cost strategy; prompt caching 50–90% off; metric = cost per successful task.
- **Morning brief pattern (Study 44):** "You don't want a digest. You want a brief" — surfaces what matters + why, with draft replies. Structure: top-of-mind → FYI → calendar. Cross-domain connections (email+calendar+tasks) are the moat. Anti-hallucination rules: use ONLY names/counts from tool output.
- **Windows deployment (Study 48):** PyInstaller false positives are endemic — code signing + VirusTotal pre-scan + Defender submission in the release checklist. **Audio devices are fragile on Windows** (Sept 2026 USB-audio breakage) — v2 needs a device-change listener with graceful re-init; a voice-first app must never crash when headphones are plugged in.
- **Personalization control surface (Study 50):** "Why am I seeing this?" / "show me less like this" / global disable / fast revoke / audit log. A "What JARVIS learned about you" page with per-item delete. Inferred preferences stay on-device.
- **Telegram isolated polling worker (Study 31):** the phone channel as a separate process that polls outward — no inbound ports, crash isolation from the main app.
- **Overlay click-through (Study 32):** real click-through on Windows = `WS_EX_TRANSPARENT` via pywin32; confirmed the HUD approach.
- **Competitor intel (Study 33):** Microsoft is building the JARVIS competitor into the OS (Hey Copilot + Copilot Actions). The moat: local-first, single-user boldness, personality. Don't compete on OS integration.
- **Two-tier brain routing (Study 35):** independent confirmation of the local-wakes-cloud-for-hard-tasks pattern.
- **MCP tool poisoning (Study 12):** pin MCP SDK versions, verify server identity, treat tool descriptions as untrusted (re-fetched at runtime).
- **Model download UX (Study 53):** per-layer progress bars + resumable downloads (non-negotiable for multi-GB files); the first-run magic moment — "turn off your Wi-Fi and ask again: it still answers"; honest framing of the local tradeoff ("not the smartest model on the market"); one shared brain server for HUD + voice + Telegram (Ollama's shared-printer model); show what fits the GPU before downloading (~0.6 GB per billion params at Q4_K_M).
- **Crash reporting without betraying local-first (Study 54):** separate capture from transmission — capture locally, redact aggressively, user decides. Next-launch banner: "JARVIS crashed last time. View / Send / Delete." Compact incident records (session, time window, failure, recovery action) — enough to diagnose without exporting prompts. Our flight recorder is the capture layer; this is its transmission policy.
- **GUI action verification (Study 55)** ⭐: "verify outcomes, not motion" — judge by the artifact, never the clicks. Compounding math (0.80^15 ≈ 3.5%): verify every step, keep plans short, checkpoint like a CEO. "Teach & Repeat": Owais demonstrates once, JARVIS generalizes — the zero-terminal-friendly PC-control pattern. v2 refuses-or-chunks anything past its reliable horizon, and says so.
- **Persona design (Study 56):** behavioral rules, not adjectives — "address him as sir, never flippant in serious moments" beats "be like a butler." Science backs the calm-butler choice (conscientiousness + agreeableness maximize credibility). Persona drift is real — v2 needs periodic re-anchoring + persona-consistency evals.

---

## What I deliberately skipped (per standing orders)

Unserious or low-value: thin "AI wrapper" product launches with no transferable pattern, benchmark-gaming leaderboard claims without methodology, enterprise-sales content disguised as engineering, anything already covered by the 363 PhD studies / 10 goldmines / 3 diamonds / REA. A few candidates were rejected mid-study for being press releases with no architecture inside.

---

## Top 10 actionable recommendations for v2 architecture

1. **Design v2's onboarding as three scripted competence shocks** (Study 46) — maximum context, low risk, near-certain success. The first impression is engineered, not hoped for.
2. **Implement the fallback chain per the recipe** (Study 23): retryable=transport errors only, hard timeouts, per-provider circuit breakers, explicit failover policy in the worker layer.
3. **Bind the local model server to 127.0.0.1 with auth on loopback** (Study 38); add the per-response local/cloud indicator covering tool calls (Studies 37, 39).
4. **Skill installer = quarantine + scan + fail-closed install policy + secrets in host process** (Study 11); agent-written skills staged for review, never auto-applied.
5. **Voice pipeline as a typed-frame stage graph** (Studies 1, 20, 52): novel-word barge-in, semantic end-of-turn (Smart Turn v3.2 class), explicit false-interruption handling, business logic strictly separated from the voice transport.
6. **TTS ladder: Piper → Chatterbox (local, Hindi) → Fish/ElevenLabs (cloud)** (Study 13); speakable-text transform + Hinglish backchannel inventory (Study 45).
7. **Memory = Nocturne pattern** (Study 7): consolidate during idle, verify with wake-quizzes; preferences learned from corrections, shown on a "What JARVIS learned" page with per-item delete (Study 50).
8. **Scheduler = write-before-reason + "no successful runs" alerts + anomaly→human** (Study 40); proactive actions gated by the Four Checks (Study 25).
9. **Every failure ships Error + suggestion + action** (Study 51); features tiered Critical/Important/Optional at design time; soft fails everywhere.
10. **Eval before users** (Study 30): DeepEval regression suites + persona simulation (including Hinglish and adversarial personas) for every subsystem. "Verify before claiming" as infrastructure.

---

## Confidence notes

- Highest confidence (95%): fallback-chain recipe, ClawHavoc defenses, localhost-hijack requirements — multiple independent sources or CVE documentation.
- High (88–92%): voice pipeline items, hardware spec, scheduler patterns, Hinglish spec, error UX — strong practitioner/research consensus.
- Honest uncertainty: ScrambleID (85% — vendor whitepaper, but standards-based patterns match field consensus); voice UX prosody guidance (85% — research-backed but partially subjective); Chatterbox Hindi quality (88% — benchmark-backed, but blind-preference tests vary by listener).
- Nothing in this report is inflated. Where a finding rests on a single source, the study entry says so.

---

*Mission complete. 56 studies, 35 cycles, 5 hours. The log is the journal; this report is the ranking. Owais — the scout delivered.* 🫡
