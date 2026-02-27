"""Primary API router module with Firebase-backed endpoints."""

import logging
from typing import Optional, Union

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from core import FirebaseClientManager, Web3ClientManager
from core.config import AppSettings
from models.exceptions import ModelNotFoundError, VersionConflictError
from models.users import UserModel, WalletAddressModel
from repositories.firestore_user_repository import FirestoreUserRepository


logger = logging.getLogger(__name__)


class UserFromFirebaseCreateRequest(BaseModel):
    """Request payload to sync user profile from Firebase by `user_id`."""

    user_id: str = Field(..., min_length=3)
    wallet_address: list[WalletAddressModel] = Field(default_factory=list)
    notification_channels: list[str] = Field(default_factory=list)
    autopay_enabled: bool = Field(default=False)
    kyc_level: int = Field(default=0, ge=0, le=3)


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


def build_router(settings: AppSettings) -> APIRouter:
    """Build and return the top-level API router.

    Args:
        settings: Application settings payload.

    Returns:
        APIRouter: Fully configured router with all endpoints.
    """
    router = APIRouter()

    firebase_manager: Optional[FirebaseClientManager] = None
    user_repository: Optional[FirestoreUserRepository] = None
    web3_manager: Optional[Web3ClientManager] = None
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

    router.include_router(build_firebase_router(firebase_manager))
    router.include_router(build_web3_router(web3_manager, settings.web3_read_function))

    @router.get("/", summary="Root endpoint")
    def read_root() -> dict:
        """Return a basic message confirming service availability."""
        return {"message": "Ping Masters API is running"}

    @router.get("/health", summary="Health check")
    def health_check() -> dict:
        """Return service health status for probes and monitors."""
        return {"status": "ok"}

    @router.get("/settings", summary="Settings snapshot")
    def get_settings_snapshot() -> dict[str, Union[str, bool, int]]:
        """Expose non-sensitive settings useful for local verification."""
        return {
            "app_name": settings.app_name,
            "debug": settings.debug,
            "host": settings.host,
            "port": settings.port,
            "firebase_enabled": settings.firebase_enabled,
            "web3_enabled": settings.web3_enabled,
        }

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
        summary="Create user from firebase profile by user_id",
        response_model=UserModel,
        status_code=status.HTTP_201_CREATED,
    )
    def create_user_from_firebase(payload: UserFromFirebaseCreateRequest) -> UserModel:
        """Fetch profile fields from Firebase and persist mapped user record."""
        try:
            if firebase_manager is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Firebase client is not configured or unavailable.",
                )

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
                wallet_address=payload.wallet_address,
                notification_channels=payload.notification_channels,
                autopay_enabled=payload.autopay_enabled,
                kyc_level=payload.kyc_level,
            )
            return _require_user_repository(user_repository).create(user)
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
        try:
            return _require_web3_manager(web3_manager).read_contract_values(read_function)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Web3 get-data endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/web3/health", summary="Web3 provider health")
    def web3_health() -> dict[str, bool]:
        """Check chain provider connectivity."""
        try:
            return _require_web3_manager(web3_manager).health()
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Web3 health endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    @router.get("/web3/get-data", summary="Get contract values (namespaced)")
    def web3_get_data() -> dict:
        """Namespaced alias for contract read endpoint."""
        try:
            return _require_web3_manager(web3_manager).read_contract_values(read_function)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Web3 namespaced get-data endpoint failed.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    return router
