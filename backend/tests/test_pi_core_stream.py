import asyncio

from backend.agent.feature_flags import is_pi_core_enabled
from backend.agent.pi_core import AssistantChunk, ModelTurn, ToolCall, ToolResult
from backend.agent.pi_core import stream as pi_stream
from backend.agent.schema import Memory
from backend.agent.web.streaming.state_machine import AgentStateMachine


class _History:
    def __init__(self):
        self.items = []

    def add_message(self, message, persist=False):
        self.items.append(message)

    def _persist_if_needed(self):
        return None


class _FakeAgent:
    def __init__(self):
        self.memory = Memory()
        self.system_prompt = "system"
        self.available_tools = type("Tools", (), {"to_params": lambda self: []})()
        self.tool_choices = "auto"
        self.llm = object()
        self.prepared = False

    async def prepare_pi_core_turn(self, user_message):
        self.prepared = user_message == "hello"


def test_pi_core_stream_preserves_linear_event_order(monkeypatch):
    async def fake_model(_agent, _messages):
        yield AssistantChunk(kind="text_delta", content="你好")
        yield AssistantChunk(
            kind="done",
            turn=ModelTurn(content="你好", stop_reason="stop"),
        )

    async def fake_tool(_agent, _call, _messages):
        raise AssertionError("tool should not execute")

    monkeypatch.setattr(pi_stream, "stream_resume_model", fake_model)
    monkeypatch.setattr(pi_stream, "execute_resume_tool", fake_tool)

    agent = _FakeAgent()
    stream = pi_stream.PiCoreAgentStream(
        agent,
        "s1",
        AgentStateMachine("s1"),
        _History(),
    )
    async def collect():
        return [event async for event in stream.execute("hello")]

    events = asyncio.run(collect())

    assert [event.event_type.value for event in events] == [
        "agent_start",
        "answer",
        "answer",
        "agent_end",
    ]
    assert events[1].to_dict()["data"]["is_complete"] is False
    assert events[2].to_dict()["data"]["is_complete"] is True
    assert agent.prepared is True
    assert agent.memory.messages[-1].role == "assistant"


def test_pi_core_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("RESUME_AGENT_PI_CORE", raising=False)
    assert is_pi_core_enabled() is False
    monkeypatch.setenv("RESUME_AGENT_PI_CORE", "true")
    assert is_pi_core_enabled() is True


def test_pi_core_stream_emits_narration_before_tool_card(monkeypatch):
    calls = 0

    async def fake_model(_agent, _messages):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield AssistantChunk(kind="text_delta", content="我先读取简历")
            yield AssistantChunk(
                kind="done",
                turn=ModelTurn(
                    content="我先读取简历",
                    tool_calls=(
                        ToolCall(
                            id="call-1",
                            name="get_resume_detail",
                            arguments={"resume_id": "r1"},
                        ),
                    ),
                    stop_reason="tool_calls",
                ),
            )
            return
        yield AssistantChunk(kind="text_delta", content="读取完成")
        yield AssistantChunk(
            kind="done",
            turn=ModelTurn(content="读取完成", stop_reason="stop"),
        )

    async def fake_tool(_agent, _call, _messages):
        return ToolResult(output="简历内容")

    monkeypatch.setattr(pi_stream, "stream_resume_model", fake_model)
    monkeypatch.setattr(pi_stream, "execute_resume_tool", fake_tool)

    async def collect():
        agent = _FakeAgent()
        stream = pi_stream.PiCoreAgentStream(
            agent,
            "s1",
            AgentStateMachine("s1"),
            _History(),
        )
        return [event async for event in stream.execute("读取")]

    events = asyncio.run(collect())
    types = [event.event_type.value for event in events]
    assert types.index("thought") < types.index("tool_call")
    assert types.index("tool_call") < types.index("tool_result")
