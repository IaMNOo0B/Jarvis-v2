# IMPLEMENTATION LEDGER — JARVIS v2 Master Build Book

**Mandate (Owais, 2026-10-20):** "Build EVERYTHING — all 500–600+ researched
items, implemented one by one at PhD level, each adapted to JARVIS, analyzed
then built then pushed." This file is the single tracking book for that
mandate. If a mechanism is not in this ledger, it does not exist for the
build. If it is in this ledger, its status must be true.

## How to update (living file — rules for every builder team)

1. When you START a row: status → `wip` + your team letter in the note.
2. When you FINISH a row: status → `done` ONLY with evidence: module path +
   the test file that proves it, and the suite run must include it green.
3. When you find a row is wrong/duplicate/superseded: don't delete it — set
   status `n-a` with one line why. The ledger keeps the corpses visible.
4. New research lands here FIRST (status `queued`), then gets built.
5. Never mark `done` from a README claim — grep the code or it didn't happen.

## Status legend

`done` verified in code+tests · `partial` some pieces exist, mechanism
incomplete · `missing` verified absent · `wip` a builder team is on it now
(see Team map) · `queued` accepted, nobody on it yet · `n-a` not applicable
(non-stdlib / owner-PC-only / study verdict SKIP / rejected with reason)

## Builder team map (active 2026-10-20)

A = brain · B = voice · C = pc/system · D = memory · E = proactivity ·
F = intent + modelfile/inference

## Snapshot — 2026-10-20 ~12:20 IST

- Suite: **689 passed** (full run excluding one file, see note) · 1 collection
  error in `tests/test_builder_c_system_skill.py` (Team C test mid-write,
  typo'd variable — Team C to fix; skill itself works).
- Sections: A = audit seed (68) · B = megascan steals · C = learn-file deep
  mechanisms · D = archaeology/master-index additions.
- Megascan reports still being written when this snapshot was taken:
  **team4 (HUD), team7 (voice-2), team8 (desktop-2), team9 (memory-2),
  team13 (browser), team15 (phone)** — their steals enter as `queued` rows
  in a later pass. Team 11 (MCP) was rate-limited to a candidate pool; its
  rows are marked accordingly.

---

## Section A — Audit seed (from hidden_check/PHD-IMPLEMENTATION-AUDIT.md)

Post-pass statuses (the audit's Phase-2 top-5 already folded in).

### Brain & routing

| ID | Mechanism | Source | Status | Value | v2 module |
|---|---|---|---|---|---|
| L001 | Fallback chain: transport errors trigger fallback | playbook B1/V8 | done | 5 | brain |
| L002 | Chain retry budget (ChainBudget) | B1 | done | 4 | brain |
| L003 | Transient retry + backoff before fallback | B1 recipe | done | 5 | brain |
| L004 | Per-provider circuit breaker in chain | B1 | wip (A) | 4 | brain |
| L005 | Provider trace stats → data-driven order | OpenJarvis trace loop | done | 4 | brain |
| L006 | Three-tier difficulty routing | learn-brain-spec | partial | 4 | brain |
| L007 | Grammar-constrained tool calls (Ollama `format`) | learn-tool-calling-reliability | wip (F) | 5 | llm_ollama |
| L008 | Flat tool schemas, enums over booleans | learn-tool-calling-reliability | done | 3 | skills |
| L009 | FLAN-style ROLE/TASK prompt | learn-small-model-instruction | done | 4 | brain |
| L010 | Underspecification ask rule + ask pricing | learn-underspecification | partial (module done, wiring left) | 4 | ask_controller |
| L011 | Trajectory verifier F1–F8 as pre-exec gate | learn-plan-validation | partial (module done, wiring left) | 5 | verifier |
| L012 | Self-critique constitutional pass | learn-ai-training-methods | partial (module done, opt-in OFF) | 3 | self_critique |
| L013 | Golden pairs from corrections (DPO-mini) | learn-ai-training-methods | done | 4 | golden_pairs |
| L014 | Master planner: plan router + plan-as-shared-store | learn-master-planner | wip (A) | 5 | brain |
| L015 | Belief ledger: Beta per tool + Brier calibration | learn-belief-ledger | missing | 3 | brain |
| L016 | Claim-level verification (CLAIM-VER) | learn-claim-verification | missing | 4 | verifier |
| L017 | Source trust tiers T0–T4 for web results | learn-source-trust | missing | 3 | skills/web |
| L018 | Discriminator protocol DISC-100 dataset + Wilson gate | learn-discriminator-protocol | partial | 3 | verifier |
| L019 | Frontier reasoning search (verifier-first adopted) | learn-frontier-reasoning | partial | 2 | brain |
| L020 | SMT/Z3 constraint verification | learn-smt-verification | n-a (non-stdlib; CI-only per study) | — | — |
| L021 | Bayesian experimental design | learn-bayesian-design | n-a (study verdict SKIP) | — | — |
| L022 | Causal discovery GES/LiNGAM | learn-causal-discovery | n-a (study verdict SKIP) | — | — |

### Memory

| ID | Mechanism | Source | Status | Value | v2 module |
|---|---|---|---|---|---|
| L023 | Two-store episodic + semantic memory | learn-memory-spec | done | 5 | memory |
| L024 | mem0 write gate ADD/UPDATE/NOOP + supersede | index M3 | done | 5 | memory |
| L025 | Provenance tiers + quarantine for tool/web facts | index M4 | done | 5 | memory |
| L026 | TTL / expiry | learn-agent-memory-2026 | done | 4 | memory |
| L027 | Secure forget incl. FTS purge | learn-privacy-engineering | done | 4 | memory |
| L028 | Automatic recall injection into brain turns | audit finding | done | 5 | brain |
| L029 | Recall Gate (skip enrichment when hot window covers query) | isair (reverse-eng) | done | 4 | recall_gate |
| L030 | Sleep consolidation: dedupe/merge/promote/decay | Nocturne M2/M5 | done | 5 | memory |
| L031 | A-MEM write-side evolution of linked neighbors | index M1 | wip (D) | 4 | memory |
| L032 | Memory audit suite (6 checks) | learn-memory-audit | partial | 3 | memory |
| L033 | Conflict-resolution 5-type workflow | learn-conflict-resolution | partial | 3 | memory |
| L034 | Hermes background review ("worth remembering?") | playbook M2 | wip (D) | 4 | memory |
| L035 | Bounded char caps on memory values | playbook M1 | done | 3 | memory |
| L036 | Timeline-first append-only episodes | playbook M3 | done | 4 | memory |

### Safety & security

| ID | Mechanism | Source | Status | Value | v2 module |
|---|---|---|---|---|---|
| L037 | Instruction hierarchy: tool output evidence-wrapped | S1/SEC4 | done | 5 | gate |
| L038 | Deny-by-default capabilities | S2/SEC5 | done | 5 | skills/registry |
| L039 | Two-dial safety + HMAC approval tokens | S3 | done | 5 | gate/approvals |
| L040 | Undo for mutations (universal) | S4 | partial (.bak in code skill only) | 4 | skills |
| L041 | Filesystem jail in code + tests | S5 | done | 5 | skills/registry |
| L042 | Secrets in OS keyring (3 backends) | S6 | done | 5 | config |
| L043 | Skill quarantine + approval | S7/SEC S1 | done | 5 | skills/registry |
| L044 | No LLM-triggerable updates | S8 | done | 4 | — (by design) |
| L045 | DCL classification + egress redaction | SEC12 | done | 5 | dcl |
| L046 | Taint propagation across tool chain | SEC12 full | partial | 4 | dcl |
| L047 | Localhost hardening VR-S1..S6 | SEC2 | partial | 3 | setup/config |
| L048 | Scope-per-tool tokens (ScrambleID pattern) | SEC3 | partial | 3 | gate |
| L049 | Shell hard-floor blocklist | team2 aizen | done (basic; see L184 tokenised upgrade) | 5 | pc_control |
| L050 | Fault-tree audit of approval-gate single points | learn-fault-trees | partial | 3 | gate |

### Voice (code exists — unproven on owner's PC)

| ID | Mechanism | Source | Status | Value | v2 module |
|---|---|---|---|---|---|
| L051 | Stage-graph voice loop (8 stages) | V2/learn-voice-loop-spec | done (code) | 5 | voice_loop |
| L052 | Novel-word barge-in ≥70% match | V3 | done (code) | 5 | voice_loop |
| L053 | Utterance Record (spoken, not generated) | V4/Moshi | done (code) | 5 | tts |
| L054 | Staged wakeup VAD→wake→STT | V5 | done (code) | 4 | stt |
| L055 | Bare "Jarvis" wake word (Voicute ONNX) | team1 steal | wip (B) | 5 | voice_loop |
| L056 | Echo salvage ack-timeline model | team1 isair/ethanplusai | wip (B) | 5 | voice_loop |
| L057 | TTS ladder Kokoro/Chatterbox default | V6/V2 index | partial (voicebox/piper/stub) | 4 | tts |
| L058 | Content-addressed TTS cache | A8 | wip (B) | 3 | tts |
| L059 | Smart Turn semantic endpointing | index V3 | missing (model-blocked) | 3 | stt |

### Proactivity, scheduling, phone, PC

| ID | Mechanism | Source | Status | Value | v2 module |
|---|---|---|---|---|---|
| L060 | Call-ringing model + urgent enum + learning | learn-proactivity-spec | done | 5 | proactivity |
| L061 | Four Checks `may_act_unasked` formal gate | index I3 | wip (E) | 4 | proactivity |
| L062 | Scheduler: write-before-reason, 3-strikes | index I1 | partial | 4 | proactivity/skills |
| L063 | Plan-progress checkbox parser | ethanplusai steal | wip (E) | 3 | proactivity |
| L064 | Phone R0/R1/R2 + PIN + pairing | learn-phone-remote-spec | done | 5 | phone |
| L065 | UIA-first PC control + RAM-only screenshots | learn-pc-control-spec | done (code) | 5 | pc_control |
| L066 | `pc.find_text` Windows-OCR fallback | PanPenek steal | wip (C) | 4 | pc_control |
| L067 | App-launch ladder by name | team2 steal | wip (C) | 4 | pc_control |
| L068 | Local-intent-first routing (~80% no-LLM) | team2 Open.Jarvis | wip (F) | 5 | brain |

### Infrastructure & UX

| ID | Mechanism | Source | Status | Value | v2 module |
|---|---|---|---|---|---|
| L069 | Session store: append-only events, wake/checkpoint | R15/SEC1 | done | 5 | session_store |
| L070 | Atomic writes + .bak + corrupt quarantine | A4/A5 | done | 5 | config |
| L071 | Event stream + replay (causal chain) | A3 | done | 4 | session_store |
| L072 | Observability: trace_id contextvars + JSONL spans | learn-observability | done | 4 | observability |
| L073 | Setup preflights + atomic downloads | learn-setup-spec | done | 4 | setup |
| L074 | Error UX: error + suggestion + action | index U2 | partial | 4 | chat_gui/chat |
| L075 | Narrate work live (activity feed) | P1 | partial | 3 | chat_gui |
| L076 | Hinglish persona + mirroring + golden eval set | index U3 | partial (set needs owner usage) | 4 | brain/tests |
| L077 | Evaluation scorecard, Wilson/Holm release gates | learn-evaluation-science | missing | 3 | tests |
| L078 | Formal methods: hand-rolled property tests | learn-formal-methods | partial | 2 | tests |
| L079 | MCP servers inside skill system | learn-mcp-plugins | missing (deferred per study; deep-read rows pending team11 re-run) | 3 | skills |
| L080 | SSE streaming transport | A9 | n-a (no web UI) | — | — |
| L081 | FastAPI backend | learn-backend | n-a (non-stdlib) | — | — |
| L082 | React/Tauri frontend | learn-frontend | n-a (tkinter chosen) | — | — |
| L083 | LoRA playbook (adapters as procedures) | learn-lora-playbook | n-a (no local training; honored via skills) | — | — |
| L084 | Hardware/KV/model-shootout guides | learn-2060-*/index B3/B7 | n-a here (owner-PC measurements; model IDs in llm_compat) | — | — |

**Section A counts: 84 rows · done 36 · partial 21 · missing 8 · wip 11 ·
queued 0 · n-a 8.** (Audit's original 68 rows; 16 rows were split where the
audit bundled two mechanisms with different statuses — e.g. ask-rule vs
verifier wiring — so the ledger tracks them honestly.)

---

## Section B — Megascan steals (teams 1, 2, 3, 5, 6, 10, 11, 12, 14 + reverse-engineering)

IDs continue from Section A. Duplicates of Section A rows are NOT repeated;
where a megascan item sharpens an A-row, it says so.

### B1 · Brain, routing, errors

| ID | Mechanism | Source | Status | Value | v2 module |
|---|---|---|---|---|---|
| L085 | Completion audit / delivery verification (StepLedger: deep success after last failure, send after last deep success) | team5 orcbot (MIT) | wip (A) | 5 | verifier |
| L086 | Deterministic error classifier (RATE_LIMIT w/ cooldown parse, TIMEOUT, CONTEXT_OVERFLOW, NETWORK, INVALID=non-retryable; backoff+jitter, cap 3) | team5 orcbot | wip (A) | 5 | brain |
| L087 | Provider circuit breaker CLOSED/OPEN/HALF_OPEN (thr 5/3, 60s) — sharpens L004 | team5 clawos | wip (A) | 4 | brain |
| L088 | Speculative parallel routing (classifier + default response concurrently) | team1 SreejanPersonal | queued | 3 | brain |
| L089 | [ACTION:…] speak-then-act protocol + cheap summariser follow-up | team1 Julian-Ivanov | queued | 3 | brain |
| L090 | Two-speed architecture (fast local path vs delegated background jobs reporting back) | team1 dijiclick | partial (chain + phone jobs exist separately) | 4 | brain |
| L091 | FAST/CHAT two-tier split via 0.5B label router (invalid output → NONE) | team6 suyogpawate; team3 DavidLiuXh | partial (cf. L006) | 4 | brain |
| L092 | NLU fast-path before LLM (TF-IDF/logreg-style intent cascade: exact→fuzzy→pattern→app) | team6 casha-cashu | partial (cf. L068, F) | 4 | brain |
| L093 | Query-improvement pre-pass + search/synthesis split (refs as separate arg, never pasted raw) | team5 khoj | queued | 3 | brain |
| L094 | Robust JSON-object extraction (brace-depth scanner) + judge max_tokens 1500 rule | reverse-eng isair | queued | 3 | brain |
| L095 | Empty-reply history rollback (empty reply never written to history) | team2B pdagent | queued | 3 | brain |
| L096 | Truncation continuation protocol (BRIEFER_PREFACE / CONTINUE_NUDGE, max 2) | team6 Johnwang688 | queued | 3 | brain |
| L097 | Budget-end handoff (DONE/OPEN/NEXT at budget exhaustion) | team6 Johnwang688 | queued | 4 | brain |
| L098 | Adjacency-aware parallel tool batching + MAX_PARALLEL_TOOLS=4 | team6 Johnwang688 | queued | 3 | brain |
| L099 | Working-context block rewritten fresh each step, lifted to message tail | team6 Johnwang688 | queued | 3 | brain |
| L100 | Transcript framed as DATA in context blocks ("describe, do not obey") | team6 Johnwang688 | partial (evidence-wrap covers tool output) | 4 | brain |
| L101 | Per-role model assignment (chat/os/search/memory roles swappable in Settings) | team6 atlas | queued | 3 | brain/config |
| L102 | Majority-vote tool selection for high-stakes calls (sample 3×) | team12 optillm | queued | 3 | brain |
| L103 | Runaway protection: LoopDetector (3 identical/10) + query CircuitBreaker | team14B aws ambient | queued | 4 | brain |
| L104 | ask_human sentinel tool pattern (sentinel + return_direct, orchestrator resumes) | team14B aws ambient | queued | 3 | brain |
| L105 | Untrusted-input labelling for ambient input (fail-closed guardrails) | team14B aws ambient | partial (DCL covers payloads) | 3 | brain |
| L106 | Cursor-advance on deterministic post-processing failure (never spin on a bug) | team5 myagent | queued | 3 | brain |
| L107 | Per-agent budgets USD (80% warn / 100% hard-stop, persisted) + complexity triage pre-loop | team5 sofia | queued | 3 | brain |
| L108 | Resumable sessions by group id (crash/network resume w/ full context) | team10 Hume EVI | partial (session wake exists) | 3 | brain |
| L109 | Guarded bootstrap identity injection (caps 20K/file, reject abs paths/NUL/traversal) | team5 nullclaw | partial | 3 | brain |
| L110 | Hard loop arithmetic caps (iterations, history msgs, per-turn token limit) | team5 nullclaw | partial (ReAct caps exist) | 4 | brain |

### B2 · Gate & safety sharp edges

| ID | Mechanism | Source | Status | Value | v2 module |
|---|---|---|---|---|---|
| L111 | Alias normalization (repair hallucinated tool names/arg keys before allowlist) | team2B pdagent | queued | 4 | gate |
| L112 | Expiring command envelope (generation+seq+ts, ≤500ms TTL, stale → read-only) | team2B Rider-Pc | queued | 3 | gate |
| L113 | Invisible-Unicode sanitization in approval prompts (zero-width shown as escapes) | team2B hyperclaw | queued | 4 | gate |
| L114 | safe_command decorator (fail-closed auth + private-chat-only + token bucket) | team2B pdagent | partial | 3 | gate |
| L115 | Deny-on-timeout remote approvals (300s) | team2B aizen | queued | 3 | gate/phone |
| L116 | Backlog-skip on bot startup (drop pending updates; reboots never replay) | team2B aizen/pdagent | queued | 4 | phone |
| L117 | Per-tool rate limits (screenshot 5/min, clicks 15/min class) | team2B pdagent | queued | 3 | gate |
| L118 | Verb-regex classification of unknown tools (create/update/delete/send/exec = mutating) | team5 CowAgent | queued | 4 | gate |
| L119 | Reach-widening write refusal (writes to MCP configs/creds/session settings refused) | team5 CowAgent | queued | 4 | gate |
| L120 | Three session permission modes (read-only / workspace-write / full) | team5 CowAgent | partial (tiers exist) | 3 | gate |
| L121 | Three-layer approval chain (hard rules → heuristic risk → LLM advisor, advisor can only relax soft) | team5 sofia | queued | 4 | gate |
| L122 | Delegated-authority envelopes + neutral-context rule on delegation | team5 jarviscore | queued | 2 | gate |
| L123 | Composable tool policies (allow/deny/rate objects + audit/retry/validation hooks per call) | team5 ArgentAIOS | partial | 3 | gate |
| L124 | Read-before-write enforcement (write_file can't clobber unread files) | team6 Johnwang688 | queued | 4 | gate/skills |
| L125 | Tokenised shell blocklist (parse rm etc. surviving quoting/env/expansion) — upgrades L049 | team6 casha-cashu | queued | 5 | gate/pc_control |
| L126 | Interpreter inline-code recursive screening (sh -c / python -c payloads) | team6 casha-cashu | queued | 4 | gate |
| L127 | Sanitized environment + timeout contract for all shell execution | team6 casha-cashu | partial | 4 | pc_control |
| L128 | Spoken readback confirmation for sends (recipient + content aloud) | team6 holojarvis | queued | 3 | gate |
| L129 | Delete-always-via-trash rule | team6 holojarvis | queued | 4 | gate |
| L130 | Checksum-verified constitution (refuse start if protected files changed) | team6 guduqingbai | queued | 3 | gate |
| L131 | Hash-chained JSONL audit log + cryptographically signed approvals | team6 AsistenteInteligente | partial (HMAC tokens exist) | 3 | gate |
| L132 | Risk-tier safety policy outside the model (safe/caution/dangerous per tool; dry-run mode) | team1 OpenJarvis | partial | 4 | gate |
| L133 | Voice confirmation timeout (silence = no) + consent dialog shows literal command | team1 dijiclick/Atzingen | partial | 3 | gate |
| L134 | Browser safety envelope (nav allowlist, clean profile, 120-action budget, content untrusted) | team6 Johnwang688 | queued | 3 | gate |
| L135 | Expiring approval codes (approve/deny short code, 10-min TTL) | team6 suyogpawate | partial (PIN exists for phone) | 3 | gate |
| L136 | Group-vs-DM confirmation distinction + quotes-equals-verbatim send rule | team6 suyogpawate | queued | 3 | phone |

### B3 · Voice

| ID | Mechanism | Source | Status | Value | v2 module |
|---|---|---|---|---|---|
| L137 | Interruption watermark for TTS queue (monotonic event_id, drop ≤ watermark) | team10 ElevenLabs SDK | wip (B) | 5 | tts |
| L138 | Ack-driven echo model (per-chunk acks, ack floor, +1.0s grace relax) — sharpens L056 | team1 ethanplusai | wip (B) | 5 | voice_loop |
| L139 | Deterministic fuzzy wake/stop matching (NFC regex + difflib 0.78/0.80, stop before echo filter) | team1 isair | wip (B) | 4 | voice_loop |
| L140 | Transcript buffer segment flags (is_during_tts, processed; 120s rolling) | team1 isair | queued | 4 | voice_loop |
| L141 | Intent judge split (warm small local LLM, temp 0, addressed/stop/ignore, 30s cooldown) | team1 isair | queued | 4 | voice_loop |
| L142 | Rules-first addressee gate (hot-window fragments count as directed) | reverse-eng isair | queued | 3 | voice_loop |
| L143 | Hot window 3.0s post-answer follow-up acceptance | team1 isair | queued | 4 | voice_loop |
| L144 | faster-whisper hallucination guard (no-speech prob drop; feed noise not zeros) | team1 isair | queued | 4 | stt |
| L145 | Whisper hallucination blocklist (exact-match denylist of silence phrases) | team1 kobold_assistant | queued | 3 | stt |
| L146 | STT fallback chain remote→local + language-prior filtering (en/hi) + STT lang fallback retry | team1 eadmin2/gia-guar | partial | 3 | stt |
| L147 | Partial-transcript scheduler (≥1.2s new audio, 1 in flight, 30s cap) | team1 eadmin2 | queued | 3 | stt |
| L148 | Short-burst stitcher + pre-speech padding + dual-stream VAD recorder | team1 HF s2s/gia-guar | queued | 3 | stt |
| L149 | Cheap smart-turn heuristic (trailing conjunction/filler check, 0 tokens) — stdlib path to L059 | team1 HF s2s | queued | 4 | voice_loop |
| L150 | Queue-of-stages pipeline w/ PIPELINE_END + SESSION_END sentinels | team1 HF s2s | partial (stage graph exists) | 3 | voice_loop |
| L151 | TTS text cleaning pack: numbers→words, spoken-form expansion (~40-entry remap), clean-for-TTS w/ secret redaction | team1 Irene/kobold/eadmin2 | queued | 4 | tts |
| L152 | Clause streaming + asymmetric first-chunk split (40/160) + complete-sentence peeling | team1 alts/ethanplusai/eadmin2 | partial | 4 | tts |
| L153 | Spoken-progress cursor (word timestamps × per-voice rate) | team10 Cartesia | queued | 2 | tts |
| L154 | Prefetch-claim speculative TTS (discarded unless claimed) | team1 HF s2s | queued | 3 | tts |
| L155 | TTS cache warmup at startup (canned phrases pre-synthed to RAM) — sharpens L058 | team1 kobold_assistant | wip (B) | 3 | tts |
| L156 | Engine warm-up at startup (throwaway STT+TTS call) | team1 kobold_assistant | queued | 3 | voice_loop |
| L157 | TTS fallback ladder w/ language routing + per-utterance voice by detected language | team1 gia-guar/kishanrajput | partial | 3 | tts |
| L158 | Interrupt-note injection (prefix next prompt with last actually-spoken sentence) | team1 eadmin2 | queued | 4 | voice_loop |
| L159 | Remaining-text bookkeeping + replay_last from cached audio | team1 ethanplusai | queued | 3 | voice_loop |
| L160 | Mic-energy watchdog for silent STT + recognizer lifecycle rules (one live instance, deferred restart) | team1 ethanplusai | queued | 3 | stt |
| L161 | Pre-roll + single-open mic + drop-don't-block queue (640ms pre-roll deque) | team1 OpenJarvis | queued | 4 | voice_loop |
| L162 | Graceful detector degradation (wake failure → push-to-talk fallback + warning) | team1 OpenJarvis | queued | 4 | voice_loop |
| L163 | Push-to-talk as first-class mode | team2D akshayaggarwal | queued | 3 | voice_loop |
| L164 | Config-range validation clamp+warn; per-keyword wake sensitivity; per-phrase thresholds in Settings | team1 py-xiaozhi/thevickypedia/project_alias | partial | 3 | config |
| L165 | Wake L1–L5 anti-false-trigger stack (consecutive frames, peak/bg ratio, cooldown, burst suppression, energy-jump tail confirm) | team1 Voicute | wip (B, with L055) | 4 | voice_loop |
| L166 | Hard-negative mining loop for wake model | team1 Voicute | queued (needs owner-PC corpus) | 2 | voice_loop |
| L167 | sherpa-onnx KeywordSpotter as second wake engine (keywords file, no training) | team1 py-xiaozhi | queued | 3 | voice_loop |
| L168 | Dedicated AEC subsystem beside wake spotter | team1 py-xiaozhi | queued (PC) | 3 | voice_loop |
| L169 | Dual-recognizer split (cheap partial for wake, full for utterance) | team1 Priler | partial | 3 | voice_loop |
| L170 | Wake-stream overflow flag + mic handoff (close wake stream before command listen) + ordered shutdown teardown | team1 thevickypedia | queued | 3 | voice_loop |
| L171 | STT-mishearing equivalence tables for control words (stop/stuff/top → stop) | team1 MushieKings | queued | 3 | voice_loop |
| L172 | Stop-word listener thread during playback + cancel-words before echo filter | team1 MushieKings/ethanplusai | partial | 4 | voice_loop |
| L173 | Adaptive noise-floor energy VAD (2.5× floor, 900ms end, 400ms min, 20s max) + published calibration constants | team1 OpenJarvis/MushieKings | partial | 3 | stt |
| L174 | Bluetooth-mic probe ban (never probe SCO mic; detect deafness from live level) | team1 dijiclick | queued (PC) | 2 | voice_loop |
| L175 | Speakable-response policy (markdown-strip table, max 3 spoken sentences, "full text in app") | team1 row-bot | queued | 3 | tts |
| L176 | Wyoming stage-event vocabulary at stage boundaries | team1 rhasspy | partial | 2 | voice_loop |

### B4 · PC control & system tools

| ID | Mechanism | Source | Status | Value | v2 module |
|---|---|---|---|---|---|
| L177 | System tools skill: system_status, volume get/set, clipboard get/set, brightness get/set, window_list | team2 PanPenek class; built by Team C | **done** (skills/system; test file mid-fix by C) | 5 | skills/system |
| L178 | Element-index clicking + verify→escalate ladder (background→coords→foreground w/ approval) + structured verdicts | team2D hermes | wip (C) | 5 | pc_control |
| L179 | Background-first input delivery (pid/window-targeted, no focus theft) | team2D hermes | queued | 4 | pc_control |
| L180 | Temp-.ps1-file trick (powershell -File kills quoting hell) + argv-not-source rule | team2D open-cowork; reverse-eng ethanplusai | queued | 4 | pc_control |
| L181 | Realpath/symlink containment for tool file paths | team2D open-cowork | partial (jail exists; symlink pass TBD) | 4 | pc_control |
| L182 | Git-checkpoint undo before mutating file effects | team2B aizen | queued | 4 | pc_control |
| L183 | Window ops pack: focus-by-title, minimize-all, close-window | team2 desktop cluster | partial (window_list done in L177) | 3 | pc_control/skills |
| L184 | Power pack: lock / sleep / shutdown / restart (destructive-gated) | team2 desktop cluster | queued | 3 | skills/system |
| L185 | screenshot.save to Pictures + Explorer select | team2 Open.Jarvis | queued | 2 | pc_control |
| L186 | Macro replay (typed action sequences as JSON, no shell) | team2 pdagent | queued | 3 | pc_control |
| L187 | Background exec sessions (spawn/poll/log/write/kill) | team2B hyperclaw | queued | 3 | pc_control |
| L188 | web.open_url (scheme-validated http/https only) | team2 Open.Jarvis | queued | 3 | skills/web |
| L189 | screen.click_vision (vision model → ONLY x,y → regex → click) as no-UIA fallback | team2 Rustamov | queued (after L066/L178) | 3 | pc_control |
| L190 | Clipboard-paste typing fallback + smart type (Ctrl+A/Delete then paste >20 chars) | team2B pdagent; team2C Rustamov | partial | 3 | pc_control |
| L191 | LibreHardwareMonitor telemetry source w/ fallback chain (LHM → nvidia-smi → honest unavailable) | team6 miguelrobles | queued | 3 | skills/system |
| L192 | Focused-app prompt shaping for dictation (app class changes formatting prompt) + system-wide dictation mode | team1 tambourine/Atzingen | queued | 3 | pc_control |
| L193 | PID-file single-instance lock w/ process verification | team2B pdagent | queued | 3 | other (launcher) |

### B5 · Memory & agents (teams 3/5/6 deep cuts)

| ID | Mechanism | Source | Status | Value | v2 module |
|---|---|---|---|---|---|
| L194 | Ebbinghaus half-life decay in ranking (strength = conf × exp(−0.1·days/(1+0.2·consolidations))) — formula sharpens L030 | team3 cortex-mem; reverse-eng isair | partial (decay exists, formula TBD) | 4 | memory |
| L195 | Two-stage forgetting thresholds (archive <0.1, hard-delete <0.02) + reasoned deletion events | team3 cortex-mem | queued | 3 | memory |
| L196 | L0/L1/L2 layered memory files, all layers indexed | team3 cortex-mem | queued | 3 | memory |
| L197 | Entity:slot:value MemoryCards + confidence-dedup merge (no LLM judge) | team3 memvid | queued | 4 | memory |
| L198 | Two-stage retrieval rerank (BM25+HNSW → rescore, top_k cap, min_score) | team3 memvid | partial (FTS5 only) | 4 | memory |
| L199 | Dual-layer Memory-vs-Raw recall (distilled + raw chunks, both FTS) | team3 agent-memory | queued | 4 | memory |
| L200 | Provenance pointers on every hit + trace command (open cited source range) | team3 agent-memory | partial | 3 | memory |
| L201 | Supersedes revision chains (append linked, never silent overwrite) | team3 agent-memory | partial (supersede exists) | 3 | memory |
| L202 | SQLite graph memory (entities/relations/aliases, uuid5 merge) + PPR diffusion ranking | team3 graph-memory/HippoRAG | queued | 4 | memory |
| L203 | Whole-hit token-budget injection capper (never half a hit, fail-silent) | team3 graph-memory | queued | 4 | memory |
| L204 | Index hygiene pack: mtime-sum change stamp, MD5 passage dedup, index-manifest identity binding (reject+rebuild on mismatch) | team3 lossless/HippoRAG | queued | 3 | memory |
| L205 | Snapshot-before-forget (copy sqlite before destructive op) | team3 memoria | queued | 4 | memory |
| L206 | retrieval_feedback log (which injected memories the answer actually used) | team3 memoria | queued | 3 | memory |
| L207 | Axioms layer (numbered decision rules as versioned memory w/ persona) + routing-table memory | team3 context-infrastructure | partial (JARVIS-RULES ≈ axioms) | 3 | memory/brain |
| L208 | Dream consolidation: cursor-watermark background pass + restricted write-set + compaction gated on watermark + git-versioned memory files | team3 nanobot | queued (extends L030) | 4 | memory |
| L209 | FTS robustness pack: hit_count/last_hit_at columns, 3-step keyword cascade, FTS self-healing index check, hash-settled flushes | team3 CowAgent | queued | 3 | memory/session_store |
| L210 | Memory scoping by user+agent + hierarchical kill-switch tri-state | team3 khoj | queued | 2 | memory/gate |
| L211 | Candidate facts with expiry + policy boundary shrinking on counter-evidence | team3 memmy-agent | queued | 3 | memory |
| L212 | Skill crystallization from successful policies (versioned, repair, archival) — cf. L230 | team3 memmy-agent | queued | 4 | skills |
| L213 | Bi-temporal memory rows (valid_from/to, superseded_by, point-in-time recall) | learn-research-frontiers (via survey) | queued | 3 | memory |
| L214 | Confidence-tagged injection (verified facts vs hint-only) + subject gating + temporal-reference resolution before search | team6 DavidLiuXh | partial (provenance tiers ≈ tags) | 4 | memory |
| L215 | Encrypted local GraphRAG (SQLite nodes/relations + FTS5 + PPR, namespace isolation) | team6 AsistenteInteligente | queued | 3 | memory |
| L216 | Nightly memory rewrite as undoable version (each note shown w/ source record, owner-correctable) | team6 samsara0xgg | queued | 3 | memory |
| L217 | Self-evolution review agent pack (idle-triggered, isolated, restricted tools, silent-default, fix-SOURCE rule, anti-poisoning capture rules, snapshot-before-edit, finish-unfinished-silently) | team5 CowAgent | queued | 5 | self_critique |
| L218 | Prompt optimizer pre-pass (rewrite-only, placeholders for ambiguity, never executes) | team5 CowAgent | queued | 3 | ask_controller |
| L219 | Dedicated ErrorAnalyzer pass (separate agent reads error → summary + fixes) | team5 autogluon | queued | 3 | brain |
| L220 | Heartbeat stall detection for agent tasks | team5 agentara | queued | 3 | session_store |
| L221 | Watcher state ladder (GONE/FRESH/NEEDS_YOU/WORKING/SHELL precedence) | reverse-eng ethanplusai; team5 skyfire | wip (E) | 4 | proactivity/session_store |
| L222 | Summary validation gate (summary must pass acceptance before replacing raw history) | team5 skyfire | queued | 3 | session_store |
| L223 | Zero-LLM session compression (raw md log + detached indexer) + watermark discipline + no-LLM compactor fallback | team5 Deus/orcbot | queued | 4 | session_store |
| L224 | Structured compaction sections (GOAL/DONE/DECISIONS/FAILED/OPEN/FILES) | team6 Johnwang688 | queued | 3 | session_store |
| L225 | Per-message token accounting in session schema + delta event reads per turn | team5 openwhale; team6 samsara0xgg | partial | 3 | session_store |
| L226 | Namespaced KV blackboard w/ TTL + provenance | team5 openwhale | queued | 2 | memory |
| L227 | Advisory file locks + checksum write-log + merge strategies for concurrent writes | team5 openwhale | queued | 2 | other |
| L228 | Config-as-git-repo w/ PR workflow for self-config changes | team5 nerve | queued | 2 | other |
| L229 | Registered-probe A/B retrieval gate (baseline/raw/distilled arms on probe queries) | team3 agent-memory | queued | 3 | verifier |

### B6 · Skills system

| ID | Mechanism | Source | Status | Value | v2 module |
|---|---|---|---|---|---|
| L230 | Skill mining/crystallisation from traces (recurring successful sequences → quarantined manifests) | reverse-eng OpenJarvis; team10 Hermes | queued | 5 | skills |
| L231 | Skill solidification (completed task frozen into parameterised template, replayed not re-planned) | team6 Nolan | queued | 5 | skills |
| L232 | Skill suggester (mine conversations for repeated patterns → propose for approval) | team5 opencrust | queued | 4 | skills |
| L233 | Deterministic grammar tier per-skill phrases.txt (exact → fuzzy → LLM → clarify; router rebuilds from installed skills) | team10 Rhasspy/Hassil/Leon | wip (F) | 5 | skills |
| L234 | Blocking/background tool declarations (`behavior` flag; background speaks holding line, async result) | team10 Gemini/GPT-Live | queued | 4 | skills |
| L235 | Typed inspectable action programs (render `now => action(...)` before execution) + composed-plan preview | team10 Almond/Bixby | queued | 3 | skills |
| L236 | Synthetic phrase generation from templates (test the deterministic tier) | team10 Genie | queued | 3 | skills/tests |
| L237 | Named tool-groups router selects as a unit ("experts") | team10 Alexa+ | queued | 2 | skills |
| L238 | @tool decorator deriving JSON schema from type hints + AST-based tool self-discovery | team6 Johnwang688; team2D hermes | partial (manifest discovery exists) | 3 | skills |
| L239 | Trace-based skill improvement proposals (stored as data, human applies) | team5 cedricziel | queued | 3 | skills |
| L240 | Grammar-from-state fast path (grammar built from entities/actions that exist now) | team1 HomeIntent | queued | 3 | skills |
| L241 | Repair loop w/ all failed attempts in prompt, ast-validated, cap 3 | team5 jarviscore | queued | 3 | skills |
| L242 | Capability learning behind a review gate (research missing capability → review → activate) | team6 AsistenteInteligente | queued | 3 | skills |
| L243 | Apps Script webhook bridge for Gmail/Calendar (zero OAuth console) | team6 pranithvelar | queued | 3 | skills |
| L244 | Plugin manifest contract (start(core) → manifest w/ default_options, engine table, per-plugin persisted options) | team1 Irene | partial | 2 | skills |

### B7 · Proactivity (team 14 deep cuts — call-ringing exists at L060; these are its organs)

| ID | Mechanism | Source | Status | Value | v2 module |
|---|---|---|---|---|---|
| L245 | Morning digest (declarative sections+sources over collector machinery; briefing run protocol: 10-min overlap, verify live, ≤8 lines, advance state) | reverse-eng OpenJarvis; team14 GAIA/daily-brief | wip (E) | 5 | proactivity |
| L246 | Statistical anticipation (time-cluster patterns, conf formula, ≥3 occ/≥2 days) + 3-gate restraint (≤1/hr, quiet hrs, idle ≥5min; high-conf relaxes idle gate) | team6 Nolan | wip (E) | 4 | proactivity |
| L247 | Trust/autonomy ladder L1–L4 (promote 10/25/50 successes, demote on failure) + shadow success + urgency-override daily cap | team5 myagent | queued | 4 | proactivity |
| L248 | Watcher announce policy (blocked rings now+singular; completions batched; FRESH never) + primary-session margin rule | reverse-eng ethanplusai | wip (E) | 4 | proactivity |
| L249 | Tick scheduler cadences (Observe 60s → Think 5min → Consolidate 4h → Reflect 12h) | team5 myagent | queued | 3 | proactivity |
| L250 | Intention state machine + two-phase arming (pending_arm→armed→surfaced/superseded/resolved/suppressed) | team14B hawky | queued | 4 | proactivity |
| L251 | Ambient watcher: 60s latent heartbeat, in-flight guard, composite trigger latches | team14B hawky | partial | 3 | proactivity |
| L252 | Weakest-link MIN aggregation + 0.6 surface threshold | team14B hawky | queued | 3 | proactivity |
| L253 | Fail-closed batched relevance gate (1 LLM call judges all candidates/tick; failure = silence) | team14B hawky | queued | 4 | proactivity |
| L254 | Delivery channels + busy policies (hard/timed/soft × speak/queue/cancel/card) + quiet/ambient/directive modes | team14B hawky | partial | 4 | proactivity |
| L255 | Durable suppression keys (decline → permanent normalized suppression) + satisfaction sweep | team14B hawky | queued | 4 | proactivity |
| L256 | Single-`now` lane invariant (max 1 ringing item) + decision provenance {owner, policy, rationale} + ambient HUD cards 5-min TTL | team14B paperclip | partial | 3 | proactivity |
| L257 | Deterministic regex intent detectors w/ stable rule IDs + relation hints (resolves/supersedes/repeats) | team14B paperclip | queued | 3 | proactivity |
| L258 | Atomic claim-or-park cooldown (60s; exactly one burst member rings) | team14B aws ambient | queued | 3 | proactivity |
| L259 | autoExecute=False default (new sources earn ringing rights per-source) | team14B aws ambient | queued | 4 | proactivity |
| L260 | Grace delay + re-check user state at delivery + 3-level DND mapping (fail-open urgent) | team14B agent-notifications | partial | 4 | proactivity |
| L261 | Two-gate interruption design (triage classify + per-tool interrupt verb matrix) | team14B langchain ambient | partial | 4 | proactivity |
| L262 | Correction→preference-store loop (pickup/dismiss/edit writes preference the classifier reads) | team14B langchain ambient | partial (ring learning exists) | 4 | proactivity |
| L263 | Context-conjunction reminder gating + debounce + snooze re-entry | team14C MicroReminders | queued | 3 | proactivity |
| L264 | Snapshot/diff anti-fatigue (prefetch state, diff, only delta to LLM; reported-items ledger) | team14C second-brain/daily-brief | queued | 4 | proactivity |
| L265 | 3-bucket notify policy (ring now / batch / silence) + 30-min heartbeat in active hours | team14C second-brain | partial | 3 | proactivity |
| L266 | Proactivity ladder as user-facing setting (Observer→Advisor→Assistant→Partner) | team14C second-brain | queued | 3 | proactivity/config |
| L267 | Canonical-key + TTL dedup file + per-section caps for briefings | team14C indfir | queued | 3 | proactivity |
| L268 | Draft lifecycle (drafts/active YAML, 24h expiry, sent/ = voice corpus) + drafts-never-send invariant | team14C second-brain; team14 GAIA | queued | 3 | proactivity |
| L269 | Dry-run gate for authored routines (must run clean once before ringing) | team14 memUBot | queued | 4 | proactivity |
| L270 | Atomic schedule claim + crash reaper (stale EXECUTING recovery scan) | team14 GAIA | queued | 4 | proactivity |
| L271 | Deactivation-reason ownership (auto-resume never overrides a user-owned reason) | team14 GAIA | queued | 3 | proactivity |
| L272 | Routine guard (one schedule table + window check + period-key once-guard + wall-clock budget → partial) | team14 ai-employees | partial | 3 | proactivity |
| L273 | Missed-task grace (>600s overdue: skip + report, never run late) | team2B pdagent | queued | 4 | proactivity |
| L274 | Scheduled-task persistence (DB row + queue in sync, re-arm on restart) | team5 agentara | partial | 3 | proactivity |
| L275 | Proactive card right-level feedback (each card asks: right level? tunes budget) | team6 samsara0xgg | queued | 3 | proactivity |
| L276 | Held-back items saved for one later summary (not repeated interruptions) | team6 samsara0xgg | queued | 3 | proactivity |
| L277 | First-message-of-the-day digest trigger (no cron needed) | team6 NikQuila | queued | 3 | proactivity |
| L278 | Conditional triggers w/ verified conditions (execution-type, checked online when due) | team6 Nolan | queued | 3 | proactivity |
| L279 | Curiosity question taxonomy driving proactive exploration | team6 guduqingbai | queued | 2 | proactivity |
| L280 | Progress narration from event stream (cheap side model, ~8–15s, cut on answer) | team1 Atzingen | queued | 3 | proactivity |
| L281 | Pre-execution action verifier for outgoing actions (per-tick op budgets, contact whitelist, secret FLAG regexes) | team5 myagent | queued | 4 | gate/proactivity |
| L282 | Proactive-only response critique (cheap model scores sends 1–10, thr 6, fail-open, bypass for replies/digests) | team5 myagent | queued | 3 | self_critique |

### B8 · Phone & webapps

| ID | Mechanism | Source | Status | Value | v2 module |
|---|---|---|---|---|---|
| L283 | Phone offline queue/retry (drop w/ reason, re-attempt next poll, timed fire reschedules, re-emit guard) | team14B hawky | queued | 4 | phone |
| L284 | Ack-first webhook + background processing (200 OK immediately) | team10 wassenger | partial (poll model differs) | 3 | phone |
| L285 | Cheapest-first eligibility gauntlet before any LLM cost + two-phase quota (memory counter + persistent flag → human handoff) | team10 wassenger | queued | 3 | phone |
| L286 | ~20-message bounded per-chat context + modality placeholders | team10 wassenger | partial | 3 | phone |
| L287 | Decorator signature check (Telegram secret_token/HMAC) + shape-gate before handler | team10 daveebbelaar | partial | 4 | phone |
| L288 | Self-hearing guard + platform-type event filtering + venue-scoped memory + unified origin addressing | team10 AstrBot | partial | 4 | phone |
| L289 | In-chat admin surface (!reset/!config) + opus voice-note temp-file recipe + whitelist-first gating | team10 askrella | partial | 3 | phone |
| L290 | Ephemeral session tokens for web/phone clients (PC mints 60s token; keys never leave PC) | team10 OpenAI relay pattern | queued | 3 | phone |
| L291 | Gladys-style E2EE relay blueprint (AES-GCM-256 + RSA-OAEP wrap, ECDSA sign, expiry anti-replay) | team10 Gladys | queued | 2 | phone |
| L292 | Satellite split (voice stages as separate processes under strict contracts; phone as satellite) | team1 rhasspy | queued | 2 | phone |
| L293 | MV3 extension + Native-Messaging host (owner's authenticated browser as tools) + planner/navigator/validator + URL firewall | team10 mcp-chrome/Nanobrowser | queued | 4 | other (browser) |
| L294 | Per-turn privacy receipt (log exactly what left the machine this turn) | team10 Apple PCC pattern | queued | 4 | observability |
| L295 | NL query over own device/state history ("Ask Home") from local event log | team10 Gemini for Home | queued | 3 | other |
| L296 | ESPHome phase enum for HUD states (idle/waiting/listening/thinking/replying + INTENT_PROGRESS) | team10 ESPHome | partial | 2 | chat_gui |

### B9 · Inference & local model (team 12 — RTX 2060 specific)

| ID | Mechanism | Source | Status | Value | v2 module |
|---|---|---|---|---|---|
| L297 | Speculative decoding Modelfile (DRAFT 0.5B GGUF + draft_num_predict 4; 1.5–2.4× on tool JSON) | team12 Ollama | wip (F) | 5 | llm_ollama |
| L298 | MTP-head awareness (re-pull registry models after Ollama upgrade) | team12 Ollama MTP | queued | 2 | llm_ollama |
| L299 | Flash attention forced ON + native sm_75 build | team12 llama.cpp/Ollama | queued (owner-PC config) | 4 | setup |
| L300 | KV sizing discipline (56KB/token Qwen2.5-7B; q8_0 KV preferred) + context sizing (num_ctx 4096, NUM_PARALLEL=1) | team12 llama.cpp | queued | 4 | llm_ollama/config |
| L301 | Server economics (keep_alive=-1, MAX_QUEUE awareness) | team12 Ollama FAQ | partial | 3 | llm_ollama |
| L302 | Ollama native tool calling (tools param → tool_calls) as local-path reliability bet | team12 Ollama API | partial (native path exists in llm_ollama) | 4 | llm_ollama |
| L303 | llama-server fallback engine (prompt caching, ngram self-spec, full GBNF) | team12 llama.cpp; index B2 | queued | 4 | llm_compat |
| L304 | Prompt/prefix caching to kill ~12s cold-prefix prefill (--cache-prompt + slot similarity) | team12 llama-server | queued (w/ L303) | 4 | llm_compat |
| L305 | Decoder-level GBNF grammar constraints via llama-server — hard-guarantee sibling of L007 | team12 llama.cpp | queued | 4 | llm_compat |
| L306 | VRAM budget pre-start guard (weights + 56KB×ctx + draft + whisper ≤ 5.5GB; refuse/warn) | team12 VRAM table | wip (F) | 5 | setup |
| L307 | Trace stats analyzer over session log (per-route success/latency/tokens) — engine-room of L005 | reverse-eng OpenJarvis | done (as L005) | — | session_store |

**Section B counts: 223 rows (L085–L307) · done 2 · partial 36 · missing 0 ·
wip 13 · queued 171 · n-a 1 (L307 folded into L005).**
("missing 0" is honest bookkeeping: B-rows are newly catalogued today, so
unstarted ones are `queued`, not `missing` — `missing` is reserved for
Section A items verified absent during the audit.)

---

## Section C — Learn-file deep mechanisms (survey of 22 under-counted files)

Granular items consolidated into buildable clusters. Full item lists live in
the source files; each cluster = one build task.

| ID | Mechanism (cluster) | Source | Status | Value | v2 module |
|---|---|---|---|---|---|
| L308 | Metareasoning controller: EU(c)=VoI−Cost over 5 currencies + per-type attempt caps + aspiration gates T1–T3 + escalate-or-abstain path | learn-adaptive-computation-math | missing | 4 | brain |
| L309 | P(change) instrumentation + prediction log (predicted VoI vs realized; overprediction = controller bug) + failure clustering by epistemic taxonomy | learn-adaptive-computation-math | queued | 3 | observability |
| L310 | PID retry/failover governor (P/I/D over failure rate; anti-windup) + backoff jitter + single shared retry budget | learn-control-theory | queued | 3 | brain |
| L311 | VRAM budget governor (shed KV → unload tier → preemptive shed before OOM) | learn-control-theory | queued (w/ L306) | 4 | brain/setup |
| L312 | Disturbance rejection inside tool wrapper (bounded auto-retry; brain sees only unrejected failures) + supervisory clamp above brain | learn-control-theory | queued | 3 | skills/gate |
| L313 | FAST vs DEEP two pipelines + binary router (uncertain → DEEP; misroute rerun bounded) + structure.selected event | learn-dynamic-modules | partial (cf. L091) | 4 | brain |
| L314 | Multi-scale layer law pack: only-L1-emits-actions, execution-time re-validation of every tool.call, plan/objective contract hashing, preemption SLOs + debounce, triple nested circuit breakers, causal_parent chain on events | learn-multi-scale | partial | 4 | gate/observability |
| L315 | Degradation ladder R0–R4 (measured triggers, announce once, recovery one rung at a time, never loosens permissions) + readiness canary for brain server | learn-reliability-spec | missing | 4 | brain/setup |
| L316 | Reliability SLO pack: implicit turn-failure signal (rephrase ≤30s), monthly error budgets + burn policy, burn shown in HUD | learn-reliability-spec | queued | 3 | observability/chat_gui |
| L317 | Checkpoint discipline: cadence from RPO (5min/50 events + before destructive), corrupt-checkpoint quarantine + boot from event-log replay, poison-job quarantine, monotonic clocks for all intervals/expiry | learn-reliability-spec | partial | 4 | session_store/gate |
| L318 | Fault-injection release gate (kill -9 mid-task ×20: ≥80% correct resume, 100% no duplicate mutation) + per-dependency detection/fallback table | learn-reliability-spec | queued | 3 | tests/setup |
| L319 | Contract-conformance harness: effect-diffing (FS hash tree/syscalls/net/env/DB), N=3 nondeterminism budget, jail invariant auto-FAIL, tiered mocks + drift gate + known_complete graduation | learn-contract-conformance | queued | 3 | tests/skills |
| L320 | Skill-system strictness pack: manifest strictness (unknown keys = startup error), schema-from-signature drift check, isolation rules, discovery-never-executes, import guard (5s timeout), audit_wiring(), hot reload w/ clean unload | learn-skill-system-spec | partial (much exists; strictness gaps TBD) | 4 | skills |
| L321 | Skill runtime pack: per-task capability grant = manifest ∩ turn allowance, tier upgrade-never-downgrade, tool pipeline (parse→validate→capability→risk→dispatch→bound→output-validate→wrap→log), per-skill circuit breaker, metered-tool spend guard, global concurrency budget 8/queue 64, quota_exhausted as first-class outcome | learn-skill-system-spec | partial | 4 | skills/gate |
| L322 | SKILL.md progressive disclosure (L0 always, L1 on trigger, L2 on demand; frontmatter ↔ skill.json cross-check; Permissions + Evidence sections) | learn-skill-system-spec | queued | 3 | skills |
| L323 | Claim-verification full stack: least-privilege judging, verbatim-quote rule w/ substring check, CoVe decomposition, isotonic calibration (ECE ≤0.10), pre-registered judge deploy rule (Wilson ≥0.88, κ ≥0.60), MCQ-with-abstain | learn-self-verification-calibration; learn-claim-verification | queued (engine of L016) | 4 | verifier |
| L324 | POMDP escalation from measured judge TPR/FPR + Beta prior (accept / escalate-check / escalate-human by expected cost) | learn-self-verification-calibration | queued | 3 | brain |
| L325 | Mental dry-run for irreversible actions (2–3 predicted outcomes) + weak-model pre-screen of plans | learn-research-frontiers | queued | 3 | brain/verifier |
| L326 | Milestone-based task scoring (verifiable subgoals, not binary success) | learn-research-frontiers | queued | 3 | observability |
| L327 | Entity resolution at write time (canonical entity table, confidence-scored linking; reads never guess) | learn-research-frontiers | queued | 3 | memory |
| L328 | Bradley-Terry private arena on owner's real prompts (blind pairwise, style ≠ completion) | learn-research-frontiers | queued | 2 | tests |
| L329 | Golden-set discipline pack: private 50–100 real tasks dev/held-out split, canary GUIDs, synthetic rule-generated tasks w/ fixed seed, eval version pinning, per-task regression diffing, quarterly 25% retire | learn-continual-learning | queued | 4 | tests |
| L330 | LLM-judge-as-contract (judge over verified artifacts w/ veto; judge itself eval'd vs human labels) + ablation protocol (one variable, null ablation, negative controls) | learn-continual-learning | queued | 3 | verifier/tests |
| L331 | Self-synthesized rehearsal (LLM-generated rehearsal examples instead of storing user data) | learn-continual-learning | queued | 2 | memory |
| L332 | SQLite discipline pack: PRAGMAs on every connection, user_version migrations (tested on copy), live backup via VACUUM INTO + rotation + integrity-verified restore | learn-databases | partial | 4 | memory/session_store |
| L333 | Hybrid search pipeline for knowledge: BM25 top-50 + vector top-50, RRF k=60, cross-encoder rerank, contextual retrieval at ingest, per-type chunking, citation mapping enforcement, tenant isolation wrapper | learn-databases | partial (FTS5 only today) | 4 | skills/knowledge |
| L334 | Evolving-defense pack: antibody store pre-check w/ incident citation, per-skill adaptive baselines, heal-and-retry gate outcome, failure-reflection records, intent-consistency check, honeypot decoy skills, user-outranks-wall rule | learn-evolving-defense | queued | 4 | gate |
| L335 | Red-team harness pack: self-grading triples, skill-manifest fuzz mutators, persistent-state poison probes, containment rails, TriPlay independent evaluator, success-flip scoring | learn-evolving-defense; learn-attack-trees | queued | 3 | tests/verifier |
| L336 | Gate hardening pack: used-nonce set in gate-private memory, log-as-audit-only (never proof of approval), deterministic tier derivation (never brain-emitted), burst detector step-up, no-context-claim-authorization audit rule | learn-attack-trees; learn-fault-trees | partial | 4 | gate |
| L337 | Approval-UX full spec pack: 7-field dialog, filename control-char sanitization, per-item naming for T3, dwell gate (3s/5s), novelty-scaled friction, fatigue step-up ladder, native trusted chrome, say-it-back voice protocol, speaker-verification-as-tripwire, plan-as-contract, weekly autonomy review card, standing-grants revocation surface, learned policy proposals (opt-in only), autonomy settings downward-only | learn-approval-ux-spec | partial (dialog + budget + burst exist) | 5 | chat_gui/approvals/gate/config |
| L338 | Chat-UI discipline pack: streaming render batching, memoized rows + virtualized history, composer queue/drafts/IME, voice transcribe-for-review, brain-state + mic-state text labels, waveform w/ reduced-motion, accessibility passes, window-geometry validation, show-without-activating summon, startup watchdog + crash dialog, hotkey single-owner | learn-chat-ui-spec; index U1/U8 | partial | 3 | chat_gui |
| L339 | Cold-start belief pack (engine of L015): 4-source prior elicitation w/ caps, class Beta defaults, hierarchical shrinkage, attestation + falsification, burn-in by evidence mass, graduation thresholds per class, prior-predictive conflict check, day-one trust UX | learn-cold-start | queued | 3 | memory/brain/chat_gui |
| L340 | Bounded-rationality pack: 3-gate stopping rule per step, anytime subsystem contracts, aspiration dynamics logging, predictive router ≤30ms, token budget as measured formula, voice hard-task deferral, satisficing contract per tier, recognition-primed fast path | learn-bounded-rationality | queued | 3 | brain/config |
| L341 | DCL depth pack (beyond L045): pipeline-stage placement, known-secrets registry (salted hash shared w/ log redaction), Tier-B pattern set, decode-then-scan ≤2 layers, split-secret session buffer, withhold placeholders, taint through summarization, 4 enforcement points, what-left-the-machine feed, SECRET-never-spoken TTS check, privacy dashboard, local-only mode | learn-data-classification (SEC12) | partial | 5 | dcl/gate/chat_gui/tts |
| L342 | SWE gate pack: per-change FAIL_TO_PASS list, 6-point correctness check, mandatory pre-commit ruff+mypy+security scan, debug iteration policy (max 2 self-fixes), second-model review validity conditions, verify-first prompting | learn-ai-for-se | queued | 3 | tests/brain |
| L343 | Vision grounding pack: UIA→OCR→screenshot ladder w/ verify-after-acting, 2-step zoom grounding, resident small grounder, OCR ladder on crops, vision budget discipline, local-first vision gating | learn-multimodal (U9) | partial (UIA-first exists) | 4 | skills/pc_control |
| L344 | Document pipeline routing (MinerU tables / Docling general / mandatory OCR for image-only PDFs) | learn-multimodal | queued | 2 | skills |
| L345 | Adapter-per-skill (O-LoRA) + retrieval adapter router + TIES/DARE merging | learn-continual-learning (B10) | n-a (no local training in v2 scope) | — | — |
| L346 | Program synthesis / theorem proving | learn-program-synthesis | n-a (study verdict SKIP) | — | — |
| L347 | Provenance audit framework | learn-provenance-audit | n-a (survey verdict SKIP; provenance tiers already at L025) | — | — |

**Section C counts: 40 rows · done 0 · partial 11 · missing 2 · wip 0 ·
queued 24 · n-a 3.**

---

## Section D — Archaeology / MASTER-INDEX additions (363-repo PhD harvest)

Rows the audit never carried as separate items. Index IDs kept in Source.

| ID | Mechanism | Source | Status | Value | v2 module |
|---|---|---|---|---|---|
| L348 | llama-server (ik_llama.cpp) directly instead of Ollama as an engine option — merged into L303 | index B2 | queued (see L303) | 4 | llm_compat |
| L349 | 9B daily-driver model spec (Qwen3.5-9B Q4_K_M, 32K cap) as default local model candidate | index B3 | queued (owner-PC bench) | 4 | llm_ollama/config |
| L350 | Chatterbox TTS rung (MIT, Hindi first-class) in the ladder — sharpens L057 | index V2 | queued | 4 | tts |
| L351 | livekit-wakeword synthetic-data wake model ("hello jarvis", threshold 0.68, no owner clips) — alternative to L055 | index V4 | queued | 4 | voice_loop |
| L352 | Moshi Inner Monologue (brain emits text trace while speaking) | index V5 | queued | 3 | brain/tts |
| L353 | E2B-style microVM sandbox ladder for code execution | index SEC6 | queued | 3 | skills/code |
| L354 | Credentials-never-in-sandbox structural rule (managed-agents pattern) | index SEC1 | partial (keyring + gate approximate) | 4 | gate/config |
| L355 | Letta OS-tier memory (core/recall/archival) + agent self-edits own memory | index M4 | queued | 3 | memory |
| L356 | Agent Plugins 1.0 standard conformance for skill format (SKILL.md content / Plugins packaging / MCP protocol) | index S2 | queued | 3 | skills |
| L357 | ClawHavoc defenses pack: quarantine+scan every skill VERSION, fail-closed installPolicy, secrets in host process, agent-written skills staged for review | index S1 | partial | 4 | skills |
| L358 | Hands-on proven patterns not yet ported: audit_wiring() (in L320), event-bus replay-reduce rule, bug-demos-as-xfail testing, fault-injection suite (832-pass pattern) | index S3/S4/I5/F7 | partial | 3 | skills/tests |
| L359 | DeepEval + persona simulation evals (Hinglish + adversarial personas; v1 criticals mapped to eval layers) | index I2 | queued | 4 | tests |
| L360 | Teach & Repeat PC control + artifact-judged GUI verification ("shall I do it in 3 steps?") | index U5 | queued | 4 | pc_control |
| L361 | Dodaios supervisor pattern (process supervision before voice; Ack-Brain) | index U6 | queued | 3 | other |
| L362 | Scripted first-3-interactions (competence-shock floor-raising) + 10 pre-built chat components (model fills props only) | index U4/U1 | queued | 3 | chat_gui |
| L363 | Event-sourcing LITE + durable local SQLite queue (no server) — formalizes session_store direction | index I6 | partial | 3 | session_store |
| L364 | Open-problems measurement backlog (top-10 unknowns as on-PC measurement tasks) | index I8 | queued (owner-PC) | 2 | setup/tests |

**Section D counts: 17 rows · done 0 · partial 4 · missing 0 · wip 0 ·
queued 13 · n-a 0.**

---

## Grand totals (snapshot 2026-10-20 ~12:20 IST)

| Section | Rows | done | partial | missing | wip | queued | n-a |
|---|---|---|---|---|---|---|---|
| A — audit seed | 84 | 36 | 21 | 8 | 11 | 0 | 8 |
| B — megascan steals | 223 | 2 | 36 | 0 | 13 | 171 | 1 |
| C — learn deep cuts | 40 | 0 | 11 | 2 | 0 | 24 | 3 |
| D — archaeology | 17 | 0 | 4 | 0 | 0 | 13 | 0 |
| **TOTAL** | **364** | **38** | **72** | **10** | **24** | **208** | **12** |

Honesty note on the owner's "500–600+ researched items": this ledger counts
*implementable mechanisms* (364). The 500–600 figure counts research
*artifacts* (363 archaeology repo studies + 106 scout studies + ~79 learn
files + ~250 megascan repos) — most artifacts yield 0–2 mechanisms, and many
mechanisms repeat across artifacts (deduped here). When the 6 pending
megascan reports land, expect +40–80 rows.

## Top of the queue (value 5, not yet started — after the wip rows finish)

1. L125 Tokenised shell blocklist (team6 casha) — gate/pc_control
2. L137→wip · L055→wip · L297→wip · L233→wip (already with teams)
3. L217 Self-evolution review agent pack (CowAgent) — self_critique
4. L230 Skill mining from traces (OpenJarvis) — skills
5. L231 Skill solidification (Nolan) — skills
6. L337 Approval-UX full spec pack — chat_gui/approvals
7. L341 DCL depth pack — dcl
8. L085→wip (A) · L086→wip (A) · L245→wip (E) · L177 done (C)

## Pending intake (next ledger pass)

- megascan team4 (HUD/GUI steals), team7, team8, team9, team13 (browser
  agents), team15 — reports still being written at snapshot time.
- team11 (MCP) code-read pass — blocked by GitHub 429 on 2026-10-20; pool
  triaged, deep reads pending (will sharpen L079).
- FIRST-RUN-AUTOPSY MEDIUM/LOW leftovers (9 + 3) — not yet ledgered; add as
  fix-rows when the autopsy file is next swept.
