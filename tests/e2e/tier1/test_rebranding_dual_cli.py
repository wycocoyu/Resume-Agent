"""Tier 1 Feature Coverage: Feature 5 (Rebranding cococv Dual CLI Aliases, Issue #53).

Authoritative specs:
- ORIGINAL_REQUEST §R2.3, Issue #53
- pyproject.toml ([project.scripts])
- backend/cli/ (init, schema, validate, render, sync, skill)
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t1_f05_01_cli_entrypoints_in_pyproject(run_cli):
    """TEST-T1-F05-01: Verify pyproject.toml specifies dual CLI script entrypoints and both execute."""
    pyproject_path = WORKTREE_ROOT / "pyproject.toml"
    assert pyproject_path.exists()
    content = pyproject_path.read_text(encoding="utf-8")
    
    assert "[project.scripts]" in content
    assert 'cococv = "backend.cli:main"' in content or 'cococv =' in content
    assert 'resume-agent = "backend.cli:main"' in content or 'resume-agent =' in content
    assert "backend.cli" in content

    # Test real binary execution for both aliases if installed in venv
    proc_cococv = run_cli(["--help"], entrypoint="cococv")
    assert proc_cococv.returncode == 0
    assert "cococv" in proc_cococv.stdout.lower() or "resume-agent" in proc_cococv.stdout.lower()

    proc_resume = run_cli(["--help"], entrypoint="resume-agent")
    assert proc_resume.returncode == 0
    assert "resume-agent" in proc_resume.stdout.lower() or "cococv" in proc_resume.stdout.lower()


def test_t1_f05_02_cli_schema_subcommand(run_cli):
    """TEST-T1-F05-02: Verify 'schema --json' outputs authoritative ResumeData schema."""
    proc = run_cli(["schema", "--json"])
    assert proc.returncode == 0, f"schema failed: {proc.stderr}"
    assert proc.json_data is not None
    
    schema = proc.json_data
    assert "title" in schema
    assert "$defs" in schema or "properties" in schema
    assert "x-field-conventions" in schema
    
    field_conventions = schema["x-field-conventions"]
    assert "html_rich_text_fields" in field_conventions
    assert "plain_text_fields" in field_conventions


def test_t1_f05_03_cli_init_subcommand(run_cli, temp_e2e_dir: Path):
    """TEST-T1-F05-03: Verify 'init -o <path> --json' generates a valid skeleton."""
    out_file = temp_e2e_dir / "init_skeleton.json"
    proc = run_cli(["init", "-o", str(out_file), "--json"])
    assert proc.returncode == 0, f"init failed: {proc.stderr}"
    assert proc.json_data is not None
    assert proc.json_data.get("ok") is True
    assert out_file.exists()
    
    with open(out_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "id" in data
    assert "title" in data
    assert "basic" in data


def test_t1_f05_04_cli_validate_subcommand(run_cli, temp_e2e_dir: Path):
    """TEST-T1-F05-04: Verify 'validate <path> --json' strictly validates valid resume JSON."""
    # First generate skeleton
    skeleton_file = temp_e2e_dir / "valid_resume.json"
    run_cli(["init", "-o", str(skeleton_file), "--json"])
    
    # Then validate
    proc = run_cli(["validate", str(skeleton_file), "--json"])
    assert proc.returncode == 0, f"validate failed: {proc.stderr}"
    assert proc.json_data is not None
    assert proc.json_data.get("ok") is True
    assert proc.json_data.get("valid") is True
    assert proc.json_data.get("errors") == []


def test_t1_f05_05_cli_subcommands_help_coverage(run_cli):
    """TEST-T1-F05-05: Verify CLI help exposes all required core subcommands."""
    proc = run_cli(["--help"])
    assert proc.returncode == 0
    stdout = proc.stdout
    for cmd in ["init", "schema", "validate", "render", "sync"]:
        assert cmd in stdout, f"Missing command '{cmd}' in CLI help output"
