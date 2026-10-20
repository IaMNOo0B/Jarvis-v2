# Remaining first-run HIGHs — implementation specs (F-08, F-09, F-12, F-15)

Status: F-10, F-11, F-13, F-14, F-16 FIXED + tested (454/454 green, 2026-10-19 ~19:30 IST).
These four remain. All specs verified against the current tree
(`~/workspace/jarvis-v2`). None can be fully verified on Linux (tkinter GUI);
implement on the build machine and smoke-test on Windows before pushing.

## F-08 — GUI never shows which brain is active (+ F-15 covered by this)

**Files:** `jarvis/brain.py` (FallbackChain), `jarvis/chat.py` (ChatApp),
`jarvis/chat_gui.py` (status pill).

**Current state (verified):**
- `FallbackChain.respond()` (brain.py:549-606) returns
  `{"ok", "reply", "via": provider.name, "attempts"}` — the provider name
  EXISTS but `chain_as_llm_call` (brain.py:609) drops it, returning only the
  reply string. The Brain never learns `via`.
- GUI pill (`chat_gui.py:56-57`, `_set_status` at :121) only ever says
  "ready" / "thinking…" / "warming up…" — never the provider.
- Stub fallback (`chat.py:296-302` region): if the chain is empty, StubLLM
  answers "At your service, sir…" while the pill says "ready".

**Fix:**
1. `brain.py` — `FallbackChain.__init__`: add `self.last_via: str = "none"`.
   In `respond()`, on success set `self.last_via = provider.name` before
   returning; on total failure set `self.last_via = "none"`.
2. `chat.py` — `ChatApp.__init__`: keep `self._chain = chain` (currently the
   chain object is built locally and only the adapted `llm_call` is kept;
   verify — if the chain isn't stored, store it).
   Add `ChatApp.last_provider` property returning
   `getattr(self._chain, "last_via", "unknown")`.
3. `chat_gui.py` — in the queue pump where `("done", None)` is handled,
   set the pill from `self.app.last_provider`:
   - normal: `ready — brain: ollama` (green #2e7d32)
   - cloud: `ready — brain: pollinations` (green)
   - stub/empty: `STUB — no models!` (red #d32f2f)
   Also announce provider switches: if `via` differs from the previous
   turn's, print `[brain] now answering via pollinations` in the window.
4. F-15 rides along: if `ollama serve` isn't running, the chain skips it
   and the pill honestly shows the fallback provider — no more silent
   console banner behind the window.

**Tests (Linux-runnable):** unit-test `FallbackChain.last_via` transitions
(success → name, total failure → "none") in `test_brain.py`. The pill
rendering itself needs the Windows smoke run.

## F-09 — No STOP/cancel: a hung turn bricks the UI for ~90s

**Files:** `jarvis/chat_gui.py` (`send` at :170, `_run_turn` at :185,
`self._worker` at :93).

**Current state (verified):** `send()` returns early if a worker is alive;
the entry stays disabled until `"done"` arrives. Worst case per turn:
6 providers × 5s × 3 ReAct rounds ≈ 90s of dead UI.

**Fix:**
1. Add a `tk.Button` "■ Stop" next to Send, disabled by default; enabled
   while a worker is alive.
2. On click: set `self._abandoned = True`, detach — do NOT join the worker
   (the brain call isn't truly interruptible; joining would block the UI
   the same 90s). Re-enable the entry, set pill to
   `ready — turn abandoned` (amber), print `[sys] Turn abandoned, sir.`
   in the window.
3. In `_run_turn`'s `finally`: only put `("done", None)` if not abandoned;
   if abandoned, put `("abandoned", None)` and have the pump ignore late
   output from the dead worker (guard `_say` with a turn token: increment
   `self._turn_id` on abandon; `_run_turn` captures its id and drops
   output if it no longer matches).
4. The orphaned worker thread is daemon=True — it dies with the process.
   Document that the provider call still completes server-side (can't
   un-send an HTTP request); the UI just stops waiting.

**Tests:** the turn-token logic is pure Python — unit-testable headless
(token mismatch drops output). The button wiring needs Windows smoke.

## F-12 — `probe_key` sprays the raw API key at 13 wrong providers

**Files:** `jarvis/llm_compat.py:90-114` (`probe_key`), `jarvis/chat.py`
(`/key` handler at ~:624).

**Current state (verified):** on fingerprint miss, the raw key goes as a
Bearer token to up to 13 providers' `/models` endpoints (sequential,
8s timeout each → ~100s hang). Twelve providers log a key that isn't
theirs. The 13:10 IST chat message told Owais "No fingerprint? It probes
the providers" — so this behavior was JUST announced to him.

**Decision needed from Owais (his keys, his call):**
- **Option A (recommended):** drop probing. On fingerprint miss, print the
  provider list and ask for `/key <provider> <key>`. Fingerprinting
  already covers his big ones (gsk_, sk-or-, nvapi-, AIza, …).
- **Option B:** keep probing but ONLY with explicit per-key consent
  ("Couldn't identify this key — may I check it against N providers?
  [y/N]") and parallel with a 3s cap each.

Do NOT silently change this without telling him — the probing behavior
was announced in chat an hour before this spec. Present both options.

**Implementation (either option):** one edit in `chat.py`'s `/key` handler;
delete or gate the `probe_key(key)` call. If Option B, rewrite `probe_key`
with `concurrent.futures` and per-call consent. Add a test asserting no
network call happens on fingerprint miss (Option A).

## F-20 (MEDIUM, ride-along) — GUI `/key` restart message

`chat.py`'s `/key` prints "Restart JARVIS to use it, sir." — verify the
GUI path (via `handle_command` in `_run_turn`) surfaces the same message
in the window, not the console. One-line check during the GUI smoke run.
