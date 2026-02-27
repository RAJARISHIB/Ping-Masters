"""Leakage-free feature extraction for stochastic liquidation estimation.

v2.0 — Removes all deterministic leakage features that directly encode
the liquidation condition (HF, LTV, distance-to-liquidation, borrow
utilization, collateral-value-fiat).  These are computable from the raw
inputs via a known formula and therefore leak the label.

Model inputs are restricted to OBSERVABLE STATE that does NOT
deterministically encode the liquidation boundary:

    collateral_bnb   — raw position size
    debt_fiat        — raw obligation
    price_current    — current oracle snapshot
    volatility       — estimated future uncertainty (the only forward-looking input)

The model must LEARN the non-linear mapping from these raw observables
(under stochastic volatility) to liquidation probability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

# Ordered list — must match training column order exactly.
FEATURE_NAMES: list[str] = [
    "collateral_bnb",
    "debt_fiat",
    "price_current",
    "volatility_estimate",
]


@dataclass
class VaultFeatures:
    """Leakage-free feature vector for a single vault position."""

    collateral_bnb: float
    debt_fiat: float
    price_current: float
    volatility_estimate: float

    def to_dict(self) -> Dict[str, float]:
        """Return an ordered dictionary matching ``FEATURE_NAMES``."""
        return {name: getattr(self, name) for name in FEATURE_NAMES}

    def to_list(self) -> list[float]:
        """Return feature values in canonical column order."""
        return [getattr(self, name) for name in FEATURE_NAMES]


def extract_features(
    collateral_bnb: float,
    debt_fiat: float,
    current_price: float,
    volatility: float,
) -> VaultFeatures:
    """Build the leakage-free feature vector from raw vault state.

    Parameters
    ----------
    collateral_bnb:
        Collateral in BNB (human-readable, e.g. 1.5).
    debt_fiat:
        Outstanding debt in fiat (human-readable, e.g. 300.0).
    current_price:
        BNB oracle price in fiat (human-readable).
    volatility:
        Annualised volatility estimate (e.g. 0.80 for 80%).

    Returns
    -------
    VaultFeatures
    """
    return VaultFeatures(
        collateral_bnb=collateral_bnb,
        debt_fiat=debt_fiat,
        price_current=current_price,
        volatility_estimate=volatility,
    )
