"""Tests for the first-run HIGH fixes (F-11, F-13, F-14, F-16).

Load-bearing properties:
  * brain.omniroute_model is a real schema field (settable, validated,
    overridable) — the "configurable model" claim is honest (F-16)
  * startup_warnings flags a OneDrive-synced data dir, silently passes
    otherwise (F-13)
  * CTX_WINDOW stays within the 2060/6GB VRAM budget (F-14)
"""

import os

import pytest

from jarvis.chat import startup_warnings
from jarvis.config import Config, default_schema
from jarvis import llm_ollama


def _cfg(tmp_path, **kw):
    return Config(str(tmp_path / "jarvis.json"), default_schema(), **kw)


# -- F-16: omniroute_model is schema-backed ------------------------------------


def test_omniroute_model_in_schema_defaults(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.load()
    assert cfg.get("brain.omniroute_model") == "google/gemini-2.5-flash"


def test_omniroute_model_settable_and_validated(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.load()
    cfg.set("brain.omniroute_model", "openai/gpt-4o-mini")
    assert cfg.get("brain.omniroute_model") == "openai/gpt-4o-mini"
    with pytest.raises(Exception):
        cfg.set("brain.omniroute_model", 123)  # wrong type rejected loudly


# -- F-13: OneDrive warning ----------------------------------------------------


def test_no_warning_outside_onedrive(tmp_path, monkeypatch):
    monkeypatch.delenv("OneDrive", raising=False)
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    assert startup_warnings(tmp_path / "data") == []


def test_warns_inside_onedrive(tmp_path, monkeypatch):
    od = tmp_path / "OneDrive"
    data = od / "Documents" / "GitHub" / "Jarvis-v2" / "data"
    monkeypatch.setenv("OneDrive", str(od))
    warnings = startup_warnings(data)
    assert len(warnings) == 1
    assert "OneDrive" in warnings[0] and "SQLite" in warnings[0]


# -- F-14: VRAM budget ----------------------------------------------------------


def test_ctx_window_within_2060_budget():
    # 4.7GB weights + KV + Win11 display reservation must stay under 6GB.
    # KV ≈ 0.13MB/token/layer-ish; 2048 keeps total ≈ 5.4GB. 4096 was
    # borderline and caused silent CPU partial-offload.
    assert llm_ollama.CTX_WINDOW <= 2048
