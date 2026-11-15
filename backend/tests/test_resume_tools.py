"""Resume tool composition and context injection tests."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.core.logger import setup_logging

setup_logging(False, "INFO", "logs/test")

from backend.agent.agent.shared_state import AgentSharedState
from backend.agent.pi_core.resume_tools import (
    build_resume_tool_collection,
    inject_resume_tool_context,
)


DOMAIN_TOOL_NAMES = {
    "cv_reader_agent",
    "list_resumes",
    "get_resume_detail",
    "show_resume",
    "cv_analyzer_agent",
    "cv_suggestions_agent",
    "cv_editor_agent",
    "generate_resume",
}


def test_full_capability_contains_base_and_all_resume_tools(monkeypatch):
    monkeypatch.delenv("AGENT_ASKING_MODE_ENABLED", raising=False)

    collection = build_resume_tool_collection("full")

    assert set(collection.tool_map) == {"ask_human", "terminate"} | DOMAIN_TOOL_NAMES


def test_capability_whitelists_keep_base_tools_and_only_allowed_domain_tools(
    monkeypatch,
):
    monkeypatch.delenv("AGENT_ASKING_MODE_ENABLED", raising=False)

    analyze = build_resume_tool_collection("analyze")
    edit = build_resume_tool_collection("edit")
    optimize = build_resume_tool_collection("optimize")

    assert set(analyze.tool_map) == {
        "ask_human",
        "terminate",
        "cv_reader_agent",
        "show_resume",
        "cv_analyzer_agent",
    }
    assert set(edit.tool_map) == {
        "ask_human",
        "terminate",
        "cv_reader_agent",
        "show_resume",
        "cv_editor_agent",
    }
    assert set(optimize.tool_map) == {
        "ask_human",
        "terminate",
        "cv_reader_agent",
        "show_resume",
        "cv_analyzer_agent",
        "cv_editor_agent",
    }


def test_asking_mode_toggle_is_evaluated_when_tools_are_built(monkeypatch):
    monkeypatch.delenv("AGENT_ASKING_MODE_ENABLED", raising=False)
    disabled = build_resume_tool_collection("full")
    assert "ask_user_question" not in disabled.tool_map

    monkeypatch.setenv("AGENT_ASKING_MODE_ENABLED", "true")
    enabled = build_resume_tool_collection("full")
    assert "ask_user_question" in enabled.tool_map


def test_context_injection_updates_declared_tool_fields():
    class ContextAwareTool:
        session_id = None
        user_id = None
        shared_state = None

    tool = ContextAwareTool()
    shared_state = AgentSharedState(session_id="session-1")

    inject_resume_tool_context(
        [tool],
        session_id="session-1",
        user_id="user-1",
        shared_state=shared_state,
    )

    assert tool.session_id == "session-1"
    assert tool.user_id == "user-1"
    assert tool.shared_state is shared_state
