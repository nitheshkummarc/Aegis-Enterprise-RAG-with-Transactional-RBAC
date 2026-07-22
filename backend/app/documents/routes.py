"""Document routes: upload, list, delete."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_role
from app.db.models import Document, User, UserRole
from app.db.session import get_db
from app.documents.schemas import DocumentResponse, DocumentUploadResponse
from app.documents.service import save_uploaded_file, create_document

router = APIRouter()


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_role(UserRole.admin))],
)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    min_role_level: int = Form(0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a PDF document for processing.

    Admin-only. Saves the file, creates a Document row with status='processing',
    pushes a Celery task, and returns 202 Accepted immediately.
    """
    # Validate min_role_level
    if min_role_level not in (0, 1, 2):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="min_role_level must be 0, 1, or 2",
        )

    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are accepted",
        )

    # Save file to disk
    file_content = await file.read()
    file_path = save_uploaded_file(file_content, file.filename)

    # Create document record
    doc = create_document(
        db=db,
        title=title,
        uploaded_by=current_user.id,
        min_role_level=min_role_level,
    )

    # Push Celery task (import here to avoid circular imports at module level)
    from app.ingestion.worker import ingest_document
    ingest_document.delay(str(doc.id), file_path)

    return DocumentUploadResponse(
        id=doc.id,
        title=doc.title,
        status=doc.status,
        message="Document uploaded and queued for processing",
    )


@router.get("/", response_model=list[DocumentResponse])
def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all documents."""
    docs = db.query(Document).all()
    return docs


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: str,
    current_user: User = Depends(require_role(UserRole.admin)),
    db: Session = Depends(get_db),
):
    """Delete a document and its chunks (cascade)."""
    import uuid as _uuid

    doc = db.query(Document).filter(Document.id == _uuid.UUID(document_id)).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    db.delete(doc)
    db.commit()
