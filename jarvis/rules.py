"""Central rules loader for JARVIS v2.

Single source of truth: JARVIS-RULES.txt. This module parses it into typed
``Rule`` objects. P0 (hard safety) integrity is enforced at load: a missing
or empty P0 rule refuses startup with ``RulesError``. No silent pass.

Rule format in the file: ``P0-1  [CONFIG] text...`` with indented
continuation lines. Meta-rules (``R-1`` ...) carry no kind tag and default
to CONFIG.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

__all__ = ["Rule", "Rules", "RulesError", "load_rules", "P0_REQUIRED"]

# Canonical hard-safety set. Every one of these must be present with
# non-empty text, or the loader refuses startup. Owais may ADD P0 rules;
# dropping one requires his explicit, live confirmation (handled by the
# caller via ``allow_missing``) — never silence.
P0_REQUIRED = tuple(f"P0-{i}" for i in range(1, 8))

_RULE_RE = re.compile(r"^(P[0-3]-\d+)\s+\[(CONFIG|STRUCTURAL)\]\s*(.*)$")
_R_RULE_RE = re.compile(r"^(R-\d+)\s+(.*)$")


class RulesError(Exception):
    """The rules file is unusable or fails P0 integrity. Startup must stop."""


@dataclass(frozen=True)
class Rule:
    """One parsed rule."""
    id: str        # e.g. "P0-3", "R-1"
    priority: str  # "P0".."P3", or "R" for meta-rules
    kind: str      # "CONFIG" or "STRUCTURAL"
    text: str

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        preview = self.text[:60] + ("..." if len(self.text) > 60 else "")
        return f"{self.id} [{self.kind}] {preview}"


def _parse(text: str) -> dict[str, Rule]:
    """Parse the whole rules file into {id: Rule}. Ignores prose/headers."""
    rules: dict[str, Rule] = {}
    cur_id: str | None = None
    cur_kind = "CONFIG"
    cur_lines: list[str] = []

    def flush() -> None:
        nonlocal cur_id
        if cur_id is None:
            return
        body = re.sub(r"\s+", " ", " ".join(cur_lines)).strip()
        priority = cur_id.split("-")[0]  # "P0".."P3", or "R"
        rules[cur_id] = Rule(id=cur_id, priority=priority,
                             kind=cur_kind, text=body)
        cur_id = None

    for raw in text.splitlines():
        if not raw.strip():
            flush()
            continue
        m = _RULE_RE.match(raw)
        if m:
            flush()
            cur_id, cur_kind = m.group(1), m.group(2)
            cur_lines = [m.group(3)]
            continue
        m = _R_RULE_RE.match(raw)
        if m:
            flush()
            cur_id, cur_kind = m.group(1), "CONFIG"
            cur_lines = [m.group(2)]
            continue
        if raw[0] in (" ", "\t") and cur_id is not None:
            cur_lines.append(raw)  # indented continuation line
        else:
            flush()  # headers, separators, prose: end any open rule
    flush()
    return rules


def _check_p0(rules: dict[str, Rule], allow_missing: frozenset[str]) -> None:
    """Enforce hard-safety integrity. Raises RulesError on any gap."""
    bad = [
        rid for rid in P0_REQUIRED
        if rid not in allow_missing
        and (rid not in rules or not rules[rid].text.strip())
    ]
    # Any *additional* P0 rule the owner added is held to the same bar.
    bad += [
        rid for rid, rule in rules.items()
        if rid.startswith("P0-") and rid not in P0_REQUIRED
        and rid not in allow_missing and not rule.text.strip()
    ]
    if bad:
        raise RulesError(
            "hard-safety rule missing: " + ", ".join(sorted(set(bad)))
            + " — refusing startup"
        )


class Rules:
    """Parsed, integrity-checked rule set with live reload."""

    def __init__(self, path: str, rules: dict[str, Rule],
                 allow_missing: frozenset[str] = frozenset()):
        self.path = os.path.abspath(path)
        self._rules = dict(rules)
        self._allow_missing = frozenset(allow_missing)

    def get(self, priority: str) -> list[Rule]:
        """All rules in a priority band: "P0".."P3" or "R"."""
        return [r for r in self._rules.values() if r.priority == priority]

    def find(self, rule_id: str) -> Rule | None:
        """One rule by id, or None."""
        return self._rules.get(rule_id)

    def ids(self) -> list[str]:
        return list(self._rules)

    def __len__(self) -> int:
        return len(self._rules)

    def __contains__(self, rule_id: str) -> bool:
        return rule_id in self._rules

    def reload(self) -> dict[str, list[str]]:
        """Re-read the file. Returns added/removed/changed rule ids.

        P0 integrity is re-checked: a weakened file cannot slip in
        quietly on reload either.
        """
        with open(self.path, "r", encoding="utf-8") as fh:
            new_rules = _parse(fh.read())
        _check_p0(new_rules, self._allow_missing)
        old = self._rules
        diff = {
            "added": sorted(i for i in new_rules if i not in old),
            "removed": sorted(i for i in old if i not in new_rules),
            "changed": sorted(
                i for i in new_rules
                if i in old and new_rules[i] != old[i]
            ),
        }
        self._rules = new_rules
        return diff


def load_rules(path: str,
               allow_missing: set[str] | frozenset[str] | None = None) -> Rules:
    """Load and integrity-check the rules file.

    Raises RulesError if the file is unreadable or any P0 hard-safety
    rule is missing/empty. ``allow_missing`` names P0 ids the owner has
    explicitly confirmed away (live confirmation UX lives in the caller);
    it must name exact ids — never a silent pass.
    """
    allowed = frozenset(allow_missing or ())
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise RulesError(f"cannot read rules file {path!r}: {exc}") from exc
    rules = _parse(text)
    if not rules:
        raise RulesError(f"no rules parsed from {path!r} — refusing startup")
    _check_p0(rules, allowed)
    return Rules(path, rules, allowed)
