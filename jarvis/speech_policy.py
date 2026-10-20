"""Speech policy — what may leave the speakers, and in what chunks.

The brain's reply text is written text: it contains markdown, code fences,
URLs, and — occasionally — things that must never be read aloud (API keys,
Aadhaar/phone numbers). Reading raw reply text into TTS speaks all of it,
character by character, through the user's speakers (a REAL leak channel:
anyone in the room hears it, and the mic can hear it too).

This module is the deterministic policy layer between brain text and TTS:

    clean_for_tts(text) -> [chunk, chunk, ...]

Pipeline: strip markdown -> redact secrets -> split into speakable
clauses -> pack into chunks with ASYMMETRIC sizing: the first chunk is
short (~40 chars) so speech starts fast, later chunks are ~160.

WHY the redaction is a SUBSET of jarvis.dcl (read this before "fixing"):
dcl guards the network with recall-first heuristics — its seed-phrase
SHAPE rule redacts ANY 12 lowercase words in a row, and its semantic tier
flags words like "doctor". Perfect for egress (a false positive costs an
annoyance), destructive for speech (it would read "redacted secret" in
the middle of ordinary sentences). The speech path therefore reuses the
dcl's HIGH-PRECISION patterns only: the Tier A registry of exact secrets,
the Tier B credential shapes (sk-, ghp_, AKIA, private-key blocks,
labeled secrets, OTP labels), Luhn-validated card numbers, and the
precise PII shapes (Indian/international phone, Aadhaar). The patterns
themselves are imported from jarvis.dcl — one source of truth — never
copied (except a last-resort fallback if that import ever breaks).

Pure functions. Stdlib only. No state, no I/O beyond the DCL import
(jarvis.dcl imports stdlib only — importing it here creates no cycle).
"""

from __future__ import annotations

import re
from typing import List

__all__ = [
    "FIRST_CHUNK_CHARS", "CHUNK_CHARS",
    "register_secret",
    "strip_markdown", "redact_secrets", "split_clauses",
    "chunk_for_speech", "clean_for_tts",
]

FIRST_CHUNK_CHARS = 40    # fast start: the first sound comes quickly
CHUNK_CHARS = 160         # steady-state chunk size after the first

# --------------------------------------------------------------------------- #
# Secret redaction — high-precision subset of jarvis.dcl's patterns
# --------------------------------------------------------------------------- #

# Last-resort fallback key shapes, used ONLY if the jarvis.dcl import ever
# fails. The dcl patterns are the authority; these keep raw keys off the
# speakers even in a broken install.
_FALLBACK_SECRET_RX = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),          # OpenAI-style
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),       # GitHub tokens
    re.compile(r"\bnvapi-[A-Za-z0-9_\-]{20,}\b"),        # NVIDIA NIM
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                 # AWS access key
    re.compile(r"\bxai-[A-Za-z0-9]{20,}\b"),             # xAI
    re.compile(r"\bAIza[A-Za-z0-9_\-]{20,}\b"),          # Google API key
    re.compile(r"\bAQ\.[A-Za-z0-9_\-]{40,}\b"),          # Google AI Studio key (2025+)
]

# The only Tier C (PII) shapes precise enough for the speech path.
_SPEECH_PII_NAMES = {"phone-in", "phone-intl", "aadhaar-shape"}

_registry = None        # jarvis.dcl.SecretRegistry (Tier A exact matches)
_tier_b: list = []      # [(name, rx)] credential shapes -> SECRET
_tier_c_speech: list = []  # [(name, rx)] PII shapes -> SENSITIVE
_card = None            # (rx, luhn_fn) or None


def _load_dcl_patterns() -> None:
    global _registry, _tier_b, _tier_c_speech, _card
    try:
        import jarvis.dcl as dcl_mod

        _registry = dcl_mod.SecretRegistry()
        _tier_b = list(dcl_mod._TIER_B_PATTERNS)  # noqa: SLF001 (same repo)
        _tier_c_speech = [
            (name, rx) for name, rx, _cls in dcl_mod._TIER_C_PATTERNS  # noqa: SLF001
            if name in _SPEECH_PII_NAMES
        ]
        if hasattr(dcl_mod, "_CARD_RE") and hasattr(dcl_mod, "_luhn_ok"):
            _card = (dcl_mod._CARD_RE, dcl_mod._luhn_ok)  # noqa: SLF001
    except Exception:  # pragma: no cover - dcl is in-repo; belt and braces
        _tier_b = [(f"fallback-{i}", rx)
                   for i, rx in enumerate(_FALLBACK_SECRET_RX)]
        _tier_c_speech = []


_load_dcl_patterns()

_SECRET, _SENSITIVE = 2, 1
_SPOKEN_PLACEHOLDER = {_SECRET: "redacted secret",
                       _SENSITIVE: "redacted detail"}


def register_secret(name: str, value: str) -> None:
    """Register an exact user secret that must never be spoken aloud
    (delegates to the dcl Tier A registry — fingerprint match)."""
    if _registry is not None:
        _registry.register_secret(name, value)


def redact_secrets(text: str) -> str:
    """Replace secret/PII spans with SPOKEN placeholders.

    The user hears THAT something was redacted ("redacted secret") —
    never WHAT it was, and never the brackets of the network path's
    "[REDACTED:SECRET]" marker (brackets don't speak)."""
    if not text:
        return ""
    spans: list = []  # (start, end, rank)
    if _registry is not None:
        for f in _registry.find_matches(text):
            spans.append((f.start, f.end, _SECRET))
    for _name, rx in _tier_b:
        for m in rx.finditer(text):
            spans.append((m.start(), m.end(), _SECRET))
    if _card is not None:
        rx, luhn_ok = _card
        for m in rx.finditer(text):
            digits = re.sub(r"\D", "", m.group(0))
            if 13 <= len(digits) <= 19 and luhn_ok(digits):
                end = m.end()
                while end > m.start() and text[end - 1] in " -.":
                    end -= 1  # the rx eats trailing separators; unglue words
                spans.append((m.start(), end, _SECRET))
    for _name, rx in _tier_c_speech:
        for m in rx.finditer(text):
            spans.append((m.start(), m.end(), _SENSITIVE))
    if not spans:
        return text
    # Merge overlaps (highest rank wins), exactly like dcl.redact.
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    merged: list = []
    for start, end, rank in spans:
        if end <= start:
            continue
        if merged and start < merged[-1][1]:
            prev = merged[-1]
            prev[1] = max(prev[1], end)
            prev[2] = max(prev[2], rank)
        else:
            merged.append([start, end, rank])
    out: List[str] = []
    pos = 0
    for start, end, rank in merged:
        out.append(text[pos:start])
        out.append(_SPOKEN_PLACEHOLDER[rank])
        pos = end
    out.append(text[pos:])
    return "".join(out)


# --------------------------------------------------------------------------- #
# Markdown stripping (written text -> speakable text)
# --------------------------------------------------------------------------- #

_FENCE_RX = re.compile(r"```[^\n]*\n?.*?(?:```|\Z)", re.DOTALL)
_IMG_RX = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RX = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BARE_URL_RX = re.compile(r"https?://\S+|www\.\S+")
_HEADING_RX = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_QUOTE_RX = re.compile(r"^>\s?", re.MULTILINE)
_LIST_RX = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.MULTILINE)
_TABLE_SEP_RX = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", re.MULTILINE)
_HR_RX = re.compile(r"^\s*(?:-{3,}|_{3,}|\*{3,})\s*$", re.MULTILINE)
_BOLD_RX = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
_ITALIC_RX = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])"
                        r"|(?<!\w)_([^_\n]+)_(?!\w)")
_CODE_RX = re.compile(r"`([^`\n]+)`")
_HTML_RX = re.compile(r"<[^>]+>")


def strip_markdown(text: str) -> str:
    """Remove markdown so TTS never speaks syntax. Content survives:
    link text stays, code-fence CONTENT goes (code read aloud is noise —
    and often full of strings that should not be spoken); inline `code`
    keeps its words because short identifiers are speakable."""
    if not text:
        return ""
    s = _FENCE_RX.sub(" ", text)
    s = _IMG_RX.sub(r"\1", s)
    s = _LINK_RX.sub(r"\1", s)
    s = _BARE_URL_RX.sub("link", s)
    s = _TABLE_SEP_RX.sub(" ", s)
    s = s.replace("|", " ")
    s = _HR_RX.sub(" ", s)
    s = _HEADING_RX.sub("", s)
    s = _QUOTE_RX.sub("", s)
    s = _LIST_RX.sub("", s)
    s = _BOLD_RX.sub(lambda m: m.group(1) or m.group(2), s)
    s = _ITALIC_RX.sub(lambda m: m.group(1) or m.group(2), s)
    s = _CODE_RX.sub(r"\1", s)
    s = _HTML_RX.sub(" ", s)
    return s


# --------------------------------------------------------------------------- #
# Clause splitting + asymmetric chunk packing
# --------------------------------------------------------------------------- #

_CLAUSE_SPLIT_RX = re.compile(r"(?<=[.!?…])\s+|(?<=[,;:—–])\s+|\n+")


def split_clauses(text: str) -> List[str]:
    """Split speakable text into clauses on sentence ends and clause
    punctuation (, ; : — –), keeping the delimiter on its clause.
    Whitespace is normalised; empty clauses are dropped."""
    if not text or not text.strip():
        return []
    parts = _CLAUSE_SPLIT_RX.split(" ".join(text.split()))
    return [p.strip() for p in parts if p and p.strip()]


def _hard_split(clause: str, limit: int) -> List[str]:
    """Split one over-long clause at word boundaries (last resort:
    a single clause longer than the chunk budget)."""
    out: List[str] = []
    rest = clause.strip()
    while len(rest) > limit:
        cut = rest.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit  # one giant word: cut it, speech must go on
        out.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        out.append(rest)
    return out


def chunk_for_speech(text: str,
                     first_limit: int = FIRST_CHUNK_CHARS,
                     limit: int = CHUNK_CHARS) -> List[str]:
    """Pack clauses into chunks: the FIRST chunk targets `first_limit`
    chars (fast first sound), the rest target `limit`. Clauses are never
    reordered and words are never lost — joining the chunks with spaces
    reproduces the clause stream."""
    clauses = split_clauses(text)
    chunks: List[str] = []
    cur = ""
    budget = first_limit
    for clause in clauses:
        pieces = _hard_split(clause, limit) if len(clause) > limit else [clause]
        for piece in pieces:
            if not cur:
                cur = piece
            elif len(cur) + 1 + len(piece) <= budget:
                cur = cur + " " + piece
            else:
                chunks.append(cur)
                cur = piece
                budget = limit  # only the first chunk is small
    if cur:
        chunks.append(cur)
    return chunks


def clean_for_tts(text: str,
                  first_limit: int = FIRST_CHUNK_CHARS,
                  limit: int = CHUNK_CHARS) -> List[str]:
    """Full policy pipeline: markdown out, secrets redacted, clauses
    packed asymmetrically. Returns speakable chunks ([] for empty)."""
    if not text or not text.strip():
        return []
    s = strip_markdown(text)
    s = redact_secrets(s)
    s = " ".join(s.split())
    return chunk_for_speech(s, first_limit=first_limit, limit=limit)
