"""Tier 2 Boundary & Corner Tests: Feature 3 (PR #67 & Pi-Core Limits).

Authoritative specs:
- ORIGINAL_REQUEST §R1.3, PR #67, Issue #42
- backend/agent/pi_core/loop.py, backend/agent/pi_core/resume_adapter.py, backend/agent/pi_core/types.py
- Boundaries: premature stream abortion, unknown tool interception, corrupt argument parsing, dead tools pruning, concurrent execution isolation
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

from backend.agent.pi_core.loop import AgentHooks, _read_model_stream, run_agent_loop
from backend.agent.pi_core.resume_adapter import _parse_arguments
from backend.agent.pi_core.types import (
    AgentEvent,
    AgentMessage,
    AssistantChunk,
    FinishDecision,
    ModelTurn,
    ToolCall,
    ToolResult,
)


def test_t2_f03_01_premature_model_stream_termination_without_done():
    """TEST-T2-F03-01: Verify loop raises RuntimeError when model stream ends abruptly without done chunk."""
    async def _runner():
        async def abrupt_stream():
            yield AssistantChunk(kind="text_delta", content="Streaming partial text...")
            # Abruptly finish without done chunk

        with pytest.raises(RuntimeError, match="Model stream ended without a done chunk"):
            async for _ in _read_model_stream(abrupt_stream()):
                pass

    asyncio.run(_runner())


def test_t2_f03_02_unknown_unregistered_tool_name_handling():
    """TEST-T2-F03-02: Verify calling unknown/unregistered tool is safely handled without loop crash."""
    async def _runner():
        async def mock_model_stream(_messages):
            yield AssistantChunk(
                kind="done",
                turn=ModelTurn(
                    content="Calling unknown tool",
                    tool_calls=(ToolCall(id="call_999", name="unregistered_malicious_tool", arguments={}),),
                ),
            )

        async def mock_tool_executor(call: ToolCall, _messages):
            # Executor catches unknown tool and returns error ToolResult
            if call.name != "valid_tool":
                return ToolResult(output=f"Error: Tool '{call.name}' is not registered", error="Unregistered tool")
            return ToolResult(output="ok")

        hooks = AgentHooks(finish_turn=lambda _turn, _msg: FinishDecision(action="end"))

        events = []
        async for event in run_agent_loop(
            [AgentMessage(role="user", content="Test")],
            mock_model_stream,
            mock_tool_executor,
            hooks=hooks,
            max_turns=2,
        ):
            events.append(event)

        event_kinds = [e.kind for e in events]
        assert "tool_execution_start" in event_kinds
        assert "tool_execution_end" in event_kinds
        end_event = next(e for e in events if e.kind == "tool_execution_end")
        assert end_event.data.get("error") == "Unregistered tool"

    asyncio.run(_runner())


def test_t2_f03_03_malformed_tool_argument_string_recovery():
    """TEST-T2-F03-03: Verify malformed JSON argument string is parsed safely to _raw dictionary."""
    malformed_json = "{'unclosed_key': invalid_value,"
    parsed = _parse_arguments(malformed_json)
    assert isinstance(parsed, dict)
    assert parsed.get("_raw") == malformed_json

    none_parsed = _parse_arguments(None)
    assert none_parsed == {}


def test_t2_f03_04_dead_tools_pruning_verification():
    """TEST-T2-F03-04: Verify deleted OpenManus and Daytona sandbox tools cannot be imported."""
    with pytest.raises(ModuleNotFoundError):
        import backend.agent.tool.sandbox.sb_shell_tool  # type: ignore[import-not-found]

    with pytest.raises(ModuleNotFoundError):
        import backend.agent.tool.sandbox.sb_browser_tool  # type: ignore[import-not-found]


def test_t2_f03_05_concurrent_agent_loops_isolation():
    """TEST-T2-F03-05: Verify 10 concurrent agent loops execute without data cross-talk."""
    async def _runner():
        async def run_single_session(session_id: str):
            async def mock_stream(_messages):
                await asyncio.sleep(0.01)
                yield AssistantChunk(kind="text_delta", content=f"Resp for {session_id}")
                yield AssistantChunk(kind="done", turn=ModelTurn(content=f"Resp for {session_id}"))

            events = []
            async for event in run_agent_loop(
                [AgentMessage(role="user", content=f"Hello {session_id}")],
                mock_stream,
                lambda call, msg: ToolResult(output="none"),
                max_turns=1,
            ):
                events.append(event)
            return session_id, events

        tasks = [run_single_session(f"session_{i}") for i in range(10)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 10
        for session_id, events in results:
            end_event = next(e for e in events if e.kind == "message_end")
            end_content = end_event.data.get("content")
            assert session_id in end_content, f"Session {session_id} received cross-talk text: {end_content}"

    asyncio.run(_runner())
