"""ML payload analysis, normalization, and orchestration utilities."""

from datetime import datetime, timezone
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union

from pydantic import BaseModel, ValidationError

from .default_inference import DefaultPredictionInferenceService
from .default_schema import DefaultPredictionInput
from .deposit_inference import DepositRecommendationInferenceService
from .deposit_policy import recommend_deposit_by_policy
from .deposit_schema import DepositRecommendationRequest
from .inference import RiskModelInferenceService
from .orchestration_schema import MlOrchestrationRequest
from .schema import RiskFeatureInput


logger = logging.getLogger(__name__)


def _dig(payload: Dict[str, Any], paths: List[Tuple[str, ...]]) -> Any:
    """Read the first non-null value from multiple nested key paths."""
    for path in paths:
        node: Any = payload
        found = True
        for key in path:
            if isinstance(node, dict) and key in node:
                node = node[key]
                continue
            found = False
            break
        if found and node is not None:
            return node
    return None


def _to_float(value: Any, default: float = 0.0) -> float:
    """Convert value to float with fallback default."""
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    """Convert value to int with fallback default."""
    try:
        if value is None:
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _to_bool_as_int(value: Any, default: int = 0) -> int:
    """Convert value into binary integer (0/1)."""
    if isinstance(value, bool):
        return 1 if value else 0
    numeric_value = _to_int(value, default=default)
    return 1 if numeric_value > 0 else 0


def _safe_iso_to_datetime(value: Any) -> Optional[datetime]:
    """Parse ISO datetime value safely."""
    try:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        text = str(value).strip()
        if not text:
            return None
        text = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        logger.exception("Failed parsing datetime value=%s", value)
        return None


def _model_field_specs(model_cls: Type[BaseModel]) -> List[Dict[str, Any]]:
    """Return required/optional field specification for a Pydantic model."""
    fields: List[Dict[str, Any]] = []
    for name, field in model_cls.__fields__.items():
        try:
            default_value = None if field.required else field.default
            fields.append(
                {
                    "name": name,
                    "required": bool(field.required),
                    "type": str(field.outer_type_),
                    "default": default_value,
                }
            )
        except Exception:
            logger.exception("Failed extracting field spec model=%s field=%s", model_cls.__name__, name)
            continue
    return fields


class MlPayloadOrchestrator:
    """Orchestrates ML payload normalization and model inference flows."""

    def __init__(
        self,
        ml_enabled: bool,
        risk_inference: Optional[RiskModelInferenceService],
        default_inference: Optional[DefaultPredictionInferenceService],
        deposit_inference: Optional[DepositRecommendationInferenceService],
    ) -> None:
        self._ml_enabled = bool(ml_enabled)
        self._risk_inference = risk_inference
        self._default_inference = default_inference
        self._deposit_inference = deposit_inference

    def get_payload_specs(self) -> Dict[str, Any]:
        """Expose payload contracts used by ML model APIs."""
        try:
            return {
                "risk_score_payload": _model_field_specs(RiskFeatureInput),
                "default_prediction_payload": _model_field_specs(DefaultPredictionInput),
                "deposit_recommendation_payload": _model_field_specs(DepositRecommendationRequest),
            }
        except Exception:
            logger.exception("Failed generating payload specs.")
            raise

    def analyze_payload(self, model_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze payload completeness and normalization readiness.

        Args:
            model_type: One of `risk`, `default`, `deposit`.
            payload: Raw payload dictionary.

        Returns:
            Dict[str, Any]: Analysis report including required fields, missing fields,
            normalization status, and normalized payload when valid.
        """
        try:
            normalized_model_type = str(model_type).strip().lower()
            if normalized_model_type not in {"risk", "default", "deposit"}:
                raise ValueError("model_type must be one of: risk, default, deposit")
            if not isinstance(payload, dict):
                raise ValueError("payload must be a JSON object/dictionary")

            model_cls: Type[BaseModel]
            normalize_callable: Callable[[Dict[str, Any]], BaseModel]
            if normalized_model_type == "risk":
                model_cls = RiskFeatureInput
                normalize_callable = self.normalize_risk_payload
            elif normalized_model_type == "default":
                model_cls = DefaultPredictionInput
                normalize_callable = self.normalize_default_payload
            else:
                model_cls = DepositRecommendationRequest
                normalize_callable = self.normalize_deposit_payload

            specs = _model_field_specs(model_cls)
            required_fields = [item["name"] for item in specs if item["required"]]
            optional_fields = [item["name"] for item in specs if not item["required"]]
            payload_keys = sorted(list(payload.keys()))
            provided_direct = [field for field in payload_keys if field in required_fields + optional_fields]
            missing_required_before = [field for field in required_fields if field not in payload_keys]

            report: Dict[str, Any] = {
                "model_type": normalized_model_type,
                "required_fields": required_fields,
                "optional_fields": optional_fields,
                "payload_keys": payload_keys,
                "provided_direct_fields": sorted(provided_direct),
                "missing_required_fields_before_normalization": sorted(missing_required_before),
                "completeness_ratio_before_normalization": round(
                    (len(required_fields) - len(missing_required_before)) / max(len(required_fields), 1),
                    6,
                ),
                "normalization_status": "unknown",
            }

            try:
                normalized = normalize_callable(payload)
                normalized_dict = normalized.dict()
                derived_fields = [field for field in normalized_dict.keys() if field not in payload_keys]
                report["normalization_status"] = "ok"
                report["normalized_payload"] = normalized_dict
                report["derived_or_filled_fields"] = sorted(derived_fields)
                report["missing_required_fields_after_normalization"] = []
            except ValidationError as validation_error:
                report["normalization_status"] = "validation_error"
                report["validation_errors"] = validation_error.errors()
                report["missing_required_fields_after_normalization"] = sorted(
                    {
                        err.get("loc", ["unknown"])[-1]
                        for err in validation_error.errors()
                        if str(err.get("type", "")).endswith("missing")
                    }
                )
            except Exception as exc:
                report["normalization_status"] = "error"
                report["error"] = str(exc)

            return report
        except Exception:
            logger.exception("Payload analysis failed model_type=%s payload=%s", model_type, payload)
            raise

    def build_training_row(
        self,
        model_type: str,
        payload: Dict[str, Any],
        label: Any = None,
    ) -> Dict[str, Any]:
        """Build a normalized training row from raw payload.

        Args:
            model_type: One of `risk`, `default`, `deposit`.
            payload: Raw event payload.
            label: Optional label value to append to the row.

        Returns:
            Dict[str, Any]: Normalized row dictionary with optional label field.
        """
        try:
            normalized_model_type = str(model_type).strip().lower()
            if normalized_model_type == "risk":
                row = self.normalize_risk_payload(payload).dict()
                if label is not None:
                    row["risk_tier"] = str(label).strip().upper()
            elif normalized_model_type == "default":
                row = self.normalize_default_payload(payload).dict()
                if label is not None:
                    row["y_miss_next"] = int(_to_int(label, default=0))
            elif normalized_model_type == "deposit":
                row = self.normalize_deposit_payload(payload).dict()
                if label is not None:
                    row["required_collateral_inr"] = float(_to_float(label, default=0.0))
            else:
                raise ValueError("model_type must be one of: risk, default, deposit")
            return row
        except Exception:
            logger.exception("Failed building training row model_type=%s payload=%s", model_type, payload)
            raise

    def normalize_risk_payload(self, payload: Dict[str, Any]) -> RiskFeatureInput:
        """Normalize raw payload into `RiskFeatureInput`."""
        try:
            plan_amount = _to_float(
                _dig(
                    payload,
                    [
                        ("plan_amount",),
                        ("plan_amount_inr",),
                        ("loan", "plan_amount"),
                        ("loan", "principal"),
                        ("loan", "principal_minor"),
                        ("plan", "amount"),
                    ],
                ),
                default=0.0,
            )
            tenure_days = _to_int(
                _dig(payload, [("tenure_days",), ("loan", "tenure_days"), ("plan", "tenure_days")]),
                default=0,
            )
            installment_count = _to_int(
                _dig(payload, [("installment_count",), ("loan", "installment_count"), ("plan", "installment_count")]),
                default=0,
            )
            installment_amount = _to_float(
                _dig(payload, [("installment_amount",), ("plan", "installment_amount"), ("loan", "installment_amount")]),
                default=0.0,
            )
            if installment_amount <= 0 and plan_amount > 0 and installment_count > 0:
                installment_amount = plan_amount / max(installment_count, 1)

            outstanding_debt = _to_float(
                _dig(
                    payload,
                    [
                        ("outstanding_debt",),
                        ("outstanding_debt_inr",),
                        ("outstanding_minor",),
                        ("loan", "outstanding_debt"),
                        ("loan", "outstanding_minor"),
                    ],
                ),
                default=0.0,
            )
            collateral_value = _to_float(
                _dig(
                    payload,
                    [
                        ("collateral_value",),
                        ("collateral_value_inr",),
                        ("collateral", "value"),
                        ("collateral", "collateral_value_minor"),
                    ],
                ),
                default=0.0,
            )
            safety_ratio = _to_float(_dig(payload, [("safety_ratio",), ("health_factor",)]), default=0.0)
            if safety_ratio <= 0 and outstanding_debt > 0 and collateral_value > 0:
                safety_ratio = collateral_value / outstanding_debt

            on_time_payment_count = _to_float(
                _dig(payload, [("on_time_payment_count",), ("repayment", "on_time_payment_count")]),
                default=0.0,
            )
            total_payment_count = _to_float(
                _dig(
                    payload,
                    [
                        ("total_payment_count",),
                        ("repayment", "total_payment_count"),
                        ("installments_paid",),
                    ],
                ),
                default=0.0,
            )
            on_time_ratio = _to_float(_dig(payload, [("on_time_ratio",)]), default=-1.0)
            if on_time_ratio < 0 and total_payment_count > 0:
                on_time_ratio = max(0.0, min(1.0, on_time_payment_count / total_payment_count))
            if on_time_ratio < 0:
                on_time_ratio = 0.8

            avg_delay_hours = _to_float(_dig(payload, [("avg_delay_hours",)]), default=-1.0)
            if avg_delay_hours < 0:
                avg_days_late = _to_float(_dig(payload, [("avg_days_late",)]), default=0.0)
                avg_delay_hours = max(0.0, avg_days_late * 24.0)

            normalized = RiskFeatureInput(
                safety_ratio=max(0.000001, safety_ratio),
                missed_payment_count=_to_int(
                    _dig(payload, [("missed_payment_count",), ("missed_count_90d",), ("repayment", "missed_payment_count")]),
                    default=0,
                ),
                on_time_ratio=max(0.0, min(1.0, on_time_ratio)),
                avg_delay_hours=max(0.0, avg_delay_hours),
                topup_count_last_30d=_to_int(
                    _dig(payload, [("topup_count_last_30d",), ("topup_count_30d",), ("user", "top_up_count")]),
                    default=0,
                ),
                plan_amount=max(0.000001, plan_amount),
                tenure_days=max(1, tenure_days),
                installment_amount=max(0.000001, installment_amount),
            )
            return normalized
        except ValidationError:
            logger.exception("Risk payload validation failed payload=%s", payload)
            raise
        except Exception:
            logger.exception("Risk payload normalization failed payload=%s", payload)
            raise

    def normalize_default_payload(self, payload: Dict[str, Any]) -> DefaultPredictionInput:
        """Normalize raw payload into `DefaultPredictionInput`."""
        try:
            cutoff_at = _safe_iso_to_datetime(_dig(payload, [("cutoff_at",), ("cutoff_time",)]))
            due_at = _safe_iso_to_datetime(_dig(payload, [("due_at",), ("due_date",), ("installment", "due_at")]))
            days_until_due = _to_float(_dig(payload, [("days_until_due",)]), default=-1.0)
            if days_until_due < 0:
                now = cutoff_at or datetime.now(timezone.utc)
                if due_at is not None:
                    delta = due_at - now
                    days_until_due = max(0.0, delta.total_seconds() / 86400.0)
                else:
                    days_until_due = 2.0

            plan_amount = _to_float(
                _dig(payload, [("plan_amount",), ("plan_amount_inr",), ("loan", "plan_amount"), ("loan", "principal")]),
                default=0.0,
            )
            tenure_days = _to_int(_dig(payload, [("tenure_days",), ("loan", "tenure_days")]), default=30)
            installment_amount = _to_float(
                _dig(payload, [("installment_amount",), ("loan", "installment_amount")]),
                default=0.0,
            )
            if installment_amount <= 0:
                installment_count = _to_int(_dig(payload, [("installment_count",), ("loan", "installment_count")]), default=0)
                if plan_amount > 0 and installment_count > 0:
                    installment_amount = plan_amount / max(installment_count, 1)

            current_safety_ratio = _to_float(
                _dig(payload, [("current_safety_ratio",), ("safety_ratio",), ("health_factor",)]),
                default=1.2,
            )
            distance_threshold = _to_float(
                _dig(payload, [("distance_to_liquidation_threshold",)]),
                default=current_safety_ratio - 1.0,
            )
            collateral_type = str(_dig(payload, [("collateral_type",)]) or "volatile").lower()
            collateral_volatility_bucket = str(
                _dig(payload, [("collateral_volatility_bucket",)])
                or ("low" if collateral_type == "stable" else "high")
            ).lower()

            normalized = DefaultPredictionInput(
                user_id=_dig(payload, [("user_id",)]),
                plan_id=_dig(payload, [("plan_id",), ("loan_id",)]),
                installment_id=_dig(payload, [("installment_id",)]),
                cutoff_at=cutoff_at,
                on_time_ratio=max(0.0, min(1.0, _to_float(_dig(payload, [("on_time_ratio",)]), default=0.75))),
                missed_count_90d=_to_int(
                    _dig(payload, [("missed_count_90d",), ("missed_payment_count",)]),
                    default=0,
                ),
                max_days_late_180d=max(0.0, _to_float(_dig(payload, [("max_days_late_180d",)]), default=0.0)),
                avg_days_late=max(
                    0.0,
                    _to_float(
                        _dig(payload, [("avg_days_late",)]),
                        default=_to_float(_dig(payload, [("avg_delay_hours",)]), default=0.0) / 24.0,
                    ),
                ),
                days_since_last_late=max(0.0, _to_float(_dig(payload, [("days_since_last_late",)]), default=30.0)),
                consecutive_on_time_count=_to_int(
                    _dig(payload, [("consecutive_on_time_count",)]),
                    default=0,
                ),
                plan_amount=max(0.000001, plan_amount),
                tenure_days=max(1, tenure_days),
                installment_amount=max(0.000001, installment_amount),
                installment_number=max(1, _to_int(_dig(payload, [("installment_number",)]), default=1)),
                days_until_due=max(0.0, days_until_due),
                current_safety_ratio=max(0.000001, current_safety_ratio),
                distance_to_liquidation_threshold=distance_threshold,
                collateral_type=collateral_type,
                collateral_volatility_bucket=collateral_volatility_bucket,
                topup_count_30d=_to_int(_dig(payload, [("topup_count_30d",), ("topup_count_last_30d",)]), default=0),
                topup_recency_days=max(0.0, _to_float(_dig(payload, [("topup_recency_days",)]), default=7.0)),
                opened_app_last_7d=_to_bool_as_int(_dig(payload, [("opened_app_last_7d",)]), default=0),
                clicked_pay_now_last_7d=_to_bool_as_int(_dig(payload, [("clicked_pay_now_last_7d",)]), default=0),
                payment_attempt_failed_count=_to_int(
                    _dig(payload, [("payment_attempt_failed_count",)]),
                    default=0,
                ),
                wallet_age_days=max(0.0, _to_float(_dig(payload, [("wallet_age_days",)]), default=180.0)),
                tx_count_30d=_to_int(_dig(payload, [("tx_count_30d",)]), default=0),
                stablecoin_balance_bucket=str(
                    _dig(payload, [("stablecoin_balance_bucket",)])
                    or "medium"
                ).lower(),
            )
            return normalized
        except ValidationError:
            logger.exception("Default payload validation failed payload=%s", payload)
            raise
        except Exception:
            logger.exception("Default payload normalization failed payload=%s", payload)
            raise

    def normalize_deposit_payload(self, payload: Dict[str, Any]) -> DepositRecommendationRequest:
        """Normalize raw payload into `DepositRecommendationRequest`."""
        try:
            normalized = DepositRecommendationRequest(
                plan_amount_inr=max(
                    0.000001,
                    _to_float(
                        _dig(payload, [("plan_amount_inr",), ("plan_amount",), ("loan", "plan_amount")]),
                        default=0.0,
                    ),
                ),
                tenure_days=max(1, _to_int(_dig(payload, [("tenure_days",), ("loan", "tenure_days")]), default=30)),
                risk_tier=str(_dig(payload, [("risk_tier",), ("tier",)]) or "MEDIUM").upper(),
                collateral_token=str(_dig(payload, [("collateral_token",), ("asset_symbol",)]) or "BNB").upper(),
                collateral_type=str(_dig(payload, [("collateral_type",)]) or "volatile").lower(),
                locked_token=max(
                    0.0,
                    _to_float(
                        _dig(payload, [("locked_token",), ("current_locked_token",), ("collateral", "locked_token")]),
                        default=0.0,
                    ),
                ),
                price_inr=max(
                    0.000001,
                    _to_float(
                        _dig(payload, [("price_inr",), ("oracle_price_inr",), ("collateral_price_inr",)]),
                        default=0.0,
                    ),
                ),
                stress_drop_pct=_dig(payload, [("stress_drop_pct",)]),
                fees_buffer_pct=_dig(payload, [("fees_buffer_pct",)]),
                outstanding_debt_inr=_to_float(
                    _dig(payload, [("outstanding_debt_inr",), ("outstanding_debt",), ("loan", "outstanding_debt")]),
                    default=0.0,
                ),
            )
            if normalized.outstanding_debt_inr <= 0:
                normalized.outstanding_debt_inr = normalized.plan_amount_inr
            return normalized
        except ValidationError:
            logger.exception("Deposit payload validation failed payload=%s", payload)
            raise
        except Exception:
            logger.exception("Deposit payload normalization failed payload=%s", payload)
            raise

    def score_risk(
        self,
        payload: Union[RiskFeatureInput, Dict[str, Any]],
        include_normalized_payload: bool = False,
    ) -> Dict[str, Any]:
        """Run risk-tier scoring with optional payload normalization."""
        if not self._ml_enabled:
            raise RuntimeError("ML scoring is disabled in config.")
        if self._risk_inference is None or not self._risk_inference.is_loaded:
            raise RuntimeError("ML model is unavailable. Train and load model artifact first.")

        try:
            features = payload if isinstance(payload, RiskFeatureInput) else self.normalize_risk_payload(payload)
            result = self._risk_inference.predict(features)
            if include_normalized_payload:
                result["normalized_payload"] = features.dict()
            return result
        except Exception:
            logger.exception("Risk scoring orchestration failed.")
            raise

    def predict_default(
        self,
        payload: Union[DefaultPredictionInput, Dict[str, Any]],
        include_normalized_payload: bool = False,
    ) -> Dict[str, Any]:
        """Run default prediction with optional payload normalization."""
        if not self._ml_enabled:
            raise RuntimeError("Default prediction ML is disabled in config.")
        if self._default_inference is None or not self._default_inference.is_loaded:
            raise RuntimeError("Default prediction model is unavailable. Train and load artifact first.")

        try:
            features = payload if isinstance(payload, DefaultPredictionInput) else self.normalize_default_payload(payload)
            result = self._default_inference.predict(features)
            if include_normalized_payload:
                result["normalized_payload"] = features.dict()
            return result
        except Exception:
            logger.exception("Default prediction orchestration failed.")
            raise

    def recommend_deposit_policy(
        self,
        payload: Union[DepositRecommendationRequest, Dict[str, Any]],
        include_normalized_payload: bool = False,
    ) -> Dict[str, Any]:
        """Run rule-based deposit recommendation with optional payload normalization."""
        try:
            features = payload if isinstance(payload, DepositRecommendationRequest) else self.normalize_deposit_payload(payload)
            result = recommend_deposit_by_policy(features)
            if include_normalized_payload:
                result["normalized_payload"] = features.dict()
            return result
        except Exception:
            logger.exception("Policy deposit orchestration failed.")
            raise

    def recommend_deposit_ml(
        self,
        payload: Union[DepositRecommendationRequest, Dict[str, Any]],
        include_normalized_payload: bool = False,
    ) -> Dict[str, Any]:
        """Run ML deposit recommendation with policy fallback."""
        if not self._ml_enabled:
            raise RuntimeError("ML deposit recommendation is disabled in config.")
        if self._deposit_inference is None:
            raise RuntimeError("Deposit model service is unavailable.")

        try:
            features = payload if isinstance(payload, DepositRecommendationRequest) else self.normalize_deposit_payload(payload)
            result = self._deposit_inference.predict(features)
            if include_normalized_payload:
                result["normalized_payload"] = features.dict()
            return result
        except Exception:
            logger.exception("ML deposit orchestration failed.")
            raise

    def orchestrate(self, request_payload: MlOrchestrationRequest) -> Dict[str, Any]:
        """Run one or many ML flows from a single API call.

        The method safely orchestrates risk score, default prediction, and deposit
        recommendation using the available sections in the request.
        """
        result: Dict[str, Any] = {"success": True, "results": {}, "errors": {}}
        try:
            if (
                request_payload.risk_payload is None
                and request_payload.default_payload is None
                and request_payload.deposit_payload is None
            ):
                raise ValueError("At least one payload section is required.")

            derived_tier: Optional[str] = None

            if request_payload.risk_payload is not None:
                try:
                    risk_result = self.score_risk(
                        request_payload.risk_payload,
                        include_normalized_payload=request_payload.include_normalized_payload,
                    )
                    result["results"]["risk"] = risk_result
                    derived_tier = str(risk_result.get("risk_tier", "")).upper() or None
                except Exception as exc:
                    logger.exception("Risk orchestration section failed.")
                    result["success"] = False
                    result["errors"]["risk"] = str(exc)

            if request_payload.default_payload is not None:
                try:
                    default_result = self.predict_default(
                        request_payload.default_payload,
                        include_normalized_payload=request_payload.include_normalized_payload,
                    )
                    result["results"]["default_prediction"] = default_result
                except Exception as exc:
                    logger.exception("Default orchestration section failed.")
                    result["success"] = False
                    result["errors"]["default_prediction"] = str(exc)

            if request_payload.deposit_payload is not None:
                deposit_payload = dict(request_payload.deposit_payload)
                if "risk_tier" not in deposit_payload and derived_tier is not None:
                    deposit_payload["risk_tier"] = derived_tier

                if request_payload.run_policy_deposit:
                    try:
                        policy_result = self.recommend_deposit_policy(
                            deposit_payload,
                            include_normalized_payload=request_payload.include_normalized_payload,
                        )
                        result["results"]["deposit_policy"] = policy_result
                    except Exception as exc:
                        logger.exception("Deposit policy orchestration section failed.")
                        result["success"] = False
                        result["errors"]["deposit_policy"] = str(exc)

                if request_payload.run_ml_deposit:
                    try:
                        ml_result = self.recommend_deposit_ml(
                            deposit_payload,
                            include_normalized_payload=request_payload.include_normalized_payload,
                        )
                        result["results"]["deposit_ml"] = ml_result
                    except Exception as exc:
                        logger.exception("Deposit ML orchestration section failed.")
                        result["success"] = False
                        result["errors"]["deposit_ml"] = str(exc)

            return result
        except Exception:
            logger.exception("ML orchestration request failed payload=%s", request_payload.dict())
            raise
