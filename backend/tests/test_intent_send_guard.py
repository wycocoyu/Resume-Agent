"""复合请求让权守卫:「优化第二段然后翻译成英文」这类组合请求,规则意图必须弃权给 LLM。

原「发送语义让权」用例随「AI 发送简历到邮箱」功能下线一并移除(守卫函数
_has_send_email_intent 已删);本文件现只覆盖复合请求让权(审计 I8 的通用解)。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.core.logger import setup_logging
setup_logging(False, "INFO", "logs/test")

import backend.agent.pi_core.resume_agent as runtime_module  # noqa: F401 包初始化
from backend.agent.agent.intent_router import (
    _looks_like_compound_request,
    _rule_intent_yield_reason,
)


# --- 复合请求让权(审计 I8 的通用解) ---

def test_compound_requests_yield():
    assert _looks_like_compound_request("优化第二段实习经历,然后翻译成英文")
    assert _looks_like_compound_request("帮我改一下名字,顺便分析一下整份简历")
    assert _looks_like_compound_request("先优化项目经历,接着生成一份新简历")
    assert _looks_like_compound_request("把腾讯改成字节,然后帮我导出 PDF")
    assert _looks_like_compound_request("润色第一段,再帮我诊断一下")


def test_single_intent_requests_do_not_yield():
    """单意图请求(哪怕很长/带修饰)必须保留给规则层,防误伤"""
    assert not _looks_like_compound_request("帮我优化一下第二段实习经历,重点突出量化成果和技术栈")
    assert not _looks_like_compound_request("把腾讯改成字节")
    assert not _looks_like_compound_request("再优化一下")  # 延续性单指令:连接词前无动词
    assert not _looks_like_compound_request("分析一下我的简历")
    assert not _looks_like_compound_request("然后呢")
    assert not _looks_like_compound_request("你好")


def test_yield_reason_aggregation():
    assert _rule_intent_yield_reason("优化第二段,然后翻译成英文") == "复合请求"
    assert _rule_intent_yield_reason("优化第二段实习经历") is None
    assert _rule_intent_yield_reason("") is None


def test_greeting_prompt_interpolation_locked():
    """审查 #19:GREETING prompt 必须是 f-string——历史上漏了前缀导致风格指引
    以 {GREETING_STYLE_GUIDANCE} 字面量发给模型,从未生效"""
    from backend.agent.prompt.greeting import GREETING_FAST_PATH_PROMPT, GREETING_STYLE_GUIDANCE

    assert "{GREETING_STYLE_GUIDANCE}" not in GREETING_FAST_PATH_PROMPT
    assert GREETING_STYLE_GUIDANCE in GREETING_FAST_PATH_PROMPT


def test_pi_core_prepare_keeps_rule_markers_out_of_memory(monkeypatch):
    """规则层只提供路由参考，Pi Core 不把工具标记写回用户消息。"""
    import asyncio

    from backend.agent.pi_core.resume_agent import ResumeAgentRuntime
    from backend.agent.application.conversation.conversation_state import Intent
    from backend.agent.schema import Message, Role

    agent = ResumeAgentRuntime(
        session_id="s-llmfirst-test",
        is_admin=False,
        user_id="uTest32CharBetterAuthIdXyz01",
    )
    domain = agent.domain_agent
    original_input = "帮我加载一下我的简历"
    agent.memory.add_message(Message.user_message(original_input))

    async def fake_process_input(**kwargs):
        return {
            "intent": Intent.LOAD_RESUME,
            "tool": "show_resume",
            "tool_args": {},
            "intent_source": "fast_rule",
            "enhanced_query": f"{original_input} /[tool:show_resume]",
            "intent_result": None,
        }

    monkeypatch.setattr(domain._conversation_state, "process_input", fake_process_input)
    asyncio.run(agent.prepare_turn(original_input))

    user_msgs = [m for m in agent.memory.messages if m.role == Role.USER]
    assert user_msgs and "/[tool:" not in (user_msgs[-1].content or ""), \
        "规则的 enhanced_query 工具标记不得写回 memory"
    assert not hasattr(ResumeAgentRuntime, "think")
    assert not hasattr(ResumeAgentRuntime, "act")
