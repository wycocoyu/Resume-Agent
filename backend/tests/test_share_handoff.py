"""Tests for cross-worker DiskShareStore and opt-in `cococv handoff` CLI."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
import httpx
import pytest

from backend.cli import run_cli
from backend.cli.schema import build_initial_resume
from backend.main import app
import backend.routes.share as share_route


def test_disk_share_store_cross_instance_ttl_size_and_traversal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_dir = tmp_path / "shares"
    monkeypatch.setenv("SHARE_STORE_DIR", str(store_dir))
    monkeypatch.setenv("FRONTEND_URL", "https://cococv.cn")

    # Separate DiskShareStore instances mimic multi-worker Uvicorn processes
    worker_a = share_route.DiskShareStore()
    worker_b = share_route.DiskShareStore()
    worker_a.clear()

    client = TestClient(app)

    # 1. Create with expire_minutes
    resp = client.post(
        "/api/resume/share",
        json={
            "resume_data": {"basic": {"name": "跨进程测试"}, "education": []},
            "resume_name": "跨进程测试",
            "expire_minutes": 60,
        },
    )
    assert resp.status_code == 200, resp.text
    created = resp.json()
    sid = created["share_id"]
    assert created["share_url"] == f"https://cococv.cn/share/{sid}"
    assert sid in worker_a
    assert sid in worker_b
    assert worker_b[sid]["resume_name"] == "跨进程测试"

    # 2. Fetch increments persisted view count
    get_resp = client.get(f"/api/resume/share/{sid}")
    assert get_resp.status_code == 200
    assert get_resp.json()["views"] == 1
    assert worker_b[sid]["views"] == 1

    # 3. Path traversal keys rejected safely
    with pytest.raises(KeyError):
        _ = worker_a["../secret"]
    assert client.get("/api/resume/share/..%2Fsecret").status_code in (404, 422)

    # 4. Payload > 512 KB returns 413
    oversized = client.post(
        "/api/resume/share",
        json={
            "resume_data": {"basic": {"name": "Big"}, "blob": "x" * (520 * 1024)},
            "resume_name": "Big",
            "expire_minutes": 10,
        },
    )
    assert oversized.status_code == 413

    # 5. Expired record returns 404 and is deleted from disk
    rec = worker_a[sid]
    rec["expires_at"] = "2020-01-01T00:00:00"
    worker_a[sid] = rec
    expired_resp = client.get(f"/api/resume/share/{sid}")
    assert expired_resp.status_code == 404
    assert sid not in worker_b

    worker_a.clear()
    assert len(worker_b) == 0


def test_cli_handoff_validates_before_network_and_uploads_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import backend.cli.handoff_cmd as handoff_cmd

    captured_requests: list[tuple[str, dict]] = []

    def _mock_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured_requests.append((str(request.url), body))
        return httpx.Response(
            200,
            json={
                "share_id": "abc123xyz",
                "share_url": "https://cococv.cn/share/abc123xyz",
                "expires_at": "2026-11-16T00:00:00",
            },
        )

    monkeypatch.setattr(handoff_cmd, "_custom_httpx_transport", httpx.MockTransport(_mock_handler))

    # 1. Invalid JSON fails validation without hitting network
    bad_file = tmp_path / "bad.json"
    bad_file.write_text('{"id": "x"}', encoding="utf-8")
    code_bad = run_cli(["handoff", str(bad_file), "--api-url", "https://cococv.cn", "--json"])
    assert code_bad != 0
    bad_out = json.loads(capsys.readouterr().out)
    assert bad_out["error"]["code"] == "validation_failed"
    assert captured_requests == []

    # 2. Valid resume uploads with expire_minutes=45
    resume = build_initial_resume(title="承接测试")
    resume["basic"]["name"] = "林零"
    good_file = tmp_path / "good.json"
    good_file.write_text(json.dumps(resume, ensure_ascii=False), encoding="utf-8")

    code_ok = run_cli(
        [
            "handoff",
            str(good_file),
            "--api-url",
            "https://cococv.cn",
            "--ttl-minutes",
            "45",
            "--json",
        ]
    )
    assert code_ok == 0
    ok_out = json.loads(capsys.readouterr().out)
    assert ok_out["ok"] is True
    assert ok_out["share_id"] == "abc123xyz"
    assert ok_out["share_url"] == "https://cococv.cn/share/abc123xyz"
    assert ok_out["ttl_minutes"] == 45
    assert len(captured_requests) == 1
    req_url, req_body = captured_requests[0]
    assert req_url == "https://cococv.cn/api/resume/share"
    assert req_body["expire_minutes"] == 45
    assert req_body["resume_name"] == "林零"
