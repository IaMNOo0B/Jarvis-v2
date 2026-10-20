"""Extension Team 5 — jarvis.wakeword tests.

No real onnxruntime / openwakeword in this environment (both are
optional deps by design): Voicute is exercised through a FAKE
onnxruntime injected into sys.modules whose sessions implement the
verified upstream contract (mel [1,1,T,32] out; keyword scores in,
[1,N] out), and openWakeWord through the adapter's listener_factory
seam wrapping a fake stt listener. numpy IS real, so the inference
glue (windowing, mel normalisation, softmax) runs for real.
"""

from __future__ import annotations

import json
import sys
import types
import zipfile
from pathlib import Path

import numpy as np
import pytest

from jarvis import wakeword
from jarvis.wakeword import (
    OpenWakeWordAdapter,
    VoicuteAdapter,
    WakeDetection,
    WakeWordError,
    create_wake_engine,
    probe_engines,
)

FRAME = bytes(1280 * 2)  # one 80 ms int16 frame of silence
SPIKE = [0.01, 0.99, 0.01]        # raw scores: "Jarvis" dominates
LOW = [0.34, 0.33, 0.33]          # raw scores: nothing dominates
KEYWORDS = ["Hey Jarvis", "Jarvis", "Hi Jarvis"]


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class _FakeInput:
    def __init__(self, name, shape):
        self.name = name
        self.shape = shape


class _FakeMelSession:
    """Contract: run({'input': (1, N) float32}) -> [ (1, 1, T, 32) ]."""

    def __init__(self, src, providers=None):
        pass

    def get_inputs(self):
        return [_FakeInput("input", [1, None])]

    def run(self, _outputs, feed):
        n = feed["input"].shape[1]
        t = max(1, (n - 400) // 160 + 1)
        return [np.zeros((1, 1, t, 32), dtype=np.float32)]


class _FakeKwSession:
    """Contract: run({'input': (1, mel_time, cols)}) -> [ (1, N) scores ].
    Scores come from a class-level script, one entry per call."""

    script = [SPIKE]
    calls = 0
    input_shape = [1, 98, 32]

    def __init__(self, src, providers=None):
        pass

    def get_inputs(self):
        return [_FakeInput("input", list(type(self).input_shape))]

    def run(self, _outputs, feed):
        cls = type(self)
        idx = min(cls.calls, len(cls.script) - 1)
        cls.calls += 1
        return [np.array([cls.script[idx]], dtype=np.float32)]


def install_fake_ort(monkeypatch, script=None, input_shape=None):
    _FakeKwSession.script = list(script) if script is not None else [SPIKE]
    _FakeKwSession.calls = 0
    _FakeKwSession.input_shape = list(input_shape or [1, 98, 32])
    mod = types.ModuleType("onnxruntime")

    def factory(src, providers=None):
        if isinstance(src, (str, Path)) and str(src).endswith(
                "melspectrogram.onnx"):
            return _FakeMelSession(src, providers)
        return _FakeKwSession(src, providers)

    mod.InferenceSession = factory
    monkeypatch.setitem(sys.modules, "onnxruntime", mod)
    return _FakeKwSession


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def make_zip_bundle(tmp_path: Path, **info_overrides) -> Path:
    info = {
        "model_type": "multi_keyword",
        "keywords": KEYWORDS,
        "model_file": "kw.onnx",
        "mel_time": 98,
        "cons_frames": 2,
        "n_mels": 32,
    }
    info.update(info_overrides)
    zp = tmp_path / "multi_jarvis_v9.3.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("model_info.json", json.dumps(info))
        zf.writestr("kw.onnx", b"fake-onnx-bytes")
    (tmp_path / "melspectrogram.onnx").write_bytes(b"fake-mel")
    return zp


# --------------------------------------------------------------------------- #
# Voicute — availability honesty
# --------------------------------------------------------------------------- #
def test_voicute_unavailable_without_onnxruntime(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "onnxruntime", None)  # import fails
    zp = make_zip_bundle(tmp_path)
    eng = VoicuteAdapter(model_path=zp)
    assert eng.available() is False
    assert "pip install onnxruntime" in eng.unavailable_reason()


def test_voicute_unavailable_without_model(monkeypatch, tmp_path):
    install_fake_ort(monkeypatch)
    eng = VoicuteAdapter(model_path=tmp_path / "nope.zip")
    assert eng.available() is False
    assert "not found" in eng.unavailable_reason()


def test_voicute_feed_raises_typed_error_when_unavailable(
        monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    eng = VoicuteAdapter(model_path=make_zip_bundle(tmp_path))
    with pytest.raises(WakeWordError, match="onnxruntime"):
        eng.feed_frame(FRAME)


def test_voicute_keywords_readable_without_ml_deps(tmp_path):
    # model_info.json parsing needs no onnxruntime — works pre-install.
    eng = VoicuteAdapter(model_path=make_zip_bundle(tmp_path))
    assert eng.keywords() == KEYWORDS


def test_voicute_threshold_clamped_like_upstream(tmp_path):
    zp = make_zip_bundle(tmp_path)
    assert VoicuteAdapter(model_path=zp, threshold=0.99).threshold == 0.95
    assert VoicuteAdapter(model_path=zp, threshold=0.10).threshold == 0.30


# --------------------------------------------------------------------------- #
# Voicute — detection behaviour
# --------------------------------------------------------------------------- #
def test_voicute_detects_bare_jarvis(monkeypatch, tmp_path):
    install_fake_ort(monkeypatch)  # every inference spikes "Jarvis"
    seen = []
    eng = VoicuteAdapter(model_path=make_zip_bundle(tmp_path),
                         clock=FakeClock(), on_detect=seen.append)
    assert eng.available() is True
    assert eng.feed_frame(FRAME) is None        # L1: 1st consecutive hit
    det = eng.feed_frame(FRAME)                 # L1: 2nd -> fire
    assert isinstance(det, WakeDetection)
    assert det.engine == "voicute"
    assert det.keyword == "Jarvis"              # the BARE wake word
    assert det.score > 0.98                     # competitive softmax prob
    assert det.frame_index == 2
    assert seen == [det]                        # callback fired exactly once
    assert eng.last_detection == det


def test_voicute_cooldown_suppresses_then_allows(monkeypatch, tmp_path):
    install_fake_ort(monkeypatch)
    clock = FakeClock()
    eng = VoicuteAdapter(model_path=make_zip_bundle(tmp_path), clock=clock)
    eng.feed_frame(FRAME)
    assert eng.feed_frame(FRAME) is not None    # fires at t=1000
    eng.feed_frame(FRAME)
    assert eng.feed_frame(FRAME) is None        # L1 refires, cooldown eats it
    clock.now += 2.0                            # past the 1.5 s cooldown
    eng.feed_frame(FRAME)
    assert eng.feed_frame(FRAME) is not None    # fires again


def test_voicute_l1_gap_tolerance(monkeypatch, tmp_path):
    kw = install_fake_ort(monkeypatch, script=[SPIKE, LOW, SPIKE])
    eng = VoicuteAdapter(model_path=make_zip_bundle(tmp_path),
                         clock=FakeClock())
    assert eng.feed_frame(FRAME) is None        # count 1
    assert eng.feed_frame(FRAME) is None        # miss -> gap 1 (tolerated)
    assert eng.feed_frame(FRAME) is not None    # count 2 -> fire
    assert kw.calls == 3


def test_voicute_l1_gap_overflow_resets(monkeypatch, tmp_path):
    install_fake_ort(monkeypatch,
                     script=[SPIKE, LOW, LOW, LOW, SPIKE, SPIKE])
    eng = VoicuteAdapter(model_path=make_zip_bundle(tmp_path),
                         clock=FakeClock())
    results = [eng.feed_frame(FRAME) for _ in range(6)]
    assert results[:5] == [None] * 5            # gap 3 > MAX_GAP reset it
    assert results[5] is not None               # two fresh hits -> fire


def test_voicute_softmax_is_competitive(monkeypatch, tmp_path):
    # Two phrases at raw 0.9 each: split by softmax+background -> ~0.47,
    # BELOW threshold. A naive adapter reading raw scores would fire.
    install_fake_ort(monkeypatch, script=[[0.9, 0.9, 0.05]])
    eng = VoicuteAdapter(model_path=make_zip_bundle(tmp_path),
                         clock=FakeClock())
    for _ in range(6):
        assert eng.feed_frame(FRAME) is None
    assert 0.46 < eng.last_score < 0.48


def test_voicute_legacy_single_keyword_bundle(monkeypatch, tmp_path):
    install_fake_ort(monkeypatch, script=[[0.99]])
    info = {"model_type": "tcn", "wake_word": "Jarvis",
            "model_file": "kw.onnx", "mel_time": 98, "cons_frames": 1}
    (tmp_path / "model_info.json").write_text(json.dumps(info))
    (tmp_path / "kw.onnx").write_bytes(b"fake")
    (tmp_path / "melspectrogram.onnx").write_bytes(b"fake")
    eng = VoicuteAdapter(model_path=tmp_path / "model_info.json",
                         clock=FakeClock())
    assert eng.keywords() == ["Jarvis"]
    det = eng.feed_frame(FRAME)
    assert det is not None and det.keyword == "Jarvis"


def test_voicute_mel_time_mismatch_is_a_load_error(monkeypatch, tmp_path):
    install_fake_ort(monkeypatch, input_shape=[1, 150, 32])  # bundle: 98
    eng = VoicuteAdapter(model_path=make_zip_bundle(tmp_path))
    with pytest.raises(WakeWordError, match="mel_time mismatch"):
        eng.feed_frame(FRAME)


def test_voicute_async_start_delivers_detection(monkeypatch, tmp_path):
    install_fake_ort(monkeypatch)
    seen = []
    eng = VoicuteAdapter(model_path=make_zip_bundle(tmp_path),
                         clock=FakeClock(), on_detect=seen.append)
    thread = eng.start(iter([FRAME] * 4))
    thread.join(timeout=5)
    eng.stop()
    assert len(seen) == 1 and seen[0].keyword == "Jarvis"


# --------------------------------------------------------------------------- #
# OpenWakeWord adapter
# --------------------------------------------------------------------------- #
class FakeSttListener:
    model_name = "hey_jarvis"
    last_score = 0.0

    def __init__(self):
        self.calls = 0

    def listen(self, pcm):
        self.calls += 1
        if self.calls == 1:
            self.last_score = 0.87
            return True
        self.last_score = 0.1
        return False


def test_oww_adapter_wraps_stt_listener():
    eng = OpenWakeWordAdapter(clock=FakeClock(),
                              listener_factory=FakeSttListener)
    assert eng.available() is True
    assert eng.keywords() == ["hey jarvis"]     # interim model, as spoken
    det = eng.feed_frame(FRAME)
    assert det is not None
    assert det.engine == "openwakeword"
    assert det.keyword == "hey jarvis"
    assert det.score == pytest.approx(0.87)
    assert eng.feed_frame(FRAME) is None


def test_oww_unavailable_without_openwakeword(monkeypatch):
    monkeypatch.setitem(sys.modules, "openwakeword", None)
    eng = OpenWakeWordAdapter()
    assert eng.available() is False
    assert "pip install openwakeword" in eng.unavailable_reason()


# --------------------------------------------------------------------------- #
# Selection + frame contract
# --------------------------------------------------------------------------- #
def test_create_prefers_voicute(monkeypatch, tmp_path):
    install_fake_ort(monkeypatch)
    eng = create_wake_engine({"voicute_model": str(make_zip_bundle(tmp_path))})
    assert isinstance(eng, VoicuteAdapter)


def test_create_falls_back_to_openwakeword(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "onnxruntime", None)  # voicute dead
    eng = create_wake_engine(
        {"voicute_model": str(make_zip_bundle(tmp_path))},
        oww_listener_factory=FakeSttListener)
    assert isinstance(eng, OpenWakeWordAdapter)


def test_create_raises_with_all_reasons(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    monkeypatch.setitem(sys.modules, "openwakeword", None)
    with pytest.raises(WakeWordError) as excinfo:
        create_wake_engine({"voicute_model": str(tmp_path / "nope.zip")})
    msg = str(excinfo.value)
    assert "voicute" in msg and "openwakeword" in msg


def test_probe_engines_reports_both(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    monkeypatch.setitem(sys.modules, "openwakeword", None)
    statuses = probe_engines({"voicute_model": str(tmp_path / "nope.zip")})
    assert [s.name for s in statuses] == ["voicute", "openwakeword"]
    assert all(not s.available and s.reason for s in statuses)


def test_feed_frame_contract(tmp_path):
    # Empty frame: Voicute short-circuits before any model work.
    eng = VoicuteAdapter(model_path=make_zip_bundle(tmp_path))
    assert eng.feed_frame(b"") is None
    # Non-bytes input is a TypeError on the shared base contract.
    eng2 = OpenWakeWordAdapter(listener_factory=FakeSttListener)
    with pytest.raises(TypeError):
        eng2.feed_frame("hey jarvis")  # type: ignore[arg-type]


def test_detection_is_frozen(tmp_path):
    det = WakeDetection(engine="voicute", keyword="Jarvis", score=0.9,
                        at=1.0, frame_index=3)
    with pytest.raises(Exception):
        det.score = 0.1  # frozen dataclass refuses
