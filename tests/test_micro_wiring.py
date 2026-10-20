"""Micro-wiring — the one-liner seams that connect Ext-1, Ext-7 and
Ext-3 into the live app:

1. Capabilities provider: ChatApp passes `capabilities_provider` to
   Brain. chat.py holds the ONLY Brain(...) construction site in the
   package — the CLI (main) and the GUI (chat_gui) both reach it
   through ChatApp — so these tests exercise both app variants
   (PC control off / on), which are the two construction paths.
2. Evolution runner hook: ChatApp.turn runs the idle self-review when
   should_run says yes, stays silent when it says no, and a review
   that blows up can never break the user's turn.
3. Phone persistence: ChatApp.start_phone passes `data_dir` to
   PhoneRemote — without it, Ext-3's allow-always allowlist and
   reconnect watermark never activate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import jarvis.evolution_runner as evo
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


# --------------------------------------------------------------------------- #
# 1. Capabilities provider reaches the Brain, live from the real registry
# --------------------------------------------------------------------------- #

def test_brain_gets_provider_pc_off(app):
    provider = app.brain._capabilities_provider
    assert provider is not None
    cap_map = provider()
    names = {s.name for s in cap_map.skills}
    # First-party skills are approved at startup -> present and live.
    assert "clock" in names and "reminders" in names
    clock = cap_map.find_skill("clock")
    assert clock is not None and clock.available_tools
    # PC control disabled -> no synthetic pc group.
    assert "pc" not in names


def test_brain_gets_provider_pc_on(tmp_path):
    app_pc = ChatApp(BASE_DIR, tmp_path / "data", enable_pc=True)
    provider = app_pc.brain._capabilities_provider
    assert provider is not None
    cap_map = provider()
    pc = cap_map.find_skill("pc")
    assert pc is not None and pc.available_tools
    # The provider is LIVE: it rebuilds from the app's own registry —
    # same fingerprint as a fresh map built from that registry.
    from jarvis.capabilities import build_capability_map
    from jarvis import pc_control
    fresh = build_capability_map(app_pc.registry,
                                 pc_control.tool_definitions())
    assert cap_map.fingerprint == fresh.fingerprint


def test_provider_reflects_registry_mutation(app):
    # Quarantine-flip a skill in the live registry; the provider's next
    # map must show it (the brain never reads a frozen copy).
    before = app.brain._capabilities_provider()
    assert before.find_skill("clock").availability == "available"
    app.registry._records["clock"].approved = False
    after = app.brain._capabilities_provider()
    assert after.find_skill("clock").availability == "quarantined"
    assert after.fingerprint != before.fingerprint


# --------------------------------------------------------------------------- #
# 2. Evolution hook in turn()
# --------------------------------------------------------------------------- #

def test_hook_fires_when_should_run_true(app, monkeypatch):
    seen = {}

    def fake_run_review(data_dir, session_store, memory, now=None):
        seen["args"] = (data_dir, session_store, memory, now)
        return object()

    monkeypatch.setattr(evo, "should_run", lambda *a, **k: True)
    monkeypatch.setattr(evo, "run_review", fake_run_review)
    rec = BrainRecorder()
    app.brain.respond = rec
    app.turn("hello")
    assert "args" in seen
    data_dir, store, memory, now = seen["args"]
    assert data_dir == app.data_dir
    assert store is app.store
    assert memory is app.memory
    assert now is not None
    assert rec.calls == ["hello"]  # the turn itself still ran


def test_hook_silent_when_should_run_false(app, monkeypatch):
    called = []
    monkeypatch.setattr(evo, "should_run", lambda *a, **k: False)
    monkeypatch.setattr(
        evo, "run_review",
        lambda *a, **k: called.append(True))
    rec = BrainRecorder()
    app.brain.respond = rec
    app.turn("hello")
    assert called == []
    assert rec.calls == ["hello"]
    assert not (app.data_dir / "evolution").exists()


def test_raising_review_never_breaks_turn(app, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("review exploded")

    monkeypatch.setattr(evo, "should_run", lambda *a, **k: True)
    monkeypatch.setattr(evo, "run_review", boom)
    rec = BrainRecorder()
    app.brain.respond = rec
    app.turn("hello")  # must not raise
    out = capsys.readouterr().out
    assert "brain handled it, sir." in out
    assert "[error]" not in out
    # The failure is noted in the session store, not swallowed silently.
    evs = app.store.get_events(app.session_id)
    notes = [e for e in evs if e["type"] == "evolution.review_error"]
    assert len(notes) == 1
    assert "RuntimeError" in notes[0]["payload"]["error"]
    assert "review exploded" in notes[0]["payload"]["error"]


# --------------------------------------------------------------------------- #
# 3. PhoneRemote receives data_dir (Ext-3 persistence activation)
# --------------------------------------------------------------------------- #

def test_start_phone_passes_data_dir(app, monkeypatch, capsys):
    import jarvis.config as config_mod
    import jarvis.phone as phone_mod

    class FakeSecrets:
        def get(self, key, default=""):
            return "test-token" if key == "telegram_bot_token" else default

    captured = {}

    class FakeRemote:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def poll_once(self):
            raise KeyboardInterrupt  # leave the poll loop immediately

        def stop(self):
            pass

    monkeypatch.setattr(config_mod, "Secrets", FakeSecrets)
    monkeypatch.setattr(phone_mod, "PhoneRemote", FakeRemote)
    app.start_phone()  # returns after the first poll "interrupt"
    assert captured["data_dir"] == str(app.data_dir)
    assert captured["token"] == "test-token"
    assert "[phone] Stopped." in capsys.readouterr().out
