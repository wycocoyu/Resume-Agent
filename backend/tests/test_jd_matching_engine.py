"""Unit tests for Job Description (JD) matching engine and 3D radar analysis.

Feature 18 / Issue #54.
100% deterministic, 0 external API key dependencies.
"""
from __future__ import annotations

import pytest
from backend.services.jd_matcher import (
    JdMatchingEngine,
    ParsedJd,
    RadarScore,
    TechnicalMatchResult,
    ProjectMatchResult,
    ExperienceMatchResult,
    JdMatchResponse,
)


@pytest.fixture
def engine():
    return JdMatchingEngine()


@pytest.fixture
def sample_jd_text():
    return """
    职位名称：资深 Go 后端研发架构师
    工作职责：
    1. 负责亿级高并发电商核心交易链路的架构设计与持续重构。
    2. 主导微服务体系建设，落地分布式缓存与异步消息队列方案。
    3. 负责高可用保障与性能调优，支撑 QPS 突破 10 万。

    任职要求：
    1. 本科及以上学历，计算机相关专业，至少 5 年以上后端研发经验。
    2. 精通 Go 语言，熟悉 Linux、Docker、Kubernetes 等容器化技术。
    3. 深入理解 MySQL、Redis、Kafka、Elasticsearch 核心原理并有丰富实战调优经验。
    4. 具备大规模分布式系统、高并发高可用架构设计落地经验，熟悉微服务架构。

    加分项：
    1. 熟悉 RAG、LLM 等 AI 应用工程化落地的候选人优先。
    2. 有开源项目贡献或技术团队管理经验者优先。
    """


@pytest.fixture
def sample_candidate_resume():
    return {
        "basic": {
            "name": "李四",
            "title": "资深后端开发工程师",
            "email": "lisi@example.com",
            "phone": "13800000000",
        },
        "skills": [
            "精通 Go, Python, SQL 编程",
            "熟练使用 Docker, Kubernetes, Linux",
            "精通 MySQL, Redis, Kafka, Elasticsearch",
            "熟悉分布式系统架构与高并发性能优化",
        ],
        "education": [
            {
                "school": "浙江大学",
                "major": "计算机科学与技术",
                "degree": "硕士",
                "period": "2016.09 - 2019.06",
            }
        ],
        "experience": [
            {
                "company": "某头部电商集团",
                "title": "高级 Go 研发工程师",
                "period": "2019.07 - 至今",
                "details": "负责电商交易中台订单模块，使用 Go 重构订单状态机，优化 MySQL 慢查询并引入 Redis 多级缓存，支撑核心链路 QPS 提升 40%，响应耗时降低 35ms。",
            }
        ],
        "projects": [
            {
                "name": "高并发分布式订单结算系统",
                "role": "核心研发负责人",
                "technologies": "Go, Docker, K8s, Redis, Kafka, MySQL",
                "details": "针对双十一大促秒杀高并发流量场景，基于 Go 与 Kafka 实现异步削峰填谷，结合 Redis 分布式锁保障库存强一致性，支撑峰值 QPS 达 50000+，零资损故障。",
            }
        ],
    }


def test_parse_jd_structured(engine: JdMatchingEngine, sample_jd_text: str):
    """Verify structured parsing of JD text."""
    parsed = engine.parse_jd(sample_jd_text)
    assert "架构师" in parsed.title or "Go" in parsed.title
    assert parsed.experience_years == 5.0
    assert parsed.degree == "本科"
    assert parsed.seniority in ("senior", "lead")
    assert "Go" in parsed.required_skills
    assert "Kubernetes" in parsed.required_skills
    assert "Redis" in parsed.required_skills
    assert "RAG" in parsed.preferred_skills or "LLM" in parsed.preferred_skills
    assert any("电商" in dk for dk in parsed.domain_keywords)
    assert len(parsed.responsibilities) >= 2


def test_parse_jd_intern_fresh(engine: JdMatchingEngine):
    """Verify intern / fresh graduate parsing defaults years to 0.0 and seniority to junior/intern."""
    jd = "招聘前端开发实习生，在校生或应届生优先，熟悉 React 与 JavaScript。"
    parsed = engine.parse_jd(jd)
    assert parsed.experience_years == 0.0
    assert parsed.seniority in ("intern", "junior")
    assert "React" in parsed.required_skills
    assert "JavaScript" in parsed.required_skills


def test_3d_radar_matching(engine: JdMatchingEngine, sample_jd_text: str, sample_candidate_resume: dict):
    """Verify 3D radar score computation and dimension bounds."""
    parsed_jd = engine.parse_jd(sample_jd_text)
    match_res = engine.calculate_3d_match(sample_candidate_resume, parsed_jd)

    assert 0 <= match_res.overall_score <= 100
    assert 0 <= match_res.radar.technical_score <= 100
    assert 0 <= match_res.radar.project_score <= 100
    assert 0 <= match_res.radar.experience_score <= 100

    # Candidate has Go, Docker, K8s, Redis, Kafka, MySQL and 5+ years with Master degree
    assert match_res.radar.technical_score >= 80
    assert match_res.radar.experience_score >= 85
    assert match_res.radar.project_score >= 60

    # Technical match details
    assert "Go" in match_res.technical_match.matched_skills
    assert "Redis" in match_res.technical_match.matched_skills
    assert match_res.technical_match.skill_coverage >= 0.7

    # Experience match details
    assert match_res.experience_match.degree_matched is True
    assert match_res.experience_match.candidate_years >= 5.0


@pytest.mark.anyio
async def test_deterministic_star_rewrites(
    engine: JdMatchingEngine, sample_jd_text: str, sample_candidate_resume: dict
):
    """Verify deterministic STAR rewrite synthesis and keyword alignment."""
    fields = [
        {
            "key": "experience:0:details",
            "label": "工作经历",
            "content": "负责电商交易中台订单模块，使用 Go 重构订单状态机，优化 MySQL 慢查询并引入 Redis 多级缓存，支撑核心链路 QPS 提升 40%，响应耗时降低 35ms。",
        },
        {
            "key": "experience:1:details",
            "label": "项目经历",
            "content": "负责微服务消息通信组件开发，完成消息投递功能。",
        },
    ]
    suggestions = await engine.generate_star_rewrites(
        jd_text=sample_jd_text,
        fields=fields,
    )
    assert len(suggestions) >= 1
    first = suggestions[0]
    assert first.original in fields[0]["content"] or first.original in fields[1]["content"]
    assert first.star_breakdown.situation
    assert first.star_breakdown.task
    assert first.star_breakdown.action
    assert first.star_breakdown.result
    assert len(first.quantifiable_metrics) >= 1
