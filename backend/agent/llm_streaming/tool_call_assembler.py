from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class _ToolCallState:
    index: int
    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class ToolCallAssembler:
    """Accumulate streamed tool_call deltas into stable OpenAI tool_calls payload."""

    _states: Dict[int, _ToolCallState] = field(default_factory=dict)

    def ingest(self, delta_tool_calls: Any) -> None:
        """Ingest one streamed delta.tool_calls chunk."""
        if not delta_tool_calls:
            return

        for item in delta_tool_calls:
            index = self._get_index(item)
            state = self._states.setdefault(index, _ToolCallState(index=index))

            call_id = self._get_attr(item, "id")
            if call_id:
                state.id = call_id

            function = self._get_attr(item, "function")
            if function is not None:
                name = self._get_attr(function, "name")
                if name:
                    state.name = name

                arguments = self._get_attr(function, "arguments")
                if arguments:
                    state.arguments += arguments

    def build(self) -> List[dict]:
        """Build normalized tool_calls list for ChatCompletionMessage."""
        results: List[dict] = []
        for index in sorted(self._states.keys()):
            state = self._states[index]
            if not (state.id or state.name or state.arguments):
                continue
            results.append(
                {
                    "id": state.id or f"call_{index}",
                    "type": "function",
                    "function": {
                        "name": state.name,
                        "arguments": state.arguments or "{}",
                    },
                }
            )
        return results

    def is_ready(self, finish_reason: str | None = None) -> bool:
        """Check whether accumulated tool calls are ready to be used."""
        if not self._states:
            return False

        # ``length`` means the provider stopped before the tool payload was
        # guaranteed complete.  The execution layer must treat it as a
        # truncated call and never run a potentially partial mutation.
        if finish_reason in {"tool_calls", "stop"}:
            return True

        for item in self.build():
            args = item.get("function", {}).get("arguments", "")
            if self._json_loads_ok(args):
                return True
        return False

    @staticmethod
    def _json_loads_ok(raw: str) -> bool:
        if not raw:
            return False
        try:
            json.loads(raw)
            return True
        except Exception:
            return False

    @staticmethod
    def _get_index(item: Any) -> int:
        idx = ToolCallAssembler._get_attr(item, "index")
        if isinstance(idx, int):
            return idx
        return 0

    @staticmethod
    def _get_attr(obj: Any, key: str) -> Any:
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)
