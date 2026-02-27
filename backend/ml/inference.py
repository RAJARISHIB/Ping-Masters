"""Inference service for risk tier predictions."""

import logging
from pathlib import Path
from typing import Any, Dict, List

import joblib
import numpy as np
import pandas as pd

from .schema import RiskFeatureInput


logger = logging.getLogger(__name__)


class RiskModelInferenceService:
    """Loads trained artifact and serves model inference requests."""

    def __init__(self, model_path: str) -> None:
        self._model_path = Path(model_path)
        self._artifact: Dict[str, Any] = {}
        self._loaded = False
        self._load_model()

    @property
    def model_path(self) -> str:
        """Return the current model artifact path as string."""
        return str(self._model_path)

    @property
    def is_loaded(self) -> bool:
        """Return whether model artifact is available and loaded."""
        return self._loaded

    def reload(self, model_path: str = "") -> None:
        """Reload model artifact, optionally from a new path.

        Args:
            model_path: Optional new model path.
        """
        try:
            if model_path:
                self._model_path = Path(model_path)
            self._load_model()
        except Exception:
            logger.exception("Failed to reload ML model path=%s", model_path or self._model_path)
            raise

    def _load_model(self) -> None:
        """Load model artifact from disk."""
        try:
            if not self._model_path.exists():
                logger.warning("ML model file not found path=%s", self._model_path)
                self._loaded = False
                return
            self._artifact = joblib.load(self._model_path)
            self._loaded = True
            logger.info("ML model loaded path=%s", self._model_path)
        except Exception:
            logger.exception("Failed to load ML model path=%s", self._model_path)
            self._loaded = False

    def predict(self, features: RiskFeatureInput) -> Dict[str, Any]:
        """Predict risk tier, probabilities, and top reasons."""
        if not self._loaded:
            raise RuntimeError("ML model not loaded. Train model first.")

        try:
            feature_columns: List[str] = self._artifact["feature_columns"]
            pipeline = self._artifact["pipeline"]

            payload = features.dict()
            x = pd.DataFrame([payload], columns=feature_columns)
            prediction = pipeline.predict(x)[0]
            probabilities_arr = pipeline.predict_proba(x)[0]
            classes = list(pipeline.classes_)
            probabilities = {classes[idx]: float(probabilities_arr[idx]) for idx in range(len(classes))}

            top_reasons = self._extract_top_reasons(pipeline=pipeline, x=x, feature_columns=feature_columns, tier=prediction)
            return {
                "risk_tier": prediction,
                "probabilities": probabilities,
                "top_reasons": top_reasons,
                "model_name": self._artifact.get("model_name", "logistic_regression_ovr"),
                "model_version": self._artifact.get("version", "v1"),
            }
        except Exception:
            logger.exception("ML prediction failed.")
            raise

    def _extract_top_reasons(self, pipeline: Any, x: pd.DataFrame, feature_columns: List[str], tier: str) -> List[Dict[str, Any]]:
        """Compute top 3 feature contributions for explainability."""
        try:
            scaler = pipeline.named_steps["scaler"]
            model = pipeline.named_steps["model"]
            x_scaled = scaler.transform(x)[0]
            class_index = list(model.classes_).index(tier)
            coef = model.coef_[class_index]
            contributions = coef * x_scaled

            ranked_idx = np.argsort(np.abs(contributions))[::-1][:3]
            result: List[Dict[str, Any]] = []
            for idx in ranked_idx:
                result.append(
                    {
                        "feature": feature_columns[idx],
                        "contribution": float(contributions[idx]),
                        "direction": "increase_risk" if contributions[idx] > 0 else "decrease_risk",
                    }
                )
            return result
        except Exception:
            logger.exception("Failed extracting top reasons.")
            return []
