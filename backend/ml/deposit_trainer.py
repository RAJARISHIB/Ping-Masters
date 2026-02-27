"""Training pipeline for deposit recommendation regression model."""

import logging
from pathlib import Path
from typing import Dict, List

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


logger = logging.getLogger(__name__)

FEATURE_COLUMNS: List[str] = [
    "plan_amount_inr",
    "tenure_days",
    "risk_tier",
    "collateral_type",
    "locked_token",
    "price_inr",
    "stress_drop_pct",
    "fees_buffer_pct",
    "outstanding_debt_inr",
]


def train_and_save_deposit_model(dataframe: pd.DataFrame, output_path: str) -> Dict[str, str]:
    """Train regressor for required collateral INR and save artifact."""
    required_columns = set(FEATURE_COLUMNS + ["required_collateral_inr"])
    missing_columns = required_columns.difference(dataframe.columns)
    if missing_columns:
        raise ValueError("Missing required columns: {0}".format(sorted(missing_columns)))

    x = dataframe[FEATURE_COLUMNS].copy()
    y = dataframe["required_collateral_inr"].copy()

    categorical_cols = ["risk_tier", "collateral_type"]
    numeric_cols = [column for column in FEATURE_COLUMNS if column not in categorical_cols]

    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical_cols),
            ("num", "passthrough", numeric_cols),
        ]
    )
    model = RandomForestRegressor(
        n_estimators=250,
        random_state=42,
        max_depth=12,
        min_samples_leaf=2,
        n_jobs=-1,
    )
    pipeline = Pipeline(steps=[("preprocessor", preprocessor), ("model", model)])

    x_train, x_test, y_train, y_test = train_test_split(
        x,
        y,
        test_size=0.2,
        random_state=42,
    )
    pipeline.fit(x_train, y_train)
    prediction = pipeline.predict(x_test)
    mae = mean_absolute_error(y_test, prediction)
    logger.info("Deposit model training complete mae=%.6f", mae)

    artifact = {
        "pipeline": pipeline,
        "feature_columns": FEATURE_COLUMNS,
        "model_name": "random_forest_regressor",
        "version": "v1",
        "metric_mae": float(mae),
    }
    model_path = Path(output_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_path)
    logger.info("Deposit model artifact saved at %s", model_path)

    return {
        "model_path": str(model_path),
        "model_name": artifact["model_name"],
        "version": artifact["version"],
        "metric_mae": str(round(float(mae), 6)),
    }
