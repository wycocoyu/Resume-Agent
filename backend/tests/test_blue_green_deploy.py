"""Tests for Issue #108: readiness probe and PM2 + Nginx blue-green deployment."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

from fastapi.testclient import TestClient
import pytest

import backend.routes.health as health_route
from backend.main import app
import scripts.blue_green_deploy as bg


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_health_and_readiness_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    health_route._resolve_git_sha.cache_clear()
    monkeypatch.setenv("COCOCV_SLOT", "blue")
    monkeypatch.setenv("COCOCV_GIT_SHA", "deadbeef1234")

    client = TestClient(app)
    res_live = client.get("/api/health")
    assert res_live.status_code == 200
    assert res_live.json() == {
        "status": "ok",
        "slot": "blue",
        "commit": "deadbeef1234",
    }

    res_ready = client.get("/api/health/ready")
    assert res_ready.status_code == 200
    assert res_ready.json() == {
        "status": "ready",
        "slot": "blue",
        "commit": "deadbeef1234",
        "database": "ok",
    }
    health_route._resolve_git_sha.cache_clear()


def test_health_ready_returns_503_on_db_error(monkeypatch: pytest.MonkeyPatch) -> None:
    health_route._resolve_git_sha.cache_clear()
    monkeypatch.setenv("COCOCV_SLOT", "green")
    monkeypatch.setenv("COCOCV_GIT_SHA", "cafe0001")

    def _broken_session():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(health_route, "SessionLocal", _broken_session)

    client = TestClient(app)
    res = client.get("/api/health/ready")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "not_ready"
    assert body["database"] == "error"
    assert body["slot"] == "green"
    assert "db unavailable" in body["detail"]
    health_route._resolve_git_sha.cache_clear()


def test_choose_target_slot(tmp_path: Path) -> None:
    cfg = bg.DeployConfig(repo_dir=tmp_path)
    assert bg.choose_target_slot(None, cfg) == bg.SlotSpec("blue", 9001, "cococv-backend-blue")
    assert bg.choose_target_slot("legacy", cfg) == bg.SlotSpec("blue", 9001, "cococv-backend-blue")
    assert bg.choose_target_slot("green", cfg) == bg.SlotSpec("blue", 9001, "cococv-backend-blue")
    assert bg.choose_target_slot("blue", cfg) == bg.SlotSpec("green", 9002, "cococv-backend-green")


def test_swap_nginx_upstream_rolls_back_on_validation_failure(tmp_path: Path) -> None:
    upstream_file = tmp_path / "cococv-upstream.conf"
    original = bg.render_upstream_conf(port=9001, slot="blue")
    upstream_file.write_text(original, encoding="utf-8")

    seen_cmds: list[list[str]] = []

    def failing_runner(cmd: list[str], **kwargs):
        seen_cmds.append(cmd)
        if cmd == ["nginx", "-t"]:
            raise bg.DeployError("nginx config invalid")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with pytest.raises(bg.DeployError, match="reverted"):
        bg.swap_nginx_upstream(
            upstream_file,
            port=9002,
            slot="green",
            nginx_test_cmd=["nginx", "-t"],
            nginx_reload_cmd=["nginx", "-s", "reload"],
            runner=failing_runner,
        )

    assert upstream_file.read_text(encoding="utf-8") == original
    assert seen_cmds == [["nginx", "-t"]]


def test_frontend_migration_asset_merge_symlink_swap_and_prune(tmp_path: Path) -> None:
    frontend_dir = tmp_path / "frontend"
    dist_path = frontend_dir / "dist"
    releases_dir = frontend_dir / "dist_releases"

    # Legacy regular dist directory
    (dist_path / "assets").mkdir(parents=True)
    (dist_path / "index.html").write_text("legacy-html", encoding="utf-8")
    (dist_path / "assets" / "old-chunk.js").write_text("old-js", encoding="utf-8")
    (dist_path / "assets" / "shared.js").write_text("legacy-shared", encoding="utf-8")

    migrated = bg.migrate_legacy_dist_dir(dist_path, releases_dir)
    assert migrated is not None
    assert dist_path.is_symlink()
    assert dist_path.resolve() == migrated.resolve()

    # Build new release and preserve non-colliding legacy assets
    new_rel = releases_dir / "rel-2"
    (new_rel / "assets").mkdir(parents=True)
    (new_rel / "index.html").write_text("new-html", encoding="utf-8")
    (new_rel / "assets" / "shared.js").write_text("new-shared", encoding="utf-8")

    copied = bg.merge_previous_assets(migrated, new_rel)
    assert copied == 1
    assert (new_rel / "assets" / "old-chunk.js").read_text(encoding="utf-8") == "old-js"
    assert (new_rel / "assets" / "shared.js").read_text(encoding="utf-8") == "new-shared"

    prev = bg.atomic_swap_symlink(dist_path, new_rel)
    assert prev == migrated.resolve()
    assert dist_path.resolve() == new_rel.resolve()
    assert (dist_path / "index.html").read_text(encoding="utf-8") == "new-html"

    # Prune extra releases while protecting active + previous
    extra_old = releases_dir / "rel-0"
    extra_old.mkdir()
    os.utime(extra_old, (1000, 1000))
    os.utime(migrated, (2000, 2000))
    os.utime(new_rel, (3000, 3000))

    removed = bg.prune_old_releases(releases_dir, keep=1, protected={migrated, new_rel})
    assert removed == [extra_old]
    assert migrated.exists()
    assert new_rel.exists()


def test_acquire_deploy_lock_prevents_concurrent_runs(tmp_path: Path) -> None:
    lock_file = tmp_path / ".deploy" / "deploy.lock"
    with bg.acquire_deploy_lock(lock_file):
        with pytest.raises(bg.DeployError, match="already running"):
            with bg.acquire_deploy_lock(lock_file):
                pass


def test_live_dual_uvicorn_deploy_and_rollback(tmp_path: Path) -> None:
    """Spin up real uvicorn processes on blue/green ports and verify deploy + rollback."""
    repo_root = Path(__file__).resolve().parents[2]
    blue_port = _free_port()
    green_port = _free_port()

    work_frontend = tmp_path / "frontend"
    (work_frontend / "dist" / "assets").mkdir(parents=True)
    (work_frontend / "dist" / "index.html").write_text("v0", encoding="utf-8")
    (work_frontend / "dist" / "assets" / "chunk-v0.js").write_text("v0", encoding="utf-8")

    upstream_file = tmp_path / "nginx" / "cococv-upstream.conf"
    state_file = tmp_path / ".deploy" / "blue_green_state.json"

    cfg = bg.DeployConfig(
        repo_dir=repo_root,
        blue_port=blue_port,
        green_port=green_port,
        upstream_file=upstream_file,
        state_file=state_file,
        drain_seconds=0.0,
        health_timeout=20.0,
        workers=1,
        python_bin=Path(sys.executable),
        skip_git=True,
        skip_deps=True,
        skip_build=True,
    )
    # Redirect frontend paths inside tmp_path so we never touch repo frontend/
    cfg.repo_dir = tmp_path
    # Keep subprocess cwd at real repo_root so `backend.main:app` imports cleanly
    real_head = bg._git_short_head(repo_root)

    # Create minimal git repo or monkeypatch _git_short_head for tmp_path
    procs: dict[str, subprocess.Popen[str]] = {}
    commands_seen: list[list[str]] = []

    def fake_runner(cmd: list[str], **kwargs):
        commands_seen.append(cmd)
        if cmd[:2] == ["pm2", "delete"]:
            app_name = cmd[2]
            proc = procs.pop(app_name, None)
            if proc and proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        if cmd[:2] == ["pm2", "start"]:
            app_name = cmd[cmd.index("--name") + 1]
            if "--" in cmd:
                uv_args = cmd[cmd.index("--") + 1 :]
                uv_cmd = [sys.executable, *uv_args]
                env = dict(kwargs.get("env") or os.environ)
                env["COCOCV_GIT_SHA"] = real_head
                procs[app_name] = subprocess.Popen(
                    uv_cmd,
                    cwd=str(repo_root),
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
            else:
                # Restarting an existing slot in rollback test
                slot = "blue" if "blue" in app_name else "green"
                port = blue_port if slot == "blue" else green_port
                env = dict(os.environ)
                env["COCOCV_SLOT"] = slot
                env["COCOCV_GIT_SHA"] = real_head
                procs[app_name] = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "backend.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--workers",
                        "1",
                    ],
                    cwd=str(repo_root),
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        if cmd[:2] == ["pm2", "stop"]:
            app_name = cmd[2]
            proc = procs.pop(app_name, None)
            if proc and proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        if cmd[:2] == ["pm2", "jlist"]:
            items = [
                {"name": name, "pm2_env": {"status": "online" if p.poll() is None else "stopped"}}
                for name, p in procs.items()
            ]
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(items), stderr="")

        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    original_git_head = bg._git_short_head
    bg._git_short_head = lambda _p: real_head
    try:
        # 1st deploy -> blue slot
        state1 = bg.deploy(cfg, runner=fake_runner)
        assert state1["active_slot"] == "blue"
        assert state1["active_port"] == blue_port
        assert f"127.0.0.1:{blue_port}" in upstream_file.read_text(encoding="utf-8")

        # 2nd deploy -> green slot while blue is still alive until drain
        state2 = bg.deploy(cfg, runner=fake_runner)
        assert state2["active_slot"] == "green"
        assert state2["active_port"] == green_port
        assert state2["previous_slot"] == "blue"
        assert f"127.0.0.1:{green_port}" in upstream_file.read_text(encoding="utf-8")

        # Confirm green /api/health/ready responds directly
        with urllib.request.urlopen(f"http://127.0.0.1:{green_port}/api/health/ready", timeout=3.0) as resp:
            ready_json = json.loads(resp.read().decode("utf-8"))
            assert ready_json["status"] == "ready"
            assert ready_json["slot"] == "green"
            assert ready_json["commit"] == real_head

        # Rollback -> returns to blue slot
        rolled = bg.rollback(cfg, runner=fake_runner)
        assert rolled["active_slot"] == "blue"
        assert rolled["active_port"] == blue_port
        assert f"127.0.0.1:{blue_port}" in upstream_file.read_text(encoding="utf-8")

        with urllib.request.urlopen(f"http://127.0.0.1:{blue_port}/api/health/ready", timeout=3.0) as resp:
            ready_json = json.loads(resp.read().decode("utf-8"))
            assert ready_json["status"] == "ready"
            assert ready_json["slot"] == "blue"
    finally:
        bg._git_short_head = original_git_head
        for proc in procs.values():
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()


def test_deploy_aborts_before_cutover_when_standby_unhealthy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    upstream_file = tmp_path / "nginx" / "cococv-upstream.conf"
    original_upstream = bg.render_upstream_conf(port=9001, slot="blue")
    upstream_file.parent.mkdir(parents=True, exist_ok=True)
    upstream_file.write_text(original_upstream, encoding="utf-8")

    state_file = tmp_path / ".deploy" / "blue_green_state.json"
    bg.save_state(
        state_file,
        {
            "active_slot": "blue",
            "active_port": 9001,
            "active_app": "cococv-backend-blue",
            "active_commit": "11111111",
        },
    )

    stopped_apps: list[str] = []

    def fake_runner(cmd: list[str], **kwargs):
        if cmd[:2] == ["pm2", "stop"]:
            stopped_apps.append(cmd[2])
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(bg, "_git_short_head", lambda _p: "22222222")
    cfg = bg.DeployConfig(
        repo_dir=tmp_path,
        blue_port=_free_port(),
        green_port=_free_port(),
        upstream_file=upstream_file,
        state_file=state_file,
        drain_seconds=0.0,
        health_timeout=0.3,
        python_bin=Path(sys.executable),
        skip_git=True,
        skip_deps=True,
        skip_build=True,
    )

    with pytest.raises(bg.DeployError, match="Readiness check timed out"):
        bg.deploy(cfg, runner=fake_runner)

    # Live upstream & active state remain untouched; failed green standby was stopped
    assert upstream_file.read_text(encoding="utf-8") == original_upstream
    assert bg.load_state(state_file)["active_slot"] == "blue"
    assert stopped_apps == ["cococv-backend-green"]


def test_shell_wrapper_status_and_dry_run(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    wrapper = repo_root / "scripts" / "deploy-blue-green.sh"
    state_file = tmp_path / "state.json"
    upstream_file = tmp_path / "upstream.conf"

    res_status = subprocess.run(
        [str(wrapper), "status", "--repo-dir", str(repo_root), "--state-file", str(state_file), "--upstream-file", str(upstream_file)],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=True,
    )
    status_json = json.loads(res_status.stdout)
    assert status_json["repo_dir"] == str(repo_root.resolve())
    assert status_json["state"] == {}

    res_dry = subprocess.run(
        [str(wrapper), "deploy", "--dry-run", "--repo-dir", str(repo_root), "--state-file", str(state_file), "--upstream-file", str(upstream_file)],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=True,
    )
    dry_json = json.loads(res_dry.stdout)
    assert dry_json["dry_run"] is True
    assert dry_json["target_slot"] == "blue"
    assert dry_json["target_port"] == 9001


def test_pm2_command_includes_venv_path_and_memory_limit(tmp_path: Path) -> None:
    captured: list[tuple[list[str], dict[str, str] | None]] = []

    def rec_runner(cmd: list[str], **kwargs):
        captured.append((cmd, kwargs.get("env")))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    py_bin = tmp_path / "venv" / "bin" / "python"
    cfg = bg.DeployConfig(repo_dir=tmp_path, python_bin=py_bin)
    bg._pm2_start_slot(cfg, cfg.slot_spec("blue"), "abc12345", runner=rec_runner)

    start_cmd, start_env = captured[-1]
    assert "--max-memory-restart" in start_cmd
    assert "1G" in start_cmd
    assert "--update-env" in start_cmd
    assert start_env is not None
    assert start_env["COCOCV_SLOT"] == "blue"
    assert start_env["COCOCV_GIT_SHA"] == "abc12345"
    assert start_env["PATH"].startswith(str(py_bin.parent))
