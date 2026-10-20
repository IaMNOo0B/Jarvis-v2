"""Final seams — the owed one-line wirings, proven to CONDUCT.

Each test drives the live app/controller surface, not the helper in
isolation: a seam counts only when current actually flows through it.

1. phone.py turn ids — NOT wired here (the only un-scoped dispatch
   lives inside phone.py, outside this pass's territory); the exact
   one-liner is recorded in PENDING-PUSH.md instead.
2. RoutineGuard -> morning digest on the first morning turn.
3. GUI sentence sink -> speech_policy.clean_for_tts.
4. pc_control.run_in_terminal -> shell_guard.check_command (legacy
   blocklist first, tokenised guard deciding).
5. ChatApp startup -> AppRegistry (learned apps) + dcl registry.
6. CapNet curated node for web_fetch_tree.
7. PatternStore surface: startup notice + /patterns confirm/decline.
8. start_voice wake_fn -> jarvis.wakeword.create_wake_engine.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.brain import TurnResult
from jarvis.chat import ChatApp

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_SKILLS = BASE_DIR / "skills"


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
# 4. shell_guard decides in run_in_terminal
# --------------------------------------------------------------------------- #

def test_terminal_guard_catches_what_legacy_blocklist_misses():
    from jarvis import pc_control as pc
    # The legacy raw-string regexes genuinely cannot see this one:
    # the program name is quoted ('r"m"'), so 'rm\s+' never matches.
    assert pc._check_blocklist('r"m" -rf /') is None
    backend = pc.FakeUiaBackend()
    c = pc.PCController(backend=backend)
    with pytest.raises(pc.BlockedCommandError):
        c.run_in_terminal('r"m" -rf /')
    with pytest.raises(pc.BlockedCommandError):
        c.run_in_terminal("rm --recursive --force /")
    assert backend.calls_to("run_shell") == []  # nothing reached a shell


def test_terminal_guard_keeps_legacy_blocks_and_benign_flow():
    from jarvis import pc_control as pc
    backend = pc.FakeUiaBackend()
    c = pc.PCController(backend=backend)
    with pytest.raises(pc.BlockedCommandError):
        c.run_in_terminal("rm -rf /")            # legacy layer still fires
    out = c.run_in_terminal("echo hello")         # benign still flows
    assert out["ok"]
    assert backend.calls_to("run_shell")


# --------------------------------------------------------------------------- #
# 6. CapNet curated node for web_fetch_tree
# --------------------------------------------------------------------------- #

def _registry(tmp_path: Path, *skills: str):
    from jarvis.skills.registry import SkillRegistry
    dst = tmp_path / "skills"
    dst.mkdir()
    for s in skills:
        shutil.copytree(REPO_SKILLS / s, dst / s)
    data = tmp_path / "data"
    data.mkdir()
    reg = SkillRegistry(dst, data)
    reg.discover()
    return reg


def test_web_fetch_tree_is_a_curated_network_node(tmp_path):
    from jarvis.capnet import build_network, describe, select
    from jarvis.pc_control import tool_definitions as pc_tool_definitions
    reg = _registry(tmp_path, "web")
    reg.approve("web")
    net = build_network(reg, pc_tools=pc_tool_definitions())
    node = net.node("tool:web_fetch_tree")
    assert node is not None
    # Curated, not heuristic: the page_reading group (so web_fetch is
    # its alternative) and the hand-written routing phrases.
    assert node.group == "page_reading"
    assert "page structure" in node.use_when
    assert "tool:web_fetch" in node.alternatives
    assert "web_fetch_tree" in describe(net)
    plan = select(net, "show me the page structure and the form fields")
    assert plan.chosen == "tool:web_fetch_tree"


# --------------------------------------------------------------------------- #
# 5. Startup: AppRegistry (learned apps) + DCL registry configuration
# --------------------------------------------------------------------------- #

def test_pc_app_registry_live_and_persistent(tmp_path):
    data = tmp_path / "data"
    app1 = ChatApp(BASE_DIR, data, enable_pc=True)
    assert app1._pc is not None
    assert app1._pc.app_registry is not None
    app1._pc.app_registry.learn("chrome", "/apps/chrome")
    assert (data / "app_registry.db").exists()
    # A fresh app over the same data dir sees what the first learned.
    app2 = ChatApp(BASE_DIR, data, enable_pc=True)
    assert app2._pc.app_registry.lookup("chrome") == "/apps/chrome"


def test_pc_survives_broken_app_registry(tmp_path, monkeypatch):
    import jarvis.pc_control as pc_mod

    def boom(*a, **k):
        raise OSError("disk gone")

    monkeypatch.setattr(pc_mod, "AppRegistry", boom)
    app = ChatApp(BASE_DIR, tmp_path / "data", enable_pc=True)
    assert app._pc is not None            # PC control itself still works
    assert app._pc.app_registry is None   # only the learned rung is off


def test_dcl_registry_configured_at_startup(tmp_path):
    from jarvis import dcl
    data = tmp_path / "data"
    ChatApp(BASE_DIR, data, enable_pc=False)
    dcl.register_secret("seam_probe", "ghp_seamprobevalue0123456789")
    saved = data / "known_secrets.json"
    assert saved.exists()  # registration persisted into THIS data dir
    # Digests only — the value itself is never on disk.
    assert "ghp_seamprobevalue" not in saved.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 2. RoutineGuard -> morning digest
# --------------------------------------------------------------------------- #

def _today_ts(hour: int, minute: int = 0) -> float:
    lt = time.localtime()
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                        hour, minute, 0, 0, 0, -1))


def _guard_at(app, ts: float):
    """Install a RoutineGuard with the app's own spec but a fixed clock
    (the app's lazy builder is the seam; the clock is the test's)."""
    from jarvis.routine_guard import RoutineGuard, RoutineSpec
    guard = RoutineGuard(
        str(app.data_dir),
        specs={"morning_digest": RoutineSpec(
            name="morning_digest", period="day", due="05:00",
            window=("05:00", "12:00"), budget_s=30.0,
            catch_up_minutes=420.0)},
        time_fn=lambda: ts)
    app._routine_guard_instance = guard
    return guard


def _seed_digest_reminder(app) -> None:
    due = _today_ts(23, 59)  # today, never past-due during the test
    (app.data_dir / "reminders.json").write_text(json.dumps(
        [{"id": "r1", "due": due, "text": "call the dentist"}]),
        encoding="utf-8")


def test_morning_digest_fires_once_on_first_morning_turn(app, capsys):
    guard = _guard_at(app, _today_ts(7))
    _seed_digest_reminder(app)
    rec = BrainRecorder()
    app.brain.respond = rec
    app.turn("hello")
    out = capsys.readouterr().out
    assert "[morning digest]" in out
    assert "call the dentist" in out
    assert guard.state("morning_digest")["status"] == "fired"
    fired = [e for e in app.store.get_events(app.session_id, 0, 100000)
             if e["type"] == "routine.fired"]
    assert len(fired) == 1
    # Second turn the same morning: claimed already — no replay.
    app.turn("again")
    out2 = capsys.readouterr().out
    assert "[morning digest]" not in out2


def test_routine_event_is_child_of_the_turns_user_message(app, capsys):
    """Ordering law: the digest is checked at turn start, but its
    session event must land AFTER — and as a child of — the turn's
    opening user.message (the turn's identity everywhere else)."""
    _guard_at(app, _today_ts(7))
    rec = BrainRecorder()
    app.brain.respond = rec
    app.turn("what time is it")  # exact intent: chat emits user.message
    evs = app.store.get_events(app.session_id, 0, 100000)
    types = [e["type"] for e in evs]
    assert types[0] == "user.message"
    user_ev = evs[0]
    fired = next(e for e in evs if e["type"] == "routine.fired")
    assert fired["seq"] > user_ev["seq"]
    assert fired["causal_parent"] == user_ev["event_id"]


def test_morning_digest_after_noon_is_missed_never_replayed(app, capsys):
    guard = _guard_at(app, _today_ts(13))
    rec = BrainRecorder()
    app.brain.respond = rec
    app.turn("hello")
    out = capsys.readouterr().out
    assert "[morning digest]" not in out
    # Recorded as missed exactly once; the period is not replayed.
    assert guard.state("morning_digest")["status"] == "missed"
    app.turn("again")
    assert guard.state("morning_digest")["status"] == "missed"


# --------------------------------------------------------------------------- #
# 7. Patterns surface: startup notice + /patterns
# --------------------------------------------------------------------------- #

def _seed_patterns(data_dir: Path, tools=("tool0", "tool1")) -> None:
    from jarvis.patterns import Proposal
    data_dir.mkdir(parents=True, exist_ok=True)
    props = {}
    for t in tools:
        p = Proposal(key=f"pattern:{t}@09", tool=t, hour=9, count=5,
                     days=3,
                     text=f"You often use {t} around 09:00 "
                          f"(5 times over 3 days).")
        rec = p.to_dict()
        rec.update({"status": "suggested",
                    "updated_ts": "2026-10-20T00:00:00+00:00"})
        props[p.key] = rec
    (data_dir / "patterns.json").write_text(
        json.dumps({"proposals": props, "suppressed": []}),
        encoding="utf-8")


def test_patterns_notice_and_command_flow(tmp_path, capsys):
    from jarvis.patterns import PatternStore
    data = tmp_path / "data"
    _seed_patterns(data)
    app = ChatApp(BASE_DIR, data, enable_pc=False)
    out = capsys.readouterr().out
    assert "I noticed a few patterns" in out  # the one-line notice
    assert app.handle_command("/patterns") is True
    out = capsys.readouterr().out
    assert "tool0" in out and "tool1" in out
    # Decline #1: gone from pending AND durably suppressed — a fresh
    # store over the same dir (a "restart") still refuses it.
    assert app.handle_command("/patterns decline 1") is True
    out = capsys.readouterr().out
    assert "Dismissed for good" in out
    fresh = PatternStore(data)
    assert fresh.is_suppressed("pattern:tool0@09")
    assert [r["key"] for r in fresh.pending()] == ["pattern:tool1@09"]
    # Confirm the remaining one: it becomes a memory fact.
    assert app.handle_command("/patterns confirm 1") is True
    out = capsys.readouterr().out
    assert "Kept:" in out
    assert app.memory.get_fact("pattern:tool1@09") is not None
    assert PatternStore(data).pending() == []


def test_patterns_quiet_when_nothing_pending(app, capsys):
    assert app.handle_command("/patterns") is True
    out = capsys.readouterr().out
    assert "No patterns waiting" in out


# --------------------------------------------------------------------------- #
# 3 + 8. start_voice: wake engine wiring + sentence sink cleaning
# --------------------------------------------------------------------------- #

class _FakeSpeaker:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    def speak_sentence(self, text, on_word=None):
        self.spoken.append(text)


class _FakeWakeEngine:
    name = "fake"
    last_score = 0.0

    def __init__(self) -> None:
        self.fed: list[bytes] = []

    def keywords(self):
        return ["Jarvis"]

    def feed_frame(self, chunk):
        from jarvis.wakeword import WakeDetection
        self.fed.append(chunk)
        if chunk == b"WAKE":
            return WakeDetection(engine="fake", keyword="Jarvis",
                                 score=0.93, at=0.0,
                                 frame_index=len(self.fed))
        return None


def _drive_start_voice(app, monkeypatch, wake_factory):
    """Run start_voice with every engine faked; the fake VoiceLoop
    captures the wired callables and closes the mic at once, so
    start_voice returns after one loop iteration."""
    import jarvis.stt as stt_mod
    import jarvis.tts as tts_mod
    import jarvis.voice_loop as vl_mod
    import jarvis.wakeword as ww_mod

    speaker = _FakeSpeaker()
    captured: dict = {}

    class _Loop:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def wait_for_wake(self, session_id=None):
            return SimpleNamespace(status="mic_closed")

    monkeypatch.setattr(
        stt_mod, "create_transcriber",
        lambda engine="auto", **k: SimpleNamespace(
            transcribe=lambda audio: {"text": ""}))
    monkeypatch.setattr(tts_mod, "pick_engine", lambda pref="auto": speaker)
    monkeypatch.setattr(vl_mod, "VoiceLoop", _Loop)
    monkeypatch.setattr(ww_mod, "create_wake_engine", wake_factory)
    app.start_voice()
    return captured, speaker


def test_start_voice_wake_fn_uses_real_engine(app, monkeypatch, capsys):
    engine = _FakeWakeEngine()
    captured, _speaker = _drive_start_voice(
        app, monkeypatch, lambda: engine)
    out = capsys.readouterr().out
    assert "Wake word armed (fake)" in out
    wake_fn = captured["wake_fn"]
    quiet = wake_fn(b"silence")
    assert quiet["detected"] is False
    hit = wake_fn(b"WAKE")
    assert hit == {"detected": True, "score": 0.93, "word": "Jarvis"}
    # The chunks really flowed into the engine, in order.
    assert engine.fed == [b"silence", b"WAKE"]


def test_start_voice_wake_unavailable_falls_back_to_stub(
        app, monkeypatch, capsys):
    from jarvis.wakeword import WakeWordError

    def factory():
        raise WakeWordError(
            "no wake-word engine available — voicute: model missing; "
            "openwakeword: package not installed")

    captured, _speaker = _drive_start_voice(app, monkeypatch, factory)
    out = capsys.readouterr().out
    # The engines' exact reason, printed exactly once.
    assert "voicute: model missing" in out
    assert out.count("Wake word unavailable") == 1
    # Stub behaviour holds: nothing is ever "detected".
    wake_fn = captured["wake_fn"]
    assert wake_fn(b"WAKE") == {"detected": False, "score": 0.0,
                                "word": ""}


def test_gui_sentence_sink_speaks_cleaned_text(app, monkeypatch):
    captured, speaker = _drive_start_voice(
        app, monkeypatch, lambda: _FakeWakeEngine())
    sink = captured["audio_out"]
    words = ["Here", "is", "**bold**", "news,",
             "ghp_abcdefghijklmnopqrstuvwxyz0123456789"]
    for i, w in enumerate(words):
        sink(w, 0, i)
    sink.flush()
    assert speaker.spoken, "nothing was spoken"
    joined = " ".join(speaker.spoken)
    assert "**" not in joined          # markdown stripped
    assert "ghp_" not in joined       # secret redacted
    assert "bold" in joined            # the words themselves survive
