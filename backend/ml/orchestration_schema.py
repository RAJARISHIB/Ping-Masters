"""Schema definitions for ML orchestration endpoints."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


_SUPPORTED_MODEL_TYPES = {"risk", "default", "deposit"}


class MlOrchestrationRequest(BaseModel):
    """Request payload for orchestrated ML inference.

    Attributes:
        risk_payload: Optional raw payload for risk-tier scoring.
        default_payload: Optional raw payload for next-installment default prediction.
        deposit_payload: Optional raw payload for deposit recommendation.
        run_policy_deposit: Whether to execute rule-based deposit recommendation.
        run_ml_deposit: Whether to execute ML-based deposit recommendation.
        include_normalized_payload: Whether response should include normalized feature payloads.
    """

    risk_payload: Optional[Dict[str, Any]] = Field(default=None)
    default_payload: Optional[Dict[str, Any]] = Field(default=None)
    deposit_payload: Optional[Dict[str, Any]] = Field(default=None)
    run_policy_deposit: bool = Field(default=True)
    run_ml_deposit: bool = Field(default=True)
    include_normalized_payload: bool = Field(default=False)


class MlPayloadAnalysisRequest(BaseModel):
    """Request payload for payload-analysis endpoint."""

    model_type: str = Field(..., min_length=4)
    payload: Dict[str, Any] = Field(default_factory=dict)

    @validator("model_type")
    def _validate_model_type(cls, value: str) -> str:
        """Validate analysis target model type."""
        normalized = value.strip().lower()
        if normalized not in _SUPPORTED_MODEL_TYPES:
            raise ValueError("model_type must be one of: risk, default, deposit")
        return normalized


class MlTrainingRowBuildRequest(BaseModel):
    """Request payload for training-row build endpoint."""

    model_type: str = Field(..., min_length=4)
    payload: Dict[str, Any] = Field(default_factory=dict)
    label: Optional[Any] = Field(default=None)

    @validator("model_type")
    def _validate_model_type(cls, value: str) -> str:
        """Validate target model type."""
        normalized = value.strip().lower()
        if normalized not in _SUPPORTED_MODEL_TYPES:
            raise ValueError("model_type must be one of: risk, default, deposit")
        return normalized


class MlEmiPlanEvaluationRequest(BaseModel):
    """Request payload to evaluate ML outputs across all or selected EMI plans."""

    base_payload: Dict[str, Any] = Field(default_factory=dict)
    plan_ids: Optional[List[str]] = Field(default=None)
    run_risk: bool = Field(default=True)
    run_default: bool = Field(default=True)
    run_policy_deposit: bool = Field(default=True)
    run_ml_deposit: bool = Field(default=False)
    include_normalized_payload: bool = Field(default=False)

    @validator("plan_ids", pre=True, always=True)
    def _normalize_plan_ids(cls, value: Optional[List[Any]]) -> Optional[List[str]]:
        """Normalize optional list of plan identifiers."""
        if value is None:
            return None
        normalized = [str(item).strip() for item in value if str(item).strip()]
        return normalized or None
