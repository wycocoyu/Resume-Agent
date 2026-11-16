"""
公司 Logo 路由
- GET  /api/logos           获取所有可用的 Logo 列表
- GET  /api/logos/file/{key}  获取本地 Logo 图片（当使用 images/logo 时）
- POST /api/logos/upload    上传自定义 Logo 到 COS
"""
import asyncio
import os
import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from middleware.auth import AppUser, require_admin_only
# User(users) 已退役(2026-07-17 身份统一),身份用 middleware.auth.AppUser

router = APIRouter(prefix="/api", tags=["Logos"])
logger = logging.getLogger(__name__)


def _import_logos():
    """兼容两种导入方式"""
    try:
        import backend.company_logos as m
    except ModuleNotFoundError:
        import company_logos as m
    return m


@router.get("/logos/file/{key}")
async def get_logo_file(key: str):
    """提供本地 images/logo 目录下的 Logo 图片（支持中文文件名，key 可为英文或中文）"""
    m = _import_logos()
    if ".." in key or "/" in key or "\\" in key:
        raise HTTPException(status_code=400, detail="无效的 key")
    path = await run_in_threadpool(m.get_logo_local_path, key)
    if path is None:
        raise HTTPException(status_code=404, detail="Logo 不存在")
    media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


@router.get("/logos")
async def get_logos():
    """获取所有可用的公司 Logo 列表（含 COS URL）。异常时始终返回 200 + 空列表，避免 500。"""
    try:
        m = _import_logos()
        logos = await asyncio.to_thread(m.get_all_logos_with_urls)
        return JSONResponse(status_code=200, content={"logos": logos})
    except Exception as e:
        module_file = ""
        logo_dir = ""
        try:
            m = _import_logos()
            module_file = str(getattr(m, "__file__", ""))
            logo_dir = str(getattr(m, "LOCAL_LOGO_DIR", ""))
        except Exception:
            pass
        logger.exception(
            "[Logo] get_logos failed: err=%s module_file=%s logo_dir=%s",
            e,
            module_file,
            logo_dir,
        )
        return JSONResponse(
            status_code=200,
            content={
                "logos": [],
                "error_code": "LOGO_LIST_FAILED",
                "error": str(e),
                "error_message": str(e),
            },
        )


@router.post("/logos/upload")
async def upload_logo(
    file: UploadFile = File(...),
    current_user: AppUser = Depends(require_admin_only),
):
    """
    上传自定义 Logo 到 COS
    - 支持 png/jpg/jpeg/webp/svg 格式
    - 文件名作为 Logo 名称（去掉后缀）
    - 上传成功后清除缓存，下次 GET /api/logos 会包含新 Logo
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    safe_filename = Path(file.filename).name
    if not safe_filename:
        raise HTTPException(status_code=400, detail="文件名无效")

    # 校验格式
    allowed_ext = {'.png', '.jpg', '.jpeg', '.webp', '.svg'}
    ext = os.path.splitext(safe_filename)[1].lower()
    if ext not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"不支持的格式 {ext}，仅支持 {', '.join(allowed_ext)}")

    # 校验大小（读取内容）
    content = await file.read()
    max_size = 2 * 1024 * 1024  # 2MB
    if len(content) > max_size:
        raise HTTPException(status_code=400, detail="文件过大，最大 2MB")

    try:
        secret_id = os.getenv('COS_SECRET_ID', '')
        secret_key = os.getenv('COS_SECRET_KEY', '')
        region = os.getenv('COS_REGION', 'ap-guangzhou')
        bucket = os.getenv('COS_BUCKET', 'resumecos-1327706280')

        if not secret_id or not secret_key:
            raise HTTPException(status_code=503, detail="COS 凭证未配置")

        m = _import_logos()
        cos_key = f"{m.COMPANY_LOGO_PREFIX}{safe_filename}"

        def _upload_sync():
            from qcloud_cos import CosConfig, CosS3Client

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key)
            client = CosS3Client(config)
            client.put_object(
                Bucket=bucket,
                Body=content,
                Key=cos_key,
                ContentType=file.content_type or 'image/png',
            )
            local_dir = Path(m.LOCAL_LOGO_DIR)
            target_path = local_dir / cos_key
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(content)
            m.clear_cache()

        await run_in_threadpool(_upload_sync)

        import urllib.request
        cos_base = m.COS_BASE_URL
        url = f"{cos_base}/{urllib.request.quote(cos_key, safe='/')}"

        return {
            "success": True,
            "logo": {
                "key": os.path.splitext(safe_filename)[0],
                "name": os.path.splitext(safe_filename)[0],
                "url": url,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.delete("/logos")
async def delete_logo(
    filename: str,
    current_user: AppUser = Depends(require_admin_only),
):
    """删除公司 Logo：从 COS 删除对象 + 本地缓存，并清列表缓存。仅管理员。"""
    safe = Path(filename).name
    if not safe:
        raise HTTPException(status_code=400, detail="文件名无效")

    m = _import_logos()
    cos_key = f"{m.COMPANY_LOGO_PREFIX}{safe}"
    try:
        secret_id = os.getenv('COS_SECRET_ID', '')
        secret_key = os.getenv('COS_SECRET_KEY', '')
        region = os.getenv('COS_REGION', 'ap-guangzhou')
        bucket = os.getenv('COS_BUCKET', 'resumecos-1327706280')
        if not secret_id or not secret_key:
            raise HTTPException(status_code=503, detail="COS 凭证未配置")

        def _delete_sync():
            from qcloud_cos import CosConfig, CosS3Client

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key)
            client = CosS3Client(config)
            client.delete_object(Bucket=bucket, Key=cos_key)
            local_dir = Path(m.LOCAL_LOGO_DIR)
            for candidate in (local_dir / cos_key, local_dir / safe):
                if candidate.exists():
                    candidate.unlink()
            m.clear_cache()

        await run_in_threadpool(_delete_sync)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
