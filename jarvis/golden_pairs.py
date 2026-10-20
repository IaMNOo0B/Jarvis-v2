"""Correction-to-pair pipeline: turn Owais's corrections into golden examples.

Stolen from DPO/RLHF: when the user corrects JARVIS, save the (bad, good)
pair. Good pairs get injected into future prompts. The assistant compounds
its learning from every correction — like preference training, without the
training run.

Flow:
  1. Owais says "no, do X instead" after a JARVIS answer.
  2. detect_correction() spots the pattern.
  3. save_pair() stores (context, bad_response, good_response).
  4. relevant_pairs() retrieves matching pairs for the live prompt.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# Phrases that signal "you got it wrong, here's the right way".
_CORRECTION_PATTERNS = [
    r"\bno[,.]?\s+(.+?)\s+instead\b",
    r"\bnahi[,.]?\s+(.+)",
    r"\bwrong\b",
    r"\bgalat\b",
    r"\bnot like that\b",
    r"\baisa nahi\b",
    r"\bi said\b",
    r"\bmaine kaha\b",
    r"\bdo it like this\b",
]


@dataclass
class GoldenPair:
    """One learned correction: what was wrong, what's right."""
    context: str          # the user's original request
    bad_response: str     # what JARVIS said (wrong)
    good_response: str    # what Owais wanted (right)
    timestamp: float = field(default_factory=time.time)
    used_count: int = 0


def detect_correction(user_text: str) -> Optional[str]:
    """If the message looks like a correction, return the corrected intent.

    Returns None for ordinary messages.
    """
    text = user_text.strip()
    for pat in _CORRECTION_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            # Return the corrected direction (group 1 if present, else full).
            try:
                return (m.group(1) or text).strip()
            except IndexError:
                return text
    return None


class PairStore:
    """JSONL store of golden pairs. Atomic appends, simple keyword retrieval."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, pair: GoldenPair) -> None:
        line = json.dumps(asdict(pair), ensure_ascii=False)
        tmp = self._path.with_suffix(".tmp")
        existing = ""
        if self._path.exists():
            existing = self._path.read_text(encoding="utf-8")
        tmp.write_text(existing + line + "\n", encoding="utf-8")
        tmp.replace(self._path)

    def all(self) -> List[GoldenPair]:
        if not self._path.exists():
            return []
        pairs = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                pairs.append(GoldenPair(**{k: d[k] for k in
                                           ("context", "bad_response",
                                            "good_response")
                                           if k in d}))
            except Exception:
                continue
        return pairs

    def relevant(self, user_text: str, limit: int = 3) -> List[GoldenPair]:
        """Keyword-overlap retrieval. Simple, deterministic, good enough."""
        words = set(re.findall(r"\w+", user_text.lower()))
        scored = []
        for p in self.all():
            pwords = set(re.findall(r"\w+", (p.context + " " +
                                             p.good_response).lower()))
            overlap = len(words & pwords)
            if overlap:
                scored.append((overlap, p))
        scored.sort(key=lambda x: -x[0])
        return [p for _, p in scored[:limit]]

    def format_for_prompt(self, pairs: List[GoldenPair]) -> str:
        """Render pairs as few-shot examples for the system prompt."""
        if not pairs:
            return ""
        lines = ["## LEARNED FROM CORRECTIONS (follow these patterns):"]
        for p in pairs:
            lines.append(f"- When asked '{p.context}': do '{p.good_response}' "
                         f"(not '{p.bad_response[:60]}...')")
        return "\n".join(lines)
