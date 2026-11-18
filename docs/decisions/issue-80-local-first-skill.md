# Decision Log — Issue 80: Local-First Skill Bundle, Output Choice & Web Handoff

- **Date**: 2026-11-15
- **Issue**: https://github.com/wycocoyu/cococv/issues/80
- **Decision**:
  1. Keep `codex + skill` (and other AI harnesses) 100% free of mandatory terminal login; default all generated artifacts to local disk.
  2. Allow users to explicitly choose local HTML preview (`.html`), PNG page preview images (`.png` / `--png`), or direct PDF export (`.pdf`, or `--png` alongside `.pdf`).
  3. Bundle pure-stdlib `scripts/html_generator.py` + `scripts/cococv_local.py` inside every generated skill directory so bare Python machines without `cococv`, `PyMuPDF`, Chrome, or `XeLaTeX` can still initialize, validate, and render self-contained A4 HTML locally.
  4. Replace process-local `share_store` dict with atomic file-backed `DiskShareStore` and expose opt-in `cococv handoff` + `SharePage` workspace import buttons so users without local `XeLaTeX`/Chrome (or wanting Web editing/cloud sync) can jump to the browser on demand and log in only there.
