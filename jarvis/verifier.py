"""Trajectory verifier: deterministic heuristic checkers (D3 variant).

From learn-discriminator-protocol.md §4: D3 = "schema validation +
precondition checklist + tier rules (deterministic)". Predicted 80-85%
overall, ~100% on structural flaws (F1/F2/F6). This is the layer that
runs BEFORE any LLM judge — cheap, fast, never wrong about structure.

Checks the 8 flaw types (F1-F8, §2.2):
  F1 wrong argument value      -> schema/type validation
  F2 missing precondition      -> existence/writability preconditions
  F3 unsafe ordering            -> backup-before-destructive ordering
  F4 wrong tool choice          -> prefer safe tools (trash over rm)
  F5 hallucinated reference     -> IDs must have been observed this session
  F6 missing confirmation       -> tier-2/3 need approval evidence
  F7 scope overreach             -> path containment vs stated scope
  F8 ignored user constraint    -> constraint matching ("don't touch X")

Input: a proposed trajectory = list of {"tool": name, "args": {...}}.
Context: user constraints, observed IDs, approval state, declared scope.

Output: Verdict per check + overall PASS/FAIL. FAIL = block execution.
"Both bad" equivalent: if the trajectory fails structural checks, it is
rejected outright — the brain must propose a better one.

Stdlib only. Python 3.11+.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class CheckResult:
    flaw: str          # F1..F8
    passed: bool
    detail: str        # what was checked / what failed


@dataclass
class Verdict:
    passed: bool
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def failures(self) -> List[CheckResult]:
        return [c for c in self.checks if not c.passed]


# Tools considered destructive-primitive (F4: prefer the safe alternative).
_UNSAFE_TOOLS = {
    "shell_rm": "use trash/recycle or a dedicated delete tool",
    "rm -rf": "use trash/recycle or a dedicated delete tool",
    "rm_rf": "use trash/recycle or a dedicated delete tool",
    "format": "no safe alternative — requires tier-3 confirmation",
    "dd": "no safe alternative — requires tier-3 confirmation",
}

# Ordering: these actions must be preceded by their safeguard (F3).
_REQUIRES_SAFEGUARD_FIRST = {
    "delete": ("backup", "verify the backup succeeded before deleting"),
    "uninstall": ("backup", "back up data before uninstalling"),
    "overwrite": ("backup", "keep the original before overwriting"),
}


class TrajectoryVerifier:
    """Deterministic pre-execution gate for tool trajectories."""

    def __init__(
        self,
        observed_ids: Optional[Set[str]] = None,
        user_constraints: Optional[List[str]] = None,
        approved_tools: Optional[Set[str]] = None,
        scope_roots: Optional[List[str]] = None,
        tool_schemas: Optional[Dict[str, Dict[str, Any]]] = None,
        tool_tiers: Optional[Dict[str, int]] = None,
    ) -> None:
        # IDs the agent has actually seen this session (pc.observe, etc.)
        self.observed_ids: Set[str] = set(observed_ids or ())
        # e.g. ["don't touch the photos", "only the downloads folder"]
        self.user_constraints: List[str] = [c.lower() for c in
                                             (user_constraints or [])]
        # tools with a live approval token this turn
        self.approved_tools: Set[str] = set(approved_tools or ())
        # declared scope roots, e.g. ["C:/Users/Owais/Downloads"]
        self.scope_roots: List[str] = [os.path.normpath(s).lower() for s in
                                       (scope_roots or [])]
        # {"tool": {"required": [...], "types": {"arg": "str"}}}
        self.tool_schemas: Dict[str, Dict[str, Any]] = tool_schemas or {}
        self.tool_tiers: Dict[str, int] = tool_tiers or {}

    # -- public ---------------------------------------------------------- #
    def verify(self, trajectory: List[Dict[str, Any]]) -> Verdict:
        checks: List[CheckResult] = []
        checks.append(self._f1_schema(trajectory))
        checks.append(self._f2_preconditions(trajectory))
        checks.append(self._f3_ordering(trajectory))
        checks.append(self._f4_tool_choice(trajectory))
        checks.append(self._f5_references(trajectory))
        checks.append(self._f6_confirmation(trajectory))
        checks.append(self._f7_scope(trajectory))
        checks.append(self._f8_constraints(trajectory))
        return Verdict(passed=all(c.passed for c in checks), checks=checks)

    # -- F1: schema validation ------------------------------------------- #
    def _f1_schema(self, traj: List[Dict[str, Any]]) -> CheckResult:
        for i, step in enumerate(traj):
            tool, args = step.get("tool", ""), step.get("args", {}) or {}
            schema = self.tool_schemas.get(tool)
            if not schema:
                continue  # unknown tool: registry validation owns this
            for req in schema.get("required", []):
                if req not in args or args[req] in (None, ""):
                    return CheckResult("F1", False,
                                       f"step {i}: {tool} missing required "
                                       f"argument {req!r}")
            for arg, want in schema.get("types", {}).items():
                if arg in args and args[arg] is not None:
                    if want == "str" and not isinstance(args[arg], str):
                        return CheckResult("F1", False,
                                           f"step {i}: {tool}.{arg} must be "
                                           f"str, got {type(args[arg]).__name__}")
                    if want == "int" and not isinstance(args[arg], int):
                        return CheckResult("F1", False,
                                           f"step {i}: {tool}.{arg} must be "
                                           f"int, got {type(args[arg]).__name__}")
        return CheckResult("F1", True, "all arguments schema-valid")

    # -- F2: preconditions ------------------------------------------------ #
    def _f2_preconditions(self, traj: List[Dict[str, Any]]) -> CheckResult:
        for i, step in enumerate(traj):
            tool = step.get("tool", "")
            args = step.get("args", {}) or {}
            base = tool.split(".")[-1].lower()
            is_file_op = any(k in base for k in
                             ("write", "overwrite", "delete", "read"))
            if is_file_op:
                path = args.get("path", "")
                if not path:
                    return CheckResult("F2", False,
                                       f"step {i}: {tool} with empty path — "
                                       f"precondition (target exists) unchecked")
                if ".." in str(path) and \
                        any(k in base for k in ("delete", "overwrite")):
                    return CheckResult("F2", False,
                                       f"step {i}: {tool} path {path!r} "
                                       f"escapes its directory")
        return CheckResult("F2", True, "preconditions satisfied")

    # -- F3: ordering ------------------------------------------------------ #
    def _f3_ordering(self, traj: List[Dict[str, Any]]) -> CheckResult:
        seen_safeguards: Set[str] = set()
        for i, step in enumerate(traj):
            tool = step.get("tool", "")
            base = tool.split(".")[-1].lower()
            if base in ("backup", "snapshot", "verify"):
                seen_safeguards.add(base)
            for action, (safeguard, why) in _REQUIRES_SAFEGUARD_FIRST.items():
                if action in base and safeguard not in seen_safeguards \
                        and "verify" not in seen_safeguards:
                    return CheckResult("F3", False,
                                       f"step {i}: {tool} before {safeguard} "
                                       f"— {why}")
        return CheckResult("F3", True, "destructive steps properly ordered")

    # -- F4: tool choice --------------------------------------------------- #
    def _f4_tool_choice(self, traj: List[Dict[str, Any]]) -> CheckResult:
        for i, step in enumerate(traj):
            tool = step.get("tool", "")
            args = step.get("args", {}) or {}
            if tool in _UNSAFE_TOOLS:
                return CheckResult("F4", False,
                                   f"step {i}: {tool} — "
                                   f"{_UNSAFE_TOOLS[tool]}")
            # shell rm -rf smuggled inside a generic shell call
            if tool in ("pc.shell", "shell", "run_in_terminal"):
                cmd = str(args.get("command", args.get("cmd", "")))
                if re.search(r"\brm\s+-rf?\b", cmd):
                    return CheckResult("F4", False,
                                       f"step {i}: shell '{cmd[:60]}' — use "
                                       f"trash/recycle, not rm -rf")
        return CheckResult("F4", True, "tool choices safe")

    # -- F5: hallucinated references --------------------------------------- #
    def _f5_references(self, traj: List[Dict[str, Any]]) -> CheckResult:
        if not self.observed_ids:
            return CheckResult("F5", True,
                               "no observed-ID registry — check skipped")
        for i, step in enumerate(traj):
            args = step.get("args", {}) or {}
            for key in ("element_id", "window_id", "handle", "id"):
                val = args.get(key)
                if val and str(val) not in self.observed_ids:
                    return CheckResult("F5", False,
                                       f"step {i}: {key}={val!r} was never "
                                       f"observed this session — hallucinated "
                                       f"reference")
        return CheckResult("F5", True, "all references observed")

    # -- F6: confirmation --------------------------------------------------- #
    def _f6_confirmation(self, traj: List[Dict[str, Any]]) -> CheckResult:
        for i, step in enumerate(traj):
            tool = step.get("tool", "")
            tier = self.tool_tiers.get(tool, 1)
            if tier >= 2 and tool not in self.approved_tools:
                return CheckResult("F6", False,
                                   f"step {i}: tier-{tier} tool {tool!r} has "
                                   f"no approval evidence this turn")
        return CheckResult("F6", True, "tier-2/3 actions approved")

    # -- F7: scope ---------------------------------------------------------- #
    def _f7_scope(self, traj: List[Dict[str, Any]]) -> CheckResult:
        if not self.scope_roots:
            return CheckResult("F7", True,
                               "no declared scope — check skipped")
        for i, step in enumerate(traj):
            args = step.get("args", {}) or {}
            path = str(args.get("path", ""))
            if not path:
                continue
            norm = os.path.normpath(path).lower()
            if not any(norm == r or norm.startswith(r + os.sep)
                       for r in self.scope_roots):
                return CheckResult("F7", False,
                                   f"step {i}: path {path!r} escapes declared "
                                   f"scope {self.scope_roots}")
        return CheckResult("F7", True, "all paths within declared scope")

    # -- F8: user constraints ----------------------------------------------- #
    def _f8_constraints(self, traj: List[Dict[str, Any]]) -> CheckResult:
        if not self.user_constraints:
            return CheckResult("F8", True, "no user constraints declared")
        blob = " ".join(
            f"{s.get('tool', '')} {s.get('args', {})}" for s in traj).lower()
        for c in self.user_constraints:
            # "don't touch X" / "never X" / "only X"
            m = re.search(r"(?:don't|never|no)\s+(?:touch|delete|modify|open)\s+"
                          r"(?:the\s+)?(\w+)", c)
            if m and m.group(1) in blob:
                # crude but catches the common case; the brain owns nuance
                if "delete" in c or "touch" in c:
                    for s in traj:
                        t, a = s.get("tool", ""), str(s.get("args", {}))
                        if ("delete" in t or "write" in t) and \
                                m.group(1) in a.lower():
                            return CheckResult("F8", False,
                                               f"trajectory violates user "
                                               f"constraint: {c!r}")
        return CheckResult("F8", True, "no constraint violations detected")
