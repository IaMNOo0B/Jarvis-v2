"""Tests for Builder C additions to jarvis/pc_control.py:

- AppRegistry (learned SQLite name->path map)
- launch_app ladder (registry -> Start Menu -> PATH)
- find_text_on_screen OCR fallback (parse/score + injection-safety guard)
"""

import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import jarvis.pc_control as pc
from jarvis.pc_control import (
    ActionFailedError,
    AppRegistry,
    FakeUiaBackend,
    PCController,
    match_ocr_text,
    parse_ocr_lines,
)


@pytest.fixture()
def controller(tmp_path):
    return PCController(backend=FakeUiaBackend(), data_dir=tmp_path)


@pytest.fixture()
def launched(monkeypatch):
    calls = []
    monkeypatch.setattr(pc, "_launch_target", calls.append)
    return calls


# --------------------------------------------------------------------------- #
# AppRegistry
# --------------------------------------------------------------------------- #

class TestAppRegistry:
    def test_learn_and_lookup_normalizes(self, tmp_path):
        reg = AppRegistry(tmp_path / "apps.db")
        reg.learn("  Chrome ", "C:/chrome.exe")
        assert reg.lookup("chrome") == "C:/chrome.exe"
        assert reg.lookup("CHROME") == "C:/chrome.exe"

    def test_lookup_miss(self, tmp_path):
        reg = AppRegistry(tmp_path / "apps.db")
        assert reg.lookup("nothing") is None

    def test_learn_counts_launches_and_updates_path(self, tmp_path):
        reg = AppRegistry(tmp_path / "apps.db")
        reg.learn("code", "C:/old.exe")
        reg.learn("code", "C:/new.exe")
        rows = reg.all()
        assert rows == [{"name": "code", "path": "C:/new.exe",
                         "launches": 2}]

    def test_persists_across_instances(self, tmp_path):
        AppRegistry(tmp_path / "apps.db").learn("notes", "/usr/bin/notes")
        reg2 = AppRegistry(tmp_path / "apps.db")
        assert reg2.lookup("notes") == "/usr/bin/notes"

    def test_forget(self, tmp_path):
        reg = AppRegistry(tmp_path / "apps.db")
        reg.learn("x", "/bin/x")
        assert reg.forget("x") is True
        assert reg.lookup("x") is None
        assert reg.forget("x") is False

    def test_memory_db(self):
        reg = AppRegistry(":memory:")
        reg.learn("y", "/bin/y")
        assert reg.lookup("y") == "/bin/y"


# --------------------------------------------------------------------------- #
# launch_app ladder
# --------------------------------------------------------------------------- #

class TestLaunchLadder:
    def test_empty_name_refused(self, controller, launched):
        with pytest.raises(ActionFailedError):
            controller.launch_app("   ")
        assert launched == []

    def test_rung1_registry_hit(self, controller, launched, tmp_path):
        exe = tmp_path / "chrome.exe"
        exe.write_bytes(b"")
        controller.app_registry.learn("chrome", str(exe))
        out = controller.launch_app("Chrome")
        assert out["ok"] is True and out["via"] == "registry"
        assert launched == [str(exe)]

    def test_rung1_stale_path_falls_through(self, controller, launched,
                                           monkeypatch, tmp_path):
        controller.app_registry.learn("gone", str(tmp_path / "missing.exe"))
        monkeypatch.setattr(pc, "_start_menu_dirs", lambda: [])
        monkeypatch.setattr(pc.shutil, "which", lambda n: None)
        with pytest.raises(ActionFailedError):
            controller.launch_app("gone")
        assert launched == []

    def test_rung2_start_menu_and_learns(self, controller, launched,
                                         monkeypatch, tmp_path):
        sm = tmp_path / "StartMenu"
        (sm / "Apps").mkdir(parents=True)
        lnk = sm / "Apps" / "My Editor.lnk"
        lnk.write_bytes(b"")
        monkeypatch.setattr(pc, "_start_menu_dirs", lambda: [sm])
        out = controller.launch_app("my editor")
        assert out["via"] == "start_menu"
        assert launched == [str(lnk)]
        # Learned: next launch takes rung 1.
        assert controller.app_registry.lookup("my editor") == str(lnk)

    def test_rung2_exact_beats_partial(self, controller, launched,
                                      monkeypatch, tmp_path):
        sm = tmp_path / "SM"
        sm.mkdir()
        (sm / "Editor Plus.lnk").write_bytes(b"")
        (sm / "Editor.lnk").write_bytes(b"")
        monkeypatch.setattr(pc, "_start_menu_dirs", lambda: [sm])
        controller.launch_app("editor")
        assert launched == [str(sm / "Editor.lnk")]

    def test_rung3_path_lookup(self, controller, launched, monkeypatch):
        monkeypatch.setattr(pc, "_start_menu_dirs", lambda: [])
        monkeypatch.setattr(pc.shutil, "which", lambda n: "/usr/bin/mycmd")
        out = controller.launch_app("mycmd")
        assert out["via"] == "path"
        assert launched == ["/usr/bin/mycmd"]

    def test_all_rungs_miss_raises_honestly(self, controller, launched,
                                            monkeypatch):
        monkeypatch.setattr(pc, "_start_menu_dirs", lambda: [])
        monkeypatch.setattr(pc.shutil, "which", lambda n: None)
        with pytest.raises(ActionFailedError, match="could not find"):
            controller.launch_app("definitely-not-an-app")
        assert launched == []

    def test_no_registry_still_launches_via_path(self, monkeypatch, launched):
        plain = PCController(backend=FakeUiaBackend())
        assert plain.app_registry is None
        monkeypatch.setattr(pc.shutil, "which", lambda n: "/bin/thing")
        out = plain.launch_app("thing")
        assert out["ok"] is True and out["via"] == "path"


# --------------------------------------------------------------------------- #
# OCR parsing + matching (pure logic)
# --------------------------------------------------------------------------- #

class TestOcrParsing:
    def test_parse_lines(self):
        entries = parse_ocr_lines(["File | 10,20", "garbage line",
                                   "Save As | 300, 45"])
        assert entries == [{"text": "File", "x": 10, "y": 20},
                           {"text": "Save As", "x": 300, "y": 45}]

    def test_parse_keeps_pipe_in_text(self):
        entries = parse_ocr_lines(["a | b | 5,6"])
        assert entries == [{"text": "a | b", "x": 5, "y": 6}]

    def test_match_exact_substring_wins(self):
        entries = [{"text": "Click the Submit button now", "x": 1, "y": 2},
                   {"text": "Submit", "x": 3, "y": 4}]
        hits = match_ocr_text(entries, "submit")
        assert hits[0]["text"] == "Click the Submit button now"
        assert hits[0]["score"] == 1.0

    def test_match_word_overlap(self):
        entries = [{"text": "Open recent files", "x": 1, "y": 1},
                   {"text": "Settings", "x": 2, "y": 2}]
        hits = match_ocr_text(entries, "open files")
        assert len(hits) == 1 and hits[0]["score"] == 1.0

    def test_match_partial_overlap_kept(self):
        entries = [{"text": "save document as pdf", "x": 1, "y": 1}]
        hits = match_ocr_text(entries, "save image")  # 1 of 2 words
        assert len(hits) == 1 and hits[0]["score"] == 0.5

    def test_match_below_threshold_dropped(self):
        entries = [{"text": "totally different", "x": 1, "y": 1}]
        assert match_ocr_text(entries, "submit") == []

    def test_match_empty_query(self):
        assert match_ocr_text([{"text": "x", "x": 0, "y": 0}], "  ") == []


# --------------------------------------------------------------------------- #
# find_text_on_screen
# --------------------------------------------------------------------------- #

CANNED = ["Welcome back | 400,300", "Press Start to play | 512,640",
          "Settings | 900,80"]


class TestFindText:
    def test_non_windows_honest_unavailable(self, controller):
        out = controller.find_text_on_screen("Start")
        assert out["ok"] is False and out["available"] is False
        assert "Windows" in out["reason"]

    def test_empty_query_refused(self, controller, monkeypatch):
        monkeypatch.setattr(pc, "_is_windows", lambda: True)
        with pytest.raises(ActionFailedError):
            controller.find_text_on_screen("   ")

    def test_windows_path_with_canned_ocr(self, controller, monkeypatch):
        monkeypatch.setattr(pc, "_is_windows", lambda: True)
        seen = {}
        def fake_ocr(path):
            seen["path"] = path
            return CANNED
        monkeypatch.setattr(pc, "_run_powershell_ocr", fake_ocr)
        out = controller.find_text_on_screen("press start")
        assert out["ok"] is True and out["found"] is True
        assert out["best"]["x"] == 512 and out["best"]["y"] == 640
        assert out["lines_seen"] == 3
        # The temp PNG was deleted after use (no screen data left on disk).
        assert not Path(seen["path"]).exists()

    def test_windows_no_match(self, controller, monkeypatch):
        monkeypatch.setattr(pc, "_is_windows", lambda: True)
        monkeypatch.setattr(pc, "_run_powershell_ocr", lambda p: CANNED)
        out = controller.find_text_on_screen("nonexistent label")
        assert out["ok"] is True and out["found"] is False
        assert out["best"] is None

    def test_ocr_engine_unavailable(self, controller, monkeypatch):
        monkeypatch.setattr(pc, "_is_windows", lambda: True)
        monkeypatch.setattr(pc, "_run_powershell_ocr",
                            lambda p: ["OCR_UNAVAILABLE"])
        out = controller.find_text_on_screen("anything")
        assert out["ok"] is False and out["available"] is False

    def test_search_text_never_enters_script(self, controller, monkeypatch):
        """Injection guard: the secret query must appear ONLY as data —
        the PowerShell body is fixed; the OCR helper receives just a path,
        and the query is matched locally in Python."""
        captured = {}

        class _Proc:
            returncode = 0
            stdout = "Hello | 1,2"
            stderr = ""

        monkeypatch.setattr(pc, "_is_windows", lambda: True)

        def fake_run(argv, **kw):
            captured["argv"] = argv
            return _Proc()
        monkeypatch.setattr(pc.subprocess, "run", fake_run)
        secret_query = "'; rm -rf /; '"
        out = controller.find_text_on_screen(secret_query)
        argv = captured["argv"]
        assert argv[0] == "powershell"
        enc_idx = argv.index("-EncodedCommand") + 1
        script_text = base64.b64decode(argv[enc_idx]).decode("utf-16-le")
        assert script_text == pc._OCR_SCRIPT  # body unchanged, query-free
        assert secret_query not in " ".join(argv)
        assert out["ok"] is True  # harmless local miss, no code ran


# --------------------------------------------------------------------------- #
# Gate definitions
# --------------------------------------------------------------------------- #

def test_new_tools_registered_with_right_tiers():
    defs = {t["name"]: t for t in pc.tool_definitions()}
    assert defs["pc.launch_app"]["tier"] == 2
    assert defs["pc.find_text"]["tier"] == 1
    reg = pc.as_gate_registry()
    assert reg["pc.launch_app"]["capabilities"] == ["ui.control"]
    assert reg["pc.find_text"]["capabilities"] == ["ui.read"]
