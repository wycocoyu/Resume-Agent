"""
用户照片上传路由
- POST /api/photos/upload  上传用户照片到 COS
"""
import os
import re
import hashlib
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from starlette.concurrency import run_in_threadpool

from middleware.auth import get_current_user

router = APIRouter(prefix="/api", tags=["Photos"])


def _import_cos_base_url() -> str:
    """复用 company_logos 的 COS_BASE_URL"""
    try:
        import backend.company_logos as m
    except ModuleNotFoundError:
        import company_logos as m
    return m.COS_BASE_URL


def _sanitize_account_name(account: str) -> str:
    """将账号名转换为安全的文件夹名"""
    if not account:
        return "unknown"
    lowered = account.strip().lower()
    # 保留常见用户名字符，其他字符替换为下划线，避免路径问题
    return re.sub(r"[^a-z0-9._-]+", "_", lowered).strip("._-") or "unknown"


def _build_photo_key(safe_account: str, content: bytes, ext: str) -> str:
    """内容寻址存储 key：同一张照片（字节完全相同）恒映射到同一个 COS 对象，
    天然去重——重复上传不再累积新对象，减轻 COS 负担。"""
    digest = hashlib.sha256(content).hexdigest()[:32]
    return f"users/{safe_account}/photos/{digest}{ext}"


@router.post("/photos/upload")
async def upload_photo(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    """
    上传用户照片到 COS
    - 仅登录用户可用
    - 支持 png/jpg/jpeg/webp
    - 最大 2MB
    - 存储路径: users/<account>/photos/<uuid>.<ext>
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    # 校验格式
    allowed_ext = {'.png', '.jpg', '.jpeg', '.webp'}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_ext:
        raise HTTPException(status_code=400, detail=f"不支持的格式 {ext}，仅支持 {', '.join(allowed_ext)}")

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

        # 以数据库 username 创建目录；文件名用内容哈希实现去重复用
        account = getattr(current_user, 'username', '') or getattr(current_user, 'email', '') or str(getattr(current_user, 'id', ''))
        safe_account = _sanitize_account_name(account)
        cos_key = _build_photo_key(safe_account, content, ext)

        def _upload_sync() -> bool:
            from qcloud_cos import CosConfig, CosS3Client

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key)
            client = CosS3Client(config)
            reused_flag = False
            try:
                reused_flag = bool(client.object_exists(Bucket=bucket, Key=cos_key))
            except Exception:
                reused_flag = False
            if not reused_flag:
                client.put_object(
                    Bucket=bucket,
                    Body=content,
                    Key=cos_key,
                    ContentType=file.content_type or 'image/png',
                )
            return reused_flag

        reused = await run_in_threadpool(_upload_sync)

        import urllib.parse
        cos_base = _import_cos_base_url()
        url = f"{cos_base}/{urllib.parse.quote(cos_key, safe='/')}"

        return {
            "success": True,
            "reused": reused,
            "photo": {
                "url": url,
                "key": cos_key,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.get("/photos/list")
async def list_photos(current_user=Depends(get_current_user)):
    """列出当前用户已上传的照片（COS users/<account>/photos/ 前缀），供前端复用选择。"""
    try:
        secret_id = os.getenv('COS_SECRET_ID', '')
        secret_key = os.getenv('COS_SECRET_KEY', '')
        region = os.getenv('COS_REGION', 'ap-guangzhou')
        bucket = os.getenv('COS_BUCKET', 'resumecos-1327706280')

        if not secret_id or not secret_key:
            raise HTTPException(status_code=503, detail="COS 凭证未配置")

        account = getattr(current_user, 'username', '') or getattr(current_user, 'email', '') or str(getattr(current_user, 'id', ''))
        safe_account = _sanitize_account_name(account)
        prefix = f"users/{safe_account}/photos/"

        def _list_sync():
            from qcloud_cos import CosConfig, CosS3Client

            config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key)
            client = CosS3Client(config)
            return client.list_objects(Bucket=bucket, Prefix=prefix, MaxKeys=100)

        resp = await run_in_threadpool(_list_sync)

        import urllib.parse
        cos_base = _import_cos_base_url()
        photos = []
        for obj in resp.get('Contents', []) or []:
            key = obj.get('Key')
            if not key or key.endswith('/'):
                continue
            photos.append({
                "url": f"{cos_base}/{urllib.parse.quote(key, safe='/')}",
                "key": key,
                "lastModified": obj.get('LastModified') or '',
            })

        # 新上传的排前面
        photos.sort(key=lambda p: p.get('lastModified') or '', reverse=True)
        return {"success": True, "photos": photos}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取照片列表失败: {str(e)}")
