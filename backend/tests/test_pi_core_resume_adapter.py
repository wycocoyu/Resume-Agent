from __future__ import annotations

import asyncio
from types import SimpleNamespace

from backend.agent.pi_core import (
    AgentMessage,
    ToolCall,
    ToolResult,
    build_resume_hooks,
    execute_resume_tool,
    to_core_messages,
    to_legacy_messages,
)
from backend.agent.pi_core.turn_policy import blocked_tool_reason
from backend.agent.schema import Message


def test_legacy_messages_round_trip_to_provider_shape():
    legacy = [
        Message.user_message("优化项目"),
        Message.assistant_message("开始检查"),
    ]
    core = to_core_messages(legacy)
    assert core[0].role == "user"
    assert to_legacy_messages(
        [
            type("Llm", (), {
                "role": "assistant",
                "content": "好的",
                "name": None,
                "tool_call_id": None,
                "tool_calls": (),
            })()
        ]
    ) == [{"role": "assistant", "content": "好的"}]


def test_resume_tool_adapter_preserves_structured_result():
    class FakeAgent:
        async def execute_tool(self, call):
            assert call.name == "cv_editor_agent"
            return (
                "已生成补丁",
                {"type": "resume_patch", "paths": ["projects[0].description"]},
            )

    result = asyncio.run(
        execute_resume_tool(
            FakeAgent(),
            ToolCall("call-1", "cv_editor_agent", {"path": "projects[0].description"}),
            [],
        )
    )
    assert result.output == "已生成补丁"
    assert result.structured_content["type"] == "resume_patch"
    assert result.supersede_key == "resume_edit"


def test_resume_hooks_block_read_only_editor_and_stop_question_tool():
    def tool_block_reason(tool_name):
        return "只读轮禁止修改工具" if tool_name == "cv_editor_agent" else None

    agent = SimpleNamespace(
        tool_block_reason=tool_block_reason,
        state="IDLE",
    )
    hooks = build_resume_hooks(agent)
    decision = asyncio.run(
        hooks.before_tool_call(ToolCall("1", "cv_editor_agent", {}), [])
    )
    assert decision.block is True

    after = asyncio.run(
        hooks.after_tool_call(
            ToolCall("2", "ask_user_question", {}),
            ToolResult(output="question"),
            [],
        )
    )
    assert after.terminate is True


def test_turn_policy_matches_legacy_guard_matrix():
    turn = SimpleNamespace(
        read_only=False,
        view_suggestions=True,
        diagnosis_only=False,
        diagnosis_apply=False,
        diagnosis_gap_collect=False,
    )

    assert blocked_tool_reason(turn, "cv_analyzer_agent")
    assert blocked_tool_reason(turn, "ask_user_question")
    assert blocked_tool_reason(turn, "cv_suggestions_agent") is None

    turn.view_suggestions = False
    turn.diagnosis_apply = True
    assert blocked_tool_reason(turn, "ask_human")
    assert blocked_tool_reason(turn, "ask_user_question")
    assert blocked_tool_reason(turn, "cv_editor_agent") is None

    turn.diagnosis_apply = False
    turn.diagnosis_gap_collect = True
    assert blocked_tool_reason(turn, "cv_editor_agent")
    assert blocked_tool_reason(turn, "ask_user_question") is None


def test_resume_hooks_stop_on_structured_approval_without_legacy_halt_flags():
    agent = SimpleNamespace(_turn=None, state="IDLE")
    hooks = build_resume_hooks(agent)

    after = asyncio.run(
        hooks.after_tool_call(
            ToolCall("2", "send_email", {}),
            ToolResult(
                output="等待确认",
                structured_content={
                    "type": "approval_request",
                    "payload": {"approval_id": "approval-1"},
                },
            ),
            [],
        )
    )

    assert after.terminate is True


def test_resume_hooks_prepare_deepseek_request_disables_native_thinking():
    agent = SimpleNamespace(
        llm=SimpleNamespace(model="deepseek-flash", extra_body=None),
        _turn=None,
        state="IDLE",
    )
    hooks = build_resume_hooks(agent)
    messages = [object()]

    prepared = asyncio.run(hooks.prepare_request(messages))

    assert prepared is messages
    assert agent.llm.extra_body == {"thinking": {"type": "disabled"}}


def test_resume_hooks_prefer_runtime_request_boundary():
    calls = []

    class Runtime:
        async def prepare_model_request(self, messages):
            calls.append(messages)
            return ["prepared"]

    hooks = build_resume_hooks(Runtime())
    messages = [object()]

    prepared = asyncio.run(hooks.prepare_request(messages))

    assert prepared == ["prepared"]
    assert calls == [messages]


def test_resume_hooks_prefer_runtime_lifecycle_boundary():
    class Runtime:
        def is_turn_finished(self):
            return True

    hooks = build_resume_hooks(Runtime())
    decision = asyncio.run(
        hooks.finish_turn(type("Turn", (), {"tool_calls": ()})(), [])
    )

    assert decision.action == "end"


def test_resume_hooks_preserve_other_deepseek_request_options():
    agent = SimpleNamespace(
        llm=SimpleNamespace(
            model="deepseek-flash",
            extra_body={"response_format": {"type": "json_object"}},
        ),
        _turn=None,
        state="IDLE",
    )
    hooks = build_resume_hooks(agent)

    asyncio.run(hooks.prepare_request([]))

    assert agent.llm.extra_body == {
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
    }
