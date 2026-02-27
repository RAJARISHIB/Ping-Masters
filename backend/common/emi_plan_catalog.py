"""EMI plan catalog utilities used by BNPL schedule and ML orchestration flows."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError, root_validator, validator


logger = logging.getLogger(__name__)

_DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[1] / "settings" / "emi_plans.json"
_DEFAULT_CATALOG_LOCK = RLock()
_DEFAULT_CATALOG_INSTANCE: Optional["EmiPlanCatalog"] = None


def _model_to_dict(model: BaseModel) -> Dict[str, Any]:
    """Serialize pydantic model across v1/v2 without deprecation warnings."""
    if hasattr(model, "model_dump"):
        return model.model_dump()  # type: ignore[attr-defined]
    return model.dict()


class EmiPlanModel(BaseModel):
    """Canonical EMI plan definition loaded from `emi_plans.json`."""

    plan_id: str = Field(..., min_length=3)
    plan_name: str = Field(..., min_length=3)
    category: str = Field(default="bnpl_installment", min_length=3)
    source_platform: str = Field(default="unknown", min_length=2)
    source_url: Optional[str] = Field(default=None)
    enabled: bool = Field(default=True)
    currency_scope: List[str] = Field(default_factory=lambda: ["INR"])

    principal_min_minor: int = Field(default=0, ge=0)
    principal_max_minor: int = Field(default=0, ge=0)

    installment_count: int = Field(..., gt=0)
    tenure_days: int = Field(..., gt=0)
    cadence_days: int = Field(..., gt=0)
    grace_window_hours: int = Field(default=24, ge=0)
    late_fee_flat_minor: int = Field(default=0, ge=0)
    late_fee_bps: int = Field(default=0, ge=0, le=10000)

    ltv_bps: int = Field(default=7000, ge=0, le=10000)
    danger_limit_bps: int = Field(default=8000, ge=0, le=10000)
    liquidation_threshold_bps: int = Field(default=9000, ge=0, le=10000)

    stress_drop_pct_stable: float = Field(default=0.02, ge=0.0, lt=1.0)
    stress_drop_pct_volatile: float = Field(default=0.20, ge=0.0, lt=1.0)
    target_ltv_by_risk_tier: Dict[str, float] = Field(default_factory=dict)

    description: str = Field(default="")
    tags: List[str] = Field(default_factory=list)

    @validator("plan_id", "plan_name", "category", "source_platform", pre=True)
    def _normalize_text(cls, value: Any) -> str:
        """Normalize textual fields by stripping whitespace."""
        return str(value or "").strip()

    @validator("currency_scope", pre=True, always=True)
    def _normalize_currency_scope(cls, value: Any) -> List[str]:
        """Normalize currency scope to uppercase unique codes."""
        try:
            currencies = [str(item).strip().upper() for item in (value or []) if str(item).strip()]
            if not currencies:
                return ["INR"]
            return sorted(set(currencies))
        except Exception:
            logger.exception("Failed normalizing currency scope value=%s", value)
            return ["INR"]

    @validator("target_ltv_by_risk_tier", pre=True, always=True)
    def _normalize_target_ltv_by_risk_tier(cls, value: Any) -> Dict[str, float]:
        """Normalize risk-tier target LTV mapping to uppercase keys."""
        try:
            mapping = dict(value or {})
            normalized: Dict[str, float] = {}
            for key, raw in mapping.items():
                tier = str(key).strip().upper()
                score = float(raw)
                if score <= 0 or score >= 1:
                    continue
                normalized[tier] = score
            if not normalized:
                normalized = {"LOW": 0.70, "MEDIUM": 0.50, "HIGH": 0.35}
            return normalized
        except Exception:
            logger.exception("Failed normalizing target LTV mapping value=%s", value)
            return {"LOW": 0.70, "MEDIUM": 0.50, "HIGH": 0.35}

    @root_validator(skip_on_failure=True)
    def _validate_plan_thresholds(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """Validate threshold and principal range relationships."""
        try:
            danger_limit_bps = int(values.get("danger_limit_bps", 0))
            liquidation_threshold_bps = int(values.get("liquidation_threshold_bps", 0))
            principal_min_minor = int(values.get("principal_min_minor", 0))
            principal_max_minor = int(values.get("principal_max_minor", 0))
            if danger_limit_bps >= liquidation_threshold_bps:
                raise ValueError("danger_limit_bps must be lower than liquidation_threshold_bps")
            if principal_max_minor > 0 and principal_max_minor < principal_min_minor:
                raise ValueError("principal_max_minor cannot be less than principal_min_minor")
            return values
        except Exception:
            logger.exception("EMI plan threshold validation failed values=%s", values)
            raise


class EmiPlanCatalog:
    """Loader and query utility for EMI plan definitions."""

    def __init__(
        self,
        path: Optional[str] = None,
        default_plan_id: str = "bnpl_pay_in_4",
    ) -> None:
        """Initialize catalog with optional custom JSON path."""
        self._path = Path(path).resolve() if path else _DEFAULT_CATALOG_PATH
        self._default_plan_id = str(default_plan_id).strip() or "bnpl_pay_in_4"
        self._lock = RLock()
        self._plans: List[EmiPlanModel] = []
        self._plan_map: Dict[str, EmiPlanModel] = {}
        self._load_plans(force=True)

    @property
    def path(self) -> str:
        """Return catalog JSON path."""
        return str(self._path)

    def _load_plans(self, force: bool = False) -> None:
        """Load and validate plans from file."""
        with self._lock:
            if self._plans and not force:
                return

            loaded_plans: List[EmiPlanModel] = []
            loaded_map: Dict[str, EmiPlanModel] = {}
            if not self._path.exists():
                logger.warning("EMI plans file not found at path=%s", self._path)
                self._plans = []
                self._plan_map = {}
                return

            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if not isinstance(raw, list):
                    raise ValueError("EMI plans file must contain a JSON array.")

                for row in raw:
                    try:
                        if hasattr(EmiPlanModel, "model_validate"):
                            plan = EmiPlanModel.model_validate(row)  # pydantic v2
                        else:
                            plan = EmiPlanModel.parse_obj(row)  # pragma: no cover - pydantic v1
                        if plan.plan_id in loaded_map:
                            logger.warning("Duplicate EMI plan id found and skipped plan_id=%s", plan.plan_id)
                            continue
                        loaded_plans.append(plan)
                        loaded_map[plan.plan_id] = plan
                    except ValidationError:
                        logger.exception("Invalid EMI plan row skipped row=%s", row)
                    except Exception:
                        logger.exception("Failed parsing EMI plan row row=%s", row)

                self._plans = loaded_plans
                self._plan_map = loaded_map
                logger.info("Loaded EMI plans count=%d from path=%s", len(self._plans), self._path)
            except Exception:
                logger.exception("Failed loading EMI plans from path=%s", self._path)
                self._plans = []
                self._plan_map = {}

    def list_plan_models(
        self,
        include_disabled: bool = False,
        currency: Optional[str] = None,
    ) -> List[EmiPlanModel]:
        """Return plan models with optional filters."""
        try:
            self._load_plans(force=False)
            normalized_currency = str(currency or "").strip().upper()
            result: List[EmiPlanModel] = []
            for plan in self._plans:
                if not include_disabled and not plan.enabled:
                    continue
                if normalized_currency and normalized_currency not in plan.currency_scope:
                    continue
                result.append(plan)
            return result
        except Exception:
            logger.exception("Failed listing EMI plans include_disabled=%s currency=%s", include_disabled, currency)
            return []

    def list_plans(
        self,
        include_disabled: bool = False,
        currency: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return list of plans as serializable dictionaries."""
        try:
            return [
                _model_to_dict(plan)
                for plan in self.list_plan_models(include_disabled=include_disabled, currency=currency)
            ]
        except Exception:
            logger.exception("Failed listing EMI plans as dictionaries.")
            return []

    def get_plan(self, plan_id: str, include_disabled: bool = False) -> Optional[EmiPlanModel]:
        """Get one plan by id."""
        try:
            self._load_plans(force=False)
            normalized_plan_id = str(plan_id or "").strip()
            if not normalized_plan_id:
                return None
            plan = self._plan_map.get(normalized_plan_id)
            if plan is None:
                return None
            if not include_disabled and not plan.enabled:
                return None
            return plan
        except Exception:
            logger.exception("Failed getting EMI plan plan_id=%s", plan_id)
            return None

    def resolve_plan(
        self,
        plan_id: Optional[str] = None,
        currency: Optional[str] = None,
        installment_count: Optional[int] = None,
        tenure_days: Optional[int] = None,
        allow_default_fallback: bool = True,
    ) -> Optional[EmiPlanModel]:
        """Resolve a plan by id, then by schedule shape, then by default id."""
        try:
            if plan_id:
                plan = self.get_plan(plan_id, include_disabled=False)
                if plan is not None:
                    return plan

            candidates = self.list_plan_models(include_disabled=False, currency=currency)
            if not candidates:
                return None

            if installment_count and tenure_days:
                for plan in candidates:
                    if plan.installment_count == int(installment_count) and plan.tenure_days == int(tenure_days):
                        return plan

            if installment_count:
                for plan in candidates:
                    if plan.installment_count == int(installment_count):
                        return plan

            if allow_default_fallback:
                default_plan = self.get_plan(self._default_plan_id, include_disabled=False)
                if default_plan is not None:
                    return default_plan
                return candidates[0]
            return None
        except Exception:
            logger.exception(
                "Failed resolving EMI plan plan_id=%s currency=%s installment_count=%s tenure_days=%s",
                plan_id,
                currency,
                installment_count,
                tenure_days,
            )
            return None

    def apply_plan_defaults(
        self,
        payload: Dict[str, Any],
        force: bool = False,
    ) -> Tuple[Dict[str, Any], Optional[EmiPlanModel]]:
        """Apply resolved plan defaults to payload for BNPL and ML flows."""
        try:
            normalized = dict(payload or {})
            plan = self.resolve_plan(
                plan_id=normalized.get("emi_plan_id"),
                currency=normalized.get("currency"),
                installment_count=normalized.get("installment_count"),
                tenure_days=normalized.get("tenure_days"),
                allow_default_fallback=bool(normalized.get("emi_plan_id") or force),
            )
            if plan is None:
                return normalized, None

            def _should_apply(current_value: Any) -> bool:
                if force:
                    return True
                if current_value is None:
                    return True
                if isinstance(current_value, str) and not current_value.strip():
                    return True
                if isinstance(current_value, (int, float)) and float(current_value) <= 0:
                    return True
                return False

            mapped_fields: Dict[str, Any] = {
                "installment_count": plan.installment_count,
                "tenure_days": plan.tenure_days,
                "grace_window_hours": plan.grace_window_hours,
                "late_fee_flat_minor": plan.late_fee_flat_minor,
                "late_fee_bps": plan.late_fee_bps,
                "ltv_bps": plan.ltv_bps,
                "danger_limit_bps": plan.danger_limit_bps,
                "liquidation_threshold_bps": plan.liquidation_threshold_bps,
                "cadence_days": plan.cadence_days,
            }
            for field_name, field_value in mapped_fields.items():
                if _should_apply(normalized.get(field_name)):
                    normalized[field_name] = field_value

            collateral_type = str(normalized.get("collateral_type") or "volatile").strip().lower()
            stress_drop = plan.stress_drop_pct_stable if collateral_type == "stable" else plan.stress_drop_pct_volatile
            if _should_apply(normalized.get("stress_drop_pct")):
                normalized["stress_drop_pct"] = stress_drop

            risk_tier = str(normalized.get("risk_tier") or "MEDIUM").strip().upper()
            target_ltv = plan.target_ltv_by_risk_tier.get(risk_tier) or plan.target_ltv_by_risk_tier.get("MEDIUM")
            if _should_apply(normalized.get("target_ltv")) and target_ltv is not None:
                normalized["target_ltv"] = float(target_ltv)

            normalized["emi_plan_id"] = plan.plan_id
            normalized["emi_plan_name"] = plan.plan_name
            normalized["emi_source_platform"] = plan.source_platform
            normalized["emi_category"] = plan.category
            return normalized, plan
        except Exception:
            logger.exception("Failed applying EMI plan defaults payload=%s force=%s", payload, force)
            return dict(payload or {}), None

    def get_stress_drop_pct(
        self,
        plan_id: Optional[str],
        collateral_type: str,
        fallback: float = 0.20,
    ) -> float:
        """Return stress-drop policy by plan and collateral type."""
        try:
            plan = self.get_plan(plan_id or "", include_disabled=False)
            if plan is None:
                return float(fallback)
            normalized_type = str(collateral_type or "volatile").strip().lower()
            if normalized_type == "stable":
                return float(plan.stress_drop_pct_stable)
            return float(plan.stress_drop_pct_volatile)
        except Exception:
            logger.exception(
                "Failed reading stress drop policy plan_id=%s collateral_type=%s",
                plan_id,
                collateral_type,
            )
            return float(fallback)

    def get_target_ltv(
        self,
        plan_id: Optional[str],
        risk_tier: str,
        fallback: float = 0.50,
    ) -> float:
        """Return target LTV from plan + risk tier mapping."""
        try:
            plan = self.get_plan(plan_id or "", include_disabled=False)
            if plan is None:
                return float(fallback)
            normalized_tier = str(risk_tier or "MEDIUM").strip().upper()
            return float(plan.target_ltv_by_risk_tier.get(normalized_tier, plan.target_ltv_by_risk_tier.get("MEDIUM", fallback)))
        except Exception:
            logger.exception("Failed reading target LTV plan_id=%s risk_tier=%s", plan_id, risk_tier)
            return float(fallback)


def get_default_emi_plan_catalog() -> EmiPlanCatalog:
    """Return singleton EMI plan catalog for modules that do not use DI."""
    global _DEFAULT_CATALOG_INSTANCE
    with _DEFAULT_CATALOG_LOCK:
        if _DEFAULT_CATALOG_INSTANCE is None:
            _DEFAULT_CATALOG_INSTANCE = EmiPlanCatalog()
        return _DEFAULT_CATALOG_INSTANCE
