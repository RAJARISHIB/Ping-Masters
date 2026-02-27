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

    return AppSettings(app_name=app_name, debug=debug, host=host, port=port)
