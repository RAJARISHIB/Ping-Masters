"""Risk prediction API routes — v2.0.

Provides the ``POST /api/risk/predict`` endpoint.  Uses the v2
leakage-free model (4 raw-observable features).  Position-derived
metrics (HF, LTV, etc.) are computed ONLY for the response payload,
NOT as model inputs.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_predictor: Any = None


def _get_predictor() -> Any:
    """Return the singleton ``LiquidationPredictor``, creating it on first call."""
    global _predictor
    if _predictor is not None:
        return _predictor
    try:
        from ml.inference.predictor import LiquidationPredictor

        _predictor = LiquidationPredictor()
        return _predictor
    except FileNotFoundError:
        logger.warning("ML model not found — risk prediction will use fallback.")
        return None
    except ImportError:
        logger.warning("xgboost not installed — risk prediction unavailable.")
        return None
    except Exception:
        logger.exception("Failed to initialise LiquidationPredictor.")
        return None


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class RiskPredictRequest(BaseModel):
    wallet_address: str = Field(..., min_length=10)
    collateral_bnb: Optional[float] = Field(default=None, ge=0)
    debt_fiat: Optional[float] = Field(default=None, ge=0)
    current_price: Optional[float] = Field(default=None, gt=0)
    volatility: float = Field(default=0.80, gt=0, le=5.0)


class PredictionPayload(BaseModel):
    liquidation_probability: float
    risk_tier: str
    model_version: str


class PositionPayload(BaseModel):
    collateral_bnb: float
    collateral_value_fiat: float
    debt_fiat: float
    health_factor: float
    ltv: float
    is_liquidatable: bool


class RiskFactorsPayload(BaseModel):
    distance_to_liquidation_price: float
    liquidation_price: float
    volatility_estimate: float
    borrow_utilization: float


class RiskPredictResponse(BaseModel):
    wallet_address: str
    prediction: PredictionPayload
    current_position: PositionPayload
    risk_factors: RiskFactorsPayload
    timestamp: str


def _compute_position_metrics(
    collateral_bnb: float,
    debt_fiat: float,
    current_price: float,
    volatility: float,
) -> Dict[str, Any]:
    """Compute display-only position metrics (NOT used as model features)."""
    from common.protocol_constants import (
        compute_health_factor,
        compute_liquidation_price,
        compute_max_borrow,
        is_liquidatable,
    )

    collateral_value = collateral_bnb * current_price
    hf = compute_health_factor(collateral_value, debt_fiat)
    if math.isinf(hf):
        hf = 1e6
    liq_price = compute_liquidation_price(collateral_bnb, debt_fiat)
    if math.isinf(liq_price):
        liq_price = 0.0
    ltv = debt_fiat / collateral_value if collateral_value > 0 else 0.0
    dist = (current_price - liq_price) / current_price if current_price > 0 else 0.0
    max_borrow = compute_max_borrow(collateral_value)
    utilization = debt_fiat / max_borrow if max_borrow > 0 else 0.0

    return {
        "position": {
            "collateral_bnb": collateral_bnb,
            "collateral_value_fiat": collateral_value,
            "debt_fiat": debt_fiat,
            "health_factor": round(hf, 6),
            "ltv": round(ltv, 6),
            "is_liquidatable": is_liquidatable(hf),
        },
        "risk_factors": {
            "distance_to_liquidation_price": round(dist, 6),
            "liquidation_price": round(liq_price, 4),
            "volatility_estimate": volatility,
            "borrow_utilization": round(utilization, 6),
        },
    }


def _fallback_predict(
    collateral_bnb: float,
    debt_fiat: float,
    current_price: float,
    volatility: float,
) -> Dict[str, Any]:
    """Rule-based fallback when ML model isn't available."""
    from common.protocol_constants import compute_health_factor
    from ml.inference.predictor import classify_risk_tier

    collateral_value = collateral_bnb * current_price
    hf = compute_health_factor(collateral_value, debt_fiat)
    if math.isinf(hf):
        hf = 1e6

    if hf >= 2.0:
        prob = 0.01
    elif hf >= 1.5:
        prob = 0.05
    elif hf >= 1.2:
        prob = 0.15
    elif hf >= 1.0:
        prob = 0.40
    else:
        prob = 0.85

    return {
        "liquidation_probability": prob,
        "risk_tier": classify_risk_tier(prob),
        "model_version": "fallback-heuristic",
    }


def build_risk_router() -> APIRouter:
    router = APIRouter(prefix="/api/risk", tags=["risk"])

    @router.post(
        "/predict",
        summary="Predict liquidation probability (v2 stochastic estimator)",
        response_model=RiskPredictResponse,
    )
    def predict_risk(payload: RiskPredictRequest) -> RiskPredictResponse:
        collateral_bnb = payload.collateral_bnb
        debt_fiat = payload.debt_fiat
        current_price = payload.current_price
        volatility = payload.volatility

        if collateral_bnb is None or debt_fiat is None or current_price is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "On-chain client not configured.  "
                    "Provide collateral_bnb, debt_fiat, and current_price."
                ),
            )

        # Position metrics — display only, NOT model inputs
        metrics = _compute_position_metrics(collateral_bnb, debt_fiat, current_price, volatility)

        # Model prediction — uses only raw observables
        predictor = _get_predictor()
        if predictor is not None:
            try:
                result = predictor.predict(
                    collateral_bnb=collateral_bnb,
                    debt_fiat=debt_fiat,
                    current_price=current_price,
                    volatility=volatility,
                )
                prediction = PredictionPayload(
                    liquidation_probability=result.liquidation_probability,
                    risk_tier=result.risk_tier,
                    model_version=result.model_version,
                )
            except Exception:
                logger.exception("ML prediction failed — using fallback.")
                fb = _fallback_predict(collateral_bnb, debt_fiat, current_price, volatility)
                prediction = PredictionPayload(**fb)
        else:
            fb = _fallback_predict(collateral_bnb, debt_fiat, current_price, volatility)
            prediction = PredictionPayload(**fb)

        return RiskPredictResponse(
            wallet_address=payload.wallet_address,
            prediction=prediction,
            current_position=PositionPayload(**metrics["position"]),
            risk_factors=RiskFactorsPayload(**metrics["risk_factors"]),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    return router
