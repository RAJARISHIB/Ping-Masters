"""Primary API router module with Firebase-backed endpoints."""

from datetime import datetime, timezone
import logging
from typing import Optional, Union

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, ValidationError
from web3 import Web3

from api.bnpl_router import build_bnpl_router
from common import EmiPlanCatalog, convert_currency_amount
from core import FirebaseClientManager, Web3ClientManager
from core.config import AppSettings
from ml.deposit_inference import DepositRecommendationInferenceService
from ml.deposit_schema import DepositRecommendationRequest
from ml.default_inference import DefaultPredictionInferenceService
from ml.default_schema import DefaultPredictionInput
from ml.inference import RiskModelInferenceService
from ml.orchestration_schema import (
    MlEmiPlanEvaluationRequest,
    MlOrchestrationRequest,
    MlPayloadAnalysisRequest,
    MlTrainingRowBuildRequest,
)
from ml.orchestrator import MlPayloadOrchestrator
from ml.schema import RiskFeatureInput
from ml.training_manager import MlModelManagementService
from ml.training_schema import (
    MlGenerateDatasetRequest,
    MlReloadModelsRequest,
    MlTrainModelRequest,
    MlUpdateDefaultThresholdRequest,
)
from models.exceptions import ModelNotFoundError, VersionConflictError
from models.users import UserModel, WalletAddressModel
from repositories.firestore_user_repository import FirestoreUserRepository
from services import ProtocolApiService, RazorpayService
from services.bnpl_feature_service import BnplFeatureService
from services.market_data_service import MarketDataService


logger = logging.getLogger(__name__)


class UserFromFirebaseCreateRequest(BaseModel):
    """Request payload to sync user profile from Firebase by `user_id`."""

    user_id: str = Field(..., min_length=3)
    wallet_address: list[WalletAddressModel] = Field(default_factory=list)
    notification_channels: list[str] = Field(default_factory=list)
    currency_code: str = Field(default="INR", min_length=3, max_length=3)
    currency_symbol: str = Field(default="Rs", min_length=1, max_length=3)
    autopay_enabled: bool = Field(default=False)
    kyc_level: int = Field(default=0, ge=0, le=3)


class UserWalletDetailsResponse(BaseModel):
    """Response payload for user wallet details lookup."""

    user_id: str = Field(..., min_length=3)
    wallet_address: list[WalletAddressModel] = Field(default_factory=list)
    wallet_count: int = Field(default=0, ge=0)


class OracleUpdatePricesRequest(BaseModel):
    """Request payload for oracle price updates."""

    usd_price: int = Field(..., gt=0)
    inr_price: int = Field(..., gt=0)


class UserSetCurrencyRequest(BaseModel):
    """Request payload for setting wallet currency."""

    wallet: str = Field(..., min_length=6)
    currency: str = Field(..., min_length=3, max_length=3)


class CollateralRequest(BaseModel):
    """Request payload for collateral actions."""

    wallet: str = Field(..., min_length=6)
    amount_bnb: str = Field(..., min_length=1)


class BorrowRequest(BaseModel):
    """Request payload for borrow endpoint."""

    wallet: str = Field(..., min_length=6)
    amount: str = Field(..., min_length=1)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)


class RepayRequest(BaseModel):
    """Request payload for repay endpoint."""

    wallet: str = Field(..., min_length=6)
    amount: str = Field(..., min_length=1)


class LiquidateRequest(BaseModel):
    """Request payload for liquidation endpoint."""

    wallet: str = Field(..., min_length=6)


class MarketChartRequest(BaseModel):
    """Request payload for market chart retrieval."""

    symbol: str = Field(..., min_length=1)
    timeframe: str = Field(..., min_length=2)
    vs_currency: str = Field(default="usd", min_length=3)


def _resolve_chain_rpc(settings: AppSettings, chain: str) -> str:
    """Resolve RPC URL for supported chain names."""
    normalized_chain = chain.strip().lower()
    if normalized_chain == "bsc":
        if not settings.bsc_rpc_url:
            raise ValueError("BSC RPC URL is not configured.")
        return settings.bsc_rpc_url
    if normalized_chain == "opbnb":
        if not settings.opbnb_rpc_url:
            raise ValueError("opBNB RPC URL is not configured.")
        return settings.opbnb_rpc_url
    raise ValueError("Unsupported chain. Use 'bsc' or 'opbnb'.")


def _require_user_repository(repository: Optional[FirestoreUserRepository]) -> FirestoreUserRepository:
    """Ensure Firebase-backed user repository is initialized."""
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase client is not configured or unavailable.",
        )
    return repository


def _require_web3_manager(manager: Optional[Web3ClientManager]) -> Web3ClientManager:
    """Ensure Web3 manager is initialized and available."""
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Web3 client is not configured or unavailable.",
        )
    return manager


def _extract_profile_fields(source_payload: dict, user_id: str) -> tuple[str, str, str]:
    """Extract user profile fields from Firebase with robust default fallbacks."""
    email = source_payload.get("email") or "{0}@example.local".format(user_id)
    phone = source_payload.get("phone") or source_payload.get("phone_number") or "0000000000"
    full_name = (
        source_payload.get("full_name")
        or source_payload.get("name")
        or source_payload.get("display_name")
        or "Unknown User"
    )
    return str(email), str(phone), str(full_name)


def _safe_to_float(value: Optional[Union[str, float]]) -> float:
    """Convert mixed numeric payload values into float safely."""
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _sync_user_loan_state(
    user_repository: Optional[FirestoreUserRepository],
    wallet: str,
    action: str,
    result_payload: dict,
) -> None:
    """Upsert and update user loan-related fields after borrow/repay events."""
    if user_repository is None:
        return

    action_normalized = action.strip().lower()
    if action_normalized not in {"borrow", "repay"}:
        logger.warning("Loan sync skipped for unknown action=%s wallet=%s", action, wallet)
        return

    currency = str(result_payload.get("currency") or "USD").upper()
    borrowed = _safe_to_float(result_payload.get("borrowed"))
    repaid = _safe_to_float(result_payload.get("repaid"))
    remaining_debt = _safe_to_float(result_payload.get("remaining_debt"))

    try:
        try:
            user = user_repository.get_by_id(wallet)
            is_new_user = False
        except ModelNotFoundError:
            user = UserModel(
                user_id=wallet,
                email="{0}@wallet.local".format(wallet[:12]),
                phone="0000000000",
                full_name="Wallet User",
                wallet_address=[WalletAddressModel(name="Primary", wallet_id=wallet)],
                currency_code=currency,
                currency_symbol="$" if currency == "USD" else "Rs",
            )
            is_new_user = True

        user.loan_currency = currency
        user.last_loan_action = action_normalized
        user.last_loan_action_at = datetime.now(timezone.utc)

        if action_normalized == "borrow":
            user.total_borrowed_fiat += borrowed
            if remaining_debt <= 0.0:
                remaining_debt = user.outstanding_debt_fiat + borrowed
        else:
            user.total_repaid_fiat += repaid
            if remaining_debt <= 0.0:
                remaining_debt = max(0.0, user.outstanding_debt_fiat - repaid)

        user.outstanding_debt_fiat = max(0.0, remaining_debt)

        if is_new_user:
            user_repository.create(user)
        else:
            user.version += 1
            user_repository.update(user)
    except Exception:
        logger.exception(
            "Failed syncing user loan state wallet=%s action=%s payload=%s",
            wallet,
            action_normalized,
            result_payload,
        )


def build_router(settings: AppSettings) -> APIRouter:
    """Build and return the top-level API router.

    Args:
        settings: Application settings payload.

    Returns:
        APIRouter: Fully configured router with all endpoints.
    """
    router = APIRouter()
    protocol_service = ProtocolApiService()
    market_service = MarketDataService(
        base_url=settings.market_api_base_url,
        provider=settings.market_api_provider,
        symbols_cache_ttl_sec=settings.market_symbols_cache_ttl_sec,
        api_key=settings.market_api_key,
        api_key_header=settings.market_api_key_header,
    )
    emi_plan_catalog = EmiPlanCatalog(
        path=settings.emi_plans_path,
        default_plan_id=settings.emi_default_plan_id,
    )
    razorpay_service: Optional[RazorpayService] = None
    if settings.razorpay_enabled:
        try:
            razorpay_service = RazorpayService(
                enabled=settings.razorpay_enabled,
                key_id=settings.razorpay_key_id,
                key_secret=settings.razorpay_key_secret,
                api_base_url=settings.razorpay_api_base_url,
                timeout_sec=settings.razorpay_timeout_sec,
            )
            if not razorpay_service.is_configured:
                logger.warning(
                    "Razorpay is enabled but not fully configured. "
                    "Check razorpay.key_id and razorpay.key_secret."
                )
        except Exception:
            logger.exception("Failed to initialize Razorpay service.")
            razorpay_service = None
    else:
        logger.info("Razorpay integration disabled by razorpay.enabled=false")

    firebase_manager: Optional[FirebaseClientManager] = None
    user_repository: Optional[FirestoreUserRepository] = None
    web3_manager: Optional[Web3ClientManager] = None
    ml_inference: Optional[RiskModelInferenceService] = None
    deposit_inference: Optional[DepositRecommendationInferenceService] = None
    default_inference: Optional[DefaultPredictionInferenceService] = None
    if settings.firebase_enabled:
        try:
            firebase_manager = FirebaseClientManager(
                project_id=settings.firebase_project_id,
                credentials_path=settings.firebase_credentials_path,
            )
            user_repository = FirestoreUserRepository(
                firebase_manager=firebase_manager,
                collection_name=settings.firebase_users_collection,
            )
        except Exception:
            logger.exception("Failed to initialize Firebase dependencies for router.")
    else:
        logger.info("Firebase integration disabled by FIREBASE_ENABLED=false")

    if settings.web3_enabled:
        try:
            if not all(
                [
                    settings.bsc_rpc_url,
                    settings.opbnb_rpc_url,
                    settings.contract_abi_json,
                    settings.bsc_contract_address,
                    settings.opbnb_contract_address,
                ]
            ):
                raise ValueError("Missing required WEB3 configuration values.")
            web3_manager = Web3ClientManager(
                bsc_rpc_url=settings.bsc_rpc_url or "",
                opbnb_rpc_url=settings.opbnb_rpc_url or "",
                abi_json=settings.contract_abi_json or "",
                bsc_contract_address=settings.bsc_contract_address or "",
                opbnb_contract_address=settings.opbnb_contract_address or "",
            )
        except Exception:
            logger.exception("Failed to initialize Web3 dependencies for router.")
    else:
        logger.info("Web3 integration disabled by WEB3_ENABLED=false")

    if settings.ml_enabled:
        try:
            ml_inference = RiskModelInferenceService(model_path=settings.ml_model_path)
            if not ml_inference.is_loaded:
                logger.warning("ML enabled but model could not be loaded path=%s", settings.ml_model_path)
            deposit_inference = DepositRecommendationInferenceService(model_path=settings.ml_deposit_model_path)
            if not deposit_inference.is_loaded:
                logger.warning(
                    "ML enabled but deposit model could not be loaded path=%s",
                    settings.ml_deposit_model_path,
                )
            default_inference = DefaultPredictionInferenceService(
                model_path=settings.ml_default_model_path,
                high_threshold=settings.ml_default_high_threshold,
                medium_threshold=settings.ml_default_medium_threshold,
            )
            if not default_inference.is_loaded:
                logger.warning(
                    "ML enabled but default model could not be loaded path=%s",
                    settings.ml_default_model_path,
                )
        except Exception:
            logger.exception("Failed to initialize ML inference service.")
    else:
        logger.info("ML integration disabled by ml.enabled=false")

    ml_orchestrator = MlPayloadOrchestrator(
        ml_enabled=settings.ml_enabled,
        risk_inference=ml_inference,
        default_inference=default_inference,
        deposit_inference=deposit_inference,
        emi_plan_catalog=emi_plan_catalog,
    )
    ml_management_service = MlModelManagementService(
        enabled=settings.ml_enabled,
        risk_model_path=settings.ml_model_path,
        default_model_path=settings.ml_default_model_path,
        deposit_model_path=settings.ml_deposit_model_path,
        default_high_threshold=settings.ml_default_high_threshold,
        default_medium_threshold=settings.ml_default_medium_threshold,
        risk_inference=ml_inference,
        default_inference=default_inference,
        deposit_inference=deposit_inference,
    )
    bnpl_feature_service = BnplFeatureService(
        settings=settings,
        protocol_service=protocol_service,
        user_repository=user_repository,
        firebase_manager=firebase_manager,
        ml_orchestrator=ml_orchestrator,
        emi_plan_catalog=emi_plan_catalog,
        razorpay_service=razorpay_service,
    )

    router.include_router(build_firebase_router(firebase_manager))
    router.include_router(build_web3_router(web3_manager, settings.web3_read_function))
    router.include_router(build_bnpl_router(bnpl_feature_service))

    @router.get("/", summary="Root endpoint")
    def read_root() -> dict:
        """Return a basic message confirming service availability."""
        return {"message": "Ping Masters API is running"}

    @router.get("/health", summary="Health check")
    def health_check() -> dict:
        """Return service health status for probes and monitors."""
        return {"status": "ok"}

    @router.get("/wallet/validate", summary="Validate wallet address format")
    def wallet_validate(wallet: str) -> dict:
        """Validate wallet address using EVM checksum/address rules."""
        try:
            normalized_wallet = wallet.strip()
            is_valid = Web3.is_address(normalized_wallet)
            checksum_address = Web3.to_checksum_address(normalized_wallet) if is_valid else None
            return {
                "wallet": normalized_wallet,
                "is_valid": is_valid,
                "checksum_address": checksum_address,
            }
        except Exception as exc:
            logger.exception("Wallet validation failed wallet=%s", wallet)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/wallet/balance", summary="Get native wallet balance")
    def wallet_balance(wallet: str, chain: str = "bsc") -> dict:
        """Fetch native balance (BNB) from public RPC for the given wallet."""
        try:
            normalized_wallet = wallet.strip()
            if not Web3.is_address(normalized_wallet):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Invalid wallet address format.",
                )
            rpc_url = _resolve_chain_rpc(settings=settings, chain=chain)
            provider = Web3(Web3.HTTPProvider(rpc_url))
            if not provider.is_connected():
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Unable to connect to RPC provider.",
                )
            checksum_wallet = Web3.to_checksum_address(normalized_wallet)
            balance_wei = provider.eth.get_balance(checksum_wallet)
            balance_bnb = provider.from_wei(balance_wei, "ether")
            return {
                "wallet": checksum_wallet,
                "chain": chain.lower(),
                "balance_wei": str(balance_wei),
                "balance_bnb": str(balance_bnb),
            }
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        except Exception as exc:
            logger.exception("Wallet balance lookup failed wallet=%s chain=%s", wallet, chain)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/market/chart", summary="Get market chart by symbol and timeframe")
    def market_chart(payload: MarketChartRequest) -> dict:
        """Fetch real-time/historical chart data for user-selected crypto symbol."""
        try:
            return market_service.get_chart(
                symbol_or_id=payload.symbol,
                timeframe=payload.timeframe,
                vs_currency=payload.vs_currency,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Market chart endpoint failed symbol=%s timeframe=%s", payload.symbol, payload.timeframe)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    @router.get("/market/symbols", summary="List all available crypto symbols")
    def market_symbols(refresh: bool = False) -> dict:
        """Return all symbols available from the configured market data provider."""
        try:
            symbols = market_service.list_all_symbols(refresh=refresh)
            return {
                "total": len(symbols),
                "symbols": symbols,
                "provider": settings.market_api_base_url,
            }
        except Exception as exc:
            logger.exception("Market symbols endpoint failed.")
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    @router.get("/market/resolve", summary="Resolve symbol to provider coin id")
    def market_resolve(symbol: str = Query(..., min_length=1)) -> dict:
        """Resolve user-provided symbol/id into normalized provider id."""
        try:
            coin_id = market_service.resolve_coin_id(symbol_or_id=symbol)
            return {
                "input": symbol,
                "coin_id": coin_id,
                "provider": settings.market_api_base_url,
            }
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Market resolve endpoint failed symbol=%s", symbol)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    @router.get("/currency/convert", summary="Convert amount to target currency")
    def currency_convert(
        amount: float = Query(..., ge=0),
        from_currency: str = Query(..., min_length=3, max_length=3),
        to_currency: str = Query(..., min_length=3, max_length=3),
    ) -> dict:
        """Convert amount using configured public currency API."""
        try:
            return convert_currency_amount(
                amount=amount,
                from_currency=from_currency,
                to_currency=to_currency,
                api_base_url=settings.currency_api_base_url,
                timeout_sec=settings.currency_api_timeout_sec,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
        except Exception as exc:
            logger.exception(
                "Currency convert endpoint failed amount=%s from=%s to=%s",
                amount,
                from_currency,
                to_currency,
            )
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/settings", summary="Settings snapshot")
    def get_settings_snapshot() -> dict:
        """Expose non-sensitive settings and API capabilities for UI gating."""
        razorpay_configured = bool(razorpay_service and razorpay_service.is_configured)
        return {
            "app_name": settings.app_name,
            "debug": settings.debug,
            "host": settings.host,
            "port": settings.port,
            "firebase_enabled": settings.firebase_enabled,
            "web3_enabled": settings.web3_enabled,
            "ml_enabled": settings.ml_enabled,
            "emi_plans_path": settings.emi_plans_path,
            "emi_default_plan_id": settings.emi_default_plan_id,
            "razorpay_enabled": settings.razorpay_enabled,
            "razorpay_configured": razorpay_configured,
            "api_capabilities": {
                "market": True,
                "risk": True,
                "ml": settings.ml_enabled,
                "bnpl": True,
                "protocol": True,
                "web3": settings.web3_enabled,
                "users": settings.firebase_enabled,
                "razorpay": razorpay_configured,
                "oracle": True,
            },
        }

    @router.get("/ml/health", summary="ML model health")
    def ml_health() -> dict:
        """Return ML inference model status."""
        return {
            "ml_enabled": settings.ml_enabled,
            "model_loaded": bool(ml_inference and ml_inference.is_loaded),
            "model_path": settings.ml_model_path,
        }

    @router.get("/ml/payload-specs", summary="List ML payload field specifications")
    def ml_payload_specs() -> dict:
        """Return required/optional payload fields used across ML endpoints."""
        try:
            return ml_orchestrator.get_payload_specs()
        except Exception as exc:
            logger.exception("ML payload specs endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/ml/payload-analyze", summary="Analyze ML payload completeness")
    def ml_payload_analyze(payload: MlPayloadAnalysisRequest) -> dict:
        """Analyze user payload for selected ML model before inference/training."""
        try:
            return ml_orchestrator.analyze_payload(model_type=payload.model_type, payload=payload.payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("ML payload analyze endpoint failed model_type=%s", payload.model_type)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/ml/payload-build-training-row", summary="Build normalized ML training row")
    def ml_payload_build_training_row(payload: MlTrainingRowBuildRequest) -> dict:
        """Build normalized training row from raw payload and optional label."""
        try:
            row = ml_orchestrator.build_training_row(
                model_type=payload.model_type,
                payload=payload.payload,
                label=payload.label,
            )
            return {"model_type": payload.model_type, "row": row}
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("ML training-row build endpoint failed model_type=%s", payload.model_type)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/ml/runtime/status", summary="ML runtime status")
    def ml_runtime_status() -> dict:
        """Return runtime model state, loaded flags, and thresholds."""
        try:
            return ml_management_service.get_runtime_status()
        except Exception as exc:
            logger.exception("ML runtime status endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/ml/training/specs", summary="ML training requirements")
    def ml_training_specs() -> dict:
        """Return model features, labels, and training artifact paths."""
        try:
            return ml_management_service.get_training_specs()
        except Exception as exc:
            logger.exception("ML training specs endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/ml/training/generate-dataset", summary="Generate synthetic ML dataset")
    def ml_generate_dataset(payload: MlGenerateDatasetRequest) -> dict:
        """Generate synthetic dataset for risk/default/deposit model training."""
        try:
            return ml_management_service.generate_dataset(payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("ML generate dataset endpoint failed model_type=%s", payload.model_type)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/ml/training/train", summary="Train ML model")
    def ml_train_model(payload: MlTrainModelRequest) -> dict:
        """Train selected ML model and optionally reload runtime artifact."""
        try:
            return ml_management_service.train_model(payload)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("ML train endpoint failed model_type=%s", payload.model_type)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/ml/runtime/reload", summary="Reload ML model artifacts")
    def ml_runtime_reload(payload: MlReloadModelsRequest) -> dict:
        """Reload one or more ML artifacts in runtime inference services."""
        try:
            return ml_management_service.reload_models(payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("ML runtime reload endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.patch("/ml/runtime/default-thresholds", summary="Update default model thresholds")
    def ml_update_default_thresholds(payload: MlUpdateDefaultThresholdRequest) -> dict:
        """Update HIGH/MEDIUM thresholds used by default prediction actions."""
        try:
            return ml_management_service.update_default_thresholds(payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("ML threshold update endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/ml/score", summary="Infer risk tier from feature payload")
    def ml_score(payload: RiskFeatureInput) -> dict:
        """Run risk-tier inference using trained model artifact."""
        try:
            return ml_orchestrator.score_risk(payload)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
        except Exception as exc:
            logger.exception("ML score endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/risk/recommend-deposit", summary="Rule-based deposit recommendation")
    def risk_recommend_deposit(payload: DepositRecommendationRequest) -> dict:
        """Recommend required deposit using deterministic policy."""
        try:
            return ml_orchestrator.recommend_deposit_policy(payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Policy deposit recommendation failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/ml/deposit-health", summary="Deposit model health")
    def ml_deposit_health() -> dict:
        """Return deposit model availability status."""
        return {
            "ml_enabled": settings.ml_enabled,
            "deposit_model_loaded": bool(deposit_inference and deposit_inference.is_loaded),
            "deposit_model_path": settings.ml_deposit_model_path,
        }

    @router.get("/ml/default-health", summary="Default prediction model health")
    def ml_default_health() -> dict:
        """Return default prediction model status."""
        return {
            "ml_enabled": settings.ml_enabled,
            "default_model_loaded": bool(default_inference and default_inference.is_loaded),
            "default_model_path": settings.ml_default_model_path,
            "high_threshold": settings.ml_default_high_threshold,
            "medium_threshold": settings.ml_default_medium_threshold,
        }

    @router.post("/ml/predict-default", summary="Predict missed next installment probability")
    def ml_predict_default(payload: DefaultPredictionInput) -> dict:
        """Predict next-installment default probability and recommended actions."""
        try:
            return ml_orchestrator.predict_default(payload)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
        except Exception as exc:
            logger.exception("Default prediction endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/ml/recommend-deposit", summary="ML deposit recommendation with fallback")
    def ml_recommend_deposit(payload: DepositRecommendationRequest) -> dict:
        """Recommend deposit using ML model; falls back to policy if model unavailable."""
        try:
            return ml_orchestrator.recommend_deposit_ml(payload)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
        except Exception as exc:
            logger.exception("ML deposit recommendation endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/ml/orchestrate", summary="Run multi-model ML orchestration")
    def ml_orchestrate(payload: MlOrchestrationRequest) -> dict:
        """Run combined ML flows from one request payload."""
        try:
            return ml_orchestrator.orchestrate(payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
        except Exception as exc:
            logger.exception("ML orchestration endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/ml/emi/evaluate", summary="Evaluate ML outputs across EMI plans")
    def ml_emi_evaluate(payload: MlEmiPlanEvaluationRequest) -> dict:
        """Run risk/default/deposit evaluation for all or selected EMI plans."""
        try:
            return ml_orchestrator.evaluate_emi_plans(payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
        except Exception as exc:
            logger.exception("ML EMI plan evaluation endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/oracle/update-prices", summary="Update oracle prices")
    def oracle_update_prices(payload: OracleUpdatePricesRequest) -> dict:
        """Update BNB/USD and BNB/INR prices."""
        try:
            return protocol_service.update_prices(payload.usd_price, payload.inr_price)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        except Exception as exc:
            logger.exception("Oracle update failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/oracle/prices", summary="Get oracle prices")
    def oracle_prices() -> dict:
        """Get currently tracked oracle prices."""
        try:
            return protocol_service.get_prices()
        except Exception as exc:
            logger.exception("Oracle price read failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/users/set-currency", summary="Set currency preference")
    def users_set_currency(payload: UserSetCurrencyRequest) -> dict:
        """Set wallet currency preference."""
        try:
            return protocol_service.set_currency(payload.wallet, payload.currency)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        except Exception as exc:
            logger.exception("Set currency failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/collateral/deposit", summary="Deposit collateral")
    def collateral_deposit(payload: CollateralRequest) -> dict:
        """Deposit BNB collateral."""
        try:
            return protocol_service.deposit_collateral(payload.wallet, payload.amount_bnb)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        except Exception as exc:
            logger.exception("Collateral deposit failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/collateral/withdraw", summary="Withdraw collateral")
    def collateral_withdraw(payload: CollateralRequest) -> dict:
        """Withdraw BNB collateral."""
        try:
            return protocol_service.withdraw_collateral(payload.wallet, payload.amount_bnb)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        except Exception as exc:
            logger.exception("Collateral withdraw failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/borrow", summary="Borrow debt token")
    def borrow(payload: BorrowRequest) -> dict:
        """Borrow using collateral and selected currency."""
        try:
            result = protocol_service.borrow(payload.wallet, payload.amount, payload.currency)
            _sync_user_loan_state(
                user_repository=user_repository,
                wallet=payload.wallet,
                action="borrow",
                result_payload=result,
            )
            return result
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        except Exception as exc:
            logger.exception("Borrow failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/repay", summary="Repay debt")
    def repay(payload: RepayRequest) -> dict:
        """Repay outstanding debt."""
        try:
            result = protocol_service.repay(payload.wallet, payload.amount)
            _sync_user_loan_state(
                user_repository=user_repository,
                wallet=payload.wallet,
                action="repay",
                result_payload=result,
            )
            return result
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        except Exception as exc:
            logger.exception("Repay failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/account/{wallet}", summary="Get account status")
    def account_status(wallet: str) -> dict:
        """Get account status by wallet."""
        try:
            return protocol_service.account(wallet)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        except Exception as exc:
            logger.exception("Account status read failed wallet=%s", wallet)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/positions/all", summary="Get all positions")
    def positions_all(liquidatable_only: bool = False) -> dict:
        """Get all tracked positions with optional liquidatable filter."""
        try:
            return protocol_service.all_positions(liquidatable_only=liquidatable_only)
        except Exception as exc:
            logger.exception("All positions read failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/liquidate", summary="Liquidate position")
    def liquidate(payload: LiquidateRequest) -> dict:
        """Liquidate an unhealthy position and archive event."""
        try:
            return protocol_service.liquidate(payload.wallet)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        except Exception as exc:
            logger.exception("Liquidation failed wallet=%s", payload.wallet)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/archive/liquidations", summary="Get liquidation archive")
    def archive_liquidations(page: int = 0, page_size: int = 20, currency: Optional[str] = None) -> dict:
        """Get paginated liquidation archive."""
        try:
            if page < 0:
                raise ValueError("page must be >= 0")
            if page_size <= 0 or page_size > 100:
                raise ValueError("page_size must be between 1 and 100")
            return protocol_service.archive_liquidations(page=page, page_size=page_size, currency=currency)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        except Exception as exc:
            logger.exception("Archive query failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/stats", summary="Get global stats")
    def stats() -> dict:
        """Get global protocol stats."""
        try:
            return protocol_service.stats()
        except Exception as exc:
            logger.exception("Stats read failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post("/users", summary="Create user", response_model=UserModel, status_code=status.HTTP_201_CREATED)
    def create_user(payload: UserModel) -> UserModel:
        """Create a user document in Firestore including wallet address list."""
        try:
            return _require_user_repository(user_repository).create(payload)
        except HTTPException:
            raise
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Create user endpoint failed user_id=%s", payload.user_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.post(
        "/users/from-firebase",
        summary="Create or update user from Firebase profile (upsert); stores user details and wallets in Firestore.",
        response_model=UserModel,
        status_code=status.HTTP_201_CREATED,
    )
    def create_user_from_firebase(payload: UserFromFirebaseCreateRequest) -> UserModel:
        """Upsert user in Firestore: fetch profile from Firebase profile collection, persist/update user and wallets."""
        try:
            if firebase_manager is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Firebase client is not configured or unavailable.",
                )

            repo = _require_user_repository(user_repository)
            profile_doc = firebase_manager.get_document(
                collection_name=settings.firebase_profile_collection,
                document_id=payload.user_id,
            )
            profile_doc = profile_doc or {}
            email, phone, full_name = _extract_profile_fields(profile_doc, payload.user_id)
            user = UserModel(
                user_id=payload.user_id,
                email=email,
                phone=phone,
                full_name=full_name,
                currency_code=payload.currency_code,
                currency_symbol=payload.currency_symbol,
                wallet_address=payload.wallet_address,
                notification_channels=payload.notification_channels,
                autopay_enabled=payload.autopay_enabled,
                kyc_level=payload.kyc_level,
            )
            try:
                existing = repo.get_by_id(payload.user_id)
                merged = UserModel(
                    user_id=existing.user_id,
                    email=email or existing.email,
                    phone=phone or existing.phone,
                    full_name=full_name or existing.full_name,
                    currency_code=payload.currency_code or existing.currency_code,
                    currency_symbol=payload.currency_symbol or existing.currency_symbol,
                    wallet_address=payload.wallet_address if (payload.wallet_address and len(payload.wallet_address) > 0) else existing.wallet_address,
                    notification_channels=payload.notification_channels if (payload.notification_channels and len(payload.notification_channels) > 0) else existing.notification_channels,
                    autopay_enabled=payload.autopay_enabled,
                    kyc_level=payload.kyc_level if payload.kyc_level is not None else existing.kyc_level,
                    status=existing.status,
                    version=existing.version,
                    created_at=existing.created_at,
                    on_time_payment_count=existing.on_time_payment_count,
                    late_payment_count=existing.late_payment_count,
                    top_up_count=existing.top_up_count,
                    loan_currency=existing.loan_currency,
                    total_borrowed_fiat=existing.total_borrowed_fiat,
                    total_repaid_fiat=existing.total_repaid_fiat,
                    outstanding_debt_fiat=existing.outstanding_debt_fiat,
                    last_loan_action=existing.last_loan_action,
                    last_loan_action_at=existing.last_loan_action_at,
                )
                merged.version += 1
                return repo.update(merged)
            except ModelNotFoundError:
                return repo.create(user)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Create user from firebase failed user_id=%s", payload.user_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/users/{user_id}", summary="Get user", response_model=UserModel)
    def get_user(user_id: str) -> UserModel:
        """Fetch one user document by id from Firestore."""
        try:
            return _require_user_repository(user_repository).get_by_id(user_id)
        except HTTPException:
            raise
        except ModelNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Get user endpoint failed user_id=%s", user_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get(
        "/users/{user_id}/wallets",
        summary="Get user wallet details",
        response_model=UserWalletDetailsResponse,
    )
    def get_user_wallets(user_id: str) -> UserWalletDetailsResponse:
        """Fetch only wallet details for a user by id."""
        try:
            user = _require_user_repository(user_repository).get_by_id(user_id)
            wallets = list(user.wallet_address or [])
            return UserWalletDetailsResponse(
                user_id=user.user_id,
                wallet_address=wallets,
                wallet_count=len(wallets),
            )
        except HTTPException:
            raise
        except ModelNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Get user wallets endpoint failed user_id=%s", user_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.put("/users/{user_id}", summary="Update user", response_model=UserModel)
    def update_user(user_id: str, payload: UserModel) -> UserModel:
        """Update one user document in Firestore with version checks."""
        try:
            payload.user_id = user_id
            return _require_user_repository(user_repository).update(payload)
        except HTTPException:
            raise
        except ModelNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        except VersionConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        except Exception as exc:
            logger.exception("Update user endpoint failed user_id=%s", user_id)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    return router


def build_firebase_router(firebase_manager: Optional[FirebaseClientManager]) -> APIRouter:
    """Build Firebase utility routes using the shared client manager."""
    router = APIRouter(prefix="/firebase", tags=["firebase"])

    @router.get("/health", summary="Firebase client health")
    def firebase_health() -> dict[str, str]:
        """Check if Firebase client manager can access configured datastore."""
        try:
            if firebase_manager is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Firebase client is not configured or unavailable.",
                )
            firebase_manager.query_documents(collection_name="_healthcheck", limit=1)
            return {"status": "ok"}
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Firebase health check failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    return router


def build_web3_router(web3_manager: Optional[Web3ClientManager], read_function: str) -> APIRouter:
    """Build Web3 utility routes using the shared Web3 client manager."""
    router = APIRouter(tags=["web3"])

    @router.get("/get-data", summary="Get contract values from BSC and opBNB")
    def get_data() -> dict:
        """Read configured smart contract value from both chains."""
        if web3_manager is None:
            return {
                "available": False,
                "bsc_testnet_value": None,
                "opbnb_testnet_value": None,
                "function_name": read_function,
                "message": "Web3 is not configured or unavailable.",
            }
        try:
            out = web3_manager.read_contract_values(read_function)
            out["available"] = True
            return out
        except Exception as exc:
            logger.exception("Web3 get-data endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/web3/health", summary="Web3 provider health")
    def web3_health() -> dict:
        """Check chain provider connectivity."""
        if web3_manager is None:
            return {
                "bsc_connected": False,
                "opbnb_connected": False,
                "available": False,
                "message": "Web3 is not configured or unavailable.",
            }
        try:
            out = web3_manager.health()
            out["available"] = True
            return out
        except Exception as exc:
            logger.exception("Web3 health endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/web3/get-data", summary="Get contract values (namespaced)")
    def web3_get_data() -> dict:
        """Namespaced alias for contract read endpoint."""
        if web3_manager is None:
            return {
                "available": False,
                "bsc_testnet_value": None,
                "opbnb_testnet_value": None,
                "function_name": read_function,
                "message": "Web3 is not configured or unavailable.",
            }
        try:
            out = web3_manager.read_contract_values(read_function)
            out["available"] = True
            return out
        except Exception as exc:
            logger.exception("Web3 namespaced get-data endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/web3/account/{wallet}", summary="Get on-chain wallet account snapshot")
    def web3_account(wallet: str, chain: str = Query(default="bsc")) -> dict:
        """Fetch native balance + contract state + remaining debt for a wallet."""
        if web3_manager is None:
            return {
                "available": False,
                "wallet": wallet.strip(),
                "chain": chain.lower(),
                "contract_address": None,
                "native_balance_wei": "0",
                "native_balance_bnb": "0",
                "account_state": None,
                "warnings": ["Web3 is not configured or unavailable."],
            }
        try:
            return _require_web3_manager(web3_manager).get_wallet_protocol_summary(wallet=wallet, chain=chain)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        except Exception as exc:
            logger.exception("Web3 account snapshot endpoint failed wallet=%s chain=%s", wallet, chain)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/web3/tx-history/{wallet}", summary="Get on-chain wallet transaction history")
    def web3_tx_history(
        wallet: str,
        chain: str = Query(default="bsc"),
        from_block: int = Query(default=0, ge=0),
        to_block: str = Query(default="latest"),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict:
        """Fetch wallet event history from contract logs with tx hashes."""
        if web3_manager is None:
            return {
                "available": False,
                "wallet": wallet.strip(),
                "chain": chain.lower(),
                "contract_address": None,
                "from_block": from_block,
                "to_block": to_block,
                "total_records": 0,
                "returned_records": 0,
                "records": [],
                "warnings": ["Web3 is not configured or unavailable."],
            }
        try:
            return _require_web3_manager(web3_manager).get_wallet_transaction_history(
                wallet=wallet,
                chain=chain,
                from_block=from_block,
                to_block=to_block,
                limit=limit,
            )
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        except Exception as exc:
            logger.exception(
                "Web3 transaction history endpoint failed wallet=%s chain=%s from_block=%s to_block=%s limit=%s",
                wallet,
                chain,
                from_block,
                to_block,
                limit,
            )
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    return router
