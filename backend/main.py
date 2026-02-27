"""Application entrypoint for the Ping Masters FastAPI backend."""

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure repo root and ml package are importable
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND_DIR = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from api.router import build_router
from api.risk_routes import build_risk_router
from core import get_logger, load_settings, setup_logging
from services import LiquidationPoller


setup_logging()
logger = get_logger(__name__)


def create_app() -> FastAPI:
    """Create and configure a FastAPI application instance."""
    settings = load_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:4200",
            "http://127.0.0.1:4200",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(build_router(settings))
    app.include_router(build_risk_router())

    # ── Background services ──────────────────────────────────────────────
    poller = LiquidationPoller(settings=settings)
    app.state.liquidation_poller = poller

    @app.on_event("startup")
    async def _startup_background_services() -> None:
        """Start background services on application startup."""
        try:
            await app.state.liquidation_poller.start()
        except Exception:
            logger.exception("Failed to start background services during startup.")

    @app.on_event("shutdown")
    async def _shutdown_background_services() -> None:
        """Stop background services on application shutdown."""
        try:
            await app.state.liquidation_poller.stop()
        except Exception:
            logger.exception("Failed to stop background services during shutdown.")

    logger.info("Application initialized: %s", settings.app_name)
    return app


app = create_app()


def run() -> None:
    """Start the ASGI server for local development."""
    settings = load_settings()
    try:
        uvicorn.run("main:app", host=settings.host, port=settings.port, reload=settings.debug)
    except Exception:
        logger.exception("Failed to start uvicorn server.")
        raise


if __name__ == "__main__":
    run()
