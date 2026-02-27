"""Reusable enums for BNPL domain models."""

from enum import Enum


class StringEnum(str, Enum):
    """Base enum class with string behavior for JSON serialization."""


class UserStatus(StringEnum):
    """User account lifecycle states."""

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
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
