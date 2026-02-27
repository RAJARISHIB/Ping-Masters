"""Unit tests for protocol constants — verify health factor matches
LendingEngine.sol known values from the Hardhat test suite.
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

# Ensure backend is importable
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from common.protocol_constants import (
    LIQUIDATION_THRESHOLD_PERCENT,
    MAX_LTV_PERCENT,
    PRECISION,
    PRICE_DECIMALS,
    compute_health_factor,
    compute_health_factor_raw,
    compute_liquidation_price,
    compute_max_borrow,
    is_liquidatable,
    raw_to_human_hf,
    raw_to_human_price,
    to_fiat_value,
)


class TestConstants(unittest.TestCase):
    """Verify constant values match LendingEngine.sol."""

    def test_precision(self) -> None:
        self.assertEqual(PRECISION, 10**18)

    def test_price_decimals(self) -> None:
        self.assertEqual(PRICE_DECIMALS, 10**8)

    def test_liquidation_threshold(self) -> None:
        self.assertEqual(LIQUIDATION_THRESHOLD_PERCENT, 80)

    def test_max_ltv(self) -> None:
        self.assertEqual(MAX_LTV_PERCENT, 75)


class TestConversions(unittest.TestCase):
    """Verify decimal conversions."""

    def test_raw_to_human_price_300(self) -> None:
        # $300 in 8-decimal = 30_000_000_000
        self.assertAlmostEqual(raw_to_human_price(30_000_000_000), 300.0)

    def test_raw_to_human_price_inr(self) -> None:
        # Rs25000 in 8-decimal = 2_500_000_000_000
        self.assertAlmostEqual(raw_to_human_price(2_500_000_000_000), 25000.0)

    def test_raw_to_human_hf_1_2(self) -> None:
        # 1.2 in 18-decimal = 1_200_000_000_000_000_000
        self.assertAlmostEqual(raw_to_human_hf(1_200_000_000_000_000_000), 1.2)

    def test_to_fiat_value(self) -> None:
        # 1 BNB (1e18 wei) at $300 (30_000_000_000 in 8-dec) → 300e18
        result = to_fiat_value(10**18, 30_000_000_000)
        self.assertEqual(result, 300 * 10**18)


class TestHealthFactor(unittest.TestCase):
    """Verify HF matches known test values from LendingEngine.test.js."""

    def test_hf_usd_1bnb_200debt(self) -> None:
        """1 BNB @ $300, borrow $200 → HF = 1.2

        From LendingEngine.test.js line 130:
            HF = (300e18 * 80 * 1e18) / (200e18 * 100) = 1.2e18
        """
        collateral_value = 1.0 * 300.0  # $300
        debt = 200.0
        hf = compute_health_factor(collateral_value, debt)
        self.assertAlmostEqual(hf, 1.2, places=10)

    def test_hf_inr_1bnb_10000debt(self) -> None:
        """1 BNB @ Rs25000, borrow Rs10000 → HF = 2.0

        From LendingEngine.test.js line 151:
            HF = (25000e18 * 80 * 1e18) / (10000e18 * 100) = 2.0e18
        """
        collateral_value = 1.0 * 25000.0
        debt = 10000.0
        hf = compute_health_factor(collateral_value, debt)
        self.assertAlmostEqual(hf, 2.0, places=10)

    def test_hf_zero_debt_returns_inf(self) -> None:
        hf = compute_health_factor(300.0, 0.0)
        self.assertTrue(math.isinf(hf))

    def test_hf_negative_debt_returns_inf(self) -> None:
        hf = compute_health_factor(300.0, -1.0)
        self.assertTrue(math.isinf(hf))

    def test_hf_raw_usd_1bnb_200debt(self) -> None:
        """Integer-precision check against contract arithmetic."""
        # colFiat = 300e18, debt = 200e18
        col_fiat_raw = 300 * 10**18
        debt_raw = 200 * 10**18
        raw_hf = compute_health_factor_raw(col_fiat_raw, debt_raw)
        # Expected: 1.2e18 = 1_200_000_000_000_000_000
        self.assertEqual(raw_hf, 1_200_000_000_000_000_000)


class TestLiquidatable(unittest.TestCase):

    def test_healthy(self) -> None:
        self.assertFalse(is_liquidatable(1.2))

    def test_boundary(self) -> None:
        self.assertFalse(is_liquidatable(1.0))

    def test_unhealthy(self) -> None:
        self.assertTrue(is_liquidatable(0.99))


class TestLiquidationPrice(unittest.TestCase):

    def test_liq_price_usd(self) -> None:
        # 1 BNB, $200 debt → liq_price = 200*100 / (1*80) = 250
        liq = compute_liquidation_price(1.0, 200.0)
        self.assertAlmostEqual(liq, 250.0)

    def test_liq_price_zero_collateral(self) -> None:
        liq = compute_liquidation_price(0.0, 200.0)
        self.assertTrue(math.isinf(liq))


class TestMaxBorrow(unittest.TestCase):

    def test_max_borrow(self) -> None:
        # $300 collateral → max borrow = 300 * 75 / 100 = 225
        self.assertAlmostEqual(compute_max_borrow(300.0), 225.0)


if __name__ == "__main__":
    unittest.main()
