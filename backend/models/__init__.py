"""Public model package exports for Ping Masters backend."""

from .base import BaseDocumentModel, Money, PercentageBps
from .collaterals import CollateralModel
from .enums import (
    CollateralStatus,
    InstallmentStatus,
    LiquidationActionType,
    LoanStatus,
    RiskTier,
    UserStatus,
)
from .exceptions import ModelError, ModelNotFoundError, ModelValidationError, VersionConflictError
from .installments import InstallmentModel
from .liquidation_logs import LiquidationLogModel
from .loans import LoanModel
from .repositories import (
    CollateralRepository,
    InstallmentRepository,
    LiquidationLogRepository,
    LoanRepository,
    RiskScoreRepository,
    UserRepository,
)
from .risk_scores import RiskScoreModel
from .users import UserModel, WalletAddressModel

__all__ = [
    "BaseDocumentModel",
    "Money",
    "PercentageBps",
    "UserModel",
    "WalletAddressModel",
    "LoanModel",
    "CollateralModel",
    "RiskScoreModel",
    "InstallmentModel",
    "LiquidationLogModel",
    "UserStatus",
    "LoanStatus",
    "CollateralStatus",
    "RiskTier",
    "InstallmentStatus",
    "LiquidationActionType",
    "ModelError",
    "ModelValidationError",
    "ModelNotFoundError",
    "VersionConflictError",
    "UserRepository",
    "LoanRepository",
    "CollateralRepository",
    "RiskScoreRepository",
    "InstallmentRepository",
    "LiquidationLogRepository",
]
