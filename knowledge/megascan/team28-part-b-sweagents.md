# Team 28 — Part B: SWE-Agents (External Repo Reverse-Engineering)

**Mission:** Clone and reverse-engineer the 10 canonical software-engineering-agent repos, and extract what JARVIS v2's `skills/code/` (code_read / code_write / code_edit / code_run — jailed, tiered, stdlib-only, Windows) should steal.

**Method:** `git clone --depth 1` into `~/workspace/jarvis-knowledge/megascan/.work28/sliceB/`, code read locally. All `file:line` refs below are into those clones at the HEADs listed. Nothing in this file comes from READMEs alone — every claim is tied to code that was opened.

**Steal-target context (one line, audit already done elsewhere):** JARVIS code skill today = exact-once string edit + single `.bak` undo + 10 s subprocess run, socket-neutered, no shell, 10 KB cap, tier-3 approval. Everything below is judged against *that*: Python 3.11+ **stdlib only**, Windows owner PC, tiers 1/2/3, DCL, gate, `.bak` undo. Docker-based designs therefore score as *pattern-steals*, never code-steals — the owner has no Docker in the loop.

**License summary (all 10 verified from the LICENSE file in each clone): 9 are MIT — and one is a trap.** auto-code-rover is under the **SONAR Source-Available License v1.0**, which grants rights only for a "Non-competitive Purpose" (`LICENSE:52,81-83`) — it is *not* open source; for that repo the verdict is ideas-only, never code. For the 9 MIT repos code may legally be borrowed, but most of it is unusable for JARVIS anyway (Docker, LiteLLM, pydantic, tree-sitter deps), so the verdicts below are almost all *pattern* steals re-implemented in stdlib.

| Repo | HEAD (clone) | License | One-line identity |
|---|---|---|---|
| SWE-agent | `3ea751c` 2026-07-16 | MIT | Full agent-computer interface (ACI): bash + tool bundles in a SWE-ReX/Docker env, reviewer retry loops |
| mini-swe-agent | `04d809c` 2026-09-03 | MIT | SWE-agent distilled: one bash tool, ~190-line agent loop, pluggable environments |
| OpenHands | `1f7b1e6` 2026-10-20 | MIT | **Repo changed identity** — now the Agent Canvas TS frontend; the Python agent/runtime moved to `OpenHands/software-agent-sdk` (see §3) |
| Agentless | `5ce5888` 2024-12-22 | MIT | No agent at all: fixed localize → repair → validate pipeline, sampling + test-based re-ranking |
| auto-code-rover | `585d3e6` 2025-04-24 | **SONAR Source-Available v1.0 (NOT open source)** | AST-structure search + spectrum-based fault localization, patch-applicability retry, Docker differential validation |
| moatless-tools | `011ead5` 2025-09-01 | MIT | Tool library + MCTS search-tree flow over a code index; best-in-slice edit tool |
| SWE-bench | `02e7a74` 2026-09-02 | MIT | The benchmark harness: FAIL_TO_PASS / PASS_TO_PASS grading in per-instance Docker images |
| gpt-engineer | `a90fcd5` 2024-11-17 | MIT | One-shot app generator + diff-based *improve* mode with salvage-and-retry |
| MetaGPT | `11cdf46` 2026-01-21 | MIT | Multi-role "software company": SOP pipeline PM → Architect → Engineer → QA over a message bus |
| smol-developer | `a6747d1` 2023-09-25 | MIT | The original ~100-line prompt pipeline: plan → file list → generate each file. No execution at all |

---

## 1. mini-swe-agent — the highest-value steal in this slice

Repo: `SWE-agent/mini-swe-agent`. Deliberately minimal ("the simplest, smallest, most readable agent", `AGENTS.md:3-5`): agent + model + environment are three swappable protocols, composed by a run script.

### Agent / verification loop
- The whole control flow is `DefaultAgent` (`src/minisweagent/agents/default.py`, 190 lines): `run()` L106-140 loops `step()` = `query()` → `execute_actions()` until a message with `role="exit"` appears.
- **Budgets are checked before every model call, in code, not in the prompt** — `query()` L147-167 raises `LimitsExceeded` on `step_limit` / `cost_limit` (default $3.00, `AgentConfig` L32) and `TimeExceeded` on `wall_time_limit_seconds`. JARVIS equivalent today: brain round/call caps exist, but *cost* and *wall-clock* caps per code-task do not. **Steal.**
- **Format-error circuit breaker:** `run()` L114-131 counts *consecutive* `FormatError`s, resets the counter on any clean step, and exits with `RepeatedFormatError` after `max_consecutive_format_errors=3` (L38-39). This is the exact antidote to a small local model looping malformed tool calls — deterministic, 10 lines.
- There is **no built-in test/verification step**: verification is delegated to the prompt template (the SWE-bench config tells the model to reproduce, fix, re-run) and to the external SWE-bench harness (§6). The submission mechanism is a sentinel: the model runs `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` and the *environment* detects it (`environments/local.py:47-58`, `docker.py` `_check_finished`) and raises `Submitted` with everything after the sentinel line as the submission. A completion signal the *runtime* enforces, not a claim the model makes — directly comparable to moatless's `VerifiedFinish` (§7) and better than trusting an LLM's "done".
- Trajectory is saved after **every** step (`finally: self.save(...)`, L132-133) — a crash never loses the run. JARVIS session store already does causal logging; the steal is *save-in-finally*, not save-at-end.

### Sandbox design (the menu JARVIS should copy selectively)
Four environment classes behind one `execute(action) -> {output, returncode, exception_info}` protocol (`environments/__init__.py`):
- **Local** (`environments/local.py`, 92 lines): raw `subprocess.Popen(..., shell=True)` on the host — explicitly *not* a sandbox. One gem inside it: `_run()` L78-92 starts a new session/process group and on timeout `os.killpg(SIGKILL)`s the **whole group** so no orphaned children survive (Windows branch: `process.kill()`). JARVIS's `code_run` uses `subprocess.run(timeout=...)`, which kills only the direct child on Windows — grandchildren leak. **Steal the process-tree kill** (on Windows stdlib: `taskkill /T /F` via subprocess, or Job Objects via ctypes — both stdlib).
- **Docker** (`environments/docker.py`): container started once (`docker run -d ... sleep 2h`, L84-108), commands via `docker exec -w <cwd>` with an explicit env-forward allowlist (`forward_env`, L118-123), `cleanup()` on `__del__` (L152-161). Pattern only — no Docker on the owner's path.
- **Bubblewrap** (`environments/extra/bubblewrap.py`): `bwrap --unshare-user-try --ro-bind ...` (config L29-52) — read-only binds of system dirs, writable only the work dir. Linux-only, but the *principle* maps to JARVIS exactly: **default read-only, writable set enumerated**. JARVIS's jail already does this for its own tools; the gap is `code_run`'s child process, which inherits full user FS rights (cwd is pinned, nothing else is). Bubblewrap is the proof that "cwd pin ≠ sandbox".
- **Singularity / SWE-ReX / Modal** variants confirm the protocol is the product: swap the environment, the agent never changes.

### Steal verdict — mini-swe-agent
**STEAL (patterns, ~40 lines total):** (1) pre-call budget checks (steps + cost + wall-clock) in the code skill's run path; (2) consecutive-format-error breaker (reset on success); (3) process-**tree** kill on timeout; (4) runtime-detected submission sentinel instead of model-claimed completion; (5) save-trajectory-in-`finally`. **DON'T STEAL:** `shell=True` local env, LiteLLM/pydantic deps, Docker env (no Docker on owner PC).

---

## 2. SWE-agent — the original ACI: tool bundles, lint-gated edits, reviewer loops

Repo: `SWE-agent/SWE-agent` (Princeton/Stanford lineage). ~11.4k lines of Python in `sweagent/` plus a `tools/` tree of *bash tool bundles* — the crucial architectural idea: **tools are directories** (`bin/` executables + `config.yaml` declaring signature/docstring/args + optional `install.sh`), loaded into the environment, e.g. `tools/windowed/`, `tools/windowed_edit_linting/`, `tools/search/`, `tools/submit/`, `tools/registry/`. JARVIS skills are already directories with a manifest — SWE-agent proves the same shape works for *tools inside the sandbox*, declared in YAML rather than code.

### Agent / verification loop
- `DefaultAgent` (`sweagent/agent/agents.py:443`) runs the classic reproduce-first workflow, but note *where* it lives: the **instance template** (`config/default.yaml:19-27`) instructs: find code → write a reproduction script and run it → edit → **re-run the reproduction script** → think about edge cases. Verification as a scripted workflow in the prompt, executed with the same bash tool — cheap and effective, and JARVIS's code skill has *no* equivalent workflow text today. **Steal the workflow, verbatim-adapted, into `skills/code/SKILL.md`.**
- **Lint-gated edit with automatic revert** — the single best edit-tool design in this slice. `tools/windowed_edit_linting/bin/edit`: flake8 the file *before* the edit (L94-95), apply the edit, flake8 again, diff the error sets (`format_flake8_output(..., previous_errors_string=pre_edit_lint, ...)`, L100-107); if the edit introduced **new** errors, it calls `wf.undo_edit()`, prints the would-have-been window next to the original, and exits 1 (L109-122). Pre-existing errors don't block; only *regressions* do. Stdlib translation for JARVIS: `compile()` / `ast.parse()` the file before and after `code_edit` — no flake8 needed for the syntax-regression case — and auto-revert from the `.bak` that `code_edit` already writes. **STEAL — this upgrades `code_edit` from "exact-once match" to "exact-once match + no new syntax errors, or nothing happened".**
- **Review-on-submit:** the `review_on_submit_m` bundle intercepts `submit`: first submission returns a checklist + the full `{{diff}}` (`config/default.yaml:44-62`) — re-run your reproduction script, delete it, revert any test-file changes — and only a second `submit` actually submits. A *deterministic speed-bump* between "model thinks it's done" and "done". Stdlib-stealable as a gate rule for code tasks: first finish attempt returns diff + checklist, second confirms.
- **Reviewer / retry loops** (`sweagent/agent/reviewer.py`, 664 lines): `RetryAgent` (`agents.py:257`) wraps `DefaultAgent` and re-runs whole attempts. `ScoreRetryLoopConfig` (L200-239): a reviewer model scores each submission; retry while `score < accept_score`, bounded by `max_attempts`, a shared `cost_limit`, and `min_budget_for_new_attempt` (don't start an attempt you can't afford to review — the comment at L213-218 is explicit that the last review is exempt from the budget or the last attempt is wasted). `ChooserRetryLoop` / `Preselector` (L242+) pick the best of N finished trajectories. For JARVIS: full reviewer-model loops are too heavy for a 9B local brain, but the **budget arithmetic** (reserve review cost before starting a retry) and **score-gated retry with hard attempt cap** are stealable as deterministic policy around `code_run` test results — retry on *test score*, not on vibes.
- **Action guardrails:** `ToolHandler` (`sweagent/tools/tools.py:227`) filters every bash action against a blocklist before execution — prefix blocklist (`vim`, `nohup`, `gdb`, `tail -f`, `make`, L37-48) and standalone blocklist (`python`, `bash`, `sh`, `su` alone, L51-65), plus `block_unless_regex` exceptions. It's an *interactivity* blocklist (things that hang an agent), not a security one — but the mechanism (deterministic pre-execution filter with a templated refusal) is exactly JARVIS's gate shape. Also `check_for_submission_cmd` (L372) and `_guard_multiline_input` for heredoc safety.

### Sandbox design
Execution is delegated to **SWE-ReX** (`sweagent/environment/swe_env.py:8-17,51`): `SWEEnv` talks to a deployment abstraction (Docker / Modal / Fargate / local) and runs bash in a persistent session via `communicate()` (L197-232). The repo itself contains no sandbox — it *outsources* isolation to the deployment. Honest lesson for JARVIS: SWE-agent can afford raw bash because the container is the jail. JARVIS has no container, so it must keep doing the opposite — no shell, argv-only, socket-neutered — and steal only the guardrail layers that sit *above* the sandbox (blocklist, lint-gate, review-on-submit).

### Steal verdict — SWE-agent
**STEAL:** lint/syntax-gated edit with auto-revert (top-3 steal of this slice); reproduce-first workflow text; review-on-submit two-step finish; score/budget retry arithmetic. **STEAL (shape):** tools-as-bundles (validates JARVIS's skill-dir design). **DON'T STEAL:** SWE-ReX/Docker execution, bash-as-the-only-tool, reviewer-model loops at local-model scale.

---

## 3. OpenHands — ⚠️ the repo you clone today is not the agent anymore

Repo: `OpenHands/OpenHands` at HEAD `1f7b1e6` (2026-10-20) is **Agent Canvas**: a React/TypeScript frontend + local-stack orchestrator. Its own `AGENTS.md` ownership table says so explicitly: this repo owns "Agent Canvas UI, frontend state, backend selection"; the **Python SDK, Agent Server, agents/tools, conversations and the REST/WebSocket API now live in `OpenHands/software-agent-sdk`**, skills in `OpenHands/extensions`, scheduling in `OpenHands/automation`. The classic OpenHands Python monorepo (CodeActAgent, Docker runtime, microagents) is **not in this clone** — any "OpenHands sandbox design" claim sourced from this repo would be fabricated. Flagged for the parent: *the agent-side OpenHands study belongs to a slice that clones `software-agent-sdk`.*

What this repo *does* contain, verified locally:
- **Backend abstraction as a product feature:** one frontend drives agent servers running locally, in Docker, on VMs, or in cloud, switchable mid-work (README "Switch between different backends"). The contract discipline is real code: `src/api/agent-server-adapter.ts` builds versioned start-requests for both native and **ACP (Agent-Client Protocol)** agents (`acp_server`, `acp_command`, `acp_model` — see `agent-server-adapter.test.ts:99-124`), and `src/api/agent-server-compatibility.ts` gates features on the backend's server version, with `compatibility.minimumAgentServer` raised whenever Canvas starts requiring a new endpoint (AGENTS.md checklist).
- **Working-dir discipline:** `src/api/agent-server-config.ts:1` — a single `DEFAULT_WORKING_DIR = "workspace/project"` constant, resolved per-backend (L200-255: ask the backend for its home via `GET /api/file/home` rather than assuming a path exists on the machine that runs the code). "Never hardcode where the agent's files live; ask the execution backend" is a genuine, stealable principle for JARVIS's phone/remote path.
- **Automations:** scheduled/webhook-triggered agent runs (Slack/GitHub/Linear) as a first-class surface — the same shape as JARVIS's proactivity + phone roadmap, productized.
- Verification *of this repo* is `npm run lint`, `npm test`, `npm run build` (AGENTS.md) — a frontend pipeline, irrelevant to the code skill.

### Steal verdict — OpenHands (this repo)
**STEAL (product patterns only):** backend-swappable agent server behind a versioned contract (JARVIS: PC-local today, phone-relay later, same skill protocol); resolve working dir from the executing backend, never hardcode. **DON'T STEAL / NOT PRESENT:** no sandbox, no edit tool, no verification loop exists in this clone to steal. **Action for parent:** reassign classic-OpenHands (CodeAct + Docker runtime) to the `software-agent-sdk` repo if that study is still wanted.

---

## 4. Agentless — delete the agent, keep the pipeline (and the best patch-selection loop in the slice)

Repo: `OpenAutoCoder/Agentless`. The thesis is in `README.md:25-28`: a fixed three-phase process — **localization, repair, patch validation** — with no autonomous loop at all. ~8k lines, each phase a standalone script over JSONL files.

### The pipeline (all deterministic orchestration, LLM only inside steps)
1. **Localization** (`agentless/fl/FL.py`, `LLMFL.localize` L313): hierarchical narrowing — file level → class/function level (`localize_function_from_compressed_files` L363, using *skeletonized* files: signatures only, bodies stripped, `agentless/util/index_skeleton.py`) → exact lines (`localize_line_from_coarse_function_locs` L546). Plus an embedding-retrieval localizer (`fl/retrieve.py`) whose results are merged. The skeleton trick is the steal: a 9B local model localizing in a big file should see the skeleton first, not 2,000 lines.
2. **Repair** (`agentless/repair/repair.py`): for each localized location, sample many candidate patches — 1 greedy + temperature samples up to `--max_samples` default **20** (L402-483, L739). Patches are expressed as search/replace blocks and *normalized* before comparison (`util/postprocess_data.py: normalize_patch`) so whitespace-equivalent patches dedupe.
3. **Patch validation / re-ranking** (`agentless/repair/rerank.py`) — **the verification loop JARVIS should copy**: for each candidate patch, (a) run a set of **regression tests** — tests that passed *before* the patch, selected by the LLM from the pre-patch passing list (`agentless/test/select_regression_tests.py: select_test` L39, `run_regression_tests.py`); a patch's score includes how many it breaks; (b) generate a **reproduction test** from the issue text (`agentless/test/generate_reproduction_tests.py`, 559 lines), run it against each patched tree (`run_reproduction_tests.py`); score = reproduction passes? Re-rank = reproduction result first, regression breakage second (rerank.py L27-72 loads both result files per sample and sorts). Only the winner is submitted. No Docker in the loop itself — tests run in the target repo's own environment via `agentless/test/run_tests.py` (630 lines).

### Sandbox design
None — deliberately. Agentless runs on a prepared benchmark checkout; safety comes from *never executing model-chosen commands*: the only things run are the repo's own tests and the generated reproduction script, both through fixed harness code. That constraint is itself the lesson: **an agent that cannot run arbitrary code needs a much smaller sandbox.** JARVIS's tier-3 `code_run` is the general case; an "Agentless mode" for fix-a-bug tasks (only `pytest <selected>` may run, nothing else) would be tier-2-able.

### Steal verdict — Agentless
**STEAL (top-3 of this slice):** the validation protocol as a *deterministic post-edit step* for JARVIS code tasks — (1) snapshot which relevant tests pass **before** the edit, (2) generate/run a reproduction script for the reported bug, (3) re-run both after the edit; success = reproduction now passes **and** zero previously-passing tests broke. All stdlib (`subprocess` + `pytest` if present, else `unittest`). **STEAL:** skeleton-first localization for large files; patch normalization/dedupe if sampling is ever added. **DON'T STEAL:** 20-sample repair (cloud-API economics; on a local 9B that's 20× the latency for a chat turn — a 3-sample variant is the ceiling).

---

## 5. auto-code-rover — structure-aware search, SBFL, and *differential* validation (⚠️ ideas only — source-available license)

Repo: `nus-apr/auto-code-rover` (NUS program-repair group). Clone note: the tree contains 37,318 files (bundled corpora/assets), which stalled a plain full clone; the studied copy is a `--depth 1 --filter=blob:none` clone with sparse checkout of `app/` + root files at the same HEAD — all refs below are from that code.

### Search: never dump files, walk the AST structure
`app/search/search_backend.py` (970 lines): at startup `SearchBackend` builds indexes over the repo's AST (L52-113) — class name → (file, line range), function/method index, and a class→superclass relation map. The tools the model gets are *structural*: `search_class` (L276) returns **only the class signature** — name, bases, and the signatures of all methods/properties (docstring L279-283) — `search_class_in_file` (L318) returns a full class body only when asked within a file, and line→(class, function) lookup is L129-130. This is Agentless's skeleton idea (§4) implemented as a real index instead of prompt-side stripping: the model navigates by *symbols*, expanding detail on demand, so context spend is proportional to relevance. Stdlib translation for JARVIS is direct: `ast` module walk of the jail building {class: (file, start, end, [method signatures])} — a `code_search` tier-1 tool in ~120 lines, no tree-sitter.
On top of search sits **spectrum-based fault localization** (`app/analysis/sbfl.py`, 685 lines): run the failing/passing tests under coverage, rank statements by how suspicious their pass/fail correlation is (classic Ochiai-style SBFL from the program-repair literature), and feed the ranked locations to the patch writer. Research-grade, and honest verdict: **don't steal for JARVIS** — it needs coverage tooling and a real test suite per project; the symbol index gives most of the practical benefit at a fraction of the machinery.

### Verification loop: applicability retry + baseline-vs-patched differential
- **Patch applicability is its own loop:** `app/agents/agent_write_patch.py: _write_applicable_patch` (L130-160) retries patch generation until the patch *applies cleanly* to the tree ("Failed to write an applicable patch in {retries} attempts"), with a feedback channel (`add_feedback` L124, `write_applicable_patch_with_feedback` L117) that carries the apply failure back into the next attempt. Applicability (does it apply?) is separated from correctness (does it fix?) — two different failure classes, two different loops. JARVIS's `code_edit` exact-once rule already guarantees applicability for single edits; the steal is for *multi-file patch* generation if JARVIS ever emits diffs: validate-apply first, feed the failure back, cap retries.
- **Differential validation:** `SweTask.validate` (`app/task.py:205`) runs the SWE-bench Docker test suite **twice** — once with a *noop patch* to capture the baseline status map (`_run_test_suite_for_regression_docker` L223-234: `orig_status_map` from `make_noop_patch` L257), once with the candidate patch — then compares: fixed = baseline-failing now passing, regressions = baseline-passing now failing. This is SWE-bench's F2P/P2P (§6) computed *by the agent, before submission*, against a measured baseline rather than a gold list. It also has a separate `agent_reproducer` (generates the reproduction test), `agent_reviewer`, and `agent_select` (picks among candidate patches) — the same separation-of-duties as Agentless §4 / MetaGPT §9, independently arrived at.
- `Task.apply_patch` (task.py:77) is a **context manager**: enter = apply patch, exit = `clean_active_project_changes` — the patched state cannot leak into the next candidate. JARVIS's `.bak` gives the same guarantee for single files; a context-manager-shaped "trial edit" (apply all edits → run tests → keep or revert-all) is the multi-file generalization.

### Sandbox design
Validation runs inside SWE-bench's per-instance Docker images (`app/api/swe_bench_docker_validation.py: run_pre_existing_tests` L37); the search/patch agents themselves run on the host against a checkout. Same split as SWE-agent: isolation is outsourced to Docker, intelligence runs outside it.

### Steal verdict — auto-code-rover
**IDEAS ONLY (license: SONAR Source-Available, Non-competitive Purpose only — no code borrowing, and a "JARVIS" product use is exactly the grey zone not to enter).** **STEAL (ideas):** AST symbol index as a `code_search` tool (stdlib `ast`); baseline-vs-patched differential as the definition of regression (already convergent with §4+§6); trial-edit context manager (apply-all → test → keep-or-revert-all); applicability-vs-correctness as separate retry loops. **DON'T STEAL:** SBFL/coverage localization (too heavy), Docker validation, any literal code.

---

## 6. SWE-bench — not an agent: the grading oracle every agent above is judged by

Repo: `SWE-bench/SWE-bench`. This is the harness that turns a model's patch into a verdict. Its design is the purest **verification loop** in the slice, and it's fully deterministic — no LLM anywhere in grading.

### The grading contract
- Each instance carries two test lists, mined from the gold PR: **FAIL_TO_PASS** (tests that failed before, must pass after — the bug is fixed) and **PASS_TO_PASS** (tests that passed before, must still pass — nothing regressed). `make_test_spec` (`swebench/harness/utils.py:251-269`) assembles them into a `TestSpec` with the eval script and log parser.
- `get_resolution_status` (`swebench/harness/grading.py:308-327`): **FULL** only if F2P = 1.0 *and* P2P = 1.0; **PARTIAL** if 0 < F2P < 1 with P2P = 1.0; otherwise **NO**. And `get_eval_report` (L329-393) sets `resolved=True` *only* on FULL (L388-389) — partial credit exists in the report but never counts as solved.
- **Anti-fake-success hardening** is the part to study line by line: if the test log is missing/unparseable, `resolved` stays False and the instance is flagged `infra_failure` with a classified reason instead of being silently scored (L364-376, with comments at L30 and L159 in the same file calling out exactly the failure mode — a suite that never ran must never read as resolved). Patch-is-None, patch-exists, patch-successfully-applied are separate booleans (L354-383) so "the patch didn't even apply" is distinguishable from "tests failed".
- Execution: `run_evaluation.py: run_instance` (L229) creates a per-instance Docker container from a prebuilt image (client at L65-67), applies the prediction patch inside it, runs `/eval.sh` via `exec_run_with_timeout` (L367), then parses the log with a per-framework log parser (`harness/log_parsers/python.py`, `javascript.py`). One instance = one disposable container = zero cross-contamination.

### Steal verdict — SWE-bench
**STEAL (the definition of "verified" for JARVIS code tasks):** adopt F2P/P2P as the *completion criterion* inside the code skill — before a fix task, record the failing test(s) (F2P set) and the passing neighbours (P2P set); after the edit, `code_run` executes exactly those; the task may be reported done only at FULL (all F2P pass, zero P2P broke), PARTIAL must be reported as partial. **STEAL:** the infra-failure rule — *no parseable test output ⇒ not verified, never "probably fixed"*; and the three separate booleans (edit applied / tests ran / tests passed) in `code_run`'s result schema. This is Agentless's validation (§4) with the scoring made rigorous — together they are the verification upgrade path for `skills/code`. **DON'T STEAL:** Docker-per-instance images (GBs each; impossible/pointless on the owner's PC) — JARVIS's equivalent isolation is the jail + `.bak` + a fresh subprocess.

---

## 7. moatless-tools — the best edit tool and the best "done" tool in the slice

Repo: `aorwall/moatless-tools` (~45k lines). A tool/action library plus agent flows (ReAct and an MCTS **search tree**) over a tree-sitter code index. Two actions are directly relevant to JARVIS's `code_edit` / finish semantics; the rest is a catalogue of what a mature action set looks like (`moatless/actions/`: `view_code`, `find_class`, `find_function`, `semantic_search`, `grep_tool`, `run_tests`, `run_mypy`, `create_file`, `insert_line`, `append_string`, `view_diff`, `finish`, `verified_finish`, …).

### StringReplace — JARVIS's exact-once edit, grown up
`moatless/actions/string_replace.py` (672 lines). `StringReplace.execute` (L255+):
- Rejects `old_str == new_str` as a no-op observation instead of writing (L276-283).
- Finds **exact** matches first (`find_exact_matches`, L629); if exactly one exact match exists *in the file-context the model was shown* but more exist globally, it proceeds and flags the observation `targeted_in_context_replacement` — context-scoped disambiguation instead of a hard error.
- On **zero** exact matches it does not give up: `find_match_when_ignoring_indentation` (L492) looks for a match modulo leading whitespace; if exactly one potential match exists and `auto_correct_indentation` is on, it **auto-corrects** — adjusts `new_str`'s indentation by the uniform indent diff, rewrites `args.old_str/new_str` so the message history shows what actually happened, flags `auto_corrected_indentation`, and applies.
- Tabs are normalized up front (`expandtabs()` on content and both strings, L269-271) — killing the entire class of "my edit didn't match because of a tab" failures before matching starts.

Compare JARVIS today: zero matches = error, >1 = error, tabs/whitespace = model's problem. Moatless shows the middle path that keeps determinism: *exact → in-context-exact → indentation-insensitive-unique (with auto-correction + flag)*, each step still requiring uniqueness. **STEAL — top-3 of this slice, and fully stdlib** (`str.expandtabs`, line-wise compare). The flags-in-observation pattern also matters: the model is *told* its edit was auto-corrected, so its mental model of the file stays true.

### VerifiedFinish — "done" is an action with required evidence fields
`moatless/actions/verified_finish.py`: finishing is a tool call whose args schema **requires** `finish_reason` *and* `test_verification` — a structured description of which tests were added/modified, what scenarios they cover, and how they verify the change (L15-25). `VerifiedFinish.execute` (L75+) returns a terminal observation. It doesn't machine-check the claim (that's SWE-bench's job), but it makes an *unevidenced* finish unrepresentable in the protocol — the same "structure over detection" doctrine as JARVIS's own rules. **STEAL:** JARVIS's code-task finish should require the same two fields, and the gate can machine-check the cheap half (did `code_run` actually execute a test since the last edit?).

### Search tree + testbed (pattern-level)
- `moatless/flow/search_tree.py`: MCTS over agent states — `_select` (L181, UCT), `_expand` (L224), `_simulate` (L271), `_backpropagate` (L327), with a *discriminator* (`moatless/discriminator/`) and value function scoring nodes, so the agent can abandon a bad branch instead of being trapped in one linear history. Powerful, and **too heavy for JARVIS chat** (multiple simultaneous trajectories × a 9B local model). Steal only the cheap shadow of it: keep the `.bak` chain + trajectory so a failed attempt can be *rolled back and retried from the branch point* — linear undo already gives 80% of this at 5% of the cost.
- Runtime: `moatless/runtime/testbed.py` — `run_tests(patch)` (L105) applies a patch, runs tests, maps failures back to code blocks (`_map_test_results_to_issues` L324, `_filter_failing_tests` L226) and caches by patch+test hash (`_generate_cache_key` L213). `runtime/local.py` runs commands as asyncio subprocesses with a `backup_killer` watchdog (L290-323). The **failure→code-block mapping** (test output parsed into "this span, this error") is stealable in stdlib for `code_run` results: return structured failures, not a 10 KB text blob.

### Steal verdict — moatless-tools
**STEAL:** the 3-stage edit matcher with indentation auto-correction + flags; `expandtabs` normalization; VerifiedFinish's required-evidence finish action. **STEAL (small):** structured test-failure results from `code_run`. **DON'T STEAL:** tree-sitter index, MCTS flow, pydantic-everywhere (all non-stdlib / oversized for the target).

---

## 8. gpt-engineer — one-shot generation, human-gated execution, and salvage-the-diffs

Repo: `gpt-engineer-org/gpt-engineer`. Two modes: generate a whole app from a prompt (specify → generate files → generate an entrypoint `run.sh`), and *improve* mode over an existing codebase.

### Verification / execution loop
- **Human-gated execution, 2023-style:** `execute_entrypoint` (`gpt_engineer/core/default/steps.py:205-268`) prints the generated entrypoint command and asks `Do you want to execute this code? (Y/n)` (L238-249); anything but yes skips execution. Only then `execution_env.upload(files_dict).run(f"bash {ENTRYPOINT_FILE}")` (L266). This is exactly JARVIS's tier-3 owner approval, arrived at independently — convergent evidence the tier is right. (Its flaw is also instructive: approval is a bare y/n on a shell string, no action-hash binding — JARVIS's gate already does this better.)
- **Improve mode = diff protocol + salvage loop:** the model returns unified diffs; `salvage_correct_hunks` (steps.py L341+) parses them (`core/diff.py: parse_diffs`), and for every non-new-file diff calls `diff.validate_and_correct(lines_dict)` (diff.py L340) — checking the diff's context lines actually exist in the current file, correcting line numbers where possible — then applies what survived. `_improve_loop` (steps.py L315-339): any diffs that failed validation are sent back to the model *with the specific errors*, "Only rewrite the problematic diffs… Make sure to not repeat past mistakes", up to `MAX_EDIT_REFINEMENT_STEPS = 2` (`core/default/constants.py:12`). **Salvage what's valid, retry only what's broken, cap the retries** — the same shape as mini's format-error breaker but at diff granularity. **STEAL** for any future JARVIS multi-edit: never re-ask for the whole change because one hunk failed.
- Memory is just files on disk (`core/default/disk_memory.py`): every step logs its full message list (`memory.log(DEBUG_LOG_FILE, …)`) — auditability by default.

### Sandbox design
None, and it's the cautionary tale of the slice: `DiskExecutionEnv.run` (`core/default/disk_execution_env.py:74-111`) is `subprocess.Popen(command, shell=True, cwd=working_dir)` with a hand-rolled polling loop and a manual timeout that `p.kill()`s. No isolation, no output cap, no network control — acceptable for a 2023 demo, disqualifying as a design to copy in 2026. JARVIS's existing `code_run` (argv list, `-I`, socket guard, caps) is strictly stronger; keep it.

### Steal verdict — gpt-engineer
**STEAL:** salvage-and-retry-only-the-failures loop (cap 2) for multi-hunk edits; log-every-step's-messages audit habit (already JARVIS doctrine). **STEAL (validation):** its y/n execution gate confirms tier-3. **DON'T STEAL:** `shell=True` execution env, entrypoint-`run.sh` generation pattern (a chat-first JARVIS runs the file it just wrote, it doesn't generate a launcher script for it).

---

## 9. MetaGPT — the software company: SOPs, a message bus, and a real QA loop

Repo: `FoundationAgents/MetaGPT` (ex-`geekan/MetaGPT`). Multi-agent by *role*: ProductManager → Architect → ProjectManager → Engineer → QaEngineer, coordinated not by a shared prompt but by an **Environment message bus**: roles `_watch` for message types (`cause_by`) and publish typed `Message`s (`metagpt/environment/base_env.py`: `Environment` L124, `publish_message` L175, `run(k)` L197 round-robins the roles). `Team` (`metagpt/team.py`) hires roles, runs `n_round` rounds. The SOP (standard operating procedure) is encoded in *which role reacts to which document type*: PRD → design → tasks → code → tests.

### The verification loop (the part worth stealing)
- `QaEngineer` (`metagpt/roles/qa_engineer.py:39`) watches for code summaries and runs a genuine loop: `WriteTest` (L58, `_write_test` L62) generates tests for the engineer's code → publishes a `RunCodeContext` to itself (L92-100) → `RunCode` (`_run_code` L105) executes → on failure, routes to `DebugError` (`_debug_error` L150) and back around; on success the task is done. Test-writing, execution, and debugging are *separate actions owned by a separate role* — the generator never grades its own homework, which is JARVIS's "separate generation from evaluation" upgrade in multi-agent form.
- `RunCode` (`metagpt/actions/run_code.py:78`): `run_script` (L92-118) is `subprocess.Popen(command, cwd=working_directory, env=env)` with `communicate(timeout=10)` and a timeout log — plus dependency installation (`_install_dependencies` L171: pip-installs requirements and pytest into the working dir first). No sandbox beyond cwd + timeout, like gpt-engineer.
- `Engineer` (`metagpt/roles/engineer.py:73`) adds two discipline mechanisms: a summarize-and-review cycle (`_act_sp_with_cr` L116, optional `WriteCodeReview`, `actions/write_code_review.py`) with `config.max_auto_summarize_code` capping self-summarize iterations, and `_is_pass` (L255) gating progression on a review verdict.

### Sandbox design
None (host subprocess). MetaGPT's isolation story is organizational, not technical: roles constrain *who may do what*, nothing constrains *what the code can do*.

### Steal verdict — MetaGPT
**STEAL (one idea, high value):** role separation for verification — in JARVIS terms, the *check* on a code task (run tests, read failures, judge) should be a fresh-context pass with only task + diff + test output, never the generating conversation grading itself. That's implementable today as a deterministic verifier step + a clean-context critique call, no multi-agent framework needed. **STEAL (small):** publish/subscribe over typed documents maps cleanly onto JARVIS's session-store causal log (already ahead). **DON'T STEAL:** the whole SOP company (PRD/design/task docs for a one-line fix is ceremony a personal assistant can't afford), `n_round` message-bus runtime, host-subprocess execution.

---

## 10. smol-developer — the ancestor: 100 lines, three prompts, zero verification

Repo: `smol-ai/developer` (swyx, 2023). Included because every repo above descends from it — and because it's the control group that shows what the verification loops are *for*.

`smol_dev/main.py` (104 lines) is the entire system: `plan(prompt)` → a `shared_deps.md` (what libraries/utilities all files will share), `specify_file_paths(prompt, shared_deps)` → a list of files, then for each file `generate_code_sync(prompt, shared_deps, file_path)` → `write_file` (main.py L13-71). Prompts in `smol_dev/prompts.py`. That's it: **no execution, no tests, no iteration, no error path** — if the generated code is broken, the program still prints "smol dev done!".

The one idea that survived into everything else: **`shared_deps.md` — state the cross-file contract before generating any file.** SWE-agent's templates, gpt-engineer's preprompts, and Agentless's skeleton index are all refinements of "agree on the shared structure first". For JARVIS multi-file writes: one cheap planning artifact (files + their shared names/signatures) written into the jail before the first `code_write`, then each file generated against it. **STEAL (that one idea).** Everything else: **DON'T STEAL** — no sandbox (writes wherever the path says), no verification, GPT-4-0613 function-call era code, effectively unmaintained since 2023-09-25.

---

---

# Synthesis — what JARVIS v2's code skill should become

## The convergent design (5 of 10 repos agree, independently)
The slice's strongest signal is not any single repo — it's that Agentless, auto-code-rover, SWE-bench, SWE-agent, and MetaGPT **all converged on the same verification skeleton**, despite opposite architectures (pipeline vs agent vs multi-agent):

1. **Reproduce before you fix** — a runnable reproduction of the bug exists before any edit (SWE-agent prompt workflow, Agentless reproduction tests, rover's reproducer agent).
2. **Baseline before you touch** — record which tests pass *pre*-edit (Agentless regression selection, rover's noop-patch status map, SWE-bench's P2P list).
3. **Verify differentially after** — done = reproduction now passes AND zero baseline tests broke; partial is reported as partial, never as done (SWE-bench FULL/PARTIAL/NO).
4. **No evidence ⇒ not verified** — a test run that produced no parseable output is an infra failure, not a pass (SWE-bench grading hardening).
5. **The generator doesn't grade itself** — selection/verification is a separate step, role, or program (Agentless re-ranker, rover's select agent, MetaGPT's QA role, SWE-agent's reviewer).

JARVIS's code skill today implements **none** of the five as mechanism (they live, at best, as prompt advice). Implementing 1-4 as a deterministic `code_verify` step around `code_edit`/`code_run` is the single highest-value change this slice produces — and it is entirely stdlib: snapshot test results → edit → re-run same tests → diff the two status maps → report FULL/PARTIAL/NO in the tool result.

## Ranked steal list for `skills/code` (all stdlib, all Windows-compatible)
| # | Steal | Source | Effort |
|---|---|---|---|
| 1 | `code_verify`: F2P/P2P differential completion criterion (FULL/PARTIAL/NO; no-output ⇒ not verified) | SWE-bench §6 + Agentless §4 + rover §5 | M |
| 2 | Syntax-gated edit: `ast.parse` before/after `code_edit`; new syntax error ⇒ auto-revert from `.bak`, return both windows | SWE-agent lint-edit §2 | S |
| 3 | 3-stage edit matcher: exact → in-context-exact → indentation-insensitive-unique with auto-correct + flag in result; `expandtabs` first | moatless §7 | S |
| 4 | Process-**tree** kill on `code_run` timeout (Windows: Job Object / `taskkill /T`) — today grandchildren leak | mini §1 | S |
| 5 | Budgets checked in code before each run: steps + wall-clock (+ cost where metered); consecutive-format-error breaker (reset on success) | mini §1 | S |
| 6 | Finish protocol: first finish returns diff + checklist (re-run reproduction, revert test edits); second confirms. Plus required `test_verification` field | SWE-agent §2 + moatless §7 | S |
| 7 | `code_search`: AST symbol index (class/function → file, span, signature-only view) as a tier-1 tool | rover §5 + Agentless skeleton §4 | M |
| 8 | Salvage loop for multi-hunk changes: apply valid hunks, retry only failed ones with their errors, cap 2 | gpt-engineer §8 | S |
| 9 | Trial-edit transaction: apply-all → test → keep-or-revert-all (generalizes `.bak`) | rover §5 | M |
| 10 | Runtime-detected completion sentinel / save-trajectory-in-`finally` | mini §1 | S |
| 11 | `shared_deps` contract file before multi-file generation | smol §10 | S |
| 12 | Backend-resolved working dir (ask the executor where files live; never hardcode) — for the phone/remote path | OpenHands §3 | S |

## Anti-steals (named so nobody re-litigates them)
- **Docker as the sandbox** (SWE-agent, SWE-bench, mini-docker, rover): the owner's JARVIS has no Docker in its path; the jail + argv-only subprocess + socket guard stays, hardened by steals #2/#4.
- **`shell=True` execution** (mini-local, gpt-engineer, MetaGPT RunCode): every repo that has it either wraps it in a container or is a demo. JARVIS's no-shell rule is * ahead* of this slice — keep it.
- **20-sample patch generation** (Agentless): cloud economics. Local ceiling ≈ 3 samples, and only inside a fix-task mode.
- **MCTS search trees / SBFL / reviewer-model loops** (moatless, rover, SWE-agent): real techniques, wrong scale for a 9B local brain in a chat turn. Their cheap shadows (undo-chain branching, symbol index, deterministic verifier) are already in the steal list.
- **Multi-role SOP ceremony** (MetaGPT): keep only the separation-of-evaluation principle.
- **Any auto-code-rover code**: source-available license, Non-competitive Purpose only. Ideas documented above; code untouched.

## Coverage / honesty notes
- Researched + code-read locally: **10/10 repos**. Validated by running: none of the repos were executed (clone-and-read mission; several need API keys/Docker by design).
- OpenHands caveat (§3): the cloned repo no longer contains the classic agent — that study needs `OpenHands/software-agent-sdk` if wanted.
- auto-code-rover caveat (§5): studied via blobless sparse clone (37,318-file tree stalled the plain clone); HEAD identical.
- Outcome label: **new combination of known techniques** — the steal list is a composition (SWE-bench grading × moatless editing × mini budgets) into JARVIS's tiered/jail model; no single repo contains it.
