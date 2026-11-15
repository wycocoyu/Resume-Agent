"""Canonical 事件协议回归:
1. 所有事件 to_dict 必含 id/type/session_id/run_id/seq/timestamp/data 统一外壳
2. resume_patch / resume_generated / tool_result 业务字段只存在 data
3. %%SUGGESTIONS%% 标记提取:完整匹配 / 半开放容错 / 无标记 / 坏 JSON
4. suggestions 每 run 只发一次(step-tail 与 post-loop 双提取点防重)
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.core.logger import setup_logging
setup_logging(False, "INFO", "logs/test")

import backend.agent.pi_core.resume_agent  # noqa: F401  先初始化包,避开循环导入
from backend.agent.web.streaming.agent_stream import AgentStream, is_tool_error_content
from backend.agent.web.streaming.events import (
    AgentStartEvent,
    AnswerEvent,
    ResumeGeneratedEvent,
    ResumePatchEvent,
    ResumeUpdatedEvent,
    SuggestionsEvent,
    SystemEvent,
    ToolProgressEvent,
    ThoughtEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from backend.agent.web.streaming.agent_stream import StreamProcessor
from backend.agent.web.streaming.state_machine import AgentStateMachine

SID = "s-protocol-test"


def test_stream_processor_stop_stream_uses_shared_state_machine():
    processor = StreamProcessor()
    state_machine = AgentStateMachine("s-stop")
    stream = type("Stream", (), {"_state_machine": state_machine})()
    processor._active_streams["s-stop"] = stream

    stopped = asyncio.run(processor.stop_stream("s-stop", reason="session_switch"))

    assert stopped is True
    assert state_machine.stop_requested is True
    assert state_machine.state_info.data["reason"] == "session_switch"
    assert asyncio.run(processor.stop_stream("missing")) is False


def make_stream() -> AgentStream:
    """仅测试标记提取/防重方法,不跑执行循环,绕开重量级构造依赖"""
    stream = AgentStream.__new__(AgentStream)
    stream._session_id = SID
    stream._suggestions_emitted = False
    return stream


# ---------- 1. 统一外壳 ----------

def test_all_events_carry_envelope():
    events = [
        ThoughtEvent(thought="t", session_id=SID, step_id=2),
        ToolCallEvent(
            tool_name="x", tool_args={}, session_id=SID, step_id=2, tool_call_id="c2"
        ),
        ToolResultEvent(
            tool_name="x", result="r", session_id=SID, step_id=2, tool_call_id="c2"
        ),
        AnswerEvent(content="a", session_id=SID),
        ResumeUpdatedEvent(resume_data={}, session_id=SID),
        ResumePatchEvent(
            patch_id="p", paths=[], before={}, after={}, summary="", session_id=SID
        ),
        ResumeGeneratedEvent(resume={}, summary="", session_id=SID),
        SuggestionsEvent(items=[], session_id=SID),
        AgentStartEvent(agent_name="m", task="t", session_id=SID),
        SystemEvent(message="m", session_id=SID),
        ToolProgressEvent(
            tool_call_id="c-progress",
            stage_id="evidence",
            current=2,
            total=5,
            label="成果证据",
            summary="已核对量化结果",
            stages=["结构完整度", "成果证据"],
            session_id=SID,
        ),
    ]
    for event in events:
        d = event.to_dict()
        missing = {"type", "session_id", "timestamp"} - set(d)
        assert not missing, f"{type(event).__name__} 缺公共字段: {missing}"
        assert d["session_id"] == SID, f"{type(event).__name__} session_id 丢失"


def test_event_can_be_bound_to_canonical_run_envelope():
    event = ThoughtEvent(thought="t", session_id=SID, step_id=1)
    event.bind_envelope(run_id="run-1", seq=7, event_id="evt-7")

    payload = event.to_dict()

    assert payload["id"] == "evt-7"
    assert payload["run_id"] == "run-1"
    assert payload["seq"] == 7
    assert payload["data"]["content"] == "t"


def test_tool_progress_event_has_formal_stage_contract():
    event = ToolProgressEvent(
        tool_call_id="c-progress",
        stage_id="evidence",
        current=2,
        total=5,
        label="成果证据",
        summary="已核对量化结果",
        stages=["结构完整度", "成果证据"],
        session_id=SID,
    ).to_dict()

    assert event["type"] == "tool_progress"
    assert event["data"]["tool_call_id"] == "c-progress"
    assert event["data"]["stage_id"] == "evidence"
    assert event["data"]["current"] == 2
    assert event["data"]["total"] == 5


# ---------- 2. canonical data 业务字段 ----------

def test_resume_patch_canonical_data():
    d = ResumePatchEvent(
        patch_id="p1",
        paths=["basic.name"],
        before={"basic.name": "a"},
        after={"basic.name": "b"},
        summary="改名",
        session_id=SID,
        operation="set",
    ).to_dict()
    assert d["type"] == "resume_patch"
    assert d["data"]["patch_id"] == "p1"
    assert d["data"]["paths"] == ["basic.name"]
    assert d["data"]["before"] == {"basic.name": "a"}
    assert d["data"]["after"] == {"basic.name": "b"}
    assert d["data"]["operation"] == "set"
    assert d["data"]["patch_id"] == "p1"


def test_resume_generated_canonical_data():
    d = ResumeGeneratedEvent(
        resume={"basic": {"name": "张三"}}, summary="done", session_id=SID
    ).to_dict()
    assert d["type"] == "resume_generated"
    assert d["data"]["resume"] == {"basic": {"name": "张三"}}
    assert d["data"]["summary"] == "done"
    assert d["data"]["resume"] == {"basic": {"name": "张三"}}


def test_tool_result_canonical_contract():
    d = ToolResultEvent(
        tool_name="cv_editor_agent",
        result="ok",
        session_id=SID,
        tool_call_id="c1",
        step_id=3,
        structured_data={"type": "resume_patch"},
    ).to_dict()
    assert d["data"]["tool"] == "cv_editor_agent"
    assert d["data"]["result"] == "ok"
    assert d["data"]["tool_call_id"] == "c1"
    assert d["data"]["step_id"] == 3
    assert d["data"]["structured_data"] == {"type": "resume_patch"}


def test_react_events_carry_the_same_step_id():
    thought = ThoughtEvent(thought="先读取简历", session_id=SID, step_id=4).to_dict()
    call = ToolCallEvent(
        tool_name="get_resume_detail",
        tool_args={},
        session_id=SID,
        tool_call_id="c-step",
        step_id=4,
    ).to_dict()
    result = ToolResultEvent(
        tool_name="get_resume_detail",
        result="ok",
        session_id=SID,
        tool_call_id="c-step",
        step_id=4,
    ).to_dict()

    assert [
        thought["data"]["step_id"],
        call["data"]["step_id"],
        result["data"]["step_id"],
    ] == [4, 4, 4]


def test_react_events_require_step_id():
    import pytest

    with pytest.raises(TypeError):
        ThoughtEvent(thought="缺少步骤")
    with pytest.raises(TypeError):
        ToolCallEvent(tool_name="x", tool_args={})
    with pytest.raises(TypeError):
        ToolResultEvent(tool_name="x", result="ok")


def test_tool_error_content_maps_to_tool_error_event():
    assert is_tool_error_content("Error: invalid arguments")
    assert is_tool_error_content("  Error: upstream unavailable")
    assert not is_tool_error_content("执行成功")

    event = ToolResultEvent(
        tool_name="get_resume_detail",
        result="Error: resume not found",
        is_error=True,
        session_id=SID,
        tool_call_id="c-error",
        step_id=5,
    ).to_dict()
    assert event["type"] == "tool_error"
    assert event["data"]["step_id"] == 5


def test_answer_event_canonical_contract():
    d = AnswerEvent(content="hello", is_complete=True, session_id=SID).to_dict()
    assert d["data"]["content"] == "hello"
    assert d["data"]["is_complete"] is True


# ---------- 3. SUGGESTIONS 标记提取 ----------

def test_extract_suggestions_full_marker():
    stream = make_stream()
    content = '回答正文\n\n%%SUGGESTIONS%%[{"text":"继续","msg":"继续优化"}]%%END%%'
    cleaned, items = stream._extract_suggestions(content)
    assert cleaned == "回答正文"
    assert items == [{"text": "继续", "msg": "继续优化"}]
    assert "%%SUGGESTIONS%%" not in cleaned


def test_extract_suggestions_partial_marker_tolerated():
    """模型没输出完 %%END%% 时半开放容错"""
    stream = make_stream()
    content = '正文\n\n%%SUGGESTIONS%%[{"text":"a","msg":"b"}'
    cleaned, items = stream._extract_suggestions(content)
    assert cleaned == "正文"
    assert items == [{"text": "a", "msg": "b"}]


def test_extract_suggestions_no_marker():
    stream = make_stream()
    cleaned, items = stream._extract_suggestions("纯正文")
    assert cleaned == "纯正文"
    assert items == []


def test_extract_suggestions_bad_json_keeps_content():
    stream = make_stream()
    content = "正文 %%SUGGESTIONS%%[not-json%%END%%"
    cleaned, items = stream._extract_suggestions(content)
    assert items == []
    assert "正文" in cleaned


# ---------- 4. suggestions 每 run 只发一次 ----------

def test_make_suggestions_event_emits_once():
    stream = make_stream()
    first = stream._make_suggestions_event([{"text": "a", "msg": "b"}])
    assert first is not None
    assert first.to_dict()["data"]["items"] == [{"text": "a", "msg": "b"}]
    assert first.to_dict()["session_id"] == SID
    # 第二次(post-loop 再提取同一标记)不再发
    second = stream._make_suggestions_event([{"text": "a", "msg": "b"}])
    assert second is None


def test_make_suggestions_event_empty_is_noop():
    stream = make_stream()
    assert stream._make_suggestions_event([]) is None
    # 空列表不占用"只发一次"额度
    assert stream._make_suggestions_event([{"text": "a", "msg": "b"}]) is not None


def test_diagnosis_completion_copy_does_not_pretend_llm_fallback_succeeded():
    assert AgentStream._diagnosis_completion_text(
        {"details": {"diagnosis_source": "llm"}}
    ) == "诊断已经整理好，本轮没有改动简历。想看逐条修改建议，点评分卡上的「查看修改建议」。"
    fallback = AgentStream._diagnosis_completion_text(
        {"details": {"diagnosis_source": "heuristic_fallback"}}
    )
    assert "深度诊断暂时没跑完" in fallback
    assert "基础检查" in fallback


def test_user_facing_error_hides_internal_retry_repr():
    """RetryError[<Future ...>] 这类内部 repr 不得露给用户（2026-07-16 实测修复）。"""
    import httpx
    import openai
    from tenacity import RetryError
    from unittest.mock import MagicMock

    from backend.agent.web.streaming.agent_stream import (
        unwrap_retry_error,
        user_facing_error_message,
    )

    upstream = openai.InternalServerError(
        "Error code: 502 - upstream failed",
        response=httpx.Response(502, request=httpx.Request("POST", "http://x")),
        body=None,
    )
    attempt = MagicMock()
    attempt.exception.return_value = upstream
    retry_error = RetryError(attempt)

    assert unwrap_retry_error(retry_error) is upstream

    message, error_type = user_facing_error_message(retry_error)
    assert "RetryError" not in message
    assert "Future" not in message
    assert "AI 服务暂时不可用" in message
    assert error_type == "InternalServerError"

    # 普通异常走通用文案，类型名如实
    message2, error_type2 = user_facing_error_message(ValueError("boom"))
    assert "boom" not in message2
    assert error_type2 == "ValueError"
