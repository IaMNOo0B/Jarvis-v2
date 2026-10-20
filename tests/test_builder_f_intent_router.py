"""Tests for jarvis/intent_router.py — the deterministic intent tier.

Exact grammar hits must be confidence 1.0 and hallucination-free;
fuzzy hits are capped at 0.8 and flagged; misses return None (LLM).
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jarvis.intent_router import IntentRouter, normalize, strip_address


def _full_router() -> IntentRouter:
    r = IntentRouter()
    r.load_skills_root(ROOT / "skills")
    r.load_phrases("system",
                   (ROOT / "jarvis" / "system_phrases.txt").read_text(
                       encoding="utf-8"))
    return r


@pytest.fixture(scope="module")
def router():
    return _full_router()


class TestNormalize:
    def test_lowercase_and_punct(self):
        assert normalize("Time Kya Hai?!") == "time kya hai"

    def test_devanagari_preserved(self):
        assert "समय" in normalize("समय क्या है?")

    def test_strip_address(self):
        assert strip_address("Jarvis, time kya hai") == "time kya hai"
        assert strip_address("hey jarvis screenshot lo") == "screenshot lo"
        assert strip_address("time kya hai") == "time kya hai"


class TestExactClock:
    @pytest.mark.parametrize("text", [
        "time kya hai", "abhi time kya hai", "what time is it",
        "समय क्या है", "TIME KYA HAI?", "jarvis time kya hai",
        "tell me the time",
    ])
    def test_now(self, router, text):
        m = router.route(text)
        assert m is not None and m.tool == "now" and m.skill == "clock"
        assert m.confidence == 1.0 and m.fuzzy is False


class TestExactReminders:
    def test_hinglish_set(self, router):
        m = router.route("10 minute me paani peene ka reminder lagao")
        assert m.tool == "reminder_set"
        assert m.args == {"in_minutes": 10, "text": "paani peene"}

    def test_english_set(self, router):
        m = router.route("remind me in 5 minutes to call mom")
        assert m.tool == "reminder_set"
        assert m.args == {"in_minutes": 5, "text": "call mom"}

    def test_int_slot_rejects_words(self, router):
        m = router.route("das minute me chai ka reminder lagao")
        assert m is None or m.args.get("in_minutes") != "das"

    def test_list(self, router):
        m = router.route("mere reminders dikhao")
        assert m.tool == "reminder_list" and m.confidence == 1.0

    def test_cancel(self, router):
        m = router.route("ab12cd34 wala reminder cancel karo")
        assert m.tool == "reminder_cancel"
        assert m.args == {"id": "ab12cd34"}


class TestExactSystem:
    def test_screen(self, router):
        m = router.route("screen pe kya hai")
        assert m.skill == "system" and m.tool == "observe_screen"

    def test_screenshot(self, router):
        m = router.route("hey jarvis screenshot lo")
        assert m.tool == "take_screenshot" and m.confidence == 1.0

    def test_launch_hinglish(self, router):
        m = router.route("chrome khol do")
        assert m.tool == "launch_app" and m.args == {"app": "chrome"}

    def test_launch_english(self, router):
        m = router.route("open notepad")
        assert m.tool == "launch_app" and m.args == {"app": "notepad"}

    def test_band_kar(self, router):
        m = router.route("band kar")
        assert m.tool == "close_thing" and m.confidence == 1.0


class TestGrammarFeatures:
    def test_alternation_and_optional(self):
        r = IntentRouter()
        r.load_phrases("t", "[X] (open | start) [the] {app} -> go")
        for text, app in [("open chrome", "chrome"),
                          ("start the chrome", "chrome"),
                          ("open the chrome", "chrome")]:
            m = r.route(text)
            assert m is not None and m.args == {"app": app}, text

    def test_anchored_no_partial(self):
        r = IntentRouter()
        r.load_phrases("t", "[X] time -> now")
        assert r.route("time please batao na") is None or \
            r.route("time please batao na").fuzzy

    def test_bad_line_raises(self):
        r = IntentRouter()
        with pytest.raises(ValueError):
            r.load_phrases("t", "this is not a rule")


class TestFuzzyTier:
    def test_typo_still_routes_flagged(self, router):
        m = router.route("mere reminder dikhao")  # singular vs 'reminders'
        if m is not None:
            assert m.fuzzy is True and m.confidence <= 0.8

    def test_fuzzy_never_beats_exact_confidence(self, router):
        m = router.route("screenshot llo")  # garbled
        if m is not None and m.fuzzy:
            assert m.confidence <= 0.8

    def test_gibberish_is_none(self, router):
        assert router.route("zyxwv quantum banana photosynthesis") is None

    def test_fuzzy_args_empty(self, router):
        m = router.route("reminder lagao kuch")
        if m is not None and m.fuzzy:
            assert m.args == {}
