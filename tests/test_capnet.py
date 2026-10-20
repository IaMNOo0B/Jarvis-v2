"""Tests for jarvis.capnet — the unified capability network.

Built over the REAL SkillRegistry (copies of the shipped skills), the
real pc_control tool table, duck-typed provider/MCP fakes, and a real
SessionStore for the outcome-feedback loop — the same fake style as
tests/test_ext1_capabilities.py.
"""

import shutil
from pathlib import Path
from types import SimpleNamespace

from jarvis.capabilities import AVAILABLE, BROKEN, QUARANTINED
from jarvis.capnet import (
    OUTCOME_EVENT_TYPE,
    build_network,
    describe,
    explain,
    health_scores,
    record_outcome,
    select,
)
from jarvis.pc_control import tool_definitions as pc_tool_definitions
from jarvis.session_store import SessionStore
from jarvis.skills.registry import SkillRegistry

REPO_SKILLS = Path(__file__).resolve().parents[1] / "skills"


def _registry(tmp_path: Path, *skills: str) -> SkillRegistry:
    dst = tmp_path / "skills"
    dst.mkdir()
    for s in skills:
        shutil.copytree(REPO_SKILLS / s, dst / s)
    data = tmp_path / "data"
    data.mkdir()
    reg = SkillRegistry(dst, data)
    reg.discover()
    return reg


def _providers(*names: str):
    return [SimpleNamespace(name=n) for n in names]


def _mcp_entry(server="fs", name="read_file", description="Read a file"):
    tool = SimpleNamespace(name=name, registry_name=name,
                           description=description)
    return SimpleNamespace(server=server, tool=tool, registry_name=name)


# --------------------------------------------------------------------------- #
# Build — every source becomes nodes; health is the registry's truth
# --------------------------------------------------------------------------- #
def test_network_covers_all_sources(tmp_path):
    reg = _registry(tmp_path, "clock", "web")
    reg.approve("clock")
    net = build_network(reg, pc_tools=pc_tool_definitions(),
                        providers=_providers("ollama", "groq"),
                        mcp_entries=[_mcp_entry()])
    kinds = {n.kind for n in net.nodes}
    assert {"tool", "pc", "provider", "mcp", "memory", "phone",
            "proactivity"} <= kinds

    now = net.node("tool:now")
    assert now is not None
    assert now.health == AVAILABLE
    assert now.group == "current_time"
    assert now.purpose  # one line from the manifest
    assert "time" in now.use_when

    web = net.node("tool:web_search")
    assert web is not None
    assert web.health == QUARANTINED  # unapproved skill, registry truth
    assert "network" in web.needs

    click = net.node("pc.click")
    assert click is not None and click.kind == "pc"
    assert "windows" in click.needs

    assert net.node("memory:recall") is not None
    assert net.node("phone:send_message") is not None
    assert net.node("proactivity:morning_digest") is not None
    assert net.fingerprint  # non-empty snapshot hash


def test_alternatives_share_a_job(tmp_path):
    reg = _registry(tmp_path, "web", "knowledge")
    net = build_network(reg, providers=_providers("ollama", "groq"))
    # Two ways to look something up = alternatives.
    assert "tool:knowledge_search" in net.node("tool:web_search").alternatives
    assert "tool:web_search" in net.node("tool:knowledge_search").alternatives
    # Providers are each other's alternatives (the FallbackChain idea).
    assert net.node("provider:ollama").alternatives == ("provider:groq",)
    assert net.node("provider:groq").alternatives == ("provider:ollama",)
    names = [n.name for n in net.alternatives_of("provider:ollama")]
    assert names == ["groq"]


def test_no_invented_alternatives_or_deps(tmp_path):
    reg = _registry(tmp_path, "clock")
    net = build_network(reg)
    now = net.node("tool:now")
    assert now.alternatives == ()  # alone in its job group
    assert all(n.depends_on == () for n in net.nodes)  # nothing declared


def test_declared_deps_are_honored():
    manifest = SimpleNamespace(
        description="fake",
        tools=[SimpleNamespace(name="t1", description="d", tier=1,
                               capabilities=())],
        depends_on=("tool:now",),
    )
    rec = SimpleNamespace(name="fake", manifest=manifest, load_error=None,
                          approved=True, approved_hash="h", manifest_hash="h",
                          enabled=True, failures=0)
    net = build_network({"fake": rec})
    node = net.node("tool:t1")
    assert node is not None
    assert node.depends_on == ("tool:now",)


def test_mcp_nodes_start_quarantined():
    net = build_network(None, mcp_entries=[_mcp_entry()])
    node = net.node("mcp:fs:read_file")
    assert node is not None
    assert node.kind == "mcp"
    assert node.health == QUARANTINED
    assert "external_server" in node.needs


def test_dead_provider_from_chain_stats_is_broken():
    chain = SimpleNamespace(
        providers=[SimpleNamespace(name="deadprov"),
                   SimpleNamespace(name="liveprov")],
        stats=lambda: {"deadprov": {"attempts": 5, "successes": 0,
                                    "failures": 5, "success_rate": 0.0}},
    )
    net = build_network(None, providers=chain)
    assert net.node("provider:deadprov").health == BROKEN
    assert net.node("provider:liveprov").health == AVAILABLE


# --------------------------------------------------------------------------- #
# The Router — deterministic judgment
# --------------------------------------------------------------------------- #
def test_router_picks_clock_for_time(tmp_path):
    reg = _registry(tmp_path, "clock", "web")
    reg.approve("clock")
    net = build_network(reg, providers=_providers("ollama"))
    plan = select(net, "what is the time right now")
    assert plan.chosen == "tool:now"
    assert plan.reason.startswith("chose tool:now")
    assert "healthy" in plan.reason


def test_router_excludes_quarantined_and_names_it(tmp_path):
    reg = _registry(tmp_path, "web")
    net = build_network(reg)
    plan = select(net, "search the web for the latest news")
    assert plan.chosen != "tool:web_search"
    excluded_ids = [nid for nid, _ in plan.excluded]
    assert "tool:web_search" in excluded_ids
    why = dict(plan.excluded)["tool:web_search"]
    assert "quarantined" in why


def test_router_cost_breaks_ties_local_first():
    net = build_network(None, providers=_providers("groq", "ollama"))
    plan = select(net, "answer this and think")
    assert plan.chosen == "provider:ollama"  # local beats paid on a tie
    assert plan.alternatives() == ("provider:groq",)


def test_router_deprioritizes_windows_nodes_off_windows(tmp_path):
    reg = _registry(tmp_path, "clock")
    net = build_network(reg, pc_tools=pc_tool_definitions())
    on_win = select(net, "click the ok button", platform="windows")
    off_win = select(net, "click the ok button", platform="linux")
    win_score = {s.node_id: s for s in on_win.ranked}["pc.click"].score
    off_score = {s.node_id: s for s in off_win.ranked}["pc.click"].score
    assert win_score > off_score
    notes = " ".join({s.node_id: s for s in off_win.ranked}["pc.click"].notes)
    assert "needs windows" in notes
    # Deprioritized, not hidden: still the chosen node here.
    assert off_win.chosen == "pc.click"


def test_router_health_first_off_keeps_with_warning(tmp_path):
    reg = _registry(tmp_path, "web")
    net = build_network(reg)
    plan = select(net, "search the web", health_first=False)
    ranked = {s.node_id: s for s in plan.ranked}
    assert "tool:web_search" in ranked
    assert "quarantined" in " ".join(ranked["tool:web_search"].notes)


def test_router_no_match_is_honest():
    net = build_network(None)
    plan = select(net, "zqxjkvb flibberty")
    assert plan.chosen is None
    assert "no capability" in plan.reason


# --------------------------------------------------------------------------- #
# Outcome feedback — measured failure sinks a node
# --------------------------------------------------------------------------- #
def test_feedback_loop_sinks_a_failing_node(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.db"))
    sid = store.create_session("owais", "test")
    try:
        for _ in range(6):
            ev = record_outcome(store, "provider:ollama", False,
                                "answer and think", session_id=sid)
            assert ev  # an event id came back
            record_outcome(store, "provider:groq", True,
                           "answer and think", session_id=sid)
        events = store.get_events(sid)
        assert any(e["type"] == OUTCOME_EVENT_TYPE for e in events)

        scores = health_scores(store, session_id=sid)
        assert scores["provider:ollama"]["success_rate"] == 0.0
        assert scores["provider:ollama"]["attempts"] == 6
        assert scores["provider:groq"]["success_rate"] == 1.0

        # Similarity filter: an unrelated task sees no record.
        assert health_scores(store, session_id=sid,
                             task_text="unrelated zebra") == {}
        similar = health_scores(store, session_id=sid,
                                task_text="think and answer")
        assert similar["provider:ollama"]["attempts"] == 6

        # The router takes the measured record over the cheaper node.
        net = build_network(None, providers=_providers("ollama", "groq"),
                            scores=scores)
        plan = select(net, "answer this and think")
        assert plan.chosen == "provider:groq"
        top = plan.ranked[0]
        assert "measured" in " ".join(top.notes)
    finally:
        store.close()


def test_health_scores_from_raw_events_and_single_node():
    events = [
        {"type": OUTCOME_EVENT_TYPE,
         "payload": {"node_id": "tool:now", "ok": True,
                     "task_tokens": ["time"]}},
        {"type": OUTCOME_EVENT_TYPE,
         "payload": {"node_id": "tool:now", "ok": False,
                     "task_tokens": ["time"]}},
        {"type": "something.else", "payload": {"node_id": "tool:now"}},
    ]
    scores = health_scores(events)
    assert scores["tool:now"]["attempts"] == 2
    assert scores["tool:now"]["success_rate"] == 0.5
    one = health_scores(events, "tool:now")
    assert list(one) == ["tool:now"]
    unseen = health_scores(events, "tool:ghost")
    assert unseen["tool:ghost"]["attempts"] == 0


def test_record_outcome_never_breaks_the_work():
    assert record_outcome(None, "tool:now", True) is None
    assert record_outcome(object(), "tool:now", True,
                          session_id="x") is None  # no emit -> no-op


# --------------------------------------------------------------------------- #
# Self-description
# --------------------------------------------------------------------------- #
def test_describe_and_explain(tmp_path):
    reg = _registry(tmp_path, "web", "knowledge", "clock")
    for s in ("web", "knowledge", "clock"):
        reg.approve(s)
    net = build_network(reg, providers=_providers("ollama"))
    text = describe(net)
    assert "Capability network" in text
    assert "information_lookup" in text
    assert "alternatives: web_search" in text
    assert len(text) <= 1600
    small = describe(net, max_chars=200)
    assert len(small) <= 200

    info = explain(net, "tool:web_search")
    assert "Search the web" in info
    assert "use when:" in info
    assert "needs: network" in info
    assert "tool:knowledge_search" in info  # the alternative, by id

    assert "not in the capability network" in explain(net, "tool:ghost")
