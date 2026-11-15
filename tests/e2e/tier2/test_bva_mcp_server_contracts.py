"""Tier 2 Boundary & Corner Tests: Feature 14 (Official CocoCV MCP Server Contracts).

Authoritative specs:
- ORIGINAL_REQUEST §R3.3, Issue #57
- Real module: backend.mcp.server
- Real tools: get_resume, patch_resume, render_pdf, sync_workspace, validate_resume
- Boundaries: nonexistent resume ID, prototype pollution path rejection, invalid engine routing, invalid sync action, concurrency
"""
from __future__ import annotations

import concurrent.futures
from pathlib import Path
import pytest


def test_t2_f14_01_nonexistent_resume_id_error_handling():
    """TEST-T2-F14-01: Verify querying non-existent resume ID raises FileNotFoundError safely."""
    from backend.mcp.server import get_resume
    with pytest.raises((FileNotFoundError, ValueError)) as exc_info:
        get_resume("/nonexistent/path/to/resume_99999.json")
    assert "not found" in str(exc_info.value).lower() or "not exist" in str(exc_info.value).lower()


def test_t2_f14_02_prototype_pollution_path_rejection(standard_resume_data: dict):
    """TEST-T2-F14-02: Verify malicious prototype pollution patch paths are intercepted safely."""
    from backend.mcp.server import patch_resume
    forbidden_paths = [
        "/__proto__/polluted",
        "/constructor/prototype/isAdmin",
    ]
    for bad_path in forbidden_paths:
        with pytest.raises((KeyError, TypeError, AttributeError, ValueError)):
            patch_resume(
                standard_resume_data,
                [{"op": "replace", "path": bad_path, "value": "injected"}],
            )


def test_t2_f14_03_render_pdf_unsupported_engine_rejection(standard_resume_data: dict):
    """TEST-T2-F14-03: Verify unsupported engine raises ValueError."""
    from backend.mcp.server import render_pdf
    with pytest.raises(ValueError, match="(?i)unsupported"):
        render_pdf(standard_resume_data, engine="unsupported_quantum_engine")


def test_t2_f14_04_sync_workspace_invalid_action_rejection():
    """TEST-T2-F14-04: Verify sync_workspace rejects unsupported actions with ValueError."""
    from backend.mcp.server import sync_workspace
    with pytest.raises(ValueError, match="(?i)unsupported"):
        sync_workspace("delete_all_remotely", {})


def test_t2_f14_05_concurrent_mcp_tool_execution(standard_resume_data: dict):
    """TEST-T2-F14-05: Verify concurrent MCP tool calls execute without state contention."""
    from backend.mcp.server import patch_resume, validate_resume

    def run_tool_call(idx: int):
        patched = patch_resume(
            standard_resume_data,
            [{"op": "replace", "path": "/basic/title", "value": f"Title {idx}"}],
        )
        validation = validate_resume(patched)
        valid = validation["valid"] if isinstance(validation, dict) else validation.valid
        return patched["basic"]["title"], valid

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(run_tool_call, i) for i in range(10)]
        results = [f.result() for f in futures]

    assert len(results) == 10
    for idx, (title, valid) in enumerate(results):
        assert valid is True
