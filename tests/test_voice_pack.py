"""Tests for the Voice Pack (Team 7 steals, re-dispatched):

  1. Learned endpointing — jarvis.endpointing.EndpointPolicy wired
     into VoiceLoop._collect where TRAILING_SILENCE_S used to rule.
  2. Barge-in classification — classify_interrupt (backchannels never
     interrupt, strong commands cut immediately, EN + roman Hinglish
     + Devanagari) composing with the novel-word rule, plus the
     protoVoice 350ms hold-gate as episode probation.
  3. VAD guard — a recognizer stream dying mid-utterance preserves
     the partial utterance and logs the event instead of vanishing.

Every stage is faked; nothing touches real audio hardware.
"""
from datetime import date
from pathlib import Path

import pytest

from jarvis.endpointing import (
    MAX_THRESHOLD_S,
    MIN_THRESHOLD_S,
    EndpointPolicy,
)
from jarvis.voice_loop import (
    BARGE_HOLD_GATE_S,
    TRAILING_SILENCE_S,
    InterruptHoldGate,
    VoiceLoop,
    classify_interrupt,
)

REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Fakes (mirroring tests/test_voice_loop.py)
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


class ExplodingStream(FakeStream):
    """A recognizer stream that dies after `explode_after` reads."""

    def __init__(self, chunks, explode_after):
        super().__init__(chunks)
        self._explode_after = explode_after
        self._reads = 0

    def read(self):
        self._reads += 1
        if self._reads > self._explode_after:
            raise RuntimeError("recognizer reset")
        return super().read()


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
        date_fn=lambda: date(2026, 10, 20),
        session_store=FakeStore(),
    )
    defaults.update(kw)
    loop = VoiceLoop(**defaults)
    loop._fake_clock = clock
    return loop


def counted_partial(script):
    """partial_fn returning script[call#] (1-based), None past the end."""
    calls = [0]

    def partial():
        calls[0] += 1
        if calls[0] <= len(script):
            return script[calls[0] - 1]
        return None

    return partial


# --------------------------------------------------------------------------- #
# 1. EndpointPolicy: the learned-threshold math
# --------------------------------------------------------------------------- #

class TestEndpointPolicyMath:
    def test_fresh_policy_starts_at_seed(self):
        assert EndpointPolicy().threshold_s == 0.5
        assert EndpointPolicy(seed_s=0.7).threshold_s == 0.7
        assert EndpointPolicy().observations == 0

    def test_ema_math_pauses_fed_threshold_moves(self):
        p = EndpointPolicy()
        p.observe_pause(2.0)
        # EMA alpha 0.9: 0.9*2.0 + 0.1*0.5 = 1.85 — the owner's long
        # pauses pull the threshold UP toward their rhythm.
        assert p.learned_s == pytest.approx(1.85)
        assert p.threshold_s == pytest.approx(1.85)
        p.observe_pause(0.4)
        # 0.9*0.4 + 0.1*1.85 = 0.545 — short pauses pull it back down.
        assert p.learned_s == pytest.approx(0.545)
        assert p.threshold_s == pytest.approx(0.545)
        assert p.observations == 2

    def test_threshold_never_exceeds_hard_clamp(self):
        p = EndpointPolicy()
        for _ in range(5):
            p.observe_pause(100.0)  # absurd input, clamped as a sample
        # The EMA converges on the clamp from below, never past it;
        # the exact 3.0 is reached via the false-EOT floor (next test
        # class) — max_delay is a clamp, not a learned value.
        assert 2.99 < p.threshold_s <= MAX_THRESHOLD_S == 3.0

    def test_threshold_never_below_floor(self):
        p = EndpointPolicy()
        for _ in range(50):
            p.observe_pause(0.05)
        assert p.learned_s < MIN_THRESHOLD_S
        assert p.threshold_s == MIN_THRESHOLD_S == 0.3

    def test_false_eot_ratchets_the_floor(self):
        p = EndpointPolicy()
        p.observe_false_eot(2.5)
        assert p.floor_s == 2.5
        assert p.threshold_s == 2.5  # floor wins over the EMA (2.3)
        for _ in range(10):
            p.observe_pause(0.4)  # short pauses drag the EMA down...
        assert p.learned_s < 1.0
        assert p.threshold_s == 2.5  # ...but the floor NEVER sinks

    def test_false_eot_floor_clamped_at_max(self):
        p = EndpointPolicy()
        p.observe_false_eot(99.0)
        assert p.floor_s == MAX_THRESHOLD_S
        assert p.threshold_s == MAX_THRESHOLD_S

    def test_garbage_observations_ignored(self):
        p = EndpointPolicy()
        for bad in (0, -1.5, None, "soon"):
            p.observe_pause(bad)
            p.observe_false_eot(bad)
        assert p.observations == 0
        assert p.threshold_s == 0.5


class TestEndpointPolicyPersistence:
    def test_roundtrip_through_data_dir(self, tmp_path):
        p1 = EndpointPolicy(data_dir=tmp_path)
        p1.observe_pause(2.0)
        p1.observe_false_eot(2.5)
        assert (tmp_path / "endpointing.json").exists()
        p2 = EndpointPolicy(data_dir=tmp_path)
        assert p2.threshold_s == p1.threshold_s == 2.5
        assert p2.floor_s == 2.5
        assert p2.learned_s == pytest.approx(p1.learned_s)
        assert p2.observations == 2

    def test_corrupt_state_falls_back_to_defaults(self, tmp_path):
        (tmp_path / "endpointing.json").write_text("not json {{{")
        p = EndpointPolicy(data_dir=tmp_path)  # no raise
        assert p.threshold_s == 0.5
        (tmp_path / "endpointing.json").write_text(
            '{"ema_s": 99.0, "floor_s": -1, "observations": 3}')
        p = EndpointPolicy(data_dir=tmp_path)  # out-of-range: rejected
        assert p.threshold_s == 0.5

    def test_no_data_dir_means_no_files(self, tmp_path):
        p = EndpointPolicy()
        p.observe_pause(2.0)  # save() is a no-op without a data dir
        assert p.threshold_s == pytest.approx(1.85)


# --------------------------------------------------------------------------- #
# 1b. Endpointing wired into the capture path
# --------------------------------------------------------------------------- #

class TestEndpointingWiring:
    def test_fresh_loop_behaves_like_the_old_constant(self):
        loop = make_loop()
        assert loop.endpoint_policy is not None
        assert loop._endpoint_threshold() == TRAILING_SILENCE_S == 0.7

    def test_threshold_fallback_without_policy(self):
        loop = make_loop()
        loop.endpoint_policy = None
        assert loop._endpoint_threshold() == TRAILING_SILENCE_S

    def test_collect_uses_the_learned_threshold(self, tmp_path):
        # Pre-teach the policy: one long pause -> EMA 2.66s.
        teacher = EndpointPolicy(data_dir=tmp_path)
        teacher.observe_pause(2.9)
        assert teacher.threshold_s == pytest.approx(2.66)

        stream = [b"v"] * 10 + [b"s"] * 60 + [b"v"] * 10 + [b"s"] * 200
        learned = make_loop(data_dir=tmp_path)
        assert learned.endpoint_policy.threshold_s == pytest.approx(2.66)
        got = learned._collect(FakeStream(list(stream)))
        # The 60-chunk (1.2s) silence gap — fatal under the old 0.7s
        # constant — is ridden through: the second speech burst is in.
        assert len(got) >= 10 + 60 + 10

        fresh = make_loop()
        got = fresh._collect(FakeStream(list(stream)))
        # Seed behavior: endpoint inside the first silence run
        # (10 speech + ~35 silence chunks at 0.02s each).
        assert 43 <= len(got) <= 47

    def test_false_eot_learned_across_collections(self, tmp_path):
        clock = [0.0]
        loop = make_loop(clock=clock, data_dir=tmp_path)
        # Turn 1: speech, endpoint at the seed 0.7s of trailing silence.
        loop._collect(FakeStream([b"v"] * 5 + [b"s"] * 40))
        base = loop.endpoint_policy.threshold_s
        # The owner is back almost immediately (0.5s later): the
        # endpoint was FALSE — they were mid-thought.
        clock[0] += 0.5
        loop._collect(FakeStream([b"v"] * 5 + [b"s"] * 10))
        # Floor ratcheted to the full real pause (0.7 + 0.5 = 1.2s,
        # ± one 20ms chunk of float accumulation).
        assert loop.endpoint_policy.floor_s == pytest.approx(1.2, abs=0.03)
        assert loop.endpoint_policy.threshold_s >= 1.17 > base


# --------------------------------------------------------------------------- #
# 2. classify_interrupt: backchannels vs strong commands, three scripts
# --------------------------------------------------------------------------- #

class TestClassifyInterrupt:
    @pytest.mark.parametrize("text", [
        "yeah", "uh-huh", "hmm", "ok", "okay",
        "haan", "accha", "theek", "sahi", "theek hai", "haan ji",
        "जी", "हाँ", "अच्छा", "ठीक", "सही",
        "Haan!", "haan accha theek",  # pure backchannel, 3 words long
    ])
    def test_backchannels(self, text):
        assert classify_interrupt(text) == "backchannel"

    @pytest.mark.parametrize("text", [
        "stop", "cancel", "shut up", "never mind",
        "ruko", "bas", "chup", "band karo",
        "रुको", "बस", "बंद करो", "चुप",
        "okay stop",  # a backchannel token cannot shield a command
    ])
    def test_strong_commands(self, text):
        assert classify_interrupt(text) == "interrupt"

    @pytest.mark.parametrize("text", [
        "", "   ", "what is the weather today",
        "haan ek kaam karo",  # backchannel + real words = a command
        "theek hai ab batao result",
    ])
    def test_ignore(self, text):
        assert classify_interrupt(text) == "ignore"

    def test_pure_and_deterministic(self):
        for text in ("haan", "रुको", "haan accha theek", "whatever"):
            assert classify_interrupt(text) == classify_interrupt(text)


# --------------------------------------------------------------------------- #
# 2b. The hold-gate: unit timing + episode probation in the loop
# --------------------------------------------------------------------------- #

class TestInterruptHoldGate:
    def test_timing(self):
        clock = [100.0]
        gate = InterruptHoldGate(clock=lambda: clock[0])
        assert not gate.active and not gate.graduated()
        gate.begin()
        assert gate.active and gate.age_s() == 0.0
        clock[0] += BARGE_HOLD_GATE_S - 0.01
        assert not gate.graduated()
        clock[0] += 0.02
        assert gate.graduated()
        gate.clear()
        assert not gate.active and not gate.graduated()
        gate.begin()  # a fresh episode starts at zero again
        assert gate.age_s() == 0.0


class TestHoldGateInLoop:
    def test_blip_words_are_rolled_back(self):
        # "zulu yankee" (2 novel words, no verdict) appears, then the
        # candidate evaporates INSIDE the hold window (frozen clock):
        # its words must leave no trace in the accumulator.
        partial = counted_partial(
            ["zulu yankee", "zulu yankee", None, "xray", None])
        loop = make_loop(partial_fn=partial)
        out = loop.speak_text("one two three four five six seven.")
        assert out.status == "completed"  # "xray" alone is 1 novel word
        assert loop.detector._novel == set()  # blip + xray both rolled back

    def test_graduated_words_stay_in_the_accumulator(self):
        clock = [0.0]

        def audio_out(w, si, wi):
            clock[0] += 0.2  # ~one word of real speech time per poll

        partial = counted_partial(
            ["zulu", "zulu yankee", "zulu yankee", None, "xray"])
        loop = make_loop(clock=clock, partial_fn=partial,
                         audio_out=audio_out)
        out = loop.speak_text("one two three four five six seven eight.")
        # Episode graduated at poll 3 (age 0.4s > 0.35s): zulu+yankee
        # are real speech now. "xray" at poll 5 is the third novel
        # word -> a genuine interrupt.
        assert out.status == "interrupted"
        assert out.interrupt_text == "xray"
        assert out.spoken_text == "one two three four five"

    def test_backchannel_never_interrupts_even_with_novel_words(self):
        # "haan accha theek" = 3 novel words: the bare novel-word rule
        # would cut. Classification says backchannel — speech runs on.
        loop = make_loop(partial_fn=lambda: "haan accha theek")
        out = loop.speak_text("alpha bravo charlie delta echo.")
        assert out.status == "completed"
        assert out.spoken_text == "alpha bravo charlie delta echo."
        assert loop.detector._novel == set()  # and leaves no trace

    def test_backchannel_then_real_command_still_works(self):
        partial = counted_partial(
            ["haan", "haan accha", "haan accha theek", None,
             "zulu yankee xray"])
        loop = make_loop(partial_fn=partial)
        out = loop.speak_text("one two three four five six seven.")
        assert out.status == "interrupted"
        assert out.interrupt_text == "zulu yankee xray"
        assert out.spoken_text == "one two three four five"

    @pytest.mark.parametrize("word", ["ruko", "रुको", "बंद करो", "stop"])
    def test_strong_commands_cut_immediately(self, word):
        partial = counted_partial([None, word])
        loop = make_loop(partial_fn=partial)
        out = loop.speak_text("alpha bravo charlie delta echo.")
        assert out.status == "interrupted"
        assert out.spoken_text == "alpha bravo"  # cut at the 2nd word
        assert out.interrupt_text == word


# --------------------------------------------------------------------------- #
# 3. VAD guard: the recognizer dies, the words survive
# --------------------------------------------------------------------------- #

class TestVadGuard:
    def test_stream_death_mid_utterance_preserves_partial(self):
        heard = {}

        def stt(audio):
            heard["audio"] = audio
            return {"text": "half a sentence", "words": [],
                    "confidence": 0.5}

        stream = ExplodingStream([b"v"] * 10 + [b"s"] * 50,
                                 explode_after=12)
        loop = make_loop(mic_fn=lambda: stream, stt_fn=stt,
                         brain_fn=lambda t: "Noted, sir.")
        out = loop.run_turn(session_id="s1")
        assert out.status == "completed"      # the turn went on honestly
        assert heard["audio"] != b""          # partial audio reached STT
        assert len(heard["audio"]) == 12      # exactly what was heard
        ev = loop._store.payloads("voice.vad_guard")
        assert len(ev) == 1
        assert ev[0]["speech_seen"] is True
        assert ev[0]["chunks_kept"] == 12

    def test_stream_death_before_speech_is_a_quiet_no_speech(self):
        stream = ExplodingStream([b"v"] * 10, explode_after=0)
        loop = make_loop(mic_fn=lambda: stream)
        out = loop.run_turn(session_id="s1")
        assert out.status == "no_speech"
        ev = loop._store.payloads("voice.vad_guard")
        assert len(ev) == 1 and ev[0]["speech_seen"] is False

    def test_vad_error_streak_ends_collection_with_event(self):
        def dead_vad(chunk):
            raise RuntimeError("vad melted")

        loop = make_loop(vad_fn=dead_vad,
                         mic_fn=lambda: FakeStream([b"s"] * 100))
        out = loop.run_turn(session_id="s1")
        assert out.status == "no_speech"  # nothing heard, honestly said
        ev = loop._store.payloads("voice.vad_guard")
        assert len(ev) == 1 and ev[0]["stage"] == "vad"
