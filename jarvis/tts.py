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
from typing import Callable, List, Optional

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


def pick_engine(preference: str = "auto") -> Engine:
    """Choose a TTS engine.

    auto: voicebox if reachable → piper if installed → stub (with a LOUD
    warning, never silent). Explicit preferences raise TTSError when the
    engine is unavailable — never a silent downgrade.
    """
    if preference == "stub":
        return StubEngine()
    if preference == "voicebox":
        return VoiceboxEngine()  # raises TTSError if unreachable
    if preference == "piper":
        return PiperEngine()  # raises TTSError if binary/model missing
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
    print("=" * 70, file=sys.stderr)
    print("[tts] WARNING: no real TTS engine found (no voicebox MCP server, "
          "no piper binary).", file=sys.stderr)
    print("[tts] Falling back to the STUB engine — it PRINTS words instead "
          "of speaking them.", file=sys.stderr)
    print("[tts] Install voicebox or piper-tts for real speech.", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    return StubEngine()


# --------------------------------------------------------------------------- #
# Speaker — echo guard wired at construction (anti-C-V1)
# --------------------------------------------------------------------------- #


class Speaker:
    """Owns the speaking half of the voice loop.

    ``on_state`` is REQUIRED — there is no default, no ``None``. It is
    called with ``"speaking"`` / ``"idle"`` on every transition, and the
    echo guard subscribes to it (spec §2.1). A speaker without a guard
    cannot be constructed.
    """

    def __init__(self, on_state: Callable[[str], None],
                 engine: Optional[Engine] = None) -> None:
        if on_state is None or not callable(on_state):
            raise TypeError(
                "Speaker requires an on_state callback (the echo guard's "
                "tts_state entry point). Got: %r. A speaker without a guard "
                "is how v1 answered itself (C-V1) — refused." % (on_state,))
        self.on_state = on_state
        self.engine: Engine = engine or pick_engine("auto")
        self._state = "idle"
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._utterance: Optional[Utterance] = None
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def current_utterance(self) -> Optional[Utterance]:
        with self._lock:
            return self._utterance

    def _to_idle(self) -> bool:
        """Move to idle. Returns True iff this was a real transition."""
        with self._lock:
            if self._state == "idle":
                return False
            self._state = "idle"
            self._worker = None
            return True

    def speak(self, text: str) -> Utterance:
        """Speak text, sentence-streamed. Sentence 1 starts immediately;
        the rest queue behind it. Returns the Utterance handle.

        Any in-flight utterance is stopped first (cleanly).
        """
        self.stop()  # park anything in flight; clears the stop flag
        assert not self._stop.is_set(), \
            "stop flag still set after stop() — C-V2 regression"
        sentences = split_sentences(text)
        utt = Utterance(sentences)
        with self._lock:
            self._utterance = utt
            self._state = "speaking"
            self._stop.clear()
            worker = threading.Thread(
                target=self._run, args=(utt,), daemon=True,
                name="jarvis-tts")
            self._worker = worker
        self.on_state("speaking")  # guard hears it BEFORE audio starts
        worker.start()
        return utt

    def _on_word(self, utt: Utterance, sentence_idx: int,
                 word_idx: int) -> None:
        if self._stop.is_set():
            raise _StopRequested()
        utt.record_word(sentence_idx, word_idx)

    def _run(self, utt: Utterance) -> None:
        try:
            for i, sent in enumerate(utt.sentences):
                if self._stop.is_set():
                    with utt._lock:
                        utt.sentence_status[i] = SKIPPED
                    continue
                with utt._lock:
                    utt.sentence_status[i] = SPEAKING
                try:
                    self.engine.speak_sentence(
                        sent,
                        lambda wi, i=i: self._on_word(utt, i, wi))
                except _StopRequested:
                    with utt._lock:
                        utt.sentence_status[i] = INTERRUPTED
                        utt.interrupted_at = time.monotonic()
                    break
                except Exception as e:  # engine failed loudly (H-V2)
                    with utt._lock:
                        utt.sentence_status[i] = INTERRUPTED
                        utt.interrupted_at = time.monotonic()
                        utt.error = f"{type(e).__name__}: {e}"
                    break
                with utt._lock:
                    utt.sentence_status[i] = SPOKEN
        finally:
            utt._done.set()
            # Only the CURRENT utterance may move the speaker to idle — a
            # stale worker (killed by stop() but still parking) must never
            # clobber a newer speak().
            with self._lock:
                mine = self._utterance is utt
            if mine and self._to_idle():
                self.on_state("idle")

    def stop(self) -> Optional[Utterance]:
        """Halt speech after the current word (spec §3.2, anti-C-V2).

        The stop flag is a signal, not a latch: it is set, the worker is
        joined, unsaid sentences are marked skipped — and then the flag is
        CLEARED BY stop() ITSELF, so the next speak() always works.
        """
        utt = self.current_utterance
        self._stop.set()
        worker = None
        with self._lock:
            worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=2.0)
        if utt is not None:
            with utt._lock:
                for i, st in enumerate(utt.sentence_status):
                    if st in (QUEUED, SPEAKING):
                        utt.sentence_status[i] = SKIPPED
                if utt.interrupted_at is None and utt.words_spoken < utt.words_total:
                    utt.interrupted_at = time.monotonic()
            utt._done.set()
        self._stop.clear()  # ← THE LINE V1 WAS MISSING (C-V2)
        if self._to_idle():
            self.on_state("idle")
        return utt
