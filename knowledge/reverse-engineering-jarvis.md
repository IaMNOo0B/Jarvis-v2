# Reverse-Engineering the Best Working JARVIS Builds — Mechanism Studies

*Compiled 2026-10-20. Method: read the actual core source files of four working JARVIS repos via the GitHub API (no README-only claims). Every mechanism below cites the file it was read in. Where a "clever feature" turned out to be a library call or config, that is stated plainly.*

License postures for JARVIS v2 (personal, non-commercial, public repo):
- **open-jarvis/OpenJarvis — Apache-2.0** → code reuse ALLOWED with attribution + NOTICE.
- **isair/jarvis — custom non-commercial license** (© Baris Sencan): copy/modify allowed for non-commercial use only, derivatives must keep the same terms → code copy would relicense v2; **ideas only** is the safe posture.
- **ethanplusai/jarvis — custom personal/non-commercial license** (© Ethan Rogers, 2026): "use, copy, modify, and run for personal, non-commercial purposes" → same caveat; **ideas only** recommended.
- **PanPenek/JarvisAi — NO LICENSE file** → all rights reserved by default → **ideas only** (its best trick is a PowerShell/.NET technique, not their code anyway).

---

## 1. isair/jarvis (2,111★) — custom NC license → ideas only

### 1.1 The Recall Gate — `src/jarvis/memory/recall_gate.py` (~96 lines, self-contained)

**What it is.** Before any long-term memory enrichment (diary recall, graph hops, memory digest) runs for a query, a *deterministic, zero-LLM* check decides whether it's worth it:

1. Tokenize query + recent "hot window" messages into content words: regex `\w{3,}`, lowercased, Unicode-aware (any script), minus a stopword set, minus digit-only runs.
2. `should_recall()` returns **False** (skip enrichment) only when BOTH hold: (a) the hot window contains at least one fresh tool-result message, and (b) ≥ 50% of the query's content words already appear in the hot-window text (coverage, deliberately asymmetric — the window is always bigger than the query).
3. Fail-open: any doubt → recall runs.

**Why it works.** Memory enrichment is the most expensive invisible cost in a chat loop — tokens, latency, and context bloat on every turn, even when the answer is already on screen. This gate costs microseconds, never calls a model, and its skip condition is conservative (needs both freshness *and* topical coverage), so false skips are rare.

**v2 steal.** New small module `jarvis/recall_gate.py` (~60 lines, pure `re` + `typing` — fully stdlib). Wire into `jarvis/brain.py` `respond()`: before building the history + memory digest portion of the prompt, run the gate against the loaded history window; skip the semantic-memory injection when the gate says the conversation already covers the query. Effort: half a day including tests. **This is the single cleanest steal in this entire study — small, deterministic, saves tokens on every turn.**

### 1.2 The Intent Judge — `src/jarvis/listening/intent_judge.py` (~560 lines) + `llm/tiers.py`

**What it is.** A two-tier model split (`llm/tiers.py`): `Tier.FAST` = a small warm model (~2B, strict-JSON, latency-bound) for all classification passes; `Tier.CHAT` = the capable model for replies/planning/summaries — every context declares its tier, routing lives in exactly one function (`resolve_model`). On top of that, `IntentJudge` classifies each ambient utterance with the FAST model, returning strict JSON `{directed, stop, confidence, reasoning}`. Two prompt regimes:
- **Wake mode** — default *not* directed; the hard problem solved in-prompt is addressee resolution: mentioning the name ≠ addressing it ("I'm talking to Jarvis, not you" → `directed=false`), across languages (examples include Turkish and Spanish).
- **Hot-window mode** (already engaged) — default directed=true; fragments, thanks, and one-word follow-ups count; exceptions are other-person speech and pure TTS echo.

Two supporting details worth copying: `_extract_json_object()` — a brace-depth scanner that respects string literals/escapes and can take the *last* balanced object (reasoning models bury the verdict at the end of their thinking); and the judge failure path has a 30 s error cooldown so a dead judge model doesn't stall every utterance.

**Why it works.** "Was that meant for me?" is the core unsolved problem of ambient listening; wake words alone can't do addressee resolution. Splitting classification onto a permanently warm tiny model makes the judgement cheap enough to run on *every* utterance, and strict-JSON + robust extraction makes a 2B model's output parseable in practice.

**v2 steal.** Lands in `jarvis/voice_loop.py` (+ a FAST tier in `jarvis/brain.py`'s `FallbackChain`): (a) adopt the two-regime idea as *rules first* — v2's deterministic gate can encode the hot-window defaults (engaged window → treat fragments/one-word replies as directed; outside → require wake evidence) at ~40 lines, no model needed for the common cases; (b) copy `_extract_json_object`'s *algorithm* (brace-depth + string-aware, ~50 lines, stdlib) into `jarvis/brain.py` for parsing tool-call/JSON blocks from small local models — v2's Ollama 7B output parsing gets measurably more robust. License: ideas/algorithm only (NC license).

### 1.3 Graph Memory with Decay — `src/jarvis/memory/graph.py` (~950 lines) + `memory/db.py`

**What it is.** Long-term memory as a **tree of nodes in SQLite** (`memory_nodes`: id, name, description, data, parent_id, access_count, last_accessed, created/updated, data_token_count; plus a revisions table). Facts are normalized/deduped by `normalise_fact()` into branch fact-keys. Retrieval ranking uses a **decay score in SQL** (`_decay_score_sql`, half-life in days) combined with access counts — stale, never-touched branches sink. A set of SQLite triggers maintains a "warm profile" revision counter that bumps whenever any ancestor of the user/directives branches changes, so the always-injected profile block is rebuilt only when it actually changed. `get_graph_data(root, max_depth)` emits the tree as nested dicts — that is what powers the graph viewer in their desktop app; the viewer itself is just a renderer of this API.

**Why it works.** Flat fact lists rot: duplicates pile up, nothing expires, and prompt injection of "everything we know" grows unboundedly. A parented tree gives natural scoping (project → topic → fact), decay gives forgetting for free, and token counts per node make prompt-budget decisions mechanical.

**v2 steal.** v2's `jarvis/memory.py` already has episodic+semantic tiers and FTS5. Don't replace it — add the two cheap parts: (a) **decay scoring** on semantic facts (an `access_count`/`last_accessed` pair + a half-life multiplier in the BM25 ranking query, ~30 lines of SQL/Python); (b) a `get_tree()` export (~40 lines) so a future viewer or the chat GUI can render memory as a tree. The full graph rewrite (~950 lines there) is NOT worth it for v2.

---

## 2. open-jarvis/OpenJarvis (11,631★, Stanford Hazy Research) — Apache-2.0 → code reuse allowed with attribution

### 2.1 Morning Digest = a declarative preset, not a feature — `configs/openjarvis/examples/morning-digest-{minimal,linux,mac}.toml`

**What it is.** The famous "morning digest" is a ~30-line TOML config: `[engine] default`, `[intelligence] default_model`, `[tools] enabled = ["digest_collect", "text_to_speech"]`, `[digest] enabled/persona/honorific/tts_backend/voice_id/sections`, and per-section sources (`[digest.messages] sources=["gmail"]`, `[digest.calendar] sources=["gcalendar"]`). Three variants ship for different setups. A scheduler runs the configured collectors, an LLM writes the digest in the configured persona, TTS reads it.

**Why it works.** Zero code per user: the product decision ("a digest is a *preset over generic machinery*") means new digests (evening recap, repo monitor — see `scheduled-monitor.toml`) are configs, not features. This is the honest finding: **the mechanism is an architecture choice, not an algorithm.**

**v2 steal.** A `digest` skill for v2 (~120 lines stdlib: a TOML/JSON preset in the data dir listing sections + sources, a collector step reusing the existing web/notes skills, brain writes it, `jarvis/tts.py` speaks it) plus one entry in `jarvis/proactivity.py`'s scheduler. v2 already has 80% of the parts; the steal is the *preset pattern*: ship `morning-digest.json` in the skills dir so Owais edits a file instead of asking for a feature. (v2 config is JSON via `jarvis/config.py` — `tomllib` is stdlib in 3.11+ if TOML is preferred.)

### 2.2 Trace → Analyzer → Optimizer loop — `src/openjarvis/traces/{collector,analyzer,store}.py`, `src/openjarvis/learning/optimize/{optimizer,llm_optimizer,trial_runner}.py`

**What it is.** `TraceCollector` wraps any agent: it subscribes to the internal EventBus during `run()`, converts inference/tool/memory events into `TraceStep`s, appends a final RESPOND step, and persists a full `Trace` (query, model, engine, steps, messages, totals for latency/tokens/energy). `TraceAnalyzer` is a read-only aggregation layer producing per-route stats (`RouteStats`: model+agent → count, avg latency, avg tokens, **success_rate**, avg user feedback), per-tool stats, and per-step-type distributions using `statistics`. `OptimizationEngine` then runs propose → evaluate → analyze → repeat: an `LLMOptimizer` proposes config changes inside a declared `SearchSpace`, `TrialRunner` executes them against objectives (accuracy, latency, cost, energy…), results persist in an `OptimizationStore`, and the analyzer's route stats feed routing-policy updates.

**Why it works.** Self-improvement stops being vibes: every claim ("route X is better") is backed by measured success rates over real usage, and changes are *trials* with objectives, not edits. The analyzer is deliberately read-only and separate from the collector — measurement can't corrupt execution.

**v2 steal.** v2's `jarvis/session_store.py` already records every event (emit/wake) — the raw material exists. Add a read-only `jarvis/trace_stats.py` (~150 lines, stdlib `statistics` + sqlite queries over the existing event log): aggregate per-provider success/latency (the FallbackChain currently picks providers blind — feed it measured success rates), per-tool failure counts (feeds the skills registry's circuit breakers with real data), and per-turn token estimates. Skip the LLM-optimizer half — v2 has no config search space worth optimizing yet; the *measurement* half is the steal. Apache-2.0: code patterns may be adapted with attribution if desired.

### 2.3 Skill mining from traces — `src/openjarvis/skills/manager.py::discover_from_traces` + `learning/agents/skill_discovery.py`

**What it is.** `SkillManager.discover_from_traces(trace_store, min_frequency=3, min_outcome=0.5)` loads up to 10,000 traces, runs `SkillDiscovery.analyze_traces()` to find **recurring tool sequences that succeeded**, and writes each as a `skill.toml` manifest into `~/.openjarvis/skills/discovered/` (names normalized to kebab-case), where the normal skill loader picks them up. The wider skill system (loader/parser/executor/overlay/security in `skills/`) treats hand-written, imported, and machine-discovered skills identically.

**Why it works.** It closes the loop between 2.2's measurement and behavior: if the user makes Jarvis do the same 4-tool dance every week, the system notices and crystallizes it into a named, reusable skill — no human authorship. Frequency + outcome thresholds keep junk sequences out.

**v2 steal.** A pale version fits v2's scale: a nightly/offline pass in `jarvis/memory.py` (or the knowledge skill) that scans the session store for repeated tool-call n-grams (≥3 occurrences, gate-approved outcomes) and *proposes* them — written into the skills dir in **quarantine** state, which v2's registry already supports (skills stay quarantined until `approve()`). ~120 lines. The v2-specific twist — discovered skills start quarantined behind the existing approval gate — makes auto-discovery safe in a way OpenJarvis's version isn't.

---

## 3. PanPenek/JarvisAi (17★) — NO LICENSE → ideas only

### 3.1 Screen OCR with coordinates via Windows' built-in OCR — `jarvis/tools/desktop.py::read_screen/_ocr_image/find_on_screen`

**What it is.** No Tesseract, no vision model, no pip OCR dependency. The code: `pyautogui.screenshot()` → PNG in temp dir → a **PowerShell script using `Windows.Media.Ocr.OcrEngine`** (the OCR built into Windows 10/11, `TryCreateFromUserProfileLanguages`) with the standard WinRT `Await` shim → for each recognized line, union the word bounding rects and emit `"line text | cx,cy"` (center coordinates). `find_on_screen(text)`: exact case-insensitive substring match first → else word-overlap scoring across lines (best overlap wins) → if still nothing, scroll down once and retry. Returned coordinates feed `click_at(x, y)`. Window focus is the same pattern (PowerShell + `user32` `SetForegroundWindow`), media control is pyautogui media keys.

**Why it works.** The "library" here is the operating system: Windows ships a decent OCR engine, so the whole vision fallback is ~90 lines of stdlib `subprocess` + one screenshot call. The `text | x,y` line format is the clever bit — it makes OCR output directly actionable by an LLM (find → click) with zero further geometry code.

**v2 steal.** v2's `jarvis/pc_control.py` is UIA-tree-first by design; the missing piece is the fallback when UIA returns nothing (games, canvas apps, remote desktops). Add `pc.find_text` (~80 lines): screenshot (already RAM-only in v2) → temp PNG → PowerShell Windows-OCR (script adapted from the *technique*; write our own quoting-safe version — see 4.3) → parse `text | x,y` → word-overlap match → return coords into the existing tier-1 observe / tier-2 click flow. Fully stdlib on Windows (`subprocess`, `tempfile`). This is v2's highest-value PC-control gap and it costs no dependency.

### 3.2 The 31-tool flat router — `jarvis/tools/router.py` + `jarvis/tools/system.py`

**What it is.** Deliberately un-clever, and worth reporting honestly: a `TOOL_MAP` dict of lambdas (name → function) beside a parallel `TOOL_SCHEMAS` list (OpenAI function-calling JSON). The *value* is the inventory: beyond the usual web/files/apps it includes clipboard get/set, volume get/set, brightness, lock screen, power commands, toast notifications, and `set_timer(seconds, message)` — the small system tools a desktop assistant is actually asked for daily. Timers/notifications live in `system.py` as thin OS calls.

**v2 steal.** A `system` skill for v2 (~100 lines): `clipboard_read/clipboard_write` (PowerShell `Get/Set-Clipboard`, tier-1/tier-2 respectively), `volume`, `timer` (a timer is just a scheduled proactivity ring — v2's `proactivity.py` call-ringing model absorbs it naturally), `notify` (toast via PowerShell). All stdlib, all behind existing gate tiers. Low glamour, high daily-use value.

---

## 4. ethanplusai/jarvis (895★) — custom personal/NC license → ideas only

*Context: this build supervises Claude Code sessions; its proactivity machinery watches agent sessions, not the desktop. The mechanisms transfer to v2's session/task watching.*

### 4.1 The watcher state machine — `session_watch.py::_derive_state` + `SessionState`

**What it is.** A poll loop tails session rosters + transcript JSONLs and derives one state per session with a strict precedence ladder: process dead → `GONE`; alive but never prompted → `FRESH`; any roster entry `waiting_for` → `NEEDS_YOU` (with the reason attached); status `waiting` → `NEEDS_YOU`; `busy` → `WORKING`; `shell` → `SHELL`; **idle but the transcript tail used a question tool or the last assistant text "looks like a question"** (`_looks_like_a_question`) → `NEEDS_YOU`. Two policy properties sit on top: `announceable` (FRESH sessions are never spoken about unprompted — nobody started them) and `needs_a_human_hand` (the wait reason matches a keyword set of things that cannot be answered remotely → escalate immediately, in person). Completions, by contrast, are batched into recaps rather than announced one-by-one (the announce policy layered over these states in `server.py`). A related guard, `_mark_primary` with `PRIMARY_MARGIN_SEC = 120`: if two sessions were touched within 120 s of each other, *neither* is declared primary — "a guess wearing a fact's clothes" is refused.

**Why it works.** The ladder is ordered by *certainty*: hard signals (process liveness, explicit waiting flags) outrank inferred ones (question-shaped text) — exactly the inference v2's proactivity needs. And the asymmetry is the product insight: **blocked-on-human is urgent and singular; finished is informational and batchable.** Owais's call-ringing model already encodes this philosophy; this is a worked implementation of it.

**v2 steal.** Port the ladder's shape into `jarvis/proactivity.py`'s Watcher (~70 lines): when v2 watches long tasks (its own background work, downloads, builds), classify state by precedence — explicit blocked/approval-pending beats inferred stuck; FRESH (never-started) items never ring; completions accumulate into one batched ring. Add the `_looks_like_a_question` tail-check as the lowest rung only. Also steal the margin rule for any "which session is primary" logic: inside the margin, say "tied" instead of guessing.

### 4.2 Progress judged from plan checkboxes — never from claims — `builds.py::parse_plan` + `specs.py::_progress_of`

**What it is.** `parse_plan(text)` parses a plan markdown file: `## Task N: title` headings open tasks; GitHub checkbox lines under each heading count as steps (`[x]` done / `[ ]` open); checkboxes before the first heading are ignored. `PlanTask.done` is true **only when steps_total > 0 and every step is ticked** — a task with no steps is *never* done ("claiming a build finished because a heading had nothing under it is exactly the class of lie the run pipeline exists to prevent"). `specs._progress_of()` is a thin, deliberately non-duplicated wrapper (one parser, so two surfaces can never disagree) returning `{done, total, current (first unticked task), current_section, steps_done, steps_total}` — that dict is what gets spoken/displayed as progress.

**Why it works.** Progress comes from an artifact the worker must physically edit (the plan file), not from the worker's self-report. The "no steps = not done" rule kills the most common false-completion mode. One canonical parser prevents UI/voice surfaces from drifting apart.

**v2 steal.** Directly aligned with v2's tracking ethos: add `jarvis/plan_progress.py` (~60 lines, pure `re`): parse `- [ ]`/`- [x]` under task headings in any plan file Owais keeps, expose `{done,total,current}`, and let `proactivity.py` announce *measured* progress ("3 of 7 steps done; current: X") instead of model-estimated progress. Zero dependencies; the parser is ~30 lines of the total.

### 4.3 Untrusted text never enters script source — `notifier.py` (macOS notifier)

**What it is.** When notifying with text that originates in someone else's transcript (attacker-influenceable), the module refuses the usual "escape quotes and interpolate" approach: the AppleScript is a **fixed** `on run argv` handler read from stdin, and title/message/subtitle are passed purely as trailing **argv** strings — data, never parsed as script source. "There is no escaping step to get wrong because there is nothing to escape." Length caps (120/120/300) and a 5 s subprocess timeout bound the rest.

**Why it works.** Escaping is a bug farm (PanPenek's `focus_window` escapes `'` by doubling — one missed case from injection). Argv-passing removes the entire class structurally: it's *structure over detection*, the same principle as v2's gate design.

**v2 steal.** Audit-and-fix task, not a new module: v2's `pc_control.py` (and the new `pc.find_text` from 3.1) invoke PowerShell with interpolated strings. Convert every dynamic value (window titles, search text, file paths) to environment variables or `-File`/stdin-passed scripts with `$args`, so untrusted text (window titles are attacker-controlled — any app can set one) never becomes PowerShell source. ~1–2 hours across `pc_control.py`; add a verifier rule (F4-style) flagging string-interpolated shell construction in skill code.

---

## Ranked steals for JARVIS v2 (value × ease, stdlib-only)

| # | Steal | From | Lands in | Size | Why first |
|---|-------|------|----------|------|-----------|
| 1 | Recall gate (skip memory enrichment when hot window covers query) | isair | `jarvis/recall_gate.py` + `brain.py` | ~60 lines | Deterministic token savings on every turn; fail-open; zero risk |
| 2 | OCR fallback `pc.find_text` via Windows built-in OCR (`text \| x,y` format) | PanPenek | `jarvis/pc_control.py` | ~80 lines | Closes v2's biggest PC-control hole (UIA-blind apps); no new dependency |
| 3 | Plan-checkbox progress parser | ethanplusai | `jarvis/plan_progress.py` + `proactivity.py` | ~60 lines | Honest progress for watched tasks; kills false "done" claims |
| 4 | Trace stats over the existing event log (per-provider/tool success rates) | OpenJarvis (Apache — attribution OK) | `jarvis/trace_stats.py` | ~150 lines | v2 already logs everything; makes FallbackChain + circuit breakers data-driven |
| 5 | Watcher state ladder + batch-completions/ring-on-blocked policy | ethanplusai | `jarvis/proactivity.py` | ~70 lines | Formalizes Owais's call-ringing model with a certainty-ordered ladder |
| 6 | Morning-digest preset pattern | OpenJarvis | new `digest` skill + preset file | ~120 lines | High daily value; v2 already owns 80% of the parts |
| 7 | Robust JSON-object extraction (brace-depth scanner) | isair | `jarvis/brain.py` | ~50 lines | Hardens small-model tool-call parsing |
| 8 | Small system tools (clipboard, volume, timer, toast) | PanPenek | new `system` skill | ~100 lines | Daily-use commands v2 simply lacks |
| 9 | Memory decay scoring on semantic facts | isair | `jarvis/memory.py` | ~30 lines | Forgetting curve for free inside existing FTS ranking |
| 10 | Argv-not-source subprocess rule + audit | ethanplusai | `pc_control.py` + verifier | audit | Removes a real injection class (hostile window titles) |

*Not stolen, deliberately: isair's full 950-line graph-memory rewrite (v2's memory tiers are sound; only decay + tree export are worth it), OpenJarvis's LLM config-optimizer (no search space in v2 yet), PanPenek's router pattern (v2's manifest registry is strictly stronger).*
