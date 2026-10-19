"""Tests for the remaining first-run HIGHs (F-08, F-09, F-12, F-20).

All headless: FallbackChain.last_via, TurnToken, _GuiWriter filtering,
probe_key neutering, and the /key restart-message surfacing mechanism.
The tkinter widgets themselves need the Windows smoke run.
"""

import queue
import sys
from pathlib import Path

import pytest

from jarvis.brain import (
    ChainBudget,
    FallbackChain,
    ProviderHTTPError,
)
from jarvis.chat_gui import TurnToken, _GuiWriter
from jarvis.llm_compat import fingerprint_key, probe_key


# -- helpers --------------------------------------------------------------- #

class _Ok:
    def __init__(self, name):
        self.name = name
        self.keys = []

    def respond(self, message, key_index=0, timeout=5.0):
        return f"reply-from-{self.name}"


class _Dead:
    """Always fails with a transport error (triggers fallback)."""
    def __init__(self, name):
        self.name = name
        self.keys = []

    def respond(self, message, key_index=0, timeout=5.0):
        raise ConnectionError("no route to host")


class _AuthDead:
    """401 with no spare keys — terminal for this provider (F-03: chain lives)."""
    def __init__(self, name):
        self.name = name
        self.keys = ["k1"]

    def respond(self, message, key_index=0, timeout=5.0):
        raise ProviderHTTPError(401, "bad key")


# -- F-08: provider provenance ---------------------------------------------- #

def test_last_via_success_names_provider():
    chain = FallbackChain([_Ok("ollama")])
    res = chain.respond("hi")
    assert res["ok"] and res["via"] == "ollama"
    assert chain.last_via == "ollama"


def test_last_via_fallback_names_winner():
    chain = FallbackChain([_Dead("ollama"), _Ok("pollinations")])
    res = chain.respond("hi")
    assert res["ok"] and res["via"] == "pollinations"
    assert chain.last_via == "pollinations"


def test_last_via_total_failure_resets_to_none():
    chain = FallbackChain([_Dead("ollama"), _AuthDead("groq")])
    res = chain.respond("hi")
    assert not res["ok"]
    assert chain.last_via == "none"


def test_last_via_budget_exhausted_resets_to_none():
    chain = FallbackChain([_Ok("ollama")])
    res = chain.respond("hi", budget=ChainBudget(max_attempts=0))
    assert not res["ok"]
    assert chain.last_via == "none"


def test_last_via_updates_across_turns():
    chain = FallbackChain([_Ok("groq")])
    chain.respond("hi")
    assert chain.last_via == "groq"
    # New chain state: a later total failure must not leave a stale name.
    dead = FallbackChain([_Dead("x")])
    dead.last_via = "stale"
    dead.respond("hi")
    assert dead.last_via == "none"


# -- F-09: turn token -------------------------------------------------------- #

def test_turn_token_live_then_abandoned():
    t = TurnToken()
    tok = t.new_turn()
    assert t.is_live(tok)
    t.abandon()
    assert not t.is_live(tok)


def test_turn_token_new_turn_invalidates_old():
    t = TurnToken()
    old = t.new_turn()
    new = t.new_turn()
    assert not t.is_live(old)
    assert t.is_live(new)


def test_gui_writer_drops_output_after_abandon():
    q: queue.Queue = queue.Queue()
    t = TurnToken()
    tok = t.new_turn()
    w = _GuiWriter(q, is_live=lambda: t.is_live(tok))
    w.write("first\n")
    assert q.get_nowait() == ("out", "first\n")
    t.abandon()  # user hit ■ Stop
    w.write("late output from orphan\n")
    assert q.empty()  # dropped, never leaks into the next turn


def test_gui_writer_default_always_live():
    q: queue.Queue = queue.Queue()
    w = _GuiWriter(q)
    w.write("hello\n")
    assert q.get_nowait() == ("out", "hello\n")


def test_gui_writer_empty_write_never_queues():
    q: queue.Queue = queue.Queue()
    w = _GuiWriter(q)
    w.write("")
    assert q.empty()


# -- F-12: no key spraying --------------------------------------------------- #

def test_probe_key_neutered_returns_none():
    assert probe_key("sk-anything-at-all") is None
    assert probe_key("") is None


def test_probe_key_makes_zero_network_calls(monkeypatch):
    import urllib.request

    def _boom(*a, **k):
        raise AssertionError("probe_key must not touch the network (F-12)")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    assert probe_key("gsk_supposedly_groq") is None


def test_fingerprint_still_covers_known_prefixes():
    # Detection path that REMAINS: shape-based, zero network.
    assert fingerprint_key("gsk_abc123") == "groq"
    assert fingerprint_key("sk-or-v1-abc") == "openrouter"
    assert fingerprint_key("nvapi-abc") == "nvidia"
    assert fingerprint_key("AIzaABC") == "gemini"
    assert fingerprint_key("totally-unknown-shape-xyz") is None


def test_key_handler_does_not_import_probe_key():
    # F-12 Option A: the /key handler must resolve via fingerprint_key
    # only. Regression guard — if someone re-adds probing, this fails.
    src = (Path(__file__).resolve().parent.parent
           / "jarvis" / "chat.py").read_text(encoding="utf-8")
    assert "from jarvis.llm_compat import fingerprint_key\n" in src
    assert "probe_key(" not in src.split("def handle_command")[1].split(
        'if text == "/keys"')[0].replace(
        "probe_key() used to spray", "")


# -- F-20: /key restart message reaches the window --------------------------- #

def test_key_restart_message_surfaces_through_capture():
    # F-20 mechanism: _run_turn redirects stdout into _GuiWriter, so
    # handle_command's prints land in the window queue — not the console.
    q: queue.Queue = queue.Queue()
    writer = _GuiWriter(q)
    old = sys.stdout
    sys.stdout = writer  # type: ignore[assignment]
    try:
        # Exactly what the /key handler prints on success.
        print("[keys] That's a gemini key — stored (keyring, never shown). "
              "Restart JARVIS to use it, sir.")
    finally:
        sys.stdout = old
    kind, text = q.get_nowait()
    assert kind == "out"
    assert "Restart JARVIS to use it, sir." in text
