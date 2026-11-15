"""
Chat History Manager - Wrapper around LangChain-style InMemoryChatMessageHistory

Provides resume agent-compatible interface for managing conversation history.
Implements LangChain-compatible sliding window mechanism.
"""

from typing import Any, List, Optional
from pathlib import Path
from datetime import datetime

from backend.agent.memory.langchain.chat_history import InMemoryChatMessageHistory
from backend.agent.memory.langchain.messages.utils import trim_messages
from backend.agent.schema import Message
from backend.agent.memory.message_adapter import MessageAdapter
from backend.core.logger import get_logger

logger = get_logger(__name__)


class ChatHistoryManager:
    """
    Chat history manager based on LangChain-style InMemoryChatMessageHistory.

    Features:
    - Sliding window (keep only last k messages) - LangChain compatible
    - Message format conversion (resume agent <-> LangChain)
    - Context retrieval for LLM prompting
    - Automatic trimming when messages exceed k limit
    """

    def __init__(
        self,
        k: int = 10,
        include_system: bool = True,
        session_id: Optional[str] = None,
        storage: Optional[Any] = None,
        user_id: Optional[str] = None,
        is_admin: bool = False,
    ):
        """
        Initialize the chat history manager.

        Args:
            k: Maximum number of messages to keep (default: 10).
                Note: This is the total number of messages, not conversation turns.
                A turn typically consists of 2+ messages (user + assistant + tool).
            include_system: Whether to preserve SystemMessage at index 0
                outside of the k limit (default: True).
            session_id: Optional session identifier for isolation/logging.
        """
        self.k = k
        self.include_system = include_system
        self.session_id = session_id or "default"
        self._history = InMemoryChatMessageHistory()
        self._storage = storage
        self._user_id = user_id
        self._is_admin = is_admin

    def _trim_history(self) -> None:
        """
        Apply sliding window to trim messages exceeding k limit.

        Uses LangChain's trim_messages with strategy='last' to keep
        the most recent messages while preserving SystemMessage if configured.
        """
        if len(self._history.messages) > self.k:
            trimmed = trim_messages(
                self._history.messages,
                max_messages=self.k,
                strategy="last",
                include_system=self.include_system,
            )
            # Update the internal messages list
            self._history._messages = trimmed
            logger.debug(
                f"✂️ ChatHistory[{self.session_id}]: Trimmed to {len(trimmed)} messages (k={self.k})"
            )

    def add_message(self, message: Message, persist: bool = True) -> None:
        """Add an resume agent Message to the history.

        After adding, automatically trims history if it exceeds k messages.

        Args:
            message: The message to add
            persist: Whether to persist after adding (default: True).
                    Set to False to batch multiple adds before persisting.
        """
        lc_message = MessageAdapter.to_langchain(message)
        self._history.add_message(lc_message)
        logger.debug(
            f"📝 ChatHistory[{self.session_id}]: Added {message.role} message "
            f"({len(message.content or '')} chars)"
        )

        # Apply sliding window
        self._trim_history()
        if persist:
            self._persist_if_needed()

    def add_messages(self, messages: List[Message], persist: bool = True) -> None:
        """Add multiple resume agent Messages to the history.

        After adding, automatically trims history if it exceeds k messages.

        Args:
            messages: List of messages to add
            persist: Whether to persist after adding (default: True).
                    Set to False to batch multiple adds before persisting.
        """
        lc_messages = MessageAdapter.batch_to_langchain(messages)
        self._history.add_messages(lc_messages)
        logger.debug(
            f"📝 ChatHistory[{self.session_id}]: Added {len(messages)} messages"
        )

        # Apply sliding window
        self._trim_history()
        if persist:
            self._persist_if_needed()

    def get_messages(self, max_messages: Optional[int] = None) -> List[Message]:
        """
        Get messages from the history.

        Args:
            max_messages: Optional maximum number of messages to return.
                If None, returns all messages (already trimmed by k).
                Uses trim_messages for consistent behavior.

        Returns:
            List of resume agent Messages
        """
        lc_messages = self._history.messages

        # If max_messages specified, use trim_messages for consistent trimming
        if max_messages is not None:
            lc_messages = trim_messages(
                lc_messages,
                max_messages=max_messages,
                strategy="last",
                include_system=self.include_system,
            )

        return MessageAdapter.batch_from_langchain(lc_messages)

    def get_recent_context(self, max_turns: int = 5) -> str:
        """
        Get recent conversation context as a string.

        Args:
            max_turns: Maximum number of turns to include (default: 5)
                A turn typically consists of 2 messages (user + assistant).

        Returns:
            Formatted conversation context string
        """
        # Use trim_messages for consistent behavior
        messages = self.get_messages(max_messages=max_turns * 2)
        if not messages:
            return ""

        context_parts = []
        for msg in messages:
            role_name = "用户" if msg.role == "user" else "AI"
            content = msg.content or ""
            if content:
                content = content[:100] + "..." if len(content) > 100 else content
                context_parts.append(f"{role_name}: {content}")

        return "\n".join(context_parts)

    def clear(self) -> None:
        """Clear all messages from the history."""
        self._history.clear()
        logger.debug(f"🧹 ChatHistory[{self.session_id}]: Cleared all messages")
        self._persist_if_needed()

    def clear_messages(self) -> None:
        """Backwards-compatible alias for clear()."""
        self.clear()

    def load_messages(self, messages: List[Message | dict[str, Any]]) -> None:
        """Replace current messages with provided list."""
        normalized: List[Message] = []
        for message in messages:
            if isinstance(message, Message):
                normalized.append(message)
            else:
                normalized.append(Message(**message))
        lc_messages = MessageAdapter.batch_to_langchain(normalized)
        self._history._messages = lc_messages
        self._trim_history()

    async def save_checkpoint(self) -> None:
        """Persist current history to storage."""
        self._persist_if_needed()

    async def restore_from_checkpoint(self) -> None:
        """Load history from storage if available."""
        if not self._storage:
            return
        loaded = self._storage.load_messages(
            self.session_id,
            user_id=self._user_id,
            is_admin=self._is_admin,
        )
        if loaded:
            self.load_messages(loaded)

    def export_to_file(self, export_path: str, fmt: str = "json") -> str:
        """Export current conversation to file."""
        if self._storage:
            return self._storage.export_session(
                self.session_id,
                export_path,
                fmt=fmt,
                user_id=self._user_id,
                is_admin=self._is_admin,
            )
        # Fallback export when storage is not configured
        data = {
            "session_id": self.session_id,
            "exported_at": datetime.now().isoformat(),
            "message_count": len(self._history.messages),
            "messages": [m.to_dict() for m in self.get_messages()],
        }
        path = Path(export_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "markdown":
            lines = [f"# Conversation {self.session_id}", ""]
            for msg in data["messages"]:
                lines.append(f"## {msg.get('role', 'assistant')}")
                lines.append(msg.get("content", "") or "")
                lines.append("")
            path.write_text("\n".join(lines), encoding="utf-8")
        else:
            import json

            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    @property
    def message_count(self) -> int:
        """Get the total number of messages in the history."""
        return len(self._history.messages)

    def _persist_if_needed(self) -> None:
        if not self._storage:
            return
        try:
            self._storage.save_session(
                self.session_id,
                self.get_messages(),
                user_id=self._user_id,
                is_admin=self._is_admin,
            )
        except Exception as exc:
            logger.warning(
                f"Failed to persist chat history for {self.session_id}: {exc}"
            )

