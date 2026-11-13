"""Experimental thin stream adapter for the linear pi-core loop.

The adapter is intentionally opt-in.  It reuses Manus' prompt/tool policy,
while replacing only the per-turn execution scheduler and event ordering.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, Optional

from backend.agent.schema import (
    AgentState as SchemaAgentState,
    Message,
    Role,
    ToolCall as LegacyToolCall,
)
from backend.agent.web.streaming.events import (
    AgentEndEvent,
    AgentErrorEvent,
    AgentStartEvent,
    AnswerEvent,
    AnswerResetEvent,
    ResumeGeneratedEvent,
    ResumePatchEvent,
    StreamEvent,
    SystemEvent,
    ThoughtEvent,
)
from backend.agent.web.streaming.agent_state import AgentState
from backend.agent.web.streaming.state_machine import AgentStateMachine

from .loop import run_agent_loop
from .resume_adapter import (
    build_resume_hooks,
    execute_resume_tool,
    stream_resume_model,
    to_core_messages,
)
from .sse_adapter import to_legacy_stream_event
from .types import AgentEvent, AgentMessage


class PiCoreAgentStream:
    """Run one request through pi-core and emit the legacy SSE event model."""

    def __init__(
        self,
        agent: Any,
        session_id: str,
        state_machine: AgentStateMachine,
        chat_history_manager: Optional[Any] = None,
    ) -> None:
        self.agent = agent
        self._session_id = session_id
        self._state_machine = state_machine
        self._chat_history_manager = chat_history_manager
        self._step_id = 0

    async def execute(self, user_message: str) -> AsyncIterator[StreamEvent]:
        start_len = len(self.agent.memory.messages)
        try:
            await self._state_machine.transition_to(
                AgentState.STARTING,
                message="Starting agent execution",
                data={"user_message": user_message},
            )
            yield AgentStartEvent(
                agent_name="Manus",
                task=user_message,
                session_id=self._session_id,
            )

            await self._state_machine.transition_to(AgentState.RUNNING)
            if hasattr(self.agent, "state"):
                self.agent.state = SchemaAgentState.IDLE
            if hasattr(self.agent.memory, "cleanup_incomplete_sequences"):
                self.agent.memory.cleanup_incomplete_sequences()
            self.agent.memory.add_message(Message.user_message(user_message))
            if getattr(self.agent, "_langchain_memory", None):
                self.agent._langchain_memory.add_user_message(user_message)
            if hasattr(self.agent, "prepare_pi_core_turn"):
                await self.agent.prepare_pi_core_turn(user_message)

            messages = to_core_messages(self.agent.memory.messages)
            core_base_len = len(self.agent.memory.messages)
            hooks = build_resume_hooks(self.agent)

            async for internal in run_agent_loop(
                messages,
                lambda llm_messages: stream_resume_model(self.agent, llm_messages),
                lambda call, current: execute_resume_tool(
                    self.agent, call, current
                ),
                hooks=hooks,
                max_turns=10,
            ):
                if self._state_machine.stop_requested:
                    reason = self._state_machine.state_info.data.get("reason", "manual")
                    message = (
                        "Execution stopped due to session switch"
                        if reason == "session_switch"
                        else "Execution stopped by user"
                    )
                    await self._state_machine.transition_to(
                        AgentState.STOPPED,
                        message=message,
                    )
                    yield SystemEvent(
                        message=message,
                        level="info",
                        session_id=self._session_id,
                    )
                    return
                if internal.kind == "message_end":
                    self._step_id += 1
                    for completion in self._emit_message_completion(internal):
                        yield completion
                    continue
                if internal.kind.startswith("_"):
                    continue

                legacy = to_legacy_stream_event(
                    internal,
                    session_id=self._session_id,
                    step_id=max(self._step_id, 1),
                )
                if legacy is not None:
                    if (
                        internal.kind == "tool_execution_start"
                        and self._state_machine.current_state
                        != AgentState.TOOL_EXECUTING
                    ):
                        await self._state_machine.transition_to(
                            AgentState.TOOL_EXECUTING
                        )
                    elif (
                        internal.kind == "tool_execution_end"
                        and self._state_machine.current_state
                        != AgentState.THINKING
                    ):
                        await self._state_machine.transition_to(AgentState.THINKING)
                    yield legacy

                for extra in self._structured_events(internal):
                    yield extra

            self._sync_memory(messages, core_base_len)
            self._persist_new_messages(start_len)
            if hasattr(self.agent, "state"):
                self.agent.state = SchemaAgentState.IDLE
            await self._state_machine.transition_to(AgentState.COMPLETED)
            yield AgentEndEvent(
                agent_name="Manus",
                success=True,
                session_id=self._session_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._state_machine.handle_error(exc)
            yield AgentErrorEvent(
                error_message="刚才这一步运行出了点问题，请稍后重试。",
                error_type=type(exc).__name__,
                session_id=self._session_id,
            )

    def _structured_events(self, event: AgentEvent):
        if event.kind != "tool_execution_end":
            return
        data = event.data
        structured = data.get("structured_content")
        if not isinstance(structured, dict):
            return
        if structured.get("type") == "resume_patch":
            yield ResumePatchEvent(
                patch_id=structured.get("patch_id", ""),
                paths=structured.get("paths", []),
                before=structured.get("before", {}),
                after=structured.get("after", {}),
                summary=structured.get("summary", ""),
                operation=structured.get("operation", "set"),
                session_id=self._session_id,
            )
        elif structured.get("type") == "resume_generated":
            yield ResumeGeneratedEvent(
                resume=structured.get("resume", {}),
                summary=structured.get("summary", ""),
                session_id=self._session_id,
            )

    def _emit_message_completion(self, event: AgentEvent):
        """Close the visible assistant turn before any tool card starts."""

        data = event.data
        content = str(data.get("content") or "")
        tool_calls = data.get("tool_calls") or ()
        if tool_calls and content.strip():
            # A tool-bearing assistant message is action narration, not the
            # final answer.  The legacy frontend already understands this
            # reset + thought pair.
            yield AnswerResetEvent(session_id=self._session_id)
            yield ThoughtEvent(
                thought=content,
                step_id=max(self._step_id, 1),
                session_id=self._session_id,
            )
            return
        if content.strip():
            yield AnswerEvent(
                content=content,
                delta=None,
                is_complete=True,
                session_id=self._session_id,
            )

    def _sync_memory(
        self,
        messages: list[AgentMessage],
        base_len: int,
    ) -> None:
        """Append only pi-core messages created after the legacy snapshot."""

        for message in messages[base_len:]:
            if message.role == "assistant":
                calls = [
                    LegacyToolCall(
                        id=call.id,
                        type="function",
                        function={
                            "name": call.name,
                            "arguments": json.dumps(
                                call.arguments, ensure_ascii=False
                            ),
                        },
                    )
                    for call in message.tool_calls
                ]
                self.agent.memory.add_message(
                    Message(
                        role=Role.ASSISTANT,
                        content=message.content or None,
                        tool_calls=calls or None,
                    )
                )
            elif message.role == "tool":
                self.agent.memory.add_message(
                    Message.tool_message(
                        content=message.content,
                        name=message.name or "unknown",
                        tool_call_id=message.tool_call_id or "",
                    )
                )

    def _persist_new_messages(self, start_len: int) -> None:
        if not self._chat_history_manager:
            return
        for message in self.agent.memory.messages[start_len:]:
            if message.role == Role.USER:
                continue
            self._chat_history_manager.add_message(message, persist=False)
        self._chat_history_manager._persist_if_needed()
