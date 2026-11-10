"""CLI `sync` subcommand group: explicit one-way Web workspace sync (list / pull / push)."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

import httpx
import typer

from backend.cli.errors import CLIError, emit_json
from backend.cli.schema import load_and_validate_resume_file

DEFAULT_API_URL = "http://127.0.0.1:9000"
_HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=5.0)

# Test seam: optional custom transport (None in normal CLI execution -> real network with trust_env=False)
_custom_httpx_transport: httpx.BaseTransport | None = None


def normalize_resumes_api_base(api_url: str | None) -> str:
    """Normalize direct FastAPI (/api/resumes) and Next.js proxy (/api/fastapi/proxy/resumes) URLs."""
    raw = (api_url or os.getenv("RESUME_AGENT_API_URL") or DEFAULT_API_URL).strip().rstrip("/")
    if not (raw.startswith("http://") or raw.startswith("https://")):
        raise CLIError(
            f"Invalid API base URL '{raw}': must start with http:// or https://",
            code="invalid_api_url",
        )
    if raw.endswith("/api/fastapi/proxy/resumes"):
        return raw
    if raw.endswith("/api/fastapi/proxy/api/resumes"):
        return raw[: -len("/api/resumes")] + "/resumes"
    if raw.endswith("/api/fastapi/proxy/api"):
        return raw[: -len("/api")] + "/resumes"
    if raw.endswith("/api/fastapi/proxy"):
        return f"{raw}/resumes"
    if raw.endswith("/api/resumes"):
        return raw
    if raw.endswith("/api"):
        return f"{raw}/resumes"
    return f"{raw}/api/resumes"


def build_auth_headers(
    *,
    token: str | None = None,
    internal_secret: str | None = None,
    user_id: str | None = None,
    user_email: str | None = None,
    user_name: str | None = None,
) -> dict[str, str]:
    """Build request auth headers with strict isolation:
    - When --token or RESUME_AGENT_TOKEN is supplied, send ONLY Authorization: Bearer <token>
      (excluding FASTAPI_INTERNAL_AUTH_SECRET so internal headers never shadow Bearer auth).
      Explicit empty/whitespace --token or RESUME_AGENT_TOKEN raises CLIError rather than
      falling back to internal trusted headers.
    - Otherwise, send Trusted Headers iff BOTH secret and user_id are non-empty.
    """
    if token is not None:
        resolved_token = token.strip()
        if not resolved_token:
            raise CLIError(
                "--token must not be empty when provided.",
                code="invalid_token",
            )
        return {"Authorization": f"Bearer {resolved_token}"}

    env_token_raw = os.getenv("RESUME_AGENT_TOKEN")
    if env_token_raw is not None:
        resolved_env_token = env_token_raw.strip()
        if not resolved_env_token:
            raise CLIError(
                "RESUME_AGENT_TOKEN must not be empty when set.",
                code="invalid_token",
            )
        return {"Authorization": f"Bearer {resolved_env_token}"}

    resolved_secret = (
        internal_secret
        if internal_secret is not None
        else (os.getenv("FASTAPI_INTERNAL_AUTH_SECRET") or "")
    ).strip()
    resolved_user_id = (
        user_id
        if user_id is not None
        else (os.getenv("RESUME_AGENT_USER_ID") or os.getenv("BETTER_AUTH_USER_ID") or "")
    ).strip()

    if resolved_secret and resolved_user_id:
        headers: dict[str, str] = {
            "X-Internal-Auth-Secret": resolved_secret,
            "X-Better-Auth-User-Id": resolved_user_id,
        }
        resolved_email = (
            user_email
            if user_email is not None
            else (os.getenv("RESUME_AGENT_USER_EMAIL") or "")
        ).strip()
        resolved_name = (
            user_name
            if user_name is not None
            else (os.getenv("RESUME_AGENT_USER_NAME") or "")
        ).strip()
        if resolved_email:
            headers["X-Better-Auth-User-Email"] = resolved_email
        if resolved_name:
            headers["X-Better-Auth-User-Name"] = resolved_name
        return headers

    return {}


def _open_http_client() -> httpx.Client:
    return httpx.Client(
        trust_env=False,
        timeout=_HTTP_TIMEOUT,
        transport=_custom_httpx_transport,
    )


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict) and payload.get("detail"):
            return str(payload["detail"])
    except Exception:
        pass
    text = response.text.strip()
    return text or f"HTTP {response.status_code}"


def _raise_for_http_error(response: httpx.Response, *, command: str) -> None:
    if response.status_code < 400:
        return
    detail = _extract_error_detail(response)
    raise CLIError(
        f"HTTP {response.status_code}: {detail}",
        code=f"http_{response.status_code}",
        extra={
            "command": command,
            "status_code": response.status_code,
            "detail": detail,
        },
    )


def _parse_json_object(response: httpx.Response, *, command: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise CLIError(
            "Remote endpoint returned non-JSON content (check --api-url).",
            code="invalid_remote_payload",
            extra={"command": command, "status_code": response.status_code},
        ) from exc
    if not isinstance(payload, dict):
        raise CLIError(
            "Remote endpoint returned an unexpected JSON shape (expected object).",
            code="invalid_remote_payload",
            extra={"command": command, "status_code": response.status_code},
        )
    return payload


def _atomic_write_json(output: Path, payload: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=".resume_agent_pull_",
        suffix=".tmp",
        dir=str(output.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
        os.replace(tmp_path, output)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _merge_sync_opts(
    ctx: typer.Context,
    *,
    api_url: str | None,
    token: str | None,
    internal_secret: str | None,
    user_id: str | None,
    user_email: str | None,
    user_name: str | None,
) -> tuple[str, dict[str, str]]:
    state: dict[str, Any] = ctx.ensure_object(dict)
    sync_cfg: dict[str, Any] = state.get("sync_opts") or {}
    eff_api_url = api_url if api_url is not None else sync_cfg.get("api_url")
    eff_token = token if token is not None else sync_cfg.get("token")
    eff_secret = internal_secret if internal_secret is not None else sync_cfg.get("internal_secret")
    eff_user_id = user_id if user_id is not None else sync_cfg.get("user_id")
    eff_email = user_email if user_email is not None else sync_cfg.get("user_email")
    eff_name = user_name if user_name is not None else sync_cfg.get("user_name")

    base = normalize_resumes_api_base(eff_api_url)
    headers = build_auth_headers(
        token=eff_token,
        internal_secret=eff_secret,
        user_id=eff_user_id,
        user_email=eff_email,
        user_name=eff_name,
    )
    return base, headers


def register_sync_commands(app: typer.Typer, get_output_context: Any) -> None:
    sync_app = typer.Typer(
        name="sync",
        help="Explicit one-way synchronization with Resume-Agent Web workspace (list / pull / push).",
        no_args_is_help=True,
    )

    @sync_app.callback()
    def sync_callback(
        ctx: typer.Context,
        api_url: str | None = typer.Option(None, "--api-url", help="Web/FastAPI base URL."),
        token: str | None = typer.Option(None, "--token", help="BetterAuth Bearer session token."),
        internal_secret: str | None = typer.Option(None, "--internal-secret", help="Local trusted internal secret."),
        user_id: str | None = typer.Option(None, "--user-id", help="BetterAuth user ID (for local trusted headers)."),
        user_email: str | None = typer.Option(None, "--user-email", help="Optional user email for trusted headers."),
        user_name: str | None = typer.Option(None, "--user-name", help="Optional user name for trusted headers."),
        json_output: bool = typer.Option(False, "--json", help="Emit a single machine-readable JSON object on stdout."),
    ) -> None:
        state = ctx.ensure_object(dict)
        if json_output:
            state["json_mode"] = True
        state["sync_opts"] = {
            "api_url": api_url,
            "token": token,
            "internal_secret": internal_secret,
            "user_id": user_id,
            "user_email": user_email,
            "user_name": user_name,
        }

    @sync_app.command("list")
    def sync_list_cmd(
        ctx: typer.Context,
        offset: int = typer.Option(0, "--offset", min=0, help="Pagination offset."),
        limit: int = typer.Option(50, "--limit", min=1, max=50, help="Page size (1..50)."),
        api_url: str | None = typer.Option(None, "--api-url", help="Web/FastAPI base URL."),
        token: str | None = typer.Option(None, "--token", help="BetterAuth Bearer session token."),
        internal_secret: str | None = typer.Option(None, "--internal-secret", help="Local trusted internal secret."),
        user_id: str | None = typer.Option(None, "--user-id", help="BetterAuth user ID."),
        user_email: str | None = typer.Option(None, "--user-email", help="Optional user email."),
        user_name: str | None = typer.Option(None, "--user-name", help="Optional user name."),
        json_output: bool = typer.Option(False, "--json", help="Emit a single machine-readable JSON object on stdout."),
    ) -> None:
        """List remote workspace resume summaries."""
        json_mode, stdout_stream = get_output_context(ctx, json_output)
        base, headers = _merge_sync_opts(
            ctx,
            api_url=api_url,
            token=token,
            internal_secret=internal_secret,
            user_id=user_id,
            user_email=user_email,
            user_name=user_name,
        )

        try:
            with _open_http_client() as client:
                resp = client.get(
                    f"{base}/summaries",
                    params={"offset": offset, "limit": limit},
                    headers=headers,
                )
        except httpx.RequestError as exc:
            raise CLIError(
                f"Network error contacting {base}/summaries: {exc}",
                code="network_error",
                extra={"command": "sync.list"},
            ) from exc

        _raise_for_http_error(resp, command="sync.list")
        body = _parse_json_object(resp, command="sync.list")
        items = body.get("items") or []
        if not isinstance(items, list):
            raise CLIError(
                "Remote summaries payload 'items' is not a list.",
                code="invalid_remote_payload",
                extra={"command": "sync.list"},
            )
        total = int(body.get("total", len(items)))

        if json_mode:
            emit_json(
                {
                    "ok": True,
                    "command": "sync.list",
                    "items": items,
                    "total": total,
                    "offset": body.get("offset", offset),
                    "limit": body.get("limit", limit),
                },
                stream=stdout_stream,
            )
        else:
            stdout_stream.write(f"Resumes ({len(items)}/{total}):\n")
            for item in items:
                alias_str = f" [{item['alias']}]" if item.get("alias") else ""
                stdout_stream.write(
                    f"  - {item.get('id')}: {item.get('name')}{alias_str} (updated: {item.get('updated_at')})\n"
                )
            stdout_stream.flush()

    @sync_app.command("pull")
    def sync_pull_cmd(
        ctx: typer.Context,
        resume_id: str = typer.Argument(..., help="Remote resume ID to pull."),
        output: Path = typer.Option(..., "-o", "--output", help="Local path to save pulled ResumeData JSON."),
        force: bool = typer.Option(False, "--force", help="Overwrite target file if it already exists."),
        api_url: str | None = typer.Option(None, "--api-url", help="Web/FastAPI base URL."),
        token: str | None = typer.Option(None, "--token", help="BetterAuth Bearer session token."),
        internal_secret: str | None = typer.Option(None, "--internal-secret", help="Local trusted internal secret."),
        user_id: str | None = typer.Option(None, "--user-id", help="BetterAuth user ID."),
        user_email: str | None = typer.Option(None, "--user-email", help="Optional user email."),
        user_name: str | None = typer.Option(None, "--user-name", help="Optional user name."),
        json_output: bool = typer.Option(False, "--json", help="Emit a single machine-readable JSON object on stdout."),
    ) -> None:
        """Pull a remote resume into a local ResumeData JSON file."""
        json_mode, stdout_stream = get_output_context(ctx, json_output)
        if not resume_id.strip():
            raise CLIError("Resume ID must not be empty.", code="invalid_resume_id")

        if output.exists() and not force:
            raise CLIError(
                f"Target file already exists: {output} (use --force to overwrite)",
                code="file_exists",
                extra={"command": "sync.pull", "id": resume_id, "output": str(output)},
            )

        base, headers = _merge_sync_opts(
            ctx,
            api_url=api_url,
            token=token,
            internal_secret=internal_secret,
            user_id=user_id,
            user_email=user_email,
            user_name=user_name,
        )
        clean_resume_id = resume_id.strip()
        encoded_id = urllib.parse.quote(clean_resume_id, safe="")

        try:
            with _open_http_client() as client:
                resp = client.get(f"{base}/{encoded_id}", headers=headers)
        except httpx.RequestError as exc:
            raise CLIError(
                f"Network error contacting {base}/{encoded_id}: {exc}",
                code="network_error",
                extra={"command": "sync.pull", "id": clean_resume_id},
            ) from exc

        _raise_for_http_error(resp, command="sync.pull")
        body = _parse_json_object(resp, command="sync.pull")
        raw_resume = body.get("data")
        if not isinstance(raw_resume, dict):
            raise CLIError(
                "Remote resume payload does not contain a valid 'data' object.",
                code="invalid_remote_payload",
                extra={"command": "sync.pull", "id": clean_resume_id},
            )

        pulled = copy.deepcopy(raw_resume)
        pulled["id"] = str(body.get("id") or clean_resume_id)
        remote_alias = body.get("alias")
        if isinstance(remote_alias, str):
            pulled["alias"] = remote_alias
        else:
            pulled.pop("alias", None)

        try:
            _atomic_write_json(output, pulled)
        except OSError as exc:
            raise CLIError(
                f"Failed to write pulled resume to {output}: {exc}",
                code="write_error",
                extra={"command": "sync.pull", "id": pulled["id"], "output": str(output)},
            ) from exc

        if json_mode:
            emit_json(
                {
                    "ok": True,
                    "command": "sync.pull",
                    "id": pulled["id"],
                    "name": body.get("name"),
                    "alias": remote_alias if isinstance(remote_alias, str) else None,
                    "output": str(output),
                },
                stream=stdout_stream,
            )
        else:
            stdout_stream.write(f"Pulled resume '{pulled['id']}' to {output}\n")
            stdout_stream.flush()

    @sync_app.command("push")
    def sync_push_cmd(
        ctx: typer.Context,
        file: Path = typer.Argument(..., help="Local ResumeData JSON file to validate and push."),
        resume_id: str | None = typer.Option(None, "--id", help="Override target resume ID (defaults to file data.id)."),
        name: str | None = typer.Option(None, "--name", help="Override workspace card name (defaults to basic.name or '未命名简历')."),
        alias: str | None = typer.Option(None, "--alias", help="Override workspace remark/alias."),
        api_url: str | None = typer.Option(None, "--api-url", help="Web/FastAPI base URL."),
        token: str | None = typer.Option(None, "--token", help="BetterAuth Bearer session token."),
        internal_secret: str | None = typer.Option(None, "--internal-secret", help="Local trusted internal secret."),
        user_id: str | None = typer.Option(None, "--user-id", help="BetterAuth user ID."),
        user_email: str | None = typer.Option(None, "--user-email", help="Optional user email."),
        user_name: str | None = typer.Option(None, "--user-name", help="Optional user name."),
        json_output: bool = typer.Option(False, "--json", help="Emit a single machine-readable JSON object on stdout."),
    ) -> None:
        """Validate a local ResumeData JSON file and push (PUT) it to the Web workspace."""
        json_mode, stdout_stream = get_output_context(ctx, json_output)
        raw_data, _, issues, io_or_syntax_err = load_and_validate_resume_file(file)
        if io_or_syntax_err and not issues:
            raise CLIError(
                io_or_syntax_err,
                code="file_error",
                extra={"command": "sync.push", "file": str(file)},
            )
        if issues:
            raise CLIError(
                io_or_syntax_err or f"Validation failed with {len(issues)} error(s) in {file}",
                code="invalid_json" if io_or_syntax_err else "validation_failed",
                extra={
                    "command": "sync.push",
                    "file": str(file),
                    "errors": [item.to_dict() for item in issues],
                },
            )

        assert raw_data is not None
        if resume_id is not None and not resume_id.strip():
            raise CLIError("--id must not be empty when provided.", code="invalid_resume_id")
        if name is not None and not name.strip():
            raise CLIError("--name must not be empty when provided.", code="invalid_name")

        target_id = resume_id.strip() if resume_id is not None else raw_data["id"].strip()
        payload_data = copy.deepcopy(raw_data)
        payload_data["id"] = target_id

        basic_name = str((payload_data.get("basic") or {}).get("name") or "").strip()
        cli_name = name.strip() if name is not None else None
        resolved_name = cli_name or basic_name or "未命名简历"

        resolved_alias = alias if alias is not None else payload_data.get("alias")
        if resolved_alias is not None:
            payload_data["alias"] = resolved_alias

        template_type = payload_data.get("templateType") or "latex"
        put_body: dict[str, Any] = {
            "id": target_id,
            "name": resolved_name,
            "alias": resolved_alias,
            "template_type": template_type,
            "data": payload_data,
        }

        base, headers = _merge_sync_opts(
            ctx,
            api_url=api_url,
            token=token,
            internal_secret=internal_secret,
            user_id=user_id,
            user_email=user_email,
            user_name=user_name,
        )
        encoded_id = urllib.parse.quote(target_id, safe="")

        try:
            with _open_http_client() as client:
                resp = client.put(f"{base}/{encoded_id}", json=put_body, headers=headers)
        except httpx.RequestError as exc:
            raise CLIError(
                f"Network error contacting {base}/{encoded_id}: {exc}",
                code="network_error",
                extra={"command": "sync.push", "id": target_id},
            ) from exc

        _raise_for_http_error(resp, command="sync.push")
        resp_json = _parse_json_object(resp, command="sync.push")

        if json_mode:
            emit_json(
                {
                    "ok": True,
                    "command": "sync.push",
                    "id": resp_json.get("id", target_id),
                    "name": resp_json.get("name", resolved_name),
                    "alias": resp_json.get("alias"),
                    "updated_at": resp_json.get("updated_at"),
                },
                stream=stdout_stream,
            )
        else:
            stdout_stream.write(
                f"Pushed resume '{resp_json.get('id', target_id)}' ({resp_json.get('name', resolved_name)})\n"
            )
            stdout_stream.flush()

    app.add_typer(sync_app, name="sync")
