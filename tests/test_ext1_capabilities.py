"""Tests for jarvis.capabilities — live capability self-knowledge.

The map is built from the REAL SkillRegistry over copies of the shipped
skills, plus duck-typed fake records for the states discovery alone can't
produce (tripped breaker, disabled, changed manifest). Brain wiring tests
use the same fake style as tests/test_brain.py.
"""

from pathlib import Path

import pytest

from jarvis.capabilities import (
    AVAILABLE,
    BROKEN,
    DISABLED,
    QUARANTINED,
    build_capability_map,
    capabilities_provider_for,
    summary_text,
)
from jarvis.skills.registry import SkillRegistry


REPO_SKILLS = Path(__file__).resolve().parents[1] / "skills"


def _registry(tmp_path: Path, *skills: str) -> SkillRegistry:
    """Registry over copies of the real shipped skills."""
    import shutil

    dst = tmp_path / "skills"
    dst.mkdir()
    for s in skills:
        shutil.copytree(REPO_SKILLS / s, dst / s)
    data = tmp_path / "data"
    data.mkdir()
    reg = SkillRegistry(dst, data)
    reg.discover()
    return reg


# --------------------------------------------------------------------------- #
# build_capability_map — availability states from the real registry
# --------------------------------------------------------------------------- #
def test_unapproved_skill_is_quarantined(tmp_path):
    reg = _registry(tmp_path, "clock")
    cap_map = build_capability_map(reg)
    clock = cap_map.find_skill("clock")
    assert clock is not None
    assert clock.availability == QUARANTINED
    tool = cap_map.find_tool("now")
    assert tool is not None
    assert tool.availability == QUARANTINED
    assert tool.tier == 1
    assert "UTC" in tool.purpose  # one-liner from the manifest description
    assert cap_map.available_tools() == []


def test_approved_skill_is_available(tmp_path):
    reg = _registry(tmp_path, "clock", "echo")
    reg.approve("clock")
    cap_map = build_capability_map(reg)
    assert cap_map.find_skill("clock").availability == AVAILABLE
    assert [t.name for t in cap_map.available_tools()] == ["now"]
    # The unapproved sibling stays quarantined.
    assert cap_map.find_skill("echo").availability == QUARANTINED
    assert cap_map.tool_count() == 2


def test_changed_manifest_requarantines(tmp_path):
    reg = _registry(tmp_path, "clock")
    reg.approve("clock")
    rec = reg._records["clock"]
    rec.approved_hash = "stale-hash"  # manifest changed after approval
    cap_map = build_capability_map(reg)
    assert cap_map.find_skill("clock").availability == QUARANTINED


def test_tripped_circuit_breaker_is_broken(tmp_path):
    reg = _registry(tmp_path, "clock")
    reg.approve("clock")
    rec = reg._records["clock"]
    rec.failures = 3  # registry threshold -> circuit_open
    rec.enabled = False  # the trip also flips enabled off; broken wins
    cap_map = build_capability_map(reg)
    assert cap_map.find_skill("clock").availability == BROKEN


def test_disabled_skill_is_disabled_not_broken(tmp_path):
    reg = _registry(tmp_path, "clock")
    reg.approve("clock")
    reg._records["clock"].enabled = False
    cap_map = build_capability_map(reg)
    assert cap_map.find_skill("clock").availability == DISABLED


def test_load_error_is_broken(tmp_path):
    from jarvis.skills.registry import SkillManifestError

    skills = tmp_path / "skills"
    skills.mkdir()
    bad = skills / "bad"
    bad.mkdir()
    (bad / "skill.json").write_text('{"name": "bad", "bogus": 1}',
                                    encoding="utf-8")
    reg = SkillRegistry(skills, tmp_path / "data")
    records = reg.discover()
    assert records and isinstance(records[0].load_error, SkillManifestError)
    cap_map = build_capability_map(reg)
    bad_skill = cap_map.find_skill("bad")
    assert bad_skill is not None
    assert bad_skill.availability == BROKEN
    assert bad_skill.tools == ()


def test_missing_manifest_record_is_broken(tmp_path):
    from types import SimpleNamespace

    fake = SimpleNamespace(name="ghost", manifest=None, load_error=None,
                           approved=False, approved_hash="",
                           manifest_hash="", enabled=True, failures=0)
    cap_map = build_capability_map({"ghost": fake})  # dict-shaped registry
    assert cap_map.find_skill("ghost").availability == BROKEN


# --------------------------------------------------------------------------- #
# PC tools
# --------------------------------------------------------------------------- #
def test_pc_tools_form_their_own_group(tmp_path):
    from jarvis import pc_control

    reg = _registry(tmp_path, "clock")
    reg.approve("clock")
    cap_map = build_capability_map(reg, pc_control.tool_definitions())
    pc = cap_map.find_skill("pc")
    assert pc is not None and pc.availability == AVAILABLE
    observe = cap_map.find_tool("pc.observe")
    assert observe is not None
    assert observe.availability == AVAILABLE
    assert observe.tier == pc_control.TIER_READ
    assert cap_map.find_tool("pc.shell").tier == pc_control.TIER_SHELL


def test_pc_tools_accept_gate_registry_dict(tmp_path):
    from jarvis import pc_control

    cap_map = build_capability_map(None, pc_control.as_gate_registry())
    assert cap_map.find_tool("pc.click") is not None
    # Gate-registry entries carry no description -> purpose falls back empty.
    assert cap_map.find_tool("pc.click").purpose == ""


def test_empty_inputs_give_empty_map():
    cap_map = build_capability_map(None)
    assert cap_map.skills == ()
    assert cap_map.tool_count() == 0
    cap_map2 = build_capability_map(None, [])
    assert cap_map2.skills == ()


# --------------------------------------------------------------------------- #
# Fingerprint — the rebuild signal
# --------------------------------------------------------------------------- #
def test_fingerprint_stable_for_same_state(tmp_path):
    reg = _registry(tmp_path, "clock")
    a = build_capability_map(reg)
    b = build_capability_map(reg)
    assert a.fingerprint == b.fingerprint
    assert a.fingerprint != ""


def test_fingerprint_changes_on_approval_and_on_breaker_trip(tmp_path):
    reg = _registry(tmp_path, "clock")
    before = build_capability_map(reg).fingerprint
    reg.approve("clock")
    after_approve = build_capability_map(reg).fingerprint
    assert after_approve != before
    reg._records["clock"].failures = 3
    after_trip = build_capability_map(reg).fingerprint
    assert after_trip != after_approve


def test_provider_rebuilds_from_live_registry(tmp_path):
    reg = _registry(tmp_path, "clock")
    provider = capabilities_provider_for(reg)
    assert provider().find_skill("clock").availability == QUARANTINED
    reg.approve("clock")
    assert provider().find_skill("clock").availability == AVAILABLE


def test_map_to_dict_round_trip_shape(tmp_path):
    reg = _registry(tmp_path, "clock")
    d = build_capability_map(reg).to_dict()
    assert d["skills"][0]["name"] == "clock"
    assert d["skills"][0]["tools"][0]["name"] == "now"
    assert d["fingerprint"]


# --------------------------------------------------------------------------- #
# summary_text
# --------------------------------------------------------------------------- #
def test_summary_has_header_trust_line_and_groups(tmp_path):
    reg = _registry(tmp_path, "clock", "echo")
    reg.approve("clock")
    text = summary_text(build_capability_map(reg))
    assert text.startswith("## What you can do right now")
    assert ("These are verified live capabilities. "
            "Do not claim inability for anything listed.") in text
    assert "clock:" in text
    assert "- now — " in text and "(tier 1)" in text
    # The quarantined tool is named as unusable, not listed as usable.
    assert "Not usable right now:" in text
    assert "echo (quarantined)" in text


def test_summary_never_exceeds_max_chars(tmp_path):
    reg = _registry(tmp_path, "clock", "echo", "notes", "reminders",
                    "system", "web", "knowledge", "code")
    for name in ("clock", "echo", "notes", "reminders", "system", "web",
                 "knowledge", "code"):
        reg.approve(name)
    from jarvis import pc_control
    cap_map = build_capability_map(reg, pc_control.tool_definitions())
    for cap in (1200, 400, 200, 80):
        text = summary_text(cap_map, max_chars=cap)
        assert len(text) <= cap
    text = summary_text(cap_map, max_chars=400)
    assert "more capabilities" in text  # elision marker on overflow


def test_summary_of_empty_map_is_just_the_header():
    text = summary_text(build_capability_map(None))
    assert "## What you can do right now" in text
    assert "Do not claim inability" in text
    assert len(text) <= 1200


def test_summary_zero_max_chars():
    assert summary_text(build_capability_map(None), max_chars=0) == ""


# --------------------------------------------------------------------------- #
# Brain wiring
# --------------------------------------------------------------------------- #
from jarvis.brain import Brain, ToolDef  # noqa: E402
from jarvis.gate import GateDecision, Verdict  # noqa: E402


class _FakeGate:
    def check(self, tool_name, args, turn_allowances):
        return GateDecision(verdict=Verdict.ALLOW, reason="test")

    @staticmethod
    def wrap_output(output, source, trust="untrusted"):
        return f'<tool_output source="{source}" trust="{trust}">{output}</tool_output>'


class _FakeStore:
    def __init__(self):
        self.events = []
        self._n = 0

    def emit(self, session_id, type, payload, actor, trust="user",
             causal_parent=None, trace_id=None):
        self._n += 1
        ev_id = f"ev{self._n}"
        self.events.append({"event_id": ev_id, "session_id": session_id,
                            "type": type, "payload": payload,
                            "causal_parent": causal_parent, "actor": actor,
                            "trust": trust})
        return ev_id

    def get_events(self, session_id, limit=100):
        return [e for e in self.events if e["session_id"] == session_id][-limit:]


class _FakeRule:
    def __init__(self, text):
        self.text = text


class _FakeRules:
    def find(self, rule_id):
        texts = {
            "P2-1": 'Persona: calm British butler. Address Owais as "sir".',
            "P2-2": "Craftsman principle: verify before claiming.",
        }
        text = texts.get(rule_id)
        return _FakeRule(text) if text is not None else None


def _make_brain(provider=None):
    def llm(messages):
        llm.prompts.append(messages)
        return "Very good, sir."
    llm.prompts = []
    brain = Brain(
        gate=_FakeGate(),
        session_store=_FakeStore(),
        rules=_FakeRules(),
        llm_call=llm,
        tools=[ToolDef(name="now", description="Current time.",
                       parameters={}, fn=lambda args: "12:00")],
        capabilities_provider=provider,
    )
    return brain, llm


def test_brain_without_provider_has_no_capabilities_section():
    brain, _ = _make_brain()
    prompt = brain._system_prompt()
    assert "## What you can do right now" not in prompt
    assert "Available tools:" in prompt  # old behavior intact


def test_brain_prompt_carries_live_capabilities(tmp_path):
    reg = _registry(tmp_path, "clock")
    reg.approve("clock")
    brain, _ = _make_brain(capabilities_provider_for(reg))
    prompt = brain._system_prompt("sess-1")
    assert "## What you can do right now" in prompt
    assert "Do not claim inability for anything listed." in prompt
    assert "- now — " in prompt


def test_brain_capabilities_cache_rebuilds_only_on_change(tmp_path):
    reg = _registry(tmp_path, "clock")
    provider = capabilities_provider_for(reg)
    brain, _ = _make_brain(provider)
    first = brain._system_prompt("sess-1")
    second = brain._system_prompt("sess-1")
    assert first == second
    assert "echo" not in first
    # Live change (approval) flips the fingerprint -> next prompt rebuilds.
    reg.approve("clock")
    third = brain._system_prompt("sess-1")
    assert third != first
    assert "- now — " in third


def test_brain_survives_a_broken_provider():
    def exploding():
        raise RuntimeError("registry on fire")

    brain, _ = _make_brain(exploding)
    prompt = brain._system_prompt("sess-1")
    assert "## What you can do right now" not in prompt
    assert "Available tools:" in prompt


def test_brain_accepts_a_prerendered_string_provider():
    brain, _ = _make_brain(lambda: "## What you can do right now\n- everything")
    prompt = brain._system_prompt("sess-1")
    assert "- everything" in prompt


def test_full_turn_prompt_includes_capabilities(tmp_path):
    reg = _registry(tmp_path, "clock")
    reg.approve("clock")
    brain, llm = _make_brain(capabilities_provider_for(reg))
    result = brain.respond("sess-9", "what time is it?")
    assert result.status == "answered"
    system_msg = llm.prompts[0][0]
    assert system_msg["role"] == "system"
    assert "## What you can do right now" in system_msg["content"]
