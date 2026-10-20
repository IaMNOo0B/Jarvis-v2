# Team 2D — Reverse-Engineer Strike: New Desktop Agents + System Control

Method: read the actual implementation files via GitHub MCP (`get_file_contents`), not READMEs.
File:function refs are exact. Confidence: [VC] = verified in code, [HC] = high (structure implies),
[MC] = medium (not opened, inferred). Cutoff note: repo "stars" per mission brief.

---

## 1. skalesapp/skales (~2200★, ALIVE & very active, proprietary — closed source)

- What it claims / what it is: "The private AI that lives on your computer and does real work" — goal-driven
  cross-platform personal agent (Windows/macOS/Linux/Android/iOS), 15+ LLM providers or offline Ollama.

- HOW IT ACTUALLY WORKS (inside): **There is no code to read.** [VC] The repository root contains only
  `.gitignore`, `CHANGELOG.md` (119 KB, v12.9.55), `LICENSE`, `COMMERCIAL-LICENSE.md`, `SECURITY.md`,
  `PROOF_OF_AUTHORSHIP.md`, install guides, `docs/` (marketing images + a 523 KB HTML guide). README states
  verbatim: *"This is where Skales is distributed: releases, the changelog, install guides and the issue
  tracker. Skales itself is proprietary and stays proprietary… A v7 source snapshot stood here until
  12.9.30 and was removed with that release. Its last code commit was 26 July 2026."* The `LICENSE`
  is a custom EULA v1.2 (14 Sep 2026): *"The Software is proprietary… it is not open source and it is not
  source-available. No source code is provided or promised."* Releases ≤12.9.27 kept the old Business
  Source Licence terms, but the snapshot was already 6+ months stale vs the shipped binary (their own
  admission: 138 TS files in the snapshot vs 984 in the actual build tree, 70 API routes vs 225).
  Capability claims from docs only [MC]: `/goal` background multi-step tasks, `/code` folder binding with
  inline diffs + one-click undo, Office task-pane + Chrome side-panel extensions, phone pairs via QR to
  drive the desktop's full toolset, migration importer from OpenClaw/Hermes/ChatGPT.

- Clever mechanism (from code): **N/A — nothing to extract.** Best documented ideas only: per-file
  folder binding with undo, background `/goal` runs that "pick up where they left off".

- Hidden weaknesses found in code: N/A, and that is itself the finding — unauditable. Their own history
  lesson: the stale public snapshot *drew four security reports about code the shipped application does
  not contain*, which is why they deleted it. Zero trust-but-verify possible.

- Stealable for a stdlib-only Python Windows assistant? **NO** — there is no implementation to steal.
  Only doc-level ideas (goal queue, folder-bind-with-undo), which we can design ourselves.

---

## 2. OpenCoworkAI/open-cowork (~2219★, ALIVE v3.3.1, MIT)

- What it claims / what it is: open-source Electron AI-agent desktop app (Windows/macOS) — "one-click
  install Claude Code, MCP tools, Skills with sandbox isolation, multi-model support". Under the hood it
  is a GUI shell around `@mariozechner/pi-coding-agent` (Claude-Code-style agent SDK) + MCP + Skills.

- HOW IT ACTUALLY WORKS (inside): [VC] entry = `src/main/index.ts` (109 KB) Electron main process;
  agent loop = `src/main/agent/agent-runner.ts` (127 KB) built on `pi-coding-agent` (`pi-session-runtime.ts`,
  `pi-model-resolution.ts`). Execution has three real paths:
  1. **Sandbox path (default, genuinely isolated):** Windows → `src/main/sandbox/wsl-bridge.ts` (35 KB)
     shells commands into a WSL2 distro via a compiled `wsl-agent` binary (`build:wsl-agent` compiles
     `src/main/sandbox/wsl-agent/`); macOS → `src/main/sandbox/lima-bridge.ts` + Lima VM. File ops sync
     both ways (`sandbox-sync.ts`, `wsl-sync.ts`, `lima-sync.ts`); the model sees virtual `/mnt/...`
     paths mapped to real host mounts by `src/main/sandbox/path-resolver.ts`.
  2. **Native executor:** `src/main/sandbox/native-executor.ts` `NativeExecutor.executeCommand()` runs on
     the HOST: on Windows it writes the command to a temp `.ps1` under `os.tmpdir()` (`oc-cmd-<Date.now()>.ps1`)
     and spawns `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File <script>` via
     Node `child_process.spawn`; POSIX: `/bin/bash -c`.
  3. **pi-agent bash tool:** `src/main/agent/windows-bash-operations.ts` `buildWindowsShellInvocation()`
     picks per-shell invocation — `cmd /d /s /c`, or PowerShell `-NoLogo -NoProfile -NonInteractive
     -ExecutionPolicy Bypass -Command <command>` — spawned with `windowsHide: true`; process trees killed
     via `taskkill /F /T /PID`.
  Tools exposed to the LLM: `src/main/tools/tool-executor.ts` `ToolExecutor` — `readFile`/`writeFile`/
  `listDirectory` via Node `fs`, `webFetch` (fetch, 15 s abort timeout, 20 000-char cap), `webSearch`
  (DuckDuckGo **Instant Answer API** — headline/abstract only, near-useless for real research), plus bash,
  bundled MCP servers (`scripts/bundle-mcp.js`), and Skills. Paths are gated by `PathResolver` /
  `assertInsideMount()` — realpath + symlink-escape check + mount containment; `validateCommandSandbox()`
  regex-blocks `..` traversal, absolute paths outside mounts, and a `dangerousPatterns` blocklist
  (`rm -rf /`, `curl|sh`, plus Windows: `format X:`, `del /s`, `reg add|delete`, `powershell -enc`,
  `Set-ExecutionPolicy`).

- Clever mechanism (from code): the WSL/Lima VM sandbox with bidirectional file sync and host-mount
  path virtualization is the only *real* isolation in this strike group; everyone else just shells out.
  The temp-`.ps1`-file trick in `native-executor.ts` is a neat stdlib-stealable workaround for
  PowerShell quoting hell (write script to file, `-File` it, delete after).

- Hidden weaknesses found in code: [HC] the command guard is a **string-regex denylist** — bypassable by
  construction (`$env:` expansion, `powershell -e` vs `-enc` spacing variants, `python -c`, encoded
  commands); security quality depends entirely on which executor path is active, and `NativeExecutor`
  runs on the host with only that regex between the model and the machine; `webSearch` = DDG Instant
  Answers (crippled research); 127 KB agent-runner + 109 KB index.ts monoliths; ships `ngrok` dep
  (remote-access surface).

- Stealable for a stdlib-only Python Windows assistant? **PARTIALLY yes**: (a) the temp-`.ps1` + 
  `-ExecutionPolicy Bypass -File` pattern maps 1:1 to Python `subprocess` + `tempfile` (stdlib-only);
  (b) the path-containment pattern (`realpath` + symlink-escape check + workspace root prefix test) is
  stdlib-portable via `os.path.realpath`; (c) the denylist regex gate is a cautionary example — don't
  copy, replace with an allowlist. WSL isolation itself: `wsl.exe` is callable from stdlib `subprocess`,
  but their sync machinery is not trivially portable.

---

## 3. aivrar/portable-hermes-agent (~235★, ALIVE, MIT — portable fork of NousResearch/hermes-agent)

- What it claims / what it is: "100 tools, GUI, local" Windows-portable Hermes Agent. The fork's own
  delta is thin: `START.bat` + `install.bat` + embedded portable Python 3.13 (`python_embedded\python.exe`,
  nothing installed system-wide), `HERMES_HOME=%USERPROFILE%\.hermes`, launch `gui/app.py` if present
  else `cli.py`. Everything substantive is upstream hermes-agent.

- HOW IT ACTUALLY WORKS (inside): [VC] entry = `cli.py` (1 MB prompt_toolkit REPL; `hermes_bootstrap`
  first import forces UTF-8 stdio on Windows). Tool dispatch = `tools/registry.py`: `discover_builtin_tools()`
  **AST-scans every `tools/*.py`** for top-level `registry.register(...)` calls and imports them —
  zero manual tool lists; each module self-registers `name/schema/handler/check_fn/toolset`. ~150 tool
  modules (the "100 tools" claim is conservative). Shell = `tools/terminal_tool.py` (190 KB):
  `TERMINAL_ENV` picks backend — `local` (direct `subprocess` on host, default), `docker`, `modal`,
  `vercel_sandbox`, `ssh`, `singularity`, `daytona` — with background tasks, interrupt polling, and a
  per-session sudo-password cache. Computer control = `tools/computer_use/` package, one consolidated
  tool: `computer_use_tool.py` is a registration shim; `schema.py` `COMPUTER_USE_SCHEMA` exposes
  actions `capture/click/double_click/right_click/middle_click/drag/scroll/type/key/set_value/wait/
  list_apps/list_windows/focus_app`; `backend.py` `ComputerUseBackend` is the abstract interface;
  `cua_backend.py` (184 KB) speaks **MCP over stdio to an external `cua-driver` binary** (trycua, not in
  repo). Capture modes: `som` (screenshot + numbered interactable overlays + AX tree → model clicks by
  **element index**, not pixels), `vision`, `ax` (tree-only for text-only models). Delivery is
  **background-first**: input routes to pid/window id without stealing focus/cursor (macOS via SkyLight
  private SPIs); each `ActionResult` carries a machine-readable `verdict` (`verified`/`effect`/
  `escalation`) implementing a verify→escalate ladder (background → pixel coords → `foreground` with
  separate approval). Non-capture actions need approval unless auto-approved; `permissions.py` gates.
  Memory/skill writes go through `tools/write_approval.py`: staged as JSON in
  `<HERMES_HOME>/pending/{memory,skills}/<id>.json` via atomic tmp+`os.replace`, reviewed out-of-band
  (`/memory pending`).

- Clever mechanism (from code): three genuine gems — (1) **SOM capture + click-by-element-index** with
  an `ax`-only lane so even non-vision models can drive a GUI, plus opaque `element_token`s for stale
  detection; (2) **background-first input delivery + structured verdict/escalation ladder** — co-work
  without focus theft; (3) **AST-based tool self-discovery** — add a file, get a tool, no registry edits.

- Hidden weaknesses found in code: [VC/HC] default `TERMINAL_ENV=local` = unsandboxed host shell (the
  `docker` isolation is opt-in); `write_approval` gate **defaults to OFF** (writes flow freely); the
  entire computer-use stack depends on an external `cua-driver` binary that isn't in the repo (Windows
  support = that driver's problem); `cli.py` is a 1 MB single file; `approval.py` alone is 262 KB —
  enormous complexity/trust surface; `_sudo_password_cache` holds sudo passwords in-process; portable
  fork = upstream + batch files (thin delta, tracks NousResearch).

- Stealable for a stdlib-only Python Windows assistant? **PATTERNS yes, CODE mostly no**: the AST
  self-registration pattern (`tools/registry.py` discovery) is pure stdlib and trivially stealable;
  the SOM/element-index concept and the verify→escalate verdict ladder are stealable as designs (UIA
  via `ctypes` can supply the tree); the pending-write staging pattern is stdlib. Not stealable as-is:
  cua-driver backend, terminal backends (Docker/Modal SDKs), prompt_toolkit TUI. MIT-licensed, so reuse
  is legal — just heavy.

---

## 4. ankitpathak62/Jarvis-2025 (~143★, DEAD — last commit 2025-02-11, no LICENSE file)

- What it claims / what it is: README claims "control all function of my system" — a voice assistant
  (eel GUI + hotword + face auth). Reality: a CodeWithHarry-style tutorial bot; last touched Feb 2025.

- HOW IT ACTUALLY WORKS (inside): [VC] entry = `run.py`: two `multiprocessing` processes — `startJarvis()`
  → `main.start()`: `eel.init("frontend")`, `os.system('start msedge.exe --app="http://127.0.0.1:8000/index.html"')`,
  face auth via `backend/auth/recoganize.py` `AuthenticateFace()` (OpenCV Haar cascade), `eel.start(...)`;
  `listenHotword()` → `feature.hotword()`: `pvporcupine` keywords `["jarvis","alexa"]` + `pyaudio` loop,
  on detection `pyautogui` presses `win+j`. Voice I/O = `backend/command.py`: `takecommand()` uses
  `speech_recognition` + Google Web Speech (`recognize_google`, en-US) → returns `query.lower()`;
  `speak()` re-inits `pyttsx3` sapi5 **on every call**. Dispatch = `takeAllCommands()`: a substring
  `if/elif` chain — `"open"` → `feature.openCommand()`; `"send message"/"call"/"video call"` →
  `findContact()` + `whatsApp()`; `"on youtube"` → `PlayYoutube()`; else → `chatBot()` via `hugchat`
  with a committed `backend/cookie.json`. `openCommand()`: strips words, looks up `jarvis.db`
  `sys_command(name→path)` → `os.startfile(path)`; else `web_command(name→url)` → `webbrowser.open(url)`;
  else falls through to `os.system('start ' + query)` — **raw voice text into a shell**. `whatsApp()`:
  builds `whatsapp://send?phone=<Phone>&text=<msg>`, runs `subprocess.run('start "" "<url>"', shell=True)`
  **twice** with `time.sleep(5)` between, then **blind `pyautogui` tab-counting** (`ctrl+f`, Tab ×12/×7/×6
  by message/call/video-call, `enter`). `findContact()` hardcodes `+91` prefix. `PlayYoutube()`:
  `helper.extract_yt_term()` regex `play (.*?) on youtube` → `pywhatkit.playonyt()`.

- Clever mechanism (from code): **nothing new** — except one tidy, stealable pattern: the sqlite
  `sys_command`/`web_command` tables (name→path/url) in `backend/db.py` give `open X` an extensible
  registry instead of more `if` branches. The tab-counting WhatsApp hack is the canonical fragile-bot
  example.

- Hidden weaknesses found in code: [VC] (a) **no system control exists** — no volume/brightness/shutdown/
  lock/settings code anywhere in `backend/`; the headline claim is false; (b) hardcoded
  `C:\Users\patha\Videos\Jarvis\frontend\assets\audio\start_sound.mp3` — `play_assistant_sound()` only
  works on the author's PC; (c) the whole `envJarvis/` virtualenv is **committed to the repo**; (d)
  `os.system('start ' + query)` = voice-driven command injection; (e) `query.lower()` result discarded
  in `openCommand` (no-op line); (f) `speak()` sets `rate` **after** `runAndWait()` and re-inits the
  engine per call (leak/slow); (g) bare `except:` everywhere; (h) `hugchat` cookie auth is long dead
  upstream; (i) face-auth `trainer/` + `samples/` dirs committed.

- Stealable for a stdlib-only Python Windows assistant? **YES, one thing**: the sqlite name→path/url
  registry (`db.py` schema + `openCommand` lookup chain) is stdlib-only (`sqlite3`, `os.startfile`,
  `webbrowser`) and a clean pattern for an extensible `open X` command. Nothing else — do not copy the
  `os.system('start '+query)` fallthrough or the tab-counting.

---

## Cross-cutting notes

- **Control stack ranking (most capable → least):** hermes (cua-driver MCP + 7 shell backends + ~150
  tools) > open-cowork (WSL/Lima VM sandbox + MCP + pi-agent) > Jarvis-2025 (os.startfile + voice
  string-matching) > skales (unauditable, claims only).
- **System-control reality check:** none of the four does *native* Windows system control (volume,
  brightness, power, settings) via proper APIs — Jarvis-2025's claim is empty; hermes/open-cowork get
  there only through generic shell/computer-use primitives.
- **Single best steal (across all four):** hermes-agent's **AST-based tool self-discovery**
  (`tools/registry.py` `discover_builtin_tools`) — pure-stdlib (`ast` + `importlib`), zero-dep,
  eliminates the central tool registry file entirely; combined with the sqlite name→path registry from
  Jarvis-2025's `db.py`, it gives a stdlib-only assistant an extensible tool/command system with no
  hand-maintained lists.
