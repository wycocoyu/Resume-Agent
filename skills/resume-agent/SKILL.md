---
name: "resume-agent"
description: "Create, edit, validate, and render CocoCV (Resume-Agent) JSON resumes locally as HTML previews, PNG page images, or PDFs via the cococv or resume-agent CLI or the bundled zero-dependency Python helper, with optional Web handoff and workspace sync. Use when drafting, tailoring, validating, previewing, or exporting resumes."
metadata:
  short-description: "Create, validate, render, and hand off CocoCV resumes"
---

# Resume Agent (CocoCV)

Build, update, validate, preview, and render Workspace v2 `ResumeData` JSON resumes locally with zero mandatory login, using either the installed `cococv` / `resume-agent` CLI or the bundled zero-dependency Python helper (`scripts/cococv_local.py`).

Invoke this skill in Codex with `$resume-agent`.

## Core Guardrails

1. **Never fabricate candidate facts.** Do not invent employers, schools, degrees, dates, GPAs, project metrics, open-source links, or awards. Populate only facts stated by the user or present in user-provided source files. When key facts are missing, mark them explicitly with `【待补】` (e.g. `峰值 QPS 由 2000 提升至【待补】`), ask concise follow-up questions, or disable unused sections via `menuSections[*].enabled = false`.
2. **Local-first and login-free by default.** Keep `resume.json`, `.html`, `.png`, and `.pdf` outputs on the user's local disk. Do NOT require terminal login tokens up front or upload user data unless the user explicitly asks for `handoff` or `sync`.
3. **Keep validation read-only and mandatory.** Always validate `resume.json` before rendering or handing off. Fix reported field paths directly in the JSON file.
4. **Stay offline by default.** `cococv render` / `resume-agent render` runs with zero network access unless the user explicitly passes `--online`.
5. **Page balance and density self-check.** When `.png` previews are generated, inspect them visually to catch 2-3 line orphan overflow onto a second page or excessive whitespace, and adjust bullets or spacing accordingly.

## Prerequisites & Zero-Dependency Fallback

Run the bundled environment probe first to detect what is available on the user's machine:

```bash
python3 scripts/cococv_local.py env --json
```

- **Full local environment (`cococv` / `resume-agent` CLI installed)**: use `cococv` or `resume-agent` directly (supports `.html`, multi-page `.png`, Chrome CDP `.pdf`, and local `XeLaTeX` `.pdf` when installed).
- **Zero-dependency fallback (bare Python 3.10+ only)**: if `cococv` / `resume-agent` is not installed, use `python3 scripts/cococv_local.py` with the same `init`, `validate`, `render`, and `handoff` subcommands. It generates self-contained `.html` with zero external binaries or packages, and automatically uses Chrome/Edge when present.
- **Harness install / status**:
  ```bash
  resume-agent skill install --harness codex --dry-run
  resume-agent skill install --harness codex
  ```

## Standard Workflow

### End-to-End Flow & Expected Outcome Matrix

1. Run `python3 scripts/cococv_local.py env --json` with zero upfront login or token setup.
2. Initialize or update `resume.json` locally and validate strictly before rendering (`init` -> edit -> `validate`).
3. Let the user pick local output format (**HTML** / **PNG images** / **PDF** / **PDF + PNG**), falling back automatically from `cococv` CLI to `scripts/cococv_local.py` on bare Python machines.
4. Visually inspect generated `.png` previews to catch 2-3 line page overflow or sparse whitespace.
5. Keep all artifacts on local disk by default, and remind the user they can open the Web workspace on demand (`resume.json` manual import or explicit 60-minute `handoff` URL) for drag-and-drop editing, cloud backup, or cloud `XeLaTeX`.

| Scenario / User Choice | Required Environment | Local Output | Login Needed |
| --- | --- | --- | --- |
| Local HTML preview (`-o resume.html`) | Bare Python 3.10+ only | Self-contained `.html` (browser `Cmd/Ctrl+P` PDF) | No (stays local) |
| Preview images (`-o resume.png`) | Chrome/Edge (or `PyMuPDF` + `XeLaTeX`) | Per-page `.png` (`-page-N.png` when multipage) | No (stays local) |
| Direct PDF (`-o resume.pdf`, optional `--png`) | Chrome/Edge CDP or local `xelatex` | A4 `.pdf` (plus `.png` previews with `--png`) | No (stays local) |
| Cloud `XeLaTeX` / Web UI continuation | Network opt-in via `handoff` | 60-min `/share/<id>` URL -> local edit or cloud save | Only in browser if saving/compiling in cloud |

### 1. Probe Output Preference & Initialize JSON

Ask or confirm which deliverable format the user prefers (defaulting to local **HTML** on bare environments, or **HTML / PNG / PDF / images + PDF** when Chrome or XeLaTeX is available):

- **Option A — Local HTML Preview (works on every machine, zero binaries required)**:
  Renders a self-contained A4 `.html` file (`-o resume.html`) that opens directly in any browser and prints to vector PDF via `Cmd/Ctrl+P`.
- **Option B — Page Preview Images (`.png` / `--png`)**:
  Renders `.png` preview images (`-o resume.png` or paired with PDF via `-o resume.pdf --png`) for quick visual review and page-balance checking.
- **Option C — Direct PDF Export (`-o resume.pdf`, or `-o resume.pdf --png` for images + PDF)**:
  Uses local Chrome/Edge CDP (`--template asu-tech`, recommended default) or local `XeLaTeX` (`--template default --engine latex`) when `xelatex` is installed.

Start or load a `ResumeData` JSON file:

```bash
resume-agent init -o resume.json --title "后端开发简历" --json
# Or without CLI installed:
python3 scripts/cococv_local.py init -o resume.json --title "后端开发简历" --json
```

### 2. Author or Edit `ResumeData`

Before editing fields, read [references/schema.md](references/schema.md) for the exact `ResumeData` structure, field conventions, and built-in logo keys (or inspect `resume-agent schema`).

Critical formatting rules:
- **8 HTML rich-text fields** (`education[*].description`, `workExperience[*].details`, `experience[*].details`, `projects[*].description`, `openSource[*].description`, `customData[*][*].description`, `selfEvaluation`, `skillContent`): format using clean HTML such as `<ul class="custom-list"><li><p><strong>关键词</strong>：具体职责与量化结果</p></li></ul>` or `<p>...</p>`.
- **Plain-text fields** (especially `awards[*].description`, plus all names, titles, companies, schools, roles, and dates): write plain text ONLY without HTML tags (`awards[*].description` is LaTeX-escaped directly, so `<p>` would print literally in the PDF).
- **Section visibility and ordering**: control rendered sections via `menuSections` (`enabled: true/false` and array order). Any `custom_*` key in `customData` must have a matching enabled entry in `menuSections`.

### 3. Validate Deterministically

```bash
resume-agent validate resume.json --json
# Or zero-dependency fallback:
python3 scripts/cococv_local.py validate resume.json --json
```

- Exit code `0` (`"valid": true`) is required before rendering.
- If exit code is `1`, inspect `errors[*].path` and repair the JSON.

### 4. Render User-Selected Output Format

- **Local self-contained HTML (always works, zero binaries):**
  ```bash
  cococv render resume.json -o resume.html --template asu-tech --json
  # Or zero-dependency fallback:
  python3 scripts/cococv_local.py render resume.json -o resume.html --template asu-tech --json
  ```
- **PNG preview images only:**
  ```bash
  cococv render resume.json -o resume.png --template asu-tech --json
  ```
- **Direct A4 PDF via Headless Chrome CDP (or images + PDF with `--png`):**
  ```bash
  resume-agent render resume.json -o resume.pdf --template asu-tech --png --json
  ```
- **XeLaTeX PDF + PNG previews (when local `xelatex` is installed):**
  ```bash
  cococv render resume.json -o resume.pdf --template default --engine latex --png --json
  ```

#### Template Recommendation Matrix
- **`asu-tech` (Recommended default)**: High-density single-column technology template, grey capsule badges, multi-level STAR bullet points. Works locally with zero TeX dependencies.
- **`asu-01` ~ `asu-04`, `asu-07`, `asu-10`, `asu-11`, `asu-15`**: Single-column distinctive HTML themes (classic blue accent line, solid header band, vertical timeline, ribbon badge, serif typography).
- **`asu-05`, `asu-13`**: Two-column sidebar HTML themes (light grey sidebar, pure black sidebar).
- **`asu-06`, `asu-08`, `asu-09`, `asu-12`, `asu-14`, `asu-16` ~ `asu-18`**: Two-page / high-density / academic HTML themes.
- **`default`**: XeLaTeX classic single-column layout (requires local `xelatex`, or use Web handoff if local `xelatex` is missing).

### 5. Local Retention & Optional Web Continuation (No Forced Login)

After delivering local files, always remind the user concisely:
- **Saved locally by default**: Your `resume.json` and rendered outputs stay on your local machine with no account required.
- **Want drag-and-drop editing, cloud backup, or cloud XeLaTeX (when local `xelatex`/Chrome is missing)?** Log in on the CocoCV Web app and import `resume.json` — or ask me to create a temporary 60-minute Web continuation link (explicit opt-in only):
  ```bash
  cococv handoff resume.json --ttl-minutes 60 --json
  # Or without CLI installed:
  python3 scripts/cococv_local.py handoff resume.json --ttl-minutes 60 --json
  ```
- **Direct workspace sync (advanced)**: `resume-agent sync list/pull/push` remains available when explicitly supplying `--token` / `RESUME_AGENT_TOKEN`.
