# Phase 2 Coverage Ledger — Rule Zero Audit (2026-10-19)

Statuses: SKIP (already covered) / GAP (partially understood — research the gap) / NEW (research in depth)

| Track | Topic | Status | Evidence of prior coverage |
|---|---|---|---|
| T1 | Hierarchical reasoning, planning | SKIP | SMITH PhD, Soar impasse→chunk, Anthropic managed agents, OpenGCUA |
| T1 | Search-based reasoning (beam/tree search) | GAP | Not deeply covered — NEW research |
| T1 | Belief-state tracking, Bayesian reasoning | GAP | Not covered — NEW research |
| T1 | Causal reasoning, counterfactuals | GAP | Not covered — NEW research |
| T1 | Neuro-symbolic architectures | GAP | Not covered — NEW research |
| T1 | Metacognitive monitoring, calibration | SKIP | Conscio judgment layer, RLCD calibration in SOUL.md |
| T2 | Durable execution, checkpoints, idempotency | SKIP | learn-advanced-cs.md (event sourcing lite, durable queue, fault domains) |
| T2 | Deadlock detection, sagas/compensating actions | GAP | Small gap — fold into researcher brief |
| T3 | Memory consolidation, forgetting, provenance | SKIP | mem0/Letta/A-MEM/cog PhDs, ECAN, temporal markers |
| T3 | Temporal knowledge graphs, entity resolution | GAP | Small gap — fold into researcher brief |
| T4 | SFT/DPO/RL distinctions | SKIP | RLCD study, nova auto-DPO lesson (killed by author) |
| T4 | Continual learning, catastrophic forgetting | GAP | Not deeply covered — NEW research |
| T4 | Eval contamination, benchmark leakage | GAP | Partial — NEW research |
| T5 | Self-improvement loop | SKIP | Harness² in AGENTS.md, Hermes skills, propose→probe→compose |
| T5 | Ablation studies, failure clustering | GAP | Small gap — fold into researcher brief |
| T6 | KV-cache, quantization, VRAM, speculative decoding | SKIP | rtx-2060-guide.md, BitNet PhD, LLMLingua-2 PhD |
| T6 | Attention variants, quantization calibration | GAP | Not deeply covered — NEW research |
| T6 | Inference measurement framework | GAP | NEW research (measure don't assume) |
| T7 | Streaming voice, barge-in, turn-taking | SKIP | learn-multimodal.md, Moshi/vocoder studies, voice pipeline |
| T7 | Speaker diarization, video temporal reasoning | GAP | Small gap — fold into researcher brief |
| T8 | Tool reliability, prompt-injection defense | SKIP | hardened_runner.py (13 attacks), REA evidence model, R2, Deno perms |
| T9 | Property-based testing, fuzzing | SKIP | testing track, 180 tests |
| T9 | Formal methods (TLA+, model checking) for agents | GAP | Not covered — NEW research (scoped) |
| T10 | Observability, metrics, tracing | SKIP | learn-observability.md |
| T10 | Human preference eval, inter-rater reliability | GAP | Small gap — fold into researcher brief |
| T11 | Distributed vs monolith | SKIP | learn-advanced-cs.md already rendered the verdict: monolith+3 processes |
| T12 | Threat modeling, injection defense, secrets | SKIP | FAILURE-ANALYSIS.md, hardened_runner, R2/R9 |
| T12 | Supply-chain security, red-teaming | GAP | Small gap — fold into researcher brief |
| T13 | Preference provenance, correction handling | SKIP | Memory system, "never treat inference as fact" doctrine |
| T14 | Agentic RL, test-time compute, long-context | SKIP | SMITH PhD, RLCD study, LLMLingua-2 |
| T14 | World models, process supervision | GAP | Not covered — NEW research |
| T14 | Mechanistic interpretability, self-reflection limits | GAP | Not covered — NEW research |
| T15 | Architecture synthesis | DEFER | Final deliverable after gap research lands |

## Research dispatched (5 workers) — ALL LANDED 2026-10-19
1. **Advanced reasoning** (T1 gaps) → `learn-frontier-reasoning.md` ✓ (8-strategy table, belief ledger, causal post-mortem)
2. **Continual learning** (T4 gaps) → `learn-continual-learning.md` ✓ (never fine-tune a fact, O-LoRA adapters, contamination tiers)
3. **Inference frontiers** (T6 gaps) → `learn-inference-frontiers.md` ✓ (KV-head math, Q4_K_M floor, 4k-physical strategy)
4. **Formal methods for agents** (T9 gap) → `learn-formal-methods.md` ✓ (beartype USE, deal on 5–10 functions, Hypothesis stateful)
5. **Research frontiers** (T14 gaps) → `learn-research-frontiers.md` ✓ (external ground truth > introspection, self-reflection limits)

## Small gaps folded into briefs
- T2: deadlock detection, sagas → researcher 1's overflow (or covered by durable queue work — mark)
- T3: temporal KG, entity resolution → researcher 2's overflow
- T5: ablation studies → researcher 5's overflow
- T7: diarization → skip (not needed for single-user JARVIS — verdict: SKIP with reason)
- T10: human eval → researcher 5's overflow
- T12: supply-chain, red-teaming → researcher 4's overflow
