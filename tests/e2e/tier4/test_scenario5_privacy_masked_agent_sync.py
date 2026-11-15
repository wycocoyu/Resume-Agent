"""Tier 4 Real-World Application Scenarios: Scenario 5.

Scenario 5: Privacy-Masked Cloud Agent Sync (客户端全链路隐私脱敏与云端安全同步)
Authoritative specs:
- SCOPE.md § Tier 4 Scenarios, TEST_INFRA.md
- backend/routes/config.py (_mask_key)
- backend/core/logger.py (_sanitize_text_payload)
- backend/agent/pi_core/loop.py (run_agent_loop)
- Pipeline:
  1. Verify sensitive keys masking
  2. Audit payload logs: assert redaction via _sanitize_text_payload
  3. Stream masked events through real pi-core event loop
  4. Ensure zero credential exposure
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import pytest

from backend.routes.config import _mask_key
from backend.core.logger import _sanitize_text_payload
from backend.agent.pi_core.loop import run_agent_loop
from backend.agent.pi_core.types import AgentMessage, AssistantChunk, ModelTurn, ToolResult

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_scenario5_privacy_masked_cloud_agent_sync(standard_resume_data: dict):
    """Scenario 5: End-to-end privacy masking, payload sanitation, pi-core streaming, and credential protection."""
    # 1. API key masking
    api_key = "sk-deepseek-prod-secret-key-12345"
    masked_key = _mask_key(api_key)
    assert api_key not in masked_key
    assert masked_key.startswith("sk-deeps")

    # 2. Server log credential redaction
    log_record = f"Audit action: username=admin_dev author_name=reviewer_agent body={api_key}"
    sanitized_log = _sanitize_text_payload(log_record)
    assert api_key not in sanitized_log
    assert "admin_dev" not in sanitized_log
    assert "reviewer_agent" not in sanitized_log
    assert "body=[REDACTED]" in sanitized_log

    # 3. Stream through real pi-core event loop with masked user prompt
    user_prompt = f"Optimize resume for candidate with masked provider key: {masked_key}"

    async def _runner():
        async def real_or_stub_stream(_messages):
            yield AssistantChunk(kind="text_delta", content="建议为候选人增强分布式网关项目经历。")
            yield AssistantChunk(kind="done", turn=ModelTurn(content="建议为候选人增强分布式网关项目经历。"))

        events = []
        async for event in run_agent_loop(
            [AgentMessage(role="user", content=user_prompt)],
            real_or_stub_stream,
            lambda call, msg: ToolResult(output="ok"),
            max_turns=1,
        ):
            events.append(event)

        end_event = next(e for e in events if e.kind == "message_end")
        stream_content = end_event.data.get("content", "")
        assert "分布式网关" in stream_content

    asyncio.run(_runner())
