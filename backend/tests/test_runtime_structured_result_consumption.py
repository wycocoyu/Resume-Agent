import asyncio

from backend.agent.pi_core.resume_agent import ResumeAgentRuntime
from backend.agent.pi_core.types import ToolCall


def test_runtime_consumes_structured_result_from_native_boundary(monkeypatch):
    runtime = ResumeAgentRuntime(session_id="structured-consume")
    tool_type = type(runtime.available_tools.tool_map["get_resume_detail"])

    async def fake_execute(self, **kwargs):
        return {"type": "resume_patch", "patch_id": "p1"}

    monkeypatch.setattr(tool_type, "execute", fake_execute)
    result = asyncio.run(
        runtime.execute_tool(
            ToolCall("call-1", "get_resume_detail", {"path": "basic"})
        )
    )
    assert isinstance(result.structured_content, dict)
