"""Tests for the code skill: jailed read/write/edit, sandboxed run.

Stdlib only; hermetic (tmp_path). code_run spawns a real interpreter
subprocess — one test takes the full 10s sandbox timeout by design.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.skills import SkillContext, SkillRegistry, scan_skill

ALLOW_ALL = lambda tool, tier, args, ctx: True  # noqa: E731

REPO = Path(__file__).resolve().parents[1]


def _registry(tmp_path: Path) -> SkillRegistry:
    src = REPO / "skills" / "code"
    dst = tmp_path / "skills" / "code"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    data = tmp_path / "data"
    data.mkdir()
    reg = SkillRegistry(dst.parent, data)
    reg.discover()
    return reg


def _ctx(**kw) -> SkillContext:
    kw.setdefault("skill_name", "test")
    kw.setdefault("capabilities", ["fs.read", "fs.write", "exec", "time.read"])
    kw.setdefault("jail_dir", ".")
    return SkillContext(**kw)


def _run(reg, tool, args):
    reg.approve("code")
    return reg.dispatch(tool, args, _ctx(), ALLOW_ALL)


# ---------------------------------------------------------------------------
# read / write / edit
# ---------------------------------------------------------------------------


def test_write_read_roundtrip_with_line_numbers(tmp_path):
    reg = _registry(tmp_path)
    out = _run(reg, "code_write", {"path": "hello.py", "content": "print('hi')\nx = 1\n"})
    assert out["ok"] is True
    assert out["result"]["written"] is True
    assert out["result"]["backed_up"] is False  # new file
    out = _run(reg, "code_read", {"path": "hello.py"})
    assert out["ok"] is True
    assert out["result"]["lines"] == 2
    assert out["result"]["content"].splitlines()[0].startswith("1: ")
    assert "print('hi')" in out["result"]["content"]
    # really jailed under <data_dir>/code
    assert (reg.data_dir / "code" / "hello.py").is_file()


def test_write_backs_up_existing(tmp_path):
    reg = _registry(tmp_path)
    _run(reg, "code_write", {"path": "a.py", "content": "v1\n"})
    out = _run(reg, "code_write", {"path": "a.py", "content": "v2\n"})
    assert out["result"]["backed_up"] is True
    out = _run(reg, "code_read", {"path": "a.py.bak"})
    assert out["ok"] is True
    assert "v1" in out["result"]["content"]


def test_edit_surgical_and_backup(tmp_path):
    reg = _registry(tmp_path)
    _run(reg, "code_write", {"path": "m.py", "content": "a = 1\nb = 2\n"})
    out = _run(reg, "code_edit",
               {"path": "m.py", "old_text": "a = 1", "new_text": "a = 10"})
    assert out["ok"] is True
    assert out["result"]["edited"] is True
    out = _run(reg, "code_read", {"path": "m.py"})
    assert "a = 10" in out["result"]["content"]
    assert "b = 2" in out["result"]["content"]
    out = _run(reg, "code_read", {"path": "m.py.bak"})
    assert "a = 1" in out["result"]["content"]


def test_edit_zero_matches_is_error(tmp_path):
    reg = _registry(tmp_path)
    _run(reg, "code_write", {"path": "m.py", "content": "a = 1\n"})
    out = _run(reg, "code_edit",
               {"path": "m.py", "old_text": "zzz", "new_text": "q"})
    assert out["ok"] is False
    assert out["error"]["code"] == "skill_error"
    # file untouched
    out = _run(reg, "code_read", {"path": "m.py"})
    assert "a = 1" in out["result"]["content"]


def test_edit_ambiguous_is_error(tmp_path):
    reg = _registry(tmp_path)
    _run(reg, "code_write", {"path": "m.py", "content": "x = 1\nx = 2\n"})
    out = _run(reg, "code_edit",
               {"path": "m.py", "old_text": "x =", "new_text": "y ="})
    assert out["ok"] is False
    assert out["error"]["code"] == "skill_error"
    out = _run(reg, "code_read", {"path": "m.py"})
    assert "y =" not in out["result"]["content"]


def test_jail_traversal_denied(tmp_path):
    reg = _registry(tmp_path)
    out = _run(reg, "code_write", {"path": "../evil.py", "content": "x"})
    assert out["ok"] is False
    assert out["error"]["code"] == "skill_violation"
    assert not (reg.data_dir / "evil.py").exists()
    out = _run(reg, "code_read", {"path": "/tmp/abs.py"})
    assert out["ok"] is False


# ---------------------------------------------------------------------------
# code_run — the sandbox
# ---------------------------------------------------------------------------


def test_run_hello(tmp_path):
    reg = _registry(tmp_path)
    out = _run(reg, "code_run", {"code": "print('hello sandbox')"})
    assert out["ok"] is True
    r = out["result"]
    assert r["exit_code"] == 0
    assert r["timed_out"] is False
    assert "hello sandbox" in r["stdout"]
    assert r["stderr"] == ""


def test_run_exit_code_propagates(tmp_path):
    reg = _registry(tmp_path)
    out = _run(reg, "code_run", {"code": "import sys; sys.exit(3)"})
    assert out["ok"] is True
    assert out["result"]["exit_code"] == 3
    assert out["result"]["timed_out"] is False


def test_run_stderr_captured(tmp_path):
    reg = _registry(tmp_path)
    out = _run(reg, "code_run", {"code": "raise RuntimeError('boom')"})
    assert out["ok"] is True
    r = out["result"]
    assert r["exit_code"] != 0
    assert "RuntimeError: boom" in r["stderr"]


def test_run_timeout(tmp_path):
    reg = _registry(tmp_path)
    out = _run(reg, "code_run", {"code": "while True:\n    pass"})
    assert out["ok"] is True
    r = out["result"]
    assert r["timed_out"] is True
    assert r["exit_code"] == -1


def test_run_network_blocked(tmp_path):
    reg = _registry(tmp_path)
    out = _run(reg, "code_run",
               {"code": "import socket; socket.create_connection(('example.com', 80), timeout=2)"})
    assert out["ok"] is True
    r = out["result"]
    assert r["exit_code"] != 0
    assert "network disabled in code sandbox" in r["stderr"]


def test_run_from_path(tmp_path):
    reg = _registry(tmp_path)
    _run(reg, "code_write", {"path": "prog.py", "content": "print(40 + 2)\n"})
    out = _run(reg, "code_run", {"path": "prog.py"})
    assert out["ok"] is True
    assert out["result"]["exit_code"] == 0
    assert "42" in out["result"]["stdout"]


def test_run_output_capped(tmp_path):
    reg = _registry(tmp_path)
    out = _run(reg, "code_run", {"code": "print('y' * 20000)"})
    assert out["ok"] is True
    r = out["result"]
    assert len(r["stdout"]) <= 10_100  # 10KB + truncation marker
    assert "truncated at 10KB" in r["stdout"]


def test_run_needs_code_or_path(tmp_path):
    reg = _registry(tmp_path)
    out = _run(reg, "code_run", {})
    assert out["ok"] is False
    out = _run(reg, "code_run", {"code": "x", "path": "y.py"})
    assert out["ok"] is False


def test_run_path_outside_jail_denied(tmp_path):
    reg = _registry(tmp_path)
    out = _run(reg, "code_run", {"path": "../evil.py"})
    assert out["ok"] is False


# ---------------------------------------------------------------------------
# manifest + static scan
# ---------------------------------------------------------------------------


def test_manifest_parses_and_scan_has_no_hard_findings(tmp_path):
    _ = _registry(tmp_path)  # discovery must accept the manifest
    findings = scan_skill(REPO / "skills" / "code")
    hard = [f for f in findings
            if f["rule"] in ("dangerous-call", "capability-mismatch",
                             "syntax-error", "manifest-unreadable")]
    assert hard == [], hard


def test_manifest_declares_exec_capability():
    manifest = json.loads((REPO / "skills" / "code" / "skill.json").read_text())
    assert "exec" in manifest["capabilities"]
    run_tool = next(t for t in manifest["tools"] if t["name"] == "code_run")
    assert run_tool["tier"] == 3
    assert run_tool["timeout_s"] >= 10
