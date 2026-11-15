"""Integration tests for Job Description (JD) matching endpoints and resume forking.

Feature 18 / Issue #54.
Endpoints:
- POST /api/jd/parse
- POST /api/jd/match
- POST /api/jd/analyze (alias)
- POST /api/jd/star-rewrite
- POST /api/resumes/{resume_id}/fork
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from database import SessionLocal
from middleware.auth import AppUser, get_current_user
from models import Resume


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_user():
    return AppUser(
        id="user_test_m5",
        email="test_m5@example.com",
        name="Test User",
        role="user",
        pdf_download_count=0,
    )


@pytest.fixture
def sample_resume_data():
    return {
        "id": "resume_test_m5_sample",
        "basic": {
            "name": "王五",
            "title": "高级全栈架构师",
            "email": "wangwu@example.com",
            "phone": "13900000000",
        },
        "skills": ["Python", "Go", "React", "Docker", "Kubernetes", "Redis", "MySQL"],
        "education": [
            {
                "school": "清华大学",
                "major": "软件工程",
                "degree": "本科",
                "period": "2015.09 - 2019.06",
            }
        ],
        "experience": [
            {
                "company": "字节跳动",
                "title": "高级研发工程师",
                "period": "2019.07 - 至今",
                "details": "负责微服务基础架构与高并发网关开发，基于 Go 语言重构服务网关，支撑 QPS 提升 50%，平均延迟降低 20ms。",
            }
        ],
        "projects": [
            {
                "name": "云原生微服务管理平台",
                "role": "技术负责人",
                "details": "针对大规模 Kubernetes 集群管理痛点，设计并开发统一控制面，实现服务自动发现与灰度发布。",
            }
        ],
    }


def test_api_jd_parse(client: TestClient):
    """Verify POST /api/jd/parse parses JD requirements."""
    jd_text = """
    招聘职位：资深 Python 后端开发工程师
    工作年限：3-5年经验
    学历要求：本科及以上
    任职要求：
    1. 精通 Python 语言及 FastAPI / Django 框架。
    2. 熟悉 MySQL、Redis、Docker 等基础组件。
    3. 具备高并发系统调优与微服务架构经验。
    """
    res = client.post("/api/jd/parse", json={"jd_text": jd_text})
    assert res.status_code == 200
    data = res.json()
    assert "Python" in data["title"] or "工程师" in data["title"]
    assert "Python" in data["required_skills"]
    assert "FastAPI" in data["required_skills"]
    assert data["experience_years"] == 3.0
    assert data["degree"] == "本科"


def test_api_jd_match_and_analyze(client: TestClient, sample_resume_data: dict):
    """Verify POST /api/jd/match and alias /api/jd/analyze return 3D radar score components."""
    payload = {
        "resume_data": sample_resume_data,
        "jd_text": """
        职位：Go / Python 后端技术专家
        要求：5年以上经验，精通 Go、Python、Kubernetes、Docker、Redis、MySQL，有微服务高并发经验。
        """,
    }
    # Test /api/jd/match
    res = client.post("/api/jd/match", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "overall_score" in data
    assert "radar" in data
    radar = data["radar"]
    assert 0 <= radar["technical_score"] <= 100
    assert 0 <= radar["project_score"] <= 100
    assert 0 <= radar["experience_score"] <= 100

    # Test alias /api/jd/analyze
    res_alias = client.post("/api/jd/analyze", json=payload)
    assert res_alias.status_code == 200
    data_alias = res_alias.json()
    assert data_alias["overall_score"] == data["overall_score"]
    assert data_alias["radar"] == data["radar"]


def test_api_jd_star_rewrite(client: TestClient):
    """Verify POST /api/jd/star-rewrite returns STAR formatted suggestions."""
    payload = {
        "jd_text": "需要熟悉 Go 与 Redis 的微服务架构师，具备高并发秒杀与性能调优实战。",
        "fields": [
            {
                "key": "experience:0:details",
                "label": "工作经历",
                "content": "负责后端订单接口开发，完成业务需求上线。",
            }
        ],
    }
    res = client.post("/api/jd/star-rewrite", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["total_suggestions"] >= 1
    sug = data["suggestions"][0]
    assert sug["original"] in payload["fields"][0]["content"]
    assert sug["star_breakdown"]["situation"]
    assert sug["star_breakdown"]["action"]
    assert sug["star_breakdown"]["result"]


def test_api_resume_fork(client: TestClient, mock_user: AppUser, sample_resume_data: dict):
    """Verify POST /api/resumes/{resume_id}/fork creates a derivative resume."""
    db = SessionLocal()
    source_id = "test_source_resume_001"
    try:
        # Cleanup any existing test record
        db.query(Resume).filter(Resume.id == source_id).delete()
        db.query(Resume).filter(Resume.name.like("%定制版%")).delete()
        db.commit()

        # Seed source resume
        source_resume = Resume(
            id=source_id,
            user_id=mock_user.id,
            name="张三的主简历",
            alias="通用主版",
            data=sample_resume_data,
        )
        db.add(source_resume)
        db.commit()

        # Override user auth
        app.dependency_overrides[get_current_user] = lambda: mock_user

        fork_payload = {
            "target_jd_title": "腾讯微信后端架构师",
            "target_company": "腾讯",
            "custom_name": "张三 - 微信定制版",
            "jd_text": "负责微信支付亿级高并发架构...",
        }
        res = client.post(f"/api/resumes/{source_id}/fork", json=fork_payload)
        assert res.status_code == 200
        data = res.json()
        assert data["id"] != source_id
        assert data["name"] == "张三 - 微信定制版"
        assert "JD定制" in data["alias"]
        assert data["data"]["_meta"]["forkedFrom"] == source_id
        assert data["data"]["_meta"]["targetJd"]["company"] == "腾讯"

        # Verify DB record exists
        forked_in_db = db.query(Resume).filter(Resume.id == data["id"]).first()
        assert forked_in_db is not None
        assert forked_in_db.name == "张三 - 微信定制版"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        # Cleanup
        db.query(Resume).filter(Resume.id == source_id).delete()
        db.query(Resume).filter(Resume.name.like("%定制版%")).delete()
        db.commit()
        db.close()
