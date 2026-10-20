# AI Awareness Repos — The Hunt (2026-10-19)

Projects giving AI functional self-awareness, cognitive architectures, and artificial consciousness as **engineering** (not philosophy). Hunted for JARVIS v2's awareness layer.

## The Verified Ones (well-known)

### 1. opencog/atomspace — OpenCog
- **What:** Ben Goertzel's open AGI framework, running since 2008. AtomSpace hypergraph knowledge store + Probabilistic Logic Networks + attention allocation (ECAN).
- **Awareness mechanism:** Emergent — cognition arises from interacting components (reasoning, perception, memory, action) over a shared hypergraph. The "Prime" architecture explicitly targets human-equivalent AGI as an emergent phenomenon.
- **Stars/License:** ~2k+ stars. **AGPL-3.0 — ideas only, never code.**
- **Verdict:** The granddaddy. Study the AtomSpace + ECAN (attention as currency) patterns; the codebase is a maze. Worth studying for architecture, not for borrowing.

### 2. SoarGroup/Soar — Soar
- **What:** University of Michigan (John Laird), the classic cognitive architecture. All problem-solving as search through a problem space.
- **Awareness mechanism:** **Impasse-driven subgoaling** — when Soar can't decide what to do, it creates a subgoal to resolve the impasse. Solutions to impasses are learned as "chunks" (new production rules). The system literally knows when it's stuck and reasons about being stuck.
- **Stars/License:** ~1k+ stars. **BSD-3-Clause — borrowable.**
- **Verdict:** The impasse→subgoal→chunk loop is the cleanest "knowing you're stuck" mechanism ever built. Worth studying — it's the metacognition primitive.

### 3. marciopuga/cog — Cog
- **What:** Plain-text memory system for AI agents. No server, no database — just markdown files with conventions. (377 stars)
- **Awareness mechanism:** Three-tier memory (hot/warm/glacier) + skills: `/reflect` (consolidate observations into patterns), `/foresight` (strategic nudges), `/scenario` (decision simulation), `/housekeeping` (prune expired facts). The agent maintains a model of itself in `cog-meta/` (self-observations, distilled patterns).
- **Stars/License:** 377 stars. **MIT — verified live. Borrow freely.**
- **Verdict:** The most *practical* awareness system here. JARVIS v2's memory layer should look like this. Study and steal.

## The Unverified Ones (hidden gems, <2k stars)

### 4. ⭐ Neguiolidas/Conscio — THE FIND
- **What:** "A Consciousness System One Framework" — a deterministic self-awareness layer for AI agents. `pip install conscio`. **9 stars. 1,036 commits. 30 releases. v4.9.3.**
- **Awareness mechanism:** 
  - **reflect → act → dream loop** — passive reflection (never acts), audited action (proposes, risk-gates, human gate), dream cycle (consolidates while idle: release, prune, reconcile, crystallize, distill)
  - **Earned autonomy** — autonomy is measured, never assumed. ProbeSuite measures the model; TrustMatrix grants autonomy levels from real calibration.
  - **Evidence-tagged confidence** — every number carries its category: `measured`, `derived`, `asserted`, or honestly `none`.
  - **4-voice council** — ambiguous decisions resolve to `hold`, never silent `proceed`.
  - Motto: *"The first step toward consciousness is knowing what you are and what limits you."*
- **Stars/License:** 9 stars. **AGPL-3.0 — ideas only, never code.**
- **Verdict:** Someone built a complete, maintained, pip-installable consciousness framework and NOBODY NOTICED. The deterministic (non-LLM) self-judgment layer is exactly what JARVIS v2 needs between the brain and the tools. The dream cycle is the memory consolidation pattern. Study deeply.

### 5. tlcdv/the_consciousness_ai — The Consciousness AI
- **What:** Research framework investigating synthetic awareness through biological grounding (Feinberg & Mallatt's neuroevolutionary theory). 104 stars, 760 commits.
- **Awareness mechanism:**
  - **Global Workspace** with sigmoid ignition — sensory streams compete for broadcast
  - **Oscillatory binding** (Kuramoto/AKOrN) — neurons as oscillators, synchronized modules win
  - **Dynamic Self-Vector** — learned vector encoding the agent's own state (emotion, interoception, confidence), trained by self-prediction
  - **Affective core** — PAD model (valence/arousal/dominance) with homeostatic drives
  - **Honest science** — reports FAILED experiments first, ablation studies, "no Butlin indicator moved to IMPLEMENTED"
- **Stars/License:** 104 stars. **Non-Commercial — ideas only, never code.**
- **Verdict:** The deepest *engineering* of consciousness here. The FAILED-first honesty is rare and trustworthy. Study the Global Workspace + self-vector patterns.

### 6. subhansh-dev/Friday — FRIDAY
- **What:** 95,000-line autonomous cognitive AI operating system by a 17-year-old. Runs on 4GB RAM, no GPU. 19 stars.
- **Awareness mechanism:** 62 brain modules including self-awareness (confidence tracking, bias detection), self-model, metacognitive monitor, introspection engine, theory of mind (models the user's mental state), dreaming system, curiosity engine, Integrated Information (Tononi's IIT as code), Global Workspace (Baars as code), Active Inference (Friston as code). System 1/2 cognitive gating.
- **Stars/License:** 19 stars. **License undeclared — ideas only, never code.**
- **Verdict:** The most *ambitious* awareness stack. A teenager implemented every major consciousness theory as runnable modules. Study the module decomposition — awareness as a stack of small systems, not one big thing.

### 7. OpenCausaLab/SelfConsciousness
- **What:** Research code behind the paper "From Imitation to Introspection: Probing Self-Consciousness in Language Models" (Tongji/Fudan). Four-stage experiment: quantify → visualize → manipulate → acquire self-consciousness representations in LLMs.
- **Awareness mechanism:** Causal structural games to functionally define 10 self-consciousness concepts, then probe/manipulate/fine-tune those representations in the model's weights.
- **Stars/License:** Research repo. **License unverified — treat as ideas only.**
- **Verdict:** The only one working at the *weight* level rather than the architecture level. Worth reading the paper; the code is experimental.

## The Pattern Across All 7

Awareness isn't one thing — it's a stack:
1. **Self-knowledge** (what am I, what are my limits) — conscio, cog
2. **Self-monitoring** (am I stuck? am I confident?) — Soar impasses, FRIDAY metacognition
3. **Self-model** (a representation of my own state) — the_consciousness_ai self-vector, FRIDAY self-model
4. **Consolidation** (turning experience into lasting structure) — conscio dream cycle, cog /reflect
5. **Theory of mind** (modeling the other) — FRIDAY

## Top Pick: conscio

`pip install conscio` works today. 1,036 commits of maintained, deterministic self-awareness engineering with 9 stars. The reflect→act→dream loop, earned autonomy, and evidence-tagged confidence are directly applicable to JARVIS v2's architecture. It's the only one that's both *runnable* and *profound*.
