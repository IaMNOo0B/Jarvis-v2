# JARVIS v2 — MASTER PLAN (Wave 1: The Spine)

*Planned 2026-10-19 per the JARVIS Master Planner spec. This is a contract: deviation voids.*
*Status: PROPOSED — awaiting Owais's approval to execute.*

---

## P1. Objective and success criteria [C]

**Objective:** Build v2's Wave-1 spine as a working text chatbot on Owais's PC: session store → Gate → brain → skills → memory, governed by JARVIS-RULES.txt, with tests proving each part.

**Done looks like (observable world-state):**
- `python -m jarvis chat` opens a text chat on Windows; user types, JARVIS answers.
- Every turn is recorded in the session store (SQLite WAL); restart resumes the session.
- The Gate blocks a test prompt-injection and an undeclared tool call (proven by tests, not claims).
- A skill can be added as a folder (SKILL.md + skill.json + skill.py) and is quarantined until approved.
- `pytest` passes 100% on the shipped suite.
- Delivered as a zip Owais installs via GitHub Desktop (pushes are 403-blocked).

**Falsification of success:** if the chatbot can't hold a 10-turn conversation without crashing, or any shipped test is faked/skipped — the plan failed.

## P2. Initial assessment and missing information

**Known:**
- 13 specs complete; 7 proven seed files (fallback chain, settings manager, hardened runner with 14 attack tests, event bus, event log, ReAct agent, plugin host with audit_wiring).
- Scaffold exists: ~/workspace/jarvis-v2/ (chat/, brain/, skills/, memory/, tools/, tests/, docs/).
- JARVIS-RULES.txt is the single rules source (38 rules, P0–P3).
- 2060 measurements: internet-sourced priors in hand; on-card numbers still unknown.
- GitHub: pushes 403-blocked; jarvis-v2 repo not yet created by Owais.

**Unknowns:**
- [Owais] Creates the `jarvis-v2` repo? (needed before any push attempt)
- [Tools] Will the GitHub 403 clear? (If not: zip delivery forever — already proven with jarvis-update.zip.)
- [Owais] 30-day usage logging starts at install (for difficulty distribution).

**Blocked on nothing.** Wave 1 needs no Owais input to build.

## P3. Recommended strategy and alternatives [C]

**Chosen: spine-first, text-only, local-only.**
Build the 5 spine components in dependency order, chat UI as a thin terminal/CLI first (Tauri comes Wave 2), brain = local Ollama/Qwen with the proven fallback chain, zero cloud dependency for Wave 1.

**Alternative 1 (rejected): UI-first.** Tempting for demo value — rejected: the autopsy proved UI-first is how v1 accumulated 210 findings. Spine first.

**Alternative 2 (rejected): full 12-box build at once.** Rejected: compounding error (6 chained steps ≈ 73% success). Waves exist for a reason.

## P4. Hierarchical task breakdown [C]

```
1. Foundation (no dependencies)
   1.1 Promote seed files into v2 layout (eventbus, eventlog, plugin_host+audit_wiring)
   1.2 Rules loader: parse JARVIS-RULES.txt → typed rule objects; P0 integrity check (missing P0 = refuse to start)
   1.3 Config: atomic writes, schema validation, OS-keyring secrets (from settings_manager seed)
2. Session store (needs 1.1)
   2.1 SQLite WAL schema: sessions, events (ULID, seq, causal_parent, actor, trust), checkpoints, tombstones
   2.2 Append-only enforcement + JSONL spillover
   2.3 wake(sessionId): checkpoint → replay → reconcile → crash.marker → announce
3. The Gate (needs 1.2, 2.1)
   3.1 Deterministic gate: permission check → tier lookup (manifest) → schema validation → tier-3 → approval hook
   3.2 Untrusted-output wrapping (<tool_output trust="untrusted">)
   3.3 Approval token binds action hash (kills replay/TOCTOU)
4. Brain (needs 3.1)
   4.1 ReAct loop (from react_agent seed) with 2-attempt cap and stopping rule
   4.2 Fallback chain (from fallback_fixed seed): walk OUTSIDE the try block; 20 simulated failures, 100% recovery
   4.3 Tier router: voice→tiny (stub), chat→7B local; escalation on 2 failures
5. Skills (needs 3.1, 1.1)
   5.1 Manifest discovery + strict validation (unknown keys = startup error)
   5.2 Quarantine inbox + static scan; dispatch pipeline: parse → validate → capability check → risk gate → bound → evidence-wrap
   5.3 Circuit breakers (3 fails → disable + notify)
   5.4 Ship 3 reference skills: echo/test, notes (file in jail), time
6. Memory (needs 2.1)
   6.1 Two stores: episodic (from session events) + semantic (versioned facts)
   6.2 Capture → extract → resolve (ADD/UPDATE/DELETE/NOOP) → quarantine gate
   6.3 Retrieval: FTS5 + vectors → RRF → rerank → top-5; quarantine markers visible
7. Chat CLI (needs 4.1, 6.3)
   7.1 Terminal chat loop: read → brain → gate → skills → session log → print
   7.2 Ten brain states as text labels; STOP wired (Ctrl+C halts cleanly)
8. Tests (parallel with each; gate before packaging)
   8.1 Unit: gate (injection blocked, undeclared tool blocked), jail escapes, atomic writes
   8.2 Attack suite: all 14 hardened_runner tests + 6 DCL exfiltration tests, 100% required
   8.3 Integration: 10-turn conversation, crash → wake → resume with no lost committed data
9. Package
   9.1 Zip: v2-wave1.zip + README (install steps, zero terminal — GUI/GDesktop only)
   9.2 Deliver to Owais with test report
```

Max depth 2. Each step's expected outcome is observable (file exists, test passes, behavior demonstrated).

## P5. Dependencies and execution sequence [C]

```
1.1, 1.2, 1.3 ──→ 2.1 ──→ 2.2, 2.3 ──┐
      │                    3.1 ──→ 3.2, 3.3 ──→ 4.x, 5.x
      └──────────────────────────────→ 6.x ──→ 7.x ──→ 8.x ──→ 9.x
```
PARALLEL-OK: 2.2/2.3 with 3.2/3.3; 5.x with 6.x (after 3.1); 8.x grows alongside each component.
Critical path: 1 → 2.1 → 3.1 → 4 → 7 → 8 → 9.

## P6. Time, budget, resources, technical requirements

- **Time:** Wave 1 ≈ 4–6 focused build sessions (estimate, [MC] — first v2 build, no velocity data).
- **Budget:** $0. Local-only; no cloud calls in Wave 1.
- **Resources:** this VM (build + tests); Owais's PC (install + 10-turn test + 2060 spot-checks later).
- **Technical:** Python 3.11+, SQLite (stdlib), pytest, no new dependencies without justification. 2060 budget: brain 7B Q4_K_M ≤5.5GB VRAM (from measurements file).

## P7. Risk analysis and mitigation [C]

| Risk | Mitigation | Pre-registered response |
|---|---|---|
| Scope creep into Wave 2 (UI, voice) | Todo list is the contract; new asks go to backlog | If a task isn't in P4: stop, ask |
| Seed files don't fit v2 layout | Adapt, don't rewrite; keep proven logic | If a seed needs >50% rewrite: flag, re-derive from spec |
| GitHub 403 persists | Zip delivery (proven path) | No push attempts after 2 failures; zip always |
| Over-engineering the Gate | ~200 lines target; spec is explicit | If Gate >400 lines: split or simplify, review |
| Tests faked to pass | Every test asserts a behavior, not a mock | Random test audit: pick 3, verify they fail when the code is broken |

## P8. Edge cases and contingency plans

- Owais creates jarvis-v2 repo mid-build → attempt one push; on 403, continue zip-only, no retry spiral.
- A spec turns out wrong mid-build → stop, surface to Owais with the evidence, don't silently reinterpret.
- Build blocked on a tool/environment limit → document exactly what's missing (First Mission rule), pivot to the next unblocked task.

## P9. Validation, testing, quality checkpoints [C]

- After §3: attack suite runs green (injection blocked, undeclared tool blocked, jail escape blocked).
- After §4: fallback chain survives 20 simulated failures per provider per type.
- After §7: 10-turn conversation, no crash; kill -9 mid-turn → wake resumes, zero committed-data loss.
- Before §9: FULL suite green, 100%. One red test = no package. No exceptions.

## P10. Progress tracking

- Todo list = the live contract (this chat's list, updated per step).
- Session events per component: built → tested → integrated.
- Delivery: zip + test report (passed/total, per-component). Honest numbers only.

## P11. Immediate next actions and completion checklist

**Next actions:**
1. Promote seed files into ~/workspace/jarvis-v2/ layout. ← START HERE
2. Build the rules loader (JARVIS-RULES.txt → typed rules + P0 check).
3. Session store schema + append-only + wake().

**Completion checklist:**
- [ ] Chat runs 10 turns without crash
- [ ] Gate blocks injection + undeclared tool (tests prove it)
- [ ] Crash → wake → resume, zero committed-data loss
- [ ] Skill added as folder → quarantined → approved → works
- [ ] pytest 100% green
- [ ] Zip delivered with test report

---

## Kill criteria (falsification)
- Any shipped test faked or skipped → plan failed, rebuild the test.
- Gate bypassed by any input in the attack suite → Wave 1 does not ship.
- 3 consecutive build sessions with no shippable increment → stop, diagnose (oscillation guard).

## Stopping rule
Per-turn EU applies to build steps too: if a step's expected value drops below its cost (e.g., gold-plating the CLI), cut it and ship.
