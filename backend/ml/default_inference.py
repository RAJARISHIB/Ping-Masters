"""Inference service for next-installment default prediction."""

import logging
from pathlib import Path
from typing import Any, Dict, List

import joblib
import pandas as pd

from .default_schema import DefaultPredictionInput


logger = logging.getLogger(__name__)


class DefaultPredictionInferenceService:
    """Serve calibrated default probability inference."""

    def __init__(
        self,
        model_path: str,
        high_threshold: float = 0.60,
        medium_threshold: float = 0.30,
    ) -> None:
        self._model_path = Path(model_path)
        self._artifact: Dict[str, Any] = {}
        self._loaded = False
        self._high_threshold = high_threshold
        self._medium_threshold = medium_threshold
        self._load_model()

    @property
    def model_path(self) -> str:
        """Return current model artifact path."""
        return str(self._model_path)

    @property
    def is_loaded(self) -> bool:
        """Whether model artifact is loaded."""
        return self._loaded

    @property
    def thresholds(self) -> Dict[str, float]:
        """Expose current HIGH and MEDIUM tier thresholds."""
        return {
            "high": float(self._high_threshold),
            "medium": float(self._medium_threshold),
        }

    def reload(self, model_path: str = "") -> None:
        """Reload model artifact, optionally from a different path."""
        try:
            if model_path:
                self._model_path = Path(model_path)
            self._load_model()
        except Exception:
            logger.exception("Failed reloading default model path=%s", model_path or self._model_path)
            raise

    def update_thresholds(self, high_threshold: float, medium_threshold: float) -> Dict[str, float]:
        """Update runtime thresholds used for tier mapping.

        Args:
            high_threshold: Probability threshold for HIGH tier.
            medium_threshold: Probability threshold for MEDIUM tier.

        Returns:
            Dict[str, float]: Updated threshold map.

        Raises:
            ValueError: If thresholds are out of bounds or inconsistent.
        """
        try:
            high = float(high_threshold)
            medium = float(medium_threshold)
            if high <= 0 or high >= 1:
                raise ValueError("high_threshold must be between 0 and 1.")
            if medium <= 0 or medium >= 1:
                raise ValueError("medium_threshold must be between 0 and 1.")
            if medium >= high:
                raise ValueError("medium_threshold must be less than high_threshold.")
            self._high_threshold = high
            self._medium_threshold = medium
            logger.info(
                "Default model thresholds updated high=%.4f medium=%.4f",
                self._high_threshold,
                self._medium_threshold,
            )
            return self.thresholds
        except Exception:
            logger.exception(
                "Failed updating default model thresholds high=%s medium=%s",
                high_threshold,
                medium_threshold,
            )
            raise

    def _load_model(self) -> None:
        """Load model artifact from disk."""
        try:
            if not self._model_path.exists():
                logger.warning("Default model file not found path=%s", self._model_path)
                self._loaded = False
                return
            self._artifact = joblib.load(self._model_path)
            self._high_threshold = float(self._artifact.get("high_threshold", self._high_threshold))
            self._medium_threshold = float(self._artifact.get("medium_threshold", self._medium_threshold))
            self._loaded = True
            logger.info("Default model loaded path=%s", self._model_path)
        except Exception:
            logger.exception("Failed loading default model path=%s", self._model_path)
            self._loaded = False

    def predict(self, payload: DefaultPredictionInput) -> Dict[str, Any]:
        """Predict probability of missing next installment and map to tier/actions."""
        if not self._loaded:
            raise RuntimeError("Default prediction model not loaded.")

        try:
            feature_columns: List[str] = self._artifact["feature_columns"]
            model = self._artifact["model"]
            payload_dict = payload.dict()
            x = pd.DataFrame([payload_dict], columns=feature_columns)
            p_miss_next = float(model.predict_proba(x)[0][1])

            if p_miss_next >= self._high_threshold:
                tier = "HIGH"
                actions = [
                    "send_early_reminders",
                    "suggest_topup_collateral",
                    "offer_smaller_plan_next_time",
                ]
            elif p_miss_next >= self._medium_threshold:
                tier = "MEDIUM"
                actions = ["send_dual_reminders", "prompt_autopay_enable"]
            else:
                tier = "LOW"
                actions = ["normal_day_of_reminder"]

            return {
                "user_id": payload.user_id,
                "plan_id": payload.plan_id,
                "installment_id": payload.installment_id,
                "p_miss_next": round(p_miss_next, 6),
                "tier": tier,
                "thresholds": {
                    "high": self._high_threshold,
                    "medium": self._medium_threshold,
                },
                "actions": actions,
                "top_reasons": self._top_reasons(payload),
                "model_name": self._artifact.get("model_name", "gradient_boosting_calibrated"),
                "model_version": self._artifact.get("version", "v1"),
            }
        except Exception:
            logger.exception("Default prediction inference failed.")
            raise

    def _top_reasons(self, payload: DefaultPredictionInput) -> List[str]:
        """Generate simple explainability reasons for risk operations."""
        reasons: List[str] = []
        if payload.current_safety_ratio < 1.1:
            reasons.append("Low safety ratio near liquidation threshold")
        if payload.missed_count_90d > 0:
            reasons.append("Recent missed payments in last 90 days")
        if payload.avg_days_late > 3:
            reasons.append("High average payment delay")
        if payload.payment_attempt_failed_count > 0:
            reasons.append("Recent payment attempt failures")
        if payload.days_until_due <= 1:
            reasons.append("Installment due very soon")
        if not reasons:
            reasons.append("Strong repayment and collateral behavior")
        return reasons[:3]
