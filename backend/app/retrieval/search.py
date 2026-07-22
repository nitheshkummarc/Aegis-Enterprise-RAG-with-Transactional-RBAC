"""Permission-filtered vector search using pgvector.

The core query uses the <=> (cosine distance) operator to match the
vector_cosine_ops HNSW index defined in the Section 3 migration.
Permission filtering happens via: WHERE dc.min_role_level <= %(user_role_level)s

This is the central architectural bet of the project: permissions and vectors
are in the same table scan, not a join-then-filter.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import UserRole, ROLE_LEVEL_MAP


# The exact SQL from Section 3 of the Master Build Prompt.
# Uses <=> (cosine distance) — NOT <-> (L2) — to match vector_cosine_ops index.
# The JOIN to documents fetches title for the Sources dropdown in Phase 4.
PERMISSION_FILTERED_SEARCH_SQL = text("""
    SELECT dc.id AS chunk_id,
           dc.text_content,
           dc.document_id,
           dc.chunk_index,
           dc.min_role_level,
           d.title,
           dc.embedding <=> :query_embedding AS distance
    FROM document_chunks dc
    JOIN documents d ON d.id = dc.document_id
    WHERE dc.min_role_level <= :user_role_level
    ORDER BY dc.embedding <=> :query_embedding
    LIMIT :limit
""")


def get_role_level(role: UserRole) -> int:
    """Resolve a UserRole enum to its numeric level.

    Never trust a numeric level sent directly by the client — always
    resolve from the JWT's role claim via this fixed mapping.
    """
    return ROLE_LEVEL_MAP.get(role, 0)


def permission_filtered_search(
    db: Session,
    query_embedding: list[float],
    user_role: UserRole,
    limit: int = 3,
) -> list[dict]:
    """Execute permission-filtered vector search.

    Args:
        db: SQLAlchemy session.
        query_embedding: The query embedding vector (1536 dims).
        user_role: The authenticated user's role.
        limit: Maximum number of chunks to return.

    Returns:
        List of dicts with keys: chunk_id, text_content, document_id,
        chunk_index, title, distance.
    """
    user_role_level = get_role_level(user_role)

    # Format embedding as pgvector literal string
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    result = db.execute(
        PERMISSION_FILTERED_SEARCH_SQL,
        {
            "query_embedding": embedding_str,
            "user_role_level": user_role_level,
            "limit": limit,
        },
    )

    rows = result.fetchall()
    return [
        {
            "chunk_id": str(row.chunk_id),
            "text_content": row.text_content,
            "document_id": str(row.document_id),
            "chunk_index": row.chunk_index,
            "title": row.title,
            "distance": row.distance,
        }
        for row in rows
    ]
