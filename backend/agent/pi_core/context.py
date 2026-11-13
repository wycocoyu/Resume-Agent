"""Pure context transforms for the agent loop."""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from .types import AgentMessage, LLMMessage


_SUPERSEDED_TEXT = "[Superseded by a newer read/edit]"


def transform_context(messages: Iterable[AgentMessage]) -> list[AgentMessage]:
    """Return a model-facing context with stale supersedable results compacted.

    The source history is never mutated.  Only tool messages carrying a
    ``supersede_key`` are eligible, and the newest result for each key wins.
    """

    source = list(messages)
    latest_keys: set[str] = set()
    transformed: list[AgentMessage] = []
    for message in reversed(source):
        key = message.supersede_key
        if message.role == "tool" and key:
            if key in latest_keys:
                transformed.append(
                    replace(
                        message,
                        content=_SUPERSEDED_TEXT,
                        structured_content=None,
                        metadata={**message.metadata, "superseded": True},
                    )
                )
                continue
            latest_keys.add(key)
        transformed.append(message)
    transformed.reverse()
    return transformed


def convert_to_llm(messages: Iterable[AgentMessage]) -> list[LLMMessage]:
    """Strip UI-only fields before sending messages to an LLM provider."""

    return [
        LLMMessage(
            role=message.role,
            content=message.content,
            tool_calls=message.tool_calls,
            tool_call_id=message.tool_call_id,
            name=message.name,
        )
        for message in messages
    ]
