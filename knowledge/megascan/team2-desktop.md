# MEGA-SCAN TEAM 2 — Desktop / Windows JARVIS Repos, Reverse-Engineered

**Method:** implementation files read in full (entry points, dispatchers, OS-call sites), not READMEs — except where blocked (marked).
**Deep code-level reads: 17 repos.** Structure-only (GitHub MCP hit HTTP 429 mid-run — hard stop, nothing invented): 7 repos. README/triage: ~11 more. Total touched: ~35.

**⚠ Blocked slices — flagged, NOT filled in from genre knowledge:**
- **Group A** (LYiHub/pub-local-jarvis, Julian-Ivanov/jarvis-voice-assistant, bertrandmbanwi/Jarvis, Surajkumar5050/zyron-assistant) — directory listings only. Retry checklist in [team2A-screen-auto.md](sandbox://workspace/jarvis-knowledge/megascan/team2A-screen-auto.md).
- **Group E** (showlab/WorldGUI, kishanrajput23/Jarvis-Desktop-Voice-Assistant, kumar045/Control-PC-Terminal) — root listings only; the kishanrajput23 exhaustive tool inventory was **not obtained** and must be re-run after the rate limit resets. Retry plan in [team2E-bench-classics.md](sandbox://workspace/jarvis-knowledge/megascan/team2E-bench-classics.md).

Full traces live in the group files: [B — remote/server](sandbox://workspace/jarvis-knowledge/megascan/team2B-remote-server.md) · [C — voice assistants](sandbox://workspace/jarvis-knowledge/megascan/team2C-voice-assistants.md) · [D — new agents](sandbox://workspace/jarvis-knowledge/megascan/team2D-new-agents.md). Below: the condensed inside-trace per repo + the two deliverables (top mechanisms, tool list).

---

## 🏆 TOP 5 MECHANISMS (from code, ranked by steal-value for v2)

**1. Two-tier dispatch: immediate read-only vs confirmation-gated mutating** — techgniouss/pdagent, `gemini_actions.py:dispatch_gemini_tool` + `ai_tool_loop.py:run_tool_turn`. Read-only tools (read file, screenshot, clipboard view, window list) execute instantly; *every* mutating tool is parked in an expiring pending-store behind an Approve/Cancel prompt. Bolted to it: **tool-name alias normalization** — a deterministic map repairs whatever tool name/arg keys the LLM hallucinates *before* the strict allowlist check. Pure logic, ports 1:1 to stdlib Python.

**2. The hard floor no autonomy mode can override** — talmetis-labs/aizen, `src/agent/cmd_guard.rs:classify`. A small deterministic regex classifier: `Blocked` (catastrophic shapes: `rm -rf /` incl. quote-smuggled spellings, `mkfs`, `format C:`, fork bomb, `curl|sh`) applies **even under yolo**; `Caution` (history-rewriting git) always prompts; `Allow` for provably read-only shapes. Checked against the whole command string plus a quote-stripped copy. Layer it *under* mechanism 1.

**3. Click by element, not by pixel + verify→escalate ladder** — aivrar/portable-hermes-agent (upstream hermes), `tools/computer_use/`. SOM capture = screenshot + numbered interactable overlays + accessibility tree → model clicks an **element index**; an `ax`-only lane lets even non-vision models drive GUIs. Input is delivered **background-first** (pid/window-targeted, no focus theft), and every action returns a structured verdict (`verified`/`effect`/`escalation`) that climbs background → pixel coords → foreground-with-approval. (Also in hermes: **AST-based tool self-discovery**, `tools/registry.py:discover_builtin_tools` — scan `tools/*.py` for `registry.register(...)`, pure stdlib `ast`+`importlib`, zero hand-maintained tool lists.)

**4. Local-intent-first routing** — dmrr35/Open.Jarvis, `commands/local_intent_router.py:route_local_intent` + `commands/groq_router.py`. The common ~80% of commands (open app, time, battery, window control, media) are answered by deterministic string tables with **zero LLM calls** — instant, free, offline, can't hallucinate. The LLM is demoted to a JSON-action translator (`{"action","params","response"}`) for the long tail, and its output is **schema-validated** (`commands/action_schema.py:validate_action_payload`) before execution. Cleanest small-assistant architecture in the scan. (Independent cousin: Melissa-Core's SQLite **word-group intent engine** — scored matches, ×1.5 order bonus, priority tie-break, DB-extensible without code.)

**5. The app-launch ladder** — assembled from three repos that each hold one rung: (a) **SQLite name→path registry + `os.startfile`** (Avinashb722 `engine/db.py`/`features.py:openCommand`; same table in ankitpathak62/Jarvis-2025 `backend/db.py`) — user-editable, no shell, stdlib-only; (b) **Get-StartApps catalog** via one PowerShell one-liner (pdagent `app_catalog.py`, win32com `Get-StartApps`) — covers Store apps; (c) **Start-Menu search fallback** (RustamovAkrom `actions/open_app.py:_launch_windows` stage 3: press Win, type name, Enter) — works for any installed app with zero path knowledge. Together they replace every hardcoded exe path in the genre.

**Honorable mentions:** Rider-Pc's **expiring command envelope** (generation + seq + ts + ≤500 ms TTL; stale commands refused, stale snapshots fail-closed to read-only) · hyperclaw's **pairing-code onboarding** (8 unambiguous chars, 1 h expiry) + **invisible-Unicode sanitization** of approval prompts · ehteshambuildagents' law: **classify read vs write at the dispatch boundary; never confirm over voice** (`bridge/server.mjs`) · OpenCowork's **temp-.ps1-file trick** (write script, `powershell -File` it — kills quoting hell) + realpath/symlink containment · pdagent's **missed-task grace** (a one-shot task overdue >600 s is skipped and reported, never run late — a shutdown scheduled for last night must not fire at boot).

---

## 🧰 SMALL TOOLS v2 SHOULD ADD (full inventory, all verified in code)

v2 already has: pc.observe, pc.screenshot, pc.click, pc.type, pc.key, pc.shell, reminders. The gaps below are what the field ships and v2 lacks — each with its proven mechanism:

**App & window**
1. `app.launch` by name — SQLite registry → Get-StartApps catalog → Start-Menu search fallback (mechanism 5 above)
2. `window.list` — enumerate open windows/titles (pdagent `list_open_windows`, pywinauto)
3. `window.focus` by title — WScript.Shell `AppActivate` via PowerShell (Rustamov `_focus_window`)
4. `window.minimize_all` / show desktop — `win+d` (Open.Jarvis)
5. `window.close` — `alt+f4` helper (Open.Jarvis)

**System settings (the two real Windows APIs in the whole genre)**
6. `volume.get` / `volume.set` / `volume.mute` — pycaw `IAudioEndpointVolume` for true 0–100 values (Rustamov/Anubhav); cheap path: media keys `VK_VOLUME_UP/DOWN/MUTE` via ctypes `keybd_event` (stdlib). **Get-before-set makes volume undoable** (`core/undo.py` pattern: record before-value, restore after)
7. `brightness.get` / `brightness.set` — WMI `WmiMonitorBrightness[Methods]` via PowerShell `-Command` (Anubhav/Rustamov) — no `wmi` package needed

**Clipboard & input**
8. `clipboard.get` / `clipboard.set` (pdagent `view_clipboard`/`set_clipboard`, pyperclip) — read instant, write gated
9. `type_long_text` — paste-via-clipboard for text >20 chars instead of char-by-char typing (Rustamov `_smart_type`: Ctrl+A/Delete clear, pyperclip + Ctrl+V) — faster and keyboard-layout-proof

**Vision & clicking**
10. `screen.find_text` + `screen.click_text` — OCR (Tesseract) scored text match → click coordinates (pdagent `automation_utils.py:find_text_in_image`). ⚠ pdagent leaves text-clicks *ungated* — v2 should gate them like coordinate clicks
11. `screen.click_vision` — screenshot → vision model → "ONLY x,y" → regex-parse → click (Rustamov `_screen_find`) — the no-UIA fallback v2's OCR plan complements

**Status & power**
12. `system.status` — battery %, RAM, CPU spoken/reported (Open.Jarvis via psutil; stdlib path: ctypes `GetSystemPowerStatus`)
13. `power.lock` — `rundll32 user32.dll,LockWorkStation` (Open.Jarvis)
14. `power.sleep` — `rundll32 powrprof.dll,SetSuspendState` (pdagent/Open.Jarvis) — gate as destructive
15. `power.shutdown` / `power.restart` — `shutdown /s|/r /t 5` (both) — destructive-gated, with pdagent's missed-task grace so a stale schedule never fires late

**Productivity glue**
16. `screenshot.save` — screenshot → `%USERPROFILE%\Pictures` + Explorer select (Open.Jarvis; v2's screenshot is RAM-only by design — an explicit *save* variant is the missing piece)
17. `macro.replay` — typed action sequences (hotkey/clipboard/findtext/click) persisted as JSON, replayed with **no shell** (pdagent `command_registry.py:CommandAction`)
18. `scheduler` — disk-persistent scheduled tasks polled on an interval (pdagent `scheduler_registry.py` + missed-task grace)
19. `web.open_url` — scheme-validated (http/https only) URL open (Open.Jarvis `integrations/url_safety.py:normalize_web_url`)

---

## PER-REPO — HOW IT ACTUALLY WORKS (inside)

### Group B — remote-control / server ([full traces](sandbox://workspace/jarvis-knowledge/megascan/team2B-remote-server.md))

**techgniouss/pdagent** (15★, ALIVE, MIT) — Telegram long-poll (`main.py:main`, PID lock, `wakepy` anti-sleep) → every handler wrapped in `handlers/_shared.py:safe_command` (fail-closed auth + private-chat-only + token-bucket rate limit) → plain text to `ai_router.py` → Gemini 10-turn loop (`gemini_client.py`) → `ai_tool_loop.py:run_tool_turn` (alias-normalize → `ALLOWED_TOOLS` frozenset) → `gemini_actions.py:dispatch_gemini_tool` two-tier (read-only instant / mutating parked behind Telegram Approve-Cancel) → pyautogui/pywinauto/Tesseract; remote desktop = aiohttp MJPEG viewer + cloudflared, token-only auth. **Weaknesses:** OCR text-clicks + screenshots execute ungated; `pyautogui.FAILSAFE=False` during typing; remote-desktop URL token is the *entire* auth. **Steal: YES — the dispatch spine; highest-value of the group.**

**mpieniak01/Rider-Pc** (11★, ALIVE, MIT) — Not a PC controller: FastAPI console on the PC *proxies* to a Raspberry-Pi robot, the sole executor. `api/routers/control_router.py` → envelope check (`core/remote_safety.py`: generation+seq+ts+TTL≤500 ms) → `RestAdapter.post_control` → Pi. **Clever:** freshness discipline; everything fail-closes toward read-only; `stop`/`estop` bypass the contract pre-flight by design. **Weaknesses:** zero authentication, binds `0.0.0.0`, CORS `*`+credentials, mTLS silently falls back to plain HTTP, mock state baked into production app. **Steal: the expiring-envelope pattern only.**

**mylo-2001/hyperclaw** (12★, DORMANT Mar 2026, MIT) — OpenClaw re-implementation (TS). Node gateway (`packages/gateway/src/server.ts`, HTTP+WS :18789) → `runAgentEngine` → `packages/core/src/agent/pc-access.ts`: `run_shell` = raw `child_process.exec` of model output; "remote PC nodes" are bookkeeping — execution always happens on the gateway machine. **Clever:** destructive gate for channel sessions + invisible-Unicode sanitization of approval prompts; pairing-code onboarding. **Worst line in the scan:** `src/bot/hyperclawbot.ts:isAllowed` returns `true` when the allowlist is empty — empty allowlist = any Telegram user can drive it. Gateway auth also opt-in (`if (!token && !auth) return true`). **Steal: patterns only (pairing, Unicode sanitization, background exec sessions).**

**talmetis-labs/aizen** (120★, ALIVE, Apache-2.0) — Serious Rust coding agent. REPL/`serve` daemon → 25-iteration tool loop with compaction + git checkpoints → shell/file tools under three layers: `cmd_guard.rs` hard floor (even yolo can't override) → approval tiers (ask/smart/yolo) → OS sandbox (Landlock/Seatbelt). Remote = hand-rolled Telegram `getUpdates` with **backlog-skip on boot** (`backlog_offset()`), per-chat lanes, deny-on-timeout (300 s) approvals. **Weaknesses:** RCE-by-design resting entirely on the Telegram allowlist; `/approval yolo` settable from chat itself; regex floor bypassable by two-step download-then-run. **Steal: patterns (hard floor, tiers, deny-on-timeout, backlog-skip, per-conversation lanes).**

**dmrr35/Open.Jarvis** (30★, DORMANT May 2026, MIT) — Mic → continuous-STT wake (no real wake engine: 3-s chunks transcribed + substring match) → `commands/komutlar.py:process_command` → **local intent tables answer most commands with zero LLM calls** → Groq only as JSON-action translator → schema-validated `action_dispatcher.py` → pyautogui/subprocess (hardcoded app paths). **Weaknesses:** in-schema LLM actions (incl. arbitrary-coordinate clicks) run with **no confirmation** — `requires_confirmation()` is dead code; destructive gate is just an env var; anyone in earshot is authorized. **Steal: YES — the architecture (mechanism 4); wire the confirmation hook they left dead.**

**IRISX-AI/IRIS-AI** (218★, ALIVE on paper, custom source-available license) — Desktop automation is **vaporware**: Electron main (~200 lines, 2 files) registers **zero IPC handlers**; `registerSystemHandlers` is dead code; renderer's `open-app`, `secure-save-keys`, `adb-*` invokes go nowhere; telemetry includes `Math.random()` temperature/network numbers. No input-automation library exists in the repo. **Steal: NO** (nothing implemented; license forbids copying anyway). The `Get-StartApps` one-liner inside its dead code is public PowerShell knowledge — take it from pdagent.

### Group C — voice assistants ([full traces](sandbox://workspace/jarvis-knowledge/megascan/team2C-voice-assistants.md))

**RustamovAkrom/JARVIS** (79★, ALIVE, proprietary) — The group's real substance: Gemini function-calling over a **self-describing TOOL-dict auto-discovery registry** (`core/action_loader.py:discover_actions` imports + *validates* every `actions/*.py` — drop in a file, get a tool). pyautogui dispatch (`computer_control.py`), vision-grounded clicking (`_screen_find`: screenshot → Gemini → "ONLY x,y" → regex → click), pycaw volume with an **undo system** (readable before-values), WMI brightness, 3-stage app launch ending in Start-Menu search. **Weaknesses:** `shell=True` with raw LLM-supplied app names; PowerShell title interpolation injection; plaintext API keys; an `exec` sandbox exposing ctypes; a `random_data` action that *invents fake identity data* for form-filling. **Steal: YES — registry pattern, launch ladder, media-key volume (ideas; proprietary license).**

**MAL19INDUSTRIES/JARVIS-OS-V.2** (113★, ALIVE, MIT) — Rebranded sibling of the Rustamov action codebase + the group's only true **plan→execute→replan agent loop** (`agent/planner.py` JSON plan → `agent/executor.py` → `replan()` on failure, step results threaded forward). **Most dangerous pattern in the scan:** `executor.py:_run_generated_code` — the LLM writes a Python program (instructed to pip-install what it needs) and it runs **unattended**; plus a second in-process `exec` path. **Steal: the planner/executor shape (MIT — liftable); NEVER the ungated code-exec.**

**Avinashb722/jarvis-ai-assistant** (133★, ALIVE, MIT) — Tutorial skeleton (`engine/command.py` elif chain) bloated sideways into ADB phone/WhatsApp automation (fixed-coordinate clicks, hardcoded `C:\platform-tools\adb.exe`). Face rec = obsolete Haar+LBPH (fooled by a photo). Committed `passwords.json`/`password_key.key` in repo root. **Steal: YES — its one gem, the SQLite app registry + `os.startfile` (see mechanism 5).**

**AnubhavChaturvedi-GitHub/jarvis-ai-assistant** (365★, ALIVE, GPL-3.0, tutorial clone) — webscout/Phind scraped-endpoint "brain" + if/elif Hinglish router. Its primary app-open path is `subprocess.run(raw voice text)` — arbitrary command execution as a feature. Only real Windows APIs: pycaw volume, WMI brightness. **Steal: ideas only (GPL); the WMI-via-PowerShell path is public knowledge.**

**Melissa-AI/Melissa-Core** (499★, DEAD since 2018, MIT) — Python 2 chatbot; essentially **zero Windows control** (a USB blink(1) LED action is its "lighting"). Its one gem: the SQLite word-group intent engine (mechanism 4, honorable mention). Shell injection via filename interpolation in `play_music.py`. **Steal: the intent-engine pattern, in stdlib `sqlite3`.**

**Shokr/JARVIS** (79★, DEAD 2021, no license) — 103-line toy: exact-match dict of 7 hardcoded exe paths + blocking `subprocess.call`; **hardcoded Gmail credentials (`Pass@123`) in source**; dead broken code below `main()`. **Steal: NO.**

**ehteshambuildagents/jarvis** (23★, ALIVE, MIT) — Different species: the hologram is *real* Three.js (phase-driven reactor — spins harder while tooling), and there is **no first-party control code**: control is delegated to an embedded Claude Code session via a Node bridge. Its engineering is the safety layer: every tool call classified read-vs-write at the bridge boundary (verb-anchored, per-server), writes refused unless `JARVIS_ALLOW_WRITES=1`. **Steal: the design law (classify at dispatch; never confirm over voice) — ports free to any Python dispatcher.**

### Group D — new desktop agents ([full traces](sandbox://workspace/jarvis-knowledge/megascan/team2D-new-agents.md))

**OpenCoworkAI/open-cowork** (2219★, ALIVE, MIT) — Electron shell over `@mariozechner/pi-coding-agent`. Three execution paths: **WSL2 bridge (Windows) / Lima VM (macOS)** with bidirectional file sync + virtual `/mnt` paths (the only real isolation in this group); `NativeExecutor` fallback running PowerShell on the host behind a *bypassable regex denylist*; pi-agent bash tool. Tools: fs read/write, webFetch, webSearch = DuckDuckGo Instant Answers (near-useless). **Steal: temp-.ps1 trick + realpath containment (stdlib-portable); the denylist is a cautionary tale — use allowlists.**

**aivrar/portable-hermes-agent** (235★, ALIVE, MIT) — Thin portable packaging (START.bat + embedded Python 3.13) of upstream hermes-agent. Substance: ~150 self-registering tool modules via **AST discovery**; `terminal_tool` with 7 backends (default = unsandboxed local subprocess); `computer_use` via MCP-over-stdio to an external cua-driver (SOM/element-index, background-first, verdict ladder — mechanism 3). **Weaknesses:** write-approval gate defaults OFF; sudo passwords cached in-process; computer-use depends on a binary not in the repo. **Steal: AST discovery pattern + SOM/verdict design (MIT, but heavy — take patterns).**

**skalesapp/skales** (2200★, ALIVE, proprietary EULA) — **No code exists to read**: distribution shell only (README/CHANGELOG/docs); README admits the v7 source snapshot was removed and "no source code is provided or promised." Unauditable by design. **Steal: NO** — doc-level ideas only (goal queue, folder-bind-with-undo).

**ankitpathak62/Jarvis-2025** (143★, DEAD Feb 2025, no license) — Tutorial bot (eel + Porcupine + Haar face auth). Its "control all function of my system" claim is **false** — zero volume/brightness/shutdown code in the repo. Dispatch = substring matching into sqlite registry → `os.startfile`, falling through to `os.system('start ' + query)` (voice command injection); WhatsApp via blind pyautogui tab-counting; hardcoded `C:\Users\patha\...` path; committed venv. **Steal: only the sqlite name→path/url registry pattern.**

### Blocked — structure only, code NOT read (retry after GitHub rate-limit reset)

**LYiHub/pub-local-jarvis** (516★, ALIVE) — Architecturally the most serious-looking in the slice: Electron shell + Python backend + **native C++ sensing** (`native/src/worker.cpp` 58 KB, `omni_runtime.cpp`, `audio.cpp`, `scheduler.cpp`, `protocol.cpp`, `native/src/windows/`) — screen sensing is native code, not pyautogui. Not stdlib-stealable even if read; architecture (privacy-mode gate, scene policy) might be.
**Julian-Ivanov/jarvis-voice-assistant** (121★, ALIVE, **no LICENSE**) — Tiny flat Python: `server.py` (12.7 KB dispatch) + `browser_tools.py` (5.2 KB, entire browser core) + `screen_capture.py` (1.3 KB — thin screenshot wrapper, no OCR engine fits). Most promising lightweight steal candidate — TO VERIFY.
**bertrandmbanwi/Jarvis** (37★, ALIVE) — Heaviest engineering signals: `jarvis/` + `skills/` plugins, `evals/`+`tests/`, Docker, 294 KB CI lockfile, macOS `.plist` — looks server/cross-platform, not Windows-native.
**Surajkumar5050/zyron-assistant** (122★, ALIVE) — Windows-native launch (`setup.bat`, `run_silent.vbs`) + browser control via **dual companion extensions** (Chrome + Firefox) — the extension-bridge (DOM work in the extension, assistant talks to it) is the structural steal candidate over fragile pyautogui/Selenium clicking.
**showlab/WorldGUI** (126★) — PC-control benchmark; agent core is "GUIThinker" (`agent/` package + `test_guithinker_*.py` entry points) — internals unread.
**kishanrajput23/Jarvis-Desktop-Voice-Assistant** (1005★) — the canonical tutorial build; code in `Jarvis/` subdir, 89-byte requirements.txt. **Exhaustive tool inventory NOT obtained — re-run required.**
**kumar045/Control-PC-Terminal** (10★) — single self-contained 21.6 KB `control-terminal` script + `custom-agents.conf` (config-driven agents) + `install.sh` — everything lives in one file, unread.

### Triage one-liners (README/structure level)
- **isair/jarvis** (2111★, ALIVE) — covered in a prior RE cycle: Recall Gate memory check; hold-to-talk dictation. Custom non-commercial license — ideas only.
- **RealDealCPA-VR/Iron-Jarvis** (63★, ALIVE, Apache-2.0 + Commons Clause) — Electron + Next.js + FastAPI daemon agent-OS; desktop control via a paired browser add-on + tray hotkeys (Ctrl+Shift+J); an agent platform, not a desktop-control implementation.
- **jev-chat/jev-chat-jarvis** (7923★, Kotlin) — chat-reading reply assistant, not a desktop controller. Out of slice.
- **phord/Jarvis** (483★, C++) — hacks a Fully standing desk. Not an AI. **Loki-Xer/jarvis** (99★) — WhatsApp bot. **tranvictor/jarvis** (81★, Go) — Ethereum automation. **cranklin/Jarvis** (122★, PHP) — Google TTS/STT toy. **MultiX0/jarvis** (23★, Dart) — HUD viewer for a remote Hermes agent. **Aryan-0001/Jarvis-AI** (125★, Dart) — mobile/desktop app shell. **krrish612/jarvis-linux** (6★) — "600+ agents" claim, Linux, unverified. **rajatsaxena/Jarvis-GUI** (12★) — hand-gesture system control (niche input channel).

---

## Bottom line for v2
The genre's real control stack is boring and convergent: **pyautogui + two Windows APIs (pycaw volume, WMI brightness) + Start-Menu search**. Nobody serious hardcodes exe paths anymore — they use a registry/catalog + search fallback. The differentiators worth building are all *safety and reliability* mechanisms, and they're all small: two-tier gated dispatch with alias normalization (pdagent), a hard floor under every autonomy mode (aizen), local-intent-first routing with schema-validated LLM actions (Open.Jarvis), element-index clicking with a verdict ladder (hermes), and the launch ladder (registry → catalog → search). The anti-patterns to never copy: ungated LLM-written code execution (MAL19), empty-allowlist-equals-everyone (hyperclaw), dead confirmation hooks (Open.Jarvis), and UI-first vaporware (IRIS-AI).
