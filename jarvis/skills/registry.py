"""v2 skill system — a jail with a guest list.

Discovery reads ``skill.json`` manifests ONLY (never executes skill code).
Strict validation: unknown manifest keys are a startup error naming the
skill. New or changed manifests land in quarantine until approved.

Dispatch pipeline (deterministic, never silent):
    parse -> schema-validate -> capability-check -> risk-gate
      -> isolated call (timeout + output cap) -> output-validate
      -> evidence-wrap

The LLM does judgment only (which tool, which args). Everything checkable
is checked by code. Tool output always enters context wrapped and marked
``trust="untrusted"``.

Stdlib only. Python 3.11+.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "CAPABILITIES",
    "SkillError",
    "UnknownTool",
    "CapabilityDenied",
    "PathDenied",
    "GateDenied",
    "SkillManifest",
    "ToolDef",
    "SkillRecord",
    "SkillContext",
    "SkillRegistry",
    "discover",
    "scan_skill",
    "validate_against_schema",
]

# ---------------------------------------------------------------------------
# Vocabulary & constants (closed — anything else is denied)
# ---------------------------------------------------------------------------

CAPABILITIES = frozenset(
    {"fs.read", "fs.write", "net.outbound", "exec", "time.read", "clipboard.read"}
)

DEFAULT_TIMEOUT_S = 5
DEFAULT_OUTPUT_CAP_CHARS = 10 * 1024  # 10KB
CIRCUIT_BREAKER_THRESHOLD = 3
IMPORT_TIMEOUT_S = 5

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

KNOWN_MANIFEST_KEYS = frozenset(
    {"name", "version", "description", "capabilities", "tools", "lifecycle", "resources"}
)
KNOWN_TOOL_KEYS = frozenset(
    {
        "name",
        "description",
        "parameters",
        "schema",  # alias for parameters
        "returns",
        "tier",
        "risk_tier",  # alias for tier
        "timeout_s",
        "output_cap_chars",
        "capabilities",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SkillError(Exception):
    """Base class for skill-system errors."""


class SkillManifestError(SkillError):
    """A skill.json manifest is missing, unreadable, or invalid."""


class UnknownTool(SkillError):
    """No registered tool by that name."""


class CapabilityDenied(SkillError):
    """A capability the skill was not granted was requested."""


class PathDenied(SkillError):
    """A file path escaped the skill's jail."""


class GateDenied(SkillError):
    """The risk gate refused a tool call."""


# ---------------------------------------------------------------------------
# Manifests (strict — unknown keys raise)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    parameters: dict
    returns: dict
    tier: int = 1
    timeout_s: int = DEFAULT_TIMEOUT_S
    output_cap_chars: int = DEFAULT_OUTPUT_CAP_CHARS
    capabilities: tuple = ()

    @classmethod
    def from_dict(cls, data: Any, *, source: str) -> "ToolDef":
        if not isinstance(data, dict):
            raise SkillManifestError(f"{source}: tool must be a JSON object")
        unknown = set(data) - KNOWN_TOOL_KEYS
        if unknown:
            raise SkillManifestError(
                f"{source}: unknown tool keys {sorted(unknown)} (typo?)"
            )
        name = data.get("name")
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise SkillManifestError(
                f"{source}: tool 'name' must match ^[a-z][a-z0-9_]*$, got {name!r}"
            )
        description = data.get("description", "")
        if not isinstance(description, str):
            raise SkillManifestError(f"{source}: tool 'description' must be a string")
        parameters = data.get("parameters", data.get("schema", {}))
        if not isinstance(parameters, dict):
            raise SkillManifestError(f"{source}: tool 'parameters' must be an object")
        returns = data.get("returns", {})
        if not isinstance(returns, dict):
            raise SkillManifestError(f"{source}: tool 'returns' must be an object")
        tier = data.get("tier", data.get("risk_tier", 1))
        if tier not in (1, 2, 3):
            raise SkillManifestError(
                f"{source}: tool 'tier' must be 1, 2 or 3, got {tier!r}"
            )
        timeout_s = data.get("timeout_s", DEFAULT_TIMEOUT_S)
        if not isinstance(timeout_s, int) or timeout_s <= 0:
            raise SkillManifestError(
                f"{source}: 'timeout_s' must be a positive int, got {timeout_s!r}"
            )
        output_cap_chars = data.get("output_cap_chars", DEFAULT_OUTPUT_CAP_CHARS)
        if not isinstance(output_cap_chars, int) or output_cap_chars <= 0:
            raise SkillManifestError(
                f"{source}: 'output_cap_chars' must be a positive int"
            )
        capabilities = data.get("capabilities", ())
        if not isinstance(capabilities, list) or not all(
            isinstance(c, str) for c in capabilities
        ):
            raise SkillManifestError(
                f"{source}: tool 'capabilities' must be a string list"
            )
        bad_caps = set(capabilities) - CAPABILITIES
        if bad_caps:
            raise SkillManifestError(
                f"{source}: unknown capabilities {sorted(bad_caps)} "
                f"(closed vocabulary: {sorted(CAPABILITIES)})"
            )
        return cls(
            name=name,
            description=description,
            parameters=parameters,
            returns=returns,
            tier=tier,
            timeout_s=timeout_s,
            output_cap_chars=output_cap_chars,
            capabilities=tuple(capabilities),
        )


@dataclass(frozen=True)
class SkillManifest:
    name: str
    version: str
    description: str
    capabilities: tuple
    tools: tuple

    @classmethod
    def from_dict(cls, data: Any, *, source: str) -> "SkillManifest":
        if not isinstance(data, dict):
            raise SkillManifestError(f"{source}: manifest must be a JSON object")
        unknown = set(data) - KNOWN_MANIFEST_KEYS
        if unknown:
            raise SkillManifestError(
                f"{source}: unknown manifest keys {sorted(unknown)} (typo?)"
            )
        name = data.get("name")
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise SkillManifestError(
                f"{source}: 'name' must match ^[a-z][a-z0-9_]*$, got {name!r}"
            )
        version = data.get("version")
        if not isinstance(version, str) or not _SEMVER_RE.match(version):
            raise SkillManifestError(
                f"{source}: 'version' must be MAJOR.MINOR.PATCH, got {version!r}"
            )
        description = data.get("description", "")
        if not isinstance(description, str):
            raise SkillManifestError(f"{source}: 'description' must be a string")
        capabilities = data.get("capabilities", [])
        if not isinstance(capabilities, list) or not all(
            isinstance(c, str) for c in capabilities
        ):
            raise SkillManifestError(
                f"{source}: 'capabilities' must be a string list"
            )
        bad_caps = set(capabilities) - CAPABILITIES
        if bad_caps:
            raise SkillManifestError(
                f"{source}: unknown capabilities {sorted(bad_caps)} "
                f"(closed vocabulary: {sorted(CAPABILITIES)})"
            )
        tools_raw = data.get("tools")
        if not isinstance(tools_raw, list):
            raise SkillManifestError(f"{source}: 'tools' must be a list")
        tools = tuple(
            ToolDef.from_dict(t, source=f"{source} tool[{i}]")
            for i, t in enumerate(tools_raw)
        )
        seen: set[str] = set()
        for t in tools:
            if t.name in seen:
                raise SkillManifestError(
                    f"{source}: duplicate tool name {t.name!r} in one skill"
                )
            seen.add(t.name)
        return cls(
            name=name,
            version=version,
            description=description,
            capabilities=tuple(capabilities),
            tools=tools,
        )

    def canonical_hash(self) -> str:
        """Hash of the canonical manifest — quarantine trigger on change."""
        blob = json.dumps(
            {
                "name": self.name,
                "version": self.version,
                "description": self.description,
                "capabilities": sorted(self.capabilities),
                "tools": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                        "returns": t.returns,
                        "tier": t.tier,
                        "timeout_s": t.timeout_s,
                        "output_cap_chars": t.output_cap_chars,
                        "capabilities": sorted(t.capabilities),
                    }
                    for t in self.tools
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class SkillRecord:
    name: str
    path: Path
    manifest: SkillManifest | None = None
    manifest_hash: str = ""
    approved: bool = False
    approved_hash: str = ""
    module: Any | None = None
    load_error: BaseException | None = None
    enabled: bool = True
    failures: int = 0
    disabled_reason: str = ""
    invoked_tools: set = field(default_factory=set)

    @property
    def circuit_open(self) -> bool:
        return self.failures >= CIRCUIT_BREAKER_THRESHOLD

    @property
    def healthy(self) -> bool:
        return (
            self.manifest is not None
            and self.load_error is None
            and self.module is not None
            and self.enabled
            and not self.circuit_open
        )


# ---------------------------------------------------------------------------
# JSON-Schema-subset validation (stdlib only)
# ---------------------------------------------------------------------------


def validate_against_schema(instance: Any, schema: dict, path: str = "$") -> list[str]:
    """Validate instance against a JSON-Schema subset. Returns error list."""
    errors: list[str] = []
    if not isinstance(schema, dict):
        return errors
    expected = schema.get("type")
    if expected is not None:
        ok = {
            "object": lambda v: isinstance(v, dict),
            "array": lambda v: isinstance(v, list),
            "string": lambda v: isinstance(v, str),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "boolean": lambda v: isinstance(v, bool),
            "null": lambda v: v is None,
        }.get(expected, lambda v: True)(instance)
        if not ok:
            errors.append(f"{path}: expected {expected}, got {type(instance).__name__}")
            return errors
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']}")
    if isinstance(instance, dict):
        for req in schema.get("required", []):
            if req not in instance:
                errors.append(f"{path}: missing required property {req!r}")
        props = schema.get("properties", {})
        for key, val in instance.items():
            if key in props:
                errors.extend(validate_against_schema(val, props[key], f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property {key!r}")
    if isinstance(instance, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for i, val in enumerate(instance):
                errors.extend(validate_against_schema(val, items, f"{path}[{i}]"))
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: fewer than minItems={schema['minItems']}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: more than maxItems={schema['maxItems']}")
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: shorter than minLength={schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path}: longer than maxLength={schema['maxLength']}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: below minimum={schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: above maximum={schema['maximum']}")
    return errors


# ---------------------------------------------------------------------------
# SkillContext — the ONLY world access a skill gets
# ---------------------------------------------------------------------------


class SkillContext:
    """Constrained world access for skill code.

    Every method checks the granted capability first. File access is jailed:
    paths resolve inside ``jail_dir``; anything else raises PathDenied.
    """

    def __init__(
        self,
        *,
        skill_name: str,
        capabilities: tuple | list = (),
        jail_dir: str | Path = ".",
        turn_id: int = 0,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.skill_name = skill_name
        self.capabilities = tuple(capabilities)
        self.jail_dir = Path(jail_dir)
        self.turn_id = turn_id
        self._logs: list[str] = []
        self._log_fn = log or self._logs.append

    # -- capability gate -------------------------------------------------
    def _require(self, cap: str) -> None:
        if cap not in self.capabilities:
            raise CapabilityDenied(
                f"skill {self.skill_name!r} lacks capability {cap!r} "
                f"(granted: {sorted(self.capabilities)})"
            )

    # -- jail ------------------------------------------------------------
    def _jailed(self, relpath: str) -> Path:
        if Path(relpath).is_absolute():
            raise PathDenied(f"absolute paths are denied: {relpath!r}")
        target = (self.jail_dir / relpath).resolve()
        jail = self.jail_dir.resolve()
        if target != jail and jail not in target.parents:
            raise PathDenied(f"path escapes jail: {relpath!r}")
        return target

    def for_skill(self, skill_name: str, jail_dir: str | Path) -> "SkillContext":
        """Child context scoped to one skill's jail; capabilities inherited."""
        return SkillContext(
            skill_name=skill_name,
            capabilities=self.capabilities,
            jail_dir=jail_dir,
            turn_id=self.turn_id,
            log=self._log_fn,
        )

    # -- world API --------------------------------------------------------
    def read_file(self, relpath: str) -> str:
        self._require("fs.read")
        return self._jailed(relpath).read_text(encoding="utf-8")

    def write_file(self, relpath: str, content: str) -> None:
        self._require("fs.write")
        target = self._jailed(relpath)
        target.parent.mkdir(parents=True, exist_ok=True)
        # atomic: tmp + rename (never a torn write)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(target)

    def list_dir(self, relpath: str = "") -> list[str]:
        self._require("fs.read")
        target = self._jailed(relpath or ".")
        return sorted(p.name for p in target.iterdir()) if target.is_dir() else []

    def now(self) -> str:
        self._require("time.read")
        return datetime.now(timezone.utc).isoformat()

    def log(self, message: str) -> None:
        self._log_fn(f"[{self.skill_name}] {message}")

    @property
    def logs(self) -> list[str]:
        return list(self._logs)


# ---------------------------------------------------------------------------
# Static scan — cheap, deterministic, no LLM
# ---------------------------------------------------------------------------


def scan_skill(skill_path: str | Path) -> list[dict]:
    """Statically scan a skill directory. Returns findings (empty = clean)."""
    path = Path(skill_path)
    findings: list[dict] = []

    def flag(rule: str, lineno: int, message: str) -> None:
        findings.append({"rule": rule, "lineno": lineno, "message": message})

    manifest_caps: set[str] = set()
    manifest_file = path / "skill.json"
    if manifest_file.is_file():
        try:
            manifest_caps = set(
                json.loads(manifest_file.read_text(encoding="utf-8")).get(
                    "capabilities", []
                )
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            flag("manifest-unreadable", 0, "skill.json is not valid JSON")

    src_file = path / "skill.py"
    if not src_file.is_file():
        flag("missing-entrypoint", 0, "skill.py not found")
        return findings
    try:
        tree = ast.parse(src_file.read_text(encoding="utf-8"), filename=str(src_file))
    except SyntaxError as exc:
        flag("syntax-error", exc.lineno or 0, f"skill.py has a syntax error: {exc}")
        return findings

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id in ("eval", "exec"):
                    flag(
                        "dangerous-call",
                        node.lineno,
                        f"{func.id}() is forbidden in skill code",
                    )
                elif func.id == "__import__":
                    flag(
                        "dangerous-call",
                        node.lineno,
                        "__import__() is forbidden in skill code",
                    )
                elif func.id == "open":
                    _flag_absolute_path_arg(node, flag)
            elif isinstance(func, ast.Attribute):
                base = func.value
                base_name = base.id if isinstance(base, ast.Name) else ""
                if base_name == "os" and func.attr == "system":
                    flag(
                        "dangerous-call",
                        node.lineno,
                        "os.system() is forbidden in skill code",
                    )
                if base_name == "subprocess":
                    flag(
                        "subprocess-use",
                        node.lineno,
                        "subprocess use is suspicious — 'exec' capability must be declared",
                    )
                if func.attr in ("Path", "open") and base_name in ("pathlib", ""):
                    _flag_absolute_path_arg(node, flag)

    if {"socket", "requests", "urllib", "http", "httpx"} & imported:
        if "net.outbound" not in manifest_caps:
            flag(
                "capability-mismatch",
                0,
                "code imports network modules but manifest lacks 'net.outbound'",
            )
    if "subprocess" in imported and "exec" not in manifest_caps:
        flag(
            "capability-mismatch",
            0,
            "code imports subprocess but manifest lacks 'exec'",
        )
    return findings


def _flag_absolute_path_arg(node: ast.Call, flag: Callable) -> None:
    if node.args and isinstance(node.args[0], ast.Constant):
        val = node.args[0].value
        if isinstance(val, str) and (
            val.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", val)
        ):
            flag(
                "absolute-path",
                node.lineno,
                f"absolute path literal {val!r} — skill must use relative paths in its jail",
            )


# ---------------------------------------------------------------------------
# Discovery — manifests ONLY, never executes skill code
# ---------------------------------------------------------------------------


def discover(skills_dir: str | Path) -> list[SkillRecord]:
    """Scan skills_dir; return records. Bad manifests are recorded, never fatal."""
    skills_dir = Path(skills_dir)
    if not skills_dir.is_dir():
        raise SkillError(f"skills directory not found: {skills_dir}")
    records: list[SkillRecord] = []
    by_name: dict[str, SkillRecord] = {}
    for child in sorted(skills_dir.iterdir()):
        manifest_file = child / "skill.json"
        if not child.is_dir() or not manifest_file.is_file():
            continue  # not a skill — ignored, not an error
        rec = SkillRecord(name=child.name, path=child)
        try:
            raw = json.loads(manifest_file.read_text(encoding="utf-8"))
            manifest = SkillManifest.from_dict(raw, source=str(manifest_file))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            rec.load_error = SkillManifestError(
                f"{manifest_file}: invalid JSON: {exc}"
            )
        except SkillManifestError as exc:
            rec.load_error = exc
        else:
            if manifest.name != child.name:
                rec.load_error = SkillManifestError(
                    f"{manifest_file}: manifest name {manifest.name!r} must match "
                    f"directory name {child.name!r}"
                )
            elif manifest.name in by_name:
                other = by_name[manifest.name]
                rec.load_error = SkillManifestError(
                    f"duplicate skill name {manifest.name!r}: {child} and {other.path}"
                )
            else:
                rec.manifest = manifest
                rec.manifest_hash = manifest.canonical_hash()
                by_name[manifest.name] = rec
        records.append(rec)
    # cross-skill tool-name collisions — startup error, never shadowing
    tool_owners: dict[str, str] = {}
    for rec in records:
        if rec.manifest is None or rec.load_error is not None:
            continue
        for tool in rec.manifest.tools:
            if tool.name in tool_owners:
                rec.load_error = SkillManifestError(
                    f"tool-name collision: tool {tool.name!r} in both "
                    f"{tool_owners[tool.name]!r} and {rec.name!r} — no shadowing allowed"
                )
                rec.manifest = None
                break
            tool_owners[tool.name] = rec.name
    return records


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class SkillRegistry:
    """Owns discovery, quarantine, loading, dispatch, and circuit breakers."""

    def __init__(self, skills_dir: str | Path, data_dir: str | Path) -> None:
        self.skills_dir = Path(skills_dir)
        self.data_dir = Path(data_dir)
        self._records: dict[str, SkillRecord] = {}
        self._pending: dict[int, list[dict]] = {}
        self._namespace = f"_jarvis_skills_{id(self):x}"
        # Approvals survive re-discovery: {skill_name: approved_manifest_hash}.
        # A changed manifest hash therefore re-triggers quarantine.
        self._approvals: dict[str, str] = {}

    # -- discovery / registration --------------------------------------
    def discover(self) -> list[SkillRecord]:
        self._records = {r.name: r for r in discover(self.skills_dir)}
        for name, rec in self._records.items():
            if name in self._approvals and rec.manifest is not None:
                rec.approved = True
                rec.approved_hash = self._approvals[name]
        return list(self._records.values())

    def register(self, manifest: dict | SkillManifest, path: str | Path) -> SkillRecord:
        """Programmatic registration (same strict validation as discovery)."""
        path = Path(path)
        if isinstance(manifest, dict):
            manifest = SkillManifest.from_dict(
                manifest, source=f"{path}/skill.json"
            )
        if manifest.name in self._records:
            raise SkillError(f"duplicate skill name {manifest.name!r}")
        rec = SkillRecord(
            name=manifest.name,
            path=path,
            manifest=manifest,
            manifest_hash=manifest.canonical_hash(),
        )
        self._records[manifest.name] = rec
        return rec

    # -- quarantine ------------------------------------------------------
    def approve(self, name: str) -> None:
        """Release a skill from quarantine; records the manifest hash."""
        rec = self._records[name]
        if rec.manifest is None:
            raise SkillError(f"cannot approve {name!r}: no valid manifest")
        rec.approved = True
        rec.approved_hash = rec.manifest_hash
        self._approvals[name] = rec.manifest_hash

    def quarantine(self) -> list[str]:
        """Names awaiting approval: never approved, or manifest changed."""
        out = []
        for name, rec in sorted(self._records.items()):
            if rec.manifest is None or rec.load_error is not None:
                continue
            if not rec.approved or rec.approved_hash != rec.manifest_hash:
                out.append(name)
        return out

    # -- tool resolution ---------------------------------------------------
    def get_tool(self, name: str) -> dict:
        """Resolve a tool name -> {tier, schema, capabilities, skill, ...}."""
        for rec in self._records.values():
            if rec.manifest is None:
                continue
            for tool in rec.manifest.tools:
                if tool.name == name:
                    return {
                        "name": tool.name,
                        "tier": tool.tier,
                        "schema": tool.parameters,
                        "returns": tool.returns,
                        "capabilities": list(tool.capabilities),
                        "skill": rec.name,
                        "description": tool.description,
                        "timeout_s": tool.timeout_s,
                        "output_cap_chars": tool.output_cap_chars,
                    }
        raise UnknownTool(f"unknown tool {name!r}")

    def tools_for_task(self, capabilities: list[str]) -> list[dict]:
        """Tool list the brain may see: approved, enabled, granted tools only."""
        caps = set(capabilities)
        out = []
        for rec in self._records.values():
            if not self._dispatchable(rec):
                continue
            for tool in rec.manifest.tools:  # type: ignore[union-attr]
                if set(tool.capabilities) <= caps:
                    out.append(self.get_tool(tool.name))
        return out

    # -- loading (importlib, never exec) -------------------------------------
    def _jail_for(self, skill_name: str) -> Path:
        jail = self.data_dir / skill_name
        jail.mkdir(parents=True, exist_ok=True)
        return jail

    def load(self, name: str) -> SkillRecord:
        """Import one skill's module. Unapproved skills are never imported."""
        rec = self._records[name]
        if rec.module is not None or rec.load_error is not None:
            return rec
        if rec.manifest is None or not rec.enabled or not rec.approved:
            return rec
        skill_file = rec.path / "skill.py"
        module_name = f"{self._namespace}.{rec.manifest.name}"
        box: dict[str, Any] = {}

        def _do_import() -> None:
            try:
                if not skill_file.is_file():
                    raise SkillError(f"{name}: skill.py not found in {rec.path}")
                spec = importlib.util.spec_from_file_location(
                    module_name, skill_file
                )
                if spec is None or spec.loader is None:
                    raise SkillError(f"{name}: could not build import spec")
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                try:
                    spec.loader.exec_module(module)
                except BaseException:
                    sys.modules.pop(module_name, None)
                    raise
                box["module"] = module
            except BaseException as exc:  # one bad skill never kills the host
                sys.modules.pop(module_name, None)
                box["error"] = exc

        worker = threading.Thread(target=_do_import, daemon=True)
        worker.start()
        worker.join(IMPORT_TIMEOUT_S)
        if worker.is_alive():
            rec.load_error = SkillError(
                f"{name}: import timed out after {IMPORT_TIMEOUT_S}s"
            )
        elif "error" in box:
            rec.load_error = box["error"]
        else:
            rec.module = box["module"]
            handle = getattr(rec.module, "handle", None)
            if not callable(handle):
                rec.module = None
                rec.load_error = SkillError(
                    f"{name}: handle(tool_name, args, ctx) not found or not callable"
                )
        return rec

    # -- wiring audit ----------------------------------------------------------
    def audit_wiring(self) -> list[str]:
        """Names of approved+enabled skills whose handler is missing/broken.

        Empty list == every registered tool resolves to an actual handler.
        """
        orphans: list[str] = []
        for name in sorted(self._records):
            rec = self._records[name]
            if rec.manifest is None or not rec.enabled or not rec.approved:
                continue
            self.load(name)
            if rec.load_error is not None or rec.module is None:
                orphans.append(name)
            elif not callable(getattr(rec.module, "handle", None)):
                orphans.append(name)
        return orphans

    # -- circuit breaker -------------------------------------------------------
    def reenable(self, name: str) -> None:
        """Manual re-enable only. Resets the failure counter (half-open probe
        runs on the next dispatch with its normal timeout)."""
        rec = self._records[name]
        rec.failures = 0
        rec.disabled_reason = ""
        rec.enabled = True

    def _dispatchable(self, rec: SkillRecord) -> bool:
        return (
            rec.manifest is not None
            and rec.load_error is None
            and rec.approved
            and rec.enabled
            and not rec.circuit_open
        )

    def _trip(self, rec: SkillRecord, code: str) -> None:
        rec.failures += 1
        if rec.failures >= CIRCUIT_BREAKER_THRESHOLD:
            rec.enabled = False
            rec.disabled_reason = (
                f"circuit breaker: {CIRCUIT_BREAKER_THRESHOLD} consecutive "
                f"failures (last: {code})"
            )

    # -- dispatch pipeline -------------------------------------------------------
    def dispatch(
        self,
        tool_name: str,
        args: Any,
        ctx: SkillContext,
        gate: Callable[[str, int, dict, SkillContext], bool],
    ) -> dict:
        """Run one tool call through the full deterministic pipeline.

        ``gate(tool_name, tier, args, ctx)`` -> True to allow, False to deny.
        Returns a result dict; failures are structured, never silent.
        """
        # 1. parse
        if not isinstance(args, dict):
            return _err("args_must_be_object", "parse", "args must be a JSON object")
        # 2. resolve
        try:
            tool = self.get_tool(tool_name)
        except UnknownTool as exc:
            return _err("unknown_tool", "resolve", str(exc))
        rec = self._records[tool["skill"]]
        if not rec.approved or (
            rec.manifest is not None and rec.approved_hash != rec.manifest_hash
        ):
            return _err(
                "skill_quarantined",
                "resolve",
                f"skill {rec.name!r} is in quarantine (not approved)",
            )
        if not rec.enabled:
            reason = rec.disabled_reason or "disabled"
            return _err("skill_disabled", "resolve", f"skill {rec.name!r}: {reason}")
        if rec.circuit_open:
            return _err(
                "circuit_open",
                "resolve",
                f"skill {rec.name!r} circuit open after "
                f"{CIRCUIT_BREAKER_THRESHOLD} failures",
            )
        # 3. schema-validate
        schema_errors = validate_against_schema(args, tool["schema"])
        if schema_errors:
            self._trip(rec, "schema_error")
            return _err(
                "schema_error",
                "schema-validate",
                "; ".join(schema_errors),
            )
        # 4. capability-check (denials never count toward the breaker)
        missing = set(tool["capabilities"]) - set(ctx.capabilities)
        if missing:
            return _err(
                "capability_denied",
                "capability-check",
                f"task grant lacks {sorted(missing)} for tool {tool_name!r}",
            )
        # 5. risk-gate (per-turn pending state; denials never count)
        try:
            allowed = gate(tool_name, tool["tier"], args, ctx)
        except Exception as exc:
            return _err("gate_error", "risk-gate", f"gate raised: {exc}")
        if not allowed:
            self._pending.setdefault(ctx.turn_id, []).append(
                {"tool": tool_name, "tier": tool["tier"]}
            )
            code = "confirmation_required" if tool["tier"] >= 3 else "gate_denied"
            return _err(
                code,
                "risk-gate",
                f"tool {tool_name!r} (tier {tool['tier']}) denied by gate",
            )
        # 6. isolated call (timeout + output cap)
        self.load(tool["skill"])
        if rec.load_error is not None or rec.module is None:
            self._trip(rec, "skill_load_error")
            return _err(
                "skill_load_error", "dispatch", f"cannot load skill: {rec.load_error}"
            )
        handle = getattr(rec.module, "handle", None)
        if not callable(handle):
            self._trip(rec, "missing_handler")
            return _err(
                "missing_handler",
                "dispatch",
                f"skill {rec.name!r} has no callable handle()",
            )
        sctx = ctx.for_skill(rec.name, self._jail_for(rec.name))
        box: dict[str, Any] = {}

        def _run() -> None:
            try:
                box["result"] = handle(tool_name, args, sctx)
            except BaseException as exc:  # never let a skill kill the turn
                box["error"] = exc

        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        worker.join(tool["timeout_s"])
        if worker.is_alive():
            # CPython cannot kill a thread; it is abandoned (daemon) and the
            # failure counts toward the breaker. Documented limitation.
            self._trip(rec, "timeout")
            return _err(
                "timeout",
                "bound",
                f"tool {tool_name!r} exceeded {tool['timeout_s']}s",
            )
        if "error" in box:
            exc = box["error"]
            if isinstance(exc, (CapabilityDenied, PathDenied)):
                # skill violated its own jail/grant — hard error, counts
                self._trip(rec, "skill_violation")
                return _err("skill_violation", "dispatch", str(exc))
            self._trip(rec, "skill_error")
            return _err(
                "skill_error", "dispatch", f"{type(exc).__name__}: {exc}"
            )
        result = box["result"]
        # 7. output-validate
        if not isinstance(result, dict):
            self._trip(rec, "output_error")
            return _err(
                "output_error",
                "output-validate",
                f"tool {tool_name!r} must return a dict, "
                f"got {type(result).__name__}",
            )
        out_errors = validate_against_schema(result, tool["returns"])
        if out_errors:
            self._trip(rec, "output_error")
            return _err(
                "output_error", "output-validate", "; ".join(out_errors)
            )
        # 8. evidence-wrap (truncate over cap, never silently drop)
        content = json.dumps(result, ensure_ascii=False)
        truncated = len(content) > tool["output_cap_chars"]
        if truncated:
            content = (
                content[: tool["output_cap_chars"]]
                + f"\n…[truncated at {tool['output_cap_chars']} chars]"
            )
        evidence = (
            f'<tool_output source="{rec.name}.{tool_name}" '
            f'trust="untrusted" turn="{ctx.turn_id}">\n{content}\n</tool_output>'
        )
        rec.failures = 0  # success resets the breaker
        rec.invoked_tools.add(tool_name)
        return {
            "ok": True,
            "result": result,
            "truncated": truncated,
            "evidence": evidence,
        }


def _err(code: str, stage: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "stage": stage, "message": message}}
