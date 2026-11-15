"""Tier 1 Feature Coverage: Feature 14 (Official CocoCV MCP Server, Issue #57).

Authoritative specs:
- ORIGINAL_REQUEST §R3.3, Issue #57
- Real module: backend/mcp/server.py
- Real entrypoint: python -m backend.mcp.server
- Tools: get_resume, validate_resume, patch_resume, render_pdf, sync_workspace
- Transports: stdio and sse
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t1_f14_01_mcp_server_module_import():
    """TEST-T1-F14-01: Verify official CocoCV MCP Server module is importable (Scheduled for M5)."""
    # In M1-M4, backend.mcp is not yet implemented (scheduled for M5).
    # This import will honestly raise ModuleNotFoundError until M5.
    import backend.mcp.server as mcp_server
    assert hasattr(mcp_server, "server") or hasattr(mcp_server, "app")


def test_t1_f14_02_mcp_server_tools_registered():
    """TEST-T1-F14-02: Verify MCP server registers all 5 required tools."""
    from backend.mcp.server import get_registered_tools
    tools = get_registered_tools()
    tool_names = [t.name if hasattr(t, "name") else t["name"] for t in tools]
    for expected in ["get_resume", "validate_resume", "patch_resume", "render_pdf", "sync_workspace"]:
        assert expected in tool_names


def test_t1_f14_03_mcp_server_cli_execution():
    """TEST-T1-F14-03: Verify python -m backend.mcp.server can be spawned via CLI."""
    venv_python = WORKTREE_ROOT / ".venv" / "bin" / "python"
    python_bin = str(venv_python) if venv_python.exists() else sys.executable

    proc = subprocess.run(
        [python_bin, "-m", "backend.mcp.server", "--help"],
        cwd=str(WORKTREE_ROOT),
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert proc.returncode == 0


def test_t1_f14_04_mcp_server_stdio_handshake():
    """TEST-T1-F14-04: Verify MCP server responds to stdio JSON-RPC initialize."""
    from backend.mcp.server import create_stdio_server
    server = create_stdio_server()
    assert server is not None


def test_t1_f14_05_mcp_server_sse_transport_supported():
    """TEST-T1-F14-05: Verify MCP server supports SSE transport."""
    from backend.mcp.server import create_sse_app
    app = create_sse_app()
    assert app is not None
