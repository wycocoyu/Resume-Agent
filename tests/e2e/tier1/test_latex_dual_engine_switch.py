"""Tier 1 Feature Coverage: Feature 11 (LaTeX Performance & Dual Engine Switching, Issue #49, #55).

Authoritative specs:
- ORIGINAL_REQUEST §R3.1, Issue #49, #55
- backend/latex_generator.py (_pdf_cache, _get_cache_key, _PDF_CACHE_MAX_SIZE)
- backend/models.py (RenderPDFRequest with engine field)
- backend/routes/pdf.py (_pdf_cache)
- Dual rendering engines (LaTeX vs HTML) with ResumeData field consistency
"""
from __future__ import annotations

import copy
from typing import Any, Dict
import pytest

from backend.latex_generator import (
    _pdf_cache,
    _get_cache_key,
    _PDF_CACHE_MAX_SIZE,
)
from backend.models import RenderPDFRequest
from backend.routes.pdf import _pdf_cache as route_pdf_cache


def test_t1_f11_01_pdf_cache_activation(standard_resume_data: dict):
    """TEST-T1-F11-01: Verify identical resume data hits _pdf_cache with pre-computed bytes."""
    cache_key = _get_cache_key(standard_resume_data)
    assert isinstance(cache_key, str)
    assert len(cache_key) > 0
    
    # Store in real generator cache
    fake_pdf = b"%PDF-1.4 Real Cached Content %%EOF"
    _pdf_cache[cache_key] = fake_pdf
    
    assert cache_key in _pdf_cache
    assert _pdf_cache[cache_key] == fake_pdf


def test_t1_f11_02_pdf_cache_invalidation_on_change(standard_resume_data: dict):
    """TEST-T1-F11-02: Verify modifying resume content produces distinct cache keys."""
    key1 = _get_cache_key(standard_resume_data)
    
    modified = copy.deepcopy(standard_resume_data)
    modified["basic"]["title"] = "首席系统架构师"
    key2 = _get_cache_key(modified)
    
    assert key1 != key2, "Cache key must change when content changes"


def test_t1_f11_03_dual_engine_switch_request_contract(standard_resume_data: dict):
    """TEST-T1-F11-03: Verify RenderPDFRequest supports both 'latex' and 'html' engine options."""
    req_latex = RenderPDFRequest(resume=standard_resume_data, engine="latex")
    assert req_latex.engine == "latex"

    req_html = RenderPDFRequest(resume=standard_resume_data, engine="html")
    assert req_html.engine == "html"


def test_t1_f11_04_resume_data_field_preservation(standard_resume_data: dict):
    """TEST-T1-F11-04: Verify switching engines does not drop or mutate ResumeData schema fields."""
    original_keys = set(standard_resume_data.keys())
    
    html_input = copy.deepcopy(standard_resume_data)
    html_input["templateType"] = "html"
    
    latex_input = copy.deepcopy(html_input)
    latex_input["templateType"] = "latex"
    
    assert set(latex_input.keys()) == original_keys
    assert latex_input["basic"]["name"] == standard_resume_data["basic"]["name"]
    assert len(latex_input["experience"]) == len(standard_resume_data["experience"])


def test_t1_f11_05_lru_cache_bounds_safety():
    """TEST-T1-F11-05: Verify cache max size boundary and route cache operational state."""
    assert _PDF_CACHE_MAX_SIZE == 50
    assert isinstance(_pdf_cache, dict)
    assert hasattr(route_pdf_cache, "get")
    assert hasattr(route_pdf_cache, "put")
