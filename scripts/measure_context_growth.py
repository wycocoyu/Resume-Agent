"""上下文膨胀实测：对比「不做处理」与「pi_core transform_context」的 token 增长。

对应用户 issue #42 的验收项之一：

    整份简历多模块连续优化场景下，上下文 Token 增长受 transform_context + pruning
    控制不再成倍膨胀。

本脚本构造「每轮都读一次整份简历」的极端场景：旧工具输出带同一个
``supersede_key``，因此新结果应当把旧结果替换为占位符；超出字符预算后再压缩旧消息。

用法：

    python scripts/measure_context_growth.py --rounds 8 --tool-chars 6000
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tiktoken  # noqa: E402

from backend.agent.pi_core.context import CompactionPolicy, transform_context  # noqa: E402
from backend.agent.pi_core.types import AgentMessage, ToolCall  # noqa: E402


def build_history(rounds: int, tool_chars: int, *, superseded: bool) -> list[AgentMessage]:
    """每轮：user 指令 + assistant 旁白 + 一次整份简历读取。"""
    body = ("工作经历：负责订单系统重构，QPS 提升 3 倍。" * (tool_chars // 30 + 1))[:tool_chars]
    messages: list[AgentMessage] = [AgentMessage(role="system", content="你是简历优化助手，遵守事实不捏造。")]
    for index in range(rounds):
        messages.append(AgentMessage(role="user", content=f"第 {index + 1} 轮：优化第 {index + 1} 段经历"))
        messages.append(
            AgentMessage(
                role="assistant",
                content=f"好的，我先读一下第 {index + 1} 段。",
                tool_calls=(ToolCall(id=f"call_{index}", name="cv_reader", arguments={}),),
            )
        )
        messages.append(
            AgentMessage(
                role="tool",
                tool_call_id=f"call_{index}",
                name="cv_reader",
                content=body,
                supersede_key="resume_read" if superseded else None,
            )
        )
    return messages


def count_tokens(messages: Sequence[AgentMessage], encoding) -> int:
    total = 0
    for message in messages:
        total += len(encoding.encode(message.content or ""))
        for call in message.tool_calls:
            total += len(encoding.encode(json.dumps(call.arguments, ensure_ascii=False)))
            total += len(encoding.encode(call.name))
    return total


def measure(rounds: int, tool_chars: int, policy: CompactionPolicy) -> list[dict[str, int]]:
    encoding = tiktoken.get_encoding("cl100k_base")
    rows: list[dict[str, int]] = []
    for n in range(1, rounds + 1):
        naive = count_tokens(build_history(n, tool_chars, superseded=False), encoding)
        compacted = count_tokens(
            transform_context(build_history(n, tool_chars, superseded=True), policy), encoding
        )
        rows.append({"rounds": n, "naive": naive, "pi_core": compacted})
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure context growth with pi_core compaction.")
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--tool-chars", type=int, default=6000, help="每轮工具输出字符数")
    parser.add_argument("--max-chars", type=int, default=24_000, help="context 字符预算")
    parser.add_argument("--keep-recent", type=int, default=8)
    args = parser.parse_args(argv)

    policy = CompactionPolicy(max_chars=args.max_chars, keep_recent_messages=args.keep_recent)
    rows = measure(args.rounds, args.tool_chars, policy)

    print(f"{'轮次':>4} {'不做处理(tokens)':>18} {'pi_core(tokens)':>18} {'节省':>8}")
    print("-" * 54)
    for row in rows:
        saved = 1 - row["pi_core"] / row["naive"] if row["naive"] else 0
        print(
            f"{row['rounds']:>4} {row['naive']:>18,} {row['pi_core']:>18,} {saved:>7.0%}"
        )

    naive_growth = rows[-1]["naive"] / rows[0]["naive"] if rows[0]["naive"] else 0
    pi_growth = rows[-1]["pi_core"] / rows[0]["pi_core"] if rows[0]["pi_core"] else 0
    print("-" * 54)
    print(f"第 1 轮 → 第 {rows[-1]['rounds']} 轮：不做处理 {naive_growth:.1f}×，pi_core {pi_growth:.2f}×")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
