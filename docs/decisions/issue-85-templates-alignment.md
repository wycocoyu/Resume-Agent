# Decision Log — Issue 85: Align `/templates` Showcase with Real Workspace Templates & Fix Rendering Bugs

- **Date**: 2026-11-16
- **Issue**: https://github.com/wycocoyu/cococv/issues/85
- **PR**: https://github.com/wycocoyu/cococv/pull/86
- **Decision (Approved per Recommendation)**:
  1. **Keep and align all 27 real Workspace templates (`方案 A`)**: Remove fake `html-classic` from `/templates` and mirror the exact 27 templates present in `SettingsDrawer.tsx` (`Classic LaTeX` + 7 Builder HTML templates `latex`, `swiss-single`, `swiss-two-column`, `modern`, `modern-two-column`, `clean`, `vivid` + `asu-tech` + `asu-01`..`asu-18`).
  2. **Avoid misleading CLI copy on web-only templates**: Only the 20 CLI-supported templates (`default`, `asu-tech`, `asu-01`..`asu-18`) expose「复制口令」/ CLI snippets; the 7 web-only Builder HTML templates route directly to「在线体验」(free local-browser editing).
  3. **Fix root rendering bugs uncovered across the 27-template audit**:
     - Fix `adapter.ts` `htmlToBullets` so nested `<ul>/<ol>/<li>` lists indent cleanly without concatenating or duplicating child items across all 26 HTML templates.
     - Hide the empty `证件照 28×36mm` placeholder box in `ResumeAsuTech` when no photo is uploaded (preserving `photoSlotNoPhoto` class for existing tests).
     - Fix `ResumeAsuVariant` `.entryHead` 118px gap when dates are empty, and fix modern section numbering (`asu-15`/`asu-18`) to start at `01` instead of `02`.
     - Load company/school logos in `TemplatesPage`, render real XeLaTeX preview (`classic-latex-preview.png`) for `Classic LaTeX`, and refresh `docs/readme/template-overview.png` from the real 27 templates.
- **Reason**: Auditing one resume across all 27 Workspace templates showed that Workspace, `/templates`, and `template-overview.png` were out of sync and the 3 frontend bugs degraded every HTML template preview.
