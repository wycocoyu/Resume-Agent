"""Wave A(P0-1/P0-3)complete 契约锁:单写者 + 多步拼接去重。

Codex review(2026-07-13,gpt-5.6-terra)对 A-1 的两条 P1 的回归锁:
1. complete 单写者:is_complete=True 的发射点全文件必须唯一(post-loop),
   step-tail/qwq 死分支的提前发射不许复活——源码锚点断言。
2. 多步拼接与前端 useCLTP.appendChunk 的前缀/包含合并契约对齐,
   complete 整体替换后不得出现重复段。
"""
import sys
import os
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.core.logger import setup_logging
setup_logging(False, "INFO", "logs/test")

from backend.agent.web.streaming.agent_stream import merge_visible_piece  # noqa: E402

_AGENT_STREAM_PATH = os.path.join(
    os.path.dirname(__file__), "..", "agent", "pi_core", "stream.py"
)


def test_complete_single_writer_source_anchor():
    """is_complete=True 只允许出现在统一 completion builder 中。"""
    with open(_AGENT_STREAM_PATH, encoding="utf-8") as f:
        lines = f.read().splitlines()
    hits = [
        ln for ln in lines
        if re.search(r"is_complete\s*=\s*True", ln) and not ln.strip().startswith("#")
    ]
    assert len(hits) == 1, (
        f"complete 单写者被破坏:源码中 is_complete=True 代码行出现 {len(hits)} 处,"
        f"只允许统一 completion builder 一处(Wave A-1/A-2,Codex review P1-1): {hits}"
    )


def test_merge_identical_piece_dropped():
    parts = ["第一步旁白"]
    merge_visible_piece(parts, "第一步旁白")
    assert parts == ["第一步旁白"]


def test_merge_cumulative_restatement_replaces_last():
    """第二步累积重述第一步(前端 appendChunk Case1 形态)→ 替换而非追加。"""
    parts = ["改了教育经历。"]
    merge_visible_piece(parts, "改了教育经历。接下来处理实习描述。")
    assert parts == ["改了教育经历。接下来处理实习描述。"]


def test_merge_contained_piece_dropped():
    parts = ["改了教育经历。接下来处理实习描述。"]
    merge_visible_piece(parts, "接下来处理实习描述。")
    assert parts == ["改了教育经历。接下来处理实习描述。"]


def test_merge_independent_pieces_accumulate():
    parts = []
    merge_visible_piece(parts, "教育经历这块学校还空着,我补上北京大学。")
    merge_visible_piece(parts, "两段实习的描述再量化一下。")
    assert len(parts) == 2
    assert "\n\n".join(parts).count("实习") == 1


def test_merge_duplicate_of_earlier_nonlast_dropped():
    """与更早(非最后)一段重复也不重进列表。"""
    parts = ["A 段旁白", "B 段旁白"]
    merge_visible_piece(parts, "A 段旁白")
    assert parts == ["A 段旁白", "B 段旁白"]


def test_merge_empty_piece_noop():
    parts = ["x"]
    merge_visible_piece(parts, "")
    assert parts == ["x"]


def _assistant_with_tools(content: str):
    from backend.agent.schema import Message, ToolCall, Function

    return Message(
        role="assistant",
        content=content,
        tool_calls=[
            ToolCall(id="c1", function=Function(name="list_resumes", arguments="{}"))
        ],
    )


def _assistant_plain(content: str):
    from backend.agent.schema import Message

    return Message(role="assistant", content=content)


def test_split_structural_routing_narration_vs_answer():
    """B层:带 tool_calls=旁白,不带=正文——纯结构判定。"""
    from backend.agent.web.streaming.agent_stream import split_turn_messages

    msgs = [
        _assistant_with_tools("好的,我先看看你现有的简历"),
        _assistant_with_tools("有一份「张三_后端」,我获取完整内容看看"),
        _assistant_plain("已经加载好了,内容很扎实~"),
    ]
    narrations, answers = split_turn_messages(msgs)
    assert narrations == [
        "好的,我先看看你现有的简历",
        "有一份「张三_后端」,我获取完整内容看看",
    ]
    assert answers == ["已经加载好了,内容很扎实~"]


def test_split_legacy_marker_message_cleaned_not_routed():
    """老会话历史消息仍是 Thought:/Response: 全文——只做清洗,路由仍看结构。"""
    from backend.agent.web.streaming.agent_stream import split_turn_messages

    msgs = [_assistant_plain("Thought: 内部推理\nResponse: 给用户的正文")]
    narrations, answers = split_turn_messages(msgs)
    assert narrations == []
    assert answers == ["给用户的正文"]


def test_split_all_tool_steps_turn_empty_answer():
    """整轮全是带工具步(ask/挂起场景):split 自身不做提升,由 post-loop
    兜底把最后一条旁白提升为正文(该规则在 execute 内,__ここ__锁 split 的
    纯粹性:它只分类,不决策)。"""
    from backend.agent.web.streaming.agent_stream import split_turn_messages

    msgs = [_assistant_with_tools("我弹个选择框跟你确认几项信息~")]
    narrations, answers = split_turn_messages(msgs)
    assert answers == []
    assert narrations == ["我弹个选择框跟你确认几项信息~"]


def test_split_strips_module_done_markers():
    from backend.agent.web.streaming.agent_stream import split_turn_messages

    msgs = [_assistant_plain("改好了。\n\n[[MODULE_DONE:basic:skip]]")]
    _, answers = split_turn_messages(msgs)
    assert answers == ["改好了。"]
