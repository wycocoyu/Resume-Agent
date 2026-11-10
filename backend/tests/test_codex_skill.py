"""Tests for Slice S4: Codex-only skill validation (SKILL.md, agents/openai.yaml, references/schema.md)."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

from backend.cli.schema import FIELD_CONVENTIONS

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_DIR = REPO_ROOT / "skills" / "resume-agent"
OFFICIAL_QUICK_VALIDATE = Path(
    "/Users/mac/.codex/skills/.system/skill-creator/scripts/quick_validate.py"
)


def test_codex_only_scope_no_claude_skills_dir() -> None:
    assert SKILL_DIR.is_dir()
    assert not (REPO_ROOT / ".claude" / "skills" / "resume-agent").exists()


def test_skill_md_frontmatter_and_official_quick_validate() -> None:
    skill_md = SKILL_DIR / "SKILL.md"
    assert skill_md.is_file()
    content = skill_md.read_text(encoding="utf-8")

    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    assert match is not None, "SKILL.md missing YAML frontmatter"
    frontmatter = yaml.safe_load(match.group(1))
    assert isinstance(frontmatter, dict)
    assert frontmatter["name"] == "resume-agent"

    desc = frontmatter["description"]
    assert isinstance(desc, str) and 20 <= len(desc) <= 1024
    assert "<" not in desc and ">" not in desc
    assert "[TODO:" not in content
    assert "[references/schema.md](references/schema.md)" in content

    if OFFICIAL_QUICK_VALIDATE.is_file():
        res = subprocess.run(
            [sys.executable, str(OFFICIAL_QUICK_VALIDATE), str(SKILL_DIR)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert res.returncode == 0, f"quick_validate.py failed: {res.stdout}\n{res.stderr}"
        assert "Skill is valid!" in res.stdout


def test_openai_yaml_conforms_to_codex_interface_contract() -> None:
    openai_yaml_path = SKILL_DIR / "agents" / "openai.yaml"
    assert openai_yaml_path.is_file()
    raw_text = openai_yaml_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw_text)
    assert isinstance(parsed, dict)
    assert set(parsed.keys()).issubset({"interface", "dependencies", "policy"})

    interface = parsed.get("interface")
    assert isinstance(interface, dict)
    assert isinstance(interface.get("display_name"), str) and interface["display_name"].strip()

    short_desc = interface.get("short_description")
    assert isinstance(short_desc, str)
    assert 25 <= len(short_desc) <= 64, f"short_description length {len(short_desc)} out of [25, 64]"

    default_prompt = interface.get("default_prompt")
    assert isinstance(default_prompt, str)
    assert "$resume-agent" in default_prompt

    # Verify unquoted keys and double-quoted string values line by line
    for raw_line in raw_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert ":" in stripped
        key_part, val_part = stripped.split(":", 1)
        assert not key_part.strip().startswith(('"', "'")), f"Key must be unquoted: {raw_line}"
        val_stripped = val_part.strip()
        if val_stripped and val_stripped not in {"true", "false"}:
            assert (
                val_stripped.startswith('"') and val_stripped.endswith('"')
            ), f"String value must be double-quoted: {raw_line}"


def test_schema_reference_covers_all_rich_text_and_plain_text_conventions() -> None:
    schema_ref = SKILL_DIR / "references" / "schema.md"
    assert schema_ref.is_file()
    ref_text = schema_ref.read_text(encoding="utf-8")

    for html_field in FIELD_CONVENTIONS["html_rich_text_fields"]:
        assert html_field in ref_text, f"Missing HTML rich-text field in references/schema.md: {html_field}"
    assert "awards[*].description" in ref_text
