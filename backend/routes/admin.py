"""
后台管理路由
"""
import os
import logging
from urllib.parse import urlparse
import importlib

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from sse_starlette.sse import EventSourceResponse

from database import get_db
from models import BetterAuthEntitlement, RenderPDFRequest, Resume
from middleware.auth import AppUser, require_admin_only

router = APIRouter(prefix="/api/admin", tags=["Admin"])
logger = logging.getLogger("backend")


class PDFRenderModeLogRequest(BaseModel):
    from_mode: str
    to_mode: str


def _format_admin_user(
    *,
    user_id: str,
    email: str | None,
    name: str | None,
    role: str | None,
    created_at,
    pdf_download_count: int | None,
    resume_count: int | None,
) -> dict:
    return {
        "id": user_id,
        "username": name or (email.split("@")[0] if email else ""),
        "email": email,
        "role": role or "user",
        "created_at": str(created_at) if created_at else None,
        "pdf_download_count": int(pdf_download_count or 0),
        "resume_count": int(resume_count or 0),
    }


@router.get("/stats/users")
def get_user_stats(
    _current_user: AppUser = Depends(require_admin_only),
    db: Session = Depends(get_db),
):
    # 以 BetterAuth "user" 表为准（所有登录用户），与用户列表口径一致；
    # 无 BetterAuth "user" 表（如本地 SQLite）时回退到 BetterAuthEntitlement。
    try:
        total_users = db.execute(text('SELECT count(*) FROM "user"')).scalar() or 0
    except SQLAlchemyError:
        db.rollback()
        total_users = db.query(BetterAuthEntitlement).count()
    return {
        "total_users": int(total_users),
    }


@router.get("/users")
def list_users(
    _current_user: AppUser = Depends(require_admin_only),
    db: Session = Depends(get_db),
):
    # 以 BetterAuth "user" 表为准（所有登录用户），role/pdf 从 entitlements 读（2026-07-17 身份统一，legacy users 已退役）。
    # 无 BetterAuth "user" 表（如本地 SQLite）时回退到 BetterAuthEntitlement + resumes 统计。
    try:
        rows = db.execute(
            text(
                '''
                SELECT bu.id,
                       bu.email,
                       bu.name,
                       COALESCE(e.role, 'user')             AS role,
                       bu."createdAt"                       AS created_at,
                       COALESCE(e.pdf_download_count, 0)    AS pdf_download_count,
                       COALESCE(rc.resume_count, 0)         AS resume_count
                FROM "user" bu
                LEFT JOIN better_auth_entitlements e ON e.better_auth_user_id = bu.id
                LEFT JOIN (
                    SELECT user_id, COUNT(*) AS resume_count
                    FROM resumes
                    GROUP BY user_id
                ) rc ON rc.user_id = bu.id
                ORDER BY CASE COALESCE(e.role, 'user') WHEN 'admin' THEN 0 WHEN 'staff' THEN 1 WHEN 'member' THEN 2 ELSE 3 END,
                         bu."createdAt" ASC
                '''
            )
        ).fetchall()
        users = [
            _format_admin_user(
                user_id=r[0],
                email=r[1],
                name=r[2],
                role=r[3],
                created_at=r[4],
                pdf_download_count=r[5],
                resume_count=r[6],
            )
            for r in rows
        ]
    except SQLAlchemyError:
        db.rollback()
        entitlements = db.query(BetterAuthEntitlement).all()
        resume_counts = dict(
            db.query(Resume.user_id, func.count(Resume.id))
            .group_by(Resume.user_id)
            .all()
        )
        role_rank = {"admin": 0, "staff": 1, "member": 2}
        entitlements.sort(
            key=lambda e: (
                role_rank.get(e.role or "user", 3),
                str(e.created_at or ""),
            )
        )
        users = [
            _format_admin_user(
                user_id=e.better_auth_user_id,
                email=e.email,
                name=e.name,
                role=e.role,
                created_at=e.created_at,
                pdf_download_count=e.pdf_download_count,
                resume_count=resume_counts.get(e.better_auth_user_id, 0),
            )
            for e in entitlements
        ]

    return {
        "total": len(users),
        "users": users,
    }


class SetRoleRequest(BaseModel):
    role: str


@router.patch("/users/{better_auth_user_id}/role")
def set_user_role(
    better_auth_user_id: str,
    body: SetRoleRequest,
    _current_user: AppUser = Depends(require_admin_only),
    db: Session = Depends(get_db),
):
    """给指定 BetterAuth 用户分配角色（role 直写 better_auth_entitlements，2026-07-17 身份统一）。"""
    allowed = {"user", "member", "staff", "admin"}
    if body.role not in allowed:
        raise HTTPException(status_code=400, detail=f"role 必须是 {sorted(allowed)} 之一")

    user_table_available = True
    email = None
    name = None
    try:
        row = db.execute(
            text('SELECT email, name FROM "user" WHERE id = :id'),
            {"id": better_auth_user_id},
        ).fetchone()
    except SQLAlchemyError:
        db.rollback()
        user_table_available = False
        row = None

    if user_table_available:
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")
        email, name = row[0], row[1]

    entitlement = (
        db.query(BetterAuthEntitlement)
        .filter(BetterAuthEntitlement.better_auth_user_id == better_auth_user_id)
        .first()
    )
    if not user_table_available:
        if not entitlement:
            raise HTTPException(status_code=404, detail="用户不存在")
        entitlement.role = body.role
        email = entitlement.email
    elif entitlement:
        entitlement.role = body.role
    else:
        db.add(
            BetterAuthEntitlement(
                better_auth_user_id=better_auth_user_id,
                email=email,
                name=name,
                role=body.role,
            )
        )

    db.commit()
    logger.info("[Admin] role assigned user=%s -> %s by=%s", email, body.role, _current_user.email)
    return {"ok": True, "email": email, "role": body.role}


@router.post("/pdf/render-mode/log")
async def log_pdf_render_mode_change(
    body: PDFRenderModeLogRequest,
    request: Request,
    current_user: AppUser = Depends(require_admin_only),
):
    logger.info(
        "[Admin PDF] render mode changed user=%s role=%s from=%s to=%s client=%s referer=%s",
        current_user.email,
        current_user.role,
        body.from_mode,
        body.to_mode,
        request.client.host if request.client else "-",
        request.headers.get("referer") or "-",
    )
    return {"ok": True}


def _get_remote_pdf_render_base_url() -> str:
    base_url = os.getenv("REMOTE_PDF_RENDER_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        raise HTTPException(status_code=503, detail="未配置远程 PDF 渲染服务")
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        base_url = f"https://{base_url}"
    return base_url


def _build_remote_pdf_headers(request: Request) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    passthrough_headers = [
        "Authorization",
        "X-PDF-Trace-Id",
        "X-PDF-Trace-Source",
        "X-PDF-Trace-Trigger",
        "X-Agent-Session-Id",
        "X-Agent-Resume-Id",
    ]
    for header_name in passthrough_headers:
        header_value = request.headers.get(header_name)
        if header_value:
            headers[header_name] = header_value

    remote_token = os.getenv("REMOTE_PDF_RENDER_TOKEN", "").strip()
    if remote_token:
        headers["X-Remote-Render-Token"] = remote_token
    return headers


def _is_self_remote_target(base_url: str, request: Request) -> bool:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").strip().lower()
    port = parsed.port
    backend_port = int(os.getenv("BACKEND_PORT", "9000"))
    request_host = (request.url.hostname or "").strip().lower()
    request_port = request.url.port or backend_port

    local_hosts = {"127.0.0.1", "localhost", "0.0.0.0", request_host}
    target_port = port or (443 if parsed.scheme == "https" else 80)
    return host in local_hosts and target_port == request_port


async def _dispatch_local_pdf(
    *,
    path: str,
    body: RenderPDFRequest,
    request: Request,
    current_user: AppUser,
    db: Session,
):
    logger.info(
        "[Admin PDF] self-target detected, bypass proxy path=%s trace_id=%s",
        path,
        request.headers.get("X-PDF-Trace-Id") or "-",
    )
    pdf_route = importlib.import_module("backend.routes.pdf")
    if path.endswith("/stream"):
        return await pdf_route.render_pdf_stream(body, request, current_user, db)
    return await pdf_route.render_pdf(body, request, current_user, db)


async def _proxy_remote_pdf(
    *,
    path: str,
    body: RenderPDFRequest,
    request: Request,
    current_user: AppUser,
    db: Session,
):
    base_url = _get_remote_pdf_render_base_url()
    if _is_self_remote_target(base_url, request):
        return await _dispatch_local_pdf(
            path=path,
            body=body,
            request=request,
            current_user=current_user,
            db=db,
        )

    target_url = f"{base_url}{path}"
    payload = body.model_dump() if hasattr(body, "model_dump") else body.dict()
    headers = _build_remote_pdf_headers(request)
    timeout = httpx.Timeout(connect=15.0, read=300.0, write=60.0, pool=15.0)
    logger.info(
        "[Admin PDF] remote proxy start path=%s trace_id=%s target=%s section_order=%s",
        path,
        request.headers.get("X-PDF-Trace-Id") or "-",
        target_url,
        body.section_order,
    )

    if path.endswith("/stream"):
        logger.info(
            "[Admin PDF] remote stream uses local SSE wrapper trace_id=%s target=%s",
            request.headers.get("X-PDF-Trace-Id") or "-",
            f"{base_url}/api/pdf/render",
        )

        async def _generate():
            trace_id = request.headers.get("X-PDF-Trace-Id") or "-"
            yield dict(event="start", data="开始远程生成PDF...")
            yield dict(event="progress", data="正在请求远程渲染服务...")
            try:
                async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                    upstream = await client.post(
                        f"{base_url}/api/pdf/render",
                        json=payload,
                        headers=headers,
                    )
                    logger.info(
                        "[Admin PDF] remote wrapped render response status=%s trace_id=%s content_type=%s",
                        upstream.status_code,
                        trace_id,
                        upstream.headers.get("content-type"),
                    )
                    if upstream.status_code >= 400:
                        detail = upstream.text
                        yield dict(event="error", data=detail or f"远程渲染失败: HTTP {upstream.status_code}")
                        return

                    yield dict(event="progress", data="远程服务已返回 PDF")
                    pdf_hex = upstream.content.hex()
                    yield dict(event="pdf", data=pdf_hex)
            except Exception as exc:
                logger.exception(
                    "[Admin PDF] remote wrapped stream failed trace_id=%s error=%s",
                    trace_id,
                    exc,
                )
                yield dict(event="error", data=f"远程渲染代理失败: {exc}")

        return EventSourceResponse(_generate())

    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        try:
            upstream = await client.post(target_url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning(
                "[Admin PDF] remote render unreachable trace_id=%s target=%s error=%s",
                request.headers.get("X-PDF-Trace-Id") or "-",
                target_url,
                exc,
            )
            raise HTTPException(
                status_code=502,
                detail=f"远程 PDF 渲染服务不可达: {exc}",
            ) from exc
        logger.info(
            "[Admin PDF] remote response status=%s trace_id=%s content_type=%s",
            upstream.status_code,
            request.headers.get("X-PDF-Trace-Id") or "-",
            upstream.headers.get("content-type"),
        )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type") or None,
            headers={
                key: value
                for key, value in {
                    "Content-Disposition": upstream.headers.get("content-disposition"),
                    "X-Render-Time": upstream.headers.get("x-render-time"),
                    "X-PDF-Trace-Id": upstream.headers.get("x-pdf-trace-id"),
                }.items()
                if value
            },
        )


@router.post("/pdf/render")
async def remote_render_pdf(
    body: RenderPDFRequest,
    request: Request,
    current_user: AppUser = Depends(require_admin_only),
    db: Session = Depends(get_db),
):
    logger.info(
        "[Admin PDF] local request accepted user=%s role=%s mode=remote path=/api/admin/pdf/render trace_id=%s",
        current_user.email,
        current_user.role,
        request.headers.get("X-PDF-Trace-Id") or "-",
    )
    return await _proxy_remote_pdf(
        path="/api/pdf/render",
        body=body,
        request=request,
        current_user=current_user,
        db=db,
    )


@router.post("/pdf/render/stream")
async def remote_render_pdf_stream(
    body: RenderPDFRequest,
    request: Request,
    current_user: AppUser = Depends(require_admin_only),
    db: Session = Depends(get_db),
):
    logger.info(
        "[Admin PDF] local request accepted user=%s role=%s mode=remote path=/api/admin/pdf/render/stream trace_id=%s",
        current_user.email,
        current_user.role,
        request.headers.get("X-PDF-Trace-Id") or "-",
    )
    return await _proxy_remote_pdf(
        path="/api/pdf/render/stream",
        body=body,
        request=request,
        current_user=current_user,
        db=db,
    )
