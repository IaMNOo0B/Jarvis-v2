# Fault-Tree Analysis for JARVIS Safety-Critical Paths

*PHASE INFINITY, Research Cycle 4. Safety engineering, not academia — concrete and actionable.*
*Date: 2026-10-19. Status: analysis complete, unvalidated on a real design review.*
*Unification note (Cycle 18): this tree's cut sets are also consumed by `learn-threat-model.md` (Cycle 10, §18 #9) and `learn-reliability-spec.md` (Cycle 12, §18 #10) — edit the analysis here, record design decisions there.*

---

## 1. FTA mechanics in plain language [VC]

Fault-tree analysis is **top-down and deductive**: start with one specific disaster (the *top event*), work downward asking "what could cause this?" until you reach *basic events* — failures you can't or won't decompose further. Formalized in **IEC 61025**; required in aviation and nuclear safety cases.

**Two gates do all the work:**
- **OR gate** — the output occurs if *any* input occurs. Models alternative failure paths. A branch of only OR gates means many single ways to die.
- **AND gate** — the output occurs only if *all* inputs occur together. Models redundancy / defense in depth. An AND gate is where safety lives.

**Minimal cut sets** are the payoff: the *smallest* combinations of basic events whose joint occurrence causes the top event. A cut set of size 1 = **single point of failure**, no redundancy, fix first. A cut set of size 2 = you need two independent failures — an order of magnitude safer (for random failures). The cut-set list *is* the prioritized hardening backlog. (Classic algorithm: MOCUS; large trees use ZBDDs — irrelevant at our scale, our trees fit on one page.)

**Scope rule:** one tree per top event. We build the approval-gate tree here, then sketch three more.

---

## 2. Fault tree: "Tier-3 action executes without user approval"

*Top event definition: a tier-3 (irreversible or high-impact) action's side effects occur, and no genuine user approval authorized that specific action.*

```
TOP: Tier-3 action executes without user approval
│
├─ G1 (OR): Gate code defeated
│   ├─ B1: approval flag flipped by bug (boolean logic error in gate)
│   ├─ B2: bypass code path exists (unauthorized path / developer backdoor)
│   └─ B3: TOCTOU — approval checked, action swapped before execution
│
├─ G2 (AND): Brain evades gate AND code enforcement absent
│   ├─ G2a (OR): brain-side evasion
│   │   ├─ B4: prompt injection reclassifies action tier (3→1)
│   │   └─ B5: brain emits action without invoking gate
│   └─ B6: gate not enforced in deterministic code (design flaw)
│
├─ G3 (OR): Approval signal forged
│   ├─ B7: UI spoofing — fake approval dialog tricks the user
│   ├── B8: replay — recorded approval reused for a different action
│   └─ B9: event log tampered — approval event forged
│
└─ G4 (OR): Human-factor defeat (gate technically functioned)
    ├─ B10: rubber-stamping — user approves without reading
    └─ B11: approval fatigue — prompt volume trains auto-approve
```

### Minimal cut sets [HC]

| # | Cut set | Size | Reading |
|---|---|---|---|
| 1 | {B1} | 1 | A single boolean bug defeats the gate |
| 2 | {B2} | 1 | A single bypass path defeats the gate |
| 3 | {B3} | 1 | A single race defeats the gate |
| 4 | {B4, B6} | 2 | Injection works **only if** code enforcement is also absent |
| 5 | {B5, B6} | 2 | Brain evasion works **only if** code enforcement is also absent |
| 6 | {B7} | 1 | One spoofed dialog defeats the gate |
| 7 | {B8} | 1 | One replayed approval defeats the gate |
| 8 | {B9} | 1 | One forged log entry defeats the gate |
| 9 | {B10} | 1 | One careless click defeats the gate's *purpose* |
| 10 | {B11} | 1 | Fatigue defeats the gate's *purpose* |

**The central insight is cut sets 4–5.** The AND gate G2 is the formal statement of R2 ("prompts are the wrong enforcement"): *as long as B6 is false by construction* — the gate is enforced in deterministic code after the brain — prompt injection (B4) and brain evasion (B5) are **not** single points of failure. They require a second, independent design failure. Without R2, B4 and B5 would be size-1 cut sets, and every prompt-injection attack would be a gate bypass. **The AND gate is defense in depth made visible.**

Everything else is a size-1 cut set. That is the honest bad news: the approval gate has **eight single points of failure**. Each one below gets its mitigation.

---

## 3. What each cut set demands [HC]

| Cut set | Mitigation (which layer catches it) | Existing defense it connects to |
|---|---|---|
| {B1} flag flipped by bug | `beartype` + `deal` contracts on the gate function; Hypothesis stateful tests hammering gate transitions; the gate function kept tiny and reviewable | learn-formal-methods (contracts on 5–10 critical functions) |
| {B2} bypass path / backdoor | No dynamic dispatch to actions — static allowlist of gate-wrapped entry points; code review; dependency pinning + SBOM (supply-chain) | learn-formal-methods (supply chain), R11 manifest |
| {B3} TOCTOU race | Check-and-dispatch in one synchronous function — no `await`, no IPC, no UI round-trip between the check and the action; the approval token embeds the **action hash**, so a swapped action invalidates the token | Idempotency-key design (backend study) |
| {B4,B6} injection + no enforcement | Keep B6 false: gate enforced in code, post-brain, on the *actual action object* — never on the brain's description of it. Plus REA untrusted-content markers and the 13-attack injection suite to shrink B4's probability | R2 instruction hierarchy, hardened_runner |
| {B5,B6} evasion + no enforcement | Same as above — the brain has no code path to side effects except through the gate | R2, capability-based permissions (Deno pattern) |
| {B7} UI spoofing | Approval dialog rendered in trusted chrome (never in web content); dialog shows origin proof; visible payload (action + target + blast radius) so a spoofed dialog has nothing convincing to show | learn-frontend (approval UX) |
| {B8} replay | Approval tokens are single-use nonces bound to (action hash, timestamp); replayed token = rejected. 30s undo buffer as backstop, not primary defense | learn-advanced-cs (idempotency) |
| {B9} log forgery | Append-only event log with hash chain — forgery is tamper-*evident*; approval events require the chained hash of the preceding event | R15 session store, learn-advanced-cs (event sourcing) |
| {B10} rubber-stamping | Visible payload pre-click (theater otherwise); anomaly-flag approval prompts (unusual action for this user → friction); rate-limit prompt bursts | learn-frontend (2026 consent finding), open-problem #10 |
| {B11} fatigue | Sliding-scale autonomy — fewer, higher-stakes gates; learned policies for routine approvals; batching | learn-frontend, learn-underspecification |

**Design rule the tree teaches:** every size-1 cut set should either (a) get an AND gate above it (add an independent layer), or (b) get its probability driven down by construction (make the basic event impossible, not just unlikely). B6 is the model: eliminated by *design*, not by testing.

---

## 4. Quantitative FTA — honest treatment [HC]

The textbook math: **AND gate → multiply** probabilities; **OR gate → add** (rare-event approximation). So P(TOP) ≈ P(B1)+P(B2)+P(B3)+P(B4)·P(B6)+P(B5)·P(B6)+P(B7)+P(B8)+P(B9)+P(B10)+P(B11).

**Why we do NOT compute a number here [VC]:** we have no empirical failure rates for "LLM bypasses gate via prompt injection," "UI spoofing succeeds," or "flag flipped by bug." Assigning 10⁻⁴ to these would be **theater — false precision**. The ScienceDirect FTA survey is explicit: quantitative results are entirely hostage to input-data precision, and unresolved uncertainty produces misleading results. FasterCapital's FTA critique lists data limitations for rare/novel events as a core weakness — our basic events are *all* rare or novel.

**When quantification is honest and useful:**
1. **After measurement.** B10/B11 (rubber-stamping, fatigue) *can* be quantified once production data exists — click-through latency and approve-without-scroll rates are observable. Then the tree tells you whether UX fixes moved the number.
2. **Order-of-magnitude sensitivity.** "Even if B1 is 10× worse than we think, cut sets 4–5 stay second-order" — robustness reasoning, not a point estimate.
3. **Design comparison.** Design A has six size-1 cut sets; design B has three. B is better *even with no numbers* — cut-set order dominates.

**The independence caveat [HC]:** FTA assumes basic events fail independently. For *random* failures (bugs, races) that's reasonable. For **adversarial** events (B4, B7, B8, B9) it's false — an attacker *correlates* failures deliberately, hunting the cheapest cut set. For those branches, the right tool is an **attack tree** (same shape, adversarial semantics), and the mitigations above are threat-model mitigations. Use FTA for the random-failure skeleton, attack trees for the adversarial branches. Both, not one.

**Verdict: qualitative FTA now (cut sets = backlog), quantitative later (after production data), never fake numbers.**

---

## 5. Three more trees worth building [MC]

### Tree 2 — Secrets pipeline. Top event: "API key exfiltrated"
Basic events (all OR, all size-1 — that's the finding): key written to log · key in error message / crash dump · key in backup · key synced to cloud provider · key in shell history · key pasted into chat/context · key in process environment readable by child process. **Every cut set is size 1** → the design response is uniform: keys live in OS keyring only, fail-closed redaction on every output path, never in logs/dumps/backups. The tree justifies R9's absolutism: with no AND gates available, you eliminate basic events instead of layering.

### Tree 3 — Updater. Top event: "malicious code executes via update"
G1 (OR): signature verification bypassed — B: minisign check skipped on error (fail-open bug) · B: public key replaced (key storage compromised). G2 (AND): manifest tampered AND signature valid — needs key compromise, second-order. G3: rollback — B: downgrade to vulnerable version permitted. Mitigations the tree demands: **verify-or-abort** (never fail-open), no-downgrade rule, two signing layers (minisign for authenticity + Authenticode for OS trust — from the frontend study), key rotation invalidates old releases. This is R10 made structural.

### Tree 4 — Memory poisoning → action. Top event: "poisoned memory causes harmful action"
G (AND): B: untrusted content written to memory without quarantine AND B: retrieved memory surfaced without provenance AND B: brain acted on it without independent verification. **Three-element cut set** — defense in depth already exists in the design (quarantine + provenance tags + verify-before-acting). The tree's value: it shows *which* layer may be dropped under schedule pressure and what that costs (dropping any one layer collapses the cut set to size 2). Don't drop two.

---

## 6. How to use this in the v2 build [HC]

1. **Build the trees before the code** — FTA is a design-review tool. Run it on the approval-gate design doc, not on the shipped binary.
2. **The cut-set list is the hardening backlog**, ordered by size then by consequence. Size-1 cut sets are P0.
3. **Every AND gate is a requirement**, not an observation: G2's AND gate *requires* R2 (code enforcement). If a refactor moves the gate into a prompt, the tree breaks — that's a regression the review must catch.
4. **Revisit after production data**: quantify B10/B11, then decide whether the UX mitigations worked.
5. **Pair with attack trees** for B4/B7/B8/B9 — FTA covers accidents, attack trees cover adversaries.

## Confidence & unknowns

- [VC] FTA mechanics, gate semantics, cut-set method (IEC 61025; IEEE TechNav; Tractian glossary; CSIRO RAI pattern catalogue).
- [HC] Tree structure and mitigations — grounded in adopted v2 decisions (R2, R3, R9, R10, R11, R15, Conscio circuit breaker, Z3 C2, Hypothesis suite).
- [MC] Completeness of basic events — a real FTA is a team exercise; a single analyst misses branches. The B-list above is "best effort," not exhaustive.
- [SP] Whether UI spoofing (B7) is in scope depends on the Tauri/WebView2 dialog design — unresolved until the frontend spike.
- [UK] Measured rubber-stamping rate; real TOCTOU surface in the final IPC design; whether the event-log hash chain survives the SQLite implementation.

## References (all real, from live search)

- IEC 61025 — fault tree analysis standard (cited via IEEE TechNav FTA topic: https://technav.ieee.org/topic/fault-tree-analysis/)
- FTA mechanics, gates, cut sets, qualitative vs quantitative: https://tractian.com/en/glossary/fault-tree-analysis
- MOCUS/ZBDD cut-set algorithms, FTA encyclopedia: https://encyclopedia.ambient.tech/articles/fault_tree_analysis_(fta).html
- FTA as responsible-AI governance pattern (CSIRO): https://research.csiro.au/ss/science/projects/responsible-ai-pattern-catalogue/fta/
- FTA limitations (static nature, data limits, expertise dependence): https://fastercapital.com/content/Risk-Management--Roots-of-Risk--Enhancing-Risk-Management-with-Fault-Tree-Analysis-Insights.html
- FTA vs FMEA, quantitative methods: https://www.truegeometry.com/api/exploreHTML?query=Fault%20Tree%20Analysis%20(FTA)%20and%20Failure%20Mode%20and%20Effects%20Analysis%20(FTA)
- Uncertainty in quantitative FTA (fuzzy methods, SciDirect survey): https://www.sciencedirect.com/science/article/abs/pii/S0957417417300714
- FTA skill workflow (top-event quality gates): https://eliteai.tools/agent-skills/fault-tree-analysis
