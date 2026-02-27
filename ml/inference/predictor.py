"""Model inference — v2.0 (leakage-free stochastic estimator)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import numpy as np

from ml.features.feature_extractor import FEATURE_NAMES, VaultFeatures, extract_features

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_PATH = MODELS_DIR / "xgboost_liquidation.json"
METADATA_PATH = MODELS_DIR / "metadata.json"


def classify_risk_tier(probability: float) -> str:
    """Map a liquidation probability to a human-readable risk tier."""
    if probability < 0.05:
        return "LOW"
    if probability < 0.20:
        return "MEDIUM"
    if probability < 0.50:
        return "HIGH"
    return "CRITICAL"


@dataclass
class PredictionResult:
    """Output of a single prediction."""

    liquidation_probability: float
    risk_tier: str
    model_version: str
    feature_values: Dict[str, float]


class LiquidationPredictor:
    """Loads a serialised XGBoost model and produces predictions."""

    def __init__(self, model_path: Path | str | None = None) -> None:
        model_path = Path(model_path) if model_path else MODEL_PATH
        if not model_path.exists():
            raise FileNotFoundError(
                f"Serialised model not found at {model_path}.  "
                "Run the training pipeline first:  python -m ml.training.run_training"
            )

        try:
            import xgboost as xgb
        except ImportError as exc:
            raise ImportError(
                "xgboost is required for inference.  Install with:  pip install xgboost"
            ) from exc

        self._model = xgb.XGBClassifier()
        self._model.load_model(str(model_path))
        logger.info("Loaded XGBoost model from %s", model_path)

        self._model_version = "unknown"
        meta_path = model_path.parent / "metadata.json"
        if meta_path.exists():
            with meta_path.open("r", encoding="utf-8") as fh:
                meta = json.load(fh)
                self._model_version = meta.get("model_version", "unknown")

    @property
    def model_version(self) -> str:
        return self._model_version

    def predict_from_features(self, features: VaultFeatures) -> PredictionResult:
        """Run inference on a pre-computed feature vector."""
        feature_array = np.array([features.to_list()], dtype=np.float64)
        prob = float(self._model.predict_proba(feature_array)[0, 1])
        return PredictionResult(
            liquidation_probability=round(prob, 6),
            risk_tier=classify_risk_tier(prob),
            model_version=self._model_version,
            feature_values=features.to_dict(),
        )

    def predict(
        self,
        collateral_bnb: float,
        debt_fiat: float,
        current_price: float,
        volatility: float = 0.80,
    ) -> PredictionResult:
        """Full pipeline: extract features then predict."""
        features = extract_features(
            collateral_bnb=collateral_bnb,
            debt_fiat=debt_fiat,
            current_price=current_price,
            volatility=volatility,
        )
        return self.predict_from_features(features)
