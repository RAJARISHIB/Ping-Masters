"""Installment model for payment schedule and delinquency tracking."""

from datetime import datetime
import logging
from typing import Dict, List, Optional

from pydantic import Field

from .base import BaseDocumentModel, Money
from .enums import InstallmentStatus
from .exceptions import ModelValidationError


logger = logging.getLogger(__name__)


class InstallmentModel(BaseDocumentModel):
    """Represents an individual installment in a BNPL repayment schedule."""

    installment_id: str = Field(..., min_length=3)
    loan_id: str = Field(..., min_length=3)
    user_id: str = Field(..., min_length=3)

    sequence_no: int = Field(..., gt=0)
    due_at: datetime = Field(...)
    amount_minor: Money = Field(..., ge=0)

    paid_minor: Money = Field(default=0, ge=0)
    paid_at: Optional[datetime] = Field(default=None)
    payment_ref: Optional[str] = Field(default=None)

    status: InstallmentStatus = Field(default=InstallmentStatus.UPCOMING)
    grace_deadline: Optional[datetime] = Field(default=None)
    late_fee_minor: Money = Field(default=0, ge=0)
    missed_reason: Optional[str] = Field(default=None)

    calculation_trace: Dict[str, str] = Field(default_factory=dict)

    @classmethod
    def validate_schedule(cls, installments: List["InstallmentModel"], expected_total_minor: Money) -> None:
        """Validate ordering and aggregate total for an installment schedule.

        Args:
            installments: Installment list for one loan.
            expected_total_minor: Expected aggregate amount for all installments.

        Raises:
            ModelValidationError: If ordering or total constraints fail.
        """
        try:
            if not installments:
                raise ModelValidationError("Installment schedule cannot be empty")

            ordered = sorted(installments, key=lambda item: item.sequence_no)
            for index, installment in enumerate(ordered, start=1):
                if installment.sequence_no != index:
                    raise ModelValidationError("Installment sequence numbers must be continuous from 1")

            total_minor = sum(item.amount_minor for item in ordered)
            if total_minor != expected_total_minor:
                raise ModelValidationError("Installment sum does not match expected total")
        except ModelValidationError:
            raise
        except Exception as exc:
            logger.exception("Failed schedule validation for installments.")
            raise ModelValidationError(str(exc))
