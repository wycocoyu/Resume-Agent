# ADR 0002 · 全栈 TypeScript 绞杀者（Strangler Fig）演进架构与防线契约

- 状态：Accepted（2026-11-15，架构委员会批准，对应 Issue #63 / #52）
- 关联：
  - [`0001-wave2-manus-decomposition.md`](0001-wave2-manus-decomposition.md)
  - [`../agent-streaming.md`](../agent-streaming.md)
  - [`../ai-ocr-and-pdf-cjk.md`](../ai-ocr-and-pdf-cjk.md)
  - [`../frontend-architecture.md`](../frontend-architecture.md)

---

## 1. 架构演进背景与问题定义

CocoCV (原 Resume-Agent) 历史架构呈现典型的多语言分层断裂特征：
1. **类型双轨分化**：前端使用 TypeScript 静态类型（`frontend/src/types/resume.ts`），后端使用 Python Pydantic（`backend/resume_models.py`、`backend/agent/web/streaming/events.py`），导致 API 契约与 SSE 事件缺乏单一真实信源（SSOT），字段重命名或可选性微调极易产生隐蔽运行时缺陷。
2. **运行时冗余与序列化开销**：前端 Node.js/Vite 构建与后端 Python FastAPI 双栈并存，进程间通信、会话生命周期与流式事件需在 Python 字典与 JSON 字符串间反复编解码。
3. **维护摩擦**：随着单协程线性事件流运行时（Pi-Core）在 Python 侧定型（PR #67, #42），全栈 TypeScript 成为长期收敛、消除历史分层摩擦、提升开发者体验与部署效率的确定性方向（Issue #63）。

然而，全面推翻 Python 后端并重写的「大爆炸式」（Big Bang）重构具有极高的工程风险，尤其是已稳定运行且具备工业级稳定性的中文 XeLaTeX PDF 编译与 `/ToUnicode` CMap 乱码防护链路。

为此，本项目正式确立采用 **绞杀者模式（Strangler Fig Pattern）**，通过 4 个渐进波次（Wave 0 ~ Wave 3）逐步将系统主干收敛至 TypeScript 全栈，并在整个迁移生命周期中设立严格不可逾越的物理防线。

---

## 2. 五象限技术现状审计（5-Quadrant Audit）

| 象限 | 组件与技术栈 | 现状与核心资产 | 迁移风险与约束 | 演进策略 |
|---|---|---|---|---|
| **Q1: Frontend** | React 18, Vite 5, TypeScript 5, Tailwind CSS, Tiptap | 现代 SPA 架构，状态管理（`useResumeData`、`storageCompat`）、双引擎实时预览、Tailwind 主题系统、自包含 HTML 导出 | 低风险；既有类型完善，需引入 Zod SSOT 并对接统一包 | 作为第一消费者率先消费 `@cococv/schema` |
| **Q2: Backend API** | FastAPI, Uvicorn, Python 3.12, SQLite / PostgreSQL | `/api/agent/*`、`/api/resumes/*`、`/api/auth/*`，基于 async/await 的 REST 路由 | 中等风险；需保障下游客户端与第三方工具 100% 向下兼容 | 通过 Wave 1 引入 TypeScript Hono 反向代理接缝，逐步绞杀接管路由 |
| **Q3: Pi-Core Runtime** | Python 3.12 `backend/agent/pi_core/` | 单协程线性事件循环运行时、上下文压缩（Summarizer）、SSE 事件信封、工具调用适配器 | 中等风险；需保证流式事件时序、心跳与取消语义一致性 | Wave 2 移植为 TypeScript 原生运行时（`packages/agent-core`） |
| **Q4: LaTeX PDF Compiler** | Python 3.12, XeLaTeX, PyMuPDF, `_ensure_cjk_tounicode_cmaps` | 双层 CJK `/ToUnicode` CMap 补丁注入、`_pdf_cache` SHA256 缓存、本地字体符号链接、原生分页检测 | **极高风险**；中文字符提取率、字形映射及 PDF/A 标准强依赖现有二进制与 CMap 管道 | **硬防线**：坚决维持 Python XeLaTeX 编译微服务，直至黄金对拍测试 100% 字节级一致 |
| **Q5: CLI & MCP** | Python Click / `argparse`, Python MCP SDK, stdio/sse 协议 | `cococv` / `resume-agent` 双别名二进制、本地简历解析、HTML/CDP 渲染导出、CocoCV MCP Server | 低至中等风险；CLI 需支持 Node.js npx 与 Python 两种分发 | 双轨支持；最终通过 `@cococv/cli` 统一为零依赖 Node 可执行脚本 |

---

## 3. 四波次渐进迁移路径（4-Wave Migration Plan）

```
[Wave 0: Shared Schema & Contracts]
  │   - 设立 pnpm-workspace.yaml (packages/*, frontend)
  │   - 创建 packages/schema (Zod SSOT: ResumeDataSchema, StreamEventSchema)
  │   - 创建 packages/proxy (Hono 契约网关骨架与健康检查)
  ▼
[Wave 1: Edge API Gateway / Proxy]
  │   - Hono 代理成为默认边缘接入层（端口 9000 或前置反向代理）
  │   - 统一跨端校验与错误处理契约，无缝穿透转发至 FastAPI (端口 9100)
  │   - 率先绞杀接管静态资源、认证中间件与健康检查路由
  ▼
[Wave 2: Pi-Core TS Native Port]
  │   - 移植 Pi-Core 单协程线性事件流运行时至 packages/agent-core (TS 原生)
  │   - 统一 LLM Client (OpenAI-compatible / Anthropic / Local)
  │   - /api/agent/stream 由 Hono + AgentCore 原生承接，彻底剥离 Python Agent 依赖
  ▼
[Wave 3: Full-Stack Convergence & Python Minimization]
  │   - REST API 业务逻辑（/api/resumes, /api/auth 等）全量收敛至 TypeScript
  │   - Python 后端退化并收缩为单一专职微服务：`cococv-latex-daemon` (专注于 XeLaTeX + CMap)
  │   - Node.js / Bun 作为主服务入口，实现全栈零摩擦部署
```

### 3.1 Wave 0: 共享契约与工程基石（当前落地交付）
- **单一事实来源（SSOT）**：在 `packages/schema` 中以 Zod 定义全量 `ResumeDataSchema` 与 `StreamEventSchema`，导出零成本推导的 TypeScript 类型。
- **工作区拓扑**：配置根目录 `pnpm-workspace.yaml`，打通 `packages/*` 与 `frontend` 的依赖链接。
- **绞杀接缝骨架**：在 `packages/proxy` 中实现轻量级 Hono 反向代理，支持请求转发、健康探针与契约断言，保障测试套件可独立闭环。

### 3.2 Wave 1: 边缘反向网关（Edge API Gateway）
- 引入 Hono 作为前端与后端的统一接缝。
- 外部所有 HTTP/SSE 流量打入 Hono 网关；网关按路由规则将 `/api/pdf/*` 转发给 Python 后端，其余接口按可用性做分流灰度。
- 前端代码零修改，无需感知后端架构变迁。

### 3.3 Wave 2: Pi-Core 运行时原生化（TS Agent Core）
- 将 `backend/agent/pi_core/` 的单协程线性循环、EventBus、ToolRunner 纯结构移植至 `@cococv/agent-core`。
- 借助 TypeScript 标准 `AsyncIterable` 与 Fetch `ReadableStream` 消除 WebSocket 与 SSE 适配层差异。

### 3.4 Wave 3: 全栈收敛与 Python 极致收缩
- 业务数据库访问、CRUD 路由与权限校验全面收归 TS 引擎。
- Python 依赖池彻底瘦身，仅保留轻量级 XeLaTeX 渲染守护进程。

---

## 4. 绝对物理防线：XeLaTeX CJK `/ToUnicode` CMap 零退化保障

在整个全栈 TypeScript 绞杀演进过程中，确立以下硬防线原则（The Hard Defense Line）：

1. **绝对禁止过早废弃 Python XeLaTeX 编译管道**：
   - 简历排版与中文排版对字距、微排版（microtype）、双语断行有极致苛刻的要求。
   - `backend/latex_compiler.py` 中的 `_ensure_cjk_tounicode_cmaps`（同时涵盖 PyMuPDF 高速路径与纯 Python 标准库回退路径）确保了生成的 PDF 可以在 Adobe Acrobat、Apple Preview、Chrome、Edge 中 100% 复制中文且复制文本绝对无乱码、无方块（ToUnicode 映射率必须维持 100%）。
2. **黄金对拍验证门禁（Golden Byte-Identical & Extraction Parity）**：
   - 任何替代编译方案（无论是 Node.js wasm 编译、Typst、或 headless Chrome CDP 渲染）必须先通过自动化对拍套件：
     * 中文字符复制准确率 100%（涵盖张三、清华大学、计算机科学与技术等真实用例）。
     * PDF 结构中所有 Type0 字体对象必须具备有效的 `/ToUnicode` 映射字典。
     * 在对拍套件完全通过之前，Python XeLaTeX 编译守护服务作为核心生产服务永久保留并受 CI 严密防护。

---

## 5. 工程治理与 CI 质量门禁契约（Issue #52）

1. **版本发布与 Changelog 纯日期硬约束**：
   - `frontend/src/data/changelog.ts` 为版本发布唯一凭据。
   - 严禁在 release entry 的 `date` 字段包含具体时间戳（如禁止 `YYYY-MM-DD HH:mm`），必须严格遵守 `YYYY-MM-DD` 纯日期 ISO 格式。
   - 版本号必须严格遵循语义化版本（SemVer 2.0.0）。
   - 自动化门禁脚本 `scripts/check-changelog.mjs` 作为 CI 与 pre-push 的阻断性执行项。
2. **确定性 CI 矩阵**：
   - CI 流水线必须在全新隔离环境中依次执行：
     1. `node scripts/check-changelog.mjs`
     2. `npm run test` / `vitest run`（前端与 packages 单元测试）
     3. `npm run build`（前端生产编译零报错）
     4. `pytest`（后端回归测试零失败）

---

## 6. 后果与收益评估

- **正面收益**：
  - 前后端契约统一由 Zod 管理，彻底告别前后端类型不一致的联调低效；
  - 绞杀者模式允许渐进式重构，每一步均可在 CI 中完全验证，系统可用性始终保持 100%；
  - 明确保护了高难度的中文 LaTeX CMap 编译技术壁垒，杜绝重构导致的商业核心能力退化。
- **负面成本与代价**：
  - 在 Wave 0 与 Wave 1 阶段，工程中需暂时维护 pnpm workspace 与 Python 虚拟环境双生态；
  - 需维护 API 代理与契约测试对齐。
