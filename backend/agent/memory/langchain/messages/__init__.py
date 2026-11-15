"""Message types - Complete LangChain implementation for resume agent."""

from backend.agent.memory.langchain.messages.base import BaseMessage, BaseMessageChunk, merge_content
from backend.agent.memory.langchain.messages.human import HumanMessage, HumanMessageChunk
from backend.agent.memory.langchain.messages.ai import AIMessage, AIMessageChunk
from backend.agent.memory.langchain.messages.system import SystemMessage, SystemMessageChunk
from backend.agent.memory.langchain.messages.tool import (
    ToolMessage,
    ToolMessageChunk,
    ToolCall,
    ToolCallChunk,
    InvalidToolCall,
    tool_call,
    tool_call_chunk,
    invalid_tool_call,
    default_tool_parser,
    default_tool_chunk_parser,
)
from backend.agent.memory.langchain.messages.utils import trim_messages

__all__ = [
    "BaseMessage",
    "BaseMessageChunk",
    "HumanMessage",
    "HumanMessageChunk",
    "AIMessage",
    "AIMessageChunk",
    "SystemMessage",
    "SystemMessageChunk",
    "ToolMessage",
    "ToolMessageChunk",
    "ToolCall",
    "ToolCallChunk",
    "InvalidToolCall",
    "tool_call",
    "tool_call_chunk",
    "invalid_tool_call",
    "default_tool_parser",
    "default_tool_chunk_parser",
    "merge_content",
    "trim_messages",
]
