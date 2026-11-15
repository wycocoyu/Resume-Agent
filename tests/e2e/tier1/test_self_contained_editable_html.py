"""Tier 1 Feature Coverage: Feature 9 (Self-Contained Editable HTML Export, Issue #46).

Authoritative specs:
- ORIGINAL_REQUEST §R3.1, Issue #46
- Single-file zero-network HTML export with inline CSS/SVG
- frontend/src/pages/Workspace/v2/utils/generateHTML.ts
- frontend/src/pages/Workspace/v2/utils/generateHTML.test.ts
- contenteditable attributes on editable sections
- Local toolbar with actions and @media print styles hiding toolbar
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t1_f09_01_production_file_contract():
    """TEST-T1-F09-01: Verify generateHTML.ts exists and exports required functions."""
    gen_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Workspace" / "v2" / "utils" / "generateHTML.ts"
    assert gen_file.exists(), f"Production file must exist at {gen_file}"
    content = gen_file.read_text(encoding="utf-8")

    assert "export function generateHTML" in content
    assert "export function generateHTMLFile" in content


def test_t1_f09_02_execute_real_vitest_generate_html_suite():
    """TEST-T1-F09-02: Execute real frontend generateHTML.test.ts via Vitest and verify 100% pass."""
    frontend_dir = WORKTREE_ROOT / "frontend"
    res = subprocess.run(
        ["npx", "vitest", "run", "src/pages/Workspace/v2/utils/generateHTML.test.ts", "--reporter=json"],
        cwd=str(frontend_dir),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Vitest execution failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    
    data = json.loads(res.stdout)
    assert data.get("numFailedTests", 0) == 0
    assert data.get("numPassedTests", 0) >= 4, f"Expected >= 4 tests passed, got {data.get('numPassedTests')}"


def test_t1_f09_03_zero_external_cdn_dependencies():
    """TEST-T1-F09-03: Verify production generateHTML.ts contains zero external CDN asset links."""
    gen_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Workspace" / "v2" / "utils" / "generateHTML.ts"
    content = gen_file.read_text(encoding="utf-8")

    assert "fonts.googleapis.com" not in content
    assert "cdnjs.cloudflare.com" not in content
    assert "unpkg.com" not in content


def test_t1_f09_04_local_toolbar_and_print_hiding():
    """TEST-T1-F09-04: Verify embedded local toolbar and @media print hiding rules."""
    gen_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Workspace" / "v2" / "utils" / "generateHTML.ts"
    content = gen_file.read_text(encoding="utf-8")

    assert "local-toolbar" in content or "toolbar" in content
    assert "@media print" in content or "@page" in content
    assert "window.print()" in content


def test_t1_f09_05_contenteditable_support():
    """TEST-T1-F09-05: Verify contenteditable attribute injection for in-browser editing."""
    gen_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Workspace" / "v2" / "utils" / "generateHTML.ts"
    content = gen_file.read_text(encoding="utf-8")
    assert 'contenteditable="true"' in content
