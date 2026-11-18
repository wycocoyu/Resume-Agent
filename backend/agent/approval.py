"""
运行时确认(approval)挂起表

requires_approval 工具被 LLM 调用时,execute_tool 不执行工具,而是在这里
登记一条 pending,并把 approval_request 结构化事件推给前端确认卡;用户在
卡片中批准(可携带编辑后的参数)后,由 /api/agent/approval 端点取出 pending
并直接执行工具。未经批准,工具在任何路径下都不会被执行——这是运行时语义,
不依赖模型自觉。

v1 约束(见 2026-07-10 方案 §8.4):进程内存储、TTL 10 分钟、同一会话仅保留
最新一条 pending(新调用顶替旧的,旧确认卡随之失效)。
"""
import time
import uuid
from typing import Any, Dict, Optional

TTL_SECONDS = 600

_pending: Dict[str, Dict[str, Any]] = {}


def _evict_expired() -> None:
    now = time.time()
    for key in [k for k, v in _pending.items() if now - v["created_at"] > TTL_SECONDS]:
        _pending.pop(key, None)


def create(
    session_id: str,
    user_id: Optional[str],
    tool_name: str,
    args: Dict[str, Any],
    owner_key: Optional[str] = None,
) -> str:
    """登记一条挂起;同 session 旧 pending 被顶替。返回 approval_id。"""
    _evict_expired()
    for key in [k for k, v in _pending.items() if v["session_id"] == session_id]:
        _pending.pop(key, None)
    approval_id = f"appr_{uuid.uuid4().hex[:16]}"
    _pending[approval_id] = {
        "session_id": session_id,
        "user_id": user_id,
        "owner_key": owner_key,
        "tool_name": tool_name,
        "args": dict(args),
        "created_at": time.time(),
    }
    return approval_id


def get_valid(approval_id: str) -> Optional[Dict[str, Any]]:
    _evict_expired()
    return _pending.get(approval_id)


def pop(approval_id: str) -> Optional[Dict[str, Any]]:
    _evict_expired()
    return _pending.pop(approval_id, None)
