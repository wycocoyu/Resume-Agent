"""Thin SSE entrypoint for the linear Pi Core agent stream."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

from backend.agent.web.streaming.state_machine import AgentStateMachine
from backend.agent.web.streaming.events import StreamEvent
from backend.agent.pi_core.stream import PiCoreAgentStream
from backend.agent.web.streaming.helpers import (
    is_tool_error_content,
    merge_visible_piece,
    split_turn_messages,
    unwrap_retry_error,
    user_facing_error_message,
)

logger = logging.getLogger(__name__)
EventSender = Any


class AgentStream(PiCoreAgentStream):
    """Historical constructor facade over the linear Pi Core stream."""

    def __init__(
        self,
        agent: Any,
        session_id: str,
        state_machine: AgentStateMachine,
        event_sender: Any = None,
        chat_history_manager: Optional[Any] = None,
    ) -> None:
        super().__init__(
            agent,
            session_id,
            state_machine,
            chat_history_manager=chat_history_manager,
        )
        self._event_sender = event_sender

if TYPE_CHECKING:
    from backend.agent.pi_core.resume_agent import ResumeAgentRuntime


class StreamProcessor:
    """Manage only the linear Pi Core stream lifecycle."""

    def __init__(self) -> None:
        self._active_streams: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def start_stream(
        self,
        session_id: str,
        agent: "ResumeAgentRuntime",
        state_machine: AgentStateMachine,
        event_sender: Any,
        user_message: str,
        chat_history_manager: Optional[Any] = None,
    ) -> AsyncIterator[StreamEvent]:
        stream = PiCoreAgentStream(
            agent,
            session_id,
            state_machine,
            chat_history_manager,
        )
        logger.info(
            "[StreamProcessor] linear pi-core stream enabled for session %s",
            session_id,
        )
        async with self._lock:
            self._active_streams[session_id] = stream
        try:
            async for event in stream.execute(user_message):
                yield event
        finally:
            await self.remove_stream(session_id)

    async def remove_stream(self, session_id: str) -> None:
        async with self._lock:
            self._active_streams.pop(session_id, None)

    def has_active_stream(self, session_id: str) -> bool:
        return session_id in self._active_streams

    def get_stream(self, session_id: str) -> Optional[Any]:
        return self._active_streams.get(session_id)

    async def stop_stream(self, session_id: str, reason: str = "manual") -> bool:
        stream = self.get_stream(session_id)
        if stream is None:
            return False
        state_machine = getattr(stream, "_state_machine", None)
        if state_machine is None or not hasattr(state_machine, "request_stop"):
            return False
        state_machine.request_stop(reason=reason)
        return True
