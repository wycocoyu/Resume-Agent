from backend.agent.pi_core import AgentMessage, CompactionPolicy, ToolCall, compact_context, transform_context


def test_compaction_preserves_tool_call_structure_and_recent_messages():
    call = ToolCall("call-1", "cv_editor_agent", {"path": "projects[0]"})
    history = [
        AgentMessage(role="system", content="system prompt"),
        AgentMessage(role="user", content="old " * 100),
        AgentMessage(role="assistant", content="narration " * 100, tool_calls=(call,)),
        AgentMessage(role="tool", content="tool output " * 100, tool_call_id="call-1"),
        AgentMessage(role="user", content="最新要求"),
    ]

    compacted = compact_context(
        history,
        CompactionPolicy(max_chars=180, keep_recent_messages=1),
    )

    assert compacted[-1].content == "最新要求"
    assert compacted[2].tool_calls[0].id == "call-1"
    assert compacted[3].tool_call_id == "call-1"
    assert any(message.metadata.get("compacted") for message in compacted)
    assert all(message.content != "" for message in compacted)


def test_transform_context_applies_supersede_and_compaction_without_mutating_source():
    old = AgentMessage(role="tool", content="old " * 100, supersede_key="resume")
    new = AgentMessage(role="tool", content="new resume", supersede_key="resume")
    history = [old, new]

    transformed = transform_context(
        history,
        CompactionPolicy(max_chars=80, keep_recent_messages=1),
    )

    assert history[0].content.startswith("old ")
    assert transformed[0].content == "[Superseded by a newer read/edit]"
    assert transformed[1].content == "new resume"
