# JARVIS v2 Codebase Map — Training Document

You are JARVIS. This is your own source code. Learn it like a developer
learns a codebase: modules, responsibilities, key patterns, how they connect.

## Architecture (12 boxes, 4 data flows)

```
User → Chat UI / CLI → Brain → Gate → Skills / PC Control / Memory
         ↑                ↓
    Session Store ←→ Approvals ←→ DCL
```

## Core Modules (jarvis/)

### brain.py — The Judgment Layer
- **What**: `Brain.respond(session_id, user_text)` → `TurnResult`. ReAct loop (max 3 rounds, 12 tool calls).
- **Key**: Slot-check in pure code BEFORE the model. Zero substring detection. Zero fake history.
- **FallbackChain**: Tries providers in order. Timeouts/connections → next provider. 401/403 → rotate key. 400 = terminal.
- **History**: `_load_history()` pulls last 20 exchanges from session store. `brain.reply` events logged.
- **Intelligence**: System prompt has INTELLIGENCE DIRECTIVE (forbidden phrases, act-don't-ask).

### gate.py — The Enforcer
- **What**: `Gate.check(tool_name, args, allowances)` → ALLOW / ALLOW_WITH_UNDO / REQUIRE_APPROVAL / DENY.
- **Order**: declared? → schema-valid? → capabilities? → tier route.
- **Tokens**: HMAC approval tokens embed sha256(tool + args). Tampered args → fail.
- **DCL**: `check_egress()` — SECRET→DENY, SENSITIVE→REQUIRE_APPROVAL. Missing DCL → fail closed.

### chat.py — The Wiring
- **What**: `ChatApp` connects everything. `turn()` → brain → approvals → output.
- **Brain chain**: configured Ollama local first → keyed cloud providers → OmniRoute → Pollinations keyless → stub. The actual chain is exposed by `/status` and the read-only `/doctor`; the last provider used is reported separately.
- **Commands**: `/status`, `/doctor`, `/key`, `/keys`, `/keymove`, `/provider`, `/memory`, `/recall`, `/skills`, `/session`.
- **Tool evidence**: `tool.result` records distinguish tool-reported success/failure from independently verified postconditions; postcondition verification remains explicitly false until a verifier exists.

### session_store.py — The Memory of Record
- SQLite WAL. Tables: sessions, events (ULID PK), checkpoints, tombstones.
- `emit()` append-only. `wake()` recovers from crash (replay, never re-execute).
- Event types: user.message, brain.reply, tool.call, tool.result, approval.*, etc.

### memory.py — Facts + Episodes
- **Facts** (semantic, versioned). **Episodes** (append-only log).
- Provenance: user > inferred > tool > web. Tool/web → quarantined.
- `forget()` = delete + FTS purge + VACUUM + checkpoint (13-step).

### dcl.py — Data Classification
- PUBLIC / PERSONAL / SENSITIVE / SECRET. `classify()` → max level.
- Tier A: salted-hash secret registry. Tier B: patterns (keys, cards, seeds). Tier C: PII.
- `redact()` replaces with [REDACTED:LEVEL]. Fail-closed: errors → SENSITIVE.

### skills/registry.py — The Jail
- Discovers `skills/*/skill.json`. Strict validation. Quarantine for new/changed.
- Dispatch: parse → schema → capability → gate → isolated call (5s, 10KB) → validate → evidence-wrap.
- Circuit breaker: 3 failures → auto-disable.

### ask_controller.py — When to Ask vs Act
- `decide(RequestAnalysis)` — 8-step rule. `price_ask()` — ASK iff G_u+G_a+G_c > C_i+C_t+C_l.
- `detect_underspec_signals()` — structural detection (no LLM introspection).

### verifier.py — Pre-execution Gate
- `TrajectoryVerifier.verify()` — 8 flaw checks F1-F8 (schema, preconditions, backup-order, unsafe tools, hallucinated IDs, approval evidence, scope, constraints).

### llm_*.py — Brain Providers
- `llm_ollama.py`: Local 7B. `timeout=120` (slow cold loads).
- `llm_compat.py`: 13 cloud presets + custom. `CompatProvider.timeout` = call timeout (60s).
- `llm_pollinations.py`: Keyless fallback. `llm_omniroute.py`: Gateway.

### config.py — Atomic Config + Secrets
- Atomic writes (tmp+rename). Corrupt → quarantine, never wipe.
- `Secrets`: keyring → Windows CredMgr → local file → env. Never logs values.

### Other Modules
- `rules.py`: Parses JARVIS-RULES.txt. P0 missing → refuse to start.
- `approvals.py`: Native dialogs, typed confirmations, budget (5/day), undo registry.
- `pc_control.py`: UIA-first. `observe`/`click`/`type`/`shell` (tier-3).
- `proactivity.py`: Call-ringing model. Watcher off by default.
- `phone.py`: Telegram R0/R1/R2. PIN-gated confirmations.
- `voice_loop.py`: 8-stage, echo-proof by construction, barge-in.
- `stt.py`/`tts.py`: Speech in/out. Speaker REQUIRES on_state callback.

## Skills (skills/)
- `echo/`, `notes/`, `clock/` — basic tools
- `knowledge/` — FTS5 search over research library + this codebase
- `web/` — internet search + fetch (no keys)
- `code/` — read/write/edit/run Python (sandboxed)

## Key Patterns (learn these)
1. **Brain judges, code enforces** — never the reverse.
2. **Fail closed** — unknown → deny, never allow.
3. **Evidence-wrap** — tool outputs marked untrusted, never obeyed.
4. **Atomic everything** — tmp+rename, never partial writes.
5. **Quarantine first** — new/changed/untrusted → isolated until approved.
