import json
import re
from typing import Any, Dict, List, Optional
from pathlib import Path

from pydantic import Field, model_validator, PrivateAttr

from backend.agent.pi_core.tool_runtime import ToolExecutionRuntime
from backend.agent.config import config
from backend.core.logger import get_logger

logger = get_logger(__name__)
from backend.agent.prompt.manus import (
    DIAGNOSIS_APPLY_PROMPT,
    DIAGNOSIS_APPLY_PROMPT_V3,
    SINGLE_APPLY_PROMPT,
    SINGLE_APPLY_NEEDS_FACT_PROMPT,
    GAP_COLLECT_PROMPT,
    VIEW_SUGGESTIONS_PROMPT,
    NEXT_STEP_PROMPT,
    SYSTEM_PROMPT,
)
from backend.agent.prompt.voice import apply_visible_action_narration_guidance
from backend.agent.utils.resume_richtext import html_to_context_text, normalize_editor_value
from backend.agent.tool import Terminate, ToolCollection
from backend.agent.memory import (
    ChatHistoryManager,
    ConversationStateManager,
    ConversationState,
    Intent,
)
from backend.agent.application.conversation.conversation_state import (
    ResumeRequestRoute,
    classify_resume_request,
    is_add_experience_query,
    is_diagnosis_apply_query,
    is_diagnosis_apply_single_query,
    is_suggestion_facts_query,
    is_view_suggestions_query,
    is_full_optimize_query,
    is_read_only_query,
)
from backend.agent.utils.optimize_progress import (
    is_optimize_continuation_message,
    parse_module_done_markers,
    resolve_module_from_path,
)
from backend.agent.schema import Message, Role, ToolCall
from backend.agent.agent.shared_state import AgentSharedState
from backend.agent.agent.turn_state import TurnExecutionState
from backend.agent.agent.prompt_builder import PromptBuilder
from backend.agent.agent.intent_router import IntentRouter, RoutingContext
from backend.agent.tool.resume_data_store import ResumeDataStore
from backend.agent.feature_flags import (
    ASKING_MODE_DISABLED_PROMPT,
    is_asking_mode_enabled,
)
from backend.agent.pi_core.resume_tools import (
    build_resume_tool_collection,
    execute_resume_tool_native,
    inject_resume_tool_context,
)
from backend.agent.pi_core.turn_policy import (
    TurnPolicySnapshot,
    blocked_tool_reason,
)

# cv_editor_agent 执行失败/被拦截时的工具消息特征，跟成功输出区分开
# （见 ResumeDomainRuntime._confirm_optimize_progress_from_results）。只读轮次拦截
# （ResumeDomainRuntime.execute_tool override）直接返回这段纯文本，不经过 ToolResult，
# 所以不带 "Error:" 前缀，必须单独识别。放在模块级而不是类属性——Manus
# 是 pydantic BaseModel 子类，下划线开头的类属性会被当成 private attr
# 描述符拦截，赋值成普通 tuple 在实例上取到的是 ModelPrivateAttr 而不是
# 值本身（round5 review 修复时实测踩过这个坑）。
_CV_EDITOR_FAILURE_MARKERS = (
    "Error:",
    "本轮为只读查看请求",
    # 只读诊断轮拦截文案前缀（2026-07-16 起为"本轮只做简历诊断，不修改简历"，
    # 旧文案"本轮只做简历诊断和修改建议"同样命中此前缀）
    "本轮只做简历诊断",
    # 查看建议轮拦截文案（2026-07-16 诊断/建议拆分）
    "本轮只展示诊断的修改建议",
    "已跳过：",
    "已跳过:",
)


class ResumeDomainRuntime(ToolExecutionRuntime):
    """A versatile general-purpose agent with local tool orchestration.

    集成 LangChain 风格的 Memory 系统提供智能对话管理：
    - ChatHistoryManager: 管理对话历史
    - ConversationStateManager: 意图识别和状态管理
    """

    name: str = "ResumeAgent"
    description: str = "A versatile agent that can solve various tasks using multiple local tools"
    native_pi_core_tools: bool = True

    # 使用动态系统提示词
    system_prompt: str = ""
    next_step_prompt: str = ""
    session_id: Optional[str] = None
    capability: Optional[str] = None
    # 管理员会话标识:保留供管理员专属工具注册使用(邮件功能下线后暂无消费者)
    is_admin: bool = False
    # 当前会话所属用户 id,注入给需要按用户查库的工具(如邮箱凭证)
    user_id: Optional[str] = None

    max_observe: int = 10000
    max_steps: int = 20

    # Add general-purpose tools to the tool collection
    available_tools: ToolCollection = Field(default_factory=ToolCollection)

    special_tool_names: list[str] = Field(
        default_factory=lambda: [Terminate().name, "cv_analyzer_agent"]
    )

    # Memory components - 使用 PrivateAttr 避免 pydantic 验证
    _conversation_state: ConversationStateManager = PrivateAttr(default=None)
    _chat_history: ChatHistoryManager = PrivateAttr(default=None)
    _last_intent: Intent = PrivateAttr(default=None)
    _last_intent_info: Dict[str, Any] = PrivateAttr(default_factory=dict)
    _current_resume_path: Optional[str] = PrivateAttr(default=None)
    _shared_state: AgentSharedState = PrivateAttr(default=None)
    _skills_cache: Dict[str, str] = PrivateAttr(default_factory=dict)
    _prompt_builder: PromptBuilder = PrivateAttr(default=None)
    _intent_router: IntentRouter = PrivateAttr(default=None)
    # Wave 2a-S1:原 5 个散落 flag 收拢进 TurnExecutionState。S4c-1 起内部直接读写
    # self._turn.*。Wave A-2(P0-3):_pending_immediate_stream 委托已随
    # AgentStream 死分支一并删除(全仓无生产者)。
    _turn: TurnExecutionState = PrivateAttr(default_factory=TurnExecutionState)

    @model_validator(mode="after")
    def initialize_helper(self) -> "ResumeDomainRuntime":
        """Initialize basic components synchronously."""
        self.available_tools = self._build_tool_collection()
        self._init_shared_state()
        # 初始化对话状态管理器（LLM 会在 base.py 的 initialize_agent 中初始化）
        # 传递 tool_collection 以支持增强意图识别
        self._conversation_state = ConversationStateManager(
            llm=None,
            tool_collection=self.available_tools,
            use_enhanced_intent=True,
            session_id=self.session_id,
        )
        # 初始化聊天历史管理器
        self._chat_history = ChatHistoryManager(
            k=30,
            session_id=self.session_id,
        )  # 滑动窗口：保留最近30条消息
        # Wave 2a-S2:动态 prompt 构造迁 PromptBuilder,共享 skills 缓存
        self._prompt_builder = PromptBuilder(
            session_id=self.session_id,
            capability=self.capability,
            skills_cache=self._skills_cache,
        )
        # Wave 2a-S4a:意图识别+让权守卫收口 IntentRouter(守卫规则函数已平移进
        # intent_router 模块级,不再从 manus 注入)
        self._intent_router = IntentRouter(self._conversation_state)
        return self

    def _build_tool_collection(self) -> ToolCollection:
        """Build tool collection based on capability settings."""
        return build_resume_tool_collection(self.capability)

    def _init_shared_state(self) -> None:
        """Initialize session-scoped shared state and inject into tools."""
        session_id = self.session_id or "default"
        self._shared_state = AgentSharedState(session_id=session_id)
        ResumeDataStore.set_shared_state(session_id, self._shared_state)
        self._inject_tool_context(self.available_tools.tools)

    def _inject_tool_context(self, tools: List[Any]) -> None:
        """Attach session_id and shared_state to tools."""
        inject_resume_tool_context(
            tools,
            session_id=self.session_id,
            user_id=self.user_id,
            shared_state=self._shared_state,
        )

    def _ensure_conversation_state_llm(self):
        """确保 ConversationStateManager 有 LLM 实例"""
        if self._conversation_state and not self._conversation_state.llm and self.llm:
            self._conversation_state.llm = self.llm

    async def cleanup(self):
        """Clean up resume runtime resources."""
        return None

    async def execute_tool(self, command: ToolCall) -> str:
        """只读查看/诊断轮次拦截误触发的写入与追问工具。"""
        name = ""
        if command and command.function:
            name = command.function.name or ""
        if self._turn.read_only and name in (
            "cv_editor_agent",
            "str_replace_editor",
        ):
            logger.info(f"📖 只读轮次拦截 {name} 调用")
            return (
                "错误：本轮为只读查看请求，禁止修改代码或简历。"
                "请直接根据 system prompt 中已注入的「# CV/Resume Context」完整回答，"
                "勿调用 cv_editor_agent、str_replace_editor 或任何文件编辑工具。"
            )
        if self._turn.view_suggestions and name in (
            "cv_editor_agent",
            "str_replace_editor",
            "cv_analyzer_agent",
            "ask_human",
            "ask_user_question",
        ):
            logger.info(f"💡 查看建议轮次拦截 {name} 调用")
            return (
                "错误：本轮只展示诊断的修改建议，不修改简历，也不重新诊断。"
                "请调用 cv_suggestions_agent 展示建议卡，然后结束本轮。"
            )
        if self._turn.diagnosis_only and name in (
            "cv_editor_agent",
            "str_replace_editor",
            "ask_user_question",
        ):
            logger.info(f"🩺 只读诊断轮次拦截 {name} 调用")
            return (
                "错误：本轮只做简历诊断，不修改简历，也不进入追问补全流程。"
                "请调用 cv_analyzer_agent，并在诊断卡生成后结束本轮。"
            )
        if self._turn.diagnosis_apply and name in (
            "ask_human",
            "ask_user_question",
        ):
            logger.info(f"📌 apply 轮拦截 {name} 调用（缺信息跳过，不提问）")
            return (
                "本轮为一次性应用诊断建议：缺少真实信息的建议直接跳过，"
                "不向用户提问。请继续处理其余建议，收尾时在「需你补充」清单中列出跳过项。"
            )
        if self._turn.diagnosis_gap_collect and name in (
            "cv_editor_agent",
            "str_replace_editor",
        ):
            logger.info(f"📋 缺口收集轮拦截 {name}（先补齐信息再改）")
            return (
                "错误：本轮只收集缺失信息，不修改简历。"
                "请调用 ask_user_question 逐项问清缺口，然后结束本轮。"
            )
        return await super().execute_tool(command)

    async def execute_pi_core_tool(self, call: Any) -> str:
        """Execute a provider-neutral Pi Core call outside the scheduler."""

        from backend.agent.pi_core.types import ToolCall as CoreToolCall

        if not isinstance(call, CoreToolCall):
            raise TypeError("execute_pi_core_tool expects a pi-core ToolCall")

        return await execute_resume_tool_native(
            self.available_tools,
            call,
            session_id=self.session_id,
            user_id=self.user_id,
            store_structured=self._store_structured_tool_result,
            mark_pending_approval=self._mark_pi_core_pending_approval,
        )

    def _mark_pi_core_pending_approval(self) -> None:
        """Mark the compatibility state for the native approval boundary."""

        self._tool_batch_control.pending_approval = True

    def get_tool_block_reason(self, tool_name: str) -> Optional[str]:
        """Expose turn policy without leaking the private turn object."""

        return blocked_tool_reason(self._turn, tool_name)

    def get_turn_policy(self) -> TurnPolicySnapshot:
        """Return an immutable public snapshot for the current turn."""

        return TurnPolicySnapshot.from_turn(self._turn)

    def queue_resume_patch(self, patch: Dict[str, Any]) -> None:
        """暂存 resume_patch，由 AgentStream 在 step 结束后 emit。"""
        self._turn.queue_patch(patch)

    def drain_resume_patches(self) -> List[Dict[str, Any]]:
        """取出并清空待发送的 resume_patch 列表。"""
        return self._turn.drain_patches()

    @staticmethod
    def _is_injected_system_user_message(content: str) -> bool:
        """识别以 user 角色注入的系统指令（非真实用户输入）。"""
        text = (content or "").strip()
        if not text:
            return True
        # 仅匹配明确的系统注入格式，避免误伤长段实习/项目粘贴
        if text.startswith("## ") and "用户输入" in text[:200]:
            return True
        injected_markers = (
            "根据用户输入，请选择",
            "意图识别结果",
            "工具选择规则",
            "**重要：本轮",
        )
        return any(marker in text[:300] for marker in injected_markers)

    def _get_last_user_message_idx(self) -> int:
        """返回最后一条真实用户消息在 memory 中的下标，不存在则 -1。"""
        for idx in range(len(self.memory.messages) - 1, -1, -1):
            msg = self.memory.messages[idx]
            role_val = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            if role_val != "user" or not msg.content:
                continue
            content = msg.content.strip()
            if not self._is_injected_system_user_message(content):
                return idx
        return -1

    def _get_last_user_input(self) -> str:
        """获取最后一条真正的用户输入（过滤系统提示词，保留长文本粘贴）。"""
        idx = self._get_last_user_message_idx()
        if idx < 0:
            return ""
        return (self.memory.messages[idx].content or "").strip()

    def _sync_turn_read_only_flag(self, user_input: str) -> None:
        """同一用户轮次内只计算一次只读标志，避免多步 think 反复重算。"""
        last_user_idx = self._get_last_user_message_idx()
        locked_idx = getattr(self, "_read_only_locked_user_idx", -2)
        if last_user_idx == locked_idx:
            return

        self._read_only_locked_user_idx = last_user_idx
        if is_add_experience_query(user_input):
            self._turn.read_only = False
        else:
            self._turn.read_only = is_read_only_query(user_input)
        route = classify_resume_request(user_input)
        # Phase 3 写入解锁：显式 apply 文案（"按建议帮我修改"等）+ 当前简历
        # 确实已产出诊断，两者同时成立才解除只读诊断闸；否则（含首轮泛优化、
        # 未诊断就说 apply 话术）仍先走只读诊断，防止跳过诊断直接改。
        completed = self._diagnosis_completed_for_loaded_resume()
        single_n = is_diagnosis_apply_single_query(user_input)
        # pending 接力：上一轮弹了缺口选择框，本轮用户提交答案（前端 handleAskQuestionSubmit
        # 固定前缀"我确认这些信息"）。非确认消息到来即丢弃 pending，不粘住后续对话。
        pending = (
            self._shared_state.get("diagnosis_apply_pending")
            if self._shared_state is not None
            else None
        )
        resume_from_pending = (
            isinstance(pending, dict) and "我确认这些信息" in (user_input or "")
        )
        if (
            isinstance(pending, dict)
            and not resume_from_pending
            and self._shared_state is not None
        ):
            self._shared_state.set("diagnosis_apply_pending", None)
            pending = None

        # 单条 apply（建议卡「帮我改这条」）> pending 恢复 > 一键 apply（前置查缺口）
        facts_n = is_suggestion_facts_query(user_input)
        is_apply_turn = False
        is_gap_turn = False
        if completed and facts_n is not None:
            # P2(2026-07-19):needs_fact 条「补充信息并修改」→ 单条缺口收集轮。
            # asking 关闭或该条并非 needs_fact 时,降级为单条 apply
            # (needs_fact 会命中 SINGLE_APPLY_NEEDS_FACT_PROMPT 的清晰话术)。
            item = self._suggestion_by_index(facts_n)
            if (
                item is not None
                and item.get("status") == "needs_fact"
                and is_asking_mode_enabled()
            ):
                is_gap_turn = True
                if self._shared_state is not None:
                    self._shared_state.set(
                        "diagnosis_apply_pending",
                        {"mode": "single", "index": facts_n},
                    )
            elif item is not None:
                is_apply_turn = True
                self._turn.diagnosis_apply_single = facts_n
        elif completed and single_n:
            is_apply_turn = True
            self._turn.diagnosis_apply_single = single_n
        elif completed and resume_from_pending:
            is_apply_turn = True
            self._turn.diagnosis_apply_single = pending.get("index")
            if self._shared_state is not None:
                self._shared_state.set("diagnosis_apply_pending", None)
        elif completed and is_diagnosis_apply_query(user_input):
            gap_items = self._needs_fact_suggestions()
            if gap_items and is_asking_mode_enabled():
                # 有缺口且 Asking 开：先弹选择框收集，写 pending 等答复接力
                is_gap_turn = True
                if self._shared_state is not None:
                    self._shared_state.set(
                        "diagnosis_apply_pending", {"mode": "all"}
                    )
            else:
                is_apply_turn = True
        # apply 轮 = 单轮出齐修改（由 prompt + ask 拦截保证）；gap 轮 = 先收集缺口再改
        self._turn.diagnosis_apply = is_apply_turn
        self._turn.diagnosis_gap_collect = is_gap_turn
        # 查看建议轮（2026-07-16 诊断/建议拆分）：点「查看修改建议」只读展示
        # 建议（cv_suggestions_agent），不重新诊断、不修改简历。
        is_view_turn = bool(
            not is_apply_turn
            and not is_gap_turn
            and is_view_suggestions_query(user_input)
            and completed
        )
        self._turn.view_suggestions = is_view_turn
        self._turn.diagnosis_only = bool(
            route in {
                ResumeRequestRoute.BROAD_OPTIMIZE,
                ResumeRequestRoute.DIAGNOSE,
            }
            and not is_apply_turn
            and not is_gap_turn
            and not is_view_turn
        )

        if self._turn.read_only:
            logger.info("📖 只读查看轮次：禁止 cv_editor_agent")
        elif self._turn.diagnosis_gap_collect:
            logger.info("📋 缺口收集轮次：先弹选择框问齐 needs_fact，再按建议改")
        elif self._turn.view_suggestions:
            logger.info("💡 查看建议轮次：只展示建议，禁止编辑与重新诊断")
        elif self._turn.diagnosis_only:
            logger.info("🩺 只读诊断轮次：禁止编辑、patch、Asking 和自动优化")
        elif is_add_experience_query(user_input):
            logger.info("📎 新增经历轮次：允许 cv_editor_agent")

    async def _generate_dynamic_prompts(self, user_input: str, intent: "Intent" = None) -> tuple:
        """动态 prompt 构造已迁 PromptBuilder(Wave 2a-S2),此处保留薄委托。"""
        system_prompt, next_step_prompt = await self._prompt_builder.generate(
            user_input,
            intent,
            resume_loaded=self._conversation_state.context.resume_loaded,
            current_resume_path=self._current_resume_path,
            recent_messages=self.memory.messages,
        )
        if not is_asking_mode_enabled():
            system_prompt = f"{system_prompt}\n\n{ASKING_MODE_DISABLED_PROMPT}"
        if self._turn.diagnosis_apply_single is not None:
            item = self._suggestion_by_index(self._turn.diagnosis_apply_single)
            if item is not None:
                system_prompt = f"{system_prompt}\n\n{self._build_single_apply_prompt(item)}"
            else:
                # 越界/无结构化建议 → 降级为整体 apply
                system_prompt = f"{system_prompt}\n\n{DIAGNOSIS_APPLY_PROMPT}"
        elif self._turn.diagnosis_apply:
            suggestions = self._guidance_suggestions()
            if suggestions:
                block = self._format_suggestions_block(suggestions)
                system_prompt = f"{system_prompt}\n\n{DIAGNOSIS_APPLY_PROMPT_V3.format(suggestions_block=block)}"
            else:
                # 用户没点过「查看建议」，assessment 无结构化建议 → 回退读诊断报告
                system_prompt = f"{system_prompt}\n\n{DIAGNOSIS_APPLY_PROMPT}"
        elif self._turn.diagnosis_gap_collect:
            # P2:pending mode=single 时只问该条的缺口;否则问全部 needs_fact
            pending = (
                self._shared_state.get("diagnosis_apply_pending")
                if self._shared_state is not None
                else None
            )
            if isinstance(pending, dict) and pending.get("mode") == "single":
                single_item = self._suggestion_by_index(pending.get("index"))
                gap_items = [single_item] if single_item else self._needs_fact_suggestions()
            else:
                gap_items = self._needs_fact_suggestions()
            block = self._format_gap_block(gap_items)
            system_prompt = f"{system_prompt}\n\n{GAP_COLLECT_PROMPT.format(gap_block=block)}"
        if self._turn.view_suggestions:
            system_prompt = f"{system_prompt}\n\n{VIEW_SUGGESTIONS_PROMPT}"
        return system_prompt, next_step_prompt

    async def prepare_pi_core_turn(self, user_input: str) -> None:
        """Prepare routing, policy and prompt state for one Pi Core turn."""

        self._sync_turn_read_only_flag(user_input)
        self._sync_resume_loaded_state()
        self._ensure_conversation_state_llm()
        route = await self._intent_router.decide(
            user_input,
            RoutingContext(
                recent_messages=self.memory.messages[-5:],
                last_ai_message=self._get_last_ai_message(),
            ),
        )
        self._last_intent = route.intent
        self._store_intent_info(route.intent, route.intent_source)
        if route.compound_hint:
            self.memory.add_message(
                Message.system_message(
                    "用户这条请求包含多个子任务，请逐个完成全部子任务，"
                    "全部完成后再结束。"
                )
            )
        self._maybe_init_optimize_progress(user_input)
        self.system_prompt, self.next_step_prompt = await self._generate_dynamic_prompts(
            user_input, route.intent
        )
        self.system_prompt = apply_visible_action_narration_guidance(
            self.system_prompt
        )

    def should_auto_terminate(self, content: str, tool_calls: list) -> bool:
        """自定义自动终止逻辑

        Manus 的终止策略：
        1. 如果有工具调用，不终止
        2. 如果有 next_step_prompt，不终止（需要继续生成）
        3. 如果 LLM 返回了有意义的内容（问答场景），自动终止
        4. 如果内容是系统指令的重复，不终止（可能是错误状态）
        """
        if tool_calls:
            return False

        # 🔧 修复：如果有 next_step_prompt，说明需要继续生成，不终止
        if self.next_step_prompt and self.next_step_prompt.strip():
            logger.info(f"🔄 有 next_step_prompt，继续生成流式内容（不终止）")
            # 清空 next_step_prompt，避免无限循环
            self.next_step_prompt = ""
            return False

        if not content or not content.strip():
            return False

        # 检查是否是有意义的回答（不是系统指令的重复）
        system_phrases = [
            "好的，我明白了",
            "我会直接回答",
            "如果需要使用工具",
        ]

        # 如果回答太短且包含系统短语，可能是错误状态
        for phrase in system_phrases:
            if phrase in content and len(content) < 100:
                logger.debug(f"⚠️ 检测到可能的系统短语重复，跳过自动终止")
                return False

        # 有实质性内容，自动终止
        return True

    def _apply_enhanced_query(self, enhanced_query: str, user_input: str) -> None:
        """查询被增强（含工具标记）时，更新最后一条用户消息为增强查询。"""
        if enhanced_query != user_input and self.memory.messages:
            # 找到最后一条用户消息并更新
            for i in range(len(self.memory.messages) - 1, -1, -1):
                msg = self.memory.messages[i]
                if msg.role == Role.USER:
                    # 更新消息内容为增强后的查询
                    msg.content = enhanced_query
                    logger.debug(f"已更新用户消息为增强查询: {enhanced_query}")
                    break

    def _store_intent_info(self, intent: Intent, intent_source: str) -> None:
        """存储本轮意图上下文，供工具结构化结果标注来源。"""
        self._last_intent_info = {
            "intent": intent.value if hasattr(intent, "value") else str(intent),
            "intent_source": intent_source,
            "trigger": (
                "load_resume_intent"
                if intent == Intent.LOAD_RESUME
                else "simple_edit_intent"
                if intent == Intent.EDIT_CV
                else "general_intent"
            ),
        }

    def _get_last_ai_message(self) -> Optional[str]:
        """获取最后一条 AI 消息内容"""
        for msg in reversed(self.memory.messages[-3:]):
            if msg.role == Role.ASSISTANT and msg.content:
                return msg.content[:500]
        return None

    def _has_resume_data_in_store(self) -> bool:
        """检查当前会话是否已有可用简历数据。"""
        resume_data = ResumeDataStore.get_data(self.session_id)
        return isinstance(resume_data, dict) and len(resume_data) > 0

    def _sync_resume_loaded_state(self) -> None:
        """
        根据 ResumeDataStore 同步 resume_loaded。

        某些轮次前端已传入 resume_data，但状态机仍为 resume_loaded=False，
        会误触发“请先加载简历”。这里以数据存在性作为兜底真值源。
        """
        if self._conversation_state.context.resume_loaded:
            return
        if not self._has_resume_data_in_store():
            return
        self._conversation_state.update_resume_loaded(True)
        logger.info("📋 resume_loaded state synced from ResumeDataStore")

    def _maybe_init_optimize_progress(self, user_input: str) -> None:
        """整份优化任务初始化：本轮确实是整份优化相关时，确保
        `_progress_by_session` 就绪，供本轮 prompt 渲染进度清单/增量注入。

        必须在生成动态 prompt 之前调用。init_progress 本身幂等（有未完成任务
        直接复用，不重置）。

        **独立 review 发现并修复的真实 bug**：最初版本用"该会话已有未完成
        任务"（has_active_task）单独作为触发条件，导致任务 alive
        （status!=done）期间，用户中途随便发一条无关消息（不调工具、不是
        续跑）也会被当成"这轮继续整份优化"处理——被迫套上增量注入裁剪、
        强制 PII 脱敏，还会被 `_advance_optimize_progress` 的信号 3 误判成
        "这轮判断不需要改"而错误 skip 掉一个模块。改成：本轮必须满足"用户
        主动措辞命中 is_full_optimize_query" 或 "是系统合成的续跑消息"
        （`is_optimize_continuation_message`，见 optimize_progress.py）
        之一，任务状态才在本轮生效；否则这一轮当普通对话处理，
        `_progress_by_session` 保持原状不变（不清空、不推进），下一轮用户
        重新明确提及"继续优化"依然能恢复。见设计方案七点二、七点六。
        """
        if not self._has_resume_data_in_store():
            return
        # apply 形态 v2（2026-07-15 用户拍板）：诊断后的显式 apply 走"单轮
        # 出齐全部 patch"（见 diagnosis_apply 轮约束），不再初始化逐模块
        # 优化任务——原 is_diagnosis_apply_query 触发分支移除。逐模块任务
        # 因此失去新的启动入口（有意为之）；continuation 分支保留，兼容
        # 既有进行中任务的 auto_continue 续跑恢复。
        if not is_optimize_continuation_message(user_input):
            return
        resume_data = ResumeDataStore.get_data(self.session_id)
        if resume_data:
            ResumeDataStore.init_progress(self.session_id, resume_data)

    def _diagnosis_completed_for_loaded_resume(self) -> bool:
        """当前会话已加载的简历是否已产出过诊断（cv_analyzer 完成时打标）。

        与 `_sync_turn_read_only_flag` / `_maybe_init_optimize_progress` 共用，
        是 Phase 3「诊断后显式 apply 才可写」闸门的会话状态半边。
        """
        resume_data = ResumeDataStore.get_data(self.session_id)
        if not isinstance(resume_data, dict):
            return False
        meta = resume_data.get("_meta") or {}
        resume_id = str(
            resume_data.get("resume_id")
            or resume_data.get("id")
            or (meta.get("resume_id") if isinstance(meta, dict) else "")
            or ""
        )
        diagnosed_for = (
            self._shared_state.get("resume_diagnosis_completed_for", "")
            if self._shared_state is not None
            else ""
        )
        return bool(resume_id) and diagnosed_for == resume_id

    def _guidance_suggestions(self) -> List[Dict[str, Any]]:
        """从 shared_state 诊断评估里取结构化建议列表（cv_suggestions_agent 写入；无则空）。"""
        if self._shared_state is None:
            return []
        assessment = self._shared_state.get("resume_guidance_assessment")
        if not isinstance(assessment, dict):
            return []
        suggestions = (assessment.get("details") or {}).get("suggestions") or []
        return [s for s in suggestions if isinstance(s, dict)]

    def _needs_fact_suggestions(self) -> List[Dict[str, Any]]:
        """建议里 status=needs_fact（缺只有用户知道的真实信息）的条目。"""
        return [s for s in self._guidance_suggestions() if s.get("status") == "needs_fact"]

    def _suggestion_by_index(self, n: Optional[int]) -> Optional[Dict[str, Any]]:
        """按 1-based 序号取单条建议（越界返回 None）。"""
        if not n:
            return None
        suggestions = self._guidance_suggestions()
        if 1 <= n <= len(suggestions):
            return suggestions[n - 1]
        return None

    @staticmethod
    def _format_suggestions_block(suggestions: List[Dict[str, Any]]) -> str:
        """建议列表 → 注入 apply prompt 的编号清单（needs_fact 标注需补充，proposed 附参考改写）。"""
        lines: List[str] = []
        for i, s in enumerate(suggestions, 1):
            section = s.get("section") or ""
            title = s.get("title") or ""
            if s.get("status") == "needs_fact":
                facts = "、".join(s.get("requires_facts") or [])
                lines.append(f"{i}. [{section}] {title} — 需补充：{facts}")
            else:
                rec = s.get("recommendation") or ""
                proposed = s.get("proposed") or ""
                tail = f"（参考改写：{proposed}）" if proposed else ""
                lines.append(f"{i}. [{section}] {title} — {rec}{tail}")
        return "\n".join(lines)

    @staticmethod
    def _format_gap_block(needs_fact_items: List[Dict[str, Any]]) -> str:
        """needs_fact 建议 → 缺口收集 prompt 的清单。"""
        lines: List[str] = []
        for s in needs_fact_items:
            section = s.get("section") or ""
            facts = "、".join(s.get("requires_facts") or [])
            lines.append(f"- [{section}] {s.get('title', '')}：需要 {facts}")
        return "\n".join(lines)

    @staticmethod
    def _build_single_apply_prompt(item: Dict[str, Any]) -> str:
        """单条 apply 的 prompt：proposed 条直接改；needs_fact 条不能改也不假装提问，
        只说明缺什么让用户补充（消除"承诺提问却不问"的断层）。"""
        block = ResumeDomainRuntime._format_suggestions_block([item])
        if item.get("status") == "needs_fact":
            return SINGLE_APPLY_NEEDS_FACT_PROMPT.format(item_block=block)
        return SINGLE_APPLY_PROMPT.format(item_block=block)

    def _advance_optimize_progress(self) -> None:
        """整份优化任务：推进进度。

        **实测发现（真实 LLM 端到端验证，qwen-max）**：单靠 LLM 输出
        `[[MODULE_DONE:模块]]` 这个自定义协议标记不可靠——指令已经完整、清晰
        地注入 system prompt，LLM 依然经常不遵循，倾向于走"跟用户对话式推进"
        （比如停下来问用户要不要提供更多信息）而不是按格式协议输出标记。不能
        把这个标记当成推进进度的唯一驱动力，否则 pending 永远不清空，
        reviewing 相变永远不触发，整套任务内进度追踪形同虚设。

        三层信号，优先级从高到低，任一命中就推进：
        1. 显式标记 `[[MODULE_DONE:xxx]]`——LLM 确实输出了就优先采信（可能
           比单看 path 更精确，比如一步改了多个字段但只想推进其中一个模块）。
        2. **真实工具调用推断（主力）**：本步有 `cv_editor_agent` 调用且真的
           执行成功，其 `path` 参数解析出的顶层模块命中 `pending`，视为该
           模块已处理，自动推进——不依赖 LLM 主动"声明"，直接从它真实做了
           什么反推状态，这是本仓库一贯的判据（规则该管确定性边界，不该
           指望 LLM 遵守自定义协议）。**这一信号的判定放在 act() 之后**，
           见 `_confirm_optimize_progress_from_results`，本函数不处理。
        3. **无工具调用兜底**：本步纯文本回复、没有调用任何工具（即将
           触发 `should_auto_terminate` 结束这轮），说明 LLM 这轮没打算动
           `pending[0]`——自动把它标记为 skip 推进，避免任务卡死在同一个
           模块；下一轮 auto_continue 会把清单重新给 LLM 看，它仍有机会
           在后续轮次改这个模块（skip 不等于永久跳过，只是不卡在这一步）。

        在 think() 里、super().think() 添加完 assistant 消息之后立即调用
        （不新开一轮 LLM 调用）。信号 3 必须放在 think() 里——
        tool execution runtime.think() 在纯文本无 tool_calls 且命中 should_auto_terminate
        时会直接 state=FINISHED 并 return False，此时 react.py 的 step() 根本
        不会调用 act()，信号 3 的兜底就永远不会被检测到；think() 里紧跟
        super().think() 之后调用则不受这个分支影响。只看最新一条 assistant
        消息（不用往回扫），避免误触发更早、其实已经处理过的旧标记。
        mark_module_done 幂等（重复/未知模块 no-op），相变 optimizing→reviewing
        由其内部规则 len(pending)==0 触发，零 LLM 步数。见设计方案七点二。

        **独立 review 发现并修复的真实 bug（只影响信号 3，不影响信号 1/2）**：
        本函数原来只检查 `status == "optimizing"` 就会跑三层信号，任务 alive
        期间只要用户某一轮没调用任何工具（哪怕是完全无关的闲聊），信号 3
        兜底都会把 `pending[0]` 误判成"这轮判断不需要改"而错误 skip
        掉——把"用户在聊别的"伪装成"任务在正常推进"。修法：信号 3 额外要求
        本轮确实是整份优化相关（用户主动措辞或系统续跑消息）才触发；信号
        1/2 不需要这层保护——它们本身就有实际证据支撑（LLM 真输出了标记 /
        真调用了工具改了字段），不该因为"这轮判断跟整份优化无关"就被
        一并拦住（比如用户中途简短回一句"继续"，没有命中任何措辞正则，
        但 LLM 确实照常调用了 cv_editor_agent 处理了下一个模块——这种真实
        发生的推进不该被拦下）。

        **独立 review round5 发现并修复的真实 bug（信号 2 假阳性完成）**：
        信号 2 原来跟信号 1/3 一起放在 think() 里，只看 `self.tool_calls`
        ——那只是 LLM 这一步"决定调用"，此时 act() 还没跑，编辑到底成没成
        根本不知道。工具真实执行时可能失败（cv_editor_agent 内部报错/校验
        不通过）或被 `execute_tool` 的只读轮次拦截直接短路（见本类
        `execute_tool` override），这些情况下模块已经被判定 done，
        mark_module_done 幂等导致后续重试也不会再推进——一次没真正生效的
        编辑被永久标记成"已完成"。修法：信号 2 挪到 act() 之后，凭工具真实
        返回的结果确认成功了才推进，见 `_confirm_optimize_progress_from_results`。
        """
        progress = ResumeDataStore.get_progress(self.session_id)
        if not progress or progress.get("status") != "optimizing":
            return

        last_assistant_content = None
        for msg in reversed(self.memory.messages[-3:]):
            role_val = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            if role_val == "assistant":
                last_assistant_content = msg.content
                break

        advanced = False

        # 信号 1：显式标记。注意:只要解析到标记(即便模块已 done、mark 幂等
        # no-op)就视为本轮有明确进度信号,阻断信号 3——否则 LLM 重复输出
        # [[MODULE_DONE:basic]] 时(它对进度无知,风暴/重发场景实测),幂等
        # no-op 导致 advanced=False,信号 3 把 pending[0](education 等)错误
        # skip 掉,LLM 说 basic、进度却跳过 education 的错乱(2026-07-13 日志)。
        if last_assistant_content:
            for module, skip in parse_module_done_markers(last_assistant_content):
                advanced = True
                ResumeDataStore.mark_module_done(self.session_id, module, skip=skip)

        # 信号 3：无工具调用兜底（本轮啥也没干，避免卡死在同一模块）。
        # 这层没有实际证据（没标记也没工具调用），必须额外确认本轮确实
        # 跟整份优化相关，否则会把"用户在聊别的"误判成"这轮决定跳过"。
        #
        # **独立 review 发现并修复的真实 bug（用户实测截图复现）**：LLM
        # 针对当前模块向用户提了个澄清问题（比如"在校期间有获得过奖学金
        # 吗？GPA 或专业排名情况如何？"），明确说了"你可以直接说'没有，
        # 跳过'或者'有，[具体信息]'"——这一步没调用工具，命中信号 3 的
        # "无工具调用"条件，本函数直接把这个模块判定成"跳过"往下推进，
        # auto_continue 又紧接着把下一个模块的处理结果糊了上来——用户
        # 压根没来得及回答，进度已经跳过这个模块走了，问题白问。信号 3
        # 的"没调用工具=这轮决定跳过"这个假设，只对"LLM主动判断不需要
        # 改"成立，对"LLM在等用户回答一个真问题"不成立，两者不能同等
        # 处理。用一个粗但够用的启发式区分：本轮回复里出现问号，就当成
        # "在等用户答复"，不触发自动跳过，让本轮正常结束、真等用户回复
        # （而不是被 auto_continue 悄悄带着往下走）。
        if not advanced and not self.tool_calls:
            is_asking_question = bool(
                last_assistant_content and re.search(r"[?？]", last_assistant_content)
            )
            if not is_asking_question:
                last_user_input = self._get_last_user_input()
                is_relevant_turn = is_full_optimize_query(
                    last_user_input
                ) or is_optimize_continuation_message(last_user_input)
                if is_relevant_turn:
                    pending = progress.get("pending") or []
                    if pending:
                        ResumeDataStore.mark_module_done(
                            self.session_id, pending[0], skip=True
                        )

    def _confirm_optimize_progress_from_results(self) -> None:
        """信号 2：act() 真实执行完 cv_editor_agent 后，凭工具返回结果确认
        编辑是否真的成功，成功才推进对应模块——不能只凭 think() 阶段
        "LLM 决定调用"就判定完成，见 `_advance_optimize_progress` 的
        round5 bug 说明。必须在 `super().act()` 之后调用，此时对应的
        ToolMessage 已经写进 `self.memory`。
        """
        progress = ResumeDataStore.get_progress(self.session_id)
        if not progress or progress.get("status") != "optimizing":
            return
        if not self.tool_calls:
            return
        target_calls = {
            call.id: call
            for call in self.tool_calls
            if getattr(call.function, "name", None) == "cv_editor_agent"
        }
        if not target_calls:
            return
        for msg in self.memory.messages[-len(self.tool_calls):]:
            if msg.role != Role.TOOL or msg.tool_call_id not in target_calls:
                continue
            content = msg.content or ""
            if any(marker in content for marker in _CV_EDITOR_FAILURE_MARKERS):
                continue
            call = target_calls[msg.tool_call_id]
            try:
                args = json.loads(call.function.arguments or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            module = resolve_module_from_path(args.get("path", ""))
            if module:
                ResumeDataStore.mark_module_done(self.session_id, module, skip=False)



