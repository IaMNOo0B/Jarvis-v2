"""Builder Team B — VOICE PACK tests.

Covers the four mega-scan steals implemented in this pass:
  1. Interruption watermark   (jarvis.tts SpeechQueue + Speaker.interrupt)
  2. Echo salvage             (jarvis.voice_loop BargeInDetector.salvage)
  3. Speech policy pack       (jarvis.speech_policy clean_for_tts)
  4. Interrupt note           (jarvis.voice_loop speak_text -> session events)

Everything is faked: no audio hardware, no real engines.
"""

import time

import pytest

from jarvis import tts as tts_mod
from jarvis.speech_policy import (
    CHUNK_CHARS,
    FIRST_CHUNK_CHARS,
    chunk_for_speech,
    clean_for_tts,
    redact_secrets,
    register_secret,
    split_clauses,
    strip_markdown,
)
from jarvis.tts import Engine, Speaker, SpeechQueue, SKIPPED, INTERRUPTED, SPOKEN
from jarvis.voice_loop import BargeInDetector, VoiceLoop


# =========================================================================== #
# Fakes
# =========================================================================== #

class RecordingEngine(Engine):
    """Fast engine that records which sentences actually started playing."""

    name = "recording"

    def __init__(self, word_delay: float = 0.01) -> None:
        self.word_delay = word_delay
        self.started: list = []

    def speak_sentence(self, text, on_word):
        self.started.append(text)
        for i in range(len(text.split())):
            time.sleep(self.word_delay)
            on_word(i)


class DeafEngine(Engine):
    """A stuck backend: never reports words, never notices the stop flag.
    Models the worst case the watermark must survive BY CONSTRUCTION."""

    name = "deaf"

    def __init__(self, sentence_delay: float = 0.4) -> None:
        self.sentence_delay = sentence_delay
        self.started: list = []

    def speak_sentence(self, text, on_word):
        self.started.append(text)
        time.sleep(self.sentence_delay)


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


def make_loop(**kw):
    defaults = dict(
        mic_fn=lambda: None,
        vad_fn=lambda c: False,
        wake_fn=lambda c: {"detected": False},
        stt_fn=lambda a: {"text": "", "words": [], "confidence": 0.0},
        brain_fn=lambda t: "ok.",
        session_store=FakeStore(),
    )
    defaults.update(kw)
    return VoiceLoop(**defaults)


# =========================================================================== #
# 1. Interruption watermark — SpeechQueue unit behaviour
# =========================================================================== #

class TestSpeechQueue:
    def test_ids_are_monotonic_and_never_recycled(self):
        q = SpeechQueue()
        first = q.enqueue(["a one", "b two"])
        second = q.enqueue(["c three"])
        assert [c.chunk_id for c in first] == [1, 2]
        assert [c.chunk_id for c in second] == [3]
        assert [c.text for c in first] == ["a one", "b two"]
        assert [c.sentence_idx for c in first] == [0, 1]

    def test_interrupt_freezes_pending(self):
        q = SpeechQueue()
        chunks = q.enqueue(["a", "b", "c"])
        wm = q.interrupt()
        assert wm == 3
        assert q.watermark == 3
        assert q.pending() == []
        assert all(q.get(c.chunk_id) is None for c in chunks)

    def test_new_chunks_after_interrupt_are_not_frozen(self):
        q = SpeechQueue()
        q.enqueue(["a", "b"])
        q.interrupt()
        fresh = q.enqueue(["c"])
        assert fresh[0].chunk_id == 3
        assert q.get(3) is fresh[0]
        assert q.pending() == fresh

    def test_interrupt_is_idempotent_when_idle(self):
        q = SpeechQueue()
        assert q.interrupt() == 0
        assert q.watermark == 0

    def test_consume_and_drain(self):
        q = SpeechQueue()
        chunks = q.enqueue(["a", "b", "c"])
        q.consume(chunks[0].chunk_id)
        assert [c.chunk_id for c in q.pending()] == [2, 3]
        q.drain()
        assert q.pending() == []
        # Drain forgets pending but never lowers the watermark.
        assert q.watermark == 0
        q.enqueue(["x"])
        q.interrupt()
        q.drain()
        assert q.watermark == 4


# =========================================================================== #
# 1b. Interruption watermark — Speaker integration
# =========================================================================== #

class TestSpeakerWatermark:
    def test_speak_assigns_chunk_ids_to_utterance(self):
        eng = RecordingEngine(word_delay=0.0)
        spk = Speaker(lambda s: None, engine=eng)
        utt = spk.speak("One sentence here. Another one follows.")
        assert utt.wait(3)
        assert utt.chunk_ids == [1, 2]
        assert utt.sentence_status == [SPOKEN, SPOKEN]

    def test_interrupt_freezes_the_backlog(self):
        eng = RecordingEngine(word_delay=0.05)
        spk = Speaker(lambda s: None, engine=eng)
        utt = spk.speak("One alpha bravo. Two charlie delta. Three echo fox.")
        while utt.words_spoken < 1:
            time.sleep(0.005)
        returned = spk.interrupt()
        assert returned is utt
        assert utt.wait(3)
        # Only the first sentence ever reached the engine; the rest of
        # the utterance was frozen by the watermark + stop flag.
        assert eng.started == ["One alpha bravo."]
        assert utt.sentence_status == [INTERRUPTED, SKIPPED, SKIPPED]
        assert spk._queue.watermark == utt.chunk_ids[-1]
        assert spk._audio_emitted == utt.chunk_ids[-1]
        assert spk.dropped_chunk_ids() == utt.chunk_ids

    def test_speak_after_interrupt_is_not_muted(self):
        """The watermark must never freeze FUTURE chunks (anti-C-V2)."""
        eng = RecordingEngine(word_delay=0.05)
        spk = Speaker(lambda s: None, engine=eng)
        utt = spk.speak("One alpha bravo. Two charlie delta.")
        while utt.words_spoken < 1:
            time.sleep(0.005)
        spk.interrupt()
        assert utt.wait(3)
        utt2 = spk.speak("Fresh start here.")
        assert utt2.wait(3)
        assert utt2.sentence_status == [SPOKEN]
        assert eng.started[-1] == "Fresh start here."
        assert min(utt2.chunk_ids) > max(utt.chunk_ids)

    def test_watermark_stops_backlog_when_worker_ignores_stop(self):
        """By construction: a worker that never checks the stop flag
        still cannot speak stale chunks — their ids are frozen."""
        eng = DeafEngine(sentence_delay=0.4)
        spk = Speaker(lambda s: None, engine=eng)
        utt = spk.speak("First deaf one. Second deaf two. Third deaf three.")
        time.sleep(0.1)  # first sentence is mid-"playback"
        spk.interrupt()
        assert utt.wait(5)
        assert eng.started == ["First deaf one."]
        assert utt.sentence_status[1:] == [SKIPPED, SKIPPED]


# =========================================================================== #
# 2. Echo salvage
# =========================================================================== #

SPOKEN8 = "one two three four five six seven eight"


class TestEchoSalvage:
    def test_salvage_strips_echo_prefix_keeps_tail(self):
        out = BargeInDetector.salvage(
            "the weather is sunny and kal barish hogi",
            "the weather is sunny today")
        assert out == "and kal barish hogi"

    def test_salvage_of_pure_echo_is_empty(self):
        assert BargeInDetector.salvage(
            "the weather is", "the weather is sunny today") == ""

    def test_salvage_is_iterative_over_repeated_words(self):
        assert BargeInDetector.salvage(
            "the the real question", "the report is ready") == "real question"

    def test_salvage_empty_inputs(self):
        assert BargeInDetector.salvage("", "anything") == ""
        assert BargeInDetector.salvage("hello there", "") == "hello there"

    def test_echo_with_long_tail_interrupts_with_salvage(self):
        d = BargeInDetector()
        verdict = d.check(
            "one two three four five six seven zulu yankee xray", SPOKEN8)
        assert verdict == "interrupt"
        assert d.last_salvage == "zulu yankee xray"
        assert d.pop_salvage() == "zulu yankee xray"
        assert d.pop_salvage() == ""  # popped means popped

    def test_echo_with_short_tail_is_ignored_not_interrupted(self):
        d = BargeInDetector()
        assert d.check(
            "one two three four five six seven zulu yankee", SPOKEN8) == "ignore"

    def test_salvaged_words_accumulate_across_partials(self):
        d = BargeInDetector()
        assert d.check(
            "one two three four five six seven jaldi", SPOKEN8) == "ignore"
        assert d.check(
            "one two three four five six seven jaldi karo abhi",
            SPOKEN8) == "interrupt"
        assert d.last_salvage == "jaldi karo abhi"

    def test_salvage_disabled_falls_back_to_plain_echo(self):
        d = BargeInDetector(salvage=False)
        assert d.check(
            "one two three four five six seven zulu yankee xray",
            SPOKEN8) == "echo"

    def test_pure_echo_still_echo_with_salvage_on(self):
        d = BargeInDetector()
        assert d.check("never mind the rain",
                       "never mind the rain") == "echo"

    def test_loop_interrupt_text_is_the_salvaged_tail(self):
        """End to end: the brain must receive the user's real words,
        not a transcript that is 70% our own voice."""
        calls = [0]

        def partial():
            calls[0] += 1
            if calls[0] == 7:
                return ("alpha bravo charlie delta echo foxtrot golf "
                        "zulu yankee xray")
            return None

        loop = make_loop(partial_fn=partial)
        out = loop.speak_text(
            "alpha bravo charlie delta echo foxtrot golf hotel india juliet",
            session_id="s")
        assert out.status == "interrupted"
        assert out.spoken_text == "alpha bravo charlie delta echo foxtrot golf"
        assert out.interrupt_text == "zulu yankee xray"


# =========================================================================== #
# 3. Speech policy pack
# =========================================================================== #

class TestSpeechPolicy:
    def test_code_fence_content_never_spoken(self):
        out = clean_for_tts("Dekho:\n```python\nimport os\nprint(1)\n```\nHo gaya.")
        joined = " ".join(out)
        assert "import os" not in joined and "print" not in joined
        assert "Dekho" in joined and "Ho gaya" in joined

    def test_inline_code_and_bold_keep_words_lose_syntax(self):
        out = clean_for_tts("Use `pip install` **right now** please")
        assert out == ["Use pip install right now please"]
        joined = out[0]
        assert "`" not in joined and "*" not in joined

    def test_links_become_their_text_and_bare_urls_are_not_read(self):
        out = clean_for_tts(
            "see [the docs](https://x.com/a) and https://example.com/long here")
        joined = " ".join(out)
        assert "the docs" in joined
        assert "example.com" not in joined and "](" not in joined
        assert "link" in joined

    def test_headings_and_lists_lose_their_markers(self):
        out = clean_for_tts("# Report\n- pehla point\n- dusra point")
        joined = " ".join(out)
        assert "#" not in joined and "- " not in joined
        assert "pehla point" in joined and "dusra point" in joined

    def test_openai_key_redacted(self):
        key = "sk-" + "a" * 40
        out = clean_for_tts(f"Your key is {key} keep it safe")
        joined = " ".join(out)
        assert key not in joined
        assert "redacted secret" in joined

    def test_github_token_and_registered_secret_redacted(self):
        out = redact_secrets("token " + "ghp_" + "B" * 36 + " ok")
        assert "ghp_" not in out and "redacted secret" in out
        register_secret("builder-b-test", "swordfish-42-test")
        out2 = redact_secrets("the word is swordfish-42-test ok")
        assert "swordfish" not in out2 and "redacted secret" in out2

    def test_phone_and_aadhaar_redacted_as_detail(self):
        assert "redacted detail" in redact_secrets("call me at 9876543210 please")
        assert "9876543210" not in redact_secrets("call 9876543210")
        out = redact_secrets("My Aadhaar is 2345 6789 0123 thanks")
        assert "2345" not in out and "redacted detail" in out

    def test_luhn_valid_card_redacted(self):
        out = redact_secrets("card is 4111 1111 1111 1111.")
        assert "4111" not in out and "redacted secret" in out

    def test_ordinary_long_sentences_are_not_redacted(self):
        """The dcl's seed-phrase SHAPE heuristic (any 12 lowercase words)
        is deliberately NOT on the speech path — normal speech survives."""
        sentence = ("the rain in spain falls mainly on the plain today "
                    "and tomorrow also pakka wala scene hai bilkul sahi")
        assert redact_secrets(sentence) == sentence
        hinglish = "doctor ne kaha ki hospital jana padega aaram ke liye"
        assert redact_secrets(hinglish) == hinglish

    def test_first_chunk_is_asymmetrically_small(self):
        text = ("Namaste sir. " + " ".join(
            f"point{i} detail{i}" for i in range(40)) + ".")
        chunks = clean_for_tts(text)
        assert chunks[0] == "Namaste sir."
        assert len(chunks[0]) <= FIRST_CHUNK_CHARS
        assert all(len(c) <= CHUNK_CHARS + 10 for c in chunks[1:])

    def test_chunking_preserves_words_in_order(self):
        text = "Sir, aaj ka plan simple hai, pehle report, phir call, aakhir me rest."
        chunks = chunk_for_speech(text)
        assert " ".join(chunks) == " ".join(split_clauses(text))
        assert len(chunks) >= 2  # clauses actually drive the packing

    def test_split_clauses_keeps_delimiters(self):
        assert split_clauses("alpha, beta; gamma: delta") == [
            "alpha,", "beta;", "gamma:", "delta"]

    def test_empty_inputs(self):
        assert clean_for_tts("") == []
        assert clean_for_tts("   \n  ") == []
        assert strip_markdown("") == ""
        assert redact_secrets("") == ""
        assert split_clauses("") == []

    def test_hinglish_flows_through_intact(self):
        out = clean_for_tts(
            "Aapka kaam ho gaya hai, sir. Kal subah report bhej dunga.")
        assert out == ["Aapka kaam ho gaya hai, sir.",
                       "Kal subah report bhej dunga."]


# =========================================================================== #
# 4. Interrupt note
# =========================================================================== #

class TestInterruptNote:
    def test_note_records_last_sentence_actually_heard(self):
        calls = [0]

        def partial():
            calls[0] += 1
            if calls[0] == 4:   # first word of sentence 2 has been spoken
                return "completely novel interruption words"
            return None

        loop = make_loop(partial_fn=partial)
        out = loop.speak_text("First part here. Second part follows now.",
                              session_id="s")
        assert out.status == "interrupted"
        notes = loop._store.payloads("voice.interrupt_note")
        assert len(notes) == 1
        # The user heard sentence 1 in full, then exactly one word of 2.
        assert notes[0]["last_spoken_sentence"] == "Second"
        assert notes[0]["at_sentence"] == 1
        assert notes[0]["interrupt_text"] == "completely novel interruption words"
        assert out.last_spoken_sentence == "Second"

    def test_note_mid_first_sentence(self):
        calls = [0]

        def partial():
            calls[0] += 1
            if calls[0] == 3:
                return "fresh new words spoken"
            return None

        loop = make_loop(partial_fn=partial)
        out = loop.speak_text("alpha bravo charlie delta echo.",
                              session_id="s")
        assert out.status == "interrupted"
        notes = loop._store.payloads("voice.interrupt_note")
        assert len(notes) == 1
        assert notes[0]["last_spoken_sentence"] == "alpha bravo charlie"
        assert notes[0]["at_sentence"] == 0
        assert out.last_spoken_sentence == "alpha bravo charlie"

    def test_completed_turn_emits_no_interrupt_note(self):
        loop = make_loop()
        out = loop.speak_text("All good here.", session_id="s")
        assert out.status == "completed"
        assert "voice.interrupt_note" not in loop._store.types()
        assert out.last_spoken_sentence == ""
        # ...but the normal completion event still fires exactly as before.
        assert "voice.turn_completed" in loop._store.types()
