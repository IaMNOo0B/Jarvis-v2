"""Recall Gate — deterministic, zero-LLM memory-enrichment skip (isair steal).

Question it answers before every turn: does long-term memory need to be
consulted at all? If the recent conversation (the "hot window") already
contains a fresh answer covering the query's content words, enrichment is
wasted tokens — skip it.

Rule (deterministic, fail-open):
  - content words = query tokens minus stopwords, len >= 3
  - coverage = fraction of content words present in the hot window text
  - SKIP when coverage >= 0.5 AND the window holds a recent assistant/tool
    message (something that could actually BE the fresh answer)
  - any doubt (empty query, no window, no content words) -> ENRICH
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

COVERAGE_THRESHOLD = 0.5

_STOPWORDS = frozenset({
    # English function words
    "the", "a", "an", "is", "are", "was", "were", "what", "when", "where",
    "who", "whom", "which", "how", "why", "do", "does", "did", "can",
    "could", "would", "should", "will", "shall", "may", "might", "my",
    "your", "his", "her", "its", "our", "their", "me", "you", "him",
    "them", "us", "it", "this", "that", "these", "those", "of", "in",
    "on", "at", "to", "for", "with", "by", "from", "about", "and", "or",
    "but", "if", "then", "so", "as", "be", "been", "am",
    # Hinglish function words (roman)
    "hai", "hain", "tha", "thi", "kya", "kyun", "kab", "kahan", "kaun",
    "ka", "ki", "ke", "ko", "me", "mein", "ne", "se", "aur", "bhi",
    "mera", "meri", "mujhe", "tum", "aap", "yeh", "woh", "batao",
})

_WORD_RE = re.compile(r"[a-z0-9']+")


def content_words(text: str) -> List[str]:
    """Query content words: lowercased tokens, no stopwords, len >= 3."""
    out: List[str] = []
    for tok in _WORD_RE.findall((text or "").lower()):
        if len(tok) >= 3 and tok not in _STOPWORDS and tok not in out:
            out.append(tok)
    return out


def window_text(messages: Iterable[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for m in messages or []:
        content = m.get("content")
        if isinstance(content, str):
            parts.append(content)
    return " ".join(parts).lower()


def should_enrich(query: str, hot_window: Iterable[Dict[str, Any]]) -> bool:
    """True = consult long-term memory. False = hot window already covers it.

    Fail-open by construction: anything unclear returns True (enrich).
    """
    words = content_words(query)
    if not words:
        return True
    window = list(hot_window or [])
    # The window must hold a potential fresh answer: an assistant or tool
    # message. A window of only user text covers nothing.
    if not any(m.get("role") in ("assistant", "tool") for m in window):
        return True
    text = window_text(window)
    if not text:
        return True
    covered = sum(1 for w in words if w in text)
    coverage = covered / len(words)
    return coverage < COVERAGE_THRESHOLD
