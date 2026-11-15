"""Structured tool-result boundary for resume UI events.

Pi Core should never inspect a legacy agent's private result cache. This
adapter exposes one public capture/consume contract while preserving the
legacy implementation behind a small compatibility callback.
"""

from __future__ import annotations

from typing import Any, Callable, Optional


class ResumeResultAdapter:
    """Capture structured tool payloads and consume them exactly once."""

    def __init__(
        self,
        capture: Optional[Callable[[str, str, Any], None]] = None,
        consume: Optional[Callable[[str], dict[str, Any] | None]] = None,
    ) -> None:
        self._capture = capture
        self._consume = consume

    def capture(self, call_id: str, tool_name: str, result: Any) -> None:
        if self._capture is not None:
            self._capture(call_id, tool_name, result)

    def consume(self, call_id: str) -> dict[str, Any] | None:
        if self._consume is None:
            return None
        value = self._consume(call_id)
        return value if isinstance(value, dict) else None

