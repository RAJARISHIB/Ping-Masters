"""BNPL feature orchestration service covering borrower, merchant, risk, and audit flows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import logging
import re
from threading import RLock
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from common.emi_plan_catalog import EmiPlanCatalog
from core.config import AppSettings
from core.firebase_client_manager import FirebaseClientManager
from ml.default_schema import DefaultPredictionInput
from ml.deposit_schema import DepositRecommendationRequest
from ml.orchestrator import MlPayloadOrchestrator
from models.collaterals import CollateralModel
from models.enums import (
    CollateralStatus,
    InstallmentStatus,
    LiquidationActionType,
    LoanStatus,
    RiskTier,
)
from models.installments import InstallmentModel
from models.liquidation_logs import LiquidationLogModel
from models.loans import LoanModel
from models.risk_scores import RiskScoreModel
from repositories.firestore_user_repository import FirestoreUserRepository


logger = logging.getLogger(__name__)

FilterTuple = Tuple[str, str, Any]


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


def _orderable_sort_key(value: Any) -> tuple:
    """Return a safe sortable tuple for heterogeneous Firestore values."""
    if value is None:
        return (3, 0.0, "")
    if isinstance(value, bool):
        return (0, float(int(value)), "")
    if isinstance(value, (int, float)):
        return (0, float(value), "")
    if isinstance(value, datetime):
        return (0, value.timestamp(), "")
    return (1, 0.0, str(value))


def _normalize_contact_number(contact: Optional[str]) -> Optional[str]:
    """Normalize and validate customer contact for payment provider constraints."""
    if contact is None:
        return None
    raw_value = str(contact).strip()
    if not raw_value:
        return None
    digits_only = re.sub(r"\D", "", raw_value)
    if len(digits_only) < 10 or len(digits_only) > 15:
        raise ValueError("customer_contact must contain 10 to 15 digits.")
    if len(set(digits_only)) == 1:
        raise ValueError("customer_contact cannot contain the same digit repeated.")
    return digits_only


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
        }

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
            try:
                return self._firebase_manager.query_documents(
                    collection_name=collection_name,
                    filters=filters,
                    order_by=order_by,
                    limit=limit,
                )
            except Exception as exc:
                message = str(exc).lower()
                if order_by and "requires an index" in message:
                    logger.warning(
                        "Firestore composite index missing. Falling back to in-memory sort "
                        "collection=%s order_by=%s",
                        collection_name,
                        order_by,
                    )
                    rows = self._firebase_manager.query_documents(
                        collection_name=collection_name,
                        filters=filters,
                        order_by=None,
                        limit=None,
                    )
                    rows.sort(key=lambda item: _orderable_sort_key(item.get(order_by)))
                    if limit is not None:
                        return rows[: int(limit)]
                    return rows
                raise
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

    def _record_event(self, event_type: str, actor: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Store audit-friendly event log for protocol actions."""
        event_id = self._new_id("evt")
        event_payload = {
            "event_id": event_id,
            "event_type": event_type,
            "actor": actor,
            "payload": payload,
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
            order_by=None,
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
    ) -> Dict[str, Any]:
        """Create BNPL plan and installment schedule (Features 2, 6, 16)."""
        self._ensure_not_paused()
        try:
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
                },
            )

            return {
                "loan": persisted_loan.to_firestore(),
                "installments": [item.to_firestore() for item in persisted_installments],
                "emi_plan": (
                    selected_plan.model_dump()
                    if selected_plan is not None and hasattr(selected_plan, "model_dump")
                    else (selected_plan.dict() if selected_plan is not None else None)
                ),
            }
        except Exception:
            logger.exception("Failed creating BNPL plan user_id=%s merchant_id=%s", user_id, merchant_id)
            raise

    def lock_security_deposit(
        self,
        loan_id: str,
        user_id: str,
        asset_symbol: str,
        deposited_units: float,
        collateral_value_minor: int,
        oracle_price_minor: int,
        vault_address: str,
        chain_id: int,
        deposit_tx_hash: str,
        proof_page_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Lock refundable security deposit in vault (Feature 1)."""
        self._ensure_not_paused()
        try:
            if deposited_units <= 0:
                raise ValueError("deposited_units must be > 0")
            if collateral_value_minor <= 0:
                raise ValueError("collateral_value_minor must be > 0")
            loan = self._load_loan(loan_id)

            collateral = CollateralModel(
                collateral_id=self._new_id("col"),
                user_id=user_id,
                loan_id=loan_id,
                vault_address=vault_address,
                chain_id=chain_id,
                deposit_tx_hash=deposit_tx_hash,
                asset_symbol=asset_symbol.upper(),
                deposited_units=float(deposited_units),
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
                },
            )
            return {"collateral": stored.to_firestore(), "safety_meter": meter}
        except Exception:
            logger.exception("Failed locking security deposit loan_id=%s user_id=%s", loan_id, user_id)
            raise

    def top_up_collateral(
        self,
        collateral_id: str,
        added_units: float,
        added_value_minor: int,
        oracle_price_minor: int,
        topup_tx_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Top-up collateral amount and update safety metrics (Feature 5)."""
        self._ensure_not_paused()
        try:
            collateral = self._load_collateral(collateral_id)
            if added_units <= 0:
                raise ValueError("added_units must be > 0")
            if added_value_minor <= 0:
                raise ValueError("added_value_minor must be > 0")

            collateral.deposited_units += float(added_units)
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
            return {"collateral": updated_collateral.to_firestore(), "safety_meter": meter}
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
            normalized_contact = _normalize_contact_number(customer_contact)
            customer_payload: Dict[str, str] = {"name": customer_name or user_id}
            customer_email_value = (customer_email or "{0}@example.com".format(user_id)).strip()
            if customer_email_value:
                customer_payload["email"] = customer_email_value
            if normalized_contact:
                customer_payload["contact"] = normalized_contact

            link = self._razorpay_service.create_payment_link(
                amount_minor=int(amount_minor),
                currency=currency,
                description="Autopay mandate simulation for loan {0}".format(loan_id),
                customer=customer_payload,
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

    def open_dispute(self, loan_id: str, reason: str, actor: str) -> Dict[str, Any]:
        """Open dispute and freeze penalties (Feature 9)."""
        try:
            loan = self._load_loan(loan_id)
            loan.paused_penalties_until = _now_utc() + timedelta(days=7)
            loan.dispute_state = "OPEN"
            loan.status = LoanStatus.DISPUTE_OPEN
            loan.updated_at = _now_utc()
            updated = self._save_loan(loan, merge=False)
            self._record_event(
                event_type="DISPUTE_OPENED",
                actor=actor,
                payload={"loan_id": loan_id, "reason": reason},
            )
            return {"loan": updated.to_firestore(), "reason": reason}
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
            loan.dispute_state = "RESOLVED"
            loan.paused_penalties_until = _now_utc()
            loan.status = LoanStatus.ACTIVE if restore_active else LoanStatus.CLOSED
            loan.updated_at = _now_utc()
            updated = self._save_loan(loan, merge=False)
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
            )
            return {"loan": updated.to_firestore(), "resolution": resolution, "refund": refund_result}
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
    ) -> Dict[str, Any]:
        """Create merchant settlement/order record (Features 11, 13, 15)."""
        try:
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
            )
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
            loan.status = LoanStatus.OVERDUE if remaining_needed > 0 else LoanStatus.ACTIVE
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
                return {
                    "enabled": False,
                    "configured": False,
                    "available": False,
                    "mode": "disabled",
                    "is_test_mode": False,
                    "key_id_masked": "",
                    "checkout_key_id": "",
                    "api_base_url": "",
                }
            return {
                "enabled": bool(self._razorpay_service.is_enabled),
                "configured": bool(self._razorpay_service.is_configured),
                "available": bool(self._razorpay_service.is_configured),
                "mode": str(getattr(self._razorpay_service, "key_mode", "unknown")),
                "is_test_mode": bool(getattr(self._razorpay_service, "is_test_mode", False)),
                "key_id_masked": str(getattr(self._razorpay_service, "key_id_masked", "")),
                "checkout_key_id": str(getattr(self._razorpay_service, "public_key_id", "")),
                "api_base_url": str(getattr(self._razorpay_service, "api_base_url", "")),
            }
        except Exception:
            logger.exception("Failed getting Razorpay status.")
            raise

    def verify_razorpay_credentials(self) -> Dict[str, Any]:
        """Perform live auth verification using configured Razorpay credentials."""
        try:
            if self._razorpay_service is None:
                raise ValueError("Razorpay integration is not initialized.")
            if not self._razorpay_service.is_configured:
                raise ValueError("Razorpay is not configured.")
            return self._razorpay_service.verify_credentials()
        except Exception:
            logger.exception("Failed verifying Razorpay credentials.")
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

    def get_loans_by_user(self, user_id: str, limit: int = 50) -> Dict[str, Any]:
        """List loans for a user from Firestore (or in-memory when Firebase is disabled)."""
        try:
            safe_limit = max(1, min(200, int(limit)))
            loan_payloads = self._query_documents(
                "loans",
                filters=[("user_id", "==", user_id), ("is_deleted", "==", False)],
                order_by=None,
                limit=safe_limit,
            )
            return {"user_id": user_id, "total": len(loan_payloads), "loans": loan_payloads}
        except Exception:
            logger.exception("Failed listing loans for user_id=%s", user_id)
            raise
