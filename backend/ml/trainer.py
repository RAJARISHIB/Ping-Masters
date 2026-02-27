"""Training pipeline for multiclass risk tier model."""

import logging
from pathlib import Path
from typing import Dict, List

import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


logger = logging.getLogger(__name__)

FEATURE_COLUMNS: List[str] = [
    "safety_ratio",
    "missed_payment_count",
    "on_time_ratio",
    "avg_delay_hours",
    "topup_count_last_30d",
    "plan_amount",
    "tenure_days",
    "installment_amount",
]


def train_and_save_model(dataframe: pd.DataFrame, output_path: str) -> Dict[str, str]:
    """Train logistic regression model and save artifact.

    Args:
        dataframe: Dataset with feature columns and `risk_tier`.
        output_path: Target artifact file path.

    Returns:
        Dict[str, str]: Training summary.
    """
    required_columns = set(FEATURE_COLUMNS + ["risk_tier"])
    missing = required_columns.difference(dataframe.columns)
    if missing:
        raise ValueError("Missing required columns: {0}".format(sorted(missing)))

    x = dataframe[FEATURE_COLUMNS].copy()
    y = dataframe["risk_tier"].copy()

    x_train, x_test, y_train, y_test = train_test_split(
        x,
        y,
        test_size=0.2,
        random_state=42,
        stratify=y,
    )

    pipeline = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    multi_class="ovr",
                    max_iter=1200,
                    random_state=42,
                ),
            ),
        ]
    )
    pipeline.fit(x_train, y_train)
    y_pred = pipeline.predict(x_test)
    report = classification_report(y_test, y_pred, output_dict=False)
    logger.info("Training complete.\n%s", report)

    artifact = {
        "pipeline": pipeline,
        "feature_columns": FEATURE_COLUMNS,
        "model_name": "logistic_regression_ovr",
        "version": "v1",
    }

    model_path = Path(output_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_path)
    logger.info("Model artifact saved at %s", model_path)

    return {
        "model_path": str(model_path),
        "model_name": artifact["model_name"],
        "version": artifact["version"],
    }
