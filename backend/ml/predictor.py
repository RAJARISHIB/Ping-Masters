"""Compatibility predictor for the legacy risk route.

This module provides ``LiquidationPredictor`` with the interface expected by
``backend/api/risk_routes.py``. It adapts the existing risk-tier model artifact
to the liquidation-risk response shape used by ``/api/risk/predict``.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import math
import os
from pathlib import Path
from typing import Dict

from .inference import RiskModelInferenceService
from .schema import RiskFeatureInput


logger = logging.getLogger(__name__)


DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "artifacts" / "risk_model.joblib"
_TIER_BASE_PROBABILITY = {
    "LOW": 0.08,
    "MEDIUM": 0.35,
    "HIGH": 0.75,
    "CRITICAL": 0.92,
}


@dataclass(frozen=True)
class LiquidationPredictionResult:
    """Prediction output for ``/api/risk/predict`` responses."""

    liquidation_probability: float
    risk_tier: str
    model_version: str


class LiquidationPredictor:
    """Predict liquidation risk using the existing risk-tier model artifact."""

    def __init__(self, model_path: str = "") -> None:
        resolved_model_path = (
            model_path
            or os.getenv("PING_MASTERS_RISK_MODEL_PATH", "").strip()
            or str(DEFAULT_MODEL_PATH)
        )
        self._inference = RiskModelInferenceService(model_path=resolved_model_path)
        if not self._inference.is_loaded:
            raise FileNotFoundError("Risk model artifact not found or failed to load.")
        self._model_version = "liquidation-adapter:{0}".format(
            Path(self._inference.model_path).name
        )
        logger.info("LiquidationPredictor initialized model_path=%s", self._inference.model_path)

    def predict(
        self,
        collateral_bnb: float,
        debt_fiat: float,
        current_price: float,
        volatility: float,
    ) -> LiquidationPredictionResult:
        """Predict liquidation probability from raw risk-route observables."""
        features = self._build_features(
            collateral_bnb=collateral_bnb,
            debt_fiat=debt_fiat,
            current_price=current_price,
            volatility=volatility,
        )
        inference_output = self._inference.predict(features)

        risk_tier = str(inference_output.get("risk_tier", "MEDIUM")).upper()
        probabilities = inference_output.get("probabilities", {})
        liquidation_probability = self._to_liquidation_probability(
            risk_tier=risk_tier,
            probabilities=probabilities if isinstance(probabilities, dict) else {},
        )

        return LiquidationPredictionResult(
            liquidation_probability=liquidation_probability,
            risk_tier=risk_tier,
            model_version=self._model_version,
        )

    @staticmethod
    def _build_features(
        collateral_bnb: float,
        debt_fiat: float,
        current_price: float,
        volatility: float,
    ) -> RiskFeatureInput:
        """Build model features from risk-route payload."""
        safe_collateral_bnb = max(float(collateral_bnb), 0.0)
        safe_debt_fiat = max(float(debt_fiat), 0.0)
        safe_current_price = max(float(current_price), 0.000001)
        safe_volatility = max(float(volatility), 0.0)

        collateral_value = safe_collateral_bnb * safe_current_price
        if safe_debt_fiat <= 0.0:
            safety_ratio = 10.0
        else:
            safety_ratio = collateral_value / safe_debt_fiat
        safety_ratio = max(0.01, min(safety_ratio, 25.0))

        # Keep the adapter deterministic and explainable for hackathon demos.
        risk_pressure = max(0.0, (1.3 - min(safety_ratio, 1.3))) + max(0.0, safe_volatility - 0.5)
        missed_payment_count = int(max(0, min(3, round(risk_pressure * 2.2))))
        on_time_ratio = max(0.05, min(0.99, 0.97 - (missed_payment_count * 0.14) - (safe_volatility * 0.04)))
        avg_delay_hours = max(0.0, min(96.0, (safe_volatility * 8.0) + (max(0.0, 1.2 - safety_ratio) * 22.0)))
        topup_count_last_30d = int(max(0, min(4, round(max(0.0, (1.2 - safety_ratio) * 3.0)))))
        plan_amount = max(safe_debt_fiat, 100.0)
        tenure_days = 120
        installment_amount = max(plan_amount / 4.0, 1.0)

        return RiskFeatureInput(
            safety_ratio=float(safety_ratio),
            missed_payment_count=missed_payment_count,
            on_time_ratio=float(on_time_ratio),
            avg_delay_hours=float(avg_delay_hours),
            topup_count_last_30d=topup_count_last_30d,
            plan_amount=float(plan_amount),
            tenure_days=tenure_days,
            installment_amount=float(installment_amount),
        )

    @staticmethod
    def _to_liquidation_probability(risk_tier: str, probabilities: Dict[str, float]) -> float:
        """Convert class probabilities from risk-tier model into liquidation probability."""
        if probabilities:
            weighted = 0.0
            total_weight = 0.0
            for tier, prob in probabilities.items():
                tier_key = str(tier).upper()
                tier_base = _TIER_BASE_PROBABILITY.get(tier_key, 0.5)
                prob_value = max(0.0, min(float(prob), 1.0))
                weighted += tier_base * prob_value
                total_weight += prob_value
            if total_weight > 0.0:
                value = weighted / total_weight
                return round(max(0.0, min(value, 1.0)), 6)

        fallback = _TIER_BASE_PROBABILITY.get(risk_tier.upper(), 0.5)
        if math.isnan(fallback):
            fallback = 0.5
        return round(max(0.0, min(float(fallback), 1.0)), 6)


def classify_risk_tier(liquidation_probability: float) -> str:
    """Classify tier for compatibility with older callers."""
    if liquidation_probability < 0.10:
        return "LOW"
    if liquidation_probability < 0.30:
        return "MEDIUM"
    if liquidation_probability < 0.60:
        return "HIGH"
    return "CRITICAL"

