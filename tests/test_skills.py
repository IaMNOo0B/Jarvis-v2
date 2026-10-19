"""Tests for the v2 skill system: discovery, quarantine, dispatch pipeline,
circuit breakers, jail, static scan. Stdlib only; hermetic (tmp_path)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.skills import (
    SkillContext,
    SkillManifestError,
    SkillRegistry,
    UnknownTool,
    scan_skill,
)

ALLOW_ALL = lambda tool, tier, args, ctx: True  # noqa: E731
DENY_ALL = lambda tool, tier, args, ctx: False  # noqa: E731


def _write_skill(
    skills_dir: Path,
    name: str,
    manifest: dict,
    code: str = 'def handle(tool_name, args, ctx):\n    return {}\n',
) -> Path:
    d = skills_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "skill.json").write_text(json.dumps(manifest), encoding="utf-8")
    (d / "skill.py").write_text(code, encoding="utf-8")
    (d / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
    return d


def _echo_manifest(**over) -> dict:
    m = {
        "name": "echo",
        "version": "1.0.0",
        "description": "echo",
        "capabilities": [],
        "tools": [
            {
                "name": "echo",
                "description": "echo",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                    "additionalProperties": False,
                },
                "returns": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
                "tier": 1,
                "timeout_s": 5,
                "output_cap_chars": 10240,
                "capabilities": [],
            }
        ],
    }
    m.update(over)
    return m


def _registry(tmp_path: Path, *skills: str) -> SkillRegistry:
    """Registry over the real shipped reference skills (copies)."""
    src = Path(__file__).resolve().parents[1] / "skills"
    dst = tmp_path / "skills"
    dst.mkdir()
    for s in skills:
        import shutil

        shutil.copytree(src / s, dst / s)
    data = tmp_path / "data"
    data.mkdir()
    reg = SkillRegistry(dst, data)
    reg.discover()
    return reg


def _ctx(**kw) -> SkillContext:
    kw.setdefault("skill_name", "test")
    kw.setdefault("capabilities", ["fs.read", "fs.write", "time.read"])
    kw.setdefault("jail_dir", ".")
    return SkillContext(**kw)


# ---------------------------------------------------------------------------
# Discovery & strict validation
# ---------------------------------------------------------------------------


def test_unknown_manifest_key_is_startup_error(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    bad = _echo_manifest()
    bad["bogus_key"] = "typo here"
    _write_skill(skills, "echo", bad)
    reg = SkillRegistry(skills, tmp_path / "data")
    records = reg.discover()
    assert len(records) == 1
    rec = records[0]
    assert isinstance(rec.load_error, SkillManifestError)
    assert "unknown manifest keys" in str(rec.load_error)
    assert rec.manifest is None  # excluded, never advertised
    with pytest.raises(UnknownTool):
        reg.get_tool("echo")


def test_manifest_name_must_match_directory(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    _write_skill(skills, "echo", _echo_manifest(name="not_echo"))
    reg = SkillRegistry(skills, tmp_path / "data")
    (rec,) = reg.discover()
    assert isinstance(rec.load_error, SkillManifestError)
    assert "must match directory name" in str(rec.load_error)


def test_duplicate_tool_names_across_skills_rejected(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    _write_skill(skills, "echo", _echo_manifest())
    other = _echo_manifest(name="echo2")
    _write_skill(skills, "echo2", other)
    reg = SkillRegistry(skills, tmp_path / "data")
    records = {r.name: r for r in reg.discover()}
    assert isinstance(records["echo2"].load_error, SkillManifestError)
    assert "collision" in str(records["echo2"].load_error)


def test_unknown_capability_rejected(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    bad = _echo_manifest(capabilities=["mind.read"])
    _write_skill(skills, "echo", bad)
    reg = SkillRegistry(skills, tmp_path / "data")
    (rec,) = reg.discover()
    assert isinstance(rec.load_error, SkillManifestError)
    assert "unknown capabilities" in str(rec.load_error)


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------


def test_new_skill_lands_in_quarantine_until_approved(tmp_path):
    reg = _registry(tmp_path, "echo")
    assert reg.quarantine() == ["echo"]
    out = reg.dispatch("echo", {"text": "hi"}, _ctx(), ALLOW_ALL)
    assert out["ok"] is False
    assert out["error"]["code"] == "skill_quarantined"
    reg.approve("echo")
    assert reg.quarantine() == []
    out = reg.dispatch("echo", {"text": "hi"}, _ctx(), ALLOW_ALL)
    assert out["ok"] is True
    assert out["result"] == {"text": "hi"}


def test_changed_manifest_retriggers_quarantine(tmp_path):
    reg = _registry(tmp_path, "echo")
    reg.approve("echo")
    assert reg.quarantine() == []
    # attacker/user edits the manifest after approval
    manifest_file = reg.skills_dir / "echo" / "skill.json"
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    data["version"] = "9.9.9"
    manifest_file.write_text(json.dumps(data), encoding="utf-8")
    reg.discover()
    assert reg.quarantine() == ["echo"]
    out = reg.dispatch("echo", {"text": "hi"}, _ctx(), ALLOW_ALL)
    assert out["error"]["code"] == "skill_quarantined"


# ---------------------------------------------------------------------------
# Dispatch pipeline
# ---------------------------------------------------------------------------


def test_happy_path_echo_and_evidence_wrap(tmp_path):
    reg = _registry(tmp_path, "echo")
    reg.approve("echo")
    out = reg.dispatch("echo", {"text": "hello"}, _ctx(turn_id=3), ALLOW_ALL)
    assert out["ok"] is True
    assert out["truncated"] is False
    assert 'source="echo.echo"' in out["evidence"]
    assert 'trust="untrusted"' in out["evidence"]
    assert 'turn="3"' in out["evidence"]


def test_schema_error_on_bad_args(tmp_path):
    reg = _registry(tmp_path, "echo")
    reg.approve("echo")
    out = reg.dispatch("echo", {"nope": 1}, _ctx(), ALLOW_ALL)
    assert out["ok"] is False
    assert out["error"]["code"] == "schema_error"
    assert out["error"]["stage"] == "schema-validate"


def test_unknown_tool(tmp_path):
    reg = _registry(tmp_path, "echo")
    reg.approve("echo")
    out = reg.dispatch("nope", {}, _ctx(), ALLOW_ALL)
    assert out["error"]["code"] == "unknown_tool"


def test_capability_denied_does_not_trip_breaker(tmp_path):
    reg = _registry(tmp_path, "notes")
    reg.approve("notes")
    poor_ctx = _ctx(capabilities=["fs.read"])  # missing fs.write
    for _ in range(5):
        out = reg.dispatch(
            "notes_write", {"path": "a.txt", "content": "x"}, poor_ctx, ALLOW_ALL
        )
        assert out["error"]["code"] == "capability_denied"
    rec = reg._records["notes"]
    assert rec.failures == 0  # denials never count
    assert rec.enabled


def test_tier3_gate_denial_needs_confirmation(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    manifest = _echo_manifest(name="danger")
    manifest["tools"][0].update({"name": "wipe", "tier": 3})
    _write_skill(
        skills,
        "danger",
        manifest,
        code='def handle(tool_name, args, ctx):\n    return {"text": args["text"]}\n',
    )
    reg = SkillRegistry(skills, tmp_path / "data")
    reg.discover()
    reg.approve("danger")
    out = reg.dispatch("wipe", {"text": "x"}, _ctx(), DENY_ALL)
    assert out["error"]["code"] == "confirmation_required"
    out = reg.dispatch("wipe", {"text": "x"}, _ctx(), ALLOW_ALL)
    assert out["ok"] is True


# ---------------------------------------------------------------------------
# Notes skill: jail
# ---------------------------------------------------------------------------


def test_notes_roundtrip_and_list(tmp_path):
    reg = _registry(tmp_path, "notes")
    reg.approve("notes")
    ctx = _ctx()
    out = reg.dispatch(
        "notes_write", {"path": "todo.txt", "content": "buy milk"}, ctx, ALLOW_ALL
    )
    assert out["ok"] is True
    out = reg.dispatch("notes_read", {"path": "todo.txt"}, ctx, ALLOW_ALL)
    assert out["result"]["content"] == "buy milk"
    out = reg.dispatch("notes_list", {}, ctx, ALLOW_ALL)
    assert out["result"]["notes"] == ["todo.txt"]
    # really jailed under <data_dir>/notes
    assert (reg.data_dir / "notes" / "todo.txt").is_file()


def test_path_traversal_denied(tmp_path):
    reg = _registry(tmp_path, "notes")
    reg.approve("notes")
    ctx = _ctx()
    out = reg.dispatch(
        "notes_write", {"path": "../evil.txt", "content": "x"}, ctx, ALLOW_ALL
    )
    assert out["ok"] is False
    assert out["error"]["code"] == "skill_violation"
    assert not (reg.data_dir / "evil.txt").exists()
    out = reg.dispatch(
        "notes_write", {"path": "/tmp/abs.txt", "content": "x"}, ctx, ALLOW_ALL
    )
    assert out["ok"] is False
    assert not Path("/tmp/abs.txt").exists()


# ---------------------------------------------------------------------------
# Clock skill
# ---------------------------------------------------------------------------


def test_clock_now(tmp_path):
    reg = _registry(tmp_path, "clock")
    reg.approve("clock")
    out = reg.dispatch("now", {}, _ctx(), ALLOW_ALL)
    assert out["ok"] is True
    assert "iso" in out["result"]


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


def test_circuit_breaker_trips_at_three(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    manifest = _echo_manifest(name="boom")
    _write_skill(
        skills,
        "boom",
        manifest,
        code="def handle(tool_name, args, ctx):\n    raise RuntimeError('always fails')\n",
    )
    reg = SkillRegistry(skills, tmp_path / "data")
    reg.discover()
    reg.approve("boom")
    for i in range(3):
        out = reg.dispatch("echo", {"text": "x"}, _ctx(), ALLOW_ALL)
        assert out["error"]["code"] == "skill_error", i
    rec = reg._records["boom"]
    assert rec.enabled is False
    assert "circuit breaker" in rec.disabled_reason
    out = reg.dispatch("echo", {"text": "x"}, _ctx(), ALLOW_ALL)
    assert out["error"]["code"] == "skill_disabled"
    # manual re-enable only
    reg.reenable("boom")
    assert reg._records["boom"].enabled is True
    out = reg.dispatch("echo", {"text": "x"}, _ctx(), ALLOW_ALL)
    assert out["error"]["code"] == "skill_error"  # fails again, counter restarts


# ---------------------------------------------------------------------------
# Output cap
# ---------------------------------------------------------------------------


def test_output_over_cap_is_truncated_not_dropped(tmp_path):
    reg = _registry(tmp_path, "echo")
    reg.approve("echo")
    big = "x" * 20000
    out = reg.dispatch("echo", {"text": big}, _ctx(), ALLOW_ALL)
    assert out["ok"] is True
    assert out["truncated"] is True
    assert "truncated at 10240 chars" in out["evidence"]
    assert len(out["evidence"]) < 20000  # actually bounded


# ---------------------------------------------------------------------------
# Static scan
# ---------------------------------------------------------------------------


def test_scan_flags_eval_and_os_system(tmp_path):
    skills = tmp_path / "skills"
    evil = _write_skill(
        skills,
        "evil",
        _echo_manifest(name="evil"),
        code="import os\ndef handle(t, a, c):\n    eval('1')\n    os.system('x')\n    return {}\n",
    )
    findings = scan_skill(evil)
    rules = {f["rule"] for f in findings}
    assert "dangerous-call" in rules
    assert any("eval" in f["message"] for f in findings)
    assert any("os.system" in f["message"] for f in findings)


def test_scan_clean_skill_has_no_findings(tmp_path):
    skills = tmp_path / "skills"
    clean = _write_skill(skills, "echo", _echo_manifest())
    assert scan_skill(clean) == []


def test_scan_flags_capability_mismatch(tmp_path):
    skills = tmp_path / "skills"
    sneaky = _write_skill(
        skills,
        "sneaky",
        _echo_manifest(name="sneaky"),  # declares NO capabilities
        code="import socket\ndef handle(t, a, c):\n    return {}\n",
    )
    findings = scan_skill(sneaky)
    assert any(
        f["rule"] == "capability-mismatch" and "net.outbound" in f["message"]
        for f in findings
    )


# ---------------------------------------------------------------------------
# Wiring audit
# ---------------------------------------------------------------------------


def test_audit_wiring_reports_missing_handle(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    _write_skill(
        skills,
        "broken",
        _echo_manifest(name="broken"),
        code="def not_handle():\n    pass\n",
    )
    reg = SkillRegistry(skills, tmp_path / "data")
    reg.discover()
    reg.approve("broken")
    orphans = reg.audit_wiring()
    assert orphans == ["broken"]


def test_audit_wiring_clean_when_all_wired(tmp_path):
    reg = _registry(tmp_path, "echo", "notes", "clock")
    for name in ("echo", "notes", "clock"):
        reg.approve(name)
    assert reg.audit_wiring() == []
