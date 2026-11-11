"""API Key 格式防呆校验与跨 Worker 进程 .env 热同步辅助模块。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parent.parent

_last_env_path: Optional[Path] = None
_last_env_mtime_ns: Optional[int] = None


def validate_provider_api_key(provider: str, raw_key: str) -> str:
    """校验指定通道的 API Key 格式，防止将智谱密钥误填到 DeepSeek（或反之）导致线上 401。"""
    key = (raw_key or "").strip().strip('"').strip("'")
    if not key:
        raise ValueError("API Key 不能为空")
    if "••" in key or "****" in key:
        raise ValueError("请粘贴完整明文 API Key，不能保存脱敏预览字符")

    if provider == "deepseek":
        if "." in key and not key.startswith("sk-"):
            raise ValueError(
                "检测到这是智谱 GLM-OCR 密钥格式（含点号 .），请填入下方「2. 智谱 GLM-OCR API Key」输入框，勿覆盖 DeepSeek 密钥"
            )
        if not key.startswith("sk-") or len(key) < 12:
            raise ValueError("DeepSeek 官方 API Key 必须以 sk- 开头，请检查是否填错输入框或粘贴不完整")
        return key

    if provider == "zhipu":
        if key.startswith("sk-"):
            raise ValueError(
                "检测到这是 sk- 开头的模型密钥，智谱 BigModel 密钥格式为 id.secret（含英文点号 .），请勿将 DeepSeek 密钥填入智谱输入框"
            )
        if "." not in key or len(key) < 12:
            raise ValueError("智谱 GLM-OCR API Key 格式应为 id.secret（中间含英文点号 .），请检查是否粘贴完整")
        return key

    return key


def sync_env_keys_if_changed(env_path: Optional[Path] = None) -> None:
    """当 .env 文件 mtime 变化时，自动将最新密钥同步到当前 Worker 进程的 os.environ。"""
    global _last_env_path, _last_env_mtime_ns

    target = Path(env_path) if env_path is not None else (ROOT_DIR / ".env")
    try:
        st = target.stat()
    except OSError:
        return

    if _last_env_path == target and _last_env_mtime_ns == st.st_mtime_ns:
        return

    try:
        parsed: dict[str, str] = {}
        with open(target, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                parsed[k.strip()] = v.strip().strip('"').strip("'")

        for env_key in ("DEEPSEEK_API_KEY", "ZHIPU_API_KEY", "DASHSCOPE_API_KEY"):
            if env_key in parsed:
                os.environ[env_key] = parsed[env_key]

        _last_env_path = target
        _last_env_mtime_ns = st.st_mtime_ns
    except OSError:
        return


def get_live_api_key(provider: str, env_path: Optional[Path] = None) -> str:
    """读取指定通道当前实时生效的 API Key（支持多 Worker 进程感知 .env 热更新）。"""
    sync_env_keys_if_changed(env_path=env_path)
    if provider == "deepseek":
        return (os.getenv("DEEPSEEK_API_KEY", "") or os.getenv("DASHSCOPE_API_KEY", "")).strip()
    if provider == "zhipu":
        return os.getenv("ZHIPU_API_KEY", "").strip()
    return ""
