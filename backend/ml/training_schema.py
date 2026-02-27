"""Schema definitions for ML data generation, training, and runtime updates."""

from typing import Optional

from pydantic import BaseModel, Field, validator


SUPPORTED_MODEL_TYPES = {"risk", "default", "deposit"}


class MlGenerateDatasetRequest(BaseModel):
    """Request payload for synthetic dataset generation."""

    model_type: str = Field(..., min_length=4)
    rows: int = Field(default=10000, gt=100, le=500000)
    seed: int = Field(default=42, ge=0)
    output_path: Optional[str] = Field(default=None, min_length=5)

    @validator("model_type")
    def _validate_model_type(cls, value: str) -> str:
        """Validate target model type."""
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_MODEL_TYPES:
            raise ValueError("model_type must be one of: risk, default, deposit")
        return normalized


class MlTrainModelRequest(BaseModel):
    """Request payload for model training operations."""

    model_type: str = Field(..., min_length=4)
    data_path: Optional[str] = Field(default=None, min_length=5)
    rows: int = Field(default=10000, gt=100, le=500000)
    seed: int = Field(default=42, ge=0)
    output_path: Optional[str] = Field(default=None, min_length=5)
    auto_generate_if_missing: bool = Field(default=True)
    reload_after_train: bool = Field(default=True)
    high_threshold: Optional[float] = Field(default=None, gt=0.0, lt=1.0)
    medium_threshold: Optional[float] = Field(default=None, gt=0.0, lt=1.0)

    @validator("model_type")
    def _validate_model_type(cls, value: str) -> str:
        """Validate target model type."""
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_MODEL_TYPES:
            raise ValueError("model_type must be one of: risk, default, deposit")
        return normalized

    @validator("medium_threshold")
    def _validate_threshold_pair(cls, medium_threshold: Optional[float], values: dict) -> Optional[float]:
        """Ensure medium threshold is lower than high threshold when both are provided."""
        high_threshold = values.get("high_threshold")
        if medium_threshold is not None and high_threshold is not None and medium_threshold >= high_threshold:
            raise ValueError("medium_threshold must be less than high_threshold")
        return medium_threshold


class MlUpdateDefaultThresholdRequest(BaseModel):
    """Request payload for runtime default-threshold updates."""

    high_threshold: float = Field(..., gt=0.0, lt=1.0)
    medium_threshold: float = Field(..., gt=0.0, lt=1.0)

    @validator("medium_threshold")
    def _validate_pair(cls, medium_threshold: float, values: dict) -> float:
        """Validate ordering against high threshold."""
        high_threshold = values.get("high_threshold")
        if high_threshold is not None and medium_threshold >= high_threshold:
            raise ValueError("medium_threshold must be less than high_threshold")
        return medium_threshold


class MlReloadModelsRequest(BaseModel):
    """Request payload for model artifact reload operations."""

    reload_risk: bool = Field(default=True)
    reload_default: bool = Field(default=True)
    reload_deposit: bool = Field(default=True)
    risk_model_path: Optional[str] = Field(default=None, min_length=5)
    default_model_path: Optional[str] = Field(default=None, min_length=5)
    deposit_model_path: Optional[str] = Field(default=None, min_length=5)
