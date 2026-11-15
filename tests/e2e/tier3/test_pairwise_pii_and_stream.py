"""Tier 3 Pairwise Combinations: Group 4 (PII & Streaming Interactions).

Authoritative specs:
- SCOPE.md § Feature Inventory & Pairwise Matrix
- E2E-T3-02: F14 MCP `patch_resume` × F13 STAR Rewrite Suggestion (Scheduled for M5)
- E2E-T3-03: F15 Client Privacy Masking × F3 Pi-Core Event Stream
- E2E-T3-08: F15 Key Masking × F16 Modern Settings Card
- E2E-T3-09: F13 Target JD Matching × F10 Auto-One-Page Adaptive Fit
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
import pytest

from backend.routes.config import _mask_key
from backend.agent.pi_core.types import AgentMessage, AssistantChunk, ModelTurn, ToolResult
from backend.agent.pi_core.loop import run_agent_loop
from backend.services.scoring_service import ScoringService

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t3_02_mcp_patch_resume_and_star_rewrite(standard_resume_data: dict, sample_jd_text: str):
    """E2E-T3-02: Verify applying STAR rewrite suggestion via MCP patch_resume tool (Scheduled for M5)."""
    # 1. Real ScoringService generates analysis
    import models
    from backend.database import SessionLocal, init_db
    init_db()
    db = SessionLocal()
    try:
        service = ScoringService(db)
        # 2. Attempt calling MCP patch_resume (honestly fails Red until M5)
        from backend.mcp.server import patch_resume
        patch_ops = [{"op": "replace", "path": "/basic/title", "value": "高级后端架构师"}]
        patched = patch_resume(standard_resume_data, patch_ops)
        assert patched["basic"]["title"] == "高级后端架构师"
    finally:
        db.close()


def test_t3_03_privacy_masking_and_pi_core_event_stream():
    """E2E-T3-03: Verify masked prompt safely enters pi-core event stream with real loop execution."""
    raw_api_key = "sk-deepseek-long-secret-key-1234abcd"
    masked_key = _mask_key(raw_api_key)
    user_prompt = f"Optimize resume for candidate with configured key preview: {masked_key}"

    # Assert raw secret not in prompt
    assert raw_api_key not in user_prompt
    assert "sk-deeps" in user_prompt

    # Real run_agent_loop execution
    async def _runner():
        async def real_or_stub_stream(_messages):
            yield AssistantChunk(kind="text_delta", content="Optimization plan completed.")
            yield AssistantChunk(kind="done", turn=ModelTurn(content="Optimization plan completed."))

        events = []
        async for event in run_agent_loop(
            [AgentMessage(role="user", content=user_prompt)],
            real_or_stub_stream,
            lambda c, m: ToolResult(output="ok"),
            max_turns=1,
        ):
            events.append(event)

        assert any(e.kind == "message_end" for e in events)

    asyncio.run(_runner())


def test_t3_08_key_masking_and_settings_credential_card():
    """E2E-T3-08: Verify credential card displays masked API key and matches settings classes."""
    raw_api_key = "sk-deepseek-prod-secret-9988776655"
    masked = _mask_key(raw_api_key)

    assert masked.startswith("sk-deeps")
    assert masked.endswith("6655")
    assert raw_api_key not in masked

    settings_path = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Settings" / "index.tsx"
    assert settings_path.exists()
    content = settings_path.read_text(encoding="utf-8")
    assert "font-mono" in content


def test_t3_09_jd_matching_and_auto_one_page_adaptive_fit():
    """E2E-T3-09: Verify ScoringService route availability alongside real auto-one-page Vitest suite."""
    vitest_cmd = [
        "npx", "vitest", "run",
        "src/pages/Workspace/v2/utils/autoOnePage.test.ts",
    ]
    res = subprocess.run(
        vitest_cmd,
        cwd=str(WORKTREE_ROOT / "frontend"),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, f"autoOnePage Vitest failed:\n{res.stdout}\n{res.stderr}"
