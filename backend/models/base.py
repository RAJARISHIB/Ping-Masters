"""Shared base models and common type aliases."""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field
try:
    from pydantic import ConfigDict
except ImportError:  # pragma: no cover - pydantic v1 fallback
    ConfigDict = None  # type: ignore

from .exceptions import ModelValidationError


logger = logging.getLogger(__name__)

Money = int
PercentageBps = int


def utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(timezone.utc)


class BaseDocumentModel(BaseModel):
    """Base document schema for Firestore-backed domain models."""

    id: Optional[str] = Field(default=None, description="Firestore document ID.")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    version: int = Field(default=1, ge=1)
    is_deleted: bool = Field(default=False)

    if ConfigDict is not None:
        model_config = ConfigDict(
            str_strip_whitespace=True,
            validate_assignment=True,
            use_enum_values=False,
        )
    else:
        class Config:
            """Pydantic config for pydantic v1 compatibility."""

            anystr_strip_whitespace = True
            validate_assignment = True
            use_enum_values = False

    def to_firestore(self) -> Dict[str, Any]:
        """Serialize model into a Firestore-ready document dictionary.

        Returns:
            Dict[str, Any]: Serialized model payload.

        Raises:
            ModelValidationError: If serialization fails.
        """
        try:
            if hasattr(self, "model_dump"):
                payload = self.model_dump(exclude_none=True)  # pydantic v2
            else:
                payload = self.dict(exclude_none=True)  # pydantic v1
            return payload
        except Exception as exc:
            logger.exception("Failed to serialize %s with id=%s", self.__class__.__name__, self.id)
            raise ModelValidationError(str(exc))

    @classmethod
    def from_firestore(cls, data: Dict[str, Any], doc_id: Optional[str] = None) -> "BaseDocumentModel":
        """Create model instance from Firestore document data.

        Args:
            data: Firestore document payload.
            doc_id: Optional Firestore document id.

        Returns:
            BaseDocumentModel: Typed domain instance.

        Raises:
            ModelValidationError: If payload parsing fails.
        """
        try:
            payload = dict(data)
            if doc_id is not None and "id" not in payload:
                payload["id"] = doc_id
            return cls(**payload)
        except Exception as exc:
            logger.exception("Failed to parse Firestore payload for %s doc_id=%s", cls.__name__, doc_id)
            raise ModelValidationError(str(exc))
