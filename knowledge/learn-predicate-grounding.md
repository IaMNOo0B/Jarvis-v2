# Predicate Grounding at Execution Time — Phase ∞, Cycle 10

*Research cycle 10, written 2026-10-19. LEARNING ONLY — no code, no installs, no model calls. Contains design pseudocode as specification; nothing here was executed.*
*Confidence tags: [VC] >95% · [HC] 80–95% · [MC] 60–80% · [SP] 40–60% · [UK] unknown. **DESIGN** = derived from research, unmeasured.*

**Research question:** How are validator predicates grounded cheaply and safely at execution time?

**Answer in one paragraph:** By *classifying predicates by volatility and only re-checking the volatile ones*, *evaluating them in trusted grounding functions that never read data produced by the thing being checked*, and *collapsing the check-act gap* with three domain-specific mechanisms: (1) the classical open-then-check / handle-not-name doctrine for filesystem predicates (stat the fd, not the path); (2) the permission-snapshot protocol for approval-gated actions — the grant state is frozen at approval, bound to the idempotency key, and re-compared (never widened) at dispatch, failing closed on revocation; (3) version-pinning of contracts and manifests so validation and dispatch provably ran against the same model. The per-dispatch cost is O(volatile predicates) — typically 1–3 syscalls, microseconds — and the conformance harness from cycle 9 doubles as the grounding test oracle, closing the loop: the same functions the validator trusts at runtime are the ones the harness audits offline.

**§19 protocol followed:** audit (§1) → question (§2) → research (§3) → compare (§4) → derive (§5: the designs) → validate (§6: falsifiers) → integrate (§7: ADR) → record (§8) → reassess (§9).

---

## 1. Audit — what prior cycles established (referenced, not re-researched)

| Prior file | Contribution to this cycle | Status |
|---|---|---|
| `learn-plan-validation.md` (cycle 8) | The 4-check validator; tool-contract schema (preconditions/add_effects/tier/idempotent/compensation/requires_approval); **TOCTOU listed as breakage #2 with "dispatch-time re-check of preconditions" named but not designed**; the email-task worked example (§5.3) reused here as the worked re-examination; falsifier §8.277 flagging predicate-grounding cost as an open measurement. | Accepted as **problem statement and test fixture** |
| `learn-contract-conformance.md` (cycle 9) | Effect-diff procedure; tiered mocks; **§8.342 explicitly suggests this cycle**: the harness's `read_predicates` is the same function the dispatch re-check needs — the grounding functions get *one* implementation serving both roles. | Accepted; this cycle delivers the named function |
| `learn-formal-methods.md` | deal/beartype contracts; "runtime guards enforce." | Accepted; grounding functions are the runtime-guard analogues at plan-dispatch level |
| `learn-advanced-cs.md` | Filesystem jail (`is_inside_jail`); durable queue; idempotency keys. | Accepted; the snapshot protocol binds to the idempotency key from here |

**Genuinely new in this cycle:** the TOCTOU taxonomy for agent predicates (volatile vs stable classes); the four re-check strategies with a reversibility×volatility decision matrix; the grounding-registry schema (predicate → grounding fn → cost → volatility → re-check policy); the precise permission-snapshot protocol; the version-pinning rule; the re-examined email worked example.

---

## 2. The question, sharpened

Cycle 8 decided *that* preconditions get re-checked at dispatch; cycle 9 suggested the harness should test the same functions. Three sub-questions turn that into a design:

1. **Which predicates need re-checking at all?** (Re-checking `url_wellformed` per dispatch is pure waste; *not* re-checking `file_exists` is the hole. The answer is a classification, not a blanket policy.)
2. **What evaluates a predicate, and how do we know the evaluation isn't lying?** (The check itself is an attack surface: a predicate reading tool-produced state is a self-graded exam.)
3. **How do we bind an approval to an execution across a time gap?** (The human taps "approve" at T₀; dispatch happens at T₁; a revocation in between must fail closed — not silently proceed, not silently die in a confusing way.)

---

## 3. Research — the genuinely new evidence

### 3.1 The classical doctrine: names rot, handles don't

The foundational TOCTOU paper is **Bishop & Dilger, "Checking for Race Conditions in File Accesses," USENIX Computing Systems, Spring 1996** [VC — verified via usenix.org archive]: *"flaws due to race conditions in which the binding of a name to an object changes between repeated references occur in many programs."* Their framing is the one that transfers: the vulnerability is never "the check was wrong" — it's that **check and use referenced the world through a re-resolvable name**. CWE-367's formalization (MITRE, status Stable) says the same thing in policy language: the product *"assumes that P is immutable between the check and the manipulation,"* and the flaw is an actor modifying the *"assumed-immutable property"* in the window [VC — verified via cwe.mitre.org structured descriptions].

Two doctrines fall out, both field-standard:

- **Open-then-check, never check-then-open.** The MathWorks/CWE-367 guidance states it bluntly: *"Before using a file, do not check its status. Instead, use the file and check the results afterward"* [HC — vendor CWE-367 rule documentation, mechanism independently sound]. In our terms: the grounding for `file_exists(path)` that is *safe* is not `os.path.exists` followed by open — it is **open the fd, then fstat the fd**. Once you hold the descriptor, the name-binding attack surface collapses: no symlink swap, no rename, no delete can redirect *your* handle (the fd refers to the inode, not the path) [VC — POSIX semantics].
- **Resolve once, operate relative.** `openat2(2)` with `RESOLVE_BENEATH` / `RESOLVE_NO_SYMLINKS` (Linux 5.6+, 2020), `O_NOFOLLOW`, and fd-relative `*at()` syscalls are the OS's own check-act collapse: path resolution becomes a single atomic step with policy enforced *during* resolution, not before it [VC — standard Linux API]. This is the mechanism behind cycle 8's filesystem jail (`is_inside_jail`): the jail is only TOCTOU-safe if the final open is done with resolution-beneath semantics on the opened dirfd, not by string-checking the path and opening separately — a string check is exactly the name-based check the doctrine forbids.

### 3.2 Capabilities: the check that can't go stale

The deepest TOCTOU result is architectural, not procedural: **a capability token collapses check and use by construction** — possession of an unforgeable reference *is* the authorization, evaluated at the moment of use, so there is no check-time for a use-time to drift from [HC — standard capability-security result, e.g. the object-capability literature; the mechanism is definitional]. Practical echoes: file descriptors (a held fd cannot be revoked by a rename), database row locks held to commit, compare-and-swap tokens (etags/CAS: the *token itself* is the version check — `UPDATE … WHERE version = :token` makes the check and the mutation one atomic statement) [VC — SQL atomicity semantics].

The permission-snapshot protocol (§5.3) is the deliberate *poor-man's capability*: where we cannot issue true capabilities (the Gmail API won't hand us a revocable token), we freeze the authorization basis at approval time and re-compare it atomically-ish at dispatch. It inherits the capability's fail-closed property without requiring capability infrastructure.

### 3.3 Counters and budgets: atomic decrement, not check-then-decrement

Budget predicates (`quota_remaining ≥ cost`, `rate_limit_ok`) are the agent-world instance of the oldest TOCTOU class: check-then-act on a shared counter. The field answer is never "re-check more often" — it is **make the decrement conditional and atomic**: SQL `UPDATE budget SET remaining = remaining - :cost WHERE id = :k AND remaining >= :cost` and check the affected-row count; in-memory, CAS loops; distributed, a lease or a fencing token [VC — standard concurrency practice; the same shape as double-spend prevention in payments]. For JARVIS this means: budget enforcement must live in the *durable queue's* atomic dequeue step (learn-advanced-cs.md's SQLite queue), not as a validator predicate at all — a predicate evaluated in two places is a race waiting to happen. **Predicates that guard a scarce resource should be enforced by the resource's own atomic operation, with the validator's predicate serving only as the pre-flight hint** [DESIGN — derived from the counter literature].

### 3.4 Leases and locks: buying a check-act window

When no atomic primitive exists, the classical answer is a **lease/lock on the window**: `flock`/`lockf` for files (with the permanent caveat that POSIX locks are *advisory* — they bind only cooperating processes, and NFS `flock` is folklore-unreliable) [VC], Chubby-style distributed locks with timeouts for the networked case (Burrows, "The Chubby lock service for loosely-coupled distributed systems," OSDI 2006) [VC — the canonical lease paper]. The cost is real: acquisition latency, deadlock risk, lock-holder crash handling. **Rule of thumb from the literature: locks are the most expensive correct answer; reach for them only when (a) no atomic primitive exists and (b) the action is irreversible** — which is exactly the bottom-right cell of the §5.2 matrix.

### 3.5 What the literature says about *our* specific gap

Bishop & Dilger's detection work was *static* (find check-use pairs on names); the USENIX Security '03 follow-up line ("Dynamic Detection and Prevention of Race Conditions in File Accesses") suspends the interfering operation to shrink the window — i.e., even the research community treats window-shrinking (our strategy b) as the deployable answer and window-elimination (strategy a) as the special case [HC — verified via usenix.org program listing]. Nothing in the classical literature addresses the *approval-to-execution* gap (§2, sub-question 3) because classical TOCTOU assumes a single process; the snapshot protocol (§5.3) is our genuinely new piece, built on the capability intuition (§3.2) rather than cited from prior art — tagged [DESIGN] honestly.

---

## 4. Compare — the four re-check strategies

| Strategy | Shape | Cost/latency | Correctness claim | When it wins |
|---|---|---|---|---|
| **(a) No-gap critical section** | Check and act in one atomic op (fd-handle use, CAS update, `RESOLVE_BENEATH` open) | ~0 marginal — the check *is* the act | Window eliminated, not shrunk [VC] | Filesystem identity/permission facts; budget counters (atomic decrement) |
| **(b) JIT re-check** | Re-evaluate volatile predicates immediately before the call | O(volatile preds): 1–3 syscalls, µs; ms for network probes | Window shrunk to ~µs; residual race is adversarial-only | The default for volatile environment facts (file existence, network reachability) |
| **(c) Optimistic + verify-after** | Act, then diff observed vs declared effects, compensate on mismatch | Failure-rate × compensation cost; ~0 added latency on the happy path | Catches everything *reversible*; proves nothing before an irreversible act | Already adopted (cycles 7–8); right for reversible/compensable steps |
| **(d) Lease/lock the window** | Acquire lock → check → act → release | Acquisition latency + deadlock/crash-holder risk; advisory-only on POSIX | Window held shut for cooperators | Shared mutable resources, irreversible acts, no atomic primitive — rare |

**The comparison that decides the design:** (a) dominates wherever an atomic primitive exists, so the registry's first job (§5.1) is to route each predicate to its primitive; (b) is the universal fallback and is *cheap enough to be unconditional* for syscall-class predicates; (c) stays as the completeness backstop (it catches what predicates can't name — cycle 8's breakage #1); (d) is gated behind the irreversibility×high-volatility cell. No strategy is chosen globally — the choice is per-predicate, recorded in the registry.

---

## 5. Derive — the designs

### 5.1 The TOCTOU taxonomy: which predicates are vulnerable

| Class | Examples | Volatility | Re-check? | Why |
|---|---|---|---|---|
| **Static/tool facts** | `tool_exists(name)`, `schema_valid(args)`, `tier ≤ manifest` | Stable | Validate-only | The registry is versioned (§5.4); change invalidates the plan wholesale, no per-dispatch re-check needed |
| **Syntactic facts** | `url_wellformed(u)`, `valid_address(to)`, `path_inside_jail(p)` (string form) | Stable | Validate-only | Pure functions of the arguments; the arguments are frozen in the dispatch record |
| **Filesystem state** | `file_exists(p)`, `file_hash(p)`, `dir_listed(d)` | **High** | **JIT (b), via fd-collapse (a) where possible** | Any process/user can mutate; the Bishop & Dilger name-binding class |
| **Permission/grant state** | `grant(skill, scope)`, `connector_connected(x)` | **High** | **Snapshot-bind (§5.3)** | Revocation is a human-speed event with machine-speed consequences |
| **Network availability** | `network_available`, `host_reachable(h)` | High | JIT probe (b); treat probe as hint — the call's own error handling is the real check (open-then-check doctrine) | Probes lie (captive portals, flaky DNS); never gate an irreversible act on a probe alone |
| **Budget/counter state** | `quota_remaining ≥ cost` | **High** | **Atomic enforcement (a)** at the queue, not a predicate | Check-then-decrement is the textbook race; see §3.3 |
| **Facts established by this plan** | `file_exists(p)` where step k < n created p | Low (but **nonzero**) | JIT, but cheap path: the dispatcher *holds the fd* from the creating step — re-fstat, don't re-resolve | "We just wrote it" is not a safety argument against external actors; but the fd makes the re-check O(1) and name-race-free |
| **Semantic/human facts** | `correct_recipient(to)`, `user_intends(goal)` | Uncheckable | **No grounding — escalate** | Faking a grounding here is worse than admitting the gap (cycle 8's admitted residual) |

**The load-bearing row is the second-to-last:** predicates the plan itself established are the ones a naive "skip re-check for self-established facts" optimization would exempt — and that exemption is precisely wrong under an adversarial filesystem. The fd-holding rule keeps the exemption's performance while refusing its unsafety.

### 5.2 The re-check decision matrix (reversibility × volatility)

|  | **Stable** | **Low volatility** | **High volatility** |
|---|---|---|---|
| **Reversible** (read tier) | validate-only | (b) JIT or (c) verify-after — pick cheaper | (b) JIT; (c) as backstop |
| **Compensable** (write tier) | validate-only | (b) JIT + compensation armed | (b) JIT + verify-after (c) with compensation armed |
| **Irreversible** (dangerous, no compensation) | validate-only | **(b) JIT mandatory** + snapshot where grants involved | **(b) JIT mandatory + (d) lock if no atomic primitive; snapshot-bind mandatory for grant predicates** |

Two readings: across each row, volatility only ever *adds* re-checking, never removes the column's baseline; down the irreversible column, the requirement ratchets from "re-check" to "re-check *and* bind." The irreversible×high-volatility cell is the only place strategy (d) is authorized — everywhere else its cost is unjustified.

### 5.3 The grounding registry

One record per predicate. **The grounding function is trusted, developer-written, audited-once code that runs in the dispatcher/harness process — never the LLM, never the tool under check** [DESIGN — the trust rule is the whole point]:

```yaml
predicate: file_exists
args: [path]                       # binds to contract arg indices
grounding_fn: groundings.fs.file_exists_fd   # open(O_NOFOLLOW|RESOLVE_BENEATH)+fstat; returns (bool, fd?)
cost_class: syscall                # pure | syscall | probe_ms | oracle
volatility: high
recheck_policy: jit_fd_hold        # validate-only | jit | jit_fd_hold | snapshot_bind | atomic_enforce | escalate
adversarial_note: "path may be attacker-influenced; never stat the string twice — resolve once, hold fd"
tested_by: conformance.harness.read_predicates  # cycle-9 symmetry: the oracle tests the grounding
version: 3
```

Registry rules [DESIGN]:

1. **Trust-domain separation.** A grounding may read OS primitives (`stat`, `fstat`, `getfacl`, bounded socket probe, SQLite), the dispatch record, and the permission ledger. It may **never** read a tool's stdout, return value, or side-channel output as evidence for that tool's own predicates. A grounding that grades its own tool's homework is rejected at registry review.
2. **Total and bounded.** Groundings are pure-ish functions: no LLM calls, no unbounded network, no user interaction. A grounding that can hang can stall dispatch — `probe_ms` class groundings carry a hard timeout (default 250 ms); on timeout the predicate evaluates to *unknown*, and unknown fails closed per the matrix row.
3. **One implementation, two callers.** The dispatch-time JIT re-check and the cycle-9 conformance harness's `read_predicates` call the *same* registry entries. If the harness's sandbox truth disagrees with a grounding, the grounding is wrong (oracle discipline) — this is the symmetry cycle 9 asked for, and it means grounding bugs are found offline, not in production.
4. **Cost budget.** The dispatcher's per-step grounding budget is O(volatile predicates) syscalls — for the email task (§5.5), two `fstat`s and one in-memory version compare: single-digit microseconds, unmeasurable against tool-call latency. If a future tool's volatile set exceeds ~10 syscall-class predicates, the contract is too fine-grained — coarsen it (design smell, cf. cycle 8 §5.4).
5. **Unknown fails closed.** Three-valued logic: true / false / unknown. `false` → REJECT with counterexample (replan may fix it). `unknown` → ABORT with escalation (replan cannot fix what we cannot see). This distinction is load-bearing: conflating them either replans forever or acts blind.

### 5.4 The permission-snapshot protocol (precise)

**Parties:** the approver (Owais, via approval card), the dispatcher, the permission ledger. **Threat:** grant revoked (or narrowed) between approval T₀ and dispatch T₁.

```
APPROVAL (T₀, on the approval card tap):
  A = {
    approval_id:   uuid(),
    plan_id, step_index,
    action_sig:    H(tool_name, normalized_args),   # what was approved, exactly
    basis:         { grant_predicates true at T₀ }, # e.g. {grant(email_send, mailbox=work),
                                                   #        connector_connected(gmail),
                                                   #        quota_remaining ≥ cost}
    versions:      {contract_version(tool), manifest_version, policy_version},
    idempotency_key: H(plan_id, step_index, action_sig),   # same key as the durable queue row
    expires_at:    T₀ + SNAPSHOT_TTL,               # default 15 min [DESIGN — policy choice]
    consumed:      false
  }
  ledger.append(A)

DISPATCH (T₁, immediately before the tool call):
  1. A = ledger.get(idempotency_key); abort("no approval") if missing
  2. abort("approval expired — re-approve") if now > A.expires_at
  3. abort("approval already consumed") if A.consumed        # double-spend guard
  4. live = evaluate(basis predicates, via registry, JIT)     # the re-check
  5. if live ⊉ A.basis:                                      # any basis predicate now false/unknown
       → FAIL CLOSED: abort step, mark plan INVALIDATED,
         escalate("grant revoked or narrowed since approval; re-approval required")
  6. if live ⊋ A.basis (strictly wider — new grants appeared):
       → IGNORE the widening; authority is exactly A.basis   # no privilege creep
  7. A.consumed = true  (atomic with the queue's dequeue — §3.3)
  8. execute tool call
  9. on crash between 7–8: retry replays bind to the SAME consumed A
     (idempotency — never mints a new grant, never re-executes the side effect twice)
```

**Why compare the snapshot instead of just re-checking live state:** a bare live re-check answers "is sending allowed *now*" — but the approval authorized a *specific basis*. If the basis narrowed (scope reduced from `mail:*` to `mail:read`), the live check "grant exists" still passes while the authorized action no longer is. The subset comparison (step 5) catches narrowing; the no-widening rule (step 6) catches the reverse — a grant *added* between approval and dispatch must not authorize an action the human never saw. **Fail-closed means: any divergence between approved basis and live basis, in either direction, aborts.** [DESIGN]

**The TTL (step 2) is a policy choice, not a derived constant** [UK — the right value depends on Owais's approval UX latency; 15 min is a starting default, measurable once the approval card ships]. Without a TTL, a tapped approval is a standing grant — the snapshot would be security theater.

### 5.5 The version-pinning rule

Validation runs against a version vector `V = (contract_version per tool, manifest_version, policy_version)` captured at validation time and stored on the dispatch record. **Before each dispatch: if current V′ ≠ V → the plan is INVALIDATED → re-validate (O(plan), microseconds — cycle 8's bound) → new V.** [DESIGN]

This closes the validator's own TOCTOU (sub-question territory from the task brief): the validator reads contracts and the manifest; if a contract is amended mid-validation, the plan it validated no longer describes the tools that will run. Pinning makes "validated against model M, executing against model M" a checked invariant rather than a hope. Long plans (>~10 steps, per cycle 8's frame-problem row) additionally re-pin at a mid-plan checkpoint — same mechanism, scheduled.

Note the layering: version-pinning covers *model* drift (contracts, manifest, policy); the snapshot protocol covers *world* drift on grants; JIT re-check covers *world* drift on environment facts. Three clocks, three mechanisms, no gaps.

### 5.6 Worked example — the cycle-8 email task re-examined

**Task:** "Download the Q3 report, extract the revenue table, and email it to Priya." Accepted plan P′ (3 steps). Predicate-by-predicate grounding assignment:

| Step | Predicate | Class (§5.1) | Grounding / strategy | What happens on drift |
|---|---|---|---|---|
| 1 `http_fetch` | `network_available` | High (network) | (b) JIT probe, 250 ms timeout; the fetch's own error handling is the real check | probe unknown → ABORT+escalate (not silent retry-loop) |
| 1 | `url_wellformed(url)` | Stable | validate-only | — (args frozen) |
| 1→2 | `file_exists(/tmp/q3.pdf)` (established by step 1) | Low-but-nonzero | **(a)-flavored: dispatcher holds the fd** step 1 returned; step 2's grounding fstats the held fd | external delete → fd still valid, open file description survives unlink [VC — POSIX]; step 2 proceeds correctly on the *same bytes* validation saw |
| 2 `pdf_extract_table` | `file_exists(path)` | (as above) | fd-hold re-check | — |
| 2→3 | `file_exists(…/revenue-q3.csv)` | Low-but-nonzero | fd-hold re-check | — |
| 3 `email_send` | `network_available` | High | (b) JIT probe | unknown → ABORT before the irreversible act |
| 3 | `valid_address(to)` | Stable | validate-only | — |
| 3 | `file_exists(attachment)` | High (external actor may delete between extract and send) | **(b) JIT: re-resolve + open** (no fd was held across the approval gap — the approval card is a human-speed pause) | deleted → REJECT(3, precondition) with machine counterexample → replan re-runs extract; **never** sends a missing-attachment email, **never** crashes on ENOENT |
| 3 | grant basis for `email_send` | High (permission) | **Snapshot-bind (§5.4)**: basis frozen at Owais's tap — `{grant(email_send, mailbox=work), connector_connected(gmail), manifest_version=42}` — bound to the idempotency key | Gmail disconnected between tap and dispatch → live ⊉ basis → **FAIL CLOSED**: abort, "connection revoked since approval — re-approve", no send, no silent drop |

**What fails closed, in one line each:** revoked connector → abort+escalate (snapshot step 5); deleted attachment → reject+replan (JIT precondition); network drop before send → abort (probe unknown); contract amended mid-plan → invalidate+re-validate (version pin). **What costs what:** the dispatch-time grounding bill for the whole plan is ~4 syscalls + 1 in-memory version compare + 1 ledger read — unmeasurable against three tool calls and one human approval tap.

**The case the design refuses to fake:** `valid_address(priya@example.com)` is grounded (syntactic, stable) but `correct_recipient` has no grounding — the registry marks it `escalate`, and the approval card is where the human supplies the uncheckable predicate. The snapshot binds the *address string*; if the LLM swaps the address post-approval, `action_sig` (step: normalized args) mismatches → abort. The human approved *that address*, not "an email."

---

## 6. Validate — falsifiers [DESIGN]

1. **Grounding latency at dispatch scale.** Measure per-step grounding time in the dispatcher. Kill threshold: if p99 grounding time exceeds 5 ms/step (i.e., becomes visible against tool-call latency), the cost classes are wrong — coarsen contracts or demote probe-class predicates to hints. Predicted: single-digit µs for syscall class.
2. **False-abort rate from JIT probes.** Run 1,000 dispatches with a flaky-network fixture; if network-probe `unknown`s abort >2% of otherwise-valid plans, the 250 ms timeout / probe design needs rework (or probes get demoted to advisory, with the tool's own error handling as the check — the open-then-check doctrine already anticipates this).
3. **The fd-hold exemption audit.** Fuzz: external actor unlinks/renames/symlink-swaps files between plan steps. The invariant under test: *no step ever operates on different bytes than validation saw.* Any violation means a grounding resolved a name twice — a registry bug, caught by the cycle-9 harness as oracle.
4. **Snapshot TTL calibration.** Once the approval card ships, measure approval-to-dispatch latency distribution. If p99 exceeds the TTL, users hit spurious "re-approve" friction — tune TTL from data, not from this document's 15-minute guess.
5. **Stale-snapshot attack drill.** Adversarial test: approve, revoke grant, attempt dispatch — must abort with the revocation message, never send, never silently skip. Approve, *widen* grant, attempt dispatch of an action outside the original basis — must abort (no-widening rule). Both are harness-testable without production.

## 7. Integrate — ADR

**Decision:** ADOPT the grounding registry (§5.3) as the single implementation serving both dispatch-time JIT re-check and the cycle-9 conformance harness's `read_predicates`; ADOPT the predicate volatility taxonomy (§5.1) and the reversibility×volatility decision matrix (§5.2) as the policy that assigns re-check strategies; ADOPT the permission-snapshot protocol (§5.4) for all `requires_approval` actions; ADOPT version-pinning (§5.5) on every dispatch record.

**Consequences:**
- The dispatcher gains a grounding engine: per step, evaluate only the volatile predicates, in registry order, within the per-step budget; three-valued logic with unknown-fails-closed.
- `requires_approval` tools cannot dispatch without a live, unexpired, unconsumed snapshot bound to the step's idempotency key — the approval card flow must mint snapshots (UX work, owned by the card design).
- Budget/quota enforcement moves out of predicates into the durable queue's atomic dequeue (SQLite `UPDATE … WHERE remaining >= cost`); the validator keeps the predicate as a pre-flight hint only.
- The registry is versioned data alongside contracts; grounding functions get the same review bar as deal contracts (cycle: formal-methods) and the same harness coverage as tools (cycle 9).
- Cycle 8's falsifier §8.277 ("whether predicate grounding stays cheap enough at dispatch scale") is now *measurable*: falsifier #1 above is its operationalization.

## 8. Record — evidence table

| # | Claim | Evidence | Confidence |
|---|---|---|---|
| 1 | TOCTOU = check/use through a re-resolvable name; the fix is handle-not-name | Bishop & Dilger 1996 (USENIX); CWE-367 structured description (cwe.mitre.org) | [VC] |
| 2 | Open-then-check: use the resource, check the result — never check-then-use on names | CWE-367 remediation guidance (MathWorks rule doc); `openat2`/`O_NOFOLLOW`/`RESOLVE_BENEATH` semantics | [HC] on the doctrine; [VC] on the syscall semantics |
| 3 | Capabilities collapse check and use (possession = authorization at use time) | Object-capability literature (definitional); fd/row-lock/CAS as instances | [HC] |
| 4 | Shared counters must be guarded by atomic conditional decrement, not check-then-act | Standard concurrency practice; SQL atomicity semantics | [VC] on the mechanism |
| 5 | Locks are the most expensive correct answer; POSIX locks are advisory-only | `flock(2)`/`lockf` semantics; Chubby (Burrows, OSDI 2006) for the lease pattern | [VC] on advisory caveat; [HC] on the cost heuristic |
| 6 | Window-shrinking (JIT re-check) is the deployable answer; window-elimination is the special case | USENIX Security dynamic-race-prevention line (suspend-interferer); field practice | [HC] |
| 7 | The snapshot protocol, TTL default, no-widening rule, fd-hold optimization | Derived in this cycle — no prior art cited | **[DESIGN]** — the genuinely new piece; needs falsifiers §6.4–6.5 |
| 8 | Unknown-fails-closed three-valued grounding logic | Derived; standard fail-closed design principle | [DESIGN] on the policy; [VC] on the principle |
| 9 | Registry/harness oracle symmetry (one implementation, two callers) | Cycle 9's `read_predicates` suggestion (§8.342); oracle-based testing discipline | [DESIGN] |

## 9. Reassess — what this cycle did and didn't do

**Did:** closed the last structural gap in the deterministic stack — every predicate class now has a named grounding strategy, a cost class, and a re-check policy; the approval-to-execution gap has a precise protocol instead of a hope; the validator's own model-drift has a pinning rule. The three clocks (model drift → version pin; grant drift → snapshot; environment drift → JIT) cover the TOCTOU surface with no overlaps and no gaps *that this cycle can see*.

**Didn't:** build or measure anything (learning only — all DESIGN tags are honest); pick the snapshot TTL from data (it's a guess awaiting the approval card's latency distribution); solve the adversarial-symmetric case where the *grounding's own* OS primitives lie (rootkit-class — out of scope, stated); ground semantic predicates (refused on principle, per cycle 8's boundary).

**Residual risks, stated not hidden:** (1) a grounding bug is a *trusted-code* bug — the registry review bar must match the deal-contract bar, because everything downstream trusts it; (2) the fd-hold optimization assumes the creating step returns a holdable handle — tools that don't will fall back to JIT re-resolve, which is safe but re-opens the µs window; (3) probe-class predicates (network) are hints wearing a check's uniform — the design admits this, but a future reader might not.

**Next cycle suggestion:** the measurement cycle — build the registry for the 5 most-used predicates (`file_exists`, `file_hash`, `grant`, `network_available`, `quota_remaining`), run falsifiers §6.1–6.3 against the cycle-9 harness, and calibrate the snapshot TTL from approval-card latency data. After that, the deterministic stack (validator + conformance + grounding) is specified end-to-end and the remaining work is engineering, not research.

---

*Cycle 10 closes the Phase-∞ deterministic verification stack: plan validation (8) proves the plan valid against the model, contract conformance (9) keeps the model honest, predicate grounding (10) keeps the model's predicates true at the moment of use. TOCTOU has nowhere left to hide that isn't named, measured, or admitted.*
