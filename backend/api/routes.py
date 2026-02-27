"""Backward-compatible route exports.

Prefer importing from `api.router` for new code.
"""

from .router import build_router

__all__ = ["build_router"]
