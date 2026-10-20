# JARVIS v2

JARVIS is a Windows-first desktop assistant built around a gated tool system:
chat → intent routing / brain → Gate → approved skill or PC action → result.

## Run it

1. Install **64-bit Python 3.11 or newer** from python.org and enable **Add Python to PATH**.
2. Double-click **`JARVIS.bat`** to open the graphical chat.
3. For the terminal chat instead, double-click **`run-chat.bat`**.
4. Start Ollama from the Windows Start menu if you want the local model available.

The GUI appears while JARVIS initializes its providers. If startup fails, read the message shown in the window rather than repeatedly launching another copy.

## Brain and provider order

When providers are healthy, JARVIS tries:

1. **Ollama (local)** — preferred for privacy and avoiding cloud quotas.
2. Configured API-key providers.
3. OmniRoute, if its local gateway is running.
4. Pollinations, as a keyless online fallback.

If none are available, JARVIS may fall back to a clearly limited stub. A stub is not a full language model; check the GUI's provider status if replies seem canned or irrelevant.

## Actions and safety

- App launches and browser navigation go through the Gate and may require approval.
- Explicit web-search requests use the `web_search` skill. Search needs an internet connection.
- JARVIS should report an actual action failure instead of claiming that it succeeded.
- Store API keys only through JARVIS's supported key command/settings flow. **Never paste keys into ordinary chat messages or screenshots/logs.** If a key has been exposed, revoke it at its provider and create a replacement.

## Troubleshooting

- **Generic or irrelevant replies:** check which provider is active and whether Ollama is running. If all providers fail, inspect the error details instead of assuming a tool ran.
- **Chrome or another app does not open:** verify the app is installed and approve the action if JARVIS asks.
- **YouTube or another supported website does not open:** verify that Windows has a default browser configured.
- **Internet search fails:** check the network connection; JARVIS must say when the search tool returns an error.
- **OmniRoute unavailable:** this is optional. JARVIS can use other available providers; do not expect OmniRoute unless its local service is running.

## Repository map

| Path | Purpose |
|---|---|
| `jarvis/` | Chat, brain, provider adapters, intent router, Gate, memory, PC control and supporting modules |
| `skills/` | First-party tools such as web search, reminders, notes, clock and code |
| `tests/` | Regression and safety tests |
| `JARVIS-RULES.txt` | Core assistant rules |
| `MASTER-PLAN.md` | Build plan |
| `FIRST-RUN-AUTOPSY.md` | Known startup and first-run risks; verify findings against current code before relying on older notes |

## Run tests

With Python 3.11+ installed:

```bash
python -m pip install pytest numpy
python -m pytest tests/ -q
```

The GitHub Actions workflow runs the same test suite on pull requests. Windows-specific app launches, Ollama performance and real provider credentials still require a smoke test on the target PC.

## Local data

The `data/` folder contains sessions, memory and local indexes. It is ignored by Git and should remain private. Back it up before removing it; deleting it resets local history.
