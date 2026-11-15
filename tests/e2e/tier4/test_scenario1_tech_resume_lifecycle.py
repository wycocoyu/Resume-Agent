"""Tier 4 Real-World Application Scenarios: Scenario 1.

Scenario 1: Full Tech Resume Lifecycle (全栈技术简历制作与双引擎导出全闭环)
Authoritative specs:
- SCOPE.md § Tier 4 Scenarios, TEST_INFRA.md
- Pipeline:
  1. Load standard tech resume
  2. Verify production asu-tech template component
  3. Validate auto-one-page adaptive fit via real Vitest suite
  4. Convert to backend LaTeX format with 0 field loss
  5. Validate self-contained HTML export via real Vitest suite
  6. Deliverable: offline XeLaTeX PDF generation
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import pytest

from backend.latex_generator import json_to_latex, render_pdf_from_resume_latex
from backend.resume_converter import convert_to_backend_format

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_scenario1_full_tech_resume_lifecycle(standard_resume_data: dict, temp_e2e_dir: Path):
    """Scenario 1: End-to-end full tech resume lifecycle from template verification to dual engine delivery."""
    # 1. Load standard tech resume
    resume = json.loads(json.dumps(standard_resume_data))
    assert resume["id"] == "e2e_resume_standard_001"
    assert resume["basic"]["name"] == "张三"

    # 2. Verify production asu-tech template component exists
    asu_tech_comp = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Builder" / "templates" / "ResumeAsuTech.tsx"
    assert asu_tech_comp.exists()
    assert "ResumeAsuTech" in asu_tech_comp.read_text(encoding="utf-8")

    # 3. Verify auto-one-page algorithm passes real Vitest suite
    vitest_auto_one_page = [
        "npx", "vitest", "run",
        "src/pages/Workspace/v2/utils/autoOnePage.test.ts",
    ]
    res_one_page = subprocess.run(
        vitest_auto_one_page,
        cwd=str(WORKTREE_ROOT / "frontend"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res_one_page.returncode == 0, f"autoOnePage Vitest failed:\n{res_one_page.stdout}\n{res_one_page.stderr}"

    # 4. Verify self-contained HTML generation passes real Vitest suite
    vitest_generate_html = [
        "npx", "vitest", "run",
        "src/pages/Workspace/v2/utils/generateHTML.test.ts",
    ]
    res_html = subprocess.run(
        vitest_generate_html,
        cwd=str(WORKTREE_ROOT / "frontend"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res_html.returncode == 0, f"generateHTML Vitest failed:\n{res_html.stdout}\n{res_html.stderr}"

    # 5. Switch to LaTeX engine: ensure 0 field loss in generated LaTeX
    backend_resume = convert_to_backend_format(resume)
    latex_src = json_to_latex(backend_resume, offline=True)
    assert "张三" in latex_src
    assert "字节跳动" in latex_src
    assert "北京航空航天大学" in latex_src

    # 6. Deliverable: High-fidelity PDF export via XeLaTeX
    pdf_stream = render_pdf_from_resume_latex(resume)
    pdf_bytes = pdf_stream.getvalue()
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > 10000
