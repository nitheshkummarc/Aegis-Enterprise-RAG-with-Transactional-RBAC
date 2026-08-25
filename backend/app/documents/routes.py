"""Document routes: presigned upload URL, confirm upload, list, delete.

Upload flow (2-step, presigned):
1. POST /documents/upload-url → returns a short-lived signed URL + object_key
2. Client uploads PDF directly to Supabase Storage using the signed URL
3. POST /documents/confirm-upload → creates Document row, queues Celery task

This keeps file bytes completely off the FastAPI server. The backend's only
role during upload is: authenticate the user, generate the signed URL,
and later record the metadata + queue ingestion.
"""

import logging
import re
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_role
from app.core.limiter import limiter
from app.db.models import Document, ROLE_LEVEL_MAP, User, UserRole
from app.db.session import get_db
from app.documents.schemas import DocumentResponse, DocumentUploadResponse
from app.documents.service import (
    generate_upload_url,
    create_document,
    delete_storage_object,
    MAX_FILE_SIZE_BYTES,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Regex for validating object keys match the expected UUID structure.
# Pattern: {uuid}/{uuid}/{uuid}.pdf
_OBJECT_KEY_PATTERN = re.compile(
    r"^[0-9a-f\-]{36}/[0-9a-f\-]{36}/[0-9a-f\-]{36}\.pdf$",
    re.IGNORECASE,
)


def _parse_uuid(value: str, field_name: str) -> _uuid.UUID:
    """Parse a string as UUID, raising HTTP 400 on invalid input."""
    try:
        return _uuid.UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid UUID for {field_name}: {value!r}",
        )


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class UploadUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(max_length=255)
    original_filename: str = Field(max_length=255)
    min_role_level: int = 0


class ConfirmUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(max_length=36)
    object_key: str = Field(max_length=200)
    title: str = Field(max_length=255)
    original_filename: str = Field(max_length=255)
    min_role_level: int = 0


class UploadUrlResponse(BaseModel):
    document_id: str
    signed_url: str
    token: str
    object_key: str
    expires_in: int
    max_file_size_bytes: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/upload-url",
    response_model=UploadUrlResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_role(UserRole.admin))],
)
@limiter.limit("10/minute")
def request_upload_url(
    request: Request,
    body: UploadUrlRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a presigned URL for direct client-to-Supabase upload.

    Admin-only. Rate-limited to 10 requests/minute per IP.
    The signed URL is scoped to a UUID-prefixed object key — no user input
    reaches the storage path. File size is capped server-side at 50 MB.
    """
    # Validate min_role_level
    if body.min_role_level not in (0, 1, 2):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="min_role_level must be 0, 1, or 2",
        )

    # Validate filename extension (metadata check only — filename never
    # reaches the storage path)
    if not body.original_filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are accepted",
        )

    # Create document record first so we have a DB-generated UUID
    doc = create_document(
        db=db,
        title=body.title,
        original_filename=body.original_filename,
        uploaded_by=current_user.id,
        min_role_level=body.min_role_level,
        object_key="",  # Will be updated after URL generation
    )

    # Roll back the Document row on failure — otherwise it's stuck at
    # status="processing" with no object_key and no task to ever process it.
    try:
        url_info = generate_upload_url(
            user_id=current_user.id,
            document_id=doc.id,
        )
    except Exception as e:
        logger.error("Failed to generate upload URL for document %s: %s", doc.id, e)
        db.delete(doc)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate upload URL. Please try again.",
        )

    # Update the document with the actual object key
    doc.object_key = url_info["object_key"]
    db.commit()

    return UploadUrlResponse(
        document_id=str(doc.id),
        signed_url=url_info["signed_url"],
        token=url_info["token"],
        object_key=url_info["object_key"],
        expires_in=url_info["expires_in"],
        max_file_size_bytes=MAX_FILE_SIZE_BYTES,
    )


@router.post(
    "/confirm-upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_role(UserRole.admin))],
)
def confirm_upload(
    body: ConfirmUploadRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Confirm that the client has finished uploading and queue ingestion.

    Called after the client successfully uploads the PDF to Supabase Storage
    using the signed URL. This endpoint verifies the document exists and
    pushes the Celery task with {document_id, object_key}.
    """
    doc_id = _parse_uuid(body.document_id, "document_id")

    # Validate object_key matches expected UUID-based pattern
    if not _OBJECT_KEY_PATTERN.match(body.object_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="object_key does not match expected pattern: {user_id}/{doc_id}/{uuid}.pdf",
        )

    doc = db.query(Document).filter(
        Document.id == doc_id,
        Document.uploaded_by == current_user.id,
    ).first()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found or not owned by current user",
        )

    if doc.status != "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document is already in state '{doc.status}'",
        )

    # Cross-check against the server-issued value, but always dispatch with
    # doc.object_key, not body.object_key — the request body is never trusted
    # for the actual storage path.
    if body.object_key != doc.object_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="object_key does not match the object_key issued for this document",
        )

    from app.ingestion.worker import ingest_document
    ingest_document.delay(str(doc.id), doc.object_key)

    return DocumentUploadResponse(
        id=doc.id,
        title=doc.title,
        status=doc.status,
        message="Upload confirmed and queued for processing",
    )


@router.get("/", response_model=list[DocumentResponse])
def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List documents visible at the current user's clearance level.

    Same rule as the chunk-level search in retrieval/search.py: a document
    is visible if min_role_level <= the user's role level.
    """
    user_role_level = ROLE_LEVEL_MAP.get(current_user.role, 0)
    docs = (
        db.query(Document)
        .filter(Document.min_role_level <= user_role_level)
        .all()
    )
    return docs


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: str,
    current_user: User = Depends(require_role(UserRole.admin)),
    db: Session = Depends(get_db),
):
    """Delete a document, its chunks (cascade), and its storage object."""
    doc_id = _parse_uuid(document_id, "document_id")

    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # Delete the PDF from Supabase Storage if an object_key exists
    if doc.object_key:
        try:
            delete_storage_object(doc.object_key)
        except Exception as e:
            logger.warning("Failed to delete storage object %s: %s", doc.object_key, e)

    db.delete(doc)
    db.commit()
