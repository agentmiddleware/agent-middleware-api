from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PolicyBundleCreate(BaseModel):
    wallet_id: str
    name: str = Field(..., min_length=1)
    allowed_tools: list[str] | None = None
    allowed_service_categories: list[str] | None = None
    max_cost_per_action: float | None = Field(default=None, ge=0)
    daily_spend_limit: float | None = Field(default=None, ge=0)
    require_real_effects: bool = False
    risk_tier: str = "medium"
    human_approval_required: bool = False
    is_active: bool = True


class PolicyBundlePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    allowed_tools: list[str] | None = None
    allowed_service_categories: list[str] | None = None
    max_cost_per_action: float | None = Field(default=None, ge=0)
    daily_spend_limit: float | None = Field(default=None, ge=0)
    require_real_effects: bool | None = None
    risk_tier: str | None = None
    human_approval_required: bool | None = None
    is_active: bool | None = None


class PolicyBundleResponse(BaseModel):
    policy_id: str
    wallet_id: str
    name: str
    allowed_tools: list[str] | None
    allowed_service_categories: list[str] | None
    max_cost_per_action: float | None
    daily_spend_limit: float | None
    require_real_effects: bool
    risk_tier: str
    human_approval_required: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PolicyBundleListResponse(BaseModel):
    policies: list[PolicyBundleResponse]
    total: int
