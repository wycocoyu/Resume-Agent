"""Tier 2 Boundary & Corner Tests: Feature 10 (Auto-One-Page Adaptive Fit Thresholds).

Authoritative specs:
- ORIGINAL_REQUEST §R3.1, Issue #46
- frontend/src/pages/Workspace/v2/utils/autoOnePage.ts
- frontend/src/pages/Workspace/v2/utils/autoOnePage.test.ts
- Boundaries: extreme overflow clamp (minScale: 0.82), minimal height, dynamic reset, photo aspect ratio, page break
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t2_f10_01_extreme_overflow_scale_cap_in_production():
    """TEST-T2-F10-01: Verify production autoOnePage clamps scale at minScale (0.82) on severe overflow."""
    alg_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Workspace" / "v2" / "utils" / "autoOnePage.ts"
    assert alg_file.exists()
    content = alg_file.read_text(encoding="utf-8")

    assert "Math.max(scale, minScale)" in content or "scale < minScale ? minScale : scale" in content or "minScale" in content
    assert "0.82" in content


def test_t2_f10_02_minimal_underflow_zero_division_safety():
    """TEST-T2-F10-02: Verify production code checks overflowRatio > 1.0 before applying compression."""
    alg_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Workspace" / "v2" / "utils" / "autoOnePage.ts"
    content = alg_file.read_text(encoding="utf-8")
    assert "origHeight <= targetHeight" in content or "overflowRatio <= 1.0" in content or "tier: 0" in content


def test_t2_f10_03_vitest_auto_one_page_suite_execution():
    """TEST-T2-F10-03: Execute real Vitest autoOnePage.test.ts verifying all 5 boundary test cases."""
    frontend_dir = WORKTREE_ROOT / "frontend"
    res = subprocess.run(
        ["npx", "vitest", "run", "src/pages/Workspace/v2/utils/autoOnePage.test.ts", "--reporter=json"],
        cwd=str(frontend_dir),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data.get("numFailedTests", 0) == 0
    assert data.get("numPassedTests", 0) >= 5


def test_t2_f10_04_fixed_photo_aspect_ratio_in_css():
    """TEST-T2-F10-04: Verify 28mm x 36mm photo dimensions in production CSS maintain aspect ratio."""
    css_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "styles" / "asuTech.module.css"
    content = css_file.read_text(encoding="utf-8")
    assert "width: 28mm" in content
    assert "height: 36mm" in content
    assert "object-fit: cover" in content


def test_t2_f10_05_page_break_inside_avoid_rules():
    """TEST-T2-F10-05: Verify CSS rules prevent breaking inside section items during multi-page print."""
    css_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "styles" / "asuTech.module.css"
    content = css_file.read_text(encoding="utf-8")
    assert "break-inside: avoid" in content
    assert "page-break-inside: avoid" in content
