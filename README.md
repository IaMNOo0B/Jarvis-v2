# JARVIS v2 — Text Chat + Tool-Using Assistant

JARVIS is a Windows-first AI assistant with a chat GUI, conversation history,
memory, web search, notes, code tools, and optional PC control. It uses an
actual model provider when one is available; the built-in stub is only a
limited fallback and is **not** a ChatGPT-level conversational model.

## Start JARVIS

1. Install Python 3.11+ from python.org and enable **Add Python to PATH**.
2. Open this folder and double-click `JARVIS.bat` (or `run-chat.bat` for the
   terminal version).
3. Wait for the startup status, then type a request.

## Get a real conversational brain

JARVIS checks configured providers at startup and builds a fallback chain.
You do not need to edit Python code to select a provider.

### Option A — Local/offline with Ollama

1. Install Ollama from https://ollama.com/download.
2. Open Command Prompt and run:
   ```bat
   ollama pull qwen2.5:7b-instruct-q4_K_M
   ```
3. Keep Ollama running, then restart JARVIS.

This keeps inference local. First responses can be slow while the model loads.
On a GPU with 6 GB VRAM, performance depends on Windows/GPU memory usage.

### Option B — Cloud provider with an API key

In the JARVIS chat, enter `/key gemini YOUR_API_KEY` or use a provider name
supported by `/help` (for example `groq`, `openrouter`, or `nvidia`).
Restart JARVIS after adding a key. Keys are stored through JARVIS's secrets
storage; never paste a real key into a public issue, screenshot, or chat outside
your own local JARVIS window.

### Option C — Keyless cloud fallback

JARVIS also checks its Pollinations provider, which may be available without an
API key. It requires an internet connection and depends on that service's
availability and fair-use limits. Do not send sensitive information to a
third-party model.

## What you can ask it to do

Examples:
- "Explain recursion in simple English."
- "Search the web for the latest Ollama setup instructions and summarize them."
- "Write a note called exam-plan with my revision schedule."
- "Look at the current screen and tell me what is open."
- "Create a small Python script that sorts a list."

JARVIS decides whether to answer directly or call an available tool. Web results
are treated as untrusted data. PC control and code execution are subject to the
configured gate and approval flow; never approve an action unless you understand
what it will do. Not every request is supported yet, and a tool can fail.

## Status and troubleshooting

- A red **STUB — no models!** status means JARVIS is not using a full AI model.
  Install/start Ollama, configure a working provider, or check your internet.
- `/help` lists chat commands; `/keys` lists configured provider names and
  counts without printing secret values; `/skills` lists discovered skills.
- `/quit` exits the chat.
- The GUI and Windows launcher still need a real Windows smoke test after code
  changes. Passing unit tests alone does not prove every PC-control action works.

## Development

Run tests from the repository root:

```bat
python -m pytest tests/
```

Tests use fakes for model/network operations; they do not replace testing with a
real model and Windows desktop. Never claim an action succeeded until JARVIS
receives a confirming tool result.
