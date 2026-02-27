"""Synthetic data generator for hackathon-friendly risk model training."""

import logging
from typing import List

import numpy as np
import pandas as pd

try:
    from common.emi_plan_catalog import get_default_emi_plan_catalog
except ImportError:  # pragma: no cover - compatibility for script package style imports
    from backend.common.emi_plan_catalog import get_default_emi_plan_catalog


logger = logging.getLogger(__name__)


def _assign_risk_tier(safety_ratio: float, missed_payment_count: int, avg_delay_hours: float, overdue_now: int) -> str:
    """Assign risk tier using simple explainable rule logic."""
    if missed_payment_count >= 1 or overdue_now == 1 or safety_ratio < 1.05:
        return "HIGH"
    if 1.05 <= safety_ratio < 1.25 or avg_delay_hours > 6:
        return "MEDIUM"
    return "LOW"


def generate_synthetic_risk_dataset(rows: int = 10000, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic BNPL risk training dataset.

    Args:
        rows: Number of synthetic records.
        seed: Random seed for reproducibility.

    Returns:
        pd.DataFrame: Feature matrix and `risk_tier` label.
    """
    rng = np.random.default_rng(seed)

    plans = get_default_emi_plan_catalog().list_plan_models(include_disabled=False)
    if plans:
        selected_indices = rng.integers(0, len(plans), size=rows)
        selected_plans = [plans[idx] for idx in selected_indices]
        tenure_days = np.array([plan.tenure_days for plan in selected_plans], dtype=int)
        installment_count = np.array([plan.installment_count for plan in selected_plans], dtype=int)
        plan_amount = np.array(
            [
                rng.uniform(
                    max(float(plan.principal_min_minor), 1000.0),
                    max(float(plan.principal_max_minor), max(float(plan.principal_min_minor), 1000.0) + 1.0),
                )
                for plan in selected_plans
            ],
            dtype=float,
        )
        emi_plan_id = np.array([plan.plan_id for plan in selected_plans], dtype=object)
        cadence_days = np.array([plan.cadence_days for plan in selected_plans], dtype=int)
    else:
        plan_amount = rng.uniform(1000, 100000, size=rows)
        tenure_days = rng.choice([30, 60, 90, 120, 180], size=rows)
        installment_count = np.clip((tenure_days / 30).astype(int), 1, None)
        emi_plan_id = np.array(["fallback_plan"] * rows, dtype=object)
        cadence_days = np.maximum(1, (tenure_days / np.maximum(installment_count, 1)).astype(int))
    installment_amount = plan_amount / installment_count

    collateral_buffer = rng.uniform(0.8, 1.8, size=rows)
    outstanding_debt = plan_amount * rng.uniform(0.3, 1.0, size=rows)
    collateral_value = outstanding_debt * collateral_buffer
    safety_ratio = collateral_value / np.maximum(outstanding_debt, 1.0)

    risk_pressure = (
        (1.25 - np.clip(safety_ratio, 0.5, 2.5))
        + (tenure_days / 180.0)
        + (installment_amount / np.maximum(plan_amount, 1.0))
    )
    risk_pressure = np.clip(risk_pressure, 0.0, 2.0)

    missed_payment_count = rng.binomial(n=3, p=np.clip(risk_pressure / 3.0, 0.01, 0.75), size=rows)
    avg_delay_hours = rng.gamma(shape=1.5 + risk_pressure, scale=2.0)
    on_time_ratio = np.clip(1.0 - (missed_payment_count * 0.15 + avg_delay_hours / 72.0), 0.0, 1.0)
    topup_count_last_30d = rng.binomial(
        n=4,
        p=np.clip((1.3 - np.clip(safety_ratio, 0.5, 2.5)) / 2.0, 0.05, 0.8),
        size=rows,
    )
    overdue_now = rng.binomial(n=1, p=np.clip((1.1 - np.clip(safety_ratio, 0.5, 2.5)) / 1.5, 0.01, 0.9), size=rows)

    risk_tier: List[str] = []
    for i in range(rows):
        risk_tier.append(
            _assign_risk_tier(
                safety_ratio=float(safety_ratio[i]),
                missed_payment_count=int(missed_payment_count[i]),
                avg_delay_hours=float(avg_delay_hours[i]),
                overdue_now=int(overdue_now[i]),
            )
        )

    dataframe = pd.DataFrame(
        {
            "safety_ratio": safety_ratio,
            "missed_payment_count": missed_payment_count,
            "on_time_ratio": on_time_ratio,
            "avg_delay_hours": avg_delay_hours,
            "topup_count_last_30d": topup_count_last_30d,
            "plan_amount": plan_amount,
            "tenure_days": tenure_days,
            "installment_amount": installment_amount,
            "emi_plan_id": emi_plan_id,
            "cadence_days": cadence_days,
            "risk_tier": risk_tier,
        }
    )
    logger.info("Generated synthetic dataset rows=%d", rows)
    return dataframe
