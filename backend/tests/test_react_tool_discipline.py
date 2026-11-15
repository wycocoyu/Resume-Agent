import asyncio

from backend.agent.pi_core.loop import AgentHooks, run_agent_loop
from backend.agent.pi_core.types import (
    AgentMessage,
    AssistantChunk,
    FinishDecision,
    ModelTurn,
    ToolCall,
    ToolResult,
)


def test_pi_core_executes_model_tool_calls_in_one_ordered_batch():
    calls = []

    async def model(_messages):
        yield AssistantChunk(
            kind="text_delta",
            content="先执行第一项，再看结果决定下一步。",
        )
        yield AssistantChunk(
            kind="done",
            turn=ModelTurn(
                content="先执行第一项，再看结果决定下一步。",
                tool_calls=(
                    ToolCall("call-1", "list_resumes", {}),
                    ToolCall("call-2", "get_resume_detail", {}),
                ),
            ),
        )

    async def execute(call, _messages):
        calls.append(call.id)
        return ToolResult(output=f"done:{call.name}")

    async def collect():
        return [
            event
            async for event in run_agent_loop(
                [AgentMessage(role="user", content="读取我的简历")],
                model,
                execute,
                hooks=AgentHooks(
                    finish_turn=lambda *_args: FinishDecision(action="end")
                ),
                max_turns=1,
            )
        ]

    events = asyncio.run(collect())
    assert calls == ["call-1", "call-2"]
    assert [
        event.kind
        for event in events
        if event.kind.startswith("tool_execution")
    ] == [
        "tool_execution_start",
        "tool_execution_end",
        "tool_execution_start",
        "tool_execution_end",
    ]
