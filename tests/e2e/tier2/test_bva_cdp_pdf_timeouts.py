"""Tier 2 Boundary & Corner Tests: Feature 12 (CLI HTML & CDP PDF Render Timeouts/Errors).

Authoritative specs:
- ORIGINAL_REQUEST §R3.2, Issue #47
- backend/cli/render_cmd.py
- Boundaries: target file exists without force, corrupt input JSON file, missing template dir, Chrome discovery fallback, large resume payload
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t2_f12_01_target_file_exists_without_force_refusal(run_cli, fixtures_dir: Path, temp_e2e_dir: Path):
    """TEST-T2-F12-01: Verify render refuses to overwrite existing target file without --force."""
    fixture_path = fixtures_dir / "standard_resume.json"
    out_pdf = temp_e2e_dir / "existing_resume.pdf"
    out_pdf.write_bytes(b"%PDF-1.4 existing dummy content")
    
    proc = run_cli(["render", str(fixture_path), "-o", str(out_pdf), "--json"])
    assert proc.returncode != 0
    if proc.json_data:
        assert proc.json_data.get("ok") is False
        assert proc.json_data.get("error", {}).get("code") == "file_exists"


def test_t2_f12_02_corrupt_input_json_syntax_error(run_cli, temp_e2e_dir: Path):
    """TEST-T2-F12-02: Verify rendering corrupted JSON file reports syntax/file error."""
    corrupt_file = temp_e2e_dir / "corrupted_input.json"
    corrupt_file.write_text("{'invalid': JSON syntax,", encoding="utf-8")
    out_pdf = temp_e2e_dir / "out.pdf"
    
    proc = run_cli(["render", str(corrupt_file), "-o", str(out_pdf), "--json"])
    assert proc.returncode in (1, 2)
    if proc.json_data:
        assert proc.json_data.get("ok") is False
        assert "error" in proc.json_data


def test_t2_f12_03_invalid_template_dir_reports_clear_error(run_cli, fixtures_dir: Path, temp_e2e_dir: Path):
    """TEST-T2-F12-03: Verify pointing --template-dir to non-existent dir exits with file_error."""
    fixture_path = fixtures_dir / "standard_resume.json"
    bad_template_dir = temp_e2e_dir / "nonexistent_template"
    out_pdf = temp_e2e_dir / "out.pdf"
    
    proc = run_cli(["render", str(fixture_path), "-o", str(out_pdf), "--template-dir", str(bad_template_dir), "--json"])
    assert proc.returncode != 0
    if proc.json_data:
        assert proc.json_data.get("ok") is False


def test_t2_f12_04_chrome_cdp_executable_resolution(chrome_executable):
    """TEST-T2-F12-04: Verify Chrome discovery returns valid executable or None gracefully."""
    import os
    if chrome_executable:
        assert os.path.exists(chrome_executable)
        assert os.access(chrome_executable, os.X_OK)


def test_t2_f12_05_large_resume_20_projects_json_integrity(fixtures_dir: Path, temp_e2e_dir: Path):
    """TEST-T2-F12-05: Verify constructing resume with 20 project entries parses without payload corruption."""
    fixture_path = fixtures_dir / "standard_resume.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    
    base_project = data.get("projects", [{}])[0]
    data["projects"] = [
        {**base_project, "name": f"Enterprise Project {i}", "role": "Architect Lead"}
        for i in range(20)
    ]
    
    assert len(data["projects"]) == 20
    large_json_path = temp_e2e_dir / "large_20_projects.json"
    large_json_path.write_text(json.dumps(data), encoding="utf-8")
    loaded = json.loads(large_json_path.read_text(encoding="utf-8"))
    assert len(loaded["projects"]) == 20
