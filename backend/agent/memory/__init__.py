"""
resume agent Memory System - Based on LangChain design

This module provides a unified memory management system inspired by LangChain's
Memory architecture, adapted for the resume optimization use case.

Components:
- langchain: Complete LangChain-style message types and chat history implementation
- ChatHistoryManager: Wrapper for managing conversation history
- ConversationStateManager: Manages conversation state and intent recognition
- MessageAdapter: Converts between resume agent and LangChain message formats
- CheckpointSaver: Version snapshot and rollback mechanism
- EntityMemory: Entity extraction and memory for resume-related entities
"""

# LangChain-style components
from backend.agent.memory.langchain import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
    BaseChatMessageHistory,
    InMemoryChatMessageHistory,
)

# resume agent wrappers
from backend.agent.memory.chat_history_manager import ChatHistoryManager
from backend.agent.application.conversation.conversation_state import (
    ConversationStateManager,
    ConversationState,
    Intent,
    OptimizationContext,
    ConversationContext,
)
from backend.agent.memory.message_adapter import MessageAdapter
from backend.agent.memory.conversation_manager import ConversationManager

# New components
from backend.agent.memory.checkpoint_saver import (
    CheckpointSaver,
    Checkpoint,
    ResumeSnapshot,
    Operation,
    CheckpointMetadata,
)
from backend.agent.memory.entity_memory import (
    EntityMemory,
    Skill,
    Company,
    Project,
    Targets,
    ExtractedEntities,
    Association,
)

__all__ = [
    # LangChain-style components
    "BaseMessage",
    "HumanMessage",
    "AIMessage",
    "SystemMessage",
    "BaseChatMessageHistory",
    "InMemoryChatMessageHistory",
    # resume agent wrappers
    "ChatHistoryManager",
    "ConversationStateManager",
    "ConversationState",
    "Intent",
    "OptimizationContext",
    "ConversationContext",
    "MessageAdapter",
    "ConversationManager",
    # Checkpoint mechanism
    "CheckpointSaver",
    "Checkpoint",
    "ResumeSnapshot",
    "Operation",
    "CheckpointMetadata",
    # Entity memory
    "EntityMemory",
    "Skill",
    "Company",
    "Project",
    "Targets",
    "ExtractedEntities",
    "Association",
]
