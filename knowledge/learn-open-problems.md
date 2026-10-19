# Open-Problem Discovery & Synthesis — Ranked Map (§26)

*Synthesized 2026-10-19 from ~15 prior studies' unknowns sections. LEARNING ONLY — no experiments run, no claims fabricated.*

## How to read this map

- **Two classes.** `FIELD` = open research problem (the literature moves slowly; resolve by tracking papers). `JARVIS` = engineering unknown measurable on Owais's machine (RTX 2060 6GB, Ryzen 5 3600, 16GB RAM; resolve by running the named experiment).
- **Rank score = importance × uncertainty × resolvability** (each 1–5). High score = do this first. A brilliant but unresolvable question ranks below a mundane but measurable one — that is deliberate.
- **Confidence tags:** [VC] >95% · [HC] 80–95% · [MC] 60–80% · [SP] 40–60% · [UK] unknown. The tag is on the *state-of-knowledge summary*, not the question.
- **Dedup note:** several studies independently surfaced the same unknown (e.g., Hinglish eval gaps appeared in 4 files). Each appears once, with all sources noted.

---

## TOP 10 — by rank score (the measurement backlog that unblocks v2)

### 1. The 2060 model shootout — which quant of which model keeps tool-calling accuracy? `JARVIS` · Score 100 · [HC]
- **Question:** For the shortlist (Qwen2.5-7B, Qwen3.5-4B/9B, …), which GGUF quant is the largest that (a) fits 6GB with KV headroom at 4k context and (b) keeps tool-call accuracy within noise of FP16?
- **State of knowledge:** Quantization damage is task-shaped: Llama-3.1-8B BFCL drops FP16 63% → q4_0 **20%** → q4_K_M 40% → q8_0 44%. Perplexity cannot predict the damage (identical PPL, different task scores). Q4_K_M is the hypothesized floor; custom imatrix from agent data is free upside. Nothing replaces running it. *(learn-inference-frontiers.md)*
- **Why it matters:** Every downstream decision (tier architecture, latency budget, voice-loop feasibility) depends on the actual brain. Wrong pick = silent capability loss.
- **Resolution experiment:** Run the §3 shootout protocol: `llama-bench` (pp4096/tg256) + BFCL (native-FC interface, pinned version, multi-turn categories weighted) + a private agentic bench (own repos, injected bugs, hidden tests) on the actual 2060.
- **Sources:** learn-inference-frontiers.md, rtx-2060-guide.md

### 2. Measured difficulty distribution of Owais's real usage `JARVIS` · Score 100 · [MC]
- **Question:** What fraction of real tasks are trivial / standard / high-stakes? Where are the tier-routing thresholds?
- **State of knowledge:** Snell et al. (arXiv 2408.03314): adaptive per-question compute allocation is >4× more efficient than best-of-N; small model + test-time compute beats 14× larger models on easy problems. But the difficulty curve's crossover points are task-specific and **unmeasured for this user**. Difficulty estimation is itself hard. *(learn-research-frontiers.md)*
- **Why it matters:** Blocks the entire three-tier 2060 architecture and the reasoning-strategy router. Without the distribution, tier thresholds are guesses.
- **Resolution experiment:** Log 2–4 weeks of real usage (task type, latency, success); classify into tiers; measure a cheap difficulty classifier (tiny model / first-100-tokens heuristic) against human labels.

### 3. Discriminator accuracy on JARVIS's real tool set `JARVIS` · Score 80 · [HC]
- **Question:** Can an LLM judge (or cheap verifier) discriminate good from bad tool-call trajectories at ≥90% accuracy on JARVIS's actual tools?
- **State of knowledge:** Tree search needs ≥90% discriminator accuracy to beat simple re-ranking; LLM self-judges don't reach it; the *environment* as judge (unit tests, compilers, SQL execution) is when search gains +21–47% (LATS). The 90% number is from literature, not from JARVIS's tools. *(learn-frontier-reasoning.md)*
- **Why it matters:** Gates Strategies 3/4 (tree search / MCTS). Below 90%, search is expensive noise — worse than useless.
- **Resolution experiment:** Build 50 verifiable tool tasks; measure candidate judges (LLM-as-judge, schema checks, execution feedback) for discrimination accuracy.

### 4. Golden-set + LLM-judge reliability, especially Hinglish `JARVIS` · Score 80 · [HC]
- **Question:** Can we build a 50–100 task golden set from real usage, and does an LLM judge score Hinglish answers reliably (measured inter-rater agreement vs human)?
- **State of knowledge:** The recipe exists (dev/held-out split, canary GUIDs, quarterly refresh, judge-as-contract over verified artifacts). No benchmark exists for Hinglish tool-call accuracy; judge reliability on code-switched answers is unmeasured. Four studies independently flagged this gap. *(learn-continual-learning.md, learn-databases.md, learn-multimodal.md, learn-research-frontiers.md)*
- **Why it matters:** Without eval, every RAG/prompt/model change is a guess. The v1 autopsy proved it: bugs lived for months because nothing measured them.
- **Resolution experiment:** Collect real tasks → human-label → measure judge-vs-human agreement (Cohen's κ); spot-check Hinglish subset separately.

### 5. Grounding-model latencies on the 2060 (ShowUI-2B, Qwen2.5-VL-3B, PaddleOCR) `JARVIS` · Score 80 · [HC]
- **Question:** What are the real inference latencies of the vision stack on the 2060 — not derived from VRAM math?
- **State of knowledge:** ShowUI-2B is the 2060-friendly grounding pick (~2GB, 77.3% ScreenSpot-v2); Qwen2-VL-OCR-2B runs in llama.cpp; PaddleOCR most robust. All latency figures are derived estimates, explicitly marked unmeasured. *(learn-multimodal.md)*
- **Why it matters:** Determines whether the tree→OCR→grounding pipeline fits interactive latency, and whether the grounder can stay resident alongside the brain.
- **Resolution experiment:** Benchmark each on real screenshots on the card; measure with/without brain loaded (VRAM contention).

### 6. GPU budget partitioning: voice + brain on 6GB `JARVIS` · Score 80 · [HC]
- **Question:** Can Whisper (STT) + brain (7B Q4) + TTS coexist on 6GB VRAM during a live voice turn, or must STT/TTS spill to CPU?
- **State of knowledge:** The guide's answer is "split: brain on GPU resident, Whisper + Kokoro on CPU" — but the exact partition (e.g., Whisper-small ~0.5GB on GPU during turns) is unmeasured. The three-process topology also needs fault-injection validation. *(learn-advanced-cs.md, rtx-2060-guide.md)*
- **Why it matters:** The full voice+tool loop must fit or the architecture is fiction. OOM mid-conversation is a v1-class failure.
- **Resolution experiment:** Load brain at candidate quant → run Whisper-small on GPU → measure peak VRAM + tok/s degradation; fault-inject OOM and verify graceful degradation.

### 7. Allocating reasoning effort under a strict latency budget `FIELD` · Score 60 · [HC]
- **Question:** Given a hard latency budget (voice <300ms, interactive <3s, batch unbounded), how should the agent allocate reasoning compute — and when does more thinking merely add latency, cost, and unsupported conclusions?
- **State of knowledge:** The 8-strategy decision table exists (ReAct → best-of-N → tree search → MCTS+verifier, with belief-ledger/causal-post-mortem/neuro-symbolic default-on at ~1×). Value-of-information is formalized in decision theory but applied heuristically to LLM reasoning. The voice loop forbids strategies 2–4 outright. Difficulty estimation remains the hard sub-problem (see #2). *(learn-frontier-reasoning.md, learn-research-frontiers.md)*
- **Why it matters:** This is the brain's runtime controller — the single highest-leverage design decision after model selection.
- **Resolution experiment:** On the golden set (#4), measure success-vs-latency curves per strategy per difficulty tier; find the crossover points empirically.

### 8. UIA tree-walk latency on heavy apps `JARVIS` · Score 60 · [HC]
- **Question:** How long does a full UI Automation tree walk take on Owais's machine for heavy apps (Chrome 50 tabs, VS Code, Excel)?
- **State of knowledge:** Tree-first is the accuracy *and* cost strategy (exact bounds, 0 tokens, DPI-independent). Latency is the one unmeasured property; if tree walks take seconds on heavy apps, the pipeline needs caching/incremental updates. *(learn-multimodal.md)*
- **Why it matters:** The whole perception architecture assumes the tree is fast. If it isn't, the design changes.
- **Resolution experiment:** Time tree walks on 5 representative heavy apps; test incremental/diff strategies if slow.

### 9. Checkpoint cadence + worst-case replay time `JARVIS` · Score 60 · [HC]
- **Question:** What checkpoint cadence (events/time) keeps worst-case crash-replay under the UX budget on the Ryzen 5 3600, without churning the laptop SSD?
- **State of knowledge:** Four detection layers designed (`excepthook` → `faulthandler` → `atexit` → supervisor); checkpoint = snapshot + exact `event_id`, tmp+`os.replace()` in same dir; 50-events/5-minutes is a starting hypothesis. NTFS `os.replace`+fsync durability untested. *(learn-observability.md)*
- **Why it matters:** Crash recovery is a headline v2 promise (Anthropic `wake(sessionId)` pattern). Wrong cadence = slow resume or dead SSD.
- **Resolution experiment:** Prototype the event log; time full-day replay; measure write amplification at candidate cadences; test NTFS atomicity.

### 10. Owais's rubber-stamping threshold `JARVIS` · Score 60 · [MC]
- **Question:** How many approval prompts before *this user* starts auto-approving — and what does the calibration curve look like?
- **State of knowledge:** Google Research (2026), "Open and Emergent Problems in Agentic Privacy and Security: A Contextual Angle" (65 authors, 36 Google-affiliated; CAPS Workshop NYC Nov 2025; Open Problem 9.2): notice-and-choice consent is ineffective for agents (unforeseeable execution paths); prescription is sliding-scale autonomy + fewer high-stakes gates + 30s undo buffer. Rubber-stamping is a security vulnerability. The exact threshold is personal and observable, not theoretical. *(learn-frontend.md)*
- **Why it matters:** Determines the approval-gate design: too many gates = security theater; too few = insufficient oversight. This is a safety-critical UX parameter.
- **Resolution experiment:** Instrument approval prompts in v2 alpha; measure approval latency and reversal rate vs gate count; find the knee.

---

## JARVIS-LEVEL — the remaining measurement backlog (by subsystem)

### Reasoning & learning
| # | Question | Score | Resolution |
|---|---|---|---|
| 11 | O-LoRA interference on *tool-calling* skills at 20+ adapters — no published benchmark covers this | 48 [MC] | Train 20 skill adapters; measure cross-skill degradation on held-out tool tasks |
| 12 | Adapter-routing accuracy (ELM-style) on Hinglish task descriptions | 48 [MC] | Routing benchmark on code-switched descriptions |
| 13 | Do merged tool-skill LoRAs preserve safety behaviors? | 40 [HC] | Safety eval suite before/after TIES/DARE merge — eval-gated |
| 14 | Belief-ledger uncertainty thresholds — what triggers verification? | 48 [MC] | Tune on real usage; measure calibration (flagged claims actually wrong?) |
| 15 | Is PDDL/Z3-scale verification ever needed, or do schemas+tests suffice? (bet: latter) | 27 [MC] | Attempt one PDDL domain for the tool set; compare cost/benefit |
| 16 | Text/tree GUI lookahead reliability for 2–3 steps (bounds mental dry-run) | 36 [MC] | Simulate 2-step plans from tree state; verify against real UI |

### Memory & retrieval
| # | Question | Score | Resolution |
|---|---|---|---|
| 17 | Chroma HNSW recall on Hinglish-mixed corpora | 36 [MC] | T4-style eval on code-switched corpus |
| 18 | Best chunker for Hinglish code-switched text (recursive hypothesized fine; semantic chunkers are English-tuned) | 36 [MC] | Chunking bake-off on Hinglish docs |
| 19 | Optimal hybrid-search alpha per query category | 36 [MC] | Grid-search alpha on golden retrieval set |
| 20 | Contextual retrieval ingest cost — does it pay off at personal scale? (likely yes docs, no chat logs) | 24 [MC] | Measure ingest cost vs retrieval gain |
| 21 | Entity-extraction accuracy on Hinglish (bounds temporal-KG value) | 36 [MC] | NER benchmark on Hinglish entities |
| 22 | Measured frequency of temporal queries in real usage (determines if graph leg earns its keep) | 24 [MC] | Query-log analysis |
| 23 | Intra-rater consistency protocol for n=1 evaluation | 36 [MC] | Test-retest on Owais's own judgments |
| 24 | Pairwise votes needed for stable Bradley-Terry estimates on one user's distribution (~100–300 hypothesized) | 18 [MC] | Bootstrap on pilot votes |

### Voice & multimodal
| # | Question | Score | Resolution |
|---|---|---|---|
| 25 | VAD tuning for Hinglish conversational speech on real hardware | 48 [MC] | Tune Silero thresholds against recorded Hinglish |
| 26 | Hindi/Devanagari OCR + grounding quality on Hinglish UI | 36 [MC] | Benchmark on Hindi UI screenshots |
| 27 | GGUF OCR-2B vs PaddleOCR accuracy on real screenshots | 24 [MC] | Head-to-head on screenshot corpus |
| 28 | Coordinate-free grounding (Microsoft GUI-Actor, MIT) vs text-coordinate models in production | 24 [MC] | Evaluate when mature |

### Reliability & observability
| # | Question | Score | Resolution |
|---|---|---|---|
| 29 | Three-process topology validation via fault injection | 48 [HC] | Kill each process mid-task; verify recovery |
| 30 | The "turn succeeded" heuristic — exact definition | 36 [MC] | Needs real usage to define; start with explicit user correction as ground truth |
| 31 | Per-turn allocation profile (py-spy/tracemalloc on frozen app) | 36 [MC] | Profile on Owais's PC |
| 32 | `deal` contract overhead on hot paths (measure before decorating voice loop) | 30 [MC] | Microbenchmark |
| 33 | OTel SDK vs ~50-line hand-rolled contextvars | 16 [MC] | Prototype both; measure per-turn overhead |
| 34 | Logging volume in the audio path; retention window | 24 [MC] | Measure bytes/turn at candidate levels |
| 35 | NTFS `os.replace` + fsync durability semantics | 30 [HC] | Crash test on Windows |
| 36 | SQLite write throughput on Owais's disk | 20 [HC] | Benchmark |
| 37 | Queue poll interval vs laptop battery (wake-on-enqueue mitigates) | 16 [MC] | Measure |
| 38 | SQLite event-store sizing past ~10M events (add counter + warning at 1M) | 12 [MC] | Not actionable until 1M; instrument now |
| 39 | Projections in same vs separate SQLite file | 16 [MC] | Benchmark at build time |

### Frontend & platform
| # | Question | Score | Resolution |
|---|---|---|---|
| 40 | Tauri + PyInstaller sidecar + auto-update end-to-end on Windows | 48 [HC] | Spike build — reading won't resolve this |
| 41 | Hotkey set avoiding collisions on a real Windows machine | 20 [MC] | Test on Owais's machine |
| 42 | Vercel AI SDK vs ~100-line hand-rolled SSE client | 20 [MC] | Spike both, measure |
| 43 | SmartScreen reputation timeline for a new publisher identity ("weeks + hundreds of installs" — documented shape, unmeasured for JARVIS) | 12 [MC] | Unresolvable by experiment; plan around it |
| 44 | PyInstaller-frozen app behavior on Owais's PC (paths, permissions, AV) | 32 [HC] | Real test, not docs |

### Correctness tooling
| # | Question | Score | Resolution |
|---|---|---|---|
| 45 | Hypothesis stateful-testing ergonomics for the skill lifecycle | 36 [MC] | Prototype |
| 46 | garak / promptfoo / PyRIT fit for JARVIS's specific tool set | 36 [MC] | Hands-on evaluation |
| 47 | AgentRewind vs hand-rolled deterministic replay | 24 [MC] | Evaluate hands-on |
| 48 | Canary-prompt latency budget on the 2060 | 36 [MC] | Measure at build time |

### Legal / supply chain (tasks, not research)
| # | Item | Score |
|---|---|---|
| 49 | License verification on pinned checkpoints (OS-Atlas, UGround, MinerU, Kreuzberg — reported open, verify before vendoring) | 40 [HC] |
| 50 | Chroma 1.x long-term maintenance trajectory | 12 [MC] |

---

## FIELD-LEVEL — open research problems (ranked)

### F1. How can the agent estimate when its internal knowledge is insufficient? Score 40 · [MC]
- **State:** Calibration research (Brier scores, RLCD, per-bin curves) gives confidence *on outputs*, but detecting "this question is outside my training" — known-unknowns — remains weak. Retrieval gating ("should I search?") is heuristic. The SelfConsciousness probe work showed representations of self-knowledge exist but **manipulation mostly fails** — can't steer from inside.
- **Why for JARVIS:** Determines whether the brain hallucinates or reaches for a tool. Core reliability lever.
- **What would resolve it:** Abstention-accuracy benchmarks on curated known/unknown splits; retrieval-gating policies evaluated on real usage; field needs a standard "known-unknowns" eval.

### F2. How do long-horizon tasks stay reliable across interruptions and changing goals? Score 45 · [HC]
- **State:** Durable execution is solved engineering (event sourcing, checkpoints, idempotent tools, outbox pattern). The *open* part is semantic: resuming when the goal changed mid-flight, knowing what "done" means after interruption, handling partial success across sessions.
- **Why for JARVIS:** Multi-session tasks (research → draft → review tomorrow) are the product promise.
- **What would resolve it:** Long-horizon benchmarks with injected interruptions and goal changes (AgentBoard / TheAgentCompany style); a plan-vs-outcome comparator design.

### F3. How can memory improve without accumulating false or contradictory beliefs? Score 40 · [HC]
- **State:** Patterns exist (provenance, confidence decay, supersede-don't-delete, bi-temporal validity). But no proven mechanism prevents slow corruption from misattributed inferences — and A-MEM-style evolution **amplifies poisoning** (documented: quarantine untrusted memories from the evolution pass). Distinguishing user statements from model inferences is doctrine, not mechanism.
- **Why for JARVIS:** A personal agent that slowly learns false things about its user is worse than one that forgets.
- **What would resolve it:** Adversarial memory-poisoning benchmark; longitudinal belief-accuracy measurement; a "memory audit" protocol.

### F4. Distinguishing genuine improvement from benchmark overfitting Score 45 · [HC]
- **State:** Contamination is now well-documented (4 tiers: exact n-gram, syntactic, semantic/translation, task-level; Qwen 2.5: 100% GSM8K-train vs 27% test). The open problem: eval that can't be gamed. The JARVIS recipe exists (private golden set, canary GUIDs, quarterly refresh, judge-as-contract) but no *standard* exists for personal agents.
- **Why for JARVIS:** Every "model X beats Y" claim and every v2 improvement claim depends on this.
- **What would resolve it:** Field adoption of contamination-resistant eval norms; for JARVIS, just build the golden set (#4).

### F5. Which safety properties are formally provable vs empirically evaluated? Score 45 · [HC]
- **State:** The meta-rule is established: formal methods on the **code** side (permission checks, jail, atomic writes, idempotency — provable), eval suites on the **model-judgment** side, red-teaming on the **boundary**. The open question is the exact inventory: which JARVIS invariants admit proof, and where proof gives false confidence (spec mistranslation — "verified the wrong thing perfectly"). TLA+ is verdict LATER (100–200 line PlusCal model of the approval gate, once design stabilizes).
- **Why for JARVIS:** Tells us where to spend the formal-methods budget vs the eval budget.
- **What would resolve it:** Attempt the approval-gate PlusCal model; catalog what resists formalization; publish the inventory.

### F6. Combining uncertain multimodal observations without false confidence Score 32 · [MC]
- **State:** Uncertainty propagation across modalities is unsolved in general. JARVIS's engineering answer: staged gating (tree → OCR → local VLM → cloud) with explicit confidence at each stage, never averaging confidences across modalities.
- **Why for JARVIS:** The screen-watcher and grounding pipeline fuse tree data, OCR text, and pixels — false confidence here clicks the wrong button.
- **What would resolve it:** A calibrated fusion benchmark for GUI agents; until then, the staged-gating discipline.

### F7. Checking generated plans against real tool outcomes Score 36 · [HC]
- **State:** Verify-after-acting + neuro-symbolic checkers + deterministic replay cover the engineering. The open part is plan-level verification: did the achieved world-state match the intended state? Needs a plan-vs-outcome comparator, which doesn't exist as a standard component.
- **Why for JARVIS:** "Falsely reporting success" is a v1 failure class (C-B1's cousins). The comparator is the fix.
- **What would resolve it:** Design the comparator (intended state spec vs observed tree diff); evaluate on long-horizon tasks.

### F8. Alignment under changing user objectives Score 32 · [MC]
- **State:** Goals drift; learned policies and cached preferences may not. Open: detecting objective shift, re-confirming intent without nagging, corrigibility for a personal agent. JARVIS's current answer (confirmation gates + revocable personalization + preference provenance) is architectural, not a solved problem.
- **Why for JARVIS:** A year-old preference ("always take the highway") silently overriding today's intent is a trust-killer.
- **What would resolve it:** Stale-preference detection (contradiction with recent behavior → re-confirm); research on objective-drift benchmarks.

### F9. Evaluating agent autonomy (not just capability) Score 32 · [MC]
- **State:** No agreed metric for "how autonomous is *safe*." Benchmarks (AgentBench, GAIA, BFCL) measure capability. Autonomy calibration — did it act at the right level without asking too much or too little? — has no standard. The BT-arena + escalation-precision metrics are a local start.
- **Why for JARVIS:** The sliding-autonomy design needs a target metric, not vibes.
- **What would resolve it:** An autonomy-calibration benchmark: tasks with known optimal ask/act trade-offs; measure over/under-escalation.

### F10. Persistent personalization coexisting with privacy and user control Score 24 · [MC]
- **State:** Patterns exist (provenance, revocation surface, inspection UI, data minimization). Open: the right *defaults* — what should the agent remember without asking? This is product philosophy as much as technique. Deletion verification across logs/backups/vectors/caches is unsolved in practice.
- **Why for JARVIS:** Defines the trust contract with Owais.
- **What would resolve it:** A deletion-verification protocol for the full data lifecycle; user studies on memory defaults (n=1 here: ask Owais).

### F11. Value of information / stopping criteria for uncertain reasoning Score 32 · [MC]
- **State:** VoI is formalized in decision theory (partially covered by the math researcher, pending); applied to LLM reasoning it remains heuristic. "When to stop thinking and act" has no principled controller in production agents.
- **Why for JARVIS:** Feeds the reasoning router (#7).
- **What would resolve it:** Empirical stopping rules tuned on the golden set (marginal-gain thresholds per strategy).

### F12. Causal reasoning at Rung 3 (counterfactuals) Score 24 · [HC]
- **State:** ~20% accuracy drop on counterfactual mutations even for GPT-4-class models (RE-IMAGINE, ICLR 2025) — a genuine wall. Rung 2 (intervention) is available via the sandbox as a "free causal laboratory"; Rung 3 remains out of reach.
- **Why for JARVIS:** Debugging and diagnosis ("would the bug persist if X changed?") would benefit; not blocking.
- **What would resolve it:** Field breakthrough; for JARVIS, the causal post-mortem discipline (PN/PS scoring) is the practical substitute.

### F13. Multi-agent independent verification without excessive cost Score 24 · [MC]
- **State:** Correlated failures dominate multi-agent setups (shared-mode errors); debate/critique helps sometimes; cost scales linearly. Open: when does a second agent add *real* independence vs expensive agreement?
- **Why for JARVIS:** The Conscio 4-voice council and Skeptic patterns assume independence — unproven.
- **What would resolve it:** Measure critic-independence (does the critic catch errors the generator's own distribution wouldn't?); diversity metrics for agent ensembles.

### F14. Meta-learning's practical limits Score 16 · [MC]
- **State:** MAML/few-shot adaptation works in narrow domains; "learning to learn" for open-ended agents hasn't delivered. Nested Learning (Google, NeurIPS 2025) is new and unvalidated.
- **Why for JARVIS:** Curiosity only — retrieval + skills + adapters already cover adaptation. Do not chase.
- **What would resolve it:** A demonstrated open-ended meta-learning result; until then, SKIP.

### F15. Model collapse / recursive training risks Score 18 · [MC]
- **State:** Training on synthetic data degrades models (documented). Relevance to JARVIS: if the agent's own outputs become training data (distillation, fine-tuning on conversation logs), quality may decay. Mitigation is known: keep human/verified data in the loop, watermark synthetic data.
- **Why for JARVIS:** Guards the continual-learning track (#11–13): never fine-tune purely on self-generated trajectories.
- **What would resolve it:** Longitudinal measurement if v2 ever trains on its own logs; policy: human-verified data majority, always.

### F16. Trained self-correction escaping the prompting bottleneck Score 15 · [SP]
- **State:** Prompting-based self-correction often *degrades* performance (Huang et al., arXiv 2310.01798 — convergent 2023–2026); the bottleneck is error *detection*. Whether RL-trained correction escapes it is open and inconclusive (2025–2026).
- **Why for JARVIS:** Would unlock a new safety/quality mechanism; currently not blocking (external critics work).
- **What would resolve it:** A replicated RL self-correction result on agentic tasks; until then, ban same-model self-review as a safety mechanism.

### F17. World models as planning tools for GUI agents Score 16 · [MC]
- **State:** Agents use simulators <1% of the time; sometimes perform 5% *worse* with them (ACL 2026). A *weak* world model guiding a *strong* agent shows promise (WKM) — maps to a tiny CPU model pre-screening irreversible plans.
- **Why for JARVIS:** Bounded: mental dry-run for high-risk actions only. Full desktop world model = fantasy on 6GB.
- **What would resolve it:** Measure whether tree-based 2-step lookahead (#16 in JARVIS list) is reliable; that's the experiment that matters.

### F18. Mechanistic interpretability yielding deployable safety Score 8 · [HC on the negative]
- **State:** Knowledge-action gap >50 points (near-perfect internal hazard representations, <25% error correction via intervention); field roadmap concedes partial coverage and validation illusions. Verdict: zero application for v2.
- **Why for JARVIS:** None — included to prevent wasted effort. Behavioral guardrails (permissions, audit, Skeptic), not SAEs.
- **What would resolve it:** Nothing in v2's timeframe; revisit if the field produces an actionable result.

---

## Design decisions parked (not unknowns — need Owais/design input, not research)

1. Shared JARVIS OAuth client ID vs per-user client creation (UX vs credential hygiene).
2. SSE stream auth pattern (session cookie vs short-lived signed URL).
3. Single vs two Uvicorn workers (measure under load — borderline measurable).
4. Outbound rate-limit placement: brain router, middleware, or both.
5. Version pins for the whole stack at build time (APScheduler 3.x vs 4.x, etc.).
6. Whether JARVIS ever needs true multi-user (family profiles?) — product decision that re-opens the PG-vs-SQLite question.
7. Polling vs webhooks for Telegram (leaning: polling — `getUpdates`, no inbound port).
8. AI SDK vs hand-rolled streaming client (spike will inform, but it's a taste call too).

## Meta-findings (patterns across the unknowns)

1. **The 2060 is the laboratory.** ~60% of JARVIS-level unknowns resolve the same way: run it on the card. Derived estimates are explicitly marked — the map's highest-value action is a single benchmarking weekend.
2. **Hinglish is the systematic blind spot.** Four independent studies flagged it (embeddings, chunking, judges, VAD, entity extraction, OCR). No public benchmark covers code-switched agent tasks. Building the Hinglish golden set is one experiment that pays off across six unknowns.
3. **External ground truth beats introspection — again.** The field-level unknowns that look tractable (F2, F4, F5, F7) all resolve via *measurement against the world*, not better self-modeling. The unknowns that look intractable (F16, F18) are the introspection ones.
4. **Uncertainty has two addresses.** Discriminator accuracy (#3) and belief thresholds (#14) are the same problem at different scales: *knowing when you don't know*. The belief ledger is the cheap always-on answer; the discriminator gates the expensive strategies.
5. **Safety unknowns are mostly resolved by architecture, not research.** F5's inventory, the approval-gate model, deletion verification — these are design work with known methods, not open science.

## What this map does NOT cover (all four pending researchers LANDED 2026-10-19)

- **Math for JARVIS** → `learn-math-for-jarvis.md` (may resolve F11 (VoI); sharpens #7) ✓
- **Frontier architectures** → `learn-frontier-architectures.md` (SSMs/Mamba, sparse compute, retrieval-augmented models) ✓
- **Evaluation science** → `learn-evaluation-science.md` (experimental design discipline, statistical validity, integrated scorecard; operationalizes #4/F4) ✓
- **Privacy engineering** → `learn-privacy-engineering.md` (data lifecycle, deletion verification — feeds F10; DP scoped) ✓

## Ledger

- **50 JARVIS-level items** (48 measurements + 2 legal/supply-chain tasks), **18 field-level problems**, **8 parked design decisions**. *(Corrected Cycle 18: an earlier draft said 44+6; the listing shows #1–#48 measurement + #49–#50 legal.)*
- **Skipped per Rule Zero:** re-deriving anything in the 15 source studies; the four pending researchers' domains.
- **No experiments run** (LEARNING ONLY per task). Every "resolution experiment" above is a proposal, not a result.
- **No fabricated citations.** References live in the source studies; this map adds none.
