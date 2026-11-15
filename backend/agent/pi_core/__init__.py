"""Small, dependency-free agent loop primitives.

The package is intentionally independent from the retired inheritance
hierarchy. The web adapter can consume its events without exposing
the internal message representation to an LLM provider.
"""

from .context import CompactionPolicy, compact_context, convert_to_llm, transform_context
from .loop import AgentHooks, run_agent_loop
from .metrics import get_pi_core_metrics, metrics_registry
from .resume_coordinator import ResumeTurnCoordinator
from .resume_result_adapter import ResumeResultAdapter
from .resume_adapter import (
    build_resume_hooks,
    append_core_messages_to_memory,
    execute_resume_tool,
    stream_resume_model,
    to_core_messages,
    to_legacy_messages,
)
from .sse_adapter import to_legacy_stream_event
from .stream import PiCoreAgentStream
from .turn_policy import TurnPolicySnapshot
from .types import (
    AgentEvent,
    AgentMessage,
    AssistantChunk,
    FinishDecision,
    LLMMessage,
    ModelTurn,
    ToolCall,
    ToolDecision,
    RuntimeToolResult,
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
    "RuntimeToolResult",
    "ToolResult",
    "convert_to_llm",
    "CompactionPolicy",
    "compact_context",
    "run_agent_loop",
    "get_pi_core_metrics",
    "metrics_registry",
    "build_resume_hooks",
    "append_core_messages_to_memory",
    "execute_resume_tool",
    "stream_resume_model",
    "to_core_messages",
    "to_legacy_messages",
    "to_legacy_stream_event",
    "PiCoreAgentStream",
    "transform_context",
    "TurnPolicySnapshot",
    "ResumeTurnCoordinator",
    "ResumeResultAdapter",
]
