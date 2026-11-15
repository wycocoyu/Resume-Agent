from importlib import import_module


_EXPORTS = {
    "AskUserQuestionTool": (
        "backend.agent.tool.ask_user_question_tool",
        "AskUserQuestionTool",
    ),
    "BaseTool": ("backend.agent.tool.base", "BaseTool"),
    "CreateChatCompletion": (
        "backend.agent.tool.create_chat_completion",
        "CreateChatCompletion",
    ),
    "CVAnalyzerAgentTool": (
        "backend.agent.tool.cv_analyzer_agent_tool",
        "CVAnalyzerAgentTool",
    ),
    "CVSuggestionsAgentTool": (
        "backend.agent.tool.cv_suggestions_agent_tool",
        "CVSuggestionsAgentTool",
    ),
    "CVEditorAgentTool": (
        "backend.agent.tool.cv_editor_agent_tool",
        "CVEditorAgentTool",
    ),
    "CVReaderAgentTool": (
        "backend.agent.tool.cv_reader_agent_tool",
        "CVReaderAgentTool",
    ),
    "ReadCVContext": ("backend.agent.tool.cv_reader_tool", "ReadCVContext"),
    "GenerateResumeTool": (
        "backend.agent.tool.generate_resume_tool",
        "GenerateResumeTool",
    ),
    "ShowResumeTool": (
        "backend.agent.tool.show_resume_tool",
        "ShowResumeTool",
    ),
    "ListResumesTool": (
        "backend.agent.tool.list_resumes_tool",
        "ListResumesTool",
    ),
    "GetResumeDetailTool": (
        "backend.agent.tool.get_resume_detail_tool",
        "GetResumeDetailTool",
    ),
    "Terminate": ("backend.agent.tool.terminate", "Terminate"),
    "ToolCollection": (
        "backend.agent.tool.tool_collection",
        "ToolCollection",
    ),
}

__all__ = [
    "AskUserQuestionTool",
    "BaseTool",
    "Bash",
    "PlanningTool",
    "StrReplaceEditor",
    "Terminate",
    "ToolCollection",
    "CreateChatCompletion",
    "ReadCVContext",
    "CVReaderAgentTool",
    "CVAnalyzerAgentTool",
    "CVSuggestionsAgentTool",
    "CVEditorAgentTool",
    "ShowResumeTool",
    "ListResumesTool",
    "GetResumeDetailTool",
    "GenerateResumeTool",
    "AskUserQuestionTool",
]

def __getattr__(name: str):
    """Load tools only when explicitly requested by a compatibility import."""

    target = _EXPORTS.get(name)
    if target is None:
        target = {
            "Bash": ("backend.agent.tool.bash", "Bash"),
            "PlanningTool": (
                "backend.agent.tool.planning",
                "PlanningTool",
            ),
            "StrReplaceEditor": (
                "backend.agent.tool.str_replace_editor",
                "StrReplaceEditor",
            ),
        }.get(name)
    if target is not None:
        module_name, attribute = target
        value = getattr(import_module(module_name), attribute)
        globals()[name] = value
        return value
    raise AttributeError(name)
