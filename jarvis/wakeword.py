"""jarvis.wakeword — unified wake-word engine layer (Extension Team 5).

One protocol, two engines, config picks the winner:

  - ``VoicuteAdapter`` — Voicute onnx-wakeword (MIT, github.com/voicute/
    onnx-wakeword, engine verified from source 2026-10-20). ONE multi-
    keyword ONNX package wakes on {"Hey Jarvis", "Jarvis", "Hi Jarvis"}
    at once — including the BARE "Jarvis" the owner chose — with no
    owner voice training. Package: models/en/multi_jarvis_v9.3.zip =
    132,844 bytes on disk (verified), plus the shared melspectrogram.onnx
    (1,087,958 bytes). The keyword model is a ~25K-param Causal TCN;
    scores are COMPETITIVE (see _softmax_scores) — read the adapter
    docstring before touching thresholds.
  - ``OpenWakeWordAdapter`` — wraps jarvis.stt.OpenWakeWordListener
    (today's behaviour): pre-trained `hey_jarvis` INTERIM until a custom
    `jarvis.onnx` exists; bare "jarvis" via openWakeWord needs that
    trained model.

Frame contract (mirrors jarvis.stt): 16 kHz mono int16 LE PCM frames in
via ``feed_frame()``; detections out as ``WakeDetection`` AND through
the optional ``on_detect`` callback; ``start(iterable)`` runs a feeder
thread for mic-style sources. A shared false-wake cooldown lives in the
base class so both engines behave identically after a fire.

Honesty rules (same as stt.py, non-negotiable):
  - NO ML import at module top level. onnxruntime / numpy / openwakeword
    are imported LAZILY inside the adapters, so `import jarvis.wakeword`
    succeeds on a machine that has none of them.
  - An unavailable engine says WHY (``unavailable_reason()``) and is
    skipped by selection; it never crashes the caller and never fakes a
    detection. onnxruntime stays an OPTIONAL dependency.
  - Upstream quality numbers (Hey Jarvis R1: 99.0% recall, 4.8 false/h
    on a 26.9 h hostile corpus) are Voicute's own README measurements on
    THEIR corpora — promising, unverified on the owner's mic/room.
"""

from __future__ import annotations

import abc
import json
import math
import sys
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

__all__ = [
    "WakeWordError", "WakeDetection", "EngineStatus",
    "WakeWordEngine", "VoicuteAdapter", "OpenWakeWordAdapter",
    "probe_engines", "create_wake_engine",
    "SAMPLE_RATE", "DEFAULT_PREFERENCE",
]


class WakeWordError(Exception):
    """Wake-word layer failed (no engine available, bad model bundle)."""


# --------------------------------------------------------------------------- #
# Constants — the frame contract is stt.py's: 16 kHz mono int16.
# --------------------------------------------------------------------------- #
SAMPLE_RATE = 16000          # == jarvis.stt.SAMPLE_RATE (kept literal so
                             # this module imports with zero side effects)
_FRAME_SAMPLES = 1280       # 80 ms — the hop both engines consume
DEFAULT_PREFERENCE = ("voicute", "openwakeword")


@dataclass(frozen=True)
class WakeDetection:
    """One wake event. `keyword` is the phrase AS SPOKEN ("Jarvis",
    "Hey Jarvis", ...), `score` the engine's post-softmax probability
    for Voicute or the model score for openWakeWord."""
    engine: str
    keyword: str
    score: float
    at: float                # engine clock (monotonic) at fire time
    frame_index: int         # feed_frame() calls seen when it fired


@dataclass(frozen=True)
class EngineStatus:
    name: str
    available: bool
    reason: str              # "" when available; else why not


# --------------------------------------------------------------------------- #
# Base engine — shared cooldown, callback, feeder thread.
# --------------------------------------------------------------------------- #
class WakeWordEngine(abc.ABC):
    """feed_frame(pcm) -> Optional[WakeDetection].

    Adapters return a CANDIDATE (keyword, score) from _feed(); this base
    owns the false-wake cooldown (default 1.5 s, same as stt.WakeListener,
    spec 5.3/M-V12) so a detection fires exactly once per wake event and
    both engines share post-fire behaviour. Clock is injectable.
    """

    name: str = "base"

    def __init__(self, threshold: float = 0.5, cooldown_s: float = 1.5,
                 clock: Callable[[], float] = time.monotonic,
                 on_detect: Optional[Callable[[WakeDetection], None]] = None
                 ) -> None:
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.on_detect = on_detect
        self.last_score = 0.0
        self.last_detection: Optional[WakeDetection] = None
        self._clock = clock
        self._last_fire = float("-inf")
        self._frame_index = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- adapter surface -------------------------------------------------- #
    @abc.abstractmethod
    def available(self) -> bool:
        """True when this engine can actually run on this machine."""

    @abc.abstractmethod
    def unavailable_reason(self) -> str:
        """Why available() is False ("" when available)."""

    @abc.abstractmethod
    def keywords(self) -> List[str]:
        """Wake phrases this engine listens for, as spoken."""

    @abc.abstractmethod
    def _feed(self, pcm: bytes) -> Optional[Tuple[str, float]]:
        """Consume one frame; return (keyword, score) candidate or None."""

    # -- shared behaviour ------------------------------------------------- #
    def feed_frame(self, pcm: bytes) -> Optional[WakeDetection]:
        """Feed one 16 kHz int16 frame. Fires on_detect + returns the
        WakeDetection on a wake; None otherwise (incl. during cooldown).
        A broken/unavailable adapter raises WakeWordError — never a
        silent None that looks like 'no wake'."""
        if not isinstance(pcm, (bytes, bytearray, memoryview)):
            raise TypeError(
                f"pcm frame must be bytes-like, got {type(pcm).__name__}")
        self._frame_index += 1
        candidate = self._feed(bytes(pcm))
        if candidate is None:
            return None
        keyword, score = candidate
        now = self._clock()
        if now - self._last_fire < self.cooldown_s:
            return None  # false-wake cooldown — same for every engine
        self._last_fire = now
        det = WakeDetection(engine=self.name, keyword=keyword,
                            score=float(score), at=now,
                            frame_index=self._frame_index)
        self.last_detection = det
        if self.on_detect is not None:
            self.on_detect(det)
        return det

    def start(self, source: Any) -> threading.Thread:
        """Feed frames from an iterable (e.g. stt.MicStream) on a daemon
        thread; detections go to on_detect. stop() ends the thread after
        the source yields its next frame."""
        if self._thread is not None and self._thread.is_alive():
            return self._thread
        self._stop.clear()

        def _run() -> None:
            for frame in source:
                if self._stop.is_set():
                    break
                self.feed_frame(frame)

        self._thread = threading.Thread(
            target=_run, name=f"wakeword-{self.name}", daemon=True)
        self._thread.start()
        return self._thread

    def stop(self) -> None:
        self._stop.set()

    def reset(self) -> None:
        """Clear cooldown + scores. Adapters extend with their state."""
        self._last_fire = float("-inf")
        self.last_score = 0.0


# --------------------------------------------------------------------------- #
# Voicute adapter — multi-keyword ONNX, bare "Jarvis" included.
# --------------------------------------------------------------------------- #
class VoicuteAdapter(WakeWordEngine):
    """Voicute onnx-wakeword via onnxruntime (LAZY, optional dep).

    Model bundle (format verified from the upstream engine source):
      - a multi-keyword package: either a .zip holding model_info.json +
        the keyword .onnx, or a model_info.json on disk. model_info:
        {"model_type": "multi_keyword", "keywords": [...],
         "model_file": "...", "mel_time": 98, "cons_frames": 2,
         "n_mels": 32}. Legacy single-keyword bundles ("tcn"/"dscnn"
        with wake_word + model_file) are also accepted; the legacy
        multi-MODEL layout is not (honest WakeWordError).
      - melspectrogram.onnx: mel_path= if given, else the file next to
        the package, else [UK] a same-named member inside the zip
        (upstream always ships it as a sibling file; the zip fallback is
        defensive and untested against an upstream bundle).

    Inference glue (our code, upstream format): audio window =
    mel_time*160 + 400 samples (16,080 @ mel_time 98); mel/10.0 + 2.0;
    take the last mel_time mel frames, zero-pad to the model's input
    width resolved from its ONNX input shape (32 cols current-gen);
    raw sigmoid outputs become logits, a background logit of 0 is
    appended, and a softmax over keywords+background yields the score —
    keywords COMPETE, so a 0.9 raw score split between two phrases
    scores ~0.47 each and must NOT fire. Threshold default 0.5 (the
    value upstream's false-trigger tables are measured at); clamped to
    upstream's 0.30..0.95 in set-threshold fashion.

    Detection: upstream's L1 — the same keyword above threshold for
    cons_frames inferences, tolerating gaps of <= 2 inferences
    (MAX_GAP). L2/L4/L5 stay OFF (upstream engine defaults); the base
    class cooldown covers L3's job.
    """

    name = "voicute"

    _MEL_HOP = 160           # 10 ms — upstream MEL_HOP
    _MEL_WIN = 400           # 25 ms — upstream MEL_WIN
    _RAW_MELS = 32           # mel channels — upstream RAW_MELS
    _MAX_GAP = 2             # L1 gap tolerance — upstream MAX_GAP
    _DEFAULT_MEL_TIME = 98

    def __init__(self, model_path: Optional[Any] = None,
                 mel_path: Optional[Any] = None,
                 threshold: float = 0.5, cooldown_s: float = 1.5,
                 cons_frames: Optional[int] = None,
                 clock: Callable[[], float] = time.monotonic,
                 on_detect: Optional[Callable[[WakeDetection], None]] = None
                 ) -> None:
        # Upstream set_threshold clamps to 0.30..0.95 — mirror it.
        threshold = max(0.30, min(0.95, float(threshold)))
        super().__init__(threshold=threshold, cooldown_s=cooldown_s,
                         clock=clock, on_detect=on_detect)
        self._model_path = (Path(model_path) if model_path is not None
                            else self._default_model_path())
        self._mel_path = Path(mel_path) if mel_path is not None else None
        self._cons_override = cons_frames
        self._probe: Optional[Tuple[bool, str]] = None
        self._loaded = False
        self._np: Any = None
        self._mel_sess: Any = None
        self._kw_sess: Any = None
        self._mel_in: str = "input"
        self._kw_in: str = "input"
        self._keywords: List[str] = []
        self._cons_frames: Dict[str, int] = {}
        self._mel_time = self._DEFAULT_MEL_TIME
        self._n_cols = self._RAW_MELS
        self._samples_needed = 0
        self._buf = bytearray()
        self._since_infer = 0
        self._cons_word = ""
        self._cons_count = 0
        self._cons_gap = 0

    @staticmethod
    def _default_model_path() -> Path:
        # Conventional in-repo location: <repo>/models/multi_jarvis_v9.3.zip
        # with melspectrogram.onnx beside it (upstream's models/ layout).
        return (Path(__file__).resolve().parent.parent / "models"
                / "multi_jarvis_v9.3.zip")

    # -- availability ----------------------------------------------------- #
    def _probe_now(self) -> Tuple[bool, str]:
        if self._model_path is None or not Path(self._model_path).exists():
            return False, (f"voicute model package not found: "
                           f"{self._model_path} (download the multi-keyword "
                           f"Jarvis package from voicute/onnx-wakeword)")
        try:
            import numpy  # noqa: F401
        except ImportError:
            return False, ("numpy is not installed. "
                           "Install it with: pip install numpy")
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            return False, ("onnxruntime is not installed. "
                           "Install it with: pip install onnxruntime")
        return True, ""

    def available(self) -> bool:
        if self._probe is None:
            self._probe = self._probe_now()
        return self._probe[0]

    def unavailable_reason(self) -> str:
        if self._probe is None:
            self._probe = self._probe_now()
        return self._probe[1]

    def keywords(self) -> List[str]:
        if self._keywords:
            return list(self._keywords)
        # Pre-load answer from the bundle's model_info.json alone —
        # parsing JSON needs no ML deps, so this works before _load().
        try:
            info, _kw_bytes, _base = self._read_bundle()
            if info.get("model_type") == "multi_keyword":
                return [str(k) for k in info.get("keywords", [])]
            if info.get("wake_word"):
                return [str(info["wake_word"])]
        except WakeWordError:
            pass
        return []

    # -- bundle loading --------------------------------------------------- #
    def _read_bundle(self) -> Tuple[Dict[str, Any], Optional[bytes], Path]:
        """Return (model_info, keyword_onnx_bytes|None, base_dir).
        Bytes are returned when the model lives inside a zip package."""
        path = Path(self._model_path)
        if not path.exists():
            raise WakeWordError(f"voicute model package not found: {path}")
        with open(path, "rb") as fh:
            header = fh.read(2)
        if header == b"PK":  # zip package — upstream sniffs the same way
            zf = zipfile.ZipFile(path)
            try:
                info = json.loads(zf.read("model_info.json"))
            except KeyError as exc:
                raise WakeWordError(
                    f"{path}: zip has no model_info.json") from exc
            model_file = info.get("model_file", "model.onnx")
            try:
                kw_bytes = zf.read(model_file)
            except KeyError as exc:
                raise WakeWordError(
                    f"{path}: zip has no {model_file}") from exc
            return info, kw_bytes, path.parent
        info = json.loads(path.read_text(encoding="utf-8"))
        return info, None, path.parent

    def _mel_source(self, base: Path) -> Any:
        """Path or bytes for melspectrogram.onnx (see class docstring)."""
        if self._mel_path is not None:
            if not self._mel_path.exists():
                raise WakeWordError(
                    f"voicute mel model not found: {self._mel_path}")
            return self._mel_path
        sibling = base / "melspectrogram.onnx"
        if sibling.exists():
            return sibling
        path = Path(self._model_path)
        with open(path, "rb") as fh:
            if fh.read(2) == b"PK":  # [UK] defensive zip-member fallback
                zf = zipfile.ZipFile(path)
                if "melspectrogram.onnx" in zf.namelist():
                    return zf.read("melspectrogram.onnx")
        raise WakeWordError(
            f"melspectrogram.onnx not found next to {path} "
            f"(it ships in voicute/onnx-wakeword under models/)")

    def _load(self) -> None:
        if self._loaded:
            return
        ok, reason = (self._probe if self._probe is not None
                      else self._probe_now())
        if not ok:
            raise WakeWordError(reason)
        import numpy as np
        import onnxruntime as ort
        self._np = np

        info, kw_bytes, base = self._read_bundle()
        model_type = info.get("model_type")
        if model_type == "multi_keyword":
            self._keywords = [str(k) for k in info["keywords"]]
            default_cons = 2  # upstream multi_keyword default
        elif info.get("wake_word") and info.get("model_file"):
            self._keywords = [str(info["wake_word"])]
            default_cons = 3  # upstream legacy default
        elif info.get("models") or info.get("multi_model"):
            raise WakeWordError(
                "legacy multi-MODEL voicute bundles are not supported; "
                "use a multi_keyword package (e.g. multi_jarvis_v9.3.zip)")
        else:
            raise WakeWordError(
                f"unrecognised voicute bundle format in {self._model_path}")
        cons = (self._cons_override if self._cons_override is not None
                else int(info.get("cons_frames", default_cons)))
        self._cons_frames = {kw: cons for kw in self._keywords}
        self._mel_time = int(info.get("mel_time", self._DEFAULT_MEL_TIME))
        self._samples_needed = self._mel_time * self._MEL_HOP + self._MEL_WIN

        mel_src = self._mel_source(base)
        mel_arg = (str(mel_src) if isinstance(mel_src, Path) else mel_src)
        self._mel_sess = ort.InferenceSession(
            mel_arg, providers=["CPUExecutionProvider"])
        if kw_bytes is None:
            kw_arg = str(base / info.get("model_file", "model.onnx"))
        else:
            kw_arg = kw_bytes
        self._kw_sess = ort.InferenceSession(
            kw_arg, providers=["CPUExecutionProvider"])
        self._mel_in = self._mel_sess.get_inputs()[0].name
        kw_input = self._kw_sess.get_inputs()[0]
        self._kw_in = kw_input.name
        # Resolve the model's real input width from its ONNX shape and
        # validate mel_time against it (upstream _resolve_input_cols):
        # feeding the wrong width fails at inference, not load — check now.
        shape = kw_input.shape
        mt = shape[-2] if len(shape) >= 2 else None
        if isinstance(mt, int) and mt > 0 and mt != self._mel_time:
            raise WakeWordError(
                f"mel_time mismatch: bundle says {self._mel_time} but the "
                f"model input shape is {shape}")
        last = shape[-1] if shape else None
        self._n_cols = (last if isinstance(last, int) and last > 0
                        else self._RAW_MELS)
        self._loaded = True

    # -- inference -------------------------------------------------------- #
    def _softmax_scores(self, raw: List[float]) -> List[float]:
        """Sigmoid outputs -> competitive probabilities (upstream math):
        logit(p) per keyword, background logit 0, softmax over all."""
        logits: List[float] = []
        for p in raw:
            p = max(1e-6, min(1 - 1e-6, float(p)))
            logits.append(math.log(p / (1.0 - p)))
        logits.append(0.0)  # background
        top = max(logits)
        exps = [math.exp(x - top) for x in logits]
        total = sum(exps)
        return [e / total for e in exps[:-1]]

    def _predict(self, window: Any) -> Tuple[str, float]:
        """One inference over a float32 window. Returns (best_keyword,
        competitive_prob). Mirrors upstream WakeWordEngine.predict()."""
        np = self._np
        mel_out = self._mel_sess.run(None, {self._mel_in: window})
        mel = mel_out[0]
        if len(mel.shape) != 4:  # verified upstream shape: [1, 1, T, 32]
            raise WakeWordError(
                f"unexpected mel output shape {mel.shape}; expected "
                f"[1, 1, frames, {self._RAW_MELS}]")
        frames = int(mel.shape[2])
        mel2d = mel[0, 0] / 10.0 + 2.0
        start = max(0, frames - self._mel_time)
        kw_in = np.zeros((1, self._mel_time, self._n_cols), dtype=np.float32)
        for f in range(self._mel_time):
            src = start + f
            if 0 <= src < frames:
                kw_in[0, f, :self._RAW_MELS] = mel2d[src]
        out = self._kw_sess.run(None, {self._kw_in: kw_in})
        data = [float(x) for x in out[0].flatten()]
        if len(data) < len(self._keywords):
            raise WakeWordError(
                f"keyword model returned {len(data)} scores for "
                f"{len(self._keywords)} keywords")
        probs = self._softmax_scores(data[:len(self._keywords)])
        best = max(range(len(probs)), key=lambda i: probs[i])
        return self._keywords[best], probs[best]

    def _l1(self, word: str, prob: float) -> Optional[Tuple[str, float]]:
        """Upstream L1: same word above threshold for cons_frames
        inferences, gaps of <= _MAX_GAP tolerated."""
        hi = prob > self.threshold and bool(word)
        if hi and word == self._cons_word:
            self._cons_count += 1
            self._cons_gap = 0
        elif hi:
            self._cons_word, self._cons_count, self._cons_gap = word, 1, 0
        elif self._cons_count > 0:
            self._cons_gap += 1
            if self._cons_gap > self._MAX_GAP:
                self._cons_word, self._cons_count, self._cons_gap = "", 0, 0
        if self._cons_word and self._cons_count >= self._cons_frames.get(
                self._cons_word, 2):
            fired = (self._cons_word, prob)
            self._cons_word, self._cons_count, self._cons_gap = "", 0, 0
            return fired
        return None

    def _feed(self, pcm: bytes) -> Optional[Tuple[str, float]]:
        if not pcm:
            return None
        self._load()
        np = self._np
        self._buf.extend(pcm)
        # Bound the buffer: only the newest window + one hop is ever read.
        keep = (self._samples_needed + _FRAME_SAMPLES) * 2
        if len(self._buf) > keep:
            del self._buf[:len(self._buf) - keep]
        self._since_infer += len(pcm) // 2
        candidate: Optional[Tuple[str, float]] = None
        while self._since_infer >= _FRAME_SAMPLES:
            self._since_infer -= _FRAME_SAMPLES
            window_bytes = bytes(self._buf[-self._samples_needed * 2:])
            audio = np.frombuffer(window_bytes, dtype=np.int16)
            audio = audio.astype(np.float32)
            if len(audio) < self._samples_needed:
                # Short stream start — upstream pads with zeros at the end.
                audio = np.pad(audio, (0, self._samples_needed - len(audio)))
            word, prob = self._predict(audio.reshape(1, -1))
            self.last_score = prob
            hit = self._l1(word, prob)
            if hit is not None and candidate is None:
                candidate = hit
        return candidate

    def reset(self) -> None:
        super().reset()
        self._buf.clear()
        self._since_infer = 0
        self._cons_word, self._cons_count, self._cons_gap = "", 0, 0


# --------------------------------------------------------------------------- #
# openWakeWord adapter — today's behaviour, behind the same protocol.
# --------------------------------------------------------------------------- #
class OpenWakeWordAdapter(WakeWordEngine):
    """Wraps jarvis.stt.OpenWakeWordListener unchanged.

    The wake word is "Jarvis" (owner's decision) but openWakeWord ships
    no pre-trained bare `jarvis` model: without model_path= the inner
    listener falls back to `hey_jarvis` and says so loudly on stderr
    (see stt.py). `listener_factory` is a test seam — when given, it
    replaces the stt listener and the import probe is skipped.
    """

    name = "openwakeword"

    def __init__(self, model_name: str = "jarvis",
                 model_path: Optional[Any] = None,
                 threshold: float = 0.5, cooldown_s: float = 1.5,
                 clock: Callable[[], float] = time.monotonic,
                 on_detect: Optional[Callable[[WakeDetection], None]] = None,
                 listener_factory: Optional[Callable[[], Any]] = None
                 ) -> None:
        super().__init__(threshold=threshold, cooldown_s=cooldown_s,
                         clock=clock, on_detect=on_detect)
        self.model_name = model_name
        self._model_path = model_path
        self._listener_factory = listener_factory
        self._listener: Any = None
        self._probe: Optional[Tuple[bool, str]] = None

    def _probe_now(self) -> Tuple[bool, str]:
        if self._listener_factory is not None:
            return True, ""
        try:
            import openwakeword  # noqa: F401
        except ImportError:
            return False, ("openwakeword is not installed. "
                           "Install it with: pip install openwakeword")
        return True, ""

    def available(self) -> bool:
        if self._probe is None:
            self._probe = self._probe_now()
        return self._probe[0]

    def unavailable_reason(self) -> str:
        if self._probe is None:
            self._probe = self._probe_now()
        return self._probe[1]

    def keywords(self) -> List[str]:
        name = self.model_name
        if self._listener is not None:
            name = getattr(self._listener, "model_name", name)
        elif self._model_path is None and name == "jarvis":
            name = "hey_jarvis"  # the interim model the listener will load
        return [name.replace("_", " ")]

    def _ensure_listener(self) -> Any:
        if self._listener is not None:
            return self._listener
        if self._listener_factory is not None:
            self._listener = self._listener_factory()
            return self._listener
        ok, reason = (self._probe if self._probe is not None
                      else self._probe_now())
        if not ok:
            raise WakeWordError(reason)
        from jarvis.stt import OpenWakeWordListener
        self._listener = OpenWakeWordListener(
            model_name=self.model_name, model_path=self._model_path,
            threshold=self.threshold, cooldown_s=self.cooldown_s,
            clock=self._clock)
        return self._listener

    def _feed(self, pcm: bytes) -> Optional[Tuple[str, float]]:
        from jarvis.stt import WakeError as SttWakeError
        listener = self._ensure_listener()
        try:
            fired = listener.listen(pcm)
        except SttWakeError as exc:
            raise WakeWordError(str(exc)) from exc
        self.last_score = float(getattr(listener, "last_score", 0.0))
        if fired:
            return self.keywords()[0], self.last_score
        return None

    def reset(self) -> None:
        super().reset()
        # The inner listener keeps its own cooldown state; a fresh one is
        # the only honest reset (it owns model + frame buffer).
        self._listener = None


# --------------------------------------------------------------------------- #
# Selection — config-driven preference: voicute -> openwakeword.
# --------------------------------------------------------------------------- #
def _cfg(config: Any, key: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, Mapping):
        return config.get(key, default)
    return getattr(config, key, default)


def _build(name: str, config: Any,
           on_detect: Optional[Callable[[WakeDetection], None]],
           clock: Callable[[], float],
           oww_listener_factory: Optional[Callable[[], Any]],
           ) -> Optional[WakeWordEngine]:
    threshold = float(_cfg(config, "threshold", 0.5))
    cooldown_s = float(_cfg(config, "cooldown_s", 1.5))
    if name == "voicute":
        return VoicuteAdapter(
            model_path=_cfg(config, "voicute_model"),
            mel_path=_cfg(config, "voicute_mel"),
            threshold=threshold, cooldown_s=cooldown_s,
            cons_frames=_cfg(config, "voicute_cons_frames"),
            clock=clock, on_detect=on_detect)
    if name == "openwakeword":
        return OpenWakeWordAdapter(
            model_name=str(_cfg(config, "oww_model_name", "jarvis")),
            model_path=_cfg(config, "oww_model_path"),
            threshold=threshold, cooldown_s=cooldown_s,
            clock=clock, on_detect=on_detect,
            listener_factory=oww_listener_factory)
    return None


def probe_engines(config: Any = None) -> List[EngineStatus]:
    """Availability of every engine, in preference order — for setup
    screens and diagnostics. Never raises."""
    pref = _cfg(config, "engine_preference", None) or DEFAULT_PREFERENCE
    out: List[EngineStatus] = []
    for name in pref:
        engine = _build(str(name), config, None, time.monotonic, None)
        if engine is None:
            out.append(EngineStatus(str(name), False,
                                    f"unknown wake engine '{name}'"))
        else:
            out.append(EngineStatus(engine.name, engine.available(),
                                    engine.unavailable_reason()))
    return out


def create_wake_engine(
        config: Any = None,
        on_detect: Optional[Callable[[WakeDetection], None]] = None,
        clock: Callable[[], float] = time.monotonic,
        oww_listener_factory: Optional[Callable[[], Any]] = None,
        ) -> WakeWordEngine:
    """First AVAILABLE engine in the preference order (default:
    voicute -> openwakeword). Raises WakeWordError listing every
    engine's reason when none can run — silence is not an option.

    Config keys (mapping or object attributes): engine_preference,
    threshold, cooldown_s, voicute_model, voicute_mel,
    voicute_cons_frames, oww_model_name, oww_model_path.
    """
    pref = _cfg(config, "engine_preference", None) or DEFAULT_PREFERENCE
    reasons: List[str] = []
    for name in pref:
        engine = _build(str(name), config, on_detect, clock,
                        oww_listener_factory)
        if engine is None:
            reasons.append(f"{name}: unknown wake engine")
            continue
        if engine.available():
            return engine
        reasons.append(f"{engine.name}: {engine.unavailable_reason()}")
    raise WakeWordError(
        "no wake-word engine available — " + "; ".join(reasons))


if __name__ == "__main__":  # pragma: no cover — manual diagnostics
    for status in probe_engines():
        mark = "OK " if status.available else "NO "
        print(f"{mark}{status.name}: {status.reason or 'available'}",
              file=sys.stderr)
