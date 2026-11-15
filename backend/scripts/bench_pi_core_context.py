"""Offline compaction/pruning benchmark for Pi Core context growth.

Usage:
    python -m backend.scripts.bench_pi_core_context --rounds 8 --chars 4000
"""

from __future__ import annotations

import argparse
import json

from backend.agent.pi_core.context import CompactionPolicy, transform_context
from backend.agent.pi_core.types import AgentMessage, ToolCall


def build_messages(rounds: int, chars: int) -> list[AgentMessage]:
    messages: list[AgentMessage] = [
        AgentMessage(role="system", content="resume system prompt"),
        AgentMessage(role="user", content="请连续优化我的简历"),
    ]
    for index in range(rounds):
        messages.append(
            AgentMessage(
                role="assistant",
                content=f"第 {index + 1} 轮正在处理项目经历。",
                tool_calls=(
                    ToolCall(
                        id=f"call-{index}",
                        name="cv_editor_agent",
                        arguments={"path": "projects[0]"},
                    ),
                ),
            )
        )
        messages.append(
            AgentMessage(
                role="tool",
                content=(f"tool output {index} " + "x" * chars),
                tool_call_id=f"call-{index}",
                name="cv_editor_agent",
                supersede_key="resume_edit",
            )
        )
    return messages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--chars", type=int, default=4000)
    parser.add_argument("--max-chars", type=int, default=24000)
    args = parser.parse_args()

    source = build_messages(args.rounds, args.chars)
    transformed = transform_context(
        source,
        CompactionPolicy(max_chars=args.max_chars, keep_recent_messages=8),
    )
    before = sum(len(message.content) for message in source)
    after = sum(len(message.content) for message in transformed)
    superseded = sum(
        1
        for message in transformed
        if message.metadata.get("superseded")
    )
    compacted = sum(
        1
        for message in transformed
        if message.metadata.get("compacted")
    )
    print(
        json.dumps(
            {
                "rounds": args.rounds,
                "before_chars": before,
                "after_chars": after,
                "reduction_ratio": round(1 - after / before, 4) if before else 0,
                "superseded_messages": superseded,
                "compacted_messages": compacted,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
