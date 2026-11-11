# AI 与 OCR 密钥管理防呆、多进程热同步及 PDF 中文 ToUnicode 嵌入方案

- **日期**：2026-11-10
- **关联 Issue**：[#48](https://github.com/wycocoyu/Resume-Agent/issues/48)
- **发布版本**：`v3.7.1` → `v3.7.3`（提交 `f097616e`、`d6d79c00`、`34337995`）

---

## 1. 背景与解决的核心问题

在收敛并打通 `/settings` 页面统一配置 **DeepSeek（`DEEPSEEK_API_KEY`）** 与 **智谱 GLM-OCR（`ZHIPU_API_KEY`）** 的全链路验收与上线过程中，共闭环解决了三项关键工程问题：

1. **设置页统一配置与连通性实测（`f097616e` / `v3.7.1`）**
   - 收敛历史遗留的 `DASHSCOPE_API_KEY` 错位映射，统一为 `DEEPSEEK_API_KEY`（对话、诊断、润色、导入结构化）与 `ZHIPU_API_KEY`（PDF / 图片 `glm-ocr` 版面识别）。
   - `/settings` 提供掩码预览、单通道与一键全量连通性检测（`GET /api/ai/test-keys`）、二次确认清空能力。

2. **导出 PDF 在无 `cMapUrl` 预览器中中文空白问题（`d6d79c00` / `v3.7.2`）**
   - **根因**：`xelatex`（`xdvipdfmx`）嵌入 `AdobeSongStd-Light.otf` / `AdobeHeitiStd-Regular.otf` 为 `CIDFontType0`（`Adobe-GB1`）时默认省略 `/ToUnicode` CMap 流。部分内置 `pdf.js` 阅读器未配置外部 `cMapUrl`，字体转换失败导致中文字形全部丢失。此前 `pyproject.toml` 未声明 `PyMuPDF`，且 `_ensure_cjk_tounicode_cmaps` 存在 `except ImportError: return pdf_bytes` 静默降级。
   - **方案**：
     - 在 `pyproject.toml` 显式声明 `PyMuPDF>=1.24.0` 与 `click>=8.1`，兼容 `typer >= 0.25` 异常类提取。
     - 在 `backend/latex_generator.py` 优先使用 `import pymupdf`，并新增零第三方依赖的纯 Python 标准库增量 PDF 更新器 `_ensure_cjk_tounicode_cmaps_stdlib`（同时支持 PDF 1.5+ `/Type /ObjStm` + `/Type /XRef` 压缩交叉引用流与经典 ASCII `xref` 表），确保任何运行环境导出的中文 PDF 100% 携带 `/ToUnicode` CMap。

3. **跨通道密钥错填覆盖与多 Worker 热更新延迟问题（`34337995` / `v3.7.3`）**
   - **根因**：线上多进程部署（`uvicorn --workers 2`）下，用户在 `/settings` 误将智谱 `id.secret` 密钥粘贴至首栏 DeepSeek 输入框（或被浏览器密码自动填充串位），原接口未做格式拦截导致直接覆盖 `.env` 中的 `DEEPSEEK_API_KEY` 引发结构化阶段 `401`；同时单 Worker 内存更新无法同步到另一 Worker 进程。
   - **方案**：
     - 新增 `backend/env_keys.py`：
       - `validate_provider_api_key(provider, raw_key)`：拦截脱敏字符提交；强制 `deepseek` 必须以 `sk-` 开头（若检测到含 `.` 的智谱密钥直接抛错提示）；强制 `zhipu` 必须满足 `id.secret` 点号格式且拒绝 `sk-` 前缀密钥。
       - `get_live_api_key(provider)`：基于 `.env` 文件 `st_mtime_ns` 纳秒级变更检测自动重载环境变量到当前 Worker，接入 `resume_assembler.py`、`zhipu_layout.py` 与 `simple.py`，实现多 Worker 零重启即时生效。
     - 前端 `frontend/src/pages/Settings/index.tsx` 为两个密码框补充独立 `name` 与 `autoComplete="new-password"` 阻止浏览器串填，并在提交前即时给出明确防呆提示。

---

## 2. 单份 PDF 简历导入成本基准（实测参考）

导入链路 `POST /api/resume/upload-pdf` 由「步骤 1 智谱 `glm-ocr` 单路提取 Markdown + 步骤 2 `deepseek-flash` 两路并发 JSON 结构化」组成。以典型 1~2 页中文简历（OCR 产物约 `3,600` 字符）计：

| 阶段 | 模型 | 单份消耗量 | 官方费率参考 | 单份成本（RMB） |
| --- | --- | --- | --- | --- |
| 版面识别 OCR | 智谱 `glm-ocr` | `2,500 ~ 5,000` Tokens | `¥0.2 / 百万 Tokens` | **¥0.0005 ~ ¥0.001**（10 元约可识别 8,000 ~ 10,000 份） |
| 结构化组装 | `deepseek-flash` | 约 `6,000` 输入 + `2,000` 输出 Tokens | 输入 `$0.15~$0.30/M`（缓存命中 `$0.003~$0.006/M`），输出 `$0.60~$1.20/M` | **¥0.01 ~ ¥0.03** |
| **合计** | 端到端约 `5 ~ 9s` | — | 按实际 Token 计费 | **约 ¥0.01 ~ ¥0.03 / 份** |

---

## 3. 回归防线

- `backend/tests/test_cli_render.py::test_cjk_tounicode_stdlib_fallback_when_pymupdf_missing`：验证屏蔽 `pymupdf`/`fitz` 时，压缩流 PDF 与经典 `xref` PDF 均正确嵌入 `/ToUnicode`。
- `backend/tests/test_config_key_guard.py`：覆盖跨平台密钥错填拦截、`POST /api/config/keys` 报错不污染原 `.env`、以及多 Worker `.env` `mtime` 变更热加载。
