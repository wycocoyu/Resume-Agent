"""
分享简历的 API 路由
提供生成分享链接和查看分享简历的功能
"""
from collections.abc import MutableMapping
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
from typing import Any, Dict, Iterator, Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

try:
    from backend.api_docs import is_production_env
except ImportError:
    from api_docs import is_production_env

try:
    from middleware.auth import AppUser, get_current_user_optional
except ImportError:
    from backend.middleware.auth import AppUser, get_current_user_optional

# 与其他接口保持一致，使用 /api 前缀
router = APIRouter(prefix="/api/resume", tags=["Resume Share"])

MAX_SHARE_PAYLOAD_BYTES = 512 * 1024
_SHARE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_share_store_dir() -> Path:
    env_dir = (os.getenv("SHARE_STORE_DIR") or "").strip()
    if env_dir:
        return Path(env_dir)
    docker_data = Path("/app/data")
    if docker_data.is_dir():
        return docker_data / "shares"
    return _REPO_ROOT / "backend" / "data" / "shares"


class DiskShareStore(MutableMapping[str, Dict[str, Any]]):
    """Cross-worker file-backed share store with atomic writes and strict key validation."""

    def _base_dir(self) -> Path:
        return _resolve_share_store_dir()

    def _validate_key(self, key: str) -> str:
        if not isinstance(key, str) or not _SHARE_ID_RE.fullmatch(key):
            raise KeyError(key)
        return key

    def _entry_path(self, key: str) -> Path:
        valid_key = self._validate_key(key)
        return self._base_dir() / f"{valid_key}.json"

    def __getitem__(self, key: str) -> Dict[str, Any]:
        path = self._entry_path(key)
        if not path.is_file():
            raise KeyError(key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise KeyError(key) from exc
        if not isinstance(payload, dict):
            raise KeyError(key)
        return payload

    def __setitem__(self, key: str, value: Dict[str, Any]) -> None:
        path = self._entry_path(key)
        base = path.parent
        base.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(value, ensure_ascii=False)
        fd, tmp_name = tempfile.mkstemp(prefix=".share_", suffix=".tmp", dir=str(base))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(encoded)
                fh.flush()
            os.replace(tmp_path, path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    def __delitem__(self, key: str) -> None:
        path = self._entry_path(key)
        if not path.is_file():
            raise KeyError(key)
        path.unlink(missing_ok=True)

    def __iter__(self) -> Iterator[str]:
        base = self._base_dir()
        if not base.is_dir():
            return iter(())
        keys = [
            p.stem
            for p in sorted(base.glob("*.json"))
            if _SHARE_ID_RE.fullmatch(p.stem)
        ]
        return iter(keys)

    def __len__(self) -> int:
        base = self._base_dir()
        if not base.is_dir():
            return 0
        return sum(1 for p in base.glob("*.json") if _SHARE_ID_RE.fullmatch(p.stem))

    def clear(self) -> None:
        base = self._base_dir()
        if not base.is_dir():
            return
        for path in base.glob("*.json"):
            if _SHARE_ID_RE.fullmatch(path.stem):
                path.unlink(missing_ok=True)


def _prune_expired_shares(store: MutableMapping[str, Dict[str, Any]]) -> None:
    now = datetime.now()
    for sid in list(store.keys()):
        try:
            record = store[sid]
            exp = record.get("expires_at")
            if isinstance(exp, str) and now > datetime.fromisoformat(exp):
                del store[sid]
        except (KeyError, ValueError, TypeError):
            continue


# 跨 worker 共享的磁盘持久化存储（避免 --workers 2 进程间 404）
share_store: MutableMapping[str, Dict[str, Any]] = DiskShareStore()

# 获取前端域名（从环境变量读取，默认为生产环境域名）
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://cococv.cn")
logger.info(f"[Share] FRONTEND_URL 配置: {FRONTEND_URL}")


class ShareResumeRequest(BaseModel):
    """分享简历请求"""
    resume_data: Dict[str, Any]
    resume_name: str
    expire_days: int = Field(default=30, ge=1, le=365)  # 默认 30 天后过期
    expire_minutes: Optional[int] = Field(default=None, ge=1, le=10080)


class ShareResumeResponse(BaseModel):
    """分享简历响应"""
    share_url: str
    share_id: str
    expires_at: str


@router.post("/share", response_model=ShareResumeResponse)
async def create_share_link(request: ShareResumeRequest):
    """
    生成分享链接
    """
    payload_bytes = len(json.dumps(request.resume_data, ensure_ascii=False).encode("utf-8"))
    if payload_bytes > MAX_SHARE_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="简历体积超出临时同步上限（512KB）")

    _prune_expired_shares(share_store)

    # 生成高熵 URL 安全 ID
    share_id = secrets.token_urlsafe(9)

    # 计算过期时间（CLI handoff 可传分钟级 TTL）
    delta = (
        timedelta(minutes=request.expire_minutes)
        if request.expire_minutes is not None
        else timedelta(days=request.expire_days)
    )
    expires_at = datetime.now() + delta

    # 存储分享数据
    share_store[share_id] = {
        "resume_data": request.resume_data,
        "resume_name": request.resume_name,
        "created_at": datetime.now().isoformat(),
        "expires_at": expires_at.isoformat(),
        "views": 0,
    }

    frontend_base = (os.getenv("FRONTEND_URL") or FRONTEND_URL).rstrip("/")
    share_url = f"{frontend_base}/share/{share_id}"

    logger.info(f"[Share] 创建分享链接: share_id={share_id}, name={request.resume_name}")
    logger.info(f"[Share] 生成的链接: {share_url}")

    return ShareResumeResponse(
        share_url=share_url,
        share_id=share_id,
        expires_at=expires_at.isoformat(),
    )


@router.get("/share/{share_id}")
async def get_shared_resume(share_id: str):
    """获取分享的简历"""
    logger.info(f"[Share] 访问分享链接: share_id={share_id}")

    try:
        share_data = share_store[share_id]
    except KeyError:
        logger.warning(f"[Share] 分享链接不存在: share_id={share_id}")
        raise HTTPException(status_code=404, detail="分享链接不存在或已过期")

    # 检查是否过期
    expires_at = datetime.fromisoformat(share_data["expires_at"])
    if datetime.now() > expires_at:
        logger.warning(f"[Share] 分享链接已过期: share_id={share_id}")
        del share_store[share_id]
        raise HTTPException(status_code=404, detail="分享链接已过期")

    # 增加浏览次数并持久化
    share_data["views"] = int(share_data.get("views", 0)) + 1
    share_store[share_id] = share_data
    logger.info(f"[Share] 获取成功: share_id={share_id}, views={share_data['views']}")

    return {
        "success": True,
        "data": share_data["resume_data"],
        "name": share_data["resume_name"],
        "expires_at": share_data["expires_at"],
        "views": share_data["views"],
    }


@router.delete("/share/{share_id}")
async def delete_share_link(
    share_id: str,
    current_user: Optional[AppUser] = Depends(get_current_user_optional),
):
    """删除分享链接"""
    if is_production_env() and current_user is None:
        raise HTTPException(status_code=401, detail="未提供有效的认证信息")
    if share_id not in share_store:
        raise HTTPException(status_code=404, detail="分享链接不存在")

    del share_store[share_id]
    return {"success": True, "message": "分享链接已删除"}


@router.get("/shares")
async def list_share_links(
    current_user: Optional[AppUser] = Depends(get_current_user_optional),
):
    """列出所有分享链接"""
    if is_production_env() and current_user is None:
        raise HTTPException(status_code=401, detail="未提供有效的认证信息")
    shares = []
    for share_id, data in share_store.items():
        expires_at = datetime.fromisoformat(data["expires_at"])
        is_expired = datetime.now() > expires_at

        shares.append({
            "share_id": share_id,
            "resume_name": data["resume_name"],
            "created_at": data["created_at"],
            "expires_at": data["expires_at"],
            "views": data["views"],
            "is_expired": is_expired,
        })

    return {"shares": shares}
