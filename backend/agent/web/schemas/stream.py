"""SSE Stream request/response models.

This module defines the data models for SSE streaming API.
"""

from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
import uuid


class StreamRequest(BaseModel):
    """SSE stream request model.

    Attributes:
        prompt: User message to send to the agent
        conversation_id: Optional conversation ID for context
        resume_path: Optional path to resume file
    """
    prompt: Optional[str] = Field(None, description="User message to send to the agent")
    message: Optional[str] = Field(None, description="Alias for prompt")
    conversation_id: Optional[str] = Field(None, description="Conversation ID for context")
    resume_path: Optional[str] = Field(None, description="Path to resume file")
    resume_data: Optional[dict] = Field(None, description="Resume data payload")
    model: Optional[str] = Field(None, description="覆盖本次请求的 LLM 模型（白名单内）")
    run_id: Optional[str] = Field(None, description="客户端为本轮分配的唯一运行 ID")
    cursor: Optional[str] = Field(None, description="Cursor for resume/reconnect")
    resume: Optional[bool] = Field(False, description="Whether this is a resume request")
    history_messages: Optional[list[dict[str, Any]]] = Field(
        None,
        description="Optional client-side history messages for anonymous/evicted session rehydration",
    )


class SSEEvent(BaseModel):
    """SSE event model for responses.

    Attributes:
        id: Unique event ID
        type: Event type (thought, answer, tool_call, etc.)
        data: Event data payload
        timestamp: Event timestamp
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str
    data: Any = None
    timestamp: datetime = Field(default_factory=datetime.now)

    def to_sse_format(self) -> str:
        """Convert event to SSE format string.

        Returns:
            SSE formatted string: "id: {id}\ndata: {json}\n\n"
        """
        import json
        event_dict = {
            "id": self.id,
            "type": self.type,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }
        return f"id: {self.id}\ndata: {json.dumps(event_dict, ensure_ascii=False)}\n\n"


class HeartbeatEvent(BaseModel):
    """Heartbeat event for keeping SSE connection alive.

    Attributes:
        id: Unique event ID
        type: Always "heartbeat"
        timestamp: Event timestamp
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str = "heartbeat"
    timestamp: datetime = Field(default_factory=datetime.now)

    def to_sse_format(self) -> str:
        """Convert heartbeat to SSE format string."""
        import json
        event_dict = {
            "id": self.id,
            "type": self.type,
            "timestamp": self.timestamp.isoformat(),
        }
        return f"id: {self.id}\ndata: {json.dumps(event_dict, ensure_ascii=False)}\n\n"


