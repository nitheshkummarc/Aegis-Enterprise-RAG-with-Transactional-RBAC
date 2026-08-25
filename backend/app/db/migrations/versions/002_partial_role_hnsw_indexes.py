"""002_partial_role_hnsw_indexes - Replace the single full-table HNSW index
with one cumulative partial HNSW index per role level.

A single HNSW index over the whole document_chunks table doesn't natively
combine with the min_role_level WHERE filter the way a B-tree does — at
scale, a manager-level query can still pay ANN-scan cost against admin-only
chunks it will discard post-filter. Roles are a fixed 3-tier set (viewer=0,
manager=1, admin=2), so three partial indexes cover it completely: each
WHERE min_role_level <= N indexes exactly the rows a role at level N (or
below) is permitted to search, so a viewer's query only ever scans public
content and an admin's covers everything (equivalent to the old full index).

Revision ID: 002
Revises: 001
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS document_chunks_embedding_hnsw;")

    for level in (0, 1, 2):
        op.execute(f"""
            CREATE INDEX document_chunks_hnsw_level{level}
                ON document_chunks USING hnsw (embedding vector_cosine_ops)
                WHERE min_role_level <= {level};
        """)


def downgrade() -> None:
    for level in (0, 1, 2):
        op.execute(f"DROP INDEX IF EXISTS document_chunks_hnsw_level{level};")

    op.execute("""
        CREATE INDEX document_chunks_embedding_hnsw
            ON document_chunks USING hnsw (embedding vector_cosine_ops);
    """)
