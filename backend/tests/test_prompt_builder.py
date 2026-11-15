"""Wave 2a-S2 PromptBuilder golden 对拍:
迁移前用 capture_prompt_golden.py 录制的 7 组合矩阵输出（fixtures/prompt_golden.json），
迁移后 ResumeDomainRuntime._generate_dynamic_prompts（委托 PromptBuilder）必须逐字符一致。
组合覆盖：有/无简历 × 只读 × 新增经历 × office 关键词 × GREETING next-step。
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.core.logger import setup_logging
setup_logging(False, "INFO", "logs/test")

import pytest

from backend.agent.pi_core.resume_domain import ResumeDomainRuntime
from backend.agent.memory import Intent
from backend.agent.tool.resume_data_store import ResumeDataStore

SESSION = "golden-prompt-session"
RESUME = {
    "basic": {"name": "张三", "email": "z@t.com"},
    "experience": [
        {"company": "美团", "position": "后端实习生", "date": "2023.01-2023.06",
         "details": "<ul class=\"custom-list\"><li>负责订单系统</li></ul>"}
    ],
    "projects": [],
}

CASES = [
    {"key": "no_resume_plain", "resume": False, "input": "帮我优化简历", "intent": "UNKNOWN"},
    {"key": "no_resume_readonly", "resume": False, "input": "看看我的简历第一段经历", "intent": "UNKNOWN"},
    {"key": "resume_plain", "resume": True, "input": "帮我优化简历", "intent": "UNKNOWN"},
    {"key": "resume_readonly", "resume": True, "input": "看看我的简历第一段经历", "intent": "UNKNOWN"},
    {"key": "resume_add_exp", "resume": True, "input": "帮我加一段在字节跳动的实习经历", "intent": "UNKNOWN"},
    {"key": "resume_office_pdf", "resume": True, "input": "帮我把简历处理成 pdf 文档", "intent": "UNKNOWN"},
    {"key": "greeting_next_step", "resume": True, "input": "你好", "intent": "GREETING"},
    # spec v2 要求的组合:有 current_resume_path(注意:此 case 在 S2 迁移后录制,
    # 性质是"向前锁定"(保护 S4+ 不破坏),非迁移对拍
    {"key": "resume_with_path", "resume": True, "input": "帮我优化简历",
     "intent": "UNKNOWN", "resume_path": "/tmp/my_resume.pdf"},
]

GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "prompt_golden.json")


@pytest.fixture(scope="module")
def golden():
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("case", CASES, ids=[c["key"] for c in CASES])
def test_prompt_output_matches_golden(case, golden):
    ResumeDataStore.clear_data(SESSION)
    agent = ResumeDomainRuntime(session_id=SESSION)
    try:
        if case["resume"]:
            ResumeDataStore.set_data(dict(RESUME), session_id=SESSION)
            agent._conversation_state.update_resume_loaded(True)
        if case.get("resume_path"):
            agent._current_resume_path = case["resume_path"]
        intent = getattr(Intent, case["intent"])
        # asyncio.run 而非 get_event_loop:全量测试顺序下前置测试会关闭/重置
        # 当前 loop,get_event_loop 在 Python3.11 主线程无活动 loop 时直接抛错
        system_prompt, next_step = asyncio.run(
            agent._generate_dynamic_prompts(case["input"], intent)
        )
        expected = golden[case["key"]]
        # normalize: prompt 含 WORKSPACE_ROOT 绝对路径,不同机器路径不同
        # golden 录制于 /Users/mac/开源工具/ResumeAgent,本地可能是任意路径
        # 统一把不同机器上的仓库 docs 绝对路径归一
        import re
        _norm = lambda s: re.sub(
            r"[^\s]*(?:ResumeAgent|Resume-Agent)[^\s/\\]*[\\/]+docs",
            "<WORKSPACE_ROOT>",
            s,
        )
        assert _norm(system_prompt) == _norm(expected["system"]), f"{case['key']} system prompt 漂移"
        assert _norm(next_step) == _norm(expected["next_step"]), f"{case['key']} next_step 漂移"
    finally:
        ResumeDataStore.clear_data(SESSION)


def test_broad_optimize_loads_full_resume_guidance_skills():
    agent = ResumeDomainRuntime(session_id="resume-guidance-skills")

    guidance = agent._prompt_builder.build_skill_addendum("我要优化简历")

    assert "[Skill: resume-diagnosis]" in guidance
    assert "[Skill: resume-suggest]" in guidance
    assert "一次诊断同时产出诊断结论和只读修改建议" in guidance
    assert "缺少真实事实时不得生成示例值" in guidance


def test_specific_field_edit_does_not_load_diagnosis_skills():
    agent = ResumeDomainRuntime(session_id="resume-guidance-skills-specific-edit")

    guidance = agent._prompt_builder.build_skill_addendum(
        "把邮箱改成 new@example.com"
    )

    assert "resume-diagnosis" not in guidance
    assert "resume-suggest" not in guidance


def test_required_resume_skill_missing_fails_fast(tmp_path: Path):
    agent = ResumeDomainRuntime(session_id="resume-guidance-skills-missing")

    with pytest.raises(RuntimeError, match="Required resume Skill"):
        agent._prompt_builder.read_skill(tmp_path / "missing" / "SKILL.md")


def test_broad_optimize_does_not_resume_an_existing_write_progress():
    session_id = "broad-diagnosis-does-not-resume-write-progress"
    ResumeDataStore.clear_data(session_id)
    agent = ResumeDomainRuntime(session_id=session_id)
    ResumeDataStore.set_data(dict(RESUME), session_id=session_id)
    ResumeDataStore.init_progress(session_id, RESUME)

    system_prompt, _ = asyncio.run(
        agent._generate_dynamic_prompts("我要优化简历", Intent.UNKNOWN)
    )

    assert "## 整份优化进度" not in system_prompt
    assert "## Work Experience" in system_prompt
    ResumeDataStore.clear_data(session_id)
