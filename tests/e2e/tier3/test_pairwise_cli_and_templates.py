"""Tier 3 Pairwise Combinations: Group 1 (CLI & Templates Interactions).

Authoritative specs:
- SCOPE.md § Feature Inventory & Pairwise Matrix
- E2E-T3-01: F5 Rebranding CLI × F9 Self-Contained HTML Export
- E2E-T3-06: F12 CLI CDP Export × F7 ASu `asu-tech` Template
- E2E-T3-11: F12 CLI Validate Output × F14 MCP `validate_resume` (Scheduled for M5)
- E2E-T3-16: F12 CLI CDP Export × F10 Auto-One-Page Adaptive Scaling
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import pytest

from backend.cli.schema import validate_resume_data

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t3_01_cli_rebranding_and_html_export(run_cli, temp_e2e_dir: Path):
    """E2E-T3-01: Verify cococv and resume-agent CLI aliases validate schema and real HTML exporter passes vitest."""
    fixture_path = WORKTREE_ROOT / "tests" / "e2e" / "fixtures" / "standard_resume.json"

    # Test real CLI validate with both aliases
    proc1 = run_cli(["validate", str(fixture_path), "--json"], entrypoint="cococv")
    assert proc1.returncode == 0
    assert proc1.json_data.get("ok") is True

    proc2 = run_cli(["validate", str(fixture_path), "--json"], entrypoint="resume-agent")
    assert proc2.returncode == 0
    assert proc2.json_data.get("ok") is True

    # Test real production HTML export utility via Vitest
    vitest_cmd = [
        "npx", "vitest", "run",
        "src/pages/Workspace/v2/utils/generateHTML.test.ts",
    ]
    res = subprocess.run(
        vitest_cmd,
        cwd=str(WORKTREE_ROOT / "frontend"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, f"generateHTML Vitest failed:\n{res.stdout}\n{res.stderr}"


def test_t3_06_cli_cdp_export_and_asu_tech_template(run_cli, temp_e2e_dir: Path):
    """E2E-T3-06: Verify CLI PDF export executes and production asu-tech template component exists."""
    fixture_path = WORKTREE_ROOT / "tests" / "e2e" / "fixtures" / "standard_resume.json"
    out_pdf = temp_e2e_dir / "asu_tech_out.pdf"

    # Real CLI render
    proc = run_cli(["render", str(fixture_path), "-o", str(out_pdf), "--json"])
    assert proc.returncode == 0
    assert out_pdf.exists()
    assert out_pdf.stat().st_size > 1000
    assert out_pdf.read_bytes()[:5] == b"%PDF-"

    # Production template stylesheet verification
    css_path = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "styles" / "asuTech.module.css"
    assert css_path.exists()
    css_content = css_path.read_text(encoding="utf-8")
    assert ".companyBar" in css_content


def test_t3_11_cli_validation_and_mcp_validation_parity(standard_resume_data: dict, temp_e2e_dir: Path, run_cli):
    """E2E-T3-11: Verify parity between CLI validate command and official MCP validate_resume tool (Scheduled for M5)."""
    # 1. Real CLI validation
    resume_file = temp_e2e_dir / "test_validate.json"
    resume_file.write_text(json.dumps(standard_resume_data, ensure_ascii=False), encoding="utf-8")
    cli_proc = run_cli(["validate", str(resume_file), "--json"])
    assert cli_proc.returncode == 0
    assert cli_proc.json_data.get("ok") is True

    # 2. Real MCP validate tool from backend.mcp.server (honestly fails Red until M5)
    from backend.mcp.server import validate_resume
    mcp_res = validate_resume(standard_resume_data)
    valid = mcp_res["valid"] if isinstance(mcp_res, dict) else mcp_res.valid
    assert valid is True


def test_t3_16_cdp_export_and_auto_one_page_scaling(run_cli, temp_e2e_dir: Path):
    """E2E-T3-16: Verify real CLI render paired with real auto-one-page Vitest test suite."""
    fixture_path = WORKTREE_ROOT / "tests" / "e2e" / "fixtures" / "standard_resume.json"
    out_pdf = temp_e2e_dir / "cdp_scaled_out.pdf"

    # Real CLI render
    proc = run_cli(["render", str(fixture_path), "-o", str(out_pdf), "--json"])
    assert proc.returncode == 0
    assert out_pdf.exists()

    # Real auto-one-page Vitest suite
    vitest_cmd = [
        "npx", "vitest", "run",
        "src/pages/Workspace/v2/utils/autoOnePage.test.ts",
    ]
    res = subprocess.run(
        vitest_cmd,
        cwd=str(WORKTREE_ROOT / "frontend"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, f"autoOnePage Vitest failed:\n{res.stdout}\n{res.stderr}"
