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
