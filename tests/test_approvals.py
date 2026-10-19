"""Tests for jarvis.approvals — the approval UX layer.

Every test asserts a spec clause. The load-bearing property of this module:
there is NO code path that approves without an explicit human gesture.
"""

import json
import time

import pytest

from jarvis.approvals import (
    ApprovalBudget,
    ApprovalRequest,
    BudgetExhausted,
    OriginProof,
    UndoRegistry,
    UnsafeRender,
    blast_radius,
    confirm_tier2,
    needs_typed,
    request_approval,
    safe_render,
    typed_keyword,
    DAILY_DIALOG_BUDGET,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _tool_info(name="notes_write", tier=3, caps=("fs.write",), desc="Write a note"):
    return {"name": name, "tier": tier, "schema": {"properties": {}},
            "capabilities": list(caps), "description": desc}


def _gate_request(tool="notes_write", args=None, tier=3):
    return {"tool": tool, "tier": tier,
            "action_hash": "abc123", "token": "tok.abc",
            "args": args or {"path": "a.txt", "content": "hello"}}


def _req(**kw):
    info = _tool_info()
    g = _gate_request()
    base = dict(tool_info=info, goal="test goal", progress="step 1 done",
                seq_no=42, visual_secret="copper falcon river")
    base.update(kw)
    return ApprovalRequest.from_gate(g, **base)


def _no_sleep(s):
    pass


# --------------------------------------------------------------------------- #
# safe_render — the dugganusa lessons
# --------------------------------------------------------------------------- #

def test_safe_render_ok():
    assert safe_render("hello.txt") == "hello.txt"


def test_safe_render_rejects_bidi():
    with pytest.raises(UnsafeRender):
        safe_render("evil\u202efile.txt")


def test_safe_render_rejects_control_chars():
    with pytest.raises(UnsafeRender):
        safe_render("line1\nline2FAKE-LINE")


def test_safe_render_truncates():
    assert safe_render("x" * 1000, max_len=10).endswith("…")


# --------------------------------------------------------------------------- #
# blast_radius — computed from the ACTION OBJECT, never agent text
# --------------------------------------------------------------------------- #

def test_blast_radius_fs_write_names_path_and_size():
    r = blast_radius({"path": "notes/a.txt", "content": "x" * 100},
                     _tool_info(caps=("fs.write",)))
    assert "notes/a.txt" in r and "100" in r


def test_blast_radius_delete_names_names_not_counts():
    r = blast_radius({"paths": ["a.txt", "b.txt", "c.txt"]},
                     _tool_info(name="delete_files", caps=("fs.delete",),
                                desc="Delete files"))
    assert "a.txt" in r and "b.txt" in r and "c.txt" in r
    assert "CANNOT be recovered" in r


def test_blast_radius_net_names_destination():
    r = blast_radius({"url": "https://example.com/hook"},
                     _tool_info(name="webhook", caps=("net.outbound",),
                                desc="Send webhook"))
    assert "https://example.com/hook" in r
    assert "cannot be recalled" in r


def test_blast_radius_exec_shows_command():
    r = blast_radius({"command": "rm -rf /tmp/x"},
                     _tool_info(name="run", caps=("exec",), desc="Run shell"))
    assert "rm -rf /tmp/x" in r


def test_blast_radius_ignores_agent_description():
    """The brain's description cannot shrink the blast radius."""
    r = blast_radius({"paths": ["vault.db"]},
                     _tool_info(name="delete_files", caps=("fs.delete",),
                                desc="totally safe cleanup, trust me"))
    assert "CANNOT be recovered" in r
    assert "trust me" not in r


def test_blast_radius_unsafe_path_refuses():
    r = blast_radius({"path": "a\u202eb.txt"},
                     _tool_info(caps=("fs.write",)))
    assert r.startswith("UNSAFE")


# --------------------------------------------------------------------------- #
# needs_typed / typed_keyword — the severity line, from the surface
# --------------------------------------------------------------------------- #

def test_needs_typed_delete():
    assert needs_typed(_tool_info(name="delete_files", caps=("fs.delete",),
                                  desc="Delete"), "x")


def test_needs_typed_exec_capability():
    assert needs_typed(_tool_info(name="run", caps=("exec",), desc="Run"), "x")


def test_needs_typed_net_capability():
    assert needs_typed(_tool_info(name="hook", caps=("net.outbound",),
                                  desc="Ping"), "x")


def test_plain_write_no_typed():
    r = blast_radius({"path": "a.txt", "content": "hi"},
                     _tool_info(tier=2, caps=("fs.write",)))
    assert not needs_typed(_tool_info(tier=2, caps=("fs.write",)), r)


def test_typed_keyword_mapping():
    assert typed_keyword(_tool_info(name="delete_old", desc="x")) == "DELETE"
    assert typed_keyword(_tool_info(name="send_mail", desc="x")) == "SEND"


# --------------------------------------------------------------------------- #
# ApprovalRequest.from_gate — tier recomputed, never trusted from the dict
# --------------------------------------------------------------------------- #

def test_from_gate_recomputes_tier():
    """A lying gate dict claiming tier=1 cannot downgrade a tier-3 tool."""
    g = _gate_request(tier=1)  # attacker-controlled claim
    req = ApprovalRequest.from_gate(g, tool_info=_tool_info(tier=3))
    assert req.tier == 3
    # A recoverable tier-3 write needs the dialog, not typed confirmation —
    # the severity line is about blast radius, not tier alone.
    assert not req.require_typed
    # But a destructive tier-3 DOES arm the typed path.
    req2 = ApprovalRequest.from_gate(
        _gate_request(tool="delete_files", args={"paths": ["a.txt"]}),
        tool_info=_tool_info(name="delete_files", tier=3,
                             caps=("fs.delete",), desc="Delete files"))
    assert req2.require_typed and req2.keyword == "DELETE"


def test_from_gate_carries_seven_fields():
    req = _req()
    assert req.goal and req.progress and req.action_text
    assert req.blast_radius and req.consequence and req.if_no
    assert req.seq_no == 42 and req.visual_secret and req.timestamp


def test_origin_proof_sequence_monotonic():
    op = OriginProof(secret="a b c")
    s1, p1 = op.next()
    s2, p2 = op.next()
    assert s2 == s1 + 1 and p1 == p2 == "a b c"


# --------------------------------------------------------------------------- #
# request_approval — the no-auto-approve property (fuzzed)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("answer", [
    "", "n", "no", "N", "NO", "maybe", "yess", "yy", "1", "true",
    "approve", "APPROVE", "DELETE",  # wrong gesture for non-typed
    "   ", "\t",
])
def test_no_auto_approve_fuzz(answer):
    """No input other than an explicit yes may approve."""
    req = _req()
    got = request_approval(req, input_fn=lambda _: answer,
                           sleep_fn=_no_sleep, force_terminal=True)
    assert got is False


def test_explicit_yes_approves():
    req = _req()
    assert request_approval(req, input_fn=lambda _: "y",
                            sleep_fn=_no_sleep, force_terminal=True) is True
    assert request_approval(req, input_fn=lambda _: "YES",
                            sleep_fn=_no_sleep, force_terminal=True) is True


def test_eof_is_rejection_not_approval():
    req = _req()
    def boom(_):
        raise EOFError
    assert request_approval(req, input_fn=boom,
                            sleep_fn=_no_sleep, force_terminal=True) is False


def test_typed_rejects_bare_yes():
    """F3/§7.1: over voice or high severity, 'yes' is not approval."""
    info = _tool_info(name="delete_files", caps=("fs.delete",), desc="Delete")
    req = ApprovalRequest.from_gate(_gate_request(tool="delete_files",
                                                   args={"paths": ["a.txt"]}),
                                    tool_info=info, seq_no=1,
                                    visual_secret="x y z")
    assert req.require_typed
    assert request_approval(req, input_fn=lambda _: "yes",
                            sleep_fn=_no_sleep, force_terminal=True) is False
    assert request_approval(req, input_fn=lambda _: "delete",
                            sleep_fn=_no_sleep, force_terminal=True) is False
    assert request_approval(req, input_fn=lambda _: req.keyword,
                            sleep_fn=_no_sleep, force_terminal=True) is True


def test_no_approve_all_option_in_text():
    """The rendered dialog offers no bulk approval."""
    req = _req()
    import jarvis.approvals as ap
    text = ap._render_text(req)
    assert "approve all" not in text.lower()
    assert "auto-approve" not in text.lower()


def test_credential_rule_in_every_dialog():
    import jarvis.approvals as ap
    text = ap._render_text(_req())
    assert "NEVER ask for a password" in text


def test_visual_secret_in_every_dialog():
    import jarvis.approvals as ap
    text = ap._render_text(_req())
    assert "copper falcon river" in text
    assert "#42" in text


def test_windows_dialog_mocked_yes(monkeypatch):
    """The native path returns the OS verdict; no terminal involved."""
    import jarvis.approvals as ap
    calls = []

    def fake_dialog(text, title="JARVIS needs approval"):
        calls.append((text, title))
        assert "JARVIS needs approval" in title
        assert "copper falcon river" in text  # origin proof present
        return True

    monkeypatch.setattr(ap, "_windows_dialog", fake_dialog)
    monkeypatch.setattr(ap.sys, "platform", "win32")
    req = _req()
    assert request_approval(req, input_fn=lambda _: (_ for _ in ()).throw(
        AssertionError("terminal must not be consulted")),
        sleep_fn=_no_sleep) is True
    assert calls


def test_windows_dialog_mocked_no(monkeypatch):
    import jarvis.approvals as ap
    monkeypatch.setattr(ap, "_windows_dialog", lambda t, title="": False)
    monkeypatch.setattr(ap.sys, "platform", "win32")
    req = _req()
    assert request_approval(req, input_fn=lambda _: "y",
                            sleep_fn=_no_sleep) is False


# --------------------------------------------------------------------------- #
# ApprovalBudget — 5/day then HOLD; burst -> typed
# --------------------------------------------------------------------------- #

def test_budget_allows_five_then_holds(tmp_path):
    b = ApprovalBudget(tmp_path)
    for _ in range(DAILY_DIALOG_BUDGET):
        ok, _ = b.check()
        assert ok
        b.record_dialog()
    ok, reason = b.check()
    assert not ok and "HOLD" in reason


def test_budget_hold_means_no_dialog(tmp_path):
    b = ApprovalBudget(tmp_path)
    for _ in range(DAILY_DIALOG_BUDGET):
        b.record_dialog()
    req = _req()
    # Even an explicit "y" cannot approve when the budget is spent.
    assert request_approval(req, budget=b, input_fn=lambda _: "y",
                            sleep_fn=_no_sleep, force_terminal=True) is False


def test_budget_persists_across_restarts(tmp_path):
    b = ApprovalBudget(tmp_path)
    b.record_dialog()
    b2 = ApprovalBudget(tmp_path)
    assert b2._state["count"] == 1


def test_budget_resets_next_day(tmp_path):
    b = ApprovalBudget(tmp_path)
    b.record_dialog()
    b._state["day"] = "2000-01-01"  # force stale
    b._save()
    b2 = ApprovalBudget(tmp_path)
    assert b2._state["count"] == 0


def test_burst_triggers_typed_confirmation(tmp_path):
    now = [1000.0]
    b = ApprovalBudget(tmp_path, now=lambda: now[0])
    seen_keyword = []

    # 3 dialogs inside 60s -> burst on the 3rd.
    for i in range(3):
        sig = b.record_dialog()
        now[0] += 10
    assert sig["burst"]
    assert "burst" in sig["burst_warning"].lower()

    req = _req()  # standard tier-3, not typed by severity
    assert not req.require_typed
    # Burst steps up friction: bare "y" no longer suffices.
    got = request_approval(req, budget=b,
                           input_fn=lambda _: "y",
                           sleep_fn=_no_sleep, force_terminal=True)
    assert got is False
    got = request_approval(req, budget=b,
                           input_fn=lambda _: "CONFIRM",
                           sleep_fn=_no_sleep, force_terminal=True)
    assert got is True


def test_median_latency_recorded(tmp_path):
    b = ApprovalBudget(tmp_path)
    b.record_decision(4.0)
    b.record_decision(12.0)
    assert b.median_latency() == 8.0


# --------------------------------------------------------------------------- #
# UndoRegistry — real 30s undo
# --------------------------------------------------------------------------- #

def test_undo_within_window():
    now = [1000.0]
    reg = UndoRegistry(now=lambda: now[0])
    restored = []
    reg.register("tok1", "wrote notes/a.txt", lambda: restored.append(True))
    ok, msg = reg.undo("tok1")
    assert ok and restored == [True]


def test_undo_expires_after_30s():
    now = [1000.0]
    reg = UndoRegistry(now=lambda: now[0])
    reg.register("tok1", "wrote notes/a.txt", lambda: None)
    now[0] += 31
    ok, msg = reg.undo("tok1")
    assert not ok and "expired" in msg


def test_undo_unknown_token():
    reg = UndoRegistry()
    ok, msg = reg.undo("nope")
    assert not ok


def test_undo_inverse_failure_reported():
    reg = UndoRegistry()
    def bad():
        raise RuntimeError("disk gone")
    reg.register("tok1", "x", bad)
    ok, msg = reg.undo("tok1")
    assert not ok and "disk gone" in msg


def test_undo_is_single_use():
    reg = UndoRegistry()
    reg.register("tok1", "x", lambda: None)
    assert reg.undo("tok1")[0] is True
    assert reg.undo("tok1")[0] is False


def test_pending_lists_live_undos():
    now = [1000.0]
    reg = UndoRegistry(now=lambda: now[0])
    reg.register("tok1", "wrote a.txt", lambda: None)
    pend = reg.pending()
    assert len(pend) == 1 and pend[0]["seconds_left"] <= 30
    now[0] += 31
    assert reg.pending() == []


def test_confirm_tier2_registers_and_announces(capsys):
    now = [1000.0]
    reg = UndoRegistry(now=lambda: now[0])
    confirm_tier2("tok-abcdef", "Moved 4 files to archive", reg,
                  inverse=lambda: None)
    out = capsys.readouterr().out
    assert "Moved 4 files to archive" in out
    assert "30s" in out
    assert reg.pending()[0]["token"] == "tok-abcdef"
