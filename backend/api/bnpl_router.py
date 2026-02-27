"""BNPL feature router exposing borrower, merchant, protocol, and trust APIs."""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
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
    category: str = Field(default="PAYMENT_ISSUE", min_length=3)


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


class KycStatusUpdateRequest(BaseModel):
    """Request payload for KYC status updates."""

    user_id: str = Field(..., min_length=3)
    status: str = Field(..., min_length=3)
    reject_reason: Optional[str] = Field(default=None)


class AmlScreeningRequest(BaseModel):
    """Request payload for AML/sanctions screening."""

    user_id: str = Field(..., min_length=3)
    provider: str = Field(default="mock_sanctions_provider", min_length=3)
    risk_flags: list[str] = Field(default_factory=list)


class WalletVerificationChallengeRequest(BaseModel):
    """Request payload for wallet verification challenge."""

    user_id: str = Field(..., min_length=3)
    wallet_id: str = Field(..., min_length=6)
    chain: str = Field(default="bsc", min_length=3)


class WalletVerificationConfirmRequest(BaseModel):
    """Request payload for wallet signature verification."""

    user_id: str = Field(..., min_length=3)
    wallet_id: str = Field(..., min_length=6)
    signature: str = Field(..., min_length=20)
    chain: str = Field(default="bsc", min_length=3)


class CollateralPolicyUpdateRequest(BaseModel):
    """Request payload for collateral asset policy updates."""

    chain: str = Field(default="bsc", min_length=2)
    ltv_bps: int = Field(..., gt=0, le=10000)
    liquidation_threshold_bps: int = Field(..., gt=0, le=10000)
    liquidation_penalty_bps: int = Field(default=700, ge=0, le=10000)
    min_deposit_minor: int = Field(default=1, ge=0)
    decimals: int = Field(default=18, ge=0, le=30)
    enabled: bool = Field(default=True)


class DisputePauseRuleRequest(BaseModel):
    """Request payload for dispute pause policy updates."""

    pause_penalties: bool = Field(default=True)
    pause_liquidation: bool = Field(default=False)
    pause_hours: int = Field(default=168, gt=0)


class DisputeEvidenceRequest(BaseModel):
    """Request payload for dispute evidence upload metadata."""

    file_name: str = Field(..., min_length=3)
    file_url: str = Field(..., min_length=5)
    notes: Optional[str] = Field(default=None)


class LoanStateTransitionRequest(BaseModel):
    """Request payload for explicit loan state transition."""

    status: str = Field(..., min_length=3)
    reason: str = Field(default="")


class LoanCloseRequest(BaseModel):
    """Request payload for closing loans."""

    force: bool = Field(default=False)


class LoanCancelRequest(BaseModel):
    """Request payload for pre-settlement cancellation."""

    reason: str = Field(..., min_length=3)


class LoanRefundAdjustmentRequest(BaseModel):
    """Request payload for refund adjustment flow."""

    refund_amount_minor: int = Field(..., gt=0)
    reason: str = Field(..., min_length=3)


class InstallmentPaymentRequest(BaseModel):
    """Request payload for installment payment API."""

    loan_id: str = Field(..., min_length=3)
    installment_id: str = Field(..., min_length=3)
    amount_minor: int = Field(..., gt=0)
    payment_ref: Optional[str] = Field(default=None)
    success: bool = Field(default=True)
    failure_reason: Optional[str] = Field(default=None)


class PayNowRequest(BaseModel):
    """Request payload for manual pay-now flow."""

    loan_id: str = Field(..., min_length=3)
    amount_minor: int = Field(..., gt=0)
    payment_ref: Optional[str] = Field(default=None)


class PaymentRetryRequest(BaseModel):
    """Request payload for payment retry flow."""

    loan_id: str = Field(..., min_length=3)
    installment_id: str = Field(..., min_length=3)


class RazorpayWebhookRequest(BaseModel):
    """Request payload for Razorpay webhook reconciliation."""

    event_type: str = Field(..., min_length=3)
    payload: Dict[str, Any] = Field(default_factory=dict)
    raw_body: str = Field(..., min_length=2)


class LateFeeWaiveRequest(BaseModel):
    """Request payload for late fee waiver."""

    loan_id: str = Field(..., min_length=3)
    installment_id: str = Field(..., min_length=3)
    reason: str = Field(..., min_length=3)


class ReminderScheduleRequest(BaseModel):
    """Request payload for reminder scheduling."""

    loan_id: str = Field(..., min_length=3)


class NotificationSendRequest(BaseModel):
    """Request payload for notification service."""

    user_id: str = Field(..., min_length=3)
    channels: list[str] = Field(default_factory=list)
    template: str = Field(..., min_length=3)
    context: Dict[str, Any] = Field(default_factory=dict)


class FullLiquidationRequest(BaseModel):
    """Request payload for full liquidation/bad debt flow."""

    loan_id: str = Field(..., min_length=3)
    notes: str = Field(default="Escalated full liquidation", min_length=3)


class FraudCheckRequest(BaseModel):
    """Request payload for fraud/abuse controls."""

    user_id: str = Field(..., min_length=3)
    wallet_id: Optional[str] = Field(default=None)
    device_id: Optional[str] = Field(default=None)


class JobEnqueueRequest(BaseModel):
    """Request payload for async job queue."""

    job_type: str = Field(..., min_length=3)
    payload: Dict[str, Any] = Field(default_factory=dict)


class MerchantOnboardRequest(BaseModel):
    """Request payload for merchant onboarding."""

    merchant_name: str = Field(..., min_length=3)


class MerchantAuthRequest(BaseModel):
    """Request payload for merchant API key validation."""

    merchant_id: str = Field(..., min_length=3)
    api_key: str = Field(..., min_length=10)


class MerchantOrderStatusRequest(BaseModel):
    """Request payload for merchant order/fulfillment sync."""

    status: str = Field(..., min_length=3)
    notes: Optional[str] = Field(default=None)


def _require_role(role: Optional[str], allowed: set[str]) -> str:
    """Validate caller role for admin-like actions."""
    normalized = (role or "").strip().upper()
    if normalized not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient role. Required one of: {0}".format(", ".join(sorted(allowed))),
        )
    return normalized


def _enforce_rate_limit(
    service: BnplFeatureService,
    request: Request,
    actor_id: Optional[str],
    action_key: str,
    limit: int = 25,
    window_sec: int = 60,
) -> None:
    """Apply per-actor/per-IP request throttling for sensitive endpoints."""
    identity = (actor_id or request.client.host or "anonymous").strip().lower()
    rate_key = "{0}:{1}".format(action_key, identity)
    state = service.check_rate_limit(key=rate_key, limit=limit, window_sec=window_sec)
    if not state.get("allowed", False):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. retry_after_sec={0}".format(state.get("retry_after_sec")),
        )


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
                "compliance_kyc_aml",
                "wallet_signature_verification",
                "collateral_asset_policy_management",
                "explicit_loan_state_machine",
                "loan_closure_cancellation_refund_adjustment",
                "installment_payment_retry_reconciliation",
                "grace_late_fee_engine",
                "notification_and_reminder_scheduler",
                "oracle_fallback_and_risk_monitor",
                "full_liquidation_and_bad_debt",
                "merchant_onboarding_settlement_lifecycle",
                "fraud_controls",
                "event_schema_ledger_kpi",
                "idempotency_rate_limit_job_queue",
                "user_facing_loan_history_apis",
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

    @router.post("/plans", summary="Create BNPL plan + schedule")
    def create_plan(
        request: Request,
        payload: BnplCreatePlanRequest,
        x_actor_id: Optional[str] = Header(default="user"),
        x_idempotency_key: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        """Create plan and schedule rows."""
        _enforce_rate_limit(service, request, x_actor_id, "create_plan", limit=15, window_sec=60)
        try:
            payload_dict = payload.dict()
            payload_dict["idempotency_key"] = x_idempotency_key
            return service.create_bnpl_plan(**payload_dict)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Create plan endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/collateral/lock", summary="Lock refundable security deposit")
    def lock_deposit(
        request: Request,
        payload: BnplLockDepositRequest,
        x_actor_id: Optional[str] = Header(default="user"),
        x_idempotency_key: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        """Lock collateral in vault against BNPL loan."""
        _enforce_rate_limit(service, request, x_actor_id, "lock_deposit", limit=20, window_sec=60)
        try:
            payload_dict = payload.dict()
            payload_dict["idempotency_key"] = x_idempotency_key
            return service.lock_security_deposit(**payload_dict)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Lock deposit endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/collateral/topup", summary="Top-up collateral")
    def topup(
        request: Request,
        payload: BnplTopUpRequest,
        x_actor_id: Optional[str] = Header(default="user"),
        x_idempotency_key: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        """Top-up collateral balance and recompute safety."""
        _enforce_rate_limit(service, request, x_actor_id, "collateral_topup", limit=20, window_sec=60)
        try:
            payload_dict = payload.dict()
            payload_dict["idempotency_key"] = x_idempotency_key
            return service.top_up_collateral(**payload_dict)
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
            return service.open_dispute(
                loan_id=payload.loan_id,
                reason=payload.reason,
                actor=x_actor_id or "user",
                category=payload.category,
            )
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
    def merchant_settlement(
        request: Request,
        payload: BnplMerchantSettlementRequest,
        x_actor_id: Optional[str] = Header(default="merchant"),
        x_idempotency_key: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        """Record merchant settlement style event."""
        _enforce_rate_limit(service, request, x_actor_id, "merchant_settlement", limit=30, window_sec=60)
        try:
            return service.simulate_merchant_settlement(
                merchant_id=payload.merchant_id,
                user_id=payload.user_id,
                loan_id=payload.loan_id,
                amount_minor=payload.amount_minor,
                external_ref=payload.external_ref,
                use_razorpay=payload.use_razorpay,
                idempotency_key=x_idempotency_key,
            )
        except Exception as exc:
            logger.exception("Merchant settlement endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/merchant/{merchant_id}/dashboard", summary="Merchant dashboard")
    def merchant_dashboard(
        merchant_id: str,
        x_admin_role: Optional[str] = Header(default=None),
        x_merchant_id: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        """Return merchant orders and loan status."""
        caller_role = _require_role(x_admin_role, {"ADMIN", "MERCHANT"})
        if caller_role == "MERCHANT" and (x_merchant_id or "").strip() != merchant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Merchant can only access own dashboard.")
        try:
            return service.merchant_dashboard(merchant_id=merchant_id)
        except Exception as exc:
            logger.exception("Merchant dashboard endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/merchant/risk-view/{loan_id}", summary="Merchant collateral proof + risk view")
    def merchant_risk_view(
        loan_id: str,
        x_admin_role: Optional[str] = Header(default=None),
        x_merchant_id: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        """Expose proof of collateral for checkout trust."""
        caller_role = _require_role(x_admin_role, {"ADMIN", "MERCHANT"})
        try:
            response = service.merchant_risk_view(loan_id=loan_id)
            if caller_role == "MERCHANT" and (x_merchant_id or "").strip() != str(response.get("merchant_id")):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Merchant cannot access unrelated loan.")
            return response
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

    @router.post("/compliance/kyc", summary="Update KYC status")
    def update_kyc(
        payload: KycStatusUpdateRequest,
        x_admin_role: Optional[str] = Header(default=None),
        x_actor_id: Optional[str] = Header(default="support"),
    ) -> Dict[str, Any]:
        """Update KYC verification lifecycle for user."""
        _require_role(x_admin_role, {"ADMIN", "SUPPORT", "REVIEWER"})
        try:
            return service.upsert_kyc_status(
                user_id=payload.user_id,
                status=payload.status,
                actor=x_actor_id or "support",
                reject_reason=payload.reject_reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("KYC update endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/compliance/kyc/{user_id}", summary="Get KYC status")
    def get_kyc(user_id: str) -> Dict[str, Any]:
        """Get KYC status for one user."""
        try:
            return service.get_kyc_status(user_id=user_id)
        except Exception as exc:
            logger.exception("KYC read endpoint failed user_id=%s", user_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/compliance/aml/screen", summary="Run AML/sanctions screening")
    def screen_aml(
        payload: AmlScreeningRequest,
        x_admin_role: Optional[str] = Header(default=None),
        x_actor_id: Optional[str] = Header(default="support"),
    ) -> Dict[str, Any]:
        """Run AML screening and store outcome."""
        _require_role(x_admin_role, {"ADMIN", "SUPPORT", "REVIEWER"})
        try:
            return service.run_aml_screening(
                user_id=payload.user_id,
                actor=x_actor_id or "support",
                provider=payload.provider,
                risk_flags=payload.risk_flags,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("AML screening endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/compliance/aml/{user_id}", summary="Get AML status")
    def get_aml(user_id: str) -> Dict[str, Any]:
        """Get AML status for one user."""
        try:
            return service.get_aml_status(user_id=user_id)
        except Exception as exc:
            logger.exception("AML read endpoint failed user_id=%s", user_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/wallets/verify/challenge", summary="Create wallet verification challenge")
    def wallet_verify_challenge(payload: WalletVerificationChallengeRequest) -> Dict[str, Any]:
        """Generate sign-message challenge for wallet ownership verification."""
        try:
            return service.create_wallet_verification_challenge(
                user_id=payload.user_id,
                wallet_id=payload.wallet_id,
                chain=payload.chain,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Wallet verification challenge endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/wallets/verify/confirm", summary="Verify wallet signature")
    def wallet_verify_confirm(payload: WalletVerificationConfirmRequest) -> Dict[str, Any]:
        """Verify signature and mark wallet as verified."""
        try:
            return service.verify_wallet_signature(
                user_id=payload.user_id,
                wallet_id=payload.wallet_id,
                signature=payload.signature,
                chain=payload.chain,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Wallet verification confirm endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/wallets/verify/{user_id}", summary="Get verified wallets")
    def wallet_verify_status(user_id: str) -> Dict[str, Any]:
        """Get wallet verification status for one user."""
        try:
            return service.get_verified_wallets(user_id=user_id)
        except Exception as exc:
            logger.exception("Wallet verification status endpoint failed user_id=%s", user_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/collateral/policies", summary="List collateral asset policies")
    def list_collateral_policies() -> Dict[str, Any]:
        """List supported collateral asset policies."""
        try:
            return service.list_collateral_asset_policies()
        except Exception as exc:
            logger.exception("Collateral policies endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.put("/collateral/policies/{asset_symbol}", summary="Update collateral asset policy")
    def update_collateral_policy(
        asset_symbol: str,
        payload: CollateralPolicyUpdateRequest,
        x_admin_role: Optional[str] = Header(default=None),
        x_actor_id: Optional[str] = Header(default="admin"),
    ) -> Dict[str, Any]:
        """Update collateral policy by asset symbol."""
        _require_role(x_admin_role, {"ADMIN"})
        try:
            return service.update_collateral_asset_policy(
                asset_symbol=asset_symbol,
                policy=payload.dict(),
                actor=x_actor_id or "admin",
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Collateral policy update endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/disputes/pause-rules", summary="Get dispute pause rules")
    def get_dispute_pause_rules() -> Dict[str, Any]:
        """Get category-based dispute pause policy."""
        try:
            return service.get_dispute_pause_rules()
        except Exception as exc:
            logger.exception("Dispute pause rules endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.put("/disputes/pause-rules/{category}", summary="Update dispute pause rule")
    def update_dispute_pause_rules(
        category: str,
        payload: DisputePauseRuleRequest,
        x_admin_role: Optional[str] = Header(default=None),
        x_actor_id: Optional[str] = Header(default="admin"),
    ) -> Dict[str, Any]:
        """Update pause/liquidation behavior by dispute category."""
        _require_role(x_admin_role, {"ADMIN"})
        try:
            return service.update_dispute_pause_rule(
                category=category,
                pause_penalties=payload.pause_penalties,
                pause_liquidation=payload.pause_liquidation,
                pause_hours=payload.pause_hours,
                actor=x_actor_id or "admin",
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Dispute pause-rule update endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/disputes/{dispute_id}/evidence", summary="Attach dispute evidence")
    def add_dispute_evidence(
        dispute_id: str,
        payload: DisputeEvidenceRequest,
        x_actor_id: Optional[str] = Header(default="user"),
    ) -> Dict[str, Any]:
        """Attach dispute evidence metadata."""
        try:
            return service.add_dispute_evidence(
                dispute_id=dispute_id,
                actor=x_actor_id or "user",
                file_name=payload.file_name,
                file_url=payload.file_url,
                notes=payload.notes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        except Exception as exc:
            logger.exception("Dispute evidence endpoint failed dispute_id=%s", dispute_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/disputes/loan/{loan_id}", summary="List disputes for loan")
    def disputes_by_loan(loan_id: str) -> Dict[str, Any]:
        """List dispute history for one loan."""
        try:
            return service.get_disputes_by_loan(loan_id=loan_id)
        except Exception as exc:
            logger.exception("Disputes by loan endpoint failed loan_id=%s", loan_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/loans/{loan_id}/state", summary="Transition loan state")
    def transition_loan(
        loan_id: str,
        payload: LoanStateTransitionRequest,
        x_admin_role: Optional[str] = Header(default=None),
        x_actor_id: Optional[str] = Header(default="support"),
    ) -> Dict[str, Any]:
        """Transition loan through explicit state machine."""
        _require_role(x_admin_role, {"ADMIN", "SUPPORT", "REVIEWER"})
        try:
            return service.transition_loan_state(
                loan_id=loan_id,
                new_status=payload.status,
                actor=x_actor_id or "support",
                reason=payload.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Loan state transition endpoint failed loan_id=%s", loan_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/loans/{loan_id}/close", summary="Close loan")
    def close_loan(
        loan_id: str,
        payload: LoanCloseRequest,
        x_admin_role: Optional[str] = Header(default=None),
        x_actor_id: Optional[str] = Header(default="support"),
    ) -> Dict[str, Any]:
        """Close loan after repayment/recovery reconciliation."""
        _require_role(x_admin_role, {"ADMIN", "SUPPORT", "REVIEWER"})
        try:
            return service.close_loan(loan_id=loan_id, actor=x_actor_id or "support", force=payload.force)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Close loan endpoint failed loan_id=%s", loan_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/loans/{loan_id}/collateral/release", summary="Release unlocked collateral")
    def release_collateral(
        loan_id: str,
        x_actor_id: Optional[str] = Header(default="system"),
    ) -> Dict[str, Any]:
        """Release available collateral for closed/cancelled/defaulted loan."""
        try:
            return service.release_collateral(loan_id=loan_id, actor=x_actor_id or "system")
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Collateral release endpoint failed loan_id=%s", loan_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/loans/{loan_id}/cancel", summary="Cancel pre-settlement order")
    def cancel_loan(
        loan_id: str,
        payload: LoanCancelRequest,
        x_actor_id: Optional[str] = Header(default="user"),
    ) -> Dict[str, Any]:
        """Cancel order before merchant settlement finalization."""
        try:
            return service.cancel_pre_settlement_order(
                loan_id=loan_id,
                actor=x_actor_id or "user",
                reason=payload.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Cancel loan endpoint failed loan_id=%s", loan_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/loans/{loan_id}/refund-adjust", summary="Apply refund adjustment")
    def refund_adjust(
        loan_id: str,
        payload: LoanRefundAdjustmentRequest,
        x_actor_id: Optional[str] = Header(default="support"),
    ) -> Dict[str, Any]:
        """Apply full/partial refund and recompute loan balances."""
        try:
            return service.apply_refund_adjustment(
                loan_id=loan_id,
                actor=x_actor_id or "support",
                refund_amount_minor=payload.refund_amount_minor,
                reason=payload.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Refund adjust endpoint failed loan_id=%s", loan_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/payments/installment", summary="Pay installment")
    def pay_installment(
        request: Request,
        payload: InstallmentPaymentRequest,
        x_actor_id: Optional[str] = Header(default="user"),
        x_idempotency_key: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        """Execute installment payment attempt."""
        _enforce_rate_limit(service, request, x_actor_id, "pay_installment", limit=20, window_sec=60)
        try:
            return service.pay_installment(
                loan_id=payload.loan_id,
                installment_id=payload.installment_id,
                amount_minor=payload.amount_minor,
                actor=x_actor_id or "user",
                payment_ref=payload.payment_ref,
                success=payload.success,
                failure_reason=payload.failure_reason,
                idempotency_key=x_idempotency_key,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Installment payment endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/payments/pay-now", summary="Manual pay-now")
    def pay_now(
        request: Request,
        payload: PayNowRequest,
        x_actor_id: Optional[str] = Header(default="user"),
        x_idempotency_key: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        """Apply one payment to current/overdue dues."""
        _enforce_rate_limit(service, request, x_actor_id, "pay_now", limit=20, window_sec=60)
        try:
            return service.pay_now(
                loan_id=payload.loan_id,
                amount_minor=payload.amount_minor,
                actor=x_actor_id or "user",
                payment_ref=payload.payment_ref,
                idempotency_key=x_idempotency_key,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Pay-now endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/payments/retry", summary="Retry failed payment")
    def retry_payment(payload: PaymentRetryRequest, x_actor_id: Optional[str] = Header(default="system")) -> Dict[str, Any]:
        """Retry a failed installment payment attempt."""
        try:
            return service.retry_failed_payment(
                loan_id=payload.loan_id,
                installment_id=payload.installment_id,
                actor=x_actor_id or "system",
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Payment retry endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/payments/webhooks/razorpay", summary="Razorpay webhook reconciliation")
    def razorpay_webhook(
        payload: RazorpayWebhookRequest,
        x_razorpay_signature: str = Header(...),
    ) -> Dict[str, Any]:
        """Process Razorpay payment/settlement webhook events."""
        try:
            return service.process_razorpay_webhook(
                event_type=payload.event_type,
                payload=payload.payload,
                signature=x_razorpay_signature,
                raw_body=payload.raw_body,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
        except Exception as exc:
            logger.exception("Razorpay webhook endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/payments/late-fee/apply", summary="Apply late fee")
    def apply_late_fee(
        payload: BnplMissedSimulationRequest,
        x_actor_id: Optional[str] = Header(default="system"),
    ) -> Dict[str, Any]:
        """Apply configured late fee rules."""
        try:
            return service.apply_late_fee(
                loan_id=payload.loan_id,
                installment_id=payload.installment_id,
                actor=x_actor_id or "system",
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Late fee apply endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/payments/late-fee/waive", summary="Waive late fee")
    def waive_late_fee(
        payload: LateFeeWaiveRequest,
        x_admin_role: Optional[str] = Header(default=None),
        x_actor_id: Optional[str] = Header(default="support"),
    ) -> Dict[str, Any]:
        """Waive/reverse late fee after review/dispute."""
        _require_role(x_admin_role, {"ADMIN", "SUPPORT", "REVIEWER"})
        try:
            return service.waive_late_fee(
                loan_id=payload.loan_id,
                installment_id=payload.installment_id,
                actor=x_actor_id or "support",
                reason=payload.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Late fee waive endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/recovery/full", summary="Execute full liquidation")
    def full_recovery(
        payload: FullLiquidationRequest,
        x_admin_role: Optional[str] = Header(default=None),
    ) -> Dict[str, Any]:
        """Escalate to full liquidation and capture bad-debt outcome."""
        role = _require_role(x_admin_role, {"ADMIN", "LIQUIDATOR"})
        try:
            return service.execute_full_liquidation(loan_id=payload.loan_id, actor_role=role, notes=payload.notes)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Full recovery endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/reminders/schedule", summary="Schedule reminders")
    def reminders_schedule(payload: ReminderScheduleRequest, x_actor_id: Optional[str] = Header(default="system")) -> Dict[str, Any]:
        """Schedule due/grace reminders for a loan timeline."""
        try:
            return service.schedule_reminders(loan_id=payload.loan_id, actor=x_actor_id or "system")
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Reminder schedule endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/reminders/run-due", summary="Run due reminders")
    def reminders_run_due(x_actor_id: Optional[str] = Header(default="scheduler")) -> Dict[str, Any]:
        """Run scheduler for due reminders and notification dispatch."""
        try:
            return service.run_due_reminders(actor=x_actor_id or "scheduler")
        except Exception as exc:
            logger.exception("Run due reminders endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/notifications/send", summary="Send notification")
    def send_notification(payload: NotificationSendRequest, x_actor_id: Optional[str] = Header(default="system")) -> Dict[str, Any]:
        """Send template notification through channel abstraction."""
        try:
            return service.send_notification(
                user_id=payload.user_id,
                channels=payload.channels,
                template=payload.template,
                context=payload.context,
                actor=x_actor_id or "system",
            )
        except Exception as exc:
            logger.exception("Notification send endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/oracle/resolve", summary="Resolve oracle with fallback")
    def oracle_resolve(
        max_age_sec: int = Query(default=300, ge=1),
        block_on_stale: bool = Query(default=True),
    ) -> Dict[str, Any]:
        """Resolve oracle data using fallback policy and stale guard."""
        try:
            return service.resolve_oracle_price(max_age_sec=max_age_sec, block_on_stale=block_on_stale)
        except Exception as exc:
            logger.exception("Oracle resolve endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/risk/monitor", summary="Run portfolio risk monitor")
    def risk_monitor(threshold_ratio: float = Query(default=1.05, gt=0)) -> Dict[str, Any]:
        """Scan active portfolio for unsafe health factors."""
        try:
            return service.run_portfolio_risk_monitor(threshold_ratio=threshold_ratio)
        except Exception as exc:
            logger.exception("Risk monitor endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/fraud/check", summary="Run fraud checks")
    def fraud_check(payload: FraudCheckRequest) -> Dict[str, Any]:
        """Run fraud/abuse detection heuristics for one user."""
        try:
            return service.run_fraud_checks(
                user_id=payload.user_id,
                wallet_id=payload.wallet_id,
                device_id=payload.device_id,
            )
        except Exception as exc:
            logger.exception("Fraud check endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/ops/dashboard", summary="Internal ops dashboard")
    def ops_dashboard(x_admin_role: Optional[str] = Header(default=None)) -> Dict[str, Any]:
        """Return support/admin back-office snapshot."""
        _require_role(x_admin_role, {"ADMIN", "SUPPORT", "REVIEWER"})
        try:
            return service.ops_dashboard()
        except Exception as exc:
            logger.exception("Ops dashboard endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/ledger", summary="Financial ledger entries")
    def ledger_entries(
        loan_id: Optional[str] = Query(default=None),
        user_id: Optional[str] = Query(default=None),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> Dict[str, Any]:
        """List ledger entries for accounting/audit reproducibility."""
        try:
            return service.list_ledger_entries(loan_id=loan_id, user_id=user_id, limit=limit)
        except Exception as exc:
            logger.exception("Ledger endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/metrics/kpi", summary="KPI metrics")
    def kpi_metrics() -> Dict[str, Any]:
        """Return KPI metrics for product and risk tracking."""
        try:
            return service.compute_kpis()
        except Exception as exc:
            logger.exception("KPI endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/jobs/enqueue", summary="Enqueue async job")
    def enqueue_job(payload: JobEnqueueRequest, x_actor_id: Optional[str] = Header(default="system")) -> Dict[str, Any]:
        """Queue asynchronous scheduler job."""
        try:
            return service.enqueue_job(
                job_type=payload.job_type,
                payload=payload.payload,
                run_at=None,
                actor=x_actor_id or "system",
            )
        except Exception as exc:
            logger.exception("Enqueue job endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/jobs/run-due", summary="Run due jobs")
    def run_due_jobs(x_actor_id: Optional[str] = Header(default="scheduler")) -> Dict[str, Any]:
        """Execute due async jobs."""
        try:
            return service.run_due_jobs(actor=x_actor_id or "scheduler")
        except Exception as exc:
            logger.exception("Run due jobs endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/merchant/onboard", summary="Merchant onboarding")
    def merchant_onboard(
        payload: MerchantOnboardRequest,
        x_admin_role: Optional[str] = Header(default=None),
        x_actor_id: Optional[str] = Header(default="admin"),
    ) -> Dict[str, Any]:
        """Onboard merchant and issue API credential."""
        _require_role(x_admin_role, {"ADMIN"})
        try:
            return service.onboard_merchant(merchant_name=payload.merchant_name, actor=x_actor_id or "admin")
        except Exception as exc:
            logger.exception("Merchant onboard endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/merchant/auth/validate", summary="Validate merchant API key")
    def merchant_validate(payload: MerchantAuthRequest) -> Dict[str, Any]:
        """Validate merchant API key and lifecycle state."""
        try:
            return service.validate_merchant_api_key(merchant_id=payload.merchant_id, api_key=payload.api_key)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        except Exception as exc:
            logger.exception("Merchant auth validate endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.patch("/merchant/orders/{order_id}/status", summary="Update merchant order status")
    def merchant_order_status(
        order_id: str,
        payload: MerchantOrderStatusRequest,
        x_admin_role: Optional[str] = Header(default=None),
        x_actor_id: Optional[str] = Header(default="merchant"),
    ) -> Dict[str, Any]:
        """Sync merchant fulfillment status changes."""
        _require_role(x_admin_role, {"ADMIN", "MERCHANT", "SUPPORT"})
        try:
            return service.update_merchant_order_status(
                order_id=order_id,
                status=payload.status,
                actor=x_actor_id or "merchant",
                notes=payload.notes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Merchant order status endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/merchant/{merchant_id}/settlements", summary="Merchant settlement lifecycle")
    def merchant_settlement_lifecycle(merchant_id: str) -> Dict[str, Any]:
        """Get settlement lifecycle for one merchant."""
        try:
            return service.list_merchant_settlements(merchant_id=merchant_id)
        except Exception as exc:
            logger.exception("Merchant settlement lifecycle endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/merchant/{merchant_id}/risk-score", summary="Merchant risk score")
    def merchant_risk_score(merchant_id: str) -> Dict[str, Any]:
        """Compute merchant-side risk score from disputes/refunds/settlements."""
        try:
            return service.compute_merchant_risk_score(merchant_id=merchant_id)
        except Exception as exc:
            logger.exception("Merchant risk score endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/admin/manual/waive-penalty", summary="Manual waive penalty")
    def manual_waive(
        payload: LateFeeWaiveRequest,
        x_admin_role: Optional[str] = Header(default=None),
        x_actor_id: Optional[str] = Header(default="support"),
    ) -> Dict[str, Any]:
        """Manual override to waive penalty."""
        _require_role(x_admin_role, {"ADMIN", "SUPPORT", "REVIEWER"})
        try:
            return service.manual_waive_penalty(
                loan_id=payload.loan_id,
                installment_id=payload.installment_id,
                actor=x_actor_id or "support",
                reason=payload.reason,
            )
        except Exception as exc:
            logger.exception("Manual waive endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/admin/manual/force-close/{loan_id}", summary="Manual force close")
    def manual_force_close(
        loan_id: str,
        payload: LoanCancelRequest,
        x_admin_role: Optional[str] = Header(default=None),
        x_actor_id: Optional[str] = Header(default="admin"),
    ) -> Dict[str, Any]:
        """Manual override to force-close loan."""
        _require_role(x_admin_role, {"ADMIN", "SUPPORT"})
        try:
            return service.manual_force_close(loan_id=loan_id, actor=x_actor_id or "admin", reason=payload.reason)
        except Exception as exc:
            logger.exception("Manual force close endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/admin/manual/retry-settlement/{order_id}", summary="Manual retry settlement")
    def manual_retry_settlement(
        order_id: str,
        x_admin_role: Optional[str] = Header(default=None),
        x_actor_id: Optional[str] = Header(default="support"),
    ) -> Dict[str, Any]:
        """Manual override to retry settlement."""
        _require_role(x_admin_role, {"ADMIN", "SUPPORT"})
        try:
            return service.manual_retry_settlement(order_id=order_id, actor=x_actor_id or "support")
        except Exception as exc:
            logger.exception("Manual retry settlement endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/users/{user_id}/loans", summary="List user loans")
    def user_loans(user_id: str, include_closed: bool = Query(default=True)) -> Dict[str, Any]:
        """List all loans for one user."""
        try:
            return service.list_user_loans(user_id=user_id, include_closed=include_closed)
        except Exception as exc:
            logger.exception("User loans endpoint failed user_id=%s", user_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/loans/{loan_id}/detail", summary="Loan detail")
    def loan_detail(loan_id: str) -> Dict[str, Any]:
        """Get full single-loan view payload."""
        try:
            return service.get_loan_detail(loan_id=loan_id)
        except Exception as exc:
            logger.exception("Loan detail endpoint failed loan_id=%s", loan_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/loans/{loan_id}/installments", summary="Installment history")
    def loan_installments(loan_id: str) -> Dict[str, Any]:
        """Get installment schedule and payment status history."""
        try:
            return service.get_installment_history(loan_id=loan_id)
        except Exception as exc:
            logger.exception("Loan installments endpoint failed loan_id=%s", loan_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/loans/{loan_id}/payments", summary="Payment history")
    def loan_payments(loan_id: str, limit: int = Query(default=200, ge=1, le=1000)) -> Dict[str, Any]:
        """Get loan payment attempts and timeline."""
        try:
            return service.get_payment_history(loan_id=loan_id, limit=limit)
        except Exception as exc:
            logger.exception("Loan payments endpoint failed loan_id=%s", loan_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    return router
