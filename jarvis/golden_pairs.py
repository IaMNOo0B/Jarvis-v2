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

Mass & decay (Team 26 steal — OpenHer/astrbot pair weighting): a pair's
influence is a MASS, not a boolean. A correction that recurs (same
context signature) is a lesson JARVIS keeps failing, so its mass grows
(+0.5 per recurrence, capped); a pair nobody has needed for a long
time fades with a ~29-day half-life toward a floor of 1.0. Decay only
reorders influence — mass never reaches zero and a pair is never
deleted by decay. Pairs fed into the prompt are chosen relevance-first,
mass as the tie-break, and being used refreshes a pair's last_used.
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


# Mass model (OpenHer/astrbot pattern): influence is a weight in
# [MASS_FLOOR, MASS_CAP]. New pairs are born at the floor; only
# recurrence raises a pair above it, and only decay lowers it back —
# asymptotically, never below the floor, never to deletion.
MASS_FLOOR = 1.0        # every pair keeps at least this much voice
MASS_CAP = 5.0          # a chronic correction shouts, but only this loud
MASS_RECUR_BONUS = 0.5  # mass gained per recurrence of the same correction
MASS_HALF_LIFE_DAYS = 29.0  # excess mass halves every ~29 days of disuse


@dataclass
class GoldenPair:
    """One learned correction: what was wrong, what's right."""
    context: str          # the user's original request
    bad_response: str     # what JARVIS said (wrong)
    good_response: str    # what Owais wanted (right)
    timestamp: float = field(default_factory=time.time)
    used_count: int = 0
    mass: float = MASS_FLOOR   # influence weight (see constants above)
    last_used: float = field(default_factory=time.time)


def _signature(context: str, good_response: str) -> str:
    """Recurrence signature: the same request corrected the same way.

    Normalized (lowercase, word tokens, whitespace-collapsed) over BOTH
    the context and the correction: if Owais repeats a request but
    changes the correction, that is a new lesson, not a recurrence.
    """
    def norm(s: str) -> str:
        return " ".join(re.findall(r"\w+", s.lower()))
    return norm(context) + "\x1f" + norm(good_response)


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

    def _write_all(self, pairs: List[GoldenPair]) -> None:
        """Atomically rewrite the whole store (tmp + replace)."""
        tmp = self._path.with_suffix(".tmp")
        text = "".join(json.dumps(asdict(p), ensure_ascii=False) + "\n"
                       for p in pairs)
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self._path)

    def save(self, pair: GoldenPair) -> GoldenPair:
        """Store a correction — or feed an existing one.

        If a stored pair carries the same context signature (same
        request, same correction), this save is a RECURRENCE: JARVIS
        made the same mistake again, so the existing pair's mass grows
        by MASS_RECUR_BONUS (capped) and its last_used refreshes,
        instead of a duplicate line being appended. Returns the pair
        as stored.
        """
        pairs = self.all()
        sig = _signature(pair.context, pair.good_response)
        for existing in pairs:
            if _signature(existing.context, existing.good_response) == sig:
                existing.mass = min(MASS_CAP,
                                    existing.mass + MASS_RECUR_BONUS)
                existing.last_used = time.time()
                self._write_all(pairs)
                return existing
        line = json.dumps(asdict(pair), ensure_ascii=False)
        tmp = self._path.with_suffix(".tmp")
        existing_text = ""
        if self._path.exists():
            existing_text = self._path.read_text(encoding="utf-8")
        tmp.write_text(existing_text + line + "\n", encoding="utf-8")
        tmp.replace(self._path)
        return pair

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
                pair = GoldenPair(context=d["context"],
                                  bad_response=d["bad_response"],
                                  good_response=d["good_response"])
                # Optional fields ride along when present (older lines
                # predate timestamp/mass and simply take the defaults).
                if isinstance(d.get("timestamp"), (int, float)):
                    pair.timestamp = float(d["timestamp"])
                if isinstance(d.get("used_count"), int):
                    pair.used_count = d["used_count"]
                if isinstance(d.get("mass"), (int, float)):
                    pair.mass = max(MASS_FLOOR,
                                    min(MASS_CAP, float(d["mass"])))
                if isinstance(d.get("last_used"), (int, float)):
                    pair.last_used = float(d["last_used"])
                pairs.append(pair)
            except Exception:
                continue
        return pairs

    def relevant(self, user_text: str, limit: int = 3) -> List[GoldenPair]:
        """Keyword-overlap retrieval, mass as the tie-break.

        Relevance still decides WHO is eligible (an irrelevant pair,
        however massive, never displaces a relevant one); among equally
        relevant pairs the heavier — more often re-taught — lesson wins,
        then the most recently used. Returned pairs are stamped used
        (used_count + 1, last_used = now) and the stamps are persisted:
        being fed into a prompt is exactly the "use" decay measures.
        A store-write failure never breaks retrieval.
        """
        words = set(re.findall(r"\w+", user_text.lower()))
        pairs = self.all()
        scored = []
        for p in pairs:
            pwords = set(re.findall(r"\w+", (p.context + " " +
                                             p.good_response).lower()))
            overlap = len(words & pwords)
            if overlap:
                scored.append((overlap, p))
        scored.sort(key=lambda x: (-x[0], -x[1].mass, -x[1].last_used))
        chosen = [p for _, p in scored[:limit]]
        if chosen:
            now = time.time()
            for p in chosen:
                p.used_count += 1
                p.last_used = now
            try:
                self._write_all(pairs)
            except Exception:
                pass  # stamps are bookkeeping; retrieval is the job
        return chosen

    def decay_pairs(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Fade unused pairs' mass toward the floor (nightly pass).

        Each pair's excess mass (mass - MASS_FLOOR) decays with a
        MASS_HALF_LIFE_DAYS half-life measured from its own last_used:

            mass' = FLOOR + (mass - FLOOR) * 0.5 ** (days_unused / 29)

        After one half-life the excess has halved; it approaches the
        floor asymptotically and NEVER crosses it, and decay never
        deletes a pair — it only reorders influence. last_used is
        re-anchored to `now` for every pair, so consecutive runs
        compound correctly instead of re-charging the same idle span.
        Returns {"pairs": n, "decayed": k} — pairs whose mass moved.
        """
        now = time.time() if now is None else now
        pairs = self.all()
        decayed = 0
        for p in pairs:
            base = p.last_used or p.timestamp
            days = max(0.0, (now - base) / 86400.0)
            if days > 0 and p.mass > MASS_FLOOR:
                factor = 0.5 ** (days / MASS_HALF_LIFE_DAYS)
                new_mass = MASS_FLOOR + (p.mass - MASS_FLOOR) * factor
                new_mass = max(MASS_FLOOR, min(MASS_CAP, new_mass))
                if new_mass < p.mass - 1e-12:
                    decayed += 1
                p.mass = new_mass
            p.last_used = now
        if pairs:
            self._write_all(pairs)
        return {"pairs": len(pairs), "decayed": decayed}

    def format_for_prompt(self, pairs: List[GoldenPair]) -> str:
        """Render pairs as few-shot examples for the system prompt."""
        if not pairs:
            return ""
        lines = ["## LEARNED FROM CORRECTIONS (follow these patterns):"]
        for p in pairs:
            lines.append(f"- When asked '{p.context}': do '{p.good_response}' "
                         f"(not '{p.bad_response[:60]}...')")
        return "\n".join(lines)
