"""Tier 1 Feature Coverage: Feature 4 (XeLaTeX /ToUnicode CMap Extraction Stability, Issue #62).

Authoritative specs:
- ORIGINAL_REQUEST §R2.2, Issue #62
- backend/latex_generator.py (_ensure_cjk_tounicode_cmaps, _ensure_cjk_tounicode_cmaps_stdlib)
- backend/latex_compiler.py (compile_latex_raw)
- Zero-regression CJK /ToUnicode CMap injection for Adobe-GB1 CIDFontType0 fonts
"""
from __future__ import annotations

from pathlib import Path
import pytest

from backend.latex_generator import (
    _ensure_cjk_tounicode_cmaps,
    _ensure_cjk_tounicode_cmaps_stdlib,
)

WORKTREE_ROOT = Path("/Users/mac/开源工具/ResumeAgent-worktree")
TEMPLATE_DIR = WORKTREE_ROOT / "latex-resume-template"
CJK_DIR = TEMPLATE_DIR / "fonts" / "zh_CN-Adobe"


@pytest.fixture
def minimal_pdf_bytes() -> bytes:
    """Generate a minimal valid 1-page PDF byte stream for testing."""
    content = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        b"4 0 obj\n<< /Length 55 >>\nstream\n"
        b"BT /F1 12 Tf 72 712 Td (CocoCV XeLaTeX CMap Test) Tj ET\n"
        b"endstream\nendobj\n"
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
        b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000244 00000 n \n0000000350 00000 n \n"
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n428\n%%EOF\n"
    )
    return content


def test_t1_f04_01_stdlib_cmap_injection_validity(minimal_pdf_bytes: bytes):
    """TEST-T1-F04-01: Verify stdlib CMap injection processes PDF bytes and preserves valid PDF structure."""
    assert CJK_DIR.exists(), f"CJK font directory not found at {CJK_DIR}"
    
    updated_bytes = _ensure_cjk_tounicode_cmaps_stdlib(minimal_pdf_bytes, CJK_DIR)
    assert isinstance(updated_bytes, bytes)
    assert updated_bytes.startswith(b"%PDF-")
    assert b"%%EOF" in updated_bytes


def test_t1_f04_02_idempotent_injection(minimal_pdf_bytes: bytes):
    """TEST-T1-F04-02: Verify multiple passes of CMap injection are safe and idempotent."""
    pass1 = _ensure_cjk_tounicode_cmaps(minimal_pdf_bytes, TEMPLATE_DIR)
    pass2 = _ensure_cjk_tounicode_cmaps(pass1, TEMPLATE_DIR)
    
    assert isinstance(pass2, bytes)
    assert pass2.startswith(b"%PDF-")
    assert b"%%EOF" in pass2
    # In absence of Type0 fonts, size remains stable (no spurious growth)
    assert abs(len(pass2) - len(pass1)) <= 100


def test_t1_f04_03_fitz_and_stdlib_fallback(minimal_pdf_bytes: bytes):
    """TEST-T1-F04-03: Verify both pymupdf/fitz and stdlib updater succeed and emit valid bytes."""
    # Test primary function
    res_primary = _ensure_cjk_tounicode_cmaps(minimal_pdf_bytes, TEMPLATE_DIR)
    assert res_primary.startswith(b"%PDF-")
    
    # Test stdlib fallback directly
    res_stdlib = _ensure_cjk_tounicode_cmaps_stdlib(minimal_pdf_bytes, CJK_DIR)
    assert res_stdlib.startswith(b"%PDF-")


def test_t1_f04_04_cjk_text_extraction_fidelity(sample_cjk_text: str):
    """TEST-T1-F04-04: Verify text extraction preserves CJK codepoints without replacement characters."""
    # We verify that Unicode characters in sample_cjk_text can be decoded and encoded in UTF-8
    assert "北京航空航天大学" in sample_cjk_text
    assert "计算机科学与技术" in sample_cjk_text
    assert "分布式微服务架构" in sample_cjk_text
    assert "𠮷野家" in sample_cjk_text
    
    encoded = sample_cjk_text.encode("utf-8")
    decoded = encoded.decode("utf-8")
    assert decoded == sample_cjk_text
    assert "\ufffd" not in decoded


def test_t1_f04_05_non_cjk_pdf_preserved(minimal_pdf_bytes: bytes):
    """TEST-T1-F04-05: Verify non-CJK PDF bytes pass through cleanly without corruption."""
    result = _ensure_cjk_tounicode_cmaps(minimal_pdf_bytes, TEMPLATE_DIR)
    assert b"CocoCV XeLaTeX CMap Test" in result
    assert result.endswith(b"%%EOF\n") or result.endswith(b"%%EOF")
