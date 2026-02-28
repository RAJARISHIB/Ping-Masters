"""Collateral domain model for deposit vault and recovery tracking."""

import logging
from typing import Optional

from pydantic import Field, root_validator

from .base import BaseDocumentModel, Money
from .enums import CollateralStatus


logger = logging.getLogger(__name__)


class CollateralModel(BaseDocumentModel):
    """Represents user collateral backing a BNPL loan."""

    collateral_id: str = Field(..., min_length=3)
    user_id: str = Field(..., min_length=3)
    loan_id: str = Field(..., min_length=3)

    vault_address: str = Field(..., min_length=6)
    chain_id: int = Field(..., gt=0)
    deposit_tx_hash: str = Field(..., min_length=8)

    asset_symbol: str = Field(..., min_length=2)
    asset_type: str = Field(default="TOKEN")
    decimals: int = Field(default=18, ge=0, le=30)

    deposited_units: float = Field(..., ge=0.0)
    collateral_value_minor: Money = Field(..., ge=0)
    oracle_price_minor: Money = Field(..., ge=0)

    health_factor: float = Field(default=0.0, ge=0.0)
    safety_color: str = Field(default="green")

    recoverable_minor: Money = Field(default=0, ge=0)
    recovered_minor: Money = Field(default=0, ge=0)
    status: CollateralStatus = Field(default=CollateralStatus.LOCKED)
    proof_page_url: Optional[str] = Field(default=None)

    @root_validator(skip_on_failure=True)
    def _validate_recovery(cls, values: dict) -> dict:
        """Ensure recovered collateral does not exceed recoverable amount."""
        try:
            recoverable_minor = int(values.get("recoverable_minor", 0))
            recovered_minor = int(values.get("recovered_minor", 0))
            if recovered_minor > recoverable_minor:
                raise ValueError("recovered_minor cannot exceed recoverable_minor")
            return values
        except Exception:
            logger.exception(
                "Collateral validation failed collateral_id=%s loan_id=%s",
                values.get("collateral_id"),
                values.get("loan_id"),
            )
            raise
