"""建议卡 apply 路由 P1（2026-07-17）：单条正则 / turn 状态 / 结构化建议注入 helper。

覆盖 S1-S3 的可单测部分（纯函数 + 静态 helper + shared_state 取数）；
_sync_turn_read_only_flag 的完整轮次分派靠端到端接口测试覆盖。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.core.logger import setup_logging
setup_logging(False, "INFO", "logs/test")

import pytest

# 先 import 完整 agent 包链，再引用子模块函数，避免裸 import 触发既有循环依赖
from backend.agent.pi_core.resume_domain import ResumeDomainRuntime
from backend.agent.agent.turn_state import TurnExecutionState
from backend.agent.application.conversation.conversation_state import (
    is_diagnosis_apply_single_query,
    is_diagnosis_apply_query,
    is_suggestion_facts_query,
    is_view_suggestions_query,
)


class _FakeShared:
    def __init__(self, d):
        self._d = dict(d)

    def get(self, k, default=None):
        return self._d.get(k, default)

    def set(self, k, v):
        self._d[k] = v


class _Host:
    """借用 Manus 取数 helper（只依赖 self._shared_state），绕开 Pydantic 实例化。"""

    _guidance_suggestions = ResumeDomainRuntime._guidance_suggestions
    _needs_fact_suggestions = ResumeDomainRuntime._needs_fact_suggestions
    _suggestion_by_index = ResumeDomainRuntime._suggestion_by_index

    def __init__(self, shared):
        self._shared_state = shared


def _host_with_assessment(suggestions):
    return _Host(
        _FakeShared(
            {"resume_guidance_assessment": {"details": {"suggestions": suggestions}}}
        )
    )


# ---- S1 单条 apply 正则 ----

@pytest.mark.parametrize(
    "text,expected",
    [
        ("按建议第2条修改：教育经历缺院校", 2),
        ("按建议第10条修改", 10),
        ("按建议第1条优化", 1),
    ],
)
def test_single_apply_regex_extracts_index(text, expected):
    assert is_diagnosis_apply_single_query(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "帮我改第二段工作经历",   # 定向编辑，非按建议
        "查看第2条建议",          # 只读查看
        "先别按建议第2条改",      # 否定
        "全部按建议修改",         # 一键（走整体，不是单条）
    ],
)
def test_single_apply_regex_rejects_non_single(text):
    assert is_diagnosis_apply_single_query(text) is None


# ---- P2 单条缺口收集正则(补充第N条建议) ----

@pytest.mark.parametrize(
    "text,expected",
    [
        ("补充第1条建议需要的信息：教育经历缺少起止时间", 1),
        ("补充第3条建议需要的信息", 3),
    ],
)
def test_facts_regex_extracts_index(text, expected):
    assert is_suggestion_facts_query(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "补充第二段经历",          # 普通编辑表达,无「条建议」锚
        "帮我补充一下教育经历",
        "先别补充第1条建议",       # 否定
        "按建议第2条修改：xxx",    # 单条 apply,不是缺口收集
    ],
)
def test_facts_regex_rejects_non_facts(text):
    assert is_suggestion_facts_query(text) is None


def test_facts_and_single_apply_disjoint():
    # 两个入口消息互不误伤
    assert is_diagnosis_apply_single_query("补充第2条建议需要的信息：xxx") is None
    assert is_suggestion_facts_query("按建议第2条修改：xxx") is None


def test_apply_and_view_stay_mutually_exclusive():
    # 单条改动不能破坏既有 apply/view 互斥
    assert is_diagnosis_apply_query("按照诊断建议帮我修改简历")
    assert is_view_suggestions_query("查看这次诊断的修改建议")
    assert not is_diagnosis_apply_query("查看这次诊断的修改建议")


# ---- S2 turn 状态新字段 ----

def test_turn_state_new_fields_default_and_reset():
    t = TurnExecutionState()
    assert t.diagnosis_apply_single is None
    assert t.diagnosis_gap_collect is False
    t.diagnosis_apply_single = 3
    t.diagnosis_gap_collect = True
    t.reset_for_new_turn()
    assert t.diagnosis_apply_single is None
    assert t.diagnosis_gap_collect is False


# ---- S4/S5 结构化建议注入 helper ----

_PROPOSED = {
    "suggestion_id": "s1", "section": "experience", "title": "量化实习成果",
    "status": "proposed", "recommendation": "补充具体指标",
    "proposed": "将接口耗时从2s降到380ms",
}
_NEEDS_FACT = {
    "suggestion_id": "s2", "section": "education", "title": "教育经历缺院校",
    "status": "needs_fact", "recommendation": "补齐院校/专业/学位",
    "requires_facts": ["院校全称", "专业名称", "学位类型"],
}


def test_format_suggestions_block_mixed():
    h = _host_with_assessment([_PROPOSED, _NEEDS_FACT])
    block = ResumeDomainRuntime._format_suggestions_block(h._guidance_suggestions())
    assert "1. [experience] 量化实习成果" in block
    assert "参考改写：将接口耗时从2s降到380ms" in block
    assert "2. [education] 教育经历缺院校 — 需补充：院校全称、专业名称、学位类型" in block


def test_needs_fact_suggestions_filters():
    h = _host_with_assessment([_PROPOSED, _NEEDS_FACT])
    needs = h._needs_fact_suggestions()
    assert len(needs) == 1 and needs[0]["suggestion_id"] == "s2"


def test_format_gap_block_only_needs_fact():
    h = _host_with_assessment([_PROPOSED, _NEEDS_FACT])
    gap = ResumeDomainRuntime._format_gap_block(h._needs_fact_suggestions())
    assert gap == "- [education] 教育经历缺院校：需要 院校全称、专业名称、学位类型"


def test_suggestion_by_index_bounds():
    h = _host_with_assessment([_PROPOSED, _NEEDS_FACT])
    assert h._suggestion_by_index(1)["suggestion_id"] == "s1"
    assert h._suggestion_by_index(2)["suggestion_id"] == "s2"
    assert h._suggestion_by_index(3) is None   # 越界
    assert h._suggestion_by_index(0) is None
    assert h._suggestion_by_index(None) is None


def test_helpers_empty_when_no_assessment():
    h = _Host(_FakeShared({}))
    assert h._guidance_suggestions() == []
    assert h._needs_fact_suggestions() == []
    assert h._suggestion_by_index(1) is None


# ---- 单条 apply 命中 needs_fact 的兜底 prompt（消除"承诺提问却不问"断层）----

def test_single_apply_prompt_proposed_edits_directly():
    p = ResumeDomainRuntime._build_single_apply_prompt(_PROPOSED)
    assert "只改这一条建议" in p
    assert "量化实习成果" in p


def test_single_apply_prompt_needs_fact_no_fake_ask():
    p = ResumeDomainRuntime._build_single_apply_prompt(_NEEDS_FACT)
    assert "缺少真实信息" in p
    assert "不要调用" in p and "ask_user_question" in p  # 不假装提问
    assert "教育经历缺院校" in p and "院校全称" in p       # 列出缺什么
