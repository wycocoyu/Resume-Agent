# Decision & Progress Log — Issue #103 (Track A: Zero-Login Web Resume Agent + Browser BYOK)

- **Date**: 2026-11-18
- **Status**: Draft PR v1 (`feat/issue-103-anon-agent-byok`, unmerged WIP checkpoint — backend route wiring & full E2E scheduled for follow-up commits)
- **Issue**: https://github.com/wycocoyu/cococv/issues/103
- **OSS Audit Comment**: https://github.com/wycocoyu/cococv/issues/103#issuecomment-6974563993
- **Approval**: 老板拍板 `/swarm 按照你的推荐去实施。先提 PR 先不合并。在 PR 里启动和测试`，随后指示 `可以先提一版PR。后续再继续做`

## Confirmed Architecture Decisions (Track A vs Track B)

1. **Track A (Web Public Side) — Zero-Login Sidebar Resume Agent + Browser BYOK (`dayuanjiang/next-ai-draw-io` pattern)**:
   - Re-enable built-in Pi-Core sidebar Resume Agent (`AGENT_ENABLED=true` default, keeping `AGENT_ENABLED=false` hot kill switch returning `503 AGENT_DISABLED` intact).
   - Decouple `/api/agent/stream*` and `/api/agent/approval` from mandatory `get_current_user` login: anonymous users keep resume drafts (`LocalStorageAdapter` + `IndexedDB`) and agent chat history (`cococv_agent_sessions_v1` in `localStorage`) strictly client-side, passing per-request `resume_data` and recent `history_messages` without writing server DB rows or server JSON chat files.
   - Isolate concurrent anonymous sessions via `X-Anon-Session-Token` (`owner_key = anon:<token>`) with `403` cross-owner protection, and protect server-paid LLM quota via `ai_guard.py` per-IP hourly sliding-window limiting (`ANON_AI_AGENT_HOURLY_LIMIT=20`) + upstream 402 circuit breaker (`AI_QUOTA_COOLDOWN_SECONDS=600`).
   - Support Browser BYOK (`localStorage` `cococv_agent_byok_v1` + headers `X-AI-Provider`, `X-AI-Api-Key`, `X-AI-Base-Url`, `X-AI-Model`), bypassing server IP limits and circuit breaker while enforcing SSRF validation (`validate_byok_base_url`), per-session isolated `LLM` instances (`LLM.create_isolated`), and secret redaction (`redact_secrets`).
2. **Track B (Deferred) — Local Coding Harness / MCP Canvas Bridge**:
   - Deferred outside this PR; existing CocoCV MCP Server (`/mcp`, `backend/mcp/server.py`) remains independent for local CLI/editor workflows (`claude` / `codex` / `agy`).

## Isolated Worktree & Branch State

Main repo `/Users/mac/开源工具/ResumeAgent` (`main` @ `b123e2b6`) is completely clean and untouched. Both temporary worker branches (`swarm/issue-103-backend` @ `da337bc6`, `swarm/issue-103-frontend` @ `7dd12493`) have been consolidated into the single PR branch/worktree:

- **PR Worktree**: `/Users/mac/开源工具/ResumeAgent-wt-103`
- **PR Branch**: `feat/issue-103-anon-agent-byok` (base: `main`, unmerged Draft PR)

## Implementation Checklist Snapshot

### Included in v1 Draft PR
- **Backend foundations (`da337bc6`)**:
  - `.env.example`, `backend/services/runtime_features.py`: flipped `AGENT_ENABLED` default to `true`, added `get_anon_ai_agent_hourly_limit` (`ANON_AI_AGENT_HOURLY_LIMIT=20`), documented `ALLOW_LOCAL_BYOK_URLS=false`.
  - `backend/services/ai_guard.py`: added `"agent"` bucket, `InvalidByokConfigError` (`400 INVALID_BYOK_BASE_URL`), `validate_byok_base_url` (HTTPS + private/loopback/CGNAT/metadata IP & DNS SSRF block), `redact_secrets`, and `check_agent_ai_guard`.
  - `backend/agent/llm.py`: added `LLM.create_isolated(...)` bypassing singleton `_instances`.
  - `backend/agent/pi_core/resume_agent.py`, `resume_domain.py`, `resume_tools.py`, `tool_runtime.py`, `backend/agent/approval.py`: propagated isolated `llm` and `owner_key` across runtime & approval pending creation.
  - `backend/agent/tool/cv_analyzer_agent_tool.py`, `cv_suggestions_agent_tool.py`, `cv_editor_agent_tool.py`, `generate_resume_tool.py`: wired injected `llm` + skipped DB persist when `user_id` is absent.
  - `backend/agent/web/schemas/stream.py` & `backend/agent/web/streaming/state_machine.py`: added `history_messages` schema field and `redact_secrets` masking in error state transitions.
- **Frontend UI & client storage (`7dd12493`)**:
  - `frontend/src/lib/runtimeEnv.ts` & `runtimeEnv.features.test.ts`: flipped `agent_enabled` default fallback to `true`.
  - `frontend/src/services/agentLocalHistory.ts` & `agentLocalHistory.test.ts`: added `cococv_anon_agent_token` and `cococv_agent_sessions_v1` browser storage CRUD + sync event.
  - `frontend/src/services/agentByokConfig.ts` & `agentByokConfig.test.ts`: added `cococv_agent_byok_v1`, provider presets, and `getAgentRequestHeaders()`.
  - `frontend/src/components/agent-chat/ByokConfigModal.tsx` & `ByokConfigModal.test.tsx`: added BYOK modal UI and component tests.
  - `frontend/src/services/agentStream.ts`, `frontend/src/transports/SSETransport.ts`, `frontend/src/hooks/useCLTP.ts`, `frontend/src/pages/WorkspaceLayout/index.tsx`, `frontend/src/components/sidebar/RecentSessions.tsx`, `frontend/src/pages/AgentChat/CocoChat.tsx`: wired zero-login entry, local history routing, top bar mode badge + `自带 API Key` modal trigger, and rate-limit CTA.

### Remaining Before Ready-for-Review / Merge
- `backend/agent/web/routes/stream.py`: convert `/stream`, `/stream/stop/{conversation_id}`, `/stream/session/{conversation_id}`, session-scoped `/stream/metrics` to `get_current_user_optional`, enforce `owner_key` `403`, strip `user_id`/`_meta.user_id` from anonymous `resume_data`, use `ChatHistoryManager(storage=None)` + `history_messages` rehydration, apply `X-AI-*` BYOK headers + `validate_byok_base_url` + `check_agent_ai_guard`, restore server channel if BYOK is cleared, and scrub secrets mid-stream.
- `backend/agent/web/routes/approval.py`: switch `/approval` to `get_current_user_optional` + `owner_key` ownership verification (and verify frontend approval callers attach `getAgentRequestHeaders()`).
- Update default `agent_enabled` assertions in `backend/tests/test_issue_97_runtime_toggles.py`, add `backend/tests/test_issue_103_anon_agent_byok.py`, and run full `pytest backend/tests/`.
- Update `frontend/src/data/changelog.ts` (merge into `2026-11-18`, bump `3.14.3` -> `3.15.0`, pure `YYYY-MM-DD`) and link this doc in `docs/README.md`.
- Run full `npm test -- --run` and live backend/frontend + `~/.local/bin/tabbit-cli` visual checks against this PR worktree.
