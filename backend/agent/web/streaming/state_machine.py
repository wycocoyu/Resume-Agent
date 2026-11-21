"""State machine for agent execution.

Manages agent lifecycle and state transitions.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional, Set
from datetime import datetime

from backend.agent.web.streaming.agent_state import (
    AgentState,
    StateInfo,
    StateTransitionError,
)

logger = logging.getLogger(__name__)


StateCallback = Callable[[StateInfo, StateInfo], Awaitable[None]]
ErrorCallback = Callable[[Exception, StateInfo], Awaitable[None]]


class AgentStateMachine:
    """State machine for managing agent execution lifecycle.

    Features:
    - Track current state
    - Validate state transitions
    - Support state change callbacks
    - Handle errors during execution
    - Support stop signal
    """

    def __init__(self, session_id: str) -> None:
        """Initialize the state machine.

        Args:
            session_id: Unique identifier for the session
        """
        self._session_id = session_id
        self._current_state = AgentState.IDLE
        self._state_info = StateInfo(AgentState.IDLE)
        self._previous_state: Optional[AgentState] = None
        self._state_history: list[StateInfo] = []
        self._callbacks: Set[StateCallback] = set()
        self._error_callbacks: Set[ErrorCallback] = set()
        self._lock = asyncio.Lock()
        self._stop_requested = False
        self._extra_secrets: tuple[str, ...] = ()

    def set_extra_secrets(self, secrets: tuple[str, ...]) -> None:
        self._extra_secrets = tuple(s for s in secrets if s)

    @property
    def current_state(self) -> AgentState:
        """Get the current state."""
        return self._current_state

    @property
    def state_info(self) -> StateInfo:
        """Get the current state info."""
        return self._state_info

    @property
    def is_running(self) -> bool:
        """Check if agent is currently running."""
        return self._current_state.is_active()

    @property
    def is_terminal(self) -> bool:
        """Check if in a terminal state."""
        return self._current_state.is_terminal()

    @property
    def stop_requested(self) -> bool:
        """Check if stop was requested."""
        return self._stop_requested

    def add_state_callback(self, callback: StateCallback) -> None:
        """Add a callback for state changes.

        Args:
            callback: Async callback function
        """
        self._callbacks.add(callback)

    def remove_state_callback(self, callback: StateCallback) -> None:
        """Remove a state change callback.

        Args:
            callback: The callback to remove
        """
        self._callbacks.discard(callback)

    def add_error_callback(self, callback: ErrorCallback) -> None:
        """Add a callback for errors.

        Args:
            callback: Async error callback function
        """
        self._error_callbacks.add(callback)

    async def transition_to(
        self,
        target_state: AgentState,
        message: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> StateInfo:
        """Transition to a new state.

        Args:
            target_state: The target state
            message: Optional message describing the transition
            data: Optional additional data

        Returns:
            The new state info

        Raises:
            StateTransitionError: If transition is invalid
        """
        async with self._lock:
            if not self._current_state.can_transition_to(target_state):
                raise StateTransitionError(
                    self._current_state,
                    target_state,
                    f"Cannot transition from {self._current_state.value} to {target_state.value}",
                )

            # Store previous state
            old_state_info = self._state_info
            self._previous_state = self._current_state

            # Create new state info
            new_state_info = StateInfo(target_state, message, data)
            new_state_info.timestamp = datetime.now().timestamp()

            # Update state
            self._current_state = target_state
            self._state_info = new_state_info
            self._state_history.append(new_state_info)

            logger.info(
                f"[{self._session_id}] State transition: "
                f"{old_state_info.state.value} -> {target_state.value}"
                + (f" ({message})" if message else "")
            )

            # Notify callbacks
            await self._notify_state_change(old_state_info, new_state_info)

            return new_state_info

    async def reset(self) -> None:
        """Reset the state machine to IDLE."""
        async with self._lock:
            self._current_state = AgentState.IDLE
            self._state_info = StateInfo(AgentState.IDLE, "Reset")
            self._previous_state = None
            self._stop_requested = False
            logger.info(f"[{self._session_id}] State machine reset")

    def request_stop(self, reason: str = "manual") -> None:
        """Request the agent to stop.

        Args:
            reason: The reason for stopping (e.g., "manual", "session_switch")
        """
        self._stop_requested = True
        self._state_info.data["reason"] = reason
        logger.info(f"[{self._session_id}] Stop requested, reason: {reason}")

    def clear_stop_request(self) -> None:
        """Clear the stop request."""
        self._stop_requested = False

    async def _notify_state_change(
        self,
        old_info: StateInfo,
        new_info: StateInfo,
    ) -> None:
        """Notify all registered callbacks of state change.

        Args:
            old_info: Previous state info
            new_info: New state info
        """
        for callback in self._callbacks:
            try:
                await callback(old_info, new_info)
            except Exception as e:
                logger.error(
                    f"[{self._session_id}] Error in state callback: {e}",
                    exc_info=True,
                )

    async def handle_error(
        self,
        error: Exception,
    ) -> None:
        """Handle an error during execution.

        Args:
            error: The exception that occurred
        """
        from backend.services.ai_guard import redact_secrets

        safe_message = redact_secrets(str(error), self._extra_secrets)
        if self._extra_secrets:
            logger.error(
                f"[{self._session_id}] Error in state {self._current_state.value}: {safe_message}"
            )
        else:
            logger.error(
                f"[{self._session_id}] Error in state {self._current_state.value}: {safe_message}",
                exc_info=True,
            )

        # Notify error callbacks
        for callback in self._error_callbacks:
            try:
                await callback(error, self._state_info)
            except Exception as e:
                logger.error(
                    f"[{self._session_id}] Error in error callback: {redact_secrets(str(e), self._extra_secrets)}"
                )

        # Transition to error state
        if not self._current_state.is_terminal():
            await self.transition_to(
                AgentState.ERROR,
                message=safe_message,
                data={"error_type": type(error).__name__},
            )

    def get_state_history(self, limit: int = 50) -> list[StateInfo]:
        """Get state transition history.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of state info entries
        """
        return self._state_history[-limit:]

    def to_dict(self) -> dict[str, Any]:
        """Convert state machine to dictionary."""
        return {
            "session_id": self._session_id,
            "current_state": self._current_state.value,
            "previous_state": self._previous_state.value if self._previous_state else None,
            "message": self._state_info.message,
            "data": self._state_info.data,
            "is_running": self.is_running,
            "stop_requested": self._stop_requested,
        }
