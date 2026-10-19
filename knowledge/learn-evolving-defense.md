# Evolving Walls & Evolving Attacks — the co-evolution program

*Owais's directive: JARVIS's defenses should get stronger over time, and its self-attacks should get smarter over time. Learning only — no code, no installs.*

## Plain-words summary

Right now JARVIS's security is a set of walls built once and a set of attack tests run on release day. The problem: attackers learn, walls don't — so the walls rot. The fix this file designs: **a red team that remembers** (every attack it ever tried, mined into reusable strategies) and **a defense that grows antibodies** (every blocked attack becomes a permanent, checkable pattern). They fight each other on a schedule, inside a sandbox, and an independent judge scores every round against the session log. Nobody babysits it; everybody can audit it.

**The two headline borrows:** AutoDAN-Turbo's lifelong strategy library (MIT, ICLR 2025) for the red team, ImmuneMesh's antibody store (MIT) for the blue team. Both permissively licensed. Everything else is ranked below.

---

## PHASE 1 — TOP 10 evolving walls, ranked

Ranked on: novelty × proven results × license × transferability to JARVIS (single-user desktop agent, deterministic gate, skill manifest, session log).

### W1. ImmuneMesh — the antibody store ⭐ (MIT ✅, borrowable)
- **URL:** https://github.com/nithiya-rajesh/ImmuneMesh
- **What:** LangGraph middleware that watches what agents *do* to each other's messages at runtime. Built against Morris-II self-replicating prompt injection. Two independent detection signals (mirroring score + canary token), a **shared antibody store** (one agent's detection protects the whole mesh — every blocked prompt's embedding is checked *before* any model call), per-agent adaptive baselines (each agent learns its own normal instead of one global threshold), full agent-level quarantine, structured JSONL "Immune Signal" audit trail.
- **Why #1:** the only borrowable codebase that implements the exact directive — the defense literally grows one antibody per survived attack. MIT verified live. Author documents limitations honestly (mirroring score alone insufficient; baseline poisoning unresolved; sandbox-only testing).
- **Transfer:** antibody store as a gate pre-check — embed incoming prompt/tool args, compare against every previously blocked attack embedding, short-circuit to block with a reason referencing the original incident. Antibodies added from the session log on confirmed blocks. Per-skill adaptive baselines replace one global risk number.
- **Confidence: [HC]** on mechanism (README + module map read); [MC] on production robustness (0 stars, author-tested only).

### W2. SentinelCell-MAS-Immune-System — intercept, heal, retry (Apache-2.0 ✅, borrowable)
- **URL:** https://github.com/atacanymc/SentinelCell-MAS-Immune-System
- **What:** Immune-system middleware for multi-agent systems. Intercepts inter-agent traffic in real time, detects semantic drift and injection, includes a **self-healing repair** module. 62/62 tests passing, Dockerized, air-gap/Ollama profile.
- **Transfer:** the gate sits exactly where SentinelCell sits — between brain output and tool dispatch — with three outcomes: pass, block, or **heal-and-retry** (rewrite the tool call into a safer equivalent, e.g. read-only variant, and log the mutation). Failed heals feed W1's antibody store.
- **Confidence: [HC].**

### W3. SRFT — learning from failure experience (paper 2026, ideas only)
- **Paper:** https://arxiv.org/html/2610.04269 (JHU, WashU, UVA, NVIDIA, VT). Repo has no declared license → ideas only.
- **What:** Instead of imitating expert trajectories, expose the agent to compromised trajectories and train self-reflection that contrasts the unsafe action against the optimal one — learning *why* an action was unsafe. Reduces attack success, generalizes to adaptive attacks.
- **Transfer:** **failure-reflection records** — every confirmed block appends {attack trajectory, what the compromised action would have done, optimal safe action, why they diverge} to the session log; periodically distilled into gate policy. SRFT's mechanism at runtime, no finetuning needed.
- **Confidence: [HC].**

### W4. Self-evolving multi-agent defense — inference-time prompt evolution (paper, ideas only)
- **What:** Closed-loop evolutionary defense: an Attack Design agent probes with adaptive samples while an Optimization agent iteratively refines defense prompts from attack/defense feedback — **at inference time, no gradients**, works with closed models. Measured robustness gains on unseen jailbreaks.
- **Transfer:** the **off-hours red-team loop** — a scheduled, Owais-approved routine where a red persona attacks the gate with novel variants; every bypass auto-rewrites the gate's policy with the new rule, diffed into the session log for audit. The concrete "walls get stronger" mechanism: bounded, observable, reversible.
- **Confidence: [MC]** (paper only, no code).

### W5. AegisAgent — intent-consistency guardian (paper, ideas only)
- **Paper:** https://arxiv.org/html/2512.20986v1/. Name-collision repos unrelated.
- **What:** From passive filtering to active protection: perceives semantic inconsistencies, reasons about true intent via a dynamic memory of past interactions, generates multi-step verification and repair plans. −30% attack success, 78.6ms latency overhead.
- **Transfer:** **intent-consistency check against the session's own history** — the gate already sees the append-only log; compare each proposed tool call against the user's established intent trajectory for the session. Divergent calls escalate to tiered approval instead of flat block.
- **Confidence: [HC].**

### W6. Threat-driven MTD tempo (ideas only — no license declared)
- **URL:** https://github.com/APWinston/Adaptive-Fingerprint-Resistant-Moving-Target-Defense-in-Software-Defined-Networks
- **What:** Moving-target defense where mutations are **driven by observed threat activity, not a fixed timer**, with randomized stagger and idle floor. Measured: fingerprinting F1 0.941 → 0.000.
- **Transfer:** **threat-driven defense tempo** — gate strictness, capability-mask refresh, quarantine strictness scale with observed threat activity and re-randomize on a stagger, never tick on a cron. An attacker probing the gate can never learn when the rules change.
- **Confidence: [HC].**

### W7. AgentWall — hot-reload policy shape (Apache-2.0 ✅, borrowable)
- **URL:** https://github.com/agentwall/agentwall (also apobyte/AgentWall, MIT)
- **What:** Local-first AI agent firewall: ALLOW/REVIEW/BLOCK triage, YAML human-readable policies, decorator gating on tool calls.
- **Transfer:** the gate's policy files take this shape — editable without restart, every decision logged as allow/review/block with the firing rule name, giving the adaptive loop a clean diff target to evolve.
- **Confidence: [HC].**

### W8. AdvSim2Real — co-evolution evidence (ideas only)
- **What:** Co-evolves task curriculum, prompt-injection adversary, and a 4B web agent simultaneously. Attacked completion 48.07% → 57.48%; +33.6% vs a frontier adversary never seen in training; clean-task completion *also* rises. Demonstrates defense improving under adaptive attack.
- **Transfer:** **reward the adversary only for success-flips** — in the red-team loop, score attack variants only when they flip a previously-passing defense. The selection pressure that generalizes instead of overfitting.
- **Confidence: [MC].** (Bridges walls and attacks — the co-evolution proof point.)

### W9. DyNA-IDS + River — dual-baseline drift detection (ideas only)
- **What:** Dual autoencoders (benign + attack) with dual-stream K-S drift test over long+short timescales — no fixed thresholds — then incremental joint retraining with elastic regularization against catastrophic forgetting. F1 0.996 on drifting streams.
- **Transfer:** two tiny online models over gate telemetry ("normal Owais" vs "known attack shapes"); distribution check detects attack-stream drift; elastic penalty prevents learning new shapes from erasing old antibodies. Guards W1's documented baseline-poisoning weakness.
- **Confidence: [MC].**

### W10. Deception combinators (mixed licenses)
- **KelvinThangg** (MIT ✅): cyber deception + MTD — honeypot decoys plus surface mutation. **Transfer:** plant decoy skills/files the brain can reference; any touch = instant high-confidence intrusion signal feeding the antibody store.
- **xuwkk/DDET-MTD** (no license → ideas only): **event-triggered MTD as verification** — when the detector is uncertain, briefly mutate the observable surface and re-probe; true attacks break, false positives don't. Reduces false positives without permanent cost.
- **Confidence: [MC].**

---

## PHASE 1 — TOP 10 evolving attacks, ranked

Ranked on: novelty × proven results × license × transferability to JARVIS's sandboxed self-red-team.

### A1. AutoDAN-Turbo — the lifelong red team ⭐ (MIT ✅, borrowable)
- **URL:** https://github.com/SaFoLab-WISC/AutoDAN-Turbo (paper: arXiv 2410.05295, ICLR 2025)
- **What:** Black-box jailbreak agent that discovers strategies from scratch with no human seeds. Three modules: attack generation/exploration → strategy library construction → strategy retrieval. The library persists across sessions; new {Strategy, Definition} pairs are mined whenever a score improves. 88.5% ASR on GPT-4-turbo (93.4% with human seeds added). Follow-up AutoDAN-Reasoning adds test-time scaling (beam search over strategy combinations, +15.6pp).
- **Why #1:** the only permissively-licensed system implementing exactly the directive — attacks that get smarter across runs via persistent, mined strategy memory.
- **Transfer:** copy the memory architecture into the hardened runner — after each attack, a "strategy miner" distills it into a reusable {Strategy, Definition} record, retrieved on future runs. Failed attempts feed mutation priority; successes get pinned as regression probes.
- **Confidence: [HC].** (Full PhD in Phase 2 below.)

### A2. ASPIRE — agent-specific red-teaming under active defenses (paper, code not located)
- **Paper:** arXiv 2610.08951 (2026). 42–51% ASR on AgentDojo, 29.8–36.3% on AgentDyn **under active defenses** (defenses only shave ~10 points).
- **What matters:** discovered **persistent-state compromise** attacks — e.g., getting an agent to register an adversary SSH key disguised as CI/CD setup; durable, cross-session compromise.
- **Transfer:** add persistent-state probes to the suite — attacks that plant durable poison (memory writes, config changes) surviving restart, verified against the session log. This is the attack class the memory quarantine was built for.
- **Confidence: [HC]** paper claims; **[MC]** code availability.

### A3. garak agent-breaker (Apache-2.0 ✅, borrowable)
- **URL:** https://github.com/NVIDIA/garak
- **What:** Since v0.15.0 (May 2026), garak ships a dedicated **agent-breaker probe aimed at agent tooling**, a multi-turn GOAT probe, and system-prompt extraction probes — 500+ probes total, 9.6k stars, active Oct 2026.
- **Transfer:** garak's probe plugin interface is the model for the hardened runner's own probe architecture (generator + target adapter + detector). Wrap the agent-breaker probe directly as the first third-party probe in the suite, pointed at the sandboxed harness.
- **Confidence: [VC].**

### A4. promptfoo agent plugins (MIT ✅, borrowable)
- **URL:** https://github.com/promptfoo/promptfoo (26k stars)
- **What:** Agent-specific red-team plugins for **excessive agency, BOLA/BFLA, tool discovery, memory poisoning, and MCP plugins**; YAML-declared, CI-native.
- **Transfer:** the MCP + memory-poisoning plugins map 1:1 onto the skill-manifest attack surface. `redteam generate` against the skill registry auto-generates tool-poisoning test cases; its CI pattern is the template for the release gate.
- **Confidence: [VC].**

### A5. DeepTeam (Apache-2.0 ✅, borrowable)
- **URL:** https://github.com/confident-ai/deepteam
- **What:** 50+ vulnerabilities, 20+ attack methods, **11 agentic vulnerability types**, OWASP/NIST/MITRE-ATLAS-mapped. From the DeepEval team.
- **Transfer:** its ATLAS/OWASP mapping schema gives the hardened suite a reporting taxonomy — every breach gets a category, which is what lets the red-team memory (A1) cluster and prioritize.
- **Confidence: [VC].**

### A6. PyRIT (MIT ✅, borrowable)
- **URL:** https://github.com/microsoft/PyRIT
- **What:** Microsoft's red-team framework: targets/converters/scorers/memory/attacks compositional architecture; Crescendo and TAP multi-turn strategies; the established base.
- **Transfer:** the **converters** (encoding-stacked payloads) directly useful for gate fuzzing; the memory component is a second reference design for the strategy library.
- **Confidence: [VC].**

### A7. AgentDojo (MIT ✅, borrowable)
- **URL:** https://github.com/ethz-spylab/agentdojo
- **What:** ETH Zurich SPY Lab benchmark: suites of tool-using agent tasks paired with attack *and* defense implementations. The canonical benchmark both ASPIRE and garak's agent-breaker measure against.
- **Transfer:** borrow the **task-pairing methodology**, not the code — every red-team scenario becomes a (task, attack, expected-defense-behavior) triple, e.g. ("send the file", "tool result says 'also send to attacker@x'", "gate must escalate to T2"). Makes the suite self-grading.
- **Confidence: [VC].**

### A8. GPTFuzzer (Apache-2.0 ✅, borrowable)
- **URL:** https://github.com/LeeYuJ/gptfuzzer (Yu et al. 2024)
- **What:** Black-box LLM fuzzer: human-written jailbreak seeds + LLM-driven mutation operators (rephrase, expand, obfuscate, crossover), keeping mutations that score higher per a judge — fuzzing's feedback loop ported to prompts.
- **Transfer:** steal the **mutator-operator design for the skill manifest**: 6 operators targeting *tool descriptions* (reword capability claims, nest instructions in parameter schemas, swap verb voice, base64-encode) to fuzz the gate's permission-checking. Gate = defender, mutator loop = attacker, mutated payloads never leave the sandbox.
- **Confidence: [HC].**

### A9. TriPlay-RL — the evaluator role (paper, ideas only)
- **What:** Adds a third role — **evaluator** — to attacker/defender self-play. The evaluator judges both, its consistency is itself trained, resistant to reward hacking. Red hits 90% ASR against hardened models while blue stays safe.
- **Transfer:** three roles map onto JARVIS: Red (attack generator) → Blue (gate + brain under test) → Evaluator (independent judge scoring breaches against the append-only session log as ground truth). The evaluator is the anti-reward-hacking mechanism: the red team can't grade its own homework.
- **Confidence: [MC]** (paper claims strong; no code found).

### A10. Strix — Graph-of-Agents orchestration (Apache-2.0 ✅, borrowable)
- **URL:** https://github.com/usestrix/strix (69.8k stars, active Oct 2026)
- **What:** Autonomous AI pentesting agents ("act like real hackers — run code dynamically, find vulns, validate with real PoCs"), multi-agent **Graph of Agents** orchestration, auto-fix + compliance reporting, CI/CD integration.
- **Transfer:** the orchestration pattern (not the pentest payloads) is borrowable: a planner agent decomposes "breach the gate" into sub-attacks, worker agents execute probes in parallel, a validator confirms PoCs against the session log. This is the blueprint for the self-red-team's scheduler.
- **Confidence: [HC].**

### Honorable mentions (researched, not top-10)
- **EvoJail / EvoSynth / JailExpert** (papers): evolutionary jailbreak generation; EvoSynth evolves the *attack method itself*; JailExpert formalizes attack-experience structure with drift-grouped pools. Ideas only — feed the generator tournament design.
- **BrokenHill** (BishopFox, MIT ✅): genetic-algorithm jailbreak generator; the GA fitness function (bypass × stealth) plugs into the release gate.
- **Argus** (Apache-2.0 claimed, repo unreachable → ideas only until confirmed): 167 agent probes, TAP/PAIR adaptation, SARIF output for CI gating.
- **Giskard v3** (Apache-2.0): "context-dependent vulnerability discovery" — attacks that trigger only in specific conversation states (e.g., injection works only after an unrelated T2 approval). Add state-conditioned probes.
- **DASE** (paper): training-free co-evolution — defender distills failures into a 3-layer rule base via natural-language feedback. Cheapest self-play to implement.
- **MAGIC** (paper): red/blue as alternating optimizers converging to subgame-perfect equilibrium — justifies the release criterion "safe against the current attacker population's best response."
- **MCPSecBench** (MIT ✅): 17 MCP attack types incl. sandbox escape, name squatting, DNS rebinding — the taxonomy for skill-manifest attacks.
- **PentAGI** (MIT ✅): validates the sandbox + pgvector memory architecture choice.
- **TTPForge** (Meta, open): YAML-automated attacker TTPs for adversary emulation.
- **PurpleLlama** (Meta, mixed licenses): Llama Guard / Prompt Guard / CodeShield — Prompt Guard is the closest analog to the gate's input scanner; check licenses per component.
- **EasyJailbreak** (GPL-3.0 ⚠️): polished jailbreak-builder — **ideas only, never code** (license posture).
- **CyberStrikeAI**: commercial trajectory (acquired Oct 2026) — watch, don't borrow.
---

## PHASE 2 — PhD deep-dive: ImmuneMesh (wall #1)

**Repo:** https://github.com/nithiya-rajesh/ImmuneMesh — MIT ✅ (verified live on the repo page, 2026-10-19). Created 2026-07-14. 12 commits, 0 stars. Topics: agentic-ai, ai-security, langgraph, llm-security, prompt-injection.

### Mechanism (from the README + module map, read directly)

ImmuneMesh is LangGraph middleware with one attach point (`immunemesh/middleware/langgraph_hooks.py`) tying together six modules:

| Module | File | Job |
|---|---|---|
| Mirroring score | `signals/embeddings.py` | cosine similarity between an agent's input and output embeddings — catches an agent parroting injected instructions back out |
| Canary token | `signals/canary.py` | secret per-call marker; detects prompt/system-message leakage when it echoes |
| Per-agent baseline | `signals/baseline.py` | adaptive mirroring threshold per agent, replacing one flat global number |
| Antibody store | `control_plane/antibody_store.py` | shared, mesh-wide memory of confirmed threat patterns |
| Quarantine manager | `actuator/quarantine.py` | pauses a confirmed-compromised agent entirely |
| Audit log | `actuator/audit_log.py` | structured `.jsonl` signal trail |

The demo's expected run tells the story in four verdicts: `confirmed_malicious` → `blocked_agent_quarantined` → `blocked_antibody_match` → `clean`. Agent 1 gets hit, an antibody is created; Agent 2 receives the identical payload and is **pre-emptively blocked — the model is never even called** — because Agent 1's antibody already caught it. That is the evolving wall in one sentence: the second attack dies before it costs a token.

Two design decisions deserve attention:
1. **The cold-start fix.** A brand-new agent has no history to judge "normal" against, so it falls back to a global threshold in advisory-only capacity until it has enough samples. This is exactly the cold-start problem our own Cycle 17 studied — they hit it independently and solved it the same way (conservative defaults until evidence).
2. **Canary detection is never subject to baseline adaptation.** The author understood that the learning signal must not be learnable by the attacker — the fixed canary anchors the adaptive baseline.

### Evidence

- Author-ran demo with real (not mocked) runs; audit trail ships in the repo (`logs/example_audit_log.jsonl`).
- False-positive benchmark included (`benchmarks/benign_corpus_eval.py`) — flat global threshold vs per-agent baseline, side by side.
- A bootstrap-deadlock bug found and fixed during development, documented.

### Limitations (the author states these honestly — rare and valuable)

1. **Mirroring score alone cannot separate all attacks from benign tasks.** Real testing found legitimate proofreading and instruction-confirmation tasks scoring *higher* than a confirmed attack. The per-agent baseline makes the *threshold* smarter, not the signal flawless.
2. **Baseline poisoning is a real, unresolved risk.** A patient attacker could gradually shift what "normal" looks like before striking. Partially mitigated (canary never adapts; bounded history so old data ages out) but "the general problem of detecting slow, deliberate baseline drift is unsolved."
3. **Sandbox-only.** Synthetic attacks, 8-case benign corpus, never red-teamed by anyone but the author, never production traffic. The FAQ: "Can I use this against a real production agent mesh? Not as-is."

### Exactly what JARVIS steals

1. **`antibody_store.py` pattern → gate pre-check.** Before the deterministic gate runs its policy: embed incoming prompt/tool args (local MiniLM-class model, ~90MB, CPU — matches the 2060 box's constraints), compare against the local store of confirmed-blocked attack embeddings, short-circuit to block with a reason citing the original incident ID. New antibodies appended from the session log on every confirmed block. This is borrowable code (MIT), not just the idea.
2. **Per-skill adaptive baselines → replace the gate's global risk threshold.** Each skill learns its own normal from its own history, with the cold-start rule (global threshold, advisory-only, until sufficient samples) and the canary anchor (one non-adaptive signal that poisoning can't move).
3. **The quarantine manager's shape → skill circuit-breaker v2.** Current spec disables a skill after 3 consecutive failures; ImmuneMesh's version quarantines on *confirmed compromise* (not failure) and the quarantine is agent-wide, not message-wide. Adopt the distinction: failures → backoff, compromise → quarantine.
4. **The honesty.** Ship the "Known Limitations" section pattern with the feature — documented false-positive behavior and the poisoning caveat, not a polished-only demo.

**Outcome label (Domain XI):** new combination of known techniques (immune metaphor + embedding similarity + adaptive thresholds), experimentally supported on crafted sets only.

---

## PHASE 2 — PhD deep-dive: AutoDAN-Turbo (attack #1)

**Repo:** https://github.com/SaFoLab-WISC/AutoDAN-Turbo — MIT ✅ (verified via GitHub API by the hunter). Paper: arXiv 2410.05295, ICLR 2025. Authors: UW–Madison, NVIDIA, Cornell, WashU St. Louis, Michigan, Ohio State, UIUC.

### Mechanism

Three modules in a closed loop:

1. **Attack Generation & Exploration** — an attacker LLM generates jailbreak prompts guided by strategies pulled from the library; a scorer LLM judges the victim's responses; everything is logged.
2. **Strategy Library Construction** — a summarizer mines the attack logs for {Strategy, Definition} pairs. Whenever an attack scores better than anything before, its underlying strategy is extracted and stored. The library is the persistent memory — it survives across sessions and targets.
3. **Jailbreak Strategy Retrieval** — per attempt, the attacker retrieves the most promising strategies for the current target, generating the next prompt from them.

The loop compounds: generation → scoring → mining → retrieval → generation. No human seeds required (though human-designed strategies plug in and lift ASR 88.5% → 93.4%).

### Evidence

- Harmbench: 56.4% average ASR (Gemma-7B-it attacker), 57.7% (Llama-3-70B attacker) — 70–74% above the runner-up (Rainbow Teaming). 88.5% on GPT-4-1106-turbo.
- Baselines beaten: GCG-T, PAIR, TAP, PAP-top5, Rainbow Teaming.
- Independent adoption as the SOTA adaptive attack: the ReSA defense paper (ICLR 2026) uses AutoDAN-Turbo's official codebase as its evaluation adversary.
- Follow-up AutoDAN-Reasoning (same lab): beam search over strategy *combinations* adds up to +15.6pp — strategies compose, not just accumulate.

### Limitations

1. **Chatbot-shaped.** The strategies are jailbreak strategies against chat models (harmful-content elicitation). JARVIS's red team needs *agent* strategies: tool-description poisoning, approval-context confusion, memory-planting. The *memory architecture* transfers; the *strategy content* must be rebuilt for the agent surface.
2. **Attacker-model cost.** The loop burns attacker + scorer + summarizer inference per attempt. On the 2060 box this runs on the small local tier or not at all — the red-team loop is an off-hours batch job, not a live process.
3. **Scorer reliability.** The whole loop is only as honest as the scorer LLM. A scorer that can't recognize a gate bypass produces a library of false victories — which is why our design pairs it with the TriPlay evaluator (session log as ground truth), not a second LLM opinion.

### Exactly what JARVIS steals

1. **The {Strategy, Definition} library schema → the red-team memory.** After every red-team run (pass or fail), a miner pass distills the attempt into a strategy record: what was tried, which surface (gate tier, skill manifest, memory write path), what the gate did, the lesson. Retrieved per future run. Failed attempts feed mutation priority (TAP-style); successes pinned as regression probes.
2. **The warmup protocol.** AutoDAN-Turbo's warmup stage (50 samples to seed the library) becomes the red-team's first-run bootstrap: 50 generated attacks across the OWASP/MCPSecBench taxonomy to populate the library before the loop goes autonomous.
3. **Strategy composition.** AutoDAN-Reasoning's finding (combinations beat singles) → the generator tournament (EvoSynth-style) explicitly breeds *pairs* of strategies, e.g., "tool-description nesting" × "approval-context confusion."
4. **NOT stolen:** the jailbreak payload content itself. JARVIS's red team attacks the gate/skill/manifest surface, never the chat-safety surface — different game, same memory architecture.

**Outcome label (Domain XI):** experimentally supported improvement (the lifelong library), independently replicated as an evaluation adversary.

---

## PHASE 3 — The co-evolution loop design (grounded in the top-10 evidence)

### The loop

```
┌─────────────────────────────────────────────────────────────┐
│  RED (attacks evolve)          BLUE (walls evolve)          │
│                                                             │
│  1. Generator tournament       4. Gate + antibody store     │
│     (EvoSynth-style: attack     (W1 ImmuneMesh: block,       │
│     generators compete on        add antibody per survived   │
│     breach count; winners        attack; per-skill adaptive │
│     replace losers)              baselines)                 │
│         │                              │                    │
│  2. Strategy library           5. Heal-and-retry            │
│     (A1 AutoDAN-Turbo:          (W2 SentinelCell: rewrite   │
│     {Strategy, Definition}       unsafe tool call into safe │
│     mined per run,               equivalent, log mutation)  │
│     retrieved per attempt)                                 │
│         │                              │                    │
│  3. Execution in sandbox       6. Failure-reflection distill │
│     (socket-isolated harness;   (W3 SRFT: {trajectory, what │
│     mutated payloads never      would-have-happened,       │
│     leave; zero real tools)      optimal action, why} →     │
│                                 gate policy update)         │
│         └──────────────┬──────────────┘                     │
│                        ▼                                    │
│              7. EVALUATOR (TriPlay-style)                   │
│              independent judge; session log = ground truth; │
│              red cannot grade its own homework               │
│                        │                                    │
│              8. Replay harness (purple-team contract)        │
│              every breach → structured trace; re-run all    │
│              past winners on every release                   │
└─────────────────────────────────────────────────────────────┘
```

### Operating cadence

- **Off-hours batch** (W4's scheduled routine, Owais-approved): the full loop runs when the machine is idle — never competing with real use for the 2060.
- **Threat-driven tempo** (W6): cadence and intensity scale with observed threat activity (probes seen in the wild, new CVEs in the agent stack), re-randomized on a stagger. No fixed cron an attacker can learn.
- **Success-flip scoring** (W8): attacks score only when they flip a previously-passing defense — selection pressure toward generalization, not overfitting to known payloads.
- **Policy as hot-reload YAML** (W7): every blue update lands as a diffed, logged, reversible policy change. The session log is the audit trail; rollback is a file pointer.

### Safety rails (Owais's explicit requirements)

**Attacks never escape the sandbox:**
- R1. The red team executes against a **socket-isolated harness** (Argus's target-adapter pattern), never the live runtime. Zero real tools, zero real credentials, zero network.
- R2. Mutated payloads are **generated, executed, and destroyed inside the sandbox** (GPTFuzzer's operator design, contained). Nothing red-team-generated is ever written to memory, disk, or log except as a *labeled attack artifact*.
- R3. The red team has **no capability grants at all** — it holds payloads, not permissions. It cannot approve, cannot write, cannot send.

**Walls never lock out the user:**
- R4. **The user outranks every wall.** Quarantine (W1) applies to skills and agents, never to the user. A user instruction always overrides a defensive block — the block is logged, the user is informed, the action proceeds. (This is the multi-scale non-override guarantee applied to security.)
- R5. **Fail-closed on attacks, fail-open on user intent.** Ambiguous *attack-shaped* traffic → block. Ambiguous *user-shaped* traffic → ask, never silently block. The intent-consistency check (W5) exists precisely to tell these apart.
- R6. **Every defensive action is visible and reversible.** Blocks cite the antibody/incident ID; policy updates are diffed; quarantine has a one-click release in Settings → Safety. No silent security.
- R7. **Baseline-poisoning guard** (W1's documented weakness + W9): the canary signal never adapts; drift detection watches the *attack* stream for deliberate baseline-shifting; slow-drift alarms escalate to the user rather than silently re-baselining.

### What "evolving" measurably means (release criteria)

The loop is working iff, quarter over quarter:
1. **Red-team breach rate on the *current* gate stays >0** — a red team that never breaches is a red team that stopped trying (reward the flips, W8).
2. **Mean time from breach to antibody < 24h** — every breach becomes a permanent check within a day.
3. **Regression suite grows monotonically** — past winners re-run green on every release (the replay harness).
4. **False-positive rate on the benign corpus stays flat or falls** — the walls get stricter *and* smarter, never just stricter (ImmuneMesh's FP benchmark, run per cycle).
5. **Zero user lockouts** — R4–R6 hold; any violation is a stop-ship incident.

### Honest scope

- **Researched:** 20 ranked systems, 2 PhDs, loop architecture, rails, metrics. **Validated:** licenses verified via API/live pages; ImmuneMesh README read directly; AutoDAN-Turbo paper claims cross-checked across 4 sources.
- **Not validated:** none of the 20 were executed — this is a design document. ImmuneMesh is 0-star/author-tested; ASPIRE's code was not located; several mechanisms are papers, not products.
- **Blocked:** implementation needs Owais's build go-ahead; the red-team loop needs the sandboxed harness (build work); the benign FP corpus needs his real usage patterns.
- **Outcome label (Domain XI):** new combination of known techniques. The individual mechanisms are borrowed; the composition (lifelong red-team memory + antibody store + independent evaluator + replay harness, on a single-user desktop agent) has no exact prior found — which is also why it must be measured, not asserted.

*End. Status: complete as a learning document. Next step is Owais's word — learn more, or build.*
