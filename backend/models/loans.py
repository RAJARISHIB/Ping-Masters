"""Loan domain model for BNPL plans and policy thresholds."""

from datetime import datetime
import logging
from typing import List, Optional

from pydantic import Field, root_validator, validator

from .base import BaseDocumentModel, Money, PercentageBps
from .enums import LoanStatus


logger = logging.getLogger(__name__)


class LoanModel(BaseDocumentModel):
    """Represents a BNPL loan with risk and repayment policy settings."""

    loan_id: str = Field(..., min_length=3)
    user_id: str = Field(..., min_length=3)
    merchant_id: str = Field(..., min_length=3)

    principal_minor: Money = Field(..., ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    tenure_days: int = Field(..., gt=0)
    installment_count: int = Field(..., gt=0)

    ltv_bps: PercentageBps = Field(..., ge=0, le=10000)
    borrow_limit_minor: Money = Field(..., ge=0)
    danger_limit_bps: PercentageBps = Field(..., ge=0, le=10000)
    liquidation_threshold_bps: PercentageBps = Field(..., ge=0, le=10000)

    schedule_hash: Optional[str] = Field(default=None)
    installment_ids: List[str] = Field(default_factory=list)
    emi_plan_id: Optional[str] = Field(default=None, min_length=3)
    emi_plan_name: Optional[str] = Field(default=None)
    emi_source_platform: Optional[str] = Field(default=None)

    grace_window_hours: int = Field(default=24, ge=0)
    late_fee_flat_minor: Money = Field(default=0, ge=0)
    late_fee_bps: PercentageBps = Field(default=0, ge=0, le=10000)

    status: LoanStatus = Field(default=LoanStatus.DRAFT)
    dispute_state: Optional[str] = Field(default=None)
    paused_penalties_until: Optional[datetime] = Field(default=None)

    outstanding_minor: Money = Field(default=0, ge=0)
    paid_minor: Money = Field(default=0, ge=0)
    penalty_accrued_minor: Money = Field(default=0, ge=0)

    @validator("currency")
    def _uppercase_currency(cls, value: str) -> str:
        """Force ISO-like uppercase currency formatting."""
        try:
            return value.upper()
        except Exception:
            logger.exception("Failed to normalize currency value=%s", value)
            return value

    @root_validator(skip_on_failure=True)
    def _validate_business_rules(cls, values: dict) -> dict:
        """Validate loan policy and balance rules."""
        try:
            danger_limit_bps = int(values.get("danger_limit_bps", 0))
            liquidation_threshold_bps = int(values.get("liquidation_threshold_bps", 0))
            outstanding_minor = int(values.get("outstanding_minor", 0))
            principal_minor = int(values.get("principal_minor", 0))
            penalty_accrued_minor = int(values.get("penalty_accrued_minor", 0))
            status = values.get("status")
            paused_penalties_until = values.get("paused_penalties_until")

            if danger_limit_bps >= liquidation_threshold_bps:
                raise ValueError("danger_limit_bps must be lower than liquidation_threshold_bps")

            if outstanding_minor > principal_minor + penalty_accrued_minor:
                raise ValueError("outstanding_minor exceeds principal + penalty_accrued_minor")

            if status in {LoanStatus.DISPUTE_OPEN, LoanStatus.DISPUTED} and paused_penalties_until is None:
                raise ValueError("paused_penalties_until is required when status is DISPUTE_OPEN")

            return values
        except Exception:
            logger.exception(
                "Loan validation failed loan_id=%s user_id=%s",
                values.get("loan_id"),
                values.get("user_id"),
            )
            raise
