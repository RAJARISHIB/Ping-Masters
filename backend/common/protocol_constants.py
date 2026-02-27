"""Canonical protocol constants and math — single source of truth.

Every formula here MUST match LendingEngine.sol exactly.

Solidity reference (LendingEngine.sol lines 356-363):
    function _calculateHealthFactor(address user) internal view returns (uint256) {
        uint256 debt = borrowedAmount[user];
        if (debt == 0) return type(uint256).max;
        PriceConsumer.Currency cur = userCurrency[user];
        uint256 price   = priceOracle.getLatestPrice(cur);
        uint256 colFiat = _toFiatValue(collateralAmount[user], price);
        return (colFiat * LIQUIDATION_THRESHOLD * PRECISION) / (debt * 100);
    }

    function _toFiatValue(uint256 bnbWei, uint256 price) internal pure returns (uint256) {
        return (bnbWei * price) / PRICE_DECIMALS;
    }
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# On-chain scaling factors
# ---------------------------------------------------------------------------
PRECISION: int = 10**18
PRICE_DECIMALS: int = 10**8

# ---------------------------------------------------------------------------
# Protocol risk parameters  (percentage, NOT basis-points)
# ---------------------------------------------------------------------------
LIQUIDATION_THRESHOLD_PERCENT: int = 80   # 80 %
LIQUIDATION_BONUS_PERCENT: int = 5        # 5 %
MAX_LTV_PERCENT: int = 75                 # 75 %

# ---------------------------------------------------------------------------
# Token / asset decimals
# ---------------------------------------------------------------------------
BNB_DECIMALS: int = 18
DEBT_TOKEN_DECIMALS: int = 18


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def raw_to_human_price(raw_price: int) -> float:
    """Convert an 8-decimal on-chain price to a human-readable float.

    Example:  30_000_000_000  ->  300.0  ($300)
    """
    return raw_price / PRICE_DECIMALS


def raw_to_human_hf(raw_hf: int) -> float:
    """Convert an 18-decimal on-chain health-factor to a human-readable float.

    Example:  1_200_000_000_000_000_000  ->  1.2
    """
    return raw_hf / PRECISION


def human_to_raw_price(human_price: float) -> int:
    """Convert a human-readable price to 8-decimal on-chain integer."""
    return int(human_price * PRICE_DECIMALS)


def to_fiat_value(bnb_wei: int, raw_price: int) -> int:
    """Mirror LendingEngine._toFiatValue — returns 18-decimal fiat value."""
    return (bnb_wei * raw_price) // PRICE_DECIMALS


# ---------------------------------------------------------------------------
# Health-factor computation  (human-scale floats, used by ML + backend)
# ---------------------------------------------------------------------------

def compute_health_factor(collateral_value_fiat: float, debt_fiat: float) -> float:
    """Canonical health-factor identical to LendingEngine._calculateHealthFactor.

    Contract formula (integer arithmetic, 1e18-scaled):
        HF = (colFiat * LIQUIDATION_THRESHOLD * PRECISION) / (debt * 100)

    In human-readable floats the PRECISION terms cancel:
        HF = (colFiat * LIQUIDATION_THRESHOLD) / (debt * 100)
           = colFiat * 0.80 / debt

    Returns ``math.inf`` when *debt_fiat* <= 0, matching the Solidity
    ``type(uint256).max`` sentinel.
    """
    if debt_fiat <= 0.0:
        return math.inf
    return (collateral_value_fiat * LIQUIDATION_THRESHOLD_PERCENT) / (debt_fiat * 100)


def compute_health_factor_raw(collateral_fiat_raw: int, debt_raw: int) -> int:
    """Integer-precision HF matching LendingEngine exactly (18-decimal result)."""
    if debt_raw == 0:
        return 2**256 - 1  # type(uint256).max
    return (collateral_fiat_raw * LIQUIDATION_THRESHOLD_PERCENT * PRECISION) // (debt_raw * 100)


def is_liquidatable(health_factor: float) -> bool:
    """Return *True* when a position can be liquidated (HF < 1.0)."""
    return health_factor < 1.0


def compute_liquidation_price(
    collateral_bnb: float,
    debt_fiat: float,
) -> float:
    """Price at which HF == 1.0 (liquidation boundary).

    Derivation from HF formula:
        1.0 = (collateral_bnb * liq_price * THRESHOLD%) / (debt * 100)
        liq_price = (debt * 100) / (collateral_bnb * THRESHOLD%)
    """
    if collateral_bnb <= 0.0:
        return math.inf
    return (debt_fiat * 100) / (collateral_bnb * LIQUIDATION_THRESHOLD_PERCENT)


def compute_max_borrow(collateral_value_fiat: float) -> float:
    """Maximum borrowable amount for a given collateral value (human-scale)."""
    return (collateral_value_fiat * MAX_LTV_PERCENT) / 100
