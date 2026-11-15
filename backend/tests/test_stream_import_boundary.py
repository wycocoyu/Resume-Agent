from __future__ import annotations

import subprocess
import sys


def test_pi_core_stream_import_does_not_load_domain_runtime() -> None:
    """Normal stream imports must not eagerly load the domain runtime."""

    probe = (
        "import sys\n"
        "import backend.agent.web.streaming.agent_stream\n"
        "assert 'backend.agent.pi_core.resume_domain' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
