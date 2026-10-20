"""Text-to-speech for JARVIS v2 — the speaking half of the voice loop.

Design authority: ``learn-voice-loop-spec.md`` (Research Cycle 15).

The governing rule (AGENTS.md): *never fix a voice component in isolation —
always trace the full loop: mic → VAD → STT → brain → TTS → speakers → mic.*
Before touching this code, ask: "what does the NEXT stage hear/see because
of this change?"

Two v1 corpses this module exists to kill:

- **C-V1 (echo guard dead code):** the ``Speaker`` constructor REQUIRES an
  ``on_state`` callback — no default, no ``None``. A speaker without a guard
  cannot be constructed. The guard is wired at construction, never fetched.
- **C-V2 (barge-in permanent mute):** ``stop()`` clears its own stop flag.
  The flag is a signal, not a latch. The next ``speak()`` always works.

The brain never "says" audio — it commits text sentences. TTS consumes
sentences and reports word-level completion back into the Utterance Record
(Moshi pattern). ``words_spoken_text()`` is what the brain may remember;
unspoken words are never history (spec §3.3).
"""

from __future__ import annotations

import base64
from collections import deque
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
import wave
from typing import Callable, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class TTSError(Exception):
    """A TTS engine failed loudly. Never silent — the loop must announce
    degradation, never swallow it (spec §4.2, corpse H-V2)."""


class _StopRequested(Exception):
    """Internal: the speaker's stop flag was seen at a word boundary."""


# --------------------------------------------------------------------------- #
# Sentence splitting (Hinglish-safe)
# --------------------------------------------------------------------------- #

_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs",
    "etc", "eg", "ie", "no", "rs", "smt", "shri",
}
_DOT = "\x01"  # placeholder for protected periods


def split_sentences(text: str) -> List[str]:
    """Split text into sentences on . ! ? — without splitting abbreviations.

    Hinglish-safe: "Mr. Sharma ne kaha." stays one sentence. Single-letter
    initials (A.P.J.) are protected too.
    """
    if not text or not text.strip():
        return []
    s = text.strip()
    # Protect single-letter initials first: A.P.J. -> A<DOT>P<DOT>J<DOT>
    s = re.sub(r"\b([A-Za-z])\.", lambda m: m.group(1) + _DOT, s)
    # Protect abbreviations: Mr. -> Mr<DOT> (case preserved)
    for ab in sorted(_ABBREVIATIONS, key=len, reverse=True):
        s = re.sub(
            rf"\b{ab}\.",
            lambda m: m.group(0)[:-1] + _DOT,
            s,
            flags=re.IGNORECASE,
        )
    # Split on sentence-ending punctuation followed by whitespace/newlines.
    parts = re.split(r"(?<=[.!?…])\s+|\n+", s)
    out = []
    for p in parts:
        p = p.replace(_DOT, ".").strip()
        if p:
            out.append(p)
    return out


# --------------------------------------------------------------------------- #
# Utterance Record (Moshi pattern — spec §1.3)
# --------------------------------------------------------------------------- #

# Sentence lifecycle states (spec §1.1 TTS row).
QUEUED = "queued"
SPEAKING = "speaking"
SPOKEN = "spoken"
INTERRUPTED = "interrupted"
SKIPPED = "skipped"


class Utterance:
    """What the brain committed vs. what actually left the speakers.

    Fields: sentences, words_spoken, words_total, interrupted_at.
    ``words_spoken_text()`` is the ONLY text the brain may remember
    (spec §3.3: record what was spoken, not what was generated).
    """

    def __init__(self, sentences: List[str]) -> None:
        self.sentences: List[str] = list(sentences)
        self.sentence_status: List[str] = [QUEUED] * len(sentences)
        self.words_total: int = sum(len(s.split()) for s in sentences)
        self.words_spoken: int = 0
        self.interrupted_at: Optional[float] = None
        self.error: Optional[str] = None
        # word offset of each sentence in the global word stream
        self._offsets: List[int] = []
        off = 0
        for s in sentences:
            self._offsets.append(off)
            off += len(s.split())
        self._lock = threading.Lock()
        self._done = threading.Event()
        # Watermark bookkeeping: Speaker.speak fills this with the chunk
        # id of every sentence via SpeechQueue.enqueue, so post-interrupt
        # code can name exactly what was dropped.
        self.chunk_ids: List[int] = []

    def record_word(self, sentence_idx: int, word_idx: int) -> None:
        """Mark one word as having left the speakers."""
        with self._lock:
            self.words_spoken = self._offsets[sentence_idx] + word_idx + 1

    def words_spoken_text(self) -> str:
        """The words that actually left the speakers — for history."""
        words: List[str] = []
        for s in self.sentences:
            words.extend(s.split())
        with self._lock:
            n = self.words_spoken
        return " ".join(words[:n])

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Block until the utterance finishes (or is stopped)."""
        return self._done.wait(timeout)

    @property
    def finished(self) -> bool:
        return self._done.is_set()


# --------------------------------------------------------------------------- #
# Interruption watermark (ElevenLabs SDK pattern — spec item 1)
# --------------------------------------------------------------------------- #
#
# Every queued chunk gets a monotonic id. interrupt() sets a WATERMARK:
# any chunk with id <= watermark is stale — ghost audio (a stale worker
# speaking after the user barged in) and permanent mute (an old queue
# haunting the next speak) become IMPOSSIBLE BY CONSTRUCTION, because the
# playing path checks the watermark, never just the queue order.
#
# Monotonic ids are never recycled, so a watermark from an old utterance
# cannot accidentally kill a newer one. This is the guarantee the
# queue-order check could not give.


class Chunk:
    """One queued sentence with its watermark id."""

    __slots__ = ("chunk_id", "text", "sentence_idx")

    def __init__(self, chunk_id: int, text: str, sentence_idx: int) -> None:
        self.chunk_id = chunk_id
        self.text = text
        self.sentence_idx = sentence_idx


class SpeechQueue:
    """Watermarked queue of speech chunks. Thread-safe.

    Staleness is LAZY: interrupt() only moves the watermark; _run()
    consults it before speaking each chunk, and get()/pending() filter on
    it. A stale worker racing with a new speak() can only find stale
    chunks — it marks them SKIPPED and keeps going, never speaking them.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_id = 0
        self._watermark = 0          # nothing at/below this id may ever play
        self._pending: dict[int, Chunk] = {}

    def enqueue(self, sentences: List[str],
                start_idx: int = 0) -> List[Chunk]:
        """Assign fresh monotonic ids to one utterance's sentences.
        Also sweeps the pending map of chunks made stale since last time
        (bounded memory, no unbounded growth).

        ``start_idx`` is the sentence index of ``sentences[0]`` inside
        its utterance — nonzero only when the Speaker rebuilds a
        postponed item's watermark-frozen remainder with fresh ids, so
        the new chunks keep pointing at the right sentences."""
        chunks: List[Chunk] = []
        with self._lock:
            self._pending = {cid: c for cid, c in self._pending.items()
                             if cid > self._watermark}
            for i, text in enumerate(sentences):
                self._next_id += 1
                ch = Chunk(self._next_id, text, start_idx + i)
                self._pending[ch.chunk_id] = ch
                chunks.append(ch)
        return chunks

    def get(self, chunk_id: int) -> Optional[Chunk]:
        """The chunk, or None if it was dropped by a watermark."""
        with self._lock:
            if chunk_id <= self._watermark:
                return None
            return self._pending.get(chunk_id)

    def consume(self, chunk_id: int) -> None:
        """Mark a chunk played (or finished): forget it."""
        with self._lock:
            self._pending.pop(chunk_id, None)

    def interrupt(self) -> int:
        """Freeze: no chunk at or below the current high-water id may ever
        play again. Returns the new watermark. Idempotent and safe to call
        when nothing is queued (watermark just stays)."""
        with self._lock:
            if self._next_id > self._watermark:
                self._watermark = self._next_id
            return self._watermark

    def drain(self) -> None:
        """Forget everything pending (used at the start of a fresh speak)."""
        with self._lock:
            self._pending.clear()

    def pending(self) -> List[Chunk]:
        """Chunks that would still play: not stale, not consumed."""
        with self._lock:
            return [c for cid, c in sorted(self._pending.items())
                    if cid > self._watermark]

    @property
    def watermark(self) -> int:
        with self._lock:
            return self._watermark


# --------------------------------------------------------------------------- #
# Engine interface + engines
# --------------------------------------------------------------------------- #

# on_word: Callable[[word_index_within_sentence], None]
OnWord = Callable[[int], None]


class Engine:
    """Pluggable TTS engine. One method, one contract:

    ``speak_sentence(text, on_word)`` blocks until the sentence is done,
    calling ``on_word(i)`` after each word leaves the speakers. If the
    speaker's stop flag trips, ``on_word`` raises — let it propagate and
    clean up in a ``finally``.
    """

    name = "engine"

    def speak_sentence(self, text: str, on_word: OnWord) -> None:
        raise NotImplementedError


class StubEngine(Engine):
    """Test/dev engine: prints, sleeps ~50ms/word, reports completion.

    Never ships as the default silently — ``pick_engine`` warns loudly.
    """

    name = "stub"
    WORD_DELAY_S = 0.05

    def speak_sentence(self, text: str, on_word: OnWord) -> None:
        words = text.split()
        print(f"[tts:stub] {' '.join(words)}")
        for i, _w in enumerate(words):
            time.sleep(self.WORD_DELAY_S)
            on_word(i)


def _wav_duration_s(path: str) -> Optional[float]:
    """Read duration from a WAV header. None if unparseable."""
    try:
        with open(path, "rb") as f:
            hdr = f.read(44)
        if len(hdr) < 44 or hdr[0:4] != b"RIFF" or hdr[8:12] != b"WAVE":
            return None
        _fmt, channels, rate, _br, _ba, bits = struct.unpack("<HHIIHH", hdr[20:34])
        _dlen = struct.unpack("<I", hdr[40:44])[0]
        if rate == 0 or channels == 0:
            return None
        return _dlen / (rate * channels * (bits // 8))
    except (OSError, struct.error):
        return None


def _default_player() -> Callable[[str], None]:
    """Resolve a platform audio player for a .wav file. Raises TTSError."""
    if os.name == "nt":
        def _win_play(path: str) -> None:
            subprocess.run(
                ["powershell", "-c",
                 f'(New-Object System.Media.SoundPlayer "{path}").PlaySync()'],
                timeout=300, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return _win_play
    for bin_name, argv in (
        ("aplay", ["aplay", "-q"]),
        ("paplay", ["paplay"]),
        ("ffplay", ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]),
    ):
        if shutil.which(bin_name):
            def _nix_play(path: str, argv=argv) -> None:
                subprocess.run(argv + [path], timeout=300, check=False,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            return _nix_play
    raise TTSError(
        "No audio player found (looked for aplay, paplay, ffplay). "
        "TTS cannot produce sound on this machine.")


class PiperEngine(Engine):
    """Piper TTS (offline, local). Shells to the ``piper`` binary.

    Missing binary or missing voice model → clean TTSError, never silent
    (corpses H-V1/H-V2).
    """

    name = "piper"

    def __init__(self, model: Optional[str] = None,
                 player: Optional[Callable[[str], None]] = None) -> None:
        self.piper_bin = shutil.which("piper")
        if self.piper_bin is None:
            raise TTSError(
                "piper binary not found on PATH. Install piper-tts or pick "
                "another engine — TTS refuses to pretend it is working.")
        self.model = model
        self.player = player or _default_player()

    def _synthesize(self, text: str, out_path: str) -> None:
        if not self.model:
            raise TTSError(
                "PiperEngine has no voice model configured (.onnx path). "
                "Pass model=... — refusing to synthesize voiceless.")
        try:
            subprocess.run(
                [self.piper_bin, "--model", self.model,
                 "--output_file", out_path],
                input=text.encode("utf-8"),
                timeout=60, check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as e:
            raise TTSError(f"piper synthesis timed out: {e}")
        except subprocess.CalledProcessError as e:
            raise TTSError(f"piper synthesis failed (exit {e.returncode})")

    def speak_sentence(self, text: str, on_word: OnWord) -> None:
        words = text.split()
        if not words:
            return
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
        try:
            self._synthesize(text, wav_path)
            duration = _wav_duration_s(wav_path) or (len(words) / 2.5)
            # Play in the background; pace word callbacks over the duration.
            # on_word raises _StopRequested at a word boundary on stop() —
            # the finally below kills nothing because the player call is
            # synchronous per sentence; interrupt granularity ≈ one word.
            player_thread = threading.Thread(
                target=self.player, args=(wav_path,), daemon=True)
            player_thread.start()
            try:
                per_word = duration / len(words)
                for i in range(len(words)):
                    time.sleep(per_word)
                    on_word(i)
            finally:
                player_thread.join(timeout=2.0)
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass


class VoiceboxEngine(Engine):
    """Voicebox MCP server as an appliance (``127.0.0.1:17493/mcp``).

    v2 owns the loop (wake, barge-in, echo guard, Utterance Record);
    Voicebox owns synthesis. The boundary is explicit (spec §7).

    Latency gate (spec §7): sentence-level round-trips must measure ≤800ms
    on the target PC or the MCP boundary is rejected — measured at runtime,
    logged loudly, counted in ``latency_violations``.
    """

    name = "voicebox"
    DEFAULT_URL = "http://127.0.0.1:17493/mcp"
    LATENCY_GATE_MS = 800.0
    PROBE_TIMEOUT_S = 2.0

    def __init__(self, url: Optional[str] = None, voice: str = "default",
                 timeout_s: float = 15.0,
                 latency_gate_ms: float = LATENCY_GATE_MS,
                 player: Optional[Callable[[str], None]] = None) -> None:
        self.url = url or self.DEFAULT_URL
        self.voice = voice
        self.timeout_s = timeout_s
        self.latency_gate_ms = latency_gate_ms
        self.latency_violations = 0
        self.last_latency_ms: Optional[float] = None
        self.player = player  # only needed if the server returns audio bytes
        self._rpc("tools/list", {}, timeout=self.PROBE_TIMEOUT_S,
                  probe=True)  # raises TTSError if unreachable

    def _rpc(self, method: str, params: dict,
             timeout: Optional[float] = None, probe: bool = False) -> dict:
        body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        ).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=body,
            headers={"Content-Type": "application/json"})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(
                    req, timeout=timeout or self.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise TTSError(
                f"Voicebox MCP server not reachable at {self.url} ({e}). "
                f"Start voicebox first — TTS refuses to pretend it is working.")
        except json.JSONDecodeError as e:
            raise TTSError(f"Voicebox returned garbage: {e}")
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        if not probe:
            self.last_latency_ms = elapsed_ms
            if elapsed_ms > self.latency_gate_ms:
                self.latency_violations += 1
                print(
                    f"[tts:voicebox] LATENCY GATE VIOLATED: {elapsed_ms:.0f}ms "
                    f"> {self.latency_gate_ms:.0f}ms gate. The MCP boundary is "
                    f"too slow for sentence streaming on this hardware — "
                    f"consider engine-level streaming instead (spec §7).",
                    file=sys.stderr)
        if isinstance(payload, dict) and payload.get("error"):
            raise TTSError(f"Voicebox error: {payload['error']}")
        return payload.get("result", {}) if isinstance(payload, dict) else {}

    def speak_sentence(self, text: str, on_word: OnWord) -> None:
        words = text.split()
        if not words:
            return
        result = self._rpc("tools/call", {
            "name": "voicebox_speak",
            "arguments": {"text": text, "voice": self.voice},
        })
        audio_b64 = None
        if isinstance(result, dict):
            audio_b64 = result.get("audio_base64") or result.get("audio")
        if audio_b64:
            # Server returned audio: play it locally, pace words over it.
            if self.player is None:
                self.player = _default_player()
            raw = base64.b64decode(audio_b64)
            with tempfile.NamedTemporaryFile(suffix=".wav",
                                             delete=False) as f:
                f.write(raw)
                wav_path = f.name
            try:
                duration = _wav_duration_s(wav_path) or (len(words) / 2.5)
                pt = threading.Thread(target=self.player, args=(wav_path,),
                                      daemon=True)
                pt.start()
                try:
                    per_word = duration / len(words)
                    for i in range(len(words)):
                        time.sleep(per_word)
                        on_word(i)
                finally:
                    pt.join(timeout=2.0)
            finally:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass
        else:
            # Server-side playback assumed: pace word callbacks over a
            # speaking-rate estimate (~150 wpm). Documented estimate.
            per_word = 1.0 / 2.5
            for i in range(len(words)):
                time.sleep(per_word)
                on_word(i)


# --------------------------------------------------------------------------- #
# Kokoro-82M — resident neural voice (team17 verdict: the Hindi default).
#
# Kokoro ships four real Hindi voices (Apache-2.0) and runs CPU-real-time
# at 82M params — zero VRAM pressure next to the 7B brain. The `kokoro`
# package is a LAZY optional dep (torch under the hood), imported inside
# _pipeline() only; a machine without it gets a typed TTSError naming the
# pip package, exactly like piper without its binary.
#
# THE HINDI ROUTE: Kokoro has no per-call language switch — the VOICE
# carries the language. So speak_sentence picks the voice per sentence:
# Devanagari / Hinglish-heavy text -> the Hindi voice (gender follows the
# configured default voice, or the explicit hindi_voice= override);
# English text keeps the owner's chosen voice untouched.
#
# HEURISTIC HONESTY: "Hinglish-heavy" is a script-ratio + marker-word
# guess (below), not language ID. It will misroute some mixed sentences.
# And a Hindi voice phonemizing ROMAN Hinglish via espeak is unproven —
# Devanagari input is the reliable path; roman input is best-effort.
# --------------------------------------------------------------------------- #

# voice name -> (kokoro lang_code, gender). The four Hindi voices are
# team17 §4.1, verified against the hexgrad/Kokoro-82M repo inventory.
KOKORO_VOICES: Dict[str, Tuple[str, str]] = {
    # Hindi (lang "h")
    "hf_alpha": ("h", "f"), "hf_beta": ("h", "f"),
    "hm_omega": ("h", "m"), "hm_psi": ("h", "m"),
    # American English (lang "a")
    "af_heart": ("a", "f"), "af_bella": ("a", "f"), "af_nova": ("a", "f"),
    "am_michael": ("a", "m"), "am_fenrir": ("a", "m"), "am_puck": ("a", "m"),
    # British English (lang "b")
    "bf_emma": ("b", "f"), "bf_isabella": ("b", "f"),
    "bm_george": ("b", "m"), "bm_fable": ("b", "m"),
}
KOKORO_HINDI_VOICES: Dict[str, str] = {
    name: gender for name, (lang, gender) in KOKORO_VOICES.items()
    if lang == "h"
}
KOKORO_SAMPLE_RATE = 24000  # Kokoro renders 24 kHz float audio

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_HINGLISH_MARKERS = frozenset({
    "hai", "hain", "kya", "ka", "ki", "ke", "ko", "mein", "ne", "se",
    "aur", "nahi", "kar", "raha", "rahi", "rahe", "mera", "meri", "mere",
    "tum", "aap", "yeh", "woh", "bhi", "toh", "karna", "karo", "bolo",
    "dekho", "suno", "chahiye", "wala", "wali", "abhi", "kal", "aaj",
    "bahut", "kuch", "sab", "kyun", "kyunki", "matlab", "bhai", "yaar",
})


def devanagari_ratio(text: str) -> float:
    """Share of letters that are Devanagari. 0.0 for pure roman text."""
    letters = [ch for ch in (text or "") if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for ch in letters if _DEVANAGARI.match(ch)) / len(letters)


def is_hindi_heavy(text: str) -> bool:
    """Heuristic: should this sentence be spoken by a Hindi voice?

    True when Devanagari is >= 20% of letters, or when roman words are
    >= 30% Hinglish markers (at least 2 of them — one stray 'ka' proves
    nothing). Deliberately simple and documented; see the honesty note
    above the voice table.
    """
    if devanagari_ratio(text) >= 0.2:
        return True
    words = re.findall(r"[a-z]+", (text or "").lower())
    if len(words) < 2:
        return False
    markers = sum(1 for w in words if w in _HINGLISH_MARKERS)
    return markers >= 2 and markers / len(words) >= 0.3


class KokoroEngine(Engine):
    """Kokoro-82M TTS (offline, local, CPU-real-time).

    `voice` is the owner's default (an English voice, normally). Hindi /
    Hinglish-heavy sentences are rerouted to a Hindi voice by
    voice_for_text(); `hindi_voice=` pins that choice explicitly,
    otherwise the gender follows the default voice (Kokoro names encode
    it: a**f**_ = female, a**m**_ = male) with hf_alpha as the fallback.
    """

    name = "kokoro"

    def __init__(self, voice: str = "af_heart",
                 hindi_voice: Optional[str] = None,
                 player: Optional[Callable[[str], None]] = None) -> None:
        if importlib.util.find_spec("kokoro") is None:
            raise TTSError(
                "kokoro is not installed. Install it with: "
                "pip install kokoro — TTS refuses to pretend it is "
                "working.")
        if hindi_voice is not None and hindi_voice not in KOKORO_HINDI_VOICES:
            raise TTSError(
                f"hindi_voice must be a Kokoro Hindi voice "
                f"({', '.join(sorted(KOKORO_HINDI_VOICES))}), "
                f"got {hindi_voice!r}")
        self.voice = voice
        self.hindi_voice = hindi_voice
        self.player = player or _default_player()
        self._pipelines: Dict[str, object] = {}

    def _hindi_voice(self) -> str:
        if self.hindi_voice:
            return self.hindi_voice
        gender = KOKORO_VOICES.get(self.voice, ("a", "f"))[1]
        return "hm_omega" if gender == "m" else "hf_alpha"

    def voice_for_text(self, text: str) -> str:
        """The lang="hi" route: Hindi voice iff the text is Hindi-heavy."""
        return self._hindi_voice() if is_hindi_heavy(text) else self.voice

    def _pipeline(self, lang_code: str):
        pipe = self._pipelines.get(lang_code)
        if pipe is None:
            try:
                from kokoro import KPipeline
            except ImportError as exc:
                raise TTSError(
                    "kokoro is not installed. Install it with: "
                    "pip install kokoro") from exc
            try:
                pipe = KPipeline(lang_code=lang_code)
            except Exception as exc:
                raise TTSError(
                    f"kokoro pipeline failed (lang={lang_code!r}): "
                    f"{type(exc).__name__}: {exc}") from exc
            self._pipelines[lang_code] = pipe
        return pipe

    def _synthesize(self, text: str, voice: str, out_path: str) -> float:
        """Render `text` in `voice` to a WAV file; return duration (s)."""
        import numpy as np  # noqa: E402  (ships with kokoro's stack)
        lang = KOKORO_VOICES.get(voice, (voice[:1] or "a", "?"))[0]
        pipe = self._pipeline(lang)
        chunks = []
        try:
            for _graphemes, _phonemes, audio in pipe(text, voice=voice):
                if audio is None:
                    continue
                if hasattr(audio, "detach"):  # torch tensor -> numpy
                    audio = audio.detach().cpu().numpy()
                chunks.append(np.asarray(audio, dtype=np.float32))
        except TTSError:
            raise
        except Exception as exc:
            raise TTSError(f"kokoro synthesis failed: "
                           f"{type(exc).__name__}: {exc}") from exc
        if not chunks:
            raise TTSError("kokoro produced no audio for the sentence")
        samples = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
        with wave.open(out_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(KOKORO_SAMPLE_RATE)
            wf.writeframes(pcm.tobytes())
        return len(samples) / KOKORO_SAMPLE_RATE

    def speak_sentence(self, text: str, on_word: OnWord) -> None:
        words = text.split()
        if not words:
            return
        voice = self.voice_for_text(text)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
        try:
            duration = self._synthesize(text, voice, wav_path)
            # Same playback shape as PiperEngine: play in the background,
            # pace word callbacks over the real rendered duration.
            player_thread = threading.Thread(
                target=self.player, args=(wav_path,), daemon=True)
            player_thread.start()
            try:
                per_word = duration / len(words)
                for i in range(len(words)):
                    time.sleep(per_word)
                    on_word(i)
            finally:
                player_thread.join(timeout=2.0)
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass


def pick_engine(preference: str = "auto") -> Engine:
    """Choose a TTS engine.

    auto: voicebox if reachable → piper if installed → kokoro if the
    package is installed → stub (with a LOUD warning, never silent).
    Explicit preferences raise TTSError when the engine is unavailable —
    never a silent downgrade.
    """
    if preference == "stub":
        return StubEngine()
    if preference == "voicebox":
        return VoiceboxEngine()  # raises TTSError if unreachable
    if preference == "piper":
        return PiperEngine()  # raises TTSError if binary/model missing
    if preference == "kokoro":
        return KokoroEngine()  # raises TTSError if package missing
    if preference != "auto":
        raise TTSError(f"Unknown engine preference: {preference!r}")

    try:
        return VoiceboxEngine()
    except TTSError:
        pass
    if shutil.which("piper") is not None:
        try:
            return PiperEngine()
        except TTSError:
            pass
    try:
        return KokoroEngine()
    except TTSError:
        pass
    print("=" * 70, file=sys.stderr)
    print("[tts] WARNING: no real TTS engine found (no voicebox MCP server, "
          "no piper binary).", file=sys.stderr)
    print("[tts] Falling back to the STUB engine — it PRINTS words instead "
          "of speaking them.", file=sys.stderr)
    print("[tts] Install voicebox or piper-tts for real speech.", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    return StubEngine()


# --------------------------------------------------------------------------- #
# Speech priority core (SSIP × NVDA — team23 steal; GPL/LGPL sources,
# ideas only, this is original code)
# --------------------------------------------------------------------------- #
#
# Three priority classes over the ONE watermarked SpeechQueue:
#
#   URGENT  safety alerts / urgent proactivity. Preempts everything at
#           the next chunk boundary; FIFO among its own class; never
#           preempted by NORMAL or LOW.
#   NORMAL  brain replies. Preempts LOW at the next chunk boundary;
#           never preempts NORMAL (FIFO within the class).
#   LOW     digests, fillers, status ticks. Preempted by anything
#           above it; a preempted item is POSTPONED — its remaining
#           chunks resume when the higher work drains — never dropped.
#
# Preemption is a CHUNK-boundary operation, NVDA's preempt-and-resume:
# the chunk in flight finishes (its words really left the speakers,
# and the index callback says so), then the higher class takes the
# pump. Word-level halts belong to stop()/cancel()/interrupt() — the
# stop-flag machinery, unchanged.
#
# Two submission paths share the pump:
#   * speak(text) — the legacy conversational COMMIT the existing
#     loop and suite are built on: a fresh reply supersedes in-flight
#     NORMAL speech (retired at the next word, record parked, never
#     resumed), postpones a playing LOW item (it resumes after), and
#     queues behind a playing URGENT. Queued items are never touched.
#   * speak(text, priority=..., key=...) — the priority core: pure
#     queue submission, nothing is stopped by the submission itself.
#     key= gives the slot latest-wins semantics (SSIP's text /
#     notification classes): a still-QUEUED item with the same key is
#     replaced by the new one — repeated status updates collapse to
#     the newest. A PLAYING item is never replaced: its words are
#     already leaving the speakers.
#
# Index callbacks (the NVDA/eSpeak discipline): on_spoken(chunk_id,
# text) fires from the pump with EXACTLY what left the speakers — the
# full chunk text on completion, the spoken prefix when a chunk was
# cut mid-way, and nothing for a chunk no word of which ever left.
# The callback stream and Utterance.words_spoken_text() therefore
# always agree about where speech stopped: the brain's memory of
# speech stays truthful (spec §3.3).

URGENT = "urgent"
NORMAL = "normal"
LOW = "low"
PRIORITIES = (URGENT, NORMAL, LOW)          # service order, highest first
_PRIORITY_RANK = {URGENT: 0, NORMAL: 1, LOW: 2}

# on_spoken: Callable[[chunk_id, text_actually_spoken], None]
OnSpoken = Callable[[int, str], None]


class _SpeechItem:
    """One submitted utterance inside the priority core."""

    __slots__ = ("utterance", "priority", "key", "next_idx",
                 "chunks_ready", "abandoned", "park_requested")

    def __init__(self, utterance: "Utterance", priority: str,
                 key: Optional[str]) -> None:
        self.utterance = utterance
        self.priority = priority
        self.key = key
        self.next_idx = 0            # next sentence index to play
        self.chunks_ready = False    # chunk ids assigned in the queue
        self.abandoned = False       # retired while deaf: never play
        self.park_requested = False  # postpone(): park at the boundary


# --------------------------------------------------------------------------- #
# Speaker — echo guard wired at construction (anti-C-V1)
# --------------------------------------------------------------------------- #


class Speaker:
    """Owns the speaking half of the voice loop.

    ``on_state`` is REQUIRED — there is no default, no ``None``. It is
    called with ``"speaking"`` / ``"idle"`` on every transition, and the
    echo guard subscribes to it (spec §2.1). A speaker without a guard
    cannot be constructed.

    ``on_spoken`` is optional: the speech core's index callback,
    ``on_spoken(chunk_id, text)`` — see the priority-core note above.
    """

    def __init__(self, on_state: Callable[[str], None],
                 engine: Optional[Engine] = None,
                 on_spoken: Optional[OnSpoken] = None) -> None:
        if on_state is None or not callable(on_state):
            raise TypeError(
                "Speaker requires an on_state callback (the echo guard's "
                "tts_state entry point). Got: %r. A speaker without a guard "
                "is how v1 answered itself (C-V1) — refused." % (on_state,))
        self.on_state = on_state
        self.on_spoken = on_spoken
        self.engine: Engine = engine or pick_engine("auto")
        self._state = "idle"
        self._stop = threading.Event()
        self._utterance: Optional[Utterance] = None
        # One RLock for everything; _cond shares it so the state helpers
        # can run under either acquisition.
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        # Interruption watermark (see SpeechQueue): every chunk spoken
        # goes through this queue, so interrupt() can freeze stale audio
        # by construction instead of hoping the worker thread notices.
        self._queue = SpeechQueue()
        # Highest chunk id that may ever have reached the speakers. Set by
        # interrupt(); consumers use it to decide which transcripts could
        # be echo of OUR voice (voice_loop salvage) vs real user speech.
        self._audio_emitted = 0
        # Priority core: per-class FIFO queues, the manual park, the
        # item on the pump right now, and the pump thread itself.
        self._queues: Dict[str, deque] = {p: deque() for p in PRIORITIES}
        self._parked: List[_SpeechItem] = []
        self._current: Optional[_SpeechItem] = None
        self._pump_thread: Optional[threading.Thread] = None
        self._worker: Optional[threading.Thread] = None  # pump alias

    # -- state ------------------------------------------------------------ #

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def current_utterance(self) -> Optional[Utterance]:
        with self._lock:
            return self._utterance

    def _transition_locked(self, new_state: str) -> bool:
        """Under _cond: move the state; True iff the caller must fire
        on_state (outside the lock). The single choke point — a
        transition can never fire twice."""
        if self._state == new_state:
            return False
        self._state = new_state
        return True

    def _fire_state(self, state: str) -> None:
        try:
            self.on_state(state)
        except Exception as exc:  # a broken guard must not kill the pump
            print(f"[tts] on_state({state!r}) callback raised: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)

    # -- submission --------------------------------------------------------- #

    def speak(self, text: str, priority: Optional[str] = None,
              key: Optional[str] = None) -> Utterance:
        """Commit speech; returns the Utterance handle at once.

        Bare ``speak(text)`` is the legacy conversational commit (see
        the priority-core note). Passing ``priority`` (URGENT /
        NORMAL / LOW) or a ``key`` selects the priority core: the
        item is queued by class and the pump's discipline decides
        when it plays.
        """
        if priority is None and key is None:
            return self._commit(text)
        prio = priority if priority is not None else NORMAL
        if prio not in _PRIORITY_RANK:
            raise ValueError(
                f"unknown speech priority {prio!r} — expected one of "
                f"{sorted(_PRIORITY_RANK)}")
        item = _SpeechItem(Utterance(split_sentences(text)), prio, key)
        with self._cond:
            if key is not None:
                self._replace_key_locked(key)
            self._queues[prio].append(item)
            self._ensure_pump_locked()
        return item.utterance

    def _commit(self, text: str) -> Utterance:
        """The legacy conversational commit: the brain's fresh reply.

        Supersedes a playing NORMAL item (retired at the next word —
        the old speak() contract), leaves a playing URGENT item to
        finish (the commit queues behind it), and needs no action
        against a playing LOW item: the pump sees the NORMAL arrival
        pending and postpones LOW at the next chunk boundary.
        """
        item = _SpeechItem(Utterance(split_sentences(text)), NORMAL, None)
        with self._cond:
            current = self._current
            self._queues[NORMAL].appendleft(item)
            self._ensure_pump_locked()
        if current is not None and current.priority == NORMAL:
            self._stop_item(current)
        return item.utterance

    def _replace_key_locked(self, key: str) -> None:
        """Latest-wins: drop STILL-QUEUED items carrying ``key`` (any
        class, parked included) — their records finish SKIPPED, they
        never reach the engine. The PLAYING item is never replaced."""
        for prio in PRIORITIES:
            q = self._queues[prio]
            for item in list(q):
                if item.key == key:
                    q.remove(item)
                    self._drop_item(item)
        for item in list(self._parked):
            if item.key == key:
                self._parked.remove(item)
                self._drop_item(item)

    # -- cancel / postpone / resume ---------------------------------------- #

    def cancel(self, priority: Optional[str] = None) -> List[Utterance]:
        """Drop speech without playing it and return what was dropped.

        ``priority=None`` cancels every class; otherwise only that
        class. Queued and parked items of the class are dropped (their
        records finish, unsaid sentences SKIPPED); a PLAYING item of
        the class is stopped at the next word. Items of other classes
        — playing or queued — are untouched.
        """
        if priority is not None and priority not in _PRIORITY_RANK:
            raise ValueError(
                f"unknown speech priority {priority!r} — expected one "
                f"of {sorted(_PRIORITY_RANK)}")
        targets = (priority,) if priority is not None else PRIORITIES
        cancelled: List[Utterance] = []
        with self._cond:
            for prio in targets:
                q = self._queues[prio]
                while q:
                    item = q.popleft()
                    self._drop_item(item)
                    cancelled.append(item.utterance)
            for item in list(self._parked):
                if item.priority in targets:
                    self._parked.remove(item)
                    self._drop_item(item)
                    cancelled.append(item.utterance)
            current = self._current
        if current is not None and current.priority in targets:
            self._stop_item(current)
            cancelled.append(current.utterance)
            self._await_idle()
        return cancelled

    def postpone(self) -> Optional[Utterance]:
        """Park the currently playing LOW item at the next chunk
        boundary: the chunk in flight finishes honestly, the rest
        waits — resumable via resume(), never dropped. Returns the
        item's Utterance, or None when nothing LOW is playing
        (postponing a reply or an alert is what priorities and
        cancel() are for)."""
        with self._cond:
            current = self._current
            if (current is None or current.priority != LOW
                    or current.utterance.finished):
                return None
            current.park_requested = True
            return current.utterance

    def resume(self) -> int:
        """Un-park every item parked by postpone() (items postponed
        BY PREEMPTION resume on their own — they never park). Returns
        how many items were un-parked."""
        with self._cond:
            parked, self._parked = self._parked, []
            for item in reversed(parked):
                self._queues[item.priority].appendleft(item)
            if parked:
                self._ensure_pump_locked()
            return len(parked)

    @property
    def postponed(self) -> List[Utterance]:
        """Utterances parked by postpone(), waiting for resume()."""
        with self._cond:
            return [item.utterance for item in self._parked]

    # -- stop / interrupt (the pre-core contract, preserved) ---------------- #

    def stop(self) -> Optional[Utterance]:
        """Halt the CURRENT item after the current word (spec §3.2,
        anti-C-V2). Queued and parked items are untouched — cancel()
        drops those. The stop flag is a signal, not a latch: it is
        cleared before returning, so the next speak() always works.
        """
        utt = self.current_utterance
        with self._cond:
            current = self._current
        if current is not None:
            self._stop_item(current)
            utt = current.utterance
        else:
            self._stop.clear()
        self._await_idle()
        return utt

    def interrupt(self) -> Optional[Utterance]:
        """Barge-in path: freeze the queued audio BY CONSTRUCTION, then stop.

        Sets the interruption watermark so no queued chunk may ever play
        (even a stale worker racing with the next speak()), records the
        watermark high-water mark in ``_audio_emitted`` (consumers: echo
        salvage can no longer treat everything ever spoken as echo), and
        then stops the engine. The next speak() always works — the watermark
        never freezes FUTURE chunks (ids are monotonic).
        """
        wm = self._queue.interrupt()
        self._audio_emitted = max(self._audio_emitted, wm)
        return self.stop()

    def dropped_chunk_ids(self) -> List[int]:
        """Chunk ids a fresh barge-in dropped: ids from a finished utterance
        are included, because anything <= the watermark may still have been
        ringing in the speakers when the user cut in."""
        utt = self.current_utterance
        ids = list(utt.chunk_ids) if utt is not None else []
        return [cid for cid in ids if cid <= self._queue.watermark]

    # -- item retirement ------------------------------------------------------ #

    def _stop_item(self, item: _SpeechItem) -> None:
        """Word-level stop of ONE playing item (the old stop() body,
        scoped to an item): set the flag, wait like the old worker
        join (<=2s), park the record, clear the flag (anti-C-V2). If
        the pump already moved past the item (it was preempted while
        we waited), abandon it in place instead of waiting out the
        clock — it will never speak again either way."""
        utt = item.utterance
        self._stop.set()
        deadline = time.monotonic() + 2.0
        while not utt.finished and time.monotonic() < deadline:
            with self._cond:
                if self._current is not item:
                    break  # preempted or finished meanwhile
            utt._done.wait(0.01)
        if not utt.finished:
            with self._cond:
                q = self._queues[item.priority]
                if item in q:
                    q.remove(item)
                if self._current is item:
                    self._current = None
            self._drop_item(item)
        self._stop.clear()  # ← THE LINE V1 WAS MISSING (C-V2)

    def _drop_item(self, item: _SpeechItem) -> None:
        """Retire an item that will never reach the pump again: free
        its still-queued chunks and finish its record."""
        if item.chunks_ready:
            for cid in item.utterance.chunk_ids[item.next_idx:]:
                self._queue.consume(cid)
        item.abandoned = True
        self._finish_record(item)

    def _finish_record(self, item: _SpeechItem) -> None:
        """Mark an item's record terminal: every unplayed sentence
        SKIPPED, interrupted_at set iff speech was cut short, done
        set. Idempotent — the pump and stop() may both arrive here."""
        utt = item.utterance
        with utt._lock:
            for j in range(item.next_idx, len(utt.sentences)):
                if utt.sentence_status[j] in (QUEUED, SPEAKING):
                    utt.sentence_status[j] = SKIPPED
            if (utt.interrupted_at is None
                    and utt.words_spoken < utt.words_total):
                utt.interrupted_at = time.monotonic()
        utt._done.set()

    def _await_idle(self, timeout: float = 2.0) -> None:
        """If no work remains, fire the idle transition exactly once.
        Waits briefly for the pump to finish unwinding a just-stopped
        item, so the transition is already visible when stop()
        returns (the old join-based stop() had this property)."""
        deadline = time.monotonic() + timeout
        fire = False
        while True:
            with self._cond:
                busy = (self._current is not None
                        or any(self._queues[p] for p in PRIORITIES))
                if not busy:
                    fire = self._transition_locked("idle")
                    break
                if time.monotonic() >= deadline:
                    return
            time.sleep(0.002)
        if fire:
            self._fire_state("idle")

    # -- the pump ------------------------------------------------------------- #

    def _ensure_pump_locked(self) -> None:
        t = self._pump_thread
        if t is None or not t.is_alive():
            t = threading.Thread(target=self._pump_loop, daemon=True,
                                 name="jarvis-tts")
            self._pump_thread = t
            self._worker = t
            t.start()

    def _take_next_locked(self) -> Optional[_SpeechItem]:
        """Highest class first, FIFO within a class. Parked items are
        NOT work — they wait for resume()."""
        for prio in PRIORITIES:
            q = self._queues[prio]
            if q:
                item = q.popleft()
                self._current = item
                self._utterance = item.utterance
                return item
        return None

    def _higher_pending(self, priority: str) -> bool:
        rank = _PRIORITY_RANK[priority]
        with self._cond:
            return any(self._queues[p] for p in PRIORITIES
                       if _PRIORITY_RANK[p] < rank)

    def _pump_loop(self) -> None:
        while True:
            fire = None
            with self._cond:
                item = self._take_next_locked()
                if item is None:
                    self._pump_thread = None
                    self._worker = None
                    if self._transition_locked("idle"):
                        fire = "idle"
                elif self._transition_locked("speaking"):
                    fire = "speaking"
            if fire is not None:
                self._fire_state(fire)
            if item is None:
                return
            try:
                self._play_item(item)
            except Exception as exc:  # the pump must never die silently
                print(f"[tts] speech pump error on a {item.priority} "
                      f"item: {type(exc).__name__}: {exc}",
                      file=sys.stderr)
                self._drop_item(item)
            with self._cond:
                if self._current is item:
                    self._current = None
                # The stop flag belongs to the item that just ended;
                # it must never latch into the next item (anti-C-V2).
                self._stop.clear()

    def _ensure_chunks(self, item: _SpeechItem) -> None:
        """Assign the item's sentences watermark ids in the shared
        SpeechQueue — lazily, at first play, so a queued item's chunks
        can never be frozen by an interrupt aimed at another item.

        On RESUME, if a watermark froze the remainder (an interrupt
        landed while the item was postponed), rebuild the remainder
        with fresh ids: the frozen ids never play (the watermark
        guarantee), the sentences still do (the resume guarantee)."""
        utt = item.utterance
        if item.chunks_ready:
            if item.next_idx >= len(utt.sentences):
                return
            if self._queue.get(utt.chunk_ids[item.next_idx]) is not None:
                return  # remainder intact
            fresh = self._queue.enqueue(
                utt.sentences[item.next_idx:], start_idx=item.next_idx)
            utt.chunk_ids[item.next_idx:] = [c.chunk_id for c in fresh]
            return
        chunks = self._queue.enqueue(utt.sentences)
        utt.chunk_ids = [c.chunk_id for c in chunks]
        item.chunks_ready = True

    def _fire_spoken(self, chunk: Chunk, words: int) -> None:
        """Index callback: report EXACTLY what left the speakers for
        this chunk — the full text on completion, the spoken prefix
        when the chunk was cut mid-way, and nothing at all when no
        word of it ever left."""
        cb = self.on_spoken
        if cb is None or words <= 0:
            return
        parts = chunk.text.split()
        text = (chunk.text if words >= len(parts)
                else " ".join(parts[:words]))
        try:
            cb(chunk.chunk_id, text)
        except Exception as exc:  # caller code must not kill the pump
            print(f"[tts] on_spoken callback raised: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)

    def _play_item(self, item: _SpeechItem) -> None:
        """Play one item's remaining chunks on the pump thread.

        Ends one of three ways: FINISHED (the record is completed —
        fully played, or parked by a stop/cancel with the unsaid
        marked SKIPPED), PREEMPTED (a strictly higher class is
        pending: the item returns to the head of its class queue,
        record NOT finished — it resumes by itself), or PARKED
        (postpone() was requested: the item waits in _parked for
        resume(), record NOT finished).
        """
        utt = item.utterance
        self._ensure_chunks(item)
        sentences = utt.sentences
        while item.next_idx < len(sentences):
            i = item.next_idx
            if item.abandoned or utt.finished or self._stop.is_set():
                break
            chunk = self._queue.get(utt.chunk_ids[i])
            if chunk is None:
                # Frozen by an interruption watermark — this backlog
                # may never play (by construction). Terminal.
                break
            with utt._lock:
                utt.sentence_status[i] = SPEAKING
            words_seen = [0]

            def _hook(wi: int, _i: int = i,
                      _seen: List[int] = words_seen) -> None:
                if self._stop.is_set():
                    raise _StopRequested()
                utt.record_word(_i, wi)
                _seen[0] = wi + 1

            try:
                self.engine.speak_sentence(chunk.text, _hook)
            except _StopRequested:
                with utt._lock:
                    utt.sentence_status[i] = INTERRUPTED
                    utt.interrupted_at = time.monotonic()
                self._fire_spoken(chunk, words_seen[0])
                item.next_idx = i + 1
                break
            except Exception as e:  # engine failed loudly (H-V2)
                with utt._lock:
                    utt.sentence_status[i] = INTERRUPTED
                    utt.interrupted_at = time.monotonic()
                    utt.error = f"{type(e).__name__}: {e}"
                self._fire_spoken(chunk, words_seen[0])
                item.next_idx = i + 1
                break
            if utt.finished:
                # stop()/cancel() parked the record while a deaf
                # engine ignored the stop flag — do not resurrect
                # this chunk as SPOKEN over their SKIPPED.
                break
            with utt._lock:
                utt.sentence_status[i] = SPOKEN
            self._queue.consume(chunk.chunk_id)
            self._fire_spoken(chunk, len(chunk.text.split()))
            item.next_idx = i + 1
            if item.next_idx >= len(sentences):
                break
            # Chunk boundary — the ONLY place preemption and parking
            # happen: the chunk in flight always finishes honestly.
            if self._higher_pending(item.priority):
                with self._cond:
                    self._queues[item.priority].appendleft(item)
                return  # postponed by preemption — resumes by itself
            if item.park_requested:
                item.park_requested = False
                with self._cond:
                    self._parked.append(item)
                return  # parked by postpone() — waits for resume()
        # Terminal: free the unplayed chunks and park the record.
        if item.chunks_ready:
            for cid in utt.chunk_ids[item.next_idx:]:
                self._queue.consume(cid)
        self._finish_record(item)
