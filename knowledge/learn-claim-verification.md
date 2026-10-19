# CLAIM-VER: Claim-Level Fact Verification for JARVIS

**Cycle 11 — Phase Infinity research. Status: LEARNING ONLY — no code, no installs, no execution.**
**Date:** 2026-10-19. **Question:** How does JARVIS verify factual claims in its answers *without trusting its own judgment*?

## TL;DR

Cycle 7's squeeze: an LLM judging whole-answer factuality (~70–78% hypothesized) fails the 90% discriminator bar, and deterministic checkers can only verify syntax, not truth. The answer is a **claim pipeline**: decompose the answer into atomic checkable claims (FActScore's atomicity), run each down a **4-rung verification ladder** where rungs 1–2 are deterministic or near-deterministic (verbatim quote match, then small NLI entailment), reserve LLM judgment for nothing it can't be checked on, and **abstain honestly** where verification is inconclusive. The pipeline is the factual half of "the verifier is the strategy" — the twin of the plan validator from the null-hypothesis architecture (learn-self-verification-calibration.md).

**Headline numbers (all sourced below):**
- Claim-level beats whole-answer: claim-level factuality calibration reaches ECE 0.266 with RL (vs 0.301 SFT) [Linguistic Calibration, 2404.00474]; confidence-guided *per-claim* verification pipelines are now the working pattern [PCC, 2601.02574].
- Atomic-claim decomposition is validated: FActScore's automated estimator matches human fact labels within <2% error [Min et al. 2023]; SAFE agreed with crowd annotators on ~16k facts 72% of the time and won 76% of disagreements [Wei et al. 2024].
- Specialized entailment beats generic NLI on grounding: vanilla MNLI-trained metrics score ~48 AUC on SummaC while AlignScore (alignment-trained, 4.7M examples) scores ~88.6 [Zha et al. 2023].
- DeBERTa-v3-small (44M backbone / 142M total, ~INT8-size for the CPU tier) hits 88.3/87.7 MNLI-m/mm officially [Microsoft/Azure catalog] — but that number does **not** transfer cleanly to chunk/claim grounding (domain shift, §4).

---

## 1. Claim extraction: the spec

### 1.1 What counts as atomic

Definition (adapted from FActScore, Min et al. 2023 [VC]): an **atomic claim** is a short statement conveying **a single piece of information** — one predicate, one entity (after coreference resolution), one number, one relation. Anything that can be true/false independently of the rest of the sentence gets its own claim.

Concrete atomicity rules:
1. **One predicate per claim.** "Pinecone is a managed vector database that claims sub-50ms latency" → two claims: (a) Pinecone is a managed vector database; (b) Pinecone claims sub-50ms latency.
2. **Coreference resolved at extraction.** SAFE's pipeline explicitly revises each fact to be self-contained, replacing pronouns with the entities they refer to [Wei et al. 2024] [VC]. Claim "It trades recall for speed" is not checkable; "HNSW trades recall for speed" is. Extraction output must be self-contained: an annotator (or NLI model) with no access to the original answer must be able to judge it.
3. **Numbers and units stay attached.** "sub-50ms" ≠ "50ms" ≠ "fast". The number, unit, and measured quantity are part of the atom.
4. **Comparisons split into their conjuncts.** "Unlike traditional databases, which index exact values with B-trees…" → (a) traditional relational databases index exact values; (b) they use B-trees for this. The *contrastive frame* is preserved as a third claim only if the answer asserts the contrast ("vector DBs do X, traditional DBs do Y" → the contrast itself is a claim about the two systems).
5. **Conjunctions distribute; disjunctions don't.** "A and B" → two claims. "A or B" → one claim (falsifying one disjunct doesn't falsify the claim).

### 1.2 Qualifiers: don't strip them, don't trust them

Hedges ("usually," "in most cases," "typically," "often") are the extraction pipeline's trap: stripping them makes the claim stronger than the answer stated (a verification false-positive factory); keeping them naively makes everything unverifiable.

**Rule [design, MC]:** the qualifier becomes part of the claim's truth conditions, and each qualifier class gets a check rule:
- **Frequency hedges** ("usually," "typically," "in most cases"): checkable *only if* a chunk states the frequency or the generality. Chunk says "HNSW is commonly used" → "HNSW is commonly used" passes by entailment; "HNSW is usually used" against a chunk that only describes HNSW neutrally → **inconclusive** (the frequency assertion is ungrounded), not failed.
- **Epistemic hedges** ("may," "might," "could"): demote to *possibility claims*. "X may cause Y" is verified by a chunk stating X is a possible cause — a much weaker bar, correctly so.
- **Approximators** ("about," "roughly," "~"): number match with tolerance (±10% as a default band; band width is a config, not a judgment).
- **Attribution hedges** ("Pinecone claims…", "according to…"): the claim is about the *claiming*, not the fact. Verifiable against a chunk quoting the vendor — this is how marketing numbers get handled honestly (see worked example, claim C5).

**Banned move:** silently dropping a hedge to make a claim checkable. That is hallucination laundering.

### 1.3 Uncheckable claims: the pipeline must abstain, not hallucinate a verdict

Extraction classifies every extracted unit into exactly one type [design, follows Litmuz's "honest negatives" principle — see §5]:

| Type | Examples | Verdict allowed |
|---|---|---|
| **Factual** | "HNSW is an approximate index", "B-trees index exact values" | verified / contradicted / inconclusive |
| **Opinion** | "HNSW is the best choice", "I find Pinecone elegant" | labeled `opinion` — never "verified" |
| **Advice** | "You should use IVF for this", "Consider sharding" | labeled `advice` — checkable only against cited best-practice sources, else `ungrounded-advice` |
| **Creative** | analogies, metaphors, illustrative examples flagged as such | labeled `illustrative` |
| **Procedural/meta** | "Here's what I found", "Let me check", greetings, questions back | skipped (not claims at all) |

An opinion sent down the entailment ladder will either fail spuriously or — worse — pass on lexical overlap. **Abstention is a first-class output**, not an error path. This mirrors Litmuz's traffic-light design where "yellow" (needs review / unverifiable) is a legitimate terminal state [litmuz.co] [HC].

### 1.4 Extraction output format (spec)

```json
{
  "claims": [
    {
      "id": "C1",
      "text": "Vector databases store embeddings.",
      "type": "factual",
      "qualifiers": [],
      "source_spans": ["answer sentence 1, chars 0-38"],
      "check": { "rung": 1, "verdict": "verified", "evidence": ["chunk 3, exact quote"], "confidence": 0.99 }
    },
    {
      "id": "C5",
      "text": "Pinecone claims sub-50ms query latency at 100M-vector scale.",
      "type": "factual",
      "qualifiers": ["attribution: vendor claim"],
      "source_spans": ["answer sentence 4"],
      "check": { "rung": 4, "verdict": "inconclusive", "evidence": [], "confidence": null }
    }
  ],
  "abstained": [
    { "id": "C6", "text": "For your use case I'd start with brute force.", "type": "advice", "reason": "recommendation, no source cited" }
  ]
}
```

Notes: `confidence` is populated only for rungs 1–3; inconclusive/uncheckable carry `confidence: null` (no number invented — RLCD honesty). `evidence` is always chunk IDs + quoted spans, never free text (the verbatim-quote grounding rule from learn-self-verification-calibration.md).

---

## 2. The verification ladder (4 rungs)

Each factual claim descends the ladder; the **first rung that yields a decisive verdict wins**; inconclusive at all four → flagged. This is the per-claim analog of PCC's "adaptively select tailored verification strategies for each claim" [2601.02574] [HC].

### Rung 1 — Verbatim quote (deterministic, ~100% precision)

**Rule:** the claim's normalized text appears as a substring of a retrieved chunk (normalization: lowercase, strip punctuation, collapse whitespace; optional light stemming — NOT paraphrase).

- **Cost:** ~free (string ops). **Accuracy:** a match means the exact proposition was retrieved; false positives ≈ 0 modulo normalization bugs [VC — this is definitional].
- **Scope limit:** recall is low — maybe 20–40% of claims in a RAG answer are verbatim [SP, design estimate]. That's fine; rung 1 is a fast lane, not the whole road.
- **Guard:** the match must be to a *retrieved chunk*, not to the answer itself (self-plagiarism is not grounding — the null-hypothesis architecture's verbatim-quote rule already requires the quote come from retrieved evidence).
- **Negation guard:** quote match on a negated claim requires the negation token be inside the matched span. "X is not Y" matching chunk "X is not Y" is fine; matching "X is Y" after stripping "not" is a bug — normalization must never delete negation tokens (see §7 failure modes).

### Rung 2 — Entailment by a small NLI model (~90% on MNLI, less on grounding)

**Rule:** claim is entailed by one cited chunk, judged by a small local NLI/alignment model (premise = chunk, hypothesis = claim). Threshold on P(entailment); contradiction above threshold → `contradicted`.

- **Cost:** one forward pass per (chunk, claim) pair on a ~44M-backbone model — CPU-feasible, milliseconds-to-tens-of-ms per pair [SP, design estimate; no measured JARVIS-tier number exists — this is an unknown to measure, §8].
- **Accuracy:** DeBERTa-v3-small scores 88.3/87.7 on MNLI-m/mm [Microsoft/Azure model catalog] [VC]; a community multi-dataset binary variant (moritzlaurer/deberta-v3-small-mnli-fever-docnli-ling-2c, trained on 1.28M pairs from 8 NLI datasets) reports MNLI-m 0.927 / FEVER-NLI 0.892 but drops to **0.684 on ANLI-all** [dataloop.ai model card] [HC — third-party card, not peer-reviewed]. The honest headline: **~90% in-distribution, meaningfully worse under adversarial or domain-shifted inputs** (§4).
- **Scope:** handles paraphrase, the case rung 1 can't. Claim "retrieval uses approximate nearest-neighbor search" vs chunk "retrieval uses approximate nearest neighbor algorithms such as HNSW" → entailment.
- **Design choice:** prefer a **3-way head** (entail/neutral/contradict) over binary. AlignScore's ablations found the 3-way classification head outperformed binary and regression heads for factual-consistency scoring [Zha et al. 2023] [HC]. Contradiction is a signal we need (a contradicted claim must be *removed or corrected*, not merely flagged inconclusive).

### Rung 3 — Multi-hop, verified stepwise with the chain recorded

**Rule:** claims needing 2+ chunks. The extractor (or a decomposition step) splits the claim into sub-claims, each sub-claim is verified at rung 1 or 2 against its own chunk, and the **inference chain is recorded** as evidence: `C4 ⊢ (chunk A: rung 1) ∧ (chunk B: rung 2)`.

- **Cost:** linear in hops × rung cost, plus one decomposition call. Multi-hop is where "performance of semantic-matching models degrades significantly as the number of reasoning hops increases" [HoVer, Jiang et al. 2020] [VC] — budget accordingly.
- **Chain discipline:** every hop must cite; a chain with a missing link is inconclusive, not verified. HoVer's design lesson: claims were *deliberately* written to minimize semantic overlap with supporting documents to defeat word-matching shortcuts [Jiang et al. 2020] [VC] — our rung-2 entailment must not be allowed to "bridge" a hop by lexical similarity alone; each hop needs its own decisive verdict.
- **Program-guided precedent:** complex claims can be decomposed into executable reasoning programs (question-answering sub-steps composed with logic) — "Fact-Checking Complex Claims with Program-Guided Reasoning" [academia.edu] [MC]. For JARVIS v1, stepwise natural-language sub-claims with recorded verdicts suffice; program-guided decomposition is the v2 upgrade.

### Rung 4 — Ungrounded: flagged, never silently passed

**Rule:** no chunk supports the claim after rungs 1–3 (or the only "support" is the model's own parametric memory). Verdict: `inconclusive — ungrounded`. The claim **stays in the answer only with an explicit marking** (§5), or the pipeline escalates: re-retrieve with the claim as query (one retrieval retry — RARR's "research" step [Gao et al. 2023] [VC]), then mark if still unsupported.

- **Cost:** one extra retrieval round-trip in the worst case; bounded by the stopping rule (§7).
- **This rung is the whole point.** The squeeze argument says the LLM's own judgment of factuality is ~70–78% and untrustworthy; rung 4 is where that judgment is *refused* rather than laundered.

### Ladder summary

| Rung | Mechanism | Precision (reported/estimated) | Cost per claim | Decisive? |
|---|---|---|---|---|
| 1 | Verbatim quote match (deterministic) | ~100% [definitional] | ~0 | yes/no |
| 2 | Small NLI entailment vs one chunk | ~90% in-dist, lower shifted [§4] | 1 forward pass | entail/contradict/neutral |
| 3 | Multi-hop stepwise, chain recorded | degrades with hops [HoVer] | hops × rung 1/2 + decompose | only if all hops decisive |
| 4 | Ungrounded → flag or retrieval retry | n/a (abstention) | ≤1 extra retrieval | no — marked |

---

## 3. NLI models for entailment: what's available small and local

### 3.1 The candidate: DeBERTa-v3-small

- **Size:** 44M backbone parameters / 142M total (128K-token SentencePiece vocab dominates) [Microsoft via ai.azure.com catalog; aiwiki.ai] [VC]. The "140MB" figure from the task brief ≈ INT8-quantized footprint; fp32 is ~570MB, fp16 ~285MB. **Honest sizing: fits the CPU tier only quantized** [MC].
- **Reported accuracy:** MNLI-m/mm **88.3/87.7** on dev (official catalog numbers) [VC]. SiFT variant: 88.8/88.5.
- **Multi-dataset variant:** `moritzlaurer/deberta-v3-small-mnli-fever-docnli-ling-2c` — fine-tuned on 1,279,665 pairs from 8 NLI datasets (MNLI, FEVER-NLI, DocNLI, LingNLI etc.), **binary** entailment/not-entailment. Reports MNLI-m 0.927, MNLI-mm 0.921, FEVER-NLI 0.892, **ANLI-all 0.684, ANLI-r3 0.673** [dataloop.ai model card] [HC]. The FEVER-NLI 0.892 is encouraging (fact-verification-flavored data helps); the ANLI 0.684 is the warning label.
- **Caveat on the card:** binary head loses the contradiction signal (§2 rung 2 prefers 3-way). And "not-entailment" conflates neutral with contradiction — for verification, neutral (inconclusive) and contradiction (remove the claim) demand different actions.

### 3.2 The domain-shift problem (the honest core of this section)

MNLI/SNLI/ANLI are **premise/hypothesis pairs written by crowdworkers** (image captions, 10 genres of text) [Williams et al. 2018; ar5iv 1909.08940] [VC]. Our rung-2 inputs are **retrieval chunks vs machine-extracted claims**: long noisy premises, claims with resolved coreference, heavy neutral-class prevalence, technical vocabulary, numbers. Known gaps:

1. **Annotation artifacts don't transfer — but new ones appear.** Hypothesis-only baselines beat chance on SNLI/MNLI because crowdworkers leak label cues ("nobody," "sleeping" → contradiction) [Poliak et al. 2018; Gururangan et al. 2018, via alphaxiv review] [VC]. Our pairs have no crowdworker — but they have *retrieval* artifacts: high lexical overlap between claim and chunk (the claim was often generated *from* the chunk's neighborhood), which models read as entailment. McCoy et al. showed high-overlap pairs are systematically mislabeled entailment by models [McCoy et al. 2019, via ar5iv 2209.03392] [VC].
2. **Negation and scope are the known kill zone.** A checklist study of an ELECTRA-small SNLI model: **99.8% failure on basic negations**, 94.4% on neutral terms in context, 100% on sophisticated negations [zhenyuanlu.com artifacts analysis] [MC — single study, small model, but direction matches the broader literature]. INLI (2025-era work) shows standard NLI models perform at **chance on implicit entailment** unless specifically augmented [emergentmind NLI topic review] [MC]. PrefixNLI error analysis: 33% of false positives from surface-level heuristic bias, 43% of false negatives from failed implicit reasoning [arxiv 2511.01359] [MC].
3. **The measured gap:** on adversarial NLI (ANLI), the best small binary model drops to 0.684 [HC]. There is **no published number I could find for DeBERTa-v3-small specifically on retrieval-chunk/claim grounding pairs** [UK — genuine unknown; the closest proxies are AlignScore's SummaC numbers and the FEVER-NLI 0.892].

**Bottom line [MC]:** expect rung-2 accuracy on real grounding pairs to sit **meaningfully below 88%** — plausibly low-80s on clean paraphrase, worse on negation/scope/numbers. This is *why the ladder exists*: rung 2 is not the truth oracle, it's a filter between deterministic quote-match and honest abstention, and its verdicts should carry confidence < 1.0 into the UX contract.

### 3.3 The specialized alternative: AlignScore

AlignScore [Zha et al. 2023, arXiv 2305.16739] [VC] is the existence proof that training *for* grounding beats repurposing NLI:
- Unified alignment function trained on **4.7M examples across 7 tasks** (NLI, QA, paraphrase, fact verification, IR, semantic similarity, summarization) — i.e., it trains on the domain shift rather than hoping to survive it.
- Chunk-level scoring: context split into ~350-token chunks, **each claim sentence scored against all chunks, max taken, then averaged** — structurally identical to our ladder's rung 2/3 routing.
- Results: **AlignScore-large 88.6 avg AUC on SummaC vs ~47.9 for a vanilla MNLI metric**; matches or beats larger LLM-based metrics on 22 benchmarks, 19 of them zero-shot [VC].
- Cost: 355M parameters (RoBERTa-large scale) — roughly 2.5× our small model's total params. Fits CPU but slower; the `-base` variant (87.4 avg) is the budget option.

**Design recommendation [MC]:** ship rung 2 with the multi-dataset DeBERTa-v3-small binary model *re-headed to 3-way* (or the official MNLI 3-way checkpoint) as the cheap default; keep AlignScore-base as the documented upgrade path when per-claim compute budget allows. Do not present MNLI accuracy as grounding accuracy anywhere in user-facing or scorecard material.

---

## 4. The abstention design: UX contract

### 4.1 The contract (normative — this is the design)

Every factual claim in a delivered answer carries exactly one status, and the rendering makes the status **visible, not footnote-buried**:

1. **`verified`** — stated plainly, no marking. (Rungs 1–3 decisive. The default reading of unmarked text is "checked.")
2. **`unverified`** — rendered with an inline mark: *"I couldn't verify this against my sources."* The claim may stay (it's the model's best answer) but the user is told the check failed. Wording is first-person and specific — never "some sources say."
3. **`contradicted`** — never delivered as stated. The pipeline revises (RARR-style post-edit [Gao et al. 2023]) or drops the claim; if revision is impossible, the answer says what the sources actually support.
4. **`opinion` / `advice` / `illustrative`** — labeled as judgment, in the answer's own voice: *"My take:"*, *"Suggestion:"*. These were never candidates for verification (§1.3).

This is Litmuz's traffic-light pattern (green/yellow/red, "yellow and red are first-class outcomes, not failures… an unsupported claim is never dressed up as a pass") [litmuz.co] [HC], transplanted from life-sciences memos to JARVIS answers.

### 4.2 Connection to RLCD calibration

The RLCD principle (SOUL.md: *be calibrated — state uncertainty honestly, never fake confidence*) is what makes rung 4 load-bearing rather than decorative:
- Linguistic calibration work shows models can be trained to emit **numerical and linguistic confidence statements throughout long-form generations**, reaching claim-level ECE 0.266 (RL) vs 0.301 (SFT), with reliability diagrams near the identity line [2404.00474] [VC]. Our pipeline's `confidence` field is the machine-readable version of the same idea; the UX markings are the human-readable version.
- The failure mode RLCD guards against: a verifier that outputs "verified" at 88% accuracy while the UI implies 100%. The contract fixes the *implied* confidence by making unverified status visible — calibration of the interface, not just the model.
- Approval-UX link (from prior cycles): high-stakes claims (medical, financial, legal — the wallet-excluded categories in MEMORY.md) should require **explicit user acknowledgment of unverified status** before acting, mirroring the "money needs his finger on the button" rule. Verification status is a safety gate, not a cosmetic badge.

### 4.3 What the contract does NOT do

It does not certify truth. A `verified` claim means "entailed by retrieved chunk(s)" — if the chunk is wrong, the claim is wrong (the provenance problem, §7). The contract's honesty is about *the check*, not about reality. Say so in the UI copy: "checked against sources," never "true."

---

## 5. Worked example: 5-claim RAG answer, by hand

**User question (technical):** "What's the difference between a vector database and a traditional database, and when would I pick one?"

**Retrieved chunks (the evidence set):**
- **Chunk A:** "Vector databases store high-dimensional vectors called embeddings and retrieve them using approximate nearest neighbor algorithms such as HNSW and IVF."
- **Chunk B:** "Traditional relational databases index exact values with B-tree indexes and answer exact-match and range queries."
- **Chunk C:** "Approximate nearest neighbor methods sacrifice some recall for query speed, which makes them suitable for similarity search at scale."
- **Chunk D:** "For datasets under about one million vectors, brute-force exact search in memory is often fast enough and simpler to operate than maintaining an index."

**JARVIS draft answer:**
> "Vector databases store embeddings — dense numerical vectors produced by embedding models — and retrieve them by approximate nearest-neighbor search. Traditional relational databases index exact values with B-trees and answer exact-match or range queries. Indexes like HNSW trade some recall for query speed. Pinecone, for example, delivers sub-50ms query latency at 100M-vector scale. For your use case I'd start with brute force."

### Extraction (per §1)

| ID | Claim text (self-contained) | Type |
|---|---|---|
| C1 | Vector databases store embeddings. | factual |
| C2 | Traditional relational databases index exact values with B-trees. | factual |
| C3 | Vector databases retrieve by approximate nearest-neighbor search rather than exact match. | factual |
| C4 | HNSW trades some recall for query speed. | factual |
| C5 | Pinecone delivers sub-50ms query latency at 100M-vector scale. | factual (vendor performance claim) |
| C6 | For your use case I'd start with brute force. | **advice → abstained** (labeled "Suggestion:", not verified) |

Note C6: recommendation with no cited source and a user-specific premise ("your use case") the pipeline can't check. Abstain per §1.3 — it ships labeled as advice, not as a verified fact.

### Down the ladder

**C1 — Rung 1, verified.** Normalized claim "vector databases store embeddings" — chunk A contains "Vector databases store high-dimensional vectors called embeddings". Paraphrase gap ("high-dimensional vectors called" inserted) → not verbatim. Falls to **rung 2**: NLI(premise=A, hypothesis=C1) → entailment (high confidence; "embeddings" ≡ "high-dimensional vectors called embeddings" is definitional in context). **Verdict: verified (rung 2), evidence: chunk A.**

**C2 — Rung 1, verified.** Chunk B: "Traditional relational databases index exact values with B-tree indexes and answer exact-match and range queries." Normalized claim "traditional relational databases index exact values with b-trees" is a substring modulo plural/punctuation. **Verdict: verified (rung 1, quote), evidence: chunk B.** (~100% precision — the fast lane working as designed.)

**C3 — Rung 2, verified.** No chunk states "rather than exact match" verbatim. Chunk A gives ANN retrieval for vector DBs; chunk B gives exact-match for relational DBs. Strictly this is a 2-hop contrast (A ∧ B ⊢ C3) — route to **rung 3**: sub-claim (i) "vector DBs retrieve by ANN search" ← chunk A rung 2; sub-claim (ii) "traditional DBs answer exact-match queries" ← chunk B rung 1; the contrast follows. **Verdict: verified (rung 3), chain recorded: C3 ⊢ (A:r2) ∧ (B:r1).** *(Design note: a production extractor might emit C3 as two claims and let the renderer re-join the contrast — §7 failure mode 1.)*

**C4 — Rung 3, verified stepwise.** Chunk A: "HNSW" is listed as an ANN algorithm (rung 1, quote). Chunk C: "Approximate nearest neighbor methods sacrifice some recall for query speed" (rung 2, entailment — "sacrifice" ≡ "trade"). Chain: HNSW ∈ ANN methods (A) ∧ ANN methods trade recall for speed (C) ⊢ C4. **Verdict: verified (rung 3), chain: C4 ⊢ (A:r1) ∧ (C:r2).**

**C5 — Rung 4, flagged.** No chunk mentions Pinecone, sub-50ms, or 100M vectors. Retrieval retry with "Pinecone query latency 100M vectors" returns nothing in the evidence set. **Verdict: inconclusive — ungrounded.** It is a vendor marketing number the model recalled parametrically. Per the contract it ships only marked, or is cut.

### Final rendered answer

> "Vector databases store embeddings and retrieve them by approximate nearest-neighbor search. Traditional relational databases index exact values with B-trees and answer exact-match or range queries. Indexes like HNSW trade some recall for query speed. ⚠️ *I couldn't verify this against my sources:* Pinecone's quoted sub-50ms latency at 100M-vector scale — treat vendor benchmarks skeptically. *Suggestion:* for your use case I'd start with brute force."

Every unmarked sentence was checked; the marked sentence carries its uncertainty; the advice is labeled as advice. That's the contract working.

---

## 6. Failure modes and mitigations

**F1. Claim-splitting destroys meaning.** Splitting "unlike traditional DBs, vector DBs…" into isolated atoms can lose the contrast (worked example C3), temporal scope ("as of 2024"), or quantifier scope ("all" vs "some"). *Mitigation:* extraction keeps a `source_spans` back-pointer and a `scope` field (time, quantity, comparison-frame); the renderer re-joins sub-claims that share a scope before display; contradiction between a claim and its scope-mate is itself a check failure. Splitting is lossy compression — the back-pointer is the decompression key [design, MC].

**F2. Entailment models fooled by negation and scope.** 99.8% failure on basic negations in one checklist study [§3.2]; lexical-overlap → entailment heuristic [McCoy et al.]; chance-level on implicit entailment [INLI]. A claim "X does not support Y" against chunk "X does not support Y" is rung-1 territory (quote match handles it); the danger is rung 2 on paraphrased negation. *Mitigation:* negation tokens are never normalized away (rung 1 guard); rung-2 pairs where claim and chunk differ by a negation cue get routed to a stricter threshold or a second model; contradiction verdicts on negated claims require the negated proposition to appear in the chunk, not merely high overlap.

**F3. Garbage in: the cited chunk is itself wrong (provenance problem).** Verification establishes *grounding*, not truth — a claim entailed by a wrong chunk passes all four rungs. This is the memory-science provenance problem applied to retrieval. *Mitigation (defense in depth):* source trust tiers (primary docs > vendor blogs > scraped forums) recorded per chunk; cross-chunk corroboration required for high-stakes claims (two independent chunks, rung 2 each — the "honest negatives" idea extended: a single-source claim is `verified-single-source`, visibly weaker); retrieval recall matters — the 91% hybrid-search recall from learn-databases.md is a precondition, because a missing chunk forces rung 4 on a true claim (false abstention, the benign direction).

**F4. Verification cost on long answers (budget × stopping rule).** Cost scales as claims × rungs, and rung 3 multiplies by hops. A 40-claim answer with 30% multi-hop is ~60+ model calls plus extraction. *Mitigation (from learn-bounded-rationality.md):* budget by tier — rung 1 first (free, drains the easy claims), then rung 2 batched (one batched forward pass over all remaining pairs, not one call each), rung 3 only for claims the answer's stakes justify; **verify high-stakes claims first, sample the rest** (spot-check 25% of low-stakes claims; a failed spot-check triggers full verification — the audit pattern). The stopping rule: verification halts when marginal cost exceeds the claim's decision value, and unvisited claims ship as `unverified` — which the UX contract already handles gracefully. Abstention is what makes bounded verification *safe*.

**F5. The extractor as a new hallucinator.** Claim extraction is itself an LLM judgment — it can invent claims the answer didn't make (false claims to verify) or drop hedges (§1.2's banned move). *Mitigation:* extraction is constrained generation — every extracted claim must carry `source_spans` pointing into the answer text, and a deterministic checker verifies each claim's content words are traceable to its span (the least-privilege judging rule: the extractor proposes, a deterministic span-checker disposes — neuro-symbolic all the way down, learn-frontier-reasoning.md).

**F6. Threshold tuning without ground truth.** Rung 2's entailment threshold picked by gut feeling is just LLM judgment with extra steps. *Mitigation:* calibrate the threshold on a labeled grounding set (FEVER-style pairs or JARVIS's own logged verdicts with user corrections as labels); report the threshold's precision/recall, not vibes. Until that set exists, default to the conservative side: high threshold, more rung-4 abstentions. Over-abstention is honest; over-verification is the failure mode we're eliminating.

---

## 7. Connections to prior cycles

- **Cycle 7 (self-verification & calibration):** this pipeline is the answer to the squeeze — factual grounding moves from rung 3 of the 5-rung judgment gradation (LLM-judged, ~70–78%) to rungs 1–2 of *this* ladder (deterministic + small-model entailment), with the remainder routed to honest abstention. Least-privilege judging and verbatim-quote grounding are implemented literally in rungs 1 and F5's span-checker.
- **learn-databases.md:** "every factual claim needs a supporting chunk" is the retrieval-side precondition; CLAIM-VER is the verification-side enforcement. 91% hybrid recall bounds the false-abstention rate.
- **learn-evaluation-science.md:** faithfulness ≥0.85 and citation precision/recall are the scorecard metrics this pipeline moves; claim-level FActScore-style measurement is both the design pattern and the eval.
- **learn-bounded-rationality.md:** §6-F4 is the stopping rule applied to verification spend; tiered budgets (free rung 1 → batched rung 2 → selective rung 3) are the mechanism.
- **learn-frontier-reasoning.md:** neuro-symbolic "LLM proposes, verifier disposes" appears twice — extractor vs span-checker, and claim vs ladder.

## 8. Unknowns and next measurements

- [UK] No published accuracy for DeBERTa-v3-small (or any small NLI model) specifically on retrieval-chunk/claim grounding pairs. Proxy numbers: MNLI 88.3/87.7, FEVER-NLI 0.892 (multi-dataset variant), ANLI 0.684. **Next:** build a JARVIS grounding eval set (500 chunk/claim pairs from real answers, human-labeled) and measure rung-2 precision/recall directly.
- [UK] CPU latency per (chunk, claim) pair for DeBERTa-v3-small INT8 on JARVIS-tier hardware. Needed for the budget math in §6-F4.
- [UK] The exact CLAIM-CAL result cited in Cycle 7 (ECE 0.212→0.038): I could not locate a paper by that name. Closest real analogs found this cycle: PCC's confidence-guided per-claim pipeline (ECE reductions on SciFact/HoVer/FeLMWk, arxiv 2601.02574) and Linguistic Calibration's claim-level ECE 0.266 (arxiv 2404.00474). Treat the 0.212→0.038 figure as Cycle 7's internal reference until re-sourced.
- [SP] Rung-1 verbatim hit rate (20–40% estimate) and optimal batching strategy are design guesses awaiting the eval set.

## References (all real, all fetched this cycle)

- Min et al. 2023, FActScore — https://ar5iv.labs.arxiv.org/html/2305.14251 (atomic facts; automated estimator <2% error; `pip install factscore`)
- Wei et al. 2024, SAFE / Long-form factuality — https://arxiv.org/pdf/2403.18802 (self-contained fact revision; 72% agreement / 76% disagreement-win on ~16k facts; 20× cheaper)
- Zha et al. 2023, AlignScore — https://arxiv.org/pdf/2305.16739 (4.7M examples, 7 tasks, 355M params; chunk-level max/avg; 3-way head ablations; SummaC results)
- Gao et al. 2023, RARR — https://arxiv.org/pdf/2210.08726 (retrofit attribution; research-then-revise post-editing)
- Jiang et al. 2020, HoVer — https://arxiv.org/pdf/2011.03088 (2/3/4-hop claims; degradation with hops; anti-shortcut claim design)
- PCC: Fact-Checking with LLMs via Probabilistic Certainty and Consistency — https://arxiv.org/html/2601.02574 (per-claim adaptive verification strategies; ECE on SciFact/HoVer/FeLMWk)
- Linguistic Calibration of Long-Form Generations — https://arxiv.org/html/2404.00474v2/ (claim-level ECE 0.266 RL vs 0.301 SFT; linguistic + numerical confidence)
- DeBERTa-v3-small official specs — https://ai.azure.com/catalog/models/microsoft-deberta-v3-small (44M backbone, MNLI-m/mm 88.3/87.7)
- Multi-dataset binary variant card — https://dataloop.ai/library/model/moritzlaurer_deberta-v3-small-mnli-fever-docnli-ling-2c/ (8 datasets, 1.28M pairs; MNLI 0.927 / FEVER-NLI 0.892 / ANLI 0.684)
- NLI artifacts reviews — https://www.emergentmind.com/topics/natural-language-inference-nli ; https://www.alphaxiv.org/overview/1805.01042v1 (hypothesis-only baselines, give-away words)
- Negation checklist failures — https://zhenyuanlu.com/blog/artifacts-mitigation-nlp/ (99.8% basic-negation failure, ELECTRA-small/SNLI)
- McCoy et al. lexical-overlap heuristic via — https://ar5iv.labs.arxiv.org/html/2209.03392 (high overlap → spurious entailment, incl. annotator-side)
- Litmuz claim-level verification layer — https://litmuz.co/ (atomic claims, traffic-light verdicts, D1–D5 diagnostics, honest negatives)

---
*Cycle 11 complete. Claim: this file contains no unverified factual claims about the pipeline's own measured performance — all performance figures are sourced above or tagged as design estimates. [VC — self-referential, but the tags are in the text.]*
