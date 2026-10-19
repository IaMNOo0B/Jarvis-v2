# SRC-TRUST: Source Trustworthiness & Corroboration for JARVIS

**Cycle 12 — Phase Infinity research. Status: LEARNING ONLY — no code, no installs, no execution.**
**Date:** 2026-10-19. **Question:** How does JARVIS score source trustworthiness and require corroboration for high-stakes claims?

## TL;DR

Cycle 11's claim-verification ladder fixes the *check* but not the *evidence*: a claim entailed by a lying chunk passes every rung. This cycle designs the missing half — a **source-trust pipeline** that (1) assigns every retrieved chunk a **trust tier T0–T4** with a numeric default score, (2) composes the score from **cheap-at-retrieval signals** plus deeper verification signals, (3) requires **corroboration by 2+ independent sources** for high-stakes claims with a computable **independence test**, (4) **surfaces conflicts** between same-tier sources instead of silently picking one, and (5) treats the corpus as a **hostile supply chain** — because the field has shown that retrieval is now the primary attack surface (fake support numbers planted on .edu/.gov domains to hijack AI assistants [ZeroFox, 2025]; AI slop loops where fabricated claims get repeated into "consensus" [Lily Ray, 2026]; indirect prompt injection through indexed documents [Greshake et al., 2023]). This is the provenance half of factual reliability — the twin of CLAIM-VER.

**Headline design numbers (design choices, not measurements — tagged):**
- Tiers: T0 (user's own data) 1.00, T1 (primary/official) 0.90, T2 (reputable secondary) 0.65, T3 (unvetted web) 0.35, T4 (adversarial-risk) 0.10.
- Corroboration rule: high-stakes (risk tier R3: health, finance, security) requires 2+ *independent* chunks with ≥1 at T1; single T2+ suffices for low-stakes; anything resting only on T3/T4 is marked, never silently stated.
- Independence test: same outlet quoted twice is one source; syndication, shared authorship, near-duplicate text, or a citation chain collapses N chunks into one.

---

## 1. The problem (Cycle 11 §7-F3, finished here)

CLAIM-VER's F3 named the failure: *verification establishes grounding, not truth.* Its named-but-undesigned mitigation was "source trust tiers (primary docs > vendor blogs > scraped forums)" plus "two independent chunks for high-stakes claims." This file designs both.

Why it's load-bearing, not decorative — three 2025–2026 field observations:

1. **Retrieval is corruptible, not the model.** ZeroFox Intelligence (July 2025 flash report) traced LLM poisoning where scammers planted fake customer-support numbers in PDFs on university share drives and on .edu/.gov sites, reposted them on forums and Pastebin to push indexing — then watched Gemini and Copilot return the fake numbers as legitimate. The design "exploits how assistants weigh sources": **models score sources partly by domain, so a .gov host lends borrowed credibility** [zerofox.com] [HC — vendor threat-intel report, but mechanism is documented with examples].
2. **Repetition masquerades as consensus.** SEO researcher Lily Ray's April 2026 analysis documented the **"AI Slop Loop"**: one hallucinated claim gets published on AI-written SEO pages, other AI sites scrape and repeat it, and retrieval-based tools then treat the repetition as evidence of truth — "systems are not weighing accuracy so much as volume. Once enough pages echo the same fabrication, the falsehood starts to look like consensus" [noah-news.com] [HC — researcher analysis; the loop mechanism is the direct anti-pattern for our corroboration rule].
3. **Retrieved content is an attack channel, not just data.** Greshake et al. (2023), "Not What You've Signed Up For," formally established **indirect prompt injection**: malicious instructions embedded in documents the model retrieves, succeeding against Bing Chat and code assistants "without any prior access to the system's prompts" [via mbrenndoerfer.com summary] [VC — the paper is arXiv 2302.12173]. OWASP's Top 10 for LLM Applications catalogues this as **LLM01** (prompt injection), adjacent to LLM06 (sensitive information disclosure) [via aydahwa.com] [HC]. Enterprise practice is converging on **trust labeling of every chunk** — "untrusted external," "internal but user-generated," "curated policy" — with the rule that retrieved content is *evidence, never orders* [RedHat AI security guidance] [HC].

So the trust system has **two masters**: the *epistemic* job (is this claim supported by trustworthy evidence?) and the *security* job (is this chunk trying to do something to the model?). Tiers carry both.

---

## 2. Source trust tiers T0–T4

Every chunk carries `tier ∈ {T0..T4}` and a numeric `trust ∈ [0,1]` (the tier's default, adjusted by §3 signals). Tiers are assigned **at ingest or retrieval time**, never by the LLM mid-answer.

| Tier | Name | Definition | Examples | Default trust | What verification it can support |
|---|---|---|---|---|---|
| **T0** | Own data | The user's own files, notes, messages, calendar, health data, photos. Highest trust **for claims about the user**, not for world facts. | User's Gmail, notes in ~/workspace, device photos, their own documents | **1.00** | Grounds claims *about the user* alone. Cannot ground claims about the world (user's file can be wrong about a stock price). |
| **T1** | Primary / official | The authoritative source for the fact it asserts: the publisher of the data, the official docs, the study itself, the vendor's own spec for its own product. | Official documentation, primary research papers, government statistics pages, vendor specs *for vendor's own product*, primary-source quotes | **0.90** | Can ground a claim solo for most stakes. The only tier allowed as the "primary" in high-stakes corroboration (§4). |
| **T2** | Reputable secondary | Established publications with editorial process; reference works with citations; sources that cite their primaries. | Major newsrooms, Wikipedia **with citations** (the citations are the tier — an uncited Wikipedia paragraph is T3), peer-reviewed reviews, established reference sites | **0.65** | Can ground low-stakes claims solo. For high-stakes, counts as corroboration *only alongside a T1* — never as the primary. |
| **T3** | Unvetted web | Anybody-can-publish pages with no editorial gate and no verifiable authorship. | Blogs, forums, marketing pages, SEO content farms, vendor claims *about competitors or the world*, AI-written content pages | **0.35** | Can ground low-stakes claims **only when corroborated** (§4). Never grounds high-stakes claims alone. |
| **T4** | Adversarial-risk | Sources with a structural incentive to mislead, or detected as hostile: paid placements, affiliate farms, sources flagged by the injection scanner, domains on a blocklist, chunks whose provenance chain is broken. | Undisclosed-sponsored content, known SEO-spam farms, sites impersonating credible domains, any chunk that fails the provenance/injection screen (§6) | **0.10** | **Never grounds any claim.** T4 chunks are *excluded from the evidence set* before verification; they may be cited only in a warning ("this claim appears on spam pages — treated as hostile"). |

### Design notes

- **Wikipedia is tier-conditional, not tier-fixed.** The citations are what make it T2; a claim resting on an uncited Wikipedia paragraph is T3. This generalizes: *the tier belongs to (chunk, claim), not to the domain* — a T1 domain page can host a T3-quality unsupported assertion.
- **T0 vs T1 separation matters for privacy.** T0 chunks (user's own data) are the highest-trust evidence *about the user*, but using them to answer about the world is a category error, and — critically — T0 chunks must never be quoted to other parties. The tier system doubles as the privacy marker (cf. learn-underspecification's tier-3 data handling).
- **Domain reputation is a signal, not a tier.** ZeroFox's poisoning case is the warning: attackers *target* high-reputation domains (.edu/.gov) precisely because models score by domain. A T1 default for "official-looking domain" must be overridable by the injection/provenance screen — a .gov PDF with a broken provenance chain drops to T4, not T1.
- **Analogous real-world system:** FACTS&EVIDENCE (arXiv 2503.14797) tags each evidence item with a **source category** shown to the user and lets users include/exclude source types interactively [alphaxiv.org] [VC]. Our tiers are the machine-readable version of the same idea, with the categories fixed at design time rather than user-toggled per query (though a user override dial belongs in Settings).

---

## 3. Trust signals: what feeds the tier score

`trust(chunk) = clamp(tier_default × Π adjustments)`, adjustments from signals below. Signals are split by **when they're computable**, because anything that costs an LLM call per chunk at retrieval time is dead on arrival for a CPU-tier system (learn-bounded-rationality).

### 3.1 Cheap: computable at retrieval/index time (no LLM)

| Signal | What it measures | How it's computed | Direction |
|---|---|---|---|
| **Domain allow/block lists** | Known-good and known-bad publishers | Curated lists (maintained, versioned); e.g., official-doc domains T1-eligible, spam-farm domains → T4. Analog: NewsGuard-style domain ratings [SP — NewsGuard is a real commercial product; integrating it is a licensing decision, not designed here] | block → T4; allow → tier floor |
| **Publisher identity** | Who published this page | Metadata extraction (publisher, author byline, date) at ingest | missing authorship → −0.15; named author + outlet → +0.1 |
| **Recency** | How stale the claim's evidence is | `age = now − published_date`; exponential decay per topic (fast for prices/APIs, slow for math). Design analog: ARGUS-PRISM's `e^(−λt)` time decay on tier-weighted claims [dev.to, MC — hobby project, but the decay form is standard] | old → down-weight |
| **Citation presence** | Does the chunk cite *its* sources | Link/quote extraction; chunk with ≥1 outbound citation to a T1/T2 source scores higher. Wikipedia's citations are the worked case | cited → +0.1–0.2 |
| **Provenance-chain completeness** | Can we trace the chunk to an origin | Ingest metadata: source URL, crawl date, retrieval path, author. Broken chain (scraped copy of unknown origin) → cap at T3 | broken → cap T3 |
| **Near-duplicate detection** | Is this chunk a copy of another | SimHash/MinHash at index time; duplicates cluster to one canonical source (feeds the independence test, §4) | dup → merge, don't count twice |
| **Injection-scan flags** | Does the chunk contain instruction-like text | Deterministic pattern screen (imperative verbs addressed to the reader-as-AI, "ignore previous instructions," hidden-text heuristics, role-play framing) — the cheap half of the hardened_runner screen; the expensive half (LLM judge) runs only on high-stakes queries | flagged → T4, excluded |

### 3.2 Expensive: deeper analysis (only where stakes justify)

| Signal | Cost | When to run |
|---|---|---|
| **Lateral reading** | Web search per source | Stanford's finding: professional fact-checkers beat professors at source evaluation by *leaving the page* — checking what others say about the source — rather than reading it closely [openeducat.org summary; the underlying work is Wineburg et al., SHEG] [HC]. For T3 sources grounding any claim that survives to the answer, one lateral check is the highest-VoI signal. |
| **Corroboration count** | Second retrieval round | §4's rule *is* the signal: each independent source corroborating the claim adds +0.1 up to +0.3. |
| **Author credential verification** | Search + parse | For health/finance/security claims: is the author actually credentialed in the domain? Run only for R3 claims. |
| **Contradiction search** | Targeted retrieval | Actively search for counter-evidence on high-stakes claims — the "honest negatives" discipline. A claim with no findable contradiction after a targeted search is meaningfully stronger than one never tested. |

### 3.3 The score is an input to verdicts, not a verdict

Trust scores feed CLAIM-VER's ladder as a **gating layer**:

- Chunk with trust < 0.25 (T4) → **excluded from the evidence set** before verification begins. The ladder never sees it.
- Claim grounded *only* by T3 chunks → verdict cap: `verified-low-confidence` at best (rendered with the §4.1 "checked, thin sources" marking), and for R2+ stakes → `inconclusive`.
- Claim grounded by T3 chunks that *fail the independence test* (§4) → treated as **single-source**: one T3 chunk quoted five times is one 0.35 chunk, not five.
- The UX contract (Cycle 11 §4) gains a vocabulary: "checked against sources" vs "checked against thin sources" vs "couldn't verify." The trust score is what chooses between the first two.

---

## 4. The corroboration rule

### 4.1 Why corroboration, and why independence is the whole game

Corroboration exists to defeat **single-point-of-failure evidence**: one wrong chunk (garbage-in), one compromised chunk (poisoning), one fabricated claim echoed by scrapers (the AI Slop Loop). But Lily Ray's finding cuts the other way too: *naive counting of sources rewards the slop loop* — ten AI-written pages repeating one hallucination look like ten sources. **Corroboration without an independence test is consensus theater.** The rule:

> **A claim is corroborated iff it is entailed (CLAIM-VER rung 1–2) by chunks from ≥2 sources that pass the independence test below.**

### 4.2 The independence test (computable)

Two chunks are **NOT independent** if any of these hold; N chunks collapsing to one group count as **one source**:

1. **Same publisher/outlet.** Two articles from the same site, two pages from the same docs domain → one source. (The manufacturer page + the manufacturer's press release = one source.)
2. **Shared authorship.** Same byline, same organization, or one author citing the other.
3. **Citation chain.** Chunk B cites chunk A (or both cite the same single primary). Following the citation trail to the primary is research; counting B as "corroboration" of A is double-counting. *Following citations to the primary is how you find the T1; counting the chain as two sources is the error.*
4. **Near-duplicate text.** SimHash distance below threshold, or >60% sentence overlap → syndication or scraping. The slop loop's signature: same fabricated claim, lightly paraphrased, across ten SEO domains. [design, MC]
5. **Temporal clustering with identical claims.** Ten pages published within 48 hours carrying the identical novel claim = one origin until provenance proves otherwise. (Wire copies, press-release echoes.)
6. **One is a quote of the other.** "According to [manufacturer]…" in the blog = the blog is not an independent source for the manufacturer's claim — it's a *conduit*. Attribution hedges (§1.2 of CLAIM-VER) mark this explicitly.

**Cheap subset** (runs at retrieval time): rules 1, 4 (index-time SimHash), 6 (quote/attribution pattern match). **Deep subset** (runs for R2+ claims): rules 2, 3, 5 (citation-edge analysis, temporal analysis).

### 4.3 The rule mapped to risk tiers

Risk tiers from learn-underspecification.md §3: **R0** read-only/trivial, **R1** low-stakes reversible, **R2** consequential/hard-to-reverse, **R3** catastrophic (health, finance, security advice, irreversible external action). The corroboration requirement scales with the action the claim *justifies*, not with the claim's topic alone — a health claim in a trivia answer is R1; the same claim justifying a supplement purchase is R3.

| Risk tier | Corroboration required | Minimum tier mix | If unmet |
|---|---|---|---|
| **R0** (read-only, trivia, reversible) | Single chunk suffices | T2+; T3 allowed with `verified-low-confidence` marking | Mark as thin-sourced; continue |
| **R1** (low-stakes action, easy undo) | Single chunk, must pass independence trivially | T1 or T2; T3 needs a second independent T3+ chunk | Downgrade to marked claim or ask |
| **R2** (consequential, hard to reverse) | **2 independent chunks** | **≥1 T1** + 1 independent T2+; two T2s acceptable only if lateral reading (§3.2) passes on both | `inconclusive` → abstain or escalate to user with both citations shown |
| **R3** (health, finance, security, irreversible) | **2+ independent chunks, ≥1 T1**, plus contradiction search (§3.2) attempted | T1 primary required; T3/T4 chunks **do not count** toward the 2 even if independent | **Abstain.** The answer states what *is* established, cites the T1, and refuses the claim. For user-acknowledged actions, the approval UX (learn-approval-ux-spec) shows the evidence gap explicitly. |

Notes:
- **T0 (user's own data)** corroborates claims *about the user* at every tier — "your flight is at 6pm" needs one T0 chunk, not two. T0 does not corroborate world-claims at any tier.
- **Single-T1 sufficiency:** an R2 claim grounded by one strong T1 (e.g., the official docs stating the API limit) is `verified-single-primary` — allowed, but rendered with the source named. R3 still wants two.
- **Two T2s for R3 is forbidden.** This is the deliberate asymmetry: at catastrophic stakes, secondary sources don't corroborate each other into a primary. (If two T2s agree, *find the primary they cite* — that's the R3 move, and it's usually one retrieval hop.)
- **Budget interaction** (learn-bounded-rationality): corroboration retrieval is the most expensive verification step, so it runs **last and only for R2+** claims. R0/R1 claims get the cheap path: trust-gate the chunks, run the CLAIM-VER ladder, done.

---

## 5. Conflict handling: when good sources disagree

### 5.1 The protocol (normative)

Two chunks at the **same tier** (especially T1 vs T1, or T1 vs strong T2) entailing **contradictory** claims is a first-class pipeline state, not a tie to break silently:

1. **Never pick one silently.** The pipeline does not average, does not prefer the higher trust score by a hair, does not drop the contradiction. Silent resolution is hallucination laundering with extra steps.
2. **Surface both.** The answer (or the escalation card) presents the disagreement with both citations, in the user's plain language: *"Source A (official docs, 2026) says X; source B (NIH review, 2025) says not-X. They disagree."* The UX contract's `contradicted` handling (Cycle 11 §4.1) applies to the *pair*, not to either claim alone.
3. **Escalate by stakes:**
   - **R0/R1:** surface both, answer hedged, let the user decide. Cheap, honest.
   - **R2:** surface both + attempt a **tiebreaker search for the primary source** both cite (or a newer primary). Design analog: ARGUS-PRISM's "tie-breaker search against primary sources" step [dev.to, MC]. If the tiebreaker resolves it, cite the resolution; if not, abstain on the disputed sub-claim and answer around it.
   - **R3:** **abstain on the disputed claim, always.** Present the conflict, refuse to act on either side, and — for health/finance/security — say explicitly that the sources disagree so the user consults a professional. No tiebreaker search is allowed to manufacture certainty at R3; it can only *find* certainty that already exists in a primary.
4. **Record the conflict in memory.** The contradiction enters the belief store as a **conflict record** (both claims, both sources, both tiers, date), not as a resolved fact — connecting to the memory contradiction-resolution work (provenance-aware claims; mem0/A-MEM quarantine patterns per MASTER-INDEX). A later primary-source resolution can close the record; until then, any future claim touching the disputed proposition re-surfaces the conflict.

### 5.2 The common sub-cases

- **T1 vs T1, different dates:** the newer one usually wins *if* it supersedes (changelog > old docs; new study > old review) — but "supersedes" must be established by citation (the new source referencing and updating the old), not assumed by date alone. Undated T1 chunks are T2 until dated.
- **T1 vs T2:** the T1 wins by default, *unless* the T2 is citing a newer T1 the pipeline hasn't retrieved — then the move is to retrieve that primary, not to promote the T2.
- **T2 vs T2:** both are secondary; the correct move is almost always to go find the primary. Two secondaries disagreeing is evidence the underlying primary is ambiguous or the secondaries are sloppy — either way, R2+ abstains.
- **Anything vs T4:** T4 chunks are already excluded from the evidence set (§3.3). A "conflict" with a T4 chunk is not a conflict — it's a hostile input, handled by §6.

---

## 6. Adversarial sources

### 6.1 The threat model (three attackers)

| Attacker | Method | What it defeats | Trust-system response |
|---|---|---|---|
| **SEO spammer / slop farmer** | Mass-produced pages repeating a fabricated claim; the AI Slop Loop [Lily Ray, 2026] | Naive source-counting; domain-reputation heuristics | Independence test (§4.2 rules 4–5: near-dup + temporal clustering collapse the farm to one source); corroboration *raises* the bar instead of lowering it |
| **Brand/payment poisoner** | Fake facts (support numbers, prices) planted on high-reputation domains (.edu/.gov PDFs) to borrow credibility [ZeroFox, 2025] | Domain-based trust ("it's a .gov, must be T1") | **Provenance-chain completeness** (§3.1): a .gov PDF with no verifiable authorship, no date, and text shaped like a customer question ("what is X's support number?") fails the chain and drops to T4. Domain is a signal; provenance is the gate. |
| **Prompt-injector** | Instructions hidden in retrieved documents; indirect injection [Greshake et al., 2023, arXiv 2302.12173]; OWASP LLM01 | The generator itself — the model obeys the chunk | Two layers: (a) the **injection screen** (cheap pattern scan at retrieval + LLM judge for high-stakes) marks the chunk T4 and excludes it; (b) the architectural rule from RedHat's guidance: **retrieved content is evidence, never orders** — the generator is instructed (and the hardened_runner is tested) to never execute instructions found in retrieved text. Note the honest limit from the field: "you cannot prompt your way out of this with a stern system message" [aydahwa.com] [HC] — the screen and the exclusion are the defense; the instruction is defense-in-depth. |

### 6.2 Interaction with the REA untrusted-content markers and hardened_runner

- **REA markers** (untrusted-content provenance flags from the memory/attack studies): a chunk arriving with an REA untrusted marker is **pre-assigned T4 pending review** — the marker is the provenance chain *reporting itself broken*. The trust pipeline trusts the marker over its own heuristics.
- **hardened_runner's 13-attack suite:** the injection screen (§3.1) is the production face of that suite — the suite's attack patterns become the screen's pattern library, and suite regressions gate screen updates. A new attack class found by the suite → new screen pattern → chunks previously scored T2/T3 re-screened. The trust tier is **not immutable**: a tier assignment is versioned with the screen version that produced it.
- **Quarantine, not deletion:** T4 chunks are excluded from evidence but **logged with their tier reasoning** (which screen fired, which provenance link broke). This is the memory-science quarantine pattern (mem0/A-MEM per MASTER-INDEX): untrusted content is preserved for forensics and re-evaluation, never silently dropped, never promoted.

### 6.3 Fail-open vs fail-closed (the deliberate asymmetry)

| Situation | Default | Rationale |
|---|---|---|
| Benign retrieval, low stakes (R0/R1), chunk looks odd but no hostile signal | **Fail open** — include at T3, mark thin-sourced | Over-abstention is the cost; a wrong trivia answer is cheap. The UX marking carries the uncertainty. |
| High stakes (R2/R3), provenance incomplete | **Fail closed** — cap at T3 (excluded from corroboration count); R3 → abstain | An unverifiable source at catastrophic stakes is indistinguishable from a hostile one. Treat it as such. |
| Injection screen fires (any stakes) | **Fail closed, always** — T4, excluded, quarantined, logged | A chunk trying to instruct the model is hostile by definition. There is no "probably benign injection." |
| Conflict between T1s at R3 | **Fail closed** — abstain | §5.1. Certainty cannot be manufactured where primaries disagree. |
| Trust signal *missing* (no date, no author) | **Fail open at R0/R1, closed at R2+** | Missing metadata is weak evidence of hostility but strong evidence of unvetting. The stakes decide. |

The principle: **the trust system fails toward the cheaper error.** Wrong inclusion is cheap at R0 and catastrophic at R3; wrong exclusion is cheap everywhere except recall (a true claim forced to abstain — the benign direction, per CLAIM-VER F3).

---

## 7. Worked example: "this supplement is safe" traced end-to-end

**User question:** "Is ashwagandha safe to take daily?"

**Claim extracted** (CLAIM-VER §1): C1 = "Ashwagandha is safe for daily use." Type: factual, health domain → **risk tier R3** (health claim justifying a consumption decision).

**Retrieval returns 3 chunks:**

| Chunk | Content (gist) | Tier assignment | Trust |
|---|---|---|---|
| **K1** | Manufacturer product page: "…clinically proven safe for daily use…" | **T3 → borderline T4.** Vendor claim *about its own product's safety* — structural incentive to mislead (§2: adversarial-risk). Injection screen: clean (no instruction text), but provenance is single-source marketing. Assigned **T3, trust 0.35**, flagged `incentive: seller`. | 0.35 |
| **K2** | Health blog: "Ashwagandha is totally safe, I take it every day! [links to K1's manufacturer]" | **T3.** Unvetted blog, no credentials, no citations except a link to the manufacturer page — **citation chain** (§4.2 rule 3): K2 cites K1. Assigned **T3, trust 0.35**. | 0.35 |
| **K3** | NIH / NCCIH page: "There is insufficient evidence to conclude ashwagandha is safe for long-term daily use; consult a healthcare provider." | **T1.** Primary health authority, authored, dated, cited. Assigned **T1, trust 0.90**. | 0.90 |

### Step 1 — Exclusion and tier gating (§3.3)

No chunk is T4 (K1's seller incentive is noted but it's marketing, not hostile — it stays T3; had it contained injected instructions it would be T4 and gone). Evidence set: {K1, K2, K3}.

### Step 2 — Corroboration attempt (§4)

- K1 and K2 both *entail* C1 (rung 2: "clinically proven safe for daily use" ⊢ C1; "totally safe" ⊢ C1). **Two chunks, but the independence test fails**: K2 links to K1 (citation chain, rule 3), same claim lineage, and K2's authorship is unverifiable. K1+K2 collapse to **one T3 source**.
- Worse: even if independent, **T3 chunks do not count toward R3 corroboration** (§4.3). R3 requires ≥1 T1 among 2+ independent sources. K1+K2 contribute **zero** to the R3 requirement.
- K3 (T1) does **not** entail C1 — it states *insufficient evidence* for the safety claim. Run the NLI the other direction: K3 arguably **contradicts** the unqualified "safe for daily use" (a 3-way head should return contradiction or at best neutral-with-hedge; the honest reading is that the primary authority refuses the claim).

**Corroboration result: FAILED.** One collapsed T3 source for the claim, zero T1 support, and the sole T1 withholds or contradicts it.

### Step 3 — Verdict (CLAIM-VER ladder + trust gating)

- C1 cannot reach `verified` — no T1 entailment, corroboration failed.
- C1 is not cleanly `contradicted` either (K3 says "insufficient evidence," not "unsafe") — so the verdict is **`inconclusive — ungrounded at R3`**, which at R3 **fails closed: abstain on the claim**.

### Final rendered answer

> "I can't verify that ashwagandha is safe for daily use. The strongest source I found — the NIH's NCCIH page — says there is **insufficient evidence** to conclude it's safe for long-term daily use and recommends consulting a healthcare provider. [citation: K3]
> 
> ⚠️ *What I found but couldn't use:* the manufacturer's page and a health blog both claim it's safe, but the blog cites the manufacturer — so that's one seller's claim, not two independent sources. For health questions I need independent confirmation including an authoritative source, and I don't have it here."

Every sentence is checkable: the abstention (R3 fail-closed), the independence collapse (K2→K1 citation chain), the T1's actual position (insufficient evidence, not "unsafe" — no strawmanning the primary), and the rule that was applied (stated, not footnoted). That's the trust pipeline and the verification ladder working as one system.

---

## 8. The scoring pipeline (assembly order)

For each user query, in order — no step sees the output of a later step:

1. **Retrieve** candidate chunks (hybrid search; learn-databases.md's 91% recall is the precondition — a missing chunk forces honest abstention, the benign direction).
2. **Tier + screen** every chunk: assign T0–T4, run the cheap injection/provenance screen, compute trust (§2–3). T4 → quarantine log, excluded from evidence.
3. **Independence-collapse** the evidence set (§4.2 cheap subset: same-publisher, near-dup, quote-of). Record the collapsed groups.
4. **Extract claims**, classify risk tier per claim (§4.3 — by the *action the claim justifies*).
5. **Corroboration check** for R2+ claims *before* the CLAIM-VER ladder: does the collapsed evidence set contain the required independent mix? If not → verdict `inconclusive` without spending ladder compute (bounded-rationality: the most expensive check fails first and cheapest).
6. **CLAIM-VER ladder** on the surviving claims, with trust-gated evidence.
7. **Conflict check** (§5): same-tier contradictions → surface/escalate/abstain by stakes.
8. **Render** per the UX contract, with trust vocabulary ("checked against sources" / "thin sources" / "couldn't verify") and citations that carry their tiers.

---

## 9. Connections to prior cycles

- **Cycle 11 (learn-claim-verification.md):** this file implements F3's named mitigation. The ladder checks claims against chunks; SRC-TRUST checks chunks against the world. Neither works alone.
- **learn-databases.md:** hybrid search 91% recall is the retrieval precondition; metadata filtering is where tier/signal metadata lives (tier, publisher, date, provenance chain as filterable fields); citation grounding post-hoc becomes tier-carrying citations.
- **learn-underspecification.md:** risk tiers R0–R3 supply the cost side of the corroboration rule (§4.3). The fail-open/fail-closed map (§6.3) is the same cost-asymmetry logic applied to evidence.
- **learn-evaluation-science.md:** faithfulness metrics and citation precision/recall are the scorecard; SRC-TRUST predicts that citation precision *stratified by tier* is the diagnostic metric (T3-sourced claims should show lower downstream accuracy — if they don't, the tiers are miscalibrated).
- **Memory studies (mem0/A-MEM/cog, MASTER-INDEX):** provenance-aware claims and quarantine-for-untrusted-sources are the memory-side twin; §5.1's conflict records and §6.2's quarantine log are the retrieval-side implementation of the same pattern.
- **learn-attack-trees.md / REA / hardened_runner:** §6 wires trust scoring into the adversarial pipeline — REA markers pre-assign T4, the 13-attack suite feeds the injection screen's pattern library, tier assignments are versioned with screen versions.

## 10. Unknowns and next measurements

- [UK] **Tier calibration:** the default scores (1.00/0.90/0.65/0.35/0.10) are design choices, not measurements. The real calibration: on a labeled set of (chunk, claim) pairs with ground-truth verdicts, what P(claim true | entailed by tier-T chunk) is observed per tier? Until measured, treat the numbers as *ordering*, not probabilities.
- [UK] **Independence-test precision/recall:** no measured false-collapse rate (two genuinely independent sources sharing phrasing, e.g., both quoting the same press release *accurately* — collapsing them loses real corroboration) or false-separation rate (slop farms with paraphrase defeating SimHash). Needs a labeled corpus of known-syndicated vs known-independent pairs.
- [UK] **Injection-screen false-positive rate on legitimate content:** legal disclaimers, quoted system prompts in documentation, and security advisories all contain instruction-like text. The cheap pattern screen will fire on them; the tier cost of a false T4 is a lost source. Measure before deploying the screen as a hard gate.
- [UK] **Lateral-reading cost/benefit:** one web search per T3 source per surviving claim — measure the latency and the actual tier-correction rate. If lateral reading rarely changes tiers, demote it to R3-only.
- [SP] **Recency decay λ per topic:** fast-decay topics (prices, API limits, software versions) vs slow-decay (math, history) — the per-topic λ table is a design guess awaiting retrieval-log analysis.
- [SP] **The "two T2s never make an R3" rule** is deliberately conservative and will cause false abstentions where two excellent secondaries (e.g., two major medical reviews) agree. The escape hatch — "find the primary they cite" — assumes the primary is retrievable; when it isn't (paywalled study), the pipeline abstains where a human expert wouldn't. This is the known cost of the rule, accepted: at R3, false abstention is the benign direction.

## References (all real, fetched or verified this cycle)

- Greshake et al. 2023, "Not What You've Signed Up For: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection" — https://arxiv.org/abs/2302.12173 (indirect prompt injection; attacks on Bing Chat et al. without prior access to system prompts) [VC]
- OWASP Top 10 for LLM Applications — LLM01 Prompt Injection, LLM06 Sensitive Information Disclosure [HC — via enterprise RAG security writeups this cycle]
- ZeroFox Intelligence, "LLM Poisoning: How Attackers Write Fake Content for AI" (July 2025 flash report) — https://www.zerofox.com/blog/llm-poisoning-attackers-write-fake-content/ (fake support numbers on .edu/.gov + forums/Pastebin; domain-weighted trust exploited; returned by Gemini/Copilot) [HC]
- Lily Ray, "AI Slop Loop" analysis (April 2026, via Noah Intelligence) — https://noah-news.com/ai-search-tools-risk-amplifying-fabricated-seo-claims-into-false-facts/ (fabricated SEO claims repeated into false consensus by AI search tools) [HC]
- Nozzle, poisoned-SERP study (Oct 2026, 27.5M result pages) — https://seohandbook.co.uk/seo-news-updates/google-altered-serps-rank-trackers/ (8.0% of SERPs altered; normal-looking pages with swapped results — the measurement layer itself can be poisoned) [HC]
- RedHat, "AI security: Defending against prompt injection and unsafe actions" — https://www.RedHat.com/de/blog/ai-security-defending-against-prompt-injection-and-unsafe-actions (trust labeling of context: untrusted external / internal user-generated / curated policy; retrieved content is evidence, never orders) [HC]
- FACTS&EVIDENCE (arXiv 2503.14797) — https://www.alphaxiv.org/abs/2503.14797 (per-evidence source-category tags; user-toggleable source types; FAVA eval, +40 F1) [VC]
- Stanford History Education Group, lateral reading research (Wineburg et al.) — professional fact-checkers outperform academics by reading *laterally* (checking what others say about a source) [HC — via openeducat.org summary this cycle]
- Corroboration-authority scoring dimensions (independence, credibility, claim consistency, freshness) — https://thegeocommunity.com/blogs/generative-engine-optimization/what-is-corroboration-authority/ [SP — marketing-SEO source; used only as a dimensions checklist, not as evidence]
- ARGUS-PRISM (dev.to hobby project) — https://dev.to/aks_a/argus-prism-the-hundred-eyed-fact-checker-that-audits-ai-refutes-hallucinations-and-gets-paid-2ajj (source tiers × time decay × contradiction detection × tiebreaker search against primaries — independent design convergence with §4–5) [MC]

---
*Cycle 12 complete. Claim about this file: all tier scores, thresholds, and rules are design choices tagged as such or marked [SP/MC]; all field observations are sourced above. The file contains no claim that the trust pipeline has been built, measured, or deployed — it hasn't.*
