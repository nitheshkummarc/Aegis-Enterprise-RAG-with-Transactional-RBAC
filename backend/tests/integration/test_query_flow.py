"""Integration tests for the /retrieval/query endpoint.

Tests the SSE streaming response format and permission-filtered behavior.
Since these tests mock the OpenAI API, they verify the integration logic
without requiring real API keys.
"""

import json
import uuid

import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.main import app
from app.db.session import get_db
from app.db.models import Base, User, UserRole, Document, DocumentChunk
from app.core.security import hash_password
from app.auth.jwt import create_access_token


@pytest.fixture()
def query_db():
    """Create an in-memory DB seeded with documents for query tests."""
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

    # Create users
    admin = User(
        email="admin@query.test",
        password_hash=hash_password("pass"),
        role=UserRole.admin,
    )
    viewer = User(
        email="viewer@query.test",
        password_hash=hash_password("pass"),
        role=UserRole.viewer,
    )
    session.add_all([admin, viewer])
    session.commit()

    # Create a viewer-accessible doc + chunk
    viewer_doc = Document(
        title="Public Policy",
        uploaded_by=admin.id,
        min_role_level=0,
        status="ready",
    )
    session.add(viewer_doc)
    session.commit()

    viewer_chunk = DocumentChunk(
        document_id=viewer_doc.id,
        chunk_index=0,
        text_content="The PTO policy is 15 days per year for all employees.",
        embedding=[0.1] * 1536,
        min_role_level=0,
    )
    session.add(viewer_chunk)

    # Create an admin-only doc + chunk
    admin_doc = Document(
        title="Exec Compensation",
        uploaded_by=admin.id,
        min_role_level=2,
        status="ready",
    )
    session.add(admin_doc)
    session.commit()

    admin_chunk = DocumentChunk(
        document_id=admin_doc.id,
        chunk_index=0,
        text_content="CEO salary is $5M with stock options.",
        embedding=[0.9] * 1536,
        min_role_level=2,
    )
    session.add(admin_chunk)
    session.commit()

    yield {
        "session": session,
        "admin": admin,
        "viewer": viewer,
        "viewer_doc": viewer_doc,
        "admin_doc": admin_doc,
    }
    session.close()
    engine.dispose()


@pytest.fixture()
def query_client(query_db):
    """TestClient wired to the query test DB."""
    def override_get_db():
        yield query_db["session"]

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _parse_sse_events(response_text: str) -> list[dict]:
    """Parse SSE response text into a list of event dicts."""
    events = []
    for line in response_text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            data_str = line[len("data: "):]
            try:
                events.append(json.loads(data_str))
            except json.JSONDecodeError:
                continue
    return events


class TestQueryEndpoint:
    """Integration tests for POST /retrieval/query."""

    @patch("app.retrieval.routes.openai")
    @patch("app.retrieval.routes.generate_streaming")
    @patch("app.retrieval.routes.permission_filtered_search")
    def test_sse_done_event_has_sources(
        self, mock_search, mock_generate, mock_openai, query_client, query_db
    ):
        """The final SSE event must be type=done with a sources array."""
        # Mock embedding
        mock_embed_response = MagicMock()
        mock_embed_response.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_openai.OpenAI.return_value.embeddings.create.return_value = (
            mock_embed_response
        )

        # Mock search results
        mock_search.return_value = [
            {
                "chunk_id": "abc-123",
                "text_content": "PTO is 15 days.",
                "document_id": "doc-456",
                "chunk_index": 0,
                "title": "Public Policy",
                "distance": 0.1,
            }
        ]

        # Mock generation
        def fake_generate(prompt):
            yield {"type": "token", "text": "PTO is "}
            yield {"type": "token", "text": "15 days."}
            yield {"type": "done", "full_response": "PTO is 15 days.", "usage": {}, "model": "gpt-4o-mini"}

        mock_generate.side_effect = fake_generate

        token = create_access_token(
            {"sub": "viewer@query.test", "role": "viewer"}
        )
        response = query_client.post(
            "/retrieval/query",
            json={"question": "What is the PTO policy?"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

        events = _parse_sse_events(response.text)
        assert len(events) > 0

        # Last event must be type=done with sources
        done_event = events[-1]
        assert done_event["type"] == "done"
        assert "sources" in done_event
        assert isinstance(done_event["sources"], list)

    @patch("app.retrieval.routes.openai")
    @patch("app.retrieval.routes.generate_streaming")
    @patch("app.retrieval.routes.permission_filtered_search")
    def test_sse_done_sources_has_correct_fields(
        self, mock_search, mock_generate, mock_openai, query_client, query_db
    ):
        """Each source in the done event must have document_id, title, chunk_id."""
        mock_embed_response = MagicMock()
        mock_embed_response.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_openai.OpenAI.return_value.embeddings.create.return_value = (
            mock_embed_response
        )

        mock_search.return_value = [
            {
                "chunk_id": "chunk-1",
                "text_content": "Content here.",
                "document_id": "doc-1",
                "chunk_index": 0,
                "title": "My Document",
                "distance": 0.2,
            }
        ]

        def fake_generate(prompt):
            yield {"type": "token", "text": "Answer."}
            yield {"type": "done", "full_response": "Answer.", "usage": {}, "model": "gpt-4o-mini"}

        mock_generate.side_effect = fake_generate

        token = create_access_token(
            {"sub": "admin@query.test", "role": "admin"}
        )
        response = query_client.post(
            "/retrieval/query",
            json={"question": "Test question"},
            headers={"Authorization": f"Bearer {token}"},
        )

        events = _parse_sse_events(response.text)
        done_event = events[-1]
        assert done_event["type"] == "done"

        for source in done_event["sources"]:
            assert "document_id" in source
            assert "title" in source
            assert "chunk_id" in source

    @patch("app.retrieval.routes.openai")
    @patch("app.retrieval.routes.generate_streaming")
    @patch("app.retrieval.routes.permission_filtered_search")
    def test_empty_sources_when_no_chunks_permitted(
        self, mock_search, mock_generate, mock_openai, query_client, query_db
    ):
        """When no chunks are permitted, sources should be empty."""
        mock_embed_response = MagicMock()
        mock_embed_response.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_openai.OpenAI.return_value.embeddings.create.return_value = (
            mock_embed_response
        )

        # No chunks returned by search (viewer asking about admin-only content)
        mock_search.return_value = []

        def fake_generate(prompt):
            yield {"type": "token", "text": "I do not have access to that information."}
            yield {"type": "done", "full_response": "I do not have access to that information.", "usage": {}, "model": "gpt-4o-mini"}

        mock_generate.side_effect = fake_generate

        token = create_access_token(
            {"sub": "viewer@query.test", "role": "viewer"}
        )
        response = query_client.post(
            "/retrieval/query",
            json={"question": "What is the CEO salary?"},
            headers={"Authorization": f"Bearer {token}"},
        )

        events = _parse_sse_events(response.text)
        done_event = events[-1]
        assert done_event["type"] == "done"
        assert done_event["sources"] == []

    @patch("app.retrieval.routes.openai")
    @patch("app.retrieval.routes.generate_streaming")
    @patch("app.retrieval.routes.permission_filtered_search")
    def test_generation_failure_emits_error_and_keeps_real_sources(
        self, mock_search, mock_generate, mock_openai, query_client, query_db
    ):
        """A mid-stream generation exception emits an "error" event, and
        the trailing done event still carries the permitted sources."""
        mock_embed_response = MagicMock()
        mock_embed_response.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_openai.OpenAI.return_value.embeddings.create.return_value = (
            mock_embed_response
        )

        mock_search.return_value = [
            {
                "chunk_id": "chunk-1",
                "text_content": "PTO is 15 days.",
                "document_id": "doc-1",
                "chunk_index": 0,
                "title": "Public Policy",
                "distance": 0.1,
            }
        ]

        def failing_generate(prompt):
            yield {"type": "token", "text": "PTO is "}
            raise RuntimeError("OpenAI connection reset mid-stream")

        mock_generate.side_effect = failing_generate

        token = create_access_token({"sub": "viewer@query.test", "role": "viewer"})
        response = query_client.post(
            "/retrieval/query",
            json={"question": "What is the PTO policy?"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

        events = _parse_sse_events(response.text)
        event_types = [e["type"] for e in events]

        assert "error" in event_types, event_types
        assert event_types[-1] == "done"

        done_event = events[-1]
        assert done_event["sources"] != []
        assert done_event["sources"][0]["document_id"] == "doc-1"

    def test_query_without_auth_returns_422(self, query_client):
        """Query without auth header returns 422."""
        response = query_client.post(
            "/retrieval/query",
            json={"question": "Any question"},
        )
        assert response.status_code == 422


class TestQueryRateLimit:
    """POST /retrieval/query is rate-limited, same as auth and upload-url."""

    @patch("app.retrieval.routes.openai")
    @patch("app.retrieval.routes.generate_streaming")
    @patch("app.retrieval.routes.permission_filtered_search")
    def test_query_returns_429_after_20_requests_per_minute(
        self, mock_search, mock_generate, mock_openai, query_client, query_db
    ):
        mock_embed_response = MagicMock()
        mock_embed_response.data = [MagicMock(embedding=[0.1] * 1536)]
        mock_openai.OpenAI.return_value.embeddings.create.return_value = (
            mock_embed_response
        )
        mock_search.return_value = []

        def fake_generate(prompt):
            yield {
                "type": "done",
                "full_response": "",
                "usage": {},
                "model": "gpt-4o-mini",
            }

        mock_generate.side_effect = fake_generate

        token = create_access_token({"sub": "viewer@query.test", "role": "viewer"})
        headers = {"Authorization": f"Bearer {token}"}

        statuses = [
            query_client.post(
                "/retrieval/query",
                json={"question": "Any question"},
                headers=headers,
            ).status_code
            for _ in range(21)
        ]
        assert statuses[:20] == [200] * 20, statuses
        assert statuses[20] == 429, statuses
