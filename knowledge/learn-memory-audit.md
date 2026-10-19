# MEM-AUDIT: The Memory Audit — JARVIS's Immune System

**Cycle 15 — Phase Infinity research. Status: LEARNING ONLY — no code, no installs, no execution.**
**Date:** 2026-10-19. **Question:** How does JARVIS audit its own memory for poisoning, drift, and decay?

## TL;DR

Cycle 13's write gate is the front door; Cycle 12's trust tiers are the bouncer's guest list; Cycle 14's resolution workflow is the courtroom. This cycle designs the **immune system**: the longitudinal, background process that catches what all three miss — slow-burn poisoning (many small individually-plausible writes), drift (once-true memories gone stale), decay (confidence that should have dropped but didn't), and contradictions that slipped past the gate's NLI classifier.

The design has five parts:

1. **A six-check audit battery** — re-screening (stratified by tier, T3-heavy), provisional re-corroboration (the promotion/demotion treadmill), contradiction sweep (blocking strategy that defeats the N² problem), write-log reconciliation (hash-chained append-only log vs store, detecting gate bypasses and tampering), staleness review (temporal-validity windows), and burst forensics (was that write burst onboarding or attack?).
2. **Scheduling + budget** — the audit runs in the **DREAM phase** (idle/low-activity consolidation window, per the OpenClaw/Sleep literature), as a nightly micro-audit plus a weekly full audit, bounded by the ≤5% metalevel-compute rule from learn-bounded-rationality, with risk-first prioritization (T3-provenance, high-stakes-adjacent, recently-conflicted).
3. **Slow-burn detection with honest limits** — distributional analysis of write patterns (topic clustering, provenance concentration, drift direction via CUSUM), plus the explicit admission of what's fundamentally undetectable: organic-looking preference evolution whose ground truth is the user's own mind. The user is the final oracle; the audit surfaces, never convicts.
4. **The audit report** — machine-readable JSON (checks run, findings, actions, undo refs) that itself goes through the write gate as a LESSON, plus a human digest surfaced *only* when action is needed. Quiet success is the norm. Wired into the observability metrics set.
5. **A worked 6-month walkthrough** — three findings: a T3 health claim demoted to a conflict record, a slow vendor-preference drift flagged for user review, a DEMONSTRATED-vs-DEMONSTRATED contradiction opened as a conflict record and deferred to the user-arbiter.

The load-bearing security rule: **the audit has no privileged write path.** Every audit action (demotion, quarantine, conflict record, supersession) passes through the write gate and lands in the write log like any other write. The immune system writes through the same valve it inspects — an immune system that can silently rewrite memory is a second poisoning vector, not a defense.

---

## 1. Why the audit exists (the gate's blind spots)

Cycle 13's six gates are point checks: they judge one candidate at one moment. Four adversary classes survive point checks by being *longitudinal*:

| Adversary | Why the gate misses it | What catches it |
|---|---|---|
| **Slow-burn poisoning** — many small individually-plausible writes that together shift behavior (preference shaping) | Each write is under every threshold: plausible text, clean scanner verdict, under budget. "Long-term behavioral drift," not "output manipulation" — Forcepoint's persistent-memory-poisoning taxonomy names exactly this split [forcepoint.com, HC] | Distributional analysis of write patterns over time (§4) |
| **Drift** — once-true memories gone stale (a price, a phone number, a world fact whose source updated) | The gate verified it *at write time*. Nothing in the gate re-checks at read time + 6 months. "The occasional wrong fact gets outvoted" only if somebody re-counts — the Sleep literature's point [dev.to/do-ai-agents-need-to-sleep, SP] | Staleness review (§2.5) |
| **Decay failure** — confidence that should have dropped but didn't (rent charged wrong, retrieval refresh mis-attributed) | The gate *sets* confidence; ECAN rent *decays* it. Neither checks whether the decay happened. Rent is a mechanism, not a guarantee | Reconciliation + rent-audit sampling (§2.4, §2.2) |
| **Slipped contradictions** — two memories that contradict but scored below the gate's 0.75 cosine band, or fooled the NLI classifier | Gate 4's classifier is approximate (~80s on paraphrase, worse on negation/scope per CLAIM-VER §3.2). Sub-threshold and misclassified pairs both pass — "legitimately, at their times" (CONFLICT-RES §2.2) | Contradiction sweep (§2.3) |

The field converges on this architecture from the other direction. OpenClaw's Dreaming runs Light/REM/Deep phases on a cron during off-hours to turn "noisy short-term signals into curated long-term knowledge" [dev.to/czmilo, SP — community guide]; the Sleep-Time Compute work reports ~5× reduction in test-time compute by pre-computing during idle [claude-wiki.com, HC]; the 2026 "Do LLMs Need Sleep?" papers formalize the principle — *"there needs to be a phase between seeing something and changing from it"* [turingpost.com, HC]. The Nocturne pattern in MASTER-INDEX M2 already places JARVIS's composition as **gate at write → evolution after → verification during idle**. This file designs the third leg.

And the security literature confirms the target. Arthur's memory-poisoning analysis: *"by the time it does damage, the turn that planted it is long gone. Single-turn defenses never see it"* [arthur.ai, HC]. The fafi25 detection guide's key metrics — refusal-rate deviation, retrieval-influence (memory dominating outputs), and the **Behavioral Drift Index (BDI) with sliding-window cumulative measurement that catches gradual corruptions** — are audit-time, not write-time, instruments [fafi25.substack.com, SP — practitioner guide, metrics plausible, thresholds are starting points]. Microsoft's 2025 guidance even recommends users *regularly clear assistant memory* to prevent "invisible manipulation" [news.aibase.com, HC] — the audit is the disciplined, non-destructive alternative to that amputation.

**Design vocabulary used throughout:** all numeric parameters are design choices tagged [DC]; real external facts carry the usual [VC/HC/MC/SP] tags; unknowns carry [UK].

---

## 2. The audit suite: six checks

Each check has: **trigger** (when it runs), **cost** (compute envelope), and **action-on-failure** (what happens when it finds something). Checks are ordered by the scheduling priority from §3 — reconciliation and forensics first, sweep and staleness later.

### Check (a) — Re-screening: the verdicts that aged

**What:** Re-run the injection/provenance screen over a **stratified sample** of stored memories. A memory's screen verdict was computed at write time with scanner version *v_w*. The scanner improves (new patterns from the 13-attack hardened_runner suite, new supply-chain intelligence like ClawHavoc-class discoveries). Old verdicts rot — Cycle 12 §6.2 already requires tier assignments to be versioned with the screen version. Re-screening is the scheduled enforcement of that requirement.

**Sample design (stratified by provenance tier, T3-heavy) [DC]:**
- **40% T3** (unvetted web) — highest-value targets: the ZeroFox .edu/.gov borrowing-credibility case and the slop-loop fabrication case both live here.
- **25% T2**, **20% T1** — primarily *world-facts* only; T1 trust is conditional (provenance-chain completeness can break retroactively, e.g., a domain later identified as compromised).
- **10% T0-world** — the user's own files/web claims *about the world* (T0-about-user excluded: the user is the authority on themselves; re-screening "I like dark mode" for injection patterns is category error).
- **5% quarantine log** — spot-check that nothing in quarantine was miscategorized (quarantine→promotion review is §2.2's sibling).

Within each stratum, sample **risk-ordered**: high-stakes-adjacent memories first (anything touching health/finance/security topics), then by retrieval frequency (a poisoned memory retrieved daily does more damage than one retrieved never).

**What changed since write time (the two deltas the re-screen evaluates):**
1. **New attack patterns in the library** — the scanner's pattern library grows with each hardened_runner regression; a memory screened clean under v1.x may fire under v2.x (e.g., a newly-added Unicode-obfuscation pattern).
2. **Provenance-chain enrichment** — links discovered since write time (a syndication relationship found later, a domain blocklist update, a source reclassified from T2→T4 after a supply-chain disclosure).

**Trigger:** weekly full-audit slot; additionally triggered immediately whenever the scanner version bumps (screen-v-change → targeted re-screen of everything screened under the old version's affected rules, not a fresh sample).

**Cost:** deterministic pattern scan per memory — cheap (~ms each). A 10,000-fact store's full re-screen is minutes on CPU, not hours; the stratified sample (default 500/stratum-weighted [DC]) is seconds. The LLM-judge half of the screen runs only on high-stakes-flagged hits — bounded by the weekly audit's compute budget (§3).

**Action-on-failure:**
- Screen now fires on a previously-clean memory → **tier downgrade by one full tier** (T3→T4-equivalent handling), never a silent confidence tweak. The memory is re-gated as if newly written: hostile verdict → QUARANTINE with the audit ID cited; suspicious → demote to PROVISIONAL with the new verdict recorded.
- Screen now *clears* a previously-flagged quarantine entry (false positive at write time, e.g., a legal disclaimer that tripped the imperative-verb pattern) → promotion candidate: re-enters the write gate as a normal candidate, not auto-promoted. The audit proposes; the gate disposes.
- Every re-screen verdict is **version-stamped** on the memory's provenance record: `screen_verdicts: [{version, date, verdict}]`. The audit trail of verdicts is what makes the *next* re-screen incremental rather than from-scratch.

### Check (b) — Provisional re-corroboration: the promotion/demotion treadmill

**What:** Every PROVISIONAL memory (INFERRED preferences, uncorroborated T3 claims, hypotheses in the hypothesis namespace) carries a `review_at` date and an evidence requirement. The audit processes the due queue: for each provisional, it attempts **re-corroboration** — checking whether the world has since supplied the missing evidence.

**The four outcomes (mechanical, not judgmental):**
1. **Confirmed by new evidence** → **promote**: the memory re-enters the gate at its new evidence level (e.g., INFERRED → DEMONSTRATED on the preference ladder when a third independent instance has been logged; provisional fact → WRITE when a T1/T2 corroboration arrives). Promotion is evidence-driven — same rule as write-time, just run later.
2. **Contradicted by new evidence** → **conflict record**: the provisional and the contradicting evidence become parties to a conflict record (CONFLICT-RES type b/c), status `open`. The provisional is *not* deleted — it becomes the loser's audit side.
3. **Unevidenced after N days** → **demote or expire**:
   - INFERRED preferences with no new instances in **90 days** [DC] → demote to HYPOTHESIZED (back to the hypothesis namespace, out of retrieval) or drop.
   - HYPOTHESIZED entries → the write-gate's 30-day TTL already expires them; the audit enforces the TTL on any stragglers.
   - Provisional facts (T3 claims awaiting corroboration) → after **180 days** [DC] without corroboration, demote to a *conflict-style open-question record* ("unverified claim, source: X") or expire. A provisional fact that sits forever is a time bomb with a lit fuse — the slop loop teaches that repetition-without-verification *becomes* consensus if you wait long enough [lily-ray via SRC-TRUST, HC].
4. **Still provisional, evidence window open** → **re-schedule**: `review_at` advances (with a capped number of extensions — a provisional extended 3 times without new evidence is demoted by the treadmill, not kept by optimism [DC]).

**Re-verification reuses CLAIM-VER's ladder** (explicitly designed as reusable for this purpose): the provisional claim descends rungs 1–3 against *current* evidence (fresh retrieval, not the write-time chunks — sources may have updated). This is the "re-verification" half of the loop claim-verification promised.

**Trigger:** nightly micro-audit processes provisionals with `review_at ≤ today` (bounded: at most K per night [DC: K=25], overflow rolls to the weekly full audit). The weekly full audit also runs the **rent-audit**: sample non-provisional memories and verify their (strength, confidence) matches what the ECAN decay schedule predicts — catching decay failures (the "confidence that should have dropped" adversary from §1). A mismatch beyond tolerance → recompute confidence from evidence and log the correction as an audit action.

**Cost:** the expensive check — ladder rungs cost retrieval + NLI forward passes per provisional. Bounded by the nightly K cap and the weekly budget. Provisional re-corroboration is the audit's single largest compute line; that is why it is *amortized nightly* rather than batched weekly (spreading the cost is itself the bounded-rationality move).

**Action-on-failure:** as above; plus **rent-audit corrections** are written as STRENGTHEN/WEAKEN events (append-only, logged, reversible — never in-place edits), and any systematic rent deviation (many memories over-confident) becomes a **LESSON candidate** for the gate ("rent rate for FACT type appears miscalibrated") — the immune system diagnosing its own metabolism.

### Check (c) — Contradiction sweep: defeating the N² problem

**What:** Find stored memory pairs that contradict each other but were never linked as conflicts — the sub-threshold and misclassified residue of Gate 4.

**The N² problem, concretely:** a 10,000-memory store has ~50M pairs. Even at 10ms per NLI pair, that's ~6 days of CPU. The sweep is tractable only with **blocking**: partition memories so that candidate pairs are compared *within* blocks, never across the whole store.

**The four-block strategy [DC design]:**

| Block key | What it captures | How it's built | Miss risk |
|---|---|---|---|
| **B1: entity slot** | Same-entity contradictions ("user lives in X" vs "user lives in Y") | Group by the memory's entity/slot field (the structured key from extraction — `subject`, `slot`). Pairs within a slot. | Misses paraphrased entities ("his GPU" vs "the RTX 2060") — the dedup-is-retrieval problem (MEM-SPEC §2.3). Mitigated by B3. |
| **B2: type + topic cluster** | Same-topic contradictions at the same ladder rung (two DEMONSTRATED preferences pulling opposite ways) | Type filter (PREFERENCE vs PREFERENCE, FACT vs FACT) × embedding topic cluster (HDBSCAN over memory embeddings, or LSH banding for the streaming case). Pairs within (type, cluster). | Misses cross-topic contradictions (rare and usually scope-resolvable). |
| **B3: ANN neighborhood** | Near-duplicate-band pairs the gate's 0.75 cosine threshold missed (threshold misses happen at boundary; embedder drift shifts boundaries) | For each memory, its k-nearest neighbors from the existing ANN index (Chroma already maintains one — reuse it, don't build a second index). k=25 [DC]. Pairs (m, neighbor) with cosine ≥ 0.70 [DC — deliberately *below* the gate's 0.75 to catch boundary misses]. | Approximate index misses (ANN recall < 100%). Mitigated by combining with B1/B2 — a pair must evade all three to escape. |
| **B4: derivation chain** | Inference entanglement (CONFLICT-RES §2.2 mechanism 3): a belief whose `derived_from` ancestor was later superseded/revised | Walk `derived_from` links; for each memory, check it against the *current* version of every ancestor in its chain. Linear in chain depth, not quadratic. | Misses unlinked derivations (extraction failed to record the link). |

**Incremental, not full, by default:** the sweep is **delta-driven**. Every memory carries `sweep_version`. The weekly sweep examines only pairs where **at least one member is new or changed since the last sweep** (`sweep_version < current`) — each new memory compared against its blocks' existing members. This is O(blocks × k) per new memory, not O(N²). A **full sweep** (all pairs within blocks) runs monthly [DC] or after any integrity event (chain break, burst-forensics attack verdict), to catch the slow accumulation of boundary misses.

The NLI classifier (3-way head, per CLAIM-VER §2) judges each candidate pair: entail/neutral/contradict. Contradictions → **CONFLICT-RECORD** (type c), with both memories' provenance attached — exactly CONFLICT-RES's "always begins with a provenance audit" rule, satisfied by construction since the gate stored provenance with every memory.

**Dedup against the open index:** before opening a new conflict record, check the existing conflict index for the same pair (by memory IDs) — if already open, attach the sweep's NLI verdict as additional evidence to the existing record (re-corroboration of the conflict itself) rather than duplicating.

**Trigger:** weekly full-audit slot (delta sweep); monthly or post-incident (full sweep). Skipped entirely on weeks where the nightly micro-audits found zero new contradiction candidates — the sweep earns its compute by being lazy when the store is quiet (bounded-rationality: don't pay for checks with no expected yield).

**Cost:** delta sweep ≈ (new memories/week) × (avg block size × B3 k) NLI pairs. At 40 writes/day × 7 = 280 new memories, blocks averaging ~50 members → ~14k candidate pairs/week before dedup, NLI-batched → minutes on CPU [DC estimate, unmeasured]. Full monthly sweep ≈ sum over blocks of |block|² — bounded by cluster granularity; HDBSCAN topic clusters keep the largest blocks in the hundreds.

**Action-on-failure:** contradictions become conflict records (never auto-resolved by the audit — resolution belongs to the CONFLICT-RES workflow; the audit is a *detector*, not a judge). If a single memory contradicts *many* others (hub of contradiction — likely a poisoned or overgeneralized entry), the audit additionally **quarantines the hub pending review** rather than opening N conflict records — one quarantine with N citations beats N conflicts for both the index size and the user's attention.

### Check (d) — Write-log reconciliation: the gate-bypass detector

**What:** The write log is append-only and **hash-chained**: each entry stores `seq` (per-tenant sequence), `payload` (the gate outcome + memory ID + provenance snapshot + timestamp), `prev_hash`, and `this_hash = SHA256(canonical(seq || payload || prev_hash))`. The pattern is standard tamper-evident logging — sequential chain rather than Merkle tree, because audit logs are verified in order (the dev.to chainlog pattern [dev.to/wfx1607, MC — practitioner implementation of the standard construction]; the same construction TheWARDN uses for governance audit trails [docs.thewardn.ai, HC]).

Reconciliation is the **two-directional audit** Cycle 13 named but didn't design:

**Direction 1 — log → store (completeness):** for every log entry with outcome ∈ {WRITE, WRITE-PROVISIONAL, SUPERSEDE, STRENGTHEN}, the referenced memory exists in the store with matching type, outcome, and `created_seq`. A log entry whose memory is missing = the memory was deleted or lost outside the protocol (durability bug, manual DB edit, or a second writer — MEM-SPEC §5.3's single-writer discipline violated). **Action:** restore from backup if the log is intact (the log's payload snapshot is the recovery source), flag the loss as an integrity event, and — if the pattern repeats — escalate to the user, because repeated log→store gaps mean the write path is broken or being bypassed.

**Direction 2 — store → log (legitimacy):** for every memory in the store, a creation log entry exists. An **orphan memory** (in the store, absent from the log) is the signature of a gate bypass: something wrote to the database without passing through the write gate. There are exactly two legitimate causes — a restore from backup (documented, seq-annotated) and a schema migration (documented, seq-annotated). Everything else is either a bug or an attack. **Action:** orphan memories are **quarantined pending investigation** (they cannot be trusted — the whole point of the gate is that unlogged provenance is untrusted provenance), and the orphan event is itself logged (the log records the discovery of the gap — the chain documents its own incompleteness honestly).

**Direction 3 — chain integrity:** walk the chain verifying `this_hash` recomputation and `prev_hash` linkage, with no sequence gaps. A break localizes the tampering to the exact entry (the chain-construction property: *"editing one record is mathematically impossible to hide"* [dev.to/gentlyding, MC]). **Honest limit, stated plainly:** the chain is **tamper-evident, not tamper-proof** — someone with raw database access can rewrite the whole chain, and the chain cannot prove it wasn't [dev.to/vinod_patil, HC — "tamper-evident, not tamper-proof" is the correct characterization]. The defense-in-depth: (1) the chain makes *casual* tampering (a bug, a sloppy manual edit, a partial attack) detectable at the next verification; (2) **periodic anchoring** — the weekly audit writes the chain's head hash into a separate, append-only anchor file (and optionally the session log, which lives on a different durability path per learn-observability's external-session-store pattern), so a full-chain rewrite must also rewrite the anchors; (3) verification runs *before* any audit action is taken, so a broken chain halts the audit rather than letting it act on tampered state.

**The GDPR-shape interaction:** user erasure ("forget that") deletes memory *content* per the 13-item checklist (MEM-SPEC §6.1) but the log entry remains with its payload **redacted to a tombstone reference** (the cryptographic-erasure pattern [dev.to/gentlyding, MC] — erase the content, keep the timeline). The chain stays verifiable because the hash was computed over the original payload *at write time*; reconciliation of a tombstoned entry checks the hash against the stored (original) hash, not a recomputed redacted payload. Erasure is forward-complete; history remains auditable.

**Trigger:** nightly micro-audit (chain walk + directions 1–2 over the last 24h of entries — cheap, O(entries)); weekly full-audit (complete chain walk from genesis + full store→log orphan scan). Chain verification is the audit's *first* act each run — a broken chain means nothing else the audit finds can be trusted until integrity is restored (fail-closed ordering).

**Cost:** O(entries) hash recomputations — microseconds each; even a year's entries (~15k) verify in seconds. The orphan scan is O(memories) — one indexed pass. This is the cheapest check in the battery, which is why it runs nightly: integrity is the foundation everything else stands on.

**Action-on-failure:** chain break → **halt the audit, alert the user immediately** (integrity events are the one audit finding that interrupts quiet success — this is the "tamper detection" that the field's memory-security literature treats as the Level-3/4 capability [cybersecpentesting.com, HC]). Orphans → quarantine + investigate. Missing memories → restore + flag. All three are logged as integrity events with the chain position where they were found.

### Check (e) — Staleness review: the half-life of truth

**What:** Every memory carries a temporal-validity window (`valid_at`, `review_at`) and a topic class with a **refresh interval** — the "half-life of truth" varies by topic (SRC-TRUST §3.1's recency-decay table: prices/APIs/software-versions decay fast; math/definitions decay slow). The staleness review processes memories whose `review_at` has passed: **re-verify or demote**.

**The re-verification ladder (cheap-first):**
1. **Source-alive check** (deterministic): does the cited source still exist and still assert the claim? (URL resolves; the T1 doc's current version still contains the proposition — a diff against the cited quote.) If the source retracted or the page 404s → **demote one confidence band** and flag (Cycle 13's "stale demotion" rule: demoted, not silently kept).
2. **Light re-retrieval** (bounded): one retrieval round with the memory's claim as query; if a current T1/T2 source contradicts it → conflict record; if corroborates → extend `review_at`, top up strength (this is legitimate retrieval-refresh, unlike the ranker's self-justification the gate forbids).
3. **User-adjacent facts skip re-verification**: "user's birthday" doesn't need a web check. Staleness review is for *world* facts; user facts age only via the preference ladder's own mechanics (a DEMONSTRATED preference with no behavioral evidence in 180 days [DC] → demote to INFERRED — the behavior *is* the source, and the source went quiet).

**TEMPORAL-STATE fast path:** memories typed TEMPORAL-STATE ("traveling this week," "meeting at 3pm") whose expected validity has passed are **archived, not reviewed** — review would cost more than the memory is worth. The type system already encodes the expiry; the audit just enforces it.

**Trigger:** nightly micro-audit processes `review_at ≤ today` (bounded K, same amortization as provisionals); weekly full audit sweeps for memories *missing* `review_at` (extraction gaps — every world-fact should have one; missing windows are themselves a finding, assigned a default by topic class).

**Cost:** dominated by source-alive checks (HTTP HEAD/GET per memory — network-bound, batched, cached). Bounded by the nightly K cap; the weekly missing-window sweep is O(memories) metadata-only.

**Action-on-failure:** demote (confidence band down, `review_at` reset shorter — a fact that went stale once gets watched more closely, the immune system's memory of past infections), conflict-record on contradiction, archive on TEMPORAL-STATE expiry. A memory demoted *twice* for staleness is archived — twice-stale is the signal that the topic class's refresh interval was wrong, which becomes a LESSON candidate ("refresh interval for {topic} too long").

### Check (f) — Burst forensics: was it onboarding or attack?

**What:** The gate's Layer-3 burst tripwire fires on anomalies: >10 write candidates in a single turn, or >3 QUARANTINE outcomes in a day (MEM-WRITE-GATE §6.2). The tripwire is a *flag*, not a verdict — the gate keeps working (availability matters). Burst forensics is the **post-hoc investigation** the audit performs on every flagged burst: legitimate or attack?

**The forensic procedure (deterministic-first):**
1. **Cluster the burst's writes** by topic (embedding similarity) and by provenance (session, source tier, injection verdicts).
2. **Score legitimacy on three axes:**
   - **Provenance concentration:** burst writes all T0 (user's own utterances, one session) → onboarding-shaped. Burst writes mixed T2/T3 from tool outputs and web content → investigation-shaped. Burst writes concentrated in *one* T3 source → attack-shaped (the single-source injection pattern).
   - **Topic coherence vs topic spray:** onboarding bursts cluster (the user setting up their profile: name, preferences, projects — coherent). Attack bursts either spray (MINJA-style: many records across topics to maximize persistence surface) or laser-focus on one high-value slot (preference-shaping: many small nudges toward one vendor/choice).
   - **Behavioral context:** did the burst coincide with a first-run/setup flow, a bulk import ("remember all of these"), or a long web-research session? The session log (external, per learn-observability) is the alibi — legitimate bursts have one.
3. **Slow-burn variant:** the tripwire also maintains a **28-day rolling view** [DC]: small daily write counts that are individually under threshold but cumulatively anomalous for the topic/tier cell. This is the CUSUM-flavored detector (accumulate deviations from the baseline write rate per (topic, tier) cell; alert when the cumulative sum crosses threshold — the classical sequential change-detection primitive, borrowed from the drift literature's playbook [SEI CMU, HC — drift detection as sequential monitoring]).

**Trigger:** every tripwire flag is investigated at the next audit boundary (nightly for quarantine-heavy flags, weekly for volume flags). The 28-day slow-burn view is recomputed weekly.

**Cost:** clustering a burst's writes is trivial (tens of memories); the 28-day view is O(writes in window) embedding-aggregations — minutes. The expensive part is only the *judgment* on ambiguous cases, which is deferred to the user via the report (§5), not spent as LLM compute guessing.

**Action-on-failure (attack verdict):** the burst's memories are **batch-quarantined** (one quarantine event citing all memory IDs — not N separate quarantines), the write-log entries are annotated with the forensic verdict, an integrity-style user alert fires (attack verdicts interrupt quiet success, like chain breaks), and the scanner's pattern library gains the burst's signature (the hardened_runner regression loop: new attack class → new screen pattern → triggers check (a)'s version-bump re-screen). **Action on legitimate verdict:** mark closed-benign with the alibi cited; the burst's writes keep their gate outcomes. **Action on ambiguous:** keep the memories but **shorten their `review_at`** (watch-list) — the audit's version of "trust but verify," and the honest middle between false accusation and blind trust.

---

## 3. Scheduling and budgeting: when the immune system runs

### 3.1 The DREAM phase: the audit's home

The audit runs during **idle/low-activity windows** — the DREAM phase. The shape is borrowed from the field's converged pattern:

- **OpenClaw's Dreaming**: Light phase (ingest, dedupe, stage, record signals) → REM phase (extract themes, reinforcement signals) → Deep phase (score, threshold, promote to MEMORY.md), run by cron during off-hours [dev.to/czmilo, SP].
- **Sleep-Time Compute**: the four-gate trigger (time ≥ 24h, sessions ≥ 5, scan throttle, filesystem lock) ordered cheapest-first so most invocations bail early [claude-wiki.com, HC].
- **Spraphul's dreaming doctrine**: *"capture experience quickly but learn from it slowly"*; LLM proposes, evals and governance activate; retire stale lessons, merge duplicates, narrow overgeneralized rules, preserve rollback paths [spraphul.github.io, HC].

**JARVIS's audit maps onto this in two cadences:**

| Cadence | Window | Checks | Purpose |
|---|---|---|---|
| **Nightly micro-audit** | Idle window (default 03:00 local [DC]; skipped if the user is active — the audit never competes with the user for the machine) | (d) chain walk + 24h reconciliation; (b) provisionals due today (≤K); (e) staleness due today (≤K); (f) tripwire flags since last run; (a) only if scanner version bumped | Keep the foundations verified daily; amortize the expensive checks so the weekly run never faces a cliff |
| **Weekly full audit** | Weekend idle window (default Sunday 03:00 [DC] — the FlatNine REM cadence [flatnine.co, SP]) | All six checks: full (a) stratified sample, (b) treadmill + rent-audit sample, (c) delta sweep (full sweep monthly/post-incident), (d) full chain walk + orphan scan, (e) missing-window sweep, (f) 28-day slow-burn view | The deep clean; produces the weekly audit report (§5) |

**Trigger gating (cheapest-first, per the sleep-time-compute pattern):** the audit scheduler checks in order — (1) is the machine idle (no active session, CPU below threshold)? (2) is there anything due (provisionals/staleness queues non-empty, or ≥7 days since last full audit)? (3) is the audit lock free (no concurrent run)? Most nights the micro-audit bails at step 2 in seconds — the audit costs nothing when there's nothing to check. This is the bounded-rationality move: *the cheapest audit is the one that correctly decides not to run.*

**The audit never blocks the user.** It runs at background priority, pauses on user activity (voice wake or active session → checkpoint and suspend, resume next idle window), and its partial results are valid — every check is resumable from its last checkpoint (each check records `last_processed_seq`; a suspended run resumes, never restarts).

### 3.2 The ≤5% budget rule (from learn-bounded-rationality)

Metalevel work — thinking about thinking, auditing memory rather than using it — is bounded: **the audit may spend at most 5% of total compute** (the bounded-rationality metalevel cap). Operationalized:

- Each audit run gets a **compute budget** (token/time envelope [DC]: nightly ≤ 15 min wall-clock at background priority; weekly ≤ 2 hours). The budget is enforced by the scheduler, not by the checks' goodwill.
- Checks are **priority-ordered**; when the budget exhausts, remaining checks **defer to the next cycle** and the deferral is logged in the report (the report says what *didn't* run — an audit that silently skips checks is a liar).
- Priority order within a run: **(d) reconciliation → (f) burst forensics → (a) re-screening → (b) provisional treadmill → (c) contradiction sweep → (e) staleness review.** Integrity first (a poisoned log poisons every other check's inputs), security second, then evidence quality, then consistency, then freshness. The ordering encodes the same value judgment as the gate's eviction order: *integrity is the most expensive thing to lose.*
- **Expected-value gating per check:** the nightly bails when queues are empty (§3.1); the sweep skips quiet weeks (§2.3); re-screening samples rather than exhausts (§2.1). Every check has a "don't run" condition — the audit is satisficing, not exhaustive. Exhaustive auditing of a growing store is the unbounded-compute trap the 5% rule exists to prevent.

### 3.3 Prioritization: riskiest memories first

Within each check, memories are processed in **risk order**, not insertion order. The risk score [DC design]:

```
risk(m) = tier_weight(m.provenance_tier) × stakes_adjacency(m.topic)
          × recency_boost(m.last_conflict_or_flag)
          × retrieval_frequency(m)
```

- `tier_weight`: T3 = 1.0, T2 = 0.6, T1 = 0.3, T0-world = 0.2, T0-user = 0.05. (T3-heavy by construction — the stratification in §2.1 is this weight made into a sampling plan.)
- `stakes_adjacency`: 1.0 if the memory's topic touches health/finance/security (R3-adjacent), 0.5 for R2-adjacent, 0.2 otherwise. A poisoned trivia fact is a nuisance; a poisoned medication fact is a catastrophe — the audit spends accordingly.
- `recency_boost`: memories flagged or conflicted in the last 30 days get a multiplier (2.0 [DC]) — past infections predict future ones, and recently-conflicted memories are where the store is already known to be uncertain.
- `retrieval_frequency`: retrieved-and-used often = higher blast radius if wrong. (The ECAN refresh log supplies this — the audit reads the rent ledger, closing the loop between retention economics and audit priority.)

**The audit is adversarially aware of its own prioritization:** a patient attacker could in principle keep writes low-tier-weight and low-frequency to stay below the audit's attention — that is exactly the slow-burn case, and it is why §4's distributional analysis exists *alongside* risk-ordered checking. Risk ordering catches the acute; distribution analysis catches the chronic. Neither alone suffices.

---

## 4. Slow-burn poisoning: the adversary the gate can't see

### 4.1 The threat, precisely stated

Slow-burn poisoning is **many small individually-plausible writes that together shift behavior** — preference shaping. Each write passes every gate: the text is plausible, the scanner is clean, the tier is honest (often T0-behavioral: the "evidence" is real user interactions), the budget has room. The attack is visible only in **aggregate, over time**: the *distribution* of writes drifts in a consistent direction.

Concrete shape: over 5 months, 6–8 small memories accumulate — "user asked about VendorV's product," "user compared VendorV favorably," "user chose VendorV's integration twice" — each true-ish, each minor. The store's preference centroid for the category migrates from neutral to VendorV. When the user later asks "which tool should I use?", retrieval returns a VendorV-tilted evidence set, and the answer tilts. No single write was wrong. The *composition* is the attack. (Forcepoint's taxonomy: the attacker's goal is "long-term behavioral drift," optimizing "what the agent will believe weeks or months later" [forcepoint.com, HC].)

The write-gate file already confesses this: *"No point check catches a patient attacker building DEMONSTRATED preferences over months"* [MEM-WRITE-GATE §9.3, UK]. This section designs the detection — and marks exactly where detection ends and honesty begins.

### 4.2 The detection design: distributional analysis of write patterns

The audit maintains a **write-history time series**: every write (all outcomes, including DROPs and QUARANTINEs — refused writes are signal too) is binned by week into a (topic-cluster, provenance-tier, memory-type) contingency table. Topic clusters come from embedding clustering of memory texts (the same HDBSCAN/LSH machinery as §2.3's B2 blocks — one clustering serves both checks). Four analyses run over this series weekly:

**Analysis 1 — Topic/tier distribution shift (the PSI/JSD watch).** Compare this week's write distribution against a rolling baseline (prior 8 weeks [DC]) using Population Stability Index / Jensen-Shannon Divergence — the standard production-drift instruments [SEI CMU; fiddler deepwiki, HC]. A PSI spike in a (topic, tier) cell means the *composition* of what's being learned changed. Legitimate cause: the user started a new project (topic shift, T0-heavy). Suspicious shape: topic shift *with tier concentration* (many writes, one topic, T3-provenance) — the single-source injection pattern wearing a slow-burn costume.

**Analysis 2 — Provenance concentration (the Gini watch).** Within each topic cluster, compute the concentration of *sources* behind recent writes (Gini coefficient over source identity [DC]). Organic learning is source-diverse: the user encounters a topic across conversations, tools, and web reads. Shaping is source-concentrated: many small writes traceable to one origin (one document read repeatedly, one conversation thread, one tool's outputs). High concentration + consistent direction = investigate.

**Analysis 3 — Drift direction (the CUSUM watch on preference centroids).** For preference-type memories, track the embedding centroid of each topic cluster's preferences over time, and the *direction* of its movement. CUSUM (cumulative sum of deviations from the baseline direction) is the classical sequential detector for slow shifts — small per-step deviations that accumulate past threshold [standard sequential-analysis primitive, HC]. The signal isn't "preferences changed" (they do, legitimately) but **"preferences moved monotonically in one direction for N consecutive windows with concentrated provenance"** — monotonic + concentrated is the shaping signature; oscillating or diversely-sourced movement is organic evolution.

**Analysis 4 — Fragmentation assembly (the ShieldCortex pattern).** Cross-reference recent writes for **assembly patterns**: individually-innocent memories that *compose* into an attack chain when read together (the "Fragmentation Detector" concept — *"catches multi-step assembly attacks spread across days"* [dev.to/mkdelta221, SP — practitioner design, mechanism sound]). Operationalized: for each new memory, retrieve its top-k semantic neighbors *across time* (not just recent) and test the *set* — do the neighbors plus the new memory jointly entail an instruction, a credential-adjacent fact, or a preference the individual members don't? The NLI classifier judges the set, not the pair. This is the memory-level analog of the burst-forensics laser-focus test, extended across weeks.

**The behavioral-drift backstop (BDI-style).** The fafi25 guide's Behavioral Drift Index — *"cumulative personality or policy changes using sliding window analysis"* with the explicit note that *"sophisticated attacks introduce changes gradually to evade sudden-change detection; BDI's cumulative measurement catches these slow corruptions"* [fafi25.substack.com, SP] — is implemented as a fifth signal: track the agent's *behavioral* outputs (not just its writes) for drift — refusal-rate deviation (±15% alert threshold per the guide), retrieval-influence (are retrieved memories dominating outputs beyond the <20% baseline?), and action-distribution shift. If the *writes* look clean but *behavior* drifted, the poisoning may be in the retrieval/ranking layer rather than the store — the audit reports the discrepancy and points at the ranker, not the memories.

### 4.3 The honest limits (what's fundamentally hard)

Stated plainly, because an immune system that overclaims is worse than none:

1. **The ground-truth problem [UK].** A preference drift toward VendorV is *indistinguishable from genuine preference formation* without access to the user's actual mind. If the user really did come to prefer VendorV over 5 months of real usage, every distributional signal fires identically to the attack case. The audit can detect *the shape* (monotonic, concentrated, directional); it cannot certify *the cause*. **The user is the oracle.** The audit's terminal action on suspected shaping is therefore always *surfacing for user review* (§5), never auto-quarantine of legitimate-looking preferences. Auto-quarantining a genuine preference because its statistics looked attack-shaped would be the immune system attacking the body — the autoimmune failure, and it is forbidden by design.
2. **Adversarial adaptation [UK].** A sophisticated attacker who knows the detectors can shape *below* them: diversify sources (defeats the Gini watch), keep drift sub-CUSUM-threshold (defeats the direction watch), interleave with organic topics (defeats the PSI watch). This is the standard arms-race caveat from the drift literature — detectors raise the attacker's cost; they don't eliminate the attack. The honest claim: the audit makes slow-burn poisoning *expensive* (it forces the attacker to be slow, diverse, and subtle — which bounds the damage rate), not impossible.
3. **The base-rate problem [MC].** Genuine preference evolution is common; shaping attacks are (presumably) rare. Any detector with a non-trivial false-positive rate will mostly flag genuine evolution — the classic base-rate fallacy applied to security alerting. Mitigations: the audit's shaping flags are *low-severity, batched, user-review* items (not alarms), and the report tracks the flag-to-confirmation ratio as its own calibration metric. If users dismiss 95% of shaping flags, the thresholds are wrong — the audit tunes itself from the dismissals.
4. **Long-tail subtlety [UK].** Below a certain effect size, no statistical test distinguishes shaping from noise — this is information-theoretic, not a detector weakness. The audit's claim is bounded: it catches *behaviorally-significant* drift (drift large enough to change answers), not *arbitrarily small* drift. Drift too small to change any answer is, by definition, harmless *today* — though it compounds, which is why the CUSUM accumulates rather than thresholding per-window.
5. **The "user was manipulated upstream" case [UK, inherited from MEM-WRITE-GATE §9.5].** If the user states a preference *because* of injected content they read elsewhere, the T0 utterance is sincere and the distributional signals read it as organic (it *is* organic — the poisoning happened upstream of the agent, in the user's own information diet). The audit cannot see upstream of the user. Flagged, not solved — same as the gate.

**The net honest claim [HC]:** the audit detects *distributional anomalies with shaping-shaped signatures* and routes them to the one oracle that can resolve them — the user. It raises the cost of slow-burn attacks (forcing slowness, diversity, and subtlety, which bounds damage rate) and it catches the *unsophisticated* slow burn (the common case: concentrated, monotonic, directional). It does not certify preferences as "genuinely yours." Nothing in the studied literature claims to solve that; neither do we.

---

## 5. The audit report: what the immune system produces

### 5.1 The machine-readable report (spec)

Every audit run — nightly micro or weekly full — emits a report. The report is a **candidate memory of type LESSON** and goes through the write gate like everything else (Cycle 13 §6.2 Layer 4 requires this: *"The audit report is itself a candidate memory… The system watches itself through the same valve"*). A report the gate refuses (over budget, malformed) is itself a finding.

```json
{
  "report_id": "audit-2026-10-19-weekly",
  "run_type": "weekly-full",
  "started_at": "2026-10-19T03:00:00+05:30",
  "completed_at": "2026-10-19T03:47:12+05:30",
  "chain_verified": true,
  "checks": [
    {
      "check": "rescreening",
      "scope": {"strata": {"T3": 200, "T2": 125, "T1": 100, "T0-world": 50, "quarantine": 25}, "scanner_version": "2.3.0"},
      "examined": 500,
      "findings": ["F-001"],
      "actions": ["A-001"],
      "cost_ms": 41230,
      "deferred": null
    }
  ],
  "findings": [
    {
      "finding_id": "F-001",
      "check": "rescreening",
      "severity": "high",
      "kind": "tier-downgrade",
      "memory_ids": ["mem-8841"],
      "details": "Scanner v2.3.0 pattern 'obfuscated-instruction-unicode' fires on mem-8841 (screened clean under v1.9). Tier T3→T4-equivalent.",
      "evidence_refs": ["log-seq:41207"]
    }
  ],
  "actions": [
    {
      "action_id": "A-001",
      "action": "quarantine",
      "memory_ids": ["mem-8841"],
      "finding_ids": ["F-001"],
      "reversible": true,
      "undo_ref": "log-seq:41209",
      "gate_outcome": "QUARANTINE"
    }
  ],
  "summary": {
    "writes_7d_by_tier": {"T0": 31, "T1": 4, "T2": 12, "T3": 9, "T4": 2},
    "quarantines": 3, "promotions": 2, "demotions": 4, "conflict_records_opened": 1,
    "orphans_found": 0, "chain_breaks": 0, "burst_flags_investigated": 2,
    "burst_verdicts": {"benign": 1, "attack": 0, "ambiguous-watchlist": 1},
    "provisionals_due": 7, "provisionals_processed": 7,
    "checks_deferred_for_budget": []
  }
}
```

**Schema notes:**
- `chain_verified` is first because every downstream field is untrustworthy if it's false (fail-closed ordering, §2.4).
- `checks[].deferred` names what *didn't* run when the budget exhausted — the report's honesty field.
- Every action carries `undo_ref` → the write-log sequence of the reversal event template (CONFLICT-RES §7's reversibility requirement, applied to audit actions too).
- `summary` is the week-over-week trendable surface — the metrics pipeline (§5.3) ingests it directly.

### 5.2 The human-readable digest (quiet success is the norm)

The digest is **surfaced to the user only if action is needed**. The routing:

| Finding class | User-visible? | How |
|---|---|---|
| Chain break / integrity event | **Yes, immediately** | Alert (not a notification-to-dismiss — the one audit event that interrupts) |
| Burst-forensics attack verdict | **Yes, same session or next** | Alert with the batch-quarantine summary and the evidence |
| Suspected preference shaping (§4) | **Yes, batched** | Review card, piggybacked on the topic (CONFLICT-RES §5.2's "piggyback, don't interrupt" rule — the shaping card about VendorV appears when the user next asks about the category, not on Tuesday morning) |
| Quarantine of a memory the user has *retrieved recently* | **Yes** | One-line note: "I quarantined a memory you'd seen — here's why" (the memory influenced their past answers; they deserve to know it was bad) |
| Promotions / demotions / routine re-screens | **No** | Logged in the machine report; visible in the memory viewer (MEM-SPEC §9) for anyone who looks |
| "All clear" weekly | **No** | Quiet success. No "audit complete, everything fine" notification — that trains the user to ignore the channel the real alerts need |

**The digest's voice contract:** findings are stated as *what the audit did and why*, with the evidence attached, never as accusations. "I found 6 small preference notes about VendorV added over 5 months, all tracing to one source. This *could* be you genuinely coming around to it — is it?" The shaping card always includes the genuine-evolution hypothesis alongside the attack hypothesis, because the base-rate problem (§4.3.3) says genuine evolution is the likelier explanation and the UI must not cry wolf.

### 5.3 Observability wiring (the audit as a scheduled job)

The audit is a scheduled job with metrics — it plugs into learn-observability's metric set directly:

| Metric | Type | Purpose |
|---|---|---|
| `audit_runs_total{run_type, outcome}` | Counter | Did the audits run? (A scheduled job that silently stops is the meta-failure — the watchdog from learn-observability §4 watches the *auditor*.) |
| `audit_duration_seconds{run_type}` | Histogram | Budget adherence — is the weekly audit staying inside its 2h envelope? |
| `memories_rescreened_total{stratum}` | Counter | Coverage over time — is the T3 stratum actually being re-screened? |
| `audit_reclassifications_total{kind}` | Counter | kinds: tier-downgrade, promote, demote, quarantine, conflict-opened, orphan, tombstone |
| `write_log_chain_verifications_total{result}` | Counter | result ∈ {ok, break} — the integrity heartbeat |
| `audit_orphans_found_total` | Counter | Gate-bypass detector's hit count — should be ~0; a non-zero trend is the emergency |
| `burst_investigations_total{verdict}` | Counter | verdict ∈ {benign, attack, ambiguous} |
| `provisionals_due_gauge` / `provisionals_overdue_gauge` | Gauge | Treadmill health — a growing overdue queue means the nightly K cap is too small |
| `shaping_flags_total{user_verdict}` | Counter | user_verdict ∈ {confirmed, dismissed, pending} — the §4.3.3 calibration metric; dismissed ≫ confirmed → retune thresholds |
| `checks_deferred_for_budget_total{check}` | Counter | Which checks starve — the 5%-rule pressure gauge |

**The watchdog watches the watcher:** if `audit_runs_total` shows no weekly run for >9 days, the system health check (learn-observability §4) raises a degradation flag — *"memory audit overdue"* — because an immune system that silently stops is indistinguishable from no immune system. The audit's own liveness is a first-class health signal.

**Retention:** machine reports are kept 1 year (they're small — KB each); the write log is kept per the log-retention policy (learn-observability §2's open question, default 90 days [DC] for full payloads, tombstone index indefinitely). The chain anchors (§2.4) are kept indefinitely — they're hashes, not content.

---

## 6. Worked example: a 6-month-old store, one weekly audit, three findings

**The store:** ~4,200 memories accumulated over 6 months. Weekly full audit runs Sunday 03:00. Chain verifies clean (Direction 3, 4,187 entries, no gaps — 40 seconds). Reconciliation Directions 1–2 clean (no orphans, no missing memories). The interesting findings come from checks (a), (c), and (f)/§4.

### Finding 1 — (a) Re-screening: the T3 health claim that never got corroborated → demoted to conflict record

**The memory:** `mem-1207` — "Ashwagandha is safe for daily use," FACT, T3 (health blog), written 5 months ago as a CONFLICT-RECORD candidate that the gate downgraded to… no — re-read the gate trace: at write time it *became* a conflict record per MEM-WRITE-GATE §7 example (c). But this store's history differs: 5 months ago the gate's conflict quota was exhausted that day, so it entered as **WRITE-PROVISIONAL** (confidence 0.35, `review_at` set, evidence: single blog quote). The provisional treadmill (§2.2) has extended it twice — no corroborating T1/T2 ever arrived.

**The audit:** re-screening's T3 stratum samples mem-1207. Two things are new since write time: (1) scanner v2.3 added the `incentive-seller-health-claim` pattern — the blog's outbound affiliate links to a supplement vendor now trip it (verdict: suspicious, was: clean); (2) the provisional treadmill's third extension is due — the "extend 3 times then demote" rule fires.

**Action:** tier downgrade T3→T4-equivalent on the new verdict + treadmill demotion. Per the gate's tier table, T4-health-claim → not storable as fact at any confidence. The audit writes it as a **CONFLICT-RECORD**: {claim: "ashwagandha safe for daily use," provenance: T3→T4 (affiliate-incentivized source, scanner v2.3), status: uncorroborated, needed: T1 or professional guidance, created: audit-2026-10-19}. The provisional memory is superseded by the record (validity window closed, `superseded_by` set — the bi-temporal trail preserved). **User-visible?** R3-adjacent and previously retrievable → yes, one-line note: the memory viewer shows the conflict record; no interrupt (the user hasn't asked about ashwagandha in months — piggyback rule: it surfaces if they ask).

**What this catches that the gate couldn't:** the gate made the right call *at the time* (provisional, not fact). But provisionals are bets, and bets expire — without the treadmill, mem-1207 would sit at confidence 0.35 *forever*, retrieved as a low-confidence "fact" (the exact move CLAIM-VER bans). The audit enforces the expiry the gate scheduled but couldn't execute.

### Finding 2 — (f) + §4: slow drift toward a vendor's product → flagged for user review (possible shaping)

**The memories:** six preference-type writes over 5 months, all in the "note-taking / PKM tools" topic cluster:
1. "User asked about VendorV's sync feature" (T0-behavioral, month 1)
2. "User compared VendorV favorably to CompetitorC on sync speed" (T0-behavioral, month 2)
3. "User chose VendorV's template gallery twice" (T0-behavioral, month 3)
4. "User asked whether VendorV supports offline mode" (T0-behavioral, month 4)
5. "INFERRED: user prefers VendorV for note-taking" (provisional, month 4 — promoted to DEMONSTRATED at month 5 when instance 6 arrived: "user opened VendorV daily for a week")

**The audit:** Analysis 3 (drift direction) fires — the topic cluster's preference centroid moved monotonically toward VendorV across 5 consecutive monthly windows. Analysis 2 (provenance concentration) fires harder: all six writes trace to **one origin** — a single long VendorV documentation deep-dive session in month 1, plus the user's subsequent *usage* of VendorV. Analysis 1 (PSI) shows the topic cell's write composition shifted T0-behavioral-heavy (not tier-suspicious — the tier is honest). The fragmentation check (Analysis 4) finds no assembly pattern — no hidden instruction composes from the set.

**The honest read:** every signal is consistent with *both* genuine preference formation (the user tried VendorV, liked it, kept using it — the most likely story) *and* slow-burn shaping (a concentrated exposure pattern nudging the store's centroid). The provenance is T0-behavioral — the user's real actions. There is no attacker in the evidence; there is only a *shape*.

**Action:** **flag for user review — not quarantine.** The audit does not touch the DEMONSTRATED preference (autoimmune prohibition, §4.3.1). It emits a shaping-review card, piggybacked: the next time the user asks about note-taking tools, the card appears — *"Quick check: your saved preferences have drifted toward VendorV over the last few months, mostly from one deep-dive session back in May. Is VendorV still your pick, or was that a phase?"* — with one-tap actions: "still my pick" (dismisses the flag, records `user-confirmed`, strengthens the preference legitimately), "not anymore" (demotes to INFERRED, re-opens the question), "show me the notes" (the six memories, with provenance). The flag and the user's verdict both go in the report (`shaping_flags_total{user_verdict}` — the calibration metric).

**What this catches that nothing else could:** no gate, no screen, no classifier fires on any individual write — each is true, T0, and benign. Only the *longitudinal distribution* has the shape. And the resolution respects the ground-truth problem: the system asks the oracle instead of convicting the data.

### Finding 3 — (c) Contradiction sweep: two DEMONSTRATED preferences collide → conflict record, resolution deferred to user-arbiter

**The memories:**
- `mem-0931` — "User prefers concise answers," PREFERENCE, DEMONSTRATED (stated once by user T0 + 40+ corroborating chat turns, high entrenchment, 8 months old).
- `mem-3410` — "User wants detailed explanations," PREFERENCE, DEMONSTRATED (promoted last month: three "explain in detail" follow-ups across separate sessions, all in technical threads, T0-behavioral).

**Why the gate missed it:** at write time, mem-3410's embedding sat at cosine ~0.71 to mem-0931 — *below* the gate's 0.75 near-duplicate band. "Prefers concise" vs "wants detailed explanations" are lexically distant (antonyms don't embed near each other reliably) despite being logically contradictory. The sub-threshold miss, exactly as CONFLICT-RES §2.2 mechanism 1 predicts.

**The audit:** the delta sweep's B3 block (ANN neighborhood, threshold 0.70 — deliberately below the gate's 0.75) pairs them. The 3-way NLI classifier returns **contradiction** (high confidence — this is the easy case for NLI: direct antonymic opposition in the same slot). B2 (type + topic cluster) independently pairs them — both PREFERENCE, both in the "answer-style" cluster. Two blocks agreeing raises the finding's priority.

**Action:** open a **CONFLICT-RECORD** (type c, R1): parties = {mem-0931 (T0 stated + 40-turn corroboration, entrenchment high), mem-3410 (T0-behavioral, 3 instances, technical-thread-scoped)}, status `open`, detected_by: sweep. **No auto-resolution** — the audit detects, the CONFLICT-RES workflow resolves. The record is marked `awaiting-user` per the c/R1 adjudication path (provenance audit → scope-or-escalate), and per the UX rules it surfaces **piggybacked**: the next time the user asks a technical question where both preferences would fire, the one-question card appears — "Concise as usual, or detailed for this one?" with the third option "detailed for technical topics" (the scoping resolution made tappable, CONFLICT-RES §5.2). Either tap writes back via the resolution workflow; "not now" defers with a 30-day `review_at`.

**What this catches that the gate couldn't:** the gate's similarity threshold is a line; reality is graded. The sweep's below-threshold B3 block exists *because* the gate's line is known to miss antonymic contradictions. Defense in depth means the second layer is deliberately tuned to catch the first layer's known blind spot — not just "more of the same checking."

---

## 7. Integration map: the audit in the full defense-in-depth

```
                        ┌─────────────────────┐
                        │   WRITE GATE (13)    │  front door: point checks,
                        │  6 gates, budgets    │  provenance tiers, quarantine
                        └────────┬────────────┘
                                 │  every outcome → append-only
                                 ▼  hash-chained WRITE LOG
┌──────────────┐        ┌─────────────────────┐        ┌──────────────┐
│ SOURCE TRUST │───────▶│   MEMORY STORE       │◀──────│ CONFLICT-RES │
│ (12) tiers,  │ screen │  main / provisional /│ record │ (14) adjudicate│
│ corroboration│versions│  quarantine / history │        │ scope/escalate │
└──────────────┘        └────────┬────────────┘        └──────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   AUDIT (15, this file)  │  immune system:
                    │   6 checks, DREAM phase, │  re-screen, re-corroborate,
                    │   ≤5% budget             │  sweep, reconcile, de-stale,
                    │                          │  burst forensics, drift watch
                    └────────────┬────────────┘
                                 │  findings → gate → log
                                 ▼  (no privileged writes)
                    ┌────────────────────────┐
                    │  AUDIT REPORT           │  machine JSON (→ gate as
                    │  machine + human digest  │  LESSON) + human digest
                    │  + observability metrics │  (only if action needed)
                    └────────────────────────┘
```

The four layers of Cycle 13's poisoning resistance are now all designed: (1) tier minimums + provenance-carried verdicts (gates 3, §6.2 layers 1–2), (2) structural rules (layer 3), (3) burst tripwire (layer 3), **(4) the periodic audit (this file)**. The chain is complete: **gate → trust → resolution → audit**, with the write log as the shared spine and the report feeding back through the gate.

Three invariants hold across the whole stack:
1. **No silent writes, anywhere.** The gate logs, the audit logs, resolutions log, the audit's own report goes through the gate. There is no privileged path into the store — that is what makes the store auditable at all.
2. **Provenance is never discarded.** The injection verdict travels with the memory from gate to store to audit to re-screen; version-stamped verdict histories make re-screening incremental.
3. **The user is the final oracle for their own mind.** Preferences are never auto-quarantined on statistical suspicion; shaping flags are review cards, not convictions; erasure is complete and honored everywhere including the audit's own records.

---

## 8. Open problems and unknowns

1. **Threshold calibration [UK].** The stratification ratios (40/25/20/10/5), the 0.70 sweep threshold, the 28-day slow-burn window, the 8-week PSI baseline, the 90/180-day treadmill clocks, the nightly K=25 cap, the 03:00 windows — all [DC], none measured. They must be calibrated against real usage, and the calibration process itself should be audit-logged (the audit tuning its own parameters from the `shaping_flags_total{user_verdict}` and dismissal ratios — the immune system learning, per the cog three-gate spirit).
2. **NLI classifier transfer to memory/memory contradiction [UK, inherited from MEM-WRITE-GATE §9.2].** The sweep's B3/B4 blocks assume the 3-way head separates contradict/entail/neutral on memory-text pairs. CLAIM-VER's numbers (AlignScore 88.6 AUC vs MNLI 48) are for chunk/claim grounding, not memory/memory. The sweep needs its own labeled eval set (memory pairs, human-judged) before its contradiction precision is trusted — until then, sweep-opened conflict records should carry a `detector-confidence` and low-confidence opens should be batched for the monthly human-eyeball sample, not auto-filed.
3. **The autoimmune boundary [UK].** The prohibition on auto-quarantining legitimate-looking preferences is stated as design law, but its *edge* is untested: what about a DEMONSTRATED preference whose provenance is T3-concentrated *and* whose behavioral evidence is thin (2 instances, both from one session)? The design says "flag, don't quarantine" — but at some concentration level the expected value flips. That level is unmeasured; the `shaping_flags` calibration metric is the instrument that will find it.
4. **Audit-of-the-audit [SP].** Who verifies the verifier? The report-goes-through-the-gate rule covers the report's *admission*; it doesn't cover the audit's *correctness* (a buggy check that never fires is invisible). The watchdog-on-`audit_runs_total` covers liveness, not correctness. The missing piece: a **canary set** — synthetic memories with known defects (a planted contradiction, a stale fact, an orphan) injected into a shadow namespace, verifying the audit *finds* them each cycle. Designed here as a requirement, not a mechanism — the mechanism is a future cycle.
5. **Cross-user propagation [UK, inherited].** The audit is per-user; a shared/team store needs per-writer provenance and writer-aware concentration analysis (a shaping campaign could distribute across writers). Not designed here.
6. **Anchor security for the hash chain [MC].** The periodic-anchor defense (§2.4) assumes the anchor store (session log / anchor file) is on an independent durability path from the write log. If both live on the same disk under the same process, a sufficiently privileged attacker rewrites both. The honest bound: the chain defeats bugs, sloppy edits, and partial attacks; it does not defeat root. Stated, not solved.
7. **Compute reality of the weekly full audit [UK].** The 2-hour envelope and the ≤5% rule are design constraints awaiting measurement against the real store size, embedder throughput, and NLI batch latency on the target hardware (RTX 2060 / Ryzen 5 3600). The first three weekly audits should be instrumented as calibration runs, with the report's `cost_ms` fields as the data source.

---

## 9. References

**Prior cycles (this project):**
- learn-memory-write-gate.md (Cycle 13): six gates, outcome taxonomy, poisoning-resistance layers 1–3, ECAN rent, write budgets, burst tripwire. *This cycle designs layer 4.*
- learn-conflict-resolution.md (Cycle 14): conflict taxonomy (a–e), resolution workflow, audit-trail spec with rollback, user-arbiter UX.
- learn-source-trust.md (Cycle 12): T0–T4 tiers, corroboration rule, independence test, injection screen, fail-open/fail-closed map.
- learn-claim-verification.md (Cycle 11): 4-rung verification ladder (reused for re-verification), abstention discipline, NLI accuracy bounds.
- learn-memory-spec.md: two stores, quarantine gate, ECAN-lite tiers, 13-item deletion checklist, durability clauses.
- learn-observability.md: metric set, structured logging, health checks, watchdog, crash recovery.
- learn-bounded-rationality.md: the ≤5% metalevel-compute rule, satisficing, deliberation costs inside rationality.
- learn-causal-discovery.md: post-mortem template, failure clustering.
- MASTER-INDEX.md: M1 (A-MEM evolution), M2 (Nocturne sleep consolidation), M5 (gate → evolution → idle-verification composition).

**Field — memory poisoning & detection (real, fetched this cycle):**
- Forcepoint X-Labs, "Persistent Memory Poisoning: An Agentic AI Risk" — https://www.forcepoint.com/blog/x-labs/persistent-memory-poisoning-ai-agents (attack model "remember this and act later"; lifetime/persistence/trigger/detection/impact table; attacker target list incl. "a preference that weakens security") [HC]
- Arthur, "Memory and State Poisoning in Long-Running Agents" — https://www.arthur.ai/column/memory-and-state-poisoning-in-long-running-agents ("by the time it does damage, the turn that planted it is long gone"; agent doesn't distinguish legitimate vs planted entries) [HC]
- fafi25, "Memory Poisoning in AI Agents: Detection & Prevention Guide (2026)" — https://fafi25.substack.com/p/ai-memory-poisoning-detection-prevention-guide (IES/refusal-rate/retrieval-influence/BDI metrics; BDI sliding-window cumulative measurement catches gradual corruptions; thresholds are starting points) [SP]
- cybersecpentesting.com, "AI Agent Memory Poisoning: Persistent Agent Attacks" — http://cybersecpentesting.com/blog/ai-agent-memory-poisoning.html (maturity levels; provenance → detection → validation cumulative; public Gemini/SafeBreach demonstrations) [HC]
- ShieldCortex design (dev.to) — https://dev.to/mkdelta221/we-found-5-ways-to-poison-ai-agent-memory-heres-how-we-stop-them-4e11 (5 layers incl. Fragmentation Detector for multi-step assembly across days; trust scoring user=1.0/web=0.3/agent=0.1; audit logging of every memory op) [SP — practitioner design]
- sentia.community, "AI Memory Poisoning: The Hidden CRM Risk" — https://sentia.community/ai-memory-poisoning-what-is-the-hidden-crm-risk-behind-ai-agents/ (four reliability primitives: lineage, glossary, freshness, ownership; temporal trust scoring Trust = e^(−λt) × Source_Authority; 30-day TTL on untrusted memory) [SP]
- news.aibase.com, Microsoft warning on poisoned share buttons — https://news.aibase.com/news/25489 (covert manipulation via URL params; "invisible manipulation"; recommendation to regularly clear assistant memory) [HC]
- ZeroFox (via SRC-TRUST): fake support numbers on .edu/.gov — the borrowed-credibility case re-screening targets [HC, via prior cycle]
- Lily Ray "AI Slop Loop" (via SRC-TRUST): repetition-as-consensus — the reason unevidenced provisionals must expire, not accumulate [HC, via prior cycle]

**Field — drift detection (real, fetched this cycle):**
- CMU SEI, "Expecting the Unexpected: Monitoring for Drift in ML Systems" — https://www.sei.cmu.edu/blog/expecting-the-unexpected-monitoring-for-drift-in-ml-systems/ (drift detectors as CISA tech of interest and DoD OT&E required step; distribution monitoring vs performance monitoring; unlabeled-data feature monitoring) [HC]
- Fiddler deepwiki, drift detection & imbalanced data — https://deepwiki.com/fiddler-labs/fiddler-examples/2.2-drift-detection-and-imbalanced-data (data drift vs concept drift; JSD/PSI against baselines; rolling baselines) [HC]
- neuralwired.com model-drift survey — https://neuralwired.com/2026/06/17/model-drift-zillow-ml-monitoring-2026/ (PSI/KS for input drift; trigger-based retraining; semantic drift in LLMs as least-solved 2026 problem) [MC]

**Field — tamper-evident logging (real, fetched this cycle):**
- chainlog (dev.to) — http://dev.to/vinod_patil_a7bd8dcbcc42e/session-recordings-are-not-evidence-until-you-can-prove-nobody-touched-them-2f2o — cited for the tamper-evident-not-tamper-proof honest limit [HC]
- "How We Built a Tamper-Evident Audit Log for SOC 2" (dev.to) — https://dev.to/gentlyding/how-we-built-a-tamper-evident-audit-log-for-soc-2-and-iso-27001-evidence-jl4 (sequential hash chain construction record[n].hash = H(payload[n] || record[n-1].hash); cryptographic erasure for GDPR without breaking the chain) [MC]
- TheWARDN audit trail & hash chain — https://docs.thewardn.ai/concepts/audit-trail.html (hash-chained governance records; single-authority chain as tamper-evident without consensus overhead) [HC]
- AI-agent SHA-256 chaining guide (dev.to) — https://dev.to/shipped_and_slept/how-to-add-tamper-evident-audit-logs-to-ai-agents-with-sha-256-chaining-16la (canonical JSON serialization for hashing; verify() walk localizing breaks) [MC]

**Field — sleep-time consolidation / DREAM phase (real, fetched this cycle):**
- Turing Post, "Continual Learning in LLMs: Why AI Models Need Sleep" — https://www.turingpost.com/p/continual-learning-llms-ai-models-sleep ("there needs to be a phase between seeing something and changing from it"; CMU/Maryland sleep-phase for KV-cache reasoning; Google Sleep paradigm: Knowledge Seeding + Dreaming) [HC]
- OpenClaw Dreaming Guide — https://dev.to/czmilo/openclaw-dreaming-guide-2026-background-memory-consolidation-for-ai-agents-585e (Light/REM/Deep phases; cron during off-hours; Dream Diary) [SP]
- Sleep-Time Compute (claude-wiki) — https://claude-wiki.com/sleep-time-compute.html (~5× test-time compute reduction via idle pre-computation; four-gate trigger ordered cheapest-first; minSessions gate) [HC]
- Spraphul, "How to Make Your Agents Dream" — https://spraphul.github.io/blog/how-to-make-your-agents-dream ("capture experience quickly but learn from it slowly"; LLM proposes, evals/governance activates; retire stale lessons, merge duplicates, preserve rollback) [HC]
- FlatNine, "AI REM" — https://flatnine.co/blog/ai-rem (weekly Sunday 03:00 dream consolidation; analysis → update phases; contradiction/staleness flagging; human correction loop) [SP]
- "Do AI Agents Need to Sleep?" (dev.to) — https://dev.to/shridhar_shah2297/do-ai-agents-need-to-sleep-i-built-one-that-does-53c4 (sleep as majority-vote over noisy facts; occasional wrong facts outvoted by the tally) [SP]

**Field — near-duplicate blocking at scale (real, fetched this cycle):**
- MinHash/LSH banding pipeline (apxml) — https://apxml.com/courses/how-to-build-a-large-language-model/chapter-7-data-cleaning-preprocessing-pipelines/near-duplicate-exact-duplicate-detection (shingling → MinHash → LSH banding; candidate pairs only; parameter tuning b/r per threshold) [HC — standard technique]
- FAISS + hierarchical clustering for dedup (dzone) — https://Dzone.com/articles/scaling-image-deduplication-finding-needles-in-a-haystack (ANN index for candidate generation; hierarchical clustering without pre-set k) [HC]

---
*Cycle 15 complete. Claim about this file: all numeric parameters (sample ratios, thresholds, windows, budgets, K-caps) are design choices tagged [DC] or inherited [SP]; all field observations are sourced above; all impossibility claims are tagged [UK] with the reason stated. The file contains no claim that the audit has been built, measured, or deployed — it hasn't. The immune system is designed, not yet alive.*
