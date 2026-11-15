"""Pure-Python self-contained HTML resume generator.

Matches the design and contract of Workspace v2 HTML templates:
- default / html-classic: classic clean layout
- asu-tech: ASu single-column high-density technology template with grey capsule badges
- asu-01 .. asu-18: 18 variant themes (single-column, sidebar, two-column, timeline, band, etc.)

Features:
- Zero external CDN dependencies (all SVGs, CSS, and fonts inline)
- Robust rich-text sanitization (XSS safe)
- @page { size: A4 portrait; margin: 0; } print styles with print-color-adjust
- Compatible with headless Chrome CDP PDF rendering
"""
from __future__ import annotations

import html
import re
from typing import Any

# Inlined standard SVG icons
SVG_ICONS = {
    "phone": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 '
        "0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 "
        "9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z\"></path></svg>"
    ),
    "mail": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<rect width="20" height="16" x="2" y="4" rx="2"></rect><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"></path></svg>'
    ),
    "mapPin": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"></path>'
        '<circle cx="12" cy="10" r="3"></circle></svg>'
    ),
    "globe": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="10"></circle><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"></path><path d="M2 12h20"></path></svg>'
    ),
    "github": (
        '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 '
        "0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 "
        '1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"></path><path d="M9 18c-4.51 2-5-2-7-2"></path></svg>'
    ),
}

ALLOWED_RICH_TAGS = {"b", "strong", "i", "em", "u", "ul", "ol", "li", "p", "br"}


def escape_html(text: Any) -> str:
    if text is None:
        return ""
    return html.escape(str(text), quote=True)


def sanitize_rich_text(content: str | None) -> str:
    """Sanitize rich text HTML to allowed subset while stripping script/iframe and events."""
    if not content:
        return ""
    text = str(content)
    # Strip dangerous container elements with their contents
    text = re.sub(r"<\s*(script|style|iframe|object|embed|noscript)\b[^>]*>[\s\S]*?<\s*/\s*\1\s*>", "", text, flags=re.I)
    text = re.sub(r"<\s*(script|style|iframe|object|embed|noscript)\b[^>]*\/?>", "", text, flags=re.I)
    # Remove inline event handlers
    text = re.sub(r"\son\w+\s*=\s*(?:'[^']*'|\"[^\"]*\"|[^\s>]+)", "", text, flags=re.I)
    # Remove javascript: URLs
    text = re.sub(r"javascript:[^\"'>\s]*", "", text, flags=re.I)

    # Filter tags
    def _replace_tag(match: re.Match) -> str:
        tag_str = match.group(0)
        tag_name = match.group(1).lower()
        if tag_name in ALLOWED_RICH_TAGS:
            if tag_name == "br":
                return "<br />"
            return f"</{tag_name}>" if tag_str.startswith("</") else f"<{tag_name}>"
        return ""

    return re.sub(r"</?([a-zA-Z0-9]+)\b[^>]*>", _replace_tag, text)


def is_valid_http_url(url: str | None) -> bool:
    if not url:
        return False
    trimmed = url.strip()
    return bool(re.match(r"^https?://", trimmed, re.I))


ASU_VARIANTS = {f"asu-{i:02d}" for i in range(1, 19)}


def _normalize_template_id(template: str) -> str:
    t = template.strip().lower()
    if t in ("default", "html-classic", "classic"):
        return "default"
    if t == "asu-tech":
        return "asu-tech"
    if t in ASU_VARIANTS:
        return t
    return "default"


def generate_html_resume(
    resume_data: dict[str, Any],
    template: str = "default",
    editable: bool = False,
    theme_color: str | None = None,
    print_background: bool = True,
) -> str:
    """Generate self-contained HTML resume from ResumeData dict."""
    norm_tpl = _normalize_template_id(template)
    basic = resume_data.get("basic") or {}
    global_settings = resume_data.get("globalSettings") or {}

    primary_color = theme_color or global_settings.get("themeColor")
    if not primary_color:
        if norm_tpl == "asu-tech":
            primary_color = "#2458b8"
        elif norm_tpl in ("asu-06", "asu-09", "asu-13", "asu-17"):
            primary_color = "#111827"
        else:
            primary_color = "#2563eb"

    # Candidate info
    name = basic.get("name") or "个人简历"
    title = basic.get("title") or ""
    phone = basic.get("phone") or ""
    email = basic.get("email") or ""
    location = basic.get("location") or basic.get("city") or ""
    website = basic.get("website") or ""
    github = basic.get("github") or ""
    photo = basic.get("photo") or ""

    # Contact items
    contact_items: list[tuple[str, str, str | None]] = []
    if phone:
        contact_items.append(("phone", phone, None))
    if email:
        contact_items.append(("mail", email, f"mailto:{email}"))
    if location:
        contact_items.append(("mapPin", location, None))
    if website:
        contact_items.append(("globe", website, website if is_valid_http_url(website) else None))
    if github:
        github_url = github if is_valid_http_url(github) else f"https://github.com/{github.lstrip('@')}"
        contact_items.append(("github", github, github_url))

    # Resolve sections and ordering
    menu_sections = resume_data.get("menuSections")
    section_order = resume_data.get("sectionOrder")

    section_configs = []
    if menu_sections and isinstance(menu_sections, list):
        for s in menu_sections:
            if s.get("enabled", True):
                section_configs.append({"id": s.get("id"), "title": s.get("title") or s.get("id")})
    elif section_order and isinstance(section_order, list):
        for s in section_order:
            if isinstance(s, dict):
                section_configs.append({"id": s.get("id"), "title": s.get("title") or s.get("id")})
            elif isinstance(s, str):
                section_configs.append({"id": s, "title": s})

    if not section_configs:
        section_configs = [
            {"id": "education", "title": "教育背景"},
            {"id": "workExperience", "title": "工作经历"},
            {"id": "experience", "title": "实习经历"},
            {"id": "projects", "title": "项目经历"},
            {"id": "openSource", "title": "开源经历"},
            {"id": "skills", "title": "专业技能"},
            {"id": "awards", "title": "荣誉奖项"},
            {"id": "selfEvaluation", "title": "自我评价"},
        ]

    # Render sections
    rendered_sections: list[str] = []
    sidebar_sections: list[str] = []
    main_sections: list[str] = []

    is_sidebar_tpl = norm_tpl in ("asu-05", "asu-13")
    is_two_column_tpl = norm_tpl in ("asu-08", "asu-14", "asu-16")

    for sec in section_configs:
        sec_id = sec.get("id", "")
        sec_title = sec.get("title", "")
        sec_html = _render_section(sec_id, sec_title, resume_data, norm_tpl, primary_color)
        if not sec_html:
            continue
        rendered_sections.append(sec_html)
        if is_sidebar_tpl:
            if sec_id in ("education", "skills", "awards", "selfEvaluation"):
                sidebar_sections.append(sec_html)
            else:
                main_sections.append(sec_html)
        elif is_two_column_tpl:
            if sec_id in ("education", "skills", "awards", "selfEvaluation", "openSource"):
                sidebar_sections.append(sec_html)
            else:
                main_sections.append(sec_html)

    # Stylesheet
    css = _build_styles(norm_tpl, primary_color, print_background)

    # Body layout
    if is_sidebar_tpl:
        body_content = f"""
        <div class="resume-sidebar-layout">
          <aside class="resume-sidebar">
            {_render_header(name, title, contact_items, photo, norm_tpl, is_sidebar=True)}
            {''.join(sidebar_sections)}
          </aside>
          <main class="resume-main">
            {''.join(main_sections)}
          </main>
        </div>
        """
    elif is_two_column_tpl:
        body_content = f"""
        {_render_header(name, title, contact_items, photo, norm_tpl)}
        <div class="resume-two-column-layout">
          <div class="resume-col-main">
            {''.join(main_sections)}
          </div>
          <div class="resume-col-sub">
            {''.join(sidebar_sections)}
          </div>
        </div>
        """
    else:
        body_content = f"""
        {_render_header(name, title, contact_items, photo, norm_tpl)}
        <div class="resume-single-column">
          {''.join(rendered_sections)}
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape_html(name)} - 简历</title>
  <style>
{css}
  </style>
</head>
<body class="template-{norm_tpl}">
  <div class="resume-paper">
    {body_content}
  </div>
</body>
</html>
"""


def _render_header(
    name: str,
    title: str,
    contact_items: list[tuple[str, str, str | None]],
    photo: str,
    template_id: str,
    is_sidebar: bool = False,
) -> str:
    contact_html_list = []
    for icon_key, text, link in contact_items:
        icon_svg = SVG_ICONS.get(icon_key, "")
        if link:
            item_body = f'<a href="{escape_html(link)}" target="_blank" rel="noopener noreferrer">{escape_html(text)}</a>'
        else:
            item_body = f"<span>{escape_html(text)}</span>"
        contact_html_list.append(f'<div class="contact-item">{icon_svg}{item_body}</div>')

    contact_html = "".join(contact_html_list)

    photo_html = ""
    if photo and (photo.startswith("data:") or is_valid_http_url(photo)):
        photo_src = escape_html(photo)
        photo_html = f'<div class="photo-slot"><img src="{photo_src}" alt="头像" /></div>'

    title_html = f'<div class="candidate-title">{escape_html(title)}</div>' if title else ""

    if template_id == "asu-04":
        return f"""
        <header class="resume-header header-banner">
          <div class="header-content">
            <h1 class="candidate-name">{escape_html(name)}</h1>
            {title_html}
            <div class="contact-row">{contact_html}</div>
          </div>
          {photo_html}
        </header>
        """

    return f"""
    <header class="resume-header">
      <div class="header-left">
        <h1 class="candidate-name">{escape_html(name)}</h1>
        {title_html}
        <div class="contact-row">{contact_html}</div>
      </div>
      {photo_html}
    </header>
    """


def _render_section(
    sec_id: str,
    title: str,
    resume_data: dict[str, Any],
    template_id: str,
    primary_color: str,
) -> str:
    if sec_id in ("basic", "header"):
        return ""

    if sec_id == "skills":
        content = resume_data.get("skillContent") or ""
        if not content:
            return ""
        return _wrap_section(title, f'<div class="rich-content skill-content">{sanitize_rich_text(content)}</div>', template_id)

    if sec_id == "selfEvaluation":
        content = resume_data.get("selfEvaluation") or ""
        if not content:
            return ""
        return _wrap_section(title, f'<div class="rich-content self-evaluation">{sanitize_rich_text(content)}</div>', template_id)

    if sec_id == "education":
        edus = resume_data.get("education") or []
        if not edus:
            return ""
        items_html = []
        for edu in edus:
            school = edu.get("school") or ""
            major = edu.get("major") or ""
            degree = edu.get("degree") or ""
            start = edu.get("startDate") or ""
            end = edu.get("endDate") or ""
            desc = edu.get("description") or ""

            date_str = f"{escape_html(start)} - {escape_html(end)}" if (start or end) else ""
            sub_parts = [p for p in (major, degree) if p]
            sub_str = " · ".join(escape_html(p) for p in sub_parts)

            items_html.append(
                _render_item_bar(
                    title=school,
                    subtitle=sub_str,
                    date_str=date_str,
                    description=desc,
                    template_id=template_id,
                )
            )
        return _wrap_section(title, "".join(items_html), template_id)

    if sec_id in ("experience", "workExperience"):
        exps = resume_data.get(sec_id) or []
        if not exps:
            return ""
        items_html = []
        for exp in exps:
            company = exp.get("company") or ""
            position = exp.get("position") or ""
            dept = exp.get("department") or ""
            start = exp.get("startDate") or ""
            end = exp.get("endDate") or ""
            desc = exp.get("description") or ""
            if not desc and exp.get("details"):
                desc = exp.get("details")

            date_str = f"{escape_html(start)} - {escape_html(end)}" if (start or end) else ""
            sub_parts = [p for p in (position, dept) if p]
            sub_str = " · ".join(escape_html(p) for p in sub_parts)

            items_html.append(
                _render_item_bar(
                    title=company,
                    subtitle=sub_str,
                    date_str=date_str,
                    description=desc,
                    template_id=template_id,
                )
            )
        return _wrap_section(title, "".join(items_html), template_id)

    if sec_id == "projects":
        projs = resume_data.get("projects") or []
        if not projs:
            return ""
        items_html = []
        for proj in projs:
            pname = proj.get("name") or ""
            role = proj.get("role") or ""
            start = proj.get("startDate") or ""
            end = proj.get("endDate") or ""
            desc = proj.get("description") or ""
            link = proj.get("projectLink") or proj.get("link") or ""

            date_str = f"{escape_html(start)} - {escape_html(end)}" if (start or end) else ""
            link_html = f' <a href="{escape_html(link)}" target="_blank" rel="noopener noreferrer" class="item-link">🔗</a>' if is_valid_http_url(link) else ""

            item_title = escape_html(pname) + link_html if link_html else pname
            items_html.append(
                _render_item_bar(
                    title=item_title,
                    subtitle=role,
                    date_str=date_str,
                    description=desc,
                    template_id=template_id,
                    is_title_html=bool(link_html),
                )
            )
        return _wrap_section(title, "".join(items_html), template_id)

    if sec_id == "openSource":
        oss = resume_data.get("openSource") or []
        if not oss:
            return ""
        items_html = []
        for os_entry in oss:
            pname = os_entry.get("project") or ""
            role = os_entry.get("role") or ""
            stars = os_entry.get("stars")
            start = os_entry.get("startDate") or ""
            end = os_entry.get("endDate") or ""
            desc = os_entry.get("description") or ""

            date_str = f"{escape_html(start)} - {escape_html(end)}" if (start or end) else ""
            sub_str = role
            if stars is not None:
                sub_str = f"{sub_str} (★ {stars})" if sub_str else f"★ {stars}"

            items_html.append(
                _render_item_bar(
                    title=pname,
                    subtitle=sub_str,
                    date_str=date_str,
                    description=desc,
                    template_id=template_id,
                )
            )
        return _wrap_section(title, "".join(items_html), template_id)

    if sec_id == "awards":
        awards = resume_data.get("awards") or []
        if not awards:
            return ""
        items_html = []
        for aw in awards:
            aname = aw.get("name") or ""
            adate = aw.get("date") or ""
            adesc = aw.get("description") or ""
            items_html.append(
                _render_item_bar(
                    title=aname,
                    subtitle="",
                    date_str=adate,
                    description=adesc,
                    template_id=template_id,
                )
            )
        return _wrap_section(title, "".join(items_html), template_id)

    # Custom sections
    custom_data = resume_data.get("customData") or {}
    custom_entries = custom_data.get(sec_id) or []
    if custom_entries and isinstance(custom_entries, list):
        items_html = []
        for c in custom_entries:
            ctitle = c.get("title") or ""
            csub = c.get("subtitle") or ""
            cdate = c.get("date") or ""
            cdesc = c.get("description") or ""
            items_html.append(
                _render_item_bar(
                    title=ctitle,
                    subtitle=csub,
                    date_str=cdate,
                    description=cdesc,
                    template_id=template_id,
                )
            )
        return _wrap_section(title, "".join(items_html), template_id)

    return ""


def _render_item_bar(
    title: str,
    subtitle: str,
    date_str: str,
    description: str,
    template_id: str,
    is_title_html: bool = False,
) -> str:
    escaped_title = title if is_title_html else escape_html(title)
    escaped_sub = escape_html(subtitle)
    escaped_date = escape_html(date_str)
    desc_html = f'<div class="item-desc">{sanitize_rich_text(description)}</div>' if description else ""

    if template_id == "asu-tech":
        return f"""
        <div class="resume-item asu-tech-item">
          <div class="companyBar">
            <div class="companyBarLeft">
              <span class="institutionName">{escaped_title}</span>
              {f'<span class="institutionSubtitle">{escaped_sub}</span>' if escaped_sub else ''}
            </div>
            {f'<span class="itemDate">{escaped_date}</span>' if escaped_date else ''}
          </div>
          {desc_html}
        </div>
        """

    return f"""
    <div class="resume-item">
      <div class="item-header">
        <div class="item-title-group">
          <span class="item-title">{escaped_title}</span>
          {f'<span class="item-subtitle">{escaped_sub}</span>' if escaped_sub else ''}
        </div>
        {f'<span class="item-date">{escaped_date}</span>' if escaped_date else ''}
      </div>
      {desc_html}
    </div>
    """


def _wrap_section(title: str, content_html: str, template_id: str) -> str:
    escaped_title = escape_html(title)
    return f"""
    <section class="resume-section section-{template_id}">
      <h2 class="section-title"><span class="title-text">{escaped_title}</span></h2>
      <div class="section-content">
        {content_html}
      </div>
    </section>
    """


def _build_styles(template_id: str, primary_color: str, print_background: bool) -> str:
    print_adjust = "exact" if print_background else "economy"
    # Common base styles
    font_family = (
        '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif'
    )
    if template_id in ("asu-11", "asu-17"):
        font_family = 'Georgia, "Songti SC", "SimSun", serif, ' + font_family

    base_css = f"""
    :root {{
      --primary-color: {primary_color};
      --text-main: #1f2937;
      --text-muted: #4b5563;
      --border-color: #e5e7eb;
      --page-padding: 24px;
      --line-height: 1.4;
    }}

    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    body {{
      background-color: #f3f4f6;
      color: var(--text-main);
      font-family: {font_family};
      font-size: 10pt;
      line-height: var(--line-height);
      -webkit-font-smoothing: antialiased;
      -webkit-print-color-adjust: {print_adjust};
      print-color-adjust: {print_adjust};
    }}

    .resume-paper {{
      width: 100%;
      max-width: 210mm;
      min-height: 297mm;
      margin: 0 auto;
      background: #ffffff;
      padding: 24px 32px;
      box-sizing: border-box;
    }}

    .resume-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 14px;
      border-bottom: 2px solid var(--primary-color);
      padding-bottom: 10px;
    }}

    .candidate-name {{
      font-size: 20pt;
      font-weight: 700;
      color: #111827;
      line-height: 1.2;
    }}

    .candidate-title {{
      font-size: 11pt;
      color: var(--text-muted);
      font-weight: 600;
      margin-top: 4px;
    }}

    .contact-row {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px 14px;
      margin-top: 6px;
      font-size: 9pt;
      color: var(--text-muted);
    }}

    .contact-item {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }}

    .contact-item svg {{
      color: var(--primary-color);
      flex-shrink: 0;
    }}

    .contact-item a {{
      color: inherit;
      text-decoration: none;
    }}

    .contact-item a:hover {{
      text-decoration: underline;
    }}

    .photo-slot {{
      width: 28mm;
      height: 36mm;
      border-radius: 4px;
      overflow: hidden;
      background: #f9fafb;
      flex-shrink: 0;
    }}

    .photo-slot img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
    }}

    .resume-section {{
      margin-bottom: 12px;
      break-inside: avoid;
      page-break-inside: avoid;
    }}

    .section-title {{
      font-size: 12pt;
      font-weight: 700;
      color: var(--primary-color);
      border-bottom: 1.5px solid var(--primary-color);
      padding-bottom: 3px;
      margin-bottom: 8px;
    }}

    .resume-item {{
      margin-bottom: 8px;
      break-inside: avoid;
      page-break-inside: avoid;
    }}

    .item-header {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 2px;
    }}

    .item-title-group {{
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 6px;
    }}

    .item-title {{
      font-size: 10.5pt;
      font-weight: 700;
      color: #111827;
    }}

    .item-subtitle {{
      font-size: 9.5pt;
      color: var(--text-muted);
    }}

    .item-date {{
      font-size: 9pt;
      color: #6b7280;
      white-space: nowrap;
    }}

    .item-desc, .rich-content {{
      font-size: 9.5pt;
      color: #374151;
      line-height: 1.4;
    }}

    .item-desc ul, .rich-content ul {{
      padding-left: 18px;
      margin: 3px 0;
    }}

    .item-desc li, .rich-content li {{
      margin-bottom: 2px;
    }}

    /* A4 print media */
    @page {{
      size: A4 portrait;
      margin: 0;
    }}

    @media print {{
      html, body {{
        width: 210mm !important;
        margin: 0 !important;
        padding: 0 !important;
        background: #ffffff !important;
        -webkit-print-color-adjust: {print_adjust} !important;
        print-color-adjust: {print_adjust} !important;
      }}
      .resume-paper {{
        box-shadow: none !important;
        padding: 16mm 18mm !important;
        max-width: none !important;
        width: 210mm !important;
      }}
      .no-print {{
        display: none !important;
      }}
    }}
    """

    # Template-specific style overrides
    if template_id == "asu-tech":
        template_css = """
        .companyBar {
          background: #f2f3f5;
          border-radius: 6px;
          padding: 5px 8px;
          min-height: 28px;
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-top: 4px;
          margin-bottom: 4px;
          -webkit-print-color-adjust: exact;
          print-color-adjust: exact;
        }
        .companyBarLeft {
          display: flex;
          align-items: center;
          gap: 8px;
          flex: 1;
        }
        .institutionName {
          font-size: 10.5pt;
          font-weight: 700;
          color: #111827;
        }
        .institutionSubtitle {
          font-size: 9.5pt;
          color: #4b5563;
        }
        .itemDate {
          font-size: 9pt;
          color: #6b7280;
        }
        .section-title {
          font-size: 13pt;
          font-weight: 700;
          color: var(--primary-color);
          border-bottom: 2px solid var(--primary-color);
          padding-bottom: 2px;
          margin-top: 8px;
          margin-bottom: 6px;
        }
        """
    elif template_id in ("asu-02", "asu-08", "asu-15"):  # Band style
        template_css = """
        .section-title {
          background-color: var(--primary-color);
          color: #ffffff;
          padding: 4px 8px;
          border-radius: 3px;
          border-bottom: none;
          font-size: 11pt;
        }
        """
    elif template_id in ("asu-03", "asu-06"):  # Timeline style
        template_css = """
        .section-content {
          border-left: 2px solid #e5e7eb;
          margin-left: 8px;
          padding-left: 14px;
        }
        .resume-item {
          position: relative;
        }
        .resume-item::before {
          content: "";
          position: absolute;
          left: -19px;
          top: 5px;
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--primary-color);
        }
        """
    elif template_id == "asu-04":  # Top banner
        template_css = """
        .header-banner {
          background-color: #1e3a8a;
          color: #ffffff;
          padding: 18px 24px;
          margin: -24px -32px 16px -32px;
          border-bottom: none;
        }
        .header-banner .candidate-name {
          color: #ffffff;
        }
        .header-banner .candidate-title {
          color: #93c5fd;
        }
        .header-banner .contact-row {
          color: #e0e7ff;
        }
        .header-banner .contact-item svg {
          color: #93c5fd;
        }
        """
    elif template_id in ("asu-05", "asu-13"):  # Sidebar layout
        bg_sidebar = "#111827" if template_id == "asu-13" else "#f8fafc"
        text_sidebar = "#f9fafb" if template_id == "asu-13" else "#1f2937"
        template_css = f"""
        .resume-sidebar-layout {{
          display: flex;
          gap: 20px;
          min-height: 270mm;
        }}
        .resume-sidebar {{
          width: 32%;
          background: {bg_sidebar};
          color: {text_sidebar};
          padding: 16px;
          border-radius: 4px;
          box-sizing: border-box;
        }}
        .resume-sidebar .candidate-name {{
          font-size: 16pt;
          color: inherit;
        }}
        .resume-sidebar .candidate-title {{
          font-size: 10pt;
          color: inherit;
          opacity: 0.85;
        }}
        .resume-sidebar .contact-row {{
          flex-direction: column;
          align-items: flex-start;
          gap: 6px;
          color: inherit;
        }}
        .resume-sidebar .resume-header {{
          border-bottom: 1px solid rgba(150, 150, 150, 0.3);
          padding-bottom: 12px;
        }}
        .resume-main {{
          width: 68%;
          box-sizing: border-box;
        }}
        """
    elif template_id in ("asu-08", "asu-14", "asu-16"):  # Two-column layout
        col_main = "60%" if template_id == "asu-16" else "55%"
        col_sub = "40%" if template_id == "asu-16" else "45%"
        template_css = f"""
        .resume-two-column-layout {{
          display: flex;
          gap: 16px;
        }}
        .resume-col-main {{
          width: {col_main};
        }}
        .resume-col-sub {{
          width: {col_sub};
        }}
        """
    elif template_id == "asu-07":  # Right rail
        template_css = """
        .resume-paper {
          border-right: 6px solid var(--primary-color);
        }
        """
    elif template_id == "asu-09":  # Cards
        template_css = """
        .resume-item {
          border: 1px solid #e5e7eb;
          border-radius: 6px;
          padding: 8px 10px;
          background: #fafafa;
        }
        """
    elif template_id == "asu-10":  # Ribbon cut corner
        template_css = """
        .section-title {
          display: inline-block;
          background: var(--primary-color);
          color: #ffffff;
          padding: 3px 12px;
          clip-path: polygon(0 0, calc(100% - 10px) 0, 100% 50%, calc(100% - 10px) 100%, 0 100%);
          border-bottom: none;
        }
        """
    elif template_id == "asu-12":  # Centered
        template_css = """
        .resume-header {
          text-align: center;
          flex-direction: column;
          align-items: center;
        }
        .contact-row {
          justify-content: center;
        }
        """
    else:
        template_css = ""

    return base_css + "\n" + template_css
