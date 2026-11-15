"""
Conversation storage adapter (file-based).

Stores session history on disk for persistence and recovery.
Each session JSON includes `user_id` for per-account isolation.
"""

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.agent.cltp.storage.session_scope import (
    SessionAccessError,
    assert_can_read,
    assert_can_write,
    stored_user_id,
)
from backend.agent.cltp.storage.session_limits import ensure_can_create_session
from backend.agent.schema import Message, Role
from backend.agent.pi_core.durable import DurableSessionStore


@dataclass
class ConversationMeta:
    session_id: str
    created_at: str
    updated_at: str
    title: str
    message_count: int
    user_id: Optional[str] = None


def _can_read_session_for_list(owner_id: Optional[int], user_id: str) -> bool:
    if owner_id is None:
        return False
    return owner_id == user_id


class FileConversationStorage:
    """File-based conversation storage adapter."""

    def __init__(
        self,
        base_dir: str = "data/conversations",
        durable_root: Optional[str] = None,
    ):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._durable = DurableSessionStore(
            durable_root or str(self.base_dir / ".durable")
        )

    def _session_path(self, session_id: str) -> Path:
        safe_id = session_id.replace("/", "_")
        return self.base_dir / f"{safe_id}.json"

    def _read_payload(self, session_id: str) -> Optional[Dict[str, Any]]:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def get_session_owner(self, session_id: str) -> Optional[int]:
        return stored_user_id(self._read_payload(session_id))

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

    def _meta_from_payload(self, data: Dict[str, Any], fallback_id: str) -> ConversationMeta:
        return ConversationMeta(
            session_id=data.get("session_id", fallback_id),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            title=data.get("title", "Conversation"),
            message_count=int(data.get("message_count", 0)),
            user_id=stored_user_id(data),
        )

    def save_session(
        self,
        session_id: str,
        messages: List[Message],
        user_id: Optional[str] = None,
        *,
        is_admin: bool = False,
    ) -> ConversationMeta:
        now = datetime.now().isoformat()
        existing = self._read_payload(session_id)
        owner_id = stored_user_id(existing) if existing else None
        assert_can_write(owner_id, user_id, is_admin=is_admin)
        if existing is None:
            ensure_can_create_session(
                self, session_id, user_id, is_admin=is_admin
            )

        created_at = now
        updated_at = now
        if existing:
            created_at = existing.get("created_at", now)
            updated_at = existing.get("updated_at", now)
            if messages:
                updated_at = now

        effective_user_id = owner_id if owner_id is not None else user_id

        meta = ConversationMeta(
            session_id=session_id,
            created_at=created_at,
            updated_at=updated_at,
            title=self._derive_title(messages),
            message_count=len(messages),
            user_id=effective_user_id,
        )
        payload = {
            "session_id": session_id,
            "user_id": effective_user_id,
            "created_at": meta.created_at,
            "updated_at": meta.updated_at,
            "title": meta.title,
            "message_count": meta.message_count,
            "messages": [self._serialize_message(m) for m in messages],
        }
        from backend.agent.tool.resume_data_store import ResumeDataStore

        resume_state = ResumeDataStore.snapshot(session_id)
        if resume_state is not None:
            payload["resume_state"] = resume_state
        path = self._session_path(session_id)
        self._atomic_write(path, payload)
        self._durable_snapshot(session_id, payload)
        return meta

    def _atomic_write(self, path: Path, payload: Dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _durable_snapshot(self, session_id: str, payload: Dict[str, Any]) -> None:
        with self._durable.transaction(session_id) as transaction:
            transaction.append(
                "session_snapshot",
                {
                    "message_count": payload.get("message_count", 0),
                    "updated_at": payload.get("updated_at", ""),
                },
            )
            transaction.set_document(payload)

    def load_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        *,
        is_admin: bool = False,
    ) -> Optional[Dict[str, Any]]:
        data = self._read_payload(session_id)
        if not data:
            return None
        try:
            assert_can_read(stored_user_id(data), user_id, is_admin=is_admin)
        except SessionAccessError:
            return None
        from backend.agent.tool.resume_data_store import ResumeDataStore

        ResumeDataStore.restore_snapshot(session_id, data.get("resume_state"))
        return data

    def list_sessions(
        self,
        user_id: Optional[str] = None,
        *,
        all_users: bool = False,
    ) -> List[ConversationMeta]:
        metas: List[ConversationMeta] = []
        for path in sorted(self.base_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                owner_id = stored_user_id(data)
                if not all_users:
                    if user_id is None:
                        continue
                    if not _can_read_session_for_list(owner_id, user_id):
                        continue
                metas.append(self._meta_from_payload(data, path.stem))
            except Exception:
                continue
        return metas

    def delete_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        *,
        is_admin: bool = False,
    ) -> bool:
        data = self._read_payload(session_id)
        if not data:
            return False
        try:
            assert_can_write(stored_user_id(data), user_id, is_admin=is_admin)
        except SessionAccessError:
            return False
        path = self._session_path(session_id)
        path.unlink()
        self._durable.delete(session_id)
        return True

    def update_session_title(
        self,
        session_id: str,
        title: str,
        user_id: Optional[str] = None,
        *,
        is_admin: bool = False,
    ) -> Optional[ConversationMeta]:
        data = self.load_session(session_id, user_id=user_id, is_admin=is_admin)
        if not data:
            return None

        now = datetime.now().isoformat()
        data["title"] = title
        data["updated_at"] = now
        data["message_count"] = len(data.get("messages", []))

        path = self._session_path(session_id)
        self._atomic_write(path, data)
        self._durable_snapshot(session_id, data)

        return self._meta_from_payload(data, session_id)

    def export_session(
        self,
        session_id: str,
        export_path: str,
        fmt: str = "json",
        user_id: Optional[str] = None,
        *,
        is_admin: bool = False,
    ) -> str:
        data = self.load_session(session_id, user_id=user_id, is_admin=is_admin)
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
            except Exception:
                continue
        return messages

    def append_session_messages(
        self,
        session_id: str,
        base_seq: int,
        messages_delta: List[Message],
        user_id: Optional[str] = None,
        *,
        is_admin: bool = False,
    ) -> Dict[str, Any]:
        """Append messages incrementally with base sequence check."""
        existing = self.load_messages(session_id, user_id=user_id, is_admin=is_admin)
        existing_count = len(existing)

        if base_seq < 0:
            base_seq = 0

        if base_seq < existing_count:
            tail = existing[base_seq : base_seq + len(messages_delta)]
            tail_sig = [self._serialize_message(m) for m in tail]
            delta_sig = [self._serialize_message(m) for m in messages_delta]
            if tail_sig == delta_sig:
                meta = self.save_session(
                    session_id,
                    existing,
                    user_id=user_id,
                    is_admin=is_admin,
                )
                return {
                    "conflict": False,
                    "skipped": True,
                    "accepted_count": 0,
                    "new_seq": existing_count,
                    "meta": meta,
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

        merged = existing + messages_delta
        meta = self.save_session(
            session_id,
            merged,
            user_id=user_id,
            is_admin=is_admin,
        )
        return {
            "conflict": False,
            "skipped": len(messages_delta) == 0,
            "accepted_count": len(messages_delta),
            "new_seq": len(merged),
            "meta": meta,
        }
