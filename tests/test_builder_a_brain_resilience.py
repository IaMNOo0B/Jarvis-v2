"""Builder Team A — Brain Resilience Pack tests.

Covers: CompletionAudit (orcbot delivery truth), ErrorClassifier +
FallbackChain rate-limit parking, the ask-controller gate wiring, and
the CowAgent anti-poisoning lesson filter (incl. self-critique use).

Fakes implement the REAL sibling interfaces (gate GateDecision, session
store emit/get_events, rules find). No network, no model.
"""

from jarvis.ask_controller import (  # noqa: F401  (documents wiring inputs)
    RequestAnalysis,
)
from jarvis.brain import (
    Brain,
    ErrorKind,
    FallbackChain,
    ProviderHTTPError,
    ToolDef,
    classify_error,
    filter_lesson,
)
from jarvis.completion_audit import CompletionAudit, audit_turn
from jarvis.gate import GateDecision, Verdict


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeGate:
    def __init__(self, verdicts=None):
        self.verdicts = verdicts or {}

    def check(self, tool_name, args, turn_allowances):
        verdict = self.verdicts.get(tool_name, Verdict.ALLOW)
        approval_request = None
        if verdict == Verdict.REQUIRE_APPROVAL:
            approval_request = {"action": tool_name, "tier": 3}
        return GateDecision(verdict=verdict, reason="test",
                            approval_request=approval_request)

    @staticmethod
    def wrap_output(output, source, trust="untrusted"):
        return (f'<tool_output source="{source}" trust="{trust}">'
                f"{output}</tool_output>")


class FakeSessionStore:
    """emit() + get_events() with the real signatures and event shape."""

    def __init__(self):
        self.events = []
        self._n = 0

    def emit(self, session_id, type, payload, actor, trust="user",
             causal_parent=None, trace_id=None):
        self._n += 1
        ev = {"event_id": f"ev{self._n}", "session_id": session_id,
              "seq": self._n, "type": type, "payload": payload,
              "causal_parent": causal_parent, "actor": actor,
              "trust": trust}
        self.events.append(ev)
        return ev["event_id"]

    def get_events(self, session_id, after_seq=0, limit=1000):
        return [e for e in self.events if e["seq"] > after_seq][:limit]

    def of_type(self, event_type):
        return [e for e in self.events if e["type"] == event_type]


class FakeRule:
    def __init__(self, text):
        self.text = text


class FakeRules:
    def __init__(self):
        self._rules = {
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


def make_brain(llm, store=None, tools=None, **kwargs):
    return Brain(gate=FakeGate(), session_store=store or FakeSessionStore(),
                 rules=FakeRules(), llm_call=llm, tools=tools or [], **kwargs)


# --------------------------------------------------------------------------- #
# 1. CompletionAudit — module level, driven by raw event streams
# --------------------------------------------------------------------------- #
def _ev(seq, type_, payload=None):
    return {"event_id": f"e{seq}", "session_id": "s", "seq": seq,
            "type": type_, "payload": payload or {}, "actor": "brain",
            "trust": "system", "causal_parent": None}


class _Store:
    def __init__(self, events):
        self._events = events

    def get_events(self, session_id, after_seq=0, limit=1000):
        return [e for e in self._events if e["seq"] > after_seq][:limit]


class TestCompletionAudit:
    def test_delivered_when_last_tool_success_before_reply(self):
        store = _Store([
            _ev(1, "user.message"),
            _ev(2, "tool.result", {"ok": False}),
            _ev(3, "tool.result", {"ok": True}),
            _ev(4, "brain.reply", {"text": "done, sir"}),
        ])
        out = audit_turn(store, "s")
        assert out["delivered"] is True
        assert out["tool_successes"] == 1 and out["tool_failures"] == 1

    def test_not_delivered_when_failure_after_last_success(self):
        store = _Store([
            _ev(1, "user.message"),
            _ev(2, "tool.result", {"ok": True}),
            _ev(3, "tool.result", {"ok": False}),
            _ev(4, "brain.reply", {"text": "I did it, sir"}),
        ])
        out = audit_turn(store, "s")
        assert out["delivered"] is False
        assert "after the last success" in out["reason"]

    def test_delivered_plain_answer_no_tools(self):
        store = _Store([_ev(1, "user.message"),
                        _ev(2, "brain.reply", {"text": "4, sir"})])
        assert audit_turn(store, "s")["delivered"] is True

    def test_not_delivered_on_approval(self):
        store = _Store([_ev(1, "user.message"),
                        _ev(2, "approval.requested", {})])
        out = audit_turn(store, "s")
        assert out["delivered"] is False
        assert "approval" in out["reason"]

    def test_not_delivered_on_honest_stop(self):
        store = _Store([
            _ev(1, "user.message"),
            _ev(2, "brain.decision", {"decision": "stop", "reason": "x"}),
        ])
        assert audit_turn(store, "s")["delivered"] is False

    def test_scoped_to_latest_turn(self):
        # An earlier catastrophic turn must not poison the current one.
        store = _Store([
            _ev(1, "user.message"),
            _ev(2, "tool.result", {"ok": False}),
            _ev(3, "brain.decision", {"decision": "stop"}),
            _ev(4, "user.message"),
            _ev(5, "brain.reply", {"text": "fresh answer, sir"}),
        ])
        out = audit_turn(store, "s")
        assert out["delivered"] is True
        assert out["tool_failures"] == 0

    def test_class_api(self):
        store = _Store([_ev(1, "user.message"),
                        _ev(2, "brain.reply", {"text": "ok"})])
        assert CompletionAudit(store).audit_turn("s")["delivered"] is True


# --------------------------------------------------------------------------- #
# 1b. CompletionAudit attached to BrainResult by Brain.respond
# --------------------------------------------------------------------------- #
class TestAuditAttached:
    def test_answered_turn_carries_delivered_audit(self):
        store = FakeSessionStore()
        brain = make_brain(ScriptedLLM(["It is noon, sir."]), store=store)
        res = brain.respond("s1", "what time is it?")
        assert res.status == "answered"
        assert res.audit is not None
        assert res.audit["delivered"] is True

    def test_failed_tool_turn_is_not_delivered(self):
        def boom(args):
            raise RuntimeError("disk gone")
        tool = ToolDef(name="explode", description="Boom.",
                       parameters={}, fn=boom)
        llm = ScriptedLLM(["TOOL: explode\nARGS: {}", "TOOL: explode\nARGS: {}"])
        brain = make_brain(llm, tools=[tool])
        res = brain.respond("s1", "explode please")
        assert res.status == "stopped"   # 2-attempt rule fired
        assert res.audit["delivered"] is False

    def test_approval_turn_is_not_delivered(self):
        store = FakeSessionStore()
        gate = FakeGate({"nuke": Verdict.REQUIRE_APPROVAL})
        tool = ToolDef(name="nuke", description="Tier 3.", parameters={},
                       fn=lambda args: "boom")
        brain = Brain(gate=gate, session_store=store, rules=FakeRules(),
                      llm_call=ScriptedLLM(["TOOL: nuke\nARGS: {}"]),
                      tools=[tool])
        res = brain.respond("s1", "nuke it")
        assert res.status == "approval_required"
        assert res.audit["delivered"] is False
        assert "approval" in res.audit["reason"]


# --------------------------------------------------------------------------- #
# 2. ErrorClassifier + rate-limit parking in the chain
# --------------------------------------------------------------------------- #
class TestErrorClassifier:
    def test_http_429_is_rate_limited_with_cooldown(self):
        out = classify_error(
            ProviderHTTPError(429, "slow down; retry after 45 seconds"))
        assert out.kind is ErrorKind.RATE_LIMITED
        assert out.cooldown_s == 45.0

    def test_http_429_minutes_cooldown_normalized(self):
        out = classify_error(ProviderHTTPError(429, "retry in 2 minutes"))
        assert out.cooldown_s == 120.0

    def test_http_429_no_cooldown_stated(self):
        out = classify_error(ProviderHTTPError(429, "Too Many Requests"))
        assert out.kind is ErrorKind.RATE_LIMITED
        assert out.cooldown_s is None

    def test_retryable_http(self):
        for status in (408, 500, 502, 503, 504):
            assert classify_error(ProviderHTTPError(status, "x")).kind \
                is ErrorKind.RETRYABLE

    def test_terminal_http(self):
        for status in (400, 401, 403, 404):
            assert classify_error(ProviderHTTPError(status, "x")).kind \
                is ErrorKind.TERMINAL

    def test_transport_is_retryable(self):
        assert classify_error(TimeoutError("t")).kind is ErrorKind.RETRYABLE
        assert classify_error(ConnectionError("down")).kind \
            is ErrorKind.RETRYABLE

    def test_buried_429_in_generic_error(self):
        out = classify_error(
            RuntimeError('Error code: 429 - {"retry_after": 90}'))
        assert out.kind is ErrorKind.RATE_LIMITED
        assert out.cooldown_s == 90.0

    def test_plain_error_is_terminal(self):
        assert classify_error(ValueError("nope")).kind is ErrorKind.TERMINAL


class _Provider:
    """Scripted provider: outcomes = list of reply strings or exceptions."""

    def __init__(self, name, outcomes, keys=None):
        self.name = name
        self.outcomes = list(outcomes)
        self.keys = keys or []
        self.calls = 0

    def respond(self, message, key_index=0, timeout=5.0):
        self.calls += 1
        if not self.outcomes:
            return "default reply"
        out = self.outcomes.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, secs):
        self.now += secs


class TestChainParking:
    def _chain(self, providers, clock):
        return FallbackChain(providers, sleep=lambda s: None, clock=clock)

    def test_429_parks_and_next_provider_answers(self):
        clock = _Clock()
        limited = _Provider("limited", [ProviderHTTPError(429, "rl")])
        backup = _Provider("backup", ["backup reply"])
        chain = self._chain([limited, backup], clock)
        res = chain.respond("hi")
        assert res["ok"] is True and res["via"] == "backup"
        outcomes = [a["outcome"] for a in res["attempts"]]
        assert "parked" in outcomes

    def test_parked_provider_skipped_until_cooldown_expires(self):
        clock = _Clock()
        limited = _Provider(
            "limited", [ProviderHTTPError(429, "retry after 30 seconds"),
                        "limited reply"])
        backup = _Provider("backup", ["backup reply", "backup reply"])
        chain = self._chain([limited, backup], clock)
        assert chain.respond("one")["via"] == "backup"
        assert chain.respond("two")["via"] == "backup"
        assert limited.calls == 1          # never retried while parked
        clock.advance(31)
        assert chain.respond("three")["via"] == "limited"

    def test_429_does_not_rotate_keys(self):
        clock = _Clock()
        limited = _Provider("limited",
                            [ProviderHTTPError(429, "rl")],
                            keys=["k1", "k2", "k3"])
        backup = _Provider("backup", ["ok"])
        chain = self._chain([limited, backup], clock)
        chain.respond("hi")
        assert limited.calls == 1          # parked after one hit, not 3 keys

    def test_default_cooldown_applies_when_unstated(self):
        clock = _Clock()
        limited = _Provider("limited",
                            [ProviderHTTPError(429, "Too Many Requests"),
                             "later"])
        chain = self._chain([limited], clock)
        assert chain.respond("one")["ok"] is False
        clock.advance(30)
        assert chain.respond("two")["ok"] is False   # default 60s not over
        clock.advance(31)
        assert chain.respond("three")["reply"] == "later"

    def test_generic_rate_limit_error_parks(self):
        clock = _Clock()
        limited = _Provider("limited",
                            [RuntimeError("rate limit exceeded")])
        backup = _Provider("backup", ["ok"])
        chain = self._chain([limited, backup], clock)
        res = chain.respond("hi")
        assert res["via"] == "backup"
        assert any(a["outcome"] == "parked" for a in res["attempts"])

    def test_401_still_rotates_keys(self):
        clock = _Clock()
        authy = _Provider("authy", [ProviderHTTPError(401, "bad key"),
                                    "via second key"], keys=["k1", "k2"])
        chain = self._chain([authy], clock)
        res = chain.respond("hi")
        assert res["ok"] is True and res["reply"] == "via second key"
        assert any(a["outcome"] == "key_rotated" for a in res["attempts"])


# --------------------------------------------------------------------------- #
# 3. Ask gate wiring
# --------------------------------------------------------------------------- #
_NORMAL_INPUTS = [
    "what is the weather in Mumbai?",
    "tell me everything about coding",
    "coding ke baare me sab batao",
    "2 plus 2 kitna hota hai?",
    "chrome kholo aur youtube chalao",
    "meri maa ko call kar do kal subah",
    "book a flight to Delhi tomorrow morning",
    "remind me to drink water at 5 pm",
    "play some nice music for me",
    "cancel my order from yesterday",
    "delete it later when you can",
    "who are you and what can you do?",
    "apna naam batao",
    "aaj ka din kaisa hai bhai",
    "sing a song for me please",
    "bhai ye python kya hota hai",
    "write a poem about the monsoon in Mumbai and make it long",
    "search the web for the best phone under 20000",
    "email kar do use kal wali file",
    "what did we talk about yesterday?",
    "set a timer for ten minutes and tell me the recipe for chai",
    "overall what is machine learning?",
    "samajh gaya, ab wohi karo jo bola tha subah tum ko",
    "good morning jarvis, kya haal hai",
]


class TestAskGate:
    def test_bare_verb_asks(self):
        for word in ("book", "cancel", "send", "schedule", "delete"):
            llm = ScriptedLLM(["irrelevant"])
            brain = make_brain(llm)
            res = brain.respond("s1", word)
            assert res.status == "asked", word
            assert llm.calls == 0, word  # model never consulted

    def test_normal_inputs_never_ask(self):
        asked = 0
        for text in _NORMAL_INPUTS:
            llm = ScriptedLLM(["An answer, sir." * 2])
            brain = make_brain(llm)
            res = brain.respond("s1", text)
            if res.status == "asked":
                asked += 1
        # Owner's bar: the gate must ask on <=20% of normal inputs.
        # In fact we require zero — every one of these is answerable.
        assert asked == 0

    def test_ask_gate_off_disables(self):
        llm = ScriptedLLM(["Booking what, sir? Tell me more."])
        brain = make_brain(llm, ask_gate=False)
        res = brain.respond("s1", "book")
        assert res.status == "answered"
        assert llm.calls == 1

    def test_asked_turn_audits_as_not_delivered(self):
        brain = make_brain(ScriptedLLM([]))
        res = brain.respond("s1", "book")
        assert res.status == "asked"
        assert res.audit["delivered"] is False

    def test_gate_decision_is_logged(self):
        store = FakeSessionStore()
        brain = make_brain(ScriptedLLM([]), store=store)
        brain.respond("s1", "book")
        gates = [e for e in store.of_type("brain.decision")
                 if e["payload"].get("decision") == "ask_gate"]
        assert gates and gates[0]["payload"]["verdict"] == "ask"


# --------------------------------------------------------------------------- #
# 4. Anti-poisoning filter + self-critique integration
# --------------------------------------------------------------------------- #
class TestFilterLesson:
    def test_negative_capability_claims_rejected(self):
        bad = [
            "the web tool doesn't work",
            "search skill fails to run",
            "I can't open files on this machine",
            "I cannot access the internet",
            "that is beyond my capabilities",
            "ye main nahi kar sakta",
            "I am unable to help with files",
        ]
        for text in bad:
            assert filter_lesson(text) is False, text

    def test_real_lessons_kept(self):
        good = [
            "always answer in Hinglish when he writes Hinglish",
            "use the web search for weather questions",
            "he prefers short answers in the morning",
            "When asked '2+2': do '4' (not 'I can't do math...')",
            "never say beyond my capabilities — act instead",
        ]
        for text in good:
            assert filter_lesson(text) is True, text

    def test_poisoned_learned_context_dropped_from_prompt(self):
        brain = make_brain(ScriptedLLM([]))
        brain._learned_context = (
            "## LEARNED FROM CORRECTIONS (follow these patterns):\n"
            "- the web_search tool doesn't work\n"
            "- always confirm before sending email")
        prompt = brain._system_prompt()
        assert "doesn't work" not in prompt
        assert "always confirm before sending email" in prompt


_LONG_DRAFT = ("Sir, the museum opens at nine in the morning and the "
               "last entry is at five; I would suggest the morning slot.")


class TestSelfCritiquePoisonGuard:
    def test_default_off_means_no_critique_call(self):
        llm = ScriptedLLM([_LONG_DRAFT])
        brain = make_brain(llm)
        res = brain.respond("s1", "when does the museum open?")
        assert res.status == "answered"
        assert llm.calls == 1  # no second (critique) call

    def test_good_revision_applied_when_on(self):
        revised = ("VIOLATIONS: tone too formal\n"
                   "REVISED: Museum 9 baje khulta hai sir, last entry 5 baje "
                   "hai — subah wala slot best rahega.")
        llm = ScriptedLLM([_LONG_DRAFT, revised])
        brain = make_brain(llm, self_critique=True)
        res = brain.respond("s1", "when does the museum open?")
        assert res.status == "answered"
        assert res.text.startswith("Museum 9 baje")

    def test_poisoned_revision_rejected_draft_kept(self):
        poisoned = ("VIOLATIONS: none\n"
                    "REVISED: I can't reliably answer questions about "
                    "museums, sir.")
        store = FakeSessionStore()
        llm = ScriptedLLM([_LONG_DRAFT, poisoned])
        brain = make_brain(llm, store=store, self_critique=True)
        res = brain.respond("s1", "when does the museum open?")
        assert res.text == _LONG_DRAFT  # original draft survives
        events = [e for e in store.of_type("brain.self_critique")
                  if e["payload"].get("rejected_poisoned")]
        assert events
