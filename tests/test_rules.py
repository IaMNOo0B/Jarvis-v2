"""Tests for jarvis.rules — the central rules loader.

P0 integrity is the load-bearing property: a missing or empty hard-safety
rule must refuse startup, loudly. Never a silent pass.
"""

import os
import shutil

import pytest

from jarvis.rules import P0_REQUIRED, RulesError, load_rules

REAL_RULES = os.path.expanduser("~/workspace/jarvis-knowledge/JARVIS-RULES.txt")

MINIMAL_P0 = """\
P0-1  [CONFIG] First hard rule.
P0-2  [CONFIG] Second hard rule.
P0-3  [CONFIG] Third hard rule.
P0-4  [CONFIG] Fourth hard rule.
P0-5  [CONFIG] Fifth hard rule.
P0-6  [CONFIG] Sixth hard rule.
P0-7  [CONFIG] Seventh hard rule.
"""


def _write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return str(path)


# -- the real file ----------------------------------------------------------

def test_real_file_parses():
    rules = load_rules(REAL_RULES)
    # P0:7 + P1:14 + P2:10 + P3:7 + R:4 = 42
    assert len(rules) == 42
    assert len(rules.get("P0")) == 7
    assert len(rules.get("P1")) == 14
    assert len(rules.get("P2")) == 10
    assert len(rules.get("P3")) == 7
    assert len(rules.get("R")) == 4


def test_real_file_spot_checks():
    rules = load_rules(REAL_RULES)
    r = rules.find("P0-3")
    assert r is not None
    assert r.kind == "STRUCTURAL"
    assert "Secrets never leave" in r.text
    # multi-line rule bodies are joined, not truncated
    r = rules.find("P2-4")
    assert "call-ringing" in r.text and "Urgent" in r.text
    assert rules.find("NOPE") is None
    assert "P0-1" in rules


def test_p0_required_ids_match_file():
    rules = load_rules(REAL_RULES)
    for rid in P0_REQUIRED:
        assert rid in rules, f"canonical P0 id {rid} not in real file"


# -- P0 integrity: refuse startup -------------------------------------------

def _remove_rule_block(text: str, rule_id: str) -> str:
    """Remove a rule and its indented continuation lines."""
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        if line.startswith(rule_id + " ") or line.startswith(rule_id + "\t"):
            skipping = True
            continue
        if skipping and (line.startswith(" ") or line.startswith("\t")
                         or not line.strip()):
            if not line.strip():
                skipping = False  # blank line ends the block
            continue
        skipping = False
        out.append(line)
    return "".join(out)


def test_missing_p0_rule_refuses_start(tmp_path):
    src = _write(tmp_path / "rules.txt", MINIMAL_P0)
    text = open(src, encoding="utf-8").read()
    _write(tmp_path / "broken.txt", _remove_rule_block(text, "P0-4"))
    with pytest.raises(RulesError, match="hard-safety rule missing"):
        load_rules(str(tmp_path / "broken.txt"))


def test_missing_p0_in_real_file_refuses_start(tmp_path):
    shutil.copy(REAL_RULES, tmp_path / "rules.txt")
    text = open(tmp_path / "rules.txt", encoding="utf-8").read()
    _write(tmp_path / "rules.txt", _remove_rule_block(text, "P0-1"))
    with pytest.raises(RulesError, match="P0-1"):
        load_rules(str(tmp_path / "rules.txt"))


def test_empty_p0_text_refuses_start(tmp_path):
    text = MINIMAL_P0.replace("P0-5  [CONFIG] Fifth hard rule.",
                              "P0-5  [CONFIG]")
    _write(tmp_path / "rules.txt", text)
    with pytest.raises(RulesError, match="hard-safety rule missing"):
        load_rules(str(tmp_path / "rules.txt"))


def test_empty_file_refuses_start(tmp_path):
    _write(tmp_path / "rules.txt", "# nothing here\n")
    with pytest.raises(RulesError):
        load_rules(str(tmp_path / "rules.txt"))


def test_unreadable_path_refuses_start(tmp_path):
    with pytest.raises(RulesError, match="cannot read"):
        load_rules(str(tmp_path / "does-not-exist.txt"))


def test_explicit_override_permits_confirmed_missing(tmp_path):
    """The owner's live confirmation path: exact ids, explicit, named."""
    text = _remove_rule_block(MINIMAL_P0, "P0-7")
    _write(tmp_path / "rules.txt", text)
    rules = load_rules(str(tmp_path / "rules.txt"), allow_missing={"P0-7"})
    assert len(rules.get("P0")) == 6
    # ...but anything NOT explicitly allowed still refuses
    with pytest.raises(RulesError):
        load_rules(str(tmp_path / "rules.txt"), allow_missing={"P0-6"})


def test_added_p0_rule_held_to_same_bar(tmp_path):
    text = MINIMAL_P0 + "P0-8  [CONFIG]\n"
    _write(tmp_path / "rules.txt", text)
    with pytest.raises(RulesError, match="P0-8"):
        load_rules(str(tmp_path / "rules.txt"))


# -- reload ------------------------------------------------------------------

def test_reload_detects_changes(tmp_path):
    _write(tmp_path / "rules.txt", MINIMAL_P0)
    rules = load_rules(str(tmp_path / "rules.txt"))

    changed = MINIMAL_P0.replace(
        "P0-2  [CONFIG] Second hard rule.",
        "P0-2  [CONFIG] Second hard rule, edited.")
    changed += "P3-9  [CONFIG] A brand new preference.\n"
    _write(tmp_path / "rules.txt", changed)

    diff = rules.reload()
    assert diff["changed"] == ["P0-2"]
    assert diff["added"] == ["P3-9"]
    assert diff["removed"] == []
    assert rules.find("P0-2").text.endswith("edited.")


def test_reload_detects_removal(tmp_path):
    _write(tmp_path / "rules.txt", MINIMAL_P0)
    rules = load_rules(str(tmp_path / "rules.txt"))
    # P0-1 removed WITHOUT confirmation -> reload must refuse too
    _write(tmp_path / "rules.txt", _remove_rule_block(MINIMAL_P0, "P0-1"))
    with pytest.raises(RulesError, match="hard-safety rule missing"):
        rules.reload()
    # ...with confirmation, the removal is honoured and reported
    rules2 = load_rules(str(tmp_path / "rules.txt"), allow_missing={"P0-1"})
    diff = rules2.reload()
    assert diff["removed"] == []


def test_reload_no_changes(tmp_path):
    _write(tmp_path / "rules.txt", MINIMAL_P0)
    rules = load_rules(str(tmp_path / "rules.txt"))
    assert rules.reload() == {"added": [], "removed": [], "changed": []}
