"""Unit tests for the v2 feature extractor (leakage-free)."""

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

from ml.features.feature_extractor import FEATURE_NAMES, VaultFeatures, extract_features


class TestFeatureExtractorV2(unittest.TestCase):
    """Verify the leakage-free v2 feature extractor."""

    def test_feature_count_is_four(self) -> None:
        """v2 has exactly 4 features (no leakage)."""
        self.assertEqual(len(FEATURE_NAMES), 4)

    def test_no_deterministic_leakage_features(self) -> None:
        """Verify none of the leakage features are present."""
        leakage_features = {
            "ltv",
            "health_factor",
            "liquidation_price",
            "distance_to_liquidation_price",
            "borrow_utilization",
            "collateral_value_fiat",
        }
        for name in FEATURE_NAMES:
            self.assertNotIn(
                name,
                leakage_features,
                f"Leakage feature '{name}' found in FEATURE_NAMES",
            )

    def test_expected_features_present(self) -> None:
        """Verify the 4 raw observable features."""
        expected = {"collateral_bnb", "debt_fiat", "price_current", "volatility_estimate"}
        self.assertEqual(set(FEATURE_NAMES), expected)

    def test_basic_extraction(self) -> None:
        """Raw values pass through without transformation."""
        f = extract_features(
            collateral_bnb=1.5,
            debt_fiat=200.0,
            current_price=300.0,
            volatility=0.80,
        )
        self.assertIsInstance(f, VaultFeatures)
        self.assertAlmostEqual(f.collateral_bnb, 1.5)
        self.assertAlmostEqual(f.debt_fiat, 200.0)
        self.assertAlmostEqual(f.price_current, 300.0)
        self.assertAlmostEqual(f.volatility_estimate, 0.80)

    def test_to_dict_keys_match_feature_names(self) -> None:
        f = extract_features(1.0, 100.0, 300.0, 0.80)
        self.assertEqual(list(f.to_dict().keys()), FEATURE_NAMES)

    def test_to_list_length(self) -> None:
        f = extract_features(1.0, 100.0, 300.0, 0.80)
        self.assertEqual(len(f.to_list()), len(FEATURE_NAMES))

    def test_zero_values_no_crash(self) -> None:
        """Edge case: zero collateral / debt should not crash."""
        f = extract_features(0.0, 0.0, 300.0, 0.5)
        self.assertEqual(f.collateral_bnb, 0.0)
        self.assertEqual(f.debt_fiat, 0.0)


if __name__ == "__main__":
    unittest.main()
