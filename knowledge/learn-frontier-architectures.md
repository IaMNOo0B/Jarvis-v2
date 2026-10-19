# Frontier Model Architectures — OMEGA Research (§8 gaps)

*JARVIS OMEGA directive, Phase 2/3 frontier architectures. Researched October 2026. Learning only — no code touched.*

**Skip-if-learned applied:** transformers, attention variants (MHA/GQA/MLA), quantization, speculative decoding, test-time scaling, MoE basics (DeepSeek) — all in prior notes, referenced not re-taught. This file covers only the five genuine gaps.

---

## 1. State-Space Models (Mamba / Mamba-2)

### Mechanism
Classical state-space models (S4, 2021) model sequences as a linear dynamical system: a hidden state evolves via learned matrices A, B, C. **Mamba** (Gu & Dao, arXiv 2312.00752) adds *selectivity* — the A/B/C matrices become input-dependent, so the model learns what to keep and what to forget per token. **Mamba-2** (Dao & Gu, arXiv 2405.21060) restructures this as a structured state-space duality (SSD) that trains 2–8× faster on modern hardware. Result: **O(L) time, O(1) memory per generated token** — no KV cache that grows with context.

### Strongest evidence (for)
- Waleffe et al. (consumer-GPU benchmark): SSMs processed **220K tokens within 24GB** — ~3× longer than transformers at 8B scale. At 8B, pure Mamba matched or exceeded transformers on standard language-modeling tasks [HC, secondary source via 2026 survey].
- Constant per-token latency regardless of context length — ideal for streaming/real-time workloads.

### Weaknesses (the decisive part)
- **Retrieval breaks.** Yarden, Ben-Artzy & Schwartz (arXiv 2610.19709, Oct 2026): Mamba underperforms transformers on in-context retrieval *even when state capacity is not the binding constraint* (query-first setup). The selection gates are expressive enough, but the relevance signal emerges gradually with depth and "the gates begin to reflect it only several layers deeper" — retrieval-critical layers operate on a relevance signal that hasn't arrived yet. This is deeper than "fixed state = forgets things." [HC, primary source]
- Jelassi et al. (theoretical): transformers can copy strings of **exponential** length with 2 layers; SSMs are provably bounded by fixed state. Empirically, transformers needed **100× less training data** than Mamba for copying tasks, and pretrained SSMs lagged dramatically on context copying despite similar perplexity [MC, via survey citation].
- "Can Mamba Learn How to Learn" (arXiv 2402.04248): Mamba's test loss on vector retrieval tasks was orders of magnitude worse than transformers; it *could* learn sparse parity (a task transformers can't) — the architectures have genuinely different inductive biases, not a strict ranking.

### Deployment on RTX 2060 6GB
- llama.cpp **does** support Mamba and FalconMamba architectures (GGUF). Checkpoints exist: **FalconMamba 7B**, original Mamba 2.8B/7B, IBM Granite 4.0-h-350m (hybrid Mamba-2, Apache-2.0, GGUF).
- BUT: no Mamba-class checkpoint at 7B has demonstrated tool-calling competence (BFCL-style) anywhere near Qwen/Llama transformers. The ecosystem (fine-tunes, quants, agent benchmarks) is transformer-first.

### Verdict: **SKIP** (as the brain) — [HC]
An agent's core workload *is* retrieval: tool schemas from context, memory recall, quoting evidence, exact copying. Mamba's measured weakness lands exactly on JARVIS's critical path. Speed is irrelevant if the tool call is wrong. Keep on the watch list: if a 7–9B Mamba-class model ever posts competitive BFCL + agentic coding scores, re-evaluate.

### Unknowns
- Whether Mamba-2's SSD changes the retrieval picture at 7B+ scale (most retrieval studies used Mamba-1 or small models).
- Tool-calling accuracy of any Mamba GGUF — unmeasured, no public numbers.

---

## 2. Hybrid Architectures (Jamba, Hymba, Nemotron-H)

### Mechanism
Two flavors: **striped** (alternate attention and SSM layers, e.g., Jamba's 1:7 ratio) and **parallel-head** (attention and SSM heads fused within each layer, e.g., Hymba). The principle: attention layers handle precise retrieval; SSM layers handle cheap long-range summarization.

### Strongest evidence
- **Jamba** (AI21, Lenz et al., arXiv 2403.19887, Apache-2.0): 52B total / 12B active (MoE), 256K context, **4GB KV cache at 256K** vs ~32GB for Mixtral. Matches/exceeds Llama-2 70B and Mixtral 8x7B on reasoning benchmarks with 3× throughput. Needle-in-a-haystack robust across the full 256K window *with only 4 attention layers in the whole model* — the minimal-attention-restores-retrieval finding. Ablation: pure Mamba struggled with format adherence and in-context learning; "even minimal inclusion of attention layers can restore Transformer-like in-context learning." [HC, primary source]
- **Hymba** (NVIDIA): hybrid-head parallel design; 1.5B beats Llama-3.2-3B with **11.67× less cache, 3.49× faster** (vendor-reported — treat as optimistic) [MC].
- Waleffe et al.: hybrids with only **7–8% attention layers** closed the associative-recall gap [HC, secondary].
- Dao & Gu (2024) and Lenz et al. (2025) systematic reviews: "combining SSM and attention layers often outperforms using either one alone" — multiple independent teams, convergent [HC].

### Weaknesses
- No deployable 7B-class hybrid checkpoint exists. Jamba is 52B (won't fit 6GB). Hymba is 1.5B (too weak for an agent brain). IBM Granite 4.0-h-350m is 350M (utility model, no evals).
- Architectural complexity: two code paths to optimize, quantize, and debug in llama.cpp.

### Deployment on RTX 2060 6GB
- No usable artifact. Theoretical fit would be excellent (tiny KV cache), but the models don't exist at the right size/quality.

### Verdict: **WATCH** — [HC]
The hybrid pattern is the most likely long-term answer to the context-cost problem: it is *not* a compromise but "competitive in every practically important row." But JARVIS can't adopt what doesn't exist. Trigger for re-evaluation: an open 7–9B hybrid with published BFCL/agentic scores.

### Unknowns
- Optimal attention:SSM ratio for *tool-calling* specifically (all ablations used academic benchmarks).
- Whether hybrid quants preserve the retrieval layers' precision (the attention layers are the critical ones — quant damage there is what the inference-frontiers study warns about).

---

## 3. Sparse Computation (Mixture-of-Depth, Sparse Attention)

### Mechanism
Two axes: **sparse attention** (each token attends to a subset of the context — learned indexers like DeepSeek Sparse Attention, per-head patterns like MoA) and **mixture-of-depth** (tokens skip entire transformer blocks adaptively).

### Strongest evidence
- **DeepSeek Sparse Attention** (V3.2-Exp, Sept 2025): learned token-wise indexer, improved long-context training/inference efficiency with **no benchmark loss** vs dense attention [HC, vendor + MISA replication].
- **MoA** (arXiv 2406.14909): per-head sparse patterns, **3.9× effective context**, retrieval accuracy +1.5–7.1× over uniform sparse baseline, 6.6–8.2× decode throughput vs FlashAttention2, capability drop vs dense narrowed to <5% [HC, primary].
- **MISA** (arXiv 2605.07363): MoE-routed indexer heads, 8× fewer indexer heads, preserves NIAH heatmaps to 128K [MC, recent].
- Cautionary: MiniMax found **entirely replacing** softmax attention undermined multi-turn reasoning; Kimi Linear 48B shows linear methods can approach full attention only with careful gating [MC].

### Weaknesses
- Almost all of this is **training-time or datacenter-inference** technology: custom TileLang/CUDA kernels, H200 GPUs, trained-from-scratch models. llama.cpp has no DSA/MoA/MoD kernels; on a single RTX 2060 these techniques buy nothing today.
- Mixture-of-Depth is a training-FLOP saver, not an inference-latency saver for batch-1 interactive use.

### Verdict: **SKIP** (for local inference) — [HC]
Research-only for JARVIS's deployment target. The 2060's wins come from KV quantization, GQA head counts, and context discipline — not sparse attention kernels that don't exist in the local stack. Revisit if llama.cpp ever ships sparse-attention backends.

---

## 4. Retrieval-Augmented Architectures (RETRO-style vs RAG Pipeline)

### Mechanism
**RETRO** (DeepMind, Borgeaud et al., arXiv 2112.04426): the model is *trained* with a retrieval database — chunked cross-attention layers attend to retrieved passages during pre-training. A 7.5B RETRO matched much larger models on perplexity using a trillion-token database. **RAG pipeline** (what we have): ordinary model + external retriever + prompt stuffing, no architectural change.

### Strongest evidence
- RETRO's headline (25× smaller, comparable perplexity) is real but narrow: it's a *perplexity* result, and **RETRO was reported not reproducible** (Retro++ was built to fix this) [HC, Wikipedia + literature].
- RAG pipeline: industry analysis through 2026 finds **~75% of RAG failures are retrieval, not generation**; NVIDIA measured accuracy climbing **61% → 89%** from fixed to structure-aware chunking; pure vector search misses exact identifiers (hence hybrid BM25+dense) [HC, secondary].
- Even very large models benefit from retrieval augmentation — the need doesn't disappear with scale [HC].

### Weaknesses of built-in retrieval
- Requires **training from scratch** with a frozen trillion-token index — infeasible for JARVIS (no 24GB+ training rig, no such dataset).
- The index is frozen at train time: updating knowledge means retraining. A personal agent's memory must update in minutes.
- No open 7B-class RETRO checkpoint exists.

### Verdict: **ADOPT the RAG pipeline, SKIP built-in retrieval architectures** — [VC]
This one is decisive. The pipeline approach (learn-databases.md: hybrid search 91% recall, reranking, SQLite+Chroma) is modular, updatable, works with *any* brain model, and runs on the 2060 today. Built-in retrieval architectures trade away exactly the properties a personal agent needs (fast knowledge updates, model swappability) for perplexity gains that don't transfer to agentic tasks.

### Unknowns
- Whether future "retrieval-native" small models ship with updatable indexes (would change the verdict).

---

## 5. Diffusion Language Models (LLaDA and family)

### Mechanism
Instead of left-to-right next-token prediction, dLLMs start from a fully masked sequence and iteratively **denoise** it — predicting many positions in parallel each step, keeping high-confidence tokens, re-masking the rest. Bidirectional context at every step (like BERT, but generative).

### Strongest evidence (for)
- **LLaDA-8B** (Nie et al., arXiv 2502.09992): trained from scratch on 2.3T tokens, **matches LLaMA3-8B** on standard benchmarks, on par in in-context learning, **beats GPT-4o on reversal reasoning** (bidirectionality's natural win) [HC, primary].
- Speed is being fixed fast: **FlashDLM** (arXiv 2505.21467) — KV-cache approximation + AR-model-guided unmasking, **up to 34× end-to-end speedup** without accuracy loss; **CreditDecoding** (arXiv 2510.06133) — 5.48× over LLaDA-8B; **SchED** (arXiv 2512.02892) — 3.8–4× at 99.8–100% quality retention. The "diffusion is slow" objection is weakening [HC, primaries].
- **ReFusion** (arXiv 2512.13586): slot-level plan-and-infill recovers KV-cache reuse, 2.33× average speedup over strong ARMs while bridging the quality gap [MC, recent].

### Weaknesses (decisive for JARVIS)
- **No streaming.** Tokens are revealed by confidence, not by position — you cannot emit token 5 while token 3 is still masked. The voice loop and the chat UI both need incremental output; diffusion gives you nothing until denoising converges. TTFT is structurally bad.
- **Tool-calling is left-to-right-shaped.** Function calls are exact, ordered, prefix-dependent syntax (`{"name": "read_file", "arguments": {"path": ...`). Parallel arbitrary-order generation fights this; the GSM8K evidence is telling — dLLMs needed **256 steps for 256 tokens (fully sequential)** to reach competitive quality, at which point the parallelism advantage is zero (arXiv 2506.00413 measurement: Qwen2.5-7B AR at 38.6 tok/s vs dLLMs at 3–13 tok/s) [HC].
- **Ecosystem immaturity:** no BFCL/tool-calling evals published for dLLMs, no mature GGUF quant pipeline, no grammar-constrained generation support comparable to llama.cpp's GBNF for ARMs.
- Quality parity claims are benchmark averages; agentic multi-turn behavior is unmeasured.

### Deployment on RTX 2060 6GB
- In principle fits (8B class). In practice: no tested quant, no server integration, no tool-call harness.

### Verdict: **SKIP** (for the agent brain) — [HC]
Diffusion LMs are a genuine research direction and the speed work is impressive, but they are architecturally mismatched to JARVIS: no streaming (kills voice + chat UX), arbitrary-order generation (fights exact tool-call syntax), zero agentic evals. Revisit trigger: a dLLM with published BFCL scores + a streaming-compatible decoding scheme.

### Unknowns
- Whether ReFusion-style slot decoding can be made streamable (slots complete left-to-right-ish).
- dLLM instruction-following at 7B for Hinglish — completely unmeasured.

---

## Cross-cutting verdicts

| Architecture | Verdict | One-line reason |
|---|---|---|
| Pure SSM (Mamba) | **SKIP** | Retrieval breaks exactly where agents live |
| Hybrid SSM+attention | **WATCH** | Best long-term answer; no 7B artifact exists |
| Sparse attention / MoD | **SKIP** | Datacenter/training tech; nothing in llama.cpp |
| Built-in retrieval (RETRO) | **SKIP** | Unreproducible, untrainable, un-updatable |
| RAG pipeline | **ADOPT** | Modular, updatable, runs today |
| Diffusion LMs | **SKIP** | No streaming, fights tool-call syntax |

**The pattern:** every "post-transformer" architecture optimizes *throughput on long sequences* — which is not JARVIS's binding constraint. JARVIS's binding constraints are **retrieval precision** (tool schemas, memory, evidence), **streaming latency** (voice), and **exact syntax generation** (tool calls). The transformer — with GQA, KV quantization, and context discipline — remains the right substrate. Newer is not better; *fitted* is better.

## References (all verified, none fabricated)
- Gu & Dao, "Mamba: Linear-Time Sequence Modeling with Selective State Spaces," arXiv 2312.00752
- Dao & Gu, "Transformers are SSMs," arXiv 2405.21060
- Lenz et al. (AI21), "Jamba: A Hybrid Transformer-Mamba Language Model," arXiv 2403.19887
- Yarden, Ben-Artzy & Schwartz, "Beyond State Capacity: Why Retrieval Breaks in Mamba," arXiv 2610.19709
- "Can Mamba Learn How to Learn?", arXiv 2402.04248
- Nie et al., "Large Language Diffusion Models," arXiv 2502.09992
- Hu et al., "FlashDLM," arXiv 2505.21467
- Wang et al., "CreditDecoding," arXiv 2510.06133
- Mohamed et al., "SchED," arXiv 2512.02892
- Li et al., "ReFusion," arXiv 2512.13586
- Borgeaud et al. (DeepMind), "Improving Language Models by Retrieving from Trillions of Tokens" (RETRO), arXiv 2112.04426
- "Mixture of Attention (MoA)," arXiv 2406.14909
- "MISA," arXiv 2605.07363
- "MoSA," arXiv 2505.00315
- "Adaptive Parallel Decoding" (dLLM throughput measurements), arXiv 2506.00413
