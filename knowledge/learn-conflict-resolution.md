# CONFLICT-RESOLUTION: The Conflict Resolution Workflow for JARVIS

**Cycle 14 — Phase Infinity research. Status: LEARNING ONLY — no code, no installs, no execution.**
**Date:** 2026-10-19. **Question:** How does JARVIS resolve conflicts between memories, sources, and beliefs?

## TL;DR

Cycles 12 and 13 built the intake side of disagreement: record it (SRC-TRUST §conflict-protocol), refuse silent overwrite (MEM-WRITE-GATE's CONFLICT-RECORD outcome). This cycle designs the **resolution workflow** — what happens to a conflict record afterward. The design rests on five findings:

1. **Five conflict types need five paths.** Source-vs-source (a), memory-vs-new-evidence (b), memory-vs-memory (c), user-vs-memory (d), and temporal (e) are not one problem with one rule; type (e) isn't a conflict at all, and type (d) has a different arbiter than types (a–c).
2. **Resolution is adjudication, not discovery.** The field's truth-discovery literature (TruthFinder, CRH, LTM — [HC]) shows the winning move is *iterative evidence weighing*, not a single judgment call. Our workflow borrows that structure and fixes its blind spots: truth discovery assumes all sources *try* to be truthful (ours may be adversarial — SRC-TRUST's hostile-supply-chain lesson stands).
3. **The loser must survive.** AGM belief-revision theory (Alchourrón, Gärdenfors, Makinson, 1985 [VC]) gives us the operation vocabulary: revision = contract-then-expand (the Levi identity), and entrenchment orders which beliefs get retracted. But AGM's postulates are idealizations; in a hostile, partial-information agent store, **every resolution is reversible** — the retracted belief becomes an audit record, never an erasure. A badly-resolved conflict must not destroy a true belief.
4. **"Both true" is the common case.** Many conflicts dissolve under temporal or contextual scoping instead of deletion — the KG literature's time-disjoint constraints (MDPI 2019 [MC]) and multi-truth discovery (MTD_VCI [HC]) both acknowledge that one claim can legitimately resolve to a *set*. Scoping is our default resolution before picking a winner.
5. **R3 never auto-resolves.** Same as Cycle 11's abstention discipline: high-stakes conflicts (health, finance, security) abstain-and-surface or escalate-to-user, no matter how decisive the evidence looks. The abstention bar doesn't move when the disagreement lives in memory instead of in retrieval.

**This closes the conflict lifecycle:** record (12) → gate (13) → resolve (14). Every outcome below carries a design tag: this is a design document, not a measurement report — headline numbers are design choices, tagged [DC].

---

## 1. The problem: a conflict index that grows forever

The write gate's CONFLICT-RECORD outcome is a valve, not a destination. Every genuine disagreement that enters memory becomes a **conflict record** — and without a resolution workflow, those records accumulate:

- **Retrieval contamination.** Both sides of an unresolved conflict sit in the store, mutually contradicting. The ranker can't tell which is "the belief," so answers flip between sessions depending on which side ranks higher — truth compounding in reverse.
- **The growth is unbounded.** The per-day write cap (40 memories, conflicts ≤5) bounds the *rate*, not the *stock*. The conflict index grows forever if resolution never shrinks it.
- **Silent re-entry.** Cycle 13's gate refused the silent overwrite, but the conflicting evidence keeps arriving. Each new arrival re-triggers the gate, produces another conflict record or dedups into the open one — work with no terminal state.

The design constraint from the task statement is sharp: *an unresolved conflict index grows forever; a badly-resolved one destroys true beliefs.* The workflow must therefore do two things at once: **shrink the index toward resolution** and **never make resolution destructive**. The whole design below is the tension between those two.

---

## 2. Conflict taxonomy: five types, five paths

### 2.1 The five types

| Type | Name | What collides | How it gets in | Example |
|---|---|---|---|---|
| **(a)** | Source-vs-source | Two retrieved sources (same tier, §SRC-TRUST) assert contradicting claims | Both arrive at answer time; neither is in memory yet | Two T1 vendor docs disagree on a drug dosage |
| **(b)** | Memory-vs-new-evidence | A stored belief is contradicted by fresh retrieval | New evidence enters through the write gate | Stored "X is CEO of Acme" vs today's news "X stepped down" |
| **(c)** | Memory-vs-memory | Two *stored* beliefs are mutually inconsistent | Inconsistent beliefs passed the gate at different times — different tiers, different moments, different entailment chains | Stored "user prefers concise answers" vs stored "user asked for detailed explanation twice" |
| **(d)** | User-vs-memory | The user asserts something contradicting a stored belief | Direct user statement at conversation time | User: "I actually live in Mumbai now" vs stored "user lives in Delhi" |
| **(e)** | Temporal (pseudo-conflict) | Two claims that *look* contradictory but carry different time anchors | Stored belief + new evidence at different valid-times | "User lives in Delhi" (2020–2026) vs "user moved to Mumbai" (2026–) |

### 2.2 How type (c) happens — the "how did both get in?" question

This is the type the task demands we explain, because two stored beliefs being inconsistent looks like a gate failure. It isn't always:

1. **Tier-asymmetric admission.** Belief A entered as T1-grounded (official doc); belief B entered months later as T3-corroborated. The gate's coherence check is an NLI-classifier pass; NLI is approximate, and "contradiction" is graded, not binary. Sub-threshold pairs pass — both legitimately, at their times.
2. **Scope drift.** Belief A was stored with an implicit context ("concise answers" observed in *chat replies*); belief B with another ("detailed explanation" requested in *study notes*). At storage time the contexts were never made explicit — the conflict is created by *de-scoping*, not by bad evidence.
3. **Inference entanglement.** One side is a stored *inference* from an earlier belief; the earlier belief was later revised, but the inference's `derived_from` link was never followed up. This is the Tripwire failure — decisions (and beliefs) break when their upstream facts change, and nobody recomputes [SP — Medium engineering essay, mechanism borrowed, not measured].
4. **User-behavior vs user-statement.** Behavioral inference (two requests for detail) vs stated preference ("keep it short"). Both are evidence about the user, at different strengths. The gate admitted both as different *preference-provenance levels* (underspecification doctrine) — the conflict is real, and it's the resolution workflow's job, not the gate's, to scope it.

**Design consequence:** type (c) resolution *always begins with a provenance audit* — pull both beliefs' tier, corroboration count, and derivation chain before any weighing. The belief with better provenance is not automatically the winner (entrenchment ≠ truth), but provenance determines the *burden of proof*.

### 2.3 Type (e) is detected, not resolved

Temporal pseudo-conflicts resolve by *recognition*, not adjudication: if both claims carry valid-time anchors and the anchors are disjoint, there is no conflict — there is a timeline. The write gate already handles the cheap case (Cycle 13's supersession protocol); the resolution workflow's job for type (e) is the **residue**: confirming the anchors are real (not inferred from retrieval date), and closing the conflict record with outcome `TEMPORAL-SCOPE` rather than leaving it open.

---

## 3. The resolution workflow: trigger → investigate → adjudicate → write back

The workflow is four stages. Each conflict type flows through all four, but with different settings per stage (the per-type table is §4).

### 3.1 Stage 1 — Trigger: when is resolution attempted vs deferred?

Not every conflict deserves immediate work. The trigger policy is **lazy by default, eager by exception**:

| Trigger | When it fires | Which types |
|---|---|---|
| **On-retrieval** | Both sides of a conflict would be returned for the same query; resolution is attempted (or abstention surfaced) because the user is about to see one of them | (a), (b), (c) |
| **On-write** | New evidence arrives through the gate contradicting a stored belief; cheap types resolve immediately | (b) low-stakes, (d) user-domain, (e) |
| **Scheduled sweep** | Periodic audit (the A-MEM-style maintenance pass) re-examines open conflict records; aged, low-stakes conflicts get resolved; stale deferrals get re-triggered | all, especially deferred |
| **User-arbiter** | Escalated conflicts; resolution attempt = presenting to the user (§5) | (d) always; others when stakes demand |

**Deferral rules (when NOT to resolve):**
- R3 conflicts are *never auto-resolved* — the "resolution attempt" for R3 is surfacing or escalation, not adjudication (§3.3).
- When the evidence set is thin on both sides (both single-sourced T3, no primary retrievable), resolving is a coin flip with extra steps: mark `DEFERRED — thin evidence`, set a review date (default 90 days [DC]), and re-trigger on the scheduled sweep *or* when new evidence arrives.
- When either side's provenance chain is broken (SRC-TRUST's adversarial screen), resolution waits for the quarantine audit — do not adjudicate a fight one side of which might be poison.

### 3.2 Stage 2 — Investigation: the tiebreaker search

Investigation is a fixed, deterministic-first sequence. The LLM never invents evidence; it only operates on retrieved chunks. The sequence borrows its skeleton from the truth-discovery literature (TruthFinder's iterative fact-confidence ↔ source-reliability loop [HC]; CRH's weighted-deviation minimization [HC]; LTM's Bayesian source-quality inference [HC]) with one deliberate departure: those algorithms assume sources *try* to be truthful. Ours may be hostile (MINJA, AgentPoison — Cycle 13), so **tier is a hard gate before weighting**, not just another feature.

**Step 1 — Normalize.** Reduce each side to the minimal contradicting claim pair. Check extraction integrity first (Nodus's rule: the graph, not the LLM, decides what's true; a deterministic verifier checks that cited quotes fall inside their spans and tenses match validity [SP]). If either claim is a mis-extraction, the "conflict" dissolves — record outcome `EXTRACTION-ERROR`, not a resolution.

**Step 2 — Temporal scope test.** Extract or retrieve valid-time anchors for both claims. Disjoint anchors → type (e) → §4's temporal path. Overlapping or anchorless → continue. (This is the KG time-disjoint constraint in miniature — MDPI 2019 [MC].)

**Step 3 — Context scope test.** Ask the cheap question before the expensive one: are the claims true in *different contexts, domains, or modalities*? Stored scope qualifiers, claim wording, and the original query contexts are compared by the NLI-classifier (cheap, deterministic-first). If a clean scope split exists → scoping resolution (§6), no weighing needed.

**Step 4 — Independence test.** Apply Cycle 12's independence test: syndication, shared authorship, near-duplicate text, citation chains collapse N chunks to one. Corroboration counts *independent* sources only. (Truth discovery's known failure mode is exactly this: repetition masquerading as consensus — the "AI Slop Loop" [HC] is what the independence test exists to defeat.)

**Step 5 — Primary-source retrieval.** If the claim class has an authoritative source (T1: official docs, the study itself, government statistics), fetch it. This step is skipped only when the primary is unretrievable — in which case the conflict's evidence ceiling is marked explicitly ("no primary source available" goes in the audit trail, §7).

**Step 6 — Evidence weighing.** Compute an evidence weight per side:

```
w(side) = tier_trust(best_chunk) × log(1 + independent_corroboration) × recency_relevance × scope_fit
```

[DC — design formula, not measured.] Notes: `tier_trust` is the *best* chunk's trust (a T1 chunk with T3 echoes is still T1 evidence); corroboration is log-scaled so five SEO echoes don't beat one primary; `recency_relevance` is relevance, not recency-as-truth — newer evidence matters for *changeable* facts (prices, personnel) and is neutral for *timeless* facts (dosages, definitions); `scope_fit` down-weights evidence whose original context doesn't match the conflict's domain.

**Step 7 — Entrenchment check (AGM).** The stored belief carries an **entrenchment score** — a design borrowing from AGM's epistemic entrenchment [VC]: how strongly the system holds it, from tier, corroboration, retrieval usefulness, and (decaying) age. Revision requires the new side's weight to *clearly exceed* the stored belief's entrenchment — the Levi-identity move (contract the old, expand the new) is only licensed when the new evidence wins by margin, not by a hair. Margin default: `w_new > 1.5 × entrenchment_old` for world facts [DC]. This is the formal version of "don't rewrite the store on thin news."

### 3.3 Stage 3 — Adjudication: who decides, by what rule

The adjudication matrix. **Rows are conflict types, columns are stakes (R0–R3 from Cycle 11).**

| Type | R0/R1 (low) | R2 (medium) | R3 (high: health, finance, security) |
|---|---|---|---|
| **(a)** source-vs-source | Resolve by evidence weight if margin clears; else retain-both-deferred | Weight + primary-source required; else deferred | **Abstain-and-surface.** Present both with citations. Never pick. |
| **(b)** memory-vs-new | Auto-resolve if weight clears entrenchment margin; else conflict record | Resolve with primary source; margin ×2 [DC]; else record | **Abstain-and-surface** to user; memory keeps *both* marked disputed until user or primary settles |
| **(c)** memory-vs-memory | Provenance audit → scope or weight-resolve | Provenance audit; resolve only if one side's provenance strictly dominates; else scope | **Escalate-to-user** (R3 memory conflicts are beliefs the user may have acted on — they get a say) |
| **(d)** user-vs-memory | **User wins on user-domain claims** (preferences, their facts) — immediate | User wins on user-domain; on world facts, record as user-disagreement (T0 opinion), do not overwrite | User-vs-memory on R3 world facts: **do not silently overwrite the world belief**; surface both, mark disputed |
| **(e)** temporal | Auto-resolve at write time (supersede with windows) | Auto-resolve; anchor verification required | Auto-resolve with verified anchors; anchors must be evidenced, not inferred |

Two rules need emphasis:

- **The R3 rule doesn't bend for memory.** Abstention was designed for retrieval-time claims (Cycle 11). The same discipline applies inside the store: an R3 conflict record is never closed by the agent's adjudication. "The abstention bar doesn't move when the disagreement lives in memory instead of in retrieval."
- **Type (d) asymmetry.** The user is the arbiter of *claims about the user* — always, immediately, no weighing. But a user correcting a *world fact* ("actually that drug's dosage is X") is T0 evidence *about the user's belief*, not a T1 source about the world. Conflating those two is how a well-meaning correction poisons the world model. The write-back for user-corrected world facts: keep the world belief, add the user's assertion as a flagged T0-opinion belief, surface the disagreement.

### 3.4 Stage 4 — Write-back: five operations

| Operation | What it does | When | What the store looks like after |
|---|---|---|---|
| **SUPERSEDE** | Bi-temporal windows (Graphiti: `valid_at`/`invalid_at`, Cycle 13): old belief gets `invalid_at`, new belief gets `valid_at` | Type (e); type (b) where the world changed | Both beliefs retained; only the current-window one is "active" |
| **CONTRACT-EXPAND** | AGM Levi identity: retract the losing belief (as *active*), expand with the winner | Weight-adjudicated (a)/(b)/(c) | Loser → audit record (retired, reversible); winner active with `supersedes` link |
| **SCOPE-ADD** | Retain both, add context qualifiers to each | §6 — the "both true" resolution | Both active, each with `scope:` qualifiers; retrieval matches scope before ranking |
| **ESCALATE** | Hand to the user as arbiter (§5) | Type (d); R3 escalations | Conflict record stays open, marked `awaiting-user`; both sides marked disputed |
| **DEFER** | Neither resolve nor escalate; schedule re-examination | Thin evidence; one side possibly poisoned; user ignored escalation | Open record with `review_at` date; both sides remain retrievable, both marked disputed |

**Dependents.** Retraction is not just the loser's problem. Beliefs with `derived_from` links to the retracted belief are flagged `needs-recheck` (the Tripwire lesson [SP]): the next retrieval touching them triggers a lightweight re-verification, not an immediate cascade — cascades are expensive and usually unnecessary; flagging is cheap and usually sufficient.

**Reversibility is structural.** Every write-back is an *appended event*, never an edit. The loser is never deleted (mem0's DELETE is exactly what we don't do — Cycle 13). Undo = append a reversal event that re-activates the prior belief and re-opens the conflict record. There is no state the resolution workflow can reach that it cannot leave.

---

## 4. The conflict record: schema and lifecycle states

The record created by Cycles 12/13 gains fields and a state machine here.

**Schema (fields):**
- `conflict_id`, `type` (a–e), `stakes` (R0–R3)
- `parties[]`: each `{belief_or_chunk_id, claim_text, provenance {tier, source, retrieved_at}, valid_time?, weight_snapshot}`
- `detected_at`, `detected_by` (gate / retrieval / sweep / user)
- `status`: `open` → `investigating` → `resolved` | `deferred` | `awaiting-user`; terminal states keep the record (never deleted)
- `review_at` (for deferred), `evidence_considered[]` (chunk refs, §7), `rule_applied` (rule id from §3.3), `outcome` (one of §3.4's operations), `resolution_id` (→ audit trail)

**Lifecycle invariant:** the index shrinks only through `resolved`. `deferred` and `awaiting-user` are *honest* states, not failure states — a deferred conflict is a documented bet that more evidence is coming. The scheduled sweep's job is to ensure `deferred` doesn't silently become `abandoned`: every deferred record has a `review_at`, and the sweep re-triggers investigation when it lapses or when new evidence on the claim arrives.

---

## 5. User-in-the-loop: the user as arbiter

### 5.1 When the user arbitrates

- **Always:** type (d) on user-domain claims — the user is the ground truth about themselves; there is nothing to investigate.
- **On demand:** R3 escalations (type (c) R3 per §3.3; R3 (a)/(b) surface-then-escalate-if-asked), and any conflict where the user explicitly asks "which is right?"
- **Never as a default for low-stakes:** asking the user to arbitrate trivia is how you train them to ignore the arbiter card. The HCI constraint from prior cycles: conflict UI must be *rare and decisive*, never a feed.

### 5.2 The presentation: one question, side-by-side, one tap

The cognitive-load problem: "I have two conflicting beliefs" is a burden to *dump*, not a question to *ask*. The card design:

1. **One conflict per card, ever.** No lists of open conflicts. If three are pending, the user sees the highest-stakes one, once.
2. **Side-by-side, evidence-first.** Each side gets: the claim in plain words, *where it came from* (source name + tier in plain language: "your doctor's note" / "two news sites" / "what you told me in March"), and *when*. No trust scores, no tier codes — the machinery stays under the glass.
3. **Three actions, not two.** "A is right" / "B is right" / **"Both — in different situations."** The third option is the scoping resolution made tappable; without it, users force false binaries and the store inherits their false precision. (This is §6's scoping operation surfaced as UX.)
4. **"Not now" is deferral, not dismissal.** Ignoring the card sets `review_at` (default 30 days [DC]) and returns the record to the sweep — *deferred, not dropped*. The conflict must be re-surfaceable: it re-appears when the user next asks about the topic (on-retrieval trigger) or at the review date, whichever comes first. Silently auto-resolving because the user didn't tap is the exact "badly-resolved conflict destroys true beliefs" failure — forbidden.
5. **Piggyback, don't interrupt.** The card appears when the user is already engaged with the topic (they asked about it, or it's the subject of the current task) — never as an ambient notification. A conflict about their medication surfaces when they ask about their medication, not on Tuesday morning.

### 5.3 After the verdict

The user's ruling writes back as **CONTRACT-EXPAND with the user as the evidence** — but the loser's provenance is preserved in the audit trail, and the resolution is tagged `arbiter: user`. If the user picked the side the evidence weighed *against*, that's recorded too (`user-overrode-evidence: true`): the system doesn't argue, but it remembers that its evidence model and the user disagree — that disagreement is itself a future conflict record if new evidence arrives. The user is the arbiter, not the oracle.

---

## 6. The "both true" resolution: scoping as a first-class operation

### 6.1 Why scoping is the default before adjudication

Three independent lines of evidence converge here:

- **KG practice:** temporal conflicts in knowledge graphs resolve by constraining validity intervals, not by deleting facts (MDPI 2019's time-disjoint constraints [MC]).
- **Truth-discovery practice:** multi-truth discovery (MTD_VCI [HC]) exists precisely because some attributes legitimately have *sets* of true values — "authors of a book" is the canonical example. The field had to build a separate algorithm family for "the conflict is the schema's fault."
- **Agent practice:** Nodus's design rule — the graph "does not flatten disagreement into a single answer" [SP] — treats preserved disagreement as a feature: the audit trail *is* the product.

For JARVIS, the operational form is: **add context qualifiers to both beliefs instead of deleting one.**

### 6.2 The scoping operation

Given conflicting beliefs B1, B2 over claim C:

1. **Find the distinguishing context.** The investigation's Step 3 (context scope test) proposes candidate dimensions: time, domain/topic, modality (chat vs document), audience, role. The cheapest sufficient dimension wins — prefer the dimension already present in the provenance (e.g., B1's evidence came from chat replies, B2's from study sessions) over an invented one.
2. **Write the qualifiers.** Each belief gets a `scope:` field in plain, retrievable form: `scope: {domain: casual-chat}`, `scope: {domain: technical-topics}`, `scope: {valid_time: [2020, 2026]}`. Scopes must be *checkable at retrieval time* — a scope the ranker can't evaluate ("when the user seems tired") is decoration, not resolution.
3. **Set the default.** Scoped beliefs need a tiebreak for unscopable queries: the belief with broader evidence (or the user's stated default) becomes `default: true`. Defaults are marked as defaults — "concise by default" is a weaker claim than "concise always," and the store says so.
4. **Cite the evidence for the scope.** The scope hypothesis is itself a belief with provenance: it cites the instances that motivated it (the two detailed-explanation requests). If future evidence contradicts the scope ("user asked for a detailed explanation of a *casual* topic"), the scope — not the beliefs — is what gets revised.

### 6.3 Worked scoping example (the task's example c, expanded)

- **B1:** "User prefers concise answers." Provenance: stated once by user (T0, high entrenchment) + corroborated by 40+ chat turns where short answers got no complaint.
- **B2 (implicit):** "User wants detailed explanations." Provenance: *behavioral* — twice asked follow-up "explain in detail" (DEMONSTRATED-level, weaker provenance: two instances, both in technical threads).
- **Naive adjudication** would weigh B1's massive corroboration against B2's two instances and contract B2 — destroying a real signal: when the topic is technical, the user *does* want depth.
- **Scoping resolution:** context dimension = topic domain (already in the evidence: both B2 instances were technical). Write-back:
  - B1 → `scope: {domain: default}`, `default: true` — "concise answers by default."
  - B2 → `scope: {domain: technical-topics}` — "detailed explanations for technical topics," DEMONSTRATED-level, citing the two instances.
  - No deletion. The conflict record closes with outcome `SCOPE-ADD`, and the scope hypothesis carries its own two-instance provenance so it can be revised, not worshipped.

---

## 7. The resolution audit trail

Every resolution — including deferrals and escalations — emits a **resolution audit record**:

- `resolution_id`, `conflict_id`, `resolved_at`, `resolved_by` (agent-auto / sweep / user)
- `parties_snapshot`: the claims *as they were at resolution time* (claims drift; the snapshot is immutable)
- `evidence_considered[]`: every chunk/source consulted, with tier and weight contribution — including evidence that *lost*. (The loser's evidence is what a future reversal needs.)
- `rule_applied`: the §3.3 matrix cell (e.g., `c/R1 → provenance-audit → scope`), plus the numeric weights and margin if weighing was used
- `outcome`: one of §3.4's five operations, with the resulting belief IDs and their new states/windows/scopes
- `reversibility`: `reversal_event_template` — the exact append needed to undo (which belief to re-activate, which windows to restore). Undo is *designed at resolution time*, not improvised later.
- `dependents_flagged[]`: beliefs marked `needs-recheck`

**Connection to Cycle 13's §18 changelog/rollback:** the audit record *is* the changelog entry — resolution events are the highest-priority entries in the rollback log, because a resolution is the only operation that retires a belief the system previously trusted. Rollback of a resolution = append the reversal event; the conflict record re-opens as `open` with a note (`reopened_by: rollback`), and both beliefs return to disputed-active. Nothing is ever un-happened; everything is superseded, including the supersession.

**What the audit trail does not do:** it does not certify truth. A resolved conflict is a *bet the system would defend* — the record shows the reasoning so the bet can be audited, challenged, and reversed. "Resolved" means "the index shrank and the reasoning is on file," not "this is now certainly true."

---

## 8. Worked examples

### 8.1 Example (a): T1 vs T1 on a drug dosage → R3 → abstain + surface both

- **Conflict:** Vendor A's official label (T1, trust 0.90) says 50 mg max daily; Vendor B's official label (T1, trust 0.90) for the *same compound* says 100 mg. Both retrieved at answer time for "what's the max dose?"
- **Type/stakes:** (a), R3 (health).
- **Trigger:** on-retrieval — the user is about to receive one of these as "the answer."
- **Investigation:** normalize → both claims are clean extractions, same compound, same population. Temporal test: no anchors (timeless dosing claim). Scope test: no clean split (same indication). Independence test: both are primaries for their own labels — independent, both T1. Weighing: `w_A ≈ w_B` — margin doesn't clear by design; even if it did, R3 forbids auto-resolution.
- **Adjudication:** `a/R3 → abstain-and-surface`.
- **Write-back:** no memory write of either dosage as fact. Conflict record stays `open` (outcome: none — abstention is not a resolution). The *answer* carries both: "Vendor A's label says 50 mg max; Vendor B's says 100 mg for the same compound — these disagree, and this is a decision for your doctor/pharmacist, not for me." Both citations attached.
- **Lesson:** the conflict index does *not* shrink here, deliberately. Shrinking an R3 index by picking a winner is exactly the "badly-resolved conflict destroys true beliefs" failure — with dosages, the destroyed belief could destroy the patient.

### 8.2 Example (b): "user lives in Delhi" vs "user moved to Mumbai" → temporal supersession

- **Conflict:** Stored belief (T0 — user stated, 2024): "user lives in Delhi." New evidence through the gate (T0 — user stated today, 2026-10-19): "I moved to Mumbai last month."
- **Type/stakes:** (e) after the temporal test; R1 (location matters for scheduling/weather, not safety-critical). Note the (d) flavor — the user is the source — but the *resolution mechanics* are temporal.
- **Trigger:** on-write — the gate's coherence check fires on the contradiction.
- **Investigation:** Step 2 temporal scope test: old claim's valid anchor is implicit (stated 2024, "lives" = present-tense then); new claim carries an explicit anchor ("last month" → ~2026-09). Anchors disjoint → type (e) confirmed. No weighing needed — this is the Cycle 13 move-cities case, and weighing would be the wrong tool (the old belief wasn't *wrong*, it *expired*).
- **Adjudication:** `e/R1 → auto-supersede`.
- **Write-back:** SUPERSEDE with bi-temporal windows:
  - B_old: `valid_at: [2024-03, 2026-09]`, `invalid_at: 2026-09`, status retired-active-history (still retrievable for "where did I live in 2025?" — the past didn't stop being true).
  - B_new: `valid_at: [2026-09, now]`, active.
  - Audit record cites both utterances; `reversal_event_template` restores the windows if the move turns out to be temporary (user: "actually I'm back in Delhi" → new SUPERSEDE, windows extend — the chain is the history).
- **Dependents flagged:** beliefs derived from Delhi-residence (e.g., "user's timezone is IST" — still true; "nearby restaurants" preferences — needs-recheck on next food query).

### 8.3 Example (c): "likes concise answers" vs "asked for detailed explanation twice" → scoping

- **Conflict:** Stored B1 (T0 stated + 40-turn corroboration, high entrenchment): "user prefers concise answers." Two recent behavioral instances (DEMONSTRATED-level): user asked for detailed explanations, both in technical threads.
- **Type/stakes:** (c), R1 (answer style affects satisfaction, not safety).
- **Trigger:** on-retrieval — both beliefs fire for "explain quantum error correction," and they'd produce opposite behaviors.
- **Investigation:** provenance audit first (type (c) rule): B1's provenance strictly dominates on *volume*, but B2's instances are *recent and domain-clustered* — volume dominance isn't scope dominance. Context scope test: both B2 instances share `domain: technical`; B1's corroboration spans all domains. Clean scope split exists → scoping, no weighing.
- **Adjudication:** `c/R1 → scope`.
- **Write-back:** SCOPE-ADD (§6.3): B1 scoped `default`, B2 scoped `technical-topics` at DEMONSTRATED-level with the two instances cited as the scope's provenance.
- **Why not CONTRACT-EXPAND:** weighing would retire B2 on corroboration-count alone — the classic truth-discovery failure mode (majority beats the truthful minority). The minority here isn't *wrong*, it's *conditional*. Scoping preserves the conditional truth; the audit trail records that the scope hypothesis rests on two instances and is revisable.

---

## 9. Theoretical grounding: what the field gives us, and where we depart

| Source | What we borrow | Where we depart |
|---|---|---|
| **AGM belief revision** (Alchourrón, Gärdenfors, Makinson 1985 [VC]) | The operation vocabulary: revision = contract-then-expand (Levi identity); entrenchment orders retraction; minimal change as the ideal | AGM assumes logical omniscience, consistent belief sets, and truthful new information. We keep none of those: entrenchment is a computed score, not an ordering over a closed set; new evidence may be poison; consistency is *maintained by workflow*, not assumed. And we reject silent contraction — AGM's contraction deletes; ours retires-to-audit. |
| **Truth discovery** (TruthFinder [HC]; CRH, Li et al. KDD 2014 [HC]; LTM, Zhao et al. 2012 [HC]) | Iterative fact-confidence ↔ source-reliability estimation; weighted deviation minimization; the structural idea that *reliability is learned from agreement patterns* | Truth discovery assumes sources attempt truthfulness and that ground truth is single. Our tiers gate *before* weighting (hostile sources don't get a vote), and multi-truth/scoping handles the non-single-truth cases the field needed a separate algorithm family (MTD_VCI [HC]) to address. |
| **KG conflict resolution** (Detect-Then-Resolve, Mathematics 2024 [HC]; time-constraint approach, Sensors 2019 [MC]) | Detect-then-resolve pipeline shape; temporal disjointness as a first-class resolution | KG work resolves triples from web extraction; we resolve *beliefs about a user and their world*, where the "ground truth" is sometimes the user's own say-so (type d) — a case the KG literature never meets. |
| **Provenance-preserving stores** (Nodus on FalkorDB [SP]; Tripwire's valid-vs-recorded time [SP]) | "Do not flatten disagreement into a single answer"; bi-temporal separation; dependency tracking from facts to downstream decisions | We operationalize these as *write-back operations* (SCOPE-ADD, SUPERSEDE, dependents-flagging) rather than visualization or inspection tooling — the audience is the agent's own future retrievals, not a human analyst. |

---

## 10. Failure modes: what this design does not establish

1. **Resolution ≠ truth.** Every resolution is a bet with the reasoning on file (§7). A resolved conflict can still be wrong — the audit trail exists so wrongness is *findable and reversible*, not so it's impossible.
2. **Scoping can manufacture false precision.** "Detailed for technical topics" from two instances is a hypothesis wearing a rule's clothes. The design mitigates by citing the scope's own thin provenance and making scopes revisable — but a scope that *looks* principled and is wrong will steer behavior until challenged. Scopes need their own review pressure; the sweep should re-examine scopes with <5 evidencing instances.
3. **Entrenchment can ossify.** The 1.5× margin [DC] protects against churn, but it also means a well-corroborated false belief is *hard to dislodge* — the store develops incumbency bias. Counterweight: entrenchment decays with age and *loses* to primary sources by rule (a T1 primary clears any margin — primaries don't compete on weight, they settle).
4. **The R3 abstention has a cost.** Open R3 conflicts accumulate; the index grows exactly where the stakes are highest. That's accepted: the alternative (auto-resolving health/finance conflicts) is the named catastrophic failure. The mitigation is escalation UX that *works* — §5's card has to be good enough that `awaiting-user` actually converts.
5. **Trigger policy is unvalidated.** Lazy-by-default vs eager resolution, the 90-day deferral review, the 30-day user-ignore re-surface — all [DC] numbers with no measurements behind them. The sweep's effectiveness at shrinking the index is the metric to watch when this gets built; if the open-index grows monotonically, the triggers are too lazy.

---

## 11. Unknowns

- **Optimal trigger policy** [UK]: the eager/lazy boundary is a guess. Real usage data (conflict arrival rate vs. retrieval-collision rate) should set it; until then, lazy-by-default is the conservative choice.
- **Entrenchment dynamics** [UK]: the 1.5× margin, the decay function, the "primary settles" override — all untested. AGM gives the *shape* (entrenchment ordering) but no numbers; truth discovery gives iterative estimation but for source reliability, not belief entrenchment. The mapping is ours and unvalidated.
- **Automatic type-(e) detection** [UK]: the temporal scope test needs reliable time-anchor extraction from arbitrary claims ("last month," "since the reorg," tense shifts). Heuristic extraction will mis-anchor; mis-anchored supersession silently rewrites history — the highest-severity failure of the temporal path.
- **Dependent recomputation cost** [UK]: flagging `needs-recheck` is cheap; the re-verification it triggers on next retrieval is not yet budgeted. Deep derivation chains could make one resolution expensive at read time — needs a depth cap [DC candidate: 2 hops].
- **User-arbiter conversion** [UK]: whether the §5 card actually resolves `awaiting-user` records or just accumulates ignored cards is an empirical HCI question. The "deferred, not dropped" rule assumes re-surfacing works; if users train themselves to dismiss, the R3 index grows without bound — the failure mode §10.4 names.

---

## 12. References

- Alchourrón, Gärdenfors, Makinson — AGM belief revision (1985). Entrenchment, Levi/Harper identities, contraction/expansion/revision. [VC — foundational, via philarchive/SEP summaries]
  - https://philarchive.org/archive/HUBBRIv1
- TruthFinder — Yin, Han, Yu: Bayesian iterative truth discovery over conflicting web facts. [HC]
  - https://underthehood.meltwater.com/blog/2020/01/20/truth-discovery-in-practice-aggregating-conflicting-datasources/
- CRH — Li et al., KDD 2014: truth inference as weighted-deviation optimization. [HC]
- LTM — Zhao et al.: Bayesian latent truth model, source specificity/sensitivity. [HC]
  - https://www.emergentmind.com/papers/1203.0058
- Detect-Then-Resolve (CRDL) — conflict detection + LLM resolution for KG fusion, *Mathematics* 2024. [HC]
  - https://www.mdpi.com/2227-7390/12/15/2318/htm
- Time-constraint KG conflict resolution — *Sensors* 2019: time-disjoint / precedence / mutual-exclusion constraints. [MC]
  - https://www2.mdpi.com/2076-3417/9/20/4399
- MTD_VCI — multi-truth discovery with confidence intervals (ResearchGate). [HC]
  - https://www.researchgate.net/publication/299583200_An_Integrated_Bayesian_Approach_for_Effective_Multi-Truth_Discovery
- Nodus on FalkorDB — provenance-preserving graph; deterministic verifier; "does not flatten disagreement into a single answer." [SP — engineering blog, pattern borrowed]
  - http://dev.to/rishik92/every-fact-cited-dated-and-disputed-building-nodus-on-falkordb-14
- Tripwire — valid time vs recorded time; fact→decision dependency layers. [SP — Medium essay, mechanism borrowed]
  - https://medium.com/@faleesha.zaeen/tripwire-when-the-facts-change-which-decisions-break-fc0b9ed41778
- Graphiti bi-temporal model (`valid_at`/`invalid_at`/`created_at`/`expired_at`) [VC — via Cycle 13]; mem0 ADD/UPDATE/DELETE/NOOP (arXiv:2504.19413) [VC — via Cycle 13].

---

*Cycle 14 closes the conflict lifecycle: record (12) → gate (13) → resolve (14). Next open threads: trigger-policy validation, entrenchment dynamics, and the scheduled sweep's effectiveness metric — all flagged [UK] above.*
