"""Firestore implementation of the user repository."""

import logging
from typing import List, Optional

from pydantic import ValidationError

from core.firebase_client_manager import FirebaseClientManager
from models.enums import UserStatus
from models.exceptions import ModelNotFoundError, VersionConflictError
from models.users import UserModel


logger = logging.getLogger(__name__)


class FirestoreUserRepository:
    """Persist and fetch user documents from Cloud Firestore."""

    def __init__(
        self,
        firebase_manager: FirebaseClientManager,
        collection_name: str = "users",
    ) -> None:
        """Initialize Firestore client and target collection.

        Args:
            firebase_manager: Shared Firebase client manager instance.
            collection_name: Firestore collection name for users.
        """
        try:
            self._firebase_manager = firebase_manager
            self._collection_name = collection_name
            logger.info("Initialized FirestoreUserRepository collection=%s", collection_name)
        except Exception:
            logger.exception("Failed to initialize Firestore client.")
            raise

    def create(self, model: UserModel) -> UserModel:
        """Create and persist a user document.

        Args:
            model: User model payload.

        Returns:
            UserModel: Persisted user with assigned Firestore id.
        """
        try:
            payload = model.to_firestore()
            stored = self._firebase_manager.set_document(
                collection_name=self._collection_name,
                document_id=model.user_id,
                payload=payload,
                merge=False,
            )
            return UserModel.from_firestore(stored, doc_id=model.user_id)
        except ValidationError:
            logger.exception("User validation failed while creating user_id=%s", model.user_id)
            raise
        except Exception:
            logger.exception("Failed to create user_id=%s", model.user_id)
            raise

    def get_by_id(self, model_id: str) -> UserModel:
        """Fetch user by user identifier.

        Raises:
            ModelNotFoundError: If document does not exist.
            ValidationError: If document shape is invalid.
        """
        try:
            payload = self._firebase_manager.get_document(self._collection_name, model_id)
            if payload is None:
                raise ModelNotFoundError("User not found: {0}".format(model_id))
            return UserModel.from_firestore(payload, doc_id=model_id)
        except ModelNotFoundError:
            raise
        except ValidationError:
            logger.exception("Invalid user payload in Firestore user_id=%s", model_id)
            raise
        except Exception:
            logger.exception("Failed to get user_id=%s", model_id)
            raise

    def update(self, model: UserModel) -> UserModel:
        """Update an existing user using optimistic version checks.

        Raises:
            ModelNotFoundError: If user does not exist.
            VersionConflictError: If version is stale.
        """
        try:
            current_payload = self._firebase_manager.get_document(self._collection_name, model.user_id)
            if current_payload is None:
                raise ModelNotFoundError("User not found: {0}".format(model.user_id))

            current = UserModel.from_firestore(current_payload, doc_id=model.user_id)
            if model.version <= current.version:
                raise VersionConflictError("Version conflict for user_id={0}".format(model.user_id))

            payload = model.to_firestore()
            updated_payload = self._firebase_manager.update_document(
                collection_name=self._collection_name,
                document_id=model.user_id,
                payload=payload,
            )
            return UserModel.from_firestore(updated_payload, doc_id=model.user_id)
        except (ModelNotFoundError, VersionConflictError):
            raise
        except ValidationError:
            logger.exception("User validation failed while updating user_id=%s", model.user_id)
            raise
        except Exception:
            logger.exception("Failed to update user_id=%s", model.user_id)
            raise

    def soft_delete(self, model_id: str) -> None:
        """Soft delete a user by marking `is_deleted=True`."""
        try:
            payload = self._firebase_manager.get_document(self._collection_name, model_id)
            if payload is None:
                raise ModelNotFoundError("User not found: {0}".format(model_id))
            self._firebase_manager.soft_delete_document(self._collection_name, model_id)
        except ModelNotFoundError:
            raise
        except Exception:
            logger.exception("Failed to soft delete user_id=%s", model_id)
            raise

    def get_active_users(self) -> List[UserModel]:
        """Return non-deleted active users."""
        try:
            payloads = self._firebase_manager.query_documents(
                collection_name=self._collection_name,
                filters=[
                    ("is_deleted", "==", False),
                    ("status", "==", UserStatus.ACTIVE.value),
                ],
            )
            return [UserModel.from_firestore(payload, doc_id=payload.get("id")) for payload in payloads]
        except ValidationError:
            logger.exception("Invalid user payload while listing active users.")
            raise
        except Exception:
            logger.exception("Failed to list active users.")
            raise
