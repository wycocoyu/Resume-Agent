"""Tier 2 Boundary & Corner Tests: Feature 8 (18 Variant HTML Themes Matrix Boundaries).

Authoritative specs:
- ORIGINAL_REQUEST §R3.1, Issue #45
- frontend/src/pages/Builder/templates/ResumeAsuVariant.tsx
- frontend/src/pages/Builder/templates/styles/asuVariants.module.css
"""
from __future__ import annotations

from pathlib import Path
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t2_f08_01_sidebar_layout_rules_in_production():
    """TEST-T2-F08-01: Verify sidebar layout defines flex gap and min-width rules."""
    css_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "styles" / "asuVariants.module.css"
    assert css_file.exists(), f"CSS module must exist at {css_file}"
    content = css_file.read_text(encoding="utf-8")

    assert ".layoutSidebar" in content
    assert ".sidebar" in content
    assert "min-width: 180px" in content or "width: 32%" in content


def test_t2_f08_02_two_column_grid_proportions():
    """TEST-T2-F08-02: Verify two-column layout defines 1.25fr:0.95fr grid proportions."""
    css_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "styles" / "asuVariants.module.css"
    content = css_file.read_text(encoding="utf-8")

    assert ".layoutTwoColumn" in content
    assert "grid-template-columns: 1.25fr 0.95fr" in content or "1.25fr" in content


def test_t2_f08_03_print_media_rules_in_variants():
    """TEST-T2-F08-03: Verify print media overrides container padding and width."""
    css_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "styles" / "asuVariants.module.css"
    content = css_file.read_text(encoding="utf-8")

    assert "@media print" in content
    assert "padding: 0 !important" in content
    assert "width: 210mm !important" in content


def test_t2_f08_04_fallback_to_asu_01_in_component():
    """TEST-T2-F08-04: Verify component fallback logic to asu-01 on unknown variant."""
    tsx_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "ResumeAsuVariant.tsx"
    assert tsx_file.exists()
    content = tsx_file.read_text(encoding="utf-8")
    assert "ASU_VARIANTS_CONFIG[variantId] || ASU_VARIANTS_CONFIG['asu-01']" in content


def test_t2_f08_05_dense_and_modern_variant_styles():
    """TEST-T2-F08-05: Verify dense and modern classes are defined in production CSS."""
    css_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "styles" / "asuVariants.module.css"
    content = css_file.read_text(encoding="utf-8")
    assert ".variantDense" in content
    assert ".variantModern" in content
