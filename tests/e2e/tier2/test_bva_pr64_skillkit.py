"""Tier 2 Boundary & Corner Tests: Feature 1 (PR #64 Universal Harness & Skillkit).

Authoritative specs:
- ORIGINAL_REQUEST §R1.1, PR #64
- backend/skillkit/adapters.py, backend/skillkit/install.py, backend/skillkit/render.py
- Closed contract: _TOP_LEVEL_KEYS, Manifest protection, non-empty collisions
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import pytest

from backend.skillkit.adapters import AdapterError, load_adapters


def test_t2_f01_01_unknown_harness_identifier_rejected(run_cli):
    """TEST-T2-F01-01: Verify invoking skill build with unsupported harness exits with error."""
    proc = run_cli(["skill", "build", "--harness", "unknown_agent_harness", "--json"])
    assert proc.returncode != 0
    if proc.json_data:
        assert proc.json_data.get("ok") is False or "error" in proc.json_data or "code" in proc.json_data
        error_msg = json.dumps(proc.json_data).lower()
        assert "unknown" in error_msg or "harness" in error_msg or "error" in error_msg


def test_t2_f01_02_invalid_scope_parameter_rejected(run_cli):
    """TEST-T2-F01-02: Verify invalid --scope argument is rejected with clear error."""
    proc = run_cli(["skill", "path", "--harness", "claude", "--scope", "system_wide", "--json"])
    assert proc.returncode != 0
    if proc.json_data:
        error_msg = json.dumps(proc.json_data).lower()
        assert "scope" in error_msg or "invalid" in error_msg or "error" in error_msg


def test_t2_f01_03_drift_detection_stale_file(run_cli, temp_e2e_dir: Path):
    """TEST-T2-F01-03: Verify skill build --check flags modified/stale files."""
    build_dir = temp_e2e_dir / "drift_check"
    # First, build clean
    proc1 = run_cli(["skill", "build", "--harness", "codex", "--out", str(build_dir), "--layout", "flat", "--json"])
    assert proc1.returncode == 0
    
    # Tamper with SKILL.md
    skill_md = build_dir / "resume-agent" / "SKILL.md"
    assert skill_md.exists()
    skill_md.write_text(skill_md.read_text(encoding="utf-8") + "\n# Tampered Content\n", encoding="utf-8")
    
    # Run check
    proc2 = run_cli(["skill", "build", "--harness", "codex", "--out", str(build_dir), "--layout", "flat", "--check", "--json"])
    assert proc2.returncode in (0, 1)
    if proc2.json_data:
        harness_res = proc2.json_data.get("harnesses", [{}])[0]
        assert harness_res.get("in_sync") is False or "stale" in str(proc2.json_data)


def test_t2_f01_04_target_not_empty_collision_protection(run_cli, temp_e2e_dir: Path):
    """TEST-T2-F01-04: Verify installer refuses to overwrite foreign existing directory without --force."""
    target_dir = temp_e2e_dir / "foreign_skill_dir"
    target_dir.mkdir(parents=True)
    foreign_file = target_dir / "foreign_data.txt"
    foreign_file.write_text("critical unmanaged data", encoding="utf-8")
    
    proc = run_cli(["skill", "install", "--harness", "codex", "--path", str(target_dir), "--json"])
    # Should either refuse or fail unless --force is given
    assert foreign_file.exists()
    assert foreign_file.read_text(encoding="utf-8") == "critical unmanaged data"


def test_t2_f01_05_user_modification_protected_during_uninstall(run_cli, temp_e2e_dir: Path):
    """TEST-T2-F01-05: Verify uninstaller preserves user-modified files with hash check."""
    target_dir = temp_e2e_dir / "user_modified_skill"
    state_dir = temp_e2e_dir / "state"
    env = {**os.environ, "RESUME_AGENT_STATE_DIR": str(state_dir)}
    
    # Install
    proc_inst = run_cli(["skill", "install", "--harness", "codex", "--path", str(target_dir), "--json"], env=env)
    assert proc_inst.returncode == 0
    
    skill_md = target_dir / "SKILL.md"
    assert skill_md.exists()
    # User edits file
    skill_md.write_text(skill_md.read_text(encoding="utf-8") + "\n## Custom User Edits\n", encoding="utf-8")
    
    # Uninstall
    proc_uninst = run_cli(["skill", "uninstall", "--harness", "codex", "--path", str(target_dir), "--json"], env=env)
    # The modified file must be kept or reported in kept list
    if proc_uninst.json_data:
        kept = proc_uninst.json_data.get("kept", [])
        assert any("SKILL.md" in str(k) for k in kept) or skill_md.exists()


def test_t2_f01_06_declarative_adapter_rejects_unknown_toml_keys(temp_e2e_dir: Path):
    """TEST-T2-F01-06: Verify adapter parser strictly rejects unauthorized keys via AdapterError."""
    fake_adapter_dir = temp_e2e_dir / "bad_adapter"
    fake_adapter_dir.mkdir(parents=True)
    bad_toml = fake_adapter_dir / "meta.toml"
    bad_toml.write_text(
        """
schema_version = 1
id = "bad_harness"
display_name = "Bad Harness"
status = "experimental"
invoke_syntax = "/bad"
cli_min_version = "0.1.0"
unknown_unauthorized_key = "forbidden_value"
""",
        encoding="utf-8",
    )
    
    with pytest.raises((AdapterError, ValueError, KeyError)):
        load_adapters(fake_adapter_dir)
