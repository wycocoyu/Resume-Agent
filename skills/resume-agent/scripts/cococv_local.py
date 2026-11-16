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
import html
from html.parser import HTMLParser
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
import xml.etree.ElementTree as ET
import zipfile

sys.dont_write_bytecode = True
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import html_generator  # noqa: E402

HTML_TEMPLATES = {"asu-tech", "html-classic"} | {f"asu-{i:02d}" for i in range(1, 19)}
DEFAULT_WEB_API_URL = "https://cococv.cn"

TEMPLATE_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "asu-tech",
        "name": "ASu 极客单栏",
        "category": "单栏技术",
        "engine": "html",
        "pages": "1页（可顺延）",
        "recommended": True,
        "description": "默认推荐。高密度单栏技术简历，蓝色标题线、浅灰经历条与多级 STAR 列表，零依赖本地即出。",
        "best_for": "后端 / 前端 / AI / 算法 / 全栈技术岗（应届与社招通用）",
    },
    {
        "id": "html-classic",
        "name": "经典模板（HTML）",
        "category": "通用单栏",
        "engine": "html",
        "pages": "1-2页",
        "recommended": False,
        "description": "简洁明快的基础 HTML 标准单栏模板，适合日常快速预览与打印。",
        "best_for": "通用研发 / 职能 / 测试与基础投递",
    },
    {
        "id": "asu-01",
        "name": "经典蓝线",
        "category": "单栏",
        "engine": "html",
        "pages": "1页",
        "recommended": False,
        "description": "深蓝横线标题与单栏紧凑排版，干净克制。",
        "best_for": "后端 / 工程 / 常规校招单页简历",
    },
    {
        "id": "asu-02",
        "name": "蓝底色块条",
        "category": "单栏",
        "engine": "html",
        "pages": "1页",
        "recommended": False,
        "description": "蓝底反白标题色块条，分区界限分明，重点一眼可见。",
        "best_for": "产品 / 运营 / 全栈工程师单页投递",
    },
    {
        "id": "asu-03",
        "name": "时间轴",
        "category": "单栏",
        "engine": "html",
        "pages": "1页",
        "recommended": False,
        "description": "左侧经历时间轴连接线，突出连续成长与阶段跃迁。",
        "best_for": "有多段实习或清晰晋升轨迹的候选人",
    },
    {
        "id": "asu-04",
        "name": "深蓝顶幅",
        "category": "单栏",
        "engine": "html",
        "pages": "1页",
        "recommended": False,
        "description": "深蓝通栏顶部信息横幅，视觉辨识度高。",
        "best_for": "偏产品、解决方案、商务或前端设计方向",
    },
    {
        "id": "asu-05",
        "name": "灰调侧栏",
        "category": "侧栏双列",
        "engine": "html",
        "pages": "1页",
        "recommended": False,
        "description": "左侧浅灰栏放基础信息、技能与奖项，右侧主栏聚焦教育与经历。",
        "best_for": "经历中等偏少、需要双列平衡留白的校招或转行候选人",
    },
    {
        "id": "asu-06",
        "name": "纯黑时间轴双页",
        "category": "双页",
        "engine": "html",
        "pages": "2页",
        "recommended": False,
        "description": "沉稳黑灰时间轴双页版式，克制不花哨。",
        "best_for": "资深工程师 / Tech Lead / 多段完整工作履历",
    },
    {
        "id": "asu-07",
        "name": "右侧蓝轨",
        "category": "单栏",
        "engine": "html",
        "pages": "1页",
        "recommended": False,
        "description": "右侧纵向蓝色装饰轨，单栏结构别致清新。",
        "best_for": "前端 / 交互 / 创意开发单页简历",
    },
    {
        "id": "asu-08",
        "name": "色块双栏双页",
        "category": "双栏双页",
        "engine": "html",
        "pages": "2页",
        "recommended": False,
        "description": "双栏结构搭配双页充实布局，模块划分明晰。",
        "best_for": "项目与技术栈跨度大的全栈 / 架构岗位",
    },
    {
        "id": "asu-09",
        "name": "卡片分区双页",
        "category": "双页",
        "engine": "html",
        "pages": "2页",
        "recommended": False,
        "description": "模块采用轻微卡片边框包围，层次分明耐读。",
        "best_for": "项目较多、需要清晰区块隔离的中高级研发",
    },
    {
        "id": "asu-10",
        "name": "丝带标签",
        "category": "单栏",
        "engine": "html",
        "pages": "1页",
        "recommended": False,
        "description": "丝带切角标题微标，版面活泼有节奏。",
        "best_for": "校招产品 / 运营 / 新媒体 / 校园骨干",
    },
    {
        "id": "asu-11",
        "name": "衬线分割头",
        "category": "单栏",
        "engine": "html",
        "pages": "1页",
        "recommended": False,
        "description": "衬线字体搭配双线分割页眉，书卷气与专业感兼备。",
        "best_for": "算法研究 / 咨询分析 / 外企及学术导向岗位",
    },
    {
        "id": "asu-12",
        "name": "居中作品集双页",
        "category": "双页",
        "engine": "html",
        "pages": "2页",
        "recommended": False,
        "description": "头部居中对齐，强化代表作与项目链接展示。",
        "best_for": "开源作者 / 独立开发者 / 作品集丰富候选人",
    },
    {
        "id": "asu-13",
        "name": "纯黑紧凑侧栏",
        "category": "侧栏双列",
        "engine": "html",
        "pages": "1页",
        "recommended": False,
        "description": "高对比深黑左侧栏配合紧凑主栏，硬核利落。",
        "best_for": "安全 / 系统 / 客户端 / 工具链工程师",
    },
    {
        "id": "asu-14",
        "name": "蓝线紧凑双栏双页",
        "category": "双栏双页",
        "engine": "html",
        "pages": "2页",
        "recommended": False,
        "description": "蓝色主题紧凑双栏双页，兼顾信息量与阅读引导。",
        "best_for": "5年以上研发 / 数据分析 / 平台工程",
    },
    {
        "id": "asu-15",
        "name": "色块现代序号",
        "category": "单栏",
        "engine": "html",
        "pages": "1页",
        "recommended": False,
        "description": "章节标题带圆圈数字序号微标，结构节奏清晰。",
        "best_for": "数据分析 / AI 应用 / 产品工程单页简历",
    },
    {
        "id": "asu-16",
        "name": "超高密度双栏双页",
        "category": "双栏双页",
        "engine": "html",
        "pages": "2页",
        "recommended": False,
        "description": "极高密度双栏双页技术排版，承载海量项目细节。",
        "best_for": "资深全栈 / 架构师 / 多段大厂核心项目经历",
    },
    {
        "id": "asu-17",
        "name": "纯黑学术风双页",
        "category": "双页学术",
        "engine": "html",
        "pages": "2页",
        "recommended": False,
        "description": "纯黑严谨学术排版，黑白打印清晰友好。",
        "best_for": "科研 / 读研 / 实验室算法与论文成果展示",
    },
    {
        "id": "asu-18",
        "name": "蓝线现代紧凑双页",
        "category": "双页",
        "engine": "html",
        "pages": "2页",
        "recommended": False,
        "description": "极简蓝线现代双页，适合条理清晰的长履历。",
        "best_for": "3-5年以上研发 / 技术管理 / 跨团队项目经历",
    },
    {
        "id": "default",
        "name": "经典模板（LaTeX）",
        "category": "经典 LaTeX",
        "engine": "latex",
        "pages": "1-2页",
        "recommended": False,
        "description": "CocoCV 原生 XeLaTeX 经典单栏版式（默认建议通过 handoff 走网页端远程编译，仅本机同时具备 cococv CLI 与 xelatex 时可本地直出）。",
        "best_for": "偏好传统 LaTeX 学术/程序员排版的用户",
    },
)

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
        "recommended_latex_route": "local" if (cli_cmd and xelatex_bin) else "remote_handoff",
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
        print(
            f"LaTeX (default) route: {report['recommended_latex_route']} "
            "(local requires both cococv CLI and xelatex)"
        )
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
                "fallback_hint": (
                    "Run 'handoff' first for remote Web cloud XeLaTeX compilation (https://cococv.cn), "
                    "or switch to '--template asu-tech' for local HTML output."
                ),
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


class _HtmlTextExtractor(HTMLParser):
    """Lightweight stdlib HTML-to-readable-text extractor for local resume import."""

    _BLOCK_TAGS = {
        "p", "div", "section", "article", "header", "footer",
        "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "br", "blockquote", "pre",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low = tag.lower()
        if low in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return
        if low in self._BLOCK_TAGS:
            self._parts.append("\n")
        if low == "li":
            self._parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        low = tag.lower()
        if low in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if self._skip_depth > 0:
            return
        if low in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
        cleaned: list[str] = []
        for line in lines:
            if line:
                cleaned.append(line)
            elif cleaned and cleaned[-1] != "":
                cleaned.append("")
        return "\n".join(cleaned).strip()


def _extract_docx_text(path: Path) -> str:
    """Extract readable paragraphs and tables from a .docx archive using stdlib only."""
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise LocalToolError(
            f"Invalid .docx file: {path}",
            code="invalid_docx",
            extra={"command": "read-source", "file": str(path)},
        ) from exc

    def _p_text(elem: ET.Element) -> str:
        chunks: list[str] = []
        for node in elem.iter():
            tag = node.tag.rsplit("}", 1)[-1]
            if tag == "t" and node.text:
                chunks.append(node.text)
            elif tag == "tab":
                chunks.append(" ")
            elif tag in {"br", "cr"}:
                chunks.append("\n")
        return "".join(chunks).strip()

    def _walk(elem: ET.Element, out: list[str]) -> None:
        for child in elem:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                txt = _p_text(child)
                if txt:
                    out.append(txt)
            elif tag == "tbl":
                for row in child:
                    if row.tag.rsplit("}", 1)[-1] != "tr":
                        continue
                    cells: list[str] = []
                    for cell in row:
                        if cell.tag.rsplit("}", 1)[-1] != "tc":
                            continue
                        cell_parts = [_p_text(p) for p in cell.iter() if p.tag.rsplit("}", 1)[-1] == "p"]
                        joined = " / ".join(p for p in cell_parts if p)
                        if joined:
                            cells.append(joined)
                    if cells:
                        out.append(" | ".join(cells))
            else:
                _walk(child, out)

    sections: list[str] = []
    with zf:
        names = set(zf.namelist())
        ordered = sorted(n for n in names if re.fullmatch(r"word/header\d*\.xml", n))
        if "word/document.xml" in names:
            ordered.append("word/document.xml")
        ordered.extend(sorted(n for n in names if re.fullmatch(r"word/footer\d*\.xml", n)))
        if "word/document.xml" not in names:
            raise LocalToolError(
                f"Corrupted .docx archive (missing word/document.xml): {path}",
                code="invalid_docx",
                extra={"command": "read-source", "file": str(path)},
            )
        for member in ordered:
            try:
                root = ET.fromstring(zf.read(member))
            except ET.ParseError as exc:
                raise LocalToolError(
                    f"Malformed XML in {member} of {path}: {exc}",
                    code="invalid_docx",
                    extra={"command": "read-source", "file": str(path)},
                ) from exc
            lines: list[str] = []
            _walk(root, lines)
            if lines:
                sections.append("\n".join(lines))
    return "\n\n".join(sections).strip()


def _read_text_with_fallback(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "utf-16", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_pdf_local(path: Path, pages_dir: Path | None, max_pages: int = 6) -> dict[str, Any]:
    """Extract PDF text cleanly with optional fallback page PNG export for visual reading."""
    text_parts: list[str] = []
    page_images: list[str] = []
    method: str | None = None
    page_count: int | None = None

    fitz_mod = None
    for mod_name in ("pymupdf", "fitz"):
        if _has_module(mod_name):
            try:
                fitz_mod = __import__(mod_name)
                break
            except Exception:
                fitz_mod = None

    if fitz_mod is not None:
        doc = fitz_mod.open(str(path))
        try:
            page_count = doc.page_count
            for idx, page in enumerate(doc):
                txt = (page.get_text("text") or "").strip()
                if txt:
                    text_parts.append(f"--- Page {idx + 1} ---\n{txt}")
            method = "pymupdf"
            total_text = "\n\n".join(text_parts).strip()
            if pages_dir is not None or len(total_text) < 40:
                out_dir = pages_dir or Path(tempfile.mkdtemp(prefix="cococv_pdf_pages_"))
                out_dir.mkdir(parents=True, exist_ok=True)
                for idx in range(min(doc.page_count, max_pages)):
                    pix = doc[idx].get_pixmap(dpi=150)
                    img_path = out_dir / f"{path.stem}-page-{idx + 1}.png"
                    pix.save(str(img_path))
                    page_images.append(str(img_path))
        finally:
            doc.close()
        return {
            "method": method,
            "page_count": page_count,
            "text": "\n\n".join(text_parts).strip(),
            "page_images": page_images,
        }

    if _has_module("pypdf"):
        try:
            import pypdf  # type: ignore

            reader = pypdf.PdfReader(str(path))
            page_count = len(reader.pages)
            for idx, page in enumerate(reader.pages):
                txt = (page.extract_text() or "").strip()
                if txt:
                    text_parts.append(f"--- Page {idx + 1} ---\n{txt}")
            method = "pypdf"
        except Exception:
            text_parts = []

    if not text_parts:
        pdftotext_bin = shutil.which("pdftotext")
        if pdftotext_bin:
            proc = subprocess.run([pdftotext_bin, str(path), "-"], capture_output=True, text=True, check=False)
            if proc.returncode == 0 and proc.stdout.strip():
                method = "pdftotext"
                text_parts = [proc.stdout.strip()]

    total_text = "\n\n".join(text_parts).strip()
    if (pages_dir is not None or len(total_text) < 40) and not page_images:
        pdftoppm_bin = shutil.which("pdftoppm")
        if pdftoppm_bin:
            out_dir = pages_dir or Path(tempfile.mkdtemp(prefix="cococv_pdf_pages_"))
            out_dir.mkdir(parents=True, exist_ok=True)
            prefix = out_dir / f"{path.stem}-page"
            subprocess.run(
                [pdftoppm_bin, "-png", "-r", "150", "-l", str(max_pages), str(path), str(prefix)],
                capture_output=True,
                check=False,
            )
            page_images = [str(p) for p in sorted(out_dir.glob(f"{path.stem}-page*.png"))]

    return {
        "method": method,
        "page_count": page_count,
        "text": total_text,
        "page_images": page_images,
    }


def cmd_read_source(args: argparse.Namespace) -> int:
    source = Path(args.file).expanduser()
    if not source.is_file():
        raise LocalToolError(
            f"Resume source file not found: {source}",
            code="file_not_found",
            extra={"command": "read-source", "file": str(source)},
        )

    ext = source.suffix.lower()
    size_bytes = source.stat().st_size
    max_chars = max(1000, int(args.max_chars))
    result: dict[str, Any] = {
        "ok": True,
        "command": "read-source",
        "file": str(source.resolve()),
        "ext": ext,
        "bytes": size_bytes,
    }

    if ext == ".json":
        text = _read_text_with_fallback(source)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LocalToolError(
                f"Invalid JSON in {source}: {exc.msg}",
                code="invalid_json",
                extra={"command": "read-source", "file": str(source)},
            ) from exc
        is_resume_data = isinstance(parsed, dict) and bool({"basic", "education", "projects"} & set(parsed))
        result.update(
            {
                "format": "json",
                "readable_text": True,
                "is_resume_data": is_resume_data,
                "validation_errors": validate_resume_dict_stdlib(parsed) if is_resume_data else [],
                "data": parsed,
            }
        )
    elif ext in {".md", ".markdown", ".txt", ".tex", ".yaml", ".yml", ".csv"}:
        text = _read_text_with_fallback(source).strip()
        truncated = len(text) > max_chars
        result.update(
            {
                "format": ext.lstrip("."),
                "readable_text": bool(text),
                "total_chars": len(text),
                "truncated": truncated,
                "text": text[:max_chars],
            }
        )
    elif ext in {".html", ".htm"}:
        raw_html = _read_text_with_fallback(source)
        parser = _HtmlTextExtractor()
        parser.feed(raw_html)
        parser.close()
        text = parser.text()
        truncated = len(text) > max_chars
        result.update(
            {
                "format": "html",
                "readable_text": bool(text),
                "total_chars": len(text),
                "truncated": truncated,
                "text": text[:max_chars],
            }
        )
    elif ext == ".docx":
        text = _extract_docx_text(source)
        truncated = len(text) > max_chars
        result.update(
            {
                "format": "docx",
                "method": "stdlib-zipfile",
                "readable_text": bool(text),
                "total_chars": len(text),
                "truncated": truncated,
                "text": text[:max_chars],
            }
        )
    elif ext == ".pdf":
        pages_dir = Path(args.pages_dir).expanduser() if args.pages_dir else None
        pdf_info = _extract_pdf_local(source, pages_dir=pages_dir)
        text = str(pdf_info["text"] or "")
        truncated = len(text) > max_chars
        hint = None
        if not text and not pdf_info["page_images"]:
            hint = (
                "No local PDF text extractor (pymupdf/pypdf/pdftotext) found on this machine. "
                "Ask the user for a screenshot image, .docx, .md/.txt export, or paste the resume text."
            )
        elif len(text) < 40 and pdf_info["page_images"]:
            hint = "PDF appears scanned/image-only; inspect the generated page_images visually."
        result.update(
            {
                "format": "pdf",
                "method": pdf_info["method"],
                "page_count": pdf_info["page_count"],
                "readable_text": bool(text),
                "total_chars": len(text),
                "truncated": truncated,
                "text": text[:max_chars],
                "page_images": pdf_info["page_images"],
                "hint": hint,
            }
        )
    elif ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        result.update(
            {
                "format": "image",
                "readable_text": False,
                "is_image": True,
                "hint": "Inspect this image file directly using your multimodal vision / image read tool.",
            }
        )
    else:
        text = _read_text_with_fallback(source).strip()
        truncated = len(text) > max_chars
        result.update(
            {
                "format": ext.lstrip(".") or "unknown",
                "readable_text": bool(text),
                "total_chars": len(text),
                "truncated": truncated,
                "text": text[:max_chars],
            }
        )

    if args.json:
        _emit_json(result)
    else:
        print(f"Source: {result['file']} (format={result['format']}, bytes={size_bytes})")
        if result.get("text"):
            print(result["text"])
        elif result.get("page_images"):
            print("Page images:", ", ".join(result["page_images"]))
        if result.get("hint"):
            print(f"Hint: {result['hint']}")
    return 0


def build_sample_resume() -> dict[str, Any]:
    """Neutral fictional ResumeData used only for template gallery previews."""
    data = build_initial_resume(title="示例简历（林小北）")
    data["templateType"] = "html"
    data["templateId"] = "asu-tech"
    data["basic"] = {
        "name": "林小北",
        "title": "后端开发工程师",
        "email": "linxiaobei@example.com",
        "phone": "138-0000-0000",
        "location": "北京",
    }
    data["education"] = [
        {
            "id": "edu_sample_1",
            "school": "示例大学",
            "major": "计算机科学与技术",
            "degree": "本科",
            "startDate": "2021.09",
            "endDate": "2025.06",
            "description": "<p>专业排名前 10%，主修操作系统、计算机网络、分布式系统与数据库原理</p>",
            "visible": True,
        }
    ]
    data["experience"] = [
        {
            "id": "exp_sample_1",
            "company": "示例科技",
            "position": "后端开发实习生",
            "date": "2024.06 - 2024.10",
            "details": (
                '<ul class="custom-list">'
                "<li><p><strong>接口治理与缓存重构</strong>：主导订单查询链路热点缓存改造，P99 延迟由 180ms 降至 42ms</p></li>"
                "<li><p><strong>异步削峰</strong>：引入消息队列与幂等消费者，保障大促峰值期间零重复写入</p></li>"
                "</ul>"
            ),
            "visible": True,
            "companyLogo": "",
        }
    ]
    data["projects"] = [
        {
            "id": "proj_sample_1",
            "name": "分布式配置与灰度发布平台",
            "role": "核心开发者",
            "date": "2024.02 - 2024.05",
            "description": (
                '<ul class="custom-list">'
                "<li><p><strong>长轮询推送</strong>：基于 Go 与 Etcd Watch 实现配置秒级下发，支持版本回滚与命名空间隔离</p></li>"
                "<li><p><strong>可观测性</strong>：补充全链路指标与压测基准，单节点支撑 8k+ 并发连接</p></li>"
                "</ul>"
            ),
            "visible": True,
        }
    ]
    data["skillContent"] = (
        '<ul class="custom-list">'
        "<li><p><strong>语言与框架</strong>：Python（FastAPI）、Go、TypeScript，熟悉 REST 与流式接口设计</p></li>"
        "<li><p><strong>存储与中间件</strong>：MySQL 索引调优、Redis 缓存防护、Kafka 异步削峰、Docker 部署</p></li>"
        "</ul>"
    )
    for sec in data["menuSections"]:
        if sec["id"] in {"workExperience", "openSource", "awards", "selfEvaluation", "custom_research"}:
            sec["enabled"] = False
    return data


def build_template_gallery_html(resume_data: dict[str, Any]) -> str:
    """Build a standalone self-contained HTML page previewing all CocoCV templates."""
    cards: list[str] = []
    for item in TEMPLATE_CATALOG:
        tpl_id = item["id"]
        badge_rec = '<span class="pill pill-rec">默认推荐</span>' if item["recommended"] else ""
        if item["engine"] == "html":
            rendered = html_generator.generate_html_resume(resume_data, template=tpl_id, print_background=True)
            escaped = html.escape(rendered, quote=True)
            preview_block = (
                f'<div class="thumb-wrap">'
                f'<iframe class="thumb-frame" sandbox="" loading="lazy" title="{html.escape(tpl_id)}" '
                f'srcdoc="{escaped}"></iframe>'
                f"</div>"
            )
            action_btn = (
                f'<button type="button" class="btn-zoom" onclick="openPreview(\'{html.escape(tpl_id)}\')">放大预览</button>'
            )
        else:
            preview_block = (
                '<div class="thumb-wrap thumb-latex">'
                '<div><strong>XeLaTeX 原生模板</strong>'
                '<p>需本机安装 xelatex，或通过 <code>cococv handoff</code> 在网页端云端编译。</p>'
                '<p class="hint">经典学术/程序员单栏排版</p></div>'
                "</div>"
            )
            action_btn = '<span class="btn-muted">XeLaTeX 引擎</span>'

        cat_tag = item["category"]
        cards.append(
            f'<article class="card" data-category="{html.escape(cat_tag)}" data-id="{html.escape(tpl_id)}">'
            f"{preview_block}"
            f'<div class="card-body">'
            f'<div class="card-head"><code>{html.escape(tpl_id)}</code>{badge_rec}'
            f'<span class="pill">{html.escape(cat_tag)}</span><span class="pill">{html.escape(item["pages"])}</span></div>'
            f'<h3>{html.escape(item["name"])}</h3>'
            f'<p class="desc">{html.escape(item["description"])}</p>'
            f'<p class="best">适合：{html.escape(item["best_for"])}</p>'
            f'<div class="card-actions">{action_btn}'
            f'<button type="button" class="btn-copy" onclick="copyId(\'{html.escape(tpl_id)}\', this)">复制 ID</button>'
            f"</div></div></article>"
        )

    categories = ["全部", "单栏技术", "单栏", "侧栏双列", "双页", "双栏双页", "双页学术", "通用单栏", "经典 LaTeX"]
    filter_btns = "".join(
        f'<button type="button" class="filter-btn{" active" if c == "全部" else ""}" '
        f'onclick="filterCards(\'{html.escape(c)}\', this)">{html.escape(c)}</button>'
        for c in categories
    )
    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='UTF-8'/>"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'/>"
        "<title>CocoCV 内置 21 套简历模板可视化画廊</title>"
        "<style>"
        "*{box-sizing:border-box}"
        "body{margin:0;padding:24px;font-family:'PingFang SC','Microsoft YaHei',system-ui,sans-serif;background:#f4f6fb;color:#0f172a}"
        ".top{max-width:1380px;margin:0 auto 20px}"
        "h1{margin:0 0 8px;font-size:24px}"
        ".sub{margin:0 0 14px;color:#475569;font-size:14px}"
        ".filters{display:flex;flex-wrap:wrap;gap:8px}"
        ".filter-btn{border:1px solid #cbd5e1;background:#fff;border-radius:999px;padding:6px 14px;font-size:13px;cursor:pointer}"
        ".filter-btn.active{background:#2563eb;border-color:#2563eb;color:#fff;font-weight:600}"
        ".grid{max-width:1380px;margin:0 auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:18px}"
        ".card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;display:flex;flex-direction:column;box-shadow:0 2px 10px rgba(15,23,42,.05)}"
        ".thumb-wrap{position:relative;width:100%;height:390px;overflow:hidden;background:#eef2f7;border-bottom:1px solid #e2e8f0}"
        ".thumb-frame{width:794px;height:1123px;border:0;transform:scale(0.385);transform-origin:top left;background:#fff;pointer-events:none}"
        ".thumb-latex{display:flex;align-items:center;justify-content:center;padding:28px;text-align:center;color:#334155}"
        ".card-body{padding:14px 16px;display:flex;flex-direction:column;gap:6px;flex:1}"
        ".card-head{display:flex;flex-wrap:wrap;align-items:center;gap:6px}"
        "code{background:#eff6ff;color:#1d4ed8;padding:2px 8px;border-radius:6px;font-weight:700;font-size:13px}"
        ".pill{font-size:11px;background:#f1f5f9;color:#475569;padding:2px 8px;border-radius:999px}"
        ".pill-rec{background:#dcfce7;color:#15803d;font-weight:600}"
        "h3{margin:4px 0 0;font-size:16px}"
        ".desc{margin:0;font-size:13px;color:#475569;line-height:1.45}"
        ".best{margin:0;font-size:12px;color:#0f766e}"
        ".card-actions{margin-top:auto;padding-top:10px;display:flex;gap:8px;align-items:center}"
        "button{font-family:inherit}"
        ".btn-zoom,.btn-copy{border:1px solid #cbd5e1;background:#fff;border-radius:8px;padding:6px 12px;font-size:12px;cursor:pointer}"
        ".btn-zoom{background:#2563eb;border-color:#2563eb;color:#fff}"
        ".btn-muted{font-size:12px;color:#64748b}"
        ".modal{display:none;position:fixed;inset:0;background:rgba(15,23,42,.72);z-index:50;padding:24px;align-items:center;justify-content:center}"
        ".modal.open{display:flex}"
        ".modal-box{background:#fff;width:min(860px,96vw);height:92vh;border-radius:12px;display:flex;flex-direction:column;overflow:hidden}"
        ".modal-bar{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid #e2e8f0}"
        ".modal-frame{flex:1;width:100%;border:0;background:#fff}"
        "</style></head><body>"
        "<div class='top'><h1>CocoCV 21 套内置模板对比画廊</h1>"
        "<p class='sub'>选定模板 ID 后，直接告诉 AI「我选 asu-tech」或使用 <code>cococv render resume.json -o resume.pdf --template &lt;ID&gt;</code>。</p>"
        f"<div class='filters'>{filter_btns}</div></div>"
        f"<main class='grid'>{''.join(cards)}</main>"
        "<div id='modal' class='modal' onclick='if(event.target===this)closePreview()'>"
        "<div class='modal-box'><div class='modal-bar'><strong id='modal-title'></strong>"
        "<button type='button' class='btn-copy' onclick='closePreview()'>关闭</button></div>"
        "<iframe id='modal-frame' class='modal-frame' sandbox=''></iframe></div></div>"
        "<script>"
        "function filterCards(cat,btn){document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'));"
        "btn.classList.add('active');document.querySelectorAll('.card').forEach(c=>{"
        "c.style.display=(cat==='全部'||c.dataset.category===cat)?'flex':'none';});}"
        "function openPreview(id){var card=document.querySelector('.card[data-id=\"'+id+'\"]');"
        "var src=card.querySelector('iframe').getAttribute('srcdoc');"
        "document.getElementById('modal-title').textContent=id+' · '+card.querySelector('h3').textContent;"
        "document.getElementById('modal-frame').setAttribute('srcdoc',src);"
        "document.getElementById('modal').classList.add('open');}"
        "function closePreview(){document.getElementById('modal').classList.remove('open');}"
        "function copyId(id,btn){navigator.clipboard?.writeText(id);btn.textContent='已复制 '+id;setTimeout(()=>btn.textContent='复制 ID',1500);}"
        "</script></body></html>"
    )


def cmd_templates(args: argparse.Namespace) -> int:
    gallery_out = Path(args.gallery).expanduser() if args.gallery else None
    if gallery_out is not None:
        if gallery_out.exists() and not args.force:
            raise LocalToolError(
                f"Target file already exists: {gallery_out} (use --force to overwrite)",
                code="file_exists",
                extra={"command": "templates", "gallery": str(gallery_out)},
            )
        if args.resume:
            resume_path = Path(args.resume).expanduser()
            raw_data, issues, err = load_and_validate_file(resume_path)
            if err and not issues:
                raise LocalToolError(err, code="file_error", extra={"command": "templates", "file": str(resume_path)})
            if issues:
                raise LocalToolError(
                    err or f"Validation failed with {len(issues)} error(s) in {resume_path}",
                    code="invalid_json" if err else "validation_failed",
                    extra={"command": "templates", "file": str(resume_path), "errors": issues},
                )
            assert raw_data is not None
        else:
            raw_data = build_sample_resume()
        gallery_html = build_template_gallery_html(raw_data)
        _atomic_write_bytes(gallery_out, gallery_html.encode("utf-8"))

    items = list(TEMPLATE_CATALOG)
    if args.json:
        payload: dict[str, Any] = {
            "ok": True,
            "command": "templates",
            "count": len(items),
            "recommended_default": "asu-tech",
            "templates": items,
        }
        if gallery_out is not None:
            payload["gallery"] = str(gallery_out.resolve())
        _emit_json(payload)
    else:
        print(f"CocoCV built-in templates ({len(items)}, recommended default: asu-tech):")
        for item in items:
            mark = " *推荐*" if item["recommended"] else ""
            print(f"  - {item['id']:<12} [{item['category']} · {item['pages']}] {item['name']}{mark} — {item['best_for']}")
        if gallery_out is not None:
            print(f"Generated visual template gallery: {gallery_out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="Emit JSON output on stdout.")

    parser = argparse.ArgumentParser(prog="cococv_local.py", description="Standalone CocoCV skill helper")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_env = sub.add_parser("env", parents=[common], help="Inspect local environment capabilities.")
    p_env.set_defaults(func=cmd_env)

    p_tpl = sub.add_parser("templates", parents=[common], help="List built-in templates and optionally build a visual gallery HTML.")
    p_tpl.add_argument("--gallery", default=None, help="Output path for self-contained visual template gallery HTML.")
    p_tpl.add_argument("--resume", default=None, help="Optional ResumeData JSON to preview inside the gallery.")
    p_tpl.add_argument("--force", action="store_true")
    p_tpl.set_defaults(func=cmd_templates)

    p_read = sub.add_parser("read-source", parents=[common], help="Read a local resume file (JSON/MD/TXT/HTML/DOCX/PDF/Image) offline.")
    p_read.add_argument("file")
    p_read.add_argument("--pages-dir", default=None, help="Optional directory to save PDF page PNG renders for visual inspection.")
    p_read.add_argument("--max-chars", type=int, default=30000)
    p_read.set_defaults(func=cmd_read_source)

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
