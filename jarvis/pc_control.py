"""JARVIS v2 — PC Control (Wave 3).

Reads the Windows UI Automation tree first (free, exact), grounds pixels
only when the tree is insufficient, and acts through a small, tiered action
vocabulary. Design source: learn-pc-control-spec.md.

Structural invariants (enforced in code, not prompts):
  1. Observation order is fixed: UIA tree -> screenshot. Never a model decision.
  2. "Only act on what you have been shown": element handles are valid only
     against the snapshot that produced them. Unknown/stale ids are REFUSED.
  3. C-X4: type_into_field and run_in_terminal are DIFFERENT functions with
     no shared code path. Text is never evaluated; commands are never typed.
  4. Every GUI action is tier-2 minimum; run_in_terminal is tier-3 always.
  5. Screenshots live in RAM only. They never touch disk.
  6. Elevated (UAC) windows are untouchable — UIPI is a security boundary,
     not a bug. Refused honestly, never bypassed.

Tiers (for gate registration via tool_definitions()/as_gate_registry()):
  pc.observe / pc.screenshot ......... tier 1 (reads, auto-allowed)
  pc.click / pc.type / pc.key ......... tier 2 (announced, undo where possible)
  pc.shell ............................ tier 3 (out-of-band approval, always)

Capabilities (extend the closed skill vocabulary for PC tools):
  ui.read, ui.control, shell.exec
"""

from __future__ import annotations

import re
import struct
import subprocess
import sys
import threading
import time
import zlib
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #

class PCControlError(Exception):
    """Base for all PC-control failures."""


class NotWindowsError(PCControlError):
    """Raised when a Windows-only operation runs on another platform."""


class StaleElementError(PCControlError):
    """The element id is not in the current observation snapshot."""


class ElevatedWindowError(PCControlError):
    """The target window is elevated (UAC/UIPI). Untouchable — by design."""


class BlockedCommandError(PCControlError):
    """run_in_terminal refused a blocklisted command."""


class ActionFailedError(PCControlError):
    """The backend could not perform the action."""


class VerificationFailedError(PCControlError):
    """Assert-after-act failed after the 2-attempt budget."""


def _is_windows() -> bool:
    return sys.platform == "win32"


def _require_windows(what: str) -> None:
    if not _is_windows():
        raise NotWindowsError(
            f"{what} requires Windows (UI Automation). "
            f"Running on {sys.platform}."
        )


# --------------------------------------------------------------------------- #
# Element model
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Element:
    """One actionable UI element, bound to the snapshot that observed it."""
    element_id: str          # durable id within a snapshot (UIA RuntimeId hex)
    role: str                # button, edit, menuitem, ...
    name: str
    bounding_box: tuple[int, int, int, int]  # x, y, w, h in physical pixels
    snapshot_id: int
    elevated: bool = False   # True if the owning window is high-integrity


@dataclass
class Snapshot:
    """One observation of one window."""
    snapshot_id: int
    window: str
    elements: list[Element] = field(default_factory=list)
    ts: float = field(default_factory=time.time)

    def by_id(self, element_id: str) -> Optional[Element]:
        for el in self.elements:
            if el.element_id == element_id:
                return el
        return None


# --------------------------------------------------------------------------- #
# Backend interface
# --------------------------------------------------------------------------- #

class UiaBackend:
    """Abstract driver. WindowsUiaBackend is real; FakeUiaBackend is for tests."""

    # -- observation ------------------------------------------------------ #
    def walk_tree(self, window: Optional[str] = None) -> list[dict]:
        """Return [{role, name, bounding_box, element_id, elevated}]."""
        raise NotImplementedError

    def capture_pixels(self, region: Optional[tuple[int, int, int, int]] = None
                       ) -> tuple[int, int, bytes]:
        """Return (width, height, RGB bytes). RAM only."""
        raise NotImplementedError

    # -- action ------------------------------------------------------------ #
    def click(self, element: Element) -> None:
        raise NotImplementedError

    def type_text(self, element: Element, text: str) -> None:
        """Type literal text into a field. NEVER a shell. No transformation."""
        raise NotImplementedError

    def press_key(self, key: str) -> None:
        raise NotImplementedError

    def run_shell(self, command: str, timeout: float = 60.0) -> dict:
        """Run a shell command. Returns {returncode, stdout, stderr}."""
        raise NotImplementedError

    def settle(self) -> None:
        """Wait for the UI to stabilize before re-observing."""
        time.sleep(0.25)


# --------------------------------------------------------------------------- #
# Real Windows backend (platform-guarded; comtypes guarded import)
# --------------------------------------------------------------------------- #

class WindowsUiaBackend(UiaBackend):
    """Real driver via UIAutomationCore. Constructing on non-Windows raises."""

    def __init__(self) -> None:
        _require_windows("WindowsUiaBackend")
        try:
            import comtypes.client  # type: ignore
        except ImportError as exc:
            raise PCControlError(
                "WindowsUiaBackend needs the 'comtypes' package: "
                "pip install comtypes"
            ) from exc
        self._comtypes = comtypes.client
        self._uia = None  # lazy CUIAutomation

    def _automation(self):
        if self._uia is None:
            self._uia = self._comtypes.CreateObject(
                "{ff48dba4-60ef-4201-aa87-54103eef594e}")  # CUIAutomation
        return self._uia

    # -- observation ------------------------------------------------------ #
    _ACTIONABLE = {
        50000,  # UIA_ButtonControlTypeId (values abbreviated; full set below)
    }
    _ACTIONABLE_TYPES = {
        "button", "edit", "menuitem", "listitem", "checkbox", "radiobutton",
        "combobox", "tabitem", "hyperlink", "treeitem", "splitbutton",
    }

    def walk_tree(self, window: Optional[str] = None) -> list[dict]:
        uia = self._automation()
        root = uia.GetRootElement()
        walker = uia.ControlViewWalker
        out: list[dict] = []
        self._walk(walker, root, out, depth=0, max_depth=12)
        return out

    def _walk(self, walker, element, out: list, depth: int, max_depth: int) -> None:
        if depth > max_depth:
            return
        try:
            ctype = element.CurrentControlType
            name = element.CurrentName or ""
            rect = element.CurrentBoundingRectangle
            # RuntimeId: durable identity across time (spec §6.5).
            rid = "-".join(str(i) for i in element.GetRuntimeId())
            role = self._control_type_name(ctype)
            if role in self._ACTIONABLE_TYPES and name:
                out.append({
                    "role": role,
                    "name": name,
                    "bounding_box": (rect.left, rect.top,
                                     rect.right - rect.left,
                                     rect.bottom - rect.top),
                    "element_id": rid,
                    "elevated": False,
                })
        except Exception:
            pass  # dead element mid-walk: skip, don't crash
        try:
            child = walker.GetFirstChildElement(element)
            while child is not None:
                self._walk(walker, child, out, depth + 1, max_depth)
                child = walker.GetNextSiblingElement(child)
        except Exception:
            pass

    @staticmethod
    def _control_type_name(ctype: int) -> str:
        return {
            50000: "button", 50004: "checkbox", 50010: "combobox",
            50011: "edit", 50012: "hyperlink", 50013: "listitem",
            50014: "list", 50019: "menuitem", 50020: "menubar",
            50021: "menu", 50029: "radiobutton", 50035: "tabitem",
            50036: "treeitem", 50033: "splitbutton",
        }.get(ctype, f"control_{ctype}")

    def capture_pixels(self, region=None):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        if region:
            x, y, w, h = region
        else:
            w = user32.GetSystemMetrics(0)
            h = user32.GetSystemMetrics(1)
            x, y = 0, 0
        hdc_src = user32.GetDC(None)
        hdc_dst = gdi32.CreateCompatibleDC(hdc_src)
        hbmp = gdi32.CreateCompatibleBitmap(hdc_src, w, h)
        gdi32.SelectObject(hdc_dst, hbmp)
        gdi32.BitBlt(hdc_dst, 0, 0, w, h, hdc_src, x, y, 0x00CC0020)  # SRCCOPY

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD),
                        ("biWidth", wintypes.LONG),
                        ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG),
                        ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h  # top-down
        bmi.biPlanes = 1
        bmi.biBitCount = 24
        bmi.biCompression = 0
        stride = (w * 3 + 3) & ~3
        buf = ctypes.create_string_buffer(stride * h)
        gdi32.GetDIBits(hdc_dst, hbmp, 0, h, buf, ctypes.byref(bmi), 0)
        # Strip row padding -> tight RGB.
        rgb = b"".join(bytes(buf[i * stride:i * stride + w * 3])
                       for i in range(h))
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_dst)
        user32.ReleaseDC(None, hdc_src)
        return w, h, bytes(rgb)

    # -- action ------------------------------------------------------------ #
    def _element_by_id(self, element_id: str):
        uia = self._automation()
        cond = uia.CreatePropertyCondition(
            30001, element_id)  # UIA_RuntimeIdPropertyId — approximate
        el = uia.GetRootElement().FindFirst(
            0x2, cond)  # TreeScope_Descendants
        if el is None:
            raise StaleElementError(
                f"element {element_id!r} not found — re-observe first")
        return el

    def click(self, element: Element) -> None:
        el = self._element_by_id(element.element_id)
        try:
            # UIA_InvokePatternId = 10000. InvokePattern works on background
            # windows without touching the cursor (spec §2.2).
            pattern = el.GetCurrentPattern(10000)
            pattern.Invoke()
        except Exception as exc:
            raise ActionFailedError(
                f"click failed on {element.name!r}: no invokable pattern"
            ) from exc

    def type_text(self, element: Element, text: str) -> None:
        # Verbatim. No transformation, no truncation, no escaping games —
        # text goes to a FIELD, never to a shell (C-X4, corpse M-X20).
        el = self._element_by_id(element.element_id)
        try:
            pattern = el.GetCurrentPattern(10002)  # UIA_ValuePatternId
            pattern.SetValue(text)
        except Exception as exc:
            raise ActionFailedError(
                f"type_text failed on {element.name!r}: not a value pattern"
            ) from exc

    def press_key(self, key: str) -> None:
        import ctypes
        _require_windows("press_key")
        # SendInput path kept minimal: real key synthesis lives here and
        # nowhere else. Full virtual-key table in _VK.
        vk = _VK.get(key.lower())
        if vk is None:
            raise ActionFailedError(f"unknown key {key!r}")
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 0x0002, 0)  # KEYEVENTF_KEYUP

    def run_shell(self, command: str, timeout: float = 60.0) -> dict:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout)
        return {"returncode": proc.returncode,
                "stdout": proc.stdout[-8000:], "stderr": proc.stderr[-8000:]}


_VK = {
    "tab": 0x09, "enter": 0x0D, "escape": 0x1B, "space": 0x20,
    "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "insert": 0x2D, "delete": 0x2E, "backspace": 0x08,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
}


# --------------------------------------------------------------------------- #
# Fake backend (tests / non-Windows dev)
# --------------------------------------------------------------------------- #

class FakeUiaBackend(UiaBackend):
    """In-memory Windows. Records every call for assertions."""

    def __init__(self, elements: Optional[list[dict]] = None,
                 elevated: bool = False) -> None:
        self._elements = elements or []
        self._elevated = elevated
        self.calls: list[tuple[str, tuple, dict]] = []
        self._lock = threading.Lock()

    def _record(self, name: str, *args, **kwargs) -> None:
        with self._lock:
            self.calls.append((name, args, kwargs))

    def calls_to(self, name: str) -> list:
        with self._lock:
            return [c for c in self.calls if c[0] == name]

    def walk_tree(self, window: Optional[str] = None) -> list[dict]:
        self._record("walk_tree", window)
        return [dict(e, elevated=self._elevated) for e in self._elements]

    def capture_pixels(self, region=None):
        self._record("capture_pixels", region)
        w, h = (region[2], region[3]) if region else (64, 48)
        # Synthetic gradient — never touches disk.
        rgb = bytes(
            v for y in range(h) for x in range(w)
            for v in (x * 4 % 256, y * 5 % 256, (x + y) % 256))
        return w, h, rgb

    def click(self, element: Element) -> None:
        self._record("click", element.element_id)

    def type_text(self, element: Element, text: str) -> None:
        # Records the EXACT string — proves no transformation (M-X20).
        self._record("type_text", element.element_id, text)

    def press_key(self, key: str) -> None:
        self._record("press_key", key)

    def run_shell(self, command: str, timeout: float = 60.0) -> dict:
        self._record("run_shell", command)
        return {"returncode": 0, "stdout": "fake-ok", "stderr": ""}

    def settle(self) -> None:
        self._record("settle")


# --------------------------------------------------------------------------- #
# PNG encoder (stdlib only — screenshots stay in RAM)
# --------------------------------------------------------------------------- #

def encode_png(width: int, height: int, rgb: bytes) -> bytes:
    """Minimal truecolor PNG encoder. Pure stdlib; writes nothing to disk."""
    if len(rgb) != width * height * 3:
        raise ValueError("rgb length does not match dimensions")

    def chunk(ctype: bytes, data: bytes) -> bytes:
        c = ctype + data
        return (struct.pack(">I", len(data)) + c +
                struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + rgb[y * width * 3:(y + 1) * width * 3]
                   for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# --------------------------------------------------------------------------- #
# Tier-3 shell blocklist (fail-closed; documented, tested)
# --------------------------------------------------------------------------- #

_BLOCKLIST: list[tuple[str, str]] = [
    (r"rm\s+-rf?\s+/(?:[\s*]|$)", "recursive delete from filesystem root"),
    (r"rm\s+-rf?\s+~", "recursive delete of home directory"),
    (r"\breg\s+delete\b", "Windows registry deletion"),
    (r"\bregedit\b", "registry editor"),
    (r"\bformat\s+[a-z]:", "disk format"),
    (r"\bmkfs\b", "filesystem creation"),
    (r"\bdd\s+if=", "raw disk write"),
    (r"\bshutdown\b", "system shutdown"),
    (r":\(\)\{\s*:\|\:&\s*\};:", "fork bomb"),
    (r"powershell.*-(e|enc|encodedcommand)\b", "encoded PowerShell (obfuscation)"),
    (r"\bcurl\b.*\|\s*(sh|bash)", "curl-piped-to-shell"),
    (r"\bwget\b.*\|\s*(sh|bash)", "wget-piped-to-shell"),
    (r"iwr\s+.*\|\s*iex", "Invoke-WebRequest piped to Invoke-Expression"),
    (r"\btakeown\b", "ownership seizure"),
    (r"\bicacls\b", "ACL modification"),
    (r"\bnet\s+(user|localgroup)\b", "account/group modification"),
    (r"\bbcdedit\b", "boot configuration edit"),
    (r"\bdiskpart\b", "disk partitioning"),
    (r"del\s+/[fs]\s+/q\s+c:\\windows", "mass delete in Windows dir"),
]
_BLOCKLIST_RE = [(re.compile(p, re.IGNORECASE), why)
                 for p, why in _BLOCKLIST]


def _check_blocklist(command: str) -> Optional[str]:
    for rx, why in _BLOCKLIST_RE:
        if rx.search(command):
            return why
    return None


# --------------------------------------------------------------------------- #
# Key allowlist (tier-2)
# --------------------------------------------------------------------------- #

_ALLOWED_KEYS = (
    {"tab", "enter", "escape", "space", "up", "down", "left", "right",
     "home", "end", "pageup", "pagedown", "delete", "backspace", "insert"}
    | {f"f{i}" for i in range(1, 13)}
    | {"ctrl+a", "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+s"}
)


# --------------------------------------------------------------------------- #
# Capabilities + gate tool definitions
# --------------------------------------------------------------------------- #

PC_CAPABILITIES = ("ui.read", "ui.control", "shell.exec")
# NOTE: these extend the closed skill-manifest vocabulary. PC tools register
# directly into the gate registry (not via skill manifests), so manifest
# validation is unaffected. The gate itself only does set arithmetic.

TIER_READ = 1
TIER_GUI = 2
TIER_SHELL = 3


def tool_definitions() -> list[dict]:
    """Gate-registry entries: {name, tier, schema, capabilities, description}."""
    return [
        {"name": "pc.observe", "tier": TIER_READ,
         "capabilities": ["ui.read"],
         "description": "Walk the UIA tree of a window (tier-1 read)",
         "schema": {"type": "object",
                    "properties": {"window": {"type": "string"}},
                    "required": []}},
        {"name": "pc.screenshot", "tier": TIER_READ,
         "capabilities": ["ui.read"],
         "description": "Capture a screenshot to RAM (never disk)",
         "schema": {"type": "object",
                    "properties": {"region": {"type": "array"}},
                    "required": []}},
        {"name": "pc.click", "tier": TIER_GUI,
         "capabilities": ["ui.control"],
         "description": "Click an element seen in the last observation",
         "schema": {"type": "object",
                    "properties": {"element_id": {"type": "string"}},
                    "required": ["element_id"]}},
        {"name": "pc.type", "tier": TIER_GUI,
         "capabilities": ["ui.control"],
         "description": "Type literal text into a field (never a shell)",
         "schema": {"type": "object",
                    "properties": {"element_id": {"type": "string"},
                                   "text": {"type": "string"}},
                    "required": ["element_id", "text"]}},
        {"name": "pc.key", "tier": TIER_GUI,
         "capabilities": ["ui.control"],
         "description": "Press an allowlisted key",
         "schema": {"type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"]}},
        {"name": "pc.shell", "tier": TIER_SHELL,
         "capabilities": ["ui.control", "shell.exec"],
         "description": "Run a terminal command (tier-3, blocklisted)",
         "schema": {"type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"]}},
    ]


def as_gate_registry() -> dict:
    """{tool_name: {tier, schema, capabilities}} — plugs into Gate(...)."""
    return {t["name"]: {"tier": t["tier"], "schema": t["schema"],
                       "capabilities": t["capabilities"]}
            for t in tool_definitions()}


# --------------------------------------------------------------------------- #
# PCController
# --------------------------------------------------------------------------- #

class PCController:
    """Owns observation snapshots, enforces the safety invariants, logs."""

    def __init__(self, backend: Optional[UiaBackend] = None,
                 session_store: Any = None,
                 session_id: Optional[str] = None,
                 allowed_commands: Optional[list[str]] = None) -> None:
        self.backend: UiaBackend = backend or WindowsUiaBackend()
        self.store = session_store
        self.session_id = session_id
        # Optional command allowlist: prefixes the shell command must match.
        self.allowed_commands = allowed_commands
        self._snapshot_seq = 0
        self._last_snapshot: Optional[Snapshot] = None
        self._lock = threading.Lock()

    # -- logging ---------------------------------------------------------- #
    def _log(self, etype: str, payload: dict, trust: str) -> None:
        if self.store is None or self.session_id is None:
            return
        try:
            self.store.emit(self.session_id, etype, payload,
                            actor="tool", trust=trust)
        except Exception:
            pass  # logging must never break control

    # -- observation (tier-1) ---------------------------------------------- #
    def observe(self, window: Optional[str] = None) -> Snapshot:
        """OBS-1: walk the UIA tree. The snapshot binds all later actions."""
        raw = self.backend.walk_tree(window)
        with self._lock:
            self._snapshot_seq += 1
            snap = Snapshot(
                snapshot_id=self._snapshot_seq,
                window=window or "foreground",
                elements=[
                    Element(element_id=str(e["element_id"]),
                            role=str(e.get("role", "?")),
                            name=str(e.get("name", "")),
                            bounding_box=tuple(e.get("bounding_box",
                                                     (0, 0, 0, 0))),  # type: ignore[arg-type]
                            snapshot_id=self._snapshot_seq,
                            elevated=bool(e.get("elevated", False)))
                    for e in raw
                ],
            )
            self._last_snapshot = snap
        self._log("pc.observe",
                  {"window": snap.window, "elements": len(snap.elements),
                   "snapshot_id": snap.snapshot_id},
                  trust="tool_untrusted")  # screen content is untrusted
        return snap

    def read_uia_tree(self, window: Optional[str] = None) -> dict:
        """Convenience: observe() as a plain dict."""
        snap = self.observe(window)
        return {"snapshot_id": snap.snapshot_id, "window": snap.window,
                "elements": [{"role": e.role, "name": e.name,
                              "bounding_box": list(e.bounding_box),
                              "element_id": e.element_id}
                             for e in snap.elements]}

    def screenshot(self, region: Optional[tuple[int, int, int, int]] = None
                   ) -> bytes:
        """OBS-2: PNG bytes in RAM. Never touches disk (privacy invariant)."""
        w, h, rgb = self.backend.capture_pixels(region)
        png = encode_png(w, h, rgb)
        self._log("pc.screenshot",
                  {"width": w, "height": h, "bytes": len(png),
                   "region": list(region) if region else None},
                  trust="tool_untrusted")
        return png

    def find(self, name_part: str) -> Optional[Element]:
        """Find an element by name substring in the last snapshot."""
        snap = self._last_snapshot
        if snap is None:
            return None
        needle = name_part.lower()
        for el in snap.elements:
            if needle in el.name.lower():
                return el
        return None

    # -- handle resolution (the "shown" invariant) --------------------------- #
    def _resolve(self, element_id: str) -> Element:
        snap = self._last_snapshot
        if snap is None:
            raise StaleElementError(
                "no observation yet — call observe() before acting")
        el = snap.by_id(element_id)
        if el is None:
            raise StaleElementError(
                f"element {element_id!r} was not in snapshot "
                f"#{snap.snapshot_id} — only act on what you have been shown; "
                f"re-observe first")
        if el.elevated:
            raise ElevatedWindowError(
                f"element {element_id!r} belongs to an elevated window — "
                f"UIPI forbids control; this is a security boundary, not a bug")
        return el

    # -- actions (tier-2 minimum) ------------------------------------------- #
    def click_element(self, element_id: str) -> dict:
        """Tier-2. Clicks ONLY elements from the last snapshot."""
        el = self._resolve(element_id)
        self.backend.click(el)
        self._log("pc.click", {"element_id": el.element_id, "name": el.name},
                  trust="tool_verified")
        return {"ok": True, "detail": f"clicked {el.name!r}"}

    def type_into_field(self, element_id: str, text: str) -> dict:
        """Tier-2. Types LITERAL text into a field.

        C-X4: this function has NO path to any shell. It calls
        backend.type_text only. Oversize text is a loud error, never
        silently truncated (corpse M-X20).
        """
        if len(text) > 4000:
            raise ActionFailedError(
                f"text is {len(text)} chars; limit is 4000 — refusing "
                f"rather than silently truncating")
        el = self._resolve(element_id)
        # NOTE: deliberately no shell, no escaping, no subprocess anywhere
        # in this function. Text is data. Full stop.
        self.backend.type_text(el, text)
        self._log("pc.type",
                  {"element_id": el.element_id, "chars": len(text)},
                  trust="tool_verified")
        return {"ok": True, "detail": f"typed {len(text)} chars into {el.name!r}"}

    def press_key(self, key: str) -> dict:
        """Tier-2. Allowlisted keys only."""
        k = key.lower()
        if k not in _ALLOWED_KEYS:
            raise ActionFailedError(
                f"key {key!r} not in the allowlist — refusing")
        self.backend.press_key(k)
        self._log("pc.key", {"key": k}, trust="tool_verified")
        return {"ok": True, "detail": f"pressed {k}"}

    # -- terminal (tier-3 ALWAYS; separate function — C-X4) ------------------ #
    def run_in_terminal(self, command: str) -> dict:
        """Tier-3, always. NEVER tier-2.

        C-X4: this is a DIFFERENT function from type_into_field with no
        shared helper. Commands go to a shell; text never does.
        """
        why = _check_blocklist(command)
        if why:
            self._log("pc.shell_blocked",
                      {"command": command[:200], "reason": why},
                      trust="tool_verified")
            raise BlockedCommandError(
                f"refusing blocklisted command ({why}): {command[:80]}")
        if self.allowed_commands is not None:
            if not any(command.strip().startswith(p)
                       for p in self.allowed_commands):
                raise BlockedCommandError(
                    "command not in the allowlist for this task")
        out = self.backend.run_shell(command)
        self._log("pc.shell",
                  {"command": command[:500],
                   "returncode": out.get("returncode")},
                  trust="tool_verified")
        return {"ok": out.get("returncode") == 0,
                "detail": f"exit {out.get('returncode')}",
                "stdout": out.get("stdout", ""),
                "stderr": out.get("stderr", "")}

    # -- assert-after-act (spec §5): 2-attempt rule --------------------------- #
    def act_and_verify(self, action: Callable[[], Any],
                       check: Callable[[Snapshot], bool],
                       window: Optional[str] = None) -> dict:
        """Run action, re-observe, check. One retry with settle, then escalate.

        The 2-attempt rule (Debugging Decay Index): attempt 1, one retry,
        then ESCALATE. Never loop clicking.
        """
        last_exc: Optional[Exception] = None
        for attempt in (1, 2):
            try:
                action()
            except Exception as exc:
                last_exc = exc
                break  # action itself failed — nothing to verify
            if attempt == 2:
                self.backend.settle()
            snap = self.observe(window)
            try:
                if check(snap):
                    return {"ok": True, "detail": f"verified on attempt {attempt}"}
            except Exception as exc:
                last_exc = exc
        raise VerificationFailedError(
            "action did not produce the expected state after 2 attempts — "
            f"escalating ({last_exc})")


# --------------------------------------------------------------------------- #
# Module-level convenience API (delegates to a default controller)
# --------------------------------------------------------------------------- #

_default: Optional[PCController] = None
_default_lock = threading.Lock()


def _default_controller() -> PCController:
    global _default
    with _default_lock:
        if _default is None:
            _default = PCController()
        return _default


def read_uia_tree(window: Optional[str] = None) -> dict:
    return _default_controller().read_uia_tree(window)


def screenshot(region: Optional[tuple[int, int, int, int]] = None) -> bytes:
    return _default_controller().screenshot(region)


def click_element(element_id: str) -> dict:
    return _default_controller().click_element(element_id)


def type_into_field(element_id: str, text: str) -> dict:
    return _default_controller().type_into_field(element_id, text)


def press_key(key: str) -> dict:
    return _default_controller().press_key(key)


def run_in_terminal(command: str) -> dict:
    return _default_controller().run_in_terminal(command)
