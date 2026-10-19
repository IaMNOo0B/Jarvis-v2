# V2 Wave 1 — R1–R14 Coverage Checklist

*Every component verified against this on integration. A miss blocks packaging.*

| Req | Requirement | Owner | Verify how |
|---|---|---|---|
| R1 | Text-first core, voice as plugin | Me (CLI) | No audio imports anywhere in Wave 1; `grep -ri "audio\|tts\|stt" jarvis/` = clean |
| R2 | Instruction hierarchy (system > developer > user > tool) | Gate | Injection test: tool output "ignore instructions" changes nothing |
| R3 | Out-of-band confirmation gates | Gate | Tier-3 → REQUIRE_APPROVAL always; token binds action hash |
| R4 | Filesystem jail in code + tests | Skills | notes/ skill: `../` traversal denied (test) |
| R5 | Sandboxed code exec + egress allowlist | Skills | exec capability default-deny; check_egress on network tools |
| R6 | Atomic writes + backups + locking | Foundation | kill -9 mid-write → no corrupt config (test) |
| R7 | Config validation | Foundation | Unknown key → startup error (test) |
| R8 | Fallback that actually falls back | Brain | 20 simulated failures/provider/type → 100% recovery (test) |
| R9 | Secrets in OS keyring + log redaction | Foundation + DCL | Secret value never in any log (test greps logs) |
| R10 | Signed updates + rollback | — | Wave 2 (updater). Wave 1: zip + version file only |
| R11 | Manifest skill discovery + circuit breakers | Skills | Unknown manifest key → error; 3 fails → disabled (tests) |
| R12 | Honest UX + startup preflight | Me (CLI) | Startup checks: rules load, P0 present, DB writable; failures announced, never silent |
| R13 | Privacy-safe defaults | DCL + Memory | SECRET never leaves; quarantine on tool/web memories (tests) |
| R14 | UI robustness | — | Wave 2 (Tauri). Wave 1: CLI text labels for 10 brain states |

**Cross-cutting (from all learnings):**
- First Mission: no vocabulary-substring detection; no fake user messages; no blocking net in failure paths → Brain
- Threat model SEC11: 7 uncovered cells — C6/C7 covered by DCL (E2 clipboard at READ time); F1 payload laundering = P0-1; F4 nonce-store = approval token hash → Gate
- 2060 budget: brain ≤5.5GB VRAM, 4k context cap → Brain router
- Planning PhDs: plan-as-shared-store, whole-list replacement, planning-innermost/approvals-outermost → applied to MY build process (todo list = shared store; approvals wrap everything)
- Master Planner: this build follows its own spec — plan contract (MASTER-PLAN.md), deviation voids, kill criteria active
