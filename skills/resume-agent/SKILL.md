---
name: "resume-agent"
description: "Guided local-first AI resume builder for CocoCV (Resume-Agent): interview users without an existing resume, read local PDF/Word/Markdown/HTML/JSON resumes directly by path, recommend and preview 21 built-in templates, validate Workspace v2 ResumeData JSON, and export HTML, PNG previews, or PDFs with zero mandatory login (plus optional Web handoff and workspace sync)."
metadata:
  short-description: "Guided local resume importer, builder, HTML, PNG, and PDF"
---

# Resume Agent（CocoCV 本地简历制作与排版）

在 Codex 中使用 `$resume-agent` 唤醒本技能。默认基于 **`asu-tech`（ASu 单栏高密度技术简历模板）** 生成自包含可编辑 `.html`（支持打印或导出 `.pdf`），同时支持 `asu-01`～`asu-18`、`html-classic` 共 20 套零依赖 HTML 模板与 CocoCV 原生 **LaTeX (`default`)** 模板。

HTML 模板全程本机离线处理、无需登录、无需本机安装 LaTeX（仅需 Python 3.10+）；原生 **LaTeX (`default`)** 模板需本机同时具备 `cococv` CLI 与 `xelatex` 才可离线编译，无双依赖时默认引导通过 `handoff` 前往远程网页端出稿。所有结构化数据遵循 Workspace v2 `ResumeData` 规范。

## 核心铁律

1. **绝不杜撰任何候选人事实**：学校、公司、职位、起止时间、GPA、项目指标、开源链接与奖项必须来自用户口述或用户提供的本地文件。缺失或无法确认的指标统一标为 `【待补】`（如 `峰值 QPS 由 2000 提升至【待补】`），不可靠占位或不想展示的模块通过 `menuSections[*].enabled = false` 关闭。
2. **本地优先、零强迫登录**：`resume.json`、`.html`、`.png`、`.pdf` 全部留在用户本机目录，绝不要求预先登录或上传服务器；仅在用户明确要求 `handoff` 或 `sync` 时才联网。
3. **先引导再动手，不甩裸参数**：新对话未给完整材料或文件路径时，先发友好引导卡；所有输出默认离线（不加 `--online`）。
4. **渲染前强制校验**：每次修改 `resume.json` 后必须执行 `validate` 且返回退出码 `0` 再渲染。
5. **Page balance and density self-check（页面平衡与视觉密度自检）**：生成 `.png` 预览图后必须看图自检，防止出现多出 2～3 行溢出到第二页或大面积留白。

## 零步 · 静默探测本机环境与定位脚本

回复新请求前，先静默探测本机能力（无需向用户输出命令行）。**切勿假设当前工作目录下存在 `./scripts/cococv_local.py`**——先用 `SKILL_PY` 变量定位本技能自带的零依赖脚本（与本 `SKILL.md` 同级的 `scripts/cococv_local.py`）：

```bash
SKILL_PY="$(find ~/.codex ~/.agents ~/.codebuddy skills -name cococv_local.py 2>/dev/null | head -n1)"
python3 "$SKILL_PY" env --json
```

- **已安装完整 CLI（`cococv` / `resume-agent`）且具备 `xelatex`（即 `capabilities.local_latex_pdf == true`）**：支持全部 `.html`、多页 `.png`、Headless Chrome CDP `.pdf` 及本机 `xelatex` `.pdf`（`default`）。
- **仅零依赖脚本或缺少双依赖（`capabilities.local_latex_pdf == false`，即使本机单独装有 `xelatex` 但 `cococv_cli` 为 `null` 也算不具备）**：`python3 "$SKILL_PY"` 内置完整 `env`、`read-source`、`templates`、`init`、`validate`、HTML/Chrome `render` 与 `handoff` 能力，无需 `pip install` 或启动后端即可本地生成 `asu-tech` 等 20 套 HTML / PDF；但 **`default`（XeLaTeX）无法单靠脚本本地编译**——**严禁在磁盘上执行全盘 `find` 搜索二进制**，首轮回复即应告知用户「本机未配齐 `cococv CLI` + `xelatex` 双依赖，建议完成 `resume.json` 整理与校验后直接通过 `handoff` 前往远程网页端编译（或改用本地零依赖 `asu-tech`）」。
- **安装到当前宿主**：
  ```bash
  resume-agent skill install --harness codex --dry-run
  resume-agent skill install --harness codex
  ```

## 第一步 · 对话开局引导（参考首轮回复模板）

当用户开启新对话且未直接给出完整经历或本地路径（例如只说 `"用 $resume-agent 帮我制作一个简历"`）时，立即用下面这份**一步到位引导卡**回复（大白话、不讲术语、不催登录）：

> 可以，我现在按 **CocoCV（Resume-Agent）** 开始制作。全程本机离线处理、无需登录、无需本机装 LaTeX；默认使用 **`asu-tech`（ASu 极客单栏）**，支持导出 **HTML / PNG 预览图 / PDF**（官网有 27 套模板，本地也可一键生成对比画廊挑选），所有经历只采用你确认过的事实。
>
> 你可以任选最省事的方式发我信息（**有现成简历直接给路径或上传，没有就按下面粗略填**）：
>
> 1. **目标岗位**：例如后端开发、AI Agent、前端、产品经理；校招 / 实习还是社招？如果有目标 JD 也可以一起贴给我。
> 2. **个人材料（三选一）**：
>    - 直接发我**本地文件路径**（支持 `.pdf`、`.docx`、`.md`、`.txt`、`.html`、`resume.json` 或简历截图）
>    - 直接**上传/粘贴**已有简历内容或项目笔记
>    - 暂时没有整理好的材料，直接复制下面模板粗略发我（也可以边聊我分轮问你）：
>      ```text
>      姓名：
>      电话 / 邮箱：
>      目标岗位：
>      教育经历：
>      工作 / 实习：
>      项目经历：
>      技能：
>      其他链接（GitHub / 作品集）：
>      ```
> 3. **版式与模板选择**：单页还是双页？需要输出 **HTML / PNG 预览图 / PDF** 哪种？如果想先看样式，可打开官网模板广场 [**cococv.cn/templates**](https://cococv.cn/templates) 查看全部 27 套真实模板并直接「复制口令」发给我（也支持免登录在浏览器体验或导入 JSON 试套），或让我直接在本地生成对比画廊。
>
> 暂时缺的数据我会标成 `【待补】`，绝不替你编造。

## 第二步 · 按用户输入分流采集与补问

- **路径 A · 用户提供了本地文件路径或上传了简历（PDF / Word / Markdown / HTML / JSON / 截图）**
  立即离线读取（纯标准库优先支持 `.docx`/`.md`/`.html`/`.json`，`pymupdf`/`pdftotext` 支持 `.pdf`）：
  ```bash
  python3 "$SKILL_PY" read-source "<本地文件路径>" --json
  ```
  - 若返回 `format == "image"` 或 `page_images`（扫描件 PDF / 截图），直接调用读图能力提取文字与版面，不要让用户手打。
  - 提取真实经历写入 `resume.json`，缺口标为 `【待补】`，与用户确认后渲染。
- **路径 B · 用户从零开始**
  不一次性甩 15 项表单。缺失字段补问规则：**每轮最多补问 3 个最关键问题**（目标岗位与页数 → 教育与核心工作/实习/项目 → 技术栈与量化指标），支持用户贴零散笔记或本地项目目录，先出初稿再逐轮补齐 `【待补】`。
- **路径 C · 对照 JD 诊断改写或换模板**
  对照本地简历与目标 JD，指出真实证据缺口，把空泛描述改写为 `动作 -> 机制 -> 量化影响`（不捏造数字，缺数据标 `【待补】`），并推荐最匹配模板。

## 第三步 · 模板选择矩阵与可视化对比

未指定模板时默认使用 `asu-tech`（ASu 单栏高密度技术简历）。**禁止把 21 个模板 ID 干巴巴直接甩给用户**，先按场景推荐 3～5 套：

| 候选人场景 | 推荐模板 ID | 版式特点 | 本地依赖 |
| --- | --- | --- | --- |
| AI / 后端 / 前端 / 全栈（推荐默认） | `asu-tech` | ASu 极客单栏，蓝色标题线与浅灰经历条 | 零依赖直出 |
| 简洁常规单页投递 | `asu-01` / `asu-02` / `html-classic` | 经典蓝线 / 蓝底色块条 / 通用标准单栏 | 零依赖直出 |
| 多段实习或清晰成长轨迹 | `asu-03` / `asu-04` / `asu-10` | 左侧时间轴 / 深蓝顶幅 / 丝带标签 | 零依赖直出 |
| 经历较少想双列平衡留白 | `asu-05` / `asu-13` | 灰调侧栏 / 纯黑紧凑侧栏（左技能右经历） | 零依赖直出 |
| 资深研发 / 多项目 / 学术科研双页 | `asu-06` / `asu-08` / `asu-16` / `asu-17` / `asu-18` | 双页时间轴 / 双栏双页 / 纯黑学术双页 | 零依赖直出 |
| 偏好传统 LaTeX 排版 | `default` | CocoCV 原生经典单栏 XeLaTeX 模板 | 默认引导 `handoff` 远程编译（仅 `capabilities.local_latex_pdf == true` 时建议本地） |

用户想看全部模板或犹豫版式时，先指引用户打开官网免登录模板广场 [**cococv.cn/templates**](https://cococv.cn/templates)（支持查看全部 21 套预览、复制口令发回给你、免登录在线微调或导入 `resume.json` 试套），也可以直接用下面命令查看清单或生成本地单文件可视化对比画廊：

```bash
# 查看全部 21 套模板中文说明与适用场景
python3 "$SKILL_PY" templates --json

# 用用户自己的 resume.json 生成单文件 21 套模板同屏对比画廊
python3 "$SKILL_PY" templates --gallery template-gallery.html --resume resume.json --json
```

## 第四步 · 生成并校验 `ResumeData` (`resume.json`)

初始化骨架：

```bash
resume-agent init -o resume.json --title "后端开发简历" --json
# 零依赖兜底：
python3 "$SKILL_PY" init -o resume.json --title "后端开发简历" --json
```

编辑前务必先读 [references/schema.md](references/schema.md)（或运行 `resume-agent schema`）核对精确字段与内置公司/学校 Logo 键名：

- **8 个 HTML 富文本字段**（`education[*].description`、`workExperience[*].details`、`experience[*].details`、`projects[*].description`、`openSource[*].description`、`customData[*][*].description`、`selfEvaluation`、`skillContent`）：使用干净 HTML（如 `<ul class="custom-list"><li><p><strong>关键词</strong>：职责与量化结果</p></li></ul>` 或 `<p>...</p>`）。
- **纯文本字段**（尤其是 `awards[*].description` 及姓名、公司、学校、职位、日期）：严禁写入 HTML 标签，否则 LaTeX 编译会原样印出 `<p>`。
- **模块显隐与顺序**：通过 `menuSections` 的 `enabled` 与数组顺序控制，未使用的模块设为 `enabled: false`。

校验必须通过（Exit Code `0`）：

```bash
resume-agent validate resume.json --json
# 零依赖兜底：
python3 "$SKILL_PY" validate resume.json --json
```

## 第五步 · HTML / PNG / PDF / LaTeX 渲染与 Print-preview QA

按用户需要选择导出格式（HTML 100% 零依赖可用；PDF / PNG 优先本机 Headless Chrome CDP 或 `xelatex`）：

```bash
# 1. 自包含可编辑 HTML（默认推荐，任意机器零依赖直出，浏览器可打印导出 PDF）
cococv render resume.json -o resume.html --template asu-tech --json
# 零依赖兜底：
python3 "$SKILL_PY" render resume.json -o resume.html --template asu-tech --json

# 2. 逐页 PNG 预览图（方便手机核对或视觉 QA）
cococv render resume.json -o resume.png --template asu-tech --json

# 3. 本机 Headless Chrome CDP 直接导出 A4 PDF 并同步出 PNG 预览图
resume-agent render resume.json -o resume.pdf --template asu-tech --png --json

# 4. 仅当 env --json 返回 capabilities.local_latex_pdf == true（本机同时装有 cococv CLI 与 xelatex）时，才建议本地 LaTeX 编译：
cococv render resume.json -o resume.pdf --template default --engine latex --png --json
```

### 交付前 Print-preview 与页面平衡 QA

- **纸张与分页**：A4 尺寸稳定，单页不过空（也不因多出 2～3 行尾巴被迫换第二页），多页先填实第一页再顺延。
- **版面与文字**：单/双栏结构正确，长姓名/邮箱/链接不溢出重叠，文本可选中可复制（不用整页截图替代 PDF）。
- **LaTeX 远程优先与禁扫盘边界**：若用户指定 `default`（LaTeX）模板且 `env --json` 返回 `capabilities.local_latex_pdf == false`（缺少 `cococv_cli` 或缺少 `xelatex` 任一项），**严禁**宣称支持本机离线编译，**严禁**对用户目录全盘执行 `find` 查找二进制，也不要硬跑必败的 `render --template default --engine latex`。应先在本地整理并校验通过 `resume.json`（`validate` 退出码 `0`），随后**默认引导远程**：征得用户同意联网后执行 `python3 "$SKILL_PY" handoff resume.json --ttl-minutes 60 --json`，返回链接引导至网页端云端编译（也可直接把 `resume.json` 导入官网 `cococv.cn/templates` 在线体验，或按用户意愿改用单栏观感相近的本地 `asu-tech`）。

## 第六步 · 交付说明与可选网页工作台续修

交付时明确告知用户：生成文件路径、所选模板与页数、Print-preview QA 结果、仍需用户补充的 `【待补】` 清单，以及浏览器 `Cmd/Ctrl + P`（开启背景图形、关闭页眉页脚）导出 PDF 的方法。

HTML 产物默认保留在用户本机，无需登录。若用户希望上网页工作台可视化拖拽微调，或选用 `default`（XeLaTeX）模板且 `capabilities.local_latex_pdf == false` 需使用远程云端 XeLaTeX 时，向用户确认联网后执行：

```bash
cococv handoff resume.json --ttl-minutes 60 --json
# 零依赖兜底：
python3 "$SKILL_PY" handoff resume.json --ttl-minutes 60 --json
```
