"""System skill — small OS tools (status, volume, clipboard, brightness,
window list). Pure stdlib; Windows APIs via ctypes only.

Honesty contract (see SKILL.md): anything this platform/stdlib combination
cannot really do returns {"ok": False, "reason": ...} — never a fake value.

Platform hooks (_run, _win_key, _clipboard_read/write, ...) are module-level
functions so tests can substitute fakes without touching real OS state.
"""

import os
import shutil
import subprocess
import sys

try:
    from jarvis.dcl import DCL, DataClass
    _DCL = DCL()
except Exception:  # pragma: no cover — jarvis package not importable
    _DCL = None
    DataClass = None  # type: ignore[assignment]

# Virtual-key codes for media volume (Windows).
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF

BRIGHTNESS_REASON = (
    "brightness is not implemented: Windows brightness is WMI "
    "(WmiMonitorBrightness), which is not stdlib; the only stdlib route "
    "(PowerShell -EncodedCommand) is blocklisted by v2's own shell policy. "
    "Refusing to fake a value."
)


# --------------------------------------------------------------------------- #
# Platform hooks (monkeypatchable in tests)
# --------------------------------------------------------------------------- #

def _is_windows() -> bool:
    return sys.platform == "win32"


def _run(argv: list[str], timeout: float = 4.0) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def _win_key(vk: int) -> None:
    import ctypes
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 0x0002, 0)  # KEYEVENTF_KEYUP


def _clipboard_read_windows() -> str | None:
    import ctypes
    from ctypes import wintypes
    CF_UNICODETEXT = 13
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    if not user32.OpenClipboard(None):
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _clipboard_write_windows(text: str) -> bool:
    import ctypes
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        data = text.encode("utf-16-le") + b"\x00\x00"
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            return False
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return False
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)
        return bool(user32.SetClipboardData(CF_UNICODETEXT, handle))
    finally:
        user32.CloseClipboard()


def _clipboard_read() -> str | None:
    """Clipboard text, or None when no backend exists on this platform."""
    if _is_windows():
        try:
            return _clipboard_read_windows()
        except Exception:
            return None
    for tool, argv in (("xclip", ["xclip", "-selection", "clipboard", "-o"]),
                       ("xsel", ["xsel", "--clipboard", "--output"])):
        if shutil.which(tool):
            try:
                proc = _run(argv)
                return proc.stdout if proc.returncode == 0 else None
            except Exception:
                return None
    return None


def _clipboard_write(text: str) -> bool:
    if _is_windows():
        try:
            return _clipboard_write_windows(text)
        except Exception:
            return False
    for tool, argv in (("xclip", ["xclip", "-selection", "clipboard"]),
                       ("xsel", ["xsel", "--clipboard", "--input"])):
        if shutil.which(tool):
            try:
                proc = subprocess.run(argv, input=text, capture_output=True,
                                      text=True, timeout=4.0)
                return proc.returncode == 0
            except Exception:
                return False
    return False


def _ram_mb() -> tuple[int | None, int | None]:
    """(total, free) in MB. None when the platform exposes neither."""
    if _is_windows():
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            mb = 1024 * 1024
            return (int(stat.ullTotalPhys // mb), int(stat.ullAvailPhys // mb))
        return None, None
    try:  # Linux /proc/meminfo
        info: dict[str, int] = {}
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(":")] = int(parts[1])
        total = info.get("MemTotal")
        free = info.get("MemAvailable", info.get("MemFree"))
        return (total // 1024 if total else None,
                free // 1024 if free else None)
    except Exception:
        return None, None


def _battery() -> tuple[int | None, bool | None]:
    """(percent, charging). (None, None) when no battery / not exposed."""
    if _is_windows():
        import ctypes

        class SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_byte),
                        ("BatteryFlag", ctypes.c_byte),
                        ("BatteryLifePercent", ctypes.c_byte),
                        ("SystemStatusFlag", ctypes.c_byte),
                        ("BatteryLifeTime", ctypes.c_ulong),
                        ("BatteryFullLifeTime", ctypes.c_ulong)]

        status = SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(
                ctypes.byref(status)):
            return None, None
        pct = int(status.BatteryLifePercent)
        if pct == 255:  # unknown / no battery
            return None, None
        charging = bool(status.ACLineStatus == 1)
        return pct, charging
    base = "/sys/class/power_supply"
    try:
        for entry in sorted(os.listdir(base)):
            if not entry.startswith("BAT"):
                continue
            cap_path = os.path.join(base, entry, "capacity")
            status_path = os.path.join(base, entry, "status")
            with open(cap_path, encoding="utf-8") as fh:
                pct = int(fh.read().strip())
            charging = None
            if os.path.exists(status_path):
                with open(status_path, encoding="utf-8") as fh:
                    charging = fh.read().strip() in ("Charging", "Full")
            return pct, charging
    except Exception:
        pass
    return None, None


def _window_titles_windows() -> list[str]:
    """Top-level visible window titles via EnumWindows (ctypes)."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    titles: list[str] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if buf.value:
                    titles.append(buf.value)
        return True

    user32.EnumWindows(_cb, 0)
    return titles


def _amixer_level() -> tuple[int | None, bool | None]:
    """(percent, muted) parsed from `amixer get Master`, else (None, None)."""
    if not shutil.which("amixer"):
        return None, None
    try:
        proc = _run(["amixer", "get", "Master"])
    except Exception:
        return None, None
    pct = muted = None
    for line in proc.stdout.splitlines():
        if "%" in line and "[" in line:
            try:
                pct = int(line.split("[")[1].split("%")[0])
            except (IndexError, ValueError):
                continue
            muted = "[off]" in line
            break
    return pct, muted


# --------------------------------------------------------------------------- #
# DCL scanning
# --------------------------------------------------------------------------- #

def _dcl_scan(text: str) -> tuple[str, str, bool]:
    """Returns (text_to_return, data_class_name, was_redacted).

    SECRET/SENSITIVE spans are replaced via DCL.redact — clipboard content
    must never carry a raw credential into the brain's context.
    """
    if _DCL is None:
        return text, "unscanned", False
    cls, findings = _DCL.classify(text)
    hits = [f for f in findings
            if f.data_class in (DataClass.SECRET, DataClass.SENSITIVE)]
    if not hits:
        return text, cls.name, False
    redacted, _ = _DCL.redact(text, findings)
    return redacted, cls.name, True


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #

def _system_status(ctx):
    total, free = _ram_mb()
    pct, charging = _battery()
    load_fn = getattr(os, "getloadavg", None)
    load = round(load_fn()[0], 2) if load_fn else None
    note_bits = []
    if pct is None:
        note_bits.append("battery not exposed (desktop / no battery API result)")
    if load is None:
        note_bits.append("load average not exposed by this OS")
    return {
        "platform": sys.platform,
        "battery_percent": pct,
        "battery_charging": charging,
        "cpu_count": os.cpu_count(),
        "cpu_load_1m": load,
        "ram_total_mb": total,
        "ram_free_mb": free,
        "note": "; ".join(note_bits) or "ok",
    }


def _volume_get(ctx):
    if _is_windows():
        return {
            "ok": False,
            "level_percent": None,
            "muted": None,
            "reason": ("Windows master volume level needs the CoreAudio COM "
                       "API (IAudioEndpointVolume), which is not practical "
                       "in pure stdlib ctypes; the media keys used by "
                       "volume_set cannot read a level."),
        }
    pct, muted = _amixer_level()
    if pct is None:
        return {"ok": False, "level_percent": None, "muted": None,
                "reason": "amixer not available on this machine"}
    return {"ok": True, "level_percent": pct, "muted": muted, "reason": ""}


def _volume_set(args, ctx):
    direction = args["direction"]
    steps = max(1, min(10, int(args.get("steps", 2))))
    if _is_windows():
        vk = {"up": VK_VOLUME_UP, "down": VK_VOLUME_DOWN,
              "mute": VK_VOLUME_MUTE}[direction]
        presses = 1 if direction == "mute" else steps
        for _ in range(presses):
            _win_key(vk)
        ctx.log(f"volume_set {direction} x{presses} via VK keys")
        return {"ok": True,
                "detail": (f"sent {presses} VK_VOLUME key press(es); no level "
                           "readback exists for the key path (see SKILL.md)"),
                "reason": ""}
    if shutil.which("amixer"):
        delta = f"{steps * 5}%+" if direction == "up" else \
            f"{steps * 5}%-" if direction == "down" else "toggle"
        proc = _run(["amixer", "set", "Master", delta])
        if proc.returncode == 0:
            return {"ok": True,
                    "detail": f"amixer set Master {delta}", "reason": ""}
        return {"ok": False, "detail": "",
                "reason": f"amixer failed: {proc.stderr.strip()[:200]}"}
    return {"ok": False, "detail": "",
            "reason": "no volume backend (Windows keys / amixer) available"}


def _clipboard_get(ctx):
    raw = _clipboard_read()
    if raw is None:
        return {"ok": False, "text": "", "data_class": "unknown",
                "redacted": False,
                "reason": ("no clipboard backend (Windows user32 / xclip / "
                           "xsel) available, or clipboard held no text")}
    text, cls_name, was_redacted = _dcl_scan(raw)
    ctx.log(f"clipboard_get: {len(raw)} chars, class={cls_name}, "
            f"redacted={was_redacted}")
    return {"ok": True, "text": text, "data_class": cls_name,
            "redacted": was_redacted, "reason": ""}


def _clipboard_set(args, ctx):
    text = args["text"]
    if _DCL is not None:
        cls, _ = _DCL.classify(text)
        if cls == DataClass.SECRET:
            return {"ok": False, "detail": "",
                    "reason": ("refusing to put SECRET-class text on the "
                               "clipboard (credential exposure)")}
    if not _clipboard_write(text):
        return {"ok": False, "detail": "",
                "reason": "no clipboard backend available"}
    ctx.log(f"clipboard_set: {len(text)} chars")
    return {"ok": True, "detail": f"clipboard set ({len(text)} chars)",
            "reason": ""}


def _brightness(reason: str):
    return {"ok": False, "level_percent": None, "reason": reason}


def _window_list(ctx):
    if not _is_windows():
        return {"ok": False, "windows": [],
                "reason": "window enumeration is Windows-only in this skill"}
    try:
        titles = _window_titles_windows()
    except Exception as exc:
        return {"ok": False, "windows": [],
                "reason": f"EnumWindows failed: {exc}"}
    return {"ok": True, "windows": titles, "reason": ""}


def handle(tool_name, args, ctx):
    if tool_name == "system_status":
        return _system_status(ctx)
    if tool_name == "volume_get":
        return _volume_get(ctx)
    if tool_name == "volume_set":
        return _volume_set(args, ctx)
    if tool_name == "clipboard_get":
        return _clipboard_get(ctx)
    if tool_name == "clipboard_set":
        return _clipboard_set(args, ctx)
    if tool_name == "brightness_get":
        return _brightness(BRIGHTNESS_REASON)
    if tool_name == "brightness_set":
        return {"ok": False, "detail": "", "reason": BRIGHTNESS_REASON}
    if tool_name == "window_list":
        return _window_list(ctx)
    raise ValueError(f"unknown tool {tool_name!r}")
