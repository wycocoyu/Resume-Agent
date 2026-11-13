import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from fastapi.testclient import TestClient

from backend.main import app
import backend.routes.admin as admin_route
from types import SimpleNamespace


def test_remote_pdf_render_requires_admin_role():
    client = TestClient(app)

    response = client.post(
        "/api/admin/pdf/render",
        json={"resume": {"name": "tester"}, "section_order": []},
    )

    assert response.status_code in {401, 403}


def test_remote_pdf_render_proxies_pdf_bytes(monkeypatch):
    async def fake_proxy_remote_pdf(*, path, body, request, current_user=None, **_kwargs):
        assert path == "/api/pdf/render"
        assert body.resume["name"] == "tester"
        assert body.section_order == []
        return admin_route.Response(
            content=b"%PDF-1.4\n%fake\n",
            media_type="application/pdf",
            headers={"X-Render-Time": "0.1"},
        )

    async def fake_require_admin_only():
        # 路由会在日志里读取 email/role，stub 必须提供这两个字段
        return SimpleNamespace(email="admin@example.com", role="admin")

    monkeypatch.setattr(admin_route, "_proxy_remote_pdf", fake_proxy_remote_pdf, raising=False)
    app.dependency_overrides[admin_route.require_admin_only] = fake_require_admin_only
    try:
        client = TestClient(app)
        response = client.post(
            "/api/admin/pdf/render",
            json={"resume": {"name": "tester"}, "section_order": []},
        )
    finally:
        app.dependency_overrides.pop(admin_route.require_admin_only, None)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content == b"%PDF-1.4\n%fake\n"
