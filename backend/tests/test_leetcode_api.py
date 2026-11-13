from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient
from pathlib import Path

from backend.core.logger import setup_logging

pytestmark = pytest.mark.skipif(
    shutil.which("go") is None, reason="Go toolchain not installed"
)

setup_logging(is_production=False, log_level="INFO", log_dir="logs/test")

from backend.routes.leetcode import create_router


def make_problem(slug: str) -> dict:
    return {
        "id": f"problem_{slug.replace('-', '_')}",
        "slug": slug,
        "title": "Example Problem",
        "difficulty": "Medium",
        "tags": ["Array"],
        "source": "custom",
        "description": "desc",
        "examples": [],
        "constraints": [],
        "hints": [],
        "functionName": "solve",
        "signature": "func solve(nums []int, k int) []int",
        "starterCode": "package main\n\nfunc solve(nums []int, k int) []int {\n\treturn nums\n}\n",
        "visibleTestCases": [
            {"id": "case-1", "input": {"nums": [1, 2, 3], "k": 2}, "expected": [2, 1, 3]}
        ],
        "hiddenTestCases": [
            {"id": "hidden-1", "input": {"nums": [1, 2], "k": 3}, "expected": [2, 1]}
        ],
        "judge": {"type": "function", "entry": "solve"},
        "createdAt": "2026-05-10T00:00:00.000Z",
        "updatedAt": "2026-05-10T00:00:00.000Z",
    }


GOOD_CODE = """package main

func solve(nums []int, k int) []int {
\tresult := make([]int, 0, len(nums))
\tfor i := 0; i < len(nums); i += k {
\t\tend := i + k
\t\tif end > len(nums) {
\t\t\tend = len(nums)
\t\t}
\t\tfor j := end - 1; j >= i; j-- {
\t\t\tresult = append(result, nums[j])
\t\t}
\t}
\treturn result
}
"""


def make_client(tmp_path: Path) -> TestClient:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(create_router(base_dir=tmp_path))
    return TestClient(app)


def test_problem_crud_and_execution(tmp_path: Path):
    client = make_client(tmp_path)
    problem = make_problem("api-problem")

    create_response = client.post("/api/leetcode/problems", json=problem)
    assert create_response.status_code == 200

    list_response = client.get("/api/leetcode/problems")
    assert list_response.status_code == 200
    assert list_response.json()[0]["slug"] == "api-problem"

    detail_response = client.get("/api/leetcode/problems/api-problem")
    assert detail_response.status_code == 200
    assert detail_response.json()["title"] == "Example Problem"

    draft_response = client.put("/api/leetcode/drafts/api-problem", json={"code": GOOD_CODE})
    assert draft_response.status_code == 200

    run_response = client.post(
        "/api/leetcode/run",
        json={
            "slug": "api-problem",
            "code": GOOD_CODE,
            "testCases": [{"id": "custom-1", "input": {"nums": [1, 2], "k": 3}, "expected": [2, 1]}],
        },
    )
    assert run_response.status_code == 200
    assert run_response.headers.get("X-LeetCode-ProgramRun") == "1"
    body = run_response.json()
    assert body["status"] == "accepted"
    assert "programRun" in body
    pr = body["programRun"]
    assert pr["status"] == "error"
    stderr = pr["stderr"]
    assert "main" in stderr.lower()

    submit_response = client.post(
        "/api/leetcode/submit",
        json={"slug": "api-problem", "code": GOOD_CODE},
    )
    assert submit_response.status_code == 200
    assert submit_response.json()["status"] == "accepted"


def test_solution_api(tmp_path: Path):
    client = make_client(tmp_path)
    problem = make_problem("api-problem")

    create_response = client.post("/api/leetcode/problems", json=problem)
    assert create_response.status_code == 200

    get_response = client.get("/api/leetcode/solutions/api-problem")
    assert get_response.status_code == 200
    assert get_response.json() == {
        "slug": "api-problem",
        "language": "go",
        "code": "",
        "updatedAt": None,
    }

    save_response = client.put("/api/leetcode/solutions/api-problem", json={"code": GOOD_CODE})
    assert save_response.status_code == 200
    assert save_response.json()["slug"] == "api-problem"
    assert save_response.json()["code"] == GOOD_CODE

    fetch_again = client.get("/api/leetcode/solutions/api-problem")
    assert fetch_again.status_code == 200
    assert fetch_again.json()["code"] == GOOD_CODE
