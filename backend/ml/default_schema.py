"""Schema for default prediction inference payloads."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, validator


class DefaultPredictionInput(BaseModel):
    """Input features for next-installment default prediction."""

    user_id: Optional[str] = Field(default=None)
    plan_id: Optional[str] = Field(default=None)
    installment_id: Optional[str] = Field(default=None)
    cutoff_at: Optional[datetime] = Field(default=None)

    on_time_ratio: float = Field(..., ge=0, le=1)
    missed_count_90d: int = Field(..., ge=0)
    max_days_late_180d: float = Field(..., ge=0)
    avg_days_late: float = Field(..., ge=0)
    days_since_last_late: float = Field(..., ge=0)
    consecutive_on_time_count: int = Field(..., ge=0)

    plan_amount: float = Field(..., gt=0)
    tenure_days: int = Field(..., gt=0)
    installment_amount: float = Field(..., gt=0)
    installment_number: int = Field(..., gt=0)
    days_until_due: float = Field(..., ge=0)

    current_safety_ratio: float = Field(..., gt=0)
    distance_to_liquidation_threshold: float = Field(..., ge=-5)
    collateral_type: str = Field(default="volatile", min_length=6)
    collateral_volatility_bucket: str = Field(default="high", min_length=3)
    topup_count_30d: int = Field(..., ge=0)
    topup_recency_days: float = Field(..., ge=0)

    opened_app_last_7d: int = Field(..., ge=0, le=1)
    clicked_pay_now_last_7d: int = Field(..., ge=0, le=1)
    payment_attempt_failed_count: int = Field(..., ge=0)

    wallet_age_days: float = Field(..., ge=0)
    tx_count_30d: int = Field(..., ge=0)
    stablecoin_balance_bucket: str = Field(default="medium", min_length=3)

    @validator("collateral_type")
    def _normalize_collateral_type(cls, value: str) -> str:
        """Normalize collateral type category."""
        normalized = value.strip().lower()
        if normalized not in {"stable", "volatile"}:
            raise ValueError("collateral_type must be 'stable' or 'volatile'")
        return normalized

    @validator("collateral_volatility_bucket")
    def _normalize_volatility_bucket(cls, value: str) -> str:
        """Normalize volatility bucket."""
        normalized = value.strip().lower()
        if normalized not in {"low", "medium", "high"}:
            raise ValueError("collateral_volatility_bucket must be low/medium/high")
        return normalized

    @validator("stablecoin_balance_bucket")
    def _normalize_balance_bucket(cls, value: str) -> str:
        """Normalize stablecoin balance bucket."""
        normalized = value.strip().lower()
        if normalized not in {"low", "medium", "high"}:
            raise ValueError("stablecoin_balance_bucket must be low/medium/high")
        return normalized
