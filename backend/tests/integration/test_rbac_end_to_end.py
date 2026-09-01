"""End-to-End integration test for RBAC vector search on Postgres.

This test empirically proves the core architectural claim: that the PostgreSQL 
engine physically blocks document chunks based on role level, bypassing the LLM.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, User, UserRole, Document, DocumentChunk
from app.retrieval.search import permission_filtered_search
from app.config import get_settings
from app.config import EMBEDDING_DIMENSIONS


@pytest.fixture(scope="module")
def pg_engine():
    """Create the Postgres engine."""
    settings = get_settings()
    if "sqlite" in settings.DATABASE_URL:
        pytest.skip("Requires Postgres with pgvector.")
    
    engine = create_engine(settings.DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(pg_engine):
    """Provide a transactional session that rolls back after the test."""
    Session = sessionmaker(bind=pg_engine)
    session = Session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_empirical_postgres_rbac_blocks_admin_chunks_from_viewers(db_session):
    """
    Empirical proof that a viewer token cannot retrieve admin chunks from PostgreSQL pgvector.
    This test runs the actual SQL query with <=> cosine distance operator.
    """
    # 1. Setup Data
    admin = User(email="test_admin_e2e@test.com", password_hash="hash", role=UserRole.admin)
    db_session.add(admin)
    db_session.flush()
    
    viewer_doc = Document(title="Public", uploaded_by=admin.id, min_role_level=0, status="ready")
    admin_doc = Document(title="Secret", uploaded_by=admin.id, min_role_level=2, status="ready")
    db_session.add_all([viewer_doc, admin_doc])
    db_session.flush()
    
    # Both chunks have identical embeddings, so both would perfectly match the search.
    viewer_chunk = DocumentChunk(
        document_id=viewer_doc.id, 
        chunk_index=0, 
        text_content="Public info", 
        embedding=[0.1] * EMBEDDING_DIMENSIONS, 
        min_role_level=0
    )
    admin_chunk = DocumentChunk(
        document_id=admin_doc.id, 
        chunk_index=0, 
        text_content="Admin secret info", 
        embedding=[0.1] * EMBEDDING_DIMENSIONS, 
        min_role_level=2
    )
    db_session.add_all([viewer_chunk, admin_chunk])
    db_session.flush()
    
    # 2. Execute vector search natively in PostgreSQL as a Viewer
    viewer_results = permission_filtered_search(
        db=db_session,
        query_embedding=[0.1] * EMBEDDING_DIMENSIONS,
        user_role=UserRole.viewer,  # Viewer role
        limit=5
    )
    
    # 3. Assertions
    # It must ONLY return the viewer chunk. The admin chunk must be physically absent.
    returned_titles = [r["title"] for r in viewer_results]
    
    assert "Public" in returned_titles, "Viewer should see the public chunk"
    assert "Secret" not in returned_titles, "SECURITY FAILURE: Viewer saw admin chunk!"
    assert len(viewer_results) == 1, "Expected exactly 1 chunk returned"

    # 4. Prove Admin CAN see it
    admin_results = permission_filtered_search(
        db=db_session,
        query_embedding=[0.1] * EMBEDDING_DIMENSIONS,
        user_role=UserRole.admin,  # Admin role
        limit=5
    )
    admin_returned_titles = [r["title"] for r in admin_results]
    assert "Public" in admin_returned_titles
    assert "Secret" in admin_returned_titles
    assert len(admin_results) == 2, "Admin should see both chunks"
