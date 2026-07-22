"""Integration tests for the Celery ingestion worker.

Runs the worker task synchronously (no broker needed) against sample data.
Tests:
- Chunks land in DB with correct min_role_level matching parent document
- Failure path sets status='failed' when embedding call is mocked to raise
- Corrupt PDF sets status='failed' immediately (no retries)
"""

import os
import uuid
import tempfile

import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base, User, UserRole, Document, DocumentChunk
from app.core.security import hash_password


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
    """Create a test admin user in the worker's DB."""
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
    """Create a test document with status='processing'."""
    session, _ = worker_db
    doc = Document(
        title="Test Policy",
        uploaded_by=sample_admin.id,
        min_role_level=1,  # manager-level
        status="processing",
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


@pytest.fixture()
def sample_pdf_path():
    """Create a temporary PDF file with valid content for testing."""
    # Create a real (minimal) PDF using PyMuPDF
    import fitz

    pdf_path = os.path.join(tempfile.gettempdir(), f"test_{uuid.uuid4()}.pdf")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (50, 100),
        "This is a test policy document for ClearanceRAG testing. "
        "It contains enough text to produce at least one chunk when "
        "processed by the ingestion pipeline. The policy states that "
        "all employees must follow the guidelines set forth by the "
        "organization regarding data handling and security protocols.",
    )
    doc.save(pdf_path)
    doc.close()
    yield pdf_path
    # Cleanup
    if os.path.exists(pdf_path):
        os.remove(pdf_path)


@pytest.fixture()
def corrupt_pdf_path():
    """Create a corrupt (non-PDF) file for failure testing."""
    pdf_path = os.path.join(tempfile.gettempdir(), f"corrupt_{uuid.uuid4()}.pdf")
    with open(pdf_path, "wb") as f:
        f.write(b"THIS IS NOT A PDF FILE AT ALL - CORRUPT DATA")
    yield pdf_path
    if os.path.exists(pdf_path):
        os.remove(pdf_path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIngestDocumentTask:
    """Tests for the ingest_document Celery task."""

    @patch("app.ingestion.embedder.embed_texts")
    def test_successful_ingestion_creates_chunks(
        self, mock_embed, worker_db, sample_document, sample_pdf_path
    ):
        """Task processes PDF and creates chunks with correct min_role_level."""
        session, TestSession = worker_db

        # Capture IDs before worker commits (avoids DetachedInstanceError)
        doc_id = sample_document.id
        expected_role_level = sample_document.min_role_level

        # Mock the embedding call to return fake 1536-dim vectors
        def fake_embed(texts):
            return [[0.1] * 1536 for _ in texts]
        mock_embed.side_effect = fake_embed

        # Patch the worker's session to use our test session
        with patch(
            "app.ingestion.worker._get_worker_session",
            return_value=session,
        ):
            from app.ingestion.worker import ingest_document
            result = ingest_document(str(doc_id), sample_pdf_path)

        assert result["status"] == "ready"
        assert result["chunks_created"] > 0

        # Verify chunks in DB
        chunks = (
            session.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc_id)
            .all()
        )
        assert len(chunks) > 0
        for chunk in chunks:
            # Critical: min_role_level must match parent document
            assert chunk.min_role_level == expected_role_level
            assert len(chunk.text_content) > 0
            assert chunk.embedding is not None

        # Verify document status is now 'ready'
        doc = session.query(Document).filter(
            Document.id == doc_id
        ).first()
        assert doc.status == "ready"

    @patch("app.ingestion.embedder.embed_texts")
    def test_embedding_failure_sets_status_failed(
        self, mock_embed, worker_db, sample_document, sample_pdf_path
    ):
        """When embedding fails, document status is set to 'failed'."""
        session, _ = worker_db
        doc_id = sample_document.id  # Capture before worker commits
        import openai

        # Mock the embedding call to raise an API error
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
            result = ingest_document(str(doc_id), sample_pdf_path)

        assert result["status"] == "failed"
        assert "Embedding error" in result["detail"]

        # Verify document status is 'failed'
        doc = session.query(Document).filter(
            Document.id == doc_id
        ).first()
        assert doc.status == "failed"

        # Verify NO chunks were created
        chunks = (
            session.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc_id)
            .all()
        )
        assert len(chunks) == 0

    def test_corrupt_pdf_sets_status_failed(
        self, worker_db, sample_document, corrupt_pdf_path
    ):
        """A corrupt PDF sets status='failed' immediately (no retries)."""
        session, _ = worker_db
        doc_id = sample_document.id  # Capture before worker commits

        with patch(
            "app.ingestion.worker._get_worker_session",
            return_value=session,
        ):
            from app.ingestion.worker import ingest_document
            result = ingest_document(str(doc_id), corrupt_pdf_path)

        assert result["status"] == "failed"
        assert "PDF extraction error" in result["detail"] or "no text" in result["detail"].lower()

        # Verify document status is 'failed'
        doc = session.query(Document).filter(
            Document.id == doc_id
        ).first()
        assert doc.status == "failed"

    @patch("app.ingestion.embedder.embed_texts")
    def test_chunk_min_role_level_matches_parent(
        self, mock_embed, worker_db, sample_admin
    ):
        """Chunks get min_role_level=2 when parent document is admin-only."""
        session, _ = worker_db

        # Create an admin-only document (min_role_level=2)
        admin_doc = Document(
            title="Admin Secret",
            uploaded_by=sample_admin.id,
            min_role_level=2,
            status="processing",
        )
        session.add(admin_doc)
        session.commit()
        session.refresh(admin_doc)

        # Create a temp PDF
        import fitz
        pdf_path = os.path.join(
            tempfile.gettempdir(), f"admin_{uuid.uuid4()}.pdf"
        )
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 100), "Top secret admin content for testing.")
        doc.save(pdf_path)
        doc.close()

        mock_embed.side_effect = lambda texts: [[0.5] * 1536 for _ in texts]

        try:
            with patch(
                "app.ingestion.worker._get_worker_session",
                return_value=session,
            ):
                from app.ingestion.worker import ingest_document
                result = ingest_document(str(admin_doc.id), pdf_path)

            assert result["status"] == "ready"

            chunks = (
                session.query(DocumentChunk)
                .filter(DocumentChunk.document_id == admin_doc.id)
                .all()
            )
            assert len(chunks) > 0
            for chunk in chunks:
                assert chunk.min_role_level == 2, (
                    f"Chunk min_role_level is {chunk.min_role_level}, expected 2"
                )
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

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
            result = ingest_document(str(uuid.uuid4()), "/nonexistent.pdf")

        assert result["status"] == "error"
        assert "not found" in result["detail"]
