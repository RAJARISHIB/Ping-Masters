"""Schema definitions for ML feature input and output."""

from pydantic import BaseModel, Field


class RiskFeatureInput(BaseModel):
    """Input features used by risk model inference."""

    safety_ratio: float = Field(..., gt=0)
    missed_payment_count: int = Field(..., ge=0)
    on_time_ratio: float = Field(..., ge=0, le=1)
    avg_delay_hours: float = Field(..., ge=0)
    topup_count_last_30d: int = Field(..., ge=0)
    plan_amount: float = Field(..., gt=0)
    tenure_days: int = Field(..., gt=0)
    installment_amount: float = Field(..., gt=0)
