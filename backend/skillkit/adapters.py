"""Harness adapter contract: declarative, data-only description of one AI harness.

An adapter never contains prose. It only declares:

* how the core body is wrapped (``frontmatter``),
* which constraints the shared copy must satisfy (``constraints``),
* which files get rendered and where they land (``assets``),
* where the generated skill is discovered and how it is installed (``install``).

Any harness requirement that cannot be expressed here is a contract gap: the
loader rejects unknown keys so that a gap fails loudly instead of being
silently ignored by a per-harness ``if`` branch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.skillkit import _toml

_SCHEMA_VERSION = 1

_TOP_LEVEL_KEYS = {
    "schema_version",
    "id",
    "display_name",
    "status",
    "invoke_syntax",
    "cli_min_version",
    "frontmatter",
    "constraints",
    "assets",
    "install",
    "notes",
}
_FRONTMATTER_KEYS = {
    "name",
    "description",
    "short_description",
    "include_metadata",
    "extra",
}
_CONSTRAINT_KEYS = {
    "description_min",
    "description_max",
    "short_description_min",
    "short_description_max",
    "forbid_chars",
}
_ASSET_KEYS = {"from", "to", "mode"}
_INSTALL_KEYS = {
    "scope_default",
    "strategy",
    "user_paths",
    "project_paths",
}
_ASSET_MODES = {"skill", "copy", "schema"}
_STATUSES = {"verified", "experimental"}
_STRATEGIES = {"copy", "link"}
_SCOPES = {"user", "project"}


class AdapterError(ValueError):
    """Raised when an adapter file violates the declarative contract."""


@dataclass(frozen=True)
class Asset:
    source: str
    target: str
    mode: str


@dataclass(frozen=True)
class HarnessAdapter:
    schema_version: int
    id: str
    display_name: str
    status: str
    invoke_syntax: str
    cli_min_version: str
    name: str
    description_key: str
    short_description_key: str
    include_metadata: bool
    extra_frontmatter: dict[str, Any]
    constraints: dict[str, Any]
    assets: tuple[Asset, ...]
    scope_default: str
    strategy: str
    user_paths: tuple[str, ...]
    project_paths: tuple[str, ...]
    notes: str
    source_dir: Path = field(default=Path("."), compare=False)

    @property
    def verified(self) -> bool:
        return self.status == "verified"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AdapterError(message)


def _check_keys(payload: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise AdapterError(
            f"{where}: unsupported key(s) {unknown}. "
            "The adapter contract is deliberately closed; extend the contract "
            "instead of adding a per-harness code branch."
        )


def _str_list(value: Any, where: str) -> tuple[str, ...]:
    _require(isinstance(value, list), f"{where} must be an array of strings")
    out: list[str] = []
    for item in value:
        _require(isinstance(item, str) and item.strip(), f"{where} entries must be non-empty strings")
        out.append(item)
    return tuple(out)


def load_adapter(path: Path) -> HarnessAdapter:
    """Parse and validate one ``harnesses/<id>/meta.toml``."""
    payload = _toml.load_path(path)
    where = str(path)
    _check_keys(payload, _TOP_LEVEL_KEYS, where)

    schema_version = payload.get("schema_version")
    _require(schema_version == _SCHEMA_VERSION, f"{where}: schema_version must be {_SCHEMA_VERSION}")

    harness_id = payload.get("id")
    _require(isinstance(harness_id, str) and harness_id.strip(), f"{where}: id is required")
    status = payload.get("status", "experimental")
    _require(status in _STATUSES, f"{where}: status must be one of {sorted(_STATUSES)}")

    frontmatter = payload.get("frontmatter")
    _require(isinstance(frontmatter, dict), f"{where}: [frontmatter] table is required")
    _check_keys(frontmatter, _FRONTMATTER_KEYS, f"{where} [frontmatter]")
    name = frontmatter.get("name")
    _require(isinstance(name, str) and name.strip(), f"{where}: frontmatter.name is required")
    description_key = frontmatter.get("description", "long")
    _require(
        description_key in {"long", "short"},
        f"{where}: frontmatter.description must be 'long' or 'short'",
    )
    short_key = frontmatter.get("short_description", "short")
    _require(
        short_key in {"long", "short"},
        f"{where}: frontmatter.short_description must be 'long' or 'short'",
    )
    include_metadata = frontmatter.get("include_metadata", False)
    _require(isinstance(include_metadata, bool), f"{where}: include_metadata must be a boolean")
    extra = frontmatter.get("extra", {})
    _require(isinstance(extra, dict), f"{where}: [frontmatter.extra] must be a table")

    constraints = payload.get("constraints", {})
    _require(isinstance(constraints, dict), f"{where}: [constraints] must be a table")
    _check_keys(constraints, _CONSTRAINT_KEYS, f"{where} [constraints]")
    forbid_chars = constraints.get("forbid_chars", [])
    _require(
        isinstance(forbid_chars, list) and all(isinstance(c, str) and len(c) == 1 for c in forbid_chars),
        f"{where}: constraints.forbid_chars must be a list of single characters",
    )

    raw_assets = payload.get("assets", [])
    _require(isinstance(raw_assets, list) and raw_assets, f"{where}: at least one [[assets]] is required")
    assets: list[Asset] = []
    for index, raw in enumerate(raw_assets):
        _require(isinstance(raw, dict), f"{where}: assets[{index}] must be a table")
        _check_keys(raw, _ASSET_KEYS, f"{where} assets[{index}]")
        mode = raw.get("mode", "copy")
        _require(mode in _ASSET_MODES, f"{where}: assets[{index}].mode must be one of {sorted(_ASSET_MODES)}")
        source = raw.get("from")
        target = raw.get("to")
        _require(isinstance(source, str) and source, f"{where}: assets[{index}].from is required")
        _require(isinstance(target, str) and target, f"{where}: assets[{index}].to is required")
        _require(
            ".." not in Path(target).parts,
            f"{where}: assets[{index}].to must not escape the skill directory",
        )
        assets.append(Asset(source=source, target=target, mode=mode))

    install = payload.get("install", {})
    _require(isinstance(install, dict), f"{where}: [install] must be a table")
    _check_keys(install, _INSTALL_KEYS, f"{where} [install]")
    scope_default = install.get("scope_default", "user")
    _require(scope_default in _SCOPES, f"{where}: install.scope_default must be 'user' or 'project'")
    strategy = install.get("strategy", "copy")
    _require(strategy in _STRATEGIES, f"{where}: install.strategy must be 'copy' or 'link'")

    return HarnessAdapter(
        schema_version=schema_version,
        id=harness_id,
        display_name=str(payload.get("display_name") or harness_id),
        status=status,
        invoke_syntax=str(payload.get("invoke_syntax") or harness_id),
        cli_min_version=str(payload.get("cli_min_version") or "0.0.0"),
        name=name,
        description_key=description_key,
        short_description_key=short_key,
        include_metadata=include_metadata,
        extra_frontmatter=dict(extra),
        constraints=dict(constraints),
        assets=tuple(assets),
        scope_default=scope_default,
        strategy=strategy,
        user_paths=_str_list(install.get("user_paths", []), f"{where}: install.user_paths"),
        project_paths=_str_list(install.get("project_paths", []), f"{where}: install.project_paths"),
        notes=str(payload.get("notes") or ""),
        source_dir=path.parent,
    )


def load_adapters(templates_root: Path) -> dict[str, HarnessAdapter]:
    """Load every adapter under ``<templates_root>/harnesses`` keyed by harness id."""
    harnesses_dir = templates_root / "harnesses"
    if not harnesses_dir.is_dir():
        raise AdapterError(f"Missing harness directory: {harnesses_dir}")
    adapters: dict[str, HarnessAdapter] = {}
    for meta in sorted(harnesses_dir.glob("*/meta.toml")):
        adapter = load_adapter(meta)
        if adapter.id in adapters:
            raise AdapterError(f"Duplicate harness id: {adapter.id}")
        adapters[adapter.id] = adapter
    if not adapters:
        raise AdapterError(f"No harness adapters found under {harnesses_dir}")
    return adapters
