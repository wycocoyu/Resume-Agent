"""Adapters between the resume domain objects and ``pi_core``.

The adapter centralizes protocol conversion and resume-specific lifecycle
rules, keeping the SSE layer independent from domain implementation details.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable
from typing import Any

from backend.agent.schema import Message, Role, ToolCall as LegacyToolCall
from backend.agent.pi_core.loop import AgentHooks
from backend.agent.pi_core.types import (
    AgentMessage,
    AssistantChunk,
    FinishDecision,
    LLMMessage,
    RuntimeToolResult,
    ToolCall,
    ToolDecision,
    ToolResult,
)


def to_core_messages(messages: Iterable[Message]) -> list[AgentMessage]:
    """Convert legacy memory messages without carrying UI-only fields forward."""

    result: list[AgentMessage] = []
    for message in messages:
        calls = tuple(
            ToolCall(
                id=call.id,
                name=call.function.name,
                arguments=_parse_arguments(call.function.arguments),
            )
            for call in (message.tool_calls or [])
        )
        result.append(
            AgentMessage(
                role=str(message.role.value if hasattr(message.role, "value") else message.role),  # type: ignore[arg-type]
                content=message.content or "",
                tool_calls=calls,
                tool_call_id=message.tool_call_id,
                name=message.name,
                metadata={"thinking": message.thought} if message.thought else {},
            )
        )
    return result


def to_legacy_messages(messages: Iterable[LLMMessage]) -> list[dict[str, Any]]:
    """Convert provider-neutral messages into OpenAI-compatible dictionaries."""

    result: list[dict[str, Any]] = []
    for message in messages:
        item: dict[str, Any] = {
            "role": message.role,
            "content": message.content,
        }
        if message.name:
            item["name"] = message.name
        if message.tool_call_id:
            item["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            item["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        result.append(item)
    return result


def append_core_messages_to_memory(
    memory: Any,
    messages: list[AgentMessage],
    base_len: int,
) -> None:
    """Commit pi-core messages through the legacy memory boundary."""

    for message in messages[base_len:]:
        if message.role == "assistant":
            calls = [
                LegacyToolCall(
                    id=call.id,
                    type="function",
                    function={
                        "name": call.name,
                        "arguments": json.dumps(
                            call.arguments,
                            ensure_ascii=False,
                        ),
                    },
                )
                for call in message.tool_calls
            ]
            memory.add_message(
                Message(
                    role=Role.ASSISTANT,
                    content=message.content or None,
                    tool_calls=calls or None,
                )
            )
        elif message.role == "tool":
            memory.add_message(
                Message.tool_message(
                    content=message.content,
                    name=message.name or "unknown",
                    tool_call_id=message.tool_call_id or "",
                )
            )


async def stream_resume_model(
    agent: Any,
    messages: list[LLMMessage],
    *,
    system_prompt: str | None = None,
    cancel_event: Any = None,
) -> AsyncIterator[AssistantChunk]:
    """Expose the runtime model stream as the core provider protocol."""

    async for chunk in agent.stream_model_response(
        to_legacy_messages(messages),
        system_prompt=system_prompt,
        cancel_event=cancel_event,
    ):
        yield chunk


def build_resume_hooks(agent: Any) -> AgentHooks:
    """Create the four lifecycle hooks for the resume runtime."""

    async def prepare_request(messages: list[Any]) -> list[Any]:
        """Apply provider safety defaults immediately before each model call.

        The normal route already configures DeepSeek with
        ``thinking.type=disabled``.  This fallback keeps the pi-core path safe
        for sessions created with an older in-memory LLM configuration or for
        tests that construct an agent directly.
        """

        prepare = getattr(agent, "prepare_model_request", None)
        if callable(prepare):
            return await prepare(messages)

        llm = getattr(agent, "llm", None)
        model = str(getattr(llm, "model", "") or "")
        if model.startswith("deepseek"):
            extra_body = getattr(llm, "extra_body", None)
            llm.extra_body = {
                **(extra_body if isinstance(extra_body, dict) else {}),
                "thinking": {"type": "disabled"},
            }
        return messages

    async def before_tool_call(call: ToolCall, _messages: list[AgentMessage]) -> ToolDecision:
        name = call.name
        policy = getattr(agent, "tool_block_reason", None)
        reason = policy(name) if callable(policy) else None
        if reason:
            return ToolDecision(block=True, reason=reason)
        return ToolDecision()

    async def after_tool_call(
        call: ToolCall,
        result: ToolResult,
        _messages: list[AgentMessage],
    ) -> ToolDecision:
        structured_type = (
            result.structured_content.get("type")
            if isinstance(result.structured_content, dict)
            else None
        )
        terminate_for_turn = False
        policy = getattr(agent, "get_turn_policy", None)
        snapshot = policy() if callable(policy) else None
        if snapshot is not None:
            terminate_for_turn = bool(
                getattr(snapshot, "diagnosis_only", False)
                and call.name == "cv_analyzer_agent"
            ) or bool(
                getattr(snapshot, "view_suggestions", False)
                and call.name == "cv_suggestions_agent"
            )
        return ToolDecision(
            terminate=(
                call.name in {"ask_user_question", "show_resume"}
                or structured_type == "approval_request"
                or terminate_for_turn
            )
        )

    async def finish_turn(
        turn: Any,
        _messages: list[AgentMessage],
    ) -> FinishDecision:
        is_finished = getattr(agent, "is_turn_finished", None)
        if callable(is_finished) and is_finished():
            return FinishDecision(
                action="end",
                reason="runtime marked the turn finished",
            )
        if (
            getattr(agent, "state", None) is not None
            and str(getattr(agent, "state")) == "FINISHED"
        ):
            return FinishDecision(
                action="end",
                reason="legacy agent marked the turn finished",
            )
        return FinishDecision(
            action="continue" if getattr(turn, "tool_calls", ()) else "end"
        )

    return AgentHooks(
        prepare_request=prepare_request,
        before_tool_call=before_tool_call,
        after_tool_call=after_tool_call,
        finish_turn=finish_turn,
    )


async def execute_resume_tool(
    agent: Any,
    call: ToolCall,
    _messages: list[AgentMessage],
) -> ToolResult:
    """Execute one core tool call through the runtime boundary."""

    execution = await agent.execute_tool(call)
    if isinstance(execution, RuntimeToolResult):
        output = execution.output
        structured = execution.structured_content
        progress_updates = execution.progress_updates
    elif isinstance(execution, tuple) and len(execution) == 2:
        # Compatibility for old runtime doubles and transitional adapters.
        output, structured = execution
        progress_updates = ()
    else:
        output, structured = str(execution or ""), {}
        progress_updates = ()

    text = str(output or "")
    error = text if text.startswith(("Error:", "错误：", "⚠️")) else None
    return ToolResult(
        output=text,
        error=error,
        structured_content=structured or None,
        supersede_key=_supersede_key(call.name),
        progress_updates=tuple(progress_updates),
    )


def _parse_arguments(raw: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {"_raw": raw or ""}
    return parsed if isinstance(parsed, dict) else {"_raw": raw or ""}


def _supersede_key(tool_name: str) -> str | None:
    if tool_name in {"cv_reader_agent", "get_resume_detail", "list_resumes"}:
        return "resume_read"
    if tool_name in {"cv_editor_agent", "generate_resume"}:
        return "resume_edit"
    return None
