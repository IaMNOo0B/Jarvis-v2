# Tool-Calling Reliability

How to make small models (7B) call tools correctly and reliably. Researched 2026-10-19 from 8 sources, cross-referenced. Directly relevant: JARVIS's brain drives everything through tool calls.

## What the field knows

**1. The 7B floor is real [HC]**
Multiple benchmarks converge: 7B parameters is the practical minimum for viable tool calling. Qwen3.5 BFCL-V4 scores: 9B → 66.1%, 4B → 50.3%, 2B → 43.6% — a cliff below ~7B. Below the floor: low/zero tool invocation rates, confabulated responses instead of tool use, catastrophic multi-step failure. The reason: tool calling needs five things at once (hold context, spot knowledge gaps, pick the tool, generate valid args, integrate results) — small models drop one, and the one they drop is the tool call itself. JARVIS's local 7B (Qwen 2.5 7B) sits right at the floor — usable, but needs every reliability trick below.

**2. It's a trainable skill, not a function of scale [VC]**
A 7B model WITH explicit tool-calling training (Mistral 7B v0.3, Qwen family, ToolACE-8B) beats a much larger general model without it. Qwen is the default local tool-caller for a reason: Qwen3.5-9B hits 66.1% BFCL-V4, and Qwen3-8B beat Mistral Large on the Berkeley leaderboard. JARVIS implication: if we ever swap the local model, pick one with published tool-calling scores, not just a bigger number.

**3. Grammar-constrained decoding is the reliability unlock [VC]**
Don't ask the model for JSON — ENFORCE it at the token level. Mask invalid tokens during generation so malformed output is impossible:
- **Cloud**: OpenAI `response_format` strict mode, Gemini `responseSchema`, Anthropic Structured Outputs (beta) — all compile the schema into a grammar.
- **Local**: vLLM `guided_json` (XGrammar backend, default), llama.cpp GBNF grammars, **Ollama `format` parameter** (XGrammar under the hood — 100% schema compliance).
- Constrained decoding is FASTER than unconstrained (trims the search space), not slower.
- The JSONSchemaBench: Guidance won on speed/coverage; XGrammar is the default everywhere now.
JARVIS runs the local brain through Ollama — **passing our tool-call schema via the `format` parameter would make malformed tool calls structurally impossible.** This is the single highest-leverage change in this file.

**4. Schema design rules [HC]**
From the anti-pattern table (multiple sources agree):
- Put reasoning BEFORE the answer field (model decides before thinking otherwise)
- Flatten: 2-3 nesting levels max (4+ degrades)
- Describe every field (`.describe()` — the model guesses otherwise)
- Make possibly-missing fields Optional/nullable (forced-required → hallucinated values)
- Keep schemas focused: one per task; 50+ fields → split into multiple calls
- Specific, non-overlapping enum options
This matches our earlier finding (named values > bare booleans) — same principle, wider evidence.

**5. Runtime settings [HC]**
- **Short tool lists**: Mistral advises minimum tools per call; fewer tools = better selection accuracy.
- **Low temperature**: below 0.1 for tool calling (NVIDIA says 0.6 for Nemotron specifically — follow the model card).
- **Right parser**: vLLM needs `--enable-auto-tool-choice` + the parser the model card names.
- JARVIS already caps at 3 rounds / 12 calls per turn — the field agrees small models need tight budgets.

**6. Most failures are infrastructure, not intelligence [HC]**
A Oct 2026 study (clawdbytes): **75.7% of model-attributed failures happened AFTER a tool was invoked** — broken server schemas, contradictory API definitions, unbounded context windows (one 7.1GB model ate 51GB RAM from a 262K window, mimicking timeouts). Server-only fixes moved models 6-21 places in rankings with zero prompt changes. Lesson for JARVIS: when a tool call fails, suspect our harness (schema, timeout, context) before blaming the model. And cap the context window hard.

**7. The counterpoint [MC]**
One n8n benchmark found a 1.5B model beating 14B on simple tool-calling (1.00 vs 0.80 accuracy, 14x faster) — but the test set was small and the tasks were simple classification-shaped. The author's own caveat: for complex multi-step tool calling, the bigger model wins. Takeaway: match model size to task shape; don't over-read this.

## What JARVIS should implement

1. **Ollama `format` parameter with our tool-call JSON schema** — grammar-constrained decoding makes malformed tool calls impossible. Single biggest reliability win. [Priority: high]
2. **Apply the schema design rules** to all tool manifests: flat, described fields, Optional for maybe-missing, enums over booleans, focused schemas. [Priority: high]
3. **Keep tool lists short per turn** — only expose tools relevant to the current context. [Priority: medium]
4. **Temperature 0 for tool-calling turns** on the local model. [Priority: medium]
5. **On tool failure, check the harness first** (schema validity, timeout, context size) — add this to the debugging runbook. [Priority: medium]
6. **Hard-cap context window** for the local model (the 51GB-RAM lesson). [Priority: medium]

## Confidence notes
- [VC] = trainable-skill-not-scale, grammar-constrained decoding (convergent benchmarks + mechanism)
- [HC] = 7B floor, schema rules, runtime settings, infrastructure-not-intelligence (well-sourced, some vendor numbers)
- [MC] = 1.5B-beats-14B counterpoint (small test set, author-caveated)
