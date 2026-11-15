---
name: "resume-agent"
description: "Create, edit, validate, and render Resume-Agent JSON resumes into local XeLaTeX PDFs, or sync resumes with the Resume-Agent Web workspace via the resume-agent CLI. Use when the user asks to draft a new resume, tailor or update a ResumeData JSON file, export a resume PDF locally, or pull and push resumes to Resume-Agent."
metadata:
  short-description: "Create, validate, render, and sync Resume-Agent resumes"
---

# Resume Agent

Build, update, validate, render, and optionally sync Workspace v2 `ResumeData` JSON resumes using the deterministic `resume-agent` CLI, while this harness handles natural-language authoring and tailoring.

Invoke this skill in Codex with `$resume-agent`.

## Core Guardrails

1. **Never fabricate candidate facts.** Do not invent employers, schools, degrees, dates, GPAs, project metrics, open-source links, or awards. Populate only facts stated by the user or present in user-provided source files. When key facts (such as exact metrics, project scale, performance improvements, dates, awards) are missing or not provided by the candidate, mark them explicitly with `【待补】` (e.g. `峰值 QPS 由 2000 提升至【待补】`) or ask concise follow-up questions, or disable unused sections via `menuSections[*].enabled = false`. Never invent quantitative metrics or employment histories.
2. **Keep validation read-only and mandatory.** Always run `resume-agent validate` before `render` or `sync push`. Fix reported field paths directly in the JSON file.
3. **Stay offline by default.** `resume-agent render` runs with zero network access unless the user explicitly asks to fetch remote COS/HTTP logos or avatars via `--online`.
4. **Sync only on explicit user intent.** Never run `resume-agent sync push` or overwrite local files with `--force` unless the user asked for it.
5. **Page balance and density self-check.** After rendering, check whether the resume fills the page cleanly. Avoid sparse overflow where a second page contains only 2-3 orphan lines. Tailor bullet points and margins so that a 1-page resume is compact and complete, or a 2-page resume is substantively filled on both pages.

## Prerequisites & Skill Discovery

- Editable CLI install (from the Resume-Agent repository root):
  ```bash
  pip install --no-build-isolation -e /path/to/Resume-Agent
  ```
- Harness discovery for Codex (writes into the documented skills directory):
  ```bash
  resume-agent skill install --harness codex --dry-run
  resume-agent skill install --harness codex
  ```
  `resume-agent skill status --harness codex` reports drift and CLI/skill version skew; `resume-agent skill uninstall --harness codex` removes only files it created.

## Standard Workflow

### 1. Initialize or Load Resume JSON

- **Start a new resume:**
  ```bash
  resume-agent init -o resume.json --title "后端开发简历" --json
  ```
- **Pull an existing resume from Web workspace (when requested):**
  ```bash
  resume-agent sync list --json
  resume-agent sync pull <resume_id> -o resume.json --json
  ```

### 2. Author or Edit `ResumeData`

Before editing fields, read [references/schema.md](references/schema.md) for the exact `ResumeData` structure, field conventions, and built-in logo keys (or inspect the live machine schema via `resume-agent schema`).

Critical formatting rules:
- **8 HTML rich-text fields** (`education[*].description`, `workExperience[*].details`, `experience[*].details`, `projects[*].description`, `openSource[*].description`, `customData[*][*].description`, `selfEvaluation`, `skillContent`): format using clean HTML such as `<ul class="custom-list"><li><p><strong>关键词</strong>：具体职责与量化结果</p></li></ul>` or `<p>...</p>`.
- **Plain-text fields** (especially `awards[*].description`, plus all names, titles, companies, schools, roles, and dates): write plain text ONLY without HTML tags (`awards[*].description` is LaTeX-escaped directly, so `<p>` would print literally in the PDF).
- **Section visibility and ordering**: control rendered sections via `menuSections` (`enabled: true/false` and array order). Any `custom_*` key in `customData` must have a matching enabled entry in `menuSections`.

### 3. Validate Deterministically

```bash
resume-agent validate resume.json --json
```

- Exit code `0` (`"valid": true`) is required before rendering or pushing.
- If exit code is `1`, inspect `errors[*].path` (for example `menuSections[0].enabled` or `education[0].school`) and repair the JSON.

### 4. Render Local Resume (HTML, Headless Chrome CDP PDF, or XeLaTeX)

- **Render self-contained HTML:**
  ```bash
  cococv render resume.json -o resume.html --template asu-tech --json
  ```
- **Render A4 PDF via Headless Chrome CDP (recommended for HTML templates):**
  ```bash
  cococv render resume.json -o resume.pdf --template asu-tech --json
  ```
- **Render XeLaTeX PDF (for LaTeX templates):**
  ```bash
  cococv render resume.json -o resume.pdf --template default --engine latex --json
  ```

#### Template Recommendation Matrix
- **`asu-tech` (Recommended default)**: High-density single-column technology template, grey capsule badges, multi-level STAR bullet points. Ideal for technical and engineering roles.
- **`asu-01` ~ `asu-04`, `asu-07`, `asu-10`, `asu-11`, `asu-15`**: Single-column distinctive themes (classic blue accent line, solid header band, vertical timeline, ribbon badge, serif typography).
- **`asu-05`, `asu-13`**: Two-column sidebar themes (light grey sidebar, pure black sidebar) ideal for separating skills and basic info on the left with experience on the right.
- **`asu-06`, `asu-08`, `asu-09`, `asu-12`, `asu-14`, `asu-16` ~ `asu-18`**: Two-page / high-density / academic themes (timeline two-page, cards, ultra-dense two-column, pure black academic).
- **`default`**: XeLaTeX classic single-column layout, optimal for academic or ATS plaintext extraction.

Notes:
- Uses local XeLaTeX or headless Chrome offline (`offline: true`).
- Local PNG/JPEG/PDF avatars in `basic.photo` (file path or `data:image/png;base64,...`) are validated by magic bytes at the CLI boundary; WebP/SVG or missing logos degrade gracefully and are reported in `warnings`.
- Add `--online` only when the user wants remote COS/HTTP logo or avatar downloads.

### 5. Optional Web Workspace Sync

- **Push validated JSON to Web workspace:**
  ```bash
  resume-agent sync push resume.json --name "张三-后端开发" --alias "秋招投递版" --json
  ```
- **Authentication options:**
  - Bearer session token: `--token <token>` or `RESUME_AGENT_TOKEN` (takes strict precedence and suppresses internal secret headers).
  - Local trusted dev headers: `FASTAPI_INTERNAL_AUTH_SECRET` + `RESUME_AGENT_USER_ID` (or `--internal-secret` + `--user-id`).
  - Target server: `--api-url` or `RESUME_AGENT_API_URL` (supports both direct FastAPI `http://127.0.0.1:9000` and Next.js proxy `http://127.0.0.1:3000/api/fastapi/proxy`).
