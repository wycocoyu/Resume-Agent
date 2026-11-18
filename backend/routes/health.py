"""
健康检查与就绪探针路由
"""
from functools import lru_cache
import os
from pathlib import Path
import subprocess

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

try:
    from database import SessionLocal
except ImportError:
    from backend.database import SessionLocal

router = APIRouter(prefix="/api", tags=["Health"])

_REPO_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _resolve_git_sha() -> str:
    env_sha = (os.getenv("COCOCV_GIT_SHA") or os.getenv("GIT_SHA") or "").strip()
    if env_sha:
        return env_sha[:12]
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short=8", "HEAD"],
            cwd=str(_REPO_ROOT),
            stderr=subprocess.DEVNULL,
            timeout=2,
            text=True,
        ).strip()
        if out:
            return out
    except Exception:
        pass
    return "unknown"


def _resolve_slot() -> str:
    slot = (os.getenv("COCOCV_SLOT") or "").strip()
    return slot or "single"


@router.get("/health")
async def health():
    """存活探针（兼容现有 {"status": "ok"} 契约，附带槽位与 Commit 元数据）"""
    return {
        "status": "ok",
        "slot": _resolve_slot(),
        "commit": _resolve_git_sha(),
    }


@router.get("/health/ready")
async def health_ready():
    """就绪探针：验证数据库连通性并回传槽位与代码版本"""
    payload = {
        "status": "ready",
        "slot": _resolve_slot(),
        "commit": _resolve_git_sha(),
        "database": "ok",
    }
    db = None
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        return payload
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={
                **payload,
                "status": "not_ready",
                "database": "error",
                "detail": str(exc),
            },
        )
    finally:
        if db is not None:
            db.close()
