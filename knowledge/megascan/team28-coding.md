# MEGA-SCAN TEAM 28 — PERSONAL CODING AGENTS (synthesis)

**Mission:** find the upgrade path for JARVIS v2's `skills/code` (today: `code_read`
tier-1 whole-file · `code_write`/`code_edit` tier-2 exact-once + `.bak` undo ·
`code_run` tier-3 subprocess sandbox, 10s, socket-neutered, jailed to
`<data_dir>/code`, stdlib-only).

**Count: 40 repo topics studied, all cloned locally and read from disk** (no API
reads — the 429 wall was avoided entirely by `git clone --depth 1` + local
reads). Part files:

| Slice | File | Lines | Repos |
|---|---|---|---|
| A — pair programmers & edit representation | `team28-part-a-pairprogrammers.md` | 1,036 | aider, cline, Roo-Code, goose, plandex, opencode, crush, gemini-cli, qwen-code, codex |
| B — autonomous SWE agents & verification | `team28-part-b-sweagents.md` | 248 | SWE-agent, mini-swe-agent, OpenHands, Agentless, auto-code-rover, moatless-tools, SWE-bench, gpt-engineer, MetaGPT, smol-developer |
| C — code review bots & diff analysis | `team28-part-c-review.md` | 709 | pr-agent, sweep, reviewdog, kodus-ai, code-review-gpt, ai-review, ChatGPT-CodeReview, ai-pr-reviewer (substitute), ai-codereviewer, danger |
| D — repo understanding & sandbox infra | `team28-part-d-context.md` | 695 | serena, tabby, refact, void, cody (public snapshot), e2b code-interpreter, daytona (OSS tag), bloop, CodeBERT, aider (discovered) |

**Process note (honest):** the first A and D workers went off-task and audited
v2's own code skill instead of the external repos. They were re-run/replaced;
the audits were kept as a bonus — two independent workers converged on the same
v2 flaws (see §5), which cross-validates them. Clone deviations under 30-team
bandwidth contention (sparse/blobless clones for goose, Roo-Code, void, cody;
sparse for auto-code-rover) are logged in each part file's clone ledger; every
cited file was read on disk.

## 1. The four convergences (what the whole field agrees on)

### 1.1 Verification is a skeleton, not a vibe (Slice B)
Five repos independently implement the same loop: **reproduce the bug first →
snapshot the baseline tests → apply the fix → differential verify (reproduction
now passes AND zero previously-passing tests regressed) → no parseable test
output means NOT verified → the generator never grades itself.** v2's code
skill has none of this as mechanism — `code_run` runs arbitrary code, but
nothing runs the *project's tests* and compares against a baseline. This is the
single biggest gap between v2 and the field.

### 1.2 Nobody ships exact-only edit matching (Slice A)
Every serious pair programmer degrades gracefully: **exact → whitespace-tolerant
→ Unicode-folded → structural** (aider `search_replace.py` cross-products 3
engines × 4 preprocessors; codex `seek_sequence.rs` runs 4 passes; gemini-cli
`edit.ts` 4 strategies). Location fuzz is safe because uniqueness is still
enforced at every rung and the matched rung is reported; replacement fuzz is
where tools refuse to go. v2's exact-once `code_edit` is the strictest outlier
in the slice — safe, but it will fail on real-world whitespace drift that every
competitor tolerates. Companion rule, also universal: **read-before-edit with a
freshness check** (crush mtime gate, qwen prior-read cache + TOCTOU
double-check) and **failure diagnostics as a first-class return** (similar-lines
reports, "did you mean", typed errors) instead of a bare "not found".

### 1.3 Structural retrieval beat embeddings — skip the vector DB (Slices A+D)
Aider's repo map (tree-sitter def/ref graph + personalized PageRank + token
budgeting), Serena's LSP symbol tools, Void's live editor-symbol context and
Cody's context providers all retrieve *exactly*; Bloop's triple-index
(embeddings included) is dead, Refact keeps its vecdb optional, and Roo-Code —
the only embeddings user in Slice A — makes it opt-in. For a stdlib-only skill
on a 6 GB GPU that should never wake for indexing, this is decisive: **AST
structure + PageRank + a sqlite mtime cache is the repo-understanding stack**,
and Serena shows the tool *shape* (`get_symbols_overview`, `find_symbol`,
`find_referencing_symbols`, `replace_symbol_body`) that a local model can drive
reliably.

### 1.4 False-positive control is a stack, not a prompt (Slice C)
Review quality comes from layered deterministic gates around the model, in
ascending cost: diff restricted to added lines (reviewdog `filter/filter.go` —
no LLM at all) → per-file calls with wrong-file discard → self-reflection
scores attached to every finding, never silently trusted (pr-agent) →
demote-don't-delete validation of suggested fixes (kodus: >15 lines/>1000 chars,
non-simple, or fails syntax-parse ⇒ demoted, kept visible) → supermajority
voting across parallel reviews (sweep ≥4/5; re-implementable in stdlib with
shingle-Jaccard instead of embeddings, or 3 local samples with ≥2/3 to report).
pr-agent additionally contributes the diff pipeline itself: extend-then-compress
with exact token recounts, deletion-hunk removal, manufactured line numbers, and
a persistent active/resolved/dismissed finding state.

## 2. Top 5 mechanisms (PhD shortlist)

1. **The differential verification skeleton** (Slice B — SWE-agent / Agentless /
   SWE-bench harness lineage): reproduce → baseline → fix → F2P/P2P verdict
   (FULL / PARTIAL / NO). Pure stdlib; turns `code_run` from a toy executor
   into a *proof* the edit worked.
2. **Aider's PageRank repo map** (`repomap.py`, Apache-2.0): def/ref graph,
   hand-tuned personalization (×50 chat-file referencers, ×10 mentioned idents,
   sqrt on ref counts), token-budgeted tree rendering, mtime/sqlite cache.
   ~900 lines upstream; the stdlib port uses `ast` instead of tree-sitter.
3. **The 4-rung match ladder with uniqueness per rung** (Slice A — aider /
   codex / gemini-cli convergent): location fuzz only, matched rung reported,
   replacement always exact. ~150 lines of stdlib.
4. **Serena's symbol tool surface over an exact index** (Slice D): overview /
   find / references / replace-body — the safest possible refactor primitive
   for a small local model, composing with `.bak` undo. (Serena app is
   GPL-3.0 — steal the *shape*, implement over stdlib `ast`; SolidLSP is MIT.)
5. **pr-agent's finding lifecycle + self-reflection scoring** (Slice C, MIT):
   every review finding carries a score and a state (active/resolved/dismissed);
   unvetted output is labelled, never silently trusted. Directly reusable for a
   self-review pass on JARVIS's own edits before the owner sees them.

*Runner-ups:* shadow-git/temp-index checkpointing (A — undo that never touches
the user's git; v2's `.bak` is 1-generation by contrast) · reviewdog's
added-mode post-gate (C — ~100 stdlib lines, should gate every LLM finding) ·
Void's paginated read contract + budgeted directory string (D — kills
whole-file reads) · mini-swe-agent's process-tree kill on timeout + in-code
budget breakers (B) · E2B/Daytona's *declarative* network policy objects (D —
policy as audited data: `networkBlockAll | allowList | domainAllowList`).

## 3. Top 3 steals for v2 `skills/code` (ranked)

### Steal 1 — `code_map`: Aider's repo map, stdlib port (Slices A+D agree)
- `ast` def/ref tags for Python (regex fallback for other languages),
  ~25-line personalized PageRank power iteration with aider's weights,
  `sqlite3` mtime cache, token-budgeted tree rendering. ~250 lines, tier-1.
- Closes v2's "model must know paths blind" gap: no `code_list`, no grep, no
  map today (`ctx.list_dir` exists but is unexposed). Pair with Void-style
  **ranged/paginated `code_read`** (`{startLine,endLine} → {totalNumLines,
  hasNextPage}`) and a budgeted `code_list`.

### Steal 2 — `code_verify`: the differential verification loop (Slice B)
- New tier-2/3 tool: run the jail project's tests (or a named repro script)
  *before* the edit session to snapshot the baseline, then after edits re-run
  and report F2P (fixed) / P2P (still passing) / regressions, verdict
  FULL/PARTIAL/NO — "no parseable output ⇒ not verified" as a hard rule.
- Include SWE-agent's lint gate in stdlib form: `ast.parse` the file before
  and after every `code_edit`; a syntax-breaking edit auto-reverts from `.bak`
  and reports instead of landing.
- This is the mechanism that makes "JARVIS fixed it" a checked claim instead
  of a model's assertion — it plugs straight into v2's existing
  CompletionAudit doctrine.

### Steal 3 — Match ladder + freshness gate for `code_edit` (Slice A)
- 4 rungs (exact → uniform-leading-whitespace strip + re-indent → trim-end →
  Unicode-fold), uniqueness enforced per rung, matched rung returned in the
  result. Location fuzz only — replacement text always applied verbatim.
- `code_read` records (mtime, size, sha256); `code_edit`/`code_write` refuse
  never-read or stale files. `NO_MATCH` errors carry `difflib` most-similar
  line ranges (aider's own diagnostic technique) plus a 2-reflection cap before
  escalating to whole-file rewrite.

**Immediately behind the top 3:** the sandbox hardening pack from the §5 audit
(env **allowlist** instead of proxy-denylist, audit-hook preamble blocking
`open` outside the jail + subprocess events, process-tree kill via Windows Job
Object through ctypes) — the current socket-neutering preamble is bypassable via
`import _socket` / subprocess respawn and the child env currently leaks parent
secrets.

## 4. License map (verified from LICENSE files in the clones)

- **Steal code freely (MIT / Apache-2.0):** aider, cline, Roo-Code, plandex,
  opencode, gemini-cli, qwen-code, codex, SWE-agent, mini-swe-agent, Agentless,
  moatless-tools, SWE-bench, gpt-engineer, MetaGPT, smol-developer, pr-agent,
  reviewdog, code-review-gpt, ai-review (Apache-2.0), ChatGPT-CodeReview (ISC),
  ai-codereviewer, danger, tabby, refact, void, CodeBERT, e2b code-interpreter.
- **Ideas only — never code:** auto-code-rover (**SONAR Source-Available v1.0,
  "Non-competitive Purpose"** — the slice's license trap; it is *not* MIT),
  kodus-ai (AGPL-3.0 + EE), daytona (AGPL-3.0), serena app (GPL-3.0; SolidLSP
  library is MIT), sweep (EE), crush (**FSL-1.1-MIT** — converts to MIT later,
  treat as ideas-only until then).
- **Upstream rot, honestly logged:** `coderabbitai/ai-pr-reviewer` is deleted
  (verified 404) — Slice C studied the highest-starred exact-name substitute
  and documented it as an anti-pattern exhibit (char-count-as-token-budget,
  schema weakened to free strings, zero FP control); `sourcegraph/cody` is
  private (Free/Pro discontinued Jul 2025) → official public snapshot studied;
  `OpenHands/OpenHands` at HEAD is only the Agent Canvas TS frontend — the
  Python agent/runtime now lives in `OpenHands/software-agent-sdk` (reassign
  if a classic-OpenHands deep study is still wanted); Daytona `main` is
  README-only since dev moved private (Jun 2026) → last OSS tag `v0.190.0`
  studied; `bloop-ai/bloop` 404s — real org is `BloopAI/bloop`.

## 5. Bonus: v2's own code skill — two independent audits, same verdict

(From the two off-task workers, cross-validated.) **Keep:** exactly-once edit
with self-teaching errors, backup-before-write, atomic tmp+rename in the host
context, XOR code/path validation, dual output caps, timeout-as-result shape,
and above all the architecture — *the jail lives in `SkillContext`, not the
skill*, so the 145-line skill contains zero security code to get wrong.
**Fix:** (1) the sandbox is a polite fence, not a jail — executed code can
`open()` anywhere, spawn subprocesses, and reload `_socket` past the network
guard; (2) child env = full parent env minus `*proxy*` keys — **secrets in env
are readable by sandboxed code**; (3) timeout kills the direct child only,
grandchildren survive (worst on Windows); (4) no CPU/RAM/disk limits;
(5) per-stream 10 KB caps make the real ceiling ~20 KB despite the "10 KB
combined" docstring; (6) `.bak` undo is exactly 1 generation deep;
(7) `code_edit` with `old_text=""` passes the exactly-once check on an empty
file — guard non-empty. Tier-3 HMAC approval (gate binds approval to
`action_hash(tool, args)`) is the real control today; the audit-hook + env
allowlist + Job Object pack in §3 is the fix path, all stdlib/ctypes.

## 6. Anti-steals (documented so nobody re-proposes them)

Docker-based sandboxes (owner's PC, stdlib-only — no), `shell=True` execution
patterns from gpt-engineer/MetaGPT/mini-swe-agent-local (v2's no-shell
`code_run` is *ahead* of this slice), Agentless's 20-sample repair voting at
local-model scale, MCTS/SBFL/reviewer-model loops (need a strong second model
v2 doesn't have locally), MetaGPT's SOP ceremony, and any embeddings-first
repo index as the *primary* retrieval path (§1.3).

**Outcome label: known techniques, convergently validated.** Nothing here is
novel — that is the point. Four independent slices, 40 codebases, and the same
skeleton keeps appearing: structural retrieval, degraded-but-unique matching,
differential verification, layered FP control. v2 already owns the safety
architecture (tiers, gate, jail-in-context); the upgrade path is Steals 1–3
plus the sandbox pack, all implementable in stdlib Python inside the existing
tier model.
