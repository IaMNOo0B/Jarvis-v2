# MEGA-SCAN TEAM 30 — PERSONAL ANALYTICS & DASHBOARDS

**Mission:** quantified-self dashboards, personal metrics pipelines, life-logging analytics,
habit/screen-time trackers with real insight generation. Question for JARVIS v2: how does a
system come to *know* the owner's patterns instead of only reacting?

**Method:** `git clone --depth 1` into `.work30/`, read locally. 41 repos attempted.
**Environment warning (honest):** this VM's network/filesystem was actively flaky during the
scan — several clones timed out repeatedly, and a few "successful" checkouts later vanished or
were empty (uhabits, kado, perkeep). Every repo below carries an evidence tag:
`[CODE]` = source read locally · `[DOCS]` = official docs/site only · `[TRIAGE]` = README/config level.
Claims never exceed their tag.

**Headline finding:** In the entire open-source QS field, "insight generation" is almost never
machine learning. It is four deterministic moves, repeated everywhere credible:
(1) **canonicalize** raw logs into clean interval events, (2) **roll up** (totals, top-N, streaks),
(3) **compare** (this period vs last period), (4) **narrate** — and only here does an LLM appear,
in the newest tools, speaking over numbers it did not invent. JARVIS v2's digest/anticipation
work is already on this exact track; what's missing is the canonicalization layer (steal #1).

---

## TOP 5

### 1. ActivityWatch (`ActivityWatch/activitywatch` + `aw-webui`, `aw-watcher-web`) — MPL-2.0 `[CODE]`
The reference architecture for screen-time analytics, and the deepest code read in this scan.
- **Data model:** everything is an *Event* `(timestamp, duration, data: dict)` stored in a
  named **bucket** per watcher (window, AFK, browser…). Watchers are dumb producers;
  all intelligence is downstream. (`aw-core/aw_datastore`, verified locally.)
- **Metric derivation = a pure transform pipeline** (`aw-core/aw_transform/`, verified):
  - `flood(events, pulsetime=5s)` — fills gaps ≤5s between events; equal-data neighbours merge
    across the gap; differing data split the uncertain interval at the **midpoint**; on overlap,
    the later event wins so time is never double-counted. This one function is the difference
    between raw watcher noise and honest "you coded 3h12m".
  - `merge_events_by_keys`, `chunk_events_by_key`, `filter_period_intersect`,
    `union_no_overlap`, `split_url_events` (URL → domain/app), `heartbeats` (pulse events →
    intervals).
  - `classify.py` — user rules (regex over title/URL, with category priorities) compile once
    and tag events with `$category`; the *owner* defines what "Work" vs "Distraction" means.
  - `aw_query/query2.py` — a small query DSL composes transforms server-side, so every view
    is the same pipeline with different parameters (no per-screen bespoke math).
- **Visualization vocabulary** (`aw-webui/src/visualizations/`, verified): `SunburstClock`
  (the day as a radial clock), `SunburstCategories`, `Timespiral`, `PeriodUsage` (period-over-
  period bars — the comparison move), `TimelineBarChart`, `Summary`, even a `Score.vue`.
- **Insight logic:** none statistical — deliberately. Totals + comparisons + a good default
  view. AFK watcher separates active from idle so totals aren't inflated.
- **Steal verdict:** the single most valuable design in this report for v2 (see Steal 1).
  MPL-2.0 is file-level copyleft — reimplement the *algorithms* in v2's stdlib style, don't
  copy files.

### 2. HPI — Human Programming Interface (`karlicoss/HPI` + `seanbreckenridge/HPI`) — MIT `[CODE]`
The reference architecture for *personal data unification* — the pipeline half of this mission.
- **Federation pattern:** ~50 source modules under `src/my/` (browser, calendar, github,
  goodreads, jawbone, emfit, endomondo, arbtt, coding, location…) each exposing plain
  iterators of typed records over the owner's local exports. No central database; modules
  read files where they lie.
- **Errors-as-values (the core trick, verified in `src/my/core/error.py`):**
  `type Res[T] = T | Exception` — a broken/missing source yields exception objects *inline*
  in the stream instead of crashing the pipeline; consumers decide to skip, log, or surface.
  One corrupt export degrades one metric, never the whole briefing.
- **Per-source `stats()`** (`core/stats.py`): every module reports counts/freshness — a built-in
  "what data do I even have, and how stale is it" feed.
- Supporting machinery: `cachew` (transparent function-result caching to disk), `core/query.py`
  (select/where composition across modules), `core/sqlite.py` + `dataset` (query any source
  as SQL), strict aware/naive datetime discipline (`core/datetime.py`).
- **The overlay pattern** (`seanbreckenridge/HPI`, verified): a second, personal repo layers
  *his own* modules on the shared core (`my/activitywatch/active_window.py` etc.). Each module
  declares `REQUIRES = [...]`, takes a typed `user_config` dataclass, and sets an
  `error_policy` (`"drop"`). Framework and personal config are separate repos — exactly the
  split v2 has between `jarvis/` and `data/`.
- **Steal verdict:** MIT — the errors-as-values + stats() contract is directly portable to
  v2's digest/anticipation inputs (Steal 2).

### 3. Wakapi (`muety/wakapi`) — MIT `[CODE]`
Self-hosted WakaTime: turns editor *heartbeats* into coding analytics. The cleanest example of
**metric derivation from point samples** in the scan.
- **Derivation chain** (verified in `models/` + `services/`): `Heartbeat` (timestamp, project,
  language, editor, branch) → `services/duration.go` builds `Duration`s — a heartbeat implies
  activity until the next heartbeat, **capped by a timeout**, so a forgotten editor doesn't
  claim 9 hours → `services/aggregation.go` rolls durations into `Summary` (per day × project ×
  language × editor), with `language_mapping.go` / `canonical_names.go` aliasing raw names to
  canonical ones before aggregation.
- **Insights:** summaries, leaderboards, project stats, badges, "coding activity" reports —
  all deterministic rollups + period comparisons. Plus a `diagnostics.go`/housekeeping that
  prunes and self-reports data health.
- **Steal verdict:** MIT. The heartbeat→duration timeout rule is the honest way to convert
  v2 watcher samples into focus-time (Steal 3).

### 4. Dawarich (`dawarich-app/dawarich`) — self-hosted Google Timeline `[DOCS]`
(Clone failed 3× on this VM — network; assessed from official docs + project site only.)
- **Insight mechanism — visit detection as a nightly deterministic job:** a background job
  scans the previous day's location points, clusters dwell into **Suggested Visits**, and
  presents them for review. Documentation (dawarich.app, fetched this scan) specifies the
  lifecycle: `Suggested → Confirmed / Declined`; confirming a visit saves its location as a
  **Place**; *declined suggestions never reappear*.
- **Analytics:** trips, distance, time-per-place, heatmaps, per-period stats — rollups over
  the confirmed model, not the raw points. Reverse geocoding is off by default (privacy-first).
- **Steal verdict:** the *lifecycle* is the steal, not the geo math: machine proposes patterns,
  owner confirms once, system remembers forever, rejections are durable (Steal 4). This is the
  missing trust layer for v2's `anticipations()` — today it emits raw frequencies with no
  confirm/decline memory.

### 5. Screenpipe (`mediar-ai/screenpipe`) — source-available (NOT OSI) `[CODE-root]`
24/7 screen + audio capture → local SQLite with full-text search → "pipes" (scheduled
processors) → LLM chat/search over your own history.
- **Pipeline:** continuous capture is stored raw first (frames OCR'd, audio transcribed),
  indexed, and only then queried — capture and analysis fully decoupled, so a smarter
  processor tomorrow can re-mine yesterday's raw log.
- **Insight logic:** retrieval + LLM narration over FTS results — the modern end of the field,
  and the clearest proof of the headline: the LLM *narrates and searches*; the numbers come
  from the index.
- **Steal verdict:** ideas only (source-available license — no code). The stealable idea is
  *raw-first storage with re-minable history* — v2's session store already keeps raw events;
  screenpipe validates never throwing the raw layer away when adding rollups.

---

## THE REST OF THE FIELD (evidence-tagged)

**Time trackers (interval-native):**
- `almarklein/timetagger` — GPL-3.0 `[CODE]`. One record type rules everything:
  `RECORD_SPEC = {key, mt, t1, t2, ds}` (verified in `server/_apiserver.py`) — a tag string,
  a modified-time for last-write-wins sync, start/end, description. Stats are computed
  client-side from the same records; "hidden" records (breaks) are just records with a
  reserved tag. Lesson: a 5-field record can carry a whole product.
- `TailorDev/Watson` — MIT `[CODE-root]`. CLI frames `(start, stop, project, tags)` in JSON;
  `report`/`log`/`aggregate` are pure rollups over frames. The frame is the same interval
  atom as AW's event, hand-made.
- `kimai/kimai` — AGPL-3.0 `[TRIAGE]`, `solidtime-io/solidtime` `[TRIAGE]`,
  `traggo/server` — GPL-3.0 `[TRIAGE]`, `projecthamster/hamster` `[TRIAGE]`:
  timesheet-class systems; their "analytics" = filtered sums + export. Confirms the field's
  ceiling: nobody in timesheets does anomaly detection.
- `GothenburgBitFactory/timewarrior` — MIT `[TRIAGE]`; `taskwarrior` — MIT `[TRIAGE]`
  adds one genuinely different idea: **urgency coefficients** — a weighted, user-tunable
  formula turns task fields (due date, priority, age) into one comparable number. A rare
  example of a *transparent scoring formula* as the whole "intelligence".

**Rule-based categorization (the pre-AW generation):**
- `nomeata/arbtt` — GPL `[CODE-root]`. A daemon samples the active window every minute;
  a user-written rule file (`categorize $current.title =~ /…/ as Work/Code`) assigns tags;
  `arbtt-stats` rolls up. AW's classify.py is this idea, productized. For v2 the *form*
  matters: categorization rules as a plain-text file the owner can read and edit.

**Habit trackers:**
- `iSoron/uhabits` (Loop Habit Tracker) `[TRIAGE — checkout lost to FS bug twice]`.
  Known for replacing fragile streaks with a **habit strength score**: an exponential-decay
  style score that drops on missed days but doesn't zero out, and recovers as you resume —
  a metric designed to describe behaviour, not to punish. `[MC — algorithm from project docs,
  code not verified this pass]`
- `scastiel/kado` `[TRIAGE — clone unreliable]`: privacy-first iOS habit tracker, JSON/CSV
  round-trip import/export as a stated design value; author site claims MIT (no LICENSE
  verified in-repo this pass).
- `blinry/habitctl` `[CODE-root]`: terminal habit tracker over a plain-text log — proof the
  habit atom is just `(date, habit, done)` and everything else is derivation.

**Personal-data aggregators & journals:**
- `markwk/qs_ledger` — MIT `[CODE]`. Per-service downloader folders (apple_health, fitbit,
  oura, rescuetime, strava, last_fm, goodreads, toggl, todoist, google_calendar…) → local
  files → pandas notebooks, incl. a **correlation explorer** (pick two series, see the
  scatter/correlation). The correlation explorer is the field's one real "insight" UI — and
  it's manual: the human asks, the tool computes. Nobody auto-discovers correlations.
- `karlicoss/promnesia` — MIT `[CODE]`. Browser-history life-logging: every visited page
  becomes a `Visit` (verified NamedTuple in `common.py`) indexed for "have I seen this,
  when, in what context" — memory augmentation as analytics over one event type.
- `WorldBrain/Memex` `[CODE-root]`: same thesis as a browser extension (full-text search +
  annotation of everything you read).
- `jrnl-org/jrnl` — GPL `[TRIAGE]`: timestamped text journal; "analytics" = tag counts and
  date-range exports. Even journaling tools stop at rollups.

**Location ingestion (feeds, not analytics):**
- `traccar/traccar` — Apache-2.0 `[TRIAGE]`; `owntracks/recorder` — MIT `[TRIAGE]`:
  GPS point ingestion/storage. Dawarich is what happens when you add derivation on top.

**Dashboards (presentation layer):**
- `gethomepage/homepage` — GPL-3.0 `[CODE-root]`; `bastienwirtz/homer` — Apache-2.0
  `[TRIAGE]`; `TwiN/gatus` — Apache-2.0 `[TRIAGE]` (status/health checks with alerting —
  the only dashboard here that *pushes* signal instead of waiting to be looked at).
  Common pattern: **config-declared widgets over small JSON APIs**; zero derivation in the
  dashboard itself. `lissy93/dashy`, `glanceapp/glance`, `mholt/timelinize`,
  `open-nomie/nomie`, `khoj-ai/khoj`, `laurent22/joplin`, `habitrpg/habitica`,
  `codeclimbersio/codeclimbers`, `perkeep/perkeep`, `wger-project/wger` — clones failed
  repeatedly on this VM (network stalls / vanished checkouts); **not assessed** rather
  than assessed from memory. Nomie and Timelinize are the two worth a retry on a healthy
  network — Nomie for its flexible "track anything" event model, Timelinize for its
  cross-source timeline unification.

**Catalogue:** `woop/awesome-quantified-self` `[CODE]` — the field's map; useful as a
checklist of data sources (it is how several candidates above were confirmed).

---

## INSIGHT / ANOMALY DETECTION — THE HONEST VERDICT

- **True anomaly detection: essentially absent.** No repo in 41 attempts ships statistical
  anomaly detection over personal metrics. The closest things are (a) Gatus-style threshold
  alerts on service health, (b) taskwarrior's urgency formula, (c) uhabits' strength decay.
- **What passes for insight:** rollups, top-N, streaks/strength, period-over-period deltas
  (AW `PeriodUsage`, Wakapi summaries), and one manual correlation explorer (qs_ledger).
- **Deterministic vs LLM split:** derivation is 100% deterministic in every credible repo.
  LLMs appear only at the narration/search edge (screenpipe; khoj-class tools). This matches
  v2's existing law — brain narrates, code computes — and validates it against the whole field.
- **The gap nobody fills (JARVIS's opening):** nobody closes the loop
  *derive → propose pattern → owner confirms → remember forever*. Dawarich does it for places
  only; anticipation engines (incl. v2's current `anticipations()`) emit unconfirmed guesses
  forever. First system to make confirmed-pattern memory general wins this category.

## VISUALIZATION VERDICT (for a voice-first JARVIS)

The digest *is* the dashboard; visuals are for the HUD only. If/when the HUD shows patterns,
steal AW-webui's vocabulary, not the config-grid dashboards: **sunburst clock** (day at a
glance), **period-usage bars** (this week vs last — the comparison move, glanceable),
**category sunburst** (where time went). Homepage/Homer-class widget grids are the right
*implementation form* (small JSON metrics API + declared widgets) but carry no ideas about
which metrics matter.

---

## TOP 3 STEALS FOR JARVIS v2

### Steal 1 — The canonical event-transform layer (ActivityWatch `aw_transform`, MPL-2.0 → reimplement)
v2 today stores point events (session store) and point samples (watcher). Add a stdlib
`jarvis/analytics.py`: events gain `(timestamp, duration, data)` form, and a small pipeline of
pure transforms — `flood` (gap-fill ≤5s, midpoint split, later-wins), `merge_by_keys`,
`classify` (owner-editable regex rules → categories, JARVIS-RULES-style text file),
`period_intersect`, `union_no_overlap`. Every downstream consumer (morning digest, anticipation,
self-review) reads canonical intervals, never raw logs. This is the metric-derivation layer the
whole field converges on and v2 lacks. ~200 lines, fully deterministic, testable with canned
event streams.

### Steal 2 — Errors-as-values pattern sources + per-source stats (HPI, MIT)
Define the contract every digest/anticipation input already half-follows: a source yields
items *or* an exception object, plus `stats() -> {count, newest, ok}`. `morning_digest` then
degrades per-section by construction (it already skips bad sections ad hoc — this makes it a
law, not luck), and `stats()` feeds the DCL "what do I know about you / how fresh is it" view
for free. Directly hardens Builder E's digest and gives proactivity a data-health signal:
JARVIS can say "I haven't seen screen data in 3 days" instead of silently knowing less.

### Steal 3 — Confirmed-pattern memory: Dawarich's lifecycle on top of Wakapi's derivation
Two-part steal. (a) **Derivation** (Wakapi, MIT): watcher heartbeats → durations with a timeout
cap → daily rollups; plus canonical-name aliasing so "Code.exe", "VS Code" and "code" are one
app in the stats. (b) **Lifecycle** (Dawarich, docs): the nightly consolidation (v2's
`memory.consolidate()` already runs the right shape of job) clusters yesterday's rollups into
*suggested patterns* — "deep work usually starts ~22:00", "Wednesdays are meeting-heavy" —
stored as candidate facts; JARVIS surfaces each **once**; owner confirm → semantic fact with
provenance; decline → durable suppression key, never re-suggested (rhymes with Team 14's
dismissal-is-forever law). This converts `skill_foundry.anticipations()` from a frequency
dump into the field's missing piece: an anticipation engine the owner has *trained by
confirmation*, feeding the morning digest and the recall gate.

**Runner-up (cheap, do it with Steal 1):** uhabits-style **strength-over-streaks** scoring for
any habit/routine v2 tracks — exponential-decay score (misses hurt, never zero out) —
plus arbtt/AW-style owner-editable categorization rules as a plain text file.

---

## LICENSE LEDGER (verified from cloned trees unless noted)

MIT: HPI (both), Wakapi, Watson, qs_ledger, promnesia, taskwarrior, timewarrior, owntracks/recorder.
MPL-2.0: ActivityWatch (reimplement algorithms; don't copy files).
Apache-2.0: Homer, Gatus, Traccar.
GPL-3.0 (ideas only): Timetagger, arbtt, jrnl, traggo, homepage. AGPL-3.0 (ideas only): Kimai.
Source-available, non-OSI (ideas only): Screenpipe.
Unverified this pass: Kado (author claims MIT), Solidtime, Memex, uhabits — do not borrow code
from these four until the license file is read on a healthy clone.

*Team 30 — end of report.*
