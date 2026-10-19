"""Tests for jarvis.stt — synthetic PCM only. No audio hardware, no models.

Covers: energy VAD on synthetic audio (speech/silence/hangover/min-speech/
adaptive floor), stub transcriber script + loud warning, lazy imports
(blocked optional deps -> typed errors naming the pip package, never a
leaked ImportError), AST proof of no top-level audio/ML imports, wake stub
trigger + cooldown, mic missing-package + lifecycle errors.
"""

import ast
import io
import math
import struct
import sys
from contextlib import redirect_stderr

import pytest

from jarvis.stt import (
    FRAME_MS,
    HANGOVER_MS,
    MIN_SPEECH_MS,
    SAMPLE_RATE,
    FasterWhisperTranscriber,
    MicError,
    MicStream,
    OpenWakeWordListener,
    STTError,
    StubTranscriber,
    StubWake,
    WakeError,
    WakeListener,
    vad_segments,
)


# --------------------------------------------------------------------------- #
# Synthetic PCM helpers
# --------------------------------------------------------------------------- #
def _tone(dur_s: float, freq: float = 440.0, amp: float = 0.8,
          sr: int = SAMPLE_RATE) -> bytes:
    n = int(dur_s * sr)
    out = bytearray()
    for i in range(n):
        v = int(amp * 32767 * math.sin(2.0 * math.pi * freq * i / sr))
        out += struct.pack("<h", v)
    return bytes(out)


def _silence(dur_s: float, sr: int = SAMPLE_RATE) -> bytes:
    return b"\x00" * (int(dur_s * sr) * 2)


def _noise(dur_s: float, amp: int = 200, freq: float = 60.0,
           sr: int = SAMPLE_RATE) -> bytes:
    # Deterministic low-level "room tone" (not random — reproducible).
    return _tone(dur_s, freq=freq, amp=amp / 32767.0, sr=sr)


@pytest.fixture
def blocked_deps():
    """Pretend the optional audio/ML packages are not installed."""
    names = ("faster_whisper", "openwakeword", "sounddevice")
    saved = {n: sys.modules.get(n) for n in names}
    for n in names:
        sys.modules[n] = None  # `import n` now raises ImportError
    yield
    for n, mod in saved.items():
        if mod is None:
            sys.modules.pop(n, None)
        else:
            sys.modules[n] = mod


# --------------------------------------------------------------------------- #
# VAD
# --------------------------------------------------------------------------- #
def test_vad_detects_single_utterance():
    pcm = _silence(0.5) + _tone(1.0) + _silence(0.5)
    segs = vad_segments(pcm)
    assert len(segs) == 1
    start, end = segs[0]
    assert 0.45 <= start <= 0.55
    # speech ends at 1.5s; 300ms hangover extends the segment
    assert 1.7 <= end <= 1.9


def test_vad_ignores_silence():
    assert vad_segments(_silence(2.0)) == []


def test_vad_empty_input_returns_no_segments():
    assert vad_segments(b"") == []


def test_vad_hangover_merges_short_pause():
    # 100ms gap < 300ms hangover -> one segment
    pcm = (_silence(0.3) + _tone(0.5) + _silence(0.1)
           + _tone(0.5) + _silence(0.5))
    segs = vad_segments(pcm)
    assert len(segs) == 1


def test_vad_long_pause_splits_segments():
    # 500ms gap > 300ms hangover -> two segments
    pcm = (_silence(0.3) + _tone(0.5) + _silence(0.5)
           + _tone(0.5) + _silence(0.5))
    segs = vad_segments(pcm)
    assert len(segs) == 2
    assert segs[0][1] < segs[1][0]


def test_vad_drops_sub_min_speech_blip():
    # 100ms < 200ms minimum -> discarded
    pcm = _silence(0.5) + _tone(0.1) + _silence(0.5)
    assert vad_segments(pcm) == []


def test_vad_closes_trailing_speech_at_buffer_end():
    pcm = _silence(0.5) + _tone(1.0)  # no trailing silence
    segs = vad_segments(pcm)
    assert len(segs) == 1
    assert segs[0][1] == pytest.approx(1.5, abs=0.03)


def test_vad_adapts_to_room_noise():
    # 1s of low room tone alone -> nothing; tone after noise -> detected
    assert vad_segments(_noise(1.0)) == []
    pcm = _noise(1.0) + _tone(0.5) + _silence(0.5)
    segs = vad_segments(pcm)
    assert len(segs) == 1
    assert 0.95 <= segs[0][0] <= 1.05


def test_vad_rejects_bad_sample_rate():
    with pytest.raises(STTError):
        vad_segments(_silence(0.2), sample_rate=0)


def test_vad_segment_times_are_sane():
    pcm = _silence(0.2) + _tone(0.4) + _silence(0.2)
    for start, end in vad_segments(pcm):
        assert 0.0 <= start < end <= 0.8 + HANGOVER_MS / 1000.0 + 0.05


# --------------------------------------------------------------------------- #
# Stub transcriber
# --------------------------------------------------------------------------- #
def test_stub_transcriber_returns_script_in_order():
    script = [
        {"text": "first", "language": "en", "confidence": 0.9},
        {"text": "pehla", "language": "hi", "confidence": 0.8},
    ]
    stt = StubTranscriber(script)
    pcm = _tone(0.2)
    assert stt.transcribe(pcm)["text"] == "first"
    r = stt.transcribe(pcm)
    assert (r["text"], r["language"]) == ("pehla", "hi")
    assert stt.transcribe(pcm)["text"] == "first"  # cycles


def test_stub_transcriber_result_shape():
    r = StubTranscriber().transcribe(_tone(0.2))
    assert set(r) == {"text", "language", "confidence"}


def test_stub_transcriber_warns_loud_once():
    stt = StubTranscriber()
    buf = io.StringIO()
    with redirect_stderr(buf):
        stt.transcribe(_tone(0.1))
        stt.transcribe(_tone(0.1))
    out = buf.getvalue()
    assert "WARNING" in out and "StubTranscriber" in out
    assert out.count("WARNING") == 1  # once, not per call


def test_stub_transcriber_empty_audio_raises():
    with pytest.raises(STTError):
        StubTranscriber().transcribe(b"")


# --------------------------------------------------------------------------- #
# Lazy imports — the core Wave 4 guarantee
# --------------------------------------------------------------------------- #
def test_no_audio_or_ml_imports_at_module_top_level():
    import pathlib
    src = pathlib.Path(__file__).resolve().parent.parent / "jarvis" / "stt.py"
    tree = ast.parse(src.read_text())
    banned = {"faster_whisper", "openwakeword", "sounddevice", "numpy"}
    stdlib = sys.stdlib_module_names | {"__future__"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots = {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots = {(node.module or "").split(".")[0]}
        else:
            continue
        assert not (roots & banned), f"banned top-level import: {roots}"
        assert roots <= stdlib, f"non-stdlib top-level import: {roots}"


def test_faster_whisper_missing_gives_typed_error(blocked_deps):
    stt = FasterWhisperTranscriber()
    with pytest.raises(STTError) as ei:
        stt.transcribe(_tone(0.2))
    assert "pip install faster-whisper" in str(ei.value)
    assert not isinstance(ei.value, ImportError)


def test_openwakeword_missing_gives_typed_error(blocked_deps):
    w = OpenWakeWordListener()
    with pytest.raises(WakeError) as ei:
        w.listen(b"\x00" * 3200)
    assert "pip install openwakeword" in str(ei.value)
    assert not isinstance(ei.value, ImportError)


def test_sounddevice_missing_gives_typed_error(blocked_deps):
    with pytest.raises(MicError) as ei:
        MicStream().open()
    assert "pip install sounddevice" in str(ei.value)


# --------------------------------------------------------------------------- #
# Wake word
# --------------------------------------------------------------------------- #
def test_stub_wake_triggers_on_phrase():
    w = StubWake(trigger_phrase="hey jarvis",
                 transcript_fn=lambda: "hey jarvis, what time is it",
                 cooldown_s=0.0)
    assert w.listen(b"\x00" * 320) is True
    assert w.last_score == 1.0


def test_stub_wake_ignores_other_speech():
    w = StubWake(trigger_phrase="hey jarvis",
                 transcript_fn=lambda: "hello there, how are you",
                 cooldown_s=0.0)
    assert w.listen(b"\x00" * 320) is False
    assert w.last_score == 0.0


def test_stub_wake_cooldown_blocks_double_fire():
    t = [1000.0]
    w = StubWake(transcript_fn=lambda: "hey jarvis",
                 clock=lambda: t[0], cooldown_s=1.5)
    assert w.listen(b"") is True
    assert w.listen(b"") is False  # within cooldown
    t[0] += 2.0
    assert w.listen(b"") is True  # cooldown expired


def test_stub_wake_warns_loud_once():
    w = StubWake(transcript_fn=lambda: "hey jarvis", cooldown_s=0.0)
    buf = io.StringIO()
    with redirect_stderr(buf):
        w.listen(b"")
        w.listen(b"")
    assert "WARNING" in buf.getvalue() and "StubWake" in buf.getvalue()


def test_wake_listener_default_threshold():
    assert OpenWakeWordListener().threshold == 0.5
    assert OpenWakeWordListener(threshold=0.7).threshold == 0.7
    assert isinstance(OpenWakeWordListener(), WakeListener)
    assert isinstance(StubWake(), WakeListener)


def test_wake_listener_is_abstract():
    with pytest.raises(TypeError):
        WakeListener()  # type: ignore[abstract]


# --------------------------------------------------------------------------- #
# Mic
# --------------------------------------------------------------------------- #
def test_mic_close_without_open_never_raises():
    MicStream().close()  # must not raise


def test_mic_iter_without_open_raises():
    with pytest.raises(MicError):
        iter(MicStream()).__next__()


def test_mic_open_is_idempotent_shape():
    # Without sounddevice we can't open; assert the *shape* of the API:
    # open() returns self on success path type, is_open is a bool.
    mic = MicStream()
    assert mic.is_open is False
