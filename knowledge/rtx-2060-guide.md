# RTX 2060 (6GB) AI Optimization Guide for JARVIS v2

**Hardware:** NVIDIA RTX 2060 6GB · Turing (sm_75) · 1920 CUDA cores · 240 Tensor Cores (2nd gen) · 336 GB/s bandwidth · 160W
**Date:** 2026-10-19 · **Honest framing:** 6GB is tight. This guide tells you exactly what fits, what doesn't, and how to squeeze every drop.

---

## 1. What fits in 6GB VRAM? (the numbers)

### The VRAM budget

| Bucket | Size |
|---|---|
| Total VRAM | 6,144 MB |
| Windows display + compositor + driver reserve | ~300–500 MB |
| **Usable for AI** | **~5,600–5,800 MB** |

**Rule: if weights + KV cache + compute buffer > 5.7GB, it will crash.** Leave margin — a browser tab can eat 200MB of VRAM silently.

### Model weights (GGUF file ≈ VRAM for weights)

| Model | Q4_K_M size | Q5_K_M | IQ4_XS | Q3_K_M | Verdict on 2060 |
|---|---|---|---|---|---|
| Qwen2.5 3B | ~1.9 GB | ~2.2 GB | ~1.7 GB | — | ✅ Easy fit, fast |
| Llama 3.2 3B | ~2.0 GB | ~2.3 GB | ~1.8 GB | — | ✅ Easy fit, fast |
| Qwen2.5 7B | ~4.7 GB | ~5.4 GB | ~4.1 GB | ~3.5 GB | ✅ **Sweet spot at Q4_K_M** |
| Llama 3.1 8B | ~4.9 GB | ~5.7 GB | ~4.3 GB | ~3.7 GB | ✅ Fits at Q4_K_M (tight at Q5) |
| Qwen3 8B | ~4.9 GB | ~5.7 GB | ~4.3 GB | — | ✅ Fits at Q4_K_M |
| **Qwen3.5 9B** | **~5.5 GB** | ~6.4 GB ✗ | ~4.8 GB | ~4.2 GB | ⚠️ **Borderline — see below** |
| Qwen3.5 4B | ~2.6 GB | ~3.0 GB | ~2.3 GB | — | ✅ Comfortable |

### KV cache (the silent killer)

KV cache grows with context length. Formula per token: `2 × layers × kv_heads × head_dim × bytes`

| Model | Per token (FP16) | 2K ctx | 4K ctx | 8K ctx (FP16) | 8K ctx (q8_0) |
|---|---|---|---|---|---|
| Llama 3.1 8B | ~128 KB | 256 MB | 512 MB | 1,024 MB | ~512 MB |
| Qwen2.5 7B | ~56 KB | 112 MB | 224 MB | 448 MB | ~224 MB |
| Qwen3 8B (est.) | ~144 KB | 288 MB | 576 MB | 1,152 MB | ~576 MB |

**Qwen2.5 7B has tiny KV cache** (only 4 KV heads) — this is a real advantage on 6GB. You can run 8K+ context comfortably.

### The full fit table (weights + 4K ctx KV q8_0 + ~300MB compute buffer)

| Setup | Total VRAM | Fits? | Headroom |
|---|---|---|---|
| Qwen2.5 7B Q4_K_M, 4K ctx | ~5.1 GB | ✅ Yes | ~600 MB |
| Qwen2.5 7B Q4_K_M, 8K ctx | ~5.2 GB | ✅ Yes | ~500 MB |
| Llama 3.1 8B Q4_K_M, 4K ctx | ~5.5 GB | ✅ Yes | ~200 MB — tight |
| Llama 3.1 8B Q4_K_M, 8K ctx | ~5.7 GB | ⚠️ Edge | ~0 MB — risky |
| Qwen3.5 9B Q4_K_M, 2K ctx | ~5.9 GB | ⚠️ Edge | ~0 MB — risky |
| Qwen3.5 9B IQ4_XS, 4K ctx | ~5.3 GB | ✅ Yes | ~400 MB |
| Qwen3.5 9B Q3_K_M, 4K ctx | ~4.7 GB | ✅ Yes | ~1 GB (quality cost) |
| Qwen3.5 4B Q4_K_M, 8K ctx | ~3.0 GB | ✅ Yes | ~2.7 GB — roomy |

### ⚠️ Honest verdict on Qwen3.5-9B

The 9B at Q4_K_M (~5.5GB weights) **technically loads** on a 2060 with short context (2K), but you have ~0MB headroom. One Chrome tab, one Windows notification animation, and you're OOM. **It's "works if you're careful," not "runs perfectly."**

**For the 2060, pick one:**
- **Safe pick:** Qwen2.5 7B Q4_K_M (best KV efficiency, 8K context fits)
- **Ambitious pick:** Qwen3.5 9B IQ4_XS (needs ik_llama.cpp or recent llama.cpp; ~4.8GB, fits with 4K ctx)
- **Quality-compromise pick:** Qwen3.5 9B Q3_K_M (fits easily, ~5-8% quality loss on reasoning)

---

## 2. Inference servers for 6GB — ranked

### 🥇 llama.cpp (built from source) — the pick

- **Why:** it's the engine under everything else; fresh builds have the latest kernels
- **Critical:** build with `-DGGML_CUDA_ARCHITECTURES=75` (Turing native — prebuilt binaries may PTX-JIT, costing performance)
- **Must-use flags for 2060:**
  ```
  --flash-attn                    # flash attention: less KV memory bandwidth
  --cache-type-k q8_0 --cache-type-v q8_0   # KV cache quantization: community-measured 2x speedup
  -ngl 99                         # all layers on GPU
  -c 4096                         # keep context at 4K (the KV budget rule)
  ```
- **Expected speed (7-8B Q4_K_M):** ~30–45 tok/s decode (estimated from 336 GB/s bandwidth math; measured Ollama numbers of 7-9 tok/s were old builds without these flags)
- **Expected speed (3-4B Q4_K_M):** ~60–80 tok/s decode (measured: 36-50 tok/s on old Ollama; modern build faster)

### 🥈 ik_llama.cpp — for IQ quants and prompt speed

- **Why:** IQ quantization (IQ4_XS is smaller than Q4_K_M at similar quality), 26x prompt-processing on certain architectures
- **Caveat:** fork last synced Aug 2024; CUDA backend supports Turing+; the 26x number was Qwen3.5-27B specific (hybrid attention), not a general 2x
- **Use when:** you want Qwen3.5-9B IQ4_XS on the 2060, or maximum prompt-processing speed
- **Verdict for 2060:** worth it if going the 9B-IQ4_XS route; otherwise mainline is fine

### 🥉 Ollama — for convenience, not speed

- **Why:** one-line install, model library, background service
- **Reality:** it's llama.cpp underneath; the "Ollama is slower" gap is defaults + version lag, not architecture
- **On 2060:** fine for getting started, but you give up `--cache-type-k`, flash-attn control, and IQ quants
- **Verdict:** use for prototyping, switch to llama.cpp server for production

### ❌ vLLM — skip on 6GB

- **Why not:** designed for multi-user throughput (PagedAttention, continuous batching); pre-allocates memory aggressively; overhead eats 1-2GB before the model loads
- On 6GB single-user, vLLM's strengths don't apply and its overhead kills you
- **Verdict:** wrong tool for this job

### Also worth knowing: ExLlamaV2 / TabbyAPI

- EXL2/EXL3 quants target fast single-user NVIDIA inference; often 10-20% faster than llama.cpp on GeForce cards
- More complex setup; worth evaluating if every tok/s matters
- **Verdict:** optional optimization, not day-one

---

## 3. Turing-specific: what matters for the 2060

| Feature | Turing (RTX 2060) | What it means |
|---|---|---|
| Architecture flag | **sm_75** | Build with `CUDA_ARCHITECTURES=75` |
| Tensor cores | 2nd gen (240) | FP16, INT8, INT4 — good |
| **BF16** | ❌ **Not supported** | Ampere+ only. Some newer models/kernels assume BF16 — use FP16 paths |
| FP16 compute | ~50-55 TFLOPS | Plenty for prefill |
| Memory bandwidth | 336 GB/s | **This is your decode speed ceiling** |
| Decode ceiling | ~336 ÷ model_GB tok/s | 7B Q4 (~4.7GB) → ~71 tok/s theoretical max |

### The key insight: decode is bandwidth-bound

Token generation speed ≈ (memory bandwidth) ÷ (model size). The 2060's 336 GB/s means:
- 7B Q4 (4.7GB): ceiling ~71 tok/s, realistic ~35-50 tok/s
- 3B Q4 (2.0GB): ceiling ~168 tok/s, realistic ~80-100 tok/s
- 9B Q4 (5.5GB): ceiling ~61 tok/s, realistic ~30-40 tok/s

**You cannot beat the bandwidth math.** Smaller model = faster, always. This is why the 4B tier is so attractive on 6GB.

### INT8 tensor cores

Turing has INT8 tensor cores (used by bitsandbytes, faster-whisper INT8). For GGUF inference the practical path is K-quants/I-quants, not raw INT8 — but faster-whisper's INT8 mode does use them for STT.

---

## 4. Splitting the load: CPU offload

llama.cpp's `-ngl` controls GPU layers. Fewer layers on GPU = less VRAM, slower inference.

| Offload | VRAM saved (8B) | Speed impact | When to use |
|---|---|---|---|
| All layers (`-ngl 99`) | 0 | Full speed | Default — always do this if it fits |
| ~75% layers | ~1.2 GB | ~20-30% slower | To squeeze 9B Q4_K_M with more context |
| ~50% layers | ~2.5 GB | ~50%+ slower | Last resort |

**The PCIe wall:** CPU-computed layers transfer over PCIe (~16 GB/s) vs GPU memory (336 GB/s). Every offloaded layer is ~20x slower for its computation. **Partial offload is a capacity tool, not a performance tool.**

**Honest rule:** if you need >25% CPU offload to fit, drop to a smaller model or lower quant instead. A fully-GPU 7B beats a half-offloaded 9B on both speed and simplicity.

---

## 5. The three-tier architecture for RTX 2060 6GB

| Tier | What | Where | Why |
|---|---|---|---|
| **Always-on** | BitNet 1-bit 2-3B (~100 tok/s CPU) or wake-word + tiny classifier | **CPU** (0 VRAM) | Sips power, instant, handles wake-ups + routing + quick answers |
| **Daily driver** | Qwen2.5 7B Q4_K_M (~4.7GB, 4-8K ctx) | **GPU** (~5.2GB) | The brain Owais talks to. Fits with headroom. |
| **Frontier** | Cloud (Gemini Flash, etc.) | **API** (0 VRAM) | Hard reasoning, complex code, research |

### The 2060's daily rhythm

```
Idle:        GPU at ~15W, BitNet on CPU listening for "hey jarvis"
Chat:        7B Q4_K_M on GPU, ~35-45 tok/s, ~120W
Voice:       Brain on GPU + Whisper-small on GPU (5.6GB total, tight)
             OR brain on GPU + Whisper on CPU (safer)
Heavy task:  Cloud brain via API, local GPU rests
```

### Why Qwen2.5 7B over Llama 3.1 8B for the 2060

Qwen2.5 7B's KV cache is **4x smaller** (4 KV heads vs 8). At 8K context: 224MB vs 512MB (q8_0). On a 6GB card, that 300MB difference is the margin between "comfortable" and "praying." Same quality tier, much more headroom.

---

## 6. Voice on the 2060 — what fits simultaneously

### Whisper VRAM (faster-whisper, measured)

| Model | INT8 VRAM | FP16 VRAM | For JARVIS |
|---|---|---|---|
| tiny | ~75 MB | ~150 MB | Wake-word verification |
| base | ~145 MB | ~290 MB | — |
| **small** | **~500 MB** | ~950 MB | **✅ The pick — 3.0% WER** |
| medium | ~1.5 GB | ~3 GB | Too big alongside brain |
| large-v3-turbo | ~1.6 GB | ~3.2 GB | Only if brain is on CPU |
| large-v3 | ~3 GB | ~6 GB | ❌ No |

### TTS engines

| Engine | VRAM | For JARVIS |
|---|---|---|
| Kokoro 82M | ~300 MB | ✅ Offline failsafe |
| Chatterbox Turbo 350M | ~1-1.5 GB | Expressiveness |
| Chatterbox Multilingual 500M | ~1-1.5 GB | Hindi/Hinglish |
| Piper | ~100 MB (CPU) | Ultra-light fallback |

### Simultaneous fit scenarios

| Scenario | GPU VRAM | Fits? |
|---|---|---|
| Brain 7B Q4 (5.2GB) + Whisper-small INT8 (0.5GB) | 5.7 GB | ⚠️ Tight — works if nothing else uses GPU |
| Brain 7B Q4 (5.2GB) + Whisper-small on **CPU** | 5.2 GB | ✅ Comfortable |
| Brain 7B Q4 + Whisper-small + Kokoro | 6.0 GB | ❌ Too tight |
| Brain 4B Q4 (3.0GB) + Whisper-small (0.5GB) + Kokoro (0.3GB) | 3.8 GB | ✅ Roomy |

### Recommended voice architecture for 2060

1. **Brain (7B Q4_K_M) stays resident on GPU** — it's the latency-critical path
2. **Whisper-small runs on CPU** (or loads to GPU on-demand and unloads — transcription is bursty, 2-5 seconds at a time)
3. **TTS: Kokoro on CPU** (82M runs realtime on CPU) or Chatterbox loaded on-demand
4. **Wake word: tiny model on CPU always** (~75MB, negligible)

**The principle:** GPU is for the brain. Everything bursty (STT, TTS) goes to CPU or loads/unloads. The 2060 can't hold the full voice stack + brain simultaneously — and it doesn't need to.

---

## 7. RTX 2060-specific tricks (community + technical)

### Build tricks
1. **Build llama.cpp from source with sm_75.** Prebuilt binaries include PTX fallback — the driver JIT-compiles at runtime, costing startup time and sometimes performance. Native SASS is always faster.
   ```
   cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=75
   ```

### Runtime flags (biggest wins)
2. **`--cache-type-k q8_0 --cache-type-v q8_0`** — quantizes KV cache. Community-measured **2x speedup** on Qwen models. No measurable quality loss. This is the single highest-ROI flag.
3. **`--flash-attn`** — flash attention. Less memory bandwidth per token, especially at longer contexts.
4. **`-c 4096` (not 8192)** — halving context roughly halves KV cache. On 6GB, 4K is the sweet spot for 7-8B.

### VRAM hygiene
5. **Close browsers before loading the model.** Chrome with tabs eats 200-500MB VRAM. This alone is the difference between OOM and stable on 6GB.
6. **Disable hardware acceleration in Discord/Spotify/etc.** Every Electron app with GPU acceleration reserves VRAM.
7. **If headless (no monitor on the 2060):** saves ~300MB. Not applicable for most desktops, but worth knowing.

### Model selection tricks
8. **IQ4_XS over Q4_K_M when tight.** ~10% smaller at similar quality. Needs ik_llama.cpp or recent mainline.
9. **Qwen2.5 7B over Llama 3.1 8B.** Same quality tier, 4x smaller KV cache. This is a 2060-specific pick.
10. **imatrix quants** (importance-matrix calibrated) beat standard quants at the same size. Look for `IQ4_XS` with imatrix.

### Power/thermal
11. **The 2060 is 160W.** At full inference load it gets hot and loud. For 24/7 always-on: use the CPU tier (BitNet) for idle, spin up GPU only for active conversation.
12. **nvidia-smi persistence mode** (`nvidia-smi -pm 1`) avoids driver reinit latency on first inference.

### What NOT to do
- ❌ Don't run vLLM (overhead kills 6GB)
- ❌ Don't use BF16 code paths (Turing doesn't have them — silent fallback to slow paths)
- ❌ Don't partially offload >25% (slower than just using a smaller model)
- ❌ Don't run the display + brain + whisper + TTS all on GPU simultaneously

---

## 8. The bottom line: your 2060's AI profile

| Workload | Setup | Speed | VRAM |
|---|---|---|---|
| **Always-on listening** | BitNet 1-bit 3B on CPU | ~100 tok/s | 0 GB |
| **Daily chat** | Qwen2.5 7B Q4_K_M, 4K ctx, q8_0 KV | ~35-45 tok/s | ~5.2 GB |
| **Fast chat** | Qwen3.5 4B Q4_K_M, 8K ctx | ~60-80 tok/s | ~3.0 GB |
| **Ambitious** | Qwen3.5 9B IQ4_XS, 4K ctx | ~30-40 tok/s | ~5.3 GB |
| **Voice STT** | Whisper-small INT8 (CPU or on-demand GPU) | faster than realtime | 0 / 0.5 GB |
| **Voice TTS** | Kokoro 82M on CPU | realtime | 0 GB |
| **Heavy lifting** | Cloud API | — | 0 GB |

**The 2060 is a capable AI card within its limits.** It won't run a 9B at Q4 with long context — but a well-tuned 7B at 40 tok/s with 8K context is a genuinely good daily driver. The three-tier architecture (CPU always-on → GPU daily → cloud frontier) means the 6GB ceiling is a design constraint, not a blocker.

**Confidence notes:** VRAM math is calculated from architecture specs (high confidence). Tok/s for modern llama.cpp on 2060 is estimated from bandwidth math + community reports (medium-high confidence — the 7-9 tok/s Ollama numbers were old builds; 30-45 tok/s is the bandwidth-realistic range with current flags). Whisper VRAM is measured (spheron.network table). Qwen3.5-9B Q4_K_M at ~5.5GB is estimated from quantization math — verify against the actual GGUF file size before committing.
