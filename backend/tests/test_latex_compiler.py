"""
Tests for XeLaTeX /ToUnicode CMap Zero-Regression Wrapper in backend/latex_compiler.py and backend/latex_generator.py.
Covers Issue #62 and Milestone 2 specification.
"""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
import pytest
import pymupdf as fitz

from backend.latex_compiler import compile_latex as compiler_compile_latex, compile_latex_raw
from backend.latex_generator import compile_latex as generator_compile_latex, compile_latex_to_pdf, json_to_latex
from backend.latex_utils import resolve_xelatex_executable

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = WORKTREE_ROOT / "latex-resume-template"


@pytest.fixture
def sample_cjk_latex() -> str:
    resume = {
        "name": "张三",
        "contact": {"phone": "13800138000", "email": "zhangsan@cococv.com", "location": "北京"},
        "education": [
            {
                "title": "清华大学",
                "subtitle": "计算机科学与技术",
                "degree": "硕士",
                "date": "2020.9-2023.7",
                "details": ["主修课程：分布式系统、高级计算机体系结构"],
            }
        ],
        "experience": [
            {
                "company": "字节跳动",
                "position": "高级后端工程师",
                "date": "2023.7-至今",
                "highlights": ["主导微服务架构升级与高并发中间件研发"],
            }
        ],
    }
    return json_to_latex(resume, ["education", "experience"])


@pytest.mark.skipif(not resolve_xelatex_executable(), reason="xelatex executable not found")
def test_compile_latex_raw_injects_tounicode_cmaps(sample_cjk_latex: str):
    """Verify that low-level compile_latex_raw injects /ToUnicode CMaps and extracts CJK text."""
    pdf_io = compile_latex_raw(sample_cjk_latex)
    assert isinstance(pdf_io, BytesIO)
    pdf_bytes = pdf_io.getvalue()
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"%%EOF" in pdf_bytes

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        assert doc.page_count >= 1
        page_text = doc[0].get_text()
        assert "张三" in page_text
        assert "清华大学" in page_text
        assert "计算机科学与技术" in page_text
        assert "字节跳动" in page_text

        # Verify all Type0 fonts have /ToUnicode
        type0_found = False
        for xref in range(1, doc.xref_length()):
            obj_str = doc.xref_object(xref)
            if "/Subtype /Type0" in obj_str:
                type0_found = True
                assert "/ToUnicode" in obj_str, f"Type0 font XREF {xref} missing /ToUnicode"
        assert type0_found, "Expected at least one Type0 CJK font in compiled PDF"


@pytest.mark.skipif(not resolve_xelatex_executable(), reason="xelatex executable not found")
def test_compile_latex_alias_in_compiler(sample_cjk_latex: str):
    """Verify compile_latex imported from latex_compiler guarantees CJK /ToUnicode CMap extraction."""
    pdf_io = compiler_compile_latex(sample_cjk_latex)
    pdf_bytes = pdf_io.getvalue()

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        extracted = doc[0].get_text()
        assert "张三" in extracted
        assert "清华大学" in extracted

        for xref in range(1, doc.xref_length()):
            obj_str = doc.xref_object(xref)
            if "/Subtype /Type0" in obj_str:
                assert "/ToUnicode" in obj_str


@pytest.mark.skipif(not resolve_xelatex_executable(), reason="xelatex executable not found")
def test_compile_latex_alias_in_generator(sample_cjk_latex: str):
    """Verify compile_latex imported from latex_generator acts as compile_latex_to_pdf with CMap injection."""
    pdf_io = generator_compile_latex(sample_cjk_latex, TEMPLATE_DIR, offline=True)
    pdf_bytes = pdf_io.getvalue()

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        extracted = doc[0].get_text()
        assert "张三" in extracted

        for xref in range(1, doc.xref_length()):
            obj_str = doc.xref_object(xref)
            if "/Subtype /Type0" in obj_str:
                assert "/ToUnicode" in obj_str


def test_compile_latex_raw_malformed_input():
    """Verify that syntax errors in compile_latex_raw raise RuntimeError with compiler log."""
    bad_latex = r"\documentclass{resume} \begin{document} \invalidcommand{test} \end{document}"
    with pytest.raises(RuntimeError) as exc_info:
        compile_latex_raw(bad_latex)
    assert "LaTeX 编译失败" in str(exc_info.value) or "Undefined" in str(exc_info.value)


@pytest.mark.skipif(not resolve_xelatex_executable(), reason="xelatex executable not found")
def test_compile_latex_raw_stdlib_fallback_layer(sample_cjk_latex: str, monkeypatch: pytest.MonkeyPatch):
    """Verify compile_latex_raw injects /ToUnicode CMaps via stdlib fallback when pymupdf is absent."""
    monkeypatch.setitem(sys.modules, "pymupdf", None)
    monkeypatch.setitem(sys.modules, "fitz", None)

    pdf_io = compile_latex_raw(sample_cjk_latex)
    pdf_bytes = pdf_io.getvalue()
    monkeypatch.undo()

    assert pdf_bytes.startswith(b"%PDF-")
    assert b"%%EOF" in pdf_bytes

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        extracted = doc[0].get_text()
        assert "张三" in extracted
        assert "清华大学" in extracted

        type0_xrefs = [
            xref
            for xref in range(1, doc.xref_length())
            if "/Subtype /Type0" in doc.xref_object(xref)
        ]
        assert type0_xrefs
        for xref in type0_xrefs:
            assert "/ToUnicode" in doc.xref_object(xref)
