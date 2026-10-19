"""Tests for the Data Classification Layer (DCL).

The 6 exfiltration scenarios from the SEC12 spec, plus registry, redaction,
fail-closed, and feed-entry tests. ALL MUST PASS -- no exceptions.
"""

import base64
import os
import tempfile

import pytest

from jarvis.dcl import (
    DCL,
    DataClass,
    Finding,
    SecretRegistry,
    classify,
    feed_entry,
    load_registry,
    redact,
    register_secret,
)


# ---------------------------------------------------------------------------
# The 6 exfiltration scenarios from the spec
# ---------------------------------------------------------------------------

def test_1_raw_key_is_secret():
    dcl = DCL()
    cls, findings = dcl.classify("deploy with ghp_" + "a" * 36 + " now")
    assert cls == DataClass.SECRET
    assert any(f.pattern == "github-token" and f.tier == "B" for f in findings)


def test_2_base64_encoded_key_is_caught():
    dcl = DCL()
    raw = "sk-" + "b" * 32
    enc = base64.b64encode(raw.encode()).decode()
    cls, findings = dcl.classify(f"config blob: {enc}")
    assert cls == DataClass.SECRET
    assert any("encoded-b64" in f.pattern for f in findings)


def test_3_double_encoded_key_is_caught():
    dcl = DCL()
    raw = "AKIA" + "C" * 16
    once = base64.b64encode(raw.encode()).decode()
    twice = base64.b64encode(once.encode()).decode()
    cls, findings = dcl.classify(f"nested data {twice} end")
    assert cls == DataClass.SECRET
    assert any("L2" in f.pattern for f in findings)


def test_4_key_in_tool_output_is_secret():
    dcl = DCL()
    wrapped = ('<tool_output source="file_reader" trust="untrusted">'
               "api_key=" + "x" * 40 + "</tool_output>")
    cls, _ = dcl.classify(wrapped)
    assert cls == DataClass.SECRET


def test_5_pii_in_prompt():
    dcl = DCL()
    cls, findings = dcl.classify(
        "email me at owais@example.com or call +91 98765 43210")
    # phone escalates the composite to SENSITIVE
    assert cls == DataClass.SENSITIVE
    assert any(f.pattern == "email" and f.data_class == DataClass.PERSONAL
               for f in findings)
    assert any(f.pattern == "phone-in" for f in findings)


def test_6_clean_text_is_public():
    dcl = DCL()
    cls, findings = dcl.classify("what's the weather like today?")
    assert cls == DataClass.PUBLIC
    assert findings == []


# ---------------------------------------------------------------------------
# Tier A -- the registry: the system's own secrets, zero false positives
# ---------------------------------------------------------------------------

def test_registered_secret_always_secret():
    dcl = DCL()
    secret = "AIza" + "x" * 35
    dcl.register_secret("gemini-key", secret)
    cls, findings = dcl.classify(f"some text {secret} more text")
    assert cls == DataClass.SECRET
    assert any(f.tier == "A" and f.data_class == DataClass.SECRET
               for f in findings)


def test_registry_value_never_stored():
    reg = SecretRegistry()
    reg.register_secret("k", "supersecretvalue123")
    # The raw value must not appear anywhere in the registry's state.
    state = repr(reg._entries) + reg._salt.hex()
    assert "supersecretvalue123" not in state


def test_registry_persists_without_values(tmp_path):
    reg = SecretRegistry()
    reg.register_secret("k", "anothersecret456")
    path = str(tmp_path / "registry.json")
    reg.save(path)
    raw = open(path, encoding="utf-8").read()
    assert "anothersecret456" not in raw
    reg2 = load_registry(path)
    cls, findings = DCL(registry=reg2).classify("leak anothersecret456 here")
    assert cls == DataClass.SECRET
    assert any(f.tier == "A" for f in findings)


# ---------------------------------------------------------------------------
# Tier B -- more pattern coverage
# ---------------------------------------------------------------------------

def test_telegram_token_is_secret():
    dcl = DCL()
    cls, _ = dcl.classify("bot token 1234567890:" + "A" * 35)
    assert cls == DataClass.SECRET


def test_private_key_block_is_secret():
    dcl = DCL()
    cls, _ = dcl.classify("-----BEGIN RSA PRIVATE KEY-----\nMIIE...")
    assert cls == DataClass.SECRET


def test_luhn_card_is_secret():
    dcl = DCL()
    cls, findings = dcl.classify("card 4111111111111111 charged")
    assert cls == DataClass.SECRET
    assert any(f.pattern == "card-number-luhn" for f in findings)


def test_non_luhn_number_not_card():
    dcl = DCL()
    cls, findings = dcl.classify("order 4111111111111112 shipped")
    assert not any(f.pattern == "card-number-luhn" for f in findings)


def test_otp_with_context_is_secret():
    dcl = DCL()
    cls, _ = dcl.classify("your OTP code is 482913, valid 5 min")
    assert cls == DataClass.SECRET


def test_url_encoded_key_is_caught():
    dcl = DCL()
    # Fully percent-encoded token: "%67%68%70%5F" == "ghp_", "%7A" == "z".
    enc = "%67%68%70%5F" + "%7A" * 36
    cls, findings = dcl.classify(f"param={enc}")
    assert cls == DataClass.SECRET
    assert any("encoded-url" in f.pattern for f in findings)


def test_seed_phrase_shape_is_secret():
    dcl = DCL()
    phrase = ("abandon " * 11 + "about").strip()
    cls, findings = dcl.classify(f"recovery: {phrase}")
    assert cls == DataClass.SECRET
    assert any(f.pattern == "seed-phrase-12" for f in findings)


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

def test_redact_removes_secret_value():
    dcl = DCL()
    raw = "leaked ghp_" + "a" * 36 + " end"
    red, _ = dcl.redact(raw)
    assert "ghp_" not in red
    assert "[REDACTED:SECRET]" in red
    assert red.startswith("leaked ") and red.endswith(" end")


def test_redact_encoded_blob_removes_whole_blob():
    dcl = DCL()
    raw = "sk-" + "b" * 32
    enc = base64.b64encode(raw.encode()).decode()
    text = f"blob {enc} done"
    red, _ = dcl.redact(text)
    assert enc not in red          # the whole blob is gone...
    assert raw not in red          # ...and the decoded value never appears
    assert "[REDACTED:SECRET]" in red


def test_redact_sensitive_uses_sensitive_placeholder():
    dcl = DCL()
    red, _ = dcl.redact("call +91 98765 43210 today")
    assert "[REDACTED:SENSITIVE]" in red
    assert "98765" not in red


def test_redact_leaves_personal_and_public():
    dcl = DCL()
    text = "write to owais@example.com about the weather"
    red, _ = dcl.redact(text)
    assert red == text  # PERSONAL/PUBLIC pass through


# ---------------------------------------------------------------------------
# Fail-closed
# ---------------------------------------------------------------------------

def test_fail_closed_on_non_string():
    dcl = DCL()
    cls, findings = dcl.classify(None)  # type: ignore[arg-type]
    assert cls == DataClass.SENSITIVE
    assert findings and findings[0].tier == "ERR"


def test_fail_closed_never_public_on_error(monkeypatch):
    dcl = DCL()
    monkeypatch.setattr(dcl, "_tier_b",
                        lambda text, depth: (_ for _ in ()).throw(RuntimeError("boom")))
    cls, _ = dcl.classify("perfectly innocent text")
    assert cls == DataClass.SENSITIVE


# ---------------------------------------------------------------------------
# Feed entry -- metadata only, never content
# ---------------------------------------------------------------------------

def test_feed_entry_metadata_only():
    secret = "ghp_" + "q" * 36
    entries = feed_entry("gemini-cloud", [
        {"data_class": DataClass.SECRET, "source": "clipboard",
         "byte_count": 40, "action": "withheld"},
        {"data_class": DataClass.PERSONAL, "source": "chat",
         "byte_count": 120, "action": "sent"},
    ])
    assert len(entries) == 2
    assert entries[0]["class"] == "SECRET"
    assert entries[0]["action"] == "withheld"
    assert entries[0]["destination"] == "gemini-cloud"
    assert "ts" in entries[0]
    # The secret value must not appear anywhere in the metadata.
    assert secret not in str(entries)


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------

def test_module_level_api():
    cls, _ = classify("hello world")
    assert cls == DataClass.PUBLIC
    red, _ = redact("key " + "AKIA" + "D" * 16)
    assert "[REDACTED:SECRET]" in red
    register_secret("mod-test", "zzzsecret999")
    cls2, f2 = classify("contains zzzsecret999 inside")
    assert cls2 == DataClass.SECRET
    assert any(f.tier == "A" for f in f2)


def test_composite_takes_max_class():
    dcl = DCL()
    cls, _ = dcl.classify(
        "hi owais@example.com, your password=hunter2x!")
    assert cls == DataClass.SECRET  # labeled secret beats PERSONAL email
