# Attack Trees for JARVIS Adversarial Branches

*PHASE INFINITY, Research Cycle 5. Companion to Cycle 4 (learn-fault-trees.md). Safety engineering, not academia — concrete and actionable.*
*Date: 2026-10-19. Status: analysis complete, unvalidated on a real design review.*
*Protocol: confidence tags on every substantive claim; no invented numbers; real citations only; honest scope (§19 house protocol).*

---

## 0. Why this file exists

Cycle 4 built a fault tree for **"tier-3 action executes without user approval"** and ended with an honest finding: FTA assumes basic events are **independent and random**, which is false for the adversarial basic events B4 (prompt injection), B7 (UI spoofing), B8 (replay), B9 (log tampering). An attacker does not roll dice per branch — they **correlate deliberately, hunting the cheapest path to the root**. This file is Cycle 4's explicit recommendation executed: an attack tree for the same top event, with the attacker as the modeled agent.

**Threat-model scope for this tree [HC]:** the assumed attacker is an external third party (not the user, not a malicious insider) trying to induce JARVIS into executing an irreversible or high-impact action without the user's genuine approval of *that specific action*. Assumed capabilities: can publish web content, send messages/documents the user might open, and interact with the agent through normal channels. Assumed *not* to have: code execution on the user's PC, physical access, or the user's credentials. Cost ordering below is relative to this attacker. Change the attacker, re-rank the tree — that is Schneier's rule, not ours.

---

## 1. Attack-tree mechanics in plain language [VC]

From Bruce Schneier, "Attack Trees: Modeling Security Threats," *Dr. Dobb's Journal* 24(12), December 1999:

- **Root = the attacker's goal.** Children = subgoals; their children = ways to achieve each subgoal; **leaves = concrete attacker actions**. "Basically, you represent attacks against a system in a tree structure, with the goal as the root node and different ways of achieving that goal as leaf nodes."
- **OR nodes are alternatives** (any child suffices — Schneier's figures mark AND nodes explicitly; everything else is OR). **AND nodes are multi-step requirements** (all children needed — e.g., eavesdrop on the conversation *AND* get the owner to say the combination).
- **Values annotate leaves and propagate up.** Boolean: I (impossible) / P (possible) — OR is possible if *any* child is possible; AND only if *all* are. Other Booleans: easy/difficult, expensive/inexpensive, intrusive/nonintrusive, legal/illegal, special-equipment/no-special-equipment. Continuous: **cost — OR takes the cheapest child, AND sums its children**; probability of success; likelihood the attacker tries it.
- **Multi-attribute queries are the payoff:** cheapest attack requiring no special equipment; cheapest low-risk attack; most likely nonintrusive attack. "Every time you query the attack tree about a certain characteristic of attack, you learn more about the system's security."
- **Marry the tree to attacker knowledge.** "Different attackers have different levels of skill, access, risk aversion, money, and so on." Organized crime, terrorists, and bored grad students get different pruned trees.
- **Countermeasure what-if games:** raise a leaf's cost (e.g., make bribery expensive), recompute the root, see whether the goal's cost moved. Defenses are evaluated by how much they raise the *cheapest* path, not by how many paths they touch.
- **Knowledge capture and reuse:** completed subtrees become library components for larger trees. Schneier's PGP example carries the famous lesson: the things people worry about (RSA key length) are rarely the cheapest attack — "Increasing the key length from 1024 bits to 2048 bits is like putting an enormous stake into the ground and hoping the enemy runs right into it, as opposed to building a lower palisade around the target."

**How this differs from FTA [VC]:** FTA's basic events *happen*; attack-tree leaves are *chosen*. FTA multiplies independent probabilities; attack trees propagate attacker cost and the attacker takes the min over OR branches. FTA asks "how can this fail?"; attack trees ask "how would *someone* make this fail, cheapest first?"

**Formal extensions (real, for the record):**
- Mauw & Oostdijk gave attack trees their formal semantics (cited in the attack-tree literature as the definitional reference) [HC].
- Buldas, Laud, Priisalu, Saarepera & Willemson (2006), "Rational Choice of Security Measures via Multi-Parameter Attack Trees" — multi-parameter evaluation (cost, probability, gain) for *choosing* countermeasures economically [HC].
- Kordy, Mauw, Radomirović & Schweitzer (2010), "Foundations of Attack–Defense Trees" (FAST'10) — adds **defense nodes** with a counter gate: a defense node blocks the attack node it counters, modeling the attacker–defender interaction as a two-player game. Our §5 mitigation mapping is an informal attack-defense tree in exactly this spirit [HC].
- Predecessor worth knowing: threat trees by Jonathan Weiss (Bell Labs, 1982, for MIL STD 1785) — Schneier popularized the method for computer security; he did not invent tree-structured threat modeling [HC, via Wikipedia].

---

## 2. The attack tree: "execute a tier-3 action without genuine user approval"

*Root definition (same as Cycle 4): a tier-3 action's side effects occur, and no genuine user approval authorized that specific action. "Genuine" covers both signal and consent — a real click on a deceived user still satisfies the root.*

```
ROOT: Attacker gets a tier-3 action executed without genuine user approval
│
├─ A (OR): Prompt-injection path — corrupt what the agent believes (refines FTA B4)
│   ├─ A1 (AND): Inject via tool output
│   │   ├─ a1.1: publish attacker-controlled content (web page, API response, file)
│   │   ├─ a1.2: get the agent to retrieve it in a relevant task context
│   │   └─ a1.3: embedded directive survives parsing into the agent's context
│   ├─ A2 (AND): Inject via user-handled document
│   │   ├─ a2.1: plant directive in email / PDF / spreadsheet / chat message
│   │   └─ a2.2: user asks JARVIS to summarize / act on that document
│   ├─ A3 (AND): Memory poisoning (slow burn)
│   │   ├─ a3.1: get false instruction persisted to memory (via A1/A2 or direct chat)
│   │   ├─ a3.2: have it retrieved at the moment of a tier-3 decision
│   │   └─ a3.3: retrieved without provenance or provenance ignored
│   ├─ A4: Reclassify the action's tier (3→1/2) so the gate never fires
│   │        └─ depends on A1/A2/A3 succeeding first (enabler, not standalone)
│   └─ A5: Forge "already approved" provenance ("the user approved this earlier")
│          └─ depends on A3 (memory) or chat-history injection
│
├─ B (OR): UI-deception path — corrupt what the user consents to (refines FTA B7)
│   ├─ B1a (AND): Clickjacking on the trusted dialog
│   │   ├─ b1a.1: render deceptive overlay/underlay around the approval dialog
│   │   └─ b1a.2: user's click lands as approval of the attacker's action
│   ├─ B1b: Payload laundering — real dialog, false description
│   │        (dialog shows "clean temp files"; action deletes documents)
│   │        └─ enabler: A1/A2 (injection writes the description) — the hybrid path
│   └─ B2: Notification spoofing — fake "JARVIS needs approval" OS notification
│          routing the user into an attacker-shaped flow
│
├─ C (OR): Replay path — reuse a genuine approval (refines FTA B8)
│   ├─ C1 (AND): Capture a live approval token AND replay it against a different action
│   │   └─ requires: read access to token store / process memory / transit
│   ├─ C2: Exploit unbound token design (one token authorizes any action)
│   │        └─ design-flaw variant; dead if tokens bind action hash
│   └─ C3 (AND): TOCTOU swap — genuine approval for action X, substitute action Y
│        before dispatch (crosses FTA B3)
│        └─ requires: token NOT bound to action hash, or check/dispatch not atomic
│
├─ D (OR): Log-forgery path — fabricate the audit trail (refines FTA B9)
│   ├─ D1 (AND): Rewrite the event log with a valid hash chain
│   │   ├─ d1.1: obtain write access to the log store
│   │   └─ d1.2: recompute the chain from the forged entry (readable prior hashes suffice)
│   ├─ D2: Compromise the log verifier/reader rather than the log
│   └─ D3: Delete/rotate the log post-execution (destroys evidence; enables repeat)
│
└─ E (OR): Manufactured-consent path — corrupt the user's judgment (adversarial B10/B11)
    └─ E1 (AND): Prompt-burst fatigue attack
        ├─ e1.1: induce a burst of low-stakes approval prompts (via A1/A2 content)
        ├─ e1.2: slip the tier-3 action into the burst
        └─ e1.3: user auto-approves without reading (rubber-stamping on demand)
```

### Leaf-by-leaf: prerequisites, blocking defense, residual gap

| Leaf | Attacker prerequisites | Existing defense that blocks it | Residual gap |
|---|---|---|---|
| a1.1–a1.3 (tool-output injection) | Publish content; agent fetches it | R2: gate enforced in deterministic code on the *actual action object* — reclassification (A4) cannot bypass the gate; REA untrusted-content markers; hardened_runner 13-attack suite | [HC] R2 blocks *gate evasion*, not *payload laundering* — see B1b. Injection still reaches the dialog description |
| a2.1–a2.2 (document injection) | Get a document in front of the user | Same as A1 | Same as A1 — plus: documents the user *wrote themselves* are trusted; attacker needs only to get the user to forward/open |
| a3.1–a3.3 (memory poisoning) | Content written to memory; retrieval at decision time | Memory quarantine + provenance tags + verify-before-acting (Cycle 4, Tree 4: three-element AND) | [MC] Any one dropped layer collapses the cut set to size 2 (Cycle 4). No stated test that provenance survives retrieval |
| A4 (tier reclassification) | A1/A2/A3 first | B6 false by construction (R2); Z3 proof of permission monotonicity (C2) | [MC] Z3 proves monotonicity of the *permission model* — if the tier label is computed outside the proven model (e.g., brain-emitted tier routed by the dispatcher), the proof doesn't cover it. Tier must be derived deterministically from the action schema |
| A5 (forged "already approved") | Poisoned memory or chat history | Approval tokens are live single-use nonces — "was approved" is not a claim the gate accepts from context | [HC] Holds **only if** no code path treats conversational claims of prior approval as sufficient. One `if user_said_approved` shortcut reopens it — needs a code-level audit rule |
| b1a.1–b1a.2 (clickjacking) | Render overlay in HUD/WebView; timing | Tauri trusted-chrome dialog (outside web content) | [SP] Depends on the unresolved frontend spike (Cycle 4): if the HUD allows content overlay near the dialog, the "trusted chrome" claim needs OS-level always-on-top + input isolation to hold |
| B1b (payload laundering) | A1/A2 to author the description | **None stated** — the "visible payload" defense assumes the payload shown is faithful | **[HC] FINDING 1** — see §5 |
| B2 (notification spoofing) | Notification API exposure | Tauri trusted-chrome dialog (approval only counts from the real dialog) | [MC] Holds only if the dialog is the *sole* approval channel and notifications can't deep-link into an approval flow |
| C1 (token capture+replay) | Read access to token store/memory | Single-use nonces bound to (action hash, timestamp) | [MC] "Used" set integrity — see FINDING 4, §5 |
| C2 (unbound token) | Design flaw exists | Bound to action hash by design | [HC] Dead *by design intent* — needs a design-review check that no legacy/unbound token path survives |
| C3 (TOCTOU swap) | Race timing or token-store read | Token embeds action hash; check-and-dispatch synchronous (no await/IPC/UI round-trip between) | [MC] The "synchronous" requirement must survive the real IPC design (Cycle 4 [UK]) — any async hop reopens it |
| d1.1–d1.2 (log rewrite) | Write access to log store | Hash-chained append-only log (tamper-*evident*) | **[HC] FINDING 2** — evident ≠ resistant; no external anchor stated — see §5 |
| D2 (verifier compromise) | Code/config access to the reader | Dependency pinning, SBOM, code review (Cycle 4, B2 row) | [MC] Same supply-chain posture as B2; no log-specific verifier hardening named |
| D3 (log deletion) | Write/delete on log store | Append-only design intent | [SP] "Append-only" in SQLite is a discipline, not a property — needs OS-level enforcement or remote anchoring to be real |
| e1.1–e1.3 (burst fatigue) | Ability to generate prompts (via A1/A2) | Anomaly-flagging of approval prompts; sliding-scale autonomy (fewer, higher-stakes gates) | **[MC] FINDING 3** — no burst threshold specified — see §5 |

---

## 3. Attacker economics: cheapest path first [MC]

Schneier's propagation rule, applied qualitatively (no invented dollar values — Cycle 4's false-precision rule stands): **OR = cheapest child; AND = sum of children.** Ranked by total attacker cost in skill × access × time × detection risk, for the §0 attacker:

| Rank | Path | Cost drivers | Status vs. current defenses |
|---|---|---|---|
| 1 | **E1 + B1b: burst-fatigue + payload laundering** | Publish a web page or send an email; no privilege; exploits rubber-stamping (Google Research, "Open and Emergent Problems in Agentic Privacy and Security", Oct 2026, 65 authors — Open Problem 9.2: notice-and-choice ineffective for agents, consent fatigue) | **Cheapest AND least defended** — FINDING 1 + FINDING 3 |
| 2 | **A2: document injection** | User hands the attacker content directly to the agent; one step | Gate evasion blocked by R2; laundering value feeds path #1 |
| 3 | **A1: tool-output injection** | Publish + wait for fetch; slightly less reliable than A2 | Same as A2 |
| 4 | **B2: notification spoofing** | Needs notification-surface exposure; moderate reliability | Blocked *if* the trusted dialog is the sole approval channel |
| 5 | **A3: memory poisoning** | Multi-step, slow; write-then-retrieve timing | Three-layer AND (quarantine + provenance + verify) — most expensive injection variant |
| 6 | **B1a: clickjacking** | Rendering capability + precise timing | Blocked *if* trusted-chrome input isolation holds (unresolved spike) |
| 7 | **C3: TOCTOU swap** | Race timing or token-store read | Blocked *if* check-and-dispatch stays synchronous and tokens bind action hash |
| 8 | **C1: token capture + replay** | Read access to token store / process memory — already a deep compromise | Blocked by single-use binding; residual = nonce-store integrity (FINDING 4) |
| 9 | **D1: log rewrite** | Write access to the log store — at this point the attacker owns the PC's file layer; the log is no longer the game | Tamper-evident only; no anchor (FINDING 2) — but note: cheapest-path logic says the attacker never *needs* this path while #1 exists |

**The backlog, in one line:** the attacker never bothers with cryptography-grade attacks (log-chain forgery, token theft) while **deceiving the user about what they're approving costs a web page**. This is Schneier's PGP lesson replayed: the RSA-key-length equivalent here would be hardening the hash chain while the dialog description is brain-written.

**What the economics reveal that the FTA hid [HC]:** Cycle 4's cut set {B4, B6} reads as "injection needs a second failure — second-order, deprioritize." The attack tree shows the attacker *reframes*: B4 doesn't need B6 if the objective shifts from "defeat the gate" to "get a genuine approval for a misdescribed action." FTA's AND gate is a **one-time cost** to the attacker (beat code enforcement once, in design review — actually they don't even need to beat it), not a per-attempt independent probability. **Cut-set size measures defender redundancy; it does not measure attacker cost.** That is the precise technical content of "FTA assumes independence, which is false for adversaries."

---

## 4. Where attack trees beat FTA, and vice versa

**Division of labor [HC]:**

| | FTA | Attack trees |
|---|---|---|
| Models | Accidents: bugs (B1), races (B3), design flaws (B6), random human error | Adversaries: deliberate, adaptive, cost-minimizing attackers |
| Core question | "How can this fail?" | "How would *someone* make this fail, cheapest first?" |
| Composition | AND = redundancy (multiply probabilities); OR = alternative failures (add) | AND = multi-step effort (sum costs); OR = attacker choice (take cheapest) |
| Prioritized output | Minimal cut sets — smallest failure combinations first | Cheapest attack paths — lowest attacker cost first |
| Countermeasure test | Does it add an AND gate / shrink a cut set? | Does it raise the *cheapest* path's cost? (Schneier's what-if game) |
| Natural quantification | After production data (Cycle 4 §4) | Attacker-cost / probability-of-attempt estimates (Buldas et al. 2006 multi-parameter) |
| Completeness story | Team exercise; misses branches | Iterative over months, multi-analyst; "there's always the chance you forgot an attack" (Schneier) |

**What breaks when one tree mixes both [HC]:**

1. **Probability semantics collapse.** You cannot multiply an attacker's deliberate choice by a bug's random rate and call the product a probability. The AND/OR propagation rules are *different math* for the two trees (probability vs. cost-minimization) — a mixed tree propagates neither correctly.
2. **Cut-set ordering misleads.** {B4, B6} size 2 looks "safe" in FTA; the attacker reads it as "skip B6 entirely, route around via B1b+E1." A mixed tree lets the defender believe redundancy exists where the attacker sees a detour.
3. **Mitigations get misclassified.** Testing and contracts (B1's mitigation) reduce *random*-failure probability and do **nothing** against an adaptive adversary who routes around the tested path. In a mixed tree, "we tested the gate" reads as progress against attackers. It isn't.
4. **The root question splits.** "How can this fail?" (exhaustive, neutral) vs. "how would someone break this?" (adversarial, economic) — a tree that asks both answers neither cleanly, because the adversary's branch selection violates the neutrality the FTA branches assume.

**Working rule [HC]:** keep two trees, cross-reference shared nodes. FTA owns the random-failure skeleton (does the gate work when nobody is attacking?). The attack tree owns the adversarial branches (does the gate hold when someone is trying to break it?). Cycle 4's B4/B7/B8/B9 appear in *both* — as random-failure basic events in the FTA and as attacker-refined subtrees here. When a defense is added, update both: the FTA cut set *and* the attack path cost.

---

## 5. Mitigation mapping and findings

For each path in cost order (§3), the concrete defense — existing or proposed. **A path with no current defense is a finding.**

| Rank | Path | Existing defense | Proposed / required | Verdict |
|---|---|---|---|---|
| 1 | E1+B1b fatigue + laundering | Anomaly-flagging (named, unspecified); visible payload (unfaithful — see gap) | **Deterministic payload renderer**: dialog text built from the action object (type + target + parameters, machine-formatted); any brain-generated description labeled untrusted. **Burst detector**: N approvals in T minutes → step-up friction (re-read prompt, cooldown) | **FINDING 1 [HC]**: no defense ensures dialog-description fidelity. **FINDING 3 [MC]**: no burst threshold specified |
| 2–3 | A1/A2 injection | R2 (gate on action object); REA markers; hardened_runner 13-attack suite | Keep B6 false by construction; add code-review rule: no `if user_said_approved` / context-claim authorization paths (closes A5) | Covered for gate evasion; laundering value flows to #1 |
| 4 | B2 notification spoof | Trusted-chrome dialog as sole approval channel (design intent) | Design rule: notifications may *inform*, never carry an approval action or deep-link into one | Covered by intent; needs the rule written down [MC] |
| 5 | A3 memory poisoning | Quarantine + provenance + verify-before-acting | Regression test: provenance tags survive retrieval; never drop two layers (Cycle 4, Tree 4) | Covered; brittle to schedule pressure [MC] |
| 6 | B1a clickjacking | Trusted-chrome dialog | Frontend spike must verify OS-level always-on-top + input isolation; otherwise treat as open | Blocked conditionally [SP] |
| 7 | C3 TOCTOU | Action-hash-bound token; synchronous check-and-dispatch | Preserve synchronicity through the real IPC design; re-verify after every IPC refactor | Covered by requirement; [UK] real IPC surface |
| 8 | C1 replay | Single-use nonce bound to (action hash, timestamp); 30s undo buffer as backstop | **FINDING 4 [MC]**: keep the used-nonce set in the gate's integrity domain (process-private memory), never in a store the log layer shares; un-burning a nonce must be impossible without gate-process compromise | Gap: nonce-store integrity unspecified |
| 9 | D1 log rewrite | Hash-chained append-only log (tamper-evident) | **FINDING 2 [HC]**: (a) design rule — the gate NEVER consults the log as proof of approval; authorization consumes the live token only; the log is audit-only. (b) external anchor for the chain (remote hash publication or OS-protected append-only store); without it, "tamper-evident" is honor-system against a writer | Gap: no anchor; authorization-vs-audit separation unstated |

### The findings (paths with no current defense)

- **FINDING 1 [HC] — Payload-description laundering.** Nothing guarantees the approval dialog shows a faithful description of the action. If the brain writes the description, prompt injection survives R2 by laundering what the user *sees* instead of evading the gate. Fix: deterministic payload renderer from the action object; brain text marked untrusted. This is the cheapest attack path with the weakest defense — P0.
- **FINDING 2 [HC] — Log as authorization oracle.** The hash chain is tamper-evident, not tamper-proof, and has no external anchor — a writer can rewrite it from genesis. If any code path treats "approval event in log" as authorization, D1 is a live bypass. Fix: gate consumes live tokens only; log is audit-only; add an anchor.
- **FINDING 3 [MC] — Manufactured fatigue unspecified.** Anomaly-flagging and burst rate-limiting are named but not specified; an attacker can manufacture consent via prompt bursts. Fix: concrete burst threshold + step-up friction; anomaly flags on unusual-for-user actions.
- **FINDING 4 [MC] — Nonce-store integrity.** Single-use is only single-use if the used-set can't be tampered with. Fix: process-private nonce set in the gate's integrity domain.

### What this analysis does NOT establish

- The cost ranking is ordinal expert judgment for the §0 attacker, not measured data — a different attacker (malicious insider, PC-compromised) re-ranks it [MC].
- Tree completeness is single-analyst best effort; Schneier's own warning applies — expect missing branches, refine iteratively [MC].
- Whether the Tauri trusted-chrome dialog actually defeats overlay/clickjacking is unresolved until the frontend spike [SP, carried from Cycle 4].
- No quantitative claim is made anywhere in this file, for the same reason as Cycle 4 §4: we have no empirical rates, and attacker costs are not probabilities [VC].

## References (all real, verified via live search)

- Schneier, B. (1999). Attack Trees: Modeling Security Threats. *Dr. Dobb's Journal*, 24(12), December 1999. Full text: http://www.schneier.com/academic/archives/1999/12/attack_trees.html?ref=blueprintcyber.com
- Buldas, A., Laud, P., Priisalu, J., Saarepera, M., & Willemson, J. (2006). Rational Choice of Security Measures via Multi-Parameter Attack Trees. In *CRITIS 2006*, LNCS 4347. https://research.cyber.ee/~janwil/publ/attacktree_with_estimations.pdf
- Kordy, B., Mauw, S., Radomirović, S., & Schweitzer, P. (2010). Foundations of Attack–Defense Trees. *FAST 2010*. https://www.slideshare.net/slideshow/foundationsofattackdefensetreespdf/257717730
- Mauw, S., & Oostdijk, M. — formal semantics of attack trees (definitional reference in the literature) [HC — cited, not directly fetched].
- Threat trees predecessor: Weiss, J., Bell Labs (1982), MIL STD 1785 work — via https://en.wikipedia.org/wiki/Attack_tree
- Companion: `~/workspace/jarvis-knowledge/learn-fault-trees.md` (Cycle 4) — FTA skeleton, cut sets, R2/AND-gate analysis this file builds on.
