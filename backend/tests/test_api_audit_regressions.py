"""Regression tests for API audit bug fixes and security hardening.

All tests run with isolated SQLite DBs, dependency overrides, temporary paths,
and local ephemeral mock servers so repo `.env`, production DB, and `data/` are
never polluted.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Iterator

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.main as main_module
from backend.main import app
from backend.better_auth import BetterAuthUser, get_current_better_auth_user
import backend.middleware.auth as backend_auth_mod
import backend.routes.admin as admin_route
import backend.routes.config as config_route
import backend.routes.leetcode as leetcode_route
import backend.routes.resume as resume_route
import backend.routes.share as share_route
import backend.services.embedding_service as embedding_service_mod
import backend.simple as backend_simple
import database
import middleware.auth as mw_auth_mod
import models
from middleware.auth import AppUser


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def isolated_db(monkeypatch):
    """Provide an isolated in-memory SQLite session and disable prod DB side effects."""
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
    monkeypatch.delenv("LOCAL_DEV_AUTH_ENABLED", raising=False)
    for env_key in ("LOG_MODE", "NODE_ENV", "APP_ENV", "ENVIRONMENT"):
        monkeypatch.delenv(env_key, raising=False)

    app.dependency_overrides[database.get_db] = _override_get_db
    backend_db = sys.modules.get("backend.database")
    if backend_db is not None and backend_db.get_db is not database.get_db:
        app.dependency_overrides[backend_db.get_db] = _override_get_db

    try:
        yield TestingSessionLocal
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _override_user(user: AppUser | None) -> None:
    async def _get_u():
        return user

    for mod in (mw_auth_mod, backend_auth_mod):
        app.dependency_overrides[mod.get_current_user_optional] = _get_u
        if user is not None:
            app.dependency_overrides[mod.get_current_user] = _get_u


def _override_admin(admin_user: AppUser) -> None:
    async def _get_admin():
        return admin_user

    for mod in (mw_auth_mod, backend_auth_mod):
        app.dependency_overrides[mod.require_admin_only] = _get_admin


@contextmanager
def _ephemeral_uvicorn(asgi_app) -> Iterator[str]:
    port = _unused_local_port()
    config = uvicorn.Config(
        asgi_app,
        host="127.0.0.1",
        port=port,
        lifespan="off",
        log_level="error",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("Ephemeral uvicorn failed to start within 5s")
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)


# 1. Chinese resume name export
def test_chinese_resume_name_export_rfc5987(isolated_db):
    user = AppUser(
        id="u_export_cn",
        email="cn@example.com",
        name="张三",
        role="user",
        pdf_download_count=0,
    )
    _override_user(user)

    db = isolated_db()
    try:
        db.add(
            models.Resume(
                id="res_cn_only",
                user_id=user.id,
                name="张三_后端简历",
                data={"basic": {"name": "张三"}},
            )
        )
        db.add(
            models.Resume(
                id="res_cn_mix",
                user_id=user.id,
                name="张三_Backend",
                data={"basic": {"name": "张三"}},
            )
        )
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    resp_cn = client.get("/api/resumes/res_cn_only/export")
    assert resp_cn.status_code == 200
    cd_cn = resp_cn.headers["content-disposition"]
    cd_cn.encode("latin-1")
    assert 'filename="res_cn_only.json"' in cd_cn
    assert f"filename*=UTF-8''{urllib.parse.quote('张三_后端简历.json', safe='')}" in cd_cn
    assert resp_cn.json()["name"] == "张三_后端简历"

    resp_mix = client.get("/api/resumes/res_cn_mix/export")
    assert resp_mix.status_code == 200
    cd_mix = resp_mix.headers["content-disposition"]
    cd_mix.encode("latin-1")
    assert 'filename="Backend.json"' in cd_mix
    assert f"filename*=UTF-8''{urllib.parse.quote('张三_Backend.json', safe='')}" in cd_mix


# 2. Duplicate POST /api/resumes returns 409 instead of 500
def test_duplicate_create_resume_returns_409(isolated_db):
    user = AppUser(
        id="u_dup_resume",
        email="dup@example.com",
        name="DupUser",
        role="user",
        pdf_download_count=0,
    )
    _override_user(user)
    client = TestClient(app)

    payload = {
        "id": "dup_resume_001",
        "name": "主简历",
        "data": {"basic": {"name": "测试"}},
    }
    first = client.post("/api/resumes", json=payload)
    assert first.status_code == 200

    second = client.post("/api/resumes", json=payload)
    assert second.status_code == 409
    assert "已存在" in second.json()["detail"]

    # Also verify SQLAlchemyError commit race branch rolls back cleanly -> 409
    def _failing_commit_db():
        db = isolated_db()
        orig_commit = db.commit

        def _raise_integrity():
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))

        db.commit = _raise_integrity  # type: ignore[method-assign]
        try:
            yield db
        finally:
            db.commit = orig_commit  # type: ignore[method-assign]
            db.close()

    app.dependency_overrides[database.get_db] = _failing_commit_db
    race_resp = client.post(
        "/api/resumes",
        json={"id": "race_resume_002", "name": "并发简历", "data": {"basic": {"name": "R"}}},
    )
    assert race_resp.status_code == 409


# 3. Semantic search routes require auth (401 unauthenticated, 200 authenticated without TypeError)
def test_semantic_search_requires_auth_and_handles_sqlite(isolated_db, monkeypatch):
    client = TestClient(app)

    assert client.post("/api/search/semantic", json={"query": "Python"}).status_code == 401
    assert client.post("/api/search/embeddings/generate/res_1").status_code == 401
    assert client.get("/api/search/embeddings/status/res_1").status_code == 401

    user = AppUser(
        id="u_sem_search",
        email="sem@example.com",
        name="SemUser",
        role="user",
        pdf_download_count=0,
    )
    _override_user(user)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    res_search = client.post("/api/search/semantic", json={"query": "Python 后端"})
    assert res_search.status_code == 200
    assert res_search.json() == []

    res_gen = client.post("/api/search/embeddings/generate/res_1")
    assert res_gen.status_code == 200
    assert res_gen.json() == {"status": "error", "message": "Failed to generate embeddings"}

    res_status = client.get("/api/search/embeddings/status/res_1")
    assert res_status.status_code == 200
    assert res_status.json() == {"resume_id": "res_1", "total_embeddings": 0, "by_type": {}}

    # Verify pgvector / runtime exception fallback returns 200 instead of 500
    def _boom(*args, **kwargs):
        raise RuntimeError("pgvector extension unavailable")

    monkeypatch.setattr(embedding_service_mod.EmbeddingService, "search_similar", _boom)
    monkeypatch.setattr(embedding_service_mod, "create_embeddings_for_user_resume", _boom)
    assert client.post("/api/search/semantic", json={"query": "Go"}).json() == []
    assert client.post("/api/search/embeddings/generate/res_1").json() == {
        "status": "error",
        "message": "Failed to generate embeddings",
    }


# 4. MCP SSE mounted at /mcp advertises /mcp/messages/?session_id=... and accepts 202
def test_mcp_sse_mounted_prefix_roundtrip(isolated_db):
    async def _run_mcp_sse_roundtrip(base_url: str) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            async with client.stream("GET", f"{base_url}/mcp/sse") as sse_resp:
                assert sse_resp.status_code == 200
                advertised_uri: str | None = None
                current_event: str | None = None
                async for line in sse_resp.aiter_lines():
                    if line.startswith("event:"):
                        current_event = line.split(":", 1)[1].strip()
                    elif line.startswith("data:") and current_event == "endpoint":
                        advertised_uri = line.split(":", 1)[1].strip()
                        break

                assert advertised_uri is not None
                assert advertised_uri.startswith("/mcp/messages/?session_id=")

                post_resp = await client.post(
                    f"{base_url}{advertised_uri}",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "audit-verifier", "version": "1.0"},
                        },
                    },
                )
                assert post_resp.status_code == 202

    with _ephemeral_uvicorn(app) as base_url:
        asyncio.run(_run_mcp_sse_roundtrip(base_url))


# 5. Agent resume content path traversal blocked (400, not 200)
def test_agent_resume_content_path_traversal_blocked(isolated_db, monkeypatch):
    monkeypatch.setenv("AGENT_ENABLED", "true")
    client = TestClient(app)

    for bad_path in (".env", "../.env", "/etc/passwd", "app/docs/../../.env", "README.md"):
        resp = client.get("/api/agent/resume/content", params={"file_path": bad_path})
        assert resp.status_code == 400, f"Expected 400 for {bad_path}, got {resp.status_code}"
        assert resp.json()["detail"] == "Invalid resume file path"

        sec_resp = client.get(
            "/api/agent/resume/section/summary", params={"file_path": bad_path}
        )
        assert sec_resp.status_code == 400

    list_resp = client.get("/api/agent/resume/list")
    assert list_resp.status_code == 200
    assert "files" in list_resp.json()

    valid_missing = client.get(
        "/api/agent/resume/content", params={"file_path": "app/docs/__nonexistent_audit__.md"}
    )
    assert valid_missing.status_code == 404


# 6. Mock billing checkout disabled in production (403) unless ALLOW_MOCK_CHECKOUT=true
def test_mock_billing_checkout_prod_gate(isolated_db, monkeypatch):
    async def _fake_ba_user():
        return BetterAuthUser(id="ba_billing_1", email="bill@example.com", name="Buyer")

    app.dependency_overrides[get_current_better_auth_user] = _fake_ba_user
    client = TestClient(app)

    monkeypatch.setenv("LOG_MODE", "production")
    monkeypatch.delenv("ALLOW_MOCK_CHECKOUT", raising=False)
    blocked = client.post("/api/billing/mock-checkout", json={"package": "starter"})
    assert blocked.status_code == 403

    monkeypatch.setenv("ALLOW_MOCK_CHECKOUT", "true")
    allowed = client.post("/api/billing/mock-checkout", json={"package": "starter"})
    assert allowed.status_code == 200
    assert allowed.json()["plan"] == "starter"
    assert allowed.json()["credits"] == 50


# 8. LeetCode missing slug -> 422, missing problem on /run & /submit -> 404
def test_leetcode_missing_slug_and_not_found(isolated_db, tmp_path: Path):
    client = TestClient(app)

    assert client.post("/api/leetcode/problems", json={}).status_code == 422
    assert client.post("/api/leetcode/problems", json={"slug": "   "}).status_code == 422
    assert (
        client.post(
            "/api/leetcode/run",
            json={"slug": "nonexistent-audit-problem", "code": "package main", "testCases": []},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/leetcode/submit",
            json={"slug": "nonexistent-audit-problem", "code": "package main"},
        ).status_code
        == 404
    )

    # Also verify isolated router instance against tmp_path
    iso_app = FastAPI()
    iso_app.include_router(leetcode_route.create_router(base_dir=tmp_path))
    iso_client = TestClient(iso_app)
    assert iso_client.post("/api/leetcode/problems", json={"title": "No Slug"}).status_code == 422
    assert (
        iso_client.post(
            "/api/leetcode/run",
            json={"slug": "missing", "code": "package main", "testCases": []},
        ).status_code
        == 404
    )
    assert (
        iso_client.post(
            "/api/leetcode/submit",
            json={"slug": "missing", "code": "package main"},
        ).status_code
        == 404
    )


# 9. Share expire_days=999999999 -> 422; prod GET /shares & DELETE /share/{id} require auth (401)
def test_share_validation_and_prod_auth(isolated_db, monkeypatch):
    share_route.share_store.clear()
    try:
        client = TestClient(app)

        too_large = client.post(
            "/api/resume/share",
            json={"resume_data": {"basic": {"name": "A"}}, "resume_name": "A", "expire_days": 999999999},
        )
        assert too_large.status_code == 422

        too_small = client.post(
            "/api/resume/share",
            json={"resume_data": {"basic": {"name": "A"}}, "resume_name": "A", "expire_days": 0},
        )
        assert too_small.status_code == 422

        monkeypatch.setenv("LOG_MODE", "production")
        _override_user(None)
        assert client.get("/api/resume/shares").status_code == 401
        assert client.delete("/api/resume/share/missing_id").status_code == 401

        _override_user(
            AppUser(id="u_share_1", email="s@e.com", name="ShareUser", role="user", pdf_download_count=0)
        )
        assert client.get("/api/resume/shares").status_code == 200
        assert client.delete("/api/resume/share/missing_id").status_code == 404
    finally:
        share_route.share_store.clear()


# 10. ASR recognize without ASR_API_URL returns 503; with mock server sends FormData + CocoCV UA
def test_asr_recognize_missing_url_503_and_formdata(isolated_db, monkeypatch):
    client = TestClient(app)

    monkeypatch.delenv("ASR_API_URL", raising=False)
    missing_resp = client.post(
        "/api/asr/recognize",
        files={"audio_file": ("sample.wav", b"RIFF0000WAVE", "audio/wav")},
    )
    assert missing_resp.status_code == 503

    captured: dict[str, object] = {}

    class _MockASRHandler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            captured["user_agent"] = self.headers.get("User-Agent")
            captured["content_type"] = self.headers.get("Content-Type", "")
            captured["body"] = body
            resp_bytes = json.dumps({"text": "识别成功", "confidence": 0.96}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)

        def log_message(self, format, *args):  # noqa: A002
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _MockASRHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("ASR_API_URL", f"http://127.0.0.1:{port}/recognize")
        ok_resp = client.post(
            "/api/asr/recognize",
            files={"audio_file": ("sample.wav", b"RIFF0000WAVE", "audio/wav")},
        )
        assert ok_resp.status_code == 200
        assert ok_resp.json()["success"] is True
        assert ok_resp.json()["text"] == "识别成功"
        assert captured["user_agent"] == "CocoCV/3.12.1"
        assert "multipart/form-data" in str(captured["content_type"])
        assert b'filename="sample.wav"' in captured["body"]  # type: ignore[operator]
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3.0)


# 11. Resume health-check with missing API key preserves 400 instead of wrapping as 500
def test_resume_health_check_missing_api_key_preserves_400(isolated_db, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setattr(backend_simple, "DEEPSEEK_API_KEY", "", raising=False)
    if "simple" in sys.modules:
        monkeypatch.setattr(sys.modules["simple"], "DEEPSEEK_API_KEY", "", raising=False)
    llm_simple = resume_route.call_llm.__globals__.get("simple")
    if llm_simple is not None:
        monkeypatch.setattr(llm_simple, "DEEPSEEK_API_KEY", "", raising=False)

    client = TestClient(app)
    resp = client.post(
        "/api/resume/health-check",
        json={
            "provider": "deepseek",
            "fields": [
                {"key": "summary", "label": "个人简介", "content": "5年Python后端开发经验"}
            ],
        },
    )
    assert resp.status_code == 400
    assert "DEEPSEEK_API_KEY" in resp.json()["detail"]


# 12. Config POST /api/ai/test & POST /api/chat require auth (401) in production
def test_config_ai_test_and_chat_require_auth_in_production(isolated_db, monkeypatch):
    monkeypatch.setenv("LOG_MODE", "production")
    _override_user(None)
    client = TestClient(app)

    assert (
        client.post("/api/ai/test", json={"provider": "deepseek", "prompt": "hi"}).status_code
        == 401
    )
    assert (
        client.post(
            "/api/chat", json={"messages": [{"role": "user", "content": "hi"}], "provider": "deepseek"}
        ).status_code
        == 401
    )

    _override_user(
        AppUser(id="u_cfg_1", email="cfg@e.com", name="CfgUser", role="user", pdf_download_count=0)
    )
    monkeypatch.setattr(
        config_route,
        "call_llm",
        lambda provider, prompt, return_usage=False: (
            {"content": "pong", "usage": {"total_tokens": 2}} if return_usage else "pong"
        ),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-dummy")

    ai_resp = client.post("/api/ai/test", json={"provider": "deepseek", "prompt": "ping"})
    assert ai_resp.status_code == 200
    assert ai_resp.json()["result"] == "pong"

    chat_resp = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "ping"}], "provider": "deepseek"},
    )
    assert chat_resp.status_code == 200
    assert chat_resp.json()["content"] == "pong"


# 13. Admin user routes on SQLite fallback cleanly to 200/404; remote PDF unreachable -> 502
def test_admin_sqlite_fallback_and_remote_pdf_502(isolated_db, monkeypatch):
    admin_user = AppUser(
        id="ba_admin_root",
        email="admin@example.com",
        name="Admin",
        role="admin",
        pdf_download_count=0,
    )
    _override_admin(admin_user)

    db = isolated_db()
    try:
        db.add(
            models.BetterAuthEntitlement(
                better_auth_user_id="ba_sqlite_user1",
                email="sqlite1@example.com",
                name="SQLiteUser",
                role="member",
                pdf_download_count=4,
            )
        )
        db.add(
            models.Resume(
                id="sqlite_res_1",
                user_id="ba_sqlite_user1",
                name="R1",
                data={"basic": {"name": "R1"}},
            )
        )
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    stats_resp = client.get("/api/admin/stats/users")
    assert stats_resp.status_code == 200
    assert stats_resp.json() == {"total_users": 1}

    users_resp = client.get("/api/admin/users")
    assert users_resp.status_code == 200
    body = users_resp.json()
    assert body["total"] == 1
    assert body["users"][0]["id"] == "ba_sqlite_user1"
    assert body["users"][0]["resume_count"] == 1
    assert body["users"][0]["pdf_download_count"] == 4

    missing_role_resp = client.patch(
        "/api/admin/users/no_such_user/role", json={"role": "staff"}
    )
    assert missing_role_resp.status_code == 404

    ok_role_resp = client.patch(
        "/api/admin/users/ba_sqlite_user1/role", json={"role": "staff"}
    )
    assert ok_role_resp.status_code == 200
    assert ok_role_resp.json() == {
        "ok": True,
        "email": "sqlite1@example.com",
        "role": "staff",
    }

    unreachable_port = _unused_local_port()
    monkeypatch.setenv("REMOTE_PDF_RENDER_BASE_URL", f"http://127.0.0.1:{unreachable_port}")
    pdf_resp = client.post(
        "/api/admin/pdf/render",
        json={"resume": {"name": "tester"}, "section_order": []},
    )
    assert pdf_resp.status_code == 502
    assert "不可达" in pdf_resp.json()["detail"]


# 14. Unconfigured COS on logos/school-logos/photos returns 503 instead of 500
def test_unconfigured_cos_returns_503(isolated_db, monkeypatch):
    monkeypatch.delenv("COS_SECRET_ID", raising=False)
    monkeypatch.delenv("COS_SECRET_KEY", raising=False)

    user = AppUser(
        id="u_cos_admin",
        email="cos@example.com",
        name="CosAdmin",
        role="admin",
        pdf_download_count=0,
    )
    _override_user(user)
    _override_admin(user)

    client = TestClient(app)
    tiny_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"

    assert (
        client.post(
            "/api/logos/upload",
            files={"file": ("logo.png", tiny_png, "image/png")},
        ).status_code
        == 503
    )
    assert client.delete("/api/logos", params={"filename": "logo.png"}).status_code == 503

    assert (
        client.post(
            "/api/school-logos/upload",
            files={"file": ("school.png", tiny_png, "image/png")},
            data={"group": "985"},
        ).status_code
        == 503
    )
    assert (
        client.delete(
            "/api/school-logos",
            params={"filename": "school.png", "group": "985"},
        ).status_code
        == 503
    )

    assert (
        client.post(
            "/api/photos/upload",
            files={"file": ("photo.png", tiny_png, "image/png")},
        ).status_code
        == 503
    )
    assert client.get("/api/photos/list").status_code == 503


# 15. OpenAPI schema has no unused "TTS" tag when tts_router is not mounted
def test_openapi_schema_excludes_unused_tts_tag(isolated_db):
    assert main_module.routes_module.tts_router is None

    app.openapi_schema = None
    schema = app.openapi()
    top_tags = [t.get("name") for t in schema.get("tags", [])]
    assert "TTS" not in top_tags

    used_tags = {
        tag
        for path_item in schema.get("paths", {}).values()
        for op in path_item.values()
        if isinstance(op, dict)
        for tag in op.get("tags", [])
    }
    assert "TTS" not in used_tags
