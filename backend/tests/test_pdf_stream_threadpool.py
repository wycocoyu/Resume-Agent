import os
import sys
from io import BytesIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from fastapi.testclient import TestClient

from backend.main import app
import backend.routes.pdf as pdf_route
import backend.latex_generator as latex_generator


def test_render_pdf_stream_offloads_blocking_work_to_threadpool(monkeypatch):
    pdf_route._pdf_cache.clear()
    latex_generator._pdf_cache.clear()
    calls: list[str] = []

    async def fake_run_in_threadpool(func, *args, **kwargs):
        calls.append(getattr(func, "__name__", "anonymous"))
        return func(*args, **kwargs)

    monkeypatch.setattr(pdf_route, "run_in_threadpool", fake_run_in_threadpool, raising=False)
    monkeypatch.setattr(
        latex_generator,
        "json_to_latex",
        lambda _resume, _order=None: r"\\documentclass{article}\\begin{document}ok\\end{document}",
    )
    monkeypatch.setattr(
        latex_generator,
        "compile_latex_to_pdf",
        lambda _latex, _template_dir, resume_data=None: BytesIO(b"%PDF-1.4\\n%fake\\n"),
    )

    client = TestClient(app)
    response = client.post(
        "/api/pdf/render/stream",
        json={"resume": {"name": "tester"}, "section_order": []},
    )

    assert response.status_code == 200
    assert "event: pdf" in response.text
    assert calls, "Expected render pipeline to use run_in_threadpool for blocking work"
