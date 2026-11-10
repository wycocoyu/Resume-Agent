"""
学校 Logo 管理
优先从 COS 读取学校 Logo；若 COS 不可用或未命中，则回退本地 images/school_logo/
支持目录分组：985 / 211 / 香港 / 双非
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import time
import urllib.request

_REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_SCHOOL_LOGO_DIR = _REPO_ROOT / "images" / "school_logo"
LOCAL_SCHOOL_LOGO_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
LATEX_SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".pdf"}
COS_BASE_URL = "https://resumecos-1327706280.cos.ap-guangzhou.myqcloud.com"
COS_PREFIXES = ("school_logo/",)
DEFAULT_GROUP_NAME = "未分组"
GROUP_ORDER = ["985", "211", "香港", "双非", DEFAULT_GROUP_NAME]

_cos_cache: list[dict] | None = None
_cos_group_cache: list[dict] | None = None
_cos_cache_time: float = 0
_CACHE_TTL = 300
_cos_key_to_file: dict[str, str] = {}
_local_key_to_file: dict[str, str] = {}
_using_local = False


def _normalize_keyword(name: str) -> str:
    s = (name or "").strip()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[（）()【】\[\]·\-—_/]", "", s)
    return s.lower()


def _build_keywords(name: str) -> list[str]:
    base = name.strip()
    aliases = {
        base,
        base.replace("大学", ""),
        base.replace("学院", ""),
        base.replace("大学", "").replace("学院", ""),
        base.replace("（", "(").replace("）", ")"),
    }
    cleaned = {_normalize_keyword(a) for a in aliases if a and _normalize_keyword(a)}
    out = [base]
    out.extend(sorted(cleaned))
    return out


def _group_sort_key(name: str) -> tuple[int, str]:
    try:
        idx = GROUP_ORDER.index(name)
    except ValueError:
        idx = len(GROUP_ORDER)
    return (idx, name)


def _build_group_payload(grouped: dict[str, list[dict]]) -> list[dict]:
    result: list[dict] = []
    for group_name in sorted(grouped.keys(), key=_group_sort_key):
        result.append(
            {
                "key": group_name,
                "name": group_name,
                "logos": sorted(grouped[group_name], key=lambda item: item["name"]),
            }
        )
    return result


def clear_cache():
    global _cos_cache, _cos_group_cache, _cos_cache_time, _cos_key_to_file, _local_key_to_file, _using_local
    _cos_cache = None
    _cos_group_cache = None
    _cos_cache_time = 0
    _cos_key_to_file = {}
    _local_key_to_file = {}
    _using_local = False


def _scan_local_school_logos() -> tuple[list[dict], list[dict]] | tuple[None, None]:
    if not LOCAL_SCHOOL_LOGO_DIR.is_dir():
        return None, None

    files = sorted(
        p for p in LOCAL_SCHOOL_LOGO_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in LOCAL_SCHOOL_LOGO_EXTS
    )
    if not files:
        return None, None

    logos: list[dict] = []
    grouped: dict[str, list[dict]] = {}
    key_map: dict[str, str] = {}

    for f in files:
        name = f.stem.strip()
        if not name:
            continue
        try:
            rel_parent = f.relative_to(LOCAL_SCHOOL_LOGO_DIR).parent
        except ValueError:
            rel_parent = Path(".")
        group_name = rel_parent.parts[0] if rel_parent.parts else DEFAULT_GROUP_NAME
        logo = {
            "key": name,
            "name": name,
            "group": group_name,
            "url": f"/api/school-logos/file/{name}",
            "keywords": _build_keywords(name),
        }
        logos.append(logo)
        grouped.setdefault(group_name, []).append(logo)
        key_map[name] = str(f.relative_to(LOCAL_SCHOOL_LOGO_DIR))

    global _local_key_to_file
    _local_key_to_file = key_map
    return sorted(logos, key=lambda item: item["name"]), _build_group_payload(grouped)


def _list_cos_school_logo_keys() -> list[str]:
    from backend.core.cos_client import build_cos_s3_client

    client, bucket = build_cos_s3_client()
    if client is None:
        return []

    keys: list[str] = []
    for prefix in COS_PREFIXES:
        marker = ""
        while True:
            resp = client.list_objects(Bucket=bucket, Prefix=prefix, MaxKeys=1000, Marker=marker)
            for obj in resp.get("Contents", []):
                key = obj["Key"]
                lower = key.lower()
                if key.endswith("/"):
                    continue
                if prefix and not key.startswith(prefix):
                    continue
                rel = key[len(prefix):] if prefix and key.startswith(prefix) else key
                if not rel or rel.startswith("/"):
                    continue
                if not lower.endswith(tuple(LOCAL_SCHOOL_LOGO_EXTS)):
                    continue
                keys.append(key)
            if resp.get("IsTruncated") == "true":
                marker = resp.get("NextMarker", "")
                if not marker:
                    break
            else:
                break
    return sorted(set(keys))


def _scan_cos_school_logos() -> tuple[list[dict], list[dict]]:
    global _cos_cache, _cos_group_cache, _cos_cache_time, _cos_key_to_file

    if (
        _cos_cache is not None
        and _cos_group_cache is not None
        and (time.time() - _cos_cache_time) < _CACHE_TTL
    ):
        return _cos_cache, _cos_group_cache

    try:
        keys = _list_cos_school_logo_keys()
        if not keys:
            return [], []

        logos: list[dict] = []
        grouped: dict[str, list[dict]] = {}
        key_map: dict[str, str] = {}
        for object_key in keys:
            rel = object_key[len(COS_PREFIXES[0]):] if object_key.startswith(COS_PREFIXES[0]) else object_key
            rel_path = Path(rel)
            name = rel_path.stem.strip()
            if not name:
                continue
            group_name = rel_path.parts[0] if len(rel_path.parts) > 1 else DEFAULT_GROUP_NAME
            logo = {
                "key": name,
                "name": name,
                "group": group_name,
                "url": f"{COS_BASE_URL}/{urllib.request.quote(object_key, safe='/')}",
                "keywords": _build_keywords(name),
            }
            logos.append(logo)
            grouped.setdefault(group_name, []).append(logo)
            key_map[name] = object_key

        _cos_cache = sorted(logos, key=lambda item: item["name"])
        _cos_group_cache = _build_group_payload(grouped)
        _cos_cache_time = time.time()
        _cos_key_to_file = key_map
        return _cos_cache, _cos_group_cache
    except Exception as e:
        print(f"[SchoolLogo] COS 扫描失败: {e}")
        return [], []


def get_all_school_logos_with_urls() -> list[dict]:
    global _using_local

    from backend.core.cos_client import prefer_local_assets

    if prefer_local_assets():
        local_logos, _ = _scan_local_school_logos()
        if local_logos:
            _using_local = True
            return local_logos

    cos_logos, _ = _scan_cos_school_logos()
    if cos_logos:
        _using_local = False
        return cos_logos

    local_logos, _ = _scan_local_school_logos()
    if local_logos:
        _using_local = True
        return local_logos

    _using_local = False
    return []


def get_grouped_school_logos_with_urls() -> list[dict]:
    global _using_local

    from backend.core.cos_client import prefer_local_assets

    if prefer_local_assets():
        local_logos, local_groups = _scan_local_school_logos()
        if local_logos:
            _using_local = True
            return local_groups or []

    cos_logos, cos_groups = _scan_cos_school_logos()
    if cos_logos:
        _using_local = False
        return cos_groups

    local_logos, local_groups = _scan_local_school_logos()
    if local_logos:
        _using_local = True
        return local_groups or []

    _using_local = False
    return []


def _is_safe_school_logo_key(key: str) -> bool:
    if not isinstance(key, str) or not key.strip():
        return False
    if "/" in key or "\\" in key or ".." in key or "\x00" in key:
        return False
    if Path(key).is_absolute():
        return False
    return True


def _resolve_within_school_logo_dir(candidate: Path) -> Path | None:
    try:
        base_dir = LOCAL_SCHOOL_LOGO_DIR.resolve()
        resolved = candidate.resolve()
    except OSError:
        return None
    if not resolved.is_relative_to(base_dir):
        return None
    return resolved if resolved.is_file() else None


def get_school_logo_local_path(key: str) -> Path | None:
    if not _is_safe_school_logo_key(key):
        return None
    local_logos, _ = _scan_local_school_logos()
    if not local_logos:
        return None
    filename = _local_key_to_file.get(key)
    if filename:
        found = _resolve_within_school_logo_dir(LOCAL_SCHOOL_LOGO_DIR / filename)
        if found:
            return found
    for p in LOCAL_SCHOOL_LOGO_DIR.rglob("*"):
        if p.stem == key and p.suffix.lower() in LOCAL_SCHOOL_LOGO_EXTS:
            found = _resolve_within_school_logo_dir(p)
            if found:
                return found
    return None


def is_school_logo_latex_supported(key: str, *, offline: bool = False) -> bool:
    if offline:
        path = get_school_logo_local_path(key)
        return bool(path and path.suffix.lower() in LATEX_SUPPORTED_EXTS)

    get_all_school_logos_with_urls()
    if _using_local:
        path = get_school_logo_local_path(key)
        return bool(path and path.suffix.lower() in LATEX_SUPPORTED_EXTS)

    source_name = _cos_key_to_file.get(key)
    if not source_name:
        return False
    return Path(source_name).suffix.lower() in LATEX_SUPPORTED_EXTS


def get_school_logo_cos_url(key: str) -> str | None:
    get_all_school_logos_with_urls()
    if _using_local:
        if get_school_logo_local_path(key):
            return f"/api/school-logos/file/{key}"
        return None
    object_key = _cos_key_to_file.get(key)
    if not object_key:
        return None
    return f"{COS_BASE_URL}/{urllib.request.quote(object_key, safe='/')}"


def download_school_logos_to_dir(
    education_list: list,
    target_dir: str,
    *,
    offline: bool = False,
) -> dict[int, str]:
    if not offline:
        get_all_school_logos_with_urls()
    logos_dir = Path(target_dir) / "logos"
    logo_map: dict[int, str] = {}

    for idx, edu in enumerate(education_list or []):
        logo_key = edu.get("logo")
        if not logo_key:
            continue

        logos_dir.mkdir(parents=True, exist_ok=True)
        if offline or _using_local:
            src = get_school_logo_local_path(logo_key)
            if not src or not src.is_file():
                continue
            local_filename = f"school_logo_{idx}{src.suffix.lower() or '.png'}"
            local_path = logos_dir / local_filename
            try:
                shutil.copy2(src, local_path)
                logo_map[idx] = local_filename
            except Exception as e:
                print(f"[SchoolLogo] 复制失败 ({logo_key}): {e}")
            continue

        source_name = _cos_key_to_file.get(logo_key)
        if not source_name:
            continue
        ext = Path(source_name).suffix.lower() or ".png"
        local_filename = f"school_logo_{idx}{ext}"
        local_path = logos_dir / local_filename
        cos_url = get_school_logo_cos_url(logo_key)
        if not cos_url:
            continue
        try:
            from .company_logos import _download_url_to_path

            _download_url_to_path(cos_url, local_path, timeout=15.0)
            logo_map[idx] = local_filename
        except Exception as e:
            print(f"[SchoolLogo] 下载失败 ({logo_key}): {e}")

    return logo_map
