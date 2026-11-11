from __future__ import annotations

from pathlib import Path
import re
import unittest
import yaml

from scripts.check_pr_template import validate_pr_body

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_MINIMAL_LABELS = {"bug", "enhancement", "refactor", "documentation"}
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")


class CheckPRTemplateTests(unittest.TestCase):
    def test_raw_unfilled_pr_template_is_rejected(self) -> None:
        template_text = (REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")
        errors = validate_pr_body(template_text, changed_files=["frontend/src/App.tsx"])
        self.assertGreaterEqual(len(errors), 5)
        self.assertTrue(any("Closes #" in err for err in errors))
        self.assertTrue(any("预期效果" in err for err in errors))
        self.assertTrue(any("修改了前端代码" in err for err in errors))

    def test_calling_pr_approach_final_solution_is_rejected(self) -> None:
        wrong_title_body = """
## 1. 需求与预期效果（What, Why & Expected Outcome）
- **关联 Issue**：Closes #59
- **需求背景与现状痛点**：统一仓库 PR 规范。
- **预期效果（必填）**：提交 PR 必须给出候选参考方案而非自封最终解决方案。

## 2. 解决方案（Solution）
- 直接修改模板。

## 3. 架构取舍与外部调研（Trade-offs & External Benchmarks）
- **参考方案的取舍与权衡（必填）**：无架构分叉，局部直修。

## 4. 验证结果（Verification & Evidence）
`python3 -m unittest` 通过。

## 5. 前端 UI 变化与截图（UI Screenshots & Screen Recording）
不涉及视觉变化：纯工程配置改动。
"""
        errors = validate_pr_body(wrong_title_body, changed_files=[".github/PULL_REQUEST_TEMPLATE.md"])
        self.assertTrue(any("候选参考方案与边界" in err for err in errors))

    def test_missing_expected_outcome_is_rejected(self) -> None:
        body_missing_outcome = """
## 1. 需求与预期效果（What, Why & Expected Outcome）
- **关联 Issue**：Closes #59
- **需求背景与现状痛点**：统一仓库 PR 模板规范。
- **预期效果（必填）**：

## 2. 候选参考方案与边界（Proposed Reference Approach & Scope）
- **本 PR 提交的参考方案**：新增 PR 模板与校验脚本。

## 3. 架构取舍与外部调研（Trade-offs & External Benchmarks）
- **参考方案的取舍与权衡（必填）**：使用 Python 标准库实现，零外部依赖。

## 4. 验证结果（Verification & Evidence）
`python3 -m unittest backend/tests/test_check_pr_template.py` 通过。

## 5. 前端 UI 变化与截图（UI Screenshots & Screen Recording）
不涉及视觉变化：纯后端与工程配置改动。
"""
        errors = validate_pr_body(body_missing_outcome, changed_files=[".github/PULL_REQUEST_TEMPLATE.md"])
        self.assertEqual(len(errors), 1)
        self.assertIn("预期效果", errors[0])

    def test_optional_research_fields_can_be_left_blank(self) -> None:
        body_with_blank_optionals = """
## 1. 需求与预期效果（What, Why & Expected Outcome）
- **关联 Issue**：Closes #59
- **需求背景与现状痛点**：统一仓库 Issue 与 PR 规范。
- **预期效果（必填）**：新建 Issue 自动展示 4 类无花哨表情表单且仅打单一主标签，PR 明确将提交代码定位为候选参考方案并拦截漏贴前端截图。

## 2. 候选参考方案与边界（Proposed Reference Approach & Scope）
- **本 PR 提交的参考方案**：新增 4 类 Issue Forms、PR 模板与 CI 校验脚本。
- **明确不包含（Out of Scope，选填）**：

## 3. 架构取舍与外部调研（Trade-offs & External Benchmarks）
- **参考方案的取舍与权衡（必填）**：无架构分叉，局部直修并采用标准库脚本校验。
- **放弃的其他候选思路（选填）**：
- **同类开源调研与外部参考（选填）**：
- **数据兼容、风险与回滚（选填）**：

## 4. 验证结果（Verification & Evidence）
`python3 -m unittest` 全部通过（Exit Code 0）。

## 5. 前端 UI 变化与截图（UI Screenshots & Screen Recording）
不涉及视觉变化：纯 `.github` 工程模板改动。
"""
        self.assertEqual(validate_pr_body(body_with_blank_optionals, changed_files=[".github/PULL_REQUEST_TEMPLATE.md"]), [])

    def test_frontend_change_requires_screenshot_or_explicit_exemption(self) -> None:
        base_body = """
## 1. 需求与预期效果（What, Why & Expected Outcome）
- **关联 Issue**：Closes #58
- **需求背景与现状痛点**：重塑设置页密钥卡片布局与状态提示。
- **预期效果（必填）**：密钥默认掩码展示，连通性测试无页面跳动并显示耗时。

## 2. 候选参考方案与边界（Proposed Reference Approach & Scope）
- **本 PR 提交的参考方案**：重构 Settings 页卡片结构。

## 3. 架构取舍与外部调研（Trade-offs & External Benchmarks）
- **参考方案的取舍与权衡（必填）**：复用现有 Tailwind 语义类，不引入额外 UI 库依赖。

## 4. 验证结果（Verification & Evidence）
`cd frontend && npm run build` 退出码 0。

## 5. 前端 UI 变化与截图（UI Screenshots & Screen Recording）
__UI_PLACEHOLDER__
"""
        errors = validate_pr_body(
            base_body.replace("__UI_PLACEHOLDER__", "改好了界面样式。"),
            changed_files=["frontend/src/pages/Settings/index.tsx"],
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("修改了前端代码", errors[0])

        with_img = base_body.replace(
            "__UI_PLACEHOLDER__",
            "| ![Before](https://github.com/user-attachments/assets/abc12345) | ![After](https://github.com/user-attachments/assets/def67890) |",
        )
        self.assertEqual(validate_pr_body(with_img, changed_files=["frontend/src/pages/Settings/index.tsx"]), [])

        with_exemption = base_body.replace(
            "__UI_PLACEHOLDER__",
            "不涉及视觉变化：仅提取纯工具类型定义，DOM 结构与样式类名完全未变。",
        )
        self.assertEqual(validate_pr_body(with_exemption, changed_files=["frontend/src/lib/utils.ts"]), [])

    def test_issue_form_templates_are_emoji_free_and_single_label(self) -> None:
        issue_dir = REPO_ROOT / ".github" / "ISSUE_TEMPLATE"
        config_raw = (issue_dir / "config.yml").read_text(encoding="utf-8")
        self.assertIsNone(EMOJI_RE.search(config_raw))
        config = yaml.safe_load(config_raw)
        self.assertIs(config["blank_issues_enabled"], False)

        for filename in ("1-bug-report.yml", "2-feature-request.yml", "3-enhancement-refactor.yml", "4-agent-behavior.yml"):
            raw = (issue_dir / filename).read_text(encoding="utf-8")
            self.assertIsNone(EMOJI_RE.search(raw), f"{filename} still contains emojis")
            form = yaml.safe_load(raw)
            labels = form.get("labels", [])
            self.assertEqual(len(labels), 1, f"{filename} should bind exactly 1 label")
            self.assertIn(labels[0], ALLOWED_MINIMAL_LABELS)

        for filename in ("2-feature-request.yml", "3-enhancement-refactor.yml"):
            form = yaml.safe_load((issue_dir / filename).read_text(encoding="utf-8"))
            by_id = {item.get("id"): item for item in form["body"] if item.get("id")}
            self.assertTrue(by_id["expected_outcome"].get("validations", {}).get("required"))
            self.assertIn("候选参考方案", by_id["reference_approach"]["attributes"]["label"])
            self.assertFalse(by_id["reference_approach"].get("validations", {}).get("required", False))


if __name__ == "__main__":
    unittest.main()
