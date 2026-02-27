"""Unit tests for the v2 predictor module."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from ml.inference.predictor import (
    MODEL_PATH,
    LiquidationPredictor,
    PredictionResult,
    classify_risk_tier,
)


class TestRiskTierClassification(unittest.TestCase):
    """Verify risk-tier boundary logic."""

    def test_low(self) -> None:
        self.assertEqual(classify_risk_tier(0.00), "LOW")
        self.assertEqual(classify_risk_tier(0.04), "LOW")

    def test_medium(self) -> None:
        self.assertEqual(classify_risk_tier(0.05), "MEDIUM")
        self.assertEqual(classify_risk_tier(0.19), "MEDIUM")

    def test_high(self) -> None:
        self.assertEqual(classify_risk_tier(0.20), "HIGH")
        self.assertEqual(classify_risk_tier(0.49), "HIGH")

    def test_critical(self) -> None:
        self.assertEqual(classify_risk_tier(0.50), "CRITICAL")
        self.assertEqual(classify_risk_tier(1.00), "CRITICAL")


@unittest.skipUnless(MODEL_PATH.exists(), "Trained model not found — skipping inference test.")
class TestPredictorInferenceV2(unittest.TestCase):
    """Verify the v2 predictor returns valid output."""

    def setUp(self) -> None:
        self.predictor = LiquidationPredictor()

    def test_probability_in_range(self) -> None:
        result = self.predictor.predict(1.0, 200.0, 300.0, 0.80)
        self.assertIsInstance(result, PredictionResult)
        self.assertGreaterEqual(result.liquidation_probability, 0.0)
        self.assertLessEqual(result.liquidation_probability, 1.0)

    def test_risk_tier_is_valid(self) -> None:
        result = self.predictor.predict(1.0, 200.0, 300.0, 0.80)
        self.assertIn(result.risk_tier, {"LOW", "MEDIUM", "HIGH", "CRITICAL"})

    def test_model_version_is_v2(self) -> None:
        result = self.predictor.predict(1.0, 200.0, 300.0, 0.80)
        self.assertEqual(result.model_version, "v2.0")

    def test_feature_values_are_raw_observables(self) -> None:
        """Feature dict should contain exactly the 4 leakage-free features."""
        from ml.features.feature_extractor import FEATURE_NAMES

        result = self.predictor.predict(1.0, 200.0, 300.0, 0.80)
        self.assertEqual(set(result.feature_values.keys()), set(FEATURE_NAMES))
        self.assertEqual(len(result.feature_values), 4)

    def test_volatility_sensitivity_direction(self) -> None:
        """Higher volatility should generally produce higher risk."""
        r_low = self.predictor.predict(1.0, 200.0, 300.0, volatility=0.20)
        r_high = self.predictor.predict(1.0, 200.0, 300.0, volatility=1.00)
        # We only check the direction, not strict monotonicity
        self.assertLessEqual(
            r_low.liquidation_probability,
            r_high.liquidation_probability + 0.05,  # small tolerance
            "Risk should generally increase with volatility",
        )


if __name__ == "__main__":
    unittest.main()
