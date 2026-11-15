"""
Message Adapter - Convert between resume agent and LangChain message formats
"""

import json
from typing import List

from backend.agent.memory.langchain.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
)
from backend.agent.schema import Message, Role, ToolCall, Function


def _convert_tool_calls_to_langchain_format(tool_calls: List[ToolCall] | None) -> List[dict]:
    """将 resume agent ToolCall 对象转换为 LangChain 期望的字典格式

    LangChain AIMessage 期望的 tool_calls 格式:
    [
        {
            "id": "call_xxx",
            "name": "tool_name",
            "args": {...}  # 必须是字典
        }
    ]
    """
    if not tool_calls:
        return []

    result = []
    for tc in tool_calls:
        # tc 是 resume agent 的 ToolCall 对象，包含 id, type, function
        args = tc.function.arguments

        # ✅ 如果 args 是 JSON 字符串，解析为字典
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                # 如果解析失败，保持原样或设为空字典
                args = {}

        tc_dict = {
            "id": tc.id,
            "name": tc.function.name,
            "args": args,  # 确保是字典
        }
        result.append(tc_dict)
    return result


def _convert_tool_calls_from_langchain_format(lc_tool_calls: List[dict] | None) -> List[ToolCall]:
    """将 LangChain 字典格式的 tool_calls 转换为 resume agent ToolCall 对象

    LangChain tool_calls 格式:
    [
        {
            "id": "call_xxx",
            "name": "tool_name",
            "args": {...}  # 字典
        }
    ]

    resume agent ToolCall 格式:
    [
        ToolCall(
            id="call_xxx",
            type="function",
            function=Function(
                name="tool_name",
                arguments="{...}"  # JSON 字符串
            )
        )
    ]
    """
    if not lc_tool_calls:
        return []

    result = []
    for tc in lc_tool_calls:
        # tc 是 LangChain 的字典格式
        tc_id = tc.get("id", "")
        tc_name = tc.get("name", "")
        tc_args = tc.get("args", {})

        # ✅ 如果 args 是字典，转换为 JSON 字符串
        if isinstance(tc_args, dict):
            tc_args = json.dumps(tc_args, ensure_ascii=False)
        elif not isinstance(tc_args, str):
            tc_args = str(tc_args)

        result.append(ToolCall(
            id=tc_id,
            type="function",
            function=Function(
                name=tc_name,
                arguments=tc_args
            )
        ))
    return result


class MessageAdapter:
    """Adapter for converting between resume agent Message and LangChain Message formats.

    Critical: Tool messages are now properly preserved to enable the optimization workflow:
    - Analysis results (cv_analyzer_agent) may contain optimization_suggestions JSON
    - These tool results must be preserved across conversation turns
    - When user says "优化", the agent needs to retrieve previous tool results
    """

    @staticmethod
    def to_langchain(message: Message) -> BaseMessage:
        """
        Convert resume agent Message to LangChain Message.

        Args:
            message: resume agent Message object

        Returns:
            LangChain BaseMessage (HumanMessage, AIMessage, SystemMessage, or ToolMessage)
        """
        content = message.content or ""
        extra = {"thought": message.thought} if message.thought else {}

        if message.role == Role.USER:
            return HumanMessage(
                content=content,
                id=getattr(message, "id", None),
                additional_kwargs=extra,
            )
        elif message.role == Role.ASSISTANT:
            # ✅ 将 resume agent ToolCall 对象转换为 LangChain 期望的字典格式
            lc_tool_calls = _convert_tool_calls_to_langchain_format(message.tool_calls)
            return AIMessage(
                content=content,
                tool_calls=lc_tool_calls,
                additional_kwargs=extra,
            )
        elif message.role == Role.SYSTEM:
            return SystemMessage(content=content, additional_kwargs=extra)
        elif message.role == Role.TOOL:
            # Preserve tool messages with their metadata
            return ToolMessage(
                content=content,
                tool_call_id=message.tool_call_id or "",
                name=message.name or "",
                additional_kwargs=extra,
            )
        else:
            # Fallback
            return AIMessage(content=content, additional_kwargs=extra)

    @staticmethod
    def from_langchain(lc_message: BaseMessage) -> Message:
        """
        Convert LangChain Message to resume agent Message.

        Args:
            lc_message: LangChain BaseMessage object

        Returns:
            resume agent Message object with all metadata preserved
        """
        thought = None
        if hasattr(lc_message, "additional_kwargs"):
            thought = (lc_message.additional_kwargs or {}).get("thought")

        if isinstance(lc_message, HumanMessage):
            role = Role.USER
            return Message(role=role, content=lc_message.content, thought=thought)
        elif isinstance(lc_message, AIMessage):
            role = Role.ASSISTANT
            # ✅ 将 LangChain 格式的 tool_calls 转换为 resume agent ToolCall 对象
            om_tool_calls = _convert_tool_calls_from_langchain_format(lc_message.tool_calls)
            return Message(
                role=role,
                content=lc_message.content,
                thought=thought,
                tool_calls=om_tool_calls if om_tool_calls else None,
            )
        elif isinstance(lc_message, SystemMessage):
            role = Role.SYSTEM
            return Message(role=role, content=lc_message.content, thought=thought)
        elif isinstance(lc_message, ToolMessage):
            role = Role.TOOL
            return Message(
                role=role,
                content=lc_message.content,
                thought=thought,
                tool_call_id=lc_message.tool_call_id or None,
                name=lc_message.name or None,
            )
        else:
            # Fallback
            return Message(role=Role.ASSISTANT, content=lc_message.content, thought=thought)

    @staticmethod
    def batch_to_langchain(messages: List[Message]) -> List[BaseMessage]:
        """Batch convert resume agent Messages to LangChain Messages."""
        return [MessageAdapter.to_langchain(msg) for msg in messages]

    @staticmethod
    def batch_from_langchain(lc_messages: List[BaseMessage]) -> List[Message]:
        """Batch convert LangChain Messages to resume agent Messages."""
        return [MessageAdapter.from_langchain(msg) for msg in lc_messages]
