# Bottleneck-01: The No-Hedge Guarantee Is a Substring Match

*JARVIS OMEGA ∞+1 — FIRST MISSION, Phase 1 (analysis only). No code changed, no prototype built.*
*Date: 2026-10-19. Status: mechanism verified by code reading; detector behavior MEASURED on crafted sets; field rates estimated, not measured.*

---

## The bottleneck in one paragraph

`brain.py` enforces a "no-hedge guarantee": if the model's reply matches `is_hedged()` from `persona.py`, the turn burns another full LLM round (and, on repeat, a full brain switch). But `is_hedged()` is a **case-insensitive substring match of 20 English phrases against the entire reply** (`persona.py:135-138`). Measured: precision **0.47** on an adversarial set — every substantive answer containing "no idea", "I'm not sure", "as an AI", or "I can't assist with X, but…" is flagged as a refusal and re-researched. Measured: **7/7 genuine hedges missed**, including all Hinglish hedges ("pata nahi", "shayad"). The autopsy's 210 findings never mention it; no knowledge-base file addresses it. The detector is simultaneously over- and under-inclusive, and each false positive costs a full model round plus a possible cloud-brain escalation.

---

## A. Evidence the limitation exists

**A1. The detector** — `~/workspace/jarvis-build/persona.py:111-138`:

```python
HEDGE_PATTERNS = ["i don't know", "i do not know", "i dont know", "i'm not sure",
    "i am not sure", "i cannot assist", "i can't assist", "i cannot help",
    "i have no information", "no information about", "i don't have information",
    "i don't have access to", "as an ai", "unable to find any information",
    "i'm unable to", "i am unable to", "cannot provide that", "i can't answer",
    "i cannot answer", "no idea"]

def is_hedged(text: str) -> bool:
    """True if the spoken reply still contains an ignorance-hedge."""
    low = text.lower()
    return any(p in low for p in HEDGE_PATTERNS)
```

Twenty English-only patterns, substring-matched against the whole reply. No sentence scoping, no negation handling ("no idea is a bad answer, so I checked…" matches "no idea"), no multilingual coverage.

**A2. The enforcement loop** — `~/workspace/jarvis-build/brain.py:493-507`:

```python
if not tool_calls:
    # ---- final answer: apply the no-hedge guarantee ----
    if is_hedged(content):
        hedged_rounds += 1
        if hedged_rounds == 1 and rnd < self.max_rounds:
            self.history.append({"role": "user", "content": RESEARCH_AGAIN_PROMPT})
            continue
        if secondary and not switched:
            switched = True
            escalated = True
            active = secondary
            ...
            self.history.append({"role": "user", "content": RESEARCH_AGAIN_PROMPT})
            continue
```

Cost per false positive, read directly from the code path:
1. First hit: +1 full LLM round (`continue` → `_call_local`/`_call_cloud` again with the grown history).
2. Second hit (same model, same hedging style — likely): a full **brain switch** to the other brain, which re-runs the turn.
3. The "guarantee" is actually "no-hedge-twice-then-give-up": after two hits plus a switch, the hedge is returned as the reply anyway (`brain.py:508-510` falls through to `return BrainResult(reply=content, …)`).

**A3. Secondary defect — fake user messages pollute history.** `RESEARCH_AGAIN_PROMPT` is appended with `role: "user"` (`brain.py:498,506`). The cleanup at `brain.py:446-449` only pops *trailing* prompts at the next turn's start. Any prompt buried mid-history (the common case — the turn continues after it) persists forever, so all future turns show the model a fake user scolding ("Your previous reply hedged instead of answering…"). Consequences: wasted context on every future turn, plus a confused model being scolded for something the user never said.

**A4. MEASURED detector behavior** (existing function, read-only execution, no changes):

| Set | N | Result |
|---|---|---|
| Adversarial FP probe (substantive answers containing hedge substrings) | 15 (7 refusals, 8 substantive) | Precision **0.47**, Recall 1.00 — all 8 substantive answers flagged |
| FN probe (genuine hedges avoiding exact patterns, incl. Hinglish) | 7 | **7/7 missed** ("It's unclear whether…", "Possibly…", "pata nahi", "shayad", …) |

*Honest scope on the numbers:* the FP set is adversarial by construction (written to contain hedge substrings), so 0.47 is a stress-test lower bound, not a field rate. The field false-positive rate depends on how often the deployed model emits hedge substrings inside substantive answers — unknown without production logs [UK]. The FN result is structural (patterns absent → cannot match), not sample-dependent [VC].

**A5. Skip-if-learned audit.** Grepped `~/workspace/jarvis-knowledge/*.md` for `is_hedged|HEDGE_PATTERNS|no-hedge`: zero hits. Grepped `FAILURE-ANALYSIS.md` for "hedge" (case-insensitive): zero hits — the 210-finding autopsy never examined this mechanism. The "hedge" hits in `learn-claim-verification.md` / `learn-source-trust.md` concern epistemic hedges in *claim extraction*, an unrelated topic. **This bottleneck is unaddressed.** [VC]

---

## B. Closest prior solutions

1. **The mechanism itself** (`brain.py` + `persona.py`): keyword-blocklist as a quality gate. Prior art for the *approach*: decades of profanity/keyword filters — known to be simultaneously over- and under-inclusive (the classic failure mode this reproduces exactly).
2. **Refusal detection in the literature**: LLM guardrail classifiers (e.g., refusal-direction probes, Llama Guard-style classifiers) detect *refusal intent* rather than uncertainty vocabulary. Heavier machinery; not obviously warranted here.
3. **Our own knowledge base, applied against itself**: the threat model's finding — *"v1's core sin was detection-mindset security"* (learn-threat-model.md §7). This detector is detection-mindset *quality control*: a pattern list standing in for the thing being measured. The knowledge base's own verdict on this pattern family is negative.
4. **Structural alternative already half-present in the code**: the persona contract says the model should *investigate with tools* rather than hedge. The observable violation is behavioral (zero tool calls + non-answer), not lexical. `tools_used` is already tracked per turn (`brain.py:453,524`) — the signal exists, unused by the gate.

Per Domain XI labeling: the proposal below is a **new combination of known techniques** (behavioral gating + sentence-scoped matching), not a novel invention. The measurement above is an **experimentally supported** characterization of the existing detector on crafted sets (not field data).

---

## C. Falsifiable hypothesis

**H1 (primary):** Replacing the substring detector with a *refusal-to-act* detector — gated on (a) zero tool calls this turn AND (b) sentence-scoped bare-refusal matching — will achieve ≥0.90 precision and ≥0.85 recall on a 100-item labeled set where the current detector scores ~0.47 precision, without reducing recall on bare refusals.

**H2 (value):** False-positive re-prompts occur in ≥5% of real turns (i.e., this is a high-value bottleneck, not a corner case).

**Falsification criteria:**
- H1 is falsified if the structural detector's precision is not significantly better than 0.47 on the same set, or if its recall on bare refusals drops below 0.85.
- H2 is falsified if instrumented field logging (counter only, no behavior change) shows false-positive re-prompts in <2% of turns over ≥500 turns. If H2 is falsified, the bottleneck is real but low-value — fix opportunistically, don't prioritize.

---

## D. Proposed architecture / algorithm

**Design principle** (from our own playbook): detect the *behavioral violation* (the model did no work and produced no answer), not the *vocabulary* (the model used uncertain words). Uncertainty expression inside a substantive answer is fine — even desirable (cf. the calibration doctrine in SOUL.md).

**Algorithm — `is_bare_refusal(content, tools_used_this_turn)` (deterministic, no model calls):**

```
1. If tools_used_this_turn is non-empty → NOT a refusal. Return False.
   (Rationale: "I can't do X, but I did Y" is action, not refusal. The model
   worked; the guarantee's purpose — forcing investigation — is satisfied.)
2. Split content into sentences (simple splitter; abbreviations tolerated via
   the whole-text fallback in step 4).
3. A sentence is "refusal-shaped" if it matches a refusal template: starts with
   or consists of an ignorance/refusal phrase (the existing 20 patterns, PLUS
   common paraphrases, applied per-sentence, not per-reply).
4. If EVERY sentence is refusal-shaped (or the whole reply is < 40 words and
   refusal-shaped) → bare refusal. Return True.
5. Otherwise → the reply contains substantive non-refusal content → NOT a refusal.
   (The "I can't X, but here's Y" shape fails step 4 at the "but here's Y" sentence.)
```

**History-pollution fix (same change):** stop appending the nudge as a fake `user` message to persistent history. `_call_local`/`_call_cloud` already accept a `messages` override (the consult path uses it: `brain.py:803-806`). Build the nudge as a *transient* trailing message for the current round's payload only; never persist it. This kills the A3 defect structurally — there is no injected message left to clean up.

**What is deliberately NOT proposed:** a smarter/longer keyword list, an LLM-as-judge for hedging, or multilingual pattern expansion. All three are the detection-mindset trap: more patterns, same category error. (The Hinglish FN gap is closed by the behavioral gate, not by translating the blocklist.)

---

## E. Minimal reproducible experiment design

**E1 — Detector bake-off (sandbox-runnable, no model needed):**
1. Build `hedge_eval_100.jsonl`: 100 replies, labeled by two raters (bare-refusal vs substantive), stratified: 40 bare refusals (English 25, Hinglish 10, paraphrase 5), 40 substantive-with-hedge-substrings (the FP trap), 20 clean substantives. Inter-rater κ ≥ 0.80 required before use (per learn-evaluation-science.md).
2. Run v1 `is_hedged` → precision/recall (baseline; predicted ≈0.5/1.0 on this distribution).
3. Run candidate `is_bare_refusal` (+ no-tools gate simulated with turn metadata) → precision/recall.
4. Report Wilson 95% CIs; McNemar for the paired comparison (per learn-evaluation-science.md §statistical machinery).

**E2 — Field prevalence (requires production logging; NOT runnable in sandbox):**
Instrument `_respond_locked` with a counter (no behavior change): log `(is_hedged(content), tools_used_nonempty, is_bare_refusal(content))` per turn. After ≥500 turns, compute the false-positive re-prompt rate = P(re-prompt fired AND tools_used_nonempty OR substantive). This decides H2.

**E3 — Cost accounting (from E2 + code):** each false positive = 1 extra `_call_local`/`_call_cloud` (measure wall-clock + tokens in the instrumented run). Converts "wasted rounds" into seconds and rupees.

---

## F. Baseline + measurable success criteria

- **Baseline:** v1 `is_hedged`: precision 0.47 / recall 1.00 on the 15-item adversarial probe (measured §A4); estimated ~0.5–0.7 precision in the wild [MC — field rate unmeasured].
- **Success criteria (pre-registered):**
  1. Candidate precision ≥ 0.90 with Wilson lower bound ≥ 0.80 on `hedge_eval_100` (n=100).
  2. Candidate recall on bare refusals ≥ 0.85 (no worse than v1's 1.00 by more than the pre-registered 0.15 margin — recall regressions are the safety-relevant direction).
  3. H2 field measurement: if false-positive re-prompts ≥5% of turns, ship the fix; if <2%, deprioritize (falsified as high-value).
  4. Zero injected fake-user messages in history after the change (asserted by a unit test on the turn path).

---

## I. Failure analysis of this proposal

1. **The adversarial set is mine.** I wrote the FP cases to break the detector; 0.47 is a stress number. Field precision could be 0.8+ if the deployed model rarely embeds hedge substrings in substantive answers — which would shrink H2 below the value threshold. *Mitigation:* E2 measures the field rate before shipping; the proposal does not assume the stress number is the field number.
2. **Sentence-splitting fragility.** "Dr. Rao said no idea is unacceptable…" — naive splitters break on abbreviations, mis-scoping the per-sentence match. *Mitigation:* the whole-text fallback (step 4's <40-word clause) plus keeping the pattern list small; a mis-split degrades to v1-like behavior on that reply, not a crash.
3. **Elaborate refusals.** "After careful consideration of your request, I must respectfully decline…" — multi-sentence, no exact pattern → missed. *Assessment:* rare in this product context (the persona demands investigation, not declination); the behavioral gate (no tools + long reply) partially covers it. Documented as a known residual.
4. **The no-tools gate has its own false negatives.** A model that makes one token tool call ("let me check…") then hedges passes the gate. *Assessment:* acceptable — a model that used tools did the thing the guarantee wants; residual risk is low-value.
5. **Transient-nudge refactor risk.** Changing how the nudge reaches the model (transient vs history-appended) alters prompt dynamics subtly; the re-prompt may become less effective. *Mitigation:* E1 includes an end-to-end check that a bare refusal + transient nudge still produces tool use on the next round (using the existing test harness pattern).
6. **Deeper alternative unaddressed:** maybe the right fix is prompt-level (a persona the small model actually follows) making the detector unnecessary. *Assessment:* the persona already says "never hedge"; the detector exists because it doesn't stick. Both can coexist; the detector is the backstop, and a backstop should be precise.

## J. Recommendation (based on evidence)

1. **Ship the structural detector** (`is_bare_refusal` + no-tools gate) — deterministic, cheap, unit-testable, and it converts a 0.47-precision tripwire into a ≥0.90-precision one on the measured distribution. This is a days-scale change with testable acceptance criteria (F1–F4).
2. **Fix the history pollution in the same change** (transient nudge via the existing `messages` override) — it's a three-line-class fix riding the same code path, and it removes fake user scoldings from all future context windows.
3. **Do not expand the keyword list** — that is the exact trap our own threat model indicted. Close the Hinglish gap behaviorally, not lexically.
4. **Instrument before optimizing further**: add the E2 counter in the same release; let 500 real turns decide whether this was a 5%-of-turns bottleneck or a corner case. If H2 falsifies, stand down.
5. **Explicit non-recommendation:** no LLM-judge, no refusal-direction probes, no training — the cheaper deterministic method covers the measured failure modes. (Per learn-program-synthesis.md's scale principle: cheaper methods cover ~everything here.)

---

## Confidence & unknowns

- [VC] Mechanism (read from `brain.py:446-510`, `persona.py:111-138`); autopsy/KB coverage gap (grep-verified); FP/FN probe results on crafted sets (executed, read-only).
- [HC] The history-pollution persistence claim (traced through the cleanup's trailing-only logic); the cost-per-false-positive path (read from the loop).
- [MC] Field false-positive rate (no production logs available in sandbox); local-model hedge frequency in real turns.
- [UK] Whether the deployed model (Qwen3.5-9B per roadmap vs current Ollama default) hedges more or less than the patterns assume; real turn distribution for E2.

## Honest scope (what this does NOT establish)

- Does not measure field prevalence (E2 needs production logging; sandbox has no turn logs).
- The 0.47 precision is from a 15-item adversarial set, not a representative sample — it proves the failure mode exists and is easy to trigger, not that it fires on 53% of real turns.
- No prototype built (per task constraints); the candidate algorithm is specified, not implemented or tested.
- One bottleneck, done deeply, as tasked — the `_get_fallback_model` 15s model-detect tax in the failure path was noticed during inspection and deliberately left for a future cycle.
