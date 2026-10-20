"""JARVIS v2 — Wave 1 text chat CLI.

R12: honest UX + startup preflight. R1: text-first core (no audio imports).
The ten brain states are text labels, printed as [state].

Wave 1 ships with a STUB brain (StubLLM) so the full pipeline —
rules -> gate -> skills -> session store -> memory — is provably working
today. Connect a real model (Ollama/Qwen) at install by replacing the
llm_call argument to ChatApp; the Brain class is model-agnostic.

Usage:  python -m jarvis.chat [--data-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from pathlib import Path

# --------------------------------------------------------------------------- #
# Preflight (R12): verify the world before doing anything. Failures are
# announced loudly, never silent. Nothing runs on a broken foundation.
# --------------------------------------------------------------------------- #

def preflight(base_dir: Path, data_dir: Path) -> list[str]:
    problems: list[str] = []
    rules_file = base_dir / "JARVIS-RULES.txt"
    if not rules_file.exists():
        # Also accept the knowledge-base copy (dev layout).
        alt = Path.home() / "workspace" / "jarvis-knowledge" / "JARVIS-RULES.txt"
        if alt.exists():
            rules_file = alt
        else:
            problems.append(f"rules file missing: {rules_file}")
    skills_dir = base_dir / "skills"
    if not skills_dir.is_dir():
        problems.append(f"skills dir missing: {skills_dir}")
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write_probe"
        probe.write_text("ok")
        probe.unlink()
    except Exception as exc:
        problems.append(f"data dir not writable: {data_dir} ({exc})")
    return problems


def _is_simple_greeting(text: str) -> bool:
    """Recognize only standalone greetings that need no model inference.

    This keeps a dead or exhausted provider chain from making basic
    conversational contact look broken. Do not match greetings embedded
    in a real request such as 'hi, open Chrome'.
    """
    normalized = re.sub(r"[^a-z0-9\s]", "", (text or "").lower()).strip()
    normalized = " ".join(normalized.split())
    return normalized in {
        "hi", "hello", "hey", "hey jarvis", "hi jarvis", "hello jarvis",
        "good morning", "good afternoon", "good evening",
    }


def _simple_chat_reply(text: str) -> str | None:
    """Answer common social turns without asking a tool planner to guess."""
    normalized = re.sub(r"[^a-z0-9\\s]", "", (text or "").lower()).strip()
    normalized = " ".join(normalized.split())
    if _is_simple_greeting(normalized):
        return "Hello, Sir. I'm here and ready to help."
    if normalized in {
        "how are you", "how are u", "how r you", "how r u",
        "how are you doing", "how are you jarvis", "whats up",
    }:
        return "I'm doing well, Sir, and ready to help. How are you?"
    if normalized in {"no", "nope", "nah", "not now"}:
        return "No problem, Sir. What would you like to do next?"
    if normalized in {"thanks", "thank you", "thanks jarvis", "thank you jarvis"}:
        return "You're welcome, Sir."
    return None


def startup_warnings(data_dir: Path) -> list[str]:
    """Non-fatal first-run warnings (F-13). Checked separately from
    preflight because they advise, not refuse."""
    warnings: list[str] = []
    try:
        onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
        if onedrive:
            data_str = str(data_dir.resolve())
            od_str = str(Path(onedrive).resolve())
            if data_str.lower().startswith(od_str.lower()):
                warnings.append(
                    "data/ lives inside a OneDrive-synced folder. OneDrive's "
                    "sync locks fight SQLite (sessions.db) and can corrupt "
                    "or duplicate your chats. Move the repo out of Documents, "
                    "or pass --data-dir to a non-synced folder."
                )
    except Exception:
        pass
    return warnings


# --------------------------------------------------------------------------- #
# StubLLM — Wave-1 stand-in for the real model. Trigger phrases route to the
# reference skills; everything else gets an honest direct answer. The format
# matches Brain._parse_reply: {"tool_calls": [...]} or {"content": "..."}.
# --------------------------------------------------------------------------- #

class StubLLM:
    """Deterministic stand-in. Replace with Ollama/Qwen at install."""

    def __call__(self, messages: list[dict]) -> dict:
        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_text = str(m.get("content", ""))
                break
        low = user_text.lower().strip()

        # Tool results already in context -> answer from them, never re-call.
        tool_seen = [m for m in messages if m.get("role") == "tool"]
        if tool_seen:
            last = tool_seen[-1]
            content = str(last.get("content", ""))
            # Strip the evidence wrapper for a clean spoken answer.
            if "</tool_output>" in content:
                inner = content.split("<tool_output", 1)[-1]
                inner = inner.split(">", 1)[-1].rsplit("</tool_output>", 1)[0]
                content = inner.strip()
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    if "iso" in data:
                        iso = str(data["iso"]).replace("T", " ").split("+")[0]
                        return {"content": f"It's {iso} UTC, sir."}
                    if "notes" in data:
                        notes = data["notes"]
                        if not notes:
                            return {"content": "No notes yet, sir."}
                        lines = [f"- {n}" for n in notes[:5]]
                        return {"content": "Your notes, sir:\n" + "\n".join(lines)}
                    if "written" in data:
                        return {"content": "Noted down, sir."}
                    if "text" in data:
                        return {"content": str(data["text"])}
                    if data.get("ok") is False:
                        return {"content": f"That didn't work, sir: {data.get('error', 'unknown error')}"}
                    return {"content": f"Done, sir. ({json.dumps(data)[:200]})"}
            except (json.JSONDecodeError, ValueError):
                pass
            return {"content": f"Here's what I found, sir: {content[:300]}"}

        if any(w in low for w in ("time", "clock", "what time")):
            return {"tool_calls": [{"name": "now", "args": {}}]}
        if low.startswith("note ") or low.startswith("remember "):
            import time as _time
            text = user_text.split(" ", 1)[1] if " " in user_text else ""
            path = f"note-{int(_time.time())}.txt"
            return {"tool_calls": [{"name": "notes_write",
                                    "args": {"path": path, "content": text}}]}
        if "my notes" in low or "show notes" in low or "list notes" in low:
            return {"tool_calls": [{"name": "notes_list", "args": {}}]}
        if low.startswith("echo "):
            return {"tool_calls": [{"name": "echo", "args": {"text": user_text[5:]}}]}
        if low in ("hi", "hello", "hey", "hey jarvis"):
            return {"content": "At your service, sir. Text chat is online — all systems nominal."}
        return {"content": (
            "Understood, sir. (Wave-1 stub brain: I can check the time, "
            "take notes, and echo — say 'what time is it', 'note buy milk', "
            "'show my notes'. The full model connects at install.)"
        )}


# --------------------------------------------------------------------------- #
# ChatApp — wires every component, owns the turn loop.
# --------------------------------------------------------------------------- #

# Turn allowances (policy, never the brain's choice):
# reads auto-allowed; file writes allowed by capability (tier-2 still
# announces + undo); network/exec/clipboard NOT granted in Wave 1.
TURN_ALLOWANCES = ["fs.read", "fs.write", "time.read"]

# First-party skills ship WITH v2: approved at first run (the voicebox
# pattern — first-party skips approval, never the sandbox).
FIRST_PARTY_SKILLS = ("echo", "notes", "clock", "knowledge", "web", "code", "reminders", "system", "finance", "email", "calendar")


class ChatApp:
    def __init__(self, base_dir: Path, data_dir: Path,
                 enable_pc: bool = True, enable_phone: bool = False) -> None:
        self.base_dir = base_dir
        self.data_dir = data_dir
        # Custom API providers live in the data dir.
        from jarvis.llm_compat import set_custom_dir
        set_custom_dir(str(data_dir))
        self._allowances = list(TURN_ALLOWANCES)
        if enable_pc:
            self._allowances += ["ui.read", "ui.control", "shell.exec"]

        from jarvis.rules import load_rules, RulesError
        from jarvis.config import Config, Field
        from jarvis.session_store import SessionStore
        from jarvis.memory import Memory
        from jarvis.skills.registry import SkillRegistry, SkillContext
        from jarvis.gate import Gate, Verdict
        from jarvis.brain import Brain, ToolDef
        from jarvis.llm_ollama import make_llm_call
        from jarvis import approvals as approvals_mod
        from jarvis import contracts as contracts_mod
        from jarvis import effects as effects_mod

        rules_path = base_dir / "JARVIS-RULES.txt"
        if not rules_path.exists():
            rules_path = Path.home() / "workspace" / "jarvis-knowledge" / "JARVIS-RULES.txt"
        try:
            self.rules = load_rules(str(rules_path))
        except RulesError as exc:
            print(f"[preflight] FATAL: {exc}")
            print("[preflight] JARVIS refuses to start with hard-safety rules missing.")
            sys.exit(2)

        # Wave-1 config schema (minimal; grows per wave).
        schema = {
            "profile": Field(str, "owais"),
            "brain": {
                "max_rounds": Field(int, 3, min=1, max=10),
                "max_tool_calls": Field(int, 12, min=1, max=50),
            },
            "data_retention_days": Field(int, 365),
        }
        self.config = Config(str(data_dir / "config.yaml"), schema)
        self.config.load()
        self.store = SessionStore(str(data_dir / "sessions.db"))
        self.memory = Memory(str(data_dir / "memory.db"))
        # Ext-6: point the DCL's module-level secret registry at THIS
        # data dir, so secrets registered for redaction persist (salted
        # digests only, never the values) across restarts. Guarded:
        # redaction keeps working in-memory if the registry file
        # cannot load — startup never dies over it.
        try:
            from jarvis import dcl as _dcl_mod
            _dcl_mod.configure_registry(str(data_dir))
        except Exception:
            pass
        # Analytics patterns: if earlier sessions left pattern
        # proposals waiting for the owner's decision, say so in ONE
        # line at startup — no modal, no ringing; /patterns reviews
        # them. Guarded: a broken patterns store stays silent.
        try:
            from jarvis.patterns import PatternStore
            if PatternStore(data_dir).pending():
                print("[patterns] I noticed a few patterns — ask me "
                      "about them when ready (/patterns).")
        except Exception:
            pass

        self.registry = SkillRegistry(base_dir / "skills", data_dir)
        self.registry.discover()
        for name in FIRST_PARTY_SKILLS:
            try:
                self.registry.approve(name)
            except Exception as exc:
                print(f"[warn] could not approve first-party skill {name!r}: {exc}")

        # The gate's registry: tool_name -> {tier, schema, capabilities}
        # + the recovery pack's declared contracts, copied from the
        # manifests so gate.dispatch can journal effects and evaluate
        # postconditions for exactly the tools that declared them.
        gate_registry: dict = {}
        for skill_name in self.registry._records:
            rec = self.registry._records[skill_name]
            if rec.manifest is None:
                continue
            for tool in rec.manifest.tools:
                gate_registry[tool.name] = {
                    "tier": tool.tier,
                    "schema": tool.parameters,
                    "capabilities": list(tool.capabilities),
                    "effects": [dict(e) for e in tool.effects],
                    "postconditions": [dict(p) for p in tool.postconditions],
                }
        # Wave 3: PC control tools. Enabled by default — the owner asked
        # for full capability ("he can do all the stuff like you do").
        # Safety comes from the approval gates (tier-2 announces, tier-3
        # needs explicit approval), not from hiding the tools.
        self._pc = None
        if enable_pc:
            from jarvis import pc_control
            import platform
            # Builder C: the learned app registry (name -> path,
            # SQLite in the data dir) makes repeat launches instant.
            # Guarded: if its file cannot be created or opened, PC
            # control still works — only the learned rung of the
            # launch ladder is off, never a startup crash.
            app_registry = None
            try:
                app_registry = pc_control.AppRegistry(
                    data_dir / "app_registry.db")
            except Exception:
                app_registry = None
            if platform.system() == "Windows":
                self._pc = pc_control.PCController(
                    app_registry=app_registry)
            else:
                print("[pc] Not Windows — PC control runs on the FAKE backend "
                      "(structure real, no real clicks).")
                self._pc = pc_control.PCController(
                    backend=pc_control.FakeUiaBackend(),
                    app_registry=app_registry)
            gate_registry.update(pc_control.as_gate_registry())
        # Recovery pack wiring: the gate journals declared effects into
        # the session store and evaluates declared postconditions
        # against real state (the data dir is the fs root — skill jails
        # live at <data_dir>/<skill>, which the manifest targets name).
        # Failed postcondition reports land in _contract_reports, keyed
        # (session_id, turn_id, tool); the brain/chat TAKE them from
        # there to stamp tool.result payloads (see _take_contract_report).
        self._contract_reports: dict = {}

        def _contract_sink(record: dict) -> None:
            try:
                key = (record.get("session_id"), record.get("turn_id"),
                       record.get("tool"))
                self._contract_reports[key] = record.get("report")
            except Exception:
                pass  # evidence plumbing never breaks a dispatch

        self.gate = Gate(
            rules={}, skill_registry=gate_registry,
            effect_sink=effects_mod.make_store_sink(self.store),
            effect_fs_root=str(data_dir),
            fact_exists=lambda k: self.memory.get_fact(k) is not None,
            postcondition_evaluator=contracts_mod.make_evaluator(
                fs_root=str(data_dir), memory=self.memory),
            contract_sink=_contract_sink)
        self._Verdict = Verdict

        # Brain tools: ToolDef(name, fn) where fn runs the skill pipeline.
        # The gate already checked before fn is called; the registry's
        # risk-gate stage re-checks (defense in depth, cheap).
        def make_fn(tool_name: str):
            def fn(args: dict):
                # PC control tools route to the PCController, not the skill pipe.
                if tool_name.startswith("pc.") and self._pc is not None:
                    return self._pc_call(tool_name, args)
                ctx = SkillContext(
                    skill_name="chat",
                    capabilities=self._allowances,
                    jail_dir=str(data_dir),
                    turn_id=self._turn_id,
                )
                def risk_gate(tn: str, tier: int, a: dict, c) -> bool:
                    d = self.gate.check(tn, a, self._allowances)
                    return d.verdict in (Verdict.ALLOW, Verdict.ALLOW_WITH_UNDO)
                result = self.registry.dispatch(tool_name, args, ctx, risk_gate)
                if not result.get("ok"):
                    raise RuntimeError(
                        f"skill pipeline: {result.get('code')}: {result.get('message')}")
                return result["result"]
            return fn

        tools = []
        pc_descs = {}
        if self._pc is not None:
            from jarvis import pc_control
            pc_descs = {t["name"]: t["description"]
                        for t in pc_control.tool_definitions()}
        for n, info in gate_registry.items():
            desc = next(
                (t.description for rec in self.registry._records.values()
                 if rec.manifest for t in rec.manifest.tools if t.name == n),
                pc_descs.get(n, n),
            )
            tools.append(ToolDef(name=n, description=desc,
                                 parameters=info["schema"], fn=make_fn(n)))
        self._turn_id = 0
        # Routine (morning digest) session events waiting for this
        # turn's user.message to exist — see _flush_routine_events.
        self._pending_routine_events: list = []
        # Brain chain: smartest first. If the owner has cloud API keys,
        # those models (Gemini, Kimi, GPT-OSS...) answer first — they're
        # far smarter than the local 7B. Local Ollama is the offline
        # fallback. Keyless Pollinations is the last resort before stub.
        # Each link is loud about its own absence; nothing is ever silent.
        from jarvis.brain import FallbackChain, chain_as_llm_call
        from jarvis.llm_ollama import make_llm_call, OllamaProvider, OllamaCall
        ollama_provider = None
        try:
            ollama_call = OllamaCall(rules=self.rules)
            ok, _ = ollama_call.check_health()
            if ok:
                ollama_provider = OllamaProvider(ollama_call)
        except Exception:
            pass
        omni_provider = None
        try:
            from jarvis.llm_omniroute import make_omniroute_call, OmniRouteProvider
            omni_model = self.config.get("brain.omniroute_model",
                                         "google/gemini-2.5-flash")
            omni_call = make_omniroute_call(model=omni_model)
            if omni_call is not None:
                omni_provider = OmniRouteProvider(omni_call)
        except Exception:
            pass
        poll_provider = None
        try:
            # Keyless cloud brain — zero setup, works out of the box.
            from jarvis.llm_pollinations import (
                make_pollinations_call, PollinationsProvider)
            poll_call = make_pollinations_call()
            if poll_call is not None:
                poll_provider = PollinationsProvider(poll_call)
        except Exception:
            pass
        keyed = []
        try:
            # The owner's key vault: every stored key becomes a provider,
            # with per-provider rotation.
            from jarvis.llm_compat import make_compat_providers
            keyed = make_compat_providers(data_dir=str(self.data_dir))
        except Exception:
            pass
        # Deterministic order: local Ollama first (when healthy), then
        # keyed cloud providers, then OmniRoute, then keyless Pollinations.
        # Do not call local_first(*providers) with keyed providers first:
        # local_first treats its FIRST argument as the local provider.
        providers = []
        if ollama_provider is not None:
            providers.append(ollama_provider)
        providers.extend(keyed)
        if omni_provider is not None:
            providers.append(omni_provider)
        if poll_provider is not None:
            providers.append(poll_provider)
        if providers:
            chain = FallbackChain(providers)
            llm_call = chain_as_llm_call(chain)
            # F-08: keep the chain so the GUI pill can read last_via.
            self._chain: "FallbackChain | None" = chain
        else:
            llm_call = make_llm_call(rules=self.rules)
            # No providers at all: make_llm_call falls back to the honest
            # StubLLM. The pill shows STUB so the owner knows (F-08).
            self._chain = None
        # Self-knowledge: who JARVIS is, what he can do. Loaded from SELF.md
        # so he can "find himself" instead of guessing.
        self_knowledge = ""
        try:
            self_md = base_dir / "SELF.md"
            if self_md.exists():
                self_knowledge = self_md.read_text(encoding="utf-8").strip()
            # Teaching: lessons from Ovi. Loaded from TEACHING.md so JARVIS
            # learns like a student, not just reads a manual.
            teaching_md = base_dir / "TEACHING.md"
            if teaching_md.exists():
                teaching = teaching_md.read_text(encoding="utf-8").strip()
                if teaching:
                    self_knowledge += "\n\n--- LESSONS FROM YOUR TEACHER ---\n" + teaching
        except Exception:
            pass
        # Live capability self-knowledge (Ext-1): the brain reads what
        # JARVIS can do from the real registry — plus the PC tool table
        # when PC control is on — on every prompt build, so it answers
        # "can you do X?" from live fact, never a stale memorized list.
        # This is the ONLY Brain construction site: the CLI (main) and
        # the GUI (chat_gui) both reach it through ChatApp.
        from jarvis.capabilities import capabilities_provider_for
        _pc_tool_defs = None
        if self._pc is not None:
            from jarvis import pc_control as _pc_control
            _pc_tool_defs = _pc_control.tool_definitions()
        # Kept for the capability network: the router, the prompt and
        # /capabilities all aggregate over the same sources.
        self._pc_tool_defs = _pc_tool_defs
        self._network = None  # latest CapabilityNetwork snapshot
        capabilities_provider = capabilities_provider_for(
            self.registry, _pc_tool_defs)
        self.brain = Brain(
            gate=self.gate,
            session_store=self.store,
            rules=self.rules,
            llm_call=llm_call,
            tools=tools,
            llm_off_machine=True,  # F-11: the chain is dynamic (local Ollama ->
            # OmniRoute -> Pollinations); redact always — harmless for local
            # (PUBLIC/PERSONAL pass through), correct for cloud.
            self_knowledge=self_knowledge,
            memory=self.memory,  # gated auto-recall every turn (Recall Gate)
            capabilities_provider=capabilities_provider,
            # The unified capability network (jarvis.capnet): when it
            # builds, its self-description replaces the plain summary in
            # the prompt, capnet.select pre-routes deterministic tasks,
            # and turn outcomes flow back into its health scores.
            network_provider=self._capability_network,
            # Recovery pack: the brain takes failed postcondition
            # reports for its gated dispatches from the gate's stash —
            # stamping tool.result payloads and feeding the ladder.
            contract_lookup=self._take_contract_report,
        )
        self._approvals = approvals_mod
        self.session_id = self.store.create_session("owais", "cli")
        # Deterministic intent tier (mega-scan steals: Rhasspy grammar
        # tier + Open.Jarvis local-intent-first). Exact grammar hits for
        # REAL skill tools dispatch through the same gate-first path an
        # LLM tool call takes (see _route_turn) — zero model calls for
        # boring commands. Virtual system intents and fuzzy guesses
        # never execute from here. Building the router must never break
        # startup: on any failure the app behaves exactly as before and
        # the brain handles every turn.
        self.router = None
        try:
            from jarvis.intent_router import IntentRouter
            _router = IntentRouter()
            _router.load_skills_root(base_dir / "skills")
            _router.load_phrases(
                "system",
                (Path(__file__).resolve().parent /
                 "system_phrases.txt").read_text(encoding="utf-8"))
            self.router = _router
        except Exception as exc:
            print(f"[router] intent tier unavailable ({exc}) — "
                  "the brain handles all turns.")

    @property
    def last_provider(self) -> str:
        """F-08: which brain answered the last turn?

        "stub" — no providers at all (StubLLM is answering, honest red pill).
        "none" — chain exists but no turn has completed yet.
        otherwise the provider name (ollama / pollinations / groq / ...).
        """
        chain = getattr(self, "_chain", None)
        if chain is None:
            return "stub"
        return getattr(chain, "last_via", "unknown")

    # -- capability network (jarvis.capnet) -------------------------------- #
    def _capability_network(self):
        """Build the unified capability network over JARVIS's live parts.

        Sources: the skill registry + PC tool table (live health via
        jarvis.capabilities), the brain's provider chain (with its
        measured stats), and THIS session's capnet outcome scores from
        the session store — a node that keeps failing at similar work
        sinks in the router. Pure aggregation, rebuilt on demand so
        approvals, quarantine flips and breaker trips show up at once;
        the latest snapshot is kept on self._network for the router
        and the /capabilities command. Returns None when the build
        fails: every consumer must degrade to life without the network.
        """
        try:
            from jarvis.capnet import build_network, health_scores
            scores = {}
            sid = getattr(self, "session_id", None)
            if sid:
                try:
                    scores = health_scores(self.store, session_id=sid)
                except Exception:
                    scores = {}
            net = build_network(self.registry, self._pc_tool_defs,
                                providers=getattr(self, "_chain", None),
                                scores=scores)
            self._network = net
            return net
        except Exception:
            return getattr(self, "_network", None)

    # -- recovery pack wiring ------------------------------------------------ #
    def _take_contract_report(self, session_id, turn_id, tool_name):
        """TAKE the latest failed postcondition report for one gated
        dispatch (the gate's contract_sink stash). Take semantics: each
        dispatch overwrites its key and each consumer pops it, so a
        later attempt of the same tool in the same turn can never read
        an earlier attempt's stale failure."""
        try:
            return self._contract_reports.pop(
                (session_id, turn_id, tool_name), None)
        except Exception:
            return None

    def _current_turn_id(self):
        """The id this turn's executions journal under: the event id of
        the session's most recent user.message (brain turns and routed
        turns both open with one). None when no turn has opened."""
        try:
            events = self.store.get_events(self.session_id, 0, 100000)
            for ev in reversed(events):
                if ev.get("type") == "user.message":
                    return ev.get("event_id")
        except Exception:
            pass
        return None

    def _execute_gated(self, tool_name: str, args: dict, fn, turn_id):
        """Execute one already-checked routed call THROUGH gate.dispatch
        (turn-scoped), so the recovery-pack hooks fire: declared effects
        journal into the session store and declared postconditions are
        evaluated against real state. Returns (ok, raw_out, content,
        report): raw_out is captured from the executor closure (dispatch
        returns only the wrapped string); report is the TAKE of the
        contract stash for this call (None when the postconditions
        passed or none were declared)."""
        captured: dict = {}

        def _exec(_name, _args):
            try:
                captured["raw"] = fn(_args)
            except Exception as exc:
                captured["exc"] = exc
                raise
            return captured["raw"]

        payload_text = None
        entry = self.gate.registry.get(tool_name) or {}
        if entry.get("network_egress") or any(
                str(c).startswith("net.")
                for c in entry.get("capabilities", [])):
            # The gate's own rule: network-bound tools dispatch only
            # with an egress-checked payload (the args are what leaves).
            payload_text = json.dumps(args, default=str)
        decision, _wrapped = self.gate.dispatch(
            tool_name, args, self._allowances, _exec,
            payload_text=payload_text,
            destination=tool_name if payload_text is not None else None,
            session_id=self.session_id, turn_id=turn_id)
        report = self._take_contract_report(self.session_id, turn_id,
                                            tool_name)
        if "exc" in captured:
            exc = captured["exc"]
            return False, None, f"error: tool '{tool_name}' raised: {exc}", report
        verdict = getattr(decision.verdict, "value", str(decision.verdict))
        if verdict not in ("allow", "allow_with_undo"):
            return False, None, (f"error: the gate withheld '{tool_name}' "
                                 f"at dispatch ({decision.reason})"), report
        raw_out = captured.get("raw")
        content = raw_out if isinstance(raw_out, str) else json.dumps(
            raw_out, default=str)
        return True, raw_out, content, report

    def _reminder_cancel(self, target: str):
        """undo_turn's reminder canceller (effects are journaled by the
        reminder's TEXT — its id is minted inside the skill, so the
        manifest target is {args.text}). Resolves the text to a pending
        reminder id and cancels THROUGH the registry executor."""
        try:
            listed = self._executor("reminder_list", {})
            for rem in (listed or {}).get("reminders", []):
                if rem.get("text") == target:
                    return self._executor("reminder_cancel",
                                          {"id": rem.get("id", "")})
        except Exception:
            pass
        return {"cancelled": False}

    def _last_journaled_turn(self):
        """The turn_id of the most recent effect.recorded event in this
        session — the last turn that actually changed something."""
        try:
            events = self.store.get_events(self.session_id, 0, 100000)
            for ev in reversed(events):
                if ev.get("type") == "effect.recorded":
                    return (ev.get("payload") or {}).get("turn_id")
        except Exception:
            pass
        return None

    def _undo_last_turn(self) -> None:
        """/undo-turn: reverse the LAST turn of this session that
        journaled effects (effects.undo_turn walks the journal in
        reverse). The reply names every effect: reversed ones with
        their action, the rest with the reason they could NOT be
        reversed — never a blanket "undone"."""
        from jarvis import effects as effects_mod
        turn_id = self._last_journaled_turn()
        if turn_id is None:
            print("[undo] Nothing to undo, sir — no turn in this "
                  "session journaled any effects.")
            return
        report = effects_mod.undo_turn(
            self.store, self.session_id, turn_id,
            memory=self.memory, fs_root=str(self.data_dir),
            reminder_cancel=self._reminder_cancel)
        total = report.get("total", 0)
        reversed_ = report.get("reversed", [])
        not_reversed = report.get("not_reversed", [])
        if total == 0:
            print("[undo] That turn journaled no effects, sir.")
            return
        if report.get("ok"):
            print(f"[undo] Turn fully reversed, sir — {len(reversed_)} "
                  f"effect(s):")
        else:
            print(f"[undo] Turn PARTIALLY reversed, sir — "
                  f"{len(reversed_)} of {total} effect(s) reversed; "
                  f"the rest could not be:")
        for entry in reversed_:
            print(f"  reversed: {entry.get('kind')} "
                  f"{entry.get('target')} — {entry.get('action')}")
        for entry in not_reversed:
            print(f"  NOT reversed: {entry.get('kind')} "
                  f"{entry.get('target')} — {entry.get('reason')}")

    # -- deterministic intent tier ---------------------------------------- #
    def _is_real_skill_tool(self, match) -> bool:
        """True only when the match names a tool that actually exists in
        the manifest of the approved skill the match claims. Virtual
        "system" intents (observe_screen, launch_app, close_thing...)
        are intent NAMES, not tools — they never dispatch from here."""
        rec = self.registry._records.get(match.skill)
        if rec is None or not rec.approved or rec.manifest is None:
            return False
        return any(t.name == match.tool for t in rec.manifest.tools)

    def _route_turn(self, text: str):
        """Try the deterministic intent tier for this turn.

        Returns a TurnResult when an EXACT grammar hit (confidence 1.0)
        names a real, approved skill tool — dispatched through the same
        gate-first path Brain.respond uses for LLM tool calls, minus
        the model. Returns None for everything else (no match, fuzzy
        guess, virtual system intent): the brain handles the turn as
        always. Fuzzy matches are NOT hinted into the brain —
        Brain.respond(session_id, text, allowances) has no context
        parameter, and inventing one is a brain change, not wiring.
        Routing failures degrade to None: routing NEVER breaks a turn.
        """
        from types import SimpleNamespace

        # Explicit search commands have a deterministic tool + argument.
        # Grant net.outbound only for this user-requested search, then restore
        # the normal turn allowances immediately after gated dispatch.
        normalized = re.sub(r"[^a-z0-9\\s:/._-]", "", (text or "").lower())
        normalized = " ".join(normalized.split())
        query = None
        for prefix in ("search the internet for ", "search internet for ",
                       "search for ", "search ", "look up ", "google "):
            if normalized.startswith(prefix):
                query = normalized[len(prefix):].strip()
                break
        if query:
            query = re.sub(r"\\s+(?:on|over)\\s+(?:the\\s+)?internet$", "", query).strip()
            if query:
                search_match = SimpleNamespace(
                    skill="web", tool="web_search",
                    args={"query": query, "max_results": 5},
                    fuzzy=False, confidence=1.0)
                if self._is_real_skill_tool(search_match):
                    previous_allowances = self._allowances
                    self._allowances = list(dict.fromkeys(
                        [*previous_allowances, "net.outbound"]))
                    try:
                        return self._dispatch_routed(text, search_match)
                    except Exception as exc:
                        print(f"[router] search dispatch failed: "
                              f"{type(exc).__name__}: {exc}")
                        return None
                    finally:
                        self._allowances = previous_allowances

        router = getattr(self, "router", None)
        if router is None:
            return None
        try:
            match = router.route(text)
        except Exception:
            return None
        if match is None or match.fuzzy or match.confidence < 1.0:
            return None  # fuzzy args are provisional — the LLM's turn
        if not self._is_real_skill_tool(match):
            # Exact app/site requests still pass through the same Gate.
            if (match.skill == "system" and match.tool == "launch_app"
                    and self._pc is not None):
                app_name = str((match.args or {}).get("app", "")).strip()
                if not app_name:
                    return None
                sites = {
                    "youtube": "https://www.youtube.com/",
                    "google": "https://www.google.com/",
                    "gmail": "https://mail.google.com/",
                    "github": "https://github.com/",
                    "chatgpt": "https://chatgpt.com/",
                    "reddit": "https://www.reddit.com/",
                    "instagram": "https://www.instagram.com/",
                    "facebook": "https://www.facebook.com/",
                }
                normalized_app = " ".join(app_name.lower().split())
                if normalized_app in sites:
                    match = SimpleNamespace(
                        skill="pc", tool="pc.open_url",
                        args={"url": sites[normalized_app]},
                        fuzzy=False, confidence=1.0)
                else:
                    match = SimpleNamespace(
                        skill="pc", tool="pc.launch_app",
                        args={"name": app_name}, fuzzy=False, confidence=1.0)
            else:
                return None  # other virtual intents remain model-mediated
        try:
            return self._dispatch_routed(text, match)
        except Exception as exc:
            # Preserve the actual failure rather than silently disguising it
            # as a generic model reply.
            print(f"[router] dispatch failed for {match.tool}: "
                  f"{type(exc).__name__}: {exc}")
            return None

    def _dispatch_routed(self, text: str, match, via: str = "intent_router"):
        """Execute one routed hit through the gate, brain-style.

        Mirrors Brain._respond_inner's Act step event-for-event so the
        completion audit and conversation history see a normal tool
        turn: user.message -> tool.call (gate verdict FIRST, before
        anything executes) -> tool.result -> brain.reply. A
        require_approval verdict returns the same TurnResult shape the
        brain produces, so turn()'s approval flow handles it unchanged.
        ``via`` names the routing tier on the tool.call event
        ("intent_router" for the grammar tier, "capnet" for the
        capability network) — the ONLY difference between the tiers'
        event streams.
        """
        from jarvis.brain import TurnResult
        store = self.store
        sid = self.session_id
        args = dict(match.args)
        user_ev = store.emit(sid, "user.message", {"text": text},
                             actor="user", trust="user")
        decision = self.gate.check(match.tool, args, self._allowances)
        verdict = getattr(decision.verdict, "value", str(decision.verdict))

        def _finish(result):
            # Same post-turn audit the brain attaches (evidence only).
            try:
                from jarvis.completion_audit import CompletionAudit
                result.audit = CompletionAudit(store).audit_turn(sid)
            except Exception as exc:
                result.audit = {"delivered": False,
                                "reason": f"audit unavailable: {exc}"}
            return result

        if verdict == "deny":
            store.emit(sid, "tool.call",
                       {"tool": match.tool, "args": args,
                        "gate_verdict": "deny",
                        "reason": getattr(decision, "reason", ""),
                        "via": via},
                       actor="brain", trust="system", causal_parent=user_ev)
            reply = (f"I can't do that, sir — the gate denied "
                     f"{match.tool} "
                     f"({getattr(decision, 'reason', 'not allowed')}).")
            store.emit(sid, "brain.reply", {"text": reply},
                       actor="brain", trust="user", causal_parent=user_ev)
            return _finish(TurnResult(status="answered", text=reply))

        if verdict == "require_approval":
            call_ev = store.emit(
                sid, "tool.call",
                {"tool": match.tool, "args": args,
                 "gate_verdict": "require_approval", "proposed": True,
                 "executed": False, "via": via},
                actor="brain", trust="system", causal_parent=user_ev)
            req = getattr(decision, "approval_request", None) or {}
            store.emit(sid, "approval.requested",
                       {"action": match.tool, "args": args, "request": req},
                       actor="brain", trust="system", causal_parent=call_ev)
            return _finish(TurnResult(
                status="approval_required",
                text=(f"This needs your approval first, sir: {match.tool}. "
                      "I've paused — nothing has run."),
                approval_request={"tool": match.tool, "args": args,
                                  "request": req}))

        # allow / allow_with_undo — the ONLY path to execution.
        call_ev = store.emit(sid, "tool.call",
                             {"tool": match.tool, "args": args,
                              "gate_verdict": verdict,
                              "via": via},
                             actor="brain", trust="system",
                             causal_parent=user_ev)
        tool = self.brain.tools.get(match.tool)
        if tool is None or tool.fn is None:
            store.emit(sid, "tool.result",
                       {"ok": False,
                        "error": f"tool '{match.tool}' is not registered"},
                       actor="tool", trust="tool_untrusted",
                       causal_parent=call_ev)
            reply = (f"That didn't work, sir: tool '{match.tool}' "
                     "is not registered.")
            store.emit(sid, "brain.reply", {"text": reply},
                       actor="brain", trust="user", causal_parent=call_ev)
            return _finish(TurnResult(status="answered", text=reply))
        # Execute THROUGH gate.dispatch (turn-scoped to this turn's
        # user.message event): declared effects journal and declared
        # postconditions are evaluated against real state.
        ok, raw_out, content, report = self._execute_gated(
            match.tool, args, tool.fn, user_ev)
        result_payload = {"ok": ok, "output": content[:2000]}
        if report is not None:
            # Stamp the typed failure: the completion audit reads the
            # turn as NOT delivered even though the tool claimed ok.
            from jarvis.contracts import mark_result
            result_payload = mark_result(result_payload, report)
        store.emit(sid, "tool.result",
                   result_payload,
                   actor="tool", trust="tool_untrusted",
                   causal_parent=call_ev)
        if ok and report is not None and not report.get("passed", True):
            failures = "; ".join(
                f"{c.get('check')}:{c.get('target')}"
                for c in report.get("failures", []))
            reply = (f"I ran {match.tool}, sir, but it failed its "
                     f"delivery check ({failures}) — please treat that "
                     f"as not done.")
        else:
            reply = (self._format_tool_reply(match, raw_out) if ok
                     else f"That didn't work, sir: {content}")
        store.emit(sid, "brain.reply", {"text": reply},
                   actor="brain", trust="user", causal_parent=call_ev)
        return _finish(TurnResult(status="answered", text=reply,
                                  tool_calls_made=1 if ok else 0))

    @staticmethod
    def _format_tool_reply(match, raw_out) -> str:
        """User-facing one-liner for a router-dispatched tool result.
        Deterministic per tool; honest generic fallback otherwise."""
        data = raw_out if isinstance(raw_out, dict) else None
        if data is None:
            return f"Done, sir. {str(raw_out)[:300]}"
        if match.tool == "now" and "iso" in data:
            iso = str(data["iso"]).replace("T", " ").split("+")[0]
            return f"It's {iso} UTC, sir."
        if match.tool == "reminder_set":
            return (f"Reminder set, sir: '{match.args.get('text', '')}' "
                    f"— due {data.get('due_at', '')} (id {data.get('id', '')}).")
        if match.tool == "reminder_list":
            rems = data.get("reminders") or []
            if not rems:
                return "No pending reminders, sir."
            lines = [f"- {r.get('text', '')} "
                     f"(due {r.get('due_at', '')}, id {r.get('id', '')})"
                     for r in rems[:10]]
            return "Your reminders, sir:\n" + "\n".join(lines)
        if match.tool == "reminder_cancel":
            return ("Reminder cancelled, sir." if data.get("cancelled")
                    else "That reminder wasn't pending, sir.")
        if data.get("ok") is False:
            return (f"That didn't work, sir: "
                    f"{data.get('error', data.get('reason', 'unknown error'))}")
        return "Done, sir. (" + json.dumps(data, default=str)[:200] + ")"

    # -- capability-network tier -------------------------------------------- #
    def _capnet_tool_skill(self, tool_name: str):
        """Owning skill name when tool_name is a REAL tool of an APPROVED
        skill in the live registry — the capnet twin of
        _is_real_skill_tool's registry check."""
        for name, rec in self.registry._records.items():
            if not rec.approved or rec.manifest is None:
                continue
            if any(t.name == tool_name for t in rec.manifest.tools):
                return name
        return None

    def _capnet_dispatchable(self, net, plan, node, text: str) -> bool:
        """The strict bar for executing a capnet plan without the LLM.

        ALL of: the chosen node is a skill TOOL (never a pc/provider/
        mcp/memory/phone node), gate tier 1, health available; the
        router's top score carries the direct-name boost — the user
        NAMED the tool in the text (capnet's own "named directly"
        criterion) — so keyword-only matches, which are heuristic by
        design, count as fuzzy and NEVER execute; the tool is real in
        the approved registry; and the brain's tool takes NO required
        arguments (capnet selects tools, it does not invent args —
        anything needing arguments is the brain's turn).
        """
        if node is None or node.kind != "tool":
            return False
        if node.tier != 1 or node.health != "available":
            return False
        if not plan.ranked or plan.ranked[0].node_id != node.id:
            return False
        if plan.ranked[0].score < 4.0:
            return False  # no direct-name boost -> fuzzy, never executes
        if node.name.lower() not in text.lower():
            return False
        if self._capnet_tool_skill(node.name) is None:
            return False
        tool = self.brain.tools.get(node.name)
        if tool is None or tool.fn is None:
            return False
        required = (tool.parameters or {}).get("required") or []
        return not required

    def _capnet_route_turn(self, text: str):
        """Try the capability network for this turn (after the intent tier).

        capnet.select() routes the task over the whole network; the
        plan (chosen node + plain-language reason) is recorded as a
        capnet.plan session event EITHER WAY — dispatched or not — so
        the routing judgment is always auditable. Only a plan passing
        _capnet_dispatchable's strict bar executes, through the same
        gate-first dispatch the intent tier uses (via="capnet"), and
        the LLM is skipped. Everything else returns None: the brain
        handles the turn. Routing failures degrade to None — the
        network NEVER breaks a turn.
        """
        from types import SimpleNamespace
        from jarvis.capnet import select
        net = self._capability_network()
        if net is None:
            return None
        plan = select(net, text)
        try:
            self.store.emit(self.session_id, "capnet.plan",
                            {"task": text[:200], "chosen": plan.chosen,
                             "reason": plan.reason, "via": "capnet"},
                            actor="brain", trust="system")
        except Exception:
            pass  # the plan record is telemetry, never a turn dependency
        node = plan.chosen_node(net) if plan.chosen else None
        if not self._capnet_dispatchable(net, plan, node, text):
            return None
        shim = SimpleNamespace(tool=node.name, args={})
        try:
            return self._dispatch_routed(text, shim, via="capnet")
        except Exception:
            return None

    def _record_turn_outcomes(self, text: str, after_seq, result,
                              brain_used: bool) -> None:
        """CapNet feedback loop: fold this turn's results into outcomes.

        Reads the events THIS turn produced (seq > after_seq) from the
        session store: each tool.result is mapped back to its tool
        through the causal parent tool.call (tool.result payloads
        carry no name — the call does), then to its capnet node id
        (capnet's scheme: "tool:<name>", pc tools keep their dotted
        name). When the brain actually served the turn, the answering
        provider earns an outcome too (ok = the turn completed as
        answered/asked/approval). Everything lands as capnet.outcome
        events via record_outcome, which is what health_scores reads
        on the next network build. Telemetry: fully wrapped, a failure
        here NEVER breaks the turn it measures.
        """
        if after_seq is None:
            return
        try:
            from jarvis.capnet import record_outcome
            events = self.store.get_events(self.session_id, after_seq,
                                           100000)
            call_tool = {}
            for e in events:
                if e["type"] == "tool.call":
                    call_tool[e["event_id"]] = (e.get("payload")
                                                or {}).get("tool")
            for e in events:
                if e["type"] != "tool.result":
                    continue
                name = call_tool.get(e.get("causal_parent"))
                if not name:
                    continue
                node_id = name if name.startswith("pc.") else f"tool:{name}"
                record_outcome(self.store, node_id,
                               bool((e.get("payload") or {}).get("ok")),
                               task_hint=text, session_id=self.session_id)
            if brain_used and getattr(self, "_chain", None) is not None:
                via = self.last_provider
                if via and via not in ("none", "unknown", "stub"):
                    ok = result is not None and result.status in (
                        "answered", "asked", "approval_required")
                    record_outcome(self.store, f"provider:{via}", ok,
                                   task_hint=text,
                                   session_id=self.session_id)
        except Exception:
            pass

    # -- the turn ---------------------------------------------------------- #
    # -- morning digest routine (Ext-4 RoutineGuard) ---------------------- #
    def _routine_guard(self):
        """The app's RoutineGuard, built lazily (one per ChatApp).

        Schedule table: a single row — the morning digest, due 05:00
        local, fireable on the owner's first turn inside the
        05:00–12:00 window (the catch-up span covers the whole
        window, so a first turn at 09:00 still gets its briefing).
        A first contact after noon records the period MISSED instead:
        a stale "morning" briefing is never replayed in the afternoon.
        """
        guard = getattr(self, "_routine_guard_instance", None)
        if guard is None:
            from jarvis.routine_guard import RoutineGuard, RoutineSpec
            guard = RoutineGuard(str(self.data_dir), specs={
                "morning_digest": RoutineSpec(
                    name="morning_digest", period="day", due="05:00",
                    window=("05:00", "12:00"), budget_s=30.0,
                    catch_up_minutes=420.0),
            })
            self._routine_guard_instance = guard
        return guard

    def _maybe_morning_digest(self) -> None:
        """Fire the morning digest when the guard clears it.

        begin() claims the period BEFORE anything runs, so a crash
        mid-digest can never double-fire it. Fully wrapped like the
        evolution hook: a digest failure is noted and NEVER breaks
        a turn.

        ORDERING LAW: this runs at turn start, BEFORE this turn's
        user.message event exists — and a turn's identity everywhere
        else is "the opening user.message event id". So the session
        events are NOT emitted here; they are stashed and flushed by
        _flush_routine_events() once the turn's user.message exists,
        as its children. (The printed digest block is stdout, not a
        session event, and still greets before the answer.)
        """
        try:
            run = self._routine_guard().begin("morning_digest")
            if run is None:
                return  # not due / already handled / missed — silent
            try:
                from jarvis.morning_digest import digest_lines
                lines = digest_lines(str(self.data_dir))
            except Exception:
                run.finish("failed")
                raise
            if lines:
                print("[morning digest]")
                for line in lines:
                    print(f"  {line}")
            status = run.finish("fired")
            self._stash_routine_event(
                "routine.fired",
                {"name": "morning_digest", "status": status})
        except Exception as exc:
            self._stash_routine_event(
                "routine.digest_error",
                {"error": f"{type(exc).__name__}: {exc}"})

    def _stash_routine_event(self, etype: str, payload: dict) -> None:
        pending = getattr(self, "_pending_routine_events", None)
        if pending is None:
            pending = self._pending_routine_events = []
        pending.append((etype, payload))

    def _flush_routine_events(self) -> None:
        """Emit any stashed routine events as children of THIS turn's
        user.message (its event id via _current_turn_id). Called at
        every turn exit point, after dispatch — by then brain turns
        and routed turns alike have opened with their user.message.
        Never raises: evidence plumbing must not break a turn."""
        pending = getattr(self, "_pending_routine_events", None)
        if not pending:
            return
        self._pending_routine_events = []
        try:
            parent = self._current_turn_id()
        except Exception:
            parent = None
        for etype, payload in pending:
            try:
                self.store.emit(self.session_id, etype, payload,
                                actor="system", trust="system",
                                causal_parent=parent)
            except Exception:
                pass

    def turn(self, text: str) -> None:
        self._turn_id += 1
        # Common social turns should not enter the tool planner. This also
        # keeps a broken provider from turning "how are you?" into a finance task.
        simple_reply = _simple_chat_reply(text)
        if simple_reply is not None:
            reply = simple_reply
            user_event = None
            try:
                user_event = self.store.emit(
                    self.session_id, "user.message", {"text": text},
                    actor="user", trust="user")
            except Exception:
                pass
            try:
                self.store.emit(
                    self.session_id, "brain.reply", {"text": reply},
                    actor="brain", trust="user",
                    causal_parent=user_event)
            except Exception:
                pass
            print(f"[answered] {reply}")
            return
        # Idle self-evolution review (Ext-7): once a day, when the user
        # has been idle long enough, JARVIS reviews itself — foundry
        # scan, yesterday's diary, memory consolidation. The guard is
        # the only per-turn cost (one small state read + one MAX(ts)
        # query); run_review itself never raises, and anything failing
        # here is swallowed with an event note — a review must NEVER
        # break a turn.
        try:
            from datetime import datetime, timezone
            from jarvis.evolution_runner import (
                last_user_turn_at, read_last_run, run_review, should_run)
            _now = datetime.now(timezone.utc)
            if should_run(read_last_run(self.data_dir), _now,
                          last_user_turn=last_user_turn_at(self.store)):
                run_review(self.data_dir, self.store, self.memory, _now)
        except Exception as exc:
            try:
                self.store.emit(
                    self.session_id, "evolution.review_error",
                    {"error": f"{type(exc).__name__}: {exc}"},
                    actor="system", trust="system")
            except Exception:
                pass
        # Morning digest (Ext-4): the RoutineGuard decides — due,
        # claimed, or missed — JARVIS runs only what it clears. The
        # helper is fully wrapped; it cannot break the turn.
        self._maybe_morning_digest()
        # Ring any due reminders before the user's turn (call-ringing model:
        # they appear once, then clear).
        try:
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location(
                "reminders_skill_check",
                str(Path(__file__).resolve().parent.parent /
                    "skills" / "reminders" / "skill.py"))
            _rm = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_rm)

            class _RCtx:
                pass

            _rc = _RCtx()
            _rc.jail_dir = str(self.data_dir)
            for due in _rm.purge_due(_rc):
                print(f"[reminder] {due['text']}")
        except Exception:
            pass
        # Inject relevant learned corrections into this turn's context.
        try:
            from jarvis.golden_pairs import PairStore
            store = PairStore(self.data_dir / "golden_pairs.jsonl")
            pairs = store.relevant(text)
            self.brain._learned_context = store.format_for_prompt(pairs)
        except Exception:
            self.brain._learned_context = ""
        print("[thinking]")
        # CapNet outcome watermark: events with seq beyond this belong
        # to THIS turn; _record_turn_outcomes reads them back at the
        # end of the turn for the network's feedback loop.
        turn_mark = None
        try:
            _prior = self.store.get_events(self.session_id, 0, 100000)
            turn_mark = _prior[-1]["seq"] if _prior else 0
        except Exception:
            turn_mark = None
        result = None
        try:
            result = self._route_turn(text)
        except Exception:
            result = None  # the intent tier must never break a turn
        if result is None:
            # Capability-network tier: deterministic intents already
            # had their chance above and still win; the network routes
            # only unambiguous, named, tier-1 tasks (see
            # _capnet_dispatchable) and merely records its plan for
            # everything else.
            try:
                result = self._capnet_route_turn(text)
            except Exception:
                result = None  # the network tier must never break a turn
        brain_used = result is None
        if result is None:
            try:
                result = self.brain.respond(self.session_id, text,
                                            self._allowances)
            except Exception as exc:
                print(f"[error] Brain failed honestly: {exc}")
                traceback.print_exc()
                self._flush_routine_events()
                return
        if result.status == "approval_required":
            req = result.approval_request or {}
            gate_req = req.get("request", {}) or {}
            tool_info = {"tier": 3, "capabilities": [], "name": req.get("tool", "")}
            # Recompute tier from the real registry (never trust the dict).
            for rec in self.registry._records.values():
                if rec.manifest:
                    for t in rec.manifest.tools:
                        if t.name == req.get("tool"):
                            tool_info = {"tier": t.tier,
                                         "capabilities": list(t.capabilities),
                                         "name": t.name}
            if not hasattr(self, "_approval_budget"):
                self._approval_budget = self._approvals.ApprovalBudget(
                    str(self.data_dir / "approval_budget.json"))
            if not hasattr(self, "_approval_seq"):
                self._approval_seq = 0
                import secrets as _secrets
                words = ["ember", "quartz", "harbor", "meadow", "cipher",
                         "falcon", "grove", "signal"]
                self._visual_secret = "-".join(
                    _secrets.choice(words) for _ in range(3))
            self._approval_seq += 1
            areq = self._approvals.ApprovalRequest.from_gate(
                gate_req, tool_info=tool_info,
                goal=text, seq_no=self._approval_seq,
                visual_secret=self._visual_secret)
            print("[waiting approval] full dialog below")
            input_fn = getattr(self, "_gui_input_fn", None) or input
            approved = self._approvals.request_approval(
                areq, budget=self._approval_budget, input_fn=input_fn)
            if approved:
                # Turn-scoped: the approved execution journals under the
                # same user.message event id that opened this turn, so
                # /undo-turn can reverse it with the rest of the turn.
                decision, out = self.gate.execute_approved(
                    gate_req.get("token", ""), req.get("tool", ""),
                    req.get("args", {}), executor=self._executor,
                    session_id=self.session_id,
                    turn_id=self._current_turn_id())
                print(f"[approved] {decision.reason}")
                if out:
                    print(out[:500])
            else:
                print("[denied] Not executed, sir.")
            self._flush_routine_events()
            self._record_turn_outcomes(text, turn_mark, result, brain_used)
            return
        state = {
            "answered": "[answered]",
            "asked": "[asked]",
            "stopped": "[stopped]",
        }.get(result.status, f"[{result.status}]")
        print(f"{state} {result.text}")
        self._flush_routine_events()
        self._record_turn_outcomes(text, turn_mark, result, brain_used)

        # Learning loop (DPO-in-miniature): if THIS message was a correction
        # of the PREVIOUS answer, save the pair — JARVIS learns from it.
        try:
            from jarvis.golden_pairs import PairStore, GoldenPair, detect_correction
            correction = detect_correction(text)
            if correction and getattr(self, "_last_exchange", None):
                prev_q, prev_a = self._last_exchange
                # Anti-poisoning (Builder A, CowAgent doctrine): a
                # "correction" that is really a negative capability claim
                # ("that is beyond my capabilities", "the web tool
                # doesn't work") must never be stored as a lesson —
                # stored defeats harden into self-refusals. filter_lesson
                # is the storage gate; lazy import, as chat already
                # imports brain lazily throughout __init__.
                from jarvis.brain import filter_lesson
                if not filter_lesson(correction):
                    print("[learned] Skipped — that phrasing claims a "
                          "capability limit, and defeats are not stored "
                          "as lessons.")
                else:
                    store = PairStore(self.data_dir / "golden_pairs.jsonl")
                    store.save(GoldenPair(context=prev_q,
                                          bad_response=prev_a,
                                          good_response=correction))
                    print("[learned] Noted your correction — "
                          "I will do it that way.")
            if result.status == "answered":
                self._last_exchange = (text, result.text)
        except Exception:
            pass  # Learning never breaks the conversation.

    def _pc_call(self, tool_name: str, args: dict):
        """Route pc.* tools to the PCController. Tier-3 (pc.shell) never
        reaches here — the brain returns approval_required first."""
        op = tool_name[3:]
        if op == "observe":
            snap = self._pc.observe(window=args.get("window"))
            return {"elements": len(snap.elements)}
        if op == "screenshot":
            data = self._pc.screenshot(region=args.get("region"))
            return {"bytes": len(data), "note": "RAM only, never disk"}
        if op == "click":
            return self._pc.click_element(args["element_id"])
        if op == "type":
            return self._pc.type_into_field(args["element_id"], args.get("text", ""))
        if op == "key":
            return self._pc.press_key(args.get("key", ""))
        if op == "launch_app":
            return self._pc.launch_app(args["name"])
        if op == "open_url":
            url = str(args.get("url", "")).strip()
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("only complete HTTP/HTTPS URLs can be opened")
            import webbrowser
            if not webbrowser.open(url, new=2):
                raise RuntimeError("Windows did not confirm that the browser opened")
            return {"ok": True, "url": url, "detail": "opened in the default browser"}
        if op == "ground":
            return self._pc.ground_target(args["query"])
        raise RuntimeError(f"unknown pc op: {op}")

    def _executor(self, tool_name: str, args: dict):
        from jarvis.skills.registry import SkillContext
        ctx = SkillContext(
            skill_name="chat", capabilities=self._allowances,
            jail_dir=str(self.data_dir), turn_id=self._turn_id)
        def risk_gate(tn, tier, a, c) -> bool:
            d = self.gate.check(tn, a, self._allowances)
            return d.verdict in (self._Verdict.ALLOW, self._Verdict.ALLOW_WITH_UNDO)
        result = self.registry.dispatch(tool_name, args, ctx, risk_gate)
        if not result.get("ok"):
            raise RuntimeError(f"{result.get('code')}: {result.get('message')}")
        return result["result"]

    def start_phone(self) -> None:
        """Wave 3: Telegram remote. Token from keyring/env, never a file."""
        from jarvis import phone as phone_mod
        from jarvis.config import Secrets
        secrets = Secrets()
        token = secrets.get("telegram_bot_token", "")
        if not token:
            print("[phone] No bot token. Set it in Settings (phone tab) first, sir.")
            print("[phone] Get one from @BotFather on Telegram — 30 seconds.")
            return
        user_id = self.config.get("phone.allowed_user_id", 0) if hasattr(
            self.config, "get") else 0

        def brain_fn(text: str, uid: int) -> str:
            sid = self.store.create_session("owais", "phone")
            res = self.brain.respond(sid, text, ["fs.read", "time.read"])
            return str(res)

        remote = phone_mod.PhoneRemote(
            brain_fn=brain_fn, gate=self.gate,
            allowed_user_id=user_id or None,
            token=token, executor=self._executor,
            on_alert=lambda m: print(f"[phone alert] {m}"),
            # Ext-3 persistence: the allow-always allowlist and the
            # reconnect watermark only activate when the remote knows
            # where its data dir is.
            data_dir=str(self.data_dir))
        print("[phone] Pair from Telegram: the PC will show a 6-digit code.")
        print("[phone] Press Ctrl+C to stop.")
        import time
        try:
            while True:
                remote.poll_once()
                time.sleep(2)
        except KeyboardInterrupt:
            remote.stop()
            print("\n[phone] Stopped.")

    def start_voice(self) -> None:
        """Wave 4: full voice loop. Needs mic + speakers + models on the PC;
        without them it says so plainly and stays in text mode."""
        from jarvis import voice_loop as vl_mod
        from jarvis import stt as stt_mod
        from jarvis import tts as tts_mod

        # -- engines: real where installed, loud stub where not ------------- #
        try:
            # "auto" = the TranscriberChain: Hinglish engine first (its
            # weights on the machine), stock whisper next, the LOUD stub
            # only when no real engine exists — never a silent downgrade.
            transcriber = stt_mod.create_transcriber(engine="auto")
        except Exception as exc:
            print(f"[voice] STT unavailable ({exc}) — voice needs "
                  "faster-whisper. Staying in text mode, sir.")
            return
        engine = tts_mod.pick_engine("auto")

        # -- sentence-buffering audio sink ---------------------------------- #
        # The loop's Speaker iterates words with no real timing; the tts
        # engine renders real audio per sentence (synchronous, blocking).
        # Buffer words per sentence; flush on sentence change; after each
        # turn flush the remainder only if the turn completed (on interrupt
        # the buffer is discarded — the user is speaking, we go silent).
        class _SentenceSink:
            def __init__(self) -> None:
                self.buf: list[str] = []
                self.si = -1

            def __call__(self, word: str, si: int, wi: int) -> None:
                if si != self.si:
                    self.flush()
                    self.si = si
                self.buf.append(word)

            def flush(self) -> None:
                if not self.buf:
                    return
                raw = " ".join(self.buf)
                self.buf = []
                # Speech policy (Builder B): this sink speaks through
                # the SAME cleaner as the voice loop — markdown out,
                # secrets redacted, clauses chunked — so the GUI path
                # can never read out markup or a key. Same fallback
                # discipline as voice_loop: if the cleaner itself
                # fails, the raw sentence is spoken; a sentence that
                # cleans to nothing (a bare code fence) is skipped.
                # Speech never breaks because the cleaner did.
                try:
                    from jarvis.speech_policy import clean_for_tts
                    chunks = clean_for_tts(raw)
                except Exception:
                    chunks = [raw]
                for chunk in chunks:
                    try:
                        engine.speak_sentence(chunk,
                                              on_word=lambda i: None)
                    except Exception as exc:
                        print(f"[voice] tts failed: {exc}")

            def discard(self) -> None:
                self.buf = []

        sink = _SentenceSink()

        # -- wake word: the real engine, built ONCE ---------------------- #
        # jarvis.wakeword's factory walks its preference order (Voicute
        # -> openWakeWord) and returns the first engine that can run on
        # this machine. When none can, it raises with EVERY engine's
        # exact reason — printed once here, after which wake_fn stays
        # the honest stub (voice still runs via the non-wake paths).
        # A detection is never faked.
        wake_engine = None
        try:
            from jarvis import wakeword as ww_mod
            wake_engine = ww_mod.create_wake_engine()
        except Exception as exc:
            print(f"[voice] Wake word unavailable: {exc}")
            wake_engine = None
        if wake_engine is not None:
            try:
                heard = ", ".join(wake_engine.keywords())
            except Exception:
                heard = "Jarvis"
            print(f"[voice] Wake word armed ({wake_engine.name}): {heard}")

        def brain_fn(text: str) -> str:
            res = self.brain.respond(self.session_id, text, self._allowances)
            return str(res)

        def stt_fn(audio: bytes) -> dict:
            return transcriber.transcribe(audio)

        if wake_engine is not None:
            def wake_fn(chunk: bytes) -> dict:
                """Feed one mic chunk to the wake engine; map its
                WakeDetection onto the loop's {detected, score, word}
                shape. The engine owns its false-wake cooldown."""
                try:
                    det = wake_engine.feed_frame(chunk)
                except Exception:
                    # A mid-loop engine failure degrades to "no wake"
                    # — never a crash, never a phantom detection.
                    return {"detected": False, "score": 0.0, "word": ""}
                if det is None:
                    return {"detected": False,
                            "score": float(wake_engine.last_score or 0.0),
                            "word": ""}
                return {"detected": True, "score": float(det.score),
                        "word": det.keyword}
        else:
            def wake_fn(chunk: bytes) -> dict:
                return {"detected": False, "score": 0.0, "word": ""}

        # -- mic adapter: MicStream is an iterator; the loop wants read/close - #
        class _MicReader:
            def __init__(self, mic) -> None:
                self._mic = mic.open()
                self._it = iter(self._mic)
                self._closed = False

            def read(self):
                if self._closed:
                    return None
                try:
                    return next(self._it)
                except StopIteration:
                    return None
                except Exception:
                    return None

            def close(self) -> None:
                self._closed = True
                self._mic.close()

        loop = vl_mod.VoiceLoop(
            mic_fn=lambda: _MicReader(stt_mod.MicStream()),
            vad_fn=lambda chunk: bool(stt_mod.vad_segments(chunk, 16000)),
            wake_fn=wake_fn,
            stt_fn=stt_fn,
            brain_fn=brain_fn,
            audio_out=sink,
        )
        print("[voice] Say 'Jarvis'… (Ctrl+C to stop)")
        try:
            while True:
                try:
                    outcome = loop.wait_for_wake(session_id=self.session_id)
                except Exception as exc:
                    print(f"[voice] Cannot start: {exc}")
                    print("[voice] Staying in text mode, sir.")
                    return
                if outcome.status == "mic_closed":
                    print("[voice] Mic closed.")
                    break
                if outcome.status != "wake":
                    continue
                turn = loop.run_turn(session_id=self.session_id)
                if turn.status == "completed":
                    sink.flush()
                else:
                    sink.discard()
                if turn.status == "error":
                    print(f"[voice] {turn.reply_text}")
        except KeyboardInterrupt:
            print("\n[voice] Stopped. Back to text, sir.")

    # -- API key management (/key, /keys) ---------------------------------- #
    @staticmethod
    def _key_providers() -> set:
        from jarvis.llm_compat import all_presets, set_custom_dir
        return set(all_presets()) | {"omniroute", "telegram_bot"}

    def _store_key(self, provider: str, key: str) -> None:
        """Store a key. Numbered slots for multiples."""
        from jarvis.config import Secrets
        secrets = Secrets(data_dir=str(self.data_dir))
        base = f"{provider}_api_key"
        if secrets.get(base):
            i = 2
            while secrets.get(f"{base}_{i}"):
                i += 1
            secrets.set(f"{base}_{i}", key)
        else:
            secrets.set(base, key)
        print(f"[keys] (stored via {secrets.storage_note})")

    def _count_keys(self, provider: str) -> int:
        from jarvis.config import Secrets
        secrets = Secrets(data_dir=str(self.data_dir))
        base = f"{provider}_api_key"
        n = 1 if secrets.get(base) else 0
        i = 2
        while secrets.get(f"{base}_{i}"):
            n += 1
            i += 1
        return n

    # -- slash commands (shared by CLI and GUI) --------------------------- #
    def handle_command(self, text: str) -> bool:
        """Handle /commands. Returns True if text was a command (so the
        caller must NOT send it to the brain). The GUI and CLI both call
        this — a /key pasted in the window can never reach the brain."""
        if text == "/quit":
            print("[stopped] Session saved. Goodbye, sir.")
            return True
        if text == "/help":
            print("Commands: /quit, /session (show session id), "
                  "/skills (list), /capabilities [name] (what I can do), "
                  "/patterns (review noticed patterns), "
                  "/memory <fact> (remember), /recall <q>, "
                  "/undo-turn (reverse the last turn's effects), "
                  "/key <paste-your-key> (store API key), /keys (list), "
                  "/keymove <wrong> <right> (fix misidentified key), "
                  "/provider <name> <url> <model> (add company)")
            return True
        if text == "/undo-turn":
            self._undo_last_turn()
            return True
        if text == "/session":
            print(f"[session] {self.session_id}")
            return True
        if text == "/skills":
            for name, rec in self.registry._records.items():
                q = "" if rec.approved else " [quarantined]"
                print(f"  - {name}{q}")
            return True
        if text.startswith("/memory "):
            fact = text[8:].strip()
            if "=" in fact:
                k, v = fact.split("=", 1)
                self.memory.write_fact(k.strip(), v.strip(), source="cli",
                                       tier="user", confidence=1.0)
                print(f"[memory] Remembered: {k.strip()}")
            else:
                print("[memory] Use: /memory key = value")
            return True
        if text.startswith("/recall "):
            for hit in self.memory.recall(text[8:].strip())[:5]:
                flag = " [quarantined]" if hit.get("quarantined") else ""
                print(f"  - {hit.get('snippet', '')[:120]}{flag}")
            return True
        if text.startswith("/key "):
            # /key <key>            — bot figures out the provider
            # /key <provider> <key> — explicit (overrides detection)
            # The key value is NEVER printed, logged, or stored elsewhere.
            #
            # F-12 (Option A): NO key probing. probe_key() used to spray the
            # raw key as a Bearer token at up to 13 providers' endpoints to
            # "identify" it — twelve strangers logging a key that isn't
            # theirs, plus a ~100s hang. On fingerprint miss we now ask for
            # the explicit form instead. The owner's call, per his order.
            from jarvis.llm_compat import fingerprint_key
            rest = text[5:].strip()
            parts = rest.split(None, 1)
            pname, key = None, None
            if len(parts) == 2 and parts[0].lower() in self._key_providers():
                pname, key = parts[0].lower(), parts[1].strip()
            elif len(parts) >= 1:
                key = parts[-1].strip() if len(parts) == 2 else parts[0].strip()
                pname = fingerprint_key(key)
            if not key:
                print("[keys] Use: /key <paste-your-key>")
                return True
            if pname is None or pname not in self._key_providers():
                print("[keys] Couldn't identify that key from its shape, "
                      "and I won't probe providers with it (privacy).")
                print("[keys] Known: " + ", ".join(sorted(self._key_providers())))
                print("[keys] Be explicit: /key <provider> <key>")
                return True
            self._store_key(pname, key)
            print(f"[keys] That's a {pname} key — stored (keyring, never shown). "
                  f"Restart JARVIS to use it, sir.")
            return True
        if text == "/keys":
            for pname in sorted(self._key_providers()):
                n = self._count_keys(pname)
                mark = f"{n} key(s)" if n else "no key"
                print(f"  - {pname}: {mark}")
            return True
        if text.startswith("/keymove "):
            # /keymove <wrong-provider> <right-provider> — move the most
            # recently stored key when auto-detect guessed wrong.
            # ("no that's a gemini key" -> /keymove openrouter gemini)
            from jarvis.config import Secrets
            parts = text[9:].strip().split(None, 1)
            if len(parts) != 2:
                print("[keys] Use: /keymove <wrong-provider> <right-provider>")
                return True
            wrong, right = parts[0].lower(), parts[1].lower()
            providers = self._key_providers()
            if wrong not in providers or right not in providers:
                print(f"[keys] Unknown provider. Known: " +
                      ", ".join(sorted(providers)))
                return True
            if wrong == right:
                print("[keys] Same provider — nothing to move.")
                return True
            secrets = Secrets(data_dir=str(self.data_dir))
            # Find the last slot under the wrong provider.
            base_wrong = f"{wrong}_api_key"
            slot, key = None, None
            i = 2
            last = secrets.get(base_wrong)
            if last:
                slot, key = base_wrong, last
                while True:
                    extra = secrets.get(f"{base_wrong}_{i}")
                    if not extra:
                        break
                    slot, key = f"{base_wrong}_{i}", extra
                    i += 1
            if key is None:
                print(f"[keys] No key stored under {wrong}.")
                return True
            # Wipe it from the wrong provider (overwrite, then rely on
            # get() returning falsy for empty).
            secrets.set(slot, "")
            # Store under the right provider (reuses numbered slots).
            self._store_key(right, key)
            print(f"[keys] Moved last {wrong} key -> {right}. "
                  f"Restart JARVIS to use it, sir.")
            return True
        if text.startswith("/provider "):
            # /provider <name> <base_url> <model> — register any
            # OpenAI-compatible API (any company).
            from jarvis.llm_compat import add_custom_provider
            parts = text[10:].strip().split(None, 2)
            if len(parts) != 3:
                print("[keys] Use: /provider <name> <base_url> <model>")
                print("[keys] Example: /provider myco https://api.myco.ai/v1 my-model")
                return True
            try:
                add_custom_provider(*parts)
                print(f"[keys] Provider '{parts[0].lower()}' registered. "
                      f"Now paste its key: /key {parts[0].lower()} <key>")
            except ValueError as exc:
                print(f"[keys] {exc}")
            return True
        if text == "/capabilities" or text.startswith("/capabilities "):
            self._print_capabilities(text[len("/capabilities"):].strip())
            return True
        if text == "/patterns" or text.startswith("/patterns "):
            self._patterns_command(text[len("/patterns"):].strip())
            return True
        return False

    def _patterns_command(self, arg: str = "") -> None:
        """Review the pattern proposals JARVIS derived from real usage.

        No argument: list what's pending, numbered. "confirm <n>" keeps
        one — it becomes a memory fact. "decline <n>" dismisses it FOR
        GOOD: PatternStore.decline writes the durable suppression, so
        a declined pattern is never proposed again. Numbers refer to
        the pending list exactly as printed.
        """
        try:
            from jarvis.patterns import PatternStore
            store = PatternStore(self.data_dir, memory=self.memory)
        except Exception as exc:
            print(f"[patterns] unavailable ({exc})")
            return
        if not arg:
            pending = store.pending()
            if not pending:
                print("[patterns] No patterns waiting for your "
                      "decision, sir.")
                return
            print("[patterns] Waiting for your decision:")
            for i, rec in enumerate(pending, 1):
                print(f"  {i}. {rec.get('text') or rec.get('key', '')}")
            print("[patterns] /patterns confirm <n> keeps one; "
                  "/patterns decline <n> dismisses it for good.")
            return
        parts = arg.split()
        if len(parts) == 2 and parts[0] in ("confirm", "decline"):
            action, num = parts
            pending = store.pending()
            try:
                idx = int(num)
            except ValueError:
                idx = 0
            if not 1 <= idx <= len(pending):
                print(f"[patterns] No pending pattern #{num}, sir — "
                      "run /patterns to see the list.")
                return
            rec = pending[idx - 1]
            label = rec.get("text") or rec.get("key", "")
            try:
                if action == "confirm":
                    store.confirm(rec["key"])
                    print(f"[patterns] Kept: {label}")
                else:
                    store.decline(rec["key"])
                    print(f"[patterns] Dismissed for good: {label}")
            except Exception as exc:
                print(f"[patterns] {exc}")
            return
        print("[patterns] Use: /patterns, /patterns confirm <n>, "
              "/patterns decline <n>")

    def _print_capabilities(self, arg: str = "") -> None:
        """Answer "what can you do" from the LIVE capability network.

        No argument: the network's own map (describe — groups, health,
        alternatives). With a name ("/capabilities now" or a node id
        like "tool:now"): that node's briefing (explain — purpose,
        use/avoid, needs, alternatives, measured record). Straight
        from capnet, never a memorized list.
        """
        try:
            from jarvis.capnet import describe, explain
            net = self._capability_network()
            if net is None:
                print("[capabilities] The network is unavailable, sir.")
                return
            if arg:
                print(explain(net, arg))
            else:
                print(describe(net, max_chars=4000))
        except Exception as exc:
            print(f"[capabilities] unavailable ({exc})")

    # -- main loop ---------------------------------------------------------- #
    def run(self) -> None:
        print("JARVIS v2 — Wave 1 text chat. Type /help. Ctrl+C saves and exits.")
        print(f"[session] {self.session_id}")
        while True:
            try:
                text = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[stopped] Session saved. Goodbye, sir.")
                break
            if not text:
                continue
            if text == "/quit":
                break
            if self.handle_command(text):
                continue
            self.turn(text)


def main() -> None:
    ap = argparse.ArgumentParser(description="JARVIS v2 Wave-1 text chat")
    ap.add_argument("--data-dir", default=None,
                    help="data directory (default: ./data)")
    ap.add_argument("--pc", action="store_true", default=True,
                    help="enable PC control tools (default: on)")
    ap.add_argument("--no-pc", action="store_true",
                    help="disable PC control tools")
    ap.add_argument("--phone", action="store_true",
                    help="start Telegram phone remote instead of chat")
    ap.add_argument("--voice", action="store_true",
                    help="start voice loop (needs mic + speakers + models)")
    args = ap.parse_args()
    base_dir = Path(__file__).resolve().parent.parent
    data_dir = Path(args.data_dir) if args.data_dir else base_dir / "data"

    problems = preflight(base_dir, data_dir)
    if problems:
        print("[preflight] FATAL — refusing to start:")
        for p in problems:
            print(f"  ! {p}")
        sys.exit(2)
    print("[preflight] all checks passed.")
    for w in startup_warnings(data_dir):
        print(f"[warn] {w}")

    app = ChatApp(base_dir, data_dir, enable_pc=args.pc and not args.no_pc)
    if args.voice:
        app.start_voice()
    elif args.phone:
        app.start_phone()
    else:
        app.run()


if __name__ == "__main__":
    main()
