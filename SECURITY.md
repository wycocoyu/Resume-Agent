# Security Policy / 安全策略

## Reporting a Vulnerability / 报告安全漏洞

Please use GitHub Security Advisories ("Report a vulnerability" under the **Security** tab) to report security issues privately to maintainers.

请优先使用 GitHub 仓库 **Security** 标签页下的私密报告功能（Report a vulnerability）向维护者反馈安全漏洞。

Do **NOT** submit the following in public Issues, Discussions, or Pull Requests:

请**切勿**在公开的 Issue、Discussion 或 Pull Request 中提交以下内容：

- API keys or tokens (`DEEPSEEK_API_KEY`, `ZHIPU_API_KEY`, `JWT_SECRET_KEY`, Cookies, or session tokens);
- Internal server IPs, database connection strings (`POSTGRESQL_URL`), or private deployment configurations;
- Unredacted logs or real users' personal resume data (PII).

报告应包含受影响版本、复现步骤、潜在影响范围及修复建议。维护者收到后会第一时间确认并跟进修复。

## Supported Versions / 支持版本

Only the latest version on the `main` branch is actively maintained with security updates.

目前仅对 `main` 主干分支的最新版本提供安全更新维护。

## Deployment Responsibility / 部署安全建议

This repository does not include production credentials. Self-hosted deployers should configure secrets exclusively via local `.env` files (which are ignored by `.gitignore`) or secret managers, and keep API keys rotated regularly.

本仓库不包含任何生产环境凭据。自托管部署时请仅通过本地 `.env`（已被 `.gitignore` 忽略）或密钥管理服务注入敏感配置，切勿将真实密钥硬编码入库。
