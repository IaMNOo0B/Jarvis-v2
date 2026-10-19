"""Tests for the ask-vs-act controller.

Covers: signal detection (§2.1), the unified pricing rule (§3.1),
narration (§5), and the 8-step decision procedure (§3.1).
"""

import pytest

from jarvis.ask_controller import (
    AskDecision,
    Decision,
    RequestAnalysis,
    detect_underspec_signals,
    decide,
    price_ask,
    should_ask,
    should_narrate,
    signal_count,
)


# -- Part 1: signal detection ---------------------------------------------- #

class TestSignals:
    def test_vague_noun(self):
        s = detect_underspec_signals("Book something nice for dinner")
        assert s["vague_noun"] and s["grade_adjective"]

    def test_unscoped_quantifier(self):
        s = detect_underspec_signals("Delete the old files")
        assert s["unscoped_quantifier"]

    def test_bare_deictic(self):
        s = detect_underspec_signals("Email him the report")
        assert s["bare_deictic"]

    def test_hinglish_deictic(self):
        s = detect_underspec_signals("Bhai ye file bhej de")
        assert s["bare_deictic"]

    def test_clean_request_has_no_signals(self):
        s = detect_underspec_signals("What is the weather in Mumbai today")
        assert signal_count(s) == 0

    def test_missing_argument(self):
        s = detect_underspec_signals("remind me")
        assert s["very_short"]


# -- Part 2: pricing rule --------------------------------------------------- #

class TestPricing:
    def test_high_uncertainty_high_stakes_asks(self):
        bd = price_ask(p_wrong=0.8, tier=3, n_asked=0)
        assert should_ask(bd, 0)  # G_c dominates on tier-3

    def test_tier3_always_asks_even_when_confident(self):
        # learn-asking-economics.md Scenario 2: confident-but-irreversible.
        # Pure VoI would say act (G_u ~ 0); G_c rescues the ask inside pricing.
        bd = price_ask(p_wrong=0.05, tier=3, n_asked=0)
        assert bd.g_c > 0 and should_ask(bd, 0)

    def test_low_stakes_confident_acts(self):
        bd = price_ask(p_wrong=0.1, tier=1, n_asked=0)
        assert not should_ask(bd, 0)

    def test_budget_guard_stops_third_question(self):
        bd = price_ask(p_wrong=0.9, tier=2, n_asked=3)
        assert not should_ask(bd, 3)  # net positive but budget exhausted

    def test_interruption_cost_grows(self):
        first = price_ask(p_wrong=0.5, tier=2, n_asked=0)
        third = price_ask(p_wrong=0.5, tier=2, n_asked=2)
        assert third.c_i > first.c_i

    def test_trust_erosion_superlinear(self):
        low = price_ask(p_wrong=0.5, tier=2, unnecessary_recent=1)
        high = price_ask(p_wrong=0.5, tier=2, unnecessary_recent=3)
        assert high.c_t > 3 * low.c_t

    def test_voice_costs_more_than_chat(self):
        v = price_ask(p_wrong=0.5, tier=2, modality="voice")
        c = price_ask(p_wrong=0.5, tier=2, modality="chat")
        assert v.c_l > c.c_l


# -- Part 3: narration ------------------------------------------------------- #

class TestNarration:
    def test_narrate_cheap_reversible(self):
        assert should_narrate(tier=1, reversible=True,
                              material_uncertainty=True)

    def test_never_narrate_instead_of_tier3_confirm(self):
        assert not should_narrate(tier=3, reversible=True,
                                  material_uncertainty=True)

    def test_no_narration_without_uncertainty(self):
        assert not should_narrate(tier=1, reversible=True,
                                  material_uncertainty=False)


# -- Part 4: the 8-step procedure -------------------------------------------- #

class TestDecide:
    def test_impossible_escalates(self):
        d = decide(RequestAnalysis(text="Predict tomorrow's stock prices",
                                   impossible=True,
                                   impossible_reason="unknowable future"))
        assert d.decision == Decision.ESCALATE

    def test_policy_blocked_escalates(self):
        d = decide(RequestAnalysis(text="Hack my neighbor's wifi",
                                   policy_blocked=True,
                                   policy_reason="unauthorized access"))
        assert d.decision == Decision.ESCALATE

    def test_self_service_acts(self):
        # U6b: never ask for what you can look up.
        d = decide(RequestAnalysis(text="What is the file size",
                                   retrievable_via_tools=True))
        assert d.decision == Decision.ACT

    def test_nobody_has_it_abstains(self):
        d = decide(RequestAnalysis(text="What did I dream last night",
                                   nobody_has_it=True))
        assert d.decision == Decision.ACT
        assert "abstention" in d.reason

    def test_convergent_safe_acts_with_narration(self):
        d = decide(RequestAnalysis(
            text="Play some music",
            interpretations=[("liked playlist", 1), ("top hits", 1)],
            tier=1, divergent=False, material_uncertainty=True))
        assert d.decision == Decision.ACT_NARRATE
        assert d.assumption is not None

    def test_divergent_irreversible_hard_gate(self):
        # Golden set #1: "Delete the old files".
        d = decide(RequestAnalysis(
            text="Delete the old files",
            interpretations=[("downloads older than 1yr", 3),
                             ("project backups", 3)],
            tier=3, divergent=True, p_wrong=0.6,
            missing_slots=["which files", "where"]))
        assert d.decision == Decision.ASK
        assert "HARD GATE" in d.reason
        assert d.question is not None

    def test_tier3_never_acts_on_assumption(self):
        d = decide(RequestAnalysis(
            text="Delete this file",
            interpretations=[("the file in context", 3)],
            tier=3, divergent=False, p_wrong=0.05))  # confident!
        assert d.decision == Decision.ASK  # G_c, not VoI

    def test_pricing_asks_on_high_voi(self):
        # Golden set #2: "Book something nice for dinner".
        d = decide(RequestAnalysis(
            text="Book something nice for dinner",
            tier=2, divergent=True, p_wrong=0.9,
            missing_slots=["cuisine", "budget", "area", "time"]))
        assert d.decision == Decision.ASK
        assert "cuisine" in (d.question or "")

    def test_budget_exhaustion_escalates(self):
        d = decide(RequestAnalysis(text="Book dinner", tier=2,
                                   p_wrong=0.9, n_asked=3))
        assert d.decision == Decision.ESCALATE
        assert "budget" in d.reason

    def test_golden_act_weather(self):
        # Golden set #13.
        d = decide(RequestAnalysis(text="What is the weather today",
                                   tier=1, p_wrong=0.0))
        assert d.decision in (Decision.ACT, Decision.ACT_NARRATE)

    def test_no_tool_capability_escalates_honestly(self):
        d = decide(RequestAnalysis(text="Turn off the lights",
                                   impossible=True,
                                   impossible_reason="no smart-home "
                                                     "integration connected"))
        assert d.decision == Decision.ESCALATE
