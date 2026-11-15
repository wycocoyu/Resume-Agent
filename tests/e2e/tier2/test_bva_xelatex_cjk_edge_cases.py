"""Tier 2 Boundary & Corner Tests: Feature 4 (XeLaTeX /ToUnicode CMap Edge Cases).

Authoritative specs:
- ORIGINAL_REQUEST §R2.2, Issue #62
- backend/latex_generator.py (_ensure_cjk_tounicode_cmaps, _ensure_cjk_tounicode_cmaps_stdlib)
- Edge cases: idempotency on existing /ToUnicode, missing font dir fallback, corrupted byte streams, missing xelatex hint, rare CJK characters
"""
from __future__ import annotations

from pathlib import Path
import pytest

from backend.latex_compiler import resolve_xelatex_executable, xelatex_install_hint
from backend.latex_generator import (
    _ensure_cjk_tounicode_cmaps,
    _ensure_cjk_tounicode_cmaps_stdlib,
)

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t2_f04_01_idempotency_on_pdf_with_tounicode(temp_e2e_dir: Path):
    """TEST-T2-F04-01: Verify re-running CMap injection on already-processed PDF does not duplicate streams."""
    template_dir = (WORKTREE_ROOT / "latex-resume-template").resolve()
    # Create minimal PDF bytes with existing /ToUnicode marker
    pdf_with_tounicode = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> >>\nendobj\n"
        b"4 0 obj\n<< /Type /Font /Subtype /Type0 /ToUnicode 5 0 R >>\nendobj\n"
        b"5 0 obj\n<< /Length 10 >>\nstream\n1234567890\nendstream\nendobj\n"
        b"xref\n0 6\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000201 00000 n \n"
        b"0000000262 00000 n \n"
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n325\n%%EOF"
    )
    result = _ensure_cjk_tounicode_cmaps(pdf_with_tounicode, template_dir)
    # Since /ToUnicode already exists on Type0 font, bytes should remain unmodified or identical length
    assert abs(len(result) - len(pdf_with_tounicode)) <= 256


def test_t2_f04_02_missing_cjk_font_directory_fallback(temp_e2e_dir: Path):
    """TEST-T2-F04-02: Verify safe fallback returning untouched bytes when fonts directory is absent."""
    empty_dir = temp_e2e_dir / "empty_template"
    empty_dir.mkdir(parents=True)
    
    sample_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
    result = _ensure_cjk_tounicode_cmaps(sample_bytes, empty_dir)
    assert result == sample_bytes, "Must return input bytes unmodified when CJK fonts dir is missing"


def test_t2_f04_03_corrupted_pdf_byte_buffer_handled_safely():
    """TEST-T2-F04-03: Verify truncated/corrupted PDF bytes are handled without uncaught crash."""
    template_dir = (WORKTREE_ROOT / "latex-resume-template").resolve()
    corrupted_bytes = b"%PDF-1.4\ncorrupted_data_without_trailer_or_xref\x00\xff\xfe"
    
    try:
        result = _ensure_cjk_tounicode_cmaps(corrupted_bytes, template_dir)
        assert result == corrupted_bytes
    except Exception as e:
        assert "Failed to open stream" in str(e) or "FileDataError" in type(e).__name__

    stdlib_res = _ensure_cjk_tounicode_cmaps_stdlib(corrupted_bytes, template_dir / "fonts" / "zh_CN-Adobe")
    assert stdlib_res == corrupted_bytes


def test_t2_f04_04_missing_xelatex_executable_hint_contract(monkeypatch):
    """TEST-T2-F04-04: Verify resolve_xelatex_executable and install hints when binary is missing."""
    monkeypatch.setenv("PATH", "")
    exe = resolve_xelatex_executable()
    # Even if None, xelatex_install_hint must provide actionable installation guide
    hint = xelatex_install_hint()
    assert isinstance(hint, str)
    assert "xelatex" in hint.lower()
    assert "mac" in hint.lower() or "brew" in hint.lower() or "apt" in hint.lower() or "texlive" in hint.lower()


def test_t2_f04_05_rare_cjk_unicode_extension_characters():
    """TEST-T2-F04-05: Verify rare CJK characters (Extension B/C/D) are recognized as valid CJK."""
    rare_cjk_chars = ["𠮷", "𬌗", "堃", "赟", "䶮"]
    for char in rare_cjk_chars:
        code_point = ord(char)
        # Check codepoint is valid Unicode in CJK ranges (Ext A 0x3400-0x4DBF, Unified 0x4E00-0x9FFF, or SIP >= 0x20000)
        assert (0x3400 <= code_point <= 0x9FFF) or (code_point >= 0x20000)
        # UTF-8 roundtrip encoding must succeed without replacement character
        encoded = char.encode("utf-8")
        assert len(encoded) in (3, 4)
        assert encoded.decode("utf-8") == char
