"""
公司 Logo 管理
优先从腾讯云 COS 的 company_logo/ 目录读取公司 Logo；若 COS 不可用或未命中，再回退本地 images/logo/
新增 Logo：上传到 COS 的 company_logo/，并同步到本地 images/logo/
"""
import os
import shutil
import time
import urllib.request
from pathlib import Path

# 仓库根目录下的 images/logo（与 .gitignore 中的 images/ 对应）
_REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_LOGO_DIR = _REPO_ROOT / "images" / "logo"
LOCAL_LOGO_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".svg"}

COS_BASE_URL = 'https://resumecos-1327706280.cos.ap-guangzhou.myqcloud.com'
COMPANY_LOGO_PREFIX = "company_logo/"

# ── 非 Logo 文件排除列表（COS 中的截图、UI 素材等） ──
EXCLUDED_FILES = {
    'AI对话生成简历.png',
    'classic.png',
    'html.png',
    'resume.preview.png',
    '工作区.png',
    '我的简历.png',
    '首页.png',
}

# ── 已知 Logo 的丰富元数据（可选，用于关键词匹配和英文 key） ──
# 如果 COS 上的某个 Logo 文件不在此表中，会自动生成基础信息
KNOWN_LOGO_META = {
    '字节跳动.png': {
        'key': 'bytedance',
        'keywords': ['字节', '跳动', 'bytedance', 'tiktok', '抖音', '飞书', '头条'],
    },
    '腾讯.png': {
        'key': 'tencent',
        'keywords': ['腾讯', 'tencent', '微信', 'wechat', 'qq'],
    },
    '腾讯云.png': {
        'key': 'tencentcloud',
        'keywords': ['腾讯云', 'tencent cloud', 'tencentcloud'],
    },
    '阿里巴巴.png': {
        'key': 'alibaba',
        'keywords': ['阿里', 'alibaba', '淘宝', '天猫', '达摩院', '钉钉'],
    },
    '美团.png': {
        'key': 'meituan',
        'keywords': ['美团', 'meituan'],
    },
    '快手.png': {
        'key': 'kuaishou',
        'keywords': ['快手', 'kuaishou'],
    },
    '百度.png': {
        'key': 'baidu',
        'keywords': ['百度', 'baidu'],
    },
    '京东.png': {
        'key': 'jd',
        'keywords': ['京东', 'jd', 'jingdong'],
    },
    '华为.png': {
        'key': 'huawei',
        'keywords': ['华为', 'huawei'],
    },
    '小红书.png': {
        'key': 'xiaohongshu',
        'keywords': ['小红书', 'xiaohongshu', 'red'],
    },
    '网易.png': {
        'key': 'netease',
        'keywords': ['网易', 'netease'],
    },
    '小米.png': {
        'key': 'xiaomi',
        'keywords': ['小米', 'xiaomi', 'mi'],
    },
    '滴滴.png': {
        'key': 'didi',
        'keywords': ['滴滴', 'didi'],
    },
    '拼多多.png': {
        'key': 'pinduoduo',
        'keywords': ['拼多多', 'pinduoduo', 'pdd'],
    },
    'bilibili.png': {
        'key': 'bilibili',
        'keywords': ['bilibili', 'b站', '哔哩'],
    },
    '蚂蚁集团.png': {
        'key': 'antgroup',
        'keywords': ['蚂蚁集团', '蚂蚁金服', 'ant', '支付宝'],
    },
    '微软.png': {
        'key': 'microsoft',
        'keywords': ['微软', 'microsoft', 'msft'],
    },
    '谷歌.png': {
        'key': 'google',
        'keywords': ['谷歌', 'google'],
    },
    '苹果.png': {
        'key': 'apple',
        'keywords': ['苹果', 'apple'],
    },
    '深言科技.png': {
        'key': 'deeplang',
        'keywords': ['深言', 'deeplang', '深言科技'],
    },
}

# key -> 中文显示名（本地模式用英文文件名时，仍返回中文名给前端展示）
LOGO_KEY_TO_DISPLAY_NAME = {
    meta['key']: filename.rsplit('.', 1)[0]
    for filename, meta in KNOWN_LOGO_META.items()
}
# 中文显示名 -> 英文 key（本地用中文文件名时，API 仍返回英文 key 兼容旧简历）
DISPLAY_NAME_TO_KEY = {v: k for k, v in LOGO_KEY_TO_DISPLAY_NAME.items()}
# 哔哩哔哩 等不在 KNOWN_LOGO_META 文件名里的，补一下
DISPLAY_NAME_TO_KEY.setdefault('哔哩哔哩', 'bilibili')

# ── COS / 本地扫描结果缓存 ──
_cos_cache: list[dict] | None = None
_cos_cache_time: float = 0
_COS_CACHE_TTL = 300
_using_local = False  # True 表示当前列表来源为本地 images/logo

# key -> 文件名 / object key 查找表（在扫描后更新）
_key_to_file: dict[str, str] = {}
_cos_key_to_file: dict[str, str] = {}
_local_key_to_file: dict[str, str] = {}


def clear_cache():
    """清除扫描缓存，下次调用会重新扫描（本地或 COS）"""
    global _cos_cache, _cos_cache_time, _using_local, _key_to_file, _cos_key_to_file, _local_key_to_file
    _cos_cache = None
    _cos_cache_time = 0
    _using_local = False
    _key_to_file = {}
    _cos_key_to_file = {}
    _local_key_to_file = {}


def _list_cos_logo_keys() -> list[str]:
    """从 COS 的 company_logo/ 目录列出 Logo key（对象路径）。"""
    from backend.core.cos_client import build_cos_s3_client

    client, bucket = build_cos_s3_client()
    if client is None:
        return []

    keys: list[str] = []
    marker = ""
    while True:
        resp = client.list_objects(Bucket=bucket, Prefix=COMPANY_LOGO_PREFIX, MaxKeys=1000, Marker=marker)
        for obj in resp.get('Contents', []):
            key = obj['Key']
            lower = key.lower()
            rel = key[len(COMPANY_LOGO_PREFIX):] if key.startswith(COMPANY_LOGO_PREFIX) else key
            if not rel or rel.endswith('/'):
                continue
            if '/' in rel:
                continue
            if not lower.endswith(('.png', '.jpg', '.jpeg', '.webp', '.svg')):
                continue
            if Path(rel).name in EXCLUDED_FILES:
                continue
            keys.append(key)
        if resp.get('IsTruncated') == 'true':
            marker = resp.get('NextMarker', '')
            if not marker:
                break
        else:
            break
    return sorted(set(keys))


def sync_local_logos_from_cos(force: bool = False) -> int:
    """
    从 COS 同步 Logo 到本地 images/logo。
    - force=False：本地已有图片则跳过
    - 返回同步后本地 logo 文件数
    """
    try:
        LOCAL_LOGO_DIR.mkdir(parents=True, exist_ok=True)
        existing = [
            p for p in LOCAL_LOGO_DIR.iterdir()
            if p.is_file() and p.suffix.lower() in LOCAL_LOGO_EXTS
        ]
        if existing and not force:
            return len(existing)

        from backend.core.cos_client import build_cos_s3_client

        client, bucket = build_cos_s3_client()
        if client is None:
            return len(existing)

        keys = _list_cos_logo_keys()
        if not keys:
            return len(existing)

        if force:
            for p in LOCAL_LOGO_DIR.iterdir():
                if p.is_file() and p.suffix.lower() in LOCAL_LOGO_EXTS:
                    p.unlink(missing_ok=True)

        for key in keys:
            out = LOCAL_LOGO_DIR / Path(key).name
            body = client.get_object(Bucket=bucket, Key=key)['Body']
            # 不能用 read() 默认值（1024 bytes），必须流式落盘
            body.get_stream_to_file(str(out))

        clear_cache()
        final_count = len([p for p in LOCAL_LOGO_DIR.iterdir() if p.is_file() and p.suffix.lower() in LOCAL_LOGO_EXTS])
        print(f"[Logo] 已从 COS 同步到本地，数量: {final_count}")
        return final_count
    except Exception as e:
        print(f"[Logo] 同步本地 logo 失败: {e}")
        return 0


def _scan_local_logos() -> list[dict] | None:
    """若存在 images/logo/ 且含图片文件，则返回本地 Logo 列表，否则返回 None。异常时返回 None 以便降级 COS。"""
    global _local_key_to_file
    try:
        if not LOCAL_LOGO_DIR.is_dir():
            return None
        files = sorted(
            p for p in LOCAL_LOGO_DIR.iterdir()
            if p.is_file() and p.suffix.lower() in LOCAL_LOGO_EXTS
        )
        if not files:
            return None
        logos = []
        key_map = {}
        for f in files:
            stem = f.stem  # 中文文件名去掉后缀，如 阿里巴巴
            api_key = DISPLAY_NAME_TO_KEY.get(stem, stem)
            key_map[api_key] = f.name
            if stem != api_key:
                key_map[stem] = f.name
            meta = next((m for fn, m in KNOWN_LOGO_META.items() if m.get('key') == api_key), {})
            keywords = [str(k) for k in meta.get('keywords', [stem])]
            logos.append({
                "key": str(api_key),
                "name": str(stem),
                "url": f"/api/logos/file/{api_key}",
                "keywords": keywords,
            })
        _local_key_to_file = key_map
        print(f"[Logo] 本地 images/logo 扫描完成，发现 {len(logos)} 个 Logo")
        return logos
    except Exception as e:
        print(f"[Logo] 本地扫描异常: {e}，降级 COS/fallback")
        return None


def _scan_cos_logos() -> list[dict]:
    """扫描 COS 获取所有 Logo 文件，排除非 Logo 文件"""
    global _cos_cache, _cos_cache_time, _key_to_file, _cos_key_to_file

    # 使用缓存
    if _cos_cache is not None and (time.time() - _cos_cache_time) < _COS_CACHE_TTL:
        return _cos_cache

    try:
        if not os.getenv('COS_SECRET_ID', '') or not os.getenv('COS_SECRET_KEY', ''):
            print("[Logo] COS 凭证未配置，使用已知 Logo 列表")
            return _fallback_logos()

        logos = []
        key_map = {}
        seen_keys = set()
        for object_key in _list_cos_logo_keys():
            filename = Path(object_key).name

            name = filename.rsplit('.', 1)[0]  # 去掉 .png 后缀
            meta = KNOWN_LOGO_META.get(filename, {})
            logo_key = meta.get('key', name)  # 没有配置的用文件名做 key
            keywords = meta.get('keywords', [name])  # 没有配置的用文件名做关键词
            if logo_key in seen_keys or name in seen_keys:
                continue

            logo_entry = {
                'key': logo_key,
                'name': name,
                'url': f"{COS_BASE_URL}/{urllib.request.quote(object_key, safe='/')}",
                'keywords': keywords,
            }
            logos.append(logo_entry)
            key_map[logo_key] = object_key
            if name != logo_key:
                key_map[name] = object_key
            seen_keys.add(logo_key)
            seen_keys.add(name)

        _cos_cache = logos
        _cos_cache_time = time.time()
        _cos_key_to_file = key_map
        _key_to_file = key_map
        print(f"[Logo] COS 扫描完成，发现 {len(logos)} 个 Logo")
        return logos

    except Exception as e:
        print(f"[Logo] COS 扫描失败: {e}，使用已知 Logo 列表")
        return _fallback_logos()


def _fallback_logos() -> list[dict]:
    """COS 不可用时的降级方案：使用已知 Logo 列表"""
    global _key_to_file, _cos_key_to_file
    logos = []
    key_map = {}
    for filename, meta in KNOWN_LOGO_META.items():
        logo_key = meta['key']
        name = filename.rsplit('.', 1)[0]
        logos.append({
            'key': logo_key,
            'name': name,
            'url': f"{COS_BASE_URL}/{urllib.request.quote(filename)}",
            'keywords': meta['keywords'],
        })
        key_map[logo_key] = filename
    _key_to_file = key_map
    _cos_key_to_file = key_map
    return logos


def get_all_logos_with_urls() -> list[dict]:
    """获取所有 Logo 列表：生产优先 COS；本地开发可优先 images/logo。异常时返回 fallback 列表。"""
    global _cos_cache, _using_local
    try:
        from backend.core.cos_client import prefer_local_assets

        if prefer_local_assets():
            local = _scan_local_logos()
            if local:
                _cos_cache = local
                _using_local = True
                return local

        cos = _scan_cos_logos()
        if cos:
            _using_local = False
            return cos
        local = _scan_local_logos()
        if local:
            _cos_cache = local
            _using_local = True
            return local
        _using_local = False
        return _fallback_logos()
    except Exception as e:
        print(f"[Logo] get_all_logos_with_urls 异常: {e}，使用 fallback")
        _using_local = False
        return _fallback_logos()


def get_logo_cos_url(key: str) -> str | None:
    """根据 key 获取 COS Logo URL；若仅本地存在，则返回 None。"""
    _scan_cos_logos()
    filename = _cos_key_to_file.get(key)
    if not filename:
        return None
    return f"{COS_BASE_URL}/{urllib.request.quote(filename)}"


def _is_safe_logo_key(key: str) -> bool:
    """Reject empty keys, path separators, parent traversal, NUL bytes, and absolute paths."""
    if not isinstance(key, str) or not key.strip():
        return False
    if "/" in key or "\\" in key or ".." in key or "\x00" in key:
        return False
    if Path(key).is_absolute():
        return False
    return True


def _resolve_within_logo_dir(candidate: Path) -> Path | None:
    try:
        base_dir = LOCAL_LOGO_DIR.resolve()
        resolved = candidate.resolve()
    except OSError:
        return None
    if not resolved.is_relative_to(base_dir):
        return None
    return resolved if resolved.is_file() else None


def get_logo_local_path(key: str) -> Path | None:
    """根据 key 返回本地 Logo 文件路径，供接口和 PDF 兜底复制使用。key 可为英文或中文。"""
    if not _is_safe_logo_key(key):
        return None
    _scan_local_logos()
    filename = _local_key_to_file.get(key)
    if filename:
        found = _resolve_within_logo_dir(LOCAL_LOGO_DIR / filename)
        if found:
            return found
    for ext in LOCAL_LOGO_EXTS:
        found = _resolve_within_logo_dir(LOCAL_LOGO_DIR / f"{key}{ext}")
        if found:
            return found
    return None


def _download_url_to_path(url: str, local_path: Path, timeout: float = 15.0) -> None:
    """带超时的 HTTP 下载，避免 PDF 编译阶段 urlretrieve 无限挂起。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers={"User-Agent": "Resume-Agent/1.0"})
    with opener.open(req, timeout=timeout) as resp:
        local_path.write_bytes(resp.read())


def download_logos_to_dir(
    internships: list,
    target_dir: str,
    prefix: str = 'logo',
    *,
    offline: bool = False,
) -> dict[int, str]:
    """
    将 internships 中用到的 Logo 写入目标目录：优先从 COS 下载，失败时回退本地复制。
    offline=True 时严格只读本地 images/logo/，绝不发起任何 COS/HTTP 网络请求。

    prefix 决定文件名（`{prefix}_{idx}.png`），必须与渲染端
    latex_sections.generate_section_internships 的 logo_prefix 一致。
    工作经历板块走 WORK_EXPERIENCE_LOGO_PREFIX，避免与实习同名互相覆盖。

    返回: { index: local_filename } 映射，如 { 0: 'logo_0.png', 2: 'logo_2.png' }
    """
    if offline:
        _scan_local_logos()
    else:
        get_all_logos_with_urls()

    logos_dir = Path(target_dir) / 'logos'
    logo_map = {}

    for idx, it in enumerate(internships):
        logo_key = it.get('logo')
        if not logo_key:
            continue

        logos_dir.mkdir(parents=True, exist_ok=True)
        local_filename = f'{prefix}_{idx}.png'
        local_path = logos_dir / local_filename

        if not offline:
            cos_url = get_logo_cos_url(logo_key)
            if cos_url:
                try:
                    print(f"[Logo] 下载: {cos_url} -> {local_path}")
                    _download_url_to_path(cos_url, local_path)
                    logo_map[idx] = local_filename
                    print(f"[Logo] 下载成功: {local_filename} ({local_path.stat().st_size} bytes)")
                    continue
                except Exception as e:
                    print(f"[Logo] 下载失败 ({logo_key})，回退本地: {e}")

        src = get_logo_local_path(logo_key)
        if src:
            try:
                shutil.copy2(src, local_path)
                logo_map[idx] = local_filename
                print(f"[Logo] 本地兜底复制: {src.name} -> {local_filename}")
            except Exception as e:
                print(f"[Logo] 本地复制失败 ({logo_key}): {e}")
        else:
            print(f"[Logo] {'本地' if offline else 'COS 与本地'}均未找到 Logo key: {logo_key}")

    return logo_map
