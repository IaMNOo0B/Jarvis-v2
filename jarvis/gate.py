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

try:
    from jarvis import shell_guard as _shell_guard
except Exception:  # shell guard missing -> shell checks fail closed
    _shell_guard = None

try:
    from jarvis import effects as _effects
except Exception:  # effects journal missing -> dispatches simply don't journal
    _effects = None


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
                 skill_registry: Optional[dict] = None,
                 egress_sink: Optional[Callable[[dict], None]] = None,
                 effect_sink: Optional[Callable[[dict], None]] = None,
                 effect_fs_root: Optional[str] = None,
                 fact_exists: Optional[Callable[[str], bool]] = None,
                 postcondition_evaluator: Optional[Callable] = None,
                 contract_sink: Optional[Callable[[dict], None]] = None,
                 flag_checker: Optional[Callable[[str, bool], bool]] = None):
        self.rules = rules or {}
        self.registry = skill_registry or {}
        # Owner kill-switch (Team 19 E1): Config.is_enabled wired in by the
        # app layer. Called as flag_checker(name, True) — the True default
        # means "absent flag = enabled"; only a flag the owner explicitly
        # set to false ("skill.<name>" or "tool.<tool.name>" in the config
        # flags section) denies dispatch. None = no flags wired, behaviour
        # identical to before this check existed.
        self.flag_checker = flag_checker
        # Optional durable "what left the machine" recorder (dcl.make_egress_
        # sink). Called with one metadata dict per egress decision; a broken
        # sink never changes a verdict.
        self.egress_sink = egress_sink
        # Recovery pack (effects journal + postcondition hook). All
        # optional; all best-effort: this machinery is EVIDENCE, never a
        # dependency — a broken sink/evaluator never changes a verdict,
        # never blocks output, never raises into the dispatch path.
        #   effect_sink: called once per successful dispatch with
        #     {"session_id", "turn_id", "tool", "records"} (see
        #     jarvis.effects.make_store_sink).
        #   postcondition_evaluator: (tool, args, declared, raw) -> report
        #     (see jarvis.contracts.make_evaluator); a failed report goes
        #     to contract_sink as a typed "postcondition_failed" record.
        self.effect_sink = effect_sink
        self.effect_fs_root = effect_fs_root
        self.fact_exists = fact_exists
        self.postcondition_evaluator = postcondition_evaluator
        self.contract_sink = contract_sink
        # Per-process HMAC key: tokens are unforgeable and die with the process.
        self._hmac_key = os.urandom(32)
        # P1-13: "what left the machine" feed (PERSONAL egress entries).
        self.feed_log: list[dict] = []

    # ------------------------------------------------------------- kill-switch
    def _flag_denied(self, tool_name: str,
                     tool: Optional[dict]) -> Optional[GateDecision]:
        """The ONE owner kill-switch check, consulted on both execution
        paths (check + execute_approved — a switch that only guards one
        path is theatre). A flag explicitly set false for the owning skill
        ("skill.<skill>") or the tool itself ("tool.<tool_name>") denies;
        absent flags never deny. A broken checker never denies either:
        flags are an owner override, not a new failure mode."""
        if self.flag_checker is None:
            return None
        names = []
        skill = (tool or {}).get("skill")
        if not skill and "." in tool_name:
            skill = tool_name.split(".", 1)[0]
        if skill:
            names.append(f"skill.{skill}")
        names.append(f"tool.{tool_name}")
        for name in names:
            try:
                enabled = self.flag_checker(name, True)
            except Exception:  # noqa: BLE001 - broken checker != denial
                return None
            if not enabled:
                return GateDecision(
                    Verdict.DENY, f"disabled by owner flag: {name}")
        return None

    # ------------------------------------------------------------------ check
    def check(self, tool_name: str, args: dict,
              turn_allowances: list[str]) -> GateDecision:
        """THE gate. First statement of dispatch. Order is load-bearing:

        1. declared?  2. owner kill-switch?  3. schema-valid?
        4. capabilities?  5. tier route.
        """
        tool = self.registry.get(tool_name)
        if tool is None:
            return GateDecision(Verdict.DENY, f"undeclared tool: {tool_name}")
        denied = self._flag_denied(tool_name, tool)
        if denied is not None:
            return denied
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

    # --------------------------------------- recovery pack (journal/hooks)
    def _prepare_effects(self, tool: dict, args: dict) -> Optional[list]:
        """Pre-execution: resolve the tool's DECLARED effects against the
        pre-state (existed_before must be probed before the tool runs —
        afterwards the truth is gone). None = nothing to journal."""
        declared = tool.get("effects")
        if not declared or _effects is None:
            return None
        try:
            return _effects.prepare_effects(
                declared, args, fs_root=self.effect_fs_root,
                fact_exists=self.fact_exists)
        except Exception:  # noqa: BLE001 - journaling never blocks a dispatch
            return None

    def _after_success(self, tool_name: str, tool: dict, args: dict,
                       raw: Any, pending_effects: Optional[list],
                       session_id: Optional[str], turn_id: Any) -> None:
        """Post-execution evidence: journal the effects, then run the
        postcondition hook. Best-effort throughout — see __init__."""
        if pending_effects:
            try:
                records = _effects.finalize_effects(
                    pending_effects, fs_root=self.effect_fs_root)
                if records and self.effect_sink is not None:
                    self.effect_sink({
                        "session_id": session_id, "turn_id": turn_id,
                        "tool": tool_name, "records": records,
                    })
            except Exception:  # noqa: BLE001
                pass
        declared_pc = tool.get("postconditions")
        if declared_pc and self.postcondition_evaluator is not None:
            try:
                report = self.postcondition_evaluator(
                    tool_name, args, declared_pc, raw)
                if report is not None and not report.get("passed", True) \
                        and self.contract_sink is not None:
                    self.contract_sink({
                        "event": "postcondition_failed",
                        "session_id": session_id, "turn_id": turn_id,
                        "tool": tool_name, "report": report,
                    })
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------ dispatch
    def _is_network_bound(self, tool: dict) -> bool:
        if tool.get("network_egress"):
            return True
        return any(str(c).startswith("net.") for c in tool.get("capabilities", []))

    def dispatch(self, tool_name: str, args: dict, turn_allowances: list[str],
                 executor: Callable[[str, dict], Any],
                 payload_text: Optional[str] = None,
                 destination: Optional[str] = None,
                 session_id: Optional[str] = None,
                 turn_id: Any = None
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
        # Recovery pack: probe declared effects against the PRE-state,
        # before the executor can change the world they describe.
        pending_effects = self._prepare_effects(tool, args)
        try:
            raw = executor(tool_name, args)
        except Exception as exc:  # noqa: BLE001 - executor failures are denies
            return GateDecision(
                Verdict.DENY, f"executor raised {type(exc).__name__}"), None
        self._after_success(tool_name, tool, args, raw, pending_effects,
                            session_id, turn_id)
        return decision, self.wrap_output(raw, source=tool_name)

    def execute_approved(self, token: str, tool_name: str, args: dict,
                         executor: Callable[[str, dict], Any],
                         session_id: Optional[str] = None,
                         turn_id: Any = None
                         ) -> tuple[GateDecision, Optional[str]]:
        """Second half of a tier-3 flow. Re-validates declaration + schema,
        then demands the token prove the approval was for THIS action."""
        tool = self.registry.get(tool_name)
        if tool is None or tool.get("tier") != 3:
            return GateDecision(
                Verdict.DENY, "approved tool no longer declared tier-3"), None
        denied = self._flag_denied(tool_name, tool)
        if denied is not None:
            return denied, None
        ok, why = _validate_args(tool.get("schema"), args)
        if not ok:
            return GateDecision(
                Verdict.DENY, f"approved args no longer valid: {why}"), None
        if not self.verify_token(token, tool_name, args):
            return GateDecision(
                Verdict.DENY,
                "approval token mismatch: replay or tampered args denied"), None
        pending_effects = self._prepare_effects(tool, args)
        try:
            raw = executor(tool_name, args)
        except Exception as exc:  # noqa: BLE001
            return GateDecision(
                Verdict.DENY, f"executor raised {type(exc).__name__}"), None
        self._after_success(tool_name, tool, args, raw, pending_effects,
                            session_id, turn_id)
        return (GateDecision(Verdict.ALLOW, "approved action executed"),
                self.wrap_output(raw, source=tool_name))

    # ------------------------------------------------------------- egress
    @staticmethod
    def _class_name(cls: Any) -> str:
        """Normalise a DCL result class to its NAME. The real DCL returns a
        DataClass enum; compare by name, never by identity with a string
        (an IntEnum never equals its name -- that mismatch once let SECRET
        payloads sail through as PUBLIC)."""
        name = getattr(cls, "name", None)
        return str(name if name is not None else cls).upper()

    @staticmethod
    def _finding_kinds(findings: Any) -> list[str]:
        """Finding KIND names from either representation: real DCL Finding
        dataclasses (kind lives in .pattern) or plain dicts (.kind/.pattern).
        Kinds only -- a secret VALUE must never reach a reason string."""
        kinds = set()
        for f in findings or []:
            kind = None
            if isinstance(f, dict):
                kind = f.get("kind") or f.get("pattern")
            else:
                kind = getattr(f, "pattern", None) or getattr(f, "kind", None)
            if kind:
                kinds.add(str(kind))
        return sorted(kinds)

    def _record_egress(self, destination: str, class_name: str,
                       kinds: list[str], action: str) -> None:
        """Best-effort durable audit (P1-13). Metadata only -- never content.
        A broken sink must never change or block a verdict."""
        if self.egress_sink is None:
            return
        try:
            self.egress_sink({
                "ts": int(time.time()), "destination": destination,
                "class": class_name, "kinds": kinds, "action": action,
                "source": "gate",
            })
        except Exception:  # noqa: BLE001 - audit failure != egress failure
            pass

    def check_egress(self, text: str, destination: str) -> GateDecision:
        """The DCL stage: governs *telling*. SECRET -> DENY (reason names the
        finding KIND, never the secret value). Independent of check()."""
        if _dcl is None:
            self._record_egress(destination, "UNCLASSIFIED", [], "withheld")
            return GateDecision(
                Verdict.DENY, "DCL unavailable: fail closed, no egress allowed")
        try:
            cls, findings = _dcl.classify(text or "")
        except Exception as exc:  # noqa: BLE001 - classifier failure is deny
            self._record_egress(destination, "UNCLASSIFIED", [], "withheld")
            return GateDecision(
                Verdict.DENY, f"DCL error: fail closed ({type(exc).__name__})")
        name = self._class_name(cls)
        kinds = self._finding_kinds(findings)
        label = ",".join(kinds) if kinds else "unclassified"
        if name == "SECRET":
            self._record_egress(destination, name, kinds, "withheld")
            return GateDecision(
                Verdict.DENY,
                f"SECRET data ({label}) may never leave this machine (P0-3)")
        if name == "SENSITIVE":
            self._record_egress(destination, name, kinds, "held_for_confirm")
            return GateDecision(
                Verdict.REQUIRE_APPROVAL,
                f"SENSITIVE data ({label}) to {destination}: confirm per item (P1-13)",
                approval_request={"destination": destination,
                                  "finding_kinds": kinds},
            )
        if name == "PERSONAL":
            self.feed_log.append({"destination": destination, "class": "PERSONAL",
                                  "kinds": kinds, "ts": int(time.time())})
            self._record_egress(destination, name, kinds, "sent")
            return GateDecision(
                Verdict.ALLOW,
                f"PERSONAL data to {destination}: allowed, logged to feed")
        self._record_egress(destination, name, kinds, "sent")
        return GateDecision(Verdict.ALLOW, f"PUBLIC data to {destination}: allowed")

    # ---------------------------------------------------------- shell guard
    def check_shell(self, command: str,
                    legacy_check: Optional[Callable[[str], Optional[str]]] = None
                    ) -> GateDecision:
        """Tokenised shell blocklist (shell_guard layer 2) composed with the
        legacy raw-string blocklist (layer 1, via the caller's callable --
        pc_control._check_blocklist). This is a GUARD, not a tier decision:
        shell execution stays tier-3 approval-gated regardless of the result.
        Fails closed if the guard module is unavailable."""
        if _shell_guard is None:
            return GateDecision(
                Verdict.DENY, "shell guard unavailable: fail closed")
        verdict = _shell_guard.check_command(command or "",
                                             legacy_check=legacy_check)
        if verdict.blocked:
            return GateDecision(
                Verdict.DENY,
                f"shell command blocked [{verdict.rule}]: {verdict.reason}")
        return GateDecision(
            Verdict.ALLOW, "shell command passed legacy + tokenised blocklists")

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
