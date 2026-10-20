"""clean_for_tts wiring — the speech policy on the LIVE voice path.

jarvis.speech_policy.clean_for_tts existed as a pure module (Builder B)
but nothing called it. These tests pin the wiring in
jarvis.voice_loop.VoiceLoop.speak_text — the single choke point for all
speech: the Utterance Record is built from speakable_sentences(), so

  - markdown / code fences / URLs never reach the speakers,
  - secrets are redacted BEFORE they can be spoken (or heard by the mic),
  - spoken_text() — the only text the brain may remember — is the
    CLEANED text: exactly what left the speakers,
  - a sentence that cleans to nothing is skipped, and
  - a broken cleaner falls back to raw text: speech never breaks.

Everything is faked: no audio hardware, no real engines.
"""

from jarvis import voice_loop as vl
from jarvis.speech_policy import clean_for_tts as policy_clean
from jarvis.voice_loop import VoiceLoop, speakable_sentences


# --------------------------------------------------------------------------- #
# Fakes (same shapes as tests/test_voice_loop.py / test_builder_b_voice.py)
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

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.closed = False

    def read(self):
        if not self._chunks:
            return None
        return self._chunks.pop(0)

    def close(self):
        self.closed = True


def _vad(chunk):
    return chunk.startswith(b"v")


def make_loop(**kw):
    defaults = dict(
        mic_fn=lambda: FakeStream([]),
        vad_fn=_vad,
        wake_fn=lambda c: {"detected": False},
        stt_fn=lambda a: {"text": "", "words": [], "confidence": 0.0},
        brain_fn=lambda t: "ok.",
        session_store=FakeStore(),
    )
    defaults.update(kw)
    return VoiceLoop(**defaults)


def speech_chunks(n_sil_before=5, n_speech=10, n_sil_after=40):
    return [b"s"] * n_sil_before + [b"v"] * n_speech + [b"s"] * n_sil_after


# --------------------------------------------------------------------------- #
# The wiring unit: speakable_sentences
# --------------------------------------------------------------------------- #

class TestSpeakableSentences:
    def test_plain_sentences_pass_through(self):
        assert speakable_sentences("It is noon. The sky is clear.") == [
            "It is noon.", "The sky is clear."]

    def test_chunks_replace_the_raw_sentence_in_order(self):
        text = ("Sir, aaj ka plan simple hai, pehle report bhejni hai, "
                "phir client ko call karna hai, uske baad files check "
                "hongi, aur aakhir me hum rest karenge bilkul aaram se.")
        units = speakable_sentences(text)
        assert units == policy_clean(text)  # one raw sentence -> its chunks
        assert len(units) >= 2              # it really was re-chunked

    def test_sentence_cleaning_to_empty_contributes_nothing(self):
        assert speakable_sentences("```\nonly code here\n```") == []
        assert speakable_sentences(
            "Pehla point. ```\ncode only\n``` Dusra point.") == [
                "Pehla point.", "Dusra point."]


# --------------------------------------------------------------------------- #
# speak_text: what leaves the speakers is the CLEANED text
# --------------------------------------------------------------------------- #

class TestSpeakTextCleaning:
    def test_markdown_is_never_spoken(self):
        words = []
        loop = make_loop(audio_out=lambda w, si, wi: words.append(w))
        out = loop.speak_text(
            "Here is **bold** and `code` plus [the docs]"
            "(https://example.com/a) now.")
        assert out.status == "completed"
        assert out.spoken_text == "Here is bold and code plus the docs now."
        assert words == out.spoken_text.split()
        assert not any("*" in w or "`" in w or "http" in w for w in words)

    def test_code_fence_content_never_reaches_the_speakers(self):
        words = []
        loop = make_loop(audio_out=lambda w, si, wi: words.append(w))
        out = loop.speak_text(
            "Pehle ye dekho. ```python\nimport os\nprint(1)\n```\n"
            "Aur ho gaya.")
        assert out.status == "completed"
        assert out.spoken_text == "Pehle ye dekho. Aur ho gaya."
        assert "import" not in words and "os" not in words
        assert not any("print" in w for w in words)

    def test_secret_is_redacted_before_it_can_be_spoken(self):
        key = "sk-" + "a" * 40
        words = []
        loop = make_loop(audio_out=lambda w, si, wi: words.append(w))
        out = loop.speak_text(f"Your key is {key} keep it safe.")
        assert out.status == "completed"
        assert key not in out.spoken_text
        assert key not in words
        assert "redacted secret" in out.spoken_text

    def test_sentence_that_cleans_to_empty_is_skipped(self):
        words = []
        loop = make_loop(audio_out=lambda w, si, wi: words.append(w))
        out = loop.speak_text("Ho gaya sir. ```\nonly code here\n```")
        assert out.status == "completed"
        assert out.spoken_text == "Ho gaya sir."
        assert words == ["Ho", "gaya", "sir."]

    def test_reply_that_is_all_code_speaks_nothing(self):
        words = []
        loop = make_loop(audio_out=lambda w, si, wi: words.append(w))
        out = loop.speak_text("```\nonly code\n```", session_id="s")
        assert out.status == "completed"
        assert out.spoken_text == ""
        assert words == []
        assert "voice.turn_completed" in loop._store.types()

    def test_long_sentence_chunks_all_spoken_in_order(self):
        text = ("Sir, aaj ka plan simple hai, pehle report bhejni hai, "
                "phir client ko call karna hai, uske baad files check "
                "hongi, aur aakhir me hum rest karenge bilkul aaram se.")
        words = []
        loop = make_loop(audio_out=lambda w, si, wi: words.append(w))
        out = loop.speak_text(text)
        expected = policy_clean(text)
        assert len(expected) >= 2  # the sentence really was re-chunked
        assert words == " ".join(expected).split()
        assert out.spoken_text == " ".join(expected)

    def test_ordinary_and_hinglish_speech_is_unchanged(self):
        loop = make_loop()
        text = "Aapka kaam ho gaya hai, sir. Kal subah report bhej dunga."
        out = loop.speak_text(text)
        assert out.status == "completed"
        assert out.spoken_text == text


# --------------------------------------------------------------------------- #
# Interrupt accounting: the record holds the CLEANED text, history the raw
# --------------------------------------------------------------------------- #

class TestInterruptAccounting:
    def test_spoken_text_is_a_prefix_of_the_cleaned_reply(self):
        calls = [0]

        def partial():
            calls[0] += 1
            if calls[0] == 4:
                return "completely novel interruption words"
            return None

        loop = make_loop(partial_fn=partial)
        raw = "Here is **bold** news for you today sir."
        out = loop.speak_text(raw, session_id="s")
        assert out.status == "interrupted"
        # Cleaned words only — the markdown never left the speakers, so
        # it is not in what the brain may remember either.
        assert out.spoken_text == "Here is bold news"
        assert "**" not in out.spoken_text
        assert out.last_spoken_sentence == "Here is bold news"
        ev = loop._store.payloads("voice.turn_interrupted")[0]
        assert ev["spoken_text"] == out.spoken_text
        assert ev["full_reply"] == raw  # raw reply is logged, not remembered


# --------------------------------------------------------------------------- #
# Fallbacks: speech must never break, and never be silenced by the cleaner
# --------------------------------------------------------------------------- #

class TestFallbacks:
    def test_cleaner_raising_falls_back_to_raw(self, monkeypatch):
        def boom(text, **kw):
            raise RuntimeError("policy exploded")

        monkeypatch.setattr(vl, "clean_for_tts", boom)
        loop = make_loop()
        out = loop.speak_text("Raw **text** stays raw.")
        assert out.status == "completed"
        assert out.spoken_text == "Raw **text** stays raw."

    def test_cleaner_unavailable_falls_back_to_raw(self, monkeypatch):
        monkeypatch.setattr(vl, "clean_for_tts", None)
        loop = make_loop()
        out = loop.speak_text("Plain fallback speech.")
        assert out.status == "completed"
        assert out.spoken_text == "Plain fallback speech."


# --------------------------------------------------------------------------- #
# End to end: a full voice turn speaks the cleaned brain reply
# --------------------------------------------------------------------------- #

class TestRunTurnEndToEnd:
    def test_brain_reply_is_cleaned_on_the_way_to_the_speakers(self):
        words = []
        loop = make_loop(
            mic_fn=lambda: FakeStream(speech_chunks()),
            stt_fn=lambda a: {"text": "report ready hai",
                              "words": [], "confidence": 1.0},
            brain_fn=lambda t: ("Ho gaya sir. **Report** ready hai, "
                                "details https://example.com/x me hain."),
            audio_out=lambda w, si, wi: words.append(w),
        )
        out = loop.run_turn(session_id="s1")
        assert out.status == "completed"
        assert "**" not in out.spoken_text
        assert "example.com" not in out.spoken_text
        assert "link" in out.spoken_text  # bare URL became the word "link"
        assert out.spoken_text == (
            "Ho gaya sir. Report ready hai, details link me hain.")
        assert words == out.spoken_text.split()
