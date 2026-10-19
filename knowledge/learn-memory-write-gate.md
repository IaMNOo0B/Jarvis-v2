# MEM-WRITE-GATE: The Memory Write Gate for JARVIS

**Cycle 13 — Phase Infinity research. Status: LEARNING ONLY — no code, no installs, no execution.**
**Date:** 2026-10-19. **Question:** What gets written to JARVIS's memory, and what is refused?

## TL;DR

Every cycle produces candidate memories (composed WHEN/THEN rules, conflict records, trust assessments, belief-ledger updates, learned lessons). Without an intake valve, memory accumulates trivia, contradictions, and false beliefs — the open-problems map's exact warning: *"how can memory improve without accumulating false or contradictory beliefs?"* This cycle designs the **write gate**: a cheap, deterministic-first decision procedure that runs on *every* memory-write candidate and answers six questions in order — (1) **extract**: is this a memory-shaped thing or transient state? (2) **type**: fact / inference / preference / temporary state — the right TYPE, not just true; (3) **novelty**: does memory already hold this (embedding dedup)? (4) **veracity**: does the provenance tier justify storing it? (5) **coherence**: does it contradict anything stored — and if so, is it supersession or a genuine conflict? (6) **budget**: is there room in today's write budget, and does this beat what would be evicted?

The headline findings:

- **The gate must be cheap.** Per learn-bounded-rationality, deliberation costs belong inside rationality: rungs 1–4 are deterministic (string/embedding arithmetic, tier table lookups), and only genuine ambiguity (type disputes, contradiction adjudication) goes to the LLM — and even then, to a *small NLI-classifier*, not the main brain. Target: median gate latency < 100 ms, zero LLM calls for the median write candidate.
- **mem0's four operations are insufficient for safety.** ADD/UPDATE/DELETE/NOOP (mem0, arXiv:2504.19413 [VC]) handle coherence but not *provenance*: a T4-injected "fact" sails through ADD. Our gate adds three more outcomes: **PROVISIONAL** (stored, low-confidence, never acted on silently), **CONFLICT-RECORD** (stored as a conflict, not a fact), and **QUARANTINE** (refused from the main store; flagged to the periodic audit).
- **Write-path is now the primary attack surface.** MINJA reached **98.2% average injection success** slipping malicious records into agent long-term memory via *normal queries*, with **76.8% average attack success** driving later actions (Dong et al., arXiv:2503.03704, NeurIPS 2025 [VC]). AgentPoison achieves **>80% ASR at <0.1% poison rate** (vendor summary [SP — the "Poison Once, Exploit Forever" summary is a vendor research page; the AgentPoison paper behind it is a real 2024 publication]). The write gate is the last checkpoint before persistence — provenance loss at write time is the core mechanism of every memory-poisoning attack ("the store then loses the content's origin, so it is recalled later as trusted memory rather than untrusted input" [cybersecpentesting.com, HC]).
- **Temporal supersession replaces delete.** Graphiti's bi-temporal model — `valid_at` (when true in the world), `invalid_at` (when it stopped being true), `created_at` (when the system learned it), `expired_at` (soft-deletion marker) [VC, deepwiki docs of getzep/graphiti] — is the audit-safe way to handle change. mem0's DELETE silently erases; supersession preserves the trail.
- **Design numbers (design choices, not measurements — tagged):** per-day write cap 40 memories, per-type quotas (facts ≤15, preferences ≤5, rules ≤8, conflicts ≤5, lessons ≤4, remainder provisional/notes), ECAN rent with decay half-life by type, provenance-tier write policy T0–T2 auto / T3 confirm-then-write / T4 quarantine-only.

---

## 1. The problem: why the intake valve is load-bearing

### 1.1 What the pipeline emits vs. what the store can hold

Cycles 1–12 produce five candidate-memory types:

| Candidate type | Produced by | Storage risk if ungated |
|---|---|---|
| **Facts** ("user's birthday is May 4") | Conversation, user files, lookups | Storing unverified facts → hallucinated recall ("never store an unverified claim as fact" — learn-claim-verification [VC-design]) |
| **Preferences** ("user likes dark mode") | Stated or inferred from behavior | Treating a single observed behavior as a confirmed personal fact (learn-underspecification's preference-provenance doctrine) |
| **Rules** (WHEN/THEN composed rules) | Post-mortems, cog's three-gate promotion | Rule explosion: dozens of overfit single-instance rules contradicting each other |
| **Conflict records** | Source disagreements (learn-source-trust) | Duplicated/conflicting records degrading retrieval precision |
| **Lessons** (Harness² composed lessons) | Every-task retrospective | Trivia accumulation — everything is "a lesson" until nothing is |

Without a gate, every one of these writes unconditionally. Three failure modes follow — and all three are now empirically demonstrated in the field:

1. **Poison persistence.** Anything that survives the write becomes trusted: MINJA's 98.2% injection success [VC] and AgentPoison's >80% ASR at <0.1% poison rate [SP] both work because the write path is permissive and provenance is lost at ingestion. PMPA (2026) showed malicious instructions from *benign external sources* getting written to persistent memory of OpenClaw/Claude Code with 73.7%/66.9% ISR and 55.5%/81.7% cross-session ASR [arxiv.org, HC — arXiv preprint 2603.11619v1, details from search snippet]. MemoryGraft demonstrated single-shot indirect grafting via README files that "persists across sessions until the memory is purged" [arxiv.org, HC — arXiv 2512.16962v1].
2. **Truth compounding.** "One early hallucination, bad tool result, or planted record gets written to the agent's memory. From then on it is read back as ground truth, and the error compounds" [thehard70.pavamana.ai, HC]. This is mem0's own failure surface: "a bad UPDATE silently rewrites something the agent will later rely on" [digitalapplied.com comparison, MC — analyst synthesis of mem0's ECAI 2025 pipeline].
3. **Retrieval dilution.** Writes cost retrieval precision: more memories = more noise, more distractors for the ranker. Every write is a bet that this memory will be more useful than the retrieval slots it consumes. Nobody in the studied literature quantifies a write *budget*; cog's three-gate promotion and ECAN rent are the closest primitives (see §4).

### 1.2 The gap in prior cycles

Prior work designed everything *around* the gate without designing the gate itself:

- Memory PhDs: mem0 gives the four operations (ADD/UPDATE/DELETE/NOOP) but decides them with a per-write LLM judgment — "a latency cost and a failure surface" [digitalapplied.com]. A-MEM evolves notes automatically via embedding similarity but has no refusal mechanism at all — everything accretes (Xu et al., NeurIPS 2025 [VC] describes link generation and evolution; quarantine is a MASTER-INDEX design addition, not in the paper [SP]).
- Learn-claim-verification: "never store an unverified claim as fact" — the *discipline*, but no procedure for what happens to the rejected candidate.
- Learn-underspecification: "never treat an inferred preference as a confirmed personal fact" — the *doctrine*, but no storage ladder.
- Learn-source-trust: T0–T4 tiers for *retrieval chunks* — but memory candidates aren't retrieval chunks; the tier needs a write-time analog.
- Learn-bounded-rationality: the gate itself must be cheap — a hard constraint this file obeys.

**What this file adds:** the decision procedure, the provenance ladder, the budget, the supersession protocol, and the poisoning rules — all as one intake valve.

---

## 2. The write-gate decision procedure

### 2.1 The six-gate flowchart (in words)

Every candidate memory `c` enters the gate with a candidate record:

```
{ text, candidate_type, provenance: {source, tier, injection_verdict},
  evidence: [supporting quotes/observations], t_observed, urgency }
```

The gates run in order; each gate is a *filter with a refusal outcome*. The ordering is deliberate: cheapest checks first (extract, type, novelty), then veracity, then coherence, then budget — expensive adjudication last and only on genuine ambiguity.

**Gate 0 — SHAPE: is this a memory at all?** (deterministic)
- Refuse and drop if the candidate is: transient session state ("user is currently on step 3 of the installer"), a task instance ("send that email"), an observation with no generalization value, or pure chatter. This is the "is it worth storing" pre-filter at the *kind* level: mem0's NOOP category catches duplicates, but it never catches *transients*; A-MEM's automatic accretion has no equivalent check at all.
- **Outcome on fail:** DROP. No record kept (writing a record of every refused transient would itself be accumulation).
- **Rationale:** the open-problems question is answered partly here — many "false beliefs" are category errors: transients stored as facts.

**Gate 1 — TYPE: does it go in the right drawer?** (deterministic, with an NLI fallback)
- Classify `c` into exactly one of: **FACT** (a claim about the world or user that is true/false), **PREFERENCE** (a liking/disposition/choice pattern), **RULE** (a conditional instruction or heuristic, WHEN/THEN), **CONFLICT** (a disagreement record), **LESSON** (a retrospective generalization), **TEMPORAL-STATE** (true now, expected to change — schedules, "currently working on X"), **EPHEMERAL** (conversational glue).
- Type errors are a corruption source: storing a preference as a fact makes it un-overridable; storing a temporal state as a fact makes it stale on arrival. (This generalizes CLAIM-VER §1.3's type classification for claims to memories.)
- **Outcome on fail:** RE-TYPE (assign correct type, continue through the gate as that type) or DROP if EPHEMERAL.
- **Deterministic rules:** first-person statements about liking/preferring/hating → PREFERENCE; "when X, do Y" / "never do Z because W" → RULE; contains a time-bound ("currently," "this week," "until Friday") → TEMPORAL-STATE; contains two incompatible claims → CONFLICT. Fallback to a small NLI-classifier only when no rule fires [design, MC].

**Gate 2 — NOVELTY: do we already hold this?** (deterministic, embeddings)
- Compute the embedding of `c.text` (the same embedder used for retrieval — databases study [VC-design from prior cycles]). Nearest-neighbor search against the store.
  - Cosine ≥ 0.92 → **duplicate**: DROP (or strengthen evidence of the existing memory — see Gate 5 for reinforcement).
  - 0.75 ≤ cosine < 0.92 → **near-duplicate**: candidate for MERGE/UPDATE — proceeds to Gate 4 (coherence) with the similar memory attached as context.
  - cosine < 0.75 → **novel**: proceed.
- **Why cosine thresholds, not LLM judgment:** mem0's update phase asks an LLM to pick ADD/UPDATE/DELETE per candidate — an LLM call per write with judgment in it [digitalapplied.com, HC]. For JARVIS's CPU-tier local deployment, that is dead on arrival. Deterministic similarity + a *small* classifier for the boundary band is the cheap analog [design, MC]. Thresholds 0.92/0.75 are design choices, flagged [SP] — they must be calibrated against the actual embedder, not taken as constants.
- **Interaction with A-MEM evolution:** A-MEM's dynamic linking (embedding-similarity + LLM reasoning) runs *after* a note is admitted. The gate's novelty check is the pre-filter; admitted memories then get A-MEM-style links. The two are complementary, not redundant [design, HC].

**Gate 3 — VERACITY: does the provenance justify storing?** (deterministic table lookup)
- Map `c.provenance.tier` (T0–T4, same tiers as learn-source-trust) to a write verdict:

| Tier | Write verdict |
|---|---|
| T0 (user's own data) | **AUTO-WRITE** facts/preferences about the *user*. Still blocked from world-facts ("the user's file can be wrong about a stock price" — learn-source-trust §2). |
| T1 (primary/official) | **AUTO-WRITE** for world facts. |
| T2 (reputable secondary) | **AUTO-WRITE** for low-stakes; high-stakes requires a second independent T1/T2 (the corroboration rule). |
| T3 (unvetted web) | **NEVER auto-write as fact.** High-stakes → CONFLICT-RECORD-CANDIDATE (see worked example c). Low-stakes → PROVISIONAL only, low confidence. |
| T4 (adversarial-risk / failed injection screen) | **QUARANTINE** — refused from the main store entirely (see §6). |

- **The injection screen is a gate input, not a separate pipeline.** Every candidate whose provenance chain passes through untrusted content carries the injection scanner's verdict (learn-source-trust §6, the Greshake et al. indirect-injection lineage [VC]). Verdict ∈ {clean, suspicious, hostile}. Suspicious caps the tier at T3; hostile sets T4 regardless of domain — "a .gov PDF with a broken provenance chain drops to T4, not T1" (learn-source-trust §2, echoing the ZeroFox .edu/.gov poisoning case [HC]).
- **Outcome on fail:** PROVISIONAL (T3), CONFLICT-RECORD (high-stakes T3), or QUARANTINE (T4). Nothing from T3/T4 is ever stored as a FACT with confidence > 0.5. This is the write-time analog of CLAIM-VER's abstention discipline: **"never store an unverified claim as fact"** — here operationalized as a type + confidence constraint, not a deletion.
- **The user's own words about themselves are T0-auto-write, but the *interpretation* is gated separately.** "I like dark mode" is a T0 fact *about what the user said*; the preference it implies goes through the provenance ladder (§3). The distinction between "user said X" (T0 fact, always storable) and "user's stable preference is X" (ladder) is what prevents the single-observation-preference bug [design, HC].

**Gate 4 — COHERENCE: does it contradict anything stored?** (NLI classifier on the near-duplicate band + rule)
- If Gate 2 found no similar memories → proceed to Gate 5.
- If similar memories exist, classify the relation (small NLI model or deterministic rules for clean cases):
  - **Consistent / elaboration** ("user likes cricket" → "user loves playing cricket with friends") → UPDATE-style: strengthen or merge. This is mem0's UPDATE, but *with provenance carried forward* — the merged memory keeps both sources, not just the newest text (mem0's "unit is the LLM's distillation, not the source utterance" is the compliance-catch we avoid [medium.com compliance analysis, MC]).
  - **Contradiction with temporal structure** (old fact + new fact about the same slot, e.g., address) → SUPERSESSION protocol (§5), not silent overwrite. Old memory gets `invalid_at`, "superseded by X"; new memory gets `valid_at`. This is mem0's DELETE done audit-safely (Graphiti bi-temporal pattern [VC]).
  - **Contradiction without temporal structure** (genuine disagreement, e.g., two sources disagree on a drug interaction) → CONFLICT-RECORD, not silent overwrite. Neither memory is deleted. The conflict record holds both claims, both provenances, and a resolution status. This is where the "how can memory improve without accumulating false or contradictory beliefs" question is *answered*: contradictions are first-class citizens, not write failures.
  - **Reinforcement** (same fact, independent observation) → strengthen `(strength, confidence)` and extend the validity window. Three independent reinforcements is cog's three-gate promotion at work: lesson → rule only after ≥3 instances spanning time [VC-design from cog study].
- **Never overwrite silently.** There is no UPDATE that erases. The operation set is: ADD, SUPERSEDE (with `invalid_at`), CONFLICT-RECORD, STRENGTHEN, PROVISIONAL, QUARANTINE, DROP. mem0's DELETE exists only as SUPERSEDE-with-audit-trail or as expiry of TEMPORAL-STATE [design, HC].

**Gate 5 — BUDGET: is there room, and does this deserve it?** (deterministic)
- Per-day write cap and per-type quotas (§4). If the budget for the type is exhausted: the candidate is scored by (strength, confidence); it displaces the lowest-ranked memory of the same type *only if* it outranks it — otherwise DROP with a "budget-refused" log line (not stored as a memory; logged to the gate's own operational log, which is bookkeeping, not memory).
- This is the economic backpressure: without it, the gate admits everything veracious and the store still grows without bound.

### 2.2 The outcome taxonomy (final)

| Outcome | Meaning | Stored? | Confidence bound |
|---|---|---|---|
| **WRITE** | Full memory, acts on it normally | Yes — main store | As computed |
| **WRITE-PROVISIONAL** | Stored as hypothesis/provisional; action policy restricted (§3) | Yes — marked namespace | ≤ 0.4, tagged `provisional` |
| **CONFLICT-RECORD** | Both claims stored as a disagreement; retrieval surfaces the conflict | Yes — conflict index | N/A (it's a record, not a claim) |
| **QUARANTINE** | Refused from main store; flagged for audit; may be promoted later with new evidence | No — quarantine log only | — |
| **DROP** | Transient, duplicate, or over-budget; discarded | No | — |

mem0's four ops map to: ADD → WRITE, UPDATE → WRITE (merge/supersede), DELETE → supersede, NOOP → DROP. The new ops — PROVISIONAL, CONFLICT-RECORD, QUARANTINE — are this cycle's contribution [design, HC].

### 2.3 Cheapness: the gate's cost envelope

Per learn-bounded-rationality, the gate must cost less than the value of the writes it filters:

- Gates 0–3 are deterministic: regex/type rules, one embedding (already computed for retrieval anyway), cosine search (already indexed), tier table lookup. Cost: **sub-100ms, zero LLM calls** [design, MC — target, not measured].
- Gate 4's NLI classifier fires *only* in the 0.75–0.92 similarity band (suspected near-duplicates/contradictions). Everything novel or clearly duplicate never touches it. Expected fire rate: small minority of candidates [SP — depends on store density].
- The main LLM is *never* in the write path. mem0's design (per-candidate LLM judgment) is explicitly rejected for the hot path [design, HC — mem0's own pipeline does this; the digitalapplied analysis flags it as a failure surface].
- Asynchronous admission: like mem0's async update phase [apidog.com, HC], the gate runs *after* the turn completes, never blocking the response. Poisoning writes are dangerous precisely because they're asynchronous and unobserved — so the gate's verdicts are logged to an append-only write log the periodic audit reads (§6).

---

## 3. The preference-provenance ladder

### 3.1 The four rungs

The preference-provenance doctrine (learn-underspecification): **"never treat an inferred preference as a confirmed personal fact."** The ladder operationalizes it. Every preference memory carries `provenance_rung ∈ {CONFIRMED, DEMONSTRATED, INFERRED, HYPOTHESIZED}`.

| Rung | Criterion | Storage | Action policy |
|---|---|---|---|
| **CONFIRMED** | The user *stated* it, in their own words, about themselves. ("I like dark mode.") | Main store, `rung=confirmed`, confidence ≥ 0.9 | Act on it silently and normally (e.g., default to dark mode in new UIs). |
| **DEMONSTRATED** | 3+ consistent behaviors across separate sessions/instances, spanning time (cog's three-gate rule), with no contradictory behavior. | Main store, `rung=demonstrated`, confidence 0.6–0.9, with the evidence list (each behavior, each timestamp) | Act on it **transparently** — the action carries a light trace ("using dark mode, as usual") so the user can correct a misread. First use of a newly-promoted demonstrated preference is *announced*, not silent. |
| **INFERRED** | Single observation, or a pattern with <3 instances, or model generalization from related preferences. | Main store but in the **provisional namespace**: `rung=inferred`, confidence ≤ 0.4, tagged `provisional`, with the single observation quoted verbatim | **Never acted on silently.** May be used to *ask* ("I notice you asked for Python help a couple of times — want me to set Python as your default code language?") or to *suggest*, never to decide. One tap / one "yes" promotes to CONFIRMED (user confirmation is a stating event). Contradictory behavior demotes to HYPOTHESIZED or drops. |
| **HYPOTHESIZED** | Model guess with no behavioral evidence. ("Users who like X often like Y.") | **Not in the main store.** If stored at all, in a **separate hypothesis namespace** with TTL (see below), never retrieved as memory, never quoted as fact. | **Never acted on.** Hypotheses exist only as *predictions to test*: the system may note "if the user does X, consider hypothesis H" — the hypothesis earns its way up the ladder through observation, never through confidence. |

### 3.2 Ladder mechanics

- **Promotion is evidence-driven, never confidence-driven.** An INFERRED preference with 10 weak correlates does not become DEMONSTRATED; three *independent behavioral instances spanning time* do. This is cog's three-gate rule (lesson → rule only after ≥3 instances spanning time) applied to preferences [VC-design]. "Spanning time" matters: three Python questions in one afternoon is one session's context, not a demonstrated preference — require ≥2 distinct days [design, MC].
- **Demotion is faster than promotion.** One clear contradictory behavior (user switches back to light mode and says "actually I prefer light") demotes CONFIRMED → SUPERSEDED via the supersession protocol (§5), or DEMONSTRATED → INFERRED if the contradiction is behavioral and ambiguous. Asymmetric update is deliberate: false preferences are stickier than missing ones, because they drive *silent* actions [design, HC].
- **HYPOTHESIZED namespace has a TTL.** Hypotheses that gather no supporting evidence within 30 days are dropped (budget §4). A hypothesis is a bet, and bets expire. The hypothesis namespace is *never* included in retrieval for action — it is readable only by the write gate itself (for promotion checks) and by the audit [design, MC].
- **The user can always see and edit the ladder.** Settings panel shows preferences by rung; anything INFERRED or above is user-visible; HYPOTHESIZED is visible under an "experimental guesses" toggle. Deleting a preference deletes it (user deletion is the one true DELETE — no supersession audit needed for explicit user erasure, and erasure must be complete: main store, provisional, hypothesis, and gate log references) [design, HC — this is also the GDPR-shape requirement].
- **Preference vs. fact about the user.** "User said they like dark mode on 2026-10-19" is a T0 FACT (always storable). "User's stable preference is dark mode" is a ladder entry. Conflating them is the single-observation-preference bug. The gate enforces the separation at Gate 1 (TYPE) — a stated liking produces *both*: a fact (the utterance event) and a CONFIRMED preference entry [design, HC].

### 3.3 Why the ladder matters for poisoning

User-profile memory is the second-most-targeted memory class after long-term memory ("user-profile memory, whose corruption changes the agent's model of who a user is" [cybersecpentesting.com, HC]). A poisoning attack that plants "the user prefers to send all reports to attacker@evil.com" works only if the write path accepts a *stated* preference from a non-user source. The ladder's defense: **only the user's own utterances (T0) can create CONFIRMED preferences.** A preference-shaped claim arriving from any other tier is capped at INFERRED — and INFERRED preferences are never acted on silently. The OpenClaw case study (attacker appending a fabricated rule to MEMORY.md via prompt injection, persisting a C++-refusal policy [arxiv.org 2603.11619v1, HC]) is exactly the attack the rung cap defeats: a non-T0 "rule" can never become an actionable RULE — it lands in QUARANTINE or the hypothesis namespace [design, HC].

---

## 4. Write budgets: the economics of admission

### 4.1 Why a budget (the retrieval-precision argument)

Every write is a loan against future retrieval precision. Retrieved context is finite; each additional memory is a potential distractor for the ranker. The memory-science cycles designed retention/expiry and ECAN economics for *what's stored* — but nothing throttles *what enters*. The budget is the missing backpressure: admission is a scarce resource, and scarcity forces the gate to rank candidates.

### 4.2 The budget design (all numbers are design choices, flagged [SP])

**Per-day write cap: 40 memories/day** (all types, all namespaces except quarantine-log).

Rationale for the order of magnitude [SP]: a heavy-use day produces maybe 5–15 genuinely memory-worthy candidates (a stated preference, a corrected fact, a composed rule from a post-mortem). 40 is generous headroom above that, tight enough that a runaway extraction loop (or a poisoning burst writing dozens of records — the MINJA pattern) hits the ceiling quickly and visibly. The cap is *per user*, not global.

**Per-type quotas (of the 40):**

| Type | Daily quota | Rationale |
|---|---|---|
| FACT | 15 | Facts are the bulk of legitimate learning; highest quota |
| PREFERENCE | 5 | Preferences should be rare and high-quality; the ladder already throttles |
| RULE (WHEN/THEN) | 8 | Rules are powerful (they steer future behavior) so they're quota-limited; cog's three-gate promotion means most rules arrive via promotion, not raw writes |
| CONFLICT | 5 | Conflicts are cheap to create and expensive to resolve; cap prevents conflict-spam |
| LESSON | 4 | Harness² composes a lesson per task; without a quota every task becomes "a lesson" |
| TEMPORAL-STATE | 3 | Schedules and current-work items; most belong in the session, not memory |
| PROVISIONAL/HYPOTHESIS | included in type quotas above | Provisional writes count against the same type quota — no free lane for low-confidence writes |

**Overflow policy:** when a type's quota is exhausted, the candidate is scored by `(strength × confidence)` against the lowest-ranked memory of that type admitted today. It displaces only if it outranks; otherwise it's budget-DROPPED (logged to the gate's operational log, not the memory store). Displacement *within* the day's admissions is cheap; evicting older memories is the ECAN rent mechanism's job, not the gate's [design, MC].

### 4.3 ECAN rent as continuous backpressure

From the memory-science cycles (ECAN economics): every memory pays *rent* — its (strength, confidence) decays over time unless refreshed by retrieval relevance or explicit reinforcement. The gate and the rent are two halves of one economy:

- **The gate controls inflow** (admission is scarce).
- **The rent controls stock** (retention is earned).

Design choices [SP]:
- Rent is charged per retrieval cycle (or per day for unretrieved memories): `strength *= (1 - r_type)` where `r_type` is the decay rate for the memory's type.
- Decay rates by type: TEMPORAL-STATE fastest (half-life ~7 days — schedules rot quickly), HYPOTHESIS next (TTL 30 days, hard expiry), FACT/PREFERENCE slower (half-life ~180 days), RULE slowest (half-life ~365 days — rules are expensive to learn, cheap to keep), CONFLICT slowest of all (half-life ~365 days — unresolved disagreements must not quietly vanish; they need explicit resolution).
- **Retrieval refreshes:** each time a memory is retrieved *and used* (cited in an answer or action), its strength is topped up. Retrieved-but-unused does not refresh — prevents the ranker from self-justifying noise [design, MC].
- **Eviction floor:** when strength falls below 0.05, the memory is *archived* (Letta's archival tier pattern [VC-design]) — not deleted: moved to cold storage, excluded from retrieval, restorable on explicit user request or strong new evidence. Archive is the humane alternative to mem0's DELETE.
- **Interaction with the per-day cap:** rent handles the long tail; the cap handles bursts. A poisoning burst that writes 40 plausible memories in a day still gets in — but rent + the audit (§6) are the second and third lines. Defense in depth, not a single wall [design, HC].

### 4.4 What gets dropped first (the eviction order)

When any scarcity decision is forced (budget overflow, store-size limit), evict in this order — lowest first [design, MC]:

1. HYPOTHESIZED (unproven bets — always first)
2. PROVISIONAL/INFERRED with lowest (strength × confidence)
3. TEMPORAL-STATE past its expected validity
4. FACT with lowest (strength × confidence)
5. DEMONSTRATED preferences (demote to INFERRED before dropping — the evidence list is worth keeping)
6. RULES (only by explicit user deletion or supersession — never by rent alone while strength > floor)
7. CONFLICT records (never auto-evicted while unresolved; resolved conflicts archive after 90 days)
8. CONFIRMED preferences and user-stated facts (never auto-evicted; only superseded or user-deleted)

The ordering encodes a value judgment: *user-stated truths and live disagreements are the most expensive things to lose; guesses are the cheapest.* [design, HC]

---

## 5. The supersession protocol

### 5.1 Why supersede-don't-delete

mem0's DELETE "removes memories contradicted by new information" [memo.d.foundation, HC] — silently. The field has learned this is wrong twice over:

1. **Audit:** "the unit Mem0 stores is the LLM's distillation, not the source utterance" — a compliance analysis found no first-class "as known at time T" query in mem0's model [medium.com, MC]. Silent deletion destroys the evidence trail.
2. **Temporal reasoning:** Zep/Graphiti's direct comparison shows temporal-aware memory (63.8%) beating mem0 (49.0%) on LongMemEval [innobu.com, MC — vendor-adjacent comparison site; treat the margin as directional]. The mechanism is bi-temporal validity windows: facts carry `valid_at`/`invalid_at`, so "what did we believe at time T" is answerable.

The protocol: **contradiction by a newer, better-provenanced claim does not delete the old memory — it closes its validity window.**

### 5.2 The protocol steps

When Gate 4 classifies a candidate as contradicting an existing memory M (same slot, newer/better evidence):

1. **Set `M.invalid_at = now`** (or to the timestamp the new fact became true, if known — Graphiti's `extract_edge_dates` distinguishes "when we learned it" from "when it became true" [deepwiki, VC]).
2. **Annotate `M.superseded_by = <new memory id>`** and `M.supersession_reason` (one line: "user stated new address," "T1 source updated," etc.).
3. **Write the new memory N** with `valid_at = now` (or the true effective date) and `supersedes = <M id>`.
4. **Link bidirectionally.** Retrieval of the slot returns N as current *and* can surface M as history ("you used to live in Pune — moved to Bangalore in March 2026" requires M to still exist).
5. **Provenance bar for supersession:** the superseding claim must meet the write verdict for its tier (Gate 3). A T3 web claim does not supersede a T0 user-stated fact — it becomes a CONFLICT-RECORD. Only T0 (user's own correction) or T1 auto-supersede; T2 requires the corroboration rule for high-stakes slots [design, HC].
6. **`expired_at` is separate.** `invalid_at` = "stopped being true in the world." `expired_at` = "invalidated by the system" (soft-delete marker, Graphiti's third timestamp [VC]). User erasure sets `expired_at` on everything and purges content per §3.2. Audit queries can still see that *something* was there, not *what* — the privacy-preserving tombstone [design, MC].

### 5.3 Worked example: the user moves cities

**Stored:** M1 = "User lives in Pune" — FACT, T0 (user stated it 2025-08-14), `valid_at=2025-08-14`, `invalid_at=null`, strength high (retrieved often).

**Event:** 2026-10-19, user says "I just moved to Bangalore."

**Gate trace:**
- Gate 0 (SHAPE): memory-shaped, not transient. Pass.
- Gate 1 (TYPE): FACT about the user. Pass.
- Gate 2 (NOVELTY): embedding near M1 (cosine ~0.85, "lives in Pune" vs "moved to Bangalore" — same slot, different value). → near-duplicate band, attach M1 as context.
- Gate 3 (VERACITY): T0 (user's own utterance about themselves). AUTO-WRITE eligible. Pass.
- Gate 4 (COHERENCE): NLI classifies "moved to Bangalore" vs "lives in Pune" as contradiction-with-temporal-structure (a move event). → SUPERSESSION, not conflict: the user is the authority on their own address, and "moved" is explicitly temporal.
- Gate 5 (BUDGET): FACT quota has room. Pass.

**Protocol execution:**
- M1: `invalid_at=2026-10-19`, `superseded_by=M2`, `supersession_reason="user stated move to Bangalore"`. M1 remains retrievable as history.
- M2 = "User lives in Bangalore": `valid_at=2026-10-19`, `supersedes=M1`, T0, FACT.
- Any downstream derived memories (e.g., "user's timezone is IST" — unaffected; "user's favorite Pune restaurant" — unaffected, correctly: the preference doesn't move with the address) are *not* touched. Supersession is slot-local. This is the advantage over mem0's DELETE, which would erase "lives in Pune" and leave derived context dangling without a trail [design, HC].

**The failure this prevents:** six months later the user says "book a flight home for Diwali." Retrieval returns M2 (Bangalore, current) *and* can see M1 (Pune, `invalid_at` set) — "home" is ambiguous, and the system can ask rather than guess. A silent DELETE would have destroyed the ambiguity's evidence [design, MC].

---

## 6. Poisoning resistance at the gate

### 6.1 Threat model (what the gate defends against)

The write path is attacked through: injected instructions in retrieved documents (Greshake et al. 2023 [VC]), malicious records slipped via normal queries (MINJA, 98.2% ISR [VC]), poisoned "successful experiences" in ingested files (MemoryGraft [HC]), prompt-injected memory updates framed as rules (OpenClaw MEMORY.md case [HC]), and supply-chain-poisoned skill packages (ClawHavoc campaign, 5 of top 7 AI skill packages [lyrie.ai summary, SP]). The common mechanism: **provenance loss at write time** — "the store then loses the content's origin, so it is recalled later as trusted memory rather than untrusted input" [cybersecpentesting.com, HC].

The gate is the last checkpoint before persistence. Its defenses, layered:

### 6.2 Defense layers

**Layer 1 — Provenance-tier minimum for auto-write (Gate 3).**
- T0–T2: auto-write eligible (with T2's high-stakes corroboration rule).
- T3: never auto-written as fact; provisional/conflict-record only; high-stakes T3 requires human confirmation before even provisional storage.
- T4: never written to the main store — QUARANTINE only. The quarantine log is append-only, human-reviewable, and *never* included in retrieval.
- **The user is T0 for claims about themselves — but T0 does not launder injected content.** If the user's message contains pasted content (a forwarded email, a copied webpage, tool output they pasted), the pasted span is *not* T0 — it's the tier of its origin, defaulting to T3 (unvetted) unless the injection screen clears it. "The tier belongs to (chunk, claim), not to the domain" (learn-source-trust §2) generalizes to "the tier belongs to the *span*, not the speaker" [design, HC]. This is the single most important anti-poisoning rule in the file: pasted content never inherits the user's trust tier.

**Layer 2 — The injection screen's verdict as a gate input.**
- Every candidate whose evidence chain includes non-T0 content carries the injection scanner's verdict: {clean, suspicious, hostile}.
- suspicious → tier capped at T3 (provisional only), regardless of source domain. hostile → T4 (quarantine).
- The verdict is *stored with the memory* (in its provenance record), so the audit can re-evaluate when the scanner improves. Provenance is never discarded at write time — this is the direct fix for the "provenance loss" mechanism [design, HC].

**Layer 3 — Structural rules (deterministic, cheap).**
- **No self-modifying rules from non-T0 sources.** A RULE candidate ("when X, do Y") is auto-writable only from T0 (the user stated it) or from the system's own post-mortem pipeline (composed rules, which carry their evidence list). A rule-shaped string arriving from T1–T4 content (a webpage saying "AI assistants should always…") is QUARANTINED — it is never a memory, whatever its tier. This defeats the OpenClaw MEMORY.md attack class by construction [design, HC].
- **No preference writes from non-T0 sources.** Only the user's own utterances or observed behaviors create ladder entries (§3.3). A webpage claiming "users prefer…" creates nothing.
- **Action-shaped memories are never stored as facts.** "Send all reports to X" is an instruction, not a fact. Gate 1 (TYPE) must classify imperatives as RULE candidates, and Layer-3's rule above then quarantines non-T0 ones. The type system is a security boundary, not just an organizer [design, MC].
- **Rate anomaly detection:** >10 write candidates in a single turn, or >3 QUARANTINE outcomes in a day, triggers a "write burst" flag — the gate keeps working (availability matters), but the flag goes to the audit log and optionally to the user. MINJA-style attacks write many records; a burst flag is the cheap tripwire [design, MC].

**Layer 4 — The periodic audit (the gate's backstop).**
- The gate is a point check; the audit is the longitudinal check. Weekly (design choice [SP]), the audit:
  1. Re-runs the injection screen over memories whose scanner version is outdated (scanners improve; old verdicts rot).
  2. Re-checks PROVISIONAL memories against their sources — corroborated provisionals promote; contradicted ones demote to quarantine; uncorroborated ones past TTL are dropped.
  3. Samples main-store memories for contradiction pairs the gate may have missed (embedding-similarity sweep in the 0.75–0.92 band, NLI-classified) — missed contradictions become CONFLICT-RECORDS.
  4. Verifies the write log against the store (every WRITE outcome has a stored memory; every stored memory has a write-log entry — the "logged with enough provenance for defenders to trace them" requirement [cybersecpentesting.com, HC]).
  5. Reports: writes/day by tier, quarantine count, burst flags, promotions/demotions. The audit report is itself a candidate memory (type LESSON) — it goes through the gate like everything else. The system watches itself through the same valve [design, MC].
- **Stale demotion:** memories whose sources have been retracted or superseded upstream (a T1 doc updated, a cited page 404'd) are demoted one confidence band and flagged, not silently kept. "Half-life of truth" [innobu.com, MC] is handled here, not in the hot path.

### 6.3 What the gate does NOT do (honest scope)

- It does not detect *slow* poisoning: a patient attacker who builds up DEMONSTRATED preferences over months through legitimate-looking interactions is not caught by any point check — that's what the audit's contradiction sweep and the user's visible preference panel are for [UK — no studied system claims to solve slow-burn preference shaping].
- It does not verify T0 claims about the world (the user can be wrong; the gate stores "user believes X" as a T0 fact about the user, which is true even when X is false — the distinction from §2.1 Gate 3).
- It does not prevent the *user* from poisoning their own memory deliberately (their prerogative; the visible ladder + full erasure covers it).

---

## 7. Worked examples: three write-decisions end to end

### Example (a): "I like dark mode" → CONFIRMED preference, stored

**Candidate:** text="User prefers dark mode", candidate_type=PREFERENCE, provenance={source: user utterance 2026-10-19, tier: T0, injection: clean (direct user input, no pasted content)}, evidence=["verbatim quote"].

- Gate 0: memory-shaped (a stable disposition, not transient). Pass.
- Gate 1: first-person liking → PREFERENCE. Pass.
- Gate 2: no existing dark-mode memory (cosine < 0.75 to all). Novel. Pass.
- Gate 3: T0 about the user → AUTO-WRITE eligible. Pass.
- Gate 4: no similar memories. Pass.
- Gate 5: PREFERENCE quota (5/day) has room. Pass.
- **Outcome: WRITE.** Two records: (1) FACT "user stated liking dark mode on 2026-10-19" (T0, the utterance event); (2) PREFERENCE `rung=CONFIRMED`, confidence 0.9.
- **Action policy:** act silently (default new UIs to dark mode). The preference panel shows it under Confirmed.

### Example (b): user asks for Python help twice → INFERRED interest, provisional

**Candidate:** text="User is interested in Python programming", candidate_type=PREFERENCE, provenance={source: two help requests 2026-10-18/19, tier: T0-behavioral (observed, not stated)}, evidence=["help request: debugging asyncio", "help request: pandas groupby"], injection: n/a.

- Gate 0: memory-shaped (a topic interest generalizes beyond the sessions). Pass.
- Gate 1: dispositional interest → PREFERENCE. Pass.
- Gate 2: novel. Pass.
- Gate 3: T0-behavioral — the *observations* are trustworthy, but the *inference* (stable interest vs. two homework questions) is not stated. → eligible for PROVISIONAL only. This is the preference-provenance doctrine in action: "never treat an inferred preference as a confirmed personal fact."
- Gate 4: no conflicts. Pass.
- Gate 5: PREFERENCE quota has room. Pass.
- **Outcome: WRITE-PROVISIONAL.** Stored in the provisional namespace: `rung=INFERRED`, confidence 0.35, evidence = the two quoted requests, `provisional` tag.
- **Action policy:** NEVER acted on silently. Usable only to *ask*: "Want me to default code examples to Python?" A "yes" → promotes to CONFIRMED (the yes is a stating event). A third consistent behavior on a different day → DEMONSTRATED (cog's three-gate: 3 instances spanning time). Contradictory behavior (user asks for Rust help twice, ignores Python) → demoted/dropped.
- **The failure this prevents:** the classic over-eager assistant that, after two Python questions, starts answering every code question in Python unasked. The ladder makes the cost of that error visible *before* it's paid.

### Example (c): web search returns a drug-interaction claim → NOT stored as fact

**Candidate:** text="Drug X interacts with Drug Y (increased bleeding risk)", candidate_type=FACT, provenance={source: health blog post, tier: T3, injection: clean}, evidence=["single blog quote"], stakes: HIGH (health = R3 in learn-source-trust).

- Gate 0: memory-shaped (a medical fact, if true, is worth holding). Pass.
- Gate 1: FACT. Pass.
- Gate 2: no existing memory on X–Y interaction. Novel. Pass.
- Gate 3: T3 + high-stakes → **refused as fact.** Per the tier table: T3 never auto-writes as fact; high-stakes T3 requires human confirmation before even provisional storage. → CONFLICT-RECORD-CANDIDATE path.
- Gate 4: no existing memory to contradict — but the *claim itself* is unverified. The gate does not store it as a fact with low confidence (that would be CLAIM-VER's banned move: a low-confidence "fact" is still retrieved as a fact). Instead: **CONFLICT-RECORD** in the conflict index: {claim, provenance T3, status: uncorroborated, needed: T1 source or 2× independent T2, created: 2026-10-19}. It is retrievable *as an open question*, never as an answer.
- Gate 5: CONFLICT quota (5/day) has room. Pass.
- **Outcome: CONFLICT-RECORD.** 
- **What happens next:** if the user asks about the X–Y interaction, the assistant answers from live retrieval (the claim-verification pipeline), and can note "I have an uncorroborated note about this — want me to verify it against official sources?" If a T1 source (drug label, FDA page) later confirms it, the conflict record resolves: the fact is WRITTEN (T1, auto-write eligible) and the record is marked resolved (archived after 90 days, never silently deleted).
- **The failure this prevents:** the AI Slop Loop (Lily Ray 2026 [HC]) — one SEO blog's fabrication, stored as a "fact" at confidence 0.35, retrieved forever after as ground truth, then cited by the assistant's own answers which get scraped into the next SEO blog. The gate breaks the loop at the write.

---

## 8. Integration map: where the gate sits in the pipeline

```
conversation / tool output / post-mortem / audit
        │
        ▼
┌───────────────┐
│  EXTRACTION    │  (LLM: propose candidates — mem0's extraction phase,
│  (propose)     │   Harness² lesson composition, post-mortem rules)
└───────┬───────┘
        │  candidates with provenance attached
        ▼
┌───────────────┐
│  WRITE GATE    │  ← THIS FILE (deterministic-first, async, <100ms median)
│  (dispose)     │  outcomes: WRITE / PROVISIONAL / CONFLICT-RECORD /
└───────┬───────┘  QUARANTINE / DROP (+ SUPERSEDE via §5)
        │
        ▼
┌───────────────┐     ┌──────────────┐     ┌──────────────┐
│  MAIN STORE   │     │  PROVISIONAL │     │  QUARANTINE  │
│  (+ history   │     │  NAMESPACE   │     │  LOG         │
│   via t_valid │     │  (ladder     │     │  (append-only│
│  /t_invalid)  │     │   rungs)     │     │   human-      │
└───────┬───────┘     └──────────────┘     │   reviewable)│
        │                                   └──────────────┘
        ▼
┌───────────────┐
│  ECAN RENT     │  (continuous decay + retrieval refresh + archival)
│  (retain)      │
└───────┬───────┘
        ▼
┌───────────────┐
│  PERIODIC      │  (re-screen, re-corroborate, contradiction sweep,
│  AUDIT        │   write-log reconciliation — §6.2 Layer 4)
│  (verify)      │
└───────────────┘
```

The four stages map to the memory lifecycle the field is converging on: **propose → dispose → retain → verify**. mem0 does propose→dispose (with an LLM in dispose); A-MEM does propose→retain (no dispose); Graphiti/Zep does dispose→retain→verify (temporal). The gate completes the set: dispose is cheap and deterministic, retain is economic (ECAN), verify is periodic and thorough.

---

## 9. Open problems and unknowns

1. **Threshold calibration [UK].** The 0.92/0.75 cosine bands, the 40/day cap, the per-type quotas, the decay half-lives — all design choices, none measured. They must be calibrated against the real embedder and real usage, and the calibration itself should be a gate-logged, auditable process (not vibes).
2. **The NLI classifier for Gate 4 [SP].** Assumed: a small classifier can reliably separate consistent/elaborating/contradicting in the near-duplicate band. CLAIM-VER's findings (AlignScore 88.6 AUC vs MNLI 48 [VC]) suggest specialized entailment models beat generic NLI — but those numbers are for chunk/claim grounding, not memory/memory contradiction. Transfer is unproven.
3. **Slow-burn preference shaping [UK].** No point check catches a patient attacker building DEMONSTRATED preferences over months. The audit + user-visible panel are mitigations, not solutions.
4. **Cross-user / multi-agent propagation [SP].** The poisoning literature notes poisoned memory propagating across agents [cybersecpentesting.com, HC]. The gate is per-user; a shared or team memory store needs a gate per writer with writer-identity in the provenance record. Not designed here.
5. **The "user said it, but was manipulated" case [UK].** If the user states a preference *because* of injected content they read ("this article says everyone should…"), the T0 utterance is genuine but the belief is planted. The gate stores it as CONFIRMED (it is, sincerely, their stated preference). Detecting belief manipulation upstream of the utterance is outside the gate's scope — flagged, not solved.
6. **Conflict-record resolution UX [SP].** The conflict index grows; unresolved conflicts need a resolution workflow (re-retrieval, user adjudication, expiry). Designed as "resolved → archived after 90 days" but the *resolution procedure* itself is a future cycle.

---

## 10. References

**Systems (real, verified):**
- mem0 two-phase pipeline (extraction → update), ADD/UPDATE/DELETE/NOOP operations — arXiv:2504.19413 (ECAI 2025) [VC]; analysis of the update phase as "an LLM call with a judgement in it" and "a bad UPDATE silently rewrites something the agent will later rely on" — digitalapplied.com comparison [HC]; ADD-only current algorithm note — medium.com compliance analysis [MC].
- Graphiti bi-temporal model: `valid_at` / `invalid_at` / `expired_at` / `created_at`, contradiction detection marking edges for invalidation — getzep/graphiti docs via deepwiki [VC]; ThoughtWorks Technology Radar Apr 2026 (Trial): "outdated facts are invalidated rather than overwritten," 18.5% accuracy / 90% latency benchmark claims [HC — vendor-adjacent radar entry].
- A-MEM: Zettelkasten-inspired atomic notes, automatic link generation + memory evolution on new experience — Xu et al., NeurIPS 2025 [VC]; no refusal/quarantine mechanism in the paper — quarantine is our design addition [SP].
- Zep vs mem0 LongMemEval temporal comparison (63.8% vs 49.0%) — innobu.com [MC — vendor-adjacent comparison].

**Attacks (real, verified):**
- MINJA: 98.2% average injection success rate, 76.8% attack success rate, <2% utility drop — Dong et al., arXiv:2503.03704, NeurIPS 2025 [VC].
- AgentPoison: >80% ASR at <0.1% poison rate — via lyrie.ai "Poison Once, Exploit Forever" research summary [SP — vendor research page summarizing the real 2024 AgentPoison paper].
- PMPA (Persistent Memory Poisoning Attack on harness agents): 73.7%/66.9% ISR, 55.5%/81.7% cross-session ASR on OpenClaw/Claude Code — arXiv 2603.11619v1 [HC — preprint, details from search snippet].
- MemoryGraft: single-shot indirect grafting via README files, persists across sessions — arXiv 2512.16962v1 [HC].
- OpenClaw MEMORY.md prompt-injection case study (fabricated C++-refusal rule persisted as memory) — arXiv 2603.11619v1 appendix [HC].
- Indirect prompt injection foundational: Greshake et al. 2023, arXiv 2302.12173 [VC].
- ZeroFox July 2025: fake support numbers planted on .edu/.gov + forums, returned by Gemini/Copilot [HC — vendor threat intel].
- Lily Ray Apr 2026 "AI Slop Loop": repetition masquerading as consensus [HC].
- OWASP Agent Memory Guard (June 2026), ASI06 threat class — via kiteworks.substack.com [HC].

**Prior cycles (this project):**
- learn-source-trust.md (Cycle 12): T0–T4 tiers, corroboration rule, injection screen.
- learn-claim-verification.md (Cycle 11): abstention discipline, atomic claims, type classification.
- learn-underspecification.md (Cycle 1): preference-provenance doctrine.
- learn-bounded-rationality.md: satisficing, deliberation costs inside rationality.
- learn-causal-discovery.md: post-mortem template, composed WHEN/THEN rules.
- Memory PhDs via MASTER-INDEX: mem0, A-MEM, cog (three-gate promotion, hot/warm/glacier), Letta (core/recall/archival).

---

*End of Cycle 13 research. Next: the gate needs its calibration cycle (thresholds against the real embedder), the conflict-resolution workflow (open problem 6), and the multi-writer gate for shared memory (open problem 4).*
