# Team 2A — Screen / Automation Reverse-Engineering Strike

> **STATUS: BLOCKED — GitHub MCP HTTP 429 (rate limit) hit during recon.**
> Per provider policy a 429 is a hard stop for this attempt: no retries via another endpoint/tool.
> Below is ONLY what directory listings returned before the limit. No implementation file bodies
> were read, so no `file:function` OS-call traces are claimed. A re-run after the limit resets
> is required to complete the "HOW IT ACTUALLY WORKS (inside)" sections.

## LYiHub/pub-local-jarvis (516*, alive — recent HEAD dd8fbf9, license file present, 1079 B — consistent with MIT, NOT verified by reading it)
- What it claims / what it is (1 line): Chinese Windows local multimodal JARVIS with screen + audio sensing (per task brief; README 10,982 B + PROJECT_OVERVIEW.md 10,528 B present, not read before block).
- HOW IT ACTUALLY WORKS (inside): entry → parse → dispatch → OS calls with file:function refs
  - NOT ESTABLISHED — blocked before code reads.
  - Structure proven by listings: this is NOT a simple Python script. Three layers:
    - `src/jarvis_backend/` (Python backend package, only entry under `src/`)
    - `native/` — C++ runtime: `native/src/worker.cpp` (58,433 B — by far the largest file, almost certainly the sensing/inference worker), `native/src/omni_runtime.cpp` (17,673 B), `native/src/audio.cpp` (2,594 B), `native/src/fingerprint.cpp` (5,346 B), `native/src/scheduler.cpp` (2,901 B), `native/src/protocol.cpp` (2,982 B), `native/src/main.cpp` (1,604 B), `native/src/runtime.cpp` (1,019 B), plus a `native/src/windows/` subdir (Windows-specific capture code lives here — unread) and `native/include/jarvis/`.
    - `desktop/` — Electron app: `desktop/src/main.js` (27,898 B), `desktop/src/backend-manager.js` (12,411 B — spawns/manages the Python/native backend), `desktop/src/event-router.js`, `desktop/src/privacy-mode.js` (715 B — suggests a sensing on/off gate), `desktop/src/scene-policy.js`, `desktop/src/game-profiles.js` (5,150 B), pet/overlay files (`pet-window.js`, `barrage-overlay.js`).
    - Launcher: `start-real.ps1` (51,345 B — very large PowerShell bootstrap) + `start-real.cmd`.
  - Inference from structure only [SP]: screen sensing is native C++, not Python/pyautogui — the Python layer is a backend behind an Electron shell, with a native protocol (`protocol.cpp`) between them.
- Clever mechanism (from code) or "nothing new": cannot verify from code — not read. Structural candidate: native worker + scheduler + privacy-mode gate.
- Hidden weaknesses found in code: cannot verify from code — not read. Structural smell: a 51 KB PowerShell launcher and a 58 KB single `worker.cpp` suggest monolith/bootstrap fragility.
- Stealable for a stdlib-only Python Windows assistant? Unknown until code is read — native C++ sensing is by definition NOT stdlib-Python stealable; only the architecture (privacy gate, scene policy, backend-manager lifecycle) might be.

## Julian-Ivanov/jarvis-voice-assistant (121*, alive — HEAD 0dbc657, NO LICENSE file in root listing)
- What it claims / what it is (1 line): Voice assistant with browser automation + screen capture (per task brief; README 9,453 B + SETUP.md 7,518 B present, not read before block).
- HOW IT ACTUALLY WORKS (inside): entry → parse → dispatch → OS calls with file:function refs
  - NOT ESTABLISHED — blocked before code reads.
  - Structure proven by listings: remarkably small, flat Python repo — the whole automation surface is 3 files:
    - `server.py` (12,721 B — entry point / server, almost certainly voice→LLM→tool dispatch)
    - `browser_tools.py` (5,162 B — the entire browser-automation core in one file)
    - `screen_capture.py` (1,312 B — the entire screen feature in one tiny file; at 1.3 KB it can only be a thin screenshot→base64/LLM-vision wrapper, no OCR/coordinate engine fits in that size)
    - `frontend/` dir, `requirements.txt` only 126 B (very few dependencies), `config.example.json` (493 B).
  - Inference from sizes only [MC]: trace the task asks for (voice → browser action) is `server.py` → `browser_tools.py`; screen is an afterthought module, not a sensing loop.
- Clever mechanism (from code) or "nothing new": cannot verify from code — not read.
- Hidden weaknesses found in code: cannot verify from code — not read. Structural: no LICENSE = legally not reusable; single-file browser core implies hardcoded selectors/no retry layer (hypothesis, unverified).
- Stealable for a stdlib-only Python Windows assistant? Unknown until code is read; small dependency list (126 B requirements) makes it the most promising of the four for a lightweight steal — TO VERIFY on re-run.

## bertrandmbanwi/Jarvis (37*, alive — HEAD d17d396, license file present, 1071 B — consistent with MIT, NOT verified by reading it)
- What it claims / what it is (1 line): Voice + browser automation + desktop assistant (per task brief; README 16,013 B + HOW-TO.md 28,755 B present, not read before block).
- HOW IT ACTUALLY WORKS (inside): entry → parse → dispatch → OS calls with file:function refs
  - NOT ESTABLISHED — blocked: the `jarvis/` package and `skills/` listings themselves returned HTTP 429, so even the automation core's filenames are unknown.
  - Structure proven by root listing only: Python project (`pyproject.toml`, multiple `requirements-*.txt` incl. a 293,907 B CI lockfile — heavy, pinned dependency stack), `jarvis/` package dir, `skills/` dir (skill-plugin architecture), `desktop-overlay/` dir, `evals/` + `tests/` dirs (has evaluation harness — rare in this class), Docker (`Dockerfile`, `docker-compose.yml`), macOS artifact `com.jarvis.assistant.plist` + `start.sh` (20,401 B) alongside Windows claims — suggests cross-platform, server-style deployment rather than a native Windows agent.
- Clever mechanism (from code) or "nothing new": cannot verify from code — not read.
- Hidden weaknesses found in code: cannot verify from code — not read.
- Stealable for a stdlib-only Python Windows assistant? Likely no on structure alone [SP] — Docker + heavy lockfile + plist point away from stdlib/Windows-native; the `skills/` + `evals/` pattern may be stealable as architecture. TO VERIFY on re-run.

## Surajkumar5050/zyron-assistant (122*, alive — HEAD 75e4654, license file present, 1074 B — consistent with MIT, NOT verified by reading it)
- What it claims / what it is (1 line): Local Windows control assistant "Zyron" (per task brief; README 16,626 B present, not read before block).
- HOW IT ACTUALLY WORKS (inside): entry → parse → dispatch → OS calls with file:function refs
  - NOT ESTABLISHED — blocked: the `src/` listing returned HTTP 429, so the control core's filenames are unknown.
  - Structure proven by root listing only: Python (`pyproject.toml` 1,655 B), `src/` package, Windows-native launch story (`setup.bat`, `start_zyron.bat`, `stop_zyron.bat`, `run_silent.vbs` — silent background launch via VBScript), plus a browser-control strategy split across TWO extensions: `browser_extension/` (Chromium) and `firefox_extension/` — i.e. browser control via a companion extension, not Selenium/pyautogui alone [MC from structure]; also `model/` dir (bundled local model assets?) and `markdown_themes/`.
- Clever mechanism (from code) or "nothing new": cannot verify from code — not read. Structural candidate: dual browser-extension bridge is the most distinctive mechanism in this set.
- Hidden weaknesses found in code: cannot verify from code — not read.
- Stealable for a stdlib-only Python Windows assistant? Unknown until code is read; the extension-bridge idea is JS, not stdlib Python, but the `src/` control core might be. TO VERIFY on re-run.

---

## Re-run checklist (when GitHub rate limit resets)
1. LYiHub: read `native/src/windows/*`, `native/src/worker.cpp`, `native/src/omni_runtime.cpp`, `src/jarvis_backend/*`, `desktop/src/backend-manager.js` — answer: DXGI/GDI/WinRT capture? OCR? audio loop?
2. Julian-Ivanov: read `server.py`, `browser_tools.py`, `screen_capture.py` in full (all small) — trace one voice command end-to-end.
3. bertrandmbanwi: list `jarvis/` + `skills/`, then read the automation/desktop skill core.
4. Surajkumar5050: list `src/`, then trace one control command; read both extension manifests/background scripts.
5. Read all four LICENSE files verbatim to confirm license claims above.
