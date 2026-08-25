"""Integration tests for the 2-step presigned upload flow:

    POST /documents/upload-url      → admin-only, generates a signed URL
    (client uploads PDF to Supabase directly — not exercised here)
    POST /documents/confirm-upload  → admin-only, queues the Celery task

Tests:
- Non-admin gets 403 on both upload-url and confirm-upload
- Admin upload-url returns a signed URL and creates a Document row
- Admin upload-url failure (Supabase raises) does not orphan the Document row
- confirm-upload queues the Celery task with the server-stored object_key,
  never the client-supplied one
- confirm-upload rejects a client-supplied object_key that doesn't match
  the one issued for this document
- confirm-upload rejects malformed object_key, unowned/missing documents,
  and documents that are no longer in 'processing'
"""

import uuid

import pytest
from unittest.mock import patch, MagicMock

from app.auth.jwt import create_access_token
from app.db.models import Document


def _auth_header(email: str, role: str) -> dict:
    token = create_access_token({"sub": email, "role": role})
    return {"Authorization": f"Bearer {token}"}


FAKE_SIGNED_URL_RESULT = {
    "signed_url": "https://supabase.example/storage/v1/object/upload/sign/documents/fake",
    "object_key": "",  # filled in per-test to match the generated document_id
    "token": "fake-signed-token",
    "expires_in": 600,
}


class TestUploadUrlEndpoint:
    """Tests for POST /documents/upload-url."""

    def test_viewer_cannot_request_upload_url(self, client, viewer_user):
        response = client.post(
            "/documents/upload-url",
            headers=_auth_header(viewer_user.email, "viewer"),
            json={
                "title": "Test Doc",
                "original_filename": "test.pdf",
                "min_role_level": 0,
            },
        )
        assert response.status_code == 403

    def test_manager_cannot_request_upload_url(self, client, manager_user):
        response = client.post(
            "/documents/upload-url",
            headers=_auth_header(manager_user.email, "manager"),
            json={
                "title": "Test Doc",
                "original_filename": "test.pdf",
                "min_role_level": 0,
            },
        )
        assert response.status_code == 403

    @patch("app.documents.routes.generate_upload_url")
    def test_admin_upload_url_returns_signed_url_and_creates_document(
        self, mock_generate_url, client, admin_user, db_session
    ):
        def fake_generate_upload_url(user_id, document_id):
            object_key = f"{user_id}/{document_id}/{uuid.uuid4()}.pdf"
            return {**FAKE_SIGNED_URL_RESULT, "object_key": object_key}

        mock_generate_url.side_effect = fake_generate_upload_url

        response = client.post(
            "/documents/upload-url",
            headers=_auth_header(admin_user.email, "admin"),
            json={
                "title": "Confidential Report",
                "original_filename": "report.pdf",
                "min_role_level": 2,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["signed_url"] == FAKE_SIGNED_URL_RESULT["signed_url"]
        assert body["object_key"]
        assert body["max_file_size_bytes"] == 50 * 1024 * 1024

        doc = (
            db_session.query(Document)
            .filter(Document.id == uuid.UUID(body["document_id"]))
            .first()
        )
        assert doc is not None
        assert doc.status == "processing"
        assert doc.title == "Confidential Report"
        assert doc.min_role_level == 2
        assert doc.object_key == body["object_key"]

    def test_upload_url_rejects_non_pdf_filename(self, client, admin_user):
        response = client.post(
            "/documents/upload-url",
            headers=_auth_header(admin_user.email, "admin"),
            json={
                "title": "Bad File",
                "original_filename": "notes.txt",
                "min_role_level": 0,
            },
        )
        assert response.status_code == 400

    def test_upload_url_rejects_invalid_min_role_level(self, client, admin_user):
        response = client.post(
            "/documents/upload-url",
            headers=_auth_header(admin_user.email, "admin"),
            json={
                "title": "Bad Level",
                "original_filename": "test.pdf",
                "min_role_level": 5,
            },
        )
        assert response.status_code == 400

    @patch("app.documents.routes.generate_upload_url")
    def test_upload_url_failure_does_not_orphan_document_row(
        self, mock_generate_url, client, admin_user, db_session
    ):
        """If the Supabase call raises, the Document row created just
        before it must be deleted, not left behind stuck in 'processing'
        with an empty object_key forever."""
        mock_generate_url.side_effect = RuntimeError("Supabase outage")

        docs_before = db_session.query(Document).count()

        response = client.post(
            "/documents/upload-url",
            headers=_auth_header(admin_user.email, "admin"),
            json={
                "title": "Ill-Fated Doc",
                "original_filename": "test.pdf",
                "min_role_level": 0,
            },
        )
        assert response.status_code == 502

        docs_after = db_session.query(Document).count()
        assert docs_after == docs_before, (
            "Document row was left orphaned after a failed upload-url call"
        )
        assert (
            db_session.query(Document)
            .filter(Document.title == "Ill-Fated Doc")
            .first()
            is None
        )


class TestConfirmUploadEndpoint:
    """Tests for POST /documents/confirm-upload."""

    @pytest.fixture()
    def pending_document(self, db_session, admin_user):
        """A Document in 'processing' with a server-issued object_key,
        as if /upload-url had already been called for it."""
        object_key = f"{admin_user.id}/{uuid.uuid4()}/{uuid.uuid4()}.pdf"
        doc = Document(
            title="Pending Doc",
            uploaded_by=admin_user.id,
            min_role_level=1,
            status="processing",
            object_key=object_key,
            original_filename="pending.pdf",
        )
        db_session.add(doc)
        db_session.commit()
        db_session.refresh(doc)
        return doc

    def test_viewer_cannot_confirm_upload(self, client, viewer_user, pending_document):
        response = client.post(
            "/documents/confirm-upload",
            headers=_auth_header(viewer_user.email, "viewer"),
            json={
                "document_id": str(pending_document.id),
                "object_key": pending_document.object_key,
                "title": pending_document.title,
                "original_filename": "pending.pdf",
                "min_role_level": 1,
            },
        )
        assert response.status_code == 403

    @patch("app.ingestion.worker.ingest_document")
    def test_confirm_upload_queues_task_with_server_stored_object_key(
        self, mock_ingest, client, admin_user, pending_document, db_session
    ):
        """Asserts the actual .delay() call args, not just the response —
        must use doc.object_key, not the request body's object_key."""
        mock_ingest.delay = MagicMock()

        response = client.post(
            "/documents/confirm-upload",
            headers=_auth_header(admin_user.email, "admin"),
            json={
                "document_id": str(pending_document.id),
                "object_key": pending_document.object_key,
                "title": pending_document.title,
                "original_filename": "pending.pdf",
                "min_role_level": 1,
            },
        )
        assert response.status_code == 202
        assert response.json()["status"] == "processing"

        mock_ingest.delay.assert_called_once_with(
            str(pending_document.id), pending_document.object_key
        )

    @patch("app.ingestion.worker.ingest_document")
    def test_confirm_upload_rejects_client_supplied_object_key_mismatch(
        self, mock_ingest, client, admin_user, pending_document
    ):
        """A pattern-valid but non-matching object_key is rejected, and
        nothing is queued."""
        mock_ingest.delay = MagicMock()

        attacker_supplied_key = f"{uuid.uuid4()}/{uuid.uuid4()}/{uuid.uuid4()}.pdf"

        response = client.post(
            "/documents/confirm-upload",
            headers=_auth_header(admin_user.email, "admin"),
            json={
                "document_id": str(pending_document.id),
                "object_key": attacker_supplied_key,
                "title": pending_document.title,
                "original_filename": "pending.pdf",
                "min_role_level": 1,
            },
        )
        assert response.status_code == 400
        mock_ingest.delay.assert_not_called()

    def test_confirm_upload_rejects_malformed_object_key(
        self, client, admin_user, pending_document
    ):
        response = client.post(
            "/documents/confirm-upload",
            headers=_auth_header(admin_user.email, "admin"),
            json={
                "document_id": str(pending_document.id),
                "object_key": "not-a-valid-object-key",
                "title": pending_document.title,
                "original_filename": "pending.pdf",
                "min_role_level": 1,
            },
        )
        assert response.status_code == 400

    def test_confirm_upload_rejects_unknown_document(self, client, admin_user):
        response = client.post(
            "/documents/confirm-upload",
            headers=_auth_header(admin_user.email, "admin"),
            json={
                "document_id": str(uuid.uuid4()),
                "object_key": f"{uuid.uuid4()}/{uuid.uuid4()}/{uuid.uuid4()}.pdf",
                "title": "Ghost Doc",
                "original_filename": "ghost.pdf",
                "min_role_level": 0,
            },
        )
        assert response.status_code == 404

    def test_confirm_upload_rejects_document_owned_by_another_admin(
        self, client, admin_user, db_session
    ):
        from app.core.security import hash_password
        from app.db.models import User, UserRole

        other_admin = User(
            email="other-admin@test.com",
            password_hash=hash_password("pass"),
            role=UserRole.admin,
        )
        db_session.add(other_admin)
        db_session.commit()
        db_session.refresh(other_admin)

        object_key = f"{other_admin.id}/{uuid.uuid4()}/{uuid.uuid4()}.pdf"
        doc = Document(
            title="Someone Else's Doc",
            uploaded_by=other_admin.id,
            min_role_level=0,
            status="processing",
            object_key=object_key,
        )
        db_session.add(doc)
        db_session.commit()
        db_session.refresh(doc)

        response = client.post(
            "/documents/confirm-upload",
            headers=_auth_header(admin_user.email, "admin"),
            json={
                "document_id": str(doc.id),
                "object_key": object_key,
                "title": doc.title,
                "original_filename": "test.pdf",
                "min_role_level": 0,
            },
        )
        assert response.status_code == 404

    @patch("app.ingestion.worker.ingest_document")
    def test_confirm_upload_rejects_already_processed_document(
        self, mock_ingest, client, admin_user, pending_document, db_session
    ):
        mock_ingest.delay = MagicMock()
        pending_document.status = "ready"
        db_session.commit()

        response = client.post(
            "/documents/confirm-upload",
            headers=_auth_header(admin_user.email, "admin"),
            json={
                "document_id": str(pending_document.id),
                "object_key": pending_document.object_key,
                "title": pending_document.title,
                "original_filename": "pending.pdf",
                "min_role_level": 1,
            },
        )
        assert response.status_code == 409
        mock_ingest.delay.assert_not_called()
