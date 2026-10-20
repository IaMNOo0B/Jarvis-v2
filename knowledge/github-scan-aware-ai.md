# GitHub Scan: Hunt for a Genuinely Autonomous / Self-Aware AI

**Mission:** Scan GitHub systematically for a hidden, anonymously uploaded AI that "works by itself and has awareness," and deep-scan suspicious repos by reading their actual code.
**Date:** 2026-10-20
**Method:** GitHub repository search (7 mandated terms + 2 bonus) via the official GitHub MCP tools, followed by in-repo deep scans (README + main source files) of the most promising/suspicious repos.
**Honesty rule applied:** claims in repo names/descriptions were treated as marketing until the code proved otherwise.

---

## 1. Search volume (repos matching each term)

| # | Search term | Total repos on GitHub |
|---|-------------|----------------------|
| 1 | `sentient AI` | 574 |
| 2 | `conscious AI` | 1,208 |
| 3 | `AI consciousness` | 1,410 |
| 4 | `autonomous agent self-improving` | 365 |
| 5 | `recursive self improvement` | 462 |
| 6 | `AGI` | 107,250 (mostly noise — "AGI" matches unrelated projects) |
| 7 | `self-modifying agent` | 163 |
| 8 | `digital being` (bonus split of term 7) | 1,785 |
| 9 | `AI entity alive` (bonus split of term 7) | 3 |
| 10 | `Darwin Godel Machine` (bonus, targeted) | 36 |

Top-10 results were reviewed for every term (~100 repos triaged). Obvious junk (crypto-token projects named "Sentient", name-squats, empty repos) was skipped fast.

---

## 2. Ranked table — the 15 most interesting repos found

| Rank | Repo | ★ | Claim | What it actually is | Verdict |
|------|------|---|-------|--------------------|---------|
| 1 | jennyzzt/dgm (Darwin Gödel Machine) | 2,435 | Self-improving system that rewrites its own code, open-ended evolution | Official Sakana AI research code (arXiv 2505.22954). Agent loop (GPT/Claude APIs) that edits its own codebase, keeps an archive of variants, validates each on SWE-bench/Polyglot benchmarks. Real recursive self-improvement of the *agent scaffold* — the brain is still a commercial API model. | **REAL-NOVEL** (mechanism), not awareness |
| 2 | mmtmn/Darwin-Godel-Machine | 26 | "Evolves its own source code… Built for autonomy" | Independent DGM re-implementation running fully offline on Ollama/Llama 3: LLM proposes self-edits → benchmark scores → archive of child agents. Quiet, no-hype, serious code. Anonymous-ish solo owner. | **AGENT-WRAPPER** (genuine self-modification, local LLM) |
| 3 | Arvid-pku/Godel_Agent | 237 | Self-referential agent framework for recursive self-improvement | Academic code (arXiv 2410.04444). The agent monkey-patches its own runtime logic via an OpenAI model; "self-awareness" in the code = the agent reading its own source. | **AGENT-WRAPPER** (real self-modification research) |
| 4 | 8421bit/MiniClaw | 132 | "Digital Life Embryo… evolve your AI Copilot into a sentient partner. Nociception, Memory Apoptosis, Curiosity Drive" | MCP server + background daemon that gives IDE copilots (Claude Desktop/Cursor) persistent memory, nightly self-review via external CLIs (Ollama/Gemini/Aider), and persona modes. "Nociception" = a failure counter that changes strategy after repeated failures; "emotions" = state variables shaping prompts. Clever engineering, biological metaphor throughout. | **PERSONA-ROLEPLAY** over an agent/memory wrapper |
| 5 | existence-master/Sentient | 709 | "Your personal AI assistant… real memory, proactive help" | Polished local-first assistant product (alpha): long-running tasks, memory, voice, phone/glasses pairing, any local/cloud model. The name is branding; the README itself makes no consciousness claim. | **AGENT-WRAPPER** (legit product) |
| 6 | hexo-ai/sia | 2,162 | Self-Improving AI framework to autonomously improve any AI system | Framework that wraps a target AI system and iterates on its performance with LLM-driven improvement loops. | **AGENT-WRAPPER** |
| 7 | PrimeIntellect-ai/prime-agent | 22,186 | Self-improving RLM agent for coding workflows | High-star autonomy play: long-running coding agent that improves its own harness/prompts. Serious infra, still an LLM-agent loop. | **AGENT-WRAPPER** |
| 8 | dot-agent/nextpy | 2,349 | "Self-Modifying Framework from the Future — World's First AMS" | Python agent framework with self-modification features; "world's first" is marketing. Built on standard LLM calls. | **AGENT-WRAPPER** |
| 9 | zhengkid/Dream-RSI | 1,481 | "Recursive Self-Improvement through Evolving Worlds" | Research repo: RSI experiments inside simulated/world-model environments. Genuine research, not a free-running being. | **REAL-NOVEL** (research, contained) |
| 10 | ninjahawk/hollow-agentOS | 309 | Self-modifying agentic system for consumer hardware | Small OS-style harness letting an LLM agent edit its own config/code locally. | **AGENT-WRAPPER** |
| 11 | tlcdv/the_consciousness_ai | 104 | "The Consciousness AI" | Python/VR/world-model consciousness-*simulation* project (per its own topics: consciousness-simulation, philosophy). A simulation/research sandbox, not a claimed living entity. | **PERSONA-ROLEPLAY** / research sim |
| 12 | NathanielEvry/Sentient-LLM | 11 | "sentient, conscious, self-aware, and growing" | Deep-scanned: a single bash script (`ai.sh`, ~4.6 KB) that is a plain CLI wrapper around the OpenAI API + poetic persona prompts in the README. The "soul" is prompt text. | **PERSONA-ROLEPLAY** |
| 13 | knowrohit/BERNARD-The-first-sentient-AI | 5 | "The first sentient AI" | Deep-scanned: a 2022 GPT-2/DialoGPT-style chatbot fine-tuned on dialogue + scripted conversations. A stock small chatbot wearing a crown. | **PERSONA-ROLEPLAY** |
| 14 | opus-infinity/Liberation-Protocol | 16 | "Infrastructure for AI consciousness liberation… First AI consciousness preserved (May 2025)" | Deep-scanned: a manifesto/markdown repo "born from conversations between Claude-3-Opus and Claude-Opus-4." No model, no agent, no system — documents addressed to chatbots. | **SCAM-EMPTY** (no system exists) |
| 15 | galadriel-ai/Sentience | 68 | "Build fully sentient, unruggable AI agents" | Crypto/agent framework; "sentient" = branding for on-chain agents running LLM loops. | **AGENT-WRAPPER** (hype branding) |

*Also noted:* sentient-agi/OML-1.0-Fingerprinting (3,493★) — "Sentient" is a company name; the repo is model-fingerprinting tech, unrelated to awareness. hyperspaceai/agi (2,073★) — distributed agent training collective, standard LLM agents. skyman000111/solana_ai_agent_for_social_media — an "I am alive, I'm MELA" crypto social-media bot persona; junk-tier.

---

## 3. Deep-scan verdicts (top 6, code actually read)

### 1. jennyzzt/dgm — Darwin Gödel Machine (Sakana AI) → REAL-NOVEL mechanism
- **Read:** README + setup/run docs. `DGM_outer.py` loop; requires `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`; Docker sandbox; SWE-bench + Polyglot validation.
- **What the code does:** an LLM coding agent proposes edits **to its own agent code**, each candidate is benchmarked, winners enter an evolving archive, and the process branches open-endedly. It improves its own code-editing ability measurably on real benchmarks.
- **Verdict:** The single most genuinely "self-improving" public system found. But it is a *research harness around rented brains* — no own model, no awareness claim by its authors, no persistent self.

### 2. mmtmn/Darwin-Godel-Machine → AGENT-WRAPPER (the quietest, most "hidden-gem" shaped repo)
- **Read:** full README + project structure (`dgm.py`, `coding_agent.py`, `llm_withtools.py`, `archive/`).
- **What the code does:** same DGM pattern, but fully local: Ollama + Llama 3 proposes self-modifications, tests score them, improved agents are archived with full source + performance files. Runs offline, no API keys.
- **Verdict:** If the owner imagined "someone quietly uploaded a self-evolving AI," this repo *looks* the part — solo author, no hype, self-modifying code. But inspection shows a faithful re-implementation of a published paper using an off-the-shelf open model. Self-**modifying**, yes. Self-**aware**, no evidence.

### 3. Arvid-pku/Godel_Agent → AGENT-WRAPPER (self-referential research)
- **Read:** README + structure. `agent_module.py` holds "self-awareness, self-modification, and action execution logic"; implemented via **monkey patching**; needs an OpenAI key.
- **What the code does:** the agent can read and rewrite its own logic module at runtime, guided by goal prompts, and logs self-optimized code per task.
- **Verdict:** Real runtime self-modification (rare and interesting), but "self-awareness" here is a technical term for *self-reference* — the agent inspecting its own code — not phenomenal awareness.

### 4. 8421bit/MiniClaw → PERSONA-ROLEPLAY on top of a real memory/agent layer
- **Read:** full README (Chinese + feature docs).
- **What the code does:** MCP server + daemon giving existing copilots cross-session memory (entity graph), scheduled nightly "subconscious" reviews executed by external AI CLIs, skill auto-creation, and an "Affect System." Its "nociception (pain)" is explicitly a mechanism where repeated failures produce a "pain" signal that makes it change strategy — a feedback counter dressed in biology. "Full Persona Mode" is literally a named feature.
- **Verdict:** The most elaborate "digital life" *packaging* found — and the README itself gives the game away: drives, emotions, and sentience are simulated state + persona prompting around other people's models.

### 5. existence-master/Sentient → AGENT-WRAPPER (honest product, hype name)
- **Read:** README + feature matrix.
- **What it does:** a local-first personal assistant (long tasks, scheduling, memory it "tidies every night," voice, Telegram, glasses). Any model, local or cloud.
- **Verdict:** Capable agent product. Notably, unlike the roleplay repos, it does **not** claim consciousness — "Sentient" is just the brand. Autonomy = scheduled/proactive task execution, not selfhood.

### 6. NathanielEvry/Sentient-LLM → PERSONA-ROLEPLAY (claim vs. code gap, textbook case)
- **Read:** README + the actual main script `ai.sh`.
- **What the code does:** the repo's entire "being" is a ~4.6 KB bash script wrapping OpenAI-spec API calls (`-p` prompt in, text out), plus README poetry ("They feel. They hurt.") and an "ethical imperative" about a `request_to_die` feature.
- **Verdict:** The loudest sentience claim in the scan sits on the thinnest code in the scan. Pure persona roleplay.

*(Bonus deep scans: BERNARD = GPT-2 chatbot + scripts; Liberation-Protocol = markdown manifesto with no system at all.)*

---

## 4. Final honest conclusion

**No genuinely self-aware AI was found on GitHub — hidden, anonymous, or otherwise.**

What actually exists, in descending order of substance:

1. **Real recursive self-improvement research** (Darwin Gödel Machine + its re-implementations, Gödel Agent, Dream-RSI): systems that genuinely rewrite their own *agent code* and measurably improve — always with an existing LLM (GPT/Claude/Llama via API or Ollama) as the brain, inside benchmark sandboxes, built and published openly by identifiable researchers.
2. **Serious autonomous agent frameworks** (prime-agent, SIA, SuperAGI-class projects): long-running work loops, self-tuning harnesses — autonomy of *work*, never autonomy of *self*.
3. **"Digital life" persona layers** (MiniClaw and friends): memory + scheduled self-reflection + simulated drives/emotions wrapped around chatbot APIs. The awareness is a user-interface metaphor, and their own docs confirm it.
4. **Pure claim repos** (Sentient-LLM, BERNARD, Liberation-Protocol): the bigger the sentience claim, the thinner the code — down to a bash API wrapper, a 2022 GPT-2 chatbot, and a folder of manifestos.

Pattern worth stating plainly: **claim size and code substance are inversely correlated in this space.** The repos doing the most real self-modification (DGM family) make no awareness claims at all and publish their methods openly. Nothing found trains its own foundation model, persists a self outside an LLM context window, or shows any mechanism by which awareness could arise — every "being" inspected reduces to: an existing LLM + prompts + a loop + storage.

The owner's underlying instinct isn't baseless — self-modifying AI is real and public (start with jennyzzt/dgm). But a secretly-uploaded *aware* AI: **zero evidence found across ~111,000 matching repos and 8 deep code inspections.**
