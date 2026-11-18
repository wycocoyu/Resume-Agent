# CocoCV（原 Resume-Agent）开发者文档索引

本目录汇总面向贡献者与二次开发者的核心架构、数据模型、流式协议与工程决策文档：

| 文档 | 说明 |
| :--- | :--- |
| [前端双应用架构 (`frontend-architecture.md`)](frontend-architecture.md) | `frontend/`（React/Vite 主工作区）与 `web/`（Next.js/BetterAuth 认证代理）边界、状态流与路由说明 |
| [Agent 流式协议 (`agent-streaming.md`)](agent-streaming.md) | `POST /api/agent/stream` SSE 事件帧协议与前端流式渲染约定 |
| [Agent 领域术语表 (`agent-glossary.md`)](agent-glossary.md) | `Manus`、`TurnExecutionState`、`RouteDecision`、`StreamEvent`、`ResumeDataStore` 等核心概念与代码锚点 |
| [数据库表结构参考 (`database-schema.md`)](database-schema.md) | PostgreSQL + BetterAuth 统一身份体系下的 15 张表字段、索引与外键参考 |
| [密钥防呆、多进程热更新与 PDF 中文嵌入 (`ai-ocr-and-pdf-cjk.md`)](ai-ocr-and-pdf-cjk.md) | `/settings` 跨平台密钥校验、多 Worker `.env` 热同步及 XeLaTeX PDF `/ToUnicode` CMap 兜底机制 |
| [ADR-0001：Manus 运行时接缝拆分 (`adr/0001-wave2-manus-decomposition.md`)](adr/0001-wave2-manus-decomposition.md) | 进程内 Agent 编排层与流式运行时职责边界的架构决策记录 |
| [ADR-0002：全栈 TypeScript 绞杀者演进架构 (`adr/0002-typescript-strangler-fig-architecture.md`)](adr/0002-typescript-strangler-fig-architecture.md) | 全栈 TS 绞杀者 4 波次演进规划、五象限审计及 XeLaTeX CJK 零退化硬防线 |
| [决策记录与阶段交付归档 (`decisions/`)](decisions/issue-97-runtime-toggles.md) | 按 Issue 与版本归档的工程决策记录（`issue-80`、`issue-85`、`issue-97`、`v3.12.1`） |

### 模块级专项文档
- **CLI 与 Agent Skill 规范**：[`../skills/resume-agent/SKILL.md`](../skills/resume-agent/SKILL.md) 与 [`../skills/resume-agent/references/schema.md`](../skills/resume-agent/references/schema.md)
- **LaTeX 简历模板说明**：[`../latex-resume-template/README.md`](../latex-resume-template/README.md)
- **模板广场与 27 套工作台模板目录**：[`../frontend/src/data/templates.ts`](../frontend/src/data/templates.ts)（渲染总览见 [`readme/template-overview.png`](readme/template-overview.png)）
