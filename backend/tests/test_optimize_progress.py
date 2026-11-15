"""整份优化进度模型单测（2026-07-12，设计方案七点二）。

覆盖：pending 由简历结构确定性算出、MODULE_DONE 标记解析、模块推进 +
相变 optimizing→reviewing 零步数触发、续跑计数、进度清单渲染。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.core.logger import setup_logging
setup_logging(False, "INFO", "logs/test")

import json

import backend.agent.pi_core.resume_agent as _runtime  # noqa: F401 触发 tool 包初始化，避开循环导入
from backend.agent.pi_core.resume_domain import ResumeDomainRuntime
from backend.agent.schema import Function, Message, ToolCall
from backend.agent.utils.optimize_progress import (
    compute_pending_modules,
    parse_module_done_markers,
    slice_resume_context_for_module,
    strip_module_done_markers,
    render_progress_checklist,
    normalize_module_name,
    OPTIMIZE_MODULES,
)
from backend.agent.tool.resume_data_store import ResumeDataStore


_SAMPLE_RESUME = {
    "basic": {"name": "张三", "title": "后端工程师", "email": "a@b.com"},
    "education": [{"school": "XX大学", "degree": "本科"}],
    "experience": [{"company": "美团", "details": "<p>QPS 提升3倍</p>"}],
    "projects": [
        {"name": "Agent Swarm", "description": "智能路由 70% 单Agent / 30% Swarm"},
        {"name": "P2", "description": "x"},
    ],
    "skillContent": "Python、Go、Kafka",
    "selfEvaluation": "",  # 空 → 不进 pending
    "openSource": [],       # 空 → 不进 pending
}


def test_compute_pending_includes_empty_modules():
    """空模块也要进 pending(除 basic 空),这样 agent 才有机会决定问用户还是跳过,
    而不是假装这个模块不存在。用户实测:简历没教育经历,整份优化时 agent 直接
    从工作经历开干,全程不知道 education 存在,从不主动问。"""
    pending = compute_pending_modules(_SAMPLE_RESUME)
    # basic 有内容 → 进;其余模块(含空的 selfEvaluation/openSource/awards)也全进
    assert "basic" in pending
    assert "education" in pending
    assert "experience" in pending
    assert "projects" in pending
    assert "skillContent" in pending
    # 空模块现在也要进 pending(以前被排除,导致 agent 看不到)
    assert "selfEvaluation" in pending
    assert "openSource" in pending
    assert "awards" in pending


def test_compute_pending_basic_empty_excluded():
    """basic(姓名/电话/邮箱)空了不进 pending——红线,空了直接跳过不问。
    其余模块即使空也进 pending。"""
    pending = compute_pending_modules({"education": [], "experience": [], "basic": {}})
    assert "basic" not in pending  # basic 空了排除
    assert "education" in pending
    assert "experience" in pending


def test_compute_pending_empty_resume():
    """空 dict / None:basic 空排除,其余模块全进 pending(让 agent 有机会问)。
    实际场景里空简历会在更上层被拦(先走创建流程),不靠这里挡。"""
    assert compute_pending_modules(None) == []
    # 空 dict:除 basic 外全进
    pending_empty = compute_pending_modules({})
    assert "basic" not in pending_empty
    assert len(pending_empty) == len(OPTIMIZE_MODULES) - 1  # 除 basic


def test_parse_markers_basic_and_skip():
    text = "优化完了。\n[[MODULE_DONE:experience]]"
    assert parse_module_done_markers(text) == [("experience", False)]
    assert parse_module_done_markers("[[MODULE_DONE:projects:skip]]") == [("projects", True)]


def test_parse_markers_aliases_and_case():
    assert parse_module_done_markers("[[module_done: Skills ]]") == [("skillContent", False)]
    assert parse_module_done_markers("[[MODULE_DONE:opensource]]") == [("openSource", False)]
    assert parse_module_done_markers("[[MODULE_DONE:garbage]]") == []


def test_normalize_module_name():
    assert normalize_module_name("Experience") == "experience"
    assert normalize_module_name("skills") == "skillContent"
    assert normalize_module_name("???") is None


def test_strip_markers_removed_from_display():
    text = "已优化经历模块。\n\n[[MODULE_DONE:experience]]"
    stripped = strip_module_done_markers(text)
    assert "MODULE_DONE" not in stripped
    assert "已优化经历模块" in stripped


def test_render_checklist_marks_current_module():
    progress = {"pending": ["experience", "projects"], "done": ["education"]}
    text = render_progress_checklist(progress)
    assert "当前模块" in text
    assert "experience" in text
    assert "[[MODULE_DONE:experience]]" in text  # 教 LLM 用当前模块 key


def _reset(sid):
    ResumeDataStore.clear_progress(sid)


def test_storage_lifecycle_and_phase_transition():
    sid = "progress-lifecycle-test"
    _reset(sid)
    progress = ResumeDataStore.init_progress(sid, _SAMPLE_RESUME)
    assert progress["status"] == "optimizing"
    assert progress["pending"][0] == "basic"
    assert progress["facts"], "初始化应缓存各模块 facts"
    # experience 模块应抽出数字实体
    assert any("3倍" in f for f in progress["facts"].get("experience", []))

    # 幂等：未完成任务重复 init 复用同一个 task_id
    same = ResumeDataStore.init_progress(sid, _SAMPLE_RESUME)
    assert same["task_id"] == progress["task_id"]

    # 逐个推进，最后一个模块处理完触发相变（零步数）
    for mod in list(progress["pending"]):
        still_optimizing = ResumeDataStore.get_progress(sid)["status"] == "optimizing"
        assert still_optimizing
        ResumeDataStore.mark_module_done(sid, mod)

    final = ResumeDataStore.get_progress(sid)
    assert final["pending"] == []
    assert final["status"] == "reviewing", "pending 清空应相变到 reviewing"
    assert set(final["done"]) == set(_SAMPLE_RESUME_MODULES())

    _reset(sid)


def test_mark_module_done_idempotent():
    sid = "progress-idempotent-test"
    _reset(sid)
    ResumeDataStore.init_progress(sid, _SAMPLE_RESUME)
    assert ResumeDataStore.mark_module_done(sid, "basic") is True
    # 重复推进同一模块 → no-op，不报错
    assert ResumeDataStore.mark_module_done(sid, "basic") is False
    # 未知模块 → no-op
    assert ResumeDataStore.mark_module_done(sid, "nonexistent") is False
    _reset(sid)


def test_continue_count_and_review_flag():
    sid = "progress-continue-test"
    _reset(sid)
    ResumeDataStore.init_progress(sid, _SAMPLE_RESUME)
    assert ResumeDataStore.bump_continue_count(sid) == 1
    assert ResumeDataStore.bump_continue_count(sid) == 2
    ResumeDataStore.mark_review_dispatched(sid)
    assert ResumeDataStore.get_progress(sid)["review_dispatched"] is True
    ResumeDataStore.finish_progress(sid)
    assert ResumeDataStore.get_progress(sid) is None


def _SAMPLE_RESUME_MODULES():
    return compute_pending_modules(_SAMPLE_RESUME)


# ---- round5 独立 review 发现并修复的真实 bug ----

_MULTI_MODULE_TEXT = (
    "# CV\n"
    "## Education\nedu content\n"
    "## Work Experience\nwork content\n"
    "## Projects\nproj content\n"
)


def test_slice_returns_full_text_when_current_module_header_missing():
    """current_module 对应的 `## ` 标题不存在（模块被清空/结构变了）时，
    保守回退全文，不能把每个识别到的模块都当"非当前模块"整体砍掉。"""
    out = slice_resume_context_for_module(_MULTI_MODULE_TEXT, "skillContent")
    assert out == _MULTI_MODULE_TEXT


def test_slice_still_slices_when_current_module_present():
    out = slice_resume_context_for_module(_MULTI_MODULE_TEXT, "projects")
    assert "proj content" in out
    assert "edu content" not in out
    assert "延后发送" in out


class _FakeMemory:
    def __init__(self, messages):
        self.messages = messages


class _FakeAgentForSignal2:
    """只装 _confirm_optimize_progress_from_results 依赖的最小字段。"""

    session_id = "signal2-test-session"

    def __init__(self, tool_calls, messages):
        self.tool_calls = tool_calls
        self.memory = _FakeMemory(messages)

    _confirm_optimize_progress_from_results = ResumeDomainRuntime._confirm_optimize_progress_from_results


def _cv_editor_call(path: str) -> ToolCall:
    return ToolCall(
        id="call1",
        type="function",
        function=Function(
            name="cv_editor_agent",
            arguments=json.dumps({"path": path, "action": "update", "value": "x"}),
        ),
    )


def test_signal2_does_not_advance_on_tool_failure():
    """think() 阶段的 tool_calls 只是"决定调用"，act() 真执行失败不该
    推进模块——否则一次没生效的编辑被永久标记成已完成。"""
    sid = _FakeAgentForSignal2.session_id
    _reset(sid)
    ResumeDataStore.init_progress(sid, _SAMPLE_RESUME)
    call = _cv_editor_call("education[0].school")
    msg = Message.tool_message(
        content="Observed output of cmd `cv_editor_agent` executed:\nError: boom",
        tool_call_id="call1",
        name="cv_editor_agent",
    )
    agent = _FakeAgentForSignal2([call], [msg])
    agent._confirm_optimize_progress_from_results()
    assert "education" in ResumeDataStore.get_progress(sid)["pending"]
    _reset(sid)


def test_signal2_does_not_advance_on_readonly_block():
    """只读轮次拦截返回的纯文本不经过 ToolResult、不带 Error: 前缀，
    必须单独识别，否则被拦截的编辑也会被误判成完成。"""
    sid = _FakeAgentForSignal2.session_id
    _reset(sid)
    ResumeDataStore.init_progress(sid, _SAMPLE_RESUME)
    call = _cv_editor_call("education[0].school")
    msg = Message.tool_message(
        content="错误：本轮为只读查看请求，禁止修改代码或简历。",
        tool_call_id="call1",
        name="cv_editor_agent",
    )
    agent = _FakeAgentForSignal2([call], [msg])
    agent._confirm_optimize_progress_from_results()
    assert "education" in ResumeDataStore.get_progress(sid)["pending"]
    _reset(sid)


def test_signal2_advances_on_real_success():
    sid = _FakeAgentForSignal2.session_id
    _reset(sid)
    ResumeDataStore.init_progress(sid, _SAMPLE_RESUME)
    call = _cv_editor_call("education[0].school")
    msg = Message.tool_message(
        content="Observed output of cmd `cv_editor_agent` executed:\n✅ 更新成功",
        tool_call_id="call1",
        name="cv_editor_agent",
    )
    agent = _FakeAgentForSignal2([call], [msg])
    agent._confirm_optimize_progress_from_results()
    assert "education" not in ResumeDataStore.get_progress(sid)["pending"]
    assert "education" in ResumeDataStore.get_progress(sid)["done"]
    _reset(sid)


# ---- 信号3：无工具调用兜底 + 提问澄清时不误跳过（用户实测截图复现的真实bug）----

class _FakeAgentForSignal3:
    """信号3依赖完整的 _get_last_user_input 链路，补齐 Manus 的三个helper。"""

    session_id = "signal3-test-session"

    def __init__(self, assistant_content, user_content="优化我的整份简历"):
        user_msg = Message.user_message(user_content)
        assistant_msg = Message.assistant_message(assistant_content)
        self.memory = _FakeMemory([user_msg, assistant_msg])
        self.tool_calls = []

    _advance_optimize_progress = ResumeDomainRuntime._advance_optimize_progress
    _get_last_user_input = ResumeDomainRuntime._get_last_user_input
    _get_last_user_message_idx = ResumeDomainRuntime._get_last_user_message_idx
    _is_injected_system_user_message = staticmethod(ResumeDomainRuntime._is_injected_system_user_message)


def test_signal3_skips_current_module_when_no_question():
    """无工具调用 + 声明句（不含问号）+ 本轮跟整份优化相关 → 正常触发skip推进
    （信号3设计的本意场景：LLM判断这块不用改，往下走）。"""
    sid = _FakeAgentForSignal3.session_id
    _reset(sid)
    ResumeDataStore.init_progress(sid, _SAMPLE_RESUME)
    current = ResumeDataStore.get_progress(sid)["pending"][0]
    agent = _FakeAgentForSignal3("这部分内容已经很完整了，不需要修改。")
    agent._advance_optimize_progress()
    assert current not in ResumeDataStore.get_progress(sid)["pending"]
    _reset(sid)


def test_signal3_does_not_skip_when_asking_clarifying_question():
    """独立review发现并修复的真实bug（用户实测截图复现）：LLM针对当前模块
    问了个澄清问题（"有没有奖学金？GPA多少？你可以说没有跳过"），没调用
    工具——命中信号3的"无工具调用"条件，旧逻辑会直接判定这个模块"跳过"
    往下推进，auto_continue紧接着用系统合成消息糊上下一个模块的处理结果，
    用户压根没来得及回答，问题白问。修复后：本轮回复含问号，一律不触发
    自动跳过，让pending原样保留，真等用户下一句真实回复。"""
    sid = _FakeAgentForSignal3.session_id
    _reset(sid)
    ResumeDataStore.init_progress(sid, _SAMPLE_RESUME)
    pending_before = list(ResumeDataStore.get_progress(sid)["pending"])
    agent = _FakeAgentForSignal3(
        "你的教育经历目前只有基本信息，在校期间有获得过奖学金、荣誉称号吗？"
        "GPA或专业排名情况如何？你可以直接说没有，跳过。"
    )
    agent._advance_optimize_progress()
    assert ResumeDataStore.get_progress(sid)["pending"] == pending_before
    _reset(sid)


# ---- Asking 模式：ask_user_question 工具 + structured_data 透传 ----

def test_ask_user_question_tool_returns_structured_data():
    """ask_user_question 工具 execute 后，返回的 ToolResult 带
    structured_data={type:"ask_question", questions:[...]}，每问固定两选项
    （直接填写/直接跳过），供前端 StructuredCardRegistry 渲染 AskQuestionCard。"""
    import asyncio
    from backend.agent.tool.ask_user_question_tool import AskUserQuestionTool

    tool = AskUserQuestionTool()
    result = asyncio.new_event_loop().run_until_complete(
        tool.execute(
            questions=[
                {"question": "你的 GPA 或专业排名？", "header": "GPA"},
                {"question": "有没有奖学金或竞赛奖项？", "header": "奖项"},
            ]
        )
    )
    assert result.structured_data is not None
    assert result.structured_data["type"] == "ask_question"
    qs = result.structured_data["questions"]
    assert len(qs) == 2
    # 每问固定两选项，标签对齐设计稿（二元化，不做内容分类）
    for q in qs:
        labels = [o["label"] for o in q["options"]]
        assert labels == ["直接填写", "直接跳过"]
        assert q["multiSelect"] is False


def test_ask_user_question_tool_rejects_empty_questions():
    """空 questions 数组或缺 question 字段，工具应返回 error，不产出
    structured_data——防止前端拿到空选择框。"""
    import asyncio
    from backend.agent.tool.ask_user_question_tool import AskUserQuestionTool

    tool = AskUserQuestionTool()
    # 空数组
    r1 = asyncio.new_event_loop().run_until_complete(tool.execute(questions=[]))
    assert r1.error
    assert r1.structured_data is None
    # 缺 question 字段
    r2 = asyncio.new_event_loop().run_until_complete(
        tool.execute(questions=[{"header": "只有header"}])
    )
    assert r2.error
    assert r2.structured_data is None


def test_verify_facts_coverage_all_present():
    """Wave A-3(P1-1):facts 全部保留 → 空 dict。"""
    from backend.agent.utils.optimize_progress import verify_facts_coverage

    progress = {"facts": {"experience": ["97%", "腾讯"], "education": ["北京大学"]}}
    resume = {
        "experience": [{"company": "腾讯", "details": "缓存命中率 97%"}],
        "education": [{"school": "北京大学"}],
    }
    assert verify_facts_coverage(progress, resume) == {}


def test_verify_facts_coverage_reports_missing():
    """被误删的实体按模块报缺;其余模块不误报。"""
    from backend.agent.utils.optimize_progress import verify_facts_coverage

    progress = {"facts": {"experience": ["97%", "腾讯"], "education": ["北京大学"]}}
    resume = {
        "experience": [{"company": "腾讯", "details": "优化了本地缓存架构"}],  # 97% 被删
        "education": [{"school": "北京大学"}],
    }
    missing = verify_facts_coverage(progress, resume)
    assert missing == {"experience": ["97%"]}


def test_verify_facts_coverage_empty_inputs():
    from backend.agent.utils.optimize_progress import verify_facts_coverage

    assert verify_facts_coverage({}, {"a": 1}) == {}
    assert verify_facts_coverage({"facts": {"x": ["y"]}}, {}) == {}


def test_reviewing_checklist_renders_facts():
    """审阅 prompt 渲染原文关键实体核对清单(facts 从死数据接入,Wave A-3)。"""
    from backend.agent.utils.optimize_progress import render_progress_checklist

    progress = {
        "status": "reviewing",
        "pending": [],
        "done": ["experience", "education"],
        "facts": {"experience": ["97%", "QPS 3000"], "education": []},
    }
    text = render_progress_checklist(progress)
    assert "最终一致性审阅" in text
    assert "核对清单" in text
    assert "97%" in text and "QPS 3000" in text
    # 空 facts 的模块不渲染行
    assert text.count("  - ") == 1


def test_verify_facts_coverage_cross_module_move_not_missing():
    """跨模块迁移不算缺失(Codex A-3 review P1):项目里的 97% 挪进工作经历。"""
    from backend.agent.utils.optimize_progress import verify_facts_coverage

    progress = {"facts": {"projects": ["97%", "Agent Swarm"]}}
    resume = {
        "projects": [{"name": "其他项目"}],
        "experience": [{"details": "Agent Swarm 系统缓存命中率 97%"}],
    }
    assert verify_facts_coverage(progress, resume) == {}


def test_reviewing_checklist_bounded_rendering():
    """facts 渲染限流(Codex A-3 review P2):超出部分提示由代码全量核验。"""
    from backend.agent.utils.optimize_progress import render_progress_checklist

    progress = {
        "status": "reviewing",
        "pending": [],
        "done": ["experience"],
        "facts": {"experience": [f"实体{i}" for i in range(100)]},
    }
    text = render_progress_checklist(progress)
    assert "实体0" in text and "实体11" in text
    assert "实体12" not in text  # 每模块 12 项截断
    assert "其余 88 项" in text and "全量核验" in text
