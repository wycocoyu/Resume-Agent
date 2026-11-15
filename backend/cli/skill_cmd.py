"""``resume-agent skill`` subcommands: build, path, install, status, uninstall."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import typer

from backend.cli.errors import CLIError, emit_json
from backend.skillkit import render as render_mod
from backend.skillkit.adapters import AdapterError, load_adapters
from backend.skillkit.docs import SkillRenderError
from backend.skillkit.install import (
    candidate_paths,
    cli_version,
    install as install_skill,
    resolve_target,
    status_entries,
    uninstall as uninstall_skill,
)

skill_app = typer.Typer(
    name="skill",
    help="Render, install and inspect the Resume-Agent skill for each AI harness.",
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

_KNOWN_ERRORS = (SkillRenderError, AdapterError)


def _fail(exc: Exception, command: str) -> "CLIError":
    return CLIError(str(exc), code="skill_error", extra={"command": command, "ok": False})


def _adapters():
    return load_adapters(render_mod.templates_root())


def _scope_value(scope: str) -> str:
    if scope not in {"user", "project"}:
        raise CLIError(
            f"Invalid scope '{scope}': expected 'user' or 'project'.",
            code="invalid_scope",
            extra={"command": "skill", "ok": False},
        )
    return scope


def _layout_value(layout: str) -> str:
    if layout not in {"nested", "flat"}:
        raise CLIError(
            f"Invalid layout '{layout}': expected 'nested' or 'flat'.",
            code="invalid_layout",
            extra={"command": "skill", "ok": False},
        )
    return layout


def register_skill_commands(app: typer.Typer, get_output_context: Callable[..., Any]) -> None:
    @skill_app.command("list")
    def list_cmd(
        ctx: typer.Context,
        json_output: bool = typer.Option(
            False, "--json", help="Emit a single machine-readable JSON object on stdout."
        ),
    ) -> None:
        """List supported harnesses and their discovery paths."""
        json_mode, stdout = get_output_context(ctx, json_output)
        try:
            adapters = _adapters()
        except _KNOWN_ERRORS as exc:
            raise _fail(exc, "skill.list") from exc

        items = [
            {
                "id": adapter.id,
                "display_name": adapter.display_name,
                "status": adapter.status,
                "invoke_syntax": adapter.invoke_syntax,
                "user_paths": [str(p) for p in candidate_paths(adapter, "user")],
                "project_paths": [str(p) for p in candidate_paths(adapter, "project")],
                "notes": adapter.notes,
            }
            for adapter in (adapters[key] for key in sorted(adapters))
        ]
        if json_mode:
            emit_json(
                {"ok": True, "command": "skill.list", "cli_version": cli_version(), "harnesses": items},
                stream=stdout,
            )
            return
        stdout.write(f"resume-agent {cli_version()} supports {len(items)} harness(es):\n")
        for item in items:
            paths = ", ".join(item["user_paths"]) or "(none; pass --path)"
            stdout.write(f"  - {item['id']:<10} {item['status']:<12} {item['invoke_syntax']:<14} {paths}\n")
            if item["notes"]:
                stdout.write(f"      note: {item['notes']}\n")
        stdout.flush()

    @skill_app.command("build")
    def build_cmd(
        ctx: typer.Context,
        harness: str = typer.Option("all", "--harness", help="Harness id or 'all'."),
        out: Path = typer.Option(Path("dist/skills"), "--out", help="Output directory."),
        layout: str = typer.Option(
            "nested",
            "--layout",
            help="'nested' writes <out>/<harness>/<skill>/; 'flat' writes <out>/<skill>/.",
        ),
        check: bool = typer.Option(
            False, "--check", help="Do not write; fail when the output tree is out of date."
        ),
        json_output: bool = typer.Option(
            False, "--json", help="Emit a single machine-readable JSON object on stdout."
        ),
    ) -> None:
        """Render the shared core into each harness's skill directory."""
        json_mode, stdout = get_output_context(ctx, json_output)
        try:
            adapters = _adapters()
            layout = _layout_value(layout)
            selected = render_mod.select_adapters(adapters, harness)
            skill_name = render_mod.load_descriptions(render_mod.templates_root())["name"]
        except _KNOWN_ERRORS as exc:
            raise _fail(exc, "skill.build") from exc

        reports: list[dict[str, Any]] = []
        stale = False
        for adapter in selected:
            target = render_mod.skill_dir_for(adapter.id, out, layout, skill_name)
            try:
                files = render_mod.render_harness(adapter)
            except _KNOWN_ERRORS as exc:
                raise _fail(exc, "skill.build") from exc
            if check:
                diff = render_mod.compare_tree(files, target)
                out_of_sync = bool(diff["missing"] or diff["stale"] or diff["extra"])
                stale = stale or out_of_sync
                reports.append(
                    {
                        "harness": adapter.id,
                        "target": str(target),
                        "in_sync": not out_of_sync,
                        **diff,
                    }
                )
            else:
                written = render_mod.write_tree(files, target)
                reports.append(
                    {
                        "harness": adapter.id,
                        "target": str(target),
                        "in_sync": True,
                        "files": written,
                        "missing": [],
                        "stale": [],
                        "extra": [],
                    }
                )

        if check and stale:
            raise CLIError(
                "Generated skill artifacts are out of date. Run `resume-agent skill build` "
                "and commit the result.",
                code="skill_out_of_sync",
                extra={
                    "command": "skill.build",
                    "check": True,
                    "harnesses": reports,
                },
            )

        if json_mode:
            emit_json(
                {
                    "ok": True,
                    "command": "skill.build",
                    "check": check,
                    "layout": layout,
                    "out": str(out),
                    "harnesses": reports,
                },
                stream=stdout,
            )
            return
        verb = "checked" if check else "wrote"
        for report in reports:
            stdout.write(f"{verb} {report['harness']} -> {report['target']}\n")
        stdout.flush()

    @skill_app.command("path")
    def path_cmd(
        ctx: typer.Context,
        harness: str = typer.Option(..., "--harness", help="Harness id."),
        scope: str = typer.Option("user", "--scope", help="'user' or 'project'."),
        target: str = typer.Option(
            None, "--path", help="Explicit skill directory (overrides adapter discovery paths)."
        ),
        json_output: bool = typer.Option(
            False, "--json", help="Emit a single machine-readable JSON object on stdout."
        ),
    ) -> None:
        """Show where a harness skill is discovered and where it would be installed."""
        json_mode, stdout = get_output_context(ctx, json_output)
        try:
            adapters = _adapters()
            scope = _scope_value(scope)
            adapter = render_mod.select_adapters(adapters, harness)[0]
            resolved = resolve_target(adapter, scope, target)
            candidates = [str(p / adapter.name) for p in candidate_paths(adapter, scope)]
        except _KNOWN_ERRORS as exc:
            raise _fail(exc, "skill.path") from exc

        payload = {
            "ok": True,
            "command": "skill.path",
            "harness": adapter.id,
            "status": adapter.status,
            "scope": scope,
            "target": str(resolved),
            "exists": resolved.exists(),
            "candidates": candidates,
            "invoke_syntax": adapter.invoke_syntax,
        }
        if json_mode:
            emit_json(payload, stream=stdout)
            return
        stdout.write(f"harness:  {adapter.id} ({adapter.status})\n")
        stdout.write(f"scope:    {scope}\n")
        stdout.write(f"target:   {resolved}\n")
        stdout.write(f"exists:   {payload['exists']}\n")
        if candidates:
            stdout.write(f"detected: {', '.join(candidates)}\n")
        stdout.flush()

    @skill_app.command("install")
    def install_cmd(
        ctx: typer.Context,
        harness: str = typer.Option(..., "--harness", help="Harness id."),
        scope: str = typer.Option("user", "--scope", help="'user' or 'project'."),
        target: str = typer.Option(None, "--path", help="Explicit destination skill directory."),
        strategy: str = typer.Option(None, "--strategy", help="'copy' or 'link'."),
        force: bool = typer.Option(
            False, "--force", help="Take ownership of a directory not created by resume-agent."
        ),
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Report the plan without writing anything."
        ),
        json_output: bool = typer.Option(
            False, "--json", help="Emit a single machine-readable JSON object on stdout."
        ),
    ) -> None:
        """Install the generated skill into a harness discovery directory."""
        json_mode, stdout = get_output_context(ctx, json_output)
        try:
            adapters = _adapters()
            scope = _scope_value(scope)
            adapter = render_mod.select_adapters(adapters, harness)[0]
            result = install_skill(
                adapter,
                scope=scope,
                target_override=target,
                strategy=strategy,
                force=force,
                dry_run=dry_run,
            )
        except _KNOWN_ERRORS as exc:
            raise _fail(exc, "skill.install") from exc

        if json_mode:
            emit_json(result, stream=stdout)
            return
        prefix = "would install" if result.get("dry_run") else "installed"
        stdout.write(f"{prefix} {result['harness']} -> {result['target']} ({result['strategy']})\n")
        for rel in result["files"]:
            stdout.write(f"  {rel}\n")
        if result.get("alternates"):
            stdout.write(f"alternate discovery paths: {', '.join(result['alternates'])}\n")
        stdout.flush()

    @skill_app.command("status")
    def status_cmd(
        ctx: typer.Context,
        harness: str = typer.Option(None, "--harness", help="Filter by harness id."),
        json_output: bool = typer.Option(
            False, "--json", help="Emit a single machine-readable JSON object on stdout."
        ),
    ) -> None:
        """Report recorded installs, drift and CLI/skill version skew (read-only)."""
        json_mode, stdout = get_output_context(ctx, json_output)
        reports = status_entries()
        if harness:
            reports = [r for r in reports if r["harness"] == harness]
        if json_mode:
            emit_json(
                {
                    "ok": True,
                    "command": "skill.status",
                    "cli_version": cli_version(),
                    "installs": reports,
                },
                stream=stdout,
            )
            return
        if not reports:
            stdout.write("No recorded skill installs.\n")
            stdout.flush()
            return
        for report in reports:
            stdout.write(
                f"{report['harness']:<10} {report['state']:<12} {report['target']} "
                f"(installed {report['installed_version']}, current {report['current_version']})\n"
            )
            if report["modified"]:
                stdout.write(f"    modified by user: {', '.join(report['modified'])}\n")
            if report["missing"]:
                stdout.write(f"    missing: {', '.join(report['missing'])}\n")
        stdout.flush()

    @skill_app.command("uninstall")
    def uninstall_cmd(
        ctx: typer.Context,
        harness: str = typer.Option(..., "--harness", help="Harness id."),
        target: str = typer.Option(None, "--path", help="Restrict to one installed target."),
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Report what would be removed without deleting."
        ),
        json_output: bool = typer.Option(
            False, "--json", help="Emit a single machine-readable JSON object on stdout."
        ),
    ) -> None:
        """Remove only files this installer created and the user never edited."""
        json_mode, stdout = get_output_context(ctx, json_output)
        try:
            result = uninstall_skill(harness, dry_run=dry_run, target_override=target)
        except _KNOWN_ERRORS as exc:
            raise _fail(exc, "skill.uninstall") from exc

        if json_mode:
            emit_json(result, stream=stdout)
            return
        prefix = "would remove" if result["dry_run"] else "removed"
        for path in result["removed"]:
            stdout.write(f"{prefix} {path}\n")
        for path in result["kept"]:
            stdout.write(f"kept (modified by user) {path}\n")
        stdout.flush()

    app.add_typer(skill_app, name="skill")
