# Setup, Onboarding & Updates — Design Specification

*PHASE INFINITY, Research Cycle 21. The first-run experience and the "it just works" layer.*

*Date: 2026-10-19. Status: design complete, unimplemented.*

**Sources unified:** `~/workspace/jarvis-build/FAILURE-ANALYSIS.md` (C-I5, C-B5, C-X2, H-I1–H-I6, M-I1–M-I12, M-I27–M-I31, R10, R12), `learn-frontend.md` (§4 Tauri vs Electron, §6 auto-updates + code signing), `learn-reliability-spec.md` (§4 degradation ladder, §5 dependency map).

**Confidence tags:** [VC] >95% · [HC] 80–95% · [MC] 60–80% · [SP] 40–60% · [UK] unknown.

---

## 1. The one entry point

**The rule:** exactly one installer, exactly one setup flow. No three-methods-downloading-to-three-places (M-I29). [DERIVED from M-I29, M-I30]

```
JARVIS_Setup.exe  →  install (files + shortcuts + single-instance registration)
                  →  first launch → preflight (Section 2)
                  →  setup flow (Section 4: model acquisition + keys)
                  →  verified ready screen
```

**What the installer does vs what first-launch does — and why the split exists:**

| Phase | Does | Does NOT | Why the split [HC] |
|---|---|---|---|
| **Installer** (offline-capable, admin-free `%LocalAppData%`) | Copies app files, creates shortcuts, registers file/protocol handlers, writes uninstall info | Downloads models, touches the network for anything big, asks the user questions | The installer must succeed on an offline machine and in locked-down environments. Network failures during install are the #1 "setup reported success but nothing works" class (H-I6). |
| **First-launch setup** (inside the app) | Preflight checks, model download with verification, key entry, capability tour | Re-install app files, touch the registry | Setup needs the full app UI (progress, retries, plain-language fixes) and must be re-runnable forever — the installer is a one-shot event, setup is a permanent UI surface (R12 "single entry point; re-runnable"). |

**Clause 1.1** — The installer ships a *manifest* of bundled assets with SHA-256 checksums; first-launch setup verifies every bundled asset before downloading anything, so a corrupted installer is caught, not propagated. [DERIVED from H-I1, H-I6]

**Clause 1.2** — One download directory, declared in one place (`paths.data_dir()/models/`), used by every setup path. No entry point may invent its own asset location. This is the direct fix for M-I29. [DERIVED from M-I29]

**Clause 1.3** — Re-running setup is always safe: it diffs against the manifest, downloads only what's missing or checksum-failed, never overwrites good keys or good models without confirmation. [DERIVED from M-I5 (wizard overwrites good key), M-I28 (re-run clobbers config)]

---

## 2. Startup preflight

**The rule:** before the main window, run the check sequence. Every check has a plain-language fix and a defined behavior if the user skips it. Preflight is fast (<5s target), non-blocking where possible (parallel checks), and *never lies* — a skipped check is a recorded skip, not a silent pass. [DERIVED from R12, C-I5, H-I4]

### The check sequence (order matters: cheap → expensive)

| # | Check | What it tests | Fix offered (plain words) | If skipped |
|---|---|---|---|---|
| P1 | **VC++ 2015–2022 Redist** | Registry key / `vcruntime140.dll` presence | "JARVIS needs Microsoft's free system component. Download and install it? (one click)" → opens the official Microsoft download | Voice features marked unavailable; chat works. A persistent, dismissible banner says *why* voice is off. [DERIVED from C-I5 — the #1 fresh-machine killer] |
| P2 | **Python runtime version + bitness** | `sys.version_info` within supported range (e.g., 3.10–3.12); `struct.calcsize("P")*8 == 64` | "This JARVIS needs 64-bit Python 3.10–3.12. You have X." → download link for the exact installer | **Blocking.** The app cannot start on the wrong interpreter; the message names the file and the key, never a traceback. [DERIVED from H-I4, M-I7] |
| P3 | **Store stub trap** | `sys.executable` resolves to the WindowsApps stub | "That's a fake Python from the Microsoft Store — install the real one?" → link to python.org installer | **Blocking.** Same screen as P2. [DERIVED from M-I2] |
| P4 | **Disk space** | Free space on data-dir drive ≥ (manifest total × 1.5) | "JARVIS needs ~X GB free. You have Y." → option to choose a different data directory | **Blocking** if below the hard floor; warn-only with a recorded skip if below the comfort margin. [DERIVED from M-I6] |
| P5 | **Model assets** | Each file in the manifest: exists + SHA-256 matches | Missing/corrupt → queued for download in setup (Section 3) | App starts in chat mode; voice/vision models marked degraded per the reliability ladder. Never claims "setup complete" with failed assets. [DERIVED from H-I1, H-I6] |
| P6 | **Dependency importability** | Actually `import` the critical modules (sounddevice, onnxruntime, pywin32) and catch `OSError`/`Exception`, not just `ImportError` | "Something's broken in an audio component — reinstall it? [Repair]" → targeted pip reinstall behind a GUI button | Component marked unavailable with a plain-language note. [DERIVED from M-I4 — the import probe caught only ImportError, so OSError crashed raw] |
| P7 | **Mic / camera availability** | Enumerate devices; request nothing yet (no permission prompts at startup — permission is requested in context, per frontend §2) | "No microphone found" → voice offered as text-only | Text chat works fully. [DERIVED from R12; frontend §2 permission UX] |
| P8 | **Write test on data dir** | Create + delete a temp file in the data dir (catches Program Files read-only installs, M-S13 class) | "JARVIS can't write where it's installed" → relocate data dir | **Blocking** for the chat path; the app cannot persist anything otherwise. [DERIVED from M-S13, logger M-I16] |

**Clause 2.1** — Preflight results are written to the log and shown as one screen: ✅ ready, ⚠️ degraded (with the plain fix), ❌ blocked (with the plain fix). No check fails silently. [DERIVED from R12 "honest UX"]

**Clause 2.2** — Exception taxonomy: a check that *raises* reports what it was doing in plain words ("I was checking your microphone and got an error I didn't expect") plus a "copy details" button — never a raw traceback in the user's face. [DERIVED from H-I3 cryptic failures; M-X19 the copy-paste-traceback habit]

**Clause 2.3** — Preflight never phones home. All checks are local. Network checks (update availability) happen after the main window is up, in the background. [DERIVED from reliability §5 "soft health check; never blocks startup"] [HC]

### Plain-language rules for every preflight message [HC]

1. Name the *thing* ("your microphone"), not the *module* ("sounddevice").
2. Name the *fix* ("install the free Microsoft component"), not the *error* ("OSError: DLL load failed").
3. One primary action per message, labeled as the outcome ("Install it", not "OK").
4. "Why" is one tap away, never in the main text.

---

## 3. Model acquisition

**The rule:** "Setup complete" may only be claimed after every manifest asset passes checksum verification. Downloads are atomic, resumable, and honest about progress. [DERIVED from H-I1, H-I6, R12]

### The download protocol

**Clause 3.1** — Download to `<name>.part` in the data-dir models folder; on completion, verify SHA-256 against the manifest; on match, atomic rename to the final name; on mismatch, delete the part file and retry (bounded retries with backoff), then report failure plainly. A truncated or interrupted download can *never* be mistaken for a good file. [DERIVED from H-I1 — the truncated-`.onnx`-treated-as-success bug; R12 "temp file + atomic rename + checksum"]

**Clause 3.2** — Resume support: HTTP Range requests; if the server doesn't support ranges, restart the part file from zero (never append to a partial file from a non-resuming server). [PROPOSED — resume is standard practice; not previously studied in the knowledge base] [MC]

**Clause 3.3** — Progress UI per asset: name in plain words ("Voice recognition model"), size, percentage, speed, time remaining. One overall progress bar. Cancel is always available and leaves no partial state that breaks re-run (the part file is either resumable or deletable; setup re-runs the verify step first). [DERIVED from H-I2 — no cancel path killed pip mid-wheel; R12 "cancel-safe"]

**Clause 3.4** — Setup is crash-safe mid-download: the on-disk state (manifest + part files + verification results) is sufficient to resume exactly. Closing the app during a 4GB model download is a *normal event*, not an error. [DERIVED from H-I2, M-I27 — close mid-install must not corrupt state]

**Clause 3.5** — "Setup complete" is a *verified state*, not a code path that ran: the setup screen shows the checklist (all assets ✅ verified) and only then says "JARVIS is ready." The installer never claims it (H-I6: installer reported success while `--prewarm` had failed silently). [DERIVED from H-I6]

**Clause 3.6** — Asset sources are pinned in the manifest (URL + checksum + expected size). No asset is ever downloaded from an unpinned URL, and no executable asset (installers, binaries) is ever executed without signature verification — the model-download path inherits the update path's trust rules (Section 5). [DERIVED from C-X3 — unverified `OllamaSetup.exe` executed; C-X5 — unverified HF weights]

---

## 4. The no-keys onboarding

**The rule:** first launch with no API keys and no local model gets an honest, plain-words explanation of the options — never the infinite useless loop. [DERIVED from C-B5]

### The onboarding screen (chatbot-first)

> "Sir, I can think in two ways, and right now I have neither set up:
>
> **1. On your computer** — private, free, works offline. I need to download a thinking model (~5 GB, one time). Your computer can run it.
>
> **2. Through the internet** — smarter on hard questions, needs an API key (free ones exist). You paste the key once; I keep it locked in Windows' own vault, never in a file.
>
> Which would you like? You can do both — I'll use the internet for hard questions and your computer for everything else."

**Clause 4.1** — Each option is one tap: "Download the local model" starts Section 3's flow for the brain model; "Add an API key" opens the key entry with a link to where the key comes from and what the free tier includes. [PROPOSED UX copy; the principle is DERIVED from C-B5]

**Clause 4.2** — The no-brain state is a *declared mode*, not a failure: the chat window is open, it explains itself, and every message in this state gets the onboarding answer — once per session, then a quiet reminder link. The app never loops "start Ollama" with no path forward. [DERIVED from C-B5]

**Clause 4.3** — Keys go to the OS keyring (Windows Credential Manager), entered through password-masked fields, never echoed, never in chat, never in `config.yaml` (git-tracked). The setup screen says this in one line: "Your keys are stored in Windows' locked vault — I never write them to a file." [DERIVED from R9, M-I7 (key echoed in cleartext), M-X3 (config.yaml token leak)]

**Clause 4.4** — Re-running the key step never overwrites a working key silently: existing keys are shown as "••••1234 (working)" with explicit Replace / Remove actions. Blank field + save = no-op, not wipe. [DERIVED from M-I5, M-I28]

---

## 5. Updates

**The rule:** the updater is a remote-code channel by definition — it gets the security of one. Signed, verified, background-downloaded, applied on restart, one-click rollback. [DERIVED from R10, C-X2]

### 5.1 Signing and verification

**Clause 5.1.1** — Two layers, per frontend §6: (a) **minisign/Ed25519** on every update artifact, public key pinned in the app, private key in CI secrets only — "this update came from us"; (b) **Authenticode via Azure Artifact Signing** on the installer — "Windows trusts this publisher". Verification failure aborts the install, full stop. [DERIVED from R10, frontend §6 — 90% [HC]]

**Clause 5.1.2** — The update manifest (`latest.json`) is fetched over HTTPS from a pinned host; the manifest lists per-platform artifact URLs + minisign signatures + version + release notes in plain words. The client verifies the manifest signature *before* trusting any URL in it. [DERIVED from R10 "checksum-pinned to a release manifest"; frontend §6] [HC]

**Clause 5.1.3** — The update check is never LLM-triggerable, never silent-installing, and never applies mid-session. `check_for_updates` as a brain tool is REMOVED — updates are a UI surface (tray + settings), not a tool. [DERIVED from C-X2 — LLM-triggerable unsigned git pull; H-S10 — LLM-triggerable pip install]

### 5.2 Download, apply, rollback

**Clause 5.2.1** — Updates download in the background while the app runs; the user gets one calm prompt via chat/tray: "Update 2.4 is ready — restart to apply? [Restart now] [Tonight]". Never force-restart mid-conversation. [DERIVED from R10 "apply on restart"; frontend §6] [HC]

**Clause 5.2.2** — Before applying: snapshot the current version as "last known good" (keep the N-1 installer cached in the data dir). After applying: run the startup preflight (Section 2) as a *smoke test* — if the app fails to reach the main window within the watchdog timeout, auto-offer rollback. Rollback is one click in Settings → Updates ("Go back to 2.3"), no terminal. [DERIVED from R10 rollback requirement; H-I5 — no rollback bricked installs; reliability spec watchdog] [HC]

**Clause 5.2.3** — The "not a git clone" dead end is eliminated (M-I12): installer-based installs update through the signed-update channel, full stop. There is no install flavor without an update path. Settings → Updates shows the same surface for every install: current version, check now, history, rollback. [DERIVED from M-I12] [VC — this is a pure design rule]

**Clause 5.2.4** — Delta updates where available (per-platform); full artifact as fallback. Failed/interrupted download resumes per Section 3's protocol — the update downloader and the model downloader are the same code. [DERIVED from frontend §6 delta updates; DRY principle] [MC]

### 5.3 Update UX states

| State | What the user sees |
|---|---|
| Up to date | Nothing (tray tooltip shows version on hover) |
| Checking | Silent; a spinner only if the user opened Settings → Updates |
| Available | One calm prompt: version, plain-words release notes ("Fixes the voice stutter; adds Hindi voice"), [Restart now] [Tonight] [Details] |
| Downloading | Tray progress; never a modal |
| Ready | "Restart to apply" prompt (one tap) |
| Failed | Plain reason + [Retry] + [Report] — never a traceback, never "run pip in terminal" (M-I15) |
| Rolled back | "Went back to 2.3 because 2.4 wouldn't start. Your data is untouched." |

---

## 6. The zero-terminal promise

**The rule:** every recovery path that v1 pushed to the terminal gets a GUI equivalent. The terminal is never part of the user journey. [DERIVED from M-I30, M-I15, R12]

| v1 terminal escape hatch | v2 GUI equivalent | Source |
|---|---|---|
| `git reset --hard` (update recovery) | Settings → Updates → "Go back to previous version" (one click) | H-I5, M-I13 |
| `pip install <pkg>` (updater's advice) | In-app dependency repair: preflight P6's [Repair] button runs the install behind progress UI | M-I15, H-S10 |
| `playwright install chromium` | Setup flow installs the browser component as a manifest asset (Section 3); if missing at runtime, the skill reports "browser component missing [Install]" | M-I9 |
| `JARVIS_SETUP.bat` (legacy terminal setup) | Deleted. One installer, one setup flow (Section 1) | M-I7, M-I30 |
| Hand-editing YAML (config recovery) | Settings → "Reset to defaults" per section + config validation screen naming the bad file and key (R7) | C-I1, C-B3 |
| `git pull` conflict resolution | Not applicable — no git-based updates exist in v2 (Section 5 replaces the updater) | M-I13, M-I14 |
| Manually deleting a corrupt model file | Setup → "Verify my downloads" → re-downloads checksum failures (Section 3) | H-I1 |
| Copying tracebacks to the assistant (JARVIS_Debug.bat) | "Report a problem" button: redacted diagnostics bundle (log tail with secrets scrubbed — R9) sent via the approved channel | M-X19, R9 |

**Clause 6.1** — No v2 UI text may contain a terminal command as an instruction to the user. If a failure has no GUI recovery path yet, the message says "This needs a fix from us — [Report it]" rather than handing the user a command. [DERIVED from M-I30, R12 "honest UX"] [VC — design rule]

**Clause 6.2** — The redacted diagnostics bundle: log tail + preflight results + version info, with the R9 redaction filter applied (keys, tokens, paths-to-secrets masked). The user reviews it before sending. This replaces the "copy the red text" habit that routinely exfiltrated secrets (M-X19). [DERIVED from M-X19, R9] [HC]

---

## 7. Uninstall

**The rule:** clean removal, with an explicit, plain-words choice about the user's data. No orphaned shortcuts, services, or scheduled tasks. [PROPOSED — uninstall was not covered by the autopsy; standard practice] [MC]

**Clause 7.1** — The uninstaller (registered in Windows Apps & Features via the installer manifest) removes: app files, shortcuts, tray autostart entry, protocol/file handlers, and the single-instance lock. It verifies removal and reports leftovers rather than failing silently.

**Clause 7.2** — Data choice screen, plain words:

> "Remove JARVIS's data too?
> - **Keep my data** (recommended) — your chats, memories, and settings stay on this computer. Reinstalling later picks up where you left off.
> - **Remove everything** — deletes chats, memories, settings, and downloaded models (~X GB). This can't be undone."

Default: **Keep my data**. The data dir is never inside the install dir (so uninstall can't take it by accident), and "Remove everything" requires a typed confirmation (it's irreversible — the same typed-confirmation rule as tier-3 actions). [DERIVED from the typed-confirmation principle, privacy-engineering deletion checklist]

**Clause 7.3** — Secrets in the OS keyring are deleted on "Remove everything" (Credential Manager entries owned by the app); on "Keep my data" they stay — and reinstalling reuses them silently. [PROPOSED] [MC]

---

## 8. The failure table — every corpse mapped

*No orphans. Every v1 setup/installer/updater corpse has a spec clause that prevents it.*

| Finding | Corpse | Prevented by |
|---|---|---|
| C-I5 | VC++ redist never checked — #1 fresh-machine DLL killer | §2 P1: preflight check with one-click fix |
| C-B5 | No keys + no model = infinite useless "start Ollama" loop | §4: no-keys onboarding; §4.2 declared no-brain mode |
| C-X2 | Unsigned LLM-triggerable `git pull` = RCE on restart | §5.1: minisign + Authenticode; §5.1.3: updates are UI-only, never a brain tool |
| C-X3 | Unverified `OllamaSetup.exe` executed | §3.6: no executable asset without signature verification |
| C-X5 | Unverified HF weights as default model | §3.6: pinned manifest (URL + checksum); provenance requirement [§3.6] |
| H-I1 | Truncated download treated as success; never repairs | §3.1: part-file + checksum + atomic rename; §3.5: "complete" = verified |
| H-I2 | No cancel path; killed pip corrupts metadata forever | §3.3: cancel-safe; §3.4: close-mid-download is a normal event; importability over metadata (§2 P6) |
| H-I3 | Cryptic pip failures, no retry, bare sys.exit | §2.2: exception taxonomy with plain-words messages; §6: [Repair] button with retries |
| H-I4 | No upper-bound / bitness check on Python | §2 P2: version range + bitness; §2 P3: Store stub trap |
| H-I5 | No rollback; bad update bricks app; recovery needs terminal | §5.2.2: N-1 cached + smoke-test + one-click rollback; §6: terminal escapes eliminated |
| H-I6 | Installer reports success; prewarm failed silently | §1: installer makes no network claims; §3.5: only verified setup says "ready" |
| H-S10 | LLM-triggerable `pip install` | §5.1.3: no package management as a brain tool; installs are user-confirmed UI actions |
| H-S14 | LLM-triggerable model download/exec (local_brain skill) | §3.6: asset downloads are setup/UI-only; never tool-triggered |
| M-I1 | `Install_JARVIS.bat` silent death on broken pythonw | §6: batch entry points deleted; installer is a real installer with error UI |
| M-I2 | Microsoft Store Python stub trap | §2 P3: explicit stub detection |
| M-I3 | Bare except swallows wake-word failure cause; VC++ never surfaced | §2.2: no bare excepts in setup paths; §2 P1: VC++ surfaced |
| M-I4 | Import probe catches only ImportError (OSError crashes raw) | §2 P6: importability probe catching Exception |
| M-I5 | Re-run overwrites working key; blank field wipes | §1.3 + §4.4: re-run is diff-based; keys shown masked with explicit Replace/Remove |
| M-I6 | No disk-space check before ~300MB+ downloads | §2 P4: disk check with hard floor + warn margin |
| M-I7 | Legacy terminal setup; key echoed in cleartext | §6: deleted; §4.3: password-masked key entry |
| M-I8 | Unpinned heavy deps ("worked in October, broken in March") | Manifest pinning (§1, §3.6); hash-pinned requirements per R10 |
| M-I9 | `playwright install chromium` never runs; terminal step | §6 table: browser component is a manifest asset with GUI install |
| M-I10 | Non-admin shortcut write fails with Inno error | Installer defaults to user-local install (`%LocalAppData%`); per-machine install is an explicit, validated choice |
| M-I11 | Crazy install paths crash frozen Python | Installer validates the path (ASCII, no trailing space, length check) before copying anything |
| M-I12 | No update path for installer users ("not a git clone" dead end) | §5.2.3: one update channel for every install flavor |
| M-I13 | Dirty-tree / MERGING state bricks future pulls | §5: no git-based updates; §5.2.2: rollback instead of conflict resolution |
| M-I14 | 120s frozen UI; git credential prompt hangs with no TTY | §5: no git; §5 table "Failed" state: bounded, cancellable, plain reason |
| M-I15 | "Run pip in terminal" advice | §6.1: no terminal commands in UI text, ever |
| M-I16 | Unwritable log dir = silent no-logging | §2 P8: write test on data dir at preflight; logger fails loudly to the user, not silently |
| M-I27 | Close mid-install → half-configured state; re-run trusts broken probes | §3.4: on-disk state is resumable; §1.3: re-run diffs against manifest |
| M-I28 | Re-run never loads current config; blank key overwrites good key | §1.3 + §4.4 |
| M-I29 | Three setup methods → three download locations | §1: one installer, one setup flow, one asset dir (§1.2) |
| M-I30 | Zero-terminal promise broken in ≥4 places | §6: enumerated GUI equivalents for every escape hatch |
| M-I31 | Crash-reporting gap for installer users | §6.2: redacted diagnostics bundle; single log location in data dir (R14) |

---

## 9. Open questions

1. **Tauri vs installed-Python packaging [UK].** The frontend study recommends Tauri 2.x with a PyInstaller sidecar (90% [HC] on facts, 80% [MC] on the recommendation). This spec is written packaging-agnostic: installer → preflight → setup flow holds for either. The decision changes *who implements the installer UI*, not the spec. Needs a spike build, not more reading.
2. **Signing key custody [UK].** Minisign private key lives in CI secrets; Authenticode via Azure Artifact Signing (~$10/mo). Who holds the Azure identity (Owais personally vs a JARVIS org), and what's the key-rotation ceremony? Rotation invalidates the trust chain — plan it before the first release, not after.
3. **SmartScreen reputation timeline [UK].** New publisher identity = "Unknown publisher" warnings for weeks-to-months regardless of signing (frontend §6). The onboarding copy must prepare Owais for the "Run anyway" click on first install. No way to buy out of this except the Microsoft Store.
4. **Model manifest governance [UK].** Who signs the model manifest, and how do model updates (new quant, new weights) flow? Proposed: models versioned in the same signed manifest as app updates (§5.1.2), but the cadence and testing bar for a *brain* change is higher than for app code — needs its own release policy.
5. **Offline installer variant [SP].** Should there be a full offline installer (models bundled, ~6GB)? It solves the offline-machine case but multiplies distribution cost. Proposed: online installer first; offline variant only if real users need it.

---

## 10. What this spec does NOT cover (honest scope)

- The chat UI itself (frontend §1, scout-phd-chat-ui) and the HUD.
- The brain, skills, and memory internals — setup *delivers* them, doesn't define them.
- Voice pipeline specifics — the voice-loop spec (Cycle 15) owns that; setup only guarantees the assets and preflight for it.
- Enterprise deployment (MDM, per-machine fleet install) — explicitly out of scope for v2; the installer is single-user by design.

---

*Spec complete. Every clause traces to a finding; open questions are marked, not buried. This is the document the installer and setup flow get built from.*
