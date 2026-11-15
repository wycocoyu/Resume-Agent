"""Tier 1 Feature Coverage: Feature 13 (Target JD Matching & 3D Radar Analysis, Issue #54).

Authoritative specs:
- ORIGINAL_REQUEST §R3.3, Issue #54
- backend/services/scoring_service.py (ScoringService)
- backend/routes/resume.py (/api/resume/score)
- 3 dimensions: 技能与经验匹配 (40%), 教育背景匹配 (20%), 项目与整体匹配 (40%)
"""
from __future__ import annotations

import inspect
from pathlib import Path
import pytest

from backend.services.scoring_service import ScoringService


def test_t1_f13_01_scoring_service_interface_contract():
    """TEST-T1-F13-01: Verify ScoringService exposes required scoring methods."""
    assert hasattr(ScoringService, "score_resume")
    assert hasattr(ScoringService, "_score_skill_experience")
    assert hasattr(ScoringService, "_score_education")
    assert hasattr(ScoringService, "_score_project_overall")
    
    sig = inspect.signature(ScoringService.score_resume)
    params = list(sig.parameters.keys())
    assert "self" in params
    assert "resume_id" in params
    assert "jd_text" in params


def test_t1_f13_02_scoring_dimensions_and_weight_formula():
    """TEST-T1-F13-02: Verify multi-dimension scoring weights (40% skill/exp, 20% edu, 40% project)."""
    source = inspect.getsource(ScoringService.score_resume)
    assert "0.4" in source, "Expected 40% weight factor"
    assert "0.2" in source, "Expected 20% weight factor"
    assert "overall_score" in source
    assert "技能与经验匹配" in source
    assert "教育背景匹配" in source
    assert "项目与整体匹配" in source


def test_t1_f13_03_score_route_contract(e2e_client):
    """TEST-T1-F13-03: Verify /api/resume/score endpoint route contract."""
    # Sending request without auth / nonexistent resume returns 401 or 404 cleanly from real FastAPI route
    response = e2e_client.post(
        "/api/resume/score",
        json={"resume_id": "nonexistent_resume_id", "jd_text": "Python FastAPI Developer"}
    )
    assert response.status_code in (401, 403, 404, 422), f"Unexpected status: {response.status_code}"


def test_t1_f13_04_target_jd_sample_fixture_validity(sample_jd_text: str):
    """TEST-T1-F13-04: Verify sample target JD fixture contains required technical requirements."""
    assert len(sample_jd_text) > 100
    assert "Python" in sample_jd_text or "架构" in sample_jd_text or "开发" in sample_jd_text


def test_t1_f13_05_score_service_database_dependency():
    """TEST-T1-F13-05: Verify ScoringService accepts and stores real SQLAlchemy session."""
    from backend.database import SessionLocal
    db = SessionLocal()
    try:
        service = ScoringService(db)
        assert service.db is db
    finally:
        db.close()
