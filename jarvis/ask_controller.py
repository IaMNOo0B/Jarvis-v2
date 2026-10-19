"""Ask-vs-act controller: when JARVIS should ask, act, narrate, or escalate.

Implements three PhD findings as deterministic code (no model calls —
the controller must be cheaper than the ask it prices):

1. learn-underspecification.md §3.1 — the 8-step Ask/Act/Escalate decision
   procedure (impossibility → self-service → nobody-has-it → enumerate →
   convergence → cost-asymmetric → escalate → budget).
2. learn-asking-economics.md §3.1 — the unified pricing rule:
   ASK iff G_u + G_a + G_c > C_i + C_t + C_l AND n_asked < 3.
3. learn-asking-economics.md §5 — narration as cheap asking.

All parameters are PROPOSED priors (unmeasured — see the learn files §7).
They err fail-safe: G_c is large on tier-3, C_t is super-linear.

Stdlib only. Python 3.11+.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Decision type
# ---------------------------------------------------------------------------

class Decision(Enum):
    ASK = "ask"            # ask one targeted question (highest VoI first)
    ACT = "act"            # act now on the best interpretation
    ACT_NARRATE = "act_narrate"  # act + narrate the uncertain assumption
    ESCALATE = "escalate"  # refuse / deliberate-confirm / honest-can't


@dataclass
class AskDecision:
    decision: Decision
    reason: str                    # why — for the session log
    question: Optional[str] = None  # the question to ask (ASK only)
    assumption: Optional[str] = None  # the narrated assumption (ACT_NARRATE)
    missing_slots: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Part 1 — underspecification signals (learn-underspecification.md §2.1)
#
# Structural, regex-based detection. The spec (CLAMBER finding) warns that
# LLM self-reported uncertainty is overconfident — so detection here is
# linguistic structure, never "the model feels unsure".
# ---------------------------------------------------------------------------

_VAGUE_NOUNS = re.compile(
    r"\b(something|stuff|things|it|that|this one|those)\b", re.I)
_UNSPEC_QUANT = re.compile(
    r"\b(all|every|everything|the old\b|some)\b", re.I)
_GRADE_ADJ = re.compile(
    r"\b(nice|good|best|fast|cheap|quick|better)\b", re.I)
_DEICTIC = re.compile(
    r"\b(him|her|them|that one|those ones|yeh|woh|ye|vo)\b", re.I)
_MISSING_ARG = re.compile(
    r"\b(book|send|email|remind|schedule|order|cancel|delete|play)\s*$", re.I)


def detect_underspec_signals(text: str) -> Dict[str, bool]:
    """Linguistic underspecification signals. Deterministic, no model."""
    t = text.strip()
    return {
        "vague_noun": bool(_VAGUE_NOUNS.search(t)),
        "unscoped_quantifier": bool(_UNSPEC_QUANT.search(t)),
        "grade_adjective": bool(_GRADE_ADJ.search(t)),
        "bare_deictic": bool(_DEICTIC.search(t)),
        "missing_argument": bool(_MISSING_ARG.search(t)),
        "very_short": len(t.split()) <= 2,
    }


def signal_count(signals: Dict[str, bool]) -> int:
    return sum(1 for v in signals.values() if v)


# ---------------------------------------------------------------------------
# Part 2 — the unified pricing rule (learn-asking-economics.md §3.1)
#
#   ASK iff G_u + G_a + G_c > C_i + C_t + C_l  AND  n_asked < 3
#
# Gain terms:
#   G_u = P(wrong interpretation) x C_wrong (classic VoI)
#   G_a = alignment value of communicating (small positive prior)
#   G_c = corrigibility/oversight value (LARGE on tier-3 by construction)
# Cost terms:
#   C_i = interruption (grows with n_asked — redundancy cost)
#   C_t = trust erosion (super-linear in recent unnecessary questions)
#   C_l = latency (modality-dependent)
# ---------------------------------------------------------------------------

# C_wrong by risk tier (proposed priors; tier-3 is hard-gated anyway).
_C_WRONG = {1: 1.0, 2: 10.0, 3: 1000.0}

# G_a prior: small positive — communication buys future correction speed.
_G_A_PRIOR = 0.5

# G_c: corrigibility value. Large on tier-3 (re-grounding mandate),
# ~0 elsewhere. This is what makes "divergent x irreversible -> ask"
# fall OUT of the pricing instead of being bolted on.
def _g_c(tier: int, divergent: bool) -> float:
    if tier >= 3:
        return 500.0
    if divergent and tier == 2:
        return 50.0
    return 0.0

# C_i: base annoyance x growth with questions already asked.
_C_I_BASE = 1.0
_C_I_GROWTH = 1.5  # each prior question makes the next 1.5x more annoying

# C_l by modality.
_C_L = {"voice": 2.0, "chat": 0.5, "background": 0.1}


@dataclass
class PriceBreakdown:
    g_u: float
    g_a: float
    g_c: float
    c_i: float
    c_t: float
    c_l: float

    @property
    def gain(self) -> float:
        return self.g_u + self.g_a + self.g_c

    @property
    def cost(self) -> float:
        return self.c_i + self.c_t + self.c_l

    @property
    def net(self) -> float:
        return self.gain - self.cost


def price_ask(
    p_wrong: float,
    tier: int,
    n_asked: int = 0,
    unnecessary_recent: int = 0,
    divergent: bool = False,
    modality: str = "chat",
) -> PriceBreakdown:
    """Price one candidate question. Pure arithmetic — no model call.

    p_wrong: probability the current best interpretation is wrong (0..1).
    tier: risk tier of the candidate action (1/2/3).
    n_asked: questions already asked on this task.
    unnecessary_recent: unnecessary questions asked recently (trust ledger).
    divergent: interpretations have divergent consequences.
    """
    p_wrong = max(0.0, min(1.0, p_wrong))
    tier = tier if tier in (1, 2, 3) else 1
    g_u = p_wrong * _C_WRONG[tier]
    g_a = _G_A_PRIOR
    g_c = _g_c(tier, divergent)
    c_i = _C_I_BASE * (_C_I_GROWTH ** max(0, n_asked))
    c_t = 0.5 * max(0, unnecessary_recent) ** 2  # super-linear
    c_l = _C_L.get(modality, 0.5)
    return PriceBreakdown(g_u=g_u, g_a=g_a, g_c=g_c,
                          c_i=c_i, c_t=c_t, c_l=c_l)


_ASK_BUDGET = 3  # sequence-level guard (learn-asking-economics.md §6)


def should_ask(breakdown: PriceBreakdown, n_asked: int) -> bool:
    """The unified rule: net gain positive AND budget not exhausted."""
    return breakdown.net > 0 and n_asked < _ASK_BUDGET


# ---------------------------------------------------------------------------
# Part 3 — narration as cheap asking (learn-asking-economics.md §5)
#
# NARRATE iff tier <= 2 AND (reversible OR high read-rate) AND material
# uncertainty worth exposing. Tier-3: NEVER narration-instead-of-confirmation.
# ---------------------------------------------------------------------------

def should_narrate(tier: int, reversible: bool, material_uncertainty: bool,
                   read_rate_high: bool = True) -> bool:
    if tier >= 3:
        return False  # narration is not consent — architectural mandate
    if not material_uncertainty:
        return False  # narrating the confident part is communicatively dead
    return reversible or read_rate_high


# ---------------------------------------------------------------------------
# Part 4 — the 8-step decision procedure (learn-underspecification.md §3.1)
# ---------------------------------------------------------------------------

@dataclass
class RequestAnalysis:
    """Everything the controller needs for one decision."""
    text: str
    # Step 1: impossibility / policy
    impossible: bool = False
    impossible_reason: str = ""
    policy_blocked: bool = False
    policy_reason: str = ""
    # Step 2/3: information source
    retrievable_via_tools: bool = False   # U6b: never ask, look it up
    nobody_has_it: bool = False           # U6c: honest abstention
    # Step 4: interpretations (description, risk_tier)
    interpretations: List[tuple] = field(default_factory=list)
    # Step 6: pricing inputs
    p_wrong: float = 0.5
    tier: int = 1
    divergent: bool = False
    missing_slots: List[str] = field(default_factory=list)
    # Step 8: budget state
    n_asked: int = 0
    unnecessary_recent: int = 0
    modality: str = "chat"
    # Narration inputs
    reversible: bool = True
    material_uncertainty: bool = False


def decide(req: RequestAnalysis) -> AskDecision:
    """The 8-step rule. Deterministic; the brain supplies the analysis,
    this function supplies the decision."""

    # Step 1 — IMPOSSIBILITY / POLICY: escalate, never clarify the impossible.
    if req.impossible:
        return AskDecision(Decision.ESCALATE,
                           f"impossible: {req.impossible_reason}")
    if req.policy_blocked:
        return AskDecision(Decision.ESCALATE,
                           f"policy-blocked: {req.policy_reason}")

    # Step 2 — SELF-SERVICE (U6b): the missing fact is retrievable.
    # Never ask for what you can look up.
    if req.retrievable_via_tools:
        return AskDecision(Decision.ACT,
                           "missing fact retrievable via tools — self-serve")

    # Step 3 — NOBODY-HAS-IT (U6c): honest abstention, not a question.
    if req.nobody_has_it:
        return AskDecision(Decision.ACT,
                           "information exists nowhere — honest abstention, "
                           "do not ask")

    # Step 5 — CONVERGENCE: all interpretations -> same safe reversible act.
    if req.interpretations:
        tiers = {t for _, t in req.interpretations}
        if len(req.interpretations) >= 1 and max(tiers) <= 1 and not req.divergent:
            assumption = req.interpretations[0][0]
            if req.material_uncertainty:
                return AskDecision(
                    Decision.ACT_NARRATE,
                    "interpretations converge on safe action — act, narrate "
                    "the uncertain part",
                    assumption=f"Assuming: {assumption}")
            return AskDecision(Decision.ACT,
                               "interpretations converge on safe action")

    # Step 6 — HARD GATES (override pricing; equivalently G_c >> C):
    # divergent x irreversible -> ASK, always. Tier-3 -> never act on assumption.
    if req.divergent and req.tier >= 3:
        q = _build_question(req)
        return AskDecision(Decision.ASK,
                           "HARD GATE: divergent interpretations x "
                           "irreversible action — ask, always",
                           question=q, missing_slots=req.missing_slots)
    if req.tier >= 3:
        q = _build_question(req)
        return AskDecision(Decision.ASK,
                           "HARD GATE: tier-3 never acts on assumption — "
                           "confirm with visible payload",
                           question=q, missing_slots=req.missing_slots)

    # Step 6 — PRICING: ask iff net gain positive and budget remains.
    bd = price_ask(req.p_wrong, req.tier, req.n_asked,
                   req.unnecessary_recent, req.divergent, req.modality)
    if should_ask(bd, req.n_asked):
        return AskDecision(
            Decision.ASK,
            f"pricing: net VoI {bd.net:.1f} > 0 "
            f"(G={bd.gain:.1f} C={bd.cost:.1f})",
            question=_build_question(req), missing_slots=req.missing_slots)

    # Step 7 — pricing says don't ask: act, narrating if cheap and useful.
    if should_narrate(req.tier, req.reversible, req.material_uncertainty):
        assumption = (req.interpretations[0][0]
                      if req.interpretations else "my best interpretation")
        return AskDecision(
            Decision.ACT_NARRATE,
            "pricing negative — act; narration is cheap and buys alignment",
            assumption=f"Assuming: {assumption}")

    # Step 8 — budget exhausted or nothing worth saying: best-effort act.
    if req.n_asked >= _ASK_BUDGET:
        return AskDecision(Decision.ESCALATE,
                           "ask budget exhausted — state the blocker, "
                           "propose closest achievable alternative")
    return AskDecision(Decision.ACT,
                       "pricing negative, no material uncertainty — "
                       "best-effort act")


def _build_question(req: RequestAnalysis) -> str:
    """One targeted question, highest-VoI slots first, batched."""
    if req.missing_slots:
        slots = ", ".join(req.missing_slots)
        return f"Which {slots}, sir? I need {slots} before I can proceed."
    signals = detect_underspec_signals(req.text)
    if signals["bare_deictic"]:
        return "Who or what do you mean, exactly, sir?"
    if signals["unscoped_quantifier"]:
        return "Which ones, exactly, sir — and where?"
    if signals["grade_adjective"]:
        return "What does that mean for you here, sir — can you give me an example?"
    return "Can you say a little more about what you want, sir?"
