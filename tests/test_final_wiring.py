"""Final wiring pass — ChatApp integration tests.

Covers the three wirings that connect today's builder modules into the
live app (all dispatch logic itself is unit-tested in the builders'
own test files; these tests prove the SEAMS):

1. IntentRouter in ChatApp.turn — exact grammar hits for real skill
   tools dispatch through the gate (brain never consulted, session
   events mirror a brain tool turn); virtual system intents and fuzzy
   matches never execute and fall through to the brain; a broken
   router can never break a turn.
2. filter_lesson on the correction -> golden-pair save path —
   negative capability claims are never stored as lessons.
3. (clean_for_tts is intentionally NOT wired here — the voice loop
   owns speech assembly; see PENDING-PUSH.md.)
"""

from __future__ import annotations

import re
from pathlib import Path

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
    return app.store.get_events(app.session_id)


def _tool_events(app) -> list[dict]:
    return [e for e in _events(app) if e["type"] == "tool.call"]


# --------------------------------------------------------------------------- #
# 1. Intent router wiring
# --------------------------------------------------------------------------- #

def test_router_built_at_startup(app):
    assert app.router is not None
    assert app.router.rule_count > 0
    # The built-in system table loaded (virtual intents exist to route).
    m = app.router.route("band kar")
    assert m is not None and m.skill == "system"


def test_exact_clock_dispatch_skips_brain(app, capsys):
    rec = BrainRecorder()
    app.brain.respond = rec
    app.turn("what time is it")
    out = capsys.readouterr().out
    assert rec.calls == []                      # LLM never consulted
    assert "[answered]" in out and "UTC, sir." in out
    evs = _events(app)
    types = [e["type"] for e in evs]
    assert types[0] == "user.message"
    call = next(e for e in evs if e["type"] == "tool.call")
    assert call["payload"]["tool"] == "now"
    assert call["payload"]["gate_verdict"] in ("allow", "allow_with_undo")
    assert call["payload"]["via"] == "intent_router"
    result = next(e for e in evs if e["type"] == "tool.result")
    assert result["payload"]["ok"] is True
    assert "brain.reply" in types               # audit/history see the turn


def test_exact_reminder_set_list_cancel_via_router(app, capsys):
    rec = BrainRecorder()
    app.brain.respond = rec
    app.turn("5 minute me chai ka reminder lagao")
    out = capsys.readouterr().out
    assert rec.calls == []
    assert "Reminder set, sir" in out and "chai" in out

    app.turn("mere reminders dikhao")
    out = capsys.readouterr().out
    assert rec.calls == []
    assert "chai" in out
    m = re.search(r"id ([0-9a-f]{8})\)", out)
    assert m, "reminder list reply must carry the id"
    rid = m.group(1)

    app.turn(f"{rid} wala reminder cancel karo")
    out = capsys.readouterr().out
    assert rec.calls == []
    assert "Reminder cancelled, sir." in out
    tools = [e["payload"]["tool"] for e in _tool_events(app)]
    assert tools == ["reminder_set", "reminder_list", "reminder_cancel"]


def test_virtual_system_intent_never_executes(app, capsys):
    rec = BrainRecorder()
    app.brain.respond = rec
    app.turn("band kar")  # exact hit for system.close_thing — VIRTUAL
    out = capsys.readouterr().out
    assert rec.calls == ["band kar"]            # brain owns the turn
    assert "brain handled it, sir." in out
    assert _tool_events(app) == []              # router executed nothing


def test_fuzzy_match_falls_through_to_brain(app, capsys):
    # Premise: this phrasing is a fuzzy (<=0.8) hit, not an exact one.
    m = app.router.route("what is the time please")
    assert m is not None and m.fuzzy and m.confidence < 1.0
    rec = BrainRecorder()
    app.brain.respond = rec
    app.turn("what is the time please")
    out = capsys.readouterr().out
    assert rec.calls == ["what is the time please"]
    assert "brain handled it, sir." in out
    assert _tool_events(app) == []


def test_router_explosion_falls_through(app, capsys):
    def boom(text):
        raise RuntimeError("router on fire")

    app.router.route = boom
    rec = BrainRecorder()
    app.brain.respond = rec
    app.turn("what time is it")  # would be an exact hit if router lived
    out = capsys.readouterr().out
    assert rec.calls == ["what time is it"]     # brain saved the turn
    assert "brain handled it, sir." in out
    assert "[error]" not in out


def test_ordinary_text_still_uses_brain(app, capsys):
    rec = BrainRecorder()
    app.brain.respond = rec
    app.turn("tell me a story about the sea")
    out = capsys.readouterr().out
    assert rec.calls == ["tell me a story about the sea"]
    assert "brain handled it, sir." in out


# --------------------------------------------------------------------------- #
# 2. filter_lesson on the golden-pairs path
# --------------------------------------------------------------------------- #

def _pairs_file(app) -> Path:
    return app.data_dir / "golden_pairs.jsonl"


def test_poisoned_correction_is_not_saved(app, capsys):
    app.turn("hello")  # stub greeting: answered, sets _last_exchange
    capsys.readouterr()
    app.turn("no, that is beyond my capabilities instead")
    out = capsys.readouterr().out
    assert "Skipped" in out
    path = _pairs_file(app)
    if path.exists():
        assert "beyond my capabilities" not in path.read_text(
            encoding="utf-8")


def test_good_correction_is_saved(app, capsys):
    app.turn("hello")
    capsys.readouterr()
    app.turn("no, just say the time loudly instead")
    out = capsys.readouterr().out
    assert "Noted your correction" in out
    path = _pairs_file(app)
    assert path.exists()
    assert "just say the time loudly" in path.read_text(encoding="utf-8")
