"""jarvis.stt — speech-to-text, energy VAD, wake word, mic input (v2 Wave 4).

The input half of the voice loop: MIC -> VAD -> WAKE -> COLLECT -> STT.
(BRAIN -> TTS -> SPEAKERS, the echo guard and barge-in are separate waves;
see learn-voice-loop-spec.md.)

All audio here is int16 little-endian PCM, mono, 16 kHz unless stated.

Honesty rules (non-negotiable):
  - NO audio or ML import at module top level. sounddevice, faster-whisper,
    openwakeword are imported LAZILY inside the methods that need them, so
    `import jarvis.stt` succeeds on a machine that has none of them.
  - Every missing optional dependency raises a typed error naming the exact
    pip package. An ImportError never leaks to the caller; nothing fails
    silently.
  - StubTranscriber / StubWake are for tests and dev only. They announce
    themselves LOUDLY on first use so canned data is never mistaken for a
    real model.
  - ONE VAD: the energy VAD in this module. faster-whisper's vad_filter is
    OFF by construction (spec M-V11: double VAD double-trims).
"""

from __future__ import annotations

import abc
import math
import struct
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

__all__ = [
    "STTError", "WakeError", "MicError",
    "SAMPLE_RATE", "FRAME_MS", "HANGOVER_MS", "MIN_SPEECH_MS",
    "vad_segments",
    "Transcriber", "StubTranscriber", "FasterWhisperTranscriber",
    "HinglishTranscriber", "TranscriberChain", "create_transcriber",
    "DEFAULT_HINGLISH_MODEL", "HINGLISH_PRIME_MODEL",
    "WakeListener", "StubWake", "OpenWakeWordListener",
    "MicStream",
]


# --------------------------------------------------------------------------- #
# Exceptions — every failure is typed, never swallowed, never faked.
# --------------------------------------------------------------------------- #
class STTError(Exception):
    """Speech-to-text failed (no audio, no backend, model error)."""


class WakeError(Exception):
    """Wake-word backend failed (missing package, bad model)."""


class MicError(Exception):
    """Microphone failed (missing package, no device, not open)."""


# --------------------------------------------------------------------------- #
# Constants — the VAD's timing contract (spec: 300 ms hangover, 200 ms min).
# --------------------------------------------------------------------------- #
SAMPLE_RATE = 16000
FRAME_MS = 20          # one VAD frame
HANGOVER_MS = 300      # silence tolerated inside an utterance
MIN_SPEECH_MS = 200    # shorter bursts are discarded, not transcribed

_FLOOR_MIN = 30.0      # RMS floor for digital silence (int16 units)
_FLOOR_MULT = 4.0      # speech threshold = max(floor * mult, _ABS_MIN)
_ABS_MIN = 60.0        # absolute energy floor so threshold is never ~0


# --------------------------------------------------------------------------- #
# Energy VAD — pure stdlib. Frame energy vs an adaptive noise floor.
# --------------------------------------------------------------------------- #
def _frame_rms(frame: bytes) -> float:
    n = len(frame) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", frame)
    return math.sqrt(sum(s * s for s in samples) / n)


def vad_segments(pcm_bytes: bytes,
                 sample_rate: int = SAMPLE_RATE) -> List[Tuple[float, float]]:
    """Split int16 mono PCM into speech segments [(start_s, end_s), ...].

    Pure stdlib: 20 ms frames, RMS energy vs an adaptive ambient floor
    (the floor learns only during silence, so loud speech can't drag the
    threshold up and cut itself off). 300 ms hangover merges pauses inside
    an utterance; bursts under 200 ms are dropped.

    NOTE: segments carry no pre-roll. The utterance collector keeps a
    500 ms ring buffer so onsets are never clipped (spec H-V6) — that is
    the collector's job, not the VAD's.
    """
    if sample_rate <= 0:
        raise STTError(f"bad sample_rate: {sample_rate}")
    if not pcm_bytes:
        return []

    frame_samples = max(1, sample_rate * FRAME_MS // 1000)
    frame_bytes = frame_samples * 2
    frame_dur = frame_samples / sample_rate
    hangover_frames = max(1, round(HANGOVER_MS / FRAME_MS))
    min_speech_frames = max(1, round(MIN_SPEECH_MS / FRAME_MS))

    n_frames = len(pcm_bytes) // frame_bytes
    segments: List[Tuple[float, float]] = []

    floor: Optional[float] = None
    in_speech = False
    seg_start = 0
    seg_last_speech = 0  # last frame that was actually speech (not hangover)
    hangover = 0

    for i in range(n_frames):
        energy = _frame_rms(pcm_bytes[i * frame_bytes:(i + 1) * frame_bytes])
        if floor is None:
            floor = max(energy, _FLOOR_MIN)
        threshold = max(floor * _FLOOR_MULT, _ABS_MIN)
        is_speech = energy > threshold

        if not in_speech:
            if is_speech:
                in_speech = True
                seg_start = i
                seg_last_speech = i
                hangover = hangover_frames
            else:
                # Silence: the floor learns the room. Speech never teaches
                # the floor, or loud speech would raise its own bar.
                floor = 0.95 * floor + 0.05 * energy
        else:
            if is_speech:
                seg_last_speech = i
                hangover = hangover_frames
            else:
                hangover -= 1
                if hangover <= 0:
                    in_speech = False
                    # Min-speech applies to SPEECH frames, not the hangover
                    # tail — a 100ms blip + 300ms tail is still a blip.
                    if seg_last_speech - seg_start + 1 >= min_speech_frames:
                        segments.append((seg_start * frame_dur, i * frame_dur))

    # Speech running into the end of the buffer still counts.
    if (in_speech
            and seg_last_speech - seg_start + 1 >= min_speech_frames):
        segments.append((seg_start * frame_dur, n_frames * frame_dur))

    return segments


# --------------------------------------------------------------------------- #
# Transcriber — pluggable backend. Result: {text, language, confidence}.
# --------------------------------------------------------------------------- #
class Transcriber(abc.ABC):
    @abc.abstractmethod
    def transcribe(self, pcm_bytes: bytes,
                   sample_rate: int = SAMPLE_RATE) -> Dict[str, Any]:
        """Return {"text": str, "language": str, "confidence": float}."""


class StubTranscriber(Transcriber):
    """Canned replies for tests/dev. LOUD on first use — never a real model."""

    def __init__(self, script: Optional[List[Dict[str, Any]]] = None) -> None:
        self._script = list(script) if script else [
            {"text": "", "language": "en", "confidence": 0.0}]
        self._i = 0
        self._warned = False

    def transcribe(self, pcm_bytes: bytes,
                   sample_rate: int = SAMPLE_RATE) -> Dict[str, Any]:
        if not self._warned:
            print("[stt] WARNING: StubTranscriber in use — canned replies, "
                  "NOT a real speech model.", file=sys.stderr)
            self._warned = True
        if not pcm_bytes:
            raise STTError("no audio provided")
        item = dict(self._script[self._i % len(self._script)])
        self._i += 1
        return item


def _resample_linear(audio: Any, src_rate: int, dst_rate: int) -> Any:
    """Linear resample of a float32 numpy array. numpy imported by caller."""
    import numpy as np
    if src_rate == dst_rate:
        return audio
    ratio = dst_rate / src_rate
    n_out = max(1, int(len(audio) * ratio))
    x_old = np.arange(len(audio), dtype=np.float64)
    x_new = np.linspace(0.0, float(len(audio) - 1), n_out)
    return np.interp(x_new, x_old, audio).astype(np.float32)


class FasterWhisperTranscriber(Transcriber):
    """faster-whisper STT. faster_whisper is imported LAZILY in _load().

    Defaults: `small` model, INT8 compute (the 2060 spec pick). vad_filter
    is OFF by construction — the energy VAD above is the single VAD
    (spec M-V11). Language auto-detects unless `language=` pins it;
    Hinglish reports the dominant language as detected by the model.

    ``RESULT_LANGUAGE``: when a subclass sets it, the result's language
    tag is that value instead of the model's detected language (the
    Hinglish engine knows its output script better than the detector).
    """

    RESULT_LANGUAGE: Optional[str] = None

    def __init__(self, model_name: str = "small",
                 compute_type: str = "int8", device: str = "auto",
                 vad_filter: bool = False,
                 language: Optional[str] = None) -> None:
        self._model_name = model_name
        self._compute_type = compute_type
        self._device = device
        self._vad_filter = vad_filter
        self._language = language
        self._model: Any = None

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise STTError(
                "faster-whisper is not installed. "
                "Install it with: pip install faster-whisper") from exc
        try:
            self._model = WhisperModel(
                self._model_name, device=self._device,
                compute_type=self._compute_type)
        except Exception as exc:
            # Missing/unconverted weights, no network, bad repo id — all
            # surface as ONE typed error so chains can fall through and
            # callers never see a raw huggingface/ctranslate traceback.
            raise STTError(
                f"could not load speech model {self._model_name!r}: "
                f"{type(exc).__name__}: {exc}") from exc

    def transcribe(self, pcm_bytes: bytes,
                   sample_rate: int = SAMPLE_RATE) -> Dict[str, Any]:
        if not pcm_bytes:
            raise STTError("no audio provided")
        self._load()
        import numpy as np  # noqa: E402  (ships with faster-whisper)
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        audio = audio / 32768.0
        audio = _resample_linear(audio, sample_rate, SAMPLE_RATE)

        segments, info = self._model.transcribe(
            audio, language=self._language, vad_filter=self._vad_filter)
        texts: List[str] = []
        logprobs: List[float] = []
        for seg in segments:
            texts.append(seg.text)
            logprobs.append(seg.avg_logprob)
        text = " ".join("".join(texts).split())
        language = self.RESULT_LANGUAGE or (
            getattr(info, "language", None) or "unknown")
        confidence = (sum(math.exp(min(lp, 0.0)) for lp in logprobs)
                      / len(logprobs)) if logprobs else 0.0
        return {"text": text, "language": language,
                "confidence": round(confidence, 4)}


# --------------------------------------------------------------------------- #
# Hinglish engine — Oriserve Whisper-Hindi2Hinglish (team17's top steal).
#
# The only open model family trained FOR roman-script Hinglish output:
# on Oriserve's evals it roughly halves stock Whisper-Large-v3's WER on
# conversational Hinglish (team17-indic.md §1.1; numbers are the vendor's
# own [MC]). Roman output is the point: it is what the owner types, what
# the LLM reads best, and what jarvis.translit canonicalizes downstream.
# Transcripts are tagged "hi-Latn" (Hindi, Latin script) — never plain
# "hi", which downstream code reads as Devanagari Hindi.
#
# Weights are downloaded on the OWNER's PC via setup — never here:
#   Oriserve/Whisper-Hindi2Hinglish-Swift   ~0.29 GB  (default, always-on)
#   Oriserve/Whisper-Hindi2Hinglish-Prime   ~6.17 GB files (~1.6 GB VRAM
#                                           as CT2 int8; dictation tier)
# faster-whisper needs CTranslate2-format weights: if the hub repo lacks
# them, WhisperModel raises, _load() wraps it as STTError naming the
# model, and a TranscriberChain falls through to plain whisper — honest
# degradation, never a crash, never a silent fake.
# --------------------------------------------------------------------------- #
DEFAULT_HINGLISH_MODEL = "Oriserve/Whisper-Hindi2Hinglish-Swift"
HINGLISH_PRIME_MODEL = "Oriserve/Whisper-Hindi2Hinglish-Prime"


class HinglishTranscriber(FasterWhisperTranscriber):
    """Hinglish-first STT: Oriserve Hindi2Hinglish via faster-whisper.

    Decoding is pinned to language="hi" (the model is Hindi-specific;
    auto-detect only wastes its strength). Output text is roman-script
    Hinglish; the result language tag is "hi-Latn".
    """

    RESULT_LANGUAGE = "hi-Latn"

    def __init__(self, model_name: str = DEFAULT_HINGLISH_MODEL,
                 compute_type: str = "int8", device: str = "auto",
                 language: Optional[str] = "hi") -> None:
        super().__init__(model_name=model_name, compute_type=compute_type,
                         device=device, vad_filter=False, language=language)


class TranscriberChain(Transcriber):
    """Ordered fallback: try each backend, degrade loudly, never crash.

    A backend that raises STTError (missing dep, missing weights) is
    marked dead for the chain's lifetime — a missing model must not be
    re-attempted (and re-download-checked) on every utterance. Every
    fall-through prints WHY to stderr; the chain never pretends a lesser
    engine is the one that was asked for. ``active_name`` reports which
    backend produced the last transcript (None before any success).
    """

    def __init__(self, backends: List[Tuple[str, Transcriber]]) -> None:
        if not backends:
            raise STTError("TranscriberChain needs at least one backend")
        self._backends = list(backends)
        self._dead: set = set()
        self.active_name: Optional[str] = None

    @property
    def backend_names(self) -> List[str]:
        return [name for name, _ in self._backends]

    def transcribe(self, pcm_bytes: bytes,
                   sample_rate: int = SAMPLE_RATE) -> Dict[str, Any]:
        if not pcm_bytes:
            raise STTError("no audio provided")
        failures: List[str] = []
        for name, backend in self._backends:
            if name in self._dead:
                continue
            try:
                result = backend.transcribe(pcm_bytes, sample_rate)
            except STTError as exc:
                self._dead.add(name)
                failures.append(f"{name}: {exc}")
                print(f"[stt] engine {name!r} unavailable ({exc}) — "
                      f"falling through to the next engine.",
                      file=sys.stderr)
                continue
            self.active_name = name
            return result
        raise STTError(
            "all speech engines failed: " + "; ".join(failures))


def create_transcriber(engine: str = "auto",
                       hinglish_model: str = DEFAULT_HINGLISH_MODEL,
                       whisper_model: str = "small") -> Transcriber:
    """Build a transcriber by engine name. The STT mirror of tts.pick_engine.

    "auto" (default): the chain hinglish -> whisper -> stub, in that
    order — the Hinglish engine when its weights are on the machine,
    stock whisper when they are not, the LOUD stub only when no real
    engine exists at all. Explicit names return exactly that engine and
    fail loudly (typed STTError) when it is unavailable — never a silent
    downgrade. Unknown names raise STTError.
    """
    if engine == "hinglish":
        return HinglishTranscriber(model_name=hinglish_model)
    if engine == "whisper":
        return FasterWhisperTranscriber(model_name=whisper_model)
    if engine == "stub":
        return StubTranscriber()
    if engine == "auto":
        return TranscriberChain([
            ("hinglish", HinglishTranscriber(model_name=hinglish_model)),
            ("whisper", FasterWhisperTranscriber(model_name=whisper_model)),
            ("stub", StubTranscriber()),
        ])
    raise STTError(
        f"unknown STT engine: {engine!r} "
        f"(expected 'auto', 'hinglish', 'whisper' or 'stub')")


# --------------------------------------------------------------------------- #
# Wake word — WakeListener base, StubWake for tests, openWakeWord for real.
# --------------------------------------------------------------------------- #
class WakeListener(abc.ABC):
    """Base: listen(pcm_chunk) -> True on a wake event.

    `last_score` always holds the most recent wake score (spec 5.2: the
    debug panel must show WHY "hey jarvis x5" did nothing).
    Anti-double-fire cooldown (spec 5.3, M-V12): default 1.5 s; the
    exponential backoff on repeated accepts belongs to the loop
    controller, not the listener. Clock is injectable for tests.
    """

    def __init__(self, threshold: float = 0.5, cooldown_s: float = 1.5,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self._clock = clock
        self._last_fire = float("-inf")
        self.last_score = 0.0

    @abc.abstractmethod
    def listen(self, pcm_chunk: bytes) -> bool:
        """Feed a PCM chunk; True exactly once per wake event."""

    def _cooldown_ok(self) -> bool:
        return (self._clock() - self._last_fire) >= self.cooldown_s

    def _fired(self) -> None:
        self._last_fire = self._clock()


class StubWake(WakeListener):
    """Test/dev wake: fires when trigger_phrase appears in injected text.

    `transcript_fn` supplies the current transcript (tests inject a mutable
    holder). LOUD on first use — never a real wake model.
    """

    def __init__(self, trigger_phrase: str = "hey jarvis",
                 transcript_fn: Optional[Callable[[], str]] = None,
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.trigger_phrase = trigger_phrase.lower()
        self._transcript_fn = transcript_fn or (lambda: "")
        self._warned = False

    def listen(self, pcm_chunk: bytes) -> bool:
        if not self._warned:
            print("[wake] WARNING: StubWake in use — phrase matching, "
                  "NOT a real wake-word model.", file=sys.stderr)
            self._warned = True
        text = (self._transcript_fn() or "").lower()
        hit = self.trigger_phrase in text
        self.last_score = 1.0 if hit else 0.0
        if hit and self._cooldown_ok():
            self._fired()
            return True
        return False


class OpenWakeWordListener(WakeListener):
    """openWakeWord wake-word detection. openwakeword imported LAZILY.

    The wake word is "Jarvis". openWakeWord ships no pre-trained bare
    `jarvis` model (only `hey_jarvis`), so the real model is a custom
    `jarvis.onnx` trained on the owner's voice — pass it as `model_path=`.
    Until then, `hey_jarvis` is the INTERIM fallback (it hears "hey jarvis";
    saying just "jarvis" may still trigger it, unreliably). The fallback
    is loud about being interim, never silent.
    Feeds the model 1280-sample (80 ms) frames; leftover bytes are buffered.
    """

    _FRAME_SAMPLES = 1280  # openWakeWord's expected frame at 16 kHz
    WAKE_WORD = "jarvis"

    def __init__(self, model_name: str = "jarvis",
                 model_path: Optional[str] = None,
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.model_name = model_name
        self._model_path = model_path
        self._oww: Any = None
        self._buf = bytearray()
        self._interim = model_path is None

    def _load(self) -> None:
        if self._oww is not None:
            return
        try:
            from openwakeword.model import Model as OWWModel
        except ImportError as exc:
            raise WakeError(
                "openwakeword is not installed. "
                "Install it with: pip install openwakeword") from exc
        kwargs: Dict[str, Any] = {}
        if self._model_path:
            kwargs["wakeword_model_paths"] = [self._model_path]
        else:
            # INTERIM: no trained "jarvis" model yet — use hey_jarvis.
            import sys
            print("[wake] INTERIM wake model: 'hey_jarvis' (pre-trained). "
                  "Train your 'jarvis' voice model for the real wake word.",
                  file=sys.stderr)
            self.model_name = "hey_jarvis"
        # No path -> openWakeWord's bundled pre-trained models (hey_jarvis).
        self._oww = OWWModel(**kwargs)

    def listen(self, pcm_chunk: bytes) -> bool:
        self._load()
        import numpy as np  # noqa: E402  (ships with openwakeword)
        self._buf.extend(pcm_chunk)
        frame_bytes = self._FRAME_SAMPLES * 2
        fired = False
        while len(self._buf) >= frame_bytes:
            frame = bytes(self._buf[:frame_bytes])
            del self._buf[:frame_bytes]
            audio = np.frombuffer(frame, dtype=np.int16)
            prediction = self._oww.predict(audio) or {}
            score = float(prediction.get(self.model_name, 0.0))
            self.last_score = score
            if score >= self.threshold and self._cooldown_ok():
                self._fired()
                fired = True
        return fired


# --------------------------------------------------------------------------- #
# Mic — lazy sounddevice, owned lifecycle (spec M-V18: always a fresh
# stream, never a restarted dead one; close() always releases).
# --------------------------------------------------------------------------- #
class MicStream:
    """16 kHz mono PCM chunks from the microphone.

    sounddevice is imported LAZILY inside open(). Usage:
        mic = MicStream()
        mic.open()
        try:
            for chunk in mic: ...   # bytes, chunk_ms long
        finally:
            mic.close()
    or `with MicStream() as mic:`.
    """

    def __init__(self, sample_rate: int = SAMPLE_RATE, channels: int = 1,
                 chunk_ms: int = 100,
                 device: Optional[Any] = None) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._chunk_frames = max(1, sample_rate * chunk_ms // 1000)
        self._device = device
        self._stream: Any = None

    @property
    def is_open(self) -> bool:
        return self._stream is not None

    def open(self) -> "MicStream":
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise MicError(
                "sounddevice is not installed. "
                "Install it with: pip install sounddevice") from exc
        if self._stream is not None:
            return self  # already open — idempotent, no double stream
        try:
            stream = sd.InputStream(
                samplerate=self._sample_rate, channels=self._channels,
                dtype="int16", blocksize=self._chunk_frames,
                device=self._device)
            stream.start()
        except Exception as exc:
            raise MicError(f"could not open microphone: {exc}") from exc
        self._stream = stream
        return self

    def __iter__(self):
        if self._stream is None:
            raise MicError("microphone is not open — call open() first")
        while True:
            data, _overflowed = self._stream.read(self._chunk_frames)
            yield bytes(data)

    def close(self) -> None:
        # Always releases, even if open() failed partway. Never raises.
        try:
            if self._stream is not None:
                try:
                    self._stream.stop()
                except Exception:
                    pass
                try:
                    self._stream.close()
                except Exception:
                    pass
        finally:
            self._stream = None

    def __enter__(self) -> "MicStream":
        return self.open()

    def __exit__(self, *exc: Any) -> None:
        self.close()
