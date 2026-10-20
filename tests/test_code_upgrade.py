"""Tests for the code skill upgrade (Team 28 steals):

P1 sandbox hardening (env allowlist, audit hook, process-tree kill,
   combined output cap)
P2 code_verify differential verdicts + the SWE-agent lint gate
P3 match ladder + freshness gate for code_edit
P4 code_map (AST def/ref graph + PageRank, sqlite cache)

Stdlib only; hermetic (tmp_path). A few tests spawn real subprocesses
by design (sandbox timeouts, tree kill, pytest runs in the jail).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.skills import SkillContext, SkillRegistry

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


def _jail(reg) -> Path:
    return reg.data_dir / "code"


def _module():
    spec = importlib.util.spec_from_file_location(
        "code_skill_direct", REPO / "skills" / "code" / "skill.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# P1 — env allowlist: parent secrets cannot leak into the child
# ---------------------------------------------------------------------------


def test_sandbox_env_allowlist_blocks_parent_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SKILL_SECRET", "hunter2-do-not-leak")
    monkeypatch.setenv("FAKE_API_TOKEN", "tok-12345")
    reg = _registry(tmp_path)
    out = _run(reg, "code_run", {
        "code": "import os, json; print(json.dumps(sorted(os.environ)))"
                "\nprint(os.environ.get('FAKE_SKILL_SECRET'))"
    })
    assert out["ok"] is True
    r = out["result"]
    assert r["exit_code"] == 0
    assert "hunter2-do-not-leak" not in r["stdout"]
    assert "tok-12345" not in r["stdout"]
    assert "FAKE_SKILL_SECRET" not in r["stdout"]
    assert "FAKE_API_TOKEN" not in r["stdout"]
    assert "None" in r["stdout"]  # the .get() printed None
    assert '"PATH"' in r["stdout"]  # allowlisted vars DO pass through


def test_sandbox_temp_pinned_into_jail(tmp_path):
    reg = _registry(tmp_path)
    out = _run(reg, "code_run",
               {"code": "import os; print(os.environ['TMPDIR'])"})
    assert out["ok"] is True
    tmp = out["result"]["stdout"].strip()
    assert tmp.endswith(".tmp")
    assert str(_jail(reg)) in tmp


# ---------------------------------------------------------------------------
# P1 — audit hook: open() outside the jail, and spawns, are refused
# ---------------------------------------------------------------------------


def test_audit_hook_blocks_open_outside_jail(tmp_path):
    reg = _registry(tmp_path)
    out = _run(reg, "code_run",
               {"code": "print(open('/etc/hostname').read())"})
    assert out["ok"] is True
    r = out["result"]
    assert r["exit_code"] != 0
    assert "outside the code sandbox jail" in r["stderr"]


def test_audit_hook_allows_open_inside_jail(tmp_path):
    reg = _registry(tmp_path)
    _run(reg, "code_write", {"path": "note.txt", "content": "jailed words"})
    out = _run(reg, "code_run",
               {"code": "print(open('note.txt').read())"})
    assert out["ok"] is True
    assert "jailed words" in out["result"]["stdout"]


def test_audit_hook_blocks_subprocess_spawn(tmp_path):
    reg = _registry(tmp_path)
    out = _run(reg, "code_run",
               {"code": "import subprocess; subprocess.run(['echo', 'hi'])"})
    assert out["ok"] is True
    r = out["result"]
    assert r["exit_code"] != 0
    assert "process spawn disabled" in r["stderr"]


def test_os_system_neutered_in_sandbox(tmp_path):
    reg = _registry(tmp_path)
    out = _run(reg, "code_run", {"code": "import os; os.system('echo hi')"})
    assert out["ok"] is True
    r = out["result"]
    assert r["exit_code"] != 0
    assert "process spawn disabled" in r["stderr"]


def test_run_never_serves_stale_bytecode(tmp_path):
    # Regression: timestamp .pyc validation has 1-second granularity, so
    # a same-size edit inside the same second used to run the OLD code.
    reg = _registry(tmp_path)
    _run(reg, "code_write",
         {"path": "calc.py", "content": "def add(a, b):\n    return a - b\n"})
    out = _run(reg, "code_run",
               {"code": "from calc import add; print(add(5, 3))"})
    assert "2" in out["result"]["stdout"]  # buggy version ran, pyc seeded
    target = _jail(reg) / "calc.py"
    original = target.stat()
    target.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    assert target.stat().st_size == original.st_size  # same size, on purpose
    os.utime(target, (original.st_atime, original.st_mtime))  # same second
    out = _run(reg, "code_run",
               {"code": "from calc import add; print(add(5, 3))"})
    assert "8" in out["result"]["stdout"]  # fresh code, not the stale pyc


def test_sandbox_can_import_sibling_jail_module(tmp_path):
    reg = _registry(tmp_path)
    _run(reg, "code_write",
         {"path": "calc.py", "content": "def add(a, b):\n    return a + b\n"})
    out = _run(reg, "code_run",
               {"code": "from calc import add; print(add(20, 22))"})
    assert out["ok"] is True
    assert "42" in out["result"]["stdout"]


# ---------------------------------------------------------------------------
# P1 — process-tree kill on timeout (exercised via the shared runner)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="POSIX killpg path")
def test_process_tree_killed_on_timeout(tmp_path):
    mod = _module()
    marker = tmp_path / "grandchild_survived.txt"
    spawner = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', "
        f"\"import time; time.sleep(3); "
        f"open({str(marker)!r}, 'w').write('x')\"])\n"
        "time.sleep(60)\n"
    )
    raw = mod._exec_argv([sys.executable, "-c", spawner],
                         cwd=str(tmp_path), env=dict(os.environ),
                         timeout_s=1.5)
    assert raw["timed_out"] is True
    time.sleep(3.5)  # the grandchild would fire at ~3s if it had survived
    assert not marker.exists()


def test_combined_output_cap_is_really_10kb(tmp_path):
    reg = _registry(tmp_path)
    code = ("import sys; sys.stdout.write('a' * 8000); "
            "sys.stderr.write('b' * 8000)")
    out = _run(reg, "code_run", {"code": code})
    assert out["ok"] is True
    r = out["result"]
    assert len(r["stdout"]) == 8000            # stdout fits, kept whole
    assert len(r["stdout"]) + len(r["stderr"]) <= 10_100
    assert "truncated at 10KB" in r["stderr"]  # stderr got the remainder


# ---------------------------------------------------------------------------
# P2 — lint gate: syntax-breaking writes/edits auto-revert
# ---------------------------------------------------------------------------


def test_lint_gate_reverts_new_broken_file(tmp_path):
    reg = _registry(tmp_path)
    out = _run(reg, "code_write",
               {"path": "bad.py", "content": "def broken(:\n    pass\n"})
    assert out["ok"] is True
    r = out["result"]
    assert r["written"] is False
    assert r["reverted"] is True
    assert "syntax_error" in r
    assert not (_jail(reg) / "bad.py").exists()  # back to nonexistence


def test_lint_gate_restores_previous_good_content(tmp_path):
    reg = _registry(tmp_path)
    _run(reg, "code_write", {"path": "ok.py", "content": "x = 1\n"})
    out = _run(reg, "code_write",
               {"path": "ok.py", "content": "def broken(:\n"})
    r = out["result"]
    assert r["reverted"] is True
    out = _run(reg, "code_read", {"path": "ok.py"})
    assert "x = 1" in out["result"]["content"]


def test_lint_gate_reverts_syntax_breaking_edit(tmp_path):
    reg = _registry(tmp_path)
    _run(reg, "code_write", {"path": "m.py", "content": "a = 1\nb = 2\n"})
    _run(reg, "code_read", {"path": "m.py"})
    out = _run(reg, "code_edit",
               {"path": "m.py", "old_text": "a = 1", "new_text": "a = ("})
    r = out["result"]
    assert r["edited"] is False
    assert r["reverted"] is True
    out = _run(reg, "code_read", {"path": "m.py"})
    assert "a = 1" in out["result"]["content"]


def test_lint_gate_ignores_non_python_files(tmp_path):
    reg = _registry(tmp_path)
    out = _run(reg, "code_write",
               {"path": "notes.txt", "content": "def broken(:\n"})
    assert out["result"]["written"] is True
    assert out["result"]["reverted"] is False


# ---------------------------------------------------------------------------
# P2 — code_verify: baseline -> edit -> verdict (real before/after)
# ---------------------------------------------------------------------------

CALC_BUGGY = "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n"
CALC_TESTS = (
    "from calc import add, sub\n\n\n"
    "def test_add():\n    assert add(2, 3) == 5\n\n\n"
    "def test_sub():\n    assert sub(5, 3) == 2\n"
)
PYTEST_CMD = ["python", "-m", "pytest", "-q"]


def _seed_project(reg, calc=CALC_BUGGY, tests=CALC_TESTS):
    _run(reg, "code_write", {"path": "calc.py", "content": calc})
    _run(reg, "code_write", {"path": "test_calc.py", "content": tests})


def test_verify_full_after_fix(tmp_path):
    reg = _registry(tmp_path)
    _seed_project(reg)
    out = _run(reg, "code_verify", {"command": PYTEST_CMD})
    r = out["result"]
    assert r["phase"] == "baseline"
    assert r["verdict"] == "BASELINE"
    assert r["parseable"] is True
    assert any("test_add" in n for n in r["current"]["failed_names"])

    _run(reg, "code_read", {"path": "calc.py"})
    out = _run(reg, "code_edit",
               {"path": "calc.py", "old_text": "return a - b\n\n\ndef sub",
                "new_text": "return a + b\n\n\ndef sub"})
    assert out["result"]["edited"] is True

    out = _run(reg, "code_verify", {"command": PYTEST_CMD})
    r = out["result"]
    assert r["phase"] == "after"
    assert r["verdict"] == "FULL", r
    assert any("test_add" in n for n in r["fixed"])
    assert r["regressions"] == []
    assert r["remaining_failures"] == []


def test_verify_partial_when_fix_regresses_another_test(tmp_path):
    reg = _registry(tmp_path)
    _seed_project(reg)
    _run(reg, "code_verify", {"command": PYTEST_CMD})
    _run(reg, "code_read", {"path": "calc.py"})
    # fix add, break sub
    _run(reg, "code_edit",
         {"path": "calc.py", "old_text": "return a - b\n\n\ndef sub",
          "new_text": "return a + b\n\n\ndef sub"})
    _run(reg, "code_edit",
         {"path": "calc.py", "old_text": "def sub(a, b):\n    return a - b",
          "new_text": "def sub(a, b):\n    return a + b"})
    out = _run(reg, "code_verify", {"command": PYTEST_CMD})
    r = out["result"]
    assert r["verdict"] == "PARTIAL", r
    assert any("test_sub" in n for n in r["regressions"])


def test_verify_no_when_repro_still_fails(tmp_path):
    reg = _registry(tmp_path)
    _seed_project(reg)
    _run(reg, "code_write",
         {"path": "repro.py",
          "content": "from calc import add\nassert add(2, 3) == 5\n"})
    out = _run(reg, "code_verify",
               {"command": PYTEST_CMD, "repro": "repro.py"})
    assert out["result"]["repro"] == "failed"
    out = _run(reg, "code_verify",
               {"command": PYTEST_CMD, "repro": "repro.py"})
    r = out["result"]
    assert r["verdict"] == "NO", r


def test_verify_full_with_repro(tmp_path):
    reg = _registry(tmp_path)
    _seed_project(reg)
    _run(reg, "code_write",
         {"path": "repro.py",
          "content": "from calc import add\nassert add(2, 3) == 5\n"})
    _run(reg, "code_verify", {"command": PYTEST_CMD, "repro": "repro.py"})
    _run(reg, "code_read", {"path": "calc.py"})
    _run(reg, "code_edit",
         {"path": "calc.py", "old_text": "return a - b\n\n\ndef sub",
          "new_text": "return a + b\n\n\ndef sub"})
    out = _run(reg, "code_verify",
               {"command": PYTEST_CMD, "repro": "repro.py"})
    r = out["result"]
    assert r["repro"] == "passed"
    assert r["verdict"] == "FULL", r


def test_verify_unparseable_output_is_no(tmp_path):
    reg = _registry(tmp_path)
    cmd = ["python", "-c", "print('just some prose')"]
    _run(reg, "code_verify", {"command": cmd})
    out = _run(reg, "code_verify", {"command": cmd})
    r = out["result"]
    assert r["parseable"] is False
    assert r["verdict"] == "NO"


def test_verify_rejects_shell_string(tmp_path):
    reg = _registry(tmp_path)
    out = _run(reg, "code_verify", {"command": "pytest -q"})
    assert out["ok"] is False


# ---------------------------------------------------------------------------
# P3 — match ladder rungs
# ---------------------------------------------------------------------------


def test_edit_exact_rung_reported(tmp_path):
    reg = _registry(tmp_path)
    _run(reg, "code_write", {"path": "m.py", "content": "a = 1\nb = 2\n"})
    out = _run(reg, "code_edit",
               {"path": "m.py", "old_text": "a = 1", "new_text": "a = 10"})
    r = out["result"]
    assert r["edited"] is True
    assert r["rung"] == "exact"


def test_edit_whitespace_rung(tmp_path):
    reg = _registry(tmp_path)
    _run(reg, "code_write",
         {"path": "m.py", "content": "if True:\n    x = 1\n    y = 2\n"})
    _run(reg, "code_read", {"path": "m.py"})
    out = _run(reg, "code_edit",
               {"path": "m.py", "old_text": "x = 1\ny = 2",
                "new_text": "    x = 10\n    y = 20"})
    r = out["result"]
    assert r["edited"] is True
    assert r["rung"] == "whitespace"
    out = _run(reg, "code_read", {"path": "m.py"})
    assert "x = 10" in out["result"]["content"]
    assert "y = 20" in out["result"]["content"]


def test_edit_unicode_rung(tmp_path):
    reg = _registry(tmp_path)
    _run(reg, "code_write",
         {"path": "m.py", "content": "msg = \"it’s jarvis\"\n"})
    _run(reg, "code_read", {"path": "m.py"})
    out = _run(reg, "code_edit",
               {"path": "m.py", "old_text": "msg = \"it's jarvis\"",
                "new_text": "msg = \"it's ovi\""})
    r = out["result"]
    assert r["edited"] is True
    assert r["rung"] == "unicode"
    out = _run(reg, "code_read", {"path": "m.py"})
    assert "ovi" in out["result"]["content"]


def test_edit_structural_rung_replaces_whole_def(tmp_path):
    reg = _registry(tmp_path)
    src = ("def keep():\n    return 1\n\n\n"
           "def target(a, b):\n    return a - b\n")
    _run(reg, "code_write", {"path": "m.py", "content": src})
    _run(reg, "code_read", {"path": "m.py"})
    out = _run(reg, "code_edit",
               {"path": "m.py",
                "old_text": "def target(a, b):\n    return a + b",
                "new_text": "def target(a, b):\n    return a * b"})
    r = out["result"]
    assert r["edited"] is True
    assert r["rung"] == "structural"
    out = _run(reg, "code_read", {"path": "m.py"})
    content = out["result"]["content"]
    assert "a * b" in content
    assert "a - b" not in content
    assert "def keep" in content  # sibling untouched


def test_edit_no_match_error_has_similar_line_hints(tmp_path):
    reg = _registry(tmp_path)
    _run(reg, "code_write", {"path": "m.py", "content": "x = 41\ny = 2\n"})
    _run(reg, "code_read", {"path": "m.py"})
    out = _run(reg, "code_edit",
               {"path": "m.py", "old_text": "x = 42", "new_text": "x = 43"})
    assert out["ok"] is False
    assert "Closest lines" in json.dumps(out)
    assert "line 1" in json.dumps(out)


def test_edit_empty_old_text_refused(tmp_path):
    reg = _registry(tmp_path)
    _run(reg, "code_write", {"path": "m.py", "content": ""})
    out = _run(reg, "code_edit",
               {"path": "m.py", "old_text": "", "new_text": "x"})
    assert out["ok"] is False
    assert "must not be empty" in json.dumps(out)


# ---------------------------------------------------------------------------
# P3 — freshness gate
# ---------------------------------------------------------------------------


def test_edit_refused_when_never_read(tmp_path):
    reg = _registry(tmp_path)
    jail = _jail(reg)
    jail.mkdir(parents=True, exist_ok=True)
    (jail / "ext.py").write_text("a = 1\n", encoding="utf-8")  # external
    out = _run(reg, "code_edit",
               {"path": "ext.py", "old_text": "a = 1", "new_text": "a = 2"})
    assert out["ok"] is False
    assert "has not been read" in json.dumps(out)


def test_edit_refused_when_file_changed_since_read(tmp_path):
    reg = _registry(tmp_path)
    _run(reg, "code_write", {"path": "m.py", "content": "a = 1\n"})
    _run(reg, "code_read", {"path": "m.py"})
    jail_file = _jail(reg) / "m.py"
    jail_file.write_text("a = 999\n", encoding="utf-8")  # external change
    out = _run(reg, "code_edit",
               {"path": "m.py", "old_text": "a = 999", "new_text": "a = 2"})
    assert out["ok"] is False
    assert "changed since" in json.dumps(out)


def test_edit_allowed_right_after_write(tmp_path):
    reg = _registry(tmp_path)
    _run(reg, "code_write", {"path": "m.py", "content": "a = 1\n"})
    # no explicit read: the write itself recorded the stamp
    out = _run(reg, "code_edit",
               {"path": "m.py", "old_text": "a = 1", "new_text": "a = 2"})
    assert out["ok"] is True
    assert out["result"]["edited"] is True


# ---------------------------------------------------------------------------
# P4 — code_map
# ---------------------------------------------------------------------------


def test_code_map_ranks_referenced_symbols_above_orphans(tmp_path):
    reg = _registry(tmp_path)
    _run(reg, "code_write", {"path": "a.py", "content":
                             "def helper():\n    return 7\n\n\n"
                             "def main():\n    return helper()\n"})
    _run(reg, "code_write", {"path": "b.py", "content":
                             "def orphan():\n    return 0\n"})
    out = _run(reg, "code_map", {})
    assert out["ok"] is True
    r = out["result"]
    assert r["files"] == 2
    assert r["nodes"] == 3
    scores = {s["name"]: s["score"] for s in r["symbols"]}
    assert scores["helper"] > scores["orphan"]
    assert "helper" in r["map"]
    assert (_jail(reg) / ".code_map.db").exists()  # sqlite cache landed


def test_code_map_focus_boosts_named_symbol(tmp_path):
    reg = _registry(tmp_path)
    _run(reg, "code_write", {"path": "a.py", "content":
                             "def helper():\n    return 7\n\n\n"
                             "def main():\n    return helper()\n"})
    out = _run(reg, "code_map", {"focus": ["main"]})
    r = out["result"]
    assert r["symbols"][0]["name"] == "main"  # personalization wins


def test_code_map_empty_jail(tmp_path):
    reg = _registry(tmp_path)
    out = _run(reg, "code_map", {})
    assert out["ok"] is True
    assert out["result"]["nodes"] == 0
