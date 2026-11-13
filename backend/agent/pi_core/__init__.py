"""Small, dependency-free agent loop primitives.

The package is intentionally independent from the legacy OpenManus-style
agent hierarchy.  The web adapter can consume its events without exposing
the internal message representation to an LLM provider.
"""

from .context import convert_to_llm, transform_context
from .loop import AgentHooks, run_agent_loop
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
    "transform_context",
]
