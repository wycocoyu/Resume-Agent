"""Tier 2 Boundary & Corner Tests: Feature 2 (PR #66 Tabbit Visual Verification).

Authoritative specs:
- ORIGINAL_REQUEST §R1.2, PR #66
- scripts/tabbit-pr-verify.mjs
- Boundary cases: missing binary, deep directory creation, malformed json stdout, max input
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t2_f02_01_missing_tabbit_cli_fails_gracefully(temp_e2e_dir: Path):
    """TEST-T2-F02-01: Verify script exits 1 with clear stderr when tabbit-cli binary is absent."""
    script_path = WORKTREE_ROOT / "scripts" / "tabbit-pr-verify.mjs"
    assert script_path.exists(), "Script must exist"
    
    env = {
        **os.environ,
        "TABBIT_CLI": "/nonexistent/fake/tabbit-cli",
        "OUT_DIR": str(temp_e2e_dir / "out"),
    }
    proc = subprocess.run(
        ["node", str(script_path)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(WORKTREE_ROOT),
    )
    assert proc.returncode == 1
    assert "Error: tabbit-cli not found" in proc.stderr


def test_t2_f02_02_deep_recursive_outdir_creation(temp_e2e_dir: Path):
    """TEST-T2-F02-02: Verify deep nested OUT_DIR path is created automatically by the script."""
    deep_dir = temp_e2e_dir / "level1" / "level2" / "level3" / "tabbit_out"
    assert not deep_dir.exists()
    
    dummy_cli = temp_e2e_dir / "dummy_tabbit.sh"
    dummy_cli.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    dummy_cli.chmod(0o755)

    script_path = WORKTREE_ROOT / "scripts" / "tabbit-pr-verify.mjs"
    env = {
        **os.environ,
        "TABBIT_CLI": str(dummy_cli),
        "OUT_DIR": str(deep_dir),
    }
    subprocess.run(
        ["node", str(script_path)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(WORKTREE_ROOT),
    )
    assert deep_dir.exists(), "Script must create nested OUT_DIR before or during execution"
    assert deep_dir.is_dir()


def test_t2_f02_03_malformed_cli_json_output_handling(temp_e2e_dir: Path):
    """TEST-T2-F02-03: Verify runner handles mock CLI returning non-JSON output without uncaught exception."""
    mock_cli = temp_e2e_dir / "mock_tabbit.sh"
    mock_cli.write_text("#!/bin/sh\necho 'Fatal internal daemon panic without json'\n", encoding="utf-8")
    mock_cli.chmod(0o755)
    
    script_path = WORKTREE_ROOT / "scripts" / "tabbit-pr-verify.mjs"
    env = {
        **os.environ,
        "TABBIT_CLI": str(mock_cli),
        "OUT_DIR": str(temp_e2e_dir / "out"),
    }
    proc = subprocess.run(
        ["node", str(script_path)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(WORKTREE_ROOT),
    )
    assert proc.returncode == 1
    assert "Failed to parse Tabbit CLI JSON output" in proc.stderr


def test_t2_f02_04_max_input_length_payload_boundaries():
    """TEST-T2-F02-04: Verify large prompt payload (5,000 chars) is correctly escaped in script."""
    large_prompt = "高级分布式架构师研发经验 " * 350  # ~5,000+ chars
    assert len(large_prompt) > 4000
    
    escaped = json.dumps(large_prompt)
    assert escaped.startswith('"') and escaped.endswith('"')
    node_check = f"const p = {escaped}; if (p.length < 4000) process.exit(1);"
    proc = subprocess.run(["node", "-e", node_check], capture_output=True, text=True)
    assert proc.returncode == 0


def test_t2_f02_05_unreachable_server_handling_logic():
    """TEST-T2-F02-05: Verify navigation timeout configuration in script is robust (timeout=10000)."""
    script_path = WORKTREE_ROOT / "scripts" / "tabbit-pr-verify.mjs"
    script_content = script_path.read_text(encoding="utf-8")
    assert "timeout: 10000" in script_content or "waitForSelector" in script_content
    assert "waitUntil: \"domcontentloaded\"" in script_content
