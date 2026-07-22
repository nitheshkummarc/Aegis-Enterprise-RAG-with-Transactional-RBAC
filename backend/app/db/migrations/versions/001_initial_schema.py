"""001_initial_schema - Create core tables with pgvector support.

This migration uses raw SQL via op.execute() as specified in the Master Build
Prompt, since Alembic's autogenerate frequently mishandles extension creation
and non-standard index types like HNSW.

Revision ID: 001
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the complete ClearanceRAG schema from Section 3 of the Master Build Prompt."""

    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # Shared role enum used by both users.role and permission fields
    op.execute("CREATE TYPE user_role AS ENUM ('viewer', 'manager', 'admin');")

    # Users table
    op.execute("""
        CREATE TABLE users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role user_role NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)

    # Documents table
    op.execute("""
        CREATE TABLE documents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            title TEXT NOT NULL,
            uploaded_by UUID NOT NULL REFERENCES users(id),
            min_role_level SMALLINT NOT NULL CHECK (min_role_level BETWEEN 0 AND 2),
            status TEXT NOT NULL DEFAULT 'processing'
                CHECK (status IN ('processing', 'ready', 'failed')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)

    op.execute("CREATE INDEX documents_uploaded_by_idx ON documents(uploaded_by);")

    # Document chunks table with denormalized min_role_level
    op.execute("""
        CREATE TABLE document_chunks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index INT NOT NULL,
            text_content TEXT NOT NULL,
            embedding VECTOR(1536) NOT NULL,
            min_role_level SMALLINT NOT NULL CHECK (min_role_level BETWEEN 0 AND 2),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (document_id, chunk_index)
        );
    """)

    # HNSW index for permission-filtered vector search using cosine distance
    op.execute("""
        CREATE INDEX document_chunks_embedding_hnsw
            ON document_chunks USING hnsw (embedding vector_cosine_ops);
    """)

    # B-tree index on min_role_level for the permission filter
    op.execute(
        "CREATE INDEX document_chunks_min_role_level_idx ON document_chunks (min_role_level);"
    )


def downgrade() -> None:
    """Drop all tables, the enum type, and the vector extension."""
    op.execute("DROP INDEX IF EXISTS document_chunks_min_role_level_idx;")
    op.execute("DROP INDEX IF EXISTS document_chunks_embedding_hnsw;")
    op.execute("DROP TABLE IF EXISTS document_chunks;")
    op.execute("DROP INDEX IF EXISTS documents_uploaded_by_idx;")
    op.execute("DROP TABLE IF EXISTS documents;")
    op.execute("DROP TABLE IF EXISTS users;")
    op.execute("DROP TYPE IF EXISTS user_role;")
    op.execute("DROP EXTENSION IF EXISTS vector;")
