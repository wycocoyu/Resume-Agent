# Contributing to Resume-Agent (CocoCV) / 参与贡献

Thank you for your interest in contributing to **Resume-Agent ([cococv.cn](https://cococv.cn))**! Before making changes, please review [`AGENTS.md`](AGENTS.md) for architecture notes and project conventions.

感谢你参与 **Resume-Agent（[cococv.cn](https://cococv.cn)）** 开源共建！在开始修改前，请先阅读 [`AGENTS.md`](AGENTS.md) 了解项目架构与工程约定。

## Project Structure / 目录结构

- `frontend/`: React 18 + TypeScript + Vite + Tailwind workspace, AI chat stream, and LaTeX PDF preview.
- `backend/`: FastAPI + Python 3.12+ API server, in-process AI agent (`backend/agent/`), and XeLaTeX compiler pipeline.
- `web/`: Next.js authentication service (optional for local single-user development).
- `skills/`: CLI (`resume-agent`) and agent skill packages for Codex / Claude Code.

## Local Development & Verification / 本地开发与校验

Install dependencies and run checks before submitting a Pull Request:

提交 Pull Request 前，请在本地完成前后端校验：

```bash
# 1. Frontend typecheck & production build / 前端类型检查与生产构建
cd frontend && npm run build

# 2. Backend unit tests / 后端单元测试
python -m pytest backend/tests/ -q
```

## Pull Request Guidelines / 提交规范

- **Minimal diffs / 最小化改动**: Keep changes focused on a single issue or feature; do not modify unrelated files.
- **Commit messages / 提交信息**: Follow Conventional Commits (e.g., `feat(editor): ...`, `fix(latex): ...`, `docs(readme): ...`).
- **Validation evidence / 验证结果**: Clearly describe the problem, resulting behavior, and actual test commands executed in your PR description.
- **No secrets or PII / 严禁提交密钥与隐私数据**: Never include `DEEPSEEK_API_KEY`, `ZHIPU_API_KEY`, `JWT_SECRET_KEY`, production database URLs, or real personal resume PDFs/JSONs in commits or PRs.
