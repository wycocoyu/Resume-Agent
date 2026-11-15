"""Agent package exports.

The production agent is composition-based and lives in ``pi_core``.  Keep
this package import-light so route startup does not eagerly construct the
resume domain or model client.
"""

__all__ = ["ResumeAgentRuntime"]


def __getattr__(name: str):
    if name != "ResumeAgentRuntime":
        raise AttributeError(name)
    from backend.agent.pi_core.resume_agent import ResumeAgentRuntime

    globals()[name] = ResumeAgentRuntime
    return ResumeAgentRuntime
