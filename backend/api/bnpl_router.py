"""BNPL feature router exposing borrower, merchant, protocol, and trust APIs."""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from services.bnpl_feature_service import BnplFeatureService


logger = logging.getLogger(__name__)


class BnplCreatePlanRequest(BaseModel):
    """Request payload for BNPL plan and schedule generation."""

    user_id: str = Field(..., min_length=3)
    merchant_id: str = Field(..., min_length=3)
    principal_minor: int = Field(..., gt=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    installment_count: int = Field(default=4, gt=0)
    tenure_days: int = Field(default=120, gt=0)
    ltv_bps: int = Field(default=7000, gt=0, le=10000)
    danger_limit_bps: int = Field(default=8000, gt=0, le=10000)
    liquidation_threshold_bps: int = Field(default=9000, gt=0, le=10000)
    grace_window_hours: int = Field(default=24, ge=0)
    late_fee_flat_minor: int = Field(default=0, ge=0)
    late_fee_bps: int = Field(default=0, ge=0, le=10000)
    emi_plan_id: Optional[str] = Field(default=None, min_length=3)
    use_plan_defaults: bool = Field(default=True)


class BnplLockDepositRequest(BaseModel):
    """Request payload for collateral vault deposit."""

    loan_id: str = Field(..., min_length=3)
    user_id: str = Field(..., min_length=3)
    asset_symbol: str = Field(default="BNB", min_length=2)
    deposited_units: int = Field(..., gt=0)
    collateral_value_minor: int = Field(..., gt=0)
    oracle_price_minor: int = Field(..., gt=0)
    vault_address: str = Field(..., min_length=6)
    chain_id: int = Field(default=97, gt=0)
    deposit_tx_hash: str = Field(..., min_length=8)
    proof_page_url: Optional[str] = Field(default=None)


class BnplTopUpRequest(BaseModel):
    """Request payload for top-up collateral action."""

    collateral_id: str = Field(..., min_length=3)
    added_units: int = Field(..., gt=0)
    added_value_minor: int = Field(..., gt=0)
    oracle_price_minor: int = Field(..., gt=0)
    topup_tx_hash: Optional[str] = Field(default=None)


class BnplAutopayRequest(BaseModel):
    """Request payload for autopay toggle."""

    user_id: str = Field(..., min_length=3)
    enabled: bool = Field(...)


class BnplDisputeRequest(BaseModel):
    """Request payload for opening dispute."""

    loan_id: str = Field(..., min_length=3)
    reason: str = Field(..., min_length=3)


class BnplDisputeResolveRequest(BaseModel):
    """Request payload for dispute resolution."""

    loan_id: str = Field(..., min_length=3)
    resolution: str = Field(..., min_length=3)
    restore_active: bool = Field(default=True)
    refund_payment_id: Optional[str] = Field(default=None)
    refund_amount_minor: Optional[int] = Field(default=None, gt=0)


class BnplMissedSimulationRequest(BaseModel):
    """Request payload for missed installment simulation."""

    loan_id: str = Field(..., min_length=3)
    installment_id: str = Field(..., min_length=3)


class BnplPartialRecoveryRequest(BaseModel):
    """Request payload for partial recovery operation."""

    loan_id: str = Field(..., min_length=3)
    installment_id: str = Field(..., min_length=3)
    notes: str = Field(default="Automated partial recovery", min_length=3)
    merchant_transfer_ref: Optional[str] = Field(default=None)


class BnplMerchantSettlementRequest(BaseModel):
    """Request payload for merchant paid-upfront simulation."""

    merchant_id: str = Field(..., min_length=3)
    user_id: str = Field(..., min_length=3)
    loan_id: str = Field(..., min_length=3)
    amount_minor: int = Field(..., gt=0)
    external_ref: Optional[str] = Field(default=None)
    use_razorpay: bool = Field(default=True)


class BnplAutopayMandateRequest(BaseModel):
    """Request payload for autopay mandate simulation via Razorpay."""

    user_id: str = Field(..., min_length=3)
    loan_id: str = Field(..., min_length=3)
    amount_minor: int = Field(..., gt=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    customer_name: Optional[str] = Field(default=None)
    customer_email: Optional[str] = Field(default=None)
    customer_contact: Optional[str] = Field(default=None)


class BnplDisputeRefundRequest(BaseModel):
    """Request payload for processing dispute refund via Razorpay."""

    loan_id: str = Field(..., min_length=3)
    payment_id: str = Field(..., min_length=3)
    amount_minor: Optional[int] = Field(default=None, gt=0)
    notes: str = Field(default="Dispute refund")


class BnplAdminPauseRequest(BaseModel):
    """Request payload for emergency pause state updates."""

    paused: bool = Field(...)
    reason: str = Field(default="")


def _require_role(role: Optional[str], allowed: set[str]) -> str:
    """Validate caller role for admin-like actions."""
    normalized = (role or "").strip().upper()
    if normalized not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient role. Required one of: {0}".format(", ".join(sorted(allowed))),
        )
    return normalized


def build_bnpl_router(service: BnplFeatureService) -> APIRouter:
    """Build BNPL router for 25-feature workflow."""
    router = APIRouter(prefix="/bnpl", tags=["bnpl"])

    @router.get("/features/status", summary="Feature coverage status")
    def feature_status() -> Dict[str, Any]:
        """Return implemented feature map for quick hackathon checks."""
        return {
            "implemented": [
                "1_vault_deposit",
                "2_plan_schedule",
                "3_safety_meter",
                "4_early_warnings",
                "5_topup",
                "6_grace_late_fee",
                "7_partial_recovery",
                "8_autopay_toggle",
                "9_dispute_workflow",
                "10_missed_payment_simulator",
                "11_merchant_paid_upfront_simulation",
                "12_merchant_risk_view",
                "13_merchant_dashboard",
                "14_eligibility_check",
                "15_chargeback_style_protection",
                "16_two_thresholds",
                "17_oracle_guard",
                "18_role_based_admin",
                "19_emergency_pause",
                "20_audit_logs",
                "21_risk_score",
                "22_dynamic_deposit_recommendation",
                "23_default_prediction_nudges",
                "24_explainability_panel",
                "25_public_proof_page",
                "emi_plan_catalog",
            ],
            "razorpay_enabled_features": [
                "8_autopay_mandate_simulation",
                "9_dispute_refund_workflow",
                "11_merchant_paid_upfront_settlement",
                "15_chargeback_style_recovery_settlement",
            ],
        }

    @router.get("/emi/plans", summary="List EMI plans")
    def emi_plans(
        currency: Optional[str] = Query(default=None, min_length=3, max_length=3),
        include_disabled: bool = Query(default=False),
    ) -> Dict[str, Any]:
        """List all configured EMI plans with optional currency filter."""
        try:
            return service.list_emi_plans(currency=currency, include_disabled=include_disabled)
        except Exception as exc:
            logger.exception("EMI plans endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/emi/plans/{plan_id}", summary="Get EMI plan by id")
    def emi_plan_by_id(plan_id: str) -> Dict[str, Any]:
        """Fetch one EMI plan from catalog."""
        try:
            return service.get_emi_plan_details(plan_id=plan_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        except Exception as exc:
            logger.exception("EMI plan details endpoint failed plan_id=%s", plan_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/payments/razorpay/features", summary="Razorpay-powered feature map")
    def razorpay_feature_map() -> Dict[str, Any]:
        """Return all BNPL features that use Razorpay integration."""
        return {
            "provider": "razorpay",
            "features": [
                {
                    "feature_id": 8,
                    "feature_name": "Auto-Pay Toggle + Mandate",
                    "endpoint": "POST /bnpl/users/autopay/mandate",
                    "description": "Creates a payment-link mandate simulation for autopay onboarding.",
                },
                {
                    "feature_id": 9,
                    "feature_name": "Dispute / Refund Workflow",
                    "endpoint": "POST /bnpl/disputes/refund",
                    "description": "Issues partial/full refund for a Razorpay payment tied to a dispute.",
                },
                {
                    "feature_id": 11,
                    "feature_name": "Merchant Paid Upfront",
                    "endpoint": "POST /bnpl/merchant/settlements",
                    "description": "Creates Razorpay order for merchant settlement with simulation fallback.",
                },
                {
                    "feature_id": 15,
                    "feature_name": "Chargeback-Style Protection",
                    "endpoint": "POST /bnpl/recovery/partial",
                    "description": "Partial recovery triggers settlement records, optionally via Razorpay.",
                },
            ],
        }

    @router.get("/payments/razorpay/status", summary="Razorpay integration status")
    def razorpay_status() -> Dict[str, Any]:
        """Return runtime Razorpay availability for payment-dependent endpoints."""
        try:
            return service.get_razorpay_status()
        except Exception as exc:
            logger.exception("Razorpay status endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/loans", summary="List loans for a user (from Firestore when Firebase enabled)")
    def list_loans(user_id: str = Query(..., min_length=3), limit: int = Query(default=50, ge=1, le=200)) -> Dict[str, Any]:
        """Return loans for the given user_id. Data is read from Firestore (bnpl_loans) when Firebase is enabled."""
        try:
            return service.get_loans_by_user(user_id=user_id, limit=limit)
        except Exception as exc:
            logger.exception("List loans endpoint failed user_id=%s", user_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/plans", summary="Create BNPL plan + schedule")
    def create_plan(payload: BnplCreatePlanRequest) -> Dict[str, Any]:
        """Create plan and schedule rows (stored in Firestore bnpl_loans when Firebase enabled)."""
        try:
            return service.create_bnpl_plan(**payload.dict())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Create plan endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/collateral/lock", summary="Lock refundable security deposit")
    def lock_deposit(payload: BnplLockDepositRequest) -> Dict[str, Any]:
        """Lock collateral in vault against BNPL loan."""
        try:
            return service.lock_security_deposit(**payload.dict())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Lock deposit endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/collateral/topup", summary="Top-up collateral")
    def topup(payload: BnplTopUpRequest) -> Dict[str, Any]:
        """Top-up collateral balance and recompute safety."""
        try:
            return service.top_up_collateral(**payload.dict())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Top-up endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/safety-meter/{loan_id}", summary="Get safety meter")
    def safety_meter(loan_id: str) -> Dict[str, Any]:
        """Return health factor UI state."""
        try:
            return service.get_safety_meter(loan_id=loan_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        except Exception as exc:
            logger.exception("Safety meter endpoint failed loan_id=%s", loan_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/alerts/scan", summary="Run early warning scan")
    def scan_alerts(threshold_ratio: float = Query(default=1.15, gt=0.0)) -> Dict[str, Any]:
        """Scan active loans and create warnings near thresholds."""
        try:
            return service.run_early_warning_scan(threshold_ratio=threshold_ratio)
        except Exception as exc:
            logger.exception("Alert scan endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/eligibility/{user_id}", summary="Instant eligibility check")
    def eligibility(user_id: str) -> Dict[str, Any]:
        """Compute BNPL eligibility from collateral/LTV."""
        try:
            return service.compute_eligibility(user_id=user_id)
        except Exception as exc:
            logger.exception("Eligibility endpoint failed user_id=%s", user_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.patch("/users/autopay", summary="Auto-pay toggle")
    def autopay(payload: BnplAutopayRequest) -> Dict[str, Any]:
        """Enable/disable autopay preference."""
        try:
            return service.set_autopay(user_id=payload.user_id, enabled=payload.enabled)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Autopay endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/users/autopay/mandate", summary="Create autopay mandate simulation")
    def autopay_mandate(payload: BnplAutopayMandateRequest) -> Dict[str, Any]:
        """Create Razorpay payment-link mandate simulation for autopay."""
        try:
            return service.create_autopay_mandate(
                user_id=payload.user_id,
                loan_id=payload.loan_id,
                amount_minor=payload.amount_minor,
                currency=payload.currency,
                customer_name=payload.customer_name,
                customer_email=payload.customer_email,
                customer_contact=payload.customer_contact,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Autopay mandate endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/disputes/open", summary="Open dispute and pause penalties")
    def dispute_open(payload: BnplDisputeRequest, x_actor_id: Optional[str] = Header(default="user")) -> Dict[str, Any]:
        """Open dispute workflow."""
        try:
            return service.open_dispute(loan_id=payload.loan_id, reason=payload.reason, actor=x_actor_id or "user")
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Dispute open endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/disputes/resolve", summary="Resolve dispute")
    def dispute_resolve(payload: BnplDisputeResolveRequest, x_actor_id: Optional[str] = Header(default="user")) -> Dict[str, Any]:
        """Resolve dispute workflow."""
        try:
            return service.resolve_dispute(
                loan_id=payload.loan_id,
                resolution=payload.resolution,
                actor=x_actor_id or "user",
                restore_active=payload.restore_active,
                refund_payment_id=payload.refund_payment_id,
                refund_amount_minor=payload.refund_amount_minor,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Dispute resolve endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/disputes/refund", summary="Process dispute refund via Razorpay")
    def dispute_refund(payload: BnplDisputeRefundRequest) -> Dict[str, Any]:
        """Process refund transaction for dispute workflow."""
        try:
            return service.process_dispute_refund(
                loan_id=payload.loan_id,
                payment_id=payload.payment_id,
                amount_minor=payload.amount_minor,
                notes=payload.notes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Dispute refund endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/payments/late-fee/preview", summary="Grace window + late fee preview")
    def late_fee_preview(payload: BnplMissedSimulationRequest) -> Dict[str, Any]:
        """Preview late fee transparency view."""
        try:
            return service.preview_late_fee(loan_id=payload.loan_id, installment_id=payload.installment_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Late fee preview endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/simulations/missed-payment", summary="Missed payment simulator")
    def missed_simulator(payload: BnplMissedSimulationRequest) -> Dict[str, Any]:
        """Run what-if simulator for missed installment."""
        try:
            return service.simulate_missed_payment(loan_id=payload.loan_id, installment_id=payload.installment_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Missed payment simulator endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/recovery/partial", summary="Execute partial recovery")
    def partial_recovery(
        payload: BnplPartialRecoveryRequest,
        x_admin_role: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        """Recover only needed collateral after default event."""
        role = _require_role(x_admin_role, {"LIQUIDATOR", "ADMIN"})
        try:
            return service.execute_partial_recovery(
                loan_id=payload.loan_id,
                installment_id=payload.installment_id,
                initiated_by_role=role,
                notes=payload.notes,
                merchant_transfer_ref=payload.merchant_transfer_ref,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Partial recovery endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/merchant/settlements", summary="Merchant paid upfront simulation")
    def merchant_settlement(payload: BnplMerchantSettlementRequest) -> Dict[str, Any]:
        """Record merchant settlement style event."""
        try:
            return service.simulate_merchant_settlement(
                merchant_id=payload.merchant_id,
                user_id=payload.user_id,
                loan_id=payload.loan_id,
                amount_minor=payload.amount_minor,
                external_ref=payload.external_ref,
                use_razorpay=payload.use_razorpay,
            )
        except Exception as exc:
            logger.exception("Merchant settlement endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/merchant/{merchant_id}/dashboard", summary="Merchant dashboard")
    def merchant_dashboard(merchant_id: str) -> Dict[str, Any]:
        """Return merchant orders and loan status."""
        try:
            return service.merchant_dashboard(merchant_id=merchant_id)
        except Exception as exc:
            logger.exception("Merchant dashboard endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/merchant/risk-view/{loan_id}", summary="Merchant collateral proof + risk view")
    def merchant_risk_view(loan_id: str) -> Dict[str, Any]:
        """Expose proof of collateral for checkout trust."""
        try:
            return service.merchant_risk_view(loan_id=loan_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        except Exception as exc:
            logger.exception("Merchant risk view endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/risk/score/{loan_id}", summary="Compute rule-based risk score")
    def risk_score(loan_id: str) -> Dict[str, Any]:
        """Compute and persist risk score snapshot."""
        try:
            return service.compute_risk_score(loan_id=loan_id)
        except Exception as exc:
            logger.exception("Risk score endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/risk/recommend-deposit/{loan_id}", summary="Dynamic deposit recommendation")
    def risk_recommend_deposit(loan_id: str, use_ml: bool = Query(default=False)) -> Dict[str, Any]:
        """Recommend extra deposit to keep position safe."""
        try:
            return service.recommend_dynamic_deposit(loan_id=loan_id, use_ml=use_ml)
        except Exception as exc:
            logger.exception("Risk recommend deposit endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/risk/default-nudge", summary="Predict default and create preventive nudge")
    def default_nudge(payload: BnplMissedSimulationRequest) -> Dict[str, Any]:
        """Run default prediction and generate nudge actions."""
        try:
            return service.predict_default_and_nudge(loan_id=payload.loan_id, installment_id=payload.installment_id)
        except Exception as exc:
            logger.exception("Default nudge endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/explainability/{loan_id}", summary="Explainability panel")
    def explainability(loan_id: str) -> Dict[str, Any]:
        """Return top reasons for decision outputs."""
        try:
            return service.explainability_panel(loan_id=loan_id)
        except Exception as exc:
            logger.exception("Explainability endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/proof/{loan_id}", summary="Public proof page payload")
    def proof(loan_id: str) -> Dict[str, Any]:
        """Return transparent timeline + proof material."""
        try:
            return service.public_proof_page(loan_id=loan_id)
        except Exception as exc:
            logger.exception("Proof endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/oracle/guard", summary="Oracle guard status")
    def oracle_guard(max_age_sec: int = Query(default=300, ge=1)) -> Dict[str, Any]:
        """Validate price feed freshness."""
        try:
            return service.validate_oracle_guard(max_age_sec=max_age_sec)
        except Exception as exc:
            logger.exception("Oracle guard endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/audit/events", summary="Audit-friendly event logs")
    def audit_events(limit: int = Query(default=100, ge=1, le=500)) -> Dict[str, Any]:
        """Return event trail for compliance/debugging."""
        try:
            return service.get_audit_events(limit=limit)
        except Exception as exc:
            logger.exception("Audit events endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.patch("/admin/pause", summary="Emergency pause update")
    def admin_pause(
        payload: BnplAdminPauseRequest,
        x_admin_role: Optional[str] = Header(default=None),
        x_actor_id: Optional[str] = Header(default="admin"),
    ) -> Dict[str, Any]:
        """Enable/disable emergency pause control."""
        role = _require_role(x_admin_role, {"ADMIN", "PAUSER"})
        try:
            return service.set_pause_state(
                paused=payload.paused,
                reason=payload.reason,
                role=role,
                actor=x_actor_id or "admin",
            )
        except Exception as exc:
            logger.exception("Admin pause endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    return router
