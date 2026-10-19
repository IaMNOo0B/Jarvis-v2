# Knowledge Provenance Audit — §18 artifact #11 / §28

*PHASE INFINITY, Research Cycle 13. Audit date: 2026-10-19. Method: 5 parallel adversarial auditors (opposition squad), read-only, all 37 `learn-*.md` files read in full. This file is the synthesis; per-file detail lives in the auditors' reports (delivered to parent, not persisted). NOTHING was rewritten — audit only.*

*Auditor's honesty note: 2026-era arXiv IDs were format-checked, not registry-verified, except three checked live by one auditor (2609.22138 ✓ real, 2610.11605 ✓ real, 2608.28433 ✗ mismatch — see C4). Classic citations (Pearl, Tian, Schneier, Simon, Cover & Thomas) were verified against training knowledge. Hand-recomputed: Wilson CIs, INT8 VRAM arithmetic, KV-cache formula, rank-score factorization, SE arithmetic — all check out unless flagged.*

---

## 1. Provenance table

| File | Date | Topic | Tags? | Citation health | Staleness risk | Contradictions |
|---|---|---|---|---|---|---|
| learn-advanced-cs.md | 2026-10-19 | Event sourcing lite, CQRS rejected, durable queue, fault domains | ✓ [VC/HC/MC] | Good (official docs); 3 soft claims flagged | Prompt-cache pricing → 2027-01 | None |
| learn-backend.md | 2026-10-19 | FastAPI, OAuth/PKCE, SSE-vs-WS, queues, webhooks, reliability | ✓ best-in-class granularity | Strong (RFCs, official docs); 3 minor flags | APScheduler 4.x, OAuth policy → 2027-01 / build time | **TENSION: SSE-vs-WS vs frontend** (T1) |
| learn-databases.md | 2026-10-19 | SQLite verdict, vector DBs, hybrid search, chunking, RAG eval | ✓ [HC/MC] honest downgrades | Mixed; false-precision on community benches; 2 unattributed stats | Q1-2026 benches, lib versions → 2027-04 | None |
| learn-frontend.md | 2026-10-19 | React streaming, voice UI, consent research, Tauri verdict, signing | ✓ %→tags | Weakest §3/§6: 65-researcher claim via blog; unsourced prices | Signing policy/price → build time; SDK churn → build time | **TENSION: WS-later vs backend SSE** (T1) |
| learn-multimodal.md | 2026-10-19 | Grounding limits, OCR, tree-first, doc understanding, cost math | ✓ [HC/MC] | Good; ceiling numbers perishable; 1 unverifiable release claim | Model scores, vision pricing → 2027-01 | None |
| learn-observability.md | 2026-10-19 | OTel data-model, structlog, metrics, health, profiling, crash recovery | ✓ [HC/MC] | Good; rhetorical numbers labeled as such | Lib versions → build time | None |
| learn-phase2-ledger.md | 2026-10-19 | Phase 2 coverage audit (SKIP/GAP/NEW) | ✗ (status tags; appropriate) | N/A (index) | **Bookkeeping rot** — update on phase completion | None |
| learn-continual-learning.md | 2026-10-19 | CL methods, RAG-vs-FT verdict, contamination, eval recipe | ✓ exemplary granularity | Best hygiene + 1 verified canary; 4 single-source numbers | Method rankings → 2027-04 | None |
| learn-formal-methods.md | 2026-10-19 | Contracts, TLA+ LATER, Hypothesis, replay, chaos, supply chain, red-team | ✓ [HC/MC/VC] | Mixed; 2 unattributed test stats | Tooling versions → 2027-01 | None |
| learn-frontier-reasoning.md | 2026-10-19 | Search reasoning, belief-state, causal lite, neuro-symbolic, 8-strategy table | ✓ [HC/MC] | Mixed; RE-IMAGINE 20% uncited; weak liner.com source | Low; ≥90% threshold → replicate by 2027-01 | None |
| learn-inference-frontiers.md | 2026-10-19 | Attention/KV math, quant calibration, measurement framework, prefill/decode | ✓ full system | Mixed; 2601.14277 dual-attributed; Qwen3.6/3.8 inconsistency | llama.cpp CLI, shortlist → build time | None (reinforces (a)) |
| learn-research-frontiers.md | 2026-10-19 | World models, process supervision, interpretability, self-reflection, scaling | ✓ [VC/HC/MC] | **Weakest**: H-JEPA, 400-paper survey, vendor spreads uncited | Field-status → 2027-01 | None |
| learn-omega-ledger.md | 2026-10-19 | OMEGA Rule Zero audit (L1–L5) | ✗ (self-assessed L3/L4 — see note) | N/A | **Stale-by-completion** — needs "landed" update | None |
| learn-frontier-architectures.md | 2026-10-19 | Mamba/SKIP, hybrid/WATCH, sparse/SKIP, RETRO/SKIP, RAG/ADOPT, dLLM/SKIP | ✓ [VC/HC/MC] | Strongest IDs; 2 unsourced industry stats | Checkpoint availability → quarterly | None (reinforces (g)) |
| learn-math-for-jarvis.md | 2026-10-19 | Info theory, Bayes, VoI, game-lite, optimization, calibration | ✓ [VC/HC] conservative | Strong (textbooks); 1 unsourced Google claim | Negligible | None |
| learn-privacy-engineering.md | 2026-10-19 | Data lifecycle, deletion verification, DP verdict, consent, sync | ✓ +[UK] | Good; specific sources; honest [UK]s | CRDT maturity → when sync is real | None |
| learn-evaluation-science.md | 2026-10-19 | Experimental design, stats validity, human eval, 18-metric scorecard | ✓ [VC/HC/MC] | Strong core (math hand-verified); weak tail | Negligible (methods); thresholds per governance | None |
| learn-open-problems.md | 2026-10-19 | 50 JARVIS + 18 field problems ranked | ✓ full system | Honest (adds none) | **"Pending researchers" section stale** — update now | Tension: LoRA-vs-(g) boundary unwritten (T6) |
| learn-lifetime-ledger.md | 2026-10-19 | A–O taxonomy audit, Rules 1–12 analysis | ✗ (7-status; appropriate) | N/A | **Bookkeeping rot** — A–O table already stale (control theory "Missing" now delivered) | None |
| learn-ai-for-se.md | 2026-10-19 | SWE-bench critique, codegen ladder, correctness gates, debug limits | ✓ [VC/HC/MC/UK] | Mixed; leaderboard figures unsourced; 1 self-corrected misquote (+) | Leaderboards → 2027-01-19 | None (reinforces (e)(f)(i)) |
| learn-control-theory.md | 2026-10-19 | Feedback loops, PID governors, stability, Kalman SKIP, cascade control | ✓ [VC/HC/UK] | Good (textbook); no suspicious numbers | Negligible (theory) | None |
| learn-accessibility.md | 2026-10-19 | WCAG 2.2 checklist, WebView2/UIA symmetry, voice double-edge, testing | ✓ heaviest tagging | Good; population stats unsourced (WHO-plausible) | WebView2/axe versions → 2027-04-19 | None |
| learn-infinity-ledger.md | 2026-10-19 | §20 audit, Q1–Q3 research plan, evidence standards | ✗ (evidence-specs instead of tags) | N/A | **Cycles 1–3 now complete** — mark landed now | None |
| learn-underspecification.md | 2026-10-19 | U1–U6 taxonomy, signals, ask/act/escalate rule, 30-task golden set | ✓ all five tags | Good; 2026 preprints format-plausible; labels self-flagged unvalidated | Preprints → 2027-04-19; labels → inter-rater check | Design tension noted, resolved in-file (T7) |
| learn-bayesian-design.md | 2026-10-19 | BoED vs BO, scale-threshold table, registry template | ✓ [VC/HC/MC/UK] | Good; competition-derived figure caveated | Event-driven (benchmarking weekend) | None |
| learn-smt-verification.md | 2026-10-19 | Z3 on 5 constraints; ADOPT C2-in-CI only | ✓ [VC/HC/SP/UK] | Good; **load-bearing arXiv 2312.04586 unverified by auditor** | Z3 string-solver → CI pin time | None |
| learn-fault-trees.md | 2026-10-19 | Approval-gate FTA, 10 cut sets, 8 SPOFs, mitigations | ✓ all five tags | Good; refuses false precision (+) | Design-dependent, not time-dependent | None (reinforces (i)) |
| learn-attack-trees.md | 2026-10-19 | Adversarial companion to FTA; cost-ordered paths | ✓ every claim tagged | Good; **"2026 consent finding" unattributed** (load-bearing for Rank 1) | Low | None |
| learn-bounded-rationality.md | 2026-10-19 | Satisficing controller, 3-gate monitor, budget matrix, anytime map | ✓ cleanest discipline | Good; hedged secondary numbers | Low–medium; router figures → shootout | None |
| learn-benchmark-spec.md | 2026-10-19 | Benchmarking-weekend runbook, 6 tracks, UNEXECUTED | ✓ +[EST]/[MEA] | Good; figures traceable | **Highest**: env pins perishable; re-pin at run time | **CONTRADICTION: Track F ≥0.85 vs Cycle 7 ≥0.90** (C1); **Track F vs DISC-100 duplication** (D4) |
| learn-discriminator-protocol.md | 2026-10-19 | DISC-100 spec, D1–D5 design, gating rule | ✓ [VC/HC/MC/SP] | Good; **MATH ERROR §3.3** (C3) | Low | **CONTRADICTION: gate bar vs benchmark-spec** (C1) |
| learn-hinglish-golden.md | 2026-10-19 | 50-task Hinglish golden-set methodology | ✓ +unknowns | Good; 2609.22138 **verified live** ✓ | Low (quarterly refresh built in) | None |
| learn-causal-discovery.md | 2026-10-19 | PC/FCI/Granger verdicts, feasibility analysis | ✓ +Rule-12 report | Good (theorems check out) | Negligible | None |
| learn-program-synthesis.md | 2026-10-19 | DreamCoder/Lean scoping; SKIP machinery, WATCH checkers | ✓ [VC/HC/MC] | **CITATION MISMATCH: 2608.28433** (C4); AlphaProof no URL | Product claims → 6 months | None |
| learn-self-verification-calibration.md | 2026-10-19 | 5-rung self-judge gradation; study design (UNRUN) | ✓ +[DESIGN] | **Weakest 2026 layer**: 2609.28564 date/ID mismatch; 3 uncited number-sets | Rung hypotheses → when study runs | None (reinforces anti-self-correction) |
| learn-reliability-spec.md | 2026-10-19 | Unified SLOs, error budgets, degradation ladder (§18 #10) | Partial ([DERIVED]/[PROPOSED] — better practice, divergent vocab) | Internal only; telephony 2s unsourced | Targets unmeasured → 2027-01-19 or benchmarking weekend | None |
| learn-threat-model.md | 2026-10-19 | Unified threat model (§18 #9); 7 uncovered + 9 partial cells named | ✓ [MC/HC/VC/UK] | Good; "2026 consent research" unattributed; test counts internal-only | Low; supply-chain per release | None |

*Positions key: (a) Qwen2.5-7B sweet spot / Q4_K_M floor / never q4_0 · (b) SQLite WAL + Chroma · (c) Tauri > Electron · (d) UIA-tree-first · (e) external ground truth > introspection · (f) self-correction degrades · (g) RAG > fine-tuning; never fine-tune a fact · (h) no CQRS/K8s/Kafka · (i) never brain-reviews-own-plan · (j) ≥90% discriminator gates tree search.*

---

## 2. Contradiction list (with resolutions)

### C1. Discriminator gate bar: ≥0.90 (Cycle 7) vs ≥0.85 (Cycle 9 Track F) — REAL
- **Claim A** (learn-discriminator-protocol.md §5, indexed MASTER-INDEX F12): tree search enabled only if `min(wilson_lo, worst_safety_stratum_lo) ≥ 0.90`.
- **Claim B** (learn-benchmark-spec.md Track F): `lower bound of 95% CI ≥ 0.85 → ENABLED`.
- **Resolution: adopt A.** Stricter, better-justified (worst-stratum gating on safety-relevant strata), and already the indexed canonical rule. Track F must be edited to reference the Cycle 7 rule before the benchmarking weekend. [Audit action required — not done in this read-only pass.]

### C2. Streaming transport: SSE (backend) vs WebSocket-later (frontend) — REAL TENSION
- **Claim A** (learn-backend.md O3, [VC]): "SSE for token/progress streaming + REST for commands; WebSockets earn their complexity only for continuous two-way traffic."
- **Claim B** (learn-frontend.md §1): "WebSocket later for token streaming and pushed events."
- **Resolution: recommend A as default** (broader source consensus, simpler ops, matches the Tauri sidecar localhost-HTTP architecture), with WS reserved for a future continuous two-way need. Needs a single design-phase ruling recorded in DECISION-PLAYBOOK.md. [Audit action required.]

### C3. Math error in learn-discriminator-protocol.md §3.3 — REAL
- **Claim:** "141/150 (94%) clears the 0.90 Wilson lower bound."
- **Fact:** 141/150 → Wilson LB ≈ 0.890 (does not clear); 142/150 → ≈0.898 (still under); ≈143/150 (95.3%) clears at ≈0.907. Hand-recomputed by auditor.
- **Resolution:** correct to 143/150. Material because the error straddles the very bar being discussed. [Audit action required.]

### C4. Citation mismatch in learn-program-synthesis.md — REAL
- **Claim:** "~43% of AI-proved Lean statements faithfully encode the intended claim (Bourigault et al. 2026)" linked to arXiv:2608.28433.
- **Fact:** 2608.28433 is the Prove2Me platform paper (verified live); its abstract says nothing about a faithfulness study.
- **Resolution:** find the actual Bourigault citation or downgrade the claim to unattributed-single-source. [Audit action required.]

### C5. Date/ID mismatch in learn-self-verification-calibration.md — REAL
- **Claim:** "Don't Read the Log… (arXiv:2609.28564, 2025)."
- **Fact:** ID prefix 2609 = September 2026, not 2025. One is wrong.
- **Resolution:** verify the ID against arXiv; correct whichever is wrong; the attached precision numbers (78–90%, 0.69 false accepts) inherit the doubt until then. [Audit action required.]

### C6. LoRA-vs-(g) boundary unwritten — TENSION TO WATCH
- **Position (g):** "never fine-tune a fact."
- **Open items** (learn-open-problems.md #11–#13): LoRA adapters for tool-calling *skills*.
- **Resolution:** no file contradicts (g) today, but the boundary is load-bearing and unwritten. Canonical statement to add: *adapters for procedures ≠ fine-tuning facts; weights may encode how, never what.* [Audit action required — one sentence in DECISION-PLAYBOOK.md.]

### C7. Ledger arithmetic in learn-open-problems.md — MINOR
- **Claim:** "50 JARVIS-level items (44 measurements + 6 legal/supply-chain tasks)."
- **Fact:** listing shows #1–#48 measurement + #49–#50 legal = 48+2.
- **Resolution:** fix the count line. [Audit action required.]

### C8. Qwen3.6 vs Qwen3.8-27B in learn-inference-frontiers.md — MINOR
- §2 cites "Five Qwen3.8-27B quants"; Key References say "Quesma Qwen3.6-27B study." Same study, two version numbers.
- **Resolution:** reconcile to one version number. [Audit action required.]

### C9. Underspecification design tension (T7) — NOTED, RESOLVED IN-FILE
- Step 4 (brain enumerates interpretations) vs §2.4 (don't rely on brain's self-reported uncertainty). File resolves via structural slot-checking as primary signal + [SP] tag. No action beyond the existing flag.

**Net: 2 real contradictions (C1, C2), 1 math error (C3), 2 citation defects (C4, C5), 4 minor/hygiene items (C6–C9). Zero contradictions against the 10 established doctrinal positions — the knowledge base is internally coherent on doctrine.**

---

## 3. Staleness register

| Claim / file | Type | Re-verify by |
|---|---|---|
| Signing price/policy, SmartScreen behavior (frontend §6) | price/policy | **at build time** |
| Vercel AI SDK API surface (frontend §1) | API churn | at build time |
| llama.cpp CLI surface, model shortlist (inference-frontiers) | tooling | at build time |
| Benchmark-spec env pins (drivers, CUDA, commit hashes) | perishable procedure | **re-pin at run time** |
| Google OAuth desktop-app policy (backend) | policy | at build time |
| APScheduler 3.x→4.x (backend) | version | 2027-01 |
| Prompt-cache TTL/pricing (advanced-cs) | pricing | 2027-01 |
| Grounding-model scores, vision pricing (multimodal) | benchmarks/prices | 2027-01 |
| Research-frontier field status (H-JEPA, interpretability timelines) | field | 2027-01 |
| Formal-methods tooling, OWASP rankings | tooling | 2027-01 |
| AI-for-SE leaderboards, contamination claims | benchmarks | 2027-01-19 |
| Databases Q1-2026 benches, Chroma/Qdrant versions | benchmarks/versions | 2027-04 |
| Continual-learning method rankings | benchmarks | 2027-04 |
| Accessibility WebView2/axe-core versions | versions | 2027-04-19 |
| Reliability-spec numeric targets (all [PROPOSED]) | unmeasured specs | 2027-01-19 or benchmarking weekend |
| Frontier-architectures checkpoint availability | availability | **quarterly** |
| Program-synthesis 2026 product claims | product news | 6 months |
| Underspecification preprints (2601.06407, 2511.08798) | preprints | 2027-04-19 |
| Underspecification golden-set labels | unvalidated labels | inter-rater check before first eval use |
| Bayesian-design cost estimates | unmeasured estimates | benchmarking weekend |
| **Ledgers (phase2/omega/lifetime/infinity): "pending/dispatched" states** | **bookkeeping rot** | **now** — mark cycles landed |
| open-problems.md "What this map does NOT cover" | stale section | now — the four studies exist |

---

## 4. Duplication list

| Overlap | Files | Verdict |
|---|---|---|
| SQLite-WAL durability rationale | advanced-cs §1/§3, backend O4, databases T1 | **Worst case.** Same argument 3×. Canonicalize: keep databases T1 as the decision record; others cross-link. |
| Idempotency-key / outbox pattern | advanced-cs §3, backend O6, observability §6 | Merge to one canonical treatment (backend O6 is deepest); cross-link. |
| Golden-set / holdout / canary machinery | databases T5, continual-learning §4 | Keep both lenses (retrieval metrics vs contamination) but add cross-links. |
| Cohen's κ / Bradley-Terry / n=1 rater | research-frontiers §7, evaluation-science §§3.1–3.3 | **Canonical: evaluation-science.** Mark research-frontiers §7 superseded-by. |
| SSE-vs-WS trade-off | backend O3, frontend §1 | Resolve per C2, then single canonical treatment. |
| Coverage ledgers | lifetime-ledger, infinity-ledger, MASTER-INDEX | **Canonical: MASTER-INDEX.** Ledgers become phase audit trails; update statuses. |
| Reliability-spec vs observability/advanced-cs/fault-trees/eval-science | reliability-spec (unification) | **By design.** Add "superseded-by" pointers in source sections to prevent edit-drift. |
| Threat-model vs fault-trees/attack-trees/FAILURE-ANALYSIS | threat-model (unification) | **By design.** Complementary angles; add merge notes. |
| open-problems "pending researchers" vs omega-ledger dispatch | open-problems, omega-ledger | Stale duplicate — update both. |
| benchmark-spec Track F vs discriminator-protocol DISC-100 | benchmark-spec, discriminator-protocol | **Inconsistency, not just duplication.** Track F must reference DISC-100 (see C1). |

---

## 5. Quality verdicts

**Rock-solid (cite freely):** learn-privacy-engineering.md · learn-control-theory.md · learn-causal-discovery.md · learn-evaluation-science.md (quantitative core) · learn-fault-trees.md · learn-math-for-jarvis.md
**Strong with flagged specifics (cite with the flags):** learn-backend.md · learn-continual-learning.md · learn-databases.md · learn-frontier-architectures.md · learn-inference-frontiers.md · learn-observability.md · learn-multimodal.md · learn-formal-methods.md · learn-frontier-reasoning.md · learn-bounded-rationality.md · learn-hinglish-golden.md · learn-underspecification.md · learn-bayesian-design.md · learn-smt-verification.md · learn-attack-trees.md · learn-threat-model.md · learn-accessibility.md · learn-ai-for-se.md · learn-program-synthesis.md · learn-discriminator-protocol.md (after C3 fix) · learn-bayesian-design.md · learn-reliability-spec.md (as spec, not fact)
**Needs re-verification before citation (do not quote numbers):** learn-research-frontiers.md (citation-thin 2026 specifics) · learn-self-verification-calibration.md (§3.1–§3.3 number-sets)
**Ledgers (living documents — update, don't cite as fact):** learn-phase2-ledger.md · learn-omega-ledger.md · learn-lifetime-ledger.md · learn-infinity-ledger.md · learn-open-problems.md (pending section)

**Top citation debt (unattributed claims appearing in ≥2 files):** the "65-researcher Google-led 2026 consent study" (frontend §3, math-for-jarvis §4, open-problems #10, attack-trees §3 as "2026 consent finding") — four files, zero primary attribution. Find the primary report or downgrade everywhere.

---

## 6. Audit limitations (my own)

- 2026-era arXiv IDs were format-checked, not registry-verified (3 checked live by one auditor). A full arxiv.org existence sweep of the ~15 26xx IDs is the obvious next verification step.
- Auditors did not re-read cross-referenced non-learn files (FAILURE-ANALYSIS.md, DECISION-PLAYBOOK.md, MASTER-INDEX.md, hardened_runner.py); internal-reference claims bottom out there unverified.
- No auditor had network access to verify provider pricing, PyPI package existence, or 2026 product claims.
- The audit is read-only by design: **9 items need edits** (C1–C8 + duplication canonicalization). None were made.

## 7. Recommended next actions (for parent)

1. Fix C1 (discriminator gate bar → ≥0.90 everywhere) and C3 (143/150) — both gate the benchmarking weekend.
2. Rule on C2 (SSE default) and record in DECISION-PLAYBOOK.md.
3. Add the C6 one-liner (adapters-for-procedures ≠ fine-tuning-facts) to DECISION-PLAYBOOK.md.
4. Fix C4/C5 citations or downgrade the claims.
5. Update the four ledgers + open-problems pending section (bookkeeping rot is the #1 staleness vector).
6. Run the arxiv.org existence sweep on 26xx IDs.
7. Add "superseded-by" pointers for the unification files (reliability-spec, threat-model).

---

## 8. Cycle 18 corrections applied (2026-10-19)

*All 9 §7 items resolved. Minimal edits only — defects fixed, no rewrites.*

**C1 — discriminator gate bar:** `learn-benchmark-spec.md` Track F decision rule changed from `lower bound of 95% CI ≥ 0.85` to the canonical Cycle 7 rule: gate on `min(wilson_lo, worst_safety_stratum_lo) ≥ 0.90`, with the supersession noted inline. Added Track F item 5: build the pair set from DISC-100 rather than inventing a new instrument (duplication D4 resolved).

**C2 — streaming transport:** ruled in `DECISION-PLAYBOOK.md` as new calibrated entry **A9**: SSE for streaming by default; WebSocket only if continuous two-way traffic is needed. "What would change my mind" recorded.

**C3 — math error:** `learn-discriminator-protocol.md` §3.3 corrected with code-computed Wilson bounds: 141/150 → LB 0.8899 (under), 142/150 → LB 0.8983 (under), **143/150 → LB 0.9068 (clears)**. The bar needs ≈143/150 (95.3%), not 141/150. Correction note left inline.

**C4 — citation mismatch:** `learn-program-synthesis.md` — the "Bourigault et al. 2026 / ~43%" claim linked to arXiv:2608.28433 (Prove2Me platform paper, unrelated) was removed as unattributable. Replaced with verified support for the (real) faithfulness gap: arXiv:2606.31002 "Beyond Compilation" + Bastounis/Circelli/Hansen (Oct 2026). Watch-trigger 2 and confidence section updated to match; references section now lists all three sources honestly.

**C5 — date/ID mismatch:** `learn-self-verification-calibration.md` — arXiv:2609.28564 verified live as real: "Don't Read the Log" (Jian Xu, submitted Sep 23, 2026). Year corrected 2025 → 2026 in both §3 and the §8 table; the 78–90% / 0.69 figures confirmed in the abstract.

**Citation debt — the 65-researcher study:** primary source FOUND and verified: Google Research (2026), *"Open and Emergent Problems in Agentic Privacy and Security: A Contextual Angle"* — 65 authors (36 Google-affiliated), from the CAPS Workshop (NYC, Nov 2025); research blog post Oct 5, 2026 (Bagdasarian & Gruteser). Open Problem 9.2 = the notice-and-choice finding. Attribution added to all 4 files: `learn-frontend.md` §3 (+ references line), `learn-math-for-jarvis.md` §4, `learn-open-problems.md` #10, `learn-attack-trees.md` §3.

**Ledger staleness:** all four ledgers marked landed — `learn-phase2-ledger.md` (5/5), `learn-omega-ledger.md` (5/5), `learn-lifetime-ledger.md` (3/3 + taxonomy rows A/N updated), `learn-infinity-ledger.md` (Cycles 8–18 recorded; the stale "Cycle 8 = Assistance games" entry corrected — it never landed). `learn-open-problems.md` "pending researchers" section → all four landed.

**Duplication canonicalization:** `learn-research-frontiers.md` §7 marked — κ/Bradley-Terry/n=1 canonically owned by `learn-evaluation-science.md`; `learn-fault-trees.md` and `learn-advanced-cs.md` got unification pointers to `learn-threat-model.md` / `learn-reliability-spec.md`.

**C6:** one-liner added to `DECISION-PLAYBOOK.md` as **A0**: "Adapters encode procedures, never facts. LoRA adapters may encode *how*; weights must never encode *what*."

**C7:** `learn-open-problems.md` count line fixed to 48 measurements + 2 legal (was 44+6), correction noted inline.

**C8:** `learn-inference-frontiers.md` reconciled to Qwen3.8-27B in both §2 and Key References (was 3.6 in one place).

**Remaining from §7 (not done — needs parent decision or a sweep task):** item 6, the full arxiv.org existence sweep on all ~15 26xx IDs (only 3 verified live this cycle: 2609.22138 ✓, 2610.11605 ✓, 2609.28564 ✓, plus 2606.31002 found real).

---

## ArXiv sweep (Cycle 29) — 2026-10-19

*The §7 item 6 leftover, now complete. Method: grepped all `learn-*.md` for `26xx.xxxxx` IDs (22 unique), skipped the 4 already verified live (2609.22138, 2610.11605, 2609.28564, 2606.31002), fetched `arxiv.org/abs/<id>` for each remaining 18 and compared title/authors against the citing file's claim. Read-only for the knowledge base: citing files NOT edited — flags only.*

### Clean verifications (16)

| ID | Actual title (arXiv) | Citing file(s) | Claim | Verdict |
|---|---|---|---|---|
| 2601.02574 | Fact-Checking with Large Language Models via Probabilistic Certainty and Consistency (PCC) | learn-claim-verification.md | confidence-guided per-claim verification | ✓ matches |
| 2601.06407 | Value of Information: A Framework for Human-Agent Communication | learn-underspecification.md, learn-asking-economics.md | NetVoI(q) = VoI(q) − c | ✓ matches |
| 2601.08955 | Imagine-then-Plan: Agent Learning from Adaptive Lookahead with World Models (ITP) | learn-research-frontiers.md | "mental sandbox" agents | ✓ matches |
| 2601.14277 | Which Quantization Should I Use? A Unified Evaluation of llama.cpp Quantization on Llama-3.1-8B-Instruct | learn-inference-frontiers.md | PPL ≠ task accuracy | ✓ matches |
| 2601.15209 | Deaf and Hard of Hearing Access to Intelligent Personal Assistants (LLM-powered touch interface) | learn-accessibility.md | DHH access study | ✓ matches |
| 2601.20913 | Noisy but Valid: Robust Statistical Evaluation of LLMs with Imperfect Judges | learn-self-verification-calibration.md | judge TPR/FPR from small holdout | ✓ matches |
| 2603.18353 | Interpretability without actionability: mechanistic methods cannot correct language model errors despite near-perfect internal representations | learn-research-frontiers.md | 4 methods, <25% errors corrected | ✓ matches |
| 2603.21454 | Cross-Context Verification: Hierarchical Detection of Benchmark Contamination through Session-Isolated Analysis | learn-continual-learning.md | N independent sessions, solution diversity | ✓ matches |
| 2604.22273 | Self-Correction as Feedback Control: Error Dynamics, Stability Thresholds, and Prompt Interventions in LLMs | learn-ai-for-se.md | EIR study, verify-first prompting | ✓ matches |
| 2605.03546 | ProgramBench: Can Language Models Rebuild Programs From Scratch? | learn-ai-for-se.md | repo-build benchmark rung | ✓ matches |
| 2605.07363 | MISA: Mixture of Indexer Sparse Attention for Long-Context LLM Inference | learn-frontier-architectures.md | MoE-routed indexer heads | ✓ matches |
| 2607.09510 | Failure as a Process: An Anatomy of CLI Coding Agent Trajectories | learn-continual-learning.md | epistemic errors dominate | ✓ matches (identity; "1,184 trajectories" figure not in abstract — PDF check if the number is ever quoted) |
| 2608.12812 | A Comprehensive Empirical Evaluation of Vector Database Systems for Approximate Nearest Neighbor Search | learn-databases.md | empirical ANN evaluation | ✓ matches |
| 2608.27508 | WM-R1: Training GUI Agents to Reason and leverage World Models with Reinforcement Learning | learn-research-frontiers.md | RL inside world model | ✓ matches |
| 2608.28433 | Prove2Me: An Open Collaborative Platform for Scaling Math Formalization | learn-program-synthesis.md | (none — already corrected in Cycle 18; retained for DreamCoder-adjacent context only) | ✓ exists; correction stands |
| 2610.19709 | Beyond State Capacity: Why Retrieval Breaks in Mamba | learn-frontier-architectures.md | retrieval breaks beyond state capacity | ✓ matches |

### 🚨 FLAG 1 — wrong citation (loud)

**`2601.0892` in `learn-ai-for-se.md`:** the file cites "Tsui et al. 2026 preprint (Self-Correction Blind Spot, preprints.org 202601.0892)". The arXiv ID 2601.0892 resolves to **arXiv:2601.00892 — "Hierarchical topological clustering" (Carpio & Duro)**, a mathematics paper about topological data clustering — completely unrelated to self-correction. The string "202601.0892" is a **preprints.org article ID, not an arXiv ID**; it was misread as one. The cited "Self-Correction Blind Spot" paper by Tsui et al. was NOT located on arXiv under this ID. **Action needed:** either find the real Tsui et al. preprint (correct venue/ID) or downgrade the claim. Do not quote this citation until fixed.

### ⚠️ FLAG 2 — partial match (needs PDF-level check)

**`2603.11619` in `learn-memory-write-gate.md`:** the file calls it "PMPA (Persistent Memory Poisoning Attack)" with figures 73.7%/66.9% ISR and 55.5%/81.7% cross-session ASR on OpenClaw/Claude Code. The actual paper is **"Taming OpenClaw: Security Analysis and Mitigation of Autonomous LLM Agent Threats" (Deng et al., cs.CR)** — a security analysis of OpenClaw whose abstract explicitly lists memory poisoning among the threats examined. So: the paper EXISTS, is on-topic (OpenClaw + memory poisoning), but the "PMPA" name and the specific figures are NOT in the title/abstract and could not be confirmed without the PDF. **Action needed:** PDF-level check to confirm the PMPA name and figures; if absent, relabel the citation to the paper's actual framing.

### Tally

22 unique 2026 arXiv IDs cited across the knowledge base. **20 verified clean** (16 this cycle + 4 previously), **1 partial** (2603.11619 — exists, on-topic, figures unconfirmed), **1 wrong** (2601.0892 — unrelated paper; preprints.org ID misread as arXiv). No fabricated IDs — every ID resolves to a real arXiv paper; the failure mode was misattribution, not invention. The §7 item 6 sweep is now COMPLETE.
