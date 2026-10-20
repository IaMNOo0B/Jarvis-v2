# MEGA-SCAN TEAM 12 — LOCAL LLM INFERENCE & OPTIMIZATION

*Mission: how projects squeeze small GPUs (RTX 2060 6GB class). Date: 2026-10-20.*
*Method: GitHub search + README/config/code-level reads via the GitHub connector and raw file fetches, plus setup-guide teardowns. Every mechanism below is traced to a file, flag, or doc line — not README marketing.*
*Confidence tags: [VC] verified from primary source · [HC] high confidence · [MC] medium · [SP] speculative.*

**Baseline (NOT re-studied — skip-if-learned from `learn-2060-measurements.md`):**
RTX 2060 plain: 336 GB/s. Decode is **bandwidth-bound**: tok/s ceiling ≈ bandwidth ÷ bytes-read-per-token.
Qwen2.5-7B Q4_K_M @4K ctx ≈ **5.2GB VRAM all-in, ~47 tok/s gen / ~260 tok/s prompt-processing** with a native sm_75 build + flash-attn (scaled from measured 62.5 tok/s on a 2060 SUPER).
KV for Qwen2.5-7B = **56 KB/token** → 4K ctx = ~229MB. f16 KV is *faster* than q8_0 when it fits; q8_0 is a memory feature, not a speed feature.
Old Ollama 0.5.11 numbers (7–9 tok/s on 7B) are a **floor**, not a ceiling — stale engine.

---

## THE BIG FIND — Speculative decoding is now a FREE Ollama feature (was server-flag-only)

### M1a. `DRAFT` + `draft_num_predict` in Ollama Modelfiles [VC]

Ollama attaches speculative decoding **to the model definition, not the server** (verified in Modelfile reference + community guide's correction note: *"`OLLAMA_SPECULATIVE_DECODE=1` does nothing — Ollama has no such env variable"*):

```dockerfile
# Modelfile — draft must be a LOCAL GGUF file; registry names are NOT accepted
FROM ./qwen2.5-7b-instruct-q4_k_m.gguf
DRAFT ./qwen2.5-0.5b-instruct-q4_k_m.gguf
PARAMETER draft_num_predict 4
```
`ollama create jarvis-spec -f Modelfile`

How it works (from code/docs): the draft model proposes K tokens (default 4 per step; 0 disables); the target verifies all K in **one parallel forward pass**; accepted tokens are emitted free, first rejected token falls back to target sampling. **Output distribution is unchanged** — same answers, faster.

Pairing rules (all three mandatory, verified):
1. **Same tokenizer/vocabulary** (check: `gguf-dump --no-tensors x.gguf | grep tokenizer.ggml.model` must match)
2. **Same family** (shared representations → high acceptance)
3. **Draft ≤ ~5% of target size** (0.5B vs 7B = 7%... borderline but the standard pairing in every guide: `qwen2.5-coder-7b + 0.5b` ships as llama.cpp's own `--fim-qwen-7b-spec` preset [VC from server README])

Acceptance by task type (vucense teardown, consistent with papers): **code completion & structured output (JSON/tool calls) = highest**; code generation high; summarisation mid; open chat lower; creative lowest. JARVIS's output is dominated by tool-call JSON and short factual answers — the *best-case* workload for speculation.

Real numbers: original papers report **2–3×**; a consumer setup (Qwen-2.5-Coder target + 0.5B draft) measured **24 → 58 tok/s (2.4×)** on code tasks. JARVIS-realistic estimate at 2060 with mixed chat/tool traffic: **1.5–2.2×** [MC — must be measured on-card].
Cost: draft model VRAM ~0.4GB (0.5B Q4) → 7B target 5.2GB + 0.4GB ≈ 5.6GB ⚠️ **over the 5.5GB kill-line with Whisper co-resident** — see the VRAM budget section for the mitigation (q8_0 KV or 4K→3K ctx).

### M1b. MTP heads — no draft model at all [VC]

Ollama ≥0.32.6/0.34 (Sept 2026): Qwen3.6/3.8 and Gemma 4 GGUFs ship **embedded MTP (multi-token prediction) tensors**; their registry Modelfiles carry `draft_num_predict 3` by default — speculation with **zero extra VRAM and zero config**. Reported: Gemma 4 up to **~90% faster** in coding-agent use; "free 2×" class claims across home-lab benchmarks.
⚠️ Trap: **`draft_num_predict` is inert without MTP tensors.** Old pulls predate the heads → silently old speed. **Re-pull after upgrading Ollama.** JARVIS's qwen2.5:7b has no MTP head — M1a (separate draft) is the path for the current brain; M1b becomes free the day the brain moves to a Qwen3.x/Gemma-4-class model.

### M1c. ngram self-speculation — no draft, no tensors, no VRAM [VC]

llama.cpp `--spec-type` list (from server README): `none, draft-simple, draft-eagle3, draft-mtp, draft-dflash, draft-dspark, ngram-simple, ngram-map-k, ngram-map-k4v, ngram-mod, ngram-cache`. The **ngram family drafts from the prompt's own text** — zero extra model, zero VRAM. Defaults: `n=12` lookup, `m=48` draft tokens, `min-hits=1`. Expected gain is smaller than a real draft model (tool-call boilerplate and repeated command patterns are the sweet spot — JARVIS's `TOOL:` lines repeat heavily), but the cost is literally nothing. Ollama does **not** expose spec-type (Modelfile DRAFT only); llama-server path does. Worth testing on-card: any positive delta is free.

### M1d. llama.cpp server speculative flags (for the non-Ollama path) [VC]

`-md/--spec-draft-model`, `--spec-draft-n-max 8` (default 3), `-ngld 99` (draft layers on GPU), `--spec-draft-type-k/q` KV types for the draft. `--spec-default` = sanctioned config. Eagle-3/DFlash/MTP/DSPark types all need matching draft weights — **none exist for Qwen2.5-7B**, so `draft-simple` is the only real option today.

---

## M2. Flash Attention + native sm_75 — the real #1 flag [VC]

From llama.cpp server README: `-fa, --flash-attn [on|off|auto]` (default auto) + env `LLAMA_ARG_FLASH_ATTN`.
From Ollama FAQ: FA is automatic where supported; **force with `OLLAMA_FLASH_ATTENTION=1`** at server start.
Measured on 2060-class (from prior): +19% generation, **+228% prompt processing** vs PTX-JIT build. ik_llama.cpp (May 2025, PR #370): "significant TG improvement on CUDA with Flash Attention for GQA models" — **Qwen2.5 is GQA (4 KV heads), so FA matters more for our exact brain than for dense models** [HC].
Interaction trap: **Ollama KV quantization requires FA enabled** — setting `OLLAMA_KV_CACHE_TYPE=q8_0` without FA may silently do nothing [MC].

## M3. KV cache — exact math, types, and sizing discipline [VC]

From llama.cpp server README: `-ctk/-ctv` types: `f32, f16, bf16, q8_0, q4_0, q4_1, iq4_nl, q5_0, q5_1` (default f16) — env `LLAMA_ARG_CACHE_TYPE_K/V`.
From Ollama FAQ: `OLLAMA_KV_CACHE_TYPE` — **global** (all models). f16 default; q8_0 = ~1/2 memory, "usually no noticeable quality impact (recommended if not using f16)"; q4_0 = ~1/4 memory, "small-medium quality loss, more noticeable at higher contexts". **GQA models (Qwen2.5!) see larger precision impact than low-GQA models** — the FAQ says it explicitly [VC].

The sizing math (Qwen2.5-7B, 28 layers, 4 KV heads, head-dim 128):
- f16: 2 bytes × 28 × 4 × 128 × 2 (K+V) = **56 KB/token** [VC — matches measured 6.0GB@8K minus file]
- q8_0: ~28 KB/token · q4_0: ~14 KB/token

**The 2060 discipline:** f16 @4K = 229MB → total 5.2GB ✅. If context must grow (8K = 458MB → 5.5GB+), prefer **q8_0 KV** before weight quantization upgrades — it halves cache for ~no speed cost, because cache is tiny next to 4.4GB weights. Do NOT drop weights from Q4_K_M to fix a *cache* problem.

## M4. Prompt caching / prefix reuse — the free turn-speedup [VC]

JARVIS sends the same giant system prompt every turn (~11.7K chars ≈ 3K tokens, ~15% of a 4K window). Prefix caching re-uses the KV of that prefix:

- llama.cpp server: `--cache-prompt` (default **enabled**), `cache_prompt: true` per-request (default true). Slots are matched by prompt similarity (`--slot-prompt-similarity 0.10`) — a repeat system prompt hits the cache → **prefill of the static prefix drops to ~0**.
- `-cram/--cache-ram N` (default **8192 MiB**): RAM-side prompt cache; `--cache-idle-slots` parks idle slots into it; `--slot-save-path` **persists KV to disk** (survives restarts).
- ⚠️ Nondeterminism caveat from the README: `cache_prompt` can make logits non-bit-identical (prompt-processing vs generation batch sizes differ) — fine for chat, note it for tests.
- **Ollama gap:** `/api/generate` `context` (the KV-continuation vector) is now **deprecated**; `/api/chat` has no prompt-cache API. Prompt caching is a **llama-server-only feature** — another reason the non-Ollama path exists.

Effect size on JARVIS: static prefix ≈ 3K tokens; at ~260 tok/s prompt-processing that's ~12s of prefill per turn on a cold prefix. With cache: **near-instant**. This is the biggest *latency* unlock after speculation — and it's free.

## M5. Grammar-constrained decoding — Ollama `format` is only the beginner version [VC]

What JARVIS uses today: Ollama `format` = JSON schema → structured outputs (confirmed in api.md §61-63; known unlock).
What the stack actually offers (llama.cpp server README):
- `-j/--json-schema SCHEMA` — CLI-level schema constraint
- API params: `grammar` (GBNF), `json_schema`, `response_format` (`json_object` | `json_schema`) on `/v1/chat/completions`
- grammars/ directory of samples; errors surface as "Failed to parse grammar"

Libraries (checked): **Outlines** (Apache-2.0) — JSON/Pydantic/multiple-choice/regex constraints, but Python deps (JARVIS is stdlib-only → ideas only); **xgrammar** (Microsoft) — the fast path used by SGLang; **mistral.rs v0.9.x**: integrated tool calling with **grammar enforcement + strict schema mode** [VC].

JARVIS payoff: tool-call emission (`TOOL: name {...}`) is exactly the "structured output with highest acceptance" workload. Constraints at the *decoder* level eliminate malformed tool calls — the #1 agentic failure mode on 7B models. Ollama `format` is the cheap version; full GBNF gives **hard guarantees** (choices/regex/CFG), not "usually valid JSON".

## M6. Ollama native tool calling [VC]

`/api/chat` + `/api/generate` accept `tools: [{type:"function", function:{name, description, parameters}}]`; responses return `tool_calls: [{function:{name, arguments}}]`. Caveat for JARVIS: brain currently speaks its own `TOOL:` text protocol, which works through ANY provider (Ollama, OpenRouter, Pollinations). Native `tools` only works through Ollama and needs model template support (Qwen2.5-7B supports it). Ranked as a later experiment — the text protocol is the portability bet; native tools are the reliability bet for the local path.

## M7. Context sizing discipline — the VRAM math nobody does [VC]

Ollama's **documented VRAM-based defaults**: <24GB VRAM → **4k**; 24–48 → 32k; ≥48 → 256k. So the 6GB card gets 4K *by design* [VC]. Raised via `OLLAMA_CONTEXT_LENGTH=64000 ollama serve` or Modelfile `PARAMETER num_ctx 4096`.
Concurrency multiplier (from FAQ): **RAM = OLLAMA_NUM_PARALLEL × OLLAMA_CONTEXT_LENGTH** — a 2K ctx with 4 parallel requests = 8K ctx worth of allocation. On 6GB: **keep NUM_PARALLEL=1 unless measured otherwise**; GUI+voice sharing one model is sequential queuing, not parallelism, on this card.
Rule for JARVIS: never raise `num_ctx` without recomputing 56 KB/token × ctx + 4.4GB weights against 5.5GB. Every 1K ctx ≈ +56MB.

## M8. Server economics — keep_alive and the unload/reload tax [VC]

From Ollama FAQ:
- `keep_alive` (per request) overrides `OLLAMA_KEEP_ALIVE` (global); **-1 = never unload**, **0 = unload now**. Default 5m.
- Unloading frees the whole 5.2GB; reloading re-pays model load + template + first-prefill (~10–30s on the 2060 [EST]).
- `OLLAMA_MAX_LOADED_MODELS` default **3×GPUs** (3 for this box — irrelevant with one model, but it means a second model slot *can* be forced loaded).
- `OLLAMA_MAX_QUEUE` default **512** (503 when exceeded).
- Concurrent model loads: each new model must **completely fit in VRAM** alongside what's loaded.

JARVIS policy implication: brain = `keep_alive: -1` (never pay the reload tax mid-session); STT/TTS are on-demand loads — sequence them so they never coexist with the brain (or shrink brain to keep co-residency math, see M3).

## M9. Heterogeneous inference — the MoE path (ktransformers) [VC]

**kvcache-ai/ktransformers** (19.6k★, Apache-2.0): the specialist answer to "big model, small GPU" for **Mixture-of-Experts**: **hot experts on GPU, cold experts on CPU** (NUMA-aware), CPU-side INT4/INT8 weights, 3-layer GPU→CPU→Disk **prefix cache** (June 2025). Their headline: DeepSeek-R1/V3-class models on single 24GB cards, **3–28× speedups** over naive offload; DeepSeek-V2 VRAM floor dropped 21G→11G.
Not directly applicable to JARVIS's dense 7B today (there is nothing to offload *to* when the whole thing fits) — but it is the documented playbook the day JARVIS wants a 30B-class MoE on the 2060 (e.g., Qwen3-30B-A3B: ~18GB Q4 → experts-on-CPU). Ideas-only import; Ollama can't do it.

## M10. Inference-time scaling at the proxy layer (optillm) [VC]

**algorithmicsuperintelligence/optillm** (4.3k★, Apache-2.0): OpenAI-compatible proxy that adds **inference-time compute** without touching the model server: majority voting (k=6), MCTS, CoT decoding, best-of-N, planner/split-and-merge, plus a `memory` plugin (unbounded context via retrieval) and `json` plugin (outlines-backed structured output).
JARVIS mapping: the v2 ReAct brain + self-critique module already do the *shape* of this. The concrete steal is **majority-vote tool selection**: for high-stakes tool calls, sample the same turn 3× and take the consensus — costs tokens, buys reliability. API-layer = provider-agnostic (works with keyed cloud + Ollama alike).

## M11. Quantization beyond Q4_K_M (ik_llama.cpp) [VC]

**ikawrakow/ik_llama.cpp**: the SOTA-quant fork where features land before mainline — MTP, DFlash, Trellis quants, MLA. Two hard facts from its README:
1. **Q4_K-family has no CUDA row-interleaved implementation** — never use `-rtr` (tensor repack) on hybrid CPU/GPU MoE runs with k-quants, or those tensors silently compute on CPU.
2. Its flash-attention for **GQA models on CUDA** (PR #370) — again, Qwen2.5 benefits.
**mistral.rs v0.9.5** also notes paged attention now default on supported Metal models, CUDA builds with FlashAttention V2/V3 [VC] — engine choice matters less than build flags.
Verdict for the 2060: Q4_K_M remains the right daily driver (IQ4_XS gains ~15% VRAM for quality loss — measured on other cards, not ours; bench-weekend item).

## M12. Batching — the quiet one [VC]

llama.cpp server: `-b/--batch-size` (logical max, default **2048**), continuous/dynamic batching **enabled by default** (`-cb`), n-ubatch physical caps. Ollama: no user-facing batching knob (server-internal). JARVIS is single-user sequential — batching is a non-issue today; it becomes one if the phone + GUI share a model, which is what NUM_PARALLEL is for (M7).

---

## THE 2060 VRAM BUDGET — with the draft model counted honestly

| Config | Weights | KV | Draft | Whisper | Total | Verdict |
|---|---|---|---|---|---|---|
| Today: 7B Q4_K_M, f16 KV, 4K | 4.7GB | 0.23GB | — | 0.5GB | **5.4GB** | ✅ tight but fits |
| + DRAFT spec (0.5B) | 4.7GB | 0.23GB | 0.40GB | 0.5GB | **5.8GB** | ❌ **over the kill-line** |
| + DRAFT, q8_0 KV | 4.7GB | 0.12GB | 0.40GB | 0.5GB | **5.7GB** | ❌ still over |
| + DRAFT, ctx 3K, q8_0 KV | 4.7GB | 0.09GB | 0.40GB | 0.5GB | **5.7GB** | ❌ |
| + DRAFT, Whisper load-on-demand | 4.7GB | 0.23GB | 0.40GB | (0.5 shared) | **5.35GB** | ✅ **the config to bench** |

Honest reading: speculation on a 6GB card is a **scheduling problem** (Whisper/TTS load-on-demand vs co-resident), not a free lunch. The M1b path (MTP model, zero draft VRAM) dissolves this entirely when the brain model changes.

## JARVIS-READY RECIPES

```dockerfile
# Modelfile — jarvis-spec (Ollama path, no code changes in v2)
FROM ./qwen2.5-7b-instruct-q4_k_m.gguf
DRAFT ./qwen2.5-0.5b-instruct-q4_k_m.gguf      # MUST be local path; same tokenizer (verify with gguf-dump)
PARAMETER draft_num_predict 4                  # 0 = disable; spec only fires when a draft/MTP exists
PARAMETER num_ctx 4096                          # the 2060-fitted context (see M7 rule)
```
```ini
# Environment (server start) — Ollama
OLLAMA_FLASH_ATTENTION=1
OLLAMA_KV_CACHE_TYPE=f16     # q8_0 only if the budget above forces it (M3 rule)
OLLAMA_CONTEXT_LENGTH=4096
OLLAMA_NUM_PARALLEL=1        # 6GB card: sequential by design (M7)
OLLAMA_KEEP_ALIVE=-1         # brain never pays the reload tax (M8)
```
```bash
# llama-server alternative (buys: prompt caching, ngram spec, GBNF grammars)
llama-server -m qwen2.5-7b-q4_k_m.gguf -c 4096 -fa on \
  --cache-prompt --cache-ram 2048 \
  --spec-type ngram-simple \
  -j '{"type":"object"}'     # or --grammar for full GBNF constraints
```

## REPO INVENTORY — 40 scanned, depth marked honestly

Deep reads (README + docs/configs/code-level extraction): llama.cpp, ollama, ktransformers, optillm, outlines, ik_llama.cpp, mistral.rs, koboldcpp = **8**
Guides/teardowns verified against primary docs: vucense speculative guide, enpremiumllc consumer-hardware study, runaihome Ollama-0.34 MTP analysis, tech-insider setup = **4**
Triaged (search metadata + description, value extracted into mechanism sections above): sglang, vllm (license verified Apache-2.0), TensorRT-LLM, DFlash, DeepSpec, SpecForge, ssd, lucidrains/speculative-decoding, nano-PEARL, LLMSpeculativeSampling, LLMLingua, xgrammar, GuruRefinery vram-budget-optimizer, courtelksoul profile-switcher, kotobuki09/rtx3060-llm, RD211/actors, llama_cpp_manager, BigMoeOnEdge, janas, MemVanta, frink, llamAmpere, pxa, quantprobe, llama-gguf-optimize, fituna, stablefix, KVBoost, llm-prefix-cache-core, what-happens-when-you-prompt = **28**
**Total: 40.** Licenses: llama.cpp **MIT**, ollama **MIT**, sglang **Apache-2.0**, ktransformers **Apache-2.0**, optillm **Apache-2.0**, vllm **Apache-2.0**, outlines **Apache-2.0** — every deep-read repo is permissive; only outlines needs deps (v2 = stdlib → ideas-only rule applies regardless).

## WEAKNESSES & ANTI-PATTERNS FOUND

1. **Fake env vars float around**: `OLLAMA_SPECULATIVE_DECODE` exists in blog posts but NOT in Ollama's source (`envconfig/config.go`) — a config that silently does nothing. Verify every env var against the official FAQ/envconfig, never a blog.
2. **`draft_num_predict` silently inert** without DRAFT or MTP tensors (M1b trap) — JARVIS must *prove* speculation is on (server log / tok/s delta), never assume.
3. **Cache nondeterminism** (M4): prompt caching changes logits slightly — golden-pair tests must tolerate it.
4. **KV-quant/GQA interaction** (M3): Qwen2.5 (high GQA) is one of the models the FAQ warns about for q4_0 KV — q4_0 KV is OFF the table for the daily driver.
5. **MoE-offload recipes don't transfer to dense models** (M9) — ktransformers-style wins require an MoE target.
6. **Two spam-pattern repos** (GuruRefinery/courtelksoul: same-day creation, SEO topic stuffing, CSS "language") — noted, not trusted, not counted as real systems.

## TOP 5 MECHANISMS (ranked for JARVIS v2)

1. **Speculative decoding via Modelfile DRAFT (+MTP awareness)** — 1.5–2.4× decode on the *exact* workload JARVIS runs (tool-call JSON, short factual turns). Zero code. [VC/HC]
2. **Prompt/prefix caching (llama-server --cache-prompt + --cache-ram)** — kills the ~12s cold-prefix prefill per turn; free; Ollama can't do it. [VC]
3. **Flash-attention forced ON + native sm_75 build** — already in v2 doctrine; this scan re-confirms it from BOTH engines' primary docs and ik_llama's GQA-specific gains. [VC]
4. **Full GBNF grammar constraints (llama-server) / Ollama format (today)** — decoder-level guarantee against malformed tool calls, the 7B's worst failure mode. [VC]
5. **Server economics: keep_alive=-1 + NUM_PARALLEL=1 + context discipline (56KB/token rule)** — no reload tax, no surprise OOM from parallel×ctx multiplication. [VC]

## TOP 3 STEALS FOR v2

1. **The `jarvis-spec` Modelfile** (DRAFT 0.5B + draft_num_predict 4 + num_ctx 4096) — one file, zero Python changes; paired with the load-on-demand Whisper scheduling from the budget table. Bench on-card: success = ≥1.4× tok/s on tool-call traffic with no answer-quality change (spec is distribution-preserving by construction — verify by golden-pair run).
2. **A llama-server fallback engine** behind the existing provider chain (not a rewrite): buys prompt caching (M4), ngram self-spec (M1c), and full grammars (M5) that Ollama structurally lacks. Same OpenAI-ish surface; v2's FallbackChain already abstracts providers.
3. **The context/KV budget as CODE**: a tiny pre-start check in v2 (stdlib Python) computing `weights + 56KB/token × ctx + draft 0.4GB + whisper 0.5GB ≤ 5.5GB` and refusing/warning before launch — the sizing rule every repo in this scan re-derives by hand, made a guard instead of folklore.

*End of Team 12 report. Standing gaps: all tok/s claims for speculation on the actual 2060 remain [MC] until the on-card bench runs (draft-pair acceptance on Hinglish chat is the unknown that decides M1a's real number).*
