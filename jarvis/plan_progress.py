"""JARVIS v2 — plan progress, measured from checkboxes, never from claims.

Pattern ported (ideas only) from ethanplusai/jarvis builds.py::parse_plan:
progress comes from an artifact the worker must physically edit — the plan
file — not from the worker's self-report. One canonical parser, so the
voice surface and the UI surface can never disagree about "how far along".

The sacred rule: a plan with ZERO steps is NEVER done. Claiming a build
finished because a file had nothing under its headings is exactly the class
of false completion this module exists to prevent.

Pure functions, stdlib only (re, dataclasses). No I/O except
parse_plan_file / progress_line, which read the file they are given.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# GitHub-style checkbox:  - [ ] todo   /   - [x] done   (also * and + bullets)
_CHECKBOX = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s+(.+?)\s*$")


@dataclass
class PlanProgress:
    """Measured progress of one plan file."""
    done: int = 0
    total: int = 0
    next_open: str | None = None   # text of the first unticked step

    @property
    def complete(self) -> bool:
        """True only when there ARE steps and every one is ticked.

        total == 0 -> False, always. No steps is not success; it is
        the absence of a plan.
        """
        return self.total > 0 and self.done == self.total

    def as_dict(self) -> dict:
        return {"done": self.done, "total": self.total,
                "next_open": self.next_open, "complete": self.complete}


def parse_plan(text: str) -> PlanProgress:
    """Parse markdown checkbox lines out of plan text.

    Lines that are not checkboxes (headings, prose, blank lines) are
    ignored. [x] and [X] count as done; [ ] counts as open. The first
    open item becomes next_open.
    """
    done = 0
    total = 0
    next_open: str | None = None
    for line in (text or "").splitlines():
        m = _CHECKBOX.match(line)
        if m is None:
            continue
        total += 1
        if m.group(1) in ("x", "X"):
            done += 1
        elif next_open is None:
            next_open = m.group(2).strip()
    return PlanProgress(done=done, total=total, next_open=next_open)


def parse_plan_file(path: str) -> PlanProgress:
    """parse_plan over a file's contents. Missing file raises OSError —
    honest absence, never a fabricated zero-progress that looks 'fine'."""
    with open(path, "r", encoding="utf-8") as fh:
        return parse_plan(fh.read())


def progress_of(text: str) -> dict:
    """Thin dict wrapper — one parser, many surfaces."""
    return parse_plan(text).as_dict()


def progress_line(path: str) -> str:
    """One speakable line: '3 of 7 done — next: <item>'.

    - no steps yet  -> '0 of 0 done — the plan has no steps yet'
    - all ticked    -> '7 of 7 done — plan complete'
    - otherwise     -> '3 of 7 done — next: <first open item>'
    """
    p = parse_plan_file(path)
    if p.total == 0:
        return "0 of 0 done — the plan has no steps yet"
    if p.complete:
        return f"{p.done} of {p.total} done — plan complete"
    return f"{p.done} of {p.total} done — next: {p.next_open}"
