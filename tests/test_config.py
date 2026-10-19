"""Tests for jarvis.config — crash-safe config + redacted secrets.

Load-bearing properties:
  * corrupt file -> quarantined aside + ConfigError raised (never wiped)
  * bad values -> defaults + error report (the v1 C-B4 fix, incl. the
    telegram.allowed_user_ids "" -> [] regression)
  * secret values NEVER appear in logs or reprs
"""

import glob
import json
import logging
import os

import pytest

from jarvis.config import (Config, ConfigError, Secrets, default_schema,
                           redact_for_log)


def _cfg(tmp_path, **kw):
    return Config(str(tmp_path / "jarvis.json"), default_schema(), **kw)


# -- round trip / atomicity ---------------------------------------------------

def test_round_trip(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.load()
    cfg.set("voice.engine", "fish")
    cfg.set("brain.temperature", 0.3)
    cfg.save()

    cfg2 = _cfg(tmp_path)
    cfg2.load()
    assert cfg2.get("voice.engine") == "fish"
    assert cfg2.get("brain.temperature") == 0.3
    # untouched defaults survive
    assert cfg2.get("telegram.allowed_user_ids") == []


def test_save_is_always_valid_json(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.load()
    cfg.set("safety.watching_eyes", True)
    cfg.save()
    with open(tmp_path / "jarvis.json", "rb") as fh:
        json.loads(fh.read())  # raises if half-written
    assert not glob.glob(str(tmp_path / ".jarvis.json.tmp-*"))


def test_missing_file_loads_defaults(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.load()  # no file yet: not an error
    assert cfg.errors == []
    assert cfg.get("voice.engine") == "piper"


def test_overrides_win_without_persisting(tmp_path):
    cfg = _cfg(tmp_path, overrides={"voice": {"engine": "elevenlabs"}})
    cfg.load()
    assert cfg.get("voice.engine") == "elevenlabs"
    cfg.save()
    cfg2 = _cfg(tmp_path)
    cfg2.load()
    assert cfg2.get("voice.engine") == "piper"  # override was not persisted


# -- corruption: quarantine + raise, never wipe --------------------------------

def test_corrupt_file_quarantined_and_raises(tmp_path):
    path = tmp_path / "jarvis.json"
    garbage = b"\x00\xff not json {{{"
    path.write_bytes(garbage)
    cfg = _cfg(tmp_path)
    with pytest.raises(ConfigError, match="corrupt"):
        cfg.load()
    quarantined = glob.glob(str(tmp_path / "jarvis.json.corrupt-*"))
    assert len(quarantined) == 1
    assert open(quarantined[0], "rb").read() == garbage  # bytes preserved


def test_non_object_json_quarantined_and_raises(tmp_path):
    (tmp_path / "jarvis.json").write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ConfigError, match="not an object"):
        _cfg(tmp_path).load()


# -- validation: the C-B4 regression ------------------------------------------

def test_bad_value_keeps_default_and_reports(tmp_path):
    # v1's Settings panel rewrote telegram.allowed_user_ids [] -> "" on OK.
    (tmp_path / "jarvis.json").write_text(
        json.dumps({"telegram": {"allowed_user_ids": ""}}), encoding="utf-8")
    cfg = _cfg(tmp_path)
    cfg.load()  # must not raise: bad *values* are reported, not fatal
    assert cfg.get("telegram.allowed_user_ids") == []
    assert any("allowed_user_ids" in str(e) for e in cfg.errors)


def test_set_rejects_invalid_loudly(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.load()
    with pytest.raises(ValueError):
        cfg.set("voice.engine", "not-a-real-engine")
    with pytest.raises(KeyError):
        cfg.set("voice.nonexistent", 1)
    # bool is not int and int is not bool (the isinstance(True, int) trap)
    with pytest.raises(ValueError):
        cfg.set("safety.watching_eyes", 1)


# -- secrets -------------------------------------------------------------------

def test_secrets_env_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_GEMINI_API_KEY", "sekret-123")
    # ensure no keyring interferes with the fallback path
    import jarvis.config as config_mod
    s = Secrets()
    s._keyring = None
    assert s.get("gemini_api_key") == "sekret-123"
    assert s.get("missing_key") is None
    assert s.get("missing_key", "dflt") == "dflt"


def test_secrets_repr_redacted(monkeypatch):
    monkeypatch.setenv("JARVIS_FISH_API_KEY", "sekret-456")
    s = Secrets()
    s._keyring = None
    assert "sekret-456" not in repr(s)
    assert "<redacted>" in repr(s)


def test_secrets_never_in_logs(tmp_path, caplog, monkeypatch):
    monkeypatch.setenv("JARVIS_TELEGRAM_BOT_TOKEN", "sekret-789")
    s = Secrets()
    s._keyring = None
    cfg = _cfg(tmp_path, secrets=s)
    cfg.load()
    logger = logging.getLogger("jarvis.config")
    with caplog.at_level(logging.INFO, logger="jarvis.config"):
        # even a careless full-export log must go through redaction
        logger.info("config dump: %s", cfg.export_redacted())
        logger.info("secrets obj: %r", s)
    assert "sekret-789" not in caplog.text


def test_redact_for_log_nested():
    blob = {
        "telegram": {"bot_token": "sekret-1", "enabled": True},
        "nested": [{"api_key": "sekret-2"}, {"other": "fine"}],
        "password": "sekret-3",
        "plain": "visible",
    }
    red = redact_for_log(blob)
    assert red["telegram"]["bot_token"] == "***"
    assert red["telegram"]["enabled"] is True
    assert red["nested"][0]["api_key"] == "***"
    assert red["nested"][1]["other"] == "fine"
    assert red["password"] == "***"
    assert red["plain"] == "visible"
    # original untouched
    assert blob["telegram"]["bot_token"] == "sekret-1"


def test_redact_uses_secret_registry():
    assert redact_for_log({"gemini_api_key": "x"}) == {"gemini_api_key": "***"}


def test_secrets_set_without_keyring_raises(monkeypatch):
    s = Secrets()
    s._keyring = None
    with pytest.raises(ConfigError, match="no secret storage available"):
        s.set("gemini_api_key", "whatever")
