# Program Synthesis & AI-Assisted Theorem Proving — Scoping Study

*PHASE INFINITY, Research Cycle 11. Date: 2026-10-19. Status: scoped, not a full survey.*
*Research question: near-term relevance for JARVIS, or principled SKIP?*

---

## Verdicts (up front)

| Sub-area | Verdict | One line |
|---|---|---|
| DreamCoder-style synthesis | **SKIP** | Research framework, not a deployable component; the LLM already is the synthesizer |
| LLM-generating tool wrappers from schemas | **SKIP as machinery** | Hand-write + property tests win at this scale; LLM codegen on demand already covers it |
| Lean proofs for the 5–10 contracted functions | **SKIP now** | Proof effort dwarfs benefit vs Hypothesis + contracts; faithfulness gap unresolved |
| Lean/Z3 as design-time checkers | **WATCH** | Already adopted for C2 (Z3 in CI); Lean if push-button tactics arrive |

---

## 1. Program synthesis [HC]

**The idea.** Generate programs from specs or examples instead of writing them. DreamCoder (Ellis et al., 2020; arXiv:2006.08381) is the flagship: wake-sleep Bayesian program learning — wake phase solves tasks via neurally-guided search over a DSL, sleep phase compresses solutions into a growing library of reusable abstractions. It rediscovers map/filter/fold from LISP primitives and physics laws from data. Takes ~a day on 20–100 CPUs to converge per domain.

**The JARVIS-relevant angle, examined.** Could synthesis generate tool wrappers/validators from schemas (e.g., TOOL_DEFINITIONS → validated dispatch code)? In principle yes. In practice:
- The wrapper code is **small, stable, and security-critical** — exactly the code you want a human (or a careful LLM + tests) to write once and review, not regenerate.
- DreamCoder needs a DSL + task corpus + compute per domain; JARVIS has ~40 tools in ordinary Python. The setup cost exceeds the writing cost by an order of magnitude.
- The practical synthesis already happens: the brain (LLM) writes code on demand; contracts (deal) + Hypothesis verify it. That IS the synthesis loop, minus the Bayesian library-learning machinery.

**What survives as an idea:** DreamCoder's *library learning* — accumulating verified abstractions from solved tasks — is the same shape as the Hermes self-improving-skills pattern already adopted. The pattern is kept; the framework is not needed.

**Verdict: SKIP.** [HC] Not everything deserves depth; this got its honest scoping pass.

---

## 2. AI-assisted theorem proving [HC]

**2026 state (verified via search).**
- DeepMind AlphaProof: 83.3% on IMO formal problems (Lean 4), MCTS + RL.
- Mistral Leanstral 1.5 (June 2026): open-weight MoE specialized for Lean 4 proofs + autoformalization.
- NanoProof (arXiv:2610.11605, Oct 2026): 50.8% pass@16 on MiniF2F-Test at ~90× less compute than HyperTree — fully open pipeline.
- Industrial scale: 13M-line Lean proof efforts reported in 2026 (Anthropic/OpenAI announcements).

**The JARVIS-relevant angle, examined.** Prove properties of the 5–10 contracted functions (permission gate, jail check, atomic writes)? The honest accounting:
- **Proof effort:** formalizing even simple properties takes hours of expert effort per property today. The 5–10 functions have maybe 15–20 properties total. A skilled engineer writes Hypothesis properties for all of them in an afternoon; Lean would take weeks including the learning curve.
- **The faithfulness gap:** AI-formalized Lean statements frequently drift from the intended claim while still compiling — a "proved" property can be vacuous or drifted. Multiply documented in 2026: "Beyond Compilation: Evaluating Faithful Natural-Language-to-Lean Statement Formalization" (arXiv:2606.31002 — human audits of compile-passing AI outputs found large unfaithful fractions), and Bastounis, Circelli & Hansen (Oct 2026 — AI mistranslations of NL proofs passing Lean checks, including the OpenAI Navier-Stokes case; they argue faithful autoformalization is *harder than any computational problem*). *(Corrected Cycle 18: an earlier draft attributed a specific "~43%" figure to "Bourigault et al. 2026" linked to arXiv:2608.28433 — that link is the Prove2Me platform paper and says nothing about a faithfulness study; the figure is unattributable. The gap itself is real; the number was not.)* The audit surface shrinks to definitions + statements — but someone must still audit those, in Lean.
- **The kernel incident (2026):** a purported Lean-verified Collatz disproof collapsed on a Lean kernel bug. Machine-checked ≠ infallible; it relocates trust to the kernel and the formalization.
- **What Lean proves vs what JARVIS needs:** Lean excels at mathematical truth. JARVIS's critical properties are *operational* (this path stays in the jail, this flag can't flip without approval) — Z3 already covers the decidable fragment (C2 adopted), Hypothesis covers the code, runtime guards enforce the decision.

**Verdict: SKIP now.** [HC] The machinery doesn't pay off at ~10 functions. Revisit only on the watch triggers below.

---

## 3. The scale argument [VC]

Both fields pay off where **human proof/writing effort is the bottleneck at scale**: math libraries (Mathlib, 210k+ theorems), compilers, crypto primitives. JARVIS's trusted computing base is ~10 small functions. At that scale:

1. `deal` contracts — minutes per function, enforced at runtime.
2. Hypothesis property tests — an afternoon for the full set, run in CI forever.
3. Z3 design-time proof for C2 (permission monotonicity) — the one property with a clean finite-domain encoding.

This stack costs days, not months, and covers the actual failure modes (the fault-tree cut sets). Synthesis/proving machinery would cost weeks-to-months to stand up and verify *itself* — the classic "who verifies the verifier" regress at small scale.

**Principle:** formal machinery earns its place when the cost of standing it up is less than the cost of the bugs it prevents, *discounted by the coverage of cheaper methods*. At JARVIS scale, cheaper methods cover ~everything the machinery would.

---

## 4. Watch triggers (what changes the verdict)

1. **Push-button Lean tactics** for permission-monotonicity-class properties — if `lean --auto` discharges C2 from the Python source with no manual proof, adopt immediately. (Leanstral's autoformalization direction is the one to watch.)
2. **Verified autoformalization of contracts** — an LLM+Lean loop that turns `deal` contracts into checked proofs with a faithful-statement guarantee >95% (current published baseline: none — the earlier "~43%" figure was unattributable; treat the baseline as unmeasured).
3. **DreamCoder-style library learning shipping as a library** — reusable, verified component synthesis for agent toolkits, not a research demo.
4. **A second independent prover** maturing (Isabelle/HOL automation, Coq hammer-style) to cross-check Lean — reduces single-kernel trust.

None of these are true today. The file gets re-opened when one fires.

---

## Confidence & unknowns

- [VC] on the scale argument and the current cost structure (contracts+Hypothesis vs Lean effort).
- [HC] on DreamCoder's status (research framework; verified via 2026 search results, no new production deployments found).
- [HC] on Lean 2026 capabilities (multiple corroborating 2026 sources: NanoProof arXiv:2610.11605, Leanstral release, the faithfulness gap — arXiv:2606.31002 "Beyond Compilation" and Bastounis/Circelli/Hansen Oct 2026).
- [MC] on the exact faithfulness figure (unattributable single-source — see §2 correction).
- Unknown: whether autoformalization crosses the usability threshold in 2027 — genuinely unknowable, hence watch triggers not predictions.

## References (all real, from live search 2026-10-19)

- Ellis et al., "DreamCoder…", arXiv:2006.08381 — https://www.alphaxiv.org/overview/2006.08381v1
- Kripner & Straka, "NanoProof…", arXiv:2610.11605 — https://arxiv.org/abs/2610.11605v1
- Prove2Me platform paper — https://arxiv.org/html/2608.28433 *(unrelated to the faithfulness gap; retained for DreamCoder-adjacent context, do not cite for faithfulness claims)*
- "Beyond Compilation: Evaluating Faithful Natural-Language-to-Lean Statement Formalization" — https://arxiv.org/abs/2606.31002
- Bastounis, Circelli & Hansen, "Navier-Stokes lost in translation" (Oct 2026) — on SCI=infinity faithfulness argument
- Mistral Leanstral 1.5 release — http://groundtruth.day/news/mistral-releases-a-model-that-does-formal-math-proofs.html
- Stephen Diehl, "Program Synthesis: the λ in the Machine" — https://www.stephendiehl.com/posts/program_synthesis/
