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

try:
    from jarvis.speech_policy import clean_for_tts
except Exception:  # pragma: no cover - in-repo, stdlib-only; belt and braces
    # The speech policy must never be able to take the voice loop down
    # with it: if it cannot even be imported, speech falls back to raw.
    clean_for_tts = None  # type: ignore[assignment]

try:
    from jarvis.translit import canonicalize as _canonicalize
except Exception:  # pragma: no cover - in-repo, stdlib-only; belt and braces
    _canonicalize = None  # type: ignore[assignment]

try:
    from jarvis.endpointing import EndpointPolicy
except Exception:  # pragma: no cover - in-repo, stdlib-only; belt and braces
    # Learned endpointing is an upgrade, not a dependency: without it
    # the loop falls back to the fixed TRAILING_SILENCE_S constant.
    EndpointPolicy = None  # type: ignore[assignment]

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

TRAILING_SILENCE_S = 0.7      # endpointing seed: the learned policy's starting point
COLLECT_CAP_S = 30.0          # hard cap; closes at the last chunk, never mid-word-cut here
CHUNK_S = 0.02                # mic chunks are 20ms
PRE_ROLL_CHUNKS = 25          # 500ms pre-roll so onsets are never clipped (H-V6)

BARGE_HOLD_GATE_S = 0.35      # protoVoice hold: unconfirmed candidates are on probation this long
VAD_ERROR_STREAK_MAX = 25     # consecutive VAD failures (~0.5s of chunks) = recognizer is dead
FALSE_EOT_GAP_S = 2.0         # owner resumes within this of an endpoint -> the endpoint was false
MIN_PAUSE_OBSERVATION_S = 0.3  # shorter gaps are not pause habits; longer
MAX_PAUSE_OBSERVATION_S = 30.0  # ones are absences, not pauses

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


def speakable_sentences(text: str) -> list[str]:
    """The units that may actually leave the speakers.

    Every raw sentence passes the speech policy (jarvis.speech_policy.
    clean_for_tts): markdown is stripped, secrets are redacted, and the
    sentence is re-chunked for speech — the returned chunks REPLACE the
    raw sentence, in order. A sentence whose cleaned form is empty
    (e.g. a bare code fence: written content, not speech) contributes
    nothing and is simply never spoken. If the policy itself raises,
    the raw sentence is used as-is: cleaning must never break speech,
    and must never silence it either."""
    raw = segment_sentences(text)
    if clean_for_tts is None:
        return raw
    units: list[str] = []
    for sentence in raw:
        try:
            units.extend(clean_for_tts(sentence))
        except Exception:
            units.append(sentence)  # broken cleaner -> raw, never silence
    return units


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


def _interrupted_index(record: UtteranceRecord) -> int:
    """First sentence marked interrupted, or -1."""
    for i, s in enumerate(record.sentences):
        if s["status"] == "interrupted":
            return i
    return -1


def _last_spoken_sentence(record: UtteranceRecord) -> str:
    """The last sentence the user ACTUALLY heard — for the interrupt note.

    Uses the partially spoken words of the interrupted sentence: if the
    user cut in mid-sentence, "the weather is su—" is what they heard,
    and that is what the brain must know. "" if nothing was spoken yet.
    """
    for i in reversed(range(len(record.sentences))):
        words = record.sentences[i]["spoken_words"]
        if words:
            return " ".join(words)
    return ""

# --------------------------------------------------------------------------- #
# Barge-in: novel words, never energy alone (AGENTS.md barge-in rule)
# --------------------------------------------------------------------------- #

_WORD = re.compile(r"[a-z0-9']+")


def _tokenize(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class BargeInDetector:
    """Compares mic partials against what the TTS actually spoke.
    >=70% word-match -> echo (keep ignoring). >=3 novel words -> interrupt.
    Hard phrases ('stop!') yield immediately.

    ECHO SALVAGE (isair/ethanplusai pattern): users often START answering
    while our voice is still ringing through the mic, so the transcript is
    echo PREFIX + real speech tail. Discarding the whole transcript throws
    away the user's actual words; treating the tail as 3+ novel words is
    what saves them. salvage() strips only the echo prefix (iteratively,
    word by word, so one mis-heard word doesn't abort the strip) and the
    tail is judged on its own merits.
    """

    def __init__(self, salvage: bool = True) -> None:
        self._salvage_on = salvage
        self.last_salvage: str = ""   # tail salvaged by the latest check
        self.reset()

    def reset(self) -> None:
        self._novel: set[str] = set()
        self.last_salvage = ""

    @staticmethod
    def salvage(partial_text: str, spoken_text: str) -> str:
        """Strip the maximal leading run of echo words from a transcript.

        A word counts as echo if it appears ANYWHERE in the spoken text
        (the same set-membership the ratio check uses — ASR reorders).
        The strip is ITERATIVE: a word moves into the remainder only when
        it is not echo, and stripping stops there. A pure-echo transcript
        salvages to "". Pure function — safe to call anywhere."""
        words = _tokenize(partial_text)
        if not words:
            return ""
        spoken = set(_tokenize(spoken_text))
        i = 0
        while i < len(words) and words[i] in spoken:
            i += 1
        return " ".join(words[i:])

    def pop_salvage(self) -> str:
        """Return and clear the tail salvaged by the interrupt verdict."""
        tail, self.last_salvage = self.last_salvage, ""
        return tail

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
                # Salvage: an echo PREFIX with a real-speech TAIL is the
                # user answering over our voice. Strip the echo, judge
                # the tail — never discard the whole transcript.
                if self._salvage_on:
                    tail = self.salvage(partial_text, spoken_text)
                    if tail:
                        self._novel.update(
                            w for w in _tokenize(tail) if w not in spoken)
                        if len(self._novel) >= BARGE_NOVEL_WORDS:
                            self.last_salvage = tail
                            return "interrupt"
                        return "ignore"  # tail noted, not yet an interrupt
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
# Barge-in classification (Team 7 pack): backchannels vs strong commands
# --------------------------------------------------------------------------- #
# ONE data table, extended by editing these tuples only. Entries are
# written the way a human says/types them (English, roman Hinglish,
# Devanagari); matching happens on CANONICALIZED text (jarvis.translit),
# so "हाँ" and "haan" land in the same bucket and spelling variants
# collapse before comparison. The canonical lookup sets are built once,
# at import, by running every entry through the same canonicalizer the
# input goes through — the two sides can never drift apart.

BACKCHANNEL_PHRASES = (
    # English listener noises: acknowledgement, never a takeover.
    "yeah", "uh-huh", "uh huh", "hmm", "mm-hmm", "ok", "okay",
    # Roman Hinglish listener noises.
    "haan", "accha", "theek", "sahi", "ji",
    "theek hai", "haan ji", "accha ji",
    # Devanagari — canonicalize() maps these onto roman forms.
    "जी", "हाँ", "अच्छा", "ठीक", "सही",
)

STRONG_INTERRUPT_PHRASES = (
    # Commands that cut speech IMMEDIATELY, hold-gate bypassed: the
    # owner is not commenting, they are taking the floor back.
    "stop", "ruko", "bas", "cancel", "chup",
    "shut up", "never mind", "quiet", "enough",
    "रुको", "बस", "बंद करो", "चुप",
)

_PUNCT_STRIP = re.compile(r"[।,.!?;:\"'“”‘’()\[\]{}<>…-]+")


def _canon(text: str) -> str:
    """Canonicalize for classification. Uses jarvis.translit when it is
    importable; the fallback (lowercase, strip punctuation, collapse
    whitespace) keeps classification alive — weaker on Devanagari, but
    never an import error in the speech path."""
    if _canonicalize is not None:
        try:
            return _canonicalize(text)
        except Exception:
            pass
    return " ".join(_PUNCT_STRIP.sub(" ", (text or "").lower()).split())


def _phrase_tokens(phrases: tuple) -> list:
    """Canonical token runs for a phrase table, longest first (so a
    two-word phrase wins over its own first word)."""
    runs = [tuple(_canon(p).split()) for p in phrases]
    return sorted({r for r in runs if r}, key=len, reverse=True)


_BACKCHANNEL_RUNS = _phrase_tokens(BACKCHANNEL_PHRASES)
_STRONG_RUNS = _phrase_tokens(STRONG_INTERRUPT_PHRASES)


def _contains_run(tokens: list, run: tuple) -> bool:
    n = len(run)
    return any(tuple(tokens[i:i + n]) == run
               for i in range(len(tokens) - n + 1))


def _consumes_all(tokens: list, runs: list) -> bool:
    """True iff EVERY token belongs to some phrase run (greedy,
    longest-first). A single foreign word disqualifies the utterance:
    'haan' is a backchannel, 'haan ek kaam karo' is a command."""
    i = 0
    while i < len(tokens):
        for run in runs:
            if tuple(tokens[i:i + len(run)]) == run:
                i += len(run)
                break
        else:
            return False
    return True


def classify_interrupt(text: str) -> str:
    """Classify a candidate interruption transcript. Pure function.

    Returns:
      "interrupt"   — a STRONG command is present anywhere in the text
                      (checked first, streamcore's rule: "okay stop"
                      interrupts even though "okay" is a backchannel).
      "backchannel" — the WHOLE utterance is listener noise and nothing
                      else (yeah / haan / अच्छा / theek hai...). A
                      backchannel NEVER interrupts, no matter how many
                      novel words it has for the echo guard.
      "ignore"      — neither: the novel-word detector makes its own
                      call; classification has no opinion.
    """
    tokens = _canon(text).split()
    if not tokens:
        return "ignore"
    for run in _STRONG_RUNS:
        if _contains_run(tokens, run):
            return "interrupt"
    if _consumes_all(tokens, _BACKCHANNEL_RUNS):
        return "backchannel"
    return "ignore"


class InterruptHoldGate:
    """protoVoice's 350 ms hold-gate, translated to this loop.

    protoVoice holds a UserStartedSpeaking FRAME for 350 ms: if the
    user stops inside the window the frame is suppressed; if a real
    transcript arrives inside the window it flushes immediately; on
    timeout it flushes as a normal interrupt. v2's barge-in polls are
    per-word transcript checks, so the same semantics land as EPISODE
    PROBATION:

      - A candidate episode OPENS at the first non-echo partial.
      - While the episode is younger than the hold window its words
        are on probation: if the episode evaporates (partials stop),
        the detector state it touched is rolled back — a cough, a TV
        blip, a one-word noise leaves NO trace in the accumulator.
      - A CONFIRMED verdict (novel words / salvage / strong command)
        flushes immediately, exactly like protoVoice's transcript
        flush — the hold governs unconfirmed candidates, never real
        words the detector has already judged.
      - An episode still alive at the end of the window GRADUATES:
        its words are real speech and stay in the accumulator.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 hold_s: float = BARGE_HOLD_GATE_S) -> None:
        self._clock = clock
        self._hold_s = float(hold_s)
        self._since: Optional[float] = None

    @property
    def active(self) -> bool:
        return self._since is not None

    def begin(self) -> None:
        """Open an episode (idempotent: an open episode keeps its age)."""
        if self._since is None:
            self._since = self._clock()

    def age_s(self) -> float:
        if self._since is None:
            return 0.0
        return self._clock() - self._since

    def graduated(self) -> bool:
        """The episode has persisted past the hold window."""
        return self.active and self.age_s() >= self._hold_s

    def clear(self) -> None:
        self._since = None


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
    last_spoken_sentence: str = ""  # interrupt note: last sentence heard
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

        # Voice pack: learned endpointing (jarvis.endpointing). The old
        # constant becomes the policy's SEED — with no learned data the
        # capture path behaves exactly as before; observations move it.
        self.endpoint_policy = (
            EndpointPolicy(data_dir=self._data_dir, seed_s=TRAILING_SILENCE_S)
            if EndpointPolicy is not None else None
        )
        # Voice pack: barge-in hold-gate + candidate-episode probation.
        self._hold_gate = InterruptHoldGate(clock=clock)
        self._episode_snapshot: Optional[tuple] = None
        # Voice pack: pause-habit bookkeeping for the endpoint policy.
        self._last_activity_end: Optional[float] = None
        self._prev_endpoint_silence: Optional[float] = None

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

    # -- candidate episodes (hold-gate probation) ---------------------------- #
    def _open_episode(self) -> None:
        """A candidate episode opens at the first non-echo partial.
        Snapshot the detector: words spoken by an episode that dies
        inside the hold window are rolled back out of the accumulator,
        so a blip can never combine with later noise into a phantom
        interrupt."""
        if not self._hold_gate.active:
            self._episode_snapshot = (
                frozenset(self.detector._novel),  # noqa: SLF001
                self.detector.last_salvage,
            )
            self._hold_gate.begin()

    def _close_episode(self, *, graduate: bool) -> None:
        """Close the episode. graduate=False + still on probation ->
        restore the detector snapshot (the episode leaves no trace).
        Graduated (or already-graduated) episodes keep their words."""
        if (not graduate and self._episode_snapshot is not None
                and not self._hold_gate.graduated()):
            novel, salvage = self._episode_snapshot
            self.detector._novel = set(novel)  # noqa: SLF001
            self.detector.last_salvage = salvage
        self._episode_snapshot = None
        self._hold_gate.clear()

    def _reset_episode(self) -> None:
        """New speech, new probation: drop episode state without
        touching the (freshly reset) detector."""
        self._episode_snapshot = None
        self._hold_gate.clear()

    # -- barge-in hook called by the Speaker after every word ---------------- #
    def _check_barge_in(self) -> bool:
        if self._partial_fn is None or self._record is None:
            return False
        partial = self._partial_fn()
        if not partial:
            # The candidate evaporated. If it was still on probation,
            # its words are rolled back — it never happened.
            self._close_episode(graduate=False)
            return False
        # Snapshot BEFORE the detector sees this partial: rollback must
        # be able to restore the state as of the episode's first word.
        self._open_episode()
        verdict = self.detector.check(partial, self._record.spoken_text())
        if verdict == "echo":
            self.guard.echo_detected()  # our own voice bled through: adapt
            self._close_episode(graduate=True)  # echo itself adds nothing
            return False
        # Classification composes with the novel-word rule (never
        # replaces it): strong commands cut NOW, backchannels never
        # cut at all — not even when they carry 3+ novel words, which
        # is exactly the "haan accha theek" failure this pack fixes.
        effective = self.detector.last_salvage or partial
        cls = classify_interrupt(effective)
        if cls == "backchannel":
            self._close_episode(graduate=False)
            return False
        if verdict == "interrupt" or cls == "interrupt":
            # protoVoice flush: a transcript the detector has CONFIRMED
            # (or a strong command) inside the window is real words —
            # the hold never delays it.
            salvaged = self.detector.pop_salvage()
            self._interrupt_text = salvaged if salvaged else partial
            self._close_episode(graduate=True)
            return True
        # Unconfirmed candidate: on probation. If it has persisted
        # past the hold window it graduates — its words are the owner
        # really speaking and stay in the accumulator.
        if self._hold_gate.graduated():
            self._close_episode(graduate=True)
            self._open_episode()  # speech continues; new probation window
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
            audio = self._collect(stream, session_id=session_id)
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
        and chat all speak through here — never the speaker directly.

        The record is built from the SPEECH-POLICY-CLEANED sentences
        (speakable_sentences -> clean_for_tts), so the Utterance Record —
        and therefore spoken_text(), the only text the brain may
        remember — is the cleaned text: exactly what left the speakers,
        never raw markdown and never a secret."""
        stages = stages or {}
        self._interrupt_text = ""
        self.detector.reset()
        self._reset_episode()
        record = UtteranceRecord(speakable_sentences(text))
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
            # The owner's next pause can only start once we stop
            # talking: endpointing observations measure from here.
            self._last_activity_end = self._clock()

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
            # Interrupt note (eadmin2 pattern): persist the last sentence
            # the user ACTUALLY heard into the session events, so the
            # brain's next turn knows exactly where its reply was cut and
            # never "remembers" words that never left the speakers.
            last_heard = _last_spoken_sentence(record)
            at_sentence = _interrupted_index(record)
            self._emit(session_id, "voice.interrupt_note",
                       {"last_spoken_sentence": last_heard,
                        "at_sentence": at_sentence,
                        "spoken_text": spoken,
                        "interrupt_text": self._interrupt_text})
            # Trace surgery: the brain forgets every word never spoken (M-V16).
            self._emit(session_id, "voice.turn_interrupted",
                       {"spoken_text": spoken,
                        "interrupt_text": self._interrupt_text,
                        "full_reply": text})
            self.guard.turn_completed_clean()
            return TurnOutcome(status="interrupted", reply_text=text,
                               spoken_text=spoken,
                               interrupt_text=self._interrupt_text,
                               last_spoken_sentence=last_heard,
                               latency_s=latency, latency_breach=breach,
                               stages=stages)

        self._emit(session_id, "voice.turn_completed",
                   {"spoken_text": spoken, "latency_s": round(latency, 3)})
        self.guard.turn_completed_clean()
        return TurnOutcome(status="completed", reply_text=text,
                           spoken_text=spoken, latency_s=latency,
                           latency_breach=breach, stages=stages)

    def _endpoint_threshold(self) -> float:
        """The silence that ends an utterance: the learned policy's
        threshold when endpointing is available, else the seed
        constant (identical behavior before anything is learned)."""
        if self.endpoint_policy is not None:
            return self.endpoint_policy.threshold_s
        return TRAILING_SILENCE_S

    def _observe_user_pause(self) -> None:
        """Feed the endpoint policy the gap since activity last ended.

        Called at the moment speech starts in a collection: the gap is
        the owner's between-utterance pause. If the previous collection
        ended on an endpoint AND the owner is already back inside
        FALSE_EOT_GAP_S, that endpoint was false — they were
        mid-thought — so the policy learns their FULL pause (the
        trailing silence we allowed + this gap) and its floor ratchets
        up. Absurd gaps (owner walked away) teach nothing.
        """
        if self.endpoint_policy is None or self._last_activity_end is None:
            return
        gap = self._clock() - self._last_activity_end
        prev_silence, self._prev_endpoint_silence = (
            self._prev_endpoint_silence, None)
        if not (MIN_PAUSE_OBSERVATION_S <= gap <= MAX_PAUSE_OBSERVATION_S):
            return
        if prev_silence is not None and gap < FALSE_EOT_GAP_S:
            self.endpoint_policy.observe_false_eot(prev_silence + gap)
        else:
            self.endpoint_policy.observe_pause(gap)

    def _collect(self, stream: Any,
                 session_id: Optional[str] = None) -> bytes:
        """Gather one utterance: 500ms pre-roll, learned trailing-silence
        endpoint (seed 700ms), 30s hard cap that closes at the last chunk.

        VAD GUARD: if the recognizer stream dies mid-utterance (read
        raises) or the VAD itself fails in a long streak, collection
        ends with whatever was already heard — the partial utterance
        is preserved and STILL goes to STT, and the degradation is
        logged as a session event. A dead recognizer must never
        vaporise words the owner already said."""
        chunks: list = []
        pre_roll: deque = deque(maxlen=PRE_ROLL_CHUNKS)
        speech_seen = False
        silence_s = 0.0
        start = self._clock()
        wrapping_noted = False
        threshold = self._endpoint_threshold()
        endpoint_silence: Optional[float] = None
        vad_error_streak = 0

        while True:
            try:
                chunk = stream.read()
            except Exception as exc:
                self._emit(session_id, "voice.vad_guard",
                           {"stage": "collect", "error": str(exc),
                            "chunks_kept": len(chunks),
                            "speech_seen": speech_seen})
                break  # keep the partial utterance; the turn goes on
            if chunk is None:
                break
            if self.guard.mic_muted():
                continue  # our own voice never enters the collector (C-V4)
            pre_roll.append(chunk)
            try:
                speech = bool(self._vad_fn(chunk))
                vad_error_streak = 0
            except Exception:
                speech = False
                vad_error_streak += 1
                if vad_error_streak >= VAD_ERROR_STREAK_MAX:
                    self._emit(session_id, "voice.vad_guard",
                               {"stage": "vad",
                                "error": "vad failed in a long streak",
                                "chunks_kept": len(chunks),
                                "speech_seen": speech_seen})
                    break  # recognizer is dead; keep what we have
            if speech:
                if not speech_seen:
                    self._observe_user_pause()
                    chunks.extend(pre_roll)  # onset kept: no clipping (H-V6)
                    speech_seen = True
                else:
                    chunks.append(chunk)
                silence_s = 0.0
            elif speech_seen:
                chunks.append(chunk)
                silence_s += CHUNK_S
                if silence_s >= threshold:
                    endpoint_silence = silence_s
                    break  # endpoint: measured silence, not a fixed include
            elapsed = self._clock() - start
            if elapsed >= COLLECT_CAP_S - 2.0 and not wrapping_noted:
                wrapping_noted = True  # "wrapping up…" moment (M-V9)
            if elapsed >= COLLECT_CAP_S:
                break  # cap: closes at the last chunk, never mid-word-cut here
        self._last_activity_end = self._clock()
        self._prev_endpoint_silence = endpoint_silence
        return b"".join(c if isinstance(c, (bytes, bytearray)) else b"" for c in chunks)
