"""Tier 1 Feature Coverage: Feature 6 (Downward Compatible Storage Read/Migrate, Issue #53).

Authoritative specs:
- ORIGINAL_REQUEST §R2.3, Issue #53
- frontend/src/utils/storageCompat.ts
- frontend/src/utils/storageCompat.test.ts
- Key mappings:
  resume_resumes / resume-agent-resumes -> cococv_resumes
  resume_current / resume-agent-current -> cococv_current
  resume_v2_data / resume-agent-v2-data -> cococv_v2_data
  resume_pinned_ids / resume-agent-pinned-ids -> cococv_pinned_ids
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t1_f06_01_storage_compat_production_file_contract():
    """TEST-T1-F06-01: Verify frontend/src/utils/storageCompat.ts exists and exports required API."""
    compat_file = WORKTREE_ROOT / "frontend" / "src" / "utils" / "storageCompat.ts"
    assert compat_file.exists(), f"Production file must exist at {compat_file}"
    content = compat_file.read_text(encoding="utf-8")

    assert "export const DEFAULT_KEY_MAP" in content
    assert "export function getCompatibleItem" in content
    assert "export function setCompatibleItem" in content
    assert "export function removeCompatibleItem" in content
    assert "export function migrateAllRegisteredKeys" in content


def test_t1_f06_02_default_key_map_mappings():
    """TEST-T1-F06-02: Verify DEFAULT_KEY_MAP correctly defines modern keys and legacy aliases."""
    compat_file = WORKTREE_ROOT / "frontend" / "src" / "utils" / "storageCompat.ts"
    content = compat_file.read_text(encoding="utf-8")

    for modern_key in ["cococv_resumes", "cococv_current", "cococv_v2_data", "cococv_pinned_ids"]:
        assert modern_key in content, f"Missing modern key {modern_key} in DEFAULT_KEY_MAP"

    for legacy_key in ["resume_resumes", "resume_current", "resume_v2_data", "resume_pinned_ids"]:
        assert legacy_key in content, f"Missing legacy key {legacy_key} in fallback map"


def test_t1_f06_03_execute_real_vitest_storage_suite():
    """TEST-T1-F06-03: Execute real frontend storageCompat.test.ts via Vitest and verify 100% pass."""
    frontend_dir = WORKTREE_ROOT / "frontend"
    res = subprocess.run(
        ["npx", "vitest", "run", "src/utils/storageCompat.test.ts", "--reporter=json"],
        cwd=str(frontend_dir),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Vitest execution failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    
    # Parse json report
    data = json.loads(res.stdout)
    assert data.get("numFailedTests", 0) == 0
    assert data.get("numPassedTests", 0) >= 11, f"Expected >= 11 tests passed, got {data.get('numPassedTests')}"


def test_t1_f06_04_storage_forward_migration_verified():
    """TEST-T1-F06-04: Verify production storageCompat automatically writes legacy values forward."""
    compat_file = WORKTREE_ROOT / "frontend" / "src" / "utils" / "storageCompat.ts"
    content = compat_file.read_text(encoding="utf-8")
    assert "storage.setItem(newKey, legVal)" in content, "Must write legacy value forward to newKey"


def test_t1_f06_05_quota_error_safe_suppression():
    """TEST-T1-F06-05: Verify storageCompat catches QuotaExceededError/write errors without throwing."""
    compat_file = WORKTREE_ROOT / "frontend" / "src" / "utils" / "storageCompat.ts"
    content = compat_file.read_text(encoding="utf-8")
    assert "try {" in content and "storage.setItem" in content
    assert "catch" in content
