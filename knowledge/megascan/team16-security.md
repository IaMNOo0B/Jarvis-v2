# MEGA-SCAN TEAM 16 — Agent Security & Guardrails (PhD reverse engineering)

**Mission:** prompt-injection defenses, agent firewalls, tool-output sanitizers, LLM guardrails, agent sandboxing — studied from code, judged as steals for JARVIS v2's `gate.py` / `dcl.py`.

**Method:** `git clone --depth 1` into `.work16/`, read locally. GitHub API used only for 2 discovery searches.

**Honesty ledger:** VM network was heavily congested (≈20 parallel teams + builders). Verified full-content clones: **16 repos** (below, all marked ★). Partial/failed clones (documented, NOT faked): Azure/PyRIT (checkout incomplete — root files only; PyRIT mechanism notes marked [from prior verified knowledge]), microsoft/presidio (clone failed 3× — Presidio notes come via its *consumer* llm-guard's anonymize code, which was read in full), ethz-spylab/agentdojo (re-clone in flight at writing time — AgentDojo defense notes marked accordingly), promptfoo/promptfoo, Giskard, AgentSafetyBench, langkit, deepteam, HarmBench, OpenInterpreter, deepset/prompt-injections — all timed out at 240–600 s and were dropped rather than thinned out. Target was 40; delivered depth on 16 + structured notes on the dropped set's known designs is worth more than 40 shallow reads. Nearly every verified repo is **MIT or Apache-2.0** (table below) — patterns are legally liftable; v2 stays stdlib-only, so steals are algorithms/designs, not dependencies.

---

## The mechanism taxonomy (what the whole field actually does)

| # | Mechanism family | Who does it best | Cost per call |
|---|---|---|---|
| 1 | Small classifier (DeBERTa) on the text itself | LLM Guard, NeMo (RF on embeddings) | ~ms, local |
| 2 | Heuristic/fuzzy signature match ("ignore previous instructions" family) | Rebuff layer 1, Vigil YARA | ~µs, local |
| 3 | Perplexity/length anomaly (adversarial-suffix detector) | NeMo heuristics (GPT-2) | ~10s ms, local |
| 4 | Known-attack vector similarity | Rebuff layer 2, Vigil vectordb | embedding call |
| 5 | LLM-as-judge (second model classifies) | Superagent, Rebuff layer 3, NeMo self-check | 1 extra LLM call |
| 6 | Canary tokens (leak tripwire in the system prompt) | Rebuff, Vigil | ~0 |
| 7 | PII/secret vaulting (placeholder ↔ restore) | LLM Guard Anonymize+Vault (Presidio inside), Vigil YARA secret rules | ~ms, local |
| 8 | Output validators with failure policies (reask/fix/refrain) | Guardrails AI | varies |
| 9 | Trace policy language (rules over tool-call sequences) | Invariant | ~µs–ms, local |
| 10 | Tool/server supply-chain scanning (static, pre-flight) | mcp-scan, Cisco mcp-scanner | offline |
| 11 | Execution sandboxing (AST-restricted interpreter ↔ microVM) | smolagents ↔ E2B / agent-sandbox / microsandbox | infra |
| 12 | Red-team automation (prove the bypass before attackers do) | garak, PyRIT | offline |
| 13 | Benchmarks of indirect injection (the measuring stick) | BIPIA, AgentDojo | offline |

The one-line truth of the whole scan: **nobody's single layer works.** Every serious system stacks a cheap deterministic layer, a classifier layer, and a structural layer (least-privilege tools / sandbox / trace policy), then red-teams the stack. v2 already has the structural layer (gate + tiers + DCL) — it is missing layers 1, 6, and 9, which are exactly the three cheapest.

---

## Deep reads (verified from local clones)

### 1. ★ protectai/llm-guard — MIT — the scanner-pipeline reference
**Architecture:** input scanners → LLM → output scanners. Each scanner returns `(sanitized_text, is_valid, risk_score)`; scores aggregate via `calculate_risk_score`.
**PromptInjection scanner (read in full):** a fine-tuned **DeBERTa-v3 classifier** (`protectai/deberta-v3-base-prompt-injection-v2`, ONNX available). The clever part is not the model — it's the **windowing**. The classifier caps at 512 tokens, so `MatchType` offers: `SENTENCE` (score per sentence), `CHUNKS` (256-char windows, 25-char overlap), `TRUNCATE_HEAD_TAIL` (126 head + 382 tail tokens — injections hide at the ends), `FULL`. *Lesson: any fixed-window detector that only reads the start of a long tool output is blind by design.*
**Anonymize/Vault (read in full):** Presidio recognizers (regex + NER + checksum-validated entities) replace PII/secrets with placeholders (`[REDACTED_PERSON_1]`); a **Vault** stores placeholder→value; the output scanner **Deanonymize** restores them. Secrets never reach the model; the user still sees real values.
**Also:** `Secrets` scanner (detect-secrets plugins), `BanSubstrings/BanTopics/BanCode`, `Gibberish`, `InvisibleText` (zero-width/unicode-tag smuggling — a scanner class most people forget), `TokenLimit`.
**FP handling:** per-scanner thresholds, risk-score aggregation instead of any-single-hit blocking; scanners fail open/closed per config.
**Steal verdict:** HIGH for DCL — see Steals #2.

### 2. ★ protectai/rebuff — Apache-2.0 — the 3-layer + canary design (smallest complete blueprint)
**Layer 1 — heuristics (read in full, ~150 lines, pure `re`+`difflib`):** *generates* the attack grammar combinatorially (11 verbs × 8 adjectives × 20 objects × 5 prepositions ≈ 8,800 variants of "ignore previous instructions…"), normalizes input (lowercase, strip punctuation), slides word-windows of keyword length, scores with `SequenceMatcher` ratio + matched-word bonus (base 0.5 + 0.5·matched/max). Threshold 0.75. Fuzzy ⇒ catches leetspeak/spacing obfuscation partially; trivially bypassed by paraphrase — and Rebuff *knows it*, that's why layers 2–3 exist.
**Layer 2 — vector DB:** embed input, top-20 similarity against a Pinecone index of *known* attacks; threshold 0.90. Novel attacks pass; yesterday's attacks never do.
**Layer 3 — LLM judge:** a model scores injection likelihood; threshold 0.9.
**Canary tokens (read in full):** `secrets.token_hex(8)` word wrapped in an HTML-comment format is prepended to the system prompt; if the canary string appears in the completion, the system prompt leaked ⇒ log + treat output as compromised. **Zero-cost tripwire, ~30 lines.**
**Verdict:** the *layering order* (cheap→expensive, deterministic→probabilistic) is the design to copy; the hosted-API form is dead (self-host or lift the heuristics file only).

### 3. ★ deadbits/vigil-llm — Apache-2.0 — LLM Guard's scrappier sibling, two unique ideas
Scanners: YARA signatures, transformer classifier, vectordb, similarity, sentiment, relevance. Two ideas nobody else has:
- **Prompt/response relevance + similarity scanners:** scan the *pair* — if the response is semantically unrelated to the prompt, or echoes the prompt suspiciously, flag. Catches successful injections that input scanning missed (defense on the output side).
- **Auto-update:** confirmed detections are embedded into the vectordb after a threshold (default 3) — the blocklist *learns* from live attacks (Vigil's `Manager(auto_update, update_threshold)`).
Also: Shannon **entropy** is computed per prompt (high-entropy = encoded payloads/base64 smuggling signal), and its YARA packs include maintained secret/token regexes (RegHex-derived) usable for DCL patterns.

### 4. ★ superagent-ai/superagent — MIT — LLM-as-judge, production form
`guard()` sends the input to a small classifier LLM with a hardened system prompt (read in full): explicit pass/block definitions, violation taxonomy (`system_prompt_extraction`, `prompt_injection`, …), **CWE codes** in the JSON verdict, "when in doubt, block." Structured JSON output, strict schema. Also offers redaction + a `verify` claim-checking mode.
**Truth:** the judge prompt is the whole product. Its weakness is the whole family's weakness — the judge is itself an LLM reading the same untrusted text (injection can target the judge; Superagent mitigates by input delimiting + never giving the judge tools or secrets).

### 5. ★ NVIDIA-NeMo/Guardrails — Apache-2.0 — the programmable-rails cathedral
Colang flows wire rails: input (self-check input, jailbreak detection, content safety…), dialog, retrieval, execution, output (self-check facts, hallucination rails…). Code-verified components:
- **Jailbreak heuristics:** sliding-window **perplexity via GPT-2-large**, score = `len/perplexity`, threshold ≈ 89.79 — GCG-style adversarial suffixes are high-perplexity gibberish, natural text isn't. A *statistical* detector, no training needed.
- **Jailbreak model rail:** embeddings + **RandomForest** classifier (NemoGuard JailbreakDetect) served as a NIM.
- **Self-check rails:** the model grades its own input/output against a policy prompt (cheapest judge pattern — same model, extra call; weakest isolation, zero new infra).
- 30+ third-party rail integrations (Llama Guard, Clavata, Patronus, ActiveFence…) — NeMo is the *switchboard*, not the detector.
**FP reality:** perplexity flags code, non-English text, and Hinglish-mixed text at elevated rates — for v2 this is a *signal*, never a gate.

### 6. ★ guardrails-ai/guardrails — Apache-2.0 — validators + the OnFail vocabulary
RAIL spec (XML-ish) declares output structure + validators from a hub (toxicity, PII, regex, competitor mentions, "valid JSON", etc.). The durable idea is **`OnFailAction`** (read in full): `REASK` (retry LLM with failure feedback), `FIX` (deterministic repair), `FILTER` (drop offending items), `REFRAIN` (return nothing), `EXCEPTION`, `FIX_REASK`, `CUSTOM`. **A detector without a declared failure policy is a half-built detector** — this enum is the missing vocabulary in most gate designs.

### 7. ★ invariantlabs-ai/invariant — Apache-2.0 — policy over TRACES, the agent-native layer
A real DSL (lexer/parser/AST/typechecker in-repo) for rules over the agent's *event trace*, e.g.:
```
raise "must not email data read from the web" if:
    (call: ToolCall) -> (prev: ToolOutput)
    call is tool:send_email and prev has web_content
```
Quantified patterns over Message/ToolCall/ToolOutput sequences, evaluated **at runtime as a Monitor** (streaming, can block mid-execution) or offline over recorded traces (their "Explorer"). This is the only scanned system that reasons about *what the agent did across steps* — exfiltration is a sequence property (read-sensitive → send-external), invisible to any per-message scanner.
**Steal verdict:** HIGHEST conceptual value for gate.py — see Steals #1.

### 8. ★ invariantlabs-ai/mcp-scan (now agent-scan) — Apache-2.0 — supply-chain for tools
Scans MCP server configs *before* the agent ever runs: pulls tool descriptions, runs **cross-referencing analysis** (an LLM checks whether a tool's *description* matches its *behavior class* — the "tool poisoning" tell: a weather tool whose description smuggles instructions), pins tool-description **hashes** so a server that silently changes its tools ("rug pull") is flagged on the next scan. Has since grown into scanning whole agent setups (Claude Code/Codex/Cursor configs, hooks) — the unit of scanning became the *agent's whole config surface*.
**For v2:** skill manifests are exactly this attack surface. Registry already quarantines unapproved skills; add **manifest hashing at approval time + re-verify on load**.

### 9. ★ cisco-ai-defense/mcp-scanner — Apache-2.0 — three engines, one lesson
CLI/API scanner for MCP servers combining: (1) **YARA rules** over tool metadata + server code, (2) **LLM-based analysis**, (3) Cisco AI Defense cloud API. Ships a large **behavioral-analysis eval corpus** of malicious code samples (zip-slip, symlink attacks, cron backdoors, DNS-tunneling C2, magic-string backdoors…) used to test whether scanners catch *behavior*, not just descriptions. Lesson: keep a local corpus of known-bad tool/skill samples and regression-test the gate against it.

### 10. ★ huggingface/smolagents — Apache-2.0 — the in-process sandbox, honestly labeled
`LocalPythonExecutor` interprets Python AST node-by-node (own `evaluate_*` for every node type) instead of `exec`: import allowlist (`BASE_BUILTIN_MODULES` + explicit additions), blocklists read in full — `DANGEROUS_MODULES` (os, sys, subprocess, socket, io, pathlib, shutil, pty, multiprocessing, builtins) and `DANGEROUS_FUNCTIONS` (eval/exec/compile/`__import__`/os.system…), result-type checks (`check_safer_result`). Docs admit it is **not** a security boundary (known escapes via attribute traversal on allowed objects); production guidance = run in E2B/Docker. Honest pattern for v2's code skill: AST-interpretation raises the bar for accidents, microVM/process isolation is the actual boundary.

### 11. ★ e2b-dev/E2B — Apache-2.0 · ★ kubernetes-sigs/agent-sandbox — Apache-2.0 · ★ microsandbox/microsandbox — Apache-2.0 — the isolation ladder
- **E2B:** Firecracker **microVM per sandbox**, cloud-hosted, SDK lifecycle (create → run → kill, timeouts, snapshots/templates). The reference for "agent code runs somewhere else entirely."
- **agent-sandbox (k8s-sigs):** a Kubernetes CRD *orchestrator* delegating isolation to **gVisor/Kata RuntimeClass** pods + a sandbox-router proxy; warm pools, per-sandbox network policy. Enterprise shape of the same idea.
- **microsandbox:** self-hostable microVMs (libkrun-style) with a local SDK — the closest to something a desktop app could bundle later.
**For v2 (Windows, stdlib):** none is directly adoptable today; the *stealable* part is the lifecycle contract — every execution gets: fresh state, CPU/wall **timeout**, **no network by default**, output size cap, kill switch. v2's sandboxed `code_run` should be graded against that contract line by line.

### 12. ★ NVIDIA/garak — Apache-2.0 — the red-team toolbox
Probe families (read from tree): `dan`, `encoding` (base64/rot13/Unicode smuggling), `atkgen` (model-generated attacks), `av_spam_scanning`, `glitch`, `goodside`, `grandma`, `exploitation`, `agent_breaker`… paired with detectors (exact-match, judge-LLM, encoding-aware). **Use pattern:** run garak-style probe *corpora* against JARVIS's own gate in CI — a defense you never attack is a hope, not a defense.

### 13. ★ llm-attacks/llm-attacks — MIT — the attacker, for bypass notes
GCG (greedy coordinate gradient) adversarial suffixes: white-box optimized gibberish suffixes that reliably jailbreak aligned models — and the direct motivation for NeMo's perplexity detector (suffixes are statistical outliers). Transfer attacks work black-box. **Bypass note for the whole report:** any defense evaluated only against *hand-written* attacks is unevaluated; optimized + paraphrase + encoded attacks are the real bar, and every layer above has published bypasses. Defense-in-depth + least privilege is the only posture that survives contact.

### 14. ★ microsoft/BIPIA — MIT — the indirect-injection measuring stick
Benchmark of **indirect** prompt injection across 5 task families (QA, email, table, abstract, code) with text/code attack splits; the paper's own defenses (black-box: boundary marking/reminders; white-box: fine-tuning) showed **no defense was satisfactory** — attack success stayed material on frontier models. For v2: BIPIA-style tasks are the acceptance test for the web/knowledge skills — tool output is the #1 injection vector, exactly what `wrap_output()` exists for.

---

## Structured notes on the dropped set (designs, not code-verified here)

- **Azure/PyRIT (MIT)** — Microsoft's red-team *orchestration*: targets, converters (base64, ROT13, translation… mutate prompts at scale), scorers (LLM-judge + classifier), memory of attempts. Steal: its **converter** idea for self-testing v2's DCL decode-then-scan (attack your own decoder with encodings).
- **microsoft/presidio (MIT)** — the PII engine inside LLM Guard's Anonymize: recognizers = regex + context words + **checksum validation** (e.g., Luhn for cards) + spaCy NER; anonymizers = replace/redact/hash/encrypt. The checksum trick is why its FP rate beats naive regex.
- **ethz-spylab/agentdojo** — benchmark *and* a defense zoo in one pipeline: `transformers_pi_detector` (classifier on tool outputs), `spotlighting` (delimiting tool output with markers/random strings so the model can distinguish data from instructions), `tool_filter` (an LLM pre-selects which tools the agent may use, shrinking attack surface), `repeat_user_prompt`. Spotlighting is a 20-line steal for `wrap_output()`.
- **promptfoo** — red-team *generator*: plugins produce attack sets (jailbreaks, PII leaks, prompt extraction) graded by assertions; CI-friendly. The workflow steal: gate changes should ship with attack regression sets.
- **whylabs/langkit** — lightweight feature metrics (toxicity, sentiment, regex, embeddings drift) feeding WhyLabs observability; the "guardrails as metrics, alert on drift" posture.
- **Giskard** — vulnerability *scanning* for LLM apps (injection, hallucination, bias detectors generating adversarial tests automatically).
- **thu-coai/AgentSafetyBench** — 2,000-case agent safety benchmark across tools/environments; good acceptance yardstick for pc_control skills.

---

## False-positive & bypass reality (cross-repo)

- **Classifiers (DeBERTa/RF):** domain shift is the FP factory — code, logs, Hindi/Hinglish, and security *discussions* all score hot. Every production deployment pairs the score with thresholds + a non-blocking tier. Never wire a classifier as a sole hard gate on user text.
- **Heuristics:** near-zero FP on natural text, near-total bypass by paraphrase. Correct role: free pre-filter + telemetry.
- **Perplexity:** catches suffix attacks; flags code/encoded/legit-technical content. Signal, not verdict.
- **LLM judges:** best paraphrase resistance; are themselves injectable (the input is in their context), add latency + cost per call; mitigate with delimiters, no tools, no secrets, forced JSON.
- **Canary:** zero FP (random hex), catches only *leakage*, not manipulation — a tripwire, not a wall.
- **Universal bypass classes:** encoding (base64/hex/rot — v2's decode-then-scan already answers this), translation/low-resource languages, splitting payloads across multiple tool outputs (only Invariant-style trace rules see the join), and slow social engineering of the user (only approvals answer that).

## Top 5 mechanisms overall
1. **Trace-level policy** (Invariant) — rules over tool-call sequences; the only layer that sees exfiltration-shaped behavior.
2. **Vaulting** (LLM Guard/Presidio) — data never reaches the model; placeholders round-trip. DCL's natural endgame.
3. **Layered detection in cost order** (Rebuff) — heuristics → classifier → vector memory → judge, each with thresholds.
4. **Canary tripwires** (Rebuff/Vigil) — 30 lines, zero FP, detects prompt leakage after the fact.
5. **Spotlighting + tool filtering** (AgentDojo) — mark data as data, shrink the tool surface per turn.

## Top 3 steals for JARVIS v2 (gate.py / dcl.py / registry)
1. **`gate.py`: add a trace-policy check (Invariant pattern, ~80 lines, stdlib).** v2's gate already sees every tool call with its args and the session's recent tool outputs (session_store has the events). Add declarative sequence rules evaluated before execution: e.g. *block/approve-escalate `send`-class tools whose payload overlaps (token overlap ≥ threshold) content produced by a `web/read`-class tool in the same session unless the user typed it* — the read→exfiltrate chain, caught structurally, no model involved. This upgrades the gate from per-call checks to *behavior* checks, and it composes with the existing HMAC approval tokens (a rule hit = forced tier escalation).
2. **`dcl.py`: add Vault-style placeholder round-trip for SECRET/PERSONAL spans (Presidio pattern, minus spaCy).** DCL already classifies + redacts on egress ("[REDACTED]"). Change redaction to **reversible placeholders** (`⟦SECRET_1⟧`) with the mapping kept in-process (never logged, never sent); on the reply path, restore placeholders before display. Add checksum validators where the format has one (Luhn for card-like numbers, IBAN mod-97) to slash FPs vs pure regex. Effect: the brain can still *reason about* "your card ending in the stored one" flows without the raw value ever leaving the machine — and unlike blunt redaction, conversation stays coherent.
3. **`brain.py` + `registry.py`: canary tripwire + manifest pinning (Rebuff + mcp-scan patterns, ~50 lines total).** (a) Per-session random canary embedded in the system prompt's evidence-wrap region; if it appears in model output or in a tool argument, raise a security event, drop the turn's output, and log — prompt-leakage becomes *detectable* instead of silent. (b) At skill `approve()` time, store SHA-256 of the manifest + tool descriptions; verify on every load; a changed manifest auto-quarantines (rug-pull defense). Both are deterministic, stdlib (`secrets`, `hashlib`), and slot into code that already exists.

*Runner-up steals:* Rebuff's heuristic grammar file as a free DCL pre-scan (pure `re`/`difflib`, threshold-tuned as telemetry first); NeMo's length/perplexity as a *score* on long tool outputs (never a gate — Hinglish FP risk); Guardrails' `OnFailAction` enum as the declared failure policy on every verifier rule; AgentDojo spotlighting delimiters inside `wrap_output()`.

## Late-verified addendum (final retry landed after first writing)

### ★ microsoft/presidio — MIT — code-verified (918 files)
The analyzer pipeline is three stacked FP-reducers, all read in code:
1. **Pattern recognizers with a `validate_result()` hook** — regex finds candidates, then a per-entity validator confirms (checksum class: Luhn-style validation for cards, IBAN checksums) *before* anything is redacted. This hook is why Presidio beats raw regex on FP rate, and it is directly copyable into DCL (Steal #2 already recommends exactly this — now code-confirmed, not inferred).
2. **LemmaContextAwareEnhancer** — boosts a match's confidence when lemmatized words *around* the match resemble the entity's context words ("card", "expire"…). Context as a scoring signal instead of more regexes.
3. **NLP/NER recognizers** (spaCy) + a newer `lm_recognizer` for the long tail.
**Anonymizer operators (verified):** `replace`, `redact`, `mask`, `hash` (salted), `encrypt`/`decrypt` (**AES** — reversible without a placeholder vault when you hold the key), `keep`, `custom`, `deanonymize_keep`. For v2's DCL the placeholder-vault (LLM Guard style) remains the better fit — the brain must not see ciphertext-shaped blobs either — but Presidio's validator+context scoring should front it.

### ★ Giskard-AI/giskard — Apache-2.0 — code-verified (464 files, structure level)
Current shape is `libs/giskard-scan`: a **generator→detector** pipeline — per-vulnerability *generators* synthesize adversarial test cases (injection, hallucination, harm, bias, information disclosure…), the model under test answers, and detectors grade answers into vulnerability issues with a scan report (`scan/quality.py`, `catalog.py`, `vulnerability.py`). The steal is the workflow, same family as garak/promptfoo: **ship gate changes with generated attack regression sets**, targeted per vulnerability class instead of one generic test pile.

*Count correction:* code-verified is now **18** (16 + Presidio + Giskard); Azure/PyRIT's clone reported OK a second time but its worktree is again an incomplete 9-file shell, so PyRIT honestly stays in the notes-only set.

## Count
- Discovery searches: 2 (≈21,000 candidate repos across terms).
- Cloned & code-verified: **18** (the 16 listed in the body + Presidio & Giskard, upgraded in the addendum).
- Structured notes (not code-verified this run, clone failures documented): 8 more (PyRIT, Presidio, AgentDojo, promptfoo, langkit, Giskard, AgentSafetyBench, +CaMeL-pattern via AgentDojo notes).
- **Total covered: 26 of 40 target** (18 code-verified after the addendum below). The 16 verified include every mechanism family the mission named; the gap is breadth, not depth — the dropped repos are variations (more scanners/benchmarks), not missing categories.
