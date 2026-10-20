# Calendar Skill

A local-first calendar. Events live in `calendar.json` inside the skill's
jail dir (schema-versioned JSON, atomic rewrites) — no account, no network,
works offline. This is the universal floor of the Team 21 design; remote
sync is a later transport (blueprint below), not part of this skill.

## Time discipline

- Every time is ISO 8601 **with a timezone** (`2026-10-20T15:00:00+05:30`
  or `...Z`). Naive times are refused with the reason — never guess a zone.
- `end` must be after `start`.

## Recurrence (RRULE-lite)

`recurrence`: `{"freq": "daily" | "weekly" | "monthly", "interval": n,
"until": iso}` or `{"freq": ..., "count": n}` — `until` and `count` are
mutually exclusive. Monthly series anchor on the original day, clamped
to short months: Jan 31 → Feb 28 → **Mar 31** (the anchor returns).
Cancel one instance with `cal_cancel(id, occurrence_start=...)`; cancel
without it removes the whole series.

## Tools

- `cal_add` — add an event (title, start, end, optional location/notes/recurrence).
- `cal_list` — occurrences in `[range_start, range_end)`, expanded and sorted
  (defaults: now → +31 days). `cal_next` — the next N upcoming.
- `cal_cancel` — whole series, or one occurrence via `occurrence_start`.
- `cal_import_ics` / `cal_export_ics` — RFC 5545 subset (below).
- `cal_brief` — a deterministic spoken brief for today: events in order,
  conflicts named with their overlap window, tight-gap warnings when
  back-to-back events (≤30 min apart) sit at different locations, and
  tomorrow's first event. No LLM is involved; pass `now` to pin the day.

## ICS subset — what travels, what is reported

Export writes VEVENTs with UID/DTSTAMP/DTSTART/DTEND/SUMMARY/LOCATION/
DESCRIPTION/RRULE/EXDATE, times normalized to UTC (`...Z`), lines folded
at 75 octets. Import reads the same subset plus `TZID=` parameters.
Anything outside it is **reported in the import result, never silently
dropped**: unknown properties, `VALARM`s, `RRULE` parts like `BYDAY`
(the series then imports as a single event), all-day `DATE` starts,
floating times, and a missing `DTEND` (a 1-hour duration is assumed and
the assumption is reported).

## Blueprint (not built): CalDAV sync

Per Team 21: transport order is (1) CalDAV via stdlib `http.client` +
`xml` (iCloud/Fastmail/Nextcloud/self-hosted), (2) a Google Calendar
adapter, (3) this ICS floor. Sync keeps a local cache with provider
cursors (CalDAV sync-token / Google nextSyncToken) so `cal_list` stays
instant and offline-tolerant; credentials live only as keyring
references. Build it as a sync layer *over* this store — the local
tools and their contracts do not change.
