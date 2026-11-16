#!/usr/bin/env python3
"""Zero-dependency CocoCV local helper bundled inside AI harness skills.

Works with Python 3.10+ standard library only (plus sibling ``html_generator.py``)
so users who only install the skill directory can initialize, validate, and
render self-contained A4 HTML resumes locally without ``pip install cococv``,
Headless Chrome, or XeLaTeX. When optional local tools (``cococv``, ``PyMuPDF``,
Chrome/Edge, or ``xelatex``) are installed, it automatically unlocks PNG previews
and local PDF export, or provides an explicit opt-in ``handoff`` link to Web.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any
import urllib.error
import urllib.request

sys.dont_write_bytecode = True
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import html_generator  # noqa: E402

HTML_TEMPLATES = {"asu-tech", "html-classic"} | {f"asu-{i:02d}" for i in range(1, 19)}
DEFAULT_WEB_API_URL = "https://cococv.cn"

DEFAULT_MENU_SECTIONS: list[dict[str, Any]] = [
    {"id": "basic", "title": "基本信息", "icon": "👤", "enabled": True, "order": 0},
    {"id": "education", "title": "教育经历", "icon": "🎓", "enabled": True, "order": 1},
    {"id": "workExperience", "title": "工作经历", "icon": "🏢", "enabled": True, "order": 2},
    {"id": "experience", "title": "实习经历", "icon": "💼", "enabled": True, "order": 3},
    {"id": "projects", "title": "项目经历", "icon": "🚀", "enabled": True, "order": 4},
    {"id": "openSource", "title": "开源经历", "icon": "🔗", "enabled": True, "order": 5},
    {"id": "skills", "title": "专业技能", "icon": "⚡", "enabled": True, "order": 6},
    {"id": "awards", "title": "荣誉奖项", "icon": "🎖️", "enabled": True, "order": 7},
    {"id": "selfEvaluation", "title": "自我评价", "icon": "📝", "enabled": True, "order": 8},
    {"id": "custom_research", "title": "竞赛科研", "icon": "🔬", "enabled": True, "order": 9},
]

DEFAULT_GLOBAL_SETTINGS: dict[str, Any] = {
    "lineHeight": 1.5,
    "baseFontSize": 16,
    "headerSize": 18,
    "pagePadding": 40,
    "sectionSpacing": 20,
    "paragraphSpacing": 10,
    "experienceGap": 1,
    "projectExperienceGap": 1,
    "latexFontSize": 11,
    "latexMargin": "standard",
    "latexLineSpacing": 1.15,
    "latexHeaderTopGapPx": -4,
    "latexHeaderNameContactGapPx": 0,
    "latexHeaderBottomGapPx": -1,
}

_REQUIRED_TOP_KEYS = (
    "id",
    "title",
    "basic",
    "education",
    "experience",
    "projects",
    "openSource",
    "awards",
    "customData",
    "selfEvaluation",
    "skillContent",
    "menuSections",
    "globalSettings",
)


class LocalToolError(Exception):
    def __init__(self, message: str, *, code: str, exit_code: int = 1, extra: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.exit_code = exit_code
        self.extra = extra or {}


def _emit_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _atomic_write_bytes(output: Path, data: bytes) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".cococv_local_", suffix=".tmp", dir=str(output.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
        os.replace(tmp_path, output)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def find_chrome_executable() -> Path | None:
    for env_var in ("CHROME_BIN", "CHROME_PATH", "GOOGLE_CHROME_BIN"):
        val = os.environ.get(env_var)
        if val is not None:
            if not val.strip() or val.strip().lower() in ("0", "none", "false", "disabled"):
                return None
            p = Path(val).expanduser()
            return p if p.is_file() and os.access(p, os.X_OK) else None

    candidates = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
        Path("/snap/bin/chromium"),
    ]
    for bin_name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
        found = shutil.which(bin_name)
        if found:
            candidates.insert(0, Path(found))

    for base_env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base_dir = os.environ.get(base_env)
        if base_dir:
            for rel in (
                "Google/Chrome/Application/chrome.exe",
                "Chromium/Application/chrome.exe",
                "Microsoft/Edge/Application/msedge.exe",
            ):
                candidates.append(Path(base_dir) / rel)

    for p in candidates:
        try:
            if p.is_file() and os.access(p, os.X_OK):
                return p
        except OSError:
            continue
    return None


def find_xelatex_executable() -> Path | None:
    for env_var in ("XELATEX_PATH", "LATEX_XELATEX_PATH"):
        val = os.environ.get(env_var, "").strip().strip('"')
        if val:
            p = Path(val).expanduser()
            if p.is_file():
                return p
            found = shutil.which(val)
            if found:
                return Path(found)

    found = shutil.which("xelatex") or shutil.which("xelatex.exe")
    if found:
        return Path(found)

    for p in (
        Path("/Library/TeX/texbin/xelatex"),
        Path("/usr/local/texlive/bin/universal-apple/xelatex"),
        Path("/usr/local/texlive/bin/x86_64-darwin/xelatex"),
    ):
        try:
            if p.exists():
                return p
        except OSError:
            continue
    return None


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _find_cococv_cli() -> list[str] | None:
    for exe in ("cococv", "resume-agent"):
        found = shutil.which(exe)
        if found:
            return [found]
    if _has_module("backend.cli"):
        return [sys.executable, "-m", "backend.cli"]
    return None


def probe_environment() -> dict[str, Any]:
    cli_cmd = _find_cococv_cli()
    has_pymupdf = _has_module("pymupdf") or _has_module("fitz")
    chrome_bin = find_chrome_executable()
    xelatex_bin = find_xelatex_executable()
    return {
        "python": sys.version.split()[0],
        "cococv_cli": " ".join(cli_cmd) if cli_cmd else None,
        "pymupdf": has_pymupdf,
        "chrome": str(chrome_bin) if chrome_bin else None,
        "xelatex": str(xelatex_bin) if xelatex_bin else None,
        "recommended_engine": "html",
        "capabilities": {
            "local_html": True,
            "local_html_pdf": bool(chrome_bin),
            "local_html_png": bool(chrome_bin),
            "local_latex_pdf": bool(cli_cmd and xelatex_bin),
            "local_latex_png": bool(cli_cmd and xelatex_bin and has_pymupdf),
        },
    }


def build_initial_resume(*, title: str = "我的简历") -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    now_iso = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return {
        "id": f"resume_{now_ms}",
        "title": title,
        "createdAt": now_iso,
        "updatedAt": now_iso,
        "templateId": None,
        "templateType": "latex",
        "basic": {
            "name": "",
            "title": "",
            "email": "",
            "phone": "",
            "location": "",
        },
        "education": [],
        "workExperience": [],
        "experience": [],
        "projects": [],
        "openSource": [],
        "awards": [],
        "customData": {},
        "selfEvaluation": "",
        "skillContent": "",
        "activeSection": "basic",
        "draggingProjectId": None,
        "menuSections": [dict(sec) for sec in DEFAULT_MENU_SECTIONS],
        "globalSettings": dict(DEFAULT_GLOBAL_SETTINGS),
    }


def _issue(path: str, message: str, err_type: str) -> dict[str, str]:
    return {"path": path, "message": message, "type": err_type}


def validate_resume_dict_stdlib(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, dict):
        return [_issue("<root>", "Resume JSON root must be an object", "dict_type")]

    issues: list[dict[str, str]] = []
    for key in _REQUIRED_TOP_KEYS:
        if key not in raw:
            issues.append(_issue(key, "Field required", "missing"))

    for str_key in ("id", "title"):
        val = raw.get(str_key)
        if val is not None and (not isinstance(val, str) or not val.strip()):
            issues.append(_issue(str_key, "must be a non-empty string", "string_type"))

    basic = raw.get("basic")
    if basic is not None:
        if not isinstance(basic, dict):
            issues.append(_issue("basic", "Input should be a valid dictionary", "dict_type"))
        else:
            for field in ("name", "title", "email", "phone", "location"):
                if field not in basic:
                    issues.append(_issue(f"basic.{field}", "Field required", "missing"))
                elif not isinstance(basic[field], str):
                    issues.append(_issue(f"basic.{field}", "Input should be a valid string", "string_type"))

    for list_key in ("education", "experience", "projects", "openSource", "awards", "menuSections"):
        val = raw.get(list_key)
        if val is not None and not isinstance(val, list):
            issues.append(_issue(list_key, "Input should be a valid list", "list_type"))

    if "workExperience" in raw and raw["workExperience"] is not None and not isinstance(raw["workExperience"], list):
        issues.append(_issue("workExperience", "Input should be a valid list", "list_type"))

    menu_sections = raw.get("menuSections")
    enabled_menu_ids: set[str] = set()
    if isinstance(menu_sections, list):
        for idx, item in enumerate(menu_sections):
            prefix = f"menuSections[{idx}]"
            if not isinstance(item, dict):
                issues.append(_issue(prefix, "Input should be a valid dictionary", "dict_type"))
                continue
            for req in ("id", "title", "icon", "enabled", "order"):
                if req not in item:
                    issues.append(_issue(f"{prefix}.{req}", "Field required", "missing"))
            sec_id = item.get("id")
            if isinstance(sec_id, str) and sec_id.strip():
                if item.get("enabled") is True:
                    enabled_menu_ids.add(sec_id)
            elif "id" in item:
                issues.append(_issue(f"{prefix}.id", "must be a non-empty string", "value_error"))
            if "enabled" in item and not isinstance(item["enabled"], bool):
                issues.append(_issue(f"{prefix}.enabled", "Input should be a valid boolean", "bool_type"))
            if "order" in item and (isinstance(item["order"], bool) or not isinstance(item["order"], int)):
                issues.append(_issue(f"{prefix}.order", "Input should be a valid integer", "int_type"))

    awards = raw.get("awards")
    if isinstance(awards, list):
        for idx, award in enumerate(awards):
            if isinstance(award, dict):
                desc = award.get("description")
                if isinstance(desc, str) and re.search(r"</?(?:p|ul|ol|li|div|span|br|strong|em|b|i)\b", desc, re.I):
                    issues.append(
                        _issue(
                            f"awards[{idx}].description",
                            "awards[*].description must be plain text without HTML tags",
                            "plain_text_violation",
                        )
                    )

    custom_data = raw.get("customData")
    if custom_data is not None:
        if not isinstance(custom_data, dict):
            issues.append(_issue("customData", "Input should be a valid dictionary", "dict_type"))
        elif isinstance(menu_sections, list):
            for ckey, cval in custom_data.items():
                if isinstance(ckey, str) and ckey.startswith("custom_") and isinstance(cval, list) and cval:
                    if ckey not in enabled_menu_ids:
                        issues.append(
                            _issue(
                                f"customData.{ckey}",
                                f"Non-empty custom section '{ckey}' has no enabled entry in menuSections",
                                "custom_section_unlinked",
                            )
                        )

    if "globalSettings" in raw and not isinstance(raw["globalSettings"], dict):
        issues.append(_issue("globalSettings", "Input should be a valid dictionary", "dict_type"))

    for text_key in ("selfEvaluation", "skillContent"):
        if text_key in raw and not isinstance(raw[text_key], str):
            issues.append(_issue(text_key, "Input should be a valid string", "string_type"))

    return issues


def load_and_validate_file(file_path: Path) -> tuple[dict[str, Any] | None, list[dict[str, str]], str | None]:
    if _has_module("backend.cli.schema"):
        from backend.cli.schema import load_and_validate_resume_file  # type: ignore[import-not-found]

        raw_data, _model, issues, err = load_and_validate_resume_file(file_path)
        return raw_data, [i.to_dict() for i in issues], err

    if not file_path.exists():
        return None, [], f"File not found: {file_path}"
    if not file_path.is_file():
        return None, [], f"Not a regular file: {file_path}"
    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [], f"Failed to read file {file_path}: {exc}"
    try:
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return (
            None,
            [_issue(f"<json>:line {exc.lineno} col {exc.colno}", exc.msg, "json_invalid")],
            f"Invalid JSON syntax at line {exc.lineno}, column {exc.colno}: {exc.msg}",
        )
    issues = validate_resume_dict_stdlib(raw_data)
    if issues:
        return raw_data if isinstance(raw_data, dict) else None, issues, None
    return raw_data, [], None


def _run_chrome_capture(
    *,
    html_content: str,
    output_path: Path,
    mode: str,
    width: int = 794,
    height: int = 1123,
    timeout: float = 30.0,
) -> bytes:
    chrome_bin = find_chrome_executable()
    if chrome_bin is None:
        raise LocalToolError(
            "Google Chrome or Chromium was not found. On machines without Chrome, export HTML (-o resume.html) "
            "and print to PDF from any browser, or run 'handoff' to open in Web.",
            code="chrome_not_found",
            extra={
                "output": str(output_path),
                "fallback_hint": "Use '-o resume.html' for zero-dependency browser preview & Print-to-PDF.",
            },
        )

    out_name = "resume.pdf" if mode == "pdf" else "resume.png"
    magic = b"%PDF-" if mode == "pdf" else b"\x89PNG\r\n\x1a\n"
    chrome_args = (
        ["--no-pdf-header-footer", "--print-to-pdf={out}"]
        if mode == "pdf"
        else ["--hide-scrollbars", f"--window-size={width},{height}", "--screenshot={out}"]
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        tmp_html = tmp_path / "resume.html"
        tmp_out = tmp_path / out_name
        tmp_html.write_text(html_content, encoding="utf-8")

        cmd = [
            str(chrome_bin),
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            *[arg.format(out=tmp_out) for arg in chrome_args],
            str(tmp_html),
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise LocalToolError(f"Headless Chrome timed out after {timeout}s", code="chrome_timeout") from exc

        if not tmp_out.is_file() or tmp_out.stat().st_size == 0:
            err = res.stderr.decode("utf-8", errors="replace").strip() or f"No {out_name} generated"
            raise LocalToolError(f"Headless Chrome failed: {err}", code="chrome_export_failed")

        raw_bytes = tmp_out.read_bytes()
        if not raw_bytes.startswith(magic):
            raise LocalToolError(f"Headless Chrome generated invalid {mode.upper()} bytes", code="chrome_export_failed")
        _atomic_write_bytes(output_path, raw_bytes)
        return raw_bytes


def _delegate_render_if_available(args: argparse.Namespace) -> dict[str, Any] | None:
    cli_cmd = _find_cococv_cli()
    if not cli_cmd:
        return None
    has_pymupdf = _has_module("pymupdf") or _has_module("fitz")
    ext = Path(args.output).suffix.lower()
    if ext == ".html" and not args.png:
        return None
    if not has_pymupdf and (ext == ".png" or args.png):
        return None

    cmd = [
        *cli_cmd,
        "render",
        str(args.file),
        "-o",
        str(args.output),
        "--template",
        args.template,
        "--dpi",
        str(args.dpi),
        "--json",
    ]
    if args.engine:
        cmd.extend(["--engine", args.engine])
    if args.png:
        cmd.append("--png")
    if args.force:
        cmd.append("--force")
    if args.no_print_background:
        cmd.append("--no-print-background")

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        return None
    if proc.returncode != 0:
        err = payload.get("error") if isinstance(payload, dict) else {}
        err_code = str(err.get("code") or "")
        err_msg = str(err.get("message") or "Render failed")
        lower_msg = err_msg.lower()
        if (
            err_code in {"usage_error", "invalid_argument"}
            or "no such option" in lower_msg
            or "unsupported output extension" in lower_msg
        ):
            return None
        raise LocalToolError(
            err_msg,
            code=err_code or "render_failed",
            exit_code=proc.returncode,
            extra={k: v for k, v in payload.items() if k not in {"ok", "error"}} if isinstance(payload, dict) else {},
        )
    return payload


def cmd_env(args: argparse.Namespace) -> int:
    report = probe_environment()
    if args.json:
        _emit_json({"ok": True, "command": "env", **report})
    else:
        print(f"Python: {report['python']}")
        print(f"cococv CLI: {report['cococv_cli'] or 'not installed (using bundled stdlib script)'}")
        print(f"Chrome/Edge: {report['chrome'] or 'not found'}")
        print(f"XeLaTeX: {report['xelatex'] or 'not found'}")
        print(f"PyMuPDF: {'yes' if report['pymupdf'] else 'no'}")
        print(f"Recommended engine: {report['recommended_engine']}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    if not args.title.strip():
        raise LocalToolError("Title must not be empty.", code="invalid_title")
    output = Path(args.output)
    if output.exists() and not args.force:
        raise LocalToolError(
            f"Target file already exists: {output} (use --force to overwrite)",
            code="file_exists",
            extra={"command": "init", "output": str(output)},
        )
    skeleton = build_initial_resume(title=args.title)
    _atomic_write_bytes(output, (json.dumps(skeleton, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    if args.json:
        _emit_json({"ok": True, "command": "init", "output": str(output), "id": skeleton["id"], "title": skeleton["title"]})
    else:
        print(f"Initialized resume skeleton at {output} (id={skeleton['id']})")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    file_path = Path(args.file)
    raw_data, issues, err = load_and_validate_file(file_path)
    if err and not issues:
        raise LocalToolError(err, code="file_error", extra={"command": "validate", "valid": False, "file": str(file_path), "errors": []})
    if issues:
        raise LocalToolError(
            err or f"Validation failed with {len(issues)} error(s) in {file_path}",
            code="invalid_json" if err else "validation_failed",
            extra={"command": "validate", "valid": False, "file": str(file_path), "errors": issues},
        )
    assert raw_data is not None
    if args.json:
        _emit_json({"ok": True, "command": "validate", "valid": True, "file": str(file_path), "id": raw_data.get("id"), "errors": []})
    else:
        print(f"Valid ResumeData: {file_path} (id={raw_data.get('id')})")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    file_path = Path(args.file)
    output = Path(args.output)
    ext = output.suffix.lower()
    if ext not in {".html", ".pdf", ".png"}:
        raise LocalToolError(
            f"Unsupported output extension '{ext}': expected .html, .pdf, or .png",
            code="invalid_argument",
            extra={"command": "render", "input": str(file_path), "output": str(output)},
        )

    if output.exists() and not args.force:
        raise LocalToolError(
            f"Target file already exists: {output} (use --force to overwrite)",
            code="file_exists",
            extra={"command": "render", "input": str(file_path), "output": str(output)},
        )
    sidecar_png = output.with_name(f"{output.stem}-page-1.png")
    if args.png and ext != ".png" and sidecar_png.exists() and not args.force:
        raise LocalToolError(
            f"Target preview file already exists: {sidecar_png} (use --force to overwrite)",
            code="file_exists",
            extra={"command": "render", "input": str(file_path), "output": str(sidecar_png)},
        )

    raw_data, issues, err = load_and_validate_file(file_path)
    if err and not issues:
        raise LocalToolError(err, code="file_error", extra={"command": "render", "input": str(file_path), "output": str(output)})
    if issues:
        raise LocalToolError(
            err or f"Resume JSON validation failed with {len(issues)} error(s) in {file_path}",
            code="invalid_json" if err else "validation_failed",
            extra={"command": "render", "input": str(file_path), "output": str(output), "errors": issues},
        )
    assert raw_data is not None

    if ext == ".html":
        if args.engine == "latex":
            raise LocalToolError(
                "Cannot render HTML output using LaTeX engine. Use --engine html or omit --engine.",
                code="engine_mismatch",
                extra={"command": "render", "input": str(file_path), "output": str(output)},
            )
        resolved_engine = "html"
    else:
        if args.engine is not None:
            eng = args.engine.lower()
            if eng not in {"html", "latex"}:
                raise LocalToolError(f"Invalid engine '{args.engine}': expected 'html' or 'latex'.", code="invalid_engine")
            resolved_engine = eng
        else:
            resolved_engine = "html" if args.template in HTML_TEMPLATES else "latex"

    delegated = _delegate_render_if_available(args)
    if delegated is not None:
        if args.json:
            _emit_json(delegated)
        else:
            print(f"Rendered {ext[1:].upper()} to {output} ({delegated.get('bytes')} bytes, engine={delegated.get('engine')})")
            if delegated.get("pages"):
                print(f"PNG previews ({len(delegated['pages'])}): {', '.join(delegated['pages'])}")
        return 0

    if resolved_engine == "latex":
        raise LocalToolError(
            "Local XeLaTeX CLI compilation requires both 'cococv' CLI and 'xelatex' installed locally.",
            code="xelatex_not_found",
            extra={
                "command": "render",
                "input": str(file_path),
                "output": str(output),
                "fallback_hint": "Switch to '--template asu-tech' for local HTML output or run 'handoff' for Web cloud LaTeX.",
            },
        )

    warnings: list[str] = []
    if (ext == ".html" and args.png) or ext in {".pdf", ".png"}:
        if find_chrome_executable() is None:
            raise LocalToolError(
                "Google Chrome or Chromium was not found for PDF/PNG rendering. Export '-o resume.html' (works with zero dependencies) "
                "or run 'handoff' to render in Web.",
                code="chrome_not_found",
                extra={
                    "command": "render",
                    "input": str(file_path),
                    "output": str(output),
                    "fallback_hint": "Run with '-o resume.html' for self-contained browser preview & Cmd+P PDF export.",
                },
            )

    html_content = html_generator.generate_html_resume(
        raw_data,
        template=args.template,
        print_background=not args.no_print_background,
    )
    page_paths: list[Path] = []
    if ext == ".html":
        html_bytes = html_content.encode("utf-8")
        _atomic_write_bytes(output, html_bytes)
        result_bytes = len(html_bytes)
        if args.png:
            _run_chrome_capture(html_content=html_content, output_path=sidecar_png, mode="png")
            page_paths = [sidecar_png]
            warnings.append("PyMuPDF 未安装：已通过 Chrome 截取首页预览图")
    elif ext == ".pdf":
        pdf_bytes = _run_chrome_capture(html_content=html_content, output_path=output, mode="pdf")
        result_bytes = len(pdf_bytes)
        if args.png:
            _run_chrome_capture(html_content=html_content, output_path=sidecar_png, mode="png")
            page_paths = [sidecar_png]
            warnings.append("PyMuPDF 未安装：已通过 Chrome 截取首页预览图")
    else:
        png_bytes = _run_chrome_capture(html_content=html_content, output_path=output, mode="png")
        result_bytes = len(png_bytes)
        page_paths = [output]
        warnings.append("PyMuPDF 未安装：已通过 Chrome 截取首页预览图")

    if args.json:
        payload: dict[str, Any] = {
            "ok": True,
            "command": "render",
            "input": str(file_path),
            "output": str(output),
            "engine": "html",
            "template": args.template,
            "bytes": result_bytes,
            "offline": True,
            "warnings": warnings,
        }
        if page_paths:
            payload["pages"] = [str(p) for p in page_paths]
            payload["page_count"] = len(page_paths)
        _emit_json(payload)
    else:
        for warn in warnings:
            sys.stderr.write(f"Warning: {warn}\n")
        print(f"Rendered {ext[1:].upper()} to {output} ({result_bytes} bytes, engine=html, offline=True)")
        if page_paths:
            print(f"PNG previews ({len(page_paths)}): {', '.join(str(p) for p in page_paths)}")
    return 0


def _normalize_share_url(api_url: str | None) -> str:
    raw = (api_url or os.getenv("RESUME_AGENT_API_URL") or DEFAULT_WEB_API_URL).strip().rstrip("/")
    if not (raw.startswith("http://") or raw.startswith("https://")):
        raise LocalToolError(f"Invalid API base URL '{raw}'", code="invalid_api_url")
    if raw.endswith("/api/resume/share") or raw.endswith("/api/fastapi/proxy/resume/share"):
        return raw
    if raw.endswith("/api/fastapi/proxy/api/resume/share"):
        return raw[: -len("/api/resume/share")] + "/resume/share"
    if raw.endswith("/api/fastapi/proxy") or raw.endswith("/api"):
        return f"{raw}/resume/share"
    if raw.endswith("/api/resume"):
        return f"{raw}/share"
    return f"{raw}/api/resume/share"


def cmd_handoff(args: argparse.Namespace) -> int:
    file_path = Path(args.file)
    raw_data, issues, err = load_and_validate_file(file_path)
    if err and not issues:
        raise LocalToolError(err, code="file_error", extra={"command": "handoff", "file": str(file_path)})
    if issues:
        raise LocalToolError(
            err or f"Validation failed with {len(issues)} error(s) in {file_path}",
            code="invalid_json" if err else "validation_failed",
            extra={"command": "handoff", "file": str(file_path), "errors": issues},
        )
    assert raw_data is not None

    endpoint = _normalize_share_url(args.api_url)
    basic_name = str((raw_data.get("basic") or {}).get("name") or "").strip()
    title_name = str(raw_data.get("title") or "").strip()
    resolved_name = (args.name or "").strip() or basic_name or title_name or "未命名简历"

    req_payload = json.dumps(
        {
            "resume_data": raw_data,
            "resume_name": resolved_name,
            "expire_minutes": args.ttl_minutes,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        endpoint,
        data=req_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20.0) as resp:
            body_bytes = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip() or f"HTTP {exc.code}"
        raise LocalToolError(f"HTTP {exc.code}: {detail}", code=f"http_{exc.code}") from exc
    except urllib.error.URLError as exc:
        raise LocalToolError(f"Network error contacting {endpoint}: {exc.reason}", code="network_error") from exc

    try:
        body = json.loads(body_bytes.decode("utf-8"))
    except ValueError as exc:
        raise LocalToolError("Remote endpoint returned invalid JSON.", code="invalid_remote_payload") from exc

    if not isinstance(body, dict) or not body.get("share_url"):
        raise LocalToolError("Remote endpoint response missing 'share_url'.", code="invalid_remote_payload")

    if args.json:
        _emit_json(
            {
                "ok": True,
                "command": "handoff",
                "share_id": body.get("share_id"),
                "share_url": body.get("share_url"),
                "expires_at": body.get("expires_at"),
                "ttl_minutes": args.ttl_minutes,
            }
        )
    else:
        print(f"Web handoff URL (expires in {args.ttl_minutes} min): {body['share_url']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="Emit JSON output on stdout.")

    parser = argparse.ArgumentParser(prog="cococv_local.py", description="Standalone CocoCV skill helper")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_env = sub.add_parser("env", parents=[common], help="Inspect local environment capabilities.")
    p_env.set_defaults(func=cmd_env)

    p_init = sub.add_parser("init", parents=[common], help="Create a ResumeData JSON skeleton.")
    p_init.add_argument("-o", "--output", default="resume.json")
    p_init.add_argument("--title", default="我的简历")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_val = sub.add_parser("validate", parents=[common], help="Validate a ResumeData JSON file.")
    p_val.add_argument("file")
    p_val.set_defaults(func=cmd_validate)

    p_ren = sub.add_parser("render", parents=[common], help="Render ResumeData JSON locally.")
    p_ren.add_argument("file")
    p_ren.add_argument("-o", "--output", required=True)
    p_ren.add_argument("--template", default="asu-tech")
    p_ren.add_argument("--engine", default=None)
    p_ren.add_argument("--png", "--images", action="store_true")
    p_ren.add_argument("--dpi", type=int, default=150)
    p_ren.add_argument("--no-print-background", action="store_true")
    p_ren.add_argument("--force", action="store_true")
    p_ren.set_defaults(func=cmd_render)

    p_hand = sub.add_parser("handoff", parents=[common], help="Create an opt-in temporary Web continuation link.")
    p_hand.add_argument("file")
    p_hand.add_argument("--api-url", default=None)
    p_hand.add_argument("--name", default=None)
    p_hand.add_argument("--ttl-minutes", type=int, default=60)
    p_hand.set_defaults(func=cmd_handoff)

    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    json_mode = "--json" in raw_argv
    parser = build_parser()
    try:
        args = parser.parse_args(raw_argv)
        return int(args.func(args))
    except LocalToolError as exc:
        if json_mode:
            payload: dict[str, Any] = {"ok": False, **exc.extra, "error": {"code": exc.code, "message": exc.message}}
            _emit_json(payload)
        else:
            sys.stderr.write(f"Error: {exc.message}\n")
        return exc.exit_code
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2


if __name__ == "__main__":
    raise SystemExit(main())
