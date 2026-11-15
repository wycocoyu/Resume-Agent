"""Thin production stream adapter for the linear pi-core loop.

It reuses the resume domain's prompt/tool policy while keeping per-turn
execution scheduling and event ordering inside the pi-core loop.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any, Optional

from backend.agent.schema import (
    AgentState as SchemaAgentState,
    Message,
    Role,
)
from backend.agent.web.streaming.events import (
    AgentEndEvent,
    AgentErrorEvent,
    AgentStartEvent,
    AnswerEvent,
    AnswerResetEvent,
    ResumeGeneratedEvent,
    ResumePatchEvent,
    SuggestionsEvent,
    StreamEvent,
    SystemEvent,
    ThoughtEvent,
)
from backend.agent.web.streaming.agent_state import AgentState
from backend.agent.web.streaming.state_machine import AgentStateMachine

from .loop import run_agent_loop
from .metrics import metrics_registry
from .resume_adapter import (
    build_resume_hooks,
    execute_resume_tool,
    append_core_messages_to_memory,
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
        self._suggestions_emitted = False
        self._pending_text_deltas: list[str] = []

    @staticmethod
    def _extract_suggestions(content: str) -> tuple[str, list[dict[str, Any]]]:
        """Extract optional suggestion-button markers from assistant text."""

        marker = "%%SUGGESTIONS%%"
        if marker not in content:
            return content, []
        prefix, payload = content.split(marker, 1)
        payload = payload.split("%%END%%", 1)[0].strip()
        try:
            items = json.loads(payload)
        except json.JSONDecodeError:
            try:
                items = json.loads(payload + "]")
            except json.JSONDecodeError:
                return prefix.strip(), []
        if not isinstance(items, list):
            return prefix.strip(), []
        return prefix.strip(), [item for item in items if isinstance(item, dict)]

    def _make_suggestions_event(
        self,
        items: list[dict[str, Any]],
    ) -> SuggestionsEvent | None:
        if not items or self._suggestions_emitted:
            return None
        self._suggestions_emitted = True
        return SuggestionsEvent(items=items, session_id=self._session_id)

    @staticmethod
    def _diagnosis_completion_text(structured: dict[str, Any] | None) -> str:
        source = ((structured or {}).get("details") or {}).get(
            "diagnosis_source"
        )
        if source == "heuristic_fallback":
            return "深度诊断暂时没跑完，先给你一份基础检查结果；稍后可重试获取完整建议。"
        return "诊断已经整理好，本轮没有改动简历。想看逐条修改建议，点评分卡上的「查看修改建议」。"

    async def execute(self, user_message: str) -> AsyncIterator[StreamEvent]:
        start_len = len(self.agent.memory.messages)
        metrics = metrics_registry.start_run(self._session_id)
        try:
            await self._state_machine.transition_to(
                AgentState.STARTING,
                message="Starting agent execution",
                data={"user_message": user_message},
            )
            yield AgentStartEvent(
                agent_name=str(getattr(self.agent, "agent_name", "ResumeAgent")),
                task=user_message,
                session_id=self._session_id,
            )

            await self._state_machine.transition_to(AgentState.RUNNING)
            set_state = getattr(self.agent, "set_lifecycle_state", None)
            if callable(set_state):
                set_state(SchemaAgentState.IDLE)
            elif hasattr(self.agent, "state"):
                self.agent.state = SchemaAgentState.IDLE
            if hasattr(self.agent.memory, "cleanup_incomplete_sequences"):
                self.agent.memory.cleanup_incomplete_sequences()
            self.agent.memory.add_message(Message.user_message(user_message))
            if getattr(self.agent, "_langchain_memory", None):
                self.agent._langchain_memory.add_user_message(user_message)
            await self.agent.prepare_turn(user_message)

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
                    metrics.record_event(internal.kind)
                    self._step_id += 1
                    tool_calls = internal.data.get("tool_calls") or ()
                    if not tool_calls:
                        for delta in self._pending_text_deltas:
                            yield AnswerEvent(
                                content=delta,
                                delta=delta,
                                is_complete=False,
                                session_id=self._session_id,
                            )
                    self._pending_text_deltas.clear()
                    for completion in self._emit_message_completion(internal):
                        yield completion
                    continue
                if internal.kind == "message_update":
                    if internal.data.get("delta_type") == "text_delta":
                        text = str(internal.data.get("text") or "")
                        if text:
                            self._pending_text_deltas.append(text)
                        continue
                if internal.kind.startswith("_"):
                    continue

                metrics.record_event(internal.kind)
                if internal.kind == "tool_execution_end":
                    metrics.record_tool_end(internal.data)

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
            set_state = getattr(self.agent, "set_lifecycle_state", None)
            if callable(set_state):
                set_state(SchemaAgentState.IDLE)
            elif hasattr(self.agent, "state"):
                self.agent.state = SchemaAgentState.IDLE
            await self._state_machine.transition_to(AgentState.COMPLETED)
            metrics.completed_runs += 1
            yield AgentEndEvent(
                agent_name=str(getattr(self.agent, "agent_name", "ResumeAgent")),
                success=True,
                session_id=self._session_id,
            )
        except asyncio.CancelledError:
            metrics.stopped_runs += 1
            raise
        except Exception as exc:
            metrics.failed_runs += 1
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
        elif structured.get("type") == "resume_diagnosis":
            yield AnswerEvent(
                content=self._diagnosis_completion_text(structured),
                **self._completion_kwargs(),
                session_id=self._session_id,
            )

    def _emit_message_completion(self, event: AgentEvent):
        """Close the visible assistant turn before any tool card starts."""

        data = event.data
        content = str(data.get("content") or "")
        cleaned, suggestions = self._extract_suggestions(content)
        content = cleaned
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
                **self._completion_kwargs(),
                session_id=self._session_id,
            )
        suggestion_event = self._make_suggestions_event(suggestions)
        if suggestion_event is not None:
            yield suggestion_event

    @staticmethod
    def _completion_kwargs() -> dict[str, bool]:
        """Keep all visible answer completions on one protocol path."""

        return dict(is_complete=True)

    def _sync_memory(
        self,
        messages: list[AgentMessage],
        base_len: int,
    ) -> None:
        """Append only pi-core messages created after the legacy snapshot."""

        append_core_messages_to_memory(self.agent.memory, messages, base_len)

    def _persist_new_messages(self, start_len: int) -> None:
        if not self._chat_history_manager:
            return
        for message in self.agent.memory.messages[start_len:]:
            if message.role == Role.USER:
                continue
            self._chat_history_manager.add_message(message, persist=False)
        self._chat_history_manager._persist_if_needed()
