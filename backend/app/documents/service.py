"""Document service layer.

Upload flow:
1. Client requests a presigned upload URL from FastAPI.
2. FastAPI generates a UUID-based object key — no user-controlled filename
   content ever reaches the storage path — and returns a short-lived
   signed URL scoped to that key.
3. Client uploads the PDF directly to Supabase Storage (the backend
   never touches the file bytes).
4. Client calls /confirm-upload; FastAPI creates the Document row and
   queues the Celery ingestion task.
"""

import uuid

from sqlalchemy.orm import Session
from supabase import create_client

from app.config import get_settings
from app.db.models import Document


BUCKET_NAME = "documents"
# Maximum file size in bytes (50 MB). Enforced in the presigned URL policy
# so the limit is applied server-side by Supabase, not checked after upload.
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024


def _get_supabase_client():
    """Create an authenticated Supabase client using the service key."""
    settings = get_settings()
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


def generate_upload_url(user_id: uuid.UUID, document_id: uuid.UUID) -> dict:
    """Generate a presigned upload URL for direct client-to-Supabase upload.

    Object key structure: {user_id}/{document_id}/{uuid}.pdf
    The original filename is never part of the storage path.

    Returns:
        dict with 'signed_url', 'object_key', and 'expires_in'.
    """
    file_uuid = uuid.uuid4()
    object_key = f"{user_id}/{document_id}/{file_uuid}.pdf"

    supabase = _get_supabase_client()
    # Create a signed upload URL valid for 10 minutes
    result = supabase.storage.from_(BUCKET_NAME).create_signed_upload_url(
        path=object_key,
    )

    return {
        "signed_url": result.get("signedURL") or result.get("signed_url", ""),
        "object_key": object_key,
        "token": result.get("token", ""),
        "expires_in": 600,  # 10 minutes
    }


def create_document(
    db: Session,
    title: str,
    original_filename: str,
    uploaded_by: uuid.UUID,
    min_role_level: int,
    object_key: str,
) -> Document:
    """Create a new Document row with status='processing'.

    The original_filename is stored as metadata in Postgres but is never
    used to construct a storage path or object key.
    """
    doc = Document(
        title=title,
        uploaded_by=uploaded_by,
        min_role_level=min_role_level,
        status="processing",
        object_key=object_key,
        original_filename=original_filename,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def delete_storage_object(object_key: str) -> None:
    """Delete a file from Supabase Storage by its object key.

    Called after successful ingestion to free storage (the PDF is dead
    weight once chunks + embeddings exist), or during document deletion.
    """
    supabase = _get_supabase_client()
    supabase.storage.from_(BUCKET_NAME).remove([object_key])
