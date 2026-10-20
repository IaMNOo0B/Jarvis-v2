# Team 2E — Benchmark + Classic Voice-Control Code — BLOCKED BY GITHUB RATE LIMIT

> Status: INCOMPLETE — GitHub MCP connector returned HTTP 429 ("too many requests")
> on the second batch of calls. Per hard-stop rule, no further GitHub requests
> (via connector, browser, or raw URLs) were made in this attempt.
> Only root-directory listings were retrieved. NO implementation files were read,
> so no "HOW IT ACTUALLY WORKS (inside)" claims are made below — inventing them
> would violate the precision protocol. Re-run this slice after the rate limit resets.

## showlab/WorldGUI (126*, alive/dead unknown, license unknown — not read)
- What it claims / what it is: "Enable AI to control your PC" + benchmark (per task brief)
- HOW IT ACTUALLY WORKS (inside): NOT READ — blocked before implementation files could be fetched
- Root listing actually retrieved (evidence): directories `agent/`, `assets/`, `css/`, `data/`, `shells/`; files `README.md`, `README_zh.md`, `Get Started.md`, `requirements.txt` (2637 bytes), `index.html`, and three entry-point candidates at root: `test_guithinker_custom.py` (4668 B), `test_guithinker_demo.py` (5886 B), `test_guithinker_fast.py` (4476 B). The `test_guithinker_*` naming suggests the agent core is "GUIThinker" and the `agent/` package is the first place to read on retry.
- Clever mechanism: unknown — not read
- Hidden weaknesses: unknown — not read
- Stealable for a stdlib-only Python Windows assistant? unknown — not read

## kishanrajput23/Jarvis-Desktop-Voice-Assistant (1005*, alive/dead unknown, license file present, 1073 B — consistent with MIT, not verified by reading)
- What it claims / what it is: classic tutorial desktop voice assistant (per task brief)
- HOW IT ACTUALLY WORKS (inside): NOT READ — blocked before implementation files could be fetched
- Root listing actually retrieved (evidence): main code lives in subdirectory `Jarvis/` (not at root), plus `Images/`, `Presentation/`, `README.md` (6698 B), `requirements.txt` (only 89 bytes — a very small dependency set), `LICENSE`, `.gitignore`. The exhaustive tool inventory requested in the brief could NOT be produced without reading `Jarvis/` — do not accept any inventory for this repo from this run.
- Clever mechanism: unknown — not read
- Hidden weaknesses: unknown — not read
- Tool inventory: NOT OBTAINED (see above)
- Stealable: unknown — not read

## kumar045/Control-PC-Terminal (10*, alive/dead unknown, license file present, 1069 B — consistent with MIT, not verified by reading)
- What it claims / what it is: control agents/PC from any device (per task brief)
- HOW IT ACTUALLY WORKS (inside): NOT READ — blocked before scripts could be fetched
- Root listing actually retrieved (evidence): the product appears to be a SINGLE self-contained script: `control-terminal` (21636 bytes, no extension — likely bash), plus `custom-agents.conf` (618 B — agent definitions are config-driven), `install.sh` (3951 B), `examples/`, `rule/`, `README.md` (4955 B), `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`. Protocol/auth/execution questions in the brief all live inside that one 21 KB file — read it first on retry.
- Clever mechanism: single-file design + `custom-agents.conf` (observed from listing only)
- Hidden weaknesses: unknown — not read
- Stealable: unknown — not read

## Retry plan (for parent / next run)
1. Wait for GitHub MCP rate limit to reset; do NOT hammer — one batch at a time.
2. WorldGUI: read `agent/` listing, then its main module + `test_guithinker_demo.py` + `requirements.txt`.
3. Jarvis: read `Jarvis/` listing, then the main `.py` file(s) fully — enumerate every task + mechanism.
4. Control-PC-Terminal: read `control-terminal` (21 KB, one file) + `custom-agents.conf` + `install.sh`.
5. Read each `LICENSE` to confirm license instead of inferring from byte size.
