# JARVIS Repo Archaeology — What the GitHub JARVISes Do That v2 Doesn't (Yet)

*Scan date: 2026-10-20. Method: 6 GitHub searches (~105,000 matching repos in total),
~180 repos triaged from result pages, 14 READMEs read in full, last-commit dates
verified via the commits API for the headline repos (GitHub's "updated_at" is
metadata noise and was NOT trusted).*

---

## 0. The v2 baseline (so the gaps below are honest)

JARVIS v2 (ours, `~/workspace/jarvis-v2`) already has: an LLM fallback-chain brain
with ReAct tool loop, a fail-closed permission gate with HMAC approval tokens,
data-classification/redaction (DCL), a jailed skill registry (skills: web,
code, notes, knowledge, clock, echo), episodic+semantic memory with provenance
and secure forget, an 8-stage echo-proof voice loop, UIA-based PC control,
a Telegram phone channel with PIN-gated confirmations, an approvals system with
daily budget + undo, self-critique, golden-pairs learning from corrections,
and ask-economics (priced ask-vs-act decisions).

**That is more safety/architecture depth than every repo below.** What the
field has that we don't is mostly *product surface*: rituals, digests, timers,
dictation, scenes, meters. Nobody below has our gate/DCL/verifier stack.

---

## 1. The repos

### 1. microsoft/JARVIS (HuggingGPT) — 25,463★ · Python · last real feature work Jan 2024; last commit 2025-07-29 (external patch merge) · DORMANT research repo
- **What it does:** Not a desktop assistant at all despite the name. A research
  system where an LLM controller plans a task, decomposes it into subtasks
  **with an explicit dependency graph** (`dep` fields), selects specialist
  models from Hugging Face by their descriptions, executes them, and composes
  the answer. Full local mode wants ≥24 GB VRAM / up to 284 GB of models.
- **Cleverest idea:** *Model selection by description + dependency-aware task
  plans.* Follow-ups worth knowing: **EasyTool** — rewriting tool docs into
  concise instructions measurably improves agent tool choice; **TaskBench** —
  a benchmark for task automation.
- **Architecture:** 4 stages (Plan → Select → Execute → Respond), config-driven
  inference modes (local / HF endpoints / hybrid).
- **Verdict:** A famous-name research artifact, not a rival product. Steal the
  ideas (dependency plans, concise tool docs), not the code shape.

### 2. open-jarvis/OpenJarvis (Stanford Hazy Research) — 11,631★ · Python · last commit 2026-10-19 · VERY ALIVE
- **What it does:** A *framework* for local-first personal AI ("in the spirit of
  PyTorch"). One-command installs, a browser GUI, 8 built-in agents in three
  modes (on-demand / scheduled / continuous), and **presets**: morning-digest,
  deep-research, code-assistant, scheduled-monitor, chat-simple.
- **Cleverest idea:** **The morning digest as a product** — a scheduled agent
  that reads email/calendar/health/news and *speaks* your briefing. Runner-up:
  the skill ecosystem play — skills follow the open agentskills.io standard and
  can be imported from public registries (~150 Hermes skills, ~13,700 OpenClaw
  community skills), then **`jarvis optimize skills`** improves them from your
  own trace history (DSPy) and `jarvis bench skills` measures the impact.
- **Architecture:** Local by default, cloud only when needed; a research strand
  ("Intelligence Per Watt") treats **energy, FLOPs, latency and dollars as
  first-class metrics** next to accuracy, with a public leaderboard. Continuous
  agents use memory compression + retrieval for long-horizon monitoring.
- **Verdict:** The most serious project in the scan. It's a platform, we're a
  product — but its digest preset and skill-optimization loop are directly
  stealable product ideas.

### 3. sukeesh/Jarvis — 3,765★ · Python · last commit 2025-06-14 · QUIET (16 months, historically long-lived since 2017)
- **What it does:** A **non-AI** CLI personal assistant for Linux/macOS/Windows.
  ~120 tiny plugins: weather, places, sports, games (blackjack, Wordle),
  health calculators, unit converters, QR codes, stock/crypto, jokes, file
  organizing, network scans, speedtest, system info.
- **Cleverest idea:** **The plugin contract.** One decorator —
  `@plugin("helloworld")` on a function that gets `(jarvis, s)` — is the whole
  extension API; a decade of community contributions flowed through it. Also
  the sheer proof that users love a long tail of tiny, instant, offline tricks
  that never need an LLM round-trip.
- **Architecture:** Monolithic CLI, plugin folders (`custom/` for user plugins),
  optional pyttsx3 voice. No wake word, no memory, no brain.
- **Verdict:** The "app store of small utilities" ancestor. v2's skill system
  is stricter and safer; sukeesh shows the *breadth* users eventually ask for.

### 4. Priler/jarvis — 2,994★ · Rust/Tauri · last commit 2026-02-18 · SLOW WIP (README self-declares outdated)
- **What it does:** 100% offline voice assistant in Rust: Vosk STT, Rustpotter
  wake word (Porcupine optional), TTS graveyard (Silero/Coqui/etc. all
  "currently not used"), NLU "nothing yet", Russian only.
- **Cleverest idea:** Honestly, the *negative* lesson: a from-scratch native
  rebuild spent years re-solving STT/TTS/wake-word plumbing and never reached
  an NLU. Validates v2's "wrap proven engines, spend effort on the brain"
  approach.
- **Verdict:** Privacy-purist experiment; nothing to steal except the warning.

### 5. isair/jarvis — 2,111★ · Python · last commit 2026-10-19 · VERY ALIVE, polished product
- **What it does:** Private local desktop assistant (packaged apps for
  mac/Win/Linux), Ollama or any OpenAI-compatible server, voice + text,
  MCP tools, nutrition tracking, screenshot OCR, location awareness.
- **Cleverest ideas (plural, this repo is dense):**
  1. **"A third person in the room."** While idle it keeps a short, *temporary
     rolling transcript* of nearby speech; address it by name anywhere in a
     sentence and "Jarvis, what do you think?" answers using the ongoing
     conversation — not just the last sentence.
  2. **System-wide dictation.** Hold a hotkey anywhere, speak, release → text
     pastes into the focused app. Filler-word removal, custom dictionary,
     dictation history, double-tap for hands-free.
  3. **Dual-model budgeting.** A small *fast model* handles voice intent/tool
     routing, a bigger chat model handles conversation; the setup wizard
     computes a combined memory budget for both + Whisper and warns honestly.
  4. **Memory as diary + knowledge graph** with a visual Memory Viewer;
     sensitive info redacted *before* it reaches the diary (same instinct as
     our DCL, applied to storage).
  5. **Task Centre** (queue prompts, follow/cancel) and **rewind a sent
     message** to regenerate chat from that point. **Low Power Mode** that
     skips warmup and shortens Ollama residency.
- **Verdict:** The closest thing to a shipping product in the field, and the
  single richest source of steals for v2. Different animal from the tutorial
  repos: fewer stars than HuggingGPT, ten times the product thinking.

### 6. ethanplusai/jarvis — 895★ · Python + TS · last commit 2026-09-07 · ACTIVE
- **What it does:** A voice front-end for Claude Code on macOS. Brainstorm by
  voice → the agreed design is written to a spec file → a real Claude Code
  session builds it plan → review → execute. Fish Audio voice, Three.js
  particle-orb UI, six-tab dashboard (Runs, Sessions, Memory, Specs,
  Projects, Usage).
- **Cleverest ideas:**
  1. **Session watcher with triage.** It watches *every* agent session on the
     machine; one blocked on a human is **announced out loud immediately**,
     mere completions are **batched into one sentence at the next pause**,
     and if no UI is open it falls back to an OS notification. (This is our
     proactivity call-ringing model pointed at agent jobs.)
  2. **Progress = reading the plan's checkboxes**, not asking the model how
     far it got.
  3. **Memory as a folder of plain Markdown files**, one fact per file, index
     always in context — human-readable, human-editable, no database.
  4. **Usage gauges** for the subscription's 5-hour / 7-day windows, and a
     **runs ledger** (SQLite: prompt, status, tokens, full event stream).
  5. A **taint gate**: anything read from web/file/screen marks the turn
     untrusted and acting tools are refused for the rest of that turn.
- **Verdict:** Narrower than v2 (one job: babysit coding agents) but the
  watcher/triage pattern and checkbox-progress trick are genuinely novel to us.

### 7. Gladiator07/JARVIS — 670★ · Python · last commit 2022-04-07 · **DEAD (4.5 years)**
- **What it does:** The canonical YouTube-tutorial JARVIS: PyQt GUI, ~25
  hardcoded features (greet, weather, calendar, email, WolframAlpha Q&A,
  YouTube, jokes, system status, screenshot with custom filename, **hide all
  files in a folder / unhide**, distance between places, notes in Notepad).
- **Cleverest idea:** None architecturally — its value is as a **feature
  checklist**: this is the exact list of tricks beginners ask a JARVIS for,
  i.e. proven demand.
- **Verdict:** Tutorial repo. 670★ measures tutorial reach, not quality.

### 8. akshayaggarwal99/jarvis-ai-assistant — 656★ · TypeScript · created 2025-11 · alive
- Mac voice assistant with dictation and an "Iron Man mode". Not deep-dived;
  noted because it independently converged on **dictation as the headline
  feature** (see isair) — two data points that dictation is what Mac/Windows
  users actually want daily.

### 9. AlexandreSajus/JARVIS — 528★ · Python · 2023-era
- **What it does:** The minimal cloud pipeline — Deepgram STT → GPT-3 →
  ElevenLabs TTS → Taipy web UI, with per-stage latency printed
  (transcribe 1.21s / generate 0.72s / synthesize 1.85s).
- **Cleverest idea:** *Printing stage latencies in the transcript* — instant
  honesty about where time goes; users forgive slow when they can see why.
- **Verdict:** A clean demo, superseded tech (GPT-3), but the latency
  transparency is a one-line steal for our GUI status line.

### 10. sosoj92/jarvis-assistant-vocal — 481★ · Python · 2026 · alive (French)
- Local voice assistant (Claude or Ollama) with **Philips Hue home control,
  OBS control, calendar, browser automation, Twilio phone calls**, and it
  *exposes itself as an MCP server*. Not deep-dived; noted for two gaps:
  smart-home control and outbound phone calls are things v2 has no path to
  today (v2's phone is Telegram-inbound).

### 11. GauravSingh9356/J.A.R.V.I.S — 1,423★ · Python · 2020-era tutorial fleet
- ~30 features: OCR, dynamic news, todo generator, dictionary with
  auto-spellcheck, weather incl. wind/humidity, YouTube download, Google Maps
  search. Same species as Gladiator07 — high stars, tutorial depth. Its OCR
  and todo skills appear in the gap list only as long-tail items.

### 12. Julian-Ivanov/jarvis-voice-assistant — 121★ · Python · 2026 · alive, obscure
- **What it does:** Windows assistant built (per its README) entirely with
  Claude Code. Claude Haiku brain, Web Speech API ears, ElevenLabs voice,
  Playwright browser automation, screen-vision Q&A.
- **Cleverest ideas:**
  1. **Double-clap wake** — clap twice and a whole *scene* launches: Spotify,
     VS Code, Obsidian, Chrome, windows auto-snapped into quadrants.
  2. **The greeting ritual** — on wake: weather + a humorous summary of your
     open tasks from Obsidian. A JARVIS that opens with a briefing feels alive.
- **Verdict:** Small repo, two genuinely charming product ideas (scenes,
  greeting briefing) that cost little to copy.

### 13. PanPenek/JarvisAi — 17★ · Python · last commit 2026-03-01 · obscure and the most v2-shaped of the hobby builds
- **What it does:** Fully offline Windows assistant: openWakeWord "Hey Jarvis",
  faster-whisper STT, Kokoro TTS, Ollama brain, **31 tools**, Iron-Man web HUD
  with live tool-execution panel, SQLite+ChromaDB memory, sliding-window
  context with **auto-summarization**.
- **Feature list worth diffing against ours:** `read_screen` (screenshot+OCR
  returning text *with coordinates*), `find_on_screen` (locate a button by its
  label text), media control, volume/brightness, clipboard get/set, toast
  notifications, **`set_timer`**, lock screen, power commands, `open_app`
  (30+ apps mapped by name), `delegate_task` (subtask to local LLM in
  parallel), wake-word-while-busy = stop.
- **Verdict:** 17 stars, more complete daily-driver tool coverage than repos
  with 100× its stars. Proof of the mission's premise: stars ≠ substance.

### 14. DawoodTouseef/J.AR.V.I.S. — 35★ · Python · 2025 · obscure
- **What it does:** PyQt5 desktop assistant (GPT-4o/LangGraph, mem0 memory,
  Porcupine wake word) with a **"Consciousness Module"**: camera analyzed every
  60s, screenshots every 120s, and **proactive spoken suggestions** from what
  it sees + live system monitoring (CPU/RAM/battery/network), e.g. "Battery
  critically low, sir."
- **Cleverest idea:** Proactivity driven by *system state*, not just time —
  low battery / high CPU as first-class interruption triggers, plus alternate
  run modes (`--coder` boots GPT-All-Star, `--interpreter` boots Open
  Interpreter) — one launcher, several personalities of work.
- **Verdict:** Rough hobby code, but its proactive triggers are exactly the
  watcher inputs our proactivity module doesn't consume yet.

### 15. eadmin2/jarvis_ai (Hermes HUD) — 194★ · Python · updated 2026-10-20 · alive
- **What it does:** A voice + holographic HUD *front-end* over NousResearch's
  Hermes Agent (which supplies memory, terminal, web, 80+ skills, cron).
- **Cleverest ideas:**
  1. **Agent-summoned display panels** — "show me a video of X, on screen"
     flies a media panel into the HUD; the agent drives the display through a
     plugin tool, and "clear the screen" sweeps panels away. The assistant
     presenting *on screen*, not just speaking.
  2. **Interrupt bookkeeping** — barge-in that knows exactly which sentences
     you heard vs didn't (we have the utterance record; they surface it in UI).
  3. HUD extras: machines panel (host CPU/GPU), per-day token/turn usage,
     ElevenLabs quota bar, LAN GPU "ears" sidecar (remote Whisper with local
     fallback).
- **Verdict:** Mostly a skin over someone else's agent — but the *display as
  a tool* idea is a real gap for v2's text-only GUI.

*Also scanned, not profiled: kalliope (1,785★ framework — "neurons + signals"
plugin model, same lesson as sukeesh), kishanrajput23 (1,005★, 2,542 forks —
the highest fork:star ratio here, a dead giveaway of a follow-along tutorial),
Dipeshpal/Jarvis_AI (411★, a pip module wrapping old TF/PyTorch intent
classifiers), SreejanPersonal/JARVIS-AGI (268★, "AGI" in the name, tutorial
underneath), Likhithsai2580 MARK-series (a one-author fleet of tutorial
forks), bertrandmbanwi/Jarvis (37★, "109+ tools" + desktop overlay + Chrome
extension), subhansh-dev/Jarvis-MT67 (10★ — clap detection, Telegram bridge,
flight finder, game updater; the long tail again), AKCodez/make-your-own-jarvis
(9★ — OpenRouter free brain + Fish Audio "real JARVIS voice", double-click
setup). Name-collision noise excluded: zouhir/jarvis (webpack dashboard),
JarvisArt (photo-retouching agent), defender (the arcade game), ctaylo21
(dotfiles), ascending-llc/jarvis-registry (enterprise MCP gateway).*

---

## 2. THE GAP LIST — what they have that v2 lacks, ranked

Ranking = owner value × ease inside a **stdlib-only Python** codebase.
(Ease assumes existing v2 machinery is reused; "stdlib" notes flag the trick.)

### Gap 1 — Timers, alarms & reminders you can set by voice/chat
*Seen in: PanPenek (`set_timer`), every tutorial repo, sukeesh.*
v2's clock skill only *tells* the time. There is no "remind me in 20 minutes"
or "timer for 10" — arguably the most-used real assistant feature on Earth.
**Sketch:** Add a `reminders` skill backed by the session store: `set_timer
(seconds, label)`, `remind_at(iso_time, text)`, `list_pending`, `cancel(id)`.
A single daemon thread sleeps to the nearest due item (condition variable,
recomputed on every insert — pure stdlib `threading`). On fire: emit a
session event, speak via the existing TTS path, and route through the
proactivity call-ringing model so a reminder *rings like a call* instead of
blurting. Persist due items as session-store events so a restart replays and
re-arms them (the store already does crash-replay; never re-execute, just
re-schedule). ~200 lines + tests.

### Gap 2 — Morning digest / daily briefing
*Seen in: OpenJarvis (flagship preset), Julian-Ivanov (greeting ritual),
isair ("help me think through my day").*
v2 has proactivity plumbing but no *digest product*: nothing that opens the
day with "here's your weather, your notes, what you were working on."
**Sketch:** A `digest` skill + a scheduled trigger: compose from skills v2
already owns — clock (date/time), notes (open items), memory (yesterday's
episodes + standing facts), knowledge (nothing), web (weather via the
existing web skill's fetch of a no-key weather endpoint, e.g. wttr.in JSON).
The brain summarizes with a fixed FLAN-style template, self-critique pass
already exists to keep it honest. Delivery: spoken on first wake of the day
(Julian-Ivanov's ritual) and on demand via `/digest`. Store a "last digest
date" fact in memory so it fires once per morning. All composition is
stdlib (`urllib`, `json`); the only new machinery is the schedule check on
session start. ~250 lines.

### Gap 3 — System-status skill + system-driven proactivity
*Seen in: PanPenek (`get_system_info`, volume/brightness), DawoodTouseef
(Consciousness Module), Gladiator07 (system status), eadmin2 (machines panel).*
v2's PC control can *act* on the machine but cannot *report* on it: no CPU /
RAM / disk / battery snapshot, and the proactivity watcher ignores the
machine's own distress signals.
**Sketch:** A `sysinfo` skill (tier-1 read): disk via `shutil.disk_usage`
(stdlib), RAM/CPU/load via `ctypes` calls to `GlobalMemoryStatusEx` /
`GetSystemTimes` on Windows (GetTickCount for uptime), battery via
`GetSystemPowerStatus` — all stdlib `ctypes`, no psutil. Return a compact
dict the brain can narrate ("disk 92% full" beats raw numbers — let the
brain phrase it). Then wire two watcher rules into proactivity: battery
< 15% and disk < 5% free become *urgent-enum* triggers (they fit the
existing closed urgent list's spirit: hardware distress ≈ disk_failing).
~180 lines + a fake-backend test seam mirroring pc_control's.

### Gap 4 — "What's on my screen?" — screenshot → vision Q&A skill
*Seen in: PanPenek (`read_screen`/`find_on_screen` with OCR coordinates),
Julian-Ivanov (Claude Vision describe), DawoodTouseef (screenshot analysis),
isair (screenshot OCR tool).*
v2's screen watching is a safety watcher (RAM-only, off by default) and
pc.observe reads the UIA tree — but the owner cannot simply *ask* "what's on
my screen / where's the Save button?" and get an answer.
**Sketch:** A `screen_ask` skill: capture via the existing pc_control
screenshot path (RAM-only, never disk — keep the standing rule), downscale,
base64 it, and send it as an image part through the existing FallbackChain
to a vision-capable provider already in the chain (Gemini/Pollinations
presets accept image input via the OpenAI-compatible endpoint — extend
`llm_compat` message building with an optional image part; Ollama models
without vision honestly decline via the chain). DCL note: screenshots are
PERSONAL by default — classify before any off-machine call, exactly like
message redaction today, and the gate treats it tier-2. For "find the Save
button," v2's UIA tree already returns labeled elements with bounds —
answer from UIA first, pixels only as fallback (the standing UIA-first
doctrine). ~220 lines, mostly provider plumbing.

### Gap 5 — Push-to-talk dictation into any app
*Seen in: isair (headline feature), akshayaggarwal99 (converged on it),
OpenJarvis-adjacent Wispr-style workflows everywhere in 2026.*
v2 can talk and listen in its own window, but cannot *type for you* into
Word, the browser, an IDE — the single most repeated daily use of voice AI.
**Sketch:** A dictation mode in the voice loop: a global hotkey (Windows
`RegisterHotKey` via `ctypes` — stdlib) starts capture, release stops;
STT text passes a pure-Python cleanup (filler-word removal list, spoken
punctuation: "comma"→",", "new line"→"\n", a user custom-dictionary JSON
for names/jargon — isair's three tricks, all string ops), then the text is
*pasted*, not typed: set clipboard (`ctypes` OpenClipboard/CF_UNICODETEXT)
+ send Ctrl+V through the existing pc_control key path — faster and safer
than synthetic keystrokes, and it flows through the gate as a tier-2
`pc.type`-class action with the dictated text as the auditable payload.
Dictation history = last N dictations in the session store. ~200 lines.

### Runners-up (real, ranked below the five)
6. **Watch-my-jobs notifier** (ethanplusai): register a long process (model
   pull, render) with the proactivity engine; blocked/finished → ring;
   completions batched. Needs a job registry; medium effort.
7. **Open-app-by-name + media control skill** (PanPenek, all tutorials):
   fuzzy app launch via Start-Menu shortcut scan (`os.scandir`, stdlib) and
   media keys via pc_control. Easy; folded into sysinfo-style utility skill.
8. **Usage meter** (ethanplusai gauges, Hermes quota bar, OpenJarvis
   per-watt): count tokens/calls per provider per day in the FallbackChain,
   show in GUI status + `/usage`. Easy, builds trust ("which brain answered
   and what it cost").
9. **Scenes / workspace rituals** (Julian-Ivanov): named bundles — "start
   work" = open these apps + play digest. Easy once Gap 2 + runner-up 7 land.
10. **Rolling ambient transcript** (isair): 30-second rolling buffer so
    follow-ups resolve against room context. Powerful but privacy-sensitive;
    v2's RAM-only/off-by-default watcher doctrine would govern it.
11. **Skill self-benchmark** (OpenJarvis `bench`/`optimize`): run the
    Hinglish golden set + per-skill evals as a `/bench` dev command; cheap
    version = pytest-style runner over stored cases. Dev-facing value.
12. **Concise tool instructions** (microsoft EasyTool): rewrite skill
    manifests' descriptions into terse imperative form; measurable tool-pick
    gains for the 7B local brain. Nearly free — an editing pass, not code.
13. **Long tail of tiny skills** (sukeesh/Gladiator fleets): weather with
    wind/humidity detail, news headlines, jokes, unit conversion, QR codes,
    hide-folder. Each ~40 lines via existing web skill; add opportunistically.
14. **Display-as-a-tool** (eadmin2 panels): "show me X on screen" needs a
    richer GUI than v2's tkinter chat; defer until a HUD exists.
15. **Smart-home + outbound calls** (sosoj92: Hue, Twilio): needs accounts/
    hardware the owner hasn't asked for; note and skip.

### Explicitly NOT gaps (we're ahead — don't copy backwards)
- **Permissions/approvals:** no scanned repo has anything like the gate +
  HMAC tokens + DCL + verifier. ethanplusai's taint gate is the closest and
  is coarser. **Do not** import their "the agent just runs it" posture.
- **Memory integrity:** provenance tiers + quarantined tool/web memories +
  cryptographic-grade forget beat every diary/vector-store here, including
  mem0-based ones (theirs remember more; ours remember *safely*).
- **Echo-proofing/barge-in bookkeeping:** v2's utterance record discipline
  matches or beats the Hermes HUD's.

---

## 3. Honesty box

- **Stars lie in both directions.** microsoft/JARVIS's 25k★ is a paper's
  citation count, not an assistant's user base; its feature development
  stopped in Jan 2024. kishanrajput23's 1,005★ comes with 2,542 forks —
  a follow-the-video tutorial. PanPenek's **17★** repo has more daily-driver
  substance than either.
- **Dead/quiescent, named:** Gladiator07 (2022), microsoft/JARVIS (feature-
  frozen 2024), JARVIS-ChatGPT (archived), Melissa-Core (archived), sukeesh
  (quiet since 2025-06, not dead), Priler (WIP forever).
- **"updated_at" was not used** for aliveness anywhere above; commit dates
  were checked for the top repos, README "What's New" sections for the rest.
- Two repos named in searches (zouhir/jarvis webpack dashboard, JarvisArt)
  are not assistants at all and were excluded rather than counted.
- READMEs are marketing surfaces: features above are as *claimed* in
  READMEs (code was spot-checked via structure listings for PanPenek and
  ethanplusai, not executed). Treat "31 tools"-style counts as ±20%.
