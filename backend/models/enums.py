"""Reusable enums for BNPL domain models."""

from enum import Enum


class StringEnum(str, Enum):
    """Base enum class with string behavior for JSON serialization."""


class UserStatus(StringEnum):
    """User account lifecycle states."""

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BLOCKED = "BLOCKED"


class UserRole(StringEnum):
    """Role names used for API authorization checks."""

    USER = "USER"
    ADMIN = "ADMIN"
    MERCHANT = "MERCHANT"
    SUPPORT = "SUPPORT"
    REVIEWER = "REVIEWER"
    LIQUIDATOR = "LIQUIDATOR"
    PAUSER = "PAUSER"


class KycStatus(StringEnum):
    """KYC verification lifecycle states."""

    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ScreeningStatus(StringEnum):
    """AML/sanctions screening result states."""

    NOT_SCREENED = "NOT_SCREENED"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    BLOCKED = "BLOCKED"


class LoanStatus(StringEnum):
    """Loan lifecycle states."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    OVERDUE = "OVERDUE"
    DEFAULTED = "DEFAULTED"
    CLOSED = "CLOSED"
    DISPUTE_OPEN = "DISPUTE_OPEN"
    PENDING_KYC = "PENDING_KYC"
    ELIGIBLE = "ELIGIBLE"
    DELINQUENT = "DELINQUENT"
    DISPUTED = "DISPUTED"
    PARTIALLY_RECOVERED = "PARTIALLY_RECOVERED"
    CANCELLED = "CANCELLED"


class InstallmentStatus(StringEnum):
    """Installment payment states."""

    UPCOMING = "UPCOMING"
    DUE = "DUE"
    PAID = "PAID"
    MISSED = "MISSED"
    WAIVED = "WAIVED"


class CollateralStatus(StringEnum):
    """Collateral lifecycle states."""

    LOCKED = "LOCKED"
    TOPPED_UP = "TOPPED_UP"
    PARTIALLY_RECOVERED = "PARTIALLY_RECOVERED"
    RELEASED = "RELEASED"


class RiskTier(StringEnum):
    """Risk classification tiers."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class LiquidationActionType(StringEnum):
    """Recovery action categories."""

    PARTIAL_RECOVERY = "PARTIAL_RECOVERY"
    FULL_RECOVERY = "FULL_RECOVERY"
    PENALTY_APPLIED = "PENALTY_APPLIED"


class DisputeCategory(StringEnum):
    """Supported dispute categories."""

    ITEM_NOT_DELIVERED = "ITEM_NOT_DELIVERED"
    WRONG_ITEM = "WRONG_ITEM"
    PAYMENT_ISSUE = "PAYMENT_ISSUE"
    DUPLICATE_CHARGE = "DUPLICATE_CHARGE"
    FRAUD = "FRAUD"
    SERVICE_ISSUE = "SERVICE_ISSUE"


class MerchantStatus(StringEnum):
    """Merchant onboarding and lifecycle status."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    BLOCKED = "BLOCKED"


class SettlementStatus(StringEnum):
    """Merchant settlement lifecycle status."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PAID = "PAID"
    FAILED = "FAILED"
    REVERSED = "REVERSED"
