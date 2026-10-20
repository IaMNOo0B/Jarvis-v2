# MEGA-SCAN TEAM 11 (RE-RUN) — MCP Servers & Plugin Ecosystems, reverse-engineered

> Supersedes the earlier partial in this file (3 lines per instructions): the first
> attempt hard-stopped on GitHub API 429 after triage only, with zero code reads.
> This re-run used `git clone --depth 1` + local reads (git protocol, no API quota)
> and contains code-level evidence throughout. Clones live in `megascan/.work11/`.
> Date: 2026-10-20.

## Coverage (honest)

**24 repos code-read** (deep reads marked ●, light reads ○):
modelcontextprotocol/servers ● (monorepo — 7 published servers inside, each read:
everything, filesystem, memory, sequentialthinking, fetch, git, time),
modelcontextprotocol/registry ●, modelcontextprotocol/python-sdk ●,
modelcontextprotocol/typescript-sdk ●, jlowin/fastmcp ●, stacklok/toolhive ●,
ArcadeAI/arcade-mcp ●, universal-tool-calling-protocol/code-mode ●,
containers/kubernetes-mcp-server ●, dcSpark/mcp-dockmaster ●, hangwin/mcp-chrome ●,
benborla/mcp-server-mysql ●, microsoft/playwright-mcp ○ (repo is a packaging shell;
evidence = its shipped `server.json` + full README tool surface — implementation lives
in the playwright monorepo), executeautomation/mcp-playwright ○,
duty1g/x64dbg-mcp-server ●, theronic/modex ○, Oaklight/ToolRegistry ●,
shinzo-labs/shinzo-ts ○, ahmedeltaher/azan-mcp ○, Chen-speculation/auto-MCP-client ○,
GongRzhe/Office-Word-MCP-Server ○, zcaceres/markdownify-mcp ○.
Counting the monorepo's 7 servers individually: **30 server codebases**.
**Partial:** upstash/context7 (tree/metadata only — checkout raced a background clone;
packages layout + MIT license + `context7.json` verified via `git show`, src not read).
**Attempted, NOT read:** brightdata/brightdata-mcp (clone corrupted twice by two
background batches racing the same path — fetch-pack index errors), DeusData/
codebase-memory-mcp (clone incomplete at write time), headroomlabs-ai/headroom,
nanbingxyz/5ire, zylon-ai/private-gpt (clones still in flight — network was very slow),
Pimzino/spec-workflow-mcp (fetch-pack disconnect).

---

## PART 1 — TIER A: protocol, manifest, SDKs

### 1. modelcontextprotocol/registry — the `server.json` manifest (THE interchange format)
Evidence: `registry/internal/validators/schemas/` holds versioned JSON Schemas
(2025-07-09 → **2025-12-11**); the schema is generated from
`docs/reference/api/openapi.yaml` ("auto-generated, do not edit").
`definitions.ServerDetail` fields: `$schema, _meta, name, title, description, version,
repository{url, source, subfolder}, websiteUrl, icons[], packages[], remotes[]`.
`definitions.Package`: `registryType (npm/pypi/nuget/mcpb/oci), identifier, version,
registryBaseUrl, fileSha256, runtimeHint, transport, runtimeArguments[],
packageArguments[], environmentVariables[]`.
Transports are typed objects: `StdioTransport | SseTransport | StreamableHttpTransport | LocalTransport`.
`definitions.Input` carries the secrets model: `isSecret: true` ("clients should handle
the value securely"), `isRequired`, `format ∈ string|number|boolean|filepath`,
`choices[]`, `default`, and `{curly_brace}` variable substitution in `value`.
**Security is written INTO the schema**: the `Argument` definition's description warns
that arguments "may contain user-provided input… a malicious argument value like
';rm -rf ~/Development' could execute dangerous commands. Clients should prefer
non-shell execution methods (e.g., posix_spawn)… obtain consent from users."
Pattern verdict: a manifest that (a) is `$schema`-pinned to a dated version,
(b) separates the *package* (how to obtain) from the *remote* (where it runs),
(c) declares secrets as named inputs, never values, (d) documents its own injection
risk. License: LICENSE file present, not read in this pass — verify before reuse.

### 2. microsoft/playwright-mcp `server.json` — the format in the wild (real example, read in full)
```json
{ "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
  "name": "io.github.microsoft/playwright-mcp",
  "description": "Playwright Tools for MCP",
  "repository": {"url": "https://github.com/microsoft/playwright-mcp", "source": "github"},
  "version": "0.0.83",
  "packages": [{"registryType": "npm", "identifier": "@playwright/mcp",
                "version": "0.0.83", "transport": {"type": "stdio"}}] }
```
Names are **reverse-DNS** (`io.github.microsoft/…`) — collision-proof without a
central allocator. A real server.json is ~20 lines: identity + provenance + how to run.

### 3. modelcontextprotocol/python-sdk — transports & the governed error space
Transports (`src/mcp/client/`): `stdio.py`, `sse.py`, `streamable_http.py`
(`StreamableHTTPTransport`, session via `mcp-session-id` header), plus `auth/oauth2.py`
+ `auth/utils.py` implementing the full OAuth dance from the wire up:
`extract_resource_metadata_from_www_auth()` parses the `WWW-Authenticate` header,
`build_protected_resource_metadata_discovery_urls()` builds RFC 9728 discovery URLs.
Errors (`src/mcp-types/mcp_types/jsonrpc.py`, read in full): standard JSON-RPC codes
(PARSE_ERROR −32700, INVALID_REQUEST −32600, METHOD_NOT_FOUND −32601,
INVALID_PARAMS −32602, INTERNAL_ERROR −32603) + an MCP band **−32000..−32099** with an
allocation policy in comments: −32000..−32019 implementation-defined, −32020.. spec-
defined (HEADER_MISMATCH −32020, MISSING_REQUIRED_CLIENT_CAPABILITY −32021,
UNSUPPORTED_PROTOCOL_VERSION −32022), −32042 URL_ELICITATION_REQUIRED (retired-band,
never reused); SDK-private codes CONNECTION_CLOSED −32000, REQUEST_TIMEOUT −32001 are
"never emitted on the wire". Envelope: `ErrorData{code:int, message:str (one
sentence), data:Any}`.
**The single most important convention** (`_types.py:1463`, `CallToolResult` docstring,
verbatim): *"Errors that originate from the tool SHOULD be reported inside the result
with `is_error` set to true, not as an MCP protocol-level error, so the LLM can see
and self-correct. Errors in finding the tool… should be reported as an MCP error
response."* Result shape: `content[] + structured_content + is_error + result_type`.
Tool metadata (`_types.py:1365` `ToolAnnotations`): four orthogonal advisory hints —
`readOnlyHint, destructiveHint, idempotentHint, openWorldHint`. License: not read in
this pass (verify before reuse).

### 4. modelcontextprotocol/typescript-sdk — safe stdio spawning (a named mechanism)
`packages/client/src/client/stdio.ts:54` `DEFAULT_INHERITED_ENV_VARS` and `:82`
`getDefaultEnvironment()`: a spawned server inherits ONLY an allowlist — POSIX:
`HOME, LOGNAME, PATH, SHELL, TERM, USER` ("list inspired by the default env
inheritance of sudo"); Windows gets a longer fixed list. Values starting with `()`
(shell function definitions) are **explicitly skipped as a security risk**. The
ecosystem's default is *deny-by-default environment*, i.e. a spawned skill does NOT
inherit the host's API keys unless the manifest asks for them by name.

### 5. modelcontextprotocol/servers — the reference servers (monorepo, MIT→Apache-2.0 transition per root LICENSE)
- **filesystem** (TS, ~2,158 LOC): 19 tools registered in `server.ts` via
  `server.registerTool` — and registration itself is wrapped: a decorator injects a
  startup "barrier" + era check; in the modern (2026-07-28, no-initialize) era, a
  session with zero allowed directories makes EVERY call return
  `{content:[{type:"text", text: NO_ALLOWED_DIRECTORIES_MODERN_ERROR}], isError:true}`
  — fail-closed, in-band (§3's convention in production). Path safety is a separate
  pure module: `path-validation.ts:11 isPathWithinAllowedDirectories()` — rejects
  null bytes, `path.resolve(path.normalize())`, separator-aware prefix check;
  allowed dirs come from argv OR the client's **roots** (`roots-utils.ts`).
- **memory**: knowledge-graph server; storage is one JSONL file (`memory.jsonl`,
  path from `MEMORY_FILE_PATH` env, `~` expanded in code because "no shell performs
  tilde expansion"; auto-migrates legacy `memory.json`). Tools: `create_entities,
  create_relations, add_observations, delete_entities, delete_observations,
  delete_relations, search_nodes, open_nodes, read_graph` — graph ops as flat verbs
  over append-only JSONL (directly comparable to JARVIS's episodic/semantic store;
  JARVIS's FTS5+provenance is richer, the JSONL audit trail is simpler).
- **sequentialthinking**: one file, 229 LOC — a single tool whose input schema IS the
  product (`thought, nextThoughtNeeded, thoughtNumber, totalThoughts, isRevision,
  revisesThought, branchFromThought, branchId`) — proof that a "skill" can be pure
  structured-state bookkeeping with no I/O.
- **everything**: the conformance kitchen sink — 25 tool modules (`tools/`) incl.
  `trigger-sampling-request` (server→client `sampling/createMessage`),
  `trigger-elicitation-request` (+ async, multi-step, and URL-mode variants),
  `trigger-long-running-operation`, resource templates/subscriptions, roots listing.
  This is the de-facto feature checklist for any host: sampling, elicitation,
  roots, list-changed notifications, progress.
- **fetch / git / time**: small single-purpose servers; git wraps local repos with
  the same allowed-roots discipline as filesystem.

### 6. jlowin/fastmcp (Apache-2.0) — the framework that ate the SDK's lunch
Current layout: `fastmcp_slim/fastmcp/` (the repo also ships `fastmcp_remote`,
`fastmcp_tasks`). Core: `server/server.py:312 class FastMCP`, `:1803 add_tool()`,
`:1818 tool()` (decorator, overloads), `:1980 resource()`, `:2111 prompt()` —
functions become tools with schemas inferred from type hints (the DX lesson:
hand-writing JSON Schema is why people adopt FastMCP over the raw SDK).
Two subsystems matter for JARVIS:
- **Middleware as a first-class stack** (`server/middleware/`): `authorization.py,
  caching.py, dereference.py, error_handling.py, logging.py, ping.py,
  rate_limiting.py, response_limiting.py, timing.py, tool_injection.py` — cross-
  cutting policy (incl. output-size limiting and timing) is composable middleware,
  not handler code.
- **Auth breadth** (`server/auth/`): `oauth_proxy/`, `oidc_proxy.py`, `cimd.py`
  (Client ID Metadata Documents), `jwt_issuer.py`, `identity_assertion.py`,
  `ssrf.py`, `redirect_validation.py` — HTTP servers are expected to be OAuth
  resource servers; SSRF/redirect validation ship in the framework, not the app.
Also an `examples/code_mode/` — FastMCP itself demos the code-execution pattern (§8).

---

## PART 2 — TIER B: frameworks, gateways, managers

### 7. stacklok/toolhive (Apache-2.0, Go) — the enterprise quarantine
ToolHive runs MCP servers **in containers** behind a local reverse proxy:
`pkg/container/` (workload runner), `pkg/runner/` (config builder + proxy),
`pkg/auth/` (OAuth providers incl. GitHub, DCR — dynamic client registration,
discovery), `pkg/authserver/` (it can BE the authorization server),
`pkg/authz/` (per-tool authorization policy), and `pkg/audit/` (`auditor.go`,
`mcp_events.go`, `middleware.go`) which records **every MCP call as a structured
audit event**. This is JARVIS's "quarantine until approve + gate + session log"
instinct, industrialized: untrusted server code never shares the host process,
credentials are injected by the proxy (the server never sees raw tokens), and the
audit trail is a separate subsystem with its own config. Steal-shape: the audit
event schema and credential-injection-by-proxy, not the container runtime.

### 8. ArcadeAI/arcade-mcp (MIT) — per-tool declared dependencies (best manifest idea in the scan)
`libs/arcade-tdk/arcade_tdk/tool.py:134` — the decorator is the manifest:
```python
@tool(requires_auth: ToolAuthorization | None = None,
      requires_secrets: list[str] | None = None,     # names only
      requires_metadata: list[str] | None = None,
      adapters: list[ErrorAdapter] | None = None,    # error normalization chain
      metadata: ToolMetadata | None = None,
      ui: ResourceDeclaration | None = None)
```
The decorator stamps `__tool_requires_auth__ / __tool_requires_secrets__ /
__tool_requires_metadata__` onto the function and wraps it so **every exception is
normalized through an adapter chain** into one error shape (`_raise_as_arcade_error`)
— handlers can't leak stack traces or provider-specific error dialects. Auth is
per-tool OAuth (`arcade_core/auth.py`, `auth_tokens.py`): the runtime, not the tool,
brokers user tokens. Repo layout is a libs monorepo (`arcade-core, arcade-tdk,
arcade-mcp-server, arcade-serve, arcade-cli, arcade-evals` — note: a dedicated
**evals** lib; tool quality is tested like code).

### 9. universal-tool-calling-protocol/code-mode (MPL-2.0) — one tool to rule the registry
Thesis (README, verbatim): "LLMs excel at writing code but struggle with tool calls.
Instead of exposing hundreds of tools directly, give them ONE tool that executes
TypeScript code with all registered tools available as native TypeScript functions."
`code-mode-mcp/index.ts` (396 LOC) exposes a single `execute` tool
(`{code, timeout=30000}` → `client.callToolChain(code, timeout)` returning
`{result, logs}`): the model composes/chains/filters tool calls **in code**, data is
processed in-sandbox ("no token overhead") instead of round-tripping through the
context window. MPL-2.0 = file-level copyleft; pattern is free to re-implement.

### 10. containers/kubernetes-mcp-server (Apache-2.0, Go) — annotation-driven confirmation policy ★
The most JARVIS-shaped code in the scan. `pkg/confirmation/confirmation.go:21
CheckToolRules(ctx, rules []config.ConfirmationRule, fallback string, elicitor
api.Elicitor, …)` + `match.go:14 MatchToolLevelRules(rules, toolName,
destructiveHint *bool)`: operator-written **confirmation rules** are matched against
the tool's MCP `destructiveHint` annotation (and, at `:42 MatchKubeLevelRules`,
against the actual k8s verb/kind/name/namespace of the call). On a match the server
pauses and asks the user via **MCP elicitation**; `:75 isElicitationNotSupported()`
detects clients that can't elicit and applies a configurable `fallback` (message /
deny). Tools are grouped into switchable **toolsets** (`pkg/api/toolsets.go`).
Translation for JARVIS: approval policy = data (rules) × manifest annotation
(destructive) × live argument inspection — with an explicit degraded-mode behavior
when the surface can't ask. v2's gate does the first two; the fallback semantics
and argument-level matching are the upgrade.

### 11. dcSpark/mcp-dockmaster (MIT, Rust/Tauri) — manager + transparent proxy + host-config injection
Three apps: a Tauri desktop manager, `apps/mcp-proxy-server/` (a Rust rmcp service
that connects to a child server as a client — `mcp_proxy_client.rs:get_mcp_client` —
and re-serves it: `mcp_proxy_server.rs` implements the full surface `list_tools,
call_tool, list_resources, read_resource, subscribe, get_prompt…` as pass-through),
and `libs/mcp-core/src/mcp_installers/` (`install_claude.rs`, `install_cursor.rs`) —
the manager **writes other hosts' config files** to register servers into them.
Pattern: install/manage UX is a separate product from the servers; a proxy shim can
front any stdio server unchanged (where ToolHive-style policy could later attach).

### 12. Oaklight/ToolRegistry (MIT, Python) — one registry, every dialect
`src/toolregistry/tool_registry.py:86 class ToolRegistry`: aggregates tools from
MCP servers, OpenAPI specs, LangChain tools and native functions into one namespace
and re-emits them in each consumer's dialect (examples: `openai_*`, `providers/`,
`mcp_related/`, `openapi_related/`, `langchain_related/`). Internals worth noting:
sub-registries (`_sub_registries`), hot discovery with change events
(`enable_tool_discovery()` + `_on_registry_change(ChangeEvent)` at :266/:313),
execution backends per tool (`_backend_for()` :385), uniform `_ToolError` (:59).
This is the adapter layer a multi-dialect world needs: register once, expose anywhere.

---

## PART 3 — TIER C: real servers, interesting shapes

### 13. microsoft/playwright-mcp (Apache-2.0) — accessibility-tree-first browsing
~30 `browser_*` tools (`browser_snapshot, browser_click, browser_find,
browser_fill_form, browser_evaluate, browser_console_messages…`). Doctrine (README:3):
interact "through structured accessibility snapshots, bypassing the need for
screenshots or visually-tuned models" — elements are addressed by **refs** from the
a11y snapshot; `browser_find` searches the snapshot and returns nodes "under its path
from the root of the tree" instead of re-sending the whole tree. This is JARVIS's
UIA-first/vision-last doctrine on the web, with the token economics to prove it.
Ships the §2 server.json. (Implementation lives in the playwright monorepo; this
repo is packaging + docs.)

### 14. executeautomation/mcp-playwright (MIT) — the community variant
Monolithic `src/index.ts` + `src/http-server.ts`, with `src/rate-limiting/`,
`src/monitoring/`, `src/logging/` directories — a single-maintainer server that
grew the operational scaffolding (rate limiting, monitoring) the official one
doesn't expose. Contrast: same protocol, wildly different engineering depth.

### 14b. hangwin/mcp-chrome (MIT) — the browser-bridge transport
Two halves: a Chrome extension (`app/chrome-extension/`) and a **native messaging
host** (`app/native-server/`, `src/native-messaging-host.ts`) that Chrome launches
over stdio native messaging; the host runs an HTTP MCP server on a fixed localhost
port (`src/constant/index.ts:11 NATIVE_SERVER_PORT = 12306`) which AI clients
connect to. The capabilities live in the page context (the user's logged-in browser)
— power and risk in one shape: whoever can reach `localhost:12306` inherits the
user's authenticated web sessions (ambient authority; no token check was found in
the constant/config layer). The bridge pattern itself (extension ↔ native host ↔
MCP) is the only clean way to automate a real browser profile.

### 15. benborla/mcp-server-mysql (MIT) — capability flags + output sanitization
`src/config/index.ts:69-83`: every write class is a separate env boolean, all
**default-false** — `ALLOW_INSERT_OPERATION, ALLOW_UPDATE_OPERATION,
ALLOW_DELETE_OPERATION, ALLOW_DDL_OPERATION` — and transactions default to
read-only (`MYSQL_DISABLE_READ_ONLY_TRANSACTIONS` is the opt-out). Then
`ENABLE_PII_REDACTION` walks read results and masks sensitive values before they
reach the client (`src/security/redact.ts`; column-name heuristics, operator-
extensible via `PII_EXTRA_COLUMNS` / regex patterns, invalid patterns logged and
skipped — "one bad entry must not crash the server"). Two steals in one server:
write-power as granular opt-in flags (not one "write" bit), and **DCL-style egress
redaction implemented inside the tool server itself**.

### 16. duty1g/x64dbg-mcp-server (MIT, Zig) — the non-child-process shape
A **native plugin DLL inside the host application**: `src/main.zig` (plugin entry),
`src/core/mcp_server.zig`, `src/core/bridge.zig`, `src/core/config.zig` (Win32
imports; HTTP server, configurable port). Zero dependencies, single binary,
cross-compiled x32/x64; exposes debugger control (breakpoints, stepping, memory,
registers) over HTTP to any MCP client. Proof that "MCP server" ≠ subprocess: the
server can be an in-process plugin of the tool it exposes — the strongest form of
the bridge pattern (no IPC mismatch, full fidelity), at the cost of running
network-facing code inside a trusted process.

---

## PART 4 — TIER D: small / obscure

### 17. theronic/modex (Clojure; NO LICENSE file in repo → all rights reserved, ideas only)
`src/modex/mcp/`: `core.clj, protocols.clj, json_rpc.clj, reflection.clj,
client.clj`, and `tools.clj:315 (defmacro deftools …)` — tools/resources/prompts as
**language constructs** built on protocols + reflection: the registry is derived
from the code's own metadata at runtime instead of a manifest file. The opposite
design pole from server.json — and a reminder that manifest-only discovery (JARVIS's
choice) buys auditability at the price of this kind of ergonomics.

### 18. shinzo-labs/shinzo-ts (MIT) — observability as a wrapper
`src/instrumentation.ts:6 class McpServerInstrumentation` — OpenTelemetry spans
wrapped around an MCP server's handlers (config in `src/config.ts`): latency,
errors and call counts per tool without touching tool code. The FastMCP-middleware
idea (§6) reduced to one concern, done portably.

### 19. ahmedeltaher/azan-mcp (MIT, Python) — the single-domain long tail
Prayer-time tools (`src/azan_mcp/server.py` importing tool modules `azan, asma,
calculators, calendar, dua_dhikr, prayer_times` from a `prayer_engine.py`). Tiny,
focused, published via Smithery (`smithery.yaml`) and Docker. Represents the real
ecosystem bulk: one author, one domain, FastMCP-style packaging, registry-distributed.

### 20. Chen-speculation/auto-MCP-client (Go) — config-driven multi-server client (license: PLACEHOLDER)
`mcp/types.go:96 BaseServerConfig`, `:110 ProcessServerConfig`, `:125
SSEServerConfig`, `mcp/engine.go:23 NewEngine(EngineConfig)` — a client engine that
reads a config of heterogeneous servers (process + SSE) and presents their tools to
an OpenAI-style model (`mcp/openai_provider.go`). **License finding: the LICENSE
file is an unfilled template** ("Placeholder for License text. Choose an
appropriate open-source license…") — legally all-rights-reserved despite being
public. A standing warning for the whole scan: public ≠ licensed.

### 21. GongRzhe/Office-Word-MCP-Server (MIT) & zcaceres/markdownify-mcp (MIT) — document utilities
Word server ships a ready `mcp-config.json` in-repo (the host-config snippet users
paste — the ecosystem's real distribution unit). Markdownify (`src/Markdownify.ts`,
`server.ts`) is the minimal viable server: one conversion capability, nothing else.
Both confirm the packaging norm: repo = server + README + a copy-paste host config.

### 22. upstash/context7 (MIT) — PARTIAL (tree-level only)
Verified via `git show`: monorepo `packages/{mcp, sdk, cli, opencode, pi,
tools-ai-sdk}` — the docs-retrieval server ships alongside an SDK and per-host
adapters (the distribution play: be in every host's config). Root `context7.json`
contains a **public key** (`"public_key": "pk_…"`) — public-by-design client
identifiers committed to the repo, distinct from secrets; a useful calibration for
what may/may not live in a manifest. Src not read (clone race) — no mechanism
claims made.

---

## PART 5 — Cross-cutting findings

**Manifest formats.** Two coexisting layers: (1) the *runtime* manifest is the
server's own `tools/list` response (name, description, inputSchema — and in newer
protocol versions outputSchema + annotations); there is NO standard on-disk server
manifest beyond (2) the **registry/distribution** layer: `server.json` (§1) +
host configs (`mcpServers: {command, args, env}` — seen in dockmaster installers,
office-word's shipped `mcp-config.json`, 5ire-style client UX). JARVIS's skill.json
is richer than both on *policy* (tiers, capabilities, quarantine) and poorer on
*distribution* (no registry identity, no package provenance/hash — server.json has
`fileSha256` and `repository` for exactly this).

**Tool schema design.** JSON Schema (draft-07 lineage), generated from code
(FastMCP type hints, Arcade decorators, Go jsonschema-go in k8s server) far more
often than hand-written. Descriptions carry behavioral instructions — which is
also the poisoning surface the prior study flagged; FastMCP shipping a
`tool_injection.py` middleware is the ecosystem admitting it.

**Auth/secrets.** Three strata: stdio servers get **env vars named in the manifest**
(never values in the registry; `isSecret` only flags UI handling); HTTP servers are
OAuth 2.1 resource servers (python-sdk's discovery-from-WWW-Authenticate flow,
FastMCP's oauth/oidc proxies + CIMD, ToolHive acting as AS); and the grown-up
pattern — **the host/proxy holds tokens, servers never see raw credentials**
(ToolHive injection, Arcade per-tool token brokering). Nobody in the scan sandboxes
a stdio server's *filesystem* reach except via containers (ToolHive) or the
server's own discipline (filesystem roots).

**Transports.** stdio (default, local, spawn-managed), SSE (legacy, still shipped),
Streamable HTTP (current; `mcp-session-id` header or stateless), plus exotics:
native-messaging bridge (mcp-chrome), in-process plugin HTTP (x64dbg), proxy
re-serving (dockmaster/ToolHive).

**Error shapes.** Two planes (§3): protocol errors = JSON-RPC codes with a governed
allocation band; tool errors = successful results with `is_error: true` +
human-readable content (+ optional structured content). Ecosystem tooling converges
on normalizing everything else into that shape (Arcade adapters, FastMCP
error_handling middleware, ToolRegistry `_ToolError`, dockmaster `map_error`).

## PART 6 — Verdict for JARVIS v2's skill registry

v2 verified from code (`jarvis/skills/registry.py`): skill.json keys
`{name, version, description, capabilities, tools, lifecycle, resources}`; tool keys
`{name, description, parameters|schema, returns, tier|risk_tier(1..3), timeout_s,
output_cap_chars, capabilities}`; **closed capability vocabulary**
`{fs.read, fs.write, net.outbound, exec, time.read, clipboard.read}` with unknown
keys/caps as startup errors; manifest-only discovery; quarantine until `approve()`;
SkillContext jail; circuit breakers. Against the whole MCP field, v2's *policy*
model is ahead (tiers are enforced, MCP annotations are advisory-only) — its gaps
are distribution, declaration, and interoperability:

**TOP 3 STEALS**
1. **Import `server.json` + ship an MCP-client bridge skill.** Teach the registry a
   second manifest dialect: parse a registry `server.json` (schema-pinned,
   reverse-DNS name, `packages[]` with registryType/identifier/`fileSha256`,
   `remotes[]`, env inputs with `isSecret`) into a quarantined skill whose tools
   are the MCP server's `tools/list`. Spawn stdio servers **non-shell** with the
   TS-SDK env allowlist (`getDefaultEnvironment`, §4) — manifest-named env vars
   only, values from the existing vault — and route every call through the
   existing gate/DCL. Effect: the entire MCP ecosystem (~179k repos from the
   triage search) becomes installable JARVIS skills without weakening the model
   that makes v2 safer than every host scanned.
2. **Declared per-tool requirements + annotation hints in skill.json** (Arcade §8 ×
   k8s §10): add `requires_secrets: [names]`, `requires_env: [names]`, and
   `annotations: {destructive, idempotent, open_world}` beside the enforced tier.
   The gate refuses to expose a tool whose named secrets aren't vault-approved;
   `destructive` + argument patterns drive confirmation rules with an explicit
   fallback when the surface can't ask (elicitation-unsupported case);
   `idempotent` licenses verifier retries. Small manifest change, three
   subsystems upgraded.
3. **Adopt the two-plane result envelope everywhere** (§3/§5): every dispatch
   returns `{content, structured, is_error, code}` with a small governed code
   table modeled on the JSON-RPC/MCP band. Tool failures stay in-band so the
   brain self-corrects (v2's ReAct loop gains real signal); gate/jail/protocol
   failures stay exceptions. Uniform errors also unlock ToolHive-style per-call
   audit events (§7) in the session store and FastMCP-style `response_limiting`
   as a middleware rule on top of the existing `output_cap_chars`.

**Runners-up:** toolset grouping (k8s §10 — enable/disable skill packs per
surface: voice gets a different toolset than phone R1); code-mode chaining (§9 —
v2's sandboxed `code_run` is 80% there; bind approved skill tools as functions
inside it); server-side PII redaction defaults (mysql §15 — move DCL redaction
into skill dispatch so even tier-1 outputs are sanitized); registry provenance
(`repository` + hash pinning in skill.json, §1/§5).

**License ledger (verified from the clones):** fastmcp Apache-2.0; toolhive
Apache-2.0; kubernetes-mcp-server Apache-2.0; playwright-mcp Apache-2.0;
servers monorepo MIT→Apache-2.0 transition; arcade-mcp MIT; mcp-dockmaster MIT;
mcp-chrome MIT; mcp-server-mysql MIT; x64dbg-mcp-server MIT; ToolRegistry MIT;
shinzo-ts MIT; azan-mcp MIT; Office-Word MIT; markdownify-mcp MIT; context7 MIT;
code-mode **MPL-2.0** (patterns only / file-level copyleft); modex **no license**
(ideas only); auto-MCP-client **placeholder license** (ideas only); python-sdk /
typescript-sdk / registry licenses not re-read this pass — verify before any code
reuse. All "steals" above are design-level and safe under every license listed.
