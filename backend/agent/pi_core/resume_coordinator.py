"""Resume turn coordination independent from the pi-core scheduler.

The coordinator owns turn preparation and public policy snapshots. During the
migration it uses a domain provider for domain-specific routing, but
the runtime and event loop no longer reach into Manus private state directly.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .turn_policy import TurnPolicySnapshot, blocked_tool_reason


class ResumeTurnCoordinator:
    """Own per-turn preparation, prompt access and tool policy decisions."""

    def __init__(
        self,
        domain_provider: Callable[[], Any],
        *,
        policy: Optional[TurnPolicySnapshot] = None,
    ) -> None:
        self._domain_provider = domain_provider
        self._policy = policy or TurnPolicySnapshot()
        self._system_prompt = ""
        self._next_step_prompt = ""

    @property
    def policy(self) -> TurnPolicySnapshot:
        return self._policy

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @property
    def next_step_prompt(self) -> str:
        return self._next_step_prompt

    async def prepare(self, user_input: str) -> None:
        domain = self._domain_provider()
        prepare = getattr(domain, "prepare_pi_core_turn", None)
        if prepare is not None:
            await prepare(user_input)
        get_policy = getattr(domain, "get_turn_policy", None)
        if callable(get_policy):
            candidate = get_policy()
            if isinstance(candidate, TurnPolicySnapshot):
                self._policy = candidate
        self._system_prompt = str(getattr(domain, "system_prompt", "") or "")
        self._next_step_prompt = str(
            getattr(domain, "next_step_prompt", "") or ""
        )

    def block_reason(self, tool_name: str) -> str | None:
        domain = self._domain_provider()
        public_policy = getattr(domain, "get_tool_block_reason", None)
        if callable(public_policy):
            return public_policy(tool_name)
        return blocked_tool_reason(self._policy, tool_name)

    def is_finished(self) -> bool:
        domain = self._domain_provider()
        state = getattr(domain, "state", None)
        value = getattr(state, "value", state)
        return str(value or "") == "FINISHED"

    def mark_state(self, state: Any) -> None:
        domain = self._domain_provider()
        if hasattr(domain, "state"):
            setattr(domain, "state", state)
