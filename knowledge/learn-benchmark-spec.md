# Reproducible Benchmark Suite — Complete Specification

*PHASE INFINITY, Research Cycle 9. §18 artifact #7 (reproducible benchmark suite) as a SPECIFICATION.*
*Date: 2026-10-19. Status: spec complete, UNEXECUTED — running it is BLOCKED on access to Owais's PC.*
*Rule Zero check: commands, stats, and decision rules below reference (not re-teach) `learn-inference-frontiers.md`, `learn-evaluation-science.md`, `rtx-2060-guide.md`, `learn-observability.md`, `learn-advanced-cs.md`, `learn-underspecification.md`.*

---

## 0. Purpose and non-goals

**Purpose:** Turn the benchmarking weekend into a mechanical procedure. Someone sitting at Owais's PC follows this document top to bottom, fills in the results ledger, and every v2 architecture decision that depends on measurement gets its number. No judgment calls mid-weekend, no "let's try one more thing."

**Non-goals:** This spec does not choose models (it produces the data that chooses them). It does not tune prompts. It does not benchmark cloud providers (their numbers come from dashboards/billing, not the lab).

**The one principle:** *Every expected value in this document is an estimate to be REPLACED by measurement.* Estimates are marked `[EST]`. Measured values are marked `[MEA]`. Never ship a decision on an `[EST]`.

---

## 1. Environment pins (the laboratory)

Record ALL of these in the results ledger before Track A. If any differ from the pins, note the deviation — do not silently proceed.

| Item | Pin | How to verify |
|---|---|---|
| Machine | Owais's PC: Ryzen 5 3600 (6C/12T), 16 GB RAM, RTX 2060 6 GB | `wmic cpu get name`, `nvidia-smi` |
| OS | Windows 10/11 64-bit (record build) | `winver` |
| GPU driver | Record exact version (e.g., 581.xx) | `nvidia-smi` top-left |
| CUDA toolkit | 12.x (record exact) | `nvcc --version` |
| llama.cpp | **Pin the commit**: `git rev-parse HEAD` at build time, record full hash | Build log |
| Build flags | `-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=75` (Turing sm_75; prebuilt binaries PTX-JIT on Turing — build from source) | CMakeCache |
| Alternative | ik_llama.cpp (only if Qwen3.5-9B IQ4_XS is tested — record fork commit too) | Build log |
| Power plan | **High performance**; display sleep OFF during runs | `powercfg /list` |
| GPU exclusivity | Close Chrome/Discord/OBS/anything with GPU. Verify `nvidia-smi` shows ~0 MiB used by other processes before every track | `nvidia-smi` |
| TDR | Note Windows TDR timeout (default 2 s can kill long kernels — record whether changed) | Registry |
| Room state | Note if the PC was cold-booted vs warm (first-run variance); always warm up (see §3) | Ledger note |

**Reproducibility rule:** any number reported without its environment pin block is anecdote, not data.

---

## 2. Results ledger (the metrics schema)

Every measurement appends ONE JSONL record to `benchmark-results.jsonl` (kept in a private folder — see §6 contamination guards). No spreadsheets, no screenshots of numbers.

```json
{
  "track": "A",
  "run_id": "A-003",
  "timestamp": "2026-11-02T14:30:00+05:30",
  "env": {"llama_cpp_commit": "<40-hex>", "driver": "581.42", "cuda": "12.6",
           "power_plan": "high-performance", "gpu_idle_mib": 12},
  "subject": {"model": "Qwen2.5-7B", "quant": "Q4_K_M", "file": "qwen2.5-7b-q4_k_m.gguf",
              "source": "<hf repo + revision>"},
  "command": "llama-bench -m ... (exact)",
  "params": {"p": 4096, "n": 256, "reps": 5, "ngl": 99,
             "cache_type_k": "q8_0", "cache_type_v": "q8_0", "flash_attn": true},
  "metrics": {"pp_mean": 0.0, "pp_ci95": [0.0, 0.0],
              "tg_mean": 0.0, "tg_ci95": [0.0, 0.0],
              "ttft_p50_ms": 0, "vram_peak_mib": 0},
  "notes": "second run after reboot; first run discarded (cold)"
}
```

**Statistical treatment (from `learn-evaluation-science.md` — applied, not re-taught):**
- Speed (continuous): mean ± 95% t-interval, n ≥ 5 reps. Never report a single run.
- Accuracy (proportions): Wilson 95% CI. Report format: `value (95% CI, n=N)`. Never a bare percentage.
- Paired comparisons (same task set, two models): McNemar's test on discordant pairs; exact binomial version when b+c < 25.
- Comparing >2 models on the same set: Holm step-down correction. Uncorrected "wins" are noise.
- Power floor: with a 50-task golden set, a <10pp difference is below the detection floor — call it a tie, pick on other grounds (VRAM, speed).

---

## 3. The six tracks

### Track A — Model shootout (tool-call accuracy per quant)

**Objective:** Choose the brain. **Decision it feeds:** `config.yaml` → `brain.model`, tier assignment (daily driver / tool brain / fallback).

**Candidates (shortlist — do not add more without re-running everything):**

| # | Model | Quant | Expected VRAM @4k [EST] | Role tested |
|---|---|---|---|---|
| A1 | Qwen2.5-7B | Q4_K_M | ~5.1 GB | Daily driver candidate |
| A2 | Qwen3.5-9B | IQ4_XS | ~5.3 GB | Ambitious candidate (needs ik_llama.cpp or recent llama.cpp) |
| A3 | Qwen3.5-4B | Q4_K_M | ~3.0 GB | Tool-brain tier candidate |
| A4 | Qwen2.5-3B | Q4_K_M | ~2.2 GB | Fallback tier candidate |

**Explicitly NOT tested:** q4_0 of anything (destroys tool calling: 63%→20% BFCL — established, do not re-measure), Q3_K_M (quality cost known), BitNet (separate CPU track, see A-phase 3).

**Phase A1 — Fast screen (speed + TTFT, all 4 candidates). ~30 min.**

Per candidate, in order:
```powershell
# 1. Load check — does it fit with headroom?
# Launch server, watch nvidia-smi during a 4k-context request. Record peak MiB.
llama-server -m <model>.gguf -ngl 99 -c 4096 --cache-type-k q8_0 --cache-type-v q8_0 --flash-attn --port 8080

# 2. Speed — 5 reps, YOUR context length (prefill and decode are different bottlenecks; record both)
llama-bench -m <model>.gguf -p 4096 -n 256 -r 5 -ngl 99 --cache-type-k q8_0 --cache-type-v q8_0

# 3. TTFT — time to first token at 4k prompt (the latency users feel)
# Script: POST a 4096-token prompt to /completion with n_predict=1, stream, record time-to-first-byte. 10 reps.
# (Use the provided ttft_probe.py sketch in §7 — fill in before the weekend.)
```
Warmup: discard the first `llama-bench` rep of the day per model (cold kernels). Record pp (prefill tok/s) and tg (decode tok/s) means + 95% CIs.

**Kill rule:** any candidate with peak VRAM > 5.5 GB at 4k context is ELIMINATED from accuracy testing (no headroom for the voice stack — see Track D). Do not "try to make it fit."

**Phase A2 — Deep accuracy (finalists only: top 2 by A1 that survive the kill rule). ~4–6 hr.**

Per finalist:
1. **BFCL-style tool-call eval:** run the Berkeley Function-Calling Leaderboard harness (or the pinned subset — record harness version/commit). Report per-category accuracy (never just the average — multi-turn is where agents live), Wilson CIs. Minimum 100 tasks; 3 seeds if time allows.
2. **Private agentic bench:** 50–100 hand-built tasks from JARVIS's actual workload shape (file ops, multi-step tool chains, error recovery, Hinglish prompts). Each task: fixed prompt, deterministic checker (script or exact-output match — LLM-judge only where deterministic checking is impossible, and then with a pinned judge + rubric). This is the ONLY eval that separated Q4–Q8 quants in prior findings (1/12 vs 12/12) — it is the tiebreaker.
3. **Contamination hygiene:** private tasks live in the private folder (§6). Never paste them into a cloud model. Never commit them to a public repo.

**Decision rule (from `learn-inference-frontiers.md`):** biggest model whose tool accuracy is within noise (overlapping 95% CIs) of the best, at Q4_K_M or better, fitting 6 GB with ≥400 MiB headroom at 4k context. Record the decision + the CI table that justifies it in `DECISION-PLAYBOOK.md` under Brain.

**Phase A3 — CPU tier (BitNet). ~30 min.** BitNet-b1.58-2B-4T via the CPU runner: measure tok/s on the Ryzen 3600 (expectation [EST]: ~40 tok/s, ~1.3 GB RAM). Decision it feeds: always-on tier viability. If <25 tok/s sustained, the always-on tier needs re-scoping.

---

### Track B — Latency track (TTFT + tok/s at 4k, per tier)

**Objective:** Set the tier-routing latency budgets. **Decision it feeds:** tier thresholds (which tasks go to which tier), voice-loop latency budget.

**Note:** B reuses A1's measurements for the GPU models — do not re-run. B adds:

1. **Turn-shape latency:** simulate a real agent turn — prefill 4k prompt → decode 200 tokens → prefill 4k again (context regrown). Measure end-to-end wall time, 10 reps, per finalist model. This is the number the UX is built on, not `tg128`.
2. **Voice-loop budget check:** STT (Whisper-small INT8, CPU) + brain turn + TTS (Kokoro-82M, CPU) end-to-end on a fixed 5-second Hindi+English test clip. Measure: audio-in → first-audio-out. Target [EST]: <2.5 s. If exceeded, the budget table says which stage to attack (do not guess — the measurement says).
3. **Record:** per-stage breakdown (VAD ms, STT ms, prefill ms, decode ms, TTS ms). The breakdown IS the deliverable — a single end-to-end number teaches nothing.

**Commands:**
```powershell
# Whisper latency (faster-whisper or whisper.cpp — record which, pin version)
# Fixed clip: 5 s, 16 kHz, mixed Hindi/English. 10 reps. Record p50/p95.
# Kokoro: fixed 20-word Hindi + 20-word English sentence. 10 reps each. Record p50/p95 + RTF (real-time factor; must be <1.0).
```

---

### Track C — Grounding track (vision/OCR latencies on the 2060)

**Objective:** Choose the grounding stack and prove it fits the latency budget. **Decision it feeds:** perception architecture (which grounder, which OCR, when tree-suffices).

**Candidates:**

| # | Model | Expected VRAM [EST] | Tests |
|---|---|---|---|
| C1 | ShowUI-2B | ~2 GB | 20 grounding queries |
| C2 | Qwen2.5-VL-3B | ~2.5 GB | 20 grounding queries |
| C3 | PaddleOCR | CPU | 20 screenshots |
| C4 | Tesseract | CPU | 20 screenshots (baseline) |

**Procedure (per candidate):**
1. **Grounding accuracy:** 20 fixed screenshots of real Windows UI (File Explorer, Settings, Chrome, VS Code — capture once, reuse for all candidates). Each with a known target element + ground-truth bounding box. Query: "click the <element>". Metric: % with predicted point inside ground-truth box (Wilson CI, n=20 — wide CIs expected; this is a screen, not a decision).
2. **Latency:** per-query wall time, p50/p95. Budget [EST]: p95 < 800 ms for interactive use (from prior findings — re-verify against the turn-shape budget from Track B).
3. **OCR:** same 20 screenshots. Metric: character accuracy on UI text regions (use a fixed annotation), plus latency p50/p95. Note table-structure failures (expected: all fail — record it, don't re-litigate).
4. **Co-residency check:** can the winner load alongside the Track A winner? If combined VRAM > 5.5 GB, the grounder runs on-demand (load → ground → unload), and the load/unload latency joins the budget.

**Decision rule:** highest accuracy within the p95 latency budget; ties broken by VRAM (smaller wins — headroom is a feature).

---

### Track D — VRAM track (budget partitioning, OOM boundaries)

**Objective:** Produce the VRAM budget table and the OOM guard values. **Decision it feeds:** `config.yaml` OOM guards, co-residency matrix, tier definitions.

**Procedure:**
1. **Single-residency map:** load each Track A finalist at 2k/4k/8k context. Record `nvidia-smi` peak per context length. Fit the line: VRAM ≈ weights + (bytes/token × context). This gives the per-model bytes/token number [MEA] to replace the [EST] table.
2. **Co-residency matrix:** brain (Track A winner) + Whisper-small (GPU? test both CPU and GPU placement) + Kokoro (CPU) + grounder (Track C winner, on-demand vs resident). For each combination: load all, run one turn of each, record peak. Mark combinations >5.5 GB as FORBIDDEN in the matrix.
3. **OOM boundary probe:** deliberately push context length up in 1k steps until allocation fails. Record the failure mode (clean OOM error vs hang vs driver crash — the failure MODE matters for the guard design). The guard is set at least 1k below the boundary.
4. **Fragmentation check:** load → unload → reload the brain 5 times; record whether peak creeps (CUDA allocator fragmentation). If it creeps >200 MiB, the design needs periodic restarts or `PYTORCH_CUDA_ALLOC_CONF` equivalents — record the finding, don't fix it this weekend.

**Deliverable:** a table — rows: deployment scenarios (chat-only, voice-full, voice+grounding), columns: brain, STT placement, TTS placement, grounder mode, peak VRAM [MEA], headroom, status (OK/FORBIDDEN). This table goes into `config.yaml` comments and the playbook.

---

### Track E — Reliability track (fallback chain, checkpoint/replay)

**Objective:** Measure the recovery machinery. **Decision it feeds:** retry constants, fallback timeouts, checkpoint cadence, the graceful-degradation ladder thresholds.

**Procedure (mostly CPU — can run in parallel with GPU tracks):**
1. **Fallback chain under simulated failure:** point the brain router at a mock provider script that fails with (a) 429, (b) DNS error, (c) timeout, (d) 500. For each: measure time-to-recovery (first successful response from the next provider) and verify NO fallback hole (the C-B1 class: transport errors must trigger fallback, never return immediately). 20 trials per failure type. Metric: recovery rate (target 100%), p95 time-to-recovery.
2. **Checkpoint/replay timing:** on a synthetic 200-event session log, measure: checkpoint write time, cold-start replay time (full log), snapshot+replay time. Vary log size (200 / 2k / 20k events — synthetic). The replay-time-vs-size curve sets the snapshot cadence (from `learn-advanced-cs.md`: snapshots are the #1 production add).
3. **Durable queue crash test:** enqueue 10 jobs, kill the dispatcher mid-run (Task Manager), restart, verify: no job lost, no job double-executed (idempotency), poison job quarantined after N retries. This is the C-B1/C-B4 failure class made into a test.
4. **Record** the constants this justifies: provider timeout ms, max retries, checkpoint interval (events), snapshot threshold.

---

### Track F — Discriminator track (gating tree search)

**Objective:** Measure discriminator accuracy on JARVIS's real tool domain. **Decision it feeds:** whether tree search / best-of-N is ENABLED (needs ≥90% — from `learn-frontier-reasoning.md`).

**Background (referenced, not re-taught):** tree search only beats simple re-ranking when the discriminator (the judge picking among candidate trajectories) reaches ≥90% accuracy. LLM self-judges don't reach it in literature. The environment (tests, compilers) can serve as the discriminator where verifiable.

**Procedure:**
1. **Build the pair set:** 60–100 items. Each item: a task + two candidate tool-call trajectories (A correct, B flawed — wrong args, wrong order, hallucinated tool). Source: the private agentic bench tasks (Track A2) — reuse, don't rebuild. Label by construction (you wrote the flaw). Contamination: private folder only (§6).
2. **The discriminator under test:** the candidate judge (same brain model, judge prompt pinned in the ledger). For each pair: present both trajectories, ask which is correct. Metric: accuracy (Wilson CI). Also record calibration: when the judge says "confident," is it right?
3. **The environment-as-discriminator arm:** for the subset where a deterministic verifier exists (unit tests, schema validation, dry-run), score verifier-vs-judge agreement. This tests the "verifier is the strategy" claim directly.
4. **Decision rule:** per the canonical Cycle 7 rule (`learn-discriminator-protocol.md` §5, DISC-100): gate on `min(wilson_lo, worst_safety_stratum_lo) ≥ 0.90` → tree search ENABLED for that domain, with the measured accuracy recorded as the operating assumption. Below → tree search DISABLED; single-pass ReAct + belief ledger only. No exceptions, no "but it felt smart." *(Corrected Cycle 18: an earlier draft used a 0.85 lower-bound bar — superseded by the stricter, better-justified Cycle 7 rule.)*
5. **Pair-set note:** prefer building from DISC-100 (`learn-discriminator-protocol.md` — 8 flaw types, "both bad" reject option, per-stratum gating) rather than inventing a new set; the 60–100 items here are a runtime subset of that instrument.

---

## 4. The runbook (benchmarking weekend)

**Friday evening — Setup (~1 hr)**
- [ ] Cold boot. Close everything GPU-resident. `nvidia-smi` shows ~0 MiB used.
- [ ] Power plan → High performance. Display sleep OFF.
- [ ] Build llama.cpp from source (`-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=75`). Record commit hash.
- [ ] Download the 4 Track A candidates (+ checksums). Record HF repo + revision per file.
- [ ] Create `benchmark-results.jsonl`. Fill the env pin block (§1).
- [ ] Capture the 20 grounding screenshots (Track C) + annotate ground-truth boxes. Save privately.
- [ ] Write the 50–100 private agentic tasks (Track A2) + the 60–100 discriminator pairs (Track F). Canary-string every file (§6).

**Saturday — GPU day (~8–10 hr)**
- [ ] Track A1: fast screen, all 4 candidates (~30 min). Apply kill rule immediately.
- [ ] Track B stage 1: turn-shape latency on A1 survivors (~30 min).
- [ ] Track D: VRAM map + co-residency + OOM probe (~1 hr). **Do this BEFORE assuming any co-residency.**
- [ ] Track A2: BFCL harness on the 2 finalists (~1–2 hr, runs unattended — start it, do Track C setup while it runs).
- [ ] Track A2: private agentic bench on the 2 finalists (~2–4 hr, mostly unattended).
- [ ] Track C: grounding accuracy + latency, 4 candidates (~1.5 hr).
- [ ] Track B stage 2: voice-loop end-to-end (~30 min).
- [ ] Track A3: BitNet CPU tier (~30 min, runs on CPU — parallel with anything).

**Sunday — Reliability + analysis (~4–6 hr)**
- [ ] Track E: fallback/replay/queue tests (~1.5 hr, mostly CPU).
- [ ] Track F: discriminator pair eval (~1 hr).
- [ ] Analysis: compute all CIs, run McNemar/Holm where applicable, fill the decision table (§5).
- [ ] Record every decision in `DECISION-PLAYBOOK.md` with its evidence pointer (result run_ids).
- [ ] Replace every `[EST]` in the playbook's hardware section with `[MEA]` or mark still-estimated.

**If a track fails:**
- Download fails → retry once, then drop the candidate (note it; do not burn the weekend on infra).
- OOM during a track → stop, record the boundary (that IS the data), move on.
- Harness won't run → fall back to the private bench only, note the gap.
- Anything takes >2× its estimate → timebox it, record partial, move on. The weekend ends Sunday night regardless.

---

## 5. Decision outputs (track → decision → recorded where)

| Track | Decision | Recorded in | Revisit trigger |
|---|---|---|---|
| A | `brain.model` + quant; tier assignments (daily/tool/fallback) | `config.yaml`, playbook Brain section | New model release with BFCL scores; VRAM change |
| B | Tier latency budgets; voice-loop stage targets | playbook Voice section, `config.yaml` timeouts | Hardware change; model change |
| C | Grounder choice; OCR choice; on-demand vs resident | playbook Perception section | New grounding model with published numbers |
| D | OOM guard values; co-residency matrix; max context per tier | `config.yaml` (as comments + guards), playbook | Driver/CUDA/llama.cpp update |
| E | Provider timeout ms; retry counts; checkpoint interval; snapshot threshold | `config.yaml`, playbook Reliability section | Any fallback incident in production |
| F | Tree search ENABLED/DISABLED per domain | playbook Reasoning section + the 8-strategy table | Discriminator improvement (new judge prompt/model) |

**Every decision entry format:** `DECISION: <what> | EVIDENCE: run_ids <...> | CI: <...> | DATE: <...> | REVISIT: <trigger>`. A decision without evidence pointers is an opinion.

---

## 6. Contamination guards

1. **Private tasks never leave the machine.** The agentic bench, discriminator pairs, and grounding annotations live in a private folder (e.g., `%APPDATA%/JARVIS/bench-private/` or an encrypted volume). Never in a public repo, never pasted into a cloud chat, never in a GitHub issue.
2. **Canary strings:** every private file starts with a unique canary GUID (e.g., `BENCH-CANARY-9f3a2c1e-...`). If the string ever appears in a model's output, the set is burned — rotate and rebuild.
3. **Held-out split:** 70% dev (may be used for prompt tuning), 30% held-out (NEVER used during development decisions; only for the final acceptance check). The split is recorded in the ledger; violating it invalidates the weekend.
4. **No training on the bench:** the private tasks are never used for fine-tuning, LoRA training, or imatrix calibration data.
5. **Version everything:** task set version, prompt version, model id + quant + commit, seed. A result without versions is not reproducible.

---

## 7. Appendix: ttft_probe.py sketch (fill in before the weekend)

```python
# Measures time-to-first-token at fixed prompt length against llama-server.
# Usage: python ttft_probe.py --prompt-tokens 4096 --reps 10 --port 8080
# Records: per-rep TTFT ms -> prints p50/p95 + appends JSONL (schema §2).
# TODO before weekend: implement prompt construction (fixed token count via
#   the model's tokenizer), streaming request, first-byte timing.
# NOTE: first rep after server start is warmup — discard, do not record.
```

---

## Confidence, unknowns, references

**Confidence:** [VC] on the statistical treatment (from `learn-evaluation-science.md`, formulas verified there); [HC] on the command shapes (from `learn-inference-frontiers.md` + llama.cpp docs); [MC] on wall-clock estimates (derived from tok/s math, not measured — the weekend measures them); [SP] on the 800 ms grounding budget (prior finding, re-verify in Track B).

**Unknowns (to be resolved BY the weekend, not before):**
1. All `[EST]` values — that's the point.
2. Whether ik_llama.cpp is needed (decided by A2's IQ4_XS result).
3. Whisper/Kokoro real latencies on the 3600 (Track B measures).
4. The discriminator's actual accuracy (Track F measures — gates tree search).
5. OOM failure mode: clean error vs hang (Track D observes).

**References (real, verified in prior studies — not re-verified here):** llama.cpp docs (llama-bench pp/tg semantics, `--cache-type-k/v`, KL-divergence perplexity methodology); Berkeley BFCL (function-calling eval); Agresti & Coull 1998 (Wilson interval); Holm 1979 (step-down correction); Bergstra & Bengio 2012 JMLR (random search — the "don't grid-search configs" rule, applies to any config sweep this weekend).

**What this spec does NOT do:** choose the model, fix the code, or run anything. It makes the weekend mechanical. The weekend makes the decisions. The decisions go in the playbook with evidence pointers. Anything else is opinion.
