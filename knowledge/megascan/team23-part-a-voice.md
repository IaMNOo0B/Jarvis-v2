# MEGA-SCAN Team 23 — Slice A: Voice-Control Grammars & Dictation Systems
### Assistive voice control for motor impairments — PhD-level deep read

**Scope:** 13 clone targets attempted. **Deep-read: 11** (cursorless, talonhub/community, Caster, dragonfly, Vocola2, nerd-dictation, vosk-api, Handy [successor], voice2json [successor], voice-desktop-assistant [discovered], serenade-commands [proxy evidence]). **Failed honestly:** `serenade-ai/serenade` (404/private — git demands auth; Serenade's client was never fully open [SEARCH]), `handy-computer/handy` (404 — real repo is `cjpais/Handy`, cloned), `rhasspy/voice2json` (404 — original author repo is `synesthesiam/voice2json`, cloned), `nico-lee/VoiceAttack` (VoiceAttack is closed-source commercial Windows software; no open repo exists [SEARCH] — closest open Windows equivalent found and deep-read instead: `mnxtr/voice-desktop-assistant`).

**Tag key:** [CODE] = read in cloned source · [README] = project's own claim · [SEARCH] = GitHub search metadata · [INFERENCE] = my analysis.

**License rule applied throughout:** MIT / Apache-2.0 = code may be lifted with attribution. LGPL/GPL = IDEAS ONLY for JARVIS v2 (stdlib-only, must stay license-clean) unless linking terms are deliberately accepted — flagged per repo.

---

## repos deep-read

### 1. cursorless-dev/cursorless — voice coding grammar (TOP priority)

**What it is.** A structural voice-coding system: every token on screen wears a coloured "hat" (coloured dot/shape over a character), so the user names a target unambiguously — *"take air"* = act on the token wearing the default hat over `a`. It runs as a VS Code / Neovim extension driven from Talon; the grammar lives in Talon `.talon` files + Python captures, the semantics in a TypeScript engine. [CODE]

**Grammar mechanism from code.**
- The entire spoken surface is ~15 composable Talon rules, not hundreds of flat commands. `cursorless-talon/src/cursorless.talon:1-40` [CODE]:
  ```
  <user.cursorless_action_or_ide_command> <user.cursorless_target>: ...
  {user.cursorless_bring_move_action} <user.cursorless_bring_move_targets>: ...
  {user.cursorless_call_action} <user.cursorless_target> on <user.cursorless_target>: ...
  ```
  Composition is **action × modifier × mark**: an action verb, zero+ scope modifiers, one mark. That product covers thousands of utterances from tens of vocabulary entries.
- Marks are a capture with structure: `cursorless-talon/src/marks/decorated_mark.py` — `@mod.capture(rule="[{user.cursorless_hat_color}] [{user.cursorless_hat_shape}] <user.cursorless_grapheme>")` produces `{"type":"decoratedSymbol","symbolColor":"blue-ex","character":"a"}` [CODE]. Colour/shape are optional slots with defaults, so "air", "blue air", "blue ex air" are one grammar rule at three specificities.
- Modifiers are their own capture family (`src/modifiers/`: `relative_scope.py`, `ordinal_scope.py`, `head_tail.py`, `interior.py`, `matching_pair_symbol.py`) — e.g. "second past air", "head air", "inside air" resolve to AST scope operations engine-side, never string surgery in the editor. [CODE]
- The Talon side serialises the parsed command to a versioned dict (`src/command.py:13-19`: `CursorlessCommand{version, spokenForm, usePrePhraseSnapshot, action}`) and RPCs it to the engine; `spokenForm` is captured from Talon's `pre:phrase` speech-system hook (`command.py:24-29`) so the engine can log *what was actually heard* alongside what it did. [CODE]
- For user-defined commands there is a real formal grammar: `packages/lib-engine/src/customCommandGrammar/grammar.ne` is a **Nearley (Earley-parser) grammar** lexed by `moo` (`CommandLexer.ts`), with productions like `action -> %simpleActionName target`, `primitiveTarget -> modifier:+ mark` [CODE]. This is a parser, not regex: ambiguous/custom spoken forms get a parse tree, then `parseAndFillOutAction.ts` fills placeholders into action descriptors.
- Spoken forms are **generated, not hand-listed**: `packages/lib-engine/src/generateSpokenForm/` + `spokenForms/` derive the canonical utterance for any command AST (used for the cheatsheet and for round-trip tests — if you can generate it, you can parse it). [CODE]

**Error recovery from code.**
- **Fallback execution:** when the IDE engine cannot perform an action (e.g. Cursorless-everywhere / non-VS Code surface), the engine returns a `fallback` payload and the Talon side executes a degraded equivalent: `cursorless-talon/src/fallback.py` maps action names → plain editor primitives (`remove → edit.delete`, `copyToClipboard → edit.copy`, `containingScope.token → edit.select_word`, …) and composes modifier callbacks in reverse order before the action (`perform_fallback`, fallback.py:57-67) [CODE]. Graceful degradation is a designed path, not an exception.
- **Pre-phrase snapshot:** `usePrePhraseSnapshot` (command.py) lets the engine act on the document state *as it was when speaking started*, so a command that itself mutates the buffer cannot invalidate its own target mid-flight. [CODE]
- **Command history as audit:** `packages/lib-engine/src/CommandHistory.ts` appends every command (sanitised, with error name + phraseId) to `.cursorless/commandHistory/*.jsonl` when opted in — misrecognitions are diagnosable after the fact from (spokenForm, AST, error) triples. [CODE]
- There is deliberately **no "did you mean" guessing**: a target either resolves via its hat or the command fails loudly. For motor-impaired users a wrong silent action costs more than a failed one. [INFERENCE from fallback/history design]

**Latency/path.** STT is entirely Talon's (Dragon / wav2letter / Conformer — engine-pluggable); Cursorless itself adds only local RPC + tree-sitter scope resolution, all on-device. [CODE/INFERENCE]

**License.** MIT [CODE: LICENSE, © Brandon Virgil Rule]. **Code may be lifted with attribution.**

**Steal verdict for JARVIS v2.**
- **Steal the compositional target grammar** → `jarvis/intent_router.py`: commands as `ACTION × MODIFIER × TARGET` triples parsed into a dict AST (exactly Cursorless's serialised shape), never flat if/elif string matching. JARVIS's PC targets ("that window", "second link", "top button") need Cursorless-style *referring expressions*, and hats generalise to JARVIS's UIA tree: every UIA element gets a short spoken alias. WHY: flat command lists collapse at ~100 commands; compositional grammar scales to thousands and each slot can be validated independently.
- **Steal the fallback contract** → `jarvis/pc_control.py`: every high-level action returns either success or a `fallback` descriptor executable with cruder primitives (UIA → keyboard → coordinates). WHY: JARVIS's known failure mode is one brittle path failing totally; Cursorless proves degraded-but-done beats failed.
- **Steal (spokenForm, AST, error) JSONL history** → `jarvis/voice_loop.py`. WHY: Owais's corrections become training pairs only if what-was-heard is logged next to what-was-done.

---

### 2. talonhub/community — Talon community command set (TOP priority)

**What it is.** The de-facto standard command vocabulary for Talon (~750 files), built and battle-tested largely by motor-impaired and RSI users who drive their whole computer by voice all day. If Cursorless is the grammar, this is the *lexicon + interaction patterns*. [CODE/README]

**Grammar mechanism from code.**
- Commands are Talon rules bound to **modes and contexts**: `core/modes/dictation_mode.talon`, `command_and_dictation_mode.talon`, app/tag-scoped `.talon` files. The same utterance parses differently per mode — the grammar is a *state machine*, not a global list. [CODE]
- Mode switching is itself spoken and total: `command_and_dictation_mode.talon` is three lines — `^dictation mode$`, `^command mode$`, `^mixed mode$` — implemented in `core/modes/modes.py` (`command_mode()` disables dictation+sleep, enables command, etc.) [CODE]. Anchors `^…$` force whole-utterance matches for mode commands so prose can never trigger them.
- Dictation is a **capture, not a mode leak**: in dictation mode `<user.raw_prose>` routes everything unmatched to `user.dictation_insert()` (`dictation_mode.talon`), which auto-capitalises/auto-spaces via `DictationFormat` state machine in `core/text/text_and_dictation.py` (`auto_capitalize()`, `DictationFormat.format/pass_through/cap/no_cap`, lines 380-470) [CODE]. Inline escapes exist inside dictation: `cap`, `no cap`, `no space`, `^cap that$`, `formatted <user.format_text>`, and `^escape <user.text>$` to type a word that would otherwise be a command.
- **Prose post-processing is grammatical**: captures in `text_and_dictation.py` (`prose`, `prose_time`, `prose_currency`, `prose_percent`, `prose_spell`, lines 64-275) rewrite spoken forms ("five dollars" → `$5`, "three thirty pm" → `3:30pm`) deterministically at parse time. [CODE]
- Spoken forms are *generated from data*: `core/create_spoken_forms.py` builds pronounceable forms from identifiers (snake_case file names → spoken words), the same trick Cursorless uses. Vocabulary lists (`.talon-list`, CSV) are hot-reloaded via `fs.watch` (see homophones below). [CODE]

**Error recovery from code.** This repo is the richest correction-flow source in the scan:
- **Phrase history buffer** (`core/text/phrase_history.py`): last 40 dictated phrases kept; `clear_last_phrase()` deletes by *backspacing exactly len(phrase) characters*, `select_last_phrase()` re-selects by extending left len(phrase) times [CODE]. Correction is length-exact because the system remembers what it inserted — it never re-recognises to undo.
- Dictation-mode correction vocabulary (`dictation_mode.talon`, "Corrections" section) [CODE]:
  ```
  nope that | scratch that: user.clear_last_phrase()
  (nope | scratch) selection: edit.delete()
  select that: user.select_last_phrase()
  spell that <user.letters>: user.dictation_insert(letters)
  ^cap that$ / ^(no space) that$: reformat last phrase in place
  ```
  i.e. undo, delete-selection, select-last, respell, and reformat are five *distinct* cheap operations on the last phrase.
- **Homophone disambiguation UI** (`core/homophones/homophones.py` + `homophones.csv`): saying the homophone command with a word selected opens an imgui picker of the canonical set (`where/wear/ware`…); `quick_replace = True` auto-replaces without UI when only one alternative exists [CODE]. The CSV is watched and merged live (`update_homophones` unions all sets sharing a word).
- **Sleep discipline:** `core/modes/sleep_mode*.talon`, `deep_sleep.py`, `sleep_mode_pop_twice_to_wake.py` — in sleep mode almost nothing parses, and wake requires a deliberate sound/double-pop, so coughs/conversation/TV never fire commands. [CODE]

**Hands-free workflows.** Mouse grid (`core/mouse_grid/mouse_grid.py`): recursive 9-cell narrowing grid with zoomed view at small sizes, expansion setting for edge targets, and history stack — the standard hands-free pointing fallback when gaze/UIA fails [CODE]. Plus `noise.py` (pop/hiss as click/scroll inputs) — non-speech sounds as first-class commands for users who cannot sustain speech. [CODE]

**Latency/path.** Talon engines: Dragon (local), wav2letter/Conformer (local). Community assumes local STT; cloud latency would break the correction loops above. [CODE/INFERENCE]

**License.** MIT [CODE: LICENSE]. **Code may be lifted with attribution.**

**Steal verdict for JARVIS v2.**
- **Steal phrase-history correction wholesale** → `jarvis/voice_loop.py`: keep last-N inserted phrases with exact lengths; implement `scratch that` (delete last), `select that`, `cap that`, `spell that` as operations on that buffer. WHY: this is *the* proven dictation-correction UX for motor-impaired users, and JARVIS v2's current dictation has no equivalent — a misheard sentence currently costs a full manual fix Owais cannot easily do by hand-waving at a keyboard.
- **Steal mode-state grammar + anchored mode commands + sleep-requires-deliberate-wake** → `jarvis/intent_router.py` + `jarvis/voice_loop.py`. WHY: JARVIS's echo problem (hearing himself) and false-trigger risk are exactly what sleep discipline + `^…$` anchoring solve.
- **Steal homophone picker with quick-replace** → `jarvis/voice_loop.py` (Hindi/English homophones + Hinglish pairs). WHY: cheapest possible fix for the most common dictation error class.
- **Steal the mouse grid** → `jarvis/pc_control.py` as the last-resort pointer when UIA finds no target. WHY: guarantees *no screen point is unreachable by voice*, the completeness property assistive users actually need.

---

### 3. dictation-toolbox/dragonfly — the grammar engine

**What it is.** The foundational Python speech-grammar framework (2007–present): a parser-combinator grammar DSL that compiles to whatever recogniser is underneath — Dragon/Natlink, Windows SAPI5, Kaldi, CMU Sphinx, or plain text. Caster and Vocola ecosystems sit on it. [CODE]

**Grammar mechanism from code.**
- Grammar = composable element tree (`dragonfly/grammar/elements_basic.py`): `ElementBase`, `Sequence`, `Optional`, `Alternative`, `Repetition`, `Literal`, `RuleRef`, `ListRef`, `Dictation`, `Modifier`, `Impossible` [CODE]. Elements parse via generators over a `State` of remaining words (`dragonfly/parser.py`, `grammar/state.py` — `Node`, backtracking decode), i.e. a real PEG-style parser in pure Python.
- The user-facing form is `MappingRule` (`grammar/rule_mapping.py:87`): a dict of **spec strings → actions**, where each spec string is itself a mini-language compiled by `Compound` (`grammar/elements_compound.py:63`) — `"press <key> [<n> times]"` with `extras=[Choice(...), IntegerRef(...)]` and `defaults` [CODE]. Spec-string compilation is the key ergonomic invention: grammars read like the utterances they accept.
- `Dictation` element (`elements_basic.py:1108`) is the free-form island inside a strict grammar — the formal version of Talon's mixed mode. [CODE]
- **Context gating** (`grammar/context.py`): `AppContext` (executable/title/class matchers), `LogicAnd/Or/NotContext`, `FuncContext` — grammars activate only when context matches, evaluated per recognition. [CODE]
- Engines are interchangeable behind `engines/base/`; the **Kaldi backend** (`engines/backend_kaldi/`) compiles the active grammar to a Kaldi FST so decoding is *constrained by the grammar* — the recogniser literally cannot output words outside active commands, which is why Kaldi+Caster feels more accurate than open dictation on the same model. [CODE]

**Error recovery from code.**
- First-class failure channel: `RecognitionObserver.on_failure()` (`grammar/recobs.py:90`), `CallbackRecognitionObserver` + `register_failure_callback()` (`recobs_callbacks.py:88-139`), engine-side `dispatch_recognition_failure()` → per-grammar `process_recognition_failure(results)` (`engines/base/engine.py:319`, `grammar_wrapper.py:129`) [CODE]. Failure is an event grammars can react to (prompt, retry, widen), not silence.
- `RecognitionHistory`/`PlaybackHistory` (`recobs.py:112-161`) record recognised word sequences and can **replay** them — regression-testing voice commands without a microphone, and the seed of "repeat that" features. [CODE]
- `State.decode_failure()` (`grammar/state.py:161`) tracks *where* parsing died, enabling near-miss diagnostics. [CODE]

**Latency/path.** All engines local (Dragon local, SAPI5 local, Kaldi local, Sphinx local). Grammar compilation happens at load; recognition is a single constrained decode. [CODE]

**License.** LGPL-3.0 [CODE: LICENSE.txt]. **IDEAS ONLY for JARVIS v2** (importing dragonfly would impose LGPL obligations and a heavy dependency; reimplement the patterns in stdlib instead).

**Steal verdict for JARVIS v2.**
- **Steal spec-string → parser compilation** → `jarvis/intent_router.py`: define commands as spec strings (`"open <app>"`, `"scroll (up|down) [<n> times]"`) compiled once into matcher objects with typed extras. WHY: it's the most maintainable grammar authoring form ever shipped in Python, it is pure-stdlib implementable (a small recursive-descent parser, ~200 lines), and it gives JARVIS Cursorless-style composition without Talon.
- **Steal the failure-observer channel** → `jarvis/stt.py` + `jarvis/voice_loop.py`: no-match is an explicit event carrying n-best/confidence, routed to a recovery policy (ask / offer alternatives / widen to dictation), never a silent drop. WHY: JARVIS v2's autopsy found silent failures everywhere; dragonfly shows the 17-year-old correct shape.
- **Steal context-gated grammar activation** → `jarvis/intent_router.py` (active app / mode / conversation state gates which spec set is live). WHY: smaller live grammar = fewer confusions = higher accuracy on a small local model — the same physics as Kaldi FST constraining.

---

### 4. dictation-toolbox/Caster — merged continuous-command rules on dragonfly

**What it is.** A full voice-control *environment* on dragonfly: hundreds of commands for coding, apps, and the OS, organised as **CCR (Continuous Command Recognition) rules** that can chain in one utterance ("copy that, go down three, paste") — the Dragon-era power-user system, now also running on the open Kaldi engine. [CODE]

**Grammar mechanism from code.**
- Core invention: `MergeRule` (`castervoice/lib/merge/mergerule.py:10`) — a `MappingRule` subclass whose mappings can be **merged** (`merge()` unions mapping/extras/defaults into a new rule) so dozens of small per-app/per-language rule classes compose into the few big grammars the engine actually loads [CODE]. `prepare_for_merger()` sorts specs into an `OrderedDict` — commented in code as *"an optimization for Kaldi engine"* — and injects a self-describing `"list available commands"` command post-merge [CODE].
- Rule families per language (`castervoice/rules/ccr/{python,java,cpp,…}_rules/`) and per app (`rules/apps/`), plus a grammar manager with validators (`lib/ctrl/mgr/grammar_manager.py`, `validation/rules/mergerule_validator.py`) that rejects broken rule combos at load instead of misfiring at runtime. [CODE]
- Every rule is `Pronounceable` with an optional spoken `pronunciation` override for its enable/disable command (`mergerule.py:14-18`) — meta-commands ("enable python rules") are generated from the same registry. [CODE]

**Error recovery from code.** Inherits dragonfly's failure observers; adds an **available-commands tracker** (`lib/available_commands_tracker.py`) that always knows the live spec list (for help *and* for constraining what "did you mean" could offer), and rule enable/disable by voice so a misfiring rule family can be switched off mid-session by speech alone. [CODE]

**Latency/path.** Dragon/WSR/Kaldi, all local; the Kaldi path is grammar-constrained (see dragonfly). [CODE]

**License.** LGPL-3.0 for original code [CODE: LICENSE — GNU LGPL v3]. **IDEAS ONLY.**

**Steal verdict for JARVIS v2.**
- **Steal MergeRule composition + generated meta-commands** → `jarvis/intent_router.py`: small per-domain rule modules merged into one live grammar; auto-generate "JARVIS, what can I say here?" and "turn off browser commands" from the registry. WHY: JARVIS will accumulate skills forever; merge-composition is how a grammar survives that growth without collisions, and self-listing help is an accessibility feature, not a luxury.
- **Steal load-time grammar validation** → `jarvis/intent_router.py`. WHY: a broken skill rule must fail at startup with a named error, never as a silent dead command at 2am.

---

### 5. dictation-toolbox/Vocola2 — voice command *language*

**What it is.** A tiny compiled language for voice commands: `.vcl` files that read almost like the utterances themselves, compiled by `vcl2py` into dragonfly/Natlink Python. The oldest design in the scan (roots 2002, Rick Mohr) and still the cleanest study in *notation*. [CODE]

**Grammar mechanism from code.**
- Surface syntax (samples in `src/vocola2/samples/_vocola.vcl`) [CODE]:
  ```
  Switch Window = SendSystemKeys({Alt+Tab});
  (Switch|Next) View <n> = {Ctrl+Tab_$2};
  <upDown> := (Up='-' | Down='');
  Drag <n> <upDown> = dragBy(0, $2$1);
  [search] Google for <_anything> = AppBringUp("IEXPLORE") {Alt+g}$1{Enter};
  ```
  Alternation `(a|b)`, optional `[word]`, typed variables `<n>`, `<_anything>` (dictation island), reusable definitions `:=` with per-alternative *values* (`Up='-'`), and `$1/$2` back-references into the action — a complete little DSL in ~6 constructs.
- The compiler is a hand-written recursive-descent parser (`src/vocola2/exec/vcl2py/parse.py`: `parse_statements/parse_context/parse_top_command/parse_terms/parse_menu_body/parse_call`, with the grammar documented in comments per function) → AST (`ast.py`) → emitted Python (`emit.py`) [CODE]. Context headers (`AppName | Title:`) scope whole files.
- Actions are keystroke-centric (`{Ctrl+Tab_$2}` = repeat interpolated) — Vocola assumes the keyboard is the universal actuator. [CODE]

**Error recovery from code.** Minimal by design: no runtime recovery — correctness is pushed to *compile time* (undefined variables, bad references are parse errors with positions, `vcl2py/log.py`) and to notation so small users can see their whole grammar. Honest finding: if a command misfires, Vocola's answer is "edit the one-line rule," which works because rules are one line. [CODE/INFERENCE]

**Latency/path.** Compiles to Natlink/Dragon — local, zero runtime parsing cost (the parse happened at compile time). [CODE]

**License.** MIT [CODE: LICENSE.txt]. **Code/notation may be lifted with attribution.**

**Steal verdict for JARVIS v2.**
- **Steal the notation as JARVIS's user-editable command file format** → `jarvis/intent_router.py` (a `commands.vcl`-style file JARVIS loads at startup). WHY: Owais must be able to add/fix a voice command *without code* — Vocola proves a non-programmer-readable one-line-per-command format with alternation/optionals/variables is sufficient for ~90% of personal commands, and compiling it at load keeps runtime at zero cost. This is the single best answer in the scan to "how does the user teach JARVIS new commands."
- **Steal per-alternative values** (`Up='-'`): spoken alternatives carrying semantic values, so grammar and action mapping never drift apart. → same file.

---

### 6. serenade-ai/serenade — voice coding (REPO UNAVAILABLE — honest report)

**What happened.** `serenade-ai/serenade` does not clone: git demands credentials (repo private or deleted). [CODE — clone output] Serenade was a commercial voice-coding product whose client was distributed as a binary with an API for custom commands; the core engine was never open source. I did **not** invent a deep read. Proxy evidence cloned instead: `awulkan/serenade-commands` (a user's personal command set).

**What the proxy evidence shows.** Custom commands are JavaScript files organised by `apps/`, `languages/`, `system/`, `input/`, `constants/` [CODE: serenade-commands tree] — i.e. Serenade's extensibility model was *code snippets registered against spoken triggers*, per-app and per-language, mirroring the Caster/Talon layout. Its documented command style [README/SEARCH] emphasised natural structural utterances ("add function", "go to next error") resolved against the editor's AST via a (cloud-assisted, later local) service — the direct commercial contemporary of Cursorless, which won the open ecosystem.

**License.** Proprietary / unavailable. **IDEAS ONLY — and only the general ones** (structural commands, per-language snippets), all of which Cursorless covers openly and better.

**Steal verdict.** Steal nothing directly. The lesson is strategic → note for `jarvis/intent_router.py`: the closed entrant in this space died/darkened while the open compositional grammar (Cursorless + community) compounded. JARVIS bets on the open pattern.

---

### 7. ideasman42/nerd-dictation — offline dictation on Vosk

**What it is.** A single-file (1,983-line) Python dictation tool: microphone → Vosk → post-processing → simulated typing (xdotool/ydotool/wtype/dotool/stdout), Linux-focused, designed to be hacked. The minimal complete dictation loop, all in one readable file. [CODE: `nerd-dictation/nerd-dictation`]

**Grammar mechanism from code.** Deliberately *no* command grammar — pure dictation — but two mechanisms matter:
- **Vosk grammar constraint hook:** `text_from_vosk_pipe(..., vosk_grammar_file=...)` loads a JSON phrase list and constructs `vosk.KaldiRecognizer(model, sample_rate, grammar_json)` instead of the open recogniser (lines 969-983) [CODE] — vocabulary restriction as a one-argument change.
- **Deterministic text post-processing in-process:** `process_text()` (line 826) strips newlines (safety: a newline would "press enter" in the target app), then a hand-built number parser `from_words_to_digits` (lines 359-805) converts "one hundred and twenty three" → `123` with follow-on-word rules (`_allow_follow_on_word`) — the same job as community's prose captures, done as a pure function with tests (`tests/`). [CODE]
- **User config as code:** `process_text_with_user_config()` (line 806) execs a user Python config that can rewrite text arbitrarily — dictation customisation via a `text_replacement` hook, zero plugin framework. [CODE]

**Error recovery / hands-free reliability from code.**
- **Partial-result handling:** the main loop distinguishes `AcceptWaveform()==True` (final → `Result()`) from partials (`PartialResult()`), tracks `json_text_partial_prev` to compute the *stable delta*, and only types the delta (lines 1063-1108, main loop ~1240-1260) [CODE] — the standard trick to avoid re-typing flickering hypotheses.
- **Timeout-as-finish:** if partial text is unchanged for `timeout` seconds, dictation ends cleanly (main loop, `timeout_text_prev/timeout_time_prev`) [CODE].
- **Suspend/resume by signal:** SIGUSR1/SIGTSTP suspend (flush final result, `rec.Reset()`, kill recorder, SIGSTOP self), SIGCONT resumes, SIGHUP reloads config (lines 1109-1195) [CODE] — hands-free pause without touching the keyboard, driven from any external switch/voice layer.
- Typing backends *delete-then-type* (`simulate_typing_* (delete_prev_chars, text)`) so a corrected hypothesis replaces its own partial in the target app. [CODE]

**Latency/path.** Fully local Vosk small models; audio via parec/sox/pw-cat subprocess at 16kHz mono, non-blocking reads, idle-sleep throttling to cap CPU. [CODE]

**License.** GPL-3.0 [CODE: LICENSE]. **IDEAS ONLY — never code** (GPL would contaminate JARVIS v2's licensing).

**Steal verdict for JARVIS v2.**
- **Steal the partial-delta + timeout-finish loop** → `jarvis/stt.py`: stream partials, emit only stabilised deltas upward, treat N seconds of unchanged partial as end-of-utterance. WHY: this is the reliability core of continuous dictation and it is ~40 lines of logic JARVIS's voice loop currently re-derives badly.
- **Steal delete-prev-chars replacement typing** → `jarvis/pc_control.py` dictation insert path: when a final result corrects a typed partial, backspace exactly the partial's length (converges with community's phrase-history lengths — same invariant, two layers).
- **Steal newline-stripping as a safety invariant** → `jarvis/stt.py` post-processing. WHY: dictated text must never inject Enter into an arbitrary focused app unsummoned.

---

### 8. alphacep/vosk-api — small-model offline STT engine

**What it is.** The Kaldi-based offline recogniser (C++ core, bindings for Python/Java/Node/Go/Rust/…) behind nerd-dictation, Caster's Kaldi path cousins, and half the offline-voice ecosystem. Small models (~40-50MB) run real-time on a CPU core. [CODE]

**Grammar mechanism from code.**
- **Runtime grammar restriction:** `KaldiRecognizer(model, rate, grammar_json)` / `SetGrammar(grammar)` (`python/vosk/__init__.py:150-195`; C++ `src/recognizer.cc:51-59,277-330` `UpdateGrammarFst`) compiles a JSON phrase list into an FST that *replaces* the language-model graph for that recogniser [CODE]. Decoding is then constrained to the phrase set (+ `[unk]` handling) — accuracy on command vocabularies jumps because the search space collapses. Grammar can be swapped between sessions, not mid-stream (`"Can't add grammar to already running recognizer"` guard, recognizer.cc:280).
- **Lattice + alternatives:** decoding keeps a word lattice (`lattice-beam=6.0`, `src/model.cc:147`; `src/postprocessor.cc` runs `fst::ShortestPath` over the lattice); `SetMaxAlternatives(n)` (recognizer.cc:205) returns N-best interpretations with confidences — the raw material for "did you mean" UIs. [CODE]
- **Word-level detail on demand:** `SetWords(True)` / `SetPartialWords(True)` yield per-word timestamps + confidence in both final and *partial* results [CODE] — partial words are what make delta-typing (nerd-dictation) and live captions possible.
- **Endpointer control:** `SetEndpointerMode(DEFAULT/SHORT/LONG/VERY_LONG)` + `SetEndpointerDelays(t_start_max, t_end, t_max)` (`__init__.py:181-186`) — silence thresholds are API parameters, tunable per use (short for commands, long for dictation). [CODE]

**Error recovery from code.** Vosk itself offers the *substrate*: N-best alternatives + word confidences + `[unk]` fallback in grammar mode. Recovery policy is deliberately left to the app — which is why every consumer above (Caster, nerd-dictation) builds its own. [CODE/INFERENCE]

**Latency/path.** 100% local, streaming (`AcceptWaveform` returns True at utterance boundaries), small-model path is the product's whole point. On JARVIS's target hardware (Ryzen 5 3600) a small model is real-time with headroom. [CODE/INFERENCE]

**License.** Apache-2.0 [CODE: COPYING]. **Code/models may be used with attribution** (models carry their own licenses — check per-model).

**Steal verdict for JARVIS v2.**
- **Steal grammar-constrained decoding for command mode** → `jarvis/stt.py`: when JARVIS is in command mode, construct the recogniser with the *live intent grammar's phrase list* (from intent_router's merged specs); in dictation mode, use the open recogniser. WHY: this single switch is the largest free accuracy win available to a small-model local stack — it is how Caster/Kaldi punches at Dragon's weight.
- **Steal dual endpointer profiles** → `jarvis/stt.py` (SHORT for commands, LONG for dictation) and **N-best + word-confidence passthrough** → `jarvis/voice_loop.py` so the recovery policy (Top 5 #2) has data to work with. Note: if JARVIS v2's STT is faster-whisper rather than Vosk, the *pattern* still applies — constrain via initial-prompt/hotwords + keep n-best/logprobs; the mechanism, not the library, is the steal. [INFERENCE]

---

### 9. handy-computer/handy → cjpais/Handy — push-to-talk dictation app (successor cloned)

**What it is.** The original `handy-computer/handy` path 404s; the living project is `cjpais/Handy` [SEARCH: fork references "Fork of Handy (MIT)"; README links handy.computer + winget `cjpais.Handy`]. A Tauri/Rust desktop app: hold/toggle a global shortcut, speak, release — text is pasted into the focused app. Completely offline. Accessibility is its stated founding motive ("Accessibility tooling belongs in everyone's hands, not behind a paywall" [README]). [CODE/README]

**Mechanism from code.**
- **Pipeline:** shortcut (hold/toggle/hold-only/toggle-only modes) → recording with **Silero VAD** → Whisper (Small→Large, GPU) or **Parakeet V3** (CPU) → optional LLM post-processing → paste (`src-tauri/src/actions.rs`: `TranscribeAction::start/stop`, `preload_vad()`, `try_start_recording(vad_policy)`, `transcribe_recording()`, paste guarded by a cancel-generation counter, actions.rs:389-760) [CODE].
- **Smoothed VAD:** `audio_toolkit/vad/smoothed.rs` wraps raw VAD with onset frames + **hangover frames** (`hangover_counter` reset on speech, decremented on silence, lines 16-160) so mid-word pauses don't chop utterances — the debounce every voice loop needs and most get wrong. [CODE]
- **Fuzzy custom-vocabulary correction:** `audio_toolkit/text.rs` post-corrects transcription against a user word list using **Levenshtein + Soundex phonetic matching** over normalised n-gram keys (`build_ngram`, `find_best_match`, lines 1-80+) [CODE] — proper nouns the model mishears get snapped to the user's spellings deterministically, *after* STT, without retraining.
- **Cancellation as a first-class path:** a dynamically registered cancel shortcut + generation counter checked immediately before paste (`was_cancelled_since(cancel_generation)`, actions.rs:714-743) — a transcription the user regrets mid-flight never lands. [CODE]
- **History:** every transcription (+ post-processed variant + prompt used) persisted to SQLite `history.db` (`managers/history.rs`) — the audit/correction corpus pattern again. [CODE]

**Error recovery from code.** Cancel-before-paste, VAD smoothing, fuzzy vocab snap, and full history. No grammar/correction-by-voice (it's dictation-only) — recovery is *prevent the bad insert*, not *repair it after*. [CODE]

**Latency/path.** 100% local; model choice is the latency dial (Parakeet V3 for CPU-only machines). [README/CODE]

**License.** MIT [CODE: LICENSE]. **Code may be lifted with attribution** (Rust — for JARVIS, lift the *algorithms*, reimplement in Python).

**Steal verdict for JARVIS v2.**
- **Steal Soundex+Levenshtein vocabulary snap** → `jarvis/stt.py` post-processing, fed by JARVIS's contacts/app-names/user word list. WHY: Hinglish names and Indian proper nouns are exactly what small STT models mangle; a deterministic phonetic snap fixes a whole error class with zero model cost — and it's ~80 lines of stdlib Python (`difflib` covers Levenshtein-ratio; Soundex is 20 lines).
- **Steal hangover-smoothed VAD parameters** → `jarvis/voice_loop.py` endpointing. WHY: JARVIS cuts users off mid-pause; hangover frames are the proven fix.
- **Steal cancel-generation-before-actuation** → `jarvis/voice_loop.py` + `jarvis/pc_control.py`: any in-flight action carries a generation id; a "stop/cancel" bumps it; executors check immediately before the irreversible step. WHY: for a user who cannot grab a mouse quickly, a reliable spoken STOP that actually pre-empts is a safety feature.

---

### 10. rhasspy/voice2json → synesthesiam/voice2json — offline intent recognition (successor cloned)

**What it is.** The original author's repo (`synesthesiam` = Michael Hansen, Rhasspy creator) [SEARCH]. A Unix-pipe toolkit: `transcribe-wav | recognize-intent | …` — offline speech + **intent recognition from a template grammar**, 18 languages, built for home automation (Rhasspy) where commands are finite and reliability beats generality. [CODE/README]

**Grammar mechanism from code.**
- **Sentence templates** (README/docs `sentences.md`) [CODE/README]:
  ```
  [LightState]
  states = (on | off)
  turn (<states>){state} [the] light
  ```
  Templates compile (`voice2json/train.py`) into an **intent graph** (networkx, pickled to `intent.pickle.gz`); recognition (`voice2json/recognize.py:84-131`) walks the graph with `rhasspynlu` to produce `{intent: {name}, slots: {state: "on"}, entities}` [CODE]. Slots are *typed extractions* — the template's `{state}` tag names the capture, exactly dragonfly's extras in declarative dress.
- **Fuzzy matching is the default:** `fuzzy = pydash.get(profile, "intent-recognition.fuzzy", True)` (recognize.py:41) — the graph walk tolerates word substitutions/insertions, so a misheard function word doesn't kill the match; stop-words are stripped from a configurable list pre-match. [CODE]
- **Converters:** slot values pass through per-slot converter programs (`CommandLineConverter`, recognize.py:166-192) — "twenty three" → `23` happens *in the grammar layer*, typed, before the app sees it. [CODE]
- **Pronunciation tooling:** `pronounce.py`/`sounds_like.py` guess pronunciations for out-of-vocabulary words so custom names enter the acoustic model — the command-vocabulary version of Handy's fuzzy snap, done at train time. [CODE]

**Error recovery from code.** Fuzzy graph matching + stop-word stripping + intent whitelist filter (`intent_filter`, recognize.py:74-82) so out-of-scope intents can't fire. On total failure it emits an **empty Recognition object** (`rhasspynlu.intent.Recognition.empty()`, recognize.py:126) — an explicit no-match the pipeline can route on, not an exception. [CODE]

**Latency/path.** Offline Kaldi/Julius profiles, CLI-pipe latency dominated by STT; intent walk is milliseconds. Linux-only (JARVIS takes the pattern, not the binary). [CODE]

**License.** MIT [CODE: LICENSE]. **Code may be lifted with attribution.**

**Steal verdict for JARVIS v2.**
- **Steal template→graph fuzzy intent matching as the fallback tier** → `jarvis/intent_router.py`: Tier 1 = exact spec match (dragonfly-style); Tier 2 = fuzzy template walk tolerating ±1 word error with slot extraction; Tier 3 = LLM. WHY: JARVIS's router currently cliffs from "exact" to "LLM guesses"; voice2json proves a fuzzy middle tier catches most mishearings deterministically, offline, in milliseconds — critical when the cloud brain is down or the command is "stop".
- **Steal typed slot converters in the grammar layer** → same file (numbers, dates, durations converted once, centrally). WHY: every skill currently re-parses "twenty three"; convert once at routing.

---

### 11. mnxtr/voice-desktop-assistant — Windows voice control for motor impairments (discovered via search)

**What it is.** Found via GitHub search for "voice control motor impairment" [SEARCH]. A Windows Python assistant explicitly "for users with motor/mobility impairments": Vosk wake-word listener + LLM (Ollama local / Gemini cloud / hybrid with fallback) translating natural language into a fixed JSON action vocabulary, plus webcam eye-gaze with dwell-click and a numbered screen grid. Small (63 files) but architecturally the closest thing in the scan to JARVIS v2 itself. [CODE]

**Grammar mechanism from code.**
- **Anti-grammar, deliberately:** no spec grammar — the LLM *is* the parser. `llm/processor.py` is a system prompt enumerating 26 JSON actions (`open_app`, `mouse_click`, `grid_click{cell}`, `type_text`, `hotkey`, `dictate`, `confirm`, `cancel`, `clarify{message}`, …, processor.py:9-41) and the model's raw output is parsed as JSON and dispatched in `main.py` (action dispatch, lines 241-315) [CODE]. Ambiguity is a returnable value: `{"action":"clarify", ...}`.
- **Wake-word gating in the STT loop:** `voice/listener.py:59-95` — Vosk `PartialResult()` is scanned for the wake word *before* the utterance completes (partial wake detection starts listening early); final results containing the wake word are split on it, the remainder is the command [CODE]. Two paths (wake-then-command, wake-with-command) in `_handle_text`.
- **Grid + gaze as equal citizens:** `show_grid/grid_click{cell}` are LLM actions like any other (`main.py:302-315`, `get_grid_cell_center`), and gaze dwell-click (`gaze/dwell.py`, `DwellClicker`, 1.5s dwell [README]) runs parallel to voice. [CODE/README]

**Error recovery from code.** `confirm`/`cancel` actions exist in the vocabulary and the hybrid processor falls back cloud→local on failure [README/CODE]; beyond that, recovery is the LLM's `clarify`. There is **no** deterministic correction flow, no phrase history, no n-best use (`Result()` text only, confidences discarded — listener.py:64-77) [CODE]. This is the scan's clearest negative example: LLM-parsing without the grammar tier inherits every failure the older systems engineered away.

**Latency/path.** Vosk small model local for wake/command capture; intelligence local (Ollama) or cloud (Gemini) per config, hybrid fallback. [CODE]

**License.** MIT [CODE: LICENSE]. **Code may be lifted with attribution.**

**Steal verdict for JARVIS v2.**
- **Steal partial-result wake-word scanning** → `jarvis/stt.py`/`jarvis/voice_loop.py`: begin command capture the moment the wake word appears in a *partial*, don't wait for endpoint. WHY: shaves perceived latency on every single interaction.
- **Steal `clarify`/`confirm`/`cancel` as router-level return values** → `jarvis/intent_router.py`: the LLM tier returns the same action-dict shape as the grammar tier, including explicit clarify/confirm — one dispatch table for all tiers (converges with Cursorless's single serialised command dict). WHY: JARVIS's tiers currently have different shapes; unifying them is what makes the Top-5 layered router possible.
- **Do NOT steal:** LLM-as-only-parser. WHY: this repo demonstrates the failure mode — no deterministic path for "stop", no offline command guarantee.

---

# Top 5 mechanisms

1. **Compositional grammar: ACTION × MODIFIER × TARGET parsed to a serialised AST dict.** (Cursorless `cursorless.talon` + `command.py`; dragonfly `Compound`/`MappingRule`.) One parser, tens of vocabulary entries, thousands of utterances; every slot validated independently; the same dict shape flows to execution, logging, fallback, and tests. This is the load-bearing design decision of every durable system in the scan.

2. **Grammar-constrained decoding + layered matching.** (Vosk `SetGrammar`/FST; Caster/Kaldi; voice2json fuzzy graph.) In command mode the recogniser is constrained to the live grammar's phrases; matching then degrades in tiers — exact spec → fuzzy template (±1 word, typed slots) → LLM — with an explicit no-match event at each tier (dragonfly `on_failure`), never silence and never a silent LLM guess for safety commands.

3. **Phrase-history correction algebra.** (talonhub/community `phrase_history.py` + dictation-mode corrections; nerd-dictation delete-prev-chars.) Remember every inserted phrase *and its exact length*; `scratch that` / `select that` / `cap that` / `spell that` / homophone-picker operate on that memory deterministically. Correction by voice must be cheaper than the error was — this is the mechanism that makes dictation viable for users who cannot fall back to a keyboard.

4. **Mode-state grammar with anchored transitions and a real sleep state.** (community `modes.py` + `^…$` anchors + pop-twice-to-wake; Cursorless pre-phrase snapshot.) Command/dictation/mixed/sleep as explicit states; mode commands whole-utterance anchored; sleep parses almost nothing and needs a deliberate wake. Kills cross-mode misfires and the assistant-hears-itself class of bugs structurally.

5. **Graceful-degradation execution contract.** (Cursorless `fallback.py`; Handy cancel-generation; dragonfly failure observers.) Every action returns success, a fallback descriptor executable by cruder means, or a routed failure — and any in-flight action can be pre-empted by a generation bump from a spoken STOP checked immediately before the irreversible step. For motor-impaired users, "degraded but done + always stoppable" is the safety property everything else rests on.

---

# Top 3 steals

1. **The spec-string grammar compiler + merged rule registry → `jarvis/intent_router.py`.** Dragonfly's spec strings (`"scroll (up|down) [<n> times]"`), Caster's `MergeRule` composition with load-time validation and generated help/meta-commands, Vocola's per-alternative values, and voice2json's fuzzy tier + typed slot converters — implemented as one stdlib-only module. Commands become data (including a user-editable Vocola-style command file), skills register rules instead of hard-coding matches, and "what can I say?" answers itself. *Why first: every other steal plugs into the router; JARVIS's flat matching is the root constraint on its voice reliability.*

2. **Phrase-history dictation + correction vocabulary + partial-delta streaming → `jarvis/voice_loop.py` + `jarvis/stt.py`.** Community's 40-phrase history with length-exact scratch/select/reformat, homophone picker with quick-replace, Handy's hangover-smoothed VAD and Soundex/Levenshtein vocabulary snap, nerd-dictation's stable-delta partial handling with timeout-finish and newline-safety. *Why second: dictation is the highest-volume voice activity for a motor-impaired user, and JARVIS currently has volume without any correction algebra — every mishearing is a dead end today.*

3. **Constrained command-mode STT + fallback/cancel execution contract → `jarvis/stt.py` + `jarvis/pc_control.py`.** Vosk-pattern grammar-constrained decoding in command mode (phrase list generated from the live merged grammar; dual endpointer profiles; n-best + word confidences surfaced), Cursorless-style fallback descriptors (UIA → keyboard → grid coordinates, with the community mouse grid as the guaranteed-reachable last resort), and Handy's cancel-generation checked before every irreversible actuation. *Why third: this converts JARVIS's two worst autopsy findings — silent recognition failure and one-brittle-path execution — into engineered properties: commands the model can actually hear, and actions that degrade instead of dying.*

---

*Method note: 10 repos cloned and read in source (9,065-file Cursorless monorepo sampled at grammar/engine/talon layers; all others read at their grammar/core files cited above). Serenade reported from clone-failure + proxy repo only, as marked. All file:line references are to the shallow clones under `~/workspace/jarvis-knowledge/megascan/.work23/a/` as of 2026-10-20.*
