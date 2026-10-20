# TEAM 13 — Browser Automation Agents: PhD-Level Reverse Engineering

Compiled 2026-10-20 for JARVIS v2 (Python, stdlib-only). Method: GitHub search triage
(153 unique repos across 6 query terms), then source-level reads of core files
(GitHub contents API for listings/first files; `git clone --depth 1` for bulk code).
Every mechanism below is cited to file:function in the repo named. Star counts as of 2026-10-20.

**JARVIS relevance key:** representation = what the model "sees"; action space = what the
model can emit; v2 constraint = stdlib-only Python (no pip), so code steals are rare —
DESIGN steals (protocols, pruning rules, verification patterns) are the real currency.

---

## 1. browser-use/browser-use — 118,583★ — Python — MIT (LICENSE at repo root)

Layout: `browser_use/{agent, browser, dom, tools, llm, mcp, skills, filesystem, sandbox, screenshots}`.
Drives Chromium over raw CDP (their own session layer, not Playwright anymore:
`browser/session.py`, `browser/profile.py`).

### Page representation — distilled DOM → indexed text tree (the field's reference design)
- `dom/service.py` + `dom/enhanced_snapshot.py`: CDP DOMSnapshot + accessibility data fused
  into `EnhancedDOMTreeNode` (geometry, visibility, AX role/name, shadow roots).
- `dom/serializer/serializer.py:DOMTreeSerializer.serialize_accessible_elements()`:
  1. `_create_simplified_tree()` — prunes invisible/non-content nodes; keeps shadow DOM
     (SPAs hide real controls there); collapses SVG subtrees to `<svg ... /> <!-- SVG content collapsed -->`.
  2. `_optimize_tree()` — collapses wrapper-only chains.
  3. `_apply_bounding_box_filtering()` / `PropagatingBounds` — drops elements occluded by
     scroll-container ancestors (`_is_contained` with threshold), so the model never sees
     off-screen clutter it cannot act on.
  4. `_assign_interactive_indices_and_mark_new_nodes()` — every interactive element gets a
     **stable selector index**; lines render as `[12]<button ...>`; elements that appeared
     since the previous step are prefixed `*` (`*[13]`) — a built-in page-diff signal.
- `dom/serializer/clickable_elements.py:ClickableElementDetector.is_interactive()` — pure
  heuristics, no LLM: native interactive tags, ARIA roles, **CDP-detected JS click listeners**
  (catches Vue `@click` divs), `cursor:pointer`, and form controls nested ≤2 deep inside
  `<label>` wrappers.
- Compound widgets get expanded inline: `_add_compound_components()`, `_extract_select_options()`
  (a `<select>` is serialized with its options), dropdown/date-picker detection via CSS-class
  patterns (jQuery/Bootstrap) annotated in `_build_attributes_string()`.
- `dom/markdown_extractor.py` — separate page→Markdown path for read-only extraction.
- Per-step prompt assembly (`agent/prompts.py:AgentMessagePrompt.get_user_message()`):
  `<agent_history>` + `<agent_state>` + `<browser_state>` blocks, page statistics header
  (counts of links/interactive/iframes/shadow roots/scroll containers), clickable tree capped
  at `max_clickable_elements_length = 40_000` chars, and **step-varying metadata pushed to the
  tail so the prefix stays prompt-cacheable**. Screenshots optional for vision models.

### Action space (`tools/service.py:Tools`, executed via `act()` with per-action timeout, default 180 s)
`navigate`, `search` (web search), `go_back`, `wait`, `click` (index-first; coordinate click
exists but is **capability-gated** — auto-enabled only for vision models that support it:
Claude 4.5 family, Gemini 3 Pro, their own models), `input` (by index), `upload_file`,
`switch`/`close` tab, `extract` (schema-guided LLM extraction), `search_page` (text search in
DOM), `find_elements` (description → indices), `find_text` (visible text → element, click),
`scroll`, `send_keys`, `select_dropdown`, `done` (structured final answer, optional schema).
The model may emit **multiple actions per step** (executed sequentially).

Form/multi-step realities, in code:
- `input()` does **post-write verification**: reads the field's actual value back and warns
  the model if it differs from what was typed (catches reformatting/autocomplete overwrites).
- Autocomplete/combobox fields (`role=combobox`, `aria-autocomplete`) get a forced 0.4 s wait
  and a hint injected into the result: "click the correct suggestion instead of pressing Enter".
- Stale index → explicit recoverable error ("page may have changed. Try refreshing browser state")
  returned as the action result, not an exception — the loop self-heals.

### Sessions / auth / anti-bot
- Auth = a real persistent Chrome profile (`browser/profile.py`): cookies/storage live in a
  user-data-dir; or connect to an already-running Chrome over CDP; cloud mode rents their
  hosted browsers.
- **Sensitive-data pattern (important):** caller passes `{placeholder: secret}`; the model only
  ever emits `<secret>name</secret>`; the real value is substituted at dispatch time and results
  log only "Typed <key_name>" (`tools/service.py:input()`, `has_sensitive_data`). Secrets never
  enter model context or logs.
- Anti-bot: essentially none in the OSS core — stealth is their paid cloud product. CAPTCHAs
  are not solved. (Consistent with JARVIS doctrine: never automate CAPTCHA solving.)
- `agent/judge.py`: a separate LLM judge verifies claimed task completion; `agent/variable_detector.py`
  scans page text for variable/secret patterns.

**Steal verdict for v2:** the *representation protocol* (indexed, pruned, new-node-marked text
tree) and three interaction patterns (post-write value verification, autocomplete wait+hint,
placeholder secrets). Code is Python but depends on CDP + pydantic/langchain — design only.

---

## 2. lavague-ai/LaVague — 6,392★ — Python — Apache-2.0

Two-stage "Large Action Model" split (`lavague-core/lavague/core/`):
- **WorldModel** (`world_model.py:WorldModel.get_instruction()`) — a multimodal LLM sees the
  screenshot (+ optional knowledge files) and emits ONE natural-language instruction
  ("click the sign-in button") per step. It never touches the page.
- **NavigationEngine** (`navigation.py`) grounds the instruction:
  - `get_nodes()` — splits the page HTML into nodes and runs an **embedding retriever**
    (`retrievers.py`) to fetch only the nodes relevant to the instruction; on the first pass
    `viewport_only = not self.driver.previously_scanned` (viewport first, full page after scroll).
  - `get_action_from_context()` — the LLM picks from the retrieved snippet and emits an action
    whose target is an **xpath**.
  - `_verify_llm_reponse()` — **closed-world anti-hallucination check**: xpaths present in the
    retrieved context are extracted (`extractors.py:extract_xpaths_from_html`) as the authorized
    set; any emitted xpath outside the set raises `HallucinatedException` (or
    `ElementOutOfContextException` if it resolves on the page but wasn't in context).
- **ActionEngine/PythonEngine** (`action_engine.py`, `python_engine.py`, `action_template.py`) —
  dispatch to engines that generate and execute Selenium code from templates (code-gen agent
  pattern); `NavigationControl` handles scroll/next-page as a separate engine.
- Sessions: Selenium driver (fresh browser, no profile persistence by default).

**Steal verdict:** the **authorized-target closed world** — the model may only act on targets
the perception layer handed it, verified mechanically before execution. That is exactly v2's
gate/DCL philosophy applied to web elements. Retriever-over-DOM-nodes is also a viable
context-budget design (embeddings needed; FTS/token-overlap works stdlib-only as a poor-man's retriever).

---

## 3. nanobrowser/nanobrowser — 14,132★ — TypeScript (Chrome extension) — Apache-2.0

Runs **inside the user's real, logged-in Chrome** (extension + side panel) — the auth problem is
solved by construction: it inherits the user's session, tabs, cookies. Code has visibly matured
into a hardened agent runtime (`src/agent/`, `src/browser-control/`).

### Page representation (`src/browser-control/core/perception/`)
- `ax.ts` — Chrome **accessibility tree** as primary representation; `layout.ts` adds
  layout-derived elements the AX tree misses; `outline.ts` builds a page outline;
  `diff.ts` diffs successive observations; `capture.ts`/`window.ts` handle viewport windows.
- **Refs** (`core/refs.ts`) — durable labels bound to (session, frame, document, backendNodeId),
  epoch-prefixed, never reused; each ref carries a `RefPrint` (AX role+name, ordinal `nth` among
  same role+name, enclosing-row digest for disambiguation) and explicit staleness reasons
  (`document`, `frame-detached`, `debugger-detached`) so errors explain *why* a ref died.

### Actions return receipts with effect verdicts (`core/interaction/`, `core/tools/`)
Tools: `act`, `fill`/`fill_form`, `navigate`, `observe`, `tabs`, `text`, `upload`, `wait`,
`dialog`, `ask` (page Q&A). Every action result carries `receipt.effect = {verdict: 'changed'|'none',
signals: [...]}` — the harness **verifies the action changed the page** (e.g. "scrolled into view")
instead of trusting dispatch. `interaction/gate.ts` + `actionability.ts` check actionability
before acting (Playwright-style: visible/stable/enabled checks).

### Loop guards (`src/agent/guards.ts`) — the most production-hardened anti-loop design found
- Call **signature** = tool + args (minus the agent's stated `intent`) + outcome verdict.
- `REPEAT_WINDOW=6, REPEAT_LIMIT=3` — same signature 3× in last 6 calls → stop.
- **No-effect guard**: mutating tools (click/set/type/press/fill_form) aimed at the same target
  with `verdict: none` → nudge at 2, stop at 3 ("clicking isn't working — change approach").
- Error streak ≥5 → stop; on stop, one **salvage call** lets the model wrap up honestly.
- Context engineering: `compaction.ts`, `elision.ts`, `injection-context.test.ts` — history
  compaction with **prompt-injection-aware context handling**; `perception/masking.ts` +
  `refs.ts:shownName` mask sensitive values inside element names before they reach the model
  (the raw name is used only internally for revalidation, never printed).

**Steal verdict:** (1) **effect-verdict receipts** — every v2 browser action should report
changed/none + signals; (2) **signature-based loop guards with no-effect detection** — pure
stdlib logic, directly portable to v2's ReAct loop; (3) masking at the perception layer.

---

## 4. Skyvern-AI/skyvern — 23,232★ — Python (Playwright) — **AGPL-3.0 → ideas only, never code**

Built for form-heavy workflow automation (job applications, government/insurance forms).
Two generations coexist: classic agent (`forge/agent.py`, `webeye/`) and a hardened "task v3"
tool-loop (`forge/taskv3/`); plus a block-based workflow SDK (`forge/sdk/workflow`).

### Page representation — DOM-injected ID tagging + hashed element dicts
- `webeye/scraper/scraper.py:build_element_dict()` — interactable elements are **tagged in the
  live DOM** with a unique attribute (`SKYVERN_ID_ATTR`, rendered back as `[attr='id']` CSS
  selectors); the page is serialized as a trimmed element-dict tree annotated with those IDs.
- `hash_element()` / `structural_identity()` — each element gets a content hash and a structural
  identity (tag+attrs, values stripped) → cheap change detection and dedup across steps;
  cross-frame ID collisions are tracked explicitly (`cross_frame_collision_ids`).
- Screenshot + element tree are fused (elements carry coordinates) for vision models.

### Forms — planned in ONE call, committed with discipline (`taskv3/`, `forge/prompts/skyvern/*.j2`)
- `batch-form-fill-plan.j2` — a single LLM call plans **every field value** from user data before
  any typing: choice fields must return the **exact option label** ("return 'Man', NOT 'Male'"),
  null allowed only for uploads/truly-optional fields, format hints per field type.
- ~45 specialized Jinja prompts: autocomplete choose/tweak-value, custom-select handling,
  `check-user-goal-with-termination` (goal/termination verification), `decisive-criterion-validate`,
  date/phone format checkers, `pre_submit_capture.py` + `field_commit.py` (capture state before
  submit, commit fields atomically-ish), `goal_check.py` (independent completion check).

### Secrets / signed URLs — opaque tokens (`forge/taskv3/opaque_refs.py`)
Signed payload URLs reach the model only as `opaque_url_<n>` tokens, resolved inside tool
handlers "the way credential placeholders are". Signing-artifact detection is shape-based:
query keys named sig/token/key/secret/auth…, plus a JWT shape regex (`eyJ…` header anchor,
segments capped at 512 chars explicitly to avoid ReDoS backtracking). `handoff_redaction.py`
redacts again at human-handoff boundaries. Strongest DCL-style egress design in this scan.

### Anti-bot / CAPTCHA — the honest exception
Skyvern **does** integrate CAPTCHA solving: `forge/taskv3/captcha_tools.py` gives the loop an
explicit `solve_captcha` action (shared solver backend, 120 s ceiling, per-task attempt budget
reset on success; image-text CAPTCHAs read via OCR path). It also documents the failure mode
precisely: cross-origin iframe CAPTCHAs (Turnstile/reCAPTCHA) are *not enumerable by observe*,
so without the explicit action the model re-clicks a dead submit forever.
**For JARVIS this is a design note, not a steal** — Owais's rules forbid CAPTCHA solving; the
transferable lesson is the *detection + explicit handoff* shape (name the gate, stop, hand to human),
which their ceiling/attempt-budget bookkeeping models well.

### Sessions
Playwright-managed browser contexts/profiles (`webeye/browser_factory.py`, persistent profiles,
`browser_profile_utils.py`); 2FA/TOTP handled as first-class actions (`webeye/actions/multi_field_totp.py`)
with secrets supplied via credential vault parameters — again placeholder-resolved, never printed.

**Steal verdict:** batch form-plan (one call, exact labels), element hashing for change detection,
opaque tokens for signed URLs, pre-submit capture. AGPL → re-implement from design only.

---

## 5. vercel-labs/agent-browser — 44,301★ — Rust CLI — Apache-2.0

Not a library: a **CLI daemon** designed so any agent (Claude Code etc.) drives a browser via
shell commands. `cli/src/{commands,connection,chat}.rs`, plus a `doctor` suite that diagnoses
Chrome/daemon/network problems (`doctor/{chrome,daemon,network,launch}.rs`).

- Representation: `agent-browser snapshot` prints the **accessibility tree with refs** (`@e1`,
  `@e2`… — Playwright ARIA-snapshot style); `snapshot -i` restricts to interactive nodes;
  actions address refs (`click @e2`, `fill @e3 "text"`). Refs are per-snapshot.
- **Covered-element errors**: clicks fail early with the *covering* element named ("another
  element covers the target's click point, e.g. a consent banner or modal — dismiss it, take a
  fresh snapshot, retry") — occlusion is reported as structured guidance, not a silent miss.
- `diff snapshot` compares current vs last snapshot — page-state diffing as a first-class verb,
  alongside `batch` (multiple commands per invocation) for latency.
- Sessions: launches or attaches to Chrome via CDP; daemon keeps the browser warm between calls.

**Steal verdict:** the CLI-verb surface (`snapshot/click/fill/diff`) is exactly the granularity a
tool-calling LLM handles best; covered-element reporting is a cheap, high-value error pattern.

---

## 6. jo-inc/camofox-browser — 11,730★ — TypeScript — MIT

A server wrapping **Camoufox** (a Firefox fork with **fingerprint spoofing at the C++ level**),
exposed as a drop-in Puppeteer/Playwright-compatible endpoint + MCP (`mcp/`, `server.js`).

- Anti-bot thesis, stated in README: "Playwright gets blocked. Headless Chrome gets
  fingerprinted. **Stealth plugins become the fingerprint**" — so spoofing moved into the
  browser engine itself (navigator/canvas/WebGL/fonts at C++ level), not JS injection.
- **Geo-consistency**: fingerprint (language, timezone, coordinates) is generated consistent
  with the proxy's location — mismatched signals are what detectors actually flag.
- Otherwise a normal automation server (sessions, pages, screenshots); no agent loop.

**Steal verdict:** none for code (v2 won't ship a browser fork); the *lesson* is evidentiary —
anti-bot is an engine-level arms race with paid/geoIP infrastructure, which is why every serious
agent above either rents stealth browsers or drives the user's own real browser. For JARVIS:
attend the user's real Chrome (his session, his fingerprint) or accept public-page limits.

---

## 7. ServiceNow/BrowserGym — 1,408★ — Python (Playwright) — Apache-2.0

Research environment behind WebArena/WorkArena/VisualWebArena — included because its
observation/action contract became the academic reference design.

- `core/observation.py:_pre_extract()` **marks the DOM before reading it**: injects a `bid`
  attribute into interactive elements, recursively through frames (child-frame bids prefixed
  by the parent frame element's bid — hierarchical addressing across iframes); also snapshots
  dynamic attributes (value, checked) at mark time.
- Observation = flattened **AX tree text** (each node tagged with its bid) + optional screenshot
  + DOM extra properties (visibility, bbox via `extract_dom_extra_properties()`).
- Actions are **Python code**: `core/action/functions.py` exposes `click(bid)`, `fill(bid, value,
  enable_autocomplete_menu=False)`, `check/uncheck`, `select_option`, `press`, `drag_and_drop`,
  `scroll`, mouse/keyboard primitives, `goto/go_back`, plus meta-actions `send_msg_to_user` and
  `report_infeasible(reason)` — an explicit, first-class "this task cannot be done" verb.
  `action/parsers.py`/`python.py` parse and execute the model's code block against these.

**Steal verdict:** (1) **hierarchical frame-prefixed IDs** — any v2 representation must address
iframes unambiguously; (2) `report_infeasible` as a designed action — matches v2's honest-stop
doctrine (better than loops); (3) mark-then-read ordering (tag DOM first, then serialize).

---

## 8. Tencent/BrowserSkill — 9,238★ — Rust CLI + TS extension — MIT

Session model for "use my real browser without interrupting me":
- Tasks run in a separate, visible **Agent Window** sharing the selected Chrome/Edge profile's
  login state (README is explicit: "not a separate account or security sandbox — agents act with
  the permissions of the signed-in websites").
- A user's existing tab can be **explicitly borrowed and returned** when the task ends; stray
  external-link tabs landing in the agent window are re-routed to the user's window.
- Capture works on **background tabs without focusing** the window and restores the original
  scroll position afterward — perception must not disturb the human.
- `bsk` CLI + daemon + extension bridge (`crates/bsk-cli`, `bsk-protocol`); full task history /
  evidence exportable as JSON for audit.

**Steal verdict:** the Agent-Window session pattern is the cleanest UX answer to "JARVIS, use my
logged-in browser": separate window, borrowed tabs returned, no focus theft, honest about the
trust boundary. Pure protocol design — portable to v2's phone/PC story later.

---

## 9. jackwener/OpenCLI — 30,451★ — JavaScript — Apache-2.0

Two layers, and the layering is the lesson:
1. **General browser primitives** (snapshot/click/type over the user's logged-in Chrome via
   extension) for unknown sites — same loop as agent-browser.
2. **Deterministic per-site adapters** (`clis/<site>/…`, hundreds: bilibili, reddit, amazon,
   36kr, 51job…): `opencli bilibili hot -f json` returns a stable structured schema in seconds,
   **zero LLM tokens, no agent loop** — built for cron/CI repeat work. Their own comparison doc
   is blunt: for recurring extraction from known sites, adapters beat LLM browsing on cost,
   speed, and determinism; agents win only on novel tasks.
- `designs/self-repair-protocol.md` — when a site changes and an adapter breaks, the agent is
  tasked to diagnose and patch the adapter (procedures are code; the LLM maintains them).

**Steal verdict:** this validates v2's existing doctrine (playbook rule A0: "adapters encode
procedures, never facts") at web scale. For JARVIS: frequent sites (YouTube, Gmail, GitHub,
WhatsApp Web) deserve deterministic adapter skills; the general agent loop is the fallback,
not the default. Adapters are plain JS/Python — stdlib-feasible as skill modules.

---

## 10. parsaghaffari/browserbee — 980★ — TypeScript (extension) — Apache-2.0

"Cline for web browsing" — the cleaned-HTML school, useful as a baseline of what simpler
designs do (`src/agent/tools/observationTools.ts`):
- `browser_snapshot_dom` — raw DOM with options: `selector=` scoping, `clean` (strips
  script/style/non-visible), `structure` (tags/ids/classes only), `limit=` (default 20,000 chars).
- `browser_accessible_tree`, `browser_read_text`, `browser_query` (CSS query), `browser_screenshot`
  as separate tools — the model chooses its representation per step.
Trade-off vs browser-use: no stable indices/verification machinery; the model re-grounds from
text each step. Cheaper to build, flakier on dynamic pages — the gap between the two designs is
precisely the engineering the top entries add.

---

## 11. tinyfish-io/agentql — 1,489★ — Python/JS SDKs — MIT (engine is a hosted API)

Not an agent: a **semantic query layer** over pages. Two primitives:
- A GraphQL-shaped query language whose fields are natural-language descriptions —
  `{ products[] { name price } }` — resolved against the live page server-side.
- `get_by_prompt("the login button")` — one-shot NL→element grounding as a function call.
The SDKs in the repo are thin; the matching engine is closed cloud. Included because the
*interface* is the lesson: agents are far more reliable when perception offers
"resolve this description to an element handle" as one atomic call instead of raw DOM dumps —
the same conclusion LaVague's retriever and browser-use's `find_elements` reach independently.

---

## 12. ntegrals/openbrowser — 9,564★ — TypeScript — MIT

An independent TypeScript re-implementation of the browser-use pattern — valuable as
**convergent-evolution evidence**: `packages/core/src/page/snapshot-builder.ts` fuses CDP
`DOMSnapshot.captureSnapshot` (with computed styles display/visibility/opacity/overflow,
DOM rects, paint order) + `Accessibility.getFullAXTree` into an indexed PageTree
(interactive = tag/role whitelists + visibility). Around it: an explicit **StallDetector**
(`agent/stall-detector.ts` — consecutive stagnant page states raise a stall alert, the
no-effect guard again), a **replay recorder** (agent runs recorded for deterministic replay/
debugging), an evaluator, and token/cost metering. When three independent codebases
(browser-use, openbrowser, nanobrowser) all invent indexed hybrid DOM+AX trees, effect/loop
guards, and completion judges, that set is the de-facto standard architecture.

---

## 13. keon/browser-control — 3,151★ — Rust CLI — MIT

The minimal end of the design space: a CDP pipe for coding agents, deliberately *not* an agent
("the coding agent stays the agent — browser-control just gives it hands and eyes", README).
`snapshot` returns stable `@e1`/`@e2` refs (implemented as attribute selectors internally, see
`src/actions.rs`), plus raw `cdp`/`eval` escape hatches, a background event watcher, and
shell-runnable saved scripts. Its workspace bootstrap writes an `AGENTS.md` protocol for the
driving model: "Use `browser-control snapshot` first. Use refs for simple actions. Use `eval`
or `cdp` when stuck. Write reusable scripts… **Verify before claiming success.**"
**Steal verdict:** the two-tier tool discipline (refs first, raw eval only when stuck) + the
bootstrapped instruction file — a pattern v2 can mirror for its own web skill at zero deps.

---

## 14. SawyerHood/dev-browser — 6,670★ — TypeScript (Puppeteer) — MIT

Ships as a *skill* for coding agents. Snapshot = accessibility tree with ARIA refs; notable
extras from CHANGELOG/code: **cross-origin iframe contents included in snapshots** with
document-scoped frame refs that survive same-document navigation and expire safely on reload;
**tracked snapshot diffs** between calls; persistent named pages; a parallel `domCua` toolset
exposing the visible interactive DOM as `node_id=N` lines when AX is insufficient.
**Steal verdict:** iframe-aware refs + diff-tracking are the two features every top entry
converges on; dev-browser shows both in a small, readable codebase.

---

## 15. agentrhq/webcmd — 2,727★ — TypeScript — Apache-2.0

"Self-learning agent browser": generic live control plus a **memory layer** — each run loads
prior learnings, browses, then persists useful site knowledge for the next agent
(README: "load memory, use the live web, keep useful learnings"). Source shows the OpenCLI-style
adapter pattern grown up: `adapter-source/adapter-analysis/adapter-shadow/adapter-override`
modules — adapters are analyzed, shadow-tested, and overridable. Direction of travel across
this scan is consistent: agents accumulate *site procedures* as durable artifacts.

---

## 16. Planetary-Computers/autotab-starter — 1,006★ — Python — © Planetary Computers (no OSS license file found)

The **learn-from-demonstration** pattern (2023, early): `src/record.py` records a human
performing a task once (browser extension mirrors the session), turning the trace into a
parameterized agent; `src/play.py` replays it with an LLM supplying parameters and handling
deviations. Brittle to site redesigns, but for stable personal workflows (the JARVIS case —
same sites, same tasks, daily) a recorded procedure beats re-deriving actions every run:
zero planning tokens, human-verified steps. Pairs naturally with the adapter doctrine (§9).

---

## 17. lennybase/browsernode — 1,056★ — TypeScript — MIT

A faithful TypeScript port of browser-use (same layout: `src/{agent,browser,dom,controller,llm,
filesystem}`), keeping the injected-JS approach explicit: `src/dom/buildDomTree.js` runs inside
the page to detect interactive elements, with `clickable_element_processor/` and
`history_tree_processor/` mirroring the Python original. Third independent codebase on the same
indexed-tree design — the architecture is a standard now, implementations differ mainly in
runtime and packaging.

---

## 18. THUDM/AutoWebGLM — 930★ — Python — Apache-2.0

The academic ancestor of the indexed-tree pattern (KDD'24; repo is data/eval + tooling —
the 10B model itself ships as weights). `miniwob++/html_tools/`:
- `html_parser.py` — **HTML simplification**: parses the page, discards irrelevant subtrees,
  keeps operable elements and their local context, producing a compact HTML the small model
  can actually fit in context.
- `identifier.py:IdentifierTool` — labels kept elements with **alphabetic IDs** (A…Z, AA, AB…)
  in document order (or random), which the model cites to act — same contract as browser-use's
  `[N]`, a generation earlier and in letters.
- Ships benchmark suites (MiniWoB++, Mind2Web, WebArena, AutoWebBench) and a hybrid
  human/agent workflow: the model proposes, a human (or verifier) confirms high-stakes steps.
Lesson for v2: representation *simplification* was the whole game for a 10B local model in
2024; on Owais's 7B local brain the same discipline (aggressive pruning before the model
sees anything) matters even more.

---

## 19. hangwin/mcp-chrome — 12,498★ — TypeScript — MIT

MCP server implemented as a **Chrome extension + native messaging host** (`app/chrome-extension`,
`app/native-server`): any MCP client (Claude Desktop/Code, JARVIS later) gets tools over the
user's *real* Chrome — tabs/windows, navigation, screenshot, content extraction, network
activity capture, bookmarks/history access — inheriting the user's logins with no separate
browser at all. No agent loop of its own; it is the "hands" layer, like browser-control (§13)
but speaking MCP and living inside the daily-driver browser.
**Steal verdict:** the MCP-over-real-Chrome bridge is the lowest-friction route to Vision-level
access for v2's future web skill: one extension, user's own session, tool surface already
standardized. (Trust note: history/bookmark tools make DCL classification of outputs essential.)

---

## 20. reworkd/tarsier — 1,771★ — Python — MIT

Perception utilities from the AgentGPT team, for the vision end of the spectrum:
- **Screenshot tagging (Set-of-Marks)**: interactable elements are visually overlaid on the
  screenshot with bracketed IDs (`[23]`), and Tarsier returns the tag→element mapping so the
  model answers `CLICK [23]` and the harness resolves it to the real element.
- **OCR text extraction** gives even a text-only LLM the page's visual text layout
  (what is where), bridging models without vision.
Design note: tagging is done by *drawing on the screenshot itself* — the ID space lives in
image pixels, complementary to DOM indices; it survives canvas/custom-rendered UIs where the
DOM is meaningless, at the cost of OCR/vision dependence.

---

## 21. nottelabs/notte — 2,041★ — Python — **SSPL-1.0 → ideas only**

Browser infrastructure rather than an agent: local Playwright-based sessions that turn pages
into "actionable observations and clean markdown", scraping to Markdown or **Pydantic-schema
structured data**, plus a cloud tier (stealth sessions, proxies, CAPTCHA solving — paid, and
again outside JARVIS rules) and **secrets vaults**: emails/passwords/MFA tokens/cards are held
in a vault and injected at action time so credentials stay out of automation code — the same
placeholder philosophy as §1/§4, productized. Functions deploy a Python automation as an API/
scheduled job. The open-core conversion (page → observation/markdown) is the reusable design.

---

## 22. unclecode/crawl4ai — 85,883★ — Python — Apache-2.0

The extraction end of the field (no acting): page → LLM-ready data.
- **"Fit Markdown" filters** (`PruningContentFilter` — DOM pruning by text density/structure;
  `BM25ContentFilter` — keeps only content relevant to your query, BM25-scored;
  `LLMContentFilter` — model-graded boilerplate removal). Query-conditioned pruning is the
  read-side twin of LaVague's retriever: never feed the model the whole page.
- **Deterministic extraction strategies**: `JsonCssExtractionStrategy`, `JsonXPathExtractionStrategy`,
  `RegexExtractionStrategy` — once a schema exists, extraction runs with **zero LLM calls**;
  `generate_schema` has an LLM write the schema once from a description; `LLMExtractionStrategy`
  covers the long tail with typed JSON output.
- Deep crawl (BFS/DFS/best-first) with crash-recovery state, adaptive crawling that stops when
  the query is answerable, topic/regex/sentence chunking for RAG.
**Steal verdict:** BM25/pruning filters + schema-once-extract-forever is directly implementable
in stdlib Python (BM25 is ~40 lines; JARVIS's knowledge skill already does FTS5 ranking) — this
is how v2's `web_fetch` should evolve for "Vision-level internet access" on a budget.

---

## 23. browserbase/stagehand — ★ (large; see sweep) — TypeScript/Python — MIT

Framework built on three verbs, each mapping to one sub-problem:
- `act("click the sign in button")` — NL action, grounded at runtime; **self-healing**: if the
  cached selector breaks after a site redesign, it re-grounds instead of failing.
- `observe("find the email input")` — returns **real selectors, not values**: the README's own
  example stresses credentials therefore *never reach the model* (harness code fills the field).
- `extract({schema})` — schema-validated structured output (Zod/Pydantic).
- Action caching: successful groundings are cached so repeat runs skip the LLM (deterministic
  replay of known flows — the adapter doctrine again, auto-generated).
**Steal verdict:** the act/observe/extract verb split + observe-returns-selectors secret hygiene
+ grounding cache. As a protocol design for v2's web tools it is the cleanest small API in the scan.

---

## 24. magnitudedev/browser-agent — 4,134★ — TypeScript — Apache-2.0

The vision-first pole: **no DOM representation at all** — a visually grounded LLM looks at the
screenshot and specifies **pixel coordinates**; a planner/executor split keeps high-level
reasoning separate from the grounding model that emits x/y. Strengths: works on canvas,
WebGL, and hostile DOMs where trees lie. Weaknesses (visible across this scan wherever pure
vision is used): coordinate drift, no stable element identity between steps, expensive
verification. Included as the deliberate counter-design to §1 — the field's center of gravity
is hybrid (tree first, vision as fallback), not vision-only.

---

## 25. hyperbrowserai/HyperAgent — 1,598★ — TypeScript — **AGPL-3.0 → ideas only**

Playwright "supercharged with AI": two APIs — `page.perform()` for single granular NL actions
and a task-level API for multi-step flows — plus **Action Caching: record a workflow once,
replay it deterministically with no LLM calls**. Fourth independent sighting of the same
pattern (OpenCLI adapters, Stagehand grounding cache, autotab record/play, webcmd memory):
*successful agent behavior gets compiled into deterministic procedures.*

---

## 26. steel-dev/steel-browser — 7,845★ — TypeScript — Apache-2.0

Browser *infrastructure* API (self-hostable): managed Chrome sessions over CDP with state
(cookies/localStorage) persisted across requests, proxy-chain management, stealth plugins +
fingerprint management, live session viewer for debugging, and utility endpoints
(page→markdown/readability/screenshot/PDF). No agent brain — it's the layer agents rent.
For JARVIS the relevant design point is the session API shape: create → connect (any driver)
→ release, with state surviving between tasks.

---

## 27. h4ckf0r0day/obscura — 29,064★ — Rust — Apache-2.0

A from-scratch headless browser engine in Rust (real V8 JavaScript, CDP server, drop-in
Puppeteer/Playwright replacement) with stealth rendering built in rather than patched on.
Relevant as infrastructure: if an agent framework needs a browser that isn't Chromium,
the interface contract everyone targets is CDP — Obscura, Lightpanda, Moli and Chrome all
converge on it, which is precisely why v2 designs should target protocols, not products.

---

## 28. lightpanda-io/browser — 36,765★ — Zig — **AGPL-3.0 → ideas only**

Another from-scratch headless browser (Zig), claiming ~16× less memory and ~9× faster page
loads than headless Chrome on their 100-page benchmark (vendor numbers, unverified here).
No rendering/GUI — DOM + JS only — so vision/screenshot agents can't use it; tree-based
agents can. Its existence (with Obscura and Moli) signals the market's verdict: agent traffic
is big enough to justify new browser engines optimized for machines, not eyes.

---

## 29. lexmount/moli — 19,734★ — Rust — (license in repo)

Headless browser for agents with the slogan **"Structure first. Pixels on demand"**: layout
and paint are computed *on demand* (skipped for pure extraction/structure reads, rendered
when coordinates/screenshots are requested) — an engine-level version of the same economy
the representation layer fights for. Interfaces: CLI, CDP, WebDriver Classic and BiDi.

---

## 30. platonai/Browser4 — 1,164★ — Kotlin/JVM + Rust CLI — Apache-2.0

"AI-native browser engine" from the PulsarRPA lineage. Distinctive pieces:
- **Zero-Token Extraction**: X-SQL (SQL-like queries over the DOM) + CSS selectors for
  deterministic extraction; **WebMiner** ML clustering turns page corpora into spreadsheet/
  report views with no LLM tokens at all.
- **Progressive experience store**: learned selectors and blocker-handling are stored and
  reused across runs — site-procedure memory again (cf. §9/§15/§25), here inside the engine.
- Agent surface via Rust CLI + MCP (navigate/click/fill/snapshot/batch/loop) over real browsers.
**Steal verdict:** X-SQL-style declarative DOM queries are a stdlib-feasible middle ground
between raw HTML dumps and LLM extraction (Python has html.parser; a tiny selector engine
is realistic) — worth a spike for v2's web skill.

---

## 31. citrolabs/ego-lite — 17,865★ — JavaScript — MIT

A browser *designed to be shared*: the human browses in their space while agents work in
isolated **Spaces** inside the same browser — real logins/tabs reachable, the user's tabs
never stolen (the productized form of BrowserSkill's Agent Window, §8).
Two transferable design choices:
- **Code-based control, not CLI round-trips**: capabilities are in-page JavaScript functions
  (snapshot/fill/click/wait/navigate/capture); the agent writes *one snippet composing the
  whole multi-step task* instead of call-observe-call loops — fewer tokens, fewer failure
  points. (Same conclusion as OpenGCUA's one-program-per-step, reached independently.)
- Engine-level snapshot customization, marketing-claimed strongest on **deeply nested
  iframes** — the case every tree serializer struggles with (cf. §7 frame-prefixed bids).

---

## 32. feder-cr/invisible_playwright_mcp — 2,773★ — Python — (license in repo)

Anti-detect as an MCP server: drives a hardened Firefox build; the identity model is
**seeded end-to-end** — "seed → fingerprint → preferences, proxy and geolocation" — one seed
generates a mutually consistent persona (the consistency principle of §6 taken furthest).
Positioning is explicit: "Other AI browser agents get captchas." JARVIS note: useful evidence
about what detection actually checks (cross-signal consistency), not a component to adopt —
deliberate bot-evasion sits outside the owner's rules for his own assistant's behavior on
sites he uses; the honest agent paths remain real-browser or public APIs.

---

## 33. vibheksoni/stealth-browser-mcp — 3,091★ — Python — (license in repo)

The maximalist MCP tool surface: **101 tools / 11 sections** over CDP, including two ideas
absent elsewhere in the scan:
- **Dynamic hook system** — restricted Python hooks that can intercept, block, redirect,
  fulfill, or modify request/response flows mid-session (network-level agency: stub an API,
  capture a payload, kill a tracker — powerful for testing/debugging workflows).
- **Pixel-accurate element cloning** — extract an element with its CSS, DOM structure, events,
  animations and assets (page archaeology / design theft / test fixtures).
Plus the input duality everyone converges on: instant CDP paste for bulk text vs human-like
keystrokes when the site watches typing.

---

## 34. remorses/playwriter — 4,016★ — TypeScript — MIT

Extension-relay design: connects agents to **your already-running Chrome** (logins, extensions,
cookies intact — "other browser MCPs spawn a fresh Chrome: no logins, instantly flagged,
double the memory"), exposing the **full Playwright API** through stateful sandbox sessions
that execute Playwright snippets (`session new` → id → run code against that session).
Closest relative: mcp-chrome (§19); playwriter's distinguishing choice is exposing a real
programming API (code in a persistent session) instead of a fixed tool list — the
power/flexibility end of the MCP spectrum.

---

## 35. AIPexStudio/AIPex — 1,272★ — TypeScript (extension) — MIT

In-browser agent positioned on privacy and zero migration ("lives in your existing browser;
alternative to Manus Browser Operator"): combines tab/history management with an automation
agent over the user's real session. Representative of the extension-agent cluster (§3, §19,
§34); its differentiator is bundling browser *organization* (tab/history tools) with acting,
so the agent can clean up and navigate the user's actual browsing context.

---

## 36. refreshdotdev/web-eval-agent — 1,233★ — Python — (license in repo)

A vertical use of the stack: an MCP server whose browser-use-powered agent **autonomously
tests and debugs web apps from the code editor** — it captures network traffic (intelligently
filtered before entering the context window), console errors, and screenshots, so the coding
agent can "debug itself". Evidence that browser agents' second career is QA/verification,
and that **filtered network+console capture** is a perception channel in its own right
(the page as the app sees it, not as the user sees it — cf. §33 hooks).

---

## 37. kalil0321/reverse-api-engineer — 1,414★ — Python — (license in repo)

The endgame of the adapter doctrine: **don't automate the UI at all.** The agent (or human)
browses while the tool observes the site's real network calls, then generates a clean,
typed API client for the endpoints the site actually uses. Every later call is a direct API
request — fastest, cheapest, most robust "browser automation" is the kind that stops
browsing. For JARVIS: when a repeated web task matters, graduate it from agent loop →
observed-API adapter; keep the browser for discovery and for sites whose APIs are hostile.

---

## 38. wy-coliney/jev-browser-use — 1,297★ — TypeScript (Skill) — (license in repo)

Explicit division of labor, sold in the tagline: "**Jev clicks. Codex thinks and verifies.**"
A fast deterministic executor (TypeSafe's Jev) performs navigation/clicks/toggles/scrolls
over the existing browser connection (claimed 5–10× faster operations in their workflows),
while the LLM keeps only text input, visual judgment, and the final verification. Ships as a
Skill for coding agents. This is §1's pattern (heuristics ground, model judges) reorganized
as two cooperating systems — and a reminder that most browser *operations* never needed a
model in the loop at all.

---

## 39. Saik0s/mcp-browser-use — 970★ — Python — (license in repo)

browser-use wrapped as an MCP server. Its durable lesson is operational: browser tasks run
30–120 s+, and **MCP stdio transports time out and drop mid-task** — so it runs as a
persistent HTTP daemon. Any v2 design that exposes browser control over MCP/RPC must budget
for long-running actions (async task handles, progress, cancellation), or it will fail
exactly at the interesting tasks.

---

## 40. browser-use/web-ui — 16,618★ — Python (Gradio) — (license in repo)

The reference UI over browser-use: Gradio front-end exposing the agent with pluggable agent
types (default, custom, and a **deep-research agent** mode that plans searches, reads sources,
and compiles a report — the pattern Owais's own research workflow uses). Confirms the layering:
engine (§1) is the product; UI is interchangeable skin. For JARVIS v2 the same holds — chat GUI
today, voice later, one brain underneath.

---

## 41. TIGER-AI-Lab/ClawBench — 1,082★ — Python — (license in repo)

Benchmark, included for its task design: "Can AI Agents Complete Everyday Online Tasks?" —
real, everyday tasks (shopping, reservations, form-filing) on **live websites**, graded by
outcome. Together with Mind2Web (§42) it defines what "works" means in this field: not demo
tasks on toy sites, but messy real flows with logins, popups, and pagination. Any future
"JARVIS browsed successfully" claim should be measured on tasks of this shape.

---

## 42. OSU-NLP-Group/Mind2Web — 1,037★ — Python — research code/dataset (license in repo)

The canonical generalist-web-agent dataset: 2,000+ open-ended tasks across 137 real websites /
31 domains with crowdsourced human action sequences; the raw dump ships **full traces** (HTML
snapshots + actions) and Multimodal-Mind2Web pairs every HTML document with its screenshot.
Historically important because its baseline (MindAct) established the two-step pattern —
**filter the DOM to candidate elements first, then let the model choose among them** — that
LaVague's retriever (§2) and browser-use's pruning (§1) industrialized.

---

## 43. Fosowl/agenticSeek — 27,514★ — Python — **GPL-3.0 → ideas only**

"100% local Manus": a fully local, voice-enabled assistant (local models via Ollama-class
runtimes) that browses, codes, and plans with **specialized agents routed by task type**
(web agent, coding agent, planner) instead of one generalist loop. For JARVIS the routing
idea is the steal: cheap local specialists first, expensive general reasoning only when the
router says so — the same economy as v2's FAST/CHAT split in the brain chain.

---

## 44. lmnr-ai/index — 2,437★ — Python — (license in repo)

Laminar's "Index" browser agent: turns any website into "an accessible API" and is notable
less for its loop than for **observability as a feature** — full agent tracing (every step,
observation, and action inspectable in their open-source Laminar platform; browser-use's
`act()` Laminar spans, §1, come from the same ecosystem). Debugging agents in production is
a tracing problem before it is a modeling problem; v2's session-store event log is the seed
of the same capability.

---

## 45. firecrawl/firecrawl — 193,166★ — TypeScript — **AGPL-3.0 → ideas only**

The hosted data layer of the ecosystem (and already connected in Owais's setup as a custom
connector): scrape/crawl/search endpoints returning clean Markdown or schema-shaped JSON.
Its role in this scan is taxonomic: for *reading* the web at scale, dedicated extraction
infrastructure beat agent loops on every axis — agents are for *acting*. JARVIS uses
Firecrawl-shaped tools for reading and reserves agent loops for interaction (§37's lesson).

---

## 46. browserable/browserable — 1,207★ — JavaScript — (license in repo)

Self-hostable browser-automation library for agents (navigate/fill/click/extract), advertising
90.4% on WebVoyager (vendor-reported). A compact generalist framework — useful mainly as one
more data point that the framework layer has commoditized: representation + loop + tools are
table stakes; differentiation has moved to sessions, stealth, verification, and memory of
procedures (the themes of the synthesis below).

---

# SYNTHESIS — Team 13

**Coverage:** 46 repos/systems examined. Deep code reads (full core files): browser-use,
LaVague, nanobrowser, Skyvern, BrowserGym, OpenCLI, BrowserSkill, browserbee, agentql,
openbrowser, browser-control, dev-browser, webcmd, autotab-starter, browsernode, AutoWebGLM,
mcp-chrome. README+structure-level (marked as such in entries): the remaining 29.
Method note (honest): mid-scan the GitHub API hit HTTP 429 and the sandbox blocked git's
shallow-clone lockfiles; reads were completed via a mix of full fetches, repo tarballs, and
API file reads. No mechanism above rests on marketing copy alone where a code path exists —
vendor benchmark numbers are labeled as vendor claims.

## Top 5 mechanisms (the field's convergent design)

1. **The indexed, pruned, hybrid DOM+AX text tree.** Every serious system distills the page
   (CDP DOMSnapshot + accessibility tree), prunes invisible/occluded/boilerplate nodes,
   expands compound widgets, and hands the model a text tree where each actionable element
   carries a stable handle — `[12]` (browser-use), `bid` (BrowserGym), letter labels
   (AutoWebGLM), `@e2` (agent-browser/dev-browser/browser-control). New-since-last-step
   elements are explicitly marked. Screenshots/SoM are the fallback for canvas-class pages.
2. **Verification instead of trust.** Actions return *effect verdicts* with signals
   (nanobrowser receipts); typed values are read back and mismatches reported (browser-use);
   completion is judged by a separate check (browser-use judge, Skyvern goal-check,
   BrowserGym's first-class `report_infeasible`); covered/occluded click targets are named
   in the error (agent-browser).
3. **Closed-world grounding.** The model may only act on targets the perception layer
   emitted — LaVague verifies xpaths against the authorized set and raises on hallucinated
   ones; Stagehand's `observe` returns selectors the harness executes; AgentQL collapses
   grounding into one atomic `get_by_prompt` call.
4. **Secrets never enter the model.** Placeholder substitution at dispatch (browser-use
   `<secret>` tokens), opaque tokens for signed URLs (Skyvern), selector-only observation
   for credential fields (Stagehand), vault injection (Notte) — four implementations of one
   rule, identical in spirit to v2's DCL SECRET tier.
5. **Success compiles into procedures.** Action caching with self-healing selectors
   (Stagehand, HyperAgent), deterministic per-site adapters (OpenCLI's hundreds of `clis/`,
   webcmd's adapter-shadow system, Browser4's experience store), and record/replay
   (autotab). The agent loop is the *compiler*; deterministic code is the *runtime*.
   Recurring tasks should graduate out of the loop.

## Sessions & anti-bot — the honest summary
- **Auth:** nobody logs in programmatically if they can avoid it. Winners either drive the
  user's real browser (extension/relay: nanobrowser, mcp-chrome, playwriter, BrowserSkill,
  ego-lite — inheriting logins, with borrowed-tab/Agent-Window etiquette) or persist a real
  Chrome profile (browser-use, Skyvern). Credential *vaults with placeholder injection* are
  the accepted pattern when credentials must be supplied.
- **Anti-bot:** an engine-level arms race — C++-level fingerprint spoofing (Camoufox),
  seeded whole-identity generation (invisible_playwright), rented stealth clouds
  (browser-use cloud, Notte, Steel). Open-source local agents get blocked; CAPTCHA solving
  exists only as a paid/cloud feature (Skyvern, Notte) or third-party solver integration.
  **Implication for JARVIS (already the owner's rule):** no CAPTCHA solving, no evasion
  tooling — attend Owais's own browser/session or use official APIs and public pages.

## Top 3 steals for JARVIS v2 (stdlib-only lens)
1. **Adopt the representation protocol as v2's web-perception standard** — pruned indexed
   tree, ~40k-char cap, page-stats header, `*` new-node marks, frame-prefixed IDs. Two
   implementation tiers, both stdlib-feasible today: (a) static/server-rendered pages via
   `html.parser` + the crawl4ai playbook (pruning + BM25 query filter — §22) to upgrade
   `web_fetch`; (b) dynamic pages later via his real Chrome over CDP (the protocol is
   driver-agnostic by design — §5/§19/§34).
2. **Port nanobrowser's guard layer into v2's ReAct brain** — call signatures, repeat
   window/limit, no-effect nudge→stop, one salvage call (§3). Pure stdlib logic (~80 lines),
   and it fixes loop failure modes for *every* tool JARVIS owns, not just web tools.
   Pair with browser-use's post-input value read-back for any future form filling.
3. **Placeholder-secret web actions + batch form-plan** — when v2 fills any form: plan all
   field values in ONE model call with exact-option-label discipline (Skyvern §4), resolve
   secrets/placeholders at dispatch through v2's existing Secrets store (never into the
   transcript), and return effect verdicts per field. This extends v2's DCL/gate design to
   the web without new machinery.

*End of Team 13 report.*
