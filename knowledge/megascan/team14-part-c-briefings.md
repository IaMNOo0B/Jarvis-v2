# MEGA-SCAN Team 14 — Part C: Morning Briefings, Routines & Reminder Systems

Scope: trigger models (time / event / context), briefing composition, reminder timing policy, feedback loops, failure stories. Tags: **[CODE]** = read in source, **[README]** = repo README/docs, **[INFERENCE]** = analyst judgement, **[BLOCKED]** = could not verify.
Method note: GitHub MCP (`search_repositories`/`get_file_contents`) returned HTTP 429 on every attempt (initial + smaller retry after wait). All code below was read via raw GitHub file fetches / repo pages instead. Nothing is fabricated; gaps are marked.

Repos covered: **7** (4 of 5 named targets verified, 1 not found, + 2 code-substantive extras).

---

## 1. sprytte/daily-briefing — NOT FOUND [BLOCKED]

- Fetch of `github.com/sprytte/daily-briefing` returned **HTTP 404** [CODE — fetch result]. Web searches for `sprytte "daily-briefing"` and variants returned no matching repo (results were unrelated briefing articles/repos).
- **Honest verdict:** the repo as named does not resolve publicly as of 2026-10-20 — deleted, renamed, made private, or the owner/name in the task brief is slightly off. No schedule, sections, or delivery channel can be reported without fabricating.
- **Steal verdict:** N/A — use §6 (Anthropic Daily Brief) as the reference implementation for exactly this pattern (cron + LLM + calendar/Slack/GitHub → one short brief); it is strictly better documented than a 1★ repo would be.

---

## 2. guilinhu/proactive_hearing_assistant (48★, MIT) — "proactive" = no prompt needed, not notifications

Paper code: *Proactive Hearing Assistants that Isolate Egocentric Conversations*, EMNLP 2025 (Hu et al., UW) [README].

### Trigger / context model [CODE + paper abstract]
- **There is no schedule, reminder, or notification trigger at all.** "Proactive" here means the system acts **without an explicit user prompt**: it continuously processes egocentric **binaural audio** and automatically decides who the wearer's conversation partners are.
- **Anchor signal = the wearer's own speech.** The system "uses the wearer's self-speech as an anchor, leveraging turn-taking behavior and dialogue dynamics to infer conversational partners and suppress others" [paper abstract]. In training config this is literal: `"required_first_speaker_as_self_speech": true`, `"clean_embed": true`, `output_conversation: 1` in `config/model_config.json` [CODE].
- **Dual-rate architecture** [paper abstract + CODE]: a lightweight streaming model runs **every 12.5 ms** for low-latency partner extraction; a slower model runs less frequently for longer-range dialogue dynamics. Config mirrors this: `Net_Conversation` with `model1` (GridNetBlock, 6 layers, latent 32) + `model2` (GridNetBlock, 6 layers, `lstm_fold_chunk: 80`, STFT chunk 200 / pad 32), 16 kHz, SNRLP loss (`neg_weight: 100`) [CODE].
- Context is therefore **conversational, not calendrical**: partner vs. bystander is inferred from turn-taking, not from any user model, location, or time.

### Composition / timing / feedback
- Output is a separated audio stream, not a message — no briefing composition, no length control, no delivery channel.
- Feedback loop is offline only: training/eval on the synthetic LibriConversation dataset (HF `guilinhu/libri_conversation`), metrics SNRi / SI-SNRi / SI-SDRi [CODE — config + README]. No online user feedback (no accept/dismiss) exists in the repo.
- Failure story: none documented in repo; evaluation is on 2–3-speaker sets from 11 participants / 6.8 h real recordings [paper abstract] — generalisation beyond that is unproven [INFERENCE].

### License: **MIT** [README repo metadata + LICENSE file present].

### Steal verdict for JARVIS v2
The *pattern*, not the code: **self-speech as anchor + dual-rate processing** maps directly onto JARVIS's echo problem — a fast always-on gate (is this my own TTS / my user?) feeding a slow reasoner. The repo itself (PyTorch hearing model) is not importable into a stdlib Python assistant.

---

## 3. NUDelta/MicroReminders (1★, Swift, Northwestern Delta Lab, 2016) — context-aware micro-reminding

Academic habit-building app (Sasha Weiss, advisor Haoqi Zhang) [README]. The most complete *reminder timing policy* in this slice.

### Trigger model [CODE — `AppDelegate.swift`, `TaskNotificationManager.swift`, `Task.swift`]
A reminder fires only when **all three** gates pass — a conjunction, never time alone:

1. **Location (event):** Estimote iBeacon region entry. `CLBeaconRegion` (UUID `B9407F30-F5F8-466E-AFF9-25556B57FE6D`, major 5625, per-room minor → location name) `didEnterRegion` → `TaskNotificationSender().notify(location)` [CODE].
2. **Anti-flap debounce (timing):** entry only counts if the user was **outside the region ≥ 20 minutes**: `threshold: Double = 20 // Minimum number of minutes outside region before notification`, checked as `Date().timeIntervalSince(then) > 60.0*threshold` against `beaconExitTimes`. Exit times are guarded against buggy sequential enter/exit events (sentinel `Date(timeIntervalSinceNow: Int.max)`) — an explicit in-code comment admits "the beacons are buggy" [CODE].
3. **Time window + state (context):** `canNotifyForTask()` requires `completed == "false"` **and** location match (case-insensitive) **and** `afterTime < secondsIntoDay < beforeTime` — every task carries an explicit valid time window (seconds-into-day) plus a location [CODE].

Task model [CODE — `Task.swift`]: `name, category, subcategory, length` (default `"<1 min"` — tasks are deliberately *micro*, ~1 minute, sized to fit "dead space" in routines [README]), `location, afterTime, beforeTime, lastSnoozed, created, completed`.

### Reminder timing policy [CODE]
- **One notification per context entry, one task only.** `notify()` filters all tasks to candidates, then the scheduler picks **exactly one** — it never dumps the whole list at the user.
- Scheduler (`TaskScheduler`) has two policies: `pickRandom()` (**active**) and `pickLastSnoozed()` (FIFO by oldest `lastSnoozed` — present but commented out). Shipping choice was randomisation to avoid nagging the same stale task [CODE].
- Notification itself is immediate (`UNTimeIntervalNotificationTrigger(timeInterval: 0.1)`, title literally `"Reminder!"`, body = task name), category `respond_to_task` with two actions: **Done** / **Snooze**, plus custom dismiss [CODE].

### Feedback loop [CODE]
Every interaction is an event logged to Firebase under `Notifications/<deviceId>/<taskId>/<epoch>`: `notificationThrown | notificationSnoozed | notificationDone | notificationCleared | listDone`. Snooze and clear both just stamp `lastSnoozed = now` and push the task back — i.e. **snooze does not reschedule a timer; it re-enters the candidate pool for the *next* context entry**. `firebase_analysis.py` at repo root is the offline analysis of that event log [CODE — file listing]. This is a research instrument: the loop exists to *measure* which contexts/policies work, not to adapt online.

### Failure stories [CODE]
- Beacon unreliability is the dominant one, handled defensively in two places (double-enter guard, exit-time sentinel) rather than trusted.
- No retry/escalation if a task is snoozed forever — it can silently rot in the pool [INFERENCE from code: no age cap, no escalation path].

### License: **None** — no LICENSE file in the repo root [CODE — root listing]. Ideas only, no code reuse.

### Steal verdict for JARVIS v2
**Steal the conjunction + debounce:** `location/context match AND inside time window AND not done AND away ≥20 min` before ringing, and **one item per interruption**. That is a ready-made anti-nag gate for JARVIS's call-ringing: ring for at most one reminder per context change, and snooze = "re-offer at next context", not "+10 minutes".

---

## 4. coleam00/second-brain-starter (820★) — a SKILL that prescribes a proactive assistant

Not an implementation: a Claude Code skill (`create-second-brain-prd`) that interviews the user (8-section requirements template) and generates a 9-phase PRD. Its value is the **proactivity spec it prescribes**, which is unusually concrete. Sources: `SKILL.md`, `references/architecture-reference.md`, `templates/memory/HEARTBEAT.md`, `templates/memory/HABITS.md` [CODE — all read in full].

### The prescribed heartbeat [CODE]
- **Schedule:** `heartbeat.py` runs **every 30 minutes during active hours**; daily reflection (`memory_reflect.py`) runs **daily at 08:00**.
- **Pipeline (deterministic-first):** (1) **Python pre-fetches** all integration data *before* invoking the LLM → (2) **state diffing** → (3) **pre-flight guardrail agent** → (4) main reasoning call → (5) notify. Quoted cost: **~$0.05/run pre-fetched vs $0.38/run with MCP tool calls**.
- **State diffing is named as THE anti-fatigue mechanism:** `build_snapshot(...)` / `diff_snapshot(current, previous)` over Gmail/Asana/Slack/Calendar, persisted atomically to `.claude/data/state/heartbeat-state.json`; **only the delta** reaches the LLM. SKILL.md, verbatim intent: "without state diffing, every 30-minute run re-surfaces the same unread emails and the user gets paged endlessly. Without this mechanism the heartbeat is unusable in production." [CODE]
- **Check cadence inside HEARTBEAT.md:** quick checks every run (urgent email <2 h, calendar <4 h ahead, overdue tasks, monitored Slack); periodic checks rotate (project status 1–2×/day, team coordination 1×/day weekday mornings, memory maintenance daily); "Don't repeat a check if it was done < 30 minutes ago" tracked in `heartbeat-state.json` [CODE].
- **Notify policy — three buckets** [CODE — HEARTBEAT.md]: *Notify immediately* (urgent email from important contact; event in <2 h with no prep; overdue tasks) · *Batch for next interaction* (non-urgent email; tasks due >48 h; interesting-not-urgent) · *Stay silent (`HEARTBEAT_OK`)* (nothing new; outside active hours unless truly urgent; everything on track).
- **Anomaly detection:** spike in unread count vs baseline, unexpectedly cancelled/moved meetings, tasks overdue >1 week (suggest cleanup), silence in usually-active channels [CODE].

### Proactivity levels (the spec's escalation ladder) [CODE — README + SKILL.md mapping]
| Level | Behaviour |
|---|---|
| **Observer** | Heartbeat notifications only; no drafting, no habit tracking |
| **Advisor** | + drafts emails/messages for review; habit suggestions, no auto-check |
| **Assistant** | + auto-organises files, auto-logs decisions; asks for anything external; habit auto-detection for objective pillars |
| **Partner** | + sends low-risk messages, completes routine tasks; asks only for irreversible actions; full habit auto-detection |

### Routines prescribed around the heartbeat [CODE]
- **Draft lifecycle:** heartbeat scans for unreplied mail/DMs/posts → writes drafts to `drafts/active/` (YAML frontmatter: type, source_id, recipient, subject, context, created, status) in the user's voice via RAG over `drafts/sent/` → drafts **expire after 24 h** to `drafts/expired/` → if the user replied themselves, the file moves to `drafts/sent/` capturing their **actual** reply (voice corpus grows from real behaviour).
- **Habits:** 3–5 "pillars" (Atomic Habits framing) in `HABITS.md`, each with explicit auto-detection rules ("routine maintenance does NOT count"); heartbeat archives yesterday, resets today, suggests actions for unchecked pillars from calendar/task context, and **nudges after 18:00** if pillars are still unchecked. Personal/relational pillars are **NEVER auto-check** — self-report only.
- **Daily reflection:** promotes daily-log items to `MEMORY.md`; a PreToolUse hook **blocks the reflection agent from editing SOUL.md** ("soul drift" prevention) — identity-change suggestions go to the daily log for user approval instead.
- **Failure-hardening baked into the spec:** hook-recursion prevention via `CLAUDE_INVOKED_BY` env var (every Agent-SDK session sets it; SessionEnd/PreCompact hooks skip if set — otherwise infinite flush loops); cross-platform file locking + atomic state writes because heartbeat/reflection/chat/flush write concurrently; `with_retry()` exponential backoff on 429/5xx so "a single rate-limited API call" can't crash a run; a **no-tools pre-flight guardrail agent** returns `{pass|fail|suspicious}` on sanitised external data before the main agent sees it (fail = abort run) [CODE].

### License: **None** — no LICENSE file in the repo root [CODE — root listing]. Ideas only.

### Steal verdict for JARVIS v2
**The single best proactivity spec in this slice.** Steal three things verbatim as design: (1) snapshot/diff so JARVIS never re-rings the same item, (2) the 3-bucket notify policy (ring now / batch / HEARTBEAT_OK silence), (3) the 4-level proactivity ladder as the user-facing setting. All are pure-Python-stdlib implementable (JSON state file + hashes).

---

## 5. digiteinfotech/kairon (282★, Apache-2.0) — "proactive digital assistants"

**Honest one-liner: in the open-source repo, "proactive" is marketing, not a mechanism — no proactive-messaging/trigger implementation was found.**

Evidence: README claims "Kairon Telemetry… monitors how users are interacting with the website/product where Kairon was injected and **proactively intervenes** if they are facing problems" and "**Realtime struggle analytics**… to proactively intervene when users are facing friction" [README]. The repo itself is a Rasa-based no-code chatbot trainer/lifecycle platform (FastAPI + MongoDB, 2,572 commits) [README repo metadata]; its root tree, docs outline, and feature list contain training, augmentation, analytics, chat-client design and deployment — **no telemetry/struggle-detection module, no trigger engine, no proactive-message scheduler** is exposed in the OSS tree [CODE — root listing + README]. The telemetry product appears to be the hosted/commercial side (nimblework.com), not this code.
What *does* exist that is proactive-adjacent: "post-processing and maintenance of bots such as metrics / **follow-up messages**" [README] — i.e. follow-ups are a platform concern, with no timing policy published.
- Trigger model / timing policy / feedback loop: **none extractable** [CODE — absence in tree/docs].
- License: **Apache-2.0** [README repo metadata, `LICENSE.txt` present] — irrelevant here, since there's nothing proactive to reuse.
- **Steal verdict:** steal nothing; cite as the cautionary example — a "proactive" label with no trigger model, no fatigue policy, and no code is exactly what JARVIS v2 must not ship.

---

## 6. EXTRA — anthropics/claude-quickstarts · `managed-agents/daily-brief` (repo 18,875★, MIT)

The most code-substantive morning-briefing implementation found in this scan. A scheduled agent (Claude Managed Agents, deployment defined as files via `ant apply`) that reads Slack channels + GitHub PRs and posts **one short brief** to Slack [CODE — subdir README, `agent.md`, `deployment.md`, `preferences.example.md`, all read in full].

### Trigger model [CODE]
- Cron deployment: **`32 7 * * 1-5`** — weekdays 07:32, `timezone: America/New_York` in `deployment.md` (the odd :32 avoids the on-the-hour thundering herd [INFERENCE]). Schedule starts **paused** after setup; a human unpauses it after a supervised trial run.
- Per-run budget cap: **$5.00/run** (`amount: "500"` cents). A run that hits the cap *pauses rather than fails* — which "from the channel looks like silence", so a missing brief must be diagnosed in the Console, not assumed fine [CODE].

### Briefing composition [CODE — `agent.md` 8 run steps]
1. **Preferences first, fresh, every run** — read-only store the agent *cannot edit*: sources, destination, **length cap**, mentions policy, retired topics, exclusions, temporary rules with end dates (`until 2026-10-01: <rule>`), and a STOP condition. If preferences are unreadable → post nothing, change nothing.
2. **State:** `bookmarks.json` (per-source/per-channel read cursor), `ledger.md` (items already reported, one line each: date, source, item id, state), `notes.md` (how each source *behaves* — quirks/limits only; failures are never notes, "because it will be fixed and the note would outlive the fix"), last run record.
3. **Read from 10 minutes *before* each bookmark** (overlap window so a late/skipped run loses nothing), skipping anything already in the ledger with unchanged state.
4. **Decide:** "An item earns a line only if you would act on it today… When unsure, leave it out." A count ("12 open reviews") is **not** an item. A still-open ledger item is carried as one marked line — **"still waiting, day 3"** — not re-reported; a closed item is dropped silently; retired topics never return.
5. **Verify live just before posting:** re-check every item against its source; resolved → drop, changed → fix, unconfirmable → drop and log in the run record's cuts. "One stale 'still waiting on you' costs more trust than ten missing items… assert it or drop it." Links are copied from the source's own link field, never assembled.
6. **Write inside the cap** — example preferences set **at most 8 lines** [CODE — `preferences.example.md`]. Gaps get **one line at the end**: a source that couldn't be read is **"unreadable, not empty"**; a missing number is stated as missing, never filled in. If nothing to report and all sources read: one line saying so — or, if preferences allow silence, post nothing as a *deliberate quiet day*.
7. **Post exactly once:** search destination history for today's title first (dedupe); write run record with `status: posting` *before* posting; Slack counts as posted only if the response body says `"ok": true` with a `ts` (Slack returns HTTP 200 on failure); unclear result → `status: maybe posted`, change nothing else; unreachable destination → `status: held`, brief text kept in the run record.
8. **Bookkeeping only after confirmed post:** only then advance bookmarks, append ledger lines, finalise `runs/<date>.md` (written every run, even silent ones: what was read, what failed, what was posted, what was cut with a one-word reason each). **A bookmark never moves for a failed source, and never if the post failed.** Dry-run mode = make the state store read-only → agent prints the brief and can move nothing.
- **Delivery:** single Slack post to one destination channel; the bot must be a member of source channels (membership *is* the access control).
- **Measured cost** [CODE — subdir README]: busy day (~140 messages + 25 PRs across 2 channels/2 repos) ≈ $1.50 (Opus) / $1.00 (Sonnet); all-sources-unreadable run $0.15–0.30.
- **Security as composition rule:** everything read is data, never instructions; web_search/web_fetch disabled so injected text has no exfil route; GitHub token read-only; preferences mounted read-only at filesystem level; reader feedback in the channel goes to `proposals.md` for the human to accept — the agent never edits its own rules.

### Feedback loop / failure stories [CODE]
The whole design is a catalogue of unattended-run failure modes, each with a named countermeasure: skipped run → bookmarks + 10-min overlap; repeats → ledger; source outage misread as a quiet day → explicit "unreadable" line + bookmark frozen; double-post → title search + post-confirmation before state moves; stale item → live re-verification; runaway cost → per-run cap; prompt injection from read content → read-only token + read-only preferences + disabled web tools.

### License: **MIT** (repo) [README repo metadata].

### Steal verdict for JARVIS v2
**This is the briefing engine to copy.** Bookmarks + ledger + "confirm post before advancing state" + "unreadable ≠ empty" + 8-line cap are ~150 lines of stdlib Python (JSON + a markdown ledger) and slot straight into JARVIS's existing routines/cron + Telegram/call-ring delivery.

---

## 7. EXTRA — indfir/daily-news-bot (0★, MIT, PowerShell) — RSS daily brief with 30-day dedup

Found via search "daily briefing / daily digest agent". Small but complete and *running in production* (318 commits, GitHub Actions) [README repo metadata].

### Trigger & composition [README — detailed, incl. workflow file refs]
- **Trigger:** GitHub Actions cron `0 23 * * *` UTC = **06:00 WIB** delivery, plus `workflow_dispatch` for manual/test/recovery runs. (README's own architecture diagram says 20:00 UTC / 03:00 WIB for the fetch stage — an internal inconsistency worth noting; the workflow cron documented by DeepWiki is `0 23 * * *`.) Known platform failure mode, documented: GitHub Actions may delay scheduled runs 10–15 min under load, and a missed run is **never** retroactively executed [DeepWiki of the workflow].
- **Sources & length control:** hundreds of RSS feeds across **8 topics** (Economy, Trading/Crypto, Science, Technology, Astronomy, Movies, Data/AI, General); per run it **randomises and selects ≤5 feeds per topic and shows ≤5 items per topic** — randomisation is the variety mechanism, the caps are the length control.
- **Filtering pipeline:** domain blocklist (paywalls/podcasts) → content blocklist ("Podcast", "Webinar", "Conference"…) → per-topic keyword relevance (title must contain ≥1 topic keyword) → **deduplication against a 30-day history** → title translation (Google Translate → Indonesian) → image extraction (`og:image`/`twitter:image` → Wikipedia fallback) [README].
- **Delivery & state:** Telegram (HTML formatting, link previews disabled for a clean layout), to one chat (+ optional second bot/chat). State lives **in the repo itself**: `news.json` (output) and `sent_links_history.json` (`{CanonicalKey, SentDate}`, entries auto-expire after 30 days) committed back by the workflow — which is why the workflow needs `contents: write`, and why dedup breaks without it [DeepWiki + README].
- **Feedback loop:** none from the reader — no reactions, no clicks tracked. The only loop is dedup history. Troubleshooting section is the failure record: workflow not running, bot silent (token/chat-id, esp. `-100…` group IDs), empty topics (dead feeds or over-strict keyword filter), dedup reset = delete the history file [README].

### License: **MIT** [README + LICENSE].

### Steal verdict for JARVIS v2
Steal the **canonical-key + TTL dedup file** (`{key, sentDate}`, 30-day expiry, state committed/next to the routine) and the **per-section item cap + feed randomisation** for any news section of the morning brief. Skip the rest — PowerShell/RSS plumbing doesn't transfer, and repo-as-database is a GitHub-Actions workaround JARVIS doesn't need.

---

## Cross-cutting synthesis

### Top 3 mechanisms (ranked by value to JARVIS v2)
1. **Diff-before-you-speak** (Second Brain + Anthropic, independently): snapshot/bookmark + ledger of already-reported items; only the *delta* may interrupt. Both projects state the same law in almost the same words — without it a periodic proactivity loop is "unusable in production" / repeats yesterday's items. This is the #1 missing piece in most reminder systems.
2. **Fail-well run protocol** (Anthropic Daily Brief): read with an overlap window → verify items live → post → *confirm* the post → only then advance state; a failed source is reported as "unreadable" in one gap line and its bookmark stays frozen. Converts every silent failure (missed run, dead API, duplicate post, stale item) into either recovery or an honest one-liner.
3. **Context-conjunction gating with debounce** (MicroReminders): fire only when context matches AND time-window matches AND item is undone AND the user has been away from that context ≥20 min; deliver **one** item per trigger; snooze re-enters the pool for the next context instead of starting a nag timer. The reminder-domain twin of mechanism 1.

### Supporting patterns worth one line each
- **Length is a config value, not a hope:** 8-line cap (Anthropic), ≤5 items × 8 topics (indfir), 30-min check spacing + "HEARTBEAT_OK" silence token (Second Brain).
- **Escalation is a level, not a mood:** Observer → Advisor → Assistant → Partner ladder, with habit nudges time-boxed (after 18:00) and drafts auto-expiring at 24 h (Second Brain).
- **Dual-rate sensing** (Hearing Assistant): 12.5 ms fast gate + slow dynamics model — the architectural shape for JARVIS's wake/echo gate vs. brain.
- **Anti-pattern logged:** Kairon — "proactive" with no trigger model in code. If JARVIS can't name its trigger, gate, cap, and state file, it isn't proactive, it's marketing.

### ⭐ Top steal (single recommendation)
**Port Anthropic Daily Brief's run protocol into JARVIS v2's morning routine, fused with Second Brain's snapshot-diff:** a stdlib `briefing_state.json` holding per-source bookmarks + a reported-items ledger; each run = gather → diff → verify-live → compose ≤8 lines (one gap line for unreadable sources) → ring/post → confirm → advance state. It directly upgrades JARVIS's existing reminders/routines skill and call-ringing model (ring = the "post", pickup/dismiss = the confirmation that lets state advance), and every component is Python-stdlib only.

### Coverage / honesty notes
- Researched & code-validated: MicroReminders, Second Brain (skill + references + templates), Hearing Assistant (README + config + paper abstract), Anthropic Daily Brief (subdir README + agent.md + deployment.md + preferences), Kairon (README + tree — proactive feature absent in OSS).
- README-level only: indfir/daily-news-bot (PowerShell source not line-read; workflow details cross-checked via DeepWiki).
- Blocked / not found: sprytte/daily-briefing (404; GitHub MCP rate-limited at HTTP 429 throughout, so an API-side existence check could not be completed — a re-check via the GitHub connector when quota resets is the one open follow-up).
