"""Translate pi-core events into the existing Resume-Agent SSE events."""

from __future__ import annotations

from typing import Any

from backend.agent.web.streaming.events import (
    AnswerEvent,
    StreamEvent,
    ThoughtEvent,
    ToolCallEvent,
    ToolProgressEvent,
    ToolResultEvent,
)

from .types import AgentEvent


def to_legacy_stream_event(
    event: AgentEvent,
    *,
    session_id: str | None,
    step_id: int,
) -> StreamEvent | None:
    """Map one internal event without changing the public SSE envelope.

    ``message_start`` and ``message_end`` are internal lifecycle markers.  The
    legacy protocol represents their useful content through answer/thought
    chunks, so those two markers intentionally produce no standalone event.
    """

    data: dict[str, Any] = event.data
    if event.kind == "message_update":
        delta_type = data.get("delta_type")
        text = str(data.get("text") or "")
        if not text:
            return None
        if delta_type == "thinking_delta":
            return ThoughtEvent(
                thought=text,
                step_id=step_id,
                session_id=session_id,
                is_complete=False,
            )
        if delta_type == "text_delta":
            return AnswerEvent(
                content=text,
                delta=text,
                is_complete=False,
                session_id=session_id,
            )
        return None

    if event.kind == "tool_execution_start":
        return ToolCallEvent(
            tool_name=str(data.get("tool") or ""),
            tool_args=data.get("arguments") if isinstance(data.get("arguments"), dict) else {},
            step_id=step_id,
            tool_call_id=str(data.get("tool_call_id") or ""),
            session_id=session_id,
        )

    if event.kind == "tool_execution_update":
        return ToolProgressEvent(
            tool_call_id=str(data.get("tool_call_id") or ""),
            stage_id=str(data.get("stage_id") or "pi-core"),
            summary=str(data.get("text") or ""),
            current=data.get("current"),
            total=data.get("total"),
            label=data.get("label"),
            stages=data.get("stages") or [],
            session_id=session_id,
        )

    if event.kind == "tool_execution_end":
        output = str(data.get("error") or data.get("output") or "")
        return ToolResultEvent(
            tool_name=str(data.get("tool") or ""),
            result=output,
            step_id=step_id,
            tool_call_id=str(data.get("tool_call_id") or ""),
            is_error=bool(data.get("error")),
            session_id=session_id,
            structured_data=data.get("structured_content"),
        )

    return None
