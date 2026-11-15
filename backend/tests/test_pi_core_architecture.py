from pathlib import Path


def test_production_runtime_has_no_retired_inheritance_chain():
    source = Path("backend/agent/pi_core/tool_runtime.py").read_text(encoding="utf-8")
    manus = Path("backend/agent/pi_core/resume_domain.py").read_text(encoding="utf-8")
    assert "class ToolCallAgent" not in source
    assert "class ReActAgent" not in source
    assert "class BaseAgent" not in source
    assert "class Manus(" not in manus
    assert not Path("backend/agent/agent/manus.py").exists()
    assert not Path("backend/agent/pi_core/legacy_turn.py").exists()
    assert "resume_compat" not in source
    assert "resume_compat" not in manus


def test_retired_optional_modules_are_removed():
    import importlib.util

    def module_exists(name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except ModuleNotFoundError:
            return False

    for module in (
        "backend.agent.tool.browser_use_tool",
        "backend.agent.tool.crawl4ai",
        "backend.agent.tool.computer_use_tool",
        "backend.agent.tool.web_search",
        "backend.agent.tool.search.google_search",
        "backend.agent.tool.search.duckduckgo_search",
        "backend.agent.tool.search.baidu_search",
        "backend.agent.tool.search.bing_search",
        "backend.agent.mcp.server",
        "backend.agent.daytona.sandbox",
        "backend.agent.sandbox.client",
    ):
        assert not module_exists(module)


def test_requirements_do_not_reintroduce_retired_dependencies():
    requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()
    for dependency in (
        "browser-use",
        "playwright",
        "crawl4ai",
        "browsergym",
        "googlesearch",
        "duckduckgo-search",
        "baidusearch",
        "daytona",
        "docker",
        "mcp",
    ):
        assert dependency not in requirements


def test_tool_execution_runtime_is_the_only_tool_runtime():
    from backend.agent.pi_core.tool_runtime import ToolExecutionRuntime
    from backend.agent.pi_core.resume_agent import ResumeAgentRuntime

    assert ToolExecutionRuntime.__name__ == "ToolExecutionRuntime"
    for retired_method in ("step", "think", "act", "run"):
        assert not hasattr(ToolExecutionRuntime, retired_method)
        assert not hasattr(ResumeAgentRuntime, retired_method)
