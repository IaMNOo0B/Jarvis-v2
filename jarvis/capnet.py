"""jarvis.capnet — the unified capability network.

Wiring modules together is not enough. JARVIS must (1) KNOW every
capability it has, (2) UNDERSTAND each one — what it is for, when to
use it, when NOT to, what it needs and what it costs — (3) ROUTE tasks
through the network with judgment — right tool, right place, right
time — and (4) LEARN from outcomes which nodes actually deliver.

This module is that network. It builds ON jarvis.capabilities (the
live capability map supplies skill/PC nodes and their health — never
duplicated here) and generalizes the brain FallbackChain's measured
routing (stats -> suggested order) to EVERY capability in the system.

Pieces:

  - :class:`Node` — one capability: a skill tool, a PC tool, an MCP
    tool, an LLM provider, a memory store, a phone action, the
    proactivity digest. Fields carry purpose, use_when / avoid_when,
    needs (network / approval / windows / ...), cost_hint, live health
    and alternatives (other nodes serving the same job).
  - :func:`build_network` — pure aggregation over the registry, PC
    tool table, provider chain and MCP entries. Edges are honest:
    alternative-to comes from shared purpose groups; depends-on only
    from declarations in the source data — never invented.
  - :func:`select` — the Router. Deterministic scoring, NO LLM:
    purpose/keyword match, health (broken / quarantined / disabled are
    excluded and the exclusion is NAMED), needs vs current context (a
    Windows node on a non-Windows runtime is deprioritized, not
    hidden), cost preference on ties (local/free before paid/cloud),
    and measured outcome scores as the final tie-break. The returned
    :class:`SelectionPlan` explains itself in plain language.
  - :func:`record_outcome` / :func:`health_scores` — the feedback
    loop: outcomes land in the session store as ``capnet.outcome``
    events; success rates are derived from that log (the FallbackChain
    stats pattern), optionally restricted to tasks similar to the one
    at hand, so a node that keeps failing at similar work sinks.
  - :func:`describe` / :func:`explain` — the network describing
    itself: a compact map for the brain prompt (capabilities summary +
    alternatives + routing hints) and a per-node briefing.

Stdlib only. Python 3.11+.
"""

from __future__ import annotations

import hashlib
import json
import platform as _platform_module
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from jarvis.capabilities import (
    AVAILABLE,
    BROKEN,
    DISABLED,
    QUARANTINED,
    build_capability_map,
)

__all__ = [
    "AVAILABLE",
    "QUARANTINED",
    "DISABLED",
    "BROKEN",
    "OUTCOME_EVENT_TYPE",
    "Node",
    "CapabilityNetwork",
    "ScoredNode",
    "SelectionPlan",
    "build_network",
    "select",
    "record_outcome",
    "health_scores",
    "describe",
    "explain",
]

OUTCOME_EVENT_TYPE = "capnet.outcome"

# Node kinds (closed vocabulary).
KIND_TOOL = "tool"
KIND_PC = "pc"
KIND_MCP = "mcp"
KIND_PROVIDER = "provider"
KIND_MEMORY = "memory"
KIND_PHONE = "phone"
KIND_PROACTIVITY = "proactivity"

# Cost preference: lower wins ties. local/free before paid/cloud is the
# owner's standing rule (the chain is smartest-first for QUALITY, but
# when two nodes serve the same job equally well, the cheap one goes).
COST_RANK = {"local": 0, "free": 1, "slow": 2, "external": 2,
             "network": 3, "paid": 4}
_UNKNOWN_COST_RANK = 3

# Health states that cannot serve a task right now.
_UNUSABLE = (BROKEN, QUARANTINED, DISABLED)

# A provider with this many measured attempts and zero successes is
# treated as broken by the network (mirrors circuit-breaker thinking).
_PROVIDER_DEAD_ATTEMPTS = 3

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_STOPWORDS = frozenset({
    "the", "a", "an", "of", "to", "for", "and", "or", "in", "on", "is",
    "it", "this", "that", "with", "from", "by", "as", "at", "be",
    "returns", "return", "current", "given", "using", "used", "use",
})


def _tokens(text: Any) -> frozenset:
    """Normalized content tokens of a text (script-safe, Hinglish-safe)."""
    words = _WORD_RE.findall(str(text or "").lower())
    return frozenset(w for w in words if len(w) >= 2 and w not in _STOPWORDS)


def _one_line(text: Any, limit: int = 120) -> str:
    line = " ".join(str(text or "").split())
    if len(line) > limit:
        line = line[: limit - 1].rstrip() + "…"
    return line


# --------------------------------------------------------------------------- #
# Node model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Node:
    """One capability in the network — something JARVIS can DO."""
    id: str                       # "tool:now", "provider:ollama", ...
    kind: str                     # KIND_* vocabulary
    name: str                     # tool/provider/subsystem name
    purpose: str                  # one line: what it is for
    group: str                    # purpose group (alternatives share it)
    use_when: Tuple[str, ...] = ()    # keywords/phrases signalling the job
    avoid_when: Tuple[str, ...] = ()  # when NOT to reach for it
    needs: Tuple[str, ...] = ()       # network / approval / windows / ...
    cost_hint: str = "local"          # COST_RANK vocabulary
    tier: int = 0                     # gate tier (0 = not gate-routed)
    health: str = AVAILABLE           # capabilities vocabulary
    alternatives: Tuple[str, ...] = ()  # node ids serving the same job
    depends_on: Tuple[str, ...] = ()    # declared deps only, never invented


@dataclass(frozen=True)
class CapabilityNetwork:
    """An immutable snapshot of the whole capability network."""
    nodes: Tuple[Node, ...] = ()
    fingerprint: str = ""
    scores: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def node(self, node_id: str) -> Optional[Node]:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def find(self, name: str) -> Optional[Node]:
        """Look a node up by bare name (e.g. "now", "ollama")."""
        for n in self.nodes:
            if n.name == name:
                return n
        return None

    def groups(self) -> Tuple[str, ...]:
        return tuple(sorted({n.group for n in self.nodes}))

    def by_group(self, group: str) -> Tuple[Node, ...]:
        return tuple(n for n in self.nodes if n.group == group)

    def alternatives_of(self, node_id: str) -> Tuple[Node, ...]:
        node = self.node(node_id)
        if node is None:
            return ()
        return tuple(self.node(a) for a in node.alternatives
                     if self.node(a) is not None)

    def usable(self) -> Tuple[Node, ...]:
        return tuple(n for n in self.nodes if n.health == AVAILABLE)


# --------------------------------------------------------------------------- #
# Purpose groups, keywords, needs — derivation tables
#
# Groups decide who is an alternative to whom, so they are curated for
# the shipped tools and extended by conservative name heuristics for
# unknown tools. A tool we know nothing about lands in its own skill
# group with NO alternatives — the network never invents kinship.
# --------------------------------------------------------------------------- #
_GROUP_BY_TOOL = {
    "now": "current_time",
    "web_search": "information_lookup",
    "knowledge_search": "information_lookup",
    "web_fetch": "page_reading",
    "web_fetch_tree": "page_reading",
    "notes_read": "notes",
    "notes_list": "notes",
    "notes_write": "notes",
    "reminder_set": "reminders",
    "reminder_list": "reminders",
    "reminder_cancel": "reminders",
    "reminder_due": "reminders",
    "code_read": "code",
    "code_write": "code",
    "code_edit": "code",
    "code_run": "code",
    "system_status": "system_info",
    "volume_get": "volume",
    "volume_set": "volume",
    "brightness_get": "brightness",
    "brightness_set": "brightness",
    "clipboard_get": "clipboard",
    "clipboard_set": "clipboard",
    "window_list": "windows",
    "echo": "echo",
}

# Extra routing knowledge for tools whose names/descriptions alone
# undersell when they should (or should not) be reached for.
_TOOL_INTEL = {
    "now": {
        "use_when": ("time", "date", "clock", "samay", "what time",
                     "aaj ki date", "day today"),
        "avoid_when": ("for times in other places or zones — it reports "
                       "this machine's clock only",),
    },
    "web_search": {
        "use_when": ("search", "web", "internet", "news", "latest",
                     "current events", "look up online", "google"),
        "avoid_when": ("when the answer lives in the owner's own library "
                       "or memory — search those first",
                       "when offline"),
    },
    "knowledge_search": {
        "use_when": ("research", "studies", "library", "notes from research",
                     "what did we learn", "playbook"),
        "avoid_when": ("for fresh external facts — this library is only "
                       "as new as its last study",),
    },
    "web_fetch": {
        "use_when": ("fetch", "read page", "open url", "article", "webpage"),
        "avoid_when": ("when offline",),
    },
    "web_fetch_tree": {
        "use_when": ("page structure", "element tree", "page elements",
                     "form fields", "buttons on the page",
                     "structured page", "inspect the page"),
        "avoid_when": ("when only the readable text is needed — "
                       "web_fetch is the lighter read",
                       "when offline"),
    },
    "code_run": {
        "use_when": ("run code", "execute", "test the script", "chala ke dekho"),
        "avoid_when": ("for anything needing network or shell access — "
                       "the sandbox has neither",),
    },
}

_PC_GROUPS = {
    "pc.observe": "screen_read",
    "pc.screenshot": "screen_read",
    "pc.click": "gui_control",
    "pc.type": "gui_control",
    "pc.key": "gui_control",
    "pc.launch_app": "app_launch",
    "pc.find_text": "screen_read",
}

# Providers that run on the owner's own machine / LAN.
_LOCAL_PROVIDERS = frozenset({"ollama", "omniroute"})
_FREE_PROVIDERS = frozenset({"pollinations"})


def _group_for_tool(name: str, skill_name: str) -> str:
    if name in _GROUP_BY_TOOL:
        return _GROUP_BY_TOOL[name]
    if name.endswith("_search"):
        return "information_lookup"
    return f"skill:{skill_name}"


def _needs_for(caps: Tuple[str, ...], tier: int) -> Tuple[str, ...]:
    needs: List[str] = []
    if "net.outbound" in caps:
        needs.append("network")
    if tier >= 3:
        needs.append("approval")
    elif tier == 2:
        needs.append("undo")  # tier-2: allowed, but must be undoable
    return tuple(needs)


def _avoid_for(needs: Tuple[str, ...], tier: int) -> Tuple[str, ...]:
    avoid: List[str] = []
    if "network" in needs:
        avoid.append("when offline")
    if "approval" in needs:
        avoid.append("for casual questions — it needs the owner's approval")
    if "windows" in needs:
        avoid.append("on non-Windows systems")
    return tuple(avoid)


def _keywords(name: str, purpose: str, extra: Tuple[str, ...]) -> Tuple[str, ...]:
    words = set(_tokens(name.replace("_", " "))) | set(_tokens(purpose))
    out = sorted(words)
    for phrase in extra:
        if phrase not in out:
            out.append(phrase)
    return tuple(out)


# --------------------------------------------------------------------------- #
# Node construction per source
# --------------------------------------------------------------------------- #
def _declared_tool_caps(registry: Any) -> Dict[str, Tuple[str, ...]]:
    """{tool name: declared manifest capabilities} from registry records.

    The capability map deliberately omits raw capabilities; needs
    (network / approval) are derived from what the manifest DECLARED,
    so we read them off the records directly (duck-typed, no I/O).
    """
    out: Dict[str, Tuple[str, ...]] = {}
    records: List[Any] = []
    if registry is None:
        return out
    if isinstance(registry, dict):
        records = list(registry.values())
    else:
        recs = getattr(registry, "_records", None)
        if isinstance(recs, dict):
            records = list(recs.values())
    for rec in records:
        manifest = getattr(rec, "manifest", None)
        for tool in getattr(manifest, "tools", ()) or ():
            caps = getattr(tool, "capabilities", ()) or ()
            if caps:
                out[str(getattr(tool, "name", ""))] = tuple(str(c) for c in caps)
    return out


def _skill_nodes(cap_map: Any,
                 tool_caps: Dict[str, Tuple[str, ...]]) -> List[Node]:
    """Skill + PC nodes from the live capability map (health included)."""
    nodes: List[Node] = []
    for skill in cap_map.skills:
        for tool in skill.tools:
            if skill.name == "pc":
                kind = KIND_PC
                nid = tool.name if tool.name.startswith("pc.") \
                    else f"pc:{tool.name}"
                group = _PC_GROUPS.get(tool.name, "pc_control")
                needs = ("windows",) + _needs_for((), tool.tier)
                intel = {}
            else:
                kind, nid = KIND_TOOL, f"tool:{tool.name}"
                group = _group_for_tool(tool.name, skill.name)
                needs = _needs_for(tool_caps.get(tool.name, ()), tool.tier)
                intel = _TOOL_INTEL.get(tool.name, {})
            nodes.append(Node(
                id=nid,
                kind=kind,
                name=tool.name,
                purpose=tool.purpose,
                group=group,
                use_when=_keywords(tool.name, tool.purpose,
                                   tuple(intel.get("use_when", ()))),
                avoid_when=tuple(intel.get("avoid_when", ()))
                           + _avoid_for(needs, tool.tier),
                needs=needs,
                cost_hint="local",
                tier=tool.tier,
                health=tool.availability,
            ))
    return nodes


def _manifest_declared_deps(registry: Any) -> Dict[str, Tuple[str, ...]]:
    """depends-on edges, ONLY where the source data declares them.

    Skill manifests today declare no dependency field (the registry's
    strict schema has none), so this normally returns {}. If a record
    or manifest ever exposes ``depends_on`` / ``requires``, it is
    honored verbatim — the network never guesses an edge.
    """
    deps: Dict[str, Tuple[str, ...]] = {}
    records: List[Any] = []
    if registry is None:
        return deps
    if isinstance(registry, dict):
        records = list(registry.values())
    else:
        recs = getattr(registry, "_records", None)
        if isinstance(recs, dict):
            records = list(recs.values())
    for rec in records:
        manifest = getattr(rec, "manifest", None)
        declared = None
        for holder in (rec, manifest):
            if holder is None:
                continue
            for attr in ("depends_on", "requires"):
                val = getattr(holder, attr, None)
                if val:
                    declared = tuple(str(v) for v in val)
                    break
            if declared:
                break
        if not declared:
            continue
        for tool in getattr(manifest, "tools", ()) or ():
            deps[f"tool:{tool.name}"] = declared
    return deps


def _provider_rows(providers: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Normalize the providers argument to (rows, stats-by-name).

    Accepts: a FallbackChain (or anything with .providers + .stats()),
    a list of provider objects/dicts, a {name: stats} dict, or None.
    """
    if providers is None:
        return [], {}
    stats_fn = getattr(providers, "stats", None)
    chain_providers = getattr(providers, "providers", None)
    if chain_providers is not None:
        stats = stats_fn() if callable(stats_fn) else {}
        return [({"name": getattr(p, "name", str(p))}) for p in chain_providers], \
            stats or {}
    if isinstance(providers, dict):
        return [{"name": name} for name in sorted(providers)], dict(providers)
    rows: List[Dict[str, Any]] = []
    for p in providers:
        if isinstance(p, dict):
            rows.append({"name": str(p.get("name", "?"))})
        else:
            rows.append({"name": str(getattr(p, "name", p))})
    return rows, {}


def _provider_nodes(providers: Any) -> List[Node]:
    rows, stats = _provider_rows(providers)
    nodes: List[Node] = []
    for row in rows:
        name = row["name"]
        lname = name.lower()
        if lname in _LOCAL_PROVIDERS:
            cost, needs = "local", ()
            purpose = f"LLM provider {name} — runs on this machine"
        elif lname in _FREE_PROVIDERS:
            cost, needs = "free", ("network",)
            purpose = f"LLM provider {name} — free cloud, no key"
        else:
            cost, needs = "paid", ("network",)
            purpose = f"LLM provider {name} — cloud, uses an API key"
        health = AVAILABLE
        s = stats.get(name) or {}
        if int(s.get("attempts", 0) or 0) >= _PROVIDER_DEAD_ATTEMPTS \
                and int(s.get("successes", 0) or 0) == 0:
            health = BROKEN
        nodes.append(Node(
            id=f"provider:{name}",
            kind=KIND_PROVIDER,
            name=name,
            purpose=purpose,
            group="brain",
            use_when=("answer", "think", "reason", "reply", "chat", "explain",
                      "likho", "batao", "samjhao"),
            avoid_when=_avoid_for(needs, 0),
            needs=needs,
            cost_hint=cost,
            tier=0,
            health=health,
        ))
    return nodes


def _mcp_entries_of(mcp_entries: Any) -> List[Any]:
    if mcp_entries is None:
        return []
    entries = getattr(mcp_entries, "entries", None)
    if isinstance(entries, dict):
        return [entries[k] for k in sorted(entries)]
    if isinstance(mcp_entries, dict):
        return [mcp_entries[k] for k in sorted(mcp_entries)]
    try:
        return list(mcp_entries)
    except TypeError:
        return []


def _mcp_nodes(mcp_entries: Any) -> List[Node]:
    nodes: List[Node] = []
    for entry in _mcp_entries_of(mcp_entries):
        tool = getattr(entry, "tool", None)
        server = str(getattr(entry, "server", "?"))
        reg_name = str(getattr(entry, "registry_name", None)
                       or getattr(tool, "registry_name", "")
                       or getattr(tool, "name", "?"))
        description = _one_line(getattr(tool, "description", ""))
        purpose = description or f"External MCP tool {reg_name} (server {server})"
        nodes.append(Node(
            id=f"mcp:{server}:{reg_name}",
            kind=KIND_MCP,
            name=reg_name,
            purpose=purpose,
            group=_group_for_tool(reg_name, f"mcp:{server}")
            if reg_name.endswith("_search") else f"mcp:{server}",
            use_when=_keywords(reg_name, purpose, ()),
            avoid_when=("until the owner approves it — external tools start "
                        "quarantined",),
            needs=("external_server",),
            cost_hint="external",
            tier=2,
            # The bridge registers tools as quarantined skills; the
            # owner approves before anything external may run.
            health=QUARANTINED,
        ))
    return nodes


def _core_nodes() -> List[Node]:
    """JARVIS's own subsystems — memory, phone, proactivity.

    These are not skills; they are organs. They exist in every build,
    so the network always carries them (health: available).
    """
    return [
        Node(
            id="memory:recall", kind=KIND_MEMORY, name="memory.recall",
            purpose="Recall facts about the owner from long-term memory",
            group="recall",
            use_when=("remember", "recall", "memory", "yaad", "meri pasand",
                      "what do you know about me", "bhool gaya"),
            avoid_when=("for fresh external facts — memory only holds "
                        "what was stored",),
            needs=(), cost_hint="local", tier=1, health=AVAILABLE,
        ),
        Node(
            id="memory:write_fact", kind=KIND_MEMORY, name="memory.write_fact",
            purpose="Store a durable fact in long-term memory",
            group="remember",
            use_when=("remember this", "note that", "save this", "yaad rakho",
                      "bhoolna mat"),
            avoid_when=("for one-off chatter — memory is for what lasts",),
            needs=(), cost_hint="local", tier=2, health=AVAILABLE,
        ),
        Node(
            id="phone:send_message", kind=KIND_PHONE, name="phone.send_message",
            purpose="Send a message to the owner's phone (Telegram)",
            group="notify_owner",
            use_when=("phone", "message me", "notify", "telegram", "text me",
                      "phone pe bhejo"),
            avoid_when=("when the owner is at this machine — just answer here",),
            needs=("network",), cost_hint="network", tier=2, health=AVAILABLE,
        ),
        Node(
            id="proactivity:morning_digest", kind=KIND_PROACTIVITY,
            name="proactivity.morning_digest",
            purpose="Compose the morning briefing (reminders, yesterday, disk)",
            group="briefing",
            use_when=("briefing", "digest", "morning", "aaj ka plan",
                      "summary of today"),
            avoid_when=(),
            needs=(), cost_hint="local", tier=1, health=AVAILABLE,
        ),
    ]


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def _fingerprint(nodes: Tuple[Node, ...]) -> str:
    canonical = [
        {"id": n.id, "health": n.health, "tier": n.tier, "group": n.group}
        for n in nodes
    ]
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def build_network(registry: Any, pc_tools: Any = None,
                  providers: Any = None, mcp_entries: Any = None,
                  *, scores: Optional[Dict[str, Dict[str, Any]]] = None
                  ) -> CapabilityNetwork:
    """Aggregate every capability source into one network.

    ``registry`` / ``pc_tools`` feed jarvis.capabilities (live health).
    ``providers``: FallbackChain, provider list, or {name: stats}.
    ``mcp_entries``: an McpClient, its entries dict, or entry objects.
    ``scores``: optional outcome stats (see :func:`health_scores`)
    carried on the network for the router / describe / explain.
    Pure aggregation — no skill code runs, no disk is touched.
    """
    cap_map = build_capability_map(registry, pc_tools)
    raw: List[Node] = []
    raw.extend(_skill_nodes(cap_map, _declared_tool_caps(registry)))
    raw.extend(_provider_nodes(providers))
    raw.extend(_mcp_nodes(mcp_entries))
    raw.extend(_core_nodes())

    declared_deps = _manifest_declared_deps(registry)

    # Alternatives: every other node in the same purpose group.
    by_group: Dict[str, List[str]] = {}
    for n in raw:
        by_group.setdefault(n.group, []).append(n.id)
    nodes: List[Node] = []
    for n in raw:
        alts = tuple(sorted(i for i in by_group[n.group] if i != n.id))
        deps = declared_deps.get(n.id, ())
        if alts == n.alternatives and deps == n.depends_on:
            nodes.append(n)
        else:
            nodes.append(replace(n, alternatives=alts, depends_on=deps))
    frozen = tuple(sorted(nodes, key=lambda n: n.id))
    return CapabilityNetwork(
        nodes=frozen,
        fingerprint=_fingerprint(frozen),
        scores=dict(scores or {}),
    )


# --------------------------------------------------------------------------- #
# The Router — deterministic judgment, no LLM
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ScoredNode:
    node_id: str
    score: float
    notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SelectionPlan:
    """The router's answer: what to use, what else could serve, why."""
    task: str
    chosen: Optional[str]                 # node id, or None = no match
    ranked: Tuple[ScoredNode, ...] = ()   # candidates, best first
    excluded: Tuple[Tuple[str, str], ...] = ()  # (node id, why)
    reason: str = ""

    def chosen_node(self, network: CapabilityNetwork) -> Optional[Node]:
        return network.node(self.chosen) if self.chosen else None

    def alternatives(self) -> Tuple[str, ...]:
        return tuple(s.node_id for s in self.ranked[1:])


def _current_platform() -> str:
    return "windows" if _platform_module.system() == "Windows" else "other"


def _match_score(node: Node, task_text: str, task_tokens: frozenset,
                 notes: List[str]) -> float:
    score = 0.0
    hits: List[str] = []
    for kw in node.use_when:
        kw_tokens = _tokens(kw)
        if not kw_tokens:
            continue
        if len(kw_tokens) > 1:
            if kw_tokens <= task_tokens:
                score += 3.0
                hits.append(kw)
        elif kw in task_tokens:
            score += 2.0
            hits.append(kw)
    name_tokens = _tokens(node.name.replace("_", " ").replace(".", " "))
    named = sorted(name_tokens & task_tokens)
    for _ in named[:2]:
        score += 1.0
    if node.name and node.name.lower() in task_text.lower():
        score += 4.0
        hits.append(f"named directly: {node.name}")
        hits = [h for h in hits if h not in name_tokens]
    overlap = len(_tokens(node.purpose) & task_tokens)
    if overlap:
        score += min(1.0, 0.25 * overlap)
    if hits:
        notes.append("match: " + ", ".join(sorted(set(hits))[:4]))
    return score


def select(network: CapabilityNetwork, task_text: str, *,
           health_first: bool = True,
           platform: Optional[str] = None,
           online: Optional[bool] = None,
           scores: Optional[Dict[str, Dict[str, Any]]] = None
           ) -> SelectionPlan:
    """Route a task to the best node in the network. Deterministic.

    Scoring, in order of importance:
      1. purpose/keyword match with the task text;
      2. health — with ``health_first`` (default) broken / quarantined
         / disabled nodes are EXCLUDED and the exclusion is named in
         the plan; with it off they are kept but crushed to the bottom
         with a warning note;
      3. needs vs context — a node needing Windows on another platform
         (or the network while known-offline) keeps its candidacy but
         is deprioritized with the reason noted, never hidden;
      4. measured outcomes — success rates from the outcome log break
         near-ties; a node failing repeatedly at similar work sinks;
      5. cost — local/free beat paid/cloud when scores tie.
    """
    task = str(task_text or "")
    task_tokens = _tokens(task)
    platform = (platform or _current_platform()).lower()
    stats = scores if scores is not None else network.scores

    scored: List[ScoredNode] = []
    excluded: List[Tuple[str, str]] = []

    for node in network.nodes:
        if node.health in _UNUSABLE:
            if health_first:
                excluded.append((node.id, f"{node.id}: excluded — {node.health}"))
                continue
            notes = [f"warning: {node.health} (health_first off)"]
            s = _match_score(node, task, task_tokens, notes) * 0.05
            scored.append(ScoredNode(node.id, round(s, 3), tuple(notes)))
            continue

        notes: List[str] = []
        s = _match_score(node, task, task_tokens, notes)
        if "windows" in node.needs and platform != "windows":
            s *= 0.25
            notes.append("deprioritized: needs windows, this is not windows")
        if "network" in node.needs and online is False:
            s *= 0.1
            notes.append("deprioritized: needs network, currently offline")
        st = stats.get(node.id) if stats else None
        if st and int(st.get("attempts", 0) or 0) > 0:
            rate = float(st.get("success_rate", 0.0) or 0.0)
            attempts = int(st.get("attempts", 0) or 0)
            # Small nudge only — outcomes break ties, they don't pick
            # the tool. A repeat failure at real volume sinks harder.
            s += (rate - 0.5) * 0.5
            if attempts >= 5 and rate < 0.3:
                s -= 1.0
                notes.append(
                    f"measured: failing ({st.get('successes', 0)}/{attempts} ok)")
            else:
                notes.append(
                    f"measured: {st.get('successes', 0)}/{attempts} ok")
        if s > 0:
            notes.append(f"cost: {node.cost_hint}")
            scored.append(ScoredNode(node.id, round(s, 3), tuple(notes)))

    scored.sort(key=lambda sn: (
        -sn.score,
        COST_RANK.get(_cost_of(network, sn.node_id), _UNKNOWN_COST_RANK),
        sn.node_id,
    ))

    if scored and scored[0].score > 0:
        chosen = scored[0].node_id
    else:
        chosen = None

    reason = _plan_reason(network, task, chosen, scored, excluded)
    return SelectionPlan(
        task=task,
        chosen=chosen,
        ranked=tuple(scored),
        excluded=tuple(sorted(excluded)),
        reason=reason,
    )


def _cost_of(network: CapabilityNetwork, node_id: str) -> str:
    node = network.node(node_id)
    return node.cost_hint if node else "network"


def _plan_reason(network: CapabilityNetwork, task: str,
                 chosen: Optional[str], scored: List[ScoredNode],
                 excluded: List[Tuple[str, str]]) -> str:
    if chosen is None:
        base = "no capability in the network matches this task"
        if excluded:
            base += "; " + "; ".join(why for _, why in excluded[:2])
        return base + " — the brain should answer directly or ask."
    top = scored[0]
    node = network.node(chosen)
    bits = [f"chose {chosen}"]
    detail: List[str] = []
    if top.notes:
        detail.append(top.notes[0])  # match line
    if node is not None:
        if node.health == AVAILABLE:
            detail.append("healthy")
        detail.append(f"cost {node.cost_hint}")
        if node.needs:
            detail.append("needs " + ", ".join(node.needs))
    if detail:
        bits.append("(" + "; ".join(detail) + ")")
    if len(scored) > 1:
        runner = scored[1]
        bits.append(
            f"next best {runner.node_id} (score {runner.score:g} "
            f"vs {top.score:g})")
    named_skips = [why for nid, why in excluded
                   if network.node(nid) is not None
                   and network.node(nid).group == (node.group if node else "")]
    if named_skips:
        bits.append("skipped " + "; ".join(named_skips))
    elif excluded:
        bits.append(f"{len(excluded)} unusable node(s) excluded")
    return "; ".join(bits)


# --------------------------------------------------------------------------- #
# Outcome feedback — the FallbackChain stats pattern, generalized
# --------------------------------------------------------------------------- #
def task_tokens_of(text: str) -> List[str]:
    return sorted(_tokens(text))


def record_outcome(store: Any, node_id: str, ok: bool,
                   task_hint: str = "", *,
                   session_id: Optional[str] = None) -> Optional[str]:
    """Write one ``capnet.outcome`` event to the session store.

    ``store`` is a jarvis.session_store.SessionStore (duck-typed:
    anything with ``emit(session_id, type, payload, actor)``).
    ``session_id`` is required by the real store; without one (or
    without a store) this is a no-op returning None — outcomes are
    telemetry, they must never break the work they measure.
    Returns the event id, or None.
    """
    if store is None or session_id is None:
        return None
    emit = getattr(store, "emit", None)
    if not callable(emit):
        return None
    payload = {
        "node_id": str(node_id),
        "ok": bool(ok),
        "task_hint": str(task_hint or "")[:200],
        "task_tokens": task_tokens_of(task_hint),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    try:
        return emit(session_id, OUTCOME_EVENT_TYPE, payload,
                    actor="brain", trust="system")
    except Exception:
        return None


def _events_of(source: Any, session_id: Optional[str]) -> List[Dict[str, Any]]:
    if source is None:
        return []
    if isinstance(source, (list, tuple)):
        return [e for e in source if isinstance(e, dict)]
    get_events = getattr(source, "get_events", None)
    if callable(get_events) and session_id is not None:
        try:
            return list(get_events(session_id, 0, 100000))
        except TypeError:
            return list(get_events(session_id))
    return []


def health_scores(source: Any, node_id: Optional[str] = None, *,
                  session_id: Optional[str] = None,
                  task_text: Optional[str] = None
                  ) -> Dict[str, Dict[str, Any]]:
    """Success rates per node, derived from ``capnet.outcome`` events.

    ``source``: a SessionStore (+ ``session_id``) or an iterable of
    event dicts (as returned by SessionStore.get_events). With
    ``task_text``, only outcomes whose recorded task shares at least
    one content token with it count — "failing at SIMILAR work" is
    what sinks a node in the router. Returns the FallbackChain.stats
    shape: {node_id: {attempts, successes, failures, success_rate}}.
    With ``node_id``, returns just that node's row (zeros if unseen).
    """
    wanted = _tokens(task_text) if task_text else None
    out: Dict[str, Dict[str, Any]] = {}
    for event in _events_of(source, session_id):
        if event.get("type") != OUTCOME_EVENT_TYPE:
            continue
        payload = event.get("payload") or {}
        nid = payload.get("node_id")
        if not nid:
            continue
        if wanted is not None:
            past = set(payload.get("task_tokens") or [])
            if not past & wanted:
                continue
        row = out.setdefault(nid, {"attempts": 0, "successes": 0,
                                   "failures": 0, "success_rate": 0.0})
        row["attempts"] += 1
        if payload.get("ok"):
            row["successes"] += 1
        else:
            row["failures"] += 1
    for row in out.values():
        row["success_rate"] = (row["successes"] / row["attempts"]
                                if row["attempts"] else 0.0)
    if node_id is not None:
        return {node_id: out.get(node_id, {"attempts": 0, "successes": 0,
                                           "failures": 0,
                                           "success_rate": 0.0})}
    return out


# --------------------------------------------------------------------------- #
# Self-description
# --------------------------------------------------------------------------- #
_HEADER = "## Capability network"
_TRUST_LINE = (
    "Every node below is a verified live capability with its known "
    "alternatives. Route by job, prefer healthy + local, never promise "
    "a node marked unusable."
)


def describe(network: CapabilityNetwork, max_chars: int = 1600) -> str:
    """Compact network map for the brain prompt, <= ``max_chars``.

    Extends the capabilities summary with what the map alone can't
    say: which nodes can substitute for each other, and the routing
    rules of the network itself.
    """
    if max_chars <= 0:
        return ""
    lines: List[str] = [_HEADER, _TRUST_LINE]
    unusable: List[str] = []
    for group in network.groups():
        members = network.by_group(group)
        usable = [n for n in members if n.health == AVAILABLE]
        unusable.extend(
            f"{n.name} ({n.health})" for n in members if n.health != AVAILABLE)
        if not usable:
            continue
        head = usable[0]
        line = f"{group}: {head.name} — {head.purpose} [{head.cost_hint}]"
        alts = [n.name for n in usable[1:]]
        if alts:
            line += " | alternatives: " + ", ".join(alts)
        lines.append(line)
    lines.append(
        "Routing: match the job to the node; on ties prefer local/free "
        "and the node with the better measured record.")
    if unusable:
        lines.append("Not usable right now: " + ", ".join(sorted(unusable)))
    out = "\n".join(lines)
    if len(out) <= max_chars:
        return out
    kept: List[str] = []
    for line in lines:
        if len("\n".join(kept + [line])) > max_chars - 30:
            break
        kept.append(line)
    kept.append("… (network map truncated)")
    out = "\n".join(kept)
    return out[:max_chars] if len(out) > max_chars else out


def explain(network: CapabilityNetwork, node_id: str) -> str:
    """Briefing on one node: what it is, when to use it, what else
    could do the job, and its measured record if the network has one."""
    node = network.node(node_id) or network.find(node_id)
    if node is None:
        return f"{node_id}: not in the capability network."
    lines = [f"{node.id} — {node.purpose}"]
    lines.append(f"kind: {node.kind} · job group: {node.group} "
                 f"· health: {node.health} · cost: {node.cost_hint}"
                 + (f" · gate tier {node.tier}" if node.tier else ""))
    if node.use_when:
        lines.append("use when: " + ", ".join(node.use_when[:8]))
    if node.avoid_when:
        lines.append("avoid: " + "; ".join(node.avoid_when))
    if node.needs:
        lines.append("needs: " + ", ".join(node.needs))
    if node.depends_on:
        lines.append("depends on: " + ", ".join(node.depends_on))
    alts = network.alternatives_of(node.id)
    if alts:
        lines.append("alternatives: " + ", ".join(
            f"{a.id} ({a.health}, {a.cost_hint})" for a in alts))
    else:
        lines.append("alternatives: none — nothing else does this job")
    st = network.scores.get(node.id)
    if st and int(st.get("attempts", 0) or 0) > 0:
        lines.append(
            f"measured record: {st.get('successes', 0)}/{st.get('attempts', 0)}"
            f" ok (success rate {float(st.get('success_rate', 0.0)):.0%})")
    return "\n".join(lines)
