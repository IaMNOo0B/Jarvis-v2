# OMEGA Coverage Ledger — Rule Zero Audit (2026-10-19)

Principle: treat previous mastery claims as claims to audit. Five mastery levels (L1 awareness → L5 research competence).

## PART II — Scientific Foundations
| § | Topic | Status | Note |
|---|---|---|---|
| 4 | Mathematics for AI (info theory, Bayes, decision/game theory, optimization) | **NEW** | Never systematically studied. Scoped: only math that genuinely affects JARVIS decisions. → researcher 1 |
| 5 | Computational complexity | SKIP (L3) | Big-O/amortized covered in coding sprint; planning complexity in reasoning study |

## PART III — Frontier AI Research
| § | Topic | Status | Note |
|---|---|---|---|
| 6 | Reasoning/search/planning | SKIP (L4) | learn-frontier-reasoning.md (8-strategy table, verifier-first) |
| 6 | Value-of-information, anytime algorithms, stopping criteria | GAP | Small — fold into researcher 1 (decision theory covers VoI) |
| 7 | Continual learning, RL distinctions, contamination | SKIP (L4) | learn-continual-learning.md |
| 7 | Meta-learning limits, model collapse/recursive training | GAP | Small — fold into researcher 5 (open problems) |
| 8 | Attention, quantization, inference | SKIP (L4) | learn-inference-frontiers.md, rtx-2060-guide |
| 8 | State-space models (Mamba), sparse compute, retrieval-augmented models | **NEW** | → researcher 2 |
| 9 | World models, process supervision, interpretability, self-reflection limits | SKIP (L4) | learn-research-frontiers.md |
| 9 | Human-AI collaboration, alignment under changing objectives, agent autonomy eval | GAP | Small — fold into researcher 5 |

## PART IV — Complete JARVIS System
| § | Topic | Status | Note |
|---|---|---|---|
| 10 | Cognitive architecture (model vs deterministic vs human decisions) | SKIP (L4) | Anthropic decoupling, Conscio, formal-methods meta-rule |
| 11 | Memory governance | SKIP (L4) | mem0/Letta/A-MEM/cog, ECAN, provenance |
| 12 | Long-horizon execution | SKIP (L4) | learn-advanced-cs.md (durable queue, idempotency, fault domains) |
| 13 | Multi-agent systems | SKIP (L3) | Multi-agent crew built; correlated failures in frontiers study |
| 14 | Real-time multimodal | SKIP (L4) | learn-multimodal.md |
| 15 | Personalization/HCI | SKIP (L3) | learn-frontend.md (approval UX), preference provenance doctrine |

## PART V — Engineering
| § | Topic | Status | Note |
|---|---|---|---|
| 16 | Formal methods | SKIP (L4) | learn-formal-methods.md (use/skip/later verdicts) |
| 17 | AI security | SKIP (L4) | hardened_runner.py, FAILURE-ANALYSIS, R2/R9 |
| 18 | Reliability/distributed | SKIP (L4) | learn-advanced-cs.md, learn-observability.md |
| 19 | Privacy & data lifecycle | **GAP** | Partial (R9/R13). Missing: differential privacy, deletion verification, lifecycle model → researcher 4 |

## PART VI — Evaluation
| § | Topic | Status | Note |
|---|---|---|---|
| 20 | Experimental design | GAP | Ablation covered; full design discipline missing → researcher 3 |
| 21 | Benchmarking & statistical validity | GAP | Contamination covered; power/CI/multiple-comparisons missing → researcher 3 |
| 22 | Integrated JARVIS scorecard | **NEW** | Never built → researcher 3 (deliverable) |

## PART VII — Computing
| § | Topic | Status | Note |
|---|---|---|---|
| 23 | Hardware-aware intelligence | SKIP (L4) | rtx-2060-guide, inference-frontiers |
| 24 | Performance engineering | SKIP (L3) | Profiling in learn-observability.md |

## PART VIII — Discovery
| § | Topic | Status | Note |
|---|---|---|---|
| 25 | Living research frontier | PROCESS | Set up as ongoing practice (this ledger + frontier watch) |
| 26 | Open-problem discovery | **SYNTHESIS** | Ranked unknowns exist across ~15 studies — synthesize into one map → researcher 5 |

## PART IX — Knowledge infrastructure
| § | Topic | Status | Note |
|---|---|---|---|
| 27-29 | Audit & improve my knowledge system | **ACTIONABLE** | Do directly after research lands: index new files in MASTER-INDEX, contradiction check, staleness markers |

## Dispatched (5 workers) — ALL LANDED 2026-10-19
1. **Math for JARVIS** (§4) → `learn-math-for-jarvis.md` ✓ (6 decision-relevant ideas: info theory, Beta-Bernoulli ledger, VoI, game-lite, optimization, calibration)
2. **Frontier architectures** (§8 gaps) → `learn-frontier-architectures.md` ✓ (Mamba SKIP, hybrid WATCH, RAG ADOPT, dLLM SKIP)
3. **Evaluation science** (§20-22) → `learn-evaluation-science.md` ✓ (18-metric scorecard, 7 release gates, Wilson/Holm discipline)
4. **Privacy engineering** (§19 gaps) → `learn-privacy-engineering.md` ✓ (data lifecycle, deletion verification, DP verdict: not needed)
5. **Open problems map** (§26) → `learn-open-problems.md` ✓ (50 JARVIS + 18 field unknowns, ranked)
