"""Chat history routes.

Provides endpoints for chat history management.
"""

import logging
import hashlib
from typing import Any

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError, DisconnectionError, InterfaceError, OperationalError

from backend.agent.memory.chat_history_manager import ChatHistoryManager
from backend.agent.memory.conversation_manager import ConversationManager
from backend.agent.cltp.storage.factory import get_conversation_storage
from backend.agent.cltp.storage.session_limits import (
    SessionLimitExceeded,
    session_limit_status,
)
from backend.agent.schema import Message
from backend.middleware.auth import get_current_user, require_admin_only
from backend.middleware.auth import AppUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/history", tags=["Agent"])
storage = get_conversation_storage()
conversation_manager = ConversationManager(storage=storage)
_save_fingerprint_cache: dict[str, tuple[int, str]] = {}


def _save_cache_key(user_id: str, session_id: str) -> str:
    return f"{user_id}:{session_id}"


def _history_error_detail(message: str, action: str = "CHECK_SERVER_LOGS") -> dict[str, str]:
    code = "AGENT_HISTORY_ERROR"
    if "DB_SCHEMA_MISMATCH" in message:
        code = "DB_SCHEMA_MISMATCH"
        action = "RUN_ALEMBIC_UPGRADE"
    return {
        "code": code,
        "message": message,
        "action": action,
    }


def _is_db_connection_error(exc: Exception) -> bool:
    return isinstance(exc, (OperationalError, InterfaceError, DisconnectionError, DBAPIError))


def _raise_session_limit_error(exc: SessionLimitExceeded) -> None:
    raise HTTPException(
        status_code=403,
        detail={
            "code": "SESSION_LIMIT_EXCEEDED",
            "message": f"历史会话已达上限（{exc.limit} 条），请先删除后再新建",
            "max_sessions": exc.limit,
            "current_count": exc.current,
        },
    ) from exc


def _raise_history_error(route: str, exc: Exception) -> None:
    logger.error(f"[History] {route} failed: {exc}")
    if _is_db_connection_error(exc):
        raise HTTPException(
            status_code=503,
            detail=_history_error_detail(
                "数据库连接异常，请稍后重试",
                action="CHECK_DB_CONNECTIVITY",
            ),
        ) from exc
    raise HTTPException(
        status_code=500,
        detail=_history_error_detail(
            f"{route} failed: {exc}",
            action="CHECK_DB_CONNECTION_AND_RUN_ALEMBIC_UPGRADE",
        ),
    ) from exc


class HistoryResponse(BaseModel):
    """Chat history response."""

    session_id: str
    messages: list[dict[str, Any]]
    count: int


class HistoryClearResponse(BaseModel):
    """History clear response."""

    session_id: str
    message: str


class SessionTitleUpdateRequest(BaseModel):
    title: str


class BatchDeleteRequest(BaseModel):
    session_ids: List[str]


class SessionSaveRequest(BaseModel):
    messages: List[Message]
    client_save_seq: Optional[int] = None
    last_message_hash: Optional[str] = None


class SessionAppendRequest(BaseModel):
    base_seq: int
    messages_delta: List[Message]
    client_save_seq: Optional[int] = None
    last_message_hash: Optional[str] = None


@router.get("/{session_id}", response_model=HistoryResponse)
async def get_history(
    session_id: str, current_user: AppUser = Depends(get_current_user)
) -> HistoryResponse:
    """Get chat history for a session.

    Args:
        session_id: The session identifier

    Returns:
        HistoryResponse with messages
    """
    try:
        session_data = storage.load_session(session_id, user_id=current_user.id)
        if not session_data:
            raise HTTPException(status_code=404, detail="Session not found")
        messages = conversation_manager.get_history(session_id, user_id=current_user.id)

        return HistoryResponse(
            session_id=session_id,
            messages=[
                {"role": m.role, "content": m.content, "thought": m.thought}
                for m in messages
            ],
            count=len(messages),
        )
    except HTTPException:
        raise
    except Exception as e:
        _raise_history_error("get_history", e)


@router.delete("/{session_id}", response_model=HistoryClearResponse)
async def clear_history(
    session_id: str, current_user: AppUser = Depends(get_current_user)
) -> HistoryClearResponse:
    """Clear chat history for a session.

    Args:
        session_id: The session identifier

    Returns:
        HistoryClearResponse with confirmation
    """
    try:
        from backend.agent.web import session_manager

        session_data = storage.load_session(session_id, user_id=current_user.id)
        if not session_data:
            raise HTTPException(status_code=404, detail="Session not found")
        history_manager = ChatHistoryManager(session_id=session_id, storage=storage)
        history_manager.clear_messages()
        await history_manager.save_checkpoint()
        deleted = conversation_manager.delete_session(session_id, user_id=current_user.id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Session not found")

        # Clean up active session in memory（含 ResumeDataStore，防简历/JD 泄漏）
        if session_manager.discard_session(session_id):
            logger.info(f"[History] Cleared active session: {session_id}")

        return HistoryClearResponse(
            session_id=session_id,
            message="History cleared successfully",
        )
    except HTTPException:
        raise
    except Exception as e:
        _raise_history_error("clear_history", e)


@router.post("/{session_id}/restore")
async def restore_history(
    session_id: str, current_user: AppUser = Depends(get_current_user)
) -> dict[str, Any]:
    """Restore chat history from checkpoint.

    Args:
        session_id: The session identifier

    Returns:
        dict with restored message count
    """
    try:
        session_data = storage.load_session(session_id, user_id=current_user.id)
        if not session_data:
            raise HTTPException(status_code=404, detail="Session not found")
        history_manager = ChatHistoryManager(session_id=session_id, storage=storage)
        await history_manager.restore_from_checkpoint()
        messages = history_manager.get_messages()

        return {
            "session_id": session_id,
            "message_count": len(messages),
            "messages": [
                {"role": m.role, "content": m.content}
                for m in messages
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        _raise_history_error("restore_history", e)


@router.get("/sessions/list")
async def list_sessions(
    page: int = 1,
    page_size: int = 20,
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    """List conversation sessions with pagination."""
    try:
        metas = conversation_manager.list_sessions(user_id=current_user.id)
        metas.sort(
            key=lambda m: (m.updated_at or m.created_at or ""),
            reverse=True,
        )

        total = len(metas)
        page_size = max(1, page_size)
        page = max(1, page)
        total_pages = (total + page_size - 1) // page_size if total else 0

        start = (page - 1) * page_size
        end = start + page_size
        sliced = metas[start:end]

        return {
            "sessions": [
                {
                    "session_id": m.session_id,
                    "title": m.title,
                    "created_at": m.created_at,
                    "updated_at": m.updated_at,
                    "message_count": m.message_count,
                }
                for m in sliced
            ],
            "pagination": {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
            },
            "limits": session_limit_status(
                storage,
                current_user.id,
                is_admin=getattr(current_user, "role", None) == "admin",
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        _raise_history_error("list_sessions", e)


@router.get("/admin/sessions/list")
async def admin_list_sessions(
    page: int = 1,
    page_size: int = 20,
    current_user: AppUser = Depends(require_admin_only),
) -> dict[str, Any]:
    """管理员查看全部用户的历史会话。"""
    try:
        metas = conversation_manager.list_sessions(all_users=True)
        metas.sort(
            key=lambda m: (m.updated_at or m.created_at or ""),
            reverse=True,
        )

        total = len(metas)
        page_size = max(1, page_size)
        page = max(1, page)
        total_pages = (total + page_size - 1) // page_size if total else 0

        start = (page - 1) * page_size
        end = start + page_size
        sliced = metas[start:end]

        return {
            "sessions": [
                {
                    "session_id": m.session_id,
                    "title": m.title,
                    "created_at": m.created_at,
                    "updated_at": m.updated_at,
                    "message_count": m.message_count,
                    "user_id": getattr(m, "user_id", None),
                }
                for m in sliced
            ],
            "pagination": {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        _raise_history_error("admin_list_sessions", e)


@router.get("/sessions/{session_id}")
async def get_session_messages(
    session_id: str,
    offset: int = 0,
    limit: int = 200,
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get session history with pagination."""
    try:
        session_data = storage.load_session(session_id, user_id=current_user.id)
        if not session_data:
            raise HTTPException(status_code=404, detail="Session not found")
        messages = conversation_manager.get_history(session_id, user_id=current_user.id)
        sliced = messages[offset: offset + limit]
        return {
            "session_id": session_id,
            "offset": offset,
            "limit": limit,
            "total": len(messages),
            "messages": [
                {"role": m.role, "content": m.content, "thought": m.thought}
                for m in sliced
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        _raise_history_error("get_session_messages", e)


@router.post("/sessions/{session_id}/save")
async def save_session_messages(
    session_id: str,
    request: SessionSaveRequest,
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Save session messages immediately."""
    try:
        messages = request.messages or []
        client_save_seq = request.client_save_seq or 0
        last_message_hash = (request.last_message_hash or "").strip()
        if not last_message_hash and messages:
            last = messages[-1]
            digest_input = f"{last.role}|{last.content or ''}|{last.thought or ''}"
            last_message_hash = hashlib.sha1(
                digest_input.encode("utf-8"),
                usedforsecurity=False,
            ).hexdigest()

        cache_key = _save_cache_key(current_user.id, session_id)
        cached = _save_fingerprint_cache.get(cache_key)
        if (
            cached
            and last_message_hash
            and cached[1] == last_message_hash
            and client_save_seq <= cached[0]
        ):
            return {
                "session_id": session_id,
                "message_count": len(messages),
                "skipped": True,
                "reason": "idempotent-noop",
            }

        # Use a large sliding window here to avoid truncating saved history snapshots.
        # Session save endpoint should persist the full client snapshot.
        history_manager = ChatHistoryManager(
            session_id=session_id,
            storage=storage,
            k=max(1000, len(messages) + 10),
        )
        history_manager.load_messages(messages)
        meta = conversation_manager.save_history(
            session_id,
            history_manager,
            user_id=current_user.id,
            is_admin=getattr(current_user, "role", None) == "admin",
        )
        if last_message_hash:
            _save_fingerprint_cache[cache_key] = (
                max(client_save_seq, (cached[0] if cached else 0)),
                last_message_hash,
            )
        return {
            "session_id": meta.session_id,
            "title": meta.title,
            "created_at": meta.created_at,
            "updated_at": meta.updated_at,
            "message_count": meta.message_count,
            "skipped": False,
        }
    except SessionLimitExceeded as exc:
        _raise_session_limit_error(exc)
    except HTTPException:
        raise
    except Exception as e:
        _raise_history_error("save_session_messages", e)


@router.post("/sessions/{session_id}/append")
async def append_session_messages(
    session_id: str,
    request: SessionAppendRequest,
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Append message delta incrementally.

    Returns 409 when base_seq conflicts with current persisted sequence.
    """
    try:
        messages_delta = request.messages_delta or []
        base_seq = max(0, int(request.base_seq))
        client_save_seq = request.client_save_seq or 0
        last_message_hash = (request.last_message_hash or "").strip()
        if not last_message_hash and messages_delta:
            last = messages_delta[-1]
            digest_input = f"{last.role}|{last.content or ''}|{last.thought or ''}"
            last_message_hash = hashlib.sha1(
                digest_input.encode("utf-8"),
                usedforsecurity=False,
            ).hexdigest()

        cache_key = _save_cache_key(current_user.id, session_id)
        cached = _save_fingerprint_cache.get(cache_key)
        if (
            cached
            and last_message_hash
            and cached[1] == last_message_hash
            and client_save_seq <= cached[0]
        ):
            return {
                "session_id": session_id,
                "skipped": True,
                "reason": "idempotent-noop",
            }

        is_admin = getattr(current_user, "role", None) == "admin"
        append_method = getattr(storage, "append_session_messages", None)
        if not callable(append_method):
            # Fallback for storage adapters without append support:
            existing = conversation_manager.get_history(
                session_id, user_id=current_user.id
            )
            if base_seq != len(existing):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "base_seq conflict",
                        "expected_base_seq": len(existing),
                    },
                )
            merged = existing + messages_delta
            history_manager = ChatHistoryManager(
                session_id=session_id,
                storage=storage,
                k=max(1000, len(merged) + 10),
            )
            history_manager.load_messages(merged)
            meta = conversation_manager.save_history(
                session_id,
                history_manager,
                user_id=current_user.id,
                is_admin=is_admin,
            )
            new_seq = len(merged)
            accepted_count = len(messages_delta)
            skipped = accepted_count == 0
        else:
            result = append_method(
                session_id,
                base_seq,
                messages_delta,
                user_id=current_user.id,
                is_admin=is_admin,
            )
            if result.get("conflict"):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "base_seq conflict",
                        "expected_base_seq": result.get("expected_base_seq", 0),
                    },
                )
            meta = result["meta"]
            new_seq = int(result.get("new_seq", meta.message_count))
            accepted_count = int(result.get("accepted_count", 0))
            skipped = bool(result.get("skipped", False))

        if last_message_hash:
            _save_fingerprint_cache[cache_key] = (
                max(client_save_seq, (cached[0] if cached else 0)),
                last_message_hash,
            )

        return {
            "session_id": meta.session_id,
            "title": meta.title,
            "created_at": meta.created_at,
            "updated_at": meta.updated_at,
            "message_count": meta.message_count,
            "accepted_count": accepted_count,
            "new_seq": new_seq,
            "skipped": skipped,
        }
    except SessionLimitExceeded as exc:
        _raise_session_limit_error(exc)
    except HTTPException:
        raise
    except Exception as e:
        _raise_history_error("append_session_messages", e)


@router.put("/sessions/{session_id}/title")
async def update_session_title(
    session_id: str,
    request: SessionTitleUpdateRequest,
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")

    meta = conversation_manager.update_session_title(
        session_id, title, user_id=current_user.id
    )
    if not meta:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": meta.session_id,
        "title": meta.title,
        "created_at": meta.created_at,
        "updated_at": meta.updated_at,
        "message_count": meta.message_count,
    }


@router.post("/sessions/{session_id}/load")
async def load_session(
    session_id: str, current_user: AppUser = Depends(get_current_user)
) -> dict[str, Any]:
    """Load a session and return its messages."""
    try:
        session_data = storage.load_session(session_id, user_id=current_user.id)
        if not session_data:
            raise HTTPException(status_code=404, detail="Session not found")
        history = conversation_manager.get_or_create_history(
            session_id, user_id=current_user.id
        )
        messages = history.get_messages()
        return {
            "session_id": session_id,
            "message_count": len(messages),
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
    except HTTPException:
        raise
    except Exception as e:
        _raise_history_error("load_session", e)


@router.get("/sessions/{session_id}/export")
async def export_session(
    session_id: str,
    fmt: str = "json",
    current_user: AppUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Export a session to a file (json/markdown)."""
    try:
        session_data = storage.load_session(session_id, user_id=current_user.id)
        if not session_data:
            raise HTTPException(status_code=404, detail="Session not found")
        export_dir = "data/exports"
        extension = "md" if fmt == "markdown" else "json"
        export_path = f"{export_dir}/{session_id}.{extension}"
        path = conversation_manager.export_session(
            session_id, export_path, fmt=fmt, user_id=current_user.id
        )
        return {"session_id": session_id, "export_path": path}
    except HTTPException:
        raise
    except Exception as e:
        _raise_history_error("export_session", e)


@router.post("/sessions/batch-delete")
async def batch_delete_sessions(
    request: BatchDeleteRequest, current_user: AppUser = Depends(get_current_user)
) -> dict[str, Any]:
    """Delete multiple sessions.

    Args:
        request: BatchDeleteRequest with session_ids list

    Returns:
        dict with deleted_count
    """
    try:
        from backend.agent.web import session_manager

        deleted_count = conversation_manager.delete_sessions(
            request.session_ids, user_id=current_user.id
        )

        # Clean up active sessions in memory（含 ResumeDataStore，防简历/JD 泄漏）
        for session_id in request.session_ids:
            if session_manager.discard_session(session_id):
                logger.info(f"[History] Cleared active session: {session_id}")
        
        logger.info(f"Batch deleted {deleted_count}/{len(request.session_ids)} sessions")
        return {
            "deleted_count": deleted_count,
            "total_requested": len(request.session_ids),
            "message": f"Successfully deleted {deleted_count} session(s)"
        }
    except HTTPException:
        raise
    except Exception as e:
        _raise_history_error("batch_delete_sessions", e)


@router.delete("/sessions/all")
async def delete_all_sessions(
    current_user: AppUser = Depends(get_current_user)
) -> dict[str, Any]:
    """Delete all sessions.

    Returns:
        dict with deleted_count
    """
    try:
        from backend.agent.web import session_manager

        # Get all session IDs before deletion
        all_sessions = conversation_manager.list_sessions(user_id=current_user.id)
        session_ids = [meta.session_id for meta in all_sessions]

        deleted_count = conversation_manager.delete_all_sessions(user_id=current_user.id)

        # Clean up active sessions in memory for current user only
        # （session_manager 版本会同步清理 ResumeDataStore，防简历/JD 泄漏）
        session_manager.clear_sessions_for_user(current_user.id)
        logger.info(
            f"[History] Cleared active sessions for user {current_user.id} "
            f"(deleted {deleted_count} persisted sessions)"
        )
        
        logger.info(f"Deleted all {deleted_count} sessions")
        return {
            "deleted_count": deleted_count,
            "message": f"Successfully deleted all {deleted_count} session(s)"
        }
    except HTTPException:
        raise
    except Exception as e:
        _raise_history_error("delete_all_sessions", e)
