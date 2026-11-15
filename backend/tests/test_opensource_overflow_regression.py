"""Regression tests for LaTeX datedsubsection right-column wrapping, openSource typography, and PDF cache invalidation."""

from pathlib import Path

import fitz

from backend.latex_generator import compile_latex_to_pdf, json_to_latex
from backend.latex_sections import generate_section_opensource
from backend.routes import pdf as pdf_routes
from backend.routes.pdf import PDFCache, _get_latex_template_fingerprint

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "latex-resume-template"


def _collect_bbox_issues(pdf_bytes: bytes) -> tuple[list[tuple], list[tuple]]:
    """Return (margin_overflows, horizontal_overlaps) across all PDF pages."""
    overflows = []
    overlaps = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page_idx, page in enumerate(doc):
            spans = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if not text:
                            continue
                        x0, y0, x1, y1 = span["bbox"]
                        spans.append((text, (x0, y0, x1, y1)))
                        if x0 < 20.0 or x1 > page.rect.width - 20.0:
                            overflows.append((page_idx, text, (x0, y0, x1, y1), page.rect.width))

            for i in range(len(spans)):
                t1, b1 = spans[i]
                for j in range(i + 1, len(spans)):
                    t2, b2 = spans[j]
                    vo = min(b1[3], b2[3]) - max(b1[1], b2[1])
                    ho = min(b1[2], b2[2]) - max(b1[0], b2[0])
                    if vo > 3.0 and ho > 1.0:
                        overlaps.append((page_idx, t1, t2, round(vo, 2), round(ho, 2)))
    finally:
        doc.close()
    return overflows, overlaps


def test_opensource_long_role_and_icon_compile_no_overlap_or_overflow():
    resume_data = {
        "personalInfo": {
            "name": "张示例",
            "phone": "13800000000",
            "email": "example@example.org",
            "github": "github.com/example-demo",
        },
        "experience": [
            {
                "company": "Example Tech",
                "role": "后端开发工程师",
                "date": "2024.06 - 2025.08",
                "description": "<ul><li>负责核心推理服务高并发网关性能优化，将 P99 延迟降低 25%。</li></ul>",
            }
        ],
        "openSource": [
            {
                "name": "Example Community",
                "role": "开源贡献者，负责社区日常维护、问题复现与模块回归验证",
                "date": "2025.09-至今",
                "repo": "https://github.com/example/community-repo",
                "description": "<ul><li>提交并合并多项核心组件修复补丁与回归测试。</li></ul>",
            },
            {
                "name": "OpenAgent 示例框架",
                "role": "开源核心作者，基于多代理编排与流式生成流水线构建交互式技术文档助手。支持实时结构化预览、模板渲染工具链调用与多格式导出扩展。",
                "date": "2025.11-至今",
                "repo": "https://github.com/example/openagent-demo",
                "description": "<ul><li>设计并实现插件化渲染管线与流式状态机，获得社区大量关注与复用。</li></ul>",
            },
        ],
        "skills": [
            "后端：熟悉 Python 与 Go 服务端开发及异步并发模型。",
            "前端：熟悉 React 与 TypeScript 状态管理与渲染优化。",
        ],
        "globalSettings": {
            "openSourceRepoDisplay": "icon",
            "fontSizePreset": "standard",
        },
    }

    latex = json_to_latex(resume_data)
    pdf_bytes = compile_latex_to_pdf(latex, TEMPLATE_DIR).getvalue()
    assert len(pdf_bytes) > 5000

    overflows, overlaps = _collect_bbox_issues(pdf_bytes)
    assert overflows == [], f"Unexpected page margin overflows: {overflows}"
    assert overlaps == [], f"Unexpected horizontal text overlaps: {overlaps}"


def test_datedsubsection_long_right_column_wraps_within_46mm():
    base_latex = json_to_latex({"personalInfo": {"name": "张示例", "email": "example@example.org"}})
    injected_block = (
        "\\section{开源经历}\n"
        "\\datedsubsection{\\textbf{OpenAgent 示例项目}}{长期开源维护与多代理调度框架实现示例长右栏文本验证自动换行}\n"
    )
    latex = base_latex.replace("\\end{document}", f"{injected_block}\n\\end{{document}}")
    pdf_bytes = compile_latex_to_pdf(latex, TEMPLATE_DIR).getvalue()

    overflows, overlaps = _collect_bbox_issues(pdf_bytes)
    assert overflows == [], f"Margin overflow with long right column: {overflows}"
    assert overlaps == [], f"Horizontal overlap with long right column: {overlaps}"

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        right_ys = []
        for block in doc[0].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "")
                    if any(token in text for token in ("长期开源", "多代理", "长右栏", "自动换行")):
                        right_ys.append(round(span["bbox"][1], 1))
        assert len(set(right_ys)) >= 2, f"Expected long right column to wrap >= 2 lines, got y={right_ys}"
    finally:
        doc.close()


def test_opensource_modes_placeholder_dates_and_concise_role():
    long_role = "核心维护者，负责分布式调度队列与多节点心跳协议设计。支持动态扩缩容。"
    inline_lines = generate_section_opensource(
        {
            "openSource": [
                {
                    "name": "Example Queue",
                    "role": long_role,
                    "date": "2025.01-至今",
                    "repo": "https://github.com/example/queue",
                }
            ],
            "globalSettings": {"openSourceRepoDisplay": "inline", "openSourceRepoLabel": "GitHub"},
        }
    )
    inline_tex = "\n".join(inline_lines)
    assert "\\datedsubsectionwithrepo{" in inline_tex
    assert "{2025.01-至今}" in inline_tex
    assert f"\\noindent {long_role}" in inline_tex

    placeholder_lines = generate_section_opensource(
        {
            "openSource": [
                {
                    "name": "ConciseLib",
                    "role": "Core Maintainer",
                    "date": "未提及",
                    "repo": "https://github.com/example/conciselib",
                },
                {
                    "name": "AnotherLib",
                    "role": "核心开发者",
                    "date": "N/A",
                },
            ],
            "globalSettings": {"openSourceRepoDisplay": "below"},
        }
    )
    placeholder_tex = "\n".join(placeholder_lines)
    assert "未提及" not in placeholder_tex
    assert "N/A" not in placeholder_tex
    assert "\\datedsubsection{\\textbf{ConciseLib}}{Core Maintainer}" in placeholder_tex
    assert "\\datedsubsection{\\textbf{AnotherLib}}{核心开发者}" in placeholder_tex


def test_pdf_cache_template_fingerprint_invalidates_on_file_change(tmp_path, monkeypatch):
    tracked = tmp_path / "resume.cls"
    tracked.write_text("% version 1\n", encoding="utf-8")

    monkeypatch.setattr(pdf_routes, "_LATEX_FINGERPRINT_FILES", (tracked,))
    monkeypatch.setattr(pdf_routes, "_TEMPLATE_FP_STAT_KEY", None)
    monkeypatch.setattr(pdf_routes, "_TEMPLATE_FP_VALUE", "")

    fp1 = _get_latex_template_fingerprint()
    fp1_repeat = _get_latex_template_fingerprint()
    assert fp1 == fp1_repeat

    cache = PDFCache()
    payload = {"personalInfo": {"name": "张示例"}}
    key1 = cache.get_cache_key(payload, ["openSource"])
    raw_key1 = cache.get_latex_cache_key("\\documentclass{resume}")

    tracked.write_text("% version 2 changed content\n", encoding="utf-8")
    fp2 = _get_latex_template_fingerprint()
    key2 = cache.get_cache_key(payload, ["openSource"])
    raw_key2 = cache.get_latex_cache_key("\\documentclass{resume}")

    assert fp2 != fp1
    assert key2 != key1
    assert raw_key2 != raw_key1


def test_html_generator_asu_tech_opensource_overview_and_code():
    from backend.html_generator import generate_html_resume

    sample = {
        "basic": {"name": "张示例", "title": "全栈开发工程师", "email": "demo@example.org"},
        "openSource": [
            {
                "name": "OpenAgent",
                "role": "开源核心作者，基于多代理编排构建交互式技术文档助手。支持模板渲染。",
                "date": "2025.11-至今",
                "repo": "https://github.com/example/openagent",
                "description": "<ul><li>使用 <code>Python</code> 实现流式引擎</li></ul>",
            }
        ],
        "sectionOrder": [{"id": "openSource", "title": "开源经历"}],
    }
    html = generate_html_resume(sample, template="asu-tech")
    assert "item-overview" in html
    assert "<code>Python</code>" in html
    assert "companyBar" in html

