"""CLI `handoff` subcommand: opt-in short-lived Web share link for browser continuation & cloud LaTeX."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import typer

from backend.cli.errors import CLIError, emit_json
from backend.cli.schema import load_and_validate_resume_file

DEFAULT_WEB_API_URL = "https://cococv.cn"
_HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=5.0)

# Test seam: optional custom transport (None in normal CLI execution -> real network with trust_env=False)
_custom_httpx_transport: httpx.BaseTransport | None = None


def normalize_share_api_url(api_url: str | None) -> str:
    """Normalize direct FastAPI or Next.js proxy base URL to the /api/resume/share endpoint."""
    raw = (api_url or os.getenv("RESUME_AGENT_API_URL") or DEFAULT_WEB_API_URL).strip().rstrip("/")
    if not (raw.startswith("http://") or raw.startswith("https://")):
        raise CLIError(
            f"Invalid API base URL '{raw}': must start with http:// or https://",
            code="invalid_api_url",
        )
    if raw.endswith("/api/resume/share"):
        return raw
    if raw.endswith("/api/fastapi/proxy/resume/share"):
        return raw
    if raw.endswith("/api/fastapi/proxy/api/resume/share"):
        return raw[: -len("/api/resume/share")] + "/resume/share"
    if raw.endswith("/api/fastapi/proxy"):
        return f"{raw}/resume/share"
    if raw.endswith("/api/resume"):
        return f"{raw}/share"
    if raw.endswith("/api"):
        return f"{raw}/resume/share"
    return f"{raw}/api/resume/share"


def register_handoff_command(app: typer.Typer, get_output_context: Any) -> None:
    @app.command("handoff")
    def handoff_cmd(
        ctx: typer.Context,
        file: Path = typer.Argument(..., help="Path to validated ResumeData JSON file."),
        api_url: str | None = typer.Option(
            None,
            "--api-url",
            help="Target CocoCV server base URL (defaults to RESUME_AGENT_API_URL or https://cococv.cn).",
        ),
        name: str | None = typer.Option(
            None,
            "--name",
            help="Display name for the temporary Web draft (defaults to basic.name or title).",
        ),
        ttl_minutes: int = typer.Option(
            60,
            "--ttl-minutes",
            min=1,
            max=10080,
            help="Expiration window in minutes for the temporary Web continuation link (default: 60).",
        ),
        json_output: bool = typer.Option(
            False,
            "--json",
            help="Emit a single machine-readable JSON object on stdout.",
        ),
    ) -> None:
        """Upload a validated local resume as a short-lived Web handoff draft (explicit opt-in)."""
        json_mode, stdout_stream = get_output_context(ctx, json_output)

        raw_data, _, issues, io_or_syntax_err = load_and_validate_resume_file(file)
        if io_or_syntax_err and not issues:
            raise CLIError(
                io_or_syntax_err,
                code="file_error",
                extra={"command": "handoff", "file": str(file)},
            )
        if issues:
            raise CLIError(
                io_or_syntax_err or f"Validation failed with {len(issues)} error(s) in {file}",
                code="invalid_json" if io_or_syntax_err else "validation_failed",
                extra={
                    "command": "handoff",
                    "file": str(file),
                    "errors": [item.to_dict() for item in issues],
                },
            )

        assert raw_data is not None
        endpoint = normalize_share_api_url(api_url)
        basic_name = str((raw_data.get("basic") or {}).get("name") or "").strip()
        title_name = str(raw_data.get("title") or "").strip()
        resolved_name = (name.strip() if name is not None else "") or basic_name or title_name or "未命名简历"

        req_body = {
            "resume_data": raw_data,
            "resume_name": resolved_name,
            "expire_minutes": ttl_minutes,
        }

        try:
            with httpx.Client(
                trust_env=False,
                timeout=_HTTP_TIMEOUT,
                transport=_custom_httpx_transport,
            ) as client:
                resp = client.post(endpoint, json=req_body)
        except httpx.RequestError as exc:
            raise CLIError(
                f"Network error contacting {endpoint}: {exc}",
                code="network_error",
                extra={"command": "handoff", "file": str(file)},
            ) from exc

        if resp.status_code >= 400:
            detail = f"HTTP {resp.status_code}"
            try:
                err_payload = resp.json()
                if isinstance(err_payload, dict) and err_payload.get("detail"):
                    detail = str(err_payload["detail"])
            except Exception:
                if resp.text.strip():
                    detail = resp.text.strip()
            raise CLIError(
                f"HTTP {resp.status_code}: {detail}",
                code=f"http_{resp.status_code}",
                extra={"command": "handoff", "status_code": resp.status_code, "detail": detail},
            )

        try:
            body = resp.json()
        except ValueError as exc:
            raise CLIError(
                "Remote endpoint returned non-JSON content (check --api-url).",
                code="invalid_remote_payload",
                extra={"command": "handoff", "status_code": resp.status_code},
            ) from exc

        if not isinstance(body, dict) or not body.get("share_url"):
            raise CLIError(
                "Remote endpoint response is missing 'share_url'.",
                code="invalid_remote_payload",
                extra={"command": "handoff", "status_code": resp.status_code},
            )

        if json_mode:
            emit_json(
                {
                    "ok": True,
                    "command": "handoff",
                    "share_id": body.get("share_id"),
                    "share_url": body.get("share_url"),
                    "expires_at": body.get("expires_at"),
                    "ttl_minutes": ttl_minutes,
                },
                stream=stdout_stream,
            )
        else:
            stdout_stream.write(
                f"Web handoff URL (expires in {ttl_minutes} min): {body['share_url']}\n"
                "Open it in your browser to continue editing or log in to compile LaTeX PDF / save to cloud.\n"
            )
            stdout_stream.flush()
