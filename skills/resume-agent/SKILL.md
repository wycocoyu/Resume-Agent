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

1. **Never fabricate candidate facts.** Do not invent employers, schools, degrees, dates, GPAs, project metrics, open-source links, or awards. Populate only facts stated by the user or present in user-provided source files. When key facts are missing, ask concise follow-up questions or disable unused sections via `menuSections[*].enabled = false`.
2. **Keep validation read-only and mandatory.** Always run `resume-agent validate` before `render` or `sync push`. Fix reported field paths directly in the JSON file.
3. **Stay offline by default.** `resume-agent render` runs with zero network access unless the user explicitly asks to fetch remote COS/HTTP logos or avatars via `--online`.
4. **Sync only on explicit user intent.** Never run `resume-agent sync push` or overwrite local files with `--force` unless the user asked for it.

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

### 4. Render Local XeLaTeX PDF

```bash
resume-agent render resume.json -o resume.pdf --force --json
```

- Uses local XeLaTeX and repository `latex-resume-template/` offline (`offline: true`).
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
