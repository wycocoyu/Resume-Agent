"""Runtime feature flags and AI rate/cooldown settings with .env mtime_ns hot-reload."""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Mapping, Optional

# 统一模块别名，避免 `services.runtime_features` 与 `backend.services.runtime_features` 双实例分裂
if __name__ == "services.runtime_features":
    sys.modules.setdefault("backend.services.runtime_features", sys.modules[__name__])
elif __name__ == "backend.services.runtime_features":
    sys.modules.setdefault("services.runtime_features", sys.modules[__name__])

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

_FEATURE_TO_ENV = {
    "auth_enabled": "AUTH_ENABLED",
    "agent_enabled": "AGENT_ENABLED",
    "editor_ai_enabled": "EDITOR_AI_ENABLED",
}

_MANAGED_ENV_KEYS = frozenset({
    "AUTH_ENABLED",
    "AGENT_ENABLED",
    "EDITOR_AI_ENABLED",
    "ADMIN_SWITCH_TOKEN",
    "ANON_AI_IMPORT_HOURLY_LIMIT",
    "ANON_AI_REWRITE_HOURLY_LIMIT",
    "ANON_AI_AGENT_HOURLY_LIMIT",
    "AI_QUOTA_COOLDOWN_SECONDS",
})

_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSY_VALUES = frozenset({"0", "false", "no", "off"})

_ENV_LOCK = threading.Lock()
_last_mtime_by_path: dict[Path, tuple[int, int]] = {}
_loaded_keys_by_path: dict[Path, set[str]] = {}


def _parse_bool(raw: Optional[str], default: bool) -> bool:
    if raw is None:
        return default
    s = raw.strip().lower()
    if not s:
        return default
    if s in _TRUTHY_VALUES:
        return True
    if s in _FALSY_VALUES:
        return False
    return default


def _parse_int(raw: Optional[str], default: int, *, min_value: int = 0) -> int:
    if raw is None:
        return default
    s = raw.strip()
    if not s:
        return default
    try:
        value = int(s)
    except ValueError:
        return default
    if value < min_value:
        return default
    return value


def _parse_env_file(target: Path) -> dict[str, str]:
    parsed: dict[str, str] = {}
    with open(target, "r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            parsed[key.strip()] = value.strip().strip('"').strip("'")
    return parsed


def reset_runtime_features_cache() -> None:
    """清除 .env 热加载时间戳缓存（供测试使用）。"""
    with _ENV_LOCK:
        _last_mtime_by_path.clear()
        _loaded_keys_by_path.clear()


def sync_runtime_features_if_changed(env_path: Optional[Path] = None) -> None:
    """当 .env 文件 mtime_ns 变化时，将运行时开关与限流配置同步到 os.environ。"""
    target = (Path(env_path) if env_path is not None else (ROOT_DIR / ".env")).resolve()
    try:
        st = target.stat()
    except OSError:
        return

    sig = (st.st_mtime_ns, st.st_size)
    with _ENV_LOCK:
        if _last_mtime_by_path.get(target) == sig:
            return
        try:
            parsed = _parse_env_file(target)
        except OSError:
            return

        prev_loaded = _loaded_keys_by_path.get(target, set())
        for env_key in _MANAGED_ENV_KEYS:
            if env_key in parsed:
                os.environ[env_key] = parsed[env_key]
            elif env_key in prev_loaded:
                os.environ.pop(env_key, None)

        _loaded_keys_by_path[target] = set(parsed.keys()) & _MANAGED_ENV_KEYS
        _last_mtime_by_path[target] = sig


def get_runtime_features(env_path: Optional[Path] = None) -> dict[str, bool]:
    """读取当前生效的前后端特性开关。"""
    sync_runtime_features_if_changed(env_path=env_path)
    return {
        "auth_enabled": _parse_bool(os.getenv("AUTH_ENABLED"), False),
        "agent_enabled": _parse_bool(os.getenv("AGENT_ENABLED"), True),
        "editor_ai_enabled": _parse_bool(os.getenv("EDITOR_AI_ENABLED"), True),
    }


def is_auth_enabled(env_path: Optional[Path] = None) -> bool:
    return get_runtime_features(env_path=env_path)["auth_enabled"]


def is_agent_enabled(env_path: Optional[Path] = None) -> bool:
    return get_runtime_features(env_path=env_path)["agent_enabled"]


def is_editor_ai_enabled(env_path: Optional[Path] = None) -> bool:
    return get_runtime_features(env_path=env_path)["editor_ai_enabled"]


def get_admin_switch_token(env_path: Optional[Path] = None) -> str:
    sync_runtime_features_if_changed(env_path=env_path)
    return (os.getenv("ADMIN_SWITCH_TOKEN") or "").strip()


def get_anon_ai_import_hourly_limit(env_path: Optional[Path] = None) -> int:
    sync_runtime_features_if_changed(env_path=env_path)
    return _parse_int(os.getenv("ANON_AI_IMPORT_HOURLY_LIMIT"), 10, min_value=0)


def get_anon_ai_rewrite_hourly_limit(env_path: Optional[Path] = None) -> int:
    sync_runtime_features_if_changed(env_path=env_path)
    return _parse_int(os.getenv("ANON_AI_REWRITE_HOURLY_LIMIT"), 30, min_value=0)


def get_anon_ai_agent_hourly_limit(env_path: Optional[Path] = None) -> int:
    sync_runtime_features_if_changed(env_path=env_path)
    return _parse_int(os.getenv("ANON_AI_AGENT_HOURLY_LIMIT"), 20, min_value=1)


def get_ai_quota_cooldown_seconds(env_path: Optional[Path] = None) -> int:
    sync_runtime_features_if_changed(env_path=env_path)
    return _parse_int(os.getenv("AI_QUOTA_COOLDOWN_SECONDS"), 600, min_value=0)


def update_runtime_features(
    updates: Mapping[str, Optional[bool]],
    env_path: Optional[Path] = None,
) -> dict[str, bool]:
    """将部分或全部特性开关持久化写入 .env（保留现有注释和其他键）并同步 os.environ。"""
    env_updates: dict[str, str] = {}
    for field_name, value in updates.items():
        if value is None or field_name not in _FEATURE_TO_ENV:
            continue
        env_key = _FEATURE_TO_ENV[field_name]
        env_updates[env_key] = "true" if bool(value) else "false"

    target = Path(env_path) if env_path is not None else (ROOT_DIR / ".env")
    resolved = target.resolve()

    if env_updates:
        with _ENV_LOCK:
            target.parent.mkdir(parents=True, exist_ok=True)
            existing_lines: list[str] = []
            if target.exists():
                with open(target, "r", encoding="utf-8") as fh:
                    existing_lines = fh.readlines()

            new_lines: list[str] = []
            seen_keys: set[str] = set()
            for line in existing_lines:
                stripped = line.strip()
                key_part = (
                    stripped.split("=", 1)[0].strip()
                    if "=" in stripped and not stripped.startswith("#")
                    else ""
                )
                if key_part in env_updates:
                    if key_part not in seen_keys:
                        new_lines.append(f"{key_part}={env_updates[key_part]}\n")
                        seen_keys.add(key_part)
                else:
                    new_lines.append(line)

            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines[-1] = new_lines[-1] + "\n"

            for env_key, env_val in env_updates.items():
                if env_key not in seen_keys:
                    new_lines.append(f"{env_key}={env_val}\n")

            with open(target, "w", encoding="utf-8") as fh:
                fh.writelines(new_lines)

            for env_key, env_val in env_updates.items():
                os.environ[env_key] = env_val

            try:
                st = target.stat()
                _last_mtime_by_path[resolved] = (st.st_mtime_ns, st.st_size)
                loaded = _loaded_keys_by_path.setdefault(resolved, set())
                loaded.update(env_updates.keys())
            except OSError:
                pass

    return get_runtime_features(env_path=env_path)


# 启动加载时初始化 .env 基线 mtime，避免之后运行期的测试 monkeypatch 被未修改的 .env 覆写
sync_runtime_features_if_changed()
