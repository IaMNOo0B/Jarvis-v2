"""Tests for jarvis.setup — preflight, model acquisition, wizard, updates.

Conventions: stdlib only (+ pytest). Fake HTTP server via http.server in a
thread. Fake winreg injected into _vcpp_via_registry. Wizard driven with
scripted input_fn/print_fn.
"""

from __future__ import annotations

import hashlib
import http.server
import os
import re
import socketserver
import threading
from pathlib import Path

import pytest

from jarvis import setup
from jarvis.setup import (
    Check,
    ModelDownloadError,
    _check_model_assets,
    _check_vcpp_redist,
    _sha256_of,
    _vcpp_via_registry,
    check_updates,
    download_model,
    first_run_wizard,
    format_preflight,
    preflight,
    preflight_report,
)


# --------------------------------------------------------------------------- #
# Fake winreg (mocked registry: pass + fail paths)
# --------------------------------------------------------------------------- #

class _FakeKey:
    def __init__(self, installed):
        self._installed = installed

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeWinreg:
    KEY_WOW64_64KEY = 0x100
    KEY_WOW64_32KEY = 0x200
    HKEY_LOCAL_MACHINE = 0
    KEY_READ = 1

    def __init__(self, installed):
        # installed=None -> OpenKey raises OSError (key missing)
        self._installed = installed

    def OpenKey(self, *args):
        if self._installed is None:
            raise OSError("no such key")
        return _FakeKey(self._installed)

    def QueryValueEx(self, key, name):
        assert name == "Installed"
        return (self._installed, None)


def test_vcpp_registry_present():
    assert _vcpp_via_registry(_FakeWinreg(1)) is True


def test_vcpp_registry_flag_zero():
    assert _vcpp_via_registry(_FakeWinreg(0)) is False


def test_vcpp_registry_key_missing():
    assert _vcpp_via_registry(_FakeWinreg(None)) is False


def test_vcpp_check_shape():
    c = _check_vcpp_redist()
    assert isinstance(c, Check)
    assert c.name == "vcpp_redist"
    assert c.warn_only is True  # chat works; voice degraded (§2 P1)
    assert c.fix_hint  # a plain-words fix is always offered


# --------------------------------------------------------------------------- #
# Preflight: structure, order, never-crashes, honest reporting
# --------------------------------------------------------------------------- #

_EXPECTED_ORDER = [
    "python_version", "store_stub", "data_dir_writable", "disk_space",
    "vcpp_redist", "import_probe", "model_assets", "mic_camera",
]


@pytest.fixture
def plenty_of_disk(monkeypatch):
    """Simulate a drive that meets the floor (this sandbox has < 1 GB)."""
    monkeypatch.setattr(setup, "MIN_DISK_BYTES", 0)


def test_preflight_eight_checks_in_order(tmp_path):
    checks = preflight(tmp_path)
    assert [c.name for c in checks] == _EXPECTED_ORDER
    for c in checks:
        assert c.title and c.detail  # every check explains itself


def test_preflight_all_pass_on_dev_box(tmp_path, plenty_of_disk):
    checks = preflight(tmp_path)
    can_start, degraded = preflight_report(checks)
    assert can_start is True
    assert degraded is False


def test_preflight_never_crashes_on_check_error(tmp_path, monkeypatch):
    def boom():
        raise RuntimeError("surprise")

    monkeypatch.setattr(setup, "_check_disk_space", boom)
    checks = preflight(tmp_path)
    assert len(checks) == 8
    disk = next(c for c in checks if c.name == "disk_space")
    assert disk.ok is False and disk.warn_only is True
    assert "didn't expect" in disk.detail  # Clause 2.2: plain words


def test_preflight_blocking_failure_blocks_start(tmp_path, monkeypatch):
    bad = Check(name="x", title="X", ok=False, warn_only=False,
                detail="bad", fix_hint="fix it")
    monkeypatch.setattr(setup, "_check_python", lambda: bad)
    checks = preflight(tmp_path)
    can_start, _ = preflight_report(checks)
    assert can_start is False


def test_preflight_warn_only_degrades_but_starts(tmp_path, monkeypatch,
                                                  plenty_of_disk):
    warn = Check(name="x", title="X", ok=False, warn_only=True,
                 detail="degraded", fix_hint="fix it")
    monkeypatch.setattr(setup, "_check_vcpp_redist", lambda: warn)
    checks = preflight(tmp_path)
    can_start, degraded = preflight_report(checks)
    assert can_start is True and degraded is True


def test_format_preflight_marks_states(tmp_path, monkeypatch):
    warn = Check(name="x", title="Ex", ok=False, warn_only=True,
                 detail="d", fix_hint="f")
    blocked = Check(name="y", title="Why", ok=False, warn_only=False,
                    detail="d", fix_hint="f")
    out = format_preflight([warn, blocked])
    assert "[warn]" in out and "[BLOCKED]" in out
    assert "Fix: f" in out


def test_disk_check_fail_and_pass_paths(tmp_path, monkeypatch):
    from jarvis.setup import _check_disk_space
    monkeypatch.setattr(setup, "MIN_DISK_BYTES", 10 ** 18)  # impossible floor
    c = _check_disk_space(tmp_path)
    assert c.ok is False and c.warn_only is False
    assert "10 GB" in c.detail
    monkeypatch.setattr(setup, "MIN_DISK_BYTES", 0)
    c = _check_disk_space(tmp_path)
    assert c.ok is True


# Zero-terminal rule (Clause 6.1): no terminal command in user strings.
_TERMINAL_PATTERNS = [
    r"pip\s+install", r"pip3\s+install",
    r"\bgit\s+(clone|pull|reset|checkout)\b",
    r"\bpython\s+-m\b", r"\bpython3?\s+[\w/\\-]+\.py\b",
    r"powershell", r"cmd\.exe",
    r"open a terminal",
]


def _all_user_strings(tmp_path):
    strings = []
    for c in preflight(tmp_path):
        strings.append(c.detail)
        strings.append(c.fix_hint)
    strings.append(format_preflight(preflight(tmp_path)))
    return "\n".join(strings)


def test_zero_terminal_in_preflight_strings(tmp_path):
    text = _all_user_strings(tmp_path)
    for pat in _TERMINAL_PATTERNS:
        assert not re.search(pat, text, re.IGNORECASE), f"terminal cmd: {pat}"


def test_zero_terminal_in_download_errors():
    for msg in [
        "Could not reach the download server (nope). Check your internet "
        "connection and try again.",
        "The downloaded file failed its safety check (checksum mismatch) "
        "after 4 tries. Nothing was installed.",
    ]:
        for pat in _TERMINAL_PATTERNS:
            assert not re.search(pat, msg, re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Model-asset check (P5)
# --------------------------------------------------------------------------- #

def _manifest_for(path: Path, name="Test model") -> list[dict]:
    return [{"name": name, "file": path.name, "sha256": _sha256_of(path)}]


def test_model_assets_none_required(tmp_path):
    c = _check_model_assets(None, tmp_path)
    assert c.ok is True


def test_model_assets_verified(tmp_path):
    f = tmp_path / "m.bin"
    f.write_bytes(b"good-bytes")
    c = _check_model_assets(_manifest_for(f), tmp_path)
    assert c.ok is True and "verified" in c.detail


def test_model_assets_missing_and_corrupt(tmp_path):
    good = tmp_path / "m.bin"
    good.write_bytes(b"good-bytes")
    manifest = _manifest_for(good) + [
        {"name": "Missing model", "file": "gone.bin",
         "sha256": "0" * 64},
    ]
    bad = tmp_path / "m.bin"
    bad.write_bytes(b"tampered")
    c = _check_model_assets(manifest, tmp_path)
    assert c.ok is False and c.warn_only is True  # degraded, not blocked
    assert "Missing model" in c.detail and "Test model" in c.detail


# --------------------------------------------------------------------------- #
# Download: fake HTTP server
# --------------------------------------------------------------------------- #

class _RangeHandler(http.server.BaseHTTPRequestHandler):
    data: bytes = b""
    support_range: bool = True
    seen_range: list = []

    def do_GET(self):
        body = type(self).data
        start = 0
        status = 200
        rng = self.headers.get("Range")
        if rng:
            type(self).seen_range.append(rng)
        if type(self).support_range and rng:
            try:
                start = int(rng.split("=")[1].split("-")[0])
                status = 206
            except (ValueError, IndexError):
                start, status = 0, 200
        body = body[start:]
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        if status == 206:
            total = len(type(self).data)
            self.send_header(
                "Content-Range", f"bytes {start}-{total - 1}/{total}")
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def file_server():
    """Yields (url, handler_cls). Set handler_cls.data / .support_range."""
    _RangeHandler.data = b""
    _RangeHandler.support_range = True
    _RangeHandler.seen_range = []
    with socketserver.TCPServer(("127.0.0.1", 0), _RangeHandler) as httpd:
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        yield f"http://127.0.0.1:{port}/model.bin", _RangeHandler
        httpd.shutdown()


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_download_success(tmp_path, file_server):
    url, handler = file_server
    handler.data = b"ab" * 200_000  # 400 KiB
    dest = tmp_path / "models" / "m.bin"
    seen = []
    out = download_model(url, dest, _sha(handler.data),
                         progress_cb=lambda d, t: seen.append((d, t)))
    assert out == dest
    assert dest.read_bytes() == handler.data
    assert not dest.with_name(dest.name + ".part").exists()  # atomic rename
    assert seen and seen[-1] == (len(handler.data), len(handler.data))


def test_download_resume_from_partial(tmp_path, file_server):
    url, handler = file_server
    handler.data = b"xy" * 300_000
    dest = tmp_path / "models" / "m.bin"
    part = dest.with_name(dest.name + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(handler.data[:200_000])  # 1/3 already there
    download_model(url, dest, _sha(handler.data), max_retries=0)
    assert dest.read_bytes() == handler.data
    assert handler.seen_range, "expected a Range request for resume"
    assert handler.seen_range[0].startswith("bytes=200000-")


def test_download_restarts_when_server_ignores_range(tmp_path, file_server):
    url, handler = file_server
    handler.data = b"q" * 100_000
    handler.support_range = False  # server always answers 200/full
    dest = tmp_path / "models" / "m.bin"
    part = dest.with_name(dest.name + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"stale-garbage-that-must-not-be-kept")
    download_model(url, dest, _sha(handler.data), max_retries=0)
    # §3.2: never append a partial file from a non-resuming server.
    assert dest.read_bytes() == handler.data


def test_download_checksum_mismatch_rejected_part_kept(tmp_path, file_server):
    url, handler = file_server
    handler.data = b"wrong-content"
    dest = tmp_path / "models" / "m.bin"
    part = dest.with_name(dest.name + ".part")
    with pytest.raises(ModelDownloadError, match="safety check"):
        download_model(url, dest, _sha(b"expected-content"), max_retries=0)
    assert not dest.exists(), "a bad file must never be installed"
    assert part.exists(), "partial file kept for inspection / re-run"


def test_download_already_good_skips_network(tmp_path, file_server):
    url, handler = file_server
    handler.data = b""  # server would fail; must not be touched
    dest = tmp_path / "models" / "m.bin"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"already-good")
    seen = []
    out = download_model(url, dest, _sha(b"already-good"),
                         progress_cb=lambda d, t: seen.append((d, t)))
    assert out == dest
    assert not handler.seen_range
    assert seen == [(len(b"already-good"), len(b"already-good"))]


def test_download_unreachable_server_plain_error(tmp_path):
    with pytest.raises(ModelDownloadError, match="internet connection"):
        download_model("http://127.0.0.1:1/none.bin",
                       tmp_path / "m.bin", "0" * 64, max_retries=0)


# --------------------------------------------------------------------------- #
# Wizard (scripted stdin)
# --------------------------------------------------------------------------- #

def _scripted(inputs: list[str]):
    it = iter(inputs)

    def input_fn(prompt: str = "") -> str:
        return next(it)

    printed: list[str] = []
    return input_fn, printed.append, printed


def test_wizard_happy_path(tmp_path, plenty_of_disk):
    input_fn, print_fn, printed = _scripted(["Test User", ""])
    result = first_run_wizard(tmp_path, None, input_fn, print_fn)
    assert result["setup_complete"] is True
    assert result["profile"] == "Test User"
    assert result.get("blocked") is not True
    assert (tmp_path / "config.yaml").exists()
    assert any("Welcome" in p for p in printed)


def test_wizard_defaults(tmp_path, plenty_of_disk):
    input_fn, print_fn, _ = _scripted(["", ""])
    result = first_run_wizard(tmp_path, None, input_fn, print_fn)
    assert result["setup_complete"] is True
    assert result["profile"] == "owais"  # default kept


def test_wizard_blocked_check_aborts(tmp_path, monkeypatch, plenty_of_disk):
    blocked = Check(name="python_version", title="Python", ok=False,
                    warn_only=False, detail="too old", fix_hint="upgrade")
    monkeypatch.setattr(setup, "preflight",
                        lambda *a, **k: [blocked])
    input_fn, print_fn, printed = _scripted(["U", ""])
    result = first_run_wizard(tmp_path, None, input_fn, print_fn)
    assert result["setup_complete"] is False
    assert result["blocked"] is True
    assert any("pick up where it left off" in p for p in printed)


def test_wizard_zero_terminal(tmp_path, plenty_of_disk):
    input_fn, print_fn, printed = _scripted(["", ""])
    first_run_wizard(tmp_path, None, input_fn, print_fn)
    text = "\n".join(printed)
    for pat in _TERMINAL_PATTERNS:
        assert not re.search(pat, text, re.IGNORECASE), f"terminal cmd: {pat}"


# --------------------------------------------------------------------------- #
# Updates: Wave-2 stub keeps the Wave-3 interface shape
# --------------------------------------------------------------------------- #

def test_check_updates_stub_shape():
    info = check_updates("2.1.0-wave2")
    assert info["update_available"] is False
    assert info["current_version"] == "2.1.0-wave2"
    assert "latest_version" in info
    assert "release_notes" in info
    assert "artifact" in info  # Wave 3 fills: url, minisign sig, size


def test_main_preflight_exit_zero(tmp_path, plenty_of_disk):
    from jarvis.setup import main
    assert main(["--data-dir", str(tmp_path), "--preflight"]) == 0

def test_desktop_chat_grants_web_and_approved_sandbox_capabilities():
    from jarvis.chat import TURN_ALLOWANCES

    assert "net.outbound" in TURN_ALLOWANCES
    assert "exec" in TURN_ALLOWANCES
    # PC shell execution remains a distinct capability added only when PC control is enabled.
    assert "shell.exec" not in TURN_ALLOWANCES

