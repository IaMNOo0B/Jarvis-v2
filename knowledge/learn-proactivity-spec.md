# v2 Proactivity Spec — Helpful Without Being Creepy

*PHASE INFINITY, Research Cycle 23. Design specification. LEARNING ONLY — no project code touched.*

*Date: 2026-10-19. Status: design complete, unvalidated on real users.*

**The bar:** proactive but never creepy. A good butler doesn't hover, doesn't gossip about what he saw, doesn't wake you for trivia. This spec designs every proactive capability of JARVIS v2 against that bar — with the corpses of v1's screen watcher and scheduler as the anti-template.

**Terms in plain language:**
- **Proactivity** = JARVIS doing something useful without being asked.
- **Nudge** = one short suggestion JARVIS offers; you can take it or dismiss it.
- **Egress** = your data leaving your PC (to Google, to a cloud brain, anywhere).
- **Opt-in** = off until you explicitly turn it on.

---

## 1. The Proactivity Contract [HC]

Every proactive capability is a contract with three clauses. If any clause is missing, the capability doesn't ship.

### The three clauses

1. **Explicit consent, per capability.** Not a blanket "allow proactivity" checkbox. Each capability (screen watching, observed-context reminders, suggestions, routines) has its own opt-in, its own plain-language description, and its own off switch. (Source: R13 requirement; privacy-engineering consent lifecycle — GRANT → ACTIVE → REVOKED → PURGED.)
2. **Stated data flow.** For each capability, the exact answer to: what is observed, where is it processed (on your PC vs sent to whom), how often, what is kept. (Source: H-X8 — v1 sent full-screen JPEGs to Google every 60s with no disclosure.)
3. **Revocation with teeth.** Turning it off stops the observation immediately — not "next restart," not "flags it for later." Data collected under the revoked permission is offered for deletion (privacy-engineering §4: "revoke + delete everything collected under it").

### What JARVIS may notice vs what it must never act on unprompted

| Layer | Allowed to notice | Allowed to do unprompted | Requires your initiation |
|---|---|---|---|
| **Observation** | Screen content (if opted in), your requests, task progress, time passing | Nothing visible yet | — |
| **Suggestions** | Patterns in your work (repeated tasks, stalling projects) | Offer ONE nudge (see §3) | Act on the nudge's content |
| **Reminders** | Time passing, your own stated commitments | Announce a reminder YOU set | Create reminders from observed context (see §4) |
| **Safety** | Failing hardware, dying battery, full disk | Warn once (this is the interruption-budget exception, §5) | — |
| **Never** | Passwords, other people's screens, private conversations | Nothing — not even "noticing" is stored (see §6) | Everything |

**The never-act list (hard rules):**
- JARVIS never speaks raw model output about your screen aloud. Model text about your screen is **untrusted content** — it goes through the same evidence markers as any tool result, and it is displayed, never spoken, until you've seen it. (Source: H-X2 — v1's "remark" spoken verbatim was a voice-phishing vector: attacker-controlled pixels → JARVIS speaks arbitrary attacker text.)
- JARVIS never acts on a screen observation that implies a financial, destructive, or irreversible action. It may *mention* it once; the action is always yours. (Source: S3 two-dial safety — confirm writes, real out-of-band gate.)
- JARVIS never "notices" something about someone else on your screen and acts on it (messages a contact, summarizes someone's document). Proactivity is scoped to YOU. (Source: §6 privacy boundaries.)

---

## 2. The Screen Watcher Done Right [HC]

v1's watcher was a surveillance default with a broken loop. v2's watcher is opt-in, disclosed, disciplined, and dumb in the right ways.

### Opt-in with explicit egress disclosure [VC — R13]

The enable screen states, in plain language, before anything captures:

> "Screen watching sends a screenshot to [model name, e.g. Gemini] every [N] minutes. Screenshots may contain passwords, banking, and private messages visible on screen. Captures are held in RAM only and never saved to disk. You can turn this off anytime in Settings → Privacy."

- **Off by default.** Not "off but nagging." Off. (Source: R13; M-X11 camera-on-by-default.)
- **The model and interval are named**, not "a cloud AI." If the model changes, consent is re-asked. (Source: H-X8 — v1's Settings never disclosed cloud egress.)
- **The interval has a floor.** No setting below 60 seconds is offered in the UI — the LOW-list corpse ("screen-watcher tunables allow 15s screenshot→Google with no egress warning") is closed by not offering the knob at all. Advanced users can edit config; the GUI protects the default.

### RAM-only captures [VC — privacy-engineering §1]

- Capture → analyze → discard. The screenshot object is freed after the brain's judgment; nothing is written to disk, ever. (Source: v1 behavior was already RAM-only — keep it, and make it a tested invariant, not a convention.)
- **Own-HUD exclusion is real.** v1's `own_hud` skip still uploaded the capture (LOW list). v2 excludes the HUD region before upload, verified by test.

### The judgment loop (probabilistic gating + cooldowns) [HC]

v1's design — glance each minute, ask the cloud brain "does he look stuck," speak when confident — is kept, but hardened:

1. **Glance** (local, cheap): capture at interval N.
2. **Triage** (local, cheap): is the screen meaningfully different from last glance? Is the foreground app one where interruption is ever appropriate? If no → discard, no cloud call. This keeps the cloud bill and the egress surface small.
3. **Ask** (cloud): only on triage-pass. The prompt frames the screenshot as untrusted input (S1 instruction hierarchy).
4. **Gate**: the brain's answer is a *candidate remark*, never spoken directly. It goes through:
   - **Do-not-disturb check** (§2, below) — if DND, the remark is logged to the observation audit trail (§6) and discarded.
   - **Cooldown**: no two watcher remarks within 30 minutes, ever. (Source: M-I25 — v1's false-positive rate up to 0.875 with no DND awareness.)
   - **Novelty check**: if the remark is substantively the same as the last one, discard. No repeating yourself.
   - **Display-first**: the remark appears as a quiet HUD card. It is NEVER spoken aloud unprompted. (Source: H-X2, M-V2 — v1's watcher bypassed the mic-coordination state machine and talked over the user; the LOW-list corpse "briefings default speak unprompted (overheard).")
5. **Speak only if summoned**: the user can tap the card to hear it. Voice is pull, never push, for proactive content.

### Do-not-disturb awareness [HC — M-I25]

The watcher checks, before every remark, a DND signal that is true when ANY of:

- A screen-share / video call is active (detect via foreground window class list — Teams/Zoom/Meet/Webex — plus a manual "in a meeting" toggle).
- A password field has focus, or a known banking/payment URL is foreground (the never-observe list, §6 — in these cases the capture itself is skipped, not just the remark).
- The user has spoken or typed in the last 60 seconds (don't interrupt active work — "never mid-task," §3).
- Quiet hours (user-configurable, default 22:00–08:00).

DND is checked in deterministic code, not by asking the model. The model doesn't get a vote on whether you're in a meeting.

### Failure discipline [VC — M-I24, M-I26]

- **Capture failures back off.** UAC desktop, lock screen, RDP disconnect: on failure, wait 5 min before retry, then 15, then stop trying until the next successful capture. Never a tight fail-loop. (Source: M-I24 — v1's `catch → continue` burned CPU forever.)
- **Provider failures disable, not retry.** N auth failures in a row (default 3) → watcher auto-disables with a plain-language notice: "Screen watching turned itself off — [provider] rejected the key 3 times. Check Settings → API Keys." (Source: M-I26 — v1 kept uploading screenshots to Google for a broken feature.)
- **Every capture failure is logged** to the observation audit trail (§6) — the user can see "watcher skipped 4 glances during your meeting."

### What the watcher may say vs what needs your initiation

| The watcher may (as a quiet card) | The watcher may never |
|---|---|
| "You've been on this error for 20 minutes — want me to look up the fix?" | Speak anything aloud unprompted |
| "This looks like the same crash as Tuesday — I kept notes" | Act on what it sees (close windows, type, click) |
| "Meeting in 10 minutes" (from YOUR calendar, not pixels) | Mention anything about another person's content on screen |
| Nothing else | Send the screenshot anywhere except the disclosed model |

---

## 3. The Foresight Engine [HC]

From cog's `/foresight`: **one evidence-based actionable nudge**, never a feed. The engine watches your *work patterns* (not your screen pixels) and offers a single suggestion at idle moments.

### The nudge contract

- **One nudge at a time.** A nudge occupies a single quiet card. A second nudge never appears while the first is unacknowledged — it queues or expires. (The anti-pattern: notification piles that train you to ignore everything. Source: M-I25's approval-fatigue cousin.)
- **Evidence-based.** Every nudge carries its evidence in one line: "Because: you opened this repo 4 times this week and never committed." No evidence → no nudge. (Source: cog /foresight — "do Y because of X and Z.")
- **Actionable.** Every nudge has a one-tap action attached ("Open the repo," "Draft the reminder," "Dismiss"). A nudge you can't act on is noise.
- **Read-only w.r.t. memory.** The foresight pass reads state; it never writes memories or changes config. (Source: cog — "/foresight is read-only, never corrupts memory.")

### The velocity taxonomy (from cog) [MC]

The engine classifies each tracked project/goal into one of:

| State | Meaning | Nudge posture |
|---|---|---|
| **Accelerating** | Activity increasing week over week | Silent. Don't interrupt momentum. |
| **Cruising** | Steady activity | Silent. |
| **Stalling** | Activity dropped ≥50% vs its own baseline, 7+ days | ONE nudge: "X has stalled — want to look at it together?" Then back off for 14 days regardless of dismissal. |
| **Dormant** | No activity 30+ days, was active before | ONE nudge, gentle: "X is still here if you want it." Then never again unless activity resumes. |

Baselines are per-project (its own history), never cross-project comparisons. A project you touch monthly isn't "stalling" — the engine learns your cadence per project before it dares to nudge.

### When nudges fire

- **Idle moments only**: no keyboard/mouse input for 5+ minutes, no fullscreen app, not in quiet hours, DND clear. Never mid-task — the engine checks the same DND signal as the watcher (§2).
- **Max 2 foresight nudges per day**, and they share the interruption budget (§5).

### Dismissal learning [HC]

- Dismissing a nudge records (nudge-type, context). A dismissed nudge type fires **half as often** next time; dismissed twice → that type is muted for 30 days, then one trial re-appears (people's needs change; permanent mutes go stale).
- "Don't suggest this again" (explicit) → permanent mute for that type, listed in Settings → Proactivity where it can be un-muted. Explicit beats inferred, always.
- The engine never asks "was this helpful?" — dismissal IS the feedback. No surveys, no ratings, no friction. (Source: Owais's UX instincts — one-tap, no interrogation.)

### The three-gate promotion (from cog /reflect) [HC]

When the same nudge-worthy pattern recurs, it graduates:

1. **Gate 1 — recurring pattern.** Seen ≥3 times spanning ≥2 weeks. (Not a single observation.)
2. **Gate 2 — coverage check.** Does an existing routine, reminder, or broader rule already cover it? If yes, suggest the routine instead of re-nudging.
3. **Gate 3 — one actionable timeless line.** It becomes a standing suggestion in Settings → Proactivity ("Offer to look up fixes when I'm stuck on an error >20 min") that you can toggle — never a hardcoded behavior.

---

## 4. Reminders and Routines [HC]

### Durable scheduler (the H-I10 fix) [VC]

- Every reminder/routine is persisted **atomically** (temp → fsync → rename) to the data dir the moment it's created — before the acknowledgment is spoken. (Source: H-I10 — v1's reminders were in-memory only; restart = all pending reminders vanish silently. Also R6.)
- On startup, the scheduler loads pending items, computes which fired while away, and handles them per the wake policy below — never silently, never all at once.

### The wake policy (the H-I9 fix) [VC]

After sleep/hibernate/offline, missed reminders are NOT burst-fired back-to-back:

1. **Collapse**: all missed occurrences of the same reminder collapse into ONE announcement ("You missed 3 check-ins while away — the next is at 6pm").
2. **Expire**: reminders whose relevance window passed (a "leave in 10 minutes" from 3 hours ago) are marked expired, listed once in the morning digest, never announced.
3. **Digest, don't barrage**: everything missed goes into a single "while you were away" card. One card. The user pulls details.
4. **Re-arm ordering** (H-I8 fix): the next occurrence is scheduled BEFORE the announcement is attempted. A failed announcement never kills the future schedule.

### Reminder UX

- **Announce once.** A reminder fires once as a quiet card + optional single chime. No repeat nagging. Snooze (10 min / 1 hr / tomorrow) is one tap. (Source: the anti-nag principle — repeated firing is how reminders become wallpaper.)
- **Voice-driven reminders are validated** before they're accepted. "Remind me at 7:30" parses; "remind me at banana" gets "I didn't catch the time — when?" — never a ValueError aborting the turn. (Source: H-I7 — v1's unvalidated time parse crashed the brain turn.)
- **Reminders run on the UI thread via queued signals.** The scheduler never touches Qt objects from its daemon thread. (Source: M-I17 — v1's thread-affinity crashes.)
- **Briefing content failures degrade, never speak errors.** If the weather API fails, the briefing says "Weather's unavailable right now" — never reads the raw error string aloud. (Source: M-I18 — v1 spoke the error string as the briefing.)
- **Network calls in briefings have independent timeouts** and never block other reminders. (Source: M-I19 — v1's `_news` call stalled all reminders behind it.)

### Routines as user-authored contracts [MC]

- A routine is a standing instruction YOU wrote ("Every weekday at 8am, brief me: calendar, weather, top news"). It is a contract: JARVIS executes exactly what it says, and any deviation (a step fails, a source is unavailable) is reported, not improvised around.
- Routines are listed in Settings → Routines with per-routine enable, edit, and a "last run" status. A routine that failed 3 times in a row auto-pauses with a notice — never a silent death, never an infinite error loop. (Source: H-I8's silent-stop corpse.)
- **Routines never gain new powers.** A routine can't start doing things you didn't write into it. If the brain wants to extend a routine, that's a nudge (§3), not an edit.

### Observed-context reminders — the hard line [HC]

JARVIS may **suggest** a reminder from observed context ("You said 'call mom tomorrow' — want a reminder?"). It may **never create** one unprompted. The suggestion is a nudge (§3); creation is always your tap. (Source: the proactivity contract §1 — acting on observations is the line between helpful and creepy.)

---

## 5. The Interruption Budget [MC]

Attention is the scarcest resource. JARVIS gets a budget and spends it like money.

### The budget

- **Default: 3 unprompted interruptions per day**, counting watcher remarks (§2), foresight nudges (§3), and system warnings. Reminders YOU set don't count — those are your own appointments, not interruptions.
- **The budget is visible**: a tiny indicator in Settings → Proactivity ("2 of 3 used today"). Invisible budgets can't be trusted.
- **Rollover: none.** Unused interruptions don't accumulate. (A rollover balance is an excuse to binge-interrupt on quiet days.)

### The escalation rule

- **Truly urgent breaks the budget**: failing disk, security events (a blocked attack, a revoked key), a reminder you marked "critical." Urgent is defined narrowly and listed in the UI — if everything is urgent, nothing is. (Source: the fault-tree discipline — enumerate, don't hand-wave.)
- **Everything else queues.** When the budget is spent, lower-priority nudges wait for tomorrow's budget or expire. The queue is visible; nothing vanishes silently.

### Adaptation to feedback [MC]

- If you act on nudges often (tap-through rate high), the budget proposal rises — JARVIS *asks* (nudge, naturally): "My suggestions seem useful — raise my daily limit from 3 to 5?" Your tap decides.
- If you dismiss everything, the budget proposal falls — same mechanism, opposite direction, floor of 1 (urgent warnings always allowed).
- The budget number itself is never changed silently. It's your attention; you set the price.

### The calm-voice rule [HC]

Every unprompted interruption — card or spoken — uses the same calm register: what happened, what you can do, one tap. No exclamation, no urgency inflation, no "URGENT!!!" styling for non-urgent things. (Source: P1 narrate-work-live — "one auto-retry with a calm status line before ever surfacing failure." The boy-who-cried-wolf failure mode is a proactivity killer: inflate urgency once, and every future warning is ignored.)

---

## 6. Privacy Boundaries [HC]

### What proactive observation never touches [VC — R13, privacy-engineering]

- **Password fields and secrets.** Capture is skipped (not redacted after — skipped) when a password field has focus. (Redaction-after-capture is the wrong layer; the pixels should never exist.)
- **Banking, payment, and health portals.** URL/domain allowlist of sensitive categories — when foreground, the watcher doesn't capture at all.
- **Other people's content.** Messages, documents, or screens belonging to someone else are never summarized, never acted on, never stored. If the watcher sees them, the glance is discarded at triage (§2 step 2).
- **Bystander audio.** Other voices in mic range are processed transiently for VAD and never persisted. (Source: privacy-engineering §1 — R13.)
- **Other profiles.** If multi-profile ever exists, observation is per-profile with hard isolation (privacy-engineering §1: separate SQLite files; §3 DP tripwire #3).

### The observation audit trail [HC]

- **You can see everything it noticed.** Settings → Privacy → "What JARVIS observed" shows the audit log: timestamp, capability (watcher/foresight), what triggered, what was decided (remark shown / discarded / DND-skipped), and what was sent where. (Source: privacy-engineering consent principle — "invisible permissions are un-revoked permissions." Extended: invisible *observations* are un-audited surveillance.)
- Screenshots themselves are never in the log (RAM-only, §2) — the log records *that* a capture happened and its outcome, not the pixels.
- The audit trail has the same retention policy as session logs (default 90 days, then summarize → archive → delete) and is covered by the deletion checklist.

### Consent lifecycle per capability [HC — privacy-engineering §4]

Each proactive capability independently moves through GRANT → ACTIVE (scoped, **expiring**) → REVOKED → PURGED:

- **Expiry by default.** Screen watching granted "for 30 days" — at expiry, JARVIS asks to renew (that's one nudge, and it counts against nothing; consent renewal is exempt from the interruption budget). A 2026 grant doesn't silently authorize 2028 observation.
- **Revocation = immediate stop + offered purge.** "Revoke + delete everything collected under it" runs the deletion checklist scoped to that capability's data.
- **Credentials die with the permission.** If the watcher used a provider key, revoking the watcher doesn't revoke the key (keys are shared) — but any capability-scoped tokens are destroyed.

---

## 7. Failure Table — Every v1 Corpse Mapped [VC]

| Corpse | Finding | Spec clause that prevents it |
|---|---|---|
| H-X2 | Watcher "remark" spoken verbatim = voice phishing | §1 never-act list: model text about screen is untrusted, displayed never spoken; §2 display-first, voice is pull-only |
| H-X8 | Full-screen JPEG to Google every 60s, undisclosed | §2 opt-in screen with named model + interval + plain-language egress disclosure; §1 stated-data-flow clause |
| M-V2 | Watcher speech bypasses mic state machine, talks over user | §2 display-first (never spoken unprompted); §3 idle-moments-only firing rule |
| M-I24 | Capture failures → tight fail-loop, CPU burn | §2 failure discipline: exponential backoff 5→15 min, then stop until success |
| M-I25 | False positives, no DND awareness, speaks during meetings | §2 DND signal (screen-share, password focus, recent input, quiet hours) checked in deterministic code; 30-min cooldown; novelty check |
| M-I26 | Revoked key → keeps uploading screenshots | §2 provider-failure rule: 3 auth failures → auto-disable with plain-language notice |
| H-I7 | Unvalidated reminder time → ValueError aborts turn | §4 reminder validation before acceptance; "I didn't catch the time" instead of a crash |
| H-I8 | Speak failure → re-arm never runs → briefing dies silently | §4 re-arm ordering: next occurrence scheduled BEFORE announcement attempted |
| H-I9 | Sleep/wake → burst-fire of missed reminders | §4 wake policy: collapse → expire → single digest card |
| H-I10 | Reminders in-memory only → vanish on restart | §4 durable scheduler: atomic persist before acknowledgment |
| M-I17 | Scheduler touches Qt from daemon thread → crashes | §4 queued-signals rule: scheduler never touches UI objects directly |
| M-I18 | Network error spoken aloud as briefing | §4 briefing degradation: "unavailable right now," never raw error strings |
| M-I19 | `_news` no timeout stalls all reminders | §4 independent timeouts per briefing source; failures never block siblings |
| M-X11 | Camera on by default | §2 + §1: every proactive capability off by default, explicit opt-in |
| LOW: 15s screenshot interval tunable, no egress warning | Tunables allow aggressive capture | §2 interval floor: UI offers nothing below 60s |
| LOW: `own_hud` skip still uploads capture | Exclusion that doesn't exclude | §2 exclusion verified by test, not by flag |
| LOW: Briefings speak unprompted (overheard) | Default-spoken proactive content | §2/§4 display-first; voice is pull-only for proactive content |

**No orphans.** Every watcher/scheduler/proactivity corpse from the autopsy has a clause. If a future corpse is found, it gets a row here first, then a fix.

---

## Confidence & Unknowns Summary

| Claim | Confidence |
|---|---|
| v1 corpse inventory and root causes | [VC] — read directly from FAILURE-ANALYSIS.md |
| Opt-in + egress disclosure requirement | [VC] — R13, derived from H-X8 |
| RAM-only capture as tested invariant | [HC] — v1 behavior was RAM-only by convention; making it a tested invariant is new |
| Display-first, voice-pull-only for proactive content | [HC] — derived from H-X2 + M-V2; voice-phishing vector is real |
| DND signal composition (screen-share, password focus, recency, quiet hours) | [HC] — M-I25 demands it; exact detection methods need prototyping |
| 30-min cooldown, 3/day budget, 60s interval floor | [MC] — principled numbers, unvalidated on real usage; tune from the audit trail |
| Foresight velocity taxonomy thresholds (50% drop, 7/14/30 days) | [MC] — from cog; thresholds are proposals |
| Dismissal half-life learning rule | [MC] — reasonable, untested; the "trial re-appears after 30 days" needs care |
| Wake policy (collapse/expire/digest) | [HC] — directly answers H-I9; exact UX needs prototyping |
| Observation audit trail design | [HC] — derived from consent-visibility principle |
| Routine auto-pause after 3 failures | [MC] — number is a proposal |

### Open questions [UK]

1. **The "feels creepy" line is ultimately empirical.** No spec can fully predict which nudges delight vs disturb. The audit trail + dismissal learning are the instruments; the first month of real use is the experiment. Ship the instruments, tune the thresholds.
2. **Screen-share detection reliability** on Windows (window-class lists vs OS-level APIs) — prototype needed.
3. **Whether 3/day is the right budget** — unknown until measured; the adaptation mechanism (§5) matters more than the starting number.
4. **Foresight on goals vs tasks** — the velocity taxonomy assumes trackable projects; Owais's actual usage patterns will reshape the categories.

## Cross-links

- FAILURE-ANALYSIS.md: H-X2, H-X8, M-V2, M-I24/25/26, H-I7/8/9/10, M-I17/18/19, M-X11, R13, LOW-list watcher items
- learn-privacy-engineering.md: consent lifecycle (§4), RAM-only collection (§1), deletion checklist (§2), audit/visibility principles
- DECISION-PLAYBOOK.md: S1 (instruction hierarchy — watcher output is untrusted), S3 (two-dial safety), P1 (narrate calmly), M2 (Hermes review loop — the engine that feeds foresight candidates)
- learn-reliability-spec.md (Cycle 12): degradation ladder, SLOs — proactivity degrades before core function
- AGENTS.md: cog /foresight pattern (one evidence-based nudge, velocity taxonomy, read-only)

## References

- marciopuga/cog (MIT, verified): `/foresight` — one evidence-based actionable nudge; velocity taxonomy (Accelerating/Cruising/Stalling/Dormant); three-gate promotion; read-only foresight. (Studied 2026-10-19, `cog-deep-dive.md`.)
- FAILURE-ANALYSIS.md, `~/workspace/jarvis-build/` — all corpse citations above.
- learn-privacy-engineering.md — consent lifecycle, deletion, RAM-only collection.
