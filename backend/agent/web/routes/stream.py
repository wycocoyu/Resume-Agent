"""SSE Stream route for agent interaction.

This module provides:
- POST /stream: SSE endpoint for streaming agent responses
- Heartbeat mechanism for keeping connection alive
- StreamEvent -> SSE 对外协议（前端再适配为 CLTP chunk）
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from openai import PermissionDeniedError
from starlette.concurrency import run_in_threadpool

from backend.agent.pi_core.resume_agent import ResumeAgentRuntime
from backend.agent.pi_core.metrics import get_pi_core_metrics
from backend.agent.config import NetworkConfig, config
from backend.core.logger import get_logger
from backend.middleware.auth import get_current_user
from backend.middleware.auth import AppUser
from backend.agent.cltp.storage.session_scope import SessionAccessError

logger = get_logger(__name__)
from backend.agent.schema import AgentState as SchemaAgentState, Message, Role
from backend.agent.web.schemas.stream import StreamRequest, SSEEvent, HeartbeatEvent
from backend.agent.web.streaming.agent_stream import StreamProcessor
from backend.agent.web.streaming.state_machine import AgentStateMachine
from backend.agent.web.streaming.events import StreamEvent
from backend.agent.cltp.storage.factory import get_conversation_storage
from backend.agent.memory.conversation_manager import ConversationManager
from backend.agent.web import session_manager

router = APIRouter(tags=["Agent"])

# Create stream processor for agent execution
stream_processor = StreamProcessor()
storage = get_conversation_storage()
conversation_manager = ConversationManager(storage=storage)

# 允许前端按请求切换的 agent 模型白名单
# 2026-09-16：阿里云百炼欠费(400 Arrearage)，全线迁到 DeepSeek 官方。
# 旧名保留在白名单里只为兼容老会话存下的 model 值，路由表里统一指向新通道。
_ALLOWED_AGENT_MODELS = {
    "deepseek-flash",
    "deepseek-v4-pro",
    # 下面几个是已下线型号，留在白名单只为让老会话能进到归一逻辑，
    # 真正发给上游的名字由 _MODEL_ALIASES 换掉
    "deepseek-v4-flash",
    "qwen-max",
    "claude-sonnet-4-6",
}

# 模型 → LLM 通道路由表（base_url, api_key 环境变量名, extra_body）
# extra_body 随模型走：deepseek-flash 默认开思考模式，会拒绝 tool_choice=required
# （诊断/建议引擎依赖它），必须显式关掉。
# ⚠️ 关思考只认 thinking.type=disabled；DashScope 时代的 enable_thinking=false
# 在 DeepSeek 官方端被静默忽略，照抄会让 tool_choice 继续报错。
_DEEPSEEK_OFFICIAL = "https://api.deepseek.com"
_NO_THINKING = {"thinking": {"type": "disabled"}}
_MODEL_CHANNELS = {
    "deepseek-flash": (_DEEPSEEK_OFFICIAL, "DEEPSEEK_API_KEY", _NO_THINKING),
    "deepseek-v4-pro": (_DEEPSEEK_OFFICIAL, "DEEPSEEK_API_KEY", _NO_THINKING),
}

# 已下线型号 → 当前型号。老会话里存着旧 model 名，原样发给上游会 404，
# 必须在用它之前归一（只改通道不改名是不够的）。
_MODEL_ALIASES = {
    "deepseek-v4-flash": "deepseek-flash",
    "qwen-max": "deepseek-flash",
    "claude-sonnet-4-6": "deepseek-flash",
}

# In-memory session TTL — evict idle agent sessions to cap memory growth
_SESSION_TTL_SECONDS = int(os.getenv("AGENT_SESSION_TTL_SECONDS", "3600"))

# Heartbeat configuration
HEARTBEAT_INTERVAL = 55  # seconds — 心跳间隔，前端超时为 60s，需留 5s 余量
HEARTBEAT_V2_ENABLED = (
    os.getenv("AGENT_STREAM_HEARTBEAT_V2", "true").strip().lower() != "false"
)


def get_active_agent(conversation_id: str):
    """薄委托，保持 approval 等既有 import 路径可用；实现在 session_manager。"""
    return session_manager.get_active_agent(conversation_id)


def _is_admin(user: AppUser) -> bool:
    return getattr(user, "role", None) == "admin"


def _assert_session_access(conversation_id: str, user: AppUser) -> None:
    owner_id = conversation_manager.get_session_owner(conversation_id)
    if owner_id is None:
        return
    if owner_id != user.id and not _is_admin(user):
        raise HTTPException(status_code=403, detail="无权访问该会话")


def _get_or_create_session(
    conversation_id: str,
    user: AppUser,
    resume_path: Optional[str] = None,
    resume_data: Optional[dict] = None,
) -> dict:
    """Get existing session or create a new one.

    Args:
        conversation_id: Conversation identifier
        resume_path: Optional path to resume file

    Returns:
        Session dict containing agent and chat history
    """
    _assert_session_access(conversation_id, user)

    # Check if session exists in memory but file has been deleted
    existing_session = session_manager.get_session(conversation_id)
    if existing_session is not None:
        session_user_id = existing_session.get("user_id")
        if session_user_id not in (None, user.id) and not _is_admin(user):
            raise HTTPException(status_code=403, detail="无权访问该会话")
        # Verify file still exists in storage
        existing_messages = storage.load_messages(
            conversation_id,
            user_id=user.id,
            is_admin=_is_admin(user),
        )
        if not existing_messages:
            # File has been deleted, but session still exists in memory
            # Clean up old session and create a new one
            logger.info(
                f"[SSE] Session {conversation_id} exists in memory but file deleted, "
                "cleaning up and creating new session"
            )
            # 原地重建：只重置 agent 记忆，简历数据是否保留由重建后的请求决定
            session_manager.discard_session(conversation_id, clear_resume_data=False)

    if session_manager.get_session(conversation_id) is None:
        from backend.agent.memory import ChatHistoryManager
        from backend.agent.tool.resume_data_store import ResumeDataStore

        agent = None
        chat_history = None
        last_exc: Exception | None = None

        # Use network configuration manager for retry settings
        network_config = config.network or NetworkConfig()
        max_retries = network_config.agent_init_max_retries
        retry_delay_base = network_config.agent_init_retry_delay
        retry_backoff = network_config.agent_init_retry_backoff

        for attempt in range(1, max_retries + 1):
            try:
                # Use network configuration manager's context manager
                with network_config.without_proxy():
                    agent = ResumeAgentRuntime(
                        session_id=conversation_id,
                        is_admin=_is_admin(user),
                        user_id=user.id,
                    )
                chat_history = conversation_manager.get_or_create_history(
                    conversation_id,
                    user_id=user.id,
                    is_admin=_is_admin(user),
                )
                break
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    f"[SSE] Agent init failed (attempt {attempt}/{max_retries}): {exc}"
                )
                # Exponential backoff: delay = delay_base * (backoff ^ (attempt - 1))
                delay = retry_delay_base * (retry_backoff ** (attempt - 1))
                time.sleep(delay)

        if agent is None or chat_history is None:
            raise last_exc or RuntimeError("Failed to create agent session")
        # Align agent's internal history with session history
        if hasattr(agent, "_chat_history"):
            agent._chat_history = chat_history

        if resume_data:
            ResumeDataStore.set_data(resume_data, session_id=conversation_id)
            # 🔍 诊断日志：验证元数据是否正确设置
            stored_meta = ResumeDataStore._meta_by_session.get(conversation_id, {})
            logger.info(f"[SSE] ResumeDataStore meta after set_data: {stored_meta}")
            if hasattr(agent, "_conversation_state") and agent._conversation_state:
                agent._conversation_state.update_resume_loaded(True)

        # created_at / last_accessed 由 register_session 统一补齐
        session_manager.register_session(
            conversation_id,
            {
                "agent": agent,
                "chat_history": chat_history,
                "resume_path": resume_path,
                "user_id": user.id,
            },
        )
        logger.info(f"[SSE] Created new session: {conversation_id}")
    else:
        # 复用已有会话即视为活跃，touch 防止长对话被 TTL 误回收
        session_manager.touch(conversation_id)
        session = session_manager.get_session(conversation_id)
        # Update resume path if provided
        if resume_path:
            session["resume_path"] = resume_path
        if resume_data:
            from backend.agent.tool.resume_data_store import ResumeDataStore

            ResumeDataStore.set_data(resume_data, session_id=conversation_id)
            agent = session.get("agent")
            if (
                agent
                and hasattr(agent, "_conversation_state")
                and agent._conversation_state
            ):
                agent._conversation_state.update_resume_loaded(True)

    return session_manager.get_session(conversation_id)


def clear_active_sessions_for_user(user_id: str) -> None:
    """薄委托；session_manager 版本会同步清理 ResumeDataStore（防简历/JD 泄漏）。"""
    session_manager.clear_sessions_for_user(user_id)


def _cleanup_session(conversation_id: str) -> None:
    """Cleanup session after completion（touch-then-sweep TTL 回收，见 session_manager）。"""
    session_manager.evict_idle_sessions(conversation_id, _SESSION_TTL_SECONDS)


async def _stream_event_generator(
    conversation_id: str,
    prompt: str,
    user: AppUser,
    resume_path: Optional[str] = None,
    resume_data: Optional[dict] = None,
    cursor: Optional[str] = None,
    resume: bool = False,
    model: Optional[str] = None,
    run_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Generate SSE events from agent execution.

    This generator:
    1. Creates/gets agent session
    2. Streams agent events as SSE format
    3. Sends heartbeat when idle
    4. Handles errors gracefully

    Args:
        conversation_id: Conversation identifier
        prompt: User message
        resume_path: Optional resume file path

    Yields:
        SSE formatted strings
    """
    canonical_run_id = run_id or f"run_{uuid.uuid4().hex}"
    event_seq = 0

    def wrap_event(event_type: str, data: dict) -> SSEEvent:
        nonlocal event_seq
        event_seq += 1
        event_id = f"evt_{uuid.uuid4().hex}"
        canonical = {
            "id": event_id,
            "type": event_type,
            "session_id": conversation_id,
            "run_id": canonical_run_id,
            "seq": event_seq,
            "timestamp": time.time(),
            "data": data,
        }
        return SSEEvent(id=event_id, type=event_type, data=canonical)

    def wrap_stream_event(event: StreamEvent) -> SSEEvent:
        nonlocal event_seq
        event_seq += 1
        event.bind_envelope(run_id=canonical_run_id, seq=event_seq)
        payload = event.to_dict()
        return SSEEvent(id=event.event_id, type=event.event_type.value, data=payload)

    logger.info(
        f"[SSE Generator] Starting generator for conversation: {conversation_id}"
    )
    try:
        session = await run_in_threadpool(
            _get_or_create_session, conversation_id, user, resume_path, resume_data
        )
        agent = session["agent"]
        chat_history = session["chat_history"]
        logger.info(f"[SSE Generator] Session created/retrieved successfully")

        # 按请求覆盖 LLM 模型（白名单防注入）；按模型动态切通道(base_url/api_key/client)
        # ask 方法每次读 self.model + self.client 即时生效
        if model and model in _ALLOWED_AGENT_MODELS and getattr(agent, "llm", None) is not None:
            # 先把已下线型号换成在售型号，再比对/切换——否则旧名会原样发给上游 404
            model = _MODEL_ALIASES.get(model, model)
            if agent.llm.model != model:
                channel = _MODEL_CHANNELS.get(model)
                if channel:
                    base_url, key_env, channel_extra_body = channel
                    api_key = os.getenv(key_env, "").strip()
                    if api_key:
                        logger.info(
                            f"[SSE] 切换模型 {agent.llm.model} -> {model} (conv={conversation_id}, channel={base_url})"
                        )
                        agent.llm.update_model(
                            model, base_url, api_key, extra_body=channel_extra_body
                        )
                    else:
                        logger.warning(f"[SSE] 模型 {model} 的通道 key {key_env} 未配置，跳过切换")
                else:
                    # 无通道路由的模型仅改 model 名（向后兼容）
                    logger.info(f"[SSE] 切换模型 {agent.llm.model} -> {model} (conv={conversation_id})")
                    agent.llm.model = model

        # Create state machine for this execution
        state_machine = AgentStateMachine(conversation_id)

        # Track stream output cadence for heartbeat diagnostics
        last_emit_time = time.time()
        last_agent_event_time = time.time()

        # Send initial status event
        logger.info(f"[SSE Generator] Preparing initial status event")
        status_event = wrap_event(
            "status", {"content": "processing", "conversation_id": conversation_id}
        )
        logger.info(f"[SSE Generator] Yielding initial status event")
        yield status_event.to_sse_format()
        last_emit_time = time.time()
        logger.info(f"[SSE Generator] Initial status event yielded successfully")

        # Restore chat history to agent memory if needed
        existing_messages = chat_history.get_messages()

        # If chat_history is empty but agent.memory has messages, clear agent.memory
        # This can happen when a session file was deleted but the active session still exists in memory
        if not existing_messages and len(agent.memory.messages) > 0:
            logger.info(
                f"[SSE] Chat history is empty but agent.memory has {len(agent.memory.messages)} messages. "
                "Clearing agent.memory to prevent stale context."
            )
            agent.memory.messages.clear()

        if existing_messages and len(agent.memory.messages) == 0:
            logger.info(
                f"[SSE] Restoring {len(existing_messages)} history messages to agent"
            )
            for msg in existing_messages:
                role_value = (
                    msg.role.value if hasattr(msg.role, "value") else str(msg.role)
                )
                if role_value == "user":
                    agent.memory.add_message(Message.user_message(msg.content))
                elif role_value == "assistant":
                    agent.memory.add_message(
                        Message(
                            role=Role.ASSISTANT,
                            content=msg.content,
                            tool_calls=msg.tool_calls,
                        )
                    )
                elif role_value == "tool":
                    agent.memory.add_message(
                        Message.tool_message(
                            content=msg.content,
                            name=msg.name or "unknown",
                            tool_call_id=msg.tool_call_id or "",
                        )
                    )

        # Add user message to chat history (don't persist yet, wait for agent to complete)
        chat_history.add_message(Message(role=Role.USER, content=prompt), persist=False)

        # Execute agent and stream events
        # 心跳只等待下一个异步事件，不再额外创建 producer + Queue。
        # 这样既不会让队列承担事件排序职责，也不会因为心跳超时取消
        # 正在执行的 LLM/工具迭代。
        if HEARTBEAT_V2_ENABLED:
            stream_iterator = stream_processor.start_stream(
                session_id=conversation_id,
                agent=agent,
                state_machine=state_machine,
                event_sender=lambda d: None,
                user_message=prompt,
                chat_history_manager=chat_history,
            ).__aiter__()
            next_event_task = asyncio.create_task(stream_iterator.__anext__())
            heartbeat_task = asyncio.create_task(
                asyncio.sleep(HEARTBEAT_INTERVAL)
            )

            try:
                while True:
                    done, _ = await asyncio.wait(
                        {next_event_task, heartbeat_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    if heartbeat_task in done:
                        yield HeartbeatEvent().to_sse_format()
                        last_emit_time = time.time()
                        heartbeat_task = asyncio.create_task(
                            asyncio.sleep(HEARTBEAT_INTERVAL)
                        )

                    if next_event_task in done:
                        try:
                            item = next_event_task.result()
                        except StopAsyncIteration:
                            break

                        sse_event = wrap_stream_event(item)
                        yield sse_event.to_sse_format()
                        now = time.time()
                        last_emit_time = now
                        last_agent_event_time = now
                        next_event_task = asyncio.create_task(
                            stream_iterator.__anext__()
                        )
            finally:
                for task in (next_event_task, heartbeat_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(
                    next_event_task,
                    heartbeat_task,
                    return_exceptions=True,
                )
                aclose = getattr(stream_iterator, "aclose", None)
                if callable(aclose):
                    try:
                        await aclose()
                    except BaseException as close_exc:
                        logger.debug(f"[SSE] Stream iterator close ignored: {close_exc}")
        else:
            async for event in stream_processor.start_stream(
                session_id=conversation_id,
                agent=agent,
                state_machine=state_machine,
                event_sender=lambda d: None,  # Not used in SSE mode
                user_message=prompt,
                chat_history_manager=chat_history,
            ):
                sse_event = wrap_stream_event(event)
                yield sse_event.to_sse_format()
                now = time.time()
                last_emit_time = now
                last_agent_event_time = now
                await asyncio.sleep(0)

        # Send completion status
        complete_event = wrap_event(
            "status", {"content": "complete", "conversation_id": conversation_id}
        )
        yield complete_event.to_sse_format()
        done_event = wrap_event(
            "done",
            {
                "conversation_id": conversation_id,
                "last_emit_seconds_ago": round(time.time() - last_emit_time, 3),
                "last_agent_event_seconds_ago": round(
                    time.time() - last_agent_event_time, 3
                ),
            },
        )
        yield done_event.to_sse_format()

    except asyncio.CancelledError:
        logger.info(f"[SSE] Stream cancelled for session: {conversation_id}")
        cancel_event = wrap_event(
            "status", {"content": "cancelled", "conversation_id": conversation_id}
        )
        yield cancel_event.to_sse_format()

    except PermissionDeniedError as e:
        logger.warning(f"[SSE] Model quota/403 for session {conversation_id}: {e}")
        error_payload = {
            "content": "模型余额不足，请充值",
            "error_type": type(e).__name__,
            "error_details": str(e),
        }
        error_event = wrap_event("error", error_payload)
        yield error_event.to_sse_format()
    except Exception as e:
        logger.exception(f"[SSE] Error in stream for session {conversation_id}: {e}")
        error_msg = str(e)
        if "proxy" in error_msg.lower() or "connection refused" in error_msg.lower():
            logger.warning(f"[SSE] Proxy connection error detected: {error_msg}")
            error_payload = {
                "content": "网络连接失败：请检查代理配置或网络连接",
                "error_type": type(e).__name__,
                "error_details": "代理连接失败可能导致 Agent 初始化失败",
            }
        elif (
            "403" in error_msg
            or "free tier" in error_msg.lower()
            or "FreeTierOnly" in error_msg
        ):
            error_payload = {
                "content": "余额不足，请充值",
                "error_type": type(e).__name__,
                "error_details": error_msg,
            }
        else:
            error_payload = {"content": error_msg, "error_type": type(e).__name__}
        error_event = wrap_event("error", error_payload)
        yield error_event.to_sse_format()
    except BaseException as base_exc:
        if isinstance(base_exc, (SystemExit, KeyboardInterrupt)):
            raise
        logger.exception(f"[SSE] BaseException/TaskGroup failure for session {conversation_id}: {base_exc}")
        cancel_event = wrap_event(
            "status", {"content": "cancelled", "conversation_id": conversation_id}
        )
        yield cancel_event.to_sse_format()

    finally:
        _cleanup_session(conversation_id)


@router.post("/stream")
async def stream_events(
    request: StreamRequest,
    current_user: AppUser = Depends(get_current_user),
) -> StreamingResponse:
    """SSE streaming endpoint for agent interaction.

    This endpoint:
    1. Accepts user messages
    2. Returns Server-Sent Events stream
    3. Includes heartbeat for connection keep-alive

    Args:
        request: StreamRequest with prompt and optional conversation_id

    Returns:
        StreamingResponse with SSE content
    """
    # Generate conversation ID if not provided
    conversation_id = request.conversation_id or str(uuid.uuid4())

    prompt = request.prompt or request.message
    if not prompt:
        raise HTTPException(status_code=422, detail="Missing prompt/message")

    _assert_session_access(conversation_id, current_user)

    logger.info(
        f"[SSE] Starting stream for conversation: {conversation_id} user={current_user.id}"
    )

    # 🚨 增加防护：同一 sessionId 正在运行时，停止旧的 stream。
    # 这样可以防止多个 tab 或快速切换导致并发冲突，同时能通过 reason 区分是"新请求打断"还是"手动停止"。
    if stream_processor.has_active_stream(conversation_id):
        logger.info(f"[SSE] Active stream found for {conversation_id}, stopping it first (reason: session_switch)")
        # 停止旧流前先尝试落盘，保护内存里未持久化的修改
        try:
            from backend.agent.tool.resume_data_store import ResumeDataStore
            if ResumeDataStore.persist_data(conversation_id):
                logger.info(f"[SSE] Persisted resume before stopping stream (conv={conversation_id})")
        except Exception:
            logger.warning(f"[SSE] Failed to persist before session_switch (conv={conversation_id})")
        await stream_processor.stop_stream(conversation_id, reason="session_switch")
        # 给一点点时间让旧流退出
        await asyncio.sleep(0.3)

    if request.resume:
        logger.info(
            f"[SSE] Resume requested for conversation: {conversation_id} cursor={request.cursor}"
        )
    logger.info(f"[SSE] Prompt: {prompt[:100]}...")

    # 🔍 诊断日志：检查 resume_data 元数据
    if request.resume_data:
        rd = request.resume_data
        resume_id = (
            rd.get("resume_id")
            or rd.get("id")
            or (rd.get("_meta") or {}).get("resume_id")
        )
        user_id = rd.get("user_id") or (rd.get("_meta") or {}).get("user_id")
        logger.info(
            f"[SSE] resume_data metadata: resume_id={resume_id}, user_id={user_id}"
        )
    else:
        logger.warning("[SSE] No resume_data provided in request")

    return StreamingResponse(
        _stream_event_generator(
            conversation_id=conversation_id,
            prompt=prompt,
            user=current_user,
            resume_path=request.resume_path,
            resume_data=request.resume_data,
            cursor=request.cursor,
            resume=bool(request.resume),
            model=request.model,
            run_id=request.run_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
        },
    )


@router.post("/stream/stop/{conversation_id}")
async def stop_stream(
    conversation_id: str,
    request: Request,
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    """Stop an active stream.

    Args:
        conversation_id: The conversation to stop
        request: The FastAPI request object to check source

    Returns:
        Status message
    """
    # 🚨 增加防护：同一 sessionId 正在运行时，记录 stop 请求的来源。
    # 如果是因为并发页面或自动触发的 stop，可以在日志中体现。
    client_host = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    logger.info(f"[SSE] Stop request for {conversation_id} from {client_host} (UA: {user_agent})")

    _assert_session_access(conversation_id, current_user)

    success = await stream_processor.stop_stream(conversation_id)

    if success:
        logger.info(f"[SSE] Stopped stream for conversation: {conversation_id}")
        return {"status": "stopped", "conversation_id": conversation_id}
    else:
        logger.warning(f"[SSE] Stop requested for non-active stream: {conversation_id}")
        return {"status": "not_found", "conversation_id": conversation_id}


@router.get("/stream/metrics")
async def stream_metrics(
    conversation_id: Optional[str] = None,
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    """Return bounded Pi Core rollout metrics for operators.

    Session-specific metrics are owner-scoped; the aggregate registry is
    restricted to administrators to avoid leaking cross-user activity.
    """

    if conversation_id:
        _assert_session_access(conversation_id, current_user)
        return {
            "conversation_id": conversation_id,
            "metrics": get_pi_core_metrics(conversation_id),
        }
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="仅管理员可查看聚合指标")
    return {"metrics": get_pi_core_metrics()}


@router.delete("/stream/session/{conversation_id}")
async def clear_session(
    conversation_id: str,
    current_user: AppUser = Depends(get_current_user),
) -> dict:
    """Clear a conversation session.

    Args:
        conversation_id: The conversation to clear

    Returns:
        Status message
    """
    _assert_session_access(conversation_id, current_user)

    # discard_session 无论条目是否在内存都会清 ResumeDataStore
    if session_manager.discard_session(conversation_id):
        logger.info(f"[SSE] Cleared session: {conversation_id}")
        return {"status": "cleared", "conversation_id": conversation_id}
    logger.info(f"[SSE] Session not found (already cleared): {conversation_id}")
    return {"status": "not_found", "conversation_id": conversation_id}
