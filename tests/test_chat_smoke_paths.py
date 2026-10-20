"""Regression tests for basic chat and app-launch smoke paths."""

from types import SimpleNamespace

from jarvis.chat import (ChatApp, _is_simple_greeting, _simple_chat_reply,
                         _ordered_providers)


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



def test_common_smalltalk_does_not_reach_the_model_planner():
    assert "doing well" in _simple_chat_reply("how are u?")
    assert "No problem" in _simple_chat_reply("no")
    assert _simple_chat_reply("search for Jarvis") is None


def test_explicit_internet_search_routes_to_web_search_with_scoped_network_access():
    app = object.__new__(ChatApp)
    app._allowances = ["fs.read"]
    app.registry = SimpleNamespace(_records={})
    app._is_real_skill_tool = lambda match: (
        match.skill == "web" and match.tool == "web_search")
    captured = {}

    def dispatch(text, match, via="intent_router"):
        captured["text"] = text
        captured["tool"] = match.tool
        captured["args"] = match.args
        captured["allowances"] = list(app._allowances)
        return "searched"

    app._dispatch_routed = dispatch
    app.router = None

    result = app._route_turn("search for jarvis on internet")

    assert result == "searched"
    assert captured["tool"] == "web_search"
    assert captured["args"]["query"] == "jarvis"
    assert "net.outbound" in captured["allowances"]
    assert app._allowances == ["fs.read"]


def test_open_youtube_routes_to_gated_browser_url():
    app = object.__new__(ChatApp)
    app.router = SimpleNamespace(route=lambda _text: SimpleNamespace(
        skill="system", tool="launch_app", args={"app": "YouTube"},
        fuzzy=False, confidence=1.0))
    app.registry = SimpleNamespace(_records={})
    app._pc = object()
    captured = {}

    def dispatch(text, match, via="intent_router"):
        captured["tool"] = match.tool
        captured["args"] = match.args
        return "routed"

    app._dispatch_routed = dispatch
    assert app._route_turn("open youtube") == "routed"
    assert captured == {
        "tool": "pc.open_url",
        "args": {"url": "https://www.youtube.com/"},
    }



def test_pc_call_dispatches_app_launch_instead_of_falling_through():
    app = object.__new__(ChatApp)
    app._pc = SimpleNamespace(
        launch_app=lambda name: {"ok": True, "name": name})
    assert app._pc_call("pc.launch_app", {"name": "Chrome"}) == {
        "ok": True, "name": "Chrome"
    }


def test_pc_open_url_rejects_non_http_schemes():
    app = object.__new__(ChatApp)
    app._pc = object()
    try:
        app._pc_call("pc.open_url", {"url": "javascript:alert(1)"})
    except ValueError as exc:
        assert "HTTP/HTTPS" in str(exc)
    else:
        raise AssertionError("non-HTTP URL should be rejected")



def test_approved_pc_executor_uses_pc_controller_not_skill_registry():
    app = object.__new__(ChatApp)
    app._pc = SimpleNamespace(
        launch_app=lambda name: {"ok": True, "name": name})
    assert app._executor("pc.launch_app", {"name": "Chrome"}) == {
        "ok": True, "name": "Chrome"
    }



def test_builtin_system_grammar_matches_plain_english_app_commands():
    from pathlib import Path
    from jarvis.intent_router import IntentRouter

    root = Path(__file__).resolve().parent.parent
    router = IntentRouter()
    router.load_skills_root(root / "skills")
    router.load_phrases(
        "system",
        (root / "jarvis" / "system_phrases.txt").read_text(encoding="utf-8"),
    )

    chrome = router.route("open chrome?")
    assert chrome is not None and chrome.fuzzy is False
    assert chrome.skill == "system" and chrome.tool == "launch_app"
    assert chrome.args == {"app": "chrome"}

    youtube = router.route("open youtube")
    assert youtube is not None and youtube.fuzzy is False
    assert youtube.skill == "system" and youtube.tool == "launch_app"
    assert youtube.args == {"app": "youtube"}



def test_provider_order_prefers_healthy_local_before_cloud_fallbacks():
    local = SimpleNamespace(name="ollama")
    cloud = [SimpleNamespace(name="groq"), SimpleNamespace(name="gemini")]
    gateway = SimpleNamespace(name="omniroute")
    keyless = SimpleNamespace(name="pollinations")

    ordered = _ordered_providers(local, cloud, gateway, keyless)
    assert [provider.name for provider in ordered] == [
        "ollama", "groq", "gemini", "omniroute", "pollinations"
    ]


def test_provider_order_still_works_when_local_provider_is_unavailable():
    cloud = [SimpleNamespace(name="groq")]
    keyless = SimpleNamespace(name="pollinations")
    ordered = _ordered_providers(None, cloud, None, keyless)
    assert [provider.name for provider in ordered] == ["groq", "pollinations"]



def test_explicit_search_preserves_non_latin_query_text():
    app = object.__new__(ChatApp)
    app._allowances = []
    app.registry = SimpleNamespace(_records={})
    app._is_real_skill_tool = lambda match: match.tool == "web_search"
    captured = {}
    app._dispatch_routed = lambda text, match, via="intent_router": (
        captured.update(args=match.args) or "searched")
    app.router = None

    assert app._route_turn("search for جاوس on internet") == "searched"
    assert captured["args"]["query"] == "جاوس"
