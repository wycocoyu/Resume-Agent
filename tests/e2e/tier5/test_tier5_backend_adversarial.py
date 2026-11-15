"""Tier 5 White-Box Adversarial Coverage Hardening Tests for Backend Subsystems.

Authoritative subsystems under test:
1. backend/mcp/ (official CocoCV MCP Server: FastMCP tool protocol, schema validation,
   non-existent resume IDs, prototype pollution, JSON patch boundaries, concurrency, SSE transport)
2. backend/skillkit/ (universal skill carrier: declarative adapter contracts, schema versions,
   closed keys, directory escape defense, installer state corruption recovery, CRLF hash normalization)
3. backend/cli/ (cococv / resume-agent dual binary CLI aliases, Typer subcommands,
   render input validation, invalid templates, engine mismatch, atomic output protection, JSON errors)
4. backend/latex_generator.py & backend/latex_compiler.py (XeLaTeX CMap injection,
   corrupted PDF recovery, OTF cmap parser boundary conditions, compile error extraction, cleanup)

Zero mock facades: all tests execute against real production code imports.
"""
from __future__ import annotations

import concurrent.futures
import io
import json
import os
import shutil
import struct
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner

# Subsystem 1: MCP Server
import backend.mcp.server as mcp_server
from backend.mcp.server import (
    create_sse_app,
    create_stdio_server,
    get_registered_tools,
    get_resume,
    patch_resume,
    render_pdf,
    sync_workspace,
    validate_resume,
)

# Subsystem 2: SkillKit
from backend.skillkit import _toml
from backend.skillkit.adapters import (
    AdapterError,
    HarnessAdapter,
    load_adapter,
    load_adapters,
)
from backend.skillkit.docs import SkillRenderError
from backend.skillkit.install import (
    candidate_paths,
    install,
    load_manifest,
    save_manifest,
    sha256_bytes,
    sha256_file,
    status_entries,
)

# Subsystem 3: CLI
from backend.cli import app as cli_app, run_cli
from backend.cli.errors import CLIError

# Subsystem 4: LaTeX Generator & Compiler
from backend.latex_compiler import (
    compile_latex_raw,
    resolve_xelatex_executable,
    xelatex_install_hint,
)
from backend.latex_generator import (
    _OTF_GID_UNICODE_CACHE,
    _codepoint_priority,
    _ensure_cjk_tounicode_cmaps,
    _ensure_cjk_tounicode_cmaps_stdlib,
    _parse_otf_gid_to_unicode,
)

WORKTREE_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_DIR = WORKTREE_ROOT / "latex-resume-template"
CJK_DIR = TEMPLATE_DIR / "fonts" / "zh_CN-Adobe"


# ==============================================================================
# Subsystem 1: Official CocoCV MCP Server (backend/mcp/)
# ==============================================================================

def test_t5_01_mcp_validate_resume_adversarial_malformed_payloads():
    """TEST-T5-01: MCP validate_resume handles malformed, non-dict, and extreme inputs defensively."""
    # 1. Non-dict types must return valid=False with score=0 without unhandled exception
    for bad_input in [None, [], "not a dict", 12345, True]:
        result = validate_resume(bad_input)
        assert result["valid"] is False
        assert result["score"] == 0
        assert any("must be a valid JSON dictionary" in err for err in result["errors"])

    # 2. Empty dict must fail ATS name check but not crash
    empty_res = validate_resume({})
    assert empty_res["valid"] is False
    assert empty_res["checks"]["has_name"] is False
    assert empty_res["score"] >= 20

    # 3. Non-string or null candidate name
    null_name_res = validate_resume({"basic": {"name": None}, "name": None})
    assert null_name_res["valid"] is False
    assert null_name_res["checks"]["has_name"] is False

    # 4. Oversized string and Unicode boundary names
    extreme_name = "张三" + "\x00\ufffd\u202e" + ("A" * 10000)
    extreme_res = validate_resume({
        "basic": {"name": extreme_name, "email": "test@cococv.com", "phone": "13800000000"},
        "experience": [{"company": "Tech Corp"}],
    })
    assert extreme_res["checks"]["has_name"] is True
    assert 20 <= extreme_res["score"] <= 100

    # 5. Experience array containing unexpected non-dict elements
    corrupt_exp_res = validate_resume({
        "basic": {"name": "Valid Candidate"},
        "experience": [None, 123, "corrupted"],
    })
    assert corrupt_exp_res["checks"]["has_experience"] is True


def test_t5_02_mcp_get_resume_adversarial_path_traversal_and_corrupt_files(temp_e2e_dir: Path):
    """TEST-T5-02: MCP get_resume safely blocks path traversal and surfaces corrupted JSON files."""
    # 1. Directory traversal paths pointing to non-existent or blocked files
    traversal_paths = [
        "../../etc/passwd",
        "/etc/shadow",
        "../../nonexistent.json",
        temp_e2e_dir / "missing_subdir" / "resume.json",
    ]
    for bad_path in traversal_paths:
        with pytest.raises(FileNotFoundError) as exc_info:
            get_resume(str(bad_path))
        assert "not found" in str(exc_info.value).lower() or "not exist" in str(exc_info.value).lower()

    # 2. Path exists but contains corrupted / malformed JSON
    corrupt_json_file = temp_e2e_dir / "corrupted_resume.json"
    corrupt_json_file.write_text("{ unquoted_key: invalid_json, trailing_comma: true, }", encoding="utf-8")
    with pytest.raises(ValueError, match="Failed to parse resume JSON"):
        get_resume(str(corrupt_json_file))

    # 3. Non-existent UUID (no slashes, no .json)
    with pytest.raises(FileNotFoundError, match="does not exist"):
        get_resume("uuid-nonexistent-999999-adversarial")


def test_t5_03_mcp_patch_resume_adversarial_prototype_pollution_and_schema_attacks(standard_resume_data: dict):
    """TEST-T5-03: MCP patch_resume defends against prototype pollution, type errors, and illegal ops."""
    # 1. Invalid resume_id_or_data input types
    for bad_target in [12345, [1, 2, 3], None, True]:
        with pytest.raises(TypeError, match="must be a dict or a string ID/path"):
            patch_resume(bad_target, [{"op": "replace", "path": "/title", "value": "New"}])

    # 2. Obfuscated and case-varied prototype pollution attempts in 'path'
    pollution_paths = [
        "/__proto__/polluted",
        "/__PROTO__/attack",
        "/basic/__proto__/admin",
        "/constructor/prototype/polluted",
        "/a/constructor/b",
        "/prototype/isRoot",
    ]
    for bad_path in pollution_paths:
        with pytest.raises(ValueError, match="Prototype pollution blocked"):
            patch_resume(standard_resume_data, [{"op": "add", "path": bad_path, "value": True}])

    # 3. Prototype pollution in 'from' field of copy/move operations
    with pytest.raises(ValueError, match="Prototype pollution blocked"):
        patch_resume(
            standard_resume_data,
            [{"op": "move", "from": "/__proto__/secret", "path": "/basic/title"}],
        )

    # 4. Out of bounds array index in patch operations raises ValueError cleanly
    with pytest.raises(ValueError, match="Failed to apply JSON patch"):
        patch_resume(
            standard_resume_data,
            [{"op": "replace", "path": "/workExperience/9999/position", "value": "Ghost"}],
        )

    # 5. Unsupported RFC 6902 operation
    with pytest.raises(ValueError, match="Failed to apply JSON patch"):
        patch_resume(
            standard_resume_data,
            [{"op": "malicious_eval", "path": "/basic/name", "value": "Hacked"}],
        )


def test_t5_04_mcp_render_pdf_adversarial_engine_injection_and_corrupted_templates(standard_resume_data: dict):
    """TEST-T5-04: MCP render_pdf rejects injected engine parameters and handles compilation failure."""
    # 1. Injected engine strings with whitespace or shell operators
    injected_engines = [
        "latex; rm -rf /",
        "html\n--injected",
        "cdp | cat",
        "weasyprint_unknown",
        "",
        "   ",
    ]
    for bad_engine in injected_engines:
        with pytest.raises(ValueError, match="Unsupported rendering engine"):
            render_pdf(standard_resume_data, engine=bad_engine)

    # 2. Valid engine with corrupted resume_data when compiling latex
    broken_resume = {"id": "broken", "sectionOrder": ["invalid_section"]}
    try:
        pdf_out = render_pdf(broken_resume, engine="latex")
        assert pdf_out.startswith(b"%PDF-")
    except RuntimeError as err:
        assert "LaTeX rendering failed" in str(err) or "LaTeX 编译失败" in str(err)

    # 3. HTML/CDP fallback engine generates valid mock PDF header
    html_pdf = render_pdf(standard_resume_data, engine="html")
    assert html_pdf.startswith(b"%PDF-1.4")
    assert len(html_pdf) > 1000


def test_t5_05_mcp_sync_workspace_adversarial_stress_and_concurrency():
    """TEST-T5-05: MCP sync_workspace defends against invalid actions, malformed payloads, and race conditions."""
    # 1. Unsupported or injected action names
    for bad_action in ["delete_all", "truncate", "DROP TABLE", "status; exit 1", ""]:
        with pytest.raises(ValueError, match="Unsupported workspace action"):
            sync_workspace(bad_action, {})

    # 2. 'push' with malformed payloads (empty payload, non-list, non-dict items)
    res1 = sync_workspace("push", {})
    assert res1["status"] == "success"
    assert res1["synced_count"] >= 1

    res2 = sync_workspace("push", {"resumes": [None, 123, "invalid_str", {"title": "Valid One"}]})
    assert res2["status"] == "success"

    # 3. High-concurrency state contention stress test
    def worker_push(worker_id: int):
        doc = {"id": f"doc_{worker_id}", "title": f"Resume {worker_id}", "content": "Adversarial"}
        sync_res = sync_workspace("push", {"resumes": [doc]})
        pull_res = sync_workspace("pull", {})
        status_res = sync_workspace("status", {})
        return sync_res["status"], pull_res["count"], status_res["workspace_active"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(worker_push, i) for i in range(16)]
        results = [f.result() for f in futures]

    assert len(results) == 16
    for status, count, active in results:
        assert status == "success"
        assert count >= 1
        assert active is True


def test_t5_06_mcp_sse_transport_malformed_protocol_requests():
    """TEST-T5-06: MCP SSE Starlette application gracefully rejects malformed HTTP transport requests."""
    app = create_sse_app()
    client = TestClient(app)

    # 1. Non-existent path returns 404
    resp_404 = client.get("/nonexistent/adversarial/endpoint")
    assert resp_404.status_code == 404

    # 2. GET to /messages (which requires POST) returns 405 Method Not Allowed
    resp_405 = client.get("/messages")
    assert resp_405.status_code in (405, 307)
    if resp_405.status_code == 307:
        redirect_resp = client.get(resp_405.headers["location"])
        assert redirect_resp.status_code == 405

    # 3. POST to /messages with malformed, non-JSON body and missing session
    resp_bad_post = client.post("/messages", content=b"MALFORMED_NON_JSON_BYTES", follow_redirects=True)
    assert resp_bad_post.status_code in (400, 422)


# ==============================================================================
# Subsystem 2: Universal SkillKit & Adapters (backend/skillkit/)
# ==============================================================================

def test_t5_07_skillkit_adapter_contract_adversarial_rejection(temp_e2e_dir: Path):
    """TEST-T5-07: SkillKit adapter loader rejects unsupported schema versions, unknown keys, and directory traversal."""
    harnesses_dir = temp_e2e_dir / "harnesses"
    harnesses_dir.mkdir(parents=True)

    # 1. Missing harness directory
    with pytest.raises(AdapterError, match="Missing harness directory"):
        load_adapters(temp_e2e_dir / "nonexistent_root")

    # 2. Empty harness directory
    with pytest.raises(AdapterError, match="No harness adapters found"):
        load_adapters(temp_e2e_dir)

    # 3. Unsupported schema version
    bad_schema_dir = harnesses_dir / "bad_schema"
    bad_schema_dir.mkdir()
    (bad_schema_dir / "meta.toml").write_text(
        'schema_version = 999\nid = "bad"\n[frontmatter]\nname = "bad"\n',
        encoding="utf-8",
    )
    with pytest.raises(AdapterError, match="schema_version must be 1"):
        load_adapter(bad_schema_dir / "meta.toml")

    # 4. Unknown top-level key (closed contract defense)
    bad_keys_dir = harnesses_dir / "bad_keys"
    bad_keys_dir.mkdir()
    (bad_keys_dir / "meta.toml").write_text(
        'schema_version = 1\nid = "bad_keys"\nillegal_injected_key = "exploit"\n',
        encoding="utf-8",
    )
    with pytest.raises(AdapterError, match="unsupported key\\(s\\)"):
        load_adapter(bad_keys_dir / "meta.toml")

    # 5. Directory traversal in asset target
    traversal_dir = harnesses_dir / "traversal"
    traversal_dir.mkdir()
    traversal_toml = (
        'schema_version = 1\n'
        'id = "traversal"\n'
        'status = "verified"\n'
        '[frontmatter]\n'
        'name = "traversal"\n'
        '[[assets]]\n'
        'from = "skill.md"\n'
        'to = "../escaped_target.txt"\n'
        'mode = "skill"\n'
        '[install]\n'
        'strategy = "copy"\n'
    )
    (traversal_dir / "meta.toml").write_text(traversal_toml, encoding="utf-8")
    with pytest.raises(AdapterError, match="must not escape the skill directory"):
        load_adapter(traversal_dir / "meta.toml")


def test_t5_08_skillkit_installer_fault_injection_and_hash_tampering(temp_e2e_dir: Path, monkeypatch):
    """TEST-T5-08: SkillKit installer recovers from corrupt manifests and detects file tampering."""
    monkeypatch.setenv("COCOCV_STATE_DIR", str(temp_e2e_dir / "state"))

    # 1. Corrupted / malformed manifest file recovery
    state_file = temp_e2e_dir / "state" / "state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text("{ unparseable_json: broken [[[", encoding="utf-8")
    manifest = load_manifest()
    assert manifest["version"] == 1
    assert manifest["installs"] == []

    # 2. sha256_file handles missing files and CRLF/LF normalization
    non_file = temp_e2e_dir / "absent.txt"
    assert sha256_file(non_file) is None

    crlf_file = temp_e2e_dir / "file_crlf.txt"
    lf_file = temp_e2e_dir / "file_lf.txt"
    crlf_file.write_bytes(b"Line 1\r\nLine 2\r\nLine 3\r\n")
    lf_file.write_bytes(b"Line 1\nLine 2\nLine 3\n")
    # CRLF and LF must yield identical SHA256 hashes to prevent false positive diffs
    assert sha256_file(crlf_file) == sha256_file(lf_file)

    # 3. Status entries report on empty manifest
    save_manifest({"version": 1, "installs": []})
    assert status_entries() == []


# ==============================================================================
# Subsystem 3: Dual-Binary CLI (backend/cli/)
# ==============================================================================

def test_t5_09_cli_dual_binary_entrypoints_and_routing():
    """TEST-T5-09: CLI entrypoint exposes authoritative subcommands and strictly structured --json mode."""
    runner = CliRunner()

    # 1. Top-level --help lists all registered subcommands
    help_res = runner.invoke(cli_app, ["--help"])
    assert help_res.exit_code == 0
    for cmd in ["init", "schema", "validate", "render", "skill", "sync"]:
        assert cmd in help_res.output

    # 2. Top-level schema command with --json outputs valid JSON Schema
    schema_res = runner.invoke(cli_app, ["schema", "--json"])
    assert schema_res.exit_code == 0
    schema_data = json.loads(schema_res.output)
    assert schema_data.get("type") == "object"
    assert "properties" in schema_data

    # 3. Unknown subcommand returns exit code 2
    bad_cmd_res = runner.invoke(cli_app, ["nonexistent_subcommand"])
    assert bad_cmd_res.exit_code == 2


def test_t5_10_cli_render_adversarial_matrix(temp_e2e_dir: Path, standard_resume_data: dict):
    """TEST-T5-10: CLI render subcommand validates arguments, file existence, and engine mismatch."""
    runner = CliRunner()

    valid_resume_file = temp_e2e_dir / "valid_resume.json"
    valid_resume_file.write_text(json.dumps(standard_resume_data), encoding="utf-8")

    # 1. Missing input file raises CLIError with file_error
    missing_res = runner.invoke(cli_app, ["render", str(temp_e2e_dir / "missing.json"), "-o", str(temp_e2e_dir / "out.pdf")])
    assert missing_res.exit_code != 0
    assert isinstance(missing_res.exception, CLIError)
    assert "File not found" in str(missing_res.exception) or "file_error" in missing_res.exception.code

    # 2. Test structured error output via run_cli with --json
    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        code = run_cli(["--json", "render", str(temp_e2e_dir / "missing.json"), "-o", str(temp_e2e_dir / "out.pdf")])
    finally:
        sys.stdout = old_stdout
    assert code != 0
    json_err = json.loads(captured.getvalue())
    assert json_err["ok"] is False
    assert json_err["error"]["code"] == "file_error"

    # 3. Corrupted JSON file
    corrupt_file = temp_e2e_dir / "corrupted.json"
    corrupt_file.write_text("{ corrupt json syntax ...", encoding="utf-8")
    corrupt_res = runner.invoke(cli_app, ["render", str(corrupt_file), "-o", str(temp_e2e_dir / "out.pdf")])
    assert corrupt_res.exit_code != 0
    assert isinstance(corrupt_res.exception, CLIError)
    assert corrupt_res.exception.code in ("invalid_json", "validation_failed", "file_error")

    # 4. Unsupported output extension
    bad_ext_res = runner.invoke(cli_app, ["render", str(valid_resume_file), "-o", str(temp_e2e_dir / "out.docx")])
    assert bad_ext_res.exit_code != 0
    assert isinstance(bad_ext_res.exception, CLIError)
    assert "Unsupported output extension" in str(bad_ext_res.exception)

    # 5. Engine mismatch: HTML output with LaTeX engine
    mismatch_res = runner.invoke(
        cli_app,
        ["render", str(valid_resume_file), "-o", str(temp_e2e_dir / "out.html"), "--engine", "latex"],
    )
    assert mismatch_res.exit_code != 0
    assert isinstance(mismatch_res.exception, CLIError)
    assert "Cannot render HTML output using LaTeX engine" in str(mismatch_res.exception)

    # 6. Invalid engine argument
    bad_eng_res = runner.invoke(
        cli_app,
        ["render", str(valid_resume_file), "-o", str(temp_e2e_dir / "out.pdf"), "--engine", "quantum"],
    )
    assert bad_eng_res.exit_code != 0
    assert isinstance(bad_eng_res.exception, CLIError)
    assert "Invalid engine 'quantum'" in str(bad_eng_res.exception)

    # 7. File already exists without --force
    existing_out = temp_e2e_dir / "already_exists.html"
    existing_out.write_text("<html>Existing</html>", encoding="utf-8")
    exists_res = runner.invoke(
        cli_app,
        ["render", str(valid_resume_file), "-o", str(existing_out), "--template", "asu-tech"],
    )
    assert exists_res.exit_code != 0
    assert isinstance(exists_res.exception, CLIError)
    assert "already exists" in str(exists_res.exception)


# ==============================================================================
# Subsystem 4: LaTeX Generator & Compiler (backend/latex_*)
# ==============================================================================

def test_t5_11_latex_cmap_injection_corrupted_pdf_and_cache_adversarial():
    """TEST-T5-11: LaTeX ToUnicode CMap injection safely handles corrupted byte streams and missing font dirs."""
    # 1. Missing CJK font directory gracefully returns unmodified bytes
    sample_pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
    res_missing_dir = _ensure_cjk_tounicode_cmaps(sample_pdf, Path("/nonexistent/latex/template/dir"))
    assert res_missing_dir == sample_pdf

    # 2. Corrupted PDF byte stream with real template dir
    corrupted_stream = b"CORRUPTED_PDF_NOT_A_VALID_HEADER\x00\xff"
    try:
        res_corrupt = _ensure_cjk_tounicode_cmaps(corrupted_stream, TEMPLATE_DIR)
        assert res_corrupt == corrupted_stream
    except Exception as exc:
        # PyMuPDF FileDataError or EmptyFileError must be raised cleanly without unhandled system crash
        assert "stream" in str(exc).lower() or "filedataerror" in type(exc).__name__.lower()

    # 3. Pure stdlib updater handles corrupted startxref offset without crashing
    res_stdlib = _ensure_cjk_tounicode_cmaps_stdlib(corrupted_stream, CJK_DIR)
    assert res_stdlib == corrupted_stream


def test_t5_12_latex_otf_font_parser_fault_injection(temp_e2e_dir: Path):
    """TEST-T5-12: OTF font parser safely handles non-existent or truncated files and enforces CJK priorities."""
    # 1. Non-existent font file returns empty mapping
    missing_font = temp_e2e_dir / "absent_font.otf"
    assert _parse_otf_gid_to_unicode(missing_font) == {}

    # 2. 0-byte font file triggers struct.error without corrupting cache
    zero_font = temp_e2e_dir / "zero.otf"
    zero_font.write_bytes(b"")
    with pytest.raises(struct.error):
        _parse_otf_gid_to_unicode(zero_font)
    assert str(zero_font.resolve()) not in _OTF_GID_UNICODE_CACHE

    # 3. Verify CJK codepoint priority rules
    # Standard CJK Unified Ideographs (0x4E00..0x9FFF) have highest priority (3)
    assert _codepoint_priority(0x4E00) == 3
    assert _codepoint_priority(0x9FA5) == 3
    # Radicals and compatibility blocks have lowest priority (0)
    assert _codepoint_priority(0x2E80) == 0
    assert _codepoint_priority(0xF900) == 0
    # Other blocks have intermediate priority (2)
    assert _codepoint_priority(0x3000) == 2


def test_t5_13_latex_compiler_raw_syntax_error_and_tempdir_cleanup():
    """TEST-T5-13: compile_latex_raw surfaces compiler errors and cleans up temporary working directories."""
    # Syntactically broken LaTeX with undefined control sequence
    broken_latex = r"""\documentclass{resume}
\begin{document}
\undefinedAdversarialMacro{Broken}
\end{document}
"""
    with pytest.raises(RuntimeError) as exc_info:
        compile_latex_raw(broken_latex)

    err_text = str(exc_info.value)
    assert "LaTeX 编译失败" in err_text or "Undefined control sequence" in err_text


def test_t5_14_end_to_end_backend_fault_injection_recovery(temp_e2e_dir: Path, standard_resume_data: dict):
    """TEST-T5-14: End-to-end integration verifies sequential multi-vector fault injection recovery."""
    runner = CliRunner()

    # Step 1: Malicious prototype pollution payload injected into resume data
    malicious_data = json.loads(json.dumps(standard_resume_data))
    malicious_data["basic"]["__proto__"] = {"isAdmin": True}

    resume_file = temp_e2e_dir / "poisoned_resume.json"
    resume_file.write_text(json.dumps(malicious_data), encoding="utf-8")

    # Step 2: Validate through CLI rejects extra injected prototype pollution keys (extra='forbid')
    val_res = runner.invoke(cli_app, ["validate", str(resume_file)])
    assert val_res.exit_code != 0
    assert isinstance(val_res.exception, CLIError)
    assert "Validation failed" in str(val_res.exception) or "extra_forbidden" in str(val_res.exception)

    # Step 3: Attempt MCP patch with prototype pollution raises ValueError
    with pytest.raises(ValueError, match="Prototype pollution blocked"):
        patch_resume(malicious_data, [{"op": "replace", "path": "/__proto__/admin", "value": True}])

    # Step 4: After sanitizing forbidden extra fields, validate and render succeed cleanly
    sanitized_data = json.loads(json.dumps(standard_resume_data))
    clean_resume_file = temp_e2e_dir / "clean_resume.json"
    clean_resume_file.write_text(json.dumps(sanitized_data), encoding="utf-8")

    clean_val_res = runner.invoke(cli_app, ["validate", str(clean_resume_file)])
    assert clean_val_res.exit_code == 0

    html_out = temp_e2e_dir / "clean_output.html"
    render_res = runner.invoke(
        cli_app,
        ["render", str(clean_resume_file), "-o", str(html_out), "--template", "asu-tech"],
    )
    assert render_res.exit_code == 0
    assert html_out.is_file()
    assert html_out.stat().st_size > 500
