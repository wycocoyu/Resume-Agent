"""Tier 1 Feature Coverage: Feature 1 (PR #64 Universal Harness & Skillkit).

Authoritative specs:
- ORIGINAL_REQUEST §R1.1, PR #64
- backend/skillkit/adapters.py, backend/skillkit/render.py, backend/skillkit/install.py
- Supported harnesses: codex, claude, pi, workbuddy
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest


def test_t1_f01_01_list_all_supported_harnesses(run_cli):
    """TEST-T1-F01-01: Verify 'skill list --json' outputs all 4 supported AI harnesses."""
    proc = run_cli(["skill", "list", "--json"])
    assert proc.returncode == 0, f"skill list failed: {proc.stderr}"
    assert proc.json_data is not None, "Output must be valid JSON"
    assert proc.json_data.get("ok") is True
    assert proc.json_data.get("command") == "skill.list"
    
    harnesses = proc.json_data.get("harnesses", [])
    harness_ids = [h.get("id") for h in harnesses]
    for expected in ["claude", "codex", "pi", "workbuddy"]:
        assert expected in harness_ids, f"Expected harness {expected} in {harness_ids}"
    
    for h in harnesses:
        assert "display_name" in h
        assert "invoke_syntax" in h
        assert "user_paths" in h
        assert "project_paths" in h


def test_t1_f01_02_build_full_skill_trees_nested(run_cli, temp_e2e_dir: Path):
    """TEST-T1-F01-02: Verify 'skill build --harness all' in nested layout generates complete skill trees."""
    out_dir = temp_e2e_dir / "skills_nested"
    proc = run_cli(["skill", "build", "--harness", "all", "--out", str(out_dir), "--layout", "nested", "--json"])
    assert proc.returncode == 0, f"skill build failed: {proc.stderr}"
    assert proc.json_data is not None
    assert proc.json_data.get("ok") is True
    
    generated = proc.json_data.get("harnesses", [])
    assert len(generated) == 4
    
    for h in ["claude", "codex", "pi", "workbuddy"]:
        skill_file = out_dir / h / "resume-agent" / "SKILL.md"
        assert skill_file.exists(), f"Expected skill file at {skill_file}"
        content = skill_file.read_text(encoding="utf-8")
        assert len(content) > 100
        assert "resume-agent" in content


def test_t1_f01_03_repository_skill_tree_sync_check(run_cli):
    """TEST-T1-F01-03: Verify 'skill build --check' audits repository skill tree status."""
    proc = run_cli(["skill", "build", "--harness", "codex", "--check", "--json"])
    assert proc.returncode in (0, 1)  # 0 if in sync, 1 if drift reported with structured data
    assert proc.json_data is not None
    assert "in_sync" in proc.json_data or "ok" in proc.json_data


def test_t1_f01_04_resolve_candidate_discovery_paths(run_cli):
    """TEST-T1-F01-04: Verify 'skill path' resolves valid discovery paths for harness and scope."""
    proc = run_cli(["skill", "path", "--harness", "claude", "--scope", "user", "--json"])
    assert proc.returncode == 0, f"skill path failed: {proc.stderr}"
    assert proc.json_data is not None
    assert proc.json_data.get("harness") == "claude"
    assert proc.json_data.get("scope") == "user"
    assert "target" in proc.json_data
    assert "claude" in proc.json_data["target"].lower()
    assert "resume-agent" in proc.json_data.get("invoke_syntax", "").lower()


def test_t1_f01_05_dry_run_installation(run_cli, temp_e2e_dir: Path):
    """TEST-T1-F01-05: Verify 'skill install --dry-run' reports planned files without writing to disk."""
    install_target = temp_e2e_dir / "dry_run_target"
    proc = run_cli(["skill", "install", "--harness", "pi", "--path", str(install_target), "--dry-run", "--json"])
    assert proc.returncode == 0, f"dry-run install failed: {proc.stderr}"
    assert proc.json_data is not None
    assert proc.json_data.get("dry_run") is True
    assert "files" in proc.json_data
    assert len(proc.json_data["files"]) > 0
    assert not install_target.exists(), "Target directory must not be created during dry-run"


def test_t1_f01_06_install_status_uninstall_roundtrip(run_cli, temp_e2e_dir: Path):
    """TEST-T1-F01-06: Verify full lifecycle: install -> status -> uninstall roundtrip."""
    target_path = temp_e2e_dir / "codex_installed_skill"
    state_dir = temp_e2e_dir / "agent_state"
    custom_env = {"RESUME_AGENT_STATE_DIR": str(state_dir)}
    
    # 1. Install
    inst_proc = run_cli(
        ["skill", "install", "--harness", "codex", "--path", str(target_path), "--strategy", "copy", "--json"],
        env=custom_env,
    )
    assert inst_proc.returncode == 0, f"install failed: {inst_proc.stderr}"
    assert target_path.exists()
    assert (target_path / "SKILL.md").exists()
    assert (target_path / "references" / "schema.md").exists()
    
    # 2. Status
    stat_proc = run_cli(
        ["skill", "status", "--harness", "codex", "--json"],
        env=custom_env,
    )
    assert stat_proc.returncode == 0, f"status failed: {stat_proc.stderr}"
    assert stat_proc.json_data is not None
    assert "installs" in stat_proc.json_data
    
    # 3. Uninstall
    uninst_proc = run_cli(
        ["skill", "uninstall", "--harness", "codex", "--path", str(target_path), "--json"],
        env=custom_env,
    )
    assert uninst_proc.returncode == 0, f"uninstall failed: {uninst_proc.stderr}"
    assert uninst_proc.json_data is not None
    assert not (target_path / "SKILL.md").exists(), "SKILL.md must be removed"
