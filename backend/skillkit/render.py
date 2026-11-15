"""Render harness skill directories from the shared core (the only write path)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

import backend
from backend.skillkit import _toml
from backend.skillkit.adapters import HarnessAdapter
from backend.skillkit.docs import SkillRenderError, render_schema_markdown

_PLACEHOLDER_RE = re.compile(r"\{\{([a-z_]+)\}\}")
_TEMPLATES_DIRNAME = "skill_templates"
_LAYOUTS = {"nested", "flat"}


def templates_root() -> Path:
    """Absolute path to the packaged ``skill_templates`` directory."""
    return Path(backend.__file__).resolve().parent / _TEMPLATES_DIRNAME


def normalize_text(text: str) -> str:
    """Force LF newlines so generated artifacts are byte-stable across platforms."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _scalar(value: Any) -> str:
    """Emit a YAML scalar; JSON double-quoted strings are valid YAML."""
    return json.dumps(value, ensure_ascii=False)


def emit_frontmatter(
    *,
    name: str,
    description: str,
    extra: dict[str, Any],
    short_description: str | None = None,
) -> str:
    lines = ["---", f"name: {_scalar(name)}", f"description: {_scalar(description)}"]
    for key, value in extra.items():
        if isinstance(value, (list, tuple)):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {_scalar(item)}")
        else:
            lines.append(f"{key}: {_scalar(value)}")
    if short_description is not None:
        lines.append("metadata:")
        lines.append(f"  short-description: {_scalar(short_description)}")
    lines.append("---")
    return "\n".join(lines)


def load_descriptions(root: Path) -> dict[str, str]:
    payload = _toml.load_path(root / "core" / "description.toml")
    for key in ("name", "long", "short"):
        if not isinstance(payload.get(key), str) or not payload[key].strip():
            raise SkillRenderError(f"core/description.toml is missing a non-empty '{key}'")
    return {k: str(payload[k]) for k in ("name", "long", "short")}


def validate_descriptions(adapter: HarnessAdapter, descriptions: dict[str, str]) -> None:
    """Fail the build when shared copy cannot satisfy an adapter constraint.

    Never truncate: truncation would make the same skill read differently per
    harness, which is exactly the drift the generator exists to prevent.
    """
    checks = (
        ("description", adapter.description_key, "description_min", "description_max"),
        (
            "short_description",
            adapter.short_description_key,
            "short_description_min",
            "short_description_max",
        ),
    )
    problems: list[str] = []
    for label, key, min_key, max_key in checks:
        text = descriptions[key]
        low = adapter.constraints.get(min_key)
        high = adapter.constraints.get(max_key)
        if isinstance(low, int) and len(text) < low:
            problems.append(f"{label} is {len(text)} chars, below {adapter.id} minimum {low}")
        if isinstance(high, int) and len(text) > high:
            problems.append(f"{label} is {len(text)} chars, above {adapter.id} maximum {high}")
    for char in adapter.constraints.get("forbid_chars", []) or []:
        if char in descriptions[adapter.description_key]:
            problems.append(f"description contains forbidden character {char!r} for {adapter.id}")
    if problems:
        raise SkillRenderError(
            "Shared copy violates harness constraints: " + "; ".join(problems) + ". "
            "Edit core/description.toml instead of truncating per harness."
        )


def _substitute(text: str, adapter: HarnessAdapter) -> str:
    mapping = {
        "invoke_syntax": adapter.invoke_syntax,
        "harness_id": adapter.id,
        "harness_display": adapter.display_name,
        "cli_min_version": adapter.cli_min_version,
    }

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in mapping:
            raise SkillRenderError(f"Unknown placeholder {{{{{key}}}}} in skill template")
        return mapping[key]

    result = _PLACEHOLDER_RE.sub(_replace, text)
    leftover = _PLACEHOLDER_RE.search(result)
    if leftover:  # pragma: no cover - defensive
        raise SkillRenderError(f"Unresolved placeholder {leftover.group(0)} in skill template")
    return result


def render_harness(adapter: HarnessAdapter, root: Path | None = None) -> dict[str, str]:
    """Return ``{relative_path: text}`` for one harness, fully deterministic."""
    root = root or templates_root()
    descriptions = load_descriptions(root)
    validate_descriptions(adapter, descriptions)

    body = normalize_text((root / "core" / "body.md").read_text(encoding="utf-8"))
    body = _substitute(body, adapter)

    frontmatter = emit_frontmatter(
        name=adapter.name,
        description=descriptions[adapter.description_key],
        extra=adapter.extra_frontmatter,
        short_description=(
            descriptions[adapter.short_description_key] if adapter.include_metadata else None
        ),
    )

    files: dict[str, str] = {}
    has_skill = False
    schema_cache: str | None = None
    for asset in adapter.assets:
        if asset.mode == "schema":
            if schema_cache is None:
                schema_cache = render_schema_markdown(root)
            files[asset.target] = schema_cache
        elif asset.mode == "skill":
            files[asset.target] = f"{frontmatter}\n\n{body}"
            has_skill = True
        else:
            source = root / asset.source
            if not source.is_file():
                raise SkillRenderError(f"{adapter.id}: missing asset source {source}")
            files[asset.target] = normalize_text(source.read_text(encoding="utf-8"))

    if not has_skill:
        raise SkillRenderError(f"{adapter.id}: adapter declares no asset with mode='skill'")
    if "SKILL.md" not in files:
        raise SkillRenderError(f"{adapter.id}: adapter must render SKILL.md for discovery")
    return {path: normalize_text(text) for path, text in sorted(files.items())}


def skill_dir_for(harness_id: str, out_root: Path, layout: str, skill_name: str) -> Path:
    if layout not in _LAYOUTS:
        raise SkillRenderError(f"layout must be one of {sorted(_LAYOUTS)}")
    return out_root / skill_name if layout == "flat" else out_root / harness_id / skill_name


def write_tree(files: dict[str, str], target: Path) -> list[str]:
    """Write rendered files under ``target``; returns written relative paths."""
    target.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for rel, text in files.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        written.append(rel.replace("\\", "/"))
    return written


def compare_tree(files: dict[str, str], target: Path) -> dict[str, list[str]]:
    """Compare an on-disk tree against rendered output (newline-insensitive)."""
    missing: list[str] = []
    stale: list[str] = []
    for rel, text in files.items():
        path = target / rel
        if not path.is_file():
            missing.append(rel)
            continue
        on_disk = normalize_text(path.read_text(encoding="utf-8"))
        if on_disk != normalize_text(text):
            stale.append(rel)
    expected = {rel.replace("\\", "/") for rel in files}
    extra: list[str] = []
    if target.is_dir():
        for path in target.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(target).as_posix()
            if rel not in expected:
                extra.append(rel)
    return {"missing": sorted(missing), "stale": sorted(stale), "extra": sorted(extra)}


def select_adapters(
    adapters: dict[str, HarnessAdapter], harness: str
) -> list[HarnessAdapter]:
    """Resolve a ``--harness`` value (``all`` or a single id)."""
    if harness == "all":
        return [adapters[key] for key in sorted(adapters)]
    if harness not in adapters:
        raise SkillRenderError(
            f"Unknown harness '{harness}'. Known harnesses: {', '.join(sorted(adapters))}, all"
        )
    return [adapters[harness]]


def iter_targets(
    adapters: Iterable[HarnessAdapter], out_root: Path, layout: str, skill_name: str
) -> list[tuple[HarnessAdapter, Path]]:
    return [(a, skill_dir_for(a.id, out_root, layout, skill_name)) for a in adapters]
