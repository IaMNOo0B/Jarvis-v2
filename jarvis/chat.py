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
FIRST_PARTY_SKILLS = ("echo", "notes", "clock", "knowledge", "web", "code")


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
        # Wave 3: PC control tools. Enabled by default — the owner asked
        # for full capability ("he can do all the stuff like you do").
        # Safety comes from the approval gates (tier-2 announces, tier-3
        # needs explicit approval), not from hiding the tools.
        self._pc = None
        if enable_pc:
            from jarvis import pc_control
            import platform
            if platform.system() == "Windows":
                self._pc = pc_control.PCController()
            else:
                print("[pc] Not Windows — PC control runs on the FAKE backend "
                      "(structure real, no real clicks).")
                self._pc = pc_control.PCController(
                    backend=pc_control.FakeUiaBackend())
            gate_registry.update(pc_control.as_gate_registry())
        self.gate = Gate(rules={}, skill_registry=gate_registry)
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
        # Order: keyed cloud (smartest) -> Ollama local -> OmniRoute ->
        # keyless Pollinations. The owner's keys win when they exist.
        providers = []
        providers.extend(keyed)
        if ollama_provider is not None:
            providers.append(ollama_provider)
        if omni_provider is not None:
            providers.append(omni_provider)
        if poll_provider is not None:
            providers.append(poll_provider)
        if providers:
            chain = FallbackChain.local_first(*providers)
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
        except Exception:
            pass
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
        )
        self._approvals = approvals_mod
        self.session_id = self.store.create_session("owais", "cli")

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

    # -- the turn ---------------------------------------------------------- #
    def turn(self, text: str) -> None:
        self._turn_id += 1
        print("[thinking]")
        try:
            result = self.brain.respond(self.session_id, text, self._allowances)
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
            input_fn = getattr(self, "_gui_input_fn", None) or input
            approved = self._approvals.request_approval(
                areq, budget=self._approval_budget, input_fn=input_fn)
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
            on_alert=lambda m: print(f"[phone alert] {m}"))
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
            transcriber = stt_mod.FasterWhisperTranscriber()
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
                if self.buf:
                    try:
                        engine.speak_sentence(
                            " ".join(self.buf), on_word=lambda i: None)
                    except Exception as exc:
                        print(f"[voice] tts failed: {exc}")
                    self.buf = []

            def discard(self) -> None:
                self.buf = []

        sink = _SentenceSink()

        def brain_fn(text: str) -> str:
            res = self.brain.respond(self.session_id, text, self._allowances)
            return str(res)

        def stt_fn(audio: bytes) -> dict:
            return transcriber.transcribe(audio)

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
                  "/skills (list), /memory <fact> (remember), /recall <q>, "
                  "/key <paste-your-key> (store API key), /keys (list), "
                  "/keymove <wrong> <right> (fix misidentified key), "
                  "/provider <name> <url> <model> (add company)")
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
        return False

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
