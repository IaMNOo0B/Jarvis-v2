# FIRST-RUN AUTOPSY — JARVIS v2 on the Owner's Windows PC

**Scope:** everything that can go wrong between "double-click JARVIS.bat" and
"first real answer", traced to exact code. Machine: Windows 11, RTX 2060 6GB
(2019), Ryzen 5 3600, 16GB RAM, Ollama installed with
`qwen2.5:7b-instruct-q4_K_M` pulled, GitHub Desktop, zero terminal tolerance.

**Verdict up front:** 7 CRITICAL, 9 HIGH, 9 MEDIUM, 3 LOW. The build is real
and the test suite is green (449/449 on Linux), but **five of the seven
CRITICALs will bite on the very first double-click** (F-01, F-02, F-05, F-06,
and F-03 as soon as one of his 26 keys is dead). None of them were caught by
the test suite because every test runs on Linux with mocked networks — the
first-run path (Windows GUI + real network + real keyring + real Ollama) has
zero test coverage.

**How to read this:** each finding has the exact user-visible symptom (what
Owais will see), the root cause with file:line, and the fix. Fix priority:
F-01 → F-05 → F-06 → F-02 → F-03 → F-04 → F-07, then the HIGHs.

---

## CRITICAL

### F-01 — GUI bypasses ALL slash commands; pasted API keys go to the cloud brain
**File:** `jarvis/chat_gui.py:155-160` (`_run_turn` → `self.app.turn(text)`)
**Symptom:** In the chat window (the only UI he was told to use), typing
`/key gsk_xxxx` does NOT store the key. It is sent to the brain as a chat
message. The brain (Pollinations/cloud) receives his raw API key as
conversation text, and the key is saved into `sessions.db` as a user message
in cleartext. `/quit`, `/help`, `/memory`, `/recall`, `/skills`, `/keys`,
`/provider` are all equally dead in the GUI.

**Root cause:** All command handling lives in `ChatApp.run()`'s input loop
(`jarvis/chat.py:545-660`). `ChatWindow.send()` calls `self.app.turn(text)`
directly, skipping that entire block. `turn()` has no command handling.

**Why tests missed it:** no test drives `ChatWindow`; the GUI was verified
only to import without a display.

**Fix (code):** extract command dispatch from `run()` into
`ChatApp.handle_command(text) -> bool` (True = was a command, don't call the
brain). Call it from both `run()` and `ChatWindow.send()`:
```python
# chat_gui.py, in send():
if self.app.handle_command(text):
    self.q.put(("done", None)); self.entry.configure(state="normal"); return
```
Until fixed, **user-facing workaround:** paste keys only in `run-chat.bat`
(the CLI), never in the JARVIS window.

---

### F-02 — 5-second chain timeout permanently disables the local Ollama brain
**Files:** `jarvis/brain.py:54` (`FALLBACK_TIMEOUT = 5.0`);
`jarvis/llm_ollama.py:288-295` (`OllamaProvider.respond` overwrites
`self._call.timeout = timeout`); `jarvis/chat.py:298`
**Symptom:** Every first message after idle takes the cloud path; his free
API quotas burn while the 4.7GB local model he downloaded sits idle. On a
cold 2060, the model needs 15–60s just to load weights into VRAM — the chain
gives it 5 seconds, declares a timeout, and falls through to Groq/Pollinations
every single time. Even warm, a 200-token reply at ~40 tok/s is ~5s: long
answers time out mid-generation too.

**Root cause:** `FallbackChain` passes one `timeout` (5.0s) to every provider.
`OllamaCall`'s own `DEFAULT_TIMEOUT = 120.0` (`llm_ollama.py:82`) is dead code
in chain mode — the provider overwrites it per call. The 5s value was chosen
for "no blocking network beyond this in failure paths" but a local model is
not a network failure path.

**Fix (code):** per-provider timeouts. Minimal patch — let providers declare
their own timeout and have the chain respect it:
```python
# brain.py FallbackChain.respond:
timeout = getattr(provider, "chain_timeout", self.timeout)
reply = provider.respond(message, key_index=key_index, timeout=timeout)
# llm_ollama.py OllamaProvider:  chain_timeout = 120.0
# cloud providers:               chain_timeout = 15.0  (5s is too tight for
#                                 Kimi-2.8T / R1 first-token from India)
```
15s for cloud (not 5): Groq from India is usually <2s, but NVIDIA NIM and
Pollinations cold starts regularly exceed 5s — with 5s they get skipped as
"down" when they're merely slow.

---

### F-03 — One dead API key kills the ENTIRE brain chain (terminal 401/403)
**File:** `jarvis/brain.py:570-581`
```python
record(provider, key_index, "terminal",
       f"HTTP {exc.status}: not retryable")
return {"ok": False,                          # <-- RETURN, not break
        "error": f"HTTP {exc.status} from {provider.name}: not retryable", ...}
```
**Symptom:** He pastes 26 keys. Statistically 1–2 will be expired, revoked,
or wrong-tier. The moment the chain reaches that provider's last key and gets
a 401/403, the whole chain ABORTS — providers listed after it (with perfectly
good keys) are never tried. User sees: `[error] Brain failed honestly:
all model providers failed: HTTP 401 from groq: not retryable`. One bad key
= total brain death.

**Root cause:** the terminal branch `return`s instead of `break`ing to the
next provider. (401/403 correctly stop key rotation *within* a provider, but
must not stop the *chain*.)

**Fix (code):** one word —
```python
record(provider, key_index, "terminal", f"HTTP {exc.status}: not retryable")
break  # next provider; this one's keys are dead, others may live
```

---

### F-04 — Chain-order bug: cloud jumps ahead of local when Pollinations is down
**File:** `jarvis/chat.py:291-294`
```python
keyed = make_compat_providers()
if keyed:
    providers[-1:] = keyed + providers[-1:]   # assumes last == pollinations
```
**Symptom:** Intermittent: on runs where Pollinations' health check fails but
Ollama is up, the intended order `[ollama, groq, …]` becomes
`[groq, …, ollama]` — cloud is tried (and billed) before local, violating the
local-first design.

**Root cause:** slice assignment assumes the last element is the keyless
Pollinations provider. When it's absent, keyed providers are inserted ahead
of Ollama.

**Fix (code):** build the order explicitly —
```python
providers = []
# ... ollama, omniroute appends ...
keyed = make_compat_providers()          # may be []
providers.extend(keyed)                  # keyed cloud, after local+omniroute
poll = make_pollinations_call()          # keyless, always last
if poll is not None:
    providers.append(PollinationsProvider(poll))
```

---

### F-05 — JARVIS.bat dies silently on ANY startup failure
**File:** `JARVIS.bat` (4 lines, no `pause`, no `python` check)
```bat
@echo off
cd /d "%~dp0"
python -m jarvis.chat_gui
```
**Symptom:** If `python` isn't on PATH, if it's the Microsoft Store stub, if
tkinter is missing, if any import crashes, if `JARVIS-RULES.txt` is corrupt
(`ChatApp.__init__` → `sys.exit(2)` at `chat.py:194`) — the console window
flashes for ~200ms and vanishes. Zero information. He will double-click
again, and again, and conclude "it doesn't work."

**Root cause:** no error trapping, no `pause`. (`setup.bat` already does this
right — `where python` + messages + `pause` — but JARVIS.bat is the launcher
he was told to double-click, and it doesn't run setup.)

**Fix (code):** make JARVIS.bat match setup.bat's discipline —
```bat
@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo JARVIS needs Python 3.11+. Install from python.org (tick "Add to PATH").
    pause
    exit /b 1
)
python -m jarvis.chat_gui
if errorlevel 1 (
    echo.
    echo JARVIS stopped with an error (code %errorlevel%). Screenshot this window.
    pause
)
```
Plus: surface the Store-stub trap (`setup.py:146 _check_store_stub` exists
but never runs on this path) — if `python` resolves under `WindowsApps`,
print the python.org instruction instead of opening the Store.

---

### F-06 — Startup freezes with zero feedback (health-check pile-up)
**File:** `jarvis/chat.py:260-294` (`ChatApp.__init__`, runs on the GUI thread
via `jarvis/chat_gui.py:main`)
**Symptom:** Double-click → nothing. No window, no splash, no sound — for up
to ~2 minutes. He WILL double-click again (see F-07). Then two windows pop up
at once.

**Root cause:** the constructor performs sequential blocking network probes
before the window exists:
- `make_omniroute_call` → GET `localhost:20128/v1/models` (fast refuse if down)
- `make_pollinations_call` → GET `text.pollinations.ai/openai/models`, 8s timeout
- `make_compat_providers()` → one GET `/models` per provider WITH keys, 8s
  each (`llm_compat.py:249`). With his 26 keys spread over ~10 providers on a
  slow-DNS or proxied connection: 10 × 8s + 8s ≈ 88s worst case.
- plus knowledge FTS5 index build (~1s, fine).

**Fix (code):** show the window FIRST with a "waking up…" status, build the
brain chain on a worker thread, then flip the pill to
"ready — brain: ollama/pollinations/…". Health checks are nice-to-have; the
chain already fails over honestly at call time. At minimum, parallelize the
probes (threads) and cap total startup probing at ~10s.

---

### F-07 — No single-instance guard (v1 had one, v2 lost it)
**Files:** `jarvis/chat.py`, `jarvis/chat_gui.py` (no lock anywhere; v1 used
QLockFile)
**Symptom:** After F-06's freeze, two JARVIS windows. Both write to the same
`data/sessions.db` / `memory.db`. SQLite serializes via file locks
(`busy_timeout=5000` at `session_store.py:119`), so it mostly survives — but
approval budgets, session sequences, and the knowledge-index cache can
interleave, and he gets two voices/states. Confusing at best.

**Fix (code):** re-add the v1 single-instance lock (platform-appropriate:
`msvcrt.locking` on a lockfile in `data/`, or a named mutex via ctypes).
Second instance should focus/exit with "JARVIS is already running."

---

## HIGH

### F-08 — GUI never shows which brain is active (stub masquerades as JARVIS)
**Files:** `jarvis/chat_gui.py:main` (banners print to console before the
window exists); `jarvis/chat.py:296-302` (stub fallback)
**Symptom:** If Ollama is down and all clouds fail, the chain is empty and
`make_llm_call` returns the StubLLM — with its loud banner going to the
console window he isn't looking at. The GUI pill says "ready" and the stub
replies "At your service, sir. Text chat is online" to greetings. He will
believe he's talking to AI when he's talking to canned strings.

**Fix:** surface `chain` provenance in the GUI: status pill shows
`ready — brain: ollama` / `pollinations` / `STUB (no models!)`, and `turn()`
should announce provider switches (`via` is already in the chain result).

### F-09 — No STOP/cancel: a hung turn bricks the UI for up to ~90 seconds
**File:** `jarvis/chat_gui.py:send` (`if ... worker.is_alive(): return` —
entry stays disabled, no cancel path)
**Symptom:** Worst case per turn: 6 providers × 5s timeout × 3 ReAct rounds ≈
90s of "thinking…" with a dead input box and no way out. (F-02's fix reduces
the timeout count but a single 120s local call still blocks.)

**Fix:** wire the spec'd STOP (C25: "STOP always wired") — a Cancel button that
abandons the worker turn (the brain call isn't truly interruptible, but the
UI can detach, re-enable input, and mark the turn abandoned).

### F-10 — No .gitignore: private chats one click from the public repo
**File:** repo root (no `.gitignore` exists — verified)
**Symptom:** After first run, GitHub Desktop shows `data/` (sessions.db =
full conversations, memory.db = his facts, approval_budget.json,
knowledge_index/), `__pycache__/`, `custom_providers.json` as untracked. One
"Commit to main" + Push and his private JARVIS data is on the public internet.

**Fix:** add `.gitignore` with `data/`, `__pycache__/`, `*.db`, `*.db-wal`,
`*.db-shm`, `.pytest_cache/` — BEFORE he pulls (i.e., push it now).

### F-11 — DCL redaction is bypassed for every chain call (privacy hole)
**Files:** `jarvis/brain.py:220-226` (`if not self.llm_off_machine: return
messages`); `jarvis/chat.py:308` (`llm_off_machine=False`)
**Symptom:** Silent. Prompts containing personal data, pasted secrets, memory
facts go to Pollinations/Groq/NVIDIA **unredacted** — the Data Classification
Layer (C27, `jarvis/dcl.py`) never engages because the flag is static
("local") while the chain is dynamic (local → cloud fallback).

**Fix:** the chain must redact per winning provider. Minimal honest fix: set
`llm_off_machine=True` (redact always — harmless for local, correct for
cloud), or thread provider identity through `chain_as_llm_call` and redact
only when `via != "ollama"`.

### F-12 — `probe_key` sprays his raw API key at 13 wrong providers
**File:** `jarvis/llm_compat.py:90-116` (`probe_key`)
**Symptom:** Silent. For any key whose prefix isn't fingerprinted, the raw key
is sent as a Bearer token to up to 13 providers' `/models` endpoints until
one returns 200. Twelve of them log a key that isn't theirs. Also: 13
sequential HTTPS round-trips × 8s timeout = the `/key` command can hang for
~100s.

**Fix:** drop probing; on fingerprint miss, ask which provider (or accept
`/key <provider> <key>`). Fingerprinting already covers his big ones
(gsk_, sk-or-, nvapi-, AIza). If probing stays, do it only with explicit
consent and in parallel with a 3s cap.

### F-13 — OneDrive-synced Documents will lock/corrupt the SQLite stores
**File:** `jarvis/chat.py:main` (`data_dir = base_dir / "data"`);
`jarvis/session_store.py:119` (`busy_timeout=5000`)
**Symptom:** GitHub Desktop's default clone location is
`%USERPROFILE%\Documents\GitHub\Jarvis-v2`. Win11 commonly backs up Documents
to OneDrive. OneDrive's sync locks fight SQLite WAL mode → `database is
locked` errors mid-chat, or worse, sync-conflicted copies of sessions.db.

**Fix:** at startup, detect OneDrive in the data path
(`os.environ["OneDrive"]`) and either warn loudly or relocate `data/` to
`%APPDATA%\JARVIS` (v1's `paths.py` already solved this — port it).

### F-14 — VRAM math is borderline on the 2019 2060
**Files:** `jarvis/llm_ollama.py:97` (`num_ctx=4096` — verify at line ~150)
**Symptom:** 4.7GB weights + ~0.5GB KV @4k + Win11 display reservation
(~0.4–0.6GB) ≈ 5.6–5.8GB of 6GB. If it doesn't fit, Ollama silently partial-
offloads to CPU → 3–5 tok/s → every reply takes 30s+ (and F-02's 5s timeout
would have skipped it anyway).

**Fix:** after F-02, if local is still slow, drop `num_ctx` to 2048 for the
2060 (KV halves). Measure on his card; don't guess.

### F-15 — `ollama serve` may not be running (he only ran `ollama pull`)
**File:** `jarvis/llm_ollama.py:254-263` (health check → honest banner)
**Symptom:** Handled honestly in CLI (`[llm] ollama not reachable…
Is it running? Try: ollama serve`). In GUI the banner goes to the console
behind the window (compounds F-08). Ollama's Windows installer does
autostart a tray service by default, so likely fine — but if he killed it,
first run silently uses cloud/stub.

**Fix:** covered by F-08's provider pill. User step if needed: start Ollama
from the Start menu (tray icon).

### F-16 — `brain.omniroute_model` config key doesn't exist in the schema
**File:** `jarvis/chat.py:267-268`
(`self.config.get("brain.omniroute_model", "google/gemini-2.5-flash")`)
**Symptom:** None (falls back to default silently) — but the "configurable
model" claim is false; the schema (`chat.py:200-208`) has no such field, so
no Settings UI or file edit can ever change it.

**Fix:** add the field to the schema or drop the `.get` and hardcode honestly.

---

## MEDIUM

### F-17 — Python version never checked on the JARVIS.bat path
`setup.py:338` checks 3.11+, but JARVIS.bat skips setup. On <3.10:
`SyntaxError` at import → F-05's silent death. (His manual PATH install
suggests python.org 3.11+, but it's unverified.) Fix: version gate in
JARVIS.bat or in `chat_gui.main()` before heavy imports.

### F-18 — Preflight/ChatApp gap: corrupt rules file kills GUI silently
`chat_gui.main()` shows a dialog for `preflight()` problems, but
`ChatApp.__init__` (`chat.py:190-194`) can still `sys.exit(2)` on a
`RulesError` (file exists but unparsable/empty P0) — no dialog, traceback to
console, window closes (F-05). Fix: wrap `ChatApp(...)` in try/except and show
the dialog.

### F-19 — OmniRoute default model ID is unverified
`chat.py:268`: `"google/gemini-2.5-flash"`. If OmniRoute expects a different
ID format, every call 404s → honest fallback (chain survives). Verify against
his dashboard's Endpoints list on first run; make it a config field (F-16).

### F-20 — First `/key` needs a restart (documented, but easy to miss)
Providers are built once in `ChatApp.__init__`. The CLI says "Restart JARVIS
to use it" — fine. In GUI (after F-01's fix) the same message must appear.

### F-21 — Knowledge FTS5 on Windows: fine, but cold-build on every fresh pull
`skills/knowledge/skill.py:_build_index` — 2.1MB, ~1s, cached by mtime
fingerprint. CPython Windows ships FTS5. Non-issue unless his Python is a
stripped embeddable build.

### F-22 — WinCred 512-byte credential-blob limit
`config.py` `_WinCredBackend.set_password` — `CRED_MAX_CREDENTIAL_BLOB_SIZE`
is 512 bytes; UTF-16LE halves that to 256 chars. API keys are <100 chars.
Non-issue; noted for completeness.

### F-23 — Stale help text
`chat.py` `/help` still says `/key <provider> <key>` although bare
`/key <paste>` auto-detects. Cosmetic; update the string.

### F-24 — `run-chat.bat` vs GUI data-dir consistency
Both resolve to `<repo>/data` (`--data-dir "%~dp0data"` vs `base_dir/"data"`).
Consistent — verified, no action.

### F-25 — Pollinations rate-limit behavior under load
No key, fair-use. 429 → `RETRYABLE_HTTP` → chain moves on honestly. From India
via Cloudflare: reachable (verified from sandbox). If his ISP blocks it,
health check fails → skipped loudly. Acceptable.

---

## LOW

- **L-1** `chat-gui.bat` duplicates `JARVIS.bat` (plus `pause`). Harmless.
- **L-2** GUI session labeled `"cli"` (`chat.py:311`). Cosmetic.
- **L-3** `from jarvis.llm_compat import ... PRESETS` unused import in
  `chat.py:run` (`/key` handler). Lint-level.

---

## Pull-time (before first run) checklist for Owais

1. **Pull `IaMNOo0B/Jarvis-v2`** in GitHub Desktop (not `jarvis` — that's v1).
   Verify the folder contains `JARVIS.bat` + `knowledge/` (76 files).
2. **Start Ollama** (tray icon) — `ollama pull` alone doesn't serve.
3. **Double-click `JARVIS.bat`.** If a window flashes and dies: screenshot the
   console — after F-05's fix it will say why.
4. **Keys go in `run-chat.bat`** (`/key <paste>`) until F-01 is fixed — NOT in
   the JARVIS window.
5. **Don't commit `data/`** — after F-10's `.gitignore` lands this is automatic.
6. Keep the repo OUT of OneDrive-synced folders if possible (F-13).

## What the test suite cannot see (structural gap)

All 449 tests run on Linux with mocked transports. Zero coverage for:
Windows GUI startup, Credential Manager round-trip, Ollama cold-start timing,
multi-provider real failover, OneDrive paths, double-click (no-console)
behavior. Recommend: a Windows smoke script (`smoke_first_run.py`) that
imports every module, constructs ChatApp with a fake data dir, and asserts
the chain order + timeouts — runnable via `setup.bat --preflight` before the
window opens.
