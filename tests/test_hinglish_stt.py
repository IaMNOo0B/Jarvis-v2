"""Hinglish STT — Oriserve engine, fallback chain, engine factory.

No real models, no network: a fake `faster_whisper` module is injected
into sys.modules (the pattern test_stt.py uses for blocked deps). The
fake records how it was constructed and called, so the tests prove the
wiring — model id, pinned language, result tag — not just the shape.
"""

import sys
import types

import pytest

from jarvis.stt import (
    DEFAULT_HINGLISH_MODEL,
    HINGLISH_PRIME_MODEL,
    FasterWhisperTranscriber,
    HinglishTranscriber,
    STTError,
    StubTranscriber,
    Transcriber,
    TranscriberChain,
    create_transcriber,
)

AUDIO = b"\x01\x00" * 1600  # 100 ms of non-silent int16 PCM


class _Seg:
    def __init__(self, text, logprob=-0.1):
        self.text = text
        self.avg_logprob = logprob


class _Info:
    def __init__(self, language):
        self.language = language


class _FakeModel:
    """Stands in for faster_whisper.WhisperModel. Class-level records."""

    constructed = []      # (model_name, device, compute_type)
    calls = []            # transcribe kwargs dicts
    fail_models = set()   # model names whose construction raises

    def __init__(self, model_name, device=None, compute_type=None):
        type(self).constructed.append((model_name, device, compute_type))
        if model_name in type(self).fail_models:
            raise RuntimeError("weights are not in CT2 format")
        self.model_name = model_name

    def transcribe(self, audio, language=None, vad_filter=False):
        type(self).calls.append({"language": language,
                                 "vad_filter": vad_filter})
        if "Oriserve" in self.model_name:
            return ([_Seg("maa ko call kar do")], _Info("hi"))
        return ([_Seg("call mom please")], _Info("en"))


@pytest.fixture
def fake_whisper(monkeypatch):
    _FakeModel.constructed = []
    _FakeModel.calls = []
    _FakeModel.fail_models = set()
    module = types.SimpleNamespace(WhisperModel=_FakeModel)
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    return _FakeModel


@pytest.fixture
def no_whisper(monkeypatch):
    # `import faster_whisper` now raises ImportError (test_stt pattern).
    monkeypatch.setitem(sys.modules, "faster_whisper", None)


# --------------------------------------------------------------------------- #
# HinglishTranscriber
# --------------------------------------------------------------------------- #

def test_hinglish_defaults_are_swift_and_hi_latn(fake_whisper):
    t = HinglishTranscriber()
    result = t.transcribe(AUDIO)
    assert _FakeModel.constructed[0][0] == DEFAULT_HINGLISH_MODEL
    assert DEFAULT_HINGLISH_MODEL == "Oriserve/Whisper-Hindi2Hinglish-Swift"
    assert HINGLISH_PRIME_MODEL == "Oriserve/Whisper-Hindi2Hinglish-Prime"
    # Decoding pinned to Hindi; the single VAD stays the module's own.
    assert _FakeModel.calls[0] == {"language": "hi", "vad_filter": False}
    assert result["text"] == "maa ko call kar do"
    # The whole point of the engine: roman output tagged hi-Latn.
    assert result["language"] == "hi-Latn"
    assert result["confidence"] > 0.0


def test_hinglish_model_id_is_configurable(fake_whisper):
    t = HinglishTranscriber(model_name=HINGLISH_PRIME_MODEL)
    t.transcribe(AUDIO)
    assert _FakeModel.constructed[0][0] == HINGLISH_PRIME_MODEL


def test_hinglish_missing_dep_is_typed_never_crash(no_whisper):
    t = HinglishTranscriber()  # construction must NOT load anything
    with pytest.raises(STTError, match="pip install faster-whisper"):
        t.transcribe(AUDIO)


def test_hinglish_unloadable_weights_are_typed(fake_whisper):
    _FakeModel.fail_models = {DEFAULT_HINGLISH_MODEL}
    with pytest.raises(STTError, match="could not load speech model"):
        HinglishTranscriber().transcribe(AUDIO)


def test_plain_whisper_still_autodetects(fake_whisper):
    # The language= addition must not change the existing engine: no pin,
    # detected language passes through untagged.
    result = FasterWhisperTranscriber().transcribe(AUDIO)
    assert _FakeModel.calls[0]["language"] is None
    assert result["language"] == "en"


# --------------------------------------------------------------------------- #
# TranscriberChain + create_transcriber
# --------------------------------------------------------------------------- #

def test_chain_prefers_hinglish(fake_whisper):
    chain = create_transcriber("auto")
    assert isinstance(chain, TranscriberChain)
    assert chain.backend_names == ["hinglish", "whisper", "stub"]
    result = chain.transcribe(AUDIO)
    assert result["language"] == "hi-Latn"
    assert chain.active_name == "hinglish"


def test_chain_falls_to_whisper_when_hinglish_weights_bad(
        fake_whisper, capsys):
    _FakeModel.fail_models = {DEFAULT_HINGLISH_MODEL}
    chain = create_transcriber("auto")
    result = chain.transcribe(AUDIO)
    assert result["text"] == "call mom please"
    assert result["language"] == "en"
    assert chain.active_name == "whisper"
    # Degradation is LOUD, never silent.
    assert "hinglish" in capsys.readouterr().err


def test_chain_falls_to_stub_when_no_real_engine(no_whisper):
    chain = create_transcriber("auto")
    result = chain.transcribe(AUDIO)
    assert chain.active_name == "stub"
    assert "language" in result  # the stub's canned dict, announced loudly


def test_chain_dead_backend_not_retried(fake_whisper):
    _FakeModel.fail_models = {DEFAULT_HINGLISH_MODEL, "small"}
    chain = TranscriberChain([
        ("hinglish", HinglishTranscriber()),
        ("whisper", FasterWhisperTranscriber()),
        ("stub", StubTranscriber()),
    ])
    chain.transcribe(AUDIO)
    chain.transcribe(AUDIO)
    # Each dead engine was attempted exactly once across both calls.
    names = [c[0] for c in _FakeModel.constructed]
    assert names.count(DEFAULT_HINGLISH_MODEL) == 1
    assert names.count("small") == 1


def test_chain_empty_audio_rejected_before_any_backend():
    class _Counting(Transcriber):
        calls = 0

        def transcribe(self, pcm_bytes, sample_rate=16000):
            type(self).calls += 1
            return {"text": "x", "language": "en", "confidence": 1.0}

    backend = _Counting()
    chain = TranscriberChain([("counting", backend)])
    with pytest.raises(STTError, match="no audio"):
        chain.transcribe(b"")
    assert _Counting.calls == 0


def test_chain_all_fail_raises_with_reasons(no_whisper):
    chain = TranscriberChain([("whisper", FasterWhisperTranscriber())])
    with pytest.raises(STTError, match="all speech engines failed"):
        chain.transcribe(AUDIO)


def test_chain_requires_a_backend():
    with pytest.raises(STTError):
        TranscriberChain([])


def test_create_transcriber_explicit_engines():
    assert isinstance(create_transcriber("hinglish"), HinglishTranscriber)
    assert isinstance(create_transcriber("whisper"),
                      FasterWhisperTranscriber)
    assert isinstance(create_transcriber("stub"), StubTranscriber)
    custom = create_transcriber("hinglish",
                                hinglish_model=HINGLISH_PRIME_MODEL)
    assert custom._model_name == HINGLISH_PRIME_MODEL


def test_create_transcriber_unknown_engine_is_typed():
    with pytest.raises(STTError, match="unknown STT engine"):
        create_transcriber("magic")
