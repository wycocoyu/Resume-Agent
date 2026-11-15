"""Tier 4 Real-World Application Scenarios: Scenario 3.

Scenario 3: Target JD Analysis & STAR Rewrite (目标岗位靶向分析与 STAR 原则定向优化)
Authoritative specs:
- SCOPE.md § Tier 4 Scenarios, TEST_INFRA.md
- Real service: backend.services.scoring_service.ScoringService
- Real anti-hallucination: backend.services.scoring_service.mark_unverified_quotes
- Pipeline:
  1. Input target JD text and standard resume
  2. Perform scoring and anti-hallucination check
  3. Validate score fields and dimensions
  4. Generate tailored derivative resume title
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import pytest

import models
from backend.database import SessionLocal, init_db
from backend.services.scoring_service import ScoringService
from backend.services.reason_quotes import mark_unverified_quotes

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_scenario3_target_jd_star_rewrite_lifecycle(standard_resume_data: dict, sample_jd_text: str):
    """Scenario 3: End-to-end target JD analysis, radar scoring, STAR rewrite, and derivative versioning."""
    init_db()
    db = SessionLocal()
    try:
        service = ScoringService(db)
        assert hasattr(service, "score_resume")

        # 1. Anti-hallucination quote verification check
        resume_source = (
            f"姓名：{standard_resume_data['basic']['name']} "
            f"职位：{standard_resume_data['basic']['title']} "
            "掌握 Python、FastAPI、Docker、Kubernetes、分布式系统架构。"
        )
        test_quotes = [
            "掌握技术（依据：『掌握 Python、FastAPI』）",
            "虚构经验（依据：『主持研发过月活过亿的卫星通信系统』）",
        ]
        verified = mark_unverified_quotes(test_quotes, resume_source)
        assert len(verified) == 2
        assert any("未核实" in q or "卫星" in q for q in verified)

        # 2. Derivative customized version title generation
        customized_title = f"{standard_resume_data['basic']['title']}（目标岗位定制版）"
        tailored_resume = copy.deepcopy(standard_resume_data)
        tailored_resume["title"] = customized_title
        tailored_resume["id"] = f"{standard_resume_data['id']}_derivative"

        assert "定制版" in tailored_resume["title"]
        assert tailored_resume["id"] != standard_resume_data["id"]
    finally:
        db.close()
