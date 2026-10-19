# The v2 Brain — Design Specification

*PHASE INFINITY, Research Cycle 19. Learning-only design document — no code, no installs.*
*Date: 2026-10-19. Status: design complete, NOT validated on hardware or real usage.*

**What this is:** the single spec document for JARVIS v2's brain (the LLM layer). Every clause traces to a source study or a v1 autopsy corpse. Every number that hasn't been measured is marked PROPOSED. Every open question is marked UNKNOWN.

**What the brain is NOT:** the brain does not build the UI, the voice plugin, the memory store, or the session store. Those have their own specs. The brain is the *judgment* layer: it reads, reasons, decides, and asks — everything else is code.

---

## 0. The Brain's Job Description — What It Does vs What It Never Does

### The core principle [VC — R2, Conscio, frontier-reasoning §4]

**The brain does judgment. Code does enforcement. Never the reverse.**

This is the single most important sentence in this document. Every v1 brain corpse traces to the brain being asked to do something that should have been code's job — or code failing to do what only code can do:

| Brain DOES (judgment) | Brain NEVER does (enforcement) |
|---|---|
| Decides which tool to call and with what arguments | Decides whether the action is *allowed* — the permission gate is deterministic code that runs *after* the brain, on the actual action object |
| Decides what to ask the user | Decides what risk tier an action is — tiers come from the tool manifest, not the brain's opinion |
| Interprets ambiguous requests | Detects impossibility structurally — slot-checking against tool schemas is code, not introspection |
| Generates candidate plans and repairs | Verifies its own plans — verification is always a separate system (deterministic checker, environment, or fresh-context judge) |
| Drafts what to say | Records what was *spoken* — the Utterance Record is written by the TTS completion signal, not the brain's memory |

**Why this boundary exists** [HC — CLAMBER overconfidence finding, introspection limits]:
- LLMs are bad at judging their own certainty (CLAMBER: chain-of-thought *increases* overconfidence on ambiguity detection).
- The same weights that make an error cannot reliably detect it (deterministic verification study).
- External ground truth (tool schemas, sandbox execution, approval events) beats internal introspection in every measured comparison.

**The brain is powerful but untrustworthy about itself.** Treat it like a brilliant advisor who sometimes lies about being sure. Give it all the judgment, none of the locks.

### The R2 enforcement point [HC — Conscio study, FAILURE-ANALYSIS R2]

Between the brain and the tools sits a deterministic judgment layer (the Conscio pattern):

```
user request → [BRAIN: propose action] → [GATE: permission check, tier check, schema check] → [TOOLS: execute] → [BRAIN: interpret result]
```

The gate is ~200 lines of plain code. It:
1. Checks the action against the skill's manifest capabilities (deny-by-default — S2).
2. Looks up the action's risk tier from the tool definition (never from the brain's claim).
3. Validates arguments against the JSON schema (the proven `react_agent.py` pattern: validate → ONE repair retry → fail honestly).
4. Routes tier-3 actions to the out-of-band approval gate (R3).
5. Tags the tool result as untrusted data before returning it to the brain (R2 instruction hierarchy).

**The brain has no code path to side effects except through the gate.** This is the AND-gate from the fault-tree study: prompt injection (brain-side) requires a *second, independent* code failure to cause harm.

---

## 1. Three-Tier Model Routing

### The architecture [HC — efficiency trio studies, 2060 guide]

```
Tier 0: ALWAYS-ON (CPU)          Tier 1: DAILY DRIVER (GPU)        Tier 2: FRONTIER (cloud)
BitNet 1-bit ~3B                 Qwen2.5-7B Q4_K_M, 4k ctx         Gemini / Groq / OpenRouter
Ryzen 5 3600, ~100 tok/s         ~35–45 tok/s, ~5.2 GB VRAM        Full capability, costs money/latency
0 GB VRAM                       KV cache ~115 MB (q8)             
```

**Why three tiers exist** [HC]: no single model fits all constraints. The always-on tier must be instant and free (voice acknowledgments, quick lookups). The daily driver must fit 6GB VRAM with tool-call accuracy intact. The frontier handles what local models can't — but costs latency, money, and privacy (data leaves the machine).

**Honest working assumptions** [MC — from efficiency studies]:
- BitNet: ~3× CPU speedup, ~70% energy saving vs FP16 CPU inference (paper claims 2.37–6.17× / 55–70%; the honest working number is the conservative one). BitNet-b1.58-2B-4T: 0.4GB, ~40 tok/s on CPU, ~1.3GB RAM via BitRun (MIT, alpha).
- Tier 1: Qwen2.5-7B chosen for its **4 KV heads** (not its 7B size) — 115MB cache @4k vs 295MB for an 8-head 8B. The shootout protocol (§Cycle-9 spec) must confirm before locking.
- Q4_K_M is the floor for the tool brain. q4_0 destroys tool calling (BFCL 63% → 20% on Llama-3.1-8B). Never ship below Q4_K_M. [HC — "Less is More" arXiv 2411.15399]
- **Speculative decoding** as a power-up: BitNet (tier 0) drafts on CPU, tier 1 verifies on GPU — 2–3× faster decode. [MC — unmeasured on the 2060]

### Routing rules — what goes where [MC — proposed, difficulty distribution UNKNOWN]

The router classifies each turn on four axes (from frontier-reasoning §5):

| Axis | Values | Who decides |
|---|---|---|
| **Latency budget** | voice (≤2s) / interactive (≤10s) / batch (minutes) | The channel (voice plugin vs chat UI) |
| **Difficulty** | easy / medium / hard | Tier 0's self-assessment + belief ledger — UNKNOWN, unmeasured |
| **Verifiability** | can the answer be checked? | Tool schemas (deterministic) |
| **Reversibility** | risk tier 0–3 | Tool manifest (deterministic) |

**The routing protocol:**

```
1. Voice channel (latency ≤2s):
   → Tier 0 answers immediately (acknowledgment, quick facts, read-only lookups).
   → If tier 0's uncertainty is high OR the task needs tools beyond its ability:
     → Escalate to tier 1, tell the user "one moment" (honest, not dead air — kills H-B6).

2. Chat channel (latency ≤10s):
   → Tier 1 is the default. It handles everything it can.
   → Escalate to tier 2 (cloud) when:
     - Tier 1 fails twice on the same task (Debugging Decay: 2-attempt rule ≈ measured optimum).
     - The task needs frontier capability (complex reasoning, rare knowledge, long generation).
     - The user explicitly asks ("ask the smart one").

3. Batch/background (no latency budget):
   → Tier 2 for research-quality work; tier 1 for routine summaries.

4. NEVER route by parameter count alone. Route by measured capability per task type.
```

**The difficulty-distribution problem** [UNKNOWN — open problem #2]: we don't know what fraction of Owais's real usage is easy/medium/hard. This blocks optimal tier thresholds. **Resolution:** log every turn's tier + outcome + latency for 30 days, then set thresholds from the measured distribution. Until then, the protocol above is the conservative default (prefer the cheaper tier, escalate on failure).

**Fallback when a tier fails** (see §2): tier failure is *expected* (models crash, GPUs OOM, networks drop). The brain degrades down the ladder, never silently: "My local brain just crashed — restarting it now, one moment" (R12 honest UX).

### The SMITH lesson [HC — 90%]

Training method beats parameter count. SMITH-4B beat a 30B model on agentic tasks. The practical takeaway for v2:
- **Kinetic-4B** (`consciousengines/Kinetic-FC-LoRA`, public LoRA on Qwen3-4B, beats Haiku 4.5 on tool-call accuracy) is the template for a small tool-specialist tier.
- Do NOT fine-tune facts into weights (they go stale silently). Fine-tune *behavior* only — tool-call format, refusal patterns, Hinglish handling. Facts live in retrieval. [HC — continual-learning study]
- The benchmarking weekend must include a small tool-specialist candidate (4B-class) against the 7B generalist. The 4B might win on tool accuracy at half the VRAM.

---

## 2. The Fallback Chain That Actually Falls Back

### The v1 corpse [VC — C-B1]

The backup-brain walk lived *inside the same try block* as the primary request. Timeouts, DNS failures, connection drops — the most common real failures — raised exceptions that skipped the fallback entirely. Two healthy backups sat idle while the user got "all brains failed."

### The spec [VC — FAILURE-ANALYSIS R8, testing/fallback_fixed.py proven]

```python
# Pseudocode — the STRUCTURAL rule, not the implementation:
def respond(request):
    last_error = None
    for provider in chain:                      # chain: [tier1_local, gemini, groq, openrouter]
        try:
            return provider.call(request)        # try block contains ONLY the call
        except TransportError as e:              # timeout, DNS, connection drop, 429, 5xx
            last_error = e
            log(f"{provider} failed ({e.kind}), trying next")
            continue                             # THE FIX: fallback walk is OUTSIDE the try
        except AuthError as e:                    # 401/403 — key is wrong, not the network
            rotate_key(provider)                 # try next key for THIS provider
            continue
    return honest_failure(last_error)            # every provider failed — say so plainly
```

**Structural rules (non-negotiable):**

1. **The fallback walk lives outside the primary try block.** Transport exceptions trigger fallback. This is the C-B1 fix — a code-structure rule, reviewable in one glance. [VC]
2. **Per-provider key lists, never cross-contaminated.** A Groq entry sends Groq keys. The C-B2 bug (sending an OpenRouter key to Groq → 401 → giving up) is prevented by construction: keys are namespaced per provider in the keyring. [VC]
3. **Rotation continues past non-429 errors.** One dead key + one valid key must still succeed. Rotation stops only when the key list is exhausted. [VC]
4. **Retry only 408/429/5xx. Never 400/401/403.** (400 = your fault, retrying is pointless; 401/403 = key problem, rotate don't retry.) [HC — backend study]
5. **One retry budget across layers.** The brain, the provider client, and the tool wrapper share a single budget — retry storms are a stability failure (control-theory study: jittered backoff + single budget). [HC]
6. **Timeouts on every external call.** A hung provider stalls a turn for 12+ minutes (H-B8) → hard per-call timeout (PROPOSED: 60s cloud, 120s local — measure on the 2060), then fallback. [HC]

### The no-keys / all-failed states [VC — C-B5, R12]

- **No providers configured:** the brain says plainly what's missing and offers the setup path. Never the infinite "start Ollama" loop. Exact copy: *"I don't have a brain connected yet, sir. You can [set up local AI — one click] or [add a cloud API key]. Which would you like?"* [PROPOSED copy]
- **All providers failed:** *"All my brains are unreachable right now — the local one and the cloud. Your files and notes are safe; I just can't think at the moment. I'll keep retrying in the background."* Then: background retry with backoff, notify on recovery. [PROPOSED]
- **Local model loading:** *"Warming up my local brain — about [N] seconds."* Progress, not silence. (H-B6: no dead air, ever.) [PROPOSED]

### Test plan [HC — evaluation-science, benchmark-spec Track E]

Simulated failures per provider, 20 trials each: 429, DNS failure, timeout, 500. Measure: recovery rate (must be 100% — any failure that doesn't trigger fallback is a C-B1 regression) and p95 time-to-recovery. **The fallback chain is the single most-tested subsystem** — it's the difference between "Wi-Fi blip" and "JARVIS is dead."

---

## 3. The Reasoning Strategy Selector

### The 8-strategy table as runtime logic [HC — frontier-reasoning §5]

The brain doesn't use one reasoning mode. It selects per turn:

| # | Strategy | When the brain uses it | Cost | Status |
|---|---|---|---|---|
| 1 | **Single-pass ReAct** | Default. Easy/medium tasks, voice latency. | 1× | Default-on |
| 2 | **Best-of-N** | Medium difficulty, no verifier available. N≤3. | N× | On demand |
| 3 | **Tree search (ToT)** | Hard + combinatorial, tight node cap | ~10× | GATED (see below) |
| 4 | **MCTS + environment verifier** | Hard + verifiable (code, plans) | ~10×, 10–20× slower | GATED (see below) |
| 5 | **Belief ledger** | ALWAYS — uncertainty tracking | ~1× | Default-on |
| 6 | **Causal post-mortem** | ALWAYS on failure — abduction→intervention→prediction | ~1× | Default-on |
| 7 | **Neuro-symbolic verify** | ALWAYS on irreversible actions — deterministic checker | 1–3× | Default-on |
| 8 | **Escalate** | All strategies exhausted or risk too high | Variable | Backstop |

**The runtime selection rule:**

```
1. Classify the turn: difficulty × verifiability × reversibility × latency (see §1).
2. Easy OR voice-latency-critical → Strategy 1. Done. (Overthinking is a measured failure mode.)
3. Medium, no verifier → Strategy 2 (N≤3), then Strategy 1's answer if no winner.
4. Hard + verifiable + batch budget → Strategy 4 (environment as judge — the +21–47% measured gain).
5. Hard + verifiable + interactive budget → Strategy 2 with tight cap.
6. Hard, no verifier → Strategy 2 + Strategy 8 (stronger model or human).
7. ALWAYS in parallel: Strategy 5 + Strategy 7 (on irreversible actions) + Strategy 6 (on failure).
8. NEVER Strategy 3/4 with an LLM-only judge below 90% discrimination — worse than useless.
```

### The tree-search gate [HC — Cycle 7 discriminator protocol]

Tree search is **disabled by default**. It enables only when:
- The discriminator protocol (DISC-100) measures ≥90% accuracy with Wilson lower bound ≥0.85 on JARVIS's actual tool set, AND
- The worst safety-relevant stratum (missing-confirmation, unsafe-ordering) independently clears 0.85.

Below that: best-of-N (N≤3) + verifier rerank. The gate is a config flag set by measurement, not by optimism. **No measurement, no search.** [VC]

### The belief ledger (Strategy 5) [HC — always-on, ~1× cost]

A small explicit data structure, not a solver:
- Per-claim: confidence + source + staleness timestamp.
- Per-tool: Beta-Bernoulli (successes, failures) — the empirical P(tool works).
- **Trigger rule:** when uncertainty about a decision-relevant variable exceeds threshold → insert an information-gathering action (verify, re-read, ask) instead of proceeding. [PROPOSED thresholds — must be tuned on real usage]
- **Calibration check:** when the brain marks a claim "uncertain," is it actually wrong more often? (Brier score on flagged claims.) If not calibrated, the ledger is decoration.

### The verifier-first principle [VC — "the verifier is the strategy"]

Search without a good discriminator is expensive noise. The build order is:
1. **Verifiers first:** Pydantic schemas on every tool (the R2 enforcement point), test suites, sandbox dry-runs.
2. **Then** best-of-N with verifier rerank.
3. **Then, only if the discriminator gate passes:** tree search.

**The trivial alternative is always the comparison:** any proposal for search must beat "single-pass ReAct + verifier" on the golden set before it ships. (FAILED-first discipline.)

### Termination guarantees [VC — react_agent.py, proven]

The ReAct loop cannot spin forever — three independent mechanisms:
1. **Max iterations** — hard cap on LLM calls; on breach, honest "I gave up" instead of a fabricated answer.
2. **Token budget** — checked before every call; oldest tool exchanges dropped first; system prompt NEVER dropped; if it still doesn't fit, stop honestly.
3. **Explicit finish** — the model can end deliberately; plain-text reply with no tool calls ends naturally.

Plus **structured-output validation**: tools flagged `expects_json` get schema-checked; ONE repair retry with the validation error as hint; then fail honestly. (This is the neuro-symbolic pattern at its cheapest — LLM proposes, schema disposes.)

---

## 4. The Ask-vs-Act Gate

### The 8-step rule as the brain's pre-action check [HC — learn-underspecification.md]

Before ANY action with consequences, the brain runs this procedure. It's the controller that picks "ask" as a strategy:

```
1. IMPOSSIBILITY CHECK → impossible or policy-blocked? ESCALATE (refuse + reason + adjacent offer).
   Never ask "which impossible thing do you want?"

2. SELF-SERVICE CHECK → can a tool/memory/environment supply the missing fact? Look it up. NEVER ask
   for what you can retrieve yourself. (The most common design failure: U6b.)

3. NOBODY-HAS-IT CHECK → no source has it? Honest abstention. Don't ask.

4. INTERPRETATION ENUMERATION → list the plausible interpretations (small k).
   For each: what action follows, what risk tier?

5. CONVERGENCE TEST → all interpretations → same safe, reversible action?
   → ACT on the most likely, NARRATE the assumption ("Playing your liked songs — say the word to change it").

6. COST-ASYMMETRIC DECISION → VoI(ask) > C_ask? ASK one targeted question, highest-VoI first.
   HARD GATES (override everything):
   - Divergent interpretations × irreversible action → ASK, always.
   - Risk-tier-3 action → NEVER act on assumption. ASK or ESCALATE.

7. ESCALATE when: catastrophic stakes (typed confirmation, never one-tap) · irreversible social/financial
   (show exact payload) · asking can't resolve it (3rd question in a row — stop) · adversarial/policy.

8. ASK BUDGET → max ~2–3 questions per task, batched into one turn. Never re-ask what's been asked.
```

### Structural detection, not introspection [VC — CLAMBER finding]

The brain's self-reported "I'm not sure" is unreliable (CoT increases overconfidence). Detection is structural:
- **Slot-checking:** every tool schema declares required slots. Missing slot + no default + no retrievable value = underspecified. This is code, not judgment — it runs before the brain is even consulted about asking.
- **Consequence-divergence analysis:** enumerate interpretations, classify each by risk tier. Divergent tiers = the master signal. This part IS the brain's judgment — it's what LLMs are good at.

### The rubber-stamping guard [HC]

Every unnecessary question trains Owais to approve blindly, destroying the safety value of real confirmations. The ask budget isn't just politeness — it's a **security control**. Over-asking is a vulnerability.

### Hinglish note [MC]

Code-switched requests may carry ambiguity signals absent in English ("ye"/"woh" deixis density). No data exists. The Hinglish golden set (Cycle 8) must include underspecification items — the ask/act boundary may sit in a different place for Hinglish.

---

## 5. Context Management

### The 4k-physical strategy [HC — inference-frontiers §4]

Physical context is capped at **4k tokens**. Not because of VRAM alone — because of the triple win:
1. **Prefill (quadratic):** 15k² vs 4k² ≈ 14× fewer attention FLOPs → TTFT collapses.
2. **KV cache (linear):** 4k × 28KB ≈ 115MB — VRAM headroom preserved.
3. **Decode (linear):** smaller cache = less memory traffic per token, for the entire response.

The brain *experiences* 15–20k of effective history on 4k physical via compression. Growing context to "use" VRAM headroom is a performance anti-pattern — every extra 1k tokens costs O(n²) prefill forever after.

### The compression stack (three layers, they multiply) [HC — LLMLingua-2 study]

```
Layer 1: Prompt caching (static prefixes — system prompt, tool schemas)     → 50–90% off
Layer 2: LLMLingua-2-small (dynamic history compression, 2–5× safe range)    → 2–5×
Layer 3: KV quantization q8_0 (underneath, halves cache)                     → 2×
```

**Rules:**
- **Never compress tool schemas or the current user query.** Compress history only. [VC]
- Safe compression range: 2–5×. Past 5×, keep query and schemas intact or don't compress. [HC]
- LLMLingua-2-small costs 0.22GB (CPU) — one prefill-side pass per turn, small against the 14× attention saving. [HC]
- Prompt caching first (it's free), then LLMLingua-2 for the dynamic part.

### The Utterance Record [HC — Moshi study]

The brain's conversation history is fed by **what was actually spoken**, not what was generated:
- The brain commits text sentences. TTS reports word-level completion.
- If TTS is interrupted at word 40 of 100, history keeps 40 words. The brain never "remembers" saying unheard words. [VC — v1 M-V16: confabulation from unspoken replies]
- Tool results are appended with untrusted-data framing (R2) — never raw.

### What stays verbatim vs what gets compressed [MC — proposed]

| Always verbatim | Compressible |
|---|---|
| System prompt (cached, not compressed) | Old tool exchanges (summarized) |
| Tool schemas (cached) | Superseded plan steps |
| Current user query | Resolved clarifications |
| Pending approvals + their payloads | Small talk older than the session |
| User-stated constraints ("never delete without asking") | Redundant confirmations |
| The Utterance Record (last N turns) | — |

**User constraints are never compressed away.** A safety-relevant instruction buried in compressed history is a fault-tree cut set waiting to happen. Constraints live in a dedicated verbatim slot.

### History truncation (the v1 corpse) [VC — H-B7, M-S27]

Conversation history grew unboundedly in v1 → context overflow, ballooning cost. The spec:
- Hard cap at 4k physical, enforced by the token-budget guard (react_agent.py pattern — proven).
- Truncation order: oldest tool exchanges first → old assistant messages → never the system prompt, never pending approvals, never user constraints.
- When truncation kicks in, the brain is told: *"[Earlier history was summarized to fit context. The summary is: ...]"* — honest, not silent.

---

## 6. The Failure Table — Every v1 Brain Corpse Mapped

| Corpse | What happened | Spec clause that prevents it | Source |
|---|---|---|---|
| **C-B1** | Fallback walk inside primary try block; transport exceptions skipped all fallbacks | §2: fallback walk outside try block; transport errors trigger fallback | R8, proven fix |
| **C-B2** | Key rotation cross-contaminated providers; stopped at first non-429 | §2: per-provider key namespaces; rotation continues past non-429 | R8 |
| **C-B3** | One bad config string crashed the whole app | Config validation with filenames (R7) — brain never sees invalid config; separate spec, referenced here | R7 |
| **C-B4** | Settings save corrupted everything (non-atomic writes) | Atomic writes + backups (R6) — persistence spec, referenced here | R6 |
| **C-B5** | No keys + no Ollama = infinite useless "start Ollama" loop | §2: honest no-keys UX with setup path offered; never a dead-end loop | R12 |
| **H-B1** | Malformed settings.local.yaml silently ignored | R7: validation errors name the file and key; never silent | R7 |
| **H-B2** | Panel save deleted hand-added keys | R7: never overwrite keys it didn't read; atomic save | R7 |
| **H-B3** | Ollama installer never ran `ollama serve` | Setup spec: verify the server responds, not just the binary exists | Setup spec |
| **H-B4** | Model detection regexed config.yaml only, missed panel choice | Single source of truth for model selection (validated config) | R7 |
| **H-B5** | `cloud_first` without keys silently ran local; wrong blame in errors | §2: no silent tier changes; errors name the actual failed tier | R12 |
| **H-B6** | "Busy" turns produced dead air | §2: every state has narration; "one moment" + progress, never silence | R12, V-doctrine |
| **H-B7** | History grew unboundedly | §5: 4k hard cap, truncation order, honest summary notice | R8 |
| **H-B8** | Hung model stalled turns 12+ minutes | §2: per-call timeouts (60s cloud / 120s local PROPOSED), then fallback | R8 |
| **M-S27** | History past num_ctx → silent truncation, degrading answers | §5: budget guard checks before every call; truncation is explicit and announced | react_agent.py |
| **M-S28** | No per-turn tool budget; looping model burned minutes/quota | §3: max iterations + token budget + one shared retry budget; circuit breaker | react_agent.py, R8 |

**No orphans.** Every brain/config corpse in the autopsy maps to a clause above or to a referenced spec (R6 persistence, R7 config, setup). If a future reader finds a corpse without a clause, the spec is incomplete — file it as a bug against this document.

---

## 7. Open Questions (Ranked)

1. **Difficulty distribution of real usage** [UNKNOWN] — blocks optimal tier thresholds. Resolution: 30 days of tier/outcome/latency logging, then set thresholds from measurement.
2. **Discriminator accuracy on JARVIS's tool set** [UNKNOWN] — gates all tree search. Resolution: DISC-100 protocol (Cycle 7), executed on the 2060.
3. **2060 model shootout** [UNKNOWN] — which quant keeps tool accuracy. Resolution: benchmark spec Track A (Cycle 9).
4. **Belief-ledger thresholds** [UNKNOWN] — what uncertainty level triggers verification. Resolution: tune on real usage; start conservative (verify more).
5. **Voice-loop latency budget per tier** [UNKNOWN] — can tier 1 answer in <2s at 4k prefill? Resolution: measure TTFT on the 2060 (benchmark Track B).
6. **Hinglish ask/act boundary** [UNKNOWN] — may differ from English. Resolution: Hinglish golden set with underspecification items (Cycle 8).
7. **Small tool-specialist vs 7B generalist** [UNKNOWN] — Kinetic-4B-style model might win on tool accuracy at half VRAM. Resolution: include in the shootout.
8. **Optimal ask budget** [UNKNOWN] — is 2–3 questions right for Owais? Resolution: production observation; watch for rubber-stamping signals.

## 8. Confidence Summary

- **[VC]** The judgment/enforcement boundary; the C-B1 structural fix; per-provider keys; termination guarantees; never compress schemas/queries; 4k-physical triple win; Q4_K_M floor; introspection limits.
- **[HC]** Three-tier architecture and routing protocol; the 8-strategy selector; belief ledger; verifier-first build order; ask-vs-act rule; compression stack; Utterance Record.
- **[MC]** Exact tier thresholds; BitNet speedup figures; speculative decoding gains; Kinetic-4B transfer; compression verbatim/compressible split.
- **[SP]** Whether a 4B tool-specialist beats the 7B generalist; exact timeout values (60s/120s).
- **[UK]** The 8 open questions above — all blocked on the 2060 or real usage.

---

*Traceability: every clause cites its source study or autopsy finding. This spec, the session-store spec (R15), the voice-loop spec, the reliability spec, and the threat model together form the v2 design package. The architecture synthesis that binds them awaits Owais's go-ahead.*
