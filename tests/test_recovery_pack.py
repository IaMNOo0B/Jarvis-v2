"""Tests for the recovery pack: effect journal + undo (Team 29 /
PlanSys2), typed postconditions + recovery ladder (Team 22 / Team 29).

Load-bearing properties:
- Manifests may DECLARE effects/postconditions; undeclared tools journal
  nothing and are never contract-checked.
- existed_before is probed BEFORE execution — a file the tool created
  still journals existed_before=False.
- undo_turn reverses a multi-effect turn in REVERSE journal order and
  reports irreversible effects by name — never a blanket "undone".
- A failed postcondition flips the CompletionAudit to NOT delivered even
  when the tool claimed ok=True.
- The recovery ladder is retry(1) -> substitute -> escalate, and stops:
  escalation is terminal, the ladder cannot loop.

Uses the REAL SessionStore + REAL Memory. No network, no model.
"""

import pytest

from jarvis import contracts, effects
from jarvis.capnet import CapabilityNetwork, Node
from jarvis.completion_audit import audit_turn
from jarvis.gate import Gate, Verdict
from jarvis.memory import Memory
from jarvis.session_store import SessionStore
from jarvis.skills.registry import (
    SkillManifest,
    SkillManifestError,
    ToolDef,
)


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
@pytest.fixture
def store(tmp_path):
    s = SessionStore(str(tmp_path / "sessions.db"))
    sid = s.create_session("test", "test")
    return s, sid


@pytest.fixture
def memory(tmp_path):
    return Memory(str(tmp_path / "memory.db"))


def _tool_entry(**overrides):
    entry = {
        "name": "writer",
        "description": "writes a file",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"}},
                       "required": ["path"]},
        "capabilities": [],
        "tier": 2,
    }
    entry.update(overrides)
    return entry


# --------------------------------------------------------------------------- #
# 1. Manifest schema — effects / postconditions are declared, validated
# --------------------------------------------------------------------------- #
class TestManifestSchema:
    def test_effects_and_postconditions_parse(self):
        tool = ToolDef.from_dict(_tool_entry(
            effects=[{"kind": "file", "target": "{args.path}"}],
            postconditions=[{"check": "file_exists", "target": "{args.path}"},
                            {"check": "tool_ok"}],
        ), source="test")
        assert tool.effects[0]["kind"] == "file"
        assert [p["check"] for p in tool.postconditions] == [
            "file_exists", "tool_ok"]

    def test_undeclared_tool_has_empty_contracts(self):
        tool = ToolDef.from_dict(_tool_entry(), source="test")
        assert tool.effects == () and tool.postconditions == ()

    @pytest.mark.parametrize("bad", [
        {"kind": "everything", "target": "x"},          # unknown kind
        {"kind": "file"},                               # missing target
        {"kind": "file", "target": ""},                 # empty target
        {"kind": "file", "target": "x", "surprise": 1},  # unknown key
        {"kind": "file", "target": "x", "existed_before": "yes"},  # not bool
    ])
    def test_bad_effects_rejected(self, bad):
        with pytest.raises(SkillManifestError):
            ToolDef.from_dict(_tool_entry(effects=[bad]), source="test")

    @pytest.mark.parametrize("bad", [
        {"check": "file_vanished", "target": "x"},      # unknown check
        {"check": "file_exists"},                       # target required
        {"check": "fact_exists", "target": 7},           # target must be str
    ])
    def test_bad_postconditions_rejected(self, bad):
        with pytest.raises(SkillManifestError):
            ToolDef.from_dict(_tool_entry(postconditions=[bad]), source="test")

    def test_tool_ok_needs_no_target(self):
        tool = ToolDef.from_dict(
            _tool_entry(postconditions=[{"check": "tool_ok"}]), source="test")
        assert tool.postconditions[0]["check"] == "tool_ok"

    def test_contract_change_retriggers_quarantine_hash(self):
        base = SkillManifest.from_dict({
            "name": "s", "version": "1.0.0", "description": "",
            "capabilities": [], "tools": [_tool_entry()],
        }, source="test")
        with_fx = SkillManifest.from_dict({
            "name": "s", "version": "1.0.0", "description": "",
            "capabilities": [],
            "tools": [_tool_entry(
                effects=[{"kind": "file", "target": "{args.path}"}])],
        }, source="test")
        assert base.canonical_hash() != with_fx.canonical_hash()

    def test_get_tool_exposes_contracts(self, tmp_path):
        from jarvis.skills.registry import SkillRegistry
        reg = SkillRegistry(tmp_path / "skills", tmp_path / "data")
        reg.register({
            "name": "s", "version": "1.0.0", "description": "",
            "capabilities": [],
            "tools": [_tool_entry(
                effects=[{"kind": "fact", "target": "k"}],
                postconditions=[{"check": "fact_exists", "target": "k"}])],
        }, tmp_path / "skills" / "s")
        tool = reg.get_tool("writer")
        assert tool["effects"] == [{"kind": "fact", "target": "k"}]
        assert tool["postconditions"] == [
            {"check": "fact_exists", "target": "k"}]


# --------------------------------------------------------------------------- #
# 2. Effect resolution — templates + honest pre-state probes
# --------------------------------------------------------------------------- #
class TestEffectResolution:
    def test_template_resolution(self, tmp_path):
        recs = effects.prepare_effects(
            [{"kind": "file", "target": "{args.path}"}],
            {"path": "a.txt"}, fs_root=tmp_path)
        assert recs[0]["target"] == "a.txt"
        assert recs[0]["target_resolved"] is True
        assert recs[0]["existed_before"] is False

    def test_existed_before_probed_from_prestate(self, tmp_path):
        (tmp_path / "old.txt").write_text("x", encoding="utf-8")
        recs = effects.prepare_effects(
            [{"kind": "file", "target": "old.txt"}], {}, fs_root=tmp_path)
        assert recs[0]["existed_before"] is True

    def test_declared_existed_before_wins(self, tmp_path):
        recs = effects.prepare_effects(
            [{"kind": "file", "target": "ghost.txt", "existed_before": True}],
            {}, fs_root=tmp_path)
        assert recs[0]["existed_before"] is True

    def test_unresolvable_template_is_honest(self, tmp_path):
        recs = effects.prepare_effects(
            [{"kind": "file", "target": "{args.nope}"}],
            {"path": "a.txt"}, fs_root=tmp_path)
        assert recs[0]["target_resolved"] is False
        assert recs[0]["existed_before"] is None

    def test_fact_probe(self, memory):
        memory.write_fact("owner.city", "Pune", source="test",
                          tier="user", confidence=0.9)
        probe = lambda k: memory.get_fact(k) is not None  # noqa: E731
        recs = effects.prepare_effects(
            [{"kind": "fact", "target": "owner.city"},
             {"kind": "fact", "target": "owner.absent"}],
            {}, fact_exists=probe)
        assert [r["existed_before"] for r in recs] == [True, False]


# --------------------------------------------------------------------------- #
# 3. Gate journaling — dispatch records declared effects, nothing invented
# --------------------------------------------------------------------------- #
def _gate(store, fs_root, registry, **kw):
    return Gate(skill_registry=registry,
                effect_sink=effects.make_store_sink(store),
                effect_fs_root=str(fs_root), **kw)


_WRITE_REGISTRY = {
    "notes.write": {
        "tier": 2, "capabilities": [],
        "schema": {"required": ["path"],
                   "properties": {"path": {"type": "str"}}},
        "effects": [{"kind": "file", "target": "{args.path}"}],
    },
    "plain.tool": {
        "tier": 1, "capabilities": [],
        "schema": {"required": [], "properties": {}},
    },
}


class TestGateJournaling:
    def test_created_file_journals_existed_before_false(self, store, tmp_path):
        s, sid = store

        def executor(name, args):
            (tmp_path / args["path"]).write_text("new", encoding="utf-8")
            return {"written": True}

        gate = _gate(s, tmp_path, _WRITE_REGISTRY)
        decision, out = gate.dispatch("notes.write", {"path": "a.txt"}, [],
                                      executor, session_id=sid, turn_id=7)
        assert decision.verdict is Verdict.ALLOW_WITH_UNDO
        assert out is not None
        journal = effects.journal_for_turn(s, sid, 7)
        assert len(journal) == 1
        rec = journal[0]
        # The file EXISTS now — but the probe ran before execution.
        assert rec["existed_before"] is False
        assert rec["target"] == "a.txt" and rec["tool"] == "notes.write"

    def test_overwrite_journals_bak_as_restore_source(self, store, tmp_path):
        s, sid = store
        (tmp_path / "a.txt").write_text("original", encoding="utf-8")

        def executor(name, args):  # the code skill's .bak discipline
            old = (tmp_path / "a.txt").read_text(encoding="utf-8")
            (tmp_path / "a.txt.bak").write_text(old, encoding="utf-8")
            (tmp_path / "a.txt").write_text("changed", encoding="utf-8")
            return {"written": True, "backed_up": True}

        gate = _gate(s, tmp_path, _WRITE_REGISTRY)
        gate.dispatch("notes.write", {"path": "a.txt"}, [], executor,
                      session_id=sid, turn_id=3)
        rec = effects.journal_for_turn(s, sid, 3)[0]
        assert rec["existed_before"] is True
        assert rec["before_value_ref"] == "a.txt.bak"

    def test_undeclared_tool_journals_nothing(self, store, tmp_path):
        s, sid = store
        gate = _gate(s, tmp_path, _WRITE_REGISTRY)
        gate.dispatch("plain.tool", {}, [], lambda n, a: {"ok": True},
                      session_id=sid, turn_id=1)
        assert effects.journal_for_turn(s, sid, 1) == []

    def test_denied_call_journals_nothing(self, store, tmp_path):
        s, sid = store
        gate = _gate(s, tmp_path, _WRITE_REGISTRY)
        decision, _ = gate.dispatch("notes.write", {}, [],  # missing arg
                                     lambda n, a: {"ok": True},
                                     session_id=sid, turn_id=1)
        assert decision.verdict is Verdict.DENY
        assert effects.journal_for_turn(s, sid, 1) == []

    def test_broken_sink_never_blocks_dispatch(self, store, tmp_path):
        def bad_sink(message):
            raise RuntimeError("sink exploded")

        gate = Gate(skill_registry=_WRITE_REGISTRY, effect_sink=bad_sink,
                    effect_fs_root=str(tmp_path))
        decision, out = gate.dispatch(
            "notes.write", {"path": "a.txt"}, [],
            lambda n, a: {"written": True},
            session_id="whatever", turn_id=1)
        assert decision.verdict is Verdict.ALLOW_WITH_UNDO
        assert out is not None

    def test_tier3_approved_execution_journals(self, store, tmp_path):
        s, sid = store
        registry = {"vault.open": {
            "tier": 3, "capabilities": [],
            "schema": {"required": ["path"],
                       "properties": {"path": {"type": "str"}}},
            "effects": [{"kind": "file", "target": "{args.path}"}],
        }}
        gate = _gate(s, tmp_path, registry)
        decision = gate.check("vault.open", {"path": "v.txt"}, [])
        assert decision.verdict is Verdict.REQUIRE_APPROVAL
        token = decision.approval_request["token"]
        done, _ = gate.execute_approved(
            token, "vault.open", {"path": "v.txt"},
            lambda n, a: {"opened": True}, session_id=sid, turn_id=9)
        assert done.verdict is Verdict.ALLOW
        journal = effects.journal_for_turn(s, sid, 9)
        assert len(journal) == 1 and journal[0]["target"] == "v.txt"


# --------------------------------------------------------------------------- #
# 4. Undo — reverse order, honest about what cannot be reversed
# --------------------------------------------------------------------------- #
class TestUndoTurn:
    def _build_turn(self, store, memory, tmp_path):
        s, sid = store
        # Post-turn world state:
        (tmp_path / "created.txt").write_text("fresh", encoding="utf-8")
        (tmp_path / "edited.txt").write_text("changed", encoding="utf-8")
        (tmp_path / "edited.txt.bak").write_text("original", encoding="utf-8")
        (tmp_path / "lost.txt").write_text("changed", encoding="utf-8")
        memory.write_fact("owner.nickname", "Ovi", source="test",
                          tier="user", confidence=0.9)
        journal = [
            {"kind": "file", "target": "created.txt", "target_resolved": True,
             "existed_before": False, "before_value_ref": None},
            {"kind": "file", "target": "edited.txt", "target_resolved": True,
             "existed_before": True, "before_value_ref": "edited.txt.bak"},
            {"kind": "fact", "target": "owner.nickname",
             "target_resolved": True, "existed_before": False,
             "before_value_ref": None},
            {"kind": "reminder", "target": "rem-1", "target_resolved": True,
             "existed_before": False, "before_value_ref": None},
            {"kind": "file", "target": "lost.txt", "target_resolved": True,
             "existed_before": True, "before_value_ref": "lost.txt.bak"},
            {"kind": "setting", "target": "voice.volume",
             "target_resolved": True, "existed_before": True,
             "before_value_ref": None},
        ]
        for rec in journal:
            rec.setdefault("tool", "some.tool")
        effects.record_effects(s, sid, 42, "some.tool", journal)
        # A stray record from another turn must not be touched.
        effects.record_effects(s, sid, 99, "some.tool", [
            {"kind": "file", "target": "created.txt", "target_resolved": True,
             "existed_before": True, "before_value_ref": None, "tool": "x"}])
        return s, sid

    def test_multi_effect_turn_reversed_in_order(self, store, memory, tmp_path):
        s, sid = self._build_turn(store, memory, tmp_path)
        cancelled = []

        def canceller(rid):
            cancelled.append(rid)
            return {"cancelled": True}

        report = effects.undo_turn(
            s, sid, 42, memory=memory, fs_root=tmp_path,
            reminder_cancel=canceller)
        assert report["total"] == 6
        assert report["ok"] is False  # two effects cannot be reversed
        # Reverse journal order: setting(fail), lost(fail), reminder,
        # fact, edited, created.
        assert [e["target"] for e in report["reversed"]] == [
            "rem-1", "owner.nickname", "edited.txt", "created.txt"]
        assert {e["target"] for e in report["not_reversed"]} == {
            "lost.txt", "voice.volume"}
        reasons = {e["target"]: e["reason"] for e in report["not_reversed"]}
        assert "snapshot missing" in reasons["lost.txt"]
        assert "manually" in reasons["voice.volume"]
        # The world is actually back:
        assert not (tmp_path / "created.txt").exists()
        assert (tmp_path / "edited.txt").read_text(
            encoding="utf-8") == "original"
        assert memory.get_fact("owner.nickname") is None
        assert cancelled == ["rem-1"]
        # The undo itself is on the record.
        kinds = [ev["type"] for ev in s.get_events(sid, limit=1000)]
        assert "effect.undo_report" in kinds

    def test_undo_without_memory_handle_is_honest(self, store, memory,
                                                  tmp_path):
        s, sid = self._build_turn(store, memory, tmp_path)
        report = effects.undo_turn(s, sid, 42, memory=None, fs_root=tmp_path,
                                   reminder_cancel=lambda rid: True)
        fact = [e for e in report["not_reversed"]
                if e["kind"] == "fact"]
        assert fact and "no memory handle" in fact[0]["reason"]
        # ...and the fact is still there (nothing pretended to remove it).
        assert memory.get_fact("owner.nickname") is not None

    def test_fully_reversible_turn_reports_ok(self, store, tmp_path):
        s, sid = store
        (tmp_path / "only.txt").write_text("x", encoding="utf-8")
        effects.record_effects(s, sid, 5, "t", [
            {"kind": "file", "target": "only.txt", "target_resolved": True,
             "existed_before": False, "before_value_ref": None, "tool": "t"}])
        report = effects.undo_turn(s, sid, 5, fs_root=tmp_path)
        assert report["ok"] is True and report["total"] == 1
        assert not (tmp_path / "only.txt").exists()


# --------------------------------------------------------------------------- #
# 5. Postconditions — verified against state, audit flips on failure
# --------------------------------------------------------------------------- #
class TestPostconditions:
    def test_file_exists_pass_and_fail(self, tmp_path):
        (tmp_path / "made.txt").write_text("x", encoding="utf-8")
        declared = [{"check": "file_exists", "target": "{args.path}"}]
        ok = contracts.evaluate_postconditions(
            declared, {"path": "made.txt"}, result_ok=True, fs_root=tmp_path)
        assert ok["passed"] is True
        bad = contracts.evaluate_postconditions(
            declared, {"path": "missing.txt"}, result_ok=True, fs_root=tmp_path)
        assert bad["passed"] is False
        assert bad["failures"][0]["check"] == "file_exists"

    def test_fact_checks_against_real_memory(self, memory):
        memory.write_fact("a.b", "1", source="t", tier="user", confidence=1.0)
        rep = contracts.evaluate_postconditions(
            [{"check": "fact_exists", "target": "a.b"},
             {"check": "fact_absent", "target": "a.c"},
             {"check": "tool_ok"}],
            {}, result_ok=True, memory=memory)
        assert rep["passed"] is True
        rep2 = contracts.evaluate_postconditions(
            [{"check": "fact_absent", "target": "a.b"}], {},
            result_ok=True, memory=memory)
        assert rep2["passed"] is False

    def test_tool_ok_uses_the_tools_own_report(self):
        rep = contracts.evaluate_postconditions(
            [{"check": "tool_ok"}], {}, result_ok=False)
        assert rep["passed"] is False

    def test_no_declarations_is_vacuously_passed(self):
        rep = contracts.evaluate_postconditions([], {}, result_ok=False)
        assert rep["passed"] is True and rep["declared"] == 0

    def test_mark_result_stamps_without_mutating(self):
        payload = {"ok": True, "output": "done"}
        report = {"passed": False, "failures": [
            {"check": "file_exists", "target": "x.txt"}]}
        marked = contracts.mark_result(payload, report)
        assert marked["postcondition_failed"] is True
        assert marked["postcondition_failures"] == ["file_exists:x.txt"]
        assert "postcondition_failed" not in payload  # original untouched
        clean = contracts.mark_result(payload, {"passed": True})
        assert "postcondition_failed" not in clean

    def test_gate_hook_emits_typed_failure(self, store, tmp_path):
        s, sid = store
        captured = []
        registry = {"maker": {
            "tier": 1, "capabilities": [],
            "schema": {"required": ["path"],
                       "properties": {"path": {"type": "str"}}},
            "postconditions": [{"check": "file_exists",
                                "target": "{args.path}"}],
        }}
        gate = Gate(
            skill_registry=registry,
            postcondition_evaluator=contracts.make_evaluator(
                fs_root=tmp_path),
            contract_sink=captured.append)
        # The tool CLAIMS success but never creates the file.
        decision, _ = gate.dispatch("maker", {"path": "ghost.txt"}, [],
                                    lambda n, a: {"ok": True},
                                    session_id=sid, turn_id=1)
        assert decision.verdict is Verdict.ALLOW  # dispatch itself worked
        assert len(captured) == 1
        assert captured[0]["event"] == "postcondition_failed"
        assert captured[0]["report"]["failures"][0]["check"] == "file_exists"
        # And when the file really appears, no failure is recorded.
        captured.clear()
        gate.dispatch("maker", {"path": "real.txt"}, [],
                      lambda n, a: (tmp_path / "real.txt").write_text(
                          "x", encoding="utf-8") or {"ok": True},
                      session_id=sid, turn_id=2)
        assert captured == []

    def test_audit_flips_on_postcondition_failure(self, store):
        s, sid = store
        s.emit(sid, "user.message", {"text": "do it"}, actor="user")
        report = {"passed": False, "failures": [
            {"check": "file_exists", "target": "x.txt"}]}
        payload = contracts.mark_result({"ok": True, "output": "done"},
                                        report)
        s.emit(sid, "tool.result", payload, actor="tool",
               trust="tool_untrusted")
        s.emit(sid, "brain.reply", {"text": "Done, sir."}, actor="brain")
        out = audit_turn(s, sid)
        assert out["delivered"] is False
        assert out["postcondition_failures"] == 1
        assert "postcondition" in out["reason"]

    def test_audit_still_delivers_clean_success(self, store):
        s, sid = store
        s.emit(sid, "user.message", {"text": "do it"}, actor="user")
        s.emit(sid, "tool.result", {"ok": True, "output": "done"},
               actor="tool", trust="tool_untrusted")
        s.emit(sid, "brain.reply", {"text": "Done, sir."}, actor="brain")
        out = audit_turn(s, sid)
        assert out["delivered"] is True
        assert out["postcondition_failures"] == 0


# --------------------------------------------------------------------------- #
# 6. Recovery ladder — retry -> substitute -> escalate, then STOP
# --------------------------------------------------------------------------- #
def _network(alt_health="available"):
    a = Node(id="tool:writer_a", kind="tool", name="writer_a",
             purpose="write things", group="writing",
             alternatives=("tool:writer_b",))
    b = Node(id="tool:writer_b", kind="tool", name="writer_b",
             purpose="write things", group="writing", health=alt_health)
    return CapabilityNetwork(nodes=(a, b))


_FAILURE = {"tool": "writer_a", "kind": "postcondition_failed",
            "detail": "file_exists: out.txt"}


class TestRecoveryLadder:
    def test_first_failure_retries(self):
        out = contracts.recover(_FAILURE, {"history": []})
        assert out["action"] == "retry" and out["rung"] == 1

    def test_second_failure_substitutes(self):
        out = contracts.recover(_FAILURE, {"history": ["retry"],
                                           "network": _network()})
        assert out["action"] == "substitute"
        assert out["substitute"] == "writer_b"

    def test_unusable_alternative_escalates(self):
        out = contracts.recover(_FAILURE, {
            "history": ["retry"], "network": _network(alt_health="broken")})
        assert out["action"] == "escalate"

    def test_no_network_skips_substitute(self):
        out = contracts.recover(_FAILURE, {"history": ["retry"]})
        assert out["action"] == "escalate"

    def test_non_retryable_kind_skips_rung_one(self):
        out = contracts.recover(
            {"tool": "writer_a", "kind": "gate_denied", "detail": "tier-3"},
            {"history": []})
        assert out["action"] == "escalate"

    def test_escalation_is_terminal(self):
        out = contracts.recover(_FAILURE, {
            "history": ["retry", "substitute", "escalate"],
            "network": _network()})
        assert out["action"] == "escalate"

    def test_ladder_walks_and_stops(self):
        # Simulate a caller obeying the ladder: it must terminate at
        # escalate in exactly 3 steps and never revisit a rung.
        history, actions = [], []
        for _ in range(10):  # generous bound — must stop long before
            step = contracts.recover(_FAILURE, {
                "history": history, "network": _network(),
                "events": []})
            actions.append(step["action"])
            if step["action"] == "escalate":
                break
            history.append(step["action"])
        assert actions == ["retry", "substitute", "escalate"]

    def test_causal_summary_is_one_line_with_facts(self):
        events = [
            {"type": "tool.result",
             "payload": {"ok": False, "postcondition_failed": True}},
            {"type": "effect.recorded", "payload": {}},
            {"type": "effect.recorded", "payload": {}},
        ]
        line = contracts.causal_summary(events, _FAILURE)
        assert "\n" not in line
        assert "writer_a" in line and "postcondition_failed" in line
        assert "1 tool failure" in line and "2 effect" in line
        escalate = contracts.recover(_FAILURE, {
            "history": ["retry", "substitute"], "events": events})
        assert escalate["summary"] == line
