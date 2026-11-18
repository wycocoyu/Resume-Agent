"""可观测性中间件：请求日志、错误日志、链路 span（纯 ASGI 实现，避免 BaseHTTPMiddleware TaskGroup 在 SSE 断连时崩溃）。"""
from __future__ import annotations

import asyncio
import builtins
import os
import time
import traceback
import threading
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from database import SessionLocal
from models import APIErrorLog, APIRequestLog, APITraceSpan

_BASE_EXC_GROUP = getattr(builtins, "BaseExceptionGroup", None)


def _is_disconnect_only_error(exc: BaseException) -> bool:
    """判断异常（含 Python 3.11+ ExceptionGroup）是否仅由客户端断开/取消引发。"""
    if isinstance(exc, (asyncio.CancelledError, BrokenPipeError, ConnectionResetError)):
        return True
    if _BASE_EXC_GROUP is not None and isinstance(exc, _BASE_EXC_GROUP):
        return bool(exc.exceptions) and all(_is_disconnect_only_error(sub) for sub in exc.exceptions)
    return False


def _first_leaf_exception(exc: BaseException) -> Exception | None:
    if _BASE_EXC_GROUP is not None and isinstance(exc, _BASE_EXC_GROUP):
        for sub in exc.exceptions:
            found = _first_leaf_exception(sub)
            if found is not None:
                return found
        return None
    return exc if isinstance(exc, Exception) else None


class RequestObservabilityMiddleware:
    """纯 ASGI 可观测性中间件：不包裹 anyio TaskGroup，兼容 SSE 长连接与提前断连。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        start_perf = time.perf_counter()
        start_at = datetime.now(timezone.utc)
        request = Request(scope)

        trace_id = request.headers.get("x-trace-id") or uuid4().hex
        request_id = request.headers.get("x-request-id") or uuid4().hex

        state = scope.setdefault("state", {})
        state["trace_id"] = trace_id
        state["request_id"] = request_id

        user_id = _extract_user_id(request)
        status_code = 500
        response_size: int | None = None
        captured_error: Exception | None = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_size
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 200))
                headers = MutableHeaders(scope=message)
                headers["X-Trace-Id"] = trace_id
                headers["X-Request-Id"] = request_id
                raw_cl = headers.get("content-length")
                response_size = _safe_int(raw_cl)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except BaseException as exc:
            if _is_disconnect_only_error(exc):
                if status_code == 500:
                    status_code = 499
                return
            captured_error = _first_leaf_exception(exc) or RuntimeError(str(exc))
            raise
        finally:
            elapsed_ms = round((time.perf_counter() - start_perf) * 1000, 2)
            end_at = datetime.now(timezone.utc)
            # 异步写日志，避免观测落库阻塞主请求。
            threading.Thread(
                target=_persist_observability,
                kwargs={
                    "request": request,
                    "status_code": status_code,
                    "response_size": response_size,
                    "user_id": user_id,
                    "trace_id": trace_id,
                    "request_id": request_id,
                    "start_at": start_at,
                    "end_at": end_at,
                    "elapsed_ms": elapsed_ms,
                    "captured_error": captured_error,
                },
                daemon=True,
            ).start()


def _extract_user_id(request: Request) -> str | None:
    """请求归因：取 BetterAuth 可信头的用户 id（2026-07-17 身份统一，旧 JWT 解码归因下架）。

    仅当同请求带合法 X-Internal-Auth-Secret（web 代理注入）才采信
    X-Better-Auth-User-Id，防伪造归因。顺带修复旧实现只认 JWT 导致
    BetterAuth 请求 99% user_id=NULL 的观测盲区。
    """
    secret = (request.headers.get("x-internal-auth-secret") or "").strip()
    if not secret:
        return None
    expected = os.getenv("FASTAPI_INTERNAL_AUTH_SECRET", "").strip()
    if not expected or secret != expected:
        return None
    user_id = (request.headers.get("x-better-auth-user-id") or "").strip()
    return user_id or None


def _persist_observability(
    *,
    request: Request,
    status_code: int,
    response_size: int | None,
    user_id: str | None,
    trace_id: str,
    request_id: str,
    start_at: datetime,
    end_at: datetime,
    elapsed_ms: float,
    captured_error: Exception | None,
) -> None:
    db = SessionLocal()
    try:
        request_size = _safe_int(request.headers.get("content-length"))

        row = APIRequestLog(
            trace_id=trace_id,
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            latency_ms=elapsed_ms,
            user_id=user_id,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            request_size=request_size,
            response_size=response_size,
        )
        db.add(row)

        if captured_error is not None:
            # 仅在需要关联错误日志时才强制 flush 获取 request_log_id，
            # 避免每个请求都产生额外往返，降低接口尾延迟。
            db.flush()
            db.add(
                APIErrorLog(
                    request_log_id=row.id,
                    trace_id=trace_id,
                    error_type=type(captured_error).__name__,
                    error_message=str(captured_error),
                    error_stack="".join(traceback.format_exception(captured_error)),
                    service="backend",
                )
            )

        # 管理端接口已迁移到 ops-portal，保留业务 API 的链路采样（排除健康检查）。
        if request.url.path.startswith("/api/") and request.url.path not in {"/api/health", "/api/health/ready"}:
            db.add(
                APITraceSpan(
                    trace_id=trace_id,
                    span_id=request_id,
                    parent_span_id=None,
                    span_name=f"{request.method} {request.url.path}",
                    start_time=start_at,
                    end_time=end_at,
                    duration_ms=elapsed_ms,
                    status="error" if captured_error else "ok",
                    tags={
                        "status_code": status_code,
                        "ip": _client_ip(request),
                        "user_id": user_id,
                    },
                )
            )

        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _safe_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def register_observability_handlers(app: FastAPI) -> None:
    """注册中间件与兜底异常处理器。"""
    app.add_middleware(RequestObservabilityMiddleware)

    @app.exception_handler(BrokenPipeError)
    async def broken_pipe_handler(request: Request, exc: BrokenPipeError):
        trace_id = getattr(request.state, "trace_id", None) or uuid4().hex
        return JSONResponse(
            status_code=499,
            content={"detail": "客户端连接已断开", "trace_id": trace_id},
            headers={"X-Trace-Id": trace_id},
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        trace_id = getattr(request.state, "trace_id", None) or uuid4().hex
        return JSONResponse(
            status_code=500,
            content={"detail": "服务器内部错误", "trace_id": trace_id},
            headers={"X-Trace-Id": trace_id},
        )
