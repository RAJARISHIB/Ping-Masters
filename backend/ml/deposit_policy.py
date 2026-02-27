"""Rule-based deposit recommendation policy."""

import logging
from typing import Any, Dict

from .deposit_schema import DepositRecommendationRequest


logger = logging.getLogger(__name__)

DEFAULT_TARGET_LTV = {
    "LOW": 0.70,
    "MEDIUM": 0.50,
    "HIGH": 0.30,
}

DEFAULT_STRESS_DROP = {
    "stable": 0.02,
    "volatile": 0.20,
}


def recommend_deposit_by_policy(payload: DepositRecommendationRequest) -> Dict[str, Any]:
    """Compute recommended collateral and top-up using deterministic policy."""
    risk_tier = payload.risk_tier
    target_ltv = DEFAULT_TARGET_LTV.get(risk_tier, DEFAULT_TARGET_LTV["MEDIUM"])
    stress_drop_pct = payload.stress_drop_pct
    if stress_drop_pct is None:
        stress_drop_pct = DEFAULT_STRESS_DROP[payload.collateral_type]
    fees_buffer_pct = payload.fees_buffer_pct if payload.fees_buffer_pct is not None else 0.03

    debt_inr = payload.outstanding_debt_inr
    if debt_inr is None or debt_inr <= 0:
        debt_inr = payload.plan_amount_inr

    try:
        required_collateral_inr = (debt_inr * (1 + fees_buffer_pct)) / target_ltv / (1 - stress_drop_pct)
        required_collateral_token = required_collateral_inr / payload.price_inr
        topup_token = max(0.0, required_collateral_token - payload.locked_token)
        current_collateral_inr = payload.locked_token * payload.price_inr
        return {
            "mode": "policy",
            "risk_tier": risk_tier,
            "target_ltv": target_ltv,
            "stress_drop_pct": stress_drop_pct,
            "fees_buffer_pct": fees_buffer_pct,
            "required_inr": round(required_collateral_inr, 6),
            "required_token": round(required_collateral_token, 12),
            "current_locked_token": round(payload.locked_token, 12),
            "current_locked_inr": round(current_collateral_inr, 6),
            "topup_token": round(topup_token, 12),
            "reasons": [
                "risk_tier={0} -> target_ltv={1}".format(risk_tier, target_ltv),
                "stress_drop_pct={0}".format(round(stress_drop_pct, 4)),
                "fees_buffer_pct={0}".format(round(fees_buffer_pct, 4)),
            ],
        }
    except Exception:
        logger.exception("Policy deposit recommendation failed payload=%s", payload.dict())
        raise
