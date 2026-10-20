# Team 28 — Slice D: Repo Understanding, Context Selection & Sandbox Infra (PhD-level)

Study method: every repo below was cloned LOCALLY (`git clone --depth 1`, verified with `ls` + `git log`)
into `~/workspace/jarvis-knowledge/megascan/.work28/sliceD/<repo>` and read from the working tree —
no GitHub API reads (429 risk). File:line references are to the cloned tree.
Clone-status note (honesty): the VM was under extreme clone contention (~30 mega-scan teams cloning
in parallel); several clones took 15–40 min and two (bloop, CodeBERT) repeatedly died mid-fetch —
their outcomes are stated explicitly in their sections, never papered over.

Target context for steal verdicts: JARVIS v2 `skills/code` is Python 3.11+ **stdlib only**, tiered
tools — `code_read` tier-1 whole-file only, `code_write`/`code_edit` tier-2 exact-once with `.bak`
undo, `code_run` tier-3 subprocess sandbox (10 s, socket-neutered, jailed to `<data_dir>/code`).
Known gaps: no repo map / no `code_list` / no grep tool, whole-file reads only, sandbox lacks
OS-level confinement + env allowlist, no LSP or symbol-level retrieval. Owner PC: Windows, RTX 2060 6 GB.

---

## 1. oraios/serena — LSP-based code retrieval (the no-vector-DB answer)

- **Clone:** `serena/` — HEAD `dc60fba "Set version to v2.1.1.dev0"`, verified.
- **License (read from `serena/LICENSE`):** per-component — SolidLSP is **MIT**, the Serena
  application is **GPL-3.0-or-later**; the combined `serena-agent` package is GPL-3.0-or-later as a
  whole. Full texts in `serena/LICENSES/{MIT,GPL-3.0-or-later}.txt`. → For JARVIS: *ideas freely
  stealable; SolidLSP code borrowable under MIT; Serena app code is GPL — do NOT copy it.*

### Exact tools exposed to the model (all in `src/serena/tools/`)

Symbolic (LSP) read tools — `symbol_tools.py`:
- `GetSymbolsOverviewTool` (`symbol_tools.py:45`) — `apply(relative_path, depth=-1, max_answer_chars=-1)`;
  returns symbols grouped by kind in compact JSON; docstring instructs the model: *"This should be
  the first tool to call when you want to understand a new file."*
- `FindSymbolTool` (`symbol_tools.py:73`) — `apply(name_path_pattern, depth=0, relative_path="",
  include_body=False, include_info=False, include_kinds=[], exclude_kinds=[], substring_matching=False,
  max_matches=-1, max_answer_chars=-1)`. Name-path semantics: `MyClass/my_method`, overloads get a
  `[i]` suffix, leading `/` = absolute match, plain name = suffix match anywhere.
- `FindReferencingSymbolsTool` (`symbol_tools.py:158`) — references + a short snippet around each.
- `FindImplementationsTool` (`symbol_tools.py:197`), `FindDeclarationTool` (`symbol_tools.py:238`),
  `GetDiagnosticsForFileTool` (`:279`), `GetDiagnosticsForSymbolTool` (`:313`),
  `RestartLanguageServerTool` (`:35`).

Symbolic edit tools — same file: `ReplaceSymbolBodyTool` (`:352`), `InsertAfterSymbolTool` (`:380`),
`InsertBeforeSymbolTool` (`:405`), `RenameSymbolTool` (`:430`, LSP rename = all references updated
atomically by the server), `SafeDeleteSymbol` (`:455`, refuses if still referenced).

File tools — `file_tools.py`: `ReadFileTool:45`, `CreateTextFileTool:65`, `ListDirTool:82`,
`FindFileTool:105` (glob), `ReplaceContentTool:122` (literal/regex, `allow_multiple_occurrences`
defaults to *error on multiple matches* — the same exact-once discipline as v2's `code_edit`),
`ReplaceInFilesTool:163`, line tools (`DeleteLines:240`, `ReplaceLines:264`, `InsertAtLine:290`, all
marked Optional), and `SearchForPatternTool:315` — regex across the project with
`paths_include_glob`/`paths_exclude_glob`, `restrict_search_to_code_files`, `skip_ignored_files=True`
(gitignore-aware), multiline by default, returning *file → matched lines with 0-based line numbers*,
plus the prompt-level instruction: *"Prefer symbolic operations if you know which symbols you are
looking for!"*

Other tool families: `ExecuteShellCommandTool` (`cmd_tools.py:27`), project/config tools
(`config_tools.py`), a JetBrains-IDE-backed duplicate family (`jetbrains_tools.py`, incl.
type-hierarchy + inspections), and memory tools (below). Tools are classified by marker mixins in
`tools_base.py:71-105` — `ToolMarkerCanEdit`, `ToolMarkerSymbolicRead`, `ToolMarkerSymbolicEdit`,
`ToolMarkerOptional`, `ToolMarkerDoesNotRequireActiveProject` — so a *mode* (e.g. onboarding,
planning) is just a set subtraction over markers. Every tool result passes through a
`max_answer_chars` budget (config default in `config/serena_config.py:924`): oversize answers are
progressively shortened instead of truncating mid-structure.

### How it avoids a vector DB — entirely

There is **no embedding/vector dependency at all**: `pyproject.toml:20-50` dependencies are
`requests, mcp, pydantic, pyyaml, flask, pygls, lsprotocol, tiktoken…` — grep for
`embedding|vector|chromadb|faiss` across `src/serena/` returns exactly one comment
(`agno.py:118`, noting a *user* might add vector tools). Retrieval is delegated to real language
servers via the bundled **SolidLSP** library (`src/solidlsp/`): one wrapper per server in
`src/solidlsp/language_servers/` (60+ servers: `jedi_server.py`/`basedpyright_server.py` for Python,
`gopls.py`, `clangd_language_server.py`, Eclipse JDT LS, …). `LanguageServerManager`
(`src/serena/ls_manager.py:76`) lazily starts the right server per file extension, in parallel
threads (`StartLSThread`, `ls_manager.py:118`), caches it, and restarts on demand. The LSP server
*is* the index — it parses, resolves cross-references and types with compiler accuracy, stays
incrementally fresh as files change, and needs zero embedding compute, zero index storage and zero
staleness management. The trade: a language server must exist and start (cold-start seconds), and
fuzzy/semantic "find code that does X" search is impossible — Serena compensates with
`search_for_pattern` (regex) + the model's own reading.

### Memory-file design (the second steal-worthy system)

- Storage: plain Markdown files in `<project>/.serena/memories/` (per-project) plus a global tier
  at `<serena_user_home>/memories/global/` (`config/serena_config.py:117-121`,
  `memories/memory_manager.py:30,48`). No database, no embeddings — files the user can read/edit.
- Tools (`tools/memory_tools.py`): `WriteMemoryTool:24`, `ReadMemoryTool:45`, `ListMemoriesTool:57`
  (topic filter), `DeleteMemoryTool:69`, `RenameMemoryTool:81`, `EditMemoryTool:96` (literal/regex,
  exact-once by default like the code editor).
- **Memories form a graph, not a bag:** references are written as `` `mem:auth/login` ``;
  `RenameMemoryTool` rewrites all `mem:` references on rename, and
  `memories/memory_reference_analysis.py` checks referential integrity (autofix reports).
  `resources/memory_maintenance.md` defines `mem:core` as the graph root entry point.
- **Onboarding protocol:** `OnboardingTool` (`tools/workflow_tools.py:10`) runs at most once per
  conversation and instructs the model to write a canonical starter set — named in
  `resources/config/prompt_templates/simple_tool_outputs.yml:17-21`: `mem:core` (top-level source
  map + project-wide invariants), `mem:tech_stack`, `mem:suggested_commands`. Serena's own repo
  dogfoods it: `.serena/memories/` contains `project_structure.md`, `critical_info.md`,
  `task_completion.md`, `memory_maintenance.md`, …
- Safety detail: memory names are path-validated — a name resolving outside the memories dir raises
  (`memory_manager.py:163-172`, symlink-aware by design for monorepos); read-only/ignored memory
  patterns are config-driven (`memory_manager.py:37-60`); writes are atomic
  (`util.file_system.write_file_atomic`).

**Verdict for v2:** Serena proves the *symbolic-first* stack end-to-end: overview → find_symbol →
find_referencing_symbols → replace_symbol_body, with regex search as fallback and Markdown
memories as the persistent repo-knowledge layer. None of it needs a vector DB, a GPU, or an index
build. The portable subset for a stdlib skill is in the STEAL VERDICT (§11).

---

## 2. TabbyML/tabby — self-hosted completion: Tantivy + tree-sitter + embeddings, editor-supplied context

- **Clone:** `tabby/` — HEAD `21b2904`, verified (2,099 files).
- **License (read from `tabby/LICENSE`):** **Apache-2.0** for everything outside `ee/`; `ee/` is a
  proprietary Enterprise license (`ee/LICENSE`). → borrow ideas + non-`ee` code with attribution.

### Indexing design (`crates/tabby-index/`)

- `index_repository(embedding, repository)` (`src/code/index.rs:28`): resolves default-branch
  commits (`repository::resolve_commits`), checks out each ref, walks the tree with the `ignore`
  crate (gitignore-aware), commits to the index **every 100 files**, and calls
  `add_changed_documents` per batch. A separate `garbage_collection()` (`index.rs:79`) deletes
  chunks whose source-file id (content-addressed, `intelligence.rs:58`
  `compute_source_file_id`) no longer matches — incremental freshness without a full rebuild.
- **Chunking is syntax-aware, not fixed-window:** `CodeIntelligence::chunks`
  (`src/code/intelligence.rs:165`) uses a tree-sitter `CodeSplitter` with a per-language chunk size
  (`languages::get(language).chunk_size`), falling back to a plain `TextSplitter` for unknown
  languages (`intelligence.rs:135-163`). Each chunk records its starting line number
  (`line_number_from_byte_offset`, `intelligence.rs:188`).
- **Two indexes over the same chunks:** (1) **Tantivy** (BM25) with a code-specific tokenizer
  (`crates/tabby-common/src/index/code/tokenizer.rs` — splits identifiers) and chunk fields
  `chunk_git_url / chunk_filepath / chunk_language / chunk_body / chunk_start_line`
  (`tabby-common/src/index/code/mod.rs:14-25`); queries are built as Boolean unions of token
  TermQueries with language/source filters forced to `ConstScoreQuery(…, 0.0)` so filters never
  distort ranking (`mod.rs:40-80`). (2) **Embeddings** computed at index time
  (`index_repository` takes `Arc<dyn Embedding>`) for semantic search in the Answer engine.
- **File-quality gate before indexing** (`index.rs:19-25,212`): constants
  `MAX_LINE_LENGTH_THRESHOLD=300`, `AVG_LINE_LENGTH_THRESHOLD=150`, `MIN_ALPHA_NUM_FRACTION=0.25`,
  `MAX_NUMBER_OF_LINES=100_000`, `MAX_NUMBER_FRACTION=0.5` — minified/generated/binary-ish files
  are rejected by `is_valid_file`, keeping junk out of the index.
- `find_tags` via **tree-sitter-tags** (`intelligence.rs:24`; grammars for ~15 languages pinned in
  `crates/tabby-index/Cargo.toml:14-30`) extracts definitions/references for the code browser.

### Context selection for completion (`crates/tabby/src/services/`)

The completion request carries a `Segments` struct (`completion.rs:143-176`) — the *editor*
supplies, in priority order:
1. `prefix`/`suffix` around the cursor (FIM — fill-in-the-middle; prompt template
   `<PRE> {prefix} <SUF>{suffix} <MID>`, `completion_prompt.rs:277`),
2. `declarations` — relevant declarations **provided by the editor's LSP** (`completion.rs:152`),
3. `relevant_snippets_from_changed_files` (`:156`) — chunks selected from recently *edited* files,
4. `relevant_snippets_from_recently_opened_files` (`:168`) — chunks from recently *opened* files,
   explicitly de-duplicated against (3) and excluding the current file.

Server-side, `CompletionService::build_snippets` (`completion.rs:315`) → `PromptBuilder::collect`
queries the Tantivy code search (`search_in_language`, params from
`config.code_search_params`, `tabby-common/src/config.rs:395`) using tokens from the prefix, then
`rewrite_with_snippets` (`completion_prompt.rs:100-142`) injects the winning snippets into the
prefix **as comments**, under a hard character budget (`max_snippets_chars_in_prompt`,
`completion_prompt.rs:50`). Retrieval can be switched off per-request
(`disable_retrieval_augmented_code_completion`, `completion.rs:319`).

**Pattern to note:** context is a *ranked cascade* — cursor-local (FIM) > LSP declarations >
changed files > opened files > repo-wide search — each tier budget-capped, never a single
"dump the repo" prompt. The editor, not the server, owns recency signals.

---

## 3. e2b-dev/code-interpreter — sandbox infra: the isolation lives OUTSIDE this repo

- **Clone:** `code-interpreter/` — HEAD `162a2a2`, verified.
- **License (read from `code-interpreter/LICENSE`):** **Apache-2.0**.

### What this repo actually is (important correction to the usual assumption)

Since the SDK moved to the `e2b-dev/E2B` monorepo (README note), this repo contains only the
**sandbox template** (the image that runs inside an E2B Firecracker microVM) + a chart extractor.
The isolation boundary — microVM, network, CPU/RAM limits, timeouts, kill — is E2B platform code,
*not in this repo*. What IS here is the in-VM execution server, and its design is the lesson:

- A small FastAPI server (`template/server/main.py`) talks to a **Jupyter server over a Unix
  socket** (`main.py:36`: `httpx.AsyncHTTPTransport(uds=JUPYTER_SOCKET_PATH)`, socket mode `0600`,
  `template/jupyter_server_config.py`) — the control channel never touches TCP.
- **Contexts = Jupyter kernels:** `template/server/contexts.py:38` `create_context()` creates a
  Jupyter session per (language, cwd); `cwd` defaults to `/home/user` and the Jupyter root_dir is
  pinned to `/home/user` (config comment documents a CVE-2026-35397 path-traversal hardening that
  broke session creation when root was `/`). State persists across calls *inside* a context
  (variables survive — `x=1` then `x+=1` in the README example) because it's a long-lived kernel,
  not a fresh subprocess per call.
- **Execution/interrupt discipline** (`template/server/messaging.py`): executions stream over a
  websocket with keepalives (`:261-270`); on client disconnect the server **interrupts the kernel**
  (`:401-412`, shielded `interrupt()` → `POST /api/kernels/{id}/interrupt`, `:105-122`) so an
  abandoned runaway cell can't wedge the next execution (their issue #213).
- Template definition is code (`template/template.py:6` `make_template()`): base image, env vars
  set explicitly (`.set_envs({...})`), user/workdir pinned, packages enumerated — the environment
  is a *manifest*, reproducible and diffable.

### Portable to a stdlib-only Python skill?

The microVM is not portable (and not needed on the owner's own PC — the threat model is
"agent-written code misbehaves", not "hostile multi-tenant"). Portable patterns:
(1) **persistent-kernel vs one-shot subprocess** — v2's `code_run` is one-shot; a REPL-style
long-lived worker with an explicit interrupt is the upgrade path for iterative data work;
(2) **control channel ≠ code channel** — supervise the worker over a pipe/socket the executed code
cannot see, so a hung/looping child can always be killed;
(3) **cwd + root pinning** — one canonical jail root, validated on every request (their CVE
comment is the cautionary tale);
(4) **env as explicit manifest** — the template's `.set_envs` allowlist-by-construction is exactly
v2's missing env allowlist, implementable as `env={k: os.environ[k] for k in ALLOWLIST}` in
`subprocess.Popen`.

---

---

## 4. daytonaio/daytona — dev-environment / sandbox platform (code moved private; studied last OSS tag)

- **Clone:** `daytona/` = current `main`, which is now **README + assets only** — the README states
  (verified in the clone): *"This repository is no longer maintained. As of June 2026, Daytona's core
  development has moved to a private codebase"* and points at tag `v0.190.0` as the last OSS state.
  So the real study tree is `daytona-oss/` — `git clone --depth 1 --branch v0.190.0`, HEAD `01c502b`,
  5,770 files, verified.
- **License (read from `daytona-oss/LICENSE`):** **AGPL-3.0** (`SPDX-License-Identifier: AGPL-3.0`
  headers throughout, e.g. `apps/daemon/pkg/common/env.go:2`). → ideas only, never code.

### Architecture (three planes, README + tree)

- **Interface plane:** SDKs in 6 languages (`libs/sdk-{python,typescript,ruby,go,java}`), CLI
  (`apps/cli`), dashboard — all generated from OpenAPI clients (`libs/api-client-*`,
  `libs/toolbox-api-client-*`).
- **Control plane:** `apps/api` (NestJS) — sandbox lifecycle, orgs, API keys, limits, audit logs,
  snapshots. Sandbox entity carries the policy knobs an agent platform needs:
  `networkBlockAll = false` (`apps/api/src/sandbox/entities/sandbox.entity.ts:129`),
  `networkAllowList` / `domainAllowList`; the update endpoint *requires* at least one of the three
  to be set (`apps/api/src/sandbox/controllers/sandbox.controller.ts:1116-1124`) — network policy
  is a first-class, validated object, not an afterthought.
- **Compute plane:** `apps/runner` (Go) — `Runner` struct holds a `DockerClient`
  (`apps/runner/pkg/runner/runner.go:25,36`): sandboxes are **Docker/OCI containers** (dedicated
  filesystem + network stack + allocated vCPU/RAM/disk per the README; snapshot images under
  `images/sandbox{,-slim,-gpu}`), with a v2 executor/healthcheck/poller split
  (`apps/runner/pkg/runner/v2/{executor,healthcheck,poller}`).
- **In-sandbox daemon ("toolbox"):** `apps/daemon` (Go) runs *inside* each sandbox and serves the
  agent-facing operations: process exec, filesystem, git, LSP, PTY. Notable details:
  `pkg/childreap/` — the daemon reaps zombie children (it lives as init in the container);
  `pkg/common/env.go:11-27` — env keys are validated against `^[A-Za-z_][A-Za-z0-9_]*$` before
  `ApplyEnvs` appends them to the child env; `internal/util/entrypoint_session.go` +
  `log_reader.go` stream process output; preview/SSH/VNC are separate gateways (`apps/proxy`,
  `apps/ssh-gateway`).

### Portable to stdlib Python?

The container layer is not (Windows owner PC, no Docker assumption) — and doesn't need to be: on a
single-user PC the *policy objects* are the steal, not the runtime: (1) a declarative
**network policy** (`block_all | allowlist | domain_allowlist`, exactly one required) maps to v2's
socket-neutering — today binary, tomorrow an allowlist for pip/docs fetches under tier-3 approval;
(2) **env-key validation + explicit env construction** (`env.go`) — 15 lines of stdlib, closes v2's
env-leak gap (child currently inherits everything); (3) **daemon-as-supervisor**: a long-lived
supervisor process owning the child, reaping it, streaming logs, enforcing timeout — the same
shape as E2B's kernel supervisor and the fix for orphaned `code_run` children on timeout;
(4) **snapshot = declarative image manifest** (cf. E2B template.py) → for v2, a declarative
"workspace manifest" (allowed dirs, env, timeout, network) per code session.

---

---

## 5. smallcloudai/refact — self-hosted assistant that grew BOTH an AST graph and a vecdb

- **Clone:** `refact/` — HEAD `27f86de "Update README to reflect project status changes"`, 178 MB,
  verified. README (in-clone) states this repo is now the *legacy archive*; active development moved
  to a fork — noted, the code studied is the final state of this repo.
- **License (read from `refact/LICENSE`):** **BSD-3-Clause** (Small Magellanic Cloud AI Ltd) —
  the most permissive license in this slice; code borrowable with attribution.

### Layout (post-restructure)

`refact-agent/engine` is a large Rust workspace (`crates/`: `refact-ast`, `refact-vecdb`,
`refact-knowledge-graph`, `refact-files`, `refact-postprocessing`, …) + IDE plugins
(`plugins/{vscode,intellij}`) + a GUI. Historically a completion engine; now an agent platform
with ~80 tools (`engine/src/tools/tool_*.rs`).

### The three context systems (this is the PhD point: Refact runs all three rival strategies at once)

1. **AST index (`engine/src/ast/`)** — a background indexer thread
   (`ast_indexer_thread.rs:20-60`: a todo-queue service loop with shutdown flag, per-language
   parse stats, `ast_max_files` cap) parses every workspace file with tree-sitter
   (`ast/treesitter/parsers/`, per-language parsers + tests) into an `AstDB` of symbols, then
   **`connect_usages`** (`ast/ast_db::{doc_add, doc_remove, connect_usages,
   connect_usages_look_if_full_reset_needed}`) wires definitions to usages — a code graph, kept
   incrementally fresh, with a "full reset needed" escape hatch when incremental wiring drifts.
   The **skeletonizer** (`ast/treesitter/skeletonizer.rs:192 make_formatter`,
   `file_ast_markup.rs`) renders a file as its skeleton — signatures + structure, bodies elided —
   which is Refact's version of Serena's symbols-overview / Aider's repo-map lines.
   Agent-facing: `tools/tool_ast_definition.rs` and `@definition` (below).
2. **Vector DB (`crates/refact-vecdb/`, wired at `engine/src/lib.rs:76,252`)** — `VecDb`
   (`vdb_highlev.rs:19`) with `embed_query:27`, `vecdb_search_with_embedding:63`,
   background vectorizer queue (`vectorizer_enqueue_files:182`, `remove_file:174` on delete), and a
   notable post-filter: `compute_usefulness_and_filter:43` re-scores raw cosine hits for
   *usefulness* before they reach the prompt. It "spontaneously starts" only when caps/CLI say an
   embedding model is available (`lib.rs:252` comment) — semantic search is an *optional layer*,
   not a load-bearing dependency. (Contrast Serena §1, which ships without it entirely.)
3. **@-commands — explicit, user/model-invoked context** (`engine/src/at_commands/`):
   `@file`, `@definition` (`at_ast_definition.rs`), `@search`, `@tree` (workspace tree),
   `@knowledge`, `@web` — registered in one dict (`at_commands.rs:233-269`). Context enters the
   prompt because someone *named* it, with the command's own arg-correction
   (`execute_at.rs: correct_at_arg`) — the deterministic opposite of "retrieve everything vaguely
   relevant".

### Completion-era machinery worth noting

- `completion_cache.rs` + scratchpads (`src/scratchpads/mod.rs:17-41`): FIM completions are cached
  against a cached tokenizer — latency engineering for the ghost-text path.
- `privacy.rs`, `files_blocklist.rs`, `file_filter.rs`: a **privacy/blocklist layer consulted
  before indexing or sending** — files can be excluded from AST/vecdb/LLM entirely (the
  self-hosted answer to "my code leaves the machine?").
- `memories.rs` (2,002 lines) + `knowledge/` + `knowledge_graph/`: persistent project knowledge as
  a separate subsystem from code context.

**Verdict for v2:** Refact is the control experiment against Serena's purity: same product
category, but it pays for *both* an AST graph and embeddings — and then still needs @-commands
because neither retrieval mode is trustworthy alone. Its portable steals: the **skeletonizer**
(stdlib `ast` module does this for Python — see §11), `connect_usages`-as-grep-graph, and the
pre-index **blocklist** (v2's jail should have an explicit never-read list: `.env`, keys, `.bak`).

---

---

## 6. sourcegraph/cody — context providers as an architecture (SUBSTITUTION, stated per instructions)

- **Substitution:** `sourcegraph/cody` **no longer exists as a public repo** — clone fails with
  `could not read Username` (GitHub's 404 behaviour). Cody Free/Pro were discontinued 2025-07-23 and
  development moved private. The like-for-like official substitute was cloned instead:
  **`sourcegraph/cody-public-snapshot`** (archived 2025-08-01), HEAD `8e20ac6 "chore: update commit
  for last public snapshot (#8226)"`, in `cody/`. Full clones repeatedly died on this VM's
  filesystem (`tmp_idx write error: Operation not permitted` during index-pack), so the clone is
  `--depth 1 --filter=blob:none --sparse` with sparse-checkout of the context subsystems
  (`lib/shared/src/{context,codebase-context,local-context,prompt,mentions,cody-ignore,chat}`,
  `vscode/src/{context,local-context,chat}`) — the sections below are read from that working tree.
- **License (read from `cody/LICENSE`):** **Apache-2.0**.

### Context-provider architecture — four layers, all returning one type: `ContextItem`

1. **Explicit mentions (user/model-named context).** `@`-mentions are a typed API
   (`lib/shared/src/mentions/api.ts`, `query.ts`): files, symbols, remote repos, web URLs, issues —
   each mention resolves to `ContextItem`s with `source: ContextItemSource.User`. This is the same
   determinism as Refact's @-commands (§5), productised.
2. **Automatic local search — symf.** `vscode/src/local-context/symf.ts:64` `SymfRunner` shells out
   to a downloaded **symf** binary (Sourcegraph's local code-search tool: tree-sitter-parsed,
   keyword-indexed) with `--boosted-keywords <query>` (`symf.ts:138-152,311-323`). Before querying,
   the user's natural-language question is **rewritten into keywords by a fast model**
   (`rewrite-keyword-query.ts:17-35` `rewriteKeywordQuery` — with the honest fallback: on any
   failure, use the original query; and the doc comment warns *"For some context backends,
   rewriting the query can make performance worse"*). Provider state machine is explicit:
   `LocalSearchProvider { kind:'search', type:'local', state:'unindexed'|'indexing'|'ready'|'failed' }`
   and the remote twin `RemoteSearchProvider` with `inclusion:'auto'|'manual'`
   (`lib/shared/src/codebase-context/context-status.ts:11-40`).
3. **OpenCtx — context as an external protocol.** `lib/shared/src/context/openctx/context.ts:8`
   `getContextForChatMessage()`: every configured OpenCtx provider declares **message selectors**
   (regex patterns); providers whose pattern matches the chat message are queried *in parallel*,
   each failure is swallowed to `[]`, results are filtered to items with `ai.content` and mapped
   into `ContextItemOpenCtx`. Concrete providers in `vscode/src/context/openctx/`: code search,
   git, Linear issues, web — context sources are *plugins with pattern triggers*, incl. non-code
   sources. Failure-isolation discipline: a broken provider can never break chat.
4. **Prompt assembly.** Retrieved items don't go raw into the prompt: `PromptString`
   (`lib/shared/src/prompt/prompt-string.ts`) is a type that tracks provenance (user vs codebase vs
   model output — an injection-defense type system), `PromptMixin`
   (`lib/shared/src/prompt/prompt-mixin.ts:18-50`) prepends cross-cutting preambles (incl. a
   context preamble + model-specific hedging prevention), and `truncation.ts` enforces the token
   budget by dropping context, never system text.

### Cody Ignore — the enterprise gate

`lib/shared/src/cody-ignore/context-filters-provider.ts`: server-pushed **include/exclude context
filters** per repo (`:26-27,144-145`); `isUriIgnored()` (`:216`) gates every file before it can
become context, and the default on missing filters is **exclude everything** (`:195` comment:
*"If we don't have any context filters, we exclude everything"*). Fail-closed context policy —
the exact inverse of most tools' fail-open defaults.

**Verdict for v2:** Cody's portable core is not symf (a binary dependency) but the *contracts*:
(1) one `ContextItem` type with a `source` field (user/auto/system) that survives into the prompt;
(2) provider failure isolation (`catch → []`, never crash the turn); (3) query-rewriting as an
optional, fallback-guarded step; (4) **fail-closed ignore filters** — v2's jail + never-read list
should default-deny outside `<data_dir>/code`, Cody-style.

---

---

## 7. voideditor/void — a VS Code fork: editor-native context, paginated tools, budgeted directory strings

- **Clone:** `void/` — HEAD `b3166e7`, via `--depth 1 --filter=blob:none --sparse` (full clones of
  this VS Code fork repeatedly died in index-pack on this VM; sparse checkout covers
  `src/vs/workbench/contrib/void` — the entire Void AI layer — plus root files).
- **License (read from `void/LICENSE.txt` + file headers):** **Apache-2.0** (© Glass Devtools, Inc.;
  the upstream VS Code base remains MIT under `LICENSE-VS-Code.txt`).

### Context for completion — ContextGatheringService (no index at all)

`browser/contextGatheringService.ts:34` — for autocomplete, Void gathers context *live from the
editor's own language features*, nothing is pre-indexed:
- `_gatherNearbySnippets:138` and `_gatherParentSnippets:168` — surrounding code + enclosing scopes;
- `_getSymbolsNearPosition:208` / `_getSymbolsInRange:223` — VS Code **DocumentSymbol** providers
  (i.e. the editor's LSP) for symbols near the cursor;
- `_getDefinitionSymbols:301` — jump-to-definition on those symbols to pull their bodies;
- `_findContainerFunction:328` — the enclosing function as a unit.
Prefix/suffix character caps are constants (`common/prompt/prompts.ts:34`). This is Tabby's
"editor supplies declarations" pattern (§2) taken further: the editor supplies *everything*, the
"index" is the IDE's live symbol model.

### Agent tools — pagination as a first-class contract

Void's builtin tool types (`common/toolsServiceTypes.ts:46-72`) are the cleanest tool-surface
design in this slice:
- `read_file {uri, startLine, endLine, pageNumber}` → `{fileContents, totalFileLen, totalNumLines,
  hasNextPage}` — **ranged, paged reads**, never whole-file-or-nothing;
- `ls_dir {uri, pageNumber}` → `{children, hasNextPage, hasPrevPage, itemsRemaining}`;
- `search_pathnames_only`, `search_for_files {query, isRegex, searchInFolder, pageNumber}`,
  `search_in_file {uri, query}` → matching **line numbers**;
- `edit_file {uri, searchReplaceBlocks}` — search/replace blocks (Aider-style diff blocks).
Every result tells the model whether more exists and how much — the model pages deliberately
instead of being flooded or truncated silently. Tool approval is typed per tool category
(`approvalTypeOfBuiltinToolName`, `toolsServiceTypes.ts:21`: `'edits' | 'terminal' | 'MCP tools'`)
— a tier system parallel to v2's tier-1/2/3.

### The directory string — a repo map with a hard budget

`common/directoryStrService.ts`: renders the workspace tree to a string under explicit budgets —
`MAX_FILES_TOTAL = 1000`, `MAX_DIRSTR_CHARS_TOTAL_BEGINNING / _TOOL` (from `prompt/prompts.ts`),
depth/items-per-dir start unbounded for small repos and clamp to `DEFAULT_MAX_DEPTH = 3`,
`DEFAULT_MAX_ITEMS_PER_DIR = 3` when large; hard exclusion list (`.git`, `node_modules`, any
dot-dir, `dist`, `build`, `out`, `bin`, `coverage`, `__pycache__`, `env`). The system prompt
(`common/prompt/prompts.ts:434-502`) frames the contract: user-selected files arrive as
`SELECTIONS`, the model is told it may ask for @-referenced files, and in Gather mode it *must*
gather before editing.

**Verdict for v2:** Void is the strongest evidence for two cheap v2 upgrades: **paginated ranged
`code_read`** (startLine/endLine + hasNextPage metadata — kills the whole-file gap without any
index) and a **budgeted `code_list`** (directory string with file cap + exclusion list + depth
clamping). Both are pure stdlib; both are exactly v2's named gaps.

---

---

## 8. Aider-AI/aider — the discovered 10th repo: the canonical "repo map" (tree-sitter tags + PageRank)

- **Discovery:** via the assigned terms — "repo map" is Aider's own name for this system
  (aider.chat/docs/repomap.html); it is the reference implementation every later "codebase context
  engine" (ast-grep outline, Graphify, repocontext…) reacts to. Cloned as `aider/`, HEAD `5dc9490`,
  verified.
- **License (read from `aider/LICENSE.txt`):** **Apache-2.0**.

### The mechanism (`aider/repomap.py`, 867 lines — one file, no server, no embeddings)

1. **Tag extraction** (`get_tags_raw:279`): each file is parsed with **tree-sitter**; a
   per-language query file (`tags.scm`, shipped per grammar) captures `def` and `ref` tags —
   definitions (classes/functions with their signature lines) and references (identifier uses).
   Unknown language or missing query → file silently contributes nothing.
2. **Cache** (`get_tags:233`, `TAGS_CACHE_DIR = ".aider.tags.cache.v4"` at `:43`): tags are stored
   in an on-disk sqlite/diskcache keyed by filename, invalidated by **mtime** — re-parse only what
   changed. (Same freshness trick as Tabby's content-id GC and Refact's AstDB, at 1% of the code.)
3. **Graph + ranking** (`get_ranked_tags:365`): builds a `networkx.MultiDiGraph` where an edge
   *referencer → definer* is created per identifier, weighted by `sqrt(num_refs) × mul`, with
   hand-tuned multipliers (`:487-530`): ident mentioned in the user's message ×10; long
   snake_case/kebab-case/CamelCase idents (≥8 chars — the "meaningful names") ×10; `_private`
   idents ×0.1; idents defined in >5 files ×0.1 (utility noise); references *from a file currently
   in chat* ×50; unreferenced definitions get a 0.1 self-edge so they don't vanish.
4. **Personalized PageRank** (`nx.pagerank(G, weight="weight", personalization=…, dangling=…)`):
   the personalization vector is seeded from files in chat, files mentioned by name, and files
   whose *path components* match mentioned identifiers (`:405-440`, seed = `100/len(fnames)`).
   Rank is then redistributed from each file across its out-edges to individual
   `(file, ident)` definitions (`:540-560`) — ranking **symbols**, not just files.
5. **Rendering under a token budget** (`get_repo_map:103`, `get_ranked_tags_map:576`,
   `to_tree:748`): default budget `map_tokens=1024` (×8 when no files are in chat,
   `map_mul_no_files=8`); the tree renderer emits, per file, the ranked definition lines verbatim
   with `⋮...` elisions, expanding/contracting to fit the budget; already-in-chat files are
   excluded (their content is already in context). Token counting itself is sampled
   (`token_count`: count 1-in-N lines and scale) to stay fast on huge maps.

**Why this matters for the slice:** Aider is the *minimum viable repo map* — ~900 lines, no index
server, no embeddings, no LSP — and it was strong enough to define the genre. Its weaknesses are
equally instructive: tree-sitter tags are syntactic (a `ref` is a name match, not a resolved
binding — Serena/LSP is the accurate version), PageRank needs the whole graph in memory, and the
map is only as fresh as the mtime cache.

**Stdlib portability (directly relevant to v2):** Python's stdlib `ast` module gives def/ref tags
for Python files with *better* fidelity than tree-sitter queries (real scopes); PageRank is ~25
lines of power iteration — `networkx` is not required. A v2 `code_map` tool is therefore
implementable in pure stdlib for Python repos, degrading to regex tags for other languages.

---

---

## 9. BloopAI/bloop — code search with THREE indexes (ORG-NAME CORRECTION, stated per instructions)

- **Correction:** the assigned `bloop-ai/bloop` **404s** (git: `could not read Username`). The real
  org is capitalised **`BloopAI/bloop`** — cloned as `bloop-ai/`, HEAD `431e9e8`, verified. The repo
  is the final state of the (now pivoted-away) Bloop company: a Tauri desktop app (`apps/desktop`)
  + Rust server (`server/bleep`) + web client. 
- **License (read from `bloop-ai/LICENSE`):** **Apache-2.0**.

### Index construction — three independent retrieval systems over one repo walk

1. **Exact/regex search — Tantivy trigram index** (`server/bleep/src/indexes/doc.rs`): the schema
   registers a custom `"trigram"` tokenizer (`NgramTokenizer::new(1, 3, false)`, `doc.rs:141`);
   queries compile each term into trigram Boolean unions over body and header fields
   (`doc.rs:651-674`). Trigrams make *regex* search index-accelerated instead of a full scan —
   the same trick as Google's codesearch/zoekt. (This is the piece Tabby's token-BM25 doesn't do.)
2. **Semantic search — local embeddings + Qdrant** (`src/semantic/`): chunks are produced by
   `chunk.rs` (byte/line `Point`-addressed chunks with a configurable `OverlapStrategy` —
   by-lines or by-token-percentage, `chunk.rs:74-161`, plus an `is_noisy` chunk filter), embedded
   by an **ONNX Runtime** embedder (`embedder.rs:63-115`: `ort::Session` loading `model/model.onnx`
   — a ~23 MB MiniLM-class model shipped in-repo under `model/`, git-LFS pointers verified) and
   stored in **Qdrant** (`semantic.rs:6-8,188-212`: collection created on first run, payload =
   repo/file/range metadata, `semantic/schema.rs`). Embeddings never leave the machine at index
   time — the privacy property Bloop marketed.
3. **Precise navigation — tree-sitter scope resolution** (`src/intelligence/`): grammars for ~12
   languages (`server/bleep/Cargo.toml:62-74`); `intelligence/scope_resolution/` + `namespace.rs` +
   `code_navigation.rs` implement go-to-definition/references by *scope resolution* (lexical
   scopes, not name matching) — a home-grown, approximate LSP, built because in 2023 embedding
   search couldn't do navigation and real LSPs were hard to embed.

Above the indexes sits a **query planner** (`src/query/planner/optimize.rs`) and an LLM answer
layer (`src/agent/`, `src/llm/`): the user's follow-up question is first rewritten by the LLM into
a standalone query (the HN launch post's "query parsing logic → pest" example is this pipeline),
then retrieval, then answer-with-snippets.

**Verdict for v2:** Bloop is the maximalist fossil: trigram + vectors + scope-resolution + LLM
planner in one Rust binary — and the company still died, while Serena (LSP only) and Aider
(tags+PageRank only) thrive. Lesson in maintenance surface: every index is a subsystem that can
rot. The one piece with no equivalent elsewhere in this slice is the **trigram-accelerated regex**
— and even that has a stdlib echo: an n-gram prefilter over file contents before running `re`
(see §11).

---

## 10. microsoft/CodeBERT — the pre-LLM baseline (what embeddings-for-code looked like before agents)

- **Clone:** `CodeBERT/` — HEAD `c0de43d`, verified. The repo is now a *series* repo (README:1-8):
  CodeBERT (EMNLP 2020), GraphCodeBERT (ICLR 2021), UniXcoder (ACL 2022), CodeReviewer (2022),
  CodeExecutor (2023), LongCoder (ICML 2023).
- **License (read from `CodeBERT/LICENSE`):** **MIT**.

### What it is

A **RoBERTa-base encoder** (~125 M params, 768-dim outputs — README quick-tour) pre-trained on
**CodeSearchNet NL–PL pairs in 6 languages** (Python, Java, JavaScript, PHP, Ruby, Go; README:14)
with two objectives: masked language modelling (MLM) on bimodal NL+PL sequences and replaced-token
detection (RTD). Input format is a single concatenated sequence
`[CLS] NL tokens [SEP] PL tokens [EOS]` (README example, token ids shown). There is **no
generation**: every downstream use is a fine-tune — code search becomes
`RobertaForSequenceClassification` over (query, candidate) pairs, scored and ranked by MRR
(`CodeBERT/codesearch/run_classifier.py:42,345+`, `mrr.py`); code2nl, clone detection, translation
and refinement each have their own fine-tuning harness (`CodeBERT/code2nl/`,
`GraphCodeBERT/{clonedetection,translation,refinement}/`).

### Strengths (why it was the baseline for years)

- **One embedding space for NL and PL** — "return maximum value" and `def max(a,b): …` land near
  each other; this is the direct ancestor of every embedding index in this slice (Tabby §2,
  Bloop §9, Refact §5 all embed code with descendants of this idea; Bloop's MiniLM is the same
  encoder family, distilled).
- **Cheap inference, deterministic, local** — 125 M params runs on modest GPUs/CPU; on the owner's
  RTX 2060 it would be trivial. Embeddings are stable across runs (unlike LLM retrieval).
- GraphCodeBERT's fix is in-repo: add the **data-flow graph** (variables + where they come from,
  extracted by `GraphCodeBERT/codesearch/parser/DFG.py`, `data_flow_length 64` in its README
  commands) as structure-aware input — an early admission that token sequences alone miss semantics.

### Limits (why no agent in this slice uses it as the retriever anymore)

- **512-token window** (RoBERTa positional limit) — a file rarely fits; chunking destroys exactly
  the cross-references retrieval needs (the problem Serena's LSP and Aider's graph don't have).
- **Encoder-only + fine-tune-per-task**: the base model does nothing useful zero-shot; each task
  needs labelled data + training. An agent skill cannot "just call" it.
- Embeddings are **fuzzy by construction**: two functions with similar tokens but different
  behaviour are neighbours; there is no exactness story (no "find THE definition"), which is why
  every surviving system pairs embeddings with an exact channel (BM25/trigram/LSP) or drops them.
- The repo's own sequel models confess the trajectory: UniXcoder (unified cross-modal), LongCoder
  (long windows) — by 2023 the field was already patching CodeBERT's limits, and decoder LLMs with
  tool use then replaced the fine-tune paradigm entirely.

**Verdict for v2:** historical baseline only — **do not adopt**. If v2 ever wants a local semantic
channel, the modern descendant (a small ONNX embedding model à la Bloop §9, run under Ollama on
the 2060) dominates CodeBERT on every axis; and §11 argues v2 doesn't need one yet.

---

## 11. STEAL VERDICT — for JARVIS v2 `skills/code` (Python 3.11+ stdlib only, Windows, RTX 2060)

### The slice's central finding

Four independent lineages converge on the same architecture, and it is **not** "embed everything":
**Serena** (LSP symbols, no vectors) · **Aider** (tree-sitter tags + PageRank, no vectors) ·
**Void** (editor's live symbol model, no index) · **Cody** (keyword symf + mentions, embeddings
removed in its final versions) — versus the two systems that *did* build vector indexes
(**Bloop**: dead; **Refact**: keeps vecdb as an optional layer beside its AST graph). Exact,
structural, fresh-by-construction retrieval beat fuzzy retrieval wherever both were tried.
v2's stdlib constraint, which looks like a handicap, actually forces the winning design.

### Top steals (ranked by gap-closed per line of stdlib code)

**STEAL 1 — `code_map`: Aider's repo map, stdlib port (closes: no repo map).**
`ast.parse` per Python file → def tags (class/function, signature line, lineno) + ref tags
(`ast.Name`/`ast.Attribute` ids); non-Python files fall back to a regex def-scan. Build the
referencer→definer graph, weight edges exactly as Aider does (`repomap.py:487-530`: sqrt(refs),
×10 mentioned/long idents, ×0.1 private/over-defined, ×50 from open files), run ~25 lines of
personalized PageRank power-iteration (no networkx needed), render a budgeted tree
(`to_tree`-style, default ~1024 tokens, ×8 when no file is open). Cache tags in sqlite3 (stdlib!)
keyed by path+mtime — `.v2.tags.cache` beside the jail. ~250 lines total.

**STEAL 2 — Ranged, paginated reads + budgeted listing: Void's tool contract (closes: whole-file
reads, no `code_list`).**
Change `code_read` to `{path, start_line, end_line, page}` → `{content, total_lines, has_next_page}`
(`toolsServiceTypes.ts:46-72`) and add `code_list` = Void's directory string
(`directoryStrService.ts`: MAX_FILES_TOTAL cap, depth/items clamping under a char budget,
hard exclusions `.git/__pycache__/dist/build/node_modules` + v2's own never-read list). Add
Serena's `max_answer_chars` discipline: every code tool takes a budget and *shortens
structurally* (drop bodies, keep signatures) instead of truncating mid-file.

**STEAL 3 — Symbol tools without an LSP: Serena's API shape over stdlib `ast` (closes: no
symbol-level retrieval).**
Expose `code_overview` (Serena `get_symbols_overview`), `code_find_symbol` (name-path patterns
`Class/method`, substring mode, include_body flag) and `code_find_references` (AST name-resolution
for Python; regex+word-boundary fallback for other languages, labelled as approximate — Bloop's
scope-resolution lesson is that honest approximation beats confident name-matching). Edits gain
`code_replace_symbol_body` (Serena `symbol_tools.py:352`): replace exactly the AST node's line
span — strictly safer than v2's current exact-once text match for refactors, and it composes with
the existing `.bak` undo. The real LSP path stays open as a *future tier-2 subprocess* (a
`jedi`/`pyright` server is just a subprocess + JSON-RPC — Serena's SolidLSP is MIT if ever needed).

**STEAL 4 — `code_search`: Serena/Cody-grade regex search (closes: no grep tool).**
Serena's `search_for_pattern` (`file_tools.py:315`) as the spec: regex, include/exclude globs,
gitignore-aware skip, context lines, results as file→(line numbers + lines), budget-capped; plus
Bloop's trigram prefilter as a pure-Python optimisation only if profiling demands it, and Cody's
**fail-closed** rule (§6): paths outside the jail are not "searched and filtered" — they are
unsearchable, and the never-read blocklist (Refact's `files_blocklist`, §5) applies to search
results too (a grep that returns the line containing a secret is a leak).

**STEAL 5 — Sandbox hardening pack: E2B + Daytona policy objects, stdlib edition (closes: no
OS-level confinement story, no env allowlist).**
(a) **Env allowlist-by-construction** (E2B `template.py` `.set_envs`, Daytona `env.go:11-27`):
`code_run` builds `env=` from an explicit allowlist (`PATH, SystemRoot, TEMP, LANG` + skill vars),
validating keys against `^[A-Za-z_][A-Za-z0-9_]*$` — today the child inherits the whole environment
including any API keys in it. (b) **Supervisor pattern** (E2B `messaging.py:401-412`, Daytona
daemon/childreap): spawn via a supervisor that owns the child process *tree* (Windows:
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` via ctypes — stdlib — so timeout kills grandchildren too,
the Windows equivalent of child-reaping), streams output, and always interrupts on caller
disconnect. (c) **Network policy as data** (Daytona `sandbox.entity.ts:129` +
controller `:1116`): replace the binary socket-neutering with a policy object
`{mode: block_all|allowlist, hosts: [...]}` recorded in the audit log per run; `block_all` stays
the default. (d) **Session manifest** (E2B contexts + Daytona snapshots): a per-session JSON
manifest (cwd jail, env, network policy, timeout) written before execution = v2's audit hook,
diffable and replayable. Honest limit, stated: on Windows without containers, none of this is a
security boundary against *malicious* code — it is a blast-radius reducer for *misbehaving* code,
which is v2's actual threat model; real isolation would be Windows Sandbox/WSL2 as a future tier.

### Explicit non-steals

- **No vector DB / embeddings yet** (against Tabby/Bloop/Refact's vecdb): every gap v2 actually
  has is closed by Steals 1–4; embeddings would add an index to keep fresh, a model to host, and
  fuzzy results the tier system can't audit. Revisit only if `code_search` telemetry shows
  "didn't know the name" failures dominating — and then Bloop's local-ONNX shape (§9), not a
  service.
- **No CodeBERT-lineage model** (§10): fine-tune-per-task is a dead paradigm for a tool-using agent.
- **No container/microVM runtime** (E2B/Daytona cores): AGPL (Daytona) + Windows/no-Docker
  reality; their *policy objects* port, their runtimes don't.
- **No GPL code** from Serena's app layer (SolidLSP's MIT parts are the borrowable exception).

### License summary (all read from cloned LICENSE files)

| Repo | License | Borrow code? |
|---|---|---|
| oraios/serena | GPL-3.0-or-later (app) / MIT (SolidLSP) | SolidLSP only |
| TabbyML/tabby | Apache-2.0 (ee/ proprietary) | Yes, outside ee/ |
| smallcloudai/refact | BSD-3-Clause | Yes |
| voideditor/void | Apache-2.0 (VS Code base MIT) | Yes |
| sourcegraph/cody-public-snapshot | Apache-2.0 | Yes |
| e2b-dev/code-interpreter | Apache-2.0 | Yes |
| daytonaio/daytona @v0.190.0 | AGPL-3.0 | **No — ideas only** |
| BloopAI/bloop | Apache-2.0 | Yes |
| microsoft/CodeBERT | MIT | Yes (not recommended) |
| Aider-AI/aider | Apache-2.0 | Yes |

### Clone ledger (verification, per instructions)

Cloned into `~/workspace/jarvis-knowledge/megascan/.work28/sliceD/` and verified by `ls` +
`git log`: serena `dc60fba` · tabby `21b2904` · refact `27f86de` · void `b3166e7` (sparse,
blobless) · cody `8e20ac6` (sparse, blobless — substitute repo, see §6) · code-interpreter
`162a2a2` · daytona `ec4c21b` (README-only main) + daytona-oss `01c502b` (tag v0.190.0) ·
aider `5dc9490` · CodeBERT `c0de43d` · bloop-ai `431e9e8` (correct org BloopAI, see §9).
Full clones of the largest repos repeatedly failed on this VM with
`tmp_idx write error: Operation not permitted` under ~30-team clone contention; sparse/blobless
clones were the documented fallback for void/cody and cover every file cited for those repos.
