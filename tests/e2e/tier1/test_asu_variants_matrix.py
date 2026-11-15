"""Tier 1 Feature Coverage: Feature 8 (18 variant-* Atomic HTML Themes Matrix, Issue #45).

Authoritative specs:
- ORIGINAL_REQUEST §R2.1, Issue #45
- 18 distinct variant combinations (asu-01 through asu-18)
- 3 skeleton layouts: single-column, sidebar, two-column
- frontend/src/pages/Builder/templates/ResumeAsuVariant.tsx
- frontend/src/pages/Builder/templates/styles/asuVariants.module.css
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t1_f08_01_variant_component_existence():
    """TEST-T1-F08-01: Verify ResumeAsuVariant.tsx exists in production codebase."""
    variant_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "ResumeAsuVariant.tsx"
    assert variant_file.exists(), f"ResumeAsuVariant.tsx must exist at {variant_file}"
    content = variant_file.read_text(encoding="utf-8")
    assert "export const ResumeAsuVariant" in content
    assert "export const ASU_VARIANTS_CONFIG" in content


def test_t1_f08_02_all_18_variants_defined_in_production():
    """TEST-T1-F08-02: Verify all 18 variants (asu-01 through asu-18) are defined in ASU_VARIANTS_CONFIG."""
    variant_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "ResumeAsuVariant.tsx"
    content = variant_file.read_text(encoding="utf-8")

    for i in range(1, 19):
        var_id = f"asu-{i:02d}"
        assert f"'{var_id}':" in content or f'"{var_id}":' in content, f"Missing variant {var_id} in config"


def test_t1_f08_03_three_skeleton_layouts_supported():
    """TEST-T1-F08-03: Verify single-column, sidebar, and two-column layouts are handled in production."""
    variant_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "ResumeAsuVariant.tsx"
    content = variant_file.read_text(encoding="utf-8")

    assert "layout: 'single-column'" in content or 'layout: "single-column"' in content
    assert "layout: 'sidebar'" in content or 'layout: "sidebar"' in content
    assert "layout: 'two-column'" in content or 'layout: "two-column"' in content


def test_t1_f08_04_fallback_to_asu_01_on_unknown():
    """TEST-T1-F08-04: Verify production component falls back to asu-01 when unknown variant requested."""
    variant_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "ResumeAsuVariant.tsx"
    content = variant_file.read_text(encoding="utf-8")
    assert "ASU_VARIANTS_CONFIG['asu-01']" in content or 'ASU_VARIANTS_CONFIG["asu-01"]' in content


def test_t1_f08_05_cli_render_variant_execution(run_cli, temp_e2e_dir: Path, standard_resume_data):
    """TEST-T1-F08-05: Real CLI execution with variant template (Scheduled for M4 delivery)."""
    resume_file = temp_e2e_dir / "resume.json"
    resume_file.write_text(json.dumps(standard_resume_data), encoding="utf-8")
    out_pdf = temp_e2e_dir / "variant_rendered.pdf"

    proc = run_cli(["render", str(resume_file), "-o", str(out_pdf), "--template", "asu-01"])
    # In M1/M2/M3, CLI does not yet implement --template asu-01, so it will exit non-zero
    # In M4, this test turns green upon implementation of CLI HTML templates
    assert proc.returncode == 0, f"CLI render with variant failed (expected until M4): {proc.stderr}"
    assert out_pdf.exists()
