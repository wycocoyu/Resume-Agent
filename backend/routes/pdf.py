"""
PDF 渲染路由 - 使用 LaTeX 生成专业简历 PDF
"""
import base64
import hashlib
import io
import json
import time
import logging
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Any, List
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

try:
    from models import RenderPDFRequest
    from database import get_db
    from middleware.auth import AppUser, get_current_user, get_current_user_optional
    from services.pdf_download_quota import (
        assert_pdf_download_allowed,
        build_quota_payload,
        record_successful_pdf_download,
    )
except ImportError:
    from backend.models import RenderPDFRequest
    from backend.database import get_db
    from backend.middleware.auth import AppUser, get_current_user, get_current_user_optional
    from backend.services.pdf_download_quota import (
        assert_pdf_download_allowed,
        build_quota_payload,
        record_successful_pdf_download,
    )

router = APIRouter(prefix="/api", tags=["PDF"])
logger = logging.getLogger("backend")

# PDF 事件的载荷编码。
#
# 历史实现把 PDF 字节 hex 编码后塞进 SSE 的 data 字段，体积是原始字节的 2 倍，
# 在跨区域链路上代价明显；base64 只有 4/3。但**老前端只会按 hex 解析**，
# 默认切换会让所有未刷新的页面拿到损坏的 PDF。
#
# 因此编码改为按请求头显式协商：
#   - 不带该头（老前端 / admin 远程流 / 其它调用方）→ 仍然发 hex 的 `pdf` 事件，
#     与改动前逐字节一致；
#   - 带头且值为 base64（新前端）→ 发 base64 的 `pdf_b64` 事件。
# 新前端同时能解析两种事件，所以新旧组合的任意搭配都能正常工作。
PDF_PAYLOAD_ENCODING_HEADER = "X-PDF-Payload-Encoding"
PDF_PAYLOAD_BASE64 = "base64"
PDF_EVENT_HEX = "pdf"
PDF_EVENT_BASE64 = "pdf_b64"


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LATEX_FINGERPRINT_FILES = (
    _PROJECT_ROOT / "latex-resume-template" / "resume.cls",
    _PROJECT_ROOT / "backend" / "latex_sections.py",
    _PROJECT_ROOT / "backend" / "latex_generator.py",
    _PROJECT_ROOT / "backend" / "html_to_latex.py",
)
_TEMPLATE_FP_LOCK = threading.Lock()
_TEMPLATE_FP_STAT_KEY: Optional[tuple] = None
_TEMPLATE_FP_VALUE: str = ""


def _get_latex_template_fingerprint() -> str:
    """Compute a fast stat-cached content SHA256 across core LaTeX template/generator files."""
    global _TEMPLATE_FP_STAT_KEY, _TEMPLATE_FP_VALUE
    stats = []
    for path in _LATEX_FINGERPRINT_FILES:
        try:
            st = path.stat()
            stats.append((str(path), st.st_mtime_ns, st.st_size))
        except OSError:
            stats.append((str(path), -1, -1))
    stat_key = tuple(stats)

    with _TEMPLATE_FP_LOCK:
        if _TEMPLATE_FP_STAT_KEY == stat_key and _TEMPLATE_FP_VALUE:
            return _TEMPLATE_FP_VALUE
        hasher = hashlib.sha256()
        for path in _LATEX_FINGERPRINT_FILES:
            hasher.update(path.name.encode("utf-8"))
            try:
                hasher.update(path.read_bytes())
            except OSError:
                hasher.update(b"<missing>")
        fp = hasher.hexdigest()[:16]
        _TEMPLATE_FP_STAT_KEY = stat_key
        _TEMPLATE_FP_VALUE = fp
        return fp


class PDFCache:
    """
    基于 LRU 策略的 PDF 内存缓存
    使用请求参数的规范化 JSON SHA256 作为缓存键
    """
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._lock = threading.Lock()

    def get_cache_key(self, resume_data: Any, section_order: Optional[List[Any]] = None) -> str:
        payload = {
            "resume": resume_data,
            "order": section_order or [],
            "tpl": _get_latex_template_fingerprint(),
        }
        normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def get_latex_cache_key(self, latex_content: str) -> str:
        fp = _get_latex_template_fingerprint()
        return hashlib.sha256(f"{fp}::{latex_content}".encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[bytes]:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def put(self, key: str, pdf_bytes: bytes) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            else:
                if len(self._cache) >= self.max_size:
                    self._cache.popitem(last=False)
            self._cache[key] = pdf_bytes

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)


_pdf_cache = PDFCache(max_size=100)


def _encode_pdf_event(pdf_bytes: bytes, requested_encoding: str) -> dict:
    """把 PDF 字节封装成 SSE 事件；缺省或无法识别的编码一律回退 hex。"""
    if (requested_encoding or "").strip().lower() == PDF_PAYLOAD_BASE64:
        return dict(
            event=PDF_EVENT_BASE64,
            data=base64.b64encode(pdf_bytes).decode("ascii"),
        )
    return dict(event=PDF_EVENT_HEX, data=pdf_bytes.hex())


def _resolve_template_dir() -> Path:
    current_dir = Path(__file__).resolve().parent
    return current_dir.parents[1] / "latex-resume-template"


def _prepare_latex_content(resume_data, section_order):
    try:
        from backend.latex_generator import json_to_latex
    except ImportError:
        from latex_generator import json_to_latex
    return json_to_latex(resume_data, section_order)


def _compile_pdf_bytes(latex_content: str, template_dir: Path, resume_data):
    try:
        from backend.latex_generator import compile_latex_to_pdf
    except ImportError:
        from latex_generator import compile_latex_to_pdf
    return compile_latex_to_pdf(latex_content, template_dir, resume_data=resume_data).getvalue()


def _resume_brief(resume_data):
    if not isinstance(resume_data, dict):
        return {"type": type(resume_data).__name__}
    return {
        "keys": list(resume_data.keys())[:20],
        "name": resume_data.get("name"),
        "has_basic": "basic" in resume_data,
        "has_experience": "experience" in resume_data,
        "has_projects": "projects" in resume_data,
    }


class CompileLatexRequest(BaseModel):
    """LaTeX 编译请求"""
    latex_content: str


@router.get("/pdf/quota")
async def get_pdf_download_quota(
    current_user: AppUser = Depends(get_current_user),
):
    """查询当前用户 PDF 下载配额。"""
    return build_quota_payload(current_user)


@router.post("/pdf/downloads/record")
async def record_pdf_download(
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """记录一次真实 PDF 下载。预览/渲染不消耗下载次数。"""
    before_quota = build_quota_payload(current_user)
    logger.info(
        "[PDF DOWNLOAD][record_request] user_id=%s username=%s role=%s used=%s limit=%s remaining=%s",
        current_user.id,
        current_user.email,
        current_user.role,
        before_quota["used"],
        before_quota["limit"],
        before_quota["remaining"],
    )
    try:
        assert_pdf_download_allowed(current_user)
        record_successful_pdf_download(current_user, db)
    except HTTPException as exc:
        detail = exc.detail
        code = detail.get("code") if isinstance(detail, dict) else None
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
        logger.warning(
            "[PDF DOWNLOAD][record_denied] status=%s code=%s message=%s user_id=%s "
            "username=%s role=%s used=%s limit=%s remaining=%s",
            exc.status_code,
            code or "-",
            message,
            current_user.id,
            current_user.email,
            current_user.role,
            before_quota["used"],
            before_quota["limit"],
            before_quota["remaining"],
        )
        raise

    return build_quota_payload(current_user)


@router.post("/pdf/render")
async def render_pdf(
    body: RenderPDFRequest,
    request: Request,
    current_user: Optional[AppUser] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """
    将简历 JSON 渲染为 PDF 并返回
    使用 LaTeX (xelatex) 生成专业排版的简历
    优先命中 LRU 内存缓存加速
    """
    start_time = time.time()
    resume_data = body.resume
    trace_id = request.headers.get("X-PDF-Trace-Id") or f"backend-{int(start_time * 1000)}"
    trace_source = request.headers.get("X-PDF-Trace-Source") or "-"
    trace_trigger = request.headers.get("X-PDF-Trace-Trigger") or "-"
    client = request.client.host if request.client else "-"
    uid = current_user.id if current_user else "anon"
    urole = current_user.role if current_user else "anon"
    print(
        f"[PDF TRACE][render:request] trace_id={trace_id} source={trace_source} trigger={trace_trigger} "
        f"user_id={uid} role={urole} "
        f"session_id={request.headers.get('X-Agent-Session-Id') or '-'} "
        f"resume_id={request.headers.get('X-Agent-Resume-Id') or '-'} client={client} "
        f"origin={request.headers.get('origin') or '-'} referer={request.headers.get('referer') or '-'} "
        f"section_order={body.section_order} resume_brief={_resume_brief(resume_data)}"
    )

    cache_key = _pdf_cache.get_cache_key(resume_data, body.section_order)
    cached_pdf = _pdf_cache.get(cache_key)
    if cached_pdf:
        render_time = time.time() - start_time
        quota = build_quota_payload(current_user) if current_user else None
        print(
            f"[PDF TRACE][render:cache-hit] trace_id={trace_id} elapsed={render_time:.4f}s "
            f"bytes={len(cached_pdf)} user_id={uid}"
        )
        return StreamingResponse(
            iter([cached_pdf]),
            media_type="application/pdf",
            headers={
                "Content-Disposition": 'inline; filename="resume.pdf"',
                "X-Render-Time": f"{render_time:.4f}",
                "X-PDF-Cache": "HIT",
                "X-PDF-Trace-Id": trace_id,
                "X-PDF-Download-Remaining": str(quota["remaining"] if quota and quota["remaining"] is not None else -1),
            },
        )

    try:
        latex_content = await run_in_threadpool(_prepare_latex_content, resume_data, body.section_order)
        pdf_bytes = await run_in_threadpool(
            _compile_pdf_bytes,
            latex_content,
            _resolve_template_dir(),
            resume_data,
        )

        _pdf_cache.put(cache_key, pdf_bytes)

        render_time = time.time() - start_time
        quota = build_quota_payload(current_user) if current_user else None
        print(
            f"[PDF TRACE][render:done] trace_id={trace_id} elapsed={render_time:.2f}s "
            f"bytes={len(pdf_bytes)} user_id={uid} pdf_used={quota['used'] if quota else '-'}"
        )

        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={
                "Content-Disposition": 'inline; filename="resume.pdf"',
                "X-Render-Time": str(render_time),
                "X-PDF-Cache": "MISS",
                "X-PDF-Trace-Id": trace_id,
                "X-PDF-Download-Remaining": str(quota["remaining"] if quota and quota["remaining"] is not None else -1),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"[PDF TRACE][render:error] trace_id={trace_id} error={e}")
        raise HTTPException(status_code=500, detail=f"PDF 渲染失败: {e}")


@router.post("/pdf/render/stream")
async def render_pdf_stream(
    body: RenderPDFRequest,
    request: Request,
    current_user: Optional[AppUser] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """
    流式渲染PDF，提供实时进度反馈
    """
    session_id = request.headers.get("X-Agent-Session-Id")
    resume_id = request.headers.get("X-Agent-Resume-Id")
    trace_id = request.headers.get("X-PDF-Trace-Id") or f"backend-s-{int(time.time() * 1000)}"
    trace_source = request.headers.get("X-PDF-Trace-Source") or "-"
    trace_trigger = request.headers.get("X-PDF-Trace-Trigger") or "-"
    payload_encoding = request.headers.get(PDF_PAYLOAD_ENCODING_HEADER) or "-"
    client = request.client.host if request.client else "-"

    async def generate_pdf():
        resume_data = body.resume
        uid = current_user.id if current_user else "anon"
        urole = current_user.role if current_user else "anon"
        print(
            f"[PDF TRACE][stream:request] trace_id={trace_id} source={trace_source} trigger={trace_trigger} "
            f"user_id={uid} role={urole} payload_encoding={payload_encoding} "
            f"session_id={session_id or '-'} resume_id={resume_id or '-'} client={client} "
            f"origin={request.headers.get('origin') or '-'} referer={request.headers.get('referer') or '-'} "
            f"section_order={body.section_order} resume_brief={_resume_brief(resume_data)}"
        )

        try:
            cache_key = _pdf_cache.get_cache_key(resume_data, body.section_order)
            cached_pdf = _pdf_cache.get(cache_key)
            if cached_pdf:
                print(f"[PDF TRACE][stream:cache-hit] trace_id={trace_id}")
                yield dict(event="start", data="开始生成PDF...")
                yield dict(event="progress", data="命中渲染缓存，即时就绪 (0.0s)")
                quota = build_quota_payload(current_user) if current_user else None
                pdf_event = _encode_pdf_event(cached_pdf, payload_encoding)
                yield pdf_event
                if quota:
                    yield dict(
                        event="quota",
                        data=str(
                            {
                                "remaining": quota["remaining"],
                                "used": quota["used"],
                                "limit": quota["limit"],
                            }
                        ),
                    )
                print(
                    f"[PDF TRACE][stream:done-cached] trace_id={trace_id} session_id={session_id or '-'} "
                    f"resume_id={resume_id or '-'} event={pdf_event['event']} size={len(cached_pdf)} bytes user_id={uid}"
                )
                return

            print(f"[PDF TRACE][stream:start] trace_id={trace_id}")
            yield dict(event="start", data="开始生成PDF...")

            latex_start = time.time()
            yield dict(event="progress", data="正在生成LaTeX代码...")

            latex_content = await run_in_threadpool(
                _prepare_latex_content,
                resume_data,
                body.section_order,
            )
            latex_time = time.time() - latex_start
            print(
                f"[PDF TRACE][stream:latex-ready] trace_id={trace_id} "
                f"elapsed={latex_time:.2f}s latex_chars={len(latex_content)}"
            )
            yield dict(event="progress", data=f"LaTeX代码生成完成 ({latex_time:.1f}s)")

            compile_start = time.time()
            yield dict(event="progress", data="正在编译PDF（可能需要几秒）...")

            try:
                pdf_bytes = await run_in_threadpool(
                    _compile_pdf_bytes,
                    latex_content,
                    _resolve_template_dir(),
                    resume_data,
                )
                _pdf_cache.put(cache_key, pdf_bytes)
                compile_time = time.time() - compile_start
                print(
                    f"[PDF TRACE][stream:compile-done] trace_id={trace_id} "
                    f"elapsed={compile_time:.2f}s pdf_bytes={len(pdf_bytes)}"
                )
                yield dict(event="progress", data=f"PDF编译完成 ({compile_time:.1f}s)")

                quota = build_quota_payload(current_user) if current_user else None

                pdf_event = _encode_pdf_event(pdf_bytes, payload_encoding)
                yield pdf_event
                if quota:
                    yield dict(
                        event="quota",
                        data=str(
                            {
                                "remaining": quota["remaining"],
                                "used": quota["used"],
                                "limit": quota["limit"],
                            }
                        ),
                    )
                print(
                    f"[PDF TRACE][stream:done] trace_id={trace_id} session_id={session_id or '-'} "
                    f"resume_id={resume_id or '-'} event={pdf_event['event']} size={len(pdf_bytes)} bytes user_id={uid} "
                    f"pdf_used={quota['used'] if quota else '-'}"
                )

            except HTTPException as exc:
                detail = exc.detail
                if isinstance(detail, dict):
                    message = detail.get("message") or str(detail)
                else:
                    message = str(detail)
                yield dict(event="error", data=message)

            except Exception as e:
                import traceback
                error_msg = f"LaTeX编译错误: {str(e)}\n{traceback.format_exc()}"
                print(f"[PDF TRACE][stream:compile-error] trace_id={trace_id} detail={error_msg}")
                error_data = str(e) if len(str(e)) <= 5000 else str(e)[:5000] + "...(错误信息过长，已截断)"
                yield dict(event="error", data=error_data)

        except HTTPException as exc:
            detail = exc.detail
            message = detail.get("message") if isinstance(detail, dict) else str(detail)
            yield dict(event="error", data=message or "PDF 下载次数已达上限")
        except Exception as e:
            import traceback
            error_msg = f"PDF生成失败: {str(e)}\n{traceback.format_exc()}"
            print(f"[PDF TRACE][stream:error] trace_id={trace_id} detail={error_msg}")
            error_data = str(e) if len(str(e)) <= 5000 else str(e)[:5000] + "...(错误信息过长，已截断)"
            yield dict(event="error", data=error_data)

    return EventSourceResponse(generate_pdf())


@router.post("/pdf/compile-latex")
async def compile_latex(
    body: CompileLatexRequest,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    直接编译 LaTeX 源代码为 PDF
    使用 slager 原版样式（与 slager.link 完全一致）
    优先命中 LRU 内存缓存
    """
    start_time = time.time()
    cache_key = _pdf_cache.get_latex_cache_key(body.latex_content)
    cached_pdf = _pdf_cache.get(cache_key)
    if cached_pdf:
        render_time = time.time() - start_time
        return StreamingResponse(
            io.BytesIO(cached_pdf),
            media_type='application/pdf',
            headers={
                'Content-Disposition': 'inline; filename="resume.pdf"',
                'X-Render-Time': f"{render_time:.4f}",
                'X-PDF-Cache': 'HIT',
            }
        )

    try:
        try:
            from backend.latex_compiler import compile_latex_raw
        except ImportError:
            from latex_compiler import compile_latex_raw
        # subprocess.run(timeout=180) 是重阻塞，必须放线程池，否则冻结事件循环，
        # 连带同进程所有 asyncio.to_thread 结果回调（如 PDF 导入结构化）一起卡住。
        pdf_io = await run_in_threadpool(compile_latex_raw, body.latex_content)
        pdf_bytes = pdf_io.getvalue()
        _pdf_cache.put(cache_key, pdf_bytes)

        render_time = time.time() - start_time
        print(f"[LaTeX 编译] 完成，耗时: {render_time:.2f}秒, user_id={current_user.id}")

        return StreamingResponse(io.BytesIO(pdf_bytes), media_type='application/pdf', headers={
            'Content-Disposition': 'inline; filename="resume.pdf"',
            'X-Render-Time': str(render_time),
            'X-PDF-Cache': 'MISS',
        })
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_msg = f"LaTeX 编译失败: {str(e)}"
        print(f"[错误] {error_msg}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=error_msg)


@router.post("/pdf/compile-latex/stream")
async def compile_latex_stream(
    body: CompileLatexRequest,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    流式编译 LaTeX 源代码为 PDF，提供实时进度反馈
    """
    async def generate():
        try:
            cache_key = _pdf_cache.get_latex_cache_key(body.latex_content)
            cached_pdf = _pdf_cache.get(cache_key)
            if cached_pdf:
                yield dict(event="start", data="开始编译 LaTeX...")
                yield dict(event="progress", data="命中编译缓存，即时就绪 (0.0s)")
                yield dict(event="pdf", data=cached_pdf.hex())
                return

            yield dict(event="start", data="开始编译 LaTeX...")
            yield dict(event="progress", data="正在准备编译环境...")

            compile_start = time.time()

            try:
                from backend.latex_compiler import compile_latex_raw
            except ImportError:
                from latex_compiler import compile_latex_raw
            yield dict(event="progress", data="正在编译 PDF（可能需要几秒）...")

            # 同 /pdf/compile-latex：subprocess.run 必须放线程池，避免冻结事件循环。
            pdf_io = await run_in_threadpool(compile_latex_raw, body.latex_content)
            pdf_bytes = pdf_io.getvalue()
            _pdf_cache.put(cache_key, pdf_bytes)
            compile_time = time.time() - compile_start

            yield dict(event="progress", data=f"PDF 编译完成 ({compile_time:.1f}s)")

            pdf_hex = pdf_bytes.hex()
            yield dict(event="pdf", data=pdf_hex)
            print(f"[LaTeX 编译] 成功，大小: {len(pdf_hex)/2} 字节, user_id={current_user.id}")

        except HTTPException as exc:
            detail = exc.detail
            message = detail.get("message") if isinstance(detail, dict) else str(detail)
            yield dict(event="error", data=message or "PDF 下载次数已达上限")
        except Exception as e:
            import traceback
            error_msg = f"LaTeX 编译错误: {str(e)}"
            print(f"[错误] {error_msg}\n{traceback.format_exc()}")
            error_data = str(e) if len(str(e)) <= 5000 else str(e)[:5000] + "...(错误信息过长，已截断)"
            yield dict(event="error", data=error_data)

    return EventSourceResponse(generate())
