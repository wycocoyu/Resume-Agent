"""Tier 2 Boundary & Corner Tests: Feature 5 (Rebranding CLI Bad Arguments & Limits).

Authoritative specs:
- ORIGINAL_REQUEST §R2.3, Issue #53
- backend/cli/ (main.py, render_cmd.py, skill_cmd.py)
- Boundaries: invalid subcommands, missing required options, broken JSON syntax, 0-byte input
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest


def test_t2_f05_01_unknown_cli_subcommand_exits_code_2(run_cli):
    """TEST-T2-F05-01: Verify invoking non-existent subcommand exits with Typer code 2."""
    proc = run_cli(["unknown_nonexistent_subcommand"])
    assert proc.returncode == 2
    assert "No such command" in proc.stderr or "Usage:" in proc.stderr


def test_t2_f05_02_missing_input_file_error_json(run_cli, temp_e2e_dir: Path):
    """TEST-T2-F05-02: Verify missing input file with --json produces structured error."""
    nonexistent = temp_e2e_dir / "does_not_exist.json"
    proc = run_cli(["validate", str(nonexistent), "--json"])
    assert proc.returncode != 0
    if proc.json_data:
        assert proc.json_data.get("ok") is False or "error" in proc.json_data


def test_t2_f05_03_zero_byte_empty_resume_validation(run_cli, temp_e2e_dir: Path):
    """TEST-T2-F05-03: Verify validating 0-byte empty file fails validation with code 2."""
    empty_file = temp_e2e_dir / "empty.json"
    empty_file.write_text("", encoding="utf-8")
    
    proc = run_cli(["validate", str(empty_file), "--json"])
    assert proc.returncode in (1, 2)
    if proc.json_data:
        assert proc.json_data.get("ok") is False


def test_t2_f05_04_broken_json_syntax_validation(run_cli, temp_e2e_dir: Path):
    """TEST-T2-F05-04: Verify validating malformed JSON syntax reports syntax error."""
    broken_file = temp_e2e_dir / "broken_syntax.json"
    broken_file.write_text('{"profile": {"name": "Test", incomplete', encoding="utf-8")
    
    proc = run_cli(["validate", str(broken_file), "--json"])
    assert proc.returncode in (1, 2)
    if proc.json_data:
        assert proc.json_data.get("ok") is False


def test_t2_f05_05_schema_command_option_handling(run_cli):
    """TEST-T2-F05-05: Verify schema command rejects invalid output option flags."""
    proc = run_cli(["schema", "--invalid-unrecognized-flag"])
    assert proc.returncode == 2
    assert "No such option" in proc.stderr or "Error" in proc.stderr
