def test_pi_core_metrics_registry_tracks_rollout_and_tool_errors():
    from backend.agent.pi_core.metrics import PiCoreMetricsRegistry

    registry = PiCoreMetricsRegistry(max_sessions=2)
    metrics = registry.start_run("session-1")
    metrics.record_event("message_end")
    metrics.record_event("tool_execution_start")
    metrics.record_event("tool_execution_end")
    metrics.record_tool_end(
        {
            "error": "tool failed",
            "structured_content": {"type": "approval_request"},
        }
    )
    metrics.failed_runs += 1

    snapshot = registry.get("session-1")
    assert snapshot is not None
    assert snapshot["runs"] == 1
    assert snapshot["event_counts"]["tool_execution_start"] == 1
    assert snapshot["tool_calls"] == 1
    assert snapshot["tool_errors"] == 1
    assert snapshot["approval_requests"] == 1


def test_pi_core_metrics_registry_is_bounded():
    from backend.agent.pi_core.metrics import PiCoreMetricsRegistry

    registry = PiCoreMetricsRegistry(max_sessions=2)
    registry.start_run("a")
    registry.start_run("b")
    registry.start_run("c")

    assert registry.get("a") is None
    assert set(registry.snapshot()) == {"b", "c"}
