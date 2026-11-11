"""Tests for Slice S2: offline zero-network PDF rendering, photo+missing-logo recompilation, sectionOrder=[], and path escape guards."""
from __future__ import annotations

import base64
import json
import socket
import urllib.request
import zlib
import struct
from pathlib import Path

import fitz
import httpx
import pytest

import backend.company_logos as company_logos
import backend.latex_generator as latex_generator
import backend.school_logos as school_logos
from backend.cli import run_cli
from backend.cli.schema import build_initial_resume


def _make_valid_png_bytes(width: int = 8, height: int = 8) -> bytes:
    """Construct a minimal valid RGB PNG in memory without external tools."""
    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw_rows = b"".join(b"\x00" + (b"\x20\x60\xc0" * width) for _ in range(height))
    idat = zlib.compress(raw_rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", idat)
        + _chunk(b"IEND", b"")
    )


def _write_resume(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_logo_and_shared_photo_path_traversal_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret_png = tmp_path / "secret.png"
    secret_png.write_bytes(_make_valid_png_bytes())

    logo_dir = tmp_path / "images" / "logo"
    logo_dir.mkdir(parents=True)
    school_dir = tmp_path / "images" / "school_logo" / "985"
    school_dir.mkdir(parents=True)
    (school_dir / "清华大学.png").write_bytes(_make_valid_png_bytes())

    monkeypatch.setattr(company_logos, "LOCAL_LOGO_DIR", logo_dir)
    monkeypatch.setattr(school_logos, "LOCAL_SCHOOL_LOGO_DIR", tmp_path / "images" / "school_logo")
    company_logos.clear_cache()
    school_logos.clear_cache()

    for bad_key in [
        str(secret_png),
        str(secret_png.with_suffix("")),
        "../secret",
        "../../secret",
        "sub/secret",
        r"..\secret",
        "",
    ]:
        assert company_logos.get_logo_local_path(bad_key) is None
        assert school_logos.get_school_logo_local_path(bad_key) is None

    # Shared Web helper _download_user_photo_to_dir must NEVER read local paths
    photo_tmp = tmp_path / "tex_tmp"
    photo_tmp.mkdir()
    assert latex_generator._download_user_photo_to_dir(str(secret_png), str(photo_tmp)) is None
    assert latex_generator._download_user_photo_to_dir(f"file://{secret_png}", str(photo_tmp)) is None


def test_offline_render_zero_network_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    network_attempts = 0

    def _forbid_network(*args, **kwargs):
        nonlocal network_attempts
        network_attempts += 1
        raise AssertionError("Offline render attempted network access!")

    monkeypatch.setattr(socket.socket, "connect", _forbid_network)
    monkeypatch.setattr(socket.socket, "connect_ex", _forbid_network)
    monkeypatch.setattr(urllib.request, "urlopen", _forbid_network)
    monkeypatch.setattr(urllib.request, "urlretrieve", _forbid_network)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", _forbid_network)
    monkeypatch.setattr(httpx.Client, "send", _forbid_network)
    monkeypatch.setattr(httpx.AsyncClient, "send", _forbid_network)
    monkeypatch.setenv("COS_SECRET_ID", "should-not-be-used")
    monkeypatch.setenv("COS_SECRET_KEY", "should-not-be-used")

    # Point local logo dirs to empty temp dirs so any fallback to COS would be caught immediately
    empty_logo_dir = tmp_path / "empty_logos"
    empty_school_dir = tmp_path / "empty_schools"
    empty_logo_dir.mkdir()
    empty_school_dir.mkdir()
    monkeypatch.setattr(company_logos, "LOCAL_LOGO_DIR", empty_logo_dir)
    monkeypatch.setattr(school_logos, "LOCAL_SCHOOL_LOGO_DIR", empty_school_dir)
    company_logos.clear_cache()
    school_logos.clear_cache()

    resume = build_initial_resume(title="离线零网络测试")
    resume["templateType"] = "html"
    resume["basic"].update(
        {
            "name": "王五",
            "title": "系统架构师",
            "email": "wangwu@example.com",
            "phone": "13700002222",
            "location": "北京",
            "photo": "https://example.com/remote-avatar.png",
        }
    )
    resume["education"] = [
        {
            "id": "edu_1",
            "school": "北京大学",
            "major": "计算机科学",
            "degree": "本科",
            "startDate": "2018.09",
            "endDate": "2022.06",
            "schoolLogo": "北京大学",
            "visible": True,
        }
    ]
    resume["experience"] = [
        {
            "id": "exp_1",
            "company": "字节跳动",
            "position": "架构实习生",
            "date": "2021.06 - 2021.09",
            "details": "<p>完成零外联离线渲染链路验证</p>",
            "companyLogo": "bytedance",
            "visible": True,
        }
    ]

    in_json = _write_resume(tmp_path / "offline.json", resume)
    out_pdf = tmp_path / "offline.pdf"

    code = run_cli(["render", str(in_json), "-o", str(out_pdf), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert network_attempts == 0
    assert code == 0, payload
    assert payload["ok"] is True
    assert payload["offline"] is True
    assert out_pdf.is_file() and out_pdf.stat().st_size > 1000
    assert any("HTML" in w for w in payload["warnings"])
    assert any("远程头像" in w for w in payload["warnings"])
    assert any("bytedance" in w for w in payload["warnings"])

    with fitz.open(out_pdf) as doc:
        assert doc.page_count >= 1
        page_text = doc[0].get_text()
        assert "王五" in page_text
        assert "字节跳动" in page_text


def test_local_photo_survives_missing_logo_recompilation_and_embeds_in_pdf(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    avatar_path = tmp_path / "avatar.png"
    avatar_path.write_bytes(_make_valid_png_bytes(12, 12))

    resume = build_initial_resume()
    resume["basic"].update(
        {
            "name": "赵六",
            "title": "资深工程师",
            "email": "zhaoliu@example.com",
            "phone": "13600003333",
            "location": "上海",
            "photo": str(avatar_path),
        }
    )
    # Missing companyLogo forces sanitized_for_assets != resume_data -> secondary json_to_latex call
    resume["workExperience"] = [
        {
            "id": "work_1",
            "company": "未来星辰科技",
            "position": "后端研发",
            "date": "2024.01 - 至今",
            "details": "<p>主导核心存储引擎研发</p>",
            "companyLogo": "nonexistent_company_logo_key_999",
            "visible": True,
        }
    ]

    in_json = _write_resume(tmp_path / "photo_recompile.json", resume)
    out_pdf = tmp_path / "photo_recompile.pdf"

    code = run_cli(["render", str(in_json), "-o", str(out_pdf), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0, payload
    assert payload["ok"] is True
    assert any("nonexistent_company_logo_key_999" in w for w in payload["warnings"])

    with fitz.open(out_pdf) as doc:
        assert doc.page_count >= 1
        images = doc[0].get_images()
        assert len(images) >= 1, "Local avatar PNG must remain embedded after missing-logo recompilation"
        assert "赵六" in doc[0].get_text()
        assert "未来星辰科技" in doc[0].get_text()


def test_base64_photo_and_disguised_webp_magic_byte_filtering(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # 1. Valid base64 PNG data URI embeds image
    png_b64 = base64.b64encode(_make_valid_png_bytes(6, 6)).decode("ascii")
    resume_b64 = build_initial_resume()
    resume_b64["basic"]["name"] = "孙七"
    resume_b64["basic"]["photo"] = f"data:image/png;base64,{png_b64}"
    in_b64 = _write_resume(tmp_path / "b64.json", resume_b64)
    out_b64 = tmp_path / "b64.pdf"

    code1 = run_cli(["render", str(in_b64), "-o", str(out_b64), "--json"])
    payload1 = json.loads(capsys.readouterr().out)
    assert code1 == 0, payload1
    with fitz.open(out_b64) as doc:
        assert len(doc[0].get_images()) >= 1

    # 2. Disguised WebP file with .png extension is blocked by magic bytes and safely stripped
    fake_webp = tmp_path / "disguised.png"
    fake_webp.write_bytes(b"RIFF\x24\x00\x00\x00WEBPVP8 ")
    resume_webp = build_initial_resume()
    resume_webp["basic"]["name"] = "周八"
    resume_webp["basic"]["photo"] = str(fake_webp)
    in_webp = _write_resume(tmp_path / "webp.json", resume_webp)
    out_webp = tmp_path / "webp.pdf"

    code2 = run_cli(["render", str(in_webp), "-o", str(out_webp), "--json"])
    payload2 = json.loads(capsys.readouterr().out)
    assert code2 == 0, payload2
    assert any("不受 XeLaTeX 支持" in w for w in payload2["warnings"])
    with fitz.open(out_webp) as doc:
        assert len(doc[0].get_images()) == 0
        assert "周八" in doc[0].get_text()


def test_empty_section_order_with_missing_logo_never_leaks_disabled_sections(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Cache key must distinguish None vs []
    sample = {"name": "测试"}
    assert latex_generator._get_cache_key(sample, None) != latex_generator._get_cache_key(sample, [])

    resume = build_initial_resume()
    resume["basic"]["name"] = "仅头部用户"
    for sec in resume["menuSections"]:
        if sec["id"] != "basic":
            sec["enabled"] = False
    resume["workExperience"] = [
        {
            "id": "w_hidden",
            "company": "绝密未启用公司经历",
            "position": "绝密职位",
            "date": "2025",
            "details": "<p>绝密内容不得泄漏</p>",
            "companyLogo": "missing_logo_triggers_recompile",
            "visible": True,
        }
    ]

    in_json = _write_resume(tmp_path / "only_basic.json", resume)
    out_pdf = tmp_path / "only_basic.pdf"

    code = run_cli(["render", str(in_json), "-o", str(out_pdf), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0, payload

    with fitz.open(out_pdf) as doc:
        text = doc[0].get_text()
        assert "仅头部用户" in text
        assert "绝密未启用公司经历" not in text
        assert "绝密内容不得泄漏" not in text

    # Also verify direct compile_latex_to_pdf(..., section_order=[]) when backend dict lacks sectionOrder key
    direct_backend = {
        "name": "直调用户",
        "workExperience": [
            {
                "title": "直调隐藏公司",
                "subtitle": "研发",
                "date": "2025",
                "highlights": ["<p>直调隐藏正文</p>"],
                "logo": "missing_direct_logo",
            }
        ],
    }
    initial_tex = latex_generator.json_to_latex(direct_backend, section_order=[], offline=True)
    template_dir = Path(__file__).resolve().parents[2] / "latex-resume-template"
    pdf_io = latex_generator.compile_latex_to_pdf(
        initial_tex,
        template_dir,
        resume_data=direct_backend,
        section_order=[],
        offline=True,
    )
    with fitz.open(stream=pdf_io.getvalue(), filetype="pdf") as doc2:
        text2 = doc2[0].get_text()
        assert "直调用户" in text2
        assert "直调隐藏公司" not in text2


def test_render_failure_modes_leave_no_corrupt_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    resume = build_initial_resume()
    resume["basic"]["name"] = "异常分支用户"
    in_json = _write_resume(tmp_path / "err.json", resume)

    # 1. Refuses overwrite without --force
    existing_pdf = tmp_path / "existing.pdf"
    existing_pdf.write_bytes(b"%PDF-sentinel")
    code_exists = run_cli(["render", str(in_json), "-o", str(existing_pdf), "--json"])
    payload_exists = json.loads(capsys.readouterr().out)
    assert code_exists == 1
    assert payload_exists["error"]["code"] == "file_exists"
    assert existing_pdf.read_bytes() == b"%PDF-sentinel"

    # 2. Missing template dir
    out_missing_tpl = tmp_path / "no_tpl.pdf"
    code_tpl = run_cli(
        [
            "render",
            str(in_json),
            "-o",
            str(out_missing_tpl),
            "--template-dir",
            str(tmp_path / "does_not_exist"),
            "--json",
        ]
    )
    payload_tpl = json.loads(capsys.readouterr().out)
    assert code_tpl == 1
    assert payload_tpl["error"]["code"] == "template_not_found"
    assert not out_missing_tpl.exists()

    # 3. Missing xelatex executable
    monkeypatch.setattr(latex_generator, "resolve_xelatex_executable", lambda: None)
    out_no_tex = tmp_path / "no_xelatex.pdf"
    code_tex = run_cli(["render", str(in_json), "-o", str(out_no_tex), "--json"])
    payload_tex = json.loads(capsys.readouterr().out)
    assert code_tex == 1
    assert payload_tex["error"]["code"] == "render_failed"
    assert not out_no_tex.exists()


def test_compile_latex_to_pdf_with_none_resume_data_still_embeds_local_photo_bytes() -> None:
    template_dir = Path(__file__).resolve().parents[2] / "latex-resume-template"
    tex = latex_generator.json_to_latex(
        {"name": "无简历字典头像用户", "photo": "__cli_local_photo__", "contact": {}},
        section_order=[],
        offline=True,
    )
    pdf_io = latex_generator.compile_latex_to_pdf(
        tex,
        template_dir,
        resume_data=None,
        local_photo_bytes=(".png", _make_valid_png_bytes(10, 10)),
        offline=True,
    )
    with fitz.open(stream=pdf_io.getvalue(), filetype="pdf") as doc:
        assert len(doc[0].get_images()) >= 1
        assert "无简历字典头像用户" in doc[0].get_text()


@pytest.mark.parametrize("display_mode", ["below", "inline", "icon"])
def test_special_char_urls_and_custom_section_reordering_compile_cleanly(
    display_mode: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    resume = build_initial_resume(title="复杂URL与排序测试")
    resume["templateType"] = "html"
    resume["basic"].update(
        {
            "name": "陈九",
            "title": "分布式系统工程师",
            "email": "chen_jiu@example.com",
            "phone": "13500009999",
            "location": "杭州",
            "blog": "https://github.com/chen_jiu/~notes?tab=repos&pct=100%25#top_anchor",
        }
    )
    resume["globalSettings"]["openSourceRepoDisplay"] = display_mode
    resume["globalSettings"]["projectLinkDisplay"] = display_mode
    # Reorder menuSections: custom_research first, then projects, then openSource
    resume["menuSections"] = [
        {"id": "basic", "title": "基本信息", "icon": "👤", "enabled": True, "order": 0},
        {"id": "custom_research", "title": "科研成果", "icon": "🔬", "enabled": True, "order": 1},
        {"id": "projects", "title": "核心项目", "icon": "🚀", "enabled": True, "order": 2},
        {"id": "openSource", "title": "开源贡献", "icon": "🔗", "enabled": True, "order": 3},
    ]
    resume["customData"] = {
        "custom_research": [
            {
                "id": "cr_1",
                "title": "OSDI 论文一作",
                "subtitle": "系统方向",
                "dateRange": "2025.05",
                "description": '<ul><li><p>延迟降低 40% &amp; 吞吐提升 2x</p><ol><li><p>子步骤 #1</p></li></ol></li></ul>',
                "visible": True,
            }
        ]
    }
    resume["projects"] = [
        {
            "id": "p_1",
            "name": "云原生网关",
            "role": "负责人",
            "date": "2024.03 - 2025.02",
            "link": "https://github.com/chen_jiu/gw_core?x=1&y=2%20ok#arch_v2",
            "description": '<p>文档：<a href="https://example.com/a_b?c=1&amp;d=2#sec_1">设计说明_v2</a></p>',
            "visible": True,
        }
    ]
    resume["openSource"] = [
        {
            "id": "os_1",
            "name": "raft_kv",
            "role": "Maintainer",
            "repo": "https://github.com/chen_jiu/raft_kv?ref=v1_0&lang=zh%20CN#design",
            "description": "<p>实现 Raft 选主与日志复制</p>",
            "visible": True,
        }
    ]

    in_json = _write_resume(tmp_path / f"urls_{display_mode}.json", resume)
    out_pdf = tmp_path / f"urls_{display_mode}.pdf"

    # Exercise human-readable render output on 'below', JSON mode on others
    if display_mode == "below":
        code = run_cli(["render", str(in_json), "-o", str(out_pdf)])
        captured = capsys.readouterr()
        assert code == 0, captured.err
        assert "Rendered PDF to " in captured.out
        assert "Warning:" in captured.err
    else:
        code = run_cli(["render", str(in_json), "-o", str(out_pdf), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert code == 0, payload

    with fitz.open(out_pdf) as doc:
        text = doc[0].get_text()
        assert "陈九" in text
        assert text.index("OSDI") < text.index("云原生网关") < text.index("raft_kv")
        type0_xrefs = [
            xref
            for xref in range(1, doc.xref_length())
            if "/Subtype /Type0" in doc.xref_object(xref)
        ]
        assert type0_xrefs, "Expected Type0 fonts in rendered PDF"
        for xref in type0_xrefs:
            assert "/ToUnicode" in doc.xref_object(xref), f"Missing /ToUnicode on Type0 font XREF {xref}"


def test_download_url_to_path_enforces_max_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, n: int = -1) -> bytes:
            return b"x" * n

    class _FakeOpener:
        def open(self, req, timeout=None):
            return _FakeResp()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **kw: _FakeOpener())
    dest = tmp_path / "oversized.bin"
    with pytest.raises(ValueError, match="exceeds"):
        company_logos._download_url_to_path("https://example.com/big.png", dest, max_bytes=64)
    assert not dest.exists()


def test_cjk_tounicode_stdlib_fallback_when_pymupdf_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: even when pymupdf/fitz is absent at runtime, CJK Type0 fonts still get /ToUnicode CMaps."""
    import sys
    import tomllib

    # 1. pyproject.toml must declare PyMuPDF so `pip install .` / `uv run` includes it
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    pyproject_data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    deps = [d.lower() for d in pyproject_data["project"]["dependencies"]]
    assert any(d.startswith("pymupdf") for d in deps), f"PyMuPDF missing from pyproject.toml: {deps}"

    # 2. Produce a raw xelatex PDF WITHOUT post-processing by temporarily bypassing _ensure_cjk_tounicode_cmaps
    template_dir = Path(__file__).resolve().parents[2] / "latex-resume-template"
    resume = {
        "name": "尹昕雨",
        "contact": {"phone": "19854081014", "email": "test@example.com", "location": "深圳"},
        "education": [
            {
                "title": "深圳大学",
                "subtitle": "播音与主持艺术",
                "degree": "本科",
                "date": "2022.9-2026.7",
                "details": ["主修课程：视听语言、非线性编辑"],
            }
        ],
    }
    latex_code = latex_generator.json_to_latex(resume, ["education"])

    orig_helper = latex_generator._ensure_cjk_tounicode_cmaps
    monkeypatch.setattr(latex_generator, "_ensure_cjk_tounicode_cmaps", lambda b, _t: b)
    raw_pdf_bytes = latex_generator.compile_latex_to_pdf(
        latex_code, template_dir, resume_data=resume, offline=True
    ).getvalue()
    monkeypatch.setattr(latex_generator, "_ensure_cjk_tounicode_cmaps", orig_helper)

    # Confirm raw xelatex PDF lacks /ToUnicode on CJK Type0 fonts
    with fitz.open(stream=raw_pdf_bytes, filetype="pdf") as raw_doc:
        raw_missing = [
            xref
            for xref in range(1, raw_doc.xref_length())
            if "/Subtype /Type0" in raw_doc.xref_object(xref)
            and "/ToUnicode" not in raw_doc.xref_object(xref)
        ]
        assert raw_missing, "Expected raw xelatex CJK Type0 fonts to lack /ToUnicode"
        # Save a classic ASCII xref variant (garbage=0, deflate=True, no ObjStm) to test classic xref branch too
        classic_xref_raw = raw_doc.tobytes(garbage=1, deflate=True)

    # 3. Block both pymupdf and fitz and run _ensure_cjk_tounicode_cmaps -> exercises stdlib incremental updater
    monkeypatch.setitem(sys.modules, "pymupdf", None)
    monkeypatch.setitem(sys.modules, "fitz", None)
    fixed_objstm_pdf = orig_helper(raw_pdf_bytes, template_dir)
    fixed_classic_pdf = orig_helper(classic_xref_raw, template_dir)
    monkeypatch.undo()

    for variant_name, pdf_blob in [("xref_stream_objstm", fixed_objstm_pdf), ("classic_xref", fixed_classic_pdf)]:
        assert len(pdf_blob) > len(raw_pdf_bytes) or variant_name == "classic_xref"
        with fitz.open(stream=pdf_blob, filetype="pdf") as fixed_doc:
            extracted = fixed_doc[0].get_text()
            assert "尹昕雨" in extracted, f"{variant_name} failed to extract 尹昕雨: {extracted!r}"
            assert "深圳大学" in extracted, f"{variant_name} failed to extract 深圳大学: {extracted!r}"
            type0_xrefs = [
                xref
                for xref in range(1, fixed_doc.xref_length())
                if "/Subtype /Type0" in fixed_doc.xref_object(xref)
            ]
            assert type0_xrefs
            for xref in type0_xrefs:
                assert "/ToUnicode" in fixed_doc.xref_object(xref), (
                    f"{variant_name}: Type0 font XREF {xref} still missing /ToUnicode"
                )


