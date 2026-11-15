"""Pure context transforms and bounded history compaction for the agent loop."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Iterable

from .types import AgentMessage, LLMMessage


_SUPERSEDED_TEXT = "[Superseded by a newer read/edit]"
_COMPACTED_TEXT = "[Compacted historical context]"


@dataclass(frozen=True)
class CompactionPolicy:
    """Controls bounded context compaction without deleting message structure."""

    max_chars: int = 24_000
    keep_recent_messages: int = 8

    @classmethod
    def from_env(cls) -> "CompactionPolicy":
        raw_limit = os.getenv("RESUME_AGENT_CONTEXT_MAX_CHARS", "")
        raw_recent = os.getenv("RESUME_AGENT_CONTEXT_KEEP_RECENT", "")
        try:
            max_chars = max(2_000, int(raw_limit)) if raw_limit else cls.max_chars
        except ValueError:
            max_chars = cls.max_chars
        try:
            keep_recent = max(1, int(raw_recent)) if raw_recent else cls.keep_recent_messages
        except ValueError:
            keep_recent = cls.keep_recent_messages
        return cls(max_chars=max_chars, keep_recent_messages=keep_recent)


def transform_context(
    messages: Iterable[AgentMessage],
    policy: CompactionPolicy | None = None,
) -> list[AgentMessage]:
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
    return compact_context(transformed, policy or CompactionPolicy.from_env())


def compact_context(
    messages: Iterable[AgentMessage],
    policy: CompactionPolicy,
) -> list[AgentMessage]:
    """Compact oldest message content while preserving tool-call pairing.

    Messages are never removed.  Their roles, tool call IDs and assistant
    tool-call structures stay intact so providers cannot receive an orphaned
    tool result.  Only old content is replaced once the configured character
    budget is exceeded.
    """

    result = list(messages)
    if policy.max_chars <= 0:
        return result
    total_chars = sum(_message_size(message) for message in result)
    if total_chars <= policy.max_chars:
        return result

    protected_start = max(0, len(result) - policy.keep_recent_messages)
    compacted = 0
    for index, message in enumerate(result[:protected_start]):
        if total_chars <= policy.max_chars:
            break
        if message.role == "system" or not message.content.strip():
            continue
        replacement = _replacement_for(message)
        total_chars -= max(0, len(message.content) - len(replacement))
        result[index] = replace(
            message,
            content=replacement,
            metadata={**message.metadata, "compacted": True},
        )
        compacted += 1

    if compacted and total_chars > policy.max_chars:
        # Keep the newest user message readable even for unusually large
        # prompts; compact only its content as a last resort.
        for index, message in enumerate(result[:protected_start]):
            if total_chars <= policy.max_chars:
                break
            if message.role != "user" or not message.content.strip():
                continue
            replacement = _COMPACTED_TEXT
            total_chars -= max(0, len(message.content) - len(replacement))
            result[index] = replace(
                message,
                content=replacement,
                metadata={**message.metadata, "compacted": True},
            )
    return result


def _replacement_for(message: AgentMessage) -> str:
    if message.role == "tool":
        return _COMPACTED_TEXT
    if message.role == "assistant" and message.tool_calls:
        return "[Compacted assistant narration]"
    return _COMPACTED_TEXT


def _message_size(message: AgentMessage) -> int:
    calls_size = sum(len(call.name) + len(str(call.arguments)) for call in message.tool_calls)
    return len(message.content) + calls_size + 16


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
