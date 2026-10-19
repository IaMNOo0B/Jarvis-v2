"""Tests for jarvis.voice_loop — the Wave 4 voice plugin.

Every stage is faked. Nothing here touches real audio hardware.
"""
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from jarvis.voice_loop import (
    BARGE_MATCH_RATIO,
    BargeInDetector,
    EchoGuard,
    Speaker,
    UtteranceRecord,
    VoiceError,
    VoiceLoop,
    segment_sentences,
)

REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #

class FakeStore:
    def __init__(self):
        self.events = []

    def emit(self, session_id, type, payload, actor, trust="system", **kw):
        self.events.append({"type": type, "payload": payload, "actor": actor})
        return "evt"

    def types(self):
        return [e["type"] for e in self.events]

    def payloads(self, type):
        return [e["payload"] for e in self.events if e["type"] == type]


class FakeStream:
    """Mic stream fake. Chunks are b's...' (silence) or b'v...' (speech)."""

    def __init__(self, chunks, clock=None, advance=0.0):
        self._chunks = list(chunks)
        self._clock = clock
        self._advance = advance
        self.closed = False

    def read(self):
        if self._clock is not None:
            self._clock[0] += self._advance
        if not self._chunks:
            return None
        return self._chunks.pop(0)

    def close(self):
        self.closed = True


def vad(chunk):
    return chunk.startswith(b"v")


def make_loop(**kw):
    clock = kw.pop("clock", [0.0])
    defaults = dict(
        mic_fn=lambda: FakeStream([]),
        vad_fn=vad,
        wake_fn=lambda c: {"detected": False},
        stt_fn=lambda a: {"text": "", "words": [], "confidence": 0.0},
        brain_fn=lambda t: "ok.",
        clock=lambda: clock[0],
        session_store=FakeStore(),
    )
    defaults.update(kw)
    loop = VoiceLoop(**defaults)
    loop._fake_clock = clock
    return loop


def speech_chunks(n_sil_before=5, n_speech=10, n_sil_after=40):
    return [b"s"] * n_sil_before + [b"v"] * n_speech + [b"s"] * n_sil_after


# --------------------------------------------------------------------------- #
# Construction: echo guard by construction (anti-C-V1)
# --------------------------------------------------------------------------- #

def test_speaker_requires_on_state():
    with pytest.raises(VoiceError):
        Speaker(None)
    with pytest.raises(TypeError):
        Speaker()  # no default: the argument is mandatory


def test_wiring_pair_verified():
    guard = EchoGuard()
    good = Speaker(guard.on_tts_state)
    VoiceLoop.verify_pair(good, guard)  # no raise
    bad = Speaker(lambda s: None)
    with pytest.raises(VoiceError):
        VoiceLoop.verify_pair(bad, guard)


def test_voice_loop_builds_wired_pair():
    loop = make_loop()
    assert loop.speaker._on_state == loop.guard.on_tts_state


# --------------------------------------------------------------------------- #
# Full turn through all 8 stages
# --------------------------------------------------------------------------- #

def test_full_turn():
    words = []
    loop = make_loop(
        mic_fn=lambda: FakeStream(speech_chunks()),
        stt_fn=lambda a: {"text": "what time is it", "words": [], "confidence": 0.99},
        brain_fn=lambda t: "It is noon. The sky is clear.",
        audio_out=lambda w, si, wi: words.append(w),
    )
    out = loop.run_turn(session_id="s1")
    assert out.status == "completed"
    assert out.spoken_text == "It is noon. The sky is clear."
    assert words == "It is noon. The sky is clear.".split()
    store = loop._store
    assert "voice.turn_completed" in store.types()
    assert "voice.stage" in store.types()
    # no-dead-air: stages were signalled
    stages = [e["payload"]["stage"] for e in store.events if e["type"] == "voice.stage"]
    assert {"listening", "transcribing", "thinking", "speaking"} <= set(stages)


def test_no_speech_returns_quietly():
    loop = make_loop(mic_fn=lambda: FakeStream([b"s"] * 50))
    out = loop.run_turn()
    assert out.status == "no_speech"


def test_segment_sentences():
    assert segment_sentences("Hi there. How are you? Fine!") == [
        "Hi there.", "How are you?", "Fine!"]


# --------------------------------------------------------------------------- #
# Echo guard: muted during speech + adaptive tail
# --------------------------------------------------------------------------- #

def test_echo_ignored_during_speech_and_tail():
    clock = [0.0]
    muted_during = []
    loop = make_loop(clock=clock,
                     audio_out=lambda w, si, wi: muted_during.append(loop.guard.mic_muted()))
    assert loop.guard.mic_muted() is False
    rec = UtteranceRecord.from_text("Hello world.")
    assert loop.speaker.say(rec) == "spoken"
    assert muted_during and all(muted_during)  # muted for every word
    assert loop.guard.mic_muted() is True      # tail after stop
    clock[0] += 1.0                            # past the 800ms tail
    assert loop.guard.mic_muted() is False


def test_collect_ignores_audio_while_speaking():
    loop = make_loop()
    loop.guard.on_tts_state("speaking")
    got = loop._collect(FakeStream(speech_chunks()))
    assert got == b""  # every chunk dropped: our own voice never collected


def test_adaptive_tail():
    clock = [0.0]
    g = EchoGuard(clock=lambda: clock[0])
    assert g.tail_ms == 800
    g.echo_detected()
    assert g.tail_ms == 1000  # grows when our voice bleeds through
    for _ in range(10):
        g.turn_completed_clean()
    assert g.tail_ms == 900   # shrinks after 10 clean turns
    for _ in range(100):
        g.turn_completed_clean()
    assert g.tail_ms == 300   # never below the floor
    g2 = EchoGuard(clock=lambda: clock[0])
    for _ in range(20):
        g2.echo_detected()
    assert g2.tail_ms == 2000  # never above the ceiling


# --------------------------------------------------------------------------- #
# Barge-in: the two-word scheme
# --------------------------------------------------------------------------- #

def test_barge_in_echo_vs_novel():
    d = BargeInDetector()
    spoken = "the weather is sunny today"
    assert d.check("the weather is", spoken) == "echo"
    assert d.check("weather sunny today", spoken) == "echo"  # 100% match


def test_barge_in_novel_word_accumulator():
    d = BargeInDetector()
    spoken = "the weather is sunny today"
    assert d.check("weather sunny maybe", spoken) == "ignore"   # 1 novel
    assert d.check("weather sunny maybe later", spoken) == "ignore"  # 2 novel
    assert d.check("weather sunny maybe later tomorrow", spoken) == "interrupt"  # 3


def test_barge_in_hard_phrase():
    d = BargeInDetector()
    assert d.check("stop", "the weather is sunny today") == "interrupt"
    # ...but our own voice saying it back is still echo, never an interrupt
    assert d.check("never mind the rain", "never mind the rain") == "echo"


def test_stop_flag_cleared_so_second_speak_works():
    """The v1 C-V2 bug: stop() set a flag nothing cleared -> permanent mute."""
    calls = [0]

    def barge():
        calls[0] += 1
        return calls[0] >= 2

    spk = Speaker(lambda s: None, barge_check=barge)
    rec = UtteranceRecord.from_text("One two three four five.")
    assert spk.say(rec) == "interrupted"
    assert spk._stop_requested is False  # cleared BY stop() itself
    spk._barge_check = None
    rec2 = UtteranceRecord.from_text("Speaking again.")
    assert spk.say(rec2) == "spoken"  # not permanently muted


def test_say_refuses_with_stop_flag_set():
    spk = Speaker(lambda s: None)
    spk._stop_requested = True
    with pytest.raises(VoiceError):
        spk.say(UtteranceRecord.from_text("hi"))


# --------------------------------------------------------------------------- #
# Utterance truncation on interrupt: brain forgets unspoken words (M-V16)
# --------------------------------------------------------------------------- #

def test_utterance_truncated_on_interrupt():
    clock = [0.0]
    calls = [0]

    def partial():
        calls[0] += 1
        if calls[0] == 5:
            return "blue elephants dance nightly"  # 4 novel words
        return None

    loop = make_loop(
        clock=clock,
        mic_fn=lambda: FakeStream(speech_chunks()),
        stt_fn=lambda a: {"text": "tell me a story", "words": [], "confidence": 1.0},
        brain_fn=lambda t: "Sentence one here. Sentence two here. Sentence three here.",
        partial_fn=partial,
    )
    out = loop.run_turn(session_id="s1")
    assert out.status == "interrupted"
    full = "Sentence one here. Sentence two here. Sentence three here."
    assert out.spoken_text != full
    assert full.startswith(out.spoken_text)  # strict prefix: only spoken words
    assert out.interrupt_text == "blue elephants dance nightly"
    ev = loop._store.payloads("voice.turn_interrupted")[0]
    assert ev["spoken_text"] == out.spoken_text
    assert ev["full_reply"] == full  # the unspoken rest is logged, not remembered


# --------------------------------------------------------------------------- #
# Wake word
# --------------------------------------------------------------------------- #

def test_wake_single_word():
    # The wake word is "jarvis" (owner's decision) — one word, no
    # local/cloud split at the wake layer; the brain routes per turn.
    def wake_fn(chunk):
        if chunk == b"W1":
            return {"detected": True, "score": 0.9, "word": "jarvis"}
        return {"detected": False}

    loop = make_loop(
        mic_fn=lambda: FakeStream([b"s", b"W1", b"v", b"v"]),
        wake_fn=wake_fn)
    out = loop.wait_for_wake()
    assert (out.status, out.word) == ("wake", "jarvis")


def test_wake_sink_muted_during_tts_and_tail():
    clock = [0.0]
    seen = []

    def wake_fn(chunk):
        seen.append(chunk)
        return {"detected": True, "score": 0.9, "word": "hey jarvis"}

    loop = make_loop(clock=clock,
                     mic_fn=lambda: FakeStream([b"a", b"b"]),
                     wake_fn=wake_fn)
    loop.guard.on_tts_state("speaking")  # TTS is talking
    out = loop.wait_for_wake()
    assert out.status == "mic_closed"   # every chunk skipped
    assert seen == []                   # wake model never saw TTS audio
    loop.guard.on_tts_state("idle")     # stop -> tail starts
    clock[0] += 1.0                     # past the tail
    loop2_mic = make_loop(clock=clock,
                          mic_fn=lambda: FakeStream([b"W", b"v"], clock=clock),
                          wake_fn=lambda c: {"detected": c == b"W", "score": 0.9,
                                             "word": "hey jarvis"})
    out2 = loop2_mic.wait_for_wake()
    assert out2.status == "wake"


def test_false_accept_and_sensitivity_note(tmp_path):
    clock = [0.0]

    def go():
        loop = make_loop(clock=clock, data_dir=tmp_path,
                         date_fn=lambda: date(2026, 10, 19),
                         mic_fn=lambda: FakeStream(
                             [b"WAKE"] + [b"s"] * 10, clock=clock, advance=0.5),
                         wake_fn=lambda c: {"detected": c == b"WAKE",
                                            "score": 0.6, "word": "hey jarvis"},
                         vad_fn=lambda c: False)  # nobody actually spoke
        return loop.wait_for_wake()

    outs = [go() for _ in range(4)]
    assert all(o.status == "false_accept" for o in outs)
    last_loop_store = None
    # the 4th false accept must carry the sensitivity note
    loop = make_loop(clock=clock, data_dir=tmp_path,
                     date_fn=lambda: date(2026, 10, 19),
                     mic_fn=lambda: FakeStream(
                         [b"WAKE"] + [b"s"] * 10, clock=clock, advance=0.5),
                     wake_fn=lambda c: {"detected": c == b"WAKE",
                                        "score": 0.6, "word": "hey jarvis"},
                     vad_fn=lambda c: False)
    # stats persisted across loop instances (same day, same dir)
    out = loop.wait_for_wake()
    assert out.status == "false_accept"
    assert "voice.sensitivity_note" in loop._store.types()
    assert (tmp_path / "wake_stats.json").exists()


# --------------------------------------------------------------------------- #
# Latency budget: breach is loud, never silent
# --------------------------------------------------------------------------- #

def test_latency_breach_logged():
    clock = [0.0]

    def stt(a):
        clock[0] += 2.0
        return {"text": "hi", "words": [], "confidence": 1.0}

    def brain(t):
        clock[0] += 2.5  # slow brain: first word leaves at 4.5s
        return "Hello there friend."

    def audio_out(w, si, wi):
        clock[0] += 1.0

    loop = make_loop(clock=clock,
                     mic_fn=lambda: FakeStream(speech_chunks(), clock=clock),
                     stt_fn=stt, brain_fn=brain, audio_out=audio_out)
    out = loop.run_turn()
    assert out.status == "completed"
    assert out.latency_s == pytest.approx(4.5)
    assert out.latency_breach is True
    assert "voice.latency_breach" in loop._store.types()


def test_no_breach_when_fast():
    clock = [0.0]
    loop = make_loop(clock=clock,
                     mic_fn=lambda: FakeStream(speech_chunks(), clock=clock),
                     stt_fn=lambda a: {"text": "hi", "words": [], "confidence": 1.0},
                     brain_fn=lambda t: "Hi.")
    out = loop.run_turn()
    assert out.latency_breach is False
    assert "voice.latency_breach" not in loop._store.types()


# --------------------------------------------------------------------------- #
# R1: the text core has zero audio imports; neither does this module
# --------------------------------------------------------------------------- #

def test_no_audio_imports_at_module_level():
    code = (
        "import sys\n"
        "class Blocker:\n"
        "    def find_module(self, name, path=None):\n"
        "        if name.split('.')[0] in {'pyaudio','sounddevice',"
        "'speech_recognition','webrtcvad','openwakeword','faster_whisper',"
        "'pygame','pyaudioop'}:\n"
        "            return self\n"
        "        return None\n"
        "    def load_module(self, name):\n"
        "        raise ImportError('blocked: ' + name)\n"
        "sys.meta_path.insert(0, Blocker())\n"
        "sys.modules.pop('jarvis.voice_loop', None)\n"
        "import jarvis.voice_loop\n"
        "print('voice_loop imported clean')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=str(REPO),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "voice_loop imported clean" in r.stdout


# --------------------------------------------------------------------------- #
# Misc structural guarantees
# --------------------------------------------------------------------------- #

def test_speak_text_is_the_single_choke_point():
    """M-V2: every speech path goes through speak_text."""
    loop = make_loop(audio_out=lambda w, si, wi: None)
    out = loop.speak_text("Direct speech path.")
    assert out.status == "completed"
    assert out.spoken_text == "Direct speech path."
    assert "voice.turn_completed" in loop._store.types()


def test_collect_hard_cap_terminates():
    clock = [0.0]
    loop = make_loop(clock=clock)
    got = loop._collect(FakeStream([b"v"] * 200, clock=clock, advance=0.5))
    assert got != b""  # terminated at the cap instead of hanging
