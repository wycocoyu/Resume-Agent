"""
简历存储相关路由
"""
from typing import List, Optional, Dict, Any
from uuid import uuid4
import json
import logging
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import case
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from database import get_db
from models import Resume, ResumeEmbedding
from middleware.auth import AppUser, get_current_user
from services.sync_service import sync_resumes

router = APIRouter(prefix="/api/resumes", tags=["Resumes"])
logger = logging.getLogger("backend")


class ResumePayload(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    alias: Optional[str] = None  # 备注/别名
    template_type: Optional[str] = None  # html 或 latex
    data: Dict[str, Any]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ResumeResponse(BaseModel):
    id: str
    name: str
    alias: Optional[str] = None  # 备注/别名
    template_type: Optional[str] = None  # html 或 latex
    data: Dict[str, Any]
    created_at: Optional[str]
    updated_at: Optional[str]


class ResumeSummaryResponse(BaseModel):
    """Dashboard 列表摘要：刻意不返回体积较大的完整 data。"""
    id: str
    name: str
    alias: Optional[str] = None
    pinned: bool = False
    created_at: Optional[str]
    updated_at: Optional[str]


class ResumeSummaryPageResponse(BaseModel):
    items: List[ResumeSummaryResponse]
    total: int
    offset: int
    limit: int


class SyncRequest(BaseModel):
    resumes: List[ResumePayload]


class ForkResumeRequest(BaseModel):
    target_jd_title: Optional[str] = None
    target_company: Optional[str] = None
    custom_name: Optional[str] = None
    jd_text: Optional[str] = None


def _extract_template_type(data: Dict[str, Any]) -> str:
    """从简历数据中提取模板类型，默认为 latex"""
    return data.get("templateType") or "latex"


@router.get("", response_model=List[ResumeResponse])
def list_resumes(
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取当前用户所有简历"""
    t0 = time.perf_counter()
    resumes = db.query(Resume).filter(Resume.user_id == current_user.id).order_by(Resume.updated_at.desc()).all()
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info(f"[DashboardPerf] /api/resumes user_id={current_user.id} count={len(resumes)} 耗时 {elapsed_ms:.1f}ms")
    return [
        ResumeResponse(
            id=r.id,
            name=r.name,
            alias=r.alias,
            template_type=_extract_template_type(r.data),
            data=r.data,
            created_at=r.created_at.isoformat() if r.created_at else None,
            updated_at=r.updated_at.isoformat() if r.updated_at else None
        )
        for r in resumes
    ]


@router.get("/summaries", response_model=ResumeSummaryPageResponse)
def list_resume_summaries(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=8, ge=1, le=50),
    pinned_ids: Optional[str] = Query(default=None, max_length=4000),
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """分页获取 Dashboard 卡片摘要，不读取和传输完整简历 JSON。"""
    t0 = time.perf_counter()
    # 置顶是当前账号在浏览器中的 UI 偏好。把 ID 传给查询后在数据库层
    # 完成全局排序，避免先分页、再在单页内置顶导致卡片跑错页。
    requested_pinned_ids = {
        resume_id.strip()
        for resume_id in (pinned_ids or "").split(",")[:100]
        if resume_id.strip()
    }
    pinned_rank = case(
        (Resume.id.in_(requested_pinned_ids), 1),
        else_=0,
    ) if requested_pinned_ids else 0
    sort_columns = [Resume.updated_at.desc(), Resume.id.asc()]
    if requested_pinned_ids:
        sort_columns.insert(0, pinned_rank.desc())

    base_query = db.query(Resume).filter(Resume.user_id == current_user.id)
    total = base_query.count()
    rows = (
        base_query
        .with_entities(
            Resume.id,
            Resume.name,
            Resume.alias,
            Resume.created_at,
            Resume.updated_at,
        )
        .order_by(*sort_columns)
        .offset(offset)
        .limit(limit)
        .all()
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        f"[DashboardPerf] /api/resumes/summaries user_id={current_user.id} "
        f"offset={offset} limit={limit} returned={len(rows)} total={total} 耗时 {elapsed_ms:.1f}ms"
    )
    return ResumeSummaryPageResponse(
        items=[
            ResumeSummaryResponse(
                id=row.id,
                name=row.name,
                alias=row.alias,
                pinned=row.id in requested_pinned_ids,
                created_at=row.created_at.isoformat() if row.created_at else None,
                updated_at=row.updated_at.isoformat() if row.updated_at else None,
            )
            for row in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{resume_id}", response_model=ResumeResponse)
def get_resume(
    resume_id: str,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取单个简历"""
    resume = db.query(Resume).filter(Resume.id == resume_id, Resume.user_id == current_user.id).first()
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")

    return ResumeResponse(
        id=resume.id,
        name=resume.name,
        alias=resume.alias,
        template_type=_extract_template_type(resume.data),
        data=resume.data,
        created_at=resume.created_at.isoformat() if resume.created_at else None,
        updated_at=resume.updated_at.isoformat() if resume.updated_at else None
    )


@router.post("", response_model=ResumeResponse)
def create_resume(
    payload: ResumePayload,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建简历"""
    resume_id = payload.id or f"resume_{uuid4().hex}"
    name = payload.name or payload.data.get("basic", {}).get("name") or "未命名简历"
    
    # 如果 payload 中有 template_type，确保同步到 data 中
    data = payload.data.copy()
    if payload.template_type:
        data["templateType"] = payload.template_type

    resume = Resume(
        id=resume_id,
        user_id=current_user.id,
        name=name,
        alias=payload.alias,
        data=data
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)

    return ResumeResponse(
        id=resume.id,
        name=resume.name,
        alias=resume.alias,
        template_type=_extract_template_type(resume.data),
        data=resume.data,
        created_at=resume.created_at.isoformat() if resume.created_at else None,
        updated_at=resume.updated_at.isoformat() if resume.updated_at else None
    )


@router.put("/{resume_id}", response_model=ResumeResponse)
def update_resume(
    resume_id: str,
    payload: ResumePayload,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新简历（不存在时自动创建）"""
    resume = db.query(Resume).filter(Resume.id == resume_id, Resume.user_id == current_user.id).first()

    # 如果当前用户下不存在，尝试按 ID 创建（避免前端首次云端保存时 404）
    if not resume:
        # 若该 ID 已被其他用户占用，避免越权覆盖
        occupied = db.query(Resume).filter(Resume.id == resume_id).first()
        if occupied and occupied.user_id != current_user.id:
            raise HTTPException(status_code=409, detail="简历ID已存在，请重试")

        data = payload.data.copy()
        if payload.template_type:
            data["templateType"] = payload.template_type

        created = Resume(
            id=resume_id,
            user_id=current_user.id,
            name=payload.name or data.get("basic", {}).get("name") or "未命名简历",
            alias=payload.alias,
            data=data,
        )
        db.add(created)
        db.commit()
        db.refresh(created)
        return ResumeResponse(
            id=created.id,
            name=created.name,
            alias=created.alias,
            template_type=_extract_template_type(created.data),
            data=created.data,
            created_at=created.created_at.isoformat() if created.created_at else None,
            updated_at=created.updated_at.isoformat() if created.updated_at else None
        )

    # 如果 payload 中有 template_type，确保同步到 data 中
    data = payload.data.copy()
    if payload.template_type:
        data["templateType"] = payload.template_type

    resume.name = payload.name or data.get("basic", {}).get("name") or resume.name
    resume.alias = payload.alias if payload.alias is not None else resume.alias
    resume.data = data
    db.commit()
    db.refresh(resume)

    return ResumeResponse(
        id=resume.id,
        name=resume.name,
        alias=resume.alias,
        template_type=_extract_template_type(resume.data),
        data=resume.data,
        created_at=resume.created_at.isoformat() if resume.created_at else None,
        updated_at=resume.updated_at.isoformat() if resume.updated_at else None
    )


@router.delete("/{resume_id}")
def delete_resume(
    resume_id: str,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除简历"""
    exists = db.query(Resume.id).filter(
        Resume.id == resume_id,
        Resume.user_id == current_user.id
    ).first()
    if not exists:
        raise HTTPException(status_code=404, detail="简历不存在")

    try:
        db.query(ResumeEmbedding).filter(
            ResumeEmbedding.user_id == current_user.id,
            ResumeEmbedding.resume_id == resume_id,
        ).delete(synchronize_session=False)

        # 使用批量删除，避免触发 Resume.user 关系懒加载导致的 mapper flush 异常
        deleted = db.query(Resume).filter(
            Resume.id == resume_id,
            Resume.user_id == current_user.id
        ).delete(synchronize_session=False)
        if deleted == 0:
            db.rollback()
            raise HTTPException(status_code=404, detail="简历不存在")
        db.commit()
        return {"success": True}
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception(f"[Resumes] delete failed user_id={current_user.id} resume_id={resume_id}: {exc}")
        raise HTTPException(status_code=500, detail="删除简历失败，请稍后重试")


@router.post("/sync", response_model=List[ResumeResponse])
def sync_resume_data(
    payload: SyncRequest,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """同步简历数据（localStorage ↔ 数据库）"""
    t0 = time.perf_counter()
    logger.info(f"[同步] 开始同步简历 user_id={current_user.id} 本地条数={len(payload.resumes)}")
    if not payload.resumes:
        logger.info(f"[同步] 跳过同步（本地条数=0）user_id={current_user.id}")
        return []
    merged = sync_resumes(db, current_user, [r.dict() for r in payload.resumes])
    logger.info(
        f"[同步] 同步完成 user_id={current_user.id} 数据库返回条数={len(merged)} 耗时={(time.perf_counter() - t0) * 1000:.1f}ms"
    )
    return [
        ResumeResponse(
            id=r.id,
            name=r.name,
            alias=r.alias,
            template_type=_extract_template_type(r.data),
            data=r.data,
            created_at=r.created_at.isoformat() if r.created_at else None,
            updated_at=r.updated_at.isoformat() if r.updated_at else None
        )
        for r in merged
    ]


def _safe_filename(name: Optional[str], resume_id: str) -> str:
    """简历名 → 安全文件名（去掉路径分隔符/非法字符，空名用 id 兜底）。"""
    raw = (name or "").strip() or resume_id
    # 去掉 Windows/macOS/Linux 文件名非法字符
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", raw)
    return cleaned or resume_id


@router.get("/{resume_id}/export")
def export_resume_json(
    resume_id: str,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """一键导出简历为 .json 文件下载（Content-Disposition: attachment）。

    用途：攒一批样本简历 JSON，后续测试简历解析（/api/resume/parse）时直接
    用这些 JSON 喂解析逻辑，不用每次都走 OCR。返回的是简历完整 data 字段，
    浏览器/curl 会直接存成 `<简历名>.json`。
    """
    resume = db.query(Resume).filter(
        Resume.id == resume_id, Resume.user_id == current_user.id
    ).first()
    if not resume:
        raise HTTPException(status_code=404, detail="简历不存在")

    payload = {
        "id": resume.id,
        "name": resume.name,
        "alias": resume.alias,
        "template_type": _extract_template_type(resume.data),
        "data": resume.data,
        "created_at": resume.created_at.isoformat() if resume.created_at else None,
        "updated_at": resume.updated_at.isoformat() if resume.updated_at else None,
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    filename = _safe_filename(resume.name, resume.id)
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}.json"; filename*=UTF-8\'\'{filename}.json'
        },
    )


@router.post("/{resume_id}/fork", response_model=ResumeResponse)
def fork_resume(
    resume_id: str,
    payload: ForkResumeRequest,
    current_user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """基于现有简历派生（Fork）一个针对特定 JD 的衍生简历版本。"""
    source = db.query(Resume).filter(
        Resume.id == resume_id,
        Resume.user_id == current_user.id
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail="源简历不存在")

    forked_id = f"resume_{uuid4().hex}"
    target_title = payload.target_jd_title or "定制岗位"
    forked_name = payload.custom_name or f"{source.name} ({target_title}定制版)"
    forked_alias = f"JD定制: {target_title}"

    forked_data = json.loads(json.dumps(source.data or {}))
    meta = forked_data.setdefault("_meta", {})
    meta["forkedFrom"] = source.id
    meta["forkedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if payload.target_jd_title or payload.target_company or payload.jd_text:
        meta["targetJd"] = {
            "title": payload.target_jd_title,
            "company": payload.target_company,
            "snippet": (payload.jd_text or "")[:500],
        }

    forked_resume = Resume(
        id=forked_id,
        user_id=current_user.id,
        name=forked_name,
        alias=forked_alias,
        data=forked_data,
    )
    db.add(forked_resume)
    db.commit()
    db.refresh(forked_resume)

    return ResumeResponse(
        id=forked_resume.id,
        name=forked_resume.name,
        alias=forked_resume.alias,
        template_type=_extract_template_type(forked_resume.data),
        data=forked_resume.data,
        created_at=forked_resume.created_at.isoformat() if forked_resume.created_at else None,
        updated_at=forked_resume.updated_at.isoformat() if forked_resume.updated_at else None,
    )
