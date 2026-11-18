# Decision Log — Issue 97

- **Date**: 2026-11-17
- **Issue**: https://github.com/wycocoyu/cococv/issues/97
- **Approval**: 老板指令 `/swarm 按照你推荐的去改吧`

## Confirmed Decisions

1. **Backend Runtime Feature Toggles (`.env` hot-reload + `/api/features` + `/api/admin/features`)**
   - Rationale: `/admin` currently requires BetterAuth `admin` login; gating switches solely behind `/admin` causes self-lockout while login is disabled or unfinished.
   - Defaults during transition: `AUTH_ENABLED=false`, `AGENT_ENABLED=false`, `EDITOR_AI_ENABLED=true`.
   - Write access guarded by `ADMIN_SWITCH_TOKEN` (`X-Admin-Switch-Token` or Bearer token), or `require_admin_only`, or local unauthenticated dev host.

2. **Disable Login UI & Unblock Anonymous PDF Export / Scoring**
   - Hide login buttons and disable `openModal` when `AUTH_ENABLED=false`.
   - Keep resume drafts persisted locally via `LocalStorageAdapter`.
   - Unblock single/batch PDF export and share-page PDF download when `auth_enabled=false`, and make `/api/resume/score` optional-auth.

3. **Local-Only Portrait Photos (`IndexedDB`) + Cloud-Served Preset Logos**
   - Store compressed user portrait photos (`<=2MB`) locally in browser `IndexedDB` (`cococv_local_assets` / `portrait_photos`) keyed by `resumeId`, preventing `localStorage` 5MB quota overflow and keeping user photos off COS.
   - Support transient `data:image/...;base64,...` decoding in `backend/latex_generator.py` inside the ephemeral XeLaTeX build directory with zero server persistence or `_USER_PHOTO_CACHE` retention.
   - Keep `GET /api/logos*` and `GET /api/school-logos*` publicly served from cloud/COS, hiding only admin custom upload controls when unauthenticated.

4. **Frontend & Backend Sidebar Agent Disable Guard**
   - Hydrate `isAgentEnabled()` from `GET /api/features` (`agent_enabled`) to hide sidebar `AI 助手` / `RecentSessions`, redirect `/agent/*`, and route Hero input to `/create-new`.
   - Enforce HTTP `503` (`AGENT_DISABLED`) on `/api/agent/*` in `backend/main.py` when `AGENT_ENABLED=false`.

5. **Upstream AI Quota Circuit Breaker & Anonymous Per-IP Rate Limit**
   - Keep editor AI import/rewrite open when `EDITOR_AI_ENABLED=true`.
   - Trip an in-memory cooldown circuit breaker (`AI_QUOTA_COOLDOWN_SECONDS`, default `600`) on upstream `402` / quota errors in DeepSeek & Zhipu OCR, returning structured `503` (`AI_QUOTA_EXHAUSTED`) while manual editing and PDF export stay unaffected.
   - Apply sliding-window per-IP limits (`ANON_AI_IMPORT_HOURLY_LIMIT=10`, `ANON_AI_REWRITE_HOURLY_LIMIT=30`) on anonymous AI calls.

## 2026-11-18 Follow-up Decision (Release & Scope Gate)

- **Approval**: 老板指示 `可以你去实施`
- **Confirmed Decisions**:
  1. **Keep PR #98 Scope Minimal for Merge**: Merge PR #98 (`551669a2`) to `main` without expanding scope to fix `backend/latex_utils.py:278` (`os.name == "darwin"`) or add automatic local-to-cloud PDF proxy fallback in non-admin `/api/pdf/render`. Track those two improvements separately if needed.
  2. **Deploy & Live-Verify `cococv.cn`**: Manually deploy `main` to production (`cococv.cn`) using the repository's manual release process (keeping backups and rollback readiness), then run live verification on `https://cococv.cn` for `/api/features`, anonymous `/share/<id>` handoff rendering, and Base64 `data:image` portrait embedding inside cloud XeLaTeX PDFs.

## 2026-11-18 Issue #99 Decision (Remove Job JD Match)

- **Issue**: https://github.com/wycocoyu/cococv/issues/99
- **Approval**: 老板拍板 `(Recommended) 合并清理前后端与旧弹窗，跑通测试与视觉验证后提 PR 等你拍板合入 main`
- **Confirmed Scope**:
  1. Remove both `🎯 岗位匹配` Workspace UI entries (`HeaderActions.tsx`, `SidePanel/index.tsx`), `'jd'` drawer tab (`SettingsDrawer.tsx`, `EditPreviewLayout.tsx`, `Workspace/v2/index.tsx`), and M5 drawer components/tests (`JdMatchDrawerContent.tsx`, `JdRadarChart*`, `JdStructuredInput.tsx`, `StarRewriteDiffCard.tsx`, `DerivativeResumeModal.tsx`).
  2. Remove dormant `<JdMatchDialog />` (`Workspace/v2/shared/JdMatchDialog.tsx`) and its dead scoring state in `Workspace/v2/index.tsx`.
  3. Remove backend M5 `/api/jd/*` routes & matching engine (`backend/routes/jd.py`, `backend/services/jd_matcher.py`, `jd_router` registration, `fork_resume` in `backend/routes/resumes.py`, `test_jd_api.py`, `test_jd_matching_engine.py`), migrating rate-limiter/feature-flag assertions in `test_issue_97_runtime_toggles.py` to `/api/resume/health-check` / `/api/resume/score` and cleaning `test_api_audit_regressions.py` + `backend/mcp/server.py` docstring.
  4. Preserve unrelated modules: official CocoCV MCP Server, `LandingPage` `JD_OPTIMIZE_CHIP` + `/api/resume/jd-optimize`, and Agent diagnosis workflow.
  5. Deliver via PR in isolated worktree (`refactor/issue-99-remove-jd-match`), verify with frontend/backend tests + Tabbit screenshot check, and wait for user approval before merging to `main`.
