from pathlib import Path

from backend import latex_utils


def test_resolve_xelatex_honors_explicit_environment_path(monkeypatch, tmp_path: Path):
    executable = tmp_path / "xelatex.exe"
    executable.write_bytes(b"")
    monkeypatch.setenv("XELATEX_PATH", str(executable))

    assert latex_utils.resolve_xelatex_executable() == str(executable.resolve())


def test_xelatex_install_hint_is_windows_specific(monkeypatch):
    monkeypatch.setattr(latex_utils.os, "name", "nt")

    hint = latex_utils.xelatex_install_hint()

    assert "MiKTeX" in hint
    assert "winget install" in hint
    assert "brew install" not in hint
