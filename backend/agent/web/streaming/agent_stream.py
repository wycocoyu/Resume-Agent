"""Agent stream output handler.

Handles streaming agent execution results to SSE clients.
当前主链仍基于 StreamEvent -> SSE 输出；
CLTP 相关能力作为过渡兼容资产逐步收敛。
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Dict, Optional, Tuple, List, Set
from datetime import datetime

import openai
from tenacity import RetryError


def unwrap_retry_error(exc: BaseException) -> BaseException:
    """tenacity RetryError 只是重试耗尽的包装，真实原因在 last_attempt 里。"""
    if isinstance(exc, RetryError):
        try:
            inner = exc.last_attempt.exception()
        except Exception:
            inner = None
        if inner is not None:
            return inner
    return exc


def user_facing_error_message(exc: BaseException) -> Tuple[str, str]:
    """把执行异常映射为用户可读文案 + 真实异常类型名。

    背景（2026-07-16）：上游 LLM 网关 502 触发 tenacity 重试耗尽后，
    `str(RetryError)` 的内部 repr（"RetryError[<Future at 0x... raised
    InternalServerError>]"）被原样塞进 AgentErrorEvent.error_message，
    前端（useCLTP）直接展示给了用户。用户永远不该看到内部异常 repr；
    完整技术细节保留在 logger.exception 的日志里。
    """
    cause = unwrap_retry_error(exc)
    if isinstance(cause, openai.APIError):
        # 上游模型服务异常（502/超时/限流/凭据失效等），对用户统一为服务波动
        return (
            "AI 服务暂时不可用（上游接口异常），请稍等片刻再试一次。",
            type(cause).__name__,
        )
    if isinstance(cause, (asyncio.TimeoutError, ConnectionError, OSError)):
        return (
            "网络连接不稳定，这一步没有完成，请稍后重试。",
            type(cause).__name__,
        )
    return (
        "刚才这一步运行出了点问题，请稍后重试。",
        type(cause).__name__,
    )


def parse_thought_response(content: str) -> Tuple[Optional[str], Optional[str]]:
    """
    解析 LLM 输出中的 Thought 和 Response 部分

    Deprecated: CLTP 已提供标准的 think/plain content chunks，
    后续在完成前端迁移后移除此函数与相关调用。
    TODO(cltp): 前端完全迁移后删除 parse_thought_response

    Returns:
        (thought, response) - 如果没有找到对应部分则为 None
    """
    # #region debug log (已禁用硬编码路径)
    import json
    # 使用 logger 代替硬编码路径，避免在不同系统上出错
    try:
        logger.debug(f"[DEBUG] parse_thought_response called: content_length={len(content) if content else 0}")
    except Exception:
        pass
    # #endregion

    thought = None
    response = None

    if not content or not content.strip():
        """
        # debug log (已禁用)
        with open('/Users/wy770/AI/.cursor/debug.log', 'a') as f:
            f.write(json.dumps({
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "C",
                "location": "agent_stream.py:parse_thought_response:EMPTY",
                "message": "content is empty or whitespace",
                "data": {"content": content},
                "timestamp": int(__import__('time').time() * 1000)
            }) + '\n')
        """
        return None, None

    # 使用更严谨的正则表达式匹配 Thought: 和 Response:
    # 考虑可能存在的换行和空格，支持多种格式变体
    # 匹配模式：
    # 1. Thought: ... Response: ...
    # 2. **Thought:** ... **Response:** ...
    # 3. Thought: ... (没有 Response)
    # 4. 思考：... 回复：... (中文格式)

    # 尝试多种匹配模式
    patterns = [
        # 标准格式：Thought: ... Response: ...（支持同一行或换行）
        (
            r'(?:^|\n)\s*(?:Thought|思考)[:：]\s*(.*?)(?=\s*(?:Response|回复|Answer|Final\s*Answer|最终回复)[:：]|$)',
            r'(?:^|\n|\s)(?:Response|回复|Answer|Final\s*Answer|最终回复)[:：]\s*(.*)',
        ),
        # 加粗格式：**Thought:** ... **Response:** ...
        (r'(?:^|\n)\s*\*\*Thought\*\*[:：]\s*(.*?)(?=\n\s*\*\*Response\*\*[:：]|$)',
         r'(?:^|\n)\s*\*\*Response\*\*[:：]\s*(.*)'),
        # 1. Thought: ... 2. Response: ... (带编号)
        (r'(?:^|\n)\s*1\.\s*(?:Thought|思考)[:：]\s*(.*?)(?=\n\s*2\.\s*(?:Response|回复)[:：]|$)',
         r'(?:^|\n)\s*2\.\s*(?:Response|回复)[:：]\s*(.*)'),
    ]

    for idx, (thought_pattern, response_pattern) in enumerate(patterns):
        thought_match = re.search(thought_pattern, content, re.DOTALL | re.IGNORECASE | re.MULTILINE)
        response_match = re.search(response_pattern, content, re.DOTALL | re.IGNORECASE | re.MULTILINE)

        if thought_match:
            thought = thought_match.group(1).strip()
        if response_match:
            response = response_match.group(1).strip()

        """
        # debug log (已禁用)
        if thought_match or response_match:
            with open('/Users/wy770/AI/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "B",
                    "location": f"agent_stream.py:parse_thought_response:PATTERN_{idx}",
                    "message": "pattern matched",
                    "data": {
                        "pattern_idx": idx,
                        "thought_matched": thought_match is not None,
                        "response_matched": response_match is not None,
                        "thought_preview": thought[:100] if thought else None,
                        "response_preview": response[:100] if response else None
                    },
                    "timestamp": int(__import__('time').time() * 1000)
                }) + '\n')
        """

        if thought or response:
            break

    # 启发式修复：
    # 一些模型只输出 "Thought: xxx\n<actual answer>"，不带 "Response:" 标签。
    # 这种情况下把第一行视作 thought，其余正文视作 response，
    # 避免最终 plain 内容里残留 "Thought:" 前缀。
    if thought and not response:
        thought_prefix = re.match(
            r"^\s*(?:\*\*)?(?:Thought|思考)(?:\*\*)?\s*[:：]\s*",
            content,
            re.IGNORECASE,
        )
        if thought_prefix:
            remaining = content[thought_prefix.end() :].strip()
            # 优先按空行拆分，否则按首个换行拆分
            parts = re.split(r"\n{2,}|\n", remaining, maxsplit=1)
            if len(parts) == 2:
                first_line = parts[0].strip()
                body = parts[1].strip()
                if first_line and body:
                    thought = first_line
                    response = body
            elif remaining:
                # 至少移除前缀，避免在 plain 中出现 "Thought:"
                thought = parts[0].strip()
                response = None

    # 如果找到了 Thought 但没找到 Response（还在生成中），或者找到了 Response
    if thought or response:
        """
        # debug log (已禁用)
        with open('/Users/wy770/AI/.cursor/debug.log', 'a') as f:
            f.write(json.dumps({
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "B",
                "location": "agent_stream.py:parse_thought_response:SUCCESS",
                "message": "parse_thought_response success",
                "data": {
                    "thought_found": thought is not None,
                    "response_found": response is not None,
                    "thought_length": len(thought) if thought else 0,
                    "response_length": len(response) if response else 0
                },
                "timestamp": int(__import__('time').time() * 1000)
            }) + '\n')
        """
        return thought, response

    # 如果都没有找到格式化的输出，返回原始内容作为 response
    # #region debug log (已禁用硬编码路径)
    # with open('/Users/wy770/AI/.cursor/debug.log', 'a') as f:
    #     f.write(json.dumps({
    #         "sessionId": "debug-session",
    #         "runId": "run1",
    #         "hypothesisId": "A",
    #         "location": "agent_stream.py:parse_thought_response:NO_MATCH",
    #         "message": "no pattern matched, returning original content as response",
    #         "data": {
    #             "content_preview": content[:200],
    #             "content_contains_thought": "Thought:" in content or "思考:" in content or "**Thought**" in content,
    #             "content_contains_response": "Response:" in content or "回复:" in content or "**Response**" in content
    #         },
    #         "timestamp": int(__import__('time').time() * 1000)
    #     }) + '\n')
    # #endregion
    return None, content

from backend.agent.agent.manus import Manus
from backend.agent.application.public_reasoning import PublicReasoning
from backend.agent.schema import AgentState as SchemaAgentState, Message, Role, ToolCall
from backend.agent.web.streaming.events import (
    EventType,
    StreamEvent,
    ThoughtEvent,
    ToolCallEvent,
    ToolResultEvent,
    ToolProgressEvent,
    ResumeUpdatedEvent,
    AnswerEvent,
    AgentStartEvent,
    AgentEndEvent,
    AgentErrorEvent,
    SystemEvent,
    SuggestionsEvent,
    AutoContinueEvent,
    AnswerResetEvent,
)
from backend.agent.web.streaming.agent_state import AgentState, StateInfo
from backend.agent.web.streaming.state_machine import AgentStateMachine
from backend.agent.web.streaming.delta_filter import filter_streaming_markers
from backend.agent.tool.resume_data_store import ResumeDataStore
from backend.agent.utils.optimize_progress import (
    AUTO_CONTINUE_PREFIX,
    MODULE_LABEL,
    strip_module_done_markers,
    verify_facts_coverage,
)
from backend.agent.feature_flags import is_pi_core_enabled

logger = logging.getLogger(__name__)


EventSender = Callable[[dict[str, Any]], asyncio.Task]

# 分析结果标记
ANALYSIS_RESULT_MARKERS = [
    "📊 分析结果摘要",
    "💡 优化建议",
    "🎯 我最推荐的优化",
    "是否要应用这个优化",
    "是否要优化",
    "是否要优化这段教育经历",
    "综合评分"
]


def merge_visible_piece(parts: list, piece: str) -> None:
    """把一步的可见正文并入本轮拼接列表,带与前端 useCLTP.appendChunk 对齐的
    前缀/包含去重(Codex review P1:complete 是整体替换语义,流式侧 appendChunk
    会合并"第二步重述第一步"的文本,后端无脑 join 会让 complete 出现重复段)。

    规则(对齐 appendChunk Case 1/2/3,重叠合并 Case 4 不做——旁白场景的重复
    形态是整段重述,不是 token 级重叠):
    - piece 与已有某段完全相同 → 丢弃
    - piece 以最后一段为前缀开头(累积式重述) → 用 piece 替换最后一段
    - piece 被最后一段包含 → 丢弃
    """
    if not piece:
        return
    if parts:
        last = parts[-1]
        if piece == last:
            return
        if piece.startswith(last):
            parts[-1] = piece
            return
        if piece in last:
            return
    if piece in parts:
        return
    parts.append(piece)


def is_tool_error_content(content: str | None) -> bool:
    """工具层用 ``Error:`` 作为失败契约，SSE 据此发 tool_error。"""
    return bool(content and content.lstrip().startswith("Error:"))


def split_turn_messages(messages) -> tuple[list[str], list[str]]:
    """B层结构路由:按「这条 assistant 消息带不带 tool_calls」把本轮消息
    分成旁白(narrations)与正文(answer_parts)。

    - 带 tool_calls = ReAct 中间步,content 是"我接下来要做什么"的旁白
      → 进思考折叠框,不进正文
    - 不带 tool_calls = 收尾步,content 是给用户的正文
    路由完全基于消息结构,不依赖 Thought:/Response: 文本协议(该协议
    只在这里作为老会话历史数据的兼容清洗保留,不参与路由判定)。
    """
    narrations: list[str] = []
    answer_parts: list[str] = []
    for msg in messages:
        role_val = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
        if role_val != "assistant" or not msg.content:
            continue
        content = msg.content
        # 老会话兼容清洗:历史消息可能仍是 "Thought:...\nResponse:..." 全文
        t_part, r_part = parse_thought_response(content)
        cleaned = (r_part or (content if not t_part else "")).strip()
        cleaned = strip_module_done_markers(cleaned)
        if not cleaned:
            continue
        if getattr(msg, "tool_calls", None):
            if not narrations or narrations[-1] != cleaned:
                narrations.append(cleaned)
        else:
            merge_visible_piece(answer_parts, cleaned)
    return narrations, answer_parts


@dataclass
class StepStreamState:
    step_id: int
    last_stream_text: str = ""
    last_stream_thought: str = ""
    last_stream_response: str = ""
    stream_emitted: bool = False
    answer_emitted: bool = False
    final_emitted: bool = False
    narration_promoted_before_tool: bool = False


class AgentStream:
    """Handles streaming agent execution to WebSocket.

    使用与原始 server.py 相同的执行逻辑：
    - 手动步骤循环
    - 调用 agent.step()
    - 发送 step, thought, tool_call, tool_result, answer 事件
    - 去重：防止发送重复内容
    """

    def __init__(
        self,
        agent: Manus,
        session_id: str,
        state_machine: AgentStateMachine,
        event_sender: EventSender,
        chat_history_manager: Optional[Any] = None,
    ) -> None:
        """Initialize the agent stream.

        Args:
            agent: The Manus agent instance
            session_id: Unique session identifier
            state_machine: The state machine for tracking execution
            event_sender: Async function to send events
            chat_history_manager: Optional chat history manager
        """
        self.agent = agent
        self._session_id = session_id
        self._state_machine = state_machine
        self._send_event = event_sender
        self._chat_history_manager = chat_history_manager

        # 🚨 去重：跟踪已发送的内容
        self._sent_thoughts: set[str] = set()
        self._sent_tools: set[str] = set()
        self._sent_tool_results: set[str] = set()
        self._last_answer_content: str = ""
        self._answer_sent_in_loop: bool = False  # 🚨 跟踪循环中是否已发送过 answer
        self._answer_event_seq: int = 0
        self._emitted_answer_fingerprints: set[str] = set()
        self._final_answer_sent: bool = False
        # Wave 1.2: suggestions 只发一次(step-tail 与 post-loop 两个提取点都可能命中同一标记)
        self._suggestions_emitted: bool = False
        # B层:本轮已收集的旁白(带工具步的 content),累计后以 ThoughtEvent 推前端
        self._turn_narrations: list[str] = []
        # B层·延迟定性:上一步的 (content, 是否流过delta)——下一步真开始才定性
        # 为旁白;循环结束仍未 flush 的交给 post-loop 裁决(Codex review P1-1)
        self._pending_step_narration: Optional[tuple] = None
        self._current_step_stream_state: Optional[StepStreamState] = None
        self._stream_cancel_event: Optional[asyncio.Event] = None

    def _next_answer_event_seq(self) -> int:
        self._answer_event_seq += 1
        return self._answer_event_seq

    def _build_answer_event(
        self,
        *,
        content: str,
        is_complete: bool,
        delta: Optional[str] = None,
    ) -> Optional[AnswerEvent]:
        content_norm = self._normalize_text(content)
        if not content_norm:
            return None

        if is_complete and self._final_answer_sent:
            return None

        delta_norm = self._normalize_text(delta)
        fingerprint = f"{int(is_complete)}|{content_norm}|{delta_norm}"
        if fingerprint in self._emitted_answer_fingerprints:
            return None

        self._emitted_answer_fingerprints.add(fingerprint)
        self._last_answer_content = content_norm
        if is_complete:
            self._final_answer_sent = True
            self._answer_sent_in_loop = True

        return AnswerEvent(
            content=content,
            delta=delta,
            is_complete=is_complete,
            session_id=self._session_id,
            event_seq=self._next_answer_event_seq(),
        )

    def _build_complete_answer_event(self, content: str) -> Optional[AnswerEvent]:
        """Single completion writer used by normal and recoverable-error exits."""
        return self._build_answer_event(content=content, is_complete=True)

    def _ensure_assistant_message(self, content: Optional[str]) -> None:
        """Ensure the assistant message is present in memory for persistence."""
        if not content or not content.strip():
            return
        
        content_clean = content.strip()
        
        # 提取 Response 部分（如果存在 Thought: ... Response: 格式）
        content_response_part = content_clean
        if "Response:" in content_clean:
            # 如果 content 包含 Response:，提取 Response: 之后的部分
            content_response_part = content_clean.split("Response:")[-1].strip()
        
        for msg in reversed(self.agent.memory.messages):
            if msg.role == Role.ASSISTANT:
                msg_content = (msg.content or "").strip()
                
                # 完全匹配
                if msg_content == content_clean:
                    return
                
                # 检查是否是 Thought + Response 格式，且 Response 部分匹配
                if "Response:" in msg_content:
                    msg_response_part = msg_content.split("Response:")[-1].strip()
                    # 如果 content 的 Response 部分与已存在的 Response 部分相同
                    if msg_response_part == content_response_part:
                        return
                    # 如果 content 完全等于已存在的 Response 部分
                    if msg_response_part == content_clean:
                        return
                
                # 检查反向：content_clean 是否包含在 msg_content 中（作为子串）
                if content_clean in msg_content:
                    return
                
                # 检查反向：msg_content 的 Response 部分是否包含 content_clean
                if "Response:" in msg_content:
                    msg_response_part = msg_content.split("Response:")[-1].strip()
                    if content_clean in msg_response_part:
                        return
                
                break
        
        self.agent.memory.add_message(Message.assistant_message(content))

    @staticmethod
    def _normalize_text(text: Optional[str]) -> str:
        return (text or "").strip()

    def _get_latest_assistant_content(self) -> str:
        for msg in reversed(self.agent.memory.messages):
            if msg.role == "assistant" and msg.content:
                return msg.content
        return ""

    def _is_pending_ask_question(self) -> bool:
        """本轮 agent 是否调用了 ask_user_question 工具(弹出选择框等用户逐项确认)。

        和 is_asking_question(问号启发式)是两套互补的暂停判据:问号启发式兜老
        路径,这里兜结构化工具路径。扫最后一条带 tool_calls 的 assistant 消息,
        看有没有 ask_user_question。"""
        for msg in reversed(self.agent.memory.messages):
            if msg.role != "assistant":
                continue
            if not msg.tool_calls:
                continue
            for tc in msg.tool_calls:
                tool_name = getattr(getattr(tc, "function", None), "name", "") or ""
                if tool_name == "ask_user_question":
                    return True
            # 只看最近一条带 tool_calls 的 assistant 消息即可
            return False
        return False

    def _should_skip_complete_answer(self, content: str) -> bool:
        state = self._current_step_stream_state
        if not state or not state.final_emitted:
            return False
        # 只有与已流式发出的「回答正文」完全一致才跳过;此前比较的是含
        # Thought:/%%SUGGESTIONS%% 标记的全文,无标记输出场景会误判,
        # 导致收尾 answer 永远发不出、正文只在流式区闪现(2026-07-10 实测)
        normalized = self._normalize_text(content)
        return bool(normalized) and normalized == self._normalize_text(state.last_stream_response)

    def _build_optimize_progress_note(
        self, progress: Optional[Dict[str, Any]], stuck: bool = False
    ) -> Optional[str]:
        """整份优化任务：把本请求收尾后的真实进度写成一句可见文案。

        auto_continue 事件当前只有后端在发，前端还没接消费逻辑（已知缺口），
        静默丢弃会让用户误以为整份优化已经全部完成。这里不依赖前端是否消费
        该事件，直接把"还剩哪些模块""是否达上限"写进用户能看到的 answer 里。

        **独立 review 发现**：`is_stuck()` 提前终止（`stuck=True`）时任务会被
        强制 `finish_progress`，不会再自动续跑——这跟"本轮处理完、系统会自动
        继续"是两码事，必须给单独的文案，否则复用下面的常规分支会说"系统将
        自动继续"，而实际上不会，属于另一种误导性完成态。
        """
        if not progress:
            return None
        status = progress.get("status")
        cnt = progress.get("continue_count", 0)
        cap = ResumeDataStore.MAX_CONTINUE_COUNT
        if stuck:
            pending = progress.get("pending") or []
            if status in ("optimizing", "reviewing") and (pending or status == "reviewing"):
                labels = "、".join(MODULE_LABEL.get(k, k) for k in pending) or "最终一致性审阅"
                return f"⚠️ 整份优化因未能继续推进已提前终止，以下部分尚未处理：{labels}。如需继续请回复「继续优化」（会重新发起整份优化，已完成的修改不会丢失，但会再过一遍）。"
            return None
        if status == "optimizing" and progress.get("pending"):
            labels = "、".join(MODULE_LABEL.get(k, k) for k in progress["pending"])
            if cnt >= cap:
                return f"⚠️ 整份优化已达自动续跑上限，以下模块尚未处理：{labels}。如需继续请回复「继续优化」（会重新发起整份优化，已完成的修改不会丢失，但会再过一遍）。"
            return f"📋 本轮已处理完成，剩余待优化模块：{labels}（系统将自动继续；若未自动继续，请回复「继续优化」）。"
        if status == "reviewing" and not progress.get("review_dispatched"):
            if cnt >= cap:
                return "⚠️ 已达自动续跑上限，最终一致性审阅尚未执行。如需审阅请回复「继续优化」。"
            return "📋 所有模块已处理完成，即将进行最终一致性审阅（若未自动进行，请回复「继续优化」）。"
        return None

    def _build_narration_thought_event(
        self, text: str, step_id: int
    ) -> Optional[ThoughtEvent]:
        """把一次 ReAct step 的动作旁白发成独立 ThoughtEvent。"""
        text = self._normalize_text(text)
        if not text:
            return None
        thought_hash = hash(f"{step_id}|{text}")
        if thought_hash in self._sent_thoughts:
            return None
        self._sent_thoughts.add(thought_hash)
        return ThoughtEvent(
            thought=text,
            session_id=self._session_id,
            step_id=step_id,
        )

    @staticmethod
    def _diagnosis_completion_text(structured_data: Any) -> str:
        details = (
            structured_data.get("details")
            if isinstance(structured_data, dict)
            else None
        )
        source = details.get("diagnosis_source") if isinstance(details, dict) else None
        if source == "heuristic_fallback":
            return "深度诊断暂时没跑完，我先给你一版基础检查；本轮没有改动简历。"
        return "诊断已经整理好，本轮没有改动简历。想看逐条修改建议，点评分卡上的「查看修改建议」。"

    @staticmethod
    def _is_hidden_diagnosis_guard_result(content: Optional[str]) -> bool:
        """Hide rejected write/asking attempts from the public tool timeline."""
        text = content or ""
        return (
            "本轮只做简历诊断和修改建议" in text
            or "本轮为只读查看请求" in text
        )

    def _make_suggestions_event(self, items: list[dict]) -> Optional[SuggestionsEvent]:
        """构造 suggestions 事件并保证整个 run 只发一次。

        Wave 1.2:step-tail 与 post-loop 两个提取点可能命中同一份标记
        (step-tail 发射后内容仍持久化在 memory,post-loop 会再次提取)。
        """
        if not items or self._suggestions_emitted:
            return None
        self._suggestions_emitted = True
        return SuggestionsEvent(items=items, session_id=self._session_id)

    def _extract_suggestions(self, content: str) -> tuple[str, list[dict]]:
        """Parse %%SUGGESTIONS%%[...]%%END%% marker from content.

        Returns (cleaned_content, suggestions_list).
        cleaned_content has the marker stripped.
        """
        import re, json
        # 尝试完整匹配
        pattern = r'%%SUGGESTIONS%%(\[.*?\])%%END%%'
        match = re.search(pattern, content, re.DOTALL)

        if match:
            try:
                items = json.loads(match.group(1))
                cleaned = content[:match.start()].rstrip() + content[match.end():]
                return cleaned.rstrip(), items
            except Exception:
                pass

        # 如果没有完整匹配，尝试半开放匹配（容错：模型可能没输出完 %%END%%）
        partial_pattern = r'%%SUGGESTIONS%%(\[.*)'
        partial_match = re.search(partial_pattern, content, re.DOTALL)
        if partial_match:
            try:
                json_str = partial_match.group(1).strip()
                # 补全可能的闭合括号
                if not json_str.endswith(']'):
                    # 寻找最后一个完整的 JSON 对象结束点
                    last_obj_end = json_str.rfind('}')
                    if last_obj_end != -1:
                        json_str = json_str[:last_obj_end+1] + ']'

                items = json.loads(json_str)
                cleaned = content[:partial_match.start()].rstrip()
                return cleaned.rstrip(), items
            except Exception:
                pass

        return content, []

    def _serialize_tool_calls(self, tool_calls: Any) -> str:
        """Serialize tool calls for deduplication."""
        if not tool_calls:
            return ""
        normalized: List[Any] = []
        for call in tool_calls:
            if hasattr(call, "model_dump"):
                normalized.append(call.model_dump())
            elif hasattr(call, "dict"):
                normalized.append(call.dict())
            elif isinstance(call, dict):
                normalized.append(call)
            else:
                normalized.append(str(call))
        return json.dumps(normalized, ensure_ascii=False, sort_keys=True, default=str)

    def _dedupe_messages(self, messages: List[Message]) -> List[Message]:
        """去重消息列表，防止重复保存到历史记录。"""
        if not messages:
            return messages

        deduped: List[Message] = []
        seen_keys: Set[str] = set()

        for msg in messages:
            if msg.role == Role.USER:
                # 用户消息已在 stream.py 中写入 history
                continue

            content = (msg.content or "").strip()
            if msg.role == Role.ASSISTANT:
                response_part = content
                if "Response:" in content:
                    response_part = content.split("Response:")[-1].strip()

                tool_calls_str = self._serialize_tool_calls(msg.tool_calls)
                key = f"assistant|||{content}|||{tool_calls_str}"
                response_key = None
                if response_part and response_part != content:
                    response_key = f"assistant|||{response_part}|||{tool_calls_str}"

                if key in seen_keys or (response_key and response_key in seen_keys):
                    logger.debug(
                        f"[AgentStream] Skip duplicate assistant message: {content[:50]}..."
                    )
                    continue

                seen_keys.add(key)
                if response_key:
                    seen_keys.add(response_key)

            elif msg.role == Role.TOOL:
                key = f"tool|||{msg.name}|||{msg.tool_call_id}|||{content}"
                if key in seen_keys:
                    logger.debug(
                        f"[AgentStream] Skip duplicate tool message: {msg.name}"
                    )
                    continue
                seen_keys.add(key)
            else:
                key = f"{msg.role}|||{content}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)

            deduped.append(msg)

        return deduped

    async def execute(self, user_message: str) -> AsyncIterator[StreamEvent]:
        """Execute agent with streaming events.

        使用手动步骤循环，与原始 server.py 逻辑相同。

        Args:
            user_message: The user's input message

        Yields:
            StreamEvent instances during execution
        """
        start_memory_len = len(self.agent.memory.messages)
        # 整份优化任务：is_stuck() 判定卡死提前退出时置位，收尾阶段据此跳过
        # auto_continue（不能对一个已经卡死的会话还发起自动续跑，见下方接入点）。
        optimize_stuck = False
        try:
            # Start state
            await self._state_machine.transition_to(
                AgentState.STARTING,
                message="Starting agent execution",
                data={"user_message": user_message},
            )

            # 转换为 SSE 格式（向后兼容）
            yield AgentStartEvent(
                agent_name="Manus",
                task=user_message,
                session_id=self._session_id,
            )

            # Running state
            await self._state_machine.transition_to(AgentState.RUNNING)

            # 确保智能体处于 IDLE 状态
            if self.agent.state != SchemaAgentState.IDLE:
                self.agent.state = SchemaAgentState.IDLE
                self.agent.current_step = 0

            # 清理不完整的消息序列
            self.agent.memory.cleanup_incomplete_sequences()

            # 添加用户消息到 memory
            self.agent.memory.add_message(Message.user_message(user_message))

            # 同步到 LangChain Memory
            if hasattr(self.agent, '_langchain_memory') and self.agent._langchain_memory:
                self.agent._langchain_memory.add_user_message(user_message)

            # 重置 answer 发送标志
            self._answer_sent_in_loop = False

            # 根据任务类型动态调整最大步数。
            # Wave A-3(P1-1):最终一致性审阅轮显式给 10 步——它要通读全篇、
            # 核对事实、还可能调编辑工具修正,此前审阅的 AUTO_CONTINUE 输入
            # ("进入最终一致性审阅")不含"分析/详细"关键词,只拿到 5 步预算,
            # 修一半就被掐(2026-07-12 long-task spec 七点二欠账)。
            _review_progress = ResumeDataStore.get_progress(self._session_id)
            is_review_round = bool(
                _review_progress
                and _review_progress.get("status") == "reviewing"
                and _review_progress.get("review_dispatched")
            )
            # 诊断 apply 轮（按建议修改 / 单条改 / 缺口接力"我确认这些信息"）要逐条
            # 改多个字段、最后还要产出编号对账收尾；5 步会被逐条编辑用满、掐掉收尾
            # （2026-07-17 端到端实测：5 条缺口填完就没预算总结）——与审阅轮同理给 10 步。
            _apply_anchors = ("按建议", "按照诊断", "诊断建议", "我确认这些信息")
            is_apply_like = any(anchor in user_message for anchor in _apply_anchors)
            if is_review_round or is_apply_like or any(
                keyword in user_message.lower()
                for keyword in ["分析", "analyze", "深入", "详细"]
            ):
                max_steps = 10
            else:
                max_steps = 5

            # 记录最后发送的思考内容
            last_sent_thought = None

            # 手动执行步骤循环
            async with self.agent.state_context(SchemaAgentState.RUNNING):
                while self.agent.current_step < max_steps and self.agent.state != SchemaAgentState.FINISHED:
                    if self._state_machine.stop_requested:
                        # 🚨 优化停止状态反馈
                        stop_reason = self._state_machine.state_info.data.get("reason", "manual")
                        message = "Execution stopped by user"
                        if stop_reason == "session_switch":
                            message = "Execution stopped due to session switch"

                        await self._state_machine.transition_to(AgentState.STOPPED, message=message)
                        yield SystemEvent(
                            message=message,
                            level="info",
                            session_id=self._session_id,
                        )
                        return

                    self.agent.current_step += 1

                    # 发送步骤事件
                    yield SystemEvent(
                        message=f"执行步骤 {self.agent.current_step}/{max_steps}",
                        level="info",
                        session_id=self._session_id,
                    )

                    # 记录执行前的消息数量
                    msg_count_before = len(self.agent.memory.messages)

                    # 真流式：并发执行 step 与内容流消费
                    step_state = StepStreamState(step_id=self.agent.current_step)
                    self._current_step_stream_state = step_state
                    # Keep ordered stream chunks to preserve true incremental output.
                    stream_queue: asyncio.Queue[str] = asyncio.Queue()
                    reasoning_queue: asyncio.Queue[PublicReasoning] = asyncio.Queue()
                    tool_start_queue: asyncio.Queue[
                        tuple[ToolCall, dict[str, Any], asyncio.Future[None]]
                    ] = asyncio.Queue()
                    self._stream_cancel_event = asyncio.Event()

                    async def _on_content_delta(content: str) -> None:
                        if not content:
                            return
                        if self._stream_cancel_event and self._stream_cancel_event.is_set():
                            return
                        await stream_queue.put(content)

                    async def _on_public_reasoning(update: PublicReasoning) -> None:
                        if self._stream_cancel_event and self._stream_cancel_event.is_set():
                            return
                        await reasoning_queue.put(update)

                    async def _on_tool_start(
                        command: ToolCall, args: dict[str, Any]
                    ) -> None:
                        if self._stream_cancel_event and self._stream_cancel_event.is_set():
                            return
                        acknowledged: asyncio.Future[None] = (
                            asyncio.get_running_loop().create_future()
                        )
                        await tool_start_queue.put((command, args, acknowledged))
                        await acknowledged

                    if hasattr(self.agent, "set_stream_content_callback"):
                        self.agent.set_stream_content_callback(
                            _on_content_delta, self._stream_cancel_event
                        )
                    if hasattr(self.agent, "set_public_reasoning_callback"):
                        self.agent.set_public_reasoning_callback(_on_public_reasoning)
                    if hasattr(self.agent, "set_tool_start_callback"):
                        self.agent.set_tool_start_callback(_on_tool_start)

                    step_task = asyncio.create_task(self.agent.step())
                    step_result: Optional[str] = None
                    try:
                        while (
                            not step_task.done()
                            or not stream_queue.empty()
                            or not reasoning_queue.empty()
                            or not tool_start_queue.empty()
                        ):
                            if self._state_machine.stop_requested:
                                # 🚨 处理真流式执行中的停止
                                stop_reason = self._state_machine.state_info.data.get("reason", "manual")
                                message = "Execution stopped by user"
                                if stop_reason == "session_switch":
                                    message = "Execution stopped due to session switch"

                                if self._stream_cancel_event:
                                    self._stream_cancel_event.set()
                                if not step_task.done():
                                    step_task.cancel()
                                break

                            while not reasoning_queue.empty():
                                update = reasoning_queue.get_nowait()
                                content = self._normalize_text(update.content)
                                if not content:
                                    continue
                                yield ThoughtEvent(
                                    thought=content,
                                    session_id=self._session_id,
                                    step_id=self.agent.current_step,
                                    node_id=update.node_id,
                                    phase=update.phase,
                                    is_complete=update.is_complete,
                                )
                                if update.tool_progress:
                                    yield ToolProgressEvent(
                                        **update.tool_progress,
                                        session_id=self._session_id,
                                    )

                            # Content deltas have priority so the action narration
                            # is fully visible before the running tool card.  The
                            # tool itself is blocked on the acknowledgement below.
                            if stream_queue.empty() and not tool_start_queue.empty():
                                command, parsed_args, acknowledged = (
                                    tool_start_queue.get_nowait()
                                )
                                try:
                                    narration = self._normalize_text(
                                        step_state.last_stream_text
                                    )
                                    thought_part, response_part = parse_thought_response(
                                        narration
                                    )
                                    narration = self._normalize_text(
                                        response_part
                                        or (narration if not thought_part else thought_part)
                                    )
                                    narration_event = self._build_narration_thought_event(
                                        narration, self.agent.current_step
                                    )
                                    if narration_event:
                                        yield narration_event
                                    if step_state.answer_emitted:
                                        self._emitted_answer_fingerprints.clear()
                                        yield AnswerResetEvent(session_id=self._session_id)
                                    step_state.narration_promoted_before_tool = True

                                    tool_name = command.function.name
                                    tool_call_id = command.id
                                    await self._state_machine.transition_to(
                                        AgentState.TOOL_EXECUTING
                                    )
                                    if tool_call_id not in self._sent_tools:
                                        self._sent_tools.add(tool_call_id)
                                        yield ToolCallEvent(
                                            tool_name=tool_name,
                                            tool_args=parsed_args,
                                            session_id=self._session_id,
                                            tool_call_id=tool_call_id,
                                            step_id=self.agent.current_step,
                                        )
                                finally:
                                    if not acknowledged.done():
                                        acknowledged.set_result(None)
                                continue

                            try:
                                streamed_content = await asyncio.wait_for(
                                    stream_queue.get(), timeout=0.01
                                )
                            except asyncio.TimeoutError:
                                continue

                            if (
                                streamed_content
                                and self._normalize_text(
                                    streamed_content
                                    if streamed_content.startswith(step_state.last_stream_text)
                                    else (step_state.last_stream_text + streamed_content)
                                )
                                != self._normalize_text(step_state.last_stream_text)
                            ):
                                # Backward compatibility:
                                # - If callback sends cumulative text, replace directly.
                                # - If callback sends delta text, append incrementally.
                                if streamed_content.startswith(step_state.last_stream_text):
                                    step_state.last_stream_text = streamed_content
                                else:
                                    step_state.last_stream_text += streamed_content
                                step_state.stream_emitted = True

                                # Try to preserve "Thought/Response" UX while streaming.
                                thought_part, response_part = parse_thought_response(
                                    step_state.last_stream_text
                                )
                                if (
                                    thought_part
                                    and self._normalize_text(thought_part)
                                    != self._normalize_text(step_state.last_stream_thought)
                                ):
                                    step_state.last_stream_thought = thought_part
                                    yield ThoughtEvent(
                                        thought=thought_part,
                                        session_id=self._session_id,
                                        step_id=self.agent.current_step,
                                    )

                                # Untagged tool narration cannot be classified as
                                # an answer until the model response reveals
                                # whether it contains a tool call.  Buffer it here;
                                # the tool-start handoff promotes it to Thought,
                                # while a no-tool turn is completed by the single
                                # post-loop answer writer.  Explicit Response:
                                # content remains eligible for incremental output.
                                has_explicit_response_marker = bool(
                                    re.search(
                                        r"(?:Response|回复|Answer|Final\s*Answer|最终回复)\s*[:：]",
                                        step_state.last_stream_text,
                                        re.IGNORECASE,
                                    )
                                )
                                stream_answer = (
                                    response_part
                                    if has_explicit_response_marker and response_part
                                    else ""
                                )
                                # Wave A-4(P0-2):delta 出口协议标记滤波——完整标记
                                # 删除、尾部未闭合/被切开的标记扣住(纯函数全量重算,
                                # 幂等;流尾由 post-loop 净化 complete 整体替换兜底)
                                stream_answer = filter_streaming_markers(stream_answer)
                                if (
                                    stream_answer
                                    and self._normalize_text(stream_answer)
                                    != self._normalize_text(step_state.last_stream_response)
                                ):
                                    answer_delta = stream_answer
                                    if stream_answer.startswith(step_state.last_stream_response):
                                        answer_delta = stream_answer[
                                            len(step_state.last_stream_response):
                                        ]
                                    step_state.last_stream_response = stream_answer
                                    if answer_delta:
                                        answer_event = self._build_answer_event(
                                            content=stream_answer,
                                            delta=answer_delta,
                                            is_complete=False,
                                        )
                                        if answer_event:
                                            step_state.answer_emitted = True
                                            yield answer_event

                        step_result = await step_task

                    except asyncio.CancelledError:
                        logger.info("[AgentStream] step_task cancelled")
                        stop_reason = self._state_machine.state_info.data.get("reason", "manual")
                        message = "Execution stopped by user"
                        if stop_reason == "session_switch":
                            message = "Execution stopped due to session switch"

                        await self._state_machine.transition_to(AgentState.STOPPED, message=message)
                        yield SystemEvent(
                            message=message,
                            level="info",
                            session_id=self._session_id,
                        )
                        return
                    finally:
                        if hasattr(self.agent, "clear_stream_content_callback"):
                            self.agent.clear_stream_content_callback()
                        if hasattr(self.agent, "clear_public_reasoning_callback"):
                            self.agent.clear_public_reasoning_callback()
                        if hasattr(self.agent, "clear_tool_start_callback"):
                            self.agent.clear_tool_start_callback()
                        while not tool_start_queue.empty():
                            _command, _args, acknowledged = tool_start_queue.get_nowait()
                            if not acknowledged.done():
                                acknowledged.set_result(None)
                        self._stream_cancel_event = None

                    if hasattr(self.agent, "drain_resume_patches"):
                        from backend.agent.web.streaming.events import ResumePatchEvent

                        queued_patches = self.agent.drain_resume_patches()
                        diagnosis_only = bool(
                            getattr(getattr(self.agent, "_turn", None), "diagnosis_only", False)
                        )
                        if diagnosis_only and queued_patches:
                            logger.info(
                                "[AgentStream] 诊断轮丢弃 %s 个跨轮残留 resume_patch",
                                len(queued_patches),
                            )
                            queued_patches = []
                        for patch in queued_patches:
                            logger.info(
                                "[AgentStream] Emitting queued resume_patch: "
                                f"patch_id={patch.get('patch_id', '')}, "
                                f"paths={patch.get('paths', [])}"
                            )
                            yield ResumePatchEvent(
                                patch_id=patch.get("patch_id", ""),
                                paths=patch.get("paths", []),
                                before=patch.get("before", {}),
                                after=patch.get("after", {}),
                                summary=patch.get("summary", ""),
                                operation=patch.get("operation", "update"),
                                session_id=self._session_id,
                            )

                    # Wave A-2(P0-3):原 _pending_immediate_stream(qwq thinking 流)
                    # 分支已整段删除——全仓无生产者的死代码(仅 turn_state 默认
                    # None 与此处消费),且其持久化格式 f"Thought:...\nResponse:..."
                    # 是文本协议污染源之一、其 is_complete 提前发射违反 complete
                    # 单写者。2026-07-13 审查 R1-MAJOR-3。

                    safe_step = str(step_result).replace("<", r"\<").replace(">", r"\>")
                    logger.info(
                        f"🔍 [DEBUG] step() 返回: {safe_step}, agent.state: {self.agent.state}, "
                        f"_answer_sent_in_loop: {self._answer_sent_in_loop}"
                    )

                    # step 收尾·B层结构路由(延迟定性,Codex review P1-1):
                    # 带 tool_calls 的步 content 是旁白还是正文,要看「后面还有
                    # 没有下一步」——FINISHED 只覆盖挂起类终点,步数耗尽/stuck
                    # 等终点它看不见,立发旁白会与 post-loop 的'末旁白提升正文'
                    # 兜底双份。故此处只暂存 pending,由下一轮循环开头 flush
                    # (真有下一步才定性为旁白);循环结束仍未 flush 的,交给
                    # post-loop 结构路由统一裁决,天然覆盖一切终点形态。
                    last_step_msg = None
                    for _m in reversed(self.agent.memory.messages):
                        _role = _m.role.value if hasattr(_m.role, "value") else str(_m.role)
                        if _role == "assistant":
                            last_step_msg = _m
                            break
                    if (
                        last_step_msg is not None
                        and getattr(last_step_msg, "tool_calls", None)
                        and (last_step_msg.content or "").strip()
                    ):
                        _piece = strip_module_done_markers(
                            (last_step_msg.content or "").strip()
                        )
                        _t, _r = parse_thought_response(_piece)  # 老会话兼容清洗
                        _piece = (_r or (_piece if not _t else "")).strip()
                        if _piece:
                            self._pending_step_narration = (
                                _piece,
                                step_state.answer_emitted,
                            )

                    # tool step 的 content 在结构上已经确定是动作旁白，不再等到
                    # 下一步才累计发射。先发本 step 的独立 thought，再发 tool
                    # call/result，保证前端时间线严格呈现 think → tool → result。
                    if self._pending_step_narration is not None:
                        _piece, _had_stream = self._pending_step_narration
                        self._pending_step_narration = None
                        if _piece and (
                            not self._turn_narrations
                            or self._turn_narrations[-1] != _piece
                        ):
                            self._turn_narrations.append(_piece)
                        narration_event = self._build_narration_thought_event(
                            _piece, self.agent.current_step
                        )
                        if narration_event:
                            yield narration_event
                        if _had_stream and not step_state.narration_promoted_before_tool:
                            self._emitted_answer_fingerprints.clear()
                            yield AnswerResetEvent(session_id=self._session_id)

                    # 🔍 调试：检查状态变化
                    # 单一路径：循环内只发 delta，不发 complete。complete 只在循环结束后发一次。
                    # 注意：不再在此处 break，确保 new_messages（工具调用等）始终被处理。
                    # FINISHED break 移至迭代末尾（analysis completion 之后）。

                    # 实时发送新增的消息
                    new_messages = self.agent.memory.messages[msg_count_before:]
                    hidden_guard_call_ids = {
                        msg.tool_call_id
                        for msg in new_messages
                        if msg.role == "tool"
                        and msg.tool_call_id
                        and self._is_hidden_diagnosis_guard_result(msg.content)
                    }

                    # 检查是否有分析工具结果
                    has_recent_analysis_result = False
                    for msg in reversed(self.agent.memory.messages[-10:]):
                        if msg.role == "tool" and msg.name == 'cv_analyzer_agent':
                            has_recent_analysis_result = True
                            break

                    # 处理新消息
                    for msg in new_messages:
                        if msg.role == "assistant":
                            # 先处理 tool_calls（assistant 消息可以同时有 content 和 tool_calls）
                            if msg.tool_calls:
                                if (
                                    self._state_machine.current_state
                                    != AgentState.TOOL_EXECUTING
                                ):
                                    await self._state_machine.transition_to(
                                        AgentState.TOOL_EXECUTING
                                    )
                                for tool_call in msg.tool_calls:
                                    tool_name = tool_call.function.name
                                    tool_call_id = tool_call.id  # ✅ 获取 tool_call_id
                                    if tool_call_id in hidden_guard_call_ids:
                                        logger.info(
                                            "[诊断守卫] 不展示已拦截的工具调用: %s",
                                            tool_name,
                                        )
                                        continue

                                    # 🚨 去重：使用 tool_call_id 而不是 step 作为键
                                    if tool_call_id in self._sent_tools:
                                        logger.info(f"[跳过重复工具] {tool_name} (ID: {tool_call_id[:8]}...)")
                                        continue
                                    self._sent_tools.add(tool_call_id)

                                    tool_args = tool_call.function.arguments
                                    safe_args = str(tool_args).replace("<", r"\<").replace(">", r"\>")
                                    logger.info(f"[工具调用] {tool_name} | ID: {tool_call_id} | 参数: {safe_args[:100]}...")
                                    yield ToolCallEvent(
                                        tool_name=tool_name,
                                        tool_args=tool_args if isinstance(tool_args, (dict, str)) else {},
                                        session_id=self._session_id,
                                        tool_call_id=tool_call_id,  # ✅ 传递 tool_call_id
                                        step_id=self.agent.current_step,
                                    )

                            # 再处理 content（如果有）
                            if msg.content:
                                # True-streaming 已经通过 on_content_delta 输出过增量内容，
                                # 这里不再重复发送 assistant content，避免 thought/answer 重复。
                                if step_state.stream_emitted:
                                    logger.debug(
                                        "[AgentStream] Skip assistant content replay in memory loop"
                                    )
                                    continue

                                # 含 %%SUGGESTIONS%% 的内容由 post-loop 统一提取后作为 AnswerEvent+SuggestionsEvent 发送，
                                # 此处跳过避免将原始标记文本当作 ThoughtEvent 发出。
                                if "%%SUGGESTIONS%%" in msg.content:
                                    logger.debug(f"[AgentStream] Skip %%SUGGESTIONS%% content in message loop (len={len(msg.content)}); will be handled in post-loop")
                                    continue

                                # 🚨 去重：跳过已发送过的相同内容
                                content_hash = hash(msg.content)  # 使用完整内容，避免截断更新被误判
                                if content_hash in self._sent_thoughts:
                                    logger.debug(f"[跳过重复内容] {msg.content[:50]}...")
                                    continue
                                self._sent_thoughts.add(content_hash)

                                # 🎯 解析 Thought 和 Response 格式
                                logger.info(f"[解析前] 原始内容: {msg.content[:150]}...")

                                # #region debug log
                                import json
            # with open('/Users/wy770/AI/.cursor/debug.log', 'a') as f:
            #     f.write(json.dumps({
            #         "sessionId": "debug-session",
            #         "runId": "run1",
            #         "hypothesisId": "D",
            #         "location": "agent_stream.py:execute:LOOP_BEFORE_PARSE",
            #         "message": "before parse_thought_response in message loop",
            #         "data": {
            #             "msg_content_length": len(msg.content) if msg.content else 0,
            #             "msg_content_preview": msg.content[:300] if msg.content else None
            #         },
            #         "timestamp": int(__import__('time').time() * 1000)
            #     }) + '\n')
                                # #endregion

                                thought_part, response_part = parse_thought_response(msg.content)
                                logger.info(f"[解析后] thought={thought_part[:50] if thought_part else None}... response={response_part[:50] if response_part else None}...")

                                # #region debug log
            # with open('/Users/wy770/AI/.cursor/debug.log', 'a') as f:
            #     f.write(json.dumps({
            #         "sessionId": "debug-session",
            #         "runId": "run1",
            #         "hypothesisId": "D",
            #         "location": "agent_stream.py:execute:LOOP_AFTER_PARSE",
            #         "message": "after parse_thought_response in message loop",
            #         "data": {
            #             "thought_part_found": thought_part is not None,
            #             "response_part_found": response_part is not None,
            #             "thought_part_length": len(thought_part) if thought_part else 0,
            #             "response_part_length": len(response_part) if response_part else 0
            #         },
            #         "timestamp": int(__import__('time').time() * 1000)
            #     }) + '\n')
                                # #endregion

                                # 判断是否是分析结果回复
                                check_content = response_part or msg.content
                                contains_analysis_result = any(
                                    marker in check_content for marker in ANALYSIS_RESULT_MARKERS
                                )
                                is_final_answer = has_recent_analysis_result and contains_analysis_result

                                # 先发送 Thought（如果有）
                                if thought_part:
                                    logger.info(f"[Thought Process] {thought_part[:100]}...")
                                    # #region debug log
            # with open('/Users/wy770/AI/.cursor/debug.log', 'a') as f:
            #     f.write(json.dumps({
            #         "sessionId": "debug-session",
            #         "runId": "run1",
            #         "hypothesisId": "D",
            #         "location": "agent_stream.py:execute:LOOP_YIELD_THOUGHT",
            #         "message": "yielding ThoughtEvent in message loop",
            #         "data": {
            #             "thought_length": len(thought_part),
            #             "thought_preview": thought_part[:100]
            #         },
            #         "timestamp": int(__import__('time').time() * 1000)
            #     }) + '\n')
                                    # #endregion

                                    # 生成 CLTP content(channel='think') chunk
                                    # 关键：保持文本内容原样，不进行任何修改
                                    # 转换为 SSE 格式（向后兼容）
                                    yield ThoughtEvent(
                                        thought=thought_part,
                                        session_id=self._session_id,
                                        step_id=self.agent.current_step,
                                    )
                                else:
                                    # #region debug log (已禁用硬编码路径)
                                    # with open('/Users/wy770/AI/.cursor/debug.log', 'a') as f:
                                    #     f.write(json.dumps({
                                    #         "sessionId": "debug-session",
                                    #         "runId": "run1",
                                    #         "hypothesisId": "D",
                                    #         "location": "agent_stream.py:execute:LOOP_NO_THOUGHT",
                                    #         "message": "thought_part is None in message loop, not yielding ThoughtEvent",
                                    #         "data": {},
                                    #         "timestamp": int(__import__('time').time() * 1000)
                                    #     }) + '\n')
                                    # #endregion
                                    pass

                                # Single-writer policy (Karis-aligned):
                                # memory loop no longer emits plain answer.
                                # plain comes from stream delta path + FINISHED/fallback completion only.
                                if response_part:
                                    if is_final_answer:
                                        logger.info(f"[分析结果回复候选] {response_part[:200]}...")
                                elif not thought_part:
                                    # 没有格式化输出时仅保留 thought 兼容展示，不在此处发送 answer
                                    logger.debug(f"[思考过程] {msg.content[:100]}...")
                                    yield ThoughtEvent(
                                        thought=msg.content,
                                        session_id=self._session_id,
                                        step_id=self.agent.current_step,
                                    )

                        elif msg.tool_calls:
                            # 非 assistant 消息的 tool_calls（fallback）
                            if (
                                self._state_machine.current_state
                                != AgentState.TOOL_EXECUTING
                            ):
                                await self._state_machine.transition_to(
                                    AgentState.TOOL_EXECUTING
                                )
                            for tool_call in msg.tool_calls:
                                tool_name = tool_call.function.name
                                tool_call_id = tool_call.id  # ✅ 获取 tool_call_id
                                if tool_call_id in hidden_guard_call_ids:
                                    continue
                                # 🚨 去重：使用 tool_call_id 而不是 step 作为键
                                if tool_call_id in self._sent_tools:
                                    logger.info(f"[跳过重复工具] {tool_name} (ID: {tool_call_id[:8]}...)")
                                    continue
                                self._sent_tools.add(tool_call_id)

                                tool_args = tool_call.function.arguments
                                safe_args = str(tool_args).replace("<", r"\<").replace(">", r"\>")
                                logger.info(f"[工具调用] {tool_name} | ID: {tool_call_id} | 参数: {safe_args[:100]}...")
                                yield ToolCallEvent(
                                    tool_name=tool_name,
                                    tool_args=tool_args if isinstance(tool_args, (dict, str)) else {},
                                    session_id=self._session_id,
                                    tool_call_id=tool_call_id,  # ✅ 传递 tool_call_id
                                    step_id=self.agent.current_step,
                                )

                        elif msg.role == "tool":
                            # Only transition if not already in THINKING state
                            if self._state_machine.current_state != AgentState.THINKING:
                                await self._state_machine.transition_to(AgentState.THINKING)
                            content = msg.content
                            tool_call_id = msg.tool_call_id  # ✅ 获取 tool_call_id
                            tool_name = msg.name or "unknown"
                            if tool_call_id in hidden_guard_call_ids:
                                continue

                            # 清理前缀
                            if content and content.startswith("Observed output of cmd `"):
                                prefix_pattern = r"Observed output of cmd `[^`]+` executed:\n"
                                content = re.sub(prefix_pattern, "", content, count=1)
                            elif content and content.startswith("Cmd `"):
                                content = "工具执行完成，无输出内容"

                            # 限制显示长度
                            if content and len(content) > 5000:
                                content = content[:5000] + f"\n...(内容已截断，共{len(msg.content)}字符)"

                            logger.info(f"[工具结果] {tool_name} | ID: {tool_call_id} | 长度: {len(msg.content) if msg.content else 0} 字符")
                            result_key = f"{tool_name}|{tool_call_id}|{self._normalize_text(content)}"
                            if result_key in self._sent_tool_results:
                                logger.info(f"[跳过重复工具结果] {tool_name} (ID: {str(tool_call_id)[:8]}...)")
                                continue
                            self._sent_tool_results.add(result_key)
                            # 结构化结果无条件透传:是否有 structured 由工具自己决定
                            # (ToolResult.system 里放 {type,...} 即可),不再逐工具开白名单
                            structured_data = None
                            if hasattr(self.agent, "get_structured_tool_result"):
                                structured_data = self.agent.get_structured_tool_result(
                                    tool_call_id
                                )
                            yield ToolResultEvent(
                                tool_name=tool_name,
                                result=content or "",
                                is_error=is_tool_error_content(content),
                                session_id=self._session_id,
                                tool_call_id=tool_call_id,  # ✅ 传递 tool_call_id
                                structured_data=structured_data,
                                step_id=self.agent.current_step,
                            )

                            # 简历编辑成功后，推送完整的更新后简历 JSON 给前端。
                            # 前端收到 resume_updated 后直接替换本地状态，无需自行 re-apply diff。
                            # 注意：resume_patch 流程由前端用户确认后应用，不应提前推送 resume_updated。
                            if tool_name == "cv_editor_agent" and structured_data and structured_data.get("type") == "resume_edit_diff":
                                try:
                                    # 不要在这里再 import ResumeDataStore——文件顶部（197行）已经
                                    # module-level 导入过了。这个方法（execute）现在到处引用
                                    # ResumeDataStore（本轮加的 progress/auto_continue 相关代码），
                                    # 只要函数体里任何地方出现过 `ResumeDataStore = ...`/局部 import，
                                    # Python 就会把 ResumeDataStore 当成整个函数作用域的局部变量——
                                    # 这条工具调用分支没触发之前，前面任何一处引用都会直接
                                    # UnboundLocalError，异常处理里再引用一次 ResumeDataStore 同样会炸，
                                    # 导致连 AgentErrorEvent 都发不出去，前端表现为卡死在 loading。
                                    # 真实生产 bug，2026-07-12 用户实测复现（"你好"/整份优化任务
                                    # 到一半就断）。
                                    updated_resume = ResumeDataStore.get_data(self._session_id)
                                    if updated_resume:
                                        yield ResumeUpdatedEvent(
                                            resume_data=updated_resume,
                                            session_id=self._session_id,
                                        )
                                        logger.info(f"[AgentStream] resume_updated emitted for session={self._session_id}")
                                except Exception as _ru_exc:
                                    logger.warning(f"[AgentStream] Failed to emit resume_updated: {_ru_exc}")

                            # resume_patch event
                            if tool_name == "cv_editor_agent" and structured_data and structured_data.get("type") == "resume_patch":
                                logger.info(f"[AgentStream] Emitting resume_patch: patch_id={structured_data.get('patch_id','')}, before_keys={list(structured_data.get('before',{}).keys())}, after_keys={list(structured_data.get('after',{}).keys())}")
                                from backend.agent.web.streaming.events import ResumePatchEvent
                                yield ResumePatchEvent(
                                    patch_id=structured_data.get("patch_id", ""),
                                    paths=structured_data.get("paths", []),
                                    before=structured_data.get("before", {}),
                                    after=structured_data.get("after", {}),
                                    summary=structured_data.get("summary", ""),
                                    operation=structured_data.get("operation", "set"),
                                    session_id=self._session_id,
                                )

                            # resume_generated event
                            if tool_name == "generate_resume" and structured_data and structured_data.get("type") == "resume_generated":
                                from backend.agent.web.streaming.events import ResumeGeneratedEvent
                                yield ResumeGeneratedEvent(
                                    resume=structured_data.get("resume", {}),
                                    summary=structured_data.get("summary", ""),
                                    session_id=self._session_id,
                                )

                            # 🔑 关键修复：如果执行了 terminate 工具，且还没有发送过 answer
                            # 不要将技术性的 terminate 消息作为最终答案，而是跳过或使用友好消息
                            if tool_name == "terminate" and not self._answer_sent_in_loop:
                                logger.info(f"🔍 [DEBUG] terminate 工具执行完成，但没有 answer，跳过技术性消息")
                                # 标记已发送，防止后续再次处理，但不实际发送技术性消息给用户
                                self._answer_sent_in_loop = True

                    # 检查是否陷入循环
                    if self.agent.is_stuck():
                        logger.info("⚠️ Agent 检测到循环，终止执行")
                        optimize_stuck = True
                        break

                    # 检查分析任务是否完成
                    if has_recent_analysis_result:
                        has_analysis_output = False
                        for msg in reversed(self.agent.memory.messages[-10:]):
                            if msg.role == "assistant" and msg.content:
                                contains_result = any(
                                    marker in msg.content for marker in ANALYSIS_RESULT_MARKERS
                                )
                                has_content = len(msg.content) > 100
                                no_more_tools = not msg.tool_calls or len(msg.tool_calls) == 0
                                if contains_result and has_content and no_more_tools:
                                    has_analysis_output = True
                                    logger.info(f"✅ 分析结果已输出: {msg.content[:100]}...")
                                    break

                        if has_analysis_output:
                            logger.info("✅ 分析任务完成，终止循环")
                            self.agent.state = SchemaAgentState.FINISHED
                            break

                    # FINISHED break：确保 new_messages 已处理后再退出循环
                    if self.agent.state == SchemaAgentState.FINISHED:
                        logger.info("✅ Agent 状态已设置为 FINISHED，退出循环；complete 将在循环结束后统一发送")
                        break

                    # 整份优化任务：全部模块刚在本步处理完（optimizing→reviewing
                    # 相变发生在这一步），即使本请求预算还没用完也提前收尾，
                    # 不在本请求里顺手插审阅——一致性审阅必须独占下一次全新请求
                    # 的完整预算（设计方案七点二明确决策，五点六记录了这条不遵守
                    # 就会导致的资源竞争）。本方法收尾阶段（下方 auto_continue
                    # 触发逻辑）负责判断要不要发起那次独立的审阅请求。
                    _progress = ResumeDataStore.get_progress(self._session_id)
                    if (
                        _progress
                        and _progress.get("status") == "reviewing"
                        and not _progress.get("review_dispatched")
                    ):
                        logger.info(
                            "📋 整份优化全部模块已处理完，本请求提前收尾；"
                            "一致性审阅将独占下一次自动续跑请求"
                        )
                        self.agent.state = SchemaAgentState.FINISHED
                        break

            # 重置步骤计数
            self.agent.current_step = 0
            self.agent.state = SchemaAgentState.IDLE

            # 单写者：所有完整答案（含异常恢复）都经
            # _build_complete_answer_event；流式阶段只发 delta。
            # B层结构路由(替代 Wave A-1 的全量拼接):按消息结构分流——
            # 带 tool_calls 的中间步 content=旁白(思考折叠框),不带=正文。
            # 旁白不再进 complete,所以前端 complete 整体替换不会"吃掉旁白"
            # (旁白在 thought 通道,FATAL-1 的前提已被结构路由消解)。
            turn_messages = self.agent.memory.messages[start_memory_len:]
            turn_narrations, turn_visible_parts = split_turn_messages(turn_messages)
            if not turn_visible_parts and turn_narrations:
                last_tool_message = next(
                    (
                        msg
                        for msg in reversed(turn_messages)
                        if msg.role == "tool" and msg.name
                    ),
                    None,
                )
                last_tool_name = last_tool_message.name if last_tool_message else None
                if last_tool_name == "cv_analyzer_agent":
                    # 诊断结果已由结构化卡片承载；动作旁白已经作为独立 thought
                    # 发出，不能再整段提升为最终正文造成视觉重复。
                    diagnosis_data = None
                    if last_tool_message and hasattr(
                        self.agent, "get_structured_tool_result"
                    ):
                        diagnosis_data = self.agent.get_structured_tool_result(
                            last_tool_message.tool_call_id
                        )
                    turn_visible_parts = [
                        self._diagnosis_completion_text(diagnosis_data)
                    ]
                else:
                    # 兜底:整轮全是带工具步(ask_user_question/show_resume 挂起等
                    # 等用户操作的场景)——最后一条旁白就是本轮可见正文
                    # ("我弹个选择框跟你确认~"),提升为正文。
                    turn_visible_parts = [turn_narrations.pop()]
            # 以全量重算为准同步累计器(step-tail 增量收集可能有遗漏场景)
            self._turn_narrations = turn_narrations
            final_answer = "\n\n".join(turn_visible_parts) if turn_visible_parts else None
            if not final_answer:
                has_terminate = any(
                    m.role == "tool" and m.name == "terminate"
                    for m in self.agent.memory.messages
                )
                if has_terminate:
                    last_user = ""
                    for m in reversed(self.agent.memory.messages):
                        if m.role == "user":
                            last_user = getattr(m, "content", "") or ""
                            break
                    greeting_patterns = ["你好", "hello", "hi", "嗨", "哈喽", "早上好", "下午好", "晚上好"]
                    if any(p in (last_user or "").lower() for p in greeting_patterns):
                        final_answer = "你好！我是 AI 助手，很高兴见到你！我可以帮助你处理各种任务，比如搜索信息、生成报告、优化简历等。有什么我可以帮你的吗？"
                    else:
                        final_answer = "好的，还有什么我可以帮助你的吗？"
            if not final_answer:
                final_answer = "错误：Agent 执行过程中未生成有效回复、请检查任务配置或重试。"

            # 拼接路径已逐条取 response 正文并 strip 过标记；fallback 文案再过
            # 一遍 strip 是幂等保险。[[MODULE_DONE]] 只是内部协议信号，信号1
            # 在 think() 阶段已读 memory 原文完成推进，展示层必须干净
            # （2026-07-12/13 两次用户截图实测裸奔）。
            final_content = strip_module_done_markers((final_answer or "").strip())
            # m2 防双份：拼接结果是"合成大消息"，与 memory 里任何单条都不同，
            # 无条件 _ensure 会 append 近似双份。仅当本轮 memory 没有任何可见
            # assistant 正文（走了 fallback 文案）时才兜底补一条供持久化。
            if not turn_visible_parts:
                self._ensure_assistant_message(final_content)

            # 提取建议按钮标记
            clean_content, suggestion_items = self._extract_suggestions(final_content)

            # 独立review发现的真实bug（用户实测截图复现）：LLM本轮针对当前模块
            # 向用户提了个澄清问题（等真人回答"有/没有"），这种情况下不该说
            # "系统将自动继续"——本函数下面的 auto_continue 触发逻辑也会看这个
            # 标志，命中就不自动续跑，这里先算出来，两处共用同一个判断结果。
            is_asking_question = bool(clean_content and re.search(r"[?？]", clean_content))
            # Asking 模式：本轮 agent 调了 ask_user_question 工具（前端弹选择框
            # 逐项确认），同样要挂起 auto_continue，等用户点完选择框提交答案。
            # 和问号启发式是两套互补判据，合并成 should_pause_optimize，避免写
            # 两个 elif 互相吞。问号兜老路径（没接新工具时的自然语言提问），
            # 工具兜结构化路径。
            pending_ask_question = self._is_pending_ask_question()
            should_pause_optimize = is_asking_question or pending_ask_question

            # 整份优化任务：任务还没做完时，在可见 answer 里明确写清楚剩余模块，
            # 不能只靠 auto_continue 事件——前端目前还没接消费逻辑（已知缺口，
            # 见设计方案七点五），届时事件会被静默丢弃，用户看到的就是一条
            # "回答完了"的普通消息，容易误以为整份优化已经全部做完。这里不管
            # 前端接没接，都在文案上把真实进度说清楚（is_stuck 提前终止走单独
            # 文案，见 _build_optimize_progress_note 的 stuck 分支）。本轮在
            # 等用户回答问题时不追加这段提示——LLM 自己问的问题已经是最准确
            # 的"接下来该做什么"，再补一句"系统将自动继续"反而误导（不会自动
            # 继续，要等真人回答）。Asking 模式（调了 ask_user_question 工具）
            # 同理，工具弹的选择框本身就是问题。
            diagnosis_only = bool(
                getattr(getattr(self.agent, "_turn", None), "diagnosis_only", False)
            )
            if not should_pause_optimize and not diagnosis_only:
                _note_progress = ResumeDataStore.get_progress(self._session_id)
                _note = self._build_optimize_progress_note(_note_progress, stuck=optimize_stuck)
                if _note:
                    clean_content = f"{clean_content}\n\n{_note}"

            # Wave A-3(P1-1):审阅轮收尾前的确定性回验——审阅 prompt 只是
            # "要求"LLM 核对事实,这里用代码核对 facts 是否仍在改后简历中,
            # 结果写进可见回复。治"97% 被误删需补回"说完就丢、无人验证的
            # 闭环缺口(审查乱象 5;facts 此前是全仓零消费的死数据)。
            if is_review_round:
                _review_missing = verify_facts_coverage(
                    ResumeDataStore.get_progress(self._session_id) or {},
                    ResumeDataStore.get_data(self._session_id) or {},
                )
                if _review_missing:
                    _miss_lines = "；".join(
                        f"{MODULE_LABEL.get(m, m)}：{'、'.join(items[:5])}"
                        for m, items in _review_missing.items()
                    )
                    clean_content = (
                        f"{clean_content}\n\n⚠️ 系统事实核对：以下原文关键信息"
                        f"在当前简历中未找到——{_miss_lines}。若不是你主动要求"
                        f"删除的，跟我说一声我帮你补回。"
                    )
                else:
                    clean_content = (
                        f"{clean_content}\n\n✅ 系统事实核对：原文关键数字与"
                        f"专有名词已全部保留。"
                    )

            if not self._final_answer_sent and not self._should_skip_complete_answer(clean_content):
                answer_event = self._build_complete_answer_event(clean_content)
                if answer_event:
                    yield answer_event

            suggestions_event = self._make_suggestions_event(suggestion_items)
            if suggestions_event:
                yield suggestions_event

            # 保存到历史记录 - 保存所有类型的消息（包括 Tool 消息）
            if self._chat_history_manager:
                # 仅保存本次执行过程中新增的消息（避免重复保存历史消息）
                new_messages = self.agent.memory.messages[start_memory_len:]

                deduped_messages = self._dedupe_messages(new_messages)

                for msg in deduped_messages:
                    if msg.role == Role.USER:
                        # 用户消息已在 stream.py 中写入 history
                        continue

                    # 保存 assistant 消息（可能包含 tool_calls）
                    if msg.role == Role.ASSISTANT:
                        # 🔑 关键修复：只保存有实际内容的 assistant 消息
                        # 过滤掉只有 tool_calls 但 content 为空的消息（技术性消息）
                        has_content = msg.content and len(msg.content.strip()) > 0
                        has_tool_calls = msg.tool_calls and len(msg.tool_calls) > 0

                        if has_content or has_tool_calls:
                            # P0-4 历史出口清洗:协议标记不入库(库里的内容会被
                            # history 接口原样返回、前端加载零清洗直接显示)。
                            # strip MODULE_DONE + %%SUGGESTIONS%% 标记(Codex review
                            # P1-4 内容层:memory 原文里的建议标记此前会原样入库);
                            # Thought:/Response: 前缀由 P0-3 断源治增量、前端兜底治存量。
                            persist_content = msg.content
                            if persist_content:
                                persist_content = strip_module_done_markers(persist_content)
                                persist_content, _ = self._extract_suggestions(persist_content)
                            self._chat_history_manager.add_message(Message(
                                role=Role.ASSISTANT,
                                content=persist_content,
                                tool_calls=msg.tool_calls
                            ), persist=False)
                        else:
                            logger.debug(
                                f"[AgentStream] 跳过空的 assistant 消息 (无 content 且无 tool_calls)"
                            )
                    # 保存 tool 消息（关键：包含 optimization_suggestions JSON）
                    elif msg.role == Role.TOOL:
                        self._chat_history_manager.add_message(Message(
                            role=Role.TOOL,
                            content=msg.content,
                            name=msg.name,
                            tool_call_id=msg.tool_call_id
                        ), persist=False)
                        logger.debug(f"  💾 保存 Tool 消息: {msg.name}, 长度: {len(msg.content or '')}")

                # 🔑 关键修复：在所有消息添加完成后，手动触发一次持久化
                # 这确保用户消息（在 stream.py 中添加 persist=False）和所有其他消息都被保存
                self._chat_history_manager._persist_if_needed()

                logger.info(
                    f"📜 已保存对话到 ChatHistory (新增 {len(deduped_messages)} 条消息, "
                    f"总内存 {len(self.agent.memory.messages)} 条)"
                )

            # 整份优化任务：本请求收尾，检查任务是否还没做完，决定要不要提示
            # 前端自动发起下一轮续跑。一致性审阅永远独占下一次全新请求，绝不
            # 与模块处理共用本请求的步数预算（设计方案七点二明确决策）。
            # continue_count 硬上限防死循环（方案七点一发现 D）。
            progress = ResumeDataStore.get_progress(self._session_id)
            _MAX_AUTO_CONTINUE = ResumeDataStore.MAX_CONTINUE_COUNT
            # is_asking_question 复用上面（构造 answer 时）算好的同一个判断：
            # LLM本轮针对当前模块问了个澄清问题（"有没有奖学金？GPA多少？"），
            # 用户还没来得及回答，auto_continue不能自动发起下一轮把这个模块
            # 糊过去——manus.py._advance_optimize_progress的信号3已经在同一个
            # bug上做了修复（不自动判定skip），这里是配套的另一半：即使信号3
            # 不再误判skip，只要pending还在，本函数原来的逻辑依然会无脑发起
            # 下一轮自动续跑。命中就不自动续跑，让请求正常收尾，真等用户回复
            # （用户下一句真实回复会走正常的新一轮请求，不是auto_continue
            # 合成的那种）。
            if diagnosis_only:
                logger.info("🩺 只读诊断轮：保留旧优化进度，不自动续跑")
            elif optimize_stuck and progress:
                logger.warning("⚠️ 整份优化任务因 is_stuck 提前终止，不再自动续跑")
                ResumeDataStore.finish_progress(self._session_id)
            elif should_pause_optimize and progress and progress.get("status") in ("optimizing", "reviewing"):
                if pending_ask_question:
                    logger.info("💬 Asking 模式：本轮弹了选择框等用户逐项确认，暂不自动续跑")
                else:
                    logger.info("💬 本轮在等用户回答澄清问题，暂不自动续跑")
            elif progress and progress.get("status") == "optimizing" and progress.get("pending"):
                if progress.get("continue_count", 0) >= _MAX_AUTO_CONTINUE:
                    done = progress.get("done") or []
                    pending = progress.get("pending") or []
                    logger.warning(
                        f"⚠️ 整份优化续跑达上限({_MAX_AUTO_CONTINUE})，强制收尾："
                        f"已完成 {len(done)} 个模块，剩余 {pending} 未处理"
                    )
                    ResumeDataStore.finish_progress(self._session_id)
                else:
                    ResumeDataStore.bump_continue_count(self._session_id)
                    pending_labels = "、".join(progress["pending"])
                    yield AutoContinueEvent(
                        message=f"继续优化剩余模块：{pending_labels}",
                        reason="optimizing",
                        next_user_input=f"{AUTO_CONTINUE_PREFIX}继续优化剩余模块：{pending_labels}",
                        session_id=self._session_id,
                    )
            elif progress and progress.get("status") == "reviewing":
                if not progress.get("review_dispatched"):
                    if progress.get("continue_count", 0) >= _MAX_AUTO_CONTINUE:
                        logger.warning(
                            "⚠️ 整份优化续跑达上限，跳过一致性审阅直接收尾"
                        )
                        ResumeDataStore.finish_progress(self._session_id)
                    else:
                        ResumeDataStore.mark_review_dispatched(self._session_id)
                        ResumeDataStore.bump_continue_count(self._session_id)
                        yield AutoContinueEvent(
                            message="进入最终一致性审阅",
                            reason="reviewing",
                            next_user_input=f"{AUTO_CONTINUE_PREFIX}进入最终一致性审阅",
                            session_id=self._session_id,
                        )
                else:
                    # review_dispatched 已经是 True，说明这次请求本身就是那次
                    # 独立派发的审阅请求，正常跑完，任务真正结束。
                    ResumeDataStore.finish_progress(self._session_id)

            # Completed state
            await self._state_machine.transition_to(
                AgentState.COMPLETED,
                message="Agent execution completed",
            )

            yield AgentEndEvent(
                agent_name="Manus",
                success=True,
                session_id=self._session_id,
            )

        except Exception as e:
            logger.exception(f"Error during agent execution: {e}")
            await self._state_machine.handle_error(e)
            # 整份优化任务：本次请求循环内抛异常直接跳到这里，跳过了循环
            # 之后的进度可见文案/auto_continue 判断——任务在 progress 里还是
            # optimizing/reviewing，但用户只会看到一条"运行失败"，看不出
            # 任务其实还活着、下次说"继续优化"能接着做（独立 review round5
            # 发现：这是另一种误导性完成态，跟 stuck/达上限那两种是同类问题）。
            # 不强制 finish_progress——异常大概率是这一步的瞬时问题，留着
            # 任务状态，让用户下次明确说"继续优化"时能凭 progress 复原。
            _err_progress = ResumeDataStore.get_progress(self._session_id)
            _err_note = self._build_optimize_progress_note(_err_progress)
            # 用户永远不该看到内部异常 repr（如 RetryError[<Future ...>]）——
            # 映射为可读文案，真实异常类型进 error_type，完整堆栈已在上方
            # logger.exception 里（2026-07-16 实测修复）。
            error_message, real_error_type = user_facing_error_message(e)
            if _err_note:
                error_message = f"{error_message}\n\n{_err_note}"
            friendly_error = "刚才这一步没有顺利跑完，我保留了当前进度。你可以稍后重试一次。"
            if _err_note:
                friendly_error = f"{friendly_error}\n\n{_err_note}"
            recovery_step = max(1, self.agent.current_step)
            yield ThoughtEvent(
                thought=(
                    "这一步没有拿到可靠结果，我先停在这里，避免把不完整内容当成完成。"
                    "现有进度会保留，下一次可以从这里继续。"
                ),
                step_id=recovery_step,
                session_id=self._session_id,
                node_id=f"error-recovery:{recovery_step}",
                phase="error_recovery",
            )
            complete_error = self._build_complete_answer_event(friendly_error)
            if complete_error:
                yield complete_error
            if self._chat_history_manager:
                self._chat_history_manager.add_message(
                    Message.assistant_message(friendly_error)
                )
            yield AgentErrorEvent(
                error_message=error_message,
                error_type=type(e).__name__,
                session_id=self._session_id,
            )

    async def send_event(self, event: StreamEvent) -> None:
        """Send an event to the client.

        Args:
            event: The event to send
        """
        try:
            task = self._send_event(event.to_dict())
            await asyncio.gather(task, return_exceptions=True)
        except Exception as e:
            logger.error(f"Error sending event: {e}")


class StreamProcessor:
    """Processes streaming agent output for multiple clients.

    Features:
    - Manage multiple active streams
    - Route events to correct clients
    - Handle stream lifecycle
    """

    def __init__(self) -> None:
        """Initialize the stream processor."""
        self._active_streams: dict[str, AgentStream] = {}
        self._lock = asyncio.Lock()

    async def start_stream(
        self,
        session_id: str,
        agent: Manus,
        state_machine: AgentStateMachine,
        event_sender: EventSender,
        user_message: str,
        chat_history_manager: Optional[Any] = None,
    ) -> AsyncIterator[StreamEvent]:
        """Start a new agent stream.

        Args:
            session_id: Unique session identifier
            agent: The Manus agent instance
            state_machine: The state machine for tracking
            event_sender: Function to send events
            user_message: The user's input
            chat_history_manager: Optional chat history manager

        Yields:
            StreamEvent instances during execution
        """
        if is_pi_core_enabled():
            from backend.agent.pi_core.stream import PiCoreAgentStream

            stream = PiCoreAgentStream(
                agent,
                session_id,
                state_machine,
                chat_history_manager,
            )
            logger.info(
                "[StreamProcessor] RESUME_AGENT_PI_CORE=true; "
                "using linear pi-core adapter for session %s",
                session_id,
            )
        else:
            stream = AgentStream(
                agent,
                session_id,
                state_machine,
                event_sender,
                chat_history_manager,
            )

        async with self._lock:
            self._active_streams[session_id] = stream

        # Execute stream and yield events
        try:
            async for event in stream.execute(user_message):
                yield event
        finally:
            await self.remove_stream(session_id)

    async def remove_stream(self, session_id: str) -> None:
        """Remove a completed stream.

        Args:
            session_id: The session ID whose stream to remove
        """
        async with self._lock:
            self._active_streams.pop(session_id, None)

    def has_active_stream(self, session_id: str) -> bool:
        """Check if a session has an active stream.

        Args:
            session_id: The session ID to check

        Returns:
            True if stream is active
        """
        return session_id in self._active_streams

    def get_stream(self, session_id: str) -> Optional[AgentStream]:
        """Get an active stream.

        Args:
            session_id: The session ID

        Returns:
            The AgentStream if active, None otherwise
        """
        return self._active_streams.get(session_id)

    async def stop_stream(self, session_id: str, reason: str = "manual") -> bool:
        """Request a stream to stop.

        Args:
            session_id: The session ID whose stream to stop
            reason: Reason for stopping (e.g., "manual", "session_switch")

        Returns:
            True if stream was found and stop requested
        """
        stream = self.get_stream(session_id)
        if stream:
            stream._state_machine.request_stop(reason=reason)
            return True
        return False
