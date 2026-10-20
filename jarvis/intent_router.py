"""Deterministic intent tier — grammar first, LLM only on a miss.

Studied from the field (megascan team10/team2, ideas only):
- Rhasspy/Hassil: one human-written sentence grammar maps text ->
  {intent, slots} deterministically — confidence 1.0 or no-match,
  zero hallucination by construction.
- OVOS confidence-tiered pipeline: deterministic matchers first,
  fuzzy intent next, the LLM only on a miss, clarifying fallback last.
- Open.Jarvis local-intent-first: ~80% of real commands are boring
  (time, reminders, open app) and should cost ZERO LLM calls.

This module is tier 0/1 of that ladder for JARVIS v2:

    exact grammar hit (confidence 1.0)
      -> fuzzy keyword match (confidence <= 0.8, flagged)
        -> None  (the caller's turn: the LLM)

Grammar syntax (phrases.txt, one rule per line) — deliberately tiny:

    [IntentName] pattern tokens -> tool_name

    pattern tokens:
      literal words              time kya hai
      (a | b | c)                alternation group
      [optional words]           optional group
      {slot}                     capture one or more words into args[slot]
      {slot:int}                 same, coerced to int (digits only)

    Blank lines and lines starting with # are ignored. A slot name may
    appear once per pattern. Patterns are matched ANCHORED (the whole
    normalized utterance must match), after stripping an optional
    leading "jarvis" / "hey jarvis" address and trailing punctuation.

Matching is over NORMALIZED text: lowercased, punctuation removed,
whitespace collapsed. Normalization never alters Devanagari script,
so Hinglish lines in either script work.

FUZZY TIER: when no exact rule matches, each rule's literal keyword
set (every literal word in the pattern, alternations included) is
scored against the query words:

    coverage = |query_words ∩ keywords| / |keywords|
    shape    = difflib ratio(query, pattern literal string)

A rule is a fuzzy candidate when coverage >= FUZZY_MIN_COVERAGE
(0.6) — every keyword present-ish is too strict for natural speech,
so the best candidate also needs shape >= FUZZY_MIN_SHAPE (0.45).
Confidence = min(0.8, 0.5 + 0.3 * coverage); the Match is flagged
fuzzy=True and callers MUST treat its args as provisional: slot
values are extracted only if the exact regex happens to match the
normalized query after all; otherwise args is empty and the wiring
layer decides (ask, or let the LLM fill them).

Stdlib only (re, difflib, dataclasses, pathlib).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

FUZZY_MIN_COVERAGE = 0.6
FUZZY_MIN_SHAPE = 0.45
FUZZY_CONFIDENCE_CAP = 0.8

_PUNCT = re.compile(r"[।,.!?;:\"'“”‘’()\[\]{}<>]+")
_ADDRESSES = ("hey jarvis", "hello jarvis", "jarvis", "oye jarvis")


def normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace. Script-safe."""
    t = (text or "").strip().lower()
    t = _PUNCT.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def strip_address(text: str) -> str:
    """Drop a leading wake-address ('jarvis, ...' / 'hey jarvis ...')."""
    t = normalize(text)
    for addr in _ADDRESSES:
        if t == addr:
            return ""
        if t.startswith(addr + " "):
            return t[len(addr):].strip()
    return t


@dataclass
class Match:
    skill: str
    tool: str
    args: Dict[str, object] = field(default_factory=dict)
    confidence: float = 1.0
    fuzzy: bool = False
    intent: str = ""
    pattern: str = ""


_SLOT_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::(int))?\}")


@dataclass
class _Rule:
    skill: str
    intent: str
    tool: str
    source: str                       # the raw pattern text
    regex: re.Pattern
    slots: List[Tuple[str, bool]]     # (name, is_int)
    keywords: frozenset               # literal words (fuzzy scoring)


def _compile_pattern(pattern: str) -> Tuple[re.Pattern, List[Tuple[str, bool]], frozenset]:
    """Compile one grammar pattern into an anchored regex.

    The pattern is scanned into SEGMENTS (literal / alternation /
    optional / slot). Segments join with ``\\s+``; an optional segment
    absorbs its following separator, so ``A [B] C`` accepts both
    "A B C" and "A C".
    """
    slots: List[Tuple[str, bool]] = []
    keywords: List[str] = []
    segments: List[Tuple[bool, str]] = []  # (is_optional, regex_fragment)
    i, n = 0, len(pattern)
    while i < n:
        ch = pattern[i]
        if ch.isspace():
            i += 1
        elif ch == "(":
            j = pattern.index(")", i)
            alts = [a.strip() for a in pattern[i + 1:j].split("|")]
            for a in alts:
                keywords.extend(a.split())
            segments.append((False, "(?:" + "|".join(
                re.escape(a).replace(r"\ ", r"\s+") for a in alts) + ")"))
            i = j + 1
        elif ch == "[":
            j = pattern.index("]", i)
            inner = pattern[i + 1:j].strip()
            keywords.extend(inner.split())
            segments.append((True, re.escape(inner).replace(r"\ ", r"\s+")))
            i = j + 1
        elif ch == "{":
            j = pattern.index("}", i)
            m = _SLOT_RE.fullmatch(pattern[i:j + 1])
            if not m:
                raise ValueError(f"bad slot in pattern: {pattern[i:j + 1]!r}")
            name, typ = m.group(1), m.group(2)
            slots.append((name, typ == "int"))
            segments.append((False, r"(?P<%s>.+?)" % name))
            i = j + 1
        else:
            j = i
            while j < n and not pattern[j].isspace() and pattern[j] not in "([{":
                j += 1
            word = pattern[i:j]
            keywords.append(word)
            segments.append((False, re.escape(word)))
            i = j
    parts: List[str] = []
    for idx, (is_opt, frag) in enumerate(segments):
        last = idx == len(segments) - 1
        if is_opt:
            # Optional segment absorbs its FOLLOWING separator, so a
            # missing optional never leaves a dangling gap.
            parts.append(f"(?:{frag})?" if last else f"(?:{frag}\\s+)?")
        else:
            parts.append(frag)
            if not last:
                parts.append(r"\s+")
    return re.compile("^" + "".join(parts) + "$"), slots, frozenset(keywords)


_RULE_LINE = re.compile(
    r"^\[(?P<intent>[^\]]+)\]\s+(?P<pattern>.+?)\s*->\s*(?P<tool>[A-Za-z0-9_.]+)\s*$")


class IntentRouter:
    """Ordered exact->fuzzy router over phrases.txt grammar tables.

    ``normalize_hook`` (optional): a callable applied to the normalized
    query before matching — the seam for jarvis.translit.canonicalize,
    which collapses Hinglish spelling variants (krdo/kardo -> kar do)
    and transliterates Devanagari to the roman the grammars are written
    in. Grammar tables are authored in canonical form, so the hook runs
    on the QUERY only. Default None = behaviour exactly as before; the
    router never imports the transliteration layer itself.
    """

    def __init__(self,
                 normalize_hook: Optional[Callable[[str], str]] = None
                 ) -> None:
        self._rules: List[_Rule] = []
        self._normalize_hook = normalize_hook

    # -- loading ---------------------------------------------------------
    def load_phrases(self, skill: str, text: str) -> int:
        """Parse grammar text for one skill. Returns rules added."""
        added = 0
        for lineno, raw in enumerate((text or "").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = _RULE_LINE.match(line)
            if not m:
                raise ValueError(
                    f"{skill} phrases line {lineno}: not a rule: {raw!r}")
            regex, slots, keywords = _compile_pattern(m.group("pattern"))
            self._rules.append(_Rule(
                skill=skill, intent=m.group("intent"), tool=m.group("tool"),
                source=m.group("pattern"), regex=regex, slots=slots,
                keywords=keywords))
            added += 1
        return added

    def load_skill_dir(self, skill_dir: str | Path) -> int:
        """Load <skill_dir>/phrases.txt if present (0 when absent)."""
        p = Path(skill_dir) / "phrases.txt"
        if not p.exists():
            return 0
        return self.load_phrases(Path(skill_dir).name,
                                 p.read_text(encoding="utf-8"))

    def load_skills_root(self, skills_root: str | Path) -> int:
        """Load phrases.txt from every skill dir under a root."""
        total = 0
        for child in sorted(Path(skills_root).iterdir()):
            if child.is_dir():
                total += self.load_skill_dir(child)
        return total

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    # -- routing ---------------------------------------------------------
    def route(self, text: str) -> Optional[Match]:
        """exact (1.0) -> fuzzy (<=0.8, flagged) -> None."""
        query = strip_address(text)
        if query and self._normalize_hook is not None:
            query = self._normalize_hook(query)
        if not query:
            return None
        exact = self._route_exact(query)
        if exact is not None:
            return exact
        return self._route_fuzzy(query)

    def _extract_args(self, rule: _Rule, match: re.Match) -> Optional[Dict[str, object]]:
        args: Dict[str, object] = {}
        for name, is_int in rule.slots:
            raw = (match.group(name) or "").strip()
            if is_int:
                if not raw.isdigit():
                    return None  # int slot captured non-digits: not a match
                args[name] = int(raw)
            else:
                args[name] = raw
        return args

    def _route_exact(self, query: str) -> Optional[Match]:
        for rule in self._rules:
            m = rule.regex.match(query)
            if not m:
                continue
            args = self._extract_args(rule, m)
            if args is None:
                continue
            return Match(skill=rule.skill, tool=rule.tool, args=args,
                         confidence=1.0, fuzzy=False, intent=rule.intent,
                         pattern=rule.source)
        return None

    def _route_fuzzy(self, query: str) -> Optional[Match]:
        qwords = set(query.split())
        best: Optional[Tuple[float, float, _Rule]] = None
        for rule in self._rules:
            if not rule.keywords:
                continue
            coverage = len(qwords & rule.keywords) / len(rule.keywords)
            if coverage < FUZZY_MIN_COVERAGE:
                continue
            literal = " ".join(sorted(rule.keywords))
            shape = difflib.SequenceMatcher(None, query, literal).ratio()
            if shape < FUZZY_MIN_SHAPE:
                continue
            score = (coverage, shape)
            if best is None or score > (best[0], best[1]):
                best = (coverage, shape, rule)
        if best is None:
            return None
        coverage, _shape, rule = best
        conf = min(FUZZY_CONFIDENCE_CAP, 0.5 + 0.3 * coverage)
        return Match(skill=rule.skill, tool=rule.tool, args={},
                     confidence=conf, fuzzy=True, intent=rule.intent,
                     pattern=rule.source)
