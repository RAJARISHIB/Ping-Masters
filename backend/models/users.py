"""User domain model for borrower profiles and behavior signals."""

import logging
from typing import List, Optional

from pydantic import Field, validator

from .base import BaseDocumentModel
from .enums import UserStatus


logger = logging.getLogger(__name__)


class UserModel(BaseDocumentModel):
    """Represents a borrower account in the BNPL system."""

    user_id: str = Field(..., min_length=3)
    email: str = Field(..., min_length=5)
    phone: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=2)
    autopay_enabled: bool = Field(default=False)
    notification_channels: List[str] = Field(default_factory=list)
    status: UserStatus = Field(default=UserStatus.ACTIVE)
    kyc_level: int = Field(default=0, ge=0, le=3)
    wallet_address: Optional[str] = Field(default=None)
    on_time_payment_count: int = Field(default=0, ge=0)
    late_payment_count: int = Field(default=0, ge=0)
    top_up_count: int = Field(default=0, ge=0)

    @validator("notification_channels", pre=True, always=True)
    def _normalize_channels(cls, value: List[str]) -> List[str]:
        """Normalize notification channel list to lowercase unique values."""
        try:
            channels = [str(channel).strip().lower() for channel in (value or []) if str(channel).strip()]
            return sorted(set(channels))
        except Exception:
            logger.exception("Failed to normalize notification channels.")
            return []
