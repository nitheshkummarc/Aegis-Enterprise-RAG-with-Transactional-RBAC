"""Integration tests for the Celery ingestion worker.

Mocks _download_from_storage (the Supabase Storage boundary) rather than
passing a local file path as object_key — matching the actual worker
contract, where object_key is a storage key downloaded via Supabase, not a
path on disk.

Tests:
- Chunks land in DB with correct min_role_level matching parent document
- Corrupt PDF sets status='failed' immediately (no retry)
- Embedding failure sets status='failed' (no retry)
- Storage download failure retries (self.retry()) instead of failing on
  the first transient error, and dead-letters once retries are exhausted
- cleanup_stuck_documents dead-letters orphaned 'processing' documents
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base, User, UserRole, Document, DocumentChunk
from app.core.security import hash_password
from app.config import EMBEDDING_DIMENSIONS


# ---------------------------------------------------------------------------
# Fixtures — worker tests need their own DB setup since the worker creates
# its own session. We patch _get_worker_session to use our test session.
# ---------------------------------------------------------------------------

@pytest.fixture()
def worker_db():
    """Create an in-memory SQLite engine and session for worker tests."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    yield session, TestSession
    session.close()
    engine.dispose()


@pytest.fixture()
def sample_admin(worker_db):
    session, _ = worker_db
    user = User(
        email="workeradmin@test.com",
        password_hash=hash_password("testpass"),
        role=UserRole.admin,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture()
def sample_document(worker_db, sample_admin):
    session, _ = worker_db
    doc = Document(
        title="Test Policy",
        uploaded_by=sample_admin.id,
        min_role_level=1,  # manager-level
        status="processing",
        object_key=f"{sample_admin.id}/{uuid.uuid4()}/{uuid.uuid4()}.pdf",
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def _make_pdf_bytes(text: str) -> bytes:
    """Build a real minimal PDF in memory using PyMuPDF."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), text)
    data = doc.tobytes()
    doc.close()
    return data


def _writes_bytes_to_dest(payload: bytes):
    """A _download_from_storage stand-in that writes `payload` to dest_path,
    ignoring object_key — the storage layer is what's mocked, not the file
    I/O contract."""

    def _download(object_key, dest_path):
        with open(dest_path, "wb") as f:
            f.write(payload)

    return _download


def _clear_backend_cache(celery_app):
    celery_app._backend_cache = None
    if hasattr(celery_app._local, "backend"):
        del celery_app._local.backend


@contextmanager
def _eager_celery(celery_app):
    """Run tasks synchronously via .apply(), using an in-memory result
    backend — the app's configured backend (Upstash Redis, from .env) isn't
    reachable from tests and isn't what these tests are about."""
    original_eager = celery_app.conf.task_always_eager
    original_backend_url = celery_app.conf.result_backend
    celery_app.conf.task_always_eager = True
    celery_app.conf.result_backend = "cache+memory://"
    _clear_backend_cache(celery_app)
    try:
        yield
    finally:
        celery_app.conf.task_always_eager = original_eager
        celery_app.conf.result_backend = original_backend_url
        _clear_backend_cache(celery_app)


SAMPLE_PDF_TEXT = (
    "This is a test policy document for Aegis testing. "
    "It contains enough text to produce at least one chunk when "
    "processed by the ingestion pipeline. The policy states that "
    "all employees must follow the guidelines set forth by the "
    "organization regarding data handling and security protocols."
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIngestDocumentTask:
    """Tests for the ingest_document Celery task."""

    @patch("app.ingestion.worker._download_from_storage")
    @patch("app.ingestion.embedder.embed_texts")
    def test_successful_ingestion_creates_chunks(
        self, mock_embed, mock_download, worker_db, sample_document
    ):
        """Task processes PDF and creates chunks with correct min_role_level."""
        session, TestSession = worker_db

        doc_id = sample_document.id
        expected_role_level = sample_document.min_role_level
        object_key = sample_document.object_key

        mock_embed.side_effect = lambda texts: [[0.1] * EMBEDDING_DIMENSIONS for _ in texts]
        mock_download.side_effect = _writes_bytes_to_dest(
            _make_pdf_bytes(SAMPLE_PDF_TEXT)
        )

        with patch(
            "app.ingestion.worker._get_worker_session",
            return_value=session,
        ):
            from app.ingestion.worker import ingest_document
            result = ingest_document(str(doc_id), object_key)

        assert result["status"] == "ready"
        assert result["chunks_created"] > 0
        mock_download.assert_called_once()
        assert mock_download.call_args[0][0] == object_key

        chunks = (
            session.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc_id)
            .all()
        )
        assert len(chunks) > 0
        for chunk in chunks:
            assert chunk.min_role_level == expected_role_level
            assert len(chunk.text_content) > 0
            assert chunk.embedding is not None

        doc = session.query(Document).filter(Document.id == doc_id).first()
        assert doc.status == "ready"

    @patch("app.ingestion.worker._download_from_storage")
    @patch("app.ingestion.embedder.embed_texts")
    def test_embedding_failure_sets_status_failed(
        self, mock_embed, mock_download, worker_db, sample_document
    ):
        """When embedding fails, document status is set to 'failed'."""
        session, _ = worker_db
        doc_id = sample_document.id
        import openai

        mock_download.side_effect = _writes_bytes_to_dest(
            _make_pdf_bytes(SAMPLE_PDF_TEXT)
        )
        mock_embed.side_effect = openai.APIError(
            message="API Error",
            request=MagicMock(),
            body=None,
        )

        with patch(
            "app.ingestion.worker._get_worker_session",
            return_value=session,
        ):
            from app.ingestion.worker import ingest_document
            result = ingest_document(str(doc_id), sample_document.object_key)

        assert result["status"] == "failed"
        assert "Embedding error" in result["detail"]

        doc = session.query(Document).filter(Document.id == doc_id).first()
        assert doc.status == "failed"

        chunks = (
            session.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc_id)
            .all()
        )
        assert len(chunks) == 0

    @patch("app.ingestion.worker._download_from_storage")
    def test_corrupt_pdf_sets_status_failed(
        self, mock_download, worker_db, sample_document
    ):
        """A corrupt PDF sets status='failed' immediately (no retry)."""
        session, _ = worker_db
        doc_id = sample_document.id

        mock_download.side_effect = _writes_bytes_to_dest(
            b"THIS IS NOT A PDF FILE AT ALL - CORRUPT DATA"
        )

        with patch(
            "app.ingestion.worker._get_worker_session",
            return_value=session,
        ):
            from app.ingestion.worker import ingest_document
            result = ingest_document(str(doc_id), sample_document.object_key)

        assert result["status"] == "failed"
        assert "PDF extraction error" in result["detail"] or "no text" in result["detail"].lower()

        doc = session.query(Document).filter(Document.id == doc_id).first()
        assert doc.status == "failed"

    @patch("app.ingestion.worker._download_from_storage")
    @patch("app.ingestion.embedder.embed_texts")
    def test_chunk_min_role_level_matches_parent(
        self, mock_embed, mock_download, worker_db, sample_admin
    ):
        """Chunks get min_role_level=2 when parent document is admin-only."""
        session, _ = worker_db

        admin_doc = Document(
            title="Admin Secret",
            uploaded_by=sample_admin.id,
            min_role_level=2,
            status="processing",
            object_key=f"{sample_admin.id}/{uuid.uuid4()}/{uuid.uuid4()}.pdf",
        )
        session.add(admin_doc)
        session.commit()
        session.refresh(admin_doc)

        mock_embed.side_effect = lambda texts: [[0.5] * EMBEDDING_DIMENSIONS for _ in texts]
        mock_download.side_effect = _writes_bytes_to_dest(
            _make_pdf_bytes("Top secret admin content for testing.")
        )

        with patch(
            "app.ingestion.worker._get_worker_session",
            return_value=session,
        ):
            from app.ingestion.worker import ingest_document
            result = ingest_document(str(admin_doc.id), admin_doc.object_key)

        assert result["status"] == "ready"

        chunks = (
            session.query(DocumentChunk)
            .filter(DocumentChunk.document_id == admin_doc.id)
            .all()
        )
        assert len(chunks) > 0
        for chunk in chunks:
            assert chunk.min_role_level == 2

    @patch("app.ingestion.embedder.embed_texts")
    def test_nonexistent_document_returns_error(
        self, mock_embed, worker_db
    ):
        """Task returns error when document ID doesn't exist."""
        session, _ = worker_db

        with patch(
            "app.ingestion.worker._get_worker_session",
            return_value=session,
        ):
            from app.ingestion.worker import ingest_document
            result = ingest_document(str(uuid.uuid4()), "some/object/key.pdf")

        assert result["status"] == "error"
        assert "not found" in result["detail"]


class TestIngestDocumentRetry:
    """Tests for the storage-download retry path (self.retry()).

    .apply() runs the task through Celery's real request/retry machinery,
    synchronously, instead of a bare function call — a bare call has no
    request context for self.retry() to schedule into, so it can't exercise
    retry behavior at all.
    """

    @patch("app.ingestion.worker._download_from_storage")
    @patch("app.ingestion.embedder.embed_texts")
    def test_transient_download_failure_retries_then_succeeds(
        self, mock_embed, mock_download, worker_db, sample_document
    ):
        """A download that fails once but succeeds on retry completes
        ingestion — proving the failure was retried, not dead-lettered."""
        from app.ingestion.worker import celery_app, ingest_document

        session, _ = worker_db
        doc_id = sample_document.id
        object_key = sample_document.object_key

        pdf_bytes = _make_pdf_bytes(SAMPLE_PDF_TEXT)
        attempts = {"n": 0}

        def flaky_download(key, dest_path):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("storage timeout")
            with open(dest_path, "wb") as f:
                f.write(pdf_bytes)

        mock_download.side_effect = flaky_download
        mock_embed.side_effect = lambda texts: [[0.1] * EMBEDDING_DIMENSIONS for _ in texts]

        with _eager_celery(celery_app):
            with patch(
                "app.ingestion.worker._get_worker_session",
                return_value=session,
            ):
                result = ingest_document.apply(args=(str(doc_id), object_key)).get()

        assert attempts["n"] >= 2
        assert result["status"] == "ready"
        doc = session.query(Document).filter(Document.id == doc_id).first()
        assert doc.status == "ready"

    @patch("app.ingestion.worker._download_from_storage")
    def test_download_failure_exhausts_retries_then_fails(
        self, mock_download, worker_db, sample_document
    ):
        """Once every retry attempt also fails, the document is dead-lettered."""
        from app.ingestion.worker import celery_app, ingest_document

        session, _ = worker_db
        doc_id = sample_document.id
        mock_download.side_effect = RuntimeError("storage unreachable")

        with _eager_celery(celery_app):
            with patch(
                "app.ingestion.worker._get_worker_session",
                return_value=session,
            ):
                with pytest.raises(RuntimeError):
                    ingest_document.apply(args=(str(doc_id), sample_document.object_key)).get()

        # 1 initial attempt + 3 retries (max_retries=3)
        assert mock_download.call_count == 4
        doc = session.query(Document).filter(Document.id == doc_id).first()
        assert doc.status == "failed"

    @patch("app.ingestion.worker._download_from_storage")
    def test_direct_call_has_no_retry_context_and_fails_immediately(
        self, mock_download, worker_db, sample_document
    ):
        """A bare (non-dispatched) call has no request to retry into, so
        self.retry() surfaces the original error on the first failure —
        the document must still end up dead-lettered, not stuck."""
        session, _ = worker_db
        doc_id = sample_document.id
        mock_download.side_effect = RuntimeError("storage unreachable")

        with patch(
            "app.ingestion.worker._get_worker_session",
            return_value=session,
        ):
            from app.ingestion.worker import ingest_document
            with pytest.raises(RuntimeError):
                ingest_document(str(doc_id), sample_document.object_key)

        assert mock_download.call_count == 1
        doc = session.query(Document).filter(Document.id == doc_id).first()
        assert doc.status == "failed"


class TestCleanupStuckDocuments:
    """Tests for the periodic cleanup_stuck_documents task."""

    def _backdate(self, session, doc_id, minutes_ago):
        old_time = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        session.query(Document).filter(Document.id == doc_id).update(
            {"updated_at": old_time}
        )
        session.commit()

    def test_marks_old_processing_document_with_no_chunks_as_failed(
        self, worker_db, sample_admin
    ):
        session, _ = worker_db
        doc = Document(
            title="Orphaned Doc",
            uploaded_by=sample_admin.id,
            min_role_level=0,
            status="processing",
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)
        doc_id = doc.id  # capture before cleanup_stuck_documents closes the session
        self._backdate(session, doc_id, minutes_ago=120)

        with patch(
            "app.ingestion.worker._get_worker_session",
            return_value=session,
        ):
            from app.ingestion.worker import cleanup_stuck_documents
            result = cleanup_stuck_documents()

        assert str(doc_id) in result["document_ids"]
        refreshed = session.query(Document).filter(Document.id == doc_id).first()
        assert refreshed.status == "failed"

    def test_leaves_recent_processing_document_alone(self, worker_db, sample_admin):
        session, _ = worker_db
        doc = Document(
            title="Fresh Doc",
            uploaded_by=sample_admin.id,
            min_role_level=0,
            status="processing",
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)
        doc_id = doc.id

        with patch(
            "app.ingestion.worker._get_worker_session",
            return_value=session,
        ):
            from app.ingestion.worker import cleanup_stuck_documents
            result = cleanup_stuck_documents()

        assert str(doc_id) not in result["document_ids"]
        refreshed = session.query(Document).filter(Document.id == doc_id).first()
        assert refreshed.status == "processing"

    def test_leaves_old_processing_document_with_chunks_alone(
        self, worker_db, sample_admin
    ):
        """Chunks exist but status was never flipped to 'ready' — that's
        not the simple orphan case, so cleanup should leave it for manual
        review rather than guessing."""
        session, _ = worker_db
        doc = Document(
            title="Stalled With Chunks",
            uploaded_by=sample_admin.id,
            min_role_level=0,
            status="processing",
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)
        doc_id = doc.id

        chunk = DocumentChunk(
            document_id=doc_id,
            chunk_index=0,
            text_content="partial content",
            embedding=[0.1] * EMBEDDING_DIMENSIONS,
            min_role_level=0,
        )
        session.add(chunk)
        session.commit()
        self._backdate(session, doc_id, minutes_ago=120)

        with patch(
            "app.ingestion.worker._get_worker_session",
            return_value=session,
        ):
            from app.ingestion.worker import cleanup_stuck_documents
            result = cleanup_stuck_documents()

        assert str(doc_id) not in result["document_ids"]
        refreshed = session.query(Document).filter(Document.id == doc_id).first()
        assert refreshed.status == "processing"
