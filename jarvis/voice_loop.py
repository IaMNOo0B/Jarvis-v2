"""JARVIS v2 — the voice loop (Wave 4, the final wave).

The 8-stage pipeline: MIC -> VAD -> WAKE -> COLLECT -> STT -> BRAIN -> TTS -> SPEAKERS.
Two cross-cutting watchers ride alongside: the echo guard and the barge-in detector.

Design rules (from learn-voice-loop-spec.md):
  - Echo guard by CONSTRUCTION: Speaker REQUIRES an on_state callback —
    no default, no None. A speaker without a guard cannot exist.
  - Barge-in stop protocol CLEARS its own flag (the v1 C-V2 permanent-mute fix).
  - Utterance Record: the brain commits text sentences; TTS reports word-level
    completion. On interrupt, history is TRUNCATED to what left the speakers —
    the brain never "remembers" words the user never heard.
  - Voice is a plugin: text chat never depends on this module, and this module
    never imports audio libraries at top level (R1). All hardware is injected.

Stdlib only. Python 3.11+.
"""

from __future__ import annotations

import json
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional

# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class VoiceError(Exception):
    """Anything the voice loop refuses to do quietly."""


# --------------------------------------------------------------------------- #
# Constants (all [PROPOSED] until calibrated on real hardware + the user)
# --------------------------------------------------------------------------- #

# The wake word is "Jarvis" (owner's decision, 2026-10-19). One word, one
# path — the brain routes local vs cloud per turn, not the wake model.
WAKE_WORD = "jarvis"
WAKE_LOCAL = WAKE_WORD   # kept for compatibility; both mean the one word
WAKE_CLOUD = WAKE_WORD   # the two-word scheme is retired

ECHO_TAIL_MS = 800            # default; adapts at runtime (M-V20)
ECHO_TAIL_MIN_MS = 300
ECHO_TAIL_MAX_MS = 2000
CLEAN_TURNS_TO_SHRINK = 10

BARGE_MATCH_RATIO = 0.70      # >=70% word overlap with spoken text -> echo
BARGE_NOVEL_WORDS = 3         # >=3 novel words -> user is interrupting

# Hard interrupt phrases: bypass the accumulator, yield immediately (M-V14).
HARD_INTERRUPT_PHRASES = (
    "stop", "shut up", "never mind", "quiet", "enough", "cancel",
)

TRAILING_SILENCE_S = 0.7      # endpointing: 700ms of quiet ends the utterance
COLLECT_CAP_S = 30.0          # hard cap; closes at the last chunk, never mid-word-cut here
CHUNK_S = 0.02                # mic chunks are 20ms
PRE_ROLL_CHUNKS = 25          # 500ms pre-roll so onsets are never clipped (H-V6)

WAKE_COOLDOWN_S = 1.5         # anti-double-fire
FALSE_ACCEPT_NOTE_AT = 3      # >3 false wakes/day -> sensitivity note (S3)
LATENCY_BUDGET_S = 4.0        # STT + BRAIN + first audio; breach is LOUD, never silent


# --------------------------------------------------------------------------- #
# Utterance Record (Moshi pattern): text spine of the speaking path
# --------------------------------------------------------------------------- #

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def segment_sentences(text: str) -> list[str]:
    """Split reply text into TTS sentences. Deterministic, no model involved."""
    parts = [p.strip() for p in _SENT_SPLIT.split(text.strip()) if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


class UtteranceRecord:
    """One per assistant turn. The brain commits sentences; TTS reports
    word-level completion back. `spoken_text()` is what ACTUALLY left the
    speakers — the only thing the brain may remember."""

    def __init__(self, sentences: list[str]) -> None:
        self.sentences: list[dict] = [
            {"text": s, "status": "queued", "spoken_words": []} for s in sentences
        ]
        self.interrupted: bool = False

    @classmethod
    def from_text(cls, text: str) -> "UtteranceRecord":
        return cls(segment_sentences(text))

    def spoken_text(self) -> str:
        words: list[str] = []
        for s in self.sentences:
            words.extend(s["spoken_words"])
        return " ".join(words)

    def mark_interrupted(self, at_sentence: int) -> None:
        """Current sentence -> INTERRUPTED, the rest -> SKIPPED."""
        self.interrupted = True
        for i, s in enumerate(self.sentences):
            if i < at_sentence:
                if s["status"] != "spoken":
                    s["status"] = "spoken"
            elif i == at_sentence:
                s["status"] = "interrupted"
            else:
                s["status"] = "skipped"


# --------------------------------------------------------------------------- #
# Echo guard: exists BEFORE the speaker, injected everywhere (anti-C-V1)
# --------------------------------------------------------------------------- #

class EchoGuard:
    """Watches TTS state. While speaking: mic muted. After stop: adaptive
    tail during which the wake sink stays muted."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._tail_ms = ECHO_TAIL_MS
        self._speaking = False
        self._tail_until = 0.0
        self._clean_turns = 0

    # -- the callback the Speaker is constructed with ---------------------- #
    def on_tts_state(self, state: str) -> None:
        if state == "speaking":
            self._speaking = True
        else:  # -> idle
            self._speaking = False
            self._tail_until = self._clock() + self._tail_ms / 1000.0

    # -- queries used by the mic coordinator -------------------------------- #
    def mic_muted(self) -> bool:
        """True while TTS is speaking OR inside the adaptive tail."""
        if self._speaking:
            return True
        return self._clock() < self._tail_until

    def is_speaking(self) -> bool:
        return self._speaking

    # -- tail adaptation (M-V20: the constant is a default, not a law) ------ #
    def echo_detected(self) -> None:
        """Our own voice came back through the mic: grow the tail."""
        self._tail_ms = min(self._tail_ms + 200, ECHO_TAIL_MAX_MS)
        self._clean_turns = 0

    def turn_completed_clean(self) -> None:
        """A full turn with no echo detection: maybe shrink the tail."""
        self._clean_turns += 1
        if self._clean_turns >= CLEAN_TURNS_TO_SHRINK:
            self._tail_ms = max(self._tail_ms - 100, ECHO_TAIL_MIN_MS)
            self._clean_turns = 0

    @property
    def tail_ms(self) -> int:
        return self._tail_ms


# --------------------------------------------------------------------------- #
# Speaker: REQUIRES on_state. No default, no None. (anti-C-V1)
# --------------------------------------------------------------------------- #

class Speaker:
    """Owns TTS playback. Constructed WITH its echo-guard callback —
    a speaker without a guard cannot exist."""

    def __init__(
        self,
        on_state: Callable[[str], None],
        audio_out: Optional[Callable[[str, int, int], None]] = None,
        barge_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        if on_state is None:
            raise VoiceError(
                "Speaker requires an on_state callback (echo guard). "
                "Pass guard.on_tts_state — there is no silent default."
            )
        self._on_state = on_state
        self._audio_out = audio_out or (lambda word, si, wi: None)
        self._barge_check = barge_check
        self._stop_requested = False
        self._state = "idle"

    # -- state -------------------------------------------------------------- #
    def _set_state(self, state: str) -> None:
        self._state = state
        self._on_state(state)  # the guard hears every transition

    def is_speaking(self) -> bool:
        return self._state == "speaking"

    # -- the anti-C-V2 stop protocol ---------------------------------------- #
    def stop(self) -> None:
        """Signal, kill the stream, drop the queue, CLEAR THE FLAG ITSELF,
        then go idle. The flag is cleared here — not by some unreachable
        future code path (that was the v1 permanent-mute bug)."""
        self._stop_requested = True   # signal, not a latch
        # (real backend: join worker, abort audio device here)
        self._stop_requested = False  # <-- THE LINE v1 was missing
        self._set_state("idle")       # guard hears it -> tail mute starts

    def say(self, record: UtteranceRecord) -> str:
        """Speak every sentence. Returns 'spoken' or 'interrupted'."""
        if self._stop_requested:
            raise VoiceError("say() called with stop flag set — refusing")
        self._set_state("speaking")
        try:
            for si, sent in enumerate(record.sentences):
                sent["status"] = "speaking"
                for wi, word in enumerate(sent["text"].split()):
                    if self._stop_requested:
                        break
                    self._audio_out(word, si, wi)  # word leaves the speakers
                    sent["spoken_words"].append(word)
                    if self._barge_check is not None and self._barge_check():
                        record.mark_interrupted(si)
                        self.stop()  # clears its own flag, notifies guard
                        return "interrupted"
                else:
                    sent["status"] = "spoken"
                    continue
                break
            return "spoken"
        finally:
            if self._state != "idle":
                self._set_state("idle")


# --------------------------------------------------------------------------- #
# Barge-in: novel words, never energy alone (AGENTS.md barge-in rule)
# --------------------------------------------------------------------------- #

_WORD = re.compile(r"[a-z0-9']+")


def _tokenize(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class BargeInDetector:
    """Compares mic partials against what the TTS actually spoke.
    >=70% word-match -> echo (keep ignoring). >=3 novel words -> interrupt.
    Hard phrases ('stop!') yield immediately."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._novel: set[str] = set()

    def check(self, partial_text: str, spoken_text: str) -> str:
        """Returns 'echo' | 'interrupt' | 'ignore'."""
        words = _tokenize(partial_text)
        if not words:
            return "ignore"
        spoken = set(_tokenize(spoken_text))

        # Echo first: our own voice coming back must never interrupt.
        if spoken:
            match = sum(1 for w in words if w in spoken)
            if match / len(words) >= BARGE_MATCH_RATIO:
                return "echo"

        # Hard interrupt phrases bypass the accumulator (M-V14).
        low = partial_text.lower()
        if any(p in low for p in HARD_INTERRUPT_PHRASES):
            return "interrupt"

        # The accumulator: genuinely new words, building up.
        self._novel.update(w for w in words if w not in spoken)
        if len(self._novel) >= BARGE_NOVEL_WORDS:
            return "interrupt"
        return "ignore"


# --------------------------------------------------------------------------- #
# Outcomes
# --------------------------------------------------------------------------- #

@dataclass
class WakeOutcome:
    status: str  # "wake" | "false_accept" | "mic_closed"
    word: str = ""
    which: str = ""  # "local" | "cloud"
    score: float = 0.0


@dataclass
class TurnOutcome:
    status: str  # "completed" | "interrupted" | "no_speech" | "error"
    reply_text: str = ""
    spoken_text: str = ""     # what ACTUALLY left the speakers
    interrupt_text: str = ""  # what the user said to interrupt
    latency_s: float = 0.0
    latency_breach: bool = False
    stages: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# The loop: the 8-stage graph as one controller
# --------------------------------------------------------------------------- #

class VoiceLoop:
    """Owns the full loop: MIC -> VAD -> WAKE -> COLLECT -> STT -> BRAIN
    -> TTS -> SPEAKERS, plus the echo guard and barge-in detector.

    All hardware is injected, so tests fake every stage. Real backends
    (faster-whisper, Kokoro/Voicebox, openWakeWord) plug into the same
    callables — the loop never imports audio libraries itself (R1)."""

    def __init__(
        self,
        *,
        mic_fn: Callable[[], Any],                    # -> stream with read()/close()
        vad_fn: Callable[[Any], bool],                # chunk -> speech?
        wake_fn: Callable[[Any], dict],               # chunk -> {detected, score, word}
        stt_fn: Callable[[bytes], dict],              # audio -> {text, words, confidence}
        brain_fn: Callable[[str], str],                # text -> reply text
        audio_out: Optional[Callable[[str, int, int], None]] = None,
        partial_fn: Optional[Callable[[], Optional[str]]] = None,
        signal_fn: Optional[Callable[[str], None]] = None,
        clock: Callable[[], float] = time.monotonic,
        date_fn: Callable[[], date] = date.today,
        data_dir: Optional[Path] = None,
        session_store: Any = None,
    ) -> None:
        self._mic_fn = mic_fn
        self._vad_fn = vad_fn
        self._wake_fn = wake_fn
        self._stt_fn = stt_fn
        self._brain_fn = brain_fn
        self._partial_fn = partial_fn
        self._signal = signal_fn or (lambda stage: None)
        self._clock = clock
        self._date_fn = date_fn
        self._data_dir = Path(data_dir) if data_dir else None
        self._store = session_store

        # Guard FIRST, speaker SECOND, wiring verified THIRD (anti-C-V1).
        self.guard = EchoGuard(clock=clock)
        self.speaker = Speaker(
            self.guard.on_tts_state,   # required: no default, no None
            audio_out=audio_out,
            barge_check=self._check_barge_in,
        )
        self.detector = BargeInDetector()
        self._verify_wiring()
        self._record: Optional[UtteranceRecord] = None

        self._last_wake_at = float("-inf")  # first wake is never "double-fire"
        self._wake_stats = self._load_wake_stats()

    # -- startup wiring test: the callback chain must be live (R12) --------- #
    def _verify_wiring(self) -> None:
        if self.speaker._on_state != self.guard.on_tts_state:  # noqa: SLF001
            raise VoiceError(
                "voice plugin refuses to load: echo guard not wired to speaker"
            )

    @staticmethod
    def verify_pair(speaker: Speaker, guard: EchoGuard) -> None:
        """Wiring test for any speaker/guard pair (re-runs after rebuilds)."""
        if speaker._on_state != guard.on_tts_state:  # noqa: SLF001
            raise VoiceError("echo guard not wired to speaker")

    # -- session events (logging never breaks the loop) ---------------------- #
    def _emit(self, session_id: Optional[str], etype: str,
              payload: dict, actor: str = "system") -> None:
        if self._store is None:
            return
        try:
            self._store.emit(session_id or "voice", etype, payload,
                             actor=actor, trust="system")
        except Exception:
            pass

    def _stage(self, session_id: Optional[str], name: str) -> None:
        """No-dead-air rule: every loop state has a signal (§4.2)."""
        self._signal(name)
        self._emit(session_id, "voice.stage", {"stage": name})

    # -- barge-in hook called by the Speaker after every word ---------------- #
    def _check_barge_in(self) -> bool:
        if self._partial_fn is None or self._record is None:
            return False
        partial = self._partial_fn()
        if not partial:
            return False
        verdict = self.detector.check(partial, self._record.spoken_text())
        if verdict == "echo":
            self.guard.echo_detected()  # our own voice bled through: adapt
            return False
        if verdict == "interrupt":
            self._interrupt_text = partial
            return True
        return False

    # ===================================================================== #
    # WAKE
    # ===================================================================== #
    def wait_for_wake(self, session_id: Optional[str] = None) -> WakeOutcome:
        """Block until 'jarvis'. The wake sink is
        hard-muted while TTS speaks and through the adaptive tail."""
        stream = self._mic_fn()
        try:
            while True:
                chunk = stream.read()
                if chunk is None:
                    return WakeOutcome(status="mic_closed")
                if self.guard.mic_muted():
                    continue  # our own voice must never wake us (H-V8, C-V3)
                res = self._wake_fn(chunk) or {}
                if not res.get("detected"):
                    continue
                now = self._clock()
                if now - self._last_wake_at < WAKE_COOLDOWN_S:
                    continue  # anti-double-fire
                self._last_wake_at = now
                word = str(res.get("word", ""))
                which = "cloud" if word == WAKE_CLOUD else "local"
                self._stage(session_id, "wake")
                if not self._confirm_speech(stream):
                    self._false_accept(session_id, word)
                    return WakeOutcome(status="false_accept", word=word,
                                       which=which,
                                       score=float(res.get("score", 0.0)))
                self._emit(session_id, "voice.wake",
                           {"word": word, "which": which,
                            "score": float(res.get("score", 0.0))})
                return WakeOutcome(status="wake", word=word, which=which,
                                   score=float(res.get("score", 0.0)))
        finally:
            stream.close()

    def _confirm_speech(self, stream: Any, window_s: float = 3.0) -> bool:
        """A wake with no speech after it is a false accept."""
        deadline = self._clock() + window_s
        while self._clock() < deadline:
            chunk = stream.read()
            if chunk is None:
                return False
            try:
                if self._vad_fn(chunk):
                    return True
            except Exception:
                return False
        return False

    def _false_accept(self, session_id: Optional[str], word: str) -> None:
        today = self._date_fn().isoformat()
        st = self._wake_stats
        if st.get("date") != today:
            st = {"date": today, "false_accepts": 0, "wakes": 0}
            self._wake_stats = st
        st["false_accepts"] += 1
        self._save_wake_stats()
        self._emit(session_id, "voice.false_accept",
                   {"word": word, "count_today": st["false_accepts"]})
        if st["false_accepts"] > FALSE_ACCEPT_NOTE_AT:
            note = (f"{st['false_accepts']} false wakes today — "
                    "consider recalibrating the wake threshold, sir.")
            self._emit(session_id, "voice.sensitivity_note", {"note": note})

    def _load_wake_stats(self) -> dict:
        if self._data_dir is None:
            return {}
        try:
            p = self._data_dir / "wake_stats.json"
            if p.exists():
                return json.loads(p.read_text())
        except Exception:
            pass
        return {}

    def _save_wake_stats(self) -> None:
        if self._data_dir is None:
            return
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            p = self._data_dir / "wake_stats.json"
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._wake_stats))
            tmp.replace(p)
        except Exception:
            pass

    # ===================================================================== #
    # COLLECT -> STT -> BRAIN -> TTS -> SPEAKERS: one full turn
    # ===================================================================== #
    def run_turn(self, session_id: Optional[str] = None) -> TurnOutcome:
        """One voice turn after the wake word. Returns what happened,
        including — on interrupt — only the words actually spoken."""
        stages: dict = {}
        stream = self._mic_fn()
        try:
            # -- COLLECT ---------------------------------------------------- #
            self._stage(session_id, "listening")
            audio = self._collect(stream)
            if not audio:
                return TurnOutcome(status="no_speech", stages=stages)

            # -- STT -> BRAIN, timed against the latency budget ------------ #
            self._stage(session_id, "transcribing")
            t_stt = self._clock()
            try:
                stt = self._stt_fn(audio) or {}
            except Exception as exc:
                return TurnOutcome(status="error", stages=stages,
                                   reply_text=f"stt failed: {exc}")
            stages["stt_s"] = round(self._clock() - t_stt, 3)
            text = str(stt.get("text", "")).strip()
            if not text:
                return TurnOutcome(status="no_speech", stages=stages)

            self._stage(session_id, "thinking")
            t_brain = self._clock()
            try:
                reply = self._brain_fn(text)
            except Exception as exc:
                return TurnOutcome(status="error", stages=stages,
                                   reply_text=f"brain failed: {exc}")
            stages["brain_s"] = round(self._clock() - t_brain, 3)

            # -- TTS -> SPEAKERS -------------------------------------------- #
            return self.speak_text(str(reply), session_id=session_id,
                                   stages=stages, t_stt=t_stt)
        finally:
            stream.close()

    def speak_text(self, text: str,
                   session_id: Optional[str] = None,
                   stages: Optional[dict] = None,
                   t_stt: Optional[float] = None) -> TurnOutcome:
        """The single choke point for ALL speech (M-V2): scheduler, watcher,
        and chat all speak through here — never the speaker directly."""
        stages = stages or {}
        self._interrupt_text = ""
        self.detector.reset()
        record = UtteranceRecord.from_text(text)
        self._record = record

        first_audio_at: list = []

        prev_out = self.speaker._audio_out  # noqa: SLF001

        def _out(word: str, si: int, wi: int) -> None:
            if not first_audio_at:
                first_audio_at.append(self._clock())
            prev_out(word, si, wi)

        self.speaker._audio_out = _out  # noqa: SLF001
        self._stage(session_id, "speaking")
        try:
            result = self.speaker.say(record)
        finally:
            self.speaker._audio_out = prev_out  # noqa: SLF001
            self._record = None

        spoken = record.spoken_text()
        latency = ((first_audio_at[0] - t_stt)
                   if (first_audio_at and t_stt is not None) else 0.0)
        breach = latency > LATENCY_BUDGET_S
        stages["first_audio_s"] = round(latency, 3)
        if breach:
            # Degradation is announced, never silent (§4.2).
            self._emit(session_id, "voice.latency_breach",
                       {"total_s": round(latency, 3), **stages})

        if result == "interrupted":
            # Trace surgery: the brain forgets every word never spoken (M-V16).
            self._emit(session_id, "voice.turn_interrupted",
                       {"spoken_text": spoken,
                        "interrupt_text": self._interrupt_text,
                        "full_reply": text})
            self.guard.turn_completed_clean()
            return TurnOutcome(status="interrupted", reply_text=text,
                               spoken_text=spoken,
                               interrupt_text=self._interrupt_text,
                               latency_s=latency, latency_breach=breach,
                               stages=stages)

        self._emit(session_id, "voice.turn_completed",
                   {"spoken_text": spoken, "latency_s": round(latency, 3)})
        self.guard.turn_completed_clean()
        return TurnOutcome(status="completed", reply_text=text,
                           spoken_text=spoken, latency_s=latency,
                           latency_breach=breach, stages=stages)

    def _collect(self, stream: Any) -> bytes:
        """Gather one utterance: 500ms pre-roll, 700ms trailing-silence
        endpoint, 30s hard cap that closes at the last chunk."""
        chunks: list = []
        pre_roll: deque = deque(maxlen=PRE_ROLL_CHUNKS)
        speech_seen = False
        silence_s = 0.0
        start = self._clock()
        wrapping_noted = False

        while True:
            chunk = stream.read()
            if chunk is None:
                break
            if self.guard.mic_muted():
                continue  # our own voice never enters the collector (C-V4)
            pre_roll.append(chunk)
            try:
                speech = bool(self._vad_fn(chunk))
            except Exception:
                speech = False
            if speech:
                if not speech_seen:
                    chunks.extend(pre_roll)  # onset kept: no clipping (H-V6)
                    speech_seen = True
                else:
                    chunks.append(chunk)
                silence_s = 0.0
            elif speech_seen:
                chunks.append(chunk)
                silence_s += CHUNK_S
                if silence_s >= TRAILING_SILENCE_S:
                    break  # endpoint: measured silence, not a fixed include
            elapsed = self._clock() - start
            if elapsed >= COLLECT_CAP_S - 2.0 and not wrapping_noted:
                wrapping_noted = True  # "wrapping up…" moment (M-V9)
            if elapsed >= COLLECT_CAP_S:
                break  # cap: closes at the last chunk, never mid-word-cut here
        return b"".join(c if isinstance(c, (bytes, bytearray)) else b"" for c in chunks)
