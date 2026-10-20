"""Tests for jarvis.mcp_bridge — real subprocess, fake MCP server.

The fake server below is written to a tmp file and run with
sys.executable, speaking real line-delimited JSON-RPC 2.0 — the client
is tested against the actual wire protocol, not mocks of itself.
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from jarvis.dcl import DataClass
from jarvis.mcp_bridge import (
    McpClient,
    McpError,
    McpRpcError,
    McpServer,
    McpTimeout,
    McpTransportError,
    McpValidationError,
    RegistryAdapter,
    SkillRegistryAdapter,
    build_manifest,
    sanitize_tool_name,
    validate_mcp_tool,
)

FAKE_SERVER = r'''
import json, os, sys, time

MODE = sys.argv[1] if len(sys.argv) > 1 else "normal"
MARKER = sys.argv[2] if len(sys.argv) > 2 else ""

def send(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()

def tool(name, desc, schema=None):
    return {"name": name, "description": desc,
            "inputSchema": schema or {"type": "object"}}

TOOLS = {
    "normal": [
        tool("echo", "Echo text back",
             {"type": "object", "properties": {"text": {"type": "string"}},
              "required": ["text"]}),
        tool("Add_Numbers", "Add two numbers",
             {"type": "object", "properties": {"a": {"type": "number"},
              "b": {"type": "number"}}}),
        tool("fail_soft", "Always returns isError"),
    ],
    "badtools": [
        tool("good_tool", "fine"),
        {"description": "no name at all"},
        {"name": "has space", "description": "bad name chars"},
        {"name": "a-b", "description": "collides with a_b"},
        tool("a_b", "collides with a-b"),
        {"name": "bad_schema", "description": "schema not object",
         "inputSchema": "nope"},
    ],
}

def tools_for_page(params):
    if MODE == "paged":
        cursor = (params or {}).get("cursor")
        if cursor == "page2":
            return {"tools": [tool("second_tool", "page two")]}
        return {"tools": [tool("first_tool", "page one")], "nextCursor": "page2"}
    return {"tools": TOOLS.get(MODE, TOOLS["normal"])}

def handle_call(params):
    name = (params or {}).get("name")
    args = (params or {}).get("arguments") or {}
    if MODE == "crash_always":
        os._exit(3)
    if MODE == "crash_once":
        if not os.path.exists(MARKER):
            open(MARKER, "w").write("x")
            os._exit(3)
    if MODE == "slow":
        time.sleep(5)
    if name == "echo":
        return {"content": [{"type": "text", "text": "echo: " + str(args.get("text", ""))}]}
    if name == "Add_Numbers":
        return {"content": [{"type": "text",
                              "text": str(args.get("a", 0) + args.get("b", 0))}]}
    if name == "fail_soft":
        return {"content": [{"type": "text", "text": "it broke"}], "isError": True}
    if name == "first_tool" or name == "second_tool" or name == "good_tool":
        return {"content": [{"type": "text", "text": "did " + name}]}
    return None  # signals JSON-RPC error

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake", "version": "1.0"}}})
    elif method == "notifications/initialized":
        send({"jsonrpc": "2.0", "method": "notifications/message",
              "params": {"level": "info", "data": "hello from fake"}})
    elif method == "ping":
        send({"jsonrpc": "2.0", "id": mid, "result": {}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": mid, "result": tools_for_page(msg.get("params"))})
    elif method == "tools/call":
        res = handle_call(msg.get("params"))
        if res is None:
            send({"jsonrpc": "2.0", "id": mid,
                  "error": {"code": -32602, "message": "unknown tool"}})
        else:
            send({"jsonrpc": "2.0", "id": mid, "result": res})
    elif mid is not None:
        send({"jsonrpc": "2.0", "id": mid,
              "error": {"code": -32601, "message": "no such method"}})
'''


@pytest.fixture()
def fake_server(tmp_path):
    script = tmp_path / "fake_mcp_server.py"
    script.write_text(textwrap.dedent(FAKE_SERVER), encoding="utf-8")
    return script


def make_client(script: Path, mode: str = "normal", marker: Path | None = None,
                **server_kw) -> McpClient:
    argv = [sys.executable, str(script), mode]
    if marker is not None:
        argv.append(str(marker))
    server = McpServer(name="fake", command=argv, **server_kw)
    return McpClient(server)


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_command_must_be_argv_list_not_shell_string():
    with pytest.raises(TypeError):
        McpServer(name="fake", command="python server.py")  # type: ignore[arg-type]


def test_server_name_must_match_registry_vocabulary():
    with pytest.raises(McpValidationError):
        McpServer(name="Bad Name!", command=["python"])


def test_server_command_must_be_nonempty():
    with pytest.raises(McpValidationError):
        McpServer(name="fake", command=[])


# ---------------------------------------------------------------------------
# Tool-name sanitization / validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("echo", "echo"),
        ("Add_Numbers", "add_numbers"),
        ("get-forecast.now", "get_forecast_now"),
        ("9lives", "t_9lives"),
        ("a--b", "a_b"),
    ],
)
def test_sanitize_tool_name(raw, expected):
    assert sanitize_tool_name(raw) == expected


def test_validate_tool_rejects_non_dict_schema():
    with pytest.raises(McpValidationError):
        validate_mcp_tool({"name": "x", "inputSchema": "nope"})


def test_validate_tool_rejects_bad_name():
    with pytest.raises(McpValidationError):
        validate_mcp_tool({"name": "has space"})


# ---------------------------------------------------------------------------
# Protocol end-to-end (real subprocess)
# ---------------------------------------------------------------------------


def test_handshake_list_and_call(fake_server):
    with make_client(fake_server) as client:
        assert client.state == "ready"
        assert client.server_info.get("name") == "fake"
        assert client.negotiated_protocol == "2024-11-05"
        tools = client.list_tools()
        names = {t.registry_name for t in tools}
        assert names == {"echo", "add_numbers", "fail_soft"}
        res = client.call_tool("echo", {"text": "hello"})
        assert res.ok is True
        assert res.text == "echo: hello"
        # evidence is the gate wrapper, marked untrusted
        assert res.evidence.startswith('<tool_output source="mcp.fake.echo"')
        assert 'trust="untrusted"' in res.evidence
        assert "echo: hello" in res.evidence
        # wire name also works, original MCP casing preserved on the wire
        res2 = client.call_tool("Add_Numbers", {"a": 2, "b": 3})
        assert res2.text == "5"
        assert client.ping() is True


def test_server_notification_is_captured(fake_server):
    with make_client(fake_server) as client:
        client.list_tools()
        methods = [n.get("method") for n in client.notifications]
        assert "notifications/message" in methods


def test_tool_level_error_returns_not_ok(fake_server):
    with make_client(fake_server) as client:
        client.list_tools()
        res = client.call_tool("fail_soft", {})
        assert res.ok is False
        assert res.text == "it broke"


def test_unknown_tool_raises_rpc_error(fake_server):
    with make_client(fake_server) as client:
        client.list_tools()
        with pytest.raises(McpRpcError) as excinfo:
            client.call_tool("nope", {})
        assert excinfo.value.code == -32602


def test_paginated_tools_list(fake_server):
    with make_client(fake_server, mode="paged") as client:
        tools = client.list_tools()
        assert {t.registry_name for t in tools} == {"first_tool", "second_tool"}


def test_bad_tools_rejected_and_recorded(fake_server):
    with make_client(fake_server, mode="badtools") as client:
        tools = client.list_tools()
        assert [t.registry_name for t in tools] == ["good_tool", "a_b"]
        reasons = " | ".join(r["reason"] for r in client.rejected_tools)
        assert len(client.rejected_tools) == 4
        assert "collides" in reasons
        assert "inputSchema" in reasons


def test_call_timeout(fake_server):
    with make_client(fake_server, mode="slow", timeout_s=10) as client:
        client.list_tools()
        with pytest.raises(McpTimeout):
            client.call_tool("echo", {"text": "hi"}, timeout=0.5)


def test_crash_restarts_once_then_recovers(fake_server, tmp_path):
    marker = tmp_path / "crashed.once"
    with make_client(fake_server, mode="crash_once", marker=marker) as client:
        client.list_tools()
        res = client.call_tool("echo", {"text": "back"})
        assert res.ok is True
        assert res.text == "echo: back"
        assert client.restart_count == 1


def test_crash_always_fails_after_single_restart(fake_server):
    with make_client(fake_server, mode="crash_always") as client:
        client.list_tools()
        with pytest.raises(McpTransportError):
            client.call_tool("echo", {"text": "hi"})
        assert client.restart_count == 1


def test_missing_executable_raises_transport_error(tmp_path):
    server = McpServer(name="fake", command=["/nonexistent/mcp-binary-xyz"])
    client = McpClient(server)
    with pytest.raises(McpTransportError):
        client.start()


# ---------------------------------------------------------------------------
# DCL classification
# ---------------------------------------------------------------------------


def test_entries_default_personal_and_reclassify(fake_server):
    with make_client(fake_server) as client:
        client.list_tools()
        entry = client.entries["echo"]
        assert entry.data_class is DataClass.PERSONAL
        res = client.call_tool("echo", {"text": "x"})
        assert res.data_class is DataClass.PERSONAL
        entry.reclassify(DataClass.SENSITIVE)
        res2 = client.call_tool("echo", {"text": "x"})
        assert res2.data_class is DataClass.SENSITIVE


# ---------------------------------------------------------------------------
# Registration into a registry
# ---------------------------------------------------------------------------


class FakeRegistry:
    """Minimal RegistryAdapter: records manifests, serves handlers."""

    def __init__(self, existing: set[str] | None = None) -> None:
        self.existing = set(existing or ())
        self.manifests: dict[str, dict] = {}
        self.handlers: dict[str, object] = {}
        self.approved: list[str] = []

    def tool_exists(self, name: str) -> bool:
        if name in self.existing:
            return True
        return any(
            t["name"] == name
            for m in self.manifests.values()
            for t in m["tools"]
        )

    def register_skill(self, manifest, handler):
        self.manifests[manifest["name"]] = manifest
        self.handlers[manifest["name"]] = handler
        return {"skill": manifest["name"], "quarantined": True}


def test_fake_registry_satisfies_protocol():
    assert isinstance(FakeRegistry(), RegistryAdapter)


def test_register_into_fake_registry_quarantined_handler_works(fake_server):
    with make_client(fake_server) as client:
        client.list_tools()
        fake = FakeRegistry()
        record = client.register_into(fake)
        assert record == {"skill": "fake", "quarantined": True}
        # bridge never approves anything itself
        assert fake.approved == []
        manifest = fake.manifests["fake"]
        assert manifest["name"] == "fake"
        tool_names = {t["name"] for t in manifest["tools"]}
        assert tool_names == {"echo", "add_numbers", "fail_soft"}
        assert all(t["tier"] == 2 for t in manifest["tools"])
        # the handler routes through the live client
        out = fake.handlers["fake"]("echo", {"text": "via registry"}, None)
        assert out["ok"] is True
        assert out["text"] == "echo: via registry"
        assert out["data_class"] == "PERSONAL"
        assert '<tool_output source="mcp.fake.echo"' in out["evidence"]


def test_register_refuses_to_shadow_existing_tool(fake_server):
    with make_client(fake_server) as client:
        client.list_tools()
        fake = FakeRegistry(existing={"echo"})
        with pytest.raises(McpValidationError):
            client.register_into(fake)
        assert fake.manifests == {}


def test_manifest_is_strict_registry_valid(fake_server):
    tools = [validate_mcp_tool(t) for t in [
        {"name": "echo", "description": "d",
         "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
    ]]
    server = McpServer(name="fake", command=["python"])
    manifest = build_manifest(server, tools)
    # the real registry validator must accept the bridge's manifest
    from jarvis.skills.registry import SkillManifest

    parsed = SkillManifest.from_dict(manifest, source="test")
    assert parsed.name == "fake"
    assert parsed.tools[0].name == "echo"
    assert parsed.tools[0].tier == 2
    assert parsed.capabilities == ()


def test_real_registry_quarantine_then_approve_then_dispatch(fake_server, tmp_path):
    from jarvis.skills.registry import SkillContext, SkillRegistry

    registry = SkillRegistry(skills_dir=tmp_path / "skills",
                             data_dir=tmp_path / "data")
    (tmp_path / "skills").mkdir()
    adapter = SkillRegistryAdapter(registry)
    assert isinstance(adapter, RegistryAdapter)
    with make_client(fake_server) as client:
        client.list_tools()
        client.register_into(adapter)
        # quarantined: visible in quarantine(), invisible to the brain
        assert "fake" in registry.quarantine()
        assert registry.tools_for_task([]) == []
        # dispatch while quarantined is refused by the pipeline
        ctx = SkillContext(skill_name="fake", capabilities=(), turn_id=1)
        refused = registry.dispatch(
            "echo", {"text": "hi"}, ctx, gate=lambda *a: True)
        assert refused["ok"] is False
        assert refused["error"]["code"] == "skill_quarantined"
        # owner approves -> dispatch flows through the real gate pipeline
        registry.approve("fake")
        assert registry.quarantine() == []
        allowed = registry.dispatch(
            "echo", {"text": "approved"}, ctx, gate=lambda *a: True)
        assert allowed["ok"] is True
        assert allowed["result"]["text"] == "echo: approved"
        assert 'trust="untrusted"' in allowed["evidence"]
        # and the gate can still deny per-call
        denied = registry.dispatch(
            "echo", {"text": "hi"}, ctx, gate=lambda *a: False)
        assert denied["ok"] is False
        assert denied["error"]["code"] == "gate_denied"


def test_register_into_requires_start(fake_server):
    client = make_client(fake_server)
    with pytest.raises(McpError):
        client.register_into(FakeRegistry())
