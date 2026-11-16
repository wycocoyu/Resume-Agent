"""Health check routes.

Provides health check endpoints for monitoring.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["Agent"])


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str = "1.0.0"


@router.get("", response_model=HealthResponse)
@router.get("/", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check if the service is healthy.

    Returns:
        HealthResponse with status and version
    """
    return HealthResponse(status="healthy")


@router.get("/ping")
async def ping() -> dict[str, str]:
    """Simple ping endpoint.

    Returns:
        dict with "pong" message
    """
    return {"message": "pong"}
