"""BNPL feature orchestration service covering borrower, merchant, risk, and audit flows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hmac
import hashlib
import json
import logging
from random import random
import secrets
from threading import RLock
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from eth_account.messages import encode_defunct
from web3 import Web3

from common.emi_plan_catalog import EmiPlanCatalog
from core.config import AppSettings
from core.firebase_client_manager import FirebaseClientManager
from ml.default_schema import DefaultPredictionInput
from ml.deposit_schema import DepositRecommendationRequest
from ml.orchestrator import MlPayloadOrchestrator
from models.collaterals import CollateralModel
from models.enums import (
    CollateralStatus,
    DisputeCategory,
    InstallmentStatus,
    KycStatus,
    LiquidationActionType,
    LoanStatus,
    MerchantStatus,
    RiskTier,
    ScreeningStatus,
    SettlementStatus,
    UserRole,
)
from models.installments import InstallmentModel
from models.liquidation_logs import LiquidationLogModel
from models.loans import LoanModel
from models.risk_scores import RiskScoreModel
from models.users import UserModel
from repositories.firestore_user_repository import FirestoreUserRepository


logger = logging.getLogger(__name__)

FilterTuple = Tuple[str, str, Any]

DEFAULT_LOAN_TRANSITIONS: Dict[LoanStatus, set] = {
    LoanStatus.DRAFT: {LoanStatus.PENDING_KYC, LoanStatus.ELIGIBLE, LoanStatus.CANCELLED},
    LoanStatus.PENDING_KYC: {LoanStatus.ELIGIBLE, LoanStatus.CANCELLED},
    LoanStatus.ELIGIBLE: {LoanStatus.ACTIVE, LoanStatus.CANCELLED},
    LoanStatus.ACTIVE: {
        LoanStatus.GRACE,
        LoanStatus.OVERDUE,
        LoanStatus.DELINQUENT,
        LoanStatus.DISPUTE_OPEN,
        LoanStatus.DISPUTED,
        LoanStatus.PARTIALLY_RECOVERED,
        LoanStatus.CLOSED,
        LoanStatus.DEFAULTED,
    },
    LoanStatus.GRACE: {
        LoanStatus.ACTIVE,
        LoanStatus.OVERDUE,
        LoanStatus.DELINQUENT,
        LoanStatus.DISPUTED,
        LoanStatus.PARTIALLY_RECOVERED,
        LoanStatus.CLOSED,
        LoanStatus.DEFAULTED,
    },
    LoanStatus.OVERDUE: {
        LoanStatus.GRACE,
        LoanStatus.DELINQUENT,
        LoanStatus.PARTIALLY_RECOVERED,
        LoanStatus.DEFAULTED,
        LoanStatus.CLOSED,
    },
    LoanStatus.DELINQUENT: {
        LoanStatus.PARTIALLY_RECOVERED,
        LoanStatus.DEFAULTED,
        LoanStatus.CLOSED,
    },
    LoanStatus.DISPUTE_OPEN: {LoanStatus.DISPUTED, LoanStatus.ACTIVE, LoanStatus.CLOSED},
    LoanStatus.DISPUTED: {LoanStatus.ACTIVE, LoanStatus.CLOSED, LoanStatus.DEFAULTED},
    LoanStatus.PARTIALLY_RECOVERED: {LoanStatus.ACTIVE, LoanStatus.DELINQUENT, LoanStatus.DEFAULTED, LoanStatus.CLOSED},
    LoanStatus.DEFAULTED: {LoanStatus.CLOSED},
    LoanStatus.CLOSED: set(),
    LoanStatus.CANCELLED: set(),
}

RISKY_DISPUTE_CATEGORIES = {
    DisputeCategory.FRAUD.value,
    DisputeCategory.DUPLICATE_CHARGE.value,
}


def _now_utc() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def _as_int(value: Any, default: int = 0) -> int:
    """Convert value to int with fallback."""
    try:
        if value is None:
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _as_float(value: Any, default: float = 0.0) -> float:
    """Convert value to float with fallback."""
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


class BnplFeatureService:
    """Implements BNPL product features with Firestore-first and in-memory fallback storage."""

    def __init__(
        self,
        settings: AppSettings,
        protocol_service: Any,
        user_repository: Optional[FirestoreUserRepository],
        firebase_manager: Optional[FirebaseClientManager],
        ml_orchestrator: MlPayloadOrchestrator,
        emi_plan_catalog: Optional[EmiPlanCatalog] = None,
        razorpay_service: Optional[Any] = None,
    ) -> None:
        """Initialize feature service dependencies."""
        self._settings = settings
        self._protocol_service = protocol_service
        self._user_repository = user_repository
        self._firebase_manager = firebase_manager
        self._ml_orchestrator = ml_orchestrator
        self._emi_plan_catalog = emi_plan_catalog or EmiPlanCatalog(
            path=settings.emi_plans_path,
            default_plan_id=settings.emi_default_plan_id,
        )
        self._razorpay_service = razorpay_service
        self._lock = RLock()
        self._memory_store: Dict[str, Dict[str, Dict[str, Any]]] = {}

        self._collections = {
            "loans": "bnpl_loans",
            "collaterals": "bnpl_collaterals",
            "installments": "bnpl_installments",
            "risk_scores": "bnpl_risk_scores",
            "liquidation_logs": "bnpl_liquidation_logs",
            "orders": "bnpl_orders",
            "alerts": "bnpl_alerts",
            "events": "bnpl_events",
            "settings": "bnpl_settings",
            "payments": "bnpl_payment_attempts",
            "disputes": "bnpl_disputes",
            "notifications": "bnpl_notifications",
            "ledger": "bnpl_ledger",
            "jobs": "bnpl_jobs",
            "idempotency": "bnpl_idempotency",
            "merchants": "bnpl_merchants",
            "reminders": "bnpl_reminders",
            "fraud_flags": "bnpl_fraud_flags",
        }
        self._rate_limit_cache: Dict[str, Dict[str, Any]] = {}

    def _new_id(self, prefix: str) -> str:
        """Generate a prefixed unique identifier."""
        return "{0}_{1}".format(prefix, uuid4().hex[:16])

    def _set_document(
        self,
        collection_alias: str,
        document_id: str,
        payload: Dict[str, Any],
        merge: bool = False,
    ) -> Dict[str, Any]:
        """Persist document into Firestore or in-memory fallback."""
        collection_name = self._collections[collection_alias]
        if self._firebase_manager is not None:
            return self._firebase_manager.set_document(
                collection_name=collection_name,
                document_id=document_id,
                payload=payload,
                merge=merge,
            )
        with self._lock:
            bucket = self._memory_store.setdefault(collection_name, {})
            if merge and document_id in bucket:
                merged = dict(bucket[document_id])
                merged.update(payload)
                bucket[document_id] = merged
            else:
                bucket[document_id] = dict(payload)
            return dict(bucket[document_id])

    def _get_document(self, collection_alias: str, document_id: str) -> Optional[Dict[str, Any]]:
        """Fetch one document by id."""
        collection_name = self._collections[collection_alias]
        if self._firebase_manager is not None:
            return self._firebase_manager.get_document(collection_name=collection_name, document_id=document_id)
        with self._lock:
            bucket = self._memory_store.setdefault(collection_name, {})
            payload = bucket.get(document_id)
            if payload is None:
                return None
            result = dict(payload)
            result.setdefault("id", document_id)
            return result

    def _query_documents(
        self,
        collection_alias: str,
        filters: Optional[Sequence[FilterTuple]] = None,
        order_by: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Query documents by filters in active storage backend."""
        collection_name = self._collections[collection_alias]
        if self._firebase_manager is not None:
            return self._firebase_manager.query_documents(
                collection_name=collection_name,
                filters=filters,
                order_by=order_by,
                limit=limit,
            )
        with self._lock:
            bucket = self._memory_store.setdefault(collection_name, {})
            records: List[Dict[str, Any]] = []
            for document_id, payload in bucket.items():
                row = dict(payload)
                row.setdefault("id", document_id)
                if self._matches_filters(row, filters or []):
                    records.append(row)
            if order_by:
                records.sort(key=lambda item: item.get(order_by))
            if limit is not None:
                records = records[: int(limit)]
            return records

    def _matches_filters(self, payload: Dict[str, Any], filters: Sequence[FilterTuple]) -> bool:
        """Evaluate query-like filters for in-memory fallback."""
        for field_name, operator, expected_value in filters:
            actual_value = payload.get(field_name)
            if operator == "==":
                if actual_value != expected_value:
                    return False
            elif operator == "!=":
                if actual_value == expected_value:
                    return False
            elif operator == ">":
                if actual_value is None or actual_value <= expected_value:
                    return False
            elif operator == ">=":
                if actual_value is None or actual_value < expected_value:
                    return False
            elif operator == "<":
                if actual_value is None or actual_value >= expected_value:
                    return False
            elif operator == "<=":
                if actual_value is None or actual_value > expected_value:
                    return False
            elif operator == "in":
                if actual_value not in expected_value:
                    return False
            else:
                raise ValueError("Unsupported filter operator: {0}".format(operator))
        return True

    def _ensure_not_paused(self) -> None:
        """Raise if emergency pause is enabled."""
        pause_state = self.get_pause_state()
        if pause_state.get("paused", False):
            raise ValueError("Protocol is paused. Risky actions are temporarily disabled.")

    def _record_event(
        self,
        event_type: str,
        actor: str,
        payload: Dict[str, Any],
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        actor_role: Optional[str] = None,
        correlation_id: Optional[str] = None,
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Store structured audit event logs for protocol actions."""
        event_id = self._new_id("evt")
        event_correlation_id = correlation_id or payload.get("correlation_id") or self._new_id("corr")
        event_payload = {
            "event_id": event_id,
            "event_type": event_type,
            "actor": actor,
            "actor_role": actor_role or UserRole.USER.value,
            "entity_type": entity_type or "GENERIC",
            "entity_id": entity_id or "",
            "correlation_id": event_correlation_id,
            "payload": payload,
            "before": before,
            "after": after,
            "created_at": _now_utc(),
            "updated_at": _now_utc(),
        }
        self._set_document("events", event_id, event_payload, merge=False)
        return event_payload

    def _load_loan(self, loan_id: str) -> LoanModel:
        """Load loan model by id."""
        payload = self._get_document("loans", loan_id)
        if payload is None:
            raise ValueError("Loan not found: {0}".format(loan_id))
        return LoanModel.from_firestore(payload, doc_id=loan_id)

    def _save_loan(self, loan: LoanModel, merge: bool = False) -> LoanModel:
        """Persist loan model."""
        payload = loan.to_firestore()
        stored = self._set_document("loans", loan.loan_id, payload, merge=merge)
        return LoanModel.from_firestore(stored, doc_id=loan.loan_id)

    def _load_collateral(self, collateral_id: str) -> CollateralModel:
        """Load collateral model by id."""
        payload = self._get_document("collaterals", collateral_id)
        if payload is None:
            raise ValueError("Collateral not found: {0}".format(collateral_id))
        return CollateralModel.from_firestore(payload, doc_id=collateral_id)

    def _save_collateral(self, collateral: CollateralModel, merge: bool = False) -> CollateralModel:
        """Persist collateral model."""
        payload = collateral.to_firestore()
        stored = self._set_document("collaterals", collateral.collateral_id, payload, merge=merge)
        return CollateralModel.from_firestore(stored, doc_id=collateral.collateral_id)

    def _save_installment(self, installment: InstallmentModel, merge: bool = False) -> InstallmentModel:
        """Persist installment model."""
        payload = installment.to_firestore()
        stored = self._set_document("installments", installment.installment_id, payload, merge=merge)
        return InstallmentModel.from_firestore(stored, doc_id=installment.installment_id)

    def _save_risk_score(self, score: RiskScoreModel, merge: bool = False) -> RiskScoreModel:
        """Persist risk score model."""
        payload = score.to_firestore()
        stored = self._set_document("risk_scores", score.risk_score_id, payload, merge=merge)
        return RiskScoreModel.from_firestore(stored, doc_id=score.risk_score_id)

    def _save_liquidation_log(self, log: LiquidationLogModel, merge: bool = False) -> LiquidationLogModel:
        """Persist liquidation log model."""
        payload = log.to_firestore()
        stored = self._set_document("liquidation_logs", log.log_id, payload, merge=merge)
        return LiquidationLogModel.from_firestore(stored, doc_id=log.log_id)

    def _get_installments_for_loan(self, loan_id: str) -> List[InstallmentModel]:
        """Fetch installments for one loan ordered by sequence."""
        payloads = self._query_documents(
            "installments",
            filters=[("loan_id", "==", loan_id), ("is_deleted", "==", False)],
            order_by="sequence_no",
        )
        installments = [InstallmentModel.from_firestore(item, doc_id=item.get("id")) for item in payloads]
        installments.sort(key=lambda item: item.sequence_no)
        return installments

    def _get_collaterals_for_loan(self, loan_id: str) -> List[CollateralModel]:
        """Fetch collateral rows for a loan."""
        payloads = self._query_documents(
            "collaterals",
            filters=[("loan_id", "==", loan_id), ("is_deleted", "==", False)],
        )
        return [CollateralModel.from_firestore(item, doc_id=item.get("id")) for item in payloads]

    def _update_user_counts(self, user_id: str, top_up_delta: int = 0) -> None:
        """Update user behavior counters when repository is available."""
        if self._user_repository is None:
            return
        try:
            user = self._user_repository.get_by_id(user_id)
            user.top_up_count = max(0, user.top_up_count + top_up_delta)
            user.version += 1
            self._user_repository.update(user)
        except Exception:
            logger.exception("Failed updating user counters user_id=%s", user_id)

    def _load_user(self, user_id: str) -> UserModel:
        """Load user profile from repository."""
        if self._user_repository is None:
            raise ValueError("User repository unavailable.")
        try:
            return self._user_repository.get_by_id(user_id)
        except Exception:
            logger.exception("Failed loading user profile user_id=%s", user_id)
            raise

    def _save_user(self, user: UserModel) -> UserModel:
        """Persist user profile using optimistic version updates."""
        if self._user_repository is None:
            raise ValueError("User repository unavailable.")
        try:
            user.version += 1
            return self._user_repository.update(user)
        except Exception:
            logger.exception("Failed saving user profile user_id=%s", user.user_id)
            raise

    def _ensure_user_compliance(self, user_id: str) -> Dict[str, Any]:
        """Validate user KYC + AML status before credit actions."""
        if self._user_repository is None:
            return {
                "kyc_status": "BYPASS_NO_REPOSITORY",
                "aml_status": "BYPASS_NO_REPOSITORY",
                "user_id": user_id,
            }
        user = self._load_user(user_id)
        if user.kyc_status != KycStatus.VERIFIED:
            raise ValueError("KYC verification is required before creating a BNPL loan.")
        if user.aml_status in {ScreeningStatus.FLAGGED, ScreeningStatus.BLOCKED}:
            raise ValueError("AML screening failed. Borrowing is blocked.")
        if user.aml_status == ScreeningStatus.NOT_SCREENED:
            raise ValueError("AML screening is required before creating a BNPL loan.")
        return {
            "kyc_status": user.kyc_status.value,
            "aml_status": user.aml_status.value,
            "user_id": user.user_id,
        }

    def _get_setting_value(self, key: str, default: Any) -> Any:
        """Read one setting value with defaults."""
        payload = self._get_document("settings", key)
        if payload is None:
            return default
        return payload.get("value", default)

    def _put_setting_value(self, key: str, value: Any, actor: str = "system") -> Dict[str, Any]:
        """Persist one setting value."""
        payload = {
            "id": key,
            "value": value,
            "updated_by": actor,
            "created_at": _now_utc(),
            "updated_at": _now_utc(),
        }
        return self._set_document("settings", key, payload, merge=False)

    def _default_asset_policies(self) -> Dict[str, Dict[str, Any]]:
        """Return built-in collateral policies used when no policy config exists."""
        return {
            "BNB": {
                "asset_symbol": "BNB",
                "chain": "bsc",
                "ltv_bps": 6500,
                "liquidation_threshold_bps": 8500,
                "liquidation_penalty_bps": 700,
                "min_deposit_minor": 1000,
                "decimals": 18,
                "enabled": True,
            },
            "USDT": {
                "asset_symbol": "USDT",
                "chain": "bsc",
                "ltv_bps": 8000,
                "liquidation_threshold_bps": 9000,
                "liquidation_penalty_bps": 500,
                "min_deposit_minor": 100,
                "decimals": 18,
                "enabled": True,
            },
            "USDC": {
                "asset_symbol": "USDC",
                "chain": "bsc",
                "ltv_bps": 8000,
                "liquidation_threshold_bps": 9000,
                "liquidation_penalty_bps": 500,
                "min_deposit_minor": 100,
                "decimals": 18,
                "enabled": True,
            },
        }

    def _get_asset_policy(self, asset_symbol: str) -> Dict[str, Any]:
        """Fetch asset-level collateral policy from settings."""
        symbol = asset_symbol.strip().upper()
        policies = self._get_setting_value("collateral_asset_policies", self._default_asset_policies())
        policy = policies.get(symbol)
        if policy is None or not bool(policy.get("enabled", True)):
            raise ValueError("Unsupported or disabled collateral asset: {0}".format(symbol))
        return policy

    def _assert_allowed_transition(self, current_status: LoanStatus, new_status: LoanStatus) -> None:
        """Validate explicit loan-state transitions."""
        allowed = DEFAULT_LOAN_TRANSITIONS.get(current_status, set())
        if new_status not in allowed:
            raise ValueError(
                "Invalid loan state transition: {0} -> {1}".format(current_status.value, new_status.value)
            )

    def _record_ledger_entry(
        self,
        loan_id: str,
        user_id: str,
        entry_type: str,
        amount_minor: int,
        currency: str,
        reference_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist financial ledger entries for all balance-changing actions."""
        ledger_id = self._new_id("led")
        payload = {
            "ledger_id": ledger_id,
            "loan_id": loan_id,
            "user_id": user_id,
            "entry_type": entry_type,
            "amount_minor": int(max(0, amount_minor)),
            "currency": currency.upper(),
            "reference_id": reference_id,
            "metadata": metadata or {},
            "created_at": _now_utc(),
            "updated_at": _now_utc(),
            "is_deleted": False,
        }
        self._set_document("ledger", ledger_id, payload, merge=False)
        return payload

    def _check_idempotency(self, operation: str, idempotency_key: Optional[str]) -> Optional[Dict[str, Any]]:
        """Guard critical write operations from duplicate execution."""
        normalized = (idempotency_key or "").strip()
        if not normalized:
            return None
        unique_key = "{0}:{1}".format(operation, normalized)
        existing = self._get_document("idempotency", unique_key)
        if existing is not None:
            return existing.get("response")
        return None

    def _store_idempotency(self, operation: str, idempotency_key: Optional[str], response: Dict[str, Any]) -> None:
        """Store idempotent operation response for replay-safe returns."""
        normalized = (idempotency_key or "").strip()
        if not normalized:
            return
        unique_key = "{0}:{1}".format(operation, normalized)
        payload = {
            "id": unique_key,
            "operation": operation,
            "key": normalized,
            "response": response,
            "created_at": _now_utc(),
            "updated_at": _now_utc(),
        }
        self._set_document("idempotency", unique_key, payload, merge=False)

    def _risk_tier_from_metrics(self, safety_ratio: float, missed_count: int, avg_delay_hours: float) -> RiskTier:
        """Convert behavioral metrics into a risk tier."""
        if safety_ratio < 1.0 or missed_count >= 2 or avg_delay_hours > 24:
            return RiskTier.CRITICAL
        if safety_ratio < 1.1 or missed_count >= 1 or avg_delay_hours > 12:
            return RiskTier.HIGH
        if safety_ratio < 1.3 or avg_delay_hours > 4:
            return RiskTier.MEDIUM
        return RiskTier.LOW

    def _safety_color(self, safety_ratio: float) -> str:
        """Map safety ratio to UI color."""
        if safety_ratio >= 1.3:
            return "green"
        if safety_ratio >= 1.1:
            return "yellow"
        return "red"

    def _schedule_hash(self, installments: List[InstallmentModel]) -> str:
        """Build deterministic hash for generated installment schedule."""
        raw = "|".join(
            "{0}:{1}:{2}".format(item.sequence_no, int(item.due_at.timestamp()), item.amount_minor)
            for item in installments
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _oracle_age_sec(self) -> Optional[int]:
        """Compute oracle staleness age in seconds from protocol state."""
        try:
            prices = self._protocol_service.get_prices()
            last_updated = _as_int(prices.get("usd_last_updated"), default=0)
            if last_updated <= 0:
                return None
            return max(0, int(_now_utc().timestamp()) - last_updated)
        except Exception:
            logger.exception("Failed computing oracle age.")
            return None

    def get_pause_state(self) -> Dict[str, Any]:
        """Return emergency pause state."""
        payload = self._get_document("settings", "emergency_pause")
        if payload is None:
            default_payload = {
                "paused": False,
                "reason": "",
                "updated_at": _now_utc(),
                "updated_by": "system",
            }
            self._set_document("settings", "emergency_pause", default_payload, merge=False)
            return default_payload
        return payload

    def set_pause_state(self, paused: bool, reason: str, role: str, actor: str) -> Dict[str, Any]:
        """Set emergency pause state (Feature 19, role controlled by router)."""
        payload = {
            "paused": bool(paused),
            "reason": reason.strip(),
            "updated_at": _now_utc(),
            "updated_by": actor,
            "role": role,
        }
        self._set_document("settings", "emergency_pause", payload, merge=False)
        self._record_event("EMERGENCY_PAUSE_UPDATED", actor, payload)
        return payload

    def list_emi_plans(self, currency: Optional[str] = None, include_disabled: bool = False) -> Dict[str, Any]:
        """List EMI plans available for schedule generation and ML orchestration."""
        try:
            plans = self._emi_plan_catalog.list_plans(include_disabled=include_disabled, currency=currency)
            return {
                "total": len(plans),
                "currency": (currency or "").upper() if currency else None,
                "plans": plans,
            }
        except Exception:
            logger.exception(
                "Failed listing EMI plans currency=%s include_disabled=%s",
                currency,
                include_disabled,
            )
            raise

    def get_emi_plan_details(self, plan_id: str) -> Dict[str, Any]:
        """Return one EMI plan by id."""
        try:
            plan = self._emi_plan_catalog.get_plan(plan_id=plan_id, include_disabled=False)
            if plan is None:
                raise ValueError("EMI plan not found: {0}".format(plan_id))
            if hasattr(plan, "model_dump"):
                return plan.model_dump()
            return plan.dict()
        except Exception:
            logger.exception("Failed getting EMI plan details plan_id=%s", plan_id)
            raise

    def create_bnpl_plan(
        self,
        user_id: str,
        merchant_id: str,
        principal_minor: int,
        currency: str,
        installment_count: int,
        tenure_days: int,
        ltv_bps: int,
        danger_limit_bps: int,
        liquidation_threshold_bps: int,
        grace_window_hours: int,
        late_fee_flat_minor: int,
        late_fee_bps: int,
        emi_plan_id: Optional[str] = None,
        use_plan_defaults: bool = True,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create BNPL plan and installment schedule (Features 2, 6, 16)."""
        self._ensure_not_paused()
        try:
            cached = self._check_idempotency("create_bnpl_plan", idempotency_key=idempotency_key)
            if cached is not None:
                return cached
            compliance_snapshot = self._ensure_user_compliance(user_id=user_id)
            if principal_minor <= 0:
                raise ValueError("principal_minor must be > 0")
            if installment_count <= 0:
                raise ValueError("installment_count must be > 0")
            if tenure_days <= 0:
                raise ValueError("tenure_days must be > 0")

            plan_context, selected_plan = self._emi_plan_catalog.apply_plan_defaults(
                payload={
                    "emi_plan_id": emi_plan_id,
                    "currency": currency,
                    "installment_count": installment_count,
                    "tenure_days": tenure_days,
                    "grace_window_hours": grace_window_hours,
                    "late_fee_flat_minor": late_fee_flat_minor,
                    "late_fee_bps": late_fee_bps,
                    "ltv_bps": ltv_bps,
                    "danger_limit_bps": danger_limit_bps,
                    "liquidation_threshold_bps": liquidation_threshold_bps,
                },
                force=bool(use_plan_defaults and emi_plan_id),
            )
            installment_count = int(plan_context.get("installment_count", installment_count))
            tenure_days = int(plan_context.get("tenure_days", tenure_days))
            grace_window_hours = int(plan_context.get("grace_window_hours", grace_window_hours))
            late_fee_flat_minor = int(plan_context.get("late_fee_flat_minor", late_fee_flat_minor))
            late_fee_bps = int(plan_context.get("late_fee_bps", late_fee_bps))
            ltv_bps = int(plan_context.get("ltv_bps", ltv_bps))
            danger_limit_bps = int(plan_context.get("danger_limit_bps", danger_limit_bps))
            liquidation_threshold_bps = int(
                plan_context.get("liquidation_threshold_bps", liquidation_threshold_bps)
            )
            emi_plan_id = str(plan_context.get("emi_plan_id") or "").strip() or None
            emi_plan_name = str(plan_context.get("emi_plan_name") or "").strip() or None
            emi_source_platform = str(plan_context.get("emi_source_platform") or "").strip() or None

            loan_id = self._new_id("loan")
            normalized_currency = currency.strip().upper()
            base_amount = principal_minor // installment_count
            remainder = principal_minor % installment_count
            step_days = max(1, tenure_days // installment_count)
            now = _now_utc()
            installments: List[InstallmentModel] = []
            for sequence_no in range(1, installment_count + 1):
                amount = base_amount + (1 if sequence_no <= remainder else 0)
                due_at = now + timedelta(days=step_days * sequence_no)
                grace_deadline = due_at + timedelta(hours=grace_window_hours)
                installment = InstallmentModel(
                    installment_id=self._new_id("ins"),
                    loan_id=loan_id,
                    user_id=user_id,
                    sequence_no=sequence_no,
                    due_at=due_at,
                    amount_minor=amount,
                    grace_deadline=grace_deadline,
                    status=InstallmentStatus.UPCOMING,
                    calculation_trace={
                        "principal_minor": str(principal_minor),
                        "installment_count": str(installment_count),
                        "base_amount_minor": str(base_amount),
                        "remainder_minor": str(remainder),
                        "emi_plan_id": str(emi_plan_id or ""),
                        "emi_plan_name": str(emi_plan_name or ""),
                    },
                )
                installments.append(installment)

            InstallmentModel.validate_schedule(installments, expected_total_minor=principal_minor)
            schedule_hash = self._schedule_hash(installments)
            installment_ids = [item.installment_id for item in installments]

            loan = LoanModel(
                loan_id=loan_id,
                user_id=user_id,
                merchant_id=merchant_id,
                principal_minor=int(principal_minor),
                currency=normalized_currency,
                tenure_days=int(tenure_days),
                installment_count=int(installment_count),
                ltv_bps=int(ltv_bps),
                borrow_limit_minor=(int(principal_minor) * int(ltv_bps)) // 10000,
                danger_limit_bps=int(danger_limit_bps),
                liquidation_threshold_bps=int(liquidation_threshold_bps),
                schedule_hash=schedule_hash,
                installment_ids=installment_ids,
                emi_plan_id=emi_plan_id,
                emi_plan_name=emi_plan_name,
                emi_source_platform=emi_source_platform,
                grace_window_hours=int(grace_window_hours),
                late_fee_flat_minor=int(late_fee_flat_minor),
                late_fee_bps=int(late_fee_bps),
                status=LoanStatus.ACTIVE,
                outstanding_minor=int(principal_minor),
                paid_minor=0,
                penalty_accrued_minor=0,
            )
            persisted_loan = self._save_loan(loan, merge=False)
            persisted_installments = [self._save_installment(item, merge=False) for item in installments]

            self._record_event(
                event_type="BNPL_PLAN_CREATED",
                actor=user_id,
                payload={
                    "loan_id": persisted_loan.loan_id,
                    "merchant_id": merchant_id,
                    "principal_minor": principal_minor,
                    "currency": normalized_currency,
                    "emi_plan_id": emi_plan_id,
                    "compliance": compliance_snapshot,
                },
                entity_type="LOAN",
                entity_id=persisted_loan.loan_id,
                actor_role=UserRole.USER.value,
            )

            response = {
                "loan": persisted_loan.to_firestore(),
                "installments": [item.to_firestore() for item in persisted_installments],
                "emi_plan": (
                    selected_plan.model_dump()
                    if selected_plan is not None and hasattr(selected_plan, "model_dump")
                    else (selected_plan.dict() if selected_plan is not None else None)
                ),
            }
            self._store_idempotency("create_bnpl_plan", idempotency_key=idempotency_key, response=response)
            return response
        except Exception:
            logger.exception("Failed creating BNPL plan user_id=%s merchant_id=%s", user_id, merchant_id)
            raise

    def lock_security_deposit(
        self,
        loan_id: str,
        user_id: str,
        asset_symbol: str,
        deposited_units: int,
        collateral_value_minor: int,
        oracle_price_minor: int,
        vault_address: str,
        chain_id: int,
        deposit_tx_hash: str,
        proof_page_url: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Lock refundable security deposit in vault (Feature 1)."""
        self._ensure_not_paused()
        try:
            cached = self._check_idempotency("lock_security_deposit", idempotency_key=idempotency_key)
            if cached is not None:
                return cached
            if self._user_repository is not None:
                user = self._load_user(user_id)
                if not user.verified_wallets:
                    raise ValueError("At least one verified wallet is required for collateral operations.")
            if deposited_units <= 0:
                raise ValueError("deposited_units must be > 0")
            if collateral_value_minor <= 0:
                raise ValueError("collateral_value_minor must be > 0")
            policy = self._get_asset_policy(asset_symbol=asset_symbol)
            if int(collateral_value_minor) < int(policy.get("min_deposit_minor", 0)):
                raise ValueError(
                    "Collateral value is below the minimum required deposit for asset {0}".format(asset_symbol.upper())
                )
            loan = self._load_loan(loan_id)

            collateral = CollateralModel(
                collateral_id=self._new_id("col"),
                user_id=user_id,
                loan_id=loan_id,
                vault_address=vault_address,
                chain_id=chain_id,
                deposit_tx_hash=deposit_tx_hash,
                asset_symbol=asset_symbol.upper(),
                decimals=int(policy.get("decimals", 18)),
                deposited_units=int(deposited_units),
                collateral_value_minor=int(collateral_value_minor),
                oracle_price_minor=int(oracle_price_minor),
                health_factor=0.0,
                safety_color="red",
                recoverable_minor=int(collateral_value_minor),
                recovered_minor=0,
                status=CollateralStatus.LOCKED,
                proof_page_url=proof_page_url,
            )
            stored = self._save_collateral(collateral, merge=False)
            meter = self.get_safety_meter(loan_id=loan_id)
            self._record_event(
                event_type="COLLATERAL_LOCKED",
                actor=user_id,
                payload={
                    "loan_id": loan.loan_id,
                    "collateral_id": stored.collateral_id,
                    "tx_hash": deposit_tx_hash,
                    "collateral_value_minor": collateral_value_minor,
                    "asset_policy": policy,
                },
                entity_type="COLLATERAL",
                entity_id=stored.collateral_id,
            )
            response = {"collateral": stored.to_firestore(), "safety_meter": meter}
            self._store_idempotency("lock_security_deposit", idempotency_key=idempotency_key, response=response)
            return response
        except Exception:
            logger.exception("Failed locking security deposit loan_id=%s user_id=%s", loan_id, user_id)
            raise

    def top_up_collateral(
        self,
        collateral_id: str,
        added_units: int,
        added_value_minor: int,
        oracle_price_minor: int,
        topup_tx_hash: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Top-up collateral amount and update safety metrics (Feature 5)."""
        self._ensure_not_paused()
        try:
            cached = self._check_idempotency("top_up_collateral", idempotency_key=idempotency_key)
            if cached is not None:
                return cached
            collateral = self._load_collateral(collateral_id)
            if added_units <= 0:
                raise ValueError("added_units must be > 0")
            if added_value_minor <= 0:
                raise ValueError("added_value_minor must be > 0")

            collateral.deposited_units += int(added_units)
            collateral.collateral_value_minor += int(added_value_minor)
            collateral.oracle_price_minor = int(oracle_price_minor)
            collateral.status = CollateralStatus.TOPPED_UP
            collateral.updated_at = _now_utc()
            updated_collateral = self._save_collateral(collateral, merge=False)

            self._update_user_counts(user_id=updated_collateral.user_id, top_up_delta=1)
            meter = self.get_safety_meter(updated_collateral.loan_id)

            self._record_event(
                event_type="COLLATERAL_TOPPED_UP",
                actor=updated_collateral.user_id,
                payload={
                    "collateral_id": updated_collateral.collateral_id,
                    "loan_id": updated_collateral.loan_id,
                    "added_units": added_units,
                    "added_value_minor": added_value_minor,
                    "tx_hash": topup_tx_hash or "",
                },
            )
            response = {"collateral": updated_collateral.to_firestore(), "safety_meter": meter}
            self._store_idempotency("top_up_collateral", idempotency_key=idempotency_key, response=response)
            return response
        except Exception:
            logger.exception("Failed top-up collateral collateral_id=%s", collateral_id)
            raise

    def get_safety_meter(self, loan_id: str) -> Dict[str, Any]:
        """Compute health factor and safety color for a loan (Feature 3)."""
        try:
            loan = self._load_loan(loan_id)
            collaterals = self._get_collaterals_for_loan(loan_id)
            total_collateral_minor = sum(item.collateral_value_minor - item.recovered_minor for item in collaterals)
            outstanding_minor = max(loan.outstanding_minor, 0)
            if outstanding_minor <= 0:
                health_factor = 999999.0
            else:
                health_factor = float(total_collateral_minor) / float(outstanding_minor)
            safety_color = self._safety_color(health_factor)

            for collateral in collaterals:
                collateral.health_factor = health_factor
                collateral.safety_color = safety_color
                collateral.updated_at = _now_utc()
                self._save_collateral(collateral, merge=False)

            return {
                "loan_id": loan_id,
                "collateral_value_minor": int(total_collateral_minor),
                "outstanding_minor": int(outstanding_minor),
                "health_factor": round(health_factor, 6),
                "safety_color": safety_color,
                "danger_limit_bps": loan.danger_limit_bps,
                "liquidation_threshold_bps": loan.liquidation_threshold_bps,
            }
        except Exception:
            logger.exception("Failed computing safety meter loan_id=%s", loan_id)
            raise

    def compute_eligibility(self, user_id: str) -> Dict[str, Any]:
        """Compute instant checkout eligibility based on collateral and LTV (Feature 14)."""
        try:
            active_loans = self._query_documents(
                "loans",
                filters=[("user_id", "==", user_id), ("status", "in", [LoanStatus.ACTIVE.value, LoanStatus.GRACE.value])],
            )
            total_outstanding = sum(_as_int(item.get("outstanding_minor"), 0) for item in active_loans)
            user_collaterals = self._query_documents(
                "collaterals",
                filters=[("user_id", "==", user_id), ("is_deleted", "==", False)],
            )
            total_collateral = sum(
                _as_int(item.get("collateral_value_minor"), 0) - _as_int(item.get("recovered_minor"), 0)
                for item in user_collaterals
            )
            default_ltv_bps = 7000
            max_credit = (total_collateral * default_ltv_bps) // 10000
            available_credit = max(0, max_credit - total_outstanding)
            return {
                "user_id": user_id,
                "total_collateral_minor": total_collateral,
                "max_credit_minor": max_credit,
                "outstanding_minor": total_outstanding,
                "available_credit_minor": available_credit,
                "ltv_bps": default_ltv_bps,
            }
        except Exception:
            logger.exception("Failed computing eligibility user_id=%s", user_id)
            raise

    def set_autopay(self, user_id: str, enabled: bool) -> Dict[str, Any]:
        """Toggle user auto-pay setting (Feature 8)."""
        if self._user_repository is None:
            raise ValueError("User repository unavailable.")
        try:
            user = self._user_repository.get_by_id(user_id)
            user.autopay_enabled = bool(enabled)
            user.version += 1
            updated = self._user_repository.update(user)
            self._record_event(
                event_type="AUTOPAY_TOGGLED",
                actor=user_id,
                payload={"autopay_enabled": enabled},
            )
            return {"user_id": user_id, "autopay_enabled": updated.autopay_enabled}
        except Exception:
            logger.exception("Failed setting autopay user_id=%s", user_id)
            raise

    def create_autopay_mandate(
        self,
        user_id: str,
        loan_id: str,
        amount_minor: int,
        currency: str = "INR",
        customer_name: Optional[str] = None,
        customer_email: Optional[str] = None,
        customer_contact: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create Razorpay payment link as autopay mandate simulation (Feature 8)."""
        try:
            if amount_minor <= 0:
                raise ValueError("amount_minor must be > 0")
            if self._razorpay_service is None or not self._razorpay_service.is_configured:
                raise ValueError("Razorpay is not configured.")

            link = self._razorpay_service.create_payment_link(
                amount_minor=int(amount_minor),
                currency=currency,
                description="Autopay mandate simulation for loan {0}".format(loan_id),
                customer={
                    "name": customer_name or user_id,
                    "email": customer_email or "{0}@example.local".format(user_id),
                    "contact": customer_contact or "9999999999",
                },
                notes={"loan_id": loan_id, "user_id": user_id, "flow": "autopay_mandate"},
            )
            self._record_event(
                event_type="AUTOPAY_MANDATE_CREATED",
                actor=user_id,
                payload={"loan_id": loan_id, "razorpay_link_id": link.get("id"), "amount_minor": amount_minor},
            )
            return {
                "loan_id": loan_id,
                "user_id": user_id,
                "amount_minor": amount_minor,
                "provider": "razorpay",
                "payment_link": link,
            }
        except Exception:
            logger.exception("Failed creating autopay mandate user_id=%s loan_id=%s", user_id, loan_id)
            raise

    def process_dispute_refund(
        self,
        loan_id: str,
        payment_id: str,
        amount_minor: Optional[int] = None,
        notes: str = "Dispute refund",
    ) -> Dict[str, Any]:
        """Trigger Razorpay refund for dispute/refund workflow (Feature 9)."""
        try:
            if self._razorpay_service is None or not self._razorpay_service.is_configured:
                raise ValueError("Razorpay is not configured.")
            refund = self._razorpay_service.create_refund(
                payment_id=payment_id,
                amount_minor=amount_minor,
                notes={"loan_id": loan_id, "flow": "dispute_refund", "notes": notes},
            )
            self._record_event(
                event_type="DISPUTE_REFUND_PROCESSED",
                actor="system",
                payload={"loan_id": loan_id, "payment_id": payment_id, "refund_id": refund.get("id")},
            )
            return {"loan_id": loan_id, "payment_id": payment_id, "provider": "razorpay", "refund": refund}
        except Exception:
            logger.exception("Failed processing dispute refund loan_id=%s payment_id=%s", loan_id, payment_id)
            raise

    def open_dispute(
        self,
        loan_id: str,
        reason: str,
        actor: str,
        category: str = DisputeCategory.PAYMENT_ISSUE.value,
    ) -> Dict[str, Any]:
        """Open dispute and freeze penalties based on category policy (Features 7.1, 7.3, 9)."""
        try:
            loan = self._load_loan(loan_id)
            normalized_category = str(category).strip().upper()
            try:
                dispute_category = DisputeCategory(normalized_category)
            except Exception:
                raise ValueError("Invalid dispute category: {0}".format(category))

            pause_rules = self.get_dispute_pause_rules()
            category_rule = pause_rules.get(dispute_category.value, {})
            pause_penalties = bool(category_rule.get("pause_penalties", True))
            pause_liquidation = bool(category_rule.get("pause_liquidation", True))
            pause_hours = int(category_rule.get("pause_hours", 168))
            loan.paused_penalties_until = _now_utc() + timedelta(hours=pause_hours) if pause_penalties else _now_utc()
            loan.dispute_state = "OPEN"
            loan.status = LoanStatus.DISPUTE_OPEN
            loan.updated_at = _now_utc()
            before = loan.to_firestore()
            updated = self._save_loan(loan, merge=False)
            dispute_id = self._new_id("dsp")
            dispute_payload = {
                "dispute_id": dispute_id,
                "loan_id": loan_id,
                "user_id": loan.user_id,
                "merchant_id": loan.merchant_id,
                "category": dispute_category.value,
                "reason": reason,
                "status": "OPEN",
                "pause_penalties": pause_penalties,
                "pause_liquidation": pause_liquidation,
                "opened_by": actor,
                "opened_at": _now_utc(),
                "updated_at": _now_utc(),
                "evidence": [],
                "comments": [],
                "review_notes": [],
            }
            self._set_document("disputes", dispute_id, dispute_payload, merge=False)
            self._record_event(
                event_type="DISPUTE_OPENED",
                actor=actor,
                payload={"loan_id": loan_id, "reason": reason, "category": dispute_category.value},
                entity_type="DISPUTE",
                entity_id=dispute_id,
                before=before,
                after=updated.to_firestore(),
            )
            return {"loan": updated.to_firestore(), "reason": reason, "category": dispute_category.value, "dispute_id": dispute_id}
        except Exception:
            logger.exception("Failed opening dispute loan_id=%s", loan_id)
            raise

    def resolve_dispute(
        self,
        loan_id: str,
        resolution: str,
        actor: str,
        restore_active: bool = True,
        refund_payment_id: Optional[str] = None,
        refund_amount_minor: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Resolve dispute and optionally restore active status (Feature 9)."""
        try:
            loan = self._load_loan(loan_id)
            before = loan.to_firestore()
            loan.dispute_state = "RESOLVED"
            loan.paused_penalties_until = _now_utc()
            loan.status = LoanStatus.ACTIVE if restore_active else LoanStatus.CLOSED
            loan.updated_at = _now_utc()
            updated = self._save_loan(loan, merge=False)
            disputes = self._query_documents(
                "disputes",
                filters=[("loan_id", "==", loan_id), ("status", "==", "OPEN")],
                order_by="opened_at",
                limit=1,
            )
            resolved_dispute: Optional[Dict[str, Any]] = None
            if disputes:
                resolved_dispute = dict(disputes[0])
                resolved_dispute["status"] = "RESOLVED"
                resolved_dispute["resolution"] = resolution
                resolved_dispute["resolved_by"] = actor
                resolved_dispute["resolved_at"] = _now_utc()
                resolved_dispute["updated_at"] = _now_utc()
                dispute_id = str(resolved_dispute.get("id") or resolved_dispute.get("dispute_id"))
                self._set_document("disputes", dispute_id, resolved_dispute, merge=True)
            refund_result: Optional[Dict[str, Any]] = None
            if refund_payment_id:
                refund_result = self.process_dispute_refund(
                    loan_id=loan_id,
                    payment_id=refund_payment_id,
                    amount_minor=refund_amount_minor,
                    notes="Dispute resolved refund",
                )
            self._record_event(
                event_type="DISPUTE_RESOLVED",
                actor=actor,
                payload={
                    "loan_id": loan_id,
                    "resolution": resolution,
                    "restore_active": restore_active,
                    "refund_payment_id": refund_payment_id,
                },
                entity_type="LOAN",
                entity_id=loan_id,
                before=before,
                after=updated.to_firestore(),
            )
            return {
                "loan": updated.to_firestore(),
                "resolution": resolution,
                "refund": refund_result,
                "dispute": resolved_dispute,
            }
        except Exception:
            logger.exception("Failed resolving dispute loan_id=%s", loan_id)
            raise

    def preview_late_fee(self, loan_id: str, installment_id: str, as_of: Optional[datetime] = None) -> Dict[str, Any]:
        """Preview grace-window status and late fee details (Feature 6)."""
        try:
            loan = self._load_loan(loan_id)
            payload = self._get_document("installments", installment_id)
            if payload is None:
                raise ValueError("Installment not found: {0}".format(installment_id))
            installment = InstallmentModel.from_firestore(payload, doc_id=installment_id)
            reference_time = as_of or _now_utc()
            grace_deadline = installment.grace_deadline or (installment.due_at + timedelta(hours=loan.grace_window_hours))
            in_grace = reference_time <= grace_deadline
            late_fee_minor = 0
            if not in_grace and installment.status in {InstallmentStatus.DUE, InstallmentStatus.MISSED, InstallmentStatus.UPCOMING}:
                late_fee_minor = int(loan.late_fee_flat_minor) + int((installment.amount_minor * loan.late_fee_bps) / 10000)
            return {
                "loan_id": loan_id,
                "installment_id": installment_id,
                "due_at": installment.due_at,
                "grace_deadline": grace_deadline,
                "in_grace": in_grace,
                "late_fee_minor": int(late_fee_minor),
                "late_fee_flat_minor": int(loan.late_fee_flat_minor),
                "late_fee_bps": int(loan.late_fee_bps),
            }
        except Exception:
            logger.exception("Failed previewing late fee loan_id=%s installment_id=%s", loan_id, installment_id)
            raise

    def run_early_warning_scan(self, threshold_ratio: float = 1.15) -> Dict[str, Any]:
        """Generate early warnings when safety meter nears danger (Feature 4)."""
        try:
            alerts: List[Dict[str, Any]] = []
            loan_payloads = self._query_documents(
                "loans",
                filters=[("status", "in", [LoanStatus.ACTIVE.value, LoanStatus.GRACE.value, LoanStatus.OVERDUE.value])],
            )
            for payload in loan_payloads:
                loan = LoanModel.from_firestore(payload, doc_id=payload.get("id"))
                meter = self.get_safety_meter(loan.loan_id)
                health_factor = _as_float(meter.get("health_factor"), default=0.0)
                if health_factor <= threshold_ratio:
                    alert_id = self._new_id("alert")
                    alert = {
                        "alert_id": alert_id,
                        "loan_id": loan.loan_id,
                        "user_id": loan.user_id,
                        "channel_candidates": ["email", "whatsapp", "push"],
                        "message": "Safety meter is close to danger threshold. Please top up collateral.",
                        "health_factor": health_factor,
                        "created_at": _now_utc(),
                        "updated_at": _now_utc(),
                    }
                    self._set_document("alerts", alert_id, alert, merge=False)
                    alerts.append(alert)
            self._record_event(
                event_type="EARLY_WARNING_SCAN",
                actor="system",
                payload={"alerts_created": len(alerts), "threshold_ratio": threshold_ratio},
            )
            return {"alerts_created": len(alerts), "alerts": alerts}
        except Exception:
            logger.exception("Failed running early warning scan.")
            raise

    def simulate_missed_payment(self, loan_id: str, installment_id: str) -> Dict[str, Any]:
        """Run 'what happens if I miss payment' simulation (Feature 10)."""
        try:
            payload = self._get_document("installments", installment_id)
            if payload is None:
                raise ValueError("Installment not found: {0}".format(installment_id))
            installment = InstallmentModel.from_firestore(payload, doc_id=installment_id)
            preview = self.preview_late_fee(loan_id=loan_id, installment_id=installment_id)
            penalty_minor = _as_int(preview.get("late_fee_minor"), 0)
            needed_minor = installment.amount_minor + penalty_minor
            collaterals = self._get_collaterals_for_loan(loan_id)
            available_minor = sum(item.collateral_value_minor - item.recovered_minor for item in collaterals)
            seized_minor = min(available_minor, needed_minor)
            returned_minor = max(0, available_minor - seized_minor)
            return {
                "loan_id": loan_id,
                "installment_id": installment_id,
                "missed_amount_minor": installment.amount_minor,
                "penalty_minor": penalty_minor,
                "needed_minor": needed_minor,
                "available_collateral_minor": available_minor,
                "seized_minor_if_default": seized_minor,
                "remaining_collateral_minor": returned_minor,
                "note": "Partial recovery model seizes only needed amount.",
            }
        except Exception:
            logger.exception("Failed simulating missed payment loan_id=%s installment_id=%s", loan_id, installment_id)
            raise

    def simulate_merchant_settlement(
        self,
        merchant_id: str,
        user_id: str,
        loan_id: str,
        amount_minor: int,
        status: str = "PAID_UPFRONT",
        external_ref: Optional[str] = None,
        use_razorpay: bool = True,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create merchant settlement/order record (Features 11, 13, 15)."""
        try:
            cached = self._check_idempotency("merchant_settlement", idempotency_key=idempotency_key)
            if cached is not None:
                return cached
            merchant = self._get_document("merchants", merchant_id)
            if merchant is not None:
                merchant_status = str(merchant.get("status", MerchantStatus.PENDING.value)).upper()
                if merchant_status != MerchantStatus.ACTIVE.value:
                    raise ValueError("Merchant is not active for settlement operations.")
            order_id = self._new_id("ord")
            gateway_payload: Optional[Dict[str, Any]] = None
            provider = "simulation"
            provider_error: Optional[str] = None
            normalized_external_ref = external_ref or "rzp_{0}".format(uuid4().hex[:12])
            if use_razorpay and self._razorpay_service is not None:
                try:
                    gateway_payload = self._razorpay_service.create_order(
                        amount_minor=int(amount_minor),
                        currency="INR",
                        receipt=order_id,
                        notes={
                            "loan_id": loan_id,
                            "merchant_id": merchant_id,
                            "user_id": user_id,
                            "flow": "merchant_paid_upfront",
                        },
                    )
                    normalized_external_ref = str(gateway_payload.get("id", normalized_external_ref))
                    provider = "razorpay"
                except Exception as gateway_exc:
                    provider_error = str(gateway_exc)
                    logger.exception(
                        "Razorpay order creation failed; using simulation fallback loan_id=%s merchant_id=%s",
                        loan_id,
                        merchant_id,
                    )

            order_payload = {
                "order_id": order_id,
                "merchant_id": merchant_id,
                "user_id": user_id,
                "loan_id": loan_id,
                "amount_minor": int(amount_minor),
                "status": status,
                "settlement_status": (
                    SettlementStatus.PAID.value if status == "PAID_UPFRONT" else SettlementStatus.PROCESSING.value
                ),
                "external_ref": normalized_external_ref,
                "provider": provider,
                "provider_error": provider_error,
                "gateway_payload": gateway_payload,
                "created_at": _now_utc(),
                "updated_at": _now_utc(),
                "is_deleted": False,
            }
            self._set_document("orders", order_id, order_payload, merge=False)
            self._record_event(
                event_type="MERCHANT_SETTLEMENT_RECORDED",
                actor=merchant_id,
                payload={"order_id": order_id, "loan_id": loan_id, "amount_minor": amount_minor, "status": status},
                entity_type="ORDER",
                entity_id=order_id,
            )
            self._store_idempotency("merchant_settlement", idempotency_key=idempotency_key, response=order_payload)
            return order_payload
        except Exception:
            logger.exception("Failed simulating merchant settlement merchant_id=%s loan_id=%s", merchant_id, loan_id)
            raise

    def execute_partial_recovery(
        self,
        loan_id: str,
        installment_id: str,
        initiated_by_role: str,
        notes: str,
        merchant_transfer_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Recover only the needed collateral amount on default (Features 7, 15)."""
        try:
            loan = self._load_loan(loan_id)
            payload = self._get_document("installments", installment_id)
            if payload is None:
                raise ValueError("Installment not found: {0}".format(installment_id))
            installment = InstallmentModel.from_firestore(payload, doc_id=installment_id)

            preview = self.preview_late_fee(loan_id=loan_id, installment_id=installment_id)
            penalty_minor = _as_int(preview.get("late_fee_minor"), 0)
            needed_minor = int(installment.amount_minor + penalty_minor)
            remaining_needed = needed_minor
            collaterals = self._get_collaterals_for_loan(loan_id)
            seized_total = 0

            for collateral in collaterals:
                available = max(0, collateral.collateral_value_minor - collateral.recovered_minor)
                if available <= 0 or remaining_needed <= 0:
                    continue
                seize = min(available, remaining_needed)
                collateral.recovered_minor += seize
                remaining_needed -= seize
                seized_total += seize
                collateral.status = CollateralStatus.PARTIALLY_RECOVERED
                collateral.updated_at = _now_utc()
                self._save_collateral(collateral, merge=False)

            if seized_total > needed_minor:
                raise ValueError("Partial recovery cannot seize more than needed amount.")

            loan.penalty_accrued_minor += penalty_minor
            loan.outstanding_minor = max(0, loan.outstanding_minor - min(installment.amount_minor, seized_total))
            loan.status = LoanStatus.DELINQUENT if remaining_needed > 0 else LoanStatus.PARTIALLY_RECOVERED
            loan.updated_at = _now_utc()
            updated_loan = self._save_loan(loan, merge=False)

            installment.status = InstallmentStatus.MISSED if remaining_needed > 0 else InstallmentStatus.WAIVED
            installment.late_fee_minor = penalty_minor
            installment.updated_at = _now_utc()
            updated_installment = self._save_installment(installment, merge=False)

            log = LiquidationLogModel(
                log_id=self._new_id("liq"),
                loan_id=loan.loan_id,
                user_id=loan.user_id,
                collateral_id=collaterals[0].collateral_id if collaterals else "NA",
                triggered_at=_now_utc(),
                trigger_reason="MISSED_INSTALLMENT",
                health_factor_at_trigger=_as_float(self.get_safety_meter(loan.loan_id).get("health_factor"), 0.0),
                missed_amount_minor=installment.amount_minor,
                penalty_minor=penalty_minor,
                needed_minor=needed_minor,
                seized_minor=seized_total,
                returned_minor=max(0, seized_total - needed_minor),
                merchant_transfer_ref=merchant_transfer_ref,
                tx_hash="0x{0}".format(uuid4().hex),
                action_type=LiquidationActionType.PARTIAL_RECOVERY,
                initiated_by_role=initiated_by_role,
                policy_version="v1",
                notes=notes,
            )
            persisted_log = self._save_liquidation_log(log, merge=False)
            self._record_ledger_entry(
                loan_id=updated_loan.loan_id,
                user_id=updated_loan.user_id,
                entry_type="PARTIAL_RECOVERY_SEIZURE",
                amount_minor=seized_total,
                currency=updated_loan.currency,
                reference_id=persisted_log.log_id,
                metadata={"installment_id": installment_id, "needed_minor": needed_minor},
            )

            settlement = self.simulate_merchant_settlement(
                merchant_id=updated_loan.merchant_id,
                user_id=updated_loan.user_id,
                loan_id=updated_loan.loan_id,
                amount_minor=seized_total,
                status="RECOVERED_FROM_COLLATERAL",
                external_ref=merchant_transfer_ref,
            )

            self._record_event(
                event_type="PARTIAL_RECOVERY_EXECUTED",
                actor=initiated_by_role,
                payload={
                    "loan_id": loan_id,
                    "installment_id": installment_id,
                    "needed_minor": needed_minor,
                    "seized_minor": seized_total,
                    "remaining_needed_minor": remaining_needed,
                },
                entity_type="LIQUIDATION",
                entity_id=persisted_log.log_id,
                actor_role=initiated_by_role,
            )
            return {
                "loan": updated_loan.to_firestore(),
                "installment": updated_installment.to_firestore(),
                "liquidation_log": persisted_log.to_firestore(),
                "merchant_settlement": settlement,
                "remaining_needed_minor": remaining_needed,
            }
        except Exception:
            logger.exception("Failed executing partial recovery loan_id=%s installment_id=%s", loan_id, installment_id)
            raise

    def merchant_risk_view(self, loan_id: str) -> Dict[str, Any]:
        """Return proof-of-collateral and risk view for merchant (Feature 12)."""
        try:
            loan = self._load_loan(loan_id)
            collaterals = self._get_collaterals_for_loan(loan_id)
            meter = self.get_safety_meter(loan_id)
            proof_items = [
                {
                    "collateral_id": item.collateral_id,
                    "deposit_tx_hash": item.deposit_tx_hash,
                    "vault_address": item.vault_address,
                    "asset_symbol": item.asset_symbol,
                    "collateral_value_minor": item.collateral_value_minor,
                    "proof_page_url": item.proof_page_url,
                }
                for item in collaterals
            ]
            return {
                "loan_id": loan_id,
                "merchant_id": loan.merchant_id,
                "user_id": loan.user_id,
                "principal_minor": loan.principal_minor,
                "outstanding_minor": loan.outstanding_minor,
                "safety_meter": meter,
                "proof_items": proof_items,
            }
        except Exception:
            logger.exception("Failed getting merchant risk view loan_id=%s", loan_id)
            raise

    def merchant_dashboard(self, merchant_id: str) -> Dict[str, Any]:
        """Return merchant order and plan status dashboard (Feature 13)."""
        try:
            loans = self._query_documents("loans", filters=[("merchant_id", "==", merchant_id)])
            orders = self._query_documents("orders", filters=[("merchant_id", "==", merchant_id)])
            status_counts: Dict[str, int] = {}
            for loan in loans:
                status_name = str(loan.get("status", "UNKNOWN"))
                status_counts[status_name] = status_counts.get(status_name, 0) + 1
            return {
                "merchant_id": merchant_id,
                "loans_total": len(loans),
                "orders_total": len(orders),
                "loan_status_breakdown": status_counts,
                "loans": loans,
                "orders": orders,
            }
        except Exception:
            logger.exception("Failed building merchant dashboard merchant_id=%s", merchant_id)
            raise

    def compute_risk_score(self, loan_id: str) -> Dict[str, Any]:
        """Compute and persist risk score with explainability (Features 21, 24)."""
        try:
            loan = self._load_loan(loan_id)
            meter = self.get_safety_meter(loan_id)
            installments = self._get_installments_for_loan(loan_id)
            missed_count = len([item for item in installments if item.status == InstallmentStatus.MISSED])
            delay_hours = 0.0
            for item in installments:
                if item.paid_at is not None:
                    delay = (item.paid_at - item.due_at).total_seconds() / 3600.0
                    delay_hours += max(0.0, delay)
            avg_delay_hours = delay_hours / max(len(installments), 1)
            safety_ratio = _as_float(meter.get("health_factor"), default=0.0)
            tier = self._risk_tier_from_metrics(safety_ratio, missed_count, avg_delay_hours)

            score = int(max(0, min(1000, (safety_ratio * 500) + (100 - (missed_count * 20)) - (avg_delay_hours * 3))))
            default_probability_bps = {
                RiskTier.LOW: 700,
                RiskTier.MEDIUM: 2400,
                RiskTier.HIGH: 5600,
                RiskTier.CRITICAL: 8300,
            }[tier]
            top_factors = []
            if safety_ratio < 1.2:
                top_factors.append("Low safety ratio from collateral vs debt")
            if missed_count > 0:
                top_factors.append("Recent missed installments")
            if avg_delay_hours > 6:
                top_factors.append("High average payment delay")
            if not top_factors:
                top_factors.append("Strong repayment and collateral behavior")
            recommendation_minor = max(0, int((loan.outstanding_minor * 0.2)))

            risk = RiskScoreModel(
                risk_score_id=self._new_id("risk"),
                user_id=loan.user_id,
                loan_id=loan.loan_id,
                score=score,
                tier=tier,
                default_probability_bps=default_probability_bps,
                top_factors=top_factors[:3],
                recommendation_minor=recommendation_minor,
                model_name="rule_based_v1",
                model_version="v1",
                feature_snapshot={
                    "safety_ratio": round(safety_ratio, 6),
                    "missed_count": missed_count,
                    "avg_delay_hours": round(avg_delay_hours, 4),
                },
                last_evaluated_at=_now_utc(),
                next_review_at=_now_utc() + timedelta(days=1),
            )
            persisted = self._save_risk_score(risk, merge=False)
            self._record_event(
                event_type="RISK_SCORE_COMPUTED",
                actor="risk_engine",
                payload={"loan_id": loan_id, "risk_score_id": persisted.risk_score_id, "tier": persisted.tier.value},
            )
            return persisted.to_firestore()
        except Exception:
            logger.exception("Failed computing risk score loan_id=%s", loan_id)
            raise

    def recommend_dynamic_deposit(self, loan_id: str, use_ml: bool = False) -> Dict[str, Any]:
        """Return dynamic deposit recommendation (Feature 22)."""
        try:
            loan = self._load_loan(loan_id)
            meter = self.get_safety_meter(loan_id)
            risk_snapshot = self.compute_risk_score(loan_id)
            risk_tier = str(risk_snapshot.get("tier", "MEDIUM"))
            collaterals = self._get_collaterals_for_loan(loan_id)
            primary_symbol = collaterals[0].asset_symbol if collaterals else "BNB"
            stable_assets = {"USDT", "USDC", "DAI", "BUSD", "USDP", "TUSD", "FDUSD"}
            collateral_type = "stable" if primary_symbol.upper() in stable_assets else "volatile"
            stress_drop_pct = self._emi_plan_catalog.get_stress_drop_pct(
                plan_id=loan.emi_plan_id,
                collateral_type=collateral_type,
                fallback=0.20,
            )
            inr_price = max(1.0, _as_float(self._protocol_service.get_prices().get("inr_price"), 1.0) / 1e8)
            locked_token = max(0.0, _as_float(meter.get("collateral_value_minor"), 0.0) / inr_price)
            payload = DepositRecommendationRequest(
                plan_amount_inr=float(loan.principal_minor),
                tenure_days=loan.tenure_days,
                risk_tier=risk_tier,
                collateral_token=primary_symbol,
                collateral_type=collateral_type,
                locked_token=locked_token,
                price_inr=inr_price,
                stress_drop_pct=stress_drop_pct,
                fees_buffer_pct=0.03,
                outstanding_debt_inr=float(max(0, loan.outstanding_minor)),
            )
            if use_ml:
                try:
                    recommendation = self._ml_orchestrator.recommend_deposit_ml(payload)
                except Exception:
                    logger.exception("ML recommendation failed; fallback to policy loan_id=%s", loan_id)
                    recommendation = self._ml_orchestrator.recommend_deposit_policy(payload)
                    recommendation["mode"] = "policy_fallback"
            else:
                recommendation = self._ml_orchestrator.recommend_deposit_policy(payload)
            self._record_event(
                event_type="DEPOSIT_RECOMMENDATION_COMPUTED",
                actor="risk_engine",
                payload={"loan_id": loan_id, "mode": recommendation.get("mode"), "risk_tier": risk_tier},
            )
            return recommendation
        except Exception:
            logger.exception("Failed recommending dynamic deposit loan_id=%s", loan_id)
            raise

    def predict_default_and_nudge(self, loan_id: str, installment_id: str) -> Dict[str, Any]:
        """Predict default and generate preventive nudges (Feature 23)."""
        try:
            loan = self._load_loan(loan_id)
            payload = self._get_document("installments", installment_id)
            if payload is None:
                raise ValueError("Installment not found: {0}".format(installment_id))
            installment = InstallmentModel.from_firestore(payload, doc_id=installment_id)
            meter = self.get_safety_meter(loan_id)

            installments = self._get_installments_for_loan(loan_id)
            missed_count = len([item for item in installments if item.status == InstallmentStatus.MISSED])
            on_time_count = len([item for item in installments if item.status == InstallmentStatus.PAID])
            total_count = max(len(installments), 1)
            on_time_ratio = float(on_time_count) / float(total_count)
            avg_days_late = 0.0
            due_diff_days = max(0.0, (installment.due_at - _now_utc()).total_seconds() / 86400.0)

            model_payload = DefaultPredictionInput(
                user_id=loan.user_id,
                plan_id=loan.loan_id,
                installment_id=installment.installment_id,
                cutoff_at=_now_utc(),
                on_time_ratio=max(0.0, min(1.0, on_time_ratio)),
                missed_count_90d=missed_count,
                max_days_late_180d=avg_days_late,
                avg_days_late=avg_days_late,
                days_since_last_late=30.0,
                consecutive_on_time_count=on_time_count,
                plan_amount=max(1.0, float(loan.principal_minor)),
                tenure_days=max(1, loan.tenure_days),
                installment_amount=max(1.0, float(installment.amount_minor)),
                installment_number=installment.sequence_no,
                days_until_due=due_diff_days,
                current_safety_ratio=max(0.0001, _as_float(meter.get("health_factor"), 1.2)),
                distance_to_liquidation_threshold=max(
                    -5.0,
                    _as_float(meter.get("health_factor"), 1.2) - (loan.liquidation_threshold_bps / 10000.0),
                ),
                collateral_type="volatile",
                collateral_volatility_bucket="high",
                topup_count_30d=0,
                topup_recency_days=7.0,
                opened_app_last_7d=1,
                clicked_pay_now_last_7d=0,
                payment_attempt_failed_count=0,
                wallet_age_days=180.0,
                tx_count_30d=8,
                stablecoin_balance_bucket="medium",
            )

            prediction = self._ml_orchestrator.predict_default(model_payload)
            tier = str(prediction.get("tier", "LOW")).upper()
            alert_id = self._new_id("alert")
            alert_payload = {
                "alert_id": alert_id,
                "loan_id": loan_id,
                "installment_id": installment_id,
                "user_id": loan.user_id,
                "tier": tier,
                "actions": prediction.get("actions", []),
                "message": "Payment risk detected. Recommended actions were generated.",
                "created_at": _now_utc(),
                "updated_at": _now_utc(),
            }
            self._set_document("alerts", alert_id, alert_payload, merge=False)
            self._record_event(
                event_type="DEFAULT_NUDGE_CREATED",
                actor="ml_service",
                payload={"loan_id": loan_id, "installment_id": installment_id, "tier": tier},
            )
            return {"prediction": prediction, "nudge": alert_payload}
        except Exception:
            logger.exception("Failed predicting default + nudge loan_id=%s installment_id=%s", loan_id, installment_id)
            raise

    def explainability_panel(self, loan_id: str) -> Dict[str, Any]:
        """Return explainability reasons for approval/risk/deposit recommendation (Feature 24)."""
        try:
            loan = self._load_loan(loan_id)
            meter = self.get_safety_meter(loan_id)
            risk = self.compute_risk_score(loan_id)
            recommendation = self._ml_orchestrator.recommend_deposit_policy(
                DepositRecommendationRequest(
                    plan_amount_inr=float(loan.principal_minor),
                    tenure_days=loan.tenure_days,
                    risk_tier=str(risk.get("tier", "MEDIUM")),
                    collateral_token="BNB",
                    collateral_type="volatile",
                    locked_token=max(0.0, _as_float(meter.get("collateral_value_minor"), 0.0) / 25000.0),
                    price_inr=max(1.0, _as_float(self._protocol_service.get_prices().get("inr_price"), 1.0) / 1e8),
                    outstanding_debt_inr=float(max(0, loan.outstanding_minor)),
                )
            )
            reasons = [
                "Deposit collateral value: {0}".format(meter.get("collateral_value_minor")),
                "Outstanding debt: {0}".format(meter.get("outstanding_minor")),
                "Risk tier: {0}".format(risk.get("tier")),
            ]
            return {
                "loan_id": loan_id,
                "reasons": reasons,
                "risk_score": risk,
                "deposit_recommendation": recommendation,
                "safety_meter": meter,
            }
        except Exception:
            logger.exception("Failed generating explainability panel loan_id=%s", loan_id)
            raise

    def public_proof_page(self, loan_id: str) -> Dict[str, Any]:
        """Build public proof payload with contract refs and event timeline (Feature 25)."""
        try:
            loan = self._load_loan(loan_id)
            collaterals = self._get_collaterals_for_loan(loan_id)
            events = self._query_documents("events", order_by="created_at", limit=200)
            events = [
                item
                for item in events
                if isinstance(item.get("payload"), dict) and item.get("payload", {}).get("loan_id") == loan_id
            ]

            return {
                "loan_id": loan.loan_id,
                "user_id": loan.user_id,
                "merchant_id": loan.merchant_id,
                "contract_addresses": {
                    "price_consumer": self._settings.bsc_contract_address,
                    "opbnb_contract": self._settings.opbnb_contract_address,
                },
                "collateral_proofs": [
                    {
                        "collateral_id": item.collateral_id,
                        "deposit_tx_hash": item.deposit_tx_hash,
                        "vault_address": item.vault_address,
                        "collateral_value_minor": item.collateral_value_minor,
                    }
                    for item in collaterals
                ],
                "timeline": events,
                "safety_meter": self.get_safety_meter(loan.loan_id),
            }
        except Exception:
            logger.exception("Failed building public proof page loan_id=%s", loan_id)
            raise

    def upsert_kyc_status(
        self,
        user_id: str,
        status: str,
        actor: str,
        reject_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create/update KYC lifecycle state for a user profile."""
        try:
            user = self._load_user(user_id)
            try:
                kyc_status = KycStatus(str(status).strip().upper())
            except Exception:
                raise ValueError("Invalid KYC status: {0}".format(status))

            before = user.to_firestore()
            user.kyc_status = kyc_status
            user.kyc_last_updated_at = _now_utc()
            user.kyc_reject_reason = reject_reason if kyc_status == KycStatus.REJECTED else None
            user.kyc_level = 2 if kyc_status == KycStatus.VERIFIED else max(0, min(user.kyc_level, 1))
            updated = self._save_user(user)
            self._record_event(
                event_type="KYC_STATUS_UPDATED",
                actor=actor,
                actor_role=UserRole.SUPPORT.value,
                entity_type="USER",
                entity_id=user_id,
                payload={"user_id": user_id, "kyc_status": kyc_status.value, "reject_reason": reject_reason},
                before=before,
                after=updated.to_firestore(),
            )
            return {
                "user_id": user_id,
                "kyc_status": updated.kyc_status.value,
                "kyc_level": updated.kyc_level,
                "kyc_last_updated_at": updated.kyc_last_updated_at,
                "kyc_reject_reason": updated.kyc_reject_reason,
            }
        except Exception:
            logger.exception("Failed upserting KYC status user_id=%s status=%s", user_id, status)
            raise

    def get_kyc_status(self, user_id: str) -> Dict[str, Any]:
        """Get KYC lifecycle details for one user."""
        try:
            user = self._load_user(user_id)
            return {
                "user_id": user.user_id,
                "kyc_status": user.kyc_status.value,
                "kyc_level": user.kyc_level,
                "kyc_last_updated_at": user.kyc_last_updated_at,
                "kyc_reject_reason": user.kyc_reject_reason,
            }
        except Exception:
            logger.exception("Failed reading KYC status user_id=%s", user_id)
            raise

    def run_aml_screening(
        self,
        user_id: str,
        actor: str,
        provider: str = "mock_sanctions_provider",
        risk_flags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Run AML/sanctions screening and persist the result on user profile."""
        try:
            user = self._load_user(user_id)
            normalized_flags = [str(flag).strip().lower() for flag in (risk_flags or []) if str(flag).strip()]
            if "sanctions" in normalized_flags or "pep" in normalized_flags or "fraud" in normalized_flags:
                screening_status = ScreeningStatus.BLOCKED
            elif "watchlist" in normalized_flags or random() < 0.03:
                screening_status = ScreeningStatus.FLAGGED
            else:
                screening_status = ScreeningStatus.CLEARED

            before = user.to_firestore()
            user.aml_status = screening_status
            user.aml_last_screened_at = _now_utc()
            user.aml_screening_reference = "aml_{0}".format(uuid4().hex[:12])
            updated = self._save_user(user)
            screening_payload = {
                "user_id": user_id,
                "provider": provider,
                "risk_flags": normalized_flags,
                "status": screening_status.value,
                "screened_at": updated.aml_last_screened_at,
                "reference": updated.aml_screening_reference,
            }
            self._record_event(
                event_type="AML_SCREENING_COMPLETED",
                actor=actor,
                entity_type="USER",
                entity_id=user_id,
                actor_role=UserRole.SUPPORT.value,
                payload=screening_payload,
                before=before,
                after=updated.to_firestore(),
            )
            return screening_payload
        except Exception:
            logger.exception("Failed AML screening user_id=%s", user_id)
            raise

    def get_aml_status(self, user_id: str) -> Dict[str, Any]:
        """Get AML/sanctions screening status for one user."""
        try:
            user = self._load_user(user_id)
            return {
                "user_id": user.user_id,
                "aml_status": user.aml_status.value,
                "aml_last_screened_at": user.aml_last_screened_at,
                "aml_screening_reference": user.aml_screening_reference,
            }
        except Exception:
            logger.exception("Failed reading AML status user_id=%s", user_id)
            raise

    def create_wallet_verification_challenge(self, user_id: str, wallet_id: str, chain: str = "bsc") -> Dict[str, Any]:
        """Create one-time sign-message challenge for wallet ownership verification."""
        try:
            if not Web3.is_address(wallet_id):
                raise ValueError("Invalid wallet address format.")
            nonce = secrets.token_hex(16)
            checksum_wallet = Web3.to_checksum_address(wallet_id)
            challenge_payload = {
                "id": "wallet_verify:{0}:{1}".format(user_id, checksum_wallet.lower()),
                "user_id": user_id,
                "wallet_id": checksum_wallet,
                "chain": chain.lower(),
                "nonce": nonce,
                "issued_at": _now_utc(),
                "expires_at": _now_utc() + timedelta(minutes=10),
                "consumed": False,
            }
            message = (
                "PingMasters wallet verification\n"
                "user_id={0}\n"
                "wallet={1}\n"
                "chain={2}\n"
                "nonce={3}"
            ).format(user_id, checksum_wallet, chain.lower(), nonce)
            challenge_payload["message"] = message
            self._set_document("settings", challenge_payload["id"], challenge_payload, merge=False)
            return {
                "user_id": user_id,
                "wallet_id": checksum_wallet,
                "chain": chain.lower(),
                "message": message,
                "nonce": nonce,
                "expires_at": challenge_payload["expires_at"],
            }
        except Exception:
            logger.exception("Failed creating wallet verification challenge user_id=%s wallet=%s", user_id, wallet_id)
            raise

    def verify_wallet_signature(
        self,
        user_id: str,
        wallet_id: str,
        signature: str,
        chain: str = "bsc",
    ) -> Dict[str, Any]:
        """Verify signed challenge and mark wallet as verified for collateral operations."""
        try:
            checksum_wallet = Web3.to_checksum_address(wallet_id)
            challenge_id = "wallet_verify:{0}:{1}".format(user_id, checksum_wallet.lower())
            challenge = self._get_document("settings", challenge_id)
            if challenge is None:
                raise ValueError("Wallet verification challenge not found.")
            if bool(challenge.get("consumed")):
                raise ValueError("Wallet verification challenge already consumed.")
            expires_at = challenge.get("expires_at")
            if isinstance(expires_at, datetime) and expires_at < _now_utc():
                raise ValueError("Wallet verification challenge is expired.")

            message = str(challenge.get("message", ""))
            signed = encode_defunct(text=message)
            recovered_wallet = Web3.to_checksum_address(
                Web3().eth.account.recover_message(signed, signature=signature)
            )
            if recovered_wallet != checksum_wallet:
                raise ValueError("Signature verification failed for wallet ownership.")

            user = self._load_user(user_id)
            before = user.to_firestore()
            if checksum_wallet.lower() not in user.verified_wallets:
                user.verified_wallets.append(checksum_wallet.lower())
                user.verified_wallets = sorted(set(user.verified_wallets))
            user.wallet_verified_at = _now_utc()
            user.wallet_verification_chain = chain.lower()
            updated = self._save_user(user)
            challenge["consumed"] = True
            challenge["consumed_at"] = _now_utc()
            self._set_document("settings", challenge_id, challenge, merge=True)
            self._record_event(
                event_type="WALLET_VERIFIED",
                actor=user_id,
                entity_type="USER",
                entity_id=user_id,
                payload={"wallet_id": checksum_wallet, "chain": chain.lower()},
                before=before,
                after=updated.to_firestore(),
            )
            return {
                "user_id": user_id,
                "wallet_id": checksum_wallet,
                "verified": True,
                "wallet_verified_at": updated.wallet_verified_at,
                "verified_wallets": updated.verified_wallets,
            }
        except Exception:
            logger.exception("Failed verifying wallet signature user_id=%s wallet=%s", user_id, wallet_id)
            raise

    def get_verified_wallets(self, user_id: str) -> Dict[str, Any]:
        """Get verified wallet list for one user."""
        try:
            user = self._load_user(user_id)
            return {
                "user_id": user.user_id,
                "verified_wallets": user.verified_wallets,
                "wallet_verified_at": user.wallet_verified_at,
                "wallet_verification_chain": user.wallet_verification_chain,
            }
        except Exception:
            logger.exception("Failed reading verified wallets user_id=%s", user_id)
            raise

    def list_collateral_asset_policies(self) -> Dict[str, Any]:
        """List configured collateral asset policies."""
        try:
            policies = self._get_setting_value("collateral_asset_policies", self._default_asset_policies())
            return {"total": len(policies), "policies": policies}
        except Exception:
            logger.exception("Failed listing collateral policies.")
            raise

    def update_collateral_asset_policy(self, asset_symbol: str, policy: Dict[str, Any], actor: str) -> Dict[str, Any]:
        """Create/update one collateral asset policy."""
        try:
            symbol = asset_symbol.strip().upper()
            if not symbol:
                raise ValueError("asset_symbol is required.")
            policies = self._get_setting_value("collateral_asset_policies", self._default_asset_policies())
            merged_policy = dict(policy)
            merged_policy["asset_symbol"] = symbol
            merged_policy.setdefault("enabled", True)
            merged_policy.setdefault("ltv_bps", 7000)
            merged_policy.setdefault("liquidation_threshold_bps", 8500)
            merged_policy.setdefault("liquidation_penalty_bps", 700)
            merged_policy.setdefault("min_deposit_minor", 1)
            merged_policy.setdefault("decimals", 18)
            if int(merged_policy["ltv_bps"]) >= int(merged_policy["liquidation_threshold_bps"]):
                raise ValueError("ltv_bps must be lower than liquidation_threshold_bps")
            policies[symbol] = merged_policy
            self._put_setting_value("collateral_asset_policies", policies, actor=actor)
            self._record_event(
                event_type="COLLATERAL_POLICY_UPDATED",
                actor=actor,
                actor_role=UserRole.ADMIN.value,
                entity_type="ASSET_POLICY",
                entity_id=symbol,
                payload={"asset_symbol": symbol, "policy": merged_policy},
            )
            return merged_policy
        except Exception:
            logger.exception("Failed updating collateral policy asset=%s", asset_symbol)
            raise

    def get_dispute_pause_rules(self) -> Dict[str, Dict[str, Any]]:
        """Get category-based dispute pause configuration."""
        defaults: Dict[str, Dict[str, Any]] = {}
        for category in DisputeCategory:
            defaults[category.value] = {
                "pause_penalties": True,
                "pause_liquidation": True if category.value in RISKY_DISPUTE_CATEGORIES else False,
                "pause_hours": 168,
            }
        return self._get_setting_value("dispute_pause_rules", defaults)

    def update_dispute_pause_rule(
        self,
        category: str,
        pause_penalties: bool,
        pause_liquidation: bool,
        pause_hours: int,
        actor: str,
    ) -> Dict[str, Any]:
        """Update dispute pause policy for one category."""
        try:
            normalized_category = str(category).strip().upper()
            if normalized_category not in {item.value for item in DisputeCategory}:
                raise ValueError("Invalid dispute category: {0}".format(category))
            if pause_hours <= 0:
                raise ValueError("pause_hours must be > 0")
            rules = self.get_dispute_pause_rules()
            rules[normalized_category] = {
                "pause_penalties": bool(pause_penalties),
                "pause_liquidation": bool(pause_liquidation),
                "pause_hours": int(pause_hours),
            }
            self._put_setting_value("dispute_pause_rules", rules, actor=actor)
            self._record_event(
                event_type="DISPUTE_PAUSE_RULE_UPDATED",
                actor=actor,
                actor_role=UserRole.ADMIN.value,
                entity_type="DISPUTE_POLICY",
                entity_id=normalized_category,
                payload=rules[normalized_category],
            )
            return {"category": normalized_category, "rule": rules[normalized_category]}
        except Exception:
            logger.exception("Failed updating dispute pause rule category=%s", category)
            raise

    def add_dispute_evidence(
        self,
        dispute_id: str,
        actor: str,
        file_name: str,
        file_url: str,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Attach evidence metadata to an existing dispute."""
        try:
            dispute = self._get_document("disputes", dispute_id)
            if dispute is None:
                raise ValueError("Dispute not found: {0}".format(dispute_id))
            evidence = list(dispute.get("evidence", []))
            evidence_item = {
                "evidence_id": self._new_id("evd"),
                "file_name": file_name,
                "file_url": file_url,
                "notes": notes,
                "uploaded_by": actor,
                "uploaded_at": _now_utc(),
            }
            evidence.append(evidence_item)
            dispute["evidence"] = evidence
            dispute["updated_at"] = _now_utc()
            self._set_document("disputes", dispute_id, dispute, merge=True)
            self._record_event(
                event_type="DISPUTE_EVIDENCE_ADDED",
                actor=actor,
                entity_type="DISPUTE",
                entity_id=dispute_id,
                payload={"evidence_id": evidence_item["evidence_id"], "file_name": file_name},
            )
            return {"dispute_id": dispute_id, "evidence": evidence_item}
        except Exception:
            logger.exception("Failed adding dispute evidence dispute_id=%s", dispute_id)
            raise

    def get_disputes_by_loan(self, loan_id: str) -> Dict[str, Any]:
        """List disputes linked to one loan."""
        try:
            disputes = self._query_documents("disputes", filters=[("loan_id", "==", loan_id)], order_by="opened_at")
            return {"loan_id": loan_id, "total": len(disputes), "disputes": disputes}
        except Exception:
            logger.exception("Failed listing disputes loan_id=%s", loan_id)
            raise

    def transition_loan_state(self, loan_id: str, new_status: str, actor: str, reason: str = "") -> Dict[str, Any]:
        """Transition loan state using explicit backend-enforced state machine."""
        try:
            loan = self._load_loan(loan_id)
            before = loan.to_firestore()
            target_status = LoanStatus(str(new_status).strip().upper())
            self._assert_allowed_transition(loan.status, target_status)
            loan.status = target_status
            if target_status in {LoanStatus.DISPUTE_OPEN, LoanStatus.DISPUTED} and loan.paused_penalties_until is None:
                loan.paused_penalties_until = _now_utc() + timedelta(days=7)
            loan.updated_at = _now_utc()
            updated = self._save_loan(loan, merge=False)
            self._record_event(
                event_type="LOAN_STATE_TRANSITIONED",
                actor=actor,
                entity_type="LOAN",
                entity_id=loan_id,
                payload={
                    "loan_id": loan_id,
                    "from_status": before.get("status"),
                    "to_status": target_status.value,
                    "reason": reason,
                },
                before=before,
                after=updated.to_firestore(),
            )
            return {"loan_id": loan_id, "from_status": before.get("status"), "to_status": target_status.value}
        except Exception:
            logger.exception("Failed transitioning loan state loan_id=%s new_status=%s", loan_id, new_status)
            raise

    def release_collateral(self, loan_id: str, actor: str) -> Dict[str, Any]:
        """Release unlocked collateral after closure/refund reconciliation."""
        try:
            loan = self._load_loan(loan_id)
            if loan.status not in {LoanStatus.CLOSED, LoanStatus.CANCELLED, LoanStatus.DEFAULTED}:
                raise ValueError("Collateral release is allowed only for closed/cancelled/defaulted loans.")
            collaterals = self._get_collaterals_for_loan(loan_id)
            releases: List[Dict[str, Any]] = []
            released_total = 0
            for collateral in collaterals:
                available_minor = max(0, collateral.collateral_value_minor - collateral.recovered_minor)
                if available_minor <= 0:
                    continue
                collateral.status = CollateralStatus.RELEASED
                collateral.recovered_minor += available_minor
                collateral.updated_at = _now_utc()
                updated_collateral = self._save_collateral(collateral, merge=False)
                released_total += available_minor
                releases.append(
                    {
                        "collateral_id": updated_collateral.collateral_id,
                        "released_minor": available_minor,
                        "asset_symbol": updated_collateral.asset_symbol,
                    }
                )
            self._record_event(
                event_type="COLLATERAL_RELEASED",
                actor=actor,
                entity_type="LOAN",
                entity_id=loan_id,
                payload={"loan_id": loan_id, "released_total_minor": released_total, "releases": releases},
            )
            return {"loan_id": loan_id, "released_total_minor": released_total, "releases": releases}
        except Exception:
            logger.exception("Failed releasing collateral loan_id=%s", loan_id)
            raise

    def close_loan(self, loan_id: str, actor: str, force: bool = False) -> Dict[str, Any]:
        """Close loan when all dues are settled and collateral can be reconciled."""
        try:
            loan = self._load_loan(loan_id)
            if not force and loan.outstanding_minor > 0:
                raise ValueError("Loan cannot be closed while outstanding amount is pending.")
            self.transition_loan_state(loan_id=loan_id, new_status=LoanStatus.CLOSED.value, actor=actor, reason="Closure")
            release = self.release_collateral(loan_id=loan_id, actor=actor)
            self._record_event(
                event_type="LOAN_CLOSED",
                actor=actor,
                entity_type="LOAN",
                entity_id=loan_id,
                payload={"loan_id": loan_id, "force": force, "release_summary": release},
            )
            return {"loan_id": loan_id, "status": LoanStatus.CLOSED.value, "release": release}
        except Exception:
            logger.exception("Failed closing loan loan_id=%s", loan_id)
            raise

    def cancel_pre_settlement_order(self, loan_id: str, actor: str, reason: str) -> Dict[str, Any]:
        """Cancel pre-settlement loan/order and free reserved collateral."""
        try:
            loan = self._load_loan(loan_id)
            orders = self._query_documents("orders", filters=[("loan_id", "==", loan_id)], order_by="created_at")
            if not orders:
                raise ValueError("No order exists for loan: {0}".format(loan_id))
            order = dict(orders[-1])
            settlement_status = str(order.get("settlement_status", SettlementStatus.PENDING.value)).upper()
            if settlement_status not in {SettlementStatus.PENDING.value, SettlementStatus.PROCESSING.value}:
                raise ValueError("Order can only be cancelled before settlement is finalized.")
            order["status"] = "CANCELLED"
            order["settlement_status"] = SettlementStatus.REVERSED.value
            order["cancel_reason"] = reason
            order["updated_at"] = _now_utc()
            order_id = str(order.get("id") or order.get("order_id"))
            self._set_document("orders", order_id, order, merge=True)
            self.transition_loan_state(loan_id=loan.loan_id, new_status=LoanStatus.CANCELLED.value, actor=actor, reason=reason)
            release = self.release_collateral(loan_id=loan.loan_id, actor=actor)
            self._record_event(
                event_type="PRE_SETTLEMENT_ORDER_CANCELLED",
                actor=actor,
                entity_type="ORDER",
                entity_id=order_id,
                payload={"loan_id": loan_id, "order_id": order_id, "reason": reason},
            )
            return {"loan_id": loan_id, "order": order, "release": release}
        except Exception:
            logger.exception("Failed cancelling pre-settlement order loan_id=%s", loan_id)
            raise

    def apply_refund_adjustment(
        self,
        loan_id: str,
        actor: str,
        refund_amount_minor: int,
        reason: str,
    ) -> Dict[str, Any]:
        """Apply merchant refund against principal/outstanding and recompute schedule."""
        try:
            if refund_amount_minor <= 0:
                raise ValueError("refund_amount_minor must be > 0")
            loan = self._load_loan(loan_id)
            before = loan.to_firestore()
            adjustment = min(int(refund_amount_minor), int(loan.outstanding_minor))
            loan.outstanding_minor = max(0, loan.outstanding_minor - adjustment)
            loan.principal_minor = max(0, loan.principal_minor - adjustment)
            loan.updated_at = _now_utc()
            if loan.outstanding_minor == 0:
                loan.status = LoanStatus.CLOSED
            updated_loan = self._save_loan(loan, merge=False)
            installments = self._get_installments_for_loan(loan_id)
            remaining_installments = [item for item in installments if item.status != InstallmentStatus.PAID]
            if remaining_installments:
                deduction_per_installment = adjustment // len(remaining_installments)
                remainder = adjustment % len(remaining_installments)
                for item in remaining_installments:
                    deduction = deduction_per_installment + (1 if remainder > 0 else 0)
                    remainder = max(0, remainder - 1)
                    item.amount_minor = max(0, item.amount_minor - deduction)
                    item.updated_at = _now_utc()
                    self._save_installment(item, merge=False)
            self._record_ledger_entry(
                loan_id=loan_id,
                user_id=loan.user_id,
                entry_type="REFUND_ADJUSTMENT",
                amount_minor=adjustment,
                currency=loan.currency,
                metadata={"reason": reason},
            )
            self._record_event(
                event_type="LOAN_REFUND_ADJUSTED",
                actor=actor,
                entity_type="LOAN",
                entity_id=loan_id,
                payload={"refund_amount_minor": refund_amount_minor, "applied_minor": adjustment, "reason": reason},
                before=before,
                after=updated_loan.to_firestore(),
            )
            response = {"loan": updated_loan.to_firestore(), "refund_applied_minor": adjustment}
            if updated_loan.status == LoanStatus.CLOSED:
                response["release"] = self.release_collateral(loan_id=loan_id, actor=actor)
            return response
        except Exception:
            logger.exception("Failed applying refund adjustment loan_id=%s", loan_id)
            raise

    def _persist_payment_attempt(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Store payment attempt details."""
        payment_id = str(payload.get("payment_attempt_id") or self._new_id("pay"))
        payload["payment_attempt_id"] = payment_id
        payload.setdefault("created_at", _now_utc())
        payload["updated_at"] = _now_utc()
        self._set_document("payments", payment_id, payload, merge=False)
        return payload

    def _load_installment(self, installment_id: str) -> InstallmentModel:
        """Load installment by identifier."""
        payload = self._get_document("installments", installment_id)
        if payload is None:
            raise ValueError("Installment not found: {0}".format(installment_id))
        return InstallmentModel.from_firestore(payload, doc_id=installment_id)

    def pay_installment(
        self,
        loan_id: str,
        installment_id: str,
        amount_minor: int,
        actor: str,
        payment_ref: Optional[str] = None,
        success: bool = True,
        failure_reason: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Pay one installment and update schedule/loan balances."""
        try:
            cached = self._check_idempotency("pay_installment", idempotency_key=idempotency_key)
            if cached is not None:
                return cached
            if amount_minor <= 0:
                raise ValueError("amount_minor must be > 0")
            loan = self._load_loan(loan_id)
            installment = self._load_installment(installment_id)
            if installment.loan_id != loan_id:
                raise ValueError("installment does not belong to loan.")
            pending_minor = max(
                0,
                installment.amount_minor + installment.late_fee_minor - installment.paid_minor,
            )
            paid_minor = min(pending_minor, int(amount_minor))
            payment_attempt = self._persist_payment_attempt(
                {
                    "loan_id": loan_id,
                    "installment_id": installment_id,
                    "user_id": loan.user_id,
                    "amount_minor": int(amount_minor),
                    "paid_minor": int(paid_minor if success else 0),
                    "currency": loan.currency,
                    "status": "SUCCESS" if success else "FAILED",
                    "failure_reason": failure_reason,
                    "payment_ref": payment_ref,
                    "retry_count": 0,
                }
            )
            if not success:
                self._record_event(
                    event_type="INSTALLMENT_PAYMENT_FAILED",
                    actor=actor,
                    entity_type="INSTALLMENT",
                    entity_id=installment_id,
                    payload={
                        "loan_id": loan_id,
                        "installment_id": installment_id,
                        "failure_reason": failure_reason,
                        "payment_attempt_id": payment_attempt["payment_attempt_id"],
                    },
                )
                response = {
                    "payment_attempt": payment_attempt,
                    "loan": loan.to_firestore(),
                    "installment": installment.to_firestore(),
                }
                self._store_idempotency("pay_installment", idempotency_key=idempotency_key, response=response)
                return response

            installment.paid_minor += int(paid_minor)
            installment.paid_at = _now_utc()
            installment.payment_ref = payment_ref or payment_attempt["payment_attempt_id"]
            installment.status = (
                InstallmentStatus.PAID
                if installment.paid_minor >= installment.amount_minor + installment.late_fee_minor
                else InstallmentStatus.DUE
            )
            installment.updated_at = _now_utc()
            updated_installment = self._save_installment(installment, merge=False)

            loan.paid_minor += int(paid_minor)
            loan.outstanding_minor = max(0, loan.outstanding_minor - int(paid_minor))
            if loan.outstanding_minor == 0:
                loan.status = LoanStatus.CLOSED
            elif loan.status in {LoanStatus.OVERDUE, LoanStatus.GRACE, LoanStatus.DELINQUENT}:
                loan.status = LoanStatus.ACTIVE
            loan.updated_at = _now_utc()
            updated_loan = self._save_loan(loan, merge=False)
            self._record_ledger_entry(
                loan_id=loan_id,
                user_id=loan.user_id,
                entry_type="INSTALLMENT_PAYMENT",
                amount_minor=int(paid_minor),
                currency=loan.currency,
                reference_id=payment_attempt["payment_attempt_id"],
                metadata={"installment_id": installment_id},
            )
            if updated_installment.status == InstallmentStatus.PAID and self._user_repository is not None:
                user = self._load_user(loan.user_id)
                user.on_time_payment_count += 1
                self._save_user(user)

            response: Dict[str, Any] = {
                "payment_attempt": payment_attempt,
                "loan": updated_loan.to_firestore(),
                "installment": updated_installment.to_firestore(),
            }
            if updated_loan.status == LoanStatus.CLOSED:
                response["release"] = self.release_collateral(loan_id=loan_id, actor=actor)
            self._record_event(
                event_type="INSTALLMENT_PAYMENT_SUCCESS",
                actor=actor,
                entity_type="INSTALLMENT",
                entity_id=installment_id,
                payload={
                    "loan_id": loan_id,
                    "installment_id": installment_id,
                    "paid_minor": int(paid_minor),
                    "payment_attempt_id": payment_attempt["payment_attempt_id"],
                },
            )
            self._store_idempotency("pay_installment", idempotency_key=idempotency_key, response=response)
            return response
        except Exception:
            logger.exception("Failed paying installment loan_id=%s installment_id=%s", loan_id, installment_id)
            raise

    def pay_now(
        self,
        loan_id: str,
        amount_minor: int,
        actor: str,
        payment_ref: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply a pay-now amount across due/unpaid installments in sequence."""
        try:
            cached = self._check_idempotency("pay_now", idempotency_key=idempotency_key)
            if cached is not None:
                return cached
            if amount_minor <= 0:
                raise ValueError("amount_minor must be > 0")
            self._load_loan(loan_id)
            remaining = int(amount_minor)
            payment_results: List[Dict[str, Any]] = []
            for installment in self._get_installments_for_loan(loan_id):
                if remaining <= 0:
                    break
                if installment.status == InstallmentStatus.PAID:
                    continue
                pending = max(0, installment.amount_minor + installment.late_fee_minor - installment.paid_minor)
                if pending <= 0:
                    continue
                applied = min(remaining, pending)
                result = self.pay_installment(
                    loan_id=loan_id,
                    installment_id=installment.installment_id,
                    amount_minor=applied,
                    actor=actor,
                    payment_ref=payment_ref,
                    success=True,
                )
                payment_results.append(result)
                remaining -= applied
            updated_loan = self._load_loan(loan_id)
            response = {
                "loan": updated_loan.to_firestore(),
                "paid_minor": int(amount_minor - remaining),
                "unapplied_minor": int(remaining),
                "payment_results": payment_results,
            }
            self._store_idempotency("pay_now", idempotency_key=idempotency_key, response=response)
            return response
        except Exception:
            logger.exception("Failed pay-now flow loan_id=%s", loan_id)
            raise

    def retry_failed_payment(self, loan_id: str, installment_id: str, actor: str) -> Dict[str, Any]:
        """Retry last failed payment attempt for one installment."""
        try:
            attempts = self._query_documents(
                "payments",
                filters=[
                    ("loan_id", "==", loan_id),
                    ("installment_id", "==", installment_id),
                    ("status", "==", "FAILED"),
                ],
                order_by="created_at",
            )
            if not attempts:
                raise ValueError("No failed payment attempts found for this installment.")
            last_attempt = dict(attempts[-1])
            retry_count = int(last_attempt.get("retry_count", 0)) + 1
            amount_minor = int(last_attempt.get("amount_minor", 0))
            if amount_minor <= 0:
                raise ValueError("Invalid amount in previous failed attempt.")
            result = self.pay_installment(
                loan_id=loan_id,
                installment_id=installment_id,
                amount_minor=amount_minor,
                actor=actor,
                payment_ref=str(last_attempt.get("payment_ref") or ""),
                success=True,
            )
            last_attempt["retry_count"] = retry_count
            last_attempt["retry_completed_at"] = _now_utc()
            payment_attempt_id = str(last_attempt.get("id") or last_attempt.get("payment_attempt_id"))
            self._set_document("payments", payment_attempt_id, last_attempt, merge=True)
            return {"retry_count": retry_count, "result": result}
        except Exception:
            logger.exception("Failed retrying payment loan_id=%s installment_id=%s", loan_id, installment_id)
            raise

    def process_razorpay_webhook(
        self,
        event_type: str,
        payload: Dict[str, Any],
        signature: str,
        raw_body: str,
    ) -> Dict[str, Any]:
        """Process Razorpay webhooks with signature validation and idempotency."""
        try:
            secret = str(self._settings.razorpay_key_secret or "")
            if not secret:
                raise ValueError("Razorpay key secret is not configured.")
            computed_signature = hmac.new(
                secret.encode("utf-8"),
                raw_body.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(computed_signature, signature):
                raise ValueError("Invalid Razorpay webhook signature.")

            event_id = str(payload.get("event_id") or payload.get("id") or self._new_id("wbh"))
            idempotency_cached = self._check_idempotency("razorpay_webhook", idempotency_key=event_id)
            if idempotency_cached is not None:
                return {"processed": True, "idempotent_replay": True, "result": idempotency_cached}

            data_object = payload.get("payload", {}).get("payment", {}).get("entity", {})
            order_id = str(data_object.get("order_id") or "")
            if order_id:
                order = self._get_document("orders", order_id)
                if order is not None:
                    if event_type in {"payment.captured", "order.paid"}:
                        order["settlement_status"] = SettlementStatus.PAID.value
                        order["status"] = "PAID_UPFRONT"
                    elif event_type in {"payment.failed"}:
                        order["settlement_status"] = SettlementStatus.FAILED.value
                        order["status"] = "SETTLEMENT_FAILED"
                    order["updated_at"] = _now_utc()
                    self._set_document("orders", order_id, order, merge=True)

            webhook_record = {
                "webhook_id": event_id,
                "event_type": event_type,
                "payload": payload,
                "processed_at": _now_utc(),
                "signature_verified": True,
            }
            self._set_document("settings", "razorpay_webhook:{0}".format(event_id), webhook_record, merge=False)
            self._record_event(
                event_type="RAZORPAY_WEBHOOK_PROCESSED",
                actor="razorpay",
                entity_type="WEBHOOK",
                entity_id=event_id,
                payload={"event_type": event_type, "order_id": order_id},
            )
            response = {"processed": True, "event_id": event_id, "order_id": order_id}
            self._store_idempotency("razorpay_webhook", idempotency_key=event_id, response=response)
            return response
        except Exception:
            logger.exception("Failed processing Razorpay webhook event_type=%s", event_type)
            raise

    def apply_late_fee(self, loan_id: str, installment_id: str, actor: str) -> Dict[str, Any]:
        """Apply late fee after grace expiry and update loan penalty ledger."""
        try:
            preview = self.preview_late_fee(loan_id=loan_id, installment_id=installment_id)
            late_fee_minor = int(preview.get("late_fee_minor", 0))
            if late_fee_minor <= 0:
                return {"loan_id": loan_id, "installment_id": installment_id, "late_fee_applied_minor": 0}
            loan = self._load_loan(loan_id)
            installment = self._load_installment(installment_id)
            installment.late_fee_minor = late_fee_minor
            installment.status = InstallmentStatus.MISSED
            installment.updated_at = _now_utc()
            updated_installment = self._save_installment(installment, merge=False)
            loan.penalty_accrued_minor += late_fee_minor
            loan.status = LoanStatus.GRACE if preview.get("in_grace", False) else LoanStatus.OVERDUE
            loan.updated_at = _now_utc()
            updated_loan = self._save_loan(loan, merge=False)
            ledger = self._record_ledger_entry(
                loan_id=loan_id,
                user_id=loan.user_id,
                entry_type="LATE_FEE_APPLIED",
                amount_minor=late_fee_minor,
                currency=loan.currency,
                reference_id=installment_id,
            )
            self._record_event(
                event_type="LATE_FEE_APPLIED",
                actor=actor,
                entity_type="INSTALLMENT",
                entity_id=installment_id,
                payload={"loan_id": loan_id, "late_fee_minor": late_fee_minor},
            )
            return {
                "loan": updated_loan.to_firestore(),
                "installment": updated_installment.to_firestore(),
                "late_fee_applied_minor": late_fee_minor,
                "ledger_entry": ledger,
            }
        except Exception:
            logger.exception("Failed applying late fee loan_id=%s installment_id=%s", loan_id, installment_id)
            raise

    def waive_late_fee(self, loan_id: str, installment_id: str, actor: str, reason: str) -> Dict[str, Any]:
        """Waive/reverse applied late fee after dispute or manual review."""
        try:
            loan = self._load_loan(loan_id)
            installment = self._load_installment(installment_id)
            waived_minor = int(max(0, installment.late_fee_minor))
            installment.late_fee_minor = 0
            installment.updated_at = _now_utc()
            updated_installment = self._save_installment(installment, merge=False)
            loan.penalty_accrued_minor = max(0, loan.penalty_accrued_minor - waived_minor)
            loan.updated_at = _now_utc()
            updated_loan = self._save_loan(loan, merge=False)
            ledger = self._record_ledger_entry(
                loan_id=loan_id,
                user_id=loan.user_id,
                entry_type="LATE_FEE_WAIVED",
                amount_minor=waived_minor,
                currency=loan.currency,
                reference_id=installment_id,
                metadata={"reason": reason},
            )
            self._record_event(
                event_type="LATE_FEE_WAIVED",
                actor=actor,
                entity_type="INSTALLMENT",
                entity_id=installment_id,
                payload={"loan_id": loan_id, "waived_minor": waived_minor, "reason": reason},
            )
            return {"loan": updated_loan.to_firestore(), "installment": updated_installment.to_firestore(), "ledger_entry": ledger}
        except Exception:
            logger.exception("Failed waiving late fee loan_id=%s installment_id=%s", loan_id, installment_id)
            raise

    def schedule_reminders(self, loan_id: str, actor: str) -> Dict[str, Any]:
        """Schedule due-date, grace expiry, and delinquency reminders."""
        try:
            loan = self._load_loan(loan_id)
            installments = self._get_installments_for_loan(loan_id)
            reminders: List[Dict[str, Any]] = []
            for item in installments:
                if item.status == InstallmentStatus.PAID:
                    continue
                due_reminder = {
                    "reminder_id": self._new_id("rmn"),
                    "loan_id": loan_id,
                    "installment_id": item.installment_id,
                    "user_id": loan.user_id,
                    "type": "PRE_DUE",
                    "scheduled_at": item.due_at - timedelta(days=1),
                    "status": "PENDING",
                    "message": "Your installment is due soon.",
                    "created_at": _now_utc(),
                    "updated_at": _now_utc(),
                }
                grace_reminder = {
                    "reminder_id": self._new_id("rmn"),
                    "loan_id": loan_id,
                    "installment_id": item.installment_id,
                    "user_id": loan.user_id,
                    "type": "GRACE_EXPIRY",
                    "scheduled_at": item.grace_deadline or (item.due_at + timedelta(hours=loan.grace_window_hours)),
                    "status": "PENDING",
                    "message": "Grace period expires soon. Pay now to avoid additional penalties.",
                    "created_at": _now_utc(),
                    "updated_at": _now_utc(),
                }
                for reminder in [due_reminder, grace_reminder]:
                    self._set_document("reminders", reminder["reminder_id"], reminder, merge=False)
                    reminders.append(reminder)
            self._record_event(
                event_type="REMINDERS_SCHEDULED",
                actor=actor,
                entity_type="LOAN",
                entity_id=loan_id,
                payload={"loan_id": loan_id, "scheduled_count": len(reminders)},
            )
            return {"loan_id": loan_id, "scheduled_count": len(reminders), "reminders": reminders}
        except Exception:
            logger.exception("Failed scheduling reminders loan_id=%s", loan_id)
            raise

    def send_notification(
        self,
        user_id: str,
        channels: List[str],
        template: str,
        context: Dict[str, Any],
        actor: str = "system",
    ) -> Dict[str, Any]:
        """Create notification records using channel-agnostic template payloads."""
        try:
            notification_id = self._new_id("ntf")
            payload = {
                "notification_id": notification_id,
                "user_id": user_id,
                "channels": [str(channel).strip().lower() for channel in channels if str(channel).strip()],
                "template": template,
                "context": context,
                "status": "SENT",
                "delivery_attempts": 1,
                "created_at": _now_utc(),
                "updated_at": _now_utc(),
            }
            self._set_document("notifications", notification_id, payload, merge=False)
            self._record_event(
                event_type="NOTIFICATION_SENT",
                actor=actor,
                entity_type="NOTIFICATION",
                entity_id=notification_id,
                payload={"user_id": user_id, "channels": payload["channels"], "template": template},
            )
            return payload
        except Exception:
            logger.exception("Failed sending notification user_id=%s template=%s", user_id, template)
            raise

    def run_due_reminders(self, actor: str = "scheduler") -> Dict[str, Any]:
        """Execute due reminder jobs and log delivery attempts."""
        try:
            now = _now_utc()
            reminders = self._query_documents("reminders", filters=[("status", "==", "PENDING")], order_by="scheduled_at")
            sent: List[Dict[str, Any]] = []
            for reminder in reminders:
                scheduled_at = reminder.get("scheduled_at")
                if isinstance(scheduled_at, datetime) and scheduled_at > now:
                    continue
                user_id = str(reminder.get("user_id"))
                notification = self.send_notification(
                    user_id=user_id,
                    channels=["email", "whatsapp", "push"],
                    template=str(reminder.get("type", "REMINDER")),
                    context={
                        "loan_id": reminder.get("loan_id"),
                        "installment_id": reminder.get("installment_id"),
                        "message": reminder.get("message"),
                    },
                    actor=actor,
                )
                reminder["status"] = "SENT"
                reminder["sent_at"] = _now_utc()
                reminder["updated_at"] = _now_utc()
                reminder_id = str(reminder.get("id") or reminder.get("reminder_id"))
                self._set_document("reminders", reminder_id, reminder, merge=True)
                sent.append({"reminder_id": reminder_id, "notification_id": notification["notification_id"]})
            return {"processed": len(sent), "deliveries": sent}
        except Exception:
            logger.exception("Failed running due reminders.")
            raise

    def resolve_oracle_price(self, max_age_sec: int = 300, block_on_stale: bool = True) -> Dict[str, Any]:
        """Resolve price from primary source with fallback and stale guard."""
        try:
            prices = self._protocol_service.get_prices()
            age = self._oracle_age_sec()
            fallback = self._get_setting_value("oracle_fallback_prices", {"usd_price": 30000, "inr_price": 2500000})
            stale = age is None or age > max_age_sec
            if stale and block_on_stale:
                return {
                    "healthy": False,
                    "stale": True,
                    "reason": "Oracle data is stale.",
                    "age_sec": age,
                    "max_age_sec": max_age_sec,
                    "selected": "none",
                }
            if stale:
                return {
                    "healthy": True,
                    "stale": True,
                    "selected": "fallback",
                    "prices": fallback,
                    "age_sec": age,
                    "max_age_sec": max_age_sec,
                }
            return {"healthy": True, "stale": False, "selected": "primary", "prices": prices, "age_sec": age}
        except Exception:
            logger.exception("Failed resolving oracle price.")
            raise

    def run_portfolio_risk_monitor(self, threshold_ratio: float = 1.05) -> Dict[str, Any]:
        """Scan active portfolio loans and flag unhealthy positions."""
        try:
            loans = self._query_documents(
                "loans",
                filters=[("status", "in", [LoanStatus.ACTIVE.value, LoanStatus.GRACE.value, LoanStatus.OVERDUE.value, LoanStatus.DELINQUENT.value])],
            )
            flagged: List[Dict[str, Any]] = []
            for payload in loans:
                loan = LoanModel.from_firestore(payload, doc_id=payload.get("id"))
                meter = self.get_safety_meter(loan.loan_id)
                health_factor = float(meter.get("health_factor", 0.0))
                if health_factor <= threshold_ratio:
                    loan.status = LoanStatus.DELINQUENT
                    loan.updated_at = _now_utc()
                    self._save_loan(loan, merge=False)
                    warning = {
                        "loan_id": loan.loan_id,
                        "user_id": loan.user_id,
                        "health_factor": health_factor,
                        "status": loan.status.value,
                    }
                    flagged.append(warning)
                    self.send_notification(
                        user_id=loan.user_id,
                        channels=["email", "push"],
                        template="RISK_TOPUP_ALERT",
                        context=warning,
                    )
            self._record_event(
                event_type="PORTFOLIO_RISK_MONITOR_RUN",
                actor="risk_monitor",
                entity_type="PORTFOLIO",
                entity_id="bnpl",
                payload={"scanned_loans": len(loans), "flagged_loans": len(flagged), "threshold_ratio": threshold_ratio},
            )
            return {"scanned_loans": len(loans), "flagged_loans": len(flagged), "flags": flagged}
        except Exception:
            logger.exception("Failed running portfolio risk monitor.")
            raise

    def execute_full_liquidation(self, loan_id: str, actor_role: str, notes: str) -> Dict[str, Any]:
        """Escalate to full liquidation and record residual bad debt if any."""
        try:
            loan = self._load_loan(loan_id)
            collaterals = self._get_collaterals_for_loan(loan_id)
            total_available = sum(max(0, item.collateral_value_minor - item.recovered_minor) for item in collaterals)
            needed_minor = int(loan.outstanding_minor + loan.penalty_accrued_minor)
            seized_minor = min(total_available, needed_minor)
            residual_bad_debt_minor = max(0, needed_minor - seized_minor)
            for collateral in collaterals:
                available = max(0, collateral.collateral_value_minor - collateral.recovered_minor)
                if available <= 0:
                    continue
                collateral.recovered_minor += available
                collateral.status = CollateralStatus.PARTIALLY_RECOVERED
                collateral.updated_at = _now_utc()
                self._save_collateral(collateral, merge=False)
            loan.outstanding_minor = residual_bad_debt_minor
            loan.status = LoanStatus.DEFAULTED if residual_bad_debt_minor > 0 else LoanStatus.CLOSED
            loan.updated_at = _now_utc()
            updated_loan = self._save_loan(loan, merge=False)
            liquidation_log = LiquidationLogModel(
                log_id=self._new_id("liq"),
                loan_id=loan.loan_id,
                user_id=loan.user_id,
                collateral_id=collaterals[0].collateral_id if collaterals else "NA",
                triggered_at=_now_utc(),
                trigger_reason="FULL_LIQUIDATION_ESCALATION",
                health_factor_at_trigger=float(self.get_safety_meter(loan_id).get("health_factor", 0.0)),
                missed_amount_minor=int(loan.outstanding_minor),
                penalty_minor=int(loan.penalty_accrued_minor),
                needed_minor=needed_minor,
                seized_minor=seized_minor,
                returned_minor=0,
                merchant_transfer_ref="full_liq_{0}".format(uuid4().hex[:8]),
                tx_hash="0x{0}".format(uuid4().hex),
                action_type=LiquidationActionType.FULL_RECOVERY,
                initiated_by_role=actor_role,
                policy_version="v1",
                notes=notes,
            )
            persisted_log = self._save_liquidation_log(liquidation_log, merge=False)
            self._record_ledger_entry(
                loan_id=loan.loan_id,
                user_id=loan.user_id,
                entry_type="FULL_LIQUIDATION",
                amount_minor=seized_minor,
                currency=loan.currency,
                reference_id=persisted_log.log_id,
                metadata={"residual_bad_debt_minor": residual_bad_debt_minor},
            )
            self._record_event(
                event_type="FULL_LIQUIDATION_EXECUTED",
                actor=actor_role,
                actor_role=actor_role,
                entity_type="LOAN",
                entity_id=loan_id,
                payload={
                    "loan_id": loan_id,
                    "needed_minor": needed_minor,
                    "seized_minor": seized_minor,
                    "residual_bad_debt_minor": residual_bad_debt_minor,
                },
            )
            return {
                "loan": updated_loan.to_firestore(),
                "liquidation_log": persisted_log.to_firestore(),
                "residual_bad_debt_minor": residual_bad_debt_minor,
            }
        except Exception:
            logger.exception("Failed executing full liquidation loan_id=%s", loan_id)
            raise

    def compute_merchant_risk_score(self, merchant_id: str) -> Dict[str, Any]:
        """Compute merchant-side risk score using dispute/refund/settlement signals."""
        try:
            orders = self._query_documents("orders", filters=[("merchant_id", "==", merchant_id)])
            disputes = self._query_documents("disputes", filters=[("merchant_id", "==", merchant_id)])
            total_orders = max(1, len(orders))
            failed_settlements = len(
                [item for item in orders if str(item.get("settlement_status", "")).upper() == SettlementStatus.FAILED.value]
            )
            refund_count = len([item for item in orders if str(item.get("status", "")).upper() == "REFUNDED"])
            dispute_rate = float(len(disputes)) / float(total_orders)
            settlement_failure_rate = float(failed_settlements) / float(total_orders)
            refund_rate = float(refund_count) / float(total_orders)
            score = max(0.0, 1.0 - min(1.0, (dispute_rate * 0.5) + (settlement_failure_rate * 0.3) + (refund_rate * 0.2)))
            tier = "LOW"
            if score < 0.4:
                tier = "HIGH"
            elif score < 0.7:
                tier = "MEDIUM"
            return {
                "merchant_id": merchant_id,
                "merchant_risk_score": round(score, 4),
                "risk_tier": tier,
                "signals": {
                    "dispute_rate": round(dispute_rate, 4),
                    "settlement_failure_rate": round(settlement_failure_rate, 4),
                    "refund_rate": round(refund_rate, 4),
                    "orders_total": len(orders),
                },
            }
        except Exception:
            logger.exception("Failed computing merchant risk score merchant_id=%s", merchant_id)
            raise

    def run_fraud_checks(
        self,
        user_id: str,
        wallet_id: Optional[str] = None,
        device_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run heuristic fraud checks and store abuse flags for review."""
        try:
            flags: List[str] = []
            user_loans = self._query_documents("loans", filters=[("user_id", "==", user_id)])
            recent_loans = [
                item
                for item in user_loans
                if isinstance(item.get("created_at"), datetime)
                and (item["created_at"] >= (_now_utc() - timedelta(hours=1)))
            ]
            if len(recent_loans) >= 3:
                flags.append("rapid_purchase_attempts")
            if wallet_id:
                wallet_lower = wallet_id.strip().lower()
                if not Web3.is_address(wallet_id):
                    flags.append("invalid_wallet_format")
                if self._user_repository is not None:
                    for other_user in self._user_repository.get_active_users():
                        if other_user.user_id == user_id:
                            continue
                        if wallet_lower in (other_user.verified_wallets or []):
                            flags.append("duplicate_wallet_across_users")
                            break
            if device_id and len(device_id.strip()) < 8:
                flags.append("suspicious_device_id")
            status = "BLOCKED" if len(flags) >= 2 else ("FLAGGED" if flags else "CLEAR")
            fraud_payload = {
                "flag_id": self._new_id("frd"),
                "user_id": user_id,
                "wallet_id": wallet_id,
                "device_id": device_id,
                "flags": flags,
                "status": status,
                "created_at": _now_utc(),
                "updated_at": _now_utc(),
            }
            self._set_document("fraud_flags", fraud_payload["flag_id"], fraud_payload, merge=False)
            self._record_event(
                event_type="FRAUD_CHECK_EXECUTED",
                actor="fraud_engine",
                entity_type="USER",
                entity_id=user_id,
                payload={"flags": flags, "status": status},
            )
            return fraud_payload
        except Exception:
            logger.exception("Failed running fraud checks user_id=%s", user_id)
            raise

    def list_ledger_entries(
        self,
        loan_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 200,
    ) -> Dict[str, Any]:
        """List ledger entries by loan/user for reproducible financial views."""
        try:
            filters: List[FilterTuple] = []
            if loan_id:
                filters.append(("loan_id", "==", loan_id))
            if user_id:
                filters.append(("user_id", "==", user_id))
            rows = self._query_documents("ledger", filters=filters or None, order_by="created_at", limit=max(1, min(limit, 1000)))
            return {"total": len(rows), "entries": rows}
        except Exception:
            logger.exception("Failed listing ledger entries loan_id=%s user_id=%s", loan_id, user_id)
            raise

    def compute_kpis(self) -> Dict[str, Any]:
        """Compute product/risk KPI metrics for dashboard reporting."""
        try:
            loans = self._query_documents("loans")
            orders = self._query_documents("orders")
            disputes = self._query_documents("disputes")
            liquidation_logs = self._query_documents("liquidation_logs")
            total_loans = max(1, len(loans))
            approved_count = len(
                [item for item in loans if str(item.get("status")) not in {LoanStatus.CANCELLED.value, LoanStatus.PENDING_KYC.value}]
            )
            default_count = len([item for item in loans if str(item.get("status")) == LoanStatus.DEFAULTED.value])
            overdue_count = len([item for item in loans if str(item.get("status")) in {LoanStatus.OVERDUE.value, LoanStatus.DELINQUENT.value}])
            refunded_count = len([item for item in orders if str(item.get("status", "")).upper() == "REFUNDED"])
            failed_settlements = len([item for item in orders if str(item.get("settlement_status", "")).upper() == SettlementStatus.FAILED.value])
            metrics = {
                "approval_rate": round(float(approved_count) / float(total_loans), 4),
                "default_rate": round(float(default_count) / float(total_loans), 4),
                "late_fee_rate": round(float(overdue_count) / float(total_loans), 4),
                "refund_rate": round(float(refunded_count) / float(max(1, len(orders))), 4),
                "dispute_rate": round(float(len(disputes)) / float(total_loans), 4),
                "liquidation_rate": round(float(len(liquidation_logs)) / float(total_loans), 4),
                "settlement_success_rate": round(
                    float(max(0, len(orders) - failed_settlements)) / float(max(1, len(orders))),
                    4,
                ),
                "counts": {
                    "loans": len(loans),
                    "orders": len(orders),
                    "disputes": len(disputes),
                    "liquidations": len(liquidation_logs),
                },
            }
            return metrics
        except Exception:
            logger.exception("Failed computing KPI metrics.")
            raise

    def enqueue_job(self, job_type: str, payload: Dict[str, Any], run_at: Optional[datetime], actor: str) -> Dict[str, Any]:
        """Add asynchronous job record for deferred execution."""
        try:
            job_id = self._new_id("job")
            job_payload = {
                "job_id": job_id,
                "job_type": job_type,
                "payload": payload,
                "run_at": run_at or _now_utc(),
                "status": "PENDING",
                "attempt_count": 0,
                "created_at": _now_utc(),
                "updated_at": _now_utc(),
            }
            self._set_document("jobs", job_id, job_payload, merge=False)
            self._record_event(
                event_type="JOB_ENQUEUED",
                actor=actor,
                entity_type="JOB",
                entity_id=job_id,
                payload={"job_type": job_type},
            )
            return job_payload
        except Exception:
            logger.exception("Failed enqueuing job job_type=%s", job_type)
            raise

    def run_due_jobs(self, actor: str = "scheduler") -> Dict[str, Any]:
        """Execute due async jobs for retries/reminders/risk scans."""
        try:
            now = _now_utc()
            rows = self._query_documents("jobs", filters=[("status", "==", "PENDING")], order_by="run_at")
            processed: List[Dict[str, Any]] = []
            for row in rows:
                run_at = row.get("run_at")
                if isinstance(run_at, datetime) and run_at > now:
                    continue
                job_type = str(row.get("job_type", "")).upper()
                payload = row.get("payload", {})
                result: Any = None
                if job_type == "REMINDER_SCAN":
                    result = self.run_due_reminders(actor=actor)
                elif job_type == "RISK_SCAN":
                    result = self.run_portfolio_risk_monitor()
                elif job_type == "SETTLEMENT_RETRY":
                    order_id = str(payload.get("order_id", ""))
                    result = self.manual_retry_settlement(order_id=order_id, actor=actor)
                elif job_type == "PAYMENT_RETRY":
                    result = self.retry_failed_payment(
                        loan_id=str(payload.get("loan_id")),
                        installment_id=str(payload.get("installment_id")),
                        actor=actor,
                    )
                else:
                    result = {"status": "SKIPPED", "reason": "Unsupported job type"}
                row["status"] = "DONE"
                row["attempt_count"] = int(row.get("attempt_count", 0)) + 1
                row["result"] = result
                row["updated_at"] = _now_utc()
                job_id = str(row.get("id") or row.get("job_id"))
                self._set_document("jobs", job_id, row, merge=True)
                processed.append({"job_id": job_id, "job_type": job_type, "result": result})
            return {"processed": len(processed), "jobs": processed}
        except Exception:
            logger.exception("Failed running due jobs.")
            raise

    def check_rate_limit(self, key: str, limit: int, window_sec: int) -> Dict[str, Any]:
        """Apply simple in-memory rate limit state for API abuse throttling."""
        try:
            normalized_key = key.strip().lower()
            now_ts = int(_now_utc().timestamp())
            entry = self._rate_limit_cache.get(normalized_key, {"count": 0, "window_start": now_ts})
            elapsed = now_ts - int(entry.get("window_start", now_ts))
            if elapsed >= window_sec:
                entry = {"count": 0, "window_start": now_ts}
            entry["count"] = int(entry.get("count", 0)) + 1
            self._rate_limit_cache[normalized_key] = entry
            allowed = entry["count"] <= limit
            return {
                "allowed": allowed,
                "count": entry["count"],
                "limit": limit,
                "window_sec": window_sec,
                "retry_after_sec": max(0, window_sec - (now_ts - entry["window_start"])),
            }
        except Exception:
            logger.exception("Failed rate-limit evaluation key=%s", key)
            raise

    def onboard_merchant(self, merchant_name: str, actor: str) -> Dict[str, Any]:
        """Create merchant profile and API credentials for merchant platform APIs."""
        try:
            merchant_id = self._new_id("mrc")
            api_key = "pm_{0}".format(secrets.token_urlsafe(24))
            merchant_payload = {
                "merchant_id": merchant_id,
                "name": merchant_name,
                "status": MerchantStatus.ACTIVE.value,
                "api_key": api_key,
                "created_at": _now_utc(),
                "updated_at": _now_utc(),
                "is_deleted": False,
            }
            self._set_document("merchants", merchant_id, merchant_payload, merge=False)
            self._record_event(
                event_type="MERCHANT_ONBOARDED",
                actor=actor,
                actor_role=UserRole.ADMIN.value,
                entity_type="MERCHANT",
                entity_id=merchant_id,
                payload={"merchant_name": merchant_name},
            )
            return merchant_payload
        except Exception:
            logger.exception("Failed onboarding merchant name=%s", merchant_name)
            raise

    def validate_merchant_api_key(self, merchant_id: str, api_key: str) -> Dict[str, Any]:
        """Validate merchant API key and lifecycle status."""
        try:
            merchant = self._get_document("merchants", merchant_id)
            if merchant is None:
                raise ValueError("Merchant not found.")
            is_active = str(merchant.get("status", "")).upper() == MerchantStatus.ACTIVE.value
            is_valid_key = hmac.compare_digest(str(merchant.get("api_key", "")), str(api_key))
            return {"merchant_id": merchant_id, "valid": bool(is_active and is_valid_key), "active": is_active}
        except Exception:
            logger.exception("Failed validating merchant api key merchant_id=%s", merchant_id)
            raise

    def update_merchant_order_status(self, order_id: str, status: str, actor: str, notes: Optional[str] = None) -> Dict[str, Any]:
        """Sync merchant order fulfillment status updates."""
        try:
            order = self._get_document("orders", order_id)
            if order is None:
                raise ValueError("Order not found.")
            normalized = str(status).strip().upper()
            allowed = {"ORDER_CREATED", "FULFILLED", "CANCELLED", "REFUNDED", "FAILED"}
            if normalized not in allowed:
                raise ValueError("Unsupported order status: {0}".format(status))
            order["status"] = normalized
            if normalized == "FAILED":
                order["settlement_status"] = SettlementStatus.FAILED.value
            if normalized == "REFUNDED":
                order["settlement_status"] = SettlementStatus.REVERSED.value
            order["notes"] = notes
            order["updated_at"] = _now_utc()
            self._set_document("orders", order_id, order, merge=True)
            self._record_event(
                event_type="MERCHANT_ORDER_STATUS_UPDATED",
                actor=actor,
                entity_type="ORDER",
                entity_id=order_id,
                payload={"status": normalized, "notes": notes},
            )
            return order
        except Exception:
            logger.exception("Failed updating merchant order status order_id=%s", order_id)
            raise

    def list_merchant_settlements(self, merchant_id: str) -> Dict[str, Any]:
        """List settlement lifecycle records for one merchant."""
        try:
            orders = self._query_documents("orders", filters=[("merchant_id", "==", merchant_id)], order_by="created_at")
            lifecycle = {}
            for order in orders:
                settlement_status = str(order.get("settlement_status", SettlementStatus.PENDING.value))
                lifecycle[settlement_status] = lifecycle.get(settlement_status, 0) + 1
            return {"merchant_id": merchant_id, "total": len(orders), "lifecycle": lifecycle, "orders": orders}
        except Exception:
            logger.exception("Failed listing merchant settlements merchant_id=%s", merchant_id)
            raise

    def manual_waive_penalty(self, loan_id: str, installment_id: str, actor: str, reason: str) -> Dict[str, Any]:
        """Manual override to waive penalty during support review."""
        return self.waive_late_fee(loan_id=loan_id, installment_id=installment_id, actor=actor, reason=reason)

    def manual_force_close(self, loan_id: str, actor: str, reason: str) -> Dict[str, Any]:
        """Manual override to force-close a loan after support/admin review."""
        try:
            response = self.close_loan(loan_id=loan_id, actor=actor, force=True)
            self._record_event(
                event_type="MANUAL_FORCE_CLOSE_EXECUTED",
                actor=actor,
                actor_role=UserRole.ADMIN.value,
                entity_type="LOAN",
                entity_id=loan_id,
                payload={"reason": reason},
            )
            return response
        except Exception:
            logger.exception("Failed manual force close loan_id=%s", loan_id)
            raise

    def manual_retry_settlement(self, order_id: str, actor: str) -> Dict[str, Any]:
        """Manual override to retry failed settlement records."""
        try:
            order = self._get_document("orders", order_id)
            if order is None:
                raise ValueError("Order not found.")
            if str(order.get("settlement_status", "")).upper() != SettlementStatus.FAILED.value:
                raise ValueError("Settlement retry is allowed only for failed settlements.")
            order["settlement_status"] = SettlementStatus.PROCESSING.value
            order["status"] = "RETRYING"
            order["updated_at"] = _now_utc()
            self._set_document("orders", order_id, order, merge=True)
            self._record_event(
                event_type="MANUAL_SETTLEMENT_RETRY_TRIGGERED",
                actor=actor,
                actor_role=UserRole.SUPPORT.value,
                entity_type="ORDER",
                entity_id=order_id,
                payload={"order_id": order_id},
            )
            return order
        except Exception:
            logger.exception("Failed manual settlement retry order_id=%s", order_id)
            raise

    def _get_next_due_at(self, loan_id: str) -> Optional[datetime]:
        """Resolve next unpaid installment due date for one loan."""
        installments = self._get_installments_for_loan(loan_id)
        due_candidates = [item.due_at for item in installments if item.status != InstallmentStatus.PAID]
        if not due_candidates:
            return None
        return min(due_candidates)

    def list_user_loans(self, user_id: str, include_closed: bool = True) -> Dict[str, Any]:
        """Return user loans for dashboard cards."""
        try:
            loans = self._query_documents("loans", filters=[("user_id", "==", user_id)], order_by="created_at")
            if not include_closed:
                loans = [
                    item
                    for item in loans
                    if str(item.get("status")) not in {LoanStatus.CLOSED.value, LoanStatus.CANCELLED.value}
                ]
            summaries = []
            for row in loans:
                summaries.append(
                    {
                        "loan_id": row.get("loan_id"),
                        "status": row.get("status"),
                        "principal_minor": row.get("principal_minor"),
                        "outstanding_minor": row.get("outstanding_minor"),
                        "next_due_at": self._get_next_due_at(str(row.get("loan_id"))),
                        "currency": row.get("currency"),
                    }
                )
            return {"user_id": user_id, "total": len(summaries), "loans": summaries}
        except Exception:
            logger.exception("Failed listing user loans user_id=%s", user_id)
            raise

    def get_loan_detail(self, loan_id: str) -> Dict[str, Any]:
        """Get complete loan detail for user-facing loan screen."""
        try:
            loan = self._load_loan(loan_id)
            meter = self.get_safety_meter(loan_id)
            disputes = self._query_documents("disputes", filters=[("loan_id", "==", loan_id)], order_by="opened_at")
            installments = self._get_installments_for_loan(loan_id)
            fees_minor = int(loan.penalty_accrued_minor)
            return {
                "loan": loan.to_firestore(),
                "next_due_at": self._get_next_due_at(loan_id),
                "collateral_locked_minor": meter.get("collateral_value_minor"),
                "health_factor": meter.get("health_factor"),
                "dispute_status": disputes[-1].get("status") if disputes else None,
                "fees_minor": fees_minor,
                "installment_count": len(installments),
            }
        except Exception:
            logger.exception("Failed getting loan detail loan_id=%s", loan_id)
            raise

    def get_installment_history(self, loan_id: str) -> Dict[str, Any]:
        """Get installment schedule and status history for one loan."""
        try:
            installments = self._get_installments_for_loan(loan_id)
            rows = [item.to_firestore() for item in installments]
            return {"loan_id": loan_id, "total": len(rows), "installments": rows}
        except Exception:
            logger.exception("Failed getting installment history loan_id=%s", loan_id)
            raise

    def get_payment_history(self, loan_id: str, limit: int = 200) -> Dict[str, Any]:
        """Get payment timeline including retries and failure reasons."""
        try:
            rows = self._query_documents(
                "payments",
                filters=[("loan_id", "==", loan_id)],
                order_by="created_at",
                limit=max(1, min(limit, 1000)),
            )
            return {"loan_id": loan_id, "total": len(rows), "payments": rows}
        except Exception:
            logger.exception("Failed getting payment history loan_id=%s", loan_id)
            raise

    def ops_dashboard(self) -> Dict[str, Any]:
        """Return consolidated back-office snapshot for admins/support."""
        try:
            loans = self._query_documents("loans")
            disputes = self._query_documents("disputes")
            failed_payments = self._query_documents("payments", filters=[("status", "==", "FAILED")], limit=100)
            pause_state = self.get_pause_state()
            return {
                "counts": {
                    "users": len(self._user_repository.get_active_users()) if self._user_repository is not None else 0,
                    "loans": len(loans),
                    "disputes_open": len([item for item in disputes if str(item.get("status")) == "OPEN"]),
                    "failed_payments": len(failed_payments),
                },
                "pause_state": pause_state,
                "kpis": self.compute_kpis(),
                "recent_failed_payments": failed_payments[:20],
            }
        except Exception:
            logger.exception("Failed building ops dashboard.")
            raise

    def validate_oracle_guard(self, max_age_sec: int = 300) -> Dict[str, Any]:
        """Validate oracle freshness and return guard status (Feature 17)."""
        try:
            age = self._oracle_age_sec()
            if age is None:
                return {"healthy": False, "reason": "No oracle update found.", "age_sec": None}
            return {"healthy": age <= max_age_sec, "age_sec": age, "max_age_sec": max_age_sec}
        except Exception:
            logger.exception("Failed validating oracle guard.")
            raise

    def get_razorpay_status(self) -> Dict[str, Any]:
        """Return Razorpay integration status for payment-dependent features."""
        try:
            if self._razorpay_service is None:
                return {"enabled": False, "configured": False, "available": False}
            return {
                "enabled": bool(self._razorpay_service.is_enabled),
                "configured": bool(self._razorpay_service.is_configured),
                "available": bool(self._razorpay_service.is_configured),
            }
        except Exception:
            logger.exception("Failed getting Razorpay status.")
            raise

    def get_audit_events(self, limit: int = 100) -> Dict[str, Any]:
        """Return audit trail event logs (Feature 20)."""
        try:
            safe_limit = max(1, min(500, int(limit)))
            events = self._query_documents("events", order_by="created_at", limit=safe_limit)
            return {"total": len(events), "events": events}
        except Exception:
            logger.exception("Failed fetching audit events.")
            raise
