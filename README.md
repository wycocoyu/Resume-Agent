<div align="center">

# 🤖 Resume-Agent

### 一句话输入，AI 帮你生成可编辑、可诊断、可导出的专业简历

<p>
  <a href="https://cococv.cn"><img src="https://img.shields.io/badge/🌐_在线体验-cococv.cn-36BCF7?style=for-the-badge" alt="Live Demo" /></a>
  <a href="https://github.com/wycocoyu/Resume-Agent/stargazers"><img src="https://img.shields.io/github/stars/wycocoyu/Resume-Agent?style=for-the-badge&color=yellow" alt="Stars" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue?style=for-the-badge" alt="License" /></a>
</p>

<p>
  <img src="https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white" alt="React 18" />
  <img src="https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white" alt="TypeScript" />
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white" alt="Python 3.12+" />
  <img src="https://img.shields.io/badge/DeepSeek-4D6BFE" alt="DeepSeek" />
  <img src="https://img.shields.io/badge/LaTeX-008080?logo=latex&logoColor=white" alt="LaTeX" />
</p>

<img src="assets/readme/2026-03-27-home.png" alt="首页" width="90%" />

</div>

---

## 📖 项目简介

**Resume-Agent** 是一个面向中文求职场景的全栈 AI 简历系统，覆盖 **智能导入 / 一句话生成 → AI 简历诊断与 ATS 检查 → 自然语言对话精修 → 可视化排版与 LaTeX PDF 导出** 的完整闭环。

## ✨ 核心特性（v3.6）

| 模块 | 核心能力 |
|:--|:---|
| 🚀 **一键生成与 PDF/图片导入** | 支持一句话描述生成简历，或上传已有 PDF / 图片简历，通过 `glm-ocr` + `glm-4.6v` 视觉识别自动还原为结构化模块 |
| 🔍 **可解释简历诊断与 ATS 检查** | 评分理由逐字引用简历原文；针对目标岗位 JD 输出 **ATS 兼容检查清单**，精准指出套话、空泛表达与技能掌握度缺口 |
| 🛠️ **单条应用与缺口补齐** | 诊断建议支持逐条点击「帮我改这条」独立生效；需要补充真实数据（如量化指标）的条目支持弹窗「补充信息并修改」 |
| 💬 **进程内 Agent 对话改写** | 自然语言增量修改，精准区分「工作经历」「实习经历」「项目经历」「开源经历」，改后自动保持分点列表层级 |
| 🎨 **双栏可视化编辑与精细排版** | 左编辑右实时预览（支持一键收起预览、切换清新/深色皮肤）；支持独立工作经历板块、工作年限、项目名/仓库地址独立字号、正文蓝字重点高亮及学校/公司 Logo 展示 |
| 📄 **LaTeX PDF 极速直连导出** | 服务端 XeLaTeX 高清编译，支持同源直连与 Base64 流式传输；导出时自动归一化中英混排引号与连接符，避免招聘系统（ATS）解析断词 |

## 📸 界面预览

<table>
<tr>
<td width="50%"><b>Dashboard 简历管理</b><br/><img src="assets/readme/2026-03-27-dashboard.png" alt="Dashboard" /></td>
<td width="50%"><b>双栏可视化工作区</b><br/><img src="assets/readme/2026-03-27-workspace.png" alt="工作区" /></td>
</tr>
<tr>
<td width="50%"><b>AI 简历诊断与对话精修</b><br/><img src="assets/readme/2026-05-23-agent-chat.png" alt="AI 对话" /></td>
<td width="50%" valign="middle" align="center">👉 <a href="https://cococv.cn"><b>立即体验在线版（cococv.cn）</b></a></td>
</tr>
</table>

## 🏗️ 技术架构与目录结构

| 目录 / 层级 | 技术栈 | 职责说明 |
|:--|:--|:--|
| `frontend/` | React 18 · TypeScript · Vite · Tailwind | 简历工作区、双栏实时预览、AI 助手对话与 Dashboard |
| `backend/` | FastAPI · Python 3.12+ · SQLAlchemy | 主业务 API、进程内 `backend/agent/` 智能体引擎、PDF 编译路由 |
| `web/` | Next.js 16 · BetterAuth · PostgreSQL | 统一身份认证服务（线上共享会话；本地单机体验可按需启用） |
| **AI 模型层** | DeepSeek 官方（`deepseek-flash` / `deepseek-v4-pro`）· 智谱 GLM（`glm-ocr` / `glm-4.6v`） | DeepSeek 负责对话、诊断与结构化生成；智谱负责 PDF/图片 OCR 与版面识别 |
| **PDF 引擎** | XeLaTeX · CTeX | 服务端中英混排编译、字体渲染与 ATS 字符归一化 |

## 🚀 本地快速启动

### 1. 环境准备

- **Python** `3.12+`（推荐使用 [`uv`](https://github.com/astral-sh/uv) 管理依赖）
- **Node.js** `18+`
- **XeLaTeX**（PDF 编译必需）
  - macOS：安装 [MacTeX](https://www.tug.org/mactex/)
  - Ubuntu / Debian：`sudo apt install texlive-xetex texlive-lang-chinese fonts-noto-cjk`

### 2. 克隆仓库与安装依赖

```bash
git clone https://github.com/wycocoyu/Resume-Agent.git
cd Resume-Agent

# 1) 安装后端依赖
pip install uv
uv pip install -r requirements.txt

# 2) 安装前端依赖
cd frontend && npm install && cd ..
```

### 3. 配置环境变量

复制根目录 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

在 `.env` 中填入以下核心配置（[`config.toml`](config.toml) 与 [`backend/llm.py`](backend/llm.py) 默认从环境变量读取）：

```ini
# 必填：DeepSeek 官方 API Key（驱动 AI 对话、简历诊断与结构化生成）
# 申请地址：https://platform.deepseek.com/
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx

# 推荐：智谱 GLM API Key（PDF / 图片简历上传导入的 OCR 与视觉识别必需）
# 申请地址：https://open.bigmodel.cn/
ZHIPU_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 本地安全密钥（任意随机字符串即可）
JWT_SECRET_KEY=replace-with-any-random-string
```

> 💡 数据库默认使用本地 SQLite，开箱即用；如需切换 PostgreSQL，可在 `.env` 中启用 `USE_POSTGRESQL=true` 与 `POSTGRESQL_URL`。前端默认连接 `http://127.0.0.1:9000`，如需自定义可执行 `cp frontend/.env.example frontend/.env.local`。

### 4. 启动前后端服务

```bash
# 终端 1：启动后端 API 与内置 Agent（端口 9000）
python -m uvicorn backend.main:app --host 127.0.0.1 --port 9000

# 终端 2：启动前端开发服务器（端口 5173）
cd frontend && npm run dev
```

启动后访问：

| 服务 | 本地地址 |
|:--|:--|
| 🖥️ **前端应用** | http://localhost:5173 |
| ⚙️ **后端 API** | http://127.0.0.1:9000 |
| 📖 **Swagger 接口文档** | http://127.0.0.1:9000/docs |

### 5. 构建与测试校验

```bash
# 前端类型检查与生产构建
cd frontend && npm run build

# 后端单元测试
python -m pytest backend/tests/ -q
```

## 🤝 参与贡献

欢迎通过 [Issues](https://github.com/wycocoyu/Resume-Agent/issues) 反馈问题或提交 [Pull Requests](https://github.com/wycocoyu/Resume-Agent/pulls)。如果本项目对你有帮助，欢迎点亮右上角 ⭐ **Star** 支持！

## 📄 开源许可

本项目基于 [MIT License](LICENSE) 开源。
