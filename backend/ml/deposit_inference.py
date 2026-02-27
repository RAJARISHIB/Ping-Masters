"""Inference service for deposit recommendation model."""

import logging
from pathlib import Path
from typing import Any, Dict

import joblib
import pandas as pd

from .deposit_policy import recommend_deposit_by_policy
from .deposit_schema import DepositRecommendationRequest


logger = logging.getLogger(__name__)


class DepositRecommendationInferenceService:
    """Load and run ML inference for dynamic deposit recommendation."""

    def __init__(self, model_path: str) -> None:
        self._model_path = Path(model_path)
        self._artifact: Dict[str, Any] = {}
        self._loaded = False
        self._load_model()

    @property
    def model_path(self) -> str:
        """Return current model artifact path as string."""
        return str(self._model_path)

    @property
    def is_loaded(self) -> bool:
        """Whether model artifact is loaded."""
        return self._loaded

    def reload(self, model_path: str = "") -> None:
        """Reload model artifact, optionally from a new path."""
        try:
            if model_path:
                self._model_path = Path(model_path)
            self._load_model()
        except Exception:
            logger.exception("Failed reloading deposit model path=%s", model_path or self._model_path)
            raise

    def _load_model(self) -> None:
        """Load model artifact from filesystem."""
        try:
            if not self._model_path.exists():
                logger.warning("Deposit model file not found path=%s", self._model_path)
                self._loaded = False
                return
            self._artifact = joblib.load(self._model_path)
            self._loaded = True
            logger.info("Deposit model loaded path=%s", self._model_path)
        except Exception:
            logger.exception("Failed to load deposit model path=%s", self._model_path)
            self._loaded = False

    def predict(self, payload: DepositRecommendationRequest) -> Dict[str, Any]:
        """Predict required collateral using model or policy fallback."""
        if not self._loaded:
            policy_result = recommend_deposit_by_policy(payload)
            policy_result["mode"] = "policy_fallback"
            return policy_result

        try:
            feature_columns = self._artifact["feature_columns"]
            model = self._artifact["pipeline"]
            data = payload.dict()
            if data.get("outstanding_debt_inr") in (None, 0):
                data["outstanding_debt_inr"] = payload.plan_amount_inr
            if data.get("stress_drop_pct") is None:
                data["stress_drop_pct"] = 0.02 if payload.collateral_type == "stable" else 0.20
            if data.get("fees_buffer_pct") is None:
                data["fees_buffer_pct"] = 0.03

            x = pd.DataFrame([data], columns=feature_columns)
            predicted_required_inr = float(model.predict(x)[0])
            required_token = predicted_required_inr / payload.price_inr
            topup_token = max(0.0, required_token - payload.locked_token)

            return {
                "mode": "ml",
                "risk_tier": payload.risk_tier,
                "required_inr": round(predicted_required_inr, 6),
                "required_token": round(required_token, 12),
                "current_locked_token": round(payload.locked_token, 12),
                "current_locked_inr": round(payload.locked_token * payload.price_inr, 6),
                "topup_token": round(topup_token, 12),
                "model_name": self._artifact.get("model_name", "random_forest_regressor"),
                "model_version": self._artifact.get("version", "v1"),
                "metric_mae": self._artifact.get("metric_mae"),
            }
        except Exception:
            logger.exception("Deposit recommendation ML prediction failed.")
            raise
