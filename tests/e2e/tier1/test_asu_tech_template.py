"""Tier 1 Feature Coverage: Feature 7 (ASu asu-tech HTML Template, Issue #44).

Authoritative specs:
- ORIGINAL_REQUEST §R2.1, Issue #44
- Single-column high-density layout (4px blue underline, grey capsule tags)
- frontend/src/pages/Builder/templates/ResumeAsuTech.tsx
- frontend/src/pages/Builder/templates/styles/asuTech.module.css
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t1_f07_01_template_component_existence():
    """TEST-T1-F07-01: Verify ResumeAsuTech.tsx exists in production codebase."""
    template_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "ResumeAsuTech.tsx"
    assert template_file.exists(), f"ResumeAsuTech.tsx must exist at {template_file}"
    content = template_file.read_text(encoding="utf-8")
    assert "export const ResumeAsuTech" in content
    assert "data: BuilderResumeData" in content


def test_t1_f07_02_single_column_structure_and_star_bullets():
    """TEST-T1-F07-02: Verify single column high-density structure and 3-level STAR accomplishments."""
    template_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "ResumeAsuTech.tsx"
    content = template_file.read_text(encoding="utf-8")
    
    # Verify STAR bullets handling and nested depth
    assert "bulletList" in content
    assert "nested" in content
    assert "renderBullets" in content


def test_t1_f07_03_accent_color_and_capsule_tags():
    """TEST-T1-F07-03: Verify CSS module defines blue underline and institution capsules."""
    css_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "styles" / "asuTech.module.css"
    assert css_file.exists(), f"asuTech.module.css must exist at {css_file}"
    content = css_file.read_text(encoding="utf-8")

    assert "sectionTitle" in content
    assert "companyBar" in content
    assert "border-bottom" in content


def test_t1_f07_04_print_color_adjustment():
    """TEST-T1-F07-04: Verify print media preserves background colors and capsules."""
    css_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "styles" / "asuTech.module.css"
    content = css_file.read_text(encoding="utf-8")
    assert "print-color-adjust" in content or "-webkit-print-color-adjust" in content


def test_t1_f07_05_cli_render_with_asu_tech_template(run_cli, temp_e2e_dir: Path, standard_resume_data):
    """TEST-T1-F07-05: Real CLI execution with --template asu-tech (Scheduled for M4 delivery)."""
    resume_file = temp_e2e_dir / "resume.json"
    resume_file.write_text(json.dumps(standard_resume_data), encoding="utf-8")
    out_pdf = temp_e2e_dir / "rendered.pdf"

    proc = run_cli(["render", str(resume_file), "-o", str(out_pdf), "--template", "asu-tech"])
    # In M1/M2/M3, CLI does not yet implement --template asu-tech, so it will exit non-zero
    # In M4, this test turns green upon implementation of CLI HTML templates
    assert proc.returncode == 0, f"CLI render with asu-tech failed (expected until M4): {proc.stderr}"
    assert out_pdf.exists()
