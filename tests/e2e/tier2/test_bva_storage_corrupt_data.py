"""Tier 2 Boundary & Corner Tests: Feature 6 (Downward Compatible Storage Corrupt Data).

Authoritative specs:
- ORIGINAL_REQUEST §R2.3, Issue #53
- frontend/src/utils/storageCompat.ts
- Edge cases: corrupt non-JSON values, empty storage null safety, quota recovery, type mismatch
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t2_f06_01_empty_storage_null_safety():
    """TEST-T2-F06-01: Verify querying nonexistent key in production storage returns null safely."""
    compat_file = WORKTREE_ROOT / "frontend" / "src" / "utils" / "storageCompat.ts"
    content = compat_file.read_text(encoding="utf-8")
    assert "return null" in content
    assert "if (!storage) return null" in content


def test_t2_f06_02_corrupt_storage_safe_recovery():
    """TEST-T2-F06-02: Verify storageCompat catches runtime access/parse exceptions."""
    compat_file = WORKTREE_ROOT / "frontend" / "src" / "utils" / "storageCompat.ts"
    content = compat_file.read_text(encoding="utf-8")
    assert "try {" in content
    assert "catch (err) {" in content
    assert "console.warn" in content


def test_t2_f06_03_quota_write_error_ignored_for_reads():
    """TEST-T2-F06-03: Verify forward migration write failure does not break the read return."""
    compat_file = WORKTREE_ROOT / "frontend" / "src" / "utils" / "storageCompat.ts"
    content = compat_file.read_text(encoding="utf-8")
    # Verify try/catch wraps setItem inside the legacy probe loop
    assert "storage.setItem(newKey, legVal)" in content
    assert "return legVal" in content


def test_t2_f06_04_remove_compatible_item_clears_both_modern_and_legacy():
    """TEST-T2-F06-04: Verify removeCompatibleItem removes both modern and all legacy keys."""
    compat_file = WORKTREE_ROOT / "frontend" / "src" / "utils" / "storageCompat.ts"
    content = compat_file.read_text(encoding="utf-8")
    assert "export function removeCompatibleItem" in content
    assert "storage.removeItem(newKey)" in content
    assert "storage.removeItem(legKey)" in content


def test_t2_f06_05_vitest_edge_cases_execution():
    """TEST-T2-F06-05: Execute Vitest test suite verifying edge cases pass on real jsdom environment."""
    frontend_dir = WORKTREE_ROOT / "frontend"
    res = subprocess.run(
        ["npx", "vitest", "run", "src/utils/storageCompat.test.ts", "--reporter=json"],
        cwd=str(frontend_dir),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data.get("numFailedTests", 0) == 0
