"""Training pipeline for next-installment default prediction model."""

import logging
from pathlib import Path
from typing import Dict, List

import joblib
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


logger = logging.getLogger(__name__)

FEATURE_COLUMNS: List[str] = [
    "on_time_ratio",
    "missed_count_90d",
    "max_days_late_180d",
    "avg_days_late",
    "days_since_last_late",
    "consecutive_on_time_count",
    "plan_amount",
    "tenure_days",
    "installment_amount",
    "installment_number",
    "days_until_due",
    "current_safety_ratio",
    "distance_to_liquidation_threshold",
    "collateral_type",
    "collateral_volatility_bucket",
    "topup_count_30d",
    "topup_recency_days",
    "opened_app_last_7d",
    "clicked_pay_now_last_7d",
    "payment_attempt_failed_count",
    "wallet_age_days",
    "tx_count_30d",
    "stablecoin_balance_bucket",
]


def train_and_save_default_model(
    dataframe: pd.DataFrame,
    output_path: str,
    high_threshold: float = 0.60,
    medium_threshold: float = 0.30,
) -> Dict[str, str]:
    """Train calibrated GBDT classifier with time-based split and save artifact."""
    required = set(FEATURE_COLUMNS + ["y_miss_next", "due_at"])
    missing = required.difference(dataframe.columns)
    if missing:
        raise ValueError("Missing required columns: {0}".format(sorted(missing)))

    frame = dataframe.sort_values("due_at").reset_index(drop=True)
    split_index = int(len(frame) * 0.8)
    train_frame = frame.iloc[:split_index]
    test_frame = frame.iloc[split_index:]

    x_train = train_frame[FEATURE_COLUMNS].copy()
    y_train = train_frame["y_miss_next"].astype(int).copy()
    x_test = test_frame[FEATURE_COLUMNS].copy()
    y_test = test_frame["y_miss_next"].astype(int).copy()

    categorical_columns = ["collateral_type", "collateral_volatility_bucket", "stablecoin_balance_bucket"]
    numeric_columns = [column for column in FEATURE_COLUMNS if column not in categorical_columns]

    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical_columns),
            ("num", StandardScaler(), numeric_columns),
        ]
    )
    gbdt = GradientBoostingClassifier(
        n_estimators=220,
        learning_rate=0.06,
        max_depth=3,
        random_state=42,
    )
    base_pipeline = Pipeline([("preprocessor", preprocessor), ("model", gbdt)])

    calibrated_model = CalibratedClassifierCV(estimator=base_pipeline, method="sigmoid", cv=3)
    calibrated_model.fit(x_train, y_train)

    proba = calibrated_model.predict_proba(x_test)[:, 1]
    roc_auc = roc_auc_score(y_test, proba)
    pr_auc = average_precision_score(y_test, proba)
    logger.info("Default model training complete roc_auc=%.6f pr_auc=%.6f", roc_auc, pr_auc)

    artifact = {
        "model": calibrated_model,
        "feature_columns": FEATURE_COLUMNS,
        "model_name": "gradient_boosting_calibrated",
        "version": "v1",
        "roc_auc": float(roc_auc),
        "pr_auc": float(pr_auc),
        "high_threshold": float(high_threshold),
        "medium_threshold": float(medium_threshold),
    }
    model_path = Path(output_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_path)
    logger.info("Default prediction model artifact saved at %s", model_path)

    return {
        "model_path": str(model_path),
        "model_name": artifact["model_name"],
        "version": artifact["version"],
        "roc_auc": str(round(artifact["roc_auc"], 6)),
        "pr_auc": str(round(artifact["pr_auc"], 6)),
    }
