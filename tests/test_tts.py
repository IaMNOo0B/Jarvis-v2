"""Tests for jarvis.tts — the speaking half of the voice loop.

Every test asserts a spec clause (learn-voice-loop-spec.md). The two
load-bearing properties of this module:

1. C-V1: a Speaker cannot exist without its on_state (echo guard) wiring.
2. C-V2: stop() clears its own flag — the next speak() always works.
"""

import http.server
import json
import os
import shutil
import stat
import sys
import threading
import time

import pytest

from jarvis.tts import (
    PiperEngine,
    Speaker,
    StubEngine,
    TTSError,
    Utterance,
    VoiceboxEngine,
    pick_engine,
    split_sentences,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def make_speaker(engine=None):
    """A Speaker wired to a recording on_state, with its transition log."""
    log = []
    sp = Speaker(on_state=log.append, engine=engine or StubEngine())
    return sp, log


def wait_for(pred, timeout=10.0, poll=0.01):
    """Wait until pred() is truthy. Raises AssertionError on timeout."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if pred():
            return True
        time.sleep(poll)
    raise AssertionError(f"timed out waiting for condition after {timeout}s")


# --------------------------------------------------------------------------- #
# 1. Echo guard by construction (anti-C-V1)
# --------------------------------------------------------------------------- #

def test_on_state_none_rejected():
    with pytest.raises(TypeError):
        Speaker(None, engine=StubEngine())


def test_on_state_noncallable_rejected():
    with pytest.raises(TypeError):
        Speaker("not-a-callback", engine=StubEngine())


def test_on_state_missing_arg_rejected():
    with pytest.raises(TypeError):
        Speaker(engine=StubEngine())


def test_on_state_transitions_fired():
    sp, log = make_speaker()
    utt = sp.speak("one two three")
    assert utt.wait(timeout=10.0)
    assert log == ["speaking", "idle"], log


def test_on_state_fired_on_stop_too():
    sp, log = make_speaker()
    utt = sp.speak(" ".join(f"word{i}" for i in range(40)))
    wait_for(lambda: utt.words_spoken >= 5)
    sp.stop()
    assert log[0] == "speaking"
    assert "idle" in log  # every transition is announced


# --------------------------------------------------------------------------- #
# 2. Word-level completion + Utterance Record
# --------------------------------------------------------------------------- #

def test_word_completion_tracked():
    sp, _log = make_speaker()
    utt = sp.speak("one two three")
    assert utt.wait(timeout=10.0)
    assert utt.words_total == 3
    assert utt.words_spoken == 3
    assert utt.words_spoken_text() == "one two three"
    assert utt.sentence_status == ["spoken"]
    assert utt.interrupted_at is None


def test_sentence_streaming_first_sentence_immediately():
    # Three sentences: the utterance exposes sentence 1 at once and the
    # rest queue behind it.
    sp, _log = make_speaker()
    utt = sp.speak("First. Second. Third.")
    assert len(utt.sentences) == 3
    assert utt.sentences[0] == "First."
    assert utt.wait(timeout=10.0)
    assert utt.sentence_status == ["spoken", "spoken", "spoken"]


def test_interrupt_mid_sentence_then_respeak():
    # THE C-V2 regression test: interrupt mid-sentence, then prove the
    # NEXT speak() works (the stop flag was cleared by stop() itself).
    sp, _log = make_speaker()
    words = [f"word{i}" for i in range(30)]
    utt = sp.speak(" ".join(words))
    wait_for(lambda: utt.words_spoken >= 5)
    sp.stop()
    assert 0 < utt.words_spoken < 30, utt.words_spoken
    assert utt.interrupted_at is not None
    assert len(utt.words_spoken_text().split()) == utt.words_spoken
    # The brain may only remember what left the speakers (spec §3.3).
    spoken_text = utt.words_spoken_text()

    # Second speak must work — the flag was cleared, not latched.
    utt2 = sp.speak("alpha beta gamma")
    assert utt2.wait(timeout=10.0)
    assert utt2.words_spoken == 3
    assert utt2.words_spoken_text() == "alpha beta gamma"
    assert spoken_text  # sanity: the first utterance recorded something


def test_speak_while_speaking_restarts_cleanly():
    sp, _log = make_speaker()
    utt1 = sp.speak(" ".join(f"long{i}" for i in range(40)))
    wait_for(lambda: utt1.words_spoken >= 3)
    utt2 = sp.speak("short one")
    assert utt2.wait(timeout=10.0)
    assert utt2.words_spoken == 2
    # The abandoned utterance was parked, not left dangling.
    assert utt1.finished
    assert utt1.words_spoken < 40


def test_empty_text_still_transitions():
    sp, log = make_speaker()
    utt = sp.speak("   ")
    assert utt.wait(timeout=10.0)
    assert utt.words_total == 0
    assert log == ["speaking", "idle"]


# --------------------------------------------------------------------------- #
# 3. Hinglish-safe sentence splitting
# --------------------------------------------------------------------------- #

def test_split_basic():
    assert split_sentences("Hello! How are you? I'm fine.") == [
        "Hello!", "How are you?", "I'm fine."]


def test_split_keeps_abbreviations():
    # "Mr." must not split the sentence — the Hinglish killer case.
    out = split_sentences(
        "Mr. Sharma ne kaha ki kaam ho jayega. Phir woh chale gaye!")
    assert out == ["Mr. Sharma ne kaha ki kaam ho jayega.",
                   "Phir woh chale gaye!"]


def test_split_initials_and_titles():
    out = split_sentences("Dr. A.P.J. Abdul Kalam the. Woh mahaan the.")
    assert out == ["Dr. A.P.J. Abdul Kalam the.", "Woh mahaan the."]


def test_split_ellipsis_and_newlines():
    out = split_sentences("Ruko…\nMain aa raha hoon. Theek hai?")
    assert out == ["Ruko…", "Main aa raha hoon.", "Theek hai?"]


def test_split_empty():
    assert split_sentences("") == []
    assert split_sentences("   ") == []


# --------------------------------------------------------------------------- #
# 4. Engine ladder + pick_engine (spec §7)
# --------------------------------------------------------------------------- #

class _MCPHandler(http.server.BaseHTTPRequestHandler):
    latency_s = 0.0

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        time.sleep(self.latency_s)
        req = json.loads(body.decode("utf-8"))
        if req.get("method") == "tools/list":
            result = {"tools": [{"name": "voicebox_speak"}]}
        else:
            result = {"played": True}
        resp = json.dumps({"jsonrpc": "2.0", "id": req.get("id"),
                           "result": result}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, *args):
        pass


@pytest.fixture()
def mcp_server():
    _MCPHandler.latency_s = 0.0
    srv = http.server.HTTPServer(("127.0.0.1", 0), _MCPHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}/mcp"
    srv.shutdown()


def test_voicebox_unreachable_is_loud():
    # Port 1: connection refused, fast. Must raise, never pretend.
    with pytest.raises(TTSError):
        VoiceboxEngine(url="http://127.0.0.1:1/mcp")


def test_voicebox_speaks_and_reports_words(mcp_server):
    eng = VoiceboxEngine(url=mcp_server)
    seen = []
    eng.speak_sentence("hello there friend", seen.append)
    assert seen == [0, 1, 2]
    assert eng.latency_violations == 0


def test_voicebox_latency_gate_logged(mcp_server, capsys):
    _MCPHandler.latency_s = 0.12
    eng = VoiceboxEngine(url=mcp_server, latency_gate_ms=50.0)
    eng.speak_sentence("hi there", lambda i: None)
    assert eng.latency_violations == 1
    assert eng.last_latency_ms is not None
    assert eng.last_latency_ms >= 100.0
    err = capsys.readouterr().err
    assert "LATENCY GATE VIOLATED" in err


def test_piper_missing_binary_is_loud(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(TTSError):
        PiperEngine()


def test_piper_fake_binary_end_to_end(tmp_path, monkeypatch):
    if os.name != "posix":
        pytest.skip("fake piper script needs a posix shell")
    script = tmp_path / "piper"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import struct, sys\n"
        "out = None\n"
        "args = sys.argv[1:]\n"
        "for i, a in enumerate(args):\n"
        "    if a == '--output_file' and i + 1 < len(args):\n"
        "        out = args[i + 1]\n"
        "# 1.0s of 16kHz mono 16-bit silence\n"
        "samples = b'\\x00\\x00' * 16000\n"
        "hdr = (b'RIFF' + struct.pack('<I', 36 + len(samples)) + b'WAVE'\n"
        "       + b'fmt ' + struct.pack('<IHHIIHH', 16, 1, 1, 16000, 32000, 2, 16)\n"
        "       + b'data' + struct.pack('<I', len(samples)))\n"
        "open(out, 'wb').write(hdr + samples)\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(shutil, "which",
                        lambda name: str(script) if name == "piper" else None)
    played = []
    eng = PiperEngine(model="fake.onnx", player=played.append)
    seen = []
    eng.speak_sentence("hello world test", seen.append)
    assert seen == [0, 1, 2]
    assert len(played) == 1  # the synthesized wav was handed to the player


def test_pick_engine_prefers_voicebox(mcp_server, monkeypatch):
    monkeypatch.setattr(VoiceboxEngine, "DEFAULT_URL", mcp_server)
    eng = pick_engine("auto")
    assert isinstance(eng, VoiceboxEngine)


def test_pick_engine_falls_back_to_stub_loudly(monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    # No server on the default port and no piper -> stub, with a LOUD warning.
    monkeypatch.setattr(VoiceboxEngine, "DEFAULT_URL",
                        "http://127.0.0.1:1/mcp")
    eng = pick_engine("auto")
    assert isinstance(eng, StubEngine)
    err = capsys.readouterr().err
    assert "WARNING" in err and "STUB" in err


def test_pick_engine_explicit_voicebox_down_raises(monkeypatch):
    monkeypatch.setattr(VoiceboxEngine, "DEFAULT_URL",
                        "http://127.0.0.1:1/mcp")
    with pytest.raises(TTSError):
        pick_engine("voicebox")


def test_pick_engine_explicit_piper_missing_raises(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(TTSError):
        pick_engine("piper")


def test_pick_engine_unknown_preference_raises():
    with pytest.raises(TTSError):
        pick_engine("bogus")


def test_speaker_defaults_to_auto_pick(monkeypatch):
    # No engine given -> pick_engine("auto") runs (loud warning here, stub).
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(VoiceboxEngine, "DEFAULT_URL",
                        "http://127.0.0.1:1/mcp")
    sp = Speaker(on_state=lambda s: None)
    assert isinstance(sp.engine, StubEngine)


# --------------------------------------------------------------------------- #
# 5. Utterance unit behavior
# --------------------------------------------------------------------------- #

def test_utterance_offsets_across_sentences():
    utt = Utterance(["one two", "three four five"])
    assert utt.words_total == 5
    utt.record_word(0, 1)   # second word of sentence 1
    assert utt.words_spoken == 2
    utt.record_word(1, 0)   # first word of sentence 2
    assert utt.words_spoken == 3
    assert utt.words_spoken_text() == "one two three"
