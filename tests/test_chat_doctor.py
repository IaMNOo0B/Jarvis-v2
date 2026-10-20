"""Read-only JARVIS doctor diagnostics tests."""

from pathlib import Path
from types import SimpleNamespace

from jarvis.chat import ChatApp


def test_doctor_report_shows_readiness_without_mutating_state(tmp_path):
    (tmp_path / "learned").mkdir()
    (tmp_path / "learned" / "research.md").write_text("source note", encoding="utf-8")

    app = object.__new__(ChatApp)
    app.data_dir = tmp_path
    app._chain = SimpleNamespace(
        providers=[SimpleNamespace(name="ollama"), SimpleNamespace(name="pollinations")],
        last_via="ollama",
    )
    app._ollama_status = "Ollama reachable; configured model available."
    app._pc = object()
    app.memory = object()
    app.registry = SimpleNamespace(_records={
        "notes": SimpleNamespace(approved=True),
        "unknown_skill": SimpleNamespace(approved=False),
    })

    report = app.doctor_report()

    assert "read-only" in report
    assert "ollama, pollinations" in report
    assert "Last response provider: ollama" in report
    assert "Registered skills: 2" in report
    assert "Quarantined skills: 1" in report
    assert "PC control: initialized" in report
    assert "Memory subsystem: available" in report
    assert "Saved research notes: 1" in report
    assert "Data directory writable: yes" in report
    assert (tmp_path / "learned" / "research.md").read_text(encoding="utf-8") == "source note"


def test_doctor_report_is_honest_when_no_provider_or_pc_is_ready(tmp_path):
    app = object.__new__(ChatApp)
    app.data_dir = tmp_path
    app._chain = None
    app._ollama_status = "Connection refused."
    app._pc = None
    app.memory = None
    app.registry = SimpleNamespace(_records={})

    report = app.doctor_report()

    assert "stub (no real provider connected)" in report
    assert "Ollama startup check: Connection refused." in report
    assert "Registered skills: 0" in report
    assert "PC control: not initialized" in report
    assert "Memory subsystem: unavailable" in report
    assert "Saved research notes: 0" in report
