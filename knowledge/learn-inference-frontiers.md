# Inference Frontiers — JARVIS Phase 2, Track 6 Gaps

*Learning mission notes. Scope: ONLY the gaps — KV-cache basics, quantization levels, VRAM budgeting, speculative decoding concept, prefix caching, and the RTX 2060 guide are already covered elsewhere and are not re-taught here.*

*Date: 2026-10-19. Confidence tags: [VC] >95%, [HC] 80–95%, [MC] 60–80%, [SP] 40–60%. Estimates are explicitly marked.*

---

## 1. Attention Variants: MHA vs GQA vs MQA vs MLA

### Mechanism (one paragraph each)

- **MHA (Multi-Head Attention):** every query head gets its own key and value head. Maximum expressiveness, maximum KV cache. Used by GPT-3, Llama 1, older models. Effectively extinct in new open models. [VC]
- **MQA (Multi-Query Attention):** all query heads share ONE key/value head. KV cache shrinks by ~H× (H = head count). Cost: measurable quality loss — every head is forced to look at the same keys. Used by PaLM, Falcon, StarCoder. [VC]
- **GQA (Grouped-Query Attention):** the compromise — query heads are divided into G groups, each group shares one K/V head. KV cache shrinks by H/G× with near-MHA quality. The industry default for every serious open model since 2023: Llama 2/3, Qwen2/2.5/3, Mistral, (reportedly) GPT-4. [VC]
- **MLA (Multi-head Latent Attention, DeepSeek-V2/V3/R1):** refuses the sharing trade-off entirely. Instead of sharing heads, it compresses K and V into a **low-rank latent vector** per token, caches only the latent, and reconstructs per-head K/V on demand during attention. Per token per layer at V2 scale: a 512-dim compressed latent + a 64-dim decoupled RoPE key = **576 cached elements vs 32,768 for MHA — 1.76% of the bytes** — while retaining per-head query diversity. The V2 paper's own ablations showed MLA *outperforming* MHA on hard benchmarks, not merely matching it (attribute: DeepSeek-V2 paper / local-ai-zone analysis). [HC on the mechanism; MC on the "outperforms MHA" claim — it's the authors' ablation, independent replication is thin]

### KV-cache math (the formula that matters)

```
KV bytes per token = 2 × n_layers × n_kv_heads × head_dim × bytes_per_value
```

| Model | Layers | Q heads | KV heads | Head dim | FP16 KV/token | q8 KV/token |
|---|---|---|---|---|---|---|
| Qwen2.5-7B | 28 | 28 | 4 | 128 | ~56 KB | ~28 KB |
| Qwen3-8B | 36 | 32 | 8 | 128 | ~144 KB | ~72 KB |
| Llama 3.1 8B | 32 | 32 | 8 | 128 | ~131 KB | ~66 KB |
| DeepSeek-V3 (MLA) | 60 | 128 | latent | 576 scalars | ~135 KB total* | ~67 KB* |

*\*MLA figures are whole-model per-token totals from published tables (FP16 138,240 B / FP8 69,120 B), not per the GQA formula. Included for scale comparison. [HC]*

### What this means for the 6GB VRAM budget [HC]

1. **Qwen2.5-7B's 4 KV heads are the reason it's the sweet spot.** At 4k context with q8 KV cache: 4096 × 28 KB ≈ **115 MB**. Qwen3-8B at the same context: 4096 × 72 KB ≈ **295 MB** — nearly 3× the cache for a similar-size model, purely because of the head count. GQA group size is a first-class model-selection criterion, not a footnote.
2. **Full 6GB budget check (Qwen2.5-7B Q4_K_M, 4k ctx):** weights ~4.7 GB + KV ~0.12 GB + compute buffers/overhead ~0.3 GB ≈ **~5.1 GB** — fits with headroom. Qwen3-8B Q4_K_M: weights ~5.0 GB + KV ~0.3 GB + overhead ≈ **~5.6 GB** — fits, but tight (matches the 2060 guide's "borderline" verdict; the cache math explains *why*).
3. **MLA is not yet actionable for JARVIS.** It requires training from scratch — there are no small MLA checkpoints practical for a 6GB card in the GGUF ecosystem as of this writing. The distill models (R1-Distill-Qwen) use GQA, not MLA. **Verdict: watch MLA, don't plan on it.** Revisit if a ≤9B MLA model ships with llama.cpp support. [MC — verify at build time]
4. **KV cache quantization (`--cache-type-k q8_0 --cache-type-v q8_0`) halves every number in the table above** with no measured quality loss (already in the 2060 guide; the attention math is *why* it matters — cache is the second-biggest VRAM line item after weights).

### Failure modes
- Picking a model on parameter count alone while ignoring KV-head count → a "7B" model that needs 2–3× the cache of another 7B at the same context. [HC]
- MQA-based models (older Falcon/StarCoder quants still floating around HF): cheap cache, but the quality hit is real on reasoning tasks. Don't be tempted by their small footprint. [HC]

### Key references
- DeepSeek-V2 paper (arXiv 2405.04434) — MLA definition and ablations.
- llama.cpp supports MLA (DeepSeek-V2/V3/R1 inference).
- KV formula confirmed against published per-model tables (dev.to MLA analysis; medium.com long-context piece for Qwen3-8B: 2×36×8×128×2 = 147,456 B/token).

### Unknowns
- Whether any sub-10B MLA model will ship with GGUF support in the next 12 months.
- Measured MLA decode speed in llama.cpp on Turing-class GPUs (no data found).

---

## 2. Quantization Calibration: imatrix, Agentic Accuracy, Weight-Only vs Activation

### How imatrix calibration actually works [HC]

`llama-imatrix` runs the **full-precision model** over a calibration corpus and records, per weight, how much activation energy flows through it — essentially a data-dependent importance score (the qudata writeup describes it as gradient-magnitude-based; the llama.cpp source integrates it as an importance-weighted term in the quantizer's loss function, `src/llama-quant.cpp`). When `llama-quantize --imatrix` then compresses, it **spends its limited bit budget on the weights that matter most** for that data distribution and spends fewer bits on the rest. Concretely:

- It matters most at **Q4_K_M and below**; at Q5_K_M and above the quality loss from skipping it is small. For the IQ (very-low-bit) quants it's close to mandatory. [HC — tech-insider GGUF guide, corroborated by llama.cpp docs]
- **One imatrix per model, reusable across all quant levels** — it's a one-time cost (a few minutes on a consumer GPU for an 8B model), not per-bit-depth. [VC]
- The calibration corpus is usually a few hundred KB of mixed prose/code/conversation. **This is the actionable gap for JARVIS:** the default corpora are generic web text. Importance is *data-dependent* — weights that matter for tool-call JSON, function schemas, and code get no special protection from a prose corpus. **Build a custom imatrix from agent-representative data** (tool schemas, JSON outputs, code, Hinglish chat, ReAct traces). One file, reused for every quant you produce. [MC — the mechanism is verified; the size of the agentic-accuracy gain from a custom corpus is unmeasured and must be tested]

### Weight-only vs activation quantization — where JARVIS actually sits [VC on taxonomy, HC on the recommendation]

- **llama.cpp/GGUF is weight-only quantization.** Weights are quantized offline; at inference time they're dequantized (to FP16/FP32 on GPU) for the matmul. Activations are *not* stored quantized. The K-quants improve on this with 256-weight super-blocks split into sub-groups with extra scale/min metadata — a hierarchical affine quantizer that buys fidelity at a fixed bit-width. (arXiv 2601.14277)
- **AWQ** (activation-*aware* weight quantization) is a different idea with a confusingly similar name: it uses activation statistics to identify the ~1% of salient weights and protects them (scaling before quant). It's the same *family* of insight as imatrix (importance-weighted bits), different implementation. AWQ/GPTQ/EXL2 are **GPU-only serving formats** — no CPU fallback, whole model must fit VRAM.
- **JARVIS's path is GGUF + llama.cpp** (CPU+GPU hybrid, Ollama-compatible). The practical levers are therefore: imatrix corpus choice, K-quants vs legacy quants, `--tensor-type` overrides (e.g. keep early layers at Q8 — see below), and KV-cache quantization. AWQ vs GGUF is not a decision JARVIS needs to make. [HC]

### The failure mode: quantized models that chat fine but can't call tools [HC]

This is the single most important finding in this section, and it's now **measured**, not theoretical:

1. **Perplexity does not predict it.** arXiv 2601.14277 (unified llama.cpp eval on Llama-3.1-8B): several 5-bit variants shared essentially identical perplexity (7.43) while showing **markedly different GSM8K and IFEval outcomes**. "Task sensitivity depends on how quantization error interacts with the computation pattern demanded by a benchmark rather than on distributional fit alone." [HC — peer-reviewed-style paper]
2. **Public benchmarks can't see it; agentic tasks can.** Five Qwen3.8-27B quants (Q4–Q8) scored within ±2 points on GSM8K/MMLU-Pro/IFEval but **diverged sharply on hidden-test agentic coding tasks — 1/12 vs 12/12** on hard tasks (anydayodelay digest, Oct 2026, citing Quesma's August 2026 study). [MC — community benchmark, methodology described but not peer-reviewed] *(Corrected Cycle 18: the Key References section called this the "Quesma Qwen3.6-27B study" — reconciled to Qwen3.8-27B, matching the §2 citation.)*
3. **Concrete tool-call numbers exist.** "Less is More" (arXiv 2411.15399): Llama-3.1-8B on BFCL — full precision **63.04%**, q4_0 **20.43%**, q4_1 34.35%, **q4_K_M 39.57%**, q8_0 44.35%. Note the ordering: q4_K_M beats q8_0 here is *not* the takeaway (different test conditions); the takeaway is **q4_0 destroys tool calling (63% → 20%) while Q4_K_M preserves ~2/3 of it**. Never ship q4_0/q4_1 for the tool brain. [HC]
4. **Model family beats size and quant level.** Independent BFCL measurement on a 4GB laptop GPU (dev.to, 3 seeds, bootstrap 95% CI): Qwen3-0.6B held schema-validity through Q4_K_M; Llama-3.2-1B's schema-validity was **fragile even at Q8_0** (emits `"10"` instead of `10` — stringified numbers that strict JSON validation rejects). [MC — single study, but the CIs are honest]
5. **What degrades first:** obscure facts go before common ones (Quesma IKP study: Q4_K_M lost ≤1.7pp, concentrated in rare tiers; the model still sounds fluent — "what it lost is the long tail"); precise structured output goes before fluent chat; multi-step reasoning chains go before single-step answers (errors compound). **Mechanism:** quantization noise is roughly uniform, but chat lives in the high-probability head of the distribution (robust) while tool calling lives in the tail — exact syntax, exact argument values, exact schema adherence (fragile). [HC — synthesis across the four sources above]

### Mitigations, ranked [HC]
1. **Q4_K_M minimum for the tool brain.** Not q4_0, not Q3. If the model only fits at Q3, take the smaller model at Q4_K_M — "the quantization cliff costs you more knowledge than the parameter count gives back" (Quesma's honest take). [HC]
2. **Custom imatrix** from agent-representative data (unmeasured upside, near-zero cost). [MC]
3. **Protect early layers:** the AmberLJC layer-placement study found early layers most quantization-sensitive — keeping layers 0–7 at Q8_0 with the rest at Q4_0 gave 1.9× compression at only +1.3% perplexity, and FFN layers benefited more from precision than attention layers. `--tensor-type` makes this a one-line build option. [MC — single-model study (24-layer model), direction likely general, magnitude uncertain]
4. **Measure on BFCL-style tasks, not MMLU** (see §3).

### Key references
- arXiv 2601.14277 — "Which Quantization Should I Use?" (llama.cpp unified eval; PPL ≠ task accuracy).
- arXiv 2411.15399 — "Less is More" (BFCL drop under quantization, Table I).
- llama.cpp tools: `llama-imatrix`, `llama-quantize --imatrix`, `--tensor-type`, `llama-perplexity --kl-divergence` (KL divergence + top-token-change rate are more sensitive than PPL alone — aicassindra llama.cpp deep dive).
- Quesma Qwen3.8-27B study (Aug 2026, via aifoss/medium writeups) — nonlinear knowledge degradation, 55 quants.

### Unknowns
- Measured gain of a custom agent-data imatrix on BFCL (nobody has published this; JARVIS should run it).
- Whether IQ4_XS (importance-matrix-aware, lower-bit) preserves tool calling better than Q4_K_M at similar size — plausible, unmeasured.

---

## 3. A Measurement Framework for Model Selection

### Principle [VC]
Decisions from measurement, not marketing. Every number below must be produced on **Owais's RTX 2060**, at **his context length (4k)**, with **his workload shape** — vendor tok/s and leaderboard scores are screening tools, not decisions.

### The four things to measure (and why each)

| # | Metric | Tool | Why it matters for JARVIS |
|---|---|---|---|
| 1 | **Tool-call accuracy** (BFCL-style: schema validity, tool selection, argument correctness) | Custom harness or BFCL eval | The tool brain's entire job. Public benchmarks understate quant damage (§2). Report **per-category** (simple/parallel/multi-turn), never just the average — multi-turn is where agents live and where scores drop 5–10 pts universally. |
| 2 | **Multi-turn coherence** (does it track state across 10+ turns) | Golden set from real usage | No public benchmark measures *your* agent's conversation shape. |
| 3 | **Latency at 4k**: TTFT + decode tok/s | `llama-bench -p 4096 -n <typical>` | tok/s at 512-token prompts is irrelevant to an agent that re-sends 4k every turn. Prefill and decode are different bottlenecks (§4) — measure both. |
| 4 | **Private agentic bench** (your repos, injected bugs, hidden tests) | Hand-built, ~50–100 tasks | The anydayodelay finding: public evals couldn't separate Q4–Q8; the private bench showed 1/12 vs 12/12. This is the only eval that measures *your* workload. |

### Which existing benchmarks measure this vs which mislead

**Useful (with caveats):**
- **BFCL** (Berkeley Function-Calling Leaderboard) — the standard for tool selection + argument correctness. Caveats: match the interface to production (native FC vs prompt-based are apples-to-oranges); pin the version; weight the multi-turn and irrelevance categories heaviest for JARVIS (qaskills.sh BFCL guide). [HC]
- **IFEval** — instruction following; the arXiv quant paper showed it *does* separate quants that PPL can't. Good smoke test. [HC]
- **GSM8K** — reasoning proxy; cheap to run. [HC]

**Misleading for this decision:**
- **MMLU / MMLU-Pro** — saturated, knowledge-heavy; quantization damage hides here (the ±2pt finding). Tells you about the base model, not the quant. [HC]
- **Perplexity alone** — the 2601.14277 finding kills it as a sole metric: identical PPL, different task scores. Use KL-divergence vs the BF16 reference instead (more sensitive). [HC]
- **Vendor tok/s** — measured at unknown context lengths, unknown backends, sometimes with spec decoding on. Reproduce with `llama-bench` or it didn't happen. [VC]
- **Single-seed runs** — the dev.to BFCL study used 3 seeds + bootstrap CIs and found CIs matter. One run is anecdote. [HC]

### The fair local shootout protocol (llama.cpp)
```
# 1. Pin: same llama.cpp commit, same sampling params, same -ngl, same -c 4096,
#    same --cache-type-k q8_0 --cache-type-v q8_0 for every candidate.
# 2. Speed (5 reps, at YOUR context length):
llama-bench -m candidate.gguf -p 4096 -n 256 -r 5 -ngl 99
#    Record pp (prefill) and tg (decode) separately.
# 3. TTFT: time-to-first-token via llama-server /timings or a scripted request.
# 4. Quality vs BF16 reference (if you have the disk):
llama-perplexity -m model-BF16.gguf -f eval.txt --kl-divergence-base ref.kld
llama-perplexity -m candidate.gguf --kl-divergence-base ref.kld --kl-divergence
# 5. Task: BFCL subset (native FC) + IFEval + your private golden set.
# 6. Decide: biggest model with tool-call accuracy within noise of its FP16,
#    at Q4_K_M or better, that fits 6GB with KV headroom.
```
(aicassindra llama.cpp deep dive for the KL-divergence methodology; llama-bench pp/tg semantics.)

### Decision rule (synthesis) [HC]
1. Shortlist by **KV-head count and architecture** (§1), not parameter count.
2. Benchmark the shortlist with the protocol above.
3. **If a model only fits at Q3 or below, drop a size and run Q4_K_M** — the cliff costs more than the parameters give back.
4. Re-run the shootout when: new model family drops, llama.cpp backend changes materially, or the workload shape changes (e.g. voice loop added).

### Unknowns
- Actual BFCL numbers for Qwen2.5-7B / Qwen3-4B/8B GGUF quants at Q4_K_M (must be measured; the published quant-vs-BFCL data is mostly Llama-3.1-8B and Qwen3.8-27B).
- Hinglish tool-call accuracy — no benchmark covers code-switched function calling; the private golden set must include it.

---

## 4. Prefill vs Decode: Why Long Prompts Hurt Differently

### The two machines [VC — well-established, multiple sources]

- **Prefill** (prompt processing): the whole prompt goes through in one parallel pass. Matrix×matrix work (GEMM), **compute-bound**. FLOPs scale with input length **squared** (full self-attention). This sets **TTFT** (time to first token).
- **Decode** (token generation): one token per forward pass, each step re-reads all weights + the full KV cache. Matrix×vector work, **memory-bandwidth-bound**. This sets tok/s. Ceiling: `tok/s ≤ memory_bandwidth / bytes_read_per_token`.

The memeburn two-machine test makes it visceral: DGX Spark vs Ryzen AI Max+ 395 on the same model — **5× apart on prefill, 13% apart on decode** — because their memory bandwidth is similar (273 vs 256 GB/s) while their compute differs enormously.

### RTX 2060 arithmetic (estimates — measure with llama-bench) [MC]

- Bandwidth: 336 GB/s. Qwen2.5-7B Q4_K_M ≈ 4.9 GB read per decode step → **theoretical decode ceiling ≈ 68 tok/s**; real-world lands ~35–45 tok/s (kernel efficiency, CPU-GPU sync, sampling overhead).
- Prefill is the opposite: bounded by the Turing TU104's ~52 TFLOPS (FP16, no tensor-core BF16 — the 2060 guide's note). 4k-token prefill is seconds, not milliseconds — **TTFT is the latency users feel**, and it's set by prefill, not decode.

### What this means for "15–20k effective history on 4k physical" [HC — follows from the above]

The LLMLingua-2 compression strategy wins **three times**, once per bottleneck:

1. **Prefill (quadratic win):** attention is O(n²). 15k² vs 4k² ≈ **14× fewer attention FLOPs** → TTFT collapses. This is the biggest win and the least obvious one — people think compression saves memory; it mostly saves *time*.
2. **KV cache (linear win):** 4k × 28 KB ≈ 115 MB instead of 15k × 28 KB ≈ 430 MB → VRAM headroom preserved for weights.
3. **Decode (linear win):** every decode step streams the KV cache; a 4× smaller cache means proportionally less memory traffic per token → faster generation for the *entire* response, not just the first token.

Costs: the compressor itself (LLMLingua-2-small, 0.22 GB, CPU) adds one prefill-side pass per turn — small against a 14× attention saving. Constraint (from the earlier study): **never compress tool schemas or the current user query** — compress history only.

### Two failure modes to avoid
- **Optimizing decode tok/s while ignoring TTFT.** An agent turn is: prefill 4k (seconds) → decode 200 tokens → prefill 4k again. If you only benchmark `tg128`, you miss the dominant cost. Always report the pair. [HC]
- **Growing context to "use" the VRAM headroom.** Every extra 1k tokens of physical context costs O(n²) prefill, linear cache, and slower decode *forever after*. The 4k cap is a performance decision, not just a memory one. [HC]

### Unknowns
- Measured pp4096 / tg256 on the actual 2060 for the shortlist models (the protocol in §3 produces these).
- Whether YaRN-style context extension (Qwen3-8B's 128k via YaRN) is ever worth it on 6GB — almost certainly not (cache math says no), but unmeasured.

---

## Cross-cutting summary

1. **Attention choice is a VRAM decision:** Qwen2.5-7B's 4 KV heads halve cache vs 8-head models at equal context. Count heads, not just parameters.
2. **Quantization damage is task-shaped, not uniform:** PPL can't see it; BFCL can; a private agentic bench sees it best. Q4_K_M floor for the tool brain; custom imatrix is free upside.
3. **Measure the pair:** prefill (TTFT, compute-bound, quadratic in context) and decode (tok/s, bandwidth-bound). The 4k-physical strategy wins on all three axes at once.
4. **The shootout protocol in §3 is the deliverable** — run it on the 2060 before locking the model choice. Nothing in this file replaces that measurement.
