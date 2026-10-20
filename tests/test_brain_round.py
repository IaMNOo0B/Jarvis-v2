"""Tests for the brain round: four landed mechanisms wired into Brain.

1. DCL placeholder round-trip (_redact_messages substitutes through ONE
   per-turn Vault; respond restores the reply before storage/return).
2. LoopGuard in the ReAct loop (CYCLE/REPEAT halt, STAGNANT nudge once).
3. Nanobrowser identical-call discipline (1 salvage repeat, then local
   refusal; the guard still observes refused attempts).
4. Bookend (short persona reminder as the LAST message before each
   model call, charged to the turn's budget accounting).

Fakes implement the REAL sibling interfaces (same shapes as
tests/test_brain.py). No network, no model. Secrets in this file are
fake-shaped strings; assertions compare booleans/membership, never
print values.
"""

import pytest

from jarvis.brain import Brain, ToolDef
from jarvis.gate import GateDecision, Verdict


# --------------------------------------------------------------------------- #
# Fakes (implementing the real sibling interfaces)
# --------------------------------------------------------------------------- #
class FakeGate:
    """verdicts: tool_name -> Verdict. Default: ALLOW."""

    def __init__(self, verdicts=None, reasons=None):
        self.verdicts = verdicts or {}
        self.reasons = reasons or {}
        self.checks = []

    def check(self, tool_name, args, turn_allowances):
        self.checks.append((tool_name, dict(args), list(turn_allowances)))
        verdict = self.verdicts.get(tool_name, Verdict.ALLOW)
        approval_request = None
        if verdict == Verdict.REQUIRE_APPROVAL:
            approval_request = {"action": tool_name, "tier": 3,
                                "reason": self.reasons.get(tool_name, "")}
        return GateDecision(verdict=verdict,
                            reason=self.reasons.get(tool_name, "test"),
                            approval_request=approval_request)

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

    def of_type(self, event_type):
        return [e for e in self.events if e["type"] == event_type]

    def get_events(self, session_id, limit=100):
        return [e for e in self.events if e["session_id"] == session_id][-limit:]


class FakeRule:
    def __init__(self, text):
        self.text = text


class FakeRules:
    def __init__(self, rules=None):
        self._rules = rules or {
            "P2-1": 'Persona: calm British butler. Address Owais as "sir".',
            "P2-2": "Craftsman principle: verify before claiming.",
        }

    def find(self, rule_id):
        text = self._rules.get(rule_id)
        return FakeRule(text) if text is not None else None


class ScriptedLLM:
    """Returns scripted replies in order; records every prompt."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []
        self.calls = 0

    def __call__(self, messages):
        self.calls += 1
        self.prompts.append([dict(m) for m in messages])
        if not self.replies:
            return "I have nothing further, sir."
        return self.replies.pop(0)


def tool_reply(name, args=None):
    return {"tool_calls": [{"name": name, "args": args or {}}]}


def make_brain(llm, gate=None, store=None, rules=None, tools=None,
               off_machine=False, **kw):
    tools = tools if tools is not None else [
        ToolDef(name="get_time", description="Current time.", parameters={},
                fn=lambda args: "12:00"),
    ]
    return Brain(gate=gate or FakeGate(),
                 session_store=store or FakeSessionStore(),
                 rules=rules or FakeRules(), llm_call=llm,
                 tools=tools, llm_off_machine=off_machine, **kw)


FAKE_KEY = "sk-or-v1-" + "a1b2c3d4" * 6


def all_prompt_text(llm):
    return "\n".join(str(m.get("content") or "")
                     for prompt in llm.prompts for m in prompt)


# --------------------------------------------------------------------------- #
# 1. DCL placeholder round-trip
# --------------------------------------------------------------------------- #
def test_placeholder_roundtrip_through_brain_respond():
    """Key in user text -> provider saw <SECRET_1> -> stored brain.reply
    and the returned text contain the real key again."""
    store = FakeSessionStore()
    llm = ScriptedLLM([{"content": "Noted, sir — I will guard <SECRET_1>."}])
    brain = make_brain(llm, store=store, off_machine=True)

    result = brain.respond("s1", f"my key is {FAKE_KEY} — keep it safe")

    seen = all_prompt_text(llm)
    assert FAKE_KEY not in seen                 # provider never saw the key
    assert "<SECRET_1>" in seen                  # it saw the placeholder
    assert result.status == "answered"
    assert FAKE_KEY in result.text               # owner reads the real thing
    replies = store.of_type("brain.reply")
    assert len(replies) == 1
    assert FAKE_KEY in replies[0]["payload"]["text"]   # stored restored too
    assert brain._turn_vault is None             # vault dropped with the turn


def test_local_destination_never_substitutes():
    """llm_off_machine=False: no vault, no substitution, prompt raw."""
    llm = ScriptedLLM([{"content": "Noted, sir."}])
    brain = make_brain(llm, off_machine=False)
    result = brain.respond("s1", f"my key is {FAKE_KEY}")
    assert FAKE_KEY in all_prompt_text(llm)      # local model: unchanged path
    assert result.text == "Noted, sir."
    assert brain._turn_vault is None


def test_same_secret_same_placeholder_across_rounds():
    """One vault per turn: the key in round 1's user text and round 2's
    history wears the SAME placeholder both times."""
    calls = {"n": 0}

    def echo_key(args):
        calls["n"] += 1
        return "echo done"

    tools = [ToolDef(name="echo", description="Echo.", parameters={},
                     fn=echo_key)]
    llm = ScriptedLLM([
        tool_reply("echo"),
        {"content": "Done — <SECRET_1> stayed safe."},
    ])
    brain = make_brain(llm, tools=tools, off_machine=True)
    result = brain.respond("s1", f"please echo with key {FAKE_KEY}")

    assert calls["n"] == 1
    for prompt in llm.prompts:
        text = "\n".join(str(m.get("content") or "") for m in prompt)
        assert FAKE_KEY not in text
    round2 = "\n".join(str(m.get("content") or "") for m in llm.prompts[1])
    assert round2.count("<SECRET_1>") >= 1
    assert "<SECRET_2>" not in round2            # same secret, same placeholder
    assert FAKE_KEY in result.text


# --------------------------------------------------------------------------- #
# 3. Nanobrowser identical-call discipline
# --------------------------------------------------------------------------- #
def test_identical_call_salvage_then_local_refusal():
    """The same call four times in one batch: #1 runs, #2 (the salvage
    repeat) runs and — its result unchanged — carries the no-effect
    note; #3 and #4 are refused locally ('already tried, same result')
    WITHOUT executing. Refusals are not tool failures: the turn still
    answers."""
    counter = {}
    tools = [_counting_tool("fetch", "page-content", counter)]
    store = FakeSessionStore()
    llm = ScriptedLLM([
        {"tool_calls": [{"name": "fetch", "args": {"url": "x"}}] * 4},
        {"content": "Got the page, sir."},
    ])
    brain = make_brain(llm, store=store, tools=tools)
    result = brain.respond("s1", "fetch that page")

    assert counter == {"fetch": 2}                # only two executions
    tool_msgs = _tool_messages(result)
    assert len(tool_msgs) == 4
    assert "already ran this turn and returned the same result" \
        in tool_msgs[1]["content"]                 # no-effect note
    assert "already tried, same result" in tool_msgs[2]["content"]
    # The first refusal's guard observation is STAGNANT (the result
    # fingerprint is frozen), which halts the turn's tool use — so the
    # 4th proposal meets the loop-guard skip text, not a 2nd refusal.
    assert "not executed" in tool_msgs[3]["content"]
    assert len(store.of_type("brain.repeat_refused")) == 1
    events = store.of_type("brain.loop_guard")
    assert len(events) == 1
    assert events[0]["payload"]["action"] == "refused_repeat"
    assert result.status == "answered"             # refusal != failure


def test_guard_verdict_surfaces_through_refusals_and_halts():
    """Same call, CHANGING results: executions cap at 2, refusals keep
    feeding the guard (fingerprinted by the last known result — the
    frozen fingerprint means STAGNANT is the verdict that surfaces on
    this path, outranking REPEAT), and the non-OK verdict on a refused
    repeat halts tool use: the 5th proposal gets the skip text, not
    another refusal."""
    counter = {}

    def changing(args):
        counter["fetch"] = counter.get("fetch", 0) + 1
        return f"result-{counter['fetch']}"

    tools = [ToolDef(name="fetch", description="Fetch.", parameters={},
                     fn=changing)]
    store = FakeSessionStore()
    llm = ScriptedLLM([
        {"tool_calls": [{"name": "fetch", "args": {"url": "x"}}] * 5},
        {"content": "Enough fetching, sir."},
    ])
    brain = make_brain(llm, store=store, tools=tools)
    result = brain.respond("s1", "fetch it again and again")

    assert counter == {"fetch": 2}
    tool_msgs = _tool_messages(result)
    assert "already ran this turn" not in tool_msgs[1]["content"]
    assert "already tried, same result" in tool_msgs[2]["content"]
    assert "already tried, same result" in tool_msgs[3]["content"]
    assert "not executed" in tool_msgs[4]["content"]   # halted via guard
    events = store.of_type("brain.loop_guard")
    assert len(events) == 1
    assert events[0]["payload"]["verdict"] == "STAGNANT"
    assert events[0]["payload"]["action"] == "refused_repeat"
    assert len(store.of_type("brain.repeat_refused")) == 2
    assert result.status == "answered"


def test_distinct_args_are_not_identical_calls():
    """Same tool, different args: never refused, never noted."""
    counter = {}
    tools = [_counting_tool("fetch", "page-content", counter)]
    llm = ScriptedLLM([
        {"tool_calls": [{"name": "fetch", "args": {"url": u}}
                        for u in ("a", "b", "c", "d")]},
        {"content": "Four pages, sir."},
    ])
    brain = make_brain(llm, tools=tools)
    result = brain.respond("s1", "fetch all four")
    assert counter == {"fetch": 4}
    for m in _tool_messages(result):
        assert "already tried" not in m["content"]


def test_interleaved_repeats_are_not_refused():
    """A rotation (alpha, beta, gamma, alpha, beta, gamma): repeats
    that are NOT back-to-back are legitimate sequenced work — the
    identical-call refusal never fires (the guard's CYCLE verdict,
    not the refusal, owns ping-pong patterns)."""
    counter = {}
    tools = [_counting_tool("alpha", "alpha-result", counter),
             _counting_tool("beta", "beta-result", counter),
             _counting_tool("gamma", "gamma-result", counter)]
    llm = ScriptedLLM([
        {"tool_calls": [{"name": n, "args": {}}
                        for n in ("alpha", "beta", "gamma",
                                  "alpha", "beta", "gamma")]},
        {"content": "Rotation complete, sir."},
    ])
    brain = make_brain(llm, tools=tools)
    result = brain.respond("s1", "rotate through all three twice")
    assert counter == {"alpha": 2, "beta": 2, "gamma": 2}
    for m in _tool_messages(result):
        assert "already tried" not in m["content"]
    assert result.status == "answered"


# --------------------------------------------------------------------------- #
# 4. Bookend
# --------------------------------------------------------------------------- #
def test_bookend_is_last_message_every_call_and_stays_out_of_history():
    """Every prompt the model receives ENDS with the bookend (persona
    core line, system role); the stored history never contains it."""
    from jarvis.brain import _estimate_tokens

    counter = {}
    tools = [_counting_tool("alpha", "alpha-result", counter)]
    llm = ScriptedLLM([tool_reply("alpha"), {"content": "Done, sir."}])
    brain = make_brain(llm, tools=tools)
    result = brain.respond("s1", "use alpha please")

    assert result.status == "answered"
    assert len(llm.prompts) == 2
    for prompt in llm.prompts:
        last = prompt[-1]
        assert last["role"] == "system"
        assert last["content"].startswith("[Reminder")
        assert "calm British butler" in last["content"]   # P2-1 core line
        assert _estimate_tokens(last["content"]) <= 60    # deliberately small
    assert not any(str(m.get("content") or "").startswith("[Reminder")
                   for m in result.history)


def test_bookend_carries_relationship_descriptor_when_offered():
    class FakeMemory:
        def recall(self, query, limit=3):
            return []

        def relationship_snapshot(self):
            return {"trust": 0.9, "familiarity": 0.6, "warmth": 0.5,
                    "descriptor": "high trust, growing familiarity"}

    llm = ScriptedLLM([{"content": "Hello, sir."}])
    brain = make_brain(llm, memory=FakeMemory())
    result = brain.respond("s1", "hello")
    assert result.status == "answered"
    content = llm.prompts[0][-1]["content"]
    assert "calm British butler" in content
    assert "high trust, growing familiarity" in content


def test_bookend_persona_only_when_memory_has_no_snapshot():
    class PlainMemory:
        def recall(self, query, limit=3):
            return []

    llm = ScriptedLLM([{"content": "Hello, sir."}])
    brain = make_brain(llm, memory=PlainMemory())
    result = brain.respond("s1", "hello")
    assert result.status == "answered"
    content = llm.prompts[0][-1]["content"]
    assert "calm British butler" in content
    assert "Relationship" not in content


def test_bookend_is_charged_to_the_budget_accounting():
    """Size a turn that fits WITHOUT the bookend but not with it: the
    honest stop must fire before any model call — proof the bookend's
    estimate is inside respond()'s budget math."""
    from jarvis.brain import TOKEN_BUDGET, _estimate_tokens, _messages_tokens

    probe = make_brain(ScriptedLLM([]))
    bookend = probe._bookend_message()
    assert bookend is not None
    bt = _estimate_tokens(bookend["content"])
    base = _messages_tokens([
        {"role": "system", "content": probe._system_prompt()},
        {"role": "user", "content": "hi"},
    ])
    # Pad lands the bare messages just under the budget, close enough
    # that the bookend's own tokens push the total over it.
    pad_tokens = TOKEN_BUDGET - base - bt + 1
    assert pad_tokens > 0
    llm = ScriptedLLM([{"content": "should never be said"}])
    brain = make_brain(llm, self_knowledge="x" * (pad_tokens * 4))
    sized = _messages_tokens([
        {"role": "system", "content": brain._system_prompt()},
        {"role": "user", "content": "hi"},
    ])
    assert sized <= TOKEN_BUDGET           # fits without the bookend
    assert sized + bt > TOKEN_BUDGET       # not with it charged

    result = brain.respond("s1", "hi")
    assert result.status == "stopped"
    assert "working memory" in result.text
    assert llm.calls == 0                  # stopped before the model


# --------------------------------------------------------------------------- #
# 2. LoopGuard in the ReAct loop
# --------------------------------------------------------------------------- #
def _tool_messages(result):
    return [m for m in result.history if m.get("role") == "tool"]


def _counting_tool(name, result_text, counter):
    def fn(args):
        counter[name] = counter.get(name, 0) + 1
        return result_text
    return ToolDef(name=name, description=f"{name}.", parameters={}, fn=fn)


def test_loop_guard_cycle_halts_and_model_still_answers():
    """A -> B -> A in one batch: the third call's observation is a
    CYCLE; its tool message carries the reflect line; the model then
    answers from what exists (no hard error)."""
    counter = {}
    tools = [_counting_tool("alpha", "alpha-result", counter),
             _counting_tool("beta", "beta-result", counter)]
    store = FakeSessionStore()
    llm = ScriptedLLM([
        {"tool_calls": [{"name": "alpha", "args": {}},
                        {"name": "beta", "args": {}},
                        {"name": "alpha", "args": {}}]},
        {"content": "Wrapping up with what I have, sir."},
    ])
    brain = make_brain(llm, store=store, tools=tools)
    result = brain.respond("s1", "do the alpha beta dance")

    assert counter == {"alpha": 2, "beta": 1}     # all three executed
    assert result.status == "answered"
    assert result.text == "Wrapping up with what I have, sir."
    tool_msgs = _tool_messages(result)
    assert "loop guard: the same action repeated without new results" \
        in tool_msgs[2]["content"]
    assert "loop guard" not in tool_msgs[0]["content"]
    events = store.of_type("brain.loop_guard")
    assert len(events) == 1
    assert events[0]["payload"]["verdict"] == "CYCLE"
    assert events[0]["payload"]["action"] == "halt"


def test_loop_guard_halt_blocks_further_execution():
    """After the halt, later proposed calls are NOT executed — they get
    the skip text as their tool message."""
    counter = {}
    tools = [_counting_tool("alpha", "alpha-result", counter),
             _counting_tool("beta", "beta-result", counter)]
    llm = ScriptedLLM([
        {"tool_calls": [{"name": "alpha", "args": {}},
                        {"name": "beta", "args": {}},
                        {"name": "alpha", "args": {}},
                        {"name": "beta", "args": {}},
                        {"name": "alpha", "args": {}}]},
        {"content": "Understood, sir — stopping there."},
    ])
    brain = make_brain(llm, tools=tools)
    result = brain.respond("s1", "keep dancing")

    assert counter == {"alpha": 2, "beta": 1}     # 4th/5th never ran
    tool_msgs = _tool_messages(result)
    assert len(tool_msgs) == 5
    assert "not executed" in tool_msgs[3]["content"]
    assert "not executed" in tool_msgs[4]["content"]
    assert result.status == "answered"


def test_loop_guard_stagnant_nudges_once_and_execution_continues():
    """Same result text from differently-argued calls: the 3rd
    observation is STAGNANT — exactly ONE nudge is appended and
    execution continues (identical outputs from distinct calls can be
    legitimate polling work; stagnation alone never halts)."""
    counter = {}
    tools = [_counting_tool("poll", "unchanged", counter)]
    store = FakeSessionStore()
    llm = ScriptedLLM([
        {"tool_calls": [{"name": "poll", "args": {"page": i}}
                        for i in range(1, 6)]},
        {"content": "All pages polled, sir."},
    ])
    brain = make_brain(llm, store=store, tools=tools)
    result = brain.respond("s1", "poll all pages")

    assert counter == {"poll": 5}                 # nothing was blocked
    tool_msgs = _tool_messages(result)
    nudged = [m for m in tool_msgs if "changed nothing" in m["content"]]
    assert len(nudged) == 1
    assert nudged[0] is tool_msgs[2]               # on the 3rd observation
    assert not any("not executed" in m["content"] for m in tool_msgs)
    events = store.of_type("brain.loop_guard")
    assert len(events) == 1
    assert events[0]["payload"]["verdict"] == "STAGNANT"
    assert events[0]["payload"]["action"] == "nudge"
    assert result.status == "answered"


def test_loop_guard_quiet_on_normal_varied_work():
    """Different tools, changing results: no verdicts, no notes."""
    counter = {}
    tools = [_counting_tool("alpha", "a1", counter),
             _counting_tool("beta", "b1", counter)]
    store = FakeSessionStore()
    llm = ScriptedLLM([
        tool_reply("alpha"),
        tool_reply("beta"),
        {"content": "All done, sir."},
    ])
    brain = make_brain(llm, store=store, tools=tools)
    result = brain.respond("s1", "alpha then beta please")
    assert result.status == "answered"
    assert counter == {"alpha": 1, "beta": 1}
    assert store.of_type("brain.loop_guard") == []
    for m in _tool_messages(result):
        assert "loop guard" not in m["content"]


def test_each_turn_gets_a_fresh_vault():
    """The vault is dropped at each turn's end and rebuilt for the next:
    turn 2's history carries turn 1's key (it takes <SECRET_1> again)
    and the NEW key takes the next placeholder — both restore to their
    own values, and no raw key ever reaches the provider."""
    llm = ScriptedLLM([
        {"content": "First: <SECRET_1>"},
        {"content": "Second: <SECRET_2>"},
    ])
    brain = make_brain(llm, off_machine=True)
    r1 = brain.respond("s1", f"key one {FAKE_KEY}")
    assert FAKE_KEY in r1.text
    assert brain._turn_vault is None             # dropped, not carried over
    other_key = "sk-or-v1-" + "e5f6a7b8" * 6
    r2 = brain.respond("s1", f"key two {other_key}")
    assert other_key in r2.text                  # turn 2's own value restored
    assert brain._turn_vault is None
    turn2_seen = "\n".join(str(m.get("content") or "")
                           for m in llm.prompts[1])
    assert FAKE_KEY not in turn2_seen
    assert other_key not in turn2_seen
    assert "<SECRET_1>" in turn2_seen and "<SECRET_2>" in turn2_seen
