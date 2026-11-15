# AGENTS.md

## Project Overview
- **CocoCV (formerly Resume-Agent)** monorepo with `frontend/` and `backend/`
- Backend is FastAPI served from `backend/main.py`
- Frontend is React 18 + Vite 5 + TypeScript in `frontend/`
- Rebranded CLI supports dual binary entrypoints: `cococv` and `resume-agent`

## Documentation & Knowledge Architecture (Single Source of Truth)
- Public developer documentation lives in `docs/` (tracked in Git; index at `docs/README.md`):
  - `docs/frontend-architecture.md`, `docs/agent-streaming.md`, `docs/database-schema.md`, `docs/agent-glossary.md`, `docs/ai-ocr-and-pdf-cjk.md`, `docs/PI-CORE-MIGRATION.md`, and `docs/adr/`
  - Internal agent configs under `docs/agents/` remain local-only (gitignored)
- Local `knowledge-base/` is gitignored and holds only the lightweight archive index (`knowledge-base/README.md`)

## Architecture Notes & Conventions (Milestone 2)
- **Agent Runtime & Convergence**:
  - In-process Pi-Core single-coroutine linear event loop (`backend/agent/pi_core/`) replacing legacy OpenManus inheritance chains
  - FastAPI backend architecture aligned with Strangler Fig evolution towards full-stack TypeScript
  - No separate agent service on port 9100; agent runs in-process with main backend (`AGENT_BACKEND_BASE_URL` disabled by default)
- **LaTeX Compilation & Zero-Regression CJK /ToUnicode CMap**:
  - Both high-level `compile_latex` (in `backend.latex_generator` and `backend.latex_compiler`) and low-level `compile_latex_raw` (in `backend.latex_compiler`) inject dual-layer CJK `/ToUnicode` CMaps
  - Primary layer: fast-path via `pymupdf`
  - Fallback layer: zero-dependency standard library incremental updater `_ensure_cjk_tounicode_cmaps_stdlib`
  - Guarantees 100% extractable and searchable Chinese text in all generated XeLaTeX PDFs
- **Dual CLI Aliases**:
  - `pyproject.toml` registers both `cococv = "backend.cli:main"` and `resume-agent = "backend.cli:main"`
  - Both CLI entrypoints support identical subcommands: `init`, `schema`, `validate`, `render`, `sync`, and `skill`
- **Downward Storage Compatibility**:
  - All modern client-side storage keys use `cococv_*` prefix (e.g. `cococv_current`, `cococv_v2_data`, `cococv_resumes`, `cococv_pinned_ids`)
  - `frontend/src/utils/storageCompat.ts` provides `getCompatibleItem`, `setCompatibleItem`, and `removeCompatibleItem`
  - Reads check `cococv_*` first; if absent, legacy `resume_*` / `resume-agent-*` keys are probed and automatically migrated forward to `cococv_*`

## Setup & Development
- Backend dependencies: `uv pip install -r requirements.txt` (or symlinked `backend/requirements.txt`)
- Frontend dependencies: `cd frontend && npm install`

## Run
- Backend: `python -m uvicorn backend.main:app --host 127.0.0.1 --port 9000`
- Frontend: `cd frontend && npm run dev`
- CLI: `cococv --help` or `resume-agent --help`

## Testing & Quality Gates
- Frontend verification:
  - Unit tests: `cd frontend && npm test -- --run`
  - Production build: `cd frontend && npm run build`
- Backend verification:
  - Unit & regression tests: `pytest backend/tests/`
  - E2E tier tests: `pytest tests/e2e/tier1/`
- Rule: All testing must use deterministic native test runners (vitest, npm, pytest). Never invoke `claude` or `opencode` CLI as test execution engines.

## Engineering Governance & Release Process
- Deploy = `git push origin main`; automated deployment pulls, builds, and restarts pm2.
- **Before pushing to main, update `CHANGELOG` array in `frontend/src/data/changelog.ts`:**
  - Bump `version` (patch +0.0.1, e.g. `3.8.0` → `3.8.1`; minor feature +0.1.0, e.g. `3.8.0` → `3.9.0`)
  - **Date format must strictly be pure-date: `YYYY-MM-DD` only, NEVER include time** (e.g. `2026-11-15`, forbidden: `2026-11-15 10:00`)
  - Write `added` / `fixed` as short user-facing Chinese (no tech/ops internal details)
  - **Multiple deploys on the same day merge into ONE entry** (fold new items into today's entry and raise its version; do not append another entry)
  - Commit the changelog together with the release code, then push
- Users see a「有什么新变化」modal (`ChangelogModal`) on first visit after each version bump.

## Conventions
- Prefer minimal diffs
- Do not modify unrelated files
- Read existing files and follow existing patterns before editing
- Preserve user changes already present in the worktree
- Do not move or rename files unless explicitly instructed
