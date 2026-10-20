# JARVIS v2 — Implementation Gap Audit

**Snapshot:** 2026-10-20  
**Branch reviewed:** fix/gui-quit-and-stale-launch-lock  
**Purpose:** Compare the research/architecture book against the actual repository. This is an implementation audit, not a claim that JARVIS is production-ready.

## Executive verdict

The repository is a meaningful Python prototype with a real chat loop, provider fallback, manifest-based skills, a safety gate, SQLite memory/session storage, a Tkinter GUI, and optional desktop/phone/voice modules. It is not yet the complete product described by the knowledge book. Passing unit tests proves the tested code paths, not that the installed model, Windows UI automation, or the full user journey works on Sir's PC.

Windows CI on commit `549e8cac8f1421687ca5a7740197afe6d71c656c` reported **574 passed, 3 skipped**. Tests use fakes/mocks for external models, web calls, and platform-sensitive behavior, so even a green CI run is not a real-model or real-desktop acceptance test.

## Important mismatch in the source documents

- knowledge/learn-chat-ui-spec.md exists in the repository, but knowledge/learn-v2-master-map.md still says the chat UI has no spec. Refresh that map.
- MASTER-PLAN.md still says the repository has not been created and GitHub pushes are blocked. Those statements are stale.
- The research book labels its work as design/research and explicitly says its proposed targets are unmeasured. Do not treat research completeness as implementation completeness.
- The specified primary UI is Tauri 2 + React with a Python sidecar and SSE. The current app uses a Python/Tkinter GUI and has no src-tauri, React frontend, or package manifest. Tkinter can remain a useful interim interface, but it is not the architecture in the UI spec.

## Capability-by-capability status

| Area | Current evidence in repository | What still needs to happen |
|---|---|---|
| Chat and provider fallback | jarvis/chat.py, jarvis/brain.py, Ollama/cloud provider adapters, /status and read-only /doctor; local Ollama is ordered before cloud fallbacks | Verify on Sir's PC that the configured Ollama model name exists, the provider actually answers, fallback works during a real outage, and responses are not silently coming from the stub |
| Request fulfillment / tools | Manifest-driven skills, schema validation, Gate, approvals, code/notes/clock/web/knowledge skills, PC-control tool definitions; Brain treats registry-style `{ok:false,...}` results as failures, counts every actual execution attempt against the hard cap, retains unresolved failures by exact tool name plus arguments, and records whether a result is only tool-reported or independently verified | Add a real-provider acceptance suite for natural-language requests → correct tool → observable result → truthful final response; exercise multi-step tasks, failures, retries, and STOP on Windows |
| Internet research | web_search, web_fetch, web_learn, learning_search; web notes include source URLs, retrieval time, hashes, and untrusted-source labels; private/local destinations are blocked in URL validation | Test real public websites and redirects on Windows; add source-quality/conflict handling, clear citations in answers, and size/rate limits for repeated research |
| Learning / memory | SQLite facts + episodes, full-text recall, provenance/quarantine for facts; recalled snippets are now passed as explicitly untrusted tool evidence, not injected into system instructions. Automatic episode capture is opt-in and off by default; conservative filters skip obvious credentials, contact identifiers, and some injection patterns | The filter is not a privacy guarantee. Add user-reviewed capture/retention controls, provenance for episodes, and tested episode deletion/forgetting before broadening automatic capture |
| Self-critique | Existing critique module is now enabled through config for longer answers | Test whether it catches factual/tool-result errors and does not rewrite correct answers into worse ones; keep a bounded retry/call budget |
| Self-upgrade | Setup/update-related code and documentation exist | No verified, complete signed-update + staged-install + rollback lifecycle has been demonstrated. Build update checking, signature/hash verification, staged apply on restart, rollback, and user-visible approval. Never allow model output to directly install or replace code |
| Safety / approvals | Gate, risk tiers, action hashes, approval token logic, DCL, filesystem-jail and attack tests | Close the threat-model gaps: data classification before cloud sends, clipboard/secret handling, DNS-egress concerns, and remaining partial attack cases. Prove all side effects route through the Gate |
| Session store / recovery | SQLite event log, JSONL spillover, checkpoints, wake/recovery code and tests | Run crash/restart fault-injection against a live app; verify action idempotency and that events never falsely claim a side effect succeeded |
| Desktop control | UIA-first PC-control module and Gate tool definitions; fake backend tests | Real Windows tests across DPI/scaling, multiple monitors, elevated windows, stale element handles, keyboard navigation, click/type verification, and undo. No screenshot/OCR/VLM fallback should be claimed unless actually wired and tested |
| GUI | Tkinter GUI has message input/output, stop and approval-related plumbing | Build the persistent activity feed, clear state/status transitions, queued input, robust cancellation, and accessible approval presentation. Decide when to replace the interim Tkinter surface with the specified Tauri/React UI |
| Phone / proactivity / voice | Separate modules and unit tests exist; chat app has integration entry points | Verify each service starts/stops correctly, runs safely in the background, and survives restart. Keep voice last; do not let an optional voice failure break text chat |
| Setup / updates | Preflight checks, model-download helpers, config and update-check functions | Demonstrate a clean Windows install, re-run-safe setup, verified model assets, no-terminal onboarding, redacted diagnostics, and signed update/rollback behavior |
| Performance / quality | Test suite and hardware research notes | Run the RTX 2060 benchmark plan: latency, VRAM, model quality, tool-call accuracy, grounding, and failure recovery. Mark proposed targets as proposed until measured |

## Recommended build order

### P0 — Make current behavior honest and safe
1. Fix stale documentation and keep the repo's status map aligned with actual code.
2. Keep automatic episode capture opt-in by default; recalled memory is untrusted evidence, never system instructions. Continue adding privacy, retention, provenance, and deletion controls.
3. Make /status distinguish the provider chain from the provider that actually answered the last turn; clearly label stub/degraded mode.
4. Ensure every tool result is treated as untrusted evidence, every side effect passes through the Gate, structured tool failures count as failures, and unresolved failed actions force an honest stop until the same action succeeds on retry.

### P1 — Prove the core assistant end to end
1. Test real Ollama connectivity and exact installed-model selection on Windows.
2. Test ordinary chat, 10+ turns, memory recall, web search/fetch/learn, code creation and sandbox execution, and provider failover.
3. Test multi-step tasks with explicit per-step result verification, bounded retries, cancellation/STOP, and recovery after a crash.
4. Add a Windows smoke-test checklist and attach results to releases; mocked CI is necessary but not sufficient.

### P2 — Make it a dependable desktop product
1. Improve the current GUI's activity feed, status states, stop/cancel semantics, queued input, and accessible approvals.
2. Implement the specified Tauri 2/React frontend + localhost Python sidecar/SSE only after the backend contract is stable—or explicitly revise the architecture decision to keep Tkinter.
3. Finish setup/preflight, safe updates, signature verification, rollback, and redacted diagnostics.

### P3 — Extend capabilities after the core is reliable
1. Finish desktop-control grounding and real-machine verification.
2. Harden phone remote and proactive reminders with opt-in, scoped permissions, and durable scheduling.
3. Add voice as an optional plugin after text chat, tools, memory, and approvals are reliable.
4. Run the hardware/model benchmark plan and use measured results to tune routing and budgets.

## Definition of done

JARVIS is not “fully working” until all of these are evidenced:

- [ ] A real configured model answers; /status identifies the actual provider, and stub mode is unmistakable.
- [ ] Common natural-language requests choose the right tools and verify their observable outcomes.
- [ ] Multi-step work is bounded, cancellable, resumable where safe, and honest about partial completion.
- [ ] Web research stores attributable notes and later answers cite sources without obeying instructions from pages.
- [ ] Memory recalls useful context, quarantines untrusted material, and supports tested forgetting/deletion.
- [ ] All side effects pass through the Gate; destructive/external actions require the specified approval.
- [ ] A real Windows smoke test covers startup, chat, web, local model, stop, quit, restart, and PC control.
- [ ] Setup/update can recover from interrupted downloads or a bad update without losing a working installation.
- [ ] Hardware benchmarks and known limitations are published; no unmeasured number is presented as a guarantee.

**Bottom line:** continue from the existing repository rather than rebuilding blindly. First close the P0 privacy/trust and runtime-verification gaps, then prove real request fulfillment end-to-end. Do not start voice polish or claim autonomous self-upgrading before those gates pass.
