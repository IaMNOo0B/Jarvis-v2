"""jarvis.capabilities — live capability self-knowledge.

JARVIS must KNOW what it can do — from its own registries, read live at
build time, never from a stale prompt or a memorized list. This module
turns the SkillRegistry's current state (plus the PC-control tool table)
into an immutable :class:`CapabilityMap`, and renders that map as a
compact prompt-ready summary the brain can trust:

    These are verified live capabilities. Do not claim inability for
    anything listed.

Availability is a closed vocabulary, derived from the registry record —
the same fields the registry itself uses to decide dispatchability
(``jarvis.skills.registry.SkillRegistry._dispatchable``):

  - ``available``    approved, enabled, no load error, circuit closed
  - ``quarantined``  never approved, or the manifest changed after approval
  - ``disabled``     explicitly disabled (circuit breaker NOT open)
  - ``broken``       invalid manifest, failed to load, or circuit breaker
                     open after repeated failures

Tools inherit their owning skill's availability — the registry tracks no
per-tool runtime state.

Freshness: :func:`build_capability_map` is a pure, cheap read (no I/O, no
imports of skill code). The map carries a ``fingerprint`` — a hash of
everything capability-relevant — so a consumer (the brain) can cache the
rendered summary and rebuild it only when the fingerprint changes: a
skill approved, quarantined, or tripping its circuit breaker changes the
fingerprint and the very next prompt reflects reality.

Duck-typed on purpose: the registry argument may be a real SkillRegistry,
a plain ``{name: record}`` dict, or any iterable of record-like objects.
Nothing here imports jarvis.brain (no cycle) and nothing executes skill
code.

Stdlib only. Python 3.11+.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

__all__ = [
    "AVAILABLE",
    "QUARANTINED",
    "DISABLED",
    "BROKEN",
    "ToolCapability",
    "SkillCapability",
    "CapabilityMap",
    "build_capability_map",
    "capabilities_provider_for",
    "summary_text",
]

# --------------------------------------------------------------------------- #
# Availability vocabulary (closed — mirrors registry dispatch truth)
# --------------------------------------------------------------------------- #
AVAILABLE = "available"
QUARANTINED = "quarantined"
DISABLED = "disabled"
BROKEN = "broken"

# Synthetic group for the PC-control tools (they live outside the skill
# registry — jarvis.pc_control.tool_definitions()).
PC_SKILL_NAME = "pc"
PC_SKILL_DESCRIPTION = (
    "Direct control of this computer (windows, apps, screen, shell)"
)

# Mirrors jarvis.skills.registry.CIRCUIT_BREAKER_THRESHOLD. Only used as a
# fallback for record-like objects that don't expose ``circuit_open``.
_CIRCUIT_BREAKER_THRESHOLD = 3

_PURPOSE_MAX_CHARS = 120


# --------------------------------------------------------------------------- #
# The map
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ToolCapability:
    """One tool, as the registry knows it right now."""
    name: str
    purpose: str          # one line, from the manifest/tool description
    tier: int
    availability: str     # AVAILABLE / QUARANTINED / DISABLED / BROKEN


@dataclass(frozen=True)
class SkillCapability:
    """One skill and every tool it declares."""
    name: str
    description: str
    availability: str
    tools: Tuple[ToolCapability, ...] = ()

    @property
    def available_tools(self) -> Tuple[ToolCapability, ...]:
        return tuple(t for t in self.tools if t.availability == AVAILABLE)


@dataclass(frozen=True)
class CapabilityMap:
    """An immutable snapshot of everything JARVIS can do, right now."""
    skills: Tuple[SkillCapability, ...] = ()
    fingerprint: str = ""

    def tool_count(self) -> int:
        return sum(len(s.tools) for s in self.skills)

    def available_tools(self) -> List[ToolCapability]:
        out: List[ToolCapability] = []
        for s in self.skills:
            out.extend(s.available_tools)
        return out

    def find_tool(self, name: str) -> Optional[ToolCapability]:
        for s in self.skills:
            for t in s.tools:
                if t.name == name:
                    return t
        return None

    def find_skill(self, name: str) -> Optional[SkillCapability]:
        for s in self.skills:
            if s.name == name:
                return s
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "skills": [
                {
                    "name": s.name,
                    "description": s.description,
                    "availability": s.availability,
                    "tools": [
                        {
                            "name": t.name,
                            "purpose": t.purpose,
                            "tier": t.tier,
                            "availability": t.availability,
                        }
                        for t in s.tools
                    ],
                }
                for s in self.skills
            ],
        }


# --------------------------------------------------------------------------- #
# Record reading (duck-typed — real SkillRecord or test fake)
# --------------------------------------------------------------------------- #
def _records_of(registry: Any) -> List[Any]:
    """Extract skill records from whatever registry-shaped thing we got."""
    if registry is None:
        return []
    # A {name: record} dict (tests, partial fakes).
    if isinstance(registry, dict):
        return [registry[k] for k in sorted(registry)]
    # The real SkillRegistry (and anything mirroring its layout).
    records = getattr(registry, "_records", None)
    if isinstance(records, dict):
        return [records[k] for k in sorted(records)]
    # An iterable of records directly.
    try:
        return list(registry)
    except TypeError:
        return []


def _circuit_open(rec: Any) -> bool:
    """Circuit-breaker state: the record's own property if it exposes one,
    else the failure counter against the registry's threshold."""
    prop = getattr(rec, "circuit_open", None)
    if isinstance(prop, bool):
        return prop
    failures = getattr(rec, "failures", 0)
    return isinstance(failures, int) and failures >= _CIRCUIT_BREAKER_THRESHOLD


def _skill_availability(rec: Any) -> str:
    """Registry-truth availability for one record.

    Check order mirrors dispatch reality: a skill that cannot load or has
    tripped its breaker is BROKEN even though the trip also flips
    ``enabled`` off; quarantine is only meaningful for a loadable skill.
    """
    manifest = getattr(rec, "manifest", None)
    if manifest is None:
        return BROKEN
    if getattr(rec, "load_error", None) is not None:
        return BROKEN
    if _circuit_open(rec):
        return BROKEN
    approved = bool(getattr(rec, "approved", False))
    approved_hash = getattr(rec, "approved_hash", "") or ""
    manifest_hash = getattr(rec, "manifest_hash", "") or ""
    if not approved or (manifest_hash and approved_hash != manifest_hash):
        return QUARANTINED
    if not getattr(rec, "enabled", True):
        return DISABLED
    return AVAILABLE


def _one_line(text: Any, limit: int = _PURPOSE_MAX_CHARS) -> str:
    """Collapse a description to one speakable line."""
    line = " ".join(str(text or "").split())
    if len(line) > limit:
        line = line[: limit - 1].rstrip() + "…"
    return line


def _skill_from_record(rec: Any) -> SkillCapability:
    name = str(getattr(rec, "name", "") or "?")
    availability = _skill_availability(rec)
    manifest = getattr(rec, "manifest", None)
    description = ""
    tools: List[ToolCapability] = []
    if manifest is not None:
        description = _one_line(getattr(manifest, "description", ""))
        for t in getattr(manifest, "tools", ()) or ():
            tools.append(ToolCapability(
                name=str(getattr(t, "name", "")),
                purpose=_one_line(getattr(t, "description", "")),
                tier=int(getattr(t, "tier", 1) or 1),
                availability=availability,
            ))
    tools.sort(key=lambda t: t.name)
    return SkillCapability(
        name=name,
        description=description,
        availability=availability,
        tools=tuple(tools),
    )


# --------------------------------------------------------------------------- #
# PC-control tools (live outside the skill registry)
# --------------------------------------------------------------------------- #
def _pc_tool_entries(pc_tools: Any) -> List[Dict[str, Any]]:
    """Normalize pc_tools to a list of {name, description, tier} dicts.

    Accepts: jarvis.pc_control.tool_definitions() output (list of dicts),
    as_gate_registry() output ({name: info}), a module/object exposing
    tool_definitions(), or None (no PC group).
    """
    if pc_tools is None:
        return []
    fn = getattr(pc_tools, "tool_definitions", None)
    if callable(fn):
        pc_tools = fn()
    if isinstance(pc_tools, dict):
        entries = []
        for name, info in sorted(pc_tools.items()):
            info = info if isinstance(info, dict) else {}
            entries.append({
                "name": name,
                "description": info.get("description", ""),
                "tier": info.get("tier", 1),
            })
        return entries
    entries = []
    for item in pc_tools or []:
        if not isinstance(item, dict) or "name" not in item:
            continue
        entries.append({
            "name": item["name"],
            "description": item.get("description", ""),
            "tier": item.get("tier", 1),
        })
    return entries


def _pc_skill(pc_tools: Any) -> Optional[SkillCapability]:
    entries = _pc_tool_entries(pc_tools)
    if not entries:
        return None
    tools = tuple(
        ToolCapability(
            name=str(e["name"]),
            purpose=_one_line(e.get("description", "")),
            tier=int(e.get("tier", 1) or 1),
            availability=AVAILABLE,  # no registry state exists for PC tools
        )
        for e in sorted(entries, key=lambda e: str(e["name"]))
    )
    return SkillCapability(
        name=PC_SKILL_NAME,
        description=PC_SKILL_DESCRIPTION,
        availability=AVAILABLE,
        tools=tools,
    )


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def _fingerprint(skills: Tuple[SkillCapability, ...]) -> str:
    """Hash of everything capability-relevant. Any live-state change that
    matters (approval, quarantine, breaker trip, tool added/removed) flips
    it — that is the rebuild signal for cached summaries."""
    canonical = [
        {
            "name": s.name,
            "availability": s.availability,
            "tools": [
                {"name": t.name, "tier": t.tier, "availability": t.availability}
                for t in s.tools
            ],
        }
        for s in skills
    ]
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def build_capability_map(registry: Any, pc_tools: Any = None) -> CapabilityMap:
    """Snapshot every registered skill + tool, with live availability.

    ``registry``: a SkillRegistry (or duck-typed equivalent / dict /
    iterable of records / None). ``pc_tools``: anything
    :func:`_pc_tool_entries` understands, or None. Pure read — never
    imports skill code, never touches disk.
    """
    skills = [_skill_from_record(rec) for rec in _records_of(registry)]
    skills = [s for s in skills if s.name and s.name != "?"]
    pc = _pc_skill(pc_tools)
    if pc is not None:
        skills.append(pc)
    skills.sort(key=lambda s: s.name)
    frozen = tuple(skills)
    return CapabilityMap(skills=frozen, fingerprint=_fingerprint(frozen))


def capabilities_provider_for(
    registry: Any, pc_tools: Any = None
) -> Callable[[], CapabilityMap]:
    """A zero-arg provider (the shape Brain consumes) that rebuilds the
    map from the live registry on every call. Rebuilds are cheap pure
    reads; the consumer caches on the map's fingerprint."""

    def _provide() -> CapabilityMap:
        return build_capability_map(registry, pc_tools)

    return _provide


# --------------------------------------------------------------------------- #
# Summary rendering (prompt-ready, grouped by skill)
# --------------------------------------------------------------------------- #
_HEADER = "## What you can do right now"
_TRUST_LINE = (
    "These are verified live capabilities. "
    "Do not claim inability for anything listed."
)


def _tool_line(t: ToolCapability) -> str:
    if t.purpose:
        return f"- {t.name} — {t.purpose} (tier {t.tier})"
    return f"- {t.name} (tier {t.tier})"


def summary_text(cap_map: CapabilityMap, max_chars: int = 1200) -> str:
    """Compact capability summary grouped by skill, <= ``max_chars``.

    Available tools are listed (the facts the model may trust); tools
    that exist but cannot run right now are named on one honest line so
    the model doesn't promise them either. Overflow keeps whole lines
    and ends with a "+N more" marker — the result never exceeds
    ``max_chars``.
    """
    if max_chars <= 0:
        return ""
    lines: List[str] = [_HEADER, _TRUST_LINE]
    unavailable: List[str] = []
    for skill in cap_map.skills:
        avail = [t for t in skill.tools if t.availability == AVAILABLE]
        unavailable.extend(
            f"{t.name} ({t.availability})"
            for t in skill.tools
            if t.availability != AVAILABLE
        )
        if not avail:
            continue
        lines.append(f"{skill.name}:")
        lines.extend(_tool_line(t) for t in avail)
    if unavailable:
        lines.append("Not usable right now: " + ", ".join(sorted(unavailable)))
    out = "\n".join(lines)
    if len(out) <= max_chars:
        return out
    # Overflow: keep whole lines, note how many tools were elided.
    total_tools = cap_map.tool_count()
    shown = 0
    kept: List[str] = []
    for line in lines:
        if line.startswith("- "):
            shown += 1
        if len("\n".join(kept + [line])) > max_chars - 40:
            break
        kept.append(line)
    hidden = total_tools - shown
    marker = f"… (+{hidden} more capabilities)" if hidden > 0 else "…"
    out = "\n".join(kept + [marker])
    if len(out) > max_chars:  # degenerate max_chars: hard slice
        out = out[:max_chars]
    return out
