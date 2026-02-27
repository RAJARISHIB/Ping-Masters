"""User domain model for borrower profiles and behavior signals."""

from datetime import datetime
import logging
from typing import List, Optional

from pydantic import BaseModel, Field, validator

from .base import BaseDocumentModel
from .enums import KycStatus, ScreeningStatus, UserRole, UserStatus


logger = logging.getLogger(__name__)


class WalletAddressModel(BaseModel):
    """Wallet metadata entry for a user profile."""

    name: str = Field(..., min_length=2)
    wallet_id: str = Field(..., min_length=6)


class UserModel(BaseDocumentModel):
    """Represents a borrower account in the BNPL system."""

    user_id: str = Field(..., min_length=3)
    email: str = Field(..., min_length=5)
    phone: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=2)
    currency_code: str = Field(default="INR", min_length=3, max_length=3)
    currency_symbol: str = Field(default="Rs", min_length=1, max_length=3)
    autopay_enabled: bool = Field(default=False)
    notification_channels: List[str] = Field(default_factory=list)
    status: UserStatus = Field(default=UserStatus.ACTIVE)
    role: UserRole = Field(default=UserRole.USER)
    kyc_level: int = Field(default=0, ge=0, le=3)
    kyc_status: KycStatus = Field(default=KycStatus.NOT_STARTED)
    kyc_last_updated_at: Optional[datetime] = Field(default=None)
    kyc_reject_reason: Optional[str] = Field(default=None)
    aml_status: ScreeningStatus = Field(default=ScreeningStatus.NOT_SCREENED)
    aml_last_screened_at: Optional[datetime] = Field(default=None)
    aml_screening_reference: Optional[str] = Field(default=None)
    wallet_address: List[WalletAddressModel] = Field(default_factory=list)
    verified_wallets: List[str] = Field(default_factory=list)
    wallet_verified_at: Optional[datetime] = Field(default=None)
    wallet_verification_chain: Optional[str] = Field(default=None)
    on_time_payment_count: int = Field(default=0, ge=0)
    late_payment_count: int = Field(default=0, ge=0)
    top_up_count: int = Field(default=0, ge=0)
    loan_currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    total_borrowed_fiat: float = Field(default=0.0, ge=0.0)
    total_repaid_fiat: float = Field(default=0.0, ge=0.0)
    outstanding_debt_fiat: float = Field(default=0.0, ge=0.0)
    last_loan_action: Optional[str] = Field(default=None)
    last_loan_action_at: Optional[datetime] = Field(default=None)

    @validator("notification_channels", pre=True, always=True)
    def _normalize_channels(cls, value: List[str]) -> List[str]:
        """Normalize notification channel list to lowercase unique values."""
        try:
            channels = [str(channel).strip().lower() for channel in (value or []) if str(channel).strip()]
            return sorted(set(channels))
        except Exception:
            logger.exception("Failed to normalize notification channels.")
            return []

    @validator("wallet_address", pre=True, always=True)
    def _normalize_wallet_address(cls, value: Optional[List[dict]]) -> List[dict]:
        """Normalize missing wallet list to an empty array for stable storage."""
        try:
            return value or []
        except Exception:
            logger.exception("Failed to normalize wallet_address payload.")
            return []

    @validator("verified_wallets", pre=True, always=True)
    def _normalize_verified_wallets(cls, value: Optional[List[str]]) -> List[str]:
        """Normalize verified wallet list to lowercase unique values."""
        try:
            wallets = [str(wallet).strip().lower() for wallet in (value or []) if str(wallet).strip()]
            return sorted(set(wallets))
        except Exception:
            logger.exception("Failed to normalize verified_wallets payload.")
            return []

    @validator("currency_code")
    def _normalize_currency_code(cls, value: str) -> str:
        """Normalize currency code to upper-case ISO style."""
        try:
            return value.upper()
        except Exception:
            logger.exception("Failed to normalize currency_code value=%s", value)
            return value

    @validator("loan_currency")
    def _normalize_loan_currency(cls, value: Optional[str]) -> Optional[str]:
        """Normalize loan currency to upper-case when present."""
        if value is None:
            return None
        try:
            return value.upper()
        except Exception:
            logger.exception("Failed to normalize loan_currency value=%s", value)
            return value
