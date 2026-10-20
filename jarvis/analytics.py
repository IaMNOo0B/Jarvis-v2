"""Analytics — the canonical event-transform layer (Analytics Team).

ActivityWatch pattern (aw-core/aw_transform), reimplemented in v2's
stdlib style — the MPL-2.0 algorithms were re-derived from the Team 30
field report, no ActivityWatch code is copied.

Why this module exists: v2 stores POINT events (session store) and point
samples (watcher). Every credible quantified-self system converges on
the same move — canonicalize raw logs into clean INTERVAL events first,
then let every consumer (morning digest, anticipation, self-review)
read the canonical form instead of re-deriving metrics from raw logs
in its own bespoke way.

An Event is (ts, duration_s, data): an interval starting at epoch
second `ts`, lasting `duration_s` seconds, carrying a data dict
(what happened: {"app": "code", "title": "..."}). Point samples are
events with duration_s == 0.

HARD GUARANTEES (this is a pure layer):
  - No I/O. No clocks. Nothing here calls time.time() or reads a file;
    every instant an output depends on arrives as an argument.
  - Inputs are never mutated. Every transform returns new Event
    objects with copied data dicts.
  - Deterministic: same input list -> same output list, always.
    Outputs are sorted by (ts, end).

Stdlib only: dataclasses, datetime/calendar (day bounds), re.
"""

from __future__ import annotations

import re
from calendar import timegm
from dataclasses import dataclass, field
from datetime import date

__all__ = [
    "Event",
    "UNCATEGORIZED",
    "flood",
    "merge_adjacent",
    "classify",
    "period_summary",
    "intersect",
]

#: Bucket name period_summary uses for events with no category.
UNCATEGORIZED = "uncategorized"


# --------------------------------------------------------------------------- #
# The atom
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Event:
    """One canonical interval event.

    ts is epoch seconds (float). duration_s must be >= 0; 0 is a point
    sample (a heartbeat, an instantaneous observation).
    """

    ts: float
    duration_s: float = 0.0
    data: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "ts", float(self.ts))
        object.__setattr__(self, "duration_s", float(self.duration_s))
        if self.duration_s < 0:
            raise ValueError(
                f"duration_s must be >= 0, got {self.duration_s}")
        if self.data is None:
            object.__setattr__(self, "data", {})

    @property
    def end(self) -> float:
        """Epoch second at which this event stops (exclusive)."""
        return self.ts + self.duration_s

    def _copy(self, ts: float | None = None,
              duration_s: float | None = None,
              data: dict | None = None) -> "Event":
        return Event(self.ts if ts is None else ts,
                     self.duration_s if duration_s is None else duration_s,
                     dict(self.data) if data is None else data)


def _sorted(events) -> list[Event]:
    return sorted(events, key=lambda e: (e.ts, e.end))


# --------------------------------------------------------------------------- #
# flood — gap-fill / midpoint-split (the noise -> honest-time transform)
# --------------------------------------------------------------------------- #

def flood(events, pulsetime: float = 5.0) -> list[Event]:
    """Fill small gaps and resolve overlaps, ActivityWatch-style.

    Walking the events in time order, for each adjacent pair:

    - OVERLAP (next starts before prev ends): the LATER event wins.
      Prev is truncated to end where next begins, so no second of time
      is ever double-counted. If prev is entirely covered it is dropped
      and the check repeats against the new previous event.
    - GAP <= pulsetime: the gap is measurement noise, not a real break.
      Equal data -> the two events MERGE into one spanning both.
      Different data -> the uncertain interval is split at its
      MIDPOINT: prev extends to the midpoint, next starts there.
    - GAP > pulsetime: a real break; both events pass through as-is.

    `pulsetime` defaults to ActivityWatch's 5 seconds.
    """
    if pulsetime < 0:
        raise ValueError(f"pulsetime must be >= 0, got {pulsetime}")
    out: list[Event] = []
    for ev in _sorted(e._copy() for e in events):
        cur = ev
        # Resolve overlap against the tail of `out`: later event wins.
        while out and cur.ts < out[-1].end:
            prev = out[-1]
            kept = cur.ts - prev.ts
            if kept > 0:
                out[-1] = prev._copy(duration_s=kept)
            else:
                out.pop()  # prev entirely covered by cur
        if out:
            prev = out[-1]
            gap = cur.ts - prev.end
            if 0 <= gap <= pulsetime:
                if prev.data == cur.data:
                    # Same thing on both sides: one event spanning all.
                    out[-1] = prev._copy(duration_s=cur.end - prev.ts)
                    continue
                mid = prev.end + gap / 2.0
                out[-1] = prev._copy(duration_s=mid - prev.ts)
                cur = cur._copy(ts=mid, duration_s=cur.end - mid)
        out.append(cur)
    return out


# --------------------------------------------------------------------------- #
# merge_adjacent — collapse touching runs of the same thing
# --------------------------------------------------------------------------- #

def merge_adjacent(events, key=None) -> list[Event]:
    """Merge consecutive events that touch and are "the same".

    Sameness is full data-dict equality by default, or equality of
    `key(data)` when a key function is given (the merged event keeps
    the FIRST event's data — pick keys that capture identity, e.g.
    lambda d: d.get("app")). Two events merge only when they touch or
    overlap (next.ts <= prev.end); a real gap keeps them separate —
    bridging gaps is flood()'s job, not this function's.
    """
    out: list[Event] = []
    for ev in _sorted(e._copy() for e in events):
        if out:
            prev = out[-1]
            if key is not None:
                same = key(prev.data) == key(ev.data)
            else:
                same = prev.data == ev.data
            if same and ev.ts <= prev.end:
                new_end = max(prev.end, ev.end)
                out[-1] = prev._copy(duration_s=new_end - prev.ts)
                continue
        out.append(ev)
    return out


# --------------------------------------------------------------------------- #
# classify — owner rules -> categories
# --------------------------------------------------------------------------- #

def _haystack(data: dict) -> str:
    """The text rules match against: the event's string values,
    joined in sorted-key order (deterministic for a given data dict)."""
    return " ".join(str(v) for _, v in sorted(data.items())
                    if isinstance(v, str))


def _compile_rule(rule) -> tuple:
    """Normalise one owner rule to (matcher, category).

    Accepted shapes:
      (pattern, category)                 substring, case-insensitive
      (pattern, category, "regex")        re.search, flags inline
      {"pattern": p, "category": c}       substring (dict form)
      {"match": p, "category": c, "regex": True}
    Malformed rules raise ValueError — a broken rule file must fail
    loud at load time, never silently misclassify the owner's day.
    """
    if isinstance(rule, dict):
        pattern = rule.get("pattern", rule.get("match"))
        category = rule.get("category")
        is_regex = bool(rule.get("regex", False))
    elif isinstance(rule, (tuple, list)) and len(rule) in (2, 3):
        pattern, category = rule[0], rule[1]
        is_regex = len(rule) == 3 and rule[2] == "regex"
        if len(rule) == 3 and not is_regex:
            raise ValueError(f"third rule element must be 'regex': {rule!r}")
    else:
        raise ValueError(f"malformed classify rule: {rule!r}")
    if not isinstance(pattern, str) or not pattern:
        raise ValueError(f"rule pattern must be a non-empty str: {rule!r}")
    if not isinstance(category, str) or not category:
        raise ValueError(f"rule category must be a non-empty str: {rule!r}")
    if is_regex:
        rx = re.compile(pattern)

        def matcher(text: str, _rx=rx) -> bool:
            return _rx.search(text) is not None
    else:
        needle = pattern.lower()

        def matcher(text: str, _n=needle) -> bool:
            return _n in text.lower()
    return matcher, category


def classify(events, rules) -> list[Event]:
    """Tag each event with data["category"] from owner rules.

    Rules are tried in order; FIRST match wins (rule order is the
    priority — put specific rules before broad ones). An event no
    rule matches passes through unchanged (no "category" key added;
    period_summary counts those under UNCATEGORIZED).
    """
    compiled = [_compile_rule(r) for r in rules]
    out: list[Event] = []
    for ev in events:
        text = _haystack(ev.data)
        category = None
        for matcher, cat in compiled:
            if matcher(text):
                category = cat
                break
        if category is None:
            out.append(ev._copy())
        else:
            data = dict(ev.data)
            data["category"] = category
            out.append(ev._copy(data=data))
    return out


# --------------------------------------------------------------------------- #
# period_summary — totals per category for one UTC day
# --------------------------------------------------------------------------- #

def _day_bounds(day) -> tuple[float, float, str]:
    """(start_epoch, end_epoch, 'YYYY-MM-DD') for a UTC calendar day.

    `day` is a datetime.date or a 'YYYY-MM-DD' string.
    """
    if isinstance(day, str):
        day = date.fromisoformat(day)  # ValueError on garbage: fail loud
    start = float(timegm((day.year, day.month, day.day, 0, 0, 0, 0, 0, 0)))
    return start, start + 86400.0, day.isoformat()


def period_summary(events, day) -> dict:
    """Duration totals per category for one UTC day.

    Events are CLIPPED to the day: an event spanning midnight counts
    only the part inside the day on each side. Zero-duration point
    events contribute nothing (they have no duration to total).

    Returns {"day": 'YYYY-MM-DD', "total_s": float,
             "by_category": {category: seconds}} with by_category
    ordered by (-seconds, category) — deterministic.
    """
    start, end, day_str = _day_bounds(day)
    totals: dict[str, float] = {}
    total = 0.0
    for ev in events:
        lo = max(ev.ts, start)
        hi = min(ev.end, end)
        if hi <= lo:
            continue
        cat = ev.data.get("category") or UNCATEGORIZED
        span = hi - lo
        totals[cat] = totals.get(cat, 0.0) + span
        total += span
    ordered = dict(sorted(totals.items(), key=lambda kv: (-kv[1], kv[0])))
    return {"day": day_str, "total_s": total, "by_category": ordered}


# --------------------------------------------------------------------------- #
# intersect — clip one stream to the spans of another
# --------------------------------------------------------------------------- #

def intersect(a, b) -> list[Event]:
    """The parts of `a` covered by `b`, carrying `a`'s data.

    Each event of `a` is clipped against every event of `b`; each
    positive overlap becomes one output piece. A zero-duration point
    event of `a` survives iff its instant lies inside some `b` span
    (inclusive). `b` is taken literally — if `b`'s own events overlap
    each other, the covered span can appear twice; canonicalize `b`
    with flood()/merge_adjacent() first when that matters.
    """
    spans = _sorted(b)
    pieces: list[Event] = []
    for ev in a:
        for other in spans:
            lo = max(ev.ts, other.ts)
            hi = min(ev.end, other.end)
            if hi > lo:
                pieces.append(Event(lo, hi - lo, dict(ev.data)))
            elif ev.duration_s == 0 and other.ts <= ev.ts <= other.end:
                pieces.append(ev._copy())
                break  # one covering span is enough for a point
    return _sorted(pieces)
