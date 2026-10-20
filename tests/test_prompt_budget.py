"""Regression tests for the prompt-budget cliff (brain.PROMPT_SOFT_CAP).

The bug: the fixed system-prompt sections alone measured ~3,994 of the
4,000-token TOKEN_BUDGET, so one longer tool description pushed EVERY
turn into the working-memory honest-stop (and starved history to ~zero
on turns that did complete). The fix: Brain._system_prompt assembles in
priority order and compacts the most expendable sections until the
prompt fits PROMPT_SOFT_CAP *by construction*, recording every shrink.

Covers: byte-identical normal case, fat-roster fit + turn completion,
descriptions capped-not-dropped, persona/protocol immunity, teaching
cut only at lesson boundaries, learned/capabilities line discipline,
the compaction event/record firing exactly when shrinking happens, and
the pathological fallback (honest-stop preserved, never a fake fit).
"""

from jarvis.brain import (
    Brain,
    PROMPT_SOFT_CAP,
    TOKEN_BUDGET,
    ToolDef,
    _MODEL_PROTOCOL,
    _cap_at_word,
    _estimate_tokens,
    _truncate_at_lines,
)
from jarvis.gate import GateDecision, Verdict


# --------------------------------------------------------------------------- #
# Fakes (same pattern as tests/test_brain.py — real sibling interfaces)
# --------------------------------------------------------------------------- #
class FakeGate:
    def __init__(self):
        self.checks = []

    def check(self, tool_name, args, turn_allowances):
        self.checks.append((tool_name, dict(args), list(turn_allowances)))
        return GateDecision(verdict=Verdict.ALLOW, reason="test")

    @staticmethod
    def wrap_output(output, source, trust="untrusted"):
        return f'<tool_output source="{source}" trust="{trust}">{output}</tool_output>'


class FakeSessionStore:
    def __init__(self):
        self.events = []
        self._n = 0

    def emit(self, session_id, type, payload, actor, trust="user",
             causal_parent=None, trace_id=None):
        self._n += 1
        ev_id = f"ev{self._n}"
        self.events.append({"event_id": ev_id, "session_id": session_id,
                            "type": type, "payload": payload,
                            "causal_parent": causal_parent, "actor": actor,
                            "trust": trust})
        return ev_id

    def get_events(self, session_id, limit=1000):
        return [e for e in self.events if e["session_id"] == session_id][-limit:]

    def of_type(self, event_type):
        return [e for e in self.events if e["type"] == event_type]


class FakeRule:
    def __init__(self, text):
        self.text = text


class FakeRules:
    def __init__(self, rules=None):
        self._rules = rules if rules is not None else {
            "P2-1": 'Persona: calm British butler. Address Owais as "sir".',
            "P2-2": "Craftsman principle: verify before claiming.",
        }

    def find(self, rule_id):
        text = self._rules.get(rule_id)
        return FakeRule(text) if text is not None else None


class ScriptedLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []
        self.calls = 0

    def __call__(self, messages):
        self.calls += 1
        self.prompts.append(messages)
        if not self.replies:
            return "I have nothing further, sir."
        return self.replies.pop(0)


PERSONA = ('Persona: calm British butler. Address Owais as "sir".'
           "\n\nCraftsman principle: verify before claiming.")


def _fat_tools(n=30, desc_len=300):
    tools = []
    for i in range(n):
        desc = (f"Tool number {i} performs a very specific operation "
                f"for the owner and ").ljust(desc_len, "x")[:desc_len]
        tools.append(ToolDef(name=f"fat_tool_{i}", description=desc,
                             parameters={"required": ["path"]},
                             fn=lambda args: "ok"))
    return tools


def _fat_self_knowledge(lessons=10):
    self_part = "SELF: I am JARVIS. " + ("I serve Owais. " * 40)
    blocks = ["# TEACHING.md — Lessons from Ovi for JARVIS\n\n"
              "Study these well.\n"]
    for i in range(1, lessons + 1):
        blocks.append(f"## Lesson {i}: Title {i}\n"
                      + (f"Body of lesson {i}, study it well. " * 24)
                      + f"\nENDOFLESSON{i}\n")
    return (self_part + "\n\n--- LESSONS FROM YOUR TEACHER ---\n"
            + "\n".join(blocks))


def _fat_brain(llm, store=None, **kw):
    kw.setdefault("tools", _fat_tools())
    kw.setdefault("self_knowledge", _fat_self_knowledge())
    kw.setdefault("capabilities_provider",
                  lambda: "\n".join(
                      f"capline-{i:03d} " + ("capability " * 8).rstrip()
                      for i in range(60)))
    return Brain(gate=FakeGate(), session_store=store or FakeSessionStore(),
                 rules=FakeRules(), llm_call=llm, **kw)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
class TestHelpers:
    def test_cap_at_word_noop_when_fitting(self):
        assert _cap_at_word("short text", 140) == "short text"

    def test_cap_at_word_cuts_at_boundary(self):
        text = " ".join(["word"] * 100)  # 499 chars
        out = _cap_at_word(text, 140)
        assert len(out) <= 141
        assert out.endswith("…")
        assert not out[:-1].endswith("wor")  # not sliced mid-word

    def test_truncate_at_lines_noop_when_fitting(self):
        text = "line one\nline two"
        assert _truncate_at_lines(text, 1000, "M") == text

    def test_truncate_at_lines_keeps_whole_lines(self):
        text = "\n".join(f"line-{i} " + "y" * 40 for i in range(20))
        out = _truncate_at_lines(text, 300, "MARK")
        body, _, marker = out.rpartition("\n")
        assert marker == "MARK"
        for line in body.split("\n"):
            assert line in text.split("\n")  # whole lines only


# --------------------------------------------------------------------------- #
# The normal case: byte-identical, no compaction, no event
# --------------------------------------------------------------------------- #
class TestNormalCaseUntouched:
    def test_byte_identical_prompt(self):
        tools = [ToolDef(name="get_time", description="Current time.",
                         parameters={"required": ["zone"]},
                         fn=lambda args: "12:00")]
        brain = Brain(gate=FakeGate(), session_store=FakeSessionStore(),
                      rules=FakeRules(), llm_call=ScriptedLLM([]),
                      tools=tools, self_knowledge="Some self knowledge.")
        expected_lines = [PERSONA, "", _MODEL_PROTOCOL, "",
                          "Some self knowledge.", "Available tools:",
                          "- get_time: Current time. (required: ['zone'])"]
        assert brain._system_prompt() == "\n".join(expected_lines)
        assert brain._last_compaction is None

    def test_no_event_when_nothing_shrank(self):
        store = FakeSessionStore()
        brain = Brain(gate=FakeGate(), session_store=store,
                      rules=FakeRules(), llm_call=ScriptedLLM([]),
                      tools=[ToolDef(name="now", description="Time.",
                                     parameters={}, fn=lambda a: "12:00")])
        brain._system_prompt("s1")
        assert store.of_type("brain.prompt_compacted") == []
        assert brain._last_compaction is None


# --------------------------------------------------------------------------- #
# The fat case: fits by construction, turn completes, shrinking is logged
# --------------------------------------------------------------------------- #
class TestFatRoster:
    def test_fat_prompt_fits_soft_cap(self):
        brain = _fat_brain(ScriptedLLM([]))
        prompt = brain._system_prompt("s1")
        assert _estimate_tokens(prompt) <= PROMPT_SOFT_CAP
        assert brain._last_compaction is not None
        rec = brain._last_compaction
        assert rec["before_tokens"] > PROMPT_SOFT_CAP
        assert rec["after_tokens"] <= PROMPT_SOFT_CAP
        assert rec["soft_cap"] == PROMPT_SOFT_CAP
        assert "tool_descriptions_capped" in rec["strategies"]

    def test_fat_turn_completes_no_honest_stop(self):
        llm = ScriptedLLM(["The museum opens at nine, sir."])
        brain = _fat_brain(llm)
        res = brain.respond("s1", "when does the museum open?")
        assert res.status == "answered"
        assert res.text == "The museum opens at nine, sir."
        # The prompt the model actually received fits the cap too.
        sent_system = llm.prompts[0][0]["content"]
        assert _estimate_tokens(sent_system) <= PROMPT_SOFT_CAP

    def test_compaction_event_fires_when_shrinking_happens(self):
        store = FakeSessionStore()
        brain = _fat_brain(ScriptedLLM([]), store=store)
        brain._system_prompt("s1")
        events = store.of_type("brain.prompt_compacted")
        assert len(events) == 1
        payload = events[0]["payload"]
        assert payload["strategies"] == brain._last_compaction["strategies"]
        assert payload["before_tokens"] > payload["after_tokens"]

    def test_all_tools_still_listed_descriptions_bounded(self):
        brain = _fat_brain(ScriptedLLM([]))
        prompt = brain._system_prompt("s1")
        tool_lines = [ln for ln in prompt.split("\n")
                      if ln.startswith("- fat_tool_")]
        assert len(tool_lines) == 30  # capped, never dropped
        for ln in tool_lines:
            desc = ln.split(": ", 1)[1].rsplit(" (required:", 1)[0]
            assert len(desc) <= 141

    def test_persona_and_protocol_survive_compaction(self):
        brain = _fat_brain(ScriptedLLM([]))
        prompt = brain._system_prompt("s1")
        assert prompt.startswith(PERSONA)
        assert _MODEL_PROTOCOL in prompt

    def test_teaching_cut_only_at_lesson_boundaries(self):
        brain = _fat_brain(ScriptedLLM([]))
        prompt = brain._system_prompt("s1")
        assert "## Lesson 1" in prompt
        assert "teaching_shortened" in brain._last_compaction["strategies"]
        # A lesson is present whole or absent whole — never sliced.
        for i in range(1, 11):
            if f"## Lesson {i}" in prompt:
                assert f"ENDOFLESSON{i}" in prompt
        # The SELF part is never cut.
        assert "SELF: I am JARVIS." in prompt
        assert "[shortened to fit working memory]" in prompt

    def test_capabilities_cut_at_line_boundaries(self):
        brain = _fat_brain(ScriptedLLM([]))
        prompt = brain._system_prompt("s1")
        assert "capabilities_shortened" in brain._last_compaction["strategies"]
        caps_lines = [ln for ln in prompt.split("\n")
                      if ln.startswith("capline-")]
        assert 0 < len(caps_lines) < 60
        for ln in caps_lines:  # whole lines only
            assert ln.startswith("capline-") and ln.endswith("capability")


# --------------------------------------------------------------------------- #
# Learned context discipline
# --------------------------------------------------------------------------- #
class TestLearnedCompaction:
    def test_fat_learned_context_is_capped(self):
        store = FakeSessionStore()
        brain = Brain(gate=FakeGate(), session_store=store,
                      rules=FakeRules(), llm_call=ScriptedLLM([]),
                      tools=[ToolDef(name="now", description="Time.",
                                     parameters={}, fn=lambda a: "12:00")])
        brain._learned_context = "\n".join(
            ["## LEARNED FROM CORRECTIONS (follow these patterns):"]
            + [f"- prefers tea in the morning, noted on day {i}"
               for i in range(300)])
        prompt = brain._system_prompt("s1")
        assert _estimate_tokens(prompt) <= PROMPT_SOFT_CAP
        assert "learned_shortened" in brain._last_compaction["strategies"]
        kept = [ln for ln in prompt.split("\n")
                if ln.startswith("- prefers tea")]
        assert 0 < len(kept) < 300


# --------------------------------------------------------------------------- #
# The pathological case: the honest-stop fallback is preserved
# --------------------------------------------------------------------------- #
class TestPathologicalFallback:
    def test_giant_persona_still_honest_stops(self):
        rules = FakeRules(rules={"P2-1": "P" * 20000, "P2-2": "x"})
        llm = ScriptedLLM(["an answer that must never be sent"])
        brain = Brain(gate=FakeGate(), session_store=FakeSessionStore(),
                      rules=rules, llm_call=llm,
                      tools=[ToolDef(name="now", description="Time.",
                                     parameters={}, fn=lambda a: "12:00")])
        prompt = brain._system_prompt("s1")
        # Nothing shrinkable: we never pretend it fits.
        assert _estimate_tokens(prompt) > PROMPT_SOFT_CAP
        rec = brain._last_compaction
        assert rec is not None and rec["after_tokens"] > PROMPT_SOFT_CAP
        res = brain.respond("s1", "hello?")
        assert res.status == "stopped"
        assert "working memory" in res.text
        assert llm.calls == 0  # the over-budget prompt was never sent

    def test_budget_constants(self):
        assert PROMPT_SOFT_CAP == TOKEN_BUDGET - 700
        assert PROMPT_SOFT_CAP > 0
