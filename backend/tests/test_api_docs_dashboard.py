"""Tests for offline Scalar + Swagger API dashboard & ScoringService user_id normalization."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.middleware.auth import AppUser, get_current_user_optional
from backend.services.scoring_service import ScoringService


@pytest.fixture
def client():
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


def test_dev_api_docs_scalar_and_swagger_are_offline(client: TestClient, monkeypatch):
    """In dev mode, Scalar (/api/docs) & Swagger (/api/swagger) load local assets only."""
    monkeypatch.delenv("ENABLE_API_DOCS", raising=False)
    monkeypatch.delenv("NODE_ENV", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("LOG_MODE", "console")

    scalar_resp = client.get("/api/docs")
    assert scalar_resp.status_code == 200
    assert "/api/docs-assets/scalar-api-reference.js" in scalar_resp.text
    assert "/api/openapi.json" in scalar_resp.text
    assert '"withDefaultFonts": false' in scalar_resp.text or "&quot;withDefaultFonts&quot;: false" in scalar_resp.text
    assert "cdn.jsdelivr.net" not in scalar_resp.text
    assert "fonts.googleapis.com" not in scalar_resp.text

    swagger_resp = client.get("/api/swagger")
    assert swagger_resp.status_code == 200
    assert "/api/docs-assets/swagger-ui-bundle.js" in swagger_resp.text
    assert "/api/docs-assets/swagger-ui.css" in swagger_resp.text
    assert "cdn.jsdelivr.net" not in swagger_resp.text

    for asset in ("scalar-api-reference.js", "swagger-ui-bundle.js", "swagger-ui.css"):
        asset_resp = client.get(f"/api/docs-assets/{asset}")
        assert asset_resp.status_code == 200
        assert len(asset_resp.content) > 1000

    blocked_asset = client.get("/api/docs-assets/not-allowed.js")
    assert blocked_asset.status_code == 404

    schema_resp = client.get("/api/openapi.json")
    assert schema_resp.status_code == 200
    schema = schema_resp.json()
    assert schema["info"]["title"] == "CocoCV API"
    assert len(schema["paths"]) >= 100

    all_tags = {
        tag
        for path_item in schema["paths"].values()
        for op in path_item.values()
        if isinstance(op, dict)
        for tag in op.get("tags", ["untagged"])
    }
    assert "untagged" not in all_tags
    assert "health" not in all_tags
    assert "resume" not in all_tags
    assert "history" not in all_tags
    assert "Agent" in all_tags


def test_prod_api_docs_require_admin_and_respect_env_override(client: TestClient, monkeypatch):
    """In production mode, /api/docs requires admin role unless overridden by ENABLE_API_DOCS."""
    monkeypatch.delenv("ENABLE_API_DOCS", raising=False)
    monkeypatch.setenv("LOG_MODE", "production")

    # 1. Anonymous user gets 401 in production
    async def _anon():
        return None

    app.dependency_overrides[get_current_user_optional] = _anon
    for endpoint in ("/api/docs", "/api/swagger", "/api/openapi.json", "/docs", "/openapi.json"):
        assert client.get(endpoint).status_code == 401

    # 2. Normal user gets 403
    async def _normal_user():
        return AppUser(id="user_123", email="u@example.com", name="User", role="user", pdf_download_count=0)

    app.dependency_overrides[get_current_user_optional] = _normal_user
    assert client.get("/api/docs").status_code == 403
    assert client.get("/api/openapi.json").status_code == 403

    # 3. Admin user gets 200
    async def _admin_user():
        return AppUser(id="admin_1", email="a@example.com", name="Admin", role="admin", pdf_download_count=0)

    app.dependency_overrides[get_current_user_optional] = _admin_user
    assert client.get("/api/docs").status_code == 200
    assert client.get("/api/swagger").status_code == 200
    assert client.get("/api/openapi.json").status_code == 200

    # 4. ENABLE_API_DOCS=false disables docs completely (404) even for admin
    monkeypatch.setenv("ENABLE_API_DOCS", "false")
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/swagger").status_code == 404

    # 5. ENABLE_API_DOCS=true opens docs even in production
    monkeypatch.setenv("ENABLE_API_DOCS", "true")
    app.dependency_overrides[get_current_user_optional] = _anon
    assert client.get("/api/docs").status_code == 200

    # 6. PM2 NODE_ENV=production without LOG_MODE also enforces admin access
    monkeypatch.delenv("ENABLE_API_DOCS", raising=False)
    monkeypatch.setenv("LOG_MODE", "console")
    monkeypatch.setenv("NODE_ENV", "production")
    assert client.get("/api/docs").status_code == 401
    app.dependency_overrides[get_current_user_optional] = _admin_user
    assert client.get("/api/docs").status_code == 200


def test_scoring_service_accepts_int_and_str_user_id_against_db():
    """ScoringService coerces integer user_id cleanly to string to match VARCHAR Resume.user_id."""
    from backend.database import SessionLocal, init_db
    import models  # noqa: F401

    init_db()
    db = SessionLocal()
    try:
        service = ScoringService(db)
        with pytest.raises(ValueError, match="not found"):
            service.score_resume(resume_id="nonexistent_scoring_check", user_id=1, jd_text="Python Backend")
        with pytest.raises(ValueError, match="not found"):
            service.score_resume(resume_id="nonexistent_scoring_check", user_id="user_abc", jd_text="Python Backend")
    finally:
        db.close()
