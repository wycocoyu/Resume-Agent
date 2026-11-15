"""Regression tests for Issue #68: upload-image SSE stream, ASGI middleware, COS offloading, and sync_resumes TZ normalization."""
from __future__ import annotations

import asyncio
import builtins
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import backend.routes.resume as resume_routes
import database as db_mod
from backend.main import app
from backend.middleware.observability import (
    RequestObservabilityMiddleware,
    _is_disconnect_only_error,
)
from backend.services.sync_service import sync_resumes
from models import Resume


def _png_file(name: str = "resume.png"):
    return ("files", (name, io.BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png"))


def test_sync_resumes_handles_mixed_naive_and_aware_datetimes(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sync_tz.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db_mod.Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        user = SimpleNamespace(id="u_tz_001")
        # Simulate SQLite returning naive UTC updated_at
        db.add(
            Resume(
                id="r_naive",
                user_id=user.id,
                name="旧名称",
                alias=None,
                data={"name": "旧名称"},
                updated_at=datetime(2026, 11, 15, 12, 0, 0),
            )
        )
        # Simulate PostgreSQL returning offset-aware updated_at
        db.add(
            Resume(
                id="r_aware",
                user_id=user.id,
                name="线上最新版",
                alias=None,
                data={"name": "线上最新版"},
                updated_at=datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc),
            )
        )
        db.commit()

        # Newer +08:00 timestamp (12:05 UTC) must update naive DB row; older Z (11:55 UTC) must skip aware DB row
        merged = sync_resumes(
            db,
            user,
            [
                {
                    "id": "r_naive",
                    "name": "新名称",
                    "data": {"name": "新名称"},
                    "updated_at": "2026-11-15T20:05:00+08:00",
                },
                {
                    "id": "r_aware",
                    "name": "本地过期版",
                    "data": {"name": "本地过期版"},
                    "updated_at": "2026-11-15T11:55:00Z",
                },
            ],
        )
        by_id = {r.id: r for r in merged}
        assert by_id["r_naive"].name == "新名称"
        assert by_id["r_aware"].name == "线上最新版"
    finally:
        db.close()
        engine.dispose()


def test_upload_image_stream_emits_status_heartbeat_and_json(monkeypatch: pytest.MonkeyPatch):
    def slow_image_to_text(b, ct, m):
        time.sleep(0.06)
        return "姓名：张三\n职位：后端工程师"

    async def fake_assemble_fast(raw_text, model=None):
        return {"name": "张三", "objective": "后端工程师", "_raw": raw_text}

    import backend.json_normalizer as json_normalizer

    monkeypatch.setattr(resume_routes, "image_to_text", slow_image_to_text)
    monkeypatch.setattr(resume_routes, "assemble_resume_data_fast", fake_assemble_fast)
    monkeypatch.setattr(resume_routes, "normalize_resume_json", lambda d: d)
    monkeypatch.setattr(json_normalizer, "normalize_resume_json", lambda d: d)
    monkeypatch.setattr(resume_routes, "IMAGE_STREAM_HEARTBEAT_INTERVAL", 0.02)

    client = TestClient(app)
    resp = client.post(
        "/api/resume/upload-image/stream",
        files=[_png_file()],
        data={"model": "glm-ocr"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    frames = []
    for line in resp.text.splitlines():
        if line.startswith("data: "):
            raw = line[6:].strip()
            frames.append(raw if raw == "[DONE]" else json.loads(raw))

    event_types = [f["type"] for f in frames if isinstance(f, dict)]
    assert "status" in event_types
    assert "heartbeat" in event_types
    assert "json" in event_types
    assert "[DONE]" in frames
    json_frame = next(f for f in frames if isinstance(f, dict) and f.get("type") == "json")
    assert json_frame["content"]["resume"]["name"] == "张三"


def test_upload_image_stream_validates_bad_inputs_with_http_400():
    client = TestClient(app)
    resp = client.post(
        "/api/resume/upload-image/stream",
        files=[("files", ("bad.pdf", io.BytesIO(b"%PDF"), "application/pdf"))],
        data={"model": "glm-ocr"},
    )
    assert resp.status_code == 400


def test_parse_stream_offloads_sync_iterator(monkeypatch: pytest.MonkeyPatch):
    def slow_chunks(provider, prompt):
        time.sleep(0.04)
        yield '{"name": "李四"}'

    monkeypatch.setattr(resume_routes, "call_llm_stream", slow_chunks)
    monkeypatch.setattr(resume_routes, "parse_json_response", lambda s: json.loads(s))
    monkeypatch.setattr(resume_routes, "IMAGE_STREAM_HEARTBEAT_INTERVAL", 0.015)

    client = TestClient(app)
    resp = client.post("/api/resume/parse/stream", json={"text": "李四 后端开发"})
    assert resp.status_code == 200
    assert "李四" in resp.text
    assert '"type": "heartbeat"' in resp.text
    assert "data: [DONE]" in resp.text


def test_pure_asgi_observability_handles_disconnect_without_taskgroup_crash(
    monkeypatch: pytest.MonkeyPatch,
):
    from backend.middleware import observability as obs_mod

    monkeypatch.setattr(obs_mod, "_persist_observability", lambda **kwargs: None)

    mini_app = FastAPI()
    mini_app.add_middleware(RequestObservabilityMiddleware)

    @mini_app.get("/ok")
    async def ok():
        return {"status": "ok"}

    async def _run():
        transport = httpx.ASGITransport(app=mini_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/ok")
            assert r.status_code == 200
            assert r.headers.get("X-Trace-Id")
            assert r.headers.get("X-Request-Id")

        # Simulate ASGI call receiving disconnect-only CancelledError / ExceptionGroup
        async def _cancel_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            raise asyncio.CancelledError()

        mw = RequestObservabilityMiddleware(_cancel_app)
        sent = []
        await mw(
            {"type": "http", "method": "GET", "path": "/sse", "headers": []},
            lambda: asyncio.sleep(0),
            lambda msg: asyncio.coroutine(lambda: sent.append(msg))()
            if False
            else _async_append(sent, msg),
        )
        assert sent and any(
            k == b"x-trace-id" for k, _ in sent[0].get("headers", [])
        )

    async def _async_append(lst, item):
        lst.append(item)

    asyncio.run(_run())

    base_exc_group = getattr(builtins, "BaseExceptionGroup", None)
    if base_exc_group is not None:
        grp = base_exc_group("disconnects", [asyncio.CancelledError(), BrokenPipeError()])
        assert _is_disconnect_only_error(grp) is True
        mixed = base_exc_group("mixed", [asyncio.CancelledError(), ValueError("boom")])
        assert _is_disconnect_only_error(mixed) is False


def test_logos_endpoints_do_not_block_event_loop():
    async def _run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            r1, r2 = await asyncio.gather(
                ac.get("/api/logos"),
                ac.get("/api/school-logos"),
            )
            assert r1.status_code == 200
            assert r2.status_code == 200
            assert "logos" in r1.json()
            assert "logos" in r2.json()

    asyncio.run(_run())
