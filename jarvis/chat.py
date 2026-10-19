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
FIRST_PARTY_SKILLS = ("echo", "notes", "clock")


class ChatApp:
    def __init__(self, base_dir: Path, data_dir: Path) -> None:
        self.base_dir = base_dir
        self.data_dir = data_dir

        from jarvis.rules import load_rules, RulesError
        from jarvis.config import Config, Field
        from jarvis.session_store import SessionStore
        from jarvis.memory import Memory
        from jarvis.skills.registry import SkillRegistry, SkillContext
        from jarvis.gate import Gate, Verdict
        from jarvis.brain import Brain, ToolDef
        from jarvis.llm_ollama import make_llm_call
        from jarvis import approvals as approvals_mod

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

        self.registry = SkillRegistry(base_dir / "skills", data_dir)
        self.registry.discover()
        for name in FIRST_PARTY_SKILLS:
            try:
                self.registry.approve(name)
            except Exception as exc:
                print(f"[warn] could not approve first-party skill {name!r}: {exc}")

        # The gate's registry: tool_name -> {tier, schema, capabilities}.
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
                }
        self.gate = Gate(rules={}, skill_registry=gate_registry)
        self._Verdict = Verdict

        # Brain tools: ToolDef(name, fn) where fn runs the skill pipeline.
        # The gate already checked before fn is called; the registry's
        # risk-gate stage re-checks (defense in depth, cheap).
        def make_fn(tool_name: str):
            def fn(args: dict):
                ctx = SkillContext(
                    skill_name="chat",
                    capabilities=TURN_ALLOWANCES,
                    jail_dir=str(data_dir),
                    turn_id=self._turn_id,
                )
                def risk_gate(tn: str, tier: int, a: dict, c) -> bool:
                    d = self.gate.check(tn, a, TURN_ALLOWANCES)
                    return d.verdict in (Verdict.ALLOW, Verdict.ALLOW_WITH_UNDO)
                result = self.registry.dispatch(tool_name, args, ctx, risk_gate)
                if not result.get("ok"):
                    raise RuntimeError(
                        f"skill pipeline: {result.get('code')}: {result.get('message')}")
                return result["result"]
            return fn

        tools = []
        for n, info in gate_registry.items():
            desc = next(
                (t.description for rec in self.registry._records.values()
                 if rec.manifest for t in rec.manifest.tools if t.name == n),
                n,
            )
            tools.append(ToolDef(name=n, description=desc,
                                 parameters=info["schema"], fn=make_fn(n)))
        self._turn_id = 0
        # Real model if available, stub otherwise (loud banner, never silent).
        llm_call = make_llm_call(rules=self.rules)
        self.brain = Brain(
            gate=self.gate,
            session_store=self.store,
            rules=self.rules,
            llm_call=llm_call,
            tools=tools,
            llm_off_machine=False,  # Wave 2: local only, no DCL redaction needed
        )
        self._approvals = approvals_mod
        self.session_id = self.store.create_session("owais", "cli")

    # -- the turn ---------------------------------------------------------- #
    def turn(self, text: str) -> None:
        self._turn_id += 1
        print("[thinking]")
        try:
            result = self.brain.respond(self.session_id, text, TURN_ALLOWANCES)
        except Exception as exc:
            print(f"[error] Brain failed honestly: {exc}")
            traceback.print_exc()
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
            approved = self._approvals.request_approval(
                areq, budget=self._approval_budget)
            if approved:
                decision, out = self.gate.execute_approved(
                    gate_req.get("token", ""), req.get("tool", ""),
                    req.get("args", {}), executor=self._executor)
                print(f"[approved] {decision.reason}")
                if out:
                    print(out[:500])
            else:
                print("[denied] Not executed, sir.")
            return
        state = {
            "answered": "[answered]",
            "asked": "[asked]",
            "stopped": "[stopped]",
        }.get(result.status, f"[{result.status}]")
        print(f"{state} {result.text}")

    def _executor(self, tool_name: str, args: dict):
        from jarvis.skills.registry import SkillContext
        ctx = SkillContext(
            skill_name="chat", capabilities=TURN_ALLOWANCES,
            jail_dir=str(self.data_dir), turn_id=self._turn_id)
        def risk_gate(tn, tier, a, c) -> bool:
            d = self.gate.check(tn, a, TURN_ALLOWANCES)
            return d.verdict in (self._Verdict.ALLOW, self._Verdict.ALLOW_WITH_UNDO)
        result = self.registry.dispatch(tool_name, args, ctx, risk_gate)
        if not result.get("ok"):
            raise RuntimeError(f"{result.get('code')}: {result.get('message')}")
        return result["result"]

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
                print("[stopped] Session saved. Goodbye, sir.")
                break
            if text == "/help":
                print("Commands: /quit, /session (show session id), "
                      "/skills (list), /memory <fact> (remember), /recall <q>")
                continue
            if text == "/session":
                print(f"[session] {self.session_id}")
                continue
            if text == "/skills":
                for name, rec in self.registry._records.items():
                    q = "" if rec.approved else " [quarantined]"
                    print(f"  - {name}{q}")
                continue
            if text.startswith("/memory "):
                fact = text[8:].strip()
                if "=" in fact:
                    k, v = fact.split("=", 1)
                    self.memory.write_fact(k.strip(), v.strip(), source="cli",
                                           tier="user", confidence=1.0)
                    print(f"[memory] Remembered: {k.strip()}")
                else:
                    print("[memory] Use: /memory key = value")
                continue
            if text.startswith("/recall "):
                for hit in self.memory.recall(text[8:].strip())[:5]:
                    flag = " [quarantined]" if hit.get("quarantined") else ""
                    print(f"  - {hit.get('snippet', '')[:120]}{flag}")
                continue
            self.turn(text)


def main() -> None:
    ap = argparse.ArgumentParser(description="JARVIS v2 Wave-1 text chat")
    ap.add_argument("--data-dir", default=None,
                    help="data directory (default: ./data)")
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

    app = ChatApp(base_dir, data_dir)
    app.run()


if __name__ == "__main__":
    main()
