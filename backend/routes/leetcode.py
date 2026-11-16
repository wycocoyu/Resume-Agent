from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from backend.services.leetcode_runner import LeetCodeRunner
from backend.services.leetcode_store import LeetCodeStore


class DraftPayload(BaseModel):
    code: str


class RunCasePayload(BaseModel):
    id: str
    input: dict
    expected: object | None = None


class RunPayload(BaseModel):
    slug: str
    code: str
    testCases: list[RunCasePayload] = Field(default_factory=list)


class SubmitPayload(BaseModel):
    slug: str
    code: str


def create_router(base_dir: str | Path | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/leetcode", tags=["LeetCode"])
    store = LeetCodeStore(base_dir=base_dir)
    runner = LeetCodeRunner(runtime_dir=store.runtime_dir)

    @router.get("/problems")
    async def list_problems():
        return store.list_problems()

    @router.get("/problems/{slug}")
    async def get_problem(slug: str):
        try:
            return store.get_problem(slug)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/problems")
    async def create_problem(problem: dict):
        raw_slug = problem.get("slug") if isinstance(problem, dict) else None
        slug = raw_slug.strip() if isinstance(raw_slug, str) else ""
        if not slug:
            raise HTTPException(status_code=422, detail="Missing required field: slug")
        if store.problem_exists(slug):
            raise HTTPException(status_code=409, detail="Problem already exists")
        normalized = {**problem, "slug": slug} if problem.get("slug") != slug else problem
        return store.save_problem(normalized)

    @router.put("/problems/{slug}")
    async def update_problem(slug: str, problem: dict):
        if slug != problem.get("slug"):
            raise HTTPException(status_code=400, detail="Slug mismatch")
        return store.save_problem(problem)

    @router.get("/drafts/{slug}")
    async def get_draft(slug: str):
        draft = store.get_draft(slug)
        if draft is None:
            return {"slug": slug, "language": "go", "code": "", "updatedAt": None}
        return draft

    @router.put("/drafts/{slug}")
    async def save_draft(slug: str, payload: DraftPayload):
        return store.save_draft(slug, payload.code)

    @router.get("/solutions/{slug}")
    async def get_solution(slug: str):
        solution = store.get_solution(slug)
        if solution is None:
            return {"slug": slug, "language": "go", "code": "", "updatedAt": None}
        return solution

    @router.put("/solutions/{slug}")
    async def save_solution(slug: str, payload: DraftPayload):
        return store.save_solution(slug, payload.code)

    @router.get("/submissions")
    async def list_submissions(slug: str | None = None):
        return store.list_submissions(slug)

    @router.post("/run")
    async def run_problem(payload: RunPayload, response: Response):
        try:
            problem = store.get_problem(payload.slug)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        cases = [item.model_dump() if hasattr(item, "model_dump") else item.dict() for item in payload.testCases]
        result = runner.run_cases(problem, payload.code, cases)
        result["programRun"] = runner.run_raw_program(payload.code)
        # 便于在浏览器 Network 里区分「新代码进程」与未重载的旧 uvicorn（仅靠 JSON 键无法自证）
        response.headers["X-LeetCode-ProgramRun"] = "1"
        return result

    @router.post("/submit")
    async def submit_problem(payload: SubmitPayload):
        try:
            problem = store.get_problem(payload.slug)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        result = runner.submit_problem(problem, payload.code)
        record = {
            "id": f"sub_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
            "slug": payload.slug,
            "language": "go",
            "code": payload.code,
            "mode": "submit",
            "status": result["status"],
            "summary": result["summary"],
            "results": result["results"],
        }
        store.save_submission(record)
        return result

    return router


router = create_router()
