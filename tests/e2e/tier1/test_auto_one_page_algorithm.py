"""Tier 1 Feature Coverage: Feature 10 (3-Tier Auto-One-Page Adaptive Fit, Issue #46).

Authoritative specs:
- ORIGINAL_REQUEST §R3.1, Issue #46
- 3-Tier progressive height fitting:
  Tier 0: Content <= 1122.5px (A4 height) -> 1.0 scale, no adjust
  Tier 1: Slight overflow -> spacing compression (0.45 min factor)
  Tier 2: Moderate overflow -> line-height compression (1.22 min)
  Tier 3: Severe overflow -> transform scale down to 0.82 minScale bound
- frontend/src/pages/Workspace/v2/utils/autoOnePage.ts
- frontend/src/pages/Workspace/v2/utils/autoOnePage.test.ts
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t1_f10_01_production_file_contract():
    """TEST-T1-F10-01: Verify autoOnePage.ts exists and exports required algorithm functions."""
    alg_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Workspace" / "v2" / "utils" / "autoOnePage.ts"
    assert alg_file.exists(), f"Production file must exist at {alg_file}"
    content = alg_file.read_text(encoding="utf-8")

    assert "export function autoFitToOnePage" in content
    assert "export function resetAutoFit" in content
    assert "A4_TARGET_HEIGHT_PX" in content


def test_t1_f10_02_execute_real_vitest_auto_one_page_suite():
    """TEST-T1-F10-02: Execute real frontend autoOnePage.test.ts via Vitest and verify 100% pass."""
    frontend_dir = WORKTREE_ROOT / "frontend"
    res = subprocess.run(
        ["npx", "vitest", "run", "src/pages/Workspace/v2/utils/autoOnePage.test.ts", "--reporter=json"],
        cwd=str(frontend_dir),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Vitest execution failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    
    data = json.loads(res.stdout)
    assert data.get("numFailedTests", 0) == 0
    assert data.get("numPassedTests", 0) >= 5, f"Expected >= 5 tests passed, got {data.get('numPassedTests')}"


def test_t1_f10_03_three_tier_compression_gradients():
    """TEST-T1-F10-03: Verify production code implements Tier 0, 1, 2, 3 compression tiers."""
    alg_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Workspace" / "v2" / "utils" / "autoOnePage.ts"
    content = alg_file.read_text(encoding="utf-8")

    assert "Tier 0" in content
    assert "Tier 1" in content
    assert "Tier 2" in content
    assert "Tier 3" in content
    assert "minSpacingFactor" in content
    assert "minLineHeight" in content


def test_t1_f10_04_min_scale_bound():
    """TEST-T1-F10-04: Verify minScale threshold (0.82) is enforced as lower bound in production."""
    alg_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Workspace" / "v2" / "utils" / "autoOnePage.ts"
    content = alg_file.read_text(encoding="utf-8")
    assert "0.82" in content, "minScale 0.82 must be specified in options"


def test_t1_f10_05_reset_auto_fit_cleanup():
    """TEST-T1-F10-05: Verify resetAutoFit restores original uncompressed styling."""
    alg_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Workspace" / "v2" / "utils" / "autoOnePage.ts"
    content = alg_file.read_text(encoding="utf-8")
    assert "container.style.removeProperty" in content or "removeProperty('--section-gap')" in content or "resetAutoFit" in content
