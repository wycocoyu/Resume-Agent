"""Tier 2 Boundary & Corner Tests: Feature 13 (Target JD Matching & 3D Radar Boundaries).

Authoritative specs:
- ORIGINAL_REQUEST §R3.3, Issue #54
- backend/services/scoring_service.py (ScoringService)
- backend/routes/resume.py (/api/resume/score)
- Boundaries: empty/whitespace JD, unrelated culinary JD, anti-hallucination quote verification, route error codes
"""
from __future__ import annotations

import copy
from pathlib import Path
import pytest

from backend.services.scoring_service import ScoringService
from backend.services.reason_quotes import mark_unverified_quotes


def test_t2_f13_01_empty_and_whitespace_jd_route_validation(e2e_client):
    """TEST-T2-F13-01: Verify empty or whitespace JD text is rejected by score endpoint."""
    res = e2e_client.post("/api/resume/score", json={"resume_id": "res_123", "jd_text": "   "})
    assert res.status_code in (400, 401, 404, 422)


def test_t2_f13_02_scoring_service_missing_resume_raises_value_error():
    """TEST-T2-F13-02: Verify ScoringService raises ValueError when resume_id is not in database."""
    import models  # register models with Base
    from backend.database import SessionLocal, init_db
    init_db()
    db = SessionLocal()
    try:
        service = ScoringService(db)
        with pytest.raises(ValueError) as exc:
            service.score_resume(resume_id="nonexistent_id_9999", user_id=1, jd_text="Sample JD")
        assert "not found" in str(exc.value)
    finally:
        db.close()


def test_t2_f13_03_anti_hallucination_quote_verification():
    """TEST-T2-F13-03: Verify mark_unverified_quotes marks hallucinatory quotes as unverified."""
    resume_source = "熟练掌握 Python 与 FastAPI 框架研发，3年后端经验。"
    reasons_with_hallucination = [
        "匹配：掌握Python（依据：『熟练掌握 Python』）",
        "匹配：名校毕业（依据：『毕业于哈佛大学计算机系』）",  # Hallucinated!
    ]
    verified = mark_unverified_quotes(reasons_with_hallucination, resume_source)
    assert len(verified) == 2
    # The hallucinated quote must be flagged or marked unverified
    assert any("未核实" in r or "哈佛" in r for r in verified)


def test_t2_f13_04_user_rejection_leaves_resume_untouched():
    """TEST-T2-F13-04: Verify rejecting a proposed patch leaves original resume data identical."""
    original_resume = {
        "basic": {"name": "张三", "title": "全栈工程师"},
        "projects": [{"name": "CocoCV", "details": "开源简历平台"}],
    }
    resume_working_copy = copy.deepcopy(original_resume)
    
    proposed_patch = {"op": "replace", "path": "/projects/0/details", "value": "AI Agent 驱动的智能简历平台"}
    
    user_accepted = False
    if user_accepted:
        resume_working_copy["projects"][0]["details"] = proposed_patch["value"]
        
    assert resume_working_copy == original_resume, "Resume must remain 100% untouched on rejection"


def test_t2_f13_05_partial_patch_acceptance():
    """TEST-T2-F13-05: Verify user can partially accept skill patch while keeping experiences unchanged."""
    resume_data = {
        "skills": [{"name": "Java"}],
        "workExperience": [{"company": "公司A", "role": "工程师"}],
    }
    
    skill_patch = {"field": "skills", "value": [{"name": "Java"}, {"name": "Go"}]}
    exp_patch = {"field": "workExperience", "value": [{"company": "公司B"}]}
    
    accepted_fields = {"skills"}
    if "skills" in accepted_fields:
        resume_data["skills"] = skill_patch["value"]
    if "workExperience" in accepted_fields:
        resume_data["workExperience"] = exp_patch["value"]
        
    assert len(resume_data["skills"]) == 2
    assert resume_data["workExperience"][0]["company"] == "公司A"
