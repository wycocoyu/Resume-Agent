"""Typed messages and events for the linear agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolCall:
    """A fully assembled model tool call."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AgentMessage:
    """Internal message that may carry UI and resume-specific metadata."""

    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None
    structured_content: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    supersede_key: str | None = None


@dataclass(frozen=True)
class LLMMessage:
    """Provider-neutral message sent to an LLM adapter."""

    role: Role
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class AssistantChunk:
    """One piece of a streamed assistant response."""

    kind: Literal["text_delta", "thinking_delta", "done"]
    content: str = ""
    turn: "ModelTurn | None" = None


@dataclass(frozen=True)
class ModelTurn:
    """Completed assistant response assembled by the model adapter."""

    content: str = ""
    thinking: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    stop_reason: str | None = None


@dataclass(frozen=True)
class ToolResult:
    """Normalized result returned by a tool executor."""

    output: str = ""
    error: str | None = None
    structured_content: dict[str, Any] | None = None
    supersede_key: str | None = None


@dataclass(frozen=True)
class ToolDecision:
    """Decision made immediately before a tool is executed."""

    block: bool = False
    reason: str = ""
    terminate: bool = False


@dataclass(frozen=True)
class FinishDecision:
    """Decision made after one model/tool turn."""

    action: Literal["end", "continue"] = "end"
    reason: str = ""


@dataclass(frozen=True)
class AgentEvent:
    """Internal event stream consumed by SSE or another harness adapter."""

    kind: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.kind, "data": dict(self.data)}
