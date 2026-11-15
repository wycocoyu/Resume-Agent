"""Install / inspect / uninstall generated skills into harness discovery directories.

Design rules:

* Never destroy data the installer did not create (tracked in a manifest with
  per-file SHA-256, so a user edit is detected and preserved).
* Default to ``copy``; ``link`` is opt-in and refused when the platform cannot
  create the link.
* Always able to run as a dry-run, so the plan is reviewable before any write.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.skillkit.adapters import HarnessAdapter
from backend.skillkit.docs import SkillRenderError
from backend.skillkit.render import render_harness, templates_root

MANIFEST_VERSION = 1
_ENV_STATE_DIR = "RESUME_AGENT_STATE_DIR"


def cli_version() -> str:
    try:
        from importlib.metadata import version

        return version("resume-agent")
    except Exception:  # pragma: no cover - source checkout without install
        return "0.0.0"


def state_dir() -> Path:
    override = os.environ.get(_ENV_STATE_DIR)
    return Path(override).expanduser() if override else Path.home() / ".resume-agent"


def manifest_path() -> Path:
    return state_dir() / "state.json"


def load_manifest() -> dict[str, Any]:
    path = manifest_path()
    if not path.is_file():
        return {"version": MANIFEST_VERSION, "installs": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": MANIFEST_VERSION, "installs": []}
    if not isinstance(data, dict) or not isinstance(data.get("installs"), list):
        return {"version": MANIFEST_VERSION, "installs": []}
    return data


def save_manifest(data: dict[str, Any]) -> None:
    path = manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str | None:
    """Hash a skill file, normalising newlines so an editor's CRLF is not a change."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:  # pragma: no cover - skill payloads are text
        return sha256_bytes(raw)
    return sha256_bytes(text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))


def candidate_paths(adapter: HarnessAdapter, scope: str) -> list[Path]:
    raw = adapter.user_paths if scope == "user" else adapter.project_paths
    return [Path(item).expanduser() for item in raw]


def resolve_target(adapter: HarnessAdapter, scope: str, override: str | None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    paths = candidate_paths(adapter, scope)
    if not paths:
        raise SkillRenderError(
            f"Harness '{adapter.id}' has no verified discovery path for scope '{scope}'. "
            "Pass --path <dir> explicitly (the adapter is marked experimental)."
        )
    return (paths[0] / adapter.name).resolve()


def _file_hashes(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            rel = path.relative_to(root).as_posix()
            digest = sha256_file(path)
            if digest:
                out[rel] = digest
    return out


def find_entry(manifest: dict[str, Any], harness: str, target: Path) -> dict[str, Any] | None:
    resolved = str(target)
    for entry in manifest.get("installs", []):
        if entry.get("harness") == harness and entry.get("target") == resolved:
            return entry
    return None


def install(
    adapter: HarnessAdapter,
    *,
    scope: str,
    target_override: str | None = None,
    strategy: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    out_root: Path | None = None,
) -> dict[str, Any]:
    """Install one harness skill. Returns a plan/result payload."""
    root = out_root or templates_root()
    files = render_harness(adapter, root)
    target = resolve_target(adapter, scope, target_override)
    strategy = strategy or adapter.strategy
    manifest = load_manifest()
    entry = find_entry(manifest, adapter.id, target)

    existed_before = target.exists() or target.is_symlink()
    if existed_before and entry is None and not force:
        raise SkillRenderError(
            f"Target already exists and was not installed by resume-agent: {target}. "
            "Re-run with --force to take ownership, or pick another --path."
        )

    planned = sorted(files)
    if dry_run:
        return {
            "ok": True,
            "command": "skill.install",
            "dry_run": True,
            "harness": adapter.id,
            "scope": scope,
            "strategy": strategy,
            "target": str(target),
            "files": planned,
            "overwrites": existed_before,
            "alternates": [str(p) for p in candidate_paths(adapter, scope)[1:]],
        }

    if strategy == "link":
        build_dir = state_dir() / "build" / adapter.id / adapter.name
        build_dir.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            path = build_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(build_dir, target, target_is_directory=True)
        except OSError as exc:
            raise SkillRenderError(
                f"Cannot create symlink at {target}: {exc}. "
                "On Windows, use --strategy copy or enable Developer Mode."
            ) from exc
        hashes: dict[str, str] = {}
        linked_to = str(build_dir)
    else:
        if target.is_symlink():
            target.unlink()
        target.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            path = target / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        hashes = _file_hashes(target)
        linked_to = None

    new_entry = {
        "harness": adapter.id,
        "scope": scope,
        "target": str(target),
        "strategy": strategy,
        "linked_to": linked_to,
        "cli_version": cli_version(),
        "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": hashes,
    }
    installs = [e for e in manifest.get("installs", []) if not (e.get("harness") == adapter.id and e.get("target") == str(target))]
    installs.append(new_entry)
    manifest["installs"] = installs
    manifest["version"] = MANIFEST_VERSION
    save_manifest(manifest)

    return {
        "ok": True,
        "command": "skill.install",
        "dry_run": False,
        "harness": adapter.id,
        "scope": scope,
        "strategy": strategy,
        "target": str(target),
        "files": planned,
        "alternates": [str(p) for p in candidate_paths(adapter, scope)[1:]],
    }


def status_entries() -> list[dict[str, Any]]:
    """Read-only health report for every recorded install."""
    manifest = load_manifest()
    current = cli_version()
    report: list[dict[str, Any]] = []
    for entry in manifest.get("installs", []):
        target = Path(entry.get("target", ""))
        files = entry.get("files") or {}
        modified: list[str] = []
        missing: list[str] = []
        for rel, digest in files.items():
            path = target / rel
            if not path.is_file():
                missing.append(rel)
            elif sha256_file(path) != digest:
                modified.append(rel)
        state = "ok"
        if not target.exists():
            state = "missing"
        elif missing:
            state = "incomplete"
        elif modified:
            state = "modified"
        elif entry.get("cli_version") and entry["cli_version"] != current:
            state = "version_skew"
        report.append(
            {
                "harness": entry.get("harness"),
                "scope": entry.get("scope"),
                "target": str(target),
                "strategy": entry.get("strategy"),
                "installed_version": entry.get("cli_version"),
                "current_version": current,
                "state": state,
                "modified": sorted(modified),
                "missing": sorted(missing),
            }
        )
    return report


def uninstall(harness: str, *, dry_run: bool = False, target_override: str | None = None) -> dict[str, Any]:
    """Remove only files this installer created and the user has not modified."""
    manifest = load_manifest()
    entries = [e for e in manifest.get("installs", []) if e.get("harness") == harness]
    if target_override:
        resolved = str(Path(target_override).expanduser().resolve())
        entries = [e for e in entries if e.get("target") == resolved]
    if not entries:
        raise SkillRenderError(f"No recorded install for harness '{harness}'.")

    removed: list[str] = []
    kept: list[str] = []
    targets: list[str] = []
    remaining: list[dict[str, Any]] = []
    for entry in entries:
        target = Path(entry.get("target", ""))
        targets.append(str(target))
        files = entry.get("files") or {}
        entry_kept: dict[str, str] = {}
        if entry.get("strategy") == "link" and target.is_symlink():
            if not dry_run:
                target.unlink()
            removed.append(str(target))
            continue
        for rel, digest in files.items():
            path = target / rel
            if not path.is_file():
                continue
            current = sha256_file(path)
            if current != digest:
                # User edited it: never delete. Keep tracking the ORIGINAL
                # digest so that reverting the file makes it removable again.
                kept.append(str(path))
                entry_kept[rel] = digest
                continue
            if not dry_run:
                path.unlink()
            removed.append(str(path))
        if not dry_run and target.is_dir():
            for path in sorted(target.rglob("*"), reverse=True):
                if path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
            if target.is_dir() and not any(target.iterdir()):
                target.rmdir()
        if entry_kept:
            tracked = dict(entry)
            tracked["files"] = entry_kept
            remaining.append(tracked)

    if not dry_run:
        drop = {str(e.get("target")) for e in entries}
        manifest["installs"] = [
            e
            for e in manifest.get("installs", [])
            if not (e.get("harness") == harness and str(e.get("target")) in drop)
        ]
        manifest["installs"].extend(remaining)
        save_manifest(manifest)

    return {
        "ok": True,
        "command": "skill.uninstall",
        "dry_run": dry_run,
        "harness": harness,
        "targets": targets,
        "removed": sorted(removed),
        "kept": sorted(kept),
    }
