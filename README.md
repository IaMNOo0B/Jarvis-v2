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

JARVIS checks for the model configured in `data/config.yaml` under
`brain.ollama_model`. If your installed Ollama model has a different name,
set that field to the exact name shown by `ollama list`. The
`brain.ollama_base_url` setting defaults to `http://localhost:11434`.
Use `/status` in the chat to see Ollama's startup health, providers in the
fallback chain (which are not all independently health-checked), the last
provider used, memory/capture settings, self-critique, and saved web notes.
The report never prints API-key values.

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

## Learning and self-improvement

JARVIS can retrieve relevant local memory snippets during later conversations.
Automatic saving of conversation episodes is **off by default** because
privacy filters are heuristic, not a guarantee. To opt in, set
`learning.auto_episode_capture: true` in `data/config.yaml`. Even with the
filter enabled, do not enter passwords, API keys, private contact details, or
other highly sensitive information. Retrieved memory is passed as untrusted
evidence, not inserted into the system instructions.

For internet research, ask JARVIS to **"learn about [topic] and save the sources"**.
It can use `web_learn` to fetch and save up to three pages under the local
`learned/` data folder, with source URLs, timestamps, hashes, and explicit
untrusted-content labels. Later it can use `learning_search` to retrieve those
notes. This is retrieval-based learning: it **does not retrain model weights**.

Self-critique is enabled by default and may make an additional model call to
review longer answers against JARVIS's rules. This can increase response time
and cloud usage.

JARVIS does **not** silently rewrite or upgrade its own application code.
A proposed code change should be reviewed, tested, and explicitly approved
before it is installed. Web pages are untrusted data; saved notes never become
system instructions.

## What you can ask it to do

Examples:
- "Explain recursion in simple English."
- "Search the web for the latest Ollama setup instructions and summarize them."
- "Learn about local AI memory systems and save the source notes."
- "What did you learn about local AI memory systems? Search your learned notes."
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
receives a confirming tool result. A failed action remains unresolved until the
each unresolved action is tracked by its exact tool and arguments, and an
unrelated success does not erase it. Gate-denied actions are also unresolved
because they never ran. If any issue remains unresolved, JARVIS stops honestly
instead of claiming completion.

External research and adoption decisions are tracked in
[docs/EXTERNAL-RESEARCH-AND-ADOPTION.md](docs/EXTERNAL-RESEARCH-AND-ADOPTION.md).
