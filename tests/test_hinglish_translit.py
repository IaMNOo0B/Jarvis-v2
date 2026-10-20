"""Transliteration / normalization layer (jarvis.translit) + the
intent-router hook that consumes it.

The contract under test: the owner's spelling chaos (krdo / kardo /
Devanagari) collapses to the ONE canonical form the shipped grammar
tables are written in — and plain English passes through untouched, so
wiring the hook into the router can never break English commands.
"""

from pathlib import Path

import pytest

from jarvis.intent_router import IntentRouter
from jarvis.translit import canonicalize, transliterate_devanagari

SKILLS = Path(__file__).parent.parent / "skills"


# --------------------------------------------------------------------------- #
# Roman spelling variants
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("raw", ["krdo", "kardo", "kerdo", "kar do"])
def test_kar_do_family_collapses(raw):
    assert canonicalize(raw) == "kar do"


@pytest.mark.parametrize("raw,canon", [
    ("chaahiye", "chahiye"), ("chahie", "chahiye"), ("chaiye", "chahiye"),
    ("muje", "mujhe"), ("mujhey", "mujhe"), ("tumhey", "tumhe"),
    ("nhi", "nahi"), ("nahin", "nahi"),
    ("abi", "abhi"), ("btao", "batao"), ("kholo", "khol"),
    ("krna", "karna"),
])
def test_single_token_variants(raw, canon):
    assert canonicalize(raw) == canon


def test_phrase_variants_collapse():
    assert canonicalize("reminders dikha do") == "reminders dikhao"
    assert canonicalize("bata do na") == "batao na"
    assert canonicalize("reminder laga do") == "reminder lagao"
    assert canonicalize("mujh ko bulao") == "mujhe bulao"


def test_variants_inside_a_sentence():
    assert canonicalize("5 minute me reminder krdo") == \
        "5 minute me reminder kar do"
    assert canonicalize("muje ek chai chahiye") == \
        "mujhe ek chai chahiye"


# --------------------------------------------------------------------------- #
# Devanagari transliteration
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("dev,roman", [
    ("समय", "samay"), ("क्या", "kya"), ("नमस्ते", "namaste"),
    ("राम", "ram"), ("हिंदी", "hindi"), ("मैं", "main"),
    ("एक", "ek"), ("घंटा", "ghanta"), ("हैं", "hain"),
    ("५", "5"), ("१०", "10"),
])
def test_devanagari_words(dev, roman):
    assert transliterate_devanagari(dev) == roman
    assert canonicalize(dev) == roman


def test_devanagari_sentence_canonicalizes():
    assert canonicalize("समय क्या है") == "samay kya hai"
    assert canonicalize("मेरे reminders दिखाओ") == "mere reminders dikhao"


def test_mixed_script_word_by_word():
    # Latin words pass through; the Devanagari imperative canonicalizes
    # all the way (transliterate -> variant table).
    assert canonicalize("chrome खोलो") == "chrome khol"
    assert transliterate_devanagari("chrome") == "chrome"


# --------------------------------------------------------------------------- #
# Safety properties: English untouched, idempotent
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("english", [
    "remind me in 5 minutes to call mom",
    "what is the time",
    "show my reminders",
    "cancel reminder 3",
    "open the pod bay doors",
])
def test_english_is_untouched(english):
    assert canonicalize(english) == english


_SAMPLES = [
    "krdo", "समय क्या है", "muje reminder laga do", "5 minute me krna hai",
    "remind me in 5 minutes", "मेरे reminders दिखाओ", "nhi chahiye",
]


def test_canonicalize_is_idempotent():
    for s in _SAMPLES:
        once = canonicalize(s)
        assert canonicalize(once) == once


def test_canonicalize_empty_and_noise():
    assert canonicalize("") == ""
    assert canonicalize("   ") == ""
    assert canonicalize("Time, kya hai?!") == "time kya hai"


# --------------------------------------------------------------------------- #
# Router integration: the hook is what makes variants + Devanagari match
# --------------------------------------------------------------------------- #

def _router(with_hook: bool) -> IntentRouter:
    hook = canonicalize if with_hook else None
    router = IntentRouter(normalize_hook=hook)
    router.load_skills_root(SKILLS)
    return router


def test_router_without_hook_is_unchanged():
    m = _router(False).route("time kya hai")
    assert m is not None and m.tool == "now" and m.confidence == 1.0


def test_router_hook_matches_roman_variant():
    # Grammar slot expects the reminder text; 'krdo' inside it must
    # canonicalize so the extracted text is the canonical command too.
    m = _router(True).route("5 minute me maa ko call krdo ka reminder lagao")
    assert m is not None and not m.fuzzy
    assert m.tool == "reminder_set"
    assert m.args["in_minutes"] == 5
    assert m.args["text"] == "maa ko call kar do"


def test_router_hook_matches_devanagari_query():
    hooked = _router(True).route("मेरे reminders दिखाओ")
    assert hooked is not None and not hooked.fuzzy
    assert hooked.tool == "reminder_list"
    # Without the hook the same query can only fuzz (or miss): the exact
    # grammar lines are roman + one Devanagari clock line, not this one.
    plain = _router(False).route("मेरे reminders दिखाओ")
    assert plain is None or plain.fuzzy


def test_router_hook_keeps_english_exact():
    m = _router(True).route("remind me in 5 minutes to call mom")
    assert m is not None and not m.fuzzy
    assert m.tool == "reminder_set"
    assert m.args["text"] == "call mom"
