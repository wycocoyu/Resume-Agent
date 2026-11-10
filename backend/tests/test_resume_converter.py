"""Tests for Slice S2 converter parity: backend/resume_converter.py vs convertToBackend.ts & birthDateDisplay.ts."""
from __future__ import annotations

from datetime import date

from backend.cli.schema import build_initial_resume
from backend.resume_converter import (
    collapse_duplicate_contact_segments,
    convert_to_backend_format,
    get_age_from_birth_date,
    resolve_employment_status_for_render,
    strip_html_tags,
)


def test_strip_html_tags_matches_frontend_text_utils() -> None:
    assert strip_html_tags("<div>Hello<br/>World</div><p>Next</p>") == "Hello World Next"
    assert strip_html_tags("  <strong>字节跳动</strong>  ") == "字节跳动"
    assert strip_html_tags("") == ""


def test_birth_date_and_employment_status_deduplication() -> None:
    ref_day = date(2026, 11, 9)
    assert get_age_from_birth_date("2002-05", today=ref_day) == 24
    assert get_age_from_birth_date("2002-12-15", today=ref_day) == 23
    assert collapse_duplicate_contact_segments("24 岁 · 24岁") == "24 岁"

    # Pure age/date status is stripped when birthDate is present (computed fresh by backend)
    assert resolve_employment_status_for_render("23岁", "2002-05", "age", today=ref_day) is None
    assert resolve_employment_status_for_render("2002-05", "2002-05", "birthDate", today=ref_day) is None
    # Status duplicating birth text is stripped
    assert resolve_employment_status_for_render("男 · 24岁", "2002-05", "age", today=ref_day) is None
    # Distinct employment status is preserved
    assert (
        resolve_employment_status_for_render("随时到岗 · 随时到岗", "2002-05", "age", today=ref_day)
        == "随时到岗"
    )


def test_convert_to_backend_format_full_field_and_visibility_invariants() -> None:
    resume = build_initial_resume(title="测试简历")
    resume["basic"].update(
        {
            "name": "李四",
            "title": "高级后端工程师",
            "email": "lisi@example.com",
            "phone": "13900001111",
            "location": "深圳",
            "birthDate": "2000-06",
            "employementStatus": "在职-考虑机会",
            "workYears": "3年经验",
            "blog": "https://github.com/lisi",
            "photoOffsetX": 0,
            "photoOffsetY": -1.5,
            "photoWidthCm": 2.8,
            "photoHeightCm": 3.5,
        }
    )
    resume["selfEvaluation"] = "<p>热爱分布式系统。</p>"
    resume["skillContent"] = "<ul><li><p>熟悉 Python / Go</p></li></ul>"
    resume["workExperience"] = [
        {
            "id": "w1",
            "company": "<div>腾讯</div>",
            "position": "后端开发",
            "date": "2024.07 - 至今",
            "details": "<p>负责微服务架构</p>",
            "visible": True,
            "companyLogo": "tencent",
            "companyLogoSize": 22,
            "companyNameFontSize": 16,
        },
        {
            "id": "w2",
            "company": "隐藏公司",
            "position": "工程师",
            "date": "2023",
            "details": "<p>不应出现</p>",
            "visible": False,
        },
    ]
    resume["experience"] = [
        {
            "id": "e1",
            "company": "字节跳动",
            "position": "后端实习生",
            "date": "2023.06 - 2023.10",
            "details": "<p>优化缓存</p>",
            "visible": True,
            "companyLogo": "bytedance",
        }
    ]
    resume["projects"] = [
        {
            "id": "p1",
            "name": "<p>RPC 框架</p>",
            "role": "核心作者",
            "date": "2024.01",
            "description": "<ul><li>零拷贝优化</li></ul>",
            "visible": True,
            "link": "  https://github.com/lisi/rpc  ",
            "projectNameFontSize": 15,
            "projectLinkFontSize": 12,
        },
        {
            "id": "p2",
            "name": "隐藏项目",
            "role": "成员",
            "date": "2022",
            "description": "<p>隐藏</p>",
            "visible": False,
        },
    ]
    resume["openSource"] = [
        {
            "id": "os1",
            "name": "Resume-Agent",
            "role": "Maintainer",
            "repo": "https://github.com/wycocoyu/Resume-Agent",
            "date": "2026",
            "description": "<p>CLI 与 Skill 支持</p>",
            "visible": True,
        }
    ]
    resume["awards"] = [
        {
            "id": "a1",
            "title": "<strong>ACM 金奖</strong>",
            "issuer": "ICPC",
            "date": "2022.11",
            "description": "亚洲区域赛第 5 名",
            "visible": True,
        }
    ]
    resume["education"] = [
        {
            "id": "edu1",
            "school": "北京大学",
            "major": "计算机科学与技术",
            "degree": "硕士",
            "startDate": "2021.09",
            "endDate": "2024.06",
            "description": "<p>GPA 3.9/4.0</p>",
            "schoolLogo": "北京大学",
            "schoolLogoSize": 20,
            "visible": True,
        }
    ]
    resume["customData"] = {
        "custom_research": [
            {
                "id": "c1",
                "title": "<p>分布式一致性论文</p>",
                "subtitle": "第一作者",
                "dateRange": "2023",
                "description": "<p>发表于 FAST</p>",
                "visible": True,
            },
            {
                "id": "c2",
                "title": "隐藏科研",
                "subtitle": "",
                "dateRange": "",
                "description": "<p>隐藏</p>",
                "visible": False,
            },
        ]
    }
    # Disable awards section in menuSections
    for sec in resume["menuSections"]:
        if sec["id"] == "awards":
            sec["enabled"] = False
        if sec["id"] == "openSource":
            sec["title"] = "开源贡献"

    out = convert_to_backend_format(resume, today=date(2026, 11, 9))

    assert out["name"] == "李四"
    assert out["objective"] == "高级后端工程师"
    assert out["contact"] == {"phone": "13900001111", "email": "lisi@example.com", "location": "深圳"}
    # photoOffsetX == 0 must be preserved (numeric zero is valid in JS typeof === 'number')
    assert out["photoOffsetX"] == 0
    assert out["photoOffsetY"] == -1.5
    assert out["employementStatus"] == "在职-考虑机会"
    assert out["workYears"] == "3年经验"
    assert out["blog"] == "https://github.com/lisi"

    # Dual write for skillContent + skills
    assert out["skillContent"] == "<ul><li><p>熟悉 Python / Go</p></li></ul>"
    assert out["skills"] == [{"category": "", "details": "<ul><li><p>熟悉 Python / Go</p></li></ul>"}]

    # Separate workExperience and internships, hidden entries filtered
    assert len(out["workExperience"]) == 1
    assert out["workExperience"][0]["title"] == "腾讯"
    assert out["workExperience"][0]["logo"] == "tencent"
    assert out["workExperience"][0]["logoSize"] == 22
    assert len(out["internships"]) == 1
    assert out["internships"][0]["title"] == "字节跳动"
    assert out["internships"][0]["logo"] == "bytedance"

    # Projects & open_source single-element list preservation
    assert len(out["projects"]) == 1
    assert out["projects"][0]["title"] == "RPC 框架"
    assert out["projects"][0]["link"] == "https://github.com/lisi/rpc"
    assert out["projects"][0]["highlights"] == ["<ul><li>零拷贝优化</li></ul>"]
    assert out["open_source"][0]["items"] == ["<p>CLI 与 Skill 支持</p>"]

    # Awards title stripped, description kept verbatim
    assert out["awards"][0]["title"] == "ACM 金奖"
    assert out["awards"][0]["description"] == "亚洲区域赛第 5 名"

    # Education date joined and logo mapped
    assert out["education"][0]["date"] == "2021.09 - 2024.06"
    assert out["education"][0]["logo"] == "北京大学"
    assert out["education"][0]["details"] == ["<p>GPA 3.9/4.0</p>"]

    # Custom data visibility filtering
    assert len(out["customData"]["custom_research"]) == 1
    assert out["customData"]["custom_research"][0]["title"] == "分布式一致性论文"

    # Section order & section titles mapping
    assert "basic" not in out["sectionOrder"]
    assert "awards" not in out["sectionOrder"]
    assert out["sectionOrder"] == [
        "education",
        "workExperience",
        "internships",
        "projects",
        "open_source",
        "skills",
        "summary",
        "custom_research",
    ]
    assert out["sectionTitles"]["openSource"] == "开源贡献"
    assert out["sectionTitles"]["open_source"] == "开源贡献"
    assert out["sectionTitles"]["opensource"] == "开源贡献"
