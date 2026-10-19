"""The Gate — the R2 enforcement point (JARVIS-RULES.txt P0-1, P1-1, P1-2).

Deterministic. No model calls. No randomness in decisions.

Pipeline position (the AND-gate from the fault-tree study):

    brain proposes -> GATE.check() -> [tier-3: approval] -> execute
                                          -> GATE.wrap_output() -> brain

Every tool call passes through Gate.dispatch(). There is no other path.
The gate governs *doing*; the DCL governs *telling* (check_egress).
Neither waives the other: both must pass.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

try:
    from jarvis import dcl as _dcl
except Exception:  # dcl.py not built yet, or broken -> fail closed
    _dcl = None


class Verdict(Enum):
    ALLOW = "allow"
    ALLOW_WITH_UNDO = "allow_with_undo"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@dataclass(frozen=True)
class GateDecision:
    verdict: Verdict
    reason: str
    approval_request: Optional[dict] = None


_SCHEMA_TYPES = {
    "str": str, "int": int, "float": float,
    "bool": bool, "list": list, "dict": dict,
    # JSON Schema aliases (real manifests use these):
    "string": str, "integer": int, "number": float,
    "boolean": bool, "array": list, "object": dict,
}


def _type_ok(want: str, val: Any) -> bool:
    """Strict type check. bool never satisfies a non-bool type (and vice versa)."""
    if want in ("bool", "boolean"):
        return isinstance(val, bool)
    if isinstance(val, bool):
        return False
    py = _SCHEMA_TYPES.get(want)
    if py is None:
        return False
    if want in ("float", "number"):
        return isinstance(val, (int, float))
    return isinstance(val, py)


def _validate_args(schema: Optional[dict], args: Any) -> tuple[bool, str]:
    """Validate args against a simple schema. Fail-closed: any doubt -> invalid."""
    if not isinstance(args, dict):
        return False, "args must be an object"
    schema = schema or {}
    for key in schema.get("required", []):
        if key not in args:
            return False, f"missing required arg: {key}"
    props = schema.get("properties", {})
    for key, val in args.items():
        if key not in props:
            return False, f"unknown arg: {key}"
        want = props[key].get("type")
        if want is not None and not _type_ok(want, val):
            return False, f"arg {key!r} must be {want}"
    return True, "ok"


def _canonical(tool_name: str, args: dict) -> str:
    return tool_name + "\x00" + json.dumps(
        args, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def action_hash(tool_name: str, args: dict) -> str:
    """The action's fingerprint. Approval tokens bind to this exact action."""
    return hashlib.sha256(_canonical(tool_name, args).encode("utf-8")).hexdigest()


class Gate:
    """The single enforcement point between the brain and side effects."""

    def __init__(self, rules: Optional[dict] = None,
                 skill_registry: Optional[dict] = None):
        self.rules = rules or {}
        self.registry = skill_registry or {}
        # Per-process HMAC key: tokens are unforgeable and die with the process.
        self._hmac_key = os.urandom(32)
        # P1-13: "what left the machine" feed (PERSONAL egress entries).
        self.feed_log: list[dict] = []

    # ------------------------------------------------------------------ check
    def check(self, tool_name: str, args: dict,
              turn_allowances: list[str]) -> GateDecision:
        """THE gate. First statement of dispatch. Order is load-bearing:

        1. declared?  2. schema-valid?  3. capabilities?  4. tier route.
        """
        tool = self.registry.get(tool_name)
        if tool is None:
            return GateDecision(Verdict.DENY, f"undeclared tool: {tool_name}")
        ok, why = _validate_args(tool.get("schema"), args)
        if not ok:
            return GateDecision(Verdict.DENY, f"schema validation failed: {why}")
        missing = set(tool.get("capabilities", [])) - set(turn_allowances or [])
        if missing:
            return GateDecision(
                Verdict.DENY, f"missing capabilities: {sorted(missing)}")
        tier = tool.get("tier", 1)
        if tier == 3:
            # P0-1: NEVER auto-allow. The approval binds this exact action.
            ah = action_hash(tool_name, args)
            return GateDecision(
                Verdict.REQUIRE_APPROVAL,
                f"tier-3 tool {tool_name!r} requires out-of-band approval (P0-1)",
                approval_request={
                    "tool": tool_name, "tier": 3, "action_hash": ah,
                    "token": self.approval_token(ah),
                    "message": f"Approve {tool_name}?",
                },
            )
        if tier == 2:
            return GateDecision(
                Verdict.ALLOW_WITH_UNDO,
                f"tier-2 tool {tool_name!r}: allowed with undo",
                approval_request={"tool": tool_name, "tier": 2,
                                  "undo_token": secrets.token_urlsafe(16)},
            )
        if tier == 1:
            return GateDecision(Verdict.ALLOW, f"tier-1 tool {tool_name!r}: allowed")
        return GateDecision(Verdict.DENY, f"unknown tier {tier!r} for {tool_name}")

    # ------------------------------------------------------- approval tokens
    def approval_token(self, action_hash: str) -> str:
        """Mint a signed token embedding the action hash. Kills replay/TOCTOU:
        an approval for action A cannot authorize action B."""
        payload = json.dumps({"h": action_hash, "t": int(time.time())},
                             separators=(",", ":")).encode()
        sig = hmac.new(self._hmac_key, payload, hashlib.sha256).hexdigest()
        return base64.urlsafe_b64encode(payload).decode() + "." + sig

    def verify_token(self, token: str, tool_name: str, args: dict) -> bool:
        """True only if the token was minted by THIS gate for THIS exact action."""
        try:
            payload_b64, sig = token.rsplit(".", 1)
            payload = base64.urlsafe_b64decode(payload_b64.encode())
            expected = hmac.new(self._hmac_key, payload, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, sig):
                return False
            data = json.loads(payload.decode())
            return hmac.compare_digest(
                str(data.get("h", "")), action_hash(tool_name, args))
        except Exception:
            return False

    # ------------------------------------------------------------ dispatch
    def _is_network_bound(self, tool: dict) -> bool:
        if tool.get("network_egress"):
            return True
        return any(str(c).startswith("net.") for c in tool.get("capabilities", []))

    def dispatch(self, tool_name: str, args: dict, turn_allowances: list[str],
                 executor: Callable[[str, dict], Any],
                 payload_text: Optional[str] = None,
                 destination: Optional[str] = None
                 ) -> tuple[GateDecision, Optional[str]]:
        """THE dispatch entry point. The gate is the first statement — no path
        around it. Returns (decision, wrapped_output_or_None)."""
        decision = self.check(tool_name, args, turn_allowances)
        if decision.verdict in (Verdict.DENY, Verdict.REQUIRE_APPROVAL):
            return decision, None
        tool = self.registry[tool_name]
        if self._is_network_bound(tool):
            # DCL governs *telling*: a second, independent gate before send.
            if payload_text is None:
                return GateDecision(
                    Verdict.DENY,
                    "network-bound tool requires an egress check"), None
            eg = self.check_egress(payload_text, destination or "unknown")
            if eg.verdict is not Verdict.ALLOW:
                return eg, None
        try:
            raw = executor(tool_name, args)
        except Exception as exc:  # noqa: BLE001 - executor failures are denies
            return GateDecision(
                Verdict.DENY, f"executor raised {type(exc).__name__}"), None
        return decision, self.wrap_output(raw, source=tool_name)

    def execute_approved(self, token: str, tool_name: str, args: dict,
                         executor: Callable[[str, dict], Any]
                         ) -> tuple[GateDecision, Optional[str]]:
        """Second half of a tier-3 flow. Re-validates declaration + schema,
        then demands the token prove the approval was for THIS action."""
        tool = self.registry.get(tool_name)
        if tool is None or tool.get("tier") != 3:
            return GateDecision(
                Verdict.DENY, "approved tool no longer declared tier-3"), None
        ok, why = _validate_args(tool.get("schema"), args)
        if not ok:
            return GateDecision(
                Verdict.DENY, f"approved args no longer valid: {why}"), None
        if not self.verify_token(token, tool_name, args):
            return GateDecision(
                Verdict.DENY,
                "approval token mismatch: replay or tampered args denied"), None
        try:
            raw = executor(tool_name, args)
        except Exception as exc:  # noqa: BLE001
            return GateDecision(
                Verdict.DENY, f"executor raised {type(exc).__name__}"), None
        return (GateDecision(Verdict.ALLOW, "approved action executed"),
                self.wrap_output(raw, source=tool_name))

    # ------------------------------------------------------------- egress
    def check_egress(self, text: str, destination: str) -> GateDecision:
        """The DCL stage: governs *telling*. SECRET -> DENY (reason names the
        finding KIND, never the secret value). Independent of check()."""
        if _dcl is None:
            return GateDecision(
                Verdict.DENY, "DCL unavailable: fail closed, no egress allowed")
        try:
            cls, findings = _dcl.classify(text or "")
        except Exception as exc:  # noqa: BLE001 - classifier failure is deny
            return GateDecision(
                Verdict.DENY, f"DCL error: fail closed ({type(exc).__name__})")
        kinds = sorted({f.get("kind", "unknown") for f in (findings or [])
                        if isinstance(f, dict)})
        label = ",".join(kinds) if kinds else "unclassified"
        if cls == "SECRET":
            return GateDecision(
                Verdict.DENY,
                f"SECRET data ({label}) may never leave this machine (P0-3)")
        if cls == "SENSITIVE":
            return GateDecision(
                Verdict.REQUIRE_APPROVAL,
                f"SENSITIVE data ({label}) to {destination}: confirm per item (P1-13)",
                approval_request={"destination": destination,
                                  "finding_kinds": kinds},
            )
        if cls == "PERSONAL":
            self.feed_log.append({"destination": destination, "class": "PERSONAL",
                                  "kinds": kinds, "ts": int(time.time())})
            return GateDecision(
                Verdict.ALLOW,
                f"PERSONAL data to {destination}: allowed, logged to feed")
        return GateDecision(Verdict.ALLOW, f"PUBLIC data to {destination}: allowed")

    # ---------------------------------------------------------- wrapping
    @staticmethod
    def wrap_output(output: Any, source: str, trust: str = "untrusted") -> str:
        """Non-negotiable evidence wrapper (P1-1). Tool output is DATA, never
        instructions. The wrapper marks it; the brain must treat it as data."""
        for name, val in (("source", source), ("trust", trust)):
            if not isinstance(val, str) or not val \
                    or any(c in val for c in ('"', ">", "<")):
                raise ValueError(f"invalid {name} for tool_output wrapper")
        text = "" if output is None else str(output)
        # Breakout guard: a forged <tool_output ...> tag inside untrusted
        # content must never parse as a wrapper element. Break the tag name
        # (invisible zero-width space) so no parser mistakes payload for frame.
        text = re.sub(r"<(/?)tool_output", "<\u200b\\1tool_output", text,
                      flags=re.IGNORECASE)
        return f'<tool_output source="{source}" trust="{trust}">{text}</tool_output>'
