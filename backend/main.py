"""
FastAPI 后端入口
模块化重构版本

提供：
1) /api/health 健康检查
2) /api/ai/test 测试现有 LLM 是否可用
3) /api/resume/generate 一句话 → 结构化简历 JSON
4) /api/pdf/render 由简历 JSON 生成 PDF

启动命令：uvicorn backend.main:app --reload --port 9000
"""
import os
import sys
import importlib
import time
from pathlib import Path

# 兼容多种启动方式（uvicorn backend.main:app 或 uvicorn main:app）
# 确保项目根目录与 backend 目录都在 sys.path
CURRENT_DIR = Path(__file__).resolve().parent            # .../backend
PROJECT_ROOT = CURRENT_DIR.parent                        # 项目根 /app
for p in [PROJECT_ROOT, CURRENT_DIR]:
    p_str = str(p)
    if p_str not in sys.path:
        sys.path.insert(0, p_str)

# 加载环境变量
try:
    from dotenv import load_dotenv
    DOTENV_PATH = PROJECT_ROOT / ".env"
    load_dotenv(dotenv_path=str(DOTENV_PATH), override=True)
    load_dotenv(override=True)
except Exception:
    pass

from backend.core.local_network import ensure_local_no_proxy

ensure_local_no_proxy()

from backend.core.logger import bridge_std_logging_to_loguru, get_logger, setup_logging

LOG_MODE = os.getenv("LOG_MODE", "console")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = os.getenv("LOG_DIR", "logs/backend")

setup_logging(
    is_production=(LOG_MODE == "production"),
    log_level=LOG_LEVEL,
    log_dir=LOG_DIR,
)
logger = get_logger(__name__)

from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
import httpx
from backend.middleware.observability import register_observability_handlers

def import_module_candidates(candidates):
    """按候选列表依次尝试导入模块，避免多层嵌套 try/except。"""
    last_exc: Exception | None = None
    for name in candidates:
        try:
            return importlib.import_module(name)
        except ModuleNotFoundError as exc:
            last_exc = exc
            continue
    raise last_exc or ModuleNotFoundError(f"Cannot import any of: {candidates}")


# 导入路由模块（兼容包/脚本两种运行方式），优先使用绝对路径
routes_module = import_module_candidates(["backend.routes", "routes"])
health_router = routes_module.health_router
config_router = routes_module.config_router
resume_router = routes_module.resume_router
pdf_router = routes_module.pdf_router
share_router = routes_module.share_router
auth_router = routes_module.auth_router
better_auth_router = routes_module.better_auth_router
resumes_router = routes_module.resumes_router
logos_router = routes_module.logos_router
school_logos_router = routes_module.school_logos_router
photos_router = routes_module.photos_router
asr_router = routes_module.asr_router
semantic_search_router = routes_module.semantic_search_router
admin_router = routes_module.admin_router
leetcode_router = routes_module.leetcode_router
billing_router = routes_module.billing_router
jd_router = getattr(routes_module, "jd_router", None)

# 初始化 FastAPI 应用
app = FastAPI(title="Resume API")

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-LeetCode-ProgramRun"],
)
register_observability_handlers(app)

# 注册路由
app.include_router(health_router)

# TTS 路由（可选，如果 TTS 依赖已安装）
try:
    tts_router = routes_module.tts_router
    if tts_router is not None:
        app.include_router(tts_router)
        logger.info("[TTS] TTS 路由已注册，前缀: /api/tts")
    else:
        logger.warning("[TTS] TTS 路由未加载（TTS 依赖未安装）")
except Exception as exc:
    logger.warning(f"[TTS] TTS 路由注册失败: {exc}")
app.include_router(config_router)
app.include_router(resume_router)
app.include_router(pdf_router)
app.include_router(share_router)
app.include_router(auth_router)
app.include_router(better_auth_router)
app.include_router(resumes_router)
app.include_router(logos_router)
app.include_router(school_logos_router)
logger.info(
    "[路由] logos_router loaded: module=%s file=%s",
    getattr(logos_router, "__module__", "unknown"),
    getattr(routes_module, "__file__", "unknown"),
)
app.include_router(photos_router)
app.include_router(asr_router)
app.include_router(semantic_search_router)
app.include_router(admin_router)
app.include_router(leetcode_router)
app.include_router(billing_router)
if jd_router:
    app.include_router(jd_router)

# 注册官方 CocoCV MCP Server (Feature 19 / Issue #57)
try:
    from backend.mcp.server import create_sse_app
    app.mount("/mcp", create_sse_app())
    logger.info("[MCP] Official CocoCV MCP Server mounted at /mcp")
except Exception as exc:
    logger.warning(f"[MCP] Failed to mount MCP SSE app: {exc}")

# 注册 resume agent 路由（合并后）
AGENT_BACKEND_BASE_URL = os.getenv("AGENT_BACKEND_BASE_URL", "").strip().rstrip("/")

if AGENT_BACKEND_BASE_URL:
    logger.info(f"[合并] 启用 Agent 反向代理: /api/agent/** -> {AGENT_BACKEND_BASE_URL}")

    @app.api_route("/api/agent", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    @app.api_route("/api/agent/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    async def proxy_agent(request: Request, path: str = ""):
        upstream_url = f"{AGENT_BACKEND_BASE_URL}/api/agent"
        if path:
            upstream_url = f"{upstream_url}/{path}"
        if request.url.query:
            upstream_url = f"{upstream_url}?{request.url.query}"

        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in {"host", "content-length", "connection"}
        }
        body = await request.body()

        timeout = httpx.Timeout(connect=15.0, read=300.0, write=60.0, pool=15.0)
        client = httpx.AsyncClient(timeout=timeout, trust_env=False)
        try:
            req = client.build_request(
                method=request.method,
                url=upstream_url,
                headers=headers,
                content=body if body else None,
            )
            upstream = await client.send(req, stream=True)
        except Exception as exc:
            await client.aclose()
            logger.error(f"[合并] Agent 代理请求失败: {exc}")
            hint = (
                f"Agent upstream unreachable: {AGENT_BACKEND_BASE_URL}. "
                "Please ensure agent-backend is running "
                "(e.g. uvicorn app.main:app --host 127.0.0.1 --port 9100)."
            )
            return JSONResponse(
                content={"code": "AGENT_PROXY_ERROR", "message": hint},
                status_code=502,
            )

        content_type = upstream.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            async def _stream():
                try:
                    async for chunk in upstream.aiter_bytes():
                        yield chunk
                finally:
                    await upstream.aclose()
                    await client.aclose()

            return StreamingResponse(
                _stream(),
                status_code=upstream.status_code,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )

        try:
            payload = await upstream.aread()
            return Response(
                content=payload,
                status_code=upstream.status_code,
                media_type=content_type or None,
            )
        finally:
            await upstream.aclose()
            await client.aclose()
else:
    try:
        from backend.agent.web.routes import api_router as resume_router
        app.include_router(resume_router, prefix="/api/agent")
        logger.info("[合并] Resume Agent 路由已加载，前缀: /api/agent")
    except Exception as exc:
        logger.warning(f"[合并] Resume Agent 路由未加载: {exc}")


# 启动时预热 HTTP 连接并配置日志
@app.on_event("startup")
async def startup_event():
    """应用启动时预热连接"""
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[1]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    
    setup_logging(
        is_production=(LOG_MODE == "production"),
        log_level=LOG_LEVEL,
        log_dir=LOG_DIR,
    )
    bridge_std_logging_to_loguru(level=LOG_LEVEL)

    logger.info("========== 后端服务启动 ==========")
    logger.info(f"日志目录: {LOG_DIR}")
    
    try:
        simple = import_module_candidates(["backend.simple", "simple"])
        # 从环境变量同步 API Key 到 simple 模块。
        # 2026-09-16 起文本链路只剩 DeepSeek；智谱仅用于 OCR，它在
        # services/zhipu_layout.py 自己读 ZHIPU_API_KEY，不经过这里。
        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "") or os.getenv("DASHSCOPE_API_KEY", "")
        if deepseek_key:
            simple.DEEPSEEK_API_KEY = deepseek_key
            logger.info("[配置] 已从环境变量加载 DEEPSEEK_API_KEY")
        
        simple.warmup_connection()
        logger.info("[启动优化] HTTP 连接已预热")
    except Exception as e:
        logger.warning(f"[启动优化] 连接预热失败: {e}")

    # 预热数据库连接，避免首次打开仪表盘时卡在连接建立（通常会额外耗时数秒）
    try:
        from sqlalchemy import text
        from database import engine as db_engine

        warmup_ok = False
        last_error = None
        for attempt in range(1, 5):
            try:
                t0 = time.perf_counter()
                with db_engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                elapsed = (time.perf_counter() - t0) * 1000
                logger.info(f"[启动优化] 数据库连接已预热 attempt={attempt} 耗时 {elapsed:.1f}ms")
                warmup_ok = True
                break
            except Exception as exc:
                last_error = exc
                logger.warning(f"[启动优化] 数据库连接预热失败 attempt={attempt}/4: {exc}")
                if attempt < 4:
                    time.sleep(0.6 * attempt)
        if not warmup_ok:
            logger.warning(f"[启动优化] 数据库连接预热最终失败: {last_error}")
    except Exception as e:
        logger.warning(f"[启动优化] 数据库连接预热失败: {e}")

    # 启动时自动补齐本地 logo（仅当 images/logo 为空时），避免每次手工同步
    try:
        auto_sync = os.getenv("LOGO_AUTO_SYNC_ON_STARTUP", "true").lower() in {"1", "true", "yes", "on"}
        if auto_sync:
            logos = import_module_candidates(["backend.company_logos", "company_logos"])
            count = logos.sync_local_logos_from_cos(force=False)
            logger.info(f"[启动优化] Logo 本地目录检查完成，数量: {count}")
    except Exception as e:
        logger.warning(f"[启动优化] Logo 自动同步失败: {e}")

    # 预加载 tiktoken 编码文件，避免首次请求时下载阻塞（使用配置管理器）
    try:
        import tiktoken

        logger.info("[启动优化] 预加载 tiktoken 编码文件...")
        tiktoken.get_encoding("cl100k_base")
        logger.info("[启动优化] tiktoken 编码文件预加载完成")
    except Exception as e:
        logger.warning(f"[启动优化] tiktoken 预加载失败: {e}（将在首次使用时加载）")


"""
本地运行：
1) 安装依赖：uv pip install -r requirements.txt
2) 启动服务：uvicorn backend.main:app --reload --port 9000
3) 测试接口：
   - 健康：curl http://127.0.0.1:9000/api/health | cat
   - AI测试：curl -X POST http://127.0.0.1:9000/api/ai/test -H 'Content-Type: application/json' -d '{"provider":"doubao","prompt":"用一句话介绍人工智能"}' | cat
"""
