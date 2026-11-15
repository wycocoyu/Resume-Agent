"""Tier 4 Real-World Application Scenarios: Scenario 2.

Scenario 2: Rebranding & Legacy Storage Migration (品牌重构向下兼容与老版本数据无缝迁移)
Authoritative specs:
- SCOPE.md § Tier 4 Scenarios, TEST_INFRA.md
- Pipeline:
  1. Verify real storageCompat module passes all 11 Vitest cases
  2. Verify dual CLI aliases (cococv & resume-agent) execute init, validate, schema
  3. Validate schema contracts without data loss
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_scenario2_rebranding_and_legacy_storage_migration(fixtures_dir: Path, temp_e2e_dir: Path, run_cli):
    """Scenario 2: End-to-end legacy storage migration and dual CLI validation."""
    # 1. Execute real storageCompat Vitest suite
    vitest_storage = [
        "npx", "vitest", "run",
        "src/utils/storageCompat.test.ts",
    ]
    res_storage = subprocess.run(
        vitest_storage,
        cwd=str(WORKTREE_ROOT / "frontend"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res_storage.returncode == 0, f"storageCompat Vitest failed:\n{res_storage.stdout}\n{res_storage.stderr}"

    # 2. Dual CLI verification: init with cococv
    new_resume_path = temp_e2e_dir / "init_test_resume.json"
    proc_init = run_cli(["init", "-o", str(new_resume_path), "--json"], entrypoint="cococv")
    assert proc_init.returncode == 0
    assert new_resume_path.exists()

    # 3. Dual CLI verification: validate with resume-agent
    proc_val = run_cli(["validate", str(new_resume_path), "--json"], entrypoint="resume-agent")
    assert proc_val.returncode == 0
    assert proc_val.json_data.get("ok") is True

    # 4. CLI schema verification
    proc_schema = run_cli(["schema", "--json"])
    assert proc_schema.returncode == 0
    assert "$defs" in proc_schema.stdout or "properties" in proc_schema.stdout
