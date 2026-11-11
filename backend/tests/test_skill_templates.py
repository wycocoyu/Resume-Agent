"""Guardrails for the universal harness base: shared core -> per-harness artifacts."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from backend.cli.schema import FIELD_CONVENTIONS, ResumeDataModel
from backend.skillkit import (
    compare_tree,
    company_logo_keys,
    load_adapters,
    load_descriptions,
    render_harness,
    render_schema_markdown,
    templates_root,
)
from backend.skillkit.adapters import AdapterError, load_adapter
from backend.skillkit.install import (
    install as install_skill,
    status_entries,
    uninstall as uninstall_skill,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_SKILL = REPO_ROOT / "skills" / "resume-agent"


def _adapters():
    return load_adapters(templates_root())


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match is not None, "generated SKILL.md is missing YAML frontmatter"
    body = match.group(1)
    parsed: dict[str, str] = {}
    for line in body.splitlines():
        if not line or line.startswith(" "):
            continue
        key, _, value = line.partition(":")
        parsed[key.strip()] = value.strip().strip('"')
    return parsed


def test_schema_markdown_is_generated_from_live_contract() -> None:
    rendered = render_schema_markdown(templates_root())

    for field in FIELD_CONVENTIONS["html_rich_text_fields"]:
        assert field in rendered, f"missing HTML rich-text field: {field}"
    assert "awards[*].description" in rendered
    assert "PLAIN TEXT ONLY" in rendered

    for key in company_logo_keys():
        assert f"`{key}`" in rendered, f"missing company logo key: {key}"

    # Counts are generated, so a field added to the contract cannot leave a stale "8" behind.
    assert f"Exactly {len(FIELD_CONVENTIONS['html_rich_text_fields'])} HTML Rich-Text Fields" in rendered
    assert "<!-- gen:" not in rendered


def test_schema_markdown_documents_every_top_level_field() -> None:
    rendered = render_schema_markdown(templates_root())
    for name in ResumeDataModel.model_fields:
        assert f"| `{name}` |" in rendered, f"top-level field not documented: {name}"


def test_every_harness_renders_a_discoverable_skill() -> None:
    adapters = _adapters()
    assert set(adapters) >= {"codex", "claude", "workbuddy", "pi"}
    descriptions = load_descriptions(templates_root())

    for adapter in adapters.values():
        files = render_harness(adapter)
        assert "SKILL.md" in files
        assert "references/schema.md" in files
        skill = files["SKILL.md"]
        assert skill.startswith("---\n")
        assert "{{" not in skill, f"{adapter.id}: unresolved placeholder in generated skill"
        assert "[references/schema.md](references/schema.md)" in skill
        assert adapter.invoke_syntax in skill
        meta = _frontmatter(skill)
        assert meta["name"] == descriptions["name"]
        # The description must satisfy the adapter's own declared limits.
        low = adapter.constraints.get("description_min")
        high = adapter.constraints.get("description_max")
        if low is not None:
            assert len(meta["description"]) >= low
        if high is not None:
            assert len(meta["description"]) <= high


def test_core_body_is_harness_neutral() -> None:
    body = (templates_root() / "core" / "body.md").read_text(encoding="utf-8")
    for harness_name in ("Codex", "Claude", "WorkBuddy"):
        assert harness_name not in body, (
            f"core/body.md leaked harness-specific wording ({harness_name}); "
            "use the {{harness_display}} placeholder instead."
        )
    assert not re.search(r"\bpi\b", body), "core/body.md leaked harness-specific wording (pi)"


def test_codex_skill_matches_adapter_constraints() -> None:
    adapter = _adapters()["codex"]
    files = render_harness(adapter)
    skill = files["SKILL.md"]
    meta = _frontmatter(skill)
    assert 20 <= len(meta["description"]) <= 1024
    short = re.search(r"short-description: \"(.*)\"", skill)
    assert short is not None
    assert 25 <= len(short.group(1)) <= 64
    assert "$resume-agent" in skill
    assert files["agents/openai.yaml"].strip()


def test_committed_skill_tree_is_in_sync_with_templates() -> None:
    """The committed skills/ tree must be exactly the generator output."""
    adapter = _adapters()["codex"]
    diff = compare_tree(render_harness(adapter), COMMITTED_SKILL)
    assert not diff["missing"], f"missing generated files: {diff['missing']}"
    assert not diff["stale"], (
        f"stale generated files: {diff['stale']}. Run `resume-agent skill build "
        "--harness codex --out skills --layout flat` and commit."
    )
    assert not diff["extra"], f"unexpected files under skills/: {diff['extra']}"


def test_no_committed_dot_claude_directory() -> None:
    """Generated artifacts are committed under skills/, never as a dot-directory."""
    assert not (REPO_ROOT / ".claude" / "skills" / "resume-agent").exists()


def test_skillkit_imports_standalone() -> None:
    """`import backend.skillkit` must not depend on the CLI package being imported first."""
    code = "import backend.skillkit as s; print(s.templates_root().name)"
    res = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "skill_templates"


def test_adapter_rejects_unknown_keys(tmp_path: Path) -> None:
    harness_dir = tmp_path / "harnesses" / "broken"
    harness_dir.mkdir(parents=True)
    (harness_dir / "meta.toml").write_text(
        "\n".join(
            [
                "schema_version = 1",
                'id = "broken"',
                '[frontmatter]',
                'name = "resume-agent"',
                "unsupported_key = true",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(AdapterError):
        load_adapter(harness_dir / "meta.toml")


def test_build_check_detects_drift(tmp_path: Path) -> None:
    adapter = _adapters()["codex"]
    files = render_harness(adapter)
    target = tmp_path / "codex" / "resume-agent"
    for rel, text in files.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    assert compare_tree(files, target) == {"missing": [], "stale": [], "extra": []}

    (target / "SKILL.md").write_text("hand edited\n", encoding="utf-8")
    assert compare_tree(files, target)["stale"] == ["SKILL.md"]


def test_install_status_uninstall_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESUME_AGENT_STATE_DIR", str(tmp_path / "state"))
    adapter = _adapters()["claude"]
    target = tmp_path / "claude-skills" / "resume-agent"

    plan = install_skill(
        adapter,
        scope="user",
        target_override=str(target),
        dry_run=True,
    )
    assert plan["dry_run"] is True
    assert not target.exists()

    result = install_skill(adapter, scope="user", target_override=str(target))
    assert result["ok"] is True
    assert (target / "SKILL.md").is_file()

    entries = status_entries()
    assert len(entries) == 1
    assert entries[0]["state"] == "ok"

    # A user edit must be detected and preserved on uninstall.
    edited = target / "SKILL.md"
    original = edited.read_bytes()
    edited.write_bytes(original + b"\nlocal note\n")
    assert status_entries()[0]["state"] == "modified"

    removed = uninstall_skill("claude", target_override=str(target))
    assert str(edited) in removed["kept"]
    assert edited.is_file()

    edited.write_bytes(original)
    uninstall_skill("claude", target_override=str(target))
    assert not edited.exists()
    assert status_entries() == []


def test_install_refuses_foreign_directory_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RESUME_AGENT_STATE_DIR", str(tmp_path / "state"))
    adapter = _adapters()["claude"]
    target = tmp_path / "existing" / "resume-agent"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("mine\n", encoding="utf-8")

    with pytest.raises(Exception):
        install_skill(adapter, scope="user", target_override=str(target))

    install_skill(adapter, scope="user", target_override=str(target), force=True)
    assert "resume-agent" in (target / "SKILL.md").read_text(encoding="utf-8")


def test_manifest_is_plain_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESUME_AGENT_STATE_DIR", str(tmp_path / "state"))
    adapter = _adapters()["codex"]
    install_skill(adapter, scope="user", target_override=str(tmp_path / "skills" / "resume-agent"))
    payload = json.loads((tmp_path / "state" / "state.json").read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["installs"][0]["harness"] == "codex"
    assert payload["installs"][0]["files"], "manifest must record per-file hashes"
