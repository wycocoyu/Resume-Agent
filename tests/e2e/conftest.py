"""Root Conftest and Fixtures for CocoCV E2E Testing Suite (Zero-Mock Clean Architecture).

Provides isolated test environments, CLI execution helpers,
FastAPI TestClients, Chrome discovery, and state cleanup.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest

# 1. Dynamic root resolution - strictly isolated to this repository/worktree
WORKTREE_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = WORKTREE_ROOT / "backend"

# Ensure sys.path points strictly to WORKTREE_ROOT at index 0 and BACKEND_DIR at index 1
# Never remove site-packages from sys.path!
for p in list(sys.path):
    if not p:
        continue
    try:
        p_resolved = Path(p).resolve()
        if "site-packages" not in str(p) and "ResumeAgent" in str(p) and p_resolved not in (WORKTREE_ROOT, BACKEND_DIR):
            sys.path.remove(p)
    except Exception:
        pass

if str(WORKTREE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKTREE_ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(1, str(BACKEND_DIR))

# 2. Production startup environment isolation
os.environ.setdefault("LOGO_AUTO_SYNC_ON_STARTUP", "false")
os.environ.setdefault("LOG_MODE", "console")
os.environ.setdefault("LOG_LEVEL", "WARNING")

FIXTURES_DIR = (Path(__file__).parent / "fixtures").resolve()


@pytest.fixture(autouse=True)
def _reset_test_state():
    """Reset sse_starlette module-level event loop binding and global caches between tests."""
    try:
        from sse_starlette.sse import AppStatus
        AppStatus.should_exit = False
        AppStatus.should_exit_event = None
    except ImportError:
        pass
    try:
        from backend.latex_generator import _pdf_cache, _pdf_cache_order
        _pdf_cache.clear()
        _pdf_cache_order.clear()
    except Exception:
        pass
    yield
    try:
        from sse_starlette.sse import AppStatus
        AppStatus.should_exit = False
        AppStatus.should_exit_event = None
    except ImportError:
        pass
    try:
        from backend.latex_generator import _pdf_cache, _pdf_cache_order
        _pdf_cache.clear()
        _pdf_cache_order.clear()
    except Exception:
        pass


@pytest.fixture
def fixtures_dir() -> Path:
    """Return path to fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def temp_e2e_dir():
    """Provide an isolated temporary directory auto-cleaned after test."""
    temp_dir = tempfile.mkdtemp(prefix="cococv_e2e_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def standard_resume_data(fixtures_dir: Path) -> Dict[str, Any]:
    """Load standard realistic technical resume fixture."""
    path = fixtures_dir / "standard_resume.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def legacy_resume_data(fixtures_dir: Path) -> Dict[str, Any]:
    """Load legacy storage format v1 fixture."""
    path = fixtures_dir / "legacy_resume_v1.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def sample_jd_text(fixtures_dir: Path) -> str:
    """Load sample target JD text."""
    path = fixtures_dir / "target_jd_sample.txt"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def sample_cjk_text(fixtures_dir: Path) -> str:
    """Load sample CJK multilingual test text."""
    path = fixtures_dir / "cjk_sample_text.txt"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def bad_inputs_dir(fixtures_dir: Path) -> Path:
    """Return path to bad_inputs fixture directory."""
    return fixtures_dir / "bad_inputs"


@pytest.fixture
def chrome_executable() -> Optional[str]:
    """Discover available Google Chrome or Chromium executable."""
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chrome"),
    ]
    for c in candidates:
        if c and os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return None


@pytest.fixture
def run_cli():
    """Execute real production CLI commands (cococv, resume-agent, or python -m backend.cli)."""
    def _run(
        args: List[str],
        entrypoint: str = "module",
        cwd: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
    ):
        venv_bin = WORKTREE_ROOT / ".venv" / "bin"
        python_bin = str(venv_bin / "python") if (venv_bin / "python").exists() else sys.executable

        if entrypoint == "cococv" and (venv_bin / "cococv").exists():
            cmd = [str(venv_bin / "cococv")] + args
        elif entrypoint == "resume-agent" and (venv_bin / "resume-agent").exists():
            cmd = [str(venv_bin / "resume-agent")] + args
        elif entrypoint == "main":
            cmd = [python_bin, "-m", "backend.cli.main"] + args
        else:
            cmd = [python_bin, "-m", "backend.cli"] + args

        custom_env = os.environ.copy()
        custom_env["PYTHONPATH"] = f"{WORKTREE_ROOT}:{BACKEND_DIR}"
        if env:
            custom_env.update(env)

        proc = subprocess.run(
            cmd,
            cwd=str(cwd or WORKTREE_ROOT),
            capture_output=True,
            text=True,
            env=custom_env,
        )

        parsed_json = None
        if "--json" in args and proc.stdout.strip():
            try:
                parsed_json = json.loads(proc.stdout.strip())
            except json.JSONDecodeError:
                pass

        proc.json_data = parsed_json  # type: ignore[attr-defined]
        return proc

    return _run


@pytest.fixture
def e2e_client():
    """Provide real FastAPI TestClient for backend API routes."""
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app) as client:
        yield client
