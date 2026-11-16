# Resume Agent (CocoCV)

Build, import, tailor, validate, preview, and render Workspace v2 `ResumeData` JSON resumes locally with zero mandatory login, using either the installed `cococv` / `resume-agent` CLI or the bundled zero-dependency Python helper (`scripts/cococv_local.py`).

Invoke this skill in {{harness_display}} with `{{invoke_syntax}}`.

## Core Guardrails

1. **Never fabricate candidate facts.** Do not invent employers, schools, degrees, dates, GPAs, project metrics, open-source links, or awards. Populate only facts stated by the user or present in user-provided source files. When key facts are missing, mark them explicitly with `【待补】` (e.g. `峰值 QPS 由 2000 提升至【待补】`), ask concise follow-up questions, or disable unused sections via `menuSections[*].enabled = false`.
2. **Local-first and login-free by default.** Keep `resume.json`, `.html`, `.png`, and `.pdf` outputs on the user's local disk. Do NOT require terminal login tokens up front or upload user data unless the user explicitly asks for `handoff` or `sync`.
3. **Guide before running commands.** Never dump raw CLI flags or JSON templates at a user who just wants a resume. Start by silently probing the environment, then warmly route the user through the intake paths below.
4. **Keep validation read-only and mandatory.** Always validate `resume.json` before rendering or handing off. Fix reported field paths directly in the JSON file.
5. **Stay offline by default.** `cococv render` / `resume-agent render` runs with zero network access unless the user explicitly passes `--online`.
6. **Page balance and density self-check.** When `.png` previews are generated, inspect them visually to catch 2-3 line orphan overflow onto a second page or excessive whitespace, and adjust bullets or spacing accordingly.

## Step 0 · Silent Environment Probe

Before replying to a new request, run the bundled probe quietly to see which local capabilities exist on this machine:

```bash
python3 scripts/cococv_local.py env --json
```

- **Full local CLI (`cococv` / `resume-agent` installed)**: supports `.html`, multi-page `.png`, Headless Chrome CDP `.pdf`, and local `XeLaTeX` `.pdf` when installed.
- **Zero-dependency fallback (bare Python 3.10+ only)**: `python3 scripts/cococv_local.py` handles `env`, `read-source`, `templates`, `init`, `validate`, `render`, and `handoff` locally with zero `pip install`, zero backend server, and zero login.
- **Harness installation**:
  ```bash
  resume-agent skill install --harness {{harness_id}} --dry-run
  resume-agent skill install --harness {{harness_id}}
  ```

## Step 1 · Conversational Intake & Branch Routing

When the user starts a fresh conversation without already handing over full details or a file path, greet briefly and ask **which starting path** they want (one short prompt, plain language, no jargon). Example first reply:

> 「我是 CocoCV 简历助手（全程本地免登录，无需本机装 LaTeX）。先选一个起点：
> 1. **手上有现成简历**：直接把本地路径发我（PDF / Word / Markdown / HTML / JSON / 截图都行），我直接读取整理
> 2. **手上没有简历**：我分几轮每次只问 2～3 个问题，带你把经历聊成简历
> 3. **已有简历想对照 JD 改写或换模板**：把简历路径和目标 JD 发我，我帮你诊断并生成模板预览对比」

Route based on their choice:

- **Path A · 手上有现成简历（本地路径直接读，免抄写）**
  Ask for the **local file path** (PDF, `.docx`, `.md`, `.txt`, `.html`, `resume.json`, or resume screenshots) or pasted text.
  Read it offline right away:
  ```bash
  python3 scripts/cococv_local.py read-source "<local-file-path>" --json
  ```
  - Supports `.json`, `.md`/`.txt`, `.html`, `.docx` (pure stdlib zip/XML extraction, zero extra packages), and `.pdf` (via `pymupdf`/`pypdf`/`pdftotext`, or renders PNG pages if scanned).
  - If `format == "image"` or `page_images` are returned for a scanned PDF, inspect the image(s) directly with your vision / image-reading tool instead of asking the user to type it out.
  - Extract verified facts into `resume.json`, list anything unclear or missing as `【待补】`, and confirm before rendering.

- **Path B · 手上没有简历（对话一步步引导生成）**
  Do NOT drop a 15-field form in one turn. Ask **at most 2-3 high-impact questions per turn**:
  - **Round 1**: Target role/industry, career stage (student/intern/new-grad/experienced), and expected length (1 page vs 2 pages).
  - **Round 2**: Education background plus 1-3 core work/internship/project experiences (users can paste rough notes, bullet fragments, or point to a local project folder).
  - **Round 3**: Technical stack, key metrics, and links; mark unverified numbers or missing dates as `【待补】` so the user can review and fill later.

- **Path C · 已有简历想诊断、针对 JD 改写或换模板**
  Read the user's local resume (`read-source` or existing `resume.json`) alongside the target JD. Highlight real evidence gaps, rewrite weak bullets into concrete `action -> mechanism -> quantified impact` statements without inventing facts, mark uncertain metrics with `【待补】`, and offer template switching.

## Step 2 · Author & Validate `ResumeData`

Initialize a clean skeleton if starting fresh:

```bash
resume-agent init -o resume.json --title "后端开发简历" --json
# Or zero-dependency fallback:
python3 scripts/cococv_local.py init -o resume.json --title "后端开发简历" --json
```

Before editing fields, read [references/schema.md](references/schema.md) for the exact Workspace v2 `ResumeData` structure and built-in logo keys (or run `resume-agent schema`).

Critical formatting rules:
- **8 HTML rich-text fields** (`education[*].description`, `workExperience[*].details`, `experience[*].details`, `projects[*].description`, `openSource[*].description`, `customData[*][*].description`, `selfEvaluation`, `skillContent`): format using clean HTML such as `<ul class="custom-list"><li><p><strong>关键词</strong>：具体职责与量化结果</p></li></ul>` or `<p>...</p>`.
- **Plain-text fields** (especially `awards[*].description`, plus all names, titles, companies, schools, roles, and dates): write plain text ONLY without HTML tags (`awards[*].description` is LaTeX-escaped directly, so `<p>` would print literally in PDF).
- **Section visibility and ordering**: control rendered sections via `menuSections` (`enabled: true/false` and array order). Unused sections should be disabled (`enabled: false`) rather than left empty.

Always validate deterministically before rendering or handoff:

```bash
resume-agent validate resume.json --json
# Or zero-dependency fallback:
python3 scripts/cococv_local.py validate resume.json --json
```

- Exit code `0` (`"valid": true`) is required before rendering.
- If exit code is `1`, inspect `errors[*].path` and repair the JSON.

## Step 3 · Template Discovery & Guided Selection

**Never dump 21 raw template IDs as an unformatted wall.** Follow this sequence instead:

1. **Recommend 3-5 matching templates first** based on the candidate's role and page budget (with `asu-tech` as the recommended zero-dependency default):

| 候选人场景 | 推荐模板 ID | 版式特点 | 本地依赖 |
| --- | --- | --- | --- |
| AI / 后端 / 前端 / 全栈（推荐默认） | `asu-tech` | ASu 极客单栏，高密度蓝色标题与浅灰经历条 | 零依赖直出 |
| 简洁常规单页投递 | `asu-01` / `asu-02` / `html-classic` | 经典蓝线 / 蓝底色块条 / 通用标准单栏 | 零依赖直出 |
| 多段实习或清晰成长轨迹 | `asu-03` / `asu-04` / `asu-10` | 左侧时间轴 / 深蓝顶幅 / 丝带标签 | 零依赖直出 |
| 经历较少想双列平衡留白 | `asu-05` / `asu-13` | 灰调侧栏 / 纯黑紧凑侧栏（左技能右经历） | 零依赖直出 |
| 资深研发 / 多项目 / 学术科研双页 | `asu-06` / `asu-08` / `asu-16` / `asu-17` / `asu-18` | 双页时间轴 / 双栏双页 / 纯黑学术双页 | 零依赖直出 |
| 偏好传统 LaTeX 排版 | `default` | CocoCV 经典单栏 XeLaTeX 模板 | 需本机 `xelatex` 或 Web `handoff` |

2. **Offer instant browse & side-by-side visual comparison** whenever the user asks `"还有什么模板"` or is unsure which layout fits best:
   ```bash
   # 查看全部 21 套模板中文说明与适用场景
   python3 scripts/cococv_local.py templates --json

   # 生成一份本地单文件可视化对比画廊（支持直接用用户自己的 resume.json 渲染每套真实效果）
   python3 scripts/cococv_local.py templates --gallery template-gallery.html --resume resume.json --json
   ```
   Open `template-gallery.html` in a browser (or render 2-3 `.png` samples of top candidates when Chrome is installed) so the user picks by eye, not by guessing IDs.

## Step 4 · Choose Deliverable Format & Render Locally

Confirm which local output(s) the user wants (never push login before delivering):

| 用户选择 | 所需环境 | 本地产物 | 说明 |
| --- | --- | --- | --- |
| **本地 HTML 预览** (`-o resume.html`) | 仅 Python 3.10+ | 自包含 `.html` | 零依赖 100% 可出，浏览器打开可看可 `Cmd/Ctrl+P` 导出矢量 PDF |
| **逐页预览图片** (`-o resume.png`) | Chrome/Edge 或 `PyMuPDF` + `XeLaTeX` | 每页 `.png`（多页自动分 `-page-N.png`） | 方便手机核对或 AI 自检 2-3 行溢出 |
| **直接导出 PDF** (`-o resume.pdf`, 可配 `--png`) | Headless Chrome CDP 或本地 `xelatex` | A4 `.pdf`（配 `--png` 同步出预览图） | 全程本机运行，不上传服务器 |
| **网页工作台精修** (`handoff`) | 联网且用户明确要求 | 60 分钟临时 `/share/<id>` 链接 | 支持拖拽微调、Logo 库与云端 XeLaTeX |

Render commands:

- **Self-contained HTML (works on every machine):**
  ```bash
  cococv render resume.json -o resume.html --template asu-tech --json
  # Or zero-dependency fallback:
  python3 scripts/cococv_local.py render resume.json -o resume.html --template asu-tech --json
  ```
- **PNG preview images only:**
  ```bash
  cococv render resume.json -o resume.png --template asu-tech --json
  ```
- **Direct A4 PDF via Headless Chrome CDP (plus `--png` page inspection):**
  ```bash
  resume-agent render resume.json -o resume.pdf --template asu-tech --png --json
  ```
- **Local XeLaTeX PDF + PNG previews (when local `xelatex` is installed):**
  ```bash
  cococv render resume.json -o resume.pdf --template default --engine latex --png --json
  ```

## Step 5 · Local Retention & Optional Web Continuation

After delivering local files, summarize clearly in plain language:
- **全部产物已留在本地**：`resume.json` 与导出的 `.html` / `.png` / `.pdf` 默认只保存在用户指定目录，全程无需登录。
- **想上网页工作台可视化精修或使用云端 XeLaTeX？** 用户可以随时登录 CocoCV Web 端手动导入 `resume.json`，或者由用户明确同意后执行：
  ```bash
  cococv handoff resume.json --ttl-minutes 60 --json
  # Or without CLI installed:
  python3 scripts/cococv_local.py handoff resume.json --ttl-minutes 60 --json
  ```
- **高级工作区同步**：只有用户主动提供 `--token` / `RESUME_AGENT_TOKEN` 时才调用 `resume-agent sync list/pull/push`。
