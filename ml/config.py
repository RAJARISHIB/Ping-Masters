"""ML module configuration — imports canonical constants from backend."""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the backend package is importable regardless of working-directory.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_DIR = _REPO_ROOT / "backend"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Re-export every canonical constant so ML sub-modules only need:
#   from ml.config import LIQUIDATION_THRESHOLD_PERCENT, compute_health_factor, ...
from common.protocol_constants import (  # noqa: E402
    BNB_DECIMALS,
    DEBT_TOKEN_DECIMALS,
    LIQUIDATION_BONUS_PERCENT,
    LIQUIDATION_THRESHOLD_PERCENT,
    MAX_LTV_PERCENT,
    PRECISION,
    PRICE_DECIMALS,
    compute_health_factor,
    compute_liquidation_price,
    compute_max_borrow,
    is_liquidatable,
    raw_to_human_hf,
    raw_to_human_price,
)

__all__ = [
    "BNB_DECIMALS",
    "DEBT_TOKEN_DECIMALS",
    "LIQUIDATION_BONUS_PERCENT",
    "LIQUIDATION_THRESHOLD_PERCENT",
    "MAX_LTV_PERCENT",
    "PRECISION",
    "PRICE_DECIMALS",
    "compute_health_factor",
    "compute_liquidation_price",
    "compute_max_borrow",
    "is_liquidatable",
    "raw_to_human_hf",
    "raw_to_human_price",
]
