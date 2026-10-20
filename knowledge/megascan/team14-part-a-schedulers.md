# MEGA-SCAN TEAM 14 · Part A — Scheduling Systems in Agent Apps

Researcher: subagent (team 14), 2026-10-20. Method: `git clone --depth 1` of each repo (API rate-limited out), reading actual scheduler code. 11 repos covered: 8 cloned code-first + skales (docs-only, source withdrawn), instar (README-only check, 155M clone trimmed), coddy-agent (Go scheduler).

Legend: **[CODE]** = read in source · **[README]** = README/docs claim · **[DOCS]** = shipping user guide · **[INFERENCE]** = my conclusion from the pattern.

---

## 1. skalesapp/skales (2200★) — proprietary distribution repo

- LICENSE: **[CODE]** No OSS license — `LICENSE` is a proprietary End User Licence Agreement; `COMMERCIAL-LICENSE.md` and `TRADEMARK.md` also present. Source removed in 12.9.30 (README states source snapshot withdrawn).
- Trigger model: **[DOCS]** (docs/skales-guide.html, README.md): cron expressions (`0 9 * * 1-5`, read in user's time zone; schedules pinned to their creation time zone), plus event triggers: watched folder, watched mailbox (once per message, deduped across restarts), webhook (POST becomes a Tasks-page task). Natural-language scheduling: type "every morning" in chat → engine extracts schedule + confidence score; dry-run mode simulates a run first ("One scheduled task, tried as a dry run first"). 16 blueprint jobs (mail watch, digest, morning brief, watches).
- Missed runs: **[DOCS]** Skales CATCHES UP after sleep: "Skales catches up scheduled runs that were missed while the machine slept, and a timer the system froze says so rather than drifting silently."
- Failure rule: **[DOCS]** "One job store, one clock… Every job… follows the same failure rule (three failures in a row pause it, and it says so)."
- Retries: **[DOCS]** disk-wake write retry (job writes that fail while a parked drive wakes are retried). Parts of a plan "retry once; a repeated failure becomes a named gap."
- Quiet hours: **[DOCS]** YES — all notifications (agent finished, answer ready, Telegram, Friend Mode check-ins) honor mute switch + quiet hours + system-notification switch. Time zone re-read at every start.
- Failure stories (from guide/changelog): **[DOCS]** timezone was once read once at setup and never updated (broke all schedules on travel — fixed by re-reading at every start); background jobs sometimes answered with raw tool-call markup (now cleaned, empty answer counts as failed); model written tool call as text instead of running it dropped tasks.
- Approval gating on scheduled runs: **[DOCS]** a job told "don't ask me first" only skips the pre-start ask — *in-run approvals still fire* ("anything dangerous still asks you, mid-run, by name"); job runs remain listed, stoppable.
- Verdict: best-in-class UX vocabulary (confidence scores, dry-run, 3-failure pause, per-schedule TZ), but proprietary + no code to steal. Steal the *rules*, not the code.

## 2. YYHDBL/AgentCrew (252★) — no license

- LICENSE: **[CODE]** none — repo root has no LICENSE file (README/CONTRIBUTING/docs only). **Do not ship its code.**
- Trigger model: **[CODE]** `backend/agentcrew_core/cron/schedule.py`, `models.py`: three typed schedule kinds — `at` (UTC unix-ms timestamp), `every` (ms interval, min 1000ms), `cron` (5- or 6-field, deterministic only — rejects `H`/`R` jitter tokens, `croniter` strict-validated, IANA tz required, per-schedule `tz`).
- Persistence: **[CODE]** SQLite (`cron_jobs`, `cron_job_runs`, `cron_change_log` tables; schema_v series) with revision field per job; scheduler (`cron/scheduler.py`) runs one asyncio timer per job, refresh on `CRON_JOB_CHANGED` bus event.
- Missed runs: **[CODE]** NO catch-up — `register_due()` inserts an occurrence with status `missed` and literal note `"错过到期窗口，不补跑"` ("missed the due window, no backfill"). Startup and clock-gap detection (`_observe_gap` heartbeat, `missed_range()` computes count/through for cron) but only records. "at" jobs are disabled after a missed fire. README confirms: "Missed schedules are recorded when the application returns and are not automatically replayed." (README = English + zh-CN.)
- Retry: **[CODE]** occurrences have `retry_no`; authorization module (`cron/authorization.py`) exists — per-job pre-authorized tools (`pre_authorized: list[Authorization]` with tool/pattern) so the scheduled run only asks for what's outside its pre-approved set.
- Overlap: **[CODE]** `store.conflict()` — if a prior occurrence of the same job is still fired/retry_wait/interrupted/pending_verification, the new slot is recorded `skipped` with a conflict note. Also checks conversation/task/pending-verification state for `existing`-conversation mode. Overlap → skip, never queue pile-up.
- Grace window: **[CODE]** `GRACE_MS = 2000` — a slot is only "missed" if the app was more than 2s late past it (plus startup/clock-gap detection).
- Failure stories: **[INFERENCE]** the entire missed_range implementation is a careful re-enumeration of cron occurrences (fold/DST handling), suggesting DST-correctness bugs were fought. `change_id` requirement on create (`^[A-Za-z0-9_-]+$`) suggests idempotency races.
- Verdict: the most *engineered* correctness-wise (typed schedule union, conflict matrix, audit chain) — but unlicensed and its stack (SQLite + asyncio + bus) is heavier than JARVIS needs. Steal ideas only.

## 3. feicaiclub/forge (75★) — Apache-2.0

- LICENSE: **[CODE]** Apache-2.0 (LICENSE file).
- Trigger model: **[CODE]** `src/lib/cron/engine.ts`, `cron-parser.ts`: hand-rolled 5-field cron matcher (no library — stdlib only, supports `*/N`, `N-M`, `N,M,O`), tick every **60s**. UI (`schedule-view.tsx`): visual builder — once / every-X-minutes / hourly / daily / weekly / monthly — converted to cron string by `scheduleToCron()`. Also HEARTBEAT.md checklist heartbeat (OpenClaw-style) seeded disabled, `*/30 * * * *` default.
- Persistence: **[CODE]** SQLite (`cron_tasks`, `task_executions` tables, `ON DELETE CASCADE`).
- Missed runs: **[CODE]** none — if the app is closed during the matching minute, the run is silently lost. No catch-up, no missed-record.
- Retry: **[CODE]** none on the engine level (only executor catches errors and logs status `error`).
- Overlap: **[CODE]** `executingTasks` set — a tick skips a task already executing (no pile-up), but no queueing of skipped slots.
- Quiet hours / urgency: **[CODE]** none found. Notifications exist (Feishu/Telegram/Discord) only as task-result delivery; heartbeat emits `alert` status only when checklist result isn't `HEARTBEAT_OK` ("silent when nothing to report").
- One-shot semantics: **[CODE]** once-tasks encoded as cron with specific day+month (`cronParts[2] !== '*' && cronParts[3] !== '*'`) are auto-disabled after firing. Past-date prevention at the UI layer only.
- Verdict: minimal stdlib-friendly design (own matcher, 60s tick, tasks.json-style tables) — closest to what a Python stdlib scheduler would look like; but its missed-run blindness is the flaw JARVIS must avoid.

## 4. milisp/codexia (938★) — MIT

- LICENSE: **[CODE]** MIT (`LICENSE`, ©2026 milisp).
- Trigger model: **[CODE]** `crates/automation/src/`: visual schedule types (`Daily` with hour/minute, `Interval` with allowed hours ∈ {1,2,3,4,6,8,12,24} — divisors of 24 only, so `0 30 0/6 * * MON` keeps uniform gaps) compiled to a cron expression by `schedule_to_cron()`, fired via `tokio-cron-scheduler` (6-field-with-seconds cron, local TZ). ALSO event triggers: `AutomationTrigger::{GitBranch, NewFile, CiFailed, IssueAssigned}` polled while running.
- Persistence: **[CODE]** JSON file `~/.codexia/automations.json` (atomic write: temp file + rename — crash can't truncate), runs in DB via `codexia_db::automation_runs`.
- Missed runs: **[CODE]** explicitly NO replay — model.rs comment: "Checked by polling while Codexia runs; what changed while it was closed is not replayed."
- Retry: **[CODE]** none (no retry config in model/schedule/execution).
- Overlap: **[CODE]** per-task in-flight guard in `execution.rs` — a tick while the same task runs emits `automation:run/skipped` ("a previous run is still in flight"), treated as neither success nor failure; covered by a test asserting no queue pile-up.
- Approval/quiet: README money rule (payments/purchases/deletions always wait for user approval "even in scheduled runs"); per-bot permissions; results land in bot history with unread badge + system notification. No quiet-hours in code.
- Verdict: schedule-type→cron compilation + divisors-of-24 interval trick are neat; JSON store with atomic rename is copyable. Apache-style clean Rust, MIT = safe.

## 5. mukiwu/orbit-agents (47★) — MIT (package.json)

- LICENSE: **[INFERENCE]** `package.json` `"license": "MIT"`; no LICENSE file seen — package.json declaration only.
- Trigger model: **[CODE]** `src/main/scheduler.ts`: `node-cron` 5-field cron per task + `week_interval` for bi-weekly cadences (next-run computation walks 500 candidates to skip ineligible weeks). Event triggers too: folder inbox scan every 10s, website SHA-256 content-hash change.
- Persistence: **[CODE]** SQLite (`database.ts`) — tasks, execution_logs, run snapshots, inbox file claims (file claimed by path+mtime+size so each file fires once).
- Missed runs: **[CODE]** none recorded — node-cron style, missed while closed = lost.
- Retry: **[CODE]** YES — `MAX_RETRIES = 3`, backoff `[30s, 60s, 120s]`, retries only network/transient errors via `isNetworkError()` pattern list (ENOTFOUND, ETIMEDOUT, 429, rate limit, 5xx…); non-network errors stop immediately. This is the cleanest retry design of all reviewed.
- Approval gating: **[CODE]** `require_review` automation flag → run forced into read-only mode (`skip_permissions=false`, no MCP tools, no writes/mail) and result becomes `pending_review` requiring human approve/reject; rejection cancels. Full run snapshot saved → `replayRun()` and `resumeDeliveryRun()` for failed deliveries.
- Missed-slot overlap: folder claim (`claimInboxFile`) and run snapshot per execution guard double-fires.
- Verdict: retry-only-on-transient + review-mode + replay snapshots = three strong steal-worthy mechanisms; MIT-ish licensing okay.

## 6. kandada/fastclaw (169★) — GPL-3.0

- LICENSE: **[CODE]** GPL-3.0. **Ideas only, never code** (per standing GPL-3.0 caution).
- Trigger model: **[CODE]** `gateway/cron_scheduler.py`: 5-field cron, pure-Python asyncio, tick every **60s**, `croniter` for next-run; stdlib-style (Python's threading model mirrors what JARVIS could do).
- Persistence: **[CODE]** JSON `workspace/data/cron/tasks.json` (array of {id,name,schedule,description,agent_id,session_id,enabled,last_triggered}). Disk↔memory two-way merge (`_merge_disk_tasks` — reads disk-added tasks before each save/check so the agent editing tasks.json directly never loses work). Skill doc forbids `crontab -e` for management.
- Missed runs: **[CODE]** configurable `max_missed_seconds` (default 300): on check, croniter walks forward from `last_triggered`; slots older than the threshold are SKIPPED (counted, logged), within-threshold fire. I.e. short outages recover, long ones don't backfill.
- Overlap: per-session asyncio queues — runs execute through a single per-session queue so scheduled messages serialize (no parallel pile-up); manual `trigger_task()` is explicit user intent and bypasses `enabled` ("不受 enabled 状态限制").
- Prompt format: `[Scheduled: name]` + "This is an automated scheduled run…" injected as a message into the session via SSE push callback.
- Verdict: nearest to JARVIS's Python-stdlib reality; the missed-window threshold + disk-merge + per-session queue are the steals — but GPL means re-implement from the idea.

## 7. t0dorakis/murmur (32★) — MIT

- LICENSE: **[CODE]** MIT.
- Trigger model: **[CODE]** README + `src/daemon.ts`: daemon ("The AI cron daemon") + `HEARTBEAT.md` prompt files with YAML frontmatter: `interval: 30m|1h|6h|1d` or `cron:` expr + `tz:`; each beat = fresh CLI invocation of Claude/Codex/pi with full tool access. `murmur beat` runs one immediately.
- Persistence: `~/.murmur/config.json`; response protocol: `HEARTBEAT_OK` (silent, just logged) vs `ATTENTION: <summary>` (surfaced in TUI).
- Missed runs: **[INFERENCE]** minimal daemon — no catch-up logic found in README/docs; tick-driven while running.
- Verdict: the HEARTBEAT.md-as-code contract (silent-when-ok) is the steal: proactivity should DEFAULT to silence and only ring on ATTENTION. Matches JARVIS's call-ringing model (don't interrupt for nothing).

## 8. DnzzL/herdr-automations (18★) — MIT

- LICENSE: **[CODE]** MIT.
- Trigger model: **[README]** one `automations.yaml` file (no store!): `cron: "0 9 * * 1-5"` + agent + prompt + timeout + fresh git worktree per run. "One YAML file, no store."
- Persistence: YAML only; run history append-only JSONL: `scheduled → running → done|failed|skipped|missed`.
- Missed runs: **[README+CHANGELOG]** the standout: occurrences computed off the WALL CLOCK; on wake from sleep, runs due during sleep fire within `catch_up_minutes` (default 120, `-1` = never catch up); anything older recorded `missed`. Failed/missed runs raise a Herdr toast (in-app panel, not OS notification).
- Overlap: **[README]** tick firing while the same automation is still working is skipped (never queued); ALSO a wizard warns of schedule overlaps at authoring time ("Herdr starts them all… it just makes sure you knew").
- Retry: CHANGELOG mentions a fixed bug "every wait-and-retry was skipped" — retries exist around waits in runs.
- Verdict: wall-clock catch-up with a per-task window + overlap warning at authoring + fail-loud-toast. Strong ideas; tiny repo, MIT = safe.

## 9. tintinweb/pi-schedule-prompt (122★) — MIT

- LICENSE: **[CODE]** MIT.
- Trigger model: **[CODE]** `src/scheduler.ts`: 3 schedule types — 6-field cron (seconds, via `croner`), `interval` ("5m"/"1h"), `once` (ISO or relative `+10s`, past-date rejected, <5s rejected). Tool + UI (cron-widget, jobs-view) for pi-coding-agent extension.
- Persistence: `CronStorage` with `lastStatus`, `runCount`, `nextRun`, `session` (jobs bind to a session so two pis in same cwd don't double-fire — re-reads fresh job from storage before every fire to avoid stale-closure bugs; code comments document past bugs they fixed).
- Missed runs: **[INFERENCE]** none — interval/cron driven by live tickers, once-jobs in the past are disabled with error.
- Execution: fires into the agent session as a message (or in a fresh subagent with chosen model + `notify` flag waking the parent only if true — matches ring-or-silent!). Stale `running` flags cleared on start after kills.
- Verdict: session-scoped jobs (no double-fire), stale-state cleanup, notify-gated wake = thoughtful multi-instance safety; MIT safe.

## 10. moadim-io/daemon (56★) — MIT

- LICENSE: **[CODE]** MIT (©2026 Moadim). Rust AI-agent daemon with REST/MCP.
- Trigger model: **[CODE]** `src/routines/`: each routine = folder with `routine.toml` (title/agent/prompt/repos/enabled/power_saving_exempt/ttl/max_runtime_secs) + `schedule.cron` sidecar + `state.local.toml` (runtime trigger state, gitignored). Internal scheduler with cron parsing in host-local TZ (legacy OS-crontab sync retained only as compat).
- Missed runs: **[CODE]** alert-only — `missed_scheduled_run_at()` computes "latest scheduled fire elapsed without a matching trigger record" but the doc comment says explicitly: "This is an alert-only signal: it never spawns a catch-up run." 60s grace.
- Governance: **[CODE]** `snoozed_until`, `skip_runs` counters, global lock, per-machine targeting (`machines` filter), `power_saving_exempt` (battery/Low-Power gating). Runs get watchdog max-runtime and workbench TTL retention. Agent malformed → surfaced as unhealthy not firing (issue #301/#404 learned from code comments).
- Verdict: file-per-routine with TOML+sidecar is git-friendly and human-editable; snooze/skip-runs/machine-scope/power-gating = best "respect the user's context" feature set seen.

## 11. coddy-project/coddy-agent (179★) — MIT

- LICENSE: **[CODE]** MIT (©2026 Pavel Rykov).
- Trigger model: **[CODE]** `external/scheduler/` (build tag `scheduler`): UTC minute-aligned daemon tick; jobs = Markdown files with YAML frontmatter (description/schedule/paused/model/agent/permission_mode). Fires `internal/agent.RunScheduledJob` as a background agent-task run.
- Persistence: flat `*.md` files in `${CODDY_HOME}/scheduler` or `<workspace>/.coddy/scheduler` + `.state` sidecar with cron checkpoint + job session id.
- Missed runs: **[CODE]** none — checkpoint written before run creation, so a slot commits atomically ("the slot does not fire again on the next tick"); missed = silently skipped, recorded only via skipped-run notes.
- Overlap: `RunningRun` check → slot skipped; `max_queue` saturation → skip with a hint to raise the knob.
- Approval gating: **[CODE]** `permission_mode: ask | accept_edits | bypass`; empty = `bypass` (unattended default), but a named agent's role/tool allowlist can only *narrow* permissions further. Project-scope jobs require explicit trust receipts (digest-keyed). First-answer-wins prompt routing to surface (Telegram vs HTTP) for background permission prompts.
- Failure stories: **[CODE]** staleCheckpointYear=1980 guard (epoch-era bug in old checkpoints); "A corrupt record is replaced rather than kept: the checkpoint it carried is untrusted" — trust-nothing-from-disk posture.
- Verdict: checkpoint-before-run atomicity + permission_mode ladder + trust receipts = solid. The `bypass`-default may be looser than JARVIS wants (JARVIS: approval PIN per sensitive command).

---

## Cross-repo synthesis (trigger model / missed / retry / persistence / quiet)

| Repo | Storage | Trigger kinds | Missed behavior | Retry | Quiet/urgency |
|---|---|---|---|---|---|
| skales | internal (proprietary) | cron + folder + mailbox + webhook | CATCH-UP after sleep | 3-fail pause; write retry | quiet hours, mute, per-type switches |
| AgentCrew | SQLite | at / every / cron | record missed, NO backfill | retry_no field | none found |
| forge | SQLite | 5-field cron | silently lost | none | heartbeat silent-when-ok |
| codexia | JSON (atomic) | schedule→cron + git/file/CI/issue events | not replayed | none | unread badge + notification; money-approval-always |
| orbit-agents | SQLite | cron + folder watch + website hash | lost (node-cron) | 3× transient-only 30/60/120s | review-mode gate |
| fastclaw | JSON tasks.json | 5-field cron | skip-if-older-than-300s, fire-if-within | none | none |
| murmur | config.json | interval / cron frontmatter | (none found) | none | HEARTBEAT_OK = silent |
| herdr | YAML file | cron | catch-up within window, else missed | in-run retry | fail-loud toast |
| pi-schedule-prompt | CronStorage | 6-field cron / interval / once | none | none | notify flag wakes parent or not |
| moadim-daemon | TOML files + sidecars | cron sidecar | alert only, never catch-up | watchdog kill | snooze, skip-runs, power gating, machine scope |
| coddy-agent | Markdown + .state | 5-field cron (UTC) | slot skipped (checkpointed) | none | permission_mode ladder |

**Industry consensus from code (not marketing):**
1. Every one stores schedules durably and reconciles on start; the two serious ones use checkpoints/watermarks (AgentCrew `cron_job_runs`, coddy `.state`, herdr wall-clock occurrences) to avoid double-fire. **The double-fire guard is table stakes.**
2. Missed-run policy is a deliberate product choice, not an omission: most choose record-only or skip; skales and herdr catch up within bounds. For JARVIS (desktop assistant, often asleep/lid-closed), bounded catch-up (herdr's `catch_up_minutes` or fastclaw's 300s) beats both extremes — but catch-up must NEVER re-fire time-sensitive actions (mailbox-once-per-message dedup is the model: idempotency keys).
3. Overlap handling is unanimous: skip the overlapping tick, never queue. (AgentCrew conflict matrix, codexia in-flight guard, orbit claim, fastclaw per-session queue, coddy RunningRun.)
4. Retry is rare and conservative: only orbit retries, and only transient/network errors with backoff. Everyone else treats a scheduled-run failure as a logged event. **For JARVIS: retry LLM-call failures with backoff, never retry the user's action.**
5. Human-readable layer over cron everywhere: visual builders, interval types, `every 5m` frontmatter, compiled schedule types. Nobody makes users write cron. Humanize display too (pi-schedule-prompt's `humanizeCron`).
6. Approval gating on scheduled runs: orbit's `require_review` (read-only dry-run → approve/reject), AgentCrew's pre_authorized tool patterns, codexia's money-approval-always, coddy's permission ladder. **JARVIS's R1 per-command confirmation + 4-digit PIN is in good company — the unanimous rule is: scheduled runs get NARROWER permissions than chat, never wider.**
7. Quiet hours: only skales does real quiet hours; the rest use silent-when-ok protocols (HEARTBEAT_OK) or notification routing. JARVIS's call-ringing model can adopt: routine results → silent log unless ATTENTION; urgent → ring.

## Failure stories worth learning from (all in code/comments/changelogs)
- skales: TZ read once at setup → all schedules wrong after travel; fixed by re-read at every start. → JARVIS: pin TZ per schedule but re-resolve machine zone on wake.
- coddy: stale epoch checkpoints; corrupt state file replaced not trusted. → JARVIS: treat state as untrusted, epoch-guard, regenerate.
- pi-schedule-prompt: stale closure captured runCount never advanced; fixed by re-reading storage before write. → JARVIS: always read-modify-write schedules.
- herdr changelog: "every wait-and-retry was skipped and the run failed instantly" (retry-timeout bug) — → test retry paths explicitly.
- codexia: payments in scheduled runs need approval "even in scheduled runs" — the money boundary.

## Top 3 mechanisms (for parent)

1. **[CODE, orbit-agents]** Transient-only retry with pattern-matched backoff (3×, 30/60/120s; network errors only, non-network fails fast) + `pending_review` read-only dry-run with approve/reject + run snapshots for replay. Best engineered execution wrapper.
2. **[CODE, herdr-automations]** Wall-clock occurrences + bounded catch-up (`catch_up_minutes`, default 120) + authoring-time overlap warnings + fail-loud toast. Best missed-run policy for a lid-closing desktop.
3. **[CODE, AgentCrew]** Typed schedule union (at/every/cron, deterministic cron only, per-schedule IANA tz) + checkpoint conflict matrix (overlap → skip with reason) + pre-authorized tool patterns per job. Best schema correctness (unlicensed — ideas only).

**Honorable:** moadim-daemon's snooze/skip-runs/machine-scope/power-gating (context-respect), fastclaw's 300s missed window + disk-merge (Python-close), skales's confidence-score + dry-run schedule creation + 3-failure pause (UX).

## Top steal for JARVIS (Python stdlib-only, call-ringing proactivity)

**One sentence:** A JSON task store with atomic writes + 5-field cron + 60s tick, where every fire (a) skips on overlap, (b) retries transient LLM failures only (30/60/120s), (c) records misses and catches up only within a 5-minute window, (d) runs with a *narrower* permission set than chat (scheduled runs need PIN-level confirmation for any consequential command — pre-approved patterns only), and (e) defaults to silent logging, ringing the call UI only on ATTENTION/urgent.

Concrete pieces to lift (all re-implementable stdlib, no license risk):
- fastclaw: `max_missed_seconds` skip/fire threshold; disk↔memory task merge; per-session FIFO queue; `[Scheduled: name]` prompt wrapper.
- orbit: `isNetworkError()` retry list + backoff schedule; `require_review` → read-only dry run → approve/reject.
- herdr: `catch_up_minutes` per task; wall-clock occurrence math; authoring-time overlap warning.
- AgentCrew idea: `{at_ms} | {every_ms} | {expr, tz}` schedule union; pre-authorized tool patterns per task.
- skales idea: natural-language schedule + confidence + dry-run before activation; 3 consecutive failures → auto-pause the task.
- murmur idea: HEARTBEAT_OK = silence; only anomalies ring.

**Licensing:** code is clean to adapt from MIT/Apache-2.0 repos (forge, codexia, orbit-agents, murmur, herdr, pi-schedule-prompt, moadim-daemon, coddy-agent). AgentCrew (no license) and fastclaw (GPL-3.0) and skales (proprietary) are ideas-only.
