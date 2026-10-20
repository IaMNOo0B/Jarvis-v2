"""CapNet wiring — the capability network LIVE in ChatApp's turn loop.

Covers the seams (capnet itself is unit-tested in test_capnet.py):

1. Prompt: the brain's capability section is the network's
   describe() — a superset replacing the plain summary — and a broken
   network build degrades to the plain summary, never to silence.
2. Pre-turn routing: after the intent tier, capnet dispatches ONLY
   unambiguous plans (tier-1 tool node, healthy, real in the registry,
   no required args, tool NAMED in the text) through the same
   gate-first dispatch (via="capnet"), skipping the LLM; keyword-only
   ("fuzzy") plans are recorded as capnet.plan events and NEVER
   execute.
3. Outcome feedback: a turn's tool.result events (and the answering
   provider, when the brain served) become capnet.outcome events.
4. /capabilities answers from explain()/describe().
5. start_voice builds its transcriber via create_transcriber("auto")
   — the Hinglish -> whisper -> stub chain — not a bare whisper.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.brain import TurnResult
from jarvis.chat import ChatApp

BASE_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture()
def app(tmp_path):
    return ChatApp(BASE_DIR, tmp_path / "data", enable_pc=False)


class BrainRecorder:
    """Stands in for brain.respond: records calls, answers plainly."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, session_id, text, allowances=None):
        self.calls.append(text)
        return TurnResult(status="answered", text="brain handled it, sir.")


def _events(app) -> list[dict]:
    return app.store.get_events(app.session_id, 0, 100000)


def _of_type(app, type_: str) -> list[dict]:
    return [e for e in _events(app) if e["type"] == type_]


def _outcomes(app) -> list[dict]:
    return [e["payload"] for e in _of_type(app, "capnet.outcome")]


# --------------------------------------------------------------------------- #
# 1. The network is in the prompt (describe replaces the summary)
# --------------------------------------------------------------------------- #

def test_prompt_section_is_network_describe(app):
    section = app.brain._capabilities_section(app.session_id)
    assert section.startswith("## Capability network")
    assert "verified live capability" in section
    # Superset REPLACES the plain summary — never stacked (no double
    # prompt cost).
    assert "## What you can do right now" not in section
    # The live network behind it knows the real tools.
    net = app._capability_network()
    assert net is not None and net.node("tool:now") is not None


def test_broken_network_falls_back_to_plain_summary(app, monkeypatch):
    import jarvis.capnet as capnet

    def boom(*a, **k):
        raise RuntimeError("network on fire")

    monkeypatch.setattr(capnet, "build_network", boom)
    assert app._capability_network() is None
    section = app.brain._capabilities_section(app.session_id)
    assert section.startswith("## What you can do right now")


# --------------------------------------------------------------------------- #
# 2. Pre-turn routing — the worked example + the strict bar
# --------------------------------------------------------------------------- #

def test_capnet_dispatches_named_tool_and_skips_llm(app, capsys):
    # Premise: the grammar tier can only FUZZY-match this phrasing
    # (trailing "now" breaks its anchored patterns), so the intent
    # tier returns None and the turn belongs to capnet.
    m = app.router.route("what time is it now")
    assert m is not None and m.fuzzy
    rec = BrainRecorder()
    app.brain.respond = rec
    app.turn("what time is it now")
    out = capsys.readouterr().out
    assert rec.calls == []                        # LLM never consulted
    assert "[answered]" in out and "UTC, sir." in out
    call = next(e for e in _events(app) if e["type"] == "tool.call")
    assert call["payload"]["tool"] == "now"
    assert call["payload"]["via"] == "capnet"
    assert call["payload"]["gate_verdict"] in ("allow", "allow_with_undo")
    plan = next(e for e in _events(app) if e["type"] == "capnet.plan")
    assert plan["payload"]["chosen"] == "tool:now"
    assert "chose tool:now" in plan["payload"]["reason"]
    # The dispatched turn feeds the outcome loop too.
    assert any(o["node_id"] == "tool:now" and o["ok"] is True
               for o in _outcomes(app))


def test_keyword_only_plan_is_recorded_but_never_executes(app, capsys):
    # "what is the time please": capnet's top pick IS tool:now (probe:
    # score 5.25 from keyword + phrase hits) — but the tool is not
    # NAMED in the text, so the plan is fuzzy by the wiring's bar:
    # recorded, never executed, the brain owns the turn.
    rec = BrainRecorder()
    app.brain.respond = rec
    app.turn("what is the time please")
    out = capsys.readouterr().out
    assert rec.calls == ["what is the time please"]
    assert "brain handled it, sir." in out
    assert _of_type(app, "tool.call") == []
    plan = next(e for e in _events(app) if e["type"] == "capnet.plan")
    assert plan["payload"]["chosen"] == "tool:now"


def test_no_match_plan_recorded_with_no_choice(app, capsys):
    rec = BrainRecorder()
    app.brain.respond = rec
    app.turn("band kar")
    assert rec.calls == ["band kar"]
    assert _of_type(app, "tool.call") == []
    plan = next(e for e in _events(app) if e["type"] == "capnet.plan")
    assert plan["payload"]["chosen"] is None


def test_capnet_explosion_falls_through_to_brain(app, capsys, monkeypatch):
    import jarvis.capnet as capnet

    def boom(*a, **k):
        raise RuntimeError("network on fire")

    monkeypatch.setattr(capnet, "select", boom)
    rec = BrainRecorder()
    app.brain.respond = rec
    app.turn("what time is it now")
    out = capsys.readouterr().out
    assert rec.calls == ["what time is it now"]   # brain saved the turn
    assert "brain handled it, sir." in out
    assert _of_type(app, "tool.call") == []


# --------------------------------------------------------------------------- #
# 3. Outcome feedback — tool results and the answering provider
# --------------------------------------------------------------------------- #

class ToolBrain:
    """A brain.respond stand-in emitting Brain._respond_inner's exact
    event pattern for one successful tool call."""

    def __call__(self, session_id, text, allowances=None):
        store = self._store
        user_ev = store.emit(session_id, "user.message", {"text": text},
                             actor="user", trust="user")
        call_ev = store.emit(session_id, "tool.call",
                             {"tool": "notes_list", "args": {},
                              "gate_verdict": "allow"},
                             actor="brain", trust="system",
                             causal_parent=user_ev)
        store.emit(session_id, "tool.result",
                   {"ok": True, "output": "{}"},
                   actor="tool", trust="tool_untrusted",
                   causal_parent=call_ev)
        store.emit(session_id, "brain.reply", {"text": "done, sir."},
                   actor="brain", trust="user", causal_parent=call_ev)
        return TurnResult(status="answered", text="done, sir.")


def test_turn_outcomes_recorded_for_tool_and_provider(app, capsys):
    app._chain = SimpleNamespace(last_via="ollama", providers=[],
                                 stats=lambda: {})
    fake = ToolBrain()
    fake._store = app.store
    app.brain.respond = fake
    app.turn("show my notes")
    outcomes = {(o["node_id"], o["ok"]) for o in _outcomes(app)}
    assert ("tool:notes_list", True) in outcomes
    assert ("provider:ollama", True) in outcomes


def test_no_provider_outcome_when_a_tier_dispatches(app, capsys):
    # A capnet-dispatched turn never consulted the chain; the provider
    # must not earn an outcome for work it did not do.
    app._chain = SimpleNamespace(last_via="ollama", providers=[],
                                 stats=lambda: {})
    app.turn("what time is it now")
    assert not any(o["node_id"].startswith("provider:")
                   for o in _outcomes(app))


# --------------------------------------------------------------------------- #
# 4. /capabilities — the network answering for itself
# --------------------------------------------------------------------------- #

def test_capabilities_command_describes_network(app, capsys):
    assert app.handle_command("/capabilities") is True
    out = capsys.readouterr().out
    assert "## Capability network" in out
    assert "now" in out


def test_capabilities_command_explains_one_node(app, capsys):
    assert app.handle_command("/capabilities now") is True
    out = capsys.readouterr().out
    assert "tool:now" in out
    assert "use when:" in out


def test_capabilities_command_unknown_node_is_honest(app, capsys):
    assert app.handle_command("/capabilities nope-not-real") is True
    out = capsys.readouterr().out
    assert "not in the capability network" in out


# --------------------------------------------------------------------------- #
# 5. start_voice uses the STT chain factory (Hinglish -> whisper -> stub)
# --------------------------------------------------------------------------- #

def test_start_voice_builds_transcriber_via_auto_chain(app, capsys,
                                                      monkeypatch):
    import jarvis.stt as stt_mod
    seen = []

    def fake_create(engine="auto", **kwargs):
        seen.append(engine)
        raise RuntimeError("sentinel: no engines in tests")

    monkeypatch.setattr(stt_mod, "create_transcriber", fake_create)
    app.start_voice()
    out = capsys.readouterr().out
    assert seen == ["auto"]
    assert "STT unavailable" in out
