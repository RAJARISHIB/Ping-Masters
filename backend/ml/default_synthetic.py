"""Synthetic event dataset generator for next-installment default prediction."""

from datetime import datetime, timedelta, timezone
import logging

import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)


def generate_synthetic_default_dataset(rows: int = 12000, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic installment-event data with leakage-safe style features."""
    rng = np.random.default_rng(seed)

    base_time = datetime.now(timezone.utc) - timedelta(days=180)
    day_offsets = rng.integers(0, 180, size=rows)
    due_at = np.array([base_time + timedelta(days=int(offset)) for offset in day_offsets], dtype=object)
    cutoff_at = np.array([item - timedelta(days=2) for item in due_at], dtype=object)

    on_time_ratio = np.clip(rng.normal(0.78, 0.18, size=rows), 0, 1)
    missed_count_90d = rng.poisson(0.6, size=rows)
    max_days_late_180d = np.clip(rng.gamma(1.8, 2.8, size=rows), 0, 40)
    avg_days_late = np.clip(rng.gamma(1.5, 1.8, size=rows), 0, 30)
    days_since_last_late = np.clip(rng.gamma(2.5, 8.0, size=rows), 0, 180)
    consecutive_on_time_count = rng.poisson(4.0, size=rows)

    plan_amount = rng.uniform(1000, 150000, size=rows)
    tenure_days = rng.choice([30, 60, 90, 120, 180], size=rows)
    installment_number = rng.integers(1, 7, size=rows)
    installment_amount = np.maximum(plan_amount / np.maximum(tenure_days / 30, 1), 100)
    days_until_due = np.clip(rng.normal(2.0, 1.2, size=rows), 0, 7)

    current_safety_ratio = np.clip(rng.normal(1.35, 0.35, size=rows), 0.65, 2.5)
    distance_to_liquidation_threshold = current_safety_ratio - 1.0
    collateral_type = rng.choice(["stable", "volatile"], size=rows, p=[0.35, 0.65])
    collateral_volatility_bucket = np.where(
        collateral_type == "stable",
        rng.choice(["low", "medium"], size=rows, p=[0.8, 0.2]),
        rng.choice(["medium", "high"], size=rows, p=[0.4, 0.6]),
    )
    topup_count_30d = rng.poisson(1.2, size=rows)
    topup_recency_days = np.clip(rng.gamma(2.0, 4.0, size=rows), 0, 30)

    opened_app_last_7d = rng.binomial(1, 0.65, size=rows)
    clicked_pay_now_last_7d = rng.binomial(1, 0.30, size=rows)
    payment_attempt_failed_count = rng.poisson(0.4, size=rows)
    wallet_age_days = np.clip(rng.gamma(4.0, 60.0, size=rows), 1, 2000)
    tx_count_30d = np.clip(rng.poisson(22.0, size=rows), 0, 250)
    stablecoin_balance_bucket = rng.choice(["low", "medium", "high"], size=rows, p=[0.35, 0.45, 0.20])

    # Probability design for y=miss next installment (structured, explainable)
    z = (
        2.2 * (1.0 - on_time_ratio)
        + 0.35 * missed_count_90d
        + 0.03 * max_days_late_180d
        + 0.04 * avg_days_late
        + 0.06 * np.maximum(0, 2.0 - days_since_last_late)
        + 0.25 * (days_until_due <= 1).astype(float)
        + 0.55 * np.maximum(0, 1.1 - current_safety_ratio)
        + 0.18 * (collateral_type == "volatile").astype(float)
        + 0.22 * (collateral_volatility_bucket == "high").astype(float)
        + 0.12 * payment_attempt_failed_count
        - 0.18 * opened_app_last_7d
        - 0.12 * clicked_pay_now_last_7d
        - 0.02 * consecutive_on_time_count
        - 0.000008 * wallet_age_days
    )
    probability = 1.0 / (1.0 + np.exp(-(z - 1.2)))
    y_miss_next = rng.binomial(1, np.clip(probability, 0.02, 0.95), size=rows)

    dataframe = pd.DataFrame(
        {
            "due_at": due_at,
            "cutoff_at": cutoff_at,
            "on_time_ratio": on_time_ratio,
            "missed_count_90d": missed_count_90d,
            "max_days_late_180d": max_days_late_180d,
            "avg_days_late": avg_days_late,
            "days_since_last_late": days_since_last_late,
            "consecutive_on_time_count": consecutive_on_time_count,
            "plan_amount": plan_amount,
            "tenure_days": tenure_days,
            "installment_amount": installment_amount,
            "installment_number": installment_number,
            "days_until_due": days_until_due,
            "current_safety_ratio": current_safety_ratio,
            "distance_to_liquidation_threshold": distance_to_liquidation_threshold,
            "collateral_type": collateral_type,
            "collateral_volatility_bucket": collateral_volatility_bucket,
            "topup_count_30d": topup_count_30d,
            "topup_recency_days": topup_recency_days,
            "opened_app_last_7d": opened_app_last_7d,
            "clicked_pay_now_last_7d": clicked_pay_now_last_7d,
            "payment_attempt_failed_count": payment_attempt_failed_count,
            "wallet_age_days": wallet_age_days,
            "tx_count_30d": tx_count_30d,
            "stablecoin_balance_bucket": stablecoin_balance_bucket,
            "y_miss_next": y_miss_next,
        }
    )
    logger.info("Generated synthetic default dataset rows=%d", rows)
    return dataframe
