import json
import asyncio
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, List, Optional, Union

from pydantic import BaseModel, Field, PrivateAttr, model_validator

from backend.agent.llm import LLM
from backend.agent.application.public_reasoning import PublicReasoning
from backend.core.logger import get_logger

logger = get_logger(__name__)
from backend.agent.prompt.toolcall import NEXT_STEP_PROMPT, SYSTEM_PROMPT
from backend.agent.schema import (
    ROLE_TYPE,
    TOOL_CHOICE_TYPE,
    AgentState,
    Memory,
    Message,
    ToolCall,
    ToolChoice,
)
from backend.agent.tool import CreateChatCompletion, Terminate, ToolCollection
from backend.agent.tool.base import ToolProgress


TOOL_CALL_REQUIRED = "Tool calls required but none provided"


@dataclass
class ToolBatchControl:
    """Control signals shared by one legacy tool batch."""

    pending_approval: bool = False
    waiting_for_user: bool = False


class ToolExecutionRuntime(BaseModel):
    """Base agent class for handling tool/function calls with enhanced abstraction

    核心设计原则：
    1. 自动终止：当 LLM 返回纯文本回答（无 tool_calls）时，自动终止
    2. 避免重复：跟踪已处理的用户输入，避免重复添加提示词
    3. 灵活扩展：子类可以通过重写 should_auto_terminate() 自定义终止逻辑
    """

    name: str = "toolcall"
    description: str = "an agent that can execute tool calls."

    system_prompt: str = SYSTEM_PROMPT
    next_step_prompt: str = NEXT_STEP_PROMPT

    available_tools: ToolCollection = ToolCollection(
        CreateChatCompletion(), Terminate()
    )
    tool_choices: TOOL_CHOICE_TYPE = ToolChoice.AUTO  # type: ignore
    special_tool_names: List[str] = Field(default_factory=lambda: [Terminate().name])

    tool_calls: List[ToolCall] = Field(default_factory=list)
    _current_base64_image: Optional[str] = None

    max_steps: int = 30
    max_observe: Optional[Union[int, bool]] = None

    llm: Optional[LLM] = Field(default_factory=LLM)
    memory: Memory = Field(default_factory=Memory)
    state: AgentState = AgentState.IDLE
    current_step: int = 0
    duplicate_threshold: int = 2

    class Config:
        arbitrary_types_allowed = True
        extra = "allow"

    @model_validator(mode="after")
    def initialize_runtime(self) -> "ToolExecutionRuntime":
        if self.llm is None or not isinstance(self.llm, LLM):
            self.llm = LLM(config_name=self.name.lower())
        if not isinstance(self.memory, Memory):
            self.memory = Memory()
        return self

    @property
    def messages(self) -> List[Message]:
        return self.memory.messages

    @messages.setter
    def messages(self, value: List[Message]) -> None:
        self.memory.messages = value

    def update_memory(
        self,
        role: ROLE_TYPE,
        content: str,
        base64_image: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        message_map = {
            "user": Message.user_message,
            "system": Message.system_message,
            "assistant": Message.assistant_message,
            "tool": lambda value, **kw: Message.tool_message(value, **kw),
        }
        if role not in message_map:
            raise ValueError(f"Unsupported message role: {role}")
        message_kwargs = {"base64_image": base64_image, **(kwargs if role == "tool" else {})}
        self.memory.add_message(message_map[role](content, **message_kwargs))

    @asynccontextmanager
    async def state_context(self, new_state: AgentState):
        if not isinstance(new_state, AgentState):
            raise ValueError(f"Invalid state: {new_state}")
        previous_state = self.state
        self.state = new_state
        try:
            yield
        except Exception:
            self.state = AgentState.ERROR
            raise
        finally:
            self.state = previous_state

    def handle_stuck_state(self) -> None:
        stuck_prompt = (
            "Observed duplicate responses. Consider new strategies and avoid "
            "repeating ineffective paths already attempted."
        )
        self.next_step_prompt = f"{stuck_prompt}\n{self.next_step_prompt}"
        logger.warning("Agent detected stuck state. Added prompt: {}", stuck_prompt)

    def is_stuck(self) -> bool:
        if len(self.memory.messages) < 2:
            return False
        last_message = self.memory.messages[-1]
        if not last_message.content:
            return False
        duplicate_count = sum(
            1
            for msg in reversed(self.memory.messages[:-1])
            if msg.role == "assistant" and msg.content == last_message.content
        )
        return duplicate_count >= self.duplicate_threshold

    # 🔑 新增：跟踪状态，避免重复处理
    _last_processed_user_input: str = PrivateAttr(default="")
    _pending_next_step: bool = PrivateAttr(default=False)  # 是否有待处理的 next_step
    _tool_structured_results: dict[str, Any] = PrivateAttr(default_factory=dict)
    _tool_batch_control: ToolBatchControl = PrivateAttr(
        default_factory=ToolBatchControl
    )
    _stream_content_callback: Optional[Callable[[str], Awaitable[None]]] = PrivateAttr(default=None)
    _stream_cancel_event: Optional[asyncio.Event] = PrivateAttr(default=None)
    _public_reasoning_callback: Optional[
        Callable[[PublicReasoning], Awaitable[None]]
    ] = PrivateAttr(default=None)
    _tool_start_callback: Optional[
        Callable[[ToolCall, dict[str, Any]], Awaitable[None]]
    ] = PrivateAttr(default=None)

    def set_stream_content_callback(
        self,
        callback: Optional[Callable[[str], Awaitable[None]]],
        cancel_event: Optional[asyncio.Event] = None,
    ) -> None:
        self._stream_content_callback = callback
        self._stream_cancel_event = cancel_event

    def clear_stream_content_callback(self) -> None:
        self._stream_content_callback = None
        self._stream_cancel_event = None

    def set_public_reasoning_callback(
        self,
        callback: Optional[Callable[[PublicReasoning], Awaitable[None]]],
    ) -> None:
        self._public_reasoning_callback = callback

    def clear_public_reasoning_callback(self) -> None:
        self._public_reasoning_callback = None

    def set_tool_start_callback(
        self,
        callback: Optional[Callable[[ToolCall, dict[str, Any]], Awaitable[None]]],
    ) -> None:
        """Register the stream handoff used before a tool starts executing."""
        self._tool_start_callback = callback

    def clear_tool_start_callback(self) -> None:
        self._tool_start_callback = None

    async def emit_tool_start(self, command: ToolCall, args: dict[str, Any]) -> None:
        """Wait until the streaming layer has exposed the running tool card."""
        if self._tool_start_callback:
            await self._tool_start_callback(command, args)

    async def emit_public_reasoning(self, update: PublicReasoning) -> None:
        if self._public_reasoning_callback:
            await self._public_reasoning_callback(update)

    @staticmethod
    def _sanitize_log_text(text: str) -> str:
        """Escape loguru tag delimiters to avoid log formatting errors."""
        return text.replace("<", r"\<").replace(">", r"\>")

    def _get_last_user_message(self) -> str:
        for msg in reversed(self.messages):
            role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            if role == "user" and msg.content:
                return msg.content.strip()
        return ""

    # 有专属解析分支的老工具(行为保持不变);名单外的一切工具走下面的通用透传
    _LEGACY_STRUCTURED_TOOLS = {
        "show_resume", "cv_editor_agent", "cv_reader_agent", "generate_resume",
    }

    def _store_structured_tool_result(
        self, tool_call_id: str, tool_name: str, result: Any
    ) -> None:
        if not tool_call_id:
            return
        # 显式结构化通道优先:工具直接给 ToolResult.structured_data,不再 JSON 编码进
        # system 旁路;下面的 system 解析分支保留作未迁移工具的 fallback(兼容迁移)
        explicit = getattr(result, "structured_data", None)
        if isinstance(explicit, dict) and explicit.get("type"):
            structured = dict(explicit)
            if tool_name in {"show_resume", "cv_editor_agent", "cv_reader_agent"}:
                # 与 legacy 分支同款的意图元信息补齐
                intent_meta = getattr(self, "_last_intent_info", {}) or {}
                structured.setdefault("source", tool_name)
                structured.setdefault("trigger", intent_meta.get("trigger", "unknown"))
                structured.setdefault(
                    "intent_source", intent_meta.get("intent_source", "unknown")
                )
            self._tool_structured_results[tool_call_id] = structured
            return
        if tool_name not in self._LEGACY_STRUCTURED_TOOLS:
            # 通用透传:任意工具把 {type, ...} JSON 放进 ToolResult.system 即可直达前端,
            # 不再需要逐工具开白名单;解析失败记日志而非静默丢弃
            raw = getattr(result, "system", None)
            if not raw:
                return
            try:
                structured = json.loads(raw) if isinstance(raw, str) else raw
            except (ValueError, TypeError) as exc:
                logger.warning(
                    f"[structured] 工具 {tool_name} 的 system 字段不是合法 JSON,已丢弃: {exc}"
                )
                return
            if not isinstance(structured, dict) or not structured.get("type"):
                logger.warning(
                    f"[structured] 工具 {tool_name} 的 system 字段缺少 type,已丢弃"
                )
                return
            self._tool_structured_results[tool_call_id] = structured
            return
        if tool_name == "show_resume":
            try:
                intent_meta = getattr(self, "_last_intent_info", {}) or {}
                intent_source = intent_meta.get("intent_source", "unknown")
                trigger = intent_meta.get("trigger", "unknown")
                from backend.agent.tool.resume_data_store import ResumeDataStore

                resume_data = ResumeDataStore.get_data(getattr(self, "session_id", None))
                if not resume_data:
                    self._tool_structured_results[tool_call_id] = {
                        "type": "resume_selector",
                        "required": True,
                        "message": "Please choose a resume: create new or select existing.",
                        "source": "show_resume",
                        "trigger": trigger,
                        "intent_source": intent_source,
                    }
                    return

                meta = resume_data.get("_meta") or {}
                basics = resume_data.get("basic") or resume_data.get("basics") or {}
                resume_name = basics.get("name") or "我的简历"
                resume_id = resume_data.get("resume_id") or resume_data.get("id") or meta.get("resume_id")
                user_id = resume_data.get("user_id") or meta.get("user_id")

                self._tool_structured_results[tool_call_id] = {
                    "type": "resume",
                    "resume_id": resume_id,
                    "user_id": user_id,
                    "name": resume_name,
                    "resume_data": resume_data,
                    "source": "show_resume",
                    "trigger": trigger,
                    "intent_source": intent_source,
                }
            except Exception:
                return
            return

        if tool_name == "cv_editor_agent":
            try:
                # 约定：CVEditorAgentTool 将 structured_data 编码在 ToolResult.system 中
                raw_structured = getattr(result, "system", None)
                if not raw_structured:
                    return
                if isinstance(raw_structured, str):
                    structured = json.loads(raw_structured)
                elif isinstance(raw_structured, dict):
                    structured = raw_structured
                else:
                    return
                if not isinstance(structured, dict):
                    return
                if structured.get("type") not in {"resume_edit_diff", "resume_patch"}:
                    return
                intent_meta = getattr(self, "_last_intent_info", {}) or {}
                structured.setdefault("source", "cv_editor_agent")
                structured.setdefault("trigger", intent_meta.get("trigger", "unknown"))
                structured.setdefault("intent_source", intent_meta.get("intent_source", "unknown"))
                self._tool_structured_results[tool_call_id] = structured
            except Exception:
                return

        if tool_name == "cv_reader_agent":
            try:
                # 约定：CVReaderAgentTool 将 structured_data 编码在 ToolResult.system 中
                raw_structured = getattr(result, "system", None)
                if not raw_structured:
                    return
                if isinstance(raw_structured, str):
                    structured = json.loads(raw_structured)
                elif isinstance(raw_structured, dict):
                    structured = raw_structured
                else:
                    return
                if not isinstance(structured, dict):
                    return
                # 支持两种类型: resume_data 和 resume_structure
                if structured.get("type") not in {"resume_data", "resume_structure"}:
                    return
                intent_meta = getattr(self, "_last_intent_info", {}) or {}
                structured.setdefault("source", "cv_reader_agent")
                structured.setdefault("trigger", intent_meta.get("trigger", "unknown"))
                structured.setdefault("intent_source", intent_meta.get("intent_source", "unknown"))
                self._tool_structured_results[tool_call_id] = structured
            except Exception:
                return

        if tool_name == "generate_resume":
            try:
                # 约定：GenerateResumeTool 将 structured_data 编码在 ToolResult.system 中
                raw_structured = getattr(result, "system", None)
                if not raw_structured:
                    return
                if isinstance(raw_structured, str):
                    structured = json.loads(raw_structured)
                elif isinstance(raw_structured, dict):
                    structured = raw_structured
                else:
                    return
                if not isinstance(structured, dict):
                    return
                if structured.get("type") != "resume_generated":
                    return
                self._tool_structured_results[tool_call_id] = structured
            except Exception:
                return

    def capture_structured_tool_result(
        self, tool_call_id: str, tool_name: str, result: Any
    ) -> None:
        """Public Pi Core boundary for structured UI payloads."""

        self._store_structured_tool_result(tool_call_id, tool_name, result)

    def get_structured_tool_result(self, tool_call_id: str) -> dict[str, Any] | None:
        return self._tool_structured_results.get(tool_call_id)

    def consume_structured_tool_result(
        self,
        tool_call_id: str,
    ) -> dict[str, Any] | None:
        """Return and remove one structured result from the compatibility cache.

        The legacy SSE path may need to inspect a result more than once, so the
        historical getter remains non-consuming.  Pi Core owns the new
        one-shot execution path and uses this method to prevent structured UI
        payloads from accumulating for the lifetime of a session.
        """

        return self._tool_structured_results.pop(tool_call_id, None)

    def should_auto_terminate(self, content: str, tool_calls: List[ToolCall]) -> bool:
        """判断是否应该自动终止

        子类可以重写此方法来自定义终止逻辑。
        默认行为：当 LLM 返回纯文本内容（无 tool_calls）时自动终止。

        Args:
            content: LLM 返回的文本内容
            tool_calls: LLM 返回的工具调用列表

        Returns:
            True 表示应该自动终止，False 表示继续执行
        """
        # 如果有工具调用，不自动终止
        if tool_calls:
            return False

        # 如果有内容但没有工具调用，自动终止（纯文本回答）
        if content and content.strip():
            return True

        return False

    def _should_add_next_step_prompt(self) -> bool:
        """判断是否应该添加 next_step_prompt

        避免重复添加相同的提示词，导致消息膨胀。

        Returns:
            True 表示应该添加，False 表示跳过
        """
        if not self.next_step_prompt:
            return False

        # 检查最后一条用户消息是否已经是这个 prompt
        for msg in reversed(self.messages[-3:]):
            if isinstance(msg, Message):
                role = msg.role.value if hasattr(msg.role, 'value') else str(msg.role)
            else:
                role = msg.get('role', '')

            if role == 'user':
                content = msg.content if isinstance(msg, Message) else msg.get('content', '')
                # 如果最近的用户消息就是 next_step_prompt，跳过添加
                if content and content.strip() == self.next_step_prompt.strip():
                    return False
                break

        return True

    async def execute_tool(self, command: ToolCall) -> str:
        """Execute a single tool call with robust error handling"""
        if not command or not command.function or not command.function.name:
            return "Error: Invalid command format"

        name = command.function.name
        if name not in self.available_tools.tool_map:
            return f"Error: Unknown tool '{name}'"

        try:
            # Parse arguments
            args = json.loads(command.function.arguments or "{}")

            # 运行时确认协议:requires_approval 工具不在这里执行——登记挂起、
            # 推 approval_request 确认卡,由 approval 端点在用户批准后执行。
            # LLM 传入的 _approved 之类标记一律剥除,模型无法绕过这道门。
            if isinstance(args, dict):
                args.pop("_approved", None)
                # 部分模型会给无参数工具塞一个 `_noargs` 占位字段。它不是业务
                # 参数，若原样传给 execute() 会先报一次 TypeError 再重试，拖慢
                # list_resumes 等入口工具。
                args.pop("_noargs", None)
            tool_obj = self.available_tools.tool_map.get(name)
            if tool_obj is not None and getattr(tool_obj, "requires_approval", False):
                return self._suspend_for_approval(command.id, name, tool_obj, args)

            # Hand the running state to the stream before execution starts.  The
            # callback acknowledges only after ToolCallEvent has been yielded,
            # so the UI timeline reflects the real lifecycle instead of replaying
            # a completed call post-hoc.
            await self.emit_tool_start(command, args)

            # Execute the tool
            logger.info(f"🔧 Activating tool: '{name}'...")

            async def _on_tool_progress(update: ToolProgress) -> None:
                await self.emit_public_reasoning(
                    PublicReasoning(
                        content=update.content,
                        phase=update.phase,
                        node_id=(
                            f"tool-progress:{command.id}:{update.node_id}"
                            if update.node_id
                            else f"tool-progress:{command.id}"
                        ),
                        is_complete=update.is_complete,
                        tool_progress={
                            "tool_call_id": command.id,
                            "stage_id": update.node_id or "progress",
                            "current": update.current,
                            "total": update.total,
                            "label": update.label,
                            "summary": update.content,
                            "stages": list(update.stages),
                        },
                    )
                )

            progress_token = tool_obj.set_progress_callback(_on_tool_progress)
            try:
                result = await self.available_tools.execute(name=name, tool_input=args)
            finally:
                tool_obj.clear_progress_callback(progress_token)

            # Handle special tools
            await self._handle_special_tool(name=name, result=result)

            self._store_structured_tool_result(command.id, name, result)

            # Check if result is a ToolResult with base64_image
            if hasattr(result, "base64_image") and result.base64_image:
                # Store the base64_image for later use in tool_message
                self._current_base64_image = result.base64_image

            # Format result for display (standard case)
            observation = (
                f"Observed output of cmd `{name}` executed:\n{str(result)}"
                if result
                else f"Cmd `{name}` completed with no output"
            )

            return observation
        except json.JSONDecodeError:
            error_msg = f"Error parsing arguments for {name}: Invalid JSON format"
            logger.error(
                f"📝 Oops! The arguments for '{name}' don't make sense - invalid JSON, arguments:{command.function.arguments}"
            )
            return f"Error: {error_msg}"
        except Exception as e:
            error_msg = f"⚠️ Tool '{name}' encountered a problem: {str(e)}"
            logger.exception(error_msg)
            return f"Error: {error_msg}"

    def _suspend_for_approval(self, tool_call_id: str, name: str, tool_obj: Any, args: dict) -> str:
        """把 requires_approval 工具调用挂起:先跑确认前校验,通过则登记 pending
        并存 approval_request 结构化结果(经通用透传直达前端确认卡),本轮终止。"""
        from backend.agent import approval as approval_store

        try:
            validation_error = tool_obj.validate_before_approval(**args)
        except Exception as exc:
            validation_error = f"发送前校验失败:{exc}"
        if validation_error:
            logger.info(f"[approval] {name} 确认前校验未通过: {validation_error}")
            return f"Error: {validation_error}"

        approval_id = approval_store.create(
            session_id=self.session_id or "default",
            user_id=getattr(tool_obj, "user_id", None),
            tool_name=name,
            args=args,
        )
        payload = {
            "approval_id": approval_id,
            "tool_name": name,
            "args": args,
            "editable_fields": list(getattr(tool_obj, "approval_editable_fields", [])),
        }
        try:
            payload.update(tool_obj.approval_preview(**args) or {})
        except Exception as exc:
            logger.warning(f"[approval] {name} approval_preview 失败(忽略): {exc}")

        self._tool_structured_results[tool_call_id] = {
            "type": "approval_request",
            "payload": payload,
        }
        # 挂起后本轮确定性终止(不靠模型自觉),等待用户在确认卡上操作
        self._tool_batch_control.pending_approval = True
        logger.info(f"[approval] {name} 已挂起等待确认: {approval_id}")
        return (
            "已生成发送请求并展示确认卡,等待用户确认或修改。"
            "本轮到此结束,不要再调用任何工具。"
        )

    async def _handle_special_tool(self, name: str, result: Any, **kwargs):
        """Handle special tool execution and state changes"""
        if not self._is_special_tool(name):
            return

        if self._should_finish_execution(name=name, result=result, **kwargs):
            # Set agent state to finished
            logger.info(f"🏁 Special tool '{name}' has completed the task!")
            self.state = AgentState.FINISHED

    @staticmethod
    def _should_finish_execution(**kwargs) -> bool:
        """Determine if tool execution should finish the agent"""
        return True

    def _is_special_tool(self, name: str) -> bool:
        """Check if tool name is in special tools list"""
        return name.lower() in [n.lower() for n in self.special_tool_names]

    async def cleanup(self):
        """Clean up resources used by the agent's tools."""
        logger.info(f"🧹 Cleaning up resources for agent '{self.name}'...")
        for tool_name, tool_instance in self.available_tools.tool_map.items():
            if hasattr(tool_instance, "cleanup") and asyncio.iscoroutinefunction(
                tool_instance.cleanup
            ):
                try:
                    logger.debug(f"🧼 Cleaning up tool: {tool_name}")
                    await tool_instance.cleanup()
                except Exception as e:
                    logger.error(
                        f"🚨 Error cleaning up tool '{tool_name}': {e}", exc_info=True
                    )
        logger.info(f"✨ Cleanup complete for agent '{self.name}'.")

