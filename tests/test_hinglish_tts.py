"""Kokoro Hindi voices — voice table, the lang="hi" route, lazy dep.

No kokoro package, no torch, no audio hardware: a fake `kokoro` module
is injected into sys.modules and importlib's find_spec is patched to
agree. The fake pipeline records (lang_code, text, voice) and renders a
short silent numpy buffer, so the tests prove WHICH voice a sentence is
routed to and that a real 24 kHz WAV reaches the player.
"""

import importlib.util
import sys
import types
import wave

import numpy as np
import pytest

from jarvis import tts as tts_mod
from jarvis.tts import (
    KOKORO_HINDI_VOICES,
    KOKORO_VOICES,
    KokoroEngine,
    TTSError,
    devanagari_ratio,
    is_hindi_heavy,
)


class _FakePipeline:
    instances = []

    def __init__(self, lang_code=None):
        self.lang_code = lang_code
        self.calls = []  # (text, voice)
        type(self).instances.append(self)

    def __call__(self, text, voice=None):
        self.calls.append((text, voice))
        yield ("g", "p", np.full(2400, 0.05, dtype=np.float32))


@pytest.fixture
def fake_kokoro(monkeypatch):
    _FakePipeline.instances = []
    module = types.SimpleNamespace(KPipeline=_FakePipeline)
    monkeypatch.setitem(sys.modules, "kokoro", module)
    real_find_spec = importlib.util.find_spec

    def _find_spec(name, *a, **kw):
        if name == "kokoro":
            return types.SimpleNamespace(name="kokoro")
        return real_find_spec(name, *a, **kw)

    monkeypatch.setattr(importlib.util, "find_spec", _find_spec)
    return _FakePipeline


@pytest.fixture
def no_kokoro(monkeypatch):
    monkeypatch.setitem(sys.modules, "kokoro", None)
    real_find_spec = importlib.util.find_spec

    def _find_spec(name, *a, **kw):
        if name == "kokoro":
            return None
        return real_find_spec(name, *a, **kw)

    monkeypatch.setattr(importlib.util, "find_spec", _find_spec)


class _Player:
    """Records each WAV's header DURING the call — the engine unlinks
    the temp file once playback finishes."""

    def __init__(self):
        self.paths = []
        self.headers = []  # (framerate, nframes)

    def __call__(self, path):
        self.paths.append(path)
        with wave.open(path, "rb") as wf:
            self.headers.append((wf.getframerate(), wf.getnframes()))


def _engine(fake_kokoro, **kw):
    kw.setdefault("player", _Player())
    return KokoroEngine(**kw)


# --------------------------------------------------------------------------- #
# Voice table
# --------------------------------------------------------------------------- #

def test_hindi_voice_table_is_team17s_four():
    assert KOKORO_HINDI_VOICES == {
        "hf_alpha": "f", "hf_beta": "f", "hm_omega": "m", "hm_psi": "m"}
    for name in KOKORO_HINDI_VOICES:
        assert KOKORO_VOICES[name][0] == "h"


# --------------------------------------------------------------------------- #
# The heuristic (script ratio + marker words)
# --------------------------------------------------------------------------- #

def test_devanagari_ratio():
    assert devanagari_ratio("hello world") == 0.0
    assert devanagari_ratio("नमस्ते") == 1.0
    assert devanagari_ratio("") == 0.0
    assert 0.0 < devanagari_ratio("meeting कल है") < 1.0


@pytest.mark.parametrize("text,heavy", [
    ("The meeting is at five o'clock.", False),
    ("मीटिंग पाँच बजे है।", True),
    ("bhai meeting kal hai, reminder laga do", True),
    ("ok", False),
    ("ka", False),               # one stray marker proves nothing
    ("Open the calendar please.", False),
])
def test_is_hindi_heavy(text, heavy):
    assert is_hindi_heavy(text) is heavy


# --------------------------------------------------------------------------- #
# Voice routing
# --------------------------------------------------------------------------- #

def test_english_keeps_owner_voice(fake_kokoro):
    eng = _engine(fake_kokoro)
    assert eng.voice_for_text("The meeting is at five.") == "af_heart"


def test_devanagari_routes_to_hindi_voice(fake_kokoro):
    eng = _engine(fake_kokoro)
    assert eng.voice_for_text("मीटिंग पाँच बजे है।") == "hf_alpha"


def test_roman_hinglish_routes_to_hindi_voice(fake_kokoro):
    eng = _engine(fake_kokoro)
    assert eng.voice_for_text(
        "bhai meeting kal hai, reminder laga do") == "hf_alpha"


def test_hindi_voice_gender_follows_default_voice(fake_kokoro):
    eng = _engine(fake_kokoro, voice="am_michael")
    assert eng.voice_for_text("मीटिंग पाँच बजे है।") == "hm_omega"
    assert eng.voice_for_text("The meeting is at five.") == "am_michael"


def test_hindi_voice_pin_and_validation(fake_kokoro):
    eng = _engine(fake_kokoro, hindi_voice="hf_beta")
    assert eng.voice_for_text("मीटिंग पाँच बजे है।") == "hf_beta"
    with pytest.raises(TTSError, match="Hindi voice"):
        _engine(fake_kokoro, hindi_voice="af_heart")


# --------------------------------------------------------------------------- #
# Synthesis end-to-end (fake pipeline, fake player)
# --------------------------------------------------------------------------- #

def test_speak_sentence_renders_hindi_through_hi_pipeline(fake_kokoro):
    player = _Player()
    eng = KokoroEngine(player=player)
    spoken = []
    eng.speak_sentence("मीटिंग पाँच बजे है", spoken.append)
    assert player.paths, "player never received a WAV"
    pipes = {p.lang_code: p for p in _FakePipeline.instances}
    assert pipes["h"].calls == [("मीटिंग पाँच बजे है", "hf_alpha")]
    assert spoken == [0, 1, 2, 3]  # one on_word per word, in order
    assert player.headers == [(24000, 2400)]  # a real 24 kHz WAV was played


def test_speak_sentence_english_uses_a_pipeline(fake_kokoro):
    eng = _engine(fake_kokoro)
    eng.speak_sentence("Hello there.", lambda i: None)
    pipes = {p.lang_code: p for p in _FakePipeline.instances}
    assert pipes["a"].calls == [("Hello there.", "af_heart")]


def test_speak_empty_text_is_a_noop(fake_kokoro):
    player = _Player()
    KokoroEngine(player=player).speak_sentence("   ", lambda i: None)
    assert player.paths == []
    assert _FakePipeline.instances == []


# --------------------------------------------------------------------------- #
# Lazy-dep honesty + pick_engine wiring
# --------------------------------------------------------------------------- #

def test_missing_package_is_typed_loud_error(no_kokoro):
    with pytest.raises(TTSError, match="pip install kokoro"):
        KokoroEngine(player=_Player())


def test_pick_engine_kokoro(fake_kokoro, monkeypatch):
    monkeypatch.setattr(tts_mod, "_default_player", lambda: _Player())
    assert isinstance(tts_mod.pick_engine("kokoro"), KokoroEngine)


def test_pick_engine_kokoro_missing_raises(no_kokoro):
    with pytest.raises(TTSError, match="kokoro"):
        tts_mod.pick_engine("kokoro")
