"""回归单测：防止智谱密钥误写入 DEEPSEEK_API_KEY（或反之），并验证多 Worker 进程按 .env mtime 自动热更新。"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from backend import env_keys


def test_validate_provider_api_key_rejects_cross_provider_paste():
    # 1. 把智谱 id.secret 密钥粘贴进 DeepSeek 框 -> 必须精准拦截
    with pytest.raises(ValueError, match="智谱 GLM-OCR 密钥格式"):
        env_keys.validate_provider_api_key(
            "deepseek", "0123456789abcdef0123456789abcdef.AbCdEfGh12345678"
        )

    # 2. 把 DeepSeek sk-... 密钥粘贴进智谱框 -> 必须精准拦截
    with pytest.raises(ValueError, match="sk- 开头的模型密钥"):
        env_keys.validate_provider_api_key("zhipu", "sk-abcdef1234567890abcdef")

    # 3. 把脱敏预览字符直接提交 -> 必须拦截
    with pytest.raises(ValueError, match="脱敏预览"):
        env_keys.validate_provider_api_key("deepseek", "sk-abcd••••••1234")

    # 4. 合法密钥原样通过（自动剥离首尾空格与引号）
    assert (
        env_keys.validate_provider_api_key("deepseek", '  "sk-valid1234567890"  ')
        == "sk-valid1234567890"
    )
    assert (
        env_keys.validate_provider_api_key(
            "zhipu", " '0123456789abcdef0123456789abcdef.Secret123456' "
        )
        == "0123456789abcdef0123456789abcdef.Secret123456"
    )


def test_multiworker_env_mtime_hot_reload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake_env = tmp_path / ".env"
    fake_env.write_text(
        "DEEPSEEK_API_KEY=sk-worker-initial-1111\nZHIPU_API_KEY=aaaa1111bbbb2222.InitZhipu\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-stale-0000")
    monkeypatch.setenv("ZHIPU_API_KEY", "stale.0000")
    env_keys._last_env_path = None
    env_keys._last_env_mtime_ns = None

    assert env_keys.get_live_api_key("deepseek", env_path=fake_env) == "sk-worker-initial-1111"
    assert env_keys.get_live_api_key("zhipu", env_path=fake_env) == "aaaa1111bbbb2222.InitZhipu"

    # 模拟另一个 Worker 更新了磁盘上的 .env（推进 mtime）
    st = fake_env.stat()
    fake_env.write_text(
        "DEEPSEEK_API_KEY=sk-worker-updated-2222\nZHIPU_API_KEY=cccc3333dddd4444.NewZhipu\n",
        encoding="utf-8",
    )
    os.utime(fake_env, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

    # 当前 Worker 无需重启即可立刻读到新密钥
    assert env_keys.get_live_api_key("deepseek", env_path=fake_env) == "sk-worker-updated-2222"
    assert env_keys.get_live_api_key("zhipu", env_path=fake_env) == "cccc3333dddd4444.NewZhipu"


@pytest.mark.anyio
async def test_save_keys_route_blocks_zhipu_key_into_deepseek_and_preserves_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import importlib.util
    from fastapi import HTTPException
    from backend.models import SaveKeysRequest

    config_path = Path(__file__).resolve().parents[1] / "routes" / "config.py"
    spec = importlib.util.spec_from_file_location("test_only_config_route", config_path)
    assert spec is not None and spec.loader is not None
    config_route = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config_route)

    fake_env = tmp_path / ".env"
    fake_env.write_text("DEEPSEEK_API_KEY=sk-keep-original-9999\n", encoding="utf-8")
    monkeypatch.setattr(config_route, "ROOT_DIR", tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        await config_route.save_keys(
            SaveKeysRequest(deepseek_key="0123456789abcdef0123456789abcdef.ZhipuSecret12"),
            _current_user=None,
        )

    assert exc_info.value.status_code == 400
    assert "智谱 GLM-OCR 密钥格式" in str(exc_info.value.detail)
    # 断言原有 DEEPSEEK_API_KEY 完好无损未被覆盖
    assert fake_env.read_text(encoding="utf-8") == "DEEPSEEK_API_KEY=sk-keep-original-9999\n"
