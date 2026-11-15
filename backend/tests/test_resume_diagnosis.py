"""简历诊断卡与 Asking 模式开关的回归测试。"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.core.logger import setup_logging

setup_logging(False, "INFO", "logs/test")

from backend.agent.pi_core.resume_domain import ResumeDomainRuntime
from backend.agent.pi_core.tool_runtime import ToolExecutionRuntime
from backend.agent.application.resume_diagnosis import build_resume_diagnosis
from backend.agent.application.resume_diagnosis_engine import ResumeGuidanceModule
from backend.agent.application.conversation.conversation_state import (
    is_diagnosis_apply_query,
    is_full_optimize_query,
    is_view_suggestions_query,
)
from backend.agent.schema import Message, ToolCall
from backend.agent.tool import ToolCollection
from backend.agent.tool.base import BaseTool, ToolProgress, ToolResult
from backend.agent.tool.cv_analyzer_agent_tool import CVAnalyzerAgentTool
from backend.agent.tool.resume_data_store import ResumeDataStore


RICH_RESUME = {
    "resume_id": "resume-diagnosis-test",
    "basic": {
        "name": "测试用户",
        "title": "后端开发工程师",
        "phone": "13800000000",
        "email": "secret@example.com",
    },
    "education": [],
    "experience": [
        {
            "company": "示例科技",
            "position": "后端开发实习生",
            "date": "2025.01 - 2025.06",
            "details": (
                "<ul><li>负责订单服务重构，使用 Go 与 Redis 将接口耗时降低 35%</li>"
                "<li>治理慢查询 80 余条，核心接口 QPS 提升 2 倍</li></ul>"
            ),
        }
    ],
    "projects": [
        {
            "name": "智能简历助手",
            "role": "核心开发",
            "date": "2025.03 - 2025.07",
            "description": "基于 FastAPI 和 React 完成 Agent 工作流与流式交互。",
        }
    ],
    "skillContent": "Go、Python、FastAPI、Redis、MySQL、React",
    "awards": [],
}


def test_diagnosis_payload_is_up_style_and_flags_missing_education():
    payload = build_resume_diagnosis(RICH_RESUME)

    assert payload["type"] == "resume_diagnosis"
    assert payload["status"] == "success"
    assert 0 <= payload["summary"]["overall_score"] <= 100
    assert 0 <= payload["summary"]["content_score"] <= 100
    assert 0 <= payload["summary"]["interview_score"] <= 100
    assert 0 <= payload["summary"]["matching_score"] <= 100
    assert 0 <= payload["summary"]["screening_score"] <= 100
    assert "screening_probability" not in payload["summary"]
    assert payload["summary"]["overall_score"] <= 95
    assert set(payload["details"]["dimensions"]) == {
        "content",
        "interview",
        "matching",
    }
    assert len(payload["details"]["actions"]) == 3
    assert any(
        "教育" in issue for issue in payload["details"]["issues"]["must_fix"]
    )


def test_diagnosis_payload_does_not_echo_contact_pii():
    rendered = str(build_resume_diagnosis(RICH_RESUME))

    assert "13800000000" not in rendered
    assert "secret@example.com" not in rendered


def test_diagnosis_cross_checks_skills_against_experience_evidence():
    resume = dict(RICH_RESUME)
    resume["skillContent"] = "Kafka、Dubbo、Kubernetes"
    resume["experience"] = [
        {
            "company": "示例科技",
            "position": "后端实习生",
            "date": "2025.01 - 2025.06",
            "details": "负责订单接口维护与日常需求开发。",
        }
    ]

    payload = build_resume_diagnosis(resume)

    assert any(
        "实际使用深度" in issue
        for issue in payload["details"]["issues"]["should_fix"]
    )


def test_diagnosis_does_not_treat_generic_development_as_direction_match():
    resume = dict(RICH_RESUME)
    resume["basic"] = {"title": "后端开发工程师"}
    resume["skillContent"] = "React、TypeScript、CSS"
    resume["experience"] = [
        {
            "company": "示例科技",
            "position": "前端开发实习生",
            "date": "2025.01 - 2025.06",
            "details": "使用 React 和 TypeScript 完成管理后台页面开发。",
        }
    ]

    payload = build_resume_diagnosis(resume)

    assert any(
        "目标岗位与当前经历方向缺少明显对应" in issue
        for issue in payload["details"]["issues"]["should_fix"]
    )


def test_asking_tool_is_disabled_by_default_and_can_be_reenabled(monkeypatch):
    monkeypatch.delenv("AGENT_ASKING_MODE_ENABLED", raising=False)
    disabled = ResumeDomainRuntime(session_id="asking-disabled")
    assert "ask_user_question" not in disabled.available_tools.tool_map

    monkeypatch.setenv("AGENT_ASKING_MODE_ENABLED", "true")
    enabled = ResumeDomainRuntime(session_id="asking-enabled")
    assert "ask_user_question" in enabled.available_tools.tool_map


def test_diagnosis_apply_turn_is_single_shot():
    """apply v2：诊断后显式 apply 走单轮出齐，不再初始化逐模块优化任务。"""
    assert is_full_optimize_query("针对诊断结果逐项修改")
    assert is_diagnosis_apply_query("针对诊断结果逐项修改")
    session_id = "diagnosis-primary-action"
    ResumeDataStore.clear_data(session_id)
    agent = ResumeDomainRuntime(session_id=session_id)
    ResumeDataStore.set_data(dict(RICH_RESUME), session_id=session_id)
    agent._shared_state.set(
        "resume_diagnosis_completed_for", RICH_RESUME["resume_id"]
    )

    agent._maybe_init_optimize_progress("针对诊断结果逐项修改")

    # 不启动逐模块任务（无 pending 清单、无 auto_continue 续跑）
    assert ResumeDataStore.get_progress(session_id) is None

    agent.memory.add_message(Message.user_message("针对诊断结果逐项修改"))
    agent._sync_turn_read_only_flag("针对诊断结果逐项修改")
    assert agent._turn.diagnosis_apply is True
    assert agent._turn.diagnosis_only is False
    ResumeDataStore.clear_data(session_id)


def test_diagnosis_apply_turn_blocks_ask_tools():
    """apply 轮拦截 ask_human/ask_user_question：缺信息跳过，不向用户提问。"""
    session_id = "diagnosis-apply-blocks-ask"
    ResumeDataStore.clear_data(session_id)
    agent = ResumeDomainRuntime(session_id=session_id)
    ResumeDataStore.set_data(dict(RICH_RESUME), session_id=session_id)
    agent._shared_state.set(
        "resume_diagnosis_completed_for", RICH_RESUME["resume_id"]
    )
    agent.memory.add_message(Message.user_message("按照诊断建议帮我修改简历"))
    agent._sync_turn_read_only_flag("按照诊断建议帮我修改简历")
    assert agent._turn.diagnosis_apply is True

    command = ToolCall(
        id="call-ask-must-be-blocked",
        function={"name": "ask_human", "arguments": '{"inquire":"GPA 是多少？"}'},
    )
    result = asyncio.run(agent.execute_tool(command))

    assert "缺少真实信息的建议直接跳过" in result
    ResumeDataStore.clear_data(session_id)


def test_diagnosis_apply_phrase_without_diagnosis_stays_read_only():
    """未诊断就说 apply 话术：闸门不放行，既不初始化任务也不解除只读。"""
    session_id = "diagnosis-apply-without-diagnosis"
    ResumeDataStore.clear_data(session_id)
    agent = ResumeDomainRuntime(session_id=session_id)
    ResumeDataStore.set_data(dict(RICH_RESUME), session_id=session_id)

    agent._maybe_init_optimize_progress("按照诊断建议帮我修改简历")
    assert ResumeDataStore.get_progress(session_id) is None

    agent._sync_turn_read_only_flag("按照诊断建议帮我修改简历")
    assert agent._turn.diagnosis_only is True
    ResumeDataStore.clear_data(session_id)


def test_diagnosis_apply_turn_unlocks_editor_after_diagnosis():
    """诊断已完成 + 显式 apply → diagnosis_only 解除，编辑工具放行。"""
    session_id = "diagnosis-apply-unlocks-editor"
    ResumeDataStore.clear_data(session_id)
    agent = ResumeDomainRuntime(session_id=session_id)
    ResumeDataStore.set_data(dict(RICH_RESUME), session_id=session_id)
    agent._shared_state.set(
        "resume_diagnosis_completed_for", RICH_RESUME["resume_id"]
    )

    agent.memory.add_message(Message.user_message("按照诊断建议帮我修改简历"))
    agent._sync_turn_read_only_flag("按照诊断建议帮我修改简历")

    assert agent._turn.diagnosis_only is False
    ResumeDataStore.clear_data(session_id)


def test_diagnosis_apply_query_matches_real_chip_phrasings():
    """apply 正则覆盖诊断卡/建议 chip 的真实措辞；泛优化与否定不误伤。"""
    for phrase in [
        "针对诊断结果逐项修改",
        "按建议帮我修改",
        "按照诊断建议帮我修改简历",
        "帮我处理简历内容诊断中的问题",
        "开始优化简历",
        "开始帮我优化简历",
        "根据建议优化一下",
    ]:
        assert is_diagnosis_apply_query(phrase), phrase
    for phrase in [
        "我要优化简历",
        "帮我优化简历",
        "帮我诊断一下简历",
        "看看我的简历怎么样",
        "先别按建议改",
        "",
    ]:
        assert not is_diagnosis_apply_query(phrase), phrase


def test_repeating_broad_optimize_after_diagnosis_stays_read_only():
    session_id = "diagnosis-repeat-broad-read-only"
    ResumeDataStore.clear_data(session_id)
    agent = ResumeDomainRuntime(session_id=session_id)
    ResumeDataStore.set_data(dict(RICH_RESUME), session_id=session_id)
    agent._shared_state.set(
        "resume_diagnosis_completed_for", RICH_RESUME["resume_id"]
    )

    agent._maybe_init_optimize_progress("我要优化简历")

    assert ResumeDataStore.get_progress(session_id) is None
    ResumeDataStore.clear_data(session_id)


def test_broad_optimize_turn_blocks_editor_even_if_model_selects_it():
    agent = ResumeDomainRuntime(session_id="diagnosis-only-editor-guard")
    agent.memory.add_message(Message.user_message("我要优化简历"))
    agent._sync_turn_read_only_flag("我要优化简历")
    command = ToolCall(
        id="call-editor-must-be-blocked",
        function={
            "name": "cv_editor_agent",
            "arguments": '{"path":"basic.title","action":"update","value":"后端开发"}',
        },
    )

    result = asyncio.run(agent.execute_tool(command))

    assert "本轮只做简历诊断" in result


def test_analyzer_tool_returns_structured_card_and_marks_completion(monkeypatch):
    session_id = "diagnosis-tool-result"
    agent = ResumeDomainRuntime(session_id=session_id)
    ResumeDataStore.set_data(dict(RICH_RESUME), session_id=session_id)
    tool = CVAnalyzerAgentTool(
        session_id=session_id,
        shared_state=agent._shared_state,
    )

    assess_calls = 0

    async def fake_assess(_self, resume_data, question, *, on_progress=None):
        nonlocal assess_calls
        assess_calls += 1
        payload = build_resume_diagnosis(resume_data)
        payload["schema_version"] = "2.0"
        payload["assessment_id"] = "assessment_tool_test"
        payload["resume_ref"] = {
            "id": resume_data["resume_id"],
            "revision": ResumeGuidanceModule.resume_revision(resume_data),
        }
        payload["artifact_id"] = "diagnosis_assessment_tool_test"
        payload["details"]["public_trace"] = [
            "结构完整度已核对。",
            "成果证据已核对。",
            "面试风险已核对。",
            "岗位匹配已核对。",
        ]
        payload["details"]["suggestions"] = [
            {
                "suggestion_id": "suggestion_tool_test",
                "assessment_id": "assessment_tool_test",
                "section": "education",
                "severity": "critical",
                "title": "补全教育经历",
                "original": "教育经历为空",
                "recommendation": "补充真实教育信息。",
                "evidence": "当前教育经历为空。",
                "requires_facts": ["院校"],
                "status": "needs_fact",
            }
        ]
        payload["details"]["diagnosis_source"] = "llm"
        return payload

    monkeypatch.setattr(ResumeGuidanceModule, "assess", fake_assess)

    result = asyncio.run(tool.execute("诊断这份简历"))

    assert result.error is None
    assert result.structured_data["type"] == "resume_diagnosis"
    assert result.structured_data["assessment_id"] == "assessment_tool_test"
    assert result.structured_data["details"]["suggestions"][0]["status"] == (
        "needs_fact"
    )
    assert agent._shared_state.get("resume_diagnosis_completed_for") == (
        "resume-diagnosis-test"
    )
    assert assess_calls == 1
    cached = agent._shared_state.get("resume_guidance_assessment")
    assert cached["assessment_id"] == "assessment_tool_test"
    suggestions_artifact = ResumeGuidanceModule.present(cached, "suggestions")
    assert suggestions_artifact["source"]["assessment_id"] == (
        "assessment_tool_test"
    )
    assert assess_calls == 1

    ResumeDataStore.clear_data(session_id)


class _NoArgsTool(BaseTool):
    name: str = "no_args_test_tool"
    description: str = "test"
    parameters: dict = {"type": "object", "properties": {}}

    async def execute(self) -> ToolResult:
        return ToolResult(output="ok")


def test_noargs_placeholder_is_removed_before_tool_execution():
    agent = ToolExecutionRuntime(available_tools=ToolCollection(_NoArgsTool()))
    command = ToolCall(
        id="call-noargs",
        function={
            "name": "no_args_test_tool",
            "arguments": '{"_noargs":"unused"}',
        },
    )

    result = asyncio.run(agent.execute_tool(command))

    assert "ok" in result
    assert "unexpected keyword" not in result


def test_tool_progress_callbacks_are_isolated_between_overlapping_runs():
    async def scenario():
        tool = _NoArgsTool()
        delivered = []
        first_bound = asyncio.Event()
        second_bound = asyncio.Event()
        release_first = asyncio.Event()
        release_second = asyncio.Event()

        async def run(label, bound, release):
            async def callback(update):
                delivered.append((label, update.content))

            token = tool.set_progress_callback(callback)
            try:
                bound.set()
                await release.wait()
                await tool.emit_progress(ToolProgress(content=label))
            finally:
                tool.clear_progress_callback(token)

        first = asyncio.create_task(
            run("first", first_bound, release_first)
        )
        await first_bound.wait()
        second = asyncio.create_task(
            run("second", second_bound, release_second)
        )
        await second_bound.wait()

        release_first.set()
        await first
        release_second.set()
        await second
        return delivered

    assert asyncio.run(scenario()) == [
        ("first", "first"),
        ("second", "second"),
    ]


def test_view_suggestions_query_matches_view_not_apply():
    """2026-07-16 拆分："查看…建议"是读不是改，不得被 apply 正则吞掉。"""
    for text in (
        "查看修改建议",
        "查看这次诊断的修改建议",
        "看看这次诊断的建议",
        "给我看具体建议",
    ):
        assert is_view_suggestions_query(text), text
        assert not is_diagnosis_apply_query(text), text
    for text in (
        "按照诊断建议帮我修改简历",
        "针对诊断结果逐项修改",
        "开始优化简历",
    ):
        assert not is_view_suggestions_query(text), text
        assert is_diagnosis_apply_query(text), text


def test_view_suggestions_turn_blocks_editor_and_reanalysis():
    """查看建议轮：只读展示建议，拦编辑与重新诊断（引导 cv_suggestions_agent）。"""
    session_id = "view-suggestions-guard"
    ResumeDataStore.clear_data(session_id)
    agent = ResumeDomainRuntime(session_id=session_id)
    ResumeDataStore.set_data(dict(RICH_RESUME), session_id=session_id)
    agent._shared_state.set(
        "resume_diagnosis_completed_for", RICH_RESUME["resume_id"]
    )
    agent.memory.add_message(Message.user_message("查看这次诊断的修改建议"))
    agent._sync_turn_read_only_flag("查看这次诊断的修改建议")

    assert agent._turn.view_suggestions is True
    assert agent._turn.diagnosis_only is False
    assert agent._turn.diagnosis_apply is False

    for blocked in ("cv_editor_agent", "cv_analyzer_agent"):
        command = ToolCall(
            id=f"call-{blocked}-blocked",
            function={"name": blocked, "arguments": "{}"},
        )
        result = asyncio.run(agent.execute_tool(command))
        assert "本轮只展示诊断的修改建议" in result, blocked
    ResumeDataStore.clear_data(session_id)


def test_view_suggestions_without_diagnosis_stays_diagnosis_only():
    """未诊断就说"查看建议"：没有建议可看，仍走只读诊断轮。"""
    session_id = "view-suggestions-no-diagnosis"
    ResumeDataStore.clear_data(session_id)
    agent = ResumeDomainRuntime(session_id=session_id)
    ResumeDataStore.set_data(dict(RICH_RESUME), session_id=session_id)
    agent.memory.add_message(Message.user_message("查看修改建议"))
    agent._sync_turn_read_only_flag("查看修改建议")

    assert agent._turn.view_suggestions is False
    ResumeDataStore.clear_data(session_id)


def test_cv_suggestions_tool_requires_diagnosis_and_serves_cache(monkeypatch):
    """cv_suggestions_agent：无诊断引导先诊断；缓存命中零生成；生成后回写。"""
    from backend.agent.tool.cv_suggestions_agent_tool import CVSuggestionsAgentTool

    session_id = "cv-suggestions-tool-test"
    ResumeDataStore.clear_data(session_id)
    agent = ResumeDomainRuntime(session_id=session_id)
    tool = next(
        t for t in agent.available_tools.tools if t.name == "cv_suggestions_agent"
    )
    assert isinstance(tool, CVSuggestionsAgentTool)

    # 1) 无诊断：引导先诊断，不报错
    ResumeDataStore.set_data(dict(RICH_RESUME), session_id=session_id)
    result = asyncio.run(tool.execute("查看修改建议"))
    assert result.error is None
    assert "还没有诊断结果" in result.output

    # 2) 有诊断但无缓存建议：走 suggest() 生成并回写 shared_state
    suggestion = {
        "suggestion_id": "s1",
        "assessment_id": "assessment_x",
        "section": "education",
        "severity": "critical",
        "title": "补全教育经历",
        "original": "教育经历为空",
        "recommendation": "补充真实的院校与学历。",
        "evidence": "无可核验教育背景。",
        "requires_facts": ["院校"],
        "status": "needs_fact",
    }
    assessment = {
        "assessment_id": "assessment_x",
        "resume_ref": {"id": RICH_RESUME["resume_id"], "revision": "r1"},
        "details": {"suggestions": []},
    }
    agent._shared_state.set("resume_guidance_assessment", assessment)

    suggest_calls = {"count": 0}

    async def fake_suggest(self, resume_data, assessment_arg):
        suggest_calls["count"] += 1
        assessment_arg["details"]["suggestions"] = [suggestion]
        return ResumeGuidanceModule.present(assessment_arg, "suggestions")

    monkeypatch.setattr(ResumeGuidanceModule, "suggest", fake_suggest)

    result = asyncio.run(tool.execute("查看修改建议"))
    assert result.error is None
    assert suggest_calls["count"] == 1
    assert result.structured_data["type"] == "resume_suggestions"
    assert result.structured_data["kind"] == "resume_suggestions"
    assert result.structured_data["payload"]["suggestions"] == [suggestion]
    cached = agent._shared_state.get("resume_guidance_assessment")
    assert cached["details"]["suggestions"] == [suggestion]

    # 3) 再次查看：缓存命中，零生成调用
    result = asyncio.run(tool.execute("再看看建议"))
    assert suggest_calls["count"] == 1
    assert result.structured_data["payload"]["suggestions"] == [suggestion]
    ResumeDataStore.clear_data(session_id)
