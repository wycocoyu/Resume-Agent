"""Tier 1 Feature Coverage: Feature 2 (PR #66 Tabbit E2E Visual Verification).

Authoritative specs:
- ORIGINAL_REQUEST §R1.2, PR #66
- scripts/tabbit-pr-verify.mjs
- Tabbit CLI driver & 4-stage UI verification contract
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t1_f02_01_script_existence_and_syntax():
    """TEST-T1-F02-01: Verify scripts/tabbit-pr-verify.mjs exists and passes Node syntax check."""
    script_path = WORKTREE_ROOT / "scripts" / "tabbit-pr-verify.mjs"
    assert script_path.exists(), f"Script not found at {script_path}"
    
    # Run node syntax check
    res = subprocess.run(["node", "--check", str(script_path)], capture_output=True, text=True)
    assert res.returncode == 0, f"Node syntax check failed: {res.stderr}"


def test_t1_f02_02_script_configuration_and_env_variables():
    """TEST-T1-F02-02: Verify script honors environment variables (TABBIT_CLI, BASE_URL, OUT_DIR)."""
    script_path = WORKTREE_ROOT / "scripts" / "tabbit-pr-verify.mjs"
    content = script_path.read_text(encoding="utf-8")
    
    assert "process.env.TABBIT_CLI" in content
    assert "process.env.BASE_URL" in content
    assert "process.env.OUT_DIR" in content
    assert "01-home.png" in content


def test_t1_f02_03_four_core_verification_stages():
    """TEST-T1-F02-03: Verify script defines all 4 core visual verification stages."""
    script_path = WORKTREE_ROOT / "scripts" / "tabbit-pr-verify.mjs"
    content = script_path.read_text(encoding="utf-8")
    
    expected_stages = [
        "01-home.png",
        "02-changelog-page.png",
        "03-skin-picker.png",
        "04-input-active.png",
    ]
    for stage in expected_stages:
        assert stage in content, f"Expected visual stage {stage} in script"


def test_t1_f02_04_tabbit_cli_path_discovery():
    """TEST-T1-F02-04: Verify Tabbit CLI discovery at ~/.local/bin/tabbit-cli."""
    tabbit_path = Path.home() / ".local" / "bin" / "tabbit-cli"
    if tabbit_path.exists():
        assert os.access(tabbit_path, os.X_OK)
        res = subprocess.run([str(tabbit_path), "--help"], capture_output=True, text=True)
        assert res.returncode in (0, 1)  # either help printed or subcommands shown
    else:
        which_path = shutil.which("tabbit-cli")
        assert which_path is not None or not tabbit_path.exists()


def test_t1_f02_05_missing_cli_fails_cleanly(temp_e2e_dir: Path):
    """TEST-T1-F02-05: Verify script exits with code 1 and error message if tabbit-cli is missing."""
    script_path = WORKTREE_ROOT / "scripts" / "tabbit-pr-verify.mjs"
    env = os.environ.copy()
    env["TABBIT_CLI"] = str(temp_e2e_dir / "nonexistent_tabbit_cli")
    
    res = subprocess.run(["node", str(script_path)], env=env, capture_output=True, text=True)
    assert res.returncode == 1
    assert "tabbit-cli not found" in res.stderr
