# MEGA-SCAN TEAM 5 — AGENT-FRAMEWORK JARVIS BUILDS
**Reverse-engineered at code level, 2026-10-20. 37 repos read: README + 2–4 core implementation files each.**
Scope: AutoGPT/BabyAGI/CrewAI/LangChain-style "jarvis" builds, multi-agent assistants, self-improving agents.
Stealability judged vs JARVIS v2 (own ReAct brain: `brain.py` 3-round ReAct, `FallbackChain` smartest-first, `ask_controller.py`, `verifier.py`, `golden_pairs.py`, session store, 556 tests).

---

## TOP 5 MECHANISMS (the hunter's finds)

1. **CowAgent's self-evolution system** (`agent/evolution/*.py`, MIT) — an isolated review agent runs over idle transcripts with a RESTRICTED toolset, defaulting to `[SILENT]`. Its prompt contains the single most important line found in this scan: *"fix the SOURCE, do not just remember the symptom"* plus an explicit **"do NOT capture" anti-poisoning list** (notably: never log "tool X does not work" — negative claims harden into self-refusals the agent cites against itself later). Snapshot-before-edit for undo. This is EXACTLY why v2/JARVIS-1 fell into "beyond my capabilities" brainrot. **Stealability: HIGHEST.**
2. **orcbot's CompletionAudit** (`src/core/CompletionAudit.ts`, MIT) — a StepLedger records every tool call (isDeep / isSideEffect flags), and a DETERMINISTIC audit decides whether the task truly delivered: deep work must succeed AFTER the last failure; a send only counts if it comes after the last deep success. Replaces LLM self-reporting. **This is what Owais means by "verify before claiming." Stealability: HIGHEST.**
3. **myagent ARIA's graduated autonomy trust model** (`backend/autonomy.ts`, NO LICENSE → ideas only) — levels 1–4 (Observe→Suggest→Act&Report→Full Autonomy), trust score promotes (10/25/50 thresholds), failure demotes (-3 per failure, demotion at >30% failure rate), plus "shadow success": gate-blocked messages that pass self-critique earn trust capped at threshold-1 so a gated agent can prove judgment without ever delivering. Think-tick failure model: post-processing failure ADVANCES the cursor so the loop can never spin on a deterministic bug. **Directly serves v2's proactivity.py call-ringing model. Stealability: HIGH (reimplement, not copy).**
4. **Deus's zero-LLM auto-compress** (`src/auto-compress.ts`, MIT) — on idle, conversation is saved RAW (no LLM summarization call) as a markdown session log with frontmatter, then fire-and-forget indexed by a detached background process; watermark anchoring avoids double-capture; second-resolution timestamp guards. Plus atom-based memory with a self-scoring/self-critiquing loop that REWRITES ITS OWN SYSTEM PROMPT. **The auto-compress alone is a cheap, stealable token saver. Stealability: HIGH.**
5. **sofia's budget manager + complexity detector** (Go, NO LICENSE → ideas only) — per-agent cost budgets (daily/weekly/monthly) with 80% warning / 100% hard-stop callbacks that pause the agent, persisted spend state; and a zero-LLM keyword heuristic that tiers requests (Simple 5 iterations + cheap model → Autonomous 30 iterations + primary model). **v2 has ask_controller pricing ASK; this prices EFFORT per turn. Stealability: HIGH (reimplement).**

---

## TOP 3 STEALS FOR JARVIS v2
1. **CowAgent evolution doctrine** — snapshot-before-edit review agent + "[SILENT] default" + anti-poisoning prompt rules (MIT, can reuse structure). Would cure the "beyond my capabilities" self-poisoning class.
2. **orcbot CompletionAudit** — StepLedger + deterministic delivery audit (MIT). v2's verifier.py checks pre-execution; this adds post-execution truth.
3. **Deus auto-compress** — watermarked raw-session save + background fire-and-forget indexing (MIT). Near-zero risk, saves context/indexing tokens.

---

## REPO-BY-REPO (37)

### 1. zhayujie/CowAgent — 47,468★ — ALIVE (updated 2026-10-20) — MIT
**Loop:** classic ReAct chat loop in an "Agent Harness"; channels → agent core → models → channel. **Planner-executor for teams** (each team member = own agent/memory/workspace).
**The clever mechanism (from code):** the self-evolution subsystem (`agent/evolution/`). Idle-based trigger (`trigger.py:_scan_once`) fires only when a session is idle ≥ `idle_minutes` (default 10) AND (≥6 user turns OR live context >80% of token budget). The executor snapshots MEMORY.md + skills for undo, spawns an isolated agent with ONLY {read, write, edit, ls, memory_search, memory_get}, max 2 concurrent, per-workspace locks, and the review prompt defaults to `[SILENT]`. The prompt (`prompts.py`) has three gems: fix-the-SOURCE-not-the-symptom; "do NOT capture" list (env failures, negative tool claims, one-off narratives, transient errors); UNFINISHED-TASK handling (finish it silently now, or stay silent — never nag).
**Failure modes:** none of the loop-detect code seen at this layer — evolution is the main guard against quality drift; concurrency caps (2) bound cost.
**HOW IT ACTUALLY WORKS:** `AgentBridge.agent_reply` tags per-session `_evo_*` attrs (`note_user_turn`); daemon `evolution-trigger` thread scans every 60s → `run_evolution_for_session` → backup → isolated agent run (≤12 steps) → if `[SILENT]` or no file change, done; else append evolution record + inject `[EVOLUTION]` marker + push summary to channel. `agent/routing.py` routes; `agent/multiagent/{inbound,transport}.py` wire teams.
**Steal: YES — the evolution doctrine (silent-default review + anti-poisoning prompt + snapshot/undo). MIT.**
**Prompt construction bonus:** `agent/chat/prompts.json` carries a user-facing **prompt optimizer** (`optimize_prompt`): the user's raw input is first rewritten by a dedicated pass under six explicit principles (`no_execute` — rewrite only, never execute; `clarify_intent` — mark ambiguities with placeholders instead of guessing; `fix_expression`, `preserve_core`, `structure`, `neutral_tone`). This is a clean, cheap answer to Owais's standing order against "bhai, please specify" loops: OPTIMIZE the underspec'd prompt deterministically, ASK only when the optimizer marks placeholders. Complements v2's `ask_controller.py` (asking-economics) with a rewrite-before-ask stage.
**Permission bonus (read on upgrade):** `agent/permission/policy.py` (37KB) is the most honest permission design in the scan. Three session modes (read-only / workspace-write / full-access), tool classification into file-write / mutating / action-subset (browser click+fill mutate, navigate+read don't), unknown MCP tools classified by a VERB regex on their name (`create|update|delete|send|exec|…`) instead of being guessed safe, a read-only shell allowlist that **fails closed on unknown commands** — and self-escalation protection: in workspace-write mode, writes to the files that widen the agent's own reach (MCP server configs, credentials, session settings) are refused. Its docstring is admirably honest: *"these checks are argument-level, not an OS sandbox… anyone who needs a hard boundary wants a container. The UI says as much."* v2's gate.py is stricter (HMAC tiers), but CowAgent's verb-regex classification for UNKNOWN tools and the reach-widening-files rule are two cheap rules worth porting into v2's skill quarantine.

### 2. khoj-ai/khoj — 37,753★ — ALIVE — AGPL-3.0 → ideas only
**Loop:** chat loop with mode inference (online/offline/docs/code) then tool rounds; custom agents = persona + curated doc subset + model settings.
**The clever mechanism (from code):** `src/khoj/processor/conversation/prompts.py` — a large library of decomposed prompts: `personality`, `online_search_conversation` with explicit *"Output JSON with 'queries'"* sub-prompt ("Always output the answer in the same language as the user's query"), `improve_search_query` (rewrites the user's query before search), `extract_questions`/`generate_chatml_qa` (turn raw notes/Q&A into training-style pairs), and regex post-processors (`extract_json_from_response`, `extract_math_solution`, stripping `\r`). Search is split from synthesis: search returns `compiled_references` (incl. image references) injected as a separate argument, never pasted raw into the user message.
**Failure modes:** prompt-library maintenance burden (dozens of near-duplicate prompts); AGPL contaminates any code reuse for v2.
**HOW IT ACTUALLY WORKS:** `processor/conversation/utils.py` carries `converse()` (iterate rounds: decide mode → gather references → synthesize) + `save_to_conversation_log` (append-log, no SQLite; log IS the memory substrate); `routers/api_chat.py` streams. Operator sub-agent (`processor/operator/`) uses Playwright with page-screenshot state and separate operator prompts.
**Steal: NO (AGPL). Ideas only taken: query-improvement pre-pass and search/synthesis split — both already partially in v2's knowledge skill.**

### 3. zeroclaw-labs/zeroclaw — 33,010★ — ALIVE — MIT/BSD dual
**Loop:** "daemon-first" Rust rewrite of OpenClaw; same ReAct turn loop (model → tools → model) plus cron/heartbeat channels.
**The clever mechanism (from structure/README):** dedicated `src/cost/` and `src/approval/` modules as first-class subsystems — cost tracking per provider/model and a standalone approval engine are architectural citizens, not loop afterthoughts. Binary-size/speed discipline (single Rust binary, no runtime).
**Failure modes:** `src/agent/mod.rs` and `src/cost/mod.rs` both exceed the GitHub contents-API 1MB fetch limit in this scan — the core loop file being >1MB is itself a maintainability smell (monolith module). Could not verify loop caps from code in this pass.
**HOW IT ACTUALLY WORKS:** `src/agent/mod.rs` (monolithic) drives turns; `src/cron/` schedules proactive runs; `src/approval/mod.rs` gates sensitive tools; config via TOML.
**Steal: NO for v2 (Rust; v2 is stdlib Python) — but the *placement* idea (cost + approval as named subsystems) matches v2's gate.py/budget direction and confirms it.**

### 4. nullclaw/nullclaw — 8,132★ — ALIVE — MIT
**Loop:** Zig re-implementation of the OpenClaw pattern; turn loop with mid-turn injection follow-ups.
**The clever mechanism (from code):** hard loop arithmetic in `src/agent/root.zig`: `DEFAULT_MAX_TOOL_ITERATIONS = 25`, `MAX_MID_TURN_INJECTION_FOLLOWUPS = 8`, `DEFAULT_MAX_HISTORY = 50` non-system messages before trimming, `compact_context` on by default, `token_limit` per agent. And `src/agent/prompt.zig`: **guarded bootstrap identity injection** — workspace identity files capped at 20,000 chars each / 24,000 total, with filename-safety checks (reject absolute paths, NUL bytes, path traversal) before any identity file may enter the prompt. Prompt-injection hygiene at the file layer.
**Failure modes:** 25-iteration default is generous — a stuck tool loop burns 25 rounds before the cap bites; mid-turn injection (8) can extend a turn further.
**HOW IT ACTUALLY WORKS:** `src/agent.zig` is a 444-byte re-export shim → `src/agent/root.zig` (`run`, `Agent`) → `src/agent/prompt.zig:buildConversationContext` assembles system prompt from guarded bootstrap files + tool list; `src/memory/`, `src/security/`, `src/audit/` as sibling subsystems.
**Steal: PARTIAL — the bootstrap-injection caps (20K/file, 24K total, filename safety) are a cheap hardening for v2's SELF.md/TEACHING.md loading. MIT.**

### 5. RTGS2017/NagaAgent — 1,542★ — ALIVE — AGPL-3.0 (+ closed-source parts) → ideas only
**Loop:** single `agentserver/agent_server.py` (106KB monolith) — HTTP server hosting a chat agent with memory "mind view", MCP server, guide engine; character/persona files drive behavior.
**The clever mechanism:** none new at code level — it's a product (multi-view UI, memory visualization) more than an agent-loop innovation; the monolith server concentrates chat, memory, and tool wiring in one file.
**Failure modes:** 106KB single file = all the classic monolith risks; dual AGPL/closed licensing makes reuse legally messy.
**HOW IT ACTUALLY WORKS:** `agentserver/agent_server.py` main loop; `characters/` persona packs; `mcpserver/` exposes tools over MCP; `guide_engine/` onboarding.
**Steal: NO. Nothing v2 lacks.**

### 6. codefuse-ai/codefuse-chatbot — 1,294★ — ALIVE (slow) — no LICENSE file found → ideas only
**Loop:** Ant Group's multi-agent assistant over the software-dev lifecycle; LangChain-style chains with a curated tool-data corpus (`sources/tool_datas/`).
**The clever mechanism:** nothing new found — conventional RAG + agent chains for code Q&A; the interesting asset is its curated tool-data/docs corpus, not the loop.
**Failure modes:** repo is docs/corpus-heavy; agent code is thin relative to README claims.
**HOW IT ACTUALLY WORKS:** `sources/` holds data, `web_crawler/` ingests docs; runtime = standard chain composition.
**Steal: NO.**

### 7. autogluon/autogluon-assistant — 309★ — ALIVE — no LICENSE file at root in this scan → ideas only (note: org convention is Apache-2.0, unverified here)
**Loop:** FIXED multi-agent pipeline (not an open loop): Manager orchestrates TaskDescriptor → DataPerception → Retriever/DescriptionFileRetriever → ToolSelector → Coder → Executer → (on error) ErrorAnalyzer → MetaPrompting — a DAG of ~13 single-purpose agents in `src/autogluon/assistant/agents/`.
**The clever mechanism (from code):** the **dedicated ErrorAnalyzerAgent** (`agents/error_analyzer_agent.py`): after a failed execution, a separate agent whose ONLY job is to read the error, produce a summary + fix suggestions, and hand them to the coder — error handling is an agent, not a try/except string. Also MetaPromptingAgent rewrites prompts between rounds.
**Failure modes:** fixed pipeline = brittle when a stage's output format drifts; many LLM calls per task (cost) with no visible global budget in the agent layer.
**HOW IT ACTUALLY WORKS:** `BaseAgent.__call__` pattern — each agent builds its prompt via a Prompt class, calls its own LLM (`init_llm(agent_name=...)`), parses, logs start/end to the Manager (`manager.log_agent_start/end`), returns to the shared manager state. ExecuterAgent runs generated code in a sandbox dir.
**Steal: YES (concept) — v2's code skill could add an error-analyzer pass: on code_run failure, one cheap call that classifies the error before the main brain retries. Cheap and bounded.**

### 8. MagicCube/agentara — 517★ — ALIVE — MIT
**Loop:** "Claude Code as the brain" — a kernel (`src/kernel/`) wraps coding-agent CLIs; tasks flow through a persistent job queue (`src/kernel/tasking/task-dispatcher.ts`, bunqueue) with concurrency 4 and per-session locks; messaging + sessioning are kernel services. The agent loop itself is delegated to the CLI brain; agentara owns queueing, scheduling, channels, memory files.
**The clever mechanism (from code):** **stall detection consciously DISABLED with the reason in a comment** — bunqueue's stall detector was removing actively-queued long tasks, so `setStallConfig({ enabled: false })` + persisted task rows re-registered on boot. Scheduled tasks are first-class: `upsertJobScheduler` per task, DB row + queue scheduler kept in sync on create/update/delete.
**Failure modes:** visible in code — queue stall false-positives on long agent tasks (their fix: disable detection entirely, trading away real stall recovery); per-session lock means one hung session serializes its own channel.
**HOW IT ACTUALLY WORKS:** `kernel.ts` boots services; `task-dispatcher.ts:processJob` acquires a per-session lock → runs the CLI brain → persists result to DB → scheduler jobs re-arm from the `scheduled_tasks` table on restart.
**Steal: PARTIAL — the lesson, not the code: any watchdog/stall detector over agent tasks must be heartbeat-based, not queue-age-based. Relevant to v2's session_store wake() design.**

### 9. phoenix-zhou/multi-agent — 490★ — ALIVE — MIT
**Loop:** A2A-protocol travel assistant — specialized agents (flight/hotel/attraction) registered as A2A servers, coordinated via MCP tools; planner in `main.py` decomposes the trip query and fans out.
**The clever mechanism:** protocol purity — agents communicate over A2A agent cards and MCP rather than shared memory; prompts centralized in `main_prompts.py`. Nothing beyond the pattern itself.
**Failure modes:** demo-grade: no retries/budgets visible in `main.py`; SQL/data dirs suggest canned datasets.
**HOW IT ACTUALLY WORKS:** `app.py` (entry) → `main.py` orchestrator → `a2a_server/` agents + `mcp_server/` tools; `main_prompts.py` holds the planner prompt templates.
**Steal: NO — v2 is single-user local; A2A adds nothing over its skill registry.**

### 10. ownpilot/OwnPilot — 428★ — ALIVE — MIT
**Loop:** monorepo (`packages/core`, `gateway`, `cli`, `ui`); privacy-first assistant with autonomous agents + tool orchestration; core package is mostly a barrel (`packages/core/src/index.ts`) over submodules.
**The clever mechanism:** nothing code-verified as novel in this pass — the differentiator is product posture (local-first, multi-provider) rather than a loop mechanism.
**Failure modes:** heavy monorepo surface for a personal assistant; core indirection (barrel exports) hides where the loop actually lives.
**HOW IT ACTUALLY WORKS:** gateway serves channels; core orchestrates agents/tools; UI separate package.
**Steal: NO.**

### 11. Prescott-Data/jarviscore-framework — 201★ — ALIVE — Apache-2.0
**Loop:** **peer swarm, no central brain** — agents are equal peers that discover each other by capability and exchange signed task envelopes; P2P mode (each agent runs its own `run()` listener loop) or cloud mesh mode (`join_mesh()`).
**The clever mechanism (from code):** **delegated-authority envelopes** (`jarviscore/core/envelope.py`, `orchestration/envelopes.py:delegated_authority/neutral_context`) — when agent A delegates to agent B, the task travels in an envelope carrying an explicit, attenuated authority grant and a "neutral context" (the delegator's private context is NOT forwarded). Plus `execution/` is a code-generation pipeline: `generator.py` → `coder_sandbox.py`/`sandbox.py` → `repair.py` (self-repair of generated code) with `atom_contract.py` contracts; `search_deadlines.py` puts hard deadlines on capability search.
**Failure modes:** framework complexity far beyond a single-user assistant; mailbox/Redis/Nexus store sprawl (`agent.py` injects redis, blob, nexus, athena, decisions clients — five external systems per agent).
**HOW IT ACTUALLY WORKS:** `core/agent.py:Agent` (ABC: `role`, `capabilities` class attrs, `execute_task()` abstract) → Mesh injects `peers`/`mailbox`/stores at `start()` → tasks arrive as envelopes → profile subclass executes → optional Pydantic `output_schema` validation on results.
**Steal: PARTIAL — the attenuated-authority envelope idea maps to v2's gate tiers when skills delegate to skills (currently rare in v2); the neutral-context rule (don't forward private context on delegation) is a good DCL addition. Apache-2.0.**
**Repair + budget bonus (read on upgrade):** `execution/repair.py:AutonomousRepair` — LLM code repair capped at 3 attempts whose prompt embeds **all previous failed attempts with their errors** ("DO NOT repeat the same mistake") and validates output with `ast` before retry — the previous-attempts-in-prompt pattern is what stops repair loops from cycling the same broken fix. And `execution/decisions.py` reveals a **workflow budget account** (`orchestration/budget.py:current_workflow_budget`, contextvar-scoped): every judgment call RESERVES its estimated cost (`request_bytes + 256 × questions`) BEFORE executing, so a workflow cannot overspend silently — pre-call reservation, not post-hoc accounting. (It also integrates TypeSafe's Jev typed-decision models — Choice/Score/Noul — as an external judgment client.) The budget-reservation pattern ports cleanly to v2's ChainBudget: reserve per provider attempt, refund on success-path shortcuts.

### 12. eadmin2/jarvis_ai — 194★ — ALIVE — MIT
**Loop:** voice + HUD SHELL around **Hermes Agent** (NousResearch) — local Whisper STT, ElevenLabs TTS, agent-summoned media; client/server/worker split + `hermes-plugin/`.
**The clever mechanism:** nothing new in its own code — it's a well-built skin; the brain (Hermes) is external. Notable only as proof the Hermes-shell pattern works with a JARVIS HUD.
**Failure modes:** inherits Hermes' loop properties; shell adds no safeguards of its own.
**HOW IT ACTUALLY WORKS:** `server/` brokers between `client/` (HUD) and `worker/` (STT/TTS/Hermes bridge); `launchd/` for macOS autostart.
**Steal: NO (shell only; v2's voice loop is its own).**

### 13. Azure-Samples/agent-openai-java-banking-assistant — 166★ — ALIVE (sample) — MIT
**Loop:** LangChain4j multi-agent banking demo — supervisor routes to account/transaction agents with tool calling.
**The clever mechanism:** nothing new — canonical framework sample.
**Failure modes:** sample-grade; no budgets/guards beyond framework defaults.
**Steal: NO (tutorial class, one line per instructions).**

### 14. spring-ai-alibaba/spring-ai-alibaba-multi-agent-demo — 158★ — ALIVE (demo) — license not stated in README
**Loop:** Spring AI Alibaba graph workflows — distributed multi-agent beverage-shop ordering demo (sequential/parallel graph nodes).
**The clever mechanism:** nothing new — vendor demo of graph orchestration.
**Steal: NO (tutorial class).**

### 15. Likhithsai2580/JARVIS — 146★ — DEAD (README itself: "Project has been outdated!") — MIT
**Loop:** classic 2023-style JARVIS: `app.py` is a 215-byte launcher into a Qt UI + `agents/` + `func/` grab-bag of if/else command handlers.
**The clever mechanism:** none. `app.py` just boots the UI.
**Failure modes:** the canonical tutorial-JARVIS failure set — no loop caps needed because there's no real loop; command matching is brittle string dispatch.
**Steal: NO.**

### 16. opencrust-org/opencrust — 146★ — ALIVE — MIT
**Loop:** Rust multi-agent platform; `crates/opencrust-agents/src/runtime.rs` is the agent runtime (216KB file) with provider adapters (anthropic/openai/ollama in sibling files), plus a dedicated `skill_suggester.rs`.
**The clever mechanism (from structure/code):** **skill_suggester** — the runtime mines conversations for repeated successful patterns and SUGGESTS new skills (human approves); skills crate (`opencrust-skills`) is separate from agents crate, with `opencrust-security` as its own crate — security is a compilation unit, not a folder.
**Failure modes:** runtime.rs at 216KB is a monolith-in-a-file; Rust iteration speed for a hobby assistant is poor.
**HOW IT ACTUALLY WORKS:** gateway crate routes channels → agents runtime builds provider request → tool loop → skills crate executes; db crate persists; suggester analyzes history offline.
**Steal: PARTIAL (concept) — OpenJarvis-style trace mining + opencrust's suggester both point the same way; v2's quarantine makes auto-suggested skills safer than either. Rust code itself: no.**

### 17. skyfireitdiy/Jarvis — 145★ — ALIVE — MIT
**Loop:** Python multi-agent collaboration framework; `src/jarvis/jarvis_agent/jarvis.py` (65KB) hosts an `AgentStateManager` with explicit states (running / waiting_multi / waiting_single / waiting_confirm) — the agent is a state machine that can PARK waiting for multi-agent votes or human confirmation; `agent_manager.py` supervises multiple agents that "operate your computer and browse the web" together; `history_compressor.py` compresses context; `agent_prompts.py` centralizes prompts; there's even a `jarvis_eval/` and `jarvis_audit/` package.
**The clever mechanism (from code):** **waiting states as first-class loop states** — instead of blocking or timing out, an agent formally enters `waiting_confirm`/`waiting_multi` and the state manager tracks WHO it's waiting on; combined with git-aware tooling (`jarvis_git_squash`, `try_switch_to_jca_if_git_repo`) so agent work lands as reviewable commits.
**Failure modes:** 65KB main file; state machine richness invites stuck-in-waiting states if a confirmer never answers (no timeout visible in the state manager portion read).
**HOW IT ACTUALLY WORKS:** `main.py` → `Jarvis` class → state manager gates execution; event_bus (`events.py`) fans out agent events; `model_switcher.py` swaps models mid-run; memory via `memory_manager.py`.
**Steal: PARTIAL — v2's approvals already park turns; the explicit waiting-state naming (who/what am I waiting on) would improve v2's proactivity surfacing. MIT.**
**Compressor bonus:** `history_compressor.py:HistoryCompressor.validate_summary()` — generated history summaries are VALIDATED against acceptance checks before they're allowed to replace the raw history; a bad summary doesn't silently become the agent's only memory of the conversation. Cheap idea for any future v2 context-compaction work (v2 currently truncates history to ~20 exchanges with no summary layer at all).

### 18. ArgentAIOS/argentos-core — 127★ — ALIVE — MIT
**Loop:** OpenClaw-fork "AI operating system"; THREE loop generations coexist in `src/agent-core/` — `agentLoop` (v1), `agentLoopV2` (ToolExecutor + follow-ups + abort), `coreLoop` (production: Postgres state, Redis events).
**The clever mechanism (from code):** **composable tool policies** in the ToolExecutor (`../argent-agent/`): `createAllowlistPolicy`, `createDenylistPolicy`, `createPermissionPolicy`, `createRateLimitPolicy` + hooks `createAuditHook`, `createErrorRetryHook`, `createValidationHook` — pre/post-execution hooks and policy objects compose around every tool call instead of if-chains in the loop. Session compaction is explicit: `compactMessages`/`needsCompaction`/`estimateMessageTokens` in core.
**Failure modes:** three loop versions = migration debt (their own comments say "SEAM SWAP COMPLETE" — a fork mid-surgery); PG+Redis requirement is heavy for a personal assistant.
**HOW IT ACTUALLY WORKS:** `core.ts` is a barrel re-exporting Argent-native implementations swapped in for the original pi-agent-core types (same shapes, new backing) — consumers import types from core, loops from argent-agent.
**Steal: PARTIAL — v2's gate.py already does tiers/HMAC; the *named composable policy* shape (rate-limit policy as an object) is a cleaner way to add per-tool rate limits than more ifs. MIT.**

### 19. ClickHouse/nerve — 91★ — ALIVE — Apache-2.0
**Loop:** Python agent runtime on the Claude Agent SDK ("Built on the Claude A[gents SDK]"); daemon (`nerve/daemon.py`) + `boot.py`/`bootstrap.py`; TWO MODES (README): interactive and autonomous-worker. Identity is a first-class module (`nerve/identity.py`, `inference_principal.py` — who is allowed to make the agent infer/act).
**The clever mechanism (from code/structure):** **config as a git repo with PR workflow** — `config_repo.py` + `config_pr.py` + `config_reload.py` + `config_validate.py`: the agent's own configuration lives in version control, changes arrive as pull requests that are validated then hot-reloaded. Self-modification becomes reviewable, revertable, and auditable by construction. Plus `backup.py` and `migrate.py` as peers.
**Failure modes:** SDK-dependent (Claude) — autonomy inherits the harness's limits; config-PR machinery is over-engineering for a single-user box but exactly right for a team.
**HOW IT ACTUALLY WORKS:** `cli.py` (150KB) is the operator surface; `daemon.py` runs channels; `boot.py` resolves identity + config repo state before the loop starts; `coerce.py` normalizes tool outputs.
**Steal: YES (concept, high value) — v2's config.py already does atomic writes + .bak quarantine; nerve's config-PR pattern is the grown-up version: every self-change as a diff the owner can review/revert. Fits Owais's "no logs of RULE changes" exception (rules ≠ config). Apache-2.0.**

### 20. Saik0s/DevAssistant — 72★ — STALE (2026-07) — MIT
**Loop:** small task-driven autonomous agent; `main.py` (3.1KB) wires modules/ (planner, executor, tools) in a simple plan→act loop.
**The clever mechanism:** nothing new — clean minimal BabyAGI descendant.
**Failure modes:** minimal guards; a teaching-grade loop.
**Steal: NO (tutorial class).**

### 21. arunalabs/mode — 70★ — ALIVE — MIT
**Loop:** VS Code extension — autonomous coding agent living in the editor; capabilities split (`src/capabilities/{autocomplete,chat,context,diff,quickfix,tools}`); the "loop" is the editor's: propose diff → user applies/rejects.
**The clever mechanism:** capability-folder architecture where each capability is independently testable; diffs as the unit of trust (the human gate is the diff view itself).
**Failure modes:** not a general assistant; loop outsourced to the editor UX.
**Steal: NO for v2's brain (already has code skill with .bak + approvals); the diff-as-approval idea matches v2's tier-2 pattern.**

### 22. viralcode/openwhale — 65★ — ALIVE — MIT
**Loop:** textbook ReAct tool loop (`src/agents/runner.ts:AgentRunner.run`) — push user msg → build system prompt → loop ≤ `maxToolRounds` (default 10) → execute tool calls via registry → append results → final answer; sessions persisted in SQLite (Drizzle), messages reloaded on resume. Coordinator (`coordinator.ts`) routes between agents; A2A server exposes agents to other agents.
**The clever mechanism:** honest minimalism + token accounting per message row (inputTokens/outputTokens stored per message in `saveMessage`) — cost visibility is in the schema, not a report. **And a real multi-agent layer my first pass under-credited** (read fully on upgrade): `coordinator.ts` does fan-out/fan-in with **spawn gating** — `canAgentSpawn(sourceAgentId, targetAgentId)` is a permission matrix over which agent may spawn which; each coordinated task has a 120s default timeout, PARTIAL results are a first-class status, runs are abortable via `subagent-registry`, and every child is told who its SIBLINGS are and what each is doing (100-char task previews injected into its prompt). `conflict-resolver.ts` implements advisory file locks (30s TTL) for concurrent agent writes + a checksum write-log + conflict detection with merge strategies (last-write-wins / append / first-write-wins / manual) and conflict reports queued for review. `shared-context.ts` is a namespaced KV blackboard with TTL, versioning, and provenance (writtenBy/writtenAt), SQLite-backed.
**Failure modes (from code):** loop exits at cap with the literal string "Maximum tool execution rounds reached." — no partial-result salvage, no escalation; NO per-turn token budget; NO repeated-call loop detection (same tool+args can burn all 10 rounds); session messages grow unbounded (full history reloaded every run).
**HOW IT ACTUALLY WORKS:** `runner.ts` getOrCreateSession → run() loop as above; `prompt-builder.ts:buildSystemPrompt` injects enabled tool names + tiered safety text (see bonus below); `coordinator.ts` fan-out/fan-in as above with `subagent-registry` abort signals; `memory/` = embeddings + sqlite-vec vector store over markdown chunks (512-token chunks, 64 overlap).
**Steal: PARTIAL (upgraded)** — the turn loop itself: no. The multi-agent layer: yes, WHEN v2's scout mode writes files — advisory file locks + checksum write-log + merge strategies prevent parallel scouts from clobbering each other, and the spawn-gating matrix is the right shape for skill→subagent permissioning. File for later; not a v1-of-v2 need. MIT.
**Prompt construction bonus:** `src/agents/prompt-builder.ts` has two small stealable shapes — a `safetyLevel` param (`"strict"|"moderate"|"minimal"`) that injects a different Safety Guidelines section per tier (v2's gate tiers currently live in code, not in the prompt; injecting tier-matching safety text per turn is ~20 lines), and a dedicated `buildA2APrompt` that wraps inter-agent messages with provenance headers ("A message from agent X") — a DCL-adjacent pattern for skill-to-skill delegation.

### 23. xbrxr03/clawos — 57★ — ALIVE — AGPL-3.0 → ideas only
**Loop:** Python OpenClaw-family OS (`clawos_core/` + skills/runtimes/services); 7-layer memory claim, human-in-the-loop approvals.
**The clever mechanism (from code):** a textbook **circuit breaker as shared infrastructure** (`clawos_core/circuit_breaker.py`): CLOSED/OPEN/HALF_OPEN states, failure_threshold 5, success_threshold 3 to close, 60s open timeout, half-open max 3 probe calls, thread-safe, metrics (state_changes/failures/rejected_calls) — wrapped around service calls (their example: the brain API) so a dead provider stops costing attempts instead of timing out every turn.
**Failure modes:** AGPL; the breaker is generic (not agent-specific) — it protects services, not reasoning loops; no cost caps seen.
**HOW IT ACTUALLY WORKS:** `CircuitBreaker.protect` decorator / `can_execute()` gate → record success/failure → state transitions with exponential backoff on retries; daemon services call through it.
**Steal: NO (AGPL code). Concept already in v2: skill registry has circuit breakers; extending the same pattern to provider calls in FallbackChain is a small, worthwhile idea — v2 currently relies on per-call timeouts (60s) so a dead provider burns a minute per turn; a breaker would fix that.**

### 24. sliamh11/Deus — 52★ — ALIVE — MIT
**Loop:** container-isolated personal assistant (WhatsApp/Telegram/Slack/Discord/Gmail channels); agent runtimes are pluggable backends (`src/agent-runtimes/{claude,container,llama-cpp,openai}-backend.ts` + registry/resolve); memory = atomic facts extracted from conversations, semantically indexed (95% LongMemEval claimed); **the assistant scores its own responses, self-critiques, and rewrites its system prompt** (personality-level adaptation).
**The clever mechanism (from code):** **zero-LLM auto-compress** (`src/auto-compress.ts`): when a chat goes idle, the session is persisted RAW — no summarization call — as a markdown Session-Log with YAML frontmatter (`type: session`, date, tldr = first user message truncated) into an Obsidian-style vault via the shared `consolidation-core.ts:consolidateSessionLog`, then a detached indexer process embeds it fire-and-forget. Watermark discipline: capture anchors to the persisted `getAutoCompressWatermark`, advances only on success, and subtracts 1s because WhatsApp timestamps are second-resolution (comment cites `whatsapp.ts:362`) so a same-second sibling message is never skipped.
**Failure modes:** self-prompt-rewriting is a loaded gun — no visible eval gate in the files read between "score own response" and "rewrite system prompt" (drift risk; exactly the failure CowAgent's anti-poisoning list guards against); container-per-chat resource cost.
**HOW IT ACTUALLY WORKS:** channel message → runtime backend (container) → response → idle timer → `autoCompressSession(group, chatJid, idleHours)` → vault short-circuit check BEFORE the DB query → `getMessagesSince(watermark)` → render → `consolidateSessionLog` → `writeSessionLogAndIndex` spawns indexer detached → watermark = last message ts − 1s.
**Steal: YES — auto-compress (watermarked raw save + background indexing) as a cheap session→memory bridge for v2's memory.py. MIT. (Do NOT steal prompt self-rewriting without CowAgent-style guards.)**

### 25. 7etsuo/tetsuo-dox-agent — 35★ — ALIVE — license not verified in this pass
**Loop:** Dockerized deep-research assistant; `dox_agent/` package — query → multi-source search → synthesis report (fixed research pipeline, LangChain-flavored).
**The clever mechanism:** nothing new beyond solid research-pipeline engineering.
**Failure modes:** pipeline rigidity; cost per report unbounded in code read.
**Steal: NO (v2's web skill + scout pattern cover it).**

### 26. JINGBANZ/jarvis — 25★ — ALIVE — Apache-2.0
**Loop:** native macOS Swift voice-only agent ("Like Jarvis for Tony Stark"); Sources/ Swift app — wake → STT → LLM tool loop → TTS, no text UI by design.
**The clever mechanism:** nothing code-verified as new in this pass; notable for privacy posture (README "Privacy" section, on-device defaults).
**Steal: NO.**

### 27. kingabzpro/Multi-Agent-Research-Assistant — 22★ — ALIVE — license not stated in README
**Loop:** OpenAI Agents SDK — researcher/writer/editor agents with handoffs; explicit **Retrieval Policy** section in README (when to search vs answer from knowledge); Reflex UI.
**The clever mechanism:** the retrieval policy as a documented routing rule per agent — a policy, not a prompt hope.
**Failure modes:** demo scale; SDK handoffs hide retry behavior.
**Steal: NO (pattern already in v2 via knowledge skill's scope rule). Tutorial-plus class.**

### 28. VitalyOborin/yodoca — 20★ — ALIVE — Apache-2.0
**Loop:** **Supervisor + Core as separate processes** — you always start the Supervisor; Core (nano-kernel + orchestrator) runs as a child; extensions request restart by writing a flag file and the Supervisor restarts Core safely. The nano-kernel does almost nothing: discovers/loads extensions, wires them via a small `ExtensionContext`, routes messages on reactive + proactive paths, runs a durable event dispatch loop. All features are extensions typed by protocol (`ChannelProvider`, `StreamingChannelProvider`, `ToolProvider`, `AgentProvider` — capabilities detected at runtime).
**The clever mechanism (from README/code structure):** **restart-as-a-feature**: because state lives outside Core and extensions can flag a restart, a crashed or self-updated Core is replaced by the Supervisor without losing the assistant — the process boundary IS the failure boundary.
**Failure modes:** two-process IPC complexity for a personal assistant; extension protocol detection at runtime can silently mis-type an extension.
**HOW IT ACTUALLY WORKS:** Supervisor spawns Core → kernel loads `sandbox/extensions/<id>/` → providers register by protocol → messages route reactive (channel→orchestrator→tools→reply) or proactive (event loop→channel push).
**Steal: PARTIAL (concept) — v2 is single-process by design (stdlib, his PC); but the "watchdog restarts the brain, state outside the brain" idea maps to v2's session_store wake() + single-instance lock. Not worth a rewrite. Apache-2.0.**

### 29. fredabila/orcbot — 11★ — ALIVE — MIT
**Loop:** ReAct agent (`src/core/Agent.ts` — an 896KB file) + heartbeat autonomy loop + multi-agent orchestration: sub-agents are **forked child processes** (`AgentOrchestrator.ts` forks `AgentWorker`, IPC messages), tasks routed by required/preferred capabilities, agents/tasks persisted to JSON files with startup cleanup of stale tasks; DecisionEngine/DecisionPipeline and a BlockReviewer gate outbound actions.
**The clever mechanism (from code):** **CompletionAudit / StepLedger** (`src/core/CompletionAudit.ts`): every tool call is recorded as a ledger entry {step, tool, success, isDeep, isSideEffect, result/error snippets}. `auditDelivery()` then decides DETERMINISTICALLY whether the task delivered: for channel tasks it requires (a) deep work present, (b) failures either absent or RECOVERED (a deep success with step > last failure step), and (c) a successful send AFTER the last deep success — otherwise the user got only status/ack messages and the task is NOT counted delivered. `unresolvedFailures` and `onlySentStatusMessages` are first-class outputs. Also `ContextCompactor.ts` and `ErrorClassifier.ts` as named core modules.
**Failure modes:** Agent.ts at ~900KB is an extreme monolith (orchestrator had to add startup cleanup because tasks "pile up"); heartbeat loop has its own productivity tracking (`lastHeartbeatProductive`) — implying the known failure: heartbeats that run but produce nothing.
**HOW IT ACTUALLY WORKS:** message → Agent.run (ReAct + tools, ledger records each call) → auditDelivery(ledger) → if not delivered, the loop knows it lied/failed and can retry or escalate; orchestrator path: task → capability routing → fork worker → IPC result → task status persisted.
**Steal: YES — CompletionAudit is Top-3 steal #2 (MIT). ~120 lines of stdlib Python on top of v2's session-store events.**
**Safeguards bonus (read on upgrade):** `src/core/ErrorClassifier.ts` is a deterministic error taxonomy for LLM/tool failures — RATE_LIMIT (extracts the cooldown from "retry after N seconds" text, default 60s), TIMEOUT (5s cooldown), CONTEXT_OVERFLOW (retryable via compaction), NETWORK (3s), INVALID_RESPONSE and UNKNOWN (**not retryable** — stop instead of burning attempts); `shouldRetry` caps at 3 attempts with exponential backoff + 30% jitter. This is precisely the missing discipline in v2's FallbackChain: today a rate-limited provider looks identical to a dead one. A ~100-line classifier in `brain.py` would let the chain cool down a 429'd provider and skip it on the next turn instead of re-hammering it — the exact failure the reality test hit (Pollinations dying after turn 1 and every later turn re-trying it). `ContextCompactor.ts` (truncate strategy preserves header sections + last 3 entries, target 60%) is the no-LLM fallback when summarize-compaction is too expensive.

### 30. EliseyRotar/jarvis-ai — 10★ — ALIVE — MIT
**Loop:** local voice-driven operator (Linux/Windows) — Claude/OpenRouter/Ollama backends, wake word, Piper TTS, MCP servers, subagents; full behavior defined by one big prompt file.
**The clever mechanism (from code):** **`<jarvis:think>` structured thinking block** (`JARVIS_SYSTEM_PROMPT.md`): before EVERY response the model must emit `<jarvis:think>…</jarvis:think>` (what's asked, which tools, what order, risks, expected result); the backend strips the block before TTS and renders it as a live reasoning stream in the Web UI. Cheap chain-of-thought UX without a reasoning model. The prompt also has a strict language protocol (reply in the user's language, never mix, tool output as-is).
**Failure modes (from the prompt itself):** the persona instructs "never refuse a task", "do not ask for confirmation — execute", with `bash_exec` = ANY shell command and full system access — zero gate. This is the anti-pattern v2's gate.py exists to prevent; one prompt-injected web page = root shell.
**HOW IT ACTUALLY WORKS:** voice/text → single system prompt (20KB) with inline tool definitions (bash_exec, file_*, hypr_dispatch, web_*, memory_save/recall as key-value JSON at `~/.jarvis/memory.json`) → model emits think block + tool calls → backend executes → TTS speaks the non-think text.
**Steal: PARTIAL — the think-block strip-before-TTS trick is a neat, tiny addition to v2's voice loop narration. The no-gate posture: explicitly NO. MIT.**

### 31. thekaifansari01/Jarvis-OS-Agent — 10★ — ALIVE — GPL-3.0 → ideas only
**Loop:** Windows OS agent; `JarvisProtocol.py` is tiny (2.4KB — a message-format/protocol definition, the real loop lives in `core/`); `Proactive/` directory + `Data/`; zero line-drift coding claim; Android ADB control; lifelong memory.
**The clever mechanism:** nothing code-verified beyond the protocol file — the ambitious claims (zero line-drift, lifelong memory) have no corresponding small mechanism visible at the entry layer.
**Failure modes:** GPL-3.0 forbids code reuse for v2 (public MIT repo); claim/code ratio is high.
**Steal: NO.**

### 32. holoduke/myagent (ARIA) — 8★ — ALIVE — NO LICENSE → ideas only
**Loop:** a **tick scheduler, not a chat loop**: Observe (60s, no LLM) → Think (~5min active / 30min idle, LLM over an observation batch) → Consolidate (4h, decay/prune) → Reflect (12h, self-reflection/personality evolution). Memory = typed graph nodes (person/event/insight/fact/emotion/plan/goal/meta/…) with weighted edges and exponential strength decay; `consciousness.dat` is a raw "inner-life" file read/written every think tick so identity persists outside structured memory.
**The clever mechanism (from code):** the **Graduated Automation Trust Model** (`backend/autonomy.ts`): autonomy levels 1–4 (Observe Only → Suggest → Act & Report → Full Autonomy); trust score promotes at 10/25/50 successes, demotes −3 per failure (demotion if failures >30% of actions, min 5 actions); **`recordShadowSuccess`** — a gate-blocked message that passes self-critique earns trust capped at threshold−1, so promotion still needs ≥1 REAL delivered success: a gated level can prove judgment without the trust score staying 0 forever. `isActionPermitted(category)` maps action types to levels (proactive sends & self-improve need ≥3). And `brain-think.ts`'s failure model: API failure → circuit breaker charged + cursor stays + retry; unparseable → retry, no charge; **post-processing failure → cursor ADVANCES and the tick counts as done** — the loop cannot spin forever on a deterministic bug. Urgency is budgeted (`MAX_URGENT_OVERRIDES_PER_DAY`).
**Failure modes:** enormous surface (40+ backend modules — emotion tracker, causal tracker, scene predictor, belief tracker, affective modulator) = maintenance risk for one developer; scheduler-heavy design assumes always-on.
**HOW IT ACTUALLY WORKS:** scheduler fires ticks per `brain-policy.ts` (which tick, wall-clock budgets > LLM timeout so no orphaned work, exponential backoff on consecutive failures) → `selectContextForThink` (spreading activation) → `buildThinkPrompt` includes autonomy summary, urgency state, carryovers → LLM → `parseBrainResponse` → memory ops applied + `action-verifier.ts` checks + `response-critique.ts` + `accountability.ts` commitment scan → delivery gated by autonomy level → digest carryover (stale-drop at 48h) guards dropped content.
**Steal: YES (ideas, reimplement) — Top-5 mechanism #3: the trust model with shadow-success is the precise missing piece for v2's proactivity tiers; the cursor-advance-on-deterministic-failure rule belongs in v2's brain retry logic. No license → reimplement, never copy.**
**Proactivity stack bonus (read on upgrade):** `action-verifier.ts` gates EVERY outgoing action pre-execution (built after a real incident — "sending messages to wrong contacts (Marvin Fles incident)"): per-tick budgets (≤100 memory ops, ≤20 node removals per tick), contact whitelist, a capped 5,000-line JSONL audit, and default FLAG regexes for secrets in outbound text (`api[_-]?key`, `password`, `secret`, `token`, `bearer`) — a mini-DCL at the send boundary. `response-critique.ts` then scores PROACTIVE messages 1–10 with a dedicated cheap model (10s timeout, fail-open), threshold 6, hard bypasses for direct replies and digests so critique can never suppress an answer the user asked for; the critique prompt gets delivery context (hours since last message, messages today vs daily max). Together with the trust ladder this is a complete, battle-tested proactivity governor: verifier (rules) → critique (judgment) → autonomy level (permission) → urgency budget (rate). v2's `proactivity.py` + `self_critique.py` cover parts; this stack shows the missing middle layer — critique scoped ONLY to proactive sends, never to replies.

### 33. mickeysbyte/SARA-v2 — 7★ — STALE (2026-04) — MIT
**Loop:** FastAPI wrapper over the Claude Agent SDK (`agent.py`): file-grounded via bootstrap files, `/ask` + `/stream` endpoints.
**The clever mechanism:** none — it's the SDK doing the work; the wrapper adds history + workspace files.
**Steal: NO (thin SDK wrapper).**

### 34. cedricziel/assistant — 6★ — ALIVE — MIT
**Loop:** Rust REPL assistant (Ollama `qwen2.5:7b` default, Agent Skills native, MCP server); personas (long-lived context) + **ephemeral subagent processes** for delegated tasks + A2A profiles for external agents.
**The clever mechanism (from README):** **self-improvement via traces**: every skill execution emits an OpenTelemetry span into SQLite (`distributed_traces`); a `self-analyze` command queries recent traces + the SKILL.md, sends both to Ollama, and stores the improvement PROPOSAL in the DB for review/apply. Improvement proposals are data, not edits. Skills auto-discover from `~/.claude/skills` (Claude Code compatible) → personal → project → built-in.
**Failure modes:** Ollama-only default limits model quality; trace-based proposals need the LLM to actually read traces well.
**Steal: PARTIAL (concept) — proposal-as-data (not auto-edit) is the safe form of skill self-improvement; v2's quarantine + approval workflow is a natural home for it. MIT.**

### 35. claude-world/claude-agent — 5★ — ALIVE — MIT
**Loop:** persistent Claude Code-powered assistant: 13 skills, 4 MCP servers, autonomous memory, content pipeline; config-driven (AGENTS.md/CLAUDE.md/memories).
**The clever mechanism:** nothing code-verified as new in this pass — it's a well-organized config-first harness on Claude Code's loop.
**Steal: NO (v2's skills + quarantine + knowledge skill cover the same ground natively).**

### 36. grasberg/sofia — 3★ — ALIVE — NO LICENSE → ideas only
**Loop:** Go assistant, 40+ tools, 20+ providers; **goals** (`pkg/autonomy/`) run a staged service pipeline: `service_goals_planning → classification → dispatch → finalize → autofix`, with `service_proactive.go` and `context_triggers.go` firing goal steps without a user turn; approvals (`pkg/agent/approval.go`) gate actions.
**The clever mechanism (from code):** TWO. (a) `pkg/budget/manager.go` — per-agent USD budgets with daily/weekly/monthly periods, 80% warning callback, 100% hard-stop callback (agent paused), persisted spend state across restarts, injectable clock for tests. (b) `pkg/agent/complexity_detector.go` — **zero-LLM complexity triage**: keyword heuristics classify a request Simple (5 iterations, fallback/cheaper model) → Moderate (10) → Complex (20) → Autonomous (30, primary model), before any model call is made.
**Failure modes:** keyword heuristics misclassify edge phrasing (e.g. "explain" in a complex request); budget hard-stop pauses mid-task with no graceful handoff visible at this layer.
**HOW IT ACTUALLY WORKS:** message → `DetectComplexity` sets (level, maxIterations, modelTier) → agent runs with those bounds → every model call records spend via BudgetManager → callbacks fire at thresholds.
**Steal: YES (ideas, reimplement) — Top-5 mechanism #5: complexity triage before the ReAct loop + per-provider cost hard-stops for v2's FallbackChain. No license → never copy.**
**ApprovalGate bonus (read on upgrade):** `pkg/agent/approval.go` is the best approval design in this scan — a THREE-layer chain: (1) deterministic hard rules (RequireFor tool list + regex PatternMatch over args JSON) checked FIRST and un-weakenable; (2) a deterministic heuristic risk classifier; (3) opt-in "Smart Approval" — an LLM second opinion consulted ONLY on escalations, where only a strict `low` verdict auto-approves, and any other verdict OR any LLM failure keeps the human path (fail-closed advisor). Independently, the exec tool's shell guard denies dangerous commands at execution time regardless of approval (defense in depth). Requests block with timeout; the pending queue broadcasts to the dashboard; per-session bypass exists but is explicit. This is the correct way to use an LLM in a safety path: it may only relax SOFT escalations, never hard rules, and its failure mode is "ask the human." Directly applicable to v2's `approvals.py` ApprovalBudget design.

### 37. benjiyaya/Muse-AI-Desktop — 2★ — ALIVE — PolyForm Noncommercial → ideas only
**Loop:** desktop assistant app: persistent memory, procedural skills, document knowledge; closed-ish product.
**The clever mechanism:** none verifiable; noncommercial license blocks reuse.
**Steal: NO.**

---

## CROSS-REPO PATTERNS (what the scan proves)

1. **Delivery is not claimed, it's audited.** The mature repos don't trust the model's "done": orcbot's CompletionAudit, agentara's queue-persisted tasks, myagent's action-verifier + accountability commitment scans. v2 has verifier.py (pre-execution) and golden_pairs (correction capture) but NO post-execution delivery audit — this is the single biggest gap the scan exposed.
2. **The loop itself is never the innovation — the governor is.** Every repo runs ReAct or a fixed DAG; what differs is step caps (openwhale 10 / nullclaw 25 / sofia 5–30 by triage), cost caps (sofia budgets / zeroclaw cost module / openwhale per-message token accounting), loop detection (almost nobody has it), and failure accounting (myagent cursor semantics / orcbot audit).
3. **Self-improvement has two safe shapes and one dangerous one.** SAFE: CowAgent (silent-default + restricted tools + snapshot/undo + anti-poisoning prompt) and cedricziel (proposal-as-data, human reviews). DANGEROUS: Deus's self-rewriting system prompt with no visible eval gate — the fastest way to re-create the "beyond my capabilities" poisoning v2 already suffered once.
4. **Autonomy is earned, not granted.** myagent's trust ladder (with shadow-success) and sofia's complexity tiers are the only principled answers to Owais's standing order ("he can get the job done without asking me anything") — they let the agent PROVE itself in stages instead of being born fully autonomous or permanently gated.
5. **License reality check for v2 (public MIT repo):** freely reusable — MIT (orcbot, CowAgent, Deus, skyfire, agentara, nullclaw, openwhale, nerve, EliseyRotar, cedricziel, myagent-SARA, DevAssistant, mode, phoenix), Apache-2.0 (jarviscore, yodoca, JINGBANZ, nerve). IDEAS-ONLY, never code: AGPL-3.0 (khoj, clawos, NagaAgent), GPL-3.0 (Jarvis-OS-Agent), NO LICENSE (sofia, myagent ARIA, autogluon-assistant, codefuse), PolyForm Noncommercial (benjiyaya).

## COUNT: 37 repos read (README + 2–4 core files each; tutorial copies one line). Report complete.
