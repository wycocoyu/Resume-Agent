"""Tests for Slice S1: packaging entrypoint, init/schema/validate single-source model, and --json contract."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.cli import run_cli
from backend.cli.schema import (
    FIELD_CONVENTIONS,
    ResumeDataModel,
    build_initial_resume,
    get_resume_json_schema,
    validate_resume_data,
)


REQUIRED_TOP_LEVEL_KEYS = [
    "id",
    "title",
    "createdAt",
    "updatedAt",
    "templateId",
    "basic",
    "education",
    "experience",
    "projects",
    "openSource",
    "awards",
    "customData",
    "selfEvaluation",
    "skillContent",
    "activeSection",
    "draggingProjectId",
    "menuSections",
    "globalSettings",
]


def _invoke_json(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict, str]:
    code = run_cli(argv)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert isinstance(parsed, dict)
    return code, parsed, captured.err


def test_init_skeleton_matches_workspace_constants_and_validates(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out_file = tmp_path / "my_resume.json"
    code, payload, _ = _invoke_json(
        ["init", "-o", str(out_file), "--title", "秋招后端简历", "--json"],
        capsys,
    )
    assert code == 0
    assert payload["ok"] is True
    assert payload["command"] == "init"
    assert payload["title"] == "秋招后端简历"

    raw = json.loads(out_file.read_text(encoding="utf-8"))
    for key in REQUIRED_TOP_LEVEL_KEYS:
        assert key in raw, f"Missing required top-level key: {key}"

    assert raw["workExperience"] == []
    assert raw["templateType"] == "latex"
    assert raw["templateId"] is None
    assert raw["draggingProjectId"] is None
    assert raw["basic"] == {
        "name": "",
        "title": "",
        "email": "",
        "phone": "",
        "location": "",
    }
    assert [s["id"] for s in raw["menuSections"]] == [
        "basic",
        "education",
        "workExperience",
        "experience",
        "projects",
        "openSource",
        "skills",
        "awards",
        "selfEvaluation",
        "custom_research",
    ]
    assert raw["globalSettings"]["latexFontSize"] == 11
    assert raw["globalSettings"]["latexMargin"] == "standard"
    assert raw["globalSettings"]["latexLineSpacing"] == 1.15

    model, issues = validate_resume_data(raw)
    assert issues == []
    assert model is not None


def test_init_refuses_overwrite_without_force(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out_file = tmp_path / "resume.json"
    out_file.write_text('{"sentinel": 1}\n', encoding="utf-8")
    before_sha = hashlib.sha256(out_file.read_bytes()).hexdigest()

    code, payload, _ = _invoke_json(["init", "-o", str(out_file), "--json"], capsys)
    assert code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "file_exists"
    assert hashlib.sha256(out_file.read_bytes()).hexdigest() == before_sha

    code_force, payload_force, _ = _invoke_json(
        ["init", "-o", str(out_file), "--force", "--json"],
        capsys,
    )
    assert code_force == 0
    assert payload_force["ok"] is True


def test_schema_shares_single_source_and_declares_field_conventions(capsys: pytest.CaptureFixture[str]) -> None:
    code, schema_payload, _ = _invoke_json(["schema", "--json"], capsys)
    assert code == 0
    assert schema_payload["properties"].keys() == ResumeDataModel.model_json_schema()["properties"].keys()
    assert set(REQUIRED_TOP_LEVEL_KEYS).issubset(set(schema_payload["required"]))

    conventions = schema_payload["x-field-conventions"]
    assert len(conventions["html_rich_text_fields"]) == 8
    assert set(conventions["html_rich_text_fields"]) == set(FIELD_CONVENTIONS["html_rich_text_fields"])
    assert "awards[*].description" in conventions["plain_text_fields"]
    assert "awards[*].description" not in conventions["html_rich_text_fields"]


def test_validate_strictly_read_only_sha256_preserved(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    valid_file = tmp_path / "valid.json"
    skeleton = build_initial_resume()
    # Deliberately format with compact spacing and trailing spaces to prove zero byte mutation
    valid_raw_bytes = (json.dumps(skeleton, ensure_ascii=False, separators=(",", ":")) + "   \n").encode("utf-8")
    valid_file.write_bytes(valid_raw_bytes)
    valid_sha_before = hashlib.sha256(valid_file.read_bytes()).hexdigest()

    code, payload, _ = _invoke_json(["validate", str(valid_file), "--json"], capsys)
    assert code == 0
    assert payload["ok"] is True
    assert payload["valid"] is True
    assert hashlib.sha256(valid_file.read_bytes()).hexdigest() == valid_sha_before

    invalid_file = tmp_path / "invalid.json"
    broken = build_initial_resume()
    broken["menuSections"][0]["enabled"] = "yes"  # invalid bool
    invalid_raw_bytes = json.dumps(broken, ensure_ascii=False, indent=4).encode("utf-8")
    invalid_file.write_bytes(invalid_raw_bytes)
    invalid_sha_before = hashlib.sha256(invalid_file.read_bytes()).hexdigest()

    code_bad, payload_bad, _ = _invoke_json(["validate", str(invalid_file), "--json"], capsys)
    assert code_bad == 1
    assert payload_bad["ok"] is False
    assert payload_bad["valid"] is False
    assert any(err["path"] == "menuSections[0].enabled" for err in payload_bad["errors"])
    assert hashlib.sha256(invalid_file.read_bytes()).hexdigest() == invalid_sha_before


@pytest.mark.parametrize("missing_key", REQUIRED_TOP_LEVEL_KEYS)
def test_validate_requires_every_required_top_level_key(missing_key: str) -> None:
    data = build_initial_resume()
    data.pop(missing_key)
    model, issues = validate_resume_data(data)
    assert model is None
    assert any(issue.path == missing_key for issue in issues)


def test_validate_legacy_optional_fields_and_arbitrary_non_empty_ids() -> None:
    # Legacy resume: no workExperience, no alias, no templateType, custom IDs + UUID
    legacy = build_initial_resume()
    legacy.pop("workExperience", None)
    legacy.pop("templateType", None)
    legacy["id"] = "3f7d8b5a-1a2b-4c3d-9e8f-1234567890ab"
    legacy["education"] = [
        {
            "id": "edu_custom_1",
            "school": "清华大学",
            "major": "软件工程",
            "degree": "硕士",
            "startDate": "2021.09",
            "endDate": "2024.06",
        }
    ]
    model, issues = validate_resume_data(legacy)
    assert issues == []
    assert model is not None

    # Explicit nulls on optional top-level keys are valid
    with_nulls = dict(legacy)
    with_nulls["workExperience"] = None
    with_nulls["alias"] = None
    with_nulls["templateType"] = None
    model2, issues2 = validate_resume_data(with_nulls)
    assert issues2 == []
    assert model2 is not None

    # Wrong types on optional fields must fail with exact paths
    bad_work = dict(legacy)
    bad_work["workExperience"] = "not-a-list"
    _, work_issues = validate_resume_data(bad_work)
    assert any(i.path == "workExperience" for i in work_issues)

    bad_edu = build_initial_resume()
    bad_edu["education"] = [
        {
            "id": "edu_1",
            "school": 12345,
            "major": "CS",
            "degree": "BS",
            "startDate": "2020",
            "endDate": "2024",
        }
    ]
    _, edu_issues = validate_resume_data(bad_edu)
    assert any(i.path == "education[0].school" for i in edu_issues)

    bad_empty_id = build_initial_resume()
    bad_empty_id["id"] = "   "
    _, id_issues = validate_resume_data(bad_empty_id)
    assert any(i.path == "id" for i in id_issues)


@pytest.mark.parametrize(
    "bad_argv",
    [
        ["--unknown-flag", "--json"],
        ["validate", "--unknown-flag", "--json"],
        ["validate", "--json"],
        ["--json"],
    ],
)
def test_json_contract_on_usage_errors_exits_2_with_single_json_object(
    bad_argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, payload, _ = _invoke_json(bad_argv, capsys)
    assert code == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "usage_error"


def test_external_cwd_subprocess_smoke(tmp_path: Path) -> None:
    external_dir = tmp_path / "outside_repo"
    external_dir.mkdir()
    target_json = external_dir / "smoke.json"

    bin_dir = Path(sys.executable).parent
    cli_bin = bin_dir / "resume-agent"
    cmd_prefix = [str(cli_bin)] if cli_bin.exists() else [sys.executable, "-m", "backend.cli"]

    res_init = subprocess.run(
        [*cmd_prefix, "init", "-o", str(target_json), "--json"],
        cwd=str(external_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_init.returncode == 0, res_init.stderr
    init_obj = json.loads(res_init.stdout)
    assert init_obj["ok"] is True

    res_val = subprocess.run(
        [*cmd_prefix, "validate", str(target_json), "--json"],
        cwd=str(external_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_val.returncode == 0, res_val.stderr
    val_obj = json.loads(res_val.stdout)
    assert val_obj["valid"] is True

    res_bad = subprocess.run(
        [*cmd_prefix, "validate", "--bogus-option", "--json"],
        cwd=str(external_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    assert res_bad.returncode == 2
    bad_obj = json.loads(res_bad.stdout)
    assert bad_obj["ok"] is False
    assert bad_obj["error"]["code"] == "usage_error"
