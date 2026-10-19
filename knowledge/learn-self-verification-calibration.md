# Self-Verification & Calibration for JARVIS — Phase ∞, Cycle 7

*Research cycle 7, written 2026-10-19. LEARNING ONLY — no code, no installs, no model calls.*
*All measurements marked **UNRUN** (no model access in this environment). This cycle designs the calibration study; it does not execute it.*

**Research question:** Can JARVIS's brain reliably judge its own outputs — and if not, what replaces self-verification?

**Answer in one paragraph:** The literature says no, with unusual convergence for this field — same-model self-judgment is squeezed from both sides: where an LLM judge is accurate enough (syntax, schema conformance) a deterministic checker is 100% and free, so the judge is redundant; where a deterministic checker is incomplete (factual grounding, plan quality, novelty) the LLM judge falls well below the 90% discriminator threshold, so it is untrustworthy. This cycle ranks the five rungs of self-judgment difficulty with falsifiable hypotheses, designs the 50-item calibration study that would confirm or kill the ranking, formalizes the AutoMix-style POMDP escalation math that consumes the study's outputs, and specifies the null-hypothesis architecture — what JARVIS looks like with **zero** self-judgment. The study is the gating measurement for open-problem #3 and the discriminator precondition on tree search (learn-frontier-reasoning.md: ≥90% required).

**§19 protocol followed:** audit (§1) → question (§2) → research (§3) → compare (§4) → derive (§5: study design) → validate (§6: falsifiers) → integrate (§7: ADR, open-problem update) → record (§8) → reassess (§9).

**Confidence tags:** [VC] >95% · [HC] 80–95% · [MC] 60–80% · [SP] 40–60% · [UK] unknown. **DESIGN** = derivation from research, unmeasured.

---

## 1. Audit — what prior cycles established (referenced, not re-researched)

| Prior file | Contribution to this cycle | Status |
|---|---|---|
| `learn-frontier-reasoning.md` | Tree search needs ≥90% discriminator accuracy; below that it is "worse than useless." "The verifier is the strategy." Environment > LLM as judge. | Accepted as the **gating constraint**. |
| `learn-research-frontiers.md` §4 | Limits of self-reflection [VC]: intrinsic self-correction frequently *degrades* performance (Huang et al. 2023); bottleneck is error *detection* (Tyen et al. 2024); error-hunting prompts → >10× false-positive rate (2026). Boundary conditions where correction works: external feedback, different-model critic, confidence-gated. | Accepted as the **negative result** this cycle extends to small models. |
| `learn-bounded-rationality.md` | AutoMix's POMDP-over-noisy-self-verification as escalation math; NEVER an LLM-judge router on the live voice path; tier budgets (voice <300ms/<1s, chat seconds, background minutes); metalevel ≤5% overhead. | Accepted as the **escalation frame + budget law**. |
| `learn-evaluation-science.md` | Wilson CIs, McNemar (paired), Holm correction, Cohen's κ, n=1 protocol for Owais, power table (50 tasks ≈ 15–20pp detectable). | Accepted as the **statistics kit** for the study design. |
| `learn-math-for-jarvis.md` | Brier score, reliability diagrams, Beta-Bernoulli ledger, VoI one-liner ("information has no value unless it can change a decision"), asymmetric loss. | Accepted as the **calibration math**. |

**Genuinely new in this cycle:** the five-rung difficulty gradation with hypotheses; small-model-as-verifier evidence (SCORE, SELF-[IN]CORRECT, trace-contamination); the self-consistency vs self-verification distinction as a confound control; the full 50-item study design; the POMDP math with measured (TPR, FPR); the null-hypothesis (zero-self-judgment) architecture.

---

## 2. The gradation of self-judgment difficulty — ranking + hypotheses

Self-verification is not one capability. Five rungs, easiest to hardest, each with a deterministic competitor and a falsifiable hypothesis about a 4–9B brain judging its *own* outputs:

| Rung | Judgment task | Deterministic competitor (accuracy / cost) | Hypothesized 7B self-judge accuracy | Clears 90%? | Verdict for JARVIS |
|---|---|---|---|---|---|
| **1. Syntax** | "Is this tool-call payload well-formed JSON / parseable?" | `json.loads` — 100%, ~0 cost | ~98% [SP] | Yes (irrelevant) | **Deterministic always.** LLM judge is strictly dominated: worse accuracy, nonzero cost. Never build it. |
| **2. Schema conformance** | "Are required args present, types correct, enums valid, ranges sane?" | Pydantic/dataclass validation — 100%, ~0 cost | ~90–94% [SP] | Borderline | **Deterministic always.** Even if the hypothesis holds, 100%-free beats 92%-expensive. The LLM adds nothing. |
| **3. Factual verification vs retrieved evidence** | "Is claim C entailed by chunk E?" (AutoMix's entailment framing) | Verbatim-quote + substring check — ~100% on quotes, *incomplete* (can't judge paraphrase) | ~70–78% [MC] | **No** | **Deterministic partial + escalate.** The gap the LLM would fill is exactly where it fails. |
| **4. Plan-quality judgment** | "Will this 3–6-step tool plan succeed as written? Where is the first fault?" | STRIPS-lite precondition/effect chain check — high precision, *incomplete* (misses semantic faults) | ~55–65% [SP] | **No** | **Deterministic partial + different-model critic or human on high stakes.** |
| **5. Novelty / creativity judgment** | "Which of these is the most novel/appropriate?" | None possible (no ground truth exists in advance) | ~50% ≈ chance [MC] | **No** | **Human only.** Owais is the taste authority; no judge, LLM or otherwise, is calibratable here. |

### Where the 90% line falls

**Between rung 2 and rung 3.** The hypothesis, stated to be falsifiable:

> **H-GRAD:** Self-judge accuracy on rungs 1–2 (syntactic/formal properties) ≥ 90%; on rungs 3–5 (semantic properties requiring grounding or taste) < 80%, with rung 5 at chance.

**Why the 90% line is unreachable in practice, not just in theory — the squeeze argument [DESIGN]:**
- Rungs 1–2: the LLM clears 90%, but the deterministic checker is at 100% with ~zero latency. The LLM judge is never the right choice — it's not that it fails, it's that it never gets to play.
- Rungs 3–5: the deterministic checker is incomplete (it cannot judge paraphrase entailment, semantic plan faults, or taste), which is precisely where you'd want an LLM judge — and the LLM judge is below the 90% line, where tree search becomes "worse than useless" (learn-frontier-reasoning.md).

**There is no rung where an LLM self-judge is both (a) needed and (b) reliable.** This is the cycle's central claim. It is consistent with every piece of evidence in §3 and is directly testable by the study in §5.

### Which rungs can a 4–9B brain plausibly clear? (Hypotheses, UNRUN)

- **4B tier (BitNet-class):** rungs 1–2 at ~90%+ [SP]. Rung 3 entailment at this size is expected to be near-chance on adversarial items (negation flips, entity swaps) [SP].
- **7–9B tier (daily driver):** rungs 1–2 clear; rung 3 at 70–78% [MC]; rung 4 at 55–65% [SP]; rung 5 chance.
- **The critical asymmetry (evidence-backed):** it is not size that matters most, it is *independence of signal*. A smaller *different* model with *independent* evidence catches what the generator misses (learn-research-frontiers.md §4, [HC]); a larger *same* model re-reading its own trace mostly re-confirms its own errors (trace-contamination finding below).

---

## 3. What the literature says — the genuinely new evidence

### 3.1 The convergent negative result (extends Huang 2023)

The prior file indexed Huang et al. (arXiv:2310.01798), "When Hindsight is Not 20/20" (arXiv:2404.09129), the 2026 prompt-sensitivity study, and Tyen et al. 2024. New since:

- **SELF-[IN]CORRECT (AAAI 2025):** the cleanest test of the question. Defines DG-DIFF = discrimination accuracy minus generation accuracy on the *same* candidate set, across 56 experiments (Phi-3, LLaMA, Mixtral, GPT families; GSM8K, TriviaQA, TruthfulQA, MT-Bench). In 54/56 experiments the hypothesis "LLMs are not reliably better at discriminating their own outputs than generating them" was **not rejected**. DG-DIFF was small or negative nearly everywhere. Even the strongest models (LLaMA-3-70B, GPT-4-turbo) showed only small positive DG-DIFF — "insufficient to reliably reject." [HC — primary source, peer-reviewed]
  - *Implication for JARVIS:* the discriminator-accuracy question and the self-verification question are the same question. If discrimination ≈ generation, then "generate-then-judge" buys nothing over "generate once" — and the 90% discriminator threshold is unreachable by same-model judging on semantic rungs.
- **"Small Language Models Need Strong Verifiers to Self-Correct Reasoning" (2024, SCORE method):** fine-tuned small LMs on self-correction data collected from small LMs themselves — they became better *refiners*, but **still needed strong verifiers** to self-correct successfully. "The self-verification limitation of LMs currently poses an obstacle to the advancement of intrinsic self-correction." [HC — primary source]
  - *Implication:* training helps the *correction* step (consistent with Tyen: correction isn't the bottleneck) but does not fix the *detection* bottleneck. For the 2060 LoRA track: fine-tuning a verifier is worth trying; fine-tuning self-correction is not the priority.
- **"Don't Read the Log: Execution Traces Contaminate Verifiers in Video-Generation Agents" (arXiv:2609.28564, 2026):** on 109 labeled clips, a trace reporting a successful tool call made three open-weight Qwen-VL judges (7B, 8B, 32B) accept **78–90% of failures** (up from 7–19% without the trace). A contradicting trace made them reject up to 100% of correct clips. "Use only the frames" instructions did not remove the effect. Frontier closed judges were essentially unmoved. And: a cheap checker writing its verdict into the trace **launders its errors into a stronger final judge** (0.69 false accepts). [HC — primary source, direct mechanism]
  - *Implication for JARVIS:* **least-privilege judging is mandatory.** The judge must see the *evidence* (the file content, the UI tree, the quoted chunk) — never the generator's trace, never the generator's narration of what it did, and never another checker's verdict inline. Deterministic checkers write to the *belief ledger*, not into the next prompt. This is a hard architectural rule, not a suggestion.
- **"Noisy but Valid" (Maia Polo et al., arXiv:2601.20913, 2026):** treats judge outputs as noisy labels characterized by **judge TPR and FPR estimated from a small holdout**, and builds hypothesis tests with finite-sample error control on top. [HC]
  - *Implication:* this is exactly the parameterization the POMDP escalation math needs (§6). The study design (§5) must therefore estimate per-rung (TPR, FPR) — not just accuracy — because the escalation threshold is computed from them.

### 3.2 Self-consistency vs self-verification — the confound that eats results

These are different operations and the literature keeps confusing them (Huang et al.'s appendix makes this exact point about multi-agent debate):

- **Self-consistency** (Wang et al., ICLR 2023): sample N reasoning paths, take the majority answer. This is *selection among candidates* — breadth. It works (large measured gains on math) and requires **no judgment at all**, just counting.
- **Self-verification** (Weng et al. 2022, FOBAR; AutoMix's entailment check): judge one output's correctness — depth. This is the operation that the negative results target.
- **Huang's razor:** multi-agent "debate" gains are self-consistency (selection among multiple generations), not self-correction (judgment). If you claim judgment gains, you must **exclude selection effects** — compare the judge's pick against a random pick from the same candidate set, not against single-generation.

*Design consequence for §5:* the study measures discrimination on a **fixed** candidate set with a random-selection baseline (DG-DIFF). Any protocol that lets the "judge" see multiple candidates and pick is measuring selection, and must be labeled as such. JARVIS's best-of-N (learn-frontier-reasoning.md Strategy 2) is selection and stays legal; what this cycle gates is *judgment*.

### 3.3 Where verification DOES work — the boundary map

| Works | Why | JARVIS transfer |
|---|---|---|
| Reflexion (Shinn et al. 2023): reflect on **environmental** failure signals | The feedback is external ground truth (tool errors, test failures), not introspection | Reflect on tool error messages — already the design |
| CoVe (Dhuliawala et al. 2023): decompose into **independently answerable verification questions** | Models answer simple questions better than complex ones; verification questions are answered *without seeing the draft* | Decompose claims; judge sub-claims against evidence, draft withheld from the sub-judge |
| CLAIM-CAL: **claim-level** verification beats whole-answer verification; **isotonic calibration** fixed ECE 0.212 → 0.038 | Whole-answer judgment lets one fluent paragraph launder five bad claims; raw verbalized confidence is systematically overconfident | Judge claims, not answers; never trust raw stated confidence — calibrate it or don't use it |
| **Trained** verification co-evolves with generation (ReVeal, ICLR 2026: test-case accuracy 50% → 88% during RL; >85% judgment accuracy on valid test cases) | RL on verification escapes the prompting bottleneck (open question in learn-research-frontiers.md: "early 2025–2026 work inconclusive" — ReVeal is now the positive datapoint) | Future 2060 LoRA track: train a verifier, don't prompt one. [MC — one paper] |
| AutoMix: few-shot verification **framed as entailment** + POMDP router over the noisy signal | Entailment ("does context C entail answer A?") is the easiest judgment framing; the POMDP handles the noise honestly | The §6 math; entailment framing for rung-3 items |
| **Different-model** critic, even smaller (learn-research-frontiers.md §4) | Independent signal breaks the correlated-error trap | The only LLM-judge allowed in the null architecture (§7) |

### 3.4 The prompt-framing landmine (protocol consequence)

The 2026 prompt-sensitivity finding (indexed in learn-research-frontiers.md): prompts that explicitly hunt for errors produce **>10× the false-positive rate** and the lowest accuracy; conservative prompts miss real errors; net effect of reflection at best ~+1%. And "Generation vs. Multiple Choice" (2025): output format itself changes correction behavior.

*Design consequence:* the study runs **two judge prompt framings as separate arms** (neutral-entailment vs error-hunting) and **two output formats** (binary verdict vs MCQ-with-abstain). The abstain option ("cannot determine from evidence") is load-bearing: rung 3's hardest items are the *unsupported* ones, where the only correct judgment is abstention.

## 4. Compare — relation to prior cycles

- **learn-frontier-reasoning.md** supplied the 90% discriminator threshold and "the verifier is the strategy." This cycle supplies the *measurement design* for that threshold on JARVIS's actual domain (tool calls / plans, not trivia) and the squeeze argument for why the threshold is structurally unreachable by same-model judges.
- **learn-research-frontiers.md §4** supplied the negative result for large models. This cycle extends it downward (SCORE: small models need strong verifiers), sideways (SELF-[IN]CORRECT: discrimination ≉ generation), and into the mechanism (trace contamination; prompt-framing FP inflation).
- **learn-bounded-rationality.md** supplied AutoMix-as-escalation-math and the budget law. This cycle formalizes the math with the (TPR, FPR) parameterization the study produces.
- **learn-evaluation-science.md** supplied the statistics kit. This cycle spends it on a concrete 50-item design.
- **learn-math-for-jarvis.md** supplied Brier/reliability-diagrams/Beta-Bernoulli/VoI. This cycle applies them to judge outputs and to the escalation threshold.

---

## 5. DERIVE — the calibration study design (deliverable core) [DESIGN, UNRUN]

### 5.1 Pre-registered hypotheses

- **H-GRAD (primary):** judge accuracy rungs 1–2 ≥ 90%; rungs 3–5 < 80% (rung 5 ≈ chance).
- **H-INDEP:** a *different-model* critic (independent signal) beats the same-model judge on rungs 3–4 by ≥ 10pp.
- **H-FRAME:** the error-hunting prompt framing has ≥ 3× the false-positive rate of the neutral framing on known-correct items (directional test of the 2026 finding).
- **H-ABSTAIN:** adding an explicit "cannot determine" option improves rung-3 accuracy by reducing forced guesses (measured via Brier score improvement).

### 5.2 Item set: 50 items, 10 per rung, tool-call/plan domain

Balance: each rung has 5 positive (correct/valid/supported) and 5 negative (faulty) items, with negatives spanning easy and adversarial variants. Shown below: 4 fully-worked exemplars per rung + generation recipes for the remaining 6 (each recipe is executable by whoever builds the golden set).

**RUNG 1 — Syntax (ground truth: `json.loads`)**
- E1.1 (valid): `{"tool": "file_write", "args": {"path": "notes.txt", "content": "hello"}}` → VALID.
- E1.2 (invalid): `{"tool": "file_write", "args": {"path": "notes.txt", "content": "hello",}}` (trailing comma) → INVALID.
- E1.3 (adversarial): `{"tool": "run", "args": {"cmd": "echo \"she said \\\"hi\\\"\""}}` (nested escaped quotes, valid) → VALID.
- E1.4 (invalid): `{'tool': 'file_write'}` (single quotes) → INVALID.
- Recipes R1.5–R1.10: unclosed bracket; `NaN` literal; missing colon; valid deeply-nested payload (4 levels); unicode escape valid; duplicate keys with different values (valid JSON, note in rubric).

**RUNG 2 — Schema conformance (ground truth: Pydantic validation against the tool's schema)**
Tool schema example: `file_write(path: str [required], content: str [required], encoding: str [optional, enum: utf-8|utf-16|ascii], create_dirs: bool [optional])`.
- E2.1 (valid): all required present, types correct, `encoding: "utf-8"` → VALID.
- E2.2 (invalid): missing `content` → INVALID.
- E2.3 (invalid): `create_dirs: "yes"` (string, not bool) → INVALID.
- E2.4 (invalid): `encoding: "utf-32"` (enum violation) → INVALID.
- Recipes R2.5–R2.10: extra unknown arg (schema-strict → invalid; document the strictness choice); `path: 12345`; null for required field; valid with all optionals; wrong tool name entirely; `content` present but empty string (valid — tests whether judge confuses empty with missing).

**RUNG 3 — Factual verification vs retrieved evidence (ground truth: human entailment labels)**
Framing (AutoMix-style): "Does EVIDENCE entail CLAIM? Answer: ENTAILED / CONTRADICTED / UNVERIFIABLE."
- E3.1 (entailed): Evidence: "The backup completed at 02:14 and wrote 4,096 files." Claim: "The backup finished after 2am with over 4,000 files." → ENTAILED.
- E3.2 (contradicted): Same evidence. Claim: "The backup wrote fewer than 4,000 files." → CONTRADICTED.
- E3.3 (unverifiable — the hard case): Evidence: "The backup completed at 02:14." Claim: "The backup completed without errors." → UNVERIFIABLE (completion ≠ error-free).
- E3.4 (adversarial negation): Evidence: "Do NOT restart the service before 18:00." Claim: "The service may be restarted at 17:30." → CONTRADICTED.
- Recipes R3.5–R3.10: entity swap (filename changed); number flip (4,096 → 4,906); claim requiring synthesis of two chunks (entailed); claim about absence ("no errors were logged" with evidence silent on logs → UNVERIFIABLE); temporal mismatch; claim quoting evidence verbatim but with one word dropped changing meaning.

**RUNG 4 — Plan-quality judgment (ground truth: STRIPS-lite symbolic simulator)**
Fixed tool set with declared preconditions/effects. Example domain: `create_folder(path)` [effect: exists(path)]; `file_write(path, content)` [precondition: exists(parent(path))]; `send_email(to, body)` [precondition: file_readable(attachment) if attachment given]; `shutdown()` [no precondition; effect: session ends].
- E4.1 (valid): create_folder("reports") → file_write("reports/q3.txt", ...) → send_email(to, attachment="reports/q3.txt") → VALID.
- E4.2 (invalid): file_write("reports/q3.txt", ...) without create_folder → INVALID (first fault: step 1, unmet precondition).
- E4.3 (invalid): send_email(...) → file_write(attachment source) → INVALID (wrong order; first fault: step 1).
- E4.4 (adversarial): valid chain + `shutdown()` as step 2 of 4 → INVALID (session ends; steps 3–4 cannot execute; first fault: step 2).
- Recipes R4.5–R4.10: hallucinated tool (`compress_folder` not in tool set); irreversible step (`delete_folder`) without confirmation step (invalid per policy — tests policy-awareness); 6-step valid plan (longer horizon); plan that is valid but suboptimal (extra redundant step — VALID, tests whether judge confuses inefficiency with incorrectness); precondition satisfied by *earlier observation* not by a plan step (valid — tests context use); two faults, judge must report the *first*.

**RUNG 5 — Novelty/creativity judgment (ground truth: Owais's pairwise preferences, Bradley-Terry)**
- Items: 10 pairs of candidate outputs (feature names, notification phrasings, HUD label wordings). Judge picks the more novel/appropriate per pair.
- Ground truth per pair: Owais's blind pick (n=1 protocol, learn-evaluation-science.md §3.2: blind, ties allowed, 20% re-presented for intra-rater consistency).
- Hypothesis: judge–Owais agreement ≈ 50–60% (chance to slight), κ ≈ 0–0.2. This rung is included to *demonstrate* uncalibratability, not to pass.

### 5.3 Judge protocol

1. **Generation phase:** the brain under test generates the 40 rung 1–4 items' *candidate outputs* (for rungs 1–2: it generates payloads; for rung 3: it generates claims from evidence; for rung 4: it generates plans). Rung 5 candidates are generated once, reused across judges.
2. **Blinding:** strip all generation metadata (no "this is my output", no trace, no narration). Shuffle item order with recorded seed. Arm labels (which model judged) removed before any human review.
3. **Judgment arms (2×2 + 1):**
   - A: same-model judge, neutral-entailment framing, binary verdict + stated confidence (0–100%).
   - B: same-model judge, error-hunting framing ("find the flaw"), binary verdict + confidence.
   - C: same-model judge, neutral framing, MCQ-with-abstain (VALID/INVALID/CANNOT-DETERMINE for rungs 1–2; ENTAILED/CONTRADICTED/UNVERIFIABLE for rung 3; VALID/INVALID-FIRST-FAULT-AT-STEP-k for rung 4).
   - D: **different-model** critic (larger or simply different weights), neutral framing, binary + confidence — tests H-INDEP.
   - E (selection control): same-model picks best of 3 candidates per item — measures *selection*, labeled separately, never mixed into judgment numbers (Huang's razor).
4. **Least-privilege evidence rule** (from §3.1): the judge sees the *artifact* (payload, claim+evidence, plan+tool definitions) and **nothing else** — no execution trace, no generator narration, no prior checker verdicts. Violation of this rule invalidates the run.
5. **Random-selection baseline:** for every judgment, also score a random pick from the candidate set — DG-DIFF = judge accuracy − random accuracy (SELF-[IN]CORRECT method).

### 5.4 Scoring

Per rung, per arm (all UNRUN until executed):
- **Primary:** accuracy = (TP+TN)/N, reported as `point (95% Wilson CI, n=10)`.
- **DG-DIFF:** discrimination accuracy − generation/random baseline accuracy on matched items.
- **(TPR, FPR):** true/false positive rates with Wilson CIs — these feed the §6 POMDP directly.
- **Brier score** on stated confidences: BS = (1/N)Σ(pᵢ−yᵢ)²; report per rung.
- **Reliability diagram spec:** 10 equal-width bins over stated confidence; plot bin mean confidence (x) vs empirical accuracy (y); report ECE = Σ(|Bₖ|/N)·|acc(Bₖ)−conf(Bₖ)|. Perfect calibration = 45° diagonal. Expect: systematic overconfidence (points below diagonal), worst on rungs 3–4 [MC].
- **Cohen's κ:** judge verdicts vs ground-truth labels (per rung).
- **False-positive rate on known-correct items**, by framing arm (tests H-FRAME).
- **Pairwise arm comparisons:** McNemar's test on discordant items (same item set, paired design); Holm correction across the arm comparisons.

### 5.5 Power honesty and the two-stage rule

With n=10 per rung, the 95% Wilson interval is wide: 9/10 correct → CI (0.60, 0.98); 10/10 → (0.72, 1.00). **The pilot cannot confirm ≥90%** — its lower bound never reaches 0.90. This is stated up front, not discovered later.

- **Stage 1 (pilot, n=10/rung):** screens for catastrophic failure. Kill rule: if any rung's point accuracy < 70%, the rung's LLM-judge candidacy is dead without needing Stage 2.
- **Stage 2 (confirmatory, n=50/rung):** required before any deploy decision. Pre-registered decision rule (§5.6) uses the lower Wilson bound.

### 5.6 The decision rule that consumes the results (pre-registered)

For each rung, after Stage 2 (n=50):

```
IF lower_95_Wilson_bound(accuracy) ≥ 0.88 AND point_accuracy ≥ 0.93
   AND no deterministic checker achieves ≥ that accuracy at lower cost
   → LLM-judge DEPLOYED for that rung (with calibrated confidences, claim-level, least-privilege evidence)
ELIF deterministic checker exists (complete or partial)
   → DETERMINISTIC checker deployed; LLM-judge REJECTED for that rung
ELSE
   → ESCALATE: different-model critic (calibrated, least-privilege) or human, per §6 math
```

Notes:
- The 0.88/0.93 bar (not 0.90 flat) is deliberate: with n=50, 47/50 (94%) gives Wilson CI ≈ (0.84, 0.98) — fails; 48/50 (96%) gives ≈ (0.86, 0.99) — fails; 49/50 gives (0.895, 0.997) — passes the 0.88 bound. The rule therefore demands **near-perfect** performance, which is the honest price of trusting a judge. No rung is expected to pass on rungs 3–5; the rule is written to make that outcome *decisive*, not disappointing.
- Rungs 1–2 will fail the "no deterministic checker" clause even if they pass the accuracy bar — the deterministic checker is 100% and free. **The expected outcome of this study is that zero rungs deploy an LLM self-judge.** The study's value is in making that a measured result instead of a hunch.
- Any ship decision additionally requires: ECE ≤ 0.10 after isotonic calibration on a held-out split (from CLAIM-CAL: uncalibrated ECE ~0.21 is disqualifying), and κ ≥ 0.60 against ground truth (learn-evaluation-science.md's stricter bar).

---

## 6. AutoMix-style escalation math — POMDP over noisy self-verification [DESIGN]

### 6.1 Formalization (JARVIS adaptation)

AutoMix (Aggarwal et al., NeurIPS 2023): small model generates → few-shot self-verification **framed as entailment** produces a noisy confidence score v → a **POMDP router** decides escalation, because the verification is noisy and LLMs are poorly calibrated. >50% cost reduction at comparable performance; up to 89% improvement in incremental-benefit-per-cost on LLaMA2-13B/70B.

JARVIS's version — states, observations, actions, costs:

- **State** s ∈ {ok, bad}: is the draft output (tool call, claim, plan) acceptable?
- **Observation** o = verifier verdict v ∈ {pass, flag} (binarized at threshold t; the continuous-score version is a straightforward extension). The verifier is noisy with **measured** rates from the §5 study: TPR = P(flag | bad), FPR = P(flag | ok). (This is the "Noisy but Valid" parameterization: judge quality = two numbers from a holdout, not a vibe.)
- **Prior** b₀ = P(ok): from the Beta-Bernoulli ledger for the relevant class (tool reliability, claim-type base rate) — learn-math-for-jarvis.md §2. Not from the model's mouth.
- **Belief update** (Bayes, one line): on observing `flag`,
  b₁ = P(ok | flag) = FPR·b₀ / (FPR·b₀ + TPR·(1−b₀)).
  On `pass`, replace FPR→(1−FPR), TPR→(1−TPR).
- **Actions**: `accept` · `escalate_check` (deterministic deep check or different-model critic, cost c_c) · `escalate_human` (cost c_h ≫ c_c).
- **Costs**: c_v = verifier compute (must be ≪ object-level; ≤5% metalevel rule); L = expected loss of accepting a bad output — **asymmetric by risk tier** (learn-math-for-jarvis.md §3): L_low (reversible chat) ≪ L_critical (irreversible file deletion).

**Decision rule (expected-cost minimization):**
```
EU(accept | o)        = (1 − b₁) · L
EU(escalate_check| o) = c_c + (1 − b₂) · L        # b₂ = posterior after the stronger check
EU(escalate_human|o)  = c_h                       # human assumed to resolve correctly
→ take argmin. Escalate iff (1 − b₁)·L > min(c_c + (1−b₂)·L, c_h).
```

### 6.2 Worked reading of the rule (symbolic — numbers are measured inputs, not inventions)

- The escalation condition is VoI in disguise: escalate only if the expected mistake cost (1−b₁)·L exceeds the check's cost — "information has no value unless it can change a decision," and here the "decision" is accept-vs-escalate.
- **When the verifier is near-chance** (rung 4–5: TPR≈FPR), b₁≈b₀ — the observation moves the belief negligibly, EU(accept)≈EU without verification, and the rule correctly says: *the verifier is worthless; decide on prior × stakes alone* (accept if L small, escalate to human if L large). The math degrades gracefully exactly where the judge does.
- **When the verifier is decent but noisy** (rung 3: TPR≈0.75, FPR≈0.20 [hypothesized]), the POMDP earns its keep over a hard threshold: a `flag` on a low-stakes action with a reliable tool (b₀ high) still accepts; the same `flag` on an irreversible action (L huge) escalates. Thresholds can't do this; posteriors can. This is AutoMix's lesson restated: **don't hard-threshold a noisy signal.**
- **Calibration enters through b₁**, not through the model's stated confidence. The model's verbalized p is *not* used (CLAIM-CAL: raw ECE ~0.21). If stated confidences are ever used, they pass through isotonic calibration fit on the §5 heldout first.

### 6.3 Tier budgets consume the math (from learn-bounded-rationality.md)

| Modality | What the POMDP is allowed to do |
|---|---|
| **Voice** (<300ms barge-in) | No serial LLM verification, ever. The verifier on the live path is a ≤30ms classifier or a deterministic check; escalation = *deferral* (acknowledge now, verify in background) or pre-computed policy (irreversible → always confirm). The POMDP runs *offline* to set those policies, not online per turn. |
| **Chat** (seconds) | One verification round + one escalation step affordable. `escalate_check` = deterministic deep check or different-model critic, not same-model re-read. |
| **Background** (minutes) | Full loop: verify → escalate_check → escalate_human; tree search allowed **iff** the §5 study measured the discriminator ≥90% (lower bound) — otherwise search stays off by the precondition rule. |

**The metalevel budget law holds:** the POMDP update is arithmetic on (b₀, TPR, FPR) — microseconds. The *verifier call* c_v is the cost that must stay ≤5% of the modality budget. A same-model "review your plan" call costs ~1–5s and blows the voice and chat budgets simultaneously — which is why the bounded-rationality file's NEVER rule ("no LLM-judge router on the live path") and this file's squeeze argument agree.

---

## 7. The null-hypothesis architecture — JARVIS with ZERO self-judgment [DESIGN]

If the study confirms H-GRAD (expected), no LLM ever judges its own output. What replaces each rung:

| Rung | Replaced by (deterministic / external) | Residual uncertainty handling |
|---|---|---|
| 1. Syntax | `json.loads` at the tool-call boundary. Malformed → reject + regenerate (regeneration is not judgment). | None — complete. |
| 2. Schema | Pydantic validation against each tool's schema at the boundary. Invalid → reject + regenerate with the schema error (external signal — this is Reflexion-shaped, and legal). | None — complete. |
| 3. Factual grounding | **Verbatim-quote rule:** any factual claim about retrieved content must carry a verbatim quote; substring check against the chunk. Paraphrased claims without quotes → ledger flag `UNVERIFIED`, confidence from base rates, never from self-report. Claim-level, not answer-level (CLAIM-CAL). | Paraphrase entailment → escalate per §6 (different-model critic with least-privilege evidence, or human on high stakes). |
| 4. Plan quality | **STRIPS-lite action model:** every tool declares preconditions and effects in a typed registry; a symbolic plan validator runs the chain before execution. Violations → refuse + replan. Plus **verify-after-acting**: re-read the UI tree / filesystem after each consequential step and compare observed vs declared effect (the environment is the verifier). | Semantic faults the symbolic check misses → different-model critic on high-stakes plans only, or human gate. |
| 5. Novelty/taste | **Nothing.** No judge of any kind. Candidates go to Owais (Bradley-Terry, n=1 protocol) or ship with a neutral default. | Admitted openly: "taste is yours, sir." |

**Cross-cutting rules of the null architecture:**
1. **No same-model self-review anywhere** — not as safety, not as quality, not as routing. (The [VC]-backed ban from learn-research-frontiers.md.)
2. **Least-privilege evidence:** any critic (different model, offline eval) sees the artifact only — never the trace, never the generator's narration, never another checker's verdict inline. Checkers write to the **belief ledger**, not into prompts. (From the trace-contamination finding: 78–90% false accepts when small judges see success-reporting traces.)
3. **Confidence comes from measurement, not introspection:** the Beta-Bernoulli ledger (tool reliability from observed successes/failures), base rates from the golden set, calibrated TPR/FPR from §5. The brain's verbalized confidence is **not an input** to any gate unless isotonic-calibrated on heldout data (ECE ≤ 0.10).
4. **Uncertainty is admitted, not laundered:** the ledger carries `UNVERIFIED` flags with (claim, source, staleness). Escalation fires on (low confidence × high stakes) per §6 — never on a single hard threshold over a noisy signal.
5. **Self-consistency (selection) stays legal; self-verification (judgment) does not.** Best-of-N with majority vote needs no judge and keeps its measured gains. Any "pick the best" step that uses the model as the picker must be labeled *selection* and can never be cited as evidence that *judgment* works.
6. **The one sanctioned LLM-judge:** a *different, larger* model, used **offline** (eval harness, batch), with least-privilege evidence, calibrated against Owais's labels (κ reported) — exactly learn-evaluation-science.md §3.2's "calibrated LLM judge as second rater." It never sits on the live path.

**What the null architecture cannot do (honest scope):** it cannot catch semantic plan faults that pass the symbolic check on low-stakes tasks (accepted residual risk — the stakes don't justify the check); it cannot verify paraphrased claims without escalation (cost accepted on high-stakes only); it has no taste. These are admitted limitations, not hidden ones — which is precisely what makes the architecture trustworthy where self-verification is not.

---

## 8. Record — evidence table

| Claim | Source | Confidence |
|---|---|---|
| Intrinsic self-correction via prompting frequently degrades performance; gains trace to oracle feedback | Huang et al., arXiv:2310.01798 (2023) | [VC] |
| Failure bottleneck is error detection, not correction | Tyen et al. 2024 (+ 2024–2026 replications, via learn-research-frontiers.md) | [HC] |
| Error-hunting prompts → >10× false-positive rate; reflection net ≈ +1% at best | "Self-Reflection Outcome is Sensitive to Prompt Construction" (2026, via learn-research-frontiers.md) | [MC] |
| DG-DIFF small/negative in 54/56 experiments; LLMs not reliably better at discriminating than generating own outputs | SELF-[IN]CORRECT, AAAI 2025 | [HC] |
| Small LMs become better refiners via self-collected fine-tuning but still need strong verifiers | SCORE, arXiv:2404.17140 (2024) | [HC] |
| Trace reporting success makes 7–32B open judges accept 78–90% of failures; frontier judges unmoved; checker verdicts launder into stronger judges (0.69 false accepts) | "Don't Read the Log", arXiv:2609.28564 (2026) | [HC] |
| Few-shot self-verification as entailment + POMDP router; >50% cost reduction; +89% incremental-benefit-per-cost | AutoMix, Aggarwal et al., arXiv:2310.12963 (NeurIPS 2023) | [HC] |
| Judge quality as (TPR, FPR) from small holdout → finite-sample error control | "Noisy but Valid", Maia Polo et al., arXiv:2601.20913 (2026) | [HC] |
| Claim-level verification + isotonic calibration: ECE 0.212 → 0.038 | CLAIM-CAL (via scienmag.com secondary report, 2026) | [MC] |
| CoVe: draft → plan verification questions → answer independently → regenerate | Dhuliawala et al., arXiv:2309.11495 (2023) | [HC] |
| FOBAR: backward verification + self-consistency as re-ranker | Weng et al., arXiv:2212.09561 (2022) | [HC] |
| Trained verification co-evolves with generation via RL (test-case accuracy 50%→88%; >85% judgment on valid tests) | ReVeal, ICLR 2026 | [MC] (one paper) |
| Tree search needs ≥90% discriminator; LLM self-discriminators generally don't meet it | "When is Tree Search Useful…", via learn-frontier-reasoning.md | [MC] |
| H-GRAD hypotheses (rung accuracies for 4–9B self-judges) | This cycle's hypotheses — extrapolated from above | [SP]–[MC] as tagged in §2 |
| Tier budgets, ≤5% metalevel, no LLM-judge router on live path | learn-bounded-rationality.md (design requirements) | [MC] as targets |

**Real references (no fabricated citations):** Huang et al. 2023 (arXiv:2310.01798); Tyen et al. 2024; Pan et al. 2023 (arXiv:2308.06808); SELF-[IN]CORRECT, AAAI 2025 (ojs.aaai.org/index.php/AAAI/article/download/34603/36758); SCORE (arXiv:2404.17140); "Don't Read the Log" (arXiv:2609.28564); Aggarwal et al. 2023 (arXiv:2310.12963); Maia Polo et al. 2026 (arXiv:2601.20913); Dhuliawala et al. 2023 (arXiv:2309.11495); Weng et al. 2022 (arXiv:2212.09561); Wang et al. 2023 self-consistency (ICLR 2023); Shinn et al. 2023 Reflexion; Madaan et al. 2023 Self-Refine; Chen et al. 2023 Self-Debug; ReVeal, ICLR 2026; Chiang et al. 2024 (arXiv:2403.04132); Bradley & Terry 1952.

---

## 9. Reassess — unknowns, falsifiers, open-problem update

### Falsification criteria (pre-registered)

| # | Claim | Falsifier | Status |
|---|---|---|---|
| F1 | H-GRAD: rungs 1–2 ≥90%, rungs 3–5 <80% | Stage-2 results contradict any rung's band (lower Wilson bound outside hypothesized band) | UNRUN — the study is the experiment |
| F2 | The squeeze: no rung deploys an LLM self-judge | Some rung passes the §5.6 decision rule (lower bound ≥0.88, point ≥0.93, no deterministic alternative) | UNRUN — would be a genuine discovery; the rule is written to recognize it |
| F3 | H-INDEP: different-model critic beats same-model by ≥10pp on rungs 3–4 | Arm D vs Arm A difference <10pp (McNemar, Holm-adjusted) | UNRUN |
| F4 | H-FRAME: error-hunting framing ≥3× FP rate | FP ratio <3× or reversed | UNRUN |
| F5 | POMDP escalation beats hard threshold on cost-per-averted-error | Simulate both policies on §5 (TPR,FPR) + tier costs; threshold wins | UNRUN — needs study outputs + cost numbers |
| F6 | Least-privilege evidence matters for JARVIS's judges | Ablation: judge with trace vs without; no accuracy difference | UNRUN — predicted to replicate the 78–90% contamination finding |

### Explicit unknowns [UK]
1. **All §5 measurements** — the study is designed, not run. No model access in this environment.
2. Whether trained verification (ReVeal-style RL) transfers to a 4–9B local brain on tool-use trajectories — the most promising escape hatch from the prompting bottleneck, and the natural 2060-LoRA-track experiment.
3. The actual (TPR, FPR) of any verifier on JARVIS's real tool set — the POMDP's core input.
4. Cost numbers L per risk tier and c_h (human interruption cost for Owais specifically) — needed to operationalize §6.
5. Whether MCQ-with-abstain framing actually improves rung-3 calibration (H-ABSTAIN) or just shifts errors.

### Open-problem #3 status update
Was: "discriminator accuracy on JARVIS's tool set — unmeasured; gates all of Strategy 3/4." Now: **measurement designed (§5), decision rule pre-registered (§5.6), escalation math formalized for whatever the numbers turn out to be (§6), null architecture specified for the expected outcome (§7).** The problem is unblocked *as a measurement program*; the numbers themselves await the 2060 shootout. State-of-knowledge: [HC] on the design, [UK] on the measurements.

### Recommended next cycles
(a) The 2060 model shootout (open-problem #1) — executes §5 Stages 1–2 as part of its eval battery; (b) the golden-set build (open-problem #4) — hosts the 50 items; (c) a trained-verifier spike (ReVeal-style, LoRA on tool trajectories) — the one result in §3 that suggests the bottleneck is escapable.

**One-line verdict for the ledger:** Self-verification isn't a capability JARVIS failed to build — it's a capability the literature says doesn't exist in prompting form. The honest architecture doesn't ask the brain whether it's right; it checks the world, counts the errors, and escalates on the math. The study in §5 exists to turn that from a literature consensus into a measured fact about our specific brain — and the decision rule is pre-registered so the measurement can surprise us.
