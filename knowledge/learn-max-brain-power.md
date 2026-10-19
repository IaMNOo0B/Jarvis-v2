# MAXIMUM BRAIN POWER — the biggest FREE models, October 2026

*Research date: 2026-10-19. Purpose: find the largest, most capable AI models
JARVIS can use for FREE. The RTX 2060 (6GB) caps local models at ~7B, so
"maximum brain power" = free cloud models via gateways (OmniRoute) or
direct free tiers. No building — research only.*

**Headline: the biggest free brain is Kimi K3 — 2.8 TRILLION parameters,
free on NVIDIA NIM.** The free frontier has moved far past the 70B models
of 2025. Five models over 500B params are reachable free right now.

---

## 1. The 10 biggest FREE models (by parameters, verified Oct 2026)

| # | Model | Params (total / active) | Free host | Exact model ID | Free limits | Verified |
|---|-------|------------------------|-----------|----------------|-------------|----------|
| 1 | **Kimi K3** (Moonshot AI) | **~2.8T** / 104B | NVIDIA NIM | `moonshotai/kimi-k3` | Trial credits, ~40 RPM, no card | ✅ dev.to + madrobot.blog, Oct 2026 |
| 2 | **GLM-5.3** (Z.ai) | **753B** / ~40B | NVIDIA NIM | `z-ai/glm-5.3` | Trial credits, ~40 RPM, no card | ✅ dev.to, Oct 2026 |
| 3 | **DeepSeek R1-0528** | **671B** / 37B | NVIDIA NIM | `deepseek-ai/deepseek-r1-0528` | Trial credits, phone verify, no card | ✅ build.nvidia.com card + byteplus |
| 4 | **DeepSeek V4.1 Flash** | **552B** / 8B–16B | NVIDIA NIM | `deepseek-ai/deepseek-v4.1-flash` | Trial credits, ~40 RPM, no card | ✅ madrobot.blog, Oct 2026 |
| 5 | **Nemotron 3 Ultra** (NVIDIA) | **550B** / 55B | OpenRouter | `nvidia/nemotron-3-ultra-550b-a55b:free` | 20 RPM, **50 req/day** (1,000/day after $10 lifetime) | ✅ freellmapi.co + aipromix, Oct 2026 |
| 6 | **GLM-5.3 Flash** (Z.ai) | **320B** / 18B | NVIDIA NIM | `z-ai/glm-5.3-flash` | Trial credits, ~40 RPM, no card | ✅ dev.to, Oct 2026 |
| 7 | **Qwen3-235B-A22B** (Alibaba) | **235B** / 22B | ⚠️ free host UNCERTAIN (see notes) | `qwen-3-235b-a22b-instruct-2507` (Cerebras ID, retired) | — | ⚠️ see §5 |
| 8 | **GPT-OSS 120B** (OpenAI) | **116.8B** / 5.1B | Groq (best) / OpenRouter / Cloudflare / NIM | Groq: `openai/gpt-oss-120b` · OR: `openai/gpt-oss-120b:free` · CF: `@cf/openai/gpt-oss-120b` | Groq: 30 RPM, 1K/day, no card | ✅ 4+ sources, Oct 2026 |
| 9 | **Nemotron 3 Super** (NVIDIA) | **120B** / 12B | OpenRouter | `nvidia/nemotron-3-super-120b-a12b:free` | 20 RPM, 50 req/day | ✅ freellmapi.co, Oct 2026 |
| 10 | **Llama 3.3 70B** (Meta) | **70B** dense | Groq (best) / OpenRouter / Cloudflare | Groq: `llama-3.3-70b-versatile` · OR: `meta-llama/llama-3.3-70b-instruct:free` · CF: `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | Groq: 30 RPM, 1K/day, no card | ✅ 4+ sources, Oct 2026 |

**Capability wildcard (params undisclosed, frontier-class, free):**
Google's **Gemini 2.5 Pro / 3.x Flash** via Google AI Studio — permanent free
tier, no card, generous limits. Google doesn't publish parameter counts, but
it competes with the biggest models above on benchmarks. Model IDs:
`gemini-2.5-pro`, `gemini-2.5-flash` (AI Studio / `generativelanguage` API).

### Context windows (matters for a brain)
- Kimi K3: **1M** · GLM-5.3: **1M** · DeepSeek V4.1 Flash: **1M** ·
  Nemotron 3 Ultra: **1M** · Nemotron 3 Super: **1M** · GPT-OSS 120B: **131K**
  (Groq) · Llama 3.3 70B: **131K** (Groq) · Gemini 2.5 Pro: **1M**

### Key sources
- dev.to/klukyanov "Kimi K3, DeepSeek and GLM free from NVIDIA" (Oct 1, 2026)
- madrobot.blog "Free DeepSeek, Kimi and GLM API: NVIDIA Key Guide" (Sep 26, 2026)
- freellmapi.co "Free OpenRouter API — 12 free models" (Oct 17, 2026)
- dev.to/tariqnasser "Free LLM API Tiers in October 2026" (Oct 7, 2026)
- costbench.com "Best LLM API with a Free Tier in 2026" (verified Aug 6, 2026)
- freellm.net directory (505 free models, 30 providers)

---

## 2. Exact model ID strings (copy-paste ready)

**NVIDIA NIM** — endpoint `https://integrate.api.nvidia.com/v1`,
key prefix `nvapi-`, OpenAI-compatible:
- `moonshotai/kimi-k3` — 2.8T, the max
- `z-ai/glm-5.3` — 753B
- `deepseek-ai/deepseek-r1-0528` — 671B, best reasoning
- `deepseek-ai/deepseek-v4.1-flash` — 552B
- `z-ai/glm-5.3-flash` — 320B

**OpenRouter** — endpoint `https://openrouter.ai/api/v1`:
- `nvidia/nemotron-3-ultra-550b-a55b:free` — 550B, 1M ctx
- `nvidia/nemotron-3-super-120b-a12b:free` — 120B, 1M ctx
- `openai/gpt-oss-120b:free` — 117B
- `meta-llama/llama-3.3-70b-instruct:free` — 70B
- `openrouter/free` — auto-router (picks a working free model for you)

**Groq** — endpoint `https://api.groq.com/openai/v1`:
- `openai/gpt-oss-120b` — 117B
- `llama-3.3-70b-versatile` — 70B
- `openai/gpt-oss-20b` — 20B
- `qwen/qwen3.8-27b` — 27B

**Google AI Studio** — endpoint `https://generativelanguage.googleapis.com`:
- `gemini-2.5-pro` — frontier, params undisclosed
- `gemini-2.5-flash` / `gemini-3-flash` — fast + free

**Cloudflare Workers AI** — `https://api.cloudflare.com/client/v4/accounts/{id}/ai/run`:
- `@cf/openai/gpt-oss-120b`
- `@cf/meta/llama-3.3-70b-instruct-fp8-fast`

---

## 3. GitHub repos (stars + licenses, checked live 2026-10-19)

| Model | Repo | Stars | License |
|-------|------|-------|---------|
| DeepSeek R1 | `deepseek-ai/DeepSeek-R1` | **91,901** | MIT ✅ |
| DeepSeek V3 | `deepseek-ai/DeepSeek-V3` | **104,511** | MIT ✅ |
| Qwen3 | `QwenLM/Qwen3` | **27,677** | Apache 2.0 ✅ |
| GPT-OSS | `openai/gpt-oss` | **20,476** | Apache 2.0 ✅ |
| Llama | `meta-llama/llama-models` | **7,708** | Llama 4 Community (custom, not OSI) |
| Kimi K2 (K3 weights on HF, same org) | `MoonshotAI/Kimi-K2` | **11,112** | Modified MIT (revenue-tiered) |
| Nemotron 3 Ultra | *no official NVIDIA GitHub repo found* — weights on HuggingFace (`nvidia` org) | — | OpenMDW v1.1 (commercial OK) |
| GLM-5.3 | weights via Z.ai / NIM; community mirrors on GitHub | — | MIT with clause (>$10B-revenue resellers) |

Licenses cross-checked against model cards and reporting (the GitHub API
didn't return license fields on search; all of the above are confirmed in
multiple 2026 sources). Practical note: MIT/Apache-2.0 = no worries.
Llama Community and Kimi's modified-MIT have commercial-use conditions —
fine for JARVIS personal use.

---

## 4. TOP 5 by "brain power per hassle"
*reasoning quality × free-tier generosity × API reliability*

### 🥇 1. Gemini 2.5 Pro — Google AI Studio
- **Why #1:** frontier-class quality, PERMANENT free tier (not a trial),
  no credit card, Google-grade API reliability, 1M context.
- **Hassle:** needs a Google account; free-tier prompts may be used for
  product improvement (not in EEA/UK/CH).
- **Best for:** the everyday default brain — the one that just works.

### 🥈 2. GPT-OSS 120B — Groq
- **Why #2:** 117B params, the most *reliably* free big open model: 30
  req/min, 1K/day, no card, fastest inference on earth (~500 tok/s),
  Apache 2.0, tool calling built for agents.
- **Hassle:** 131K context (smaller than the 1M-context giants); not
  frontier-reasoning class.
- **Best for:** the fast escalation tier — hard questions get a big,
  fast brain in under a second.

### 🥉 3. Kimi K3 — NVIDIA NIM
- **Why #3:** the single biggest free brain on the planet (2.8T params,
  104B active), near-frontier benchmarks, 1M context, multimodal, one
  `nvapi-` key, no card.
- **Hassle:** trial terms (evaluation, not production); rate limits are
  fair-use and "will never be raised" per NVIDIA forums; big models cold-start;
  model IDs churn monthly.
- **Best for:** the "think really hard" tier — planning, architecture,
  problems the smaller brains fumble.

### 4. DeepSeek R1-0528 — NVIDIA NIM
- **Why #4:** 671B, still the best *open* reasoning model dollar-for-dollar
  (free here); chain-of-thought you can read and verify; MIT license.
- **Hassle:** same NIM trial limits as K3; slower than Groq-served models;
  reasoning models are verbose (token-hungry).
- **Best for:** math, debugging, multi-step logic — the reasoning specialist.

### 5. Nemotron 3 Ultra 550B — OpenRouter :free
- **Why #5:** 550B params + 1M context + reasoning effort control, free,
  tool-calling support, OpenMDW license.
- **Hassle:** **50 requests/day** is the tightest cap on this list
  (rises to 1,000/day after a one-time $10 credit purchase); free routes
  can be slow at peak; prompts may be logged.
- **Best for:** long-document reasoning within the daily budget — the
  1M-context specialist.

### The honest ranking logic
Raw size isn't the ranking — *usable* size is. Gemini wins because a
frontier brain with a permanent free tier and zero friction beats a 2.8T
model you can only poke at trial limits. GPT-OSS/Groq wins the
reliability crown: it's the only 100B+ model with 30 RPM free and
sub-second latency. Kimi K3 is the "break glass for maximum thought"
option — unmatched ceiling, metered access.

---

## 5. Corrections, caveats, and uncertainty

1. **Qwen3-235B is NOT free on Cerebras anymore.** A Sep 2026 field report
   confirms Cerebras removed `qwen-3-235b-a22b-instruct-2507` from its free
   tier in Aug 2026 (now `gpt-oss-120b` + `gemma-4-31b`). No other verified
   free host found → marked ⚠️ uncertain. (It's still Apache-2.0 open
   weights for anyone with the GPUs.)
2. **Cerebras "free tier" is disputed.** freellmapi.co (Oct 17, 2026) lists
   ~1M tokens/day free; costbench.com (Aug 2026) says Cerebras requires a
   verified payment method and its $5 grant is a *trial*, not a tier.
   Treat Cerebras as "free-ish, verify at signup" — NOT the clean choice.
3. **NVIDIA NIM is a trial, not a permanent tier.** Terms say evaluation
   only, not production; prompts may train models; rate limits are
   fair-use. Three of five originally-hyped models were already removed
   (dev.to, Oct 2026). Parameterize model IDs — they churn monthly.
4. **DeepSeek's own API has ZERO free models** (lmmarketcap, Oct 2026) —
   the free DeepSeek access is via NVIDIA NIM / OpenRouter, not DeepSeek.
5. **Kimi K3's "Modified MIT"** is revenue-tiered — fine for personal
   JARVIS use, read it before any commercial use.
6. **Llama 4 Maverick (400B)** has no verified free host — Groq and
   Cerebras both lack it (spheron.network, Sep 2026). Excluded from the
   top 10 for that reason.
7. **OpenRouter :free models rotate** without notice; `openrouter/free`
   (the auto-router) is the robust default if a specific ID vanishes.
8. Star counts were read live from GitHub on 2026-10-19; they move daily.

---

## 6. What this means for JARVIS

The brain ladder writes itself now:
- **Local (2060):** Qwen2.5-7B Q4 — private, instant, offline.
- **Fast cloud:** GPT-OSS 120B on Groq — 30 RPM free, sub-second.
- **Frontier cloud:** Gemini 2.5 Pro on AI Studio — permanent free tier.
- **Maximum thought:** Kimi K3 2.8T on NVIDIA NIM — the ceiling.
- **Reasoning specialist:** DeepSeek R1-0528 on NIM.
- **Long context:** Nemotron 3 Ultra 550B on OpenRouter :free (1M ctx).

One free NVIDIA key + one Groq key + one Google key + one OpenRouter key =
four keys, zero cards, and a brain that ranges from 7B local to 2.8T cloud.
The FallbackChain in `jarvis/brain.py` was built for exactly this ladder —
each provider is one duck-typed class away.
