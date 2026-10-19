# AI for Software Engineering — Evaluation (SCOPED)

*Part of the JARVIS knowledge base. Researched October 2026. LEARNING ONLY.*

**Question answered:** JARVIS will write and modify code on Owais's PC. How do we MEASURE whether it's doing it correctly?

---

## 1. SWE-bench — what it measures, and why it's broken as a frontier signal

**Mechanism [VC]:** SWE-bench (Jimenez et al., 2023, ICLR 2024) takes real GitHub issues from 12 Python repositories, pairs each with the repository's actual fix (gold patch) and its test suite (FAIL_TO_PASS tests that the gold patch makes pass, PASS_TO_PASS tests that must keep passing). An agent is given the issue text + repo snapshot and must produce a patch. Score = resolved rate (% of instances where the patch passes both test sets). The original full set is 2,294 instances; **SWE-bench Verified** is a human-filtered 500-instance subset (OpenAI + SWE-bench team, Aug 2024). Variants: **SWE-bench Multilingual** (300 instances, 42 repos, 9 languages), **SWE-bench Multimodal** (517 instances with visual elements), **SWE-PolyBench** (Amazon, 2,000+ issues, 21 repos, arXiv 2504.08703), **SWE-bench Pro** (Scale AI, longer tasks, public + held-out + commercial repos).

**Why it was a breakthrough [HC]:** first widely-adopted *executable* benchmark — the patch must import, the tests must run, behavior must change, existing behavior must hold. Tests-as-specification is the closest thing to an objective correctness oracle we have.

**Why it's no longer a frontier signal [HC]:**
- **Saturation:** bash-only Verified leaderboard tops ~79%; vendor-reported numbers reach ~95%. Remaining headroom is noise.
- **Task size:** 161 of 500 Verified tasks are 1–2 line changes; average ~11 lines changed, ~1 file touched. A spot-the-diff exercise, not software engineering.
- **Harness confound:** a 100-line Python agent scores 65% on Verified — much of the historical spread was scaffolding quality, not model capability.
- **Contamination:** OpenAI's Feb 2026 audit found frontier models (GPT-5.2, Claude Opus 4.5, Gemini 3 Flash) could reproduce gold patches and problem-specific details from training data — the benchmark's solutions are in the training corpora.
- **Flawed tests:** OpenAI audited 138 failure-heavy tasks; 59.4% of *that subset* had material test-design or problem-description issues (35.5% overly strict tests rejecting functionally correct solutions; 18.8% testing unspecified functionality). Note: 59.4% is of the audited hard-task subset, NOT of all 500 — don't misquote this.
- **SWE-bench Pro isn't clean either:** OpenAI's later audit estimated ~30% of Pro's public tasks were broken. Realistic evaluation inherits real engineering's ambiguity.

**JARVIS application [HC]:** Use SWE-bench *methodology* (issue → patch → FAIL_TO_PASS/PASS_TO_PASS), never SWE-bench *scores*, for model selection. For JARVIS's own code changes, the pattern is: every change ships with its own test list; a change is "done" only when new tests pass AND the existing suite is green. Scores on public leaderboards are contaminated noise — validate on our own tasks.

**References:** SWE-bench paper (Jimenez et al., ICLR 2024); SWE-bench Verified (OpenAI, Aug 2024); OpenAI Feb 2026 audit ("Why SWE-Bench Verified no longer measures frontier coding progress"); aiwiki.ai SWE-bench page (data-quality studies incl. SWE-Bench+ 32.67% solution-disclosure finding); SWE-PolyBench arXiv 2504.08703.

---

## 2. Other codegen evals — what each actually tests

| Benchmark | What it tests | Contamination status | Matters for JARVIS? |
|---|---|---|---|
| **HumanEval** (Chen et al., 2021) | 164 single-function Python completions, pass@k | Saturated (>95% frontier), effectively memorized | NO — leaderboard only |
| **MBPP** | ~1k entry-level Python problems | Same as HumanEval | NO |
| **LiveCodeBench** (Jain et al., 2024, arXiv 2403.07974) | Code generation + self-repair + code execution + test-output prediction on contest problems (LeetCode/AtCoder/Codeforces) released AFTER model cutoff; 4 scenarios | Contamination-resistant by design (temporal isolation); detected contamination in GPT-4o, Claude, DeepSeek, Codestral via time-segmented eval | PARTIAL — best honest single-model coding signal, but contest problems ≠ repo engineering |
| **RepoBench** (Liu et al., ICLR 2024) | Repository-level: -R retrieval of cross-file snippets, -C next-line completion with cross-file context, -P full pipeline; Python + Java | Static dataset; some contamination risk | YES for retrieval eval — -R directly measures the "find the right context" skill JARVIS needs |
| **Commit0** (Zhao et al., arXiv 2412.01769) | Generate entire libraries from scratch: 54 Python libs, implementations erased, agent fills from specs; scored on % of original test suite passing | Moderate (libraries are public) | YES as the ceiling test — can JARVIS build, not just fix? Note: skeleton prescribed, so design ability untested |
| **ProgramBench** (2026) | Rebuild programs from executables, no prescribed structure | New | WATCH — tests actual software design (abstractions, decomposition) |
| **SWE-bench Pro** (Scale AI) | Longer tasks, commercial repos, held-out split | ~30% public tasks estimated broken (OpenAI audit) | CAUTION |

**Key insight [HC]:** the benchmarks form a ladder — function (HumanEval) → contest (LiveCodeBench) → repo-context (RepoBench) → repo-fix (SWE-bench) → repo-build (Commit0) → design (ProgramBench). JARVIS's daily work lives at the repo-fix and repo-build rungs. Evaluate there, on private tasks.

**References:** LiveCodeBench arXiv 2403.07974; RepoBench (Liu et al., ICLR 2024); Commit0 arXiv 2412.01769; ProgramBench arXiv 2605.03546.

---

## 3. What "correct code" means — operationalized

A change is correct iff ALL of these hold [HC — synthesized from the eval literature + the v2 R-requirements]:

1. **Target behavior:** the new/affected tests pass (FAIL_TO_PASS analog).
2. **No regressions:** the full existing suite stays green (PASS_TO_PASS analog). Run it — don't assume.
3. **Minimal diff:** the change touches what the task requires and nothing else. (SWE-bench's "1 file touched" average is a *measurement*, not a virtue — but diff-size growth correlates with regression risk.)
4. **Convention match:** lint clean (ruff), types clean (mypy), style consistent with the surrounding file. A patch that passes tests but violates project conventions is a future bug.
5. **No new attack surface:** the change passes the security test suite (the 13-attack hardened_runner set). Code that works but opens injection = incorrect.
6. **Reviewable:** diff is small enough and described well enough that a human (or second model) can verify it in one pass.

**Automated check for JARVIS's code changes [MC — design proposal, untested]:**
```
pre-commit gate: ruff + mypy + security-scan on changed files
post-change gate: targeted tests (new) + full suite (existing) + diff-size flag (>X lines → escalate)
```
This is the "verify before claiming" doctrine compiled into CI. It already exists in skeleton form (pyproject.toml, CI workflow, pytest suite from the redesign) — the missing piece is wiring it as a *mandatory gate the agent cannot skip*, not a script the agent may run.

**Unknowns:** the right diff-size escalation threshold (needs measurement); whether mypy-strict is sustainable for agent-written code or produces more friction than signal.

---

## 4. The agentic coding loop — when to stop iterating

**The evidence [HC]:**
- **Debugging Decay Index** (Oxford/McGill): LLM debugging ability collapses fast. First fix attempt usually helps; the second adds marginal value; by the third, repeated edits, semantic drift, and hallucinations set in. **Performance drops up to 80% by the 5th round.** "If your tool sends the same broken code back to the LLM again and again hoping it'll get it right eventually — it probably won't."
- This is the code-domain instance of the general compounding law: 0.95²⁰ ≈ 0.36 — each additional unaudited iteration multiplies error probability.
- It also matches the fail-fast rule already in AGENTS.md (2 failed attempts = change approach): the evidence says 2 is not just a heuristic, it's approximately the measured optimum.

**The loop that works [HC]:** plan → write → **test (external signal)** → fix → test. The test suite is the verifier; the loop is productive exactly as long as each iteration brings *new external information* (a new failing test, a new error message). Iterating on the model's own opinion of its code is the failure mode.

**JARVIS policy [MC — design proposal]:**
- Max 2 self-fix iterations on the same error signature, then: change approach (different strategy, smaller scope, or escalate to Owais).
- Every iteration must consume fresh external feedback (test output, compiler error, linter message). No "try again" without new information — that's the no-change impasse type from the Soar detector.
- Track iteration count per task in the event log; tasks exceeding the budget get flagged in review.

**References:** Debugging Decay Index (Oxford/McGill, via dev.to summary — seek primary paper before design-doc citation); the compounding math (verified in learn-continual-learning.md).

---

## 5. Code review by a second model — evidence

**The core finding [VC]:** review works when the reviewer has an *independent* signal; it fails when reviewer and author share the same error distribution.

- **Huang et al. (ICLR 2024), "Large Language Models Cannot Self-Correct Reasoning Yet":** intrinsic self-correction (model critiques its own output, no external feedback) often *degrades* accuracy — models flip correct answers to incorrect ones, driven by nearby distractors. Earlier reported gains traced to **oracle-guided** correction (answer keys, external signals), not genuine self-critique.
- **The Self-Correction Blind Spot** (Tsui et al., 2026 preprint): LLMs correct identical errors presented as *external input* but fail on the same errors in *their own outputs* — 64.5% average failure rate across 14 models. Same weights, different framing. The bottleneck is error *detection*, not correction.
- **Same-model multi-agent critique ≈ self-consistency:** identical models share error distributions, so adding copies doesn't break correlation. The fix is context separation or genuinely independent evaluation channels.
- **Where review DOES work [HC]:** Reflexion-style loops (external environment feedback → lesson → retry), CRITIC (tool-based verification), and the 2026 EIR study — verify-first prompting (model must explicitly confirm before refining) cut destructive refinement on GPT-4o-mini from a 6.2-point loss to a 0.2-point gain. The pattern: review against something real.

**JARVIS policy [HC]:**
- **Never "brain reviews its own plan" as a safety mechanism** — banned by evidence (extends the research-frontiers finding).
- Second-model review is useful ONLY with: (a) a different model, or (b) the same model given genuinely different context (fresh context, no transcript history — the "separate generation from evaluation" rule), or (c) review grounded in external artifacts (test results, diff, static analysis output).
- The highest-ROI review is not model-on-model at all: **deterministic checks** (tests, types, lint, security suite) catch what models miss, and models catch what checks can't express (design judgment, convention fit).

**References:** Huang et al., ICLR 2024 ("Large Language Models Cannot Self-Correct Reasoning Yet"); Tsui et al. 2026 preprint (Self-Correction Blind Spot, preprints.org 202601.0892); critical survey arXiv 2406.01297; EIR study arXiv 2604.22273 (verify-first prompting); dreaming.press Reflexion-vs-Self-Refine comparison.

---

## Cross-cutting synthesis

1. **The verifier is the strategy** (again): every section converges here. SWE-bench works because tests are real. Debugging loops work while tests supply new information. Review works with independent signal. The eval, the loop, and the review are all the same question: *what external ground truth is this claim checked against?*
2. **Contamination is the universal confound:** public benchmark scores measure training-data exposure as much as capability. JARVIS's eval must be private, held-out, and refreshed — the golden-set recipe from learn-continual-learning.md.
3. **Two is the number:** two productive debug iterations, two-attempt fail-fast, second-model review needs independence. The evidence keeps returning the same small integers.
4. **Measurement before leaderboard:** for model selection, run the §3 gates + a private repo-fix task set on the actual 2060. Nothing public replaces it.

## Confidence summary
- [VC] on self-correction negative results (convergent 2023–2026 literature), the verifier principle, SWE-bench mechanics.
- [HC] on contamination specifics (OpenAI audit figures are single-source; treat exact percentages as audit claims, not established facts), the 2-iteration optimum (one strong study + convergent heuristics).
- [MC] on the automated-gate design and diff-size thresholds (proposals, untested).
- [UK] on Hinglish code-comment/task eval (no benchmark exists); on whether verify-first prompting transfers to agentic coding loops (measured on QA, not code).
