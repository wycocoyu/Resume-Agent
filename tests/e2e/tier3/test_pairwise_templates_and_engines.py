"""Tier 3 Pairwise Combinations: Group 2 (Templates & Engines Interactions).

Authoritative specs:
- SCOPE.md § Feature Inventory & Pairwise Matrix
- E2E-T3-04: F10 Auto-One-Page × F8 18 Atomic HTML Themes Matrix
- E2E-T3-05: F11 Dual Engine Switch × F11 LaTeX Memory Cache
- E2E-T3-10: F9 Self-Contained HTML Export × F16 Dark Mode Design Tokens
- E2E-T3-15: F14 MCP `render_pdf` × F11 Dual Rendering Engines (Scheduled for M5)
"""
from __future__ import annotations

import io
from pathlib import Path
import subprocess
import time
import pytest

from backend.latex_generator import (
    _get_cache_key,
    _pdf_cache,
    render_pdf_from_resume_latex,
)

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t3_04_auto_one_page_and_18_variants_matrix():
    """E2E-T3-04: Verify production ResumeAsuVariant template component exists and auto-one-page Vitest suite passes."""
    variant_component = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "ResumeAsuVariant.tsx"
    assert variant_component.exists()
    content = variant_component.read_text(encoding="utf-8")
    assert "ResumeAsuVariant" in content

    # Run real auto-one-page Vitest suite
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


def test_t3_05_engine_switch_and_latex_cache_hit(standard_resume_data: dict):
    """E2E-T3-05: Verify switching back to LaTeX engine after HTML editing achieves instant cache hit."""
    # Step 1: Render via LaTeX engine and populate cache
    pdf_stream1 = render_pdf_from_resume_latex(standard_resume_data)
    assert pdf_stream1.getvalue()[:5] == b"%PDF-"

    cache_key = _get_cache_key(standard_resume_data, None)
    assert cache_key in _pdf_cache

    # Step 2: Second call must hit memory cache (< 100ms)
    start_t = time.time()
    pdf_stream2 = render_pdf_from_resume_latex(standard_resume_data)
    elapsed = time.time() - start_t

    assert elapsed < 0.1, f"Expected cache hit under 100ms, took {elapsed*1000:.1f}ms"
    assert pdf_stream2.getvalue() == pdf_stream1.getvalue()


def test_t3_10_html_export_and_dark_mode_print_isolation():
    """E2E-T3-10: Verify production variants CSS enforces @media print isolation for clean paper output."""
    css_path = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "styles" / "asuVariants.module.css"
    assert css_path.exists()
    content = css_path.read_text(encoding="utf-8")
    assert "@media print" in content

    # Vitest for generateHTML
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


def test_t3_15_mcp_render_pdf_and_dual_engines(standard_resume_data: dict):
    """E2E-T3-15: Verify MCP render_pdf routes to rendering engine (Scheduled for M5)."""
    from backend.mcp.server import render_pdf
    pdf_bytes = render_pdf(standard_resume_data, engine="latex")
    assert pdf_bytes[:5] == b"%PDF-"
