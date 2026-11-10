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
