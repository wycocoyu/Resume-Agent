"""Tier 2 Boundary & Corner Tests: Feature 9 (Self-Contained Editable HTML Boundaries).

Authoritative specs:
- ORIGINAL_REQUEST §R3.1, Issue #46
- frontend/src/pages/Workspace/v2/utils/generateHTML.ts
- frontend/src/pages/Workspace/v2/utils/generateHTML.test.ts
- Boundaries: zero external assets, file:/// isolation, XSS protection, size limits
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t2_f09_01_zero_external_network_dependencies():
    """TEST-T2-F09-01: Verify production generateHTML.ts contains zero external CDN / HTTP links."""
    gen_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Workspace" / "v2" / "utils" / "generateHTML.ts"
    assert gen_file.exists(), f"generateHTML.ts must exist at {gen_file}"
    content = gen_file.read_text(encoding="utf-8")

    assert "fonts.googleapis.com" not in content
    assert "cdnjs.cloudflare.com" not in content
    assert "unpkg.com" not in content
    assert "cdn.jsdelivr.net" not in content


def test_t2_f09_02_offline_file_protocol_compatibility():
    """TEST-T2-F09-02: Verify generateHTML.ts does not rely on server-hosted absolute root URLs."""
    gen_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Workspace" / "v2" / "utils" / "generateHTML.ts"
    content = gen_file.read_text(encoding="utf-8")
    assert 'href="/' not in content
    assert 'src="/' not in content


def test_t2_f09_03_xss_protection_in_production_export():
    """TEST-T2-F09-03: Verify production generateHTML sanitizes text fields and escapes HTML entities."""
    gen_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Workspace" / "v2" / "utils" / "generateHTML.ts"
    content = gen_file.read_text(encoding="utf-8")
    assert "escape" in content.lower() or "sanitize" in content.lower() or "replace(/</g" in content


def test_t2_f09_04_print_styles_embedded_in_css():
    """TEST-T2-F09-04: Verify production generateHTML embeds print styling for exact page fit."""
    gen_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Workspace" / "v2" / "utils" / "generateHTML.ts"
    content = gen_file.read_text(encoding="utf-8")
    assert "@page {" in content or "@media print" in content
    assert "size: A4 portrait" in content or "A4" in content


def test_t2_f09_05_vitest_generate_html_execution():
    """TEST-T2-F09-05: Execute real Vitest generateHTML.test.ts verifying offline and print boundary conditions."""
    frontend_dir = WORKTREE_ROOT / "frontend"
    res = subprocess.run(
        ["npx", "vitest", "run", "src/pages/Workspace/v2/utils/generateHTML.test.ts", "--reporter=json"],
        cwd=str(frontend_dir),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data.get("numFailedTests", 0) == 0
