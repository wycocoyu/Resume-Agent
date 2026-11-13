from __future__ import annotations

import asyncio
from types import SimpleNamespace

from backend.core.logger import setup_logging

setup_logging(False, "INFO", "logs/test")

from backend.agent.llm import LLM


class _Completions:
    async def create(self, **_kwargs):
        async def stream():
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason=None,
                        delta=SimpleNamespace(
                            content="我先检查。",
                            reasoning_content="保留事实。",
                            tool_calls=None,
                        ),
                    )
                ]
            )
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="length",
                        delta=SimpleNamespace(
                            content=None,
                            reasoning_content=None,
                            tool_calls=[
                                {
                                    "index": 0,
                                    "id": "call-1",
                                    "function": {
                                        "name": "cv_editor_agent",
                                        "arguments": "{\"path\":",
                                    },
                                }
                            ],
                        ),
                    )
                ]
            )

        return stream()


def _fake_llm() -> LLM:
    llm = LLM.__new__(LLM)
    llm.model = "deepseek-chat"
    llm.extra_body = None
    llm.max_tokens = 100
    llm.temperature = 0.2
    llm.max_input_tokens = None
    llm.client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    llm.total_input_tokens = 0
    llm.total_completion_tokens = 0
    llm.tokenizer = None
    llm.token_counter = None
    return llm


def test_stream_tool_response_emits_core_chunks_and_preserves_length_reason():
    async def collect():
        return [
            chunk
            async for chunk in _fake_llm().stream_tool_response(
                messages=[{"role": "user", "content": "优化项目"}],
                tools=[{"type": "function", "function": {"name": "cv_editor_agent"}}],
            )
        ]

    chunks = asyncio.run(collect())
    assert [chunk.kind for chunk in chunks] == [
        "text_delta",
        "thinking_delta",
        "done",
    ]
    turn = chunks[-1].turn
    assert turn is not None
    assert turn.stop_reason == "length"
    assert turn.tool_calls[0].arguments == {"_raw": "{\"path\":"}
