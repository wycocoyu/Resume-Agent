"""CLI `render` subcommand: default strictly-offline local XeLaTeX PDF rendering."""
from __future__ import annotations

import base64
import binascii
import contextlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import typer

from backend.cli.errors import CLIError, emit_json
from backend.cli.schema import load_and_validate_resume_file
from backend.latex_generator import (
    _detect_xelatex_image_ext,
    compile_latex_to_pdf,
    json_to_latex,
)
from backend.resume_converter import convert_to_backend_format

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_TEMPLATE_DIR = _REPO_ROOT / "latex-resume-template"


def _resolve_template_dir(cli_template_dir: Path | None) -> Path:
    if cli_template_dir is not None:
        return cli_template_dir
    env_dir = (os.getenv("RESUME_AGENT_TEMPLATE_DIR") or "").strip()
    if env_dir:
        return Path(env_dir)
    return _DEFAULT_TEMPLATE_DIR


def _resolve_cli_photo(
    raw_photo: Any,
    *,
    input_file: Path,
    warnings: list[str],
) -> tuple[str | None, tuple[str, bytes] | None]:
    """Resolve photo value strictly at CLI boundary:
    - http(s):// -> passed through as URL (handled according to offline/online mode)
    - data:...;base64,... -> decoded and magic-checked into local_photo_bytes
    - local file path -> read at CLI boundary, magic-checked into local_photo_bytes
    """
    if not isinstance(raw_photo, str) or not raw_photo.strip():
        return None, None

    photo = raw_photo.strip()
    if photo.startswith("http://") or photo.startswith("https://"):
        return photo, None

    if photo.startswith("data:"):
        if ";base64," not in photo:
            warnings.append("头像 data URI 非 base64 编码，已自动跳过")
            return None, None
        _, b64_part = photo.split(";base64,", 1)
        try:
            raw_bytes = base64.b64decode(b64_part, validate=False)
        except (binascii.Error, ValueError):
            warnings.append("头像 base64 解码失败，已自动跳过")
            return None, None
        ext = _detect_xelatex_image_ext(raw_bytes)
        if not ext:
            warnings.append("头像 data URI 图片格式不受 XeLaTeX 支持（仅支持 PNG/JPEG/PDF），已自动跳过")
            return None, None
        return "__cli_local_photo__", (ext, raw_bytes)

    # Local filesystem path (only permitted at CLI boundary, never via Web routes)
    candidate = Path(photo)
    resolved_file: Path | None = None
    if candidate.is_absolute():
        if candidate.is_file():
            resolved_file = candidate
    else:
        cwd_candidate = Path.cwd() / candidate
        rel_candidate = input_file.resolve().parent / candidate
        if cwd_candidate.is_file():
            resolved_file = cwd_candidate
        elif rel_candidate.is_file():
            resolved_file = rel_candidate

    if resolved_file is None:
        warnings.append(f"本地头像文件不存在，已自动跳过: {photo}")
        return None, None

    try:
        raw_bytes = resolved_file.read_bytes()
    except OSError as exc:
        warnings.append(f"无法读取本地头像文件 ({photo}): {exc}")
        return None, None

    ext = _detect_xelatex_image_ext(raw_bytes)
    if not ext:
        warnings.append(
            f"本地头像文件格式不受 XeLaTeX 支持（仅支持 PNG/JPEG/PDF），已自动跳过: {photo}"
        )
        return None, None

    return "__cli_local_photo__", (ext, raw_bytes)


def _atomic_write_pdf(output: Path, pdf_bytes: bytes) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".resume_agent_pdf_",
        suffix=".tmp",
        dir=str(output.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(pdf_bytes)
            fh.flush()
        os.replace(tmp_path, output)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def register_render_command(app: typer.Typer, get_output_context: Any) -> None:
    @app.command("render")
    def render_cmd(
        ctx: typer.Context,
        file: Path = typer.Argument(..., help="Path to validated ResumeData JSON file."),
        output: Path = typer.Option(
            ...,
            "-o",
            "--output",
            help="Output PDF file path.",
        ),
        template_dir: Path | None = typer.Option(
            None,
            "--template-dir",
            help="Override LaTeX template directory (default: repo latex-resume-template/ or RESUME_AGENT_TEMPLATE_DIR).",
        ),
        online: bool = typer.Option(
            False,
            "--online",
            help="Allow remote COS/HTTP downloads for logos and HTTP avatars (default: strictly offline).",
        ),
        force: bool = typer.Option(
            False,
            "--force",
            help="Overwrite target PDF file if it already exists.",
        ),
        json_output: bool = typer.Option(
            False,
            "--json",
            help="Emit a single machine-readable JSON object on stdout.",
        ),
    ) -> None:
        """Render a ResumeData JSON file to PDF via local XeLaTeX (strictly offline by default)."""
        json_mode, stdout_stream = get_output_context(ctx, json_output)
        offline = not online
        warnings: list[str] = []

        if output.exists() and not force:
            raise CLIError(
                f"Target PDF already exists: {output} (use --force to overwrite)",
                code="file_exists",
                extra={"command": "render", "input": str(file), "output": str(output), "warnings": warnings},
            )

        raw_data, _, issues, io_or_syntax_err = load_and_validate_resume_file(file)
        if io_or_syntax_err and not issues:
            raise CLIError(
                io_or_syntax_err,
                code="file_error",
                extra={"command": "render", "input": str(file), "output": str(output), "warnings": warnings},
            )
        if issues:
            raise CLIError(
                io_or_syntax_err or f"Resume JSON validation failed with {len(issues)} error(s) in {file}",
                code="invalid_json" if io_or_syntax_err else "validation_failed",
                extra={
                    "command": "render",
                    "input": str(file),
                    "output": str(output),
                    "errors": [item.to_dict() for item in issues],
                    "warnings": warnings,
                },
            )

        assert raw_data is not None
        resolved_template_dir = _resolve_template_dir(template_dir)
        if not resolved_template_dir.is_dir() or not (resolved_template_dir / "resume.cls").is_file():
            raise CLIError(
                f"LaTeX template directory missing or incomplete (expected resume.cls): {resolved_template_dir}",
                code="template_not_found",
                extra={
                    "command": "render",
                    "input": str(file),
                    "output": str(output),
                    "template_dir": str(resolved_template_dir),
                    "warnings": warnings,
                },
            )

        if raw_data.get("templateType") == "html":
            warnings.append(
                "当前简历 templateType='html'：CLI 使用 LaTeX 模板渲染，与 Web HTML 模板视觉不等价"
            )

        backend_data = convert_to_backend_format(raw_data)
        photo_marker, local_photo_bytes = _resolve_cli_photo(
            backend_data.get("photo"),
            input_file=file,
            warnings=warnings,
        )
        if photo_marker is None:
            backend_data.pop("photo", None)
        else:
            backend_data["photo"] = photo_marker

        section_order = list(backend_data.get("sectionOrder") or [])

        try:
            with contextlib.redirect_stdout(sys.stderr):
                latex_content = json_to_latex(
                    backend_data,
                    section_order,
                    offline=offline,
                    warnings_out=warnings,
                )
                pdf_io = compile_latex_to_pdf(
                    latex_content,
                    resolved_template_dir,
                    resume_data=backend_data,
                    section_order=section_order,
                    offline=offline,
                    local_photo_bytes=local_photo_bytes,
                    warnings_out=warnings,
                )
            pdf_bytes = pdf_io.getvalue()
            if not pdf_bytes.startswith(b"%PDF-"):
                raise RuntimeError("Generated output is not a valid PDF document")
            _atomic_write_pdf(output, pdf_bytes)
        except Exception as exc:
            deduped_warnings = list(dict.fromkeys(warnings))
            raise CLIError(
                str(exc),
                code="render_failed",
                extra={
                    "command": "render",
                    "input": str(file),
                    "output": str(output),
                    "offline": offline,
                    "warnings": deduped_warnings,
                },
            ) from exc

        deduped_warnings = list(dict.fromkeys(warnings))
        if json_mode:
            emit_json(
                {
                    "ok": True,
                    "command": "render",
                    "input": str(file),
                    "output": str(output),
                    "bytes": len(pdf_bytes),
                    "offline": offline,
                    "warnings": deduped_warnings,
                },
                stream=stdout_stream,
            )
        else:
            for warn in deduped_warnings:
                sys.stderr.write(f"Warning: {warn}\n")
            sys.stderr.flush()
            stdout_stream.write(
                f"Rendered PDF to {output} ({len(pdf_bytes)} bytes, offline={offline})\n"
            )
            stdout_stream.flush()
