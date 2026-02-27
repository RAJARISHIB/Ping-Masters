"""HTTP route declarations for the FastAPI application."""

from fastapi import APIRouter
from typing import Union

from core.config import AppSettings


def build_router(settings: AppSettings) -> APIRouter:
    """Build and return application routes with injected settings."""
    router = APIRouter()

    @router.get("/", summary="Root endpoint")
    def read_root() -> dict[str, str]:
        """Return a basic message confirming service availability."""
        return {"message": "Ping Masters API is running"}

    @router.get("/health", summary="Health check")
    def health_check() -> dict[str, str]:
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
        }

    return router
