"""A single-coroutine, ordered model/tool event loop."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass, replace
from typing import Any

from .context import convert_to_llm, transform_context
from .types import (
    AgentEvent,
    AgentMessage,
    AssistantChunk,
    FinishDecision,
    ModelTurn,
    ToolCall,
    ToolDecision,
    ToolResult,
)


async def _resolve(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


@dataclass
class AgentHooks:
    """Optional lifecycle hooks for one agent loop."""

    prepare_request: Callable[[list[Any]], Any] | None = None
    before_tool_call: Callable[[ToolCall, list[AgentMessage]], Any] | None = None
    after_tool_call: Callable[[ToolCall, ToolResult, list[AgentMessage]], Any] | None = None
    finish_turn: Callable[[ModelTurn, list[AgentMessage]], Any] | None = None


ModelStream = Callable[[list[Any]], AsyncIterable[AssistantChunk]]
ToolExecutor = Callable[[ToolCall, list[AgentMessage]], Any]


async def _read_model_stream(stream: AsyncIterable[AssistantChunk]) -> AsyncIterator[AgentEvent]:
    """Collect one model response while yielding ordered deltas."""

    turn: ModelTurn | None = None
    yield AgentEvent("message_start")
    async for chunk in stream:
        if chunk.kind in {"text_delta", "thinking_delta"}:
            if chunk.content:
                yield AgentEvent("message_update", {"delta_type": chunk.kind, "text": chunk.content})
        elif chunk.kind == "done":
            turn = chunk.turn
        else:
            raise ValueError(f"Unknown assistant chunk kind: {chunk.kind}")
    if turn is None:
        raise RuntimeError("Model stream ended without a done chunk")
    # The caller retrieves the completed turn through a private marker event.
    yield AgentEvent("_model_turn", {"turn": turn})


async def _consume_tool_result(value: Any) -> AsyncIterator[tuple[str, ToolResult | None]]:
    """Support a single result or a streamed tool result without queues."""

    if hasattr(value, "__aiter__"):
        async for item in value:
            if isinstance(item, ToolResult):
                yield "done", item
            elif isinstance(item, str):
                yield "update", ToolResult(output=item)
            else:
                raise TypeError("Tool stream items must be ToolResult or str")
        return
    result = await _resolve(value)
    if not isinstance(result, ToolResult):
        raise TypeError("Tool executor must return ToolResult")
    yield "done", result


async def run_agent_loop(
    messages: list[AgentMessage],
    stream_assistant_response: ModelStream,
    execute_tool_call: ToolExecutor,
    *,
    hooks: AgentHooks | None = None,
    max_turns: int = 20,
) -> AsyncIterator[AgentEvent]:
    """Run model and tools in a deterministic linear sequence.

    The assistant message is committed to ``messages`` before ``message_end``.
    Tool events are emitted only after the assistant stream is complete.
    """

    hooks = hooks or AgentHooks()
    for turn_index in range(max_turns):
        context = transform_context(messages)
        llm_messages = convert_to_llm(context)
        if hooks.prepare_request:
            llm_messages = await _resolve(hooks.prepare_request(llm_messages))

        completed_turn: ModelTurn | None = None
        async for event in _read_model_stream(stream_assistant_response(llm_messages)):
            if event.kind == "_model_turn":
                completed_turn = event.data["turn"]
                continue
            yield event
        if completed_turn is None:
            raise RuntimeError("Model stream did not produce a completed turn")

        assistant = AgentMessage(
            role="assistant",
            content=completed_turn.content,
            tool_calls=completed_turn.tool_calls,
            metadata={"thinking": completed_turn.thinking} if completed_turn.thinking else {},
        )
        messages.append(assistant)
        # Commit the complete assistant message before exposing message_end.
        yield AgentEvent(
            "message_end",
            {
                "stop_reason": completed_turn.stop_reason,
                "content": completed_turn.content,
                "thinking": completed_turn.thinking,
                "tool_calls": completed_turn.tool_calls,
            },
        )

        if completed_turn.stop_reason == "length" and completed_turn.tool_calls:
            for call in completed_turn.tool_calls:
                error = ToolResult(error="Tool call was truncated; please regenerate the complete call.")
                messages.append(
                    AgentMessage(
                        role="tool",
                        content=error.error or "",
                        tool_call_id=call.id,
                        name=call.name,
                    )
                )
                yield AgentEvent(
                    "tool_execution_end",
                    {"tool_call_id": call.id, "tool": call.name, "error": error.error, "truncated": True},
                )
            decision = await _finish_turn(hooks, completed_turn, messages, default="continue")
            if decision.action == "end":
                return
            continue

        should_terminate = False
        for call in completed_turn.tool_calls:
            decision = ToolDecision()
            if hooks.before_tool_call:
                decision = await _resolve(hooks.before_tool_call(call, messages))
            if decision.block:
                result = ToolResult(error=decision.reason or "Tool call blocked")
                blocked = True
            else:
                blocked = False
                yield AgentEvent(
                    "tool_execution_start",
                    {"tool_call_id": call.id, "tool": call.name, "arguments": call.arguments},
                )
                result = ToolResult()
                async for phase, partial in _consume_tool_result(execute_tool_call(call, messages)):
                    if phase == "update":
                        assert partial is not None
                        yield AgentEvent(
                            "tool_execution_update",
                            {"tool_call_id": call.id, "tool": call.name, "text": partial.output},
                        )
                    else:
                        assert partial is not None
                        result = partial

                for progress in result.progress_updates:
                    yield AgentEvent(
                        "tool_execution_update",
                        {
                            "tool_call_id": call.id,
                            "tool": call.name,
                            "text": str(progress.get("summary") or progress.get("content") or ""),
                            "stage_id": progress.get("stage_id") or "progress",
                            "current": progress.get("current"),
                            "total": progress.get("total"),
                            "label": progress.get("label"),
                            "stages": progress.get("stages") or [],
                        },
                    )

            if hooks.after_tool_call:
                after = await _resolve(hooks.after_tool_call(call, result, messages))
                if after.structured_content:
                    result = replace(
                        result,
                        structured_content={
                            **(result.structured_content or {}),
                            **after.structured_content,
                        },
                    )
                should_terminate = after.terminate

            if blocked:
                yield AgentEvent(
                    "tool_execution_end",
                    {
                        "tool_call_id": call.id,
                        "tool": call.name,
                        "error": result.error,
                        "structured_content": result.structured_content,
                        "blocked": True,
                    },
                )
            else:
                yield AgentEvent(
                    "tool_execution_end",
                    {
                        "tool_call_id": call.id,
                        "tool": call.name,
                        "output": result.output,
                        "error": result.error,
                        "structured_content": result.structured_content,
                    },
                )

            messages.append(
                AgentMessage(
                    role="tool",
                    content=result.error or result.output,
                    tool_call_id=call.id,
                    name=call.name,
                    structured_content=result.structured_content,
                    supersede_key=result.supersede_key,
                )
            )
            if decision.terminate or should_terminate:
                break

        decision = await _finish_turn(hooks, completed_turn, messages, default="continue" if completed_turn.tool_calls else "end")
        if should_terminate or decision.action == "end":
            return

    raise RuntimeError(f"Agent exceeded max_turns={max_turns}")


async def _finish_turn(
    hooks: AgentHooks,
    turn: ModelTurn,
    messages: list[AgentMessage],
    *,
    default: str,
) -> FinishDecision:
    if hooks.finish_turn:
        result = await _resolve(hooks.finish_turn(turn, messages))
        if not isinstance(result, FinishDecision):
            raise TypeError("finish_turn must return FinishDecision")
        return result
    return FinishDecision(action=default)  # type: ignore[arg-type]
