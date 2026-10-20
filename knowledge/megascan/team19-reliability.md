# TEAM 19 — ALWAYS-ON RELIABILITY: Daemons, Watchdogs, Auto-Update

**Mission:** JARVIS must run 24/7 on the owner's Windows PC and survive crashes, restarts and updates. Reverse-engineer how long-running agents and desktop daemons stay alive.

**Method:** `git clone --depth 1` into `megascan/.work19/` (git protocol, no API quota), code read locally. Sparse/blobless clones for the giants (systemd, OTP, Squirrel, Velopack, Omaha). Every backoff constant below is traced to a file in the clone unless tagged [DOCS].

**Count: 40 repos code-read + 1 documented-missing** (nbari/immortal — repo deleted from GitHub, project moved off-platform; only the `immortal-formula` packaging repo remains. No deep read possible; noted as a failure story in itself: a supervisor whose home disappeared).

> Note: this file previously held an empty scaffold from a parallel re-dispatch (different target list, zero findings). It has been replaced by the completed scan below; nothing of substance was lost.

---

## PART A — PROCESS SUPERVISORS (the state machines)

### A1. Supervisor (supervisord) — custom BSD-family license → ideas + careful reuse
The reference design everyone copies. Explicit state machine (`supervisor/states.py`): STOPPED 0 / STARTING 10 / RUNNING 20 / BACKOFF 30 / STOPPING 40 / EXITED 100 / FATAL 200 / UNKNOWN 1000.
- **Backoff math** (`supervisor/process.py:169-172`): on failed start, `backoff += 1; delay = now + backoff` — **linear 1s, 2s, 3s…** up to `startretries` (default 3), then FATAL (no more attempts until human intervenes).
- Counter resets only after the process survives `startsecs` in RUNNING — a process that dies at 0.9×startsecs never earns a reset.
- `autorestart` ∈ {true, false, unexpected} (unexpected = restart only on exit codes not in `exitcodes`).
- Stop discipline: `stopwaitsecs` default 10s → SIGKILL; `stopasgroup`/`killasgroup` for process trees.
- Built-in log rotation (`maxbytes` + `backups`, default 10) and an **event-listener bus** — the extension point superlance plugs into.

### A2. superlance — same license family → ideas
Event listeners on top of Supervisor: **memmon** polls `ps` RSS per program and restarts via XML-RPC when over a memory ceiling (`superlance/memmon.py:116,165-175`); **crashmail / fatalmailbatch** notify on state transitions into FATAL (batched, so a flapping service doesn't spam); **httpok** = HTTP health check as an event listener. Lesson: resource limits and health checks are *plugins on the state machine*, not part of it.

### A3. Circus (circus-tent/circus) — Apache-2.0 → code OK with attribution
Arbiter → Watchers → Processes tree, ZeroMQ control plane.
- **Flapping plugin** (`circus/plugins/flapping.py`): attempts=2 restarts within window=1s → suspicious; wait `retry_in`=7s; after `max_retry`=5 the watcher is **stopped** (circuit breaker, not infinite retry).
- `resource_watcher` plugin kills processes over CPU/mem thresholds; `numprocesses` scaling; config `max_retry` default 5.
- Steal-shaped: flapping detection is a *separate counter* from ordinary restart counting — a service can restart "normally" forever but flapping fast trips a different, harsher breaker.

### A4. ochinchina/supervisord — MIT → code OK (Go re-implementation of Supervisor)
Mirrors Supervisor's states (Backoff=30). Two scar-tissue details:
- **Anti-flap hack** (`process/process.go` ~342): a start that fails in <2s sleeps 5s before retry regardless of the configured backoff — fast death is treated as a different disease than slow death.
- `zombie_reaper` for PID-1 duties; a `daemonize_windows.go` exists (rare among Unix-born supervisors).

### A5. pm2 (Unitech/pm2) — **AGPL-3.0 → IDEAS ONLY, never code**
The most battle-tested Node supervisor; its constants are the field's default answer:
- **Exponential backoff** (`lib/God.js:518-528`, `lib/Worker.js:131`): `prev = min(15000, prev × 1.5)`; **reset after 30s of uptime** (`EXP_BACKOFF_RESET_TIMER = 30000`).
- `unstable_restarts` counter vs `max_restarts` → process marked `errored` and left down (circuit breaker).
- **State checkpoint:** `dump.pm2` serializes the whole process list; `pm2 resurrect` restores it after reboot/crash.
- **Scar tissue worth stealing:** the dump code *refuses to overwrite a good dump with an empty process list* (`lib/God/ActionMethods.js:127+`, comment admits "often happens when PM2 crashed") — a checkpoint writer must never let a dying process erase the last known-good state.
- `max_memory_restart` enforced by the Worker loop.

### A6. Monit (tildeslash/monit) — **AGPL-3.0 → IDEAS ONLY**
Poll-cycle checker (sample `monitrc` daemon interval 30s): checks = pidfile/process existence, TCP ports, filesystem, file checksums.
- **Restart-limit circuit breaker** (`src/validate.c` ~1625-1635): if `s->nstart >= count && s->ncycle <= cycle` → service times out and monitoring stops. "If it needed 5 restarts in 5 cycles, restarting is not the treatment."
- Philosophy: checks verify *function* (port answers, checksum matches), not just process existence.

### A7. s6 (skarnet/s6) — ISC → code OK
The minimalist extreme: `svscan` scans a directory; each service dir gets an `s6-supervise` with `run`/`finish` scripts; a `down` file = don't start.
- **Readiness done right:** the daemon itself signals readiness on a **notification-fd** (`doc/notifywhenup.html`) — the supervisor never guesses with sleeps or port polls; `s6-notifyoncheck` is the polling fallback for daemons that can't.
- `finish` script has a max lifetime → SIGKILL (cleanup code can hang too; bound it).

### A8. systemd — GPL-2/LGPL → ideas only
- `RestartSec` default 100ms.
- **`RestartSteps` geometric interpolation** (man/systemd.service.xml:611-640): delays interpolate geometrically from initial to max over N steps — ratio = (Max/Initial)^(1/Steps); documented example yields 10, 20, 40, 80, 160s.
- `StartLimitIntervalSec` + `StartLimitBurst` = rate-limit circuit breaker at the unit level.
- **`WatchdogSec` + `sd_notify("WATCHDOG=1")`**: the service must pet the watchdog from inside its own event loop; a live-but-wedged process that stops petting gets killed. This is the liveness/readiness distinction enforced by the OS.
- FDSTORE: file descriptors handed across restarts so listeners survive.

### A9. Erlang/OTP supervisors — Apache-2.0 → code OK
The original supervision-tree paper, as a runtime (design_principles docs read in clone):
- **Restart intensity:** if a supervisor's children restart more than `MaxR` times in `MaxT` seconds, the supervisor **terminates all its children and itself** — failure escalates up the tree instead of looping at the leaf (`sup_princ.md:238-276`; textbook example intensity=1, period=5).
- Strategies: one_for_one / one_for_all / rest_for_one / simple_one_for_one. Restart types: permanent / transient / temporary. Modern OTP adds significant children + `auto_shutdown`.
- The deep idea: **escalation is a feature.** A supervisor that cannot fix its subtree dies loudly so its own supervisor (or a human) deals with a bigger, cleaner failure.

### A10. god (mojombo/god) — MIT, **DEAD (~2017)**
Condition system (`flapping.rb`, `tries.rb` = N-times-within-period, cpu/disk/http conditions). Failure story: the watcher itself bloated and died — Ruby god processes were notorious for eating the memory they were hired to police. **Who watches the watcher must be smaller than the watched.**

### A11. gosuv (codeskyblue/gosuv) — MIT, archived/deprecated
FSM + `StartRetries` (`fsm.go:117,297`). One sharp heuristic (`fsm.go:386`): **"if first time quit so fast, just set to fatal"** — a process that has never once run successfully doesn't get a retry budget; it's misconfigured, not unlucky.

### A12. ncolony — MIT
Twisted-based colony supervisor; `beatcheck.py` implements a **heartbeat checker that sends restart messages for processes that miss beats** — an internal dead-man's switch inside the supervisor itself.

### A13. honcho (nickstenning/honcho) — MIT
Deliberately **no restart logic at all** — pure Procfile runner. Included as the anti-scope control: a launcher is not a supervisor, and pretending otherwise is how JARVIS.bat fails silently today.

---

## PART B — WINDOWS SERVICE WRAPPERS (JARVIS's actual platform)

### B1. WinSW (winsw/winsw) — MIT → code OK
Wraps any exe as a Windows service via XML config. Key move: **it delegates recovery to the OS.** `<onfailure action="restart" delay="…"/>` entries (1st, 2nd, subsequent failures each get their own delay) are compiled into **Windows SCM failure actions** (`src/WinSW.Core/Configuration/XmlServiceConfig.cs:485-508`); `<resetfailure>` resets the failure counter after a healthy period. Built-in log modes include roll-by-size. If the wrapper dies, SCM still restarts the service — the supervisor's supervisor is the operating system.

### B2. NSSM (kirillkovalenko/nssm) — public domain (author's stated license; no license file in this fork) → code OK
The other classic Windows wrapper (v2.24 + fork fixes). **NSSM monitors the child process itself** (it does not rely on SCM):
- **Throttle math** (`service.cpp:279-285,1956-1972,2138`): if the app exits before `AppThrottle` ms (default **1500**, `nssm.h:95`), the throttle count increments and the restart is delayed by `throttle_milliseconds(n) = 2^(n-1) × 1000` ms — **1s, 2s, 4s … capped at n=8 → 128s**. Surviving the throttle window resets the count to 0.
- Per-exit-code actions (`AppExit`: Restart / Ignore / Exit / really-exit), plus an unconditional `AppRestartDelay`.
- Log rotation built in: `AppRotate` with byte threshold and *online* rotation (CopyFile + SetEndOfFile so a running app's open log can rotate — ChangeLog), plus a configurable post-rotation sleep.
- Graceful-stop ladder: Ctrl-C simulation → window close → kill threads → TerminateProcess, each with a 1500ms grace period.

### B3. kardianos/service — zlib-style permissive → code OK; takama/daemon — MIT → code OK
Cross-platform `Service` interface (Install/Start/Stop/Restart/Status) that **delegates restart semantics entirely to systemd / launchd / SCM** — no backoff math of their own. Verdict: the right shape for "install as service" plumbing, but they are adapters, not supervisors. JARVIS needs policy *above* this layer.

---

## PART C — AUTO-UPDATE (delta? full? signed?)

| System | Delta? | Signature / integrity | Swap mechanism | Rollback |
|---|---|---|---|---|
| Sparkle (macOS) | Yes — BinaryDelta (bsdiff), delta **validated before extraction**, failure → full update | **EdDSA (Ed25519) mandatory-ish; unsigned updates deprecated** (`Documentation/Security.md:35`) | Separate installer helper swaps after app quits | Delta failure falls back to full archive |
| Squirrel.Windows | Yes — `DeltaPackageBuilder` bsdiff + MsDelta (`src/Squirrel/DeltaPackage.cs:26`) | RELEASES file w/ SHA-1 per package (integrity, not signatures, in the classic design). License: MIT [MC — root COPYING outside sparse checkout, not re-read] | Per-version sibling dirs (`app-1.0`, `app-1.1`); a stub exe always launches newest | Keep old version dir; stub can be pointed back |
| Velopack (MIT) — Squirrel's successor, Rust core | Yes — delta patch chain (`src/bins/src/commands/patch.rs:54`) | Package checksums; signing supported | **Directory-level atomic swap** (`commands/apply_windows_impl.rs:20-40`): rename current→old (IO retried ×10 against locked files), rename new→current; **Update.exe `--waitPid` waits for the app to exit before touching anything** | On any failure the old dir is renamed back; old version kept as backup |
| Omaha (Google) — Apache-2.0 | Yes — Courgette differential (protocol-level; core `update_check.cc` not in sparse checkout [DOCS]) | Signed update manifests, hash-pinned payloads | Dedicated Windows service + XML update-check protocol (`omaha/common/protocol_definition.h:102-155`) with ping/event telemetry (`days_since_last_active_ping`) | Staged rollout + cohort targeting; server can halt a bad update |
| python-tuf — Apache-2.0/MIT | Transport-agnostic | **The gold standard:** 4 roles — root (offline keys), timestamp (anti-freeze), snapshot (anti-mix-and-match), targets (hash+length, anti-rollback versioning); ngclient refreshes metadata *before* any download | n/a (framework) | Anti-rollback is a metadata property, not a hope |
| minio/selfupdate — Apache-2.0 | No (full binary) | Optional SHA-256 + Ed25519 verify | **Atomic binary swap** (`apply.go:91-143`): rename target→`.old`, rename new→target; **Windows trick: you may rename a running exe, you just can't delete it** | Failure → rename `.old` back |
| tj/go-update — MIT | Yes (bsdiff patches) | Checksum + signature provider interfaces | Provider-based patch/apply | Verify-after-patch |
| PyUpdater (Digital-Sapphire) — MIT | Yes — **patch chains capped at 4; delta used ONLY if total patch bytes < full file** (`client/patcher.py:240-256`) | Signature verified before apply (`client/__init__.py:545 _verify_sig`) | Versioned app dirs | **Post-patch: hash of installed binary verified** — a corrupt patch is detected after apply, not by the user's crash |
| getdown (threerings) — BSD-2-Clause (LICENSE read in clone) | Per-file: downloads only changed files | **Signed `digest.txt`** covering every file (certs in `EnvConfig.java:208`) | Version-dir switching | Previous version dir retained |
| hazel (zeit) — MIT | n/a | n/a | Tiny update *server*: caches GitHub Releases + serves Squirrel `RELEASES` | n/a |
| update-electron-app — MIT | via Electron/Squirrel | via Squirrel | Sets autoUpdater feed (update.electronjs.org), check on launch + interval | via Squirrel |
| Chocolatey — Apache-2.0 | No (package-level full installs) | Checksums in package scripts; pinning | Windows package manager (`choco upgrade`) — the "boring" enterprise path | Package version pinning / previous .nupkg |

**Update verdict for v2:** the field converged on one shape — *verify signature before download completes → stage in a sibling directory → wait for the app to exit → atomic rename swap → keep the old version until the new one proves itself → post-apply hash check.* Nobody swaps files under a running process, and nobody trusts an unsigned payload anymore.

---

## PART D — HEALTH, DEAD-MAN'S SWITCHES, AND THE AGENT-SPECIFIC DESIGNS

### D1. healthchecks (healthchecks/healthchecks) — BSD-3 → code OK
**Dead man's switch:** the job must *ping*; period + grace window (`hc/api/models.py:202,300`). Silence = alarm. Crucially, a ping is **proof of completed work**, not proof a process exists — the exact check that catches a hung-but-alive JARVIS whose brain loop wedged mid-turn.

### D2. uptime-kuma — MIT → code OK
External monitoring with **anti-flap at the monitoring layer**: a failed check enters PENDING and retries up to `maxretries` at `retryInterval` before declaring DOWN (`server/model/monitor.js:421,452`). One failed probe is weather, not climate.

### D3. docker-autoheal — MIT → code OK
Polls container health every 5s (`AUTOHEAL_INTERVAL`), restarts `unhealthy` ones, label opt-in, `start_period` grace + 10s stop timeout. Rides Docker's own HEALTHCHECK state machine — the supervisor does as little as possible because the platform already computes health.

### D4. ⭐ cdog (dongocthanhchau/cdog) — MIT → code OK — **the most JARVIS-shaped design in the entire scan**
A watchdog built specifically for an AI-agent service. File-drop JSON request queue; the restart ritual is:
1. **Backup before action** — git patch + HEAD hash + tar snapshot, keep last 5.
2. **Pre-test** (health/smoke, including an actual LLM tool-calling probe — `scripts/test_llm_tool_calling.py`).
3. Restart → grace period → **post-test**.
4. **Post-test fails → restore the backup (automatic rollback).**
5. **Guards** (`cdog.py:14-22,43-122,125-200`): `COOLDOWN_SECONDS=900` between rollbacks, `MAX_ROLLBACKS_PER_DAY=50`, then **ESCALATE to a human (Telegram alert) and STOP auto-restarting**. State persisted as JSON.
This is the only repo in 40 that treats "the update/restart itself might be the thing that's broken" as a first-class case — and it already speaks Telegram.

### D5. openclaw-watchdog (hrygo) — **NO LICENSE → ideas only**
Go watchdog for an agent gateway:
- **Backoff with jitter, capped correctly** (`internal/backoff/backoff.go`): `delay = Base × 2^attempt`, **±25% jitter applied BEFORE the `min(delay, Max)` cap** (jitter-after-cap is the common bug; they avoid it).
- Health parsing distinguishes **"live" vs "ready" vs "mcpReady"** from the gateway's JSON status — three different promises, three different checks.
- Dedicated deadlock-detector package + restart-rate state machine.

### D6. cabot (arachnys/cabot) — MIT
Self-hosted monitoring/alerting, now largely unmaintained. Failure story: the watcher stack itself needed watching and nobody did — recursion has to bottom out at something *simpler* than the system it guards (see god, A10).

### D7. Log rotation, distilled
- **lumberjack (natefinch) — MIT:** the 4 knobs every app should copy: `MaxSize` (default 100MB) / `MaxBackups` / `MaxAge` days / `Compress` (gzip). In-process, zero config files.
- **logrotate — GPL-2 (ideas):** external rotation driven by a **state file** recording last-rotate time per file; `copytruncate` vs create+signal trade-off (copytruncate exists precisely because long-running daemons hold their log fd open — same problem NSSM's online rotation solves).

### D8. keepalived — GPL-2 (ideas only)
VRRP failover: weighted health scripts adjust a node's *priority*; notify scripts fire on master/backup transitions. Single-PC transferable idea is small but real: **health should be a weighted score feeding a priority**, not a boolean — a JARVIS with a dead cloud provider but healthy local brain is degraded, not down.

### D9. gorakhargosh/watchdog — Apache-2.0
Filesystem-events library (name collision with the watchdog *concept*); its `watchmedo auto-restart` restarts a subprocess when files change — dev-grade supervision only, but the pattern (restart-on-change) is what a future JARVIS skill hot-reload wants.

---

## FAILURE STORIES (the scar tissue is the curriculum)

1. **pm2's empty-dump guard** — a crashed supervisor process overwrote `dump.pm2` with an empty process list, so `resurrect` restored *nothing* after reboot. Fix shipped in code: refuse to persist an empty checkpoint over a non-empty one. → *A dying process must never be trusted to write the checkpoint it dies on.*
2. **god ate itself** — the Ruby supervisor bloated until it was the resource problem. → *The supervisor must be an order of magnitude smaller/simpler than the supervised.*
3. **immortal vanished** — the GitHub repo is gone; a 24/7 reliability tool whose own home wasn't reliable. → *Vendor your supervisor; don't fetch it at runtime.*
4. **cabot recursion** — unmaintained watcher watching watchers. → *The chain must terminate at the OS (SCM/systemd), which is maintained by someone else.*
5. **Squirrel → Velopack rewrite** — Squirrel.Windows' apply step was fragile enough under locked-file/AV conditions that its own successor rewrote the core in Rust around one idea: rename directories, retry IO, never delete in place. → *On Windows, rename is the only atomic verb you truly have — for binaries (minio) and for whole version dirs (Velopack).*

---

## TOP 5 MECHANISMS (field-wide, code-evidenced)

1. **Counted backoff → FATAL, with uptime-based reset.** Every serious supervisor converges here; only the curve differs: Supervisor linear 1,2,3s→FATAL@3; pm2 `min(15s, prev×1.5)` reset@30s uptime; NSSM `2^(n-1)`s cap 128s reset by surviving 1.5s; systemd geometric `RestartSteps` + `StartLimitBurst`. The invariant: **retries are a budget, the budget refills only with demonstrated uptime, and exhaustion is a state (FATAL), not a faster loop.**
2. **Escalation over looping (OTP restart intensity).** >MaxR restarts in MaxT → the supervisor kills its whole subtree and itself. Failure moves *up* to a layer with more context — ultimately, to the human (cdog's Telegram escalation is the same idea at product level).
3. **Verified restart with rollback (cdog).** Backup → pre-test → restart → post-test → auto-restore on failure, with cooldown + daily cap. Restarting is a *transaction*, not an event.
4. **Proof-of-work health, not process existence (healthchecks + systemd WatchdogSec + s6 notification-fd).** A ping/`WATCHDOG=1`/readiness signal emitted from inside the work loop catches the hung-but-alive failure — the exact failure a process-alive check can never see.
5. **Atomic directory/binary swap updates with verify-before + verify-after (Velopack / minio / Sparkle / PyUpdater / TUF).** Ed25519 signature checked before apply, staged sibling version, swap only after the app exits (`--waitPid`), old version retained, installed result hash-checked. Delta is an optimization (capped chains, size-gated); the swap discipline is the safety.

---

## TOP 3 STEALS FOR JARVIS v2 — what replaces the lone `JARVIS.bat`

### Steal 1 — cdog's verified-restart ritual as JARVIS's self-healing core (MIT, code borrowable)
A small `jarvis/supervisor.py` ritual for both crash-restarts and updates: snapshot `data/` (tar, keep 5) → restart → grace → **post-test = one real brain turn + one tool-call probe against the local stub/Ollama** (cdog's LLM smoke test, adapted) → probe fails → restore snapshot, count the rollback. Guards copied in spirit: long cooldown between rollbacks, a small daily cap, then **escalate via the existing Telegram phone channel and stop** — JARVIS rings Owais instead of boot-looping at 3 AM. This plugs straight into v2's existing proactivity/urgent enum and session store.

### Steal 2 — Two-layer supervision: OS as the outer net, a tiny Python state machine inside
- **Outer layer (WinSW pattern, MIT):** install JARVIS as a Windows service (or logon-task fallback) with SCM failure actions — 1st failure restart after 5s, 2nd after 30s, counter reset after 1 healthy hour. If everything Python dies, SCM is still standing (cabot/god lesson: the chain must bottom out at the OS).
- **Inner layer:** one small stdlib Python supervisor process owning the chat/voice children, implementing the Supervisor/OTP hybrid: states STOPPED/STARTING/RUNNING/BACKOFF/FATAL; **exponential backoff `min(60s, 2^n × 2s)` with the counter reset only after 60s of demonstrated uptime** (pm2's reset rule, NSSM's curve); **flapping breaker** (Circus/systemd): 5 restarts in 10 min → FATAL + escalate, never a 6th silent retry; **fast-death rule** (gosuv/ochinchina): a child that has never survived 10s even once goes straight to FATAL — it's misconfigured, not unlucky.
- **Checkpoint:** `dump.json` written on clean shutdown AND by a heartbeat thread — with pm2's scar-tissue guard: **never overwrite a non-empty checkpoint with an empty one.** On startup, resurrect = restore session id + pending reminders/proactivity state from the checkpoint + SQLite WAL (which v2 already has).

### Steal 3 — Velopack/minio/Sparkle update protocol for ZIP-free updates
Today Owais hand-carries ZIPs and must remember to copy `data/` across. Replace with: versioned sibling dirs (`jarvis-0.9/`, `jarvis-1.0/`) + a tiny `Update.exe`-style stub (the thing the desktop shortcut points to) that always launches the newest *verified* version. Update flow: download → **Ed25519 signature verify (Sparkle/TUF discipline; signing key offline)** → stage in sibling dir → post-stage hash check (PyUpdater) → hand off to the stub with a wait-for-PID exit handshake (Velopack `--waitPid`) → atomic rename swap, old dir kept → first launch of the new version runs Steal 1's post-test; failure → stub points back at the old dir and JARVIS reports the rollback. `data/` lives OUTSIDE the version dirs, so the copy-the-data-folder ritual dies forever. Delta updates: skip for now — full-zip + this swap discipline is the 95% win; PyUpdater's rule (delta only if patch bytes < full, chains ≤4) is the note to reopen if download size ever hurts.

**Runner-up steals (cheap, do them in the same pass):** healthchecks-style dead-man ping — JARVIS writes a "turn completed" heartbeat to the supervisor every N minutes; silence past grace = wedged, restart (catches hung-brain, the failure process checks miss). systemd-style internal watchdog petting from the voice loop. lumberjack's 4 knobs as v2's log-rotation defaults (100MB / 5 backups / 14 days / gzip). Weighted health score (keepalived) for the provider pill: degraded ≠ down.

---

## HONESTY LEDGER
- **Code-read (40):** supervisor, superlance, circus, ochinchina/supervisord, pm2, monit, s6, systemd (sparse: service man pages + core service sources), erlang/otp (sparse: design-principles docs), god, gosuv, ncolony, honcho, winsw, nssm (kirillkovalenko fork), kardianos/service, takama/daemon, Sparkle, Squirrel.Windows (sparse: src/Squirrel + StubExecutable), Velopack (sparse: Rust bins + C# lib), Omaha (sparse: protocol headers only), python-tuf, minio/selfupdate, tj/go-update, PyUpdater, getdown, hazel, update-electron-app, chocolatey/choco, healthchecks, uptime-kuma, docker-autoheal, cdog, openclaw-watchdog, cabot, logrotate, lumberjack, keepalived, gorakhargosh/watchdog.
- **[DOCS]/partial:** Omaha core update engine (sparse checkout yielded protocol definitions only — Courgette/staging claims are protocol-level, not code-traced); systemd RestartSteps math is from the shipped man pages in-clone; OTP intensity from the in-repo design-principles doc.
- **Missing:** nbari/immortal (repo deleted from GitHub — verified during clone batch; documented, not read).
- **License flags:** pm2 + monit = AGPL-3.0 → ideas only. systemd/logrotate/keepalived = GPL family → ideas only. openclaw-watchdog = no license → ideas only. Squirrel.Windows = MIT per project [MC — root COPYING fell outside the sparse checkout and was not re-read]. NSSM = public domain per the author's site [MC — asserted from README lineage, no license file in the fork]. Everything recommended as a *steal* above is MIT/BSD/Apache/public-domain and code-borrowable with attribution.


---

## PART E — SUPPLEMENT (parallel re-dispatch worker): JARVIS v2 gap map + the quadrants Parts A–D didn't cover

> Provenance: this section was written by the re-dispatched Team 19 worker (the original
> worker, presumed dead, delivered Parts A–D into this same file — verified by spot-check:
> Supervisor backoff `process.py:171-172` and states FATAL=200/BACKOFF=30 match the clones).
> Part E adds what the main scan's target list lacked: feature flags/kill-switches, a
> concrete log-rotation policy, error grouping, SQLite continuity, and — most important —
> a gap map verified against JARVIS v2's actual code with file:line references.
> Additional repos code-read here: Flipt, Gatus, Watchtower, Litestream, Loguru
> (+ independent re-verification clones of Supervisor, lumberjack, WinSW, Velopack,
> Squirrel.Windows, NetSparkle, docker-autoheal). Combined unique coverage: **~45 repos**.

### E0. JARVIS v2 baseline — what already exists (read from `~/workspace/jarvis-v2` code, 2026-10-20)

**Exists and is genuinely good:**
- **Health suite** — `jarvis/maintenance.py:388 run_health_checks()`: DB integrity
  (`check_db_integrity` :222), disk, RAM, backup freshness, log *pressure*, crash state,
  uptime, GPU, Ollama reachability → structured `HealthReport`.
- **Backups** — `create_backup()` (:511) with rotation (`_rotate_backups` :554) and
  `restore_backup()` (:566). DB copies are done *right*: `_snapshot_db()` (:483) opens
  the source read-only via URI and uses the sqlite3 **backup API** — never a raw copy of
  a hot WAL database.
- **Crash-loop self-detection** — `note_startup()` (:720) / `note_clean_shutdown()` (:742)
  count consecutive unclean starts; `crash_loop_suspected()` (:757) → `auto_recover()` (:762)
  restores the newest backup and resets the counter. Limit: it runs *inside the next
  start* — nothing external revives a dead or hung process, and it restores data while
  booting the same code/config that just crash-looped (no safe mode).
- **Single-instance lock** — `InstanceLock` (:814), stale-aware via PID liveness +
  heartbeat `refresh()`.
- **Config safety** — `jarvis/config.py`: atomic writes with `.bak`; a corrupt file is
  *quarantined aside* and `ConfigError` raised — bytes never wiped.
- **Downloads** — `jarvis/setup.py:595 download_model()`: `<dest>.part` + HTTP Range
  resume + SHA-256 verify before rename; `.part` kept on mismatch for inspection.

**Confirmed GAPS (priority order):**
1. **No update mechanism.** `setup.py:833 check_updates()` is an explicit *stub* that
   always returns `update_available: False`. Its docstring already carries the Wave-3
   contract (signed manifest verified *before* trusting any URL, background download,
   prompt-once, N-1 installer cached, post-apply preflight smoke test, one-click
   rollback, never silent / never mid-session / never LLM-triggered). The contract is
   written; the machinery is not. → Main scan's Steal 3 is the fix.
2. **No external crash supervisor / no safe mode.** → Main scan's Steals 1+2 are the fix.
3. **No kill-switch / feature flags.** Grep for `feature_flag|kill_switch|flagsmith|
   unleash` across `jarvis/` = **zero hits**. A bad skill, provider preset, or config
   value can only be fixed by editing files on the owner's PC. → E1 below.
4. **No log rotation policy.** Zero `RotatingFileHandler`/`maxBytes` anywhere in the
   repo; logs are only *measured* (`_check_log_pressure` :320) and pruned by age in
   `cleanup_data_dir()` (:632). → E2 below.
5. **No error grouping.** Crashes surface as raw tracebacks; nothing counts "this same
   failure happened 14 times." → E3 below.
6. **Backup RPO, not correctness.** Snapshots are correct but point-in-time; everything
   since the last snapshot is the recovery-point gap. → E4 below.
   (Dead-man's switch: covered by main scan D1 — v2 has none; the heartbeat design is
   in runner-up steals there.)

### E1. Kill-switches & feature flags — the missing quadrant

- **Flipt (flipt-io/flipt) — [CODE], Apache-2.0:** single Go binary; flags/segments/
  rollouts stored declaratively, including **in Git**; environments isolate flag sets;
  percentage rollouts for gradual exposure. Transferable lesson: *flags-as-files is a
  legitimate architecture* — a hosted flag server is a multi-team luxury.
- **OpenFeature (open-feature) — [PATTERN]:** the spec's one idea worth copying is the
  **provider interface**: evaluation call sites never know where flags live, so the
  backing store can graduate file → remote without touching feature code.
- **Flagsmith / Unleash / GrowthBook — [WEB, pattern level]:** hosted model = server +
  SDK with **local evaluation from a cached payload**. The kernel that transfers to a
  desktop app: (1) evaluation is local and cached — a flag fetch must never block a
  conversation turn; (2) **absent flag = fail-safe default** (risky feature defaults
  off, core feature defaults on); (3) flags are useless without an owner-visible
  list of what they control.
- **Minimal v2 design (stdlib-sized):** a schema-validated `flags` section in
  `config.py` (it already has typed `Field`s, atomic writes, quarantine) +
  `flags.is_enabled(name)` consulted at `gate.py` dispatch for skills/providers;
  optional remote override = one signed JSON fetched opportunistically under the same
  signature discipline as updates. Effect: a bad feature dies by flipping one boolean —
  pushed as a config change, not an app release. This is the cheapest reliability
  mechanism in the entire scan relative to what it prevents (a broken auto-approved
  skill currently has *no* off-switch short of file surgery).

### E2. Log rotation policy — copy the 4 knobs, at desktop scale

- **lumberjack (natefinch/lumberjack) — [CODE verified], MIT:** `lumberjack.go:41`
  `defaultMaxSize = 100` (MB); the policy is exactly four knobs — `MaxSize` /
  `MaxBackups` / `MaxAge` (days) / `Compress` (gzip) — enforced in-process at write
  time; rotated files carry timestamps; cleanup applies count *and* age.
- **Loguru (Delgan/loguru) — [CODE], MIT:** `loguru/_logger.py:348-354,649-664` —
  `rotation` accepts size / int bytes / time-of-day / timedelta / callable, checked
  before each write; `retention` (count, duration, or callable) applied at rotation.
  Confirms the same two-axis design (when to roll × what to keep) in Python idiom.
- **stdlib `logging.handlers.RotatingFileHandler`** already ships both axes
  (`maxBytes`, `backupCount`) — v2 needs **zero new dependencies**.
- **v2 policy:** per-log-file 10 MB × 5 backups (lumberjack's 100 MB is server scale),
  keep the existing age-based `cleanup_data_dir()` for the data dir as a whole, and let
  the existing `_check_log_pressure` health item become the alarm for "rotation itself
  stopped working." Failure prevented: the slow-motion disk-full that currently has a
  detector but no actuator.

### E3. Error grouping — Sentry's fingerprint, minus Sentry

- **sentry-python / GlitchTip — [PATTERN/WEB]:** Sentry groups events by a
  **fingerprint**: the stack trace normalized (in-app frames only, addresses and
  volatile values stripped) and hashed; same hash → same issue, with a counter and
  first/last-seen timestamps. GlitchTip proves the server side can be tiny and
  self-hosted — but for a single-PC assistant even that is overkill.
- **v2 steal (stdlib-sized):** an appender in the existing `jarvis/observability.py`
  that, on unhandled exception, writes one JSON line with a fingerprint = hash of the
  top-3 in-app frames (module + function only). `maintenance.py`'s health report can
  then surface "exception X — 14 occurrences, first 2026-10-03, last today" instead of
  traceback soup. Failure prevented: the recurring crash nobody notices because each
  instance looks like a one-off in an unrotated log.

### E4. SQLite continuity — Litestream's lesson, honestly scoped

- **Litestream (benbjohnson/litestream) — [CODE/README], Apache-2.0:** continuous WAL
  replication: it tracks WAL frames and ships segments to replica storage; restore =
  replay to a point in time. Built for servers losing whole machines.
- **Honest scoping for v2:** v2's snapshot correctness is already right (E0). The only
  transferable piece is *continuity between snapshots* — and on a single PC whose threat
  model is "bad update / crash loop," the existing snapshot + `auto_recover` covers it;
  WAL shipping earns its complexity only when off-PC backup arrives (e.g., alongside
  the phone/sync work). Recorded as a deliberate deferral, not an oversight.

### E5. Two smaller confirmations

- **Watchtower (containrrr/watchtower) — [CODE], Apache-2.0:** container auto-updater
  whose most-used mode in the wild is **monitor-only + notifications**, with
  pre/post-update lifecycle hooks (`pkg/lifecycle`) and cleanup of old images.
  Independent confirmation of v2's written update contract: *notify first, apply on
  consent, clean up the old version after* — the field's auto-updaters get run in
  manual-approval mode by the people who operate them longest.
- **Gatus (TwiN/gatus) — [CODE], Apache-2.0:** health defined as **conditions-as-data**
  in YAML (`[STATUS] == 200`, `[RESPONSE_TIME] < 500`, body/IP checks) evaluated per
  endpoint. v2's health suite already does this in Python code; the transferable idea
  is letting *users* add checks as data (a dropped-in check file) without code changes —
  which is also exactly how new `maintenance.py` checks should be added as JARVIS grows.

### E6. Supplement verdict — if only three things from Part E happen

1. **Kill-switch flags in config.py + one `is_enabled` check in gate.py** (E1) —
   smallest code, largest blast-radius reduction.
2. **RotatingFileHandler policy 10 MB × 5 on every log sink** (E2) — one sitting,
   deletes an entire failure class.
3. **Exception fingerprinting into observability + a "top recurring errors" line in the
   health report** (E3) — turns silent recurrence into a visible count.
(Combined with the main scan's Steals 1–3 — verified-restart ritual, two-layer
supervision, signed sibling-dir updates — these six close every gap in E0.)
