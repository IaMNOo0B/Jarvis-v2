# PUSHED — 2026-10-20 ~14:05 IST (owner's "analysis → fix → push" order)

Owner approved the push at 13:22 IST after analysis + fixes. FULL BATCH:
the entire local tree below, verified by the owner's agent personally —
**full suite 1862 passed / 0 failed** (own run on the still tree) before
pushing. This file is kept as the historical build log of the day.

## (Historical) PENDING PUSH — recorded 2026-10-20 ~11:23 IST

Owais was editing JARVIS on his PC himself; pushes were frozen until he
said the word. He later ruled: proceed with the local tree as-is.

## What's on GitHub remote (HEAD, verified)
- Commit 9624822: FLAN-style prompt (ROLE/TASK/...) + golden_pairs.py module
- All prior work: ask_controller, verifier, code skill, self-critique, TEACHING.md, CODEBASE.md, timeout fix, history

## What's LOCAL ONLY (unpushed — needs analysis before push)
1. `skills/reminders/` (NEW skill: SKILL.md, skill.json, skill.py) — set/list/cancel/due, persistent, rings per turn
2. `tests/test_reminders_skill.py` (NEW, 6 tests)
3. `jarvis/chat.py` — golden pairs LEARNING WIRING (detect_correction → PairStore save on correction, "Noted your correction" message); per-turn due-reminder ringing via purge_due; FIRST_PARTY_SKILLS += "reminders"; per-turn `_learned_context` injection into brain
4. `jarvis/brain.py` — `_learned_context` appended in `_system_prompt()`
5. `README.md` — test count 166 → 550
6. `hidden_check/reality_test.py` — internal reality-test script (not in push manifest, stays local)

## Conflict risk
Owais edits the same files on his PC (chat.py, brain.py most likely). When he
says "analysis and push": DIFF each file first, merge his changes with these,
run the full suite, then push ONE batch. Never push over his edits blindly.

## Reality-test finding (same session, unpushed) — ROOT CAUSE FOUND
Evidence (direct chain drive with the real 11,723-char system prompt):
- PollinationsCall with tiny messages: 3/3 OK
- SAME provider with the real system prompt: PollinationsConnectionError
  (transport failure) — the anonymous free tier chokes on big payloads,
  intermittently. Turn 1 in the reality test went through; turns 2..10 died.
CONCLUSION: code path is fine; the free keyless brain is the bottleneck.
Fix (NOT yet implemented — Owais is editing, so code is untouched):
  1. FallbackChain.respond: 1 auto-retry with backoff per provider on
     TRANSIENT_TRANSPORT (our own doctrine: one calm retry before giving up).
  2. chain_as_llm_call: surface `attempts` on failure so the app can show
     WHY (provider pill / logs), instead of archaeology to debug.
His keys (OpenRouter etc.) + the 60s timeout fix remain the real answer on
his PC; Pollinations stays last-resort only.

## Reality-test finding (earlier, unpushed)

## PhD implementations batch (2026-10-20, local only — Implementation General)
Audit of the FULL research library vs code: 68 mechanisms — 27 done, 21 partial,
15 missing, 5 N/A (audit: hidden_check/PHD-IMPLEMENTATION-AUDIT.md). Top 5 of the
missing implemented (stdlib, tested; suite 577 green):
1. jarvis/brain.py — FallbackChain transient retry+backoff (the reality-test fix)
   + stats()/suggested_order() provider trace stats
2. jarvis/recall_gate.py (NEW) + brain._memory_context — auto-recall every turn,
   gated by deterministic coverage (isair pattern, our code)
3. jarvis/memory.py — consolidate(): expire→dedupe→promote→confidence decay
4. jarvis/observability.py (NEW) — trace spans + JSONL, wired into brain.respond
5. tests/test_phd_implementations.py (NEW, 21 tests)
Note: Pollinations free tier rate-limited after ~1 call in the reality test —
evidence the free brain is unreliable; his own keys are the answer on his PC.

## Builders A–F batch + FINAL WIRING (2026-10-20, local only)
Six builder teams implemented the mega-scan/audit queue; the final wiring
pass connected the seams in jarvis/chat.py. FULL SUITE: **819 passed** in
one stable run (was 577 before this batch; 810 after builders A–F, +9
final-wiring tests). All files below are LOCAL ONLY, unpushed.

### New files
- `jarvis/completion_audit.py` (A) — post-execution delivery audit,
  attached to every TurnResult (brain + router paths)
- `jarvis/speech_policy.py` (B) — clean_for_tts: markdown strip, secret
  redaction, asymmetric clause chunking
- `jarvis/skill_foundry.py` (D) — skill solidification from traces +
  statistical anticipation
- `jarvis/plan_progress.py` (E) — checkbox plan progress (0 steps never "done")
- `jarvis/morning_digest.py` (E) — deterministic morning briefing, no LLM
- `jarvis/intent_router.py` (F) — deterministic grammar intent tier
  (exact 1.0 / fuzzy ≤0.8 / None), stdlib re+difflib
- `jarvis/system_phrases.txt` (F) — built-in VIRTUAL system intents
  (observe_screen / take_screenshot / launch_app / close_thing)
- `skills/clock/phrases.txt`, `skills/reminders/phrases.txt` (F) —
  grammar tables incl. Hinglish lines
- `jarvis-spec.Modelfile` (F, repo root) — Ollama speculative-decoding
  config for the RTX 2060 (speeds [MC] until benched on his card)
- `skills/system/` (C — SKILL.md, skill.json, skill.py) — system_status,
  volume, clipboard (DCL-redacted), brightness (honest stub), window_list
- `IMPLEMENTATION-LEDGER.md` (repo root) — the 364-mechanism tracking book
- Tests (all NEW): tests/test_builder_a_brain_resilience.py,
  test_builder_b_voice.py, test_builder_c_system_skill.py,
  test_builder_c_pc_ext.py, test_builder_d_memory_graph.py,
  test_builder_d_diary.py, test_builder_d_foundry.py,
  test_builder_e_proactivity.py, test_builder_e_plan_progress.py,
  test_builder_e_morning_digest.py, test_builder_f_intent_router.py,
  test_final_wiring.py

### Edited files
- `jarvis/brain.py` (A) — ErrorClassifier + provider parking on 429,
  ask_controller wired behind a conservative pre-filter (0% ask rate on
  a 24-input battery), filter_lesson anti-poisoning storage gate,
  CompletionAudit attach
- `jarvis/tts.py` (B) — interruption watermark on the chunk queue
- `jarvis/voice_loop.py` (B) — echo salvage + interrupt note
- `jarvis/pc_control.py` (C) — AppRegistry (learned name→path),
  launch_app ladder, find_text OCR fallback
- `jarvis/memory.py` (D) — fact graph edges (link/neighbors) + diary roll-up
- `jarvis/proactivity.py` (E) — watcher state ladder + CompletionBatcher
- `jarvis/chat.py` (FINAL WIRING) —
  1. IntentRouter built at startup (skills phrases + system table).
     In turn(), BEFORE brain.respond: exact 1.0 hits naming a real
     approved skill tool (now, reminder_set/list/cancel) dispatch
     through the SAME gate-first path as LLM tool calls (identical
     session events + completion audit; the gate sees every call).
     Virtual system.* intents and fuzzy matches NEVER execute here —
     they fall through to the brain (Brain.respond has no context
     parameter, so no hint injection; adding one is a brain change).
     Any router failure falls through — routing never breaks a turn.
  2. filter_lesson gates the correction→golden-pair save: corrections
     phrased as negative capability claims are skipped, never stored.
  README test count also needs 550 → 819 at push time.

### clean_for_tts wiring — WIRED (2026-10-20, local only)
- `jarvis/speech_policy.clean_for_tts` is now applied to live speech in
  the voice_loop path: `jarvis/voice_loop.py:659` (in
  `VoiceLoop.speak_text`, the single speech choke point) builds the
  Utterance Record from `speakable_sentences(text)` —
  `jarvis/voice_loop.py:92` — which passes every raw sentence through
  `clean_for_tts` (guarded import at voice_loop.py:31) and speaks the
  returned chunks in order, replacing the raw sentence list. A
  sentence that cleans to empty (e.g. a bare code fence) is skipped;
  if `clean_for_tts` raises or is unavailable, that sentence falls
  back to raw — speech never breaks and is never silenced by the
  cleaner. Because the record holds the CLEANED chunks, `spoken_text()`
  (what the brain may remember, incl. interrupt truncation) is exactly
  what left the speakers — never raw markdown, never a secret.
  Tests: `tests/test_clean_tts_wiring.py` (NEW, 14 tests).
  Full suite after this wiring: **1094 passed** (one stable run).
  NOTE: chat.py's start_voice()/_SentenceSink path (tts.Speaker) still
  hands raw sentences to engine.speak_sentence() — outside this pass's
  territory; wiring clean_for_tts there remains an open item.

### Push status
STILL FROZEN. Everything above waits for Owais's "analysis and push"
signal; at that point DIFF/merge HIS PC edits first (chat.py and
brain.py especially — both changed heavily in this batch), run the
full suite, then push ONE batch.

## Micro-wiring pass (2026-10-20, local only — jarvis/chat.py only)
Three seams connected in ChatApp; tests in tests/test_micro_wiring.py
(NEW, 7 tests). Full suite after this pass: **1122 passed** (one
stable run).

1. **Capabilities provider (Ext-1)** — in ChatApp.__init__, right
   before the single Brain(...) construction (the CLI and the GUI
   both reach Brain through ChatApp; there is no second site):
   `capabilities_provider_for(self.registry, pc_control.
   tool_definitions() if self._pc is not None else None)` is passed
   as Brain(capabilities_provider=...). The brain's "What you can do
   right now" prompt section is now LIVE data from the real registry
   (+ synthetic pc group when PC control is on), rebuilt per prompt.
2. **Evolution runner hook (Ext-7)** — at the very start of
   ChatApp.turn: the cheap guard runs every turn
   (`should_run(read_last_run(data_dir), now, last_user_turn=
   last_user_turn_at(store))`); when it fires, `run_review(data_dir,
   store, memory, now)` runs the once-a-day idle self-review
   (foundry scan, diary, consolidation). Fully wrapped: any failure
   is swallowed with an `evolution.review_error` session event —
   a review can never break a turn.
3. **PhoneRemote data_dir (Ext-3)** — ChatApp.start_phone now passes
   `data_dir=str(self.data_dir)` to PhoneRemote(...). Without it,
   Ext-3's persistence (allow-always allowlist + reconnect
   watermark) silently never activated.

## CapNet wiring pass (2026-10-20, local only — jarvis/chat.py + jarvis/brain.py surgical)
The unified capability network (jarvis/capnet.py) is LIVE in the turn
loop; tests in tests/test_capnet_wiring.py (NEW, 12 tests). Full suite
after this pass: **1312 passed** (one stable run).

1. **Network in the prompt** — Brain gains an optional
   `network_provider` kwarg (capabilities_provider API unchanged —
   the micro-wiring tests pin it to returning CapabilityMaps).
   `_capabilities_section` now prefers `_network_section`:
   capnet.describe() REPLACES the plain summary (superset:
   alternatives + routing rules, no double prompt cost), cached per
   session on the network fingerprint; any failure falls back to the
   summary path. ChatApp passes `network_provider=
   self._capability_network`, which aggregates the live registry +
   PC tool table + the brain's FallbackChain + this session's
   capnet outcome scores (health_scores) and keeps the snapshot on
   `self._network`.
2. **Pre-turn routing** — in ChatApp.turn, AFTER the intent tier
   (deterministic intents still win): `_capnet_route_turn` runs
   capnet.select, records a `capnet.plan` event (chosen + reason)
   EITHER WAY, and dispatches only plans passing the strict bar in
   `_capnet_dispatchable`: chosen node is a skill tool, tier 1,
   health available, top score carries the direct-name boost (the
   user NAMED the tool in the text — keyword-only matches count as
   fuzzy and NEVER execute), real in an approved skill's manifest,
   and the brain tool takes no required arguments. Dispatch reuses
   `_dispatch_routed` (now parameterized with `via=`) so the event
   stream is identical to the intent tier's, with `via: "capnet"`.
3. **Outcome feedback** — turn() captures a seq watermark before
   routing; `_record_turn_outcomes` (called on both the normal and
   the approval paths, fully wrapped) reads the turn's events back:
   each tool.result is mapped through its causal-parent tool.call to
   a capnet node id (tool:<name>; pc.* keep their dotted name) and
   recorded via record_outcome; when the brain served the turn, the
   chain's answering provider (chain.last_via) earns a
   provider:<name> outcome. Tier-dispatched turns record NO provider
   outcome — no credit for work not done.
4. **/capabilities command** — `/capabilities` prints
   capnet.describe (wider 4000-char budget for humans);
   `/capabilities <name|node-id>` prints capnet.explain (purpose,
   use/avoid, needs, alternatives, measured record). Added to /help.
5. **STT chain in start_voice** — the transcriber is now built via
   `stt.create_transcriber(engine="auto")` (TranscriberChain:
   hinglish -> whisper -> stub) instead of a bare
   FasterWhisperTranscriber(); the loud-failure try/except is
   unchanged. Seam-tested by monkeypatching create_transcriber.

## Voice Pack (Team 7 steals) — RE-DISPATCH landed 2026-10-20

The first voice-pack worker ended silently with NOTHING in the tree
(verified by grep, reported to Owais). This re-dispatch delivered:

1. **Learned endpointing** — NEW `jarvis/endpointing.py`:
   `EndpointPolicy` = LiveKit DynamicEndpointing (EMA alpha 0.9 over
   the owner's observed pauses, seed 0.5s, floor = false-EOT ratchet,
   threshold clamped [0.3, 3.0]s, atomic JSON persistence in the data
   dir, corruption -> defaults). Wired in `jarvis/voice_loop.py`:
   `TRAILING_SILENCE_S` is now the policy's SEED (identical behavior
   with no learned data); `_collect` ends utterances on
   `policy.threshold_s`; between-utterance gaps feed `observe_pause`,
   and a resume within 2s of an endpoint feeds `observe_false_eot`.
2. **Barge-in classification** — `jarvis/voice_loop.py`:
   `classify_interrupt(text)` (pure) over ONE data table
   (`BACKCHANNEL_PHRASES` / `STRONG_INTERRUPT_PHRASES`, EN + roman
   Hinglish + Devanagari, matched on translit-canonicalized text).
   Backchannels NEVER interrupt — not even "haan accha theek" (3 novel
   words, which the bare novel-word rule used to cut on). Strong
   commands (stop/ruko/bas/cancel/chup/रुको/बस/बंद करो/चुप) cut
   immediately. protoVoice 350ms hold-gate = `InterruptHoldGate` +
   episode probation in `_check_barge_in`: unconfirmed candidates'
   words roll back out of the detector accumulator if the episode
   dies inside the window; confirmed verdicts flush immediately
   (protoVoice transcript-flush semantics — pinned word-exact
   interrupt tests forbid delaying them).
3. **VAD guard** — `_collect`: a recognizer stream raising mid-
   utterance (or a 25-chunk VAD error streak) ends collection with
   the partial audio PRESERVED (still goes to STT) and a
   `voice.vad_guard` session event; the turn continues honestly.

Tests: `tests/test_voice_pack.py` — 63 tests. Full suite after this
batch: **1532 passed, 0 failed** (one stable run, ~63s; the tree
total includes sibling teams' concurrently landed work).

STILL FROZEN. Push waits for Owais's "analysis and push" signal;
DIFF/merge his PC edits first (chat.py and brain.py changed heavily
in this batch), run the full suite, then push ONE batch.

## Recovery wiring batch (2026-10-20, local only)

The recovery pack (jarvis/effects.py + jarvis/contracts.py + gate
hooks, landed earlier) is now LIVE in the turn loop:

1. `jarvis/chat.py` — Gate built with the recovery hooks:
   `effect_sink=effects.make_store_sink(store)`,
   `effect_fs_root=<data_dir>`, `fact_exists` probe over Memory,
   `postcondition_evaluator=contracts.make_evaluator(fs_root, memory)`,
   and a contract_sink stashing failed reports per
   (session_id, turn_id, tool) in `ChatApp._contract_reports`
   (TAKE semantics via `_take_contract_report`). gate_registry entries
   copy each manifest tool's `effects`/`postconditions`. Brain gets
   `contract_lookup=self._take_contract_report`. Routed dispatch
   (`_dispatch_routed`) executes THROUGH `gate.dispatch` (turn-scoped
   to its user.message event id) and stamps tool.result via
   `contracts.mark_result`; a failed contract makes the reply say so.
   The approval branch passes `session_id`/`turn_id` (the turn's
   user.message event id) to `gate.execute_approved`.
2. `jarvis/brain.py` — new `contract_lookup` kwarg. The Act step's
   turn id is the turn's user.message event id. Execution goes
   through `gate.dispatch(session_id=, turn_id=)` when the gate
   provides it (raw result captured via closure; network-bound tools
   pass their args as the egress payload); check-only gates keep the
   legacy direct call bit-for-bit. Failed postconditions stamp the
   tool.result payload (CompletionAudit: NOT delivered). Typed
   failures climb `contracts.recover` — retry(1) → substitute (CapNet
   alternative via network_provider, own tool.call event,
   `via="recovery_substitute"`) → escalate: `recovery.escalated`
   event + the REFLECT causal line appended to the tool message.
   Per-turn `recovery_history`; the ladder cannot loop.
3. `/undo-turn` (chat.handle_command, CLI + GUI): reverses the LAST
   session turn that journaled effects via `effects.undo_turn`
   (reminder canceller resolves the journaled reminder TEXT to a
   pending id and cancels through the registry executor). The reply
   lists reversed effects with actions and NOT-reversed ones with
   reasons — never a blanket "undone".
4. Manifest contracts (first-party, honest only): code_write +
   code_edit — effect file `code/{args.path}`, postcondition
   file_exists same; notes_write — effect file `notes/{args.path}`,
   postcondition file_exists same (notes keeps no .bak, so undo of an
   overwrite honestly reports "no snapshot"); reminder_set — effect
   reminder `{args.text}` (the id is minted inside the skill; text is
   the journal's identifier), postcondition file_exists
   `reminders/reminders.json`. reminder_cancel declares nothing (no
   closed-vocabulary check can verify a cancel).
5. `tests/test_recovery_wiring.py` (NEW, 9 tests) — incl. the E2E
   proof: real ChatApp turn → real code skill writes through the gate
   → journal shows the effect (turn 2: existed_before=True,
   before_value_ref=code/demo.txt.bak) → /undo-turn restores the
   original content; a postcondition-failure turn retries once,
   escalates with its causal line, and audits NOT delivered.

Full suite after this batch: **1584 passed, 0 failed** (two stable
runs, ~66-70s; total includes sibling teams' concurrently landed
work). NOT wired (territory boundary): phone.py's gate.dispatch call
still passes no session/turn ids, so phone-dispatched effects do not
journal yet.

STILL FROZEN. Push waits for Owais's "analysis and push" signal;
DIFF/merge his PC edits first (chat.py and brain.py changed heavily
in this batch), run the full suite, then push ONE batch.

## Final seams pass (2026-10-20, local only — tests/test_final_seams.py)

The owed one-line wirings, closed. Each seam is proven CONDUCTING by a
test that drives the live surface, not the helper in isolation.

1. **phone.py turn ids — NOT WIRED HERE (exact one-liner for the
   phone.py pass).** The only un-scoped dispatch lives inside
   phone.py, outside this pass's territory, and there is no chat-side
   call site: `PhoneRemote._execute_approved` (~line 735) calls
   `self.gate.dispatch(tool_name, args, [...], tracking_executor)`
   with no session/turn ids, so phone-confirmed effects do not
   journal. The fix, when phone.py is in scope: give PhoneRemote a
   `session_id` (parent passes its phone session id at construction,
   next to `data_dir=`) and change that one call to
   `self.gate.dispatch(tool_name, args, ["fs.write", "fs.read",
   "time.read"], tracking_executor, session_id=self.session_id,
   turn_id=pending["cid"])` — the pending confirmation id is the
   natural per-command turn id. (Brain-path phone turns already
   journal: brain_fn routes through Brain.respond, which is scoped.)
2. **RoutineGuard call site — WIRED** (jarvis/chat.py). ChatApp.turn
   calls `_maybe_morning_digest()` right after the evolution hook.
   `_routine_guard()` lazily builds one RoutineGuard over the data
   dir with a single-row schedule: morning_digest due 05:00 local,
   window 05:00–12:00, catch_up_minutes=420 (a first turn anywhere
   in the window still gets its briefing), budget_s=30. begin()
   claims the period BEFORE the digest runs; the digest prints as a
   "[morning digest]" proactive block; outcome finishes the claim.
   A first contact after noon records the period MISSED (never
   replayed). Fully wrapped — failures are noted as
   `routine.digest_error`, turns never break. ORDERING (bug found by
   the HUD team, fixed in this pass): the claim + print happen at
   turn start, but the session events are STASHED and flushed at
   turn end as children of the turn's opening user.message
   (causal_parent = its event id) — a routine event may never
   precede the user.message that gives the turn its identity.
   Regression-locked in test_final_seams.py.
3. **GUI sentence sink → clean_for_tts — WIRED** (chat.py
   start_voice, _SentenceSink.flush). The buffered sentence now goes
   through jarvis.speech_policy.clean_for_tts and each returned
   chunk is spoken in order — the GUI voice path can no longer read
   out markdown or a secret. Same fallback discipline as voice_loop:
   cleaner raises → the raw sentence is spoken; cleans to [] → the
   sentence is skipped; speech never breaks.
4. **shell_guard into pc_control — WIRED** (jarvis/pc_control.py
   run_in_terminal). The deciding check is now
   `shell_guard.check_command(command, legacy_check=_check_blocklist)`:
   the legacy raw-string blocklist runs FIRST inside the guard (its
   reason strings preserved), then the tokenised guard screens what
   regexes cannot see — proven by test: `r"m" -rf /` and
   `rm --recursive --force /` pass the legacy layer untouched and
   are refused by the guard, reaching no shell. Refusals still raise
   BlockedCommandError on the existing path, logged as
   pc.shell_blocked with the verdict's reason + rule.
5. **Startup configuration — WIRED** (ChatApp.__init__).
   (a) The PC controller is now built with the learned AppRegistry
   (SQLite at <data_dir>/app_registry.db) constructed explicitly and
   passed as `app_registry=` — guarded: if the registry file cannot
   be created/opened, app_registry stays None and PC control works
   without the learned launch rung. (Before this, ChatApp built
   PCController with no data_dir/app_registry at all, so learned
   apps NEVER activated on the real app path.)
   (b) Ext-6's `dcl.configure_registry(str(data_dir))` is called at
   startup (guarded), pointing the DCL secret registry at the app's
   data dir so registered secrets persist (digests only).
6. **CapNet node for web_fetch_tree — WIRED** (jarvis/capnet.py).
   `_GROUP_BY_TOOL["web_fetch_tree"] = "page_reading"` (web_fetch is
   its alternative) + a `_TOOL_INTEL` entry (use_when: page
   structure / element tree / form fields / buttons on the page /
   structured page; avoid_when: text-only reads — web_fetch is
   lighter; offline). The node appears in describe() and the router
   selects it for structure-shaped asks (test-proven).
7. **Patterns surface — WIRED** (jarvis/chat.py). Startup: when
   PatternStore(data_dir).pending() is non-empty, ChatApp prints ONE
   line — "[patterns] I noticed a few patterns — ask me about them
   when ready (/patterns)." — no modal, no ringing. `/patterns`
   lists pending proposals numbered; `/patterns confirm <n>` keeps
   one (PatternStore.confirm with the app's Memory → becomes a
   fact); `/patterns decline <n>` dismisses it through
   PatternStore.decline — the durable suppression path (verified
   across a fresh store: declined keys stay suppressed and out of
   pending). Added to /help.
8. **Wake word in start_voice — WIRED** (jarvis/chat.py). The
   wake_fn stub ({"detected": False} forever) is replaced: the real
   engine is built ONCE via jarvis.wakeword.create_wake_engine()
   (Voicute -> openWakeWord factory preference). wake_fn feeds each
   chunk to engine.feed_frame and maps WakeDetection ->
   {detected, score, word} (non-firing chunks report the engine's
   last_score). When no engine is available, the factory's exact
   reason prints once ("[voice] Wake word unavailable: ...") and
   the stub behaviour holds — never a crash, never a faked wake.
   A mid-loop feed exception degrades that chunk to "no wake".

Tests: tests/test_final_seams.py (NEW, 14 tests — 13 seams + the
ordering regression). test_final_seams.py + test_final_wiring.py
together: 23 passed, 0 failed (post-fix).
Full suite after this pass: **1843 passed, 2 failed**. Both failures
are in tests/test_code_upgrade.py (the code-skill upgrade team's
file, landed mid-session — the tree total grew 1767 -> 1845 between
runs): its code_verify verdict tests (test_verify_full_after_fix,
test_verify_full_with_repro) spawn real pytest subprocesses inside
the skill sandbox. The failing set ROTATES between runs (2-3 of the
verdict tests), every named test passes solo, and the machine was
at load average 5-7 throughout — consistent with the sandboxed
nested runs degrading under load, NOT with these seams (no file in
that path was touched here). Flagged for the code-upgrade team;
their call, their territory.

