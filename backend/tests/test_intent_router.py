"""IntentRouter 决策表回归（2026-07-11 LLM-first 一次性了断后重写）：

路由判定从 think() 迁出,决策表按现状行为锁定——
诊断兜底(内部覆盖但仍被 LLM-first 让权收回) / 发送守卫 / LLM-first 无条件全量
让权(唯一路径,无回退开关) / GREETING 不让权 / enhanced_query 清洗(无条件丢弃
规则改写) / 复合请求提示 / process_input 恰好一次。

原"规则模式"(llm_first=False)/"无简历让权"两组用例测的是已随
AGENT_LLM_FIRST_ROUTING 回退开关一并删除的规则分派路径,不再保留。
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.core.logger import setup_logging
setup_logging(False, "INFO", "logs/test")

import backend.agent.pi_core.resume_agent as runtime_module  # noqa: F401 包初始化
from backend.agent.agent.intent_router import IntentRouter, RoutingContext
from backend.agent.application.conversation.conversation_state import Intent


class FakeConversationState:
    """process_input 桩:记录调用次数,返回预设意图结果"""

    def __init__(self, result):
        self._result = result
        self.calls = 0

    async def process_input(self, **kwargs):
        self.calls += 1
        return dict(self._result)


def make_router(rule_result):
    state = FakeConversationState(rule_result)
    router = IntentRouter(state)
    return router, state


def ctx():
    return RoutingContext(recent_messages=[], last_ai_message=None)


def run(coro):
    return asyncio.run(coro)


BASE = {
    "intent": Intent.UNKNOWN, "tool": None, "tool_args": {},
    "intent_source": "fast_rule", "enhanced_query": "", "intent_result": None,
}


# ---------- 决策表 ----------

def test_greeting_never_yields():
    router, state = make_router({**BASE, "intent": Intent.GREETING})
    out = run(router.decide("你好", ctx()))
    assert out.intent == Intent.GREETING
    assert out.yield_reason is None
    assert state.calls == 1


def test_business_intent_always_yields_llm_first():
    """LLM-first 是唯一路径(无回退开关):任何业务意图一律让权给 ReAct loop"""
    router, _ = make_router(
        {**BASE, "intent": Intent.LOAD_RESUME, "tool": "show_resume"}
    )
    out = run(router.decide("帮我加载简历", ctx()))
    assert out.intent == Intent.UNKNOWN
    assert out.yield_reason == "LLM-first"
    assert out.tool is None


def test_compound_request_sets_hint():
    router, _ = make_router({**BASE, "intent": Intent.OPTIMIZE_SECTION})
    out = run(router.decide("优化第二段实习经历,然后翻译成英文", ctx()))
    # 复合请求先被判定让权原因为"复合请求",而不是被后续 LLM-first 覆盖
    assert out.yield_reason == "复合请求"
    assert out.compound_hint is True


def test_diagnosis_keyword_override_still_yields_llm_first():
    """「诊断」关键词兜底仍会把内部 intent 强转 ANALYZE_RESUME(触发日志/复合判定),
    但 LLM-first 唯一路径下最终仍会把它让权收回 UNKNOWN——覆盖只影响过程,不影响
    最终路由结果。"""
    router, _ = make_router({**BASE, "intent": Intent.UNKNOWN})
    out = run(router.decide("帮我诊断一下简历", ctx()))
    assert out.intent == Intent.UNKNOWN
    assert out.yield_reason == "LLM-first"


def test_enhanced_query_stripped_on_yield():
    router, _ = make_router(
        {**BASE, "intent": Intent.LOAD_RESUME, "tool": "show_resume",
         "enhanced_query": "帮我加载简历 /[tool:show_resume]"},
    )
    out = run(router.decide("帮我加载简历", ctx()))
    assert out.enhanced_query == "帮我加载简历"  # 工具标记被清洗


def test_enhanced_query_stripped_even_without_business_intent():
    """intent 本来是 UNKNOWN(无让权)时,/[tool:] 改写也一律被无条件丢弃"""
    router, _ = make_router(
        {**BASE, "intent": Intent.UNKNOWN,
         "enhanced_query": "随便聊聊 /[tool:show_resume]"},
    )
    out = run(router.decide("随便聊聊", ctx()))
    assert out.enhanced_query == "随便聊聊"
