"""Tests for jarvis/self_critique.py — constitutional self-critique."""

import pytest

from jarvis.self_critique import SelfCritique, parse_critique


def _llm_no_violation(messages):
    return "VIOLATIONS: none\nREVISED: NO CHANGE NEEDED"


def _llm_violation(messages):
    return ("VIOLATIONS: P2-3 asked 'which part' for 'everything'\n"
            "REVISED: Here is the complete overview you asked for.")


def _llm_broken(messages):
    raise RuntimeError("model exploded")


class TestParseCritique:
    def test_no_violation(self):
        r = parse_critique("VIOLATIONS: none\nREVISED: NO CHANGE NEEDED")
        assert r.revised is False
        assert r.violations == []

    def test_violation_with_revision(self):
        r = parse_critique(_llm_violation([]))
        assert r.revised is True
        assert len(r.violations) == 1
        assert "complete overview" in r.final_text

    def test_garbage_input_fail_open(self):
        r = parse_critique("blah blah no structure")
        assert r.revised is False


class TestSelfCritique:
    def test_clean_draft_passes_through(self):
        sc = SelfCritique(_llm_no_violation, rules_text="R1: be nice")
        r = sc.review("Hello!", "hi")
        assert r.revised is False
        assert r.final_text == "Hello!"

    def test_violation_gets_revised(self):
        sc = SelfCritique(_llm_violation, rules_text="R1: be nice")
        r = sc.review("Which part?", "tell me everything")
        assert r.revised is True
        assert "complete overview" in r.final_text

    def test_llm_failure_returns_original(self):
        sc = SelfCritique(_llm_broken, rules_text="R1")
        r = sc.review("Original draft", "hi")
        assert r.revised is False
        assert r.final_text == "Original draft"

    def test_disabled_returns_original(self):
        sc = SelfCritique(_llm_violation, enabled=False)
        r = sc.review("Draft", "hi")
        assert r.revised is False
        assert r.final_text == "Draft"

    def test_empty_draft(self):
        sc = SelfCritique(_llm_violation)
        r = sc.review("   ", "hi")
        assert r.revised is False
