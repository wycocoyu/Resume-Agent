"""Tier 4 Real-World Application Scenarios: Scenario 4.

Scenario 4: Universal Skill & CLI CDP PDF Render (多端通用 Skill 载体与 CLI 无头 CDP 导出)
Authoritative specs:
- SCOPE.md § Tier 4 Scenarios, TEST_INFRA.md
- Pipeline:
  1. Inspect skill list and build skill directory
  2. Validate resume data with CLI
  3. Render PDF via CLI render subcommand
  4. Verify PDF structure and extractable text
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest


def test_scenario4_universal_skill_and_cli_cdp_render(fixtures_dir: Path, temp_e2e_dir: Path, run_cli):
    """Scenario 4: End-to-end skill generation, CLI validation, and PDF render execution."""
    resume_file = fixtures_dir / "standard_resume.json"
    
    # 1. Skill list discovery
    proc_list = run_cli(["skill", "list", "--json"])
    assert proc_list.returncode == 0
    assert proc_list.json_data.get("ok") is True
    
    # 2. Build skill into temp dir
    skill_out = temp_e2e_dir / "skills"
    proc_build = run_cli(["skill", "build", "--harness", "claude", "--out", str(skill_out), "--json"])
    assert proc_build.returncode == 0
    claude_skill = skill_out / "claude" / "resume-agent" / "SKILL.md"
    assert claude_skill.exists()
    
    # 3. CLI validation
    proc_val = run_cli(["validate", str(resume_file), "--json"])
    assert proc_val.returncode == 0
    assert proc_val.json_data.get("ok") is True
    
    # 4. Render PDF
    out_pdf = temp_e2e_dir / "rendered_output.pdf"
    proc_render = run_cli(["render", str(resume_file), "-o", str(out_pdf), "--json"])
    assert proc_render.returncode == 0
    assert out_pdf.exists()
    
    # 5. Verify PDF bytes
    pdf_bytes = out_pdf.read_bytes()
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 10000
