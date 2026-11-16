"""
Billing routes — mock checkout for development.
Real Creem webhook handler will replace mock_checkout when payment goes live.
"""
import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.api_docs import is_production_env
from backend.database import get_db
from backend.better_auth import BetterAuthUser, get_current_better_auth_user
from backend.services.better_auth_entitlements import get_or_create_entitlement

router = APIRouter(prefix="/api/billing", tags=["Billing"])

MOCK_PLANS = {
    "starter": {"credits": 50,  "plan": "starter"},
    "pro":     {"credits": 200, "plan": "pro"},
}


class MockCheckoutRequest(BaseModel):
    package: str  # "starter" | "pro"


class EntitlementResponse(BaseModel):
    plan: str
    credits: int
    daily_usage_count: int
    subscription_status: str


@router.post("/mock-checkout", response_model=EntitlementResponse)
async def mock_checkout(
    body: MockCheckoutRequest,
    current_user: BetterAuthUser = Depends(get_current_better_auth_user),
    db: Session = Depends(get_db),
) -> EntitlementResponse:
    """Mock 支付：直接充值 credits，无真实扣款。上线 Creem 后替换此端点。"""
    if is_production_env() and os.getenv("ALLOW_MOCK_CHECKOUT", "").strip().lower() not in {"1", "true", "yes"}:
        raise HTTPException(status_code=403, detail="生产环境已禁用模拟充值")

    pkg = MOCK_PLANS.get(body.package)
    if not pkg:
        raise HTTPException(status_code=400, detail=f"Unknown package: {body.package}")

    entitlement = get_or_create_entitlement(db, current_user)
    entitlement.credits += pkg["credits"]
    entitlement.plan = pkg["plan"]
    entitlement.subscription_status = "active"
    db.commit()
    db.refresh(entitlement)

    return EntitlementResponse(
        plan=entitlement.plan,
        credits=entitlement.credits,
        daily_usage_count=entitlement.daily_usage_count,
        subscription_status=entitlement.subscription_status,
    )
