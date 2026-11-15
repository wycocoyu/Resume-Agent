"""
学校 Logo 路由
- GET  /api/school-logos
- GET  /api/school-logos/file/{key}
- POST /api/school-logos/upload
"""
from __future__ import annotations

import os
import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends, Form
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from middleware.auth import AppUser, require_admin_only
# User(users) 已退役(2026-07-17 身份统一),身份用 middleware.auth.AppUser

router = APIRouter(prefix="/api", tags=["SchoolLogos"])


def _import_school_logos():
    try:
        import backend.school_logos as m
    except ModuleNotFoundError:
        import school_logos as m
    return m


@router.get("/school-logos/file/{key}")
async def get_school_logo_file(key: str):
    if ".." in key or "/" in key or "\\" in key:
        raise HTTPException(status_code=400, detail="无效的 key")
    m = _import_school_logos()
    path = await run_in_threadpool(m.get_school_logo_local_path, key)
    if path is None:
        raise HTTPException(status_code=404, detail="School logo 不存在")
    media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


@router.get("/school-logos")
async def get_school_logos():
    try:
        m = _import_school_logos()
        logos = await run_in_threadpool(m.get_all_school_logos_with_urls)
        groups = await run_in_threadpool(m.get_grouped_school_logos_with_urls)
        return JSONResponse(status_code=200, content={"logos": logos, "groups": groups})
    except Exception as e:
        return JSONResponse(
            status_code=200,
            content={
                "logos": [],
                "groups": [],
                "error_code": "SCHOOL_LOGO_LIST_FAILED",
                "error": str(e),
                "error_message": str(e),
            },
        )


@router.post("/school-logos/upload")
async def upload_school_logo(
    file: UploadFile = File(...),
    group: str = Form(...),
    current_user: AppUser = Depends(require_admin_only),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    safe_filename = Path(file.filename).name
    if not safe_filename:
        raise HTTPException(status_code=400, detail="文件名无效")

    allowed_groups = {"985", "211", "香港", "双非"}
    if group not in allowed_groups:
        raise HTTPException(status_code=400, detail="分组无效")

    allowed_ext = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
    ext = os.path.splitext(safe_filename)[1].lower()
    if ext not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"不支持的格式 {ext}，仅支持 {', '.join(sorted(allowed_ext))}")

    content = await file.read()
    max_size = 2 * 1024 * 1024
    if len(content) > max_size:
        raise HTTPException(status_code=400, detail="文件过大，最大 2MB")

    try:
        secret_id = os.getenv("COS_SECRET_ID", "")
        secret_key = os.getenv("COS_SECRET_KEY", "")
        region = os.getenv("COS_REGION", "ap-guangzhou")
        bucket = os.getenv("COS_BUCKET", "resumecos-1327706280")

        if not secret_id or not secret_key:
            raise HTTPException(status_code=500, detail="COS 凭证未配置")

        cos_key = f"school_logo/{group}/{safe_filename}"
        m = _import_school_logos()

        def _upload_sync():
            from qcloud_cos import CosConfig, CosS3Client

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key)
            client = CosS3Client(config)
            client.put_object(
                Bucket=bucket,
                Body=content,
                Key=cos_key,
                ContentType=file.content_type or "image/png",
            )
            local_dir = Path(m.LOCAL_SCHOOL_LOGO_DIR) / group
            local_dir.mkdir(parents=True, exist_ok=True)
            (local_dir / safe_filename).write_bytes(content)
            m.clear_cache()

        await run_in_threadpool(_upload_sync)

        import urllib.request

        name = os.path.splitext(safe_filename)[0]
        url = f"{m.COS_BASE_URL}/{urllib.request.quote(cos_key, safe='/')}"

        return {
            "success": True,
            "logo": {
                "key": name,
                "name": name,
                "group": group,
                "url": url,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.delete("/school-logos")
async def delete_school_logo(
    filename: str,
    group: str,
    current_user: AppUser = Depends(require_admin_only),
):
    """删除学校 Logo：从 COS 删除对象 + 本地缓存，并清列表缓存。仅管理员。"""
    safe = Path(filename).name
    if not safe:
        raise HTTPException(status_code=400, detail="文件名无效")
    allowed_groups = {"985", "211", "香港", "双非"}
    if group not in allowed_groups:
        raise HTTPException(status_code=400, detail="分组无效")

    m = _import_school_logos()
    cos_key = f"school_logo/{group}/{safe}"
    try:
        secret_id = os.getenv("COS_SECRET_ID", "")
        secret_key = os.getenv("COS_SECRET_KEY", "")
        region = os.getenv("COS_REGION", "ap-guangzhou")
        bucket = os.getenv("COS_BUCKET", "resumecos-1327706280")
        if not secret_id or not secret_key:
            raise HTTPException(status_code=500, detail="COS 凭证未配置")

        def _delete_sync():
            from qcloud_cos import CosConfig, CosS3Client

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key)
            client = CosS3Client(config)
            client.delete_object(Bucket=bucket, Key=cos_key)
            local_path = Path(m.LOCAL_SCHOOL_LOGO_DIR) / group / safe
            if local_path.exists():
                local_path.unlink()
            m.clear_cache()

        await run_in_threadpool(_delete_sync)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
