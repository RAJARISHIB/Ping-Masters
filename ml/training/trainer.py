"""Model training — v2.0 (leakage-free stochastic estimator).

Changes from v1:
  - Reads v2 feature set (4 raw observables only)
  - Reports Brier score for probability calibration
  - Warns if AUC > 0.99 (potential residual leakage)
  - Model version = v2.0
  - Saves class distribution in metadata
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

from ml.features.feature_extractor import FEATURE_NAMES

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
DEFAULT_DATASET = Path(__file__).parent / "dataset.csv"
MODEL_PATH = MODELS_DIR / "xgboost_liquidation.json"
METADATA_PATH = MODELS_DIR / "metadata.json"


def _load_dataset(path: Path) -> Tuple[pd.DataFrame, np.ndarray]:
    """Read CSV and split into features X and binary labels y."""
    df = pd.read_csv(path)
    X = df[FEATURE_NAMES]
    y = df["label"].values.astype(int)
    return X, y


def _evaluate(
    name: str,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_prob: np.ndarray,
) -> Dict[str, float]:
    """Compute classification + calibration metrics."""
    metrics: Dict[str, float] = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "brier_score": float(brier_score_loss(y_true, y_prob)),
    }
    try:
        metrics["auc_roc"] = float(roc_auc_score(y_true, y_prob))
    except ValueError:
        metrics["auc_roc"] = 0.0

    logger.info(
        "  %s  →  AUC=%.4f  Acc=%.4f  Prec=%.4f  Rec=%.4f  Brier=%.4f",
        name,
        metrics["auc_roc"],
        metrics["accuracy"],
        metrics["precision"],
        metrics["recall"],
        metrics["brier_score"],
    )

    # Leakage warning
    if metrics["auc_roc"] > 0.99:
        logger.warning(
            "⚠ Potential leakage still present. AUC=%.4f > 0.99 for %s",
            metrics["auc_roc"],
            name,
        )

    return metrics


def train(
    dataset_path: Path | str | None = None,
    test_size: float = 0.2,
    random_state: int = 42,
) -> Dict[str, Any]:
    """Train both models, evaluate, serialise the best.

    Returns
    -------
    dict
        Training summary including metrics for both models.
    """
    dataset_path = Path(dataset_path) if dataset_path else DEFAULT_DATASET
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found at {dataset_path}")

    logger.info("Loading dataset from %s", dataset_path)
    X, y = _load_dataset(dataset_path)
    n_pos = int(y.sum())
    n_neg = int(len(y) - n_pos)
    ratio = float(y.mean())
    logger.info(
        "Dataset: %d samples, %d features, label-0=%d, label-1=%d, ratio=%.3f",
        len(y),
        X.shape[1],
        n_neg,
        n_pos,
        ratio,
    )

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=y
    )

    results: Dict[str, Any] = {}

    # ----- Logistic Regression baseline -----
    logger.info("Training Logistic Regression baseline...")
    t0 = time.perf_counter()
    lr = LogisticRegression(max_iter=2000, random_state=random_state, solver="lbfgs")
    lr.fit(X_train, y_train)
    lr_time = time.perf_counter() - t0

    lr_pred = lr.predict(X_test)
    lr_prob = lr.predict_proba(X_test)[:, 1]
    lr_metrics = _evaluate("LogisticRegression", y_test, lr_pred, lr_prob)
    lr_metrics["training_seconds"] = round(lr_time, 3)
    results["logistic_regression"] = lr_metrics

    # ----- XGBoost classifier -----
    logger.info("Training XGBoost classifier...")
    t0 = time.perf_counter()

    try:
        import xgboost as xgb
    except ImportError as exc:
        raise ImportError(
            "xgboost is required for training.  Install with:  pip install xgboost"
        ) from exc

    xgb_clf = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        reg_alpha=0.1,
        eval_metric="logloss",
        random_state=random_state,
    )
    xgb_clf.fit(
        X_train,
        y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )
    xgb_time = time.perf_counter() - t0

    xgb_pred = xgb_clf.predict(X_test)
    xgb_prob = xgb_clf.predict_proba(X_test)[:, 1]
    xgb_metrics = _evaluate("XGBoost", y_test, xgb_pred, xgb_prob)
    xgb_metrics["training_seconds"] = round(xgb_time, 3)
    results["xgboost"] = xgb_metrics

    # ----- Feature importance -----
    importances = xgb_clf.feature_importances_
    importance_dict = dict(zip(FEATURE_NAMES, [float(v) for v in importances]))
    sorted_importance = sorted(importance_dict.items(), key=lambda x: x[1], reverse=True)

    logger.info("")
    logger.info("Feature importance (XGBoost, gain-based):")
    for fname, imp in sorted_importance:
        bar = "█" * int(imp * 50)
        logger.info("  %-25s  %.4f  %s", fname, imp, bar)

    # Volatility contribution check
    vol_importance = importance_dict.get("volatility_estimate", 0.0)
    if vol_importance < 0.05:
        logger.warning(
            "⚠ Model may still be threshold-dominated. "
            "volatility_estimate importance = %.4f (< 5%%)",
            vol_importance,
        )

    # ----- Serialise XGBoost -----
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    xgb_clf.save_model(str(MODEL_PATH))
    logger.info("XGBoost model saved to %s", MODEL_PATH)

    # ----- Metadata -----
    metadata = {
        "model_version": "v2.0",
        "training_date": datetime.now(timezone.utc).isoformat(),
        "dataset_path": str(dataset_path),
        "dataset_samples": int(len(y)),
        "class_distribution": {
            "label_0": n_neg,
            "label_1": n_pos,
            "label_1_ratio": round(ratio, 4),
        },
        "test_size": test_size,
        "feature_names": FEATURE_NAMES,
        "feature_importance": dict(sorted_importance),
        "metrics": results,
    }
    with METADATA_PATH.open("w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2)
    logger.info("Metadata saved to %s", METADATA_PATH)

    return metadata
