"""Configuration loading utilities for environment-based settings."""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .logging_config import get_logger


logger = get_logger(__name__)
_BASE_DIR = Path(__file__).resolve().parent.parent
_ENV_PATH = _BASE_DIR / ".env"


@dataclass(frozen=True)
class AppSettings:
    """Application settings loaded from environment variables."""

    app_name: str
    debug: bool
    host: str
    port: int
    firebase_enabled: bool
    firebase_project_id: Optional[str]
    firebase_credentials_path: Optional[str]
    firebase_users_collection: str
    firebase_profile_collection: str
    web3_enabled: bool
    bsc_rpc_url: Optional[str]
    opbnb_rpc_url: Optional[str]
    contract_abi_json: Optional[str]
    bsc_contract_address: Optional[str]
    opbnb_contract_address: Optional[str]
    web3_read_function: str


def _to_bool(value: str, default: bool = False) -> bool:
    """Convert string value to bool with a default fallback."""
    try:
        return value.strip().lower() in {"1", "true", "yes", "on"}
    except (AttributeError, ValueError):
        logger.warning("Invalid boolean value '%s'. Using default=%s", value, default)
        return default


def _to_int(value: str, default: int) -> int:
    """Convert string value to int with a default fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning("Invalid integer value '%s'. Using default=%s", value, default)
        return default


def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Return an environment variable value by key."""
    try:
        value = os.getenv(key, default)
        if value is None:
            logger.debug("Environment key '%s' not found and no default provided.", key)
        return value
    except Exception:
        logger.exception("Failed to read environment key '%s'.", key)
        return default


def load_settings() -> AppSettings:
    """Load and validate application settings from `.env` and process env."""
    try:
        load_dotenv(dotenv_path=_ENV_PATH)
        logger.info("Environment loaded from %s", _ENV_PATH)
    except Exception:
        logger.exception("Failed to load .env file from %s", _ENV_PATH)

    app_name = get_env("APP_NAME", "Ping Masters API") or "Ping Masters API"
    debug = _to_bool(get_env("DEBUG", "false") or "false")
    host = get_env("HOST", "127.0.0.1") or "127.0.0.1"
    port = _to_int(get_env("PORT", "8000"), 8000)
    firebase_enabled = _to_bool(get_env("FIREBASE_ENABLED", "false") or "false")
    firebase_project_id = get_env("FIREBASE_PROJECT_ID", None)
    firebase_credentials_path = get_env("FIREBASE_CREDENTIALS_PATH", None)
    firebase_users_collection = get_env("FIREBASE_USERS_COLLECTION", "users") or "users"
    firebase_profile_collection = get_env("FIREBASE_PROFILE_COLLECTION", "firebase_users") or "firebase_users"
    web3_enabled = _to_bool(get_env("WEB3_ENABLED", "false") or "false")
    bsc_rpc_url = get_env("BSC_RPC_URL", None)
    opbnb_rpc_url = get_env("OPBNB_RPC_URL", None)
    contract_abi_json = get_env("CONTRACT_ABI_JSON", None)
    bsc_contract_address = get_env("BSC_CONTRACT_ADDRESS", None)
    opbnb_contract_address = get_env("OPBNB_CONTRACT_ADDRESS", None)
    web3_read_function = get_env("WEB3_READ_FUNCTION", "getValue") or "getValue"

    return AppSettings(
        app_name=app_name,
        debug=debug,
        host=host,
        port=port,
        firebase_enabled=firebase_enabled,
        firebase_project_id=firebase_project_id,
        firebase_credentials_path=firebase_credentials_path,
        firebase_users_collection=firebase_users_collection,
        firebase_profile_collection=firebase_profile_collection,
        web3_enabled=web3_enabled,
        bsc_rpc_url=bsc_rpc_url,
        opbnb_rpc_url=opbnb_rpc_url,
        contract_abi_json=contract_abi_json,
        bsc_contract_address=bsc_contract_address,
        opbnb_contract_address=opbnb_contract_address,
        web3_read_function=web3_read_function,
    )
