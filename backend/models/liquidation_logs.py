"""Liquidation and recovery audit model."""

from datetime import datetime
import logging
from typing import Optional

from pydantic import Field, root_validator

from .base import BaseDocumentModel, Money
from .enums import LiquidationActionType


logger = logging.getLogger(__name__)


class LiquidationLogModel(BaseDocumentModel):
    """Represents a liquidation or partial recovery event."""

    log_id: str = Field(..., min_length=3)
    loan_id: str = Field(..., min_length=3)
    user_id: str = Field(..., min_length=3)
    collateral_id: str = Field(..., min_length=3)

    triggered_at: datetime = Field(...)
    trigger_reason: str = Field(..., min_length=3)
    health_factor_at_trigger: float = Field(..., ge=0.0)

    missed_amount_minor: Money = Field(..., ge=0)
    penalty_minor: Money = Field(default=0, ge=0)
    needed_minor: Money = Field(..., ge=0)
    seized_minor: Money = Field(..., ge=0)
    returned_minor: Money = Field(default=0, ge=0)

    merchant_transfer_ref: Optional[str] = Field(default=None)
    tx_hash: Optional[str] = Field(default=None)
    action_type: LiquidationActionType = Field(...)

    initiated_by_role: str = Field(..., min_length=3)
    policy_version: str = Field(default="v1")
    notes: Optional[str] = Field(default=None)

    @root_validator(skip_on_failure=True)
    def _validate_recovery_math(cls, values: dict) -> dict:
        """Validate recovery constraints for partial/full liquidation events."""
        try:
            seized_minor = int(values.get("seized_minor", 0))
            needed_minor = int(values.get("needed_minor", 0))
            returned_minor = int(values.get("returned_minor", 0))
            missed_amount_minor = int(values.get("missed_amount_minor", 0))
            penalty_minor = int(values.get("penalty_minor", 0))

            if seized_minor > needed_minor:
                raise ValueError("seized_minor cannot exceed needed_minor")

            if needed_minor < missed_amount_minor + penalty_minor:
                raise ValueError("needed_minor must cover missed_amount_minor + penalty_minor")

            if returned_minor < 0:
                raise ValueError("returned_minor cannot be negative")

            return values
        except Exception:
            logger.exception(
                "Liquidation validation failed log_id=%s loan_id=%s",
                values.get("log_id"),
                values.get("loan_id"),
            )
            raise
