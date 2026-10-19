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
import queue
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext, simpledialog
from pathlib import Path


class _GuiWriter(io.TextIOBase):
    """stdout replacement: lines go to a queue for the UI thread."""

    def __init__(self, q: queue.Queue[str]) -> None:
        self._q = q

    def write(self, s: str) -> int:  # type: ignore[override]
        if s:
            self._q.put(("out", s))
        return len(s)

    def flush(self) -> None:  # type: ignore[override]
        pass


class ChatWindow:
    def __init__(self, app) -> None:
        self.app = app
        self.q: queue.Queue = queue.Queue()
        self.root = tk.Tk()
        self.root.title("JARVIS")
        self.root.geometry("720x520")
        self.root.minsize(480, 360)

        # Status pill (brain state)
        self.status = tk.Label(self.root, text="● ready", fg="#2e7d32",
                               font=("Segoe UI", 10, "bold"), anchor="w")
        self.status.pack(fill="x", padx=10, pady=(8, 0))

        # Message view
        self.view = scrolledtext.ScrolledText(
            self.root, wrap="word", state="disabled",
            font=("Segoe UI", 11), padx=10, pady=10)
        self.view.pack(fill="both", expand=True, padx=10, pady=8)
        self.view.tag_config("you", foreground="#1565c0")
        self.view.tag_config("jarvis", foreground="#212121")
        self.view.tag_config("sys", foreground="#757575", font=("Segoe UI", 9, "italic"))

        # Input row
        row = tk.Frame(self.root)
        row.pack(fill="x", padx=10, pady=(0, 10))
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
        # Focus the entry so typing works immediately.
        self.root.after(200, lambda: self.entry.focus_set())

        # Approval answers from a Tk modal (the _gui_input_fn hook).
        app._gui_input_fn = self._ask_approval

        self._worker: threading.Thread | None = None
        self._drain()
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
        self.status.configure(text="● " + text, fg=color)

    def _drain(self) -> None:
        """Pull queued brain output into the view."""
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "out":
                    self._route_output(payload)
                elif kind == "state":
                    self._set_status(*payload)
                elif kind == "done":
                    self._set_status("ready", "#2e7d32")
                    self.entry.configure(state="normal")
        except queue.Empty:
            pass
        self.root.after(80, self._drain)

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
        self.q.put(("state", ("thinking…", "#f9a825")))
        self._worker = threading.Thread(target=self._run_turn, args=(text,),
                                        daemon=True)
        self._worker.start()

    def _run_turn(self, text: str) -> None:
        """Worker thread: run the brain with stdout captured."""
        old = sys.stdout
        sys.stdout = _GuiWriter(self.q)  # type: ignore[assignment]
        try:
            self.app.turn(text)
        except Exception as exc:  # never kill the window on a brain error
            print(f"[error] {exc}")
        finally:
            sys.stdout = old
            self.q.put(("done", None))

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
    app = ChatApp(base_dir, data_dir)
    ChatWindow(app).run()


if __name__ == "__main__":
    import tkinter.messagebox  # noqa: E402  (dialog for preflight failures)
    main()
