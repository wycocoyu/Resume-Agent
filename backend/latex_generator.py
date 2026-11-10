"""
LaTeX 简历生成模块
将简历 JSON 转换为 LaTeX 代码，并编译为 PDF
"""
import os
import re
import subprocess
import tempfile
import shutil
import time
import hashlib
import json
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Dict, Any, List
from io import BytesIO
from datetime import date

from .latex_utils import escape_latex, normalize_resume_data, resolve_xelatex_executable, subprocess_env_with_xelatex_bin
from .latex_sections import (
    SECTION_GENERATORS,
    DEFAULT_SECTION_ORDER,
    WORK_EXPERIENCE_LOGO_PREFIX,
    generate_section_custom,
)
from .company_logos import download_logos_to_dir
from .school_logos import download_school_logos_to_dir, is_school_logo_latex_supported


def _safe_float(value: Any, default: float, min_value: float, max_value: float) -> float:
    """读取并限制浮点参数范围，避免异常值破坏排版。"""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, num))


def _normalize_latex_font_size(value: Any) -> int:
    """返回合法的 LaTeX 基础字号；只接受 8–12 范围内的整数。"""
    if isinstance(value, bool):
        return 11

    if isinstance(value, int):
        font_size = value
    elif isinstance(value, float) and value.is_integer():
        font_size = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        font_size = int(value.strip())
    else:
        return 11

    return font_size if 8 <= font_size <= 12 else 11


def _px_to_pt(px: float) -> float:
    """
    将 UI 的“px 调整量”映射到 TeX pt。
    为保证 0.5 步进在 PDF 预览中可感知，这里使用增强系数。
    """
    return px * 4.0


def _compute_age_from_birth_date(birth_date: str) -> int | None:
    """
    支持 YYYY-MM / YYYY-MM-DD，返回年龄（整岁）。
    """
    if not isinstance(birth_date, str):
        return None
    raw = birth_date.strip()
    if not raw:
        return None
    try:
        parts = raw.split("-")
        if len(parts) < 2:
            return None
        y = int(parts[0])
        m = int(parts[1])
        d = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 1
        if m < 1 or m > 12 or d < 1 or d > 31:
            return None
        today = date.today()
        age = today.year - y
        if (today.month, today.day) < (m, d):
            age -= 1
        if age < 0 or age > 120:
            return None
        return age
    except Exception:
        return None


def _format_birth_contact_text(birth_date_raw: str, birth_display_mode: str) -> str:
    """根据展示模式生成联系栏中的生日/年龄文案（未转义）。"""
    raw = birth_date_raw.strip()
    if not raw:
        return ""
    if birth_display_mode == "age":
        age = _compute_age_from_birth_date(raw)
        return f"{age}岁" if age is not None else raw
    return raw


def _compact_contact_token(text: str) -> str:
    return re.sub(r"[\s：:·\-]+", "", text or "").lower()


def _collapse_duplicate_contact_segments(status: str) -> str:
    """折叠「21 岁 · 21 岁」等重复片段，避免历史脏数据原样输出。"""
    status = (status or "").strip()
    if not status:
        return ""
    parts = [p.strip() for p in re.split(r"\s*·\s*", status) if p.strip()]
    if len(parts) < 2:
        return status
    compact_parts = [_compact_contact_token(p) for p in parts]
    if len(set(compact_parts)) == 1:
        return parts[0]
    deduped: list[str] = []
    for i, part in enumerate(parts):
        if i > 0 and compact_parts[i] == compact_parts[i - 1]:
            continue
        deduped.append(part)
    return " · ".join(deduped)


_AGE_ONLY_RE = re.compile(r"^(?:年龄[：:]\s*)?\d{1,3}\s*岁$")
_DATE_ONLY_RE = re.compile(r"^\d{4}[-/]\d{2}(?:[-/]\d{2})?$")


def _status_is_pure_age_or_date(status: str) -> bool:
    """状态字段是否仅为年龄（如 '21 岁'）或生日年月（如 '2005-03'），是则直接替换。"""
    s = (status or "").strip()
    return bool(_AGE_ONLY_RE.match(s) or _DATE_ONLY_RE.match(s))


def _status_duplicates_birth(status: str, birth_text: str, birth_date_raw: str) -> bool:
    """状态字段已包含与 birthDate 相同的年龄/年月时，不再重复拼接。"""
    status = (status or "").strip()
    if not status or not birth_text:
        return False
    compact_status = _compact_contact_token(status)
    for token in (birth_text, birth_date_raw.strip()):
        if token and _compact_contact_token(token) in compact_status:
            return True
    birth_digits = re.sub(r"\D", "", _compact_contact_token(birth_text))
    status_digits = re.sub(r"\D", "", compact_status)
    if birth_digits and birth_digits == status_digits:
        return True
    return False


def _merge_contact_status_with_birth(
    employement_status: str,
    birth_date_raw: str,
    birth_display_mode: str,
) -> str:
    status = _collapse_duplicate_contact_segments(employement_status or "")
    if not birth_date_raw.strip():
        return status
    birth_text = _format_birth_contact_text(birth_date_raw, birth_display_mode)
    if not birth_text:
        return status
    # 状态字段只是一个年龄/日期时，直接用最新计算值替换（避免跨年后出现「20 岁 · 21 岁」）
    if status and _status_is_pure_age_or_date(status):
        return birth_text
    if _status_duplicates_birth(status, birth_text, birth_date_raw):
        return birth_text or status
    if status:
        return f"{status} · {birth_text}"
    return birth_text


def _summarize_latex_error(error_msg: str, max_chars: int = 2000) -> str:
    """提取更有可读性的 LaTeX 错误摘要（优先返回 ! 错误附近上下文）。"""
    if not error_msg:
        return ""

    lines = error_msg.splitlines()
    if not lines:
        return error_msg[:max_chars]

    # 优先抓取第一个 "!" 错误块附近上下文
    bang_idx = next((i for i, line in enumerate(lines) if line.lstrip().startswith("!")), None)
    if bang_idx is not None:
        start = max(0, bang_idx - 3)
        end = min(len(lines), bang_idx + 14)
        snippet = "\n".join(lines[start:end]).strip()
        return snippet[:max_chars]

    # 次优：抓取包含 Error 的关键行
    key_lines = [line for line in lines if "Error" in line or "error" in line or "Undefined" in line]
    if key_lines:
        snippet = "\n".join(key_lines[:25]).strip()
        return snippet[:max_chars]

    # 兜底：返回尾部日志，通常最接近失败原因
    tail = "\n".join(lines[-40:]).strip()
    return tail[:max_chars]


def _detect_xelatex_image_ext(raw_bytes: bytes) -> str | None:
    """Strict magic-byte whitelist for XeLaTeX / xdvipdfmx (PNG, JPEG, PDF only; blocks WebP/SVG/HTML)."""
    if not isinstance(raw_bytes, (bytes, bytearray)) or len(raw_bytes) < 4:
        return None
    head = bytes(raw_bytes[:16])
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith(b"%PDF-"):
        return ".pdf"
    return None


def _is_xelatex_supported_image(data_or_path: bytes | Path) -> bool:
    """Return True iff bytes or file header match PNG, JPEG, or PDF magic bytes."""
    if isinstance(data_or_path, Path):
        try:
            with data_or_path.open("rb") as fh:
                head = fh.read(16)
        except OSError:
            return False
        return _detect_xelatex_image_ext(head) is not None
    return _detect_xelatex_image_ext(data_or_path) is not None


def _strip_photo_block_from_latex(latex_content: str) -> str:
    stripped_lines = []
    for line in latex_content.splitlines():
        if "{photo}" in line:
            continue
        if r"\vspace{-1.1\baselineskip}" in line:
            continue
        if r"\vspace{-0.8ex}" in line:
            continue
        stripped_lines.append(line)
    return "\n".join(stripped_lines)


def _append_warning(warnings_out: List[str] | None, message: str) -> None:
    if warnings_out is not None and message not in warnings_out:
        warnings_out.append(message)


def _download_user_photo_to_dir(
    photo_url: str,
    temp_dir: str,
    *,
    offline: bool = False,
) -> str | None:
    """
    下载用户照片到临时目录，固定命名为 photo.<ext>
    仅接受 http(s)://（严禁读取服务器本地路径），offline=True 或非支持魔数返回 None。
    """
    if offline:
        return None
    if not photo_url or not isinstance(photo_url, str):
        return None
    if not (photo_url.startswith("http://") or photo_url.startswith("https://")):
        return None

    try:
        logos_dir = Path(temp_dir) / "logos"
        logos_dir.mkdir(parents=True, exist_ok=True)
        staging_path = logos_dir / "photo.download"
        from .company_logos import _download_url_to_path

        _download_url_to_path(photo_url, staging_path, timeout=15.0)
        raw_bytes = staging_path.read_bytes()
        staging_path.unlink(missing_ok=True)

        detected_ext = _detect_xelatex_image_ext(raw_bytes)
        if not detected_ext:
            return None

        local_name = f"photo{detected_ext}"
        (logos_dir / local_name).write_bytes(raw_bytes)
        return local_name
    except Exception:
        return None


def _sanitize_resume_for_latex(
    resume_data: Dict[str, Any],
    *,
    offline: bool = False,
    warnings_out: List[str] | None = None,
) -> Dict[str, Any]:
    """
    LaTeX 与前端图片支持范围不同：前端可显示 svg/webp，但 XeLaTeX 不支持这些学校 Logo。
    在生成 LaTeX 前先降级掉不支持的学校 Logo，避免编译阶段引用不存在的资源。
    """
    sanitized = json.loads(json.dumps(resume_data))
    education = sanitized.get("education") or []
    if isinstance(education, list):
        for item in education:
            if not isinstance(item, dict):
                continue
            logo_key = item.get("logo")
            if logo_key and not is_school_logo_latex_supported(logo_key, offline=offline):
                _append_warning(
                    warnings_out,
                    f"学校 Logo 未命中或格式不受 LaTeX 支持，已自动跳过: {logo_key}",
                )
                item.pop("logo", None)
                item.pop("logoSize", None)
    return sanitized


def _sanitize_resume_for_available_assets(
    resume_data: Dict[str, Any],
    logo_map: Dict[int, str] | None = None,
    school_logo_map: Dict[int, str] | None = None,
    work_logo_map: Dict[int, str] | None = None,
) -> Dict[str, Any]:
    """
    只保留当前已成功落到临时目录的 Logo 引用，避免 LaTeX includegraphics 指向不存在文件。

    每个带 Logo 的板块都必须在这里出现——漏一个板块，那个板块缺图时就会留下
    悬空的 includegraphics，xdvipdfmx 直接致命失败、整份 PDF 导不出。
    """
    sanitized = json.loads(json.dumps(resume_data))
    logo_map = logo_map or {}
    school_logo_map = school_logo_map or {}
    work_logo_map = work_logo_map or {}

    def _strip_unavailable(items: Any, available: Dict[int, str]) -> None:
        if not isinstance(items, list):
            return
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            if item.get("logo") and idx not in available:
                item.pop("logo", None)
                item.pop("logoSize", None)

    _strip_unavailable(sanitized.get("internships") or [], logo_map)
    _strip_unavailable(sanitized.get("workExperience") or [], work_logo_map)

    education = sanitized.get("education") or []
    if isinstance(education, list):
        for idx, item in enumerate(education):
            if not isinstance(item, dict):
                continue
            if item.get("logo") and idx not in school_logo_map:
                item.pop("logo", None)
                item.pop("logoSize", None)

    return sanitized


def json_to_latex(
    resume_data: Dict[str, Any],
    section_order: List[str] | None = None,
    *,
    offline: bool = False,
    warnings_out: List[str] | None = None,
) -> str:
    """
    将简历 JSON 转换为 LaTeX 代码
    支持中文和英文字段名，支持自定义 section 顺序
    
    参数:
        resume_data: 简历数据字典（中文或英文字段名）
        section_order: 自定义 section 顺序列表（None 回退默认顺序，[] 表示不输出任何正文模块）
    
    返回:
        LaTeX 代码字符串
    """
    resume_data = _sanitize_resume_for_latex(
        resume_data,
        offline=offline,
        warnings_out=warnings_out,
    )

    """标准化 JSON：先尝试通用方法，失败则降级到固定映射"""
    try:
        from backend.json_normalizer import normalize_resume_json
        resume_data = normalize_resume_json(resume_data)
    except Exception:
        resume_data = normalize_resume_data(resume_data)
    
    """获取 LaTeX 模板目录路径"""
    current_dir = Path(__file__).resolve().parent
    root_dir = current_dir.parent
    latex_template_dir = root_dir / "latex-resume-template"
    
    """构建 LaTeX 文档"""
    latex_content = []
    
    # 获取全局设置
    global_settings = resume_data.get('globalSettings') or {}
    
    # 字体大小设置（8 - 12pt，步进 1pt）
    font_size = _normalize_latex_font_size(global_settings.get('latexFontSize', 11))
    
    # 页面边距设置
    margin_setting = global_settings.get('latexMargin', 'standard')
    margin_map = {
        'tight': '0.25in',
        'compact': '0.3in',
        'standard': '0.4in',
        'relaxed': '0.5in',
        'wide': '0.6in',
    }
    margin = margin_map.get(margin_setting, '0.4in')
    
    # 行间距设置 - 默认 1.0 与原始模板保持一致
    line_spacing = global_settings.get('latexLineSpacing', 1.0)
    if not isinstance(line_spacing, (int, float)) or line_spacing < 0.8 or line_spacing > 2.0:
        line_spacing = 1.0

    # 头部三段间距（px，可为负）
    header_top_gap_px = _safe_float(global_settings.get('latexHeaderTopGapPx'), 0.0, -80.0, 80.0)
    header_name_contact_gap_px = _safe_float(global_settings.get('latexHeaderNameContactGapPx'), 0.0, -80.0, 80.0)
    header_bottom_gap_px = _safe_float(global_settings.get('latexHeaderBottomGapPx'), 0.0, -80.0, 80.0)
    
    """文档头部"""
    latex_content.append(r"% !TEX TS-program = xelatex")
    latex_content.append(r"% !TEX encoding = UTF-8 Unicode")
    latex_content.append(r'% !Mode:: "TeX:UTF-8"')
    latex_content.append("")
    # 使用动态字体大小
    latex_content.append(f"\\documentclass[{font_size}pt]{{resume}}")
    """使用中文字体配置"""
    latex_content.append(r"\usepackage{zh_CN-Adobefonts_external}")
    latex_content.append(r"\usepackage{linespacing_fix}")
    latex_content.append(r"\usepackage{cite}")
    latex_content.append(r"\usepackage{graphicx}")
    latex_content.append(r"\graphicspath{{logos/}}")
    """确保中文字体正确加载和 Unicode 支持"""
    latex_content.append(r'\XeTeXlinebreaklocale "zh"')
    latex_content.append(r"\XeTeXlinebreakskip = 0pt plus 1pt")
    """强制使用 Unicode 编码"""
    latex_content.append(r'\XeTeXinputencoding "utf8"')
    latex_content.append(r"\pdfstringdefDisableCommands{")
    latex_content.append(r"  \def\raisebox#1#2{#2}")
    latex_content.append(r"  \def\includegraphics#1#2{}")
    latex_content.append(r"  \def\fontsize#1#2{}")
    latex_content.append(r"  \def\selectfont{}")
    latex_content.append(r"  \def\hspace#1{}")
    latex_content.append(r"  \def\normalsize{}")
    latex_content.append(r"  \def\textendash{-}")
    latex_content.append(r"}")
    latex_content.append("")
    # 只有当用户明确设置了非默认值时才覆盖（保持与原始模板一致）
    # 原始模板默认: 11pt 字体, 0.4in 边距, 无 linespread 设置
    if margin_setting != 'standard':
        latex_content.append(f"\\geometry{{a4paper,left={margin},right={margin},top={margin},bottom={margin},nohead}}")
    if line_spacing != 1.0:
        latex_content.append(f"\\linespread{{{line_spacing}}}")
    
    latex_content.append("")
    latex_content.append(r"\begin{document}")
    latex_content.append(r"\pagenumbering{gobble}")
    latex_content.append("")

    if abs(header_top_gap_px) > 0.01:
        latex_content.append(f"\\vspace*{{{_px_to_pt(header_top_gap_px):.2f}pt}}")

    """姓名/联系信息"""
    name = resume_data.get('name') or '姓名'
    contact = resume_data.get('contact') or {}
    phone = escape_latex(contact.get('phone') or '')
    email = escape_latex(contact.get('email') or '')
    """求职意向：优先从 objective 获取，其次从 contact.role 获取"""
    role = escape_latex(resume_data.get('objective') or contact.get('role') or '')
    location = escape_latex(contact.get('location') or '')
    birth_date_raw = resume_data.get('birthDate') or resume_data.get('birth_date') or ''
    birth_display_mode = (global_settings.get('birthDateDisplayMode') or 'birthDate') if isinstance(global_settings, dict) else 'birthDate'
    raw_employement_status = resume_data.get('employementStatus') or ''
    if isinstance(birth_date_raw, str):
        merged_status = _merge_contact_status_with_birth(
            raw_employement_status,
            birth_date_raw,
            birth_display_mode,
        )
    else:
        merged_status = raw_employement_status
    employement_status = escape_latex(merged_status)
    blog = resume_data.get('blog') or ''  # 不 escape，保留原始 URL 给 \href

    # 每字段显示样式 fieldLabelModes（icon/text/none）；缺失回退老简历全局 contactLabelMode，再回退 'icon'。
    # 注：PDF 无 emoji 字体，icon 模式等价「仅值」（与 none 一致），仅 text 模式加中文前缀。
    field_label_modes = global_settings.get('fieldLabelModes') if isinstance(global_settings, dict) else None
    field_label_modes = field_label_modes if isinstance(field_label_modes, dict) else {}
    legacy_label_mode = (global_settings.get('contactLabelMode') if isinstance(global_settings, dict) else None) or 'icon'

    def _field_mode(key):
        mode = field_label_modes.get(key)
        return mode if mode in ('icon', 'text', 'none') else legacy_label_mode

    def _label(key, prefix, value):
        """text 模式加中文前缀；icon/none 仅值（PDF 不渲染 emoji）"""
        if not value:
            return ''
        if _field_mode(key) == 'text':
            return f'{prefix}{value}'
        return value

    # 根据每字段模式追加 label 前缀
    phone = _label('phone', '电话：', phone)
    email = _label('email', '邮箱：', email)
    role = _label('title', '求职意向：', role)
    location = _label('location', '地点：', location)
    # employment_status 已含年龄/状态，label 跟随 birthDate 字段模式与 birthDateDisplayMode
    if employement_status:
        if _field_mode('birthDate') == 'text':
            if birth_display_mode == 'age':
                employement_status = f'年龄：{employement_status}'
            else:
                employement_status = f'生日：{employement_status}'

    # 工作年限：\contactInfo 是固定 5 参宏（resume.cls），加参数要改模板、波及所有 PDF，
    # 故并入第 5 位（同为个人属性），用宏内同款 \textperiodcentered 分隔，视觉一致
    work_years = _label('workYears', '工作年限：', escape_latex(resume_data.get('workYears') or ''))
    if work_years:
        employement_status = (
            rf'{employement_status} \textperiodcentered\ {work_years}'
            if employement_status
            else work_years
        )

    # 有照片时，右侧叠加照片，不改变姓名/联系信息的居中布局
    if resume_data.get("photo"):
        photo_offset_x = _safe_float(resume_data.get("photoOffsetX"), 0.0, -6.0, 6.0)
        photo_offset_y = _safe_float(resume_data.get("photoOffsetY"), -2.0, -6.0, 6.0)
        photo_width_cm = _safe_float(resume_data.get("photoWidthCm"), 3.0, 1.2, 6.0)
        photo_height_cm = _safe_float(resume_data.get("photoHeightCm"), 3.0, 1.2, 8.0)
        # 右对齐锚点：在图片后追加空白才能改变右边界；x 正值代表向右偏移（与前端输入一致）。
        x_shift_cm = -photo_offset_x
        latex_content.append(
            f"\\noindent\\makebox[\\textwidth][r]{{\\raisebox{{{photo_offset_y:.2f}cm}}[0pt][0pt]{{\\includegraphics[width={photo_width_cm:.2f}cm,height={photo_height_cm:.2f}cm,keepaspectratio]{{photo}}}}\\hspace*{{{x_shift_cm:.2f}cm}}}}"
        )
        # 覆盖浮层不应拉开标题区高度
        latex_content.append(r"\vspace{-1.1\baselineskip}")

    latex_content.append(f"\\name{{{escape_latex(name)}}}")
    latex_content.append("")
    # 姓名与联系信息间距调节：保留有照片时的默认压缩，再叠加用户设置
    if resume_data.get("photo"):
        latex_content.append(r"\vspace{-0.8ex}")
    if abs(header_name_contact_gap_px) > 0.01:
        latex_content.append(f"\\vspace{{{_px_to_pt(header_name_contact_gap_px):.2f}pt}}")
    """contactInfo 格式: {phone}{email}{role}{location}{status}"""
    latex_content.append(f"\\contactInfo{{{phone}}}{{{email}}}{{{role}}}{{{location}}}{{{employement_status}}}")
    if blog:
        # 博客/GitHub 三档：icon（默认，复用开源经历的 \faGithub）/ text（博客：前缀）/ none（仅 URL）
        blog_mode = _field_mode('blog')
        if blog_mode == 'text':
            blog_prefix = '博客：'
        elif blog_mode == 'none':
            blog_prefix = ''
        else:
            blog_prefix = r'\faGithub\hspace{0.3em}'
        latex_content.append(f"\\blogLine{{{blog_prefix}}}{{{blog}}}")
    if abs(header_bottom_gap_px) > 0.01:
        latex_content.append(f"\\vspace{{{_px_to_pt(header_bottom_gap_px):.2f}pt}}")
    latex_content.append("")
    
    """获取自定义模块标题"""
    section_titles = resume_data.get('sectionTitles') or {}
    
    """按顺序生成各 section（严格区分 None 与空列表 []）"""
    order = section_order if section_order is not None else DEFAULT_SECTION_ORDER
    for section_id in order:
        generator = SECTION_GENERATORS.get(section_id)
        if generator:
            latex_content.extend(generator(resume_data, section_titles))
        elif isinstance(section_id, str) and section_id.startswith('custom_'):
            latex_content.extend(generate_section_custom(resume_data, section_id, section_titles))
    
    """文档结尾"""
    latex_content.append(r"\end{document}")
    
    return "\n".join(latex_content)


def _filter_supported_logos_in_dir(
    items: list,
    asset_map: Dict[int, str],
    temp_dir: str,
    kind_label: str,
    warnings_out: List[str] | None,
) -> Dict[int, str]:
    """Verify magic bytes on each downloaded/copied logo; strip unsupported files and emit warnings."""
    logos_dir = Path(temp_dir) / "logos"
    verified: Dict[int, str] = {}
    unsupported_indices: set[int] = set()

    for idx, fname in list(asset_map.items()):
        fpath = logos_dir / fname
        if _is_xelatex_supported_image(fpath):
            verified[idx] = fname
        else:
            fpath.unlink(missing_ok=True)
            unsupported_indices.add(idx)
            logo_key = items[idx].get("logo") if idx < len(items) and isinstance(items[idx], dict) else fname
            _append_warning(
                warnings_out,
                f"{kind_label} Logo 图片格式不受 XeLaTeX 支持（仅支持 PNG/JPEG/PDF），已自动跳过: {logo_key}",
            )

    for idx, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        logo_key = item.get("logo")
        if logo_key and idx not in verified and idx not in unsupported_indices:
            _append_warning(
                warnings_out,
                f"{kind_label} Logo 未命中，已自动跳过: {logo_key}",
            )

    return verified


def compile_latex_to_pdf(
    latex_content: str,
    template_dir: Path,
    resume_data: Dict[str, Any] = None,
    *,
    section_order: List[str] | None = None,
    offline: bool = False,
    local_photo_bytes: tuple[str, bytes] | None = None,
    warnings_out: List[str] | None = None,
) -> BytesIO:
    """
    编译 LaTeX 代码为 PDF

    参数:
        latex_content: LaTeX 代码字符串
        template_dir: LaTeX 模板目录（包含 resume.cls 等文件）
        resume_data: 简历数据（用于下载 Logo 等资源）
        section_order: 显式传入的模块顺序（用于缺图二次重生成时保持 [] 空列表语义）
        offline: True 时严格禁止任何网络请求
        local_photo_bytes: CLI 边界已校验通过的本地/base64 头像字节 (ext, bytes)
        warnings_out: 可选告警收集列表

    返回:
        PDF 文件的 BytesIO 对象
    """
    template_dir = Path(template_dir)
    if not template_dir.is_dir() or not (template_dir / "resume.cls").is_file():
        raise RuntimeError(f"LaTeX 模板目录无效或缺少 resume.cls: {template_dir}")

    """创建临时目录"""
    temp_dir = tempfile.mkdtemp()

    try:
        # 复制所有必要的模板文件
        template_files = [
            'resume.cls', 'fontawesome.sty', 'linespacing_fix.sty',
            'zh_CN-Adobefonts_external.sty', 'zh_CN-Adobefonts_internal.sty'
        ]
        for file_name in template_files:
            src_file = template_dir / file_name
            if src_file.exists():
                dest_file = Path(temp_dir) / file_name
                shutil.copy2(src_file, dest_file)
            else:
                raise RuntimeError(f"LaTeX 模板缺少必要文件: {src_file}")

        # 复制字体目录（如果存在）
        fonts_dir = template_dir / 'fonts'
        if fonts_dir.exists():
            shutil.copytree(fonts_dir, Path(temp_dir) / 'fonts', dirs_exist_ok=True)

        # 下载/复制公司与学校 Logo 到临时目录
        local_photo = None
        logo_map: Dict[int, str] = {}
        school_logo_map: Dict[int, str] = {}
        work_logo_map: Dict[int, str] = {}
        if resume_data:
            internships = resume_data.get('internships') or []
            if any(isinstance(it, dict) and it.get('logo') for it in internships):
                logo_map = download_logos_to_dir(internships, temp_dir, offline=offline)
                logo_map = _filter_supported_logos_in_dir(
                    internships, logo_map, temp_dir, "实习经历", warnings_out
                )
                print(f"[Logo] 下载完成，共 {len(logo_map)} 个 Logo")
            work_experience = resume_data.get('workExperience') or []
            if any(isinstance(it, dict) and it.get('logo') for it in work_experience):
                work_logo_map = download_logos_to_dir(
                    work_experience,
                    temp_dir,
                    prefix=WORK_EXPERIENCE_LOGO_PREFIX,
                    offline=offline,
                )
                work_logo_map = _filter_supported_logos_in_dir(
                    work_experience, work_logo_map, temp_dir, "工作经历", warnings_out
                )
                print(f"[Logo] 工作经历下载完成，共 {len(work_logo_map)} 个 Logo")
            education = resume_data.get('education') or []
            if any(isinstance(ed, dict) and ed.get('logo') for ed in education):
                school_logo_map = download_school_logos_to_dir(
                    education, temp_dir, offline=offline
                )
                school_logo_map = _filter_supported_logos_in_dir(
                    education, school_logo_map, temp_dir, "教育经历", warnings_out
                )
                print(f"[SchoolLogo] 下载完成，共 {len(school_logo_map)} 个 Logo")

            sanitized_for_assets = _sanitize_resume_for_available_assets(
                resume_data,
                logo_map=logo_map,
                school_logo_map=school_logo_map,
                work_logo_map=work_logo_map,
            )
            if sanitized_for_assets != resume_data:
                effective_order = (
                    section_order
                    if section_order is not None
                    else sanitized_for_assets.get("sectionOrder")
                )
                if local_photo_bytes is not None and not sanitized_for_assets.get("photo"):
                    sanitized_for_assets["photo"] = "__cli_local_photo__"
                latex_content = json_to_latex(
                    sanitized_for_assets,
                    effective_order,
                    offline=offline,
                    warnings_out=warnings_out,
                )

            photo_url = resume_data.get("photo")
            if local_photo_bytes is not None:
                _, raw_photo_bytes = local_photo_bytes
                detected_ext = _detect_xelatex_image_ext(raw_photo_bytes)
                if not detected_ext:
                    _append_warning(
                        warnings_out,
                        "本地头像格式不受 XeLaTeX 支持（仅支持 PNG/JPEG/PDF），已自动降级为无照片渲染",
                    )
                    latex_content = _strip_photo_block_from_latex(latex_content)
                else:
                    logos_dir = Path(temp_dir) / "logos"
                    logos_dir.mkdir(parents=True, exist_ok=True)
                    local_photo = f"photo{detected_ext}"
                    (logos_dir / local_photo).write_bytes(raw_photo_bytes)
            elif photo_url:
                if offline and isinstance(photo_url, str) and (
                    photo_url.startswith("http://") or photo_url.startswith("https://")
                ):
                    _append_warning(
                        warnings_out,
                        f"离线模式已跳过远程头像下载，已降级为无照片渲染: {photo_url}",
                    )
                    local_photo = None
                else:
                    local_photo = _download_user_photo_to_dir(
                        photo_url, temp_dir, offline=offline
                    )
                    if not local_photo:
                        _append_warning(
                            warnings_out,
                            f"头像资源不可用或格式不支持，已降级为无照片渲染: {photo_url}",
                        )
                if not local_photo:
                    print("[Photo] 下载失败，已自动降级为无照片渲染")
                    latex_content = _strip_photo_block_from_latex(latex_content)

        # 写入 LaTeX 文件
        tex_file = Path(temp_dir) / 'resume.tex'
        tex_file.write_text(latex_content, encoding='utf-8')

        # 检查 xelatex 是否可用（Windows 下额外搜索 MiKTeX 常见路径）
        xelatex_path = resolve_xelatex_executable()
        if not xelatex_path:
            # 提供安装说明
            install_hint = """
LaTeX (XeLaTeX) 未安装。请运行以下命令安装：

通过 Homebrew 安装 BasicTeX（推荐，较小）：
  brew install --cask basictex
  然后运行: eval "$(/usr/libexec/path_helper)"

或安装完整版 MacTeX：
  brew install --cask mactex

安装完成后，需要重新启动终端或运行:
  eval "$(/usr/libexec/path_helper)"
"""
            raise RuntimeError(f"xelatex 命令未找到。{install_hint}")
        
        # 使用 xelatex 编译
        compile_cmd = [
            xelatex_path,
            '-interaction=nonstopmode',
            '-output-directory', temp_dir,
            str(tex_file)
        ]

        # 只编译一次；Windows MiKTeX 首次运行可能按需装包，给足时间
        _latex_env = subprocess_env_with_xelatex_bin(xelatex_path)
        result = subprocess.run(
            compile_cmd,
            cwd=temp_dir,
            capture_output=True,
            text=True,
            timeout=180,
            env=_latex_env,
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout
            error_summary = _summarize_latex_error(error_msg)
            print(f"LaTeX 编译失败: {error_summary}")
            raise RuntimeError(f"LaTeX 编译失败: {error_summary}")

        """读取生成的 PDF"""
        pdf_file = Path(temp_dir) / 'resume.pdf'
        if not pdf_file.exists():
            raise RuntimeError("PDF 文件未生成")

        # 读取 PDF
        pdf_bytes = pdf_file.read_bytes()
        print(f"PDF 生成成功，大小: {len(pdf_bytes)} 字节")

        pdf_io = BytesIO(pdf_bytes)
        pdf_io.seek(0)

        return pdf_io

    finally:
        """清理临时目录"""
        shutil.rmtree(temp_dir, ignore_errors=True)


"""
PDF 缓存（内存缓存，最多保留 50 个）
"""
_pdf_cache: Dict[str, bytes] = {}
_pdf_cache_order: List[str] = []
_PDF_CACHE_MAX_SIZE = 50


def _get_cache_key(resume_data: Dict[str, Any], section_order: List[str] | None = None) -> str:
    """生成缓存键（严格区分 section_order=None 与 section_order=[]）"""
    content = json.dumps(
        {"resume_data": resume_data, "section_order": section_order},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.md5(content.encode()).hexdigest()


def render_pdf_from_resume_latex(
    resume_data: Dict[str, Any],
    section_order: List[str] | None = None,
) -> BytesIO:
    """
    将简历 JSON 渲染为 PDF（使用 LaTeX）
    支持内容缓存，相同内容直接返回缓存
    
    参数:
        resume_data: 简历数据字典
        section_order: 自定义 section 顺序列表
    
    返回:
        PDF 文件的 BytesIO 对象
    """
    total_start = time.time()
    resume_data = _sanitize_resume_for_latex(resume_data)
    
    """检查缓存"""
    cache_key = _get_cache_key(resume_data, section_order)
    if cache_key in _pdf_cache:
        cache_time = time.time() - total_start
        print(f"[性能] 缓存命中! 耗时: {cache_time*1000:.0f}ms")
        return BytesIO(_pdf_cache[cache_key])
    
    """获取模板目录"""
    current_dir = Path(__file__).resolve().parent
    root_dir = current_dir.parent
    template_dir = root_dir / "latex-resume-template"
    
    if not template_dir.exists():
        raise RuntimeError(f"LaTeX 模板目录不存在: {template_dir}")
    
    """转换为 LaTeX"""
    latex_start = time.time()
    latex_content = json_to_latex(resume_data, section_order)
    latex_time = time.time() - latex_start
    print(f"[性能] JSON 转 LaTeX: {latex_time*1000:.0f}ms")
    
    """编译为 PDF"""
    compile_start = time.time()
    pdf_io = compile_latex_to_pdf(
        latex_content,
        template_dir,
        resume_data=resume_data,
        section_order=section_order,
    )
    compile_time = time.time() - compile_start
    print(f"[性能] LaTeX 编译 PDF: {compile_time*1000:.0f}ms")
    
    """写入缓存"""
    pdf_bytes = pdf_io.getvalue()
    if len(_pdf_cache) >= _PDF_CACHE_MAX_SIZE:
        """删除最旧的缓存"""
        oldest_key = _pdf_cache_order.pop(0)
        _pdf_cache.pop(oldest_key, None)
    _pdf_cache[cache_key] = pdf_bytes
    _pdf_cache_order.append(cache_key)
    print(f"[性能] 已缓存 PDF (缓存数: {len(_pdf_cache)})")
    
    total_time = time.time() - total_start
    print(f"[性能] PDF 生成总耗时: {total_time*1000:.0f}ms")
    
    return pdf_io
