"""
测试 AI 与 OCR 密钥统一配置接口 (/api/config/keys, /api/ai/test-keys)
"""
import importlib.util
import os
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.logger import setup_logging
setup_logging(False)

from backend.middleware.auth import AppUser, get_current_user_optional
from backend import simple
from backend.services import zhipu_layout

_config_spec = importlib.util.spec_from_file_location(
    "backend_routes_config",
    Path(__file__).resolve().parents[1] / "routes" / "config.py",
)
config_route = importlib.util.module_from_spec(_config_spec)
assert _config_spec and _config_spec.loader
_config_spec.loader.exec_module(config_route)


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """隔离 ROOT_DIR 到临时目录，避免测试修改真实 .env"""
    monkeypatch.setattr(config_route, "ROOT_DIR", tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")
    monkeypatch.setenv("ZHIPU_API_KEY", "")
    monkeypatch.setenv("FASTAPI_INTERNAL_AUTH_SECRET", "")
    monkeypatch.setenv("LOG_MODE", "development")
    simple.DEEPSEEK_API_KEY = ""
    zhipu_layout.refresh_zhipu_api_key("")
    return tmp_path


def _make_app(user: AppUser | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(config_route.router)
    app.dependency_overrides[config_route.get_current_user_optional] = lambda: user
    return app


def test_save_get_and_delete_keys_syncs_env_and_runtime(isolated_env: Path):
    admin = AppUser(id="u-admin", email="a@test.com", name="Admin", role="admin", pdf_download_count=0)
    client = TestClient(_make_app(admin))

    # 1. 初始未配置
    res0 = client.get("/api/config/keys")
    assert res0.status_code == 200
    body0 = res0.json()
    assert body0["deepseek"]["configured"] is False
    assert body0["zhipu"]["configured"] is False

    # 2. 保存 DeepSeek 与 智谱 Key
    res_save = client.post(
        "/api/config/keys",
        json={
            "deepseek_key": "sk-deepseek-1234567890abcdef",
            "zhipu_key": "7448f886f3a94a88ab031819.testkey99",
        },
    )
    assert res_save.status_code == 200
    assert res_save.json()["success"] is True

    # 校验 .env 落盘的是 DEEPSEEK_API_KEY 与 ZHIPU_API_KEY
    env_text = (isolated_env / ".env").read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY=sk-deepseek-1234567890abcdef\n" in env_text
    assert "ZHIPU_API_KEY=7448f886f3a94a88ab031819.testkey99\n" in env_text
    assert "DASHSCOPE_API_KEY=" not in env_text

    # 校验内存热更新已同步
    assert os.environ["DEEPSEEK_API_KEY"] == "sk-deepseek-1234567890abcdef"
    assert simple.DEEPSEEK_API_KEY == "sk-deepseek-1234567890abcdef"
    assert os.environ["ZHIPU_API_KEY"] == "7448f886f3a94a88ab031819.testkey99"
    assert zhipu_layout.ZHIPU_API_KEY == "7448f886f3a94a88ab031819.testkey99"

    # 3. 查询状态返回脱敏预览，不泄露明文
    res1 = client.get("/api/config/keys")
    assert res1.status_code == 200
    body1 = res1.json()
    assert body1["deepseek"]["configured"] is True
    assert "••••" in body1["deepseek"]["preview"]
    assert "1234567890abcdef" not in body1["deepseek"]["preview"]
    assert body1["zhipu"]["configured"] is True
    assert "••••" in body1["zhipu"]["preview"]

    # 4. 单独删除 zhipu key
    res_del = client.delete("/api/config/keys/zhipu")
    assert res_del.status_code == 200
    assert zhipu_layout.ZHIPU_API_KEY == ""
    body2 = client.get("/api/config/keys").json()
    assert body2["zhipu"]["configured"] is False
    assert body2["deepseek"]["configured"] is True


def test_test_keys_endpoint_single_and_all(isolated_env: Path, monkeypatch: pytest.MonkeyPatch):
    admin = AppUser(id="u-admin", email="a@test.com", name="Admin", role="admin", pdf_download_count=0)
    client = TestClient(_make_app(admin))

    client.post(
        "/api/config/keys",
        json={
            "deepseek_key": "sk-deepseek-1234567890abcdef",
            "zhipu_key": "7448f886f3a94a88ab031819.testkey99",
        },
    )

    monkeypatch.setattr(config_route, "call_llm", lambda provider, prompt, return_usage=False: "OK")
    monkeypatch.setattr(zhipu_layout, "test_zhipu_api_key", lambda key=None: None)

    res_all = client.get("/api/ai/test-keys")
    assert res_all.status_code == 200
    data_all = res_all.json()
    assert data_all["deepseek"] == {"configured": True, "ok": True}
    assert data_all["zhipu"] == {"configured": True, "ok": True}

    res_single = client.get("/api/ai/test-keys?provider=zhipu")
    assert res_single.status_code == 200
    data_single = res_single.json()
    assert "zhipu" in data_single
    assert "deepseek" not in data_single
    assert data_single["zhipu"]["ok"] is True


def test_access_control_blocks_non_admin_and_remote_anonymous(isolated_env: Path, monkeypatch: pytest.MonkeyPatch):
    # 已登录但非管理员 -> 403
    normal_user = AppUser(id="u-1", email="u@test.com", name="User", role="user", pdf_download_count=0)
    client_user = TestClient(_make_app(normal_user))
    assert client_user.get("/api/config/keys").status_code == 403
    assert client_user.post("/api/config/keys", json={"deepseek_key": "sk-1234567890"}).status_code == 403

    # 生产环境未登录匿名请求 -> 401
    monkeypatch.setenv("LOG_MODE", "production")
    client_anon = TestClient(_make_app(None))
    assert client_anon.get("/api/config/keys").status_code == 401

    # 本地开发环境 (127.0.0.1) 未登录请求 -> 允许免登配置 (200)
    monkeypatch.setenv("LOG_MODE", "development")
    client_local = TestClient(_make_app(None), client=("127.0.0.1", 50000))
    assert client_local.get("/api/config/keys").status_code == 200
