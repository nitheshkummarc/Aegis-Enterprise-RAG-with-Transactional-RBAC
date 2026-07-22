"""Document service layer."""

import os
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import Document, User


UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


def save_uploaded_file(file_content: bytes, filename: str) -> str:
    """Save uploaded file bytes to disk and return the file path."""
    # Create a unique filename to avoid collisions
    unique_name = f"{uuid.uuid4()}_{filename}"
    file_path = UPLOAD_DIR / unique_name
    file_path.write_bytes(file_content)
    return str(file_path)


def create_document(
    db: Session,
    title: str,
    uploaded_by: uuid.UUID,
    min_role_level: int,
) -> Document:
    """Create a new Document row with status='processing'."""
    doc = Document(
        title=title,
        uploaded_by=uploaded_by,
        min_role_level=min_role_level,
        status="processing",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc
