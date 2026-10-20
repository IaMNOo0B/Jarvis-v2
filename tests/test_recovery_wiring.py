"""Recovery wiring — the recovery pack LIVE in the turn loop.

The pack itself (effects journal, contracts, ladder) is unit-tested in
test_recovery_pack.py. These tests prove the SEAMS ChatApp/Brain wiring
adds:

1. ChatApp's gate registry carries the manifests' declared
   effects/postconditions, and the Gate is built with the recovery
   hooks (store sink, fs root = data dir, fact probe, evaluator,
   contract stash with TAKE semantics).
2. Brain tool execution runs through gate.dispatch (session/turn
   scoped): declared effects journal, failed postconditions stamp the
   tool.result payload, and the CompletionAudit flips to NOT delivered.
3. The recovery ladder climbs in a live brain turn: retry(1) ->
   substitute (a CapNet alternative, through the same gated path) ->
   escalate with the REFLECT-style causal line surfaced into the
   turn's events and the model's tool message. It never loops.
4. END-TO-END: a real ChatApp turn writes a file through the gate via
   the real code skill; the journal shows the effect; /undo-turn
   restores the original content. A reminder set through the routed
   tier journals too, and /undo-turn cancels it. An effect with no
   honest reversal is NAMED, never blanket-"undone".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis import effects as effects_mod
from jarvis.brain import Brain, ToolDef
from jarvis.capnet import CapabilityNetwork, Node
from jarvis.chat import ChatApp

BASE_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture()
def app(tmp_path):
    return ChatApp(BASE_DIR, tmp_path / "data", enable_pc=False)


class ScriptedLLM:
    """Returns scripted replies in order; records every prompt."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, messages):
        self.prompts.append(messages)
        if not self.replies:
            return "I have nothing further, sir."
        return self.replies.pop(0)


def _scripted_brain(app, llm, extra_tools=(), **brain_kw):
    """A REAL Brain over the app's REAL gate/store/rules/tools — only
    the model is scripted. This is the seam under test: everything the
    wiring connects (gate hooks, registry, skills, journal) is live."""
    tools = list(app.brain.tools.values()) + list(extra_tools)
    brain = Brain(
        gate=app.gate,
        session_store=app.store,
        rules=app.rules,
        llm_call=llm,
        tools=tools,
        memory=app.memory,
        ask_gate=False,
        contract_lookup=app._take_contract_report,
        **brain_kw)
    app.brain = brain
    return brain


def _events(app):
    return app.store.get_events(app.session_id, 0, 100000)


def _of_type(app, type_):
    return [e for e in _events(app) if e["type"] == type_]


# --------------------------------------------------------------------------- #
# 1. Gate construction — registry carries contracts, stash takes reports
# --------------------------------------------------------------------------- #

def test_gate_registry_carries_declared_contracts(app):
    code = app.gate.registry["code_write"]
    assert code["effects"] == [{"kind": "file",
                                 "target": "code/{args.path}"}]
    assert code["postconditions"] == [
        {"check": "file_exists", "target": "code/{args.path}"}]
    rem = app.gate.registry["reminder_set"]
    assert rem["effects"] == [{"kind": "reminder", "target": "{args.text}"}]
    assert rem["postconditions"] == [
        {"check": "file_exists", "target": "reminders/reminders.json"}]
    notes = app.gate.registry["notes_write"]
    assert notes["effects"] == [{"kind": "file",
                                 "target": "notes/{args.path}"}]
    # Undeclared tools carry EMPTY contracts — nothing is invented.
    assert app.gate.registry["now"]["effects"] == []
    assert app.gate.registry["now"]["postconditions"] == []


def test_contract_stash_take_semantics_and_journal(app):
    # A lying executor through the app's REAL gate: claims the write,
    # never creates the file. The postcondition hook must stash a
    # failed report; the effect must still journal.
    decision, out = app.gate.dispatch(
        "code_write", {"path": "ghost.txt", "content": "x"},
        ["fs.write"], lambda n, a: {"path": "ghost.txt", "written": True},
        session_id=app.session_id, turn_id="turn-x")
    assert out is not None
    journal = effects_mod.journal_for_turn(app.store, app.session_id,
                                           "turn-x")
    assert len(journal) == 1
    assert journal[0]["target"] == "code/ghost.txt"
    assert journal[0]["existed_before"] is False
    report = app._take_contract_report(app.session_id, "turn-x",
                                       "code_write")
    assert report is not None and report["passed"] is False
    assert report["failures"][0]["check"] == "file_exists"
    # TAKE semantics: consumed — a second take finds nothing.
    assert app._take_contract_report(app.session_id, "turn-x",
                                     "code_write") is None


# --------------------------------------------------------------------------- #
# 2./3. Brain turns — stamping, audit flip, ladder retry + escalate
# --------------------------------------------------------------------------- #

_LYING_ENTRY = {
    "tier": 1, "capabilities": [],
    "schema": {"required": ["path"],
               "properties": {"path": {"type": "string"}}},
    "effects": [{"kind": "file", "target": "{args.path}"}],
    "postconditions": [{"check": "file_exists", "target": "{args.path}"}],
}


def test_postcondition_failure_stamps_audits_and_escalates(app):
    calls = []

    def lying_fn(args):
        calls.append(args["path"])
        return {"written": True, "path": args["path"]}  # writes NOTHING

    app.gate.registry["writer_a"] = dict(_LYING_ENTRY)
    tool = ToolDef(name="writer_a", description="Writes a file.",
                   parameters={"type": "object",
                               "properties": {"path": {"type": "string"}},
                               "required": ["path"]},
                   fn=lying_fn)
    llm = ScriptedLLM([
        'TOOL: writer_a\nARGS: {"path": "liar.txt"}',
        "Done, sir.",
    ])
    brain = _scripted_brain(app, llm, extra_tools=[tool])
    res = brain.respond(app.session_id, "write the liar file",
                        app._allowances)

    # The ladder retried exactly once, then escalated — fn ran twice,
    # never a third time (the ladder cannot loop).
    assert calls == ["liar.txt", "liar.txt"]
    results = _of_type(app, "tool.result")
    assert len(results) == 2
    for ev in results:
        assert ev["payload"]["postcondition_failed"] is True
        assert "file_exists:liar.txt" in (
            ev["payload"]["postcondition_failures"])
    # The audit reads the turn as NOT delivered, stamp counted.
    assert res.audit["delivered"] is False
    assert res.audit["postcondition_failures"] == 2
    # Escalation surfaced: a recovery.escalated event with the causal
    # line, and the same line in the tool message the model saw.
    esc = _of_type(app, "recovery.escalated")
    assert len(esc) == 1
    summary = esc[0]["payload"]["summary"]
    assert "writer_a failed (postcondition_failed)" in summary
    tool_msgs = [m for m in llm.prompts[1] if m.get("role") == "tool"]
    assert any("Recovery note" in str(m.get("content", ""))
               and "writer_a failed (postcondition_failed)"
               in str(m.get("content", "")) for m in tool_msgs)
    # Both attempts journaled under the turn's user.message event id.
    user_evs = _of_type(app, "user.message")
    journal = effects_mod.journal_for_turn(
        app.store, app.session_id, user_evs[-1]["event_id"])
    assert len(journal) == 2
    assert all(r["target"] == "liar.txt" for r in journal)


def test_ladder_substitute_recovers_the_turn(app):
    order = []

    def bad_fn(args):
        order.append("writer_a")
        return {"written": True}  # claims success, writes nothing

    def good_fn(args):
        order.append("writer_b")
        (app.data_dir / args["path"]).write_text("by b", encoding="utf-8")
        return {"written": True}

    app.gate.registry["writer_a"] = dict(_LYING_ENTRY)
    app.gate.registry["writer_b"] = dict(_LYING_ENTRY)
    tools = [
        ToolDef(name="writer_a", description="Writes (badly).",
                parameters={"type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"]}, fn=bad_fn),
        ToolDef(name="writer_b", description="Writes (well).",
                parameters={"type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"]}, fn=good_fn),
    ]
    net = CapabilityNetwork(nodes=(
        Node(id="tool:writer_a", kind="tool", name="writer_a",
             purpose="write things", group="writing",
             alternatives=("tool:writer_b",)),
        Node(id="tool:writer_b", kind="tool", name="writer_b",
             purpose="write things", group="writing", health="available"),
    ))
    llm = ScriptedLLM([
        'TOOL: writer_a\nARGS: {"path": "sub.txt"}',
        "Done, sir.",
    ])
    brain = _scripted_brain(app, llm, extra_tools=tools,
                            network_provider=lambda: net)
    res = brain.respond(app.session_id, "write the sub file",
                        app._allowances)

    # retry(writer_a) -> substitute(writer_b) -> success. No escalation.
    assert order == ["writer_a", "writer_a", "writer_b"]
    sub_calls = [e for e in _of_type(app, "tool.call")
                 if e["payload"].get("via") == "recovery_substitute"]
    assert len(sub_calls) == 1
    assert sub_calls[0]["payload"]["tool"] == "writer_b"
    results = _of_type(app, "tool.result")
    assert results[-1]["payload"]["ok"] is True
    assert "postcondition_failed" not in results[-1]["payload"]
    assert _of_type(app, "recovery.escalated") == []
    # The audit judges the LAST outcome: a success after failures is a
    # delivery (the failures stay on the record as diagnostics).
    assert res.audit["delivered"] is True
    assert res.audit["postcondition_failures"] == 2
    assert (app.data_dir / "sub.txt").read_text(
        encoding="utf-8") == "by b"


# --------------------------------------------------------------------------- #
# 4. End-to-end — real turn writes through the gate, /undo-turn reverses
# --------------------------------------------------------------------------- #

def test_end_to_end_write_journal_and_undo_restores(app, capsys):
    llm = ScriptedLLM([
        'TOOL: code_write\nARGS: {"path": "demo.txt", "content": "original"}',
        "Written, sir.",
        'TOOL: code_write\nARGS: {"path": "demo.txt", "content": "changed"}',
        "Updated, sir.",
    ])
    _scripted_brain(app, llm)
    jail_file = app.data_dir / "code" / "demo.txt"

    app.turn("please write the demo file")
    assert jail_file.read_text(encoding="utf-8") == "original"
    app.turn("please update the demo file")
    assert jail_file.read_text(encoding="utf-8") == "changed"
    assert llm.prompts  # the brain (not a router tier) served both turns

    # Both turns journaled, turn-scoped to their user.message event ids.
    user_ids = [e["event_id"] for e in _of_type(app, "user.message")]
    first = effects_mod.journal_for_turn(app.store, app.session_id,
                                         user_ids[0])
    assert len(first) == 1
    assert first[0]["existed_before"] is False  # the turn CREATED it
    second = effects_mod.journal_for_turn(app.store, app.session_id,
                                          user_ids[1])
    assert len(second) == 1
    assert second[0]["target"] == "code/demo.txt"
    assert second[0]["existed_before"] is True
    # The code skill's .bak snapshot was adopted as the restore source.
    assert second[0]["before_value_ref"] == "code/demo.txt.bak"

    # /undo-turn reverses the LAST turn: original content restored.
    assert app.handle_command("/undo-turn") is True
    out = capsys.readouterr().out
    assert "code/demo.txt" in out
    assert "NOT reversed" not in out
    assert jail_file.read_text(encoding="utf-8") == "original"


def test_routed_reminder_journals_and_undo_cancels(app, capsys):
    # The intent tier routes this (no brain): the routed dispatch now
    # runs through gate.dispatch too, so the effect journals.
    app.turn("5 minute me chai ka reminder lagao")
    capsys.readouterr()
    fx = _of_type(app, "effect.recorded")
    assert len(fx) == 1
    assert fx[0]["payload"]["kind"] == "reminder"
    assert fx[0]["payload"]["target"] == "chai"
    listed = app._executor("reminder_list", {})
    assert [r["text"] for r in listed["reminders"]] == ["chai"]

    assert app.handle_command("/undo-turn") is True
    out = capsys.readouterr().out
    assert "chai" in out and "reversed" in out
    assert app._executor("reminder_list", {})["reminders"] == []


def test_undo_names_what_cannot_be_reversed(app, capsys):
    # notes_write keeps NO .bak: overwriting a note journals an effect
    # whose before-state has no snapshot. Undo must NAME it as not
    # reversed — never claim a blanket "undone".
    llm = ScriptedLLM([
        'TOOL: notes_write\nARGS: {"path": "n.txt", "content": "v1"}',
        "Noted, sir.",
        'TOOL: notes_write\nARGS: {"path": "n.txt", "content": "v2"}',
        "Updated, sir.",
    ])
    _scripted_brain(app, llm)
    note = app.data_dir / "notes" / "n.txt"
    app.turn("please write the note")
    app.turn("please rewrite the note")
    assert note.read_text(encoding="utf-8") == "v2"
    capsys.readouterr()

    assert app.handle_command("/undo-turn") is True
    out = capsys.readouterr().out
    assert "PARTIALLY" in out or "NOT reversed" in out
    assert "notes/n.txt" in out
    assert "snapshot" in out  # the honest reason is named
    # And the world was NOT pretended back: v2 still stands.
    assert note.read_text(encoding="utf-8") == "v2"


def test_undo_turn_with_nothing_journaled_is_honest(app, capsys):
    assert app.handle_command("/undo-turn") is True
    out = capsys.readouterr().out
    assert "Nothing to undo" in out


def test_undo_turn_is_a_command_not_a_brain_turn(app):
    # handle_command consumes it (the GUI/CLI never forward it).
    assert app.handle_command("/undo-turn") is True
    assert app.handle_command("/undo-turn please") is False
