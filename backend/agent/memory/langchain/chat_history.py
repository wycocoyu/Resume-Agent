"""
Chat History - Complete LangChain implementation for resume agent

This is a complete implementation of LangChain's chat history,
adapted for resume agent use case with in-memory storage.
"""

from typing import List, Sequence
from abc import ABC, abstractmethod
from backend.agent.memory.langchain.messages import BaseMessage, HumanMessage, AIMessage


class BaseChatMessageHistory(ABC):
    """Abstract base class for storing chat message history."""

    @property
    @abstractmethod
    def messages(self) -> List[BaseMessage]:
        """A property that returns a list of messages."""

    async def aget_messages(self) -> List[BaseMessage]:
        """Async version of getting messages."""
        return self.messages

    def add_user_message(self, message: HumanMessage | str) -> None:
        """Convenience method for adding a human message string to the store."""
        if isinstance(message, HumanMessage):
            self.add_message(message)
        else:
            self.add_message(HumanMessage(content=message))

    def add_ai_message(self, message: AIMessage | str) -> None:
        """Convenience method for adding an `AIMessage` string to the store."""
        if isinstance(message, AIMessage):
            self.add_message(message)
        else:
            self.add_message(AIMessage(content=message))

    def add_message(self, message: BaseMessage) -> None:
        """Add a Message object to the store."""
        if type(self).add_messages != BaseChatMessageHistory.add_messages:
            # This means that the sub-class has implemented an efficient add_messages
            # method, so we should use it.
            self.add_messages([message])
        else:
            msg = (
                "add_message is not implemented for this class. "
                "Please implement add_message or add_messages."
            )
            raise NotImplementedError(msg)

    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
        """Add a list of messages."""
        for message in messages:
            self.add_message(message)

    async def aadd_messages(self, messages: Sequence[BaseMessage]) -> None:
        """Async add a list of messages."""
        self.add_messages(messages)

    @abstractmethod
    def clear(self) -> None:
        """Remove all messages from the store."""

    async def aclear(self) -> None:
        """Async remove all messages from the store."""
        self.clear()


class InMemoryChatMessageHistory(BaseChatMessageHistory):
    """In memory implementation of chat message history.

    Stores messages in a memory list.
    """

    def __init__(self) -> None:
        """Initialize the in-memory chat message history."""
        self._messages: List[BaseMessage] = []

    @property
    def messages(self) -> List[BaseMessage]:
        """A list of messages stored in memory."""
        return self._messages

    async def aget_messages(self) -> List[BaseMessage]:
        """Async version of getting messages."""
        return self._messages

    def add_message(self, message: BaseMessage) -> None:
        """Add a message to the store."""
        self._messages.append(message)

    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
        """Add multiple messages to the store."""
        self._messages.extend(messages)

    async def aadd_messages(self, messages: Sequence[BaseMessage]) -> None:
        """Async add messages to the store."""
        self.add_messages(messages)

    def clear(self) -> None:
        """Clear all messages from the store."""
        self._messages = []

    async def aclear(self) -> None:
        """Async clear all messages from the store."""
        self.clear()


__all__ = ["BaseChatMessageHistory", "InMemoryChatMessageHistory"]
