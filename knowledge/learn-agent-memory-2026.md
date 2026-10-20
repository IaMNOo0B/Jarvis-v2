# Agent Memory Architectures 2026

What's new in agent memory as of October 2026 — papers, open-source systems, and what works at small (single-user, local-first) scale. Researched 2026-10-19 from 6 sources, cross-referenced. (Supplements the existing learn-memory-spec.md, which covers our own two-store design.)

## The landscape

**1. The field has a taxonomy now [HC]**
A 70+ researcher survey (Hugging Face Papers, Oct 2026) catalogued **297 multimodal agent memory architectures** and sorted them on two axes: what is stored (representation) and three management tiers — **T1 Static** (store fixed, never modify), **T2 Dynamic** (update state via stable policy: append/revise/merge/forget), **T3 Self-Evolving** (update the state AND the policy). T2 is widespread; deployment-time T3 remains scarce. Hybrid architectures (explicit records + latent/internalized) are prevalent in advanced systems. JARVIS's current design is T2 — the right call; T3 is research-grade.

**2. RAG is retrieval, not memory [VC]**
A March 2026 wiki synthesis (citing an arXiv systematic review): less than 15% of studied RAG deployments support production-level integration. RAG answers "find text similar to this query" but doesn't address staleness, conflicting knowledge, write-path governance, scoping, or provenance. GraphRAG narrows the gap for relationships but not governance. **The "ungardened wiki" failure mode is real**: agents that write at machine speed corrupt memory unless TTL, confidence decay, or explicit conflict resolution is built into the write path. JARVIS already has provenance tiers and quarantine — this validates that design and says: add TTL/confidence decay next.

**3. Five layers in production systems [HC]**
Real deployments (Copilot, Cursor, Devin) use: (a) in-context working memory, (b) vector retrieval/RAG (90% token savings vs full context), (c) episodic/temporal knowledge graphs, (d) structured paging (MemGPT/Letta OS-style swap), (e) parametric (fine-tuning). Mixing (a)+(b)+(c) gives 70-91% latency reduction vs pure in-context. JARVIS has (a)+(b)+(d-lite); the gap is (c) — a temporal knowledge graph.

**4. The framework ranking [HC]**
- **Mem0** (41K stars): most adopted. +26% accuracy over OpenAI native memory on LOCOMO, 91% faster, 90% cheaper. User/session/agent scoping, graph entities, TTL/confidence filtering. Apache 2.0.
- **Zep/Graphiti**: most mature **temporal** memory. Every fact carries explicit validity intervals ("what was true at time T?"). Beats Mem0 on LongMemEval 63.8% vs 49.0%. The pick when temporal accuracy matters.
- **Letta** (21K stars): OS-inspired memory for autonomous agents (MemGPT lineage).
- **LangMem**: LangChain's memory SDK. **Cognee**: knowledge-graph memory engine.
- Governance (audit trails, retention policies) is a gap across ALL of them.

**5. New 2026 papers worth watching [MC]**
- **AtomMem** (Jan 2026): learnable CRUD memory policies — the agent learns HOW to manage memory, not just what to store.
- **Memory-R1** (2025/2026): reinforcement learning for memory management.
- **D-MEM** (Mar 2026): dopamine-gated memory via reward-prediction-error routing (bio-inspired).
- **Jev-Mem** (Sep 2026): System-1 (fast/intuitive) controlled memory to cut latency — early stage, low discussion volume.
- **A-MemGuard**: proactive defense against memory poisoning — directly relevant to our quarantine design.
- **AgentSys** (Feb 2026): OS-inspired hierarchical memory with explicit isolation.
- Microsoft's **SkillOpt**: updates agent skills in text-space from feedback without retraining weights — no fine-tuning regression.

**6. The security angle is now a subfield [HC]**
Memory poisoning has its own papers (A-MemGuard) and frameworks (SSGM for governing evolving memory). Our quarantine gate (tool/web → quarantined, never auto-acted on) is ahead of most open-source frameworks here — keep it, and add A-MemGuard's patterns to the threat model.

## What JARVIS should implement

1. **Add TTL + confidence decay to the write path** — the single biggest validated gap. Memories should carry `expires_at` and a confidence that decays without reinforcement. [Priority: high]
2. **Study Zep/Graphiti's temporal model** (Apache 2.0 — borrowable): validity intervals on facts ("what was true at time T?"). Implement a light version in our episodic store. [Priority: medium]
3. **Explicit conflict resolution on write**: when a new fact contradicts a stored one, don't silently overwrite — version it (we do) AND surface the conflict. The wiki synthesis says this is what separates working from broken memory. [Priority: medium]
4. **Watch, don't build**: AtomMem/Memory-R1 (learned memory policies) and Jev-Mem (System-1 memory) — revisit in 6 months. [Priority: low]
5. **Borrow A-MemGuard patterns** into the threat model for memory poisoning. [Priority: medium]

## Confidence notes
- [VC] = RAG≠memory, unguarded-wiki failure mode (systematic review + multiple sources)
- [HC] = five layers, framework ranking, T1/T2/T3 taxonomy, security subfield (well-sourced, some vendor claims discounted)
- [MC] = individual 2026 papers (early-stage, low discussion volume — interesting, unproven)
