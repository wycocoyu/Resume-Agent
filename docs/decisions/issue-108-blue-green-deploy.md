# Decision Log — Issue 108

- **Date**: 2026-11-18
- **Issue**: https://github.com/wycocoyu/cococv/issues/108
- **Approval**: 老板拍板 `(Recommended) 宿主机 PM2 + Nginx 双槽位脚本（贴合当前线上现状，免停机迁移，最稳）` 与 `可以。但是还是不要打通 CICD 流程。只允许手动发布`

## Confirmed Decisions

1. **Manual Release Only (Strict No-CI/CD Boundary)**
   - Keep `.github/workflows/ci.yml` strictly `workflow_dispatch` only and keep server `auto-deploy.sh` cron paused.
   - Never connect GitHub Actions CD, webhooks, or scheduled auto-pull triggers to blue-green deployment; every production release and rollback must be invoked manually by an operator via `./scripts/deploy-blue-green.sh`.

2. **Host PM2 + Nginx Dual-Slot Blue-Green Architecture**
   - Keep the existing host Nginx + PM2 + PostgreSQL production topology rather than forcing a disruptive container migration.
   - Run two backend slots (`cococv-backend-blue` on port `9001`, `cococv-backend-green` on port `9002`) behind a symlink/include-managed Nginx `upstream cococv_backend` block (`deploy/nginx/`).
   - Manage frontend `frontend/dist` via atomic POSIX symlink switching over `frontend/dist_releases/<release_id>`, copying non-colliding `assets/*` chunks from the active release so cached browser tabs do not hit 404s during cutover.

3. **Readiness & Commit Parity Gate Before Cutover**
   - Keep `GET /api/health` backward-compatible (`{"status": "ok", "slot": ..., "commit": ...}`) and add `GET /api/health/ready` checking live database connectivity (`SELECT 1`).
   - Deployment scripts (`scripts/blue_green_deploy.py` + `scripts/deploy-blue-green.sh`) must wait for the standby slot's `/api/health/ready` to report `status == "ready"`, matching `slot`, and matching `commit` SHA before touching Nginx upstream or the frontend symlink.
   - Validate Nginx syntax (`nginx -t`) before `nginx -s reload`, automatically restoring the previous upstream file on any validation or reload error.

4. **Graceful Drain, One-Command Rollback & Delivery Boundary**
   - Wait for a configurable drain grace window (`COCOCV_DRAIN_SECONDS`, default `15s`) after Nginx reload before stopping the previous backend slot so active SSE/XeLaTeX requests can finish.
   - Support instant `rollback` back to the recorded `previous_slot` and `previous_release` (switching directly if standby is still warm, or checking out `previous_commit` and warming up the slot before cutover if already drained).
   - Deliver via isolated worktree (`feat/issue-108-blue-green-deploy`) and PR #109, then manually wire up host Nginx upstream and verify live cutover/rollback without enabling any CI/CD triggers.
