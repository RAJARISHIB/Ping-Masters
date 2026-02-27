"""Risk scoring model for explainable borrower risk intelligence."""

from datetime import datetime
import logging
from typing import Any, Dict, List, Optional

from pydantic import Field

from .base import BaseDocumentModel, Money, PercentageBps
from .enums import RiskTier


logger = logging.getLogger(__name__)


class RiskScoreModel(BaseDocumentModel):
    """Represents a risk score snapshot for user or loan-level decisions."""

    risk_score_id: str = Field(..., min_length=3)
    user_id: str = Field(..., min_length=3)
    loan_id: Optional[str] = Field(default=None)

    score: int = Field(..., ge=0, le=1000)
    tier: RiskTier = Field(...)
    default_probability_bps: PercentageBps = Field(..., ge=0, le=10000)

    top_factors: List[str] = Field(default_factory=list)
    recommendation_minor: Money = Field(default=0, ge=0)

    model_name: str = Field(default="rule_based_risk")
    model_version: str = Field(default="v1")
    feature_snapshot: Dict[str, Any] = Field(default_factory=dict)

    next_review_at: Optional[datetime] = Field(default=None)
    last_evaluated_at: Optional[datetime] = Field(default=None)
