"""Observability — OTel data model, not the infrastructure (learn-observability).

trace_id propagated via contextvars; spans are JSONL lines appended to a
sink the caller owns. ~6 instrumented boundaries is the design target:
turn, model call, tool call, memory recall, consolidation, chain attempt.

A span is a plain dict: {trace_id, span_id, parent_id, name, ts, dur_ms,
attrs}. The exporter never raises into the caller's path — observability
must not be able to break the thing it observes.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import time
import traceback
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "jarvis_trace_id", default="")
_span_stack: contextvars.ContextVar[tuple] = contextvars.ContextVar(
    "jarvis_span_stack", default=())

# ---------------------------------------------------------------------------
# Log rotation policy (Team 19 E2): per-log-file 10 MB x 5 backups,
# lumberjack's four knobs at desktop scale, enforced in-process at write
# time. Every append sink in v2 rotates through rotate_numbered (or, for
# the date-partitioned session archive, the same size/count budget) so no
# log file can grow without bound.
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5


def rotate_numbered(path: str | Path, max_bytes: int = LOG_MAX_BYTES,
                    backup_count: int = LOG_BACKUP_COUNT) -> bool:
    """Roll ``path`` to ``path.1`` (shifting older backups up, the oldest
    beyond ``backup_count`` is discarded) once it reaches ``max_bytes`` —
    stdlib RotatingFileHandler semantics as a free function, so non-logging
    writers (JSONL sinks) share the exact same policy.

    Returns True when a roll happened. NEVER raises: a failed roll must
    not break the writer it protects (observability discipline)."""
    try:
        p = Path(path)
        if max_bytes < 1 or backup_count < 1 or not p.is_file():
            return False
        if p.stat().st_size < max_bytes:
            return False
        for i in range(backup_count - 1, 0, -1):
            src = p.with_name(f"{p.name}.{i}")
            if src.exists():
                os.replace(src, p.with_name(f"{p.name}.{i + 1}"))
        os.replace(p, p.with_name(f"{p.name}.1"))
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Exception fingerprinting (Team 19 E3): Sentry's grouping minus Sentry.
# A fingerprint = hash of the exception type + the top-3 in-app frames
# (module + function only — no line numbers, no addresses, no values), so
# the same bug raised twice groups to the same fingerprint and a health
# surface can count recurrences instead of showing traceback soup.
_PKG_DIR = Path(__file__).resolve().parent


def _in_app_module(filename: str) -> Optional[str]:
    """Dotted module name if ``filename`` lives under the jarvis package,
    else None (stdlib/site-packages/test frames are not the app's bug)."""
    try:
        rel = Path(filename).resolve().relative_to(_PKG_DIR)
    except (ValueError, OSError):
        return None
    parts = list(rel.parts)
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(["jarvis", *parts]) if parts else "jarvis"


def fingerprint(exc: BaseException) -> str:
    """Stable grouping hash for ``exc``: sha256 of the exception type name
    plus the last three in-app frames (``module:function``). Deterministic
    across processes and restarts; an exception that was never raised
    (no traceback) groups by type alone."""
    frames: List[str] = []
    tb = getattr(exc, "__traceback__", None)
    if tb is not None:
        for frame in traceback.extract_tb(tb):
            module = _in_app_module(frame.filename)
            if module is not None:
                frames.append(f"{module}:{frame.name}")
    raw = "|".join([type(exc).__name__, *frames[-3:]])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def current_trace_id() -> str:
    return _trace_id.get()


def new_trace_id() -> str:
    tid = uuid.uuid4().hex[:16]
    _trace_id.set(tid)
    return tid


class SpanRecorder:
    """Collects spans in memory; optionally appends each as JSONL to a file.

    Error grouping (Team 19 E3): a span whose attrs carry ``error_exc``
    (an exception object) or ``error_fingerprint`` gets the fingerprint
    recorded plus ``error_count`` — how many times THIS recorder has seen
    that fingerprint, in memory and in the JSONL sink alike. The exception
    object itself is never serialised; it is replaced by its ``error``
    string before the span is stored."""

    def __init__(self, sink_path: Optional[str | Path] = None) -> None:
        self.spans: List[Dict[str, Any]] = []
        self.sink_path = Path(sink_path) if sink_path else None
        self._error_counts: Dict[str, int] = {}
        self._error_first: Dict[str, str] = {}

    def record(self, span: Dict[str, Any]) -> None:
        attrs = span.get("attrs")
        if isinstance(attrs, dict):
            exc = attrs.pop("error_exc", None)
            if exc is not None:
                attrs.setdefault("error", f"{type(exc).__name__}: {exc}")
                attrs.setdefault("error_fingerprint", fingerprint(exc))
            fp = attrs.get("error_fingerprint")
            if isinstance(fp, str) and fp:
                count = self._error_counts.get(fp, 0) + 1
                self._error_counts[fp] = count
                self._error_first.setdefault(fp, str(attrs.get("error", "")))
                attrs["error_count"] = count
        self.spans.append(span)
        if self.sink_path is not None:
            try:
                rotate_numbered(self.sink_path, max_bytes=LOG_MAX_BYTES,
                                backup_count=LOG_BACKUP_COUNT)
                with self.sink_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(span, ensure_ascii=False) + "\n")
            except OSError:
                pass  # Observability never breaks the observed system.

    def error_summary(self) -> Dict[str, Dict[str, Any]]:
        """fingerprint -> {count, error} for every grouped exception seen.
        The health report's 'top recurring errors' raw material."""
        return {fp: {"count": n, "error": self._error_first.get(fp, "")}
                for fp, n in self._error_counts.items()}

    def by_name(self, name: str) -> List[Dict[str, Any]]:
        return [s for s in self.spans if s["name"] == name]

    def summary(self) -> Dict[str, Dict[str, Any]]:
        """name -> {count, avg_ms, max_ms} — the reliability SLO raw material."""
        out: Dict[str, Dict[str, Any]] = {}
        for s in self.spans:
            row = out.setdefault(s["name"], {"count": 0, "total_ms": 0.0,
                                             "max_ms": 0.0})
            row["count"] += 1
            row["total_ms"] += s["dur_ms"]
            row["max_ms"] = max(row["max_ms"], s["dur_ms"])
        for row in out.values():
            row["avg_ms"] = row["total_ms"] / row["count"] if row["count"] else 0.0
        return out


# Default recorder: in-memory only until the app points it at a file.
default_recorder = SpanRecorder()


@contextmanager
def span(name: str, recorder: Optional[SpanRecorder] = None,
         clock: Callable[[], float] = time.time,
         **attrs: Any) -> Iterator[Dict[str, Any]]:
    """Record one span. Sets trace_id if absent; nests via the span stack."""
    rec = recorder if recorder is not None else default_recorder
    if not _trace_id.get():
        new_trace_id()
    stack = _span_stack.get()
    record: Dict[str, Any] = {
        "trace_id": _trace_id.get(),
        "span_id": uuid.uuid4().hex[:12],
        "parent_id": stack[-1] if stack else "",
        "name": name,
        "ts": clock(),
        "attrs": dict(attrs),
    }
    token = _span_stack.set(stack + (record["span_id"],))
    started = clock()
    try:
        yield record
    except Exception as exc:  # mark, then let it propagate untouched
        record["attrs"]["error"] = f"{type(exc).__name__}: {exc}"
        record["attrs"]["error_fingerprint"] = fingerprint(exc)
        raise
    finally:
        record["dur_ms"] = round((clock() - started) * 1000.0, 3)
        _span_stack.reset(token)
        rec.record(record)
