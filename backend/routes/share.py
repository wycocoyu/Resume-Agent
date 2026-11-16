"""
分享简历的 API 路由
提供生成分享链接和查看分享简历的功能
"""
import uuid
import json
import os
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from loguru import logger

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

# 使用内存存储（生产环境请替换为数据库/Redis）
share_store: Dict[str, Dict[str, Any]] = {}

# 获取前端域名（从环境变量读取，默认为生产环境域名）
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://cococv.cn")
logger.info(f"[Share] FRONTEND_URL 配置: {FRONTEND_URL}")


class ShareResumeRequest(BaseModel):
    """分享简历请求"""
    resume_data: Dict[str, Any]
    resume_name: str
    expire_days: int = Field(default=30, ge=1, le=365)  # 默认 30 天后过期


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
    # 生成唯一 ID
    share_id = str(uuid.uuid4())[:8]

    # 计算过期时间
    expires_at = datetime.now() + timedelta(days=request.expire_days)

    # 存储分享数据
    share_store[share_id] = {
        "resume_data": request.resume_data,
        "resume_name": request.resume_name,
        "created_at": datetime.now().isoformat(),
        "expires_at": expires_at.isoformat(),
        "views": 0,
    }

    # 分享链接配置（根据环境变量动态设置）
    # 开发环境：http://localhost:5173/share/{share_id}
    # 生产环境：从环境变量 FRONTEND_URL 读取
    share_url = f"{FRONTEND_URL}/share/{share_id}"

    logger.info(f"[Share] 创建分享链接: share_id={share_id}, name={request.resume_name}")
    logger.info(f"[Share] 生成的链接: {share_url}")
    logger.info(f"[Share] 当前存储的所有 share_id: {list(share_store.keys())}")

    return ShareResumeResponse(
        share_url=share_url,
        share_id=share_id,
        expires_at=expires_at.isoformat(),
    )


@router.get("/share/{share_id}")
async def get_shared_resume(share_id: str):
    """获取分享的简历"""
    logger.info(f"[Share] 访问分享链接: share_id={share_id}")
    logger.info(f"[Share] 当前存储的所有 share_id: {list(share_store.keys())}")
    
    if share_id not in share_store:
        logger.warning(f"[Share] 分享链接不存在: share_id={share_id}")
        raise HTTPException(status_code=404, detail="分享链接不存在或已过期")

    share_data = share_store[share_id]

    # 检查是否过期
    expires_at = datetime.fromisoformat(share_data["expires_at"])
    if datetime.now() > expires_at:
        logger.warning(f"[Share] 分享链接已过期: share_id={share_id}")
        del share_store[share_id]
        raise HTTPException(status_code=404, detail="分享链接已过期")

    # 增加浏览次数
    share_data["views"] += 1
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
