"""Reusable Firebase Firestore client manager for CRUD and query operations."""

from datetime import datetime, timezone
import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from google.cloud import firestore
from google.oauth2 import service_account


logger = logging.getLogger(__name__)

FilterTuple = Tuple[str, str, Any]


def _utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class FirebaseClientManager:
    """Encapsulates Firestore client setup and common data operations."""

    def __init__(self, project_id: Optional[str] = None, credentials_path: Optional[str] = None) -> None:
        """Initialize Firestore client.

        Args:
            project_id: Optional Google Cloud project id override.
            credentials_path: Optional path to Firebase service account json file.
        """
        try:
            if credentials_path:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
                credentials = service_account.Credentials.from_service_account_file(credentials_path)
                self._client = firestore.Client(project=project_id, credentials=credentials)
            else:
                self._client = firestore.Client(project=project_id) if project_id else firestore.Client()
            logger.info("FirebaseClientManager initialized for project_id=%s", project_id)
        except Exception:
            logger.exception("Failed to initialize Firebase Firestore client.")
            raise

    def set_document(
        self,
        collection_name: str,
        document_id: str,
        payload: Dict[str, Any],
        merge: bool = False,
    ) -> Dict[str, Any]:
        """Create or replace a Firestore document.

        Args:
            collection_name: Target collection.
            document_id: Firestore document id.
            payload: Document payload.
            merge: If true, merge with existing fields.

        Returns:
            Dict[str, Any]: Persisted document payload.
        """
        try:
            ref = self._client.collection(collection_name).document(document_id)
            safe_payload = dict(payload)
            safe_payload["updated_at"] = safe_payload.get("updated_at", _utc_now())
            safe_payload["created_at"] = safe_payload.get("created_at", _utc_now())
            ref.set(safe_payload, merge=merge)
            snapshot = ref.get()
            return snapshot.to_dict() or {}
        except Exception:
            logger.exception(
                "Failed to set document collection=%s document_id=%s",
                collection_name,
                document_id,
            )
            raise

    def get_document(self, collection_name: str, document_id: str) -> Optional[Dict[str, Any]]:
        """Get one Firestore document by id."""
        try:
            snapshot = self._client.collection(collection_name).document(document_id).get()
            if not snapshot.exists:
                return None
            data = snapshot.to_dict() or {}
            data["id"] = snapshot.id
            return data
        except Exception:
            logger.exception(
                "Failed to get document collection=%s document_id=%s",
                collection_name,
                document_id,
            )
            raise

    def update_document(
        self,
        collection_name: str,
        document_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update fields in an existing Firestore document."""
        try:
            ref = self._client.collection(collection_name).document(document_id)
            safe_payload = dict(payload)
            safe_payload["updated_at"] = _utc_now()
            ref.set(safe_payload, merge=True)
            snapshot = ref.get()
            return snapshot.to_dict() or {}
        except Exception:
            logger.exception(
                "Failed to update document collection=%s document_id=%s",
                collection_name,
                document_id,
            )
            raise

    def soft_delete_document(self, collection_name: str, document_id: str) -> None:
        """Soft delete a document by setting `is_deleted=True`."""
        try:
            ref = self._client.collection(collection_name).document(document_id)
            ref.set({"is_deleted": True, "updated_at": _utc_now()}, merge=True)
        except Exception:
            logger.exception(
                "Failed to soft delete document collection=%s document_id=%s",
                collection_name,
                document_id,
            )
            raise

    def delete_document(self, collection_name: str, document_id: str) -> None:
        """Hard delete a Firestore document."""
        try:
            self._client.collection(collection_name).document(document_id).delete()
        except Exception:
            logger.exception(
                "Failed to hard delete document collection=%s document_id=%s",
                collection_name,
                document_id,
            )
            raise

    def query_documents(
        self,
        collection_name: str,
        filters: Optional[Sequence[FilterTuple]] = None,
        order_by: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Run a filtered query and return document payloads.

        Args:
            collection_name: Target collection.
            filters: Sequence of tuples `(field, op, value)`.
            order_by: Optional field name for sorting.
            limit: Optional maximum result count.
        """
        try:
            query = self._client.collection(collection_name)
            for field_name, operator, value in filters or []:
                query = query.where(field_name, operator, value)
            if order_by:
                query = query.order_by(order_by)
            if limit is not None:
                query = query.limit(limit)

            documents: List[Dict[str, Any]] = []
            for snapshot in query.stream():
                payload = snapshot.to_dict() or {}
                payload["id"] = snapshot.id
                documents.append(payload)
            return documents
        except Exception:
            logger.exception("Failed query for collection=%s", collection_name)
            raise
