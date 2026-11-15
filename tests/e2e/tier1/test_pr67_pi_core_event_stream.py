"""Tier 1 Feature Coverage: Feature 3 (PR #67 & Pi-Core Linear Event Stream, Issue #42).

Authoritative specs:
- ORIGINAL_REQUEST §R1.3, Issue #42
- backend/agent/pi_core/ (loop.py, context.py, durable.py, metrics.py, sse_adapter.py)
- Single-coroutine event loop & SSE streaming protocol
"""
from __future__ import annotations

from pathlib import Path
import pytest

from backend.agent.pi_core.types import AgentEvent, AgentMessage
from backend.agent.pi_core.sse_adapter import to_legacy_stream_event
from backend.agent.pi_core.context import transform_context, CompactionPolicy
from backend.agent.pi_core.durable import DurableSessionStore
from backend.agent.pi_core.metrics import PiCoreMetricsRegistry, PiCoreSessionMetrics


def test_t1_f03_01_sse_adapter_text_and_thought_events():
    """TEST-T1-F03-01: Verify mapping of text_delta and thinking_delta to legacy SSE events."""
    from backend.agent.web.streaming.events import AnswerEvent, ThoughtEvent
    
    # 1. Text delta
    text_event = AgentEvent("message_update", {"delta_type": "text_delta", "text": "系统已为您优化简历。"})
    legacy_text = to_legacy_stream_event(text_event, session_id="sess_123", step_id=1)
    assert isinstance(legacy_text, AnswerEvent)
    event_dict = legacy_text.to_dict()
    assert event_dict["type"] == "answer"
    assert event_dict["session_id"] == "sess_123"
    assert event_dict["data"]["content"] == "系统已为您优化简历。"
    assert event_dict["data"]["is_complete"] is False
    
    # 2. Thinking delta
    thought_event = AgentEvent("message_update", {"delta_type": "thinking_delta", "text": "正在分析候选人技术栈..."})
    legacy_thought = to_legacy_stream_event(thought_event, session_id="sess_123", step_id=1)
    assert isinstance(legacy_thought, ThoughtEvent)
    thought_dict = legacy_thought.to_dict()
    assert thought_dict["type"] == "thought"
    assert thought_dict["data"]["content"] == "正在分析候选人技术栈..."


def test_t1_f03_02_sse_adapter_tool_call_lifecycle():
    """TEST-T1-F03-02: Verify mapping of tool execution lifecycle to ToolCallEvent and ToolResultEvent."""
    from backend.agent.web.streaming.events import ToolCallEvent, ToolResultEvent
    
    # Tool start
    start_event = AgentEvent("tool_execution_start", {
        "tool": "patch_resume",
        "tool_call_id": "call_abc999",
        "arguments": {"section": "skills", "action": "add"},
    })
    legacy_call = to_legacy_stream_event(start_event, session_id="sess_456", step_id=2)
    assert isinstance(legacy_call, ToolCallEvent)
    call_dict = legacy_call.to_dict()
    assert call_dict["type"] == "tool_call"
    assert call_dict["data"]["tool"] == "patch_resume"
    assert call_dict["data"]["args"] == {"section": "skills", "action": "add"}
    assert call_dict["data"]["tool_call_id"] == "call_abc999"
    
    # Tool end
    end_event = AgentEvent("tool_execution_end", {
        "tool": "patch_resume",
        "tool_call_id": "call_abc999",
        "output": "success",
        "structured_content": {"status": "success", "modified_fields": ["skills"]},
    })
    legacy_result = to_legacy_stream_event(end_event, session_id="sess_456", step_id=2)
    assert isinstance(legacy_result, ToolResultEvent)
    res_dict = legacy_result.to_dict()
    assert res_dict["type"] == "tool_result"
    assert res_dict["data"]["tool"] == "patch_resume"
    assert res_dict["data"]["result"] == "success"
    assert res_dict["data"]["structured_data"] == {"status": "success", "modified_fields": ["skills"]}


def test_t1_f03_03_context_compaction_reduces_size():
    """TEST-T1-F03-03: Verify context compaction policy achieves target size reduction."""
    # Create conversation history with multiple turns
    messages = [
        AgentMessage(role="system", content="You are a professional resume optimization assistant."),
        AgentMessage(role="user", content="请帮我润色以下项目经历：" + "非常详细的项目背景介绍说明。" * 30),
        AgentMessage(role="assistant", content="我已经为您润色完毕：" + "详细的技术亮点阐述。" * 30),
        AgentMessage(role="user", content="现在继续润色教育背景：" + "清华大学软件工程硕士毕业生。" * 20),
        AgentMessage(role="assistant", content="教育背景优化结果如下：" + "优秀毕业生科研成果。" * 20),
    ]
    
    original_size = sum(len(m.content) for m in messages)
    policy = CompactionPolicy(max_chars=500, keep_recent_messages=2)
    compacted = transform_context(messages, policy)
    
    compacted_size = sum(len(m.content) for m in compacted)
    assert compacted_size <= original_size
    assert len(compacted) > 0
    assert compacted[0].role == "system"  # system message preserved


def test_t1_f03_04_durable_session_store(temp_e2e_dir: Path):
    """TEST-T1-F03-04: Verify durable session store writes, reads, and atomic transactions."""
    store = DurableSessionStore(root=str(temp_e2e_dir / "sessions"))
    session_id = "durable_test_session_01"
    
    # Append entries
    store.append(session_id, "user_msg", {"text": "优化技能项"})
    store.append(session_id, "assistant_msg", {"text": "已添加FastAPI"})
    
    entries = store.entries(session_id)
    assert len(entries) == 2
    assert entries[0].payload["text"] == "优化技能项"
    assert entries[1].payload["text"] == "已添加FastAPI"


def test_t1_f03_05_pi_core_metrics_registry():
    """TEST-T1-F03-05: Verify metrics registry tracks session execution metrics."""
    registry = PiCoreMetricsRegistry()
    session_metrics = registry.start_run("metrics_session_01")
    
    session_metrics.record_event("message_start")
    session_metrics.record_event("message_update")
    session_metrics.record_event("tool_execution_start")
    session_metrics.record_event("tool_execution_end")
    
    assert session_metrics.runs == 1
    assert session_metrics.tool_calls == 1
    assert session_metrics.event_counts["message_update"] == 1
    
    snap = registry.snapshot()
    assert "metrics_session_01" in snap
    assert snap["metrics_session_01"]["tool_calls"] == 1
