"""Resume-Agent CLI entrypoint and core subcommands (init, schema, validate)."""
from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import Any, Sequence, TextIO

import click
import typer

from backend.cli.errors import CLIError, emit_json, has_json_flag
from backend.cli.schema import (
    build_initial_resume,
    get_resume_json_schema,
    load_and_validate_resume_file,
)

app = typer.Typer(
    name="resume-agent",
    help="Resume-Agent deterministic CLI for skeleton init, validation, offline PDF rendering, and Web sync.",
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


def get_output_context(ctx: typer.Context, local_json: bool = False) -> tuple[bool, TextIO]:
    state: dict[str, Any] = ctx.ensure_object(dict)
    json_mode = bool(state.get("json_mode") or local_json)
    stdout_stream: TextIO = state.get("stdout") or sys.stdout
    return json_mode, stdout_stream


@app.callback()
def root_callback(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit a single machine-readable JSON object on stdout.",
    ),
) -> None:
    state = ctx.ensure_object(dict)
    if json_output:
        state["json_mode"] = True


@app.command("init")
def init_cmd(
    ctx: typer.Context,
    output: Path = typer.Option(
        Path("resume.json"),
        "-o",
        "--output",
        help="Path to write the initialized ResumeData JSON file.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite target file if it already exists.",
    ),
    title: str = typer.Option(
        "我的简历",
        "--title",
        help="Initial resume title.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit a single machine-readable JSON object on stdout.",
    ),
) -> None:
    """Generate a clean Workspace v2 ResumeData JSON skeleton."""
    json_mode, stdout_stream = get_output_context(ctx, json_output)
    if not title.strip():
        raise CLIError("Title must not be empty.", code="invalid_title")

    if output.exists() and not force:
        raise CLIError(
            f"Target file already exists: {output} (use --force to overwrite)",
            code="file_exists",
            extra={"command": "init", "output": str(output)},
        )

    skeleton = build_initial_resume(title=title)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(skeleton, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise CLIError(
            f"Failed to write resume skeleton to {output}: {exc}",
            code="write_error",
            extra={"command": "init", "output": str(output)},
        ) from exc

    if json_mode:
        emit_json(
            {
                "ok": True,
                "command": "init",
                "output": str(output),
                "id": skeleton["id"],
                "title": skeleton["title"],
            },
            stream=stdout_stream,
        )
    else:
        stdout_stream.write(f"Initialized resume skeleton at {output} (id={skeleton['id']})\n")
        stdout_stream.flush()


@app.command("schema")
def schema_cmd(
    ctx: typer.Context,
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit a single machine-readable JSON Schema object on stdout.",
    ),
) -> None:
    """Export authoritative ResumeData JSON Schema with x-field-conventions."""
    _, stdout_stream = get_output_context(ctx, json_output)
    schema_obj = get_resume_json_schema()
    emit_json(schema_obj, stream=stdout_stream)


@app.command("validate")
def validate_cmd(
    ctx: typer.Context,
    file: Path = typer.Argument(..., help="Path to ResumeData JSON file to validate (read-only)."),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit a single machine-readable JSON object on stdout.",
    ),
) -> None:
    """Strictly validate a ResumeData JSON file without modifying it."""
    json_mode, stdout_stream = get_output_context(ctx, json_output)
    _, model, issues, io_or_syntax_err = load_and_validate_resume_file(file)

    if io_or_syntax_err and not issues:
        raise CLIError(
            io_or_syntax_err,
            code="file_error",
            extra={
                "command": "validate",
                "valid": False,
                "file": str(file),
                "errors": [],
            },
        )

    if issues:
        error_dicts = [issue.to_dict() for issue in issues]
        code = "invalid_json" if io_or_syntax_err else "validation_failed"
        summary = (
            io_or_syntax_err
            if io_or_syntax_err
            else f"Validation failed with {len(error_dicts)} error(s) in {file}"
        )
        raise CLIError(
            summary,
            code=code,
            extra={
                "command": "validate",
                "valid": False,
                "file": str(file),
                "errors": error_dicts,
            },
        )

    assert model is not None
    if json_mode:
        emit_json(
            {
                "ok": True,
                "command": "validate",
                "valid": True,
                "file": str(file),
                "id": model.id,
                "errors": [],
            },
            stream=stdout_stream,
        )
    else:
        stdout_stream.write(f"Valid ResumeData: {file} (id={model.id})\n")
        stdout_stream.flush()


from backend.cli.render_cmd import register_render_command
from backend.cli.sync_cmd import register_sync_commands

register_render_command(app, get_output_context)
register_sync_commands(app, get_output_context)


_typer_click = getattr(typer, "_click", click)
_NO_ARGS_EXC = tuple({click.exceptions.NoArgsIsHelpError, _typer_click.exceptions.NoArgsIsHelpError})
_USAGE_EXC = tuple({click.UsageError, _typer_click.exceptions.UsageError})
_CLICK_EXC = tuple({click.ClickException, _typer_click.exceptions.ClickException})
_EXIT_EXC = tuple({click.exceptions.Exit, _typer_click.exceptions.Exit, typer.Exit})
_ABORT_EXC = tuple({click.exceptions.Abort, _typer_click.exceptions.Abort, typer.Abort})


def run_cli(argv: Sequence[str] | None = None) -> int:
    """Execute CLI with deterministic exit codes (0=ok, 1=runtime/business, 2=usage) and pure --json stdout."""
    args = list(argv) if argv is not None else sys.argv[1:]
    json_mode = has_json_flag(args)
    real_stdout = sys.stdout
    ctx_obj = {"json_mode": json_mode, "stdout": real_stdout}

    redirect_ctx = (
        contextlib.redirect_stdout(sys.stderr)
        if json_mode
        else contextlib.nullcontext()
    )

    try:
        with redirect_ctx:
            app(args=args, prog_name="resume-agent", standalone_mode=False, obj=ctx_obj)
        return 0
    except CLIError as exc:
        if json_mode:
            payload: dict[str, Any] = {"ok": False}
            payload.update(exc.extra)
            payload["error"] = {"code": exc.code, "message": exc.message}
            emit_json(payload, stream=real_stdout)
        else:
            sys.stderr.write(f"Error: {exc.message}\n")
            for item in exc.extra.get("errors") or []:
                if isinstance(item, dict) and "path" in item and "message" in item:
                    sys.stderr.write(f"  - {item['path']}: {item['message']}\n")
            sys.stderr.flush()
        return exc.exit_code
    except _NO_ARGS_EXC:
        if json_mode:
            emit_json(
                {
                    "ok": False,
                    "error": {
                        "code": "usage_error",
                        "message": "Missing command.",
                    },
                },
                stream=real_stdout,
            )
            return 2
        return 0
    except _CLICK_EXC as exc:
        exit_code = 2 if isinstance(exc, _USAGE_EXC) else (getattr(exc, "exit_code", 1) or 1)
        if json_mode:
            emit_json(
                {
                    "ok": False,
                    "error": {
                        "code": "usage_error" if exit_code == 2 else "cli_error",
                        "message": exc.format_message(),
                    },
                },
                stream=real_stdout,
            )
        else:
            exc.show(file=sys.stderr)
        return exit_code
    except _EXIT_EXC as exc:
        return int(getattr(exc, "exit_code", 0))
    except _ABORT_EXC:
        if json_mode:
            emit_json(
                {"ok": False, "error": {"code": "aborted", "message": "Aborted"}},
                stream=real_stdout,
            )
        else:
            sys.stderr.write("Aborted!\n")
            sys.stderr.flush()
        return 1
    except Exception as exc:  # pragma: no cover - unexpected crash safeguard
        if json_mode:
            emit_json(
                {
                    "ok": False,
                    "error": {"code": "internal_error", "message": str(exc)},
                },
                stream=real_stdout,
            )
        else:
            sys.stderr.write(f"Internal error: {exc}\n")
            sys.stderr.flush()
        return 1


def main() -> None:
    raise SystemExit(run_cli())
