import asyncio
from types import SimpleNamespace

from backend.agent.pi_core.resume_agent import ResumeAgentRuntime
from backend.agent.pi_core.types import ToolCall


def test_runtime_is_lazy_composition_facade():
    runtime = ResumeAgentRuntime(session_id="s1", is_admin=True, user_id="u1")
    assert runtime._domain is None
    assert runtime.memory.messages == []
    assert "cv_reader_agent" in runtime.available_tools.tool_map
    assert runtime._domain is None


def test_runtime_prepares_turn_and_model_policy():
    runtime = ResumeAgentRuntime(session_id="prepare")
    asyncio.run(runtime.prepare_turn("优化项目经历"))
    assert runtime.get_system_prompt()

    llm = SimpleNamespace(model="deepseek-chat", extra_body={})
    runtime = ResumeAgentRuntime(session_id="policy", llm=llm)
    messages = [object()]
    assert asyncio.run(runtime.prepare_model_request(messages)) is messages
    assert llm.extra_body["thinking"] == {"type": "disabled"}


def test_runtime_prepares_domain_once_per_turn(monkeypatch):
    runtime = ResumeAgentRuntime(session_id="prepare-once")
    domain = runtime.domain_agent
    calls = 0
    original = domain.prepare_pi_core_turn

    async def counted(user_input):
        nonlocal calls
        calls += 1
        await original(user_input)

    monkeypatch.setattr(domain, "prepare_pi_core_turn", counted)
    asyncio.run(runtime.prepare_turn("优化项目经历"))

    assert calls == 1


def test_runtime_stream_model_response_uses_provider_boundary():
    calls = []

    class FakeLLM:
        model = "deepseek-chat"

        async def stream_tool_response(self, **kwargs):
            calls.append(kwargs)
            from backend.agent.pi_core.types import AssistantChunk, ModelTurn

            yield AssistantChunk(kind="text_delta", content="你好")
            yield AssistantChunk(kind="done", turn=ModelTurn(content="你好"))

    runtime = ResumeAgentRuntime(session_id="model", llm=FakeLLM())

    async def collect():
        return [chunk async for chunk in runtime.stream_model_response([])]

    chunks = asyncio.run(collect())
    assert [chunk.kind for chunk in chunks] == ["text_delta", "done"]
    assert calls and calls[0]["tools"]


def test_runtime_tool_boundary_returns_native_output(monkeypatch):
    runtime = ResumeAgentRuntime(session_id="tool")
    tool_type = type(runtime.available_tools.tool_map["get_resume_detail"])

    async def fake_execute(self, **kwargs):
        return {"ok": True}

    monkeypatch.setattr(tool_type, "execute", fake_execute)
    result = asyncio.run(
        runtime.execute_tool(
            ToolCall("call-1", "get_resume_detail", {"path": "basic"})
        )
    )
    assert result.output
    assert isinstance(result.structured_content, dict)


def test_runtime_policy_boundary_is_public():
    runtime = ResumeAgentRuntime(session_id="policy-boundary")
    asyncio.run(runtime.prepare_turn("帮我诊断一下简历"))
    assert runtime.tool_block_reason("cv_editor_agent")
