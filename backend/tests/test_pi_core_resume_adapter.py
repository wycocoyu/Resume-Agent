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
        _tool_structured_results = {
            "call-1": {"type": "resume_patch", "paths": ["projects[0].description"]}
        }

        async def execute_tool(self, call):
            assert call.function.name == "cv_editor_agent"
            return "已生成补丁"

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
    agent = SimpleNamespace(
        _turn=SimpleNamespace(
            read_only=True,
            view_suggestions=False,
            diagnosis_only=False,
            diagnosis_gap_collect=False,
        ),
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
