"""Synthetic dataset generator for deposit recommendation regression."""

import logging

import numpy as np
import pandas as pd

from .deposit_policy import DEFAULT_STRESS_DROP, DEFAULT_TARGET_LTV


logger = logging.getLogger(__name__)


def generate_synthetic_deposit_dataset(rows: int = 10000, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic rows for training deposit recommendation model."""
    rng = np.random.default_rng(seed)

    risk_tiers = rng.choice(["LOW", "MEDIUM", "HIGH"], size=rows, p=[0.45, 0.35, 0.20])
    collateral_types = rng.choice(["stable", "volatile"], size=rows, p=[0.35, 0.65])
    plan_amount_inr = rng.uniform(1000, 200000, size=rows)
    tenure_days = rng.choice([30, 60, 90, 120, 180], size=rows)
    outstanding_debt_inr = plan_amount_inr * rng.uniform(0.7, 1.05, size=rows)
    price_inr = np.where(
        collateral_types == "stable",
        rng.uniform(70, 95, size=rows),
        rng.uniform(15000, 45000, size=rows),
    )

    stress_drop_pct = np.array([DEFAULT_STRESS_DROP[item] for item in collateral_types], dtype=float)
    fees_buffer_pct = rng.uniform(0.02, 0.06, size=rows)
    target_ltv = np.array([DEFAULT_TARGET_LTV[item] for item in risk_tiers], dtype=float)
    required_inr = (outstanding_debt_inr * (1 + fees_buffer_pct)) / target_ltv / (1 - stress_drop_pct)
    required_token = required_inr / price_inr
    locked_token = np.maximum(required_token * rng.uniform(0.2, 1.1, size=rows), 0.0)

    dataframe = pd.DataFrame(
        {
            "plan_amount_inr": plan_amount_inr,
            "tenure_days": tenure_days,
            "risk_tier": risk_tiers,
            "collateral_type": collateral_types,
            "locked_token": locked_token,
            "price_inr": price_inr,
            "stress_drop_pct": stress_drop_pct,
            "fees_buffer_pct": fees_buffer_pct,
            "outstanding_debt_inr": outstanding_debt_inr,
            "required_collateral_inr": required_inr,
        }
    )
    logger.info("Generated synthetic deposit dataset rows=%d", rows)
    return dataframe
