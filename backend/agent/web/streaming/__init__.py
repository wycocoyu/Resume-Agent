"""Streaming module for agent execution events.

This module provides:
- Event types and data models for streaming
- Agent execution state management
- State machine for agent lifecycle
- Stream output handler
"""

from backend.agent.web.streaming.events import (
    EventType,
    StreamEvent,
    ThoughtEvent,
    ToolCallEvent,
    ToolResultEvent,
    ToolProgressEvent,
    AnswerEvent,
    AgentStartEvent,
    AgentEndEvent,
    AgentErrorEvent,
    SystemEvent,
)
from backend.agent.web.streaming.agent_state import (
    AgentState,
    StateInfo,
    StateTransitionError,
)
from backend.agent.web.streaming.state_machine import AgentStateMachine

# ``agent_stream`` imports the runtime/SSE adapter stack, which requires
# logging to be initialized before import. Keep the lightweight event package
# usable on its own (for example from the pi-core SSE adapter) and load the
# runtime classes only when callers explicitly request them.
_LAZY_STREAMING_EXPORTS = {"AgentStream", "StreamProcessor", "EventSender"}


def __getattr__(name: str):
    if name in _LAZY_STREAMING_EXPORTS:
        from backend.agent.web.streaming.agent_stream import (
            AgentStream,
            EventSender,
            StreamProcessor,
        )

        exports = {
            "AgentStream": AgentStream,
            "StreamProcessor": StreamProcessor,
            "EventSender": EventSender,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # Events
    "EventType",
    "StreamEvent",
    "ThoughtEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "ToolProgressEvent",
    "AnswerEvent",
    "AgentStartEvent",
    "AgentEndEvent",
    "AgentErrorEvent",
    "SystemEvent",
    # State
    "AgentState",
    "StateInfo",
    "StateTransitionError",
    "AgentStateMachine",
    # Streaming
    "AgentStream",
    "StreamProcessor",
    "EventSender",
]
