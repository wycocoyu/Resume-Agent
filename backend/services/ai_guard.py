"""AI feature switch, upstream quota circuit breaker, and anonymous per-IP sliding-window rate limiter."""
from __future__ import annotations

from collections import deque
import inspect
import os
import re
import sys
import threading
import time
from typing import Literal, Optional

from fastapi import Depends, HTTPException, Request

# 统一模块别名，避免 `services.ai_guard` 与 `backend.services.ai_guard` 双实例分裂
if __name__ == "services.ai_guard":
    sys.modules.setdefault("backend.services.ai_guard", sys.modules[__name__])
elif __name__ == "backend.services.ai_guard":
    sys.modules.setdefault("services.ai_guard", sys.modules[__name__])

try:
    from middleware.auth import AppUser, get_current_user_optional
except ImportError:
    from backend.middleware.auth import AppUser, get_current_user_optional

try:
    from backend.services.runtime_features import (
        get_ai_quota_cooldown_seconds,
        get_anon_ai_import_hourly_limit,
        get_anon_ai_rewrite_hourly_limit,
        is_editor_ai_enabled,
    )
except ImportError:
    from services.runtime_features import (
        get_ai_quota_cooldown_seconds,
        get_anon_ai_import_hourly_limit,
        get_anon_ai_rewrite_hourly_limit,
        is_editor_ai_enabled,
    )

AI_FEATURE_DISABLED_MESSAGE = "当前 AI 辅助功能已暂时关闭，您仍可正常手动编辑简历并免费导出 PDF。"
AI_QUOTA_EXHAUSTED_MESSAGE = "当前免费 AI 额度暂已用完，您仍可正常手动编辑简历并免费导出 LaTeX / HTML PDF。"
AI_RATE_LIMITED_MESSAGE = "当前 IP 短时间内 AI 调用次数已达上限，请稍后再试，手动编辑与导出 PDF 不受影响。"


class AiGuardError(HTTPException):
    """带有稳定 code / message 与纯字符串 detail 的 AI 熔断/限流异常。"""

    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(status_code=status_code, detail=message)


class AiFeatureDisabledError(AiGuardError):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code="AI_FEATURE_DISABLED",
            message=AI_FEATURE_DISABLED_MESSAGE,
        )


class AiQuotaExhaustedError(AiGuardError):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code="AI_QUOTA_EXHAUSTED",
            message=AI_QUOTA_EXHAUSTED_MESSAGE,
        )


class AiRateLimitedError(AiGuardError):
    def __init__(self) -> None:
        super().__init__(
            status_code=429,
            code="AI_RATE_LIMITED",
            message=AI_RATE_LIMITED_MESSAGE,
        )


def ai_guard_error_payload(exc: AiGuardError) -> dict[str, str]:
    return {
        "code": exc.code,
        "message": exc.message,
        "detail": str(exc.detail),
    }


_QUOTA_KEYWORDS = (
    "insufficient_balance",
    "insufficient balance",
    "insufficient_quota",
    "insufficient quota",
    "insufficient_user_quota",
    "exceeded your current quota",
    "quota_exceeded",
    "quota exceeded",
    "quota exhausted",
    "balance exhausted",
    "out of quota",
    "out of credits",
    "credit balance",
    "arrearage",
    "billing_not_active",
    "quota",
    "balance",
    "余额不足",
    "欠费",
    "额度不足",
    "额度已用完",
    "额度用完",
    "配额不足",
    "配额已用完",
    "资源包已耗尽",
    "账户余额",
)
_STATUS_402_RE = re.compile(r"(?:^|[\s=:(])402(?:$|[\s:),])")

_CIRCUIT_LOCK = threading.Lock()
_circuit_open_until: float = 0.0
_circuit_reason: str = ""

WINDOW_SECONDS = 3600.0
_RATE_LOCK = threading.Lock()
_RATE_BUCKETS: dict[tuple[str, str], deque[float]] = {}


def is_quota_exhausted_signal(
    *,
    status_code: Optional[int] = None,
    error_text: str = "",
) -> bool:
    if status_code == 402:
        return True
    lower = (error_text or "").strip().lower()
    if not lower:
        return False
    if _STATUS_402_RE.search(lower):
        return True
    return any(kw in lower for kw in _QUOTA_KEYWORDS)


def is_non_retryable_ai_error(exc: BaseException) -> bool:
    """判断异常是否属于已熔断/配额耗尽/功能关闭，禁止 retry_with_backoff 重试。"""
    if isinstance(exc, AiGuardError):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code is None and getattr(exc, "response", None) is not None:
        status_code = getattr(exc.response, "status_code", None)
    return is_quota_exhausted_signal(status_code=status_code, error_text=str(exc))


def trip_ai_circuit(reason: str = "", cooldown_seconds: Optional[int] = None) -> float:
    """触发上游 AI 额度冷却熔断。"""
    global _circuit_open_until, _circuit_reason
    cooldown = (
        get_ai_quota_cooldown_seconds()
        if cooldown_seconds is None
        else int(cooldown_seconds)
    )
    with _CIRCUIT_LOCK:
        if cooldown > 0:
            _circuit_open_until = time.monotonic() + cooldown
            _circuit_reason = reason
        else:
            _circuit_open_until = 0.0
            _circuit_reason = ""
        return _circuit_open_until


def is_ai_circuit_tripped() -> bool:
    with _CIRCUIT_LOCK:
        return time.monotonic() < _circuit_open_until


def ensure_ai_circuit_open() -> None:
    if is_ai_circuit_tripped():
        raise AiQuotaExhaustedError()


def reset_ai_circuit() -> None:
    """重置上游 AI 额度冷却熔断（更新 API Key 后立即恢复）。"""
    global _circuit_open_until, _circuit_reason
    with _CIRCUIT_LOCK:
        _circuit_open_until = 0.0
        _circuit_reason = ""


def reset_ai_rate_limiter() -> None:
    """清空匿名 IP 限流滑动窗口（供测试使用）。"""
    with _RATE_LOCK:
        _RATE_BUCKETS.clear()


def reset_ai_guard() -> None:
    reset_ai_circuit()
    reset_ai_rate_limiter()


def handle_upstream_quota_error(
    *,
    status_code: Optional[int] = None,
    error_text: str = "",
    provider: str = "",
) -> None:
    """若上游返回 402 或余额/额度关键词，立即触发熔断并抛出 AiQuotaExhaustedError。"""
    if is_quota_exhausted_signal(status_code=status_code, error_text=error_text):
        trip_ai_circuit(reason=f"{provider}:{status_code}:{(error_text or '')[:120]}")
        raise AiQuotaExhaustedError()


def handle_upstream_quota_exception(exc: BaseException, *, provider: str = "") -> None:
    """识别上游 SDK 异常中的配额耗尽信号并触发熔断。"""
    if isinstance(exc, AiGuardError):
        raise exc
    status_code = getattr(exc, "status_code", None)
    if status_code is None and getattr(exc, "response", None) is not None:
        status_code = getattr(exc.response, "status_code", None)
    handle_upstream_quota_error(
        status_code=status_code,
        error_text=str(exc),
        provider=provider,
    )


def _should_skip_rate_limit(request: Request) -> tuple[bool, str]:
    forwarded = (request.headers.get("x-forwarded-for") or "").strip()
    real_ip = (request.headers.get("x-real-ip") or "").strip()
    client_host = (request.client.host if request.client else "") or ""
    force_in_tests = os.getenv("FORCE_ANON_RATE_LIMIT_IN_TESTS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if forwarded:
        ip = forwarded.split(",")[0].strip() or client_host or "unknown"
        return False, ip
    if real_ip:
        return False, real_ip
    if client_host == "testclient" and not force_in_tests:
        return True, client_host
    return False, (client_host or "unknown")


def check_anonymous_rate_limit(
    request: Request,
    current_user: Optional[AppUser],
    *,
    bucket: Literal["import", "rewrite"],
) -> None:
    """对匿名请求按 IP + 桶（import/rewrite）执行 3600 秒滑动窗口限流。"""
    if current_user is not None:
        return

    skip, ip = _should_skip_rate_limit(request)
    if skip:
        return

    limit = (
        get_anon_ai_import_hourly_limit()
        if bucket == "import"
        else get_anon_ai_rewrite_hourly_limit()
    )
    now = time.monotonic()
    cutoff = now - WINDOW_SECONDS
    key = (bucket, ip)

    with _RATE_LOCK:
        dq = _RATE_BUCKETS.get(key)
        if dq is None:
            dq = deque()
            _RATE_BUCKETS[key] = dq
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if len(dq) >= limit:
            raise AiRateLimitedError()
        dq.append(now)
        if len(_RATE_BUCKETS) > 10000:
            stale = [k for k, v in _RATE_BUCKETS.items() if not v or v[-1] <= cutoff]
            for k in stale:
                _RATE_BUCKETS.pop(k, None)


def check_ai_guard(
    request: Request,
    current_user: Optional[AppUser],
    *,
    bucket: Literal["import", "rewrite"],
) -> None:
    """统一执行 AI 开关检查、配额熔断检查与匿名 IP 限流检查。"""
    if not is_editor_ai_enabled():
        raise AiFeatureDisabledError()
    ensure_ai_circuit_open()
    check_anonymous_rate_limit(request, current_user, bucket=bucket)


async def _resolve_effective_user(
    request: Request,
    current_user: Optional[AppUser],
) -> Optional[AppUser]:
    if current_user is not None:
        return current_user
    overrides = getattr(request.app, "dependency_overrides", None)
    if not overrides:
        return None
    for mod_name in ("middleware.auth", "backend.middleware.auth"):
        mod = sys.modules.get(mod_name)
        dep = getattr(mod, "get_current_user_optional", None) if mod else None
        if dep is not None and dep is not get_current_user_optional and dep in overrides:
            res = overrides[dep]()
            if inspect.isawaitable(res):
                res = await res
            return res
    return None


async def require_ai_import(
    request: Request,
    current_user: Optional[AppUser] = Depends(get_current_user_optional),
) -> None:
    user = await _resolve_effective_user(request, current_user)
    check_ai_guard(request, user, bucket="import")


async def require_ai_rewrite(
    request: Request,
    current_user: Optional[AppUser] = Depends(get_current_user_optional),
) -> None:
    user = await _resolve_effective_user(request, current_user)
    check_ai_guard(request, user, bucket="rewrite")
