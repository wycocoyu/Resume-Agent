"""CLI exception types and machine-readable JSON output utilities."""
from __future__ import annotations

import json
import sys
from typing import Any, Sequence, TextIO


class CLIError(Exception):
    """Expected operational/business error that maps to exit code 1."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "cli_error",
        exit_code: int = 1,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.exit_code = exit_code
        self.extra = dict(extra or {})


def has_json_flag(argv: Sequence[str]) -> bool:
    """Detect --json anywhere before end-of-options '--'."""
    for token in argv:
        if token == "--":
            break
        if token == "--json":
            return True
    return False


def emit_json(payload: dict[str, Any], *, stream: TextIO | None = None) -> None:
    """Write a single JSON object to the target stream."""
    out = stream if stream is not None else sys.stdout
    out.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    out.flush()
