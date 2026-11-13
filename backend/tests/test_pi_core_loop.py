from __future__ import annotations

import asyncio

from backend.agent.pi_core import (
    AgentHooks,
    AgentMessage,
    AssistantChunk,
    FinishDecision,
    ModelTurn,
    ToolCall,
    ToolDecision,
    ToolResult,
    run_agent_loop,
    transform_context,
)
from backend.agent.llm_streaming.tool_call_assembler import ToolCallAssembler


def _collect(coro):
    return asyncio.run(coro)


async def _events(stream, execute, *, hooks=None):
    messages = [AgentMessage(role="user", content="优化项目")]
    events = [
        event async for event in run_agent_loop(
            messages,
            stream,
            execute,
            hooks=hooks,
        )
    ]
    return messages, events


def test_assistant_events_are_emitted_before_tool_events():
    call = ToolCall("call-1", "cv_editor_agent", {"path": "projects[0]"})

    async def stream(_messages):
        yield AssistantChunk("text_delta", "我先检查项目经历。")
        yield AssistantChunk("thinking_delta", "需要保留用户事实。")
        yield AssistantChunk("done", turn=ModelTurn(content="我先检查项目经历。", thinking="需要保留用户事实。", tool_calls=(call,), stop_reason="tool_calls"))

    async def execute(_call, _messages):
        return ToolResult(output="已生成补丁", structured_content={"type": "resume_patch"})

    messages, events = _collect(
        _events(
            stream,
            execute,
            hooks=AgentHooks(
                finish_turn=lambda _turn, _messages: FinishDecision(action="end")
            ),
        )
    )
    kinds = [event.kind for event in events]
    assert kinds == [
        "message_start",
        "message_update",
        "message_update",
        "message_end",
        "tool_execution_start",
        "tool_execution_end",
    ]
    assert messages[-1].structured_content == {"type": "resume_patch"}


def test_truncated_tool_call_is_never_executed():
    call = ToolCall("call-1", "cv_editor_agent", {"path": "projects[0]"})
    executed = False

    async def stream(_messages):
        yield AssistantChunk("done", turn=ModelTurn(tool_calls=(call,), stop_reason="length"))

    async def execute(_call, _messages):
        nonlocal executed
        executed = True
        return ToolResult(output="should not happen")

    messages, events = _collect(
        _events(
            stream,
            execute,
            hooks=AgentHooks(
                finish_turn=lambda _turn, _messages: FinishDecision(action="end")
            ),
        )
    )
    assert executed is False
    assert any(event.data.get("truncated") for event in events)
    assert messages[-1].content.startswith("Tool call was truncated")


def test_hooks_can_block_and_terminate_after_tool():
    call = ToolCall("call-1", "cv_editor_agent", {})

    async def stream(_messages):
        yield AssistantChunk("done", turn=ModelTurn(tool_calls=(call,), stop_reason="tool_calls"))

    async def execute(_call, _messages):
        raise AssertionError("blocked tool must not execute")

    async def before(_call, _messages):
        return ToolDecision(block=True, reason="只读诊断轮禁止修改")

    async def after(_call, result, _messages):
        return ToolDecision(terminate=True)

    async def finish(_turn, _messages):
        return FinishDecision(action="end", reason="等待用户")

    _, events = _collect(
        _events(
            stream,
            execute,
            hooks=AgentHooks(
                before_tool_call=before,
                after_tool_call=after,
                finish_turn=finish,
            ),
        )
    )
    assert events[-1].kind == "tool_execution_end"
    assert events[-1].data["blocked"] is True


def test_superseded_tool_output_is_compacted_without_mutating_history():
    old = AgentMessage(role="tool", content="old resume", supersede_key="resume")
    new = AgentMessage(role="tool", content="new resume", supersede_key="resume")
    history = [old, new]
    transformed = transform_context(history)
    assert history[0].content == "old resume"
    assert transformed[0].content == "[Superseded by a newer read/edit]"
    assert transformed[1].content == "new resume"


def test_tool_assembler_does_not_mark_length_as_safe():
    assembler = ToolCallAssembler()
    assembler.ingest(
        [
            {
                "index": 0,
                "id": "call-1",
                "function": {"name": "cv_editor_agent", "arguments": "{\"x\":"},
            }
        ]
    )
    assert assembler.is_ready("length") is False
