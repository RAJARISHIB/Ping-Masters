"""Central logging configuration for the backend application."""

import logging


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the root logger once for consistent application logs."""
    if logging.getLogger().handlers:
        return
    logging.basicConfig(level=level, format=LOG_FORMAT)


def get_logger(name: str) -> logging.Logger:
    """Create or retrieve a module logger."""
    return logging.getLogger(name)
