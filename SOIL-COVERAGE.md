# SOIL-COVERAGE — Jarvis Soil studies → JARVIS v2 code

Evidence-based mapping of every recommendation in `~/workspace/jarvis-soil/`
(7 study files, 2026-10-19) to its state in v2. Statuses:

- **implemented** — working code exists (file:line given; grep-verified)
- **partial** — a real subset exists; the gap is named
- **not-code** — cannot be code inside v2 (hardware buy, account, GUI or
  owner action); listed for the owner, never faked

New code from the Soil Implementation Team is marked **[SOIL]**:
`jarvis/maintenance.py` (new), five additive preflights in
`jarvis/setup.py` (opt-in `soil_extras=True`; the default 8 checks are
untouched), `tests/test_soil_*.py` (59 tests), and two deterministic
architecture tests that enforce the seed-viability DNA.

---

## hardware-requirements.md

| Recommendation | Status | Evidence / gap |
|---|---|---|
| RAM tiers (16 GB recommended; <8 GB = cloud-brain territory) | implemented [SOIL] | Health check `maintenance.py:263` (`_check_ram`) + preflight P12 `setup.py:463` (`_check_memory_size`) |
| Disk headroom for model + KV cache (10 GB floor) | implemented | Preflight P4 `setup.py` (`_check_disk_space`, blocking) + health `maintenance.py:245` (fail <2 GB, warn <10 GB) |
| GPU detection / tier advice | partial [SOIL] | `maintenance.py:198` probes `nvidia-smi` and reports the card in the health suite; no automatic model-size switching (brain territory) |
| Weekly reboot for 24/7 health (§5 checklist #5) | implemented [SOIL] | Uptime watchdog `maintenance.py:345` — warns past 7 days uptime |
| Temperature monitoring (§5 #7) | not-code | No stdlib sensor path on Windows; needs a hardware monitor tool (owner tooling) |
| UPS, dust, PSU, SSD-not-HDD (§5) | not-code | Physical owner actions |
| Buy a cardioid USB mic + external speakers (the $60 rule) | not-code | Hardware purchase (owner) |
| Cloud-brain mode when no GPU | implemented | Brain fallback chain ends at Ollama with keyed cloud first (`jarvis/brain.py:972` FallbackChain); mic/speaker quality is hardware (above) |

## software-api-data.md

| Recommendation | Status | Evidence / gap |
|---|---|---|
| Freeze Python on 3.11/3.12 (A1) | implemented [SOIL] | Preflight P9 `setup.py:336` (`_check_python_release_window`, warn-only); P2 already blocks <3.11 |
| VC++ 2015–2022 Redist check (A1, fresh-machine killer #1) | implemented | Preflight P1, pre-existing (`setup.py` `_check_vcpp_redist`) |
| Mic privacy toggle check (A2 breakage #1) | implemented [SOIL] | Preflight P10 `setup.py:373` (`_check_mic_privacy` + `_mic_consent_via_registry` :356, winreg-injected) |
| Never persist audio device indices; enumerate by name (A2) | partial | `jarvis/stt.py` territory (voice team); not re-verified line-by-line here |
| Non-ASCII path / HF_HOME hygiene (A5 #9) | implemented [SOIL] | Preflight P11 `setup.py:409` + health `maintenance.py:358` |
| Ollama health-check on startup, cloud fallback when down (A3) | implemented [SOIL] | Preflight P13 `setup.py:487` (loopback :11434, warn-only) + health `maintenance.py:379`; fallback itself is the brain chain |
| Log rotation under the data dir (A4) | implemented [SOIL] | `maintenance.py:632` `cleanup_data_dir` (logs pruned at retention) + log-pressure health item :320 |
| Keys in OS keyring, never in chat/logs/git (B4) | implemented | `jarvis/config.py:235` — keyring → Win Credential Manager (ctypes) → guarded fallback; verified |
| Provider quota behavior: 429 parking, per-day skip, no dead-provider hammering (B1) | implemented | `jarvis/brain.py:944` `classify_error` + FallbackChain parking :1067 (Builder A) |
| Free-Gemini training warning / ZDR on OpenRouter (B4/D2) | partial | DCL redaction exists (`jarvis/dcl.py`); the visible first-key warning is GUI work (chat_gui territory) |
| SQLCipher-encrypted history DB (C5) | not-code | Needs a non-stdlib cipher build; v2 is stdlib-only. Current posture: OS-account isolation + keyring-held secrets |
| Telemetry default OFF, per-crash preview (C6) | partial | No telemetry sender exists in v2 at all (nothing phones home) — the default is honored by absence; no crash-report pipeline either |
| Wake-word model training data (C1) / voice-clone data (C2) | not-code | Owner/Colab training job + installer payload; the wake adapter work is Extension Team 5's |
| 10-screen first-run wizard (C4) | partial | `setup.py` ships a 3-question wizard (name, data dir, models) + full preflight; the 10-screen GUI wizard is chat_gui/installer territory |
| Pin model versions; staged upgrades (also maint. §3.1) | partial | Model assets are SHA-256-verified against a manifest (P5, pre-existing); version pinning lives in that manifest, managed at release time |

## testing-deployment-maintenance.md

| Recommendation | Status | Evidence / gap |
|---|---|---|
| Circuit breaker on the provider chain (§2.2 #4) | implemented | brain.py FallbackChain parking (above) |
| Stage timestamps / latency p50-p95 (§1.6, checklist) | partial | `jarvis/observability.py` spans exist (PhD wave); a p50/p95 latency *view* is not built |
| CPU fallback when GPU init fails (§2.1) | partial | stt/llm territory; Ollama + whisper degrade paths exist but were not re-verified here |
| Re-enumerate audio devices; never cache IDs (§2.1) | partial | stt.py territory (voice team) |
| Mic-permission friendly card on startup (§2.1) | partial [SOIL] | Detection implemented (P10 above); the friendly GUI card is chat_gui territory |
| Updater rollback: 2 startup crashes → auto-revert (§3.5) | implemented [SOIL] (data-side) | `maintenance.py:720` `note_startup` / :762 `auto_recover` — crash-loop restores the newest backup, resets the counter. Code-version revert belongs to the Wave-3 signed updater (setup.py `check_updates` is still the documented stub) |
| Rollback safety: never lose current state on revert | implemented [SOIL] | `maintenance.py:566` `restore_backup` always takes a pre-restore snapshot first (:580 keep-guard so rotation can't eat the restore target) |
| Lockfile/CI discipline (§3.2) | partial | The pytest suite is the canary (800+ tests); v2 ships zero third-party deps, so dependency rot is structurally minimal |
| Wake-word FPPH/recall + STT WER + TTS regression harnesses (§1.3–1.5) | not-code (yet) | Need recorded clip sets from the owner's voice/room — data collection is an owner session, then harnesses become tests |

## security-protection.md

| Recommendation | Status | Evidence / gap |
|---|---|---|
| Human confirmation for irreversible actions (#1) | implemented | `jarvis/approvals.py` + `jarvis/gate.py` (fail-closed, HMAC tokens) — pre-existing spine |
| Trust tagging: tool output is data, never instructions (#6) | implemented | `jarvis/gate.py:347` `wrap_output` evidence-wrap; DCL decode-then-scan |
| Keys in OS keychain; model names, tool attaches (#4) | implemented | config.py keyring (above) |
| Log redaction of secret shapes (#5) | implemented | `jarvis/dcl.py` redaction on the egress path |
| Tool-call audit log (#12) | implemented | `jarvis/session_store.py` event log (emit/wake) |
| Hardened subprocess for model code: env={}, no shell, timeout, output caps (#2/#3) | **partial — gap found** | `skills/code/skill.py:107` — isolated interpreter (`-I`), jail cwd, 10 s timeout, capped output, `shell=False`, socket guard; **but env is the full os.environ minus proxy vars, not the soil's empty/minimal env.** Keys live in the keyring (not env), which blunts it, but the soil baseline is stricter. Flagged for the code-skill owner; outside this team's territory |
| Low-pass filter before wake/STT; wake rate-limiting (#8/#9) | partial | Voice-loop territory (barge-in/cooldown logic in `jarvis/voice_loop.py`, `jarvis/proactivity.py`); the spectral filter itself is not verified |
| Docker/gVisor sandbox tier (#13) | not-code | Optional escalation; v2's stdlib sandbox + gate tiers are the shipped posture |
| Adversarial test suite (#14) | partial | Gate/DCL test files exist; a dedicated hostile-corpus suite is not assembled |

## seed-viability.md

| Recommendation | Status | Evidence / gap |
|---|---|---|
| Architecture tests enforce the DNA (§3.2) | implemented [SOIL] | `tests/test_soil_architecture.py` — core-never-imports-UI + stdlib-only-core, AST-verified in CI |
| Provider abstraction / independent stage failure (§1.3) | implemented | FallbackChain (brain), TTS backend ladder (tts.py), STT lazy engines — pre-existing |
| Single-instance lock (PRR reliability) | implemented [SOIL] | `maintenance.py:814` `InstanceLock` — pid+heartbeat, stale-aware takeover |
| Watchdog (PRR reliability) | implemented [SOIL] | `maintenance.py:903` `write_heartbeat` / :917 `watchdog_status` (300 s staleness) |
| Crash capture / auto-recovery (PRR) | implemented [SOIL] | Crash tracking + `auto_recover` (above); commit-hash stamping of crash reports is not wired (no crash-report pipeline — see telemetry row) |
| Fresh-clone setup with no tribal knowledge (Phase 0) | implemented | setup.py preflight + wizard, pre-existing |
| ADRs as documents (§3.1) | partial | JARVIS-RULES.txt + R-COVERAGE.md carry decisions in-repo; a formal docs/adr/ series is not started |
| Debt tracking cadence (§1.4) | partial | IMPLEMENTATION-LEDGER.md + FIRST-RUN-AUTOPSY.md track debt openly; no quarterly cadence is scheduled |

## growth-learning.md

| Recommendation | Status | Evidence / gap |
|---|---|---|
| Memory table with confidence/expiry/supersession (Phase A) | implemented | `jarvis/memory.py` (provenance tiers, TTL, consolidate) — pre-existing + PhD wave |
| Nightly purge/consolidation job (§5, Phase D) | implemented [SOIL] | `maintenance.py:978` `run_maintenance` — recovery → health → backup → cleanup → consolidation hook (store injected; `memory.py:339` `consolidate()` is the target) |
| Explicit forget that really deletes (§5) | implemented | `jarvis/memory.py:293` `forget()` (secure forget) |
| Correction → golden-pair lessons (Phase C) | implemented | `jarvis/golden_pairs.py` + brain `filter_lesson` anti-poisoning (Builder A) |
| Extraction denylist for secrets (§5) | partial | DCL classification blocks SECRET at egress; a memory-write denylist rides on the same classifier — not a separate named list |
| "What do you remember about me?" transparency (§5) | partial | `/recall` + memory search exist (chat territory); a single owner-facing listing command is chat work |
| Cold-start seed memories from the wizard (§4) | partial | Wizard stores profile/data-dir in config; writing them as seed *memories* is chat/memory wiring |

## seed-to-tree-mapping.md

| Metaphor row | Status | Evidence / gap |
|---|---|---|
| Seed coat → error handling, crash recovery, single-instance lock | implemented [SOIL] | maintenance.py crash tracking + InstanceLock + auto-recovery |
| Drainage → log rotation, temp cleanup, memory management | implemented [SOIL] | `cleanup_data_dir` (logs/archives at 1-year retention, stale .part litter at 7 days, probe leftovers) |
| Stored food → zero-config local capabilities | implemented | Keyless Pollinations floor + Ollama + local skills (pre-existing) |
| Water → full activation (keys, wizard) | partial | Wizard + /key flows exist; full activation is an owner session on his PC |
| Light/oxygen/nutrients/time rows | not-code | Usage, connectivity and maturity — lived, not coded |

---

## This team's new code (all [SOIL] rows)

- `jarvis/maintenance.py` — health suite (disk/RAM/Python window/DB
  integrity via PRAGMA/backup freshness/log pressure/crash state/
  watchdog/uptime/path/GPU/Ollama), backup+rotation+restore with
  SQLite-API snapshots, retention cleanup, crash-loop auto-recovery,
  InstanceLock, heartbeat, `run_maintenance` nightly rhythm.
- `jarvis/setup.py` — P9–P13 behind `preflight(soil_extras=True)`
  (:336, :373, :409, :463, :487). Default preflight behavior identical.
- `tests/test_soil_maintenance.py` (30 tests), `tests/test_soil_setup_extras.py`
  (16), `tests/test_soil_architecture.py` (4) — 50 new tests, all green.
- Nothing pushed (owner freeze). chat.py wiring for note_startup /
  write_heartbeat / run_maintenance call-sites is a one-line-each job
  for the wiring owner — deliberately not done here (territory).
