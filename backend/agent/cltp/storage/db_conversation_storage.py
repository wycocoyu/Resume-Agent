"""
Database-backed conversation storage adapter.

Stores session history in SQL tables for persistence and queryability.
"""

from __future__ import annotations

import json
import logging
import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.agent.schema import Message, Role
from sqlalchemy import inspect, text

try:
    from backend.database import SessionLocal, engine
    from backend.models import AgentConversation, AgentMessage
except ImportError:
    from database import SessionLocal, engine
    from models import AgentConversation, AgentMessage

from backend.agent.cltp.storage.conversation_storage import ConversationMeta
from backend.agent.cltp.storage.session_scope import SessionAccessError
from backend.agent.cltp.storage.session_limits import ensure_can_create_session
from backend.agent.pi_core.durable import DurableSessionStore

logger = logging.getLogger(__name__)


class DBConversationStorage:
    """Database-backed conversation storage adapter."""
    _supports_message_hash: Optional[bool] = None

    def __init__(self, durable_root: Optional[str] = None) -> None:
        """Initialize DB storage and its file-backed durable sidecar.

        The sidecar deliberately avoids a schema migration: the relational
        database remains the source of truth for chat messages while the
        durable document keeps session-scoped resume state recoverable.
        """

        root = (
            durable_root
            or os.getenv("AGENT_DB_DURABLE_ROOT")
            or "data/db-conversations/.durable"
        )
        self._durable = DurableSessionStore(root)

    def _durable_payload(self, conversation: AgentConversation) -> Dict[str, Any]:
        from backend.agent.tool.resume_data_store import ResumeDataStore

        return {
            "session_id": conversation.session_id,
            "user_id": conversation.user_id,
            "created_at": (
                conversation.created_at.isoformat()
                if conversation.created_at
                else ""
            ),
            "updated_at": (
                conversation.updated_at.isoformat()
                if conversation.updated_at
                else ""
            ),
            "title": conversation.title or "Conversation",
            "message_count": conversation.message_count or 0,
            "resume_state": ResumeDataStore.snapshot(conversation.session_id),
        }

    def _sync_durable_snapshot(
        self,
        conversation: AgentConversation,
        *,
        event_kind: str,
    ) -> None:
        """Persist the latest resume sidecar after a successful DB operation."""

        payload = self._durable_payload(conversation)
        try:
            with self._durable.transaction(conversation.session_id) as transaction:
                transaction.append(
                    event_kind,
                    {
                        "message_count": payload["message_count"],
                        "updated_at": payload["updated_at"],
                    },
                )
                transaction.set_document(payload)
        except Exception:
            # The DB commit has already succeeded; sidecar failure must not
            # turn a durable conversation write into a false API failure.
            logger.exception(
                "[AgentStorage] Failed to sync durable session sidecar: "
                "session_id=%s",
                conversation.session_id,
            )

    def _restore_durable_snapshot(
        self,
        session_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        from backend.agent.tool.resume_data_store import ResumeDataStore

        document = self._durable.read_document(session_id)
        resume_state = document.content.get("resume_state") if document else None
        if resume_state is not None:
            payload["resume_state"] = resume_state
            ResumeDataStore.restore_snapshot(session_id, resume_state)
        return payload

    def _repair_durable_snapshot_if_stale(
        self,
        session_id: str,
        payload: Dict[str, Any],
    ) -> None:
        """Best-effort read-repair for DB/sidecar divergence.

        The relational transaction remains the source of truth.  If a process
        crash or transient filesystem failure happened after the DB commit but
        before the sidecar write, the next successful read re-materializes the
        durable document instead of leaving the session permanently stale.
        """

        document = self._durable.read_document(session_id)
        expected_updated_at = str(payload.get("updated_at") or "")
        current_updated_at = ""
        if document:
            current_updated_at = str(document.content.get("updated_at") or "")
        expected_count = int(payload.get("message_count") or 0)
        current_count = (
            int(document.content.get("message_count") or 0)
            if document
            else -1
        )
        if (
            document is not None
            and current_updated_at == expected_updated_at
            and current_count == expected_count
        ):
            return
        try:
            conversation = type(
                "DurableConversationSnapshot",
                (),
                {
                    "session_id": session_id,
                    "user_id": payload.get("user_id"),
                    "created_at": (
                        datetime.fromisoformat(payload["created_at"])
                        if payload.get("created_at")
                        else None
                    ),
                    "updated_at": (
                        datetime.fromisoformat(payload["updated_at"])
                        if payload.get("updated_at")
                        else None
                    ),
                    "title": payload.get("title", "Conversation"),
                    "message_count": expected_count,
                },
            )()
            self._sync_durable_snapshot(
                conversation,
                event_kind="session_read_repair",
            )
        except Exception:
            logger.exception(
                "[AgentStorage] Failed to repair durable session sidecar: "
                "session_id=%s",
                session_id,
            )

    def validate_schema_or_raise(self) -> None:
        """Validate required DB schema for strict DB mode."""
        inspector = inspect(engine)
        required_tables = {"agent_conversations", "agent_messages"}
        existing_tables = set(inspector.get_table_names())
        missing_tables = sorted(required_tables - existing_tables)
        if missing_tables:
            raise RuntimeError(
                "DB_SCHEMA_MISMATCH: missing tables "
                f"{missing_tables}. action=RUN_ALEMBIC_UPGRADE"
            )

        required_columns = {
            "agent_conversations": {"id", "session_id", "title", "message_count"},
            "agent_messages": {
                "id",
                "conversation_id",
                "seq",
                "role",
                "content",
                "thought",
                "message_hash",
            },
        }
        for table, cols in required_columns.items():
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            missing_cols = sorted(cols - existing_cols)
            if missing_cols:
                raise RuntimeError(
                    "DB_SCHEMA_MISMATCH: missing columns "
                    f"{table}.{missing_cols}. action=RUN_ALEMBIC_UPGRADE"
                )

    def _schema_supports_message_hash(self) -> bool:
        if self._supports_message_hash is not None:
            return self._supports_message_hash
        try:
            inspector = inspect(engine)
            cols = {c["name"] for c in inspector.get_columns("agent_messages")}
            self._supports_message_hash = "message_hash" in cols
        except Exception:
            self._supports_message_hash = True
        return self._supports_message_hash

    def _is_message_hash_missing_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        missing_col = (
            "message_hash" in msg
            and (
                "no such column" in msg
                or "undefinedcolumn" in msg
                or "unknown column" in msg
            )
        )
        return missing_col

    def _ensure_json_value(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    def _message_to_legacy_params(self, conversation_pk: int, seq: int, message: Message) -> Dict[str, Any]:
        payload = self._serialize_message(message)
        role = payload.get("role")
        if isinstance(role, Role):
            role = role.value
        return {
            "conversation_id": conversation_pk,
            "seq": seq,
            "role": str(role or ""),
            "content": payload.get("content"),
            "thought": payload.get("thought"),
            "name": payload.get("name"),
            "tool_call_id": payload.get("tool_call_id"),
            "tool_calls": self._ensure_json_value(payload.get("tool_calls")),
            "base64_image": payload.get("base64_image"),
        }

    def _legacy_row_to_payload(self, row: Dict[str, Any]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"role": row.get("role", "")}
        if row.get("content") is not None:
            payload["content"] = row.get("content")
        if row.get("thought") is not None:
            payload["thought"] = row.get("thought")
        if row.get("name") is not None:
            payload["name"] = row.get("name")
        if row.get("tool_call_id") is not None:
            payload["tool_call_id"] = row.get("tool_call_id")
        tool_calls = row.get("tool_calls")
        if tool_calls is not None:
            if isinstance(tool_calls, str):
                try:
                    tool_calls = json.loads(tool_calls)
                except Exception:
                    pass
            payload["tool_calls"] = tool_calls
        if row.get("base64_image") is not None:
            payload["base64_image"] = row.get("base64_image")
        return payload

    def _message_signature(self, message: Message) -> Dict[str, Any]:
        payload = self._serialize_message(message)
        role = payload.get("role")
        if isinstance(role, Role):
            role = role.value
        return {
            "role": str(role or ""),
            "content": payload.get("content"),
            "thought": payload.get("thought"),
            "name": payload.get("name"),
            "tool_call_id": payload.get("tool_call_id"),
        }

    def _compute_message_hash(self, message: Message) -> str:
        sig = self._message_signature(message)
        raw = json.dumps(sig, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()

    def _row_signature(self, row: AgentMessage) -> Dict[str, Any]:
        return {
            "role": row.role or "",
            "content": row.content,
            "thought": row.thought,
            "name": row.name,
            "tool_call_id": row.tool_call_id,
        }

    def _snapshot_unchanged(
        self,
        db,
        conversation_id: int,
        messages: List[Message],
    ) -> bool:
        """Cheap idempotency check: compare count + first/last message signature."""
        existing_count = (
            db.query(AgentMessage)
            .filter(AgentMessage.conversation_id == conversation_id)
            .count()
        )
        incoming_count = len(messages)
        if existing_count != incoming_count:
            return False
        if incoming_count == 0:
            return True

        first_row = (
            db.query(AgentMessage)
            .filter(AgentMessage.conversation_id == conversation_id)
            .order_by(AgentMessage.seq.asc())
            .first()
        )
        last_row = (
            db.query(AgentMessage)
            .filter(AgentMessage.conversation_id == conversation_id)
            .order_by(AgentMessage.seq.desc())
            .first()
        )
        if not first_row or not last_row:
            return False

        first_incoming = self._message_signature(messages[0])
        last_incoming = self._message_signature(messages[-1])
        return self._row_signature(first_row) == first_incoming and self._row_signature(
            last_row
        ) == last_incoming

    def _rows_match_messages(self, rows: List[AgentMessage], messages: List[Message]) -> bool:
        if len(rows) != len(messages):
            return False
        for row, msg in zip(rows, messages):
            if self._row_signature(row) != self._message_signature(msg):
                return False
        return True

    def _serialize_message(self, message: Message) -> Dict[str, Any]:
        payload = message.to_dict()
        role = payload.get("role")
        if isinstance(role, Role):
            payload["role"] = role.value
        return payload

    def _deserialize_message(self, payload: Dict[str, Any]) -> Message:
        data = dict(payload)
        role = data.get("role")
        if isinstance(role, Role):
            data["role"] = role.value
        return Message(**data)

    def _derive_title(self, messages: List[Message]) -> str:
        def _first_non_empty(contents: List[Message], role: Optional[Role] = None) -> Optional[str]:
            for msg in contents:
                if role is not None and msg.role != role:
                    continue
                content = (msg.content or "").strip()
                if content:
                    return content
            return None

        title = _first_non_empty(messages, Role.USER)
        if not title:
            title = _first_non_empty(messages)
        return (title or "New Conversation")[:40]

    def _fetch_conversation_by_session(
        self, db, session_id: str, user_id: Optional[str] = None
    ) -> Optional[AgentConversation]:
        query = db.query(AgentConversation).filter(AgentConversation.session_id == session_id)
        if user_id is not None:
            query = query.filter(AgentConversation.user_id == user_id)
        return query.first()

    def _fetch_conversation_any(
        self, db, session_id: str
    ) -> Optional[AgentConversation]:
        return (
            db.query(AgentConversation)
            .filter(AgentConversation.session_id == session_id)
            .first()
        )

    def get_session_owner(self, session_id: str) -> Optional[int]:
        db = SessionLocal()
        try:
            conversation = self._fetch_conversation_any(db, session_id)
            return conversation.user_id if conversation else None
        finally:
            db.close()

    def _validate_conversation_owner(
        self,
        conversation: AgentConversation,
        user_id: Optional[str],
        *,
        is_admin: bool = False,
    ) -> None:
        if user_id is None:
            return
        if is_admin:
            return
        if conversation.user_id is None:
            raise SessionAccessError("SESSION_FORBIDDEN_OR_NOT_FOUND")
        if conversation.user_id != user_id:
            raise SessionAccessError("SESSION_FORBIDDEN_OR_NOT_FOUND")

    def _message_to_row(self, conversation_pk: int, seq: int, message: Message) -> AgentMessage:
        payload = self._serialize_message(message)
        role = payload.get("role")
        if isinstance(role, Role):
            role = role.value
        return AgentMessage(
            conversation_id=conversation_pk,
            seq=seq,
            role=str(role or ""),
            content=payload.get("content"),
            thought=payload.get("thought"),
            name=payload.get("name"),
            message_hash=self._compute_message_hash(message),
            tool_call_id=payload.get("tool_call_id"),
            tool_calls=payload.get("tool_calls"),
            base64_image=payload.get("base64_image"),
        )

    def _row_to_message(self, row: AgentMessage) -> Message:
        payload: Dict[str, Any] = {"role": row.role}
        if row.content is not None:
            payload["content"] = row.content
        if row.thought is not None:
            payload["thought"] = row.thought
        if row.name is not None:
            payload["name"] = row.name
        if row.tool_call_id is not None:
            payload["tool_call_id"] = row.tool_call_id
        if row.tool_calls is not None:
            payload["tool_calls"] = row.tool_calls
        if row.base64_image is not None:
            payload["base64_image"] = row.base64_image
        return self._deserialize_message(payload)

    def save_session(
        self,
        session_id: str,
        messages: List[Message],
        user_id: Optional[str] = None,
        *,
        is_admin: bool = False,
    ) -> ConversationMeta:
        if not self._schema_supports_message_hash():
            logger.warning(
                "[AgentStorage] DB schema missing agent_messages.message_hash; using legacy save path. "
                "Please run: python backend/create_tables.py"
            )
            return self._save_session_legacy(
                session_id, messages, user_id=user_id, is_admin=is_admin
            )

        now = datetime.now()
        db = SessionLocal()
        try:
            conversation = self._fetch_conversation_any(db, session_id)

            if conversation is None:
                ensure_can_create_session(
                    self, session_id, user_id, is_admin=is_admin
                )
                conversation = AgentConversation(
                    session_id=session_id,
                    user_id=user_id,
                    title=self._derive_title(messages),
                    message_count=len(messages),
                    created_at=now,
                    updated_at=now,
                    last_message_at=now if messages else None,
                )
                db.add(conversation)
                db.flush()
            else:
                if conversation.user_id is None and user_id is not None:
                    conversation.user_id = user_id
                self._validate_conversation_owner(
                    conversation, user_id, is_admin=is_admin
                )
                conversation.title = self._derive_title(messages)
                conversation.message_count = len(messages)
                conversation.updated_at = now
                conversation.last_message_at = now if messages else conversation.last_message_at

            snapshot_unchanged = self._snapshot_unchanged(
                db=db,
                conversation_id=conversation.id,
                messages=messages,
            )

            if not snapshot_unchanged:
                # Keep full-snapshot semantics for compatibility, but skip when unchanged.
                db.query(AgentMessage).filter(
                    AgentMessage.conversation_id == conversation.id
                ).delete(synchronize_session=False)

                for seq, message in enumerate(messages):
                    db.add(self._message_to_row(conversation.id, seq, message))

            db.commit()
            self._sync_durable_snapshot(
                conversation,
                event_kind="session_snapshot",
            )

            created_at = conversation.created_at or now
            updated_at = conversation.updated_at or now
            return ConversationMeta(
                session_id=conversation.session_id,
                created_at=created_at.isoformat(),
                updated_at=updated_at.isoformat(),
                title=conversation.title or "New Conversation",
                message_count=conversation.message_count or 0,
            )
        except Exception as exc:
            db.rollback()
            # Dual-insurance compatibility: retry without message_hash when schema is behind.
            if self._is_message_hash_missing_error(exc):
                logger.warning(
                    "[AgentStorage] save_session hit missing message_hash column; retrying legacy path. "
                    "Please run: python backend/create_tables.py"
                )
                self._supports_message_hash = False
                return self._save_session_legacy(
                    session_id, messages, user_id=user_id, is_admin=is_admin
                )
            raise
        finally:
            db.close()

    def _save_session_legacy(
        self,
        session_id: str,
        messages: List[Message],
        user_id: Optional[str] = None,
        *,
        is_admin: bool = False,
    ) -> ConversationMeta:
        now = datetime.now()
        db = SessionLocal()
        try:
            conversation = self._fetch_conversation_any(db, session_id)
            if conversation is None:
                ensure_can_create_session(
                    self, session_id, user_id, is_admin=is_admin
                )
                conversation = AgentConversation(
                    session_id=session_id,
                    user_id=user_id,
                    title=self._derive_title(messages),
                    message_count=len(messages),
                    created_at=now,
                    updated_at=now,
                    last_message_at=now if messages else None,
                )
                db.add(conversation)
                db.flush()
            else:
                if conversation.user_id is None and user_id is not None:
                    conversation.user_id = user_id
                self._validate_conversation_owner(
                    conversation, user_id, is_admin=is_admin
                )
                conversation.title = self._derive_title(messages)
                conversation.message_count = len(messages)
                conversation.updated_at = now
                conversation.last_message_at = now if messages else conversation.last_message_at

            db.execute(
                text("DELETE FROM agent_messages WHERE conversation_id = :conversation_id"),
                {"conversation_id": conversation.id},
            )
            insert_sql = text(
                """
                INSERT INTO agent_messages
                (conversation_id, seq, role, content, thought, name, tool_call_id, tool_calls, base64_image)
                VALUES
                (:conversation_id, :seq, :role, :content, :thought, :name, :tool_call_id, :tool_calls, :base64_image)
                """
            )
            for seq, message in enumerate(messages):
                db.execute(insert_sql, self._message_to_legacy_params(conversation.id, seq, message))

            db.commit()
            self._sync_durable_snapshot(
                conversation,
                event_kind="session_snapshot",
            )
            created_at = conversation.created_at or now
            updated_at = conversation.updated_at or now
            return ConversationMeta(
                session_id=conversation.session_id,
                created_at=created_at.isoformat(),
                updated_at=updated_at.isoformat(),
                title=conversation.title or "New Conversation",
                message_count=conversation.message_count or 0,
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def append_session_messages(
        self,
        session_id: str,
        base_seq: int,
        messages_delta: List[Message],
        user_id: Optional[str] = None,
        *,
        is_admin: bool = False,
    ) -> Dict[str, Any]:
        if not self._schema_supports_message_hash():
            logger.warning(
                "[AgentStorage] DB schema missing agent_messages.message_hash; using legacy append path. "
                "Please run: python backend/create_tables.py"
            )
            return self._append_session_messages_legacy(
                session_id, base_seq, messages_delta, user_id=user_id, is_admin=is_admin
            )

        now = datetime.now()
        db = SessionLocal()
        try:
            conversation = self._fetch_conversation_any(db, session_id)
            if conversation is None:
                ensure_can_create_session(
                    self, session_id, user_id, is_admin=is_admin
                )
                conversation = AgentConversation(
                    session_id=session_id,
                    user_id=user_id,
                    title=self._derive_title(messages_delta),
                    message_count=0,
                    created_at=now,
                    updated_at=now,
                    last_message_at=None,
                )
                db.add(conversation)
                db.flush()

            else:
                if conversation.user_id is None and user_id is not None:
                    conversation.user_id = user_id
                self._validate_conversation_owner(
                    conversation, user_id, is_admin=is_admin
                )

            existing_count = (
                db.query(AgentMessage)
                .filter(AgentMessage.conversation_id == conversation.id)
                .count()
            )

            if base_seq < 0:
                base_seq = 0

            # Idempotent replay handling when client retries a previously appended tail.
            if base_seq < existing_count:
                rows = (
                    db.query(AgentMessage)
                    .filter(
                        AgentMessage.conversation_id == conversation.id,
                        AgentMessage.seq >= base_seq,
                        AgentMessage.seq < base_seq + len(messages_delta),
                    )
                    .order_by(AgentMessage.seq.asc())
                    .all()
                )
                if self._rows_match_messages(rows, messages_delta):
                    self._sync_durable_snapshot(
                        conversation,
                        event_kind="session_append_replay",
                    )
                    created_at = conversation.created_at or now
                    updated_at = conversation.updated_at or now
                    return {
                        "conflict": False,
                        "skipped": True,
                        "accepted_count": 0,
                        "new_seq": existing_count,
                        "meta": ConversationMeta(
                            session_id=conversation.session_id,
                            created_at=created_at.isoformat(),
                            updated_at=updated_at.isoformat(),
                            title=conversation.title or "New Conversation",
                            message_count=conversation.message_count or existing_count,
                        ),
                    }
                return {
                    "conflict": True,
                    "expected_base_seq": existing_count,
                }

            if base_seq > existing_count:
                return {
                    "conflict": True,
                    "expected_base_seq": existing_count,
                }

            for idx, message in enumerate(messages_delta):
                db.add(self._message_to_row(conversation.id, base_seq + idx, message))

            new_count = existing_count + len(messages_delta)
            conversation.message_count = new_count
            if existing_count == 0 and messages_delta:
                conversation.title = self._derive_title(messages_delta)
            conversation.updated_at = now
            if messages_delta:
                conversation.last_message_at = now

            db.commit()
            self._sync_durable_snapshot(
                conversation,
                event_kind="session_append",
            )
            created_at = conversation.created_at or now
            updated_at = conversation.updated_at or now
            return {
                "conflict": False,
                "skipped": len(messages_delta) == 0,
                "accepted_count": len(messages_delta),
                "new_seq": new_count,
                "meta": ConversationMeta(
                    session_id=conversation.session_id,
                    created_at=created_at.isoformat(),
                    updated_at=updated_at.isoformat(),
                    title=conversation.title or "New Conversation",
                    message_count=conversation.message_count or new_count,
                ),
            }
        except Exception as exc:
            db.rollback()
            if self._is_message_hash_missing_error(exc):
                logger.warning(
                    "[AgentStorage] append_session_messages hit missing message_hash column; "
                    "retrying legacy path. Please run: python backend/create_tables.py"
                )
                self._supports_message_hash = False
                return self._append_session_messages_legacy(
                    session_id, base_seq, messages_delta, user_id=user_id, is_admin=is_admin
                )
            raise
        finally:
            db.close()

    def _append_session_messages_legacy(
        self,
        session_id: str,
        base_seq: int,
        messages_delta: List[Message],
        user_id: Optional[str] = None,
        *,
        is_admin: bool = False,
    ) -> Dict[str, Any]:
        now = datetime.now()
        db = SessionLocal()
        try:
            conversation = self._fetch_conversation_by_session(
                db, session_id, user_id=user_id
            )
            if conversation is None:
                ensure_can_create_session(
                    self, session_id, user_id, is_admin=is_admin
                )
                conversation = AgentConversation(
                    session_id=session_id,
                    user_id=user_id,
                    title=self._derive_title(messages_delta),
                    message_count=0,
                    created_at=now,
                    updated_at=now,
                    last_message_at=None,
                )
                db.add(conversation)
                db.flush()

            else:
                self._validate_conversation_owner(
                    conversation, user_id=user_id, is_admin=is_admin
                )

            existing_count = (
                db.execute(
                    text(
                        "SELECT COUNT(*) AS cnt FROM agent_messages WHERE conversation_id = :conversation_id"
                    ),
                    {"conversation_id": conversation.id},
                )
                .scalar()
                or 0
            )

            if base_seq < 0:
                base_seq = 0
            if base_seq > existing_count:
                return {"conflict": True, "expected_base_seq": int(existing_count)}
            if base_seq < existing_count:
                rows = (
                    db.execute(
                        text(
                            """
                            SELECT role, content, thought, name, tool_call_id
                            FROM agent_messages
                            WHERE conversation_id = :conversation_id
                              AND seq >= :base_seq
                              AND seq < :end_seq
                            ORDER BY seq ASC
                            """
                        ),
                        {
                            "conversation_id": conversation.id,
                            "base_seq": base_seq,
                            "end_seq": base_seq + len(messages_delta),
                        },
                    )
                    .mappings()
                    .all()
                )
                if len(rows) == len(messages_delta):
                    same = True
                    for row, msg in zip(rows, messages_delta):
                        sig = self._message_signature(msg)
                        if (
                            row.get("role", "") != sig.get("role", "")
                            or row.get("content") != sig.get("content")
                            or row.get("thought") != sig.get("thought")
                            or row.get("name") != sig.get("name")
                            or row.get("tool_call_id") != sig.get("tool_call_id")
                        ):
                            same = False
                            break
                    if same:
                        self._sync_durable_snapshot(
                            conversation,
                            event_kind="session_append_replay",
                        )
                        created_at = conversation.created_at or now
                        updated_at = conversation.updated_at or now
                        return {
                            "conflict": False,
                            "skipped": True,
                            "accepted_count": 0,
                            "new_seq": int(existing_count),
                            "meta": ConversationMeta(
                                session_id=conversation.session_id,
                                created_at=created_at.isoformat(),
                                updated_at=updated_at.isoformat(),
                                title=conversation.title or "New Conversation",
                                message_count=conversation.message_count or int(existing_count),
                            ),
                        }
                return {"conflict": True, "expected_base_seq": int(existing_count)}

            insert_sql = text(
                """
                INSERT INTO agent_messages
                (conversation_id, seq, role, content, thought, name, tool_call_id, tool_calls, base64_image)
                VALUES
                (:conversation_id, :seq, :role, :content, :thought, :name, :tool_call_id, :tool_calls, :base64_image)
                """
            )
            for idx, message in enumerate(messages_delta):
                db.execute(
                    insert_sql,
                    self._message_to_legacy_params(conversation.id, base_seq + idx, message),
                )

            new_count = int(existing_count) + len(messages_delta)
            conversation.message_count = new_count
            if int(existing_count) == 0 and messages_delta:
                conversation.title = self._derive_title(messages_delta)
            conversation.updated_at = now
            if messages_delta:
                conversation.last_message_at = now
            db.commit()
            self._sync_durable_snapshot(
                conversation,
                event_kind="session_append",
            )
            created_at = conversation.created_at or now
            updated_at = conversation.updated_at or now
            return {
                "conflict": False,
                "skipped": len(messages_delta) == 0,
                "accepted_count": len(messages_delta),
                "new_seq": new_count,
                "meta": ConversationMeta(
                    session_id=conversation.session_id,
                    created_at=created_at.isoformat(),
                    updated_at=updated_at.isoformat(),
                    title=conversation.title or "New Conversation",
                    message_count=conversation.message_count or new_count,
                ),
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def load_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        *,
        is_admin: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if not self._schema_supports_message_hash():
            return self._load_session_legacy(
                session_id, user_id=user_id, is_admin=is_admin
            )

        db = SessionLocal()
        try:
            conversation = self._fetch_conversation_any(db, session_id)
            if conversation is None:
                return None
            try:
                self._validate_conversation_owner(
                    conversation, user_id, is_admin=is_admin
                )
            except SessionAccessError:
                return None

            rows = (
                db.query(AgentMessage)
                .filter(AgentMessage.conversation_id == conversation.id)
                .order_by(AgentMessage.seq.asc())
                .all()
            )
            messages = [self._serialize_message(self._row_to_message(row)) for row in rows]
            payload = {
                "session_id": conversation.session_id,
                "user_id": conversation.user_id,
                "created_at": conversation.created_at.isoformat() if conversation.created_at else "",
                "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else "",
                "title": conversation.title or "Conversation",
                "message_count": conversation.message_count or len(messages),
                "messages": messages,
            }
            restored = self._restore_durable_snapshot(session_id, payload)
            self._repair_durable_snapshot_if_stale(session_id, restored)
            return restored
        except Exception as exc:
            if self._is_message_hash_missing_error(exc):
                logger.warning(
                    "[AgentStorage] load_session hit missing message_hash column; "
                    "switching to legacy read path. Please run: python backend/create_tables.py"
                )
                self._supports_message_hash = False
                return self._load_session_legacy(
                    session_id, user_id=user_id, is_admin=is_admin
                )
            raise
        finally:
            db.close()

    def _load_session_legacy(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        *,
        is_admin: bool = False,
    ) -> Optional[Dict[str, Any]]:
        db = SessionLocal()
        try:
            conversation = self._fetch_conversation_any(db, session_id)
            if conversation is None:
                return None
            try:
                self._validate_conversation_owner(
                    conversation, user_id, is_admin=is_admin
                )
            except SessionAccessError:
                return None

            rows = (
                db.execute(
                    text(
                        """
                        SELECT role, content, thought, name, tool_call_id, tool_calls, base64_image
                        FROM agent_messages
                        WHERE conversation_id = :conversation_id
                        ORDER BY seq ASC
                        """
                    ),
                    {"conversation_id": conversation.id},
                )
                .mappings()
                .all()
            )
            messages = [
                self._serialize_message(
                    self._deserialize_message(self._legacy_row_to_payload(dict(row)))
                )
                for row in rows
            ]
            payload = {
                "session_id": conversation.session_id,
                "user_id": conversation.user_id,
                "created_at": conversation.created_at.isoformat() if conversation.created_at else "",
                "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else "",
                "title": conversation.title or "Conversation",
                "message_count": conversation.message_count or len(messages),
                "messages": messages,
            }
            restored = self._restore_durable_snapshot(session_id, payload)
            self._repair_durable_snapshot_if_stale(session_id, restored)
            return restored
        finally:
            db.close()

    def list_sessions(
        self,
        user_id: Optional[str] = None,
        *,
        all_users: bool = False,
    ) -> List[ConversationMeta]:
        db = SessionLocal()
        try:
            query = db.query(AgentConversation)
            if not all_users:
                if user_id is None:
                    return []
                query = query.filter(AgentConversation.user_id == user_id)
            rows = query.order_by(
                AgentConversation.last_message_at.desc(),
                AgentConversation.updated_at.desc(),
            ).all()
            metas: List[ConversationMeta] = []
            for row in rows:
                metas.append(
                    ConversationMeta(
                        session_id=row.session_id,
                        created_at=row.created_at.isoformat() if row.created_at else "",
                        updated_at=(row.last_message_at or row.updated_at or row.created_at).isoformat(),
                        title=row.title or "Conversation",
                        message_count=row.message_count or 0,
                        user_id=row.user_id,
                    )
                )
            return metas
        finally:
            db.close()

    def delete_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        *,
        is_admin: bool = False,
    ) -> bool:
        db = SessionLocal()
        try:
            conversation = self._fetch_conversation_any(db, session_id)
            if conversation is None:
                return False
            self._validate_conversation_owner(
                conversation, user_id, is_admin=is_admin
            )
            db.query(AgentMessage).filter(
                AgentMessage.conversation_id == conversation.id
            ).delete(synchronize_session=False)
            db.delete(conversation)
            db.commit()
            self._durable.delete(session_id)
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def update_session_title(
        self, session_id: str, title: str, user_id: Optional[str] = None
    ) -> Optional[ConversationMeta]:
        db = SessionLocal()
        try:
            conversation = self._fetch_conversation_by_session(
                db, session_id, user_id=user_id
            )
            if conversation is None:
                return None
            self._validate_conversation_owner(conversation, user_id=user_id)

            conversation.title = title
            conversation.updated_at = datetime.now()
            db.commit()
            db.refresh(conversation)
            self._sync_durable_snapshot(
                conversation,
                event_kind="session_title_update",
            )

            return ConversationMeta(
                session_id=conversation.session_id,
                created_at=conversation.created_at.isoformat() if conversation.created_at else "",
                updated_at=(conversation.last_message_at or conversation.updated_at or conversation.created_at).isoformat(),
                title=conversation.title or "Conversation",
                message_count=conversation.message_count or 0,
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def export_session(
        self,
        session_id: str,
        export_path: str,
        fmt: str = "json",
        user_id: Optional[str] = None,
    ) -> str:
        data = self.load_session(session_id, user_id=user_id)
        if not data:
            raise FileNotFoundError("Session not found")

        export_file = Path(export_path)
        export_file.parent.mkdir(parents=True, exist_ok=True)

        if fmt == "markdown":
            lines = [f"# Conversation {session_id}", ""]
            for msg in data.get("messages", []):
                role = msg.get("role", "assistant")
                content = msg.get("content", "")
                lines.append(f"## {role}")
                lines.append(content or "")
                lines.append("")
            export_file.write_text("\n".join(lines), encoding="utf-8")
        else:
            export_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(export_file)

    def load_messages(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        *,
        is_admin: bool = False,
    ) -> List[Message]:
        data = self.load_session(session_id, user_id=user_id, is_admin=is_admin)
        if not data:
            return []
        messages = []
        for payload in data.get("messages", []):
            try:
                messages.append(self._deserialize_message(payload))
            except Exception as exc:
                logger.warning(f"Failed to deserialize message in session {session_id}: {exc}")
                continue
        return messages

        return messages
























