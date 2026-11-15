import asyncio
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[2]))

from backend.core.logger import setup_logging

setup_logging(False, "INFO", "logs/test")

from backend.agent.pi_core.resume_agent import ResumeAgentRuntime
from backend.agent.application.conversation.conversation_state import Intent
from backend.agent.prompt.greeting import (
    GREETING_FAST_PATH_PROMPT,
    build_greeting_message,
    greeting_fallback,
)
from backend.agent.prompt.voice import (
    VISIBLE_ACTION_NARRATION_GUIDANCE,
    apply_visible_action_narration_guidance,
)
from backend.agent.tool.cv_reader_tool import ReadCVContext
from backend.agent.tool.resume_data_store import ResumeDataStore
from backend.agent.schema import Message, Role
from backend.agent.web.streaming.agent_stream import AgentStream
from backend.agent.web.streaming.state_machine import AgentStateMachine


def _suggestions_from(content: str) -> list[dict]:
    match = re.search(r"%%SUGGESTIONS%%(.*?)%%END%%", content, re.DOTALL)
    assert match, "问候必须携带建议按钮协议"
    return json.loads(match.group(1))


def test_visible_action_guidance_defines_soul_without_raw_reasoning():
    assert "不是原始思维链" in VISIBLE_ACTION_NARRATION_GUIDANCE
    assert "微判断" in VISIBLE_ACTION_NARRATION_GUIDANCE
    assert "用户想" in VISIBLE_ACTION_NARRATION_GUIDANCE
    assert "先不急着动笔" in VISIBLE_ACTION_NARRATION_GUIDANCE
    assert "覆盖面 + 证据感" in VISIBLE_ACTION_NARRATION_GUIDANCE
    assert "结构完整度、成果证据、面试风险、岗位匹配" in VISIBLE_ACTION_NARRATION_GUIDANCE
    assert "不是原始思维链" in VISIBLE_ACTION_NARRATION_GUIDANCE

    merged = apply_visible_action_narration_guidance("BASE")
    assert merged.startswith("BASE")
    assert merged.endswith(VISIBLE_ACTION_NARRATION_GUIDANCE)


def test_greeting_prompt_uses_context_and_companion_voice():
    assert "接住" in GREETING_FAST_PATH_PROMPT
    assert "看见" in GREETING_FAST_PATH_PROMPT
    assert "推进" in GREETING_FAST_PATH_PROMPT
    assert "简历已经加载" in GREETING_FAST_PATH_PROMPT
    assert "有什么可以帮您" in GREETING_FAST_PATH_PROMPT


def test_loaded_resume_greeting_has_contextual_copy_and_actions():
    fallback = greeting_fallback(has_resume=True)
    assert "右边这份简历" in fallback
    assert "简历搭子" in fallback

    content = build_greeting_message(fallback, has_resume=True)
    suggestions = _suggestions_from(content)
    assert [item["text"] for item in suggestions] == [
        "先诊断一下",
        "按目标岗位改",
        "继续完善简历",
    ]

    model_marker = (
        '模型正文\n%%SUGGESTIONS%%[{"text":"旧按钮","msg":"旧消息"}]%%END%%'
    )
    normalized = build_greeting_message(model_marker, has_resume=True)
    assert normalized.count("%%SUGGESTIONS%%") == 1
    assert [item["text"] for item in _suggestions_from(normalized)] == [
        "先诊断一下",
        "按目标岗位改",
        "继续完善简历",
    ]


def test_empty_resume_greeting_does_not_pretend_to_see_resume():
    fallback = greeting_fallback(has_resume=False)
    assert "右边这份简历" not in fallback
    assert "？" in fallback

    suggestions = _suggestions_from(
        build_greeting_message(fallback, has_resume=False)
    )
    assert [item["text"] for item in suggestions] == [
        "选择已有简历",
        "从零做一份",
        "先聊求职方向",
    ]


def test_greeting_runtime_has_no_retired_think_lifecycle():
    session_id = "soulful-greeting-fallback"
    ResumeDataStore.clear_data(session_id)
    agent = ResumeAgentRuntime(session_id=session_id, user_id="uTest32CharBetterAuthIdXyz01")
    assert not hasattr(agent, "think")
    assert not hasattr(agent, "act")
    assert "今天想从哪儿开始？" in greeting_fallback(has_resume=False)


def test_greeting_stream_emits_public_thought_before_response(monkeypatch):
    session_id = "soulful-greeting-stream"
    ResumeDataStore.clear_data(session_id)
    agent = ResumeAgentRuntime(session_id=session_id, user_id="uTest32CharBetterAuthIdXyz01")

    async def fake_decide(*_args, **_kwargs):
        return SimpleNamespace(
            intent=Intent.GREETING,
            intent_source="test",
            enhanced_query="你好",
            compound_hint=None,
        )

    async def fake_prompts(*_args, **_kwargs):
        return "BASE", ""

    async def fake_stream(**_kwargs):
        from backend.agent.pi_core.types import AssistantChunk, ModelTurn

        text = "嗨～我是 coco，你的简历搭子。今天想从哪儿开始？"
        yield AssistantChunk(kind="text_delta", content=text)
        yield AssistantChunk(kind="done", turn=ModelTurn(content=text))

    monkeypatch.setattr(agent.domain_agent._intent_router, "decide", fake_decide)
    monkeypatch.setattr(agent.domain_agent, "_generate_dynamic_prompts", fake_prompts)
    monkeypatch.setattr(agent.llm, "stream_tool_response", fake_stream)

    async def collect_events():
        async def ignore_event(_event):
            return None

        stream = AgentStream(
            agent,
            session_id,
            AgentStateMachine(session_id),
            ignore_event,
        )
        return [event.to_dict() async for event in stream.execute("你好")]

    events = asyncio.run(collect_events())
    response_index = next(
        i
        for i, event in enumerate(events)
        if event["type"] == "answer" and event["data"].get("is_complete")
    )

    assert events[response_index]["data"]["content"].startswith("嗨～我是 coco")


def test_committed_resume_sample_formats_as_grounded_context():
    sample_path = Path(__file__).parents[2] / "简历测试" / "韦宇测试.json"
    resume_data = json.loads(sample_path.read_text(encoding="utf-8"))
    reader = ReadCVContext()
    reader.set_resume_data(resume_data)

    context = reader._format_full_resume(mask_pii=True)

    assert "Name: 韦宇" in context
    assert "Target Position: 大模型应用开发/后端开发" in context
    assert "## Work Experience" in context
    assert "## Open Source" in context
    assert "## Skills" in context
    assert "Email:" not in context
    assert "Phone:" not in context


def test_historical_resume_shape_does_not_drop_all_context():
    reader = ReadCVContext()
    reader.set_resume_data(
        {
            "name": "历史用户",
            "contact": {"email": "hidden@example.com"},
            "objective": "后端开发",
            "education": [
                {
                    "title": "示例大学",
                    "subtitle": "计算机科学 本科",
                    "date": "2020-2024",
                    "details": ["主修数据结构", "GPA 3.8"],
                }
            ],
            "internships": [
                {
                    "title": "示例公司",
                    "subtitle": "后端实习生",
                    "date": "2023",
                    "highlights": ["负责订单服务"],
                }
            ],
            "skills": [{"category": "开发", "details": ["Python", "Go"]}],
            "awards": ["校级一等奖学金"],
        }
    )

    context = reader._format_full_resume(mask_pii=True)

    assert "Name: 历史用户" in context
    assert "Target Position: 后端开发" in context
    assert "示例大学" in context
    assert "示例公司" in context
    assert "Python、Go" in context
    assert "校级一等奖学金" in context
    assert "hidden@example.com" not in context
