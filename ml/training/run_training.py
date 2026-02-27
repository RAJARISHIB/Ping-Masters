#!/usr/bin/env python
"""End-to-end training script — v2.0 (leakage-free stochastic estimator).

Usage:
    python -m ml.training.run_training          (from repo root)
    python ml/training/run_training.py          (from repo root)

Steps:
    1. Generate balanced, leakage-free dataset
    2. Train LogReg + XGBoost with Brier score
    3. Feature importance analysis
    4. Volatility sensitivity validation
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _run_volatility_sensitivity(logger: logging.Logger) -> None:
    """Phase 5 — Validate the model is volatility-aware.

    Holds collateral, debt, and price constant while sweeping volatility.
    Predicted risk must increase monotonically with volatility.
    """
    from ml.inference.predictor import LiquidationPredictor

    try:
        predictor = LiquidationPredictor()
    except FileNotFoundError:
        logger.error("Cannot run volatility sensitivity — model not found.")
        return

    collateral_bnb = 1.0
    debt_fiat = 200.0
    current_price = 300.0

    volatilities = [0.20, 0.40, 0.60, 0.80, 1.00]
    probs: list[float] = []

    logger.info("")
    logger.info("=" * 60)
    logger.info("VOLATILITY SENSITIVITY VALIDATION")
    logger.info("=" * 60)
    logger.info(
        "Fixed position: collateral=%.1f BNB  debt=$%.0f  price=$%.0f",
        collateral_bnb,
        debt_fiat,
        current_price,
    )
    logger.info("")
    logger.info("  %-15s  %-20s  %-10s", "Volatility", "Predicted Risk", "Tier")
    logger.info("  " + "-" * 50)

    for vol in volatilities:
        result = predictor.predict(
            collateral_bnb=collateral_bnb,
            debt_fiat=debt_fiat,
            current_price=current_price,
            volatility=vol,
        )
        prob = result.liquidation_probability
        probs.append(prob)
        logger.info("  %-15.2f  %-20.6f  %-10s", vol, prob, result.risk_tier)

    # Monotonicity check
    is_monotonic = all(probs[i] <= probs[i + 1] for i in range(len(probs) - 1))
    logger.info("")
    if is_monotonic:
        logger.info("✓ Predicted risk increases monotonically with volatility.")
    else:
        logger.warning(
            "⚠ DIAGNOSTIC: Predicted risk is NOT monotonically increasing with "
            "volatility. This may indicate the model has not fully learned "
            "the volatility → risk relationship, or that the dataset does "
            "not contain sufficient volatility variation."
        )
        # Print pairwise deltas for diagnosis
        for i in range(len(probs) - 1):
            delta = probs[i + 1] - probs[i]
            sign = "+" if delta >= 0 else ""
            logger.info(
                "    vol %.2f → %.2f:  Δprob = %s%.6f",
                volatilities[i],
                volatilities[i + 1],
                sign,
                delta,
            )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    logger = logging.getLogger("run_training")

    from ml.training.generate_dataset import generate_dataset
    from ml.training.trainer import train

    # --- Step 1: Generate dataset ---
    logger.info("=" * 60)
    logger.info("STEP 1 / 3 — Generating leakage-free balanced dataset")
    logger.info("=" * 60)
    dataset_path = generate_dataset(
        n_vaults=15_000,
        n_simulations=2_000,
        horizon_hours=24,
        seed=42,
    )

    # --- Step 2: Train models ---
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 2 / 3 — Training models (v2.0)")
    logger.info("=" * 60)
    metadata = train(dataset_path=dataset_path)

    # --- Summary ---
    logger.info("")
    logger.info("=" * 60)
    logger.info("TRAINING COMPLETE — v2.0")
    logger.info("=" * 60)
    logger.info("Model version  : %s", metadata["model_version"])
    logger.info("Dataset samples: %d", metadata["dataset_samples"])

    cd = metadata.get("class_distribution", {})
    logger.info(
        "Class dist     : label-0=%d  label-1=%d  ratio=%.4f",
        cd.get("label_0", 0),
        cd.get("label_1", 0),
        cd.get("label_1_ratio", 0),
    )
    logger.info("Features       : %s", metadata["feature_names"])

    for model_name, metrics in metadata["metrics"].items():
        logger.info(
            "  %-20s  AUC=%.4f  Acc=%.4f  Prec=%.4f  Rec=%.4f  Brier=%.4f  (%.2fs)",
            model_name,
            metrics.get("auc_roc", 0),
            metrics.get("accuracy", 0),
            metrics.get("precision", 0),
            metrics.get("recall", 0),
            metrics.get("brier_score", 0),
            metrics.get("training_seconds", 0),
        )

    models_dir = Path(metadata.get("dataset_path", "")).parent.parent / "models"
    logger.info("")
    logger.info("Serialised model : %s", models_dir / "xgboost_liquidation.json")
    logger.info("Metadata         : %s", models_dir / "metadata.json")

    # --- Step 3: Volatility sensitivity ---
    _run_volatility_sensitivity(logger)


if __name__ == "__main__":
    main()
