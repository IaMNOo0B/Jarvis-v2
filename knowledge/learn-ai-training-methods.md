# How AI Models Are Trained — And How JARVIS Learns Without Training

*PHD study. Date: 2026-10-19. Status: researched, cross-referenced, saved.*
*Question: the top AI training methods exist to make models helpful, honest, and harmless. JARVIS can't retrain its brain (the LLM). So how do we steal the methods' PRINCIPLES and apply them without a training run?*

---

## 1. RLHF — Learning From Human Thumbs-Up and Thumbs-Down

**How it works (plain English).** RLHF teaches a model what humans like in three stages:

1. **Show it good examples.** Human experts write ideal answers to questions. The model studies them, like a student reading model essays. This teaches the FORMAT of helpfulness.
2. **Let humans rank answers.** Show humans two answers to the same question, ask "which is better?" Do this thousands of times. Train a second, smaller model (the "reward model") to predict which answer a human would pick. Now you have an automatic judge that works at scale.
3. **Practice against the judge.** The main model generates answers, the reward model scores them, and the model adjusts to get higher scores. One safety net: a penalty stops it from drifting too far from what it learned in stage 1 — otherwise it "games" the judge with flowery nonsense that scores high but says nothing (called reward hacking).

**What behavior it produces.** [VC] A model that follows instructions reliably, refuses harmful requests, adjusts tone to the user, and admits uncertainty — the difference between ChatGPT and a raw autocomplete engine.

**The catch.** [HC] It's expensive and fragile: stage 3 holds up to FOUR giant models in memory at once, needs thousands of human labelers, and is prone to reward hacking.

### How JARVIS uses RLHF's principles (no training run)

The insight: RLHF's real product is a LOOP — generate → get judged → improve. JARVIS can run that loop at runtime:

- **The reward model becomes Owais's corrections.** Every time Owais corrects JARVIS ("no, that's wrong, do X"), save it as a preference pair: (bad answer → good answer). The memory system already stores facts — extend it to store *corrections* with higher weight. Before answering, the brain checks: "have I been corrected on anything like this before?"
- **The KL penalty becomes the constitution.** RLHF needs a penalty to stop drift. JARVIS has JARVIS-RULES.txt — the same job. Every answer gets checked against the rules before it goes out.
- **Implementation status:** PARTIAL. `memory.py` stores facts and corrections; `gate.py` enforces rules. Missing: explicit preference-pair storage and pre-answer correction lookup.

---

## 2. Constitutional AI — A Written Rulebook Instead of Human Labels

**How it works (plain English).** Anthropic (the Claude company) asked: what if instead of humans rating every answer, we write down the RULES and let the model judge itself? The "constitution" is a list of principles — drawn from the Universal Declaration of Human Rights, plus rules like "pick the answer least likely to be false" and "don't manipulate people."

The training loop:
1. The model answers a tricky question.
2. The model is asked: "Look at your own answer. Does it break any rule in the constitution?" (self-critique)
3. The model rewrites its answer to follow the rules better. (self-revision)
4. The improved answers become training data.

Over thousands of rounds, the model internalizes the reasoning — it doesn't need to do the explicit critique step anymore. [HC]

**What behavior it produces.** [VC] A model whose values are explicit and inspectable — you can read the constitution and know WHY it behaves the way it does, instead of the values being hidden inside a black-box reward model.

### How JARVIS uses Constitutional AI's principles (no training run)

This is the EASIEST method to steal, because JARVIS already has a constitution: **JARVIS-RULES.txt** (42 rules, P0 > P1 > P2 > P3).

- **The self-critique step becomes a second LLM call.** After the brain drafts an answer, send it BACK to the model with: "Here is your draft. Check it against these rules: [constitution]. Flag violations, then revise." This is exactly what Anthropic does — except they bake it into training, and we do it per-answer at runtime. Costs one extra model call per answer; worth it for important answers.
- **The audit trail is free.** Anthropic's big selling point is "you can read the constitution." JARVIS's rules are already a text file Owais can edit. When JARVIS does something unexpected, check which rule failed.
- **Implementation status:** PARTIAL. `rules.py` parses the constitution; `gate.py` enforces it deterministically. Missing: the LLM self-critique-and-revise pass. **This is the #1 recommended build.**

---

## 3. DPO — The Shortcut (Skip the Judge, Just Show Pairs)

**How it works (plain English).** Researchers noticed RLHF was overcomplicated. DPO asks: why build a separate judge model at all? Just show the model PAIRS of answers — "this one is good, that one is bad" — and train it to prefer the good one. It's a classification problem, not reinforcement learning. No reward model, no PPO, no four-models-in-memory. [VC]

Meta used DPO instead of RLHF for Llama 3 and found it more effective and cheaper. [HC]

**The catch.** [HC] DPO lives or dies on data quality. Garbage preference pairs = garbage behavior. And it's still training — you need the pairs and a fine-tuning run.

### How JARVIS uses DPO's principles (no training run)

The insight: **preference pairs are the simplest, most powerful teaching signal.** You don't need math — you need examples of "do this, not that."

- **Golden examples ARE DPO data, used at inference time.** `TEACHING.md` already has golden conversations (right way vs wrong way). The trick: put the most relevant pairs directly in the system prompt, not just in a file the model might not read. When Owais corrects JARVIS, that correction should become a new golden pair automatically.
- **Implementation status:** PARTIAL. `TEACHING.md` exists with 5 golden conversations. Missing: automatic pair extraction from corrections, and injecting the most relevant pairs into the live system prompt (not just the knowledge base).

---

## 4. Instruction Tuning — Teaching "Follow Instructions" As a Skill

**How it works (plain English).** Google's FLAN (2021) had a simple bet: take a model, train it on HUNDREDS of different tasks all phrased as instructions ("translate this", "summarize that", "classify this"). The model stops learning the individual tasks and starts learning the META-skill: read an instruction, figure out what's being asked, do it. Then it can follow instructions it has NEVER seen before. [VC]

The shocking result: a small 1.3B model with good instruction training was preferred by users over a 175B model without it. **The data matters more than the size.** [HC]

**What behavior it produces.** [VC] Zero-shot generalization — the model handles new task types gracefully instead of needing examples every time.

### How JARVIS uses Instruction Tuning's principles (no training run)

The insight: **the system prompt IS instruction tuning, done at inference time.** Every word in the system prompt is an "instruction" the model follows.

- **Structure beats prose.** Research (our own `learn-small-model-instruction.md`) confirms: a rigid ROLE / TASK / CONSTRAINTS / FORMAT / INPUT skeleton works better than paragraphs of advice. Concrete examples beat abstract rules every time.
- **JARVIS's `_MODEL_PROTOCOL` should be rewritten** in this skeleton format, with 3-5 concrete examples of good behavior embedded directly. This is the FLAN finding applied to prompts.
- **Implementation status:** NOT STARTED. The current system prompt is prose-heavy. **This is the #2 recommended build** — restructure the system prompt per the FLAN skeleton.

---

## 5. RLAIF — Let AI Do the Grading

**How it works (plain English).** RLHF needs humans. RLAIF asks: what if an AI does the grading instead? Train a small "evaluator" model on a little bit of human data, then let it grade millions of answers at near-zero cost. Same RLHF pipeline, but the judge is artificial. [VC]

**The tradeoff.** [HC] It's cheaper, faster, and more consistent than humans — but the evaluator's biases get amplified. If the grader is wrong, the student learns the wrong thing at scale. Most labs use a hybrid: humans for the tricky stuff, AI for the bulk.

### How JARVIS uses RLAIF's principles (no training run)

The insight: **a second opinion from the same brain, used as a gate.**

- **The judge is already half-built.** `verifier.py` runs 8 deterministic checks (F1–F8) on tool calls — that's AI feedback without an LLM. The missing piece: an LLM judge for ANSWER QUALITY. After the brain drafts a response, a cheap/fast model (or the same model with a different prompt) scores it: "Is this helpful? Accurate? Does it actually answer the question?" If it fails, revise or regenerate.
- **The hybrid rule:** deterministic checks (verifier, gate, DCL) run on EVERYTHING — they're free and exact. LLM judging runs on high-stakes answers only (tier 2/3 actions, anything going to the user that matters). This mirrors the industry hybrid: cheap AI grading for bulk, careful review for what matters.
- **Implementation status:** PARTIAL. `verifier.py` covers tool-call checking. Missing: the LLM answer-quality judge.

---

## Summary: The 5 Methods, The 5 Steals

| Method | Core idea | JARVIS steal (no training) | Status |
|---|---|---|---|
| RLHF | Human ranks answers → reward model → optimize | Save Owais's corrections as preference pairs; check before answering | Partial |
| Constitutional AI | Written rules + self-critique + self-revision | Self-critique pass: draft → check against JARVIS-RULES.txt → revise | **#1 to build** |
| DPO | Good/bad pairs, no judge model | Golden examples in the live prompt; auto-extract pairs from corrections | Partial |
| Instruction Tuning | Many instruction→response examples → meta-skill | Restructure system prompt to ROLE/TASK/CONSTRAINTS/FORMAT/INPUT + examples | **#2 to build** |
| RLAIF | AI grades instead of humans | LLM judge scores draft answers; deterministic checks on everything | Partial |

## Top 3 Actionable Techniques for JARVIS (ranked)

1. **Constitutional self-critique pass** (from Constitutional AI). After the brain drafts an answer, one more LLM call: "Check this draft against JARVIS-RULES.txt. List violations. Revise." This is the single highest-leverage addition — it's Anthropic's core method, it maps perfectly onto the existing constitution, and it needs no new infrastructure. Estimated: one new module (`jarvis/self_critique.py`), ~100 lines, called from `Brain.respond()` for non-trivial answers.

2. **FLAN-style system prompt restructure** (from Instruction Tuning). Rewrite `_MODEL_PROTOCOL` as ROLE / TASK / CONSTRAINTS / FORMAT / INPUT with embedded concrete examples. Zero new code — just a better prompt. The research says this is the highest-ROI change for small models, and JARVIS's brain is often a 7B local model.

3. **Correction-to-pair pipeline** (from RLHF + DPO). When Owais corrects JARVIS, automatically save (bad answer → good answer) as a golden pair, and inject the most relevant pairs into the system prompt at runtime. This creates a learning loop that compounds: every correction makes future answers better. Needs: a `corrections` table in memory, a retrieval step in `Brain.respond()`.

## Confidence & Sources

- [VC] on the 3-stage RLHF pipeline, Constitutional AI's generate→critique→revise loop, DPO's pair-based simplification, FLAN's instruction-tuning finding, and RLAIF's AI-grader substitution. Each cross-referenced across 2+ independent sources.
- [HC] on specific claims: PPO's 4-model memory cost, Meta using DPO for Llama 3, the 1.3B-vs-175B instruction-tuning result, RLAIF bias amplification.
- [MC] on the exact implementation effort estimates (new-module line counts are informed guesses).
- Unknown: whether per-answer self-critique latency is acceptable to Owais in practice — needs his feedback after trying it.

## References (all from live search 2026-10-19)

- RLHF pipeline: https://temperature2.com/p/2026-09-25-learning-what-is-rlhf/ · https://growai.in/rlhf-reinforcement-learning-human-feedback-explained-2026/ · https://www.arraysoflight.com/rlhf_ppo.html
- Constitutional AI: https://www.byteplus.com/en/what-is/constitutional-ai · https://metavert.io/constitutional-ai · https://www.envisioning.com/vocab/constitutional-ai
- DPO: https://huggingface.co/learn/smol-course/unit2/2 · https://www.manchesterdigital.com/post/ve3/rlhf-ppo-and-dpo-how-ai-models-learn-from-human-preferences · https://arxiv.org/html/2409.03650v1
- Instruction Tuning / FLAN: https://www.theaicompendium.com/6-llms/instruction-tuning-alignment.html · https://aimersociety.com/introducing-flan-more-generalizable-language-models-with-instruction-fine-tuning/ · https://ar5iv.labs.arxiv.org/html/2305.11383
- RLAIF: https://www.turing.com/resources/rlaif-in-llms · https://klu.ai/glossary/rlaif · https://www.turingpost.com/p/stateofrl2025
