"""Regression tests for basic chat and app-launch smoke paths."""

from types import SimpleNamespace

from jarvis.chat import ChatApp, _is_simple_greeting


def test_standalone_greetings_are_provider_independent():
    for text in ("Hi", "hello!", "HEY", "Hey Jarvis.", "good morning"):
        assert _is_simple_greeting(text), text


def test_greeting_detector_does_not_swallow_a_real_request():
    for text in ("Hi, open Chrome", "hello can you help me", "hey and open Notepad"):
        assert not _is_simple_greeting(text), text


def test_exact_system_launch_phrase_maps_to_gated_pc_tool():
    app = object.__new__(ChatApp)
    app.router = SimpleNamespace(
        route=lambda _text: SimpleNamespace(
            skill="system",
            tool="launch_app",
            args={"app": "Chrome"},
            fuzzy=False,
            confidence=1.0,
        )
    )
    app.registry = SimpleNamespace(_records={})
    app._pc = object()
    captured = {}

    def dispatch(text, match, via="intent_router"):
        captured["text"] = text
        captured["tool"] = match.tool
        captured["args"] = match.args
        captured["via"] = via
        return "routed"

    app._dispatch_routed = dispatch

    result = app._route_turn("Chrome kholo")

    assert result == "routed"
    assert captured == {
        "text": "Chrome kholo",
        "tool": "pc.launch_app",
        "args": {"name": "Chrome"},
        "via": "intent_router",
    }


def test_system_launch_does_not_route_when_pc_control_is_disabled():
    app = object.__new__(ChatApp)
    app.router = SimpleNamespace(
        route=lambda _text: SimpleNamespace(
            skill="system",
            tool="launch_app",
            args={"app": "Chrome"},
            fuzzy=False,
            confidence=1.0,
        )
    )
    app.registry = SimpleNamespace(_records={})
    app._pc = None
    app._dispatch_routed = lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("must not dispatch when PC control is disabled")
    )

    assert app._route_turn("Chrome kholo") is None

def test_reminder_grammar_covers_common_natural_phrasing():
    from pathlib import Path
    from jarvis.intent_router import IntentRouter

    root = Path(__file__).resolve().parent.parent
    router = IntentRouter()
    router.load_skills_root(root / "skills")
    router.load_phrases(
        "system", (root / "jarvis" / "system_phrases.txt").read_text(encoding="utf-8")
    )

    match = router.route("remind me after 1 min of doing hw")
    assert match is not None and match.fuzzy is False
    assert match.skill == "reminders"
    assert match.tool == "reminder_set"
    assert match.args == {"in_minutes": 1, "text": "doing hw"}

    listed = router.route("is there any reminder set")
    assert listed is not None and listed.fuzzy is False
    assert listed.tool == "reminder_list"
