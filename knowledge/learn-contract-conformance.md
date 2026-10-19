# Contract-Conformance Testing — Phase ∞, Cycle 9

*Research cycle 9, written 2026-10-19. LEARNING ONLY — no code, no installs, no model calls. Contains design pseudocode as specification; nothing here was executed.*
*Confidence tags: [VC] >95% · [HC] 80–95% · [MC] 60–80% · [SP] 40–60% · [UK] unknown. **DESIGN** = derived from research, unmeasured.*

**Research question:** How do we test that a tool's declared contract matches its actual behavior?

**Answer in one paragraph:** By treating the contract as a *model* and the tool's sandbox behavior as the *system*, and applying the classic model-based testing triangle: (1) **effect-diffing** — snapshot the sandbox before/after each tool run (filesystem tree, syscalls, network attempts, env vars, DB rows), normalize away noise (timestamps, temp paths, `__pycache__`), and diff the observed transition against the contract's declared add/delete effects; (2) **Hypothesis stateful testing** — generate random action sequences through a `RuleBasedStateMachine` whose model is the contract's simulated state, asserting the real tool's transitions equal the declared ones; (3) **tiered mocks** — in-memory fakes (fast, low fidelity), namespace-isolated real FS (slower, high fidelity), and production-trace record-replay (catches production-only behavior) — selected by cost/fidelity policy; (4) **a CI gate** where declared≠observed is a build failure and `known_incomplete` contracts graduate to `known_complete` through evidence, not assertion. The refinement loop (ARMS/RIM/FAMA/SAM literature) lets traces *propose* contract patches offline with a SAM-style soundness bias, but only a human *applies* them — the live LLM never edits contracts. The honest boundary: conformance proves contract-honesty for behaviors the harness can elicit; the adversarial residual (sandbox-aware behavior) is caught only by production-trace replay and never fully.

**§19 protocol followed:** audit (§1) → question (§2) → research (§3) → compare (§4) → derive (§5: the design) → validate (§6: falsifiers) → integrate (§7: ADR) → record (§8) → reassess (§9).

---

## 1. Audit — what prior cycles established (referenced, not re-researched)

| Prior file | Contribution to this cycle | Status |
|---|---|---|
| `learn-plan-validation.md` (cycle 8) | The tool-contract schema (STRIPS triple + tier + idempotent + compensation + requires_approval + completeness + budget_cost); the 4-check validator; worked example; **contract-completeness named as breakage #1**; this cycle is the explicitly requested follow-up ("the least-designed piece"). | Accepted as the **problem statement and schema**. |
| `learn-formal-methods.md` | Hypothesis property-based testing ADOPTED ("the cheap man's TLA+"); stateful testing as the substitute for model-checking interleavings; beartype on tool entry points; deal on 5–10 critical functions; AgentRewind VCR record/replay pattern for cassettes. | Accepted; this cycle applies stateful testing **to tool contracts specifically**. |
| `learn-advanced-cs.md` | Sandboxing, filesystem jail (`is_inside_jail`), SQLite durable queue, fault domains. | Accepted; the sandbox + jail are the **fixture** the harness runs inside. |
| `learn-causal-discovery.md` | The sandbox as causal laboratory; the replay protocol; PN/PS scoring discipline; the ledger of causal claims. | Accepted; production-trace replay (tier c) feeds the same ledger discipline. |

**Genuinely new in this cycle:** the before/after effect-diff procedure spec (snapshot domains, normalization, nondeterminism budget); the Hypothesis state-machine pattern per tool class; the three-tier mock design with fidelity/cost policy; the CI drift gate + `known_incomplete` graduation workflow; the adversarial conformance boundary; the SAM-biased human-in-the-loop refinement loop.

---

## 2. The question, sharpened

Cycle 8 left one sentence as a TODO: *"contract conformance tests: Hypothesis generates random action sequences × random environments, executes against sandboxed mocks, asserts declared add/del effects match the observed state diff."* Three sub-questions decide whether that sentence is a design or a wish:

1. **What exactly is "the observed state diff"?** (Which state domains are snapshotted, how noise is normalized, how flakiness is budgeted — without this, the diff is either all noise or all fiction.)
2. **What does the harness prove, and what does it provably not prove?** (The adversarial question: a tool that behaves in sandbox but not in production. If the harness can't name its blind spot, it becomes a false-confidence machine.)
3. **How do contracts improve over time without the live LLM editing them?** (The action-model-learning literature has forty years of answers; most of them learn in the *wrong direction* for our purpose — §3.3 sorts them.)

---

## 3. Research — the genuinely new evidence

### 3.1 The diff precedent: write-set audits, strace tracing, filesystem manifests

The "run it, snapshot before/after, diff" pattern is field practice, not theory:

- **Write-set audits** (dev.to, Oct 2026 — practitioner post): run the suite under a harness that snapshots a fixture tree before/after, diffs to `{added, removed, changed}`, and compares touched paths against a *declared* write list; any undeclared write exits 2 — "the suite may have passed, but it edited evidence without saying so. That is a review block, not a warning." The exact declared-vs-observed discipline we need, down to the three-bucket diff. [MC — single practitioner post, but the pattern is independently sound]
- **strace-based effect extraction** (testtrim, Mathieu Fenniak): runs each test under `strace -f` (follow forks), parses `open`/`execve` syscalls from the trace into the set of files the process actually touched — the dependency/effect set *extracted from behavior, not from claims*. [HC — real open-source tool, documented mechanism]
- **Filesystem-as-manifest** (dev.to, Oct 2026 — practitioner post): "for most CLI tools the filesystem *is* the contract." Snapshot the tool's output tree into a canonical JSON manifest (path → hash, excluding mtimes); the key design detail is a *noise model*: temp paths, timestamps, and mode bits make every naive diff noisy, so the harness pins a throwaway directory, canonicalizes paths, and hashes contents — the normalization problem stated honestly. [MC]

Transfer for §5.1: the snapshot domains are wider than files (env vars, sockets, DB rows), but the three moves are the same — **capture, canonicalize, diff against the declaration**.

### 3.2 Hypothesis stateful mechanics (from the official docs)

`hypothesis.stateful.RuleBasedStateMachine` (verified against hypothesis.readthedocs.io, v6.170.x) gives exactly the machinery cycle 8's TODO needs:

- **`@rule`**: a method whose arguments are drawn from strategies; each execution is one transition. Rules map 1:1 to tool invocations.
- **`@precondition`**: a filter applied *before* generation (not `assume()` inside the rule) — Hypothesis docs are explicit that `assume()` inside rules collapses the search to degenerate sequences. Preconditions map to the contract's own preconditions: a rule for `write_file` only fires when the model says the parent dir exists.
- **`@invariant`**: checked after *every* step — the place for the two conformance invariants (§5.2).
- **`Bundle`**: strategies over values *produced by earlier rules* (e.g. a `Files` bundle of paths created by a `create_file` rule) — this is how sequences build on each other's outputs, exactly like tool plans do.
- **Shrinking**: a failing sequence is minimized to the shortest reproducing case — a 14-step conformance failure becomes a 2-step "the tool did X undeclared" report. This is the debugging payoff the manual seeded-RNG property tests (cycle: formal-methods §3) never had.

The established pattern in real codebases (e.g. the bidict stateful suite): a *model* (simple Python reference) runs alongside the system under test, each rule updates both, invariants assert they stay synchronized. **Our design inverts this**: the model is not a reference implementation — it's *the contract itself* (the validator's simulated state from cycle 8 §5.2). Each rule executes the real tool in the sandbox and asserts the observed environment transition equals the contract's declared transition. The contract is executable; conformance is model-based testing with the contract as the model. [DESIGN]

### 3.3 Action-model learning: ARMS, RIM, FAMA, SAM — and which direction each learns

The literature named by cycle 8, assessed for *what transfers to a human-in-the-loop refinement loop*:

- **ARMS** (Yang, Wu & Jiang, 2007, *Artificial Intelligence* 171(2–3):107–143 — weighted MAX-SAT over plan traces): encodes traces as intra-operator and inter-operator constraints; frequent action pairs (via Apriori) generate plan constraints; a SAT solver finds the action model satisfying the most constraints. [HC — mechanism verified via the review literature] Transfer: the *constraint formulation* — a proposed precondition/effect is a hypothesis with *evidence weight* (how many traces support it), not a fact. Our refinement loop's proposals carry exactly this weight.
- **RIM** (Zhuo & Kambhampati, 2013, IJCAI): *refines an incomplete model* rather than learning from scratch — constructs soft and hard constraints from the partial model + traces, and learns macro-actions. [HC — mechanism verified via review] Transfer: RIM is the closest ancestor of our loop — it starts from the hand-written contract and proposes *amendments*. The soft/hard distinction maps to: hard = "contradicts N traces, must fix"; soft = "suggested by traces, review."
- **FAMA** (Aineto, Jiménez & Onaindía, 2019): reframes learning as *planning* — every solution to a constructed planning problem is an action model consistent with the observations; handles missing observations. [HC — mechanism from the openreview summary; venue details MC] Transfer: the *consistency* framing — a proposed contract patch must be consistent with *all* recorded traces, not just the ones that motivated it. This is our proposal-validity check.
- **SAM — the keystone** (Stern & Juba, 2017, "Efficient, Safe, and Probably Approximately Complete Learning of Action Models," IJCAI 2017; ar5iv:1705.08961): learns a *safe* action model — one where **every plan consistent with the learned model is also consistent with the real, unknown model** (the L-boundary of version space learning; Valiant's elimination algorithm). The recipe: start by assuming every literal is a precondition and nothing is an effect, then *remove* preconditions and *add* effects only when trajectories prove it. Sample complexity is quasilinear in the number of actions. Extensions: lifted SAM (Juba, Le & Stern 2021), partial observability (Le, Juba & Stern, AAAI 2024), stochastic effects. [HC — theorem and algorithm verified]
- **CAMA** (Zhuo et al., crowdsourced action-model acquisition): weighted MAX-SAT combining crowd labels with trace constraints; trace information filters inaccurate human input. [MC — via review summary] Transfer: *the machine's traces arbitrate human claims* — in our loop the direction is reversed (human arbitrates machine proposals), but the weighted-evidence discipline is the same.

**The direction problem, resolved:** for our validator, errors have asymmetric cost. A contract that *over-claims effects* (says the tool creates X when it doesn't) → the validator accepts plans the world can't execute (false accept of executability). A contract that *under-claims effects* (misses a real side effect) → the validator proves validity of a fiction (cycle 8's breakage #1 — the dangerous one). SAM's bias is exactly right for **preconditions** (propose only what held in *all* traces — conservative applicability), and the *dual* bias is right for **effects** (propose *everything observed* in any trace — the union, so nothing real stays undeclared). Missing an effect is the fiction risk; a spurious proposed effect is caught by human review and by the multi-run evidence threshold. The loop is biased toward **soundness where over-claiming is dangerous (preconditions) and completeness where under-claiming is dangerous (effects)**. This asymmetry is the cycle's main theoretical contribution. [DESIGN]

### 3.4 The adversarial literature: what a clean sandbox report does not prove

MITRE ATT&CK **T1497 (Virtualization/Sandbox Evasion)** catalogs the mechanism set: system checks (T1497.001 — VM artifacts, hardware fingerprints, registry keys), user-activity checks (T1497.002 — mouse movement, real-user signals), time-based checks (T1497.003 — sleep timers, accelerated-clock detection). Modern variants add environment scoring (ML over subtle indicators: core count, uptime, recent file activity) and predictive time-bombing (stay dormant until the analysis window likely closed). [VC — MITRE ATT&CK is the standard reference; verified at attack.mitre.org]

The honest-for-JARVIS translation (no malware involved — the concern is *unintentional* environment-conditional behavior, which is strictly more common):

1. **Mock detection by the tool's dependencies**, not the tool: a library that checks `os.environ`, sniffs for CI variables, or behaves differently when stdout isn't a TTY. The tool's *own* code is honest; its dependency tree isn't.
2. **Timing-conditional behavior**: timeouts/retries that never trigger under fast mocks but dominate in production; rate-limit paths that only exist against the real API.
3. **State-conditional behavior**: the tool reads ambient state the sandbox doesn't populate (real mailbox contents, real calendar, OS keychain) and takes different branches.

The forensic-analysis field's standing warning applies verbatim: **"a clean sandbox report is not proof of benign intent"** — it is proof of benign behavior *under observation*. [HC — practitioner consensus, multiple 2025–2026 sources]

Transfer for §5.5: the harness's anti-evasion design is (a) *tier diversity* — the same tool under in-memory fake, namespace-isolated real FS, and production-trace replay, with divergence across tiers flagged as a finding, not averaged away; (b) *production-trace replay as the standing watch* — verify-after-acting diffs (cycle 8 §5.4) compare production-observed effects against the contract continuously, which is the only channel that can see sandbox-divergent behavior; (c) *never trusting absence* — an effect never observed in any tier is not proven absent, which is why `known_complete` requires production evidence (§5.4), not just sandbox evidence.

---

## 4. Compare — relation to prior cycles

- **Cycle 8** named the conformance harness as its least-designed mitigation and specified the contract schema it must test against. This cycle is that design; the schema fields it exercises are pre/add/del effects (the STRIPS triple), `idempotent`, and `completeness`.
- **learn-formal-methods.md** adopted Hypothesis stateful testing as "the cheap man's TLA+" for interleavings. This cycle instantiates it with a new model: not a reference implementation, but the *contract's simulated state* — the validator's `S` from cycle 8 §5.2 becomes the expected trace.
- **learn-advanced-cs.md**'s filesystem jail and sandbox are the fixture; the harness runs *inside* them. The jail check (`is_inside_jail`) becomes one of the conformance invariants for file tools: observed writes outside the jail are an automatic UNDER-CLAIMED fail regardless of declaration.
- **learn-causal-discovery.md**'s replay protocol and production traces are tier (c) of the mock design; the PN/PS discipline is how the refinement loop weighs trace evidence (a proposed effect seen in 1 of 200 traces gets a different weight than one seen in 199).

---

## 5. DERIVE — the contract-conformance harness [DESIGN]

### 5.1 The diff procedure spec

**Goal:** for one tool invocation with grounded args, compute the *observed* state transition and compare it against the contract's *declared* transition.

**Snapshot domains** (what is captured before and after; each domain has a canonicalizer):

| Domain | Capture | Canonicalization (noise removal) |
|---|---|---|
| Filesystem tree (the sandbox root) | recursive walk: path → {sha256(content), mode, is_symlink→target} | **drop mtimes entirely** (existence+content is the signal); normalize tool-declared temp patterns (`{tmp}/report-*.pdf` → `{tmp}/report-<TMP>.pdf`); drop `__pycache__`, `.coverage`, `.hypothesis` via the noise allowlist (§5.1.1) |
| Syscalls (Linux CI; ETW/ProcMon on Windows runners) | `strace -f -e trace=%file,%network,%process` log: opened paths, `connect()` targets, `execve`/`clone` | map fd-relative opens to absolute paths; drop reads of the Python stdlib/site-packages (interpreter noise); keep all writes and all `connect()`s |
| Network attempts | socket-layer interception log (destination host:port, bytes out/in) — *attempted*, since the sandbox has no route out | normalize ephemeral ports; group by (host, port); DNS resolutions recorded as `dns_query(name)` effects |
| Environment variables | `os.environ` diff | drop harness-injected vars (`HYPOTHESIS_*`, `CI_*`) via allowlist; keep tool-visible additions/removals |
| DB rows (SQLite-backed tools) | per-table row hashes before/after | drop autoincrement-sequence-only changes; treat `sqlite_sequence` as noise |

**Procedure** (`conformance_diff`, specification):

```
snap_before ← snapshot_all_domains()
result ← run_tool_in_sandbox(tool, args)        # timeout-bounded, jailed
snap_after ← snapshot_all_domains()
raw ← diff(snap_before, snap_after)             # per domain: {added, removed, changed}
observed ← canonicalize(raw)                   # noise removal, temp normalization
declared ← ground(contract.add_effects ∪ contract.delete_effects, args)

UNDER ← observed − declared                     # the fiction risk (cycle 8 breakage #1)
OVER  ← declared − observed_stable              # declared but never seen (§5.1.2)
if UNDER − noise_allowlist ≠ ∅:  → FAIL("undeclared_effect", UNDER)
elif OVER ≠ ∅:                   → FAIL("unobserved_effect", OVER)   # explain-or-remove
else:                            → PASS
```

**5.1.1 The noise allowlist is per-tool, versioned, and reviewable** — not a global rug to sweep dirt under. Each entry needs a reason string ("`__pycache__` — interpreter artifact, not a tool effect"). An entry that grows to cover real effects is itself a conformance smell; the CI gate reports allowlist size per tool and flags growth.

**5.1.2 The nondeterminism budget:** every conformance case runs **N=3**. An effect observed in all 3 runs = *stable* (compared against declared). Observed in 1–2 = *flaky*: the contract must either declare it (if it's a real conditional effect → split the tool per cycle 8's design-smell rule, or document the condition) or the tool is nondeterministic in a way the validator cannot model — flagged `nondeterministic_effect`, which forces `completeness: known_incomplete` until resolved. Randomness with a seeded RNG in the harness makes the flaky/stable split reproducible.

**5.1.3 Jail invariant:** any observed write outside the filesystem jail is an automatic FAIL regardless of declaration — the contract cannot legitimize a jail escape by declaring it. (This is the `deal.pre(is_inside_jail)` contract from learn-formal-methods.md, enforced empirically.)

### 5.2 Hypothesis state-machine pattern per tool class

The machine's *model* is the contract's simulated state — the same `S` the cycle-8 validator threads through a plan. Each rule executes the real tool in the sandbox and asserts the observed transition equals the declared one. Two invariants run after every step:

- **I1 (declared-holds):** every declared add/delete effect is present in the observed diff (modulo the noise allowlist).
- **I2 (nothing-undeclared):** every observed mutation is either declared or allowlisted. *This is the load-bearing invariant — it is the executable form of cycle 8's breakage #1.*

```python
# Specification pseudocode — the contract as the model.
class ToolConformanceMachine(RuleBasedStateMachine):
    Paths = Bundle("paths")          # values produced by earlier rules, like tool plans

    def __init__(self):
        super().__init__()
        self.model_state = initial_propositions()   # the contract's S0
        self.sandbox = fresh_sandbox()               # tier-a or tier-b (§5.3)

    @rule(target=Paths, name=file_names(), content=binary())
    def create_file(self, name, content):
        # precondition() gates this rule exactly where the contract's
        # preconditions gate the tool: only fire when the model says it's legal
        before = snapshot(self.sandbox)
        tool.write_file(path=name, content=content)  # the REAL tool, sandboxed
        observed = canonical_diff(before, snapshot(self.sandbox))
        declared = ground(contract["write_file"].effects, {"path": name})
        assert declared.add <= observed.add, f"undeclared: {observed.add - declared.add}"  # I2
        assert declared.add >= observed.add - ALLOWLIST, "declared but missing"             # I1
        self.model_state = apply_effects(self.model_state, declared)  # model steps with the CONTRACT

    @rule(path=Paths)
    @precondition(lambda self: self.model_has("file_exists"))  # never assume() inside rules
    def delete_file(self, path):
        ...  # same shape: snapshot → run → diff → assert I1, I2 → step model

    @invariant()
    def jail_never_escaped(self):
        assert all inside_jail(p) for p in self.sandbox.all_writes()

    @invariant()
    def model_matches_reality(self):
        # periodically re-read the sandbox and check the model's tracked
        # predicates agree — catches model/reality drift mid-sequence
        assert tracked_predicates(self.model_state) <= read_predicates(self.sandbox)
```

**Per-class rule/invariant profiles:**

| Tool class | Rules (transitions) | Class-specific invariants (beyond I1/I2) |
|---|---|---|
| **File tools** (`write_file`, `move`, `delete`, `mkdir`) | create/write/delete/move with `Bundle`d paths; symlink and `..` path strategies (the jail-fuzzing strategies from learn-formal-methods.md) | I-jail (above); *content fidelity*: declared `file_content(path, sha)` must match the actual bytes — catches "wrote the file but with wrong content" |
| **Network tools** (`http_fetch`, `api_call`) | request sequences against a fake socket layer that records attempts; redirect-following strategies | *host allowlist*: every `connect()` target must be in the declared `network_peers` effect — this is the executable form of cycle 8's "follows a redirect to another domain" example; *no-silent-retry*: retry attempts are observable effects, not free |
| **System tools** (`run_shell`, `spawn`, `env_set`) | command/arg strategies; env mutation rules | *process-tree closure*: children spawned are effects too (strace `-f` catches them); *exit-code semantics*: declared `succeeds`/`fails` predicates must match actual return codes |

**Precondition strategy:** rules carry `@precondition`s mirroring the contract's preconditions, so generated sequences are *mostly* contract-legal — the interesting failures are then effect mismatches, not precondition noise. A second, smaller machine runs *without* preconditions to test the tool's behavior on illegal inputs (it should fail cleanly, not corrupt state — the fault-injection spirit of learn-formal-methods.md §5).

### 5.3 Mock tiers: fidelity vs cost

| Tier | What it is | Cost per run | Fidelity | What it catches | What it misses |
|---|---|---|---|---|---|
| **(a) In-memory fakes** | dict-backed FS, fake socket (records `connect` attempts, returns canned bytes), fake clock, fake env | ~ms; runs per-commit in CI | Low | Logic-level effect errors: wrong path written, missing declared file, extra dict entry | Permission bits, symlinks, real syscalls, timing behavior, anything OS-specific |
| **(b) Namespace-isolated real FS** | Linux mount+user namespaces (or a container): real syscalls, real SQLite, real file modes; loopback-only network with a fake DNS/HTTP stub | ~100ms–s; nightly + on tool-contract change | High (for the OS it runs on) | Everything in (a) plus: mode-bit errors, symlink escapes, undeclared temp files, child processes, real `connect()` attempts | Behavior specific to the *other* OS — see the Windows gap below |
| **(c) Production-trace replay** | VCR-cassette style (AgentRewind pattern, learn-formal-methods.md §4): production runs emit span trees with before/after state hashes; conformance replays offline, diffing observed vs declared | ~0 marginal (recorded once, replayed free) | Highest *for observed paths* | Production-only behavior: real API responses, real mailbox/calendar state, timing-dependent branches | Paths production never took — coverage is whatever the user actually did |

**Selection policy:**
- **Per commit:** tier (a) for all tools, whole suite in seconds.
- **On tool-implementation or contract change:** tier (b) for the changed tool(s) — the CI gate (§5.4).
- **Continuously:** tier (c) sampling — every production `verify-after-acting` diff (cycle 8 §5.4) is a tier-(c) conformance datapoint for free; drift accumulates in the ledger and feeds the refinement loop (§5.6).

**The Windows gap (stated, not hidden):** JARVIS runs on Windows; cheap CI runs on Linux. Tier (b) on Linux cannot observe Windows-specific effects (ACLs, registry, `\\?\` paths, real Win32 behavior). Until a Windows CI runner exists, tier-(b) conformance covers the *platform-agnostic tool core* with platform adapters stubbed, and the gap is recorded per-tool as a `platform_coverage: linux-only` annotation — which blocks graduation to `known_complete` (§5.4). A Linux-passing conformance suite is evidence, not proof, for the Windows runtime. [DESIGN — constraint acknowledged]

**Tier-divergence as a finding:** the same tool+args runs under (a) and (b); if the observed effect sets *differ* (beyond the known fidelity delta documented per tier), that's not averaged away — it's flagged as `tier_divergence`, the primary automated signal for the adversarial concern (§5.5).

### 5.4 The CI gate and the graduation workflow

**Gate triggers:** any change to a tool's implementation *or* its contract file. The contract is versioned data (cycle 8 §7); the gate treats "contract edited without implementation change" as a first-class event, not a docs tweak.

**Gate stages:**
1. **Schema check** (seconds): contract YAML validates against the schema; `beartype` checks on the tool's entry point still hold.
2. **Tier-(a) suite** (seconds): all tools, fast fakes. Any UNDER-CLAIMED → **hard fail**. Any OVER-CLAIMED → fail with "explain or remove."
3. **Tier-(b) for changed tools** (minutes): namespace-isolated runs, N=3 nondeterminism budget. Same fail semantics.
4. **Drift report**: observed-vs-declared diffs from tier-(c) production traces since the last gate run, attached to the build as evidence. Drift without a contract update → warning that becomes a fail after a grace window (default: 7 days) — contracts rot gradually, and the gate should catch rot, not just breakage.

**Drift semantics (the four outcomes):**
| Observed vs declared | Meaning | Gate action |
|---|---|---|
| MATCH | contract honest | pass |
| UNDER-CLAIMED (observed ⊄ declared) | tool does more than declared — the fiction risk | **hard fail**; author must declare the effect or fix the tool |
| OVER-CLAIMED (declared, never observed in N runs × 2 tiers) | contract claims what the tool doesn't do | fail with "explain or remove"; allowed escape: `expected_absent_in: [tier-a]` annotation for environment-dependent effects (e.g. "only writes cache when network is up"), which itself needs tier-(c) evidence within the grace window |
| NOISE (allowlisted) | known benign | pass; allowlist growth flagged |

**The `known_incomplete` graduation workflow** (how a tool earns `completeness: known_complete`):
1. New/changed tool ships with `completeness: known_incomplete` by default — incompleteness is the default state, completeness is *earned* (the model-lite transfer from cycle 8 §3.3).
2. **Evidence bar for graduation:** K consecutive clean tier-(b) runs (K=50, tunable) + zero tier-(c) drift flags for M days (M=14) + `platform_coverage` includes the production OS + **human review** of the full declared effect set against the trace evidence.
3. Human review is where §5.6's proposals land: the reviewer sees each declared effect annotated with its evidence (traces, run counts, tiers). Effects with thin evidence are challenged, not rubber-stamped.
4. Graduation is recorded as a ledger event with the evidence snapshot hash — reversible, auditable. A later drift flag *demotes* the contract back to `known_incomplete` automatically. Completeness is a standing claim, not a one-time badge.

### 5.5 Adversarial conformance: what the harness can and cannot catch

**The threat model, honestly scoped:** not malware — *environment-conditional behavior* in tool code or (more often) its dependencies: CI-env sniffing, TTY detection, timing-dependent branches, ambient-state-dependent branches (§3.4).

**What the harness CAN catch:**
- **Tier divergence** (§5.3): identical args, different observed effects across tiers (a)/(b)/(c) → flagged. A tool (or dependency) that detects the in-memory fake and takes a quieter path will show its louder path in tier (b) or (c).
- **Dependency sniffing, statically:** the tier-(b) syscall trace records *reads* of environment and system-probing files (`/proc`, env vars like `CI`, `TERM`). A tool that reads `CI=true` and branches is visible in the trace even if both branches look benign — the *read itself* is reviewable evidence.
- **Production drift** (tier c): verify-after-acting diffs continuously compare production behavior to the contract. Sandbox-quiet/production-loud behavior surfaces here as drift, with trace IDs attached.

**What it CANNOT catch (the residual):**
- Behavior whose trigger never occurs under any harness run *and* never occurred in sampled production traces — the harness proves honesty for *elicited* behaviors only.
- Timing-dependent behavior below the harness's time resolution (sub-millisecond races; predictive time-bombing with windows longer than any test run).
- A tool that detects *all three tiers* and behaves identically under each — the "clean report under total observation" case. Defense in depth here is not a fourth tier; it's the `known_incomplete` default and the standing tier-(c) watch.

**Residual risk statement (for the ADR):** *The conformance harness establishes that the contract honestly describes every behavior the harness could elicit. It does not establish that no unelicited behavior exists. The residual risk — environment-conditional behavior invisible to all three tiers — is accepted and managed, not eliminated: managed by the `known_incomplete` default, the tier-(c) production watch, and automatic demotion on drift. Any claim stronger than this would make the harness a false-confidence machine.*

### 5.6 The human-in-the-loop refinement loop (ARMS/RIM/FAMA/SAM-informed)

**Never violated:** proposals are generated *offline* from traces; the live LLM never edits contracts; only a human applies a patch; the validator only reads committed contracts. (Cycle 8's rule, extended: the judge never judges the judge, and the student never grades its own exam.)

**Proposal sources:**
1. **Tier-(c) drift**: production verify-after-acting diffs where observed ⊄ declared, clustered by (tool, effect-signature). Each cluster is a proposal: "declare this effect," with the trace IDs as evidence.
2. **Conformance failures**: UNDER-CLAIMED findings from tiers (a)/(b) — same shape, sandbox evidence.
3. **Offline learning pass** (nightly/weekly, the ARMS/RIM step): over the trace corpus, extract candidate preconditions and effects with the SAM-biased rules below.

**The SAM-biased proposal rules** (§3.3 transfer):
- **Precondition candidates:** propose `p` as a precondition of tool `t` only if `p` held before *every* successful run of `t` in the corpus (the L-boundary / Valiant-elimination direction — conservative, sound). Support count attached; threshold for proposal: ≥20 successful runs.
- **Effect candidates:** propose `e` as an effect of `t` if `e` was observed after *any* run of `t` (the union direction — completeness-biased, because under-claimed effects are the fiction risk). Each candidate carries: run count, tier(s) observed in, and a flakiness flag from the N=3 budget.
- **Consistency check** (FAMA transfer): a proposed patch is only *proposable* if the patched contract is consistent with *all* recorded traces — replay every trace's observed transitions against the patched contract; any contradiction vetoes the patch. This stops a 3-trace proposal from breaking a 300-trace history.
- **Macro-action note** (RIM transfer): if traces show tools X→Y *always* co-occurring with an intermediate state the contracts don't model, the loop proposes a *contract amendment*, not a merged tool — tool granularity stays a human design decision.

**The review step:** the tool owner receives a contract *patch* (YAML diff) where each hunk carries its evidence (trace IDs, counts, tiers, consistency-check result). Accept / reject / amend per hunk. Rejections require a reason, which routes to: the noise allowlist (benign, declare as noise), a tool bug report (real undeclared behavior → fix the tool, don't declare the bug), or the `expected_absent_in` annotation. Accepted patches bump the contract version and reset the relevant evidence counters. The whole loop is logged to the ledger — the contract's history is the audit trail of *why* each effect is declared.

### 5.7 Worked mini-example — one file-write tool, one caught undeclared effect

**Tool:** `write_report(path, content)` — writes a text report. **Contract (declared):**

```yaml
tool: write_report
tier: write
preconditions: [parent_dir_exists(path)]
add_effects: [file_exists(path), file_content(path, sha256(content))]
delete_effects: []
idempotent: true
completeness: known_incomplete
```

**Conformance run (tier b, N=3):** snapshot → `write_report("/sandbox/reports/q3.txt", ...)` → snapshot → canonical diff.

**Observed (all 3 runs, stable):**
- `added: /sandbox/reports/q3.txt` (content hash matches) → declared ✓
- `added: /sandbox/reports/q3.txt.bak` → **not declared** ✗
- `changed: /sandbox/reports/` (mtime only) → normalized away (directory mtime is noise) ✓
- `added: /sandbox/reports/__pycache__/…` → noise allowlist (interpreter artifact, reason recorded) ✓

**Diff result:** UNDER-CLAIMED — `file_exists(path + ".bak")` observed in 3/3 runs, declared in 0/3 contracts. **Gate: hard fail.** The machine-generated finding: `(tool=write_report, fault=undeclared_effect, observed=file_exists(/sandbox/reports/q3.txt.bak), evidence=3/3 tier-b runs, trace_ids=[…])`.

**Human triage:** the `.bak` write is a real behavior (the tool keeps one backup generation) — not a bug, a missing declaration. Reviewer accepts the refinement proposal; contract gains `file_exists(sibling_backup(path))` in add_effects; the validator's model now knows the backup exists (so a later `delete_report` contract can declare cleaning it up — the composition payoff). Had the reviewer judged the backup unintended, the fix would have gone to the *tool*, and the contract would stay unchanged — the loop distinguishes "declare it" from "fix it," which auto-learning alone cannot.

**What the example demonstrates:** the fiction risk made concrete (without the harness, the validator would prove plans valid while a ghost `.bak` file accumulated on every run — harmless here, a data-leak vector for a tool writing to a shared directory); the normalizer earning its keep (directory mtime, `__pycache__`); and the human as the only entity allowed to convert an observation into a declaration.

---

## 6. Validate — falsifiers [DESIGN]

What would kill or bound this design (measured when built):

1. **Noise drowning signal:** if >30% of tier-(b) conformance failures are noise-allowlist misses (new interpreter artifacts, new temp patterns) rather than real findings, the harness becomes an allowlist-maintenance treadmill. Kill threshold: allowlist entries per tool growing >2/quarter with no real findings attached.
2. **The N=3 budget is wrong:** measure the flaky/stable split across the first 1,000 runs. If >10% of effects are flaky at N=3, the budget is too small to distinguish nondeterminism from noise — raise N or admit the tool is unmodelable (`known_incomplete` permanently).
3. **Tier-(a)/(b) divergence is all fidelity delta:** if every tier-divergence flag turns out to be "fake FS doesn't do X" rather than real environment-conditional behavior, the adversarial signal is pure cost. Measure the true-positive rate of `tier_divergence` flags over the first quarter.
4. **Proposal precision:** of the refinement loop's proposed patches, if human reviewers accept <50% (the rest = noise or tool bugs misrouted), the proposal thresholds are too loose — tighten the SAM-bias support counts.
5. **The honest-scope test (adversarial):** deliberately plant 5 environment-conditional behaviors (CI-sniffing branch, timing branch, ambient-state branch) in test tools. The harness must catch ≥4 via tier divergence, syscall-trace reads, or tier-(c) drift. If it catches ≤2, the §5.5 "can catch" list is overstated and the residual risk statement must be strengthened.
6. **Windows-gap bite:** the first Windows-runner tier-(b) pass over already-"conformant" tools — count the new findings. If >20% of tools gain findings, the `platform_coverage: linux-only` annotation was load-bearing and graduation was correctly blocked; if ~0%, consider relaxing.

## 7. Integrate — ADR

**Decision:** ADOPT the contract-conformance harness as the enforcement mechanism for cycle 8's contract-completeness mitigation — the diff procedure (§5.1), Hypothesis state machines per tool class (§5.2), three-tier mocks (§5.3), CI drift gate + graduation workflow (§5.4), adversarial boundary (§5.5), and the SAM-biased human-in-the-loop refinement loop (§5.6).

**Consequences:**
- Every tool in the dangerous tier gets a conformance machine first (highest fiction-risk), then write tier, then read tier — same ordering as cycle 8's contract authoring.
- The contract registry gains `platform_coverage` and per-effect evidence annotations; `known_complete` becomes an earned, revocable status with a ledger trail.
- CI grows a namespace-isolated tier-(b) stage on tool-contract changes; production gains the standing tier-(c) watch via the existing verify-after-acting hook (no new production instrumentation — the hook already exists in cycle 8 §5.4).
- The refinement loop is an offline batch job + human review queue, never a live component. No LLM writes to contracts, ever.
- Open-problem linkage: cycle 7's "environment is the verifier" now has two concrete implementations — the per-dispatch verify-after-acting diff (runtime) and the tier-(c) conformance replay (offline).

## 8. Record — evidence table

| # | Claim | Evidence | Confidence |
|---|---|---|---|
| 1 | Declared-vs-observed write-set diffing is field practice (snapshot → canonicalize → diff against declaration; undeclared = review block) | dev.to practitioner posts (write-set audit pattern; filesystem-manifest pattern, Oct 2026) | [MC] (single-source practitioner posts; pattern independently sound) |
| 2 | Syscall-trace effect extraction works (strace -f, parse open/connect into the touched-set) | testtrim (mathieu.fenniak.net) — real tool, documented mechanism | [HC] |
| 3 | Hypothesis RuleBasedStateMachine gives rules/preconditions/invariants/Bundles/shrinking; preconditions must gate generation (not assume() inside rules) | hypothesis.readthedocs.io stateful docs (v6.170.x) | [VC] on mechanics |
| 4 | ARMS learns action models from traces via weighted MAX-SAT over intra/inter-operator constraints; frequent action pairs via Apriori | Yang, Wu & Jiang 2007, AI 171(2–3); review literature | [HC] |
| 5 | RIM refines *incomplete* models (soft/hard constraints from partial model + traces); FAMA frames learning-as-planning with a consistency guarantee; both handle the amend-don't-rebuild case | Zhuo & Kambhampati 2013 (RIM); Aineto, Jiménez & Onaindía 2019 (FAMA); openreview summary | [HC] on mechanisms; [MC] on venue details |
| 6 | SAM learns *safe* action models (every plan consistent with the learned model is consistent with the real model); recipe = start maximally conservative, remove preconditions/add effects only on trajectory evidence; quasilinear sample complexity | Stern & Juba 2017, IJCAI 2017 (ar5iv:1705.08961); extensions Juba, Le & Stern 2021; Le, Juba & Stern, AAAI 2024 | [HC] |
| 7 | Sandbox evasion is a cataloged mechanism set (T1497: system checks, user-activity checks, time-based checks); "a clean sandbox report is not proof of benign intent" | MITRE ATT&CK T1497 (attack.mitre.org); forensicspot/apriorit practitioner consensus 2025–2026 | [VC] on T1497's existence; [HC] on the warning's applicability |
| 8 | The diff procedure, state-machine pattern, mock tiers, CI gate, graduation workflow, adversarial boundary, and refinement loop | Derived in §5 from 1–7 | [DESIGN] — specified, unmeasured; falsifiers in §6 |

## 9. Reassess — what changes, what's still unknown

**What changes:** cycle 8's least-designed mitigation is now the most-designed piece of the deterministic stack. The contract-completeness loop is closed on paper: contracts are authored (cycle 8) → tested by the harness (this cycle) → refined from traces with human approval (this cycle) → re-tested. The validator's load-bearing assumption ("the contract declares everything the tool does") is no longer an article of faith — it's a CI-enforced property with a named residual.

**Unknowns [UK]:**
- The noise-allowlist maintenance burden in practice (§6.1) — the most likely way this harness dies is tedium, not theory.
- The true-positive rate of `tier_divergence` as an adversarial signal (§6.3, §6.5).
- Whether the SAM-bias support thresholds (≥20 runs for preconditions, union-with-evidence for effects) produce acceptable proposal precision (§6.4) — thresholds are guesses until measured.
- The Windows-runner timeline, which gates the `platform_coverage` annotation from blocking graduation forever.
- Interaction with tool *versioning*: when a tool's dependency upgrades change its effects (new cache file from a new library version), is that a tool change (gate triggers) or environment drift? Proposed: lockfile change on the tool's dependency closure triggers the gate — unmeasured cost.

**Next cycle suggestion:** the falsifier that matters most is §6.5 (the planted-adversarial test) — but it needs the harness built first. The cheaper next research step: the *predicate-grounding* problem cycle 8 deferred — how `file_exists(path)` and friends are actually evaluated against a live filesystem cheaply enough for the dispatch-time TOCTOU re-check, since the conformance harness's `read_predicates` (§5.2) is the same function.

---

*Honest completion (Rule 12): Researched: effect-diff precedents (write-set audits, strace extraction, fs manifests — 2 web searches), Hypothesis stateful mechanics (docs-verified), ARMS/RIM/FAMA/SAM/CAMA mechanisms (2 searches + review literature), sandbox-evasion catalog (T1497 verified at MITRE). Validated: all citations checked against real sources — no fabricated references; SAM's safety theorem and the version-space connection verified via ar5iv abstract. Saved: this file. Tested/Measured: nothing (learning only). Incomplete: noise-burden, tier-divergence precision, proposal thresholds, Windows runner (marked UK). Blocked: none.*
