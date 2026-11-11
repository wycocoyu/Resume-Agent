#!/usr/bin/env python3
"""Validate GitHub Pull Request descriptions against CocoCV's PR template rules.

Enforces:
1. All 5 core sections exist in the PR body.
2. Required items (including `预期效果`) contain substantive content rather than empty template placeholders.
3. Optional items (`调研对比与参考方案`, `明确不包含`, etc.) may be omitted or left blank without failing CI.
4. When changed files touch `frontend/` or `web/` (excluding test-only files and changelog.ts), Section 5
   must include either visual media (image/video link) or an explicit `不涉及视觉变化：<reason>` declaration.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REQUIRED_SECTIONS: list[tuple[str, str]] = [
    ("## 1. 需求与预期效果", "1. 需求与预期效果（What, Why & Expected Outcome）"),
    ("## 2. 方案是什么", "2. 方案是什么（Solution & Scope）"),
    ("## 3. 架构取舍与参考方案", "3. 架构取舍与参考方案（Trade-offs & References）"),
    ("## 4. 验证结果", "4. 验证结果（Verification & Evidence）"),
    ("## 5. 前端 UI 变化与截图", "5. 前端 UI 变化与截图（UI Screenshots & Screen Recording）"),
]

HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
MEDIA_PATTERNS = [
    re.compile(r"!\[[^\]]*\]\([^)]+\)"),
    re.compile(r"<img\b", re.IGNORECASE),
    re.compile(r"<video\b", re.IGNORECASE),
    re.compile(r"https://github\.com/user-attachments/assets/[A-Za-z0-9_-]+"),
    re.compile(r"https?://\S+\.(?:png|jpg|jpeg|webp|gif|mp4|mov|webm)\b", re.IGNORECASE),
]
NO_UI_CHANGE_RE = re.compile(r"不涉及视觉变化\s*[：:]\s*(\S.{3,})")

PLACEHOLDER_LINES = {
    "-",
    "- **关联 Issue**：Closes #",
    "- **需求背景与现状痛点**：",
    "- **预期效果（必填）**：",
    "- **预期效果**：",
    "- **本 PR 包含的核心改动**：",
    "- **明确不包含（Out of Scope，选填）**：",
    "- **明确不包含（Out of Scope）**：",
    "- **变更类型**：",
    "- **架构取舍与决策（必填）**：",
    "- **调研对比与参考方案（选填）**：",
    "- **数据兼容、风险与回滚（选填）**：",
    "- **手工验证路径与未覆盖盲区（选填）**：",
    "# 实际运行的构建或测试命令及结果",
    "| 改动前（Before） | 改动后（After） |",
    "| :---: | :---: |",
    "| 请贴图或填写不涉及说明 | 请贴图或填写不涉及说明 |",
}


def strip_comments(text: str) -> str:
    return HTML_COMMENT_RE.sub("", text)


def extract_sections(body: str) -> dict[str, str]:
    cleaned = strip_comments(body or "")
    matches: list[tuple[int, int, str]] = []
    for prefix, _label in REQUIRED_SECTIONS:
        idx = cleaned.find(prefix)
        if idx != -1:
            line_end = cleaned.find("\n", idx)
            content_start = len(cleaned) if line_end == -1 else line_end + 1
            matches.append((idx, content_start, prefix))

    next_h2 = [m.start() for m in re.finditer(r"^##\s+", cleaned, flags=re.MULTILINE)]
    sections: dict[str, str] = {}
    for idx, content_start, prefix in matches:
        later = [pos for pos in next_h2 if pos > idx]
        end = min(later) if later else len(cleaned)
        sections[prefix] = cleaned[content_start:end].strip()
    return sections


def meaningful_content(section_text: str) -> str:
    kept: list[str] = []
    for raw_line in section_text.splitlines():
        line = raw_line.strip()
        if not line or line in PLACEHOLDER_LINES:
            continue
        if line.startswith("- [ ]"):
            continue
        if line in {"```", "```bash", "```text", "```sh"}:
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def has_expected_outcome(sec1_text: str) -> bool:
    """Verify `预期效果` is explicitly filled in Section 1."""
    lines = sec1_text.splitlines()
    for i, raw in enumerate(lines):
        m = re.search(r"预期效果(?:（必填）)?\*{0,2}\s*[：:]\s*(.*)", raw)
        if m:
            inline_val = m.group(1).strip()
            if len(inline_val) >= 4:
                return True
            sub_lines: list[str] = []
            for follow in lines[i + 1 :]:
                stripped = follow.strip()
                if not stripped:
                    continue
                if re.match(r"^-\s*\*\*", stripped) and not stripped.startswith("  "):
                    break
                sub_lines.append(stripped.lstrip("-* ").strip())
            if len("".join(sub_lines)) >= 4:
                return True
            return False
    return False


def is_ui_code_path(file_path: str) -> bool:
    norm = file_path.strip().lstrip("./")
    if not (norm.startswith("frontend/") or norm.startswith("web/")):
        return False
    lower = norm.lower()
    if any(seg in lower for seg in (".test.", ".spec.", "__tests__/", "/data/changelog.ts")):
        return False
    return lower.endswith((".tsx", ".ts", ".jsx", ".js", ".css", ".scss", ".html"))


def has_ui_evidence_or_exemption(section_5_text: str) -> bool:
    for pattern in MEDIA_PATTERNS:
        if pattern.search(section_5_text):
            return True
    return bool(NO_UI_CHANGE_RE.search(section_5_text))


def validate_pr_body(body: str, changed_files: list[str] | None = None) -> list[str]:
    errors: list[str] = []
    if not (body or "").strip():
        return ["PR 描述为空，请使用 .github/PULL_REQUEST_TEMPLATE.md 填写完整说明。"]

    sections = extract_sections(body)
    for prefix, label in REQUIRED_SECTIONS:
        if prefix not in sections:
            errors.append(f"缺少必填章节标题：{label}")
            continue
        substantive = meaningful_content(sections[prefix])
        if len(substantive) < 6:
            errors.append(f"章节「{label}」未填写实质内容（不能仅保留空模板占位符）。")

    if "## 1. 需求与预期效果" in sections:
        sec1 = sections["## 1. 需求与预期效果"]
        if re.search(r"Closes\s*#\s*$", sec1, flags=re.MULTILINE):
            errors.append("第 1 节「关联 Issue」仍为空占位符 `Closes #`，请填写具体 Issue 编号（如 `Closes #59`）或改为 `无（已在下文说明背景）`。")
        if not has_expected_outcome(sec1):
            errors.append("第 1 节缺少必填项「预期效果」，请明确写出合入后用户可感知的预期效果或量化指标。")

    ui_files = [f for f in (changed_files or []) if is_ui_code_path(f)]
    if ui_files and "## 5. 前端 UI 变化与截图" in sections:
        if not has_ui_evidence_or_exemption(sections["## 5. 前端 UI 变化与截图"]):
            sample = ", ".join(ui_files[:3])
            errors.append(
                f"本次 PR 修改了前端代码（{sample}），第 5 节必须附上截图/视频链接，或显式注明 `不涉及视觉变化：<具体原因>`。"
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate PR body against CocoCV PR template rules.")
    parser.add_argument("--body-file", type=Path, help="Path to file containing PR markdown body.")
    parser.add_argument("--event-path", type=Path, help="Path to GitHub Actions GITHUB_EVENT_PATH JSON.")
    parser.add_argument("--changed-files-file", type=Path, help="Newline-separated list of changed file paths.")
    args = parser.parse_args(argv)

    body = ""
    if args.body_file:
        body = args.body_file.read_text(encoding="utf-8")
    elif args.event_path and args.event_path.exists():
        payload = json.loads(args.event_path.read_text(encoding="utf-8"))
        body = (payload.get("pull_request") or {}).get("body") or ""
    else:
        body = os.environ.get("PR_BODY", "")

    changed_files: list[str] = []
    if args.changed_files_file and args.changed_files_file.exists():
        changed_files = [
            line.strip()
            for line in args.changed_files_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    errors = validate_pr_body(body, changed_files=changed_files)
    if errors:
        print("PR 模板门禁校验未通过：", file=sys.stderr)
        for err in errors:
            print(f"  - {err.strip()}", file=sys.stderr)
        return 1

    print("PR 模板门禁校验通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
