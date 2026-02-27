"""Repository interfaces for datastore-agnostic model access."""

from abc import ABC, abstractmethod
from datetime import datetime
import logging
from typing import List, Optional

from pydantic import ValidationError

from .collaterals import CollateralModel
from .exceptions import ModelNotFoundError, VersionConflictError
from .installments import InstallmentModel
from .liquidation_logs import LiquidationLogModel
from .loans import LoanModel
from .risk_scores import RiskScoreModel
from .users import UserModel


logger = logging.getLogger(__name__)


class BaseRepository(ABC):
    """Common contract for CRUD and soft-delete operations."""

    @abstractmethod
    def create(self, model):
        """Persist a new model."""

    @abstractmethod
    def get_by_id(self, model_id: str):
        """Return model by identifier."""

    @abstractmethod
    def update(self, model):
        """Update existing model with optimistic version check."""

    @abstractmethod
    def soft_delete(self, model_id: str) -> None:
        """Mark a model as deleted."""


class UserRepository(BaseRepository):
    """User data access abstraction."""

    @abstractmethod
    def create(self, model: UserModel) -> UserModel:
        """Persist a new user model."""

    @abstractmethod
    def get_by_id(self, model_id: str) -> UserModel:
        """Fetch a user by identifier.

        Raises:
            ModelNotFoundError: If user does not exist.
            ValidationError: If payload is malformed.
        """

    @abstractmethod
    def update(self, model: UserModel) -> UserModel:
        """Update user document.

        Raises:
            ModelNotFoundError: If user does not exist.
            VersionConflictError: If version does not match persisted document.
            ValidationError: If payload is malformed.
        """

    @abstractmethod
    def soft_delete(self, model_id: str) -> None:
        """Soft delete user document."""

    @abstractmethod
    def get_active_users(self) -> List[UserModel]:
        """Fetch active users only."""


class LoanRepository(BaseRepository):
    """Loan data access abstraction."""

    @abstractmethod
    def create(self, model: LoanModel) -> LoanModel:
        """Persist a new loan model."""

    @abstractmethod
    def get_by_id(self, model_id: str) -> LoanModel:
        """Fetch a loan by identifier.

        Raises:
            ModelNotFoundError: If loan does not exist.
            ValidationError: If payload is malformed.
        """

    @abstractmethod
    def update(self, model: LoanModel) -> LoanModel:
        """Update loan document.

        Raises:
            ModelNotFoundError: If loan does not exist.
            VersionConflictError: If version does not match persisted document.
            ValidationError: If payload is malformed.
        """

    @abstractmethod
    def soft_delete(self, model_id: str) -> None:
        """Soft delete loan document."""

    @abstractmethod
    def get_active_loans_by_user(self, user_id: str) -> List[LoanModel]:
        """Return active loans for a user."""


class CollateralRepository(BaseRepository):
    """Collateral data access abstraction."""

    @abstractmethod
    def create(self, model: CollateralModel) -> CollateralModel:
        """Persist new collateral document."""

    @abstractmethod
    def get_by_id(self, model_id: str) -> CollateralModel:
        """Fetch collateral by identifier."""

    @abstractmethod
    def update(self, model: CollateralModel) -> CollateralModel:
        """Update collateral document."""

    @abstractmethod
    def soft_delete(self, model_id: str) -> None:
        """Soft delete collateral document."""

    @abstractmethod
    def get_by_loan_id(self, loan_id: str) -> List[CollateralModel]:
        """Return collateral documents for a loan."""


class RiskScoreRepository(BaseRepository):
    """Risk score data access abstraction."""

    @abstractmethod
    def create(self, model: RiskScoreModel) -> RiskScoreModel:
        """Persist risk score snapshot."""

    @abstractmethod
    def get_by_id(self, model_id: str) -> RiskScoreModel:
        """Fetch risk score by identifier."""

    @abstractmethod
    def update(self, model: RiskScoreModel) -> RiskScoreModel:
        """Update risk score snapshot."""

    @abstractmethod
    def soft_delete(self, model_id: str) -> None:
        """Soft delete risk score document."""

    @abstractmethod
    def get_latest_by_user(self, user_id: str) -> Optional[RiskScoreModel]:
        """Fetch most recent risk score for a user."""


class InstallmentRepository(BaseRepository):
    """Installment data access abstraction."""

    @abstractmethod
    def create(self, model: InstallmentModel) -> InstallmentModel:
        """Persist installment document."""

    @abstractmethod
    def get_by_id(self, model_id: str) -> InstallmentModel:
        """Fetch installment by identifier."""

    @abstractmethod
    def update(self, model: InstallmentModel) -> InstallmentModel:
        """Update installment document."""

    @abstractmethod
    def soft_delete(self, model_id: str) -> None:
        """Soft delete installment document."""

    @abstractmethod
    def get_due_installments(self, before: datetime) -> List[InstallmentModel]:
        """Fetch due installments up to a timestamp."""

    @abstractmethod
    def get_by_loan_id(self, loan_id: str) -> List[InstallmentModel]:
        """Fetch installments belonging to one loan."""


class LiquidationLogRepository(BaseRepository):
    """Liquidation log data access abstraction."""

    @abstractmethod
    def create(self, model: LiquidationLogModel) -> LiquidationLogModel:
        """Persist liquidation log."""

    @abstractmethod
    def get_by_id(self, model_id: str) -> LiquidationLogModel:
        """Fetch liquidation log by identifier."""

    @abstractmethod
    def update(self, model: LiquidationLogModel) -> LiquidationLogModel:
        """Update liquidation log document."""

    @abstractmethod
    def soft_delete(self, model_id: str) -> None:
        """Soft delete liquidation log."""

    @abstractmethod
    def get_by_loan_id(self, loan_id: str) -> List[LiquidationLogModel]:
        """Fetch liquidation logs for a loan."""


__all__ = [
    "ValidationError",
    "ModelNotFoundError",
    "VersionConflictError",
    "UserRepository",
    "LoanRepository",
    "CollateralRepository",
    "RiskScoreRepository",
    "InstallmentRepository",
    "LiquidationLogRepository",
]
