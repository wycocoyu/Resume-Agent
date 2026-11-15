"""Tier 3 Pairwise Combinations: Group 3 (Storage & Rendering Interactions).

Authoritative specs:
- SCOPE.md § Feature Inventory & Pairwise Matrix
- E2E-T3-07: F14 MCP `sync_workspace` × F6 Downward Compatible Storage Migration (Scheduled for M5)
- E2E-T3-12: F11 Dual Engine PDF × F15 Client-Side Privacy Masking
- E2E-T3-13: F10 Auto-One-Page Adaptive Fit × F9 Print Preview Styles
- E2E-T3-14: F13 Derivative Resume Storage × F6 Storage Compatibility
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import pytest

from backend.routes.config import _mask_key
from backend.core.logger import _sanitize_text_payload
from backend.latex_generator import render_pdf_from_resume_latex

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t3_07_mcp_sync_workspace_and_legacy_storage_migration(fixtures_dir: Path):
    """E2E-T3-07: Verify MCP sync_workspace consumes legacy v1 storage format (Scheduled for M5)."""
    legacy_fixture = fixtures_dir / "legacy_resume_v1.json"
    legacy_data = json.loads(legacy_fixture.read_text(encoding="utf-8"))

    # Real MCP server call (honestly fails Red until M5)
    from backend.mcp.server import sync_workspace
    sync_res = sync_workspace("push", {"resumes": [legacy_data]})
    assert sync_res.get("status") == "success" or sync_res.get("synced_count", 0) >= 1


def test_t3_12_pdf_click_to_source_and_privacy_unmasked_form(standard_resume_data: dict):
    """E2E-T3-12: Verify real LaTeX rendering generates valid PDF while PII logging remains sanitized."""
    pdf_stream = render_pdf_from_resume_latex(standard_resume_data)
    assert pdf_stream.getvalue()[:5] == b"%PDF-"

    # Verify that logging raw resume payload masks sensitive keys
    raw_log = f"Rendering PDF for candidate with body={json.dumps(standard_resume_data, ensure_ascii=False)}"
    sanitized = _sanitize_text_payload(raw_log)
    assert "body=[REDACTED]" in sanitized


def test_t3_13_auto_one_page_and_print_preview_styles():
    """E2E-T3-13: Verify auto-one-page Vitest suite passes and production variants CSS includes @media print rules."""
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

    css_path = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "styles" / "asuVariants.module.css"
    assert css_path.exists()
    content = css_path.read_text(encoding="utf-8")
    assert "@media print" in content


def test_t3_14_derivative_resume_and_storage_key_compatibility():
    """E2E-T3-14: Verify storage compatibility migration passes all 11 Vitest test cases."""
    vitest_cmd = [
        "npx", "vitest", "run",
        "src/utils/storageCompat.test.ts",
    ]
    res = subprocess.run(
        vitest_cmd,
        cwd=str(WORKTREE_ROOT / "frontend"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, f"storageCompat Vitest failed:\n{res.stdout}\n{res.stderr}"
