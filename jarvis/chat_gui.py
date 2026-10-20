"""JARVIS v2 — graphical chat window (Wave 4).

A real chatting space: no terminal, no voice module needed. The same
ChatApp brain, skills, gate, and approvals as the CLI — wrapped in a
tkinter window (stdlib, zero new dependencies).

Run:  python -m jarvis.chat_gui
      (or double-click chat-gui.bat on Windows)

Design notes:
- The brain runs in a worker thread; the UI never blocks.
- Brain output is captured by redirecting stdout into a thread-safe queue,
  then drained on the Tk event loop (root.after). No Tk calls from the
  worker thread — ever.
- Approval dialogs: the approvals module already prefers the native
  Windows dialog; typed confirmations use a small Tk modal via the
  _gui_input_fn hook in ChatApp.
- Brain states ([thinking], [answered], ...) become a status pill.
"""

from __future__ import annotations

import io
import json
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext, simpledialog
from pathlib import Path
from typing import Callable


class _GuiWriter(io.TextIOBase):
    """stdout replacement: lines go to a queue for the UI thread.

    `is_live` is a no-arg callable returning False once the turn that
    created this writer has been abandoned (F-09): late output from the
    orphaned worker is dropped instead of leaking into the next turn.
    """

    def __init__(self, q: queue.Queue[str],
                 is_live: "Callable[[], bool] | None" = None) -> None:
        self._q = q
        self._is_live = is_live or (lambda: True)

    def write(self, s: str) -> int:  # type: ignore[override]
        if s and self._is_live():
            self._q.put(("out", s))
        return len(s)

    def flush(self) -> None:  # type: ignore[override]
        pass


class TurnToken:
    """Monotonic turn token (F-09). Pure Python, no tkinter — unit-tested.

    Each turn captures a token; abandoning bumps the counter so any late
    output from the orphaned worker thread fails `is_live()` and is
    dropped. The brain call itself isn't interruptible (can't un-send an
    HTTP request), so abandon = stop waiting, not stop the call.
    """

    def __init__(self) -> None:
        self._id = 0

    def new_turn(self) -> int:
        self._id += 1
        return self._id

    def abandon(self) -> None:
        self._id += 1

    def is_live(self, token: int) -> bool:
        return token == self._id


# --------------------------------------------------------------------------- #
# HUD live feed (Team 4 steals) — pure Python, NO tkinter: unit-tested.
#
# Team 4's convergent findings, landed for a tkinter surface:
#  - Typed run-event stream (Itsme23476): the GUI renders work in progress
#    from the session store's typed events, not just final answers.
#  - Focus highlight (ditto): when a knowledge note is used, the feed NAMES
#    it — provenance you can watch, not a spinner you have to trust.
#  - State -> tempo (jincocodev): the status pill's color AND pulse speed
#    derive from brain state; you can read JARVIS's state across the room.
# EventFeed is the model; ChatWindow only polls + paints.
# --------------------------------------------------------------------------- #

FEED_MAX_LINES = 200

# Tool name -> feed phrase (present continuous, no trailing ellipsis —
# the renderer adds it, or " (approved)" after an approved execution).
_TOOL_ACTIONS = {
    "now": "Checking the time",
    "web_search": "Searching the web",
    "web_fetch": "Reading a page",
    "web_fetch_tree": "Reading a page",
    "knowledge_search": "Searching my notes",
    "reminder_set": "Setting a reminder",
    "reminder_list": "Checking your reminders",
    "reminder_cancel": "Cancelling a reminder",
    "reminder_due": "Checking due reminders",
    "notes_write": "Writing a note",
    "notes_read": "Reading a note",
    "notes_list": "Listing your notes",
    "code_read": "Reading code",
    "code_write": "Writing code",
    "code_edit": "Editing code",
    "code_run": "Running code in the sandbox",
    "system_status": "Checking system status",
    "volume_get": "Checking the volume",
    "volume_set": "Adjusting the volume",
    "clipboard_get": "Reading the clipboard",
    "clipboard_set": "Writing to the clipboard",
    "brightness_get": "Checking brightness",
    "brightness_set": "Adjusting brightness",
    "window_list": "Listing open windows",
    "finance_load_transactions": "Loading transactions",
    "finance_detect_subscriptions": "Looking for subscriptions",
    "finance_categorize": "Categorising a transaction",
    "price_watch_set": "Setting a price watch",
    "price_watch_check": "Checking a watched price",
    "price_watch_list": "Listing price watches",
    "echo": "Echoing",
    "observe": "Looking at the screen",
    "screenshot": "Taking a screenshot",
    "click": "Clicking",
    "type": "Typing",
    "key": "Pressing a key",
    "ground": "Locating it on screen",
    "find_text": "Searching the screen",
    "shell": "Running a shell command",
}


def _short(text, limit: int = 100) -> str:
    """One-line, whitespace-collapsed, length-capped rendering helper."""
    s = " ".join(str(text).split())
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def _tool_action(tool: str, args) -> str:
    """Human phrase for a tool call: 'Searching the web', 'Opening Notepad'."""
    bare = str(tool).rsplit(".", 1)[-1]  # pc.launch_app -> launch_app
    if bare == "launch_app":
        app = ""
        if isinstance(args, dict):
            for key in ("app", "name", "program", "target"):
                if args.get(key):
                    app = str(args[key])
                    break
        return f"Opening {app}" if app else "Opening an app"
    if bare in _TOOL_ACTIONS:
        return _TOOL_ACTIONS[bare]
    return f"Running {tool}"


def _knowledge_lookup(payload: dict):
    """(note_name, match_count) from a knowledge_search tool.result payload.

    The result's `output` is the tool's return value — a JSON string (or,
    depending on the path, an already-decoded dict), shaped either as the
    bare search result {matches: [...], count: n} or wrapped in the skill
    envelope {result: {...}}. Returns (None, None) when it doesn't parse
    as a knowledge result at all; (None, 0) for a genuine no-match.
    """
    data = payload.get("output")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return None, None
    if not isinstance(data, dict):
        return None, None
    inner = data.get("result")
    if not isinstance(inner, dict):
        inner = data
    matches = inner.get("matches")
    if not isinstance(matches, list):
        return None, None
    count = inner.get("count")
    if not isinstance(count, int):
        count = len(matches)
    if not matches:
        return None, count
    first = matches[0] or {}
    name = ""
    path = first.get("file")
    if path:
        name = str(path).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if not name and first.get("title"):
        name = str(first["title"])
    return (name or None), count


class EventFeed:
    """Session-store events -> short human feed lines + activity state.

    Pure Python (no tkinter) — unit-tested headless. Feed it batches from
    SessionStore.get_events() at any cadence: a seq cursor guarantees each
    event renders at most once (re-polls and overlapping batches are safe),
    and the buffer is capped at `max_lines` (oldest lines drop first).
    """

    def __init__(self, max_lines: int = FEED_MAX_LINES) -> None:
        self._max = max(1, int(max_lines))
        self._lines: list[str] = []
        self._cursor = 0
        self._activity = "idle"
        # tool.call event_id -> {"tool", "verdict"} so a tool.result can
        # name its tool and a knowledge result can name its note.
        self._calls: dict[str, dict] = {}

    @property
    def cursor(self) -> int:
        """Seq of the last consumed event — pass as get_events(after_seq=)."""
        return self._cursor

    @property
    def lines(self) -> list[str]:
        return list(self._lines)

    @property
    def activity(self) -> str:
        """Derived brain activity: idle | thinking | tool | approval |
        speaking. Feed it to pill_state() with the provider name."""
        return self._activity

    def consume(self, events) -> list[str]:
        """Render a batch of store events; returns only the NEW lines."""
        fresh = []
        for ev in events or []:
            if isinstance(ev, dict) and isinstance(ev.get("seq"), int):
                fresh.append(ev)
        fresh.sort(key=lambda e: e["seq"])
        added: list[str] = []
        for ev in fresh:
            if ev["seq"] <= self._cursor:
                continue  # already rendered — re-polls never duplicate
            self._cursor = ev["seq"]
            line = self._render(ev)
            if line:
                added.append(line)
                self._lines.append(line)
        if len(self._lines) > self._max:
            del self._lines[: len(self._lines) - self._max]
        return added

    # -- rendering ------------------------------------------------------- #
    def _render(self, ev: dict) -> "str | None":
        etype = ev.get("type", "")
        payload = ev.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        if etype == "user.message":
            self._activity = "thinking"
            return None
        if etype == "capnet.plan":
            return self._render_plan(payload)
        if etype == "tool.call":
            return self._render_call(ev, payload)
        if etype == "tool.result":
            return self._render_result(ev, payload)
        if etype == "approval.requested":
            self._activity = "approval"
            action = payload.get("action") or "a tool"
            return (f"Approval requested: {action} — "
                    "nothing runs until you approve")
        if etype == "recovery.escalated":
            summary = payload.get("summary") or ""
            if summary:
                return _short(f"Recovery: {summary}", 120)
            return "Recovery: a failure was escalated to you, sir"
        if etype == "brain.reply":
            self._activity = "idle"
            return None
        if etype == "voice.stage":
            stage = str(payload.get("stage", "")).lower()
            if "speak" in stage or stage == "tts":
                self._activity = "speaking"
            return None
        return None

    def _render_plan(self, payload: dict) -> "str | None":
        chosen = payload.get("chosen")
        if not chosen:
            return None  # a plan that chose nothing isn't feed-worthy
        name = str(chosen).split(":", 1)[-1]  # tool:web_search -> web_search
        reason = str(payload.get("reason") or "").strip()
        # CapNet reasons start "chose tool:<name> ..." — the line already
        # names the tool, so drop that prefix.
        reason = re.sub(r"^chose\s+\S+\s*[—–\-:]*\s*", "", reason,
                        flags=re.IGNORECASE)
        if reason:
            return _short(f"Plan: use {name} — {reason}", 120)
        return f"Plan: use {name}"

    def _render_call(self, ev: dict, payload: dict) -> str:
        tool = str(payload.get("tool") or "a tool")
        verdict = str(payload.get("gate_verdict") or "")
        self._calls[str(ev.get("event_id", ""))] = {
            "tool": tool, "verdict": verdict}
        if len(self._calls) > 1000:  # long session: forget the oldest calls
            for key in list(self._calls)[:500]:
                del self._calls[key]
        if verdict == "deny":
            self._activity = "thinking"
            line = f"Blocked by the gate: {tool}"
            reason = payload.get("reason")
            if reason:
                line += f" ({_short(reason, 60)})"
            return line
        if verdict == "require_approval" or payload.get("proposed"):
            self._activity = "approval"
            return f"Waiting for your approval: {tool}"
        self._activity = "tool"
        action = _tool_action(tool, payload.get("args") or {})
        if verdict == "allow_with_undo":
            return f"{action} (approved)"
        return action + "…"

    def _render_result(self, ev: dict, payload: dict) -> str:
        parent = self._calls.get(str(ev.get("causal_parent") or ""), {})
        tool = parent.get("tool", "")
        self._activity = "thinking"  # the brain deliberates on every result
        if payload.get("postcondition_failed"):
            fails = payload.get("postcondition_failures") or []
            detail = f" ({', '.join(str(f) for f in fails)})" if fails else ""
            return (f"Delivery check failed: {tool or 'tool'}{detail} — "
                    "treat as not done")
        if payload.get("ok"):
            if tool == "knowledge_search":
                name, count = _knowledge_lookup(payload)
                if name:
                    extra = (f" (+{count - 1} more)"
                             if count and count > 1 else "")
                    return f"Looked up: {name}{extra}"
                if count == 0:
                    return "Looked in my notes — no matches"
            return f"✓ {tool} done" if tool else "✓ Done"
        err = payload.get("error") or payload.get("output") or ""
        line = f"✗ {tool} failed" if tool else "✗ Tool failed"
        if err:
            line += f": {_short(err, 70)}"
        return line


def pill_state(provider, activity) -> "tuple[str, str, int]":
    """Status pill from (provider, activity): (label, color, pulse_ms).

    Pure — unit-tested. pulse_ms == 0 means steady; smaller = faster pulse
    (Team 4: tempo IS the state signal). Spec mapping: idle steady green,
    thinking amber slow pulse, tool-running blue fast pulse, speaking
    violet, error/stopped red steady. The provider name rides the idle
    label (F-08); "stub" is the honest red state — no real model is up.
    """
    raw = str(provider or "").strip()
    prov = raw.lower()
    act = str(activity or "idle").strip().lower()
    if act == "error":
        return ("error — see the chat", "#d32f2f", 0)
    if act == "stopped":
        return ("turn stopped", "#d32f2f", 0)
    if act == "approval":
        return ("waiting approval", "#d32f2f", 1400)
    if act == "tool":
        return ("working — running a tool…", "#1565c0", 350)
    if act == "thinking":
        return ("thinking…", "#f9a825", 900)
    if act == "speaking":
        return ("speaking…", "#7b1fa2", 650)
    if act == "warming":
        return ("warming up…", "#f9a825", 900)
    # idle (and anything unrecognized)
    if prov == "stub":
        return ("STUB — no models!", "#d32f2f", 0)
    if prov and prov not in ("none", "unknown"):
        return (f"ready — brain: {raw}", "#2e7d32", 0)
    return ("ready", "#2e7d32", 0)


def dim_color(hex_color: str, toward: str = "#f5f5f5",
              fraction: float = 0.55) -> str:
    """Blend a #rrggbb color toward another — the pulse's 'dim' phase."""
    def _rgb(c: str):
        c = c.lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))

    try:
        a, b = _rgb(hex_color), _rgb(toward)
    except Exception:
        return hex_color
    return "#%02x%02x%02x" % tuple(
        round(x + (y - x) * fraction) for x, y in zip(a, b))


class ChatWindow:
    def __init__(self, app) -> None:
        self.app = app
        self.q: queue.Queue = queue.Queue()
        self.root = tk.Tk()
        self.root.title("JARVIS")
        self.root.geometry("720x520")
        self.root.minsize(480, 360)

        # Status pill (brain state) — label/color/pulse from pill_state().
        self.status = tk.Label(self.root, text="● ready", fg="#2e7d32",
                               font=("Segoe UI", 10, "bold"), anchor="w")
        self.status.pack(fill="x", padx=10, pady=(8, 0))

        # HUD live feed (Team 4): typed run events from the session store,
        # rendered as short human lines — watch JARVIS work, not just
        # read his answers. Polled in _drain; painted only on the UI thread.
        self.feed_view = scrolledtext.ScrolledText(
            self.root, wrap="word", state="disabled", height=5,
            font=("Segoe UI", 9), padx=8, pady=4)
        self.feed_view.tag_config("feed", foreground="#616161")
        self.feed_view.pack(fill="x", padx=10, pady=(2, 0))
        self._feed = EventFeed()
        self._activity = "idle"
        self._pill_override: "tuple[str, str] | None" = None
        self._pill_gen = 0
        self._pill_color = "#2e7d32"
        self._pill_pulse_ms = 0
        self._pulse_dim = False

        # Message view
        self.view = scrolledtext.ScrolledText(
            self.root, wrap="word", state="disabled",
            font=("Segoe UI", 11), padx=10, pady=10)
        self.view.tag_config("you", foreground="#1565c0")
        self.view.tag_config("jarvis", foreground="#212121")
        self.view.tag_config("sys", foreground="#757575", font=("Segoe UI", 9, "italic"))

        # Input row — packed FIRST with side="bottom" so it can never be
        # squeezed out by the expanding message view (Windows DPI bug).
        row = tk.Frame(self.root)
        row.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
        self.entry = tk.Entry(row, font=("Segoe UI", 11))
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry.bind("<Return>", lambda _e: self.send())
        # Placeholder so it's obvious where to type.
        self._placeholder = "Type your message here, sir…"
        self.entry.insert(0, self._placeholder)
        self.entry.configure(fg="#9e9e9e")
        self.entry.bind("<FocusIn>", self._clear_placeholder)
        self.entry.bind("<FocusOut>", self._restore_placeholder)
        send = tk.Button(row, text="Send", command=self.send,
                         font=("Segoe UI", 10, "bold"))
        send.pack(side="right")
        # F-09: STOP button. A hung turn (worst case ~90s: 6 providers x 5s
        # x 3 ReAct rounds) used to brick the UI. Stop abandons the turn:
        # the worker is NOT joined (the HTTP call isn't interruptible),
        # its late output is dropped via the turn token, and the daemon
        # thread dies with the process.
        self.stop_btn = tk.Button(row, text="■ Stop", command=self.stop,
                                  font=("Segoe UI", 10, "bold"),
                                  state="disabled")
        self.stop_btn.pack(side="right", padx=(0, 8))
        # Message view fills whatever is left.
        self.view.pack(side="top", fill="both", expand=True, padx=10, pady=8)
        # F-09: turn token — late output from abandoned turns is dropped.
        self._turns = TurnToken()
        # F-08: last announced provider (for switch announcements).
        self._last_via: str | None = None
        # Focus the entry so typing works immediately.
        self.root.after(200, lambda: self.entry.focus_set())

        # Approval answers from a Tk modal (the _gui_input_fn hook).
        if app is not None:
            app._gui_input_fn = self._ask_approval
        self.app = app

        self._worker: threading.Thread | None = None
        self._drain()
        if app is None:
            # F-06: brain still warming up in background — window is already
            # visible, entry disabled until the app attaches.
            self._set_status("warming up…", "#f9a825")
            self._say("sys", "Warming up the brain — one moment, sir.\n")
            self.entry.configure(state="disabled")
        else:
            self._refresh_pill()
            self._say("sys", "JARVIS online — text chat ready, sir.\n")

    # -- UI helpers (UI thread only) ------------------------------------ #
    def _clear_placeholder(self, _event=None) -> None:
        if self.entry.get() == self._placeholder:
            self.entry.delete(0, "end")
            self.entry.configure(fg="#212121")

    def _restore_placeholder(self, _event=None) -> None:
        if not self.entry.get().strip():
            self.entry.insert(0, self._placeholder)
            self.entry.configure(fg="#9e9e9e")

    def _say(self, tag: str, text: str) -> None:
        self.view.configure(state="normal")
        self.view.insert("end", text, tag)
        self.view.see("end")
        self.view.configure(state="disabled")

    def _set_status(self, text: str, color: str) -> None:
        """One-off steady status (warming up, startup failed, turn
        abandoned). An override: it holds until the next activity change
        (see _set_activity) — activity states own the pill otherwise."""
        self._pill_override = (text, color)
        self._apply_pill(text, color, 0)

    # -- status pill: state -> (label, color, pulse) ---------------------- #
    def _provider_name(self) -> "str | None":
        try:
            if self.app is not None:
                return self.app.last_provider
        except Exception:
            pass
        return None

    def _set_activity(self, activity: str) -> None:
        """The single door for activity-driven pill changes."""
        self._activity = activity
        self._pill_override = None
        self._refresh_pill()

    def _refresh_pill(self) -> None:
        if self._pill_override is not None:
            text, color = self._pill_override
            self._apply_pill(text, color, 0)
            return
        label, color, pulse = pill_state(self._provider_name(),
                                         self._activity)
        self._apply_pill(label, color, pulse)

    def _apply_pill(self, text: str, color: str, pulse_ms: int) -> None:
        self._pill_gen += 1  # supersedes any in-flight pulse tick
        self._pill_color = color
        self._pill_pulse_ms = pulse_ms
        self._pulse_dim = False
        self.status.configure(text="● " + text, fg=color)
        if pulse_ms > 0:
            gen = self._pill_gen
            self.root.after(pulse_ms, lambda: self._pulse_tick(gen))

    def _pulse_tick(self, gen: int) -> None:
        if gen != self._pill_gen or self._pill_pulse_ms <= 0:
            return  # a newer pill state owns the label now
        self._pulse_dim = not self._pulse_dim
        fg = (dim_color(self._pill_color) if self._pulse_dim
              else self._pill_color)
        try:
            self.status.configure(fg=fg)
        except Exception:
            return
        self.root.after(self._pill_pulse_ms, lambda: self._pulse_tick(gen))

    def _apply_state(self, text: str, color: str) -> None:
        """Queued ("state", ...) messages from the worker/output router:
        the recurring ones become activities (pill_state owns their look);
        the rest are one-off statuses."""
        low = text.lower()
        if low.startswith("thinking"):
            self._set_activity("thinking")
        elif low.startswith("waiting approval"):
            self._set_activity("approval")
        else:
            self._set_status(text, color)

    # -- HUD live feed ----------------------------------------------------- #
    def _poll_feed(self) -> None:
        """Pull NEW session events past the feed's cursor and render them.

        Runs on the UI thread inside _drain (the GUI's existing cadence);
        the store read is the only I/O and it is read-only. Any failure is
        silent — the feed is a window onto the work, never a dependency.
        """
        app = self.app
        if app is None:
            return
        store = getattr(app, "store", None)
        sid = getattr(app, "session_id", None)
        if store is None or not sid:
            return
        try:
            events = store.get_events(sid, after_seq=self._feed.cursor,
                                      limit=500)
        except Exception:
            return
        if not events:
            return
        for line in self._feed.consume(events):
            self._say_feed(line)
        if self._feed.activity != self._activity:
            self._set_activity(self._feed.activity)

    def _say_feed(self, text: str) -> None:
        self.feed_view.configure(state="normal")
        self.feed_view.insert("end", text + "\n", "feed")
        self.feed_view.see("end")
        self.feed_view.configure(state="disabled")

    def _drain(self) -> None:
        """Pull queued brain output into the view."""
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "out":
                    self._route_output(payload)
                elif kind == "state":
                    self._apply_state(*payload)
                elif kind == "done":
                    self._on_turn_done()
                elif kind == "abandoned":
                    pass  # F-09: orphaned worker's epitaph — ignore it
        except queue.Empty:
            pass
        # Watchdog: the entry must NEVER be stuck disabled while the app
        # is ready and no turn is running. (Stuck-disabled was the
        # "can't click to type" bug.)
        try:
            worker_alive = self._worker is not None and self._worker.is_alive()
            if (self.app is not None and not worker_alive
                    and str(self.entry.cget("state")) == "disabled"):
                self.entry.configure(state="normal")
        except Exception:
            pass
        self._poll_feed()
        self.root.after(80, self._drain)

    def _on_turn_done(self) -> None:
        """F-08: the pill shows WHICH brain answered, not just "ready".

        pill_state(provider, "idle") reproduces the F-08 labels exactly:
        stub -> red "STUB — no models!", a name -> "ready — brain: <name>".
        Provider switches are announced once in the window.
        """
        if self.app is None:
            return  # still warming up — attach_app owns the pill
        try:
            via = self.app.last_provider
        except Exception:
            via = "unknown"
        if via not in ("none", "unknown", "stub"):
            if self._last_via is not None and via != self._last_via:
                self._say("sys", f"[brain] now answering via {via}\n")
            self._last_via = via
        self._set_activity("idle")
        self.entry.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    def _route_output(self, text: str) -> None:
        low = text.strip().lower()
        if low.startswith("[thinking]"):
            self.q.put(("state", ("thinking…", "#f9a825")))
        elif low.startswith("[waiting approval]"):
            self.q.put(("state", ("waiting approval", "#d32f2f")))
        elif low.startswith(("[answered]", "[asked]", "[stopped]")):
            self._say("jarvis", "JARVIS: " + text.split("]", 1)[1].strip() + "\n")
        elif text.strip().startswith("[") and text.strip().endswith("]"):
            self._say("sys", text)
        else:
            self._say("jarvis", text if text.endswith("\n") else text + "\n")

    def _ask_approval(self, prompt: str) -> str:
        """Modal dialog for typed confirmations (called on worker thread —
        marshalled to the UI thread via a future)."""
        answer: queue.Queue[str] = queue.Queue()

        def ask() -> None:
            try:
                r = simpledialog.askstring("JARVIS needs approval", prompt,
                                           parent=self.root)
            except Exception:
                r = None
            answer.put(r or "")

        self.root.after(0, ask)
        return answer.get()

    # -- send path ------------------------------------------------------- #
    def send(self) -> None:
        text = self.entry.get().strip()
        if text == self._placeholder:
            text = ""
        if not text or (self._worker and self._worker.is_alive()):
            return
        self.entry.delete(0, "end")
        self.entry.configure(state="disabled")
        self._say("you", "You: " + text + "\n")
        self._set_activity("thinking")
        token = self._turns.new_turn()  # captured on the UI thread — no race
        self._worker = threading.Thread(target=self._run_turn,
                                        args=(text, token), daemon=True)
        self._worker.start()
        self.stop_btn.configure(state="normal")

    def stop(self) -> None:
        """F-09: abandon the running turn. Never joins the worker — the
        brain call isn't truly interruptible, so we stop WAITING, detach
        the UI, and let the turn token drop the orphan's late output."""
        if not (self._worker and self._worker.is_alive()):
            return
        self._turns.abandon()
        self._worker = None  # orphaned; daemon thread dies with the process
        self.entry.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self._set_status("ready — turn abandoned", "#f9a825")
        self._say("sys", "[sys] Turn abandoned, sir.\n")
        self.entry.focus_set()

    def _run_turn(self, text: str, token: int) -> None:
        """Worker thread: run the brain with stdout captured."""
        my_id = token
        if self.app is None:
            self.q.put(("out", "[sys] Still warming up — one moment, sir.\n"))
            self.q.put(("done", None))
            return
        old = sys.stdout
        writer = _GuiWriter(self.q,
                            is_live=lambda: self._turns.is_live(my_id))
        sys.stdout = writer  # type: ignore[assignment]
        try:
            # Slash commands NEVER reach the brain (F-01: key-leak fix).
            if text.startswith("/") and self.app.handle_command(text):
                return
            self.app.turn(text)
        except Exception as exc:  # never kill the window on a brain error
            print(f"[error] {exc}")
        finally:
            sys.stdout = old
            # F-09: live turn -> done; abandoned turn -> epitaph (ignored).
            self.q.put(("done", None)
                       if self._turns.is_live(my_id) else ("abandoned", None))

    def attach_app(self, app) -> None:
        """Called on the UI thread when the background build finishes."""
        self.app = app
        app._gui_input_fn = self._ask_approval
        self._set_activity("idle")
        self._say("sys", "JARVIS online — text chat ready, sir.\n")
        self.entry.configure(state="normal")
        self.entry.focus_set()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    base_dir = Path(__file__).resolve().parent.parent
    data_dir = base_dir / "data"
    # Reuse the CLI's preflight + ChatApp wiring.
    from jarvis.chat import preflight, ChatApp
    problems = preflight(base_dir, data_dir)
    if problems:
        # No terminal here — show the problems in a dialog and exit.
        root = tk.Tk()
        root.withdraw()
        tk.messagebox.showerror(
            "JARVIS — cannot start",
            "Preflight failed:\n\n" + "\n".join("• " + p for p in problems))
        sys.exit(2)
    # F-06: build the brain OFF the UI thread. The window appears instantly
    # with "warming up…"; the app attaches when its health probes finish.
    window = ChatWindow(None)

    # F-13: OneDrive-synced data dir — warn in a dialog (no terminal here).
    from jarvis.chat import startup_warnings
    for w in startup_warnings(data_dir):
        tk.messagebox.showwarning("JARVIS — storage warning", w)

    def build() -> None:
        try:
            app = ChatApp(base_dir, data_dir)
        except Exception as exc:  # startup failed — say so in the window
            window.q.put(("out", f"[error] Startup failed: {exc}\n"))
            window.q.put(("state", ("startup failed", "#d32f2f")))
            return
        window.root.after(0, lambda: window.attach_app(app))

    threading.Thread(target=build, daemon=True).start()
    window.run()


if __name__ == "__main__":
    import tkinter.messagebox  # noqa: E402  (dialog for preflight failures)
    main()
