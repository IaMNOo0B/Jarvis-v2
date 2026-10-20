"""Completion audit: post-execution delivery truth for a brain turn.

Stolen from orcbot's CompletionAudit (our own code, MIT-licensed source):
pre-execution verification (verifier.py) proves the plan was sound; this
module proves the WORK was actually delivered. A turn is "delivered" iff
the last deep-work outcome in the turn was a success AND a reply went out.
Deep work must succeed AFTER the last failure — a failure followed by a
reply is not a delivery.

Deterministic. Reads session-store events. No model involved. An audit
failure never breaks a turn — Brain.respond catches and marks it.

Event vocabulary (from the real session store):
  user.message        — turn boundary (last one scopes the audit)
  brain.reply         — a reply was delivered
  tool.result         — deep work; payload {"ok": bool, ...}. A payload
                        carrying "postcondition_failed": true (stamped by
                        jarvis/contracts.py when a tool's declared
                        postconditions fail against real state) counts as
                        a FAILURE even when "ok" is true: a tool's own
                        success claim is never success by itself
                        (Team 22 law — completion is verified, not assumed).
  approval.requested  — paused for approval; nothing executed
  brain.decision      — payload {"decision": "ask"|"ask_gate"|"stop", ...}

Stdlib only. Python 3.11+.
"""

from __future__ import annotations

from typing import Any, Dict, List


# --------------------------------------------------------------------------- #
# The audit
# --------------------------------------------------------------------------- #
class CompletionAudit:
    """Deterministic post-execution audit over session-store events."""

    def __init__(self, session_store: Any) -> None:
        self._store = session_store

    # -- scope ----------------------------------------------------------- #

    def _turn_events(self, session_id: str) -> List[Dict[str, Any]]:
        """Events from the most recent user.message onward (seq-ordered)."""
        events = self._store.get_events(session_id, limit=1000)
        start = None
        for ev in events:
            if ev.get("type") == "user.message":
                start = ev.get("seq", 0)
        if start is None:
            return list(events)
        return [ev for ev in events if ev.get("seq", 0) >= start]

    # -- verdict ---------------------------------------------------------- #

    def audit_turn(self, session_id: str) -> Dict[str, Any]:
        """Audit the most recent turn. Deterministic, no model.

        Returns {"delivered": bool, "reason": str, ...diagnostics}.
        """
        try:
            events = self._turn_events(session_id)
        except Exception as exc:  # audit is evidence, never a dependency
            return {"delivered": False,
                    "reason": f"audit could not read events: {exc}"}

        payload_of = lambda ev: (ev.get("payload") or {})  # noqa: E731

        def _pc_failed(ev: Dict[str, Any]) -> bool:
            return bool(payload_of(ev).get("postcondition_failed"))

        tool_oks = [ev.get("seq", 0) for ev in events
                    if ev.get("type") == "tool.result"
                    and bool(payload_of(ev).get("ok"))
                    and not _pc_failed(ev)]
        tool_fails = [ev.get("seq", 0) for ev in events
                      if ev.get("type") == "tool.result"
                      and (not bool(payload_of(ev).get("ok"))
                           or _pc_failed(ev))]
        pc_failures = sum(1 for ev in events
                          if ev.get("type") == "tool.result"
                          and _pc_failed(ev))
        replied = any(ev.get("type") == "brain.reply" for ev in events)
        approval = any(ev.get("type") == "approval.requested"
                       for ev in events)
        asked = any(ev.get("type") == "brain.decision"
                    and payload_of(ev).get("decision") in ("ask", "ask_gate")
                    for ev in events)
        stopped = any(ev.get("type") == "brain.decision"
                      and payload_of(ev).get("decision") == "stop"
                      for ev in events)

        out = {"delivered": False, "reason": "",
               "tool_successes": len(tool_oks),
               "tool_failures": len(tool_fails), "replied": replied,
               "postcondition_failures": pc_failures}

        # orcbot rule: a reply after a final failure is not a delivery.
        if replied and tool_fails and (not tool_oks
                                      or max(tool_fails) > max(tool_oks)):
            latest_fail_pc = any(
                ev.get("seq", 0) == max(tool_fails) and _pc_failed(ev)
                for ev in events if ev.get("type") == "tool.result")
            if latest_fail_pc:
                out["reason"] = (
                    "the final deep-work outcome failed its declared "
                    f"postconditions (failure seq {max(tool_fails)}); the "
                    "tool's own success claim is not a delivery")
            else:
                out["reason"] = (
                    "the final deep-work outcome was a failure after the last "
                    f"success (failure seq {max(tool_fails)}); the reply is "
                    "not a delivery")
            return out
        if approval:
            out["reason"] = "approval was requested; nothing executed"
            return out
        if asked:
            out["reason"] = "a clarifying question was asked; nothing delivered"
            return out
        if stopped:
            out["reason"] = "the turn stopped honestly before delivery"
            return out
        if not replied:
            out["reason"] = "the turn ended without a delivered reply"
            return out
        out["delivered"] = True
        if tool_oks:
            out["reason"] = (
                "reply delivered; last deep-work outcome was a success")
        else:
            out["reason"] = "reply delivered; no deep work was needed"
        return out


def audit_turn(session_store: Any, session_id: str) -> Dict[str, Any]:
    """One-shot convenience: audit the most recent turn of a session."""
    return CompletionAudit(session_store).audit_turn(session_id)
