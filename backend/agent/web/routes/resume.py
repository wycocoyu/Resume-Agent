"""Resume data routes.

Provides endpoints for resume data management.
"""

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/resume", tags=["Agent"])

# Default resume path
DEFAULT_RESUME_DIR = Path("app/docs")
DEFAULT_RESUME_FILE = "韦宇_简历.md"


@router.get("/")  # 🔴 添加 /resume 端点，供前端获取简历数据
async def get_resume_data() -> dict[str, Any]:
    """Get full resume data for frontend rendering.

    Returns:
        dict with parsed resume data
    """
    from backend.agent.utils.resume_parser import parse_markdown_resume

    resume_path = DEFAULT_RESUME_DIR / DEFAULT_RESUME_FILE

    if not resume_path.exists():
        return {"data": {}}

    try:
        data = parse_markdown_resume(str(resume_path))
        return {"data": data}
    except Exception as e:
        logger.error(f"Error parsing resume: {e}")
        return {"data": {}}


class ResumeData(BaseModel):
    """Resume data response."""

    name: Optional[str] = None
    content: str
    file_path: str


class ResumeSection(BaseModel):
    """Resume section data."""

    section: str
    content: str


@router.get("/content", response_model=ResumeData)
async def get_resume_content(
    file_path: Optional[str] = None,
) -> ResumeData:
    """Get resume content from file.

    Args:
        file_path: Optional path to resume file. Uses default if not provided.

    Returns:
        ResumeData with content and metadata

    Raises:
        HTTPException: If file not found or cannot be read
    """
    if file_path:
        resume_path = Path(file_path)
    else:
        resume_path = DEFAULT_RESUME_DIR / DEFAULT_RESUME_FILE

    if not resume_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Resume file not found: {resume_path}",
        )

    try:
        content = resume_path.read_text(encoding="utf-8")

        # Try to extract name from content
        name = None
        for line in content.split("\n")[:10]:
            line = line.strip()
            if line.startswith("# "):
                name = line.lstrip("#").strip()
                break
            elif "姓名" in line or "name" in line.lower():
                # Try to extract from "姓名: XXX" format
                if ":" in line or "：" in line:
                    name = line.split(":", 1)[-1].split("：", 1)[-1].strip()
                    break

        return ResumeData(
            name=name,
            content=content,
            file_path=str(resume_path),
        )
    except Exception as e:
        logger.error(f"Error reading resume: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error reading resume file: {e}",
        )


@router.get("/section/{section_name}")
async def get_resume_section(
    section_name: str,
    file_path: Optional[str] = None,
) -> dict:
    """Get a specific section from the resume.

    Args:
        section_name: The section name to retrieve (e.g., "basic_info", "education")
        file_path: Optional path to resume file

    Returns:
        dict with section content

    Raises:
        HTTPException: If file not found or section not found
    """
    if file_path:
        resume_path = Path(file_path)
    else:
        resume_path = DEFAULT_RESUME_DIR / DEFAULT_RESUME_FILE

    if not resume_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Resume file not found: {resume_path}",
        )

    try:
        content = resume_path.read_text(encoding="utf-8")

        # Simple section extraction based on markdown headers
        lines = content.split("\n")
        section_lines = []
        in_section = False
        section_header = f"## {section_name}"

        for line in lines:
            if line.strip().startswith("## "):
                if in_section:
                    break
                if section_name.lower() in line.lower():
                    in_section = True
                    continue
            elif in_section:
                section_lines.append(line)

        if not section_lines:
            raise HTTPException(
                status_code=404,
                detail=f"Section '{section_name}' not found in resume",
            )

        return {
            "section": section_name,
            "content": "\n".join(section_lines).strip(),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading resume section: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error reading resume section: {e}",
        )


@router.get("/list")
async def list_resumes() -> dict[str, list[dict[str, str]]]:
    """List available resume files.

    Returns:
        dict with list of resume files
    """
    try:
        if not DEFAULT_RESUME_DIR.exists():
            return {"files": []}

        files = []
        for file_path in DEFAULT_RESUME_DIR.glob("*.md"):
            files.append({
                "name": file_path.name,
                "path": str(file_path),
                "size": file_path.stat().st_size,
            })

        return {"files": files}
    except Exception as e:
        logger.error(f"Error listing resumes: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error listing resumes: {e}",
        )
