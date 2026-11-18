"""Tests for Issue #97: runtime toggles, /api/agent guard, anonymous compatibility, data URL photos, and AI guard."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.latex_generator as latex_generator
import backend.main as main_module
import backend.middleware.auth as backend_auth_mod
import backend.routes.config as config_route
import backend.routes.pdf as pdf_route
import backend.routes.resume as resume_route
import backend.services.ai_guard as ai_guard
import backend.services.runtime_features as runtime_features
import backend.services.zhipu_layout as zhipu_layout
import backend.simple as backend_simple
import database
import middleware.auth as mw_auth_mod
import models
from backend.llm_utils import retry_with_backoff
from backend.main import app
from middleware.auth import AppUser

VALID_PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"


@pytest.fixture(autouse=True)
def _isolated_runtime_and_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """隔离 .env、环境变量、AI 熔断器/限流器与头像缓存，确保测试互不污染。"""
    for key in (
        "AUTH_ENABLED",
        "AGENT_ENABLED",
        "EDITOR_AI_ENABLED",
        "ADMIN_SWITCH_TOKEN",
        "ANON_AI_IMPORT_HOURLY_LIMIT",
        "ANON_AI_REWRITE_HOURLY_LIMIT",
        "AI_QUOTA_COOLDOWN_SECONDS",
        "FORCE_ANON_RATE_LIMIT_IN_TESTS",
        "LOG_MODE",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setattr(runtime_features, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(config_route, "ROOT_DIR", tmp_path)
    runtime_features.reset_runtime_features_cache()
    ai_guard.reset_ai_guard()
    latex_generator.clear_user_photo_cache()

    try:
        yield tmp_path
    finally:
        app.dependency_overrides.clear()
        runtime_features.reset_runtime_features_cache()
        ai_guard.reset_ai_guard()
        latex_generator.clear_user_photo_cache()


@pytest.fixture
def isolated_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(
        "backend.middleware.observability._persist_observability",
        lambda **kwargs: None,
    )
    app.dependency_overrides[database.get_db] = _override_get_db
    backend_db = os.sys.modules.get("backend.database")
    if backend_db is not None and backend_db.get_db is not database.get_db:
        app.dependency_overrides[backend_db.get_db] = _override_get_db

    try:
        yield TestingSessionLocal
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _override_optional_user(user: AppUser | None) -> None:
    async def _get_u():
        return user

    for mod in (mw_auth_mod, backend_auth_mod):
        app.dependency_overrides[mod.get_current_user_optional] = _get_u


# ---------------------------------------------------------------------------
# 1. Runtime Feature Flags + /api/features + /api/admin/features
# ---------------------------------------------------------------------------


def test_runtime_features_defaults_and_env_mtime_hot_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    env_file = tmp_path / ".env"

    assert runtime_features.get_runtime_features(env_path=env_file) == {
        "auth_enabled": False,
        "agent_enabled": False,
        "editor_ai_enabled": True,
    }
    assert runtime_features.get_admin_switch_token(env_path=env_file) == ""
    assert runtime_features.get_anon_ai_import_hourly_limit(env_path=env_file) == 10
    assert runtime_features.get_anon_ai_rewrite_hourly_limit(env_path=env_file) == 30
    assert runtime_features.get_ai_quota_cooldown_seconds(env_path=env_file) == 600

    # 写入 .env 文件后应按 mtime_ns 自动热同步
    env_file.write_text(
        "AUTH_ENABLED=true\n"
        "AGENT_ENABLED=false\n"
        "EDITOR_AI_ENABLED=false\n"
        "ADMIN_SWITCH_TOKEN=top-secret-token\n"
        "ANON_AI_IMPORT_HOURLY_LIMIT=4\n"
        "ANON_AI_REWRITE_HOURLY_LIMIT=12\n"
        "AI_QUOTA_COOLDOWN_SECONDS=90\n",
        encoding="utf-8",
    )
    assert runtime_features.get_runtime_features(env_path=env_file) == {
        "auth_enabled": True,
        "agent_enabled": False,
        "editor_ai_enabled": False,
    }
    assert runtime_features.get_admin_switch_token(env_path=env_file) == "top-secret-token"
    assert runtime_features.get_anon_ai_import_hourly_limit(env_path=env_file) == 4
    assert runtime_features.get_anon_ai_rewrite_hourly_limit(env_path=env_file) == 12
    assert runtime_features.get_ai_quota_cooldown_seconds(env_path=env_file) == 90

    # 模拟其他 Worker 更新磁盘 .env 并推进 mtime_ns
    st = env_file.stat()
    env_file.write_text(
        "AUTH_ENABLED=false\nAGENT_ENABLED=true\nEDITOR_AI_ENABLED=true\n",
        encoding="utf-8",
    )
    os.utime(env_file, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000))

    assert runtime_features.get_runtime_features(env_path=env_file) == {
        "auth_enabled": False,
        "agent_enabled": True,
        "editor_ai_enabled": True,
    }
    # 已从 .env 移除的托管键回落到默认值
    assert runtime_features.get_admin_switch_token(env_path=env_file) == ""
    assert runtime_features.get_anon_ai_import_hourly_limit(env_path=env_file) == 10


def test_features_get_and_admin_put_access_control_and_persistence(
    tmp_path: Path, isolated_db, monkeypatch: pytest.MonkeyPatch
):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# 顶部注释必须保留\n"
        "DEEPSEEK_API_KEY=sk-existing-keep-123\n"
        "AUTH_ENABLED=false\n"
        "# 中间注释\n"
        "EDITOR_AI_ENABLED=true\n",
        encoding="utf-8",
    )

    client = TestClient(app)

    # 1. GET /api/features 公开无需认证
    get_res = client.get("/api/features")
    assert get_res.status_code == 200
    assert get_res.json() == {
        "auth_enabled": False,
        "agent_enabled": False,
        "editor_ai_enabled": True,
    }

    # 2. 生产/非本地未登录 -> 401
    monkeypatch.setenv("LOG_MODE", "production")
    _override_optional_user(None)
    assert client.put("/api/admin/features", json={"agent_enabled": True}).status_code == 401

    # 3. 已登录普通用户 -> 403
    regular = AppUser(id="u1", email="u@e.com", name="User", role="user", pdf_download_count=0)
    _override_optional_user(regular)
    assert client.put("/api/admin/features", json={"agent_enabled": True}).status_code == 403

    # 4. ADMIN_SWITCH_TOKEN 通过 X-Admin-Switch-Token 或 Authorization Bearer 放行
    monkeypatch.setenv("ADMIN_SWITCH_TOKEN", "switch-secret-97")
    assert (
        client.put(
            "/api/admin/features",
            json={"agent_enabled": True},
            headers={"X-Admin-Switch-Token": "wrong-token"},
        ).status_code
        == 403  # 回落到已登录非管理员 -> 403
    )

    ok_header = client.put(
        "/api/admin/features",
        json={"agent_enabled": True},
        headers={"X-Admin-Switch-Token": "switch-secret-97"},
    )
    assert ok_header.status_code == 200
    assert ok_header.json() == {
        "ok": True,
        "features": {
            "auth_enabled": False,
            "agent_enabled": True,
            "editor_ai_enabled": True,
        },
    }

    _override_optional_user(None)
    ok_bearer = client.put(
        "/api/admin/features",
        json={"editor_ai_enabled": False},
        headers={"Authorization": "Bearer switch-secret-97"},
    )
    assert ok_bearer.status_code == 200
    assert ok_bearer.json()["features"]["editor_ai_enabled"] is False

    # 5. 已登录管理员放行
    admin = AppUser(id="a1", email="a@e.com", name="Admin", role="admin", pdf_download_count=0)
    _override_optional_user(admin)
    ok_admin = client.put("/api/admin/features", json={"auth_enabled": True})
    assert ok_admin.status_code == 200
    assert ok_admin.json()["features"] == {
        "auth_enabled": True,
        "agent_enabled": True,
        "editor_ai_enabled": False,
    }

    # 6. 本地未登录开发环境放行（127.0.0.1 且非 production 且无代理头）
    monkeypatch.setenv("LOG_MODE", "development")
    _override_optional_user(None)
    local_client = TestClient(app, client=("127.0.0.1", 50000))
    ok_local = local_client.put("/api/admin/features", json={"agent_enabled": False})
    assert ok_local.status_code == 200
    assert ok_local.json()["features"]["agent_enabled"] is False

    # 带 X-Forwarded-For 的本地 IP 不再视作本地直连 -> 401
    assert (
        local_client.put(
            "/api/admin/features",
            json={"agent_enabled": True},
            headers={"X-Forwarded-For": "203.0.113.10"},
        ).status_code
        == 401
    )

    # 7. 验证 .env 持久化保留注释和已有密钥
    env_text = env_file.read_text(encoding="utf-8")
    assert "# 顶部注释必须保留\n" in env_text
    assert "# 中间注释\n" in env_text
    assert "DEEPSEEK_API_KEY=sk-existing-keep-123\n" in env_text
    assert "AUTH_ENABLED=true\n" in env_text
    assert "AGENT_ENABLED=false\n" in env_text
    assert "EDITOR_AI_ENABLED=false\n" in env_text


# ---------------------------------------------------------------------------
# 2. Backend Sidebar Agent Guard (/api/agent/*)
# ---------------------------------------------------------------------------


def test_agent_endpoints_blocked_by_default_and_hot_toggleable(isolated_db, monkeypatch):
    client = TestClient(app)

    # 默认 AGENT_ENABLED 未设置 -> 503 AGENT_DISABLED
    for method, path in (
        ("GET", "/api/agent"),
        ("GET", "/api/agent/resume/list"),
        ("POST", "/api/agent/chat/stream"),
    ):
        resp = client.request(method, path)
        assert resp.status_code == 503
        body = resp.json()
        assert body["code"] == "AGENT_DISABLED"
        assert isinstance(body["detail"], str) and body["detail"]
        assert body["message"] == body["detail"]

    # 显式 AGENT_ENABLED=false -> 503
    monkeypatch.setenv("AGENT_ENABLED", "false")
    assert client.get("/api/agent/resume/list").status_code == 503

    # OPTIONS 预检不拦截
    opt_resp = client.options(
        "/api/agent/resume/list",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert opt_resp.status_code != 503

    # 非 /api/agent 路由不受影响
    assert client.get("/api/features").status_code == 200

    # 通过 /api/admin/features 热开启后，无需重启立即放行
    local_client = TestClient(app, client=("127.0.0.1", 50000))
    assert local_client.put("/api/admin/features", json={"agent_enabled": True}).status_code == 200
    assert client.get("/api/agent/resume/list").status_code == 200

    # 热关闭后立即重新拦截
    assert local_client.put("/api/admin/features", json={"agent_enabled": False}).status_code == 200
    assert client.get("/api/agent/resume/list").status_code == 503


# ---------------------------------------------------------------------------
# 3. Anonymous Score & PDF Quota Compatibility
# ---------------------------------------------------------------------------


def test_anonymous_score_and_pdf_quota_compatibility(
    isolated_db, monkeypatch: pytest.MonkeyPatch
):
    _override_optional_user(None)
    client = TestClient(app)

    # AUTH_ENABLED=false 时：/api/pdf/quota 和 /api/pdf/downloads/record 返回无限配额
    q_resp = client.get("/api/pdf/quota")
    assert q_resp.status_code == 200
    assert q_resp.json() == {
        "unlimited": True,
        "limit": None,
        "used": 0,
        "remaining": None,
    }

    r_resp = client.post("/api/pdf/downloads/record")
    assert r_resp.status_code == 200
    assert r_resp.json() == {
        "unlimited": True,
        "limit": None,
        "used": 0,
        "remaining": None,
    }

    # AUTH_ENABLED=false 时：匿名 /api/resume/score 不再直接 401
    # - 传不存在的 resume_id 返回 404（且不越权访问别人数据）
    db = isolated_db()
    try:
        db.add(
            models.Resume(
                id="other_user_resume",
                user_id="real_owner_id",
                name="Other",
                data={"skills": ["Python"]},
            )
        )
        db.commit()
    finally:
        db.close()

    idor_score = client.post(
        "/api/resume/score",
        json={"resume_id": "other_user_resume", "jd_text": "Python 后端开发"},
    )
    assert idor_score.status_code == 404

    # - 传内联 resume_data 可在匿名模式直接评分（Mock LLM）
    import backend.services.scoring_service as scoring_service_mod

    monkeypatch.setattr(
        scoring_service_mod,
        "call_llm",
        lambda provider, prompt: json.dumps({"score": 88, "reasons": ["匹配：具备 Python 经验"]}),
    )
    inline_score = client.post(
        "/api/resume/score",
        json={
            "resume_data": {
                "skills": ["Python"],
                "experience": [{"company": "A", "details": "Python 后端"}],
                "education": [{"school": "B", "degree": "本科"}],
                "projects": [{"name": "P", "details": "FastAPI"}],
            },
            "jd_text": "Python 后端开发",
        },
    )
    assert inline_score.status_code == 200
    assert inline_score.json()["overall_score"] > 0

    # AUTH_ENABLED=true 时：匿名均应返回 401
    monkeypatch.setenv("AUTH_ENABLED", "true")
    assert client.get("/api/pdf/quota").status_code == 401
    assert client.post("/api/pdf/downloads/record").status_code == 401
    assert (
        client.post(
            "/api/resume/score",
            json={"resume_id": "other_user_resume", "jd_text": "Python"},
        ).status_code
        == 401
    )

    # 已登录用户恢复正常配额计数
    ent_db = isolated_db()
    try:
        ent_db.add(
            models.BetterAuthEntitlement(
                better_auth_user_id="u_quota_1",
                email="q@test.com",
                name="Q",
                role="user",
                pdf_download_count=0,
            )
        )
        ent_db.commit()
    finally:
        ent_db.close()

    _override_optional_user(
        AppUser(
            id="u_quota_1",
            email="q@test.com",
            name="Q",
            role="user",
            pdf_download_count=0,
        )
    )
    auth_q = client.get("/api/pdf/quota")
    assert auth_q.status_code == 200
    assert auth_q.json()["unlimited"] is False
    assert auth_q.json()["limit"] == 10
    assert auth_q.json()["used"] == 0


# ---------------------------------------------------------------------------
# 4. Transient data:image/... Portrait Photo Decode
# ---------------------------------------------------------------------------


def test_transient_data_url_photo_decode_and_no_global_cache(tmp_path: Path):
    png_b64 = base64.b64encode(VALID_PNG_BYTES).decode("ascii")
    jpg_b64 = base64.b64encode(VALID_JPEG_BYTES).decode("ascii")

    # 1. PNG data URL 在 offline=True 下也能瞬时解码写入 temp_dir，不入 _USER_PHOTO_CACHE
    d1 = tmp_path / "run_png"
    res1 = latex_generator._download_user_photo_to_dir(
        f"data:image/png;base64,{png_b64}",
        str(d1),
        offline=True,
    )
    assert res1 == "photo.png"
    assert (d1 / "logos" / "photo.png").read_bytes() == VALID_PNG_BYTES
    assert len(latex_generator._USER_PHOTO_CACHE) == 0

    # 2. JPEG data URL 正确识别魔数并返回 photo.jpg
    d2 = tmp_path / "run_jpg"
    res2 = latex_generator._download_user_photo_to_dir(
        f"data:image/jpeg;base64,{jpg_b64}",
        str(d2),
        offline=False,
    )
    assert res2 == "photo.jpg"
    assert (d2 / "logos" / "photo.jpg").read_bytes() == VALID_JPEG_BYTES
    assert len(latex_generator._USER_PHOTO_CACHE) == 0

    # 3. WebP data URL 内存转码为 .jpg（无透明通道）或 .png（含透明通道），绝不进入 _USER_PHOTO_CACHE
    from io import BytesIO
    from PIL import Image

    rgb_webp_buf = BytesIO()
    Image.new("RGB", (4, 4), color=(12, 34, 56)).save(rgb_webp_buf, format="WEBP")
    rgb_webp_bytes = rgb_webp_buf.getvalue()
    rgb_webp_b64 = base64.b64encode(rgb_webp_bytes).decode("ascii")

    d_webp_rgb = tmp_path / "run_webp_rgb"
    res_webp_rgb = latex_generator._download_user_photo_to_dir(
        f"data:image/webp;base64,{rgb_webp_b64}",
        str(d_webp_rgb),
        offline=True,
    )
    assert res_webp_rgb == "photo.jpg"
    converted_jpg = (d_webp_rgb / "logos" / "photo.jpg").read_bytes()
    assert latex_generator._detect_xelatex_image_ext(converted_jpg) == ".jpg"
    assert len(latex_generator._USER_PHOTO_CACHE) == 0

    rgba_webp_buf = BytesIO()
    Image.new("RGBA", (4, 4), color=(12, 34, 56, 128)).save(rgba_webp_buf, format="WEBP")
    rgba_webp_b64 = base64.b64encode(rgba_webp_buf.getvalue()).decode("ascii")

    d_webp_rgba = tmp_path / "run_webp_rgba"
    res_webp_rgba = latex_generator._download_user_photo_to_dir(
        f"data:image/webp;base64,{rgba_webp_b64}",
        str(d_webp_rgba),
        offline=True,
    )
    assert res_webp_rgba == "photo.png"
    converted_png = (d_webp_rgba / "logos" / "photo.png").read_bytes()
    assert latex_generator._detect_xelatex_image_ext(converted_png) == ".png"
    assert len(latex_generator._USER_PHOTO_CACHE) == 0

    # 4. 拦截缺 ;base64,、非法 base64、超 2MB、以及伪装 SVG/WebP 魔数
    d3 = tmp_path / "run_bad"
    assert (
        latex_generator._download_user_photo_to_dir(
            "data:image/png,not-base64", str(d3)
        )
        is None
    )
    assert (
        latex_generator._download_user_photo_to_dir(
            "data:image/png;base64,%%%invalid%%%", str(d3)
        )
        is None
    )
    svg_b64 = base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>").decode("ascii")
    assert (
        latex_generator._download_user_photo_to_dir(
            f"data:image/svg+xml;base64,{svg_b64}", str(d3)
        )
        is None
    )
    # 即使声明为 image/png，魔数不是 PNG/JPEG/PDF（包括伪装的 WebP 或 SVG）一样拒收
    assert (
        latex_generator._download_user_photo_to_dir(
            f"data:image/png;base64,{svg_b64}", str(d3)
        )
        is None
    )
    assert (
        latex_generator._download_user_photo_to_dir(
            f"data:image/png;base64,{rgb_webp_b64}", str(d3)
        )
        is None
    )
    assert latex_generator._detect_xelatex_image_ext(rgb_webp_bytes) is None
    oversized_bytes = VALID_PNG_BYTES + b"A" * (2 * 1024 * 1024 + 1 - len(VALID_PNG_BYTES))
    oversized_b64 = base64.b64encode(oversized_bytes).decode("ascii")
    assert (
        latex_generator._download_user_photo_to_dir(
            f"data:image/png;base64,{oversized_b64}", str(d3)
        )
        is None
    )
    assert not (d3 / "logos").exists()
    assert len(latex_generator._USER_PHOTO_CACHE) == 0


# ---------------------------------------------------------------------------
# 5. AI Feature Disabled, Quota Circuit Breaker, retry_with_backoff, & Per-IP Rate Limiter
# ---------------------------------------------------------------------------


def test_ai_feature_disabled_returns_503_with_plain_detail_while_pdf_render_stays_200(
    isolated_db, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("EDITOR_AI_ENABLED", "false")
    client = TestClient(app)

    for method, url, payload in (
        ("POST", "/api/resume/parse", {"text": "张三 后端开发"}),
        ("POST", "/api/resume/parse/stream", {"text": "张三 后端开发"}),
        ("POST", "/api/resume/health-check", {"fields": [{"key": "s", "content": "5年Python"}]}),
        ("POST", "/api/resume/rewrite/stream", {"provider": "deepseek", "resume": {"summary": "hi"}, "path": "summary", "instruction": "优化"}),
        ("POST", "/api/resume/score", {"resume_data": {"skills": ["Go"]}, "jd_text": "Go 后端"}),
        ("POST", "/api/jd/match", {"resume_data": {"skills": ["Go"]}, "jd_text": "Go 后端"}),
    ):
        resp = client.request(method, url, json=payload)
        assert resp.status_code == 503, f"Expected 503 for {url}, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["code"] == "AI_FEATURE_DISABLED"
        assert isinstance(data["detail"], str) and "[object" not in data["detail"]
        assert data["message"] == data["detail"]

    # PDF 渲染在 EDITOR_AI_ENABLED=false 时依然正常工作
    monkeypatch.setattr(pdf_route, "_prepare_latex_content", lambda *_a, **_k: "latex")
    monkeypatch.setattr(pdf_route, "_compile_pdf_bytes", lambda *_a, **_k: b"%PDF-1.4\n")
    pdf_resp = client.post("/api/pdf/render", json={"resume": {"name": "匿名用户"}, "section_order": []})
    assert pdf_resp.status_code == 200
    assert pdf_resp.content.startswith(b"%PDF-")


def test_deepseek_402_trips_circuit_breaker_and_skips_retries_and_resets_on_key_update(
    tmp_path: Path, isolated_db, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-1234567890")
    monkeypatch.setenv("AI_QUOTA_COOLDOWN_SECONDS", "600")
    backend_simple.DEEPSEEK_API_KEY = "sk-test-1234567890"

    post_calls = 0

    class _FakeResponse:
        def __init__(self, status_code: int, text: str, json_body=None):
            self.status_code = status_code
            self.text = text
            self.content = text.encode("utf-8")
            self._json = json_body
            self.encoding = "utf-8"

        def json(self):
            if self._json is not None:
                return self._json
            raise ValueError("not json")

    class _FakeSession:
        def post(self, *args, **kwargs):
            nonlocal post_calls
            post_calls += 1
            if post_calls == 1:
                return _FakeResponse(
                    402,
                    '{"error": {"message": "Insufficient Balance"}}',
                    {"error": {"message": "Insufficient Balance"}},
                )
            return _FakeResponse(
                200,
                '{"choices": [{"message": {"content": "{\\"overallScore\\": 90, \\"dimensions\\": [], \\"suggestions\\": [], \\"summary\\": \\"ok\\"}"}}]}',
                {"choices": [{"message": {"content": '{"overallScore": 90, "dimensions": [], "suggestions": [], "summary": "ok"}'}}]},
            )

    monkeypatch.setattr(backend_simple, "get_http_session", lambda: _FakeSession())

    client = TestClient(app)
    payload = {
        "provider": "deepseek",
        "fields": [{"key": "summary", "label": "简介", "content": "Python 后端开发"}],
    }

    # 第 1 次请求触发上游 402 -> 熔断并返回 503 AI_QUOTA_EXHAUSTED
    r1 = client.post("/api/resume/health-check", json=payload)
    assert r1.status_code == 503
    d1 = r1.json()
    assert d1["code"] == "AI_QUOTA_EXHAUSTED"
    assert isinstance(d1["detail"], str) and "手动编辑简历" in d1["detail"]
    assert post_calls == 1

    # 第 2 次请求在冷却期内直接熔断拦截，不再调用上游（post_calls 仍为 1）
    r2 = client.post("/api/resume/health-check", json=payload)
    assert r2.status_code == 503
    assert r2.json()["code"] == "AI_QUOTA_EXHAUSTED"
    assert post_calls == 1

    # SSE 端点在熔断期间直接返回 HTTP 503（不开启流）
    r_sse = client.post("/api/resume/parse/stream", json={"text": "张三 后端"})
    assert r_sse.status_code == 503
    assert r_sse.json()["code"] == "AI_QUOTA_EXHAUSTED"

    # retry_with_backoff 绝不重试已熔断/额度耗尽异常
    retry_attempts = 0

    @retry_with_backoff(max_retries=3, initial_delay=0.01)
    def _never_retry_quota():
        nonlocal retry_attempts
        retry_attempts += 1
        backend_simple.call_deepseek_api("hi")

    with pytest.raises(ai_guard.AiQuotaExhaustedError):
        _never_retry_quota()
    assert retry_attempts == 1

    # PDF 渲染在熔断期间仍然 200
    monkeypatch.setattr(pdf_route, "_prepare_latex_content", lambda *_a, **_k: "latex")
    monkeypatch.setattr(pdf_route, "_compile_pdf_bytes", lambda *_a, **_k: b"%PDF-1.4\n")
    assert (
        client.post("/api/pdf/render", json={"resume": {"name": "A"}, "section_order": []}).status_code
        == 200
    )

    # 通过 /api/config/keys 更新 Key 会调用 reset_ai_circuit() 立即恢复
    local_client = TestClient(app, client=("127.0.0.1", 50000))
    save_res = local_client.post(
        "/api/config/keys",
        json={"deepseek_key": "sk-fresh-new-key-123456"},
    )
    assert save_res.status_code == 200
    assert not ai_guard.is_ai_circuit_tripped()

    r3 = client.post("/api/resume/health-check", json=payload)
    assert r3.status_code == 200
    assert post_calls == 2


def test_zhipu_quota_error_trips_circuit_and_sse_midstream_emits_clean_error(
    isolated_db, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ZHIPU_API_KEY", "id1234567890.secret1234")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-1234567890")
    zhipu_layout.refresh_zhipu_api_key("id1234567890.secret1234")

    import httpx as real_httpx

    class _MockClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, *args, **kwargs):
            return SimpleNamespace(
                status_code=402,
                text='{"error":{"code":"1113","message":"账户余额不足，请充值"}}',
            )

    monkeypatch.setattr(real_httpx, "Client", _MockClient)
    client = TestClient(app)

    # /api/resume/upload-pdf 命中智谱 402 -> 返回 503 AI_QUOTA_EXHAUSTED 而非 502
    resp = client.post(
        "/api/resume/upload-pdf",
        files={"file": ("resume.pdf", b"%PDF-1.4\n...", "application/pdf")},
    )
    assert resp.status_code == 503
    assert resp.json()["code"] == "AI_QUOTA_EXHAUSTED"
    assert ai_guard.is_ai_circuit_tripped() is True

    # 重置后测试 SSE 流内触发 402 时输出干净 error 事件并触发熔断
    ai_guard.reset_ai_circuit()

    def _quota_stream(provider, prompt):
        raise ai_guard.AiQuotaExhaustedError()
        yield ""  # pragma: no cover

    monkeypatch.setattr(resume_route, "call_llm_stream", _quota_stream)
    sse_resp = client.post(
        "/api/resume/rewrite-text/stream",
        json={"text": "负责后端开发", "instruction": "更量化"},
    )
    assert sse_resp.status_code == 200
    assert "AI_QUOTA_EXHAUSTED" in sse_resp.text
    assert "503:" not in sse_resp.text


def test_anonymous_per_ip_sliding_window_rate_limiter(
    isolated_db, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("ANON_AI_IMPORT_HOURLY_LIMIT", "2")
    monkeypatch.setenv("ANON_AI_REWRITE_HOURLY_LIMIT", "3")
    monkeypatch.setattr(
        resume_route,
        "call_llm",
        lambda provider, prompt, **kwargs: json.dumps(
            {"overallScore": 85, "dimensions": [], "suggestions": [], "summary": "ok"}
        ),
    )
    monkeypatch.setattr(
        resume_route,
        "parse_resume_text_parallel",
        lambda *a, **k: None,
    )

    async def _fake_parse_serial(body):
        return {"resume": {"name": "测试"}, "provider": "deepseek"}

    monkeypatch.setattr(resume_route, "_parse_resume_serial", _fake_parse_serial)
    _override_optional_user(None)
    client = TestClient(app)

    # 1. 默认 testclient 无代理头且未开 FORCE_ANON_RATE_LIMIT_IN_TESTS 时跳过限流，不误伤单测
    for _ in range(5):
        ok_skip = client.post(
            "/api/jd/parse",
            json={"jd_text": "招聘 Python FastAPI 后端工程师"},
        )
        assert ok_skip.status_code == 200

    # 2. 带 X-Forwarded-For 触发按 IP 分桶滑动窗口限流：import 桶上限 2
    ip1_headers = {"X-Forwarded-For": "203.0.113.10"}
    ip2_headers = {"X-Forwarded-For": "203.0.113.20"}

    assert client.post("/api/resume/parse", json={"text": "张三 后端"}, headers=ip1_headers).status_code == 200
    assert client.post("/api/resume/parse", json={"text": "张三 后端"}, headers=ip1_headers).status_code == 200
    blocked_import = client.post("/api/resume/parse", json={"text": "张三 后端"}, headers=ip1_headers)
    assert blocked_import.status_code == 429
    assert blocked_import.json()["code"] == "AI_RATE_LIMITED"
    assert isinstance(blocked_import.json()["detail"], str)

    # 同一 IP 的 rewrite 桶与 import 桶相互隔离；不同 IP 也相互隔离
    assert client.post("/api/resume/parse", json={"text": "张三 后端"}, headers=ip2_headers).status_code == 200

    # 3. rewrite 桶上限 3（覆盖 /api/jd/*、/api/resume/health-check、/api/resume/score 等）
    for _ in range(3):
        r = client.post(
            "/api/jd/parse",
            json={"jd_text": "招聘 Python FastAPI 后端工程师"},
            headers=ip1_headers,
        )
        assert r.status_code == 200

    blocked_rewrite = client.post(
        "/api/resume/health-check",
        json={"fields": [{"key": "s", "content": "Python 开发"}]},
        headers=ip1_headers,
    )
    assert blocked_rewrite.status_code == 429
    assert blocked_rewrite.json()["code"] == "AI_RATE_LIMITED"

    # 4. 滑动窗口过期（超过 3600s）后自动恢复
    now_holder = {"t": 10000.0}
    monkeypatch.setattr(ai_guard.time, "monotonic", lambda: now_holder["t"])
    ai_guard.reset_ai_rate_limiter()
    monkeypatch.setenv("FORCE_ANON_RATE_LIMIT_IN_TESTS", "1")
    monkeypatch.setenv("ANON_AI_REWRITE_HOURLY_LIMIT", "1")

    assert client.post("/api/jd/parse", json={"jd_text": "招聘 Go 后端工程师"}).status_code == 200
    assert client.post("/api/jd/parse", json={"jd_text": "招聘 Go 后端工程师"}).status_code == 429
    now_holder["t"] += 3601.0
    assert client.post("/api/jd/parse", json={"jd_text": "招聘 Go 后端工程师"}).status_code == 200

    # 5. 已登录用户不受匿名 IP 限流约束
    _override_optional_user(
        AppUser(id="u_auth", email="a@test.com", name="Auth", role="user", pdf_download_count=0)
    )
    for _ in range(3):
        assert client.post("/api/jd/parse", json={"jd_text": "招聘 Go 后端工程师"}).status_code == 200


def test_agent_middleware_blocks_proxy_mode_and_compile_latex_uses_transient_data_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from fastapi import FastAPI
    from backend.services import resume_assembler

    # 1. 验证 AgentFeatureGuardMiddleware 在反向代理路由模式下也能在进入路由前拦截 /api/agent/*
    proxy_app = FastAPI()
    proxy_app.add_middleware(main_module.AgentFeatureGuardMiddleware)
    upstream_called = 0

    @proxy_app.api_route("/api/agent/{path:path}", methods=["GET", "POST"])
    async def _fake_proxy(path: str):
        nonlocal upstream_called
        upstream_called += 1
        return {"proxied": path}

    proxy_client = TestClient(proxy_app)
    r_blocked = proxy_client.get("/api/agent/history/sessions/list")
    assert r_blocked.status_code == 503
    assert r_blocked.json()["code"] == "AGENT_DISABLED"
    assert upstream_called == 0

    monkeypatch.setenv("AGENT_ENABLED", "true")
    r_ok = proxy_client.get("/api/agent/history/sessions/list")
    assert r_ok.status_code == 200
    assert upstream_called == 1

    # 2. 验证 compile_latex_to_pdf 对 data:image/... 写入 temp_dir/logos 后自动清理且不入全局缓存
    template_dir = Path(__file__).resolve().parents[2] / "latex-resume-template"
    png_b64 = base64.b64encode(VALID_PNG_BYTES).decode("ascii")
    data_url = f"data:image/png;base64,{png_b64}"
    observed: dict = {}

    def _fake_run(cmd, cwd=None, **_kwargs):
        logos_photo = Path(cwd) / "logos" / "photo.png"
        observed["temp_dir"] = cwd
        observed["photo_exists_during_compile"] = logos_photo.is_file()
        observed["photo_bytes"] = logos_photo.read_bytes() if logos_photo.is_file() else b""
        (Path(cwd) / "resume.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(latex_generator, "resolve_xelatex_executable", lambda: "/usr/bin/xelatex")
    monkeypatch.setattr(latex_generator.subprocess, "run", _fake_run)
    monkeypatch.setattr(latex_generator, "_ensure_cjk_tounicode_cmaps", lambda b, _t: b)

    resume_obj = {"name": "匿名用户", "photo": data_url, "contact": {}}
    tex = latex_generator.json_to_latex(resume_obj, section_order=[], offline=True)
    pdf_io = latex_generator.compile_latex_to_pdf(
        tex,
        template_dir,
        resume_data=resume_obj,
        section_order=[],
        offline=True,
    )
    assert pdf_io.getvalue().startswith(b"%PDF-")
    assert observed["photo_exists_during_compile"] is True
    assert observed["photo_bytes"] == VALID_PNG_BYTES
    assert not Path(observed["temp_dir"]).exists()
    assert len(latex_generator._USER_PHOTO_CACHE) == 0

    # 2b. 无效 data: URL 在编译降级告警中必须被截断，不得把完整 base64 刷入日志/warnings
    long_bad_b64 = base64.b64encode(b"<svg>" + b"x" * 200 + b"</svg>").decode("ascii")
    bad_data_url = f"data:image/png;base64,{long_bad_b64}"
    warnings_out: list[str] = []
    bad_resume_obj = {"name": "匿名用户", "photo": bad_data_url, "contact": {}}
    bad_tex = latex_generator.json_to_latex(bad_resume_obj, section_order=[], offline=True)
    latex_generator.compile_latex_to_pdf(
        bad_tex,
        template_dir,
        resume_data=bad_resume_obj,
        section_order=[],
        offline=True,
        warnings_out=warnings_out,
    )
    assert len(warnings_out) == 1
    assert warnings_out[0].endswith("...")
    assert long_bad_b64 not in warnings_out[0]

    # 3. 验证 resume_assembler 与 zhipu_layout.recognize_layout_from_images 命中 402/余额不足立即熔断
    class _Quota402Error(Exception):
        status_code = 402

    class _FakeCompletions:
        def create(self, **kwargs):
            raise _Quota402Error("Insufficient Balance")

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
    monkeypatch.setattr(resume_assembler, "_get_client", lambda _model=None: fake_client)
    with pytest.raises(ai_guard.AiQuotaExhaustedError):
        resume_assembler.assemble_resume_data("张三 后端", {}, ocr_text="张三 后端")
    assert ai_guard.is_ai_circuit_tripped() is True

    ai_guard.reset_ai_circuit()
    monkeypatch.setattr(zhipu_layout, "_get_client", lambda _key=None: fake_client)
    with pytest.raises(ai_guard.AiQuotaExhaustedError):
        zhipu_layout.recognize_layout_from_images([VALID_PNG_BYTES])
    assert ai_guard.is_ai_circuit_tripped() is True


def test_quota_signal_avoids_false_positive_on_ordinary_resume_words():
    ai_guard.reset_ai_circuit()

    # 普通简历正文或业务异常里出现 balance / quota 词汇不得误触发全局熔断
    assert ai_guard.is_quota_exhausted_signal(
        status_code=500,
        error_text="User snippet mentioned work-life balance and sales quota attainment",
    ) is False
    assert ai_guard.is_quota_exhausted_signal(
        status_code=200,
        error_text="Insufficient Balance",
    ) is False
    assert ai_guard.is_quota_exhausted_signal(
        status_code=402,
        error_text="",
    ) is True
    assert ai_guard.is_quota_exhausted_signal(
        status_code=400,
        error_text="Your account has Insufficient Balance",
    ) is True
