"""Backward-compatible settings import surface.

Prefer importing from `core.config` for new code.
"""

from core.config import AppSettings, get_env, load_settings

__all__ = ["AppSettings", "get_env", "load_settings"]
