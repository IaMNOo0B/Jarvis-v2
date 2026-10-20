"""Architecture tests — the seed-viability study's enforcement layer.

seed-viability.md §3: "A decision you cannot verify is just a wish."
JARVIS's DNA includes two mechanically checkable boundaries:

1. **Core never imports the UI.** The pipeline core (brain, memory,
   gate, dcl, session store, config, rules, skills, maintenance,
   setup) must not import a GUI toolkit or the chat GUI module —
   dependency direction points inward; UI lives at the edge
   (jarvis/chat_gui.py is the only UI module).

2. **Stdlib-only core (local-first).** Core modules import only the
   standard library plus jarvis itself, with two recorded exceptions:
   `keyring` (config.py's OS-keychain backend — the soil's mandated
   secret store) and `winreg` (setup.py's guarded Windows probe).
   A core module that cannot be imported offline cannot honor
   "cloud is a fallback, never a hard dependency."

These tests read source via AST — they verify the boundary itself, not
a runtime accident of what happens to be installed.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CORE_MODULES = [
    "jarvis/brain.py",
    "jarvis/memory.py",
    "jarvis/gate.py",
    "jarvis/dcl.py",
    "jarvis/session_store.py",
    "jarvis/config.py",
    "jarvis/rules.py",
    "jarvis/maintenance.py",
    "jarvis/setup.py",
    "jarvis/skills/registry.py",
]

UI_ROOTS = {"tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6"}
ALLOWED_NON_STDLIB = {"keyring", "winreg"}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_core_modules_exist():
    for rel in CORE_MODULES:
        assert (ROOT / rel).exists(), f"missing core module {rel}"


def test_core_never_imports_ui_toolkit():
    for rel in CORE_MODULES:
        roots = _imported_roots(ROOT / rel)
        bad = roots & UI_ROOTS
        assert not bad, f"{rel} imports UI toolkit(s): {sorted(bad)}"


def test_core_never_imports_chat_gui():
    for rel in CORE_MODULES:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "chat_gui" not in node.module, \
                    f"{rel} imports the chat GUI — direction violation"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "chat_gui" not in alias.name


def test_core_imports_are_stdlib_only():
    stdlib = set(sys.stdlib_module_names) | {"jarvis"} | ALLOWED_NON_STDLIB
    for rel in CORE_MODULES:
        roots = _imported_roots(ROOT / rel)
        foreign = {r for r in roots if r not in stdlib
                   and not r.startswith("_")}
        assert not foreign, \
            f"{rel} imports non-stdlib module(s): {sorted(foreign)}"
