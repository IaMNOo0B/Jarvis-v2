"""Calendar skill — local-first calendar (Team 21 design brief, local tier).

Storage: calendar.json in the skill jail —
{"schema_version": 1, "events": [...]}. Atomic rewrites (tmp + replace),
the reminders skill's discipline.

Every time is a timezone-aware ISO 8601 string; naive times are refused
with a plain-words reason (a floating time is a bug, not a default).
Recurrence is RRULE-lite: daily/weekly/monthly with interval, until XOR
count, and per-occurrence exceptions (cancel one instance of a series).

ICS (RFC 5545 subset) import/export is the universal floor: VEVENT with
DTSTART/DTEND/SUMMARY/LOCATION/DESCRIPTION/RRULE/EXDATE. Anything
outside the subset is reported in the result — never silently dropped.
CalDAV sync is a later transport (see SKILL.md); this tier is local.
"""

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

STORE_NAME = "calendar.json"
SCHEMA_VERSION = 1
_FREQS = ("daily", "weekly", "monthly")
_MAX_GENERATED = 20000  # per-event occurrence generation safety cap


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #

def _store_path(ctx) -> Path:
    return Path(ctx.jail_dir) / STORE_NAME


def _empty_store():
    return {"schema_version": SCHEMA_VERSION, "events": []}


def _load(ctx):
    p = _store_path(ctx)
    if not p.exists():
        return _empty_store()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return _empty_store()
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        return _empty_store()
    return {"schema_version": data.get("schema_version", SCHEMA_VERSION),
            "events": data["events"]}


def _save(ctx, store):
    p = _store_path(ctx)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(p)


# --------------------------------------------------------------------------- #
# Time helpers — timezone-aware or refused, in plain words
# --------------------------------------------------------------------------- #

def _parse_dt(value, field):
    """Parse an ISO 8601 string into an aware datetime, or refuse."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{field} must be an ISO 8601 time string, "
            "e.g. 2026-10-20T15:00:00+05:30.")
    text = value.strip()
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(
            f"{field} is not a readable ISO 8601 time: {value!r}. "
            "Use a form like 2026-10-20T15:00:00+05:30.") from None
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(
            f"{field} has no timezone: {value!r}. A calendar time must "
            "say which timezone it is in — add an offset like +05:30 "
            "or a trailing Z for UTC.")
    return dt


def _now_arg(args):
    if args.get("now"):
        return _parse_dt(args["now"], "now")
    return datetime.now().astimezone()


# --------------------------------------------------------------------------- #
# Recurrence expansion (RRULE-lite)
# --------------------------------------------------------------------------- #

def _days_in_month(year, month):
    if month == 12:
        nxt = datetime(year + 1, 1, 1)
    else:
        nxt = datetime(year, month + 1, 1)
    return (nxt - datetime(year, month, 1)).days


def _advance(start, freq, interval, k):
    """The k-th occurrence start (k=0 is the event's own start)."""
    if k == 0:
        return start
    if freq == "daily":
        return start + timedelta(days=interval * k)
    if freq == "weekly":
        return start + timedelta(weeks=interval * k)
    # monthly: anchor on the original day, clamped to the target month —
    # Jan 31 -> Feb 28 -> Mar 31 (the anchor returns, it does not drift).
    idx = (start.year * 12 + (start.month - 1)) + interval * k
    year, month0 = divmod(idx, 12)
    day = min(start.day, _days_in_month(year, month0 + 1))
    return start.replace(year=year, month=month0 + 1, day=day)


def _skip_ahead(start, freq, interval, floor_dt):
    """First k whose occurrence start is >= floor_dt (fast-forward)."""
    if start >= floor_dt:
        return 0
    if freq in ("daily", "weekly"):
        step = (timedelta(days=interval) if freq == "daily"
                else timedelta(weeks=interval))
        k = int((floor_dt - start) / step)
    else:
        months = ((floor_dt.year - start.year) * 12
                  + (floor_dt.month - start.month))
        k = max(0, months // interval - 1)
    while _advance(start, freq, interval, k) < floor_dt:
        k += 1
    return k


def _iter_occurrences(ev, range_start, range_end):
    """Yield (occ_start, occ_end) overlapping [range_start, range_end).

    COUNT is consumed by generated occurrences before exception
    filtering (RFC semantics: EXDATE removes from the counted set).
    UNTIL is inclusive of an occurrence starting exactly at it.
    """
    start = _parse_dt(ev["start"], "start")
    end = _parse_dt(ev["end"], "end")
    dur = end - start
    exceptions = set()
    for raw in ev.get("exceptions") or []:
        try:
            exceptions.add(_parse_dt(raw, "exception"))
        except ValueError:
            pass
    rec = ev.get("recurrence") or None
    if not rec:
        if start < range_end and end > range_start and start not in exceptions:
            yield start, end
        return
    freq = rec["freq"]
    interval = int(rec.get("interval") or 1)
    until = (_parse_dt(rec["until"], "recurrence.until")
             if rec.get("until") else None)
    count = rec.get("count")
    k = _skip_ahead(start, freq, interval, range_start - dur)
    emitted = k  # occurrences with index < k were already generated
    generated = 0
    while generated < _MAX_GENERATED:
        if count is not None and emitted >= count:
            break
        occ = _advance(start, freq, interval, k)
        if until is not None and occ > until:
            break
        if occ >= range_end:
            break
        emitted += 1
        k += 1
        generated += 1
        if occ in exceptions:
            continue
        occ_end = occ + dur
        if occ_end > range_start:
            yield occ, occ_end


def _occ_view(ev, occ_start, occ_end):
    return {
        "id": ev["id"],
        "title": ev["title"],
        "start": occ_start.isoformat(),
        "end": occ_end.isoformat(),
        "location": ev.get("location"),
        "notes": ev.get("notes"),
        "recurring": bool(ev.get("recurrence")),
    }


def _validate_recurrence(rec):
    if rec is None:
        return None
    if not isinstance(rec, dict):
        raise ValueError(
            "recurrence must be an object like "
            '{"freq": "weekly", "interval": 1, "count": 8}.')
    freq = rec.get("freq")
    if freq not in _FREQS:
        raise ValueError(
            "recurrence.freq must be one of daily, weekly, monthly — "
            f"got {freq!r}.")
    interval = rec.get("interval", 1)
    if (not isinstance(interval, int) or isinstance(interval, bool)
            or not 1 <= interval <= 99):
        raise ValueError(
            "recurrence.interval must be a whole number between 1 and 99.")
    until = rec.get("until")
    count = rec.get("count")
    if until is not None and count is not None:
        raise ValueError(
            "recurrence: give either until or count, not both — "
            "a series ends one way or the other.")
    out = {"freq": freq, "interval": interval}
    if until is not None:
        out["until"] = _parse_dt(until, "recurrence.until").isoformat()
    if count is not None:
        if (not isinstance(count, int) or isinstance(count, bool)
                or not 1 <= count <= 1000):
            raise ValueError(
                "recurrence.count must be a whole number between 1 and 1000.")
        out["count"] = count
    return out


# --------------------------------------------------------------------------- #
# Tools: add / list / next / cancel
# --------------------------------------------------------------------------- #

def _add(args, ctx):
    title = args.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title is required — give the event a name.")
    title = title.strip()
    if len(title) > 200:
        raise ValueError("title is too long (200 characters at most).")
    start = _parse_dt(args.get("start"), "start")
    end = _parse_dt(args.get("end"), "end")
    if end <= start:
        raise ValueError("end must be after start.")
    location = args.get("location")
    notes = args.get("notes")
    for field, val, cap in (("location", location, 500),
                            ("notes", notes, 2000)):
        if val is not None and (not isinstance(val, str) or len(val) > cap):
            raise ValueError(
                f"{field} must be a string of at most {cap} characters.")
    rec = _validate_recurrence(args.get("recurrence"))
    store = _load(ctx)
    ev = {
        "id": uuid.uuid4().hex[:12],
        "title": title,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "location": location or None,
        "notes": notes or None,
        "recurrence": rec,
        "exceptions": [],
    }
    store["events"].append(ev)
    _save(ctx, store)
    return {"id": ev["id"], "title": title,
            "start": ev["start"], "end": ev["end"]}


def _list(args, ctx):
    now = _now_arg(args)
    range_start = (_parse_dt(args["range_start"], "range_start")
                   if args.get("range_start") else now)
    range_end = (_parse_dt(args["range_end"], "range_end")
                 if args.get("range_end") else range_start + timedelta(days=31))
    if range_end <= range_start:
        raise ValueError("range_end must be after range_start.")
    out = []
    for ev in _load(ctx)["events"]:
        for occ_start, occ_end in _iter_occurrences(ev, range_start, range_end):
            out.append(_occ_view(ev, occ_start, occ_end))
    out.sort(key=lambda o: (o["start"], o["title"]))
    return {"events": out}


def _next(args, ctx):
    count = args.get("count", 5)
    if (not isinstance(count, int) or isinstance(count, bool)
            or not 1 <= count <= 50):
        raise ValueError("count must be a whole number between 1 and 50.")
    now = _now_arg(args)
    horizon = now + timedelta(days=370)
    out = []
    for ev in _load(ctx)["events"]:
        for occ_start, occ_end in _iter_occurrences(ev, now, horizon):
            out.append(_occ_view(ev, occ_start, occ_end))
    out.sort(key=lambda o: (o["start"], o["title"]))
    out = out[:count]
    return {"events": out, "count": len(out)}


def _cancel(args, ctx):
    store = _load(ctx)
    events = store["events"]
    ev = next((e for e in events if e["id"] == args.get("id")), None)
    if ev is None:
        return {"cancelled": False, "scope": None}
    occ_raw = args.get("occurrence_start")
    if not occ_raw:
        events.remove(ev)
        _save(ctx, store)
        return {"cancelled": True, "scope": "series"}
    occ = _parse_dt(occ_raw, "occurrence_start")
    if not ev.get("recurrence"):
        start = _parse_dt(ev["start"], "start")
        if occ == start:
            events.remove(ev)
            _save(ctx, store)
            return {"cancelled": True, "scope": "occurrence"}
        return {"cancelled": False, "scope": None}
    dur = _parse_dt(ev["end"], "end") - _parse_dt(ev["start"], "start")
    horizon = occ + dur + timedelta(seconds=1)
    for occ_start, _occ_end in _iter_occurrences(ev, occ, horizon):
        if occ_start == occ:
            ev.setdefault("exceptions", []).append(occ_start.isoformat())
            _save(ctx, store)
            return {"cancelled": True, "scope": "occurrence"}
    return {"cancelled": False, "scope": None}


# --------------------------------------------------------------------------- #
# ICS (RFC 5545 subset) — export
# --------------------------------------------------------------------------- #

def _ics_escape(text):
    return (str(text).replace("\\", "\\\\").replace("\r\n", "\\n")
            .replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;"))


def _ics_unescape(text):
    out = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append("\n" if nxt in "nN" else nxt)
            i += 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _fold_line(line):
    """Fold a content line to <=75-octet physical lines (RFC 5545 §3.1)."""
    if len(line.encode("utf-8")) <= 75:
        return line
    lines = []
    cur = ""
    cur_len = 0
    for ch in line:
        cl = len(ch.encode("utf-8"))
        if cur_len + cl > 75:
            lines.append(cur)
            cur = " " + ch
            cur_len = 1 + cl
        else:
            cur += ch
            cur_len += cl
    lines.append(cur)
    return "\r\n".join(lines)


def _fmt_utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _export_ics(args, ctx):
    store = _load(ctx)
    stamp = _fmt_utc(datetime.now(timezone.utc))
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//JARVIS v2//Calendar//EN", "CALSCALE:GREGORIAN"]
    for ev in store["events"]:
        start = _parse_dt(ev["start"], "start")
        end = _parse_dt(ev["end"], "end")
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{ev['id']}@jarvis.calendar")
        lines.append(f"DTSTAMP:{stamp}")
        lines.append(f"DTSTART:{_fmt_utc(start)}")
        lines.append(f"DTEND:{_fmt_utc(end)}")
        lines.append(f"SUMMARY:{_ics_escape(ev['title'])}")
        if ev.get("location"):
            lines.append(f"LOCATION:{_ics_escape(ev['location'])}")
        if ev.get("notes"):
            lines.append(f"DESCRIPTION:{_ics_escape(ev['notes'])}")
        rec = ev.get("recurrence")
        if rec:
            parts = [f"FREQ={rec['freq'].upper()}"]
            if rec.get("interval") and rec["interval"] != 1:
                parts.append(f"INTERVAL={rec['interval']}")
            if rec.get("count"):
                parts.append(f"COUNT={rec['count']}")
            if rec.get("until"):
                parts.append(
                    f"UNTIL={_fmt_utc(_parse_dt(rec['until'], 'until'))}")
            lines.append("RRULE:" + ";".join(parts))
        exceptions = ev.get("exceptions") or []
        if exceptions:
            stamps = ",".join(
                _fmt_utc(_parse_dt(x, "exception")) for x in exceptions)
            lines.append(f"EXDATE:{stamps}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    text = "\r\n".join(_fold_line(ln) for ln in lines) + "\r\n"
    return {"ics": text, "events": len(store["events"])}


# --------------------------------------------------------------------------- #
# ICS (RFC 5545 subset) — import
# --------------------------------------------------------------------------- #

_ICS_DT_RE = re.compile(r"^(\d{8})T(\d{6})(Z?)$")
_ICS_SUPPORTED_PROPS = {
    "UID", "DTSTART", "DTEND", "SUMMARY", "LOCATION", "DESCRIPTION",
    "RRULE", "EXDATE",
}
_ICS_METADATA_PROPS = {"DTSTAMP", "CREATED", "LAST-MODIFIED", "SEQUENCE"}


def _parse_ics_dt(value, params):
    """-> (aware datetime, None) or (None, plain-words reason)."""
    value = (value or "").strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        return None, "all-day DATE times are not supported"
    m = _ICS_DT_RE.match(value)
    if not m:
        return None, f"unrecognized time format {value!r}"
    try:
        naive = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    except ValueError:
        return None, f"unrecognized time format {value!r}"
    if m.group(3) == "Z":
        return naive.replace(tzinfo=timezone.utc), None
    tzid = params.get("TZID")
    if tzid:
        try:
            from zoneinfo import ZoneInfo
            return naive.replace(tzinfo=ZoneInfo(tzid)), None
        except Exception:
            return None, f"timezone {tzid!r} is not available on this system"
    return None, "floating time (no timezone) is not supported"


def _split_prop(line):
    """'DTSTART;TZID=Asia/Kolkata:2026...' -> (name, params, value)."""
    if ":" not in line:
        return line.strip().upper(), {}, ""
    head, value = line.split(":", 1)
    bits = head.split(";")
    params = {}
    for bit in bits[1:]:
        if "=" in bit:
            key, val = bit.split("=", 1)
            params[key.strip().upper()] = val.strip().strip('"')
    return bits[0].strip().upper(), params, value


def _unfold(text):
    raw = text.replace("\r\n", "\n").split("\n")
    lines = []
    for ln in raw:
        if ln[:1] in (" ", "\t") and lines:
            lines[-1] += ln[1:]
        elif ln.strip():
            lines.append(ln)
    return lines


def _parse_rrule(value):
    """-> (recurrence dict | None, [problem strings])."""
    parts = {}
    problems = []
    for bit in value.split(";"):
        if "=" in bit:
            key, val = bit.split("=", 1)
            parts[key.strip().upper()] = val.strip()
    freq = parts.get("FREQ", "").lower()
    if freq not in _FREQS:
        problems.append(
            f"RRULE FREQ={parts.get('FREQ', '?')} is not supported "
            "(only DAILY, WEEKLY, MONTHLY)")
        return None, problems
    extra = sorted(set(parts) - {"FREQ", "INTERVAL", "UNTIL", "COUNT"})
    if extra:
        problems.append(
            "RRULE parts not supported: " + ", ".join(extra))
        return None, problems
    rec = {"freq": freq, "interval": 1}
    if "INTERVAL" in parts:
        try:
            rec["interval"] = int(parts["INTERVAL"])
        except ValueError:
            problems.append(f"RRULE INTERVAL={parts['INTERVAL']!r} unreadable")
            return None, problems
    if "COUNT" in parts and "UNTIL" in parts:
        problems.append("RRULE had both COUNT and UNTIL; COUNT kept, "
                        "UNTIL dropped")
        parts.pop("UNTIL")
    if "COUNT" in parts:
        try:
            rec["count"] = int(parts["COUNT"])
        except ValueError:
            problems.append(f"RRULE COUNT={parts['COUNT']!r} unreadable")
            return None, problems
    if "UNTIL" in parts:
        until, err = _parse_ics_dt(parts["UNTIL"], {})
        if err:
            problems.append(f"RRULE UNTIL unreadable: {err}")
            return None, problems
        rec["until"] = until.isoformat()
    return rec, problems


def _import_one(props, store, report):
    """Import one parsed VEVENT. Returns the stored event or None."""
    label = None
    for name, _params, value in props:
        if name == "SUMMARY":
            label = _ics_unescape(value)
    uid_raw = next((v for n, _p, v in props if n == "UID"), "")
    label = label or uid_raw or "(untitled event)"

    def unsupported(construct, detail):
        report["unsupported"].append(
            {"construct": construct, "detail": detail, "event": label})

    def skipped(reason):
        report["skipped"].append({"event": label, "reason": reason})

    seen = {}
    for name, params, value in props:
        if name in _ICS_METADATA_PROPS:
            continue
        if name not in _ICS_SUPPORTED_PROPS:
            unsupported(name, "property is outside the supported subset "
                              "and was dropped")
            continue
        seen.setdefault(name, []).append((params, value))

    if "DTSTART" not in seen:
        skipped("no DTSTART — an event without a start cannot be imported")
        return None
    start, err = _parse_ics_dt(seen["DTSTART"][0][1], seen["DTSTART"][0][0])
    if err:
        skipped(f"DTSTART: {err}")
        return None
    if "DTEND" in seen:
        end, err = _parse_ics_dt(seen["DTEND"][0][1], seen["DTEND"][0][0])
        if err:
            skipped(f"DTEND: {err}")
            return None
    else:
        end = start + timedelta(hours=1)
        unsupported("DTEND", "missing; a 1-hour duration was assumed")

    title = label if label != "(untitled event)" else "Untitled event"
    location = (_ics_unescape(seen["LOCATION"][0][1])
                if "LOCATION" in seen else None)
    notes = (_ics_unescape(seen["DESCRIPTION"][0][1])
             if "DESCRIPTION" in seen else None)

    recurrence = None
    if "RRULE" in seen:
        recurrence, problems = _parse_rrule(seen["RRULE"][0][1])
        for problem in problems:
            unsupported("RRULE", problem)
        if recurrence is None and problems:
            unsupported("RRULE", "the series was imported as a single "
                                 "event (first occurrence only)")

    exceptions = []
    if "EXDATE" in seen:
        for _params, value in seen["EXDATE"]:
            for stamp in value.split(","):
                if not stamp.strip():
                    continue
                when, err = _parse_ics_dt(stamp, {})
                if err:
                    unsupported("EXDATE", f"{stamp!r}: {err}")
                else:
                    exceptions.append(when.isoformat())

    ev_id = uid_raw.strip()
    if ev_id.endswith("@jarvis.calendar"):
        ev_id = ev_id[: -len("@jarvis.calendar")]
    if not ev_id:
        ev_id = uuid.uuid4().hex[:12]
    ev_id = ev_id[:128]
    if any(e["id"] == ev_id for e in store["events"]):
        skipped("an event with this id already exists in the calendar")
        return None

    ev = {
        "id": ev_id,
        "title": title,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "location": location or None,
        "notes": notes or None,
        "recurrence": recurrence,
        "exceptions": exceptions,
    }
    store["events"].append(ev)
    return ev


def _import_ics(args, ctx):
    text = args.get("ics_text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("ics_text is required — pass the .ics file's "
                         "contents as text.")
    if "BEGIN:VCALENDAR" not in text:
        raise ValueError("ics_text does not look like an iCalendar file "
                         "(no BEGIN:VCALENDAR).")
    store = _load(ctx)
    report = {"imported": 0, "event_ids": [], "skipped": [],
              "unsupported": []}
    blocks = []
    current = None
    sub_depth = 0
    sub_name = None
    for line in _unfold(text):
        upper = line.strip().upper()
        if upper == "BEGIN:VEVENT":
            current = []
            sub_depth = 0
        elif upper == "END:VEVENT":
            if current is not None:
                blocks.append(current)
            current = None
        elif current is not None:
            if upper.startswith("BEGIN:"):
                sub_depth += 1
                sub_name = upper.split(":", 1)[1]
                if sub_name == "VALARM":
                    report["unsupported"].append({
                        "construct": "VALARM",
                        "detail": "alarms are not imported; the event "
                                  "itself still is",
                        "event": "(see following event)"})
                continue
            if upper.startswith("END:"):
                sub_depth = max(0, sub_depth - 1)
                continue
            if sub_depth == 0:
                current.append(_split_prop(line))
    for props in blocks:
        ev = _import_one(props, store, report)
        if ev is not None:
            report["imported"] += 1
            report["event_ids"].append(ev["id"])
    if report["imported"]:
        _save(ctx, store)
    return report


# --------------------------------------------------------------------------- #
# Brief — deterministic spoken-style summary, no LLM
# --------------------------------------------------------------------------- #

def _fmt_time(dt):
    return dt.strftime("%I:%M %p").lstrip("0")


def _fmt_range(start, end):
    s_txt = _fmt_time(start)
    e_txt = _fmt_time(end)
    if start.strftime("%p") == end.strftime("%p"):
        s_txt = s_txt.rsplit(" ", 1)[0]
    return f"{s_txt}–{e_txt}"


def _day_occurrences(events, day_start):
    day_end = day_start + timedelta(days=1)
    out = []
    for ev in events:
        for occ_start, occ_end in _iter_occurrences(ev, day_start, day_end):
            out.append((occ_start, occ_end, ev))
    out.sort(key=lambda t: (t[0], t[2]["title"]))
    return out


def _brief(args, ctx):
    now = _now_arg(args)
    tz = now.tzinfo
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    events = _load(ctx)["events"]
    today = _day_occurrences(events, day_start)
    tomorrow = _day_occurrences(events, day_start + timedelta(days=1))

    lines = [f"Calendar brief for {now.strftime('%A, %d %B %Y')}."]
    if not today:
        lines.append("Nothing scheduled today.")
    else:
        lines.append("Today:")
        for occ_start, occ_end, ev in today:
            loc = f" at {ev['location']}" if ev.get("location") else ""
            lines.append(
                f"- {_fmt_range(occ_start.astimezone(tz), occ_end.astimezone(tz))}"
                f" — {ev['title']}{loc}")

    conflicts = []
    for i in range(len(today)):
        a_start, a_end, a_ev = today[i]
        for j in range(i + 1, len(today)):
            b_start, b_end, b_ev = today[j]
            if b_start >= a_end:
                break
            ov_start, ov_end = max(a_start, b_start), min(a_end, b_end)
            if ov_start < ov_end:
                conflicts.append((a_ev, b_ev, ov_start, ov_end))
    for a_ev, b_ev, ov_start, ov_end in conflicts:
        lines.append(
            f"Conflict: {a_ev['title']} overlaps {b_ev['title']} "
            f"({_fmt_range(ov_start.astimezone(tz), ov_end.astimezone(tz))}).")

    for (a_start, a_end, a_ev), (b_start, b_end, b_ev) in zip(today,
                                                              today[1:]):
        gap = b_start - a_end
        if timedelta(0) <= gap <= timedelta(minutes=30):
            la, lb = a_ev.get("location"), b_ev.get("location")
            if la and lb and la.strip().lower() != lb.strip().lower():
                mins = int(gap.total_seconds() // 60)
                lines.append(
                    f"Tight gap: only {mins} minutes between "
                    f"{a_ev['title']} ({la}) and {b_ev['title']} ({lb}) "
                    "— allow travel time.")

    if tomorrow:
        occ_start, _occ_end, ev = tomorrow[0]
        lines.append(
            f"Tomorrow starts with {ev['title']} at "
            f"{_fmt_time(occ_start.astimezone(tz))}.")
    else:
        lines.append("Nothing on the calendar tomorrow.")

    return {"brief": "\n".join(lines), "date": now.date().isoformat(),
            "events_today": len(today), "conflicts": len(conflicts)}


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #

def handle(tool_name, args, ctx):
    args = args or {}
    if tool_name == "cal_add":
        return _add(args, ctx)
    if tool_name == "cal_list":
        return _list(args, ctx)
    if tool_name == "cal_next":
        return _next(args, ctx)
    if tool_name == "cal_cancel":
        return _cancel(args, ctx)
    if tool_name == "cal_import_ics":
        return _import_ics(args, ctx)
    if tool_name == "cal_export_ics":
        return _export_ics(args, ctx)
    if tool_name == "cal_brief":
        return _brief(args, ctx)
    raise ValueError(f"unknown tool {tool_name!r}")
