"""Unit tests for the v2 labeler (forward-looking stochastic)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from ml.simulation.labeler import label_vault
from ml.simulation.vault_generator import SyntheticVault


class TestLabelerV2(unittest.TestCase):
    """Verify forward-looking stochastic labeling logic."""

    def _make_vault(
        self,
        collateral: float = 1.0,
        debt: float = 200.0,
        price: float = 300.0,
        vol: float = 0.80,
    ) -> SyntheticVault:
        hf = (collateral * price * 80) / (debt * 100) if debt > 0 else float("inf")
        return SyntheticVault(
            collateral_bnb=collateral,
            debt_fiat=debt,
            current_price=price,
            ltv=debt / (collateral * price) if collateral * price > 0 else 0,
            health_factor=hf,
            volatility=vol,
        )

    def test_all_paths_safe_label_zero(self) -> None:
        """When no path triggers liquidation, label = 0."""
        vault = self._make_vault(collateral=1.0, debt=100.0, price=300.0)
        # All 100 paths stay at $300 → HF = 2.4 → always safe
        paths = np.full((100, 25), 300.0)
        result = label_vault(vault, paths)
        self.assertEqual(result.binary_label, 0)
        self.assertAlmostEqual(result.liquidation_probability, 0.0)

    def test_all_paths_crash_label_one(self) -> None:
        """When all paths crash, probability=1.0, label=1."""
        vault = self._make_vault(collateral=1.0, debt=225.0, price=300.0)
        # HF at $100 = (100*80)/(225*100) = 0.356 → liquidated
        paths = np.full((100, 25), 100.0)
        result = label_vault(vault, paths)
        self.assertEqual(result.binary_label, 1)
        self.assertAlmostEqual(result.liquidation_probability, 1.0)

    def test_majority_vote_threshold(self) -> None:
        """label=1 iff probability > 0.5."""
        vault = self._make_vault(collateral=1.0, debt=200.0, price=300.0)
        n = 100
        # 60 paths crash (HF < 1.0), 40 are safe → prob = 0.6 > 0.5 → label=1
        crash = np.full((60, 25), 200.0)  # HF = (200*80)/(200*100) = 0.8
        safe = np.full((40, 25), 300.0)   # HF = (300*80)/(200*100) = 1.2
        paths = np.vstack([crash, safe])
        result = label_vault(vault, paths)
        self.assertEqual(result.binary_label, 1)
        self.assertAlmostEqual(result.liquidation_probability, 0.6, places=2)

    def test_minority_crash_label_zero(self) -> None:
        """30% paths crash → prob=0.3 < 0.5 → label=0."""
        vault = self._make_vault(collateral=1.0, debt=200.0, price=300.0)
        n = 100
        crash = np.full((30, 25), 200.0)  # HF = 0.8
        safe = np.full((70, 25), 300.0)   # HF = 1.2
        paths = np.vstack([crash, safe])
        result = label_vault(vault, paths)
        self.assertEqual(result.binary_label, 0)
        self.assertAlmostEqual(result.liquidation_probability, 0.3, places=2)

    def test_zero_debt_always_safe(self) -> None:
        vault = self._make_vault(collateral=1.0, debt=0.0, price=300.0)
        paths = np.full((50, 25), 1.0)  # even price of $1
        result = label_vault(vault, paths)
        self.assertEqual(result.binary_label, 0)

    def test_hf_checked_at_all_timesteps(self) -> None:
        """A single-timestep dip below HF=1.0 counts as liquidation."""
        vault = self._make_vault(collateral=1.0, debt=200.0, price=300.0)
        # 100 paths × 25 timesteps, all safe except col 12 for all paths
        paths = np.full((100, 25), 300.0)
        # Dip at timestep 12 to $200 → HF = 0.8
        paths[:, 12] = 200.0
        result = label_vault(vault, paths)
        self.assertEqual(result.binary_label, 1)
        self.assertAlmostEqual(result.liquidation_probability, 1.0)

    def test_boundary_hf_exactly_one_not_liquidated(self) -> None:
        """HF == 1.0 exactly is NOT < 1.0, so not liquidated."""
        vault = self._make_vault(collateral=1.0, debt=240.0, price=300.0)
        # HF = (300*80)/(240*100) = 1.0 → boundary → NOT liquidated
        paths = np.full((100, 25), 300.0)
        result = label_vault(vault, paths)
        self.assertEqual(result.binary_label, 0)


if __name__ == "__main__":
    unittest.main()
