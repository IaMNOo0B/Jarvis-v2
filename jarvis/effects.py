"""Effect journal + undo-to-consistent-state (recovery pack).

Team 29 steal (PlanSys2, Apache-2.0 — pattern, not code): PlanSys2 compiles
a plan into a behavior tree, journals every applied effect as a FactChange
recording ``existed_before``, and — on divergence — walks the journal in
REVERSE, restoring the world to the last consistent state before it dares
replan. This module is v2's turn-scoped version of that journal.

How it works here:

* A tool's manifest may DECLARE its effects (``effects`` in skill.json —
  see jarvis/skills/registry.py). Undeclared tools journal NOTHING; no
  effect is ever invented for a tool that didn't declare it.
* ``gate.dispatch`` calls :func:`prepare_effects` BEFORE the tool runs, so
  ``existed_before`` is probed against the pre-state — never guessed from
  the post-state. After a successful run, :func:`finalize_effects` fills
  in the restore source and the records are emitted into the session
  store as ``effect.recorded`` events (via :func:`make_store_sink`).
* :func:`undo_turn` walks one turn's journal in reverse seq order and
  reverses what can honestly be reversed:

    - ``file``: restore the before-state snapshot (``before_value_ref``;
      by default the ``<target>.bak`` the code skill writes before every
      overwrite), or delete the file if it did not exist before.
    - ``fact``: ``memory.forget(target)`` — complete and self-verifying.
    - ``reminder``: an injected canceller callable (the reminders skill
      owns its own store; this module never reaches into it).
    - ``setting``: NO generic reverser exists — always reported as
      not-reversed so the owner restores it manually.

  Whatever cannot be reversed is named in the report with its reason.
  The report NEVER claims a blanket "undone".

Stdlib only. Python 3.11+.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable, Optional

from jarvis.skills.registry import EFFECT_KINDS

__all__ = [
    "resolve_target",
    "prepare_effects",
    "finalize_effects",
    "record_effects",
    "make_store_sink",
    "journal_for_turn",
    "undo_turn",
]

_PLACEHOLDER_RE = re.compile(r"\{args\.([A-Za-z0-9_]+)\}")


# --------------------------------------------------------------------------- #
# Target resolution
# --------------------------------------------------------------------------- #
def resolve_target(template: Any, args: Optional[dict]) -> Optional[str]:
    """Resolve ``{args.<key>}`` placeholders in a declared target.

    Returns the resolved string, or None if any placeholder cannot be
    resolved from ``args`` (an unresolved target is recorded as such —
    undo will honestly refuse it rather than guess a path).
    """
    if not isinstance(template, str):
        return None
    args = args or {}
    missing: list[str] = []

    def _sub(match: re.Match) -> str:
        key = match.group(1)
        if key not in args:
            missing.append(key)
            return match.group(0)
        return str(args[key])

    resolved = _PLACEHOLDER_RE.sub(_sub, template)
    return None if missing else resolved


# --------------------------------------------------------------------------- #
# Prepare (pre-execution) / finalize (post-execution)
# --------------------------------------------------------------------------- #
def _jailed_join(fs_root: Optional[str | Path], target: str) -> Optional[Path]:
    """Join target under fs_root; None if it would escape the root."""
    if fs_root is None:
        return None
    root = Path(fs_root).resolve()
    candidate = (root / target).resolve()
    if candidate != root and root not in candidate.parents:
        return None
    return candidate


def _probe_existed(kind: str, target: Optional[str], *,
                   fs_root: Optional[str | Path],
                   fact_exists: Optional[Callable[[str], bool]]) -> Optional[bool]:
    """Probe the PRE-state. None = could not determine (recorded honestly)."""
    if target is None:
        return None
    if kind == "file":
        path = _jailed_join(fs_root, target)
        if path is None:
            return None
        try:
            return path.exists()
        except OSError:
            return None
    if kind == "fact" and fact_exists is not None:
        try:
            return bool(fact_exists(target))
        except Exception:  # noqa: BLE001 - a broken probe is "unknown"
            return None
    return None


def prepare_effects(declared: Any, args: Optional[dict], *,
                    fs_root: Optional[str | Path] = None,
                    fact_exists: Optional[Callable[[str], bool]] = None
                    ) -> list[dict]:
    """Build pending journal records from a tool's declared effects.

    MUST be called before the tool executes: ``existed_before`` is the
    truth about the world before the call (a manifest-declared value
    wins; otherwise the live pre-state is probed). Malformed entries are
    skipped — manifest validation already rejects them at load time, so
    anything odd here came from a hand-built registry dict.
    """
    records: list[dict] = []
    for entry in declared or []:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        if kind not in EFFECT_KINDS:
            continue
        target = resolve_target(entry.get("target"), args)
        ref = resolve_target(entry.get("before_value_ref"), args)
        declared_existed = entry.get("existed_before")
        if isinstance(declared_existed, bool):
            existed: Optional[bool] = declared_existed
        else:
            existed = _probe_existed(kind, target, fs_root=fs_root,
                                     fact_exists=fact_exists)
        records.append({
            "kind": kind,
            "target": target if target is not None else entry.get("target"),
            "target_resolved": target is not None,
            "existed_before": existed,
            "before_value_ref": ref,
        })
    return records


def finalize_effects(prepared: list[dict], *,
                     fs_root: Optional[str | Path] = None) -> list[dict]:
    """Post-execution pass: fill the default restore source for files.

    The code skill's .bak discipline (skills/code) snapshots prior content
    to ``<path>.bak`` BEFORE overwriting. If a file effect has no declared
    ``before_value_ref`` and that snapshot exists, it becomes the ref —
    the exact bytes undo will restore.
    """
    out: list[dict] = []
    for rec in prepared or []:
        rec = dict(rec)
        if (rec.get("kind") == "file" and not rec.get("before_value_ref")
                and rec.get("existed_before") and rec.get("target_resolved")):
            candidate = _jailed_join(fs_root, str(rec["target"]) + ".bak")
            if candidate is not None and candidate.is_file():
                rec["before_value_ref"] = str(rec["target"]) + ".bak"
        out.append(rec)
    return out


# --------------------------------------------------------------------------- #
# Recording into the session store
# --------------------------------------------------------------------------- #
def record_effects(store: Any, session_id: Optional[str], turn_id: Any,
                   tool_name: str, records: list[dict]) -> list[str]:
    """Emit one ``effect.recorded`` event per record. Returns event ids.

    No store / no session / no records -> no-op. Recording is evidence,
    never a dependency: callers wrap this so a store failure can never
    break the dispatch it describes.
    """
    if store is None or not session_id or not records:
        return []
    ids = []
    for rec in records:
        payload = {
            "turn_id": turn_id,
            "tool": tool_name,
            "kind": rec.get("kind"),
            "target": rec.get("target"),
            "target_resolved": bool(rec.get("target_resolved")),
            "existed_before": rec.get("existed_before"),
            "before_value_ref": rec.get("before_value_ref"),
        }
        ids.append(store.emit(session_id, "effect.recorded", payload,
                              actor="system", trust="system"))
    return ids


def make_store_sink(store: Any) -> Callable[[dict], None]:
    """Adapt a SessionStore to the gate's ``effect_sink`` protocol.

    The gate calls the sink once per successful dispatch with
    {"session_id", "turn_id", "tool", "records"}; the sink writes the
    journal events. Wire it in chat/app construction:
    ``Gate(..., effect_sink=effects.make_store_sink(store))``.
    """
    def _sink(message: dict) -> None:
        record_effects(store, message.get("session_id"),
                       message.get("turn_id"), message.get("tool", ""),
                       message.get("records") or [])
    return _sink


def journal_for_turn(store: Any, session_id: str, turn_id: Any) -> list[dict]:
    """One turn's journal: effect.recorded payloads, seq order."""
    if store is None:
        return []
    events = store.get_events(session_id, limit=100000)
    return [ev.get("payload") or {} for ev in events
            if ev.get("type") == "effect.recorded"
            and (ev.get("payload") or {}).get("turn_id") == turn_id]


# --------------------------------------------------------------------------- #
# Undo — walk the journal in reverse, reverse what can honestly be reversed
# --------------------------------------------------------------------------- #
def _restore_file(rec: dict, fs_root: Optional[str | Path]) -> tuple[bool, str]:
    target = rec.get("target")
    if not rec.get("target_resolved") or not isinstance(target, str):
        return False, "target was never resolved to a concrete path"
    path = _jailed_join(fs_root, target)
    if path is None:
        return False, "target escapes the data root (or no fs_root given)"
    existed = rec.get("existed_before")
    if existed is None:
        return False, "pre-state unknown: existed_before was not recorded"
    if existed is False:
        # The turn created it; undo removes it.
        try:
            if path.exists():
                path.unlink()
                return True, "deleted (did not exist before the turn)"
            return True, "already absent (nothing to delete)"
        except OSError as exc:
            return False, f"delete failed: {exc}"
    # existed is True: restore the before-state snapshot.
    ref = rec.get("before_value_ref")
    if not ref:
        return False, "no before-state snapshot recorded for this file"
    ref_path = _jailed_join(fs_root, str(ref))
    if ref_path is None or not ref_path.is_file():
        return False, f"before-state snapshot missing: {ref}"
    try:
        data = ref_path.read_bytes()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".undo-tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError as exc:
        return False, f"restore failed: {exc}"
    return True, f"restored from snapshot {ref}"


def _reverse_one(rec: dict, *, memory: Any, fs_root: Optional[str | Path],
                 reminder_cancel: Optional[Callable[[str], Any]]
                 ) -> tuple[bool, str]:
    kind = rec.get("kind")
    target = rec.get("target")
    if kind == "file":
        return _restore_file(rec, fs_root)
    if kind == "fact":
        if memory is None:
            return False, "no memory handle provided"
        try:
            memory.forget(str(target))
        except Exception as exc:  # noqa: BLE001 - report, never crash undo
            return False, f"memory.forget failed: {exc}"
        return True, "fact forgotten (memory.forget verifies the delete)"
    if kind == "reminder":
        if reminder_cancel is None:
            return False, "no reminder canceller provided"
        try:
            outcome = reminder_cancel(str(target))
        except Exception as exc:  # noqa: BLE001
            return False, f"reminder canceller raised: {exc}"
        if isinstance(outcome, dict):
            if outcome.get("cancelled"):
                return True, "reminder cancelled"
            return False, "canceller reported no such reminder"
        if outcome:
            return True, "reminder cancelled"
        return False, "canceller reported no such reminder"
    if kind == "setting":
        return False, ("settings have no automatic reverser; "
                       "the owner must restore this manually")
    return False, f"unknown effect kind {kind!r}"


def undo_turn(store: Any, session_id: str, turn_id: Any, *,
              memory: Any = None,
              fs_root: Optional[str | Path] = None,
              reminder_cancel: Optional[Callable[[str], Any]] = None) -> dict:
    """Reverse one turn's journaled effects, newest first (PlanSys2 order).

    Returns {"turn_id", "ok", "total", "reversed": [...], "not_reversed":
    [...]}. ``ok`` is True ONLY when every journaled effect was reversed;
    each entry names its action (reversed) or its reason (not_reversed).
    """
    report: dict[str, Any] = {
        "turn_id": turn_id, "ok": False, "total": 0,
        "reversed": [], "not_reversed": [],
    }
    if store is None:
        report["error"] = "no session store provided"
        return report
    journal = journal_for_turn(store, session_id, turn_id)
    report["total"] = len(journal)
    for rec in reversed(journal):
        ok, note = _reverse_one(rec, memory=memory, fs_root=fs_root,
                                reminder_cancel=reminder_cancel)
        entry = {
            "kind": rec.get("kind"), "target": rec.get("target"),
            "tool": rec.get("tool"),
        }
        if ok:
            entry["action"] = note
            report["reversed"].append(entry)
        else:
            entry["reason"] = note
            report["not_reversed"].append(entry)
    report["ok"] = not report["not_reversed"]
    try:  # the undo itself joins the audit trail (best-effort)
        store.emit(session_id, "effect.undo_report", {
            "turn_id": turn_id, "ok": report["ok"], "total": report["total"],
            "reversed": len(report["reversed"]),
            "not_reversed": [e["target"] for e in report["not_reversed"]],
        }, actor="system", trust="system")
    except Exception:  # noqa: BLE001 - the report stands even if logging fails
        pass
    return report
