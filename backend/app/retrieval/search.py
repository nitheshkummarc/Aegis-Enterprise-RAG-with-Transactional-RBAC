"""Permission-filtered vector search using pgvector.

Permission filtering and vector ordering are expressed in a single SQL
statement, so unauthorised chunks are never returned to the application.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import UserRole, ROLE_LEVEL_MAP


# Uses <=> (cosine distance) to match the vector_cosine_ops HNSW indexes.
# The join to documents supplies the title shown in the sources list.
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
    """Return the numeric clearance level for a role.

    Levels are resolved from this fixed mapping rather than from any
    client-supplied value.
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
        query_embedding: The query embedding vector (EMBEDDING_DIMENSIONS wide).
        user_role: The authenticated user's role.
        limit: Maximum number of chunks to return.

    Returns:
        List of dicts with keys: chunk_id, text_content, document_id,
        chunk_index, title, distance.
    """
    user_role_level = get_role_level(user_role)

    # pgvector accepts the vector as a bracketed literal string.
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
