"""Unit and integration tests for official CocoCV MCP Server.

Feature 19 / Issue #57.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from backend.mcp.server import (
    create_sse_app,
    create_stdio_server,
    get_registered_tools,
    get_resume,
    patch_resume,
    render_pdf,
    server,
    sync_workspace,
    validate_resume,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "e2e" / "fixtures"


def test_mcp_server_instance_and_tools():
    """Verify FastMCP instance and tool registrations."""
    assert server is not None
    tools = get_registered_tools()
    tool_names = [t.name if hasattr(t, "name") else t["name"] for t in tools]
    for expected in ["get_resume", "validate_resume", "patch_resume", "render_pdf", "sync_workspace"]:
        assert expected in tool_names


def test_get_resume_file_and_not_found():
    """Verify get_resume reads files and raises FileNotFoundError on missing files."""
    fixture_file = FIXTURES_DIR / "standard_resume.json"
    data = get_resume(str(fixture_file))
    assert data["id"] == "e2e_resume_standard_001"
    assert "basic" in data

    with pytest.raises(FileNotFoundError):
        get_resume("/nonexistent/path/to/missing_resume.json")


def test_validate_resume_structure():
    """Verify validate_resume scoring and ATS checks."""
    valid_data = {
        "basic": {"name": "张三", "title": "架构师", "email": "zhangsan@example.com"},
        "experience": [{"company": "Tech Corp", "title": "Engineer"}],
        "projects": [{"name": "Platform"}],
        "education": [{"school": "University"}],
        "skills": ["Python", "FastAPI"],
    }
    res = validate_resume(valid_data)
    assert res["valid"] is True
    assert res["score"] >= 80

    invalid_data = {"basic": {}}
    res_invalid = validate_resume(invalid_data)
    assert res_invalid["valid"] is False
    assert any("name" in err.lower() for err in res_invalid["errors"])


def test_patch_resume_and_prototype_pollution_guard():
    """Verify patch_resume applies RFC 6902 and blocks prototype pollution."""
    doc = {"basic": {"title": "Junior Developer"}}
    patched = patch_resume(doc, [{"op": "replace", "path": "/basic/title", "value": "Senior Architect"}])
    assert patched["basic"]["title"] == "Senior Architect"

    # Prototype pollution checks
    for bad_path in ["/__proto__/polluted", "/constructor/prototype/isAdmin", "/a/__proto__/b"]:
        with pytest.raises(ValueError, match="(?i)prototype pollution"):
            patch_resume(doc, [{"op": "replace", "path": bad_path, "value": "injected"}])


def test_render_pdf_engines():
    """Verify render_pdf validates engine and renders latex."""
    fixture_file = FIXTURES_DIR / "standard_resume.json"
    data = json.loads(fixture_file.read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match="(?i)unsupported"):
        render_pdf(data, engine="nonexistent_engine")

    pdf_bytes = render_pdf(data, engine="latex")
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 5000


def test_sync_workspace_actions():
    """Verify sync_workspace push, pull, status, and invalid action rejection."""
    with pytest.raises(ValueError, match="(?i)unsupported"):
        sync_workspace("invalid_action_xyz", {})

    push_res = sync_workspace("push", {"resumes": [{"id": "res_test_1", "basic": {"name": "Test"}}]})
    assert push_res["status"] == "success"
    assert push_res["synced_count"] >= 1

    pull_res = sync_workspace("pull", {})
    assert pull_res["status"] == "success"
    assert any(r.get("id") == "res_test_1" for r in pull_res["resumes"])

    status_res = sync_workspace("status", {})
    assert status_res["status"] == "success"
    assert status_res["workspace_active"] is True


def test_transports_factory():
    """Verify create_stdio_server and create_sse_app return valid objects."""
    stdio_server = create_stdio_server()
    assert stdio_server is not None

    sse_app = create_sse_app()
    assert sse_app is not None
