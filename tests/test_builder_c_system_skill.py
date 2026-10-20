"""Tests for skills/system — status/volume/clipboard/brightness/windows.

All OS access goes through module-level hooks in the skill, so tests run on
any platform (Linux CI included) with fakes — real OS state is never touched.
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = ROOT / "skills" / "system" / "skill.py"
spec = importlib.util.spec_from_file_location("system_skill", SKILL_PATH)
syskill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(syskill)


class _Ctx:
    def __init__(self):
        self.logs = []

    def log(self, msg):
        self.logs.append(msg)


@pytest.fixture()
def ctx():
    return _Ctx()


@pytest.fixture()
def linux(monkeypatch):
    monkeypatch.setattr(syskill, "_is_windows", lambda: False)


@pytest.fixture()
def windows(monkeypatch):
    monkeypatch.setattr(syskill, "_is_windows", lambda: True)


# --------------------------------------------------------------------------- #
# Manifest sanity
# --------------------------------------------------------------------------- #

def test_manifest_is_valid_and_matches_handlers():
    manifest = json.loads((ROOT / "skills" / "system" / "skill.json")
                          .read_text(encoding="utf-8"))
    from jarvis.skills.registry import SkillManifest
    parsed = SkillManifest.from_dict(manifest, source="system test")
    names = {t.name for t in parsed.tools}
    assert names == {"system_status", "volume_get", "volume_set",
                     "clipboard_get", "clipboard_set", "brightness_get",
                     "brightness_set", "window_list"}
    tiers = {t.name: t.tier for t in parsed.tools}
    assert tiers["system_status"] == 1 and tiers["clipboard_get"] == 1
    assert tiers["volume_set"] == 2 and tiers["clipboard_set"] == 2


def test_unknown_tool_raises(ctx):
    with pytest.raises(ValueError):
        syskill.handle("nope", {}, ctx)


# --------------------------------------------------------------------------- #
# system_status
# --------------------------------------------------------------------------- #

def test_system_status_shape_linux(ctx, linux, monkeypatch):
    monkeypatch.setattr(syskill, "_ram_mb", lambda: (16384, 8192))
    monkeypatch.setattr(syskill, "_battery", lambda: (87, True))
    out = syskill.handle("system_status", {}, ctx)
    assert out["ram_total_mb"] == 16384
    assert out["battery_percent"] == 87
    assert out["battery_charging"] is True
    assert out["cpu_count"] and out["cpu_count"] >= 1


def test_system_status_honest_nulls(ctx, linux, monkeypatch):
    monkeypatch.setattr(syskill, "_ram_mb", lambda: (None, None))
    monkeypatch.setattr(syskill, "_battery", lambda: (None, None))
    out = syskill.handle("system_status", {}, ctx)
    assert out["battery_percent"] is None
    assert "battery not exposed" in out["note"]


def test_ram_mb_linux_reads_proc(ctx, linux):
    total, free = syskill._ram_mb()
    assert total is not None and total > 0
    assert free is not None and 0 <= free <= total


# --------------------------------------------------------------------------- #
# volume
# --------------------------------------------------------------------------- #

def test_volume_get_windows_honest_unavailable(ctx, windows):
    out = syskill.handle("volume_get", {}, ctx)
    assert out["ok"] is False
    assert out["level_percent"] is None
    assert "CoreAudio" in out["reason"]


def test_volume_get_linux_parses_amixer(ctx, linux, monkeypatch):
    class _Proc:
        returncode = 0
        stdout = ("Simple mixer control 'Master',0\n"
                  "  Front Left: Playback 52429 [80%] [on]\n")
        stderr = ""
    monkeypatch.setattr(syskill.shutil, "which",
                        lambda c: "/usr/bin/amixer" if c == "amixer" else None)
    monkeypatch.setattr(syskill, "_run", lambda argv, timeout=4.0: _Proc())
    out = syskill.handle("volume_get", {}, ctx)
    assert out == {"ok": True, "level_percent": 80, "muted": False,
                   "reason": ""}


def test_volume_get_linux_no_amixer(ctx, linux, monkeypatch):
    monkeypatch.setattr(syskill.shutil, "which", lambda c: None)
    out = syskill.handle("volume_get", {}, ctx)
    assert out["ok"] is False and "amixer" in out["reason"]


def test_volume_set_windows_presses_vk_keys(ctx, windows, monkeypatch):
    pressed = []
    monkeypatch.setattr(syskill, "_win_key", pressed.append)
    out = syskill.handle("volume_set", {"direction": "up", "steps": 3}, ctx)
    assert out["ok"] is True
    assert pressed == [syskill.VK_VOLUME_UP] * 3


def test_volume_set_windows_mute_single_press(ctx, windows, monkeypatch):
    pressed = []
    monkeypatch.setattr(syskill, "_win_key", pressed.append)
    out = syskill.handle("volume_set", {"direction": "mute", "steps": 5}, ctx)
    assert out["ok"] is True
    assert pressed == [syskill.VK_VOLUME_MUTE]


def test_volume_set_steps_clamped(ctx, windows, monkeypatch):
    pressed = []
    monkeypatch.setattr(syskill, "_win_key", pressed.append)
    syskill.handle("volume_set", {"direction": "down", "steps": 99}, ctx)
    assert pressed == [syskill.VK_VOLUME_DOWN] * 10  # clamped to the cap


def test_volume_set_linux_no_backend(ctx, linux, monkeypatch):
    monkeypatch.setattr(syskill.shutil, "which", lambda c: None)
    out = syskill.handle("volume_set", {"direction": "up", "steps": 1}, ctx)
    assert out["ok"] is False


# --------------------------------------------------------------------------- #
# clipboard + DCL
# --------------------------------------------------------------------------- #

def test_clipboard_get_plain_text(ctx, monkeypatch):
    monkeypatch.setattr(syskill, "_clipboard_read",
                        lambda: "meeting at 5 tomorrow")
    out = syskill.handle("clipboard_get", {}, ctx)
    assert out["ok"] is True
    assert out["text"] == "meeting at 5 tomorrow"
    assert out["redacted"] is False


def test_clipboard_get_redacts_secret(ctx, monkeypatch):
    fake_secret = "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    monkeypatch.setattr(syskill, "_clipboard_read",
                        lambda: f"my key is {fake_secret} ok")
    out = syskill.handle("clipboard_get", {}, ctx)
    assert out["ok"] is True
    assert fake_secret not in out["text"]
    assert out["redacted"] is True
    assert out["data_class"] == "SECRET"


def test_clipboard_get_no_backend(ctx, monkeypatch):
    monkeypatch.setattr(syskill, "_clipboard_read", lambda: None)
    out = syskill.handle("clipboard_get", {}, ctx)
    assert out["ok"] is False and out["text"] == ""


def test_clipboard_set_ok(ctx, monkeypatch):
    written = []
    monkeypatch.setattr(syskill, "_clipboard_write",
                        lambda t: written.append(t) or True)
    out = syskill.handle("clipboard_set", {"text": "hello"}, ctx)
    assert out["ok"] is True and written == ["hello"]


def test_clipboard_set_refuses_secret(ctx, monkeypatch):
    called = []
    monkeypatch.setattr(syskill, "_clipboard_write",
                        lambda t: called.append(t) or True)
    out = syskill.handle(
        "clipboard_set",
        {"text": "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}, ctx)
    assert out["ok"] is False
    assert "SECRET" in out["reason"]
    assert called == []  # never written


# --------------------------------------------------------------------------- #
# brightness: honest stubs + guard logic
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("tool,args", [
    ("brightness_get", {}),
    ("brightness_set", {"level_percent": 50}),
])
def test_brightness_stubs_are_honest(ctx, tool, args):
    out = syskill.handle(tool, args, ctx)
    assert out["ok"] is False
    assert "not implemented" in out["reason"]


# --------------------------------------------------------------------------- #
# window_list
# --------------------------------------------------------------------------- #

def test_window_list_non_windows_honest(ctx, linux):
    out = syskill.handle("window_list", {}, ctx)
    assert out["ok"] is False and out["windows"] == []


def test_window_list_windows(ctx, windows, monkeypatch):
    monkeypatch.setattr(syskill, "_window_titles_windows",
                        lambda: ["Notepad", "Chrome — example"])
    out = syskill.handle("window_list", {}, ctx)
    assert out["ok"] is True
    assert out["windows"] == ["Notepad", "Chrome — example"]
