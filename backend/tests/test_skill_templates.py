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
    resolve_target,
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


def test_pi_adapter_matches_pi_dev_docs() -> None:
    """pi.dev/docs/latest/skills: skills are invoked as /skill:<name>; user skills
    live under the agent directory (~/.pi/agent/skills) and pi also discovers
    the Agent Skills location ~/.agents/skills (project: .agents/skills)."""
    adapter = _adapters()["pi"]
    assert adapter.invoke_syntax == "/skill:resume-agent"
    assert adapter.user_paths == ("~/.pi/agent/skills", "~/.agents/skills")
    assert adapter.project_paths == (".pi/skills", ".agents/skills")
    meta = _frontmatter(render_harness(adapter)["SKILL.md"])
    assert meta["name"] == "resume-agent"
    assert len(meta["description"]) <= 1024


def test_workbuddy_adapter_uses_codebuddy_discovery_paths() -> None:
    """WorkBuddy (CodeBuddy family): user-level skills in ~/.codebuddy/skills,
    project-level in .codebuddy/skills - each a directory with a SKILL.md."""
    adapter = _adapters()["workbuddy"]
    assert adapter.user_paths == ("~/.codebuddy/skills",)
    assert adapter.project_paths == (".codebuddy/skills",)
    # With a confirmed discovery path, install must no longer require --path.
    target = resolve_target(adapter, scope="user", override=None)
    assert target == Path("~/.codebuddy/skills").expanduser() / "resume-agent"


def test_claude_frontmatter_declares_allowed_tools() -> None:
    """Claude Code skills are description-driven (no slash command), so the
    generated skill must not advertise one and must declare allowed-tools."""
    adapter = _adapters()["claude"]
    skill = render_harness(adapter)["SKILL.md"]
    assert "allowed-tools:" in skill
    assert "Bash(resume-agent:*)" in skill
    assert "/resume-agent" not in skill


def test_generated_frontmatter_is_agent_skills_compliant() -> None:
    """Every harness ships the portable Agent Skills shape: lowercase hyphenated
    name (<= 64 chars) and a routing description (<= 1024 chars)."""
    for adapter in _adapters().values():
        meta = _frontmatter(render_harness(adapter)["SKILL.md"])
        name = meta["name"]
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name), f"{adapter.id}: invalid name {name}"
        assert len(name) <= 64
        assert len(meta["description"]) <= 1024


def test_every_harness_skill_documents_pdf_pipeline() -> None:
    """The shared body must carry the full PDF chain for every harness:
    skeleton init, validate before render, then a local XeLaTeX render."""
    for adapter in _adapters().values():
        skill = render_harness(adapter)["SKILL.md"]
        assert "resume-agent init" in skill, f"{adapter.id}: init step missing"
        assert "resume-agent validate" in skill, f"{adapter.id}: validate step missing"
        assert "resume-agent render" in skill, f"{adapter.id}: render step missing"
        assert "-o resume.pdf" in skill, f"{adapter.id}: PDF output missing"
        assert "references/schema.md" in skill, f"{adapter.id}: schema reference missing"


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


def test_claude_allowed_tools_contains_dual_aliases() -> None:
    adapter = _adapters()["claude"]
    skill = render_harness(adapter)["SKILL.md"]
    assert "Bash(cococv:*)" in skill
    assert "Bash(resume-agent:*)" in skill


def test_skill_body_contains_template_matrix_and_gap_guardrails() -> None:
    body = (templates_root() / "core" / "body.md").read_text(encoding="utf-8")
    assert "【待补】" in body
    assert "Page balance and density self-check" in body
    assert "asu-tech" in body
    assert "asu-01" in body
    assert "cococv render" in body
    assert "Headless Chrome CDP" in body
    assert "capabilities.local_latex_pdf" in body
    assert "handoff" in body
    assert "上云" in body
    assert "cococv.cn" in body
    assert "https://cococv.cn/templates" in body
    assert "https://cococv.cn/create-new" in body
    assert "网页模板中心" in body
    assert "27 套" in body
    assert "经典 LaTeX" in body
    assert "HTML 版本" in body
    assert "复制口令" in body
    assert "没有现成简历" in body
    assert "OCR" in body
    assert "极客" not in body


def test_install_and_uninstall_harness_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESUME_AGENT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True)

    from backend.cli import app
    from typer.testing import CliRunner

    runner = CliRunner()

    # 1. Test install --harness all --dry-run
    res_dry = runner.invoke(app, ["skill", "install", "--harness", "all", "--dry-run", "--json"])
    assert res_dry.exit_code == 0
    dry_data = json.loads(res_dry.stdout)
    assert dry_data["ok"] is True
    assert dry_data["harness"] == "all"
    assert len(dry_data["installs"]) == 4
    harness_ids = {item["harness"] for item in dry_data["installs"]}
    assert harness_ids == {"claude", "codex", "pi", "workbuddy"}

    # 2. Test install --harness all disallows --path
    res_bad = runner.invoke(app, ["skill", "install", "--harness", "all", "--path", str(tmp_path / "foo")])
    assert res_bad.exit_code != 0

    # 3. Test install --harness all real execution
    res_install = runner.invoke(app, ["skill", "install", "--harness", "all", "--json"])
    assert res_install.exit_code == 0
    inst_data = json.loads(res_install.stdout)
    assert inst_data["ok"] is True
    assert len(inst_data["installs"]) == 4

    # Verify manifest has 4 installs
    manifest = json.loads((tmp_path / "state" / "state.json").read_text(encoding="utf-8"))
    assert len(manifest["installs"]) == 4

    # 4. Test path --harness all
    res_path = runner.invoke(app, ["skill", "path", "--harness", "all", "--json"])
    assert res_path.exit_code == 0
    path_data = json.loads(res_path.stdout)
    assert path_data["ok"] is True
    assert len(path_data["items"]) == 4

    # 5. Test uninstall --harness all
    res_uninstall = runner.invoke(app, ["skill", "uninstall", "--harness", "all", "--json"])
    assert res_uninstall.exit_code == 0
    uninst_data = json.loads(res_uninstall.stdout)
    assert uninst_data["ok"] is True
    assert len(uninst_data["removed"]) > 0

    # Verify manifest now has 0 installs
    manifest_after = json.loads((tmp_path / "state" / "state.json").read_text(encoding="utf-8"))
    assert len(manifest_after["installs"]) == 0


def test_state_dir_priority_and_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.skillkit.install import state_dir

    fake_home = tmp_path / "userhome"
    fake_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.delenv("RESUME_AGENT_STATE_DIR", raising=False)
    monkeypatch.delenv("COCOCV_STATE_DIR", raising=False)

    # When neither exists, defaults to ~/.cococv
    assert state_dir() == fake_home / ".cococv"

    # When legacy ~/.resume-agent exists, falls back to legacy
    legacy_dir = fake_home / ".resume-agent"
    legacy_dir.mkdir()
    assert state_dir() == legacy_dir

    # When ~/.cococv exists, ~/.cococv takes priority over legacy
    cococv_dir = fake_home / ".cococv"
    cococv_dir.mkdir()
    assert state_dir() == cococv_dir

    # Environment variable override takes highest priority
    custom_override = tmp_path / "custom_state"
    monkeypatch.setenv("COCOCV_STATE_DIR", str(custom_override))
    assert state_dir() == custom_override


def test_bundled_html_generator_matches_backend_source() -> None:
    expected = (REPO_ROOT / "backend" / "html_generator.py").read_text(encoding="utf-8").replace("\r\n", "\n")
    committed_copy = COMMITTED_SKILL / "scripts" / "html_generator.py"
    assert committed_copy.is_file()
    assert committed_copy.read_text(encoding="utf-8") == expected
    for harness in ("claude", "codex", "pi", "workbuddy"):
        bundled = REPO_ROOT / "dist" / "skills" / harness / "resume-agent" / "scripts" / "html_generator.py"
        assert bundled.is_file()
        assert bundled.read_text(encoding="utf-8") == expected


def test_bundled_cococv_local_runs_zero_dependency_stdlib_only(tmp_path: Path) -> None:
    """Copy scripts/ out of the repo and run under `python -S` with empty PYTHONPATH."""
    import shutil

    scripts_dst = tmp_path / "standalone_skill" / "scripts"
    shutil.copytree(COMMITTED_SKILL / "scripts", scripts_dst)
    local_script = scripts_dst / "cococv_local.py"
    work_dir = tmp_path / "user_work"
    work_dir.mkdir()

    clean_env = {"PATH": "", "HOME": str(tmp_path)}

    def _run_isolated(args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-S", str(local_script), *args],
            cwd=str(work_dir),
            env=clean_env,
            capture_output=True,
            text=True,
            check=False,
        )

    # 1. env probe
    res_env = _run_isolated(["env", "--json"])
    assert res_env.returncode == 0, res_env.stderr
    env_payload = json.loads(res_env.stdout)
    assert env_payload["ok"] is True
    assert env_payload["capabilities"]["local_html"] is True
    assert env_payload["capabilities"]["local_latex_pdf"] is False
    assert env_payload["recommended_engine"] == "html"
    assert env_payload["recommended_latex_route"] == "remote_handoff"

    # 2. init skeleton
    resume_path = work_dir / "resume.json"
    res_init = _run_isolated(["init", "-o", str(resume_path), "--title", "裸机测试", "--json"])
    assert res_init.returncode == 0, res_init.stderr
    assert resume_path.is_file()

    # Populate candidate name
    data = json.loads(resume_path.read_text(encoding="utf-8"))
    data["basic"]["name"] = "无环境测试者"
    resume_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 3. validate passes
    res_val = _run_isolated(["validate", str(resume_path), "--json"])
    assert res_val.returncode == 0, res_val.stderr
    assert json.loads(res_val.stdout)["valid"] is True

    # 4. render self-contained HTML succeeds with PATH="" and -S
    out_html = work_dir / "resume.html"
    res_html = _run_isolated(["render", str(resume_path), "-o", str(out_html), "--template", "asu-tech", "--json"])
    assert res_html.returncode == 0, res_html.stderr
    html_payload = json.loads(res_html.stdout)
    assert html_payload["ok"] is True
    assert html_payload["engine"] == "html"
    assert "无环境测试者" in out_html.read_text(encoding="utf-8")

    # 5. validate rejects HTML inside awards[*].description
    bad_path = work_dir / "bad_awards.json"
    data["awards"] = [{"title": "奖", "date": "2025", "description": "<p>一等奖</p>"}]
    bad_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    res_bad = _run_isolated(["validate", str(bad_path), "--json"])
    assert res_bad.returncode == 1
    bad_payload = json.loads(res_bad.stdout)
    assert bad_payload["valid"] is False
    assert any(err["path"] == "awards[0].description" for err in bad_payload["errors"])

    # 6. LaTeX without xelatex fails loudly with structured fallback_hint
    res_tex = _run_isolated(["render", str(resume_path), "-o", str(work_dir / "out.pdf"), "--engine", "latex", "--json"])
    assert res_tex.returncode == 1
    tex_payload = json.loads(res_tex.stdout)
    assert tex_payload["error"]["code"] == "xelatex_not_found"
    assert "handoff" in tex_payload.get("fallback_hint", "")
    assert "--template asu-tech" in tex_payload.get("fallback_hint", "")


def test_cococv_local_falls_back_when_global_cli_lacks_png_flags(tmp_path: Path) -> None:
    """If an outdated `cococv` on PATH returns usage_error/invalid_argument for --png, fall back cleanly."""
    import shutil

    scripts_dst = tmp_path / "skill" / "scripts"
    shutil.copytree(COMMITTED_SKILL / "scripts", scripts_dst)
    local_script = scripts_dst / "cococv_local.py"

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_cli = fake_bin / "cococv"
    fake_cli.write_text(
        "#!/bin/sh\n"
        'echo \'{"ok": false, "error": {"code": "usage_error", "message": "No such option: --png"}}\'\n'
        "exit 2\n",
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    resume_path = work_dir / "resume.json"
    subprocess.run(
        [sys.executable, str(local_script), "init", "-o", str(resume_path), "--title", "降级测试"],
        check=True,
        capture_output=True,
    )

    # Run render -o out.html (no --png) and render -o out.html --png via mocked outdated PATH CLI
    # Wait: test render -o out.html --png with a fake Chrome path? Instead verify _delegate_render_if_available directly
    probe_code = (
        f"import argparse, sys; sys.path.insert(0, {str(scripts_dst)!r}); "
        "import cococv_local; "
        "ns = argparse.Namespace(file='r.json', output='out.pdf', template='asu-tech', engine=None, "
        "png=True, dpi=150, no_print_background=False, force=False); "
        "print('DELEGATED:', cococv_local._delegate_render_if_available(ns))"
    )
    res = subprocess.run(
        [sys.executable, "-c", probe_code],
        cwd=str(work_dir),
        env={"PATH": str(fake_bin), "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    assert "DELEGATED: None" in res.stdout


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Quartz/PDFKit fallback is darwin-only")
def test_cococv_local_macos_quartz_reads_multipage_pdf_without_deps(tmp_path: Path) -> None:
    """When pymupdf/pypdf/pdftotext are unavailable on macOS, read-source still extracts all pages and PNGs."""
    import shutil

    scripts_dst = tmp_path / "skill" / "scripts"
    shutil.copytree(COMMITTED_SKILL / "scripts", scripts_dst)
    local_script = scripts_dst / "cococv_local.py"

    # Build a minimal valid 2-page PDF in pure Python stdlib (no pymupdf/reportlab/Chrome needed)
    def _build_two_page_pdf(out_path: Path) -> None:
        objects: list[bytes] = []
        # 1: Catalog, 2: Pages, 3: Font, 4: Page1, 5: Contents1, 6: Page2, 7: Contents2
        c1 = b"BT /F1 18 Tf 72 720 Td (PageOneMarker Alice) Tj ET"
        c2 = b"BT /F1 18 Tf 72 720 Td (PageTwoMarker Bob) Tj ET"
        objects.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
        objects.append(b"2 0 obj << /Type /Pages /Kids [4 0 R 6 0 R] /Count 2 >> endobj\n")
        objects.append(b"3 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n")
        objects.append(
            b"4 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >> endobj\n"
        )
        objects.append(f"5 0 obj << /Length {len(c1)} >> stream\n".encode("ascii") + c1 + b"\nendstream endobj\n")
        objects.append(
            b"6 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents 7 0 R >> endobj\n"
        )
        objects.append(f"7 0 obj << /Length {len(c2)} >> stream\n".encode("ascii") + c2 + b"\nendstream endobj\n")

        header = b"%PDF-1.4\n"
        offsets = [0]
        body = bytearray(header)
        for obj in objects:
            offsets.append(len(body))
            body.extend(obj)
        xref_pos = len(body)
        xref_lines = [f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii")]
        for off in offsets[1:]:
            xref_lines.append(f"{off:010d} 00000 n \n".encode("ascii"))
        trailer = f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii")
        out_path.write_bytes(bytes(body) + b"".join(xref_lines) + trailer)

    pdf_path = tmp_path / "two-page-resume.pdf"
    pages_dir = tmp_path / "pages"
    _build_two_page_pdf(pdf_path)

    probe_code = (
        f"import json, sys; sys.path.insert(0, {str(scripts_dst)!r}); "
        "import cococv_local; "
        "cococv_local._has_module = lambda name: False; "
        "orig_which = cococv_local.shutil.which; "
        "cococv_local.shutil.which = lambda name: None if name in ('pdftotext', 'pdftoppm') else orig_which(name); "
        f"res = cococv_local._extract_pdf_local(cococv_local.Path({str(pdf_path)!r}), cococv_local.Path({str(pages_dir)!r})); "
        "print(json.dumps(res, ensure_ascii=False))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe_code],
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["method"] == "macos-quartz"
    assert payload["page_count"] == 2
    assert "PageOneMarker Alice" in payload["text"]
    assert "PageTwoMarker Bob" in payload["text"]
    assert len(payload["page_images"]) == 2
    for img in payload["page_images"]:
        p = Path(img)
        assert p.is_file()
        assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


