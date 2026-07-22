"""Integration tests for the /documents/upload endpoint.

Tests:
- Non-admin gets 403 on upload
- Admin upload returns 202 Accepted immediately (response time < 0.5s)
"""

import io
import time

import pytest
from unittest.mock import patch, MagicMock

from app.auth.jwt import create_access_token


class TestUploadEndpoint:
    """Tests for POST /documents/upload."""

    def _get_auth_header(self, email: str, role: str) -> dict:
        """Create an Authorization header with a valid JWT."""
        token = create_access_token({"sub": email, "role": role})
        return {"Authorization": f"Bearer {token}"}

    def _make_pdf_file(self):
        """Create a minimal valid-looking file for upload testing."""
        # We don't need a real PDF for these tests — the upload endpoint
        # just saves the file and queues a Celery task. We mock the task.
        return ("test.pdf", io.BytesIO(b"%PDF-1.4 fake content"), "application/pdf")

    def test_viewer_cannot_upload(self, client, viewer_user):
        """A viewer should get 403 Forbidden when trying to upload."""
        headers = self._get_auth_header(viewer_user.email, "viewer")
        files = {"file": self._make_pdf_file()}
        data = {"title": "Test Doc", "min_role_level": "0"}

        response = client.post(
            "/documents/upload",
            headers=headers,
            files=files,
            data=data,
        )
        assert response.status_code == 403

    def test_manager_cannot_upload(self, client, manager_user):
        """A manager should get 403 Forbidden when trying to upload."""
        headers = self._get_auth_header(manager_user.email, "manager")
        files = {"file": self._make_pdf_file()}
        data = {"title": "Test Doc", "min_role_level": "0"}

        response = client.post(
            "/documents/upload",
            headers=headers,
            files=files,
            data=data,
        )
        assert response.status_code == 403

    @patch("app.ingestion.worker.ingest_document")
    def test_admin_upload_returns_202(self, mock_ingest, client, admin_user):
        """Admin upload returns 202 Accepted and response is fast (non-blocking)."""
        mock_ingest.delay = MagicMock()

        headers = self._get_auth_header(admin_user.email, "admin")
        files = {"file": self._make_pdf_file()}
        data = {"title": "Confidential Report", "min_role_level": "2"}

        start_time = time.time()
        response = client.post(
            "/documents/upload",
            headers=headers,
            files=files,
            data=data,
        )
        elapsed = time.time() - start_time

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "processing"
        assert body["title"] == "Confidential Report"
        assert "id" in body

        # Verify the response is fast — it should NOT be blocking on embedding
        assert elapsed < 0.5, (
            f"Upload took {elapsed:.2f}s — expected < 0.5s for async processing"
        )

        # Verify Celery task was queued
        mock_ingest.delay.assert_called_once()

    @patch("app.ingestion.worker.ingest_document")
    def test_upload_creates_document_row(self, mock_ingest, client, admin_user, db_session):
        """Upload should create a Document row with status='processing'."""
        from app.db.models import Document

        mock_ingest.delay = MagicMock()

        headers = self._get_auth_header(admin_user.email, "admin")
        files = {"file": self._make_pdf_file()}
        data = {"title": "Policy Doc", "min_role_level": "1"}

        response = client.post(
            "/documents/upload",
            headers=headers,
            files=files,
            data=data,
        )
        assert response.status_code == 202

        doc_id = response.json()["id"]
        import uuid
        doc = db_session.query(Document).filter(
            Document.id == uuid.UUID(doc_id)
        ).first()
        assert doc is not None
        assert doc.status == "processing"
        assert doc.min_role_level == 1
        assert doc.title == "Policy Doc"

    def test_upload_rejects_non_pdf(self, client, admin_user):
        """Upload should reject non-PDF files with 400."""
        headers = self._get_auth_header(admin_user.email, "admin")
        files = {"file": ("test.txt", io.BytesIO(b"not a pdf"), "text/plain")}
        data = {"title": "Bad File", "min_role_level": "0"}

        response = client.post(
            "/documents/upload",
            headers=headers,
            files=files,
            data=data,
        )
        assert response.status_code == 400

    def test_upload_without_auth_returns_422(self, client):
        """Upload without Authorization header returns 422."""
        files = {"file": self._make_pdf_file()}
        data = {"title": "Test", "min_role_level": "0"}

        response = client.post(
            "/documents/upload",
            files=files,
            data=data,
        )
        # Missing authorization header → 422 (FastAPI can't parse the dependency)
        assert response.status_code == 422
