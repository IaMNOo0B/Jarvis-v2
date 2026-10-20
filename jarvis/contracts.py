"""Skill contracts: typed postconditions + the recovery ladder.

Two steals, one module:

* **Typed postconditions** (Team 22 — mc_aiplayer/Voyager): *"The LLM
  chooses intent. Goals define completion. Deterministic tasks execute."*
  A tool returning is NOT success. A manifest may declare
  ``postconditions`` (see jarvis/skills/registry.py); after dispatch,
  :func:`evaluate_postconditions` checks them against REAL state — the
  file is on disk, the fact is in memory — never against the tool's own
  success claim. A failed postcondition is a typed failure:
  :func:`mark_result` stamps the tool.result payload with
  ``postcondition_failed`` and the CompletionAudit reads that as NOT
  delivered, even when ``ok`` is true.

* **The recovery ladder** (Team 29 — PlanSys2/SkiROS2/py_trees): failure
  handling is a DECLARED policy, not improvisation. :func:`recover`
  returns exactly one next action:

      retry(1) -> substitute (a CapNet alternative for the same job)
               -> escalate to the owner with a REFLECT-style one-line
                  causal summary built from the turn's events.

  The ladder STOPS at escalation. Replan-suffix (repairing the un-executed
  remainder of a multi-step plan) is a declared gap — it needs the brain's
  plan representation, which does not exist yet — so the ladder escalates
  instead of pretending.

Stdlib only. Python 3.11+.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from jarvis.effects import _jailed_join, resolve_target
from jarvis.skills.registry import POSTCONDITION_CHECKS

__all__ = [
    "RETRYABLE_KINDS",
    "evaluate_postconditions",
    "mark_result",
    "make_evaluator",
    "causal_summary",
    "recover",
]

# Failure kinds where one retry is the declared policy. Anything else
# (denials, schema errors, unknown tools) skips straight past rung 1:
# retrying a refusal is how agents learn to nag.
RETRYABLE_KINDS = frozenset(
    {"tool_error", "postcondition_failed", "timeout", "executor_error"}
)


# --------------------------------------------------------------------------- #
# Postconditions — checked against real state, never the tool's word
# --------------------------------------------------------------------------- #
def _check_one(entry: dict, args: Optional[dict], *, result_ok: bool,
               fs_root: Optional[str | Path], memory: Any) -> dict:
    check = entry.get("check")
    target = resolve_target(entry.get("target"), args)
    out = {"check": check, "target": target if target is not None
           else entry.get("target"), "passed": False, "reason": ""}
    if check not in POSTCONDITION_CHECKS:
        out["reason"] = f"unknown postcondition check {check!r}"
        return out
    if check == "tool_ok":
        out["passed"] = bool(result_ok)
        out["reason"] = ("the tool reported success" if result_ok
                         else "the tool itself reported failure")
        return out
    if target is None:
        out["reason"] = "target could not be resolved from the call args"
        return out
    if check == "file_exists":
        path = _jailed_join(fs_root, target)
        if path is None:
            out["reason"] = "no fs_root to check against (or target escapes it)"
            return out
        out["passed"] = path.exists()
        out["reason"] = ("file exists" if out["passed"]
                         else f"file not found after dispatch: {target}")
        return out
    # fact_exists / fact_absent
    if memory is None:
        out["reason"] = "no memory handle to check against"
        return out
    try:
        present = memory.get_fact(target) is not None
    except Exception as exc:  # noqa: BLE001 - an uncheckable fact is a failure
        out["reason"] = f"memory lookup failed: {exc}"
        return out
    if check == "fact_exists":
        out["passed"] = present
        out["reason"] = "fact present" if present else \
            f"fact absent after dispatch: {target}"
    else:  # fact_absent
        out["passed"] = not present
        out["reason"] = "fact absent" if not present else \
            f"fact still present after dispatch: {target}"
    return out


def evaluate_postconditions(declared: Any, args: Optional[dict], *,
                            result_ok: bool,
                            fs_root: Optional[str | Path] = None,
                            memory: Any = None) -> dict:
    """Evaluate a tool's declared postconditions against real state.

    Returns {"passed": bool, "declared": int, "checks": [...],
    "failures": [...]}. No declarations -> passed (vacuous): contracts
    are opt-in per tool, and an undeclared tool is not failed for lacking
    a contract — it is simply unverified, which the report says.
    """
    checks = [
        _check_one(entry, args, result_ok=result_ok, fs_root=fs_root,
                   memory=memory)
        for entry in (declared or []) if isinstance(entry, dict)
    ]
    failures = [c for c in checks if not c["passed"]]
    return {
        "passed": not failures,
        "declared": len(checks),
        "checks": checks,
        "failures": failures,
    }


def mark_result(payload: dict, report: Optional[dict]) -> dict:
    """Stamp a tool.result payload from a postcondition report.

    Returns a COPY (the caller's dict is never mutated). On failure the
    copy carries ``postcondition_failed: True`` + the typed failures, so
    the CompletionAudit sees NOT delivered even if ``ok`` is true.
    """
    out = dict(payload or {})
    if report and not report.get("passed", True):
        out["postcondition_failed"] = True
        out["postcondition_failures"] = [
            f"{c.get('check')}:{c.get('target')}" for c in report["failures"]
        ]
    return out


def make_evaluator(*, fs_root: Optional[str | Path] = None,
                   memory: Any = None):
    """Build the gate's ``postcondition_evaluator`` hook.

    Signature matches jarvis/gate.py: (tool_name, args, declared,
    raw_output) -> report | None (None when the tool declared no
    postconditions). ``result_ok`` is derived from the raw output: a
    dict result with an ``ok`` key speaks for itself; anything else that
    came back at all counts as self-reported success — and then the
    state checks still get their say.
    """
    def _evaluator(tool_name: str, args: dict, declared: Any,
                   raw_output: Any) -> Optional[dict]:
        if not declared:
            return None
        if isinstance(raw_output, dict) and "ok" in raw_output:
            result_ok = bool(raw_output.get("ok"))
        else:
            result_ok = raw_output is not None
        return evaluate_postconditions(declared, args, result_ok=result_ok,
                                       fs_root=fs_root, memory=memory)
    return _evaluator


# --------------------------------------------------------------------------- #
# The recovery ladder — declared policy, stops at escalation
# --------------------------------------------------------------------------- #
def causal_summary(events: Optional[list], failure: dict) -> str:
    """REFLECT-style one-line causal summary from the turn's events.

    REFLECT (Team 29) turns a hierarchical execution log into a causal
    failure explanation; here the session events are that log. One line,
    facts only: what failed, how, what else the turn shows.
    """
    tool = failure.get("tool", "unknown tool")
    kind = failure.get("kind", "failure")
    detail = str(failure.get("detail") or "").strip()
    events = events or []
    tool_failures = sum(
        1 for ev in events if ev.get("type") == "tool.result"
        and not (ev.get("payload") or {}).get("ok"))
    pc_failures = sum(
        1 for ev in events if ev.get("type") == "tool.result"
        and (ev.get("payload") or {}).get("postcondition_failed"))
    effects = sum(1 for ev in events if ev.get("type") == "effect.recorded")
    head = f"{tool} failed ({kind})"
    if detail:
        head += f": {detail}"
    tail = (f"{tool_failures} tool failure(s) this turn"
            f" ({pc_failures} postcondition), {effects} effect(s) journaled; "
            "retry and substitution are exhausted — owner decision needed")
    return f"{head} — {tail}."


def _find_substitute(network: Any, tool_name: str) -> Optional[Any]:
    """First USABLE CapNet alternative for the tool, or None.

    Duck-typed against jarvis.capnet.CapabilityNetwork; any surprise
    (no node, broken network) means "no substitute", never a crash —
    the ladder must always reach a rung.
    """
    if network is None:
        return None
    try:
        node = network.find(tool_name)
        if node is None:
            return None
        for alt in network.alternatives_of(node.id):
            if getattr(alt, "health", None) == "available":
                return alt
    except Exception:  # noqa: BLE001 - ladder robustness beats cleverness
        return None
    return None


def recover(failure: dict, ctx: Optional[dict] = None) -> dict:
    """The declared recovery policy. Returns ONE next action.

    ``failure``: {"tool", "kind", "detail"}. ``ctx`` (all optional):
    {"history": [actions already taken], "network": CapabilityNetwork,
     "events": [turn events for the causal summary]}.

    Rungs: retry(1) -> substitute -> escalate. Once escalation is in the
    history the ladder is DONE — recover() returns escalate again, never
    a fresh retry. It cannot loop: each rung fires at most once, and the
    top rung is terminal by construction.
    """
    ctx = ctx or {}
    history = list(ctx.get("history") or [])
    tool = failure.get("tool", "")
    kind = failure.get("kind", "")
    if "escalate" in history:
        return {"action": "escalate", "rung": 3, "tool": tool,
                "summary": causal_summary(ctx.get("events"), failure),
                "reason": "already escalated; the ladder stops at the owner"}
    if kind in RETRYABLE_KINDS and "retry" not in history:
        return {"action": "retry", "rung": 1, "tool": tool,
                "reason": f"first {kind} failure of {tool!r}; the declared "
                          "policy allows exactly one retry"}
    if "substitute" not in history:
        alt = _find_substitute(ctx.get("network"), tool)
        if alt is not None:
            return {"action": "substitute", "rung": 2, "tool": tool,
                    "substitute": getattr(alt, "name", None),
                    "substitute_node": getattr(alt, "id", None),
                    "reason": f"{tool!r} failed; {alt.name!r} serves the "
                              "same purpose group and is available"}
    return {"action": "escalate", "rung": 3, "tool": tool,
            "summary": causal_summary(ctx.get("events"), failure),
            "reason": "retry/substitute rungs exhausted or unavailable; "
                      "replan-suffix is a declared gap (no plan "
                      "representation yet), so the owner decides"}
