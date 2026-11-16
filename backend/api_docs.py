"""Offline OpenAPI API dashboard module (Scalar primary + Swagger UI fallback).

Serves 100% self-hosted JS/CSS bundles under `/api/docs-assets/*` with zero external CDN
or remote font dependencies, exposes Scalar at `/api/docs` (and `/docs`) and Swagger UI
at `/api/swagger`, and enforces environment-aware admin protection in production.
"""
from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from backend.middleware.auth import AppUser, get_current_user_optional

DocsMode = Literal["public", "admin", "disabled"]

API_DOCS_STATIC_DIR = Path(__file__).resolve().parent / "static" / "api_docs"

_ALLOWED_ASSETS: dict[str, str] = {
    "scalar-api-reference.js": "application/javascript; charset=utf-8",
    "swagger-ui-bundle.js": "application/javascript; charset=utf-8",
    "swagger-ui.css": "text/css; charset=utf-8",
}

_TRUE_VALUES = {"1", "true", "yes", "on", "public"}
_FALSE_VALUES = {"0", "false", "no", "off", "disabled"}
_PROD_VALUES = {"prod", "production"}

OPENAPI_TAGS_METADATA: list[dict[str, str]] = [
    {"name": "Health", "description": "服务健康检查、就绪探针与基础运行状态。"},
    {"name": "Auth", "description": "登录认证与账号权限校验接口。"},
    {"name": "BetterAuth", "description": "BetterAuth 会话桥接、用户信息同步与退出登录。"},
    {"name": "Resume", "description": "简历生成、诊断、图片/文件导入解析及评分接口。"},
    {"name": "Resumes", "description": "云端简历列表、保存、删除与增量同步接口。"},
    {"name": "Resume Share", "description": "公开只读简历分享链接创建与读取。"},
    {"name": "PDF", "description": "XeLaTeX PDF 编译、流式进度推送与下载限额。"},
    {"name": "Job JD Matching & Analysis", "description": "目标岗位 JD 解析、三维匹配度评分与简历衍生分支。"},
    {"name": "Agent", "description": "Pi-Core 对话流式 SSE、历史会话、工具审批与工作区状态。"},
    {"name": "Config", "description": "AI / OCR 密钥配置、连通性检测与系统运行统计。"},
    {"name": "Logos", "description": "企业 Logo 检索、本地缓存与 COS 上传。"},
    {"name": "SchoolLogos", "description": "高校校徽检索、匹配与管理接口。"},
    {"name": "Photos", "description": "证件照上传、裁剪与安全访问。"},
    {"name": "ASR", "description": "语音识别转写接口。"},
    {"name": "TTS", "description": "语音合成播报接口。"},
    {"name": "Semantic Search", "description": "岗位与简历语义检索接口。"},
    {"name": "LeetCode", "description": "算法刷题进度与题目查询辅助接口。"},
    {"name": "Billing", "description": "配额计费与订单状态接口。"},
    {"name": "Admin", "description": "后台管理员统计、用户管理与日志审计接口。"},
]

API_DESCRIPTION_MARKDOWN = (
    "CocoCV（原 Resume-Agent）统一后端接口参考与在线调试看板。\n\n"
    "- 支持 `Cmd+K` 全局检索、多语言请求代码生成与在线联调（本地零外网 CDN 依赖）。\n"
    "- 需要传统表单调试界面时，可切换至 [Swagger UI 备用面板](/api/swagger) 或下载 [OpenAPI 3.1 JSON](/api/openapi.json)。\n"
    "- 官方 MCP SSE 服务默认挂载于 `/mcp`。"
)


def is_production_env() -> bool:
    """Detect whether the backend is running in a production environment."""
    return any(
        os.getenv(key, "").strip().lower() in _PROD_VALUES
        for key in ("LOG_MODE", "NODE_ENV", "APP_ENV", "ENVIRONMENT")
    )


def resolve_api_docs_mode() -> DocsMode:
    """Resolve effective API docs visibility mode from env flags.

    Defaults to `public` in local/dev environments and `admin` in production unless
    explicitly overridden via `ENABLE_API_DOCS`.
    """
    raw = os.getenv("ENABLE_API_DOCS", "").strip().lower()
    if raw in _TRUE_VALUES:
        return "public"
    if raw in _FALSE_VALUES:
        return "disabled"
    if raw == "admin" or is_production_env():
        return "admin"
    return "public"


async def require_api_docs_access(
    current_user: Optional[AppUser] = Depends(get_current_user_optional),
) -> Optional[AppUser]:
    """Enforce dev-open / prod-admin-gated access on API dashboard endpoints."""
    mode = resolve_api_docs_mode()
    if mode == "disabled":
        raise HTTPException(status_code=404, detail="API 文档未启用")
    if mode == "public":
        return None
    if current_user is None:
        raise HTTPException(status_code=401, detail="接口看板受管理员鉴权保护，请先登录管理员账号")
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问接口看板")
    return current_user


def build_scalar_html(openapi_url: str = "/api/openapi.json", title: str = "CocoCV API") -> str:
    """Build self-hosted Scalar API Reference HTML without any external CDN."""
    config = {
        "url": openapi_url,
        "theme": "kepler",
        "layout": "modern",
        "withDefaultFonts": False,
        "defaultHttpClient": {"targetKey": "shell", "clientKey": "curl"},
        "searchHotKey": "k",
        "persistAuth": True,
        "hideDownloadButton": False,
    }
    escaped_title = html.escape(f"{title} - 接口看板", quote=True)
    escaped_openapi_url = html.escape(openapi_url, quote=True)
    escaped_config = html.escape(json.dumps(config, ensure_ascii=False), quote=True)
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        f"  <title>{escaped_title}</title>\n"
        '  <meta charset="utf-8" />\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        "</head>\n"
        "<body>\n"
        "  <script\n"
        '    id="api-reference"\n'
        f'    data-url="{escaped_openapi_url}"\n'
        f'    data-configuration="{escaped_config}"\n'
        "  ></script>\n"
        '  <script src="/api/docs-assets/scalar-api-reference.js"></script>\n'
        "</body>\n"
        "</html>\n"
    )


def build_swagger_html(openapi_url: str = "/api/openapi.json", title: str = "CocoCV API") -> str:
    """Build self-hosted Swagger UI HTML without any external CDN."""
    escaped_title = html.escape(f"{title} - Swagger UI", quote=True)
    escaped_openapi_url = json.dumps(openapi_url)
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '  <meta charset="utf-8" />\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        f"  <title>{escaped_title}</title>\n"
        '  <link rel="stylesheet" type="text/css" href="/api/docs-assets/swagger-ui.css" />\n'
        "  <style>\n"
        "    html { box-sizing: border-box; overflow-y: scroll; }\n"
        "    *, *:before, *:after { box-sizing: inherit; }\n"
        "    body { margin: 0; background: #fafafa; }\n"
        "    .cococv-top-bar { display:flex; align-items:center; justify-content:space-between; padding:10px 20px; background:#0f172a; color:#f8fafc; font-family:system-ui,sans-serif; font-size:13px; }\n"
        "    .cococv-top-bar a { color:#93c5fd; text-decoration:none; font-weight:600; }\n"
        "    .cococv-top-bar a:hover { text-decoration:underline; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        '  <div class="cococv-top-bar">\n'
        "    <span>CocoCV Swagger UI（离线备用面板）</span>\n"
        '    <a href="/api/docs">切换到 Scalar 现代看板 →</a>\n'
        "  </div>\n"
        '  <div id="swagger-ui"></div>\n'
        '  <script src="/api/docs-assets/swagger-ui-bundle.js"></script>\n'
        "  <script>\n"
        "    window.onload = function () {\n"
        "      window.ui = SwaggerUIBundle({\n"
        f"        url: {escaped_openapi_url},\n"
        '        dom_id: "#swagger-ui",\n'
        '        layout: "BaseLayout",\n'
        "        deepLinking: true,\n"
        "        filter: true,\n"
        "        persistAuthorization: true,\n"
        "        displayRequestDuration: true,\n"
        "        presets: [SwaggerUIBundle.presets.apis]\n"
        "      });\n"
        "    };\n"
        "  </script>\n"
        "</body>\n"
        "</html>\n"
    )


def register_api_docs(app: FastAPI) -> None:
    """Mount offline API docs assets, schema JSON, Scalar UI, and Swagger fallback."""

    @app.get("/api/docs-assets/{asset_name}", include_in_schema=False)
    async def serve_api_docs_asset(asset_name: str):
        media_type = _ALLOWED_ASSETS.get(asset_name)
        if not media_type:
            raise HTTPException(status_code=404, detail="静态资源不存在")
        file_path = API_DOCS_STATIC_DIR / asset_name
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail=f"静态资源未就绪: {asset_name}")
        return FileResponse(
            file_path,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get(
        "/api/openapi.json",
        include_in_schema=False,
        dependencies=[Depends(require_api_docs_access)],
    )
    @app.get(
        "/openapi.json",
        include_in_schema=False,
        dependencies=[Depends(require_api_docs_access)],
    )
    async def get_openapi_schema():
        return JSONResponse(app.openapi())

    @app.get(
        "/api/docs",
        include_in_schema=False,
        dependencies=[Depends(require_api_docs_access)],
    )
    @app.get(
        "/docs",
        include_in_schema=False,
        dependencies=[Depends(require_api_docs_access)],
    )
    async def get_scalar_docs():
        return HTMLResponse(build_scalar_html("/api/openapi.json", app.title))

    @app.get(
        "/api/swagger",
        include_in_schema=False,
        dependencies=[Depends(require_api_docs_access)],
    )
    @app.get(
        "/swagger",
        include_in_schema=False,
        dependencies=[Depends(require_api_docs_access)],
    )
    async def get_swagger_docs():
        return HTMLResponse(build_swagger_html("/api/openapi.json", app.title))
