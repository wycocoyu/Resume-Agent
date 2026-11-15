"""
LangChain-style Memory System - Complete implementation for resume agent

This is a complete implementation inspired by LangChain's Memory design,
with in-memory storage for the resume optimization use case.
"""

from backend.agent.memory.langchain.messages import (
    BaseMessage,
    BaseMessageChunk,
    HumanMessage,
    HumanMessageChunk,
    AIMessage,
    AIMessageChunk,
    SystemMessage,
    SystemMessageChunk,
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
    merge_content,
)
from backend.agent.memory.langchain.messages.utils import (
    message_to_dict,
    messages_to_dict,
    messages_from_dict,
    get_buffer_string,
    trim_messages,
)
from backend.agent.memory.langchain.chat_history import (
    BaseChatMessageHistory,
    InMemoryChatMessageHistory,
)

__all__ = [
    # Messages
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
    # Tool calls
    "ToolCall",
    "ToolCallChunk",
    "InvalidToolCall",
    "tool_call",
    "tool_call_chunk",
    "invalid_tool_call",
    "default_tool_parser",
    "default_tool_chunk_parser",
    # Utilities
    "merge_content",
    "message_to_dict",
    "messages_to_dict",
    "messages_from_dict",
    "get_buffer_string",
    "trim_messages",
    # Chat history
    "BaseChatMessageHistory",
    "InMemoryChatMessageHistory",
]
