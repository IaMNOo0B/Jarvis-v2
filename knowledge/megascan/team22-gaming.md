# MEGA-SCAN TEAM 22 — Gaming & Entertainment Agents

Reverse-engineering how AI agents **play games, companion players, coach in real time, and
stream** — mined for JARVIS v2's media-control and proactivity patterns (and for the
general agent-architecture laws that only real-time, adversarial, 60-fps environments
force people to discover).

**Method note (honesty):** this scan fought the network. Git clones were cut
mid-transfer (`fetch-pack: unexpected disconnect`), tarball downloads were intermittently
stripped on write, and background processes lost workspace write permission partway
through the session. Salvage routes that worked: early foreground clones, the GitHub
connector (full README fetch), and `raw.githubusercontent.com` file reads. Every fact is
tagged **[CODE]** (read in cloned source), **[README]** (project's own docs, read in
full), **[SEARCH]** (search-result metadata only), or **[INFERENCE]**. Repos I could not
read are in the triage table and are never quoted for mechanism claims.

**Coverage:** **~55 repos touched** across 6 search terms ("game ai assistant" 179k+
total results ecosystem, "llm agent minecraft", "ai npc companion", "ai vtuber",
"ai game copilot", "llm plays game agent"). **20 read at depth** (9 full source clones,
1 README-only repo verified locally, 10 full-README/architecture reads), the rest
triaged in §4.

---

## 1. The deep reads

### 1.1 kolbytn/mindcraft — MIT — the reference LLM game agent [CODE]

The most complete open implementation of an LLM embodied in a live game (Mineflayer
body, Node.js). Its architecture is **two-tier**, and the tier boundary is the lesson:

- **Reflex layer — `src/agent/modes.js`** [CODE]: a priority-ordered list of *modes*
  (`self_preservation`, `unstuck`, `cowardice`, `self_defense`, `hunting`,
  `item_collecting`, `torch_placing`, `elbow_room`, `idle_staring`). Each mode's
  `update()` runs **every tick**; the file's own contract states update functions
  "should *not* be awaited longer than ~100ms as it will block the update loop" — long
  work goes through `execute()`, which runs off-loop. Modes declare `interrupts: ['all']`
  (self-preservation pre-empts anything) and can be *paused* by higher actions.
  `unstuck` is pure deterministic signal math: same position within 2 blocks for
  `max_stuck_time: 20` s while not idle → recovery action. No LLM is consulted for any
  of this.
- **Deliberation layer** [CODE]: chat commands (`!goToPlayer`, …) parsed from LLM
  output, backed by a **2,093-line `library/skills.js`** of ~40 hand-written async
  primitives (`craftRecipe`, `collectBlock`, `goToPosition`, `defendSelf`, …) — the LLM
  composes primitives; it never emits raw movement.
- **Code-as-action, sandboxed** [CODE — `coder.js`, `library/lockdown.js`]: for open
  tasks the LLM writes JavaScript that runs inside an **SES lockdown Compartment**
  (`makeCompartment, lockdown`), lint-checked with ESLint before execution,
  `MAX_ATTEMPTS = 5`, `MAX_NO_CODE = 3`, an `interrupt_code` flag the reflex layer can
  set, and generated code persisted per-bot under `bots/<name>/action-code/`.
- **Self-prompter** [CODE — `self_prompter.js`]: the autonomous-goal loop. State
  machine STOPPED/ACTIVE/PAUSED, 2 s cooldown between self-prompts, and a circuit
  breaker: **3 consecutive self-prompts that produce no command stop the loop**
  (`MAX_NO_COMMAND = 3`) and announce why in chat.
- **Vision is a tool, not a stream** [CODE — `vision/vision_interpreter.js`]:
  screenshots are captured on demand (`lookAtPlayer`, `lookAtPosition`) via a
  prismarine-viewer camera and sent to a vision model; the rest of the time the agent
  perceives only structured world state (`library/world.js`, `full_state.js`).

**Steal verdict:** the modes pattern is a ready-made template for v2's watcher layer —
priority-ordered, sub-100 ms, deterministic interruptors sitting *under* the LLM, with
an explicit interrupt ladder. The 3-strikes self-prompt breaker belongs in v2's
proactivity loop verbatim (as a pattern; code is MIT anyway).

### 1.2 zoyluoblue/mc_aiplayer — 161★, MIT — "the LLM chooses intent; deterministic tasks execute" [README]

A server-side Fabric mod (Java, ~32k lines, 197 classes) that states the cleanest
architecture law found in this entire scan, in its own words [README]:

> **"The LLM chooses intent. Goals define completion. Deterministic tasks execute."**

- The model "is not allowed to improvise per-tick movement or edit the world directly."
  It picks from a **registry of 63 tools**; a goal engine plans over **9 typed Goal
  variants** (item acquisition, pickaxe tiers, ore, crops, armor, workstations,
  stockpiles, food, blueprint builds); **34 concrete Task state machines** execute.
- **Completion is a typed postcondition**, evaluated by `GoalExecutor + postcondition`:
  "a Task ending is not automatically treated as mission success." This is exactly the
  failure mode (agent declares victory because the subroutine returned) that
  post-execution audits exist to catch — solved here structurally.
- Perception is explicitly **"visible perception"** — the agent only knows what its
  body can see (fair-play constraint), which keeps its world model honest.
- The README is unusually honest about limits: long navigation / deep mining / large
  builds "still need broader clean-commit, multi-seed evidence."

**Steal verdict:** #1 steal candidate for v2 overall (see §5). Typed goals +
postcondition verification maps 1:1 onto v2's skill system: a skill call should end
with a *checked postcondition*, not with the tool's return string.

### 1.3 BrightGir/dota-ai-coach — 33★, MIT — the proactive-coach reference [README]

A Go app that coaches Dota 2 live. Three mechanisms matter for v2:

- **Perception = the game pushes state.** Dota's **GSI (Game State Integration)**
  POSTs structured JSON (provider/map/player/hero/abilities/items) to
  `localhost:6000` with `buffer 0.1`, `throttle 0.1`, `heartbeat 30.0`. Thread-safe
  store (`RWMutex`) holds latest state. Zero screenshots, zero OCR — because the
  platform offers a state channel, the coach uses it. (Same law as v2's UIA-first:
  structured channel before pixels.)
- **Proactivity with an explicit silence window** [README — config]: auto-advice every
  `request_interval_seconds` (default **60**), and after the user asks a manual
  question, auto-advice is **paused for `silence_duration_seconds`** (default **60**).
  The user speaking resets the proactive clock. Advice pipeline: state → prompt
  builder → RAG (the LLM first generates search queries, then BERT-embedding retrieval
  over a Chroma knowledge base, `minSimilarity 0.7`) → final prompt; the AI worker
  retries **3 attempts** before giving up quietly.
- Delivery is a non-modal overlay (RayLib, F9 toggle / F10 focus) — advice never
  steals the game.

**Steal verdict:** the silence-window rule is the single most transferable proactivity
parameter in this scan: *any user-initiated interaction suppresses proactive output
for a fixed window afterwards*. v2's call-ringing model should adopt it next to the
5/day cap.

### 1.4 lmwilki/civ6-mcp — 222★, MIT — perceive the diff, not the state [README]

An MCP server that lets an LLM play Civilization VI end-to-end: **76 tools** over the
game's own Lua/rule-enforcing APIs ("no cheats, no vision model required"). Its
perception trick is the gem [README]:

> "Every turn, `end_turn` takes **before/after snapshots and reports what happened**:
> units damaged, cities grew, production completed, threats spotted near your cities."

The agent is never handed a raw state dump to re-read; it is handed a **diff rendered
as events**. That is precisely the shape v2's watcher/morning-digest needs (and what
Team 14 independently found as "diff-before-you-speak"): snapshot → diff → narrate
only the delta. A design note also worth stealing: Auto-End-Turn is deliberately
*disabled* by default because it "interferes with the blocker resolution flow" — the
agent, not a timer, decides when a turn is complete.

### 1.5 MineDojo/Voyager — MIT — curriculum + critic + executable skill library [CODE]

The 2023 landmark (GPT-4 in Minecraft) still defines the self-improvement pattern:

- **Three agents** [CODE — `voyager/agents/`]: `CurriculumAgent` proposes the next
  task from completed/failed task lists (with a **QA cache backed by a Chroma vector
  DB** so repeated world-questions aren't re-asked), `ActionAgent` writes code,
  `CriticAgent` verifies success **from the structured observation** (biome, health,
  hunger, inventory, voxels, equipment) — an `onError` event short-circuits the critic
  to failure without an LLM call.
- **Skill library = executable code, retrieved by embedding** [CODE — `agents/skill.py`]:
  successful programs are stored in Chroma with LLM-generated descriptions
  (`add_new_skill`, `retrieve_skills(query)`); the growing `skill_library/` (three
  trial snapshots ship in the repo) is the agent's long-term procedural memory.
  Control primitives (`mineBlock.js`, `craftItem.js`, `exploreUntil.js`, …) are the
  frozen bottom layer.
- Everything runs through Mineflayer state — again, no pixels in the main loop.

**Steal verdict:** v2 already has skill solidification (Builder D) — Voyager is the
proof-of-concept that the retrieve-by-embedding-index-over-code-skills loop works, and
its *critic-reads-state-not-screenshots* rule should govern v2's completion audit.

### 1.6 CraftJarvis/JARVIS-1 — license [UK] — memory-augmented multimodal planner [README]

Yes, there is a published **JARVIS-1** (arXiv 2311.05997) — a Minecraft generalist.
Architecture [README]: a multimodal LLM **planner** reads visual observations +
instructions and emits plans; plans dispatch to **goal-conditioned low-level
controllers**; a **multimodal memory** stores both pre-trained knowledge and the
agent's *own survival experiences* and is consulted during planning. 200+ tasks,
near-perfect short-horizon, ~5× prior SOTA reliability on ObtainDiamondPickaxe.
The planner/controller split with an experience memory in the loop is the same shape
as mc_aiplayer's law, one level up: the planner also never touches controls directly.

### 1.7 BAAI-Agents/Cradle — MIT (LICENSE verified) — general computer control [README]

Cradle plays *arbitrary* games/software (RDR2, Cities: Skylines, Stardew Valley…) via
the pure human interface: **screenshots in, keyboard/mouse out** — the deliberate
opposite of the structured-state school, chosen because most software has no GSI.
Structure [README]: a **planner** with action-planning + self-reflection modules, a
**memory** module, and a per-game **skill registry** split into **atomic skills**
(user-customised, e.g. movement) and **composite skills** built from them; UI grounding
via GroundingDINO (+ BERT for text). Skills for a new game are partly *generated
automatically* into a skills JSON. Its lesson for v2 is the boundary condition: when
no structured channel exists, the fallback stack is screenshot → grounding model →
atomic/composite skill registry — the same ladder v2's pc_control already climbs
(UIA → OCR → vision), with the registry idea as the missing rung.

### 1.8 latorc/MahjongCopilot — 1,089★, GPL-3.0 → ideas only [CODE]

Real-time Majsoul coach/auto-player. Perception tiering in one product [CODE]:

1. **Protocol interception (primary):** `mitm.py` implements a `WSDataInterceptor`
   (mitmproxy) with an `allowed_domains` allowlist; the game's WebSocket traffic is
   decoded via the liqi protocol (`liqi.py`, `liqi_proto/`) into exact game state.
2. **Brain:** the mjai-protocol bot slot (`bot/factory.py`, `bot_manager.py`) filled
   by **Mortal**, a strong RL mahjong model — local or online, 3p/4p.
3. **Action:** step-by-step guidance overlay *or* full auto-play + auto-join
   (`game/automation.py`, Playwright-driven browser in `game/browser.py`), with
   `game/img_proc.py` image processing as the lowest perception tier.

The hierarchy — wire protocol > DOM > pixels — is the general law; GSI (§1.3) is just
the sanctioned version of the same idea. (GPL-3.0: pattern only, no code.)

### 1.9 art-from-the-machine/Mantella — 419★, AGPL-3.0 → ideas only [README]

Voice-driven NPCs in Skyrim/Fallout 4: **Moonshine/Whisper STT → LLM → Piper /
xVASynth / XTTS TTS**, bridged into the game by a companion "spell" mod; a local Python
server (`main.py`, `config.ini`) holds conversation state. Two steal-worthy ideas
[README]: (1) the NPC voice stack is *per-character* — xVASynth gives each NPC its own
synthesised voice, i.e. voice identity as data, not code; (2) the conversation is
anchored to an in-world affordance (cast the spell at an NPC) — interaction has a
physical, unambiguous trigger, the game-world cousin of v2's wake word. AGPL: ideas
only.

### 1.10 SerpentAI/SerpentAI — MIT — the pixels-in framework [CODE]

The classic (2016-era, still maintained) "turn ANY game into an ML sandbox" framework,
born as an OpenAI Universe replacement [CODE]: `serpent/frame_grabber.py` +
frame-transformation pipeline capture the screen; `game_agent.py` plugins receive
frames and emit keyboard/mouse via a per-game API (`game_api.py`); sprite extraction /
OCR helpers in `cv.py`. Entirely plugin-based for both games and agents. Its historical
role for v2: it marks the *floor* of the perception hierarchy — when nothing else
exists, frames + input injection still work, at the cost of the agent having to learn
everything from pixels. (Contrast §1.3/§1.8: everyone who *can* escape pixels, does.)

### 1.11 microsoft/malmo — MIT — the platform that started it [CODE]

Microsoft's Minecraft RL platform: missions are **XML MissionSpecs**; an AgentHost
talks TCP to the game mod; observations arrive as JSON + video frames
(`Malmo/src/AgentHost.cpp`, ALE integration in `ALEAgentHost.h` — it also wraps the
Atari Learning Environment, `ALE_ROMS/`). Malmo's durable idea is the *contract*:
a declarative mission spec (world, agents, handlers, quit conditions) separated from
the agent — the ancestor of every "task spec + postcondition" design in §1.2.

### 1.12 yuniko-software/minecraft-mcp-server — 787★, Apache-2.0 [CODE]

The MCP-era form of the same body: a TypeScript server wrapping Mineflayer behind a
`ToolFactory.registerTool` pattern — **~22 tools** in 10 files (`block-tools`,
`position-tools` ×5, `crafting-tools` ×4, `inventory-tools` ×3, `chat-tools`,
`gamestate-tools` with exactly one tool: `detect-gamemode`) [CODE]. Perception tools
are conspicuously *fewer* than action tools — state comes from the bot object on
demand, not from a perception API. For v2 this is the template for exposing any
external body (game, media player, browser) to the brain: small typed tool surface,
factory registration, Apache-2.0.

### 1.13 Open-LLM-VTuber — 14,199★, MIT (LICENSE verified) [README]

Voice-interactive Live2D companion/streamer, fully offline-capable. Features that map
to v2 [README]: **voice interruption without headphones** ("AI won't hear its own
voice" — acoustic-echo handling), **AI proactive speaking** as a first-class feature,
emotion→Live2D-expression mapping driven from the backend, ASR backend zoo
(sherpa-onnx, FunASR, Faster-Whisper, Whisper.cpp, Groq/Azure), and *chat-log
persistence as the memory substrate* (long-term memory was removed and is being
rebuilt — an honest admission that persona logs ≠ memory). Desktop "pet mode" vs
window mode is a nice ambient-presence pattern: the companion shrinks to a peripheral
overlay instead of disappearing.

### 1.14 moeru-ai/airi — 50,511★, MIT [README]

The largest project in this scan: a self-hosted AI companion ("container of souls")
that streams, joins Discord voice, and **plays Minecraft and Factorio with friends**.
Engineering shape [README]: a monorepo of packages — stage UI, Live2D utilities,
RAG + embedded DB (DuckDB-WASM), multi-provider TTS (ElevenLabs/Azure/OpenAI-compatible/
local Kokoro), a WIP plugin system, and a memory subsystem ("Alaya", still WIP — the
roadmap lists Memory unchecked, which at 50k★ is itself a finding: *memory is the last
thing even successful companion projects finish*). AIRI's realtime-voice reference
implementation (VAD + STT + LLM + TTS) is published as a sibling example repo.

### 1.15 bigph00t/hermescraft — 73★, MIT [README]

Embodied companions in Minecraft built on the Hermes agent stack. Each character is a
*full agent instance*: own `HERMES_HOME`, own memory/session history, own **SOUL
prompt file** (`SOUL-minecraft.md`, `SOUL-civilization.md`, `SOUL-landfolk.md` ship in
the repo), own Mineflayer body reached via `agent → mc CLI → bot/server.js HTTP API →
Mineflayer` [README]. Two ideas for v2: (1) **persona as one swappable file per
context** — the same runtime becomes a companion, a villager, or a civilisation sim by
swapping SOUL; (2) multi-agent worlds where agents **privately message each other** —
social behaviour emerges from messaging + memory, not from a social module. It also
advertises "fair instead of x-ray omniscient" perception, matching §1.2.

### 1.16 ggg123124/vrchat-assistant — 26★, MIT [CODE/README]

A resident background service that ingests **VRChat friend activity over the platform
WebSocket** (online/offline, room changes, avatar changes) into SQLite and exposes it
to an AI agent over MCP [README]. Its notification discipline is the most precise in
this scan [README]: proactive host notifications fire only for auth-failure states,
gated by **`consecutive_fail_threshold` (default 3)** and **`min_interval_sec`
(default 300)**, over desktop-toast or webhook channels, with a watchdog service and a
**daily report** job. Translate directly: v2's proactivity should count *consecutive*
failures before speaking and enforce a hard minimum interval per source — numbers, not
vibes.

### 1.17 ruslanmv/BOT-MMORPG-AI — 312★, Apache-2.0 [README]

The imitation-learning school: an **Eel-based launcher dashboard** runs the whole
lifecycle without a terminal — `collect_data.py` (record gameplay) → `train_model.py`
→ `test_model.py` (bot plays) [README]. Perception is screenshots into a trained DL
model; there is no LLM and no state channel. Its transferable piece is product, not
architecture: **collect/train/run as one-click stages in a GUI** is how non-technical
owners actually adopt agent tooling (compare v2's zero-terminal doctrine).

### 1.18 zju-vipa/Odyssey — 411★, MIT [README]

Minecraft agent framework from ZJU: an **open-world skill library of 40 primitive +
183 compositional skills** [README], plus an open-sourced "Comprehensive Skill
Library" that auto-collects every collectible/craftable item. Its curriculum splits
roles across two models [README]: the curriculum agent *proposes* tasks; a separate QA
agent *schedules subtasks, generates QA context, and ranks targets* — role separation
inside the curriculum itself, echoing Voyager (§1.5) with the addition of an explicit
scheduling/ranking pass.

### 1.19 TACKLER16/Silksong-AI-Companion — 1★, no license [CODE — repo is README-only]

Verified locally: the repo contains a single README and no code. The *described*
pattern is still worth one line [README]: real-time screen capture (mss + OpenCV) →
Gemini vision (switched from Groq "for image processing") → an NPC overlay that
**roasts your deaths with combat tips** — event-triggered commentary on a *detected
game event* (death), not continuous narration. As a pattern: detect a salient event
deterministically, spend exactly one VLM call on it, speak once. Unverifiable as code;
pattern only.

### 1.20 pab1it0/chess-mcp — 90★, MIT [CODE]

An MCP wrapper over Chess.com's public API (profiles, games, online status) —
read-only data access, no play loop. Included to mark a category boundary: most "game
MCP" repos are *data* servers, not agents; civ6-mcp (§1.4) is the exception that
actually plays.

---

## 2. Cross-cutting laws (the PhD layer)

**L1 — The perception hierarchy is universal.** Every strong project escapes pixels as
far as the platform allows: **game-pushed structured state** (GSI §1.3, Mineflayer
state §1.1/1.5, Lua APIs §1.4) > **wire-protocol interception** (§1.8) > **platform
event streams** (§1.16) > **screenshots + grounding** (§1.7, §1.10). Nobody with a
state channel chooses vision for the main loop; vision survives as an on-demand tool
(§1.1) or an event commentator (§1.19). This is v2's UIA-first doctrine, independently
re-derived by an entire field.

**L2 — Two layers, always.** A fast deterministic layer owns the tick (mindcraft
modes, mc_aiplayer's 34 FSMs, Malmo handlers); a slow LLM layer owns intent
(planner §1.6, curriculum §1.5/1.18, tool-choice §1.2). No successful project lets the
LLM improvise per-tick actuation. Latency trick of the field: keep the LLM *off* the
real-time path entirely — reflex updates budget ~100 ms (§1.1), advice loops run at
60 s (§1.3), snapshots diff once per turn (§1.4).

**L3 — Completion is verified, never assumed.** Typed postconditions (§1.2),
state-reading critics (§1.5), before/after diffs (§1.4). "The subroutine returned" is
nowhere accepted as success. This is the gaming field's version of v2's
CompletionAudit — convergent evolution, strong validation.

**L4 — Skills are code in a library, retrieved not re-derived.** Voyager's
embedding-indexed executable skills (§1.5), Odyssey's 40+183 primitive/compositional
split (§1.18), Cradle's atomic/composite registry (§1.7), mindcraft's frozen
2,093-line primitive library (§1.1). Four independent implementations of *procedural
memory as retrievable code* — the pattern behind v2's skill foundry.

**L5 — Proactivity is governed by numbers.** Silence window after user interaction
(60 s, §1.3), consecutive-failure threshold before speaking (3, §1.16), minimum
interval per source (300 s, §1.16), self-prompt circuit breaker (3 no-command strikes,
§1.1), advice retry cap (3, §1.3). Every mature system replaces "notify when
appropriate" with countable gates — exactly v2's closed-enum + budget philosophy, with
three concrete parameters v2 doesn't have yet (silence window, consecutive-failure
threshold, per-source min interval).

**L6 — Commentary/commentator agents are event-triggered, not continuous.** The Dota
coach speaks on a timer *or* on questions (§1.3); the Silksong companion speaks on
deaths (§1.19); the VRChat service speaks on auth failures (§1.16). Nobody narrates
continuously — attention is spent on detected salient events. For v2's planned media
control: react to *track-changed / playback-paused / volume-changed* diffs (§1.4),
never poll-and-describe.

---

## 3. License summary

- **MIT / Apache-2.0 (code + ideas liftable):** mindcraft, Voyager, Cradle,
  Open-LLM-VTuber, airi, hermescraft, vrchat-assistant, SerpentAI, malmo, civ6-mcp,
  chess-mcp, minecraft-mcp-server (Apache), dota-ai-coach, mc_aiplayer, Odyssey,
  BOT-MMORPG-AI (Apache).
- **Ideas only, never code:** MahjongCopilot (GPL-3.0), Mantella (AGPL-3.0),
  chatclef (AGPL-3.0, triage).
- **Unverified / none:** JARVIS-1 [UK], Silksong-AI-Companion (no license, no code).

---

## 4. Triage table (one-line verdicts, [SEARCH] unless noted)

| Repo | Stars | Lic | Verdict |
|---|---|---|---|
| gamedev-skills/awesome-gamedev-agent-skills | 1,743 | Apache | Game-*dev* agent skills, not play — out of scope |
| jiran214/GPT-vup | 1,277 | none | Bilibili/Douyin AI VTuber streamer; AIRI/OLV cover the pattern better |
| arda27/AI-Waifu-Vtuber | 1,119 | none | Twitch/YouTube VTuber pipeline; redundant with §1.13/1.14 |
| IvanMurzak/Godot-MCP | 297 | Apache | Editor control for Godot — dev tooling, not a player |
| satelliteoflove/godot-mcp | 178 | MIT | Same category as above |
| Ars-note (TaylliSun) | 296 | GPL | Game-design workspace, not an agent |
| BAAI-Agents/GPA-LM | 161 | none | Paper list for game-playing LMMs — bibliography, mine for citations |
| CyniaAI/BuilderGPT | 164 | Apache | Generative Minecraft *building* tool |
| VillagerAgent (cnsdqd-dyb) | 187 | none | ACL-2024 graph-based Minecraft multi-agent framework — worth a future deep read |
| LudicDynamics/WorldLines | 97 | NOASSERT | Role-play agent orchestrator |
| hayowei/aisandboxgame | 80 | NOASSERT | Local-first LLM text-RPG engine |
| youichi-uda/unity-mcp-pro | 82 | MIT | Unity editor MCP — dev tooling |
| IvanMurzak/Unreal-MCP | 50 | Apache | Unreal editor MCP — dev tooling |
| AkshitIreddy/AI-Plays-God-of-War | 41 | Unlicense | LLM + captioning + YOLOv8 plays GoW — SerpentAI-pattern, small |
| 7vik/AmongUs | 41 | CC0 | Open-weight LLMs play Among Us — social-deduction study |
| laurigates/foundryvtt-mcp | 34 | MIT | Tabletop (FoundryVTT) MCP bridge |
| JesseRWeigel/minecraft-agent-swarm | 34 | MIT | Self-improving local-LLM Minecraft swarm |
| wuxiyang1996/COS-PLAY | 31 | MIT | Co-evolving decision + skill-bank agents for long-horizon play — Voyager-lineage |
| gautierdag/plancraft | 31 | MIT | Planning benchmark env, not a product |
| jeremy46231/axon | 28 | GPL | LLM + Baritone pathfinding Minecraft agent |
| gigio1023/minecraft-llm-agent-community | 25 | none | Mineflayer social-sim runtime with life goals |
| niveck/LLMafia | 25 | MIT | Async LLM plays Mafia vs humans |
| oscaem/ARIS-Unreal-GPT | 24 | none | AI-NPC story demo in Unreal |
| elefant-ai/chatclef | 21 | AGPL | Minecraft copilot mod (plays for/with you) |
| lechmazur/buyout_game | 21 | none | Multi-agent money-elimination benchmark |
| Goodbird-git/Player2NPC | 19 | none | Companion-mod showcase |
| MelonS/MelonS-Agents | 17 | MIT | Builds, plays, verifies its own colony-sim |
| Ahmed-KHI/digital-companion-core | 13 | NOASSERT | Persona + memory + emotion core for companions |
| stellarfeline/delvewright | 13 | GPL | Story → playable RPG dungeon generator |
| denfry/mcpfabric | 12 | MIT | MCP control of a running Minecraft (Fabric) |
| 0xAdafang/PersonAi | 36 | MIT | Local-first desktop AI-character chat app |
| lappat/farhold-os | 4 | MIT | Companion OS for tabletop campaigns |
| Hakurei-git/minecraft-codex-companion | 2 | MIT | Local-first Forge NPC companion |
| Joao-Serrao/skyrim-follower-framework | 2 | NOASSERT | Utility-AI + relationship sim for Skyrim followers |
| Yameteshka/ai-minecraft-companion | 1 | NOASSERT | Personal Minecraft companion (learns/remembers) |
| nekostul/nekostulAICompanion | 1 | MIT | Practical-task Minecraft NPC companion |

---

## 5. Verdicts

**Top 5 (for JARVIS v2):**
1. **mc_aiplayer** — the architecture law in one sentence + typed postconditions (§1.2)
2. **mindcraft** — reflex-mode layer, sandboxed code-as-action, self-prompt breaker (§1.1)
3. **dota-ai-coach** — push-state perception + silence-window proactivity + retry discipline (§1.3)
4. **Voyager** — curriculum/critic/executable-skill-library self-improvement loop (§1.5)
5. **civ6-mcp** — before/after snapshot-diff narration over a full 76-tool play loop (§1.4)

**Top 3 steals for v2:**
1. **Typed postconditions on every skill call** (mc_aiplayer §1.2, backed by Voyager's
   state-critic §1.5): a tool returning is not success — check the postcondition
   against structured state. Direct upgrade to v2's CompletionAudit.
2. **The numeric proactivity pack** (dota coach §1.3 + vrchat §1.16 + mindcraft §1.1):
   silence window after any user interaction, consecutive-failure threshold (3) before
   speaking, per-source minimum interval (300 s), self-prompt 3-strikes breaker.
   Drop-in parameters for `proactivity.py` beside the existing 5/day cap.
3. **Diff-events as the media/proactivity perception format** (civ6-mcp §1.4 + GSI
   §1.3): for media control and watchers, subscribe/push structured state and narrate
   *changes* (track changed, playback paused, friend came online) — never poll screens
   and never re-describe full state. This is Team 14's "diff-before-you-speak" with a
   working reference implementation.
