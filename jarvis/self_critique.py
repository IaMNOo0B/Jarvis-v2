"""Constitutional self-critique: JARVIS checks its own draft against its rules.

Stolen from Anthropic's Constitutional AI: the model critiques and revises
its own output against a written constitution (here: JARVIS-RULES.txt).

Flow: draft answer -> critique ("does this violate any rule?") -> revise.
One extra LLM call per turn. Only revises when a violation is found.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


CRITIQUE_PROMPT = """You are reviewing a draft answer from JARVIS, an AI assistant.

CONSTITUTION (his rules):
{rules}

DRAFT ANSWER:
{draft}

USER'S ORIGINAL MESSAGE:
{user_text}

Check the draft against the constitution. Look for:
1. Rule violations (especially P0 safety and P1 security rules)
2. Forbidden phrases or over-asking (asking when he should act)
3. Made-up facts presented as certain
4. Tone mismatch (too formal when user is casual)

Reply in this exact format:
VIOLATIONS: <none | list each violation with rule number>
REVISED: <the corrected answer, or "NO CHANGE NEEDED">
"""


@dataclass
class CritiqueResult:
    """Outcome of one self-critique pass."""
    revised: bool
    violations: List[str] = field(default_factory=list)
    final_text: str = ""


def parse_critique(raw: str) -> CritiqueResult:
    """Parse the model's critique output. Fail-open to original on parse error."""
    violations: List[str] = []
    revised_text = ""
    in_revised = False

    for line in raw.splitlines():
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("VIOLATIONS:"):
            rest = stripped[len("VIOLATIONS:"):].strip()
            if rest.lower() not in ("none", "no", "-", ""):
                violations.append(rest)
            in_revised = False
        elif upper.startswith("REVISED:"):
            rest = stripped[len("REVISED:"):].strip()
            if rest.upper() != "NO CHANGE NEEDED":
                revised_text = rest
            in_revised = True
        elif in_revised:
            revised_text += "\n" + line

    if revised_text.strip():
        return CritiqueResult(revised=True, violations=violations,
                              final_text=revised_text.strip())
    return CritiqueResult(revised=False, violations=violations, final_text="")


class SelfCritique:
    """One constitutional review pass over a draft answer."""

    def __init__(self, llm_call, rules_text: str = "",
                 enabled: bool = True) -> None:
        # llm_call(messages) -> str. Injected so tests don't need a real model.
        self._llm_call = llm_call
        self._rules = rules_text
        self.enabled = enabled

    def review(self, draft: str, user_text: str) -> CritiqueResult:
        """Critique a draft. Returns revised text or the original."""
        if not self.enabled or not draft.strip():
            return CritiqueResult(revised=False, final_text=draft)

        prompt = CRITIQUE_PROMPT.format(
            rules=self._rules or "(no constitution loaded)",
            draft=draft,
            user_text=user_text,
        )
        try:
            raw = self._llm_call([{"role": "user", "content": prompt}])
        except Exception:
            # Critique failure must never block the answer.
            return CritiqueResult(revised=False, final_text=draft)

        result = parse_critique(raw or "")
        if result.revised and result.final_text:
            return result
        return CritiqueResult(revised=False, violations=result.violations,
                              final_text=draft)
