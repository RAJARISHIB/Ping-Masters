"""Application entrypoint for the Ping Masters FastAPI backend."""

from fastapi import FastAPI
import uvicorn

from api.routes import build_router
from core import get_logger, load_settings, setup_logging


setup_logging()
logger = get_logger(__name__)


def create_app() -> FastAPI:
    """Create and configure a FastAPI application instance."""
    settings = load_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.include_router(build_router(settings))
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
