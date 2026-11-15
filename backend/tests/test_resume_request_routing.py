"""宽泛简历请求的语义路由回归测试。"""

import asyncio
import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.core.logger import setup_logging

setup_logging(False, "INFO", "logs/test")

from backend.agent.pi_core.resume_agent import ResumeAgentRuntime
from backend.agent.pi_core.resume_domain import ResumeDomainRuntime
from backend.agent.application.resume_diagnosis import build_resume_diagnosis
from backend.agent.schema import Message, ToolCall
from backend.agent.application.conversation.conversation_state import (
    ResumeRequestRoute,
    classify_resume_request,
    is_full_optimize_query,
    is_read_only_query,
)
from backend.agent.tool.resume_data_store import ResumeDataStore
from backend.agent.tool.base import ToolProgress, ToolResult
from backend.agent.web.streaming.agent_stream import AgentStream
from backend.agent.web.streaming.state_machine import AgentStateMachine


@pytest.mark.parametrize(
    "query",
    [
        "我要优化简历",
        "我要改简历",
        "帮我改改简历",
        "润色一下我的简历",
        "帮我完善简历",
        "提升一下简历",
        "把整份简历打磨一下",
        "把我的简历写得更专业",
        "把简历改成更专业的版本",
        "优化简历里的全部内容",
        "帮我改改简历里的内容",
        "润色一下简历里的文字",
        "优化一下简历中的表述",
        "针对诊断结果逐项修改",
    ],
)
def test_broad_resume_improvement_phrasings_share_one_route(query):
    assert classify_resume_request(query) is ResumeRequestRoute.BROAD_OPTIMIZE
    assert is_full_optimize_query(query)


@pytest.mark.parametrize(
    "query",
    [
        "帮我诊断一下简历",
        "看看我的简历哪里有问题",
        "从招聘者角度分析我的简历",
        "这份简历质量怎么样",
        "帮我看看简历",
        "帮我整体看一下简历",
        "帮我诊断一下简历的项目经历",
        "分析项目经历",
        "看看项目经历哪里有问题",
    ],
)
def test_diagnosis_phrasings_share_diagnosis_route(query):
    assert classify_resume_request(query) is ResumeRequestRoute.DIAGNOSE
    assert not is_full_optimize_query(query)


@pytest.mark.parametrize(
    "query",
    [
        "把第二段实习改短",
        "优化项目经历",
        "全面优化项目经历",
        "优化简历的项目经历",
        "按这个 JD 优化我的简历",
        "把简历里的出生日期改成 2000 年 1 月 1 日",
        "把整份简历里的手机号改成 13800000000",
        "手机号改成 13800000000",
        "把这句话写得更专业",
        "修改简历里的错别字",
    ],
)
def test_specific_edits_do_not_enter_full_diagnosis_route(query):
    assert classify_resume_request(query) is ResumeRequestRoute.SPECIFIC_EDIT
    assert not is_full_optimize_query(query)


@pytest.mark.parametrize(
    "query",
    [
        "看看我的简历第一段经历",
        "展示我的简历",
        "别改简历，先展示一下",
        "不要优化简历",
        "先别改简历了",
        "不要对我的简历进行任何优化",
        "你好",
    ],
)
def test_read_only_and_unrelated_requests_do_not_enter_diagnosis(query):
    assert classify_resume_request(query) is ResumeRequestRoute.OTHER
    assert not is_full_optimize_query(query)


def test_read_only_guard_uses_the_same_edit_vocabulary_as_routing():
    assert is_read_only_query("别改简历，先展示一下")
    assert not is_read_only_query("帮我提升简历，看看效果")


def test_whole_diagnosis_can_name_a_priority_section():
    assert (
        classify_resume_request("全面分析简历，重点看项目经历")
        is ResumeRequestRoute.DIAGNOSE
    )


def test_broad_alias_reaches_diagnosis_tool_result_event(monkeypatch):
    """宽泛优化由 LLM 选择诊断工具，再走完整 structured event 链路。"""
    session_id = "request-route-stream-diagnosis"
    ResumeDataStore.clear_data(session_id)
    agent = ResumeAgentRuntime(session_id=session_id)
    ResumeDataStore.set_data(
        {
            "resume_id": "resume-stream-diagnosis",
            "basic": {"name": "测试用户", "title": ""},
            "education": [],
            "experience": [],
            "projects": [],
            "skillContent": "",
        },
        session_id=session_id,
    )
    progress = ResumeDataStore.init_progress(
        session_id, ResumeDataStore.get_data(session_id)
    )
    progress_task_id = progress["task_id"]
    agent.queue_resume_patch(
        {
            "patch_id": "stale_patch",
            "paths": ["education"],
            "before": {},
            "after": {"education": [{"school": "不应发送"}]},
            "summary": "上一轮残留 patch",
        }
    )

    llm_calls = 0
    analyzer_released = asyncio.Event()
    analyzer_finished = asyncio.Event()

    async def fake_ask_tool_stream(**kwargs):
        nonlocal llm_calls
        llm_calls += 1
        narration = (
            "正文已经在了，我先换上招聘者的视角，从结构、成果证据、"
            "面试风险和岗位匹配四个方向找出最值得优先动的地方。"
        )
        await kwargs["on_content_delta"](narration)
        return SimpleNamespace(
            content=narration,
            tool_calls=[
                ToolCall(
                    id="call_resume_diagnosis",
                    function={
                        "name": "cv_analyzer_agent",
                        "arguments": json.dumps(
                            {"question": "我要改简历"}, ensure_ascii=False
                        ),
                    },
                )
            ],
        )

    async def fake_analyzer_execute(_self, question: str):
        await analyzer_released.wait()
        for index, content in enumerate(
            (
                "先核对结构完整度：教育经历为空。",
                "再看成果证据：当前缺少可量化经历。",
                "接着检查面试风险：可追问证据不足。",
                "最后核对岗位匹配：目标方向尚未明确。",
            )
        ):
            await _self.emit_progress(
                ToolProgress(
                    content=content,
                    phase="diagnosis_progress",
                    node_id=f"stage-{index + 1}",
                )
            )
        structured = build_resume_diagnosis(ResumeDataStore.get_data(session_id))
        structured["details"]["public_trace"] = [
            "先核对结构完整度：教育经历为空。",
            "再看成果证据：当前缺少可量化经历。",
            "接着检查面试风险：可追问证据不足。",
            "最后核对岗位匹配：目标方向尚未明确。",
        ]
        structured["details"]["suggestions"] = [
            {
                "suggestion_id": "suggestion_stream_test",
                "assessment_id": "assessment_stream_test",
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
        structured["assessment_id"] = "assessment_stream_test"
        structured["details"]["diagnosis_source"] = "test_llm"
        analyzer_finished.set()
        return ToolResult(output="诊断完成", structured_data=structured)

    monkeypatch.setattr(agent.llm, "ask_tool_stream", fake_ask_tool_stream)
    monkeypatch.setattr(
        type(agent.available_tools.tool_map["cv_analyzer_agent"]),
        "execute",
        fake_analyzer_execute,
    )

    async def collect_events():
        async def ignore_event(_event):
            return None

        stream = AgentStream(
            agent,
            session_id,
            AgentStateMachine(session_id),
            ignore_event,
        )
        events = []
        async for event in stream.execute("我要改简历"):
            event_data = event.to_dict()
            events.append(event_data)
            if (
                event_data["type"] == "tool_call"
                and event_data["data"]["tool"] == "cv_analyzer_agent"
            ):
                    # 线性事件流保证 tool_call 先于 tool_result；这里释放
                    # 测试工具，验证前端可在 running 卡片展示后继续推进。
                analyzer_released.set()
        return events

    events = asyncio.run(asyncio.wait_for(collect_events(), timeout=1))
    assert llm_calls == 1
    event_types = [event["type"] for event in events]
    tool_call_index = next(
        index
        for index, event in enumerate(events)
        if event["type"] == "tool_call"
        and event["data"]["tool"] == "cv_analyzer_agent"
    )
    tool_result_index = next(
        index
        for index, event in enumerate(events)
        if event["type"] == "tool_result"
        and event["data"]["tool"] == "cv_analyzer_agent"
    )
    thought_index = next(
        index
        for index, event in enumerate(events)
        if event["type"] == "thought"
        and "换上招聘者的视角" in event["data"]["content"]
    )
    complete_answer = next(
        event["data"]["content"]
        for event in events
        if event["type"] == "answer" and event["data"].get("is_complete")
    )

    assert "agent_start" in event_types
    assert thought_index < tool_call_index < tool_result_index
    assert not any(
        event["type"] == "answer" for event in events[:tool_call_index]
    ), f"工具动作旁白不得先冒充 response 再被重置: {events[:tool_call_index]}"
    assert events[thought_index]["data"]["step_id"] == 1
    assert events[tool_call_index]["data"]["step_id"] == 1
    assert events[tool_result_index]["data"]["step_id"] == 1
    assert events[tool_result_index]["data"]["structured_data"]["type"] == (
        "resume_diagnosis"
    )
    # Pi Core 的最小 tool boundary 不把工具内部日志重新注入模型上下文；
    # 进度卡由独立的 tool_execution_update 适配器负责，诊断结果本身仍按
    # tool_result 结构化事件稳定落盘。
    assert events[tool_result_index]["data"]["structured_data"]["assessment_id"] == (
        "assessment_stream_test"
    )
    assert events[tool_result_index]["data"]["structured_data"]["details"][
        "suggestions"
    ]
    assert not any(
        event["data"].get("tool") == "cv_editor_agent" for event in events
    )
    assert "resume_patch" not in event_types
    assert "auto_continue" not in event_types
    assert complete_answer == "诊断已经整理好，本轮没有改动简历。想看逐条修改建议，点评分卡上的「查看修改建议」。"
    assert ResumeDataStore.get_progress(session_id)["task_id"] == progress_task_id

    ResumeDataStore.clear_data(session_id)


def test_explicit_diagnosis_is_also_a_diagnosis_only_turn():
    agent = ResumeDomainRuntime(session_id="request-route-explicit-diagnosis")

    agent.memory.add_message(Message.user_message("帮我诊断一下简历"))
    agent._sync_turn_read_only_flag("帮我诊断一下简历")

    assert agent._turn.diagnosis_only is True
