"""Synthetic vault generator — v2.0 with balanced class distribution.

Changes from v1:
  - LTV capped at 85% (reject extreme over-leverage)
  - Volatility sampled per vault (not a single global constant)
  - Target label-1 ratio between 0.3 and 0.7
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np

from ml.config import (
    LIQUIDATION_THRESHOLD_PERCENT,
    compute_health_factor,
)


@dataclass
class SyntheticVault:
    """One simulated lending-engine position."""

    collateral_bnb: float
    """Collateral deposited (BNB, human-readable, e.g. 1.5)."""

    debt_fiat: float
    """Outstanding debt in the user's fiat currency (e.g. 300.0 USD)."""

    current_price: float
    """Current oracle price of BNB in fiat (e.g. 300.0)."""

    ltv: float
    """Loan-to-Value ratio at creation time (0–1)."""

    health_factor: float
    """Health factor at current price (used for generation only, NOT a model feature)."""

    volatility: float
    """Per-vault annualised volatility estimate."""

    liquidation_threshold: float = LIQUIDATION_THRESHOLD_PERCENT / 100.0
    """Fraction form of the threshold (0.80)."""


def generate_vaults(
    n_vaults: int = 10_000,
    price_range: tuple[float, float] = (100.0, 1000.0),
    collateral_range: tuple[float, float] = (0.1, 100.0),
    ltv_range: tuple[float, float] = (0.10, 0.85),
    volatility_range: tuple[float, float] = (0.20, 1.00),
    seed: int = 42,
) -> List[SyntheticVault]:
    """Create *n_vaults* synthetic positions with balanced risk profiles.

    Parameters
    ----------
    n_vaults:
        Number of vaults to generate.
    price_range:
        (min, max) BNB price in fiat.
    collateral_range:
        (min, max) collateral in BNB.
    ltv_range:
        (min, max) loan-to-value ratio.  Capped at 0.85 to avoid
        unrealistic extreme leverage.
    volatility_range:
        (min, max) annualised volatility sampled per vault.
    seed:
        RNG seed.

    Returns
    -------
    List[SyntheticVault]
    """
    rng = np.random.default_rng(seed)

    collaterals = rng.uniform(*collateral_range, size=n_vaults)
    prices = rng.uniform(*price_range, size=n_vaults)
    ltvs = rng.uniform(*ltv_range, size=n_vaults)
    volatilities = rng.uniform(*volatility_range, size=n_vaults)

    vaults: List[SyntheticVault] = []
    for i in range(n_vaults):
        collateral = float(collaterals[i])
        price = float(prices[i])
        ltv = float(ltvs[i])
        vol = float(volatilities[i])

        collateral_value = collateral * price
        debt = collateral_value * ltv
        hf = compute_health_factor(collateral_value, debt)

        vaults.append(
            SyntheticVault(
                collateral_bnb=collateral,
                debt_fiat=debt,
                current_price=price,
                ltv=ltv,
                health_factor=hf,
                volatility=vol,
            )
        )

    return vaults
