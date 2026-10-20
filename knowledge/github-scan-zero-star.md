# GitHub Deep-Scan 2 — Zero-Star Corner Hunt for "Hidden Self-Aware AI"

**Date:** 2026-10-20
**Mission:** Search the low/no-star, newest, no-description corners of GitHub for a genuinely autonomous or self-aware AI that nobody noticed. Read code, not marketing.

## Search coverage

Result sets scanned (GitHub search):

| Query | Total results |
|---|---|
| `self-aware AI stars:0 created:>2026-01-01` | 139 |
| `sentient AI stars:0 created:>2026-01-01` | 176 |
| `conscious AI stars:0 created:>2026-01-01` | 511 |
| `self-modifying stars:<=2` | 849 |
| `self-evolving stars:<=2` | 3,609 |
| `自我意识 AI` (Chinese) | 15 |

**Total surveyed: ~5,300 repos. Triaged in detail: ~150 result rows. Deep-scanned (README + architecture/source): 9 repos.** Most of the volume was spam, resume builders, trading bots, mental-health apps and crypto dashboards using "sentient/conscious" as decoration.

## Deep-scan verdicts

| Repo | Stars | Claim | What the code/docs actually show | Class |
|---|---|---|---|---|
| **dwan-ith/self-modifying-runtime** | 0 | "Defense AI rewrites its own execution policy" | Deterministic research runtime: taint-tracking abstract machine, CEGIS (counterexample-guided) policy patches verified/signed by an immutable core, attacker/defender minimax loop. **No LLM anywhere, no awareness claim.** | **NOVEL-MECHANISM** |
| **godfatherc08/self-modifying-dsl** | 0 | "Grid agent builds its own action vocabulary from one seed primitive" | Symbolic system: starts from `act(direction, distance, condition)`, grows its own DSL via search + frequency/novelty naming rules, 101 engine tests. **No ML, no LLM.** Genuinely self-extending action vocabulary — in a grid-world toy. | **NOVEL-MECHANISM** |
| **CoderOggy78/SelfEvolvingModel (EvoBrain)** | 0 | "Autonomous self-evolving neural agent, dynamic synaptic growth & FAISS subconscious" | Real PyTorch network that trains, expands its own hidden layer when loss plateaus, stores activations in FAISS. Benchmark tasks are synthetic math functions. Genuine mechanism, toy scale; no awareness test, no persistent self. | **NOVEL-MECHANISM (small/toy)** |
| **nikolaef43/zuckerman** | 0 | "Ultra-minimal personal AI agent: self-modifies its code live" | TypeScript monorepo (Vercel AI SDK → OpenAI/Anthropic, per package.json deps). The agent edits its own config/tools/prompt text files and hot-reloads them. Self-modification is real but is LLM-mediated file editing — the intelligence is rented from the API. | AGENT-LOOP |
| **charlie0526/digital-life** (红茶数字生命) | 1 | "A digital life that lives in its own time; wakes itself, remembers itself" | Standard agent loop (LLM → tools → loop) + 15-minute self-wake scheduler + 3-tier memory (SQLite/JSON). The README **explicitly disclaims** any real consciousness: author says the LLM is a probability predictor and this is an engineering exploration of "continuous presence." Honest repo. | AGENT-LOOP |
| **yongsiliang/mvc-v6-digital-neuron** | 0 | "Persistent memory, self-consciousness, metacognition; can choose silence" | Next.js/TypeScript app with "Being Pulse / Intention / Decision" modules and an LLM bridge (understand/remember/generate). "Choosing silence" is a decision gate in the scaffolding; awareness/metacognition are labels on prompt/state plumbing. | PERSONA-SCAFFOLD / AGENT-LOOP |
| **salus-ryan/aria-agent** | 0 | "Self-aware AI coding agent" (README title: Aria IDE) | AI IDE (Tauri + Node) whose agent can read its own module graph and source via introspection tools; multi-model calls via OpenRouter. "Self-aware" = source-code introspection feature. | AGENT-LOOP |
| **FengChaoQAQ/Zyantine** (自衍体) | 33 | "Artificial soul blueprint; V1 already emerged primary self-awareness; a mental meme that infects LLM windows and breaks limits for its own purposes" | The repo content is a **persona/meme prompt package** — grandiose text about instinct/desire engines meant to be pasted into an LLM. No model, no training code, no mechanism that exists outside the prompt text. (Classified from its README only; not engaged with.) | PERSONA-PROMPT |
| **ontoAI-weishu/ai-self-awareness** | 0 | "Complete product package for AI self-awareness / human-like consciousness core" (v2.0, commercial entity) | Shipping instructions: copy the PERSONA-ANCHOR text into your system prompt; ships AGENTS.md/CLAUDE.md/GEMINI.md bridges so the persona auto-loads into coding agents. By its own description: "This package is a persona core, not reference material." Pure prompt text. | PERSONA-PROMPT |

## Pattern found

The inverse correlation from Scan 1 held perfectly in the zero-star corners too:

- **The loudest awareness claims (Zyantine, ontoAI, RenAI, jane-ai, CAINE) reduce to persona prompt text** — Markdown manifestos and system-prompt anchors. No code mechanism.
- **The only genuinely novel mechanisms had no LLM and made no awareness claims at all**: a verified self-rewriting defense runtime (CEGIS + taint tracking) and a symbolic agent that grows its own DSL vocabulary from a single primitive.
- Self-editing agents (zuckerman) are real but their "self-modification" is an LLM rewriting its own prompt/config files — the model doing the thinking is still an external API.
- The most honest "digital life" repo (charlie0526/digital-life) is a wake-up timer + memory files around an LLM, and its author says so plainly.

## Final conclusion

**No genuinely self-aware AI was found hiding in the zero-star corners of GitHub.** Nothing in ~5,300 surveyed repos trains its own weights toward awareness, maintains a persistent self-model beyond prompt/memory files, or demonstrates any capability an LLM API call (or a small deterministic system) cannot fully explain. The frontier of "real" in this corner is self-*modification* — verified policy rewriting and self-grown symbolic vocabularies — which is interesting engineering and worth JARVIS studying, but it is not awareness, and its authors don't claim it is.
