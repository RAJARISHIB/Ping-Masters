"""Configuration loading utilities for YAML-based application settings."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Optional

import yaml

from .logging_config import get_logger


logger = get_logger(__name__)
_BASE_DIR = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _BASE_DIR / "config.yml"


@dataclass(frozen=True)
class AppSettings:
    """Application settings loaded from YAML configuration file."""

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
    liquidator_enabled: bool
    liquidator_rpc_url: Optional[str]
    liquidator_contract_address: Optional[str]
    liquidator_contract_abi_json: Optional[str]
    liquidator_private_key: Optional[str]
    liquidator_address: Optional[str]
    liquidator_poll_interval_sec: int
    liquidator_health_threshold: float
    liquidator_chain_id: int
    liquidator_gas_limit: int
    liquidator_gas_price_gwei: int
    liquidator_price_function: str
    liquidator_health_function: str
    liquidator_execute_function: str
    liquidator_borrowers: list[str]
    currency_api_base_url: str
    currency_api_timeout_sec: int


def _to_bool(value: Any, default: bool = False) -> bool:
    """Convert value to bool with a default fallback."""
    try:
        if isinstance(value, bool):
            return value
        return value.strip().lower() in {"1", "true", "yes", "on"}
    except (AttributeError, ValueError):
        logger.warning("Invalid boolean value '%s'. Using default=%s", value, default)
        return default


def _to_int(value: Any, default: int) -> int:
    """Convert value to int with a default fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning("Invalid integer value '%s'. Using default=%s", value, default)
        return default


def _to_float(value: Any, default: float) -> float:
    """Convert value to float with a default fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning("Invalid float value '%s'. Using default=%s", value, default)
        return default


def _to_list(value: Any) -> list[str]:
    """Convert list-like or comma-separated value to list[str]."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _to_json_string(value: Any, default: str = "[]") -> str:
    """Convert value into JSON string for ABI compatibility."""
    try:
        if value is None:
            return default
        if isinstance(value, str):
            return value
        return json.dumps(value)
    except Exception:
        logger.exception("Failed to serialize value as JSON string.")
        return default


def _read_config() -> dict:
    """Read and parse YAML configuration."""
    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            config_data = yaml.safe_load(config_file) or {}
        logger.info("Configuration loaded from %s", _CONFIG_PATH)
        return config_data
    except FileNotFoundError:
        logger.warning("Config file not found at %s. Falling back to defaults.", _CONFIG_PATH)
        return {}
    except Exception:
        logger.exception("Failed to load config file from %s", _CONFIG_PATH)
        return {}

def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Backward-compatible config reader using dot-notation keys."""
    try:
        data = _read_config()
        current: Any = data
        for part in key.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        if current is None:
            return default
        return str(current)
    except Exception:
        logger.exception("Failed to read config key '%s'.", key)
        return default


def load_settings() -> AppSettings:
    """Load and validate application settings from `config.yml`."""
    config = _read_config()
    app_cfg = config.get("app", {})
    firebase_cfg = config.get("firebase", {})
    web3_cfg = config.get("web3", {})
    liquidator_cfg = config.get("liquidator", {})

    app_name = str(app_cfg.get("name", "Ping Masters API"))
    debug = _to_bool(app_cfg.get("debug", False), False)
    host = str(app_cfg.get("host", "127.0.0.1"))
    port = _to_int(app_cfg.get("port", 8000), 8000)

    firebase_enabled = _to_bool(firebase_cfg.get("enabled", False), False)
    firebase_project_id = firebase_cfg.get("project_id")
    firebase_credentials_path = firebase_cfg.get("credentials_path")
    firebase_users_collection = str(firebase_cfg.get("users_collection", "users"))
    firebase_profile_collection = str(firebase_cfg.get("profile_collection", "firebase_users"))

    web3_enabled = _to_bool(web3_cfg.get("enabled", False), False)
    bsc_rpc_url = web3_cfg.get("bsc_rpc_url")
    opbnb_rpc_url = web3_cfg.get("opbnb_rpc_url")
    contract_abi_json = _to_json_string(web3_cfg.get("contract_abi_json"), default="[]")
    bsc_contract_address = web3_cfg.get("bsc_contract_address")
    opbnb_contract_address = web3_cfg.get("opbnb_contract_address")
    web3_read_function = str(web3_cfg.get("read_function", "getValue"))

    liquidator_enabled = _to_bool(liquidator_cfg.get("enabled", False), False)
    liquidator_rpc_url = liquidator_cfg.get("rpc_url", bsc_rpc_url)
    liquidator_contract_address = liquidator_cfg.get("contract_address", bsc_contract_address)
    liquidator_contract_abi_json = _to_json_string(
        liquidator_cfg.get("contract_abi_json", contract_abi_json),
        default="[]",
    )
    liquidator_private_key = liquidator_cfg.get("private_key")
    liquidator_address = liquidator_cfg.get("address")
    liquidator_poll_interval_sec = _to_int(liquidator_cfg.get("poll_interval_sec", 10), 10)
    liquidator_health_threshold = _to_float(liquidator_cfg.get("health_threshold", 1.0), 1.0)
    liquidator_chain_id = _to_int(liquidator_cfg.get("chain_id", 97), 97)
    liquidator_gas_limit = _to_int(liquidator_cfg.get("gas_limit", 2000000), 2000000)
    liquidator_gas_price_gwei = _to_int(liquidator_cfg.get("gas_price_gwei", 10), 10)
    liquidator_price_function = str(liquidator_cfg.get("price_function", "getBNBPrice"))
    liquidator_health_function = str(liquidator_cfg.get("health_function", "getHealthFactor"))
    liquidator_execute_function = str(liquidator_cfg.get("execute_function", "liquidate"))
    liquidator_borrowers = _to_list(liquidator_cfg.get("borrowers", []))
    currency_cfg = config.get("currency_api", {})
    currency_api_base_url = str(currency_cfg.get("base_url", "https://api.frankfurter.app"))
    currency_api_timeout_sec = _to_int(currency_cfg.get("timeout_sec", 10), 10)

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
        liquidator_enabled=liquidator_enabled,
        liquidator_rpc_url=liquidator_rpc_url,
        liquidator_contract_address=liquidator_contract_address,
        liquidator_contract_abi_json=liquidator_contract_abi_json,
        liquidator_private_key=liquidator_private_key,
        liquidator_address=liquidator_address,
        liquidator_poll_interval_sec=liquidator_poll_interval_sec,
        liquidator_health_threshold=liquidator_health_threshold,
        liquidator_chain_id=liquidator_chain_id,
        liquidator_gas_limit=liquidator_gas_limit,
        liquidator_gas_price_gwei=liquidator_gas_price_gwei,
        liquidator_price_function=liquidator_price_function,
        liquidator_health_function=liquidator_health_function,
        liquidator_execute_function=liquidator_execute_function,
        liquidator_borrowers=liquidator_borrowers,
        currency_api_base_url=currency_api_base_url,
        currency_api_timeout_sec=currency_api_timeout_sec,
    )
