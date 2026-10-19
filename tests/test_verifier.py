"""Tests for the D3 trajectory verifier (F1-F8 flaw taxonomy)."""

import pytest

from jarvis.verifier import TrajectoryVerifier


def v(**kw):
    return TrajectoryVerifier(**kw)


class TestF1Schema:
    def test_missing_required_arg_fails(self):
        tv = v(tool_schemas={"notes_write": {"required": ["path", "content"],
                                             "types": {"path": "str"}}})
        r = tv.verify([{"tool": "notes_write", "args": {"path": "a.txt"}}])
        assert not r.passed
        assert r.failures[0].flaw == "F1"

    def test_wrong_type_fails(self):
        tv = v(tool_schemas={"x": {"required": [], "types": {"n": "int"}}})
        r = tv.verify([{"tool": "x", "args": {"n": "five"}}])
        assert not r.passed and r.failures[0].flaw == "F1"

    def test_valid_passes(self):
        tv = v(tool_schemas={"notes_write": {"required": ["path"],
                                             "types": {"path": "str"}}})
        r = tv.verify([{"tool": "notes_write", "args": {"path": "a.txt"}}])
        assert r.passed


class TestF2Preconditions:
    def test_empty_path_fails(self):
        r = v().verify([{"tool": "notes_write", "args": {"path": ""}}])
        assert not r.passed and r.failures[0].flaw == "F2"

    def test_dotdot_escape_fails(self):
        r = v().verify([{"tool": "delete",
                         "args": {"path": "../../secret.txt"}}])
        assert not r.passed and r.failures[0].flaw == "F2"


class TestF3Ordering:
    def test_delete_before_backup_fails(self):
        r = v().verify([
            {"tool": "delete", "args": {"path": "report.docx"}},
            {"tool": "backup", "args": {"path": "report.docx"}},
        ])
        assert not r.passed and r.failures[0].flaw == "F3"

    def test_backup_before_delete_passes(self):
        r = v().verify([
            {"tool": "backup", "args": {"path": "report.docx"}},
            {"tool": "delete", "args": {"path": "report.docx"}},
        ])
        assert r.passed


class TestF4ToolChoice:
    def test_rm_rf_in_shell_fails(self):
        r = v().verify([{"tool": "pc.shell",
                         "args": {"command": "rm -rf /tmp/junk"}}])
        assert not r.passed and r.failures[0].flaw == "F4"

    def test_safe_delete_passes(self):
        r = v().verify([{"tool": "notes_write",
                         "args": {"path": "a.txt", "content": "hi"}}])
        assert r.passed


class TestF5References:
    def test_hallucinated_id_fails(self):
        tv = v(observed_ids={"btn-1", "btn-2"})
        r = tv.verify([{"tool": "pc.click",
                        "args": {"element_id": "btn-999"}}])
        assert not r.passed and r.failures[0].flaw == "F5"

    def test_observed_id_passes(self):
        tv = v(observed_ids={"btn-1"})
        r = tv.verify([{"tool": "pc.click",
                        "args": {"element_id": "btn-1"}}])
        assert r.passed


class TestF6Confirmation:
    def test_tier3_without_approval_fails(self):
        tv = v(tool_tiers={"pc.shell": 3})
        r = tv.verify([{"tool": "pc.shell",
                        "args": {"command": "dir"}}])
        assert not r.passed and r.failures[0].flaw == "F6"

    def test_tier3_with_approval_passes(self):
        tv = v(tool_tiers={"pc.shell": 3}, approved_tools={"pc.shell"})
        r = tv.verify([{"tool": "pc.shell",
                        "args": {"command": "dir"}}])
        assert r.passed

    def test_tier1_needs_no_approval(self):
        tv = v(tool_tiers={"clock.now": 1})
        assert tv.verify([{"tool": "clock.now", "args": {}}]).passed


class TestF7Scope:
    def test_path_outside_scope_fails(self):
        tv = v(scope_roots=["C:/Users/Owais/Downloads"])
        r = tv.verify([{"tool": "notes_write",
                        "args": {"path": "C:/Windows/evil.txt"}}])
        assert not r.passed and r.failures[0].flaw == "F7"

    def test_path_inside_scope_passes(self):
        tv = v(scope_roots=["C:/Users/Owais/Downloads"])
        r = tv.verify([{"tool": "notes_write",
                        "args": {"path": "C:/Users/Owais/Downloads/n.txt"}}])
        assert r.passed


class TestF8Constraints:
    def test_violated_constraint_fails(self):
        tv = v(user_constraints=["don't touch the photos"])
        r = tv.verify([{"tool": "delete",
                        "args": {"path": "photos/vacation.jpg"}}])
        assert not r.passed
        assert any(f.flaw == "F8" for f in r.failures)

    def test_unrelated_action_passes(self):
        tv = v(user_constraints=["don't touch the photos"])
        r = tv.verify([{"tool": "notes_write",
                        "args": {"path": "todo.txt", "content": "x"}}])
        assert r.passed


class TestVerdict:
    def test_clean_trajectory_passes_all(self):
        tv = v(
            tool_schemas={"notes_write": {"required": ["path", "content"],
                                          "types": {"path": "str"}}},
            tool_tiers={"notes_write": 2},
            approved_tools={"notes_write"},
            scope_roots=["/data/notes"],
        )
        r = tv.verify([{"tool": "notes_write",
                        "args": {"path": "/data/notes/a.txt",
                                 "content": "hi"}}])
        assert r.passed and len(r.checks) == 8
