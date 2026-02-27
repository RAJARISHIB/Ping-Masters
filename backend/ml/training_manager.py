"""Management utilities for ML dataset generation, training, and runtime reload."""

import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pandas as pd

from .default_inference import DefaultPredictionInferenceService
from .default_synthetic import generate_synthetic_default_dataset
from .default_trainer import FEATURE_COLUMNS as DEFAULT_FEATURE_COLUMNS
from .default_trainer import train_and_save_default_model
from .deposit_inference import DepositRecommendationInferenceService
from .deposit_synthetic import generate_synthetic_deposit_dataset
from .deposit_trainer import FEATURE_COLUMNS as DEPOSIT_FEATURE_COLUMNS
from .deposit_trainer import train_and_save_deposit_model
from .inference import RiskModelInferenceService
from .synthetic import generate_synthetic_risk_dataset
from .trainer import FEATURE_COLUMNS as RISK_FEATURE_COLUMNS
from .trainer import train_and_save_model
from .training_schema import (
    MlGenerateDatasetRequest,
    MlReloadModelsRequest,
    MlTrainModelRequest,
    MlUpdateDefaultThresholdRequest,
)


logger = logging.getLogger(__name__)


class MlModelManagementService:
    """Service for managing ML data and model lifecycle operations."""

    def __init__(
        self,
        enabled: bool,
        risk_model_path: str,
        default_model_path: str,
        deposit_model_path: str,
        default_high_threshold: float,
        default_medium_threshold: float,
        risk_inference: Optional[RiskModelInferenceService],
        default_inference: Optional[DefaultPredictionInferenceService],
        deposit_inference: Optional[DepositRecommendationInferenceService],
    ) -> None:
        self._enabled = bool(enabled)
        self._risk_model_path = str(risk_model_path)
        self._default_model_path = str(default_model_path)
        self._deposit_model_path = str(deposit_model_path)
        self._default_high_threshold = float(default_high_threshold)
        self._default_medium_threshold = float(default_medium_threshold)
        self._risk_inference = risk_inference
        self._default_inference = default_inference
        self._deposit_inference = deposit_inference
        self._dataset_paths = {
            "risk": "backend/ml/artifacts/risk_training_data.csv",
            "default": "backend/ml/artifacts/default_training_data.csv",
            "deposit": "backend/ml/artifacts/deposit_training_data.csv",
        }

    def get_training_specs(self) -> Dict[str, Any]:
        """Return model feature/label requirements and runtime configuration."""
        try:
            return {
                "enabled": self._enabled,
                "datasets": dict(self._dataset_paths),
                "models": {
                    "risk": {
                        "artifact_path": self._risk_model_path,
                        "feature_columns": list(RISK_FEATURE_COLUMNS),
                        "label_column": "risk_tier",
                    },
                    "default": {
                        "artifact_path": self._default_model_path,
                        "feature_columns": list(DEFAULT_FEATURE_COLUMNS),
                        "label_column": "y_miss_next",
                        "extra_required_columns": ["due_at"],
                        "thresholds": {
                            "high": self._default_high_threshold,
                            "medium": self._default_medium_threshold,
                        },
                    },
                    "deposit": {
                        "artifact_path": self._deposit_model_path,
                        "feature_columns": list(DEPOSIT_FEATURE_COLUMNS),
                        "label_column": "required_collateral_inr",
                    },
                },
            }
        except Exception:
            logger.exception("Failed building ML training specs.")
            raise

    def get_runtime_status(self) -> Dict[str, Any]:
        """Return model runtime health and loaded states."""
        try:
            return {
                "enabled": self._enabled,
                "risk_model": {
                    "path": self._risk_model_path,
                    "loaded": bool(self._risk_inference and self._risk_inference.is_loaded),
                },
                "default_model": {
                    "path": self._default_model_path,
                    "loaded": bool(self._default_inference and self._default_inference.is_loaded),
                    "thresholds": self._default_inference.thresholds
                    if self._default_inference is not None
                    else {"high": self._default_high_threshold, "medium": self._default_medium_threshold},
                },
                "deposit_model": {
                    "path": self._deposit_model_path,
                    "loaded": bool(self._deposit_inference and self._deposit_inference.is_loaded),
                },
            }
        except Exception:
            logger.exception("Failed collecting ML runtime status.")
            raise

    def generate_dataset(self, request: MlGenerateDatasetRequest) -> Dict[str, Any]:
        """Generate synthetic dataset for a target model type and persist CSV."""
        try:
            dataset_path = Path(request.output_path or self._dataset_paths[request.model_type])
            dataset_path.parent.mkdir(parents=True, exist_ok=True)

            generator: Callable[[int, int], pd.DataFrame]
            if request.model_type == "risk":
                generator = generate_synthetic_risk_dataset
            elif request.model_type == "default":
                generator = generate_synthetic_default_dataset
            else:
                generator = generate_synthetic_deposit_dataset

            dataframe = generator(rows=request.rows, seed=request.seed)
            dataframe.to_csv(dataset_path, index=False)
            logger.info(
                "Generated dataset model_type=%s rows=%d output_path=%s",
                request.model_type,
                len(dataframe),
                dataset_path,
            )
            return {
                "model_type": request.model_type,
                "rows": int(len(dataframe)),
                "output_path": str(dataset_path),
            }
        except Exception:
            logger.exception("Dataset generation failed request=%s", request.dict())
            raise

    def train_model(self, request: MlTrainModelRequest) -> Dict[str, Any]:
        """Train selected model from dataset file or synthetic generation."""
        try:
            dataframe = self._load_training_dataframe(request)
            output_path = request.output_path or self._get_default_model_output_path(request.model_type)

            if request.model_type == "risk":
                summary = train_and_save_model(dataframe=dataframe, output_path=output_path)
                if request.reload_after_train:
                    self.reload_models(
                        MlReloadModelsRequest(
                            reload_risk=True,
                            reload_default=False,
                            reload_deposit=False,
                            risk_model_path=output_path,
                        )
                    )
            elif request.model_type == "default":
                high_threshold = (
                    request.high_threshold if request.high_threshold is not None else self._default_high_threshold
                )
                medium_threshold = (
                    request.medium_threshold
                    if request.medium_threshold is not None
                    else self._default_medium_threshold
                )
                summary = train_and_save_default_model(
                    dataframe=dataframe,
                    output_path=output_path,
                    high_threshold=high_threshold,
                    medium_threshold=medium_threshold,
                )
                self._default_high_threshold = float(high_threshold)
                self._default_medium_threshold = float(medium_threshold)
                if request.reload_after_train:
                    self.reload_models(
                        MlReloadModelsRequest(
                            reload_risk=False,
                            reload_default=True,
                            reload_deposit=False,
                            default_model_path=output_path,
                        )
                    )
            else:
                summary = train_and_save_deposit_model(dataframe=dataframe, output_path=output_path)
                if request.reload_after_train:
                    self.reload_models(
                        MlReloadModelsRequest(
                            reload_risk=False,
                            reload_default=False,
                            reload_deposit=True,
                            deposit_model_path=output_path,
                        )
                    )

            logger.info("Model training completed model_type=%s output_path=%s", request.model_type, output_path)
            return {
                "model_type": request.model_type,
                "summary": summary,
                "runtime": self.get_runtime_status(),
            }
        except Exception:
            logger.exception("Model training failed request=%s", request.dict())
            raise

    def reload_models(self, request: MlReloadModelsRequest) -> Dict[str, Any]:
        """Reload model artifacts into runtime inference services."""
        try:
            results: Dict[str, Any] = {}

            if request.reload_risk:
                self._risk_model_path = request.risk_model_path or self._risk_model_path
                if self._risk_inference is None:
                    results["risk"] = {"reloaded": False, "reason": "risk inference service unavailable"}
                else:
                    self._risk_inference.reload(self._risk_model_path)
                    results["risk"] = {
                        "reloaded": bool(self._risk_inference.is_loaded),
                        "path": self._risk_model_path,
                    }

            if request.reload_default:
                self._default_model_path = request.default_model_path or self._default_model_path
                if self._default_inference is None:
                    results["default"] = {"reloaded": False, "reason": "default inference service unavailable"}
                else:
                    self._default_inference.reload(self._default_model_path)
                    results["default"] = {
                        "reloaded": bool(self._default_inference.is_loaded),
                        "path": self._default_model_path,
                        "thresholds": self._default_inference.thresholds,
                    }

            if request.reload_deposit:
                self._deposit_model_path = request.deposit_model_path or self._deposit_model_path
                if self._deposit_inference is None:
                    results["deposit"] = {"reloaded": False, "reason": "deposit inference service unavailable"}
                else:
                    self._deposit_inference.reload(self._deposit_model_path)
                    results["deposit"] = {
                        "reloaded": bool(self._deposit_inference.is_loaded),
                        "path": self._deposit_model_path,
                    }

            logger.info("Reload models result=%s", results)
            return {"results": results, "runtime": self.get_runtime_status()}
        except Exception:
            logger.exception("Model reload failed request=%s", request.dict())
            raise

    def update_default_thresholds(self, request: MlUpdateDefaultThresholdRequest) -> Dict[str, Any]:
        """Update runtime thresholds for default prediction tiers."""
        try:
            self._default_high_threshold = float(request.high_threshold)
            self._default_medium_threshold = float(request.medium_threshold)
            if self._default_inference is None:
                logger.warning("Default inference unavailable; thresholds stored only in management service.")
                return {
                    "thresholds": {
                        "high": self._default_high_threshold,
                        "medium": self._default_medium_threshold,
                    },
                    "applied_to_runtime": False,
                }

            updated = self._default_inference.update_thresholds(
                high_threshold=self._default_high_threshold,
                medium_threshold=self._default_medium_threshold,
            )
            return {"thresholds": updated, "applied_to_runtime": True}
        except Exception:
            logger.exception(
                "Failed to update thresholds high=%s medium=%s",
                request.high_threshold,
                request.medium_threshold,
            )
            raise

    def _load_training_dataframe(self, request: MlTrainModelRequest) -> pd.DataFrame:
        """Load or generate training dataframe based on request settings."""
        try:
            if request.data_path:
                data_path = Path(request.data_path)
                if data_path.exists():
                    logger.info("Loading training data from file path=%s", data_path)
                    dataframe = pd.read_csv(data_path)
                    return self._normalize_training_dataframe(
                        dataframe=dataframe,
                        model_type=request.model_type,
                    )
                if not request.auto_generate_if_missing:
                    raise FileNotFoundError("Dataset file not found: {0}".format(data_path))
                logger.warning(
                    "Data file not found path=%s. Auto generation enabled; generating synthetic dataset.",
                    data_path,
                )

            generator = self.generate_dataset(
                MlGenerateDatasetRequest(
                    model_type=request.model_type,
                    rows=request.rows,
                    seed=request.seed,
                    output_path=self._dataset_paths[request.model_type],
                )
            )
            generated_path = Path(generator["output_path"])
            dataframe = pd.read_csv(generated_path)
            return self._normalize_training_dataframe(
                dataframe=dataframe,
                model_type=request.model_type,
            )
        except Exception:
            logger.exception("Failed preparing training dataframe request=%s", request.dict())
            raise

    def _get_default_model_output_path(self, model_type: str) -> str:
        """Resolve default artifact output path for model type."""
        if model_type == "risk":
            return self._risk_model_path
        if model_type == "default":
            return self._default_model_path
        return self._deposit_model_path

    def _normalize_training_dataframe(self, dataframe: pd.DataFrame, model_type: str) -> pd.DataFrame:
        """Normalize training dataframe dtypes required by model trainer."""
        try:
            normalized = dataframe.copy()
            if model_type == "default" and "due_at" in normalized.columns:
                normalized["due_at"] = pd.to_datetime(normalized["due_at"], errors="coerce", utc=True)
                normalized = normalized.dropna(subset=["due_at"]).reset_index(drop=True)
            return normalized
        except Exception:
            logger.exception("Failed normalizing training dataframe model_type=%s", model_type)
            raise
