"""Universal harness base: one shared skill core rendered per harness adapter."""
from __future__ import annotations

from backend.skillkit.adapters import AdapterError, HarnessAdapter, load_adapter, load_adapters
from backend.skillkit.docs import (
    SkillRenderError,
    company_logo_keys,
    html_rich_text_fields,
    plain_text_fields,
    render_schema_markdown,
)
from backend.skillkit.render import (
    compare_tree,
    emit_frontmatter,
    load_descriptions,
    normalize_text,
    render_harness,
    select_adapters,
    skill_dir_for,
    templates_root,
    validate_descriptions,
    write_tree,
)

__all__ = [
    "AdapterError",
    "HarnessAdapter",
    "SkillRenderError",
    "company_logo_keys",
    "compare_tree",
    "emit_frontmatter",
    "html_rich_text_fields",
    "load_adapter",
    "load_adapters",
    "load_descriptions",
    "normalize_text",
    "plain_text_fields",
    "render_harness",
    "render_schema_markdown",
    "select_adapters",
    "skill_dir_for",
    "templates_root",
    "validate_descriptions",
    "write_tree",
]
