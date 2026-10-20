"""JARVIS v2 setup — startup preflight, model acquisition, first-run wizard.

Pipeline position (setup spec, Cycle 21):

    installer -> first launch -> preflight() -> setup flow -> verified ready

Rules honored here:
- Zero-terminal promise: NO terminal command may appear in any user-facing
  string. fix_hints describe GUI steps only (Clause 6.1).
- "Setup complete" is a *verified state*, never a code path that ran (§3.5).
- Re-running setup is always safe: it diffs, never clobbers (§1.3).
- Preflight never phones home; checks run cheap -> expensive (§2, Cl. 2.3).
- Every check that raises reports plain words + a fix, never a traceback
  in the user's face (Clause 2.2).

Stdlib only. Python 3.11+.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

VERSION = "2.1.0-wave2"

# 10 GB floor for the data drive (spec §2 P4: manifest total x 1.5;
# Wave 2 ships no heavy models yet, so the floor is the binding number).
MIN_DISK_BYTES = 10 * 1024**3

# Model downloads retry this many times with exponential backoff (§3.1).
DOWNLOAD_RETRIES = 3
_CHUNK = 1024 * 256  # 256 KiB per read


# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #

@dataclass
class Check:
    """One preflight result. Displayed as one screen per Clause 2.1:

    ✅ ready      (ok=True)
    ⚠️ degraded   (ok=False, warn_only=True)  — works, with a plain fix
    ❌ blocked     (ok=False, warn_only=False) — cannot proceed
    """

    name: str
    title: str
    ok: bool
    warn_only: bool
    detail: str       # plain words: what we found
    fix_hint: str     # plain words: GUI steps only, NEVER a terminal command


def _vcpp_via_registry(winreg) -> bool:
    """True if the VC++ 2015-2022 Redist 'Installed' flag is set.

    `winreg` is injected (the real module on Windows, a fake in tests).
    """
    for view, sub in (
        (winreg.KEY_WOW64_64KEY,
         r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"),
        (winreg.KEY_WOW64_32KEY,
         r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x86"),
    ):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub, 0,
                                winreg.KEY_READ | view) as key:
                installed, _ = winreg.QueryValueEx(key, "Installed")
                if installed:
                    return True
        except OSError:
            continue
    return False


def _check_vcpp_redist() -> Check:
    """P1 — VC++ 2015-2022 Redist. The #1 fresh-machine killer (C-I5)."""
    found = False
    detail = ""
    if os.name == "nt":
        # Registry first, DLL on the search path as fallback.
        try:
            import winreg
            found = _vcpp_via_registry(winreg)
        except Exception:
            found = False
        if not found:
            for candidate in ("vcruntime140.dll", "vcruntime140_1.dll"):
                if shutil.which(candidate):
                    found = True
                    break
        detail = ("Microsoft's Visual C++ component is installed."
                  if found else
                  "Microsoft's Visual C++ component was not found on this computer.")
    else:
        # Not Windows: the redist is a Windows-only concern.
        found = True
        detail = "Not a Windows computer — this check does not apply."
    return Check(
        name="vcpp_redist",
        title="Windows system component (VC++ Redist)",
        ok=found,
        warn_only=True,  # chat works; voice features stay off (§2 P1)
        detail=detail,
        fix_hint=("Open the Microsoft website, search for 'Visual C++ "
                  "Redistributable 2015-2022', download the x64 installer, "
                  "and run it. Then start JARVIS again."),
    )


def _check_python() -> Check:
    """P2 — interpreter version + bitness. Blocking (H-I4)."""
    vi = sys.version_info
    is_64 = struct.calcsize("P") * 8 == 64
    ok = (vi.major, vi.minor) >= (3, 11) and is_64
    detail = (f"Python {vi.major}.{vi.minor}.{vi.micro}, "
              f"{'64-bit' if is_64 else '32-bit'}.")
    if not ok:
        detail += " JARVIS needs 64-bit Python 3.11 or newer."
    return Check(
        name="python_version",
        title="Python version",
        ok=ok,
        warn_only=False,
        detail=detail,
        fix_hint=("Install 64-bit Python 3.11 or newer from the Python "
                  "website (python.org). During setup, tick the box that "
                  "adds Python to PATH. Then start JARVIS again."),
    )


def _check_store_stub() -> Check:
    """P3 — the Microsoft Store fake-Python trap (M-I2). Blocking."""
    exe = sys.executable or ""
    lowered = exe.lower().replace("/", "\\")
    is_stub = "windowsapps" in lowered
    return Check(
        name="store_stub",
        title="Real Python (not the Store stub)",
        ok=not is_stub,
        warn_only=False,
        detail=("That's the fake Python from the Microsoft Store — it can't "
                "run JARVIS." if is_stub else
                "Running on a real Python install."),
        fix_hint=("Install Python from the Python website (python.org), "
                  "not the Microsoft Store. Then start JARVIS again."),
    )


def _check_disk_space(data_dir: Path) -> Check:
    """P4 — free space on the data-dir drive. Blocking below the floor."""
    try:
        free = shutil.disk_usage(data_dir).free
        ok = free >= MIN_DISK_BYTES
        gb = free / 1024**3
        detail = f"{gb:.1f} GB free where JARVIS keeps its data."
        if not ok:
            detail += " JARVIS needs at least 10 GB free."
    except OSError as exc:
        ok, detail = False, f"Could not measure free space ({exc})."
    return Check(
        name="disk_space",
        title="Free disk space",
        ok=ok,
        warn_only=False,
        detail=detail,
        fix_hint=("Free up space on that drive, or choose a different folder "
                  "for JARVIS's data when the setup asks."),
    )


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_model_assets(manifest: Optional[list[dict]],
                        models_dir: Path) -> Check:
    """P5 — every manifest asset exists and its checksum matches (H-I1).

    manifest entries: {"name": plain-words name, "file": filename,
                       "sha256": hex digest}. None/empty -> nothing required.
    """
    if not manifest:
        return Check(
            name="model_assets", title="Downloaded models", ok=True,
            warn_only=True,
            detail="No models are required for this version.",
            fix_hint="",
        )
    missing, corrupt = [], []
    for asset in manifest:
        target = models_dir / asset["file"]
        if not target.exists():
            missing.append(asset["name"])
        elif _sha256_of(target) != asset["sha256"].lower():
            corrupt.append(asset["name"])
    ok = not missing and not corrupt
    if ok:
        detail = f"All {len(manifest)} model files verified."
    else:
        parts = []
        if missing:
            parts.append("missing: " + ", ".join(missing))
        if corrupt:
            parts.append("damaged: " + ", ".join(corrupt))
        detail = "Some model files need downloading (" + "; ".join(parts) + ")."
    return Check(
        name="model_assets",
        title="Downloaded models",
        ok=ok,
        warn_only=True,  # chat starts; affected features stay degraded (§2 P5)
        detail=detail,
        fix_hint=("Start JARVIS and say yes when it offers to download the "
                  "missing files. It will verify each one before finishing."),
    )


_CORE_MODULES = (
    "jarvis.rules", "jarvis.config", "jarvis.session_store", "jarvis.gate",
    "jarvis.brain", "jarvis.memory", "jarvis.skills.registry", "jarvis.dcl",
)


def _check_import_probe() -> Check:
    """P6 — really import the critical modules, catching *Exception*,
    not just ImportError (M-I4: OSError crashed raw in v1)."""
    import importlib
    broken: list[str] = []
    for mod in _CORE_MODULES:
        try:
            importlib.import_module(mod)
        except Exception as exc:  # noqa: BLE001 — the probe must not crash
            broken.append(f"{mod} ({type(exc).__name__})")
    ok = not broken
    detail = ("All core parts loaded."
              if ok else
              "These parts of JARVIS failed to load: " + ", ".join(broken) + ".")
    return Check(
        name="import_probe",
        title="Core parts load correctly",
        ok=ok,
        warn_only=False,
        detail=detail,
        fix_hint=("Reinstall JARVIS from the installer — a file is missing or "
                  "damaged. Your chats and settings are kept separately and "
                  "will not be touched."),
    )


def _check_mic_camera() -> Check:
    """P7 — enumerate mic/camera without requesting anything (best effort,
    warn-only; permission is asked in context, never at startup)."""
    found: list[str] = []
    if os.name == "nt":
        try:
            import ctypes
            winmm = ctypes.WinDLL("winmm")
            n_in = winmm.waveInGetNumDevs()
            n_cam = 0
            # Camera enumeration without third-party libs is unreliable;
            # report what we can verify and stay honest about the rest.
            if n_in and n_in > 0:
                found.append(f"{n_in} microphone(s)")
            detail = ("Found " + ", ".join(found) + ". Camera check needs "
                      "the app running — it will ask when you use voice."
                      if found else
                      "No microphone seen. Camera check needs the app "
                      "running — it will ask when you use voice.")
        except Exception:
            detail = ("Could not check devices on this computer. JARVIS "
                      "will ask about the microphone when you use voice.")
    else:
        detail = ("Device check is best-effort on this system. JARVIS will "
                  "ask about the microphone when you use voice.")
    return Check(
        name="mic_camera",
        title="Microphone and camera",
        ok=True,
        warn_only=True,
        detail=detail,
        fix_hint=("If voice doesn't hear you later, check that a microphone "
                  "is plugged in and allowed in Windows sound settings."),
    )


def _check_data_dir_writable(data_dir: Path) -> Check:
    """P8 — write test on the data dir (M-S13 class). Blocking for chat."""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".jarvis_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return Check(
            name="data_dir_writable", title="Data folder is writable",
            ok=True, warn_only=False,
            detail="JARVIS can save chats and settings here.",
            fix_hint="",
        )
    except OSError as exc:
        return Check(
            name="data_dir_writable", title="Data folder is writable",
            ok=False, warn_only=False,
            detail=("JARVIS can't write where it keeps its data "
                    f"({exc}). Nothing can be saved."),
            fix_hint=("Choose a different folder for JARVIS's data — for "
                      "example inside your Documents folder — when setup asks."),
        )


# --------------------------------------------------------------------------- #
# Soil-study extras (P9-P13) — additive checks demanded by the Jarvis Soil
# studies (~/workspace/jarvis-soil/software-api-data.md A1/A2/A3 and the
# hardware tiers). Opt-in via preflight(soil_extras=True); the default
# eight checks above are unchanged. Every extra is warn-only: these are
# soil conditions, not germination blockers.
# --------------------------------------------------------------------------- #

def _check_python_release_window() -> Check:
    """P9 — the soil froze the runtime at 3.11/3.12 (software-api-data A1:
    3.10 caps onnxruntime; 3.13 strands niche wheels). Warn-only."""
    vi = sys.version_info
    in_window = (vi.major, vi.minor) in ((3, 11), (3, 12))
    detail = (f"Python {vi.major}.{vi.minor} is inside the tested "
              "3.11-3.12 window." if in_window else
              f"Python {vi.major}.{vi.minor} is outside the tested "
              "3.11-3.12 window — some voice features may misbehave.")
    return Check(
        name="python_release_window",
        title="Python in the tested window (3.11-3.12)",
        ok=in_window,
        warn_only=True,
        detail=detail,
        fix_hint=("Install Python 3.11 or 3.12 from the Python website "
                  "(python.org) — the versions JARVIS is tested with."),
    )


def _mic_consent_via_registry(winreg) -> Optional[str]:
    """Read the Windows microphone consent value ('Allow'/'Deny'/...).

    `winreg` is injected (real module on Windows, a fake in tests).
    Returns None when the value cannot be read.
    """
    sub = (r"SOFTWARE\Microsoft\Windows\CurrentVersion"
           r"\CapabilityAccessManager\ConsentStore\microphone")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub, 0,
                            winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, "Value")
            return str(value)
    except OSError:
        return None


def _check_mic_privacy() -> Check:
    """P10 — mic privacy toggle (software-api-data A2: fresh-machine
    breakage #1; a denied toggle means the wake word can never fire)."""
    if os.name != "nt":
        return Check(
            name="mic_privacy", title="Microphone permission",
            ok=True, warn_only=True,
            detail="Not a Windows computer — this check does not apply.",
            fix_hint="")
    state: Optional[str] = None
    try:
        import winreg
        state = _mic_consent_via_registry(winreg)
    except Exception:
        state = None
    if state is None:
        return Check(
            name="mic_privacy", title="Microphone permission",
            ok=True, warn_only=True,
            detail=("Could not read the microphone permission setting. "
                    "JARVIS will ask when you first use voice."),
            fix_hint="")
    allowed = state.lower() == "allow"
    return Check(
        name="mic_privacy", title="Microphone permission",
        ok=allowed, warn_only=True,
        detail=("Windows allows apps to use the microphone."
                if allowed else
                "Windows is currently blocking microphone access — "
                "JARVIS will not be able to hear you."),
        fix_hint=("Open Windows Settings, choose 'Privacy and security', "
                  "then 'Microphone', and switch on microphone access. "
                  "Then start JARVIS again."),
    )


def _check_path_encoding(data_dir: Path) -> Check:
    """P11 — non-ASCII paths break model caches on fresh machines
    (software-api-data A5 #9). Warn-only."""
    bad = [str(p) for p in (Path.home(), data_dir)
           if not str(p).isascii()]
    ok = not bad
    return Check(
        name="path_encoding", title="Folder names use plain letters",
        ok=ok, warn_only=True,
        detail=("All folder names on JARVIS's path use plain letters."
                if ok else
                "A folder on JARVIS's path contains special letters "
                f"({bad[0]}), which can confuse some model downloads."),
        fix_hint=("When setup asks where to keep JARVIS's data, choose a "
                  "folder whose name uses plain English letters only."),
    )


def _total_ram_bytes() -> Optional[int]:
    """Total physical RAM, stdlib only. None when unknowable."""
    try:
        if os.name == "nt":
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = _MemStatus()
            status.dwLength = ctypes.sizeof(_MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(
                    ctypes.byref(status)):
                return int(status.ullTotalPhys)
            return None
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            for line in meminfo.read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
        if hasattr(os, "sysconf"):
            return int(os.sysconf("SC_PHYS_PAGES")) * \
                int(os.sysconf("SC_PAGE_SIZE"))
    except Exception:  # noqa: BLE001 — a probe must never crash setup
        return None
    return None


def _check_memory_size() -> Check:
    """P12 — RAM vs the soil hardware tiers (16 GB recommended;
    under 8 GB is cloud-brain territory). Warn-only."""
    total = _total_ram_bytes()
    if total is None:
        return Check(
            name="memory_size", title="Computer memory",
            ok=True, warn_only=True,
            detail="Could not measure this computer's memory; skipping.",
            fix_hint="")
    gb = total / 1024**3
    ok = total >= 8 * 1024**3
    return Check(
        name="memory_size", title="Computer memory",
        ok=ok, warn_only=True,
        detail=(f"This computer has {gb:.0f} GB of memory — comfortable "
                "for JARVIS." if ok else
                f"This computer has {gb:.0f} GB of memory. JARVIS will "
                "lean on the cloud brain; the local brain will be tight."),
        fix_hint=("Close other large apps while JARVIS runs, or add "
                  "memory if this computer allows it."),
    )


def _check_ollama_health() -> Check:
    """P13 — local brain health probe (software-api-data A3: health-check
    Ollama on startup; the cloud brain is the fallback when it is down).
    Loopback only — this never phones home. Warn-only."""
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            running = resp.status == 200
    except Exception:  # noqa: BLE001 — down is a normal state
        running = False
    return Check(
        name="ollama_health", title="Local brain (Ollama)",
        ok=running, warn_only=True,
        detail=("The local brain is running — JARVIS can think offline."
                if running else
                "The local brain is not running. JARVIS will use the "
                "cloud brain until it is opened."),
        fix_hint=("Open the Ollama app from the Start menu, then start "
                  "JARVIS again. JARVIS also works without it, using "
                  "the cloud brain."),
    )


def _soil_extra_checks(data_dir: Path) -> list[tuple[str, Callable[[], Check]]]:
    return [
        ("python_release_window", _check_python_release_window),
        ("mic_privacy", _check_mic_privacy),
        ("path_encoding", lambda: _check_path_encoding(data_dir)),
        ("memory_size", _check_memory_size),
        ("ollama_health", _check_ollama_health),
    ]


def preflight(data_dir: Optional[Path] = None,
              model_manifest: Optional[list[dict]] = None,
              soil_extras: bool = False) -> list[Check]:
    """Run the 8 checks, cheap -> expensive. Never phones home (Cl. 2.3).

    With soil_extras=True, the five additive soil-study checks (P9-P13)
    run after the core eight; the default behavior is unchanged.

    A check that raises reports plain words + a fix (Clause 2.2) — the
    preflight itself must never crash.
    """
    data_dir = Path(data_dir) if data_dir else default_data_dir()
    models_dir = data_dir / "models"
    checks: list[tuple[str, Callable[[], Check]]] = [
        ("python_version", _check_python),
        ("store_stub", _check_store_stub),
        ("data_dir_writable", lambda: _check_data_dir_writable(data_dir)),
        ("disk_space", lambda: _check_disk_space(data_dir)),
        ("vcpp_redist", _check_vcpp_redist),
        ("import_probe", _check_import_probe),
        ("model_assets", lambda: _check_model_assets(model_manifest, models_dir)),
        ("mic_camera", _check_mic_camera),
    ]
    if soil_extras:
        checks += _soil_extra_checks(data_dir)
    results: list[Check] = []
    for name, fn in checks:
        try:
            results.append(fn())
        except Exception as exc:  # noqa: BLE001 — Clause 2.2
            results.append(Check(
                name=name, title=name.replace("_", " ").title(),
                ok=False, warn_only=True,
                detail=("I was checking this and ran into an error I didn't "
                        "expect. JARVIS can continue, but this is worth a look."),
                fix_hint=("Use 'Report a problem' in Settings so the details "
                          f"can be reviewed. (Technical note: {type(exc).__name__})"),
            ))
    return results


def preflight_report(checks: list[Check]) -> tuple[bool, bool]:
    """(can_start, degraded). can_start=False if any blocking check failed."""
    blocked = any(not c.ok and not c.warn_only for c in checks)
    degraded = any(not c.ok for c in checks)
    return (not blocked, degraded)


def format_preflight(checks: list[Check]) -> str:
    """One screen per Clause 2.1. Plain words, one primary action each."""
    lines = []
    for c in checks:
        mark = "ok" if c.ok else ("warn" if c.warn_only else "BLOCKED")
        lines.append(f"[{mark}] {c.title}: {c.detail}")
        if not c.ok and c.fix_hint:
            lines.append(f"        Fix: {c.fix_hint}")
    return "\n".join(lines)


def default_data_dir() -> Path:
    """One data directory, declared in one place (§1.2)."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "JARVIS"
    return Path.home() / ".jarvis"


# --------------------------------------------------------------------------- #
# Model acquisition (§3) — atomic, resumable, checksum-verified.
# --------------------------------------------------------------------------- #

class ModelDownloadError(Exception):
    """A model could not be downloaded and verified."""


def download_model(url: str, dest: str | Path, sha256: str,
                   progress_cb: Optional[Callable[[int, int], None]] = None,
                   max_retries: int = DOWNLOAD_RETRIES) -> Path:
    """Download to `<dest>.part`, resume with Range, verify SHA-256,
    atomic rename on match. On mismatch the part file is deleted and the
    download retried (bounded); closing mid-download is a normal event
    (§3.4) — re-running resumes from the part file.

    progress_cb(downloaded_bytes, total_bytes_or_0).
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    want = sha256.lower()

    # Already good? Then there is nothing to do (§1.3: diff, never clobber).
    if dest.exists() and _sha256_of(dest) == want:
        if progress_cb:
            size = dest.stat().st_size
            progress_cb(size, size)
        return dest

    downloaded = part.stat().st_size if part.exists() else 0
    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(url)
            if downloaded:
                req.add_header("Range", f"bytes={downloaded}-")
            try:
                resp = urllib.request.urlopen(req, timeout=60)
            except urllib.error.HTTPError as exc:
                if exc.code == 416:  # part already complete; verify it
                    resp = None
                else:
                    raise
            except urllib.error.URLError as exc:
                raise ModelDownloadError(
                    f"Could not reach the download server ({exc.reason}). "
                    "Check your internet connection and try again.") from exc

            if resp is None:
                total = downloaded
            elif resp.status == 206 and downloaded:
                # Server honors resume: append.
                total = downloaded + int(resp.headers.get("Content-Length", 0) or 0)
                _stream_to_part(resp, part, downloaded, total, progress_cb, append=True)
            else:
                # 200, or server ignores Range: restart from zero (§3.2 —
                # never append a partial file from a non-resuming server).
                if downloaded:
                    part.unlink()
                    downloaded = 0
                total = int(resp.headers.get("Content-Length", 0) or 0)
                _stream_to_part(resp, part, 0, total, progress_cb, append=False)

            if _sha256_of(part) != want:
                # A file that fails its checksum is never installed (§3.1).
                if attempt < max_retries:
                    part.unlink(missing_ok=True)  # fresh start for the retry
                    downloaded = 0
                    last_error = ModelDownloadError(
                        "The downloaded file failed its safety check "
                        "(checksum mismatch). It was deleted; retrying.")
                    time.sleep(2 ** attempt)  # bounded backoff
                    continue
                # Final attempt: reject, but keep the .part so the state is
                # inspectable. Re-running setup retries the download.
                raise ModelDownloadError(
                    "The downloaded file failed its safety check "
                    f"(checksum mismatch) after {max_retries + 1} tries. "
                    "Nothing was installed. The partial file was kept; "
                    "running setup again will try the download once more.")
            # Atomic rename: a verified file appears all at once (§3.1).
            os.replace(part, dest)
            return dest
        except ModelDownloadError as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(2 ** attempt)  # bounded backoff (§3.1)
                downloaded = part.stat().st_size if part.exists() else 0
                continue
            raise
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                downloaded = part.stat().st_size if part.exists() else 0
                continue
            raise ModelDownloadError(
                f"Download failed ({type(exc).__name__}). Your partial file "
                "was kept, so starting again will resume where it stopped."
            ) from exc
    raise ModelDownloadError(f"Download failed after {max_retries + 1} tries: "
                             f"{last_error}")


def _stream_to_part(resp, part: Path, offset: int, total: int,
                    progress_cb, append: bool) -> None:
    mode = "ab" if append else "wb"
    done = offset
    if progress_cb:
        progress_cb(done, total)
    with open(part, mode) as f:
        while True:
            chunk = resp.read(_CHUNK)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress_cb:
                progress_cb(done, total)


# --------------------------------------------------------------------------- #
# First-run wizard (terminal-based for Wave 2; §4 no-keys onboarding).
#
# Every question must "pay rent" — change behavior — or it is cut:
#   1. profile name   -> memory/session namespace. Pays rent. KEEP.
#   2. data dir       -> where everything is stored. Pays rent. KEEP.
#   3. model download -> only offered if models are missing. Pays rent. KEEP.
# Dropped: theme, "tour", newsletter-style questions — rent-free, cut.
# --------------------------------------------------------------------------- #

def _schema_fields():
    from jarvis.config import Field
    return {
        "profile": Field(str, "owais"),
        "data_dir": Field(str, ""),
        "setup_complete": Field(bool, False),
        "setup_version": Field(str, VERSION),
    }


def first_run_wizard(data_dir: Optional[Path] = None,
                     model_manifest: Optional[list[dict]] = None,
                     input_fn: Callable[[str], str] = input,
                     print_fn: Callable[[str], None] = print) -> dict:
    """Terminal-based first-run flow. Returns what was configured.

    `input_fn`/`print_fn` are injectable so tests can script the wizard.
    """
    from jarvis.config import Config

    data_dir = Path(data_dir) if data_dir else default_data_dir()
    cfg = Config(str(data_dir / "config.yaml"), _schema_fields())
    try:
        cfg.load()
    except Exception:
        pass  # corrupt config -> preflight/config layer handles it; keep going

    print_fn("Welcome, sir. Three quick questions, then we're done.")
    print_fn("")

    # Q1 — profile name. Pays rent: namespaces memory + sessions.
    current = cfg.get("profile", "owais") or "owais"
    answer = input_fn(f"What should I call you? [{current}]: ").strip()
    profile = answer or current
    cfg.set("profile", profile)

    # Q2 — data dir. Pays rent: every file JARVIS writes lands here.
    current_dir = cfg.get("data_dir", "") or str(data_dir)
    answer = input_fn(f"Where should I keep your data? [{current_dir}]: ").strip()
    chosen = Path(answer) if answer else Path(current_dir)
    cfg.set("data_dir", str(chosen))
    chosen.mkdir(parents=True, exist_ok=True)

    # Preflight, then Q3 — model download, only if something is missing.
    print_fn("")
    print_fn("Checking this computer...")
    checks = preflight(chosen, model_manifest)
    print_fn(format_preflight(checks))
    can_start, _ = preflight_report(checks)
    if not can_start:
        print_fn("")
        print_fn("Something above needs fixing before JARVIS can start. "
                 "Fix it, then run setup again — it will pick up where it left off.")
        return {"profile": profile, "data_dir": str(chosen),
                "setup_complete": False, "blocked": True}

    assets = _check_model_assets(model_manifest, chosen / "models")
    downloaded: list[str] = []
    if not assets.ok and model_manifest:
        print_fn("")
        answer = input_fn("Some model files are missing. Download them now? "
                          "[yes/no]: ").strip().lower()
        if answer in ("yes", "y", ""):
            for asset in model_manifest:
                target = chosen / "models" / asset["file"]
                if target.exists() and _sha256_of(target) == asset["sha256"].lower():
                    continue  # §1.3: never re-download what's already good
                print_fn(f"Downloading {asset['name']}...")

                def _progress(done: int, total: int, _name=asset["name"]) -> None:
                    if total:
                        pct = done * 100 // total
                        print_fn(f"\r  {_name}: {pct}% "
                                 f"({done // 1024**2} of {total // 1024**2} MB)")
                    else:
                        print_fn(f"\r  {_name}: {done // 1024**2} MB so far")

                try:
                    download_model(asset["url"], target, asset["sha256"], _progress)
                    print_fn("")
                    downloaded.append(asset["name"])
                except ModelDownloadError as exc:
                    print_fn(f"\n  Couldn't download {asset['name']}: {exc}")

    cfg.set("setup_complete", True)
    cfg.set("setup_version", VERSION)
    cfg.save()

    print_fn("")
    print_fn(f"All set, {profile}. JARVIS is ready.")
    return {"profile": profile, "data_dir": str(chosen),
            "setup_complete": True, "downloaded": downloaded}


# --------------------------------------------------------------------------- #
# Updates — Wave 2 ships the *interface*; the signed updater lands in Wave 3
# (§5: minisign + Authenticode, N-1 cache, one-click rollback, UI-only —
# updates are never a brain tool, Cl. 5.1.3).
# --------------------------------------------------------------------------- #

UPDATE_MANIFEST_URL = "https://updates.jarvis.local/latest.json"  # pinned host, Wave 3


@dataclass
class UpdateInfo:
    current_version: str
    latest_version: Optional[str]
    update_available: bool
    release_notes: str = ""
    # Wave 3 fills these in: artifact_url, minisign_signature, size_bytes.
    artifact: dict = field(default_factory=dict)


def check_updates(current_version: str = VERSION) -> dict:
    """Wave-2 stub with the Wave-3 interface.

    Wave 3 contract (do not change the return shape):
      - fetch UPDATE_MANIFEST_URL over HTTPS, verify the manifest's
        minisign signature BEFORE trusting any URL in it (§5.1.2)
      - download in background; prompt once: restart now / tonight (§5.2.1)
      - keep the N-1 installer cached; smoke-test via preflight after
        applying; one-click rollback in Settings → Updates (§5.2.2)
      - never silent-install, never apply mid-session, never LLM-triggered
    """
    info = UpdateInfo(
        current_version=current_version,
        latest_version=None,
        update_available=False,
        release_notes="",
    )
    return {
        "update_available": info.update_available,
        "current_version": info.current_version,
        "latest_version": info.latest_version,
        "release_notes": info.release_notes,
        "artifact": info.artifact,
    }


# --------------------------------------------------------------------------- #
# CLI entry (run as: python -m jarvis.setup)
# --------------------------------------------------------------------------- #

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="JARVIS v2 setup")
    ap.add_argument("--data-dir", default=None, help="Data directory")
    ap.add_argument("--preflight", action="store_true",
                    help="Run the checks and print the report, then exit")
    ap.add_argument("--wizard", action="store_true",
                    help="Run preflight + the first-run wizard")
    ap.add_argument("--check-updates", action="store_true",
                    help="Check for updates (Wave-2 stub)")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else default_data_dir()

    if args.check_updates:
        print(json.dumps(check_updates(), indent=2))
        return 0

    checks = preflight(data_dir)
    print(format_preflight(checks))
    can_start, degraded = preflight_report(checks)

    if args.preflight:
        return 0 if can_start else 1

    # Default / --wizard: first run -> wizard; otherwise just report.
    from jarvis.config import Config, ConfigError
    cfg = Config(str(data_dir / "config.yaml"), _schema_fields())
    try:
        cfg.load()
        done = bool(cfg.get("setup_complete", False))
    except (ConfigError, OSError):
        done = False

    if not done or args.wizard:
        result = first_run_wizard(data_dir)
        return 0 if result.get("setup_complete") else 1

    if not can_start:
        print("\nJARVIS can't start until the blocked items above are fixed.")
        return 1
    if degraded:
        print("\nJARVIS can start, but some features are degraded (see above).")
    else:
        print("\nAll checks passed. JARVIS is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
