"""Production-facing resume agent runtime.

The web/SSE layer depends on this small composition facade instead of importing
the historical legacy inheritance tree directly.  The domain implementation
is kept behind a single domain boundary while the pi-core loop owns
turn scheduling and event ordering.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterator
from typing import Any, Optional

from backend.agent.agent.shared_state import AgentSharedState
from backend.agent.pi_core.resume_tools import (
    build_resume_tool_collection,
    execute_resume_tool_native,
    inject_resume_tool_context,
)
from backend.agent.pi_core.resume_coordinator import ResumeTurnCoordinator
from backend.agent.pi_core.resume_result_adapter import ResumeResultAdapter
from backend.agent.pi_core.turn_policy import (
    TurnPolicySnapshot,
)
from backend.agent.schema import Memory
from backend.agent.pi_core.types import RuntimeToolResult
from backend.agent.pi_core.types import AssistantChunk, ModelTurn, ToolCall


class ResumeAgentRuntime:
    """Session-scoped runtime used by the production SSE path.

    The domain object is intentionally created lazily so importing the
    web route does not eagerly import the domain runtime or optional tools.
    ``__getattr__`` preserves the existing pi-core/stream contracts while
    keeping the domain implementation outside the event-loop layer.
    """

    def __init__(
        self,
        *,
        session_id: Optional[str] = None,
        is_admin: bool = False,
        user_id: Optional[str] = None,
        capability: Optional[str] = None,
        llm: Any = None,
        owner_key: Optional[str] = None,
    ) -> None:
        object.__setattr__(self, "_domain", None)
        object.__setattr__(self, "_native_tools", None)
        object.__setattr__(self, "_native_shared_state", None)
        object.__setattr__(self, "_native_memory", None)
        object.__setattr__(self, "_native_llm", llm)
        object.__setattr__(self, "_native_owner_key", owner_key)
        object.__setattr__(self, "_result_adapter", None)
        object.__setattr__(self, "_turn_policy", TurnPolicySnapshot())
        object.__setattr__(
            self,
            "_coordinator",
            ResumeTurnCoordinator(
                lambda: self._get_domain(),
                policy=TurnPolicySnapshot(),
            ),
        )
        object.__setattr__(
            self,
            "_runtime_kwargs",
            {
                "session_id": session_id,
                "is_admin": is_admin,
                "user_id": user_id,
                "capability": capability,
            },
        )

    def _get_domain(self) -> Any:
        domain = self.__dict__.get("_domain")
        if domain is None:
            from backend.agent.llm import LLM
            from backend.agent.pi_core.resume_domain import ResumeDomainRuntime

            native_llm = self.llm
            extra_kwargs = {"llm": native_llm} if isinstance(native_llm, LLM) else {}
            domain = self._construct_domain(
                ResumeDomainRuntime, extra_kwargs=extra_kwargs
            )
            native_memory = self.__dict__.get("_native_memory")
            if native_memory is not None and getattr(native_memory, "messages", None):
                domain.memory = native_memory
            if native_llm is not None:
                domain.llm = native_llm
                if hasattr(domain, "_inject_tool_context") and hasattr(
                    domain, "available_tools"
                ):
                    domain._inject_tool_context(domain.available_tools.tools)
            object.__setattr__(self, "_domain", domain)
            if hasattr(domain, "memory"):
                object.__setattr__(
                    self,
                    "_native_memory",
                    domain.memory,
                )
            if hasattr(domain, "llm"):
                object.__setattr__(self, "_native_llm", domain.llm)
            if hasattr(domain, "available_tools"):
                object.__setattr__(
                    self,
                    "_native_tools",
                    domain.available_tools,
                )
            object.__setattr__(
                self,
                "_result_adapter",
                ResumeResultAdapter(
                    capture=getattr(
                        domain,
                        "capture_structured_tool_result",
                        getattr(domain, "_store_structured_tool_result", None),
                    ),
                    consume=getattr(
                        domain,
                        "consume_structured_tool_result",
                        getattr(domain, "get_structured_tool_result", None),
                    ),
                ),
            )
            self._sync_pending_attributes(domain)
        return domain

    def _construct_domain(
        self,
        domain_type: Any,
        *,
        extra_kwargs: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Instantiate the domain runtime with only supported kwargs.

        Test doubles and transitional adapters do not always expose the full
        ``Manus`` constructor.  Filtering by the declared signature keeps the
        runtime boundary tolerant without swallowing constructor failures from
        the real implementation.
        """

        kwargs = {**self.__dict__["_runtime_kwargs"], **(extra_kwargs or {})}
        try:
            signature = inspect.signature(domain_type)
        except (TypeError, ValueError):
            return domain_type(**kwargs)

        parameters = signature.parameters.values()
        if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters):
            return domain_type(**kwargs)

        supported = {
            name: value
            for name, value in kwargs.items()
            if name in signature.parameters
        }
        return domain_type(**supported)

    def _get_native_shared_state(self) -> AgentSharedState:
        state = self.__dict__.get("_native_shared_state")
        if state is None:
            session_id = self.__dict__["_runtime_kwargs"].get("session_id") or "default"
            state = AgentSharedState(session_id=session_id)
            from backend.agent.tool.resume_data_store import ResumeDataStore

            ResumeDataStore.set_shared_state(session_id, state)
            object.__setattr__(self, "_native_shared_state", state)
        return state

    @property
    def available_tools(self) -> Any:
        """Return resume tools without forcing legacy Manus construction."""

        tools = self.__dict__.get("_native_tools")
        if tools is None:
            kwargs = self.__dict__["_runtime_kwargs"]
            tools = build_resume_tool_collection(kwargs.get("capability"))
            inject_resume_tool_context(
                tools.tools,
                session_id=kwargs.get("session_id"),
                user_id=kwargs.get("user_id"),
                shared_state=self._get_native_shared_state(),
                llm=self.llm,
            )
            object.__setattr__(self, "_native_tools", tools)
        return tools

    @property
    def memory(self) -> Memory:
        """Keep conversation memory available without eager legacy creation."""

        memory = self.__dict__.get("_native_memory")
        if memory is None:
            memory = Memory()
            object.__setattr__(self, "_native_memory", memory)
        return memory

    @property
    def llm(self) -> Any:
        """Provide the model client without eagerly constructing Manus."""

        llm = self.__dict__.get("_native_llm")
        if llm is None:
            from backend.agent.llm import LLM

            llm = LLM.create_isolated(config_name="manus")
            object.__setattr__(self, "_native_llm", llm)
        return llm

    def _sync_pending_attributes(self, domain: Any) -> None:
        for name, value in tuple(self.__dict__.items()):
            if name in {
                "_domain",
                "_runtime_kwargs",
                "_native_tools",
                "_native_shared_state",
                "_native_memory",
                "_native_llm",
                "_native_owner_key",
            }:
                continue
            if hasattr(domain, name):
                setattr(domain, name, value)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "llm":
            object.__setattr__(self, "_native_llm", value)
            domain = self.__dict__.get("_domain")
            if domain is not None:
                domain.llm = value
                if hasattr(domain, "_inject_tool_context") and hasattr(
                    domain, "available_tools"
                ):
                    domain._inject_tool_context(domain.available_tools.tools)
            tools = self.__dict__.get("_native_tools")
            if tools is not None:
                kwargs = self.__dict__["_runtime_kwargs"]
                inject_resume_tool_context(
                    tools.tools,
                    session_id=kwargs.get("session_id"),
                    user_id=kwargs.get("user_id"),
                    shared_state=self.__dict__.get("_native_shared_state"),
                    llm=value,
                )
            return
        if name == "owner_key":
            object.__setattr__(self, "_native_owner_key", value)
            return
        if name in {"_domain", "_runtime_kwargs"} or "_domain" not in self.__dict__:
            object.__setattr__(self, name, value)
            return
        domain = self.__dict__.get("_domain")
        if domain is None:
            object.__setattr__(self, name, value)
            return
        if hasattr(domain, name):
            setattr(domain, name, value)
            return
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        """Keep monkeypatch/test cleanup aligned with the domain runtime."""

        if name in {"_domain", "_runtime_kwargs"}:
            object.__delattr__(self, name)
            return
        domain = self.__dict__.get("_domain")
        if domain is not None and hasattr(domain, name):
            try:
                object.__delattr__(domain, name)
            except AttributeError:
                delattr(domain, name)
            return
        object.__delattr__(self, name)

    @property
    def domain_agent(self) -> Any:
        """Return the domain implementation for controlled migration."""

        return self._get_domain()

    @property
    def agent_name(self) -> str:
        """Expose the public event name without leaking domain internals."""

        domain = self._get_domain()
        return str(getattr(domain, "name", "ResumeAgent") or "ResumeAgent")

    async def prepare_turn(self, user_input: str) -> None:
        """Prepare one turn through the runtime-owned coordinator."""

        await self._coordinator.prepare(user_input)
        object.__setattr__(self, "_turn_policy", self._coordinator.policy)

    async def prepare_model_request(self, messages: list[Any]) -> list[Any]:
        """Apply provider safety defaults before a model request."""

        llm = self.llm
        model = str(getattr(llm, "model", "") or "")
        if model.startswith("deepseek"):
            extra_body = getattr(llm, "extra_body", None)
            llm.extra_body = {
                **(extra_body if isinstance(extra_body, dict) else {}),
                "thinking": {"type": "disabled"},
            }
        return messages

    def get_system_prompt(self) -> str:
        """Return the prepared system prompt through the runtime boundary."""

        return self._coordinator.system_prompt or str(
            getattr(self._get_domain(), "system_prompt", "") or ""
        )

    def get_tool_choice(self) -> Any:
        """Return the provider tool-choice policy for the current turn."""

        return getattr(self._get_domain(), "tool_choices", "auto")

    def is_turn_finished(self) -> bool:
        """Return whether the domain state marked the turn finished."""

        return self._coordinator.is_finished()

    def set_lifecycle_state(self, state: Any) -> None:
        """Update execution state without exposing domain internals."""

        domain = self.__dict__.get("_domain")
        if domain is not None and hasattr(domain, "state"):
            setattr(domain, "state", state)
            return
        object.__setattr__(self, "_lifecycle_state", state)

    def get_lifecycle_state(self) -> Any:
        """Return the current public lifecycle state, if one is available."""

        domain = self.__dict__.get("_domain")
        if domain is not None and hasattr(domain, "state"):
            return getattr(domain, "state")
        return self.__dict__.get("_lifecycle_state")

    async def stream_model_response(
        self,
        messages: list[dict[str, Any]],
        *,
        system_prompt: str | None = None,
        cancel_event: Any = None,
    ) -> AsyncIterator[Any]:
        """Expose the provider stream through the runtime boundary."""

        prompt = (
            system_prompt
            if system_prompt is not None
            else self.get_system_prompt()
        )
        system_msgs = [{"role": "system", "content": prompt}] if prompt else None
        llm = self.llm
        params = {
            "messages": messages,
            "system_msgs": system_msgs,
            "tools": self.available_tools.to_params(),
            "tool_choice": self.get_tool_choice(),
            "cancel_event": cancel_event,
        }
        legacy_override = llm.__dict__.get("ask_tool_stream") if hasattr(llm, "__dict__") else None
        native_stream = getattr(llm, "stream_tool_response", None)
        # Test doubles and older integrations may only provide the original
        # callback-based helper.  Keep that boundary compatible without
        # reintroducing queues into the SSE path.
        if callable(native_stream) and not callable(legacy_override):
            async for chunk in native_stream(**params):
                yield chunk
            return

        legacy_stream = getattr(llm, "ask_tool_stream", None)
        if not callable(legacy_stream):
            raise RuntimeError("LLM must provide stream_tool_response() or ask_tool_stream()")

        deltas: list[str] = []

        async def on_content_delta(piece: str) -> None:
            if piece:
                deltas.append(str(piece))

        response = await legacy_stream(
            **params,
            on_content_delta=on_content_delta,
        )
        content = "".join(deltas)
        calls: list[ToolCall] = []
        raw_calls = getattr(response, "tool_calls", None) or []
        for raw_call in raw_calls:
            function = getattr(raw_call, "function", None)
            name = getattr(function, "name", "") if function is not None else ""
            raw_arguments = (
                getattr(function, "arguments", "{}") if function is not None else "{}"
            )
            if isinstance(raw_arguments, str):
                try:
                    arguments = json.loads(raw_arguments)
                except json.JSONDecodeError:
                    arguments = {"_raw": raw_arguments}
            else:
                arguments = raw_arguments if isinstance(raw_arguments, dict) else {}
            calls.append(
                ToolCall(
                    id=str(getattr(raw_call, "id", "")),
                    name=str(name),
                    arguments=arguments,
                )
            )
        yield AssistantChunk(kind="text_delta", content=content)
        yield AssistantChunk(
            kind="done",
            turn=ModelTurn(
                content=content,
                thinking="",
                tool_calls=tuple(calls),
                stop_reason=getattr(response, "finish_reason", None),
            ),
        )

    async def execute_tool(self, call: Any) -> RuntimeToolResult:
        """Execute one core tool call through an explicit runtime contract."""

        domain = self._get_domain()
        progress_events: list[dict[str, Any]] = []

        def capture_progress(update: Any) -> None:
            progress_events.append(
                {
                    "stage_id": getattr(update, "node_id", "") or "progress",
                    "summary": str(
                        getattr(update, "content", "")
                        or getattr(update, "summary", "")
                        or ""
                    ),
                    "current": getattr(update, "current", None),
                    "total": getattr(update, "total", None),
                    "label": getattr(update, "label", None),
                    "stages": list(getattr(update, "stages", ()) or ()),
                }
            )

        if getattr(domain, "native_pi_core_tools", False):
            output = await execute_resume_tool_native(
                self.available_tools,
                call,
                session_id=self.__dict__["_runtime_kwargs"].get("session_id"),
                user_id=self.__dict__["_runtime_kwargs"].get("user_id"),
                owner_key=self.__dict__.get("_native_owner_key"),
                store_structured=getattr(
                    self._result_adapter, "capture", None
                ),
                mark_pending_approval=getattr(
                    domain, "_mark_pi_core_pending_approval", None
                ),
                progress_sink=capture_progress,
            )
        else:
            execute_pi_core = getattr(domain, "execute_pi_core_tool", None)
            if not callable(execute_pi_core):
                raise RuntimeError(
                    "ResumeAgentRuntime requires domain.execute_pi_core_tool(); "
                    "legacy execute_tool() is not a Pi Core runtime boundary"
                )
            output = await execute_pi_core(call)
        structured: dict[str, Any] = {}
        adapter = self.__dict__.get("_result_adapter")
        if adapter is not None:
            candidate = adapter.consume(call.id)
            if isinstance(candidate, dict):
                structured = candidate
        if not structured:
            consume = getattr(domain, "get_structured_tool_result", None)
            if callable(consume):
                candidate = consume(call.id)
                if isinstance(candidate, dict):
                    structured = candidate
            else:
                structured_results = getattr(domain, "_tool_structured_results", {})
                if isinstance(structured_results, dict):
                    candidate = structured_results.pop(call.id, None)
                    if isinstance(candidate, dict):
                        structured = candidate
        return RuntimeToolResult(
            str(output or ""),
            structured,
            tuple(progress_events),
        )

    def tool_block_reason(self, tool_name: str) -> str | None:
        """Return the current turn's public tool-policy decision."""

        return self._coordinator.block_reason(tool_name)

    def get_turn_policy(self) -> TurnPolicySnapshot:
        """Return the immutable policy snapshot for lifecycle hooks."""

        return self.__dict__.get("_turn_policy", TurnPolicySnapshot())

    async def cleanup(self) -> Any:
        domain = self.__dict__.get("_domain")
        if domain is None:
            return None
        cleanup = getattr(domain, "cleanup", None)
        if cleanup is None:
            return None
        return await cleanup()

    def __getattr__(self, name: str) -> Any:
        # ``hasattr(runtime, "_chat_history")`` is used by the route to decide
        # whether to inject an existing history object.  Missing private
        # domain fields must not instantiate the legacy agent merely
        # because of that probe; pending values are synchronized later.
        if name.startswith("_") and self.__dict__.get("_domain") is None:
            raise AttributeError(name)
        return getattr(self._get_domain(), name)

