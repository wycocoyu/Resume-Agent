"""Generate ``references/schema.md`` from the live contract instead of hand-copying it.

Facts are generated (field names, types, required/optional, the eight HTML
rich-text fields, the plain-text field list, the built-in company logo keys).
Reasoning stays hand-written in the ``.in`` template. This is what keeps
``references/schema.md`` from drifting away from ``backend/cli/schema.py``.
"""
from __future__ import annotations

import re
import types
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel

from backend.skillkit import _toml

_MARKER_RE = re.compile(r"<!--\s*gen:([a-z0-9-]+)\s*-->")
_SCALAR_NAMES = {"str": "string", "int": "number", "float": "number", "bool": "boolean"}

_schema_module: Any | None = None


def _schema() -> Any:
    """Import ``backend.cli.schema`` lazily.

    Importing it at module scope would create a cycle: ``backend.skillkit`` ->
    ``backend.cli.schema`` -> ``backend.cli.__init__`` -> ``skill_cmd`` ->
    ``backend.skillkit.render`` -> this module. A deferred import keeps
    ``import backend.skillkit`` usable on its own.
    """
    global _schema_module
    if _schema_module is None:
        from backend.cli import schema as module

        _schema_module = module
    return _schema_module


_annotations_cache: dict[str, Any] | None = None


def _annotations() -> dict[str, Any]:
    """Resolved annotations that keep ``Annotated`` metadata (validators included)."""
    global _annotations_cache
    if _annotations_cache is None:
        _annotations_cache = get_type_hints(_schema().ResumeDataModel, include_extras=True)
    return _annotations_cache


class SkillRenderError(RuntimeError):
    """Raised when templates, adapters or generated artifacts are inconsistent."""


def _format_type(annotation: Any) -> str:
    """Render a Pydantic annotation as a compact TypeScript-flavoured type."""
    metadata = getattr(annotation, "__metadata__", None)
    if metadata is not None:
        origin = getattr(annotation, "__origin__", None)
        if origin is not None:
            return _format_type(origin)

    origin = get_origin(annotation)
    if origin is Literal:
        return " | ".join(f'"{arg}"' for arg in get_args(annotation))
    if origin in (Union, types.UnionType):
        parts: list[str] = []
        for arg in get_args(annotation):
            rendered = "null" if arg is type(None) else _format_type(arg)
            if rendered not in parts:
                parts.append(rendered)
        return " | ".join(parts) if parts else "null"
    if origin is list:
        args = get_args(annotation)
        return f"{_format_type(args[0])}[]" if args else "any[]"
    if origin is dict:
        args = get_args(annotation)
        if len(args) == 2:
            return f"Record<{_format_type(args[0])}, {_format_type(args[1])}>"
        return "Record<string, any>"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        # Display the Workspace v2 type name (``BasicInfo``) rather than the
        # internal Pydantic class name (``BasicInfoModel``).
        return annotation.__name__.removesuffix("Model")
    return _SCALAR_NAMES.get(getattr(annotation, "__name__", ""), "any")


def _cell(text: str) -> str:
    """Escape a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _check_notes(notes: dict[str, str]) -> None:
    fields = _schema().ResumeDataModel.model_fields
    missing = [name for name in fields if name not in notes]
    if missing:
        raise SkillRenderError(
            "core/references/field_notes.toml is missing notes for top-level field(s): "
            + ", ".join(sorted(missing))
            + ". Add a note so a newly added field cannot ship undocumented."
        )
    unknown = sorted(set(notes) - set(fields))
    if unknown:
        raise SkillRenderError(
            "core/references/field_notes.toml documents unknown top-level field(s): "
            + ", ".join(unknown)
        )


def _annotation_tags(name: str) -> str:
    """Extra type qualifiers kept inline with the type, e.g. ``(HTML)``."""
    hint = _annotations().get(name)
    for item in getattr(hint, "__metadata__", ()):
        if getattr(getattr(item, "func", None), "__name__", "") == "_require_non_empty":
            return " (non-empty)"
    if name in set(_schema().FIELD_CONVENTIONS["html_rich_text_fields"]):
        return " (HTML)"
    return ""


def _table(fields: list[tuple[str, Any]], notes: dict[str, str]) -> str:
    rows = ["| Key | Type | Notes |", "| :--- | :--- | :--- |"]
    for name, info in fields:
        type_cell = f"`{_cell(_format_type(_annotations().get(name, info.annotation)))}`" + _annotation_tags(name)
        rows.append(f"| `{name}` | {type_cell} | {_cell(notes[name])} |")
    return "\n".join(rows)


def required_top_level_fields() -> list[tuple[str, Any]]:
    return [(n, f) for n, f in _schema().ResumeDataModel.model_fields.items() if f.is_required()]


def optional_top_level_fields() -> list[tuple[str, Any]]:
    return [(n, f) for n, f in _schema().ResumeDataModel.model_fields.items() if not f.is_required()]


def html_rich_text_fields() -> list[str]:
    return list(_schema().FIELD_CONVENTIONS["html_rich_text_fields"])


def plain_text_fields() -> list[str]:
    return list(_schema().FIELD_CONVENTIONS["plain_text_fields"])


def company_logo_keys() -> list[str]:
    """Return the built-in ``companyLogo`` keys in declaration order."""
    try:
        from backend.company_logos import KNOWN_LOGO_META
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise SkillRenderError(f"Cannot import company logo dictionary: {exc}") from exc

    keys: list[str] = []
    for meta in KNOWN_LOGO_META.values():
        key = (meta or {}).get("key")
        if isinstance(key, str) and key and key not in keys:
            keys.append(key)
    if not keys:  # pragma: no cover - defensive
        raise SkillRenderError("Company logo dictionary is empty; refusing to render an empty key list.")
    return keys


def _blocks(notes: dict[str, str]) -> dict[str, str]:
    rich = html_rich_text_fields()
    plain = plain_text_fields()
    logos = company_logo_keys()
    return {
        "required-count": str(len(required_top_level_fields())),
        "rich-text-count": str(len(rich)),
        "top-required": _table(required_top_level_fields(), notes),
        "top-optional": _table(optional_top_level_fields(), notes),
        "rich-text": "\n".join(f"{i}. `{field}`" for i, field in enumerate(rich, start=1)),
        "plain-text": "\n".join(f"- `{field}`" for field in plain),
        "company-logos": ", ".join(f"`{key}`" for key in logos),
    }


def render_schema_markdown(templates_root: Path) -> str:
    """Render ``core/references/schema.md.in`` into the final Markdown document."""
    template_path = templates_root / "core" / "references" / "schema.md.in"
    notes_path = templates_root / "core" / "references" / "field_notes.toml"
    if not template_path.is_file():
        raise SkillRenderError(f"Missing schema template: {template_path}")
    if not notes_path.is_file():
        raise SkillRenderError(f"Missing field notes: {notes_path}")

    notes = _toml.load_path(notes_path).get("notes", {})
    if not isinstance(notes, dict):
        raise SkillRenderError("field_notes.toml must contain a [notes] table")
    notes = {str(k): str(v) for k, v in notes.items()}
    _check_notes(notes)

    blocks = _blocks(notes)
    template = template_path.read_text(encoding="utf-8")

    used: set[str] = set()

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in blocks:
            raise SkillRenderError(f"Unknown generator marker: gen:{name} in {template_path}")
        used.add(name)
        return blocks[name]

    rendered = _MARKER_RE.sub(_replace, template)
    if "<!-- gen:" in rendered:  # pragma: no cover - defensive
        raise SkillRenderError("Unresolved generator marker left in schema.md")

    unused = sorted(set(blocks) - used)
    if unused:
        raise SkillRenderError(
            f"schema.md.in does not use generator block(s): {', '.join(unused)}. "
            "A generated fact that never reaches the document is a silent hole."
        )

    if not rendered.endswith("\n"):
        rendered += "\n"
    return rendered.replace("\r\n", "\n")
