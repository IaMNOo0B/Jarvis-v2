# MEGA-SCAN TEAM 14 — Proactivity, Routines & Scheduling Systems

Reverse-engineering how other assistants decide **when to speak, when to stay silent, and
what runs without being asked** — for JARVIS v2's `proactivity.py` (call-ringing model:
normal updates ring like a call and wait to be picked up; urgent events speak immediately;
closed urgent enum; 5/day learned backstop; watcher off by default).

**Method note (honesty):** the GitHub MCP hit an HTTP 429 rate limit mid-scan (4-way
parallel team load). Team-lead reads stopped at the 429 per hard-stop protocol; the three
parallel part-files (children dispatched before the limit) supply the code-level depth.
Every fact is tagged **[CODE]** (read in source), **[README]** (project's own claim),
**[SEARCH]** (search-result metadata), or **[INFERENCE]**.

**Coverage:** ~46 repos touched across 7 search terms (709 "proactive assistant",
780 "ambient agent", 1,273 "scheduled agent tasks", 1,792 "ai routines", 96 "context
aware reminders", 304 "notification intelligence", 328 "morning briefing ai" + targeted
follow-ups). **27 repos read at code level** (this file §1–3: 3; [part A](team14-part-a-schedulers.md):
11 schedulers; [part B](team14-part-b-ambient.md): 6 ambient/attention systems;
[part C](team14-part-c-briefings.md): 7 briefing/reminder systems), the rest triaged in
the table at the end. One target (sprytte/daily-briefing) could not be verified —
repo returns 404 and API quota blocked the check; flagged as a follow-up, not invented.

---

## 1. NevaMind-AI/memUBot — 464★, TypeScript — "The Enterprise-Ready OpenClaw"

- **What it is** [README]: a production re-skin of **OpenClaw** (the viral open-source
  personal agent) on top of the memU memory framework. Markets itself as "proactive,
  24/7… Continuously captures intent and acts before you ask."
- **Trigger model** [README/INFERENCE]: inherits OpenClaw's architecture — an always-on
  daemon where proactivity = the agent loop waking on schedule/heartbeat and on inbound
  channel messages, with long-term memory deciding what is worth acting on. The README's
  proactivity claims are **memory claims in disguise**: auto-flush before context
  compaction, semantic recall, shared memory pools. No urgency scoring, quiet hours, or
  interruption budget is documented — proactivity quality is delegated entirely to the
  LLM's judgment over retrieved memory.
- **Feedback loop** [README]: memory "grows smarter over time, learning team patterns,
  preferences" — implicit learning from accumulated context, not from accept/dismiss
  signals on interruptions.
- **License:** [CODE — LICENSE file read from clone] **AGPL-3.0.** → **Ideas only, never
  code** (copyleft; v2 stays clean by writing its own).
- **Steal verdict:** the *positioning* lesson, not code — in the OpenClaw family,
  "proactive" is an emergent property of (always-on loop + good memory), not a policy
  engine. JARVIS v2's explicit interruption policy is the opposite bet, and this scan
  found nobody else doing the policy-engine version well (see §5).

- **Trigger model, from code** [CODE — `src/main/tools/service.definitions.ts`,
  `service.executor.ts`]: proactivity is implemented as **agent-created background
  services**. The agent writes a Node/Python script and registers it as a service of
  type `longRunning` or `scheduled` with a **cron-like interval string** (e.g. `"*/5"`).
  Every service must declare `userRequest` and **`expectation` — "used for notification
  decisions"**: when the service produces something, the agent judges it against the
  user's stated expectation to decide whether to notify, and on which channel
  (`notifyPlatform`: telegram/discord/slack/whatsapp/line). Services are **dry-run
  validated before going live** (a scheduled service must run once and exit cleanly in
  dry-run, or it's rejected with a TIMEOUT explanation), and a supervisor checks service
  status every **60 s** (`INTERVAL_MS = 60000`, checkAndReport).
- **Interruption policy** [CODE/INFERENCE]: no scoring formula, no quiet hours, no daily
  cap anywhere in the executor — the notification decision is an **LLM judgment against
  the stored expectation string**. Flexible, but unauditable and prompt-dependent —
  exactly what v2's deterministic budget/enum design exists to avoid.
- **Steal verdict (revised):** steal the *dry-run gate* idea — any user/agent-authored
  routine in v2 must pass a one-shot dry run before it's allowed to ring. Do NOT steal
  the LLM-judged notification decision.

## 2. theexperiencecompany/gaia — 313★, Python/TS — proactive daily-life assistant

- **Trigger model** [README]: **workflows auto-activate the moment an integration is
  connected** — zero user configuration. Two trigger families:
  - **Cron:** "Inbox desk" runs **every morning at 08:00** — triages new mail, follows
    up threads waiting on you or on others, saves reply drafts (**never sends**), and
    delivers **one briefing**.
  - **Event/calendar:** "Meeting Briefing" researches attendees before you walk in;
    a "Meeting Reminder" workflow fires off calendar proximity.
- **Interruption policy** [README]: **act silently, report once.** GAIA does the work
  in the background and "when something needs you, it comes to you" — on whatever
  channel you're on (iMessage/WhatsApp/Telegram/Slack/Discord). The batching is
  structural: a whole morning of triage collapses into a single briefing message.
  Drafts-never-sends is a hard safety rule for outbound actions.
- **Feedback loop** [README]: memory "learns people, projects and preferences as you
  talk; edit, export or delete any of it" — user-correctable memory as the loop.
- **License** [CODE — LICENSE.md read from clone]: **PolyForm Noncommercial 1.0.0** —
  personal/non-profit self-hosting free, business use needs an enterprise licence.
  → **Ideas only, never code.**
- **Scheduler internals, from code** [CODE — `apps/api/app/services/workflow/scheduler.py`,
  `models/scheduler_models.py`]: a Redis/ARQ-backed scheduler shared by workflows AND
  reminders, with production-grade fire discipline:
  - **Atomic claim:** a fire must claim the task (SCHEDULED → EXECUTING) with an
    `expected_occurrence` stamp; a stale queued job whose schedule was rescheduled away
    **cannot fire**. Kills duplicate/double-ring fires.
  - **Crash reaper:** a recovery scan (`find_stale_executing(cutoff)`) resurrects tasks
    wedged in EXECUTING by a crashed worker; the pending scan filters to genuinely
    recurring tasks (a code comment warns the filter is "load-bearing": without it the
    recovery scan would re-run one-shot tasks every pass).
  - **Deactivation-reason ownership:** the system auto-pauses tasks with a typed reason
    (`user_dormant`, `integration_expired`, `subscription_lapsed`, `invalid_schedule`,
    `owner_not_found`…). **Auto-resume only ever touches tasks carrying a reason the
    system itself set — a task the user switched off has no reason and is never
    silently re-enabled.** This is the single best trust rule found in this scan.
  - Schedules carry `max_occurrences` caps and are timezone-aware throughout.
- **Steal verdict:** (a) workflows that arm themselves on connect — no setup screens;
  (b) the 08:00 single-briefing batching pattern is exactly JARVIS's morning digest
  done right; (c) "drafts never send" as an invariant for any proactive outbound action;
  (d) **[CODE] steal the deactivation-reason rule** — any v2 watcher that gets
  auto-paused (budget exhausted, errors) must record *why*, and auto-resume must never
  override a reason the user owns.

## 3. markfulton/ai-employees — 642★, JavaScript, MIT — routines-as-files, done seriously

- **What it is** [README/CODE]: 8 "AI Employees" (GTM Engineer, Chief of Staff, SEO,
  Social Media…), each a folder of **scheduled routines (60 total)** that run on the
  user's existing agent harness (Claude Code + 10 others) and "brief you every morning."
- **Trigger model** [CODE — `employees/*/SCHEDULE.md`]: the most disciplined scheduling
  design in this entire scan. **One SCHEDULE.md table is the only place cadences, fire
  times, windows, budgets, period keys and resource lanes live** — "a SKILL.md never
  carries a clock time." Every routine reads its own row as Step 0.1 of every run.
  Columns: `days`, `fire`, `window_start`, `window_end`, `key` (period-key format),
  `budget` (hard wall-clock minutes), `browser` (resource lane: never/light/read
  only/conditional/heavy).
- **Fire discipline** [CODE]:
  - **Fire time ≠ permission.** The OS/harness fire time is explicitly "not a
    guarantee"; the routine itself checks the window — outside it, it records
    `skipped-out-of-window` and exits. Scheduler drift, machine sleep and DST are all
    absorbed by the guard, plus a monthly drift check reconciles registered jobs
    against the table.
  - **Once-per-period idempotency:** the period key (`YYYY-MM-DD` / ISO `YYYY-Www` /
    `YYYY-MM`, computed from the **local** date, never UTC) gates re-runs — double
    fires are harmless.
  - **Fail-closed lookup:** missing/unparseable SCHEDULE.md row → record
    `status:"failed"` with a named blocker and exit. **It never guesses a window.**
  - **Hard budget:** at budget expiry the routine writes what it has and records
    `partial` — outcomes come from a closed status vocabulary.
  - **Resource mutex:** any routine needing the browser takes the browser mutex for
    its whole run; the lane column drives staggering so 8 routines don't fight.
  - Guardrails [CODE — `docs/GUARDRAILS.md`]: no account creation, no passwords, no
    CAPTCHAs, no credential files — the same hard rules JARVIS holds.
- **Feedback loop** [README]: runs record "verified deliverables separately from
  successful runs and business results"; interrupted work uses **atomic claims and the
  remaining scheduled budget** — a resumed routine picks up where the budget left off,
  not from zero.
- **License** [CODE]: **MIT** — code/patterns liftable with attribution.
- **Steal verdict:** **the routine guard itself** — a stdlib deterministic pre-flight
  for every v2 routine/reminder fire: (1) read row from one schedule table, (2) window
  check → skip-with-record, (3) period-key once-guard, (4) hard wall-clock budget →
  partial-with-record, (5) fail-closed on missing config. ~100 lines, zero LLM, and it
  makes v2's proactivity crash-, sleep- and double-fire-proof.

<!-- PARTS A/B/C + SYNTHESIS APPENDED BELOW -->

---

## Triage table — remaining candidates (search-metadata level, [SEARCH])

| Repo | ★ | Why it's here | Depth |
|---|---|---|---|
| markfulton/ai-employees | 642 | **"8 scheduled business roles, 60 routines"** on Claude Code + 10 harnesses — routines-as-files, the largest explicit routines library found in this scan | ⚠️ NOT deep-read (429) — **#1 follow-up** |
| digiteinfotech/kairon | 282 | "proactive digital assistants" platform (Rasa-era) | child C |
| coleam00/second-brain-starter | 820 | skill that generates a PRD for a "proactive, persistent AI assistant" | child C |
| titechprabhasolutions/Brahma-AI (+Lite) | 58/71 | Windows-first JARVIS-like: voice, routines, modular backend | triage only |
| superglue-ai/superglue | 1,427 | data-integration agent; routines angle is off-topic | rejected: not proactivity |
| sdi2200262/context-awareness-for-agents | 35 | context-window **threshold reminders** for coding agents — self-interruption policy: the agent reminds *itself* at usage thresholds | one-liner, §5 |
| NUDelta/MicroReminders | 1 | academic context-aware micro-reminding (habits) | child C |
| codeword/contexter | 0 | 2013 iPhone context-aware reminders — pre-LLM location triggers | historical |
| giri14v/Context-Vault | 0 | Chrome ext: context-aware bookmark reminders | triage only |
| digantDj/Smart-Shopper | 1 | 2016 location-based shopping reminders | historical |
| emineugurlu/reminder_app | 5 | weather-based outfit + health reminders (context-triggered) | triage only |
| viz-centric/flair-notifications | 17 | BI alerting — "notification intelligence" search was a dead end (BI/VirusTotal noise) | rejected |
| mvanhorn/paperclip-plugin-discord | 49 | Discord notification bridge for Paperclip agents | child B context |
| ambient-xyz/AmbientDesktop | 7 | local-first "durable, inspectable agentic work" desktop | triage only |
| Guesswhat-Studio/Linnet | 9 | personal morning briefing (arXiv/HN/GitHub trends) "curated overnight, waiting when you wake up" — scheduled via GitHub Actions | triage only |
| tballochi/daily-briefing | 8 | morning news briefing emailed daily; **runs entirely on GitHub Actions cron (Groq+Tavily), no server** | triage only |
| paulobarb/vaultmind | 13 | local (Ollama) Obsidian toolkit with morning briefings | triage only |
| dreamybecca-coder/invert-morning-brief | 9 | market briefing → Telegram + Obsidian | triage only |

---

## 4. Part reports (parallel children)

- **[team14-part-a-schedulers.md](team14-part-a-schedulers.md)** — 11 repos: skales [DOCS — source
  withdrawn, proprietary EULA], AgentCrew (no license → ideas only), forge (Apache-2.0), codexia
  (MIT) + 7 discovered: orbit-agents, fastclaw (GPL-3.0 → ideas only), murmur, herdr-automations,
  pi-schedule-prompt, moadim-daemon, coddy-agent (all MIT). Mechanisms: **transient-only retry
  with backoff + review gate** (orbit: 30/60/120 s on network errors only; `require_review`
  runs execute read-only into `pending_review`); **bounded catch-up** (herdr: missed runs fire
  on wake only inside per-task `catch_up_minutes`, default 120, else recorded `missed` +
  toasted; plus authoring-time overlap warnings); **typed schedule schema + conflict matrix**
  (AgentCrew: `at`/`every`/`cron` union, deterministic cron, per-schedule IANA tz, croniter
  validation, overlap → new slot `skipped` with reason, pre-authorized tool patterns per job).
- **[team14-part-b-ambient.md](team14-part-b-ambient.md)** — 6 repos: langchain-ai/ambient-agent-101
  (no license), hao-ai-lab/hawky (Apache-2.0), tomismeta/paperclip-aperture (MIT),
  aws-samples/sample-ambient-agent (MIT-0), NVIDIA ambient-healthcare-agents (Apache-2.0),
  777genius/agent-notifications (GPL-3.0 → ideas only). Mechanisms: **HITL allowlist** —
  only listed tools interrupt (langchain `interrupt()` into Agent Inbox), with per-interrupt
  verb matrices (ignore/respond/edit/accept); **per-tool outcome → targeted preference
  store** (langchain `update_memory()`: "NEVER overwrite the entire memory profile —
  ONLY make targeted additions"); **Intention surfacing** — weakest-link MIN aggregation,
  `SURFACE_THRESHOLD = 0.6`, latent heartbeat polls every 60 s (hawky); **single-`now`
  lane** (aperture: one ringing item, rest are `next`/staged or `ambient` HUD cards with
  5-min TTL, every item stamped `{owner, sourcePolicy, rationale[]}`); **atomic
  claim-or-park cooldown** (AWS: `lastAutoExecuteAt` set only if absent or ≤ now−60 s);
  **durable dismissal-suppression keys + satisfaction sweep** (hawky); delivery-time
  re-check of DND/focus (agent-notifications).
- **[team14-part-c-briefings.md](team14-part-c-briefings.md)** — 7 repos: sprytte/daily-briefing
  **[BLOCKED — 404, not verified]**, guilinhu/proactive_hearing_assistant (MIT),
  NUDelta/MicroReminders (no license → ideas only), coleam00/second-brain-starter (no
  license → ideas only), digiteinfotech/kairon (Apache-2.0 — but "proactive" is marketing,
  no mechanism in the OSS tree), anthropics/claude-quickstarts `managed-agents/daily-brief`
  (MIT), indfir/daily-news-bot (MIT). Mechanisms: **diff-before-you-speak** — Second
  Brain's `build_snapshot`/`diff_snapshot` over Gmail/Asana/Slack/Calendar persisted to
  `heartbeat-state.json`; heartbeat every 30 min in active hours, reflection 08:00 daily;
  3-bucket notify policy (notify now / batch / `HEARTBEAT_OK` silence); 4-level proactivity
  ladder (Observer/Advisor/Assistant/Partner); draft lifecycle with 24-h expiry; **fail-well
  run protocol** (Anthropic: read 10 min before bookmarks, verify every item live before
  posting, confirm post, then advance cursors; failed source = "unreadable, not empty";
  cron `32 7 * * 1-5`, 8-line cap, $5/run budget); **context-conjunction gating + debounce**
  (MicroReminders: fire only when iBeacon entry AND time window AND not-done AND away ≥20
  min; exactly one task per trigger; snooze re-enters the pool — no nag timers).

---

## 5. Top 5 mechanisms (cross-scan synthesis, code-evidenced)

1. **Diff-before-you-speak — the unanimous anti-fatigue law.** Second Brain (heartbeat
   `diff_snapshot`) and Anthropic Daily Brief (bookmarks + reported-items ledger) state
   it independently and in the same words: without a delta gate, a periodic loop re-rings
   the same items forever and becomes unusable. *Every proactivity system that survived
   contact with users grew one.*
2. **Fail-closed batched relevance gate with weakest-link math.** hawky's Intention:
   aggregate confidence = MIN(per-term contributions), surface ⇔ every term matched AND
   aggregate ≥ 0.6; one batched LLM relevance call judges ALL pending candidates per tick,
   and judge failure = silence, never fallback to dumber matching. The only quantified
   urgency gate found anywhere in this scan.
3. **Fire discipline: window guard + period-key idempotency + hard budget.**
   markfulton/ai-employees (MIT): fire time is only a hint — the routine itself checks its
   window (`skipped-out-of-window`), the period key (`YYYY-MM-DD`/`YYYY-Www`/`YYYY-MM`
   from local time) makes double-fires harmless, and a hard wall-clock budget records
   `partial` instead of running away. GAIA's atomic claim (SCHEDULED → EXECUTING with an
   occurrence stamp) + stale-exec reaper is the server-grade version of the same idea.
4. **Bounded catch-up + transient-only retry.** herdr-automations: occurrences computed
   from the wall clock, missed runs fire on wake only inside `catch_up_minutes` (default
   120), else recorded `missed` and surfaced once. orbit-agents: retry ONLY transient
   network errors (30/60/120 s backoff); logic errors never retry. Missed work is
   *recorded, never silently replayed.*
5. **Durable, targeted feedback — dismissal is forever.** hawky's suppression keys
   (durable across restarts, checked before any candidate is minted) + satisfaction sweep
   (items the user already handled retire themselves); langchain-101's correction →
   preference-store loop (targeted additions, never profile rewrites); GAIA's
   deactivation-reason ownership (auto-resume may only touch tasks carrying a reason the
   system itself set — the user's own off-switch is never silently overridden).

**Honest gap:** no repo implements JARVIS's exact combination (call-ringing + 5/day
learned budget). Most "proactive" products — Kairon, memUBot — delegate the ring/speak
decision to LLM judgment over memory; explicit interruption-policy engines are the
exception, not the norm.

## 6. Top 3 steals for JARVIS v2 (`proactivity.py`)

1. **Snapshot-diff + reported-items ledger for the watcher and morning routine.**
   A stdlib `briefing_state.json` holding per-source bookmarks/cursors + a reported-items
   ledger; each run = gather → **diff** → verify-live ("one stale 'still waiting' costs
   more trust than ten missing items"; failed source reported as "unreadable, not
   empty", never filled in) → compose under a line cap → ring/post → confirm delivery →
   advance cursors. Only deltas may ring. *(From: Anthropic Daily Brief + Second Brain,
   MIT/unlicensed-ideas.)*
2. **The deterministic routine guard** for every v2 scheduled fire (reminders, morning
   digest, watcher ticks): single schedule table (ai-employees' "a SKILL.md never carries
   a clock time") → per-run window check (`skipped-out-of-window` + record) → period-key
   once-guard → hard wall-clock budget (`partial` + record) → fail-closed on missing row
   → missed runs caught up only inside a bounded window (`catch_up_minutes`-style).
   ~100 lines, stdlib, zero LLM. *(From: ai-employees/MIT + herdr + GAIA-claim ideas.)*
3. **Gate + suppression layer on the call-ringing engine.** Before any ring: triage
   candidates (respond/notify/ignore), score multi-signal candidates with weakest-link
   MIN math and a fail-closed relevance gate, enforce the single-`now` lane (everything
   else waits as `next` or parks), write every pickup/dismiss/edit to a **durable
   suppression/preference store** (not an in-memory promise), and when the 5/day budget
   or a per-source cooldown is spent, **park the item for review instead of dropping it**
   (claim-or-park). New sources start review-first and earn ringing rights.
   *(From: hawky/Apache-2.0, langchain-101, aperture/MIT, AWS sample.)*

## 7. License summary (all repos, per repo-license-file reads)

| Repo | License | Reuse |
|---|---|---|
| markfulton/ai-employees | MIT | ✅ with attribution |
| NevaMind-AI/memUBot | **AGPL-3.0** | ⚠️ ideas only |
| theexperiencecompany/gaia | **PolyForm Noncommercial 1.0.0** | ⚠️ ideas only |
| milisp/codexia, orbit-agents, murmur, herdr-automations, pi-schedule-prompt, moadim-daemon, coddy-agent | MIT | ✅ with attribution |
| feicaiclub/forge, digiteinfotech/kairon, hao-ai-lab/hawky, NVIDIA ambient-healthcare-agents | Apache-2.0 | ✅ with attribution |
| aws-samples/sample-ambient-agent | MIT-0 | ✅ |
| anthropics/claude-quickstarts (daily-brief), indfir/daily-news-bot, guilinhu/proactive_hearing_assistant, tomismeta/paperclip-aperture | MIT | ✅ with attribution |
| fastclaw, 777genius/agent-notifications | GPL-3.0 | ⚠️ ideas only |
| YYHDBL/AgentCrew, langchain-ai/ambient-agent-101, NUDelta/MicroReminders, coleam00/second-brain-starter | none | ⚠️ ideas only |
| skalesapp/skales | proprietary EULA (source withdrawn) | ⚠️ ideas/[DOCS] only |
| sprytte/daily-briefing | **unverified — repo 404** | ⚠️ do not cite internals; follow-up |
