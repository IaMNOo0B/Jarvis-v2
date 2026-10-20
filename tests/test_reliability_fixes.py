"""Tests for the Team 19 Part E reliability fixes:

1. Owner kill-switch flags (config.py `flags` section + Config.is_enabled,
   consulted once in gate.py's dispatch paths).
2. Log rotation on every append sink (observability JSONL sink, session
   day archive, evolution snapshots) — shared 10 MB x 5 budget.
3. Exception fingerprinting in observability (same error -> same
   fingerprint, recurrence counted in memory and in the JSONL sink).
"""

import json

import pytest

from jarvis import observability as obs
from jarvis.config import Config, default_schema
from jarvis.gate import Gate, Verdict


# --------------------------------------------------------------------------
# 1. Feature flags / kill-switch
# --------------------------------------------------------------------------

def _config(tmp_path, flags=None):
    path = tmp_path / "config.json"
    if flags is not None:
        path.write_text(json.dumps({"flags": flags}), encoding="utf-8")
    cfg = Config(str(path), default_schema())
    cfg.load()
    return cfg


def test_flags_section_defaults_empty_and_absent_is_caller_default(tmp_path):
    cfg = _config(tmp_path)
    assert cfg.get("flags") == {}
    assert cfg.is_enabled("skill.finance") is False          # default default
    assert cfg.is_enabled("skill.finance", True) is True      # absent = default


def test_flag_values_are_honoured(tmp_path):
    cfg = _config(tmp_path, {"skill.finance": False, "tool.code_run": True})
    assert cfg.is_enabled("skill.finance", True) is False     # explicit off
    assert cfg.is_enabled("tool.code_run") is True            # explicit on
    assert cfg.is_enabled("skill.never_set", True) is True    # absent


def test_flag_set_save_reload_roundtrip(tmp_path):
    cfg = _config(tmp_path)
    cfg.set("flags", {"skill.web": False})
    cfg.save()
    cfg2 = _config(tmp_path)
    assert cfg2.is_enabled("skill.web", True) is False


def test_flag_non_bool_value_is_fail_safe(tmp_path):
    cfg = _config(tmp_path, {"skill.web": "off"})
    # A non-bool is not a decision: the caller's default wins, both ways.
    assert cfg.is_enabled("skill.web", True) is True
    assert cfg.is_enabled("skill.web", False) is False


@pytest.fixture
def registry():
    return {
        "notes.read": {
            "tier": 1, "capabilities": ["fs.read"],
            "schema": {"required": ["path"],
                       "properties": {"path": {"type": "str"}}},
        },
        "notes.write": {
            "tier": 2, "capabilities": ["fs.write"],
            "schema": {"required": ["path", "text"],
                       "properties": {"path": {"type": "str"},
                                      "text": {"type": "str"}}},
        },
        "counter.bump": {
            "tier": 1, "capabilities": [],
            "schema": {"required": ["n"],
                       "properties": {"n": {"type": "int"}}},
        },
        "system.reboot": {
            "tier": 3, "capabilities": ["sys.admin"],
            "schema": {"required": [], "properties": {}},
        },
    }


def _spy_executor(calls):
    def run(tool_name, args):
        calls.append(tool_name)
        return f"done:{tool_name}"
    return run


def test_gate_without_flag_checker_behaves_as_before(registry):
    g = Gate(rules={}, skill_registry=registry)
    calls = []
    decision, out = g.dispatch("notes.read", {"path": "x"}, ["fs.read"],
                               _spy_executor(calls))
    assert decision.verdict is Verdict.ALLOW
    assert calls == ["notes.read"]
    assert out is not None


def test_gate_flag_checker_with_no_flags_set_behaves_as_before(
        registry, tmp_path):
    cfg = _config(tmp_path)  # no flags anywhere
    g = Gate(rules={}, skill_registry=registry, flag_checker=cfg.is_enabled)
    calls = []
    decision, _ = g.dispatch("notes.read", {"path": "x"}, ["fs.read"],
                             _spy_executor(calls))
    assert decision.verdict is Verdict.ALLOW
    assert calls == ["notes.read"]


def test_gate_tool_flag_denies_dispatch_before_executor(registry, tmp_path):
    cfg = _config(tmp_path, {"tool.notes.read": False})
    g = Gate(rules={}, skill_registry=registry, flag_checker=cfg.is_enabled)
    calls = []
    decision, out = g.dispatch("notes.read", {"path": "x"}, ["fs.read"],
                               _spy_executor(calls))
    assert decision.verdict is Verdict.DENY
    assert decision.reason == "disabled by owner flag: tool.notes.read"
    assert out is None
    assert calls == []  # executor never ran


def test_gate_skill_flag_denies_the_whole_skill_only(registry, tmp_path):
    cfg = _config(tmp_path, {"skill.notes": False})
    g = Gate(rules={}, skill_registry=registry, flag_checker=cfg.is_enabled)
    calls = []
    for tool, args, allow in (
            ("notes.read", {"path": "x"}, ["fs.read"]),
            ("notes.write", {"path": "x", "text": "y"}, ["fs.write"])):
        decision, _ = g.dispatch(tool, args, allow, _spy_executor(calls))
        assert decision.verdict is Verdict.DENY
        assert decision.reason == "disabled by owner flag: skill.notes"
    # A different skill is untouched.
    decision, _ = g.dispatch("counter.bump", {"n": 1}, [],
                             _spy_executor(calls))
    assert decision.verdict is Verdict.ALLOW
    assert calls == ["counter.bump"]


def test_gate_flag_also_guards_the_approved_path(registry, tmp_path):
    cfg = _config(tmp_path)
    g = Gate(rules={}, skill_registry=registry, flag_checker=cfg.is_enabled)
    decision = g.check("system.reboot", {}, ["sys.admin"])
    assert decision.verdict is Verdict.REQUIRE_APPROVAL
    token = decision.approval_request["token"]
    # Owner flips the kill-switch AFTER approval, BEFORE execution.
    cfg.set("flags", {"tool.system.reboot": False})
    calls = []
    decision2, out = g.execute_approved(token, "system.reboot", {},
                                        _spy_executor(calls))
    assert decision2.verdict is Verdict.DENY
    assert decision2.reason == "disabled by owner flag: tool.system.reboot"
    assert out is None
    assert calls == []


# --------------------------------------------------------------------------
# 2. Log rotation
# --------------------------------------------------------------------------

def test_rotate_numbered_below_cap_is_noop(tmp_path):
    p = tmp_path / "spans.jsonl"
    p.write_text("small\n", encoding="utf-8")
    assert obs.rotate_numbered(p, max_bytes=1024, backup_count=5) is False
    assert p.read_text(encoding="utf-8") == "small\n"
    assert not (tmp_path / "spans.jsonl.1").exists()


def test_rotate_numbered_rolls_and_shifts(tmp_path):
    p = tmp_path / "spans.jsonl"
    p.write_text("live" * 40, encoding="utf-8")       # 160 bytes
    (tmp_path / "spans.jsonl.1").write_text("older", encoding="utf-8")
    assert obs.rotate_numbered(p, max_bytes=100, backup_count=5) is True
    assert not p.exists()
    assert (tmp_path / "spans.jsonl.1").read_text(
        encoding="utf-8") == "live" * 40
    assert (tmp_path / "spans.jsonl.2").read_text(
        encoding="utf-8") == "older"


def test_rotate_numbered_respects_backup_budget(tmp_path):
    p = tmp_path / "x.log"
    for i in range(4):
        p.write_text(f"gen{i}" * 40, encoding="utf-8")
        assert obs.rotate_numbered(p, max_bytes=100, backup_count=2) is True
    names = sorted(x.name for x in tmp_path.iterdir())
    assert names == ["x.log.1", "x.log.2"]            # never a .3
    assert (tmp_path / "x.log.1").read_text(
        encoding="utf-8").startswith("gen3")          # newest backup


def test_rotate_numbered_missing_file_and_never_raises(tmp_path):
    assert obs.rotate_numbered(tmp_path / "nope.log") is False


def test_span_recorder_sink_rotates_on_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(obs, "LOG_MAX_BYTES", 120)
    sink = tmp_path / "spans.jsonl"
    rec = obs.SpanRecorder(sink_path=sink)
    for i in range(30):
        rec.record({"trace_id": "t", "span_id": str(i), "parent_id": "",
                    "name": "turn", "ts": 0.0, "dur_ms": 1.0,
                    "attrs": {"i": i, "pad": "x" * 20}})
    assert (tmp_path / "spans.jsonl.1").exists()      # a roll happened
    assert sink.stat().st_size < 10 * 120             # live file bounded
    total = sum(x.stat().st_size for x in tmp_path.iterdir())
    assert total <= 6 * (120 + 200)                   # live + <=5 backups


def test_session_day_archive_rolls_to_glob_compatible_parts(
        tmp_path, monkeypatch):
    import jarvis.session_store as ss

    monkeypatch.setattr(ss, "LOG_MAX_BYTES", 300)
    monkeypatch.setattr(ss, "LOG_BACKUP_COUNT", 2)
    store = ss.SessionStore(str(tmp_path / "sessions.db"))
    sid = store.create_session("owais", "chat")
    for _ in range(40):
        store.emit(sid, "user.message", {"text": "x" * 60}, actor="user")

    day_files = sorted(p.name for p in tmp_path.glob("sessions-*.jsonl"))

    def _is_part(name):
        mid = name[len("sessions-"):-len(".jsonl")]  # "2026-10-20" or "...20.3"
        return "." in mid and mid.rsplit(".", 1)[-1].isdigit()

    parts = [n for n in day_files if _is_part(n)]
    live = [n for n in day_files if n not in parts]
    assert parts, "the day archive rolled into part files"
    assert len(parts) <= 2, "part count respects the backup budget"
    assert len(live) == 1, "exactly one live day file"
    # Every file still matches the sessions-*.jsonl glob the DCL audit
    # reader scans (they all end in .jsonl by construction).
    assert all(n.endswith(".jsonl") for n in day_files)
    # The events themselves are intact in the store.
    assert len(store.get_events(sid, limit=1000)) == 40


def test_evolution_snapshots_call_site_rotates(tmp_path, monkeypatch):
    import jarvis.evolution_runner as er

    calls = []

    def spy(path, **kw):
        calls.append(path)
        return obs.rotate_numbered(path, max_bytes=100, backup_count=2)

    monkeypatch.setattr(er, "rotate_numbered", spy)
    evo_dir = tmp_path / "evolution"
    evo_dir.mkdir()
    snap = evo_dir / "anticipations.jsonl"
    snap.write_text("old" * 60 + "\n", encoding="utf-8")

    class FakeFoundry:
        def anticipations(self, now):
            return [{"kind": "reminder"}]

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    report = er.ReviewReport(day="2026-10-20", diary_day="2026-10-19",
                             ran_at=now.isoformat())
    er._step_anticipation(FakeFoundry(), now, evo_dir, report)
    assert calls == [snap]                            # rotation was consulted
    assert (evo_dir / "anticipations.jsonl.1").exists()
    lines = snap.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1                            # fresh line appended
    assert json.loads(lines[0])["anticipations"] == [{"kind": "reminder"}]


# --------------------------------------------------------------------------
# 3. Exception fingerprinting
# --------------------------------------------------------------------------

def _raised_wrap_output_error():
    """Raise the same jarvis error from the same site, twice-able."""
    try:
        Gate.wrap_output("x", source='bad"source')
    except ValueError as exc:
        return exc
    raise AssertionError("wrap_output should have raised")


def test_fingerprint_stable_for_same_error_raised_twice():
    fp1 = obs.fingerprint(_raised_wrap_output_error())
    fp2 = obs.fingerprint(_raised_wrap_output_error())
    assert fp1 == fp2
    assert len(fp1) == 16


def test_fingerprint_differs_for_different_bug(tmp_path):
    gate_fp = obs.fingerprint(_raised_wrap_output_error())
    cfg = _config(tmp_path)
    try:
        cfg.set("nope.missing", 1)
    except KeyError as exc:
        config_fp = obs.fingerprint(exc)
    else:  # pragma: no cover
        raise AssertionError("set() should have raised KeyError")
    assert config_fp != gate_fp


def test_fingerprint_unraised_exception_groups_by_type():
    fp = obs.fingerprint(ValueError("never raised"))
    assert fp == obs.fingerprint(ValueError("different message, same type"))


def test_recorder_counts_recurrences_in_memory_and_sink(tmp_path):
    sink = tmp_path / "spans.jsonl"
    rec = obs.SpanRecorder(sink_path=sink)
    base = {"trace_id": "t", "parent_id": "", "name": "turn", "ts": 0.0,
            "dur_ms": 1.0}
    rec.record({**base, "span_id": "1",
                "attrs": {"error_exc": _raised_wrap_output_error()}})
    rec.record({**base, "span_id": "2",
                "attrs": {"error_exc": _raised_wrap_output_error()}})

    fp = rec.spans[0]["attrs"]["error_fingerprint"]
    assert rec.spans[1]["attrs"]["error_fingerprint"] == fp
    assert rec.spans[0]["attrs"]["error_count"] == 1
    assert rec.spans[1]["attrs"]["error_count"] == 2
    assert "error_exc" not in rec.spans[0]["attrs"]  # never serialised
    assert rec.error_summary()[fp]["count"] == 2

    lines = sink.read_text(encoding="utf-8").strip().splitlines()
    sink_rows = [json.loads(line) for line in lines]
    assert sink_rows[0]["attrs"]["error_fingerprint"] == fp
    assert sink_rows[1]["attrs"]["error_count"] == 2


def test_span_context_marks_fingerprint_and_counts(tmp_path):
    rec = obs.SpanRecorder()
    for _ in range(2):
        with pytest.raises(ValueError):
            with obs.span("boom", recorder=rec):
                Gate.wrap_output("x", source='bad"source')
    first, second = rec.spans
    assert first["attrs"]["error_fingerprint"] == \
        second["attrs"]["error_fingerprint"]
    assert first["attrs"]["error_count"] == 1
    assert second["attrs"]["error_count"] == 2
    assert "ValueError" in first["attrs"]["error"]
