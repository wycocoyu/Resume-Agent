import io

from fastapi.testclient import TestClient

from backend.main import app
import backend.routes.resume as resume_routes

client = TestClient(app)


def _patch(monkeypatch):
    calls = {"n": 0}

    def fake_image_to_text(b, ct, m):
        calls["n"] += 1
        return f"第{calls['n']}张文本"

    monkeypatch.setattr(resume_routes, "image_to_text", fake_image_to_text)
    canned = {"name": "王宇", "_raw": None}

    async def fake_assemble_fast(raw_text, model=None):
        # 路由当前走 assemble_resume_data_fast（分段并行版），必须一并替换
        return {**canned, "_raw": raw_text}

    monkeypatch.setattr(resume_routes, "assemble_resume_data", lambda *a, **k: canned)
    monkeypatch.setattr(resume_routes, "assemble_resume_data_fast", fake_assemble_fast)
    # 路由在函数内部 `from backend.json_normalizer import normalize_resume_json`，
    # 因此必须 patch 源模块，patch resume_routes 上的同名属性无效。
    import backend.json_normalizer as json_normalizer
    monkeypatch.setattr(json_normalizer, "normalize_resume_json", lambda d: d)
    return calls


def _png(name="r.png"):
    return ("files", (name, io.BytesIO(b"\x89PNG"), "image/png"))


def test_upload_image_single_golden(monkeypatch):
    _patch(monkeypatch)
    resp = client.post(
        "/api/resume/upload-image", files=[_png()], data={"model": "qwen-vl-max"}
    )
    assert resp.status_code == 200
    assert resp.json()["resume"]["name"] == "王宇"


def test_upload_image_two_images_merged(monkeypatch):
    calls = _patch(monkeypatch)
    resp = client.post(
        "/api/resume/upload-image",
        files=[_png("a.png"), _png("b.png")],
        data={"model": "qwen-vl-max"},
    )
    assert resp.status_code == 200
    assert calls["n"] == 2  # 两张都识别
    # 两张文本按顺序合并
    assert resp.json()["resume"]["_raw"] == "第1张文本\n\n第2张文本"


def test_upload_image_rejects_more_than_two(monkeypatch):
    _patch(monkeypatch)
    resp = client.post(
        "/api/resume/upload-image",
        files=[_png("a.png"), _png("b.png"), _png("c.png")],
        data={"model": "qwen-vl-max"},
    )
    assert resp.status_code == 400


def test_upload_image_rejects_non_image(monkeypatch):
    _patch(monkeypatch)
    resp = client.post(
        "/api/resume/upload-image",
        files=[("files", ("r.pdf", io.BytesIO(b"%PDF"), "application/pdf"))],
        data={"model": "qwen-vl-max"},
    )
    assert resp.status_code == 400
