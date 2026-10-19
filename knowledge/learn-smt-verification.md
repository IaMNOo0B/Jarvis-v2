# Can SMT/SAT Solving Verify Real Agent Constraints? — Cycle 2 (speed edition)

*PHASE INFINITY Research Cycle 2. Analysis only — no solver was executed; performance figures are literature-reported, not measured. Confidence tags throughout.*

**Research question:** Can Z3 verify the actual constraints JARVIS needs?

**One-line answer:** Z3 is a superb *offline design-time verifier* for 2 of the 5 constraints, marginal for 2, wrong tool for 1. The runtime gate stays deterministic code + contracts.

---

## 1. SMT in one page

Z3 (Microsoft Research, MIT license, C++) decides **satisfiability modulo theories**: given a formula mixing Booleans with arithmetic, bitvectors, arrays, strings, datatypes, uninterpreted functions — it answers sat/unsat/unknown. The killer feature for verification: to prove "property P always holds," you assert ¬P and get **unsat** (no counterexample exists) or a **concrete counterexample model**. [VC — Microsoft Z3 guide, Wikipedia]

**Handles well:** linear integer/real arithmetic (decidable, fast), bitvectors (bit-blasting to SAT), arrays (extensional, but *unbounded* — no length notion), algebraic datatypes, uninterpreted functions, fixed-size problems. [VC]

**Handles poorly:** nonlinear integer arithmetic (**undecidable** — Matiyasevich; Z3 may return `unknown` or loop), quantified formulas (heuristic instantiation, often `unknown`), string equations (Z3-Noodler complete only for chain-free fragment + regular constraints; outside that, sound but incomplete), mixed integer/bitvector reasoning (weak propagation across the boundary). Same formula can take seconds or hours depending on encoding — heuristics dominate. [HC — Z3 internals draft, z3prover.github.io]

**Precedent for our use case:** Z3 already verifies access-control policies in industry — SELinux RBAC policies (arXiv 2312.04586, found a real Google-published CVE-class overpermissive rule), AWS access policies, NGAC obligations (cvc5). Authorization verification via SMT is established practice, not exotic. [HC]

---

## 2. The 5 constraint encodings (on paper)

### C1. Filesystem jail — every write path under the workspace root
**Encoding:** string prefix constraint. `p = String('p')`, `root = "/workspace"`. Jail property: `StartsWith(p, root)`. To find violations, assert a write with `Not(StartsWith(p, root))` ∧ "jail check passed" and ask for sat — a model is an escape path. Path *normalization* (`..`, symlinks, `C:\` vs `/`) must be axiomatized or normalized *before* Z3 sees it — Z3 strings know nothing about filesystems. The real subtlety: `"/workspace_evil/x"` starts with `"/workspace"` — so the constraint must be `StartsWith(p, root + sep) ∨ p == root`, and separator handling is OS-specific. [HC]
**Theory:** QF_S (strings/sequences). **Awkwardness:** medium — normalization is the actual work; Z3 checks the normalized form. Symlinks are invisible to the encoding (runtime concern).
**Verdict: LATER.** The check that matters is the 5-line runtime prefix test on the *canonicalized* path (`os.path.realpath` + `os.path.commonpath`). Z3 adds nothing at runtime (same logic, 1000× slower). Z3's value: *design-time* — prove the jail *function itself* correct against a path grammar once, via Dafny-style verification, not per-call.

### C2. Permission monotonicity — skill's effective permissions ⊆ its manifest
**Encoding:** sets as uninterpreted predicates or bitvectors. Permissions = finite enum (read, write, network, exec...). `granted(p)`, `manifest(p)` as Bool functions over a finite sort; assert `∀p: granted(p) → manifest(p)`; negation gives a concrete permission that leaked. Finite domain → decidable, fast (bitvector encoding: manifest as bitmask, check `(granted & ~manifest) == 0`). [VC]
**Theory:** QF_BV or EUF. **Awkwardness:** low — this is exactly the SELinux-RBAC pattern from the literature (arXiv 2312.04586). Transitive grants (skill A delegates to skill B) need the closure axiomatized, but it's finite.
**Verdict: ADOPT (design-time).** Encode the permission lattice + delegation rules once; run Z3 in CI on every skill-manifest change. Catches the "skill gained a permission nobody noticed" class. Runtime still enforces via bitmask check (nanoseconds). This is the single best Z3 fit of the five.

### C3. Budget invariants — tokens ≤ cap; retries × cost ≤ cap
**Encoding:** linear integer arithmetic. `spent`, `cap`, `attempts`, `cost_per_attempt` as Ints; assert `spent ≤ cap`, `attempts * cost ≤ cap` (linear when cost is constant). Ask: is there an execution reaching `spent > cap`? With constant costs this is trivially decidable and instant. [VC]
**Theory:** QF_LIA. **Awkwardness:** low — *but* the constraint is about *accumulation over a run*, which needs either bounded unrolling (k steps) or an inductive invariant. Z3 can't do induction; you prove the step preserves the invariant and separately argue the base case — that's Dafny/Boogie territory, or just a runtime counter.
**Verdict: SKIP (for Z3).** A runtime integer counter with `if spent + estimate > cap: refuse` is simpler, exact, and zero-dependency. The `deal`/`beartype` contracts already adopted cover the function boundary. Z3 would verify the counter logic — which is 3 lines. Not worth the integration.

### C4. Approval gate — tier-3 actions require an approval event before execution
**Encoding:** temporal ordering over a finite event trace. Model as: events `approve(a)`, `execute(a)` with integer timestamps `t_approve`, `t_execute`; property: `t_approve < t_execute` for all tier-3 `a`. Bounded trace (k events) → quantifier-free LIA + Booleans, decidable and fast. Unbounded ("for all possible runs") → needs induction over traces; Z3 alone can't do it — this is model-checking (TLA+) or runtime enforcement territory. [HC]
**Theory:** QF_LIA over a bounded trace. **Awkwarness:** medium — the encoding is easy, but it verifies a *model of the gate*, not the gate. The gap between the model and the shipped code is where bugs live (the TLA+ "spec↔code drift" lesson).
**Verdict: LATER.** The runtime gate (boolean flag set only by the approval handler, checked before dispatch — the Conscio circuit-breaker pattern) is the real enforcement. Z3/TLA+ modeling of the gate is a "once the design stabilizes" task (same verdict as TLA+ in the formal-methods study). Revisit with the approval-gate PlusCal model.

### C5. Idempotency — same key ⇒ no new side effects
**Encoding:** state equivalence. Two executions `s1 = apply(op, key, state)`, `s2 = apply(apply(op, key, state), key, state)`; property: `observable(s1) == observable(s2)`. Requires modeling `apply` — uninterpreted function + axioms, or a concrete state as arrays. For *concrete* ops (e.g., "insert row if key absent") this is encodable with arrays + quantifiers; for *arbitrary* tool code it's not — Z3 can't see inside Python. [HC]
**Theory:** Arrays + EUF (+ quantifiers → `unknown` risk). **Awkwardness:** high — the encoding effort scales with each op's complexity, and quantifiers over arrays invite `unknown`.
**Verdict: SKIP (for Z3).** This is Hypothesis's home turf: stateful property testing (`@given` operation sequences, assert second-apply is a no-op) exercises the *real code*, not a model of it. Already adopted in the formal-methods study. Z3's marginal value over PBT here ≈ 0.

---

## 3. The three layers — what verifies what

| Layer | Tool | Verifies | Cost | When |
|---|---|---|---|---|
| **Static/design-time proof** | Z3 (Dafny-style, CI) | Permission lattice, jail-function correctness vs path grammar | Minutes of CI, one-time encoding effort | Invariants that must hold for *all* inputs |
| **Property-based testing** | Hypothesis | Idempotency, serialization round-trips, atomic-write crash points — on the *real code* | Seconds per run, runs every commit | Behaviors over *many* inputs where a model would drift |
| **Runtime monitoring** | Deterministic guards (bitmask checks, counters, flags) | The actual live decision, every call | Nanoseconds | The enforcement point — always present |

Rule: **Z3 proves the design, Hypothesis tests the code, runtime guards enforce the decision.** Never ask one layer to do another's job. The model↔code gap is the eternal caveat: a proved model of a buggy implementation proves nothing — which is why layer 2 (tests on real code) is non-negotiable even where layer 1 exists. [HC]

---

## 4. Cost analysis (literature-reported, NOT measured)

- **Integration:** `z3-solver` on PyPI (official Microsoft bindings, `pip install z3-solver`, wheels for Windows/Linux/macOS). Import cost ~100–300ms (native lib load) — acceptable for CI/design-time, unacceptable per-tool-call. [HC — PyPI, widely reported]
- **Solve latency:** for our constraint sizes (dozens of variables, finite domains, linear arithmetic): **milliseconds** — Dafny precedent: small verification conditions discharge in ~0.3s including Boogie overhead; pure Z3 on QF_BV/QF_LIA of this size is typically 1–50ms. [HC — Dafny docs report 0.28–0.33s per VC with full pipeline; the Z3 portion is a fraction]
- **Pathological risk:** quantified string/array formulas can blow up to timeouts; mitigation = keep encodings quantifier-free and bounded, set `TryFor` timeouts (e.g., 5s), treat timeout as "inconclusive, fall back to testing" — never as "proved." [VC — Z3 tactics docs]
- **vs the cheap alternative:** `beartype` + `deal` contracts (already adopted) give per-call runtime checking at ~microsecond overhead with zero new dependency. Z3 is *not* a replacement — it's the design-time complement for the 2 constraints where exhaustive reasoning beats sampling.

---

## 5. Verdicts

| Constraint | Verdict | Rationale |
|---|---|---|
| C1 Filesystem jail | **LATER** | Runtime canonicalize+prefix test is the enforcement; Z3 proves the jail *function* once at design time (Dafny-style), not per-call |
| C2 Permission monotonicity | **ADOPT (design-time)** | Best fit — finite domain, matches published SELinux-RBAC precedent; run in CI on manifest changes; runtime keeps the bitmask check |
| C3 Budget invariants | **SKIP** | 3-line runtime counter is exact; Z3 verifies nothing the counter doesn't already guarantee |
| C4 Approval gate | **LATER** | Runtime boolean-flag gate is the enforcement; formal modeling waits for design freeze (with the TLA+ gate model) |
| C5 Idempotency | **SKIP** | Hypothesis stateful testing on real code dominates; Z3 can't see inside the op |

**Net new Z3 adoption: exactly one — C2, permission monotonicity, in CI.** Everything else stays with contracts + Hypothesis + runtime guards.

---

## Unknowns

1. [UK] Z3-Noodler's behavior on Windows-style path grammars (`\` separators, drive letters, UNC) — untested; C1's design-time proof needs this nailed first.
2. [UK] Delegation-closure encoding cost if skill graphs grow (transitive grants over N skills) — likely fine at N<100, unmeasured.
3. [UK] Whether the permission lattice stays finite as capabilities grow (network egress allowlists are string sets — pushes C2 toward the string theory, weakening the verdict; revisit if manifests gain URL patterns).
4. [SP] Solver version drift: Z3 5.x string-solver behavior changed across releases (Z3str3 → Z3-Noodler); pin the version in CI.

## References (all real, verified via search)

- Z3 internals draft (encoding guidance, quantifier/string limits): https://z3prover.github.io/papers/z3internals.html
- Z3 guide — arithmetic/theories (nonlinear undecidability): https://microsoft.github.io/z3guide/docs/theories/Arithmetic/
- Z3Py strategies/tactics (TryFor, solver combinators): http://www.cs.tau.ac.il/~msagiv/courses/asv/z3py/strategies-examples.htm
- UMD CMSC433 Z3/SMT tutorial (limitation table): https://www.cs.umd.edu/class/fall2025/cmsc433/Solving_SAT_and_SMT_Problems_Using_Z3.html
- Automated SELinux RBAC Policy Verification Using SMT (arXiv 2312.04586): https://arxiv.org/html/2312.04586v1/
- Z3-Noodler string solver (TACAS): https://link.springer.com/chapter/10.1007/978-3-031-57246-3_2
- Z3 theorem prover (bindings, MIT license): https://en.wikipedia.org/wiki/Z3_Theorem_Prover
- Dafny verification optimization (VC timing ~0.3s): https://dafny.org/v4.1.0/VerificationOptimization/VerificationOptimization
