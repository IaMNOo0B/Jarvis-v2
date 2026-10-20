"""jarvis.translit — deterministic Hinglish canonicalization layer.

Team 17's verdict (megascan/team17-indic.md §5, §6): *normalization is a
pipeline stage, not an afterthought* — transliterate -> canonicalize
spelling -> THEN intent matching / memory. Every serious Hinglish system
has this layer; v2 had none. The owner's spelling variants (``krdo`` /
``kardo`` / ``kar do``) fragmented intent matching and memory keys.

This module is the DETERMINISTIC, stdlib-only first stage:

  canonicalize(text) -> one canonical form

  1. Devanagari runs are transliterated to roman with a fixed char table
     (below). Roman-Hindi convention, tuned to the grammar tables in
     skills/*/phrases.txt: long vowels fold to short (``क्या`` -> ``kya``,
     matching the hand-written grammar line ``samay kya hai``), inherent
     final -a drops (``समय`` -> ``samay``).
  2. Roman spelling variants collapse via a curated table — common
     Hinglish verbs, pronouns and question words, drawn from TEACHING.md,
     the shipped phrase grammars, and the team17 report.
  3. A few two-word phrase variants collapse to the single canonical
     token the grammars use (``dikha do`` -> ``dikhao``).

FUTURE UPGRADE (documented, deliberately NOT built here): the learned
transliterator is AI4Bharat **IndicXlit** (~11M params, MIT, Aksharantar
26M word pairs, roman<->Devanagari both directions). It is a torch dep,
so it stays OUT of the stdlib core; when it lands it slots in BEHIND
this module's ``canonicalize`` signature — callers will not change.
Until then this table is the whole story, and its limits are honesty
rules, not bugs:

  - The variant table is CONSERVATIVE. A token is rewritten only when it
    is not an ordinary English word (``me`` is NOT rewritten to ``mein`` —
    the English grammar lines must keep matching). One documented
    exception: ``kia`` -> ``kya`` (owners type it constantly for क्या;
    the lowercase English collision is a car brand, vanishingly rare in
    a command line).
  - Transliteration folds distinctions the script keeps (ट/त both -> t,
    long/short vowels merge). It is a canonicalizer for intent matching,
    NOT a scholarly transliterator — collisions like काम/कम (both ->
    ``kam``) are accepted and known.
  - canonicalize() is IDEMPOTENT and never invents words: unknown text
    passes through (lightly normalized) untouched.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

__all__ = ["canonicalize", "transliterate_devanagari", "ROMAN_VARIANTS"]


# --------------------------------------------------------------------------- #
# Devanagari -> roman table (canonical roman, grammar-table style)
# --------------------------------------------------------------------------- #
_VOWELS = {  # independent vowels
    "अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
}
_MATRAS = {  # dependent vowel signs (replace the inherent -a)
    "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॅ": "e", "ॉ": "o",
}
_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
}
_DIGITS = {chr(0x966 + i): str(i) for i in range(10)}  # ०-९
_HALANT = "्"
_NUKTA = "़"
_ANUSVARA = "ं"      # -> n
_CHANDRABINDU = "ँ"  # -> n
_VISARGA = "ः"       # -> h


def transliterate_devanagari(word: str) -> str:
    """Transliterate ONE word (may mix scripts) Devanagari -> roman.

    Latin/digit characters pass through untouched. A word with no
    Devanagari is returned unchanged.
    """
    if not any("ऀ" <= ch <= "ॿ" for ch in word):
        return word
    # Syllables: (roman, vowel_is_inherent). Latin chars are opaque
    # single units that break the syllable chain.
    syllables: List[Tuple[str, bool]] = []
    i, n = 0, len(word)
    while i < n:
        ch = word[i]
        if ch in _CONSONANTS:
            roman = _CONSONANTS[ch]
            i += 1
            if i < n and word[i] == _NUKTA:
                i += 1  # nukta: base consonant stands (क़ -> k)
            vowel = "a"
            inherent = True
            if i < n and word[i] == _HALANT:
                vowel, inherent = "", False
                i += 1
            elif i < n and word[i] in _MATRAS:
                vowel, inherent = _MATRAS[word[i]], False
                i += 1
            tail = ""
            if i < n and word[i] in (_ANUSVARA, _CHANDRABINDU):
                tail = "n"
                i += 1
            elif i < n and word[i] == _VISARGA:
                tail = "h"
                i += 1
            syllables.append((roman + vowel + tail, inherent))
        elif ch in _VOWELS:
            roman = _VOWELS[ch]
            i += 1
            tail = ""
            if i < n and word[i] in (_ANUSVARA, _CHANDRABINDU):
                tail = "n"
                i += 1
            elif i < n and word[i] == _VISARGA:
                tail = "h"
                i += 1
            syllables.append((roman + tail, False))
        elif ch in _DIGITS:
            syllables.append((_DIGITS[ch], False))
            i += 1
        else:
            syllables.append((ch, False))
            i += 1
    # Word-final rule: a trailing bare consonant's inherent -a drops
    # (कर -> kar, समय -> samay) — unless it is the word's only syllable.
    if len(syllables) >= 2 and syllables[-1][1]:
        roman, _ = syllables[-1]
        syllables[-1] = (roman[:-1], False)
    return "".join(r for r, _ in syllables)


# --------------------------------------------------------------------------- #
# Roman spelling-variant table: variant token -> canonical form.
# Canonical forms match the shipped grammar tables (phrases.txt).
# --------------------------------------------------------------------------- #
ROMAN_VARIANTS: Dict[str, str] = {
    # kar do / karna family (team17: the krdo/kardo problem)
    "krdo": "kar do", "kardo": "kar do", "kerdo": "kar do",
    "krna": "karna", "kerna": "karna",
    # chahiye
    "chaahiye": "chahiye", "chaahie": "chahiye", "chahie": "chahiye",
    "chaiye": "chahiye",
    # pronouns (oblique forms owners actually type)
    "muje": "mujhe", "mujhey": "mujhe",
    "tumhey": "tumhe",
    "meray": "mere",
    # negation
    "nhi": "nahi", "nahin": "nahi", "nahee": "nahi",
    # question word (documented exception: lowercase 'kia' — see header)
    "kia": "kya", "kyaa": "kya",
    # time / immediacy
    "abi": "abhi",
    # imperatives -> the canonical tokens the grammars carry
    "btao": "batao",
    "kholo": "khol",
    "lagado": "lagao", "dikhaado": "dikhao", "dikhado": "dikhao",
    "sunado": "sunao",
    # fillers / emphasis spellings
    "yar": "yaar", "bhee": "bhi",
}

# Two-token phrase variants -> canonical tokens (matched longest-first
# on the token stream, before single-token variants).
_PHRASE_VARIANTS: Dict[Tuple[str, ...], Tuple[str, ...]] = {
    ("dikha", "do"): ("dikhao",),
    ("bata", "do"): ("batao",),
    ("suna", "do"): ("sunao",),
    ("laga", "do"): ("lagao",),
    ("khol", "do"): ("khol",),
    ("band", "kar", "do"): ("band", "kar"),
    ("mujh", "ko"): ("mujhe",),
}

_PUNCT = re.compile(r"[।,.!?;:\"'“”‘’()\[\]{}<>…]+")


def _apply_phrase_variants(tokens: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    max_len = max(len(k) for k in _PHRASE_VARIANTS)
    while i < len(tokens):
        hit = None
        for size in range(min(max_len, len(tokens) - i), 1, -1):
            key = tuple(tokens[i:i + size])
            if key in _PHRASE_VARIANTS:
                hit = (size, _PHRASE_VARIANTS[key])
                break
        if hit:
            out.extend(hit[1])
            i += hit[0]
        else:
            out.append(tokens[i])
            i += 1
    return out


def canonicalize(text: str) -> str:
    """Return the canonical form of `text` for intent matching / keys.

    Lowercases, drops punctuation, collapses whitespace (so it composes
    with intent_router.normalize in either order), transliterates
    Devanagari words to roman, then collapses spelling variants.
    Idempotent: canonicalize(canonicalize(x)) == canonicalize(x).
    """
    t = _PUNCT.sub(" ", (text or "").strip().lower())
    words = [transliterate_devanagari(w) for w in t.split()]
    words = _apply_phrase_variants(words)
    out: List[str] = []
    for w in words:
        canon = ROMAN_VARIANTS.get(w)
        if canon is None:
            out.append(w)
        else:
            out.extend(canon.split())
    return " ".join(out)
