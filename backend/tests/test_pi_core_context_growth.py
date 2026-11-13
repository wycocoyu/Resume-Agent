"""上下文预算的实测断言（对应 issue #42 验收项「Token 不再成倍膨胀」）。

用 scripts/measure_context_growth.py 的同一套构造，确保：
- 不做处理时上下文随轮次线性膨胀
- 经过 transform_context（supersede + compaction）后基本恒定
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from backend.agent.pi_core.context import CompactionPolicy

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "measure_context_growth.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("measure_context_growth", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_context_growth_is_bounded_by_pi_core() -> None:
    module = _load_script()
    rows = module.measure(8, 6000, CompactionPolicy())

    assert rows[0]["naive"] == rows[0]["pi_core"], "第一轮尚未发生过期输出，两边应相同"

    naive_growth = rows[-1]["naive"] / rows[0]["naive"]
    pi_growth = rows[-1]["pi_core"] / rows[0]["pi_core"]

    assert naive_growth > 5, f"对照组应显著膨胀，实际 {naive_growth:.2f}x"
    assert pi_growth < 1.5, f"pi_core 上下文应基本恒定，实际 {pi_growth:.2f}x"
    assert rows[-1]["pi_core"] < rows[-1]["naive"] / 3


def test_superseded_tool_outputs_are_replaced_not_dropped() -> None:
    """压缩必须保留消息结构（tool_call_id 配对），不能整条删除。"""
    module = _load_script()
    from backend.agent.pi_core.context import transform_context

    history = module.build_history(4, 6000, superseded=True)
    transformed = transform_context(history, CompactionPolicy(max_chars=24_000))

    assert len(transformed) == len(history)
    tool_ids = [m.tool_call_id for m in transformed if m.role == "tool"]
    assert tool_ids == [m.tool_call_id for m in history if m.role == "tool"]
