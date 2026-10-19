# v2 Skill System Specification

*PHASE INFINITY, Research Cycle 16. Design specification — the document the v2 skill system gets built from.*
*Date: 2026-10-19. Status: spec complete, unvalidated (no implementation exists).*
*Confidence on overall design: [HC] — every clause traces to a v1 corpse or a validated pattern; all numeric constants are PROPOSED.*

**Sources:** `FAILURE-ANALYSIS.md` skill findings (H-S1..H-S14, M-S1..M-S34, R11); `plugin_host.py` (proven manifest host with `audit_wiring()`); DECISION-PLAYBOOK (S1–S8, A2, A6, A7); Agent Plugins 1.0 (scout-log Study 10); SKILL.md industry standard.

**Design philosophy in one line:** the skill system is a *jail with a guest list* — skills declare exactly what they need, the runtime enforces it, the brain never sees what a skill wasn't granted, and nothing is ever silent.

---

## 1. The skill contract

A skill is a directory containing exactly three required files:

```
skills/<skill_name>/
  SKILL.md      — human/LLM-readable: frontmatter + progressive-disclosure instructions
  skill.json    — machine manifest: the CONTRACT (validated strictly, see §2)
  skill.py      — implementation: provides exactly one entrypoint, handle()
```

### 1.1 The manifest schema (skill.json) [HC]

Every field validated at startup. Unknown keys → **startup error naming the skill** (typo caught, not ignored — the plugin_host.py pattern).

| Field | Type | Required | Rule |
|---|---|---|---|
| `name` | string | yes | `^[a-z][a-z0-9_]*$`, must match directory name (M-S4-adjacent: no aliasing confusion) |
| `version` | string | yes | semver `MAJOR.MINOR.PATCH`; breaking contract change = MAJOR bump |
| `description` | string | yes | one line; this is what the brain matches against (Level 0 disclosure, §7) |
| `capabilities` | string[] | yes | Deno-style grants from the closed vocabulary in §3; empty = pure-compute skill |
| `tools` | object[] | yes | each tool: `name`, `description`, `parameters` (JSON Schema), `returns` (JSON Schema), `timeout_s`, `output_cap_chars`, `risk_tier` (1/2/3) |
| `lifecycle` | object | no | `on_load`, `on_unload` hook names; hooks run bounded (5s), no network, no tool calls |
| `resources` | object | no | declared heavy resources: `browser: true`, `model_files: [...]` — lets the host preflight |

**Clause SC-1:** A malformed manifest is a **startup error** naming the skill and the bad field. Never silently skipped (kills M-S3: malformed TOOL_DEFINITIONS silently skipped → silent capability loss).

**Clause SC-2:** A tool whose `handle()` is missing or not callable is a **startup error** naming the skill — the skill is not advertised at all (kills M-S2: missing handle still advertised → "Unknown tool" → LLM retry loop burning rounds).

**Clause SC-3:** Tool schemas are generated from function signatures where possible and **checked against the manifest at load** (A7 schema-first). Drift between code and manifest = startup error. Generated schemas can't drift; hand-written ones are verified.

### 1.2 skill.py constraints [HC]

- Provides `handle(tool_name: str, args: dict, ctx: SkillContext) -> dict`. No other public entrypoint.
- **No top-level side effects.** Import must be pure: no network calls, no `sys.path` mutation, no thread/process spawning, no file writes outside the skill dir. Violations are caught by the quarantine scan (§2) and by the import-timeout watchdog.
- `ctx` is the ONLY way a skill touches the world: `ctx.read_file()`, `ctx.http_get()`, `ctx.log()`, etc. — each gated by the skill's declared capabilities (§3). A skill calling `requests` or `open()` directly gets **denied at the OS level** where feasible and flagged in audit (defense in depth; the primary enforcement is code review + quarantine scan).
- Skills **may not import other skills** (kills M-S7: cascade imports — broken `everyday` killed `feed`). Shared code lives in a vetted `skillslib/` package, versioned separately.
- Skills **may not call other skills' `handle()` directly** (kills M-S31: `feed` bypassed dispatch isolation/logging). Cross-skill work goes through the dispatcher, which logs and permission-checks.

---

## 2. Manifest-based discovery

**Clause D-1: Discovery never executes untrusted code.** The scan reads `skill.json` files only. Import happens *after* manifest validation *and* (for new skills) user approval (kills H-S1: importing a skill executed top-level code at startup with full privileges — drop-in `skill.py` = RCE on next start).

### 2.1 Discovery algorithm

1. Scan `skills/` for directories containing `skill.json`. A directory without one is **not a skill** — logged once at startup as "ignored: no manifest", not an error (users drop notes folders in there).
2. Parse + strictly validate each manifest (SC-1). Failures → startup **error naming the skill**; the skill is excluded; startup continues (one bad skill never kills the host — the plugin_host.py isolation pattern).
3. **Duplicate skill names** (two dirs, same `manifest.name`) → startup **error naming both paths** (kills the directory-vs-manifest aliasing class adjacent to M-S4).
4. **Tool-name collisions across skills** → startup **error naming both skills and the tool** (kills M-S4: first-in-sorted-order silently shadowed the second). No shadowing, ever.
5. **New-skill quarantine:** a skill directory never seen before (no record in the approved-skills registry) is **not imported**. It appears in Settings → Skills as "awaiting approval" with its manifest, capability list, and quarantine scan results. The user approves → registry records the approval + manifest hash → import proceeds (S7: skill installs quarantined + scanned; answers the ClawHavoc lesson — 1,184 malicious skills in the wild).

### 2.2 Quarantine scan (static, at approval time) [MC]

Cheap, deterministic, no LLM:
- Manifest capabilities vs code imports: does the code import `socket`/`requests` while declaring no `net` capability? → **flag**.
- `eval(`, `exec(`, `__import__`, `subprocess` at module top level → **flag** (top-level side-effect risk).
- Reads of paths outside the skill dir at import time (static scan for `open(`/`Path(` with absolute paths) → **flag**.
- Manifest hash recorded at approval; **any change to skill.json or skill.py after approval → re-quarantine** (updated skill = new skill).

**Clause D-2:** The Agent Plugins 1.0 spec has **no signing** (verified correction). v2 does not rely on signatures it doesn't have — quarantine + scan + capability enforcement is the trust mechanism. If a signing story arrives later, it *adds* to this, never replaces it.

### 2.3 Loading (importlib, never exec) [VC — proven in plugin_host.py]

- `importlib.util.spec_from_file_location` with a **unique module namespace per host instance** (no `sys.modules` collisions across reloads).
- **Import timeout: 5s** in a worker thread (kills M-S6: skill blocking at import hung brain init forever). Timeout → load error recorded, skill excluded, startup continues.
- **`BaseException` caught per skill** (kills M-S5: only `Exception` caught — a `SystemExit` in one skill killed ALL skills + startup).
- Load failure → recorded on the skill record with the traceback; skill excluded; **user-visible notice** (R12 honest UX — never silent).
- `sys.path` is **never mutated** by skill loading (kills M-S8: `sys.path.insert(0, repo_root)` polluted imports and shadowed stdlib).

### 2.4 Wiring audit [VC — proven in plugin_host.py]

**Clause D-3:** After startup, `audit_wiring()` runs: every enabled, loadable skill whose entrypoint was never invoked during a self-test dispatch is reported as "registered but never wired." This is the test that would have caught v1's entire "created but never wired" bug class (echo guard C-V1 was the same disease in a different organ). Empty list or a startup warning naming names — never silent.

### 2.5 Hot reload

**Clause D-4:** Reload is a full unload → discover → validate → load cycle. Every skill's `on_unload` hook **must** release heavy resources (browser contexts, file handles). The host **tracks resource handles** per skill and force-releases orphans (kills M-S9: reload abandoned `_CTX` → zombie Chromium processes accumulated). A skill that can't unload cleanly twice in a row is flagged in audit.

---

## 3. The permission model — capabilities as Deno-style grants

**S2 (deny-by-default) is the law.** Undeclared = denied, loudly.

### 3.1 Capability vocabulary (closed — the manifest may only use these) [HC]

| Capability | Grants | Typical risk tier |
|---|---|---|
| `fs.read` | read files under declared `paths[]` (default: skill dir + workspace) | 1 |
| `fs.write` | write files under declared `paths[]` — always inside the R4 filesystem jail | 2 |
| `net.http` | outbound HTTP to declared `domains[]` only (egress allowlist, R5) | 2 |
| `net.websocket` | WS to declared domains | 2 |
| `shell.run` | subprocess execution, declared `commands[]` allowlist | 3 |
| `code.exec` | `execute_code`-style arbitrary code — sandboxed subprocess only (R5) | 3 |
| `ui.control` | keyboard/mouse/window control | 3 |
| `browser.use` | shared headless-browser context (host-managed, §6) | 2 |
| `clipboard` | read/write clipboard | 2 |
| `mic` / `camera` | capture devices (privacy: opt-in, R13) | 3 |
| `secrets.read` | read named secrets from OS keyring (never the values in logs) | 3 |
| `memory.write` | write to the memory store (provenance-tagged, M4) | 2 |
| `system.control` | process control, shutdown, services | 3 |

**Clause P-1:** Capabilities are **granted per task, not just per skill.** The manifest declares the maximum; each dispatch carries the *task grant* — the intersection of the skill's declaration and what the current turn is allowed. A skill declaring `ui.control` doesn't get it on a pure Q&A turn.

**Clause P-2:** The brain **never sees undeclared tools.** The tool list presented to the LLM is filtered: tool present ⟺ skill loaded + capability granted for this task. The model cannot hallucinate its way into an undeclared tool because the dispatcher rejects unknown tool names (defense in depth with SC-2).

**Clause P-3:** Every capability use is **logged to the session store** (R15): which skill, which capability, which arguments (redacted), which turn. The audit trail is the interrogation interface's raw material.

### 3.2 Risk tiers → confirmation gates [HC]

| Tier | Meaning | Gate |
|---|---|---|
| 1 | Read-only, reversible, local | none — auto-allow (S3 two-dial) |
| 2 | Writes, network egress, external state | **announce** (HUD activity feed; undo snapshot where applicable — S4) |
| 3 | Irreversible, destructive, privileged | **out-of-band confirmation** (R3): UI button/inline "yes", enforced in code, never a text token the model can emit |

**Clause P-4:** The tier is declared per *tool* in the manifest, and the dispatcher **upgrades, never downgrades**: if a tier-1 tool's arguments resolve to a destructive target (e.g., `fs.write` to a path outside its declared scope — rejected anyway by the jail), the gate fires. Tier is a floor, not a ceiling.

**Clause P-5:** Destructive tools check the gate **as the first statement** of dispatch — before any work, no `await` between check and action (kills C-S4: `taskkill` executed *before* the confirmation gate; and the TOCTOU class from the fault-tree study — the approval token embeds the action hash).

---

## 4. Tool execution pipeline

Every tool call flows through the same deterministic pipeline. **The LLM does judgment only** (which tool, which arguments); everything checkable is checked by code (verify-before-claiming, operationalized — AGENTS.md).

```
parse → schema-validate → capability-check → risk-gate → dispatch
  → bound → output-validate → evidence-wrap → event-log
```

**Clause E-1 — schema-validate:** arguments validated against the tool's JSON Schema with `beartype`-style strict typing at the boundary (learn-formal-methods: beartype USE at tool entry points). Invalid args → structured error returned to the brain (so it can self-correct), logged, counted toward the circuit breaker (§5).

**Clause E-2 — capability-check:** the tool's required capability ⊆ the task grant (§3, P-1). Failure → hard error, audit event, **no retry** (a permission failure is not transient).

**Clause E-3 — risk-gate:** tier-3 tools pause the pipeline for out-of-band confirmation (P-5). The pending-confirmation state is **per-turn with a lock**, never a global slot (kills M-S33: single global `_pending` — "yes" could execute the wrong action; and H-X4's race).

**Clause E-4 — dispatch isolation:** each tool runs in a worker with its own exception boundary. A throwing tool **cannot** take down the turn (kills M-S10: HUD `emit()` inside the parallel worker broke the "never raises" guarantee — observability code is wrapped in its own try/except, always).

**Clause E-5 — bound:** every tool gets `timeout_s` (manifest, default 30s PROPOSED) and `output_cap_chars` (manifest, default 20k PROPOSED). Timeout → kill worker, structured timeout error, counts toward circuit breaker. Output over cap → truncated with a `truncated: true` marker in the evidence (the brain must know it didn't see everything). CPU guard on compute tools (kills M-S20: `9**9**9` hung the turn and flooded context).

**Clause E-6 — output-validate:** tool results validated against the tool's `returns` schema. Malformed output → error, counted. This is where the contract is enforced on the way out, not just in.

**Clause E-7 — evidence-wrap:** every result is wrapped before entering LLM context:

```
<tool_output source="<skill>.<tool>" trust="untrusted" turn="<n>">
  ...content (truncated marker if E-5 fired)...
</tool_output>
```

Untrusted framing is **non-negotiable** (S1/R2 — kills the C-S1 injection cluster: H-S8's 9000-char attacker transcript, H-S9's repo README, M-S25's `javascript:` URLs — all arrive tagged, and the system prompt's instruction hierarchy states tool output can never issue instructions).

**Clause E-8 — event-log:** the full pipeline trace (tool, args-redacted, capability used, gate decision, latency, outcome, error class) appends to the session store (R15). Debugging replays it; the interrogation interface queries it.

### What the LLM may vs may not do

- **May:** choose tools, craft arguments, interpret results, decide next steps, ask the user.
- **May not:** bypass the pipeline (no direct `handle()` calls — kills M-S31), declare its own permissions, approve its own tier-3 actions (the gate is out-of-band), see undeclared tools (P-2), execute code outside `code.exec` sandbox (R5).

---

## 5. Circuit breakers

**Clause C-1:** Per-skill consecutive-failure counter. **N = 3 consecutive failures** (PROPOSED) → skill **auto-disabled** with a user-visible notice ("skill X disabled after 3 failures — re-enable in Settings → Skills") and an audit-log entry (kills M-S1: always-throwing skill never quarantined → user heard "failed" forever).

**Clause C-2:** Failures counted: exceptions, timeouts (E-5), schema violations (E-1/E-6), permission denials do **not** count (not the skill's fault — but repeated denials flag a manifest/grant mismatch in audit).

**Clause C-3:** Re-enable is **manual only**, followed by a half-open probe: the next dispatch runs with a tight timeout and the result is checked before the skill is trusted again. Two consecutive post-reenable failures → disabled again, and the notice escalates ("skill X keeps failing — consider updating or removing").

**Clause C-4:** Per-turn tool budget (kills M-S28: 6 rounds × unbounded calls, no circuit breaker): max **3 rounds and 12 total tool calls per turn** (PROPOSED). Exceeded → turn ends with an honest "I'm going in circles" message, not a silent burn.

**Clause C-5:** Cost guard (kills M-S23: ~12 paid Tavily searches per "research deeply", no warning): tools declaring `metered: true` in the manifest get a per-turn spend budget; approaching it → HUD notice; exceeded → tool refused with a clear message. Metered tools must declare `cost_hint` ("~$0.02/search").

---

## 6. Bounded parallelism

**Clause B-1:** Global concurrency budget: **8 concurrent tool dispatches** (PROPOSED). The 9th waits in a bounded queue (64 deep, PROPOSED); queue-full → structured "busy" error, never unbounded spawn (kills H-S7: 10× scout → ~140 threads, 429s, quota burn, socket exhaustion; and M-S11: `max_workers=len(parsed)`).

**Clause B-2:** Per-domain rate buckets: network tools declare their domain (`tavily`, `github`, …); each domain gets a token bucket (rate + burst, PROPOSED defaults from the domain's documented limits). 429 → **exponential backoff with jitter**, shared across skills (kills M-S12: scout and github skill unknowingly shared the 60/hr unauthenticated quota → silent degradation; and M-S32: bare `except → None` burned a failed request *then* fell back — the failure is now classified once, and the fallback is explicit in the tool's contract).

**Clause C-6 (quota dead-ends):** A tool whose backend quota is exhausted reports `quota_exhausted` as a **first-class outcome** — the brain sees "Tavily quota exhausted, falling back to DDGS" instead of a mysterious failure (kills M-S22: MyMemory quota dead-ends with no fallback).

**Clause B-3:** No global serialization locks around heterogeneous tools (kills M-S30: one `_LOCK` serialized all browser ops — a 20s navigation blocked everything). Shared heavy resources (the headless browser) are **host-managed pools** with per-tool checkout, declared in `resources` (SC-1), released by `on_unload` (D-4).

**Clause B-4:** Browser lifecycle is the host's job, not the skill's: the pool opens/closes contexts; skills check them out. Zombie processes are impossible by construction (kills M-S14: browser never closed → zombie Chromium holding temp profiles).

---

## 7. The SKILL.md standard + Agent Plugins 1.0 packaging

### 7.1 SKILL.md — progressive disclosure [HC — industry converged, A6]

Three levels. The brain's context is a budget; skills spend it only when relevant.

- **Level 0 — always loaded:** `name`, one-line `description`, trigger phrases. (~30 tokens/skill. 40 skills ≈ 1.2k tokens — affordable.)
- **Level 1 — on trigger:** the full SKILL.md body: when to use, how to use, argument guidance, examples, known limitations. Loaded when the brain selects the skill or the dispatcher matches a trigger.
- **Level 2 — on demand:** `resources/` — scripts, reference docs, schemas. Loaded only when the skill's instructions reference them.

**Clause K-1:** SKILL.md frontmatter carries `name`, `version`, `description` — and the loader **cross-checks frontmatter against skill.json**. Mismatch = startup error naming the skill (one source of truth is skill.json; SKILL.md must agree).

**Clause K-2:** v2's SKILL.md adds two sections the base standard lacks: `## Permissions` (human-readable rendering of the capability manifest — the user approves *this*) and `## Evidence` (what the skill records per call — the audit contract). Format stays compatible with agentskills.io readers; the additions are additive.

### 7.2 Packaging — Agent Plugins 1.0 [MC — spec is young, Aug 2026]

A distributable plugin = directory with `plugin.json` + `skills/` + optional `mcp.json` (scout-log Study 10). v2 adopts this as the **install/packaging format**:

- `plugin.json`: plugin-level metadata (name, version, author, license, contained skills).
- `skills/`: one or more skill directories, each conforming to §1.
- `mcp.json` (optional): MCP server declarations — loaded as *tools through the same pipeline* (§4), not as a side channel.

**Clause K-3 — failure isolation mandated:** a plugin whose MCP server fails to start does **not** take its skills down — the loader skips the entry, keeps loading, surfaces it in the audit trail (the spec mandates this; v2 implements it).

**Clause K-4:** Installing a plugin = dropping it into the quarantine inbox → the §2 approval flow. There is no "install and auto-trust." Updates to an installed plugin re-trigger quarantine (D-2: manifest hash change = new skill).

---

## 8. Failure table — every v1 skill corpse mapped to its clause

*No orphans: every finding below names the clause that prevents its recurrence. Findings marked (R6)/(R5)/(R3) are owned by sibling specs with the skill-system clause that interfaces them.*

### Discovery / loading

| Finding | Clause |
|---|---|
| H-S1 import executes top-level code at startup (drop-in = RCE) | D-1 (never execute before validate+approve), §1.2 (no top-level side effects), D-2 (quarantine scan) |
| M-S1 always-throws skill never auto-disabled | C-1, C-3 |
| M-S2 missing/non-callable handle still advertised | SC-2 |
| M-S3 malformed TOOL_DEFINITIONS silently skipped | SC-1 |
| M-S4 cross-skill tool-name collision, silent shadowing | §2.1 step 4 — startup error, never shadowing |
| M-S5 BaseException (SystemExit) kills all skills | §2.3 — BaseException caught per skill |
| M-S6 skill blocks at import, hangs brain init | §2.3 — 5s import timeout |
| M-S7 cascade imports (broken everyday kills feed) | §1.2 — skills may not import skills; shared code in vetted skillslib |
| M-S8 sys.path pollution, stdlib shadowing | §2.3 — sys.path never mutated |
| M-S9 reload abandons browser ctx → zombie Chromium | D-4 (on_unload + host-tracked handles), B-4 (host-managed browser pool) |

### Permissions / security

| Finding | Clause |
|---|---|
| C-S1/S5/S6 prompt injection = RCE (tool output raw into context) | E-7 (untrusted framing, non-negotiable) + R2 system prompt |
| C-S2 execute_code unsandboxed | §3 `code.exec` capability — sandboxed subprocess only (R5) |
| C-S3 workspace_only_writes enforced nowhere | `fs.write` capability scoped to declared paths + R4 jail; P-4 (tier floor) |
| C-S4 kill_process executed before confirmation gate | P-5 (gate first statement, no await between check and action) |
| H-S2 close_app force-kill, zero confirmation | P-4/P-5 — tier-3 by default for process control |
| H-S3 open_url/open_path executes arbitrary strings | capability `shell.run`/`browser.use` with declared allowlists; tier-3 |
| H-S4 unattended GUI control, zero confirmation | `ui.control` capability, tier-3, per-task grant (P-1) |
| H-S6 browser: no URL validation, file:// exfil, SSRF, silent form submits | `browser.use` via host pool (B-4); URL allowlist in manifest; SSRF block (no 169.254.0.0/8, no localhost unless declared); form-submit = tier-2 announce |
| H-S8/H-S9 attacker-controlled content into context | E-7 evidence wrapping (source + trust tags) |
| H-S10 LLM-triggerable pip install | S8 — installs are never tools; §3 vocabulary has no `pip.install` capability by design |
| H-S14 unverified OllamaSetup.exe download+exec | same — no download-and-execute capability exists; setup is a UI action, not a tool |
| M-S31 feed called other skills' handle() directly | §1.2 — forbidden; cross-skill via dispatcher only |
| M-S34 github _create_issue, no confirmation | tier-2 minimum for external-state writes; tier-3 for public/persistent ones |
| M-S10 observability code broke "never raises" | E-4 — emit wrapped in its own try/except, always |
| M-S25 javascript: URLs in generated HTML reports | E-7 (untrusted framing) + output contract: `returns` schema for HTML tools strips scriptable schemes |

### Resources / reliability

| Finding | Clause |
|---|---|
| H-S7 unbounded parallelism (140 threads, quota burn) | B-1 (budget of 8), B-2 (per-domain buckets + backoff) |
| M-S11 max_workers = len(parsed), unbounded | B-1 |
| M-S30 one global lock serialized all browser ops | B-3 (host-managed pool, no global lock) |
| M-S28 no per-turn tool budget (looping model burns quota) | C-4 (3 rounds / 12 calls per turn) |
| M-S23 paid Tavily, no cost guard | C-5 (metered tools, per-turn spend budget) |
| M-S12 scout+github shared 60/hr quota unknowingly | B-2 (shared per-domain bucket, visible) |
| M-S32 bare except → burned request then fell back | B-2 (failure classified once, fallback explicit in contract) |
| M-S22 quota dead-ends (MyMemory) with no fallback | C-6 (quota_exhausted as first-class outcome) |
| M-S20 _calculate: no CPU/output guard | E-5 (timeout + output cap + CPU guard) |
| M-S19 finished timers never removed (unbounded growth) | E-5 output caps + D-4 resource tracking; state hygiene is a review checklist item |
| M-S14 browser never closed (zombie Chromium) | B-4 |
| M-S17 in-place rewrite of x_cookies.json (corrupt = dead) | R6 atomic writes — the skill-system interface: skills persist via ctx.storage (atomic, backed up), never raw open() |

### Quality / contracts

| Finding | Clause |
|---|---|
| M-S24 brittle regex coupling to actions.py output | contracts are schemas (SC-3), not regexes; cross-component parsing is a review red flag |
| M-S26 dangling cross-skill reference (media→social) | §1.2 (no cross-skill imports) + startup validation of declared dependencies |
| M-S33 _pending global confirm slot ("yes" → wrong action) | E-3 (per-turn locked pending state) |
| M-S16 401/403/429 collapsed into one message | B-2 (classified failures); error taxonomy in returns schema |
| M-S15 git pull mid-session (Frankenstein state) | S8 — updates are never tools (R10) |
| M-S21 plain-HTTP ip-api (spoofable) | manifest `net.http` requires declared domains; review checklist requires https for non-public data |
| M-S13 clipboard_set clobbers password silently | `clipboard` capability, tier-2 announce ("clipboard overwritten") |
| M-S27 history unbounded (brain-side) | owned by brain spec; skill interface: E-5 output caps bound per-call contribution |

### Adjacent (owned by sibling specs, interfaced here)

| Finding | Owner | Skill-system interface |
|---|---|---|
| H-S11/H-S12/H-S13 persistence: non-atomic, no locking, wrong paths | R6 | skills persist only via `ctx.storage` (atomic + backup + data-dir) |
| M-S29 config promises safety the code doesn't implement | R7 | every safety-relevant manifest field has a runtime enforcement point; audit_wiring (D-3) verifies the wiring |

---

## Open questions [UK unless noted]

1. **Numeric constants are all PROPOSED:** circuit-breaker N=3, import timeout 5s, dispatch timeout 30s, output cap 20k chars, global budget 8, queue 64, per-turn 3 rounds/12 calls. The benchmarking weekend + production experience sets them. [MC that defaults are sane; UK on optimal]
2. **OS-level enforcement depth:** how far can capability denial go on Windows without a driver? (Job objects + restricted tokens are the realistic ceiling — needs a spike.)
3. **The `skillslib` governance:** who vets shared code, and how do skills pin versions? (Proposed: vendored per-skill snapshots, hash-pinned.)
4. **MCP servers inside plugins:** `mcp.json` tools flow through §4 — but MCP servers are long-lived processes with their own sandbox story. Needs a dedicated study before v2 ships plugin MCP support. [Recommendation: ship skills first, MCP second.]
5. **Approval UX for quarantine:** what exactly does Owais see when a new skill awaits approval? (Needs the frontend study's sliding-scale autonomy work — learn-frontend.md.)
6. **Hot upgrade of a running skill:** D-4 covers reload; *version migration* of skill state (v1→v2 of a skill with stored data) is unspecified.

## Confidence & unknowns

- [VC] The failure→clause mapping: every v1 skill corpse has a named clause; the table was checked twice.
- [HC] The overall architecture: manifest + capabilities + pipeline + breakers is the converged shape (Deno, Agent Plugins 1.0, plugin_host.py proof, A2/A6).
- [MC] Quarantine scan effectiveness: static scans catch lazy malware, not determined adversaries. It raises the bar; it is not a proof.
- [SP] That 8 concurrent dispatches is the right budget — workload-dependent, measure in production.
- [UK] Windows OS-level sandboxing ceiling; MCP server sandbox story; optimal numeric constants.

**Honest completion (Rule 12):** Researched: FAILURE-ANALYSIS.md skill findings (all), plugin_host.py (261 lines, in full), DECISION-PLAYBOOK.md skill/tool entries, scout-log Study 10 (Agent Plugins 1.0). Validated: finding IDs cross-checked against the analysis; plugin_host patterns verified by reading the code. Saved: 1 file. Tested/Measured: nothing (design only). Incomplete: none — all 8 requested sections written. Blocked: none.
