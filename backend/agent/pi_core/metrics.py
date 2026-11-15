"""Small in-process metrics registry for Pi Core rollout monitoring."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PiCoreSessionMetrics:
    session_id: str
    runs: int = 0
    completed_runs: int = 0
    failed_runs: int = 0
    stopped_runs: int = 0
    event_counts: dict[str, int] = field(default_factory=dict)
    tool_calls: int = 0
    tool_errors: int = 0
    approval_requests: int = 0
    user_waits: int = 0
    started_at: float = field(default_factory=time.time)
    last_event_at: float = field(default_factory=time.time)

    def record_event(self, event_kind: str) -> None:
        self.event_counts[event_kind] = self.event_counts.get(event_kind, 0) + 1
        self.last_event_at = time.time()
        if event_kind == "tool_execution_start":
            self.tool_calls += 1
        elif event_kind == "tool_execution_end":
            pass

    def record_tool_end(self, data: dict[str, Any]) -> None:
        if data.get("error"):
            self.tool_errors += 1
        structured = data.get("structured_content")
        if isinstance(structured, dict):
            event_type = structured.get("type")
            if event_type == "approval_request":
                self.approval_requests += 1
            elif event_type in {"ask_user_question", "user_wait"}:
                self.user_waits += 1


class PiCoreMetricsRegistry:
    """Bounded, thread-safe registry suitable for local rollout diagnostics."""

    def __init__(self, max_sessions: int = 1024) -> None:
        self._max_sessions = max_sessions
        self._lock = threading.RLock()
        self._sessions: OrderedDict[str, PiCoreSessionMetrics] = OrderedDict()

    def start_run(self, session_id: str) -> PiCoreSessionMetrics:
        with self._lock:
            metrics = self._sessions.get(session_id)
            if metrics is None:
                metrics = PiCoreSessionMetrics(session_id=session_id)
                self._sessions[session_id] = metrics
            else:
                self._sessions.move_to_end(session_id)
            metrics.runs += 1
            self._trim()
            return metrics

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            metrics = self._sessions.get(session_id)
            return asdict(metrics) if metrics else None

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {session_id: asdict(item) for session_id, item in self._sessions.items()}

    def reset(self) -> None:
        with self._lock:
            self._sessions.clear()

    def _trim(self) -> None:
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)


metrics_registry = PiCoreMetricsRegistry()


def get_pi_core_metrics(session_id: str | None = None) -> dict[str, Any]:
    """Return one session's counters or the full bounded registry snapshot."""

    if session_id:
        return metrics_registry.get(session_id) or {}
    return metrics_registry.snapshot()
