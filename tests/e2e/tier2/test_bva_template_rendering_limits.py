"""Tier 2 Boundary & Corner Tests: Feature 7 (ASu Tech Template Rendering Limits).

Authoritative specs:
- ORIGINAL_REQUEST §R3.1, Issue #44
- frontend/src/pages/Builder/templates/sanitizeHtml.ts
- frontend/src/pages/Builder/templates/ResumeAsuTech.tsx
- frontend/src/pages/Builder/templates/styles/asuTech.module.css
"""
from __future__ import annotations

from pathlib import Path
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t2_f07_01_sanitize_html_production_contract():
    """TEST-T2-F07-01: Verify sanitizeHtml.ts defines inline whitelist and exports sanitizeInlineHtml."""
    sanitizer_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "sanitizeHtml.ts"
    assert sanitizer_file.exists(), f"Sanitizer must exist at {sanitizer_file}"
    content = sanitizer_file.read_text(encoding="utf-8")

    assert "export function sanitizeInlineHtml" in content
    assert "export function escapeText" in content
    assert "INLINE_TAGS = new Set(" in content
    for expected_tag in ("'STRONG'", "'B'", "'EM'", "'I'", "'U'", "'A'", "'CODE'"):
        assert expected_tag in content


def test_t2_f07_02_script_and_dangerous_protocols_blocked():
    """TEST-T2-F07-02: Verify production sanitizer limits anchor hrefs to safe protocols."""
    sanitizer_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "sanitizeHtml.ts"
    content = sanitizer_file.read_text(encoding="utf-8")
    assert "/^(https?:|mailto:|tel:)/i.test(href)" in content, "Must restrict anchor hrefs to safe protocols"


def test_t2_f07_03_empty_sections_return_null_in_production():
    """TEST-T2-F07-03: Verify ResumeAsuTech guards against orphaned headers when lists are empty."""
    template_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "ResumeAsuTech.tsx"
    content = template_file.read_text(encoding="utf-8")
    assert "if (!items || items.length === 0) return null" in content


def test_t2_f07_04_avatar_slot_empty_handling():
    """TEST-T2-F07-04: Verify photo slot empty styling and print media hiding in production CSS."""
    css_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "styles" / "asuTech.module.css"
    content = css_file.read_text(encoding="utf-8")
    assert ".photoSlotEmpty" in content
    assert "display: none !important" in content


def test_t2_f07_05_word_break_and_overflow_protection():
    """TEST-T2-F07-05: Verify break-inside and page break rules prevent orphaned elements."""
    css_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "styles" / "asuTech.module.css"
    content = css_file.read_text(encoding="utf-8")
    assert "break-inside: avoid" in content
    assert "page-break-inside: avoid" in content
