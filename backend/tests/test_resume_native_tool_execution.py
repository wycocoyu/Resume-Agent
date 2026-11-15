import asyncio


def test_native_resume_tool_execution_does_not_enter_legacy_step_loop():
    from backend.agent.pi_core.resume_tools import execute_resume_tool_native
    from backend.agent.pi_core.types import ToolCall
    from backend.agent.tool.base import BaseTool, ToolResult
    from backend.agent.tool.tool_collection import ToolCollection

    class EchoTool(BaseTool):
        name: str = "echo_resume"
        description: str = "echo"
        parameters: dict = {"type": "object"}

        async def execute(self, value: str = "") -> ToolResult:
            return ToolResult(
                output=value,
                structured_data={"type": "resume_patch", "patch_id": "p1"},
            )

    calls = []
    tools = ToolCollection(EchoTool())

    output = asyncio.run(
        execute_resume_tool_native(
            tools,
            ToolCall("call-1", "echo_resume", {"value": "ok"}),
            store_structured=lambda *args: calls.append(args),
        )
    )

    assert output == "Observed output of cmd `echo_resume` executed:\nok"
    assert calls[0][0] == "call-1"
    assert calls[0][1] == "echo_resume"
    assert calls[0][2].structured_data["patch_id"] == "p1"


def test_native_resume_tool_execution_turns_approval_into_structured_result():
    from backend.agent.pi_core.resume_tools import execute_resume_tool_native
    from backend.agent.pi_core.types import ToolCall
    from backend.agent.tool.base import BaseTool, ToolResult
    from backend.agent.tool.tool_collection import ToolCollection

    class ApprovalTool(BaseTool):
        name: str = "approval_resume"
        description: str = "approval"
        parameters: dict = {"type": "object"}
        requires_approval: bool = True
        approval_editable_fields: list = ["value"]

        async def execute(self, value: str = "") -> ToolResult:
            raise AssertionError("approval tool must not execute before approval")

    stored = []
    pending = []
    output = asyncio.run(
        execute_resume_tool_native(
            ToolCollection(ApprovalTool()),
            ToolCall("call-2", "approval_resume", {"value": "ok"}),
            session_id="native-approval",
            user_id="user-1",
            store_structured=lambda *args: stored.append(args),
            mark_pending_approval=lambda: pending.append(True),
        )
    )

    assert "确认卡" in output
    assert pending == [True]
    assert stored[0][2].structured_data["type"] == "approval_request"


def test_native_resume_tool_execution_forwards_tool_progress():
    from backend.agent.pi_core.resume_tools import execute_resume_tool_native
    from backend.agent.pi_core.types import ToolCall
    from backend.agent.tool.base import BaseTool, ToolProgress, ToolResult
    from backend.agent.tool.tool_collection import ToolCollection

    class ProgressTool(BaseTool):
        name: str = "progress_resume"
        description: str = "progress"
        parameters: dict = {"type": "object"}

        async def execute(self) -> ToolResult:
            await self.emit_progress(
                ToolProgress(
                    content="正在分析成果证据",
                    node_id="evidence",
                    current=2,
                    total=5,
                    label="成果证据",
                    stages=("结构完整度", "成果证据"),
                )
            )
            return ToolResult(output="done")

    progress = []
    output = asyncio.run(
        execute_resume_tool_native(
            ToolCollection(ProgressTool()),
            ToolCall("call-3", "progress_resume", {}),
            progress_sink=progress.append,
        )
    )

    assert output.endswith("done")
    assert progress[0].content == "正在分析成果证据"
    assert progress[0].current == 2
