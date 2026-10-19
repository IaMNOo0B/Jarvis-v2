# RTX 2060 6GB — Internet-Sourced Measurements

*PHASE INFINITY. Date: 2026-10-19. LEARNING ONLY — no code, no installs, no execution.*
*Mission: replace the rtx-2060-guide's estimates with published numbers where they exist.*

**Label key:** [MEA] = published benchmark · [DER] = computed from published specs · [EST] = our old estimate from rtx-2060-guide.md · [NONE] = no published number found.

---

## Plain-words verdict: does our plan fit the card?

**Yes — with one correction and one caveat.**

The plan (Qwen2.5-7B Q4_K_M daily driver at 4K context, ~5.2GB) is confirmed by independent sources: Qwen2.5-7B Q4_K_M is listed at ~5.2GB all-in at 4K context, and 7B models on the 2060 measured ~80% VRAM. A modern native build (sm_75, flash-attn) on a 2060 SUPER did 62.5 tok/s on an 8B model — scaled to the plain 2060's bandwidth, that's ~47 tok/s, comfortably above our 35–45 estimate. So the daily-driver tier is **more solid than we estimated.**

**The correction:** our guide's "#1 optimization flag" (`--cache-type-k q8_0` = 2× speedup) is wrong as stated. Community testing reports **f16 KV cache is faster than q8_0 when it fits** — quantizing the cache adds per-token conversion work. q8_0 is a *memory* feature (use when f16 doesn't fit), not a speed feature. The real #1 flag is **flash-attn + native sm_75 build** (measured +19% generation, 3.3× prompt processing vs PTX-JIT build).

**The caveat:** Owais's card is from 2019 (6+ years). Published repaste reports show 5–10°C core drops on cards that needed it. If the card throttles (Turing drops clocks above ~83°C), sustained inference will be slower than these benchmarks. The benchmarking weekend must start with a temperature check.

---

## 1. LLM inference: tok/s on RTX 2060

### 1a. RTX 2060 SUPER, Ministral-8B (~5.1GB), all 37 layers on GPU — [MEA]
- **62.5 tok/s generation, ~348 tok/s prompt processing** (live server, real 200-token generations, model flags as shipped)
- Native sm_75 build, `GGML_CUDA_FA_ALL_QUANTS=ON`, q8_0 KV cache
- Wrong-arch build (PTX JIT) on the same card: 52.8 tok/s gen, 106 tok/s prompt → **native build = +19% generation, +228% prompt processing**
- Source: https://ianlpaterson.com/blog/llama-cpp-build-from-source-cuda-benchmark/ (published 2026-06-06, updated 2026-08-15) [VC]

### 1b. Scaled to plain RTX 2060 (6GB) — [DER]
- 2060 SUPER: 448 GB/s · plain 2060: 336 GB/s → 0.75×
- Expected Ministral-8B-class on plain 2060: **~47 tok/s generation, ~260 tok/s prompt processing**
- Same Turing architecture, same kernels — bandwidth-bound decode scales linearly [HC]

### 1c. RTX 2060, Ollama 0.5.11, 7B models — [MEA, but stale]
- Qwen2.5-7B: **8.98 tok/s** · Llama 3.1 8B: **7.39 tok/s** · Qwen2.5-3B: **36.02 tok/s** · Llama 3.2 3B: **50.41 tok/s**
- Source: https://www.databasemart.com/blog/ollama-gpu-benchmark-rtx2060 (~Feb 2025)
- **Do NOT use as targets.** Ollama 0.5.11 = old llama.cpp core, no flash-attn, no KV-quant, no native sm_75 guarantee. Treat as a **floor**, not a ceiling. [HC]

### 1d. Qwen3-4B / Qwen2.5-4B Q4_K_M on plain 2060 — [NONE]
- No published tok/s found for 4B models on the plain 2060 specifically.
- Nearest: Qwen2.5-3B at 36 tok/s (stale Ollama) — a 4B should land between 3B and 7B numbers.
- Our [EST] of 60–80 tok/s for 4B Q4_K_M remains unconfirmed — the benchmarking weekend measures it. [UK]

### 1e. Qwen3.5-9B IQ4_XS on 2060 — [NONE]
- No published numbers. Our [EST] (~30–40 tok/s, ~5.3GB) stands as estimate only. [UK]

---

## 2. VRAM usage: measured

### 2a. Qwen2.5-7B Q4_K_M ≈ 5.2GB all-in at 4K context — [MEA-ish]
- Table value "includes a 4096-token KV cache and runtime overhead estimates": Qwen 2.5 7B Q4_K_M = **~5.2 GB**
- Source: https://linuxprofessional.ie/article.php?slug=ollama-gpu-memory-troubleshooting-linux (2026)
- Note: Ollama-derived, includes its overhead — llama.cpp server overhead is similar magnitude [HC]

### 2b. 7B models on RTX 2060 hit ~80% VRAM — [MEA]
- "Models like Mistral 7B, DeepSeek 7B, and Llama 3.1 (8B) experienced... near 80% VRAM usage" on the 6GB card = **~4.8GB**
- Source: https://www.databasemart.com/blog/ollama-gpu-benchmark-rtx2060 [HC]

### 2c. Qwen2.5-VL-7B: 4.7GB file → 6.0GB at 8K ctx — [MEA]
- File: 4.7GB · at 8K context: **6.0GB** · at 32K: 7.4GB · KV = 56 KB/token
- Source: https://www.thinkfacility.com/run-locally/qwen/ (2026) [VC]
- Confirms the KV math in our guide: 56 KB/token × 4096 ≈ 229MB for Qwen2.5-7B [VC]

### 2d. Verdict vs our guide
- Guide [EST]: ~5.1GB for 7B Q4_K_M @4K → published: ~5.2GB. **Confirmed within 100MB.** Headroom: ~600–900MB after OS/driver. [HC]

---

## 3. Whisper STT: realtime factors

Convention used here: **×realtime** (higher = faster). 10× = 10 seconds of audio processed per 1 second of compute.

### 3a. faster-whisper small — [MEA]
| Hardware | Speed | VRAM | Source |
|---|---|---|---|
| RTX 3060 | **5× realtime** | ~2GB | https://deepwiki.com/tiandaren/video-quick-eval/9.2-gpu-acceleration |
| RTX 4090 laptop | **13.1× realtime** (0.84s for 11s clip, CUDA) | — | https://starwhisper.ai/whisper-benchmark.html (2026-07) |
| L40S (INT8) | **60× realtime** | ~500MB INT8 / ~950MB FP16 | https://www.spheron.network/blog/faster-whisper-gpu-cloud-production-deployment-guide/ (2026-09) |
| RX 7700 XT | **10–15× realtime** | — | https://gist.github.com/danielrosehill/278b1719598093767126e52105ae076e |
| CPU (reference) | **0.2× realtime** (5× slower than realtime) | — | deepwiki (same) |

### 3b. RTX 2060 small — [DER]
- 3060 ≈ 12.7 TFLOPS FP16 vs 2060 ≈ 6.5 TFLOPS → ~0.5× → **~2.5× realtime expected on the 2060** (FP16)
- INT8 on Turing tensor cores narrows the gap somewhat — **3–4× realtime plausible at INT8** [MC]
- A 5-second voice command transcribes in ~1.5–2s on GPU, ~25s on CPU. The "Whisper on CPU" fallback in our guide is **too slow for voice UX** — GPU (even shared) or on-demand load is required. [HC]

### 3c. VRAM confirmed
- small INT8: **~500MB** · FP16: **~950MB** (spheron table) — matches our guide exactly [VC]
- Co-residency: 5.2GB (brain) + 0.5GB (whisper INT8) = 5.7GB — **fits, but tight**; confirms the guide's "works if nothing else uses GPU" [HC]

---

## 4. TTS

### 4a. Kokoro-82M on CPU — [MEA]
- **RTF 0.469 (PyTorch) / 0.509 (ONNX)** on AMD EPYC 7763, 4 cores — RTF < 1.0 = faster than realtime, so **~2× realtime**
- 120 timed runs, 6 text lengths, warmup discarded — solid methodology
- Source: https://heyneo.com/blog/kokoro-tts-vs-supertonic-3-tts (2026)
- Ryzen 5 3600 (6C/12T Zen 2, higher clocks than the 4 allocated EPYC cores): **~2× realtime expected, possibly better** [HC]
- Our guide's "realtime on CPU" claim: **confirmed** [HC]

### 4b. Chatterbox — [MEA]
- **Turbo:** 4–6GB VRAM comfortable, **1.5GB with memory optimization**, ~0.5s first audio on RTX 4090
- Source: https://aiforautomation.io/news/2026-03-18-chatterbox-tts-open-source-voice-cloning-23k-stars (2026-03)
- **Full model:** 8GB VRAM recommended — https://adam.holter.com/chatterbox-tts-after-extensive-testing-the-open-source-voice-cloning-model-that''s-become-my-go-to/
- Desktop wrapper: ~5GB VRAM required — https://ampedhorizon.itch.io/chatterbox-tts-desktop
- **2060 verdict:** Turbo at 1.5GB optimized *cannot* co-reside with the 5.2GB brain (6.7GB > 6GB). **Load-on-demand only** (unload brain → load TTS → speak → unload), or CPU. Our guide's "on-demand" recommendation confirmed [HC]
- vLLM implementation note: S3Gen waveform generation = 84% of total time (RTX 3090) — the bottleneck is the vocoder, not the transformer — https://deepwiki.com/randombk/chatterbox-vllm/5-performance-and-benchmarking [MC]

---

## 5. Speculative decoding (EAGLE)

### Published (none on 2060-class) — [MEA elsewhere]
| Setup | Speedup | Acceptance | Source |
|---|---|---|---|
| General guidance, temp 0.6 (chat-like) | **1.7–2.3×** | 55–65% | https://localaimaster.com/blog/speculative-decoding-guide (2026) |
| Greedy decoding | **2.5–3.5×** | 75–85% | same |
| Qwen3-4B + EAGLE-3, vLLM, H20 | **1.66×** | 2.08 avg accept length | AngelSlim HF model card (vendor-reported) |
| Llama 3.1 8B + EAGLE-3, AWS trn2 | **1.57×** | 74.1% | https://awsdocs-neuron.readthedocs-hosted.com/ (measured) |
| EAGLE-3 paper (SGLang, batch 64) | **1.38×** throughput | — | arXiv:2503.01840 (authors' figure, upper-bound-ish) |

### RTX 2060 + EAGLE — [NONE]
- **No published EAGLE/EAGLE-3 numbers on any 2060-class card found.**
- Practical notes for the weekend: EAGLE-3 heads ship as PyTorch checkpoints (not GGUF) — must convert against target metadata; llama.cpp `--spec-type draft-eagle3`; heads exist for Llama 3.x and Qwen3 families (AngelSlim/Tengyunw) — **verify a head exists for our exact brain model before planning the test** [HC]
- Rule of thumb: acceptance > 0.7 needed for net speedup at batch-1 (https://blog.teliaz.com/2026/09/17/speculative-decoding-explained-how-eagle-3-makes-llms-2-3x-faster-without-changing-outputs/)
- Our guide's "2–3× via BitNet drafts" claim: **unmeasured, treat as [EST]** — EAGLE needs a trained head for the specific model; a BitNet CPU drafter is a different (unproven) setup [MC]

---

## 6. Thermals and aging (2019 card)

### Repaste results — [MEA]
- Successful repaste: **core temps down 5–10°C, hotspot down 8–12°C** under sustained load — https://tech-insider.org/gpu-thermal-paste-replacement-2026/ (2026)
- RTX 2060 specific: repaste dropped 78–82°C → ~73–76°C (**~5–6°C**), card had been throttling clocks — https://forums.tomshardware.com/threads/do-i-need-to-repaste-my-gpu.3753839/ (2022)

### Normal 2060 temperatures — [MEA]
- Budget-cooler 2060 (Ventus XS): **80–82°C under gaming load is normal**, not a defect — https://forum-en.msi.com/index.php?threads/high-temp.320479/ (2019)
- ≤85°C is safe for sustained load — https://forums.tomshardware.com/threads/rtx-2060-super-graphics-card-has-me-confused.3647423/

### What aging means for inference — [DER]
- Turing GPU Boost drops clocks above ~83°C. A 2019 card with dried paste can sit at 80–85°C under sustained full load → **5–15% clock reduction vs a fresh card** [MC]
- LLM inference is the worst thermal case: 100% sustained load for minutes (unlike gaming's bursty load)
- **Weekend protocol addition:** log GPU temp + clocks during every benchmark (nvidia-smi dmon). If temps >83°C with clock drops, the numbers are the *aged* card's numbers — note it, and consider repaste before treating results as final [HC]

---

## 7. Corrections to rtx-2060-guide.md

| # | Guide claim | Correction | Source |
|---|---|---|---|
| 1 | "`--cache-type-k q8_0` = 2× speedup, #1 flag" | **Wrong as stated.** Community testing: f16 KV is *faster* than q8_0 when it fits — quantization adds per-token conversion cost. q8_0 is a memory feature (use when f16 OOMs), not a speed feature. | https://openclawdc.com/blog/llama-cpp-moe-offload-flags-explained/ (2026) |
| 2 | "Real #1 flag" | **flash-attn + native sm_75 build**: measured +19% generation, +228% prompt processing vs PTX-JIT build on 2060 SUPER | https://ianlpaterson.com/blog/llama-cpp-build-from-source-cuda-benchmark/ |
| 3 | "7–9 tok/s Ollama numbers" (cited as old) | Confirmed stale — keep labeled as floor only | https://www.databasemart.com/blog/ollama-gpu-benchmark-rtx2060 |
| 4 | Whisper "faster than realtime" on 2060 | Refined: **~2.5–4× realtime on GPU**; CPU (0.2×) is unusable for voice — GPU or on-demand required | spheron + deepwiki tables |
| 5 | Chatterbox "1–1.5GB" | Refined: Turbo 1.5GB *with memory optimization*, 4–6GB comfortable; full model wants 8GB. On-demand only on 6GB. | aiforautomation.io (2026-03) |

---

## 8. Final table — does the v2 spec fit?

| Workload | Best available number | Source | Conf | v2 spec verdict |
|---|---|---|---|---|
| 7B Q4_K_M decode | **~47 tok/s** (scaled from 62.5 on 2060S) | ianlpaterson [MEA] + bandwidth [DER] | HC | ✅ Exceeds the 35–45 [EST] — daily driver solid |
| 7B Q4_K_M prompt processing | **~260 tok/s** (scaled from 348) | same | HC | ✅ 4K prompt prefills in ~15s worst case; typical turns much faster |
| 7B Q4_K_M VRAM @4K | **~5.2GB** | linuxprofessional [MEA] | HC | ✅ Fits; ~600–900MB headroom — matches spec's ≥400MB rule |
| 4B Q4_K_M decode | **60–80 tok/s** [EST] | none published | MC | ⚠️ Unconfirmed — weekend measures |
| 9B IQ4_XS | **30–40 tok/s, ~5.3GB** [EST] | none published | MC | ⚠️ Unconfirmed — weekend measures |
| Whisper-small INT8 | **~2.5–4× realtime, ~500MB** | spheron [MEA] + TFLOPS [DER] | HC | ✅ Fits alongside brain (5.7GB total, tight) |
| Kokoro-82M CPU | **~2× realtime** | heyneo [MEA] | HC | ✅ CPU realtime confirmed |
| Chatterbox Turbo | **1.5GB opt / 4–6GB comf** | aiforautomation [MEA] | HC | ⚠️ On-demand only — cannot co-reside with brain |
| EAGLE on 2060 | **No data** (1.6–2.3× elsewhere) | various [MEA] | MC | ⚠️ Weekend experiment; verify head exists for our model first |
| Aged-card penalty | **5–15% clocks if throttling** | tomshardware [MEA] + boost [DER] | MC | ⚠️ Weekend must log temps; repaste if >83°C sustained |

**Bottom line for the benchmark spec:** Tracks A–D can proceed with these as priors instead of pure estimates. The kill rule (>5.5GB eliminated) is validated by the 5.2GB measurement. The two [NONE] items (4B speed, 9B-IQ4_XS) and EAGLE remain genuine unknowns — the weekend earns its keep on those three.

*End. Status: internet-sourced priors complete; on-card measurement still required for [NONE]/[EST] items.*
