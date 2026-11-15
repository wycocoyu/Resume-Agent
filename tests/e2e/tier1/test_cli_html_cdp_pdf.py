"""Tier 1 Feature Coverage: Feature 12 (CLI HTML Rendering & CDP PDF Export, Issue #47).

Authoritative specs:
- ORIGINAL_REQUEST §R3.2, Issue #47
- backend/cli/render_cmd.py
- Headless Chrome CDP discovery and CLI render command contract
"""
from __future__ import annotations

import os
from pathlib import Path
import pytest


def test_t1_f12_01_cli_render_help(run_cli):
    """TEST-T1-F12-01: Verify 'render --help' displays required options."""
    proc = run_cli(["render", "--help"])
    assert proc.returncode == 0
    stdout = proc.stdout
    assert "-o" in stdout or "--output" in stdout
    assert "--force" in stdout
    assert "--json" in stdout
    assert "--template" in stdout
    assert "--engine" in stdout
    assert "print-background" in stdout


def test_t1_f12_02_cli_render_standard_pdf(run_cli, fixtures_dir: Path, temp_e2e_dir: Path):
    """TEST-T1-F12-02: Verify CLI renders standard_resume.json to valid PDF file."""
    input_json = fixtures_dir / "standard_resume.json"
    output_pdf = temp_e2e_dir / "standard_output.pdf"

    proc = run_cli(["render", str(input_json), "-o", str(output_pdf), "--json"])
    assert proc.returncode == 0, f"Render failed: {proc.stderr}"
    assert proc.json_data is not None
    assert proc.json_data.get("ok") is True
    assert proc.json_data.get("command") == "render"
    assert proc.json_data.get("bytes", 0) > 1000

    assert output_pdf.exists()
    assert output_pdf.stat().st_size > 1000
    # Verify PDF magic bytes
    with open(output_pdf, "rb") as f:
        header = f.read(5)
    assert header == b"%PDF-"


def test_t1_f12_03_chrome_cdp_discovery(chrome_executable):
    """TEST-T1-F12-03: Verify Chrome CDP executable discovery."""
    assert chrome_executable is not None, "Google Chrome or Chromium executable should be discovered on macOS"
    assert os.path.exists(chrome_executable)
    assert os.access(chrome_executable, os.X_OK)


def test_t1_f12_04_cli_render_force_overwrite(run_cli, fixtures_dir: Path, temp_e2e_dir: Path):
    """TEST-T1-F12-04: Verify target file collision without --force vs with --force."""
    input_json = fixtures_dir / "standard_resume.json"
    output_pdf = temp_e2e_dir / "collision_test.pdf"

    # Pre-create output file
    output_pdf.write_bytes(b"existing content")

    # 1. Without --force -> should fail or reject overwrite
    proc_no_force = run_cli(["render", str(input_json), "-o", str(output_pdf), "--json"])
    assert proc_no_force.returncode != 0
    assert proc_no_force.json_data is not None
    assert proc_no_force.json_data.get("ok") is False

    # 2. With --force -> should succeed
    proc_force = run_cli(["render", str(input_json), "-o", str(output_pdf), "--force", "--json"])
    assert proc_force.returncode == 0
    assert proc_force.json_data.get("ok") is True
    assert output_pdf.read_bytes().startswith(b"%PDF-")


def test_t1_f12_05_cli_render_json_contract(run_cli, fixtures_dir: Path, temp_e2e_dir: Path):
    """TEST-T1-F12-05: Verify CLI output contract with machine-readable --json payload."""
    input_json = fixtures_dir / "standard_resume.json"
    output_pdf = temp_e2e_dir / "json_contract.pdf"

    proc = run_cli(["render", str(input_json), "-o", str(output_pdf), "--json"])
    assert proc.returncode == 0
    data = proc.json_data
    assert data["ok"] is True
    assert data["command"] == "render"
    assert data["input"] == str(input_json)
    assert data["output"] == str(output_pdf)
    assert isinstance(data["bytes"], int)
    assert data["offline"] is True


def test_t1_f12_06_cli_render_html_export(run_cli, fixtures_dir: Path, temp_e2e_dir: Path):
    """TEST-T1-F12-06: Verify CLI renders valid self-contained HTML file."""
    input_json = fixtures_dir / "standard_resume.json"
    output_html = temp_e2e_dir / "rendered_resume.html"

    proc = run_cli(["render", str(input_json), "-o", str(output_html), "--template", "asu-tech", "--json"])
    assert proc.returncode == 0, f"HTML render failed: {proc.stderr}"
    assert proc.json_data is not None
    assert proc.json_data.get("ok") is True
    assert proc.json_data.get("engine") == "html"
    assert proc.json_data.get("template") == "asu-tech"

    assert output_html.exists()
    content = output_html.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "@page" in content
    assert "A4 portrait" in content
    assert "张三" in content


def test_t1_f12_07_cli_render_cdp_pdf_export(run_cli, fixtures_dir: Path, temp_e2e_dir: Path):
    """TEST-T1-F12-07: Verify CLI renders HTML template to PDF via Headless Chrome CDP."""
    input_json = fixtures_dir / "standard_resume.json"
    output_pdf = temp_e2e_dir / "cdp_rendered.pdf"

    proc = run_cli(["render", str(input_json), "-o", str(output_pdf), "--template", "asu-tech", "--json"])
    assert proc.returncode == 0, f"CDP render failed: {proc.stderr}"
    assert proc.json_data is not None
    assert proc.json_data.get("ok") is True
    assert proc.json_data.get("engine") == "html"
    assert proc.json_data.get("template") == "asu-tech"

    assert output_pdf.exists()
    assert output_pdf.stat().st_size > 1000
    with open(output_pdf, "rb") as f:
        header = f.read(5)
    assert header == b"%PDF-"


def test_t1_f12_08_cli_render_chrome_missing_error(run_cli, fixtures_dir: Path, temp_e2e_dir: Path, monkeypatch):
    """TEST-T1-F12-08: Verify structured chrome_not_found error when Chrome binary is missing."""
    input_json = fixtures_dir / "standard_resume.json"
    output_pdf = temp_e2e_dir / "missing_chrome.pdf"

    # Set invalid CHROME_BIN pointing to non-existent executable
    proc = run_cli(
        ["render", str(input_json), "-o", str(output_pdf), "--template", "asu-tech", "--json"],
        env={"CHROME_BIN": "/nonexistent/chrome/path", "PATH": ""},
    )
    assert proc.returncode != 0
    assert proc.json_data is not None
    assert proc.json_data.get("ok") is False
    assert proc.json_data.get("error", {}).get("code") == "chrome_not_found"


def test_t1_f12_09_cli_render_engine_auto_detection(run_cli, fixtures_dir: Path, temp_e2e_dir: Path):
    """TEST-T1-F12-09: Verify auto-detection of html vs latex engines and conflict rejection."""
    input_json = fixtures_dir / "standard_resume.json"

    # 1. Output ending in .html auto-selects html engine
    out_html = temp_e2e_dir / "auto_detect.html"
    proc_html = run_cli(["render", str(input_json), "-o", str(out_html), "--json"])
    assert proc_html.returncode == 0
    assert proc_html.json_data.get("engine") == "html"

    # 2. --engine latex with .html output must fail with engine_mismatch
    out_conflict = temp_e2e_dir / "conflict.html"
    proc_conflict = run_cli(["render", str(input_json), "-o", str(out_conflict), "--engine", "latex", "--json"])
    assert proc_conflict.returncode != 0
    assert proc_conflict.json_data.get("error", {}).get("code") == "engine_mismatch"

    # 3. Output ending in .pdf with default template auto-selects latex engine
    out_pdf_latex = temp_e2e_dir / "auto_latex.pdf"
    proc_latex = run_cli(["render", str(input_json), "-o", str(out_pdf_latex), "--template", "default", "--json"])
    assert proc_latex.returncode == 0
    assert proc_latex.json_data.get("engine") == "latex"
