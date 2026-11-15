"""TOML loading shim (``tomllib`` on 3.11+, ``tomli`` on 3.10)."""
from __future__ import annotations

try:  # pragma: no cover - trivial import branch
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

loads = tomllib.loads


def load_path(path) -> dict:
    """Load a TOML document from ``path`` as a ``dict``."""
    return tomllib.loads(path.read_text(encoding="utf-8"))
