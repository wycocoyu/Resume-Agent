"""
LaTeX Section 生成器模块
提供各个简历模块的 LaTeX 代码生成函数
与 slager.link (wy.tex) 格式保持一致
"""
from typing import Dict, Any, List
from .latex_utils import escape_latex
from .html_to_latex import escape_href, html_to_latex, html_to_latex_items
import math
import re

# 工作经历板块的 Logo 文件名前缀。实习用默认的 'logo'，两者必须不同——
# 同名会让两个板块下标相同的 Logo 互相覆盖（显示成错的公司）。
# 下载端 company_logos.download_logos_to_dir 与渲染端共用本常量。
WORK_EXPERIENCE_LOGO_PREFIX = 'work_logo'


def _apply_px_font_size(
    latex_content: str,
    raw_size: Any,
    default_px: float,
    *,
    apply_default: bool = False,
) -> str:
    """将前端 px 字号转换为 LaTeX pt；可按需显式应用默认字号。"""
    if isinstance(raw_size, bool) or raw_size is None:
        return latex_content
    try:
        px_size = float(raw_size)
    except (TypeError, ValueError):
        return latex_content
    if (
        not math.isfinite(px_size)
        or not 8 <= px_size <= 32
        or (px_size == default_px and not apply_default)
    ):
        return latex_content

    pt_size = round(px_size * 0.75, 2)
    baseline = round(pt_size * 1.2, 2)
    return f"{{\\fontsize{{{pt_size:g}pt}}{{{baseline:g}pt}}\\selectfont {latex_content}}}"

def generate_section_summary(resume_data: Dict[str, Any], section_titles: Dict[str, str] = None) -> List[str]:
    """生成个人总结"""
    content = []
    summary = resume_data.get('summary')
    title = (section_titles or {}).get('summary', '个人总结')
    if isinstance(summary, str) and summary.strip():
        content.append(f"\\section{{{escape_latex(title)}}}")
        summary_text = summary.strip()
        if '<' in summary_text and '>' in summary_text:
            content.append(html_to_latex(summary_text))
        else:
            content.append(escape_latex(summary_text))
        content.append("")
    return content

def generate_section_internships(
    resume_data: Dict[str, Any],
    section_titles: Dict[str, str] = None,
    logo_prefix: str = 'logo',
) -> List[str]:
    """
    生成实习经历/工作经历 - 与 wy.tex 格式一致
    支持 Markdown 加粗（**text**），自动组合 company 和 position
    格式：{company} - {position}
    支持列表类型：none（无列表）、unordered（无序列表）、ordered（有序列表）

    logo_prefix 决定 Logo 图片文件名（`{prefix}_{idx}.png`），必须与
    company_logos.download_logos_to_dir 落盘时用的前缀一致。工作经历复用本
    生成器但走独立前缀，否则两个板块同下标的 Logo 会互相覆盖。
    """
    content = []
    internships = resume_data.get('internships') or []
    title = (section_titles or {}).get('internships') or (section_titles or {}).get('experience', '实习经历')
    
    # 获取列表类型，默认为 'none'
    global_settings = resume_data.get('globalSettings') or {}
    list_type = global_settings.get('experienceListType', 'none')
    company_font_size = global_settings.get('companyNameFontSize')
    experience_gap = global_settings.get('experienceGap', 1)  # 经历项间距，默认 1ex
    logo_size_px = global_settings.get('companyLogoSize', 20)  # Logo 大小（px），默认 20
    logo_size_pt = round(logo_size_px * 0.75, 1)  # 转换为 pt
    
    if isinstance(internships, list) and internships:
        content.append(f"\\section{{{escape_latex(title)}}}")
        
        # 始终使用 \datedsubsection 保持与教育经历一致的字号/对齐
        for idx, it in enumerate(internships):
            company = escape_latex(it.get('title') or '')
            position = escape_latex(it.get('subtitle') or '')
            date = it.get('date') or ''
            if date and date.strip() in ['未提及', '未知', 'N/A', '-', '']:
                date = ''
            date = escape_latex(date)
            
            item_company_font_size = it.get('companyNameFontSize', company_font_size)
            try:
                item_company_font_size = float(item_company_font_size) if item_company_font_size is not None else None
            except (TypeError, ValueError):
                item_company_font_size = None

            # 单条经历字号优先；未设置时回退全局字号
            if company and item_company_font_size and item_company_font_size != 15:
                pt_size = round(item_company_font_size * 0.75, 1)
                baseline = round(pt_size * 1.2, 1)
                company = f"{{\\fontsize{{{pt_size}pt}}{{{baseline}pt}}\\selectfont {company}}}"
            
            # 如果有公司 Logo，在公司名称前插入图片
            logo_key = it.get('logo')
            if logo_key:
                logo_file = f"logos/{logo_prefix}_{idx}.png"
                # 优先使用单条经历的 logoSize，否则用全局设置
                item_logo_px = it.get('logoSize') or logo_size_px
                item_logo_pt = round(item_logo_px * 0.75, 1)
                max_width_pt = round(item_logo_pt * 4, 1)
                logo_latex = f"\\raisebox{{-0.2em}}{{\\includegraphics[height={item_logo_pt}pt,width={max_width_pt}pt,keepaspectratio]{{{logo_file}}}}}\\hspace{{0.3em}}"
                company = f"{logo_latex}{company}"
            
            if company and position:
                title_text = f"{company}\\hspace{{0.2em}}\\textendash\\hspace{{0.2em}}{position}"
            elif company:
                title_text = company
            elif position:
                title_text = position
            else:
                title_text = '未命名公司'
            
            # 使用 \normalsize 字体，确保与教育经历一致
            latex_line = f"\\datedsubsection{{\\normalsize {title_text}}}{{\\normalsize {date}}}"
            content.append(latex_line)

            # 处理工作内容/成就
            achievements = it.get('highlights') or it.get('achievements') or it.get('items') or it.get('description') or []
            if isinstance(achievements, str):
                # 如果是字符串，转换为列表
                achievements = [achievements]
            elif isinstance(achievements, dict):
                # 如果是字典，尝试提取text字段
                achievements = achievements.get('text') or [achievements]

            if isinstance(achievements, list) and achievements:
                # 根据列表类型决定渲染方式
                if list_type == 'ordered':
                    content.append(r"\begin{enumerate}[label={},parsep=0.2ex,itemsep=0.2ex,topsep=0.2ex]")
                    for ach in achievements:
                        if isinstance(ach, str) and ach.strip():
                            content.append(f"  \\item {html_to_latex(ach.strip()).strip()}")
                        elif isinstance(ach, dict):
                            text = ach.get('text') or ach.get('content') or ''
                            if text and text.strip():
                                content.append(f"  \\item {html_to_latex(text.strip()).strip()}")
                    content.append(r"\end{enumerate}")
                elif list_type == 'unordered':
                    content.append(r"\begin{itemize}[label={},parsep=0.2ex,itemsep=0.2ex,topsep=0.2ex]")
                    for ach in achievements:
                        if isinstance(ach, str) and ach.strip():
                            content.append(f"  \\item {html_to_latex(ach.strip()).strip()}")
                        elif isinstance(ach, dict):
                            text = ach.get('text') or ach.get('content') or ''
                            if text and text.strip():
                                content.append(f"  \\item {html_to_latex(text.strip()).strip()}")
                    content.append(r"\end{itemize}")
                else:
                    # list_type == 'none' 或其他情况，使用段落格式
                    for ach in achievements:
                        if isinstance(ach, str) and ach.strip():
                            # 对于段落格式，我们直接使用html_to_latex，但让内容自然流动
                            
                            latex_content = html_to_latex(ach.strip())
                            # 清理多余的换行符
                            latex_content = re.sub(r'\n{3,}', '\n\n', latex_content)
                            latex_stripped_before = latex_content.strip()
                            
                            # strip 后检查内容是否为空
                            latex_stripped = latex_content.strip()
                            if not latex_stripped:
                                # 如果转换后内容为空，跳过
                                continue
                            # 如果转换结果包含 itemize/enumerate，则视为列表，避免自动补句号
                            list_env = (
                                "\\begin{itemize}" in latex_stripped
                                or "\\begin{enumerate}" in latex_stripped
                                or bool(re.search(r'\\begin\\{(?:itemize|enumerate)\\}', latex_stripped))
                            )
                            
                            if list_env:
                                latex_content = latex_stripped
                                
                                content.append(latex_content)
                                continue
                            # 如果内容不以句号等结尾，添加句号（用 strip 后的内容检查末尾字符）
                            if latex_stripped[-1] not in '.。！?；;\n':
                                latex_content = latex_stripped + '。'
                            else:
                                latex_content = latex_stripped
                            
                            content.append(latex_content)
                        elif isinstance(ach, dict):
                            text = ach.get('text') or ach.get('content') or ''
                            if text and text.strip():
                                
                                latex_content = html_to_latex(text.strip())
                                latex_content = re.sub(r'\n{3,}', '\n\n', latex_content)
                                latex_stripped = latex_content.strip()
                                
                                if not latex_stripped:
                                    continue
                                list_env = (
                                    "\\begin{itemize}" in latex_stripped
                                    or "\\begin{enumerate}" in latex_stripped
                                    or bool(re.search(r'\\begin\\{(?:itemize|enumerate)\\}', latex_stripped))
                                )
                                
                                if list_env:
                                    latex_content = latex_stripped
                                    
                                    content.append(latex_content)
                                    continue
                                if latex_stripped[-1] not in '.。！?；;\n':
                                    latex_content = latex_stripped + '。'
                                else:
                                    latex_content = latex_stripped
                                
                                content.append(latex_content)
            else:
                # 没有成就信息
                pass

            content.append("")
            # 在经历项之间插入可配置间距（最后一项不需要）
            if idx < len(internships) - 1 and experience_gap and experience_gap > 0:
                content.append(f"\\vspace{{{experience_gap}ex}}")
                content.append("")
        # 不再开启列表环境，避免额外缩进和字号差异
        content.append("")
    return content

def generate_section_experience(resume_data: Dict[str, Any], section_titles: Dict[str, str] = None) -> List[str]:
    """
    生成工作经历
    支持 Markdown 加粗（**text**），自动组合 company 和 position
    格式：{company} - {position}
    """
    content = []
    exp = resume_data.get('experience') or []
    title = (section_titles or {}).get('experience', '工作经历')
    
    # 获取公司名称字号设置
    global_settings = resume_data.get('globalSettings') or {}
    company_font_size = global_settings.get('companyNameFontSize')
    
    if isinstance(exp, list) and exp:
        content.append(f"\\section{{{escape_latex(title)}}}")
        for e in exp:
            # escape_latex 会自动处理 **text** -> \textbf{text}
            company = escape_latex(e.get('company') or '')
            position = escape_latex(e.get('position') or '')
            duration = escape_latex(e.get('duration') or e.get('date') or '')
            
            item_company_font_size = e.get('companyNameFontSize', company_font_size)
            try:
                item_company_font_size = float(item_company_font_size) if item_company_font_size is not None else None
            except (TypeError, ValueError):
                item_company_font_size = None

            # 单条经历字号优先；未设置时回退全局字号
            if company and item_company_font_size and item_company_font_size != 15:
                # LaTeX pt ≈ CSS px * 0.75，但这里直接用 pt 近似
                pt_size = round(item_company_font_size * 0.75, 1)
                baseline = round(pt_size * 1.2, 1)
                company = f"{{\\fontsize{{{pt_size}pt}}{{{baseline}pt}}\\selectfont {company}}}"
            
            # 自动组合：{company} – {position}（使用 \textendash 并显式空隙让破折号居中）
            if company and position:
                subsection_title = f"{company}\\hspace{{0.2em}}\\textendash\\hspace{{0.2em}}{position}"
            elif company:
                subsection_title = company
            elif position:
                subsection_title = position
            else:
                subsection_title = '未命名公司'
            
            content.append(f"\\datedsubsection{{{subsection_title}}}{{{duration}}}")
            # Prefer 'details' (workspace editor HTML/Markdown); fall back to legacy 'achievements' list
            details_raw = e.get('details') or ''
            if isinstance(details_raw, str) and details_raw.strip():
                latex_details = html_to_latex(details_raw.strip())
                latex_details = re.sub(r'\n{3,}', '\n\n', latex_details).strip()
                if latex_details:
                    content.append(latex_details)
            else:
                achievements = e.get('achievements') or []
                if isinstance(achievements, list) and achievements:
                    content.append(r"\begin{itemize}[label={},parsep=0.2ex]")
                    for ach in achievements:
                        if isinstance(ach, str) and ach.strip():
                            content.append(f"  \\item {escape_latex(ach.strip())}")
                    content.append(r"\end{itemize}")
            content.append("")
    return content

def _convert_markdown_bold(text: str) -> str:
    """将 **text** 转换为 \\textbf{text}"""
    import re
    import json
    # 匹配 **text** 或 **text**: 格式
    pattern = r'\*\*([^*]+)\*\*'
    return re.sub(pattern, r'\\textbf{\1}', text)


def _extract_project_link(raw_link: Any) -> str:
    """提取并清洗项目链接，兼容 Markdown 链接格式。"""
    if not isinstance(raw_link, str):
        return ""
    link = raw_link.strip()
    if not link:
        return ""

    # 兼容: [文本](https://example.com)
    md_match = re.match(r'^\[[^\]]*\]\(([^)]+)\)$', link)
    if md_match:
        link = md_match.group(1).strip()

    return link

def generate_section_projects(resume_data: Dict[str, Any], section_titles: Dict[str, str] = None) -> List[str]:
    """
    生成项目经历 - 与 wy.tex 格式一致
    支持两种格式：
    1. items 结构：嵌套的子项目
    2. highlights 结构：支持 **bold** 和 > 缩进语法
    
    格式:
    \\datedsubsection{\\textbf{项目名}}{}
    \\begin{itemize}[parsep=0.2ex]
      \\item \\textbf{子项目标题}
        \\begin{itemize}[label=\\textbf{·},parsep=0.2ex]
          \\item 详情1
          \\item 详情2
        \\end{itemize}
    \\end{itemize}
    """
    content = []
    projects = resume_data.get('projects') or []
    section_title = (section_titles or {}).get('projects', '项目经验')
    global_settings = resume_data.get('globalSettings') or {}
    link_display = global_settings.get('projectLinkDisplay', 'inline')
    link_label = global_settings.get('projectLinkLabel', '链接')
    project_experience_gap = global_settings.get('projectExperienceGap', 1)  # 经历项间距，默认 1ex
    if isinstance(projects, list) and projects:
        content.append(f"\\section{{{escape_latex(section_title)}}}")
        content.append("")
        content.append("")
        
        for pidx, p in enumerate(projects):
            # 兼容多种字段名
            title = p.get('title') or p.get('name') or ''
            role = p.get('role') or p.get('subtitle') or ''
            date = p.get('date') or ''
            project_link = _extract_project_link(
                p.get('link')
                or p.get('repo')
                or p.get('repoUrl')
                or p.get('url')
                or ''
            )
            
            # 过滤无效时间
            if date and date.strip() in ['未提及', '未知', 'N/A', '-', '']:
                date = ''
            date = escape_latex(date)
            
            # 构建标题；第二参数为时间，与实习/教育经历一致
            full_title = escape_latex(title)
            
            if full_title:
                heading_title = f"\\textbf{{{full_title}}}"
                heading_title = _apply_px_font_size(
                    heading_title,
                    p.get('projectNameFontSize'),
                    15,
                )

                escaped_label = escape_latex(link_label) if link_label else ''
                label_prefix = f"{escaped_label}: " if escaped_label else ''

                # 根据设置决定项目链接位置
                if isinstance(project_link, str) and project_link.strip():
                    link = project_link.strip()
                    display_link = escape_latex(link)
                    if link_display == 'icon' and (link.startswith("http://") or link.startswith("https://")):
                        heading_title = f"{heading_title}\\hspace{{0.3em}}\\href{{{escape_href(link)}}}{{\\faGithub}}"
                    elif link_display == 'inline':
                        if link.startswith("http://") or link.startswith("https://"):
                            link_content = f"{label_prefix}\\textit{{\\href{{{escape_href(link)}}}{{{display_link}}}}}"
                        else:
                            link_content = f"{label_prefix}\\textit{{{display_link}}}"
                        link_content = _apply_px_font_size(
                            link_content,
                            p.get('projectLinkFontSize', 12),
                            12,
                            apply_default=True,
                        )
                        heading_title = f"{heading_title}\\hspace{{0.5em}}{link_content}"

                content.append(f"\\datedsubsection{{{heading_title}}}{{{date}}}")

                # 下方显示项目链接：紧跟标题下一行
                if (
                    isinstance(project_link, str)
                    and project_link.strip()
                    and link_display == 'below'
                ):
                    link = project_link.strip()
                    display_link = escape_latex(link)
                    escaped_label = escape_latex(link_label) if link_label else ''
                    label_prefix = f"{escaped_label}: " if escaped_label else ''
                    if link.startswith("http://") or link.startswith("https://"):
                        link_content = f"{label_prefix}\\textit{{\\href{{{escape_href(link)}}}{{{display_link}}}}}"
                    else:
                        link_content = f"{label_prefix}\\textit{{{display_link}}}"
                    link_content = _apply_px_font_size(
                        link_content,
                        p.get('projectLinkFontSize', 12),
                        12,
                        apply_default=True,
                    )
                    content.append(link_content)

                # 检查是否有 items（子项目结构）
                items = p.get('items') or []
                highlights = p.get('highlights') or []

                if isinstance(items, list) and items:
                    # 有子项目结构 - 不带圆点的列表，缩进对齐实习经历（使用 leftmargin=* 自动对齐）
                    content.append(r"\begin{itemize}[label={},parsep=0.2ex,itemsep=0ex,leftmargin=*,labelsep=0.5em,itemindent=0em]")
                    for sub in items:
                        sub_title = sub.get('title')
                        if sub_title:
                            escaped_sub_title = escape_latex(sub_title)
                            content.append(f"  \\item \\textbf{{{escaped_sub_title}}}")
                            details = sub.get('details') or []
                            if isinstance(details, list) and details:
                                content.append(r"    \begin{itemize}[label=\footnotesize$\bullet$,parsep=0.2ex,itemsep=0ex,leftmargin=1em,labelsep=0.4em,itemindent=0em]")
                                for detail in details:
                                    if isinstance(detail, str) and detail.strip():
                                        content.append(f"      \\item {escape_latex(detail.strip())}")
                                content.append(r"    \end{itemize}")
                            content.append("")
                    content.append(r"\end{itemize}")
                elif isinstance(highlights, list) and highlights:
                    # highlights 结构 - 支持 HTML 和 Markdown 格式
                    has_list_wrapper = False
                    
                    
                    for h in highlights:
                        if not isinstance(h, str) or not h.strip():
                            continue
                        
                        h = h.strip()
                        
                        # 检查是否是 HTML 格式
                        if '<' in h and '>' in h:
                            # HTML 格式，使用 html_to_latex 转换
                            converted = html_to_latex(h)
                            if converted.strip():
                                # 如果 HTML 已包含列表结构，直接添加
                                if '\\begin{itemize}' in converted or '\\begin{enumerate}' in converted:
                                    # html_to_latex 已按列表层级指定圆点：一级实心、二级空心。
                                    # 不要在章节层再次重写 itemize，否则会抹掉嵌套列表标记。
                                    converted = re.sub(
                                        r'\\begin\{enumerate\}(\[[^\]]*\])?',
                                        r'\\begin{enumerate}[leftmargin=*,labelsep=0.5em,topsep=0ex,partopsep=0ex]',
                                        converted
                                    )
                                    content.append(converted)
                                    
                                else:
                                    # 否则包装成列表项（与实习经历对齐）
                                    if not has_list_wrapper:
                                        content.append(r"\begin{itemize}[label=\footnotesize$\bullet$,parsep=0.2ex,itemsep=0ex,leftmargin=*,labelsep=0.5em,itemindent=0em]")
                                        has_list_wrapper = True
                                    content.append(f"  \\item {converted}")
                                    
                        elif h.startswith('**') and '**' in h[2:]:
                            # Markdown 加粗格式（保留圆点，适度缩进）
                            if not has_list_wrapper:
                                # 对齐实习经历的列表缩进
                                content.append(r"\begin{itemize}[label=\footnotesize$\bullet$,parsep=0.2ex,itemsep=0ex,leftmargin=*,labelsep=0.5em,itemindent=0em]")
                                has_list_wrapper = True
                            converted = _convert_markdown_bold(h)
                            converted = escape_latex(converted.replace('\\textbf{', '<<<TEXTBF>>>').replace('}', '<<<ENDBF>>>')).replace('<<<TEXTBF>>>', '\\textbf{').replace('<<<ENDBF>>>', '}')
                            content.append(f"  \\item {converted}")
                            
                        else:
                            # 普通文本（与实习经历对齐）
                            if not has_list_wrapper:
                                content.append(r"\begin{itemize}[label=\footnotesize$\bullet$,parsep=0.2ex,itemsep=0ex,leftmargin=*,labelsep=0.5em,itemindent=0em]")
                                has_list_wrapper = True
                            content.append(f"  \\item {escape_latex(h)}")
                            
                    
                    if has_list_wrapper:
                        content.append(r"\end{itemize}")

                content.append("")
                content.append("")
                if pidx < len(projects) - 1 and project_experience_gap and project_experience_gap > 0:
                    content.append(f"\\vspace{{{project_experience_gap}ex}}")
                    content.append("")
    return content

def generate_section_skills(resume_data: Dict[str, Any], section_titles: Dict[str, str] = None) -> List[str]:
    """
    生成专业技能 - 支持 HTML 编辑器内容
    如果 skillContent 存在，直接转换 HTML 为 LaTeX
    否则使用旧的 skills 数组格式
    """
    content = []
    title = (section_titles or {}).get('skills', '专业技能')
    
    # 优先使用 skillContent（HTML 格式）
    skill_content = resume_data.get('skillContent') or resume_data.get('skill_content') or ''
    if skill_content and skill_content.strip():
        content.append(f"\\section{{{escape_latex(title)}}}")
        # 检查 HTML 是否包含列表结构
        has_list = '<ul>' in skill_content or '<ol>' in skill_content
        
        if has_list:
            # 用户已使用工具栏添加了列表，直接转换（会保留圆点）
            latex_content = html_to_latex(skill_content.strip())
            content.append(latex_content)
        else:
            # 如果没有列表结构，按段落或换行分割成列表项（无圆点）
            latex_content = html_to_latex(skill_content.strip())
            # 按段落或换行分割
            if '\\par' in latex_content:
                paragraphs = latex_content.split('\\par')
            elif '\n\n' in latex_content:
                paragraphs = latex_content.split('\n\n')
            else:
                paragraphs = [latex_content]

            # 先收集有效的段落
            paragraph_items = []
            for para in paragraphs:
                para = para.strip()
                if para:
                    paragraph_items.append(f"  \\item {para}")

            # 只有在有内容时才添加itemize
            if paragraph_items:
                content.append(r"\begin{itemize}[label={},parsep=0.2ex]")
                content.extend(paragraph_items)
                content.append(r"\end{itemize}")
        content.append("")
        return content
    
    # 兼容旧的 skills 数组格式
    skills = resume_data.get('skills') or []
    if skills:
        # 先收集有效的技能项
        skill_items = []
        for s in skills:
            if isinstance(s, str):
                if s.strip():
                    if ':' in s or '：' in s:
                        parts = s.replace('：', ':').split(':', 1)
                        category = parts[0].strip()
                        details = parts[1].strip() if len(parts) > 1 else ''
                        if category and details:
                            skill_items.append(f"  \\item \\textbf{{{escape_latex(category)}:}} {escape_latex(details)}")
                        else:
                            skill_items.append(f"  \\item {escape_latex(s.strip())}")
                    else:
                        skill_items.append(f"  \\item {escape_latex(s.strip())}")
            elif isinstance(s, dict):
                category = escape_latex(s.get('category') or '').strip()
                details = s.get('details') or ''
                # 检查 details 是否是 HTML
                if '<' in details and '>' in details:
                    details = html_to_latex(details)
                else:
                    details = escape_latex(details)
                # 如果 category 为空，只输出 details
                if not category:
                    if details:
                        skill_items.append(f"  \\item {details}")
                elif details:
                    skill_items.append(f"  \\item \\textbf{{{category}:}} {details}")
                elif category:
                    skill_items.append(f"  \\item \\textbf{{{category}}}")

        # 只有在有内容时才创建section和itemize
        if skill_items:
            content.append(f"\\section{{{escape_latex(title)}}}")
            content.append(r"\begin{itemize}[label={},parsep=0.2ex]")
            content.extend(skill_items)
            content.append(r"\end{itemize}")
            content.append("")
    return content

def generate_section_education(resume_data: Dict[str, Any], section_titles: Dict[str, str] = None) -> List[str]:
    """
    生成教育经历 - 与 wy.tex 格式一致
    格式: \\datedsubsection{学校 - 专业 - 学位}{日期}
    \\ \\textbf{荣誉:} 荣誉内容
    """
    content = []
    edu = resume_data.get('education') or []
    section_title = (section_titles or {}).get('education', '教育经历')
    global_settings = resume_data.get('globalSettings') or {}
    default_logo_size_px = global_settings.get('schoolLogoSize', 20)
    default_school_font_size = global_settings.get('schoolNameFontSize')
    if isinstance(edu, list) and edu:
        content.append(f"\\section{{{escape_latex(section_title)}}}")
        for idx, ed in enumerate(edu):
            # 兼容多种字段名
            school = escape_latex(ed.get('title') or ed.get('school') or '')
            degree = escape_latex(ed.get('degree') or '')
            major = escape_latex(ed.get('subtitle') or ed.get('major') or '')
            duration = escape_latex(ed.get('date') or ed.get('duration') or '')

            item_school_font_size = ed.get('schoolNameFontSize', default_school_font_size)
            try:
                item_school_font_size = float(item_school_font_size) if item_school_font_size is not None else None
            except (TypeError, ValueError):
                item_school_font_size = None

            if school and item_school_font_size and item_school_font_size != 15:
                pt_size = round(item_school_font_size * 0.75, 1)
                baseline = round(pt_size * 1.2, 1)
                school = f"{{\\fontsize{{{pt_size}pt}}{{{baseline}pt}}\\selectfont {school}}}"
            
            logo_key = ed.get('logo')
            if logo_key and school:
                logo_file = f"logos/school_logo_{idx}"
                item_logo_px = ed.get('logoSize') or default_logo_size_px
                item_logo_pt = round(item_logo_px * 0.75, 1)
                max_width_pt = round(item_logo_pt * 4, 1)
                logo_latex = f"\\raisebox{{-0.2em}}{{\\includegraphics[height={item_logo_pt}pt,width={max_width_pt}pt,keepaspectratio]{{{logo_file}}}}}\\hspace{{0.3em}}"
                school = f"{logo_latex}{school}"

            # 构建标题：学校 - 专业 - 学位（学校和学位默认不加粗）
            title_parts = []
            if school:
                title_parts.append(school)
            if major:
                title_parts.append(major)
            if degree:
                title_parts.append(degree)

            title_str = " - ".join(title_parts) if title_parts else school
            
            if title_str:
                # 使用 \normalsize 字体，确保与实习经历一致
                latex_line = f"\\datedsubsection{{\\normalsize {title_str}}}{{\\normalsize {duration}}}"
                content.append(latex_line)
                # 荣誉信息 - 与 wy.tex 格式一致
                honors = ed.get('honors')
                if honors:
                    escaped_honors = escape_latex(honors)
                    content.append(f"\\ \\textbf{{荣誉:}} {escaped_honors}")
                # 补充说明 details/description（富文本 HTML，与实习经历列表风格一致）
                details = ed.get('details') or ([ed.get('description')] if ed.get('description') else [])
                if isinstance(details, list) and details:
                    for d in details:
                        if not isinstance(d, str) or not d.strip():
                            continue
                        d = d.strip()
                        if '<' in d and '>' in d:
                            converted = html_to_latex(d)
                            if converted.strip():
                                if '\\begin{itemize}' in converted or '\\begin{enumerate}' in converted:
                                    # 保留 html_to_latex 生成的分层无序列表标记。
                                    converted = re.sub(
                                        r'\\begin\{enumerate\}(\[[^\]]*\])?',
                                        r'\\begin{enumerate}[leftmargin=*,labelsep=0.5em,topsep=0ex,partopsep=0ex]',
                                        converted
                                    )
                                    content.append(converted)
                                else:
                                    content.append(converted.strip())
                        else:
                            content.append(escape_latex(d))
            content.append("")
    return content

def generate_section_awards(resume_data: Dict[str, Any], section_titles: Dict[str, str] = None) -> List[str]:
    """生成奖项"""
    content = []
    awards = resume_data.get('awards') or []
    section_title = (section_titles or {}).get('awards', '荣誉奖项')
    global_settings = resume_data.get('globalSettings') or {}
    list_type = global_settings.get('awardsListType', 'unordered')
    if isinstance(awards, list) and awards:
        # 先收集有效的奖项内容
        award_items = []
        for a in awards:
            if isinstance(a, str):
                if a.strip():
                    award_items.append(f"  \\item {escape_latex(a.strip())}")
                continue
            title = escape_latex(a.get('title') or '')
            issuer = escape_latex(a.get('issuer') or '')
            date = escape_latex(a.get('date') or '')
            description = escape_latex(a.get('description') or '')
            parts = [s for s in [title, issuer] if s]
            subsection_title = " - ".join(parts) if parts else ""
            if description:
                subsection_title = f"{subsection_title}：{description}" if subsection_title else description
            if not subsection_title and date:
                subsection_title = f"获奖时间：{date}"
            if subsection_title:
                if date and "获奖时间：" not in subsection_title:
                    award_items.append(f"  \\item {subsection_title} ({date})")
                else:
                    award_items.append(f"  \\item {subsection_title}")

        # 只有在有内容时才创建section和itemize
        if award_items:
            content.append(f"\\section{{{escape_latex(section_title)}}}")
            if list_type == 'ordered':
                # 有序列表：显示数字编号
                content.append(r"\begin{enumerate}[label=\arabic*.,leftmargin=*,labelsep=0.5em,topsep=0.2ex,partopsep=0ex,itemsep=0ex,parsep=0.2ex]")
                # award_items 目前已带 \item 前缀，enumerate/itemize 通用
                content.extend(award_items)
                content.append(r"\end{enumerate}")
            else:
                # 无序列表：显示圆点
                content.append(r"\begin{itemize}[label=\footnotesize$\bullet$,leftmargin=*,labelsep=0.5em,topsep=0.2ex,partopsep=0ex,itemsep=0ex,parsep=0.2ex,itemindent=0em]")
                content.extend(award_items)
                content.append(r"\end{itemize}")
            content.append("")
    return content

def generate_section_opensource(resume_data: Dict[str, Any], section_titles: Dict[str, str] = None) -> List[str]:
    """
    生成开源经历 - 与 wy.tex 格式一致
    格式:
    \\datedsubsection{\\textbf{项目名}}{角色}
    \\begin{itemize}[parsep=0.2ex]
      \\item 仓库: \\textit{url}
      \\item 贡献描述
    \\end{itemize}

    支持两种字段格式：
    1. AI返回格式: title, subtitle, items, repoUrl/date
    2. 编辑器格式: name, role, description, repo/date
    """
    content = []
    # 兼容 openSource、opensource、open_source 三种字段名
    open_source = resume_data.get('openSource') or resume_data.get('opensource') or resume_data.get('open_source') or []
    title = (section_titles or {}).get('openSource', '开源经历')
    # 获取全局设置
    global_settings = resume_data.get('globalSettings') or {}
    repo_display = global_settings.get('openSourceRepoDisplay', 'below')
    repo_label = global_settings.get('openSourceRepoLabel', '仓库')  # 前缀：'' 无前缀 | '仓库' | 'GitHub' | 自定义
    
    if isinstance(open_source, list) and open_source:
        content.append(f"\\section{{{escape_latex(title)}}}")
        for os_idx, os_item in enumerate(open_source):
            # 兼容两种字段名
            item_title = escape_latex(
                os_item.get('title') or os_item.get('name') or ''
            )
            item_title = _apply_px_font_size(
                f"\\textbf{{{item_title}}}",
                os_item.get('projectNameFontSize'),
                15,
            )
            subtitle = escape_latex(
                os_item.get('subtitle') or os_item.get('role') or ''
            )
            # 兼容多种字段名获取仓库链接
            repo_url = (os_item.get('repo') or  # 前端使用 repo
                       os_item.get('repoUrl') or
                       os_item.get('link') or
                       os_item.get('url') or '')

            # 获取日期（如果有）
            date = escape_latex(os_item.get('date') or '')
            if date:
                subtitle = f"{subtitle} ({date})" if subtitle else date

            # 根据设置决定仓库链接位置
            if repo_display == 'icon' and repo_url:
                # 图标模式：在标题旁放一个链接符号
                subsection_title = f"{item_title}\\hspace{{0.3em}}\\href{{{escape_href(repo_url)}}}{{\\faGithub}}"
            elif repo_display == 'inline' and repo_url:
                escaped_label = escape_latex(repo_label) if repo_label else ''
                label_prefix = f"{escaped_label}: " if escaped_label else ''
                visible_url = (
                    repo_url.replace('{', '%7B')
                    .replace('}', '%7D')
                    .replace('%', r'\%')
                    .replace('#', r'\#')
                )
                repo_content = (
                    f"\\textit{{{label_prefix}\\href{{{escape_href(repo_url)}}}"
                    f"{{\\nolinkurl{{{visible_url}}}}}}}"
                )
                repo_content = _apply_px_font_size(
                    repo_content,
                    os_item.get('repoUrlFontSize', 12),
                    12,
                    apply_default=True,
                )
            else:
                subsection_title = item_title

            if repo_display == 'inline' and repo_url:
                content.append(
                    f"\\datedsubsectionwithrepo{{{item_title}}}{{{repo_content}}}{{{subtitle}}}"
                )
            else:
                content.append(f"\\datedsubsection{{{subsection_title}}}{{{subtitle}}}")

            # 处理贡献描述 - description 是 HTML 格式
            description = os_item.get('description') or ''

            # 准备要显示的内容
            item_contents = []

            if repo_url and repo_display not in ('inline', 'icon'):
                escaped_label = escape_latex(repo_label) if repo_label else ''
                label_prefix = f"{escaped_label}: " if escaped_label else ''
                if repo_url.startswith("http://") or repo_url.startswith("https://"):
                    visible_url = (
                        repo_url.replace('{', '%7B')
                        .replace('}', '%7D')
                        .replace('%', r'\%')
                        .replace('#', r'\#')
                    )
                    repo_content = (
                        f"{label_prefix}\\href{{{escape_href(repo_url)}}}"
                        f"{{\\nolinkurl{{{visible_url}}}}}"
                    )
                else:
                    repo_content = f"{label_prefix}{escape_latex(repo_url)}"
                item_contents.append(
                    _apply_px_font_size(
                        repo_content,
                        os_item.get('repoUrlFontSize', 12),
                        12,
                        apply_default=True,
                    )
                )

            if description:
                # description 是 HTML 格式，需要转换
                from .html_to_latex import html_to_latex
                converted_desc = html_to_latex(description)
                if converted_desc.strip():
                    # 如果转换后的内容包含列表标签，直接添加
                    if '\\begin{itemize}' in converted_desc or '\\begin{enumerate}' in converted_desc:
                        item_contents.append(converted_desc)
                    else:
                        # html_to_latex 已经处理了转义，不需要再次 escape_latex
                        if '\n' in converted_desc:
                            for desc in converted_desc.split('\n'):
                                if desc.strip():
                                    item_contents.append(desc.strip())
                        else:
                            if converted_desc.strip():
                                item_contents.append(converted_desc.strip())

            # 如果有内容，生成itemize（除非已经包含列表）
            if item_contents:
                # 检查是否已经包含列表结构
                has_list = any('\\begin{itemize}' in item or '\\begin{enumerate}' in item for item in item_contents)
                if not has_list:
                    content.append(r"\begin{itemize}[label={},parsep=0.2ex]")
                    for item in item_contents:
                        content.append(f"  \\item {item}")
                    content.append(r"\end{itemize}")
                else:
                    # 已经包含列表结构，直接添加
                    for item in item_contents:
                        content.append(item)

            content.append("")
    return content

def generate_section_custom(
    resume_data: Dict[str, Any],
    section_id: str,
    section_titles: Dict[str, str] = None
) -> List[str]:
    """
    生成自定义模块（custom_*）内容
    数据来源：resume_data.customData[section_id]
    """
    content: List[str] = []
    custom_data = resume_data.get('customData') or {}
    items = custom_data.get(section_id) if isinstance(custom_data, dict) else None
    if not isinstance(items, list):
        return content

    visible_items = [item for item in items if isinstance(item, dict) and item.get('visible', True) is not False]
    if not visible_items:
        return content

    title = (section_titles or {}).get(section_id, '自定义模块')
    section_title_raw = (title or '').strip()
    content.append(f"\\section{{{escape_latex(title)}}}")

    for item in visible_items:
        raw_title = (item.get('title') or '').strip()
        raw_subtitle = (item.get('subtitle') or '').strip()
        raw_date = (item.get('dateRange') or '').strip()

        # 条目标题为空或与模块名相同时视为冗余，不再作为子标题渲染（单块语义，避免重复）
        effective_title = '' if (not raw_title or raw_title == section_title_raw) else raw_title

        item_title = escape_latex(effective_title)
        item_subtitle = escape_latex(raw_subtitle)
        item_date = escape_latex(raw_date)

        if item_title and item_subtitle:
            heading = f"{item_title}\\hspace{{0.2em}}\\textendash\\hspace{{0.2em}}{item_subtitle}"
        else:
            heading = item_title or item_subtitle

        # 仅在有标题/副标题/日期时才输出子标题行，否则只渲染正文
        if heading or item_date:
            content.append(f"\\datedsubsection{{\\normalsize {heading}}}{{\\normalsize {item_date}}}")

        description = item.get('description') or ''
        if isinstance(description, str) and description.strip():
            converted_desc = html_to_latex(description).strip()
            if converted_desc:
                if '\\begin{itemize}' in converted_desc or '\\begin{enumerate}' in converted_desc:
                    content.append(converted_desc)
                else:
                    content.append(r"\begin{itemize}[label={},parsep=0.2ex]")
                    content.append(f"  \\item {converted_desc}")
                    content.append(r"\end{itemize}")

        content.append("")

    return content

def generate_section_work_experience(resume_data: Dict[str, Any], section_titles: Dict[str, str] = None) -> List[str]:
    """
    生成工作经历（2026-07-21 新增的独立板块，与实习经历并行）。

    数据源取 workExperience、标题取 workExperience，其余渲染细节
    （Logo / 列表类型 / 经历间距 / 公司名字号）整段复用
    generate_section_internships——两个板块必须长得一模一样，
    复用而非复制可避免后续改一处漏一处。
    """
    items = resume_data.get('workExperience') or []
    if not isinstance(items, list) or not items:
        return []

    proxy = dict(resume_data)
    proxy['internships'] = items
    titles = dict(section_titles or {})
    # internships 生成器按 internships → experience 顺序取标题，此处显式覆盖
    titles['internships'] = titles.get('workExperience') or '工作经历'
    return generate_section_internships(
        proxy, titles, logo_prefix=WORK_EXPERIENCE_LOGO_PREFIX
    )


"""
Section 生成器映射
"""
SECTION_GENERATORS = {
    'contact': None,
    'summary': generate_section_summary,
    'education': generate_section_education,
    'experience': generate_section_experience,
    'internships': generate_section_internships,
    'workExperience': generate_section_work_experience,   # 前端字段名
    'work_experience': generate_section_work_experience,  # 蛇形别名
    'projects': generate_section_projects,
    'skills': generate_section_skills,
    'awards': generate_section_awards,
    'openSource': generate_section_opensource,  # 前端使用的字段名
    'opensource': generate_section_opensource,
    'open_source': generate_section_opensource,  # 别名
}

"""
默认 section 顺序 - 与 wy.tex 一致
"""
DEFAULT_SECTION_ORDER = [
    # 工作经历排在实习之前（与前端 menuSections 顺序一致）；调用方未传
    # section_order 时走这里，无该板块数据时生成器返回空、不产生空 section
    'workExperience',
    'internships', 'projects', 'opensource', 'skills', 'education',
    'awards', 'summary'
]
