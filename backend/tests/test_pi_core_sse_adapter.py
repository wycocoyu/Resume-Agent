from backend.agent.pi_core import AgentEvent, to_legacy_stream_event


def test_pi_core_events_map_to_existing_sse_contract():
    answer = to_legacy_stream_event(
        AgentEvent("message_update", {"delta_type": "text_delta", "text": "正在分析"}),
        session_id="s1",
        step_id=2,
    )
    assert answer is not None
    assert answer.to_dict()["type"] == "answer"
    assert answer.to_dict()["data"]["delta"] == "正在分析"

    tool_start = to_legacy_stream_event(
        AgentEvent(
            "tool_execution_start",
            {
                "tool": "cv_editor_agent",
                "arguments": {"path": "projects[0]"},
                "tool_call_id": "call-1",
            },
        ),
        session_id="s1",
        step_id=2,
    )
    assert tool_start is not None
    assert tool_start.to_dict()["type"] == "tool_call"
    assert tool_start.to_dict()["data"]["tool_call_id"] == "call-1"

    tool_end = to_legacy_stream_event(
        AgentEvent(
            "tool_execution_end",
            {
                "tool": "cv_editor_agent",
                "tool_call_id": "call-1",
                "output": "已生成",
                "structured_content": {"type": "resume_patch"},
            },
        ),
        session_id="s1",
        step_id=2,
    )
    assert tool_end is not None
    assert tool_end.to_dict()["type"] == "tool_result"
    assert tool_end.to_dict()["data"]["structured_data"] == {"type": "resume_patch"}


def test_internal_message_markers_do_not_leak_as_new_public_event_types():
    assert (
        to_legacy_stream_event(
            AgentEvent("message_start"),
            session_id="s1",
            step_id=1,
        )
        is None
    )
    assert (
        to_legacy_stream_event(
            AgentEvent("message_end"),
            session_id="s1",
            step_id=1,
        )
        is None
    )
