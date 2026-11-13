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


_VALUE_TAKING_OPTIONS = frozenset(
    {
        "-o",
        "--output",
        "--title",
        "--template-dir",
        "--api-url",
        "--token",
        "--internal-secret",
        "--user-id",
        "--user-email",
        "--user-name",
        "--id",
        "--name",
        "--alias",
        "--offset",
        "--limit",
        "--harness",
        "--out",
        "--layout",
        "--scope",
        "--strategy",
        "--path",
    }
)


def has_json_flag(argv: Sequence[str]) -> bool:
    """Detect standalone --json flag before '--', ignoring values passed to value-taking options."""
    skip_next = False
    for token in argv:
        if skip_next:
            skip_next = False
            continue
        if token == "--":
            break
        if token in _VALUE_TAKING_OPTIONS:
            skip_next = True
            continue
        if token == "--json":
            return True
    return False


def emit_json(payload: dict[str, Any], *, stream: TextIO | None = None) -> None:
    """Write a single JSON object to the target stream."""
    out = stream if stream is not None else sys.stdout
    out.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    out.flush()
