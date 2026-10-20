# Small-Model Instruction Following

How to make a 7B model (like JARVIS's local Qwen 2.5 7B) follow complex instructions reliably. Researched 2026-10-19 from 6+ sources, cross-referenced.

## What the field knows

**1. 7B is the practical floor for instruction following [HC]**
Well-aligned 7B models in 2026 follow instructions, refuse appropriately, and produce structured output more reliably than a 70B from 2023 (masturbyte.com). On narrow tasks with a clean prompt they land within 5-10pp of frontier models at 1-3% of the cost. The three drivers: better curated/synthetic training data (the "phi" approach), better post-training (RLHF/DPO), better serving stacks. For classification, routing, extraction, and short structured tasks, a 7B is >95% of frontier accuracy.

**2. Concrete beats abstract — always [VC]**
Two independent sources agree: a dev.to practitioner found prose rules ("a negated condition is a unary NOT") were followed inconsistently by qwen2.5-coder:7b, but a couple of tiny concrete JSON examples fixed the same problems. The hackernoon playbook says the same: one good example beats three paragraphs of explanation. For JARVIS: every instruction in the system prompt that matters should carry a tiny example, not just a rule.

**3. Named values beat bare booleans [HC]**
The dev.to practitioner found the 7B "quietly omitted" bare boolean flags (`"tapped": true`) often enough to break things. Replacing them with named strings (`"press": "held"`) fixed it — "a string with a name is much harder to forget than a missing true." Field order also mattered. JARVIS application: tool schemas should prefer enums/named strings over bare booleans, and required fields should come early in the schema.

**4. Prompt length is a budget, not free [VC]**
Every prompt addition risks making the model forget something else — the practitioner watched negations regress after adding a drawing section. The only defence found: a **regression net** — a script that regenerates sample outputs with the real model and checks them against expectations, run on every prompt change. JARVIS should build this: a golden set of ~20 prompts covering tool calls, Hinglish, approvals, and run it before every prompt edit.

**5. The micro-task skeleton [HC]**
The hackernoon production playbook gives a rigid scaffold 7B models "love":
```
ROLE: <one line>
TASK: <single concrete output>
CONSTRAINTS: <length, tone, must-include>
FORMAT: <exact output shape>
INPUT: <the data>
```
Plus: inject facts the model needs ("FACTS (use only these):") instead of making it guess — this narrows the search space and cuts hallucination. JARVIS's system prompt should be restructured toward this skeleton rather than prose paragraphs.

**6. Small-model prompt quirks [MC]**
From the tchncs discussion: use a direct authoritative tone ("do this"), strip wordy phrases (small models are literal — "delve" in the prompt produces "delving" in the output), adjectives bleed into completions, use markdown sections and delimiters, constrain output with JSON schema, temperature 0 for determinism.

**7. The training pipeline matters more than the prompt [HC]**
Distillation (teacher→student) transfers capability; Phi-style curated synthetic data beats raw scale; quantization (GGUF Q4) keeps 95%+ quality at 75% size reduction. For JARVIS: the local 7B is a fallback, not the star — but if we ever fine-tune, distill from the cloud brains' good traces, don't hand-write data.

## What JARVIS should implement

1. **Restructure the system prompt** to the micro-task skeleton (ROLE/TASK/CONSTRAINTS/FORMAT/INPUT) with tiny concrete examples attached to every load-bearing instruction. [Priority: high]
2. **Build the regression net**: ~20 golden prompts → run against the real local model → check outputs. Gate every prompt change on it. [Priority: high]
3. **Prefer enums over booleans** in tool schemas; put required fields first. [Priority: medium]
4. **Keep prompts short**: every section must earn its tokens; measure, don't accumulate. [Priority: medium]
5. **Temperature 0** for tool-calling turns (deterministic). [Priority: low — verify first]

## Confidence notes
- [VC] = concrete-examples-beat-rules, prompt-length budget, regression net (two independent practitioner sources + playbook agree)
- [HC] = 7B floor, named-values, micro-task skeleton, training pipeline (well-supported, some inference on our side)
- [MC] = adjective-bleed quirks (forum wisdom, plausible, unmeasured by us)
