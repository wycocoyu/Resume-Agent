"""FastAPI router for Job Description (JD) parsing, 3D radar matching, and STAR rewrites.

Authoritative specs:
- Feature 18 / Issue #54
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import Resume
from middleware.auth import AppUser, get_current_user_optional
from backend.services.jd_matcher import (
    JdMatchingEngine,
    JdMatchResponse,
    ParsedJd,
    StarRewriteResponse,
)

router = APIRouter(prefix="/api/jd", tags=["Job JD Matching & Analysis"])


class JdParseRequest(BaseModel):
    jd_text: str = Field(..., min_length=5, description="Raw job description text")


class JdMatchRequest(BaseModel):
    resume_id: Optional[str] = Field(default=None, description="Optional resume ID from database")
    resume_data: Optional[Dict[str, Any]] = Field(default=None, description="Full resume JSON data")
    jd_text: Optional[str] = Field(default=None, description="Raw JD text")
    jd_parsed: Optional[ParsedJd] = Field(default=None, description="Pre-parsed JD structure")


class StarRewriteRequest(BaseModel):
    jd_text: str = Field(..., min_length=5, description="Raw JD text")
    fields: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="List of JdOptimizeField items [{key, label, content}]"
    )
    resume_data: Optional[Dict[str, Any]] = None
    mode: str = Field(default="auto")
    provider: Optional[str] = "deepseek"


@router.post("/parse", response_model=ParsedJd)
def parse_jd(payload: JdParseRequest):
    """Parse raw job description text into a structured JD profile."""
    engine = JdMatchingEngine()
    return engine.parse_jd(payload.jd_text)


@router.post("/match", response_model=JdMatchResponse)
@router.post("/analyze", response_model=JdMatchResponse)
def match_jd(
    payload: JdMatchRequest,
    db: Session = Depends(get_db),
    current_user: Optional[AppUser] = Depends(get_current_user_optional),
):
    """Compute 3D radar matching scores (Technical, Project, Experience) between resume and target JD."""
    resume_data = payload.resume_data
    if not resume_data and payload.resume_id:
        if not current_user:
            raise HTTPException(status_code=401, detail="未提供有效的认证信息")
        resume = (
            db.query(Resume)
            .filter(Resume.id == payload.resume_id, Resume.user_id == current_user.id)
            .first()
        )
        if not resume or not resume.data:
            raise HTTPException(status_code=404, detail="简历不存在或无数据")
        resume_data = resume.data

    if not resume_data:
        raise HTTPException(status_code=400, detail="必须提供 resume_data 或有效的 resume_id")

    if not payload.jd_text and not payload.jd_parsed:
        raise HTTPException(status_code=400, detail="必须提供 target jd_text 或 jd_parsed")

    engine = JdMatchingEngine()
    parsed_jd = payload.jd_parsed or engine.parse_jd(payload.jd_text or "")
    return engine.calculate_3d_match(resume_data, parsed_jd)


@router.post("/star-rewrite", response_model=StarRewriteResponse)
async def star_rewrite(payload: StarRewriteRequest):
    """Generate deterministic STAR rewrite suggestions for candidate experience/projects."""
    engine = JdMatchingEngine()
    suggestions = await engine.generate_star_rewrites(
        jd_text=payload.jd_text,
        fields=payload.fields,
        resume_data=payload.resume_data,
        mode=payload.mode,
        provider=payload.provider,
    )
    return StarRewriteResponse(suggestions=suggestions, total_suggestions=len(suggestions))
