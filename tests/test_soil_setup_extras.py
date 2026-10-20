"""Tests for the additive soil-study preflights in jarvis.setup (P9-P13).

The Jarvis Soil studies demand five more preflight checks (Python in the
tested 3.11-3.12 window, Windows mic-privacy consent, plain-letter
paths, RAM vs the hardware tiers, Ollama loopback health). They are
opt-in via preflight(soil_extras=True): the default eight checks and
their behavior are unchanged. Every extra is warn-only — soil
conditions degrade, they never block germination.
"""

from __future__ import annotations

import re
import sys
import urllib.error
from pathlib import Path

from jarvis import setup
from jarvis.setup import (
    _check_memory_size,
    _check_mic_privacy,
    _check_ollama_health,
    _check_path_encoding,
    _check_python_release_window,
    _mic_consent_via_registry,
    _total_ram_bytes,
    preflight,
    preflight_report,
)

_CORE_ORDER = [
    "python_version", "store_stub", "data_dir_writable", "disk_space",
    "vcpp_redist", "import_probe", "model_assets", "mic_camera",
]
_EXTRA_ORDER = [
    "python_release_window", "mic_privacy", "path_encoding",
    "memory_size", "ollama_health",
]

_TERMINAL_PATTERNS = [
    r"pip\s+install", r"pip3\s+install",
    r"\bgit\s+(clone|pull|reset|checkout)\b",
    r"\bpython\s+-m\b", r"\bpython3?\s+[\w/\\-]+\.py\b",
    r"powershell", r"cmd\.exe",
    r"open a terminal",
]


def test_default_preflight_unchanged(tmp_path):
    checks = preflight(tmp_path)
    assert [c.name for c in checks] == _CORE_ORDER


def test_soil_extras_append_after_core_eight(tmp_path):
    checks = preflight(tmp_path, soil_extras=True)
    assert [c.name for c in checks] == _CORE_ORDER + _EXTRA_ORDER
    for c in checks:
        assert c.title and c.detail


def test_soil_extras_are_all_warn_only(tmp_path, monkeypatch):
    # Isolate from the sandbox's small disk (core disk check floor) —
    # the claim under test is only that the EXTRAS never block.
    monkeypatch.setattr(setup, "MIN_DISK_BYTES", 0)
    checks = preflight(tmp_path, soil_extras=True)
    extras = [c for c in checks if c.name in _EXTRA_ORDER]
    assert extras and all(c.warn_only for c in extras)
    can_start, _ = preflight_report(checks)
    assert can_start is True  # extras can never block a start


def test_soil_extras_zero_terminal(tmp_path):
    checks = preflight(tmp_path, soil_extras=True)
    text = "\n".join(f"{c.detail}\n{c.fix_hint}" for c in checks)
    for pat in _TERMINAL_PATTERNS:
        assert not re.search(pat, text, re.IGNORECASE), f"terminal: {pat}"


def test_soil_extras_never_crash(tmp_path, monkeypatch):
    def boom():
        raise RuntimeError("surprise")

    monkeypatch.setattr(setup, "_check_memory_size", boom)
    checks = preflight(tmp_path, soil_extras=True)
    mem = next(c for c in checks if c.name == "memory_size")
    assert mem.ok is False and mem.warn_only is True


# --------------------------------------------------------------------------- #
# P9 — Python release window (soil froze 3.11/3.12)
# --------------------------------------------------------------------------- #

def test_python_release_window_matches_interpreter():
    c = _check_python_release_window()
    in_window = (sys.version_info.major, sys.version_info.minor) \
        in ((3, 11), (3, 12))
    assert c.ok is in_window
    assert c.warn_only is True


# --------------------------------------------------------------------------- #
# P10 — mic privacy consent via injected winreg
# --------------------------------------------------------------------------- #

class _FakeKey:
    def __init__(self, value):
        self._value = value

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeWinreg:
    HKEY_CURRENT_USER = 1
    KEY_READ = 1

    def __init__(self, value):
        # value=None -> OpenKey raises OSError (key missing)
        self._value = value

    def OpenKey(self, hive, sub, reserved, access):
        assert "CapabilityAccessManager" in sub
        assert "microphone" in sub
        if self._value is None:
            raise OSError("no such key")
        return _FakeKey(self._value)

    def QueryValueEx(self, key, name):
        assert name == "Value"
        return (key._value, None)


def test_mic_consent_allow():
    assert _mic_consent_via_registry(_FakeWinreg("Allow")) == "Allow"


def test_mic_consent_deny():
    assert _mic_consent_via_registry(_FakeWinreg("Deny")) == "Deny"


def test_mic_consent_missing_key():
    assert _mic_consent_via_registry(_FakeWinreg(None)) is None


def test_mic_privacy_check_shape():
    c = _check_mic_privacy()
    assert c.name == "mic_privacy" and c.warn_only is True


# --------------------------------------------------------------------------- #
# P11 — plain-letter paths
# --------------------------------------------------------------------------- #

def test_path_encoding_ascii_ok(tmp_path):
    c = _check_path_encoding(tmp_path)
    assert c.ok is True


def test_path_encoding_non_ascii_warns():
    c = _check_path_encoding(Path("/home/üser/JARVIS"))
    assert c.ok is False and c.warn_only is True
    assert c.fix_hint  # plain-words remedy offered


# --------------------------------------------------------------------------- #
# P12 — memory size vs soil tiers
# --------------------------------------------------------------------------- #

def test_total_ram_probe():
    ram = _total_ram_bytes()
    assert ram is None or ram > 0


def test_memory_size_check_consistent():
    c = _check_memory_size()
    assert c.name == "memory_size" and c.warn_only is True
    ram = _total_ram_bytes()
    if ram is not None:
        assert c.ok is (ram >= 8 * 1024**3)


# --------------------------------------------------------------------------- #
# P13 — Ollama loopback health (warn-only, never blocks)
# --------------------------------------------------------------------------- #

def test_ollama_health_down_is_warn_not_block(monkeypatch):
    def refused(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(setup.urllib.request, "urlopen", refused)
    c = _check_ollama_health()
    assert c.ok is False and c.warn_only is True
    assert "cloud brain" in c.detail


class _FakeResp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ollama_health_up(monkeypatch):
    monkeypatch.setattr(setup.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp())
    c = _check_ollama_health()
    assert c.ok is True
