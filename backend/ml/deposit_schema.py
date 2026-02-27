"""Schema definitions for deposit recommendation APIs."""

from typing import Optional

from pydantic import BaseModel, Field, validator


class DepositRecommendationRequest(BaseModel):
    """Input payload for dynamic deposit recommendation."""

    plan_amount_inr: float = Field(..., gt=0)
    tenure_days: int = Field(..., gt=0)
    risk_tier: str = Field(..., min_length=3)
    collateral_token: str = Field(default="BNB", min_length=2)
    collateral_type: str = Field(default="volatile", min_length=6)
    locked_token: float = Field(default=0.0, ge=0.0)
    price_inr: float = Field(..., gt=0)
    stress_drop_pct: Optional[float] = Field(default=None, ge=0.0, lt=1.0)
    fees_buffer_pct: Optional[float] = Field(default=0.03, ge=0.0, lt=1.0)
    outstanding_debt_inr: Optional[float] = Field(default=None, ge=0.0)

    @validator("risk_tier")
    def _normalize_risk_tier(cls, value: str) -> str:
        """Normalize risk tier values."""
        return value.strip().upper()

    @validator("collateral_type")
    def _normalize_collateral_type(cls, value: str) -> str:
        """Normalize collateral type values."""
        normalized = value.strip().lower()
        if normalized not in {"stable", "volatile"}:
            raise ValueError("collateral_type must be 'stable' or 'volatile'")
        return normalized
