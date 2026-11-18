# Decision & Progress Log — Issue #103 (Track A: Zero-Login Web Resume Agent + Browser BYOK)

- **Date**: 2026-11-18
- **Status**: Paused at WIP Checkpoint (`swarm` stopped cleanly per user request; NOT merged or pushed)
- **Issue**: https://github.com/wycocoyu/cococv/issues/103
- **OSS Audit Comment**: https://github.com/wycocoyu/cococv/issues/103#issuecomment-6974563993
- **Approval**: 老板拍板 `/swarm 按照你的推荐去实施。先提 PR 先不合并。在 PR 里启动和测试`，随后指示 `你去帮我记录一下进度 然后停止运行。后面我再优化`

## Confirmed Architecture Decisions (Track A vs Track B)

1. **Track A (Web Public Side) — Zero-Login Sidebar Resume Agent + Browser BYOK (`dayuanjiang/next-ai-draw-io` pattern)**:
   - Re-enable built-in Pi-Core sidebar Resume Agent (`AGENT_ENABLED=true` default, keeping `AGENT_ENABLED=false` hot kill switch returning `503 AGENT_DISABLED` intact).
   - Decouple `/api/agent/stream*` and `/api/agent/approval` from mandatory `get_current_user` login: anonymous users keep resume drafts (`LocalStorageAdapter` + `IndexedDB`) and agent chat history (`cococv_agent_sessions_v1` in `localStorage`) strictly client-side, passing per-request `resume_data` and recent `history_messages` without writing server DB rows or server JSON chat files.
   - Isolate concurrent anonymous sessions via `X-Anon-Session-Token` (`owner_key = anon:<token>`) with `403` cross-owner protection, and protect server-paid LLM quota via `ai_guard.py` per-IP hourly sliding-window limiting (`ANON_AI_AGENT_HOURLY_LIMIT=20`) + upstream 402 circuit breaker (`AI_QUOTA_COOLDOWN_SECONDS=600`).
   - Support Browser BYOK (`localStorage` `cococv_agent_byok_v1` + headers `X-AI-Provider`, `X-AI-Api-Key`, `X-AI-Base-Url`, `X-AI-Model`), bypassing server IP limits and circuit breaker while enforcing SSRF validation (`validate_byok_base_url`), per-session isolated `LLM` instances (`LLM.create_isolated`), and secret redaction (`redact_secrets`).
2. **Track B (Deferred) — Local Coding Harness / MCP Canvas Bridge**:
   - Deferred outside this PR; existing CocoCV MCP Server (`/mcp`, `backend/mcp/server.py`) remains independent for local CLI/editor workflows (`claude` / `codex` / `agy`).

## Isolated Local Worktrees & WIP Checkpoint Commits

Main repo `/Users/mac/开源工具/ResumeAgent` (`main` @ `b123e2b6`) is completely clean and untouched.

| Role | Directory | Branch | HEAD Commit | State |
| :--- | :--- | :--- | :--- | :--- |
| Integration / PR | `/Users/mac/开源工具/ResumeAgent-wt-103` | `feat/issue-103-anon-agent-byok` | (this commit) | Decision & progress log only; unmerged |
| Backend WIP | `/Users/mac/开源工具/ResumeAgent-wt-103-be` | `swarm/issue-103-backend` | `da337bc6` | Partial WIP committed (15 files); not yet tested |
| Frontend WIP | `/Users/mac/开源工具/ResumeAgent-wt-103-fe` | `swarm/issue-103-frontend` | `7dd12493` | Core UI & BYOK services committed WIP (14 files); not yet verified via build/test |

## Implementation Checklist Snapshot

### Backend (`swarm/issue-103-backend` @ `da337bc6`)
- **Done (WIP, unverified by pytest)**:
  - `.env.example`, `backend/services/runtime_features.py`: flipped `AGENT_ENABLED` default to `true`, added `get_anon_ai_agent_hourly_limit` (`ANON_AI_AGENT_HOURLY_LIMIT=20`), documented `ALLOW_LOCAL_BYOK_URLS=false`.
  - `backend/services/ai_guard.py`: added `"agent"` bucket, `InvalidByokConfigError` (`400 INVALID_BYOK_BASE_URL`), `validate_byok_base_url` (HTTPS + private/loopback/CGNAT/metadata IP & DNS SSRF block), `redact_secrets`, and `check_agent_ai_guard`.
  - `backend/agent/llm.py`: added `LLM.create_isolated(...)` bypassing singleton `_instances`.
  - `backend/agent/pi_core/resume_agent.py`, `resume_domain.py`, `resume_tools.py`, `tool_runtime.py`, `backend/agent/approval.py`: propagated isolated `llm` and `owner_key` across runtime & approval pending creation.
  - `backend/agent/tool/cv_analyzer_agent_tool.py`, `cv_suggestions_agent_tool.py`, `cv_editor_agent_tool.py`, `generate_resume_tool.py`: wired injected `llm` + skipped DB persist when `user_id` is absent.
  - `backend/agent/web/schemas/stream.py` & `backend/agent/web/streaming/state_machine.py`: added `history_messages` schema field and `redact_secrets` masking in error state transitions.
- **Remaining on Backend**:
  - `backend/agent/web/routes/stream.py`: convert `/stream`, `/stream/stop/{conversation_id}`, `/stream/session/{conversation_id}`, session-scoped `/stream/metrics` to `get_current_user_optional`, enforce `owner_key` `403`, strip `user_id`/`_meta.user_id` from anonymous `resume_data`, use `ChatHistoryManager(storage=None)` + `history_messages` rehydration, apply `X-AI-*` BYOK headers + `validate_byok_base_url` + `check_agent_ai_guard`, restore server channel if BYOK is later cleared on same session, and protect upstream quota vs BYOK secret masking.
  - `backend/agent/web/routes/approval.py`: switch `/approval` to `get_current_user_optional` + `owner_key` ownership verification.
  - Verify `backend/application/resume_diagnosis_engine.py` `ResumeGuidanceModule.__init__` accepts `llm=` parameter passed by `cv_analyzer_agent_tool.py` / `cv_suggestions_agent_tool.py`.
  - Update default `agent_enabled` assertions in `backend/tests/test_issue_97_runtime_toggles.py` and add `backend/tests/test_issue_103_anon_agent_byok.py`, then run full `pytest backend/tests/`.

### Frontend & Docs (`swarm/issue-103-frontend` @ `7dd12493`)
- **Done (WIP, unverified by `npm test` / `npm run build`)**:
  - `frontend/src/lib/runtimeEnv.ts` & `runtimeEnv.features.test.ts`: flipped `agent_enabled` default fallback to `true`.
  - `frontend/src/services/agentLocalHistory.ts` & `agentLocalHistory.test.ts`: added `cococv_anon_agent_token` and `cococv_agent_sessions_v1` browser storage CRUD + sync event.
  - `frontend/src/services/agentByokConfig.ts` & `agentByokConfig.test.ts`: added `cococv_agent_byok_v1`, provider presets, and `getAgentRequestHeaders()`.
  - `frontend/src/components/agent-chat/ByokConfigModal.tsx` & `ByokConfigModal.test.tsx`: added BYOK modal UI and component tests.
  - `frontend/src/services/agentStream.ts`, `frontend/src/transports/SSETransport.ts`, `frontend/src/hooks/useCLTP.ts`, `frontend/src/pages/WorkspaceLayout/index.tsx`, `frontend/src/components/sidebar/RecentSessions.tsx`, `frontend/src/pages/AgentChat/CocoChat.tsx`: wired zero-login entry, local history routing, top bar mode badge + `自带 API Key` modal trigger, and rate-limit CTA.
- **Remaining on Frontend & Verification**:
  - Review & run `npm test -- --run` and `npm run build` in `ResumeAgent-wt-103-fe/frontend` (fix any type/test/style issues and confirm approval requests include `getAgentRequestHeaders()`).
  - Update `frontend/src/data/changelog.ts` (merge into `2026-11-18` entry, bump `3.14.3` -> `3.15.0`, pure `YYYY-MM-DD`) and link this doc in `docs/README.md`.
  - Integrate both branches into `/Users/mac/开源工具/ResumeAgent-wt-103`, run full `pytest` + live backend/frontend + `~/.local/bin/tabbit-cli` visual checks, then open an unmerged PR against `main`.

## Resume Commands

```bash
# Inspect exact WIP commits
git -C /Users/mac/开源工具/ResumeAgent-wt-103-be show da337bc6 --stat
git -C /Users/mac/开源工具/ResumeAgent-wt-103-fe show 7dd12493 --stat

# Diff against main
git -C /Users/mac/开源工具/ResumeAgent-wt-103-be diff main..HEAD
git -C /Users/mac/开源工具/ResumeAgent-wt-103-fe diff main..HEAD
```
