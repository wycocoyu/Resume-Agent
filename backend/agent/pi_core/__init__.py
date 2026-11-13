"""Small, dependency-free agent loop primitives.

The package is intentionally independent from the legacy OpenManus-style
agent hierarchy.  The web adapter can consume its events without exposing
the internal message representation to an LLM provider.
"""

from .context import convert_to_llm, transform_context
from .loop import AgentHooks, run_agent_loop
from .resume_adapter import (
    build_resume_hooks,
    execute_resume_tool,
    stream_resume_model,
    to_core_messages,
    to_legacy_messages,
)
from .sse_adapter import to_legacy_stream_event
from .stream import PiCoreAgentStream
from .types import (
    AgentEvent,
    AgentMessage,
    AssistantChunk,
    FinishDecision,
    LLMMessage,
    ModelTurn,
    ToolCall,
    ToolDecision,
    ToolResult,
)

__all__ = [
    "AgentEvent",
    "AgentHooks",
    "AgentMessage",
    "AssistantChunk",
    "FinishDecision",
    "LLMMessage",
    "ModelTurn",
    "ToolCall",
    "ToolDecision",
    "ToolResult",
    "convert_to_llm",
    "run_agent_loop",
    "build_resume_hooks",
    "execute_resume_tool",
    "stream_resume_model",
    "to_core_messages",
    "to_legacy_messages",
    "to_legacy_stream_event",
    "PiCoreAgentStream",
    "transform_context",
]
