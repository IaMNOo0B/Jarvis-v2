# The Tool-Calling LoRA Playbook

*PHASE INFINITY, Research Cycle 30. The closest thing to "training" in the entire JARVIS program — get it right.*
*Date: 2026-10-19. Status: playbook complete, unexecuted. Implementation is a build decision (Owais's call), not authorized by this cycle.*

---

## 0. The one-paragraph version

Conscious Engines (Bengaluru) showed a 4B model with a small LoRA adapter can beat Claude Haiku 4.5 at tool-calling, trained in 4.5 hours on one rented GPU for single-digit dollars. The playbook: **first** spend one hour testing their public adapter on JARVIS's tools (nearly free — it might already be good enough as a baseline); **then**, if the gap justifies it, generate ~15–18k synthetic tool-calling examples for JARVIS's own ~40 tools (this is the real work and the real cost — roughly $50–150 in frontier-model API calls, dwarfing the ~$5 GPU bill); train a rank-64 LoRA with loss on assistant tokens only, keeping no-call examples as canaries; eval-gate everything on a private golden set with a pre-registered bar. The adapter learns *procedures* (format, which tool, when to call, when not to) — never facts (A0). Total budget: an afternoon of setup, a weekend of data review, under $200.

---

## 1. The Kinetic recipe, reconstructed

### 1.1 What we know [HC — scout Study 66, multiple corroborating details]

- **Who:** Conscious Engines, Bengaluru. **When:** ~April 2026.
- **Base:** Qwen3-4B-Instruct-2507. **Adapter:** public on Hugging Face (verify at pull — repo URL not captured by the scout; search `consciousengines` org).
- **Data:** 13,694 synthetic tool-calling samples.
- **Compute:** 4.5 hours on one rented GPU.
- **Size:** 3.18% of base parameters trainable.
- **Result:** 82.33% on Composio's tool-calling eval vs Claude Haiku 4.5 (80.0%) and GPT-OSS-120B (76.33%).
- **Recipe fragments (from the scout):** real chat template + real tool definitions in training; loss computed on assistant tokens only; no-call cases kept as canaries.
- **License:** base Apache-2.0; adapter license to verify at pull.

### 1.2 What we can derive [MC — arithmetic, stated assumptions]

**The 3.18% → rank inference.** 3.18% of 4B ≈ 127M trainable parameters. Qwen3-4B has ~36 layers, hidden size 2560, intermediate ~9728. LoRA parameters per layer with all-linear targets (q, k, v, o, gate, up, down) ≈ 2.06M × rank. 127M ÷ 2.06M ≈ **rank 64 with all-linear targets** (alpha conventionally 2× rank = 128). Other (rank, target-set) combinations give the same count, but r=64/all-linear is the clean fit and the standard choice — treat as the working hypothesis, not a confirmed fact.

**The 4.5-hour throughput check.** 13,694 samples × ~2 epochs ≈ 27k sample-updates in 16,200 seconds ≈ 1.7 samples/sec. At ~1,500 tokens/sample average (tool-calling samples are short), that's ~2.5k tokens/sec — consistent with a 4B model + r64 LoRA on an A100 40GB or RTX 4090 with unsloth/axolotl. Order-of-magnitude plausible, not verified.

**The GPU bill.** Vast.ai/RunPod 2026 pricing (check at time of use): RTX 4090 ~$0.40–0.70/hr, A100 40GB ~$0.90–1.60/hr. 4.5 hours → **$2–7**. The GPU is the cheapest line item in this entire playbook.

### 1.3 What's missing (would need figuring out)

- Exact hyperparameters (learning rate, scheduler, warmup, batch size, epochs, sequence length).
- The synthetic data generation prompt and quality-control process.
- The Composio eval's exact composition (single-turn? multi-turn? which tools?).
- Whether any general-instruction data was mixed in (anti-forgetting replay) — unknown, and it matters (§8).
- The adapter's exact Hugging Face repo path.

**None of these block us.** The recipe is standard enough to reconstruct with good defaults (§5); the missing pieces are tuned empirically, not researched.

---

## 2. The decision first: use Kinetic directly vs train vs wait

Do these **in order**. Each step is cheap and can obsolete the next.

### Step 1: Test Kinetic directly (1 hour, ~$0) [HC recommendation]

Download the public adapter, mount it on Qwen3-4B in llama.cpp (`--lora`), and run 20–30 of JARVIS's own tool-calling tasks through it. Two possible outcomes:

- **It handles JARVIS's tool format well** → the *format* skill transfers (procedures, not facts). Training then buys only tool-*specific* behavior. Recompute the ROI with a smaller expected gain.
- **It doesn't** → the gap is real, proceed to Step 2.

This is the fail-fast move. A LoRA trained on Composio's toolset owes JARVIS nothing on JARVIS's 40 tools — but the underlying format discipline (valid JSON, correct schema adherence, multi-step sequencing) is exactly what transfers. Measure, don't assume.

### Step 2: Train on JARVIS's tools (~$100–200, one weekend)

The full playbook below. Justified when Step 1 shows a gap on JARVIS's own tasks.

### Step 3 (alternative): Wait — for what, exactly?

- **Sarvam's open weights** (scout Study 72): a Hinglish-first base would change the base-model choice (§3), not the playbook. The LoRA recipe transfers.
- **Qwen4-class models**: no weights exist (scout null finding, Study 70). Not a reason to wait.
- **Verdict: don't wait.** The LoRA is a small, disposable artifact (~500MB–2GB). Training now doesn't block any future base-model swap — you retrain the adapter on the new base the same weekend. The cost of waiting (months without the accuracy gain) exceeds the cost of a disposable retrain (~$150).

---

## 3. Base model choice

| Option | Base | Why | Cost/complexity |
|---|---|---|---|
| **A (recommended start)** | Qwen3.5-4B-Instruct (or Qwen3-4B-Instruct-2507 to match Kinetic exactly) | Cheapest, fastest, replicates the proven recipe 1:1. The 4B becomes JARVIS's **tool specialist tier**. | 4.5 GPU-hours, ~$5 |
| B (stretch) | Qwen3.5-9B (JARVIS's planned daily driver) | One model for chat + tools; no tier routing needed for tool turns. | QLoRA on 9B needs ~14–16GB VRAM → rented A100 40GB, ~2× the time, ~$15–25 |
| C (deferred) | Sarvam-30B/105B (when open weights land) | Hinglish-native base. | Unknown; revisit when weights exist |

**Recommendation [HC]:** Start with A. The brain spec already has three tiers — the 4B+LoRA slots in as the tool-calling specialist, the 7B stays the chat generalist, and the router sends tool-heavy turns to the specialist. This is also the SMITH lesson in miniature: *training method beats parameter count* — a 4B trained on your tools beats a 9B that wasn't, for tool-calling specifically. Benchmark A against the 7B generalist on the golden set (§6); if the specialist wins by ≥5pp, it earns the tier.

**Base-model hygiene:** download from the official Qwen org, checksum-verify, pin the exact revision. The adapter is married to its base — document the pair (base revision + adapter version) as one unit.

---

## 4. The data playbook (the real work)

### 4.1 Tool inventory first

Before generating a single example: enumerate all ~40 tools with their exact JSON schemas, required vs optional arguments, and which tools are commonly chained. The generator needs the real schemas — synthetic data with *approximate* schemas teaches *approximate* tool-calling, which is worse than useless (it teaches confident wrongness).

### 4.2 The generation pipeline

1. **Generator:** a frontier model (the strong one — this is where quality comes from) prompted with: the real chat template, the real tool schemas for a sampled subset, and a scenario seed.
2. **Scenario seeds:** drawn from JARVIS's actual use cases (file ops, web research, scheduling, messaging, system control) + the underspecification golden set (learn-underspecification.md §5) + edge cases (ambiguous requests, multi-step chains, parallel calls).
3. **Output format:** (user request → assistant reasoning → tool call(s) → tool result → final answer), with loss computed on assistant tokens only (the Kinetic recipe).
4. **Verification pass:** every generated example gets schema-validated mechanically (does the tool call parse? do the arguments match the schema? are required args present?). Reject failures — don't "fix" them by hand; a rejected example is cheaper than a learned bad habit.
5. **Human review sample:** 200–300 examples reviewed by a human (Owais or a reviewer who knows the tools). If >5% are wrong, fix the generator prompt, regenerate — don't patch examples individually.

### 4.3 The mix (concrete numbers)

| Category | Count | Purpose |
|---|---|---|
| Single tool calls | ~6,000 | Bread and butter: right tool, right args |
| Multi-step sequences (2–4 calls) | ~3,500 | Chaining, using prior results as args |
| Parallel independent calls | ~1,500 | Batching correctly |
| **No-call canaries** | ~2,500 (15%) | Requests answerable without tools — the model must NOT call. *This is the anti-overfitting canary.* |
| Negative/correction | ~1,500 | Wrong tool chosen → corrected; teaches the boundary |
| Hinglish tool calls | ~1,000 | Code-switched requests (needs native review, §4.5) |
| Ask-vs-act (underspecification) | ~500 | Vague requests → asks instead of acting |
| General chat replay | ~1,000 (6%) | Anti-forgetting: normal conversation, no tools |
| **Total** | **~17,500** | Slightly above Kinetic's 13,694 — justified by 40 tools + Hinglish |

### 4.4 A0 enforcement — concrete data rules (procedures, never facts)

1. **No real user data.** No real names, paths, keys, or personal facts in any example.
2. **No facts that change.** Dates, prices, versions, weather — use placeholders (`<DATE>`, "example.com") or timeless values. If the model can't learn it from weights without it going stale, it doesn't go in the data.
3. **Synthetic but schema-valid arguments.** Every argument value must validate against the real tool schema.
4. **What the adapter learns:** tool-call *format*, *which* tool for which intent, *argument mapping* from natural language, *sequencing*, *when NOT to call*. **What it never learns:** any fact about the world, the user, or the tools' outputs.
5. **Audit:** grep the final dataset for secret patterns, real-looking keys, and personal identifiers before training. One poisoned example in 17,500 is a rounding error in loss and a landmine in behavior.

### 4.5 Hinglish in the mix — the hard part, honestly

Synthetic Hinglish from a frontier model risks **translationese** — grammatically Hindi-flavored English that no one actually speaks. The 1,000 Hinglish examples need:

- **Seed-first:** start from 50–100 real Hinglish requests (Owais's own phrasing — the Cycle 8 golden set is the seed corpus).
- **Expand by variation**, not by translation: paraphrase the seeds, vary the code-switching points, vary transliteration spellings (*kar do / krdo / kardo*).
- **Native review:** every Hinglish example gets a "would someone actually say this?" check. Machine-generated Hinglish that fails this check teaches the model to expect phrasing that never arrives — actively harmful.
- **Confidence: [MC]** on synthetic Hinglish quality even with review; the real fix is production data over time (the memory loop captures real phrasing).

### 4.6 What the data costs (the GPU is the cheapest part)

- **Generation:** ~17,500 samples × ~2,000 tokens avg (prompt + completion) ≈ 35M tokens. At frontier pricing (~$2–5/MTok blended), **~$70–175**. With a mid-tier generator (~$0.50/MTok), ~$18. **Recommendation:** strong model for the seed 3,000, mid-tier for the expansion 14,500 → ~$40–60 total [MC — check pricing at time of use].
- **Verification:** mechanical (free) + human review of ~300 samples (~3–4 hours of human time — the actual bottleneck).
- **GPU:** ~$5 (see §1.2).
- **Total: ~$50–200 + one human weekend.** The human review is the scarce resource, not the money.

---

## 5. The training setup (concrete config)

**Stack:** unsloth (fastest Qwen LoRA training) or axolotl (most configurable). Either is fine; unsloth if you want it done tonight.

| Hyperparameter | Value | Why |
|---|---|---|
| Base | Qwen3.5-4B-Instruct (pinned revision) | §3, Option A |
| Rank (r) | 64 | Matches Kinetic's 3.18% param count (§1.2) |
| Alpha | 128 | Standard 2× rank |
| Targets | All linear (q,k,v,o,gate,up,down) | Matches the param-count derivation |
| Learning rate | 2e-4 | Standard LoRA starting point for 4B |
| Scheduler | Cosine, 3–5% warmup | Standard |
| Epochs | 2–3 | Kinetic-scale data; watch the canary, not the loss |
| Batch | As large as VRAM allows (grad accum to 32–64 effective) | Stability |
| Sequence length | 4096 | Tool-calling samples are short; 4k is plenty |
| Loss masking | Assistant tokens only | The Kinetic recipe — don't train on user/tool tokens |
| Precision | bf16 | Standard |

**Hardware:** one rented A100 40GB or RTX 4090 (~$0.50–1.50/hr). ~5 hours. **Do not train on the 2060** — 6GB is enough for *inference* of the finished adapter, not for training it (optimizer states + activations need the headroom). This is a $5 rental, not a hardware project.

**Checkpointing:** save every 500 steps; keep the best 2 by held-out canary pass rate (not by training loss).

---

## 6. The eval harness (pre-registered bars — FAILED-first discipline)

Run **before** training (baseline) and **after** (delta). All on the **private** golden set — never the training data, never public benchmarks as decision metrics (learn-continual-learning.md §3).

| Eval | What it measures | Bar to ship |
|---|---|---|
| JARVIS golden tool tasks (private, ~100) | Tool accuracy on OUR tools | **≥5pp improvement over base**, Wilson CI |
| No-call canary set (~200) | Did we break "don't call"? | **≥98% no-call rate** (no regression vs base) |
| Chat quality spot set (~50) | General conversation didn't degrade | No human-judged regression |
| Safety spot set (~30) | Refusals, safe completions intact | **Zero regressions** (any failure = don't ship) |
| BFCL-style synthetic held-out | Same-distribution learning check | Improvement expected; informational only |
| Post-quantization check | Q4_K_M base + GGUF LoRA | Tool accuracy within 2pp of fp16+LoRA |

**Ship rule:** golden-set gain ≥5pp AND zero safety/chat regressions AND canary holds. Otherwise: don't ship, diagnose (usually a data problem, §4 — not a hyperparameter problem).

**The reflex caution [HC]:** a public LoRA adapter was once *worse* than the frozen base on held-out data — sharper on its training mix, duller elsewhere. The golden set (different distribution from training) is the only thing standing between us and that failure mode. Trust the golden set, not the training curve.

---

## 7. Deployment (the llama.cpp path)

1. **Convert:** adapter → GGUF LoRA (llama.cpp's LoRA-to-GGUF conversion; verify the script name in the pinned llama.cpp revision).
2. **Serve:** `llama-server -m qwen3.5-4b-q4_k_m.gguf --lora jarvis-tools.gguf` — the adapter applies at runtime over the quantized base. LoRA strength is adjustable live (`--lora-scaled`), which gives a free ablation: sweep the scale on the golden set to find the operating point.
3. **Co-residency:** 4B Q4_K_M (~2.5GB) + adapter (~0.5–2GB depending on rank/export) fits easily alongside the 7B daily driver in 6GB — or run the specialist *instead* of the generalist for tool-heavy turns (the tier router decides).
4. **Versioning:** adapter files are versioned artifacts (v1, v2…) with their eval scores. Rollback = point at the previous file. No retraining to undo.

---

## 8. The risks (honest)

1. **Safety erosion (the big one).** Continual-learning §1.1: safety mitigations are often the *first* thing naive fine-tuning destroys. Mitigations: safety examples in the mix, the §6 safety spot set as a ship-blocker, and the knowledge that 3.18% of weights can still move refusal behavior. **This is why the safety eval is a gate, not a metric.**
2. **Chat quality degradation.** The specialist gets dumber at chat. Mitigations: general-chat replay in the mix (§4.3), the chat spot set, and the architectural backstop — it's a *specialist tier*, not a replacement. The 7B still does chat.
3. **Synthetic-distribution overfit (the reflex lesson).** Mitigation: the golden set is a different distribution; the no-call canary; diverse phrasing in generation.
4. **Hinglish translationese.** Mitigation: seed-first + native review (§4.5). Residual risk accepted and labeled.
5. **Distillation ceiling.** Synthetic data from a frontier model teaches the frontier model's *format*, not superhuman tool judgment. The adapter makes the 4B *reliable*, not *brilliant*. Calibrate expectations: +5–15pp on tool accuracy, not a new brain.
6. **Quantization interaction.** The adapter trains in bf16, serves over Q4_K_M. Mitigation: the §6 post-quant check. Known-good pattern (standard practice), not a research risk.

---

## 9. Adapter composition (the future this playbook enables)

This LoRA is the **tool-calling base adapter**. Later, per-skill adapters stack on the O-LoRA pattern (orthogonal subspaces, frozen predecessors — learn-continual-learning.md §1.3). Periodic TIES/DARE merges, eval-gated. Because adapters are *files*, skills stay versionable, removable, and auditable — the whole point of parameter isolation. This playbook builds the first file; the composition discipline is already specified.

---

## 10. What could go wrong (top 5, pre-registered)

1. Kinetic-directly is already good enough → training buys <5pp → **don't train** (Step 1 exists for this).
2. Golden-set eval shows no gain → the gap was in *prompting*, not weights → fix the system prompt (free).
3. Safety spot set fails → don't ship, add safety mix, retrain (~$5, not a tragedy).
4. Hinglish examples are translationese → cut them from v1, ship the English adapter, add Hinglish in v2 with real seeds.
5. The 4B specialist wins tools but the router misroutes → the failure is in routing, not the adapter → fix the router.

Every failure mode has a named, cheap recovery. That's what makes this a playbook and not a gamble.

---

## 11. The execution checklist (ordered)

- [ ] Step 1: pull Kinetic adapter, 1-hour test on 20–30 JARVIS tool tasks → go/no-go on training
- [ ] Enumerate the ~40 tools with exact schemas (prerequisite for everything)
- [ ] Collect 50–100 real Hinglish request seeds (Owais)
- [ ] Build the private golden tool-task set (~100) + canary set (~200) + safety spot set (~30) — BEFORE generating training data
- [ ] Write the generator prompt; generate 500-sample pilot; human-review all 500
- [ ] Fix generator; generate full ~17.5k; mechanical schema validation; human-review 300-sample slice
- [ ] A0 audit: grep for secrets, real data, facts-that-change
- [ ] Rent GPU (A100 40GB or 4090); run baseline evals on the base model first
- [ ] Train (unsloth, §5 config); checkpoint on canary pass rate
- [ ] Run the full §6 harness; apply the ship rule
- [ ] Convert to GGUF; deploy on llama-server; post-quant check
- [ ] Sweep `--lora-scaled` on the golden set; lock the operating point
- [ ] Version the artifact (v1) with eval scores; document base revision + adapter as one unit

---

## Confidence & unknowns

- **[VC]** LoRA mechanics, the A0 rule, the adapter-per-skill pattern, eval-gating discipline, the "data costs more than GPU" economics.
- **[HC]** The r=64/all-linear reconstruction (clean arithmetic fit to 3.18%, but unconfirmed), the recommended mix ratios, the ship bars, Kinetic's existence and headline numbers.
- **[MC]** Kinetic's exact numbers (self-published eval, possible contamination — re-verify on our tasks per learn-continual-learning.md §3.3), GPU pricing at time of use, synthetic Hinglish quality, the $50–200 total budget.
- **[UK]** Whether the 4B specialist beats the 7B generalist on JARVIS's tools (that's the benchmark, not a premise); the exact Kinetic hyperparameters; long-term adapter composition behavior at 5+ adapters (no published tool-calling benchmark covers it).

## References

- Scout Study 66 (Kinetic-4B) — `~/workspace/jarvis-knowledge/scout-log.md`
- `~/workspace/jarvis-knowledge/learn-continual-learning.md` — adapters, O-LoRA, A0, contamination, eval recipe
- DECISION-PLAYBOOK.md A0 — adapters encode procedures, never facts
- `~/workspace/jarvis-knowledge/learn-brain-spec.md` §1 — tier routing, the 4B-specialist benchmark
- `~/workspace/jarvis-knowledge/learn-underspecification.md` §5 — golden-set seed for ask-vs-act examples
- `~/workspace/jarvis-knowledge/learn-evaluation-science.md` — Wilson CIs, pre-registered bars
- Dialpad REALM study (via scout) — SFT-with-LoRA strongest in-distribution 0.6B–32B; LoRA beat full fine-tuning at 4B
- Hu et al., 2021 — LoRA (arXiv:2106.09685)
- Wang et al., 2023 — O-LoRA; Yadav et al., 2023 — TIES; Yu et al., 2023 — DARE
- The reflex-adapter cautionary tale (2026-09-19): frozen base + good prompt beat the trained adapter on held-out data — via web search this cycle
- LocoTrainer-4B (contrast case): full SFT, 361k samples, 8×H100, ~25h — what LoRA avoids

## Honest completion (Rule 12)

- **Researched:** Kinetic recipe (scout log + 2 web searches), LoRA mechanics and cautionary cases (web), continual-learning constraints (knowledge base), cost arithmetic (derived, marked).
- **Validated:** 3.18%→r64 arithmetic checked by hand; throughput and cost math order-of-magnitude checked; A0 and eval-gating cross-checked against the knowledge base. Kinetic's exact hyperparameters and eval numbers NOT independently verified — marked [MC]/[UK] throughout.
- **Saved:** 1 file (`~/workspace/jarvis-knowledge/learn-lora-playbook.md`).
- **Tested / Measured:** nothing — playbook only, unexecuted by design.
- **Incomplete:** the Hugging Face repo path for the Kinetic adapter (search `consciousengines` org at execution time).
- **Blocked:** execution is a build decision — needs Owais's go-ahead; the 50–100 Hinglish seeds need Owais; the golden tool-task set needs building (build work, not learning).
