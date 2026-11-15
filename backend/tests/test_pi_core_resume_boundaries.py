import asyncio

from backend.agent.pi_core.resume_coordinator import ResumeTurnCoordinator
from backend.agent.pi_core.resume_result_adapter import ResumeResultAdapter
from backend.agent.pi_core.turn_policy import TurnPolicySnapshot


def test_resume_turn_coordinator_owns_public_prompt_and_policy():
    class Compat:
        system_prompt = "system"
        next_step_prompt = "next"
        state = "FINISHED"

        async def prepare_pi_core_turn(self, user_input):
            self.user_input = user_input

        def get_turn_policy(self):
            return TurnPolicySnapshot(read_only=True)

        def get_tool_block_reason(self, tool_name):
            return "blocked" if tool_name == "cv_editor_agent" else None

    compat = Compat()
    coordinator = ResumeTurnCoordinator(lambda: compat)

    asyncio.run(coordinator.prepare("查看简历"))

    assert compat.user_input == "查看简历"
    assert coordinator.system_prompt == "system"
    assert coordinator.next_step_prompt == "next"
    assert coordinator.policy.read_only is True
    assert coordinator.block_reason("cv_editor_agent") == "blocked"
    assert coordinator.is_finished() is True


def test_resume_result_adapter_captures_and_consumes_once():
    values = {}
    adapter = ResumeResultAdapter(
        capture=lambda call_id, tool_name, result: values.__setitem__(
            call_id, {"type": tool_name, "result": result}
        ),
        consume=lambda call_id: values.pop(call_id, None),
    )

    adapter.capture("call-1", "cv_editor_agent", {"ok": True})

    assert adapter.consume("call-1") == {
        "type": "cv_editor_agent",
        "result": {"ok": True},
    }
    assert adapter.consume("call-1") is None
