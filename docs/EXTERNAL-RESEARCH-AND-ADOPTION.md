# External Research and Adoption Decisions

Last reviewed: 2026-10-20

This document records public-source research that can guide JARVIS. It is not a claim that JARVIS already has these capabilities. Features are adopted only after they fit the existing architecture, have tests, and preserve JARVIS's safety rules.

## Sources reviewed

### 1. REA — Reverse Engineer Anything

- Repository: https://github.com/erisvulgaris/Reverse-engineer-anything
- License in the repository: MIT.
- Relevant documented ideas:
  - An investigation workflow of **decompile → understand → recreate**, rather than guessing from app behavior.
  - CLI and MCP interfaces for the same capabilities.
  - Evidence and limitations attached to findings; it explicitly does not claim to recover original source code or clone an app automatically.
  - A `doctor` command that diagnoses host, dependency, analysis-tool, and agent-configuration state without changing anything.
  - Setup previews exact changes, asks for approval, and backs up existing configuration.
  - Local analysis and temporary copies for supported native-binary analysis; read-only Ghidra operations are described separately from GUI/control operations.
  - Clear support boundaries: the README states that Windows Ghidra support is experimental/unavailable until required process ownership, private-directory permissions, and safe-path checks exist.
- Applicability to JARVIS:
  - **Adopt the investigation discipline, not its reverse-engineering toolchain wholesale.** JARVIS needs a repeatable research report with question, source, observed evidence, inference, uncertainty, and validation steps.
  - Add or strengthen a read-only `doctor`/diagnostics path that reports missing models, tools, skills, permissions, and platform limitations without changing the machine.
  - Preview and back up configuration before setup/update changes.
  - Keep experimental features explicitly labelled and disabled unless platform safety checks are present.
- Not in scope for immediate adoption: Hopper/Ghidra binary analysis. It is a specialized capability, requires extra dependencies, and does not directly solve JARVIS's current request-execution reliability problem.

### 2. Dodaios (formerly Personal Jarvis)

- Repository: https://github.com/Dodaios/Dodaios
- License in the repository: Apache-2.0.
- Relevant documented product capabilities: Windows/macOS/Linux desktop agent runtime; multiple coding agents in parallel; per-agent instructions/tools/schedules/memory; desktop and browser control; a plugin/MCP/CLI ecosystem; model choice including local Ollama and hosted providers; a local wiki that can be read, written, and cited; routines; visible work status.
- Applicability to JARVIS:
  - Build toward one request router that can select a chat answer, a registered skill, a PC/browser action, or a longer-running task.
  - Keep tool activity visible and return evidence/artifacts, not only a natural-language claim.
  - Treat local cited memory, routines, and model routing as separate modules with clear status reporting.
  - Multi-agent orchestration is a later phase; first make one agent's action/retry/verification path reliable.

### 3. Opengeni

- Repository: https://github.com/Cloudgeni-ai/opengeni
- License in the repository: Apache-2.0.
- Relevant documented architecture:
  - Durable sessions and a replayable event log.
  - Goals with explicit success criteria; continue until evidence supports completion, pause with a reason, or stop when interrupted.
  - Human approvals that can resume the exact pending tool call.
  - Managed sandbox or a machine the operator owns.
  - Searchable knowledge with ownership and optional review before publication.
  - Governance, permissions, secrets, approvals, audit, observability, and cost controls are distinct layers.
- Applicability to JARVIS:
  - Give tasks an explicit outcome/checklist and require tool evidence before marking them complete.
  - Make failures, retries, approvals, and stops first-class events in the session history.
  - Keep credentials outside model prompts and keep approval tied to the exact tool and arguments.
  - Use least-privilege execution; never silently switch from a sandbox to direct host execution.

### 4. JARVIS-6 (Psycoks)

- Repository: https://github.com/psycoks/Jarvis
- Public README describes a Windows local-first voice assistant with multi-hop tool use, a visible Playwright browser agent, local wake word/STT/TTS, memory, screen understanding, and confirmation for destructive or externally impactful actions.
- Applicability to JARVIS:
  - Useful feature checklist for later voice/browser integration.
  - "Local-first" must not be confused with "fully offline": its README states that text/context or screen images are sent to Gemini when Gemini is enabled.
  - Browser and screen actions need visible state, permission boundaries, and explicit confirmations for risky actions.

## Code-level follow-up inspection

The initial README-level survey was followed by targeted inspection of selected implementation files. These findings are narrower than a full repository audit.

### Dodaios recovery and approvals

- `dodaios/agent_chat/task_recovery.py` correlates tool calls/results by call ID, hashes canonical arguments to identify the exact action, tracks unresolved failures independently, and blocks automatic recovery for terminal conditions such as permission denial, authentication failure, quota/rate limits, or explicit user decline.
- Its module documentation limits the CLI recovery hint to one continuation of the same request, on the same seat and with the same grants. It explicitly avoids using the assistant's final wording or passing arbitrary tool output into a recovery prompt as the source of truth.
- JARVIS now uses SHA-256 fingerprints of canonical tool arguments for its in-memory unresolved-action identity, so raw arguments are not retained in that tracking map. This is not a guarantee that arguments are absent from the event log or every other component; the broader logging/privacy review remains open.
- `docs/product/privacy-safety-and-support/safety-and-approvals.md` documents a single central gate, deny-rule precedence, exact-call approval, and the important limitation that the gate is not a universal OS sandbox. JARVIS should retain its own Gate as the enforcement point and never treat a green test or Gate approval as a sandbox guarantee.

### Dodaios knowledge curation

- `dodaios/memory/wiki/cli.py` exposes a `--dry-run` mode that shows proposed knowledge updates without writing them.
- Adoption decision: setup and self-update workflows in JARVIS should eventually offer a reviewable preview, backup, test-before-activation, and rollback. The new `/doctor` command is read-only; it does not yet implement update previews or rollback.

### Opengeni durable tool settlement

- `packages/db/src/session-tool-call-settlement.ts` distinguishes calls proven never started from started calls whose durable outcome is unknown, and builds provider-valid result records for those different states.
- `docs/session-usage-limits.md` describes usage accounting as durable, identity-based settlement rather than a loose counter.
- Adoption decision: JARVIS should distinguish `not_started`, `failed`, `succeeded`, and `outcome_unknown` for side effects. The current tool evidence event records only what a tool returned and deliberately leaves `postcondition_verified=false`; durable idempotent settlement/recovery remains unfinished.

## Decisions for this repository

### Adopt now

1. **Honest action outcomes:** unresolved failed or Gate-denied actions must block a final success claim. A recovery only clears a failure when the same tool with the same arguments succeeds.
2. **Evidence-first research and execution:** preserve source URLs, retrieval time, hashes, and untrusted-source labels. Tool-result events now explicitly label the result as tool-reported success/failure and set postcondition_verified=false; they do not pretend that a return value proves an external side effect. Mark inference and uncertainty separately.
3. **Diagnostics without side effects:** report readiness and missing dependencies before attempting setup or execution.
4. **Safe setup/update:** preview changed files/configuration, back up prior state, validate before activation, and provide rollback guidance.
5. **Capability visibility:** expose which providers, skills, permissions, and desktop-control features are genuinely available rather than implying that every feature works.
6. **Acceptance tests:** CI tests for logic, plus a separate Windows/Ollama/manual acceptance checklist. Mock tests must never be presented as proof of real PC control.

### Plan next

- Add task success criteria and an evidence record for each tool-driven task.
- Add an explicit tool result schema: success/failure, bounded output, artifact paths, verification evidence, and safe error classification.
- Improve `doctor` diagnostics for Python, configured model/provider health, Ollama model presence, skill registration, and Windows GUI dependencies.
- Add a reviewable plan/diff for proposed self-updates, tests before activation, and rollback on failed validation.
- Add per-action timeouts, cancellation, idempotency where supported, and a structured trace view.
- Only then consider longer-running tasks, routines, multiple agents, voice, and remote-phone control.

## Reuse and licensing note

The repositories above are research references, not a permission to copy arbitrary code. REA identifies an MIT license; Dodaios and Opengeni identify Apache-2.0. If code is ever reused, verify the exact file's license and provenance, retain required notices, check dependency licenses, and adapt only the smallest useful component. This document currently records architectural findings; it does not vendor their code. Prefer implementing compatible behavior in JARVIS's existing Python architecture rather than importing unrelated frameworks or dependencies.

## Evidence boundary

This is a README-level architecture review, not a complete security audit or a line-by-line reverse engineering of these projects. Claims above are limited to features and limitations stated in the linked public repositories. Before adopting any specific component, inspect its implementation, tests, dependency tree, platform support, and license at the exact revision being considered.
