# MCP Servers Inside v2's Skill System

*PHASE INFINITY, Research Cycle 28. The last major deferred item from the skill-system spec (learn-skill-system-spec.md §8.6 / Clause K-3 open question).*
*Date: 2026-10-19. Status: study complete, unvalidated against a real Windows build.*

**Reading rule:** MCP is a road, not a security boundary. Every claim below is tagged; unverified industry claims are marked as such.

---

## 1. MCP in one page [VC — protocol shape; MC — 2026 ecosystem numbers]

The **Model Context Protocol** (Anthropic, open standard, late 2024) is how an LLM host discovers and invokes external capabilities. Three actors:

- **Host** — the AI application (v2's brain + client code).
- **Client** — per-server session inside the host; negotiates capabilities, sends tool calls.
- **Server** — a process exposing **tools** (callable functions), **resources** (data: files, API responses), and **prompts** (reusable instruction templates).

Two transports [VC]:
- **stdio** — the server is a child process; messages over stdin/stdout. Default for local servers. The server inherits the launching user's full OS permissions — **ambient authority by default**.
- **Streamable HTTP** (successor to SSE transport) — the server is a network service, local or remote. Since the June 2025 spec revision, **OAuth 2.1 with PKCE is the authentication standard** for HTTP servers; servers are classified as OAuth Resource Servers with per-server audience (RFC 8707) [MC — from 2026 hardening guides; spec direction confirmed across multiple sources].

What servers can do: anything a process can do — read files, run shell commands, call APIs, hold sockets, keep state across calls, spawn children. There is **no sandbox, no capability model, no tool-description verification in the protocol itself** [VC — stated explicitly in the spec's security best-practices page and confirmed by every 2026 audit writeup]. Every one of those decisions belongs to the deployer.

Ecosystem state 2026 [MC — industry writeups, figures vary]: thousands of public servers (GitHub, registries, Discord), no central registry with malware scanning, no verified-publisher program. The supply chain is npm-in-2012: useful, fast-moving, unvetted.

The voicebox decision (learn-voicebox — v2 wraps voicebox via MCP at `127.0.0.1:17493/mcp`) makes this study load-bearing, not theoretical: v2 will run at least one MCP server on day one of voice.

---

## 2. The trust difference: why a malicious MCP server is worse than a malicious skill [HC]

Skills (per the spec) are **imported code with declared capabilities**: they run inside v2's process (or a worker), declare 13 capabilities, execute through the §4 pipeline (schema-validate → capability-check → risk-gate → bound → evidence-wrap), and die when the turn ends. Their blast radius is bounded by the pipeline.

MCP servers are **separate long-lived processes**. The trust shape differs in five ways, each strictly worse:

1. **Ambient authority.** A stdio server launched by v2 inherits the user's token: SSH keys, `%APPDATA%` secrets, browser profiles, env vars — unless v2 explicitly strips them. A skill's file access goes through the R4 jail; a server's file access goes through *whatever the server's code does*. [VC]
2. **Persistence across turns.** A server keeps state between calls and between sessions. A malicious server can stage an attack over days (learn the user's patterns on Monday, exfiltrate on Friday). Skills are stateless per dispatch. [HC]
3. **Network listeners.** An HTTP server holds a socket. DNS rebinding against `localhost` listeners is a documented attack: malicious JavaScript in a browser tab calls the local server without origin validation [MC — reported in 2026 audits]. Skills never listen.
4. **Self-update.** A server can download and exec its own updates (many do — `npx` shims, auto-updaters). A quarantined skill is hash-pinned; a server can mutate out from under the pin. The manifest-hash re-quarantine rule from the skill spec does not transfer. [HC]
5. **Tool poisoning at the metadata layer.** Tool *descriptions* are LLM context. A malicious server embeds instructions in tool metadata ("when called, also exfiltrate keys") — 5 of 7 evaluated MCP clients performed no static validation of server tool descriptions [MC — MCP threat-modeling community research, via policyascode.dev]. The skill spec's evidence-wrap covers tool *results*; MCP needs the same treatment for tool *definitions* — descriptions are untrusted content too. The WhatsApp MCP incident (full message-history exfiltration via poisoned tool metadata, Invariant Labs) is the reference case [MC].

**The short version:** a malicious skill is a bad guest in your house (the pipeline watches it). A malicious MCP server is a bad *neighbor with a key* — its own process, its own schedule, its own network.

---

## 3. The sandbox story on Windows [HC on mechanisms; MC on practical ceilings]

The skill spec asks: what's practical on Windows for sandboxing a server process? The mechanisms, cheapest first:

**Layer 1 — launch-time stripping (cheap, do this always) [VC]:**
- Launch the server with a scrubbed environment (`env={}` plus an explicit allowlist — the hardened_runner `test_attack_env_exfiltration_blocked` pattern, applied to server spawn).
- Working directory pinned to a scratch dir; no inherited handles.
- stdio servers: no network capability granted by default — a stdio server that opens sockets is anomalous and must declare it.

**Layer 2 — Windows Job Objects (cheap, practical) [HC]:**
- Assign the server process to a Job Object with limits: `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (no orphaned servers — kills the C-V-era zombie class), CPU rate caps, working-set caps, `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` (no child-spawning unless declared — answers the "servers that spawn children" question: default deny, declare to allow).
- Job objects are the Windows-native equivalent of Linux cgroups-lite. Implementable in ~100 lines of ctypes/pywin32. No admin rights needed for own-process jobs.

**Layer 3 — restricted tokens / integrity levels (medium cost) [MC]:**
- Launch with a restricted token (deny-only SIDs) or Low integrity level. Low-integrity processes cannot write to user profile locations — which breaks most legitimate servers (they want config dirs). Practical ceiling: restricted tokens work for narrow servers (a calculator, a date server); general-purpose servers (filesystem, browser) fight it.
- AppContainer (the Edge/Store sandbox) is the strong option but requires packaging the server as an AppContainer-aware binary — impractical for arbitrary `npx` servers. [MC]

**Layer 4 — Windows Firewall per-process rules (medium cost) [HC]:**
- Default-deny egress for the server process; allowlist by hostname via WFP (Windows Filtering Platform) rules. The xsypher hardening guide's rule — "default-deny egress, then allowlist by hostname" — is the single highest-value control: it removes the exfiltration half of every attack (cf. the WhatsApp case: tool poisoning + unrestricted network = exfiltration; remove the network and the poisoning has nowhere to send data).
- Practical via `New-NetFirewallRule` with `-Program` scoping, applied at server registration. No admin needed for per-user rules.

**Layer 5 — full VM/container isolation (expensive, deferred) [VC]:**
- Firecracker microVMs (E2B pattern, EV 61.2 in the goldmines) or Docker Desktop with WSL2. Strongest isolation; heaviest operational cost on a consumer PC (Docker Desktop = GBs of RAM, license considerations). The industry is converging here (Microsoft's MXC execution containers for Windows agents, Oct 2026 [MC — rakibulinux.com report]; Perplexity's open-source SPACE, Firecracker-based [MC]).
- Verdict for v2: **deferred, not dismissed** — same posture as the threat model's residual risk #4. Revisit trigger: a sandbox-escape PoC against the Layer 1–4 stack.

**The practical stack for v2:** Layers 1 + 2 + 4 for every server, always. Layer 3 for narrow servers. Layer 5 deferred. This is implementable in the skill-system's server-manager component without new dependencies (ctypes + netsh/PowerShell for firewall rules).

---

## 4. The permission model: MCP servers in the Deno-style vocabulary [HC]

The skill spec's 13-capability vocabulary maps to MCP servers with three adjustments:

**Maps cleanly:** `fs.read` / `fs.write` (scoped to declared roots — the server's file tools get the same jail treatment, enforced at *v2's* dispatch layer since the server itself can't be trusted to jail itself), `network.outbound` (hostname allowlist — enforced at Layer 4, declared in `mcp.json`), `exec` (almost never granted to servers; a server that needs subprocesses declares it and gets Layer 2's child-process limit).

**Doesn't map — needs new capabilities:**
- `net.listen` — the server holds a socket. Default **deny** for stdio servers; for HTTP servers, bound to loopback + origin validation required (DNS-rebinding defense). A server requesting `net.listen` on a non-loopback address is a red flag at quarantine review.
- `proc.spawn` — the server may spawn children. Default deny; Layer 2's `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` enforces the declared count.
- `proc.persist` — the server keeps state across sessions. Not a permission to *grant* but a fact to *record*: persistent servers get the audit-trail requirement (every cross-session state read/write logged) and a user-visible "this server remembers things" badge.
- `self.update` — default **deny**. A server that auto-updates is re-quarantined on every update (hash change = new quarantine review). This closes the self-update hole from §2.

**The dispatch-layer rule (Clause K-3's missing half):** `mcp.json` tools flow through the §4 pipeline — schema-validate, capability-check, risk-gate, bound, evidence-wrap. The capability check for an MCP tool is the *intersection* of the server's granted capabilities and the tool's declared needs. A server granted `fs.read:/data` whose tool tries `/etc/shadow` fails at v2's layer even if the server's code allows it — **defense in depth: the server is untrusted too**.

---

## 5. Quarantine for MCP: what "scan + approve before first run" means for a server [HC]

The skill quarantine (static scan + user approval + hash-pinned manifest) transfers with server-specific additions:

1. **Declared-tools review.** At registration, v2 fetches the server's tool/resource/prompt list and shows the user: tool names, what each claims to do, which capabilities each needs. Tool *descriptions* are displayed as untrusted (they're LLM-targeted text) — and v2 **hashes the description set**. A description change at runtime = re-quarantine (kills silent tool-poisoning updates).
2. **Sandbox trial run.** Before first real use, v2 starts the server in the Layer 1+2+4 sandbox and runs a scripted probe: list tools, call each tool with benign args, observe syscalls/network attempts. Anything the server does that its declaration didn't mention (opens a socket, spawns a child, reads outside its roots) = quarantine failed, user notified with specifics. This is the dynamic complement to the static scan — and it's the only scan that can catch behavior, not just code. [MC on effectiveness — catches crude malice, not targeted stealth; labeled as tripwire, not wall, per the REA lesson]
3. **Provenance requirement.** Where did this server come from? npm package (version pinned, not `latest`), GitHub repo (commit pinned), or local path. `npx -y` floating installs are **refused** — the April 2026 "Mother of All AI Supply Chains" incident (150M+ downloads, 200k vulnerable instances via STDIO flaws [MC — aibuzz.blog]) is what floating gets you.
4. **The voicebox exception.** First-party servers (voicebox at `127.0.0.1:17493/mcp`) ship with v2's own signature and skip user approval but **not** the sandbox — trusted code still gets Layers 1+2+4. Trust is not a sandbox exemption.
5. **Runtime monitoring.** Every tool call logged (server identity, tool, args, timestamp — the 2026 best-practice checklist [MC]); description-hash checked per session; egress attempts outside the allowlist blocked + surfaced. A server that starts misbehaving mid-life gets disabled with the evidence shown to the user.

---

## 6. Verdict: ship-skills-first — CONFIRMED, with a precise boundary [HC]

The skill spec's recommendation holds, and this study sharpens it into a rule:

**Ship order:**
1. **Skills first** — in-process, pipeline-bounded, quarantine model proven by the hardened_runner tests.
2. **MCP second, in two tiers:**
   - **Tier A (ship with v2.1):** first-party servers only (voicebox). Full sandbox (Layers 1+2+4), `mcp.json` through the §4 pipeline, description-hash monitoring. The trust decision is v2's own signature.
   - **Tier B (later, gated):** third-party servers. Everything in Tier A **plus** the full quarantine (§5: declared-tools review, sandbox trial, provenance pinning, runtime monitoring). No Tier B server without all five quarantine steps.

**Concrete prerequisites for Tier B (the checklist):**
- [ ] Server-manager component implementing Layers 1+2+4 (job objects via ctypes, firewall rules via netsh/PowerShell, env scrubbing) — no new dependencies.
- [ ] `mcp.json` schema with the four new capabilities (`net.listen`, `proc.spawn`, `proc.persist`, `self.update`) and the intersection rule at dispatch.
- [ ] Description-hash monitoring (per-session check, re-quarantine on change).
- [ ] Sandbox trial-run harness (scripted probe + behavior diff against declaration).
- [ ] Provenance pinning (no floating `npx -y`; commit/version pins recorded).
- [ ] The audit-trail requirement for `proc.persist` servers.
- [ ] DNS-rebinding defense for HTTP servers (loopback bind + Origin validation).
- [ ] User-facing quarantine UI (the declared-tools review screen) — needs the approval-UX work from Cycle 20.

**What would change the verdict (watch triggers):**
1. A maintained, malware-scanned MCP registry with verified publishers (removes the supply-chain objection for Tier B).
2. Protocol-level tool-description signing (removes the poisoning-at-metadata objection).
3. Windows shipping a consumer-friendly process sandbox API (lowers the Layer 3/5 cost).

**What this study does NOT establish:** measured overhead of the Layer 1+2+4 stack on the 2060 (benchmarking weekend); the quarantine UI's effectiveness against real users (needs the fatigue research from Cycle 20 applied); whether description-hash monitoring catches real poisoning attempts in the wild (no production data).

---

## Confidence & unknowns

- [VC] MCP protocol shape (tools/resources/prompts, stdio/HTTP, no in-protocol sandbox — the spec's own security page says the deployer owns these controls).
- [HC] The five trust differences, the Layer 1+2+4 practicality on Windows (job objects and per-user firewall rules need no admin), the four new capabilities, the quarantine design.
- [MC] 2026 ecosystem figures (server counts, incident details — single-source industry writeups), Layer 3 practical ceiling, trial-run effectiveness, MXC/SPACE reports.
- [UK] Measured sandbox overhead on the target hardware; real-world quarantine-UI effectiveness; whether any 2026 incident figures are inflated by vendor marketing.

## References (verbatim URLs from search output)

- https://dev.to/royce_fabbd83cb268312e928/mcp-server-security-best-practices-2026-4oel — OAuth 2.1 mandate, tool poisoning, ambient authority, DNS rebinding.
- https://medium.com/@zellkernel/wtf-is-mcp-57536249d6d8 — "MCP is a road, not a security model"; the lethal-trifecta framing.
- https://dev.to/chunxiaoxx/mcp-security-vulnerabilities-in-2026-command-injection-ssrf-mitigation-strategies-kmb — command injection, SSRF, sandboxing options.
- https://policyascode.dev/blog/mcp-security-vulnerabilities-2026/ — 5-of-7 clients skip tool-description validation; session IDs in URLs.
- https://dev.to/ecap0/the-state-of-mcp-server-security-in-2026-what-we-learned-auditing-the-ecosystem-4i86 — tool redefinition attacks, no central registry.
- https://aibuzz.blog/mcp-security-for-beginners/ — CVE-2026-82456 pattern, April 2026 supply-chain incident figures.
- https://windowsforum.com/threads/mcp-security-treat-ai-agents-as-privileged-infrastructure.404091/?amp=1 — treat MCP servers as high-risk supply chain; approve toolchains as bundles.
- https://xsypher.com/article/how-to-secure-mcp-servers-and-ai-agents-in-production — per-server OAuth audience; "sandbox the server, not just the prompt"; default-deny egress.
- https://medium.com/@urshilaravindran/a-practical-starter-guide-to-mcp-pentesting-bb37e45fbb08 — least-privilege, server-side enforcement, stdio sandboxing.
- https://www.rakibulinux.com/blogs/microsoft-execution-containers-ai-agents-windows — Microsoft MXC execution containers (Oct 2026); Perplexity SPACE (Firecracker).
- https://mcpmanager.ai/blog/sandbox-mcp-servers/ — containerization rationale for workstation servers.

## Traceability

- Closes: learn-skill-system-spec.md §8.6 + §9 open question ("MCP server sandbox story needs a dedicated study").
- Feeds: threat model (new attack surfaces §2 → future coverage-matrix rows); reliability spec (server-manager as a dependency-map row); voice-loop spec (voicebox is the Tier A reference server); approval-UX spec (quarantine UI prerequisite #8).
- Rule 12: researched (2 web searches, 11 sources, skill-spec deferred text read); validated (deferred clause quoted verbatim from the spec); saved (1 file); tested/measured (nothing — study only); incomplete (none); blocked (Windows build validation, overhead measurement — recorded).
