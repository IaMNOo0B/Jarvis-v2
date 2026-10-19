# JARVIS v2 — Wave 1: The Spine

Text chatbot core. Session store → Gate → Brain → Skills → Memory → DCL,
governed by `JARVIS-RULES.txt`. Voice comes last (Wave 4).

## Run it (no terminal needed for daily use)

1. Install Python 3.11+ from python.org (tick "Add to PATH").
2. Open this folder, double-click `run-chat.bat` (Windows).
3. Type. That's it.

## What's inside

| Folder | What |
|---|---|
| `jarvis/` | The 7 components: rules, config, session_store, gate, brain, memory, dcl + chat CLI |
| `skills/` | 3 reference skills (echo, notes, clock) — quarantined until approved |
| `tests/` | 166 pytest tests, all passing |
| `JARVIS-RULES.txt` | THE rules file — edit it, restart, JARVIS obeys |
| `MASTER-PLAN.md` | The build contract |
| `R-COVERAGE.md` | R1–R14 verification checklist |

## The honest notes

- **Stub brain:** Wave 1 ships with a deterministic stub so the whole
  pipeline is provable today. Connect Ollama/Qwen at install for the real
  model (one-line swap in `jarvis/chat.py`).
- **Tests:** `python -m pytest tests/` — 166 passed.
- **Data:** lives in `./data/` (sessions, memory, config). Delete it for a fresh start.
