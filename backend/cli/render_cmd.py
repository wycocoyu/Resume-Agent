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

from backend.chrome_export import export_html_to_pdf
from backend.cli.errors import CLIError, emit_json
from backend.cli.schema import load_and_validate_resume_file
from backend.html_generator import generate_html_resume
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


def _atomic_write_bytes(output: Path, raw_bytes: bytes, *, prefix: str = ".resume_agent_out_") -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=prefix,
        suffix=".tmp",
        dir=str(output.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw_bytes)
            fh.flush()
        os.replace(tmp_path, output)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _import_fitz():
    try:
        import pymupdf as fitz_mod  # type: ignore[import-not-found]

        return fitz_mod
    except ImportError:
        try:
            import fitz as fitz_mod  # type: ignore[import-not-found]

            return fitz_mod
        except ImportError:
            return None


def render_pdf_bytes_to_pngs(
    pdf_bytes: bytes,
    output: Path,
    *,
    dpi: int = 150,
    single_primary: bool = True,
    force: bool = False,
) -> list[Path]:
    """Rasterize PDF pages into PNG preview files via PyMuPDF."""
    fitz_mod = _import_fitz()
    if fitz_mod is None:
        raise CLIError(
            "PyMuPDF is required to render PNG page previews.",
            code="pymupdf_not_found",
            extra={"command": "render", "output": str(output)},
        )

    scale = dpi / 72.0
    matrix = fitz_mod.Matrix(scale, scale)
    with fitz_mod.open(stream=pdf_bytes, filetype="pdf") as doc:
        if doc.page_count < 1:
            raise CLIError(
                "Rendered PDF contains 0 pages.",
                code="render_failed",
                extra={"command": "render", "output": str(output)},
            )
        png_pages = [
            doc[idx].get_pixmap(matrix=matrix, alpha=False).tobytes("png")
            for idx in range(doc.page_count)
        ]

    if single_primary and len(png_pages) == 1:
        _atomic_write_bytes(output, png_pages[0], prefix=".resume_agent_png_")
        return [output]

    sidecar_paths = [
        output.with_name(f"{output.stem}-page-{idx}.png")
        for idx in range(1, len(png_pages) + 1)
    ]
    if not force:
        for path in sidecar_paths:
            if path.exists():
                raise CLIError(
                    f"Target preview file already exists: {path} (use --force to overwrite)",
                    code="file_exists",
                    extra={"command": "render", "output": str(path)},
                )

    if single_primary:
        _atomic_write_bytes(output, png_pages[0], prefix=".resume_agent_png_")
    for path, page_bytes in zip(sidecar_paths, png_pages):
        _atomic_write_bytes(path, page_bytes, prefix=".resume_agent_png_")
    return sidecar_paths


def register_render_command(app: typer.Typer, get_output_context: Any) -> None:
    @app.command("render")
    def render_cmd(
        ctx: typer.Context,
        file: Path = typer.Argument(..., help="Path to validated ResumeData JSON file."),
        output: Path = typer.Option(
            ...,
            "-o",
            "--output",
            help="Output PDF, HTML, or PNG file path.",
        ),
        template: str = typer.Option(
            "default",
            "--template",
            help="Template name ('default', 'asu-tech', 'asu-01'..'asu-18').",
        ),
        engine: str | None = typer.Option(
            None,
            "--engine",
            help="Rendering engine ('latex' or 'html').",
        ),
        png: bool = typer.Option(
            False,
            "--png",
            "--images",
            help="Also emit per-page PNG preview images alongside output.",
        ),
        dpi: int = typer.Option(
            150,
            "--dpi",
            min=72,
            max=300,
            help="PNG preview resolution in DPI.",
        ),
        print_background: bool = typer.Option(
            True,
            "--print-background/--no-print-background",
            help="Print background graphics in Chrome CDP.",
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
            help="Overwrite target file if it already exists.",
        ),
        json_output: bool = typer.Option(
            False,
            "--json",
            help="Emit a single machine-readable JSON object on stdout.",
        ),
    ) -> None:
        """Render a ResumeData JSON file to PDF, HTML, or PNG via local XeLaTeX or Headless Chrome CDP."""
        json_mode, stdout_stream = get_output_context(ctx, json_output)
        offline = not online
        warnings: list[str] = []
        page_paths: list[Path] = []

        ext = output.suffix.lower()
        if ext not in {".pdf", ".html", ".png"}:
            raise CLIError(
                f"Unsupported output extension '{ext}': expected .pdf, .html, or .png",
                code="invalid_argument",
                extra={"command": "render", "input": str(file), "output": str(output)},
            )

        if output.exists() and not force:
            raise CLIError(
                f"Target file already exists: {output} (use --force to overwrite)",
                code="file_exists",
                extra={"command": "render", "input": str(file), "output": str(output), "warnings": warnings},
            )
        if png and ext != ".png":
            first_sidecar = output.with_name(f"{output.stem}-page-1.png")
            if first_sidecar.exists() and not force:
                raise CLIError(
                    f"Target preview file already exists: {first_sidecar} (use --force to overwrite)",
                    code="file_exists",
                    extra={"command": "render", "input": str(file), "output": str(first_sidecar), "warnings": warnings},
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

        # Resolve engine
        html_templates = {"asu-tech", "html-classic"} | {f"asu-{i:02d}" for i in range(1, 19)}
        if ext == ".html":
            if engine == "latex":
                raise CLIError(
                    "Cannot render HTML output using LaTeX engine. Use --engine html or omit --engine.",
                    code="engine_mismatch",
                    extra={"command": "render", "input": str(file), "output": str(output)},
                )
            resolved_engine = "html"
        else:
            if engine is not None:
                eng_lower = engine.lower()
                if eng_lower not in {"latex", "html"}:
                    raise CLIError(
                        f"Invalid engine '{engine}': expected 'latex' or 'html'.",
                        code="invalid_engine",
                        extra={"command": "render", "input": str(file), "output": str(output)},
                    )
                resolved_engine = eng_lower
            else:
                if template in html_templates:
                    resolved_engine = "html"
                else:
                    resolved_engine = "latex"

        if resolved_engine == "html":
            try:
                html_content = generate_html_resume(
                    raw_data,
                    template=template,
                    print_background=print_background,
                )
                if ext == ".html":
                    html_bytes = html_content.encode("utf-8")
                    _atomic_write_bytes(output, html_bytes, prefix=".resume_agent_html_")
                    result_bytes = len(html_bytes)
                    if png:
                        with tempfile.TemporaryDirectory() as tmp_dir:
                            pdf_bytes = export_html_to_pdf(
                                html_content,
                                output_path=Path(tmp_dir) / "preview.pdf",
                                print_background=print_background,
                            )
                        page_paths = render_pdf_bytes_to_pngs(
                            pdf_bytes, output, dpi=dpi, single_primary=False, force=force
                        )
                elif ext == ".pdf":
                    pdf_bytes = export_html_to_pdf(
                        html_content,
                        output_path=output,
                        print_background=print_background,
                    )
                    result_bytes = len(pdf_bytes)
                    if png:
                        page_paths = render_pdf_bytes_to_pngs(
                            pdf_bytes, output, dpi=dpi, single_primary=False, force=force
                        )
                else:
                    with tempfile.TemporaryDirectory() as tmp_dir:
                        pdf_bytes = export_html_to_pdf(
                            html_content,
                            output_path=Path(tmp_dir) / "preview.pdf",
                            print_background=print_background,
                        )
                    page_paths = render_pdf_bytes_to_pngs(
                        pdf_bytes, output, dpi=dpi, single_primary=True, force=force
                    )
                    result_bytes = output.stat().st_size
            except CLIError:
                raise
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
        else:
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
                if ext == ".pdf":
                    _atomic_write_bytes(output, pdf_bytes, prefix=".resume_agent_pdf_")
                    result_bytes = len(pdf_bytes)
                    if png:
                        page_paths = render_pdf_bytes_to_pngs(
                            pdf_bytes, output, dpi=dpi, single_primary=False, force=force
                        )
                else:
                    page_paths = render_pdf_bytes_to_pngs(
                        pdf_bytes, output, dpi=dpi, single_primary=True, force=force
                    )
                    result_bytes = output.stat().st_size
            except CLIError:
                raise
            except Exception as exc:
                deduped_warnings = list(dict.fromkeys(warnings))
                extra: dict[str, Any] = {
                    "command": "render",
                    "input": str(file),
                    "output": str(output),
                    "offline": offline,
                    "warnings": deduped_warnings,
                }
                if "xelatex" in str(exc).lower():
                    extra["fallback_hint"] = (
                        "Local XeLaTeX is unavailable. Use '--template asu-tech' for local HTML/Chrome rendering "
                        "or run 'cococv handoff <file>' for Web cloud LaTeX rendering."
                    )
                raise CLIError(
                    str(exc),
                    code="render_failed",
                    extra=extra,
                ) from exc

        deduped_warnings = list(dict.fromkeys(warnings))
        if json_mode:
            payload: dict[str, Any] = {
                "ok": True,
                "command": "render",
                "input": str(file),
                "output": str(output),
                "engine": resolved_engine,
                "template": template,
                "bytes": result_bytes,
                "offline": offline,
                "warnings": deduped_warnings,
            }
            if page_paths:
                payload["pages"] = [str(p) for p in page_paths]
                payload["page_count"] = len(page_paths)
            emit_json(payload, stream=stdout_stream)
        else:
            for warn in deduped_warnings:
                sys.stderr.write(f"Warning: {warn}\n")
            sys.stderr.flush()
            stdout_stream.write(
                f"Rendered {output.suffix[1:].upper()} to {output} ({result_bytes} bytes, engine={resolved_engine}, offline={offline})\n"
            )
            if page_paths:
                stdout_stream.write(f"PNG previews ({len(page_paths)}): {', '.join(str(p) for p in page_paths)}\n")
            stdout_stream.flush()
