"""Custom exceptions for model and repository layers."""


class ModelError(Exception):
    """Base class for model-related failures."""


class ModelValidationError(ModelError):
    """Raised when model data fails custom business validation."""


class ModelNotFoundError(ModelError):
    """Raised when a requested document does not exist."""


class VersionConflictError(ModelError):
    """Raised when optimistic concurrency version checks fail."""
