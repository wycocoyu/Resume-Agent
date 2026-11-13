"""Adapters between the existing Resume-Agent objects and ``pi_core``.

The adapter deliberately keeps the legacy Manus object alive during migration.
It centralizes protocol conversion and resume-specific lifecycle rules so the
SSE layer can switch execution engines without duplicating business policy.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable
from typing import Any

from backend.agent.schema import Message, ToolCall as LegacyToolCall
from backend.agent.pi_core.loop import AgentHooks
from backend.agent.pi_core.types import (
    AgentMessage,
    AssistantChunk,
    FinishDecision,
    LLMMessage,
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


async def stream_resume_model(
    agent: Any,
    messages: list[LLMMessage],
    *,
    system_prompt: str | None = None,
    cancel_event: Any = None,
) -> AsyncIterator[AssistantChunk]:
    """Expose the existing LLM client as the core model-stream protocol."""

    prompt = system_prompt if system_prompt is not None else getattr(agent, "system_prompt", "")
    system_msgs = [{"role": "system", "content": prompt}] if prompt else None
    tools = agent.available_tools.to_params()
    async for chunk in agent.llm.stream_tool_response(
        messages=to_legacy_messages(messages),
        system_msgs=system_msgs,
        tools=tools,
        tool_choice=getattr(agent, "tool_choices", "auto"),
        cancel_event=cancel_event,
    ):
        yield chunk


def build_resume_hooks(agent: Any) -> AgentHooks:
    """Create the four lifecycle hooks using existing Manus state."""

    async def before_tool_call(call: ToolCall, _messages: list[AgentMessage]) -> ToolDecision:
        turn = getattr(agent, "_turn", None)
        name = call.name
        if turn is None:
            return ToolDecision()

        blocked: tuple[bool, str] = (
            (
                bool(getattr(turn, "read_only", False)),
                "错误：本轮为只读查看请求，禁止修改简历。",
            ),
            (
                bool(getattr(turn, "view_suggestions", False)),
                "错误：本轮只展示诊断建议，不修改简历。",
            ),
            (
                bool(getattr(turn, "diagnosis_only", False)),
                "错误：本轮只做简历诊断，不修改简历。",
            ),
            (
                bool(getattr(turn, "diagnosis_gap_collect", False)),
                "错误：本轮只收集缺失信息，不修改简历。",
            ),
        )
        protected_tools = {
            "cv_editor_agent",
            "str_replace_editor",
            "ask_human",
            "ask_user_question",
        }
        for enabled, reason in blocked:
            if enabled and name in protected_tools:
                return ToolDecision(block=True, reason=reason)
        return ToolDecision()

    async def after_tool_call(
        call: ToolCall,
        _result: ToolResult,
        _messages: list[AgentMessage],
    ) -> ToolDecision:
        pending_approval = bool(getattr(agent, "_halt_for_pending_approval", False))
        pending_question = bool(getattr(agent, "_halt_for_ask_question", False))
        return ToolDecision(
            terminate=(
                call.name in {"ask_user_question", "show_resume"}
                or pending_approval
                or pending_question
            )
        )

    async def finish_turn(
        turn: Any,
        _messages: list[AgentMessage],
    ) -> FinishDecision:
        if getattr(agent, "state", None) is not None and str(getattr(agent, "state")) == "FINISHED":
            return FinishDecision(action="end", reason="legacy agent marked the turn finished")
        return FinishDecision(
            action="continue" if getattr(turn, "tool_calls", ()) else "end"
        )

    return AgentHooks(
        before_tool_call=before_tool_call,
        after_tool_call=after_tool_call,
        finish_turn=finish_turn,
    )


async def execute_resume_tool(
    agent: Any,
    call: ToolCall,
    _messages: list[AgentMessage],
) -> ToolResult:
    """Execute one core tool call through the existing Manus implementation."""

    legacy_call = LegacyToolCall(
        id=call.id,
        type="function",
        function={"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)},
    )
    output = await agent.execute_tool(legacy_call)
    structured = {}
    structured_results = getattr(agent, "_tool_structured_results", {})
    if isinstance(structured_results, dict):
        candidate = structured_results.pop(call.id, None)
        if isinstance(candidate, dict):
            structured = candidate

    text = str(output or "")
    error = text if text.startswith(("Error:", "错误：", "⚠️")) else None
    return ToolResult(
        output=text,
        error=error,
        structured_content=structured or None,
        supersede_key=_supersede_key(call.name),
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
