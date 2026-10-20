"""MCP bridge — external MCP servers join JARVIS under v2's safety rules.

Implements a minimal, stdlib-only MCP *client* (JSON-RPC 2.0 over stdio)
so tools from external Model Context Protocol servers can be registered
into the skill registry as a quarantined skill. The bridge never
auto-approves: ``registry.approve()`` remains the owner's act, exactly
like a hand-written skill dropped into the skills directory.

Protocol coverage (stdio transport):
    initialize handshake (+ notifications/initialized), tools/list
    (with cursor pagination), tools/call, ping (both directions).
    Streamable-HTTP transport is NOT implemented — see "Honest limits".

Safety posture (why this module exists at all):
  * Server commands are argv lists, NEVER shell strings. A ``str``
    command is a type error, not a convenience.
  * Discovered tools are schema-validated before registration; invalid
    tools are rejected and recorded, never silently mangled in.
  * MCP tool names (``[A-Za-z0-9._-]``) are sanitized to the registry's
    ``^[a-z][a-z0-9_]*$`` vocabulary; the original wire name is kept for
    ``tools/call``.
  * Every entry defaults to DCL PERSONAL until the owner reclassifies.
  * Call results are returned in the gate's evidence format
    (``Gate.wrap_output``) — tool output is DATA, never instructions.
  * Hard caps everywhere: message size, tool count, description length,
    stderr tail, per-request timeouts. A crashed server is restarted
    exactly once; after that the failure is the caller's problem.

Ambient-authority warning: an MCP stdio server is a local process the
owner chose to run. The bridge governs the *tools* (quarantine, gate,
evidence), not the process itself — same trust level as any program the
owner installs. Do not register servers you would not run directly.

Stdlib only. Python 3.11+.
"""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from jarvis.dcl import DataClass
from jarvis.gate import Gate

__all__ = [
    "McpError",
    "McpTimeout",
    "McpTransportError",
    "McpProtocolError",
    "McpValidationError",
    "McpRpcError",
    "McpServer",
    "McpTool",
    "McpToolEntry",
    "McpCallResult",
    "McpClient",
    "RegistryAdapter",
    "SkillRegistryAdapter",
    "sanitize_tool_name",
    "validate_mcp_tool",
    "build_manifest",
    "PROTOCOL_VERSION",
]

PROTOCOL_VERSION = "2024-11-05"
CLIENT_NAME = "jarvis-v2"
CLIENT_VERSION = "0.1.0"
BRIDGE_SKILL_VERSION = "0.1.0"

# MCP tool tier inside the registry: unknown side effects => confirmation
# tier (2). Never tier 1: the bridge cannot prove a tool is read-only.
MCP_TOOL_TIER = 2

MAX_MESSAGE_BYTES = 1 * 1024 * 1024  # one JSON-RPC line, hard cap
MAX_TOOLS = 256                      # per server, across all pages
MAX_LIST_PAGES = 10
MAX_DESCRIPTION_CHARS = 2000
MAX_TOOLS_PER_PAGE_ITEMS = 1024
STDERR_TAIL_LINES = 50
STOP_WAIT_S = 2.0

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")          # registry vocabulary
_MCP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")  # MCP spec


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class McpError(Exception):
    """Base class for MCP bridge errors."""


class McpTimeout(McpError):
    """A request exceeded its timeout."""


class McpTransportError(McpError):
    """The stdio transport broke (EOF, broken pipe, oversized message)."""


class McpProtocolError(McpError):
    """The peer sent something that is not valid MCP/JSON-RPC."""


class McpValidationError(McpError):
    """A server or tool description failed validation."""


class McpRpcError(McpError):
    """The server returned a JSON-RPC error object."""

    def __init__(self, code: Any, message: str, data: Any = None) -> None:
        super().__init__(f"JSON-RPC error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class McpServer:
    """One external MCP server, launched as a child process.

    ``command`` is an argv LIST (program + args). Shell strings are
    rejected: there is no shell anywhere in this bridge.
    """

    name: str
    command: tuple[str, ...]
    timeout_s: float = 30.0
    env: dict[str, str] | None = None
    cwd: str | None = None
    protocol_version: str = PROTOCOL_VERSION

    def __init__(
        self,
        name: str,
        command: list[str] | tuple[str, ...],
        *,
        timeout_s: float = 30.0,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        protocol_version: str = PROTOCOL_VERSION,
    ) -> None:
        if isinstance(command, str):
            raise TypeError(
                "McpServer.command must be an argv list, never a shell string"
            )
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise McpValidationError(
                f"server name must match ^[a-z][a-z0-9_]*$ (it becomes the "
                f"registry skill name), got {name!r}"
            )
        argv = tuple(command)
        if not argv or not all(isinstance(a, str) and a for a in argv):
            raise McpValidationError(
                "McpServer.command must be a non-empty list of non-empty strings"
            )
        if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
            raise McpValidationError(f"timeout_s must be positive, got {timeout_s!r}")
        if env is not None and not (
            isinstance(env, dict)
            and all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())
        ):
            raise McpValidationError("env must be a dict of str -> str")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "command", argv)
        object.__setattr__(self, "timeout_s", float(timeout_s))
        object.__setattr__(self, "env", dict(env) if env is not None else None)
        object.__setattr__(self, "cwd", cwd)
        object.__setattr__(self, "protocol_version", protocol_version)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def sanitize_tool_name(name: str) -> str:
    """Map an MCP tool name to the registry vocabulary ^[a-z][a-z0-9_]*$."""
    s = re.sub(r"[^a-z0-9_]", "_", name.lower())
    s = re.sub(r"_+", "_", s)
    if not s or not s[0].isalpha():
        s = "t_" + s
    return s[:64]


def validate_mcp_tool(raw: Any) -> "McpTool":
    """Validate one tools/list entry. Raises McpValidationError."""
    if not isinstance(raw, dict):
        raise McpValidationError(f"tool entry must be an object, got {type(raw).__name__}")
    name = raw.get("name")
    if not isinstance(name, str) or not _MCP_NAME_RE.match(name):
        raise McpValidationError(
            f"tool name must match MCP [A-Za-z0-9._-] (1-128 chars), got {name!r}"
        )
    description = raw.get("description", "")
    if not isinstance(description, str):
        raise McpValidationError(f"tool {name!r}: 'description' must be a string")
    if len(description) > MAX_DESCRIPTION_CHARS:
        description = description[:MAX_DESCRIPTION_CHARS] + "…[truncated]"
    schema = raw.get("inputSchema", {"type": "object"})
    if not isinstance(schema, dict):
        raise McpValidationError(
            f"tool {name!r}: 'inputSchema' must be a JSON object, "
            f"got {type(schema).__name__}"
        )
    return McpTool(
        name=name,
        registry_name=sanitize_tool_name(name),
        description=description,
        input_schema=schema,
    )


@dataclass(frozen=True)
class McpTool:
    """A validated MCP tool. ``name`` is the wire name (used in calls);
    ``registry_name`` is the sanitized registry-vocabulary name."""

    name: str
    registry_name: str
    description: str
    input_schema: dict


@dataclass
class McpToolEntry:
    """One registered tool + its DCL classification.

    Defaults to PERSONAL: an external tool's output is about the user's
    world until the owner decides otherwise. ``reclassify`` is the
    owner's lever (mirrors dcl.DataClass semantics).
    """

    server: str
    tool: McpTool
    data_class: DataClass = DataClass.PERSONAL

    @property
    def registry_name(self) -> str:
        return self.tool.registry_name

    def reclassify(self, data_class: DataClass) -> None:
        if not isinstance(data_class, DataClass):
            raise McpValidationError(f"data_class must be a DataClass, got {data_class!r}")
        self.data_class = data_class


@dataclass
class McpCallResult:
    """Result of one tools/call.

    ``evidence`` is the gate-wrapped form (Gate.wrap_output) — the only
    form that should enter an LLM context. ``text`` is the raw flattened
    text; ``content`` is the server's raw content list.
    """

    ok: bool
    text: str
    evidence: str
    content: list
    structured: Any = None
    data_class: DataClass = DataClass.PERSONAL


# ---------------------------------------------------------------------------
# Registry adapter protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class RegistryAdapter(Protocol):
    """The narrow surface the bridge needs from a skill registry.

    ``register_skill`` receives the strict manifest dict and the skill's
    ``handle(tool_name, args, ctx) -> dict`` callable, and returns an
    opaque record. Registration must leave the skill QUARANTINED —
    approval is a separate, owner-only act the bridge never performs.
    """

    def tool_exists(self, name: str) -> bool: ...

    def register_skill(
        self, manifest: dict, handler: Callable[[str, dict, Any], dict]
    ) -> Any: ...


class SkillRegistryAdapter:
    """Concrete adapter for jarvis.skills.registry.SkillRegistry.

    The real registry loads skill modules from ``skill.py`` files, but
    ``SkillRegistry.load()`` returns early when ``record.module`` is
    already set — so the adapter pre-seeds the record with a module-like
    object exposing the bridge handler. Dispatch (schema-validate ->
    capability-check -> risk-gate -> evidence-wrap) then works unchanged,
    and the skill sits in quarantine until ``registry.approve(name)``.
    """

    def __init__(self, registry: Any) -> None:
        self._registry = registry

    def tool_exists(self, name: str) -> bool:
        from jarvis.skills.registry import UnknownTool

        try:
            self._registry.get_tool(name)
        except UnknownTool:
            return False
        return True

    def register_skill(
        self, manifest: dict, handler: Callable[[str, dict, Any], dict]
    ) -> Any:
        source = Path(f"<mcp:{manifest['name']}>")
        record = self._registry.register(manifest, source)
        record.module = _HandlerModule(handler)
        return record


class _HandlerModule:
    """Module-shaped shim: registry dispatch only needs ``.handle``."""

    def __init__(self, handle: Callable[[str, dict, Any], dict]) -> None:
        self.handle = handle


def build_manifest(server: McpServer, tools: list[McpTool]) -> dict:
    """Strict registry manifest for one MCP server's validated tools."""
    return {
        "name": server.name,
        "version": BRIDGE_SKILL_VERSION,
        "description": (
            f"External MCP server {server.name!r} via stdio bridge. "
            "Tools are quarantined until the owner approves this skill."
        ),
        "capabilities": [],
        "tools": [
            {
                "name": t.registry_name,
                "description": t.description,
                "parameters": t.input_schema,
                "returns": {},  # free-form: dispatch output-validates vs {}
                "tier": MCP_TOOL_TIER,
                "timeout_s": max(1, min(120, int(server.timeout_s))),
                "capabilities": [],
            }
            for t in tools
        ],
    }


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class _Pending:
    __slots__ = ("event", "response", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.response: dict | None = None
        self.error: BaseException | None = None


class McpClient:
    """JSON-RPC 2.0 client for one stdio MCP server.

    Lifecycle: ``start()`` (spawn + initialize) -> ``list_tools()`` /
    ``call_tool()`` -> ``stop()``. A dead transport is restarted exactly
    once per ``start()`` cycle (``restart_count`` tracks it); ``stop()``
    re-arms the single restart.
    """

    def __init__(self, server: McpServer) -> None:
        self.server = server
        self.state: str = "stopped"  # stopped|starting|ready|dead
        self.server_info: dict = {}
        self.negotiated_protocol: str | None = None
        self.notifications: list[dict] = []
        self.rejected_tools: list[dict] = []
        self.entries: dict[str, McpToolEntry] = {}
        self.restart_count = 0
        self._tools: list[McpTool] = []
        self._proc: subprocess.Popen | None = None
        self._pending: dict[int, _Pending] = {}
        self._next_id = 0
        self._id_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._dead = threading.Event()
        self._dead.set()
        self._restart_used = False
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._stderr_tail: list[str] = []

    # -- lifecycle -----------------------------------------------------

    def start(self) -> None:
        with self._lifecycle_lock:
            if self.state == "ready":
                return
            self._spawn_and_initialize()

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._teardown()
            self.state = "stopped"
            self._restart_used = False

    def __enter__(self) -> "McpClient":
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    @property
    def stderr_tail(self) -> list[str]:
        return list(self._stderr_tail)

    def _spawn_and_initialize(self) -> None:
        self._teardown()
        self.state = "starting"
        env = None
        if self.server.env is not None:
            env = {**os.environ, **self.server.env}
        try:
            self._proc = subprocess.Popen(
                list(self.server.command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.server.cwd,
                env=env,
            )
        except OSError as exc:
            self.state = "stopped"
            raise McpTransportError(
                f"cannot launch MCP server {self.server.name!r} "
                f"({self.server.command[0]!r}): {exc}"
            ) from exc
        self._dead = threading.Event()
        self._reader = threading.Thread(
            target=self._read_loop, name=f"mcp-reader-{self.server.name}", daemon=True
        )
        self._reader.start()
        self._stderr_reader = threading.Thread(
            target=self._drain_stderr, name=f"mcp-stderr-{self.server.name}", daemon=True
        )
        self._stderr_reader.start()
        try:
            result = self._request(
                "initialize",
                {
                    "protocolVersion": self.server.protocol_version,
                    "capabilities": {},
                    "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
                },
                timeout=self.server.timeout_s,
                _allow_restart=False,
            )
        except BaseException:
            self._teardown()
            self.state = "stopped"
            raise
        if not isinstance(result, dict):
            self._teardown()
            self.state = "stopped"
            raise McpProtocolError(
                f"initialize result must be an object, got {type(result).__name__}"
            )
        self.server_info = result.get("serverInfo") or {}
        self.negotiated_protocol = result.get("protocolVersion")
        self._notify("notifications/initialized", {})
        self.state = "ready"

    def _teardown(self) -> None:
        proc, self._proc = self._proc, None
        self._dead.set()
        self._fail_all_pending(
            McpTransportError(f"MCP server {self.server.name!r} stopped")
        )
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        try:
            proc.wait(timeout=STOP_WAIT_S)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=STOP_WAIT_S)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=STOP_WAIT_S)
                except subprocess.TimeoutExpired:
                    pass

    def _restart_once(self) -> None:
        if self._restart_used:
            raise McpTransportError(
                f"MCP server {self.server.name!r} died and the single "
                "automatic restart was already used"
            )
        self._restart_used = True
        self.restart_count += 1
        self._spawn_and_initialize()

    # -- transport -------------------------------------------------------

    def _read_loop(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        try:
            while True:
                line = proc.stdout.readline(MAX_MESSAGE_BYTES + 1)
                if not line:
                    break  # EOF: server exited
                if len(line) > MAX_MESSAGE_BYTES:
                    self._fail_all_pending(
                        McpTransportError(
                            f"message from {self.server.name!r} exceeded "
                            f"{MAX_MESSAGE_BYTES} bytes"
                        )
                    )
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    continue  # not JSON-RPC; ignore the noise line
                if isinstance(msg, dict):
                    self._route_message(msg)
        finally:
            self._dead.set()
            if self.state == "ready":
                self.state = "dead"
            self._fail_all_pending(
                McpTransportError(
                    f"MCP server {self.server.name!r} closed the connection"
                )
            )

    def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                self._stderr_tail.append(line)
                del self._stderr_tail[:-STDERR_TAIL_LINES]
        except (ValueError, OSError):
            pass

    def _route_message(self, msg: dict) -> None:
        is_response = "id" in msg and ("result" in msg or "error" in msg)
        if is_response:
            pend = self._pending.pop(msg.get("id"), None)  # type: ignore[arg-type]
            if pend is not None:
                pend.response = msg
                pend.event.set()
            return
        if "method" in msg and "id" in msg:
            # server -> client request
            if msg["method"] == "ping":
                self._send_raw({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
            else:
                self._send_raw(
                    {
                        "jsonrpc": "2.0",
                        "id": msg["id"],
                        "error": {"code": -32601, "message": "method not supported"},
                    }
                )
            return
        if "method" in msg:
            self.notifications.append(msg)
            del self.notifications[:-100]

    def _send_raw(self, msg: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or self._dead.is_set():
            raise McpTransportError(
                f"MCP server {self.server.name!r} is not connected"
            )
        payload = (json.dumps(msg) + "\n").encode("utf-8")
        if len(payload) > MAX_MESSAGE_BYTES:
            raise McpTransportError("outgoing message exceeds size cap")
        with self._send_lock:
            try:
                proc.stdin.write(payload)
                proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                raise McpTransportError(
                    f"write to MCP server {self.server.name!r} failed: {exc}"
                ) from exc

    def _fail_all_pending(self, error: BaseException) -> None:
        pending, self._pending = self._pending, {}
        for pend in pending.values():
            if not pend.event.is_set():
                pend.error = error
                pend.event.set()

    # -- requests --------------------------------------------------------

    def _request(
        self,
        method: str,
        params: dict | None,
        *,
        timeout: float | None = None,
        _allow_restart: bool = True,
    ) -> Any:
        timeout = self.server.timeout_s if timeout is None else timeout
        try:
            return self._request_once(method, params, timeout)
        except McpTransportError:
            if not _allow_restart:
                raise
            with self._lifecycle_lock:
                self._restart_once()
            return self._request_once(method, params, timeout)

    def _request_once(self, method: str, params: dict | None, timeout: float) -> Any:
        with self._id_lock:
            self._next_id += 1
            req_id = self._next_id
        pend = _Pending()
        self._pending[req_id] = pend
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        try:
            self._send_raw(msg)
        except BaseException:
            self._pending.pop(req_id, None)
            raise
        if not pend.event.wait(timeout):
            self._pending.pop(req_id, None)
            raise McpTimeout(
                f"{method} to MCP server {self.server.name!r} timed out "
                f"after {timeout}s"
            )
        if pend.error is not None:
            raise pend.error
        resp = pend.response or {}
        if "error" in resp:
            err = resp["error"] or {}
            raise McpRpcError(err.get("code"), str(err.get("message", "")), err.get("data"))
        if "result" not in resp:
            raise McpProtocolError(
                f"response to {method} has neither 'result' nor 'error'"
            )
        return resp["result"]

    def _notify(self, method: str, params: dict | None) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._send_raw(msg)

    def ping(self, *, timeout: float | None = None) -> bool:
        self._request("ping", {}, timeout=timeout)
        return True

    # -- tools -----------------------------------------------------------

    def list_tools(self, *, timeout: float | None = None) -> list[McpTool]:
        """Fetch + validate all tools (pagination-aware).

        Invalid tools are skipped and recorded in ``rejected_tools``
        with reasons; duplicates after sanitization are rejected too
        (the registry forbids shadowing).
        """
        tools: list[McpTool] = []
        seen: dict[str, str] = {}
        self.rejected_tools = []
        cursor: str | None = None
        for _page in range(MAX_LIST_PAGES):
            params: dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            result = self._request("tools/list", params, timeout=timeout)
            if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
                raise McpProtocolError("tools/list result must be an object with a 'tools' list")
            raw_tools = result["tools"]
            if len(raw_tools) > MAX_TOOLS_PER_PAGE_ITEMS:
                raise McpProtocolError("tools/list page exceeds item cap")
            for raw in raw_tools:
                try:
                    tool = validate_mcp_tool(raw)
                except McpValidationError as exc:
                    self.rejected_tools.append(
                        {"tool": raw.get("name") if isinstance(raw, dict) else raw,
                         "reason": str(exc)}
                    )
                    continue
                if tool.registry_name in seen:
                    self.rejected_tools.append(
                        {"tool": tool.name,
                         "reason": f"registry name {tool.registry_name!r} collides "
                                   f"with {seen[tool.registry_name]!r} after sanitization"}
                    )
                    continue
                seen[tool.registry_name] = tool.name
                tools.append(tool)
                if len(tools) >= MAX_TOOLS:
                    break
            cursor = result.get("nextCursor")
            if not cursor or len(tools) >= MAX_TOOLS:
                break
        self._tools = tools
        self.entries = {
            t.registry_name: McpToolEntry(server=self.server.name, tool=t) for t in tools
        }
        return list(tools)

    def call_tool(
        self,
        name: str,
        arguments: dict | None = None,
        *,
        timeout: float | None = None,
    ) -> McpCallResult:
        """Call one tool by registry name (or wire name) and return the
        result with gate evidence. Tool-level failures (isError) come
        back as ``ok=False`` results; protocol failures raise."""
        wire_name = name
        entry = self.entries.get(name)
        if entry is not None:
            wire_name = entry.tool.name
        else:
            for t in self._tools:
                if t.name == name:
                    wire_name = t.name
                    break
        result = self._request(
            "tools/call",
            {"name": wire_name, "arguments": dict(arguments or {})},
            timeout=timeout,
        )
        if not isinstance(result, dict):
            raise McpProtocolError("tools/call result must be an object")
        content = result.get("content")
        if not isinstance(content, list):
            content = []
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                parts.append(str(item))
            elif item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif item.get("type") in ("image", "audio"):
                parts.append(f"[{item.get('type')} content omitted from text]")
            elif item.get("type") == "resource":
                parts.append("[resource content omitted from text]")
            else:
                parts.append(f"[{item.get('type', 'unknown')} content omitted from text]")
        text = "\n".join(parts)
        source = f"mcp.{self.server.name}.{wire_name}"
        evidence = Gate.wrap_output(text, source=source, trust="untrusted")
        data_class = entry.data_class if entry is not None else DataClass.PERSONAL
        return McpCallResult(
            ok=not bool(result.get("isError", False)),
            text=text,
            evidence=evidence,
            content=content,
            structured=result.get("structuredContent"),
            data_class=data_class,
        )

    # -- registration ------------------------------------------------------

    def register_into(self, adapter: RegistryAdapter) -> Any:
        """Register this server's validated tools as ONE quarantined skill.

        Requires ``list_tools()`` first. Raises McpValidationError if a
        tool name already exists in the registry (no shadowing). The
        bridge NEVER approves the skill — that is the owner's act.
        """
        if self.state != "ready":
            raise McpError("client is not started; call start() first")
        if not self._tools and not self.entries:
            self.list_tools()
        tools = list(self._tools)
        for t in tools:
            if adapter.tool_exists(t.registry_name):
                raise McpValidationError(
                    f"tool {t.registry_name!r} already exists in the registry; "
                    "refusing to shadow it"
                )
        manifest = build_manifest(self.server, tools)
        client = self

        def handle(tool_name: str, args: dict, ctx: Any) -> dict:
            res = client.call_tool(tool_name, args)
            return {
                "ok": res.ok,
                "text": res.text,
                "is_error": not res.ok,
                "data_class": res.data_class.name,
                "evidence": res.evidence,
            }

        return adapter.register_skill(manifest, handle)
