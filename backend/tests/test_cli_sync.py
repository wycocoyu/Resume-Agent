"""Tests for Slice S3: Web workspace sync (list / pull / push) across direct & proxy topologies, auth channels, legacy roundtrip, and 401/409."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import fitz
import httpx
import pytest
from fastapi import APIRouter, FastAPI, Request, Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import backend.better_auth as better_auth
import backend.cli.sync_cmd as sync_cmd
import database as db_mod
import middleware.auth as mw_auth
import models as models_mod  # noqa: F401 - ensures ORM tables register on db_mod.Base
from backend.cli import run_cli
from backend.cli.schema import build_initial_resume
from backend.cli.sync_cmd import build_auth_headers, normalize_resumes_api_base


def _load_resumes_route_module():
    route_path = _BACKEND_DIR / "routes" / "resumes.py"
    spec = importlib.util.spec_from_file_location("resumes_route_for_cli_sync_test", route_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def sync_test_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Real FastAPI resumes router + isolated SQLite DB + simulated BetterAuth session & Next.js proxy."""
    resumes_route = _load_resumes_route_module()
    db_file = tmp_path / "sync_test.sqlite3"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db_mod.Base.metadata.create_all(bind=engine)

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setenv("FASTAPI_INTERNAL_AUTH_SECRET", "server-internal-secret")

    valid_tokens = {
        "valid-token-alice": better_auth.BetterAuthUser(
            id="user_alice_001",
            email="alice@example.com",
            name="Alice",
        ),
        "valid-token-bob": better_auth.BetterAuthUser(
            id="user_bob_002",
            email="bob@example.com",
            name="Bob",
        ),
    }

    async def _fake_verify_token(token: str, *, auth_base_url: str | None = None) -> better_auth.BetterAuthUser:
        if token in valid_tokens:
            return valid_tokens[token]
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="BetterAuth session 无效或已过期")

    monkeypatch.setattr(better_auth, "verify_better_auth_token", _fake_verify_token)
    monkeypatch.setattr(mw_auth, "verify_better_auth_token", _fake_verify_token)

    test_app = FastAPI()
    test_app.dependency_overrides[db_mod.get_db] = _override_get_db
    test_app.include_router(resumes_route.router)

    # Mount Next.js-equivalent /api/fastapi/proxy/{path:path} forwarding to internal /api/{path}
    proxy_router = APIRouter(prefix="/api/fastapi/proxy")
    recorded_headers: list[dict[str, str]] = []

    @test_app.middleware("http")
    async def _record_incoming_headers(request: Request, call_next):
        recorded_headers.append({k.lower(): v for k, v in request.headers.items()})
        return await call_next(request)

    @proxy_router.api_route("/{subpath:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def _proxy_dispatch(subpath: str, request: Request) -> Response:
        normalized = subpath[4:] if subpath.startswith("api/") else subpath
        body_bytes = await request.body()
        fwd_headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in {"host", "content-length"}
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=test_app),
            base_url="http://internal-fastapi",
        ) as internal_client:
            upstream = await internal_client.request(
                request.method,
                f"/api/{normalized}",
                params=dict(request.query_params),
                content=body_bytes,
                headers=fwd_headers,
            )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type"),
        )

    test_app.include_router(proxy_router)

    from fastapi.testclient import TestClient

    with TestClient(test_app) as tc:
        monkeypatch.setattr(sync_cmd, "_custom_httpx_transport", tc._transport)
        yield {
            "session_factory": TestingSessionLocal,
            "recorded_headers": recorded_headers,
        }
    engine.dispose()


def test_url_normalization_and_auth_header_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    assert normalize_resumes_api_base("http://127.0.0.1:9000") == "http://127.0.0.1:9000/api/resumes"
    assert normalize_resumes_api_base("http://127.0.0.1:9000/api") == "http://127.0.0.1:9000/api/resumes"
    assert normalize_resumes_api_base("http://127.0.0.1:9000/api/resumes/") == "http://127.0.0.1:9000/api/resumes"
    assert (
        normalize_resumes_api_base("http://localhost:3000/api/fastapi/proxy")
        == "http://localhost:3000/api/fastapi/proxy/resumes"
    )
    assert (
        normalize_resumes_api_base("http://localhost:3000/api/fastapi/proxy/api")
        == "http://localhost:3000/api/fastapi/proxy/resumes"
    )
    assert (
        normalize_resumes_api_base("http://localhost:3000/api/fastapi/proxy/resumes")
        == "http://localhost:3000/api/fastapi/proxy/resumes"
    )

    # Mixed env isolation: FASTAPI_INTERNAL_AUTH_SECRET MUST NOT leak when token is provided
    monkeypatch.setenv("FASTAPI_INTERNAL_AUTH_SECRET", "poison-env-secret")
    monkeypatch.setenv("RESUME_AGENT_USER_ID", "env-user")
    bearer_only = build_auth_headers(token="my-session-token")
    assert bearer_only == {"Authorization": "Bearer my-session-token"}

    # Trusted headers require BOTH secret AND user_id
    monkeypatch.delenv("RESUME_AGENT_TOKEN", raising=False)
    monkeypatch.delenv("RESUME_AGENT_USER_ID", raising=False)
    monkeypatch.delenv("BETTER_AUTH_USER_ID", raising=False)
    assert build_auth_headers() == {}

    trusted = build_auth_headers(internal_secret="sec", user_id="u_1", user_email="u@e.com")
    assert trusted == {
        "X-Internal-Auth-Secret": "sec",
        "X-Better-Auth-User-Id": "u_1",
        "X-Better-Auth-User-Email": "u@e.com",
    }


@pytest.mark.parametrize(
    "api_url",
    [
        "http://testserver:9000",
        "http://testserver:3000/api/fastapi/proxy",
    ],
)
def test_sync_push_list_pull_across_both_topologies_and_bearer_isolation(
    api_url: str,
    sync_test_env: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Set poison internal secret in env (wrong secret) while authenticating via --token:
    # If CLI leaked X-Internal-Auth-Secret, backend would immediately reject with 401!
    monkeypatch.setenv("FASTAPI_INTERNAL_AUTH_SECRET", "server-internal-secret")
    local_json = tmp_path / "alice_resume.json"
    resume = build_initial_resume(title="Alice 简历")
    resume["basic"]["name"] = "Alice Wang"
    local_json.write_text(json.dumps(resume, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    before_sha = hashlib.sha256(local_json.read_bytes()).hexdigest()

    sync_test_env["recorded_headers"].clear()
    code_push = run_cli(
        [
            "sync",
            "push",
            str(local_json),
            "--id",
            "resume_alice_custom",
            "--alias",
            "投递字节版",
            "--api-url",
            api_url,
            "--token",
            "valid-token-alice",
            "--internal-secret",
            "wrong-secret-must-be-ignored-when-token-present",
            "--user-id",
            "ignored_user",
            "--json",
        ]
    )
    push_out = json.loads(capsys.readouterr().out)
    assert code_push == 0, push_out
    assert push_out["id"] == "resume_alice_custom"
    assert push_out["name"] == "Alice Wang"
    assert push_out["alias"] == "投递字节版"
    # Local file untouched by push
    assert hashlib.sha256(local_json.read_bytes()).hexdigest() == before_sha
    # First request headers must NOT contain x-internal-auth-secret
    assert "x-internal-auth-secret" not in sync_test_env["recorded_headers"][0]
    assert sync_test_env["recorded_headers"][0]["authorization"] == "Bearer valid-token-alice"

    # List via Trusted Headers channel
    code_list = run_cli(
        [
            "sync",
            "list",
            "--api-url",
            api_url,
            "--internal-secret",
            "server-internal-secret",
            "--user-id",
            "user_alice_001",
            "--json",
        ]
    )
    list_out = json.loads(capsys.readouterr().out)
    assert code_list == 0, list_out
    assert list_out["total"] == 1
    assert list_out["items"][0]["id"] == "resume_alice_custom"
    assert list_out["items"][0]["alias"] == "投递字节版"


def test_legacy_resume_with_null_alias_and_missing_work_experience_roundtrip_to_pdf(
    sync_test_env: dict[str, Any],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Seed a legacy DB record (alias=None, no workExperience key, mismatched inner data.id),
    then run sync pull -> validate -> render to real PDF."""
    from models import Resume

    legacy_data = build_initial_resume(title="存量老简历")
    legacy_data.pop("workExperience", None)
    legacy_data["id"] = "stale_inner_id"
    legacy_data["alias"] = None  # null alias stored in old JSON
    legacy_data["basic"].update(
        {
            "name": "陈九",
            "title": "全栈开发工程师",
            "email": "chenjiu@example.com",
            "phone": "13500004444",
            "location": "杭州",
        }
    )

    db = sync_test_env["session_factory"]()
    try:
        db.add(
            Resume(
                id="legacy_db_id_777",
                user_id="user_alice_001",
                name="陈九",
                alias=None,
                data=legacy_data,
            )
        )
        db.commit()
    finally:
        db.close()

    pulled_file = tmp_path / "pulled_legacy.json"
    code_pull = run_cli(
        [
            "sync",
            "pull",
            "legacy_db_id_777",
            "-o",
            str(pulled_file),
            "--api-url",
            "http://testserver:9000",
            "--token",
            "valid-token-alice",
            "--json",
        ]
    )
    pull_out = json.loads(capsys.readouterr().out)
    assert code_pull == 0, pull_out
    assert pull_out["id"] == "legacy_db_id_777"
    assert pull_out["alias"] is None

    pulled_raw = json.loads(pulled_file.read_text(encoding="utf-8"))
    assert pulled_raw["id"] == "legacy_db_id_777"
    assert "alias" not in pulled_raw  # Top-level null alias stripped cleanly
    assert "workExperience" not in pulled_raw

    # Pull refuses overwrite without --force
    code_dup = run_cli(
        [
            "sync",
            "pull",
            "legacy_db_id_777",
            "-o",
            str(pulled_file),
            "--api-url",
            "http://testserver:9000",
            "--token",
            "valid-token-alice",
            "--json",
        ]
    )
    dup_out = json.loads(capsys.readouterr().out)
    assert code_dup == 1
    assert dup_out["error"]["code"] == "file_exists"

    # Validate pulled file
    code_val = run_cli(["validate", str(pulled_file), "--json"])
    val_out = json.loads(capsys.readouterr().out)
    assert code_val == 0, val_out
    assert val_out["valid"] is True

    # Render pulled file offline to PDF
    rendered_pdf = tmp_path / "legacy_roundtrip.pdf"
    code_render = run_cli(["render", str(pulled_file), "-o", str(rendered_pdf), "--json"])
    render_out = json.loads(capsys.readouterr().out)
    assert code_render == 0, render_out
    with fitz.open(rendered_pdf) as doc:
        assert "陈九" in doc[0].get_text()


def test_sync_401_unauthorized_and_409_cross_user_id_conflict(
    sync_test_env: dict[str, Any],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    resume_file = tmp_path / "conflict.json"
    resume = build_initial_resume()
    resume["id"] = "shared_id_conflict_001"
    resume["basic"]["name"] = "Alice Owner"
    resume_file.write_text(json.dumps(resume, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 1. Invalid Bearer token -> 401 exit 1
    code_401 = run_cli(
        [
            "sync",
            "list",
            "--api-url",
            "http://testserver:9000",
            "--token",
            "expired-or-invalid-token",
            "--json",
        ]
    )
    out_401 = json.loads(capsys.readouterr().out)
    assert code_401 == 1
    assert out_401["status_code"] == 401

    # 2. Alice creates shared_id_conflict_001 -> 200
    code_alice = run_cli(
        [
            "sync",
            "push",
            str(resume_file),
            "--api-url",
            "http://testserver:9000",
            "--token",
            "valid-token-alice",
            "--json",
        ]
    )
    capsys.readouterr()
    assert code_alice == 0

    # 3. Bob attempts to push to Alice's ID -> 409 Conflict exit 1
    code_409 = run_cli(
        [
            "sync",
            "push",
            str(resume_file),
            "--api-url",
            "http://testserver:9000",
            "--token",
            "valid-token-bob",
            "--json",
        ]
    )
    out_409 = json.loads(capsys.readouterr().out)
    assert code_409 == 1
    assert out_409["status_code"] == 409
    assert out_409["error"]["code"] == "http_409"


def test_real_uvicorn_subprocess_sync_end_to_end(tmp_path: Path) -> None:
    """Spawn a real uvicorn backend.main:app TCP server on a free localhost port with temp SQLite,
    and invoke the installed `resume-agent` CLI binary from an external working directory."""
    import os
    import socket
    import subprocess
    import time

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    sqlite_file = tmp_path / "live_uvicorn.sqlite3"
    engine = create_engine(f"sqlite:///{sqlite_file}", connect_args={"check_same_thread": False})
    db_mod.Base.metadata.create_all(bind=engine)
    engine.dispose()

    repo_root = Path(__file__).resolve().parents[2]
    server_env = os.environ.copy()
    server_env.update(
        {
            "USE_POSTGRESQL": "false",
            "DATABASE_URL": f"sqlite:///{sqlite_file}",
            "FASTAPI_INTERNAL_AUTH_SECRET": "live-uvicorn-secret-xyz",
            "LOGO_AUTO_SYNC_ON_STARTUP": "false",
            "LOG_DIR": str(tmp_path / "logs"),
            "NO_PROXY": "127.0.0.1,localhost",
        }
    )
    server_env.pop("POSTGRESQL_URL", None)
    server_env.pop("MYSQLHOST", None)

    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import dotenv; dotenv.load_dotenv = lambda *a, **k: False; "
                "import uvicorn; "
                f"uvicorn.run('backend.main:app', host='127.0.0.1', port={port}, log_level='warning')"
            ),
        ],
        cwd=str(repo_root),
        env=server_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    api_url = f"http://127.0.0.1:{port}"
    try:
        ready = False
        deadline = time.time() + 20.0
        with httpx.Client(trust_env=False, timeout=1.5) as probe:
            while time.time() < deadline:
                if proc.poll() is not None:
                    out, err = proc.communicate()
                    raise RuntimeError(f"uvicorn exited prematurely: {out}\n{err}")
                try:
                    r = probe.get(f"{api_url}/api/health")
                    if r.status_code == 200:
                        ready = True
                        break
                except httpx.RequestError:
                    pass
                time.sleep(0.25)
        assert ready, "Timed out waiting for live uvicorn /api/health"

        ext_cwd = tmp_path / "ext_cwd"
        ext_cwd.mkdir()
        cli_bin = Path(sys.executable).parent / "resume-agent"
        cmd_prefix = [str(cli_bin)] if cli_bin.exists() else [sys.executable, "-m", "backend.cli"]

        cli_env = os.environ.copy()
        cli_env["RESUME_AGENT_API_URL"] = api_url
        cli_env["FASTAPI_INTERNAL_AUTH_SECRET"] = "live-uvicorn-secret-xyz"
        cli_env["RESUME_AGENT_USER_ID"] = "uvicorn_live_user_01"

        src_json = ext_cwd / "created.json"
        r_init = subprocess.run(
            [*cmd_prefix, "init", "-o", str(src_json), "--title", "Uvicorn 实测简历", "--json"],
            cwd=str(ext_cwd),
            env=cli_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert r_init.returncode == 0, r_init.stderr

        # Populate candidate name
        doc_json = json.loads(src_json.read_text(encoding="utf-8"))
        doc_json["basic"]["name"] = "林十"
        doc_json["basic"]["email"] = "linshi@example.com"
        src_json.write_text(json.dumps(doc_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        r_push = subprocess.run(
            [*cmd_prefix, "sync", "push", str(src_json), "--alias", "实测同步版", "--json"],
            cwd=str(ext_cwd),
            env=cli_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert r_push.returncode == 0, r_push.stderr
        push_payload = json.loads(r_push.stdout)
        assert push_payload["ok"] is True
        pushed_id = push_payload["id"]

        r_list = subprocess.run(
            [*cmd_prefix, "sync", "list", "--json"],
            cwd=str(ext_cwd),
            env=cli_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert r_list.returncode == 0, r_list.stderr
        list_payload = json.loads(r_list.stdout)
        assert list_payload["total"] == 1
        assert list_payload["items"][0]["id"] == pushed_id
        assert list_payload["items"][0]["name"] == "林十"

        pulled_json = ext_cwd / "pulled.json"
        r_pull = subprocess.run(
            [*cmd_prefix, "sync", "pull", pushed_id, "-o", str(pulled_json), "--json"],
            cwd=str(ext_cwd),
            env=cli_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert r_pull.returncode == 0, r_pull.stderr
        pull_payload = json.loads(r_pull.stdout)
        assert pull_payload["alias"] == "实测同步版"

        out_pdf = ext_cwd / "live_sync.pdf"
        r_render = subprocess.run(
            [*cmd_prefix, "render", str(pulled_json), "-o", str(out_pdf), "--json"],
            cwd=str(ext_cwd),
            env=cli_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert r_render.returncode == 0, r_render.stderr
        with fitz.open(out_pdf) as pdf_doc:
            assert "林十" in pdf_doc[0].get_text()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_empty_token_never_falls_back_to_internal_trusted_headers(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("FASTAPI_INTERNAL_AUTH_SECRET", "poison-internal-secret")
    monkeypatch.setenv("RESUME_AGENT_USER_ID", "victim_admin_user")

    # Explicit empty or whitespace --token must fail closed with invalid_token, never leaking internal headers
    for bad_token in ("", "   "):
        code = run_cli(["sync", "list", "--token", bad_token, "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert code == 1
        assert payload["error"]["code"] == "invalid_token"

    # Explicit whitespace RESUME_AGENT_TOKEN must also fail closed
    monkeypatch.setenv("RESUME_AGENT_TOKEN", "   ")
    code_env = run_cli(["sync", "list", "--json"])
    payload_env = json.loads(capsys.readouterr().out)
    assert code_env == 1
    assert payload_env["error"]["code"] == "invalid_token"


def test_sync_handles_non_json_or_non_dict_200_responses_cleanly(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sync_cmd,
        "_custom_httpx_transport",
        httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                text="<!DOCTYPE html><html><body>Login</body></html>",
                headers={"content-type": "text/html"},
            )
        ),
    )
    code_html = run_cli(["sync", "list", "--token", "tok", "--json"])
    out_html = json.loads(capsys.readouterr().out)
    assert code_html == 1
    assert out_html["error"]["code"] == "invalid_remote_payload"

    monkeypatch.setattr(
        sync_cmd,
        "_custom_httpx_transport",
        httpx.MockTransport(lambda req: httpx.Response(200, json=[1, 2, 3])),
    )
    code_list = run_cli(["sync", "list", "--token", "tok", "--json"])
    out_list = json.loads(capsys.readouterr().out)
    assert code_list == 1
    assert out_list["error"]["code"] == "invalid_remote_payload"


def test_sync_human_readable_output_mode(
    sync_test_env: dict[str, Any],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    src_json = tmp_path / "human_sync.json"
    resume = build_initial_resume(title="人类可读测试")
    resume["basic"]["name"] = "周十一"
    src_json.write_text(json.dumps(resume, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rc_push = run_cli(
        ["sync", "push", str(src_json), "--alias", "可读版", "--token", "valid-token-alice"]
    )
    out_push = capsys.readouterr().out
    assert rc_push == 0
    assert "Pushed resume '" in out_push

    rc_list = run_cli(["sync", "list", "--token", "valid-token-alice"])
    out_list = capsys.readouterr().out
    assert rc_list == 0
    assert "Resumes (" in out_list
    assert "[可读版]" in out_list

    pulled = tmp_path / "human_pulled.json"
    rc_pull = run_cli(
        ["sync", "pull", resume["id"], "-o", str(pulled), "--token", "valid-token-alice"]
    )
    out_pull = capsys.readouterr().out
    assert rc_pull == 0
    assert "Pulled resume '" in out_pull

