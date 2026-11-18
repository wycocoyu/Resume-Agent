#!/usr/bin/env python3
"""Host PM2 + Nginx zero-downtime blue-green deployment and rollback CLI for CocoCV."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Iterator
import urllib.error
import urllib.request


class DeployError(RuntimeError):
    """Raised when a blue-green deployment or rollback step fails."""


@dataclass(frozen=True)
class SlotSpec:
    name: str
    port: int
    app_name: str


@dataclass
class DeployConfig:
    repo_dir: Path
    blue_port: int = 9001
    green_port: int = 9002
    legacy_port: int = 9000
    blue_app: str = "cococv-backend-blue"
    green_app: str = "cococv-backend-green"
    legacy_app: str = "resume-backend"
    bind_host: str = "127.0.0.1"
    upstream_file: Path = Path("/etc/nginx/conf.d/cococv-upstream.conf")
    state_file: Path | None = None
    drain_seconds: float = 15.0
    health_timeout: float = 45.0
    keep_releases: int = 5
    workers: int = 2
    python_bin: Path | None = None
    nginx_test_cmd: list[str] = field(default_factory=lambda: ["nginx", "-t"])
    nginx_reload_cmd: list[str] = field(default_factory=lambda: ["nginx", "-s", "reload"])
    skip_git: bool = False
    skip_deps: bool = False
    skip_build: bool = False
    keep_standby: bool = False
    dry_run: bool = False

    def __post_init__(self) -> None:
        self.repo_dir = self.repo_dir.resolve()
        if self.state_file is None:
            self.state_file = self.repo_dir / ".deploy" / "blue_green_state.json"
        if self.python_bin is None:
            self.python_bin = _detect_python_bin(self.repo_dir)

    @property
    def lock_file(self) -> Path:
        assert self.state_file is not None
        return self.state_file.parent / "deploy.lock"

    @property
    def frontend_dir(self) -> Path:
        return self.repo_dir / "frontend"

    @property
    def releases_dir(self) -> Path:
        return self.frontend_dir / "dist_releases"

    @property
    def dist_path(self) -> Path:
        return self.frontend_dir / "dist"

    def slot_spec(self, slot: str) -> SlotSpec:
        if slot == "blue":
            return SlotSpec(name="blue", port=self.blue_port, app_name=self.blue_app)
        if slot == "green":
            return SlotSpec(name="green", port=self.green_port, app_name=self.green_app)
        raise DeployError(f"Unsupported slot: {slot!r}")


def _detect_python_bin(repo_dir: Path) -> Path:
    for candidate in (
        repo_dir / "venv" / "bin" / "python",
        repo_dir / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _release_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _run_cmd(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        capture_output=capture_output,
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise DeployError(
            f"Command failed (exit={proc.returncode}): {' '.join(shlex.quote(c) for c in cmd)}"
            + (f"\n{detail}" if detail else "")
        )
    return proc


@contextmanager
def acquire_deploy_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DeployError(f"Another deployment is already running (lock: {lock_path})") from exc
        try:
            fh.write(f"{os.getpid()}\n")
            fh.flush()
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def load_state(state_file: Path) -> dict[str, Any]:
    if not state_file.exists():
        return {}
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        raise DeployError(f"Corrupted state file {state_file}: {exc}") from exc


def save_state(state_file: Path, state: dict[str, Any]) -> None:
    atomic_write_text(state_file, json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def choose_target_slot(active_slot: str | None, config: DeployConfig) -> SlotSpec:
    if active_slot == "blue":
        return config.slot_spec("green")
    return config.slot_spec("blue")


def render_upstream_conf(port: int, slot: str, host: str = "127.0.0.1") -> str:
    return (
        f"# Managed by scripts/deploy-blue-green.sh (active_slot={slot})\n"
        "upstream cococv_backend {\n"
        f"    server {host}:{port};\n"
        "    keepalive 32;\n"
        "}\n"
    )


def swap_nginx_upstream(
    upstream_file: Path,
    *,
    port: int,
    slot: str,
    host: str = "127.0.0.1",
    nginx_test_cmd: list[str],
    nginx_reload_cmd: list[str],
    runner: Callable[..., subprocess.CompletedProcess[str]] = _run_cmd,
) -> None:
    existed = upstream_file.exists()
    prev_content = upstream_file.read_text(encoding="utf-8") if existed else None
    new_content = render_upstream_conf(port=port, slot=slot, host=host)

    atomic_write_text(upstream_file, new_content)
    try:
        runner(nginx_test_cmd, check=True)
        runner(nginx_reload_cmd, check=True)
    except Exception as exc:
        # Roll back upstream file immediately if nginx -t or reload fails
        if prev_content is not None:
            atomic_write_text(upstream_file, prev_content)
        else:
            upstream_file.unlink(missing_ok=True)
        raise DeployError(f"Nginx upstream cutover failed and was reverted: {exc}") from exc


def migrate_legacy_dist_dir(dist_path: Path, releases_dir: Path) -> Path | None:
    """If frontend/dist is a regular directory, move it into dist_releases and symlink to it."""
    if not dist_path.exists() and not dist_path.is_symlink():
        return None
    if dist_path.is_symlink():
        try:
            return dist_path.resolve()
        except OSError:
            return None

    releases_dir.mkdir(parents=True, exist_ok=True)
    migrated = releases_dir / f"legacy-{_release_stamp()}"
    shutil.move(str(dist_path), str(migrated))
    atomic_swap_symlink(dist_path, migrated)
    return migrated


def atomic_swap_symlink(link_path: Path, target_dir: Path) -> Path | None:
    if not target_dir.exists():
        raise DeployError(f"Target release directory does not exist: {target_dir}")
    if link_path.exists() and not link_path.is_symlink():
        raise DeployError(f"Refusing to overwrite non-symlink directory: {link_path}")

    previous_target: Path | None = None
    if link_path.is_symlink():
        try:
            previous_target = link_path.resolve()
        except OSError:
            previous_target = None

    link_path.parent.mkdir(parents=True, exist_ok=True)
    rel_target: Path | str
    try:
        rel_target = target_dir.resolve().relative_to(link_path.parent.resolve())
    except ValueError:
        rel_target = target_dir.resolve()

    tmp_link = link_path.parent / f".{link_path.name}.next.{os.getpid()}"
    tmp_link.unlink(missing_ok=True)
    os.symlink(str(rel_target), str(tmp_link))
    try:
        os.replace(tmp_link, link_path)
    except Exception:
        tmp_link.unlink(missing_ok=True)
        raise
    return previous_target


def merge_previous_assets(prev_release: Path | None, new_release: Path) -> int:
    """Preserve non-colliding hashed assets from the previous release so open tabs avoid 404s."""
    if prev_release is None or not prev_release.exists():
        return 0
    prev_assets = prev_release / "assets"
    if not prev_assets.is_dir():
        return 0
    new_assets = new_release / "assets"
    new_assets.mkdir(parents=True, exist_ok=True)

    copied = 0
    for item in prev_assets.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(prev_assets)
        dest = new_assets / rel
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
            copied += 1
    return copied


def prune_old_releases(releases_dir: Path, keep: int, protected: set[Path]) -> list[Path]:
    if keep < 1 or not releases_dir.exists():
        return []
    resolved_protected = {p.resolve() for p in protected if p is not None}
    dirs = [p for p in releases_dir.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    removed: list[Path] = []
    for candidate in dirs[keep:]:
        if candidate.resolve() in resolved_protected:
            continue
        shutil.rmtree(candidate, ignore_errors=True)
        removed.append(candidate)
    return removed


def wait_for_healthy(
    base_url: str,
    *,
    expected_commit: str | None = None,
    expected_slot: str | None = None,
    timeout_s: float = 45.0,
    interval_s: float = 0.5,
) -> dict[str, Any]:
    probe_url = f"{base_url.rstrip('/')}/api/health/ready"
    deadline = time.monotonic() + timeout_s
    last_error = "no probe executed"

    while True:
        try:
            req = urllib.request.Request(probe_url, method="GET")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                if resp.status != 200 or data.get("status") != "ready":
                    last_error = f"unexpected payload status={resp.status} body={data}"
                elif expected_slot and data.get("slot") != expected_slot:
                    last_error = f"slot mismatch: expected={expected_slot} got={data.get('slot')}"
                elif (
                    expected_commit
                    and expected_commit != "unknown"
                    and not str(data.get("commit", "")).startswith(expected_commit[:7])
                ):
                    last_error = f"commit mismatch: expected={expected_commit} got={data.get('commit')}"
                else:
                    return data
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_error = str(exc)

        if time.monotonic() >= deadline:
            raise DeployError(f"Readiness check timed out for {probe_url}: {last_error}")
        time.sleep(interval_s)


def _git_short_head(repo_dir: Path) -> str:
    proc = _run_cmd(["git", "rev-parse", "--short=8", "HEAD"], cwd=repo_dir)
    return proc.stdout.strip()


def _pm2_is_online(app_name: str, runner: Callable[..., subprocess.CompletedProcess[str]] = _run_cmd) -> bool:
    proc = runner(["pm2", "jlist"], check=False)
    if proc.returncode != 0 or not proc.stdout.strip():
        return False
    try:
        items = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return False
    for item in items:
        if item.get("name") == app_name:
            status = (item.get("pm2_env") or {}).get("status")
            return status == "online"
    return False


def _pm2_start_slot(
    config: DeployConfig,
    slot: SlotSpec,
    commit: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] = _run_cmd,
) -> None:
    runner(["pm2", "delete", slot.app_name], check=False)
    env = dict(os.environ)
    env["COCOCV_SLOT"] = slot.name
    env["COCOCV_GIT_SHA"] = commit
    env["PORT"] = str(slot.port)

    assert config.python_bin is not None
    cmd = [
        "pm2",
        "start",
        str(config.python_bin),
        "--name",
        slot.app_name,
        "--cwd",
        str(config.repo_dir),
        "--update-env",
        "--",
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        config.bind_host,
        "--port",
        str(slot.port),
        "--workers",
        str(config.workers),
    ]
    runner(cmd, cwd=config.repo_dir, env=env, check=True)


def _pm2_stop_app(app_name: str, runner: Callable[..., subprocess.CompletedProcess[str]] = _run_cmd) -> None:
    runner(["pm2", "stop", app_name], check=False)


def _build_frontend_release(
    config: DeployConfig,
    release_dir: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]] = _run_cmd,
) -> None:
    release_dir.parent.mkdir(parents=True, exist_ok=True)
    build_env = dict(os.environ)
    build_env.setdefault("NODE_OPTIONS", "--max-old-space-size=2560")
    runner(["npm", "ci", "--no-audit", "--no-fund"], cwd=config.frontend_dir, env=build_env, check=True)
    runner(
        ["npm", "run", "build", "--", "--outDir", str(release_dir)],
        cwd=config.frontend_dir,
        env=build_env,
        check=True,
    )


def deploy(config: DeployConfig, runner: Callable[..., subprocess.CompletedProcess[str]] = _run_cmd) -> dict[str, Any]:
    assert config.state_file is not None
    state = load_state(config.state_file)
    active_slot_name = state.get("active_slot")
    target_slot = choose_target_slot(active_slot_name, config)

    if config.dry_run:
        plan = {
            "action": "deploy",
            "dry_run": True,
            "current_slot": active_slot_name or "legacy",
            "target_slot": target_slot.name,
            "target_port": target_slot.port,
            "target_app": target_slot.app_name,
            "upstream_file": str(config.upstream_file),
            "drain_seconds": config.drain_seconds,
        }
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return plan

    with acquire_deploy_lock(config.lock_file):
        if not config.skip_git:
            runner(["git", "fetch", "origin", "main"], cwd=config.repo_dir, check=True)
            runner(["git", "reset", "--hard", "origin/main"], cwd=config.repo_dir, check=True)

        target_commit = _git_short_head(config.repo_dir)
        assert config.python_bin is not None
        if not config.skip_deps:
            pip_bin = config.python_bin.parent / "pip"
            if pip_bin.exists():
                runner([str(pip_bin), "install", "-r", "requirements.txt"], cwd=config.repo_dir, check=True)
            else:
                runner(
                    [str(config.python_bin), "-m", "pip", "install", "-r", "requirements.txt"],
                    cwd=config.repo_dir,
                    check=True,
                )

        prev_release = migrate_legacy_dist_dir(config.dist_path, config.releases_dir)
        new_release: Path | None = None
        if not config.skip_build:
            new_release = config.releases_dir / f"{target_commit}-{_release_stamp()}"
            _build_frontend_release(config, new_release, runner=runner)
            merge_previous_assets(prev_release, new_release)

        # Start standby slot and verify readiness before switching any live traffic
        _pm2_start_slot(config, target_slot, target_commit, runner=runner)
        try:
            health_payload = wait_for_healthy(
                f"http://{config.bind_host}:{target_slot.port}",
                expected_commit=target_commit,
                expected_slot=target_slot.name,
                timeout_s=config.health_timeout,
            )
        except Exception:
            _pm2_stop_app(target_slot.app_name, runner=runner)
            raise

        swapped_frontend = False
        try:
            if new_release is not None:
                atomic_swap_symlink(config.dist_path, new_release)
                swapped_frontend = True

            swap_nginx_upstream(
                config.upstream_file,
                port=target_slot.port,
                slot=target_slot.name,
                host=config.bind_host,
                nginx_test_cmd=config.nginx_test_cmd,
                nginx_reload_cmd=config.nginx_reload_cmd,
                runner=runner,
            )
        except Exception:
            if swapped_frontend and prev_release is not None and prev_release.exists():
                atomic_swap_symlink(config.dist_path, prev_release)
            _pm2_stop_app(target_slot.app_name, runner=runner)
            raise

        prev_slot = state.get("active_slot")
        prev_port = state.get("active_port") or (config.legacy_port if prev_slot is None else None)
        prev_app = state.get("active_app") or (config.legacy_app if prev_slot is None else None)
        prev_commit = state.get("active_commit")
        active_release_str = str(new_release) if new_release is not None else (str(prev_release) if prev_release else None)

        new_state = {
            "active_slot": target_slot.name,
            "active_port": target_slot.port,
            "active_app": target_slot.app_name,
            "active_commit": target_commit,
            "active_release": active_release_str,
            "previous_slot": prev_slot or "legacy",
            "previous_port": prev_port,
            "previous_app": prev_app,
            "previous_commit": prev_commit,
            "previous_release": str(prev_release) if prev_release else None,
            "health": health_payload,
            "updated_at": _utc_now(),
        }
        save_state(config.state_file, new_state)

        if not config.keep_standby and prev_app and prev_app != target_slot.app_name:
            if config.drain_seconds > 0:
                time.sleep(config.drain_seconds)
            _pm2_stop_app(prev_app, runner=runner)

        protected = {
            Path(p)
            for p in (new_state.get("active_release"), new_state.get("previous_release"))
            if p
        }
        prune_old_releases(config.releases_dir, config.keep_releases, protected)

        print(json.dumps(new_state, indent=2, ensure_ascii=False))
        return new_state


def rollback(config: DeployConfig, runner: Callable[..., subprocess.CompletedProcess[str]] = _run_cmd) -> dict[str, Any]:
    assert config.state_file is not None
    state = load_state(config.state_file)
    prev_slot = state.get("previous_slot")
    prev_port = state.get("previous_port")
    prev_app = state.get("previous_app")
    prev_commit = state.get("previous_commit")
    prev_release = Path(state["previous_release"]) if state.get("previous_release") else None

    if not prev_slot or not prev_port or not prev_app:
        raise DeployError("No previous deployment state recorded; cannot rollback automatically.")

    if config.dry_run:
        plan = {
            "action": "rollback",
            "dry_run": True,
            "from_slot": state.get("active_slot"),
            "to_slot": prev_slot,
            "to_port": prev_port,
            "to_app": prev_app,
            "to_commit": prev_commit,
            "to_release": str(prev_release) if prev_release else None,
        }
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return plan

    with acquire_deploy_lock(config.lock_file):
        # If previous backend was already drained/stopped, check out previous commit and warm it up
        if not _pm2_is_online(prev_app, runner=runner):
            if prev_commit and not config.skip_git and prev_slot in {"blue", "green"}:
                current_head = _git_short_head(config.repo_dir)
                if not current_head.startswith(prev_commit[:7]):
                    runner(["git", "checkout", "--detach", prev_commit], cwd=config.repo_dir, check=True)
            if prev_slot in {"blue", "green"}:
                slot_spec = config.slot_spec(prev_slot)
                _pm2_start_slot(config, slot_spec, prev_commit or "unknown", runner=runner)
            else:
                runner(["pm2", "start", prev_app], cwd=config.repo_dir, check=True)

        expected_commit = None if config.skip_git else (prev_commit if prev_slot in {"blue", "green"} else None)
        health_payload = wait_for_healthy(
            f"http://{config.bind_host}:{prev_port}",
            expected_commit=expected_commit,
            expected_slot=prev_slot if prev_slot in {"blue", "green"} else None,
            timeout_s=config.health_timeout,
        )

        current_dist = config.dist_path.resolve() if config.dist_path.is_symlink() else None
        if prev_release is not None and prev_release.exists():
            atomic_swap_symlink(config.dist_path, prev_release)

        try:
            swap_nginx_upstream(
                config.upstream_file,
                port=int(prev_port),
                slot=str(prev_slot),
                host=config.bind_host,
                nginx_test_cmd=config.nginx_test_cmd,
                nginx_reload_cmd=config.nginx_reload_cmd,
                runner=runner,
            )
        except Exception:
            if current_dist is not None and current_dist.exists():
                atomic_swap_symlink(config.dist_path, current_dist)
            raise

        old_active_app = state.get("active_app")
        rolled_state = {
            "active_slot": prev_slot,
            "active_port": int(prev_port),
            "active_app": prev_app,
            "active_commit": prev_commit,
            "active_release": str(prev_release) if prev_release else None,
            "previous_slot": state.get("active_slot"),
            "previous_port": state.get("active_port"),
            "previous_app": old_active_app,
            "previous_commit": state.get("active_commit"),
            "previous_release": state.get("active_release"),
            "health": health_payload,
            "updated_at": _utc_now(),
        }
        save_state(config.state_file, rolled_state)

        if not config.keep_standby and old_active_app and old_active_app != prev_app:
            if config.drain_seconds > 0:
                time.sleep(config.drain_seconds)
            _pm2_stop_app(old_active_app, runner=runner)

        print(json.dumps(rolled_state, indent=2, ensure_ascii=False))
        return rolled_state


def status(config: DeployConfig) -> dict[str, Any]:
    assert config.state_file is not None
    state = load_state(config.state_file)
    dist_target = str(config.dist_path.resolve()) if config.dist_path.is_symlink() else (
        str(config.dist_path) if config.dist_path.exists() else None
    )
    out = {
        "repo_dir": str(config.repo_dir),
        "head_commit": _git_short_head(config.repo_dir),
        "upstream_file": str(config.upstream_file),
        "dist_target": dist_target,
        "state": state,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return out


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CocoCV Host PM2 + Nginx Blue-Green Deploy CLI")
    parser.add_argument("action", choices=["status", "deploy", "rollback"])
    parser.add_argument("--repo-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--upstream-file", type=Path, default=Path(os.getenv("COCOCV_NGINX_UPSTREAM_FILE", "/etc/nginx/conf.d/cococv-upstream.conf")))
    parser.add_argument("--state-file", type=Path, default=None)
    parser.add_argument("--blue-port", type=int, default=_env_int("COCOCV_BLUE_PORT", 9001))
    parser.add_argument("--green-port", type=int, default=_env_int("COCOCV_GREEN_PORT", 9002))
    parser.add_argument("--legacy-port", type=int, default=_env_int("COCOCV_LEGACY_PORT", 9000))
    parser.add_argument("--drain-seconds", type=float, default=_env_float("COCOCV_DRAIN_SECONDS", 15.0))
    parser.add_argument("--health-timeout", type=float, default=_env_float("COCOCV_HEALTH_TIMEOUT", 45.0))
    parser.add_argument("--keep-releases", type=int, default=_env_int("COCOCV_KEEP_RELEASES", 5))
    parser.add_argument("--workers", type=int, default=_env_int("COCOCV_UVICORN_WORKERS", 2))
    parser.add_argument("--skip-git", action="store_true")
    parser.add_argument("--skip-deps", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--keep-standby", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = DeployConfig(
        repo_dir=args.repo_dir,
        blue_port=args.blue_port,
        green_port=args.green_port,
        legacy_port=args.legacy_port,
        upstream_file=args.upstream_file,
        state_file=args.state_file,
        drain_seconds=args.drain_seconds,
        health_timeout=args.health_timeout,
        keep_releases=args.keep_releases,
        workers=args.workers,
        skip_git=args.skip_git,
        skip_deps=args.skip_deps,
        skip_build=args.skip_build,
        keep_standby=args.keep_standby,
        dry_run=args.dry_run,
    )
    try:
        if args.action == "status":
            status(config)
        elif args.action == "deploy":
            deploy(config)
        elif args.action == "rollback":
            rollback(config)
        return 0
    except DeployError as exc:
        print(f"[blue-green] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
